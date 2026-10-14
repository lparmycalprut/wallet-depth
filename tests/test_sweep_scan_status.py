# -*- coding: utf-8 -*-
"""Scan gagal (fetch data error) tidak boleh disembunyikan (permintaan user 2026-10-14).

Scan yang gagal tidak menyimpan view baru, jadi view sukses lama bisa tetap
tampil. Tes ini memastikan kegagalan tercatat, baris ditandai, dan tidak
pernah tersembunyi oleh filter tampilan.
Juga memastikan latch kohort ikut tersimpan dan digabung (sebelumnya hilang).
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

import sweep_scan as scan
import sweep_screen as ss
import sweep_store as store


def _stale_hidden_state(mint="M"):
    """State dengan view sukses lama yang MEMENUHI filter (× dana acuan 10x = 5×)."""
    state = store.empty_state()
    state["snapshots"] = {mint: {"1000": {"ts": 1000, "price": 1.0}}}
    view = store.make_view(mint, {"ok": True, "symbol": "OLD"},
                           {"reference_fund_x": 5.0}, ts=1000)
    store.set_view(state, mint, state["snapshots"][mint]["1000"], view)
    return state


class ScanFailureNotHiddenTest(unittest.TestCase):
    def test_stale_view_is_hidden_without_failure_flag(self):
        # Baseline: view lama yang memenuhi filter memang disembunyikan.
        views, _ = store.watchlist_views(_stale_hidden_state(), ["M"])
        self.assertTrue(ss.view_hidden(views[0]))
        self.assertNotIn("scan_error", views[0])

    def test_failed_scan_keeps_row_visible_and_flagged(self):
        state = _stale_hidden_state()
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=RuntimeError("GeckoTerminal HTTP 429")):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=2000)
        failure = store.scan_failure(state, "M")
        self.assertIsNotNone(failure)
        self.assertIn("429", failure["error"])
        views, _ = store.watchlist_views(state, ["M"])
        self.assertEqual(views[0]["scan_error"]["error"], failure["error"])
        self.assertFalse(ss.view_hidden(views[0]))
        # View di state tidak ikut dimodifikasi (hanya salinan yang diberi tanda).
        self.assertNotIn("scan_error", store.latest_view(state, "M"))

    def test_successful_scan_clears_failure(self):
        state = _stale_hidden_state()
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=RuntimeError("timeout")):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=2000)
        self.assertIsNotNone(store.scan_failure(state, "M"))
        store.record_scan_status(state, "M", ok=True, ts=3000)
        self.assertIsNone(store.scan_failure(state, "M"))
        views, _ = store.watchlist_views(state, ["M"])
        self.assertNotIn("scan_error", views[0])

    def test_failed_mint_without_view_is_reported_as_missing_with_status(self):
        state = store.empty_state()
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=RuntimeError("DexScreener timeout")):
            scan.run_scan(["N"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=2000)
        views, missing = store.watchlist_views(state, ["N"])
        self.assertEqual(views, [])
        self.assertEqual(missing, ["N"])
        self.assertIsNotNone(store.scan_failure(state, "N"))

    def test_view_hidden_never_hides_scan_error_row(self):
        row = {"scan_error": {"ts": 1, "ok": False, "error": "x"},
               "result": {"reference_fund_x": 9.0},
               "metrics": {"top_bundler_trader_percentage": 0.01}}
        self.assertFalse(ss.view_hidden(row))


class LatchPersistenceTest(unittest.TestCase):
    def test_cohort_latch_survives_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "sweep_state.json"
            with mock.patch.object(store, "STATE_PATH", path):
                state = store.empty_state()
                state["cohort_latched"] = {"M": {"ts": 1234, "source": "live"}}
                store.save_state(state, persist=False)
                loaded = store.load_state()
        self.assertEqual(loaded["cohort_latched"], {"M": {"ts": 1234, "source": "live"}})

    def test_merge_keeps_earliest_cohort_latch_and_newest_scan_status(self):
        local = store.empty_state()
        remote = store.empty_state()
        remote["cohort_latched"] = {"M": {"ts": 500, "source": "riwayat"}}
        local["cohort_latched"] = {"M": {"ts": 900, "source": "live"},
                                   "K": {"ts": 700, "source": "live"}}
        remote["scan_status"] = {"M": {"ts": 100, "ok": False, "error": "old"}}
        local["scan_status"] = {"M": {"ts": 200, "ok": True, "error": ""}}
        merged = store.merge_states(local, remote)
        self.assertEqual(merged["cohort_latched"]["M"]["ts"], 500)
        self.assertEqual(merged["cohort_latched"]["K"]["ts"], 700)
        self.assertTrue(merged["scan_status"]["M"]["ok"])


if __name__ == "__main__":
    unittest.main()
