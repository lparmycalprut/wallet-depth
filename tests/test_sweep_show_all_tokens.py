# -*- coding: utf-8 -*-
"""Sementara tampilkan semua token di tabel Sweep (permintaan user 2026-10-27)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sweep_ui as ui  # noqa: E402


def _row(mint, *, hidden):
    # Baris yang kena filter: bundler < 10% (view_hidden → True).
    bundler = 0.02 if hidden else 0.30
    return {"mint": mint, "result": {"checks": [], "reference_fund_x": 1.0},
            "metrics": {"top_bundler_trader_percentage": bundler}}


class ShowAllTokensTests(unittest.TestCase):
    def setUp(self):
        self.rows = [_row("A", hidden=False), _row("B", hidden=True),
                     _row("C", hidden=True)]

    def test_show_all_keeps_every_row_in_main_table(self):
        with mock.patch.object(ui, "SHOW_ALL_TOKENS", True):
            rows, hidden = ui._split_rows(self.rows)
        self.assertEqual([r["mint"] for r in rows], ["A", "B", "C"])
        self.assertEqual(hidden, [])

    def test_filter_restored_when_flag_off(self):
        with mock.patch.object(ui, "SHOW_ALL_TOKENS", False):
            rows, hidden = ui._split_rows(self.rows)
        self.assertEqual([r["mint"] for r in rows], ["A"])
        self.assertEqual([r["mint"] for r in hidden], ["B", "C"])

    def test_default_is_show_all(self):
        self.assertTrue(ui.SHOW_ALL_TOKENS)


if __name__ == "__main__":
    unittest.main()
