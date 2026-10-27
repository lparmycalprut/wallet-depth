# -*- coding: utf-8 -*-
"""Grafik tren token/MC per snapshot (permintaan user 2026-10-27)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sweep_store as store  # noqa: E402
import sweep_ui as ui  # noqa: E402


class SnapshotTokenMcTests(unittest.TestCase):
    def test_snapshot_row_stores_token_mc(self):
        row = store.snapshot_row({"price_usd": 0.0003376, "pool_base_usd": 33926.1,
                                  "fdv_usd": 334836.0, "liq_usd": 66356.5}, ts=1000)
        self.assertAlmostEqual(row["token_mc"], 33926.1 / 334836.0)
        self.assertEqual(row["pool_base_usd"], 33926.1)

    def test_snapshot_row_without_pool_data_is_none(self):
        row = store.snapshot_row({"price_usd": 1.0, "fdv_usd": 0}, ts=1000)
        self.assertIsNone(row["token_mc"])

    def test_token_mc_of_old_row_uses_view_fallback(self):
        old = {"ts": 1, "view": {"metrics": {"pool_base_usd": 50.0, "fdv_usd": 500.0}}}
        self.assertAlmostEqual(store.token_mc_of(old), 0.1)
        self.assertIsNone(store.token_mc_of({"ts": 1}))


class TrendSeriesTests(unittest.TestCase):
    def test_series_is_oldest_first_and_skips_missing(self):
        state = store.empty_state()
        for ts, pool in [(3600 * 2, 30.0), (3600 * 1, 10.0), (3600 * 3, None)]:
            store.add_snapshot(state, "M", {"pool_base_usd": pool, "fdv_usd": 100.0},
                               ts=ts)
        self.assertEqual(ui._token_mc_series(state, "M"), [10.0, 30.0])

    def test_series_is_capped_to_limit(self):
        state = store.empty_state()
        for i in range(10):
            store.add_snapshot(state, "M", {"pool_base_usd": i + 1, "fdv_usd": 100.0},
                               ts=3600 * i)
        series = ui._token_mc_series(state, "M", limit=4)
        self.assertEqual(series, [7.0, 8.0, 9.0, 10.0])

    def test_unknown_mint_gives_empty_series(self):
        self.assertEqual(ui._token_mc_series(store.empty_state(), "X"), [])


class TrendColumnTests(unittest.TestCase):
    def _row(self, **extra):
        row = {"mint": "M", "metrics": {"symbol": "RARI", "fdv_usd": 100.0,
                                        "pool_base_usd": 10.0},
               "result": {"checks": []}, "sweep_context": None}
        row.update(extra)
        return row

    def test_column_present_only_when_history_given(self):
        with_hist = ui._eligibility_rows([self._row(token_mc_hist=[9.0, 10.0])])[0]
        self.assertEqual(with_hist["Tren token/MC"], [9.0, 10.0])
        without = ui._eligibility_rows([self._row()])[0]
        self.assertNotIn("Tren token/MC", without)

    def test_column_sits_right_after_token_mc(self):
        keys = list(ui._eligibility_rows([self._row(token_mc_hist=[])])[0])
        self.assertEqual(keys[keys.index("Token/MC") + 1], "Tren token/MC")


if __name__ == "__main__":
    unittest.main()
