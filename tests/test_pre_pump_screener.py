# -*- coding: utf-8 -*-
"""Coverage 🚀 Pre-Pump Screener: 4 sinyal on-chain + PUMP SCORE + kartu UI.

Fokus pada keputusan yang bisa salah secara diam-diam:
- token **tanpa** data holder tidak boleh terbaca sebagai konsolidasi;
- sinyal volume harus bisa menyala (window tenang tidak boleh menelan window
  spike — lihat ``detect_volume_anomaly``);
- data likuiditas yang hilang = confidence 0,3, bukan 0 dan bukan 1;
- fallback DexScreener untuk TX velocity harus ``available``.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:  # Streamlit + requests opsional di environment test minimal.
    import pre_pump_screener as pp
except ModuleNotFoundError as exc:  # pragma: no cover
    if exc.name not in {"streamlit", "requests"}:
        raise
    pp = None

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

APP = str(Path(__file__).resolve().parent.parent / "app.py")

NOW = 1_800_000_000
H = 3600
CA = "Pump111111111111111111111111111111111111"
DEGEN_CA = "Degen11111111111111111111111111111111111"
LP_CA = "LpMint111111111111111111111111111111111111"
MANUAL_CA = "Manual11111111111111111111111111111111111"


def _two_wave_series(*, first_add=10_000.0, second_add=60_000.0,
                     base=100_000.0, second_start_hours_ago=10):
    """Seri likuiditas: add kecil 40 jam lalu, add besar belakangan.

    ``base`` di atas ``LIQ_LOW_VOLUME_USD`` supaya ambang standar 5x dipakai;
    jarak antar gelombang = ``40 - second_start_hours_ago`` jam.
    """
    return [
        {"ts": NOW - 40 * H, "liq_usd": base},
        {"ts": NOW - 39 * H, "liq_usd": base + first_add},
        {"ts": NOW - second_start_hours_ago * H, "liq_usd": base + first_add},
        {"ts": NOW - (second_start_hours_ago - 1) * H,
         "liq_usd": base + first_add + second_add},
    ]


def _candles(*, hours=7 * 24, normal=10_000.0, calm=1_000.0,
             calm_hours=24, storm=100_000.0, storm_hours=6):
    """Candle hourly: minggu normal → 24 jam tenang → 6 jam badai."""
    rows = []
    for index in range(hours):
        ts = NOW - (hours - 1 - index) * H
        if ts > NOW - storm_hours * H:
            volume = storm
        elif ts > NOW - (storm_hours + calm_hours) * H:
            volume = calm
        else:
            volume = normal
        rows.append({"ts": ts, "volume_usd": volume, "close": 1.0})
    return rows


def _swap(side: str, age_hours: float, wallet: str = "w"):
    return (side, 1.0, int(NOW - age_hours * H), wallet, None, 0.0, [])


@unittest.skipIf(pp is None, "UI dependencies are not installed")
class LoadDegenWatchlistTest(unittest.TestCase):
    def test_only_degen_source_is_kept(self):
        picked = pp.load_degen_watchlist({
            DEGEN_CA: {"symbol": "DGN", "source": "degen"},
            LP_CA: {"symbol": "LPT", "source": "meteora"},
            MANUAL_CA: {"symbol": "MAN", "source": "manual"},
        })
        self.assertEqual(list(picked), [DEGEN_CA])

    def test_source_matching_is_case_insensitive_and_trimmed(self):
        picked = pp.load_degen_watchlist(
            {DEGEN_CA: {"symbol": "DGN", "source": "  Degen "}})
        self.assertEqual(list(picked), [DEGEN_CA])

    def test_order_is_preserved_and_missing_meta_is_skipped(self):
        picked = pp.load_degen_watchlist({
            DEGEN_CA: {"symbol": "DGN", "source": "degen"},
            MANUAL_CA: {"symbol": "MAN", "source": "manual"},
            LP_CA: {"symbol": "LP2", "source": "degen"},
        })
        self.assertEqual(list(picked), [DEGEN_CA, LP_CA])

    def test_non_dict_input_returns_empty(self):
        self.assertEqual(pp.load_degen_watchlist("bukan dict"), {})

    def test_without_a_watchlist_it_reads_the_shared_one(self):
        with mock.patch("pre_pump_screener.load_watchlist",
                        return_value={DEGEN_CA: {"symbol": "DGN",
                                                 "source": "degen"},
                                      MANUAL_CA: {"symbol": "MAN",
                                                  "source": "manual"}}):
            self.assertEqual(list(pp.load_degen_watchlist()), [DEGEN_CA])


@unittest.skipIf(pp is None, "UI dependencies are not installed")
class LiquidityWaveTest(unittest.TestCase):
    def test_two_wave_pattern_is_detected(self):
        result = pp.detect_liquidity_add_pattern(CA, series=_two_wave_series(),
                                                 now=NOW)
        self.assertTrue(result["detected"])
        self.assertEqual(result["threshold"], pp.LIQ_SECOND_WAVE_MULT)
        self.assertEqual(result["mult"], 6.0)
        self.assertEqual(result["first_add_usd"], 10_000.0)
        self.assertEqual(result["second_add_usd"], 60_000.0)
        self.assertEqual(result["time_diff_hours"], 30.0)
        self.assertGreaterEqual(result["confidence"], 0.55)

    def test_below_threshold_is_not_detected_but_scores_partial(self):
        series = _two_wave_series(second_add=30_000.0)   # 3x < ambang 5x
        result = pp.detect_liquidity_add_pattern(CA, series=series, now=NOW)
        self.assertFalse(result["detected"])
        self.assertEqual(result["mult"], None)
        self.assertEqual(result["best_mult"], 3.0)
        self.assertEqual(result["waves"][0]["add_usd"], 10_000.0)
        self.assertLess(result["confidence"], 0.4)
        self.assertGreater(result["confidence"], 0.0)

    def test_low_liquidity_token_uses_the_3x_threshold(self):
        series = _two_wave_series(first_add=500.0, second_add=1_800.0,
                                  base=4_000.0)
        result = pp.detect_liquidity_add_pattern(CA, series=series, now=NOW)
        self.assertEqual(result["threshold"], pp.LIQ_SECOND_WAVE_MULT_LOW_VOL)
        self.assertTrue(result["detected"])
        self.assertEqual(result["mult"], 3.6)

    def test_single_observation_locks_confidence_to_missing_data(self):
        result = pp.detect_liquidity_add_pattern(
            CA, series=[{"ts": NOW, "liq_usd": 10_000.0}], now=NOW)
        self.assertFalse(result["detected"])
        self.assertFalse(result["available"])
        self.assertEqual(result["confidence"], pp.LIQ_MISSING_CONFIDENCE)

    def test_adds_older_than_the_lookback_are_dropped(self):
        """Gelombang pertama 60 jam lalu sudah di luar window → bukan pola."""
        series = [
            {"ts": NOW - 60 * H, "liq_usd": 100_000.0},
            {"ts": NOW - 59 * H, "liq_usd": 101_000.0},
            {"ts": NOW - 6 * H, "liq_usd": 101_000.0},
            {"ts": NOW - 5 * H, "liq_usd": 111_000.0},
        ]
        result = pp.detect_liquidity_add_pattern(CA, series=series, now=NOW)
        self.assertEqual(result["observations"], 2)
        self.assertEqual(len(result["waves"]), 1)
        self.assertFalse(result["detected"])

    def test_consecutive_observations_merge_into_one_wave(self):
        series = [
            {"ts": NOW - 40 * H, "liq_usd": 100_000.0},
            {"ts": NOW - 39 * H, "liq_usd": 120_000.0},        # +20.000
            {"ts": NOW - 39 * H + 600, "liq_usd": 144_000.0},  # +24.000
            {"ts": NOW - 39 * H + 1_200, "liq_usd": 172_800.0},  # +28.800
            {"ts": NOW - 5 * H, "liq_usd": 172_800.0},
            {"ts": NOW - 4 * H, "liq_usd": 1_036_800.0},
        ]
        result = pp.detect_liquidity_add_pattern(CA, series=series, now=NOW)
        self.assertEqual(len(result["waves"]), 2)
        self.assertEqual(result["waves"][0]["add_usd"], 72_800.0)
        self.assertTrue(result["detected"])
        self.assertEqual(result["mult"], 11.87)

    def test_price_noise_below_min_add_is_not_a_wave(self):
        series = [{"ts": NOW - 10 * H, "liq_usd": 20_000.0},
                  {"ts": NOW - 9 * H, "liq_usd": 20_400.0}]
        result = pp.detect_liquidity_add_pattern(CA, series=series, now=NOW)
        self.assertEqual(result["waves"], [])
        self.assertFalse(result["detected"])


@unittest.skipIf(pp is None, "UI dependencies are not installed")
class LiquidityJournalTest(unittest.TestCase):
    def test_record_then_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "journal.json")
            pp.record_liquidity_observations(
                [{"ca": CA, "liq_usd": 12_345.6, "mc": 900_000.0,
                  "pool": "Pool1"}], now=NOW, path=path)
            journal = pp.load_liquidity_journal(path)
            rows = pp.liquidity_series_for(journal, CA, now=NOW)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["liq_usd"], 12_345.6)
            self.assertEqual(rows[0]["pool"], "Pool1")

    def test_duplicate_observations_within_min_gap_are_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "journal.json")
            for stamp in (NOW, NOW + 5, NOW + 400):
                pp.record_liquidity_observations(
                    [{"ca": CA, "liq_usd": 10_000.0}], now=stamp, path=path)
            rows = pp.liquidity_series_for(pp.load_liquidity_journal(path), CA,
                                           now=NOW + 400)
            self.assertEqual([row["ts"] for row in rows], [NOW, NOW + 400])

    def test_old_observations_are_pruned(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "journal.json")
            pp.record_liquidity_observations(
                [{"ca": CA, "liq_usd": 10_000.0}],
                now=NOW - (pp.LIQ_KEEP_HOURS + 2) * H, path=path)
            self.assertEqual(len(pp.load_liquidity_journal(path)[CA]), 1)
            pp.record_liquidity_observations(
                [{"ca": CA, "liq_usd": 11_000.0}], now=NOW, path=path)
            rows = pp.load_liquidity_journal(path)[CA]
            self.assertEqual([row["ts"] for row in rows], [NOW])

    def test_missing_or_corrupt_journal_returns_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = os.path.join(folder, "nope.json")
            self.assertEqual(pp.load_liquidity_journal(missing), {})
            corrupt = os.path.join(folder, "bad.json")
            with open(corrupt, "w", encoding="utf-8") as handle:
                handle.write("{bukan json")
            self.assertEqual(pp.load_liquidity_journal(corrupt), {})

    def test_negative_and_missing_liquidity_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "journal.json")
            pp.record_liquidity_observations(
                [{"ca": CA, "liq_usd": -5.0},
                 {"ca": "NoLiq1111", "liq_usd": None},
                 {"liq_usd": 10.0}], now=NOW, path=path)
            self.assertEqual(pp.load_liquidity_journal(path), {})


@unittest.skipIf(pp is None, "UI dependencies are not installed")
class HolderConsolidationTest(unittest.TestCase):
    @staticmethod
    def _status(dust=100, real=40, real_pct=20.0, mc=1_000_000.0, ts=NOW):
        return {"analyzed_at": ts, "marketcap": mc,
                "holders": {"dust_count": dust, "real_count": real,
                            "real_pct_mc": real_pct,
                            "wallets_analyzed": dust + real}}

    @staticmethod
    def _store(points, intervals=None):
        return {"tokens": {CA: {"points": points,
                                "chronology": {"intervals": intervals or []}}}}

    def test_consolidation_needs_wallets_and_bag_growth(self):
        status = {CA: self._status()}
        store = self._store(
            [{"ts": NOW - 24 * H, "dust_count": 130, "real_count": 40,
              "real_pct_mc": 8.0, "mc": 1_000_000.0, "holder_count": 170}],
            intervals=[{"from_ts": NOW - 24 * H, "to_ts": NOW,
                        "counts": {"dust_grew_out": 8}}])
        result = pp.detect_holder_consolidation(CA, status_tokens=status,
                                                store=store, now=NOW)
        self.assertTrue(result["consolidating"])
        self.assertEqual(result["wallets_exited_dust"], 8)
        self.assertEqual(result["wallets_moved_out"], 8)
        self.assertEqual(result["avg_bag_growth_pct"], 150.0)
        self.assertEqual(result["source"], "chronology_dust_grew_out")
        self.assertFalse(result["stale"])
        self.assertEqual(result["days_active"], 1.0)
        self.assertGreaterEqual(result["confidence"], 0.5)

    def test_wallets_alone_are_not_consolidation(self):
        status = {CA: self._status()}
        store = self._store(
            [{"ts": NOW - 24 * H, "dust_count": 130, "real_count": 40,
              "real_pct_mc": 20.0, "mc": 1_000_000.0, "holder_count": 170}],
            intervals=[{"from_ts": NOW - 24 * H, "to_ts": NOW,
                        "counts": {"dust_grew_out": 8}}])
        result = pp.detect_holder_consolidation(CA, status_tokens=status,
                                                store=store, now=NOW)
        self.assertFalse(result["consolidating"])
        self.assertEqual(result["avg_bag_growth_pct"], 0.0)
        self.assertLess(result["confidence"], 0.5)

    def test_bag_growth_alone_is_not_consolidation(self):
        status = {CA: self._status()}
        store = self._store(
            [{"ts": NOW - 24 * H, "dust_count": 100, "real_count": 40,
              "real_pct_mc": 8.0, "mc": 1_000_000.0, "holder_count": 140}],
            intervals=[{"from_ts": NOW - 24 * H, "to_ts": NOW,
                        "counts": {"dust_grew_out": 1}}])
        result = pp.detect_holder_consolidation(CA, status_tokens=status,
                                                store=store, now=NOW)
        self.assertFalse(result["consolidating"])
        self.assertEqual(result["wallets_exited_dust"], 1)

    def test_token_without_holder_data_never_reports_consolidation(self):
        """Regresi: dust sekarang 0 vs dust 24 jam lalu ≠ ribuan wallet keluar."""
        store = self._store([{"ts": NOW - 24 * H, "dust_count": 900,
                              "real_count": 40, "real_pct_mc": 8.0,
                              "mc": 1_000_000.0, "holder_count": 940}])
        result = pp.detect_holder_consolidation(CA, status_tokens={},
                                                store=store, now=NOW)
        self.assertFalse(result["consolidating"])
        self.assertFalse(result["available"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["wallets_exited_dust"], 0)

    def test_falls_back_to_dust_count_delta_without_chronology(self):
        status = {CA: self._status()}
        store = self._store([{"ts": NOW - 24 * H, "dust_count": 112,
                              "real_count": 40, "real_pct_mc": 8.0,
                              "mc": 1_000_000.0, "holder_count": 152}])
        result = pp.detect_holder_consolidation(CA, status_tokens=status,
                                                store=store, now=NOW)
        self.assertEqual(result["source"], "dust_count_delta")
        self.assertEqual(result["wallets_exited_dust"], 12)
        self.assertTrue(result["consolidating"])

    def test_missing_24h_point_uses_the_oldest_point_and_flags_stale(self):
        status = {CA: self._status(real=20, real_pct=9.0, mc=500_000.0)}
        store = self._store([{"ts": NOW - 60 * H, "dust_count": 90,
                              "real_count": 20, "real_pct_mc": 4.0,
                              "mc": 500_000.0, "holder_count": 110}])
        result = pp.detect_holder_consolidation(CA, status_tokens=status,
                                                store=store, now=NOW)
        self.assertTrue(result["available"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["hours_compared"], 60.0)

    def test_second_snapshot_comes_from_store_detail_when_status_is_empty(self):
        store = {"tokens": {CA: {
            "points": [{"ts": NOW - 24 * H, "dust_count": 120,
                        "real_count": 40, "real_pct_mc": 8.0,
                        "mc": 1_000_000.0, "holder_count": 160}],
            "latest_detail": {"ts": NOW, "dust_count": 95, "real_count": 40,
                              "real_pct_mc": 20.0, "marketcap": 1_000_000.0,
                              "holder_count": 135},
            "chronology": {"intervals": [
                {"from_ts": NOW - 24 * H, "to_ts": NOW,
                 "counts": {"dust_grew_out": 6}}]},
        }}}
        result = pp.detect_holder_consolidation(CA, status_tokens={},
                                                store=store, now=NOW)
        self.assertTrue(result["available"])
        self.assertEqual(result["holder_count"], 135)
        self.assertTrue(result["consolidating"])


@unittest.skipIf(pp is None, "UI dependencies are not installed")
class VolumeAnomalyTest(unittest.TestCase):
    def test_calm_then_spike_is_detected(self):
        result = pp.detect_volume_anomaly(CA, hourly=_candles(), now=NOW)
        self.assertTrue(result["available"])
        self.assertTrue(result["is_calm"])
        self.assertTrue(result["is_spike"])
        self.assertTrue(result["is_calm_before_storm"])
        self.assertLessEqual(result["vol_ratio_24h"], pp.VOLUME_CALM_RATIO)
        self.assertGreaterEqual(result["vol_ratio_6h_norm"],
                                pp.VOLUME_SPIKE_RATIO)
        self.assertGreater(result["confidence"], 0.5)

    def test_calm_window_excludes_the_spike_window(self):
        """Regresi: 24 jam trailing menelan spike → sinyal tak pernah menyala."""
        result = pp.detect_volume_anomaly(CA, hourly=_candles(), now=NOW)
        self.assertLess(result["vol_ratio_24h"], pp.VOLUME_CALM_RATIO)
        self.assertGreater(result["vol_ratio_24h_trailing"], 1.0)
        self.assertGreater(result["vol_6h"], result["vol_24h_prior"])

    def test_flat_volume_is_neither_calm_nor_spike(self):
        flat = [{"ts": NOW - index * H, "volume_usd": 10_000.0, "close": 1.0}
                for index in range(7 * 24)]
        result = pp.detect_volume_anomaly(CA, hourly=flat, now=NOW)
        self.assertTrue(result["available"])
        self.assertFalse(result["is_calm"])
        self.assertFalse(result["is_spike"])
        self.assertFalse(result["is_calm_before_storm"])
        self.assertEqual(result["confidence"], 0.0)

    def test_token_without_7d_history_skips_the_signal(self):
        short = [{"ts": NOW - index * H, "volume_usd": 5_000.0, "close": 1.0}
                 for index in range(6)]
        result = pp.detect_volume_anomaly(CA, hourly=short, now=NOW)
        self.assertFalse(result["available"])
        self.assertFalse(result["is_calm_before_storm"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["vol_ratio_24h"], None)

    def test_spike_without_calm_scores_only_a_fraction(self):
        rows = [{"ts": NOW - index * H, "volume_usd": 10_000.0, "close": 1.0}
                for index in range(7 * 24)]
        for index in range(6):
            rows[index]["volume_usd"] = 100_000.0
        result = pp.detect_volume_anomaly(CA, hourly=rows, now=NOW)
        self.assertTrue(result["is_spike"])
        self.assertFalse(result["is_calm"])
        self.assertFalse(result["is_calm_before_storm"])
        self.assertLess(result["confidence"], 0.4)

    def test_daily_spike_base_can_be_switched_to_the_blueprint_reading(self):
        rows = _candles()
        with mock.patch.object(pp, "VOLUME_SPIKE_BASE", "daily"):
            result = pp.detect_volume_anomaly(CA, hourly=rows, now=NOW)
        self.assertTrue(result["available"])
        self.assertGreater(result["vol_ratio_6h"], 2.0)
        self.assertTrue(result["is_spike"])


@unittest.skipIf(pp is None, "UI dependencies are not installed")
class TxVelocityTest(unittest.TestCase):
    def test_buckets_are_ordered_oldest_to_newest(self):
        swaps = [_swap("buy", 5.5), _swap("buy", 5.2), _swap("sell", 0.2)]
        buckets = pp.tx_buckets(swaps, now=NOW, hours=6)
        self.assertEqual(buckets, [2, 0, 0, 0, 0, 1])
        self.assertEqual(sum(buckets), 3)

    def test_acceleration_uses_the_2h_formula(self):
        swaps = ([_swap("buy", 5.5)] * 2 + [_swap("buy", 0.5)] * 9
                 + [_swap("sell", 0.2)] * 3)
        result = pp.detect_tx_velocity_spike(CA, swaps=swaps, now=NOW)
        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "helius_swaps")
        self.assertEqual(result["tx_count_by_hour"], [2, 0, 0, 0, 0, 12])
        # first_2h_avg = 1.0, latest_2h_avg = 6.0 → velocity 5.0
        self.assertEqual(result["velocity"], 5.0)
        self.assertEqual(result["velocity_pct"], 500.0)
        self.assertTrue(result["accelerating"])
        self.assertEqual(result["buy_pressure"], 0.786)
        self.assertTrue(result["whale_accumulation"])
        self.assertGreaterEqual(result["tx_velocity_confidence"], 0.5)

    def test_activity_from_zero_is_infinite_acceleration(self):
        swaps = [_swap("buy", 0.5), _swap("buy", 0.2)]
        result = pp.detect_tx_velocity_spike(CA, swaps=swaps, now=NOW)
        self.assertEqual(result["velocity"], float("inf"))
        self.assertEqual(result["velocity_pct"], None)
        self.assertTrue(result["accelerating"])

    def test_sell_pressure_is_not_whale_accumulation(self):
        swaps = [_swap("sell", 5.5)] * 2 + [_swap("sell", 0.5)] * 10
        result = pp.detect_tx_velocity_spike(CA, swaps=swaps, now=NOW)
        self.assertTrue(result["accelerating"])
        self.assertFalse(result["whale_accumulation"])
        self.assertEqual(result["buy_pressure"], 0.0)

    def test_empty_swap_list_is_available_false_without_api_call(self):
        result = pp.detect_tx_velocity_spike(CA, swaps=[], now=NOW)
        self.assertFalse(result["available"])
        self.assertEqual(result["tx_velocity_confidence"], 0.0)

    def test_dexscreener_fallback_is_available_and_capped(self):
        """Regresi: ``available`` dulu dibaca dari key yang belum di-set."""
        result = pp.detect_tx_velocity_spike(
            CA, txns={"h1": {"buys": 40, "sells": 10},
                      "h6": {"buys": 60, "sells": 40}}, now=NOW)
        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "dexscreener_txns")
        self.assertEqual(result["velocity"], 4.0)
        self.assertTrue(result["accelerating"])
        self.assertEqual(result["buy_pressure"], 0.8)
        self.assertLessEqual(result["tx_velocity_confidence"],
                             pp.VELOCITY_SOURCE_CONFIDENCE["dexscreener_txns"])

    def test_market_txns_are_used_when_swaps_cannot_be_fetched(self):
        market = {"txns": {"h1": {"buys": 30, "sells": 5},
                           "h6": {"buys": 40, "sells": 30}}}
        with mock.patch.object(pp, "_fetch_swaps", return_value=(None, "")):
            result = pp.detect_tx_velocity_spike(CA, market=market, now=NOW)
        self.assertEqual(result["source"], "dexscreener_txns")
        self.assertTrue(result["available"])

    def test_helius_fetch_failure_falls_back_to_dexscreener(self):
        market = {"txns": {"h1": {"buys": 12, "sells": 2},
                           "h6": {"buys": 20, "sells": 20}}}
        with mock.patch.object(pp, "get_helius_keys",
                               return_value=["key"]), \
             mock.patch("cvd.fetch_swaps", side_effect=RuntimeError("boom")):
            result = pp.detect_tx_velocity_spike(
                CA, market={"pair_addresses": ["Pool1"], **market},
                api_key=["key"], now=NOW)
        self.assertEqual(result["source"], "dexscreener_txns")
        self.assertTrue(result["available"])

    def test_no_helius_key_and_no_txns_leaves_the_signal_unavailable(self):
        with mock.patch.object(pp, "get_helius_keys", return_value=[]):
            result = pp.detect_tx_velocity_spike(CA, market={}, now=NOW)
        self.assertFalse(result["available"])
        self.assertEqual(result["tx_velocity_confidence"], 0.0)


@unittest.skipIf(pp is None, "UI dependencies are not installed")
class PumpScoreTest(unittest.TestCase):
    def test_score_spans_zero_to_ten(self):
        self.assertEqual(pp.calculate_pump_score(0, 0, 0, 0), 0.0)
        self.assertEqual(pp.calculate_pump_score(1, 1, 1, 1), 10.0)

    def test_each_signal_weighs_a_quarter(self):
        self.assertEqual(pp.calculate_pump_score(1, 0, 0, 0), 2.5)
        self.assertEqual(pp.calculate_pump_score(0.5, 0.5, 0.5, 0.5), 5.0)

    def test_out_of_range_confidence_is_clamped(self):
        self.assertEqual(pp.calculate_pump_score(2, -1, 0, 0), 2.5)

    def test_summary_counts_active_signals_and_averages_their_confidence(self):
        signals = {"liq": {"detected": True, "confidence": 0.8},
                   "consol": {"consolidating": True, "confidence": 0.6},
                   "vol": {"is_calm_before_storm": False, "confidence": 0.2},
                   "vel": {"accelerating": True,
                           "tx_velocity_confidence": 1.0}}
        summary = pp.summarize(signals)
        self.assertEqual(summary["active"], ["liq", "consol", "vel"])
        self.assertEqual(summary["active_count"], 3)
        self.assertEqual(summary["confidence_pct"], 80)
        self.assertEqual(summary["score"], 6.5)

    def test_summary_without_active_signals_reports_zero_confidence(self):
        summary = pp.summarize({"liq": {"detected": False, "confidence": 0.3}})
        self.assertEqual(summary["active_count"], 0)
        self.assertEqual(summary["confidence_pct"], 0)
        self.assertEqual(summary["alpha_window"], "belum ada window")

    def test_alpha_window_reacts_to_acceleration(self):
        signals = {"vel": {"accelerating": True}}
        self.assertIn("0–2 jam",
                      pp.estimate_alpha_window(7.0, ["liq", "consol", "vel"],
                                               signals))
        self.assertEqual(
            pp.estimate_alpha_window(7.0, ["liq", "consol", "vel"],
                                     {"vel": {"accelerating": False}}),
            "2–6 jam")
        self.assertEqual(pp.estimate_alpha_window(5.5, ["liq"], {}), "6–24 jam")
        self.assertEqual(pp.estimate_alpha_window(3.5, ["liq"], {}),
                         "1–3 hari (setup awal)")


@unittest.skipIf(pp is None, "UI dependencies are not installed")
class RunScreenTest(unittest.TestCase):
    WATCHLIST = {
        DEGEN_CA: {"symbol": "DGN", "source": "degen", "added": "2026-09-03"},
        LP_CA: {"symbol": "LPT", "source": "meteora", "added": "2026-09-03"},
        MANUAL_CA: {"symbol": "MAN", "source": "manual", "added": "2026-09-03"},
    }

    def test_only_degen_tokens_are_scanned_and_sorted_by_score(self):
        markets = {DEGEN_CA: {"price_usd": 0.01, "marketcap": 1_000_000.0,
                              "liquidity_usd": 40_000.0,
                              "pair_addresses": ["Pool1"]}}
        progress = []
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "journal.json")
            with mock.patch.object(pp, "get_market",
                                   side_effect=lambda ca: markets.get(ca, {})), \
                 mock.patch.object(pp, "get_helius_keys", return_value=[]), \
                 mock.patch.object(pp, "LIQ_JOURNAL_PATH", path), \
                 mock.patch.object(pp, "detect_volume_anomaly",
                                   return_value={"is_calm_before_storm": True,
                                                 "confidence": 0.9}), \
                 mock.patch.object(pp, "detect_holder_consolidation",
                                   return_value={"consolidating": True,
                                                 "confidence": 0.8}):
                results = pp.run_screen(self.WATCHLIST, api_key=[],
                                        progress=lambda *args: progress.append(
                                            args),
                                        max_tokens=0, workers=1, now=NOW)
            # Journal terisi oleh scan sehingga run berikutnya punya pembanding.
            self.assertEqual(len(pp.liquidity_series_for(
                pp.load_liquidity_journal(path), DEGEN_CA, now=NOW)), 1)
        self.assertEqual([row["ca"] for row in results], [DEGEN_CA])
        self.assertEqual(results[0]["symbol"], "DGN")
        self.assertEqual(results[0]["active_count"], 2)
        self.assertEqual(results[0]["score"],
                         pp.calculate_pump_score(
                             results[0]["signals"]["liq"]["confidence"], 0.8,
                             0.9, results[0]["signals"]["vel"][
                                 "tx_velocity_confidence"]))
        self.assertTrue(progress)

    def test_empty_watchlist_returns_no_results(self):
        self.assertEqual(pp.run_screen({}, api_key=[], now=NOW), [])

    def test_max_tokens_limits_the_scan(self):
        watchlist = {f"Tok{i}11111111111111111111111111111111111": {
            "symbol": f"T{i}", "source": "degen", "added": f"2026-09-0{i}"}
            for i in range(1, 5)}
        with mock.patch.object(pp, "get_market", return_value={}), \
             mock.patch.object(pp, "record_liquidity_observations",
                               return_value={}):
            results = pp.run_screen(watchlist, api_key=[], max_tokens=2,
                                    workers=1, now=NOW)
        self.assertEqual(len(results), 2)

    def test_a_broken_signal_does_not_kill_the_token_row(self):
        with mock.patch.object(pp, "get_market", return_value={}), \
             mock.patch.object(pp, "record_liquidity_observations",
                               return_value={}), \
             mock.patch.object(pp, "detect_volume_anomaly",
                               side_effect=RuntimeError("geckoterminal down")):
            results = pp.run_screen({DEGEN_CA: {"symbol": "DGN",
                                                "source": "degen"}},
                                    api_key=[], workers=1, now=NOW)
        self.assertEqual(len(results), 1)
        self.assertIn("geckoterminal down", results[0]["signals"]["vol"]["note"])
        self.assertEqual(results[0]["signals"]["vol"]["confidence"], 0.0)


@unittest.skipIf(pp is None or AppTest is None,
                 "UI dependencies are not installed")
class TokenCardTest(unittest.TestCase):
    RESULT = {
        "ca": CA, "symbol": "dgn",
        "market": {"price_usd": 0.0000123, "marketcap": 50_000_000.0,
                   "liquidity_usd": 2_100_000.0},
        "signals": {
            "liq": {"detected": True, "mult": 5.2, "first_add_usd": 2_100_000.0,
                    "second_add_usd": 10_900_000.0, "confidence": 0.8,
                    "available": True, "waves": [], "threshold": 5.0},
            "consol": {"consolidating": True, "wallets_moved_out": 8,
                       "avg_bag_growth_pct": 210.0, "confidence": 0.7,
                       "available": True, "holder_count": 1_200},
            "vol": {"is_calm_before_storm": False, "is_calm": True,
                    "is_spike": False, "vol_ratio_24h": 0.23,
                    "vol_ratio_6h_norm": 1.1, "confidence": 0.1,
                    "available": True},
            "vel": {"accelerating": True, "velocity": 1.8, "velocity_pct": 180.0,
                    "buy_pressure": 0.65, "whale_accumulation": True,
                    "tx_velocity_confidence": 0.9, "available": True},
        },
        "score": 7.8, "active_count": 3, "confidence_pct": 78,
        "alpha_window": "2–6 jam",
    }

    def _run(self, result=None):
        payload = result if result is not None else self.RESULT

        def script(payload):
            # AppTest menjalankan source fungsi ini di namespace sendiri.
            import pre_pump_screener as screener

            screener.render_token_card(payload["ca"], payload["symbol"],
                                       payload)

        return AppTest.from_function(script, args=(payload,),
                                     default_timeout=30).run()

    def _body(self, app):
        return "\n".join(block.value for block in app.markdown)

    def test_card_shows_identity_metrics_and_score(self):
        app = self._run()
        self.assertFalse(app.exception)
        body = self._body(app)
        self.assertIn("$DGN", body)
        self.assertIn("CA: Pump1111…111111", body)
        self.assertIn("MC: $50.00M", body)
        self.assertIn("Holders: 1.2k", body)
        self.assertIn("PUMP SCORE: 7.8/10", body)
        self.assertIn("SIGNALS: 3/4 active", body)
        self.assertIn("Confidence: 78%", body)
        self.assertIn("EST. ALPHA WINDOW: 2–6 jam", body)

    def test_card_shows_all_four_signal_lines(self):
        body = self._body(self._run())
        self.assertIn("Liquidity Wave:", body)
        self.assertIn("5.2x detected", body)
        self.assertIn("$2.10M → $10.90M", body)
        self.assertIn("Holder Consolidation: 8 wallets out (+210% avg bag)",
                      body)
        self.assertIn("Volume Spike:", body)
        self.assertIn("23% of avg", body)
        self.assertIn("TX Velocity:", body)
        self.assertIn("+180% last 6h", body)
        self.assertIn("65% buys", body)

    def test_card_has_chart_holders_and_cvd_shortcuts(self):
        app = self._run()
        labels = [button.label for button in app.button]
        self.assertIn("👥 Holders", labels)
        self.assertIn("📈 CVD", labels)
        charts = app.get("link_button")
        self.assertEqual([chart.label for chart in charts], ["🔗 Chart"])
        self.assertIn(f"dexscreener.com/solana/{CA}", charts[0].url)

    def test_holders_button_switches_to_the_holder_page(self):
        app = self._run()
        with mock.patch("streamlit.switch_page") as switch:
            [button for button in app.button
             if button.label == "👥 Holders"][0].click().run()
        switch.assert_called_once_with(
            "pages/5_🧮_Holder.py", query_params={"mint": CA})

    def test_liquidity_line_reports_the_best_ratio_when_below_threshold(self):
        signals = dict(self.RESULT["signals"])
        signals["liq"] = {"detected": False, "available": True,
                          "best_mult": 4.7, "threshold": 5.0,
                          "waves": [{}, {}], "confidence": 0.3}
        body = self._body(self._run({**self.RESULT, "signals": signals}))
        self.assertIn("2 wave, terbesar 4.7x (ambang 5x)", body)

    def test_card_survives_an_empty_signal_dict(self):
        app = self._run({"ca": CA, "symbol": "?", "score": 0.0,
                         "active_count": 0, "confidence_pct": 0})
        self.assertFalse(app.exception)
        body = self._body(app)
        self.assertIn("PUMP SCORE: 0.0/10", body)
        self.assertIn("data likuiditas belum cukup", body)
        self.assertIn("tidak ada history 7 hari", body)

    def test_symbol_and_ca_are_html_escaped(self):
        app = self._run({**self.RESULT, "symbol": "<cat>",
                         "ca": "Bad&Ca1111111111111111111111111111111"})
        body = self._body(app)
        self.assertIn("$&lt;CAT&gt;", body)
        self.assertNotIn("$<CAT>", body)
        self.assertIn("Bad&amp;Ca", body)


@unittest.skipIf(pp is None or AppTest is None,
                 "UI dependencies are not installed")
class MainSectionTest(unittest.TestCase):
    WATCHLIST = {DEGEN_CA: {"symbol": "DGN", "source": "degen",
                            "added": "2026-09-03"},
                 LP_CA: {"symbol": "LPT", "source": "meteora",
                         "added": "2026-09-03"}}

    def _run(self):
        def script(watchlist):
            # AppTest menjalankan source fungsi ini di namespace sendiri.
            import pre_pump_screener as screener

            screener.main(configure_page=False, watchlist=watchlist,
                          status_tokens={}, store={})

        return AppTest.from_function(script, args=(self.WATCHLIST,),
                                     default_timeout=30).run()

    def test_section_header_and_controls_render(self):
        app = self._run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Pre-Pump Screener" in block.value
                            for block in app.subheader))
        self.assertTrue(any("Jalankan Pre-Pump Scan" in (button.label or "")
                            for button in app.button))
        self.assertEqual(app.toggle[0].value, False)

    def test_scan_button_stores_sorted_results_and_renders_cards(self):
        app = self._run()
        rows = [{"ca": DEGEN_CA, "symbol": "DGN", "score": 8.1,
                 "active_count": 4, "confidence_pct": 81,
                 "alpha_window": "2–6 jam", "market": {},
                 "signals": {"liq": {"detected": True, "mult": 5.2,
                                     "available": True}}}]
        submit = [button for button in app.button
                  if "Jalankan Pre-Pump Scan" in (button.label or "")][0]
        with mock.patch.object(pp, "run_screen",
                               return_value=rows) as screen:
            app = submit.click().run()
        screen.assert_called_once()
        self.assertEqual(app.session_state[pp.RESULTS_KEY]["results"], rows)
        self.assertIn("PUMP SCORE: 8.1/10",
                      "\n".join(block.value for block in app.markdown))
        self.assertIn("Last updated:",
                      "\n".join(block.value for block in app.info))

    def test_scan_failure_is_reported_without_crashing_the_page(self):
        app = self._run()
        submit = [button for button in app.button
                  if "Jalankan Pre-Pump Scan" in (button.label or "")][0]
        with mock.patch.object(pp, "run_screen",
                               side_effect=RuntimeError("dexscreener 500")):
            app = submit.click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("dexscreener 500" in node.value
                            for node in app.error))

    def test_auto_refresh_reruns_only_after_the_interval(self):
        app = self._run()
        app.toggle[0].set_value(True)
        app.session_state[pp.RESULTS_KEY] = {
            "results": [{"ca": DEGEN_CA, "symbol": "DGN", "score": 1.0,
                         "active_count": 0, "confidence_pct": 0,
                         "alpha_window": "—", "market": {}, "signals": {}}],
            "ts": pp._now(), "error": "", "max_tokens": 24}
        with mock.patch.object(pp, "run_screen") as screen:
            app = app.run()
        screen.assert_not_called()   # belum 5 menit → tidak scan ulang

        app.session_state[pp.RESULTS_KEY]["ts"] = (
            pp._now() - pp.REFRESH_SEC - 1)
        with mock.patch.object(pp, "run_screen", return_value=[]) as screen:
            app = app.run()
        screen.assert_called_once()

    def test_auto_refresh_without_results_does_not_loop(self):
        app = self._run()
        app.toggle[0].set_value(True)
        app.session_state[pp.RESULTS_KEY] = {"results": [], "ts": 0,
                                             "error": "", "max_tokens": 24}
        with mock.patch.object(pp, "run_screen") as screen:
            app = app.run()
        screen.assert_not_called()
        self.assertIn("jalankan scan pertama dulu",
                      "\n".join(node.value for node in app.caption))


@unittest.skipIf(pp is None or AppTest is None,
                 "UI dependencies are not installed")
class AppIntegrationTest(unittest.TestCase):
    """Section Pre-Pump ikut ter-render di dashboard tanpa request jaringan."""

    def setUp(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       return_value={DEGEN_CA: {"symbol": "DGN",
                                                "source": "degen"}}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            # Backup durable store: tes tidak boleh menyentuh jaringan.
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
            mock.patch("trending_ui.screen", return_value=[]),
            mock.patch("trending_ui.screen_trending_h1", return_value=[]),
            mock.patch("trending_ui.screen_hrhr", return_value=[]),
            mock.patch("trending_ui.screen_hrhr_h1", return_value=[]),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_dashboard_renders_the_pre_pump_section(self):
        app = AppTest.from_file(APP, default_timeout=60).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Pre-Pump Screener" in block.value
                            for block in app.subheader))
        self.assertTrue(any("Jalankan Pre-Pump Scan" in (button.label or "")
                            for button in app.button))

    def test_dashboard_scan_button_calls_the_screener(self):
        app = AppTest.from_file(APP, default_timeout=60).run()
        submit = [button for button in app.button
                  if "Jalankan Pre-Pump Scan" in (button.label or "")][0]
        with mock.patch.object(pp, "run_screen", return_value=[]) as screen:
            app = submit.click().run()
        self.assertFalse(app.exception)
        screen.assert_called_once()


@unittest.skipIf(pp is None or AppTest is None,
                 "UI dependencies are not installed")
class StandalonePageTest(unittest.TestCase):
    """``pages/6_🚀_Pre-Pump.py`` = rute mandiri ``main()``."""

    PAGE = str(Path(__file__).resolve().parent.parent
               / "pages" / "6_🚀_Pre-Pump.py")

    def setUp(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       return_value={DEGEN_CA: {"symbol": "DGN",
                                                "source": "degen"}}),
            # Halaman mandiri menarik snapshot + store sendiri; tes offline.
            mock.patch("pre_pump_screener.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("pre_pump_screener.load_durable_holder_history",
                       return_value={"tokens": {}}),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_page_renders_its_own_title_and_controls(self):
        app = AppTest.from_file(self.PAGE, default_timeout=60).run()
        self.assertFalse(app.exception)
        self.assertIn("Pre-Pump Screener", app.title[0].value)
        self.assertTrue(any("Jalankan Pre-Pump Scan" in (button.label or "")
                            for button in app.button))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
