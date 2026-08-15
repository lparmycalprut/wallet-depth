import tempfile
import unittest
from pathlib import Path

from effort_detector import (classify_effort, daily_effort_record,
                             merge_daily_effort, MIN_BASELINE_RATIO,
                             MIN_BASELINE_CVD_SOL)


class EffortDetectorTest(unittest.TestCase):
    def pair(self, direction, multiplier, cvd_sign=None, move=10.0):
        # Previous day direction matches current direction for compatibility
        if direction == "up":
            previous = daily_effort_record("M", "2026-08-01", 100, 110, 10)
        else:
            previous = daily_effort_record("M", "2026-08-01", 100, 90, -10)
        close = 100 + move if direction == "up" else 100 - move
        ratio_target = previous["ratio"] * multiplier
        cvd = ratio_target * abs(move)
        if cvd_sign == "negative" or (cvd_sign is None and direction == "down"):
            cvd *= -1
        current = daily_effort_record("M", "2026-08-02", 100, close, cvd)
        return classify_effort([previous, current], "M")

    def test_ratio_formula(self):
        row = daily_effort_record("M", "2026-08-01", 100, 80, -10)
        self.assertAlmostEqual(row["price_chg_pct"], -20)
        self.assertAlmostEqual(row["ratio"], 0.5)
        self.assertEqual(row["direction"], "down")

    def test_all_directional_signals_and_exact_boundaries(self):
        self.assertEqual(self.pair("down", 2.0)["signal"], "S1_PENYERAPAN")
        self.assertEqual(self.pair("down", 0.5)["signal"],
                         "S2_DUMP_DISTRIBUSI")
        self.assertEqual(self.pair("up", 2.0)["signal"],
                         "S3_DISTRIBUSI_KE_KUAT")
        self.assertEqual(self.pair("up", 0.5)["signal"], "S4_PUMP_ASLI")
        self.assertEqual(self.pair("up", 1.0)["signal"], "S5_NETRAL")

    def test_small_price_move_is_always_neutral(self):
        result = self.pair("down", 3.0, move=2.99)
        self.assertEqual(result["signal"], "S5_NETRAL")

    def test_opposite_cvd_direction_sets_flag_only(self):
        result = self.pair("down", 2.0, cvd_sign="positive")
        self.assertEqual(result["signal"], "S1_PENYERAPAN")
        self.assertTrue(result["flag_divergence"])

    def test_requires_two_consecutive_valid_days(self):
        one = daily_effort_record("M", "2026-08-01", 100, 90, -10)
        self.assertEqual(classify_effort([one], "M")["signal"],
                         "insufficient_data")
        gap = daily_effort_record("M", "2026-08-03", 100, 90, -20)
        self.assertEqual(classify_effort([one, gap], "M")["signal"],
                         "insufficient_data")

    def test_merge_is_idempotent_and_retains_newest_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "daily.json")
            rows = [daily_effort_record("M", f"2026-08-{day:02d}",
                                        100, 90, -day)
                    for day in range(1, 6)]
            first = merge_daily_effort(rows, path=path, retention_days=3)
            second = merge_daily_effort(rows[-1:], path=path,
                                        retention_days=3)
            self.assertEqual(first, second)
            self.assertEqual([row["date"] for row in second],
                             ["2026-08-03", "2026-08-04", "2026-08-05"])

    # --- Required new test cases ---

    def test_fixture_mim_nyata(self):
        """Fixture MIM real case: unstable baseline + different direction."""
        prev = daily_effort_record(
            "86KR6eG2VuNntLBi23SAYFW1cXkiYcwxGJd746rqcUAG",
            "2026-08-13", 100, 132.83650172, 0.2507202)
        prev["ratio"] = 0.00763541
        prev["price_chg_pct"] = 32.83650172
        prev["direction"] = "up"

        curr = daily_effort_record(
            "86KR6eG2VuNntLBi23SAYFW1cXkiYcwxGJd746rqcUAG",
            "2026-08-14", 132.83650172,
            132.83650172 * (1 - 0.6693230007), -97.9211605)
        curr["ratio"] = 1.46298813
        curr["price_chg_pct"] = -66.93230007
        curr["direction"] = "down"

        res = classify_effort([prev, curr],
                              "86KR6eG2VuNntLBi23SAYFW1cXkiYcwxGJd746rqcUAG")
        self.assertAlmostEqual(res["raw_multiplier"], 191.61, delta=1.0)
        self.assertEqual(res["signal"], "insufficient_data")
        self.assertIsNone(res["bias"])
        self.assertNotEqual(res.get("signal"), "S1_PENYERAPAN")
        self.assertEqual(res["baseline_status"], "unstable")
        self.assertIn("minimum", res["baseline_reason"])
        # Telegram defensive gate: must not send
        from signals import should_send_telegram
        self.assertFalse(should_send_telegram(res))

    def test_baseline_ratio_too_small_same_direction(self):
        prev = daily_effort_record("M", "2026-08-13", 100, 120, 0.98)
        prev["ratio"] = 0.008
        prev["price_chg_pct"] = -20.0
        prev["direction"] = "down"
        curr = daily_effort_record("M", "2026-08-14", 120, 100, -50)
        curr["ratio"] = 2.5
        curr["price_chg_pct"] = -16.66666667
        curr["direction"] = "down"
        res = classify_effort([prev, curr], "M")
        self.assertEqual(res["signal"], "insufficient_data")
        self.assertEqual(res["baseline_status"], "unstable")
        self.assertIn("minimum", res["baseline_reason"])

    def test_direction_different_stable_baseline(self):
        prev = daily_effort_record("M", "2026-08-13", 100, 80, -10)
        prev["ratio"] = 0.5
        prev["price_chg_pct"] = -20.0
        prev["direction"] = "down"
        curr = daily_effort_record("M", "2026-08-14", 80, 96, 20)
        curr["ratio"] = 1.25
        curr["price_chg_pct"] = 20.0
        curr["direction"] = "up"
        res = classify_effort([prev, curr], "M")
        self.assertEqual(res["signal"], "insufficient_data")
        self.assertEqual(res["baseline_status"], "incompatible_direction")
        self.assertEqual(res["baseline_reason"],
                         "direction hari N berbeda dari baseline")

    def test_stable_baseline_produces_s1(self):
        prev = daily_effort_record("M", "2026-08-13", 100, 27, -34.7)
        prev["ratio"] = 0.475
        prev["price_chg_pct"] = -73.0
        prev["direction"] = "down"
        curr = daily_effort_record("M", "2026-08-14", 27, 12.96, -50.5)
        curr["ratio"] = 0.971
        curr["price_chg_pct"] = -52.0
        curr["direction"] = "down"
        res = classify_effort([prev, curr], "M")
        self.assertEqual(res["baseline_status"], "stable")
        self.assertEqual(res["signal"], "S1_PENYERAPAN")
        self.assertEqual(res["bias"], "bullish")
        self.assertAlmostEqual(res["multiplier"], 2.04, delta=0.05)

    def test_boundary_exact_minimums(self):
        # Boundary: ratio = 0.05 (valid), CVD = 1.0 (valid), price = 3.0% (valid), same dir
        prev = daily_effort_record("M", "2026-08-13", 100, 120, 1.0)
        prev["ratio"] = 0.05
        prev["price_chg_pct"] = 20.0
        prev["direction"] = "up"
        curr = daily_effort_record("M", "2026-08-14", 120, 122.4, 2.0)
        curr["ratio"] = 0.83333333
        curr["price_chg_pct"] = 2.0
        curr["direction"] = "up"
        res = classify_effort([prev, curr], "M")
        # Since current price < 3%, signal should be S5 even with stable baseline
        self.assertEqual(res["baseline_status"], "stable")
        self.assertEqual(res["signal"], "S5_NETRAL")

        # Boundary: ratio just below 0.05
        prev2 = daily_effort_record("M", "2026-08-13", 100, 120, 0.98)
        prev2["ratio"] = 0.049
        prev2["price_chg_pct"] = 20.0
        prev2["direction"] = "down"
        curr2 = daily_effort_record("M", "2026-08-14", 120, 80, -40)
        curr2["ratio"] = 1.0
        curr2["price_chg_pct"] = -33.33333333
        curr2["direction"] = "down"
        res2 = classify_effort([prev2, curr2], "M")
        self.assertEqual(res2["baseline_status"], "unstable")
        self.assertIn("0.05", res2["baseline_reason"])

        # Boundary: CVD exactly 1.0 (valid), price 3.0% (valid), same dir up
        # Current price exactly 3.0% (not < 3%), so classification applies
        prev3 = daily_effort_record("M", "2026-08-13", 100, 103, 1.0)
        prev3["ratio"] = 0.33333333
        prev3["price_chg_pct"] = 3.0
        prev3["direction"] = "up"
        curr3 = daily_effort_record("M", "2026-08-14", 103, 106.09, 10.0)
        curr3["ratio"] = 3.33333333
        curr3["price_chg_pct"] = 3.0
        curr3["direction"] = "up"
        res3 = classify_effort([prev3, curr3], "M")
        self.assertEqual(res3["baseline_status"], "stable")
        # Multiplier ~10.0 with up direction -> S3
        self.assertEqual(res3["signal"], "S3_DISTRIBUSI_KE_KUAT")

        # Boundary: price exactly 3.0% (valid), direction same down
        prev4 = daily_effort_record("M", "2026-08-13", 100, 97, -5.0)
        prev4["ratio"] = 1.66666667
        prev4["price_chg_pct"] = -3.0
        prev4["direction"] = "down"
        curr4 = daily_effort_record("M", "2026-08-14", 97, 87.3, -10)
        curr4["ratio"] = 1.03092784
        curr4["price_chg_pct"] = -10.0
        curr4["direction"] = "down"
        res4 = classify_effort([prev4, curr4], "M")
        self.assertEqual(res4["baseline_status"], "stable")
        # Multiplier ~0.618 (between 0.5 and 2.0) -> S5
        self.assertEqual(res4["signal"], "S5_NETRAL")

    def test_current_day_ranging(self):
        prev = daily_effort_record("M", "2026-08-13", 100, 120, 1.0)
        prev["ratio"] = 0.05
        prev["price_chg_pct"] = 20.0
        prev["direction"] = "up"
        curr = daily_effort_record("M", "2026-08-14", 120, 121, 10)
        curr["ratio"] = 10.0
        curr["price_chg_pct"] = 0.83333333
        curr["direction"] = "up"
        res = classify_effort([prev, curr], "M")
        self.assertEqual(res["signal"], "S5_NETRAL")
        self.assertEqual(res["baseline_status"], "stable")
        # Telegram should not be triggered
        from signals import should_send_telegram
        self.assertFalse(should_send_telegram(res))

    def test_telegram_defensive_gate(self):
        from signals import should_send_telegram
        # S1 with stable baseline -> should send
        s1_result = {
            "signal": "S1_PENYERAPAN",
            "baseline_status": "stable",
            "bias": "bullish",
        }
        self.assertTrue(should_send_telegram(s1_result))

        # S1 with unstable baseline -> must NOT send
        s1_unstable = {
            "signal": "S1_PENYERAPAN",
            "baseline_status": "unstable",
            "bias": "bullish",
        }
        self.assertFalse(should_send_telegram(s1_unstable))

        # S5 with stable baseline -> must NOT send
        s5_result = {
            "signal": "S5_NETRAL",
            "baseline_status": "stable",
            "bias": "neutral",
        }
        self.assertFalse(should_send_telegram(s5_result))

        # Insufficient data -> must NOT send
        insufficient = {
            "signal": "insufficient_data",
            "baseline_status": "missing",
            "bias": None,
        }
        self.assertFalse(should_send_telegram(insufficient))


if __name__ == "__main__":
    unittest.main()
