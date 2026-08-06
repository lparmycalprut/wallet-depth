# -*- coding: utf-8 -*-
"""Hourly CVD updater (GitHub Actions cron, scheduled at :30).

Sumber: **GMGN Token Trades API** (https://gmgn.ai) — tanpa API key, tanpa
rate-limit Helius. Fetch trade history per CA dari watchlist, konversi ke
CVD hourly buckets, dan commit ke cvd.json + conviction.json.

GMGN Trades endpoint:
  GET https://gmgn.ai/vas/api/v1/token_trades/sol/{ca}
  → field `event` (buy/sell), `quote_amount`/`amount_usd` → SOL-equivalent,
    `timestamp` → unix ts, `maker` → wallet address.

Usage: python scripts/update_cvd.py [max_pages]
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import (record_conviction, update_token_cvd,  # noqa: E402
                 get_gmgn_last_error, get_recent_swaps,
                 get_gmgn_wallet_metadata, WHALE_SOL)
from signals import detect_and_record, detect_prepump_and_record  # noqa: E402
from prepump_detector import compute_bullish_div  # noqa: E402
from watchlist import load_watchlist, save_watchlist  # noqa: E402


# ---------------------------------------------------------------------------
# Optional Helius fallback — hanya dipakai untuk holder snapshot (supply +
# holders), BUKAN untuk swap/CVD. Kalau Helius tidak ada, holder snapshot
# diskip — CVD tetap jalan penuh via GMGN.
# ---------------------------------------------------------------------------
try:
    from core import (get_helius_keys, get_holders, get_market,
                      get_supply)  # noqa: E402
except Exception:
    get_holders = None
    get_supply = None

    def get_helius_keys():
        """Return no Helius keys if the optional core import is unavailable."""
        return ()

    def get_market(_ca):
        """Fallback when the optional core import is unavailable."""
        return {}


def main_pool(ca: str):
    """Resolve the queried token's canonical DexScreener pool and metadata."""
    try:
        market = get_market(ca)
        pools = market.get("pair_addresses") or []
        if not market or not pools:
            return None, None, None
        return (pools[0], float(market.get("price_usd") or 0),
                market.get("symbol") or "?")
    except Exception:
        return None, None, None


# ---------------------------------------------------------------------------
# Holder snapshot — Fix #2.7 (was: "Temporarily disabled")
#
# We try in order:
#   1. Helius (if a key is configured) — gives the full holder list
#   2. GMGN token_stat (free, no key) — gives top-10 only, which is
#      enough to seed `holder_delta()` for top-tier (whale) movement.
#
# Either path produces a snapshot that `holder_delta()` can compare
# against on the next cron run. The Helius path is preferred because
# GMGN only exposes the top-10 holders (so tier classification for
# tokens with many holders collapses into "all top-10 are whales",
# which inflates the whale count but is still useful for delta).
# ---------------------------------------------------------------------------
def _gmgn_top_holders(ca: str, timeout: int = 15) -> tuple:
    """Return (holders_list, supply) from GMGN token_stat, or (None, None).

    Thin wrapper around :func:`core.gmgn_token_stat` so the cron has
    a single source of truth (the new function is also reused by the
    trending screener for its real/dust approximation). Behaviour is
    identical to the previous in-file implementation.
    """
    from core import gmgn_token_stat
    stat = gmgn_token_stat(ca, timeout=timeout)
    return (stat.get("holders") or None), stat.get("supply")


def _cron_dust_limit() -> float:
    """Dust threshold (USD) for the hourly real-vs-dust recording.

    Mirrors the dashboard's ``dust_limit_usd`` config value so the cron
    history and the live card use the same split. Defaults to $5.
    """
    try:
        import json as _json
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            return float((_json.load(f) or {}).get("dust_limit_usd", 5.0))
    except Exception:
        return 5.0


