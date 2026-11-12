#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alert pool terbaik Scan Best Pool (timeframe 12H), dijalankan tiap 30 menit.

Pemakaian:
    python3 scripts/pool_flow_alert.py [--state berkas.json]

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
    result = (scan or pf.scan_pools)()
    text = pf.apply_best_alert(state, result["passing"])
    print(f"best: listing {result['listing_rows']} baris, dievaluasi {result['candidates']}, "
          f"lolos {len(result['passing'])}, error listing {result['listing_errors']}, "
          f"terpotong {result['truncated']}")
    return [text] if text else []


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default=None)
    args = parser.parse_args(argv)

    path = Path(args.state) if args.state else pf.STATE_PATH
    before = path.read_text(encoding="utf-8") if path.exists() else None
    state = pf.load_state(path)
    messages = run_best(state)

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
