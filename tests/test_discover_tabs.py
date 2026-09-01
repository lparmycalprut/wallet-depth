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
            mock.patch("silent_status.load_silent_status",
                       return_value={"updated_at": None, "tokens": {}}),
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

    def _body(self, app):
        return "\n".join(block.value for block in app.markdown)

    def test_default_tab_is_trending(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, TREND_TAB)
        self.assertIn("Scan Trending", self._scan_button(app).label)

    def test_scan_degen_keeps_the_degen_tab_active(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.segmented_control[0].set_value(DEGEN_TAB).run()
        self.assertIn("Scan Degen", self._scan_button(app, "Scan Degen").label)

        self._scan_button(app, "Scan Degen").click().run()

        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, DEGEN_TAB)
        self.assertEqual(app.session_state["discover_tab_active"], DEGEN_TAB)
        self.assertIn("Scan Degen", self._scan_button(app, "Scan Degen").label)
        self.assertIn("$DGN", self._body(app))
        self.assertNotIn("$TRD", self._body(app))

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
