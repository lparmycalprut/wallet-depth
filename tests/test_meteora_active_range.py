"""Coverage kolom **Active Range** (rentang bin berisi likuiditas DLMM).

Permintaan user 2026-09-14: *"ok tambahkan Active Range, tapi % saja, misal
-30% +40 atau bagaimana terserah kamu agar gampang saya baca"*. Yang di-pin di
file ini:

- **sumber angka**: ``pool_price`` (harga bin aktif) + ``min_price`` /
  ``max_price`` (tepi range likuiditas) dari listing API Meteora yang sudah
  dipakai card ini, disimpan ke baris oleh ``_row_from_pool`` sebagai
  ``pool_price`` / ``range_min_price`` / ``range_max_price`` + ``bin_step``;
- **angka nyata**: tiga pool live 2026-09-14 (CATE-USDC bin_step 20,
  biketyson-SOL 100, ROUTER-SOL 250) dipakai apa adanya sebagai fixture —
  ketiganya terbukti harga bin DLMM persis (``P_i = (1 + bin_step/10000)^i``,
  docs.meteora.ag → DLMM Formulas), jadi persen yang ditampilkan card bisa
  dicek ulang dari harga mentahnya;
- **arah persen**: turun/naik diukur **dari harga sekarang** (harga × (1 −
  turun/100) = tepi bawah), bukan sebaliknya;
- **format**: persen saja ``-34.5% / +19.0%``; nol ditulis ``0.0%`` tanpa
  tanda (harga nempel tepi range), data hilang → ``—`` — tidak pernah
  ``-0.0% / +0.0%`` palsu;
- **UI**: kolom Active Range ada di tabel 🏆 Best Pool (kanan A.TVL),
  memakai builder sel yang sama.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import best_pool_ui as bp
import meteora_screener as ms

APP = str(Path(__file__).resolve().parent.parent / "app.py")
SOL = ms.SOL_MINT

# ---------------------------------------------------------------------------
# Angka API Meteora apa adanya (pool-discovery-api, 2026-09-14). Dipakai sebagai
# fixture supaya setiap persen di card bisa ditelusuri ke harga bin mentahnya.
# ---------------------------------------------------------------------------
CATE = dict(pool_address="Cgk5DWJc59TcWTQ1iaJ8Hn4bsVjKXJF2fCjPAZtMUSkV",
            pool_price=0.07431804692125288,
            range_min_price=0.04865610312274629,
            range_max_price=0.08842723818935955, bin_step=20)
BIKETYSON = dict(pool_address="ARqHS4dXM989rYBjDKzx249yqBXQtdrUioemyoGEnAnk",
                 pool_price=0.000064807043559752,
                 range_min_price=0.000060446699600373,
                 range_max_price=0.000070176741690609, bin_step=100)
# ROUTER: ``min_price`` == ``pool_price`` persis — harga nempel tepi bawah.
ROUTER = dict(pool_address="DJ8qzBm3ZoRi4YiVmpiLBBuc67cq737vqaTNbMRJGcvZ",
              pool_price=0.00001493690344708,
              range_min_price=0.00001493690344708,
              range_max_price=0.000015693084184088, bin_step=250)


class ActiveRangePctTest(unittest.TestCase):
    def test_pool_live_dihitung_dari_harga_sekarang(self):
        """CATE: -34.5% / +19.0% — angka yang diverifikasi dari payload API."""
        down, up = ms.active_range_pct(CATE)
        self.assertAlmostEqual(down, 34.53, places=2)
        self.assertAlmostEqual(up, 18.98, places=2)
        self.assertEqual(ms.active_range_text(CATE), "-34.5% / +19.0%")

    def test_persen_bisa_dikembalikan_ke_harga_bin(self):
        """harga × (1 − turun) = tepi bawah, harga × (1 + naik) = tepi atas."""
        for row in (CATE, BIKETYSON, ROUTER):
            with self.subTest(pool=row["pool_address"]):
                down, up = ms.active_range_pct(row)
                price = row["pool_price"]
                self.assertAlmostEqual(price * (1 - down / 100),
                                       row["range_min_price"], places=18)
                self.assertAlmostEqual(price * (1 + up / 100),
                                       row["range_max_price"], places=18)

    def test_range_sempit_dan_harga_nempel_tepi(self):
        """biketyson -6.7% / +8.3%; ROUTER 0.0% (tanpa tanda) / +5.1%."""
        self.assertEqual(ms.active_range_text(BIKETYSON), "-6.7% / +8.3%")
        self.assertEqual(ms.active_range_text(ROUTER), "0.0% / +5.1%")
        down, _up = ms.active_range_pct(ROUTER)
        self.assertEqual(down, 0.0)

    def test_tepi_tertukar_tetap_aman(self):
        swapped = dict(CATE, range_min_price=CATE["range_max_price"],
                       range_max_price=CATE["range_min_price"])
        self.assertEqual(ms.active_range_text(swapped),
                         ms.active_range_text(CATE))
        self.assertEqual(ms.active_range_width_pct(swapped),
                         ms.active_range_width_pct(CATE))

    def test_data_hilang_bukan_nol_palsu(self):
        for row in ({}, {"pool_price": 0.074}, dict(CATE, pool_price=0),
                    dict(CATE, range_min_price=-1),
                    dict(CATE, range_max_price=None)):
            with self.subTest(row=sorted(row)):
                down, up = ms.active_range_pct(row)
                self.assertIsNone(down)
                self.assertIsNone(up)
                self.assertEqual(ms.active_range_text(row), "—")

    def test_bin_step_hilang_tidak_mengubah_persen(self):
        """Persen cukup dari tiga harga; ``bin_step`` hanya untuk tooltip."""
        tanpa_step = dict(CATE, bin_step=None)
        self.assertEqual(ms.active_range_pct(tanpa_step),
                         ms.active_range_pct(CATE))
        self.assertEqual(ms.active_range_text(tanpa_step), "-34.5% / +19.0%")
        self.assertIsNone(ms.active_range_bins(tanpa_step))

    def test_lebar_range(self):
        self.assertAlmostEqual(ms.active_range_width_pct(CATE), 81.74,
                               places=2)
        self.assertAlmostEqual(ms.active_range_width_pct(ROUTER), 5.06,
                               places=2)
        self.assertIsNone(ms.active_range_width_pct({}))


class ActiveRangeBinsTest(unittest.TestCase):
    def test_jumlah_bin_dari_bin_step(self):
        # CATE: 300 bin berisi likuiditas, harga 212 bin di atas tepi bawah.
        self.assertEqual(ms.active_range_bins(CATE), (300, 212, 87))
        self.assertEqual(ms.active_range_bins(BIKETYSON), (16, 7, 8))
        self.assertEqual(ms.active_range_bins(ROUTER), (3, 0, 2))

    def test_tanpa_bin_step_tidak_dihitung(self):
        self.assertIsNone(ms.active_range_bins({}))
        self.assertIsNone(ms.active_range_bins(dict(CATE, bin_step=0)))
        self.assertIsNone(ms.active_range_bins(dict(CATE, bin_step=None)))


class RowFromPoolTest(unittest.TestCase):
    @staticmethod
    def _payload(**over):
        payload = {
            "pool_address": "Cgk5DWJc59TcWTQ1iaJ8Hn4bsVjKXJF2fCjPAZtMUSkV",
            "name": "CATE-USDC", "pool_type": "dlmm",
            "token_x": {"address": "Ai66LHZG9MCzg1WKdawwqduVAXpNDUuV8M3uyq5ppump",
                        "symbol": "CATE", "name": "Cate", "decimals": 6,
                        "market_cap": 71_798_695.7, "price": 0.0744,
                        "holders": 126_045},
            "token_y": {"address": ms.USDC_MINT, "symbol": "USDC",
                        "name": "USD Coin", "decimals": 6, "price": 1.0,
                        "holders": 5_248_202},
            "tvl": 66_679.22, "active_tvl": 65_315.94,
            "fee_active_tvl_ratio": 19.54, "volume": 4_872_478.48,
            "fee_pct": 0.2, "volatility": 1.11,
            "dlmm_params": {"bin_step": 20, "collect_fee_mode": "both"},
            "pool_price": 0.07431804692125288,
            "max_price": 0.08842723818935955,
            "min_price": 0.04865610312274629,
        }
        payload.update(over)
        return payload

    def test_baris_membawa_harga_bin_dan_bin_step(self):
        row = ms._row_from_pool(self._payload())
        self.assertEqual(row["pool_price"], 0.07431804692125288)
        self.assertEqual(row["range_min_price"], 0.04865610312274629)
        self.assertEqual(row["range_max_price"], 0.08842723818935955)
        self.assertEqual(row["bin_step"], 20)
        self.assertEqual(ms.active_range_text(row), "-34.5% / +19.0%")

    def test_payload_tanpa_dlmm_params_tidak_melempar(self):
        row = ms._row_from_pool(self._payload(dlmm_params=None,
                                              pool_price=None,
                                              min_price=None,
                                              max_price=None))
        self.assertIsNone(row["bin_step"])
        self.assertIsNone(row["pool_price"])
        self.assertEqual(ms.active_range_text(row), "—")


class ActiveRangeCellTest(unittest.TestCase):
    def test_sel_berisi_persen_dan_lebar_range(self):
        value, sub, tip = bp._active_range_cell(CATE)
        self.assertIn("-34.5%", value)
        self.assertIn("+19.0%", value)
        # Turun merah, naik hijau — satu kali lihat sudah kebaca arahnya.
        self.assertIn("#dc2626", value)
        self.assertIn("#16a34a", value)
        self.assertEqual(sub, "lebar 81.7%")
        self.assertIn("0.074318", tip)
        self.assertIn("300 bin berisi likuiditas", tip)
        self.assertIn("bukan saringan", tip)

    def test_sel_nol_tanpa_tanda_dan_tanpa_warna(self):
        value, _sub, _tip = bp._active_range_cell(ROUTER)
        self.assertIn("0.0%", value)
        self.assertNotIn("-0.0%", value)
        self.assertNotIn("+0.0%", value)
        self.assertIn("+5.1%", value)

    def test_sel_tanpa_data_menulis_strip(self):
        value, sub, tip = bp._active_range_cell({})
        self.assertEqual(value, "—")
        self.assertEqual(sub, "range")
        self.assertIn("tekan tombol scan lagi", tip)


class BestPoolColumnsTest(unittest.TestCase):
    def test_kolom_dan_judul_sinkron(self):
        """Header, lebar kolom, dan isi sel harus satu jumlah (13/14 kolom).

        Penataan 2026-09-16: Active Range naik ke kanan Volat (indeks 4) dan
        LPs tepat di kanannya (5). Penataan 2026-09-17 (permintaan user:
        *"hapus kolom dust %"* + *"hapus tombol favorit / watchlist"*):
        kolom **Dust %MC** dan kolom **⭐** dicabut — A.TVL berada di indeks
        8, RugCheck (11) tetap sebelum Pool (12, kini memuat tombol 📋 copy
        link HawkFi).

        Penataan 2026-09-19 (permintaan user: *"hapus tentang bubblemap,
        sisakan hyperlink ke bubblemapnya saja"* + *"Kasih kolom baru dipaling
        kanan STRATEGY"*): kolom **Bubble Map** dicabut sehingga kolom
        dasarnya kembali **13** dengan Pool di indeks 12 (tautan 🫧 pindah ke
        dalamnya), dan tabel utama menambah **STRATEGY** di indeks 13 → 14
        kolom. Tabel "▶ N pool dilewati" memakai ``show_strategy=False`` →
        tetap 13 kolom.
        """
        for lane in ("24h", "30m"):
            with self.subTest(lane=lane):
                titles = bp._lane_titles(lane)
                self.assertEqual(len(titles),
                                 len(bp._col_spec(show_strategy=True)))
                self.assertEqual(len(titles), 14)
                self.assertEqual(titles[4], "Active Range")
                self.assertEqual(titles[5], "LPs")
                self.assertEqual(titles[8], "A.TVL")
                self.assertEqual(titles[11], "RugCheck")
                self.assertEqual(titles[12], "Pool")
                self.assertEqual(titles[13], "STRATEGY")
                tanpa_strategy = bp._lane_titles(lane, show_strategy=False)
                self.assertEqual(len(tanpa_strategy),
                                 len(bp._col_spec(show_strategy=False)))
                self.assertEqual(len(tanpa_strategy), 13)
                self.assertEqual(tanpa_strategy[-1], "Pool")
                # Dust %MC, kolom ⭐, dan Bubble Map benar-benar hilang.
                for hilang in ("Dust %MC", "Bubble Map", ""):
                    self.assertNotIn(hilang, titles)
                    self.assertNotIn(hilang, tanpa_strategy)
                # "30m" = alias lama, tetap dipetakan ke tabel 24H.
                self.assertEqual(bp._lane_titles("30m"), titles)

    def test_tooltip_card_menjelaskan_kolom_baru(self):
        tip = bp.best_pool_tooltip()
        self.assertIn("Active Range", tip)
        self.assertIn("-34.5% / +19.0%", tip)

@unittest.skipIf(AppTest is None, "streamlit not installed")
class ActiveRangeCardTest(unittest.TestCase):
    """Kolom Active Range benar-benar terender di dua card listing."""

    def setUp(self):
        patches = (
            mock.patch("watchlist.load_watchlist", side_effect=lambda **_kw: {}),
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

    @staticmethod
    def _body(app):
        return "\n".join(node.value for node in app.markdown)

    def test_tabel_best_pool_menampilkan_active_range(self):
        rows = [dict(CATE, ca="MintCATE", symbol="CATE", timeframe="24h",
                     source="24h", mc=71_798_695.7, tvl=66_679.22,
                     active_tvl=65_315.94, fee_active_tvl_ratio=19.54,
                     volatility=1.11, volume=4_872_478.48, fee=12_763.44,
                     volume_change_pct=1022.69, fee_pct=0.2, total_lps=56,
                     top_holders_pct=14.4,
                     analysis={"holders": {"dust_pct_mc": 0.03,
                                           "dust_count": 5,
                                           "total_fetched": 1200,
                                           "wallets_analyzed": 1100}})]
        app = AppTest.from_file(APP, default_timeout=90).run()
        app.session_state["best_pool_scan_24h"] = {
            "rows": rows, "hidden_rows": [], "error": "", "fetched": 1,
            "hidden_metric": 0, "hidden_dust": 0, "skipped_quote": 0,
            "dropped_volatility": 0, "lane": "24h",
            "gate": ms.best_lane_gate_label("24h"), "analyzed_at": 1}
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = self._body(app)
        self.assertIn(">Active Range<", body)
        self.assertIn("-34.5%", body)
        self.assertIn("+19.0%", body)
        self.assertIn("lebar 81.7%", body)
        # Tombol ⭐ watchlist DIHAPUS 2026-09-17 (permintaan user: "hapus
        # tombol favorit / watchlist"); kolom terakhir kini memuat tombol 📋
        # copy link HawkFi milik pool baris ini (bukan st.button → tanpa
        # rerun) di samping tautan Meteora/HawkFi.
        self.assertFalse(any("-star-" in (button.key or "")
                             for button in app.button))
        self.assertIn('class="hawkfi-copy-btn"', body)
        self.assertIn("https://www.hawkfi.ag/meteora/" + CATE["pool_address"],
                      body)


if __name__ == "__main__":
    unittest.main()
