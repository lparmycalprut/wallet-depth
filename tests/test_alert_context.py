"""Coverage konteks pasar (volume + harga + volatilitas) untuk alert dust."""
from __future__ import annotations

import unittest
from unittest import mock

import alert_context as ac

NOW = 1_800_000_000
MINT = "MintAddress123"

# Empat jam terakhir: volume 4× baseline, harga turun stabil (stddev ~2,3%).
DUMP_TAIL = [(0.99, 4_000.0), (0.97, 4_000.0), (0.95, 4_000.0), (0.94, 4_000.0)]
# Empat jam terakhir: volume 4× baseline, harga liar (stddev ~9% → high volatility).
WILD_TAIL = [(1.06, 4_000.0), (0.90, 4_000.0), (1.02, 4_000.0), (0.88, 4_000.0)]
FLAT_TAIL = [(1.0, 1_000.0)] * 4


def candles(tail, *, hours: int = 168, base_volume: float = 1_000.0,
            base_price: float = 1.0) -> list[dict]:
    """Candle hourly datar, lalu ``tail`` = ``[(close, volume), ...]`` jam terakhir."""
    prefix = max(0, hours - len(tail))
    rows = [{"ts": NOW - 3600 * (hours - 1 - index), "open": base_price,
             "high": base_price * 1.01, "low": base_price * 0.99,
             "close": base_price, "volume_usd": base_volume}
            for index in range(prefix)]
    previous = base_price
    for index, (close, volume) in enumerate(tail):
        rows.append({
            "ts": NOW - 3600 * (len(tail) - 1 - index),
            "open": previous,
            "high": max(previous, close) * 1.01,
            "low": min(previous, close) * 0.99,
            "close": close, "volume_usd": volume,
        })
        previous = close
    return rows


DEX_MARKET = {
    "price_usd": 0.96,
    "volume": {"m5": 100, "h1": 900, "h6": 5_400, "h24": 24_000},
    "price_change": {"m5": -0.2, "h1": -1.2, "h6": -3.4, "h24": -8.0},
    "txns": {"h1": {"buys": 10, "sells": 20},
             "h6": {"buys": 40, "sells": 120},
             "h24": {"buys": 400, "sells": 900}},
    "pair_addresses": ["PAIR1", "PAIR2"],
}

DAILY_ROWS = [
    {"date": f"2026-08-{day:02d}", "volume_usd": 12_000.0,
     "buy_usd": 7_000.0, "sell_usd": 5_000.0}
    for day in range(20, 27)
]


def build(tail=FLAT_TAIL, **kwargs) -> dict:
    params = {"market": DEX_MARKET, "hourly": candles(tail), "daily_rows": [],
              "now": NOW, "fetch": False}
    params.update(kwargs)
    return ac.build_market_context(MINT, {"price": 0.96}, **params)


