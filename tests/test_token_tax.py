"""Pajak transfer + dividend untuk kolom TAX/DIVIDEND (2026-09-23).

Dividend yang mengubah STRATEGY hanya StonkFun ``mode=reward`` atau pump.fun
``is_holder_reward is True``. Pajak, cashback, dan ``creator_reward`` tidak
pernah memakai teks ``30 70 spotbidask full range``.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ["TOKEN_TAX_FETCH"] = "0"

import best_pool_ui as bp
import gmgn_liquidity as gl
import token_tax as tt


REWARD = {
    "mode": "reward",
    "quoteOnlyFees": True,
    "transferFee": {"bps": 100},
}
STANDARD = {"mode": "standard"}
NOT_FOUND = {"error": {"code": "not_found"}}
HOLDER = {"is_holder_reward": True, "is_cashback_enabled": False}
CASHBACK = {"is_holder_reward": False, "is_cashback_enabled": True,
            "bonus_category": "creator_reward"}


class ParseTest(unittest.TestCase):
    def test_stonkfun_reward_adalah_dividend_dan_100_bps_jadi_1_persen(self):
        parsed = tt.parse_stonkfun(REWARD)
        self.assertTrue(parsed["answered"])
        self.assertTrue(parsed["dividend"])
        self.assertEqual(parsed["mode"], "reward")
        self.assertEqual(parsed["tax_pct"], 1.0)
        # quoteOnlyFees ikut di payload reward, tetapi bukan pemicu sendiri.
        self.assertTrue(REWARD["quoteOnlyFees"])

    def test_stonkfun_standard_dan_not_found_bukan_dividend(self):
        standard = tt.parse_stonkfun(STANDARD)
        self.assertTrue(standard["answered"])
        self.assertFalse(standard["dividend"])
        self.assertEqual(standard["mode"], "standard")
        missing = tt.parse_stonkfun(NOT_FOUND, status=200)
        self.assertTrue(missing["answered"])
        self.assertTrue(missing["not_found"])
        self.assertFalse(missing["dividend"])
        self.assertTrue(tt.parse_stonkfun({}, status=404)["answered"])
        self.assertFalse(tt.parse_stonkfun({}, status=404)["dividend"])

    def test_quote_only_dan_pajak_jupiter_bukan_dividend(self):
        self.assertFalse(tt.parse_stonkfun(
            {"mode": "standard", "quoteOnlyFees": True})["dividend"])
        self.assertIsNone(tt.parse_stonkfun(
            {"quoteOnlyFees": True}).get("dividend") or None)
        pct = tt.transfer_fee_pct_from_token({
            "warnings": [{
                "type": "TRANSFER_FEE_CONFIGURED",
                "message": "token has a transfer fee of 1.00%",
            }],
        })
        self.assertEqual(pct, 1.0)

    def test_pump_hanya_is_holder_reward_true(self):
        yes = tt.parse_pump(HOLDER)
        self.assertTrue(yes["answered"])
        self.assertTrue(yes["dividend"])
        no = tt.parse_pump(CASHBACK)
        self.assertTrue(no["answered"])
        self.assertFalse(no["dividend"])
        # Tanpa field-nya: jangan menebak dari cashback / creator_reward.
        blank = tt.parse_pump({"is_cashback_enabled": True,
                               "bonus_category": "creator_reward"})
        self.assertFalse(blank["answered"])
        self.assertFalse(blank["dividend"])
        self.assertTrue(tt.parse_pump({}, status=404)["answered"])
        self.assertFalse(tt.parse_pump({}, status=404)["dividend"])

    def test_combine_satu_sumber_gagal_tidak_mengunci_bukan_dividend(self):
        known_no = tt.combine(tt.parse_stonkfun(STANDARD),
                              tt.parse_pump(CASHBACK))
        self.assertFalse(known_no["dividend"])
        self.assertTrue(known_no["dividend_known"])
        unknown = tt.combine(tt.parse_stonkfun(STANDARD), tt._blank_parse())
        self.assertFalse(unknown["dividend"])
        self.assertFalse(unknown["dividend_known"])
        reward = tt.combine(tt.parse_stonkfun(REWARD), tt._blank_parse())
        self.assertTrue(reward["dividend"])
        self.assertTrue(reward["dividend_known"])
        self.assertEqual(reward["tax_pct"], 1.0)
        self.assertEqual(reward["source"], "stonkfun")

    def test_label_tidak_menulis_tax_0(self):
        self.assertEqual(tt.label_for(1, True), "tax 1% · dividend")
        self.assertEqual(tt.label_for(1.5, False), "tax 1.5%")
        self.assertEqual(tt.label_for(None, True), "dividend")
        self.assertEqual(tt.label_for(0, False), "—")
        self.assertEqual(tt.label_for(None, False), "—")


class StrategyOverrideTest(unittest.TestCase):
    def test_dividend_mengalahkan_likuiditas_di_atas_500k(self):
        row = {
            "rugcheck": {"ok": True, "liquidity_total_usd": 884_912.0,
                         "liquidity_source": "gmgn"},
            "tax_dividend": {"dividend": True, "dividend_known": True,
                             "source": "stonkfun", "mode": "reward",
                             "tax_pct": 1.0},
        }
        info = gl.row_strategy(row)
        self.assertEqual(info["text"], "30 70 spotbidask full range")
        self.assertEqual(info["text"], gl.STRATEGY_DIVIDEND)
        self.assertTrue(info["dividend"])
        self.assertNotIn("hybird", info["text"])
        value, sub, tip = bp._strategy_cell(row)
        self.assertIn(
            '<div class="watchlist-metric-value">30 70 spotbidask full range'
            '</div>',
            bp._cell(value, sub, tip))
        self.assertEqual(sub, "dividend")
        self.assertIn("30 70 spotbidask full range", tip)
        self.assertIn("$500K", tip)

    def test_pajak_saja_tidak_mengubah_strategi(self):
        row = {
            "rugcheck": {"ok": True, "liquidity_total_usd": 884_912.0,
                         "liquidity_source": "gmgn", "transfer_fee": 1.0},
            "transfer_fee_pct": 1.0,
            "tax_dividend": {"dividend": False, "dividend_known": True,
                             "source": "stonkfun", "mode": "standard",
                             "tax_pct": 1.0},
        }
        info = gl.row_strategy(row)
        self.assertEqual(info["text"], gl.STRATEGY_LIQ_HIGH)
        self.assertFalse(info["dividend"])
        cell = tt.row_tax_dividend(row)
        self.assertEqual(cell["label"], "tax 1%")
        self.assertFalse(cell["dividend"])
        html = bp._tax_dividend_cell_html(cell)
        self.assertIn("tax 1%", html)
        self.assertNotIn("bp-dividend", html)
        self.assertIn("bp-tax-dividend", html)

    def test_belum_terbaca_tetap_cabang_likuiditas_dan_strip(self):
        row = {"rugcheck": {"ok": True, "liquidity_total_usd": 103_300.0,
                            "liquidity_source": "gmgn"}}
        info = gl.row_strategy(row)
        self.assertEqual(info["text"], gl.STRATEGY_LIQ_LOW)
        self.assertFalse(info["dividend"])
        self.assertFalse(tt.row_has_dividend(row))
        label = tt.row_tax_dividend(row)["label"]
        self.assertEqual(label, "—")

    def test_pajak_lokal_tampil_tanpa_override(self):
        row = {"transfer_fee_pct": 2.5}
        cell = tt.row_tax_dividend(row)
        self.assertEqual(cell["label"], "tax 2.5%")
        self.assertFalse(cell["dividend"])
        self.assertEqual(gl.row_strategy(row)["text"], gl.STRATEGY_LIQ_LOW)


class FetchGuardTest(unittest.TestCase):
    def test_kill_switch_tidak_http_dan_tidak_menandai_dividend(self):
        with mock.patch.object(tt, "_get_json",
                               side_effect=AssertionError("HTTP")):
            rows = tt.attach_to_rows([{"ca": "MintAAA", "symbol": "AAA"}])
        self.assertEqual(rows[0]["tax_dividend"]["error"], "TOKEN_TAX_FETCH=0")
        self.assertFalse(rows[0]["tax_dividend"]["dividend"])
        self.assertFalse(rows[0]["tax_dividend"]["fetched"])
        self.assertFalse(tt.row_has_dividend(rows[0]))

    def test_fetch_reward_tidak_memanggil_pump(self):
        calls = []

        def fake_get(url, **_kw):
            calls.append(url)
            if "stonkfun" in url:
                return 200, REWARD
            raise AssertionError(url)

        with mock.patch.dict(os.environ, {"TOKEN_TAX_FETCH": "1"}), \
                mock.patch.object(tt, "_get_json", side_effect=fake_get), \
                mock.patch.object(tt, "_cache_get", return_value=None), \
                mock.patch.object(tt, "_cache_put"):
            report = tt.fetch_report("MintReward", use_cache=False)
        self.assertEqual(len(calls), 1)
        self.assertIn("stonkfun", calls[0])
        self.assertTrue(report["dividend"])
        self.assertTrue(report["dividend_known"])
        self.assertEqual(report["tax_pct"], 1.0)

    def test_keduanya_gagal_belum_diketahui(self):
        with mock.patch.dict(os.environ, {"TOKEN_TAX_FETCH": "1"}), \
                mock.patch.object(tt, "_get_json",
                                  side_effect=RuntimeError("down")), \
                mock.patch.object(tt, "_cache_get", return_value=None):
            report = tt.fetch_report("MintDown", use_cache=False)
        self.assertFalse(report["dividend"])
        self.assertFalse(report["dividend_known"])
        self.assertTrue(report["fetched"])


class ColumnPlacementTest(unittest.TestCase):
    def test_sel_pajak_di_kiri_strategy_dan_teks_dividend_di_strategy(self):
        import types

        rendered = []
        st_palsu = types.ModuleType("streamlit")
        st_palsu.markdown = lambda html, **_kw: rendered.append(html)
        row = {
            "ca": "MintDiv", "symbol": "DIV", "pool_address": "PoolDiv",
            "fee_active_tvl_ratio": 40.0, "volatility": 6.2,
            "rugcheck": {"ok": True, "liquidity_total_usd": 900_000.0,
                         "liquidity_source": "gmgn"},
            "tax_dividend": {"dividend": True, "dividend_known": True,
                             "tax_pct": 1.0, "source": "pump",
                             "mode": "holder_reward"},
        }
        with mock.patch.dict("sys.modules", {"streamlit": st_palsu}):
            bp._render_best_table([row], lane="24h", mark_tops=False)
        body = "".join(rendered)
        self.assertEqual(body.count("<th scope=\"col\">"), 15)
        self.assertIn(">TAX/DIVIDEND<", body)
        self.assertIn(">STRATEGY<", body)
        self.assertIn("tax 1%", body)
        self.assertIn("bp-dividend", body)
        self.assertIn("30 70 spotbidask full range", body)
        self.assertNotIn("hybird", body)

    def test_tabel_dilewati_tanpa_kolom_pajak(self):
        titles = bp._lane_titles("24h", show_strategy=False)
        self.assertEqual(titles[-1], "Pool")
        self.assertNotIn("TAX/DIVIDEND", titles)
        self.assertEqual(len(bp._col_spec(show_strategy=True)),
                         len(bp._col_spec(show_strategy=False)) + 2)


if __name__ == "__main__":
    unittest.main()
