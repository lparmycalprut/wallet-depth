# -*- coding: utf-8 -*-
"""Sinyal bottom — info saja (permintaan user 2026-10-28).

Indikator: divergensi CVD bullish, token/MC berhenti naik, sisi quote pool
tahan, dan harga di atas low shakeout. Tidak boleh memengaruhi vonis.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sweep_bottom as bottom  # noqa: E402
import sweep_screen as screen  # noqa: E402
import sweep_store as store  # noqa: E402
import sweep_ui as ui  # noqa: E402

HOUR = 3600


def _bucket(i, price, cvd):
    return {"ts": 1_000_000 + i * HOUR, "delta": 0.0, "cvd": cvd, "price": price}


class CvdDivergenceTests(unittest.TestCase):
    def _delta(self, buckets):
        return {"available": True, "buckets": buckets, "complete": True}

    def test_new_low_with_higher_cvd_is_active(self):
        # Low sebelumnya di jam 1 (harga 8, CVD -300); sekarang harga 7,5 (low baru),
        # CVD -150 (lebih tinggi) -> divergensi bullish.
        item = bottom.cvd_divergence(self._delta([
            _bucket(0, 10.0, -100.0), _bucket(1, 8.0, -300.0),
            _bucket(2, 9.0, -200.0), _bucket(3, 7.5, -150.0)]))
        self.assertTrue(item["available"])
        self.assertTrue(item["active"])
        self.assertEqual(item["data"]["low_price"], 8.0)
        self.assertAlmostEqual(item["data"]["cvd_change"], 150.0)
        self.assertEqual(item["reason"], "")
        self.assertTrue(any("CVD" in line for line in item["lines"]))

    def test_price_not_at_new_low_is_not_active(self):
        item = bottom.cvd_divergence(self._delta([
            _bucket(0, 10.0, -100.0), _bucket(1, 8.0, -300.0),
            _bucket(2, 9.0, -200.0), _bucket(3, 8.5, -150.0)]))
        self.assertTrue(item["available"])
        self.assertFalse(item["active"])
        self.assertIn("belum: harga", item["reason"])

    def test_new_low_with_lower_cvd_is_not_active(self):
        item = bottom.cvd_divergence(self._delta([
            _bucket(0, 10.0, -100.0), _bucket(1, 8.0, -300.0),
            _bucket(2, 9.0, -200.0), _bucket(3, 7.5, -400.0)]))
        self.assertFalse(item["active"])
        self.assertIn("CVD tidak lebih tinggi", item["reason"])

    def test_equal_low_counts_as_new_low(self):
        item = bottom.cvd_divergence(self._delta([
            _bucket(0, 8.0, -300.0), _bucket(1, 9.0, -200.0), _bucket(2, 8.0, -100.0)]))
        self.assertTrue(item["active"])

    def test_missing_prices_are_unavailable_not_zero(self):
        # Delta lama tanpa harga per jam: tidak boleh dihitung sebagai divergensi.
        old = self._delta([{"ts": 1, "delta": 5.0, "cvd": 5.0},
                           {"ts": 2, "delta": 1.0, "cvd": 6.0},
                           {"ts": 3, "delta": 1.0, "cvd": 7.0}])
        item = bottom.cvd_divergence(old)
        self.assertFalse(item["available"])
        self.assertFalse(item["active"])
        self.assertIn("harga per jam belum cukup", item["reason"])

    def test_no_delta_or_unavailable_delta(self):
        self.assertIn("bukan kandidat", bottom.cvd_divergence(None)["reason"])
        item = bottom.cvd_divergence({"available": False, "reason": "tidak ada trade"})
        self.assertFalse(item["available"])
        self.assertIn("tidak ada trade", item["reason"])


class TokenMcStallTests(unittest.TestCase):
    def _rows(self, tmc_values, prices):
        return [{"ts": 1_000_000 + i * HOUR, "price": p, "token_mc": t}
                for i, (t, p) in enumerate(zip(tmc_values, prices))]

    def test_flat_token_mc_while_price_falls_is_active(self):
        tmc = [0.30, 0.31, 0.32, 0.30, 0.30, 0.30, 0.30, 0.30]
        prices = [1.0, 0.98, 0.96, 0.94, 0.93, 0.92, 0.90, 0.88]  # -5,4% dalam 3 jam
        item = bottom.token_mc_stall(self._rows(tmc, prices))
        self.assertTrue(item["active"])
        self.assertLessEqual(item["data"]["change_pp"], bottom.TMC_FLAT_PP)

    def test_rising_token_mc_is_not_active(self):
        tmc = [0.30] * 4 + [0.30, 0.31, 0.33, 0.36]
        prices = [1.0, 0.95, 0.9, 0.85, 0.8, 0.78, 0.75, 0.7]
        item = bottom.token_mc_stall(self._rows(tmc, prices))
        self.assertFalse(item["active"])
        self.assertIn("masih naik", item["reason"])

    def test_flat_token_mc_without_price_drop_is_not_active(self):
        tmc = [0.30] * 8
        prices = [1.0] * 8
        item = bottom.token_mc_stall(self._rows(tmc, prices))
        self.assertFalse(item["active"])

    def test_short_history_is_unavailable(self):
        item = bottom.token_mc_stall(self._rows([0.3, 0.3], [1.0, 0.9]))
        self.assertFalse(item["available"])

    def test_token_mc_falls_back_to_pool_and_fdv(self):
        rows = [{"ts": i, "price": 1.0 - 0.02 * i, "pool_base_usd": 30.0, "fdv_usd": 100.0}
                for i in range(5)]
        item = bottom.token_mc_stall(rows)
        self.assertTrue(item["available"])
        self.assertTrue(item["active"])


class PoolQuoteHoldTests(unittest.TestCase):
    def _rows(self, quotes, prices):
        # quote = liq_usd − pool_base_usd; pool_base_usd tetap 50.
        return [{"ts": i, "price": p, "liq_usd": q + 50.0, "pool_base_usd": 50.0}
                for i, (q, p) in enumerate(zip(quotes, prices))]

    def test_quote_held_while_price_falls_is_active(self):
        quotes = [100.0] * 7
        prices = [1.0, 0.98, 0.95, 0.92, 0.9, 0.88, 0.85]
        item = bottom.pool_quote_hold(self._rows(quotes, prices))
        self.assertTrue(item["active"])

    def test_quote_drained_is_not_active(self):
        quotes = [100.0, 95.0, 90.0, 85.0, 80.0, 78.0, 75.0]
        prices = [1.0, 0.95, 0.9, 0.85, 0.8, 0.78, 0.7]
        item = bottom.pool_quote_hold(self._rows(quotes, prices))
        self.assertFalse(item["active"])
        self.assertIn("sisi quote turun", item["reason"])

    def test_quote_held_but_price_not_falling_enough_is_not_active(self):
        quotes = [100.0] * 7
        prices = [1.0, 1.0, 0.99, 0.99, 0.98, 0.98, 0.97]
        item = bottom.pool_quote_hold(self._rows(quotes, prices))
        self.assertFalse(item["active"])


class ShakeoutHoldTests(unittest.TestCase):
    def _check(self, **extra):
        check = {"key": "shakeout", "passed": True, "detail": "latch"}
        check.update(extra)
        return check

    def test_price_above_shakeout_low_is_active(self):
        item = bottom.shakeout_hold(self._check(shakeout_low=0.5), 0.6, latched_at=1)
        self.assertTrue(item["active"])

    def test_price_below_shakeout_low_is_not_active(self):
        item = bottom.shakeout_hold(self._check(shakeout_low=0.5), 0.4, latched_at=1)
        self.assertTrue(item["available"])
        self.assertFalse(item["active"])

    def test_breached_low_is_not_active(self):
        check = self._check(shakeout_low=0.5, breached=True,
                            breach={"base_low": 0.5, "low": 0.3})
        item = bottom.shakeout_hold(check, 0.6, latched_at=1)
        self.assertFalse(item["active"])
        self.assertIn("sudah dilanggar", item["reason"])

    def test_latch_without_stored_low_waits_for_scan(self):
        item = bottom.shakeout_hold(self._check(), 0.6, latched_at=1)
        self.assertFalse(item["available"])
        self.assertIn("tunggu scan", item["reason"])

    def test_no_shakeout_is_unavailable(self):
        item = bottom.shakeout_hold({"key": "shakeout", "passed": False}, 0.6)
        self.assertFalse(item["available"])


class SummaryTests(unittest.TestCase):
    def test_summary_counts_active_over_available(self):
        out = bottom.bottom_signals(
            result={"delta": None, "checks": [
                {"key": "shakeout", "passed": True, "shakeout_low": 1.0}]},
            metrics={"price_usd": 2.0},
            history=[{"ts": i, "price": 2.0 - 0.1 * i, "liq_usd": 100.0,
                      "pool_base_usd": 50.0, "token_mc": 0.2} for i in range(8)],
            latched_at=1)
        self.assertEqual(out["total"], 4)
        self.assertEqual(out["available"], 3)  # CVD tidak ada (delta None)
        self.assertEqual(out["active"], 3)     # token/MC diam, quote tahan, harga di atas low
        self.assertEqual(out["summary"], "3/3 · Token/MC⏸ · Pool tahan · Low bertahan")

    def test_nothing_available_shows_dash(self):
        out = bottom.bottom_signals(result={}, metrics={}, history=[])
        self.assertEqual(out["summary"], "—")
        self.assertEqual(out["available"], 0)

    def test_pure_module_has_no_network_or_state_imports(self):
        with open(bottom.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for name in ("requests", "curl_cffi", "sweep_scan", "sweep_state", "urllib"):
            self.assertNotIn(f"import {name}", source)


class ShakeoutLowStoredTests(unittest.TestCase):
    def test_latched_check_stores_low_without_changing_verdict(self):
        candles = [[1_000, 1.0, 1.0, 0.8, 0.9, 1.0],
                   [1_000 + HOUR, 0.9, 1.0, 0.85, 0.95, 1.0],
                   [1_000 + 2 * HOUR, 0.95, 1.1, 0.9, 1.05, 1.0]]
        check = screen._latched_shakeout_check(
            {"key": "shakeout", "label": "x", "passed": False, "detail": "d"},
            1_000, candles)
        self.assertTrue(check["passed"])
        self.assertEqual(check["shakeout_low"], 0.8)
        self.assertFalse(check["breached"])

    def test_breached_latch_still_passes(self):
        candles = [[1_000, 1.0, 1.0, 0.8, 0.9, 1.0],
                   [1_000 + HOUR, 0.9, 0.95, 0.5, 0.6, 1.0]]
        check = screen._latched_shakeout_check({"key": "shakeout", "passed": False},
                                               1_000, candles)
        self.assertTrue(check["passed"])
        self.assertTrue(check["breached"])
        self.assertEqual(check["shakeout_low"], 0.8)

    def test_delta_buckets_keep_price(self):
        candles = [[1_000_000, 0, 0, 0, 2.0, 0]]
        info = screen.delta_info([("buy", 10.0, 1_000_100)], candles,
                                 now=1_000_000 + HOUR, complete=True)
        self.assertIn("price", info["buckets"][0])


class TableColumnTests(unittest.TestCase):
    def _row(self, bottom_info=None):
        row = {"mint": "M" * 44, "ts": 1, "metrics": {"symbol": "T"},
               "result": {"verdict": "TUNGGU", "checks": []},
               "sweep_context": None, "turnover_x": None, "token_mc_hist": [1.0, 2.0]}
        if bottom_info is not None:
            row["bottom"] = bottom_info
        return row

    def test_column_shows_summary_after_trend(self):
        keys = list(ui._eligibility_rows([self._row({"summary": "1/2 · CVD↗"})])[0])
        self.assertEqual(keys[keys.index("Tren token/MC") + 1], "Sinyal bottom")
        out = ui._eligibility_rows([self._row({"summary": "1/2 · CVD↗"})])[0]
        self.assertEqual(out["Sinyal bottom"], "1/2 · CVD↗")

    def test_missing_bottom_shows_dash(self):
        out = ui._eligibility_rows([self._row()])[0]
        self.assertEqual(out["Sinyal bottom"], "—")

    def test_bottom_does_not_change_verdict_or_sort_key(self):
        state = store.empty_state()
        for i in range(8):
            store.add_snapshot(state, "M" * 44,
                               {"price_usd": 1.0 - 0.02 * i, "pool_base_usd": 30.0,
                                "fdv_usd": 100.0, "liq_usd": 100.0}, ts=HOUR * (i + 1))
        result = {"verdict": "TUNGGU", "eligible": False, "checks": [
            {"key": "shakeout", "passed": True, "shakeout_low": 0.5}]}
        before = dict(result)
        key_before = screen.display_sort_key(result)
        row = {"mint": "M" * 44, "metrics": {"price_usd": 0.86}, "result": result}
        ui._attach_bottom(row, state, {})
        self.assertEqual(result, before)
        self.assertEqual(screen.display_sort_key(result), key_before)
        self.assertFalse(result["eligible"])

    def test_attach_bottom_uses_state_history(self):
        state = store.empty_state()
        for i in range(8):
            store.add_snapshot(state, "M" * 44,
                               {"price_usd": 1.0 - 0.02 * i, "pool_base_usd": 30.0,
                                "fdv_usd": 100.0, "liq_usd": 100.0}, ts=HOUR * (i + 1))
        row = {"mint": "M" * 44, "metrics": {"price_usd": 0.86},
               "result": {"checks": []}}
        ui._attach_bottom(row, state, {})
        self.assertIn("summary", row["bottom"])
        self.assertTrue(row["bottom"]["items"][1]["available"])


if __name__ == "__main__":
    unittest.main()
