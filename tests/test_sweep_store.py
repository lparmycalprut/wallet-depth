# -*- coding: utf-8 -*-
"""Penyimpanan page 🌊 Sweep (:mod:`sweep_store`).

Yang di-pin di sini adalah kontrak yang membuat statistik bisa dipercaya:
watchlist selalu list bersih, snapshot dibucket per jam (bukan per 5 menit),
``update_outcomes`` mencatat ``max_up`` / ``max_down`` yang benar, dan
``alert_gate`` hanya membuka jalan saat **transisi** status — bukan tiap scan.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import sweep_store as store


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sweep-store-")
        self.watchlist = os.path.join(self.dir, "sweep_watchlist.json")
        self.state_path = os.path.join(self.dir, "sweep_state.json")
        for target, value in (("WATCHLIST_PATH", self.watchlist),
                              ("STATE_PATH", self.state_path)):
            patcher = mock.patch.object(store, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write_state(self, data):
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)


class ParseMintsTest(unittest.TestCase):
    def test_accepts_text_list_and_junk(self):
        raw = ("AAA111\nBBB222\n# komentar\nAAA111\n"
               "CCC333, DDD444  EEE555\n\n")
        self.assertEqual(store.parse_mints(raw),
                         ["AAA111", "BBB222", "CCC333", "DDD444", "EEE555"])

    def test_accepts_list_and_none(self):
        self.assertEqual(store.parse_mints(["A", "", " A ", "B"]), ["A", "B"])
        self.assertEqual(store.parse_mints(None), [])
        self.assertEqual(store.parse_mints([]), [])


class WatchlistTest(_Sandbox):
    def test_roundtrip(self):
        saved = store.save_watchlist(["A", "B"], persist=False)
        self.assertEqual(saved, ["A", "B"])
        self.assertEqual(store.load_watchlist(), ["A", "B"])

    def test_load_missing_file_is_empty(self):
        self.assertEqual(store.load_watchlist(), [])

    def test_load_legacy_dict_format(self):
        with open(self.watchlist, "w", encoding="utf-8") as handle:
            json.dump({"A": {"symbol": "AAA"}, "B": {"symbol": "BBB"}}, handle)
        self.assertEqual(store.load_watchlist(), ["A", "B"])

    def test_load_corrupt_file_is_empty(self):
        with open(self.watchlist, "w", encoding="utf-8") as handle:
            handle.write("{bukan json")
        self.assertEqual(store.load_watchlist(), [])

    def test_falls_back_to_config_when_file_empty(self):
        # Streamlit Cloud: berkas lokal hilang saat restart → cadangan
        # config.json harus tetap terbaca.
        config = os.path.join(self.dir, "config.json")
        with open(config, "w", encoding="utf-8") as handle:
            json.dump({"sweep_watchlist": ["AAA111", "BBB222"]}, handle)
        with mock.patch.object(store, "CONFIG_PATH", config):
            self.assertEqual(store.load_watchlist(), ["AAA111", "BBB222"])
            # Berkas lokal yang berisi tetap menang atas cadangan.
            store.save_watchlist(["CCC333"], persist=False)
            self.assertEqual(store.load_watchlist(), ["CCC333"])

    def test_push_watchlist_reports_failure(self):
        with mock.patch.object(store, "push_json", return_value=False) as push:
            self.assertFalse(store.push_watchlist(["A"]))
        self.assertEqual(push.call_args[0][0], "sweep_watchlist.json")
        self.assertIn("1 mint", push.call_args[0][2])

    def test_save_watchlist_can_skip_push(self):
        with mock.patch.object(store, "push_json") as push:
            store.save_watchlist(["A"], persist=False)
        push.assert_not_called()


class StateTest(_Sandbox):
    def test_load_missing_and_corrupt(self):
        self.assertEqual(store.load_state()["signals"], [])
        self._write_state("bukan objek")
        self.assertEqual(store.load_state()["snapshots"], {})

    def test_snapshot_is_bucketed_per_hour(self):
        state = store.empty_state()
        store.add_snapshot(state, "M", {"price_usd": 1.0, "ts": 3600 + 10})
        store.add_snapshot(state, "M", {"price_usd": 1.1, "ts": 3600 + 50})
        store.add_snapshot(state, "M", {"price_usd": 1.2, "ts": 7200 + 5})
        buckets = state["snapshots"]["M"]
        self.assertEqual(sorted(buckets.keys()), ["3600", "7200"])
        # Bucket terakhir menang dalam satu jam (nilai terbaru).
        self.assertEqual(buckets["3600"]["price"], 1.1)

    def test_mint_history_sorted_and_limited(self):
        state = store.empty_state()
        for hour in (3, 1, 2):
            store.add_snapshot(state, "M", {"price_usd": float(hour),
                                            "ts": hour * 3600 + 5})
        rows = store.mint_history(state, "M", limit=2)
        self.assertEqual([r["price"] for r in rows], [2.0, 3.0])
        self.assertEqual(store.mint_history(state, "X"), [])

    def test_prune_caps_buckets_and_signals(self):
        state = store.empty_state()
        state["snapshots"]["M"] = {str(i): {"ts": i} for i in range(300)}
        state["signals"] = [{"id": str(i)} for i in range(store.MAX_SIGNALS + 10)]
        store.prune(state)
        self.assertEqual(len(state["snapshots"]["M"]),
                         store.MAX_BUCKETS_PER_MINT)
        self.assertEqual(len(state["signals"]), store.MAX_SIGNALS)
        # Yang tersisa adalah bucket paling baru.
        self.assertIn("299", state["snapshots"]["M"])

    def test_fingerprint_ignores_volatile_fields(self):
        state = store.empty_state()
        store.add_snapshot(state, "M", {"price_usd": 1.0, "ts": 3600})
        first = store.fingerprint(state)
        state["updated"] = 999
        state["alerts"] = {"M": {"last_sweep_ts": 123}}
        self.assertEqual(store.fingerprint(state), first)
        store.record_signal(state, {"mint": "M", "kind": "sweep", "ts": 5})
        self.assertNotEqual(store.fingerprint(state), first)


class NetInflowTest(_Sandbox):
    """Inflow nyata = Δ likuiditas antar snapshot (dasar churn nyata)."""

    def test_no_previous_snapshot(self):
        state = store.empty_state()
        store.add_snapshot(state, "M", {"liq_usd": 30000.0, "ts": 7200})
        self.assertIsNone(store.previous_snapshot(state, "M", 7200))
        self.assertIsNone(store.net_inflow(state, "M", 30000.0, 7200))

    def test_measures_delta_between_buckets(self):
        state = store.empty_state()
        store.add_snapshot(state, "M", {"liq_usd": 30232.0, "ts": 3600 + 10})
        store.add_snapshot(state, "M", {"liq_usd": 89010.0, "ts": 7200 + 10})
        prev = store.previous_snapshot(state, "M", 7200 + 20)
        self.assertEqual(prev["liq_usd"], 30232.0)
        self.assertEqual(store.net_inflow(state, "M", 89010.0, 7200 + 20),
                         58778.0)

    def test_ignores_stale_previous_snapshot(self):
        state = store.empty_state()
        store.add_snapshot(state, "M", {"liq_usd": 30232.0, "ts": 3600})
        # 5 jam kemudian: selisihnya bukan lagi "inflow sweep".
        self.assertIsNone(store.previous_snapshot(state, "M", 3600 * 6))
        self.assertIsNone(store.net_inflow(state, "M", 89010.0, 3600 * 6))

    def test_liquidity_drop_is_not_inflow(self):
        state = store.empty_state()
        store.add_snapshot(state, "M", {"liq_usd": 90000.0, "ts": 3600})
        store.add_snapshot(state, "M", {"liq_usd": 30000.0, "ts": 7200})
        self.assertIsNone(store.net_inflow(state, "M", 30000.0, 7300))

    def test_missing_liquidity_is_not_guessed(self):
        state = store.empty_state()
        store.add_snapshot(state, "M", {"liq_usd": None, "ts": 3600})
        store.add_snapshot(state, "M", {"liq_usd": 30000.0, "ts": 7200})
        self.assertIsNone(store.net_inflow(state, "M", 30000.0, 7300))
        self.assertIsNone(store.net_inflow(state, "M", None, 7300))


class FixedStateTest(_Sandbox):
    def test_legacy_settings_are_ignored_and_removed_on_save(self):
        state = store.empty_state()
        state["settings"] = {"liq_mc_max": 0.25, "holder_max_pct": 1.0}
        before = store.fingerprint(state)
        state["settings"]["liq_mc_max"] = 0.60
        self.assertEqual(store.fingerprint(state), before)
        store.save_state(state)
        self.assertNotIn("settings", store.load_state())

    def test_fingerprint_ignores_price_churn_inside_same_hour(self):
        """Run cron yang menimpa bucket jam berjalan tidak boleh memicu commit."""
        state = store.empty_state()
        store.add_snapshot(state, "M", {"price_usd": 1.0, "ts": 3600 + 10})
        before = store.fingerprint(state)
        store.add_snapshot(state, "M", {"price_usd": 1.7, "ts": 3600 + 310})
        store.add_snapshot(state, "M", {"price_usd": 2.2, "ts": 3600 + 610})
        self.assertEqual(store.fingerprint(state), before)

    def test_fingerprint_changes_when_new_hour_bucket_appears(self):
        state = store.empty_state()
        store.add_snapshot(state, "M", {"price_usd": 1.0, "ts": 3600 + 10})
        before = store.fingerprint(state)
        store.add_snapshot(state, "M", {"price_usd": 1.0, "ts": 7200 + 10})
        self.assertNotEqual(store.fingerprint(state), before)

    def test_shakeout_latch_is_fingerprinted(self):
        state = store.empty_state()
        before = store.fingerprint(state)
        state["shakeout_latched_at"]["M"] = 12345
        self.assertNotEqual(store.fingerprint(state), before)
class SignalTest(_Sandbox):
    def test_record_signal_gets_id(self):
        state = store.empty_state()
        signal = store.record_signal(state, {"mint": "M", "kind": "sweep",
                                             "ts": 100})
        self.assertEqual(signal["id"], "sweep:M:100")
        self.assertTrue(store.has_signal(state, "sweep:M:100"))
        self.assertFalse(store.has_signal(state, "sweep:M:999"))
        self.assertEqual(signal["status"], "open")

    def test_update_outcomes_tracks_up_and_down(self):
        state = store.empty_state()
        store.record_signal(state, {"mint": "M", "kind": "sweep", "ts": 1000,
                                    "base_price": 1.0, "entry_price": 1.0})
        store.update_outcomes(state, {"M": 5.0}, now=1100)
        store.update_outcomes(state, {"M": 0.5}, now=1200)
        signal = state["signals"][0]
        self.assertAlmostEqual(signal["max_up_pct"], 400.0)
        self.assertAlmostEqual(signal["max_down_pct"], -50.0)
        self.assertAlmostEqual(signal["max_price"], 5.0)
        self.assertAlmostEqual(signal["min_price"], 0.5)
        self.assertAlmostEqual(signal["from_base_up_pct"], 400.0)
        self.assertEqual(signal["status"], "open")

    def test_update_outcomes_closes_old_signal(self):
        state = store.empty_state()
        store.record_signal(state, {"mint": "M", "kind": "sweep", "ts": 1000,
                                    "base_price": 1.0, "entry_price": 1.0})
        store.update_outcomes(state, {"M": 2.0}, now=1000 + store.SIGNAL_TRACK_SEC + 1)
        self.assertEqual(state["signals"][0]["status"], "closed")

    def test_eligible_mints_uses_latest_eligibility(self):
        state = store.empty_state()
        store.record_signal(state, {"mint": "A", "kind": "eligibility", "ts": 10})
        store.record_signal(state, {"mint": "B", "kind": "eligibility", "ts": 10})
        store.record_signal(state, {"mint": "B", "kind": "sweep", "ts": 20})
        self.assertEqual(sorted(store.eligible_mints(state)), ["A", "B"])
        for signal in state["signals"]:
            if signal["mint"] == "A":
                signal["status"] = "closed"
        self.assertEqual(store.eligible_mints(state), ["B"])


class AlertGateTest(_Sandbox):
    def test_eligibility_alerts_on_transition_then_cooldown(self):
        state = store.empty_state()
        self.assertTrue(store.alert_gate(state, "M", "eligibility", now=1000))
        # Masih aktif + di dalam cooldown → tidak diulang.
        self.assertFalse(store.alert_gate(state, "M", "eligibility", now=1001))
        self.assertFalse(store.alert_gate(
            state, "M", "eligibility", now=1000 + store.ELIG_COOLDOWN - 1))
        # Cooldown lewat → boleh lagi (masih aktif).
        self.assertTrue(store.alert_gate(
            state, "M", "eligibility", now=1000 + store.ELIG_COOLDOWN + 1))

    def test_clear_eligibility_reopens_transition(self):
        state = store.empty_state()
        self.assertTrue(store.alert_gate(state, "M", "eligibility", now=1000))
        store.clear_eligibility(state, "M")
        self.assertTrue(store.alert_gate(state, "M", "eligibility", now=1001))

    def test_sweep_cooldown_is_shorter(self):
        state = store.empty_state()
        self.assertTrue(store.alert_gate(state, "M", "sweep", now=1000))
        self.assertFalse(store.alert_gate(state, "M", "sweep", now=1001))
        self.assertTrue(store.alert_gate(
            state, "M", "sweep", now=1000 + store.SWEEP_COOLDOWN + 1))

    def test_kinds_are_independent(self):
        state = store.empty_state()
        self.assertTrue(store.alert_gate(state, "M", "eligibility", now=1000))
        self.assertTrue(store.alert_gate(state, "M", "sweep", now=1000))


class GithubPushTest(unittest.TestCase):
    def test_no_token_skips_push_without_network(self):
        calls = []

        class _Requests:
            @staticmethod
            def get(*a, **k):       # pragma: no cover - tidak boleh dipanggil
                calls.append("get")
                raise AssertionError("tidak boleh ada HTTP tanpa token")

            @staticmethod
            def put(*a, **k):       # pragma: no cover
                calls.append("put")
                raise AssertionError("tidak boleh ada HTTP tanpa token")

        with mock.patch.object(store, "_github_token", return_value=""), \
                mock.patch.dict("sys.modules", {"requests": _Requests()}):
            self.assertFalse(store.push_json("x.json", {}, "m"))
        self.assertEqual(calls, [])

    def test_push_creates_file_when_absent(self):
        seen = {}

        class _Get:
            status_code = 404

            @staticmethod
            def json():
                return {}

        class _Put:
            status_code = 201

        class _Requests:
            @staticmethod
            def get(url, headers=None, timeout=None):
                seen["url"] = url
                return _Get()

            @staticmethod
            def put(url, headers=None, json=None, timeout=None):
                seen["payload"] = json
                return _Put()

        with mock.patch.object(store, "_github_token", return_value="tok"), \
                mock.patch.dict("sys.modules", {"requests": _Requests()}):
            self.assertTrue(store.push_json("sweep_state.json", {"a": 1}, "m"))
        self.assertIn("/contents/sweep_state.json", seen["url"])
        self.assertNotIn("sha", seen["payload"])
        self.assertEqual(seen["payload"]["message"], "m")

    def test_push_updates_existing_file_with_sha(self):
        seen = {}

        class _Get:
            status_code = 200

            @staticmethod
            def json():
                return {"sha": "abc123"}

        class _Put:
            status_code = 200

        class _Requests:
            @staticmethod
            def get(url, headers=None, timeout=None):
                return _Get()

            @staticmethod
            def put(url, headers=None, json=None, timeout=None):
                seen["payload"] = json
                return _Put()

        with mock.patch.object(store, "_github_token", return_value="tok"), \
                mock.patch.dict("sys.modules", {"requests": _Requests()}):
            self.assertTrue(store.push_json("x.json", {}, "m"))
        self.assertEqual(seen["payload"]["sha"], "abc123")

    def test_push_returns_false_on_network_error(self):
        class _Boom:
            def __init__(self, *a, **k):
                pass

            def get(self, *a, **k):
                raise RuntimeError("offline")

        with mock.patch.object(store, "_github_token", return_value="tok"), \
                mock.patch.dict("sys.modules", {"requests": _Boom()}):
            self.assertFalse(store.push_json("x.json", {}, "m"))


if __name__ == "__main__":
    unittest.main()
