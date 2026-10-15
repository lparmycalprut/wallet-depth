# -*- coding: utf-8 -*-
"""TIDAK LAYAK disembunyikan dan diperlakukan seperti SKIP kohort plus; kolom
Lowest buy (MC) menampilkan selisih terhadap MC saat ini (2026-10-15)."""
from __future__ import annotations

import unittest

import sweep_screen as ss
import sweep_ui as ui

HUMAN_MIN_AVG = 0.00014612677607271226
HUMAN_PRICE = 0.0002133
HUMAN_MC = 207_453.0


def _row(verdict, *, cohort_status="LOLOS", cohort_passed=True, scan_error=None):
    row = {"metrics": {}, "result": {"verdict": verdict,
                                     "cohort_gate_status": cohort_status,
                                     "cohort_gate_passed": cohort_passed,
                                     "passed_count": 1, "score": 0.2,
                                     "scored_count": 6}}
    if scan_error:
        row["scan_error"] = scan_error
    return row


class LowestBuyVsMcTest(unittest.TestCase):
    def test_negative_when_lowest_buy_below_price(self):
        diff = ss.holder_lowest_buy_vs_mc(HUMAN_MIN_AVG, HUMAN_PRICE)
        self.assertAlmostEqual(diff, HUMAN_MIN_AVG / HUMAN_PRICE - 1.0)
        self.assertLess(diff, 0)
        self.assertAlmostEqual(diff, -0.3149, places=3)

    def test_equals_lowest_buy_mc_over_mc_minus_one(self):
        low_mc = ss.holder_lowest_buy_mc(HUMAN_MIN_AVG, HUMAN_PRICE, HUMAN_MC)
        diff = ss.holder_lowest_buy_vs_mc(HUMAN_MIN_AVG, HUMAN_PRICE)
        self.assertAlmostEqual(diff, low_mc / HUMAN_MC - 1.0, places=9)

    def test_positive_when_lowest_buy_above_price(self):
        self.assertAlmostEqual(ss.holder_lowest_buy_vs_mc(0.3, 0.2), 0.5)

    def test_missing_inputs_return_none(self):
        self.assertIsNone(ss.holder_lowest_buy_vs_mc(None, HUMAN_PRICE))
        self.assertIsNone(ss.holder_lowest_buy_vs_mc(HUMAN_MIN_AVG, 0))
        self.assertIsNone(ss.holder_lowest_buy_vs_mc(-1.0, HUMAN_PRICE))

    def test_signed_percent_formatting(self):
        self.assertEqual(ui._fmt_signed_pct(-0.3149), "−31.5%")
        self.assertEqual(ui._fmt_signed_pct(0.5), "+50.0%")
        self.assertEqual(ui._fmt_signed_pct(0.0), "+0.0%")
        self.assertEqual(ui._fmt_signed_pct(None), "—")

    def test_cell_shows_value_and_signed_diff(self):
        cell = ui._lowest_buy_cell({"holder_min_avg_cost": HUMAN_MIN_AVG,
                                    "price_usd": HUMAN_PRICE,
                                    "fdv_usd": HUMAN_MC})
        self.assertIn("(−31.5% vs MC)", cell)
        self.assertTrue(cell.startswith("$"))

    def test_cell_without_data_is_dash(self):
        self.assertEqual(ui._lowest_buy_cell({}), "—")


class TidakLayakHiddenTest(unittest.TestCase):
    def test_tidak_layak_is_hidden(self):
        self.assertTrue(ss.is_tidak_layak({"verdict": "TIDAK LAYAK"}))
        self.assertTrue(ss.view_hidden(_row("TIDAK LAYAK")))

    def test_other_verdicts_not_hidden_by_this_rule(self):
        for verdict in ("LAYAK SWEEP", "KANDIDAT", "DATA KURANG"):
            self.assertFalse(ss.view_hidden(_row(verdict)), verdict)

    def test_scan_error_never_hidden(self):
        row = _row("TIDAK LAYAK", scan_error={"error": "fetch gagal"})
        self.assertFalse(ss.view_hidden(row))

    def test_tidak_layak_sorts_with_skip_kohort_plus(self):
        tidak = _row("TIDAK LAYAK")
        plus = {"metrics": {}, "result": {"verdict": "TIDAK LAYAK",
                                          "cohort_gate_status": "SKIP — kohort plus",
                                          "cohort_gate_passed": False}}
        kandidat = {"metrics": {}, "result": {"verdict": "KANDIDAT",
                                              "cohort_gate_status": "LOLOS",
                                              "cohort_gate_passed": True,
                                              "passed_count": 2, "score": 0.5,
                                              "scored_count": 4}}
        order = sorted([plus, tidak, kandidat],
                       key=lambda r: ss.display_sort_key(r["result"]))
        self.assertIs(order[0], kandidat)
        # TIDAK LAYAK dan SKIP kohort plus sama-sama di grup paling bawah.
        self.assertEqual(ss.display_sort_key(tidak["result"])[1],
                         ss.display_sort_key(plus["result"])[1])
        self.assertTrue(ss.display_sort_key(tidak["result"])[1])

    def test_skip_plus_rows_are_not_hidden(self):
        # SKIP kohort plus saja tetap tampil (hanya diurutkan ke bawah).
        plus = {"metrics": {}, "result": {"verdict": "SKIP — kohort plus",
                                          "cohort_gate_status": "SKIP — kohort plus",
                                          "cohort_gate_passed": False}}
        self.assertFalse(ss.view_hidden(plus))


if __name__ == "__main__":
    unittest.main()
