import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import scripts.update_cvd as uc
from cvd_daily import MARKET_TZ
from effort_detector import daily_effort_record


def _swap(timestamp):
    return ("buy", 2.0, timestamp, "wallet")


# DexScreener market fiktif: supply = 2.000.000 / 2.0 = 1.000.000 token.
_MARKET = {"pair_addresses": ["pool123"], "symbol": "TST",
           "marketcap": 2_000_000.0, "price_usd": 2.0}


class LookbackWindowTest(unittest.TestCase):
    def test_window_uses_market_midnight_and_excludes_today(self):
        now = datetime.fromisoformat("2026-08-15T12:00:00+00:00")
        start, end = uc.compute_lookback_window(now, 7)
        self.assertEqual(start.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-08T00:00:00+00:00")
        self.assertEqual(end.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-15T00:00:00+00:00")
        # end is today's 00:00 UTC -> the open day is never included
        self.assertEqual(end.astimezone(MARKET_TZ).hour, 0)

    def test_window_respects_requested_days(self):
        now = datetime.fromisoformat("2026-08-15T12:00:00+00:00")
        start2, end2 = uc.compute_lookback_window(now, 2)
        start7, end7 = uc.compute_lookback_window(now, 7)
        self.assertEqual((end2 - start2).days, 2)
        self.assertEqual((end7 - start7).days, 7)
        self.assertEqual(end2, end7)  # same ceiling, different lookback span
        self.assertEqual(start7, end2 - timedelta(days=7))
        self.assertEqual(start2, end2 - timedelta(days=2))


class DateWindowTest(unittest.TestCase):
    def test_date_window_inclusive_and_excludes_today(self):
        now = datetime.fromisoformat("2026-08-15T12:00:00+00:00")
        start, end = uc.compute_date_window("2026-08-10", "2026-08-14", now=now)
        self.assertEqual(start.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-10T00:00:00+00:00")
        # end exclusive = day after the inclusive end date
        self.assertEqual(end.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-15T00:00:00+00:00")

    def test_date_window_caps_at_yesterday(self):
        # Requesting today as the end date must clamp to yesterday.
        now = datetime.fromisoformat("2026-08-15T12:00:00+00:00")
        start, end = uc.compute_date_window("2026-08-10", "2026-08-15", now=now)
        self.assertEqual(end.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-15T00:00:00+00:00")

    def test_date_window_clamps_span(self):
        now = datetime.fromisoformat("2026-08-15T12:00:00+00:00")
        start, end = uc.compute_date_window("2026-07-01", "2026-08-14",
                                            now=now, max_span_days=10)
        span = (end - start).days
        self.assertEqual(span, 10)

    def test_date_window_swaps_reversed_order(self):
        now = datetime.fromisoformat("2026-08-15T12:00:00+00:00")
        start, end = uc.compute_date_window("2026-08-14", "2026-08-10", now=now)
        self.assertEqual(start.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-10T00:00:00+00:00")
        self.assertEqual(end.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-15T00:00:00+00:00")

    def test_resolve_window_prefers_date_range(self):
        now = datetime.fromisoformat("2026-08-15T12:00:00+00:00")
        start, end, span = uc._resolve_window(
            now, lookback_days=4, start_date="2026-08-10",
            end_date="2026-08-14")
        self.assertEqual(span, 5)
        self.assertEqual(start.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-10T00:00:00+00:00")

    def test_refresh_with_date_range_reports_window(self):
        now = datetime.fromisoformat("2026-08-15T10:00:00+00:00")
        tmp = tempfile.TemporaryDirectory()
        path = str(Path(tmp.name) / "daily.json")
        patches = [
            mock.patch.object(uc, "get_market", return_value=dict(_MARKET)),
            mock.patch.object(uc, "_pool_and_symbol",
                              return_value=("pool", "TST")),
            mock.patch.object(uc, "_fetch_history_with_source",
                              return_value=([_swap(1)], "gmgn", False)),
            mock.patch.object(uc, "get_daily_candles", return_value=[]),
            mock.patch.object(uc, "fallback_candles_from_swaps",
                              return_value=[]),
            mock.patch.object(uc, "build_effort_rows", return_value=[
                daily_effort_record("TokenMint123", "2026-08-14", 100, 110, 5)]),
        ]
        for p in patches:
            p.start()
        fetch_mock = uc._fetch_history_with_source
        try:
            res = uc.refresh_single_token(
                "TokenMint123", {"symbol": "TST"}, now=now, api_key="secret",
                start_date="2026-08-10", end_date="2026-08-14", path=path)
        finally:
            for p in patches:
                p.stop()
            tmp.cleanup()
        self.assertTrue(res["ok"])
        self.assertEqual(res["start_date"], "2026-08-10")
        self.assertEqual(res["end_date"], "2026-08-14")
        self.assertEqual(res["requested_days"], 5)
        # Fetch window passed to the pipeline must match the range.
        call = fetch_mock.call_args
        # (mint, pool, api_key, start, end) — start/end are positional 4th/5th.
        start_arg, end_arg = call.args[3], call.args[4]
        self.assertEqual(start_arg.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-10T00:00:00+00:00")
        self.assertEqual(end_arg.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-15T00:00:00+00:00")


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
            mock.patch.object(uc, "get_market", return_value=dict(_MARKET)),
            mock.patch.object(uc, "_pool_and_symbol",
                              return_value=(pool, self.META["symbol"])),
            mock.patch.object(uc, "_fetch_history_with_source",
                              return_value=(swaps, source, fallback)),
            mock.patch.object(uc, "get_daily_candles", return_value=[]),
            mock.patch.object(uc, "fallback_candles_from_swaps",
                              return_value=[]),
            mock.patch.object(uc, "build_effort_rows",
                              return_value=build_rows),
        ]

    def _run(self, swaps, source="gmgn", fallback=False, days=7, pool="pool123"):
        now = datetime.fromisoformat("2026-08-15T10:00:00+00:00")
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

    def test_supply_from_market_passed_to_build_effort_rows(self):
        # supply = marketcap/price = 2.000.000/2.0 — untuk marketcap_close
        # harian di gerbang anti wash-trade.
        res = self._run([_swap(1)])
        self.assertTrue(res["ok"])
        call = uc.build_effort_rows.call_args
        self.assertEqual(call.kwargs.get("supply"), 1_000_000.0)

    def test_no_market_data_leaves_supply_none(self):
        patches = self._patches([_swap(1)])
        for patch in patches:
            patch.start()
        self.addCleanup(lambda: [patch.stop() for patch in patches])
        uc.get_market.return_value = {}  # token tanpa data market
        now = datetime.fromisoformat("2026-08-15T10:00:00+00:00")
        res = uc.refresh_single_token(
            self.MINT, self.META, now=now, api_key="secret",
            lookback_days=7, path=self.path)
        self.assertTrue(res["ok"])
        self.assertIsNone(uc.build_effort_rows.call_args.kwargs.get("supply"))

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
        now = datetime.fromisoformat("2026-08-15T10:00:00+00:00")
        with mock.patch.object(uc, "get_market", return_value=dict(_MARKET)), \
                mock.patch.object(uc, "_pool_and_symbol",
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

    def test_log_uses_ts_market_and_never_leaks_credentials(self):
        res = self._run([_swap(1)])
        for entry in res["log"]:
            self.assertIn("ts_market", entry)
            self.assertNotIn("ts_wib", entry)
            self.assertNotIn("secret", str(entry.get("message") or ""))
        self.assertNotIn("secret", str(res.get("error") or ""))


class DateRangeRefreshTest(unittest.TestCase):
    MINT = "TokenMint123"
    META = {"symbol": "TST"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "daily.json")
        self.now = datetime.fromisoformat("2026-08-15T10:00:00+00:00")

    def _patches(self, swaps, source="gmgn", fallback=False, build_rows=None,
                 pool="pool123"):
        build_rows = build_rows if build_rows is not None else [
            daily_effort_record(self.MINT, "2026-08-14", 100, 110, 5)]
        return [
            mock.patch.object(uc, "get_market", return_value=dict(_MARKET)),
            mock.patch.object(uc, "_pool_and_symbol",
                              return_value=(pool, self.META["symbol"])),
            mock.patch.object(uc, "_fetch_history_with_source",
                              return_value=(swaps, source, fallback)),
            mock.patch.object(uc, "get_daily_candles", return_value=[]),
            mock.patch.object(uc, "fallback_candles_from_swaps",
                              return_value=[]),
            mock.patch.object(uc, "build_effort_rows",
                              return_value=build_rows),
        ]

    def _run_range(self, swaps, start_date, end_date, source="gmgn",
                   fallback=False, pool="pool123"):
        patches = self._patches(swaps, source=source, fallback=fallback,
                                pool=pool)
        for patch in patches:
            patch.start()
        self.addCleanup(lambda: [patch.stop() for patch in patches])
        return uc.refresh_single_token(
            self.MINT, self.META, now=self.now, api_key="secret",
            start_date=start_date, end_date=end_date, path=self.path)

    def test_date_range_success_and_no_telegram(self):
        with mock.patch.object(uc, "send_telegram",
                               wraps=uc.send_telegram) as send:
            res = self._run_range([_swap(1)], "2026-08-10", "2026-08-14")
            self.assertTrue(res["ok"])
            self.assertEqual(res["source"], "gmgn")
            self.assertEqual(res["start_date"], "2026-08-10")
            self.assertEqual(res["end_date"], "2026-08-14")
            send.assert_not_called()

    def test_date_range_is_idempotent(self):
        first = self._run_range([_swap(1)], "2026-08-10", "2026-08-14")
        self.assertEqual(first["rows_created"], 1)
        second = self._run_range([_swap(1)], "2026-08-10", "2026-08-14")
        self.assertEqual(second["rows_created"], 0)
        self.assertEqual(second["rows_updated"], 1)

    def test_date_range_clamps_to_30_days(self):
        res = self._run_range([_swap(1)], "2026-07-01", "2026-08-14")
        self.assertEqual(res["requested_days"], 30)
        self.assertEqual(res["start_date"], "2026-07-16")
        self.assertEqual(res["end_date"], "2026-08-14")
        call = uc._fetch_history_with_source.call_args
        start_arg, end_arg = call.args[3], call.args[4]
        self.assertEqual((end_arg - start_arg).days, 30)
        self.assertEqual(start_arg.astimezone(MARKET_TZ).isoformat(),
                         "2026-07-16T00:00:00+00:00")
        self.assertEqual(end_arg.astimezone(MARKET_TZ).isoformat(),
                         "2026-08-15T00:00:00+00:00")

    def test_date_range_excludes_open_day(self):
        # Requesting today as the end date clamps to yesterday.
        res = self._run_range([_swap(1)], "2026-08-10", "2026-08-15")
        self.assertEqual(res["end_date"], "2026-08-14")
        self.assertEqual(res["requested_days"], 5)

    def test_date_range_error_is_clean_and_redacted(self):
        with mock.patch.object(uc, "get_market", return_value=dict(_MARKET)), \
                mock.patch.object(uc, "_pool_and_symbol",
                                  return_value=("pool", "TST")):
            def boom(*a, **k):
                raise RuntimeError("connection failed with key secret")
            with mock.patch.object(uc, "_fetch_history_with_source", boom):
                res = uc.refresh_single_token(
                    self.MINT, self.META, now=self.now, api_key="secret",
                    start_date="2026-08-10", end_date="2026-08-14",
                    path=self.path)
        self.assertFalse(res["ok"])
        self.assertNotIn("secret", res["error"])
        self.assertIn("REDACTED", res["error"])


if __name__ == "__main__":
    unittest.main()
