"""Coverage validasi volume/harga: gerbang dump, akumulasi, dan data hilang."""
from __future__ import annotations

import math
import unittest
from unittest import mock

import telegram_alerts as ta

HIGH_VOLATILITY = {"available": True, "price_stddev_4h": 4.2,
                   "high_volatility": True, "high_volatility_pct": 3.0}
CALM_VOLATILITY = {"available": True, "price_stddev_4h": 0.8,
                   "high_volatility": False, "high_volatility_pct": 3.0}


def context(**overrides) -> dict:
    """Konteks pasar minimal yang dianggap lengkap oleh volume_verdict."""
    base = {"available": True, "volume_4h": 20_000.0, "avg_volume_7d": 10_000.0,
            "price": 0.5, "price_change_pct": -1.0, "buy_pressure": 60.0,
            "sell_pressure": 40.0}
    base.update(overrides)
    return base


class DumpGateTest(unittest.TestCase):
    def test_exact_thresholds_pass_at_base_confidence(self):
        """Volume tepat 2× dan harga tepat -1% = lolos di ambang 0,70."""
        check = ta.validate_alert_with_volume(0.25, 20_000, 10_000, 0.5, -1.0)
        self.assertTrue(check.is_valid)
        self.assertTrue(check.verified)
        self.assertAlmostEqual(check.confidence_score, ta.MIN_CONFIDENCE)
        verdict = ta.volume_verdict("dump", 0.25, context())
        self.assertTrue(verdict["allow"])
        self.assertTrue(verdict["verified"])
        self.assertAlmostEqual(verdict["confidence_score"], 0.70, places=2)

    def test_volume_just_below_multiple_is_rejected(self):
        check = ta.validate_alert_with_volume(0.40, 19_900, 10_000, 0.5, -3.0)
        self.assertFalse(check.is_valid)
        self.assertLessEqual(check.confidence_score, ta.MAX_DIAGNOSTIC_CONFIDENCE)
        self.assertIn("1.99x", check.reason)
        self.assertIn("2.0x", check.reason)

    def test_price_above_minus_one_is_rejected(self):
        """Dust naik tanpa tekanan jual = noise, bukan dump."""
        check = ta.validate_alert_with_volume(0.40, 50_000, 10_000, 0.5, -0.4)
        self.assertFalse(check.is_valid)
        self.assertIn("belum ada tekanan jual", check.reason)
        verdict = ta.volume_verdict(
            "dump", 0.40, context(volume_4h=50_000.0, price_change_pct=-0.4))
        self.assertFalse(verdict["allow"])

    def test_price_rising_is_rejected_even_with_huge_volume(self):
        check = ta.validate_alert_with_volume(0.90, 500_000, 10_000, 0.5, 12.0)
        self.assertFalse(check.is_valid)

    def test_zero_volume_is_measured_data_not_missing(self):
        """Volume 0 (tidak ada trade) harus menolak, bukan dianggap 'tidak tahu'."""
        check = ta.validate_alert_with_volume(0.40, 0.0, 10_000, 0.5, -4.0)
        self.assertTrue(check.verified)
        self.assertFalse(check.is_valid)
        self.assertIn("0.00x", check.reason)
        verdict = ta.volume_verdict(
            "dump", 0.40, context(volume_4h=0.0, price_change_pct=-4.0))
        self.assertFalse(verdict["allow"])

    def test_high_volatility_reproduces_prompt_example(self):
        """stddev 4 jam > 3% + dust naik → skor 0,90 melawan ambang 0,80."""
        check = ta.validate_alert_with_volume(
            0.30, 20_000, 10_000, 0.5, -1.0, volatility=HIGH_VOLATILITY)
        self.assertTrue(check.is_valid)
        self.assertAlmostEqual(check.confidence_score, 0.90, places=2)
        self.assertAlmostEqual(ta.required_confidence(HIGH_VOLATILITY), 0.80)
        verdict = ta.volume_verdict("dump", 0.30,
                                    context(volatility=HIGH_VOLATILITY))
        self.assertTrue(verdict["allow"])
        self.assertAlmostEqual(verdict["required_confidence"], 0.80)

    def test_high_volatility_without_price_confirmation_gets_no_bonus(self):
        """Ambang 0,80 harus punya gigi: tanpa arah harga, bonus tidak diberi."""
        check = ta.validate_alert_with_volume(
            -0.60, 15_000, 10_000, 0.5, -2.0, kind="accumulation",
            buy_pressure=51.0, sell_pressure=50.0, volatility=HIGH_VOLATILITY)
        self.assertTrue(check.is_valid)          # gerbang keras terpenuhi
        self.assertLess(check.confidence_score, 0.80)
        self.assertFalse(ta.volume_verdict(
            "accumulation", -0.60,
            context(volume_4h=15_000.0, avg_volume_7d=10_000.0,
                    price_change_pct=-2.0, buy_pressure=51.0,
                    sell_pressure=50.0, volatility=HIGH_VOLATILITY))["allow"])

    def test_stronger_volume_and_price_raise_confidence(self):
        weak = ta.validate_alert_with_volume(0.30, 20_000, 10_000, 0.5, -1.0)
        strong = ta.validate_alert_with_volume(0.30, 40_000, 10_000, 0.5, -5.0)
        self.assertGreater(strong.confidence_score, weak.confidence_score)
        self.assertLessEqual(strong.confidence_score, ta.MAX_CONFIDENCE)

    def test_confidence_is_capped(self):
        check = ta.validate_alert_with_volume(
            9.0, 1e12, 1.0, 0.5, -90.0, volatility=HIGH_VOLATILITY)
        self.assertLessEqual(check.confidence_score, ta.MAX_CONFIDENCE)

    def test_result_supports_attribute_and_tuple_access(self):
        check = ta.validate_alert_with_volume(0.30, 30_000, 10_000, 0.5, -2.0)
        is_valid, confidence, reason = check[:3]
        self.assertEqual(is_valid, check.is_valid)
        self.assertEqual(confidence, check.confidence_score)
        self.assertEqual(reason, check.reason)
        self.assertIsInstance(check.details, dict)
        self.assertEqual(check.details["required_ratio"], ta.DUMP_VOLUME_MULTIPLE)


