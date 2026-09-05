"""Streamlit AppTest untuk halaman Holder Analytic.

Fokus: grafik holder baru (jumlah holder + komposisi bucket + distribusi
scan FULL) dan tombol scan manual yang wajib **FULL** serta menyimpan
detail baseline (``detail=True``). Sejak 2026-09-05 cron ikut scan FULL
+ ``detail=True`` (lihat ``scripts/scan_holders.py``).
"""
from __future__ import annotations

import contextlib
import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency — halaman butuh streamlit saat runtime
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import holder_chronology as hc
import holder_history as hh

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "5_🧮_Holder.py")
MINT = "So11111111111111111111111111111111111111112"
OTHER = "TokenB1111111111111111111111111111111111111"
GROW = "Grow1111111111111111111111111111111111111"
META = {"symbol": "TST"}
HOUR = 3600


def _buckets(base: int):
    return [
        {"label": ">$0-$10", "count": base, "value_usd": base * 5.0,
         "pct_mc": 0.5},
        {"label": "$10-$100", "count": 12, "value_usd": 600.0, "pct_mc": 1.0},
        {"label": "$100-$1k", "count": 5, "value_usd": 2500.0, "pct_mc": 2.0},
    ]


def _point(ts: int, dust: int):
    return {
        "ts": ts, "price": 0.01, "mc": 100_000.0,
        "dust_count": dust, "dust_pct_mc": 0.8, "dust_value_usd": 500.0,
        "real_count": 40, "real_pct_mc": 20.0,
        "mid_count": 6, "mid_pct_mc": 4.0,
        "cohort_token_pct": 90.0, "cohort_cut50_pct": 10.0, "cohort_n": 6,
        "holder_count": dust + 40,
        "buckets": {row["label"]: row["count"] for row in _buckets(dust)},
    }


def _store():
    detail = {
        "ts": 4 * HOUR, "symbol": "TST", "price": 0.01, "mc": 100_000.0,
        "source": "helius", "fetched": 4210, "pages": 5, "truncated": False,
        "holder_count": 130, "dust_count": 90, "dust_pct_mc": 0.8,
        "real_count": 40, "real_pct_mc": 20.0, "mid_count": 6,
        "mid_pct_mc": 4.0,
        "depth": {
            "buckets": _buckets(90),
            "tiers": [{"tier": "Shrimp", "emoji": "🦐", "count": 100,
                       "pct_mc": 1.5}],
            "buckets_include_pools": False, "holders_all": 130,
            "holders_wallet": 130, "pool_excluded": 0,
            "market_cap": 100_000.0,
        },
    }
    grow_before = {"balance": 100.0, "usd": 5.0, "category": "Dust",
                   "dust": True}
    grow_after = {"balance": 250.0, "usd": 25.0, "category": "$10-$100",
                  "dust": False}
    interval = {
        "from_ts": 4 * HOUR, "to_ts": 12 * HOUR,
        "from_metrics": {"ts": 4 * HOUR, "holder_count": 130,
                         "dust_count": 90, "dust_pct_mc": 1.40,
                         "price": 0.01, "mc": 100_000.0},
        "to_metrics": {"ts": 12 * HOUR, "holder_count": 171,
                       "dust_count": 120, "dust_pct_mc": 0.72,
                       "price": 0.01, "mc": 100_000.0},
        "counts": {"increased": 1, "decreased": 0, "new_wallets": 0,
                   "exited_total": 0, "unobserved": 0, "dust_grew_out": 1,
                   "dust_price_exit": 0, "shrank_to_dust": 0,
                   "category_moves": 1, "same_increased": 0,
                   "same_decreased": 0, "compared_wallets": 1},
        "movements": [{
            "address": GROW, "from_category": "Dust",
            "to_category": "$10-$100", "balance_before": 100.0,
            "balance_after": 250.0, "delta_balance": 150.0, "delta_pct": 150.0,
            "usd_before": 5.0, "usd_after": 25.0, "kind": "dust_grew_out",
            "interpretation": ("Wallet menambah muatan dan berpindah dari "
                               "Dust ke $10-$100."),
            "solscan": f"https://solscan.io/account/{GROW}",
        }],
        "truncated": False, "sampled": False, "complete": True,
    }
    return {
        "updated_at": 12 * HOUR,
        "tokens": {
            MINT: {
                "symbol": "TST",
                "cohort": {"frozen_at": 4 * HOUR, "balances": {"A": 10.0}},
                "baseline": detail,
                "latest_detail": {**detail, "ts": 12 * HOUR,
                                  "dust_pct_mc": 0.72, "dust_count": 120,
                                  "holder_count": 171,
                                  "depth": {**detail["depth"],
                                            "buckets": _buckets(120)}},
                "chronology": {
                    "baseline_wallets": {
                        "ts": 4 * HOUR, "wallets": {GROW: grow_before},
                        "sampled": False, "truncated": False,
                    },
                    "latest_wallets": {
                        "ts": 12 * HOUR, "wallets": {GROW: grow_after},
                        "sampled": False, "truncated": False,
                    },
                    "intervals": [interval],
                },
                "points": [_point(4 * HOUR, 90), _point(8 * HOUR, 105),
                           _point(12 * HOUR, 120)],
            }
        },
    }


