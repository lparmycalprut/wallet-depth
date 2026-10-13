# -*- coding: utf-8 -*-
"""Offline tests for Sweep's GMGN cohort data and early-pool OHLCV fetch."""
from __future__ import annotations

import time
import unittest
from unittest import mock

import sweep_data as data


class GmgnTopBuyersTest(unittest.TestCase):
    def test_holding_rate_and_status_now_are_normalized(self):
        payload = {
            "data": {
                "holders": {
                    "statusNow": {
                        "holding_rate": "0",
                        "hold": {"count": "12"},
                        "sold_part": "4",
                        "sold": 8,
                    }
                }
            }
        }
        with mock.patch.object(data, "_get_json", return_value=payload) as fetch:
            result = data.gmgn_top_buyers("MINT", use_cache=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["holding_rate"], 0.0)
        self.assertEqual(result["status_now"],
                         {"hold": 12.0, "sold_part": 4.0, "sold": 8.0})
        self.assertIn("/api/v1/tokens/top_buyers/sol/MINT", fetch.call_args.args[0])

    def test_failure_is_a_non_raising_empty_result(self):
        with mock.patch.object(data, "_get_json", side_effect=RuntimeError("offline")):
            result = data.gmgn_top_buyers("MINT", use_cache=False)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["holding_rate"])
        self.assertEqual(result["status_now"], {})
        self.assertIn("offline", result["error"])

    def test_token_stat_exposes_original_bundler_field(self):
        payload = {"data": {
            "holder_count": "21",
            "top_bundler_trader_percentage": "0.18",
            "bot_degen_rate": "0.446",
            "fresh_wallet_rate": "0.025",
        }}
        with mock.patch.object(data, "_get_json", return_value=payload):
            result = data.gmgn_stat("MINT", use_cache=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["top_bundler_trader_percentage"], 0.18)
        self.assertEqual(result["bundler_rate"], 0.18)
        self.assertEqual(result["bot_degen_rate"], 0.446)
        self.assertEqual(result["fresh_wallet_rate"], 0.025)


class GmgnTokenHoldersTest(unittest.TestCase):
    def test_min_avg_cost_counts_only_holders_still_holding(self):
        payload = {"code": 0, "data": {"list": [
            {"avg_cost": "0.00099", "balance": "100"},
            {"avg_cost": None, "balance": "50"},          # tanpa avg → diabaikan
            {"avg_cost": "0.00002", "balance": "0"},      # sudah jual habis
            {"avg_cost": "0.0000707", "balance": "5870000"},
            {"avg_cost": "0.00015", "balance": "9"},
        ]}}
        with mock.patch.object(data, "_get_json", return_value=payload) as fetch:
            result = data.gmgn_token_holders("MINT", use_cache=False)
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["holder_min_avg_cost"], 0.0000707)
        self.assertEqual(result["holder_cost_count"], 3)
        url = fetch.call_args.args[0]
        self.assertIn("/vas/api/v1/token_holders/sol/MINT", url)
        self.assertIn("limit=100", url)

    def test_no_usable_holder_gives_none_but_ok(self):
        payload = {"data": {"list": [{"avg_cost": None, "balance": "1"}]}}
        with mock.patch.object(data, "_get_json", return_value=payload):
            result = data.gmgn_token_holders("MINT", use_cache=False)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["holder_min_avg_cost"])
        self.assertEqual(result["holder_cost_count"], 0)

    def test_failure_is_non_raising(self):
        with mock.patch.object(data, "_get_json", side_effect=RuntimeError("403")):
            result = data.gmgn_token_holders("MINT", use_cache=False)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["holder_min_avg_cost"])
        self.assertIn("403", result["error"])


class CollectMetricsTest(unittest.TestCase):
    def test_row_metrics_include_gmgn_and_birth_pool_fields(self):
        dex = {
            "ok": True, "mint": "M", "symbol": "T", "name": "Token",
            "price_usd": 0.1, "liq_usd": 1000.0, "fdv_usd": 5000.0,
            "market_cap_usd": 5000.0, "vol_24h": 3350.0,
            "pair_address": "POOL", "pair_created_at": 1_790_866_800_000,
            "dex_id": "raydium",
        }
        rug = {"ok": True, "top10_holder_pct": 10.0, "holder_pcts": [2.0],
               "rugcheck_ok": True, "pool_count": 1}
        stat = {"ok": True, "top_bundler_trader_percentage": 0.18,
                "bundler_rate": 0.18, "bot_degen_rate": 0.446,
                "fresh_wallet_rate": 0.025, "holder_count": 100}
        buyers = {"ok": True, "holding_rate": 0.0,
                  "status_now": {"hold": 12, "sold_part": 4, "sold": 8}}
        with (mock.patch.object(data, "dex_snapshot", return_value=dex),
              mock.patch.object(data, "rugcheck_snapshot", return_value=rug),
              mock.patch.object(data, "gmgn_stat", return_value=stat),
              mock.patch.object(data, "gmgn_top_buyers", return_value=buyers),
              mock.patch.object(data, "gmgn_token_holders", return_value={
                  "ok": True, "holder_min_avg_cost": 0.00007,
                  "holder_cost_count": 42})):
            row = data.collect_metrics("M", use_cache=False)
        self.assertEqual(row["holder_min_avg_cost"], 0.00007)
        self.assertEqual(row["holder_cost_count"], 42)
        self.assertTrue(row["sources"]["gmgn_token_holders"])
        self.assertEqual(row["top_bundler_trader_percentage"], 0.18)
        self.assertEqual(row["bot_degen_rate"], 0.446)
        self.assertEqual(row["fresh_wallet_rate"], 0.025)
        self.assertEqual(row["holding_rate"], 0.0)
        self.assertEqual(row["status_now"]["sold_part"], 4)
        self.assertEqual(row["pair_created_at"], 1_790_866_800)
        self.assertEqual(row["vol24_usd"], 3350.0)


