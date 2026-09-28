"""Focused contracts for the remaining Best Pool scanner and UI."""
from __future__ import annotations

import inspect
from pathlib import Path
import unittest
from unittest import mock

import best_pool_ui as bp
import meteora_screener as ms

ROOT = Path(__file__).resolve().parent.parent


def row(**overrides):
    data = {
        "pool_address": "pool",
        "ca": "Token11111111111111111111111111111111111",
        "symbol": "TOK",
        "pool_name": "TOK-SOL",
        "timeframe": "24h",
        "fee_active_tvl_ratio": 80.0,
        "volatility": 6.0,
        "total_lps": 100,
        "top_holders_pct": 10.0,
        "active_tvl": 100_000.0,
        "liquidity_distribution": {
            "checked": True,
            "ok": True,
            "token_value_usd": 80_000.0,
            "sol_value_usd": 100_000.0,
            "token_to_sol_ratio": 0.8,
            "error": "",
        },
    }
    data.update(overrides)
    return data


class BestPoolGateTest(unittest.TestCase):
    def test_threshold_constants(self):
        self.assertEqual(ms.BEST_ACTIVE_TVL_MIN, 50_000.0)
        self.assertEqual(ms.BEST_FV_24H_MIN, 10.0)
        self.assertEqual(ms.BEST_FV_HIDE_MIN, 10.0)
        self.assertEqual(ms.BEST_LPS_MIN, 100.0)
        self.assertFalse(hasattr(ms, "BEST_SOL_TOKEN_MAX_RATIO"))
        self.assertFalse(hasattr(ms, "BEST_TOKEN_SOL_MIN_RATIO"))

    def test_cheap_gate_boundaries(self):
        self.assertEqual(ms.row_best_gaps(row()), [])
        self.assertEqual(ms.row_best_gaps(row(total_lps=99))[0],
                         "24H: LPs 99 < 100 — LP terlalu sedikit")
        # F/V = 59.9/6.0 = 9,98× < 10× → gugur ambang lane (baru: 10×).
        self.assertIn("F/V < 10×", ms.row_best_gaps(
            row(fee_active_tvl_ratio=59.9, volatility=6.0))[0])
        # Tepat/di atas 10× lolos: F/V = 60.0/6.0 = 10,00×.
        self.assertEqual(ms.row_best_gaps(
            row(fee_active_tvl_ratio=60.0, volatility=6.0)), [])
        # Fee/TVL dinonaktifkan sebagai filter; angka tetap informasional.
        self.assertEqual(ms.row_best_gaps(
            row(fee_active_tvl_ratio=29.9, volatility=2.5)), [])
        self.assertIn("Top10 25%", ms.row_best_gaps(
            row(top_holders_pct=25.0))[0])

    def test_distribution_and_bundler_are_information_only(self):
        # Token:SOL tidak pernah menggugurkan pool (hanya informasi kolom).
        extreme = row(liquidity_distribution={
            "checked": True, "ok": True,
            "token_value_usd": 10_000.0, "sol_value_usd": 100_000.0,
            "token_to_sol_ratio": 0.1, "error": ""})
        self.assertEqual(ms.row_best_final_gaps(extreme), [])
        # Filter Bundler+Phishing dihapus 2026-09-28: bundler+phishing 26% tetap
        # lolos (datanya hanya informasi kolom, tidak menggugurkan pool).
        risky = row(bundler={
            "ok": True, "bundler_rate": 0.20, "phishing_rate": 0.06,
            "combined_rate": 0.26})
        self.assertEqual(ms.row_bundler_phishing_gap(risky), "")
        self.assertEqual(ms.row_best_final_gaps(risky), [])

    def test_low_fv_goes_to_skipped_not_dropped(self):
        # F/V di bawah 10× tidak lagi dibuang total — ia gugur ambang lane dan
        # tetap tampil di listing "pool dilewati" (permintaan user 2026-09-28).
        low = row(fee_active_tvl_ratio=30.0, volatility=6.0)  # F/V = 5×
        self.assertIn("F/V < 10×", ms.row_best_gaps(low)[0])
        self.assertIsNone(ms.row_fv_under_hide(low))
        self.assertFalse(ms.row_best_dropped(low))

    def test_scanner_has_no_wallet_analysis_parameters_or_imports(self):
        params = inspect.signature(ms.scan_best_lane).parameters
        self.assertNotIn("max_wallets", params)
        self.assertNotIn("progress", params)
        source = inspect.getsource(ms.scan_best_lane)
        self.assertNotIn("enrich_pools", source)
        self.assertNotIn("holder_history", source)


