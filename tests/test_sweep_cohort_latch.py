# -*- coding: utf-8 -*-
"""Latch kohort Sweep (2026-10-14): sekali kohort <= -50% tercatat, tetap lolos.

Kohort dihitung dari harga SEKARANG (VWAP 48 jam tetap, harga bergerak), jadi tanpa
latch token yang sempat <= -50% lalu naik kembali akan kembali TUNGGU.
"""
from __future__ import annotations

import pathlib
import unittest

import sweep_screen as ss
from tests.test_sweep_screen import _birth_candles

NOW = 1000 + 49 * 3600


def _metrics(price, basis=1.0, balance=1.0):
    return {"mint": "M", "price_usd": price, "pair_created_at": 1000,
            "holder_cost_basis": basis, "holder_cost_balance": balance,
            "liq_usd": 1000.0, "fdv_usd": 10000.0,
            "mint_authority": None, "freeze_authority": None,
            "top10_holder_pct": 18.0, "holder_pcts": [2.0]}


class CohortLatchEvaluateTest(unittest.TestCase):
    def test_latch_turns_belum_minus_into_lolos(self):
        # VWAP 1,0; harga kini 0,7 -> minus 30% (belum 50%).
        now_only = ss.evaluate(_metrics(0.7), cohort_candles=_birth_candles(),
                               now=NOW)
        self.assertEqual(now_only["cohort_gate_status"],
                         "TUNGGU — kohort belum minus 50%")
        self.assertFalse(now_only["cohort_gate_passed"])
        latched = ss.evaluate(_metrics(0.7), cohort_candles=_birth_candles(),
                              now=NOW,
                              cohort_latch={"ts": 1000, "source": "riwayat"})
        self.assertTrue(latched["cohort_gate_passed"])
        self.assertIn("latch", latched["cohort_gate_status"])
        self.assertIn("pernah ≤ −50%", latched["cohort_gate_status"])

    def test_latch_does_not_override_plus(self):
        # Harga di atas VWAP = kohort PLUS -> tetap SKIP walau pernah latch.
        result = ss.evaluate(_metrics(1.2), cohort_candles=_birth_candles(),
                             now=NOW, cohort_latch={"ts": 1000, "source": "live"})
        self.assertFalse(result["cohort_gate_passed"])
        self.assertTrue(result["cohort_gate_status"].startswith("SKIP"))

    def test_no_latch_keeps_old_behaviour(self):
        result = ss.evaluate(_metrics(0.7), cohort_candles=_birth_candles(), now=NOW)
        self.assertFalse(result["cohort_gate_passed"])


class CohortLatchHistoryTest(unittest.TestCase):
    def test_history_snapshot_meeting_both_thresholds_latches(self):
        history = [{"ts": 3600, "price": 0.9}, {"ts": 7200, "price": 0.45}]
        found = ss.cohort_latch_from_history(history, 1.0, 1.0, 1.0)
        self.assertEqual(found["ts"], 7200)
        self.assertEqual(found["source"], "riwayat")

    def test_vwap_minus_50_alone_is_not_enough(self):
        # Harga 0,45 = VWAP -55%, tapi avg buy GMGN 0,5 -> GMGN hanya -10%.
        history = [{"ts": 7200, "price": 0.45}]
        self.assertIsNone(ss.cohort_latch_from_history(history, 1.0, 0.5, 1.0))

    def test_missing_data_never_latches(self):
        history = [{"ts": 7200, "price": 0.45}]
        self.assertIsNone(ss.cohort_latch_from_history(history, None, 1.0, 1.0))
        self.assertIsNone(ss.cohort_latch_from_history(history, 1.0, None, None))
        self.assertIsNone(ss.cohort_latch_from_history([], 1.0, 1.0, 1.0))


class ScanWiringTest(unittest.TestCase):
    def test_run_scan_persists_and_passes_cohort_latch(self):
        source = (pathlib.Path(__file__).resolve().parent.parent
                  / "sweep_scan.py").read_text(encoding="utf-8")
        self.assertIn('state.setdefault("cohort_latched", {})', source)
        self.assertIn("cohort_latch=cohort_latches.get(mint)", source)


if __name__ == "__main__":
    unittest.main()


class RunScanLatchIntegrationTest(unittest.TestCase):
    """run_scan end-to-end dengan bundel palsu: riwayat pernah -50%, harga kini naik."""

    def _bundle(self, price):
        metrics = _metrics(price)
        metrics.update({"ok": True, "pair_address": "P", "ts": NOW})
        return {"mint": "M", "metrics": metrics, "candles_hour": [],
                "candles_min5": [], "cohort_candles": _birth_candles(),
                "cohort_error": ""}

    def _run(self, price, history_price):
        import sweep_scan
        from unittest import mock
        state = {"snapshots": {"M": {
            "h1": {"ts": NOW - 7200, "price": history_price,
                   "liq_usd": 1000.0, "fdv_usd": 10000.0}}}}
        with mock.patch.object(sweep_scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: self._bundle(price)):
            out = sweep_scan.run_scan(["M"], state=state, use_cache=False,
                                      send_alerts=False, workers=1, now=NOW)
        return out, state

    def test_history_latch_persists_and_passes_after_price_rise(self):
        out, state = self._run(price=0.7, history_price=0.45)
        self.assertIn("M", state["cohort_latched"])
        self.assertEqual(state["cohort_latched"]["M"]["source"], "riwayat")
        row = out["rows"][0]
        self.assertTrue(row["result"]["cohort_gate_passed"])

    def test_without_history_price_rise_stays_waiting(self):
        out, state = self._run(price=0.7, history_price=0.8)
        self.assertNotIn("M", state["cohort_latched"])
        self.assertFalse(out["rows"][0]["result"]["cohort_gate_passed"])
