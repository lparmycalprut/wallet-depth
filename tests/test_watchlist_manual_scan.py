"""AppTest: tombol **🔄 Scan holder watchlist** tidak menimpa data tercatat.

Permintaan user 2026-09-06: "ketika saya scan dari main app page, jangan timpa
data awal yang sudah tercatat, tapi update list dari watchlist yang sudah
dilakukan".

Tiga kebocoran yang ditutup di sini:

1. ``publish_holder_status(...)`` dipanggil **tanpa** ``merge_status``,
   sedangkan ``snapshot_status`` membangun ``tokens`` hanya dari analyses yang
   diberikan — akibatnya token yang scan-nya gagal **hilang** dari snapshot
   (datanya tertimpa) sampai cron berikutnya.
2. Analisis yang holdernya tidak lengkap (provider mengembalikan sampel
   pendek, ``dust 0``) ikut di-publish → angka tercatat yang benar ditimpa
   0,00% dan baris membaca "dust habis".
3. Baseline scan FULL / ``latest_detail`` / kronologi adalah *data awal*
   yang tidak boleh disentuh scan halaman utama
   (``ingest_many(detail=False)``).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import watchlist_detail as wd

APP = str(Path(__file__).resolve().parent.parent / "app.py")

GOOD = "GoodMint1111111111111111111111111111111111"
FAILS = "FailMint2222222222222222222222222222222222"
SHORT = "ShortMint333333333333333333333333333333333"
BASELINE_TS = 1_700_000_000
POINT_TS = BASELINE_TS + 4 * 3600
SCAN_TS = POINT_TS + 4 * 3600


def _holders(dust, pct, wallets):
    return {"dust_count": dust, "dust_pct_mc": pct, "dust_value_usd": dust * 5,
            "real_count": wallets - dust, "real_pct_mc": 12.0,
            "wallets_analyzed": wallets, "total_fetched": wallets,
            "truncated": False, "source": "helius",
            "mid": {"count": 2, "pct_mc": 3.0, "balances": {}}}


def _watchlist():
    return {
        GOOD: {"symbol": "GOOD", "source": "manual", "added": "2026-09-01"},
        FAILS: {"symbol": "FAIL", "source": "manual", "added": "2026-09-01"},
        SHORT: {"symbol": "SHRT", "source": "manual", "added": "2026-09-01"},
    }


def _status():
    """Snapshot cron: ketiga token punya angka tercatat."""
    tokens = {}
    for mint, dust, pct in ((GOOD, 90, 0.80), (FAILS, 120, 1.30),
                            (SHORT, 70, 0.55)):
        tokens[mint] = {
            "symbol": _watchlist()[mint]["symbol"], "marketcap": 100_000.0,
            "price": 0.01, "analyzed_at": POINT_TS,
            "holders": _holders(dust, pct, 900),
            "history": [{"ts": POINT_TS, "dust_count": dust,
                         "dust_pct_mc": pct, "holder_count": 900}],
        }
    return {"updated_at": POINT_TS, "scanner": "holder-dust-v1",
            "tokens": tokens}


def _store():
    """Store dengan baseline scan FULL (data awal) untuk setiap token."""
    def _slot(symbol):
        baseline = {"ts": BASELINE_TS, "symbol": symbol, "dust_count": 80,
                    "dust_pct_mc": 0.70, "holder_count": 800,
                    "depth": {"buckets": [{">$0-$10": 80}], "tiers": []}}
        return {"symbol": symbol, "cohort": {"frozen_at": BASELINE_TS,
                                             "balances": {}},
                "baseline": baseline, "latest_detail": dict(baseline),
                "points": [{"ts": POINT_TS, "dust_count": 85,
                            "dust_pct_mc": 0.75, "holder_count": 850}]}
    return {"updated_at": POINT_TS,
            "tokens": {GOOD: _slot("GOOD"), FAILS: _slot("FAIL"),
                       SHORT: _slot("SHRT")}}


def _analysis(mint, dust, pct, wallets):
    return {"ca": mint, "symbol": _watchlist()[mint]["symbol"],
            "marketcap": 100_000.0, "price": 0.01, "analyzed_at": SCAN_TS,
            "holders": _holders(dust, pct, wallets)}


def _analyze(mint, symbol="?", **_kwargs):
    if mint == FAILS:
        raise RuntimeError("Helius 429")
    if mint == SHORT:
        # Provider pulang dengan sampel pendek: dust selalu 0.
        return _analysis(mint, 0, 0.0, 19)
    return _analysis(mint, 95, 0.85, 950)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class ManualWatchlistScanTest(unittest.TestCase):
    def _run_scan(self):
        self.written = {}
        self.store = _store()

        def _write(path, payload, **_kw):
            self.written[str(path)] = payload

        def _save(store, path=None):
            self.store = store
            return store

        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: _watchlist()),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: _status()),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: _store()),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
            mock.patch("holder_analysis.analyze_token", side_effect=_analyze),
            mock.patch("holder_status.atomic_write_json", side_effect=_write),
            mock.patch("holder_history.save_holder_history",
                       side_effect=_save),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60).run()
        self.assertEqual(len(app.exception), 0)
        # Label Robinhood ("🔄 Scan holder watchlist Robinhood …") punya
        # prefiks yang sama — pilih yang persis tombol watchlist Solana.
        buttons = [b for b in app.button
                   if (b.label or "") == "🔄 Scan holder watchlist"]
        self.assertTrue(buttons, "tombol scan watchlist tidak ditemukan")
        buttons[0].click().run()
        self.assertEqual(len(app.exception), 0)
        return app

    def _snapshot(self):
        rows = [value for key, value in self.written.items()
                if key.endswith("holder_status.json")]
        self.assertTrue(rows, "snapshot tidak ditulis")
        return rows[-1]

    def test_token_yang_gagal_tetap_ada_di_snapshot(self):
        """Tanpa ``merge_status`` baris FAIL hilang dari dashboard."""
        self._run_scan()
        tokens = self._snapshot()["tokens"]
        self.assertEqual(set(tokens), {GOOD, FAILS, SHORT})
        # angka tercatat token yang gagal dipertahankan, bukan dikosongkan
        self.assertEqual(tokens[FAILS]["holders"]["dust_pct_mc"], 1.30)
        self.assertEqual(tokens[FAILS]["holders"]["dust_count"], 120)

    def test_scan_tidak_lengkap_tidak_menimpa_angka_tercatat(self):
        self._run_scan()
        tokens = self._snapshot()["tokens"]
        # SHORT cuma dapat 19 wallet → dust 0,00% palsu tidak boleh masuk
        self.assertEqual(tokens[SHORT]["holders"]["dust_pct_mc"], 0.55)
        self.assertEqual(tokens[SHORT]["analyzed_at"], POINT_TS)
        # token yang scan-nya layak tetap diperbarui
        self.assertEqual(tokens[GOOD]["holders"]["dust_pct_mc"], 0.85)
        self.assertEqual(tokens[GOOD]["analyzed_at"], SCAN_TS)

    def test_hanya_scan_layak_yang_masuk_history(self):
        self._run_scan()
        points = {mint: [p["ts"] for p in slot["points"]]
                  for mint, slot in self.store["tokens"].items()}
        # titik baru ditambahkan hanya untuk token yang scan-nya layak
        # (``ingest_many`` memberi cap waktu run, jadi nilainya "sekarang").
        self.assertEqual(len(points[GOOD]), 2)
        self.assertGreater(points[GOOD][-1], POINT_TS)
        self.assertEqual(points[FAILS], [POINT_TS])
        self.assertEqual(points[SHORT], [POINT_TS])

    def test_baseline_scan_full_tidak_ditimpa(self):
        self._run_scan()
        for mint in (GOOD, FAILS, SHORT):
            slot = self.store["tokens"][mint]
            self.assertEqual(slot["baseline"]["ts"], BASELINE_TS)
            self.assertEqual(slot["latest_detail"]["ts"], BASELINE_TS)

    def test_laporan_scan_menyebut_yang_dilewati(self):
        app = self._run_scan()
        infos = "\n".join(node.value for node in app.info)
        self.assertIn("1 token diperbarui", infos)
        self.assertIn("tidak lengkap dilewati", infos)
        self.assertIn("SHRT", infos)
        self.assertIn("Baseline scan FULL", infos)

    def test_laporan_menyebut_list_diperbarui_sampai_waktu_snapshot(self):
        app = self._run_scan()
        infos = "\n".join(node.value for node in app.info)
        snapshot = self._snapshot()
        self.assertIn("list holder diperbarui sampai snapshot", infos)
        self.assertIn(wd.format_wib(snapshot.get("updated_at")), infos)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