def _try_snapshot(api_keys, ca: str, meta: dict,
                  price_now: float = 0.0) -> str:
    """Holder snapshot — Helius (preferred) → GMGN (fallback).

    Returns a short status string for the cron log:
      " snap-helius:1234 holders" — Helius path
      " snap-gmgn:10 holders"     — GMGN top-10 only
      " snap-skip:<reason>"       — both failed, snapshot skipped

    The snapshot is committed to holder_snapshots.json so that
    `holder_delta()` can compute true T0↔T1 holdings change on
    subsequent runs.

    On the Helius path we ALSO commit one real-vs-dust history point
    (``real_dust_history.json``) — the holder list is already fetched,
    so the growth chart rides along at zero extra RPC cost.
    """
    from cvd import record_holder_snapshot, record_real_dust_point

    # ── 1) Helius path (preferred when keys are configured) ───────────
    if api_keys and get_holders is not None:
        try:
            df = get_holders(api_keys, ca)
            if df is not None and not df.empty:
                if get_supply is not None:
                    try:
                        supply, _ = get_supply(api_keys, ca)
                    except Exception:
                        supply = 0.0
                else:
                    supply = 0.0
                # normalize to [owner, ui_amount] pairs
                pairs = []
                amt_col = ("ui_amount" if "ui_amount" in df.columns
                           else "raw_amount")
                for _, row in df.iterrows():
                    owner = row.get("owner")
                    amt = row.get(amt_col)
                    if owner and amt and float(amt) > 0:
                        pairs.append([str(owner), float(amt)])
                if pairs:
                    rec = record_holder_snapshot(ca, pairs, supply or 0.0)
                    # Real-vs-dust history point — full list only (never
                    # the GMGN top-10 fallback). Dedup'd hourly by the
                    # recorder, so cron retries don't double-commit.
                    rd_txt = ""
                    try:
                        limit = _cron_dust_limit()
                        if price_now and price_now > 0:
                            n_real = sum(1 for _, amt in pairs
                                         if amt * price_now >= limit)
                            n_dust = len(pairs) - n_real
                            pt = record_real_dust_point(
                                ca, n_real, n_dust, price=price_now,
                                dust_limit=limit)
                            if pt is not None:
                                rd_txt = f" rd:{n_real}r/{n_dust}d"
                    except Exception:
                        pass  # history is best-effort, never crash cron
                    return f" snap-helius:{len(pairs)} holders{rd_txt}"
        except Exception as e:
            # fall through to GMGN; don't crash the cron
            print(f"WARN: helius holder snapshot failed for {ca}: {e}")

    # ── 2) GMGN path (no key needed) ──────────────────────────────────
    try:
        holders, supply = _gmgn_top_holders(ca)
        if holders:
            rec = record_holder_snapshot(ca, holders, supply or 0.0)
            if rec is not None:
                return f" snap-gmgn:{len(holders)} holders"
    except Exception:
        pass

    return " snap-skip:no-source"