class CandleContextTest(unittest.TestCase):
    def test_candles_win_over_dexscreener_estimates(self):
        ctx = build(DUMP_TAIL)
        self.assertEqual(ctx["volume_4h"], 16_000.0)
        self.assertEqual(ctx["volume_source"], "geckoterminal_hourly")
        self.assertEqual(ctx["candles"], 168)
        self.assertEqual(ctx["candles_in_window"], 4)
        self.assertTrue(ctx["available"])
        self.assertEqual(ctx["missing"], [])
        self.assertLess(ctx["price_change_pct"], 0)
        self.assertEqual(ctx["price_change_window"], "candles_4h")

    def test_seven_day_average_is_per_four_hour_window(self):
        """avg_volume_7d = total 7 hari / 42 window, bukan total harian."""
        ctx = build(FLAT_TAIL)
        self.assertAlmostEqual(ctx["avg_volume_7d"], 4_000.0, places=2)
        self.assertAlmostEqual(ctx["avg_volume_daily_7d"], 24_000.0, places=2)
        self.assertAlmostEqual(ctx["volume_ratio"], 1.0, places=4)
        spiked = build(DUMP_TAIL)
        self.assertAlmostEqual(spiked["avg_volume_7d"], 4_285.71, places=2)
        self.assertAlmostEqual(spiked["volume_ratio"], 3.7333, places=4)

    def test_volatility_metrics_are_attached(self):
        ctx = build(WILD_TAIL)
        volatility = ctx["volatility"]
        self.assertTrue(volatility["available"])
        self.assertGreater(volatility["price_stddev_4h"], 3.0)
        self.assertTrue(volatility["high_volatility"])
        self.assertIsNotNone(volatility["intra_hour_volatility"])
        self.assertEqual(ctx["price_change_pct"],
                         volatility["price_change_4h_pct"])

    def test_calm_market_is_not_flagged_as_high_volatility(self):
        volatility = build(DUMP_TAIL)["volatility"]
        self.assertTrue(volatility["available"])
        self.assertFalse(volatility["high_volatility"])
        self.assertLess(volatility["price_stddev_4h"], 3.0)

    def test_young_pool_does_not_fake_a_seven_day_baseline(self):
        """Coverage 6 jam < 24 jam → baseline ditolak, konteks jadi tidak lengkap."""
        young = {"volume": {}, "price_change": {}, "txns": {},
                 "pair_addresses": []}
        ctx = build(FLAT_TAIL, hourly=candles([(1.0, 500.0)] * 6, hours=6),
                    market=young)
        self.assertEqual(ctx["candles"], 6)
        self.assertIsNotNone(ctx["volume_4h"])
        self.assertIsNone(ctx["avg_volume_7d"])
        self.assertFalse(ctx["available"])
        self.assertIn("avg_volume_7d", ctx["missing"])
        self.assertTrue(any("coverage candle" in note for note in ctx["notes"]))

    def test_no_candles_still_produces_a_usable_context(self):
        ctx = build(FLAT_TAIL, hourly=[])
        self.assertEqual(ctx["volume_4h"], 3_600.0)      # h6 5.400 × 4/6
        self.assertEqual(ctx["avg_volume_7d"], 4_000.0)  # h24 24.000 / 6 window
        self.assertEqual(ctx["volume_source"], "dexscreener_h6_scaled")
        self.assertEqual(ctx["price_change_pct"], -3.4)
        self.assertEqual(ctx["price_change_window"], "dexscreener_h6")
        self.assertIsNone(ctx["volatility"])
        self.assertTrue(any("proxy 1 hari" in note for note in ctx["notes"]))

    def test_dexscreener_window_fallback_order(self):
        only_h1 = {"volume": {"h1": 800}, "price_change": {"h1": -2.5},
                   "txns": {"h1": {"buys": 5, "sells": 9}}}
        ctx = build(FLAT_TAIL, hourly=[], market=only_h1)
        self.assertEqual(ctx["volume_4h"], 3_200.0)
        self.assertEqual(ctx["volume_source"], "dexscreener_h1_scaled")
        self.assertIsNone(ctx["avg_volume_7d"])
        self.assertIn("avg_volume_7d", ctx["missing"])
        self.assertEqual(ctx["price_change_pct"], -2.5)
        self.assertEqual(ctx["pressure_window"], "dexscreener_txns_h1")

        only_h24 = {"volume": {"h24": 24_000}, "price_change": {"h24": -9.0},
                    "txns": {"h24": {"buys": 400, "sells": 900}}}
        ctx24 = build(FLAT_TAIL, hourly=[], market=only_h24)
        self.assertEqual(ctx24["volume_4h"], 4_000.0)
        self.assertEqual(ctx24["avg_volume_7d"], 4_000.0)
        self.assertEqual(ctx24["price_change_window"], "dexscreener_h24")
        self.assertEqual(ctx24["pressure_window"], "dexscreener_txns_h24")

    def test_daily_effort_baseline_replaces_the_one_day_proxy(self):
        ctx = build(FLAT_TAIL, hourly=[], daily_rows=DAILY_ROWS)
        self.assertEqual(ctx["volume_source"], "daily_effort_7d")
        self.assertAlmostEqual(ctx["avg_volume_7d"], 2_000.0, places=2)
        self.assertAlmostEqual(ctx["avg_volume_daily_7d"], 12_000.0, places=2)
        self.assertFalse(any("proxy 1 hari" in note for note in ctx["notes"]))

    def test_candles_still_beat_the_daily_baseline(self):
        ctx = build(DUMP_TAIL, daily_rows=DAILY_ROWS)
        self.assertEqual(ctx["volume_source"], "geckoterminal_hourly")
        self.assertAlmostEqual(ctx["avg_volume_7d"], 4_285.71, places=2)

    def test_buy_sell_pressure_prefers_usd_from_daily_rows(self):
        ctx = build(FLAT_TAIL, hourly=[], daily_rows=DAILY_ROWS)
        self.assertEqual(ctx["buy_pressure"], 7_000.0)
        self.assertEqual(ctx["sell_pressure"], 5_000.0)
        self.assertEqual(ctx["pressure_unit"], "usd")
        self.assertTrue(ctx["pressure_window"].startswith("daily_effort:"))

    def test_pressure_falls_back_to_txn_counts(self):
        ctx = build(FLAT_TAIL, hourly=[])
        self.assertEqual(ctx["buy_pressure"], 40.0)
        self.assertEqual(ctx["sell_pressure"], 120.0)
        self.assertEqual(ctx["pressure_unit"], "tx_count")
        self.assertEqual(ctx["pressure_window"], "dexscreener_txns_h6")

    def test_broken_market_payload_degrades_to_unavailable(self):
        ctx = ac.build_market_context(MINT, None, market="bukan-dict",
                                      hourly=None, daily_rows=None, now=NOW,
                                      fetch=False)
        self.assertFalse(ctx["available"])
        self.assertEqual(set(ctx["missing"]),
                         {"volume_4h", "avg_volume_7d", "price_change_pct",
                          "buy/sell_pressure"})
        self.assertIn("data pasar tidak lengkap", ctx["reason"])

    def test_nan_and_infinite_values_are_dropped(self):
        market = {"volume": {"h6": float("nan"), "h24": float("inf")},
                  "price_change": {"h6": None}, "txns": {},
                  "pair_addresses": []}
        ctx = ac.build_market_context(MINT, {"price": float("nan")},
                                      market=market, hourly=[], now=NOW,
                                      fetch=False)
        self.assertIsNone(ctx["volume_4h"])
        self.assertIsNone(ctx["avg_volume_7d"])
        self.assertIsNone(ctx["price"])
        self.assertFalse(ctx["available"])

    def test_analysis_market_is_used_when_no_market_argument(self):
        analysis = {"price": 1.0, "market": DEX_MARKET}
        ctx = ac.build_market_context(MINT, analysis, hourly=[],
                                      daily_rows=[], now=NOW, fetch=False)
        self.assertEqual(ctx["volume_4h"], 3_600.0)
        # Harga hasil scan menang; harga DexScreener hanya fallback.
        self.assertEqual(ctx["price"], 1.0)
        fallback = ac.build_market_context(MINT, {"market": DEX_MARKET},
                                          hourly=[], daily_rows=[], now=NOW,
                                          fetch=False)
        self.assertEqual(fallback["price"], 0.96)

    def test_fetch_time_is_reported_for_the_cron_summary(self):
        self.assertGreaterEqual(build(FLAT_TAIL)["fetch_ms"], 0)


