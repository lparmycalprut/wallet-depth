"""Snapshot + dashboard helpers for realtime watchlist status."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reversal_engine import REVERSAL_DOWN, REVERSAL_UP
from reversal_status import (publish_reversal_status, reset_cache,
                             snapshot_status, status_sort_key)
from scripts.realtime_reversal import format_alert, format_wallet_lines


JLY = "6fEaYuzirTMXFnFo7dGKHJs8wWVFPdh1bfZL9oRPpump"


def _jly_state(now_ts=1755482160):
    current = {
        "cvd_delta_clean": -18.7, "wash_pct": 1.4, "price_chg_pct": -27.5,
        "unique_makers": 152, "smart_money_buy": 33, "smart_net_sol": -3.5,
        "fresh_buy": 8, "fresh_buy_sol": 2.9, "bot_sell": 42,
        "top_wallet_pct": 5.9, "top3_wallet_pct": 17.0,
        "top_wallet_net_sol": 10.2, "top_wallet_churn_pct": 0.0,
    }
    context = {"cvd_delta_clean": 32.4, "wash_pct": 10.7, "price_chg_pct": 20.0}
    return {
        "_meta": {"updated_at": now_ts, "scanner": "rolling-6h-v1"},
        JLY: {
            "state": "REVERSAL_DOWN_FIRED",
            "observed_signal": REVERSAL_DOWN,
            "last_scan_ts": now_ts,
            "result": {
                "signal": REVERSAL_DOWN, "bias": "bearish",
                "confidence": "strong",
                "reason": "wash runtuh + CVD bersih negatif setelah pump",
                "current": current, "context": context,
            },
        },
        "OtherMint": {
            "state": "NONE", "observed_signal": "NEUTRAL",
            "last_scan_ts": now_ts,
            "result": {"signal": "NEUTRAL", "confidence": "info",
                       "current": {}, "context": {}},
        },
    }


class SnapshotTest(unittest.TestCase):
    def test_snapshot_strips_private_meta_and_keeps_alert_fields(self):
        snap = snapshot_status(_jly_state(), {JLY: {"symbol": "JLY"}})
        self.assertEqual(snap["updated_at"], 1755482160)
        self.assertNotIn("_meta", snap["tokens"])
        row = snap["tokens"][JLY]
        self.assertEqual(row["symbol"], "JLY")
        self.assertEqual(row["signal"], REVERSAL_DOWN)
        self.assertEqual(row["confidence"], "strong")
        self.assertEqual(row["current"]["cvd_delta_clean"], -18.7)
        self.assertEqual(row["context"]["wash_pct"], 10.7)
        self.assertEqual(row["current"]["unique_makers"], 152)

    def test_reversals_sort_ahead_of_neutral(self):
        snap = snapshot_status(_jly_state(), {JLY: {"symbol": "JLY"}})
        ordered = sorted(snap["tokens"],
                         key=lambda mint: status_sort_key(
                             mint, snap["tokens"][mint]))
        self.assertEqual(ordered[0], JLY)

    def test_wallet_lines_match_telegram_payload(self):
        current = _jly_state()[JLY]["result"]["current"]
        text = format_wallet_lines(current)
        self.assertIn("152 maker", text)
        self.assertIn("smart 33 (net jual -3.5 SOL)", text)
        self.assertIn("fresh 8 (2.9 SOL)", text)
        self.assertIn("bot-sell 42", text)
        self.assertIn("top-1 5.9%", text)
        self.assertIn("churn 0%", text)
        self.assertIn("terdistribusi", text)

    def test_alert_uses_hyperlinks_instead_of_raw_urls(self):
        result = _jly_state()[JLY]["result"]  # REVERSAL_DOWN fixture
        text = format_alert("JLY", JLY, result, now_ts=1755482160)
        self.assertIn("<b>🔴 REVERSAL DOWN — $JLY</b>", text)
        self.assertIn("📈 Konteks: pump +32.4 SOL · wash 10.7%", text)
        self.assertIn("📉 Sekarang: CVD bersih -18.7 SOL", text)
        self.assertIn("⭐ Confidence: 🟢 KUAT", text)
        self.assertIn(
            f'<a href="https://gmgn.ai/sol/token/{JLY}">GMGN</a>', text)
        self.assertIn(
            f'<a href="https://dexscreener.com/solana/{JLY}">DEXSCREENER</a>',
            text)
        # No bare URL lines left — links only appear inside anchors.
        for line in text.splitlines():
            self.assertFalse(line.startswith("https://"), line)
        self.assertNotIn("🧱", text)  # tanpa verdict struktur, tanpa baris SBR

    def test_alert_includes_structure_line_when_confirmed(self):
        result = _jly_state()[JLY]["result"]  # REVERSAL_DOWN fixture
        struct = {"side": "down", "state": "confirmed",
                  "zone": {"low": 1.0, "high": 1.0521, "touches": 7},
                  "low_state": "higher_low", "extreme": 1.3,
                  "extreme_ts": 1755480000, "reclaim_ts": 1755481200,
                  "last_close": 0.99, "reason": ""}
        text = format_alert("JLY", JLY, result, now_ts=1755482160,
                            structure=struct)
        self.assertIn("🧱 SBR 1–1.052 tertembus 08:40 WIB · lower-high ✓", text)
        # Alert ditembakkan hanya setelah gate struktur — lihat
        # tests/test_reversal_engine.py::test_unconfirmed_structure_*.

    def test_snapshot_passes_structure_through(self):
        snap = snapshot_status(_jly_state(), {JLY: {"symbol": "JLY"}})
        self.assertIsNone(snap["tokens"][JLY]["structure"])
        state = _jly_state()
        state[JLY]["structure"] = {"state": "forming",
                                   "zone": {"low": 1, "high": 2, "touches": 5}}
        snap = snapshot_status(state, {JLY: {"symbol": "JLY"}})
        self.assertEqual(snap["tokens"][JLY]["structure"]["state"], "forming")


class PublishTest(unittest.TestCase):
    def setUp(self):
        reset_cache()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_publish_writes_local_and_can_skip_github(self):
        path = Path(self.tmp.name) / "reversal_status.json"
        with mock.patch("reversal_status.STATUS_PATH", str(path)), \
                mock.patch("reversal_status._github_push") as push:
            status = publish_reversal_status(
                _jly_state(), {JLY: {"symbol": "JLY"}}, push=False)
            push.assert_not_called()
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["tokens"][JLY]["signal"], REVERSAL_DOWN)
        self.assertEqual(status["tokens"][JLY]["symbol"], "JLY")

    def test_publish_pushes_when_requested(self):
        path = Path(self.tmp.name) / "reversal_status.json"
        with mock.patch("reversal_status.STATUS_PATH", str(path)), \
                mock.patch("reversal_status._github_push",
                           return_value=True) as push:
            publish_reversal_status(
                _jly_state(), {JLY: {"symbol": "JLY"}}, push=True)
            push.assert_called_once()
            self.assertIn("[skip ci]", push.call_args.args[1])


class ScannerPublishHookTest(unittest.TestCase):
    def test_live_scan_publishes_status_after_save(self):
        import scripts.realtime_reversal as rr

        with mock.patch.object(rr, "load_watchlist", return_value={}), \
                mock.patch.object(rr, "load_state", return_value={}), \
                mock.patch.object(rr, "load_cache", return_value={}), \
                mock.patch.object(rr, "save_cache"), \
                mock.patch.object(rr, "save_state"), \
                mock.patch.object(rr, "process_telegram_callbacks"), \
                mock.patch.object(rr, "publish_reversal_status") as publish:
            rc = rr.main(["--no-alert"])
        self.assertEqual(rc, 0)
        publish.assert_called_once()

    def test_fixture_scan_does_not_publish(self):
        import scripts.realtime_reversal as rr

        fixture = Path(tempfile.mkdtemp()) / "fix.json"
        fixture.write_text("[]", encoding="utf-8")
        with mock.patch.object(rr, "load_watchlist", return_value={}), \
                mock.patch.object(rr, "publish_reversal_status") as publish:
            rc = rr.main(["--fixture", str(fixture), "--mint", "x",
                          "--no-alert", "--now-ts", "1"])
        self.assertEqual(rc, 0)
        publish.assert_not_called()


try:
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@unittest.skipIf(AppTest is None, "streamlit not installed")
class WatchlistStatusRenderTest(unittest.TestCase):
    def test_main_page_shows_live_reversal_not_daily_effort(self):
        snap = snapshot_status(_jly_state(), {JLY: {"symbol": "JLY"}})
        patches = (
            mock.patch("watchlist.load_watchlist",
                       return_value={JLY: {"symbol": "JLY"}}),
            mock.patch("reversal_status.load_reversal_status",
                       return_value=snap),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=30)
        app.run()
        self.assertFalse(app.exception)
        body = "\n".join(block.value for block in app.markdown)
        self.assertIn('class="signal bear">REVERSAL DOWN', body)
        self.assertIn("🟢 KUAT", body)
        self.assertIn("CVD bersih -18.7", body)
        self.assertIn("wash 1.4%", body)
        self.assertIn("runtuh 87%", body)
        self.assertIn("152 maker", body)
        self.assertNotIn("SELLER EXHAUSTION", body)
        self.assertNotIn("vs kemarin", body)


if __name__ == "__main__":
    unittest.main()
