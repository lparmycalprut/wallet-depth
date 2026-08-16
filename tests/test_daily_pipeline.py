import unittest
from datetime import datetime
from unittest.mock import patch

from cvd_daily import MARKET_TZ, calculate_daily_cvd
from cvd_daily import build_effort_rows, fallback_candles_from_swaps


class DailyPipelineTest(unittest.TestCase):
    def test_day_boundary_is_utc_market_day(self):
        # 00:30 UTC is still the same market day (00:00 UTC boundary).
        ts = int(datetime.fromisoformat("2026-08-01T00:30:00+00:00").timestamp())
        rows = calculate_daily_cvd([
            ("buy", 3.0, ts, "A"), ("sell", 1.0, ts + 60, "B")])
        self.assertEqual(rows[0]["date"], "2026-08-01")
        self.assertEqual(rows[0]["cvd_delta"], 2.0)

    def test_day_boundary_rolls_over_at_utc_midnight(self):
        # 23:59 UTC belongs to the same day; +2min crosses to the next day.
        ts = int(datetime.fromisoformat("2026-08-01T23:59:00+00:00").timestamp())
        rows = calculate_daily_cvd([
            ("buy", 3.0, ts, "A"),
            ("sell", 1.0, ts + 120, "B")])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date"], "2026-08-01")
        self.assertEqual(rows[1]["date"], "2026-08-02")

    def test_candle_and_cvd_join(self):
        ts = int(datetime.fromisoformat("2026-08-01T03:00:00+00:00").timestamp())
        now = datetime.fromisoformat("2026-08-03T00:05:00+00:00")
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
        now = datetime.fromisoformat("2026-08-03T12:00:00+00:00")
        ts = int(now.timestamp())
        rows = build_effort_rows(
            "M", [("buy", 1, ts, "A")],
            [{"date": "2026-08-03", "open": 1, "close": 2}], now=now)
        self.assertEqual(rows, [])

    def test_core_daily_candles_aggregate_on_utc_boundary(self):
        from core import get_daily_candles

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                # [ts, open, high, low, close, volume]
                return {"data": {"attributes": {"ohlcv_list": [
                    [int(datetime.fromisoformat("2026-08-01T23:00:00+00:00").timestamp()), 1.0, 1.2, 0.9, 1.1, 100],
                    [int(datetime.fromisoformat("2026-08-02T00:00:00+00:00").timestamp()), 2.0, 2.2, 1.9, 2.1, 200],
                ]}}}

        with patch("core.requests.get", return_value=Response()):
            rows = get_daily_candles("PAIR", limit_days=7)
        self.assertEqual([row["date"] for row in rows], ["2026-08-01", "2026-08-02"])
        self.assertEqual(rows[0]["open"], 1.0)
        self.assertEqual(rows[0]["close"], 1.1)
        self.assertEqual(rows[1]["open"], 2.0)
        self.assertEqual(rows[1]["close"], 2.1)


if __name__ == "__main__":
    unittest.main()
