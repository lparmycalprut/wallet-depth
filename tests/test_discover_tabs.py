"""The Trending/Degen switcher must survive the rerun caused by a scan.

``st.tabs`` always re-renders on the first tab after a rerun, so clicking
"Scan Degen" used to throw the user back to Trending. The switcher is now a
stateful segmented control whose selection lives in session state.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    import trending_ui
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    trending_ui = None
    AppTest = None

APP = str(Path(__file__).resolve().parent.parent / "app.py")

TREND_TAB = "📈 Trending"
DEGEN_TAB = "🔥 Degen"

DEGEN_ROW = {"ca": "DegenMint1111", "symbol": "DGN", "mc": 120_000,
             "liq": 30_000, "volume": 90_000, "change_24h": 42.0}
TREND_ROW = {"ca": "TrendMint1111", "symbol": "TRD", "mc": 500_000,
             "liq": 80_000, "volume": 250_000, "change_24h": 12.0}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class DiscoverTabPersistenceTest(unittest.TestCase):
    def setUp(self):
        patches = (
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            # Backup durable store: tes tidak boleh menyentuh jaringan.
            mock.patch("holder_history.pull_holder_history", return_value=None),
            # trending_ui binds the screeners at import time.
            mock.patch("trending_ui.screen", return_value=[TREND_ROW]),
            mock.patch("trending_ui.screen_trending_h1", return_value=[]),
            mock.patch("trending_ui.screen_hrhr", return_value=[DEGEN_ROW]),
            mock.patch("trending_ui.screen_hrhr_h1", return_value=[]),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    @staticmethod
    def _scan_button(app, expected="Scan Trending"):
        return [button for button in app.button
                if expected in (button.label or "")][0]

    @staticmethod
    def _add_all_button(app):
        return [button for button in app.button
                if "Add All to Watchlist" in (button.label or "")][0]

    def _body(self, app):
        return "\n".join(block.value for block in app.markdown)

    def test_default_tab_is_trending(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, TREND_TAB)
        self.assertIn("Scan Trending", self._scan_button(app).label)
        self.assertTrue(any("Add All to Watchlist" in (button.label or "")
                            for button in app.button))

    def test_scan_degen_keeps_the_degen_tab_active(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.segmented_control[0].set_value(DEGEN_TAB).run()
        self.assertIn("Scan Degen", self._scan_button(app, "Scan Degen").label)
        self.assertTrue(any("Add All to Watchlist" in (button.label or "")
                            for button in app.button))

        self._scan_button(app, "Scan Degen").click().run()

        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, DEGEN_TAB)
        self.assertEqual(app.session_state["discover_tab_active"], DEGEN_TAB)
        self.assertIn("Scan Degen", self._scan_button(app, "Scan Degen").label)
        self.assertIn("$DGN", self._body(app))
        self.assertNotIn("$TRD", self._body(app))

    def test_add_all_empty_scan_shows_feedback_without_model_write(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        with mock.patch("trending_ui.add_many_to_watchlist") as add_many:
            self._add_all_button(app).click().run()
        add_many.assert_not_called()
        self.assertTrue(any("Hasil scan kosong" in node.value
                            for node in app.info))

    def test_add_all_uses_trending_source_and_shows_count_feedback(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        self._scan_button(app).click().run()
        result = {"added": 1, "skipped": 0, "duplicates": 0,
                  "invalid": 0, "saved": True, "addresses": ["TrendMint1111"]}
        with mock.patch("trending_ui.add_many_to_watchlist",
                        return_value=result) as add_many:
            self._add_all_button(app).click().run()
        add_many.assert_called_once()
        self.assertEqual(add_many.call_args.kwargs["source"], "trending")
        self.assertTrue(any("1 token berhasil ditambahkan" in node.value
                            for node in app.success))

    def test_add_all_uses_degen_source(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.segmented_control[0].set_value(DEGEN_TAB).run()
        self._scan_button(app, "Scan Degen").click().run()
        result = {"added": 1, "skipped": 0, "duplicates": 0,
                  "invalid": 0, "saved": True, "addresses": ["DegenMint1111"]}
        with mock.patch("trending_ui.add_many_to_watchlist",
                        return_value=result) as add_many:
            self._add_all_button(app).click().run()
        add_many.assert_called_once()
        self.assertEqual(add_many.call_args.kwargs["source"], "degen")

    def test_deselecting_keeps_the_last_active_tab(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.segmented_control[0].set_value(DEGEN_TAB).run()
        # Clicking the active pill again clears the widget value.
        app.segmented_control[0].set_value(None).run()

        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["discover_tab_active"], DEGEN_TAB)
        self.assertIn("Scan Degen", self._scan_button(app, "Scan Degen").label)

    def test_scan_trending_stays_on_trending(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        self._scan_button(app, "Scan Trending").click().run()

        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, TREND_TAB)
        self.assertIn("$TRD", self._body(app))
        self.assertNotIn("$DGN", self._body(app))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