def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    wl = load_watchlist()
    if not wl:
        print("Watchlist empty.")
        return

    # Helius keys hanya untuk holder snapshot (opsional)
    api_keys = tuple(get_helius_keys())

    # FOCUS_MODE: log once at start so the cron output is clear about
    # what gets Telegram-notified (Tier 1 only) vs not.
    try:
        import json as _json
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "config.json"),
                  "r", encoding="utf-8") as _f:
            _cfg = _json.load(_f) or {}
    except Exception:
        _cfg = {}
    _focus_mode = bool(_cfg.get("focus_mode", True))
    if _focus_mode:
        print("🎯 FOCUS_MODE: Telegram Tier 1 only "
              "(accumulation, stealth_accumulation, distribution). "
              "Divergence → signals.json only (no Telegram).")
    else:
        print("📡 FOCUS_MODE: OFF — all signal types to Telegram.")

    wl_changed = False
    for ca, meta in list(wl.items()):
        try:
            pool, price_now, live_sym = main_pool(ca)
            if not pool:
                print(f"❌ {ca[:8]}… no pool found")
                continue

            # auto-fix missing symbols
            if (meta.get("symbol") in (None, "", "?")) and live_sym and \
                    live_sym != "?":
                meta["symbol"] = live_sym
                wl_changed = True

            # ── CVD via GMGN ──────────────────────────────────────────
            res = update_token_cvd(
                api_keys, ca, pool, max_pages=max_pages, use_gmgn=True)
            gap = " ⚠️gap(pages exhausted)" if res["gap"] else ""

            gmgn_err = res.get("error") or get_gmgn_last_error()
            if not res.get("fetch_ok", True):
                # Partial-walk recovery: if partial with coverage_from ≤ now-4h,
                # continue recording conviction + signals; else skip as usual.
                coverage_from = res.get("coverage_from")
                partial_ok = (res.get("partial") and coverage_from is not None
                              and (time.time() - coverage_from) <= 4 * 3600)
                if partial_ok:
                    # Partial result covers at least last 4h → safe to record.
                    pass  # fall through to conviction/signals
                else:
                    detail = gmgn_err or "GMGN fetch incomplete"
                    print(f"⚠️ {meta.get('symbol', '?'):>10} {ca[:8]}… "
                          f"CVD not updated: {detail[:120]}")
                    continue
            if gmgn_err and res["new_swaps"] == 0:
                gap += f" gmgn:{gmgn_err[:60]}"

            # ── Signals + conviction ───────────────────────────────────
            sigs = detect_and_record(ca, meta.get("symbol", "?"),
                                     src="cron", window_h=4,
                                     price_now=price_now, pool=pool)
            cp = record_conviction(ca, window_h=4)
            # Independent monitor alerts: all four indicators move together,
            # or TX/volume jumps at least 5x between four-hour bins
            # (vs the previous bin or the median of the 4 bins before).
            from signals import detect_growth_alerts
            sigs.extend(detect_growth_alerts(ca, meta.get("symbol", "?"), cp))
            conv_txt = (f" conv={cp['conviction']:.0f}%" if cp else "")
            sig_txt = (" 🔔 " + ",".join(sigs)) if sigs else ""

            # ── Breakout Guard ────────────────────────────────────────
            guard_txt = ""
            try:
                from breakout_guard import run_guard
                alerts = run_guard(ca, meta.get("symbol", "?"), pool,
                                   price_now)
                if alerts:
                    guard_txt = " 🚨" + ",".join(a[2] for a in alerts)
            except Exception as ge:
                guard_txt = f" guard-err:{str(ge)[:40]}"

            # ── Liquidity Test TX ─────────────────────────────────────
            liq_test_txt = ""
            try:
                from cvd import get_recent_swaps, get_sol_price
                from breakout_guard import send_telegram
                from signals import load_signals, save_signals
                
                swaps_4h = get_recent_swaps(ca, hours=4)
                sol_price = get_sol_price()
                vol_sol_4h = sum(float(s[1]) for s in swaps_4h)
                vol_usd_4h = vol_sol_4h * sol_price
                
                if vol_usd_4h <= 10000.0:
                    wallet_swaps = {}
                    for s in swaps_4h:
                        if len(s) < 4:
                            continue
                        side, sol, ts, wallet = s[0], float(s[1]), int(s[2]), str(s[3])
                        wallet_swaps.setdefault(wallet, []).append((side, sol, ts))
                        
                    test_wallets = []
                    for wallet, txs in wallet_swaps.items():
                        txs.sort(key=lambda x: x[2])
                        has_test = False
                        for i in range(len(txs)):
                            for j in range(i + 1, len(txs)):
                                side_i, sol_i, ts_i = txs[i]
                                side_j, sol_j, ts_j = txs[j]
                                
                                if side_i != side_j:
                                    if abs(ts_i - ts_j) <= 900:  # within 15 minutes
                                        if sol_i <= 1.0 and sol_j <= 1.0:  # both <= 1.0 SOL
                                            has_test = True
                                            break
                            if has_test:
                                break
                        if has_test:
                            test_wallets.append(wallet)
                    
                    if len(test_wallets) > 5:
                        sigs = load_signals()
                        now = int(time.time())
                        already_sent = False
                        for s in reversed(sigs[-200:]):
                            if s.get("ca") == ca and s.get("type") == "liquidity_test_tx" and now - (s.get("ts") or 0) < 4 * 3600:
                                already_sent = True
                                break
                        if not already_sent:
                            sym = meta.get("symbol", "?")
                            msg = (
                                f"🚨 <b>LIQUIDITY TEST TX ALERT</b> 🚨\n\n"
                                f"Token: <b>{sym}</b>\n"
                                f"CA: <code>{ca}</code>\n"
                                f"Volume 4H Terakhir: <b>${vol_usd_4h:,.2f}</b> (&lt;= $10K)\n"
                                f"Unique Wallets melakukan test: <b>{len(test_wallets)}</b> (&gt; 5)\n\n"
                                f"<b>Rekap Wallet (Hyperlink Solscan):</b>\n"
                            )
                            for idx, w in enumerate(test_wallets[:10], 1):
                                msg += f"{idx}. <a href='https://solscan.io/account/{w}'>{w[:8]}...{w[-4:]}</a>\n"
                            if len(test_wallets) > 10:
                                msg += f"...dan {len(test_wallets) - 10} wallet lainnya\n"
                                
                            msg += f"\nLink: <a href='https://dexscreener.com/solana/{ca}'>DexScreener</a> | <a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>"
                            
                            send_telegram(msg)
                            sigs.append({
                                "ts": now,
                                "ca": ca,
                                "symbol": sym,
                                "type": "liquidity_test_tx",
                                "src": "cron",
                                "detail": f"Volume 4H: ${vol_usd_4h:,.2f}, {len(test_wallets)} test wallets"
                            })
                            save_signals(sigs)
                            liq_test_txt = f" 🧪test_tx:{len(test_wallets)}w"
            except Exception as e_lt:
                liq_test_txt = f" 🧪test_err:{str(e_lt)[:20]}"

            # ── Holder snapshot + real/dust history (Helius opsional) ──
            snap_txt = _try_snapshot(api_keys, ca, meta,
                                     price_now=price_now or 0.0)

            # ── Pre-Pump Radar ──────────────────────────────────────────
            pp_txt = ""
            try:
                _swaps_pp = get_recent_swaps(ca, hours=1)
                _wmeta = get_gmgn_wallet_metadata()
                _bull = compute_bullish_div(ca, pool) if pool else False
                _mc = (get_market(ca) or {}).get("marketcap")
                _tinfo = {"symbol": meta.get("symbol", "?"),
                          "price_usd": price_now, "mc": _mc}
                _pp = detect_prepump_and_record(
                    ca, meta.get("symbol", "?"), _swaps_pp,
                    token_info=_tinfo, now_ts=int(time.time()),
                    window_min=30, whale_min_sol=WHALE_SOL,
                    wallet_tags=_wmeta, bullish_div=_bull)
                if _pp:
                    pp_txt = " 🎯prepump:%s/%d" % (_pp["tier"], int(_pp["score"]))
            except Exception as e_pp:
                pp_txt = " 🎯prepump_err:%s" % str(e_pp)[:20]

            print(f"✅ {meta.get('symbol', '?'):>10} {ca[:8]}… "
                  f"+{res['new_swaps']} swaps, {res['buckets']} hourly "
                  f"buckets{gap}{conv_txt}{sig_txt}{guard_txt}{snap_txt}"
                  f"{liq_test_txt}{pp_txt}")

        except Exception as e:
            print(f"❌ {ca[:8]}… unhandled error: {str(e)[:100]}")

    # ── Retry pending Telegram alerts ────────────────────────────────────
    try:
        from breakout_guard import flush_pending_alerts
        n_retry = flush_pending_alerts()
        if n_retry:
            print(f"🔁 re-sent {n_retry} pending alert(s)")
    except Exception as e:
        print(f"retry-err: {str(e)[:80]}")

    if wl_changed:
        save_watchlist(wl, "auto-fix symbols")
        print("watchlist symbols updated")


if __name__ == "__main__":
    main()
