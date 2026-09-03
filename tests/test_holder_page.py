"""Streamlit AppTest untuk halaman Holder Analytic.

Fokus: grafik holder baru (jumlah holder + komposisi bucket + distribusi
scan FULL) dan tombol scan manual yang wajib **FULL** serta menyimpan
detail baseline (``detail=True``) — cron tetap hanya mencatat perubahan.
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

import holder_history as hh

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "5_🧮_Holder.py")
MINT = "So11111111111111111111111111111111111111112"
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
    return {
        "updated_at": 12 * HOUR,
        "tokens": {
            MINT: {
                "symbol": "TST",
                "cohort": {"frozen_at": 4 * HOUR, "balances": {"A": 10.0}},
                "baseline": detail,
                "latest_detail": {**detail, "ts": 12 * HOUR,
                                  "depth": {**detail["depth"],
                                            "buckets": _buckets(120)}},
                "points": [_point(4 * HOUR, 90), _point(8 * HOUR, 105),
                           _point(12 * HOUR, 120)],
            }
        },
    }


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


@unittest.skipUnless(AppTest is not None, "streamlit is not installed")
class HolderPageChartTest(unittest.TestCase):
    @contextlib.contextmanager
    def _page(self, analyze=None, ingest=None):
        """Jalankan halaman dengan semua dependensi jaringan di-mock."""
        patches = [
            mock.patch("watchlist.load_watchlist", return_value={MINT: META}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value=_store()),
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


if __name__ == "__main__":
    unittest.main()
