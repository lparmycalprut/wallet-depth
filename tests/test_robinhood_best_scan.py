# -*- coding: utf-8 -*-
"""Scan Best Robinhood Coin (2026-09-10).

Rule user: data listing GMGN **volume 6 jam terakhir**, hanya tampilkan
top 10 holder < 30% dan dust ≤ 0,05% MC; urutan dust % MC terkecil dulu
lalu volume 6 jam terbesar; pernah Dexboost = poin tambah (badge 🚀).
Jaringan (GMGN + Blockscout) selalu di-mock; UI dicoba lewat AppTest
halaman utama.
"""
from __future__ import annotations

import unittest
from unittest import mock

import robinhood_best_scan as rbs

CA_A = "0x" + "a" * 40
CA_B = "0x" + "b" * 40
CA_C = "0x" + "c" * 40
CA_D = "0x" + "d" * 40
CA_E = "0x" + "e" * 40
CA_F = "0x" + "f" * 40


def _token(addr, **over):
    base = {
        "address": addr, "symbol": "TOK", "name": "Tok",
        "price": 0.5, "market_cap": 1_000_000, "liquidity": 50_000,
        "volume": 100_000, "swaps": 500, "buys": 260, "sells": 240,
        "holder_count": 5_000, "top_10_holder_rate": 0.15,
        "price_change_percent": 10.0, "price_change_percent1h": 1.0,
        "is_honeypot": 0, "is_renounced": 1,
        "dexscr_boost_ts": 0, "dexscr_boost_fee": 0,
        "creation_timestamp": 1_700_000_000,
        "launchpad_platform": "pons_v2",
    }
    base.update(over)
    return base


def _payload(*tokens):
    return {"code": 0, "message": "success",
            "data": {"rank": list(tokens)}}


def _analysis(pct, *, dust_count=3, wallets=500, fetched=500,
              truncated=False, blocked=False):
    return {"holders": {"dust_pct_mc": pct, "dust_count": dust_count,
                        "wallets_analyzed": wallets,
                        "total_fetched": fetched, "truncated": truncated,
                        "blocked": blocked}}


class RankRowTest(unittest.TestCase):
    def test_fraction_top10_dijadi_percent(self):
        row = rbs.rank_row(_token(CA_A, top_10_holder_rate=0.1209))
        self.assertEqual(row["top10_pct"], 12.09)

    def test_nilai_percent_tidak_digandakan(self):
        row = rbs.rank_row(_token(CA_A, top_10_holder_rate=12.5))
        self.assertEqual(row["top10_pct"], 12.5)

    def test_dexboost_dari_timestamp(self):
        row = rbs.rank_row(_token(CA_A, dexscr_boost_ts=1_788_579_322))
        self.assertTrue(row["dexboost"])

    def test_dexboost_dari_fee(self):
        row = rbs.rank_row(_token(CA_A, dexscr_boost_fee=99))
        self.assertTrue(row["dexboost"])

    def test_tanpa_dexboost(self):
        self.assertFalse(rbs.rank_row(_token(CA_A))["dexboost"])

    def test_honeypot_ditandai(self):
        self.assertTrue(rbs.rank_row(_token(CA_A, is_honeypot=1))["honeypot"])
        self.assertFalse(rbs.rank_row(_token(CA_A, is_honeypot=0))["honeypot"])

    def test_ca_dinormalisasi_lowercase(self):
        row = rbs.rank_row(_token(CA_A.upper()))
        self.assertEqual(row["ca"], CA_A)

    def test_field_listing_diambil_apa_adanya(self):
        row = rbs.rank_row(_token(CA_A, volume=28_290_600,
                                  market_cap=637_876_000,
                                  holder_count=89_329))
        self.assertEqual(row["volume"], 28_290_600.0)
        self.assertEqual(row["mc"], 637_876_000.0)
        self.assertEqual(row["holders"], 89_329)
        self.assertEqual(row["launchpad"], "pons_v2")


