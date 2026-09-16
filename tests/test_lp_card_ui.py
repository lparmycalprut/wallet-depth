"""AppTest: card **Watchlist Meteora** (dulu "Chart LP") di halaman utama.

Menutup perilaku yang diminta user:
- token ``source=meteora`` tampil di card paling atas, bukan di watchlist biasa;
- badge **HATI-HATI** (≥ 0,5% MC) dan **BAHAYA** (≥ 1% MC);
- grafik perubahan dust holder ikut ter-render;
- tambah manual bisa diarahkan ke Watchlist Meteora (radio) atau lewat form
  di card;
- tombol 🌊 memindahkan token watchlist biasa ke Watchlist Meteora;
- detail karakteristik card = tooltip judul (2026-09-10), bukan caption.
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

ROOT = Path(__file__).resolve().parent.parent
# Card 🌊 Watchlist Meteora pindah ke halaman **📦 TEMP** (2026-09-16, permintaan
# user) — seluruh uji AppTest di file ini jadi menjalankan file halaman itu,
# bukan app.py lagi. Widget key + isi card tidak berubah, jadi yang berubah di
# sini hanya alamat file.
APP = str(ROOT / "app.py")
TEMP = str(ROOT / "pages/6_📦_TEMP.py")

LP_MINT = "LpMint11111111111111111111111111111111111"
LP_SAFE = "LpSafe22222222222222222222222222222222222"
# base58 valid (tanpa 0/O/I/l) supaya lolos validasi CA di UI
HOLDER_MINT = "Watch11111111111111111111111111111111111"
BUCKET = hh.INTERVAL_SEC


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
        return AppTest.from_file(TEMP, default_timeout=60).run()

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
        app = AppTest.from_file(TEMP, default_timeout=60).run()
        self.assertEqual(len(app.exception), 0)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("📌 Saat masuk watchlist", captions)
        # LPRISK: titik pertama 0,62% → sekarang 1,35% (+0,73 pp).
        self.assertIn("dust 0.620% MC", captions)
        self.assertIn("sekarang 1.350% MC (+0.730 pp)", captions)
        self.assertIn("patokan notif ⚡ EARLY DUMP", captions)
        # Angka yang sama kini juga tampil sebagai KOLOM "Awal Masuk" di
        # tabel (permintaan user 2026-09-13) — terlihat tanpa membuka
        # expander; title sel = kalimat lengkap baseline_note().
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(">Awal Masuk</div>", body)
        self.assertIn('watchlist-metric-value">0.620%', body)   # LPRISK
        self.assertIn('watchlist-metric-value">0.300%', body)   # LPSAFE
        self.assertIn('title="📌 Saat masuk watchlist', body)
        # Tooltip sel LPSAFE: 0,30% → sekarang 0,61% (+0,31 pp).
        self.assertIn("· sekarang 0.610% MC (+0.310 pp)", body)

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

    def test_move_back_button_returns_token_to_holder_watchlist(self):
        app = self._app()
        with mock.patch("watchlist.set_watchlist_source",
                        return_value=True) as move:
            self._button(app, f"lp-move-{LP_MINT}").click().run()
        move.assert_called_once_with(LP_MINT, "manual", background=True)

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
        app = AppTest.from_file(TEMP, default_timeout=60).run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("🌊 Watchlist Meteora</span>", body)
        self.assertTrue(any("Watchlist Meteora masih kosong" in node.value
                            for node in app.info))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


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
