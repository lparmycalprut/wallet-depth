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

    def test_wallet_depth_metrics(self):
        from reversal_engine import aggregate_window, normalize_trades
        trades = normalize_trades([
            {"maker": "whale", "event": "buy", "quote_amount": 10,
             "amount_usd": 1600, "price_usd": 1, "timestamp": 100},
            {"maker": "whale", "event": "sell", "quote_amount": 4,
             "amount_usd": 640, "price_usd": 1, "timestamp": 500},
            {"maker": "sm", "event": "buy", "quote_amount": 3, "amount_usd": 480,
             "price_usd": 1, "timestamp": 200, "maker_tags": ["smart_money"]},
            {"maker": "fr", "event": "buy", "quote_amount": 3, "amount_usd": 480,
             "price_usd": 1, "timestamp": 300, "maker_tags": ["fresh_wallet"]},
        ])
        annotate_matched_amounts(trades)
        win = aggregate_window(trades)
        self.assertAlmostEqual(win["top_wallet_pct"], 70.0)
        self.assertAlmostEqual(win["top3_wallet_pct"], 100.0)
        self.assertAlmostEqual(win["top_wallet_net_sol"], 6.0)
        # 14 SOL churned by the whale for 6 SOL of net exposure.
        self.assertAlmostEqual(win["top_wallet_churn_pct"], 100 * (1 - 6 / 14))
        self.assertAlmostEqual(win["smart_net_sol"], 3.0)
        self.assertAlmostEqual(win["fresh_buy_sol"], 3.0)

    def test_whale_verdict_and_confidence_gap(self):
        from scripts.realtime_reversal import _confidence_gap, _whale_verdict
        self.assertEqual(_whale_verdict(10, 90, -5), "terdistribusi")
        self.assertEqual(_whale_verdict(59, 95, 0.2), "muter sendiri")
        self.assertEqual(_whale_verdict(59, 10, 8), "akumulasi")
        self.assertEqual(_whale_verdict(59, 10, -8), "distribusi")
        gap = _confidence_gap({"signal": REVERSAL_UP, "confidence": "watch",
                               "current": {"cvd_delta_clean": 0.7, "wash_pct": 0.0}})
        self.assertIn("belum +5.0 SOL", gap)
        self.assertNotIn("wash", gap)
        self.assertEqual(_confidence_gap({"signal": REVERSAL_UP,
                                          "confidence": "strong"}), "")

    def test_state_requires_two_scans_and_cooldown(self):
        first, alert = transition({}, REVERSAL_UP, 1_000)
        self.assertFalse(alert)
        second, alert = transition(first, REVERSAL_UP, 1_300)
        self.assertTrue(alert)
        repeated, alert = transition(second, REVERSAL_UP, 1_600)
        self.assertFalse(alert)
        self.assertEqual(repeated["state"], "REVERSAL_UP_FIRED")

    def test_unconfirmed_structure_arms_watch_without_alert(self):
        # Flow lolos 2 scan tapi struktur belum reclaim → WATCH, tanpa alert.
        first, _ = transition({}, REVERSAL_UP, 1_000, structure_state="forming")
        second, alert = transition(first, REVERSAL_UP, 1_300,
                                   structure_state="forming")
        self.assertFalse(alert)
        self.assertEqual(second["state"], "WATCH")
        # Struktur mengonfirmasi pada scan ketiga → alert menyala dari WATCH.
        third, alert = transition(second, REVERSAL_UP, 1_600,
                                  structure_state="confirmed")
        self.assertTrue(alert)
        self.assertEqual(third["state"], "REVERSAL_UP_FIRED")

    def test_watch_clears_back_to_none_when_flow_fades(self):
        first, _ = transition({}, REVERSAL_DOWN, 1_000, structure_state="forming")
        second, alert = transition(first, REVERSAL_DOWN, 1_300,
                                   structure_state="forming")
        self.assertFalse(alert)
        self.assertEqual(second["state"], "WATCH")
        faded, alert = transition(second, NEUTRAL, 1_600)
        self.assertFalse(alert)
        cleared, _ = transition(faded, NEUTRAL, 1_900)
        self.assertEqual(cleared["state"], "NONE")

    def test_no_zone_never_alerts(self):
        state = {}
        for i in range(4):
            state, alert = transition(state, REVERSAL_UP, 1_000 + i * 300,
                                      structure_state="no_zone")
            self.assertFalse(alert)
        self.assertEqual(state["state"], "WATCH")


if __name__ == "__main__":
    unittest.main()