class FetchPolicyTest(unittest.TestCase):
    def test_fetch_disabled_never_touches_the_network(self):
        fetcher = mock.Mock(return_value=candles(FLAT_TAIL))
        loader = mock.Mock(return_value=DEX_MARKET)
        ctx = ac.build_market_context(MINT, {"price": 1.0}, hourly=None,
                                      daily_rows=None, now=NOW, fetch=False,
                                      hourly_fetcher=fetcher,
                                      market_loader=loader)
        fetcher.assert_not_called()
        loader.assert_not_called()
        self.assertFalse(ctx["available"])

    def test_hourly_fetcher_receives_pair_address_and_seven_day_limit(self):
        fetcher = mock.Mock(return_value=candles(FLAT_TAIL))
        ctx = ac.build_market_context(
            MINT, {"price": 1.0}, market=DEX_MARKET, daily_rows=[], now=NOW,
            fetch=True, hourly_fetcher=fetcher)
        fetcher.assert_called_once_with("PAIR1", ac.BASELINE_HOURS)
        self.assertEqual(ac.BASELINE_HOURS, 168)
        self.assertEqual(ctx["volume_source"], "geckoterminal_hourly")

    def test_second_pair_is_tried_when_the_first_has_no_candles(self):
        calls = []

        def fetcher(pair, hours):
            calls.append(pair)
            return [] if pair == "PAIR1" else candles(DUMP_TAIL)

        ctx = ac.build_market_context(
            MINT, {"price": 1.0}, market=DEX_MARKET, daily_rows=[], now=NOW,
            fetch=True, hourly_fetcher=fetcher)
        self.assertEqual(calls, ["PAIR1", "PAIR2"])
        self.assertEqual(ctx["volume_source"], "geckoterminal_hourly")

    def test_fetcher_and_loader_failures_never_raise(self):
        fetcher = mock.Mock(side_effect=RuntimeError("geckoterminal 429"))
        loader = mock.Mock(side_effect=RuntimeError("dexscreener down"))
        ctx = ac.build_market_context(
            MINT, {"price": 1.0}, market=None, daily_rows=[], now=NOW,
            fetch=True, hourly_fetcher=fetcher, market_loader=loader)
        self.assertFalse(ctx["available"])
        self.assertIn("volume_4h", ctx["missing"])

    def test_market_loader_used_when_analysis_has_no_market(self):
        loader = mock.Mock(return_value=DEX_MARKET)
        ctx = ac.build_market_context(MINT, {"price": 1.0}, hourly=[],
                                      daily_rows=[], now=NOW, fetch=True,
                                      market_loader=loader)
        loader.assert_called_once_with(MINT)
        self.assertEqual(ctx["volume_4h"], 3_600.0)


