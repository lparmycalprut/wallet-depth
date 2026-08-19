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

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

APP = str(Path(__file__).resolve().parent.parent / "app.py")
MINT = "MintBottom"


def _row(signal, *, confidence="watch", current=None, context=None,
         reason=""):
    return snapshot_status({
        "_meta": {"updated_at": 1_700_000_000, "scanner": "rolling-6h-v1"},
        MINT: {
            "state": f"{signal}_FIRED" if signal.startswith("REVERSAL")
            else signal,
            "observed_signal": signal,
            "last_scan_ts": 1_700_000_000,
            "result": {
                "signal": signal, "confidence": confidence,
                "reason": reason,
                "current": current or {},
                "context": context or {},
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
