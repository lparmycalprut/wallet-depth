# -*- coding: utf-8 -*-
"""Penggabungan state cron vs app (:func:`sweep_store.merge_states`).

Kontrak yang dikunci: snapshot jam dari penulis lain tidak boleh hilang, dan
state yang tidak bisa dibaca dari GitHub tidak boleh menimpa remote.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import sweep_store as store


def _row(ts, price):
    return {"ts": ts, "price": price}


class MergeStatesTest(unittest.TestCase):
    def test_union_of_mints_and_hour_buckets_keeps_both_writers(self):
        remote = {"snapshots": {"M": {"3600": _row(3700, 1.0)}}}
        local = {"snapshots": {"M": {"7200": _row(7300, 2.0)},
                               "N": {"7200": _row(7300, 9.0)}}}
        merged = store.merge_states(local, remote)
        self.assertEqual(set(merged["snapshots"]["M"]), {"3600", "7200"})
        self.assertIn("N", merged["snapshots"])

    def test_same_bucket_keeps_newer_row(self):
        remote = {"snapshots": {"M": {"3600": _row(3900, 1.0)}}}
        local = {"snapshots": {"M": {"3600": _row(3700, 2.0)}}}
        merged = store.merge_states(local, remote)
        self.assertEqual(merged["snapshots"]["M"]["3600"]["price"], 1.0)
        local_newer = {"snapshots": {"M": {"3600": _row(4000, 3.0)}}}
        merged = store.merge_states(local_newer, remote)
        self.assertEqual(merged["snapshots"]["M"]["3600"]["price"], 3.0)

    def test_signals_union_by_id_and_capped(self):
        remote = {"signals": [{"id": "a", "ts": 1, "outcome": "old"}]}
        local = {"signals": [{"id": "a", "ts": 1, "outcome": "new"},
                             {"id": "b", "ts": 2}]}
        merged = store.merge_states(local, remote)
        self.assertEqual([s["id"] for s in merged["signals"]], ["a", "b"])
        self.assertEqual(merged["signals"][0]["outcome"], "new")
        many = {"signals": [{"id": str(i), "ts": i}
                            for i in range(store.MAX_SIGNALS + 5)]}
        self.assertEqual(len(store.merge_states(many, {})["signals"]),
                         store.MAX_SIGNALS)

    def test_latch_keeps_earliest_and_alert_numbers_never_go_back(self):
        remote = {"shakeout_latched_at": {"M": 500},
                  "alerts": {"M": {"last_sweep_ts": 900, "eligibility": True}}}
        local = {"shakeout_latched_at": {"M": 700, "N": 100},
                 "alerts": {"M": {"last_sweep_ts": 300, "eligibility": False}}}
        merged = store.merge_states(local, remote)
        self.assertEqual(merged["shakeout_latched_at"], {"M": 500, "N": 100})
        self.assertEqual(merged["alerts"]["M"]["last_sweep_ts"], 900)
        self.assertFalse(merged["alerts"]["M"]["eligibility"])

    def test_updated_is_max_and_empty_remote_is_fine(self):
        merged = store.merge_states({"updated": 10, "snapshots": {}},
                                    {"updated": 25})
        self.assertEqual(merged["updated"], 25)
        self.assertEqual(store.merge_states({"snapshots": {"M": {}}}, {})
                         ["snapshots"], {"M": {}})


class SaveStatePersistTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sweep-merge-")
        self.state_path = os.path.join(self.dir, "sweep_state.json")
        patcher = mock.patch.object(store, "STATE_PATH", self.state_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _local_state(self):
        state = store.empty_state()
        store.add_snapshot(state, "LOCAL", {"price_usd": 2.0, "ts": 7300})
        return state

    def test_persist_merges_remote_before_pushing(self):
        remote = {"snapshots": {"CRON": {"3600": _row(3700, 1.0)}}}
        with mock.patch.object(store, "fetch_remote_state", return_value=remote), \
             mock.patch.object(store, "push_state", return_value=True) as push:
            saved = store.save_state(self._local_state(), persist=True)
        self.assertIn("CRON", saved["snapshots"])
        self.assertIn("LOCAL", saved["snapshots"])
        pushed = push.call_args[0][0]
        self.assertIn("CRON", pushed["snapshots"])
        with open(self.state_path, encoding="utf-8") as handle:
            self.assertIn("CRON", json.load(handle)["snapshots"])

    def test_unreadable_remote_writes_locally_but_never_pushes(self):
        with mock.patch.object(store, "fetch_remote_state", return_value=None), \
             mock.patch.object(store, "push_state") as push:
            store.save_state(self._local_state(), persist=True)
        push.assert_not_called()
        with open(self.state_path, encoding="utf-8") as handle:
            self.assertIn("LOCAL", json.load(handle)["snapshots"])

    def test_non_persist_does_not_touch_remote(self):
        with mock.patch.object(store, "fetch_remote_state") as fetch, \
             mock.patch.object(store, "push_state") as push:
            store.save_state(self._local_state())
        fetch.assert_not_called()
        push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