def _initial_store():
    store = _store()
    slot = store["tokens"][MINT]
    slot["latest_detail"] = dict(slot["baseline"])
    slot["chronology"] = {
        "baseline_wallets": {
            "ts": 4 * HOUR, "wallets": {
                GROW: {"balance": 100.0, "usd": 5.0, "category": "Dust",
                       "dust": True}},
            "sampled": False, "truncated": False,
        },
        "latest_wallets": {
            "ts": 4 * HOUR, "wallets": {
                GROW: {"balance": 100.0, "usd": 5.0, "category": "Dust",
                       "dust": True}},
            "sampled": False, "truncated": False,
        },
        "intervals": [],
    }
    return store


def _analysis():
    return {
        "symbol": "TST", "marketcap": 100_000.0, "price": 0.01,
        "analyzed_at": 16 * HOUR,
        "holders": {
            "dust_count": 130, "dust_pct_mc": 0.9, "dust_value_usd": 600.0,
            "real_count": 41, "real_pct_mc": 21.0, "wallets_analyzed": 171,
            "total_fetched": 4300, "pages": 5, "truncated": False,
            "source": "helius",
            "depth": {"buckets": _buckets(130), "tiers": []},
            "mid": {"count": 6, "pct_mc": 4.0, "balances": {"A": 10.0}},
            "cohort_now": {"A": 9.0},
        },
    }


def _first_metric(app, label: str):
    """Nilai metrik pertama dengan label itu (beberapa label muncul 2x: kartu
    atas vs seksi kronologi)."""
    for node in app.metric:
        if node.label == label:
            return node.value
    return None


