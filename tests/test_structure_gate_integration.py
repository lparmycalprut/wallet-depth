"""Scanner still classifies a fixture stream without crashing."""
import json
import unittest
from pathlib import Path

from scripts.realtime_reversal import scan_token
from serok_engine import NEUTRAL, SIAP2_PUMP, WASPADA_DUMP, BATTLE

FIXTURE = Path(__file__).parent / "fixtures" / "dregg_15m.json"
MINT = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"


def _trades_from_fixture(now_ts: int) -> list[dict]:
    bars = sorted(json.loads(FIXTURE.read_text()), key=lambda b: b[0])
    trades = []
    for i, (ts, o, _h, _l, c, _v) in enumerate(bars):
        current = ts >= now_ts - 6 * 3600
        buy_sol, sell_sol = (1.30, 0.20) if current else (0.20, 1.20)
        trades.append({"maker": f"b{i}", "event": "buy", "timestamp": ts + 60,
                       "quote_amount": buy_sol, "price_usd": o,
                       "amount_usd": buy_sol * 160, "base_amount": 1})
        trades.append({"maker": f"s{i}", "event": "sell",
                       "timestamp": ts + 120, "quote_amount": sell_sol,
                       "price_usd": c, "amount_usd": sell_sol * 160,
                       "base_amount": 1})
    return trades


class SerokScanIntegrationTest(unittest.TestCase):
    def test_scan_token_returns_serok_signal(self):
        now_ts = 1787015700 + 300
        state, cache = {}, {}
        row = scan_token(MINT, {"symbol": "DREGG"}, now_ts=now_ts,
                         cache=cache, state=state,
                         fixture=_trades_from_fixture(now_ts),
                         send_alerts=False)
        self.assertIn(row["signal"],
                      {NEUTRAL, WASPADA_DUMP, SIAP2_PUMP, BATTLE})
        self.assertIn("state", row)


if __name__ == "__main__":
    unittest.main()
