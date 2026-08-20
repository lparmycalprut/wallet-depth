"""Coverage for realtime reversal badges on the main watchlist.

The watchlist now renders the latest scanner snapshot (REVERSAL UP/DOWN,
setup, or NEUTRAL) rather than the historical daily-effort verdict.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from reversal_engine import REVERSAL_DOWN, REVERSAL_UP
from reversal_status import snapshot_status
from serok_engine import BATTLE, SIAP2_PUMP, WASPADA_DUMP
from serok_engine import NEUTRAL as SEROK_NEUTRAL

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

APP = str(Path(__file__).resolve().parent.parent / "app.py")
MINT = "MintBottom"


def _row(signal, *, confidence="watch", current=None, context=None,
         reason="", event=None):
    return snapshot_status({
        "_meta": {"updated_at": 1_700_000_000, "scanner": "rolling-6h-v1"},
        MINT: {
            "state": f"{signal}_FIRED" if (
                signal.startswith("REVERSAL")
                or signal in (WASPADA_DUMP, SIAP2_PUMP, BATTLE)
            ) else signal,
            "observed_signal": signal,
            "last_scan_ts": 1_700_000_000,
            "result": {
                "signal": signal, "confidence": confidence,
                "reason": reason,
                "current": current or {},
                "context": context or {},
                "event": event,
            },
        },
    }, {MINT: {"symbol": "TST"}})


@unittest.skipIf(AppTest is None, "streamlit not installed")
class SignalColumnRenderTest(unittest.TestCase):
    def _run(self, status, watchlist=None):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       return_value=watchlist or {MINT: {"symbol": "TST"}}),
            mock.patch("reversal_status.load_reversal_status",
                       return_value=status),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=30)
        app.run()
        self.assertFalse(app.exception)
        return "\n".join(block.value for block in app.markdown)

    def test_reversal_down_badge_and_wash_collapse(self):
        status = _row(
            REVERSAL_DOWN, confidence="strong",
            current={"cvd_delta_clean": -18.7, "wash_pct": 1.4,
                     "price_chg_pct": -27.5, "unique_makers": 152,
                     "smart_money_buy": 33, "smart_net_sol": -3.5,
                     "fresh_buy": 8, "fresh_buy_sol": 2.9, "bot_sell": 42,
                     "top_wallet_pct": 5.9, "top3_wallet_pct": 17.0,
                     "top_wallet_net_sol": 10.2, "top_wallet_churn_pct": 0},
            context={"cvd_delta_clean": 32.4, "wash_pct": 10.7},
            reason="wash runtuh + CVD bersih negatif setelah pump")
        body = self._run(status)
        self.assertIn('class="signal bear">REVERSAL DOWN', body)
        self.assertIn("wash 1.4%", body)
        self.assertIn('class="signal-detail bear"', body)

    def test_reversal_up_badge_is_green(self):
        status = _row(
            REVERSAL_UP, confidence="watch",
            current={"cvd_delta_clean": 4.0, "wash_pct": 2.0,
                     "price_chg_pct": 3.0},
            context={"cvd_delta_clean": -22.0, "wash_pct": 15.2})
        body = self._run(status)
        self.assertIn('class="signal bull">REVERSAL UP', body)
        self.assertIn("🟡 WATCH", body)

    def test_missing_scan_shows_placeholder(self):
        body = self._run({"updated_at": None, "tokens": {}})
        self.assertIn("BELUM ADA SCAN", body)

    def test_detail_text_is_always_white(self):
        status = _row(REVERSAL_UP, current={"cvd_delta_clean": 8,
                                            "wash_pct": 1.0})
        body = self._run(status)
        self.assertIn(".signal-detail.bull,", body)
        self.assertIn(".signal-detail.dist,", body)
        self.assertIn(".signal-detail.neutral {color:#ffffff !important}",
                      body)

    def test_waspada_dump_shows_r_spike_not_wash_collapse(self):
        status = _row(
            WASPADA_DUMP, confidence="info",
            current={"cvd_delta_clean": 22.0, "wash_pct": 4.0,
                     "price_chg_pct": 2.1, "tx_count": 40,
                     "unique_makers": 12, "R": 13.8, "signedR": 13.8,
                     "bar_start": 1_700_000_000},
            event={
                "signal": WASPADA_DUMP,
                "setup": {"start": 1_700_000_000, "washPct": 4.0,
                          "txCount": 40, "uniqueMakers": 12,
                          "cvdClean": 22.0, "price_chg_pct": 2.1},
                "ev": {"rMult": 12.5, "prevR": 1.1, "setupR": 13.8,
                       "setupChg": 2.1, "setupCvd": 22.0},
            })
        body = self._run(status)
        self.assertIn('class="signal bear">WASPADA DUMP', body)
        self.assertIn("R 1.10 → 13.80 (12.5×)", body)
        self.assertIn("Harga naik + cumCVD naik", body)
        self.assertIn("CVD +22.0 SOL", body)
        self.assertIn("40 TX · 12 wallet", body)
        self.assertNotIn("wash runtuh", body)
        self.assertNotIn("SBR ", body)
        self.assertNotIn("smart ", body)

    def test_siap2_pump_shows_down_r_spike(self):
        status = _row(
            SIAP2_PUMP, confidence="info",
            event={
                "signal": SIAP2_PUMP,
                "setup": {"start": 1_700_003_600, "txCount": 55,
                          "uniqueMakers": 18, "cvdClean": -31.2},
                "ev": {"rMult": 11.0, "prevR": 1.2, "setupR": -13.2,
                       "setupChg": -8.4, "setupCvd": -31.2},
            })
        body = self._run(status)
        self.assertIn('class="signal bull">SIAP2 PUMP', body)
        self.assertIn("Harga turun + cumCVD turun", body)
        self.assertIn("R 1.20 → 13.20 (11.0×)", body)
        self.assertIn("harga -8.4%", body)

    def test_battle_shows_balance_trigger_and_mc_range(self):
        status = _row(
            BATTLE, confidence="info",
            event={
                "signal": BATTLE,
                "setup": {"start": 1_700_007_200, "buySol": 45.2,
                          "sellSol": 44.8, "txCount": 142,
                          "uniqueMakers": 61, "freshWallets": 12,
                          "lowMc": 120_000, "highMc": 145_000,
                          "price_chg_pct": 0.4},
                "ev": {"balanceGapPct": 0.89, "txFloor": 80,
                       "makersFloor": 40, "freshFloor": 5,
                       "triggerSignal": SIAP2_PUMP,
                       "triggerStart": 1_700_000_000, "gap": 2,
                       "rangeLowMc": 120_000, "rangeHighMc": 145_000,
                       "setupChg": 0.4},
            })
        body = self._run(status)
        self.assertIn('class="signal watch">BATTLE TERJADI', body)
        self.assertIn("BUY 45.2 vs SELL 44.8 SOL · gap 0.89%", body)
        self.assertIn("Pemicu SIAP2 PUMP", body)
        self.assertIn("+2 bar", body)
        self.assertIn("142 TX (≥80)", body)
        self.assertIn("61 wallet (≥40)", body)
        self.assertIn("fresh 12 (≥5)", body)
        self.assertIn("MC $120.0K — $145.0K", body)
        self.assertNotIn("wash runtuh", body)

    def test_netral_shows_scanner_reason(self):
        status = _row(
            SEROK_NEUTRAL, confidence="info",
            reason="NETRAL — belum ada WASPADA DUMP / SIAP2 PUMP / BATTLE TERJADI.")
        body = self._run(status)
        self.assertIn("NETRAL", body)
        self.assertIn("belum ada WASPADA DUMP", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
