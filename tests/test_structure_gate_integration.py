"""Integrasi: scan_token + gate struktur, memakai stream trade yang
disederhanakan dari candle asli DREGG (17–18 Agu 2026).

Alur yang diverifikasi:
- sebelum candle breakout tutup: sinyal flow REVERSAL_UP kuat tetapi state
  parkir di WATCH — tidak ada alert;
- setelah close menembus zona SBR: alert menyala (should_alert=True).
"""
import json
import unittest
from pathlib import Path

from price_structure import CONFIRMED, StructureConfig
from scripts.realtime_reversal import scan_token

FIXTURE = Path(__file__).parent / "fixtures" / "dregg_15m.json"
MINT = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"


def _trades_from_fixture(now_ts: int) -> list[dict]:
    """Dua trade per candle 15m (open/close). Arah buy/sell direkayasa supaya
    window current 6 jam ber-CVD bersih positif kuat dan baseline 24 jam
    membawa flush (sell dominan + sedikit wash round-trip)."""
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
        if not current:  # wash di baseline: round-trip maker sama <60 detik
            trades.append({"maker": f"w{i}", "event": "buy",
                           "timestamp": ts + 130, "quote_amount": 0.5,
                           "price_usd": c, "amount_usd": 80.0, "base_amount": 1})
            trades.append({"maker": f"w{i}", "event": "sell",
                           "timestamp": ts + 150, "quote_amount": 0.5,
                           "price_usd": c, "amount_usd": 80.0, "base_amount": 1})
    return trades


class StructureGateIntegrationTest(unittest.TestCase):
    def test_watch_before_breakout_close_then_fire_after(self):
        # Skenario 1: now = 08:20 WIB — candle 5m terakhir yang tutup adalah
        # 08:15 (close 0.0002644 < zona). Flow kuat, struktur forming.
        early = 1787015700 + 300  # 08:20 WIB
        state = {}
        cache = {}
        row = None
        for _ in range(2):  # konfirmasi 2 scan
            row = scan_token(MINT, {"symbol": "DREGG"}, now_ts=early,
                             cache=cache, state=state,
                             fixture=_trades_from_fixture(early),
                             send_alerts=True)
        self.assertEqual(row["signal"], "REVERSAL_UP")
        self.assertFalse(row["should_alert"])         # tertahan oleh struktur
        self.assertEqual(row["state"], "WATCH")
        self.assertEqual(state[MINT]["structure"]["state"], "forming")

        # Skenario 2: now = 09:05 WIB — zona sudah ter-reclaim by close.
        late = 1787017500 + 1200
        row = scan_token(MINT, {"symbol": "DREGG"}, now_ts=late, cache=cache,
                         state=state, fixture=_trades_from_fixture(late),
                         send_alerts=True)
        self.assertEqual(state[MINT]["structure"]["state"], CONFIRMED)
        self.assertTrue(row["should_alert"])          # alert sah
        self.assertEqual(row["state"], "REVERSAL_UP_FIRED")
        self.assertFalse(state[MINT]["alert_sent"])   # telegram tak terkonfigurasi


if __name__ == "__main__":
    unittest.main()
