"""AppTest: kolom **Sejak masuk** + sinkronisasi baris watchlist di app.py.

Menutup perilaku yang diminta user 2026-09-04:

- sejak ditambahkan ke watchlist sampai scan terakhir, berapa % dust holder
  naik/turun (angka relatif + poin persentase + jumlah wallet);
- warna berbeda saat dust % MC yang dipegang **turun ≥ 50%** (hijau) atau
  **naik ≥ 100%** (merah);
- baris watchlist dan "scan terakhir" membaca data yang sama: bila titik
  ``holder_history`` lebih baru daripada snapshot ``holder_status``, angka
  baris ikut titik terbaru dan caption menandainya.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import holder_history as hh
import watchlist_detail as wd

APP = str(Path(__file__).resolve().parent.parent / "app.py")

DROP_MINT = "DropMint1111111111111111111111111111111"
RISE_MINT = "RiseMint2222222222222222222222222222222"
SYNC_MINT = "SyncMint3333333333333333333333333333333"

BASE = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
HOUR = 3600
DAY = 86_400

GREEN = wd.TONE_COLORS[wd.TONE_DROP]
RED = wd.TONE_COLORS[wd.TONE_RISE]


def _point(ts, pct, count):
    return {"ts": int(ts), "price": 0.01, "mc": 100_000.0,
            "dust_count": count, "dust_pct_mc": pct,
            "dust_value_usd": count * 5.0, "real_count": 40,
            "real_pct_mc": 20.0, "mid_count": 6, "mid_pct_mc": 4.0,
            "cohort_token_pct": 90.0, "cohort_cut50_pct": 10.0,
            "cohort_n": 6, "holder_count": count + 40,
            "buckets": {">$0-$10": count}}


def _points():
    return {
        # 0,40% -> 0,10% MC = turun 75% (hijau)
        DROP_MINT: [_point(BASE + 2 * HOUR, 0.40, 200),
                    _point(BASE + DAY, 0.10, 80)],
        # 0,20% -> 0,60% MC = naik 200% (merah)
        RISE_MINT: [_point(BASE + 2 * HOUR, 0.20, 100),
                    _point(BASE + DAY, 0.60, 180)],
        # snapshot cron 0,30% tetapi titik history 0,71% lebih baru
        SYNC_MINT: [_point(BASE + 2 * HOUR, 0.30, 120),
                    _point(BASE + 2 * DAY, 0.71, 210)],
    }


def _watchlist():
    return {mint: {"symbol": symbol, "source": "manual", "added": "2026-09-01"}
            for mint, symbol in ((DROP_MINT, "DRP"), (RISE_MINT, "RSE"),
                                 (SYNC_MINT, "SYN"))}


def _status():
    points = _points()
    tokens = {}
    for mint in (DROP_MINT, RISE_MINT):
        last = points[mint][-1]
        tokens[mint] = {"symbol": _watchlist()[mint]["symbol"],
                        "marketcap": 100_000.0, "price": 0.01,
                        "analyzed_at": last["ts"],
                        "holders": {"dust_count": last["dust_count"],
                                    "dust_pct_mc": last["dust_pct_mc"],
                                    "real_count": 40, "total_fetched": 200},
                        "history": points[mint]}
    stale = points[SYNC_MINT][0]
    tokens[SYNC_MINT] = {"symbol": "SYN", "marketcap": 100_000.0,
                         "price": 0.01, "analyzed_at": stale["ts"],
                         "holders": {"dust_count": stale["dust_count"],
                                     "dust_pct_mc": stale["dust_pct_mc"],
                                     "real_count": 40, "total_fetched": 200},
                         "history": points[SYNC_MINT]}
    return {"updated_at": BASE + 2 * DAY, "scanner": "holder-dust-v1",
            "tokens": tokens}


def _store():
    """Store ``holder_history``: titik yang sama dengan snapshot + 1 lebih baru."""
    return {"updated_at": BASE + 2 * DAY,
            "tokens": {mint: {"symbol": _watchlist()[mint]["symbol"],
                              "cohort": {}, "points": points}
                       for mint, points in _points().items()}}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class WatchlistRowDetailTest(unittest.TestCase):
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
        return AppTest.from_file(APP, default_timeout=60).switch_page("pages/8_temp.py").run()

    def _body(self, app):
        return "\n".join(node.value for node in app.markdown)

    def _captions(self, app):
        return "\n".join(node.value for node in app.caption)

    def test_page_renders_the_new_column(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Sejak masuk", self._body(app))

    def test_kolom_awal_masuk_menampilkan_dust_saat_ditambahkan(self):
        """Kolom **Awal Masuk** (permintaan user 2026-09-13): dust % MC saat
        token masuk watchlist tampil langsung di tabel, di sebelah kiri
        "Sejak masuk" — angka yang sama dengan patokan notif ⚡ EARLY DUMP."""
        body = self._body(self._app())
        self.assertIn(">Awal Masuk</div>", body)
        # Titik pembanding tiap token = titik pertama pada/setelah ``added``
        # (2026-09-01): DRP 0,40%, RSE 0,20%, SYN 0,30%.
        self.assertIn('watchlist-metric-value">0.400%', body)   # DRP
        self.assertIn('watchlist-metric-value">0.200%', body)   # RSE
        self.assertIn('watchlist-metric-value">0.300%', body)  # SYN
        # Angka baris (Hold %MC) tidak berubah karena kolom baru: SYN tetap
        # memakai titik history 0,71%, bukan snapshot 0,30%.
        self.assertIn('watchlist-metric-value">0.71%', body)
        # Hover sel = kalimat lengkap baseline_note().
        self.assertIn('title="📌 Saat masuk watchlist', body)

    def test_drop_and_rise_use_different_colors(self):
        body = self._body(self._app())
        self.assertIn(GREEN, body)
        self.assertIn(RED, body)
        # angka relatif sejak masuk watchlist
        self.assertIn("-75.0%", body)
        self.assertIn("+200.0%", body)
        # detail pembanding (dust % MC awal -> akhir + perubahan jumlah wallet)
        self.assertIn("0.40→0.10% MC", body)
        self.assertIn("0.20→0.60% MC", body)
        self.assertIn("-60% wallet", body)
        self.assertIn("+80% wallet", body)

    def test_caption_reports_one_synced_scan_time(self):
        captions = self._captions(self._app())
        self.assertIn("Scan terakhir:", captions)
        self.assertIn(wd.format_wib(BASE + 2 * DAY), captions)
        # token dengan titik history lebih baru daripada snapshot cron
        self.assertIn("1 dari titik history lebih baru", captions)
        self.assertIn("snapshot ≠ titik history", captions)

    def test_row_uses_the_newer_history_value(self):
        body = self._body(self._app())
        # Kartu "Hold %MC" SYN memakai 0,71% dari titik history, bukan 0,30%
        # dari snapshot cron (0,30% hanya boleh muncul sebagai pembanding).
        self.assertIn('watchlist-metric-value">0.71%', body)
        self.assertNotIn('watchlist-metric-value">0.30%', body)
        self.assertIn("titik history", body)

    def test_badge_follows_the_value_that_is_displayed(self):
        app = self._app()
        body = self._body(app)
        self.assertIn("HATI-HATI", body)   # SYN 0,71% MC
        self.assertIn("AMAN", body)        # DRP 0,10% MC

    def test_row_renders_dust_change_chart_like_watchlist_meteora(self):
        """Watchlist biasa = grafik perubahan dust holder ala Watchlist
        Meteora (permintaan user 2026-09-10), bucket 4 jam sesuai kadens."""
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        labels = [node.label or "" for node in app.expander]
        self.assertTrue(any("📈 Grafik perubahan dust holder" in label
                            for label in labels),
                        f"expander grafik tidak ditemukan: {labels}")
        captions = self._captions(app)
        self.assertIn("Garis = dust % marketcap", captions)
        self.assertIn("titik per 4 jam", captions)
        self.assertGreaterEqual(len(app.get("image")), 1)

    def test_default_sort_puts_biggest_dust_drop_first(self):
        """Urutan default sejak 2026-09-05: minus dust sejak masuk di atas.

        DRP turun −75% → baris paling atas, SYN (+137%) di tengah, RSE
        (+200%) paling bawah (sebelumnya urutan alfabetis DRP, RSE, SYN).
        """
        body = self._body(self._app())
        # Card Robinhood (LP + biasa) dirender SEBELUM card Solana dan pada
        # run unittest (stub conftest pytest tidak aktif) ikut menampilkan
        # token watchlist Solana dengan symbol sama — pakai kemunculan
        # TERAKHIR supaya yang dinilai baris card Solana yang terurut.
        order = [body.rfind(f"${symbol}")
                 for symbol in ("DRP", "SYN", "RSE")]
        self.assertGreater(order[0], -1)
        self.assertLess(order[0], order[1])
        self.assertLess(order[1], order[2])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
