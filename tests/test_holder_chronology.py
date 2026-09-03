"""Kronologi holder antar-scan FULL: klasifikasi, batas payload, history."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import holder_chronology as hc
import holder_history as hh
from solscan_holders import (DUST_CATEGORY, EXITED_CATEGORY, UNKNOWN_CATEGORY,
                             holder_category)


NOW = 1_800_000_000
HOUR = 3600
MINT = "MintChrono111111111111111111111111111111"
GROW = "Grow1111111111111111111111111111111111111"
PRICE = "Pric1111111111111111111111111111111111111"
SOLD = "Sold1111111111111111111111111111111111111"
MISS = "Miss1111111111111111111111111111111111111"
SHRK = "Shrk1111111111111111111111111111111111111"
NEWA = "NewA1111111111111111111111111111111111111"
SAME = "Same1111111111111111111111111111111111111"
POOL = "Pool1111111111111111111111111111111111111"
NOIS = "Nois1111111111111111111111111111111111111"


def _h(addr, balance, usd, *, is_wallet=True, tags=None):
    return {
        "address": addr,
        "balance": balance,
        "usd_value": usd,
        "is_wallet": is_wallet,
        "tags": list(tags or []),
        "maker_token_tags": [],
        "wallet_tag": "",
    }


def _snap(ts, rows, *, truncated=False, price=0.01, mc=100_000.0,
          dust_pct=1.40, tracked=None):
    records = hc.wallet_records(rows)
    dust_n = sum(1 for rec in records.values() if rec["dust"])
    return hc.build_chrono_snapshot(
        rows, tracked_addresses=tracked, ts=ts, price=price, market_cap=mc,
        dust_pct_mc=dust_pct, holder_count=len(records), dust_count=dust_n,
        truncated=truncated)


def _analysis(ts, rows, *, truncated=False, dust_pct=1.40, price=0.01,
              mc=100_000.0, fetched=None, tracked=None):
    snap = _snap(ts, rows, truncated=truncated, price=price, mc=mc,
                 dust_pct=dust_pct, tracked=tracked)
    records = hc.wallet_records(rows)
    dust_n = sum(1 for rec in records.values() if rec["dust"])
    return {
        "symbol": "TST", "marketcap": mc, "price": price, "analyzed_at": ts,
        "holders": {
            "dust_count": dust_n, "dust_pct_mc": dust_pct,
            "dust_value_usd": 200.0,
            "real_count": max(0, len(records) - dust_n),
            "real_pct_mc": 12.0,
            "wallets_analyzed": len(records),
            "total_fetched": len(rows) if fetched is None else fetched,
            "pages": 1, "truncated": truncated, "source": "helius",
            "mid": {"count": 0, "pct_mc": 0.0, "balances": {}},
            "cohort_now": {},
            "chrono_snapshot": snap,
            "depth": {"buckets": [], "tiers": []},
        },
    }


def _kinds(interval):
    return {row["address"]: row["kind"] for row in interval.get("movements") or []}


class HolderCategoryTest(unittest.TestCase):
    def test_dust_and_buckets_match_wallet_depth(self):
        self.assertEqual(holder_category(5.0, 100.0), DUST_CATEGORY)
        self.assertEqual(holder_category(10.0, 100.0), DUST_CATEGORY)
        self.assertEqual(holder_category(10.01, 100.0), "$10-$100")
        self.assertEqual(holder_category(100.0, 1.0), "$10-$100")
        self.assertEqual(holder_category(100.01, 1.0), "$100-$1k")
        self.assertEqual(holder_category(0.0, 0.0), EXITED_CATEGORY)
        self.assertEqual(holder_category(5.0, 0.0), EXITED_CATEGORY)
        self.assertEqual(holder_category(None, 12.0), UNKNOWN_CATEGORY)


class ClassifyMovementTest(unittest.TestCase):
    def test_dust_grows_into_upper_category(self):
        before = hc._wallet_record(100.0, 5.0)
        after = hc._wallet_record(250.0, 25.0)
        row = hc.classify_wallet_movement(GROW, before, after,
                                          current_truncated=False)
        self.assertEqual(row["kind"], "dust_grew_out")
        self.assertIn("menambah muatan", row["interpretation"])
        self.assertIn("$10-$100", row["interpretation"])
        self.assertNotIn("membeli", row["interpretation"].lower())

    def test_dust_exits_because_of_price_not_buy(self):
        before = hc._wallet_record(100.0, 8.0)
        after = hc._wallet_record(100.0, 16.0)  # balance tetap, USD naik
        row = hc.classify_wallet_movement(PRICE, before, after,
                                          current_truncated=False)
        self.assertEqual(row["kind"], "dust_price_exit")
        self.assertIn("perubahan harga", row["interpretation"])
        self.assertNotIn("membeli", row["interpretation"].lower())
        self.assertNotIn("menambah muatan", row["interpretation"])

    def test_zero_balance_is_exit_not_definite_sale(self):
        before = hc._wallet_record(80.0, 6.0)
        after = hc._wallet_record(0.0, 0.0)
        row = hc.classify_wallet_movement(SOLD, before, after,
                                          current_truncated=False)
        self.assertEqual(row["kind"], "exited_total")
        self.assertIn("jual seluruh holding atau transfer",
                      row["interpretation"])
        self.assertNotIn("pasti", row["interpretation"].lower())
        self.assertTrue(hc.claims_are_non_definitive(row["interpretation"]))

    def test_missing_on_truncated_scan_is_unobserved(self):
        before = hc._wallet_record(80.0, 6.0)
        row = hc.classify_wallet_movement(MISS, before, None,
                                          current_truncated=True)
        self.assertEqual(row["kind"], "unobserved")
        self.assertIn("belum dapat dipastikan", row["interpretation"])
        self.assertNotIn("pasti menjual", row["interpretation"].lower())
        self.assertTrue(hc.claims_are_non_definitive(row["interpretation"]))

    def test_missing_on_complete_scan_is_exit(self):
        before = hc._wallet_record(80.0, 6.0)
        row = hc.classify_wallet_movement(MISS, before, None,
                                          current_truncated=False)
        self.assertEqual(row["kind"], "exited_total")

    def test_upper_category_shrinks_to_dust(self):
        before = hc._wallet_record(1000.0, 50.0)
        after = hc._wallet_record(100.0, 5.0)
        row = hc.classify_wallet_movement(SHRK, before, after,
                                          current_truncated=False)
        self.assertEqual(row["kind"], "shrank_to_dust")
        self.assertIn("turun dari $10-$100 ke Dust", row["interpretation"])

    def test_new_wallet_separated_from_old_increase(self):
        after = hc._wallet_record(40.0, 4.0)
        row = hc.classify_wallet_movement(NEWA, None, after,
                                          current_truncated=False)
        self.assertEqual(row["kind"], "new_wallet")
        self.assertIn("baru teramati", row["interpretation"])

    def test_same_category_balance_change(self):
        before = hc._wallet_record(100.0, 5.0)
        up = hc.classify_wallet_movement(
            SAME, before, hc._wallet_record(150.0, 7.5),
            current_truncated=False)
        down = hc.classify_wallet_movement(
            SAME, before, hc._wallet_record(50.0, 2.5),
            current_truncated=False)
        self.assertEqual(up["kind"], "increased_same")
        self.assertEqual(down["kind"], "decreased_same")
        tiny = hc.classify_wallet_movement(
            SAME, before, hc._wallet_record(100.000000001, 5.0),
            current_truncated=False)
        self.assertIsNone(tiny)

    def test_lp_and_noise_excluded(self):
        rows = [
            _h(GROW, 100.0, 5.0),
            _h(POOL, 9_000.0, 9_000.0, is_wallet=False),
            _h("PoolAddr", 8_000.0, 8_000.0, is_wallet=True),
            _h(NOIS, 50.0, 4.0, tags=["sandwich_bot"]),
        ]
        records = hc.wallet_records(rows, pool_addresses=["PoolAddr"])
        self.assertIn(GROW, records)
        self.assertNotIn(POOL, records)
        self.assertNotIn("PoolAddr", records)
        self.assertNotIn(NOIS, records)

    def test_address_trim_is_case_sensitive(self):
        rows = [
            _h("  AbC  ", 10.0, 5.0),
            _h("abc", 20.0, 6.0),
        ]
        records = hc.wallet_records(rows)
        self.assertIn("AbC", records)
        self.assertIn("abc", records)
        self.assertEqual(records["AbC"]["balance"], 10.0)


class CompareAndNarrativeTest(unittest.TestCase):
    def setUp(self):
        self.t0 = NOW
        self.t1 = NOW + 4 * HOUR
        self.before = [
            _h(GROW, 100.0, 5.0),
            _h(PRICE, 100.0, 8.0),
            _h(SOLD, 80.0, 6.0),
            _h(SHRK, 1000.0, 50.0),
            _h(SAME, 100.0, 5.0),
        ]
        self.after = [
            _h(GROW, 250.0, 25.0),
            _h(PRICE, 100.0, 16.0),
            _h(SOLD, 0.0, 0.0),
            _h(SHRK, 100.0, 5.0),
            _h(SAME, 160.0, 8.0),
            _h(NEWA, 40.0, 4.0),
        ]

    def test_interval_counts_and_solscan_link(self):
        prev = _snap(self.t0, self.before, dust_pct=1.40)
        curr = _snap(self.t1, self.after, dust_pct=0.72)
        interval = hc.compare_snapshots(prev, curr)
        kinds = _kinds(interval)
        self.assertEqual(kinds[GROW], "dust_grew_out")
        self.assertEqual(kinds[PRICE], "dust_price_exit")
        self.assertEqual(kinds[SOLD], "exited_total")
        self.assertEqual(kinds[SHRK], "shrank_to_dust")
        self.assertEqual(kinds[NEWA], "new_wallet")
        self.assertEqual(kinds[SAME], "increased_same")
        self.assertGreaterEqual(interval["counts"]["increased"], 2)
        self.assertEqual(interval["counts"]["new_wallets"], 1)
        grow = next(row for row in interval["movements"] if row["address"] == GROW)
        self.assertEqual(grow["solscan"], f"https://solscan.io/account/{GROW}")
        self.assertNotIn("...", grow["solscan"])
        rows = hc.movement_table_rows([grow])
        self.assertEqual(rows[0]["Solscan"], grow["solscan"])
        self.assertIn("...", rows[0]["Wallet"])
        self.assertTrue(hc.claims_are_non_definitive(grow["interpretation"]))

    def test_truncated_missing_not_sold(self):
        prev = _snap(self.t0, self.before)
        after = [row for row in self.after if row["address"] != SOLD]
        curr = _snap(self.t1, after, truncated=True)
        interval = hc.compare_snapshots(prev, curr)
        kinds = _kinds(interval)
        self.assertEqual(kinds[SOLD], "unobserved")
        self.assertNotEqual(kinds.get(SOLD), "exited_total")

    def test_chronology_sorted_by_time(self):
        packed = hc.compact_chronology({
            "intervals": [
                {"from_ts": self.t1, "to_ts": self.t1 + HOUR, "counts": {},
                 "movements": []},
                {"from_ts": self.t0, "to_ts": self.t1, "counts": {},
                 "movements": []},
            ],
        })
        stamps = [row["from_ts"] for row in packed["intervals"]]
        self.assertEqual(stamps, sorted(stamps))

    def test_payload_is_bounded(self):
        holders = [_h(f"W{i:04d}{'x' * 28}", float(i + 1), 5.0)
                   for i in range(hc.MAX_SNAPSHOT_WALLETS + 80)]
        snap = hc.build_chrono_snapshot(holders, ts=NOW)
        self.assertLessEqual(len(snap["wallets"]), hc.MAX_SNAPSHOT_WALLETS)
        self.assertTrue(snap["sampled"])
        self.assertEqual(snap["wallets_seen"], hc.MAX_SNAPSHOT_WALLETS + 80)
        movements = [{
            "address": f"W{i:04d}{'x' * 28}",
            "kind": "increased_same",
            "from_category": "Dust", "to_category": "Dust",
            "balance_before": 1.0, "balance_after": 2.0,
            "delta_balance": 1.0, "interpretation": "x",
            "solscan": "https://solscan.io/account/x",
        } for i in range(hc.MAX_MOVEMENTS_PER_INTERVAL + 20)]
        interval = hc.compact_interval({"from_ts": 1, "to_ts": 2,
                                        "movements": movements, "counts": {}})
        self.assertLessEqual(len(interval["movements"]),
                             hc.MAX_MOVEMENTS_PER_INTERVAL)
        chrono = hc.compact_chronology({
            "intervals": [{"from_ts": i, "to_ts": i + 1, "movements": [],
                           "counts": {}}
                          for i in range(hc.MAX_CHRONOLOGY_INTERVALS + 5)],
        })
        self.assertLessEqual(len(chrono["intervals"]),
                             hc.MAX_CHRONOLOGY_INTERVALS)

    def test_unsafe_address_is_url_encoded(self):
        nasty = "abc&def ghi"
        url = hc.solscan_link(nasty)
        self.assertTrue(url.startswith("https://solscan.io/account/"))
        self.assertNotIn("&", url.split("/account/")[-1])
        self.assertNotIn(" ", url)

    def test_narrative_mentions_sample_and_avoids_buy_claims(self):
        text = hc.cumulative_narrative(
            {"dust_pct_mc": 1.40}, {"dust_pct_mc": 0.72},
            {"dust_grew_out": 4, "exited_total": 3, "new_wallets": 7,
             "unobserved": 0, "dust_price_exit": 0, "shrank_to_dust": 0,
             "category_moves": 4},
            sampled=True)
        self.assertIn("1,40% MC", text)
        self.assertIn("0,72% MC", text)
        self.assertIn("sampel", text.lower())
        self.assertTrue(hc.claims_are_non_definitive(text))
        self.assertNotIn("membeli", text.lower())


class HistoryIngestChronologyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "hist.json")

    def test_first_full_scan_is_initial_snapshot(self):
        store = hh.empty_store()
        first = _analysis(NOW, [_h(GROW, 100.0, 5.0)], dust_pct=1.40)
        hh.ingest_one(store, MINT, first, now=NOW, detail=True)
        view = hh.chronology_view_for_mint(store, MINT)
        self.assertEqual(view["state"], "initial")
        self.assertIn("snapshot awal", view["message"].lower())
        self.assertEqual(hh.baseline_for_mint(store, MINT)["ts"], NOW)
        self.assertEqual(len(hh.chronology_for_mint(store, MINT)["intervals"]), 0)

    def test_second_full_scan_does_not_overwrite_baseline(self):
        store = hh.empty_store()
        first = _analysis(NOW, [
            _h(GROW, 100.0, 5.0), _h(SOLD, 80.0, 6.0),
        ], dust_pct=1.40)
        second = _analysis(NOW + 4 * HOUR, [
            _h(GROW, 250.0, 25.0), _h(NEWA, 40.0, 4.0),
        ], dust_pct=0.72)
        hh.ingest_one(store, MINT, first, now=NOW, detail=True)
        hh.ingest_one(store, MINT, second, now=NOW + 4 * HOUR, detail=True)
        self.assertEqual(hh.baseline_for_mint(store, MINT)["ts"], NOW)
        self.assertEqual(hh.latest_detail_for_mint(store, MINT)["ts"],
                         NOW + 4 * HOUR)
        chrono = hh.chronology_for_mint(store, MINT)
        self.assertEqual(len(chrono["intervals"]), 1)
        kinds = _kinds(chrono["intervals"][0])
        self.assertEqual(kinds[GROW], "dust_grew_out")
        self.assertEqual(kinds[SOLD], "exited_total")
        self.assertEqual(kinds[NEWA], "new_wallet")
        view = hh.chronology_view_for_mint(store, MINT)
        self.assertEqual(view["state"], "ready")
        self.assertTrue(view["intervals"])

    def test_failed_full_scan_does_not_change_history(self):
        store = hh.empty_store()
        first = _analysis(NOW, [_h(GROW, 100.0, 5.0)])
        hh.ingest_one(store, MINT, first, now=NOW, detail=True)
        before = json.loads(json.dumps(store))
        failed = _analysis(NOW + HOUR, [], fetched=0, dust_pct=0.0)
        failed["holders"]["total_fetched"] = 0
        hh.ingest_one(store, MINT, failed, now=NOW + HOUR, detail=True)
        self.assertEqual(hh.baseline_for_mint(store, MINT)["ts"], NOW)
        self.assertEqual(hh.latest_detail_for_mint(store, MINT)["ts"], NOW)
        self.assertEqual(len(store["tokens"][MINT]["points"]),
                         len(before["tokens"][MINT]["points"]))
        self.assertEqual(len(hh.chronology_for_mint(store, MINT)["intervals"]), 0)

    def test_old_schema_loads_without_error(self):
        old = {
            "updated_at": NOW,
            "tokens": {
                MINT: {
                    "symbol": "TST",
                    "cohort": {},
                    "points": [{"ts": NOW, "dust_pct_mc": 0.5,
                                "dust_count": 3, "holder_count": 10}],
                    "baseline": {"ts": NOW, "dust_count": 3,
                                 "dust_pct_mc": 0.5, "holder_count": 10},
                    "latest_detail": {"ts": NOW, "dust_count": 3,
                                      "dust_pct_mc": 0.5, "holder_count": 10},
                }
            },
        }
        view = hh.chronology_view_for_mint(old, MINT)
        self.assertEqual(view["state"], "initial")
        chrono = hh.chronology_for_mint(old, MINT)
        self.assertEqual(chrono["intervals"], [])
        hh.ingest_one(old, MINT, _analysis(NOW + 4 * HOUR, [_h(GROW, 1.0, 4.0)]),
                      now=NOW + 4 * HOUR, detail=True)
        self.assertEqual(hh.baseline_for_mint(old, MINT)["ts"], NOW)

    def test_save_load_keeps_chronology(self):
        first = _analysis(NOW, [_h(GROW, 100.0, 5.0), _h(SOLD, 80.0, 6.0)])
        second = _analysis(NOW + 4 * HOUR, [_h(GROW, 250.0, 25.0)])
        store = hh.empty_store()
        hh.ingest_one(store, MINT, first, now=NOW, detail=True)
        hh.ingest_one(store, MINT, second, now=NOW + 4 * HOUR, detail=True)
        hh.save_holder_history(store, self.path)
        loaded = hh.load_holder_history(self.path)
        chrono = hh.chronology_for_mint(loaded, MINT)
        self.assertEqual(len(chrono["intervals"]), 1)
        self.assertIn(GROW, chrono["latest_wallets"]["wallets"])
        self.assertEqual(hh.baseline_for_mint(loaded, MINT)["ts"], NOW)

    def test_other_token_unchanged(self):
        store = hh.empty_store()
        other = "OtherMint1111111111111111111111111111111"
        hh.ingest_one(store, other, _analysis(NOW, [_h(SAME, 10.0, 4.0)]),
                      now=NOW, detail=True)
        hh.ingest_one(store, MINT, _analysis(NOW + HOUR, [_h(GROW, 10.0, 4.0)]),
                      now=NOW + HOUR, detail=True)
        self.assertEqual(hh.baseline_for_mint(store, other)["ts"], NOW)
        self.assertEqual(len(hh.chronology_for_mint(store, other)["intervals"]),
                         0)

    def test_seed_from_status_restores_compact_chronology(self):
        remote = {
            "tokens": {
                MINT: {
                    "symbol": "TST",
                    "history": [],
                    "chronology": {
                        "intervals": [{
                            "from_ts": NOW, "to_ts": NOW + HOUR,
                            "counts": {"new_wallets": 1},
                            "movements": [],
                        }],
                        "latest_wallets": {
                            "ts": NOW + HOUR,
                            "wallets": {GROW: {"balance": 2.0, "usd": 4.0,
                                               "category": "Dust",
                                               "dust": True}},
                        },
                        "baseline_wallets": {
                            "ts": NOW,
                            "wallets": {GROW: {"balance": 1.0, "usd": 2.0,
                                               "category": "Dust",
                                               "dust": True}},
                        },
                    },
                }
            }
        }
        store = hh.seed_from_status(hh.empty_store(), remote)
        chrono = hh.chronology_for_mint(store, MINT)
        self.assertEqual(len(chrono["intervals"]), 1)
        self.assertIn(GROW, chrono["latest_wallets"]["wallets"])


class AnalyzeTokenChronoSnapshotTest(unittest.TestCase):
    def test_analyze_token_attaches_bounded_chrono_snapshot(self):
        import holder_analysis as sa
        snapshot = {
            "holders": [
                _h(GROW, 100.0, 5.0),
                _h(POOL, 9_000.0, 9_000.0, is_wallet=False),
            ],
            "source": "helius", "truncated": False, "pages": 1,
        }
        market = {"marketcap": 10_000, "price_usd": 0.1, "pair_addresses": []}
        with mock.patch.object(sa, "get_market", return_value=market), \
                mock.patch.object(
                    sa, "_fetch_holders_snapshot",
                    return_value=(snapshot, None)):
            result = sa.analyze_token("MINT", "TST")
        chrono = result["holders"]["chrono_snapshot"]
        self.assertIn(GROW, chrono["wallets"])
        self.assertNotIn(POOL, chrono["wallets"])
        self.assertEqual(chrono["wallets"][GROW]["category"], DUST_CATEGORY)


import unittest.mock  # noqa: E402  — dipakai tes analyze_token


class StatusStripsRawChronoTest(unittest.TestCase):
    def test_status_keeps_compact_chronology_not_raw_holders(self):
        import holder_status as ss
        analyses = {MINT: _analysis(NOW, [_h(GROW, 100.0, 5.0)])}
        analyses[MINT]["holders"]["wallet_snapshot"] = {
            "balances": {GROW: 100.0}, "dust": [GROW]}
        history = {"tokens": {MINT: {
            "chronology": {
                "intervals": [{"from_ts": NOW, "to_ts": NOW + 1,
                               "counts": {}, "movements": []}],
                "latest_wallets": {"ts": NOW, "wallets": {
                    GROW: {"balance": 100.0, "usd": 5.0,
                           "category": "Dust", "dust": True}}},
                "baseline_wallets": {"ts": NOW, "wallets": {
                    GROW: {"balance": 100.0, "usd": 5.0,
                           "category": "Dust", "dust": True}}},
            },
            "points": [], "cohort": {},
        }}}
        token = ss.snapshot_status(
            analyses, history_store=history)["tokens"][MINT]
        self.assertNotIn("chrono_snapshot", token["holders"])
        self.assertNotIn("wallet_snapshot", token["holders"])
        self.assertIn("chronology", token)
        self.assertEqual(len(token["chronology"]["intervals"]), 1)


if __name__ == "__main__":
    unittest.main()
