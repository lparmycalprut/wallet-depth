# -*- coding: utf-8 -*-
"""Retry otomatis untuk mint yang kohortnya tanpa data — logika murni, offline."""
from __future__ import annotations

import unittest

import sweep_screen as screen

A = "AAAA1111pump"
B = "BBBB2222pump"
C = "CCCC3333pump"


def _view(mint, status):
    return {"mint": mint, "ts": 1, "metrics": {}, "result": {"cohort_gate_status": status}}


NODATA = "TANPA DATA — kohort GMGN belum ada"


class IsCohortNodataTest(unittest.TestCase):
    def test_prefix_tanpa_data_kohort_dikenali(self):
        self.assertTrue(screen.is_cohort_nodata({"cohort_gate_status": NODATA}))
        self.assertTrue(screen.is_cohort_nodata(
            {"cohort_gate_status": "TANPA DATA — kohort"}))

    def test_status_lain_tidak_dianggap_nodata(self):
        for status in ("LOLOS — kohort C", "TUNGGU — kohort GMGN belum minus 50%",
                       "TANPA DATA — biaya", "", None):
            self.assertFalse(screen.is_cohort_nodata({"cohort_gate_status": status}),
                             status)
        self.assertFalse(screen.is_cohort_nodata(None))


class NodataRetryTargetsTest(unittest.TestCase):
    def test_hanya_mint_tanpa_data_kohort(self):
        views = [_view(A, NODATA), _view(B, "LOLOS — kohort C"), _view(C, NODATA)]
        self.assertEqual(screen.nodata_retry_targets(views, {}), [A, C])

    def test_urutan_watchlist_dipertahankan(self):
        views = [_view(C, NODATA), _view(A, NODATA)]
        self.assertEqual(screen.nodata_retry_targets(views, {}), [C, A])

    def test_batas_percobaan_menghentikan_mint(self):
        views = [_view(A, NODATA), _view(B, NODATA)]
        attempts = {A: screen.NODATA_RETRY_MAX_ATTEMPTS, B: 1}
        self.assertEqual(screen.nodata_retry_targets(views, attempts), [B])

    def test_batas_percobaan_bisa_diubah(self):
        views = [_view(A, NODATA)]
        self.assertEqual(screen.nodata_retry_targets(views, {A: 2}, max_attempts=3), [A])
        self.assertEqual(screen.nodata_retry_targets(views, {A: 3}, max_attempts=3), [])

    def test_view_tidak_valid_diabaikan(self):
        views = [None, {"result": {"cohort_gate_status": NODATA}}, _view(A, NODATA)]
        self.assertEqual(screen.nodata_retry_targets(views, None), [A])

    def test_tanpa_view_tidak_ada_target(self):
        self.assertEqual(screen.nodata_retry_targets([], {}), [])
        self.assertEqual(screen.nodata_retry_targets(None, None), [])

    def test_konstanta_jeda_dan_batas(self):
        self.assertEqual(screen.NODATA_RETRY_DELAY_SEC, 60)
        self.assertEqual(screen.NODATA_RETRY_MAX_ATTEMPTS, 5)


if __name__ == "__main__":
    unittest.main()
