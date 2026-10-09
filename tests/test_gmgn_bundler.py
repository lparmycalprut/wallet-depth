from __future__ import annotations

import unittest
from unittest import mock

import gmgn_bundler as gb
import meteora_screener as ms

MINT = "Token11111111111111111111111111111111111"


class BundlerSummaryTest(unittest.TestCase):
    def test_exactly_40_percent_is_informational_waspada(self):
        report = gb.summarize({"data": {
            "top_bundler_trader_percentage": "0.25",
            "top_entrapment_trader_percentage": "0.15",
            "dev_team_hold_rate": "0.0125",
            "top70_sniper_hold_rate": "0.03",
        }}, mint=MINT)
        self.assertTrue(report["ok"])
        self.assertEqual(report["combined_rate"], 0.40)
        self.assertEqual(report["verdict"], "WASPADA")
        self.assertEqual(ms.row_bundler_phishing_gap({"bundler": report}), "")

    def test_above_40_percent_is_only_an_informational_warning(self):
        report = gb.summarize({
            "top_bundler_trader_percentage": 0.25,
            "top_entrapment_trader_percentage": 0.16,
        })
        self.assertAlmostEqual(report["combined_rate"], 0.41)
        self.assertEqual(report["verdict"], "RISIKO TINGGI")
        value, sub, tip = gb.cell_parts(report)
        self.assertEqual(value, "41.0%")
        self.assertIn("⚠️ RISIKO TINGGI", sub)
        self.assertIn("hanya peringatan informasi", tip)
        self.assertIn("bukan filter", tip)
        self.assertNotIn("berkedip", tip)
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
        self.assertIn("hanya sebagai informasi", tip)
        self.assertIn("bukan filter", tip)

    def test_missing_either_field_stays_unknown_but_is_not_a_gate(self):
        report = gb.summarize({
            "top_bundler_trader_percentage": "0.1"})
        self.assertFalse(report["ok"])
        self.assertIsNone(report["combined_rate"])
        self.assertEqual(gb.cell_parts(report)[0], "—")
        # Report yang tidak terbaca tidak membuat kandidat gagal.
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

    def test_token_sol_and_bundler_never_change_eligibility(self):
        result = self._scan(0.15, 0.10)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["failed_liquidity_ratio"], 0)
        self.assertEqual(result["bundler_filter_failed"], 0)

    def test_combined_metric_remains_visible_in_main_table(self):
        # Persentase tetap ditampilkan sebagai informasi, bukan saringan.
        result = self._scan(0.18, 0.08)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual(result["bundler_filter_failed"], 0)
        self.assertEqual(result["rows"][0]["bundler"]["combined_rate"], 0.26)

    def test_high_combined_rate_still_passes_to_main_rows(self):
        result = self._scan(0.65, 0.25)  # gabungan 90% tidak lagi menyaring.
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual(result["bundler_filter_failed"], 0)
        self.assertFalse(result["bundler_phishing_filter"])
        self.assertAlmostEqual(result["rows"][0]["bundler"]["combined_rate"], 0.90)

    def test_unreadable_report_does_not_filter_or_skip_enrichment(self):
        def attach(rows, **_kwargs):
            rows[0]["bundler"] = gb.summarize({
                "top_bundler_trader_percentage": 0.8}, mint=MINT)
            return rows

        rug_rows = []
        tax_rows = []

        def rug_attach(rows, **_kwargs):
            rug_rows.extend(rows)
            return rows

        def tax_attach(rows, **_kwargs):
            tax_rows.extend(rows)
            return rows

        import rugchecker
        import token_tax

        with mock.patch.object(ms, "fetch_best_pools", return_value=[self._pool()]), \
                mock.patch.object(ms, "attach_liquidity_distribution",
                                  side_effect=self._distribution), \
                mock.patch.object(gb, "attach_to_rows", side_effect=attach), \
                mock.patch.object(rugchecker, "attach_to_rows",
                                  side_effect=rug_attach), \
                mock.patch.object(token_tax, "attach_to_rows",
                                  side_effect=tax_attach):
            result = ms.scan_best_lane(gmgn=False, bundler=True,
                                       rugcheck=True, tax=True)

        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual(result["bundler_failed"], 1)
        self.assertEqual(result["bundler_filter_failed"], 0)
        self.assertEqual(len(rug_rows), 1)
        self.assertEqual(len(tax_rows), 1)

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
