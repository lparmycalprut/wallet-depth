"""🆕 Deteksi POOL BARU di 🏆 Scan Best Pool (permintaan user 2026-09-24).

Syarat (enam): umur pool < 12 jam, active TVL > 75K, fee/active TVL > 20%,
0 < volatility < 15%, LPs >= 100 (inklusif — tepat 100 lolos; angka hilang
= tidak memenuhi) dan top holders < 20%. Contoh acuan user: familiars-SOL
harus muncul di hasil scan, bertanda "POOL BARU", dengan STRATEGY
"50 50 spotba, bidask".

Lanjutan 2026-09-24 (laporan user: tulisan POOL BARU tidak muncul di app):
penyebabnya hasil scan LAMA di session_state/scan_result_cache (dibuat
sebelum PR #212) tidak punya ``pool_created_at``/``fetched_at`` →
``row_new_pool`` False saat render. Perbaikannya: keputusan deteksi dibuat
sekali saat scan — ``scan_best_lane`` menandai ``row["new_pool"]`` — dan
render memakai flag itu ATAU ``row_new_pool(row)`` (dihitung ulang terhadap
``fetched_at`` baris, bukan jam render).
"""
import unittest
from pathlib import Path
from unittest import mock

import meteora_screener as ms
from gmgn_liquidity import STRATEGY_NEW_POOL, row_strategy

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

# Potongan payload API asli (response user 2026-09-24).
FETCHED_AT = 1790206791 + 2 * 3600  # 2 jam setelah pool dibuat

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _familiars_pool(**over):
    pool = {
        "pool_address": "ET9QEc18XnEXNyz8ZuGkJfgSuDDqLDiA1U8bEpyuyLKC",
        "name": "familiars-SOL",
        "token_x": {
            "address": "2PENPmfgJfq6CG3k4byj4oWwHf8SerqakmYHMkUupump",
            "symbol": "familiars", "name": "familiars.family",
            "market_cap": 2078479.25, "price": 0.00218, "holders": 4258,
            "warnings": [], "top_holders_pct": 14.677167252514254,
        },
        "token_y": {"address": ms.SOL_MINT, "symbol": "SOL"},
        "pool_type": "dlmm", "fee_pct": 2.0,
        "pool_created_at": 1790206791000,
        "dlmm_params": {"bin_step": 100},
        "tvl": 112664.66744021911,
        "active_tvl": 112294.36385085656,
        "fee_active_tvl_ratio": 34.09200065211515,
        "volume_active_tvl_ratio": 1031.868642418687,
        "volume": 1158730.327780534, "fee": 38283.395256322576,
        "total_lps": 230.0,
        "volatility": 10.37084454997201,
    }
    pool.update(over)
    return pool


def _row(**over):
    with mock.patch.object(ms.time, "time", return_value=FETCHED_AT):
        return ms.rows_from_pools([_familiars_pool(**over)])[0]


def _scan(pools):
    """``scan_best_lane`` offline untuk satu set pool (waktu dipin)."""
    with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
            mock.patch.object(ms, "enrich_pools",
                              side_effect=lambda rows, **kw: rows), \
            mock.patch.object(ms.time, "time", return_value=FETCHED_AT):
        return ms.scan_best_lane(rugcheck=False, gmgn=False, tax=False,
                                 max_wallets=10)


