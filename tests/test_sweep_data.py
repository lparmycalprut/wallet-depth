# -*- coding: utf-8 -*-
"""Offline tests for Sweep's GMGN cohort data and early-pool OHLCV fetch."""
from __future__ import annotations

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
               "lp_locked_pct": 90.0, "pool_count": 1}
        stat = {"ok": True, "top_bundler_trader_percentage": 0.18,
                "bundler_rate": 0.18, "bot_degen_rate": 0.446,
                "fresh_wallet_rate": 0.025, "holder_count": 100}
        buyers = {"ok": True, "holding_rate": 0.0,
                  "status_now": {"hold": 12, "sold_part": 4, "sold": 8}}
        with (mock.patch.object(data, "dex_snapshot", return_value=dex),
              mock.patch.object(data, "rugcheck_snapshot", return_value=rug),
              mock.patch.object(data, "gmgn_stat", return_value=stat),
              mock.patch.object(data, "gmgn_top_buyers", return_value=buyers)):
            row = data.collect_metrics("M", use_cache=False)
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
        with mock.patch.object(data, "ohlcv", return_value=rows) as fetch:
            result = data.cohort_ohlcv("POOL", created, use_cache=False)
        self.assertEqual(result, rows[1:3])
        self.assertEqual(fetch.call_args.kwargs["before"],
                         created + 48 * 3600)
        self.assertEqual(fetch.call_args.kwargs["limit"], 50)

    def test_normalizes_pair_created_at_milliseconds(self):
        self.assertEqual(data._timestamp_seconds(1_790_866_800_000),
                         1_790_866_800)


if __name__ == "__main__":
    unittest.main()
