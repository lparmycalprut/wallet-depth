# -*- coding: utf-8 -*-
"""Filter tabel Sweep: Token/MC dan turnover (permintaan user 2026-10-27)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sweep_ui as ui  # noqa: E402

FULL_TMC = ui.TMC_FILTER_BOUNDS
FULL_TURN = ui.TURN_FILTER_BOUNDS


def _row(mint, tmc_pct=None, turnover=None):
    """Baris minimal: Token/MC = pool_base_usd ÷ fdv_usd (fdv = 100)."""
    metrics = {"fdv_usd": 100.0}
    if tmc_pct is not None:
        metrics["pool_base_usd"] = tmc_pct  # pool_base_usd/100 = tmc_pct %
    return {"mint": mint, "metrics": metrics,
            "result": {"turnover_x": turnover}}


class RowValueTests(unittest.TestCase):
    def test_token_mc_pct_from_pool_value(self):
        self.assertAlmostEqual(ui.row_token_mc_pct(_row("A", 25.0)), 25.0)

    def test_token_mc_none_without_data(self):
        self.assertIsNone(ui.row_token_mc_pct(_row("A")))

    def test_turnover_prefers_row_then_result(self):
        self.assertEqual(ui.row_turnover({"turnover_x": 2.5, "result": {}}), 2.5)
        self.assertEqual(ui.row_turnover({"result": {"turnover_x": 1.5}}), 1.5)
        self.assertIsNone(ui.row_turnover({"result": {}}))


class FilterRowsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [_row("low", 5.0, 0.5), _row("mid", 20.0, 3.0),
                     _row("high", 60.0, 12.0), _row("none")]

    def _mints(self, out):
        return [row["mint"] for row in out]

    def test_default_filter_keeps_everything_including_missing(self):
        self.assertEqual(self._mints(ui.filter_rows(self.rows)),
                         ["low", "mid", "high", "none"])

    def test_token_mc_range_excludes_outside_and_missing(self):
        out = ui.filter_rows(self.rows, tmc_range=(10.0, 30.0))
        self.assertEqual(self._mints(out), ["mid"])

    def test_turnover_range(self):
        out = ui.filter_rows(self.rows, turn_range=(1.0, 5.0))
        self.assertEqual(self._mints(out), ["mid"])

    def test_both_filters_combine_with_and(self):
        out = ui.filter_rows(self.rows, tmc_range=(0.0, 50.0),
                             turn_range=(0.0, 1.0))
        self.assertEqual(self._mints(out), ["low"])

    def test_upper_bound_at_maximum_means_no_upper_limit(self):
        out = ui.filter_rows(self.rows, tmc_range=(10.0, FULL_TMC[1]))
        self.assertEqual(self._mints(out), ["mid", "high"])
        out = ui.filter_rows(self.rows, turn_range=(1.0, FULL_TURN[1]))
        self.assertEqual(self._mints(out), ["mid", "high"])

    def test_lower_bound_at_zero_means_no_lower_limit(self):
        out = ui.filter_rows(self.rows, tmc_range=(FULL_TMC[0], 10.0))
        self.assertEqual(self._mints(out), ["low"])

    def test_filter_does_not_reorder_or_mutate_rows(self):
        before = [dict(row) for row in self.rows]
        ui.filter_rows(self.rows, tmc_range=(10.0, 30.0))
        self.assertEqual(self.rows, before)


if __name__ == "__main__":
    unittest.main()
