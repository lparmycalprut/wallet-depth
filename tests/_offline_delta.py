"""Matikan pengambilan trade GMGN selama tes scan (tanpa jaringan).

Dipakai dengan ``setUpModule``/``tearDownModule`` di modul tes yang menjalankan
``run_scan``. Dua jalur GMGN dimatikan: trade untuk delta (kandidat tetap
dihitung, tetapi tanpa trade: delta = tidak lengkap) dan trade untuk fitur
wallet (tanpa jaringan: fitur kosong, status tidak lengkap).
"""
from __future__ import annotations

from unittest import mock

import sweep_scan


class _Patches:
    def __init__(self, *patchers):
        self._patchers = patchers

    def stop(self):
        for patcher in reversed(self._patchers):
            patcher.stop()


def start():
    delta = mock.patch.object(sweep_scan, "_gmgn_trades_for_delta",
                              return_value=([], False))
    wallet = mock.patch.object(sweep_scan, "_gmgn_wallet_swaps",
                               return_value=([], False))
    delta.start()
    wallet.start()
    return _Patches(delta, wallet)
