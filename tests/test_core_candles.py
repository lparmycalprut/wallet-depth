"""Coverage candle hourly/harian GeckoTerminal: normalisasi + batas hari UTC."""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest import mock

import core

MINT = "So11111111111111111111111111111111111111112"
PAIR = "PairAddress11111111111111111111111111111111"


def ts(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp())


def payload(rows):
    """Objek response GeckoTerminal palsu untuk ``ohlcv_list``."""
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"attributes": {"ohlcv_list": rows}}}

    return Response()


class NormalizeHourlyTest(unittest.TestCase):
    def test_rows_are_sorted_and_complete(self):
        rows = core.normalize_hourly_candles([
            [ts("2026-08-02T01:00:00+00:00"), 2.0, 2.5, 1.5, 2.2, 200],
            [ts("2026-08-02T00:00:00+00:00"), 1.0, 1.5, 0.5, 1.2, 100],
        ])
        self.assertEqual([row["ts"] for row in rows],
                         [ts("2026-08-02T00:00:00+00:00"),
                          ts("2026-08-02T01:00:00+00:00")])
        self.assertEqual(rows[0]["open"], 1.0)
        self.assertEqual(rows[0]["close"], 1.2)
        self.assertEqual(rows[1]["volume_usd"], 200.0)

    def test_duplicate_timestamp_keeps_the_last_row(self):
        stamp = ts("2026-08-02T00:00:00+00:00")
        rows = core.normalize_hourly_candles([
            [stamp, 1.0, 1.5, 0.5, 1.2, 100],
            [stamp, 1.0, 1.5, 0.5, 1.2, 999],
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["volume_usd"], 999.0)

    def test_quiet_hour_keeps_coverage_from_its_close(self):
        """Open/high/low null (jam tanpa trade) diisi dari close, volume 0."""
        rows = core.normalize_hourly_candles(
            [[ts("2026-08-02T00:00:00+00:00"), None, None, None, 1.4, None]])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["open"], 1.4)
        self.assertEqual(rows[0]["high"], 1.4)
        self.assertEqual(rows[0]["low"], 1.4)
        self.assertEqual(rows[0]["volume_usd"], 0.0)

    def test_missing_close_drops_the_row(self):
        rows = core.normalize_hourly_candles([
            [ts("2026-08-02T00:00:00+00:00"), 1.0, 1.5, 0.5, None, 100],
            [ts("2026-08-02T01:00:00+00:00"), 1.0, 1.5, 0.5, 1.1, 100],
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["close"], 1.1)

    def test_garbage_rows_are_skipped_without_raising(self):
        rows = core.normalize_hourly_candles([
            "bukan-baris", None, [1, 2, 3], {},
            [None, 1.0, 1.0, 1.0, 1.0, 1.0],
            ["teks", 1.0, 1.0, 1.0, 1.0, 1.0],
            [0, 1.0, 1.0, 1.0, 1.0, 1.0],
            [-5, 1.0, 1.0, 1.0, 1.0, 1.0],
            [ts("2026-08-02T00:00:00+00:00"), 1.0, float("nan"), 1.0, 1.1, 5],
            [ts("2026-08-02T01:00:00+00:00"), 1.0, 1.0, 1.0, float("inf"), 5],
        ])
        self.assertEqual(len(rows), 1)          # hanya baris NaN-high yang lolos
        self.assertEqual(rows[0]["high"], 1.1)   # high rusak → diisi close

    def test_negative_volume_is_clamped(self):
        rows = core.normalize_hourly_candles(
            [[ts("2026-08-02T00:00:00+00:00"), 1, 1, 1, 1, -500]])
        self.assertEqual(rows[0]["volume_usd"], 0.0)

    def test_millisecond_timestamps_are_normalized(self):
        """Kalau API berpindah ke milidetik, agregasi harian tidak boleh rusak."""
        seconds = ts("2026-08-02T00:00:00+00:00")
        rows = core.normalize_hourly_candles(
            [[seconds * 1000, 1.0, 1.5, 0.5, 1.2, 100],
             [(seconds + 3600) * 1000, 1.2, 1.6, 1.1, 1.4, 100]])
        self.assertEqual([row["ts"] for row in rows], [seconds, seconds + 3600])
        daily = core.aggregate_daily_candles(rows, limit_days=7)
        self.assertEqual([row["date"] for row in daily], ["2026-08-02"])
        self.assertEqual(daily[0]["hours"], 2)

    def test_empty_input(self):
        self.assertEqual(core.normalize_hourly_candles([]), [])
        self.assertEqual(core.normalize_hourly_candles(None), [])


class AggregateDailyTest(unittest.TestCase):
    def hourly(self, stamps, **kwargs):
        return core.normalize_hourly_candles(
            [[stamp, kwargs.get("open", 1.0), kwargs.get("high", 1.2),
              kwargs.get("low", 0.8), kwargs.get("close", 1.1),
              kwargs.get("volume", 100)] for stamp in stamps])

    def test_utc_day_boundary_is_exact(self):
        rows = core.aggregate_daily_candles(self.hourly([
            ts("2026-08-01T23:00:00+00:00"),
            ts("2026-08-02T00:00:00+00:00"),
        ]), limit_days=7)
        self.assertEqual([row["date"] for row in rows],
                         ["2026-08-01", "2026-08-02"])
        self.assertEqual(rows[0]["hours"], 1)
        self.assertEqual(rows[1]["hours"], 1)

    def test_year_edge_has_no_off_by_one(self):
        rows = core.aggregate_daily_candles(self.hourly([
            ts("2025-12-31T22:00:00+00:00"),
            ts("2025-12-31T23:00:00+00:00"),
            ts("2026-01-01T00:00:00+00:00"),
            ts("2026-01-01T01:00:00+00:00"),
        ]), limit_days=7)
        self.assertEqual([row["date"] for row in rows],
                         ["2025-12-31", "2026-01-01"])
        self.assertEqual([row["hours"] for row in rows], [2, 2])

    def test_leap_day_edge(self):
        rows = core.aggregate_daily_candles(self.hourly([
            ts("2024-02-28T23:00:00+00:00"),
            ts("2024-02-29T00:00:00+00:00"),
            ts("2024-03-01T00:00:00+00:00"),
        ]), limit_days=7)
        self.assertEqual([row["date"] for row in rows],
                         ["2024-02-28", "2024-02-29", "2024-03-01"])

    def test_open_close_high_low_and_volume_aggregate(self):
        hourly = core.normalize_hourly_candles([
            [ts("2026-08-01T00:00:00+00:00"), 1.0, 1.4, 0.9, 1.1, 100],
            [ts("2026-08-01T01:00:00+00:00"), 1.1, 1.9, 1.0, 1.3, 250],
            [ts("2026-08-01T02:00:00+00:00"), 1.3, 1.5, 0.5, 0.8, 50],
        ])
        rows = core.aggregate_daily_candles(hourly, limit_days=7)
        self.assertEqual(len(rows), 1)
        day = rows[0]
        self.assertEqual(day["open"], 1.0)
        self.assertEqual(day["close"], 0.8)
        self.assertEqual(day["high"], 1.9)
        self.assertEqual(day["low"], 0.5)
        self.assertEqual(day["volume_usd"], 400.0)
        self.assertEqual(day["hours"], 3)

    def test_limit_days_keeps_the_newest_days(self):
        stamps = [ts(f"2026-08-{day:02d}T12:00:00+00:00") for day in range(1, 11)]
        rows = core.aggregate_daily_candles(self.hourly(stamps), limit_days=3)
        self.assertEqual([row["date"] for row in rows],
                         ["2026-08-08", "2026-08-09", "2026-08-10"])

    def test_non_positive_limit_returns_nothing(self):
        """``[-0:]`` akan mengembalikan seluruh riwayat — harus dijaga."""
        stamps = [ts("2026-08-01T12:00:00+00:00"),
                  ts("2026-08-02T12:00:00+00:00")]
        hourly = self.hourly(stamps)
        self.assertEqual(core.aggregate_daily_candles(hourly, limit_days=0), [])
        self.assertEqual(core.aggregate_daily_candles(hourly, limit_days=-3), [])
        self.assertEqual(core.aggregate_daily_candles(hourly, limit_days=None),
                         [])
        self.assertEqual(core.aggregate_daily_candles(hourly,
                                                      limit_days="x"), [])

    def test_broken_rows_are_skipped(self):
        rows = core.aggregate_daily_candles([
            "rusak", None, {"ts": None, "close": 1.0},
            {"ts": ts("2026-08-01T00:00:00+00:00"), "close": None},
            {"ts": ts("2026-08-01T01:00:00+00:00"), "close": 1.2},
        ], limit_days=7)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hours"], 1)
        self.assertEqual(rows[0]["close"], 1.2)


class GetHourlyCandlesTest(unittest.TestCase):
    def test_empty_pair_skips_the_request(self):
        with mock.patch.object(core.requests, "get") as get:
            self.assertEqual(core.get_hourly_candles(""), [])
            self.assertEqual(core.get_hourly_candles(None), [])
        get.assert_not_called()

    def test_request_shape_and_normalization(self):
        rows = [[ts("2026-08-02T00:00:00+00:00"), 1, 2, 0.5, 1.5, 100]]
        with mock.patch.object(core.requests, "get",
                               return_value=payload(rows)) as get:
            result = core.get_hourly_candles(PAIR, limit_hours=168)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["close"], 1.5)
        args, kwargs = get.call_args
        self.assertIn(PAIR, args[0])
        self.assertIn("/ohlcv/hour", args[0])
        self.assertEqual(kwargs["params"], {"aggregate": 1, "limit": 168})
        self.assertEqual(kwargs["timeout"], 25)

    def test_limit_is_clamped_to_the_api_maximum(self):
        with mock.patch.object(core.requests, "get",
                               return_value=payload([])) as get:
            core.get_hourly_candles(PAIR, limit_hours=5_000)
        self.assertEqual(get.call_args.kwargs["params"]["limit"],
                         core.GECKOTERMINAL_MAX_LIMIT)
        with mock.patch.object(core.requests, "get",
                               return_value=payload([])) as get:
            core.get_hourly_candles(PAIR, limit_hours=0)
        self.assertEqual(get.call_args.kwargs["params"]["limit"], 1)

    def test_transport_and_payload_failures_return_empty(self):
        with mock.patch.object(core.requests, "get",
                               side_effect=RuntimeError("429")):
            self.assertEqual(core.get_hourly_candles(PAIR), [])
        broken = mock.Mock(status_code=200)
        broken.raise_for_status = mock.Mock()
        broken.json.side_effect = ValueError("bukan json")
        with mock.patch.object(core.requests, "get", return_value=broken):
            self.assertEqual(core.get_hourly_candles(PAIR), [])
        with mock.patch.object(core.requests, "get",
                               return_value=payload(None)):
            self.assertEqual(core.get_hourly_candles(PAIR), [])


