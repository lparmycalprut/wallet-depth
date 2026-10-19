# -*- coding: utf-8 -*-
"""Delta dan CVD dari trade GMGN (info saja, 2026-10-15)."""
from __future__ import annotations

import unittest
from unittest import mock

import cvd
import sweep_scan as scan
import sweep_screen as ss

H = 3600
NOW = 1_700_000_000 - (1_700_000_000 % H) + 1800  # tengah jam


END = NOW - (NOW % H)  # awal jam terakhir = bucket terakhir jendela


def _candles(closes_by_hour):
    # closes_by_hour: {j: close}; j = 0,1,2 → jam E−2, E−1, E (E = jam terakhir).
    out = []
    for j, price in sorted(closes_by_hour.items()):
        ts = END - (2 - j) * H
        out.append([ts, price, price, price, price, 1.0])
    return out


def _at(j, offset=5):
    # Waktu trade di jam ke-j relatif jam terakhir (j = 0,1,2).
    return END - (2 - j) * H + offset


def _start_hour():
    return NOW - (NOW % H) - (ss.DELTA_WINDOW_HOURS - 1) * H


class DeltaInfoTest(unittest.TestCase):
    def test_delta_and_cvd_accumulate_per_hour(self):
        s = _start_hour()
        trades = [("buy", 100.0, s + 10), ("sell", 300.0, s + H + 10),
                  ("buy", 50.0, s + H + 20)]
        info = ss.delta_info(trades, _candles({0: 1.0}), now=NOW)
        self.assertTrue(info["available"])
        self.assertEqual(info["trades"], 3)
        self.assertAlmostEqual(info["buy_usd"], 150.0)
        self.assertAlmostEqual(info["sell_usd"], 300.0)
        self.assertAlmostEqual(info["cvd_usd"], -150.0)  # 100 − 300 + 50
        buckets = {b["ts"]: b for b in info["buckets"]}
        self.assertAlmostEqual(buckets[s]["delta"], 100.0)
        self.assertAlmostEqual(buckets[s + H]["cvd"], -150.0)

    def test_quiet_hours_are_zero_delta(self):
        s = _start_hour()
        info = ss.delta_info([("buy", 10.0, s + 5)], [], now=NOW)
        self.assertEqual(len(info["buckets"]), ss.DELTA_WINDOW_HOURS)
        self.assertEqual(info["buckets"][-1]["delta"], 0.0)

    def test_invalid_and_out_of_window_trades_ignored(self):
        s = _start_hour()
        trades = [("hold", 10.0, s + 5), ("buy", 0.0, s + 5), ("buy", -5.0, s + 5),
                  ("buy", 10.0, s - H), ("buy", 10.0, NOW + H), ("buy", "x", s + 5),
                  ("buy", 25.0, s + 5)]
        info = ss.delta_info(trades, [], now=NOW)
        self.assertEqual(info["trades"], 1)
        self.assertAlmostEqual(info["buy_usd"], 25.0)

    def test_no_trades_complete_or_not(self):
        complete = ss.delta_info([], [], now=NOW, complete=True)
        partial = ss.delta_info([], [], now=NOW, complete=False)
        self.assertFalse(complete["available"])
        self.assertIn("tidak ada trade", complete["reason"])
        self.assertIn("tidak lengkap", partial["reason"])
        self.assertFalse(partial["complete"])

    def test_bearish_divergence_new_high_lower_cvd(self):
        s = _start_hour()
        trades = [("buy", 1000.0, _at(0)),    # jam E−2: CVD 1000, harga 1,0
                  ("buy", 1000.0, _at(1)),    # jam E−1: CVD 2000, harga 1,2 (high)
                  ("sell", 3000.0, _at(2))]   # jam E: CVD −1000, harga 1,3 (high baru)
        info = ss.delta_info(trades, _candles({0: 1.0, 1: 1.2, 2: 1.3}), now=NOW)
        self.assertIn("div_bearish", info["flags"])
        self.assertIn("divergensi bearish", info["labels"][0])

    def test_no_divergence_when_cvd_also_makes_high(self):
        s = _start_hour()
        trades = [("buy", 1000.0, _at(0)), ("buy", 1000.0, _at(1)),
                  ("buy", 1000.0, _at(2))]
        info = ss.delta_info(trades, _candles({0: 1.0, 1: 1.2, 2: 1.3}), now=NOW)
        self.assertNotIn("div_bearish", info["flags"])

    def test_absorption_strong_buy_falling_price(self):
        s = _start_hour()
        trades = [("buy", 800.0, _at(2)), ("sell", 200.0, _at(2, 9))]
        info = ss.delta_info(trades, _candles({0: 1.0, 1: 1.0, 2: 0.95}), now=NOW)
        self.assertIn("absorb", info["flags"])
        self.assertNotIn("spike_no_progress", info["flags"])

    def test_spike_without_price_progress(self):
        s = _start_hour()
        trades = [("sell", 900.0, _at(2)), ("buy", 100.0, _at(2, 9))]
        info = ss.delta_info(trades, _candles({0: 1.0, 1: 1.0, 2: 1.005}), now=NOW)
        self.assertIn("spike_no_progress", info["flags"])
        self.assertNotIn("absorb", info["flags"])

    def test_no_flags_without_prices(self):
        s = _start_hour()
        info = ss.delta_info([("buy", 800.0, s + 2 * H + 5)], [], now=NOW)
        self.assertEqual(info["flags"], [])


