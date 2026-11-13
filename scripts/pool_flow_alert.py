#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alert pool paling ramai Scan Best Pool (volume 4H), dijalankan tiap 4 jam.

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


def run_best(state: dict, *, scan=None) -> list[tuple[str, dict | None]]:
    """Kembalikan daftar (teks, reply_markup) yang akan dikirim.

    Hanya satu pool: yang volume 4H pool-nya paling besar di antara pool yang lolos.
    Bila volume 4H tidak bisa diambil, kirim peringatan singkat dan state tidak berubah.
    """
    result = (scan or pf.scan_pools)()
    print(f"best: listing {result['listing_rows']} baris, dievaluasi {result['candidates']}, "
          f"lolos {len(result['passing'])}, error listing {result['listing_errors']}, "
          f"terpotong {result['truncated']}")
    if not result["passing"]:
        return []
    pf.enrich_scan_result(result)
    top = pf.most_crowded(result)
    if top is None:
        print("best: volume 4H tidak tersedia, peringatan dikirim")
        return [(pf.crowded_unavailable_text(len(result["passing"])), None)]
    text = pf.apply_crowded_alert(state, top)
    print(f"best: pool paling ramai {top['symbol']} ({top['pool']})")
    return [(text, pf.alert_copy_markup([top["row"]]))]


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default=None)
    args = parser.parse_args(argv)

    path = Path(args.state) if args.state else pf.STATE_PATH
    before = path.read_text(encoding="utf-8") if path.exists() else None
    state = pf.load_state(path)
    messages = run_best(state)

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
