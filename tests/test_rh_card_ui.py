# -*- coding: utf-8 -*-
"""AppTest: tombol Holder Analytic di card Watchlist Robinhood Chain.

Permintaan user 2026-09-05: setiap baris watchlist (Meteora maupun
Robinhood) punya tombol 🧮 yang membuka halaman Holder Analytic token itu.
Card Chart LP (Meteora) sudah memilikinya; card Robinhood baru diberi tombol
di sini + navigasi ``?mint=0x…`` yang dipahami halaman Holder (chain EVM).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

from links import HOLDER_PAGE_PATH

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
    def _status(self):
        history = [_point(2 * HOUR, 0.30, 50), _point(6 * HOUR, 0.55, 70)]
        return {
            "updated_at": 6 * HOUR,
            "tokens": {CA: {
                "symbol": "VLAD", "price": 0.01, "marketcap": 100_000.0,
                "analyzed_at": 6 * HOUR,
                "holders": {"dust_count": 70, "dust_pct_mc": 0.55,
                            "real_count": 40, "total_fetched": 110,
                            "mid": {"count": 5, "pct_mc": 4.0}},
                "history": history,
                "cohort": {"frozen_at": 2 * HOUR, "balances": {}},
            }},
        }

    def _history_store(self):
        return {"updated_at": 6 * HOUR,
                "tokens": {CA: {"symbol": "VLAD", "cohort": {},
                                "points": [_point(2 * HOUR, 0.30, 50),
                                           _point(6 * HOUR, 0.55, 70)]}}}

    def _app(self):
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
                       return_value=self._status()),
            mock.patch("robinhood_watchlist.load_history",
                       return_value=self._history_store()),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=60).run()

    def test_row_has_holder_analytic_button(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("Watchlist Robinhood LP", body)
        self.assertIn("$VLAD", body)
        keys = [button.key or "" for button in app.button]
        self.assertIn(f"rh-holder-{CA}", keys)
        # tombol hapus tetap ada di kolom setelah tombol holder
        self.assertIn(f"rh-remove-{CA}", keys)
        # token Solana kosong di test ini — tidak ada baris holder biasa
        self.assertFalse(any(k.startswith("holder-") for k in keys))

    def test_holder_button_navigates_with_evm_mint(self):
        app = self._app()
        with mock.patch("streamlit.switch_page") as switch:
            buttons = [b for b in app.button if b.key == f"rh-holder-{CA}"]
            self.assertTrue(buttons)
            buttons[0].click().run()
        self.assertEqual(len(app.exception), 0)
        switch.assert_called_once_with(
            HOLDER_PAGE_PATH, query_params={"mint": CA})
        self.assertEqual(app.session_state["holder_mint"], CA)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
