"""Streamlit AppTest coverage for the CVD page backtest history.

These tests verify the two fetch entry points on ``pages/4_📊_CVD.py``:

* the explicit "🔍 Fetch rentang ini" button targets the selected date range
  (``start_date``/``end_date``) instead of a last-N-days lookback, and
* auto-fetch still fires when the user changes the start date / days-forward.

Streamlit is an optional dev dependency; the whole module is skipped when it
is not installed so ``python -m unittest discover tests`` still passes with a
minimal environment.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:  # optional dev dependency — the page itself needs it at runtime
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "4_📊_CVD.py")
MINT = "Mint123"
META = {"symbol": "TST"}

# The page derives "today" from MARKET_TZ (UTC); mirror that here so the
# expected default range matches whatever date the test actually runs on.
TODAY = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)
DEFAULT_START = YESTERDAY - timedelta(days=6)


def _fake_result(mint=MINT, *, ok=True, error=None):
    """Build the same structured dict ``refresh_single_token`` returns."""
    return {
        "mint": mint, "symbol": "TST", "ok": ok, "error": error,
        "source": "gmgn" if ok else None, "fallback": False,
        "trades_count": 3 if ok else 0, "rows_created": 0,
        "rows_updated": 0, "duration_ms": 1, "requested_days": 7,
        "start_date": "2026-08-08", "end_date": "2026-08-14",
        "log": [{"ts_market": "2026-08-15 00:00:01", "stage": "success",
                 "message": "fetch manual berhasil", "ok": True}],
    }


def _patches(refresh_side_effect, daily_rows):
    """Patch the page's external dependencies so no network or disk I/O runs."""
    return (
        mock.patch("watchlist.load_watchlist",
                   return_value={MINT: META}),
        mock.patch("scripts.update_cvd.refresh_single_token",
                   side_effect=refresh_side_effect),
        mock.patch("effort_detector.load_daily_effort",
                   return_value=daily_rows or []),
        mock.patch("core.get_helius_keys", return_value=["test-key"]),
    )


@unittest.skipUnless(AppTest is not None, "streamlit is not installed")
class CvdPageBacktestTest(unittest.TestCase):
    def test_first_load_does_not_fetch_and_prompts(self):
        calls = []

        def fake(mint, meta=None, **kwargs):
            calls.append(kwargs)
            return _fake_result(mint=mint)

        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("scripts.update_cvd.refresh_single_token",
                        side_effect=fake), \
             mock.patch("effort_detector.load_daily_effort",
                        return_value=[]), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(len(calls), 0)
            self.assertTrue(any("Fetch rentang ini" in info.value
                                for info in at.info))

    def test_range_button_fetches_selected_range_not_lookback(self):
        calls = []

        def fake(mint, meta=None, **kwargs):
            calls.append(kwargs)
            return _fake_result(mint=mint)

        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("scripts.update_cvd.refresh_single_token",
                        side_effect=fake), \
             mock.patch("effort_detector.load_daily_effort",
                        return_value=[]), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            at.button(key="bt_fetch_range").click().run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("start_date", calls[0])
            self.assertIn("end_date", calls[0])
            self.assertNotIn("lookback_days", calls[0])
            self.assertEqual(calls[0]["start_date"], DEFAULT_START)
            self.assertEqual(calls[0]["end_date"], YESTERDAY)
            self.assertTrue(any("Fetch berhasil" in info.value
                                for info in at.info))

    def test_auto_fetch_fires_when_range_changes(self):
        calls = []

        def fake(mint, meta=None, **kwargs):
            calls.append(kwargs)
            return _fake_result(mint=mint)

        new_start = YESTERDAY - timedelta(days=10)
        new_end = new_start + timedelta(days=6)
        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("scripts.update_cvd.refresh_single_token",
                        side_effect=fake), \
             mock.patch("effort_detector.load_daily_effort",
                        return_value=[]), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            self.assertEqual(len(calls), 0)
            at.date_input[0].set_value(new_start).run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["start_date"], new_start)
            self.assertEqual(calls[0]["end_date"], new_end)

    def test_failed_fetch_shows_error_not_silent(self):
        def fake(mint, meta=None, **kwargs):
            return _fake_result(mint=mint, ok=False,
                                error="pair market tidak ditemukan")

        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("scripts.update_cvd.refresh_single_token",
                        side_effect=fake), \
             mock.patch("effort_detector.load_daily_effort",
                        return_value=[]), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            at.button(key="bt_fetch_range").click().run()
            self.assertEqual(len(at.exception), 0)
            joined = " ".join(error.value for error in at.error)
            self.assertIn("Fetch gagal", joined)
            self.assertIn("pair market tidak ditemukan", joined)

    def test_data_present_renders_metrics_and_table(self):
        def make(date):
            return {"mint": MINT, "date": date, "open": 100.0,
                    "close": 110.0, "price_chg_pct": 10.0, "cvd_delta": 5.0,
                    "direction": "up", "ratio": 0.5}

        rows = [make((YESTERDAY - timedelta(days=1)).isoformat()),
                make(YESTERDAY.isoformat())]
        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("scripts.update_cvd.refresh_single_token"), \
             mock.patch("effort_detector.load_daily_effort",
                        return_value=rows), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            self.assertEqual(len(at.exception), 0)
            self.assertGreater(len(at.metric), 0)
            self.assertGreater(len(at.dataframe), 0)

    def test_manual_panel_button_still_uses_lookback(self):
        calls = []

        def fake(mint, meta=None, **kwargs):
            calls.append(kwargs)
            return _fake_result(mint=mint)

        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("scripts.update_cvd.refresh_single_token",
                        side_effect=fake), \
             mock.patch("effort_detector.load_daily_effort",
                        return_value=[]), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            manual = at.button[0]  # "Fetch sekarang" (no key) in manual panel
            self.assertIn("Fetch", manual.label)
            manual.click().run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("lookback_days", calls[0])
            self.assertNotIn("start_date", calls[0])
            self.assertNotIn("end_date", calls[0])


if __name__ == "__main__":
    unittest.main()
