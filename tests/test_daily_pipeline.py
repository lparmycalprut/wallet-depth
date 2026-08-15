import unittest
from datetime import datetime

from cvd_daily import WIB, calculate_daily_cvd
from cvd_daily import build_effort_rows, fallback_candles_from_swaps


class DailyPipelineTest(unittest.TestCase):
    def test_day_boundary_is_wib_not_utc(self):
        # 17:30 UTC is 00:30 WIB on the following date.
        ts = int(datetime.fromisoformat("2026-08-01T17:30:00+00:00").timestamp())
        rows = calculate_daily_cvd([
            ("buy", 3.0, ts, "A"), ("sell", 1.0, ts + 60, "B")])
        self.assertEqual(rows[0]["date"], "2026-08-02")
        self.assertEqual(rows[0]["cvd_delta"], 2.0)

    def test_candle_and_cvd_join(self):
        ts = int(datetime.fromisoformat("2026-08-01T03:00:00+00:00").timestamp())
        now = datetime.fromisoformat("2026-08-03T00:05:00+07:00")
        swaps = [("buy", 4.0, ts, "A"), ("sell", 1.0, ts + 1, "B")]
        candles = [{"date": "2026-08-01", "open": 100, "close": 110}]
        rows = build_effort_rows("M", swaps, candles, now=now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cvd_delta"], 3.0)
        self.assertAlmostEqual(rows[0]["ratio"], 0.3)

    def test_trade_price_fallback_uses_first_and_last(self):
        first = int(datetime.fromisoformat(
            "2026-08-01T03:00:00+00:00").timestamp())
        candles = fallback_candles_from_swaps([
            ("buy", 1, first + 60, "A", 1.2),
            ("sell", 1, first, "B", 1.0),
            ("buy", 1, first + 120, "C", 1.5),
        ])
        self.assertEqual(candles[0]["open"], 1.0)
        self.assertEqual(candles[0]["close"], 1.5)

    def test_open_day_is_not_joined(self):
        now = datetime.fromisoformat("2026-08-03T12:00:00+07:00")
        ts = int(now.timestamp())
        rows = build_effort_rows(
            "M", [("buy", 1, ts, "A")],
            [{"date": "2026-08-03", "open": 1, "close": 2}], now=now)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
