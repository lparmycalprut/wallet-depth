"""Tombol on/off notif Telegram untuk watchlist biasa (2026-09-06)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import alert_settings
from telegram_alerts import process_holder_alerts


def _analysis(pct: float, ts: int = 1000) -> dict:
    return {
        "symbol": "AA",
        "analyzed_at": ts,
        "holders": {
            "total_fetched": 500,
            "dust_pct_mc": pct,
            "wallet_snapshot": {"ts": ts, "dust_pct_mc": pct},
        },
    }


class SettingsStoreTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        patch = mock.patch.object(
            alert_settings, "SETTINGS_PATH",
            os.path.join(self._dir.name, "alert_settings.json"))
        patch.start()
        self.addCleanup(patch.stop)
        alert_settings.reset_cache()
        self.addCleanup(alert_settings.reset_cache)

    def test_default_enabled_when_nothing_stored(self):
        with mock.patch.object(alert_settings, "_read_remote",
                               return_value=None):
            self.assertTrue(alert_settings.regular_telegram_enabled(True))

    def test_save_then_read_local(self):
        with mock.patch.object(alert_settings, "_read_remote",
                               return_value=None):
            ok = alert_settings.save_settings(
                {alert_settings.KEY_REGULAR_TELEGRAM: False}, push=False)
            self.assertTrue(ok)
            alert_settings.reset_cache()
            self.assertFalse(alert_settings.regular_telegram_enabled(True))
        with open(alert_settings.SETTINGS_PATH, encoding="utf-8") as handle:
            self.assertFalse(json.load(handle)[
                alert_settings.KEY_REGULAR_TELEGRAM])

    def test_remote_wins_over_local(self):
        alert_settings.save_settings(
            {alert_settings.KEY_REGULAR_TELEGRAM: False}, push=False)
        alert_settings.reset_cache()
        with mock.patch.object(
                alert_settings, "_read_remote",
                return_value={alert_settings.KEY_REGULAR_TELEGRAM: True}):
            self.assertTrue(alert_settings.regular_telegram_enabled(True))

    def test_broken_remote_falls_back_without_muting(self):
        with mock.patch.object(alert_settings, "_read_remote",
                               side_effect=None, return_value=None):
            alert_settings.reset_cache()
            self.assertTrue(alert_settings.regular_telegram_enabled(True))


class MuteMintsTest(unittest.TestCase):
    """``mute_mints`` menahan kiriman tapi tetap memajukan state."""

    def _run(self, muted):
        store = {"tokens": {"MINT": {
            "symbol": "AA",
            "alert_state": {
                "high_drop": {"ts": 100, "high": 2.0, "high_ts": 100,
                              "notified_high": 0.0},
            },
        }}}
        sent = []

        def sender(event):
            sent.append(event)
            return {"ok": True, "skipped": False}

        deliveries = process_holder_alerts(
            {"MINT": _analysis(0.5)}, store, sender=sender,
            high_mints={"MINT"}, mute_mints=muted)
        state = store["tokens"]["MINT"]["alert_state"]
        return sent, deliveries, state

    def test_sends_when_not_muted(self):
        sent, deliveries, state = self._run(set())
        self.assertEqual(len(sent), 1)
        self.assertTrue(deliveries[0]["delivery"]["ok"])
        self.assertEqual(state["high_drop"]["notified_high"], 2.0)

    def test_muted_skips_send_but_keeps_marker(self):
        sent, deliveries, state = self._run({"MINT"})
        self.assertEqual(sent, [])
        self.assertEqual(len(deliveries), 1)
        self.assertTrue(deliveries[0]["delivery"]["muted"])
        self.assertTrue(deliveries[0]["delivery"]["skipped"])
        # Marker tetap maju: menyalakan notif lagi tidak membanjiri user
        # dengan alert titik high yang sudah lewat.
        self.assertEqual(state["high_drop"]["high"], 2.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
