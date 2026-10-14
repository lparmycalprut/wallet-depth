# -*- coding: utf-8 -*-
"""Peringatan pelanggaran low shakeout (permintaan user 2026-10-14, opsi 3).

Latch shakeout tetap permanen dan kriteria 6 tetap LOLOS. Bila candle sesudah
latch menembus low shakeout, hanya ditandai ``breached`` dan keterangan.
"""
from __future__ import annotations

import unittest

import sweep_screen as ss

# Candle jam COCKROACH 1 Okt 2026 (WIB), [ts, open, high, low, close, vol].
# ts 1790859600 = 20:00 WIB (flush 20:35, low 0,00026020); 1790863200 = 21:00
# (higher low 0,00030340); 1790866800 = 22:00 (low 0,00021623 = pelanggaran).
COCK = [
    [1790856000, 0.00039625, 0.00048255, 0.00039499, 0.00048222, 22781],
    [1790859600, 0.00048222, 0.00049506, 0.00026020, 0.00031827, 30539],
    [1790863200, 0.00031827, 0.00037454, 0.00030340, 0.00034290, 18699],
    [1790866800, 0.00034290, 0.00206033, 0.00021623, 0.00182639, 1536017],
    [1790870400, 0.00182639, 0.00212241, 0.00123589, 0.00147833, 594575],
]
COCK_LATCH_TS = 1790859600


def _shakeout(result):
    return next(c for c in result["checks"] if c["key"] == "shakeout")


class ShakeoutBreachTest(unittest.TestCase):
    def test_cock_breach_is_detected_on_22_candle(self):
        breach = ss.shakeout_breach(COCK, COCK_LATCH_TS)
        self.assertIsNotNone(breach)
        self.assertAlmostEqual(breach["low"], 0.00021623, places=8)
        self.assertAlmostEqual(breach["base_low"], 0.00026020, places=8)
        self.assertEqual(breach["ts"], 1790866800)

    def test_no_breach_when_later_lows_hold(self):
        candles = [[100, 1, 1.0, 0.5, 1, 1], [200, 1, 1.0, 0.6, 1, 1],
                   [300, 1, 1.0, 0.7, 1, 1]]
        self.assertIsNone(ss.shakeout_breach(candles, 100))

    def test_latch_outside_window_is_not_flagged(self):
        candles = [[200, 1, 1.0, 0.6, 1, 1], [300, 1, 1.0, 0.1, 1, 1]]
        self.assertIsNone(ss.shakeout_breach(candles, 100))
        self.assertIsNone(ss.shakeout_breach(candles, None))

    def test_breach_only_looks_after_the_shakeout_bar(self):
        # Low sebelum/pada bar shakeout tidak dihitung sebagai pelanggaran.
        candles = [[50, 1, 1.0, 0.1, 1, 1], [100, 1, 1.0, 0.5, 1, 1],
                   [200, 1, 1.0, 0.6, 1, 1]]
        self.assertIsNone(ss.shakeout_breach(candles, 100))


class LatchedShakeoutCheckTest(unittest.TestCase):
    def test_breached_latch_stays_passed_and_is_flagged(self):
        # Kondisi COCK pukul 22:05 WIB: kriteria hidup gagal, latch tetap LOLOS.
        live = ss.criterion_shakeout(COCK[:3])
        self.assertTrue(live["passed"])
        latched = ss._latched_shakeout_check(
            ss.criterion_shakeout(COCK[:2]), COCK_LATCH_TS, COCK)
        self.assertTrue(latched["passed"])
        self.assertTrue(latched["breached"])
        self.assertIn("dilanggar", latched["detail"])

    def test_latch_without_breach_is_not_flagged(self):
        latched = ss._latched_shakeout_check(
            ss.criterion_shakeout([]), COCK_LATCH_TS, COCK[:3])
        self.assertTrue(latched["passed"])
        self.assertFalse(latched["breached"])
        self.assertNotIn("dilanggar", latched["detail"])

    def test_evaluate_keeps_verdict_inputs_and_exposes_flag(self):
        state = {"shakeout_latched_at": {"M": COCK_LATCH_TS}}
        result = ss.evaluate({"mint": "M"}, candles=COCK, state=state, mint="M")
        shakeout = _shakeout(result)
        self.assertTrue(shakeout["passed"])
        self.assertTrue(shakeout["breached"])

    def test_evaluate_without_latch_is_unchanged(self):
        result = ss.evaluate({"mint": "M"}, candles=COCK, state={}, mint="M")
        self.assertNotIn("breached", _shakeout(result))


if __name__ == "__main__":
    unittest.main()
