"""Coverage for the 3 bottom signals in the watchlist UI.

The watchlist row renders the newest day's bottom signal (badge tone per
sinyal) plus a detail column with flush/volume narrative and the 4 on-chain
markers (info only).

Streamlit is an optional dev dependency, so the AppTest part is skipped when
it is unavailable.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from effort_detector import classify_effort, daily_effort_record

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

APP = str(Path(__file__).resolve().parent.parent / "app.py")
MINT = "MintBottom"


def _row(date, open_, close, cvd, volume_usd=None, **tags):
    row = daily_effort_record(MINT, date, open_, close, cvd)
    if volume_usd is not None:
        row["volume_usd"] = volume_usd
    for key in ("smart_money_buy", "fresh_buy", "bot_sell", "mev_noise"):
        if key in tags:
            row[key] = tags[key]
    return row


def exhaustion_rows():
    """Flush -106.6 SOL, lalu hari kering: CVD -15.4, volume 3% dari kemarin."""
    return [
        _row("2026-08-13", 1.0, 0.55, -106.6, volume_usd=9000.0),
        _row("2026-08-14", 0.55, 0.55, -15.4, volume_usd=300.0),
    ]


def reversal_rows():
    # CVD -20 vs flush -120 (16.7% ≤ 40%) dan volume 12000/9000 = 133% ≥ 130%
    return [
        _row("2026-08-13", 1.0, 0.5, -120.0, volume_usd=9000.0),
        _row("2026-08-14", 0.5, 0.45, -20.0, volume_usd=12000.0),
    ]


def akumulasi_rows():
    return [
        _row("2026-08-13", 1.0, 0.99, 2.0, volume_usd=500.0),
        _row("2026-08-14", 0.99, 0.988, 8.0, volume_usd=800.0,
             smart_money_buy=3, fresh_buy=1),
    ]


class SignalFieldTest(unittest.TestCase):
    def test_exhaustion_result_fields(self):
        result = classify_effort(exhaustion_rows(), MINT)
        self.assertEqual(result["signal"], "SELLER_EXHAUSTION")
        self.assertEqual(result["bias"], "bullish")
        self.assertEqual(result["flush_date"], "2026-08-13")
        self.assertAlmostEqual(result["volume_pct"], 300 / 9000 * 100,
                               places=3)
        self.assertIn("reason", result)

    def test_neutral_row_has_dash(self):
        rows = [_row("2026-08-13", 1.0, 1.01, 0.2, volume_usd=100.0)]
        result = classify_effort(rows, MINT)
        self.assertEqual(result["signal"], "—")
        self.assertIsNone(result["bias"])


@unittest.skipIf(AppTest is None, "streamlit not installed")
class SignalColumnRenderTest(unittest.TestCase):
    def _run(self, rows):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       return_value={MINT: {"symbol": "TST"}}),
            mock.patch("effort_detector.load_daily_effort",
                       return_value=rows),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=30)
        app.run()
        self.assertFalse(app.exception)
        return "\n".join(block.value for block in app.markdown)

    def test_exhaustion_badge_and_flush_detail(self):
        body = self._run(exhaustion_rows())
        self.assertIn('class="signal bull">SELLER EXHAUSTION', body)
        self.assertIn("Flush 2026-08-13", body)
        self.assertIn("CVD -106.60 SOL", body)
        self.assertIn("Volume 3% dari kemarin", body)
        self.assertIn('class="signal-detail bull"', body)

    def test_reversal_badge_is_purple(self):
        body = self._run(reversal_rows())
        self.assertIn('class="signal rev">REVERSAL', body)
        self.assertIn("Volume 133% dari kemarin", body)

    def test_akumulasi_badge_is_blue_with_tags(self):
        body = self._run(akumulasi_rows())
        self.assertIn('class="signal aku">AKUMULASI', body)
        # 4 penanda on-chain tampil sebagai info
        self.assertIn("smart 3", body)
        self.assertIn("fresh 1", body)

    def test_detail_text_is_always_white(self):
        body = self._run(exhaustion_rows())
        self.assertIn(".signal-detail.bull,", body)
        self.assertIn(".signal-detail.aku,", body)
        self.assertIn(".signal-detail.neutral {color:#ffffff !important}",
                      body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
