"""Matikan pengambilan trade GMGN untuk delta selama tes scan (tanpa jaringan).

Dipakai dengan ``setUpModule``/``tearDownModule`` di modul tes yang menjalankan
``run_scan``. Kandidat tetap dihitung, tetapi tanpa trade: delta = tidak lengkap.
"""
from __future__ import annotations

from unittest import mock

import sweep_scan


def start():
    patcher = mock.patch.object(sweep_scan, "_gmgn_trades_for_delta",
                                return_value=([], False))
    patcher.start()
    return patcher
