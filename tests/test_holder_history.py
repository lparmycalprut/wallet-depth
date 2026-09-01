"""Coverage dust flag, kohort mid-tier, resample 4 jam, sparkline."""
from __future__ import annotations

import os
import tempfile
import unittest

import holder_history as hh


def _h(addr, usd, balance=None, is_wallet=True):
    return {
        "address": addr, "usd_value": usd,
        "balance": usd if balance is None else balance,
        "is_wallet": is_wallet,
    }


class DustFlagTest(unittest.TestCase):
    def test_caution_at_one_percent(self):
        flag = hh.dust_flag(1.0)
        self.assertEqual(flag["level"], "caution")
        self.assertEqual(flag["label"], "HATI-HATI")
        self.assertFalse(flag["hide"])

    def test_limit_above_two_percent(self):
        flag = hh.dust_flag(2.01)
        self.assertEqual(flag["level"], "limit")
        self.assertTrue(flag["hide"])
        self.assertTrue(hh.should_hide_dust(2.01))
        self.assertFalse(hh.should_hide_dust(2.0))
        self.assertFalse(hh.should_hide_dust(1.5))

    def test_rising_compared_to_previous(self):
        flag = hh.dust_flag(1.4, 1.1)
        self.assertTrue(flag["rising"])
        self.assertFalse(hh.dust_flag(1.4, 1.4)["rising"])


class MidTierAndCohortTest(unittest.TestCase):
    def test_mid_excludes_pool_and_dust(self):
        stats = hh.mid_tier_stats([
            _h("dust", 9),
            _h("crab", 250, balance=1000),
            _h("fish", 4000, balance=2000),
            _h("shark", 50_000, balance=9000),
            _h("POOL", 800, balance=500, is_wallet=True),
        ], market_cap=100_000, pool_addresses=["POOL"])
        self.assertEqual(stats["count"], 2)
        self.assertIn("crab", stats["balances"])
        self.assertIn("fish", stats["balances"])
        self.assertNotIn("POOL", stats["balances"])
        self.assertAlmostEqual(stats["pct_mc"], 4.25, places=2)

    def test_score_cohort_uses_token_not_usd(self):
        frozen = {"A": 100.0, "B": 100.0}
        current = {"A": 100.0, "B": 40.0}  # B potong 60% token
        score = hh.score_cohort(frozen, current)
        self.assertAlmostEqual(score["remaining_pct"], 70.0, places=2)
        self.assertAlmostEqual(score["cut50_pct"], 50.0, places=2)

    def test_missing_address_counts_as_full_exit(self):
        score = hh.score_cohort({"A": 10.0}, {})
        self.assertAlmostEqual(score["remaining_pct"], 0.0)
        self.assertAlmostEqual(score["cut50_pct"], 100.0)

    def test_lookup_fills_zero_for_missing(self):
        found = hh.lookup_balances([_h("A", 5, balance=3)], ["A", "B"])
        self.assertEqual(found["A"], 3)
        self.assertEqual(found["B"], 0.0)


class HistoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "hist.json")

    def _analysis(self, *, dust_pct=0.4, dust_count=10, mid_balances=None,
                  cohort_now=None, ts=1_800_000_000):
        return {
            "symbol": "TST", "marketcap": 50_000, "price": 0.01,
            "analyzed_at": ts,
            "holders": {
                "dust_count": dust_count, "dust_pct_mc": dust_pct,
                "dust_value_usd": 200, "real_count": 8, "real_pct_mc": 12.0,
                "mid": {"count": len(mid_balances or {}), "pct_mc": 5.0,
                        "balances": mid_balances or {"A": 10.0}},
                "cohort_now": cohort_now or {},
            },
        }

    def test_first_ingest_freezes_cohort_at_100(self):
        store = hh.empty_store()
        hh.ingest_one(store, "MINT", self._analysis(mid_balances={"A": 10}),
                      now=100)
        self.assertEqual(store["tokens"]["MINT"]["cohort"]["balances"]["A"], 10)
        pt = store["tokens"]["MINT"]["points"][0]
        self.assertAlmostEqual(pt["cohort_token_pct"], 100.0)

    def test_second_ingest_scores_against_frozen_tokens(self):
        store = hh.empty_store()
        hh.ingest_one(store, "MINT", self._analysis(mid_balances={"A": 10},
                                                    ts=100), now=100)
        hh.ingest_one(store, "MINT", self._analysis(
            mid_balances={"A": 4}, cohort_now={"A": 4}, ts=100 + 900),
                      now=100 + 900)
        pt = store["tokens"]["MINT"]["points"][-1]
        self.assertAlmostEqual(pt["cohort_token_pct"], 40.0)
        self.assertAlmostEqual(pt["cohort_cut50_pct"], 100.0)

    def test_resample_4h_keeps_last_in_bucket(self):
        points = [
            {"ts": 0, "dust_pct_mc": 0.5},
            {"ts": 100, "dust_pct_mc": 0.8},
            {"ts": 4 * 3600 + 10, "dust_pct_mc": 1.2},
        ]
        sampled = hh.resample_4h(points)
        self.assertEqual(len(sampled), 2)
        self.assertAlmostEqual(sampled[0]["dust_pct_mc"], 0.8)
        self.assertAlmostEqual(sampled[1]["dust_pct_mc"], 1.2)

    def test_sparkline_needs_two_values(self):
        self.assertEqual(hh.sparkline_svg([{"ts": 1, "dust_pct_mc": 1}]), "")
        svg = hh.sparkline_svg([
            {"ts": 100, "dust_pct_mc": 0.4},
            {"ts": 4 * 3600 + 100, "dust_pct_mc": 1.5},
        ])
        self.assertIn("<svg", svg)
        self.assertIn("#b91c1c", svg)  # rising → merah

    def test_ingest_many_roundtrip_file(self):
        hh.ingest_many({"MINT": self._analysis()}, path=self.path, now=50)
        loaded = hh.load_holder_history(self.path)
        self.assertIn("MINT", loaded["tokens"])
        self.assertEqual(len(loaded["tokens"]["MINT"]["points"]), 1)


if __name__ == "__main__":
    unittest.main()
