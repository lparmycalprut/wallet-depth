"""Scanner still classifies a fixture stream without crashing."""
import json
import unittest
from pathlib import Path
from unittest import mock

from reversal_status import snapshot_status
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

    def test_gmgn_fetch_failure_is_neutral_not_crash(self):
        mint = "488SaFq6wHF2z2k6NLSD3PtoSkXDNZaPkJwxze11pump"
        state, cache = {}, {}
        with mock.patch("scripts.realtime_reversal.fetch_raw_trades",
                        side_effect=RuntimeError(
                            "HTTP 403 Cloudflare cf-mitigated=challenge")), \
                mock.patch("scripts.realtime_reversal._market_guards",
                           return_value=(True, "", {})), \
                mock.patch("scripts.realtime_reversal.get_gmgn_last_error",
                           return_value="HTTP 403 Cloudflare"):
            row = scan_token(mint, {"symbol": "MOMO"}, now_ts=1_700_000_000,
                             cache=cache, state=state, send_alerts=False)
        self.assertEqual(row["signal"], NEUTRAL)
        self.assertIn("GMGN fetch gagal", row["reason"])
        self.assertIn("403", row["reason"])
        self.assertIn(mint, state)
        self.assertEqual(state[mint]["result"]["signal"], NEUTRAL)
        snap = snapshot_status(state, {mint: {"symbol": "MOMO"}})
        self.assertEqual(snap["tokens"][mint]["symbol"], "MOMO")
        self.assertIn("GMGN fetch gagal", snap["tokens"][mint]["reason"])

    def test_main_exits_0_and_publishes_momo_on_fetch_failure(self):
        import scripts.realtime_reversal as rr

        mint = "488SaFq6wHF2z2k6NLSD3PtoSkXDNZaPkJwxze11pump"
        with mock.patch.object(rr, "load_watchlist",
                               return_value={mint: {"symbol": "MOMO"}}), \
                mock.patch.object(rr, "load_state", return_value={}), \
                mock.patch.object(rr, "load_cache", return_value={}), \
                mock.patch.object(rr, "save_cache"), \
                mock.patch.object(rr, "save_state"), \
                mock.patch.object(rr, "process_telegram_callbacks"), \
                mock.patch.object(rr, "publish_reversal_status") as publish, \
                mock.patch.object(rr, "fetch_raw_trades",
                                  side_effect=RuntimeError(
                                      "HTTP 403 Cloudflare")), \
                mock.patch.object(rr, "_market_guards",
                                  return_value=(True, "", {})), \
                mock.patch.object(rr, "get_gmgn_last_error",
                                  return_value="HTTP 403 Cloudflare"):
            rc = rr.main(["--no-alert"])
        self.assertEqual(rc, 0)
        publish.assert_called_once()
        published = publish.call_args.args[0]
        self.assertIn(mint, published)
        self.assertEqual(published[mint]["result"]["signal"], NEUTRAL)
        self.assertIn("GMGN fetch gagal", published[mint]["result"]["reason"])


if __name__ == "__main__":
    unittest.main()
