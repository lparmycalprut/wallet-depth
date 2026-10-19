# -*- coding: utf-8 -*-
"""Snapshot terakhir per mint (view) + urutan tabel Sweep — offline.

Halaman Sweep dibuka dengan menampilkan view yang tersimpan di snapshot
terbaru tiap mint watchlist, tanpa memindai ulang jaringan.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

import sweep_scan as scan
import sweep_store as store
import sweep_ui as ui

from tests.test_sweep_scan import MINT, _Sandbox

OTHER = "EcZndAERfzNhLirHwfsy44dAyPSZazjDU83pa6RApump"


_DELTA_PATCH = None


def setUpModule():
    global _DELTA_PATCH
    import _offline_delta
    _DELTA_PATCH = _offline_delta.start()


def tearDownModule():
    if _DELTA_PATCH is not None:
        _DELTA_PATCH.stop()


class ViewPersistenceTest(_Sandbox):
    def test_scan_attaches_view_to_latest_snapshot(self):
        state = store.empty_state()
        scan.run_scan([MINT], state=state, send_alerts=False, now=1000)
        view = store.latest_view(state, MINT)
        self.assertIsNotNone(view)
        self.assertEqual(view["mint"], MINT)
        self.assertEqual(view["ts"], 1000)
        self.assertEqual(view["metrics"]["symbol"], "COCKROACH")
        self.assertIn("verdict", view["result"])
        self.assertIn("cohort_gate_status", view["result"])
        # Candle mentah tidak ikut masuk ke state.
        self.assertNotIn("candles_hour", view)
        self.assertNotIn("holder_pcts", view["metrics"])

    def test_only_latest_snapshot_keeps_a_view(self):
        state = store.empty_state()
        scan.run_scan([MINT], state=state, send_alerts=False, now=1000)
        scan.run_scan([MINT], state=state, send_alerts=False, now=1000 + 7200)
        buckets = state["snapshots"][MINT]
        self.assertEqual(len(buckets), 2)
        with_view = [b for b in buckets.values() if "view" in b]
        self.assertEqual(len(with_view), 1)
        self.assertEqual(store.latest_view(state, MINT)["ts"], 1000 + 7200)

    def test_view_survives_json_round_trip(self):
        state = store.empty_state()
        scan.run_scan([MINT], state=state, send_alerts=False, now=1000)
        restored = json.loads(json.dumps(state))
        self.assertEqual(store.latest_view(restored, MINT)["ts"], 1000)

    def test_watchlist_views_follow_watchlist_order_and_report_missing(self):
        state = store.empty_state()
        scan.run_scan([MINT], state=state, send_alerts=False, now=1000)
        views, missing = store.watchlist_views(state, [OTHER, MINT])
        self.assertEqual([v["mint"] for v in views], [MINT])
        self.assertEqual(missing, [OTHER])

    def test_removed_mint_is_not_listed_even_with_old_snapshot(self):
        state = store.empty_state()
        scan.run_scan([MINT], state=state, send_alerts=False, now=1000)
        views, missing = store.watchlist_views(state, [])
        self.assertEqual(views, [])
        self.assertEqual(missing, [])


class RemoveFromTableTest(unittest.TestCase):
    def test_only_checked_rows_are_picked(self):
        rows = [{"mint": "A"}, {"mint": "B"}, {"mint": "C"}]
        self.assertEqual(ui._flagged_mints(rows, [False, True, False]), {"B"})
        self.assertEqual(ui._flagged_mints(rows, []), set())

    def test_removal_keeps_rest_of_watchlist(self):
        import os
        import tempfile
        tmp = tempfile.mkdtemp(prefix="sweep-remove-")
        with mock.patch.object(store, "WATCHLIST_PATH",
                               os.path.join(tmp, "wl.json")), \
                mock.patch.object(store, "CONFIG_PATH",
                                  os.path.join(tmp, "config.json")), \
                mock.patch.object(store, "push_watchlist", return_value=True):
            store.save_watchlist([MINT, OTHER], persist=False)
            remaining = [m for m in store.load_watchlist() if m != MINT]
            store.save_watchlist(remaining, persist=False)
            self.assertEqual(store.load_watchlist(), [OTHER])


if __name__ == "__main__":
    unittest.main()
