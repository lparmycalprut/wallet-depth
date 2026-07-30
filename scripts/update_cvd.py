# -*- coding: utf-8 -*-
"""Hourly CVD updater (GitHub Actions cron, scheduled at minute :20).

For every CA in the watchlist, incrementally fetches new swaps from the
main pool via Helius Enhanced API and appends hourly buy/sell buckets to
cvd.json. Incremental signatures keep each hourly run bounded even for
active tokens.

Usage: HELIUS_API_KEY=xxx python scripts/update_cvd.py [max_pages]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from core import get_helius_keys, get_holders, get_supply  # noqa: E402
from cvd import (record_holder_snapshot, record_conviction,  # noqa: E402
                 update_token_cvd)
from signals import detect_and_record  # noqa: E402
from watchlist import load_watchlist  # noqa: E402


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
    api_keys = tuple(get_helius_keys())
    if not api_keys:
        sys.exit("HELIUS_API_KEY(S) missing (env, config.json, or secrets)")

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
            res = update_token_cvd(api_keys, ca, pool, max_pages=max_pages)
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
            # Holder snapshot — commits at most every 6h (controlled by
            # cvd.SNAPSHOT_MIN_GAP_S), so on a 4h cron this writes every
            # other run. Adds 1 extra Helius call per snapshot but the
            # store stays small and gives the dashboard a real
            # whale/dolphin holdings delta instead of swap-flow proxy.
            snap_txt = ""
            try:
                _supply, _dec = get_supply(api_keys, ca)
                _hd = get_holders(api_keys, ca)
                if _hd is not None and not _hd.empty and _dec:
                    _hd["ui_amount"] = _hd["raw_amount"] / (10 ** _dec)
                    _hd = _hd[_hd["ui_amount"] > 0]
                    # LP wallets get filtered in `snapshot_one` (history)
                    # but the LP set isn't on hand here; rely on the
                    # pair_addresses filter the snapshot_one path uses
                    # too. For the live CVD we keep them in (cheap).
                    _point = record_holder_snapshot(
                        ca, _hd[["owner", "ui_amount"]].values.tolist(),
                        supply=float(_supply))
                    if _point is not None:
                        snap_txt = (f" 📸snap={_point['ts'] // 3600}h "
                                    f"({len(_point['holders'])} h)")
                    else:
                        snap_txt = " 📸snap=skipped(recent)"
            except Exception as se:
                snap_txt = f" snap-err:{str(se)[:40]}"
            print(f"✅ {meta.get('symbol', '?'):>10} {ca[:8]}… "
                  f"+{res['new_swaps']} swaps, {res['buckets']} hourly "
                  f"buckets{gap}{conv_txt}{sig_txt}{guard_txt}{snap_txt}")
        except Exception as e:
            print(f"❌ {ca[:8]}… {str(e)[:100]}")
    # Retry any guard alert whose Telegram send failed on an earlier run —
    # the message text is cached in breakouts.json until it is delivered.
    try:
        from breakout_guard import flush_pending_alerts
        n_retry = flush_pending_alerts()
        if n_retry:
            print(f"🔁 re-sent {n_retry} pending alert(s)")
    except Exception as e:
        print(f"retry-err: {str(e)[:80]}")

    if wl_changed:
        from watchlist import save_watchlist
        save_watchlist(wl, "auto-fix symbols")
        print("watchlist symbols updated")


if __name__ == "__main__":
    main()
