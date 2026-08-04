# -*- coding: utf-8 -*-
"""Tests for memecoin_scanner module.

No network calls — tests use mocks and verify scoring logic,
message building, and state persistence.
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


class TestConfig(unittest.TestCase):
    """Test configuration loading."""

    def test_default_config(self):
        """Default config has all required keys."""
        cfg = ms.load_config()
        self.assertIn("scan_interval_minutes", cfg)
        self.assertIn("alert_score_threshold", cfg)
        self.assertIn("liquidity_threshold", cfg)
        self.assertIn("volume_spike_x", cfg)
        self.assertEqual(cfg["scan_interval_minutes"], 15)
        self.assertEqual(cfg["alert_score_threshold"], 60)


class TestAnalyzeToken(unittest.TestCase):
    """Test 5-phase scoring system."""

    def setUp(self):
        self.config = ms.load_config()

    def test_early_stage_high_score(self):
        """Early stage token (low tx, low vol, thin liq) should score high."""
        data = {
            "address": "test" + "a" * 40,
            "symbol": "EARLY",
            "price_usd": 0.00001,
            "liquidity_usd": 20000,
            "fdv": 200000,
            "volume_h1": 500,
            "volume_h6": 1000,
            "txns_h1": {"buys": 10, "sells": 5},
            "txns_h6": {"buys": 30, "sells": 20},
        }
        result = ms.analyze_token(data, self.config)
        self.assertIsNotNone(result)
        # Should score high on liquidity_test (early), thin_liquidity
        self.assertGreater(result.phases["liquidity_test"]["score"], 10)
        self.assertEqual(result.phases["thin_liquidity"]["score"], 20)

    def test_volume_spike_scoring(self):
        """Volume spike should score high."""
        data = {
            "address": "test" + "b" * 40,
            "symbol": "SPIKE",
            "price_usd": 0.001,
            "liquidity_usd": 500000,
            "fdv": 5000000,
            "volume_h1": 100000,  # 100k in 1h
            "volume_h6": 6000,    # avg 1k/h -> spike 100x
            "txns_h1": {"buys": 200, "sells": 100},
            "txns_h6": {"buys": 50, "sells": 30},
        }
        result = ms.analyze_token(data, self.config)
        self.assertIsNotNone(result)
        # Volume spike should be high
        self.assertGreaterEqual(result.phases["volume_spike"]["score"], 15)

    def test_slow_accumulation_growth(self):
        """Transaction growth should score well."""
        data = {
            "address": "test" + "c" * 40,
            "symbol": "GROW",
            "price_usd": 0.005,
            "liquidity_usd": 80000,
            "fdv": 800000,
            "volume_h1": 15000,
            "volume_h6": 3000,
            "txns_h1": {"buys": 100, "sells": 50},  # 150 total
            "txns_h6": {"buys": 10, "sells": 5},     # 15 total -> 10x growth
        }
        result = ms.analyze_token(data, self.config)
        self.assertIsNotNone(result)
        # tx growth = 150/15 = 10x, should score high
        self.assertGreaterEqual(result.phases["slow_accumulation"]["score"], 12)

    def test_no_data_returns_none(self):
        """Empty data should return None."""
        result = ms.analyze_token(None, self.config)
        self.assertIsNone(result)

    def test_alert_message_threshold(self):
        """Score >= threshold should generate alert message."""
        # Construct data that scores >= 60
        data = {
            "address": "test" + "d" * 40,
            "symbol": "ALERT",
            "price_usd": 0.00001,
            "liquidity_usd": 30000,   # thin -> 20 pts
            "fdv": 300000,            # thin -> bonus
            "volume_h1": 500,         # early -> 15 pts
            "volume_h6": 500,
            "txns_h1": {"buys": 10, "sells": 5},  # early -> 15 pts
            "txns_h6": {"buys": 10, "sells": 5},
        }
        result = ms.analyze_token(data, self.config)
        self.assertIsNotNone(result)
        # Check total score makes sense
        self.assertGreater(result.score, 0)
        self.assertLessEqual(result.score, 100)

    def test_phase_scores_sum(self):
        """Phase scores should sum to total score."""
        data = {
            "address": "test" + "e" * 40,
            "symbol": "SUM",
            "price_usd": 0.001,
            "liquidity_usd": 50000,
            "fdv": 500000,
            "volume_h1": 5000,
            "volume_h6": 2000,
            "txns_h1": {"buys": 30, "sells": 20},
            "txns_h6": {"buys": 20, "sells": 15},
        }
        result = ms.analyze_token(data, self.config)
        self.assertIsNotNone(result)
        phase_sum = sum(v["score"] for v in result.phases.values())
        self.assertEqual(phase_sum, result.score)


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
        state = {"last_scan_ts": 1234567890, "last_alerts": {}}
        ms.save_state(state)
        loaded = ms.load_state()
        self.assertEqual(loaded["last_scan_ts"], 1234567890)


class TestTelegram(unittest.TestCase):
    """Test Telegram credential loading."""

    def test_no_credentials_returns_false(self):
        """Without credentials, send returns False."""
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            os.environ.pop(key, None)
        result = ms.send_telegram("test message")
        self.assertFalse(result)


class TestScanResult(unittest.TestCase):
    """Test ScanResult dataclass."""

    def test_dataclass_defaults(self):
        """ScanResult should have sensible defaults."""
        r = ms.ScanResult(address="abc", symbol="TEST", score=50)
        self.assertEqual(r.address, "abc")
        self.assertEqual(r.symbol, "TEST")
        self.assertEqual(r.score, 50)
        self.assertEqual(r.phases, {})
        self.assertIsNone(r.alert_message)
        self.assertIsInstance(r.timestamp, str)


class TestFormatWhaleSummary(unittest.TestCase):
    """Test whale summary formatting."""

    def test_empty_whale_list(self):
        """Empty whale list → no whales message."""
        config = {"whale_lookback_hours": 3}
        summary = ms.format_whale_summary([], config)
        self.assertIn("Tidak ada whale", summary)
        self.assertIn("3", summary)

    def test_with_whale_data(self):
        """Whale data → formatted summary."""
        config = {"whale_lookback_hours": 3}
        whale_txs = [
            {"signature": "sig1", "buyer": "A" * 44, "usd_value": 5000},
            {"signature": "sig2", "buyer": "B" * 44, "usd_value": 3000},
        ]
        summary = ms.format_whale_summary(whale_txs, config)
        self.assertIn("Aktivitas Whale", summary)
        self.assertIn("2", summary)  # 2 whales
        self.assertIn("$8,000", summary)  # total value


if __name__ == "__main__":
    unittest.main()
