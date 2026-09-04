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

    def test_alert_state_persists_but_transient_wallet_snapshot_is_removed(self):
        addr = "WalletAddr111111111111111111111111111111111"
        analyses = {"Mint123": dict(ANALYSIS["Mint123"])}
        analyses["Mint123"]["holders"] = {
            **ANALYSIS["Mint123"]["holders"],
            "wallet_snapshot": {"ts": 200, "dust_pct_mc": 0.5,
                                "balances": {addr: 2.0}, "dust": [addr]},
        }
        history = {"tokens": {"Mint123": {
            "alert_state": {
                "baseline": {"ts": 100, "dust_pct_mc": 0.2,
                             "balances": {addr: 1.0}, "dust": [addr],
                             "wallets_seen": 7},
                "rolling": {"ts": 200, "dust_pct_mc": 0.5,
                            "balances": {addr: 2.0}, "dust": [addr],
                            "wallets_seen": 9},
                "sent_event_ids": ["event-1"],
                "last_sent": {"dump": 199},
                "rejected_signals": [{"reason": "x"}],
            },
            "points": [], "cohort": {"frozen_at": 50, "balances": {addr: 3.0}},
        }}}
        token = ss.snapshot_status(
            analyses, history_store=history)["tokens"]["Mint123"]
        self.assertNotIn("wallet_snapshot", token["holders"])

        # alert_state di snapshot = RINGKASAN (jumlah + timestamp), bukan peta
        # wallet; state penuh ikut terbackup di holder_history.json.gz.
        state = token["alert_state"]
        self.assertTrue(state["summary"])
        self.assertEqual(state["sent_event_ids"], 1)
        self.assertEqual(state["rejected_signals"], 1)
        self.assertEqual(state["last_sent"], {"dump": 199})
        self.assertEqual(state["baseline"]["balances"], 1)
        self.assertEqual(state["baseline"]["dust"], 1)
        self.assertEqual(state["baseline"]["ts"], 100)
        self.assertEqual(state["baseline"]["dust_pct_mc"], 0.2)
        self.assertEqual(state["baseline"]["wallets_seen"], 7)
        self.assertEqual(state["rolling"]["balances"], 1)
        self.assertEqual(state["rolling"]["ts"], 200)

        # kohort juga ringkas: jumlah address, tanpa balance.
        self.assertEqual(token["cohort"], {"summary": True, "frozen_at": 50,
                                           "wallets": 1})

        # tidak ada address wallet yang bocor ke payload dashboard
        self.assertNotIn(addr, json.dumps(token))


class StatusSummaryHelperTest(unittest.TestCase):
    def test_cohort_summary(self):
        self.assertEqual(
            ss._cohort_for_status({"frozen_at": 7, "balances": {"A": 1.0,
                                                                 "B": 2.0}}),
            {"summary": True, "frozen_at": 7, "wallets": 2})
        self.assertEqual(ss._cohort_for_status(None),
                         {"summary": True, "frozen_at": None, "wallets": 0})
        self.assertEqual(ss._cohort_for_status({"balances": "rusak"}),
                         {"summary": True, "frozen_at": None, "wallets": 0})

    def test_chronology_summary_keeps_intervals_drops_wallet_maps(self):
        packed = {
            "baseline_wallets": {"ts": 1, "wallets": {"A": {"balance": 1.0}},
                                 "holder_count": 5},
            "latest_wallets": {"ts": 2, "wallets": {"A": {"balance": 2.0},
                                                    "B": {"balance": 3.0}}},
            "intervals": [{"from_ts": 1, "to_ts": 2}],
        }
        out = ss._chronology_for_status(packed)
        self.assertEqual(out["baseline_wallets"]["wallets"], 1)
        self.assertEqual(out["latest_wallets"]["wallets"], 2)
        self.assertEqual(out["baseline_wallets"]["holder_count"], 5)
        self.assertEqual(out["intervals"], [{"from_ts": 1, "to_ts": 2}])
        self.assertNotIn("A", json.dumps(out))

    def test_chronology_summary_tolerates_bad_input(self):
        self.assertEqual(ss._chronology_for_status(None), {"intervals": []})
        self.assertEqual(ss._chronology_for_status("x"), {"intervals": []})
        out = ss._chronology_for_status({"baseline_wallets": "rusak"})
        self.assertEqual(out["baseline_wallets"], "rusak")
        self.assertEqual(out["intervals"], [])


class ParseStatusTest(unittest.TestCase):
    def test_accepts_payload_with_tokens(self):
        parsed = ss._parse_status_payload(
            {"updated_at": 1, "scanner": "x", "tokens": {}})
        self.assertIsNotNone(parsed)

    def test_rejects_other_shapes(self):
        self.assertIsNone(ss._parse_status_payload({"data": []}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