class FetchRankingTest(unittest.TestCase):
    def test_rows_dinormalisasi_dan_dedupe(self):
        payload = _payload(_token(CA_A), _token(CA_A), _token(CA_B))
        with mock.patch.object(rbs, "_get_json", return_value=(payload, "")):
            rows, error = rbs.fetch_ranking()
        self.assertEqual(error, "")
        self.assertEqual([r["ca"] for r in rows], [CA_A, CA_B])

    def test_gagal_fetch_memakai_error(self):
        with mock.patch.object(rbs, "_get_json",
                               return_value=(None, "HTTP 403")):
            rows, error = rbs.fetch_ranking()
        self.assertEqual(rows, [])
        self.assertEqual(error, "HTTP 403")

    def test_rank_kosong_aman(self):
        with mock.patch.object(rbs, "_get_json",
                               return_value=({"code": 0, "data": {}}, "")):
            rows, error = rbs.fetch_ranking()
        self.assertEqual((rows, error), ([], ""))

    def test_item_non_dict_dilewati(self):
        payload = _payload(_token(CA_A), "bukan-dict", None)
        with mock.patch.object(rbs, "_get_json", return_value=(payload, "")):
            rows, error = rbs.fetch_ranking()
        self.assertEqual([r["ca"] for r in rows], [CA_A])


class SortRowsTest(unittest.TestCase):
    """Urutan listing: dust % MC terkecil dulu, lalu volume 6 jam terbesar."""

    def _row(self, ca, symbol, dust, volume):
        return {"ca": ca, "symbol": symbol, "dust_pct_mc": dust,
                "volume": volume, "dexboost": False}

    def test_dust_terkecil_dulu_lalu_volume_terbesar(self):
        rows = [
            self._row(CA_A, "AAA", 0.04, 1_000.0),
            self._row(CA_B, "BBB", 0.01, 500.0),     # juara: dust terkecil
            self._row(CA_C, "CCC", 0.04, 9_000.0),   # dust seri AAA → vol menang
            self._row(CA_D, "DDD", 0.0, 10.0),       # dust 0 → paling atas
        ]
        out = [r["ca"] for r in rbs.sort_rows(rows)]
        self.assertEqual(out, [CA_D, CA_B, CA_C, CA_A])

    def test_deterministik_tidak_ganti_input(self):
        rows = [
            self._row(CA_A, "AAA", 0.04, 1_000.0),
            self._row(CA_B, "BBB", 0.01, 500.0),
        ]
        before = [r["symbol"] for r in rows]
        first = [r["ca"] for r in rbs.sort_rows(rows)]
        second = [r["ca"] for r in rbs.sort_rows(list(reversed(rows)))]
        self.assertEqual(first, second)
        self.assertEqual([r["symbol"] for r in rows], before)

    def test_kosong_aman(self):
        self.assertEqual(rbs.sort_rows([]), [])
        self.assertEqual(rbs.sort_rows(None), [])


