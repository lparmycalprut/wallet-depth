import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import scripts.update_cvd as uc
from cvd_daily import WIB
from effort_detector import daily_effort_record


def _swap(timestamp):
    return ("buy", 2.0, timestamp, "wallet")


class LookbackWindowTest(unittest.TestCase):
    def test_window_uses_wib_midnight_and_excludes_today(self):
        now = datetime.fromisoformat("2026-08-15T12:00:00+07:00")
        start, end = uc.compute_lookback_window(now, 7)
        self.assertEqual(start.astimezone(WIB).isoformat(),
                         "2026-08-08T00:00:00+07:00")
        self.assertEqual(end.astimezone(WIB).isoformat(),
                         "2026-08-15T00:00:00+07:00")
        # end is today's 00:00 WIB -> the open day is never included
        self.assertEqual(end.astimezone(WIB).hour, 0)

    def test_window_respects_requested_days(self):
        now = datetime.fromisoformat("2026-08-15T12:00:00+07:00")
        start2, end2 = uc.compute_lookback_window(now, 2)
        start7, end7 = uc.compute_lookback_window(now, 7)
        self.assertEqual((end2 - start2).days, 2)
        self.assertEqual((end7 - start7).days, 7)
        self.assertEqual(end2, end7)  # same ceiling, different lookback span
        self.assertEqual(start7, end2 - timedelta(days=7))
        self.assertEqual(start2, end2 - timedelta(days=2))


class ManualRefreshTest(unittest.TestCase):
    MINT = "TokenMint123"
    META = {"symbol": "TST"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "daily.json")

    def _patches(self, swaps, source="gmgn", fallback=False,
                 build_rows=None, pool="pool123"):
        build_rows = build_rows if build_rows is not None else [
            daily_effort_record(self.MINT, "2026-08-14", 100, 110, 5)]
        return [
            mock.patch.object(uc, "_pool_and_symbol",
                              return_value=(pool, self.META["symbol"])),
            mock.patch.object(uc, "_fetch_history_with_source",
                              return_value=(swaps, source, fallback)),
            mock.patch.object(uc, "get_daily_candles_wib", return_value=[]),
            mock.patch.object(uc, "fallback_candles_from_swaps",
                              return_value=[]),
            mock.patch.object(uc, "build_effort_rows",
                              return_value=build_rows),
        ]

    def _run(self, swaps, source="gmgn", fallback=False, days=7, pool="pool123"):
        now = datetime.fromisoformat("2026-08-15T10:00:00+07:00")
        patches = self._patches(swaps, source=source, fallback=fallback,
                                pool=pool)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return uc.refresh_single_token(
            self.MINT, self.META, now=now, api_key="secret",
            lookback_days=days, path=self.path)

    def test_success_path_ok_and_structured(self):
        res = self._run([_swap(1)])
        self.assertTrue(res["ok"])
        self.assertEqual(res["symbol"], "TST")
        self.assertEqual(res["source"], "gmgn")
        self.assertFalse(res["fallback"])
        self.assertEqual(res["trades_count"], 1)
        self.assertEqual(res["rows_created"], 1)
        self.assertEqual(res["rows_updated"], 0)
        self.assertIsInstance(res["duration_ms"], int)
        self.assertGreaterEqual(res["duration_ms"], 0)
        stages = {e["stage"] for e in res["log"]}
        self.assertIn("market_lookup", stages)
        self.assertIn("fetch_trades", stages)
        self.assertIn("fetch_candle", stages)
        self.assertIn("aggregate", stages)
        self.assertIn("persist", stages)
        self.assertIn("success", stages)
        self.assertNotIn("error", stages)

    def test_manual_refresh_does_not_send_telegram(self):
        with mock.patch.object(uc, "send_telegram",
                               wraps=uc.send_telegram) as send:
            res = self._run([_swap(1)])
            self.assertTrue(res["ok"])
            send.assert_not_called()

    def test_manual_refresh_never_touches_watchlist(self):
        # No call to update_local_meta / add_to_watchlist during manual fetch.
        with mock.patch.object(uc, "update_local_meta") as meta:
            res = self._run([_swap(1)])
            self.assertTrue(res["ok"])
            meta.assert_not_called()

    def test_helius_fallback_source_reported(self):
        res = self._run([_swap(1)], source="helius_fallback", fallback=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["source"], "helius_fallback")
        self.assertTrue(res["fallback"])
        self.assertIn("fallback Helius", res["log"][2]["message"])

    def test_error_path_returns_clean_result(self):
        res = self._run([], pool="")
        self.assertFalse(res["ok"])
        self.assertIn("pair market", res["error"])
        self.assertTrue(any(e["stage"] == "error" for e in res["log"]))

    def test_error_message_redacts_api_key(self):
        now = datetime.fromisoformat("2026-08-15T10:00:00+07:00")
        with mock.patch.object(uc, "_pool_and_symbol",
                               return_value=("pool", "TST")):
            def boom(*a, **k):
                raise RuntimeError("connection failed with key secret")
            with mock.patch.object(uc, "_fetch_history_with_source", boom):
                res = uc.refresh_single_token(
                    self.MINT, self.META, now=now, api_key="secret",
                    lookback_days=7, path=self.path)
        self.assertFalse(res["ok"])
        self.assertNotIn("secret", res["error"])
        self.assertIn("REDACTED", res["error"])

    def test_manual_refresh_is_idempotent(self):
        first = self._run([_swap(1)], days=7)
        self.assertEqual(first["rows_created"], 1)
        # Re-run with the exact same daily row -> nothing new is created.
        second = self._run([_swap(1)], days=7)
        self.assertEqual(second["rows_created"], 0)
        self.assertEqual(second["rows_updated"], 1)
        with open(self.path, encoding="utf-8") as fh:
            stored = json.load(fh)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["mint"], self.MINT)


if __name__ == "__main__":
    unittest.main()