@unittest.skipUnless(AppTest is not None, "streamlit is not installed")
class HolderPageChartTest(unittest.TestCase):
    @contextlib.contextmanager
    def _page(self, analyze=None, ingest=None, store=None, watchlist=None,
              query_mint=None, status=None):
        """Jalankan halaman dengan semua dependensi jaringan di-mock."""
        patches = [
            mock.patch("watchlist.load_watchlist",
                       return_value=watchlist or {MINT: META}),
            mock.patch("holder_status.load_holder_status",
                       return_value=status or {"updated_at": None,
                                               "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value=store if store is not None else _store()),
            # Backup durable store: tes tidak boleh menyentuh jaringan.
            mock.patch("holder_history.pull_holder_history", return_value=None),
            mock.patch("core.get_helius_keys", return_value=["test-key"]),
        ]
        if analyze is not None:
            patches.append(mock.patch("holder_analysis.analyze_token",
                                      side_effect=analyze))
        if ingest is not None:
            patches.append(mock.patch("holder_history.ingest_many",
                                      side_effect=ingest))
        for patch in patches:
            patch.start()
        try:
            app = AppTest.from_file(PAGE, default_timeout=30)
            if query_mint:
                app.query_params["mint"] = query_mint
            app.run()
            yield app
        finally:
            for patch in reversed(patches):
                patch.stop()

    def test_page_renders_holder_charts(self):
        with self._page() as app:
            self.assertEqual(len(app.exception), 0)
            headers = " ".join(node.value for node in app.subheader)
            self.assertIn("Grafik holder", headers)
            self.assertIn("Distribusi holder", headers)
            # dust/pilar (2) + jumlah holder + komposisi bucket +
            # bar distribusi scan FULL = 5 figure matplotlib.
            self.assertGreaterEqual(len(app.get("image")), 5)
            # tabel perubahan bucket vs baseline
            self.assertGreaterEqual(len(app.get("dataframe")), 1)

    def test_scan_button_is_full_and_stores_detail(self):
        seen = {}

        def _analyze(mint, symbol="?", **kwargs):
            seen["max_wallets"] = kwargs.get("max_wallets")
            return _analysis()

        def _ingest(analyses, **kwargs):
            seen["detail"] = kwargs.get("detail")
            seen["mints"] = list(analyses)
            return _store()

        with self._page(analyze=_analyze, ingest=_ingest) as app:
            buttons = [b for b in app.button
                       if "Scan holder FULL" in (b.label or "")]
            self.assertTrue(buttons, "tombol scan FULL tidak ditemukan")
            buttons[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(seen.get("max_wallets"), hh.FULL_SCAN_MAX_WALLETS)
            self.assertTrue(seen.get("detail"))
            self.assertEqual(seen.get("mints"), [MINT])

    def test_metric_cards_follow_manual_scan(self):
        """Kartu metrik harus ikut scan manual, bukan snapshot cron lama.

        Regression AGENTHQ: snapshot cron 1,16% (harga lama) vs titik scan
        manual 0,90% — sebelum overlay ``apply_manual_scan``, grafik sudah
        baru tetapi kartu "Dust hold % MC" + badge masih angka lama.
        """
        stale_status = {
            "updated_at": 12 * HOUR,
            "tokens": {MINT: {
                "symbol": "TST", "price": 0.01, "marketcap": 100_000.0,
                "analyzed_at": 12 * HOUR,
                "holders": {"dust_count": 90, "dust_pct_mc": 1.16,
                            "real_count": 40,
                            "mid": {"count": 6, "pct_mc": 4.0}},
                "history": [_point(4 * HOUR, 90), _point(8 * HOUR, 105),
                            _point(12 * HOUR, 120)],
                "cohort": {"frozen_at": 4 * HOUR, "balances": {"A": 10.0}},
            }},
        }
        fresh = _analysis()  # analyzed_at 16 jam, dust_pct_mc 0.9, count 130

        with self._page(analyze=lambda *a, **k: fresh,
                        ingest=lambda *a, **k: _store(),
                        status=stale_status) as app:
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(_first_metric(app, "Dust hold % MC"), "1.16%")
            self.assertEqual(_first_metric(app, "Dust wallet"), "90")
            self.assertNotIn("scan manual barusan",
                             " ".join(c.value for c in app.caption))

            buttons = [b for b in app.button
                       if "Scan holder FULL" in (b.label or "")]
            self.assertTrue(buttons, "tombol scan FULL tidak ditemukan")
            buttons[0].click().run()
            self.assertEqual(len(app.exception), 0)

            self.assertEqual(_first_metric(app, "Dust hold % MC"), "0.90%")
            self.assertEqual(_first_metric(app, "Dust wallet"), "130")
            self.assertEqual(_first_metric(app, "Real >$10"), "41")
            captions = " ".join(c.value for c in app.caption)
            self.assertIn("scan manual barusan", captions)
            # badge mengikuti nilai baru: 0,90% -> HATI-HATI, bukan BAHAYA.
            self.assertIn("HATI-HATI", captions + " ".join(
                n.value for n in app.markdown))

    def test_metric_cards_ignore_manual_scan_for_other_mint(self):
        stale_status = {
            "updated_at": 12 * HOUR,
            "tokens": {MINT: {
                "symbol": "TST", "analyzed_at": 12 * HOUR,
                "holders": {"dust_count": 90, "dust_pct_mc": 1.16,
                            "real_count": 40, "mid": {"count": 6}},
            }},
        }
        with self._page(status=stale_status, query_mint=MINT) as app:
            app.session_state["holder_manual_scan"] = {
                "mint": OTHER, "saved_at": 99 * HOUR,
                "analysis": {"analyzed_at": 99 * HOUR, "price": 0.02,
                             "marketcap": 1.0, "symbol": "LAIN",
                             "holders": {"dust_count": 1, "dust_pct_mc": 9.9,
                                         "real_count": 1, "mid": {}}}}
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(_first_metric(app, "Dust hold % MC"), "1.16%")

@unittest.skipUnless(AppTest is not None, "streamlit is not installed")
class HolderPageRobinhoodTest(unittest.TestCase):
    """Halaman Holder Analytic harus membuka token Robinhood Chain (0x…).

    Tombol 🧮 di card Watchlist Robinhood memakai query param `mint` 0x…;
    halaman memilih watchlist/status/history Robinhood yang terpisah dan
    rule dust (charts/metrik) tetap sama dengan Solana.
    """

    RH_CA = "0x" + "a" * 40

    def _rh_status(self):
        points = [_point(4 * HOUR, 90), _point(8 * HOUR, 95)]
        return {
            "updated_at": 8 * HOUR,
            "tokens": {self.RH_CA: {
                "symbol": "VLAD", "price": 0.01, "marketcap": 100_000.0,
                "analyzed_at": 8 * HOUR,
                "holders": {"dust_count": 95, "dust_pct_mc": 0.42,
                            "real_count": 40, "mid": {"count": 6,
                                                      "pct_mc": 4.0}},
                "history": points,
                "cohort": {"frozen_at": 4 * HOUR, "balances": {}},
            }},
        }

    def test_page_renders_evm_token(self):
        import robinhood_watchlist as rw_mod
        status = self._rh_status()
        with mock.patch.object(rw_mod, "load_watchlist",
                               return_value={self.RH_CA: {"symbol": "VLAD"}}), \
                mock.patch.object(rw_mod, "load_status",
                                  return_value=status), \
                mock.patch.object(rw_mod, "load_history",
                                  return_value={"updated_at": None,
                                                "tokens": {}}):
            app = AppTest.from_file(PAGE, default_timeout=30)
            app.query_params["mint"] = self.RH_CA
            app.run()
        self.assertEqual(len(app.exception), 0)
        headers = " ".join(node.value for node in app.subheader)
        self.assertIn("Grafik holder", headers)
        self.assertEqual(_first_metric(app, "Dust hold % MC"), "0.42%")
        self.assertEqual(_first_metric(app, "Dust wallet"), "95")
        # Token Robinhood tampil sebagai pilihan yang sedang aktif, bukan
        # peringatan "belum ada token".
        self.assertNotIn("Belum ada token", " ".join(
            node.value for node in app.info))

@unittest.skipUnless(AppTest is not None, "streamlit is not installed")
class HolderPageShortScanTest(unittest.TestCase):
    """Snapshot cron dari scan holder **tidak lengkap** tidak boleh jadi angka.

    Kasus produksi 2026-09-06: Helius mati → fallback GMGN mengembalikan 20
    holder (``truncated: False``) → ``dust 0`` / ``0,00% MC``. Kartu metrik
    halaman ini membaca snapshot, jadi tanpa guard ia menyajikan "dust habis"
    yang tidak pernah terjadi.
    """

    SHORT = {"dust_count": 0, "dust_pct_mc": 0.0, "real_count": 19,
             "wallets_analyzed": 19, "total_fetched": 20, "source": "gmgn"}

    @contextlib.contextmanager
    def _page(self, status):
        patches = [
            mock.patch("watchlist.load_watchlist",
                       return_value={MINT: META}),
            mock.patch("holder_status.load_holder_status",
                       return_value=status),
            mock.patch("holder_history.load_holder_history",
                       return_value=_store()),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
            mock.patch("core.get_helius_keys", return_value=["test-key"]),
        ]
        for patch in patches:
            patch.start()
        try:
            app = AppTest.from_file(PAGE, default_timeout=30)
            app.run()
            yield app
        finally:
            for patch in reversed(patches):
                patch.stop()

    def test_short_scan_falls_back_to_history_and_warns(self):
        status = {"updated_at": 12 * HOUR,
                  "tokens": {MINT: {"symbol": "TST", "analyzed_at": 12 * HOUR,
                                    "holders": dict(self.SHORT)}}}
        with self._page(status) as app:
            self.assertEqual(len(app.exception), 0)
            warnings = " ".join(node.value for node in app.warning)
            self.assertIn("tidak lengkap", warnings)
            self.assertIn("19 wallet", warnings)
            # angka memakai titik history layak terakhir (120 dust / 0,80%),
            # bukan 0 dari sampel 20 wallet.
            self.assertEqual(_first_metric(app, "Dust wallet"), "120")
            self.assertEqual(_first_metric(app, "Dust hold % MC"), "0.80%")

    def test_complete_scan_still_uses_the_snapshot(self):
        status = {"updated_at": 16 * HOUR,
                  "tokens": {MINT: {"symbol": "TST", "analyzed_at": 16 * HOUR,
                                    "holders": {
                                        "dust_count": 130,
                                        "dust_pct_mc": 0.9,
                                        "real_count": 41,
                                        "wallets_analyzed": 171,
                                        "total_fetched": 4_300}}}}
        with self._page(status) as app:
            self.assertEqual(len(app.exception), 0)
            self.assertNotIn("tidak lengkap",
                             " ".join(node.value for node in app.warning))
            self.assertEqual(_first_metric(app, "Dust wallet"), "130")
            self.assertEqual(_first_metric(app, "Dust hold % MC"), "0.90%")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