class CohortOhlcvTest(unittest.TestCase):
    def test_fetches_and_filters_first_48_hours(self):
        created = 1_790_866_800
        rows = [
            [created - 3600, 1, 1, 1, 1, 1],
            [created, 2, 2, 2, 2, 2],
            [created + 47 * 3600, 3, 3, 3, 3, 3],
            [created + 48 * 3600, 4, 4, 4, 4, 4],
        ]
        with mock.patch.object(data, "ohlcv_detail",
                               return_value={"rows": rows, "error": ""}) as fetch:
            result = data.cohort_ohlcv("POOL", created, use_cache=False)
        self.assertEqual(result, rows[1:3])
        self.assertEqual(fetch.call_args.kwargs["before"],
                         created + 48 * 3600)


class OhlcvRetryTest(unittest.TestCase):
    def setUp(self):
        self._delays = data.OHLCV_RETRY_DELAYS
        self._interval = data.GECKO_MIN_INTERVAL
        data.OHLCV_RETRY_DELAYS = (0.0, 0.0)
        data.GECKO_MIN_INTERVAL = 0.0

    def tearDown(self):
        data.OHLCV_RETRY_DELAYS = self._delays
        data.GECKO_MIN_INTERVAL = self._interval

    def test_requests_are_spaced_by_min_interval(self):
        data.GECKO_MIN_INTERVAL = 0.05
        data._gecko_next_at[0] = 0.0
        started = time.monotonic()
        for _ in range(3):
            data._gecko_throttle()
        self.assertGreaterEqual(time.monotonic() - started, 0.09)

    @staticmethod
    def _ok(rows):
        return {"data": {"attributes": {"ohlcv_list": rows}}}

    def test_retries_rate_limit_then_succeeds(self):
        responses = [data.HttpError("GET gagal: HTTP 429", status=429),
                     data.HttpError("GET gagal: HTTP 503", status=503),
                     self._ok([[100, 1, 1, 1, 1, 1]])]
        with mock.patch.object(data, "_get_json", side_effect=responses) as fetch:
            detail = data.ohlcv_detail("POOL", "hour", use_cache=False)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(detail, {"rows": [[100, 1, 1, 1, 1, 1]], "error": ""})

    def test_gives_up_after_retries_and_reports_status(self):
        err = data.HttpError("GET gagal: HTTP 429", status=429)
        with mock.patch.object(data, "_get_json", side_effect=err) as fetch:
            detail = data.ohlcv_detail("POOL", "hour", use_cache=False)
        self.assertEqual(fetch.call_count, len(data.OHLCV_RETRY_DELAYS) + 1)
        self.assertEqual(detail, {"rows": [], "error": "GeckoTerminal HTTP 429"})

    def test_client_error_is_not_retried(self):
        err = data.HttpError("GET gagal: HTTP 404", status=404)
        with mock.patch.object(data, "_get_json", side_effect=err) as fetch:
            detail = data.ohlcv_detail("POOL", "hour", use_cache=False)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(detail["error"], "GeckoTerminal HTTP 404")

    def test_cohort_reports_missing_inputs_without_fetching(self):
        with mock.patch.object(data, "_get_json") as fetch:
            no_pool = data.cohort_ohlcv_detail("", 1_790_866_800, use_cache=False)
            no_time = data.cohort_ohlcv_detail("POOL", None, use_cache=False)
        fetch.assert_not_called()
        self.assertIn("pairAddress", no_pool["error"])
        self.assertEqual(no_time["error"], "pairCreatedAt tidak tersedia")

    def test_empty_candles_are_explained_not_silent(self):
        with mock.patch.object(data, "_get_json", return_value=self._ok([])):
            detail = data.cohort_ohlcv_detail("POOL", 1_790_866_800, use_cache=False)
        self.assertEqual(detail["rows"], [])
        self.assertIn("48 jam", detail["error"])

    def test_normalizes_pair_created_at_milliseconds(self):
        self.assertEqual(data._timestamp_seconds(1_790_866_800_000),
                         1_790_866_800)


if __name__ == "__main__":
    unittest.main()