class ProviderTest(unittest.TestCase):
    def test_provider_memoizes_per_token(self):
        fetcher = mock.Mock(return_value=candles(FLAT_TAIL))
        cache: dict = {}
        provider = ac.market_context_provider(
            cache=cache, hourly_fetcher=fetcher, daily_loader=lambda: [],
            now=NOW)
        first = provider(MINT, {"price": 1.0, "market": DEX_MARKET})
        second = provider(MINT, {"price": 1.0, "market": DEX_MARKET})
        self.assertIs(first, second)
        self.assertEqual(fetcher.call_count, 1)
        self.assertIs(cache[MINT], first)
        self.assertEqual(len(cache), 1)      # tidak ada memo internal bocor

    def test_daily_file_is_loaded_once_for_many_tokens(self):
        loader = mock.Mock(return_value=DAILY_ROWS)
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=[]),
            daily_loader=loader, now=NOW)
        provider("MINT1", {"market": DEX_MARKET})
        provider("MINT2", {"market": DEX_MARKET})
        loader.assert_called_once()

    def test_provider_without_daily_loader_skips_local_file(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=[]), now=NOW,
            fetch=False)
        ctx = provider(MINT, {"market": DEX_MARKET})
        self.assertEqual(ctx["volume_source"], "dexscreener_h6_scaled")

    def test_compact_signal_is_bounded_and_flat(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=candles(WILD_TAIL)),
            daily_loader=lambda: [], now=NOW)
        signal = ac.compact_signal(provider(MINT, {"market": DEX_MARKET}))
        self.assertEqual(signal["volume_4h"], 16_000.0)
        self.assertAlmostEqual(signal["volume_ratio_7d"], 3.7333, places=4)
        self.assertTrue(signal["high_volatility"])
        self.assertTrue(signal["volatility_available"])
        self.assertTrue(signal["available"])
        self.assertEqual(signal["missing"], [])
        self.assertLess(signal["price_change_pct"], 0)
        self.assertNotIn("volatility", signal)      # sudah diratakan
        for key, value in signal.items():
            if key == "missing":                    # satu-satunya list
                self.assertIsInstance(value, list)
                continue
            self.assertNotIsInstance(value, (dict, list), f"key={key}")

    def test_compact_signal_of_nothing_is_safe(self):
        signal = ac.compact_signal(None)
        self.assertFalse(signal["available"])
        self.assertIsNone(signal["volume_4h"])
        self.assertIsNone(signal["price_stddev_4h"])


