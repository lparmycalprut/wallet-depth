import unittest

from reversal_engine import (
    NEUTRAL, REVERSAL_DOWN, REVERSAL_UP, ReversalConfig,
    annotate_matched_amounts, detect_reversal, normalize_trade_item,
)
from reversal_state import transition


class ReversalEngineTests(unittest.TestCase):
    def test_normalize_rederives_broken_quote_amount(self):
        row = normalize_trade_item({
            "maker": "wallet", "event": "buy", "timestamp": 1_700_000_000,
            "quote_amount": 100_000, "amount_usd": 160, "price_usd": 0.1,
        })
        self.assertAlmostEqual(row["sol"], 1.0)

    def test_fifo_wash_matcher_marks_both_sides(self):
        rows = [
            {"maker": "a", "event": "buy", "sol": 3.0, "ts": 100, "matched": 0},
            {"maker": "a", "event": "sell", "sol": 2.0, "ts": 130, "matched": 0},
            {"maker": "a", "event": "sell", "sol": 2.0, "ts": 200, "matched": 0},
        ]
        annotate_matched_amounts(rows)
        self.assertEqual([row["matched"] for row in rows], [2.0, 2.0, 0.0])

    def _window(self, clean, wash, price=0, tx=30, vol=100):
        return {"cvd_delta_clean": clean, "wash_pct": wash,
                "price_chg_pct": price, "tx_count": tx, "vol_sol": vol}

    def test_bidirectional_reversals(self):
        cfg = ReversalConfig(current_cvd_min=1)
        up = detect_reversal(self._window(8, 3, 10),
                             self._window(-20, 15, -25), cfg)
        down = detect_reversal(self._window(-8, 3, -10),
                               self._window(20, 15, 25), cfg)
        self.assertEqual(up["signal"], REVERSAL_UP)
        self.assertEqual(down["signal"], REVERSAL_DOWN)

    def test_false_positive_guards(self):
        cfg = ReversalConfig(current_cvd_min=1)
        thin = detect_reversal(self._window(8, 3, tx=2),
                               self._window(-20, 15, -25), cfg)
        no_context = detect_reversal(self._window(8, 3),
                                     self._window(-2, 15, -1), cfg)
        self.assertEqual(thin["signal"], NEUTRAL)
        self.assertEqual(no_context["signal"], NEUTRAL)

    def test_state_requires_two_scans_and_cooldown(self):
        first, alert = transition({}, REVERSAL_UP, 1_000)
        self.assertFalse(alert)
        second, alert = transition(first, REVERSAL_UP, 1_300)
        self.assertTrue(alert)
        repeated, alert = transition(second, REVERSAL_UP, 1_600)
        self.assertFalse(alert)
        self.assertEqual(repeated["state"], "REVERSAL_UP_FIRED")


if __name__ == "__main__":
    unittest.main()
