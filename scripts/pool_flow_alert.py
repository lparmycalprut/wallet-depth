#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alert Scan Best Pool (net deposit).

Pemakaian:
    python3 scripts/pool_flow_alert.py --mode best    # tiap 30 menit
    python3 scripts/pool_flow_alert.py --mode watch   # tiap 10 menit

Keluaran: mencetak ``POOL_FLOW_CHANGED=1`` bila ``pool_flow_state.json`` berubah,
supaya workflow hanya meng-commit saat perlu.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pool_flow as pf  # noqa: E402


def run_best(state: dict, *, scan=None) -> list[str]:
    result = (scan or pf.scan_candidates)()
    pf.record_scan(state, result["results"], ts=result["scanned_at"])
    text = pf.apply_best_alert(state, result["passing"])
    print(f"best: listing {result['listing_rows']} baris, kandidat {result['candidates']}, "
          f"lolos {len(result['passing'])}, error listing {result['listing_errors']}")
    return [text] if text else []


def run_watch(state: dict, *, fetch=None) -> list[str]:
    checks = []
    for item in state["watchlist"]:
        nets = {}
        for window in ("1h", "4h"):
            try:
                row = (fetch or pf.pool_row_for_window)(item["mint"], item["pool"], window)
            except Exception:  # noqa: BLE001 — satu pool gagal tidak menghentikan yang lain
                row = None
            nets[window] = pf.net_of(row)
        checks.append({"pool": item["pool"], "mint": item["mint"],
                       "symbol": item["symbol"], "nets": nets})
        pf.record_snapshot(state, item["pool"], nets)
    print(f"watch: {len(checks)} pool dicek")
    return pf.watch_transition_alerts(state, checks)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("best", "watch"), required=True)
    parser.add_argument("--state", default=None)
    args = parser.parse_args(argv)

    path = Path(args.state) if args.state else pf.STATE_PATH
    before = path.read_text(encoding="utf-8") if path.exists() else None
    state = pf.load_state(path)
    messages = run_best(state) if args.mode == "best" else run_watch(state)

    for text in messages:
        ok, error = pf.send_telegram(text)
        print("telegram:", "terkirim" if ok else f"gagal ({error})")
    pf.save_state(state, path)
    after = path.read_text(encoding="utf-8")
    if after != before:
        print("POOL_FLOW_CHANGED=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
