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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from cvd import (record_conviction, update_token_cvd,  # noqa: E402
                 get_gmgn_last_error)
from signals import detect_and_record  # noqa: E402
from watchlist import load_watchlist, save_watchlist  # noqa: E402


# ---------------------------------------------------------------------------
# Optional Helius fallback — hanya dipakai untuk holder snapshot (supply +
# holders), BUKAN untuk swap/CVD. Kalau Helius tidak ada, holder snapshot
# diskip — CVD tetap jalan penuh via GMGN.
# ---------------------------------------------------------------------------
try:
    from core import get_helius_keys, get_holders, get_supply  # noqa: E402
except Exception:
    get_helius_keys = lambda: ()
    get_holders = None
    get_supply = None


def main_pool(ca: str):
    """Cari main pool address + price + symbol dari DexScreener."""
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
            timeout=20)
        pairs = (r.json() or {}).get("pairs") or []
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                   reverse=True)
        if not pairs:
            return None, None, None
        b = pairs[0]
        return (b["pairAddress"], float(b.get("priceUsd") or 0),
                (b.get("baseToken") or {}).get("symbol") or "?")
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

    ``holders_list`` is a list of ``[owner, ui_amount]`` pairs (largest
    first). ``supply`` is the float total supply if GMGN reports it.
    """
    try:
        from curl_cffi import requests as cr
        r = cr.get(
            f"https://gmgn.ai/api/v1/token_stat/sol/{ca}",
            headers={
                "accept": "application/json, text/plain, */*",
                "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/150.0.0.0 Safari/537.36"),
            },
            impersonate="chrome", timeout=timeout)
    except ImportError:
        r = requests.get(
            f"https://gmgn.ai/api/v1/token_stat/sol/{ca}",
            headers={
                "accept": "application/json, text/plain, */*",
                "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/150.0.0.0 Safari/537.36"),
            },
            timeout=timeout)
    if r.status_code != 200:
        return None, None
    try:
        data = r.json() or {}
    except Exception:
        return None, None
    if not isinstance(data, dict):
        return None, None

    # ── holders list (top-10 typically) ─────────────────────────────────
    holders = []
    for h in (data.get("holders") or []):
        if not isinstance(h, dict):
            continue
        addr = h.get("address") or h.get("owner")
        amt = h.get("amount") or h.get("ui_amount") or h.get("balance")
        try:
            amt_f = float(amt)
        except (TypeError, ValueError):
            continue
        if addr and amt_f > 0:
            holders.append([str(addr), float(amt_f)])

    # Some GMGN responses put the holders under nested paths — try
    # alternate keys before giving up.
    if not holders:
        for key in ("top10_holders", "top_holders", "top_holder",
                    "top_10_holders"):
            alt = data.get(key)
            if isinstance(alt, list):
                for h in alt:
                    if not isinstance(h, dict):
                        continue
                    addr = h.get("address") or h.get("owner")
                    amt = h.get("amount") or h.get("ui_amount")
                    try:
                        amt_f = float(amt)
                    except (TypeError, ValueError):
                        continue
                    if addr and amt_f > 0:
                        holders.append([str(addr), float(amt_f)])
                if holders:
                    break

    # ── supply (try several known fields) ──────────────────────────────
    supply = None
    for key in ("total_supply", "supply", "totalSupply", "total"):
        try:
            v = float(data.get(key) or 0)
            if v > 0:
                supply = v
                break
        except (TypeError, ValueError):
            continue
    return (holders or None), supply


def _try_snapshot(api_keys, ca: str, meta: dict) -> str:
    """Holder snapshot — Helius (preferred) → GMGN (fallback).

    Returns a short status string for the cron log:
      " snap-helius:1234 holders" — Helius path
      " snap-gmgn:10 holders"     — GMGN top-10 only
      " snap-skip:<reason>"       — both failed, snapshot skipped

    The snapshot is committed to holder_snapshots.json so that
    `holder_delta()` can compute true T0↔T1 holdings change on
    subsequent runs.
    """
    from cvd import record_holder_snapshot

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
                    if rec is not None:
                        return f" snap-helius:{len(pairs)} holders"
        except Exception as e:
            # fall through to GMGN; don't crash the cron
            pass

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

            gmgn_err = get_gmgn_last_error()
            if gmgn_err and res["new_swaps"] == 0:
                gap += f" gmgn:{gmgn_err[:60]}"

            # ── Signals + conviction ───────────────────────────────────
            sigs = detect_and_record(ca, meta.get("symbol", "?"),
                                     src="cron", window_h=6,
                                     price_now=price_now, pool=pool)
            cp = record_conviction(ca, window_h=6)
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

            # ── Holder snapshot (Helius opsional) ─────────────────────
            snap_txt = _try_snapshot(api_keys, ca, meta)

            print(f"✅ {meta.get('symbol', '?'):>10} {ca[:8]}… "
                  f"+{res['new_swaps']} swaps, {res['buckets']} hourly "
                  f"buckets{gap}{conv_txt}{sig_txt}{guard_txt}{snap_txt}")

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
