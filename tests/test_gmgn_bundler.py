from __future__ import annotations

import unittest
from unittest import mock

import gmgn_bundler as gb
import meteora_screener as ms


MINT = "Token11111111111111111111111111111111111"


class BundlerSummaryTest(unittest.TestCase):
    def test_parses_string_fractions_and_risk_boundary(self):
        report = gb.summarize({"data": {
            "top_bundler_trader_percentage": "0.15",
            "dev_team_hold_rate": "0.0125",
            "top70_sniper_hold_rate": "0.03",
        }}, mint=MINT)
        self.assertTrue(report["ok"])
        self.assertEqual(report["bundler_rate"], 0.15)
        self.assertEqual(report["verdict"], "BERISIKO")
        self.assertEqual(report["color"], gb.RISK_COLOR)

    def test_zero_is_measured_not_missing(self):
        report = gb.summarize({
            "top_bundler_trader_percentage": 0,
            "dev_team_hold_rate": 0,
        })
        self.assertTrue(report["ok"])
        self.assertEqual(report["bundler_rate"], 0)
        self.assertEqual(report["verdict"], "RENDAH")
        value, sub, tip = gb.cell_parts(report)
        self.assertEqual(value, "0.0%")
        self.assertIn("dev 0.0%", sub)
        self.assertIn("bukan bukti pasti", tip)

    def test_missing_field_stays_unknown(self):
        report = gb.summarize({"data": {"dev_team_hold_rate": "0.2"}})
        self.assertFalse(report["ok"])
        self.assertIsNone(report["bundler_rate"])
        self.assertEqual(gb.cell_parts(report)[0], "—")

    def test_warn_boundary(self):
        below = gb.summarize({"top_bundler_trader_percentage": 0.0499})
        at = gb.summarize({"top_bundler_trader_percentage": 0.05})
        self.assertEqual(below["verdict"], "RENDAH")
        self.assertEqual(at["verdict"], "WASPADA")


class BundlerAttachTest(unittest.TestCase):
    def test_attach_preserves_order_and_reuses_duplicate_mint(self):
        rows = [{"ca": MINT, "pool_address": "A"},
                {"ca": MINT, "pool_address": "B"},
                {"ca": "", "pool_address": "C"}]
        report = gb.summarize({"top_bundler_trader_percentage": "0.08"},
                              mint=MINT)
        with mock.patch.object(gb, "fetch_report", return_value=report) as fetch:
            result = gb.attach_to_rows(rows, workers=2, use_cache=False)
        self.assertEqual([row["pool_address"] for row in result], ["A", "B", "C"])
        fetch.assert_called_once()
        self.assertEqual(result[0]["bundler"]["bundler_rate"], 0.08)
        self.assertEqual(result[1]["bundler"]["bundler_rate"], 0.08)
        self.assertFalse(result[2]["bundler"]["ok"])


class BundlerPipelineTest(unittest.TestCase):
    def test_scanner_attaches_bundler_without_filtering_row(self):
        pool = {
            "pool_address": "PoolA",
            "token_x": {"address": MINT, "symbol": "TOK",
                        "market_cap": 1_000_000, "price": 0.01,
                        "top_holders_pct": 10.0},
            "token_y": {"address": ms.SOL_MINT, "symbol": "SOL",
                        "price": 100.0},
            "active_tvl": 100_000.0, "tvl": 120_000.0,
            "total_lps": 100, "fee_active_tvl_ratio": 30.0,
            "volatility": 6.0, "volume": 1_000_000.0, "fee_pct": 2.0,
        }

        def distribution(rows, **_kwargs):
            rows[0]["liquidity_distribution"] = {
                "checked": True, "ok": True, "token_value_usd": 80_000.0,
                "sol_value_usd": 100_000.0, "token_to_sol_ratio": 0.8,
                "error": ""}
            return rows

        def bundler(rows, **_kwargs):
            rows[0]["bundler"] = gb.summarize({
                "top_bundler_trader_percentage": "0.18"}, mint=MINT)
            return rows

        with mock.patch.object(ms, "fetch_best_pools", return_value=[pool]), \
                mock.patch.object(ms, "attach_liquidity_distribution",
                                  side_effect=distribution), \
                mock.patch.object(gb, "attach_to_rows", side_effect=bundler) as attach:
            result = ms.scan_best_lane(gmgn=False, bundler=True,
                                       rugcheck=False, tax=False)
        attach.assert_called_once()
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["bundler"]["bundler_rate"], 0.18)
        self.assertEqual(result["bundler_failed"], 0)


if __name__ == "__main__":
    unittest.main()
