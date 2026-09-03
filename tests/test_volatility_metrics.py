"""Coverage metrik volatilitas 4 jam dari candle hourly (edge case data)."""
from __future__ import annotations

import unittest

import holder_history as hh

NOW = 1_800_000_000


def hourly(prices, *, start=None, spread=0.02, volume=1_000.0, step=3600):
    """Candle hourly berurutan; ``prices`` = close tiap jam."""
    first = NOW - step * (len(prices) - 1) if start is None else start
    rows = []
    for index, close in enumerate(prices):
        rows.append({
            "ts": first + index * step,
            "open": close * (1 - spread / 2),
            "high": close * (1 + spread),
            "low": close * (1 - spread),
            "close": close,
            "volume_usd": volume,
        })
    return rows


class VolatilityWindowTest(unittest.TestCase):
    def test_flat_market_has_zero_stddev_and_is_not_high_volatility(self):
        metrics = hh.calculate_volatility_metrics(
            hourly([1.0, 1.0, 1.0, 1.0]), now=NOW)
        self.assertTrue(metrics["available"])
        self.assertEqual(metrics["price_stddev_4h"], 0.0)
        self.assertFalse(metrics["high_volatility"])
        self.assertEqual(metrics["candles_in_window"], 4)
        self.assertEqual(metrics["missing_hours"], 0)
        self.assertEqual(metrics["volume_4h"], 4_000.0)

    def test_wild_market_crosses_the_three_percent_bar(self):
        metrics = hh.calculate_volatility_metrics(
            hourly([1.0, 1.25, 0.8, 1.1]), now=NOW)
        self.assertTrue(metrics["available"])
        self.assertGreater(metrics["price_stddev_4h"],
                           hh.HIGH_VOLATILITY_STDDEV_PCT)
        self.assertTrue(metrics["high_volatility"])
        self.assertGreater(metrics["price_range_4h"], metrics["price_stddev_4h"])
        self.assertGreaterEqual(metrics["intra_hour_volatility_max"],
                                metrics["intra_hour_volatility"])

    def test_only_the_current_window_counts_for_the_4h_metrics(self):
        """16 candle masuk, tapi stddev/range/volume hanya dari 4 jam terakhir."""
        history = hourly([1.0] * 12, start=NOW - 3600 * 15)
        current = hourly([1.0, 1.4, 0.7, 1.2], start=NOW - 3600 * 3)
        metrics = hh.calculate_volatility_metrics(current, history, now=NOW)
        self.assertEqual(metrics["candles_in_window"], 4)
        self.assertEqual(metrics["candles_total"], 16)
        self.assertEqual(metrics["history_hours"], hh.VOLATILITY_HISTORY_HOURS)
        self.assertIsNotNone(metrics["history_stddev_pct"])
        self.assertGreater(metrics["price_stddev_4h"], 3.0)

    def test_window_argument_overrides_the_default(self):
        rows = hourly([1.0, 1.1, 1.2, 1.3, 1.4, 1.5], start=NOW - 3600 * 5)
        metrics = hh.calculate_volatility_metrics(rows, now=NOW, window_hours=6)
        self.assertEqual(metrics["candles_in_window"], 6)
        self.assertEqual(metrics["window_hours"], 6)


class MissingCandleTest(unittest.TestCase):
    def test_empty_input_is_unavailable_not_calm(self):
        for value in ([], None, (), "bukan-list"):
            metrics = hh.calculate_volatility_metrics(value, now=NOW)
            self.assertFalse(metrics["available"], f"input={value!r}")
            self.assertIsNone(metrics["price_stddev_4h"])
            self.assertIsNone(metrics["price_range_4h"])
            self.assertIsNone(metrics["volume_4h"])
            self.assertFalse(metrics["high_volatility"])
            self.assertEqual(metrics["missing_hours"],
                             hh.VOLATILITY_WINDOW_HOURS)

    def test_single_candle_cannot_produce_a_stddev(self):
        metrics = hh.calculate_volatility_metrics(hourly([1.0]), now=NOW)
        self.assertFalse(metrics["available"])
        self.assertIsNone(metrics["price_stddev_4h"])
        self.assertEqual(metrics["candles_in_window"], 1)
        self.assertEqual(metrics["missing_hours"], 3)

    def test_price_gap_reports_missing_hours_and_wider_range(self):
        """Dua jam kosong di tengah: coverage berkurang, lompatan tetap terlihat."""
        rows = [
            {"ts": NOW - 3600 * 3, "open": 1.0, "high": 1.0, "low": 1.0,
             "close": 1.0, "volume_usd": 100.0},
            {"ts": NOW, "open": 1.6, "high": 1.6, "low": 1.6,
             "close": 1.6, "volume_usd": 900.0},
        ]
        metrics = hh.calculate_volatility_metrics(rows, now=NOW)
        self.assertEqual(metrics["candles_in_window"], 2)
        self.assertEqual(metrics["missing_hours"], 2)
        self.assertTrue(metrics["available"])
        self.assertAlmostEqual(metrics["price_range_4h"], 46.1538, places=3)
        self.assertAlmostEqual(metrics["price_change_4h_pct"], 60.0, places=3)
        self.assertEqual(metrics["volume_4h"], 1_000.0)

    def test_stale_candles_are_flagged(self):
        old = hourly([1.0, 1.1, 1.2, 1.3], start=NOW - 3600 * 24)
        metrics = hh.calculate_volatility_metrics(old, now=NOW)
        self.assertTrue(metrics["stale"])
        self.assertFalse(metrics["available"])   # tidak ada candle di window

    def test_without_now_the_newest_candle_anchors_the_window(self):
        """Backfill data lama tidak boleh dianggap basi/lubang."""
        rows = hourly([1.0, 1.1, 1.05, 1.2], start=NOW - 3600 * 100)
        metrics = hh.calculate_volatility_metrics(rows)
        self.assertEqual(metrics["anchor_ts"], rows[-1]["ts"])
        self.assertTrue(metrics["available"])
        self.assertFalse(metrics["stale"])
        self.assertEqual(metrics["missing_hours"], 0)