class AccumulationGateTest(unittest.TestCase):
    def test_gate_needs_1_5x_volume_and_dominant_buyers(self):
        check = ta.validate_alert_with_volume(
            -0.60, 15_000, 10_000, 0.5, 0.4, kind="accumulation",
            buy_pressure=120.0, sell_pressure=40.0)
        self.assertTrue(check.is_valid)
        self.assertIn("1.5x", check.reason)
        self.assertIn("buy 120 > sell 40", check.reason)

    def test_volume_multiple_below_accumulation_gate(self):
        check = ta.validate_alert_with_volume(
            -0.60, 14_000, 10_000, 0.5, 0.4, kind="accumulation",
            buy_pressure=120.0, sell_pressure=40.0)
        self.assertFalse(check.is_valid)

    def test_equal_buy_and_sell_pressure_is_rejected(self):
        check = ta.validate_alert_with_volume(
            -0.60, 30_000, 10_000, 0.5, 0.4, kind="accumulation",
            buy_pressure=80.0, sell_pressure=80.0)
        self.assertFalse(check.is_valid)
        self.assertIn("tekanan beli belum dominan", check.reason)

    def test_sell_dominant_is_rejected(self):
        check = ta.validate_alert_with_volume(
            -0.60, 30_000, 10_000, 0.5, -6.0, kind="accumulation",
            buy_pressure=10.0, sell_pressure=200.0)
        self.assertFalse(check.is_valid)

    def test_zero_sell_pressure_with_buys_still_valid(self):
        check = ta.validate_alert_with_volume(
            -0.60, 30_000, 10_000, 0.5, 1.0, kind="accumulation",
            buy_pressure=25.0, sell_pressure=0.0)
        self.assertTrue(check.is_valid)

    def test_price_is_not_a_hard_gate_for_accumulation(self):
        """Gerbang akumulasi = volume + tekanan beli; arah harga bukan syarat."""
        falling = ta.validate_alert_with_volume(
            -0.60, 30_000, 10_000, 0.5, -4.0, kind="accumulation",
            buy_pressure=100.0, sell_pressure=20.0)
        rising = ta.validate_alert_with_volume(
            -0.60, 30_000, 10_000, 0.5, 4.0, kind="accumulation",
            buy_pressure=100.0, sell_pressure=20.0)
        self.assertTrue(falling.is_valid)
        self.assertTrue(rising.is_valid)
        self.assertEqual(falling.confidence_score, rising.confidence_score)

    def test_price_direction_only_matters_through_the_volatility_bonus(self):
        """Saat pasar liar, harga naik memperkuat akumulasi; harga turun tidak."""
        rising = ta.validate_alert_with_volume(
            -0.60, 16_000, 10_000, 0.5, 2.0, kind="accumulation",
            buy_pressure=30.0, sell_pressure=20.0, volatility=HIGH_VOLATILITY)
        falling = ta.validate_alert_with_volume(
            -0.60, 16_000, 10_000, 0.5, -2.0, kind="accumulation",
            buy_pressure=30.0, sell_pressure=20.0, volatility=HIGH_VOLATILITY)
        self.assertTrue(rising.is_valid and falling.is_valid)
        self.assertGreater(rising.confidence_score, falling.confidence_score)
        self.assertGreaterEqual(rising.confidence_score, 0.80)
        self.assertLess(falling.confidence_score, 0.80)

    def test_stronger_buy_pressure_raises_confidence(self):
        weak = ta.validate_alert_with_volume(
            -0.60, 16_000, 10_000, 0.5, 1.0, kind="accumulation",
            buy_pressure=22.0, sell_pressure=20.0)
        strong = ta.validate_alert_with_volume(
            -0.60, 16_000, 10_000, 0.5, 1.0, kind="accumulation",
            buy_pressure=200.0, sell_pressure=20.0)
        self.assertGreater(strong.confidence_score, weak.confidence_score)


