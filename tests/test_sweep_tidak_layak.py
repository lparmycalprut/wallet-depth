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


class LowestBuyPriceMoveTest(unittest.TestCase):
    def test_price_risen_since_lowest_buy(self):
        # Human: harga 0,0002133 ÷ lowest buy 0,000146 − 1 ≈ +46% (naik)
        move = ss.holder_price_change_vs_lowest_buy(HUMAN_MIN_AVG, HUMAN_PRICE)
        self.assertAlmostEqual(move, HUMAN_PRICE / HUMAN_MIN_AVG - 1.0)
        self.assertGreater(move, 0)

    def test_price_fallen_below_lowest_buy(self):
        self.assertAlmostEqual(ss.holder_price_change_vs_lowest_buy(0.2, 0.15), -0.25)

    def test_missing_inputs_return_none(self):
        self.assertIsNone(ss.holder_price_change_vs_lowest_buy(None, HUMAN_PRICE))
        self.assertIsNone(ss.holder_price_change_vs_lowest_buy(HUMAN_MIN_AVG, 0))
        self.assertIsNone(ss.holder_price_change_vs_lowest_buy(-1.0, HUMAN_PRICE))

    def test_price_move_formatting(self):
        self.assertEqual(ui._fmt_price_move(0.381), "naik 38.1%")
        self.assertEqual(ui._fmt_price_move(-0.058), "turun 5.8%")
        self.assertEqual(ui._fmt_price_move(0.0), "tetap")
        self.assertEqual(ui._fmt_price_move(None), "—")

    def test_cell_shows_value_and_price_move(self):
        cell = ui._lowest_buy_cell({"holder_min_avg_cost": HUMAN_MIN_AVG,
                                    "price_usd": HUMAN_PRICE,
                                    "fdv_usd": HUMAN_MC})
        move_pct = (HUMAN_PRICE / HUMAN_MIN_AVG - 1.0) * 100
        self.assertIn(f"(harga naik {move_pct:.1f}%)", cell)
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
