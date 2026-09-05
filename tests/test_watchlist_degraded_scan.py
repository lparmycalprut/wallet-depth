"""AppTest: baris watchlist saat scan holder terakhir **tidak lengkap**.

Menutup bug yang dilaporkan user 2026-09-06: "banyak yang jadi −100% padahal
cron sudah terjadi beberapa kali". Penyebabnya bukan perhitungan perubahan,
melainkan **data** scan terakhir: Helius mati (rate limit) → fallback GMGN
mengembalikan satu halaman berisi 20 holder dengan ``truncated: False``.
Wallet dust (nilai ≤ $10) ada di ekor daftar holder, jadi sampel sependek itu
selalu berisi ``dust 0`` / ``0,00% MC`` — dan kolom **Sejak masuk** lalu
mengklaim "dust turun 100%" untuk puluhan token.

Yang diuji di sini (semuanya lewat ``app.py`` sungguhan):

- angka baris memakai scan layak terakhir, bukan 0,00% palsu;
- kolom **Sejak masuk** tidak lagi −100% dan diberi penanda ⚠️;
- caption menyebut berapa token yang scan terakhirnya tidak lengkap;
- token yang **semua** scan-nya pendek jujur menulis "belum ada data".
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

APP = str(Path(__file__).resolve().parent.parent / "app.py")

GOOD_MINT = "GoodMint1111111111111111111111111111111111"
BAD_MINT = "BadMint222222222222222222222222222222222222"

BASE = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
HOUR = 3600
DAY = 86_400
SHORT_WALLETS = 19


def _point(ts, pct, count, wallets):
    return {"ts": int(ts), "price": 0.01, "mc": 100_000.0,
            "dust_count": count, "dust_pct_mc": pct,
            "dust_value_usd": count * 5.0, "real_count": wallets - count,
            "real_pct_mc": 20.0, "mid_count": 0, "mid_pct_mc": 0.0,
            "cohort_token_pct": None, "cohort_cut50_pct": None,
            "cohort_n": 0, "holder_count": wallets,
            "buckets": {">$0-$10": count}}


def _points():
    return {
        # dua scan layak lalu satu scan pendek (20 holder, dust 0)
        GOOD_MINT: [_point(BASE + 2 * HOUR, 0.40, 200, 2_000),
                    _point(BASE + DAY, 0.30, 150, 1_996),
                    _point(BASE + 2 * DAY, 0.0, 0, SHORT_WALLETS)],
        # token ini belum pernah dapat scan yang layak
        BAD_MINT: [_point(BASE + 2 * HOUR, 0.0, 0, SHORT_WALLETS),
                   _point(BASE + 2 * DAY, 0.0, 0, SHORT_WALLETS)],
    }


def _watchlist():
    return {GOOD_MINT: {"symbol": "GDST", "source": "manual",
                        "added": "2026-09-01"},
            BAD_MINT: {"symbol": "SHRT", "source": "manual",
                       "added": "2026-09-01"}}


def _short_holders():
    return {"dust_count": 0, "dust_pct_mc": 0.0,
            "real_count": SHORT_WALLETS, "wallets_analyzed": SHORT_WALLETS,
            "total_fetched": SHORT_WALLETS + 1, "source": "gmgn"}


def _status():
    points = _points()
    tokens = {}
    for mint in (GOOD_MINT, BAD_MINT):
        tokens[mint] = {"symbol": _watchlist()[mint]["symbol"],
                        "marketcap": 100_000.0, "price": 0.01,
                        "analyzed_at": points[mint][-1]["ts"],
                        "holders": _short_holders(),
                        "history": points[mint]}
    return {"updated_at": BASE + 2 * DAY, "scanner": "holder-dust-v1",
            "tokens": tokens}


def _store():
    return {"updated_at": BASE + 2 * DAY,
            "tokens": {mint: {"symbol": _watchlist()[mint]["symbol"],
                              "cohort": {}, "points": points}
                       for mint, points in _points().items()}}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class DegradedScanWatchlistRowTest(unittest.TestCase):
    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: _watchlist()),
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
        return AppTest.from_file(APP, default_timeout=60).run()

    def _body(self, app):
        return "\n".join(node.value for node in app.markdown)

    def _captions(self, app):
        return "\n".join(node.value for node in app.caption)

    def test_page_renders_without_exception(self):
        self.assertEqual(len(self._app().exception), 0)

    def test_fake_zero_percent_is_not_displayed(self):
        body = self._body(self._app())
        # Hold %MC tidak boleh lagi menampilkan 0,00% dari sampel 20 wallet.
        self.assertNotIn('watchlist-metric-value">0.00%', body)
        self.assertIn('watchlist-metric-value">0.30%', body)

    def test_sejak_masuk_is_not_minus_100(self):
        body = self._body(self._app())
        self.assertNotIn("-100.0%", body)
        # 0,40% -> 0,30% (dua scan layak) = -25%, dengan penanda ⚠️ karena
        # run terakhir datanya dibuang.
        self.assertIn("-25.0%", body)
        self.assertIn("⚠️", body)
        self.assertIn(f"{SHORT_WALLETS} wallet", body)

    def test_caption_reports_the_incomplete_scans(self):
        captions = self._captions(self._app())
        self.assertIn("scan terakhirnya tidak lengkap", captions)
        self.assertIn("2 token", captions)

    def test_token_with_only_short_scans_says_no_data(self):
        body = self._body(self._app())
        self.assertIn("belum ada data ⚠️", body)