class DeltaCandidateTest(unittest.TestCase):
    def test_candidates_are_tunggu_and_lolos(self):
        for status in ("TUNGGU — kohort belum minus 50%", "TUNGGU — kohort GMGN plus",
                       "LOLOS", "LOLOS — pernah ≤ −50% (latch)"):
            self.assertTrue(ss.delta_candidate({"cohort_gate_status": status}), status)

    def test_non_candidates(self):
        for status in ("SKIP — kohort plus", "TANPA DATA — kohort", "MENUNGGU SNAPSHOT"):
            self.assertFalse(ss.delta_candidate({"cohort_gate_status": status}), status)
        self.assertFalse(ss.delta_candidate({"cohort_gate_status": "LOLOS",
                                             "verdict": "TIDAK LAYAK"}))


class DeltaForResultTest(unittest.TestCase):
    CANDIDATE = {"cohort_gate_status": "TUNGGU — kohort belum minus 50%"}

    def test_non_candidate_skips_fetch(self):
        calls = []

        def fake(*args):
            calls.append(args)
            return [], True

        out = scan.delta_for_result("M", {"cohort_gate_status": "SKIP — kohort plus"},
                                    candles=[], now=NOW, fetch=fake)
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_candidate_fetches_window_and_computes(self):
        s = _start_hour()
        seen = {}

        def fake(mint, from_ts, to_ts):
            seen.update(mint=mint, from_ts=from_ts, to_ts=to_ts)
            return [("buy", 500.0, s + 5)], True

        out = scan.delta_for_result("MINT", self.CANDIDATE, candles=[],
                                    now=NOW, fetch=fake)
        self.assertEqual(seen["mint"], "MINT")
        self.assertEqual(seen["to_ts"], NOW)
        self.assertEqual(seen["from_ts"], NOW - ss.DELTA_WINDOW_HOURS * 3600)
        self.assertTrue(out["available"])
        self.assertTrue(out["complete"])
        self.assertAlmostEqual(out["cvd_usd"], 500.0)

    def test_fetch_error_does_not_raise(self):
        def boom(*_a):
            raise RuntimeError("GMGN mati")

        out = scan.delta_for_result("M", self.CANDIDATE, candles=[], now=NOW, fetch=boom)
        self.assertFalse(out["available"])
        self.assertIn("GMGN mati", out["reason"])


class GmgnTradesMappingTest(unittest.TestCase):
    def test_maps_swap_tuples_to_side_usd_ts(self):
        swaps = [("buy", 1.0, 1000, "w1", 0.1, 150.0, []),
                 ("sell", 2.0, 1100, "w2", 0.1, None, []),  # tanpa USD: dibuang
                 ("buy", 3.0, 1200, "w3", 0.1, 75.0, [])]
        with mock.patch.object(cvd, "fetch_gmgn_swaps",
                               return_value=(swaps, None, None, False)), \
                mock.patch.object(cvd, "get_gmgn_fetch_status",
                                  return_value={"complete": True}):
            trades, complete = scan._gmgn_trades_for_delta("M", 900, 1300)
        self.assertTrue(complete)
        self.assertEqual(trades, [("buy", 150.0, 1000), ("buy", 75.0, 1200)])

    def test_store_keeps_delta_and_order_flow_in_view(self):
        import sweep_store as store
        self.assertIn("delta", store.VIEW_RESULT_KEYS)
        self.assertIn("order_flow", store.VIEW_RESULT_KEYS)


if __name__ == "__main__":
    unittest.main()