class HelperUnitTest(unittest.TestCase):
    def test_volume_from_candles_needs_usable_rows(self):
        self.assertEqual(ac.volume_from_candles([]), {})
        self.assertEqual(ac.volume_from_candles(None), {})
        self.assertEqual(ac.volume_from_candles(["rusak", {"ts": None}]), {})

    def test_volume_from_candles_without_now_uses_latest_candle(self):
        rows = candles(FLAT_TAIL, hours=48)
        self.assertEqual(ac.volume_from_candles(rows)["volume_4h"],
                         ac.volume_from_candles(rows, now=NOW)["volume_4h"])

    def test_baseline_from_daily_rows_ignores_zero_volume_days(self):
        rows = [{"date": "2026-08-25", "volume_usd": 0.0},
                {"date": "2026-08-26", "volume_usd": 6_000.0},
                {"date": "2026-08-27", "volume_usd": None},
                {"date": "2026-08-28", "volume_usd": 12_000.0}]
        baseline = ac.baseline_from_daily_rows(rows)
        self.assertAlmostEqual(baseline["avg_volume_daily_7d"], 9_000.0)
        self.assertAlmostEqual(baseline["avg_volume_7d"], 1_500.0)
        self.assertEqual(baseline["baseline_days"], 2)
        self.assertEqual(ac.baseline_from_daily_rows([]), {})

    def test_baseline_only_looks_at_the_requested_number_of_days(self):
        rows = [{"date": f"2026-08-{day:02d}", "volume_usd": 60_000.0}
                for day in range(1, 27)]
        baseline = ac.baseline_from_daily_rows(rows, days=7)
        self.assertEqual(baseline["baseline_days"], 7)
        self.assertAlmostEqual(baseline["avg_volume_daily_7d"], 60_000.0)

    def test_pressure_helpers_report_nothing_when_absent(self):
        self.assertEqual(ac.pressure_from_txns({}), {})
        self.assertEqual(ac.pressure_from_txns({"txns": {"h6": {}}}), {})
        self.assertEqual(ac.pressure_from_daily_rows([]), {})
        self.assertEqual(ac.pressure_from_daily_rows(None), {})
        self.assertEqual(ac.pressure_from_daily_rows([{"date": "2026-08-26"}]),
                         {})

    def test_pressure_picks_the_latest_daily_row(self):
        rows = [{"date": "2026-08-25", "buy_usd": 1.0, "sell_usd": 2.0},
                {"date": "2026-08-27", "buy_usd": 30.0, "sell_usd": 4.0},
                {"date": "2026-08-26", "buy_usd": 3.0, "sell_usd": 4.0}]
        pressure = ac.pressure_from_daily_rows(rows)
        self.assertEqual(pressure["buy_pressure"], 30.0)
        self.assertIn("2026-08-27", pressure["pressure_window"])

    def test_dexscreener_helper_survives_garbage(self):
        for garbage in (None, {}, {"volume": "x"}, {"price_change": [1]},
                        {"txns": {"h6": "bukan-dict"}}):
            out = ac.volume_from_dexscreener(garbage)
            self.assertIsNone(out.get("volume_4h"), f"input={garbage!r}")
            self.assertIsNone(out.get("avg_volume_7d"))
            self.assertIsNone(out.get("price_change_pct"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