class MissingDataTest(unittest.TestCase):
    """Data hilang = tidak tahu, bukan "tenang": alert tetap jalan, ditandai."""

    def test_missing_seven_day_baseline_is_unverified(self):
        for baseline in (None, 0, 0.0, -5):
            check = ta.validate_alert_with_volume(0.40, 5_000, baseline, 0.5, -3.0)
            self.assertFalse(check.verified, f"baseline={baseline}")
            self.assertAlmostEqual(check.confidence_score,
                                   ta.UNVERIFIED_CONFIDENCE)
            self.assertIn("avg_volume_7d", check.reason)

    def test_missing_volume_is_unverified(self):
        check = ta.validate_alert_with_volume(0.40, None, 10_000, 0.5, -3.0)
        self.assertFalse(check.verified)
        self.assertIn("volume_4h", check.reason)

    def test_negative_volume_is_unverified_not_a_rejection(self):
        check = ta.validate_alert_with_volume(0.40, -1.0, 10_000, 0.5, -3.0)
        self.assertFalse(check.verified)

    def test_missing_price_change_is_unverified_for_dump(self):
        check = ta.validate_alert_with_volume(0.40, 30_000, 10_000, 0.5, None)
        self.assertFalse(check.verified)
        self.assertIn("price_change_pct", check.reason)

    def test_missing_price_change_is_allowed_for_accumulation(self):
        check = ta.validate_alert_with_volume(
            -0.60, 30_000, 10_000, 0.5, None, kind="accumulation",
            buy_pressure=90.0, sell_pressure=10.0)
        self.assertTrue(check.verified)
        self.assertTrue(check.is_valid)

    def test_missing_pressure_is_unverified_for_accumulation(self):
        check = ta.validate_alert_with_volume(
            -0.60, 30_000, 10_000, 0.5, 1.0, kind="accumulation",
            buy_pressure=None, sell_pressure=10.0)
        self.assertFalse(check.verified)
        self.assertIn("buy/sell_pressure", check.reason)

    def test_nan_and_inf_are_treated_as_missing(self):
        for bad in (math.nan, math.inf, -math.inf):
            check = ta.validate_alert_with_volume(0.40, bad, 10_000, 0.5, -3.0)
            self.assertFalse(check.verified, f"volume={bad}")

    def test_verdict_allows_unverified_and_flags_it(self):
        verdict = ta.volume_verdict("dump", 0.40, None)
        self.assertTrue(verdict["allow"])
        self.assertFalse(verdict["verified"])
        self.assertAlmostEqual(verdict["confidence_score"],
                               ta.UNVERIFIED_CONFIDENCE)
        self.assertIn("tanpa verifikasi", verdict["reason"])

    def test_empty_context_is_unverified(self):
        verdict = ta.volume_verdict("dump", 0.40, {})
        self.assertTrue(verdict["allow"])
        self.assertFalse(verdict["verified"])

    def test_context_marked_unavailable_is_unverified(self):
        verdict = ta.volume_verdict(
            "dump", 0.40,
            {"available": False, "volume_4h": 90_000.0, "avg_volume_7d": 1.0,
             "price_change_pct": -9.0,
             "reason": "data pasar tidak lengkap: avg_volume_7d"})
        self.assertTrue(verdict["allow"])
        self.assertFalse(verdict["verified"])
        self.assertIn("tidak lengkap", verdict["reason"])

    def test_policy_constant_controls_unverified_alerts(self):
        with mock.patch.object(ta, "ALLOW_UNVERIFIED_ALERTS", False):
            self.assertFalse(ta.volume_verdict("dump", 0.40, None)["allow"])


class RequiredConfidenceTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertAlmostEqual(ta.required_confidence(None), 0.70)
        self.assertAlmostEqual(ta.required_confidence(CALM_VOLATILITY), 0.70)
        self.assertAlmostEqual(ta.required_confidence(HIGH_VOLATILITY), 0.80)

    def test_unavailable_volatility_never_raises_the_bar(self):
        self.assertAlmostEqual(ta.required_confidence(
            {"available": False, "price_stddev_4h": 99.0,
             "high_volatility": True}), 0.70)
        self.assertFalse(ta.is_high_volatility({"available": False}))
        self.assertFalse(ta.is_high_volatility("bukan dict"))
        self.assertFalse(ta.is_high_volatility(None))

    def test_stddev_fallback_when_flag_missing(self):
        self.assertTrue(ta.is_high_volatility(
            {"available": True, "price_stddev_4h": 3.01,
             "high_volatility_pct": 3.0}))
        self.assertFalse(ta.is_high_volatility(
            {"available": True, "price_stddev_4h": 3.0,
             "high_volatility_pct": 3.0}))

    def test_boundary_is_strictly_greater(self):
        """Tepat 3,0% belum "liar" (ambang pakai > bukan >=)."""
        self.assertFalse(ta.is_high_volatility(
            {"available": True, "price_stddev_4h": 3.0, "high_volatility": None,
             "high_volatility_pct": 3.0}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
