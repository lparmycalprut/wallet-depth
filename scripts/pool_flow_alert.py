#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alert RINGKASAN Scan ALL (BEST POOL dan 4H ≥ 10 %), dijalankan tiap jam.

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


def run_summary(state: dict, *, scan=None, scan_4h=None) -> list[tuple[str, dict | None]]:
    """Kembalikan daftar (teks, reply_markup) yang akan dikirim: RINGKASAN saja (2026-11-18).

    Isi = ``pool_flow.summary_rows``: BEST POOL (HIGH RISK 12H dan DETEKSI 4H) dan
    4H ≥ 10 % avg volume/menit ÷ TVL. Tidak ada fetch per token.
    """
    result = (scan or pf.scan_pools)()
    result_4h = (scan_4h or pf.scan_4h)()
    print(f"12H: listing {result['listing_rows']} baris, dievaluasi {result['candidates']}, "
          f"lolos {len(result['passing'])}, error listing {result['listing_errors']}, "
          f"terpotong {result['truncated']}")
    print(f"4H: listing {result_4h['listing_rows']} baris, dievaluasi {result_4h['candidates']}, "
          f"tampil {len(result_4h['passing'])}, error listing {result_4h['listing_errors']}, "
          f"terpotong {result_4h['truncated']}")
    entries = pf.summary_rows(result, result_4h)
    text, markup = pf.apply_summary_alert(state, entries)
    if text is None:
        print("ringkasan: tidak ada pool yang memenuhi kriteria, tidak ada alert")
        return []
    best = sum(1 for _row, label in entries if label == pf.SUMMARY_BEST)
    print(f"ringkasan: {len(entries)} pool ({best} BEST POOL)")
    return [(text, markup)]


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default=None)
    args = parser.parse_args(argv)

    path = Path(args.state) if args.state else pf.STATE_PATH
    before = path.read_text(encoding="utf-8") if path.exists() else None
    state = pf.load_state(path)
    messages = run_summary(state)

    for text, markup in messages:
        ok, error = pf.send_telegram(text, reply_markup=markup)
        print("telegram:", "terkirim" if ok else f"gagal ({error})")
    pf.save_state(state, path)
    after = path.read_text(encoding="utf-8")
    if after != before:
        print("POOL_FLOW_CHANGED=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
