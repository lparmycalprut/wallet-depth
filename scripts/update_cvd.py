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


def _try_snapshot(api_keys, ca: str, meta: dict) -> str:
    """Holder snapshot via Helius (opsional). Return status string."""
    # Temporarily disabled
    return ""


def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    wl = load_watchlist()
    if not wl:
        print("Watchlist empty.")
        return

    # Helius keys hanya untuk holder snapshot (opsional)
    api_keys = tuple(get_helius_keys())

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
