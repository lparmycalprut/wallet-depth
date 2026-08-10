"""Scan priority watchlist tokens every 15 minutes for GMGN trade bursts."""
import json
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cvd import fetch_swaps
from cvd_daily import priority_spike
from signals import record_priority_spike
from watchlist import load_watchlist


def _thresholds():
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"), encoding="utf-8") as f:
            cfg = json.load(f) or {}
    except Exception:
        cfg = {}
    return float(cfg.get("priority_min_tx", 500)), float(cfg.get("priority_min_volume_sol", 500))


def main():
    min_tx, min_volume = _thresholds()
    now = int(time.time())
    for ca, meta in load_watchlist().items():
        if not meta.get("priority"):
            continue
        try:
            swaps, _, _, _ = fetch_swaps("", "", ca, stop_ts=now - 15 * 60,
                                         max_pages=10, sleep=0.1, use_gmgn=True)
            stats = priority_spike(swaps, min_tx=min_tx, min_volume_sol=min_volume)
            if stats["triggered"]:
                sent = record_priority_spike(ca, meta.get("symbol", "?"), stats)
                print(f"🚨 {meta.get('symbol', '?')} {stats['tx']} tx / {stats['volume_sol']:.2f} SOL sent={sent}")
            else:
                print(f"· {meta.get('symbol', '?')} {stats['tx']} tx / {stats['volume_sol']:.2f} SOL")
        except Exception as exc:
            print(f"⚠️ {ca[:8]}… {exc}")


if __name__ == "__main__":
    main()
