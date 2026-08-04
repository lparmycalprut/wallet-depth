# -*- coding: utf-8 -*-
"""Tests for memecoin_scanner module.

No network calls — tests use mocks and verify message building,
state persistence, and scan logic.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memecoin_scanner as ms


class TestBuildSummaryMessage(unittest.TestCase):
    """Test the Telegram message builder."""

    def test_empty_results(self):
        """No notable results → empty message."""
        msg = ms.build_summary_message([], "12:00")
        self.assertEqual(msg, "")

    def test_no_notable(self):
        """All tokens have no alerts → empty message."""
        results = [
            {"ca": "abc123", "symbol": "TEST", "price": 0.001,
             "chg1": 0, "chg6": 0, "chg24": 0, "mc": 10000,
             "has_urgent": False, "has_notable": False, "alerts": []},
        ]
        msg = ms.build_summary_message(results, "12:00")
        self.assertEqual(msg, "")

    def test_with_urgent_token(self):
        """Urgent token (signal) → message includes it."""
        results = [
            {"ca": "abc123def456", "symbol": "PEPE", "price": 0.00001,
             "chg1": 20, "chg6": 30, "chg24": 50, "mc": 500000,
             "vol24": 100000, "liq": 50000,
             "conviction": 70, "conv_trend": "rising", "net_pure": 50,
             "has_urgent": True, "has_notable": True,
             "alerts": ["1h +20.0% 🚨", "💎 accumulation"]},
        ]
        msg = ms.build_summary_message(results, "12:00")
        self.assertIn("MEMECOIN SCANNER", msg)
        self.assertIn("PEPE", msg)
        self.assertIn("12:00", msg)
        self.assertIn("accumulation", msg)

    def test_quiet_message(self):
        """All quiet → minimal message."""
        msg = ms.build_quiet_message(10, "12:00")
        self.assertIn("MEMECOIN SCANNER", msg)
        self.assertIn("10", msg)
        self.assertIn("no notable", msg)

    def test_sorting_urgent_first(self):
        """Urgent tokens appear before notable ones."""
        results = [
            {"ca": "aaa", "symbol": "NOTABLE", "price": 0.01,
             "chg1": 5, "chg6": 0, "chg24": 0, "mc": 100000,
             "has_urgent": False, "has_notable": True,
             "alerts": ["6h +25.0% ⚠️"]},
            {"ca": "bbb", "symbol": "URGENT", "price": 0.01,
             "chg1": 20, "chg6": 0, "chg24": 0, "mc": 200000,
             "has_urgent": True, "has_notable": True,
             "alerts": ["1h +20.0% 🚨"]},
        ]
        msg = ms.build_summary_message(results, "12:00")
        # URGENT should appear before NOTABLE
        pos_urgent = msg.find("URGENT")
        pos_notable = msg.find("NOTABLE")
        self.assertLess(pos_urgent, pos_notable)


class TestState(unittest.TestCase):
    """Test state persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_state_path = ms.STATE_PATH
        ms.STATE_PATH = os.path.join(self.tmpdir, "scanner_state.json")

    def tearDown(self):
        ms.STATE_PATH = self.orig_state_path
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_empty(self):
        """Load state when file doesn't exist → empty dict."""
        state = ms.load_state()
        self.assertEqual(state, {})

    def test_save_and_load(self):
        """Save state and load it back."""
        state = {"last_sent_ts": 1234567890, "cycle_count": 3}
        ms.save_state(state)
        loaded = ms.load_state()
        self.assertEqual(loaded["last_sent_ts"], 1234567890)
        self.assertEqual(loaded["cycle_count"], 3)


class TestScanToken(unittest.TestCase):
    """Test individual token scanning logic."""

    def test_price_alert_thresholds(self):
        """Price change alerts fire at correct thresholds."""
        meta = {"symbol": "TEST"}
        # High 1h change → urgent
        market = {"price": 0.001, "chg1": 20, "chg6": 30, "chg24": 50,
                  "mc": 100000, "vol24": 50000, "liq": 10000,
                  "symbol": "TEST"}
        result = ms.scan_token("test_ca", meta, market)
        self.assertTrue(result["has_urgent"])
        self.assertIn("1h +20.0% 🚨", result["alerts"])

    def test_no_alert_small_changes(self):
        """Small price changes don't trigger alerts."""
        meta = {"symbol": "TEST"}
        market = {"price": 0.001, "chg1": 2, "chg6": 5, "chg24": 10,
                  "mc": 100000, "vol24": 50000, "liq": 10000,
                  "symbol": "TEST"}
        result = ms.scan_token("test_ca", meta, market)
        # Small changes → not notable unless conviction/holder alerts
        self.assertFalse(result["has_urgent"])

    def test_large_24h_change(self):
        """Large 24h change triggers fire emoji alert."""
        meta = {"symbol": "TEST"}
        market = {"price": 0.001, "chg1": 2, "chg6": 10, "chg24": 55,
                  "mc": 100000, "vol24": 50000, "liq": 10000,
                  "symbol": "TEST"}
        result = ms.scan_token("test_ca", meta, market)
        self.assertTrue(result["has_notable"])
        self.assertIn("24h +55.0% 🔥", result["alerts"])


class TestTelegram(unittest.TestCase):
    """Test Telegram credential loading."""

    def test_no_credentials_returns_false(self):
        """Without credentials, send returns False."""
        # Ensure no env vars
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            os.environ.pop(key, None)
        result = ms.send_telegram("test message")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
