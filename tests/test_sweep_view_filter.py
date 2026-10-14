# -*- coding: utf-8 -*-
"""Filter tampilan hasil Sweep (permintaan user 2026-10-14).

Baris disembunyikan bila ``x dana acuan 10x`` > 3× atau bundler < 10%.
Nilai yang belum ada tidak pernah menyembunyikan baris.
"""
from __future__ import annotations

import pathlib
import unittest

import sweep_screen as ss

ROOT = pathlib.Path(__file__).resolve().parent.parent

COCK_LIQ_MC = 30232.0 / 233451.0  # ≈1,0× acuan


class ViewHiddenTest(unittest.TestCase):
    def _row(self, ref_x=None, bundler=None, liq_mc=None, bundler_rate=None):
        metrics = {}
        if bundler is not None:
            metrics["top_bundler_trader_percentage"] = bundler
        if bundler_rate is not None:
            metrics["bundler_rate"] = bundler_rate
        result = {}
        if ref_x is not None:
            result["reference_fund_x"] = ref_x
        if liq_mc is not None:
            result["liq_mc"] = liq_mc
        return {"metrics": metrics, "result": result}

    def test_threshold_constants(self):
        self.assertEqual(ss.VIEW_HIDE_REF_X_ABOVE, 3.0)
        self.assertEqual(ss.VIEW_HIDE_BUNDLER_BELOW, 0.10)

    def test_ref_x_above_3_is_hidden(self):
        self.assertTrue(ss.view_hidden(self._row(ref_x=3.01)))
        self.assertFalse(ss.view_hidden(self._row(ref_x=3.0)))  # tepat 3× tampil

    def test_bundler_below_10_percent_is_hidden(self):
        self.assertTrue(ss.view_hidden(self._row(bundler=0.09)))
        self.assertFalse(ss.view_hidden(self._row(bundler=0.10)))  # tepat 10% tampil

    def test_bundler_falls_back_to_bundler_rate(self):
        self.assertTrue(ss.view_hidden(self._row(bundler_rate=0.02)))
        self.assertFalse(ss.view_hidden(self._row(bundler_rate=0.25)))

    def test_either_condition_hides(self):
        self.assertTrue(ss.view_hidden(self._row(ref_x=5.0, bundler=0.5)))
        self.assertTrue(ss.view_hidden(self._row(ref_x=1.0, bundler=0.01)))

    def test_missing_values_never_hide(self):
        self.assertFalse(ss.view_hidden(self._row()))
        self.assertFalse(ss.view_hidden({}))
        self.assertFalse(ss.view_hidden(None))

    def test_ref_x_falls_back_to_liq_mc(self):
        # Snapshot lama tanpa reference_fund_x: dihitung dari liq/MC.
        self.assertFalse(ss.view_hidden(self._row(liq_mc=COCK_LIQ_MC, bundler=0.5)))
        # liq/MC 80% → biaya 10x ≈ 86% MC → x ≈ 6,2 → disembunyikan.
        self.assertTrue(ss.view_hidden(self._row(liq_mc=0.80, bundler=0.5)))


class HiddenTableToggleTest(unittest.TestCase):
    def test_toggle_is_off_by_default_and_hidden_table_has_own_keys(self):
        source = (ROOT / "sweep_ui.py").read_text(encoding="utf-8")
        self.assertIn('key="sweep_show_hidden"', source)
        self.assertIn("value=False", source)
        # Tabel tersembunyi memakai key widget sendiri (tidak bentrok dengan tabel utama).
        self.assertIn('suffix="_hidden"', source)
        self.assertIn('key=f"sweep_table{suffix}"', source)


if __name__ == "__main__":
    unittest.main()
