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
from cvd import update_token_cvd  # noqa: E402
from watchlist import load_watchlist  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main_pool(ca: str):
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                         timeout=20)
        pairs = (r.json() or {}).get("pairs") or []
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                   reverse=True)
        return pairs[0]["pairAddress"] if pairs else None
    except Exception:
        return None


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
    for ca, meta in wl.items():
        pool = main_pool(ca)
        if not pool:
            print(f"❌ {ca[:8]}… no pool found")
            continue
        try:
            res = update_token_cvd(api_key, ca, pool, max_pages=max_pages)
            gap = " ⚠️gap(pages exhausted)" if res["gap"] else ""
            print(f"✅ {meta.get('symbol', '?'):>10} {ca[:8]}… "
                  f"+{res['new_swaps']} swaps, {res['buckets']} hourly "
                  f"buckets{gap}")
        except Exception as e:
            print(f"❌ {ca[:8]}… {str(e)[:100]}")


if __name__ == "__main__":
    main()