class GetDailyCandlesTest(unittest.TestCase):
    def test_non_positive_limit_skips_the_request(self):
        with mock.patch.object(core.requests, "get") as get:
            self.assertEqual(core.get_daily_candles(PAIR, limit_days=0), [])
            self.assertEqual(core.get_daily_candles(PAIR, limit_days=None), [])
        get.assert_not_called()

    def test_requests_one_extra_day_of_hours(self):
        with mock.patch.object(core.requests, "get",
                               return_value=payload([])) as get:
            core.get_daily_candles(PAIR, limit_days=7)
        self.assertEqual(get.call_args.kwargs["params"]["limit"], 7 * 24 + 24)

    def test_null_cells_in_the_payload_do_not_raise(self):
        """Sebelumnya ``float(None)`` melempar TypeError keluar dari fungsi."""
        rows = [
            [ts("2026-08-01T00:00:00+00:00"), None, None, None, 1.1, None],
            [ts("2026-08-01T01:00:00+00:00"), 1.1, 1.3, 1.0, 1.2, 100],
            [ts("2026-08-02T00:00:00+00:00"), 1.2, None, None, None, 100],
        ]
        with mock.patch.object(core.requests, "get",
                               return_value=payload(rows)):
            result = core.get_daily_candles(PAIR, limit_days=7)
        self.assertEqual([row["date"] for row in result], ["2026-08-01"])
        self.assertEqual(result[0]["hours"], 2)
        self.assertEqual(result[0]["close"], 1.2)
        self.assertEqual(result[0]["volume_usd"], 100.0)

    def test_month_edge_grouping_end_to_end(self):
        rows = [
            [ts("2026-08-31T23:00:00+00:00"), 1.0, 1.1, 0.9, 1.05, 10],
            [ts("2026-09-01T00:00:00+00:00"), 1.05, 1.2, 1.0, 1.15, 20],
        ]
        with mock.patch.object(core.requests, "get",
                               return_value=payload(rows)):
            result = core.get_daily_candles(PAIR, limit_days=7)
        self.assertEqual([row["date"] for row in result],
                         ["2026-08-31", "2026-09-01"])
        self.assertEqual([row["volume_usd"] for row in result], [10.0, 20.0])

    def test_dexscreener_pair_matching_is_still_exact(self):
        """Regresi: pair quote-side tidak boleh menggantikan token yang diminta."""
        pairs = [
            {"pairAddress": "P1", "liquidity": {"usd": 10},
             "baseToken": {"address": "OTHER"}, "quoteToken": {"address": MINT}},
            {"pairAddress": "P2", "liquidity": {"usd": 999},
             "baseToken": {"address": MINT}, "quoteToken": {"address": "SOL"}},
            {"pairAddress": "P3", "liquidity": {"usd": 5},
             "baseToken": {"address": MINT}, "quoteToken": {"address": "SOL"}},
        ]
        matches = core.matching_dexscreener_pairs(pairs, MINT)
        self.assertEqual([pair["pairAddress"] for pair in matches],
                         ["P2", "P3", "P1"])
        self.assertEqual(core.select_dexscreener_pair(pairs, MINT)["pairAddress"],
                         "P2")
        self.assertEqual(core.matching_dexscreener_pairs(pairs, ""), [])
        self.assertIsNone(core.select_dexscreener_pair(pairs, "TIDAKADA"))
        token = core.dexscreener_pair_token(matches[-1], MINT)
        self.assertEqual(token["address"], MINT)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
