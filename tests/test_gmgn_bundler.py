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

    def test_above_25_percent_verdict_but_no_longer_filters(self):
        report = gb.summarize({
            "top_bundler_trader_percentage": 0.18,
            "top_entrapment_trader_percentage": 0.08,
        })
        self.assertEqual(report["combined_rate"], 0.26)
        self.assertEqual(report["verdict"], "GAGAL")
        # Filter Bundler+Phishing dihapus 2026-09-28: verdict tetap dihitung
        # untuk kolom info, tapi tidak lagi menggugurkan pool.
        self.assertEqual(ms.row_bundler_phishing_gap({"bundler": report}), "")

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
        # Filter dihapus: data tak terbaca tidak lagi fail-closed ke "dilewati".
        self.assertEqual(ms.row_bundler_phishing_gap({"bundler": report}), "")


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
    def _pool(address="PoolA", *, mint=MINT, fee=80.0, volatility=6.0):
        return {
            "pool_address": address,
            "token_x": {"address": mint, "symbol": "TOK",
                        "market_cap": 1_000_000, "price": 0.01,
                        "top_holders_pct": 10.0},
            "token_y": {"address": ms.SOL_MINT, "symbol": "SOL", "price": 100.0},
            "active_tvl": 100_000.0, "tvl": 120_000.0, "total_lps": 100,
            "fee_active_tvl_ratio": fee, "volatility": volatility,
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

    def test_combined_above_25_no_longer_filters(self):
        # Filter Bundler+Phishing dihapus 2026-09-28: pool dengan combined 26%
        # tetap lolos ke tabel utama; datanya hanya ditempel untuk kolom info.
        result = self._scan(0.18, 0.08)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual(result["bundler_filter_failed"], 0)
        self.assertEqual(result["rows"][0]["bundler"]["combined_rate"], 0.26)

    def test_hidden_fv_candidates_also_fetch_bundler(self):
        visible = self._pool("VISIBLE", mint=MINT, fee=80.0, volatility=6.0)
        hidden = self._pool(
            "HIDDEN", mint="Hidden111111111111111111111111111111111",
            fee=30.0, volatility=6.0)  # F/V = 5×, masuk pool dilewati.
        dropped = self._pool(
            "DROPPED", mint="Dropped1111111111111111111111111111111",
            fee=24.0, volatility=6.0)  # F/V = 4×, dibuang total.
        seen_batches = []

        def distribution(rows, **_kwargs):
            for row in rows:
                row["liquidity_distribution"] = {
                    "checked": True, "ok": True,
                    "token_value_usd": 10_000.0,
                    "sol_value_usd": 100_000.0,
                    "token_to_sol_ratio": 0.1,
                    "error": ""}
            return rows

        def attach(rows, **_kwargs):
            seen_batches.append([row["pool_address"] for row in rows])
            for row in rows:
                row["bundler"] = gb.summarize({
                    "top_bundler_trader_percentage": 0.04,
                    "top_entrapment_trader_percentage": 0.03,
                }, mint=row.get("ca") or "")
            return rows

        with mock.patch.object(ms, "fetch_best_pools",
                               return_value=[visible, hidden, dropped]), \
                mock.patch.object(ms, "attach_liquidity_distribution",
                                  side_effect=distribution), \
                mock.patch.object(gb, "attach_to_rows", side_effect=attach):
            result = ms.scan_best_lane(gmgn=False, bundler=True,
                                       rugcheck=False, tax=False)

        self.assertEqual(seen_batches, [["VISIBLE", "HIDDEN"]])
        self.assertEqual([row["pool_address"] for row in result["rows"]],
                         ["VISIBLE"])
        self.assertEqual([row["pool_address"] for row in result["hidden_rows"]],
                         ["HIDDEN"])
        self.assertEqual(result["dropped_fv"], 1)
        self.assertEqual(result["dropped_total"], 1)
        self.assertEqual(result["hidden_rows"][0]["bundler"]["combined_rate"],
                         0.07)
        self.assertNotIn("DROPPED", [row["pool_address"]
                                      for row in result["rows"] + result["hidden_rows"]])


if __name__ == "__main__":
    unittest.main()
