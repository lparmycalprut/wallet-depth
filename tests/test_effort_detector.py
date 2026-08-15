import tempfile
import unittest
from pathlib import Path

from effort_detector import (classify_effort, daily_effort_record,
                             merge_daily_effort)


class EffortDetectorTest(unittest.TestCase):
    def pair(self, direction, multiplier, cvd_sign=None, move=10.0):
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


if __name__ == "__main__":
    unittest.main()
