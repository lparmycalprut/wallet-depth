#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alert RINGKASAN Scan ALL (pool dari SLOW FEE PRINTER), dijalankan tiap jam.

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


def run_summary(state: dict, *, scan=None) -> list[tuple[str, dict | None]]:
    """Kembalikan daftar (teks, reply_markup) yang akan dikirim: RINGKASAN saja (2026-11-20).

    Isi = ``pool_flow.summary_rows``: pool dari tabel SLOW FEE PRINTER saja.
    Tidak ada fetch per token dan tidak ada scan 4H (bagian Deteksi 4H dihapus 2026-11-20).
    """
    result = (scan or pf.scan_pools)()
    print(f"12H: listing {result['listing_rows']} baris, dievaluasi {result['candidates']}, "
          f"lolos {len(result['passing'])}, error listing {result['listing_errors']}, "
          f"terpotong {result['truncated']}")
    entries = pf.summary_rows(result)
    text, markup = pf.apply_summary_alert(state, entries)
    if text is None:
        print("ringkasan: tidak ada pool yang memenuhi kriteria, tidak ada alert")
        return []
    print(f"ringkasan: {len(entries)} pool (FEE PRINTER)")
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
