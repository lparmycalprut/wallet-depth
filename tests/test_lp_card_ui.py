"""AppTest: card **Watchlist Meteora** (dulu "Chart LP") di halaman utama.

Menutup perilaku yang diminta user:
- token ``source=meteora`` tampil di card paling atas, bukan di watchlist biasa;
- badge **HATI-HATI** (≥ 0,5% MC) dan **BAHAYA** (≥ 1% MC);
- grafik perubahan dust holder ikut ter-render;
- tambah manual bisa diarahkan ke Watchlist Meteora (radio) atau lewat form
  di card;
- tombol 🌊 memindahkan token watchlist biasa ke Watchlist Meteora;
- detail karakteristik card = tooltip judul (2026-09-10), bukan caption;
- card **Scan Meteora Pool** pindah ke halaman temp (2026-09-10).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import holder_history as hh

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TEMP = "pages/8_temp.py"

LP_MINT = "LpMint11111111111111111111111111111111111"
LP_SAFE = "LpSafe22222222222222222222222222222222222"
# base58 valid (tanpa 0/O/I/l) supaya lolos validasi CA di UI
HOLDER_MINT = "Watch11111111111111111111111111111111111"
BUCKET = hh.INTERVAL_SEC
LP_TAB = "🌊 Watchlist Meteora"
HOLDER_TAB = "📋 Watchlist Holder"


def _point(index: int, pct: float, count: int) -> dict:
    return {"ts": (index + 1) * BUCKET, "price": 0.01, "mc": 100_000.0,
            "dust_count": count, "dust_pct_mc": pct,
            "dust_value_usd": count * 5.0, "real_count": 40,
            "real_pct_mc": 20.0, "mid_count": 6, "mid_pct_mc": 4.0,
            "cohort_token_pct": 90.0, "cohort_cut50_pct": 10.0,
            "cohort_n": 6, "holder_count": count + 40,
            "buckets": {">$0-$10": count}}


def _watchlist():
    return {
        LP_MINT: {"symbol": "LPRISK", "source": "meteora",
                  "added": "2026-09-03"},
        LP_SAFE: {"symbol": "LPSAFE", "source": "meteora",
                  "added": "2026-09-03"},
        HOLDER_MINT: {"symbol": "HOLDT", "source": "manual",
                      "added": "2026-09-02"},
    }


def _status():
    return {
        "updated_at": 2 * BUCKET,
        "tokens": {
            LP_MINT: {"symbol": "LPRISK", "marketcap": 90_000.0,
                      "price": 0.01, "analyzed_at": 2 * BUCKET,
                      "holders": {"dust_count": 120, "dust_pct_mc": 1.35,
                                  "real_count": 40, "total_fetched": 160},
                      "history": [_point(0, 0.62, 90), _point(1, 1.35, 120)]},
            LP_SAFE: {"symbol": "LPSAFE", "marketcap": 300_000.0,
                      "price": 0.02, "analyzed_at": 2 * BUCKET,
                      "holders": {"dust_count": 70, "dust_pct_mc": 0.61,
                                  "real_count": 90, "total_fetched": 160},
                      "history": [_point(0, 0.30, 50), _point(1, 0.61, 70)]},
            HOLDER_MINT: {"symbol": "HOLDT", "marketcap": 500_000.0,
                          "price": 0.05, "analyzed_at": 2 * BUCKET,
                          "holders": {"dust_count": 12, "dust_pct_mc": 0.20,
                                      "real_count": 80,
                                      "total_fetched": 92},
                          "history": [_point(0, 0.10, 9),
                                      _point(1, 0.20, 12)]},
        },
    }


def _store():
    return {"updated_at": 2 * BUCKET,
            "tokens": {mint: {"symbol": slot["symbol"], "cohort": {},
                              "points": slot.get("history") or []}
                       for mint, slot in _status()["tokens"].items()}}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class ChartLpCardTest(unittest.TestCase):
    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: _watchlist()),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: _status()),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: _store()),
            # Backup durable store: tes tidak boleh menyentuh jaringan.
            mock.patch("holder_history.pull_holder_history", return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=60).run()

    def _body(self, app):
        return "\n".join(node.value for node in app.markdown)

    def _button(self, app, key):
        found = [button for button in app.button if button.key == key]
        self.assertTrue(found, f"tombol {key} tidak ditemukan")
        return found[0]

    def test_card_renders_meteora_tokens_with_dust_levels(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = self._body(app)
        self.assertIn("🌊 Watchlist Meteora</span>", body)
        self.assertIn("HATI-HATI", body)     # LPSAFE 0,61% MC
        self.assertIn("BAHAYA", body)        # LPRISK 1,35% MC
        self.assertIn("$LPRISK", body)
        self.assertIn("$LPSAFE", body)
        # Kolom Hold %MC 3 desimal sejak 2026-09-12 (permintaan user).
        self.assertIn('watchlist-metric-value">0.610%', body)
        self.assertIn('watchlist-metric-value">1.350%', body)
        # token non-meteora tidak masuk card LP
        self.assertNotIn(f"lp-move-{HOLDER_MINT}",
                         " ".join(b.key or "" for b in app.button))

    def test_dust_chart_is_rendered(self):
        app = self._app()
        # overlay semua token LP + grafik per token (di dalam expander)
        self.assertGreaterEqual(len(app.get("image")), 2)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("Garis = dust % marketcap", captions)
        self.assertIn(f"ambang HATI-HATI {hh.DUST_CAUTION_PCT:g}% / BAHAYA "
                      f"{hh.DUST_DANGER_PCT:g}%", captions)

    def test_detail_menampilkan_dust_saat_masuk_watchlist(self):
        """Permintaan user 2026-09-13: detail tiap token juga menulis posisi
        dust % MC **saat token pertama masuk watchlist** (patokan notifikasi
        ⚡ EARLY DUMP), bukan cuma angka terbaru.

        Tanggal ``added`` dibuat lebih tua dari titik pertama supaya jalur
        "titik pertama sejak tanggal masuk" yang diuji (bukan varian
        fallback).
        """
        watchlist = _watchlist()
        for meta in watchlist.values():
            meta["added"] = "1970-01-01"
        patches = (
            mock.patch("watchlist.load_watchlist", return_value=watchlist),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: _status()),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: _store()),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60).run()
        self.assertEqual(len(app.exception), 0)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("📌 Saat masuk watchlist", captions)
        # LPRISK: titik pertama 0,62% → sekarang 1,35% (+0,73 pp).
        self.assertIn("dust 0.620% MC", captions)
        self.assertIn("sekarang 1.350% MC (+0.730 pp)", captions)
        self.assertIn("patokan notif ⚡ EARLY DUMP", captions)

    def test_card_detail_is_hover_tooltip_on_title(self):
        """Detail karakteristik card = tooltip judul (permintaan 2026-09-10).

        Caption panjang di badan card diganti atribut ``title`` pada teks
        judul — hanya muncul saat kursor digeser ke tulisan "Watchlist
        Meteora". Ambang level dust (0,5 / 1% MC) dan rule notifikasi delta
        0,02% harus tetap disebut di dalamnya.
        """
        app = self._app()
        body = self._body(app)
        captions = "\n".join(node.value for node in app.caption)
        # Teks detail tidak lagi dirender sebagai caption card.
        self.assertNotIn("berulang untuk tiap kelipatan", captions)
        self.assertNotIn("perubahan holder langsung kelihatan", captions)
        # ... tapi ada sebagai tooltip (title="…") di span judul card.
        self.assertIn('title="Watchlist terpisah', body)
        self.assertIn("berulang untuk tiap kelipatan 0.02%", body)
        self.assertIn("⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE", body)
        self.assertIn("perubahan holder langsung kelihatan", body)
        self.assertIn("per bucket 5 menit", body)
        # Jangan ada lagi janji "Meteora tetap 15 menit" di tooltip ini.
        tooltip = body.split('title="Watchlist terpisah', 1)[1]
        tooltip = tooltip.split('"', 1)[0]
        self.assertIn("tiap ±5 menit", tooltip)
        self.assertNotIn("15 menit", tooltip)
        # Caption watchlist biasa sekarang hanya ada di halaman temp.
        self.assertNotIn("semua watchlist LP", captions)

    def test_lp_rows_are_separate_from_holder_watchlist(self):
        app = self._app()
        keys = [button.key or "" for button in app.button]
        self.assertIn(f"lp-move-{LP_MINT}", keys)
        self.assertNotIn(f"to-lp-{HOLDER_MINT}", keys)
        # token LP tidak punya tombol baris watchlist biasa
        self.assertNotIn(f"to-lp-{LP_MINT}", keys)
        self.assertNotIn(f"remove-{LP_MINT}", keys)

    def test_move_button_sends_token_to_lp_card(self):
        app = self._app().switch_page("pages/8_temp.py").run()
        with mock.patch("watchlist.set_watchlist_source",
                        return_value=True) as move:
            self._button(app, f"to-lp-{HOLDER_MINT}").click().run()
        move.assert_called_once_with(HOLDER_MINT, "meteora", background=True)

    def test_move_back_button_returns_token_to_holder_watchlist(self):
        app = self._app()
        with mock.patch("watchlist.set_watchlist_source",
                        return_value=True) as move:
            self._button(app, f"lp-move-{LP_MINT}").click().run()
        move.assert_called_once_with(LP_MINT, "manual", background=True)

    def test_manual_add_can_target_the_lp_card(self):
        app = self._app().switch_page("pages/8_temp.py").run()
        # Radio form add token Solana (bukan form Robinhood yang juga punya
        # radio "Masuk ke card") — dibedakan lewat key eksplisit.
        radios = [node for node in app.radio if node.key == "add-token-target"]
        self.assertTrue(radios, "radio pilihan card tidak ditemukan")
        self.assertEqual(list(radios[0].options), [HOLDER_TAB, LP_TAB])

        radios[0].set_value(LP_TAB)
        inputs = [node for node in app.text_input
                  if node.key == "add-token-input"]
        self.assertTrue(inputs)
        inputs[0].set_value(LP_MINT[:32])
        submit = [button for button in app.button
                  if "Tambah ke watchlist" in (button.label or "")]
        self.assertTrue(submit)
        with mock.patch("watchlist.add_to_watchlist",
                        return_value=True) as add:
            submit[0].click().run()
        self.assertEqual(add.call_args.kwargs["source"], "meteora")

    def test_manual_add_defaults_to_holder_watchlist(self):
        app = self._app().switch_page("pages/8_temp.py").run()
        inputs = [node for node in app.text_input
                  if node.key == "add-token-input"]
        inputs[0].set_value(HOLDER_MINT[:32])
        submit = [button for button in app.button
                  if "Tambah ke watchlist" in (button.label or "")][0]
        with mock.patch("watchlist.add_to_watchlist",
                        return_value=True) as add:
            submit.click().run()
        self.assertEqual(add.call_args.kwargs["source"], "manual")

    def test_lp_card_form_adds_with_meteora_source(self):
        app = self._app()
        inputs = [node for node in app.text_input
                  if node.key == "lp-ca-input"]
        self.assertTrue(inputs, "form CA di card LP tidak ditemukan")
        inputs[0].set_value(LP_MINT[:32])
        submit = [button for button in app.button
                  if "Tambah ke Watchlist Meteora" in (button.label or "")]
        self.assertTrue(submit)
        with mock.patch("watchlist.add_to_watchlist",
                        return_value=True) as add:
            submit[0].click().run()
        self.assertEqual(add.call_args.kwargs["source"], "meteora")

    def test_scan_sekarang_button_on_chart_lp(self):
        app = self._app()
        keys = [button.key or "" for button in app.button]
        self.assertIn("lp-scan-now", keys)
        labels = [button.label or "" for button in app.button]
        self.assertTrue(any("Scan sekarang Watchlist Meteora" in lab
                            for lab in labels))

    def test_scan_sekarang_hanya_token_lp(self):
        app = self._app()
        btn = [button for button in app.button if button.key == "lp-scan-now"]
        self.assertTrue(btn, "tombol Scan sekarang Watchlist Meteora "
                             "tidak ditemukan")
        analysis = {
            "ca": LP_MINT, "symbol": "LPRISK", "analyzed_at": 1,
            "holders": {"total_fetched": 80, "wallets_analyzed": 80,
                        "dust_count": 10, "dust_pct_mc": 1.0, "real_count": 70},
        }

        def _analyze(mint, *args, **kwargs):
            item = dict(analysis)
            item["ca"] = mint
            return item

        with mock.patch("holder_analysis.analyze_token",
                        side_effect=_analyze) as analyze, \
                mock.patch("holder_history.ingest_many") as ingest, \
                mock.patch("holder_status.publish_holder_status",
                           return_value={"updated_at": 1}) as pub:
            result = btn[0].click().run()
        self.assertEqual(len(result.exception), 0)
        scanned = {call.args[0] for call in analyze.call_args_list}
        self.assertIn(LP_MINT, scanned)
        self.assertIn(LP_SAFE, scanned)
        self.assertNotIn(HOLDER_MINT, scanned)
        self.assertTrue(analyze.call_args.kwargs.get("detail") is False)
        ingest.assert_called()
        self.assertFalse(ingest.call_args.kwargs.get("detail"))
        pub.assert_called()
        self.assertFalse(pub.call_args.kwargs.get("push"))

    def test_invalid_ca_is_rejected_without_adding(self):
        app = self._app()
        inputs = [node for node in app.text_input
                  if node.key == "lp-ca-input"]
        inputs[0].set_value("bukan-address")
        submit = [button for button in app.button
                  if "Tambah ke Watchlist Meteora" in (button.label or "")][0]
        with mock.patch("watchlist.add_to_watchlist") as add:
            result = submit.click().run()
        add.assert_not_called()
        self.assertTrue(any("Format CA tidak valid" in node.value
                            for node in result.warning))


@unittest.skipIf(AppTest is None, "streamlit not installed")
class EmptyChartLpCardTest(unittest.TestCase):
    def test_empty_card_shows_hint(self):
        patches = (
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value={"tokens": {}}),
            # Backup durable store: tes tidak boleh menyentuh jaringan.
            mock.patch("holder_history.pull_holder_history", return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60).run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("🌊 Watchlist Meteora</span>", body)
        self.assertTrue(any("Watchlist Meteora masih kosong" in node.value
                            for node in app.info))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


@unittest.skipIf(AppTest is None, "streamlit not installed")
class MeteoraBestBadgeTest(unittest.TestCase):
    """Badge 🏆 BEST POOL di listing Scan Meteora (dust < 0,1% + data valid).

    Card **Scan Meteora Pool** dipindah ke halaman temp sejak 2026-09-10 —
    AppTest dijalankan dari entrypoint ``app.py`` lalu ``switch_page`` ke
    temp (pola yang sama dengan test_temp_page) supaya registry multipage
    sama dengan deployment.
    """

    def _temp_app(self):
        patches = (
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value={"tokens": {}}),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
            # Store Robinhood + setelan notif: tes ini tidak boleh menyentuh
            # jaringan / file lokal sama sekali.
            mock.patch("robinhood_watchlist.load_watchlist",
                       return_value={}),
            mock.patch("robinhood_watchlist.load_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("robinhood_watchlist.load_history",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("alert_settings.regular_telegram_enabled",
                       return_value=True),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60)
        app.switch_page(TEMP)
        return app

    CLEAN = "CleanMint1111111111111111111111111111111111"
    BOGUS = "BogusMint1111111111111111111111111111111111"
    THIN = "ThinMint11111111111111111111111111111111111"

    def _scan_rows(self):
        return {
            "rows": [
                # Pool bersih: dust 0,02% MC, data holder valid, TVL 25K.
                {"ca": self.CLEAN, "symbol": "CLN", "pool_address": "P1",
                 "in_24h": True, "in_1h": False, "mc": 1_000_000.0,
                 "tvl": 25_000.0,
                 "dust_count": 3, "dust_pct_mc": 0.02, "real_count": 80,
                 "analysis": {"holders": {
                     "total_fetched": 200, "wallets_analyzed": 83,
                     "real_count": 80, "dust_count": 3,
                     "dust_pct_mc": 0.02}}},
                # Data holder gagal (fetch 0) dengan dust 0,00%: TIDAK boleh
                # dapat BEST POOL (dust 0 juga muncul saat data kosong).
                {"ca": self.BOGUS, "symbol": "BGS", "pool_address": "P2",
                 "in_24h": True, "in_1h": True, "mc": 900_000.0,
                 "tvl": 50_000.0,
                 "dust_count": 0, "dust_pct_mc": 0.0, "real_count": 0,
                 "analysis": {"holders": {
                     "total_fetched": 0, "wallets_analyzed": 0,
                     "real_count": 0, "dust_count": 0, "dust_pct_mc": 0.0}}},
                # Dust bersih + holder valid tapi TVL 4K (< 10K): bukan BEST.
                {"ca": self.THIN, "symbol": "THN", "pool_address": "P3",
                 "in_24h": False, "in_1h": True, "mc": 300_000.0,
                 "tvl": 4_000.0,
                 "dust_count": 1, "dust_pct_mc": 0.01, "real_count": 90,
                 "analysis": {"holders": {
                     "total_fetched": 150, "wallets_analyzed": 91,
                     "real_count": 90, "dust_count": 1,
                     "dust_pct_mc": 0.01}}},
            ],
            "error": "", "fetched": 3, "hidden_dust": 0,
            "analyzed_at": 1_800_000_000,
        }

    def test_badge_best_pool_hanya_untuk_data_valid(self):
        app = self._temp_app()
        app.session_state["meteora_scan"] = self._scan_rows()
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$CLN", body)
        self.assertIn("$BGS", body)
        self.assertIn("$THN", body)
        # Persis satu chip BEST POOL: untuk CLN (0,02% + 83 wallet + TVL
        # 25K). CSS .dust-best ikut di markdown <style>, jadi yang dihitung
        # chip-nya. THN (TVL 4K) dan BGS (holder 0) tidak dapat chip.
        self.assertEqual(body.count("dust-badge dust-best"), 1)
        self.assertIn("🏆 BEST POOL", body)
        cln_index = body.find("$CLN")
        bgs_index = body.find("$BGS")
        thn_index = body.find("$THN")
        self.assertIn("dust-best", body[cln_index:bgs_index])
        self.assertNotIn("dust-best", body[bgs_index:thn_index])
        self.assertNotIn("dust-best", body[thn_index:])
        # Kolom TVL ikut dirender.
        self.assertIn("$25.0K", body[cln_index:bgs_index])
        self.assertIn("$4.0K", body[thn_index:])
        # Badge level AMAN/HATI-HATI/BAHAYA sudah dinonaktifkan di listing
        # Scan Meteora (2026-09-07): tidak ada chip level di baris mana pun.
        listing = body[cln_index:]
        for cls in ("dust-badge dust-ok", "dust-badge dust-caution",
                    "dust-badge dust-danger", "dust-badge dust-none"):
            self.assertNotIn(cls, listing)

    def test_best_pool_dirender_paling_atas(self):
        """Permintaan user 2026-09-08: BEST POOL urut pertama di listing.

        Data uji sengaja menaruh CLEAN (satu-satunya BEST POOL) di posisi
        pertama input, lalu diacak: setelah sort, CLN tetap harus di atas
        BGS/THN meski aslinya bukan yang teratas dari API.
        """
        scan = self._scan_rows()
        # Acak: BEST POOL (CLN) ditaruh paling BELAKANG oleh "API".
        scan["rows"] = [scan["rows"][1], scan["rows"][2], scan["rows"][0]]
        app = self._temp_app()
        app.session_state["meteora_scan"] = scan
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        cln_index = body.find("$CLN")
        bgs_index = body.find("$BGS")
        thn_index = body.find("$THN")
        self.assertNotEqual(cln_index, -1)
        # BEST POOL naik ke urutan pertama meski input menaruhnya terakhir.
        self.assertLess(cln_index, bgs_index)
        self.assertLess(cln_index, thn_index)
        # Chip-nya tetap menempel di baris CLN saja.
        self.assertIn("dust-best", body[cln_index:min(bgs_index, thn_index)])
        self.assertEqual(body.count("dust-badge dust-best"), 1)
        # Ringkasan menyebut jumlah BEST POOL — angka saja, tanpa menulis
        # ulang ambangnya (itu isi tooltip judul; 2026-09-11).
        caption = "\n".join(node.value for node in app.caption)
        self.assertIn("🏆 1 BEST POOL", caption)
        self.assertNotIn("dust > 0.1% MC", caption)
        self.assertIn('title="Top DLMM 24 jam', "\n".join(
            node.value for node in app.markdown))


@unittest.skipIf(AppTest is None, "streamlit not installed")
class TableColumnsRemovedTest(ChartLpCardTest):
    """Kolom **Δ 4 jam** + **Grafik 4 jam** dihapus (permintaan 2026-09-07)."""

    def test_delta_and_sparkline_columns_are_gone(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = self._body(app)
        self.assertNotIn("Δ 4 jam", body)
        self.assertNotIn("Grafik 4 jam", body)
        self.assertNotIn("<svg", body)          # sparkline baris hilang
        self.assertNotIn("belum ada grafik", body)
        # Kolom yang tersisa tetap ada.
        for title in ("Token", "Dust", "Hold %MC"):
            self.assertIn(title, body)

    def test_lp_chart_uses_five_minute_buckets(self):
        app = self._app()
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("titik per 5 menit", captions)
        self.assertNotIn("titik per 4 jam", captions)
