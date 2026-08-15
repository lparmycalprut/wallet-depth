import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from effort_detector import (
    classify_at,
    classify_all,
    classify_effort,
    daily_effort_record,
    merge_daily_effort,
    MIN_BASELINE_RATIO,
    MIN_BASELINE_CVD_SOL,
    MIN_CURRENT_CVD_SOL,
)
from cvd_daily import day_key, calculate_daily_cvd


class EffortDetectorV3Test(unittest.TestCase):
    def pair(self, direction, multiplier, cvd_sign=None, move=10.0, cvd_override=None):
        """Helper to build 2-day window for previous tests.

        previous day healthy baseline, current day with target multiplier.
        direction = up/down for both previous and current (same dir to avoid direction gate,
        which no longer exists but kept for compat).
        """
        if direction == "up":
            previous = daily_effort_record("M", "2026-08-01", 100, 110, 10)
        else:
            previous = daily_effort_record("M", "2026-08-01", 100, 90, -10)
        close = 100 + move if direction == "up" else 100 - move
        ratio_target = previous["ratio"] * multiplier
        cvd = ratio_target * abs(move)
        if cvd_override is not None:
            cvd = cvd_override
        else:
            if cvd_sign == "negative" or (cvd_sign is None and direction == "down"):
                cvd *= -1
            if cvd_sign == "positive":
                cvd = abs(cvd)
        current = daily_effort_record("M", "2026-08-02", 100, close, cvd)
        return classify_effort([previous, current], "M")

    def test_ratio_formula(self):
        row = daily_effort_record("M", "2026-08-01", 100, 80, -10)
        self.assertAlmostEqual(row["price_chg_pct"], -20)
        self.assertAlmostEqual(row["ratio"], 0.5)
        self.assertEqual(row["direction"], "down")

    def test_classify_at_exists_and_classify_all_exists(self):
        # verify functions exist and work
        rows = [
            daily_effort_record("M", "2026-08-01", 100, 90, -10),
            daily_effort_record("M", "2026-08-02", 100, 80, -20),
        ]
        res = classify_at(rows, 1)
        self.assertIsInstance(res, dict)
        all_res = classify_all(rows)
        self.assertEqual(len(all_res), 2)
        # first day should be insufficient or ABSORBSI
        self.assertIn(all_res[0]["signal"], ("insufficient_data", "ABSORBSI_LANGSUNG", "S5_NETRAL"))

    # --- (a) ABSORBSI LANGSUNG ---
    def test_absorbsi_langsung_direct(self):
        # ΔCVD >=5, ΔPrice <=0.5, harga turun/datar
        rec = daily_effort_record("M", "2026-06-17", 100, 77.6, 24.88)  # -22.4%
        self.assertAlmostEqual(rec["price_chg_pct"], -22.4, delta=0.1)
        res = classify_at([rec], 0)
        self.assertEqual(res["signal"], "ABSORBSI_LANGSUNG")
        self.assertEqual(res["bias"], "bullish")
        self.assertTrue(res["flag_divergence"])
        self.assertEqual(res["baseline_status"], "direct")

    def test_absorbsi_first_day_window(self):
        # berlaku untuk hari pertama window
        rec = daily_effort_record("M", "2026-08-01", 100, 100.2, 6.0)  # +0.2%
        res = classify_at([rec], 0)
        self.assertEqual(res["signal"], "ABSORBSI_LANGSUNG")

    def test_absorbsi_requires_cvd_positive(self):
        rec = daily_effort_record("M", "2026-08-01", 100, 90, -6.0)  # -10%, CVD negative
        res = classify_at([rec], 0)
        # CVD negative cannot be ABSORBSI
        self.assertNotEqual(res["signal"], "ABSORBSI_LANGSUNG")

    # --- (b) SELLING_EXHAUSTION ---
    def test_selling_exhaustion_flush_then_collapse(self):
        # Build 2 days: flush -50 SOL, then -15 SOL (30% of flush) with price <=0.5
        flush = daily_effort_record("M", "2026-07-10", 100, 50, -50)  # -50%
        flush["cvd_delta"] = -50.0
        # second day after flush
        curr = daily_effort_record("M", "2026-07-11", 50, 45, -15)  # -10%, CVD -15
        curr["cvd_delta"] = -15.0
        curr["price_chg_pct"] = -10.0
        curr["direction"] = "down"
        # ensure ratio present
        curr["ratio"] = abs(curr["cvd_delta"]) / abs(curr["price_chg_pct"])
        flush["ratio"] = abs(flush["cvd_delta"]) / abs(flush["price_chg_pct"])
        rows = [flush, curr]
        res = classify_at(rows, 1)
        self.assertEqual(res["signal"], "SELLING_EXHAUSTION")
        self.assertEqual(res["bias"], "bullish")
        self.assertFalse(res["flag_divergence"])
        self.assertEqual(res["flush_date"], "2026-07-10")
        self.assertAlmostEqual(res["flush_cvd"], -50.0)
        self.assertAlmostEqual(res["exhaustion_pct"], 30.0, delta=0.1)

    def test_selling_exhaustion_needs_flush(self):
        # No flush <=-30 in lookback -> not exhaustion
        prev = daily_effort_record("M", "2026-07-10", 100, 80, -10)  # -20%, -10 SOL
        curr = daily_effort_record("M", "2026-07-11", 80, 70, -5)   # -12.5%, -5 SOL
        # both have |CVD|<30, so no flush
        res = classify_at([prev, curr], 1)
        self.assertNotEqual(res["signal"], "SELLING_EXHAUSTION")

    def test_selling_exhaustion_lookback_5(self):
        # flush 5 days ago still counts, 6 days ago does not
        rows = []
        for i in range(6):
            # day 0 flush -100, days 1-4 small, day 5 current -20
            if i == 0:
                r = daily_effort_record("M", f"2026-07-0{i+1}", 100, 50, -100)
                r["cvd_delta"] = -100.0
                r["price_chg_pct"] = -50.0
                r["direction"] = "down"
                r["ratio"] = 2.0
            else:
                r = daily_effort_record("M", f"2026-07-0{i+1}", 100, 90, -5 if i < 5 else -20)
                r["cvd_delta"] = -5.0 if i < 5 else -20.0
                r["price_chg_pct"] = -10.0
                r["direction"] = "down"
                r["ratio"] = 0.5
            rows.append(r)
        # current is index 5, flush at index 0 is exactly 5 days before, should be within lookback 5? lookback is 5 days before idx, so indices 0-4? Actually look_start = max(0, idx-5) =0, so includes 0. Good.
        res = classify_at(rows, 5)
        self.assertEqual(res["signal"], "SELLING_EXHAUSTION")

        # Now flush at index 0, current at index 6 (6 days later) -> flush out of 5 lookback
        rows.append(daily_effort_record("M", "2026-07-07", 100, 90, -20))
        rows[-1]["cvd_delta"] = -20.0
        rows[-1]["price_chg_pct"] = -10.0
        rows[-1]["direction"] = "down"
        rows[-1]["ratio"] = 2.0
        res2 = classify_at(rows, 6)
        # no flush within last 5 (indices 1-5 have -5), so not exhaustion
        self.assertNotEqual(res2["signal"], "SELLING_EXHAUSTION")

    # --- (c) S1/S3 wajib divergen ---
    def test_s3_divergence_required(self):
        # healthy baseline
        prev = daily_effort_record("M", "2026-08-01", 100, 120, 10)  # up 20%, CVD +10
        prev["ratio"] = 0.5
        prev["price_chg_pct"] = 20.0
        prev["direction"] = "up"
        prev["cvd_delta"] = 10.0

        # current: up 10%, CVD -20 (divergent, negative while up) and M high
        curr = daily_effort_record("M", "2026-08-02", 120, 132, -20)  # up 10%, CVD -20
        curr["price_chg_pct"] = 10.0
        curr["direction"] = "up"
        curr["cvd_delta"] = -20.0
        curr["ratio"] = 2.0  # M=4.0 >=2

        res = classify_at([prev, curr], 1)
        self.assertEqual(res["signal"], "S3_DISTRIBUSI_KE_KUAT")
        self.assertEqual(res["bias"], "bearish")
        self.assertTrue(res["flag_divergence"])

    def test_s3_non_divergent_falls_to_s5(self):
        prev = daily_effort_record("M", "2026-08-01", 100, 120, 10)
        prev["ratio"] = 0.5
        prev["price_chg_pct"] = 20.0
        prev["direction"] = "up"
        prev["cvd_delta"] = 10.0

        curr = daily_effort_record("M", "2026-08-02", 120, 132, 20)  # up, CVD positive (searah)
        curr["price_chg_pct"] = 10.0
        curr["direction"] = "up"
        curr["cvd_delta"] = 20.0
        curr["ratio"] = 2.0  # M=4

        res = classify_at([prev, curr], 1)
        self.assertEqual(res["signal"], "S5_NETRAL")
        self.assertIn("bukan penyerapan/distribusi murni", res["baseline_reason"])

    def test_s1_non_divergent_falls_to_s5(self):
        # S1 down direction but CVD negative (searah) and M>=2 -> should be S5 with reason
        # Avoid ABSORBSI by making CVD negative
        prev = daily_effort_record("M", "2026-08-01", 100, 80, -10)  # down 20%
        prev["ratio"] = 0.5
        prev["price_chg_pct"] = -20.0
        prev["direction"] = "down"
        prev["cvd_delta"] = -10.0

        curr = daily_effort_record("M", "2026-08-02", 80, 64, -32)  # down 20%, CVD -32 (searah)
        curr["price_chg_pct"] = -20.0
        curr["direction"] = "down"
        curr["cvd_delta"] = -32.0
        curr["ratio"] = 1.6  # M=3.2

        res = classify_at([prev, curr], 1)
        self.assertEqual(res["signal"], "S5_NETRAL")
        self.assertIn("bukan penyerapan/distribusi murni", res["baseline_reason"])

    def test_s1_divergent_is_absorbsi_due_to_priority(self):
        # down + CVD positive >=5 should be ABSORBSI, not S1, due to priority
        prev = daily_effort_record("M", "2026-08-01", 100, 80, -10)
        prev["ratio"] = 0.5
        prev["price_chg_pct"] = -20.0
        prev["direction"] = "down"
        prev["cvd_delta"] = -10.0

        curr = daily_effort_record("M", "2026-08-02", 80, 64, 32)  # down, CVD +32 divergent
        curr["price_chg_pct"] = -20.0
        curr["direction"] = "down"
        curr["cvd_delta"] = 32.0
        curr["ratio"] = 1.6

        res = classify_at([prev, curr], 1)
        # Should be ABSORBSI because checked first
        self.assertEqual(res["signal"], "ABSORBSI_LANGSUNG")

    # --- (d) floor 5.0 noise ---
    def test_floor_5_noise(self):
        prev = daily_effort_record("M", "2026-08-01", 100, 80, -10)
        prev["price_chg_pct"] = -20.0
        prev["direction"] = "down"
        prev["ratio"] = 0.5
        prev["cvd_delta"] = -10.0

        curr = daily_effort_record("M", "2026-08-02", 80, 70, -2)  # |CVD|=2 <5
        curr["price_chg_pct"] = -12.5
        curr["direction"] = "down"
        curr["cvd_delta"] = -2.0
        curr["ratio"] = 0.16

        res = classify_at([prev, curr], 1)
        self.assertEqual(res["signal"], "S5_NETRAL")
        self.assertEqual(res["baseline_status"], "noise")
        self.assertIn("< minimum", res["baseline_reason"])

    def test_floor_exact_5_is_not_noise(self):
        prev = daily_effort_record("M", "2026-08-01", 100, 80, -10)
        prev["ratio"] = 0.5
        prev["price_chg_pct"] = -20.0
        prev["direction"] = "down"
        prev["cvd_delta"] = -10.0

        curr = daily_effort_record("M", "2026-08-02", 80, 64, -5)  # exactly 5
        curr["price_chg_pct"] = -20.0
        curr["direction"] = "down"
        curr["cvd_delta"] = -5.0
        curr["ratio"] = 0.25

        res = classify_at([prev, curr], 1)
        # |CVD|=5 should not be noise, should go to stable path (maybe S2 etc)
        self.assertNotEqual(res["baseline_status"], "noise")

    # --- (e) batas hari UTC ---
    def test_day_boundary_is_utc(self):
        # 00:30 UTC same market day, 23:59 UTC same day, +2min cross
        ts1 = int(datetime.fromisoformat("2026-08-01T00:30:00+00:00").timestamp())
        rows = calculate_daily_cvd([("buy", 3.0, ts1, "A"), ("sell", 1.0, ts1 + 60, "B")])
        self.assertEqual(rows[0]["date"], "2026-08-01")

        ts2 = int(datetime.fromisoformat("2026-08-01T23:59:00+00:00").timestamp())
        rows2 = calculate_daily_cvd([("buy", 3.0, ts2, "A"), ("sell", 1.0, ts2 + 120, "B")])
        self.assertEqual(len(rows2), 2)
        self.assertEqual(rows2[0]["date"], "2026-08-01")
        self.assertEqual(rows2[1]["date"], "2026-08-02")

        # WIB midnight (00:00 WIB = 17:00 UTC previous day) should NOT roll day if using UTC
        # 2026-08-02 00:00 WIB = 2026-08-01 17:00 UTC => date should be 2026-08-01 in UTC logic
        ts_wib_midnight = int(datetime.fromisoformat("2026-08-01T17:00:00+00:00").timestamp())
        self.assertEqual(day_key(ts_wib_midnight), "2026-08-01")

    # --- (f) insufficient_baseline ---
    def test_insufficient_baseline(self):
        # Only one day that is not ABSORBSI
        single = daily_effort_record("M", "2026-08-01", 100, 90, -2)  # |CVD|<5 => noise, not healthy baseline
        res = classify_at([single], 0)
        # Single day noise -> S5 noise, not insufficient? Actually first day with no baseline and not absorpsi -> insufficient or noise?
        # For a day with |CVD|<5, floor triggers noise S5
        self.assertEqual(res["signal"], "S5_NETRAL")

        # Two days where previous is unhealthy (ratio too small)
        prev = daily_effort_record("M", "2026-08-01", 100, 120, 0.1)
        prev["ratio"] = 0.01  # <0.05
        prev["price_chg_pct"] = 20.0
        prev["direction"] = "up"
        prev["cvd_delta"] = 0.1

        curr = daily_effort_record("M", "2026-08-02", 120, 100, -10)
        curr["price_chg_pct"] = -16.66
        curr["direction"] = "down"
        curr["cvd_delta"] = -10.0
        curr["ratio"] = 0.6

        res2 = classify_at([prev, curr], 1)
        self.assertEqual(res2["baseline_status"], "insufficient_baseline")
        self.assertEqual(res2["signal"], "insufficient_data")

    def test_baseline_walkback_not_require_consecutive(self):
        # Gap of 2 days still finds baseline (no consecutive requirement)
        d1 = daily_effort_record("M", "2026-08-01", 100, 80, -10)
        d1["ratio"] = 0.5
        d1["price_chg_pct"] = -20.0
        d1["direction"] = "down"
        d1["cvd_delta"] = -10.0

        d3 = daily_effort_record("M", "2026-08-03", 80, 64, -5)
        d3["price_chg_pct"] = -20.0
        d3["direction"] = "down"
        d3["cvd_delta"] = -5.0
        d3["ratio"] = 0.25

        res = classify_at([d1, d3], 1)
        # Should find d1 as baseline despite 1-day gap
        self.assertNotEqual(res["baseline_status"], "insufficient_baseline")
        self.assertEqual(res["previous_date"], "2026-08-01")

    # --- Existing functionality regression ---
    def test_small_price_move_is_neutral(self):
        prev = daily_effort_record("M", "2026-08-01", 100, 80, -10)
        prev["ratio"] = 0.5
        prev["price_chg_pct"] = -20.0
        prev["direction"] = "down"
        prev["cvd_delta"] = -10.0

        curr = daily_effort_record("M", "2026-08-02", 80, 78, -10)  # -2.5%
        curr["price_chg_pct"] = -2.5
        curr["direction"] = "down"
        curr["cvd_delta"] = -10.0
        curr["ratio"] = 4.0

        res = classify_at([prev, curr], 1)
        self.assertEqual(res["signal"], "S5_NETRAL")

    def test_merge_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "daily.json")
            rows = [daily_effort_record("M", f"2026-08-{day:02d}", 100, 90, -day)
                    for day in range(1, 6)]
            first = merge_daily_effort(rows, path=path, retention_days=3)
            second = merge_daily_effort(rows[-1:], path=path, retention_days=3)
            self.assertEqual(first, second)
            self.assertEqual([row["date"] for row in second],
                             ["2026-08-03", "2026-08-04", "2026-08-05"])

    def test_classify_all_scan(self):
        rows = [
            daily_effort_record("M", "2026-08-01", 100, 80, -10),
            daily_effort_record("M", "2026-08-02", 80, 78, 6),  # absorpsi flat +6
            daily_effort_record("M", "2026-08-03", 78, 60, -40),  # flush
            daily_effort_record("M", "2026-08-04", 60, 55, -10),  # exhaustion? -10 vs -40 => 25%
        ]
        # fix ratios
        rows[0]["ratio"] = 0.5
        rows[0]["price_chg_pct"] = -20.0
        rows[0]["direction"] = "down"
        rows[0]["cvd_delta"] = -10.0

        rows[1]["price_chg_pct"] = -2.5
        rows[1]["direction"] = "down"
        rows[1]["cvd_delta"] = 6.0
        rows[1]["ratio"] = 2.4

        rows[2]["price_chg_pct"] = -23.07
        rows[2]["direction"] = "down"
        rows[2]["cvd_delta"] = -40.0
        rows[2]["ratio"] = 1.73

        rows[3]["price_chg_pct"] = -8.33
        rows[3]["direction"] = "down"
        rows[3]["cvd_delta"] = -10.0
        rows[3]["ratio"] = 1.2

        results = classify_all(rows)
        self.assertEqual(len(results), 4)
        # day2 should be absorpsi (CVD +6, price -2.5 <=0.5)
        self.assertEqual(results[1]["signal"], "ABSORBSI_LANGSUNG")
        # day4 should be exhaustion (flush -40 -> -10, 25%)
        self.assertEqual(results[3]["signal"], "SELLING_EXHAUSTION")


if __name__ == "__main__":
    unittest.main()