class BestPoolTableTest(unittest.TestCase):
    def test_all_columns_and_headers_are_preserved(self):
        titles = bp._lane_titles("24h", show_tax_dividend=True)
        self.assertEqual(titles, [
            "Token", "F/V", "Fee/TVL", "Volat", "Active Range", "LPs",
            "Token:SOL", "Bundler+Phishing", "Fee %", "MC", "A.TVL",
            "Vol 24h", "Top10", "RugCheck", "Pool", "TAX/DIVIDEND",
        ])
        self.assertEqual(len(titles), len(bp._col_spec(show_tax_dividend=True)))
        self.assertEqual(bp._lane_titles("24h", show_tax_dividend=False)[-1],
                         "Pool")
        self.assertNotIn("STRATEGY", titles)

    def test_mobile_css_uses_horizontal_scroll_not_cards_or_hidden_columns(self):
        css = (ROOT / "dashboard_components.py").read_text(encoding="utf-8")
        self.assertIn(".bp-table-scroll", css)
        self.assertIn("overflow-x:auto !important", css)
        self.assertIn("min-width:1458px", css)
        self.assertIn(".bp-table th:nth-child(16)", css)
        # Bundler ditambahkan tanpa menghidupkan kembali kolom STRATEGY.
        self.assertNotIn(".bp-table th:nth-child(17)", css)
        self.assertNotIn("hawkfi-copy-btn", css)
        self.assertNotIn("bp-strategy-range", css)
        self.assertNotIn("mobile-hide-next", css)
        self.assertNotIn("nth-child(n+6)", css)
        ui = (ROOT / "best_pool_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("mobile-hide-next", ui)
        self.assertIn('class="bp-table-scroll"', ui)
        self.assertIn('<table class="bp-table">', ui)

    def test_tooltip_states_correct_ratio_examples(self):
        tip = bp.best_pool_tooltip()
        self.assertIn("$50,000", tip)
        self.assertIn("LPs at least 100", tip)
        self.assertIn("F/V at least 10×", tip)
        self.assertIn("Token:SOL", tip)
        self.assertIn("informational only", tip)
        # Filter Bundler+Phishing dihapus: tooltip menyebut kolom info saja.
        self.assertNotIn("at most 25%", tip)
        self.assertIn("no longer filter a pool", tip)
        self.assertIn("horizontal scrolling", tip)

    def test_run_lane_scan_calls_pool_only_scanner(self):
        expected = {"rows": [], "hidden_rows": []}
        with mock.patch.object(ms, "scan_best_lane", return_value=expected) as scan:
            self.assertIs(bp._run_lane_scan("24h"), expected)
        scan.assert_called_once_with("24h", workers=6, bubblemap=False)


class AppSurfaceTest(unittest.TestCase):
    def test_removed_pages_and_automation_are_absent(self):
        for relative in (
            "pages/5_🧮_Holder.py", "pages/6_📦_TEMP.py", "temp_ui.py",
            "scripts/scan_holders.py", ".github/workflows/daily-effort.yml",
            "holder_history.py", "telegram_alerts.py",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_app_only_renders_best_pool_surface(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("render_best_pool_scan()", source)
        self.assertNotIn("page_router", source)
        self.assertNotIn("temp_ui", source)


if __name__ == "__main__":
    unittest.main()
