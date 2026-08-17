import unittest

from reversal_engine import REVERSAL_DOWN, REVERSAL_UP, ReversalConfig, detect_reversal
from scripts.backtest_confidence import group_by_mint, run


def _window(clean, wash, price=0, tx=30, vol=100):
    return {"cvd_delta_clean": clean, "wash_pct": wash, "price_chg_pct": price,
            "tx_count": tx, "vol_sol": vol}


class BacktestConfidenceTests(unittest.TestCase):
    def test_legacy_daily_rows_can_never_reach_strong(self):
        """Baris harian lama tak punya wash_pct, jadi strong mustahil muncul."""
        rows = [{"mint": "A", "date": f"2026-08-{day:02d}", "cvd_delta": -40 + day,
                 "price_chg_pct": -20 + day} for day in range(10, 20)]
        report = run(rows)
        self.assertEqual(report["strong_count"], 0)
        self.assertEqual(report["reversal_signals"], 0)
        self.assertEqual(report["rows_with_wash_field"], 0)
        self.assertIn("tanpa field wash_pct (data harian lama)",
                      report["blocking_gates"])

    def test_group_by_mint_sorts_by_date(self):
        rows = [{"mint": "A", "date": "2026-08-12"}, {"mint": "A", "date": "2026-08-10"},
                {"mint": "B", "date": "2026-08-11"}]
        grouped = group_by_mint(rows)
        self.assertEqual([r["date"] for r in grouped["A"]],
                         ["2026-08-10", "2026-08-12"])
        self.assertEqual(len(grouped["B"]), 1)

    def test_strong_boundary_up(self):
        """+5.0 SOL / 3.0% wash adalah batas inklusif menuju strong."""
        cfg = ReversalConfig(current_cvd_min=0)
        context = _window(-20, 15, -25)
        self.assertEqual(detect_reversal(_window(5.0, 3.0), context, cfg)["confidence"],
                         "strong")
        for cvd, wash in ((4.9, 3.0), (5.0, 3.1), (0.7, 0.0)):
            result = detect_reversal(_window(cvd, wash), context, cfg)
            self.assertEqual(result["signal"], REVERSAL_UP)
            self.assertEqual(result["confidence"], "watch", (cvd, wash))

    def test_strong_boundary_down(self):
        cfg = ReversalConfig(current_cvd_min=0)
        context = _window(20, 15, 25)
        self.assertEqual(detect_reversal(_window(-5.0, 3.0), context, cfg)["confidence"],
                         "strong")
        result = detect_reversal(_window(-4.9, 3.0), context, cfg)
        self.assertEqual(result["signal"], REVERSAL_DOWN)
        self.assertEqual(result["confidence"], "watch")

    def test_live_alert_sample_is_watch_because_of_cvd(self):
        """Reproduksi alert $MOVER: gagal strong murni karena CVD +0.7 SOL."""
        cfg = ReversalConfig(current_cvd_min=0)
        result = detect_reversal(_window(0.7, 0.0, 3.1), _window(-12.9, 6.2, -20), cfg)
        self.assertEqual(result["signal"], REVERSAL_UP)
        self.assertEqual(result["confidence"], "watch")
        stronger = detect_reversal(_window(5.2, 0.0, 3.1), _window(-12.9, 6.2, -20), cfg)
        self.assertEqual(stronger["confidence"], "strong")


if __name__ == "__main__":
    unittest.main()
