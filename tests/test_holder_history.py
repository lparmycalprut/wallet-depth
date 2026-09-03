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
    def test_danger_at_one_percent(self):
        flag = hh.dust_flag(1.0)
        self.assertEqual(flag["level"], "danger")
        self.assertEqual(flag["label"], "BAHAYA")
        self.assertTrue(flag["hide"])
        self.assertTrue(hh.should_hide_dust(1.0))
        self.assertTrue(hh.should_hide_dust(2.01))

    def test_ok_below_one_percent(self):
        flag = hh.dust_flag(0.99)
        self.assertEqual(flag["level"], "ok")
        self.assertFalse(flag["hide"])
        self.assertFalse(hh.should_hide_dust(0.5))

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

    def test_detail_scan_writes_baseline_once(self):
        store = hh.empty_store()
        first = self._analysis(dust_count=10)
        first["holders"]["depth"] = {
            "buckets": [{"label": ">$0-$10", "count": 10, "value_usd": 50},
                        {"label": "$10-$100", "count": 4, "value_usd": 200}],
            "tiers": [{"tier": "Shrimp", "emoji": "🦐", "count": 12,
                       "pct_mc": 1.0}],
            "holders_all": 14, "holders_wallet": 14,
        }
        first["holders"]["wallets_analyzed"] = 14
        hh.ingest_one(store, "MINT", first, now=100, detail=True)
        baseline = hh.baseline_for_mint(store, "MINT")
        self.assertEqual(baseline["ts"], 100)
        self.assertEqual(len(baseline["depth"]["buckets"]), 2)

        second = self._analysis(dust_count=30)
        second["holders"]["depth"] = {
            "buckets": [{"label": ">$0-$10", "count": 30, "value_usd": 120},
                        {"label": "$10-$100", "count": 3, "value_usd": 150}],
            "tiers": [], "holders_all": 33, "holders_wallet": 33,
        }
        second["holders"]["wallets_analyzed"] = 33
        hh.ingest_one(store, "MINT", second, now=100 + 3600, detail=True)
        # Baseline tetap scan pertama, detail terbaru ikut yang kedua.
        self.assertEqual(hh.baseline_for_mint(store, "MINT")["ts"], 100)
        self.assertEqual(hh.latest_detail_for_mint(store, "MINT")["ts"],
                         100 + 3600)
        delta = {r["label"]: r["delta"] for r in hh.bucket_delta(
            hh.baseline_for_mint(store, "MINT"),
            hh.latest_detail_for_mint(store, "MINT"))}
        self.assertEqual(delta[">$0-$10"], 20)
        self.assertEqual(delta["$10-$100"], -1)

    def test_cron_point_never_overwrites_baseline(self):
        store = hh.empty_store()
        full = self._analysis()
        full["holders"]["depth"] = {
            "buckets": [{"label": ">$0-$10", "count": 5, "value_usd": 20}],
            "tiers": [],
        }
        hh.ingest_one(store, "MINT", full, now=100, detail=True)
        hh.ingest_one(store, "MINT", self._analysis(dust_count=99),
                      now=100 + 3600)  # cron: detail=False
        self.assertEqual(hh.baseline_for_mint(store, "MINT")["ts"], 100)
        self.assertEqual(
            hh.latest_detail_for_mint(store, "MINT")["ts"], 100)
        self.assertEqual(store["tokens"]["MINT"]["points"][-1]["dust_count"],
                         99)
        self.assertTrue(store["tokens"]["MINT"]["points"][0].get("full"))
        self.assertNotIn("full", store["tokens"]["MINT"]["points"][-1])

    def test_bucket_counts_and_series(self):
        self.assertEqual(
            hh.bucket_counts({"buckets": [{"label": "$10-$100", "count": 7}]}),
            {"$10-$100": 7})
        points = [
            {"ts": 100, "buckets": {"a": 1, "b": 2}},
            {"ts": 4 * 3600 + 100, "buckets": {"a": 4}},
        ]
        stamps, labels, series = hh.bucket_series(points)
        self.assertEqual(len(stamps), 2)
        self.assertEqual(labels, ["a", "b"])
        self.assertEqual(series["a"], [1, 4])
        self.assertEqual(series["b"], [2, 0])

    def test_detail_survives_save_and_load(self):
        analysis = self._analysis()
        analysis["holders"]["depth"] = {
            "buckets": [{"label": ">$0-$10", "count": 3, "value_usd": 9}],
            "tiers": [],
        }
        hh.ingest_many({"MINT": analysis}, path=self.path, now=50,
                       detail=True)
        loaded = hh.load_holder_history(self.path)
        self.assertEqual(hh.baseline_for_mint(loaded, "MINT")["ts"], 50)
        self.assertEqual(
            hh.baseline_for_mint(loaded, "MINT")["depth"]["buckets"][0][
                "count"], 3)

    def test_ingest_many_roundtrip_file(self):
        hh.ingest_many({"MINT": self._analysis()}, path=self.path, now=50)
        loaded = hh.load_holder_history(self.path)
        self.assertIn("MINT", loaded["tokens"])
        self.assertEqual(len(loaded["tokens"]["MINT"]["points"]), 1)

    def test_seed_from_status_restores_alert_state_for_next_cron(self):
        remote_state = {
            "baseline": {"ts": 100, "dust_pct_mc": 0.2,
                         "balances": {"A": 1.0}, "dust": ["A"]},
            "rolling": {"ts": 200, "dust_pct_mc": 0.4,
                        "balances": {"A": 2.0}, "dust": ["A"]},
            "sent_event_ids": ["event-1"],
        }
        store = hh.seed_from_status(
            hh.empty_store(),
            {"tokens": {"MINT": {"symbol": "TST", "history": [],
                                  "alert_state": remote_state}}},
        )
        restored = store["tokens"]["MINT"]["alert_state"]
        self.assertEqual(restored["rolling"]["ts"], 200)
        self.assertEqual(restored["sent_event_ids"], ["event-1"])


if __name__ == "__main__":
    unittest.main()
