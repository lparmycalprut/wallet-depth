# -*- coding: utf-8 -*-
"""Refresh Sweep di background: run Streamlit tidak menunggu pemindaian.

Permintaan user 2026-10-27: halaman tidak blur saat refresh data. Streamlit
meredupkan elemen yang belum dirender ulang setelah 0,5 detik, jadi run utama
harus selesai cepat walaupun pemindaian masih berjalan.
"""
import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sweep_scan as scan  # noqa: E402
import sweep_store as store  # noqa: E402
import sweep_ui as ui  # noqa: E402


def _outcome(state, rows=None, elapsed=0.01):
    return {"state": state, "rows": rows or [], "alerts": [], "elapsed": elapsed}


class BackgroundJobTests(unittest.TestCase):
    def setUp(self):
        self.fake = types.SimpleNamespace(
            session_state={"sweep_state": store.empty_state()})
        self.patch_st = mock.patch.object(ui, "st", self.fake)
        self.patch_st.start()

    def tearDown(self):
        self.patch_st.stop()

    def _wait(self):
        job = self.fake.session_state[ui.BG_JOB_KEY]
        self.assertTrue(job.done.wait(5), "job tidak selesai")
        return job

    def test_second_start_refused_while_running(self):
        gate = threading.Event()

        def slow(mints, **kw):
            gate.wait(5)
            return _outcome(kw["state"])

        with mock.patch.object(scan, "run_scan", side_effect=slow):
            self.assertTrue(ui._start_scan_job(["M"], kind="manual"))
            self.assertTrue(ui._job_running())
            self.assertFalse(ui._start_scan_job(["N"], kind="manual"))
            gate.set()
            self._wait()

    def test_manual_job_applies_state_meta_and_flash(self):
        new_state = store.empty_state()
        new_state["updated"] = 123
        with mock.patch.object(scan, "run_scan",
                               return_value=_outcome(new_state, elapsed=2.5)):
            self.assertTrue(ui._start_scan_job(["M1", "M2"], kind="manual",
                                               label="manual"))
            self._wait()
        self.assertTrue(ui._apply_finished_job())
        self.assertNotIn(ui.BG_JOB_KEY, self.fake.session_state)
        self.assertEqual(self.fake.session_state["sweep_state"]["updated"], 123)
        meta = self.fake.session_state[ui.SCAN_META_KEY]
        self.assertEqual((meta["n"], meta["kind"]), (2, "manual"))
        kind, message = self.fake.session_state["sweep_flash"][0]
        self.assertEqual(kind, "success")
        self.assertIn("2 mint", message)
        self.assertFalse(ui._apply_finished_job())  # tidak ada lagi yang diterapkan

    def test_failed_job_keeps_previous_snapshot_and_warns(self):
        before = self.fake.session_state["sweep_state"]
        with mock.patch.object(scan, "run_scan",
                               side_effect=RuntimeError("gmgn down")):
            self.assertTrue(ui._start_scan_job(["M"], kind="retry",
                                               use_cache=False))
            self._wait()
        self.assertTrue(ui._apply_finished_job())
        self.assertIs(self.fake.session_state["sweep_state"], before)
        kind, message = self.fake.session_state["sweep_flash"][0]
        self.assertEqual(kind, "warning")
        self.assertIn("gmgn down", message)

    def test_auto_saves_only_when_fingerprint_changes(self):
        self.fake.session_state[ui.FINGERPRINT_KEY] = "fingerprint-lama"
        with mock.patch.object(scan, "run_scan",
                               return_value=_outcome(store.empty_state())), \
                mock.patch.object(store, "save_state") as save:
            self.assertTrue(ui._start_scan_job(["M"], kind="auto", persist=False,
                                               label="auto-refresh"))
            job = self._wait()
        self.assertEqual(save.call_count, 1)
        self.assertTrue(ui._apply_finished_job())
        self.assertEqual(self.fake.session_state[ui.FINGERPRINT_KEY], job.fingerprint)

    def test_first_auto_run_does_not_save(self):
        with mock.patch.object(scan, "run_scan",
                               return_value=_outcome(store.empty_state())), \
                mock.patch.object(store, "save_state") as save:
            ui._start_scan_job(["M"], kind="auto", persist=False, label="auto-refresh")
            self._wait()
        self.assertEqual(save.call_count, 0)


class PageStaysResponsiveTests(unittest.TestCase):
    """Run Streamlit selesai cepat walau pemindaian background belum selesai."""

    def test_refresh_click_does_not_wait_for_scan(self):
        from streamlit.testing.v1 import AppTest

        gate = threading.Event()

        def slow(mints, **kw):
            gate.wait(10)
            return _outcome(kw["state"], elapsed=1.0)

        page = os.path.join(ROOT, "pages", "8_🌊_Sweep.py")
        with mock.patch.object(scan, "run_scan", side_effect=slow):
            try:
                at = AppTest.from_file(page, default_timeout=30)
                at.run()
                buttons = [b for b in at.button if "Refresh & ambil" in str(b.label)]
                self.assertTrue(buttons, "tombol Refresh tidak ditemukan")
                buttons[0].click()
                started = time.time()
                at.run()
                elapsed = time.time() - started
                self.assertLess(elapsed, 5, f"run menunggu scan ({elapsed:.1f}s)")
                captions = " ".join(str(c.value) for c in at.caption)
                self.assertIn("background", captions)
            finally:
                gate.set()


if __name__ == "__main__":
    unittest.main()
