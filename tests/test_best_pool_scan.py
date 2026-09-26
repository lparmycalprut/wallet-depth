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
        "fee_active_tvl_ratio": 30.0,
        "volatility": 6.0,
        "total_lps": 100,
        "top_holders_pct": 10.0,
        "active_tvl": 100_000.0,
        "liquidity_distribution": {
            "checked": True,
            "ok": True,
            "token_value_usd": 20_000.0,
            "sol_value_usd": 100_000.0,
            "token_to_sol_ratio": 0.2,
            "error": "",
        },
    }
    data.update(overrides)
    return data


class BestPoolGateTest(unittest.TestCase):
    def test_threshold_constants(self):
        self.assertEqual(ms.BEST_ACTIVE_TVL_MIN, 100_000.0)
        self.assertEqual(ms.BEST_LPS_MIN, 100.0)
        self.assertEqual(ms.BEST_SOL_TOKEN_MIN_RATIO, 5.0)
        self.assertEqual(ms.BEST_TOKEN_SOL_MAX_RATIO, 0.2)

    def test_cheap_gate_boundaries(self):
        self.assertEqual(ms.row_best_gaps(row()), [])
        self.assertEqual(ms.row_best_gaps(row(total_lps=99))[0],
                         "24H: LPs 99 < 100 — LP terlalu sedikit")
        self.assertIn("F/V < 5×", ms.row_best_gaps(
            row(fee_active_tvl_ratio=29.9, volatility=6.0))[0])
        self.assertIn("Fee/TVL 29.9% < 30%", ms.row_best_gaps(
            row(fee_active_tvl_ratio=29.9, volatility=5.0))[0])
        self.assertIn("Top10 20%", ms.row_best_gaps(
            row(top_holders_pct=20.0))[0])

    def test_distribution_gate_is_additional_and_fail_closed(self):
        self.assertEqual(ms.row_best_final_gaps(row()), [])
        failed = row(liquidity_distribution={
            "checked": True, "ok": True,
            "token_value_usd": 25_000.0,
            "sol_value_usd": 100_000.0,
            "token_to_sol_ratio": 0.25,
            "error": "",
        })
        self.assertIn("SOL hanya 4× token", ms.row_best_final_gaps(failed)[0])
        missing = row(liquidity_distribution={
            "checked": True, "ok": False, "error": "timeout"})
        self.assertIn("timeout", ms.row_best_final_gaps(missing)[0])

    def test_scanner_has_no_wallet_analysis_parameters_or_imports(self):
        params = inspect.signature(ms.scan_best_lane).parameters
        self.assertNotIn("max_wallets", params)
        self.assertNotIn("progress", params)
        source = inspect.getsource(ms.scan_best_lane)
        self.assertNotIn("enrich_pools", source)
        self.assertNotIn("holder_history", source)


class BestPoolTableTest(unittest.TestCase):
    def test_all_columns_and_headers_are_preserved(self):
        titles = bp._lane_titles("24h", show_strategy=True)
        self.assertEqual(titles, [
            "Token", "F/V", "Fee/TVL", "Volat", "Active Range", "LPs",
            "Fee %", "MC", "A.TVL", "Vol 24h", "Top10", "RugCheck",
            "Pool", "TAX/DIVIDEND", "STRATEGY",
        ])
        self.assertEqual(len(titles), len(bp._col_spec(show_strategy=True)))
        self.assertEqual(bp._lane_titles("24h", show_strategy=False)[-1],
                         "Pool")

    def test_mobile_css_uses_horizontal_scroll_not_cards_or_hidden_columns(self):
        css = (ROOT / "dashboard_components.py").read_text(encoding="utf-8")
        self.assertIn(".bp-table-scroll", css)
        self.assertIn("overflow-x:auto !important", css)
        self.assertIn("min-width:1320px", css)
        self.assertIn(".bp-table th:nth-child(15)", css)
        self.assertNotIn("mobile-hide-next", css)
        self.assertNotIn("nth-child(n+6)", css)
        ui = (ROOT / "best_pool_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("mobile-hide-next", ui)
        self.assertIn('class="bp-table-scroll"', ui)
        self.assertIn('<table class="bp-table">', ui)

    def test_tooltip_states_correct_ratio_examples(self):
        tip = bp.best_pool_tooltip()
        self.assertIn("$100,000", tip)
        self.assertIn("LPs at least 100", tip)
        self.assertIn("Exact 1:5", tip)
        self.assertIn("1:6.52 pass", tip)
        self.assertIn("1:4 fails", tip)
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
