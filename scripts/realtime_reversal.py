#!/usr/bin/env python3
"""Adapter cron lama → Silent Accumulation 12H Scanner.

Seluruh sinyal (SMART SEROK / reversal / effort bottom) dan notifikasi
Telegram sudah dihapus dari repo. File ini hanya jembatan kompatibilitas:
workflow GitHub Actions lama (`.github/workflows/daily-effort.yml`)
memanggil ``python scripts/realtime_reversal.py`` — dan GitHub App tanpa
permission ``workflows`` tidak bisa mengubah workflow tersebut, jadi
entry ini meneruskan pemanggilan ke ``scripts.scan_silent.main``.

Flag lama (``--no-alert``, ``--mint``, ``--fixture``, dst.) diabaikan;
untuk opsi baru jalankan langsung ``python scripts/scan_silent.py``.
Tidak ada akses Telegram, tidak ada sinyal yang dihitung.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main(argv=None) -> int:
    from scripts.scan_silent import main as scan_main
    return scan_main([])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
