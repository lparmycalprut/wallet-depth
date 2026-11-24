#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alert RINGKASAN Scan ALL (pool dari FEE PRINTER), dijalankan tiap 15 menit.

Pemakaian:
    python3 scripts/pool_flow_alert.py [--state berkas.json]

Aturan (permintaan user, 2026-11-24):
- Ada pool FEE PRINTER: kirim RINGKASAN, state disimpan.
- Tidak ada pool: kirim pesan heartbeat supaya user tahu cron jalan. State tidak berubah.
- Scan gagal: kirim pesan error, exit 1.
- Telegram gagal atau kredensial kosong: exit 1 dan state TIDAK disimpan,
  supaya alert tidak dianggap sudah terkirim.

Keluaran: mencetak ``POOL_FLOW_CHANGED=1`` bila ``pool_flow_state.json`` ditulis ulang
(hanya saat ada alert baru), supaya workflow hanya meng-commit saat perlu.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pool_flow as pf  # noqa: E402


def run_summary(state: dict, *, scan=None) -> list[tuple[str, dict | None]]:
    """Daftar (teks, reply_markup) yang akan dikirim. Selalu berisi tepat satu pesan.

    Ada pool FEE PRINTER: RINGKASAN (``pool_flow.summary_rows``). Tidak ada: heartbeat.
    ``apply_summary_alert`` hanya mengubah ``state`` in-memory; penyimpanan dilakukan di ``main``
    setelah pengiriman berhasil.
    """
    result = (scan or pf.scan_pools)()
    print(f"24H: listing {result['listing_rows']} baris, dievaluasi {result['candidates']}, "
          f"lolos {len(result['passing'])}, error listing {result['listing_errors']}, "
          f"terpotong {result['truncated']}")
    entries = pf.summary_rows(result)
    text, markup = pf.apply_summary_alert(state, entries)
    if text is None:
        print("ringkasan: 0 pool FEE PRINTER, kirim heartbeat")
        return [(pf.heartbeat_text(result), None)]
    print(f"ringkasan: {len(entries)} pool (FEE PRINTER)")
    if result.get("listing_errors") or result.get("truncated"):
        text += "\n⚠️ listing belum lengkap (error atau terpotong), daftar mungkin belum menyeluruh"
    return [(text, markup)]


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default=None)
    args = parser.parse_args(argv)

    if not (os.environ.get(pf.ENV_TOKEN) or "").strip() or not (os.environ.get(pf.ENV_CHAT) or "").strip():
        print(f"telegram: kredensial belum dipasang ({pf.ENV_TOKEN} / {pf.ENV_CHAT}), "
              "alert tidak bisa dikirim. State tidak disimpan.")
        return 1

    path = Path(args.state) if args.state else pf.STATE_PATH
    state = pf.load_state(path)
    before = json.dumps(state, sort_keys=True)

    scan_failed = False
    try:
        messages = run_summary(state)
    except Exception as exc:  # noqa: BLE001 — harus tetap memberi tahu user
        scan_failed = True
        print(f"scan gagal: {exc}")
        messages = [(pf.heartbeat_text(error=str(exc) or type(exc).__name__), None)]

    all_sent = True
    for text, markup in messages:
        ok, error = pf.send_telegram(text, reply_markup=markup)
        print("telegram:", "terkirim" if ok else f"gagal ({error})")
        all_sent = all_sent and ok
    if not all_sent:
        print("pengiriman gagal: state tidak disimpan, alert akan dicoba lagi")
        return 1
    if scan_failed:
        return 1

    # State hanya ditulis bila ada alert baru (heartbeat tidak mengubah state).
    if json.dumps(state, sort_keys=True) != before:
        pf.save_state(state, path)
        print("POOL_FLOW_CHANGED=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
