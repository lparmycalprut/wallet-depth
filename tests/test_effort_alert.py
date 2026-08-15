import unittest

from signals import format_effort_alert, should_send_telegram


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

    def test_absorbsi_alert_format(self):
        result = {
            "mint": "Mint123", "date": "2026-06-17",
            "previous_date": "2026-06-16", "signal": "ABSORBSI_LANGSUNG",
            "bias": "bullish", "ratio_N": 1.11,
            "ratio_N_minus_1": None, "multiplier": None,
            "price_chg_pct": -22.4, "cvd_delta": 24.88,
            "flag_divergence": True,
            "baseline_status": "direct",
        }
        text = format_effort_alert("TEST", result)
        self.assertIn("ABSORBSI LANGSUNG", text)
        self.assertIn("bullish", text)
        self.assertIn("Mint123", text)
        self.assertTrue(should_send_telegram(result))

    def test_selling_exhaustion_alert_format(self):
        result = {
            "mint": "Mint123", "date": "2026-07-16",
            "previous_date": "2026-07-10", "signal": "SELLING_EXHAUSTION",
            "bias": "bullish", "ratio_N": 0.326,
            "price_chg_pct": -47.1, "cvd_delta": -15.36,
            "flag_divergence": False,
            "baseline_status": "direct",
            "flush_date": "2026-07-10",
            "flush_cvd": -946.0,
            "exhaustion_pct": 3.0,
        }
        text = format_effort_alert("TEST", result)
        self.assertIn("SELLING EXHAUSTION", text)
        self.assertIn("flush", text.lower())
        self.assertIn("runtuh", text.lower())
        self.assertTrue(should_send_telegram(result))

    def test_should_send_telegram_gate(self):
        # old signals need stable
        s1_stable = {"signal": "S1_PENYERAPAN", "baseline_status": "stable", "date": "2026-08-02"}
        self.assertTrue(should_send_telegram(s1_stable))
        s1_unstable = {"signal": "S1_PENYERAPAN", "baseline_status": "unstable", "date": "2026-08-02"}
        self.assertFalse(should_send_telegram(s1_unstable))
        s5 = {"signal": "S5_NETRAL", "baseline_status": "stable", "date": "2026-08-02"}
        self.assertFalse(should_send_telegram(s5))
        # new signals should send even with direct status
        abs_direct = {"signal": "ABSORBSI_LANGSUNG", "baseline_status": "direct", "date": "2026-08-02"}
        self.assertTrue(should_send_telegram(abs_direct))
        exh_direct = {"signal": "SELLING_EXHAUSTION", "baseline_status": "direct", "date": "2026-08-02"}
        self.assertTrue(should_send_telegram(exh_direct))


if __name__ == "__main__":
    unittest.main()