class MalformedCandleTest(unittest.TestCase):
    def test_raw_geckoterminal_rows_are_accepted(self):
        rows = [[NOW - 3600 * 3, 1.0, 1.05, 0.95, 1.0, 500],
                [NOW - 3600 * 2, 1.0, 1.10, 0.99, 1.05, 400],
                [NOW - 3600, 1.05, 1.20, 1.00, 0.90, 700],
                [NOW, 0.90, 1.00, 0.80, 0.95, 300]]
        metrics = hh.calculate_volatility_metrics(rows, now=NOW)
        self.assertTrue(metrics["available"])
        self.assertEqual(metrics["volume_4h"], 1_900.0)
        self.assertEqual(metrics["candles_in_window"], 4)

    def test_duplicate_timestamps_count_once(self):
        rows = hourly([1.0, 1.1, 1.2, 1.3], start=NOW - 3600 * 3)
        duplicated = [dict(rows[0], volume_usd=9_999.0)] + rows
        metrics = hh.calculate_volatility_metrics(duplicated, now=NOW)
        self.assertEqual(metrics["candles_in_window"], 4)
        self.assertEqual(metrics["volume_4h"], 4_000.0)

    def test_broken_rows_are_skipped(self):
        rows = hourly([1.0, 1.1], start=NOW - 3600)
        rows += ["rusak", {"ts": NOW}, {"ts": NOW - 5, "close": None},
                 {"ts": "bukan-angka", "close": 1.0},
                 {"ts": NOW - 7200, "close": -1.0},
                 {"ts": NOW - 10800, "close": float("nan")},
                 [1, 2, 3]]
        metrics = hh.calculate_volatility_metrics(rows, now=NOW)
        # Hanya dua candle sehat yang tersisa; keduanya tetap dipakai.
        self.assertEqual(metrics["candles_total"], 2)
        self.assertEqual(metrics["candles_in_window"], 2)
        self.assertTrue(metrics["available"])
        self.assertAlmostEqual(metrics["close_price"], 1.1)

    def test_zero_and_negative_prices_never_produce_nan(self):
        rows = hourly([1.0, 1.1], start=NOW - 3600)
        rows.append({"ts": NOW - 7200, "open": 0.0, "high": 0.0, "low": 0.0,
                     "close": 0.0, "volume_usd": 10.0})
        metrics = hh.calculate_volatility_metrics(rows, now=NOW)
        self.assertTrue(metrics["available"])
        self.assertIsNotNone(metrics["price_stddev_4h"])
        self.assertGreater(metrics["avg_price_4h"], 0)

    def test_inverted_high_low_row_is_ignored_for_intra_hour(self):
        rows = hourly([1.0, 1.1, 1.2], start=NOW - 3600 * 2)
        rows.append({"ts": NOW, "open": 1.2, "high": 0.5, "low": 1.4,
                     "close": 1.2, "volume_usd": 10.0})
        metrics = hh.calculate_volatility_metrics(rows, now=NOW)
        self.assertTrue(metrics["available"])
        self.assertIsNotNone(metrics["intra_hour_volatility"])
        self.assertGreaterEqual(metrics["intra_hour_volatility"], 0.0)


class VolatilityContractTest(unittest.TestCase):
    def test_metric_keys_are_stable(self):
        metrics = hh.calculate_volatility_metrics(
            hourly([1.0, 1.1, 1.2, 1.3]), now=NOW)
        for key in ("available", "price_stddev_4h", "price_range_4h",
                    "intra_hour_volatility", "intra_hour_volatility_max",
                    "high_volatility", "price_change_4h_pct", "volume_4h",
                    "history_stddev_pct", "avg_price_4h", "close_price",
                    "candles_in_window", "candles_total", "missing_hours",
                    "stale", "anchor_ts", "window_hours", "history_hours",
                    "high_volatility_pct"):
            self.assertIn(key, metrics)

    def test_threshold_is_configurable(self):
        # stddev ~1,7%: di atas ambang uji 1%, di bawah ambang default 3%.
        rows = hourly([1.0, 1.02, 0.98, 1.01], start=NOW - 3600 * 3)
        metrics = hh.calculate_volatility_metrics(rows, now=NOW,
                                                  high_volatility_pct=1.0)
        self.assertAlmostEqual(metrics["high_volatility_pct"], 1.0)
        self.assertTrue(metrics["high_volatility"])
        default = hh.calculate_volatility_metrics(rows, now=NOW)
        self.assertFalse(default["high_volatility"])

    def test_stddev_is_sample_standard_deviation_in_percent(self):
        rows = hourly([1.0, 1.1, 0.9, 1.0], start=NOW - 3600 * 3)
        metrics = hh.calculate_volatility_metrics(rows, now=NOW)
        mean = 1.0
        sample = ((0.0 + 0.01 + 0.01 + 0.0) / 3) ** 0.5
        self.assertAlmostEqual(metrics["price_stddev_4h"],
                               sample / mean * 100.0, places=3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
