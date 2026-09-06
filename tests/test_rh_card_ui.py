# -*- coding: utf-8 -*-
"""AppTest: aksi Holder Analytic di card Watchlist Robinhood Chain.

Permintaan user 2026-09-05: setiap baris watchlist (Meteora maupun
Robinhood) punya tombol 🧮 yang membuka halaman Holder Analytic token itu,
dengan navigasi ``?mint=0x…`` yang dipahami halaman Holder (chain EVM).

Sejak 2026-09-06 aksinya tautan **tab baru** (``holder_analytic_link_html``),
bukan tombol ``st.switch_page``, supaya watchlist tidak ikut di-rerun. Tautan
itu wajib memakai **slug halaman** Streamlit (``/Holder``), bukan path file
(``pages/5_🧮_Holder.py``) — path file bukan route, jadi app jatuh ke
halaman utama dan token di URL tidak pernah dibaca. Ditambah dua jaminan:
target tautan = slug yang benar-benar dipakai Streamlit, dan router
``page_router`` memantulkan ``?mint=`` yang mendarat di halaman utama (tautan
lama yang sudah tersebar tetap berfungsi).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

from links import (HOLDER_PAGE_PATH, holder_analytic_url, page_url_path)

APP = str(Path(__file__).resolve().parent.parent / "app.py")

CA = "0x8490acd2d52d0ebd34cb13e01bd9a9380b36411d"
HOUR = 3600


def _point(ts: int, pct: float, count: int) -> dict:
    return {"ts": ts, "dust_count": count, "dust_pct_mc": pct,
            "price": 0.01, "mc": 100_000.0, "real_count": 40,
            "mid_count": 5, "holder_count": count + 40,
            "cohort_token_pct": 90.0, "cohort_n": 5}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class RobinhoodCardHolderButtonTest(unittest.TestCase):
    def _status(self, holders=None, history=None):
        return {
            "updated_at": 6 * HOUR,
            "tokens": {CA: {
                "symbol": "VLAD", "price": 0.01, "marketcap": 100_000.0,
                "analyzed_at": 6 * HOUR,
                "holders": {"dust_count": 70, "dust_pct_mc": 0.55,
                            "real_count": 40, "total_fetched": 110,
                            "mid": {"count": 5, "pct_mc": 4.0}}
                if holders is None else holders,
                "history": [_point(2 * HOUR, 0.30, 50),
                            _point(6 * HOUR, 0.55, 70)]
                if history is None else history,
                "cohort": {"frozen_at": 2 * HOUR, "balances": {}},
            }},
        }

    def _history_store(self, points=None):
        return {"updated_at": 6 * HOUR,
                "tokens": {CA: {"symbol": "VLAD", "cohort": {},
                                "points": [_point(2 * HOUR, 0.30, 50),
                                           _point(6 * HOUR, 0.55, 70)]
                                if points is None else points}}}

    def _app(self, query_params=None, *, status=None, history_store=None):
        patches = (
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value={"tokens": {}}),
            # Backup durable store: tes tidak boleh menyentuh jaringan.
            mock.patch("holder_history.pull_holder_history", return_value=None),
            mock.patch("robinhood_watchlist.load_watchlist",
                       return_value={CA: {"symbol": "VLAD",
                                          "source": "manual"}}),
            mock.patch("robinhood_watchlist.load_status",
                       return_value=status or self._status()),
            mock.patch("robinhood_watchlist.load_history",
                       return_value=history_store or self._history_store()),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60)
        if query_params:
            app.query_params = dict(query_params)
        return app.run()

    def test_row_has_holder_analytic_link(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("Watchlist Robinhood LP", body)
        self.assertIn("$VLAD", body)
        # Aksi 🧮 = tautan tab baru ke SLUG halaman, bukan path file.
        self.assertIn(f'href="/Holder?mint={CA}"', body)
        self.assertIn('target="_blank"', body)
        self.assertNotIn("pages/5_🧮_Holder.py", body)
        keys = [button.key or "" for button in app.button]
        # tombol pindah card + hapus tetap ada di samping tautan holder
        self.assertIn(f"rh-move-{CA}", keys)
        self.assertIn(f"rh-remove-{CA}", keys)
        # token Solana kosong di test ini — tidak ada baris holder biasa
        self.assertFalse(any(k.startswith("holder-") for k in keys))

    def test_holder_link_targets_streamlit_page_slug(self):
        """Slug tautan harus sama dengan yang diberikan Streamlit ke file-nya.

        Streamlit mencocokkan URL dengan ``pathname.endsWith('/' + urlPathname)``
        (case-sensitive); kalau slugnya meleset, tautan membuka dashboard,
        bukan Holder Analytic — persis bug yang membuat ``?mint=`` "belum
        berfungsi".
        """
        url = holder_analytic_url(CA)
        self.assertEqual(url, f"/Holder?mint={CA}")
        self.assertTrue(url.startswith("/"))
        self.assertNotIn("pages/", url)
        try:
            from streamlit.source_util import page_icon_and_name
        except Exception:  # pragma: no cover - streamlit selalu ada di suite ini
            self.skipTest("streamlit tidak tersedia")
        real_slug = page_icon_and_name(Path(HOLDER_PAGE_PATH))[1]
        self.assertEqual(page_url_path(HOLDER_PAGE_PATH), real_slug)
        self.assertEqual(url.split("?", 1)[0], f"/{real_slug}")

    def test_main_page_routes_mint_query_to_holder(self):
        """Tautan lama (``pages/5_…py?mint=…``) mendarat di halaman utama.

        Halaman utama harus memantulkannya ke Holder Analytic dengan mint yang
        sama — bukan menampilkan dashboard kosong seperti sebelumnya.
        """
        with mock.patch("streamlit.switch_page") as switch:
            app = self._app(query_params={"mint": [CA]})
        self.assertEqual(len(app.exception), 0)
        switch.assert_called_once_with(
            HOLDER_PAGE_PATH, query_params={"mint": CA})
        # penanda sesi: deep link yang sama tidak dipantulkan berulang
        self.assertEqual(app.session_state["_deep_link_routed"],
                         (HOLDER_PAGE_PATH, CA))

    def test_incomplete_scan_is_not_presented_as_result(self):
        """Scan RH yang pulang dengan 0 wallet harus bilang begitu di barisnya."""
        broken = {"dust_count": 0, "dust_pct_mc": 0.0, "real_count": 0,
                  "total_fetched": 0,
                  "fetch_error": "Blockscout getToken: 429 Too Many Requests"}
        app = self._app(status=self._status(holders=broken, history=[]),
                        history_store=self._history_store(points=[]))
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("⚠️ scan terakhir tidak lengkap", body)
        self.assertIn("429 Too Many Requests", body)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class RobinhoodPublishGuardTest(unittest.TestCase):
    """``publish_scan`` tidak menulis scan tidak layak ke snapshot dashboard."""

    def test_unusable_analysis_skipped_from_status(self):
        import robinhood_watchlist as rw

        broken = {"holders": {"total_fetched": 0, "wallets_analyzed": 0,
                              "dust_count": 0, "dust_pct_mc": 0.0}}
        good = {"holders": {"total_fetched": 300, "wallets_analyzed": 300,
                            "dust_count": 12, "dust_pct_mc": 0.7}}
        published = {}

        def fake_publish(analyses, *args, **kwargs):
            published["mint"] = dict(analyses)
            return {"updated_at": 1, "tokens": {}}

        store = {"updated_at": 0, "tokens": {}}
        with mock.patch.object(rw, "ingest_many", return_value=store), \
                mock.patch.object(rw, "publish_holder_status",
                                  side_effect=fake_publish):
            rw.publish_scan({"broken": broken, "good": good}, {},
                            history_store=store)
        self.assertIn("good", published["mint"])
        self.assertNotIn("broken", published["mint"])

    def test_all_can_be_published_when_usable(self):
        import robinhood_watchlist as rw

        good = {"holders": {"total_fetched": 300, "wallets_analyzed": 300,
                            "dust_count": 12, "dust_pct_mc": 0.7}}
        with mock.patch.object(rw, "ingest_many",
                                return_value={"tokens": {}}), \
                mock.patch.object(rw, "publish_holder_status",
                                  return_value={}) as publish:
            rw.publish_scan({"a": good}, {}, history_store={"tokens": {}})
        self.assertIn("a", publish.call_args[0][0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