class NewPoolDetectionTest(unittest.TestCase):
    def test_familiars_lolos_sebagai_pool_baru(self):
        row = _row()
        self.assertEqual(row["fetched_at"], FETCHED_AT)
        self.assertAlmostEqual(ms.row_pool_age_hours(row), 2.0, places=3)
        self.assertTrue(ms.row_new_pool(row))
        # Tanpa jalur pool baru ia gugur (F/V 3,3× & volatility > 10%).
        self.assertEqual(ms.row_best_gaps(row), [])
        self.assertFalse(ms.row_best_dropped(row))
        kept, hidden, _ = ms.filter_best_rows([row])
        self.assertEqual(len(kept), 1)
        self.assertEqual(hidden, 0)

    def test_strategy_pool_baru(self):
        info = row_strategy(_row())
        self.assertEqual(info["text"], "50 50 spotba, bidask")
        self.assertEqual(STRATEGY_NEW_POOL, "50 50 spotba, bidask")
        self.assertTrue(info.get("new_pool"))

    def test_batas_eksklusif_tiap_syarat(self):
        cases = {
            "umur": {"pool_created_at": (FETCHED_AT - 12 * 3600) * 1000},
            "active TVL": {"active_tvl": 75_000.0},
            "fee/active TVL": {"fee_active_tvl_ratio": 20.0},
            "volatility": {"volatility": 15.0},
        }
        for gap, over in cases.items():
            with self.subTest(gap=gap):
                row = _row(**over)
                self.assertIn(gap, ms.row_new_pool_gaps(row))
                self.assertFalse(ms.row_new_pool(row))
        pool = _familiars_pool()
        pool["token_x"] = dict(pool["token_x"], top_holders_pct=20.0)
        with mock.patch.object(ms.time, "time", return_value=FETCHED_AT):
            row = ms.rows_from_pools([pool])[0]
        self.assertIn("top holders", ms.row_new_pool_gaps(row))

    def test_lps_pool_baru_99_gagal_100_lolos(self):
        # Syarat keenam (2026-09-24 lanjutan): LPs minimal 100, INKLUSIF —
        # 99 gagal (gap "LPs"), tepat 100 lolos.
        self.assertEqual(ms.NEW_POOL_LPS_MIN, 100.0)
        row99 = _row(total_lps=99.0)
        self.assertIn("LPs", ms.row_new_pool_gaps(row99))
        self.assertFalse(ms.row_new_pool(row99))
        row100 = _row(total_lps=100.0)
        self.assertEqual(ms.row_new_pool_gaps(row100), [])
        self.assertTrue(ms.row_new_pool(row100))
        # Fixture familiars (230 LPs) tetap pool baru.
        self.assertTrue(ms.row_new_pool(_row()))

    def test_lps_hilang_bukan_pool_baru(self):
        # Angka LPs hilang = tidak terbukti → tidak memenuhi.
        row = _row(total_lps=None)
        self.assertIn("LPs", ms.row_new_pool_gaps(row))
        self.assertFalse(ms.row_new_pool(row))

    def test_gagal_lps_kembali_ke_saringan_reguler(self):
        # Pool baru yang lolos SEMUA saringan reguler (F/V 45÷8,6 = 5,2×,
        # Fee/TVL 45%, vol 8,6%, LPs 99 >= BEST_LPS_MIN 50, Top10 14,7%)
        # tapi gagal syarat LPs pool baru (99 < 100): jalur pool baru TIDAK
        # dipakai — dinilai saringan reguler biasa, tampil tanpa flag
        # new_pool dan STRATEGY bukan teks pool baru.
        pool = _familiars_pool(fee_active_tvl_ratio=45.0, volatility=8.6,
                               total_lps=99.0)
        result = _scan([pool])
        self.assertEqual([r["symbol"] for r in result["rows"]], ["FAMILIARS"])
        self.assertEqual(result["hidden_rows"], [])
        row = result["rows"][0]
        self.assertIn("LPs", ms.row_new_pool_gaps(row))
        self.assertFalse(ms.row_new_pool(row))
        self.assertEqual(ms.row_best_gaps(row), [])
        self.assertFalse(row.get("new_pool"))
        self.assertNotEqual(row_strategy(row)["text"],
                            "50 50 spotba, bidask")

    def test_volatility_nol_bukan_pool_baru(self):
        row = _row(volatility=0.0)
        self.assertFalse(ms.row_new_pool(row))
        self.assertTrue(ms.row_best_dropped(row))

    def test_pool_lama_tetap_aturan_reguler(self):
        # Umur 13 jam → jalur reguler: F/V 3,3× + volatility 10,37% → dibuang.
        row = _row(pool_created_at=(FETCHED_AT - 13 * 3600) * 1000)
        self.assertFalse(ms.row_new_pool(row))
        self.assertTrue(ms.row_best_gaps(row))
        self.assertTrue(ms.row_best_dropped(row))

    def test_render_ulang_tidak_menua(self):
        # Umur dihitung terhadap fetched_at, bukan jam render.
        row = _row()
        with mock.patch.object(ms.time, "time",
                               return_value=FETCHED_AT + 48 * 3600):
            self.assertTrue(ms.row_new_pool(row))

    def test_scan_best_lane_menampilkan_familiars(self):
        pools = [_familiars_pool()]
        result = _scan(pools)
        self.assertEqual([r["symbol"] for r in result["rows"]], ["FAMILIARS"])
        self.assertEqual(result["hidden_rows"], [])

    def test_scan_best_lane_menandai_flag_new_pool(self):
        # Keputusan deteksi ditempel baris SAAT SCAN (flag ``new_pool``) —
        # render label POOL BARU + STRATEGY memakai flag ini ATAU
        # row_new_pool(row), jadi keputusan scan dan render tidak bisa
        # berbeda (hasil scan lama tanpa pool_created_at/fetched_at).
        result = _scan([_familiars_pool()])
        self.assertIs(result["rows"][0].get("new_pool"), True)
        # Pool LAMA (48 jam) yang lolos saringan reguler: tampil, flag False.
        old = _familiars_pool(pool_created_at=(FETCHED_AT - 48 * 3600) * 1000,
                              fee_active_tvl_ratio=45.0, volatility=8.6)
        result = _scan([old])
        self.assertEqual([r["symbol"] for r in result["rows"]], ["FAMILIARS"])
        self.assertIs(result["rows"][0].get("new_pool"), False)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class NewPoolRenderTest(unittest.TestCase):
    """Render tanda "POOL BARU" di kolom Token (AppTest, offline)."""

    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: {}),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: {"updated_at": None,
                                                  "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: {"tokens": {}}),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=90).run()

    @staticmethod
    def _result(rows):
        return {"rows": rows, "hidden_rows": [], "error": "",
                "fetched": len(rows), "hidden_metric": 0, "hidden_dust": 0,
                "skipped_quote": 0, "dropped_volatility": 0,
                "dropped_top10": 0, "dropped_lps": 0, "dropped_fv": 0,
                "dropped_total": 0, "rugcheck_failed": 0, "gmgn_failed": 0,
                "tax_failed": 0, "lane": "24h"}

    @staticmethod
    def _body(app):
        return "\n".join(node.value for node in app.markdown)

    def test_render_tanda_pool_baru_di_kolom_token(self):
        # Baris hasil scan (flag new_pool=True dari scan_best_lane) →
        # HTML kolom Token memuat "POOL BARU" (class .bp-new-pool) tepat
        # setelah $SYMBOL.
        row = _row(new_pool=True)
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result([row])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = self._body(app)
        self.assertIn("$FAMILIARS", body)
        self.assertIn("POOL BARU", body)
        self.assertIn('<span class="watchlist-symbol">$FAMILIARS '
                      '<span class="bp-new-pool"', body)

    def test_render_cadangan_hitungan_ulang_tanpa_flag(self):
        # Baris tanpa flag tapi punya pool_created_at/fetched_at (mis. hasil
        # alur yang belum menandai): hitungan ulang row_new_pool(row)
        # terhadap fetched_at tetap menampilkannya.
        row = _row()
        self.assertNotIn("new_pool", row)
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result([row])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = self._body(app)
        self.assertIn("$FAMILIARS", body)
        self.assertIn("POOL BARU", body)

    def test_render_hasil_scan_lama_tanpa_field_pool_baru(self):
        # PENYEBAB label hilang di app live (2026-09-24): hasil scan LAMA di
        # session_state/scan_result_cache (dibuat sebelum PR #212) tidak
        # punya pool_created_at/fetched_at/flag → row_new_pool False (tidak
        # ada bukti umur). Baris yang lolos saringan reguler tetap tampil,
        # TANPA tanda POOL BARU — pool baru yang memang baru di-scan dengan
        # kode #212 yang ditandai.
        row = {
            "pool_address": "ET9QEc18XnEXNyz8ZuGkJfgSuDDqLDiA1U8bEpyuyLKC",
            "pool_name": "familiars-SOL",
            "ca": "2PENPmfgJfq6CG3k4byj4oWwHf8SerqakmYHMkUupump",
            "symbol": "FAMILIARS", "name": "familiars.family",
            "timeframe": "24h", "source": "24h",
            "mc": 2078479.25, "tvl": 112664.66, "active_tvl": 112294.36,
            "fee_active_tvl_ratio": 45.0, "volume": 1158730.32,
            "fee": 38283.40, "volume_change_pct": 12.0, "fee_pct": 2.0,
            "volatility": 8.6, "total_lps": 230.0, "top_holders_pct": 14.68,
            "volume_active_tvl_ratio": 1031.87,
        }
        self.assertFalse(ms.row_new_pool(row))
        self.assertEqual(ms.row_best_gaps(row), [])  # lolos saringan reguler
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result([row])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = self._body(app)
        self.assertIn("$FAMILIARS", body)
        self.assertNotIn("POOL BARU", body)


if __name__ == "__main__":
    unittest.main()
