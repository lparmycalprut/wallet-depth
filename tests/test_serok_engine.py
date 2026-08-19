"""Parity tests for SMART SEROK 1H signals."""
from __future__ import annotations

import unittest

from serok_engine import (BATTLE, NEUTRAL, SIAP2_PUMP, WASPADA_DUMP,
                          bar_floor, build_bars, classify, scan_signals)


def _trade(maker, event, ts, sol, price, tags=None):
    return {
        "maker": maker, "event": event, "timestamp": ts,
        "quote_amount": sol, "amount_usd": sol * 160, "price_usd": price,
        "maker_tags": tags or [],
    }


class SerokEngineTests(unittest.TestCase):
    def test_bar_floor_hour(self):
        self.assertEqual(bar_floor(1_700_000_100), (1_700_000_100 // 3600) * 3600)

    def test_waspada_dump_on_r_spike_up(self):
        t0 = 1_700_000_000
        trades = []
        # bar 0: small R
        trades += [
            _trade("a", "buy", t0 + 10, 1, 1.0),
            _trade("b", "sell", t0 + 20, 0.5, 1.01),
        ]
        # bar 1: price up + large clean buy CVD → high R, cumCVD up
        t1 = t0 + 3600
        for i in range(20):
            trades.append(_trade(f"w{i}", "buy", t1 + i, 5, 1.02 + i * 0.0001))
        bars = build_bars(trades, now_ts=t1 + 3500)
        events = scan_signals(bars)
        kinds = [e["signal"] for e in events]
        self.assertIn(WASPADA_DUMP, kinds)

    def test_siap2_pump_on_r_spike_down(self):
        t0 = 1_700_000_000
        trades = [
            _trade("a", "sell", t0 + 10, 1, 1.0),
            _trade("b", "buy", t0 + 20, 0.4, 0.99),
        ]
        t1 = t0 + 3600
        for i in range(20):
            trades.append(_trade(f"s{i}", "sell", t1 + i, 5, 0.98 - i * 0.0001))
        bars = build_bars(trades, now_ts=t1 + 3500)
        kinds = [e["signal"] for e in scan_signals(bars)]
        self.assertIn(SIAP2_PUMP, kinds)

    def test_battle_requires_prior_setup(self):
        t0 = 1_700_000_000
        trades = []
        # 8 completed balanced bars with fresh wallets, no R spike
        for h in range(9):
            start = t0 + h * 3600
            for i in range(25):
                ev = "buy" if i % 2 == 0 else "sell"
                trades.append(_trade(
                    f"m{h}_{i}", ev, start + i * 10, 1.0, 1.0,
                    tags=["fresh_wallet"]))
        bars = build_bars(trades, now_ts=t0 + 9 * 3600 + 10)
        kinds = [e["signal"] for e in scan_signals(bars)]
        self.assertNotIn(BATTLE, kinds)

    def test_neutral_when_empty(self):
        self.assertEqual(classify([])["signal"], NEUTRAL)

    def test_all_events_covers_prior_cluster_signals(self):
        from serok_engine import all_events
        t0 = 1_700_000_000
        trades = [
            _trade("a", "buy", t0 + 10, 1, 1.0),
            _trade("b", "sell", t0 + 20, 0.5, 1.01),
        ]
        t1 = t0 + 3600
        for i in range(20):
            trades.append(_trade(f"w{i}", "buy", t1 + i, 5, 1.02 + i * 0.0001))
        # gap > 6h then another spike
        t2 = t1 + 8 * 3600
        trades += [
            _trade("c", "sell", t2 + 10, 1, 1.0),
            _trade("d", "buy", t2 + 20, 0.4, 0.99),
        ]
        t3 = t2 + 3600
        for i in range(20):
            trades.append(_trade(f"s{i}", "sell", t3 + i, 5, 0.98 - i * 0.0001))
        bars = build_bars(trades, now_ts=t3 + 3500)
        kinds = [e["signal"] for e in all_events(bars)]
        self.assertIn(WASPADA_DUMP, kinds)
        self.assertIn(SIAP2_PUMP, kinds)

    def test_take_new_events_alerts_historical_once(self):
        from reversal_state import take_new_events
        events = [
            {"event_id": "WASPADA DUMP:1", "signal": WASPADA_DUMP},
            {"event_id": "SIAP2 PUMP:2", "signal": SIAP2_PUMP},
        ]
        state, fresh = take_new_events({}, events)
        self.assertEqual(len(fresh), 2)
        state, again = take_new_events(state, events)
        self.assertEqual(again, [])

    def test_symbol_fetch_helper_exists(self):
        from watchlist import fetch_token_symbol
        from unittest.mock import patch
        with patch("core.get_market", return_value={"symbol": "PEPE"}):
            self.assertEqual(fetch_token_symbol("SomeMint111"), "PEPE")
        with patch("core.get_market", side_effect=RuntimeError("down")):
            self.assertEqual(fetch_token_symbol("SomeMint111"), "?")


if __name__ == "__main__":
    unittest.main()
