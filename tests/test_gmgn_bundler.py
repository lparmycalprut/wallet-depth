from __future__ import annotations

import unittest
from unittest import mock

import gmgn_bundler as gb
import meteora_screener as ms

MINT = "Token11111111111111111111111111111111111"


class BundlerSummaryTest(unittest.TestCase):
    def test_combined_boundary_exactly_25_percent_passes(self):
        report = gb.summarize({"data": {
            "top_bundler_trader_percentage": "0.15",
            "top_entrapment_trader_percentage": "0.10",
            "dev_team_hold_rate": "0.0125",
            "top70_sniper_hold_rate": "0.03",
        }}, mint=MINT)
        self.assertTrue(report["ok"])
        self.assertEqual(report["combined_rate"], 0.25)
        self.assertEqual(report["verdict"], "WASPADA")
        self.assertEqual(ms.row_bundler_phishing_gap({"bundler": report}), "")

    def test_above_25_percent_fails(self):
        report = gb.summarize({
            "top_bundler_trader_percentage": 0.18,
            "top_entrapment_trader_percentage": 0.08,
        })
        self.assertEqual(report["combined_rate"], 0.26)
        self.assertEqual(report["verdict"], "GAGAL")
        self.assertIn("26.00% > maksimum 25%",
                      ms.row_bundler_phishing_gap({"bundler": report}))

    def test_zero_is_measured_not_missing(self):
        report = gb.summarize({
            "top_bundler_trader_percentage": 0,
            "top_entrapment_trader_percentage": 0,
            "dev_team_hold_rate": 0,
        })
        self.assertTrue(report["ok"])
        self.assertEqual(report["combined_rate"], 0)
        value, sub, tip = gb.cell_parts(report)
        self.assertEqual(value, "0.0%")
        self.assertIn("B 0.0% · P 0.0%", sub)
        self.assertIn("maksimal 25%", tip)

    def test_missing_either_field_stays_unknown_and_fails_closed(self):
        report = gb.summarize({
            "top_bundler_trader_percentage": "0.1"})
        self.assertFalse(report["ok"])
        self.assertIsNone(report["combined_rate"])
        self.assertEqual(gb.cell_parts(report)[0], "—")
        self.assertIn("GMGN gagal",
                      ms.row_bundler_phishing_gap({"bundler": report}))


class BundlerAttachTest(unittest.TestCase):
    def test_attach_preserves_order_and_reuses_duplicate_mint(self):
        rows = [{"ca": MINT, "pool_address": "A"},
                {"ca": MINT, "pool_address": "B"},
                {"ca": "", "pool_address": "C"}]
        report = gb.summarize({
            "top_bundler_trader_percentage": "0.08",
            "top_entrapment_trader_percentage": "0.04"}, mint=MINT)
        with mock.patch.object(gb, "fetch_report", return_value=report) as fetch:
            result = gb.attach_to_rows(rows, workers=2, use_cache=False)
        self.assertEqual([row["pool_address"] for row in result], ["A", "B", "C"])
        fetch.assert_called_once()
        self.assertEqual(result[0]["bundler"]["combined_rate"], 0.12)
        self.assertEqual(result[1]["bundler"]["combined_rate"], 0.12)
        self.assertFalse(result[2]["bundler"]["ok"])


class BundlerPipelineTest(unittest.TestCase):
    @staticmethod
    def _pool():
        return {
            "pool_address": "PoolA",
            "token_x": {"address": MINT, "symbol": "TOK",
                        "market_cap": 1_000_000, "price": 0.01,
                        "top_holders_pct": 10.0},
            "token_y": {"address": ms.SOL_MINT, "symbol": "SOL", "price": 100.0},
            "active_tvl": 100_000.0, "tvl": 120_000.0, "total_lps": 100,
            "fee_active_tvl_ratio": 80.0, "volatility": 6.0,
            "volume": 1_000_000.0, "fee_pct": 2.0,
        }

    @staticmethod
    def _distribution(rows, **_kwargs):
        rows[0]["liquidity_distribution"] = {
            "checked": True, "ok": True, "token_value_usd": 10_000.0,
            "sol_value_usd": 100_000.0, "token_to_sol_ratio": 0.1,
            "error": ""}
        return rows

    def _scan(self, bundler_rate, phishing_rate):
        def attach(rows, **_kwargs):
            rows[0]["bundler"] = gb.summarize({
                "top_bundler_trader_percentage": bundler_rate,
                "top_entrapment_trader_percentage": phishing_rate}, mint=MINT)
            return rows
        with mock.patch.object(ms, "fetch_best_pools", return_value=[self._pool()]), \
                mock.patch.object(ms, "attach_liquidity_distribution",
                                  side_effect=self._distribution), \
                mock.patch.object(gb, "attach_to_rows", side_effect=attach):
            return ms.scan_best_lane(gmgn=False, bundler=True,
                                     rugcheck=False, tax=False)

    def test_token_sol_no_longer_filters_and_combined_25_passes(self):
        result = self._scan(0.15, 0.10)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["failed_liquidity_ratio"], 0)
        self.assertEqual(result["bundler_filter_failed"], 0)

    def test_combined_above_25_moves_to_skipped(self):
        result = self._scan(0.18, 0.08)
        self.assertEqual(result["rows"], [])
        self.assertEqual(len(result["hidden_rows"]), 1)
        self.assertEqual(result["bundler_filter_failed"], 1)
        self.assertIn("Bundler+Phishing 26.00%",
                      result["hidden_rows"][0]["best_gaps"][0])


if __name__ == "__main__":
    unittest.main()
