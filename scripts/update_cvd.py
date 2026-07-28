# -*- coding: utf-8 -*-
"""4-hourly CVD updater (GitHub Actions cron).

For every CA in the watchlist, incrementally fetches new swaps from the
main pool via Helius Enhanced API and appends hourly buy/sell buckets to
cvd.json. Run every 4 hours so even very active tokens stay within a
reasonable number of requests per run.

Usage: HELIUS_API_KEY=xxx python scripts/update_cvd.py [max_pages]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from cvd import update_token_cvd, record_conviction  # noqa: E402
from signals import detect_and_record  # noqa: E402
from watchlist import load_watchlist  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main_pool(ca: str):
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
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


def main():
    api_key = os.environ.get("HELIUS_API_KEY", "").strip()
    if not api_key:
        try:
            with open(os.path.join(BASE_DIR, "config.json")) as f:
                api_key = (json.load(f) or {}).get("helius_api_key", "")
        except Exception:
            pass
    if not api_key:
        sys.exit("HELIUS_API_KEY missing")

    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    wl = load_watchlist()
    if not wl:
        print("Watchlist empty.")
        return
    wl_changed = False
    for ca, meta in wl.items():
        pool, price_now, live_sym = main_pool(ca)
        if not pool:
            print(f"❌ {ca[:8]}… no pool found")
            continue
        # auto-fix missing symbols
        if (meta.get("symbol") in (None, "", "?")) and live_sym and \
                live_sym != "?":
            meta["symbol"] = live_sym
            wl_changed = True
        try:
            res = update_token_cvd(api_key, ca, pool, max_pages=max_pages)
            gap = " ⚠️gap(pages exhausted)" if res["gap"] else ""
            sigs = detect_and_record(ca, meta.get("symbol", "?"),
                                     src="cron", window_h=6,
                                     price_now=price_now, pool=pool)
            cp = record_conviction(ca, window_h=6)
            conv_txt = (f" conv={cp['conviction']:.0f}%" if cp else "")
            sig_txt = (" 🔔 " + ",".join(sigs)) if sigs else ""
            # Breakout Guard: level tracking + on-chain diagnosed alerts
            guard_txt = ""
            try:
                from breakout_guard import run_guard
                alerts = run_guard(ca, meta.get("symbol", "?"), pool,
                                   price_now)
                if alerts:
                    guard_txt = " 🚨" + ",".join(a[2] for a in alerts)
            except Exception as ge:
                guard_txt = f" guard-err:{str(ge)[:40]}"
            print(f"✅ {meta.get('symbol', '?'):>10} {ca[:8]}… "
                  f"+{res['new_swaps']} swaps, {res['buckets']} hourly "
                  f"buckets{gap}{conv_txt}{sig_txt}{guard_txt}")
        except Exception as e:
            print(f"❌ {ca[:8]}… {str(e)[:100]}")
    if wl_changed:
        from watchlist import save_watchlist
        save_watchlist(wl, "auto-fix symbols")
        print("watchlist symbols updated")


if __name__ == "__main__":
    main()