class ScanBestTest(unittest.TestCase):
    """Filter + penggabungan: listing → top10 < 30% → dust ≤ 0,05% MC."""

    def _listing(self):
        return [
            rbs.rank_row(_token(CA_A, symbol="PASS", volume=900_000)),
            rbs.rank_row(_token(CA_B, symbol="TOP10", top_10_holder_rate=0.30,
                                volume=800_000)),
            rbs.rank_row(_token(CA_C, symbol="HONEY", is_honeypot=1,
                                volume=700_000)),
            rbs.rank_row(_token(CA_D, symbol="NOCAP", market_cap=0,
                                price=0, volume=600_000)),
            rbs.rank_row(_token(CA_E, symbol="DUSTY", volume=500_000)),
            rbs.rank_row(_token(CA_F, symbol="FAILED", volume=400_000)),
        ]

    def _scan(self, listing, analyses):
        def _analyze(ca, symbol, **kwargs):
            return analyses.get(ca)
        with mock.patch.object(rbs, "fetch_ranking",
                               return_value=(listing, "")), \
             mock.patch("robinhood_holders.analyze_token",
                        side_effect=_analyze):
            return rbs.scan_best(progress=lambda *a: None)

    def test_rule_filter_dan_urutan(self):
        listing = self._listing()
        analyses = {
            CA_A: _analysis(0.04, fetched=5_000, wallets=5_000),
            CA_E: _analysis(0.06, fetched=4_000, wallets=4_000),  # > 0,05%
            CA_F: _analysis(0.01, fetched=20, wallets=20),        # sampel pendek
        }
        result = self._scan(listing, analyses)
        self.assertEqual([r["ca"] for r in result["rows"]], [CA_A])
        skipped = result["skipped"]
        self.assertEqual(skipped["top10"], 1)
        self.assertEqual(skipped["honeypot"], 1)
        self.assertEqual(skipped["no_quote"], 1)
        self.assertEqual(skipped["dust"], 1)
        self.assertEqual(skipped["failed"], 1)
        self.assertEqual(result["fetched"], 6)

    def test_ambang_dust_bersama_005_ditampilkan(self):
        listing = [rbs.rank_row(_token(CA_A, symbol="EDGE"))]
        result = self._scan(listing, {CA_A: _analysis(0.05)})
        self.assertEqual([r["ca"] for r in result["rows"]], [CA_A])
        self.assertEqual(result["skipped"]["dust"], 0)

    def test_truncated_holder_ditolak(self):
        listing = [rbs.rank_row(_token(CA_A, symbol="TRUNC"))]
        result = self._scan(listing,
                            {CA_A: _analysis(0.0, truncated=True)})
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["skipped"]["failed"], 1)

    def test_dexboost_dihitung_di_kandidat_tertampil(self):
        listing = [
            rbs.rank_row(_token(CA_A, symbol="BOOST",
                                dexscr_boost_fee=99, volume=2_000)),
            rbs.rank_row(_token(CA_B, symbol="PLAIN", volume=1_000)),
        ]
        result = self._scan(listing, {
            CA_A: _analysis(0.02, fetched=3_000, wallets=3_000),
            CA_B: _analysis(0.01, fetched=3_000, wallets=3_000),
        })
        self.assertEqual(result["dexboost"], 1)
        # Urutan tetap dust-dulu, bukan dexboost-dulu (poin tambah = badge):
        # PLAIN (0,01%) di atas BOOST (0,02%) walau BOOST yang dapat 🚀.
        self.assertEqual([r["ca"] for r in result["rows"]], [CA_B, CA_A])
        self.assertFalse(result["rows"][0]["dexboost"])
        self.assertTrue(result["rows"][1]["dexboost"])

    def test_listing_gagal_tetap_pulang_result(self):
        with mock.patch.object(rbs, "fetch_ranking",
                               return_value=([], "HTTP 503")):
            result = rbs.scan_best()
        self.assertEqual(result["error"], "HTTP 503")
        self.assertEqual(result["rows"], [])

    def test_skipped_terisi_walapun_listing_kosong(self):
        listing = self._listing()
        result = self._scan(listing, {})
        # Semua kandidat: top10=1, honeypot=1, no_quote=1, failed=3 (A,E,F).
        self.assertEqual(result["skipped"]["failed"], 3)


