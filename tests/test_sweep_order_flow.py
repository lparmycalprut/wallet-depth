# -*- coding: utf-8 -*-
"""Order flow dari candle jam: info saja, tidak memengaruhi vonis (2026-10-15)."""
from __future__ import annotations

import unittest

import sweep_screen as ss


def _flat(n=30, price=1.0, vol=100.0):
    # [ts, open, high, low, close, volume], ts naik per jam. Open = close di
    # bawah titik tengah range, supaya tidak memicu ekor bawah (rasio 17%).
    return [[1_700_000_000 + i * 3600, price * 0.98, price * 1.03, price * 0.97,
             price * 0.98, vol] for i in range(n)]


class OrderFlowInfoTest(unittest.TestCase):
    def test_flat_candles_have_no_pattern(self):
        info = ss.order_flow_info(_flat())
        self.assertTrue(info["available"])
        self.assertEqual(info["flags"], [])
        self.assertEqual(info["labels"], [])

    def test_bos_up_when_close_above_prior_high(self):
        candles = _flat()
        candles[-1] = [candles[-1][0], 1.0, 1.25, 0.99, 1.2, 100.0]
        self.assertIn("bos_up", ss.order_flow_info(candles)["flags"])

    def test_sweep_reclaim_when_low_breaks_and_close_recovers(self):
        candles = _flat()
        candles[-1] = [candles[-1][0], 1.0, 1.02, 0.80, 1.0, 100.0]
        flags = ss.order_flow_info(candles)["flags"]
        self.assertIn("sweep_reclaim", flags)

    def test_no_sweep_reclaim_when_close_stays_below_prior_low(self):
        candles = _flat()
        candles[-1] = [candles[-1][0], 1.0, 1.0, 0.80, 0.85, 100.0]
        self.assertNotIn("sweep_reclaim", ss.order_flow_info(candles)["flags"])

    def test_wick_rejection_long_lower_wick_close_upper_half(self):
        candles = _flat()
        candles[-1] = [candles[-1][0], 1.0, 1.03, 0.90, 1.02, 100.0]
        self.assertIn("wick_rejection", ss.order_flow_info(candles)["flags"])

    def test_not_enough_candles_is_unavailable(self):
        info = ss.order_flow_info(_flat(n=10))
        self.assertFalse(info["available"])
        self.assertIn("butuh", info["reason"])

    def test_invalid_rows_are_skipped(self):
        candles = _flat() + [None, [1, 2], ["x", 1, 1, 1, 1, 1]]
        self.assertTrue(ss.order_flow_info(candles)["available"])

    def test_poc_is_level_with_most_volume(self):
        # Volume besar di sekitar 1,0; candle terakhir di 1,1 → POC dekat 1,0.
        candles = _flat(n=30, price=1.0, vol=10.0)
        candles[-1] = [candles[-1][0], 1.0, 1.12, 1.0, 1.1, 10.0]
        info = ss.order_flow_info(candles, bins=10)
        self.assertIsNotNone(info["poc_price"])
        self.assertAlmostEqual(info["poc_price"], 1.0, delta=0.04)
        self.assertGreater(info["poc_dist"], 0)

    def test_poc_none_without_volume(self):
        info = ss.order_flow_info(_flat(vol=0.0))
        self.assertIsNone(info["poc_price"])
        self.assertIsNone(info["poc_dist"])


class OrderFlowDoesNotAffectVerdictTest(unittest.TestCase):
    KEYS = ("checks", "passed_count", "scored_count", "required_count", "score",
            "structural_ok", "eligible", "verdict", "color", "cohort_gate_status",
            "holder_gate_status", "missing")

    def test_flags_present_but_verdict_identical(self):
        flat = _flat()
        pattern = _flat()
        pattern[-1] = [pattern[-1][0], 1.0, 1.25, 0.80, 1.2, 100.0]  # BOS + sweep
        self.assertTrue(ss.order_flow_info(pattern)["flags"])
        base = ss.evaluate({}, candles=flat, now=1_700_100_000)
        with_flow = ss.evaluate({}, candles=pattern, now=1_700_100_000)
        self.assertEqual(ss.order_flow_info(flat)["flags"], [])
        for key in self.KEYS:
            self.assertEqual(base[key], with_flow[key], key)
        self.assertEqual(with_flow["order_flow"]["flags"],
                         ss.order_flow_info(pattern)["flags"])

    def test_result_contains_order_flow_key(self):
        result = ss.evaluate({}, candles=_flat(), now=1_700_100_000)
        self.assertIn("order_flow", result)
        self.assertTrue(result["order_flow"]["available"])


if __name__ == "__main__":
    unittest.main()
