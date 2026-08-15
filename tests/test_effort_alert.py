import unittest

from signals import format_effort_alert


class EffortAlertTest(unittest.TestCase):
    def test_alert_contains_only_effort_fields(self):
        result = {
            "mint": "Mint123", "date": "2026-08-02",
            "previous_date": "2026-08-01", "signal": "S1_PENYERAPAN",
            "bias": "bullish", "ratio_N": 1.0,
            "ratio_N_minus_1": 0.4, "multiplier": 2.5,
            "price_chg_pct": -20, "cvd_delta": 20,
            "flag_divergence": True,
        }
        text = format_effort_alert("TEST", result)
        self.assertIn("ANOMALI EFISIENSI", text)
        self.assertIn("×2.50", text)
        self.assertIn("divergensi arah CVD", text)
        self.assertIn("Mint123", text)


if __name__ == "__main__":
    unittest.main()
