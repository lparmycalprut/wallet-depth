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
        self.assertAlmostEqual(rows[0]["price_chg_pct"], 10.0)
        # legacy tuples tanpa USD → volume_usd 0
        self.assertEqual(rows[0]["volume_usd"], 0.0)

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


class DailyVolumeUsdTest(unittest.TestCase):
    """Volume antar-hari HARUS dalam USD (amount_usd), bukan SOL."""

    def test_usd_volume_aggregated_separately_from_sol(self):
        ts = int(datetime.fromisoformat("2026-08-01T03:00:00+00:00").timestamp())
        rows = calculate_daily_cvd([
            ("buy", 2.0, ts, "A", None, 300.0, []),
            ("sell", 1.0, ts + 5, "B", None, 100.0, []),
            ("buy", 1.0, ts + 9, "C", None, 50.5, []),
        ])
        self.assertEqual(rows[0]["cvd_delta"], 2.0)          # 3-1 SOL
        self.assertEqual(rows[0]["buy_usd"], 350.5)          # USD terpisah
        self.assertEqual(rows[0]["sell_usd"], 100.0)
        self.assertEqual(rows[0]["volume_usd"], 450.5)

    def test_usd_volume_flows_into_effort_rows(self):
        ts1 = int(datetime.fromisoformat("2026-08-01T03:00:00+00:00").timestamp())
        ts2 = int(datetime.fromisoformat("2026-08-02T03:00:00+00:00").timestamp())
        now = datetime.fromisoformat("2026-08-03T00:05:00+00:00")
        swaps = [
            ("sell", 5.0, ts1, "A", None, 1000.0, []),
            ("sell", 6.0, ts2, "A", None, 250.0, []),
        ]
        candles = [{"date": "2026-08-01", "open": 100, "close": 60},
                   {"date": "2026-08-02", "open": 60, "close": 55}]
        rows = build_effort_rows("M", swaps, candles, now=now)
        self.assertEqual([r["volume_usd"] for r in rows], [1000.0, 250.0])


class OnchainTagAggregationTest(unittest.TestCase):
    """4 penanda on-chain diagregasi per hari (info output, bukan syarat)."""

    def test_four_markers_counted_by_side_and_day(self):
        d1 = int(datetime.fromisoformat("2026-08-01T03:00:00+00:00").timestamp())
        d2 = int(datetime.fromisoformat("2026-08-02T03:00:00+00:00").timestamp())
        swaps = [
            ("buy", 1.0, d1, "A", None, 10.0, ["axiom"]),            # smart
            ("buy", 1.0, d1 + 1, "B", None, 10.0, ["smart_money"]),   # smart
            ("buy", 1.0, d1 + 2, "C", None, 10.0, ["fresh_wallet"]),  # fresh
            ("sell", 1.0, d1 + 3, "D", None, 10.0, ["bundler"]),      # bot sell
            ("sell", 1.0, d1 + 4, "E", None, 10.0, ["paper_hands"]),  # bot sell
            ("buy", 1.0, d1 + 5, "F", None, 10.0, ["sandwich_bot"]),  # mev
            ("buy", 1.0, d1 + 6, "G", None, 10.0, ["Smart Money", "FRESH-WALLET"]),
            # sell bergaya smart money BUKAN smart_money_buy; buy bundler
            # BUKAN bot_sell:
            ("sell", 1.0, d2, "H", None, 10.0, ["axiom"]),
            ("buy", 1.0, d2 + 1, "I", None, 10.0, ["bundler"]),
        ]
        rows = calculate_daily_cvd(swaps)
        day1, day2 = rows
        self.assertEqual(day1["smart_money_buy"], 3)
        self.assertEqual(day1["fresh_buy"], 2)
        self.assertEqual(day1["bot_sell"], 2)
        self.assertEqual(day1["mev_noise"], 1)
        self.assertEqual(day2["smart_money_buy"], 0)
        self.assertEqual(day2["fresh_buy"], 0)
        self.assertEqual(day2["bot_sell"], 0)
        self.assertEqual(day2["mev_noise"], 0)

    def test_markers_flow_into_effort_rows(self):
        ts1 = int(datetime.fromisoformat("2026-08-01T03:00:00+00:00").timestamp())
        now = datetime.fromisoformat("2026-08-03T00:05:00+00:00")
        swaps = [("buy", 2.0, ts1, "A", None, 100.0, ["trojan"]),
                 ("sell", 1.0, ts1 + 9, "B", None, 50.0, [],)]
        candles = [{"date": "2026-08-01", "open": 100, "close": 95}]
        rows = build_effort_rows("M", swaps, candles, now=now)
        self.assertEqual(rows[0]["smart_money_buy"], 1)
        self.assertEqual(rows[0]["fresh_buy"], 0)
        self.assertEqual(rows[0]["bot_sell"], 0)
        self.assertEqual(rows[0]["mev_noise"], 0)


class MarketcapCloseTest(unittest.TestCase):
    def test_supply_produces_marketcap_close(self):
        ts1 = int(datetime.fromisoformat("2026-08-01T03:00:00+00:00").timestamp())
        now = datetime.fromisoformat("2026-08-03T00:05:00+00:00")
        swaps = [("buy", 2.0, ts1, "A", None, 100.0, [])]
        candles = [{"date": "2026-08-01", "open": 100, "close": 2.0}]
        rows = build_effort_rows("M", swaps, candles, now=now,
                                 supply=1_000_000.0)
        self.assertEqual(rows[0]["marketcap_close"], 2_000_000.0)
        # tanpa supply → tidak ada marketcap_close (gerbang wash dilewati)
        rows2 = build_effort_rows("M", swaps, candles, now=now)
        self.assertNotIn("marketcap_close", rows2[0])


if __name__ == "__main__":
    unittest.main()
