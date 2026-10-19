# -*- coding: utf-8 -*-
"""Perbaikan 2026-10-14: sinyal sweep per candle, leverage dari MC dasar,
dan tampilan waktu WIB.

Angka berasal dari fixture COCKROACH di ``test_sweep_scan`` (stub jaringan).
"""
from __future__ import annotations

import pathlib
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import rugchecker
import sweep_scan as scan
import sweep_screen as ss
import sweep_store as store
from tests.test_sweep_scan import BUNDLE, MINT

ROOT = pathlib.Path(__file__).resolve().parent.parent
WIB = timezone(timedelta(hours=7))


_DELTA_PATCH = None


def setUpModule():
    global _DELTA_PATCH
    import _offline_delta
    _DELTA_PATCH = _offline_delta.start()


def tearDownModule():
    if _DELTA_PATCH is not None:
        _DELTA_PATCH.stop()


class LeverageFromBaseMcTest(unittest.TestCase):
    def test_leverage_equals_paper_gain_over_cost(self):
        # Base MC 233.451, supply tetap, harga naik 4x sampai puncak.
        base_price, supply = 0.0002377, 233451.0 / 0.0002377
        event = {"ts": 1_790_000_000, "base_price": base_price,
                 "close": base_price * 2, "peak": base_price * 4,
                 "low": base_price, "vol": 1000.0, "index": 5,
                 "mult": 2.0}
        ctx = ss.sweep_context(event, 30232.0 / 233451.0, 233451.0,
                               market_cap_usd=233451.0, price_usd=base_price,
                               liq_usd=30232.0)
        self.assertIsNotNone(ctx["leverage"])
        expected = ctx["paper_gain_usd"] / ctx["est_cost_usd"]
        self.assertAlmostEqual(ctx["leverage"], expected, places=6)
        # Dengan MC dasar, paper gain ÷ biaya = (√m+1)·MC_dasar·2/liq.
        self.assertAlmostEqual(ctx["leverage"],
                               (4 ** 0.5 + 1) * 233451.0 * 2 / 30232.0, places=3)

    def test_sweep_ts_is_candle_time(self):
        event = {"ts": 1_790_000_300, "base_price": 1.0, "close": 1.5,
                 "peak": 1.8, "low": 1.0, "vol": 10.0, "index": 3, "mult": 1.5}
        ctx = ss.sweep_context(event, 0.1, 1000.0, market_cap_usd=1000.0,
                               price_usd=1.0, liq_usd=100.0)
        self.assertEqual(ctx["sweep_ts"], 1_790_000_300)


class SweepSignalPerCandleTest(unittest.TestCase):
    def _run(self, state, *, now, send_alerts=True):
        with mock.patch.object(scan, "_fetch_bundle",
                               return_value=dict(BUNDLE)):
            return scan.run_scan([MINT], state=state, now=now,
                                 send_alerts=send_alerts)

    def test_signal_time_is_candle_time_not_scan_time(self):
        probe = scan.analyze(BUNDLE)
        candle_ts = probe["sweep"]["ts"]
        state = store.empty_state()
        with mock.patch.object(scan.alert, "send_message",
                               return_value=(True, "")) as send:
            self._run(state, now=candle_ts + 120)
        sweeps = [s for s in state["signals"] if s["kind"] == "sweep"]
        self.assertEqual(len(sweeps), 1)
        self.assertEqual(sweeps[0]["ts"], candle_ts)
        self.assertEqual(sweeps[0]["sweep_ts"], candle_ts)
        self.assertEqual(sweeps[0]["detected_ts"], candle_ts + 120)
        # Candle masih segar → alert sweep terkirim.
        self.assertTrue(send.called)

    def test_stale_candle_is_recorded_without_alert(self):
        probe = scan.analyze(BUNDLE)
        candle_ts = probe["sweep"]["ts"]
        state = store.empty_state()
        with mock.patch.object(scan.alert, "send_message",
                               return_value=(True, "")) as send:
            self._run(state, now=candle_ts + store.SWEEP_ALERT_MAX_AGE + 600)
        # Tidak ada alert sweep untuk candle yang sudah terlalu tua.
        self.assertFalse(send.called)
        sweeps = [s for s in state["signals"] if s["kind"] == "sweep"]
        self.assertEqual(len(sweeps), 1)
        self.assertEqual(sweeps[0]["alert_skipped"], "candle_terlalu_tua")

    def test_same_candle_not_recorded_twice_across_scans(self):
        probe = scan.analyze(BUNDLE)
        candle_ts = probe["sweep"]["ts"]
        state = store.empty_state()
        self._run(state, now=candle_ts + 60, send_alerts=False)
        self._run(state, now=candle_ts + 60 + 1800, send_alerts=False)
        sweeps = [s for s in state["signals"] if s["kind"] == "sweep"]
        self.assertEqual(len(sweeps), 1)


class FindSweepSignalTest(unittest.TestCase):
    def test_legacy_signal_matched_by_entry_price(self):
        state = {"signals": [{"kind": "sweep", "mint": "M", "ts": 5000,
                              "entry_price": 0.25}]}
        self.assertIsNotNone(store.find_sweep_signal(
            state, "M", {"sweep_ts": 1000, "close": 0.25}))
        self.assertIsNone(store.find_sweep_signal(
            state, "M", {"sweep_ts": 1000, "close": 0.26}))
        self.assertIsNone(store.find_sweep_signal(
            state, "X", {"sweep_ts": 1000, "close": 0.25}))

    def test_backfill_only_fills_missing_net_inflow(self):
        signal = {"kind": "sweep", "net_inflow_usd": None}
        ctx = {"net_inflow_usd": 100.0, "churn_net_x": 2.0, "leverage_net": 3.0}
        self.assertTrue(store.backfill_sweep_inflow(signal, ctx, measured_at=9))
        self.assertEqual(signal["net_inflow_usd"], 100.0)
        self.assertEqual(signal["net_measured_at"], 9)
        # Angka yang sudah terukur tidak ditimpa.
        self.assertFalse(store.backfill_sweep_inflow(
            signal, {"net_inflow_usd": 999.0}, measured_at=10))
        self.assertEqual(signal["net_inflow_usd"], 100.0)


class TokenCriterionDisplayTest(unittest.TestCase):
    def test_token_mc_check_lists_as_first_structural_key(self):
        self.assertEqual(ss.ELIGIBLE_STRUCTURAL[0], "token_mc")
        self.assertEqual(ss.CRITERIA_KEYS[0][0], "token_mc")
        self.assertNotIn("liq_mc", ss.ELIGIBLE_STRUCTURAL)


class WibDisplayTest(unittest.TestCase):
    def test_rugchecker_time_is_wib(self):
        # 2026-10-14 00:30 UTC = 07:30 WIB.
        ts = datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc).timestamp()
        self.assertEqual(rugchecker._fmt_wib_hm(ts), "07:30")
        # Epoch 0 = 00:00 UTC = 07:00 WIB.
        self.assertEqual(rugchecker._fmt_wib_hm(None), "07:00")

    def test_no_server_local_time_left_in_display_code(self):
        for name in ("sweep_ui.py", "rugchecker.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("time.localtime", source, name)
            self.assertNotIn("time.gmtime", source, name)
            self.assertNotIn("time.strftime('%H:%M:%S')", source, name)


if __name__ == "__main__":
    unittest.main()