class ScanCandidatesTest(unittest.TestCase):
    """Semua kandidat ditunggu — budget waktu sudah DIHAPUS (2026-09-10).

    Kejadian nyata: progress tampak macet di "Holder 6/7" bukan karena hang,
    tapi karena satu token ber-holder puluhan ribu memang butuh paginasi
    Blockscout 10-15 menit. User memutuskan (2026-09-10): "hapus timeoutnya,
    gak papa ternyata tadi masalahnya holdernya sangat banyak, jadi agak lama
    memang fetchingnya" — jadi kandidat lambat TIDAK boleh dibuang lagi, dan
    label progress menyebut token yang sedang digiling supaya tetap kelihatan
    hidup.
    """

    def _row(self, ca, symbol="TOK"):
        return {"ca": ca, "symbol": symbol, "mc": 1_000_000, "price": 0.5}

    def test_kandidat_lambat_tetap_ditunggu_sampai_selesai(self):
        import threading
        release = threading.Event()
        threading.Timer(0.4, release.set).start()   # lama, tapi selesai

        def _analyze(ca, symbol, **kwargs):
            if ca == CA_B:
                release.wait(timeout=30)
            return {"holders": _analysis(0.01)["holders"]}

        with mock.patch("robinhood_holders.analyze_token",
                        side_effect=_analyze):
            analyses = rbs.scan_candidates(
                [self._row(CA_A), self._row(CA_B)], workers=2)
        # Dua-duanya dapat hasil — yang lambat tidak dikorbankan.
        self.assertIn(CA_A, analyses)
        self.assertIn(CA_B, analyses)

    def test_scan_candidates_tidak_menerima_budget_waktu(self):
        """``timeout_sec``/``CANDIDATE_TIMEOUT_SEC`` sudah dihapus total."""
        import inspect

        source = inspect.getsource(rbs.scan_candidates)
        self.assertNotIn("timeout_sec", source)
        self.assertNotIn("deadline", source)
        self.assertNotIn("CANDIDATE_TIMEOUT_SEC",
                         inspect.getsource(rbs))

    def test_progress_menyebut_kandidat_yang_sedang_jalan(self):
        labels = []

        def _analyze(ca, symbol, **kwargs):
            return {"holders": _analysis(0.01)["holders"]}

        with mock.patch("robinhood_holders.analyze_token",
                        side_effect=_analyze):
            rbs.scan_candidates(
                [self._row(CA_A, "AAA")], workers=1,
                progress=lambda done, total, label: labels.append(label))
        self.assertTrue(any("AAA" in str(label) for label in labels),
                        f"label progress tidak menyebut token: {labels}")

    def test_progress_error_tidak_mematikan_scan(self):
        def _analyze(ca, symbol, **kwargs):
            return {"holders": _analysis(0.01)["holders"]}

        def _boom(*args):
            raise RuntimeError("progress rusak")

        with mock.patch("robinhood_holders.analyze_token",
                        side_effect=_analyze):
            analyses = rbs.scan_candidates([self._row(CA_A)], workers=1,
                                           progress=_boom)
        self.assertIn(CA_A, analyses)


