"""Coverage snapshot holder-status."""
from __future__ import annotations

import json
import tempfile
import unittest

import holder_status as ss


ANALYSIS = {
    "Mint123": {
        "symbol": "TST",
        "marketcap": 100_000,
        "price": 0.01,
        "analyzed_at": 1_800_000_000,
        "holders": {"real_count": 20, "dust_count": 150,
                    "dust_pct_mc": 0.5},
    },
    "MintBad": {"symbol": "BAD", "marketcap": 0, "price": 0,
                "analyzed_at": None, "holders": {}},
}


class SnapshotStatusTest(unittest.TestCase):
    def test_snapshot_is_compact(self):
        status = ss.snapshot_status(ANALYSIS, {"Mint123": {"symbol": "TST"}})
        self.assertEqual(status["scanner"], "holder-dust-v1")
        self.assertEqual(status["updated_at"], 1_800_000_000)
        self.assertIn("Mint123", status["tokens"])
        self.assertIn("MintBad", status["tokens"])
        token = status["tokens"]["Mint123"]
        self.assertEqual(token["holders"]["dust_count"], 150)
        self.assertIn("history", token)
        self.assertNotIn("cohort_now", token["holders"])


class ParseStatusTest(unittest.TestCase):
    def test_accepts_payload_with_tokens(self):
        parsed = ss._parse_status_payload(
            {"updated_at": 1, "scanner": "x", "tokens": {}})
        self.assertIsNotNone(parsed)

    def test_rejects_other_shapes(self):
        self.assertIsNone(ss._parse_status_payload({"data": []}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
