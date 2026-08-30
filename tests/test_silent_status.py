"""Coverage snapshot silent-status (tanpa sinyal/Telegram)."""
from __future__ import annotations

import json
import tempfile
import unittest

import silent_status as ss


ANALYSIS = {
    "Mint123": {
        "symbol": "TST",
        "marketcap": 100_000,
        "price": 0.01,
        "analyzed_at": 1_800_000_000,
        "holders": {"real_count": 20, "dust_count": 150,
                    "dust_pct_mc": 0.5},
        "flow": {"net_usd": 250.0, "price_chg_pct": 1.0},
        "silent": {"silent": True, "strength": "sedang", "reason": "ok"},
    },
    "MintBad": {"symbol": "BAD", "marketcap": 0, "price": 0,
                "analyzed_at": None, "holders": {}, "flow": {},
                "silent": {}},
}


class SnapshotStatusTest(unittest.TestCase):
    def test_snapshot_is_compact(self):
        status = ss.snapshot_status(ANALYSIS, {"Mint123": {"symbol": "TST"}})
        self.assertEqual(status["scanner"], "silent-12h-v1")
        self.assertEqual(status["updated_at"], 1_800_000_000)
        self.assertIn("Mint123", status["tokens"])
        self.assertIn("MintBad", status["tokens"])
        token = status["tokens"]["Mint123"]
        self.assertEqual(token["holders"]["dust_count"], 150)
        self.assertEqual(token["silent"]["silent"], True)


class ParseStatusTest(unittest.TestCase):
    def test_accepts_payload_with_tokens(self):
        parsed = ss._parse_status_payload(
            {"updated_at": 1, "scanner": "x", "tokens": {}})
        self.assertIsNotNone(parsed)

    def test_rejects_other_shapes(self):
        self.assertIsNone(ss._parse_status_payload({"data": []}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