class RenderTest(unittest.TestCase):
    """AppTest halaman utama: card + tombol scan + baris hasil."""

    ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
    APP = str(ROOT / "app.py")

    @staticmethod
    def _result():
        rows = [
            {"ca": CA_A, "symbol": "PASS", "name": "Pass", "price": 0.5,
             "mc": 1_000_000, "liq": 50_000, "volume": 900_000,
             "holders": 5_000, "top10_pct": 12.1, "dexboost": True,
             "dust_pct_mc": 0.02, "dust_count": 3},
            {"ca": CA_B, "symbol": "OTHER", "name": "Other", "price": 0.2,
             "mc": 800_000, "liq": 30_000, "volume": 700_000,
             "holders": 4_000, "top10_pct": 21.0, "dexboost": False,
             "dust_pct_mc": 0.04, "dust_count": 9},
        ]
        return {"rows": rows, "error": "", "fetched": 10,
                "skipped": {"honeypot": 1, "top10": 2, "no_quote": 0,
                            "failed": 1, "dust": 2},
                "blocked": 0, "dexboost": 1}

    @staticmethod
    def _body(app):
        return "\n".join(node.value for node in app.markdown)

    def test_card_tampil_di_halaman_utama(self):
        from streamlit.testing.v1 import AppTest

        with mock.patch.object(rbs, "scan_best", return_value=self._result()):
            app = AppTest.from_file(self.APP, default_timeout=30)
            app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("🦅 Scan Best Robinhood Coin</span>", self._body(app))
        self.assertIn("volume 6 jam terakhir", self._body(app))

    def test_detail_karakteristik_di_tooltip_bukan_caption(self):
        """Caption panjang card pindah ke tooltip judul (permintaan user).

        ``st.caption`` hanya boleh berisi hasil scan (jumlah coin / yang
        dilewati) — rule filter, sumber dust, dan tombol dijelaskan di atribut
        ``title`` pada teks judul card.
        """
        from streamlit.testing.v1 import AppTest

        with mock.patch.object(rbs, "scan_best", return_value=self._result()):
            app = AppTest.from_file(self.APP, default_timeout=30)
            app.run()
            button = next(b for b in app.button if b.label == rbs.CARD_TITLE)
            app = button.click().run()   # hasil scan → caption rekap + listing
        body = self._body(app)
        captions = "\n".join(node.value for node in app.caption)
        # masih ada di tooltip judul…
        self.assertIn('title="Listing GMGN Robinhood Chain', body)
        self.assertIn("Honeypot otomatis dikeluarkan", body)
        self.assertIn("scan cron ±5 menit", body)
        # …dan sudah TIDAK di caption card.
        self.assertNotIn("Honeypot otomatis dikeluarkan", captions)
        self.assertNotIn("top 10 holder < 30%", captions)
        # 2026-09-11: caption tidak lagi menulis ulang ANGKA ambangnya juga —
        # dulu "dust > 0,05% MC = 2, top 10 holder ≥ 30% = 1, honeypot = …".
        self.assertNotIn("0.05% MC", captions)
        self.assertNotIn("≥ 30%", captions)
        self.assertNotIn("volume 6h", captions)
        # caption hasil scan tetap ada (itu data, bukan deskripsi rule).
        self.assertIn("Listing 10 coin", captions)
        self.assertIn("6 dilewati", captions)
        self.assertIn("dust 2", captions)

    def test_tombol_scan_memanggil_scan_best_lalu_render_baris(self):
        from streamlit.testing.v1 import AppTest

        with mock.patch.object(rbs, "scan_best", return_value=self._result()) \
                as scan:
            app = AppTest.from_file(self.APP, default_timeout=30)
            app.run()
            self.assertEqual(len(app.exception), 0)
            button = next(b for b in app.button
                          if b.label == rbs.CARD_TITLE)
            app = button.click().run()
        self.assertEqual(len(app.exception), 0)
        scan.assert_called_once()
        body = self._body(app)
        self.assertIn("$PASS", body)
        self.assertIn("$OTHER", body)
        self.assertIn("🚀 DEXBOOST", body)
        self.assertIn("0.020%", body)
        # ⭐ ada di setiap baris hasil.
        stars = [b for b in app.button if b.label == "⭐"
                 and str(b.key).startswith("rh-best-star-")]
        self.assertEqual(len(stars), 2)

    def test_star_menambah_ke_watchlist_robinhood(self):
        from streamlit.testing.v1 import AppTest

        with mock.patch.object(rbs, "scan_best", return_value=self._result()), \
             mock.patch("robinhood_watchlist.add_to_robinhood_watchlist",
                        return_value=True) as add:
            app = AppTest.from_file(self.APP, default_timeout=30)
            app.run()
            scan_button = next(b for b in app.button
                               if b.label == rbs.CARD_TITLE)
            app = scan_button.click().run()
            star = next(b for b in app.button
                        if b.label == "⭐"
                        and str(b.key) == f"rh-best-star-{CA_A}")
            app = star.click().run()
        self.assertEqual(len(app.exception), 0)
        add.assert_called_once()
        self.assertEqual(add.call_args.args[0], CA_A)
        self.assertEqual(add.call_args.kwargs.get("background"), True)
        # st.success bukan elemen markdown — cek lewat app.success.
        self.assertIn("$PASS masuk Watchlist Robinhood",
                      [s.value for s in app.success])


if __name__ == "__main__":
    unittest.main()
