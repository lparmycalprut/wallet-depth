# -*- coding: utf-8 -*-
"""Saringan Best Pool **Fee/TVL ≥ 5%** dan **Fee-IL ≥ +5 poin** (2026-11-02).

Permintaan user 2026-11-02:
- "rubah minimal fee/tvl 5x yang di show" → Fee/TVL minimal 5 (persen);
- "terapkan juga detail di tabel" → kolom TVL/Fee/TVL/perubahan harga/IL/Fee-IL;
- "filter hanya show jika Fee-IL minimal +5%" → hanya Fee-IL ≥ +5 tampil.

Fee-IL = Fee/TVL (``fee_active_tvl_ratio``) + IL pool 50/50 CPMM atas
perubahan harga 24 jam (``pool_price_change_pct``). Semua tes offline.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import meteora_screener as ms  # noqa: E402

SOL = ms.SOL_MINT
OLD_POOL_MS = 1_700_000_000_000  # pool dibuat jauh lebih dari 24 jam lalu
NOW_MS = 1_800_000_000_000


def _row(**overrides):
    row = {
        "ca": "MintFEEIL", "symbol": "FIL", "pool_address": "PoolFEEIL",
        "fee_active_tvl_ratio": 20.0,
        "price_change_pct": 0.0,
        "pool_created_at": OLD_POOL_MS,
    }
    row.update(overrides)
    return row


class ImpermanentLossFormulaTest(unittest.TestCase):
    def test_tanpa_perubahan_harga_il_nol(self):
        self.assertAlmostEqual(ms.il_pct_from_change(0.0), 0.0, places=9)

    def test_nilai_referensi(self):
        # r = 2 → 2√2/3 − 1 ≈ −5,72%; r = 3 → ≈ −13,40%; r = 0,1 → ≈ −42,5%.
        self.assertAlmostEqual(ms.il_pct_from_change(100.0), -5.719, places=2)
        self.assertAlmostEqual(ms.il_pct_from_change(200.0), -13.397, places=2)
        self.assertAlmostEqual(ms.il_pct_from_change(-90.0), -42.5, places=1)

    def test_il_tidak_pernah_positif(self):
        for change in (-99.0, -50.0, -10.0, 0.5, 10.0, 142.0, 1000.0):
            with self.subTest(change=change):
                self.assertLessEqual(ms.il_pct_from_change(change), 0.0)

    def test_input_tidak_valid_jadi_none(self):
        self.assertIsNone(ms.il_pct_from_change(None))
        self.assertIsNone(ms.il_pct_from_change(float("nan")))
        self.assertIsNone(ms.il_pct_from_change(-100.0))  # r = 0
        self.assertIsNone(ms.il_pct_from_change(-150.0))  # r < 0


class RowIlTest(unittest.TestCase):
    def test_pool_tua_tanpa_perubahan_dihitung_nol(self):
        self.assertAlmostEqual(
            ms.row_il_pct(_row(), now_ms=NOW_MS), 0.0, places=9)

    def test_pool_muda_tanpa_perubahan_belum_terukur(self):
        young = _row(pool_created_at=NOW_MS - 3_600_000)  # 1 jam lalu
        self.assertIsNone(ms.row_il_pct(young, now_ms=NOW_MS))

    def test_tanpa_tanggal_pembuatan_dan_tanpa_perubahan_belum_terukur(self):
        self.assertIsNone(ms.row_il_pct(
            _row(pool_created_at=None), now_ms=NOW_MS))

    def test_perubahan_nol_tidak_perlu_umur_jika_ada_perubahan(self):
        # Pool muda tetapi harga sudah bergerak: IL tetap dihitung.
        young = _row(pool_created_at=NOW_MS - 3_600_000, price_change_pct=100)
        self.assertAlmostEqual(ms.row_il_pct(young, now_ms=NOW_MS),
                               -5.719, places=2)

    def test_tanpa_perubahan_harga_belum_terukur(self):
        self.assertIsNone(ms.row_il_pct(
            _row(price_change_pct=None), now_ms=NOW_MS))


class FeeIlGateTest(unittest.TestCase):
    def test_fee_il_sama_dengan_fee_ditambah_il(self):
        gap = ms.row_fee_minus_il(
            _row(fee_active_tvl_ratio=16.39, price_change_pct=142.0),
            now_ms=NOW_MS)
        self.assertAlmostEqual(gap, 16.39 - 9.03, places=1)

    def test_lolos_bila_fee_il_dan_fee_memenuhi(self):
        self.assertIsNone(ms.row_fee_il_gap(
            _row(fee_active_tvl_ratio=20.0, price_change_pct=100.0),
            now_ms=NOW_MS))  # 20 − 5,72 = 14,28 ≥ 5

    def test_batas_inklusif_tepat_lima(self):
        self.assertIsNone(ms.row_fee_il_gap(
            _row(fee_active_tvl_ratio=5.0), now_ms=NOW_MS))

    def test_fee_il_di_bawah_lima_gugur(self):
        # Fee 9 dengan harga naik 300% → IL −20 → Fee-IL −11.
        reason = ms.row_fee_il_gap(
            _row(fee_active_tvl_ratio=9.0, price_change_pct=300.0),
            now_ms=NOW_MS)
        self.assertIsNotNone(reason)
        self.assertIn("Fee-IL", reason)

    def test_fee_di_bawah_lima_gugur_walau_il_nol(self):
        reason = ms.row_fee_il_gap(
            _row(fee_active_tvl_ratio=4.9), now_ms=NOW_MS)
        self.assertIn("Fee/TVL", reason)

    def test_fee_il_tak_terukur_ikut_gugur(self):
        reason = ms.row_fee_il_gap(
            _row(fee_active_tvl_ratio=30.0, price_change_pct=0.0,
                 pool_created_at=NOW_MS - 60_000), now_ms=NOW_MS)
        self.assertIn("tidak terukur", reason)

    def test_fee_hilang_gugur(self):
        self.assertIsNotNone(ms.row_fee_il_gap(
            _row(fee_active_tvl_ratio=None), now_ms=NOW_MS))

    def test_filter_menghitung_yang_gugur(self):
        rows = [
            _row(pool_address="A", fee_active_tvl_ratio=16.0,
                 price_change_pct=142.0),
            _row(pool_address="B", fee_active_tvl_ratio=4.0),
            _row(pool_address="C", fee_active_tvl_ratio=9.0,
                 price_change_pct=300.0),
            _row(pool_address="D", fee_active_tvl_ratio=12.0,
                 price_change_pct=0.0, pool_created_at=NOW_MS - 1000),
        ]
        kept, dropped = ms.filter_fee_il_rows(rows, now_ms=NOW_MS)
        self.assertEqual([row["pool_address"] for row in kept], ["A"])
        self.assertEqual(dropped, 3)

    def test_ambang_konstanta_sesuai_permintaan(self):
        self.assertEqual(ms.BEST_FEE_TVL_MIN, 5.0)
        self.assertEqual(ms.BEST_FEE_MINUS_IL_MIN, 5.0)


class PoolRowFieldsTest(unittest.TestCase):
    def test_row_membawa_perubahan_harga_dan_umur_pool(self):
        pool = {
            "pool_address": "PoolX", "pool_type": "dlmm",
            "name": "TOK-SOL", "timeframe": "24h",
            "token_x": {"address": "MintX", "symbol": "TOK", "price": 0.1,
                        "market_cap": 1_000_000, "top_holders_pct": 10.0},
            "token_y": {"address": SOL, "symbol": "SOL", "price": 100.0},
            "tvl": 150_000.0, "active_tvl": 120_000.0,
            "fee_active_tvl_ratio": 12.0, "volume": 2_000_000.0,
            "fee": 48_000.0, "volatility": 6.0, "total_lps": 188,
            "pool_price_change_pct": -35.5,
            "pool_created_at": OLD_POOL_MS,
        }
        rows = ms.rows_from_pools([pool], timeframe="24h")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_change_pct"], -35.5)
        self.assertEqual(rows[0]["pool_created_at"], float(OLD_POOL_MS))

    def test_pool_tanpa_field_baru_menghasilkan_none(self):
        pool = {"pool_address": "PoolY", "token_x": {"address": "MintY"},
                "token_y": {"address": SOL}, "fee_active_tvl_ratio": 9.0}
        rows = ms.rows_from_pools([pool], timeframe="24h")
        self.assertIsNone(rows[0]["price_change_pct"])
        self.assertIsNone(rows[0]["pool_created_at"])


class ScanFeeIlFilterTest(unittest.TestCase):
    """Filter berjalan di ``scan_best_lane``: pool gugur tidak masuk tabel
    utama maupun daftar "dilewati" dan jumlahnya dicatat."""

    @staticmethod
    def _pool(address, mint, *, ratio, change, created=OLD_POOL_MS):
        return {
            "pool_address": address,
            "token_x": {"address": mint, "symbol": address,
                        "market_cap": 1_000_000, "price": 0.01,
                        "top_holders_pct": 10.0},
            "token_y": {"address": SOL, "symbol": "SOL", "price": 100.0},
            "active_tvl": 100_000.0, "tvl": 120_000.0, "total_lps": 188,
            # F/V = fee/volatility = 16/1,5 ≈ 10,7× (lolos ≥ 10×); volatilitas
            # 1,5% berada di rentang tampil 1%–10%.
            "fee_active_tvl_ratio": ratio, "volatility": 1.5,
            "volume": 1_000_000.0, "fee_pct": 2.0, "fee": 20_000.0,
            "pool_price_change_pct": change, "pool_created_at": created,
        }

    def _scan(self, pools):
        def fake_fetch(**_kw):
            return pools

        def fake_distribution(rows, **_kw):
            for item in rows:
                item["liquidity_distribution"] = {
                    "checked": True, "ok": True,
                    "token_value_usd": 100_000.0,
                    "sol_value_usd": 100_000.0,
                    "token_to_sol_ratio": 1.0, "error": ""}
            return rows

        def fake_gmgn(rows, **_kw):
            for row in rows:
                row["gmgn_liq"] = {"ok": False}
            return rows

        with patch.object(ms, "fetch_best_pools", side_effect=fake_fetch), \
                patch.object(ms, "attach_liquidity_distribution",
                             side_effect=fake_distribution), \
                patch("rugchecker.attach_to_rows",
                      side_effect=lambda rows, **_kw: [
                          dict(row, rugcheck={"ok": False}) for row in rows]), \
                patch("gmgn_liquidity.attach_total_liquidity",
                      side_effect=fake_gmgn):
            return ms.scan_best_lane("24h", rugcheck=True, bundler=False)

    def test_pool_gagal_fee_il_tidak_muncul_dimana_pun(self):
        pools = [
            self._pool("GOOD", "MintGOOD", ratio=16.0, change=142.0),
            self._pool("LOWFEE", "MintLOW", ratio=4.0, change=0.0),
            self._pool("BADIL", "MintBAD", ratio=9.0, change=300.0),
        ]
        result = self._scan(pools)
        visible = [row["pool_address"] for row in result["rows"]]
        hidden = [row["pool_address"] for row in result["hidden_rows"]]
        self.assertEqual(visible, ["GOOD"])
        self.assertNotIn("LOWFEE", hidden)
        self.assertNotIn("BADIL", hidden)
        self.assertEqual(result["dropped_fee_il"], 2)
        self.assertIn("fee_active_tvl_ratio", result["rows"][0])
        self.assertIn("price_change_pct", result["rows"][0])

    def test_pool_lolos_fee_il_tampil_dengan_kolom_il(self):
        result = self._scan([
            self._pool("GOOD", "MintGOOD", ratio=16.0, change=142.0)])
        row = result["rows"][0]
        self.assertAlmostEqual(
            ms.row_fee_minus_il(row, now_ms=NOW_MS), 16.0 - 9.03, places=1)
        self.assertEqual(result["dropped_fee_il"], 0)


class ColumnDetailTest(unittest.TestCase):
    def test_kolom_fee_il_setelah_fee_tvl(self):
        from best_pool_ui import _lane_titles
        titles = _lane_titles("24h")
        self.assertEqual(titles[2:5], ["Fee/TVL", "Fee-IL", "Total IL"])
        self.assertEqual(len(titles), 18)

    def test_sel_fee_il_menampilkan_harga_dan_il(self):
        import best_pool_ui as bp
        import types
        from unittest import mock

        rendered = []
        st_palsu = types.ModuleType("streamlit")
        st_palsu.markdown = lambda html, **_kw: rendered.append(html)
        row = _row(ca="MintX", symbol="X", pool_address="PX",
                   fee_active_tvl_ratio=16.39, price_change_pct=142.0,
                   fee=28_900.0, active_tvl=179_600.0, tvl=179_600.0,
                   fee_pct=2.0, volatility=2.0, total_lps=200,
                   volume=1_200_000.0)
        with mock.patch.dict("sys.modules", {"streamlit": st_palsu}):
            bp._render_best_table([row], lane="24h", mark_tops=False)
        body = "".join(rendered)
        self.assertIn(">Fee-IL<", body)
        self.assertIn("harga +142.0%", body)
        self.assertIn("IL -9.0%", body)
        self.assertIn("+7.4%", body)


if __name__ == "__main__":
    unittest.main()
