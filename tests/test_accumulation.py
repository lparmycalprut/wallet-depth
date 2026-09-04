"""Delapan metrik ``accumulation.py`` — heuristik deteksi akumulasi.

Semua tes memakai data dummy (tuple swap GMGN + titik ``holder_history``) dan
**tidak menyentuh jaringan**; store snapshot diarahkan ke temporary directory
supaya ``accumulation_history.json`` repo tidak tersentuh.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import accumulation as acc

WALLET_A = "WalletA111111111111111111111111111111111"
WALLET_B = "WalletB222222222222222222222222222222222"
WALLET_C = "WalletC333333333333333333333333333333333"
WALLET_D = "WalletD444444444444444444444444444444444"
WALLET_E = "WalletE555555555555555555555555555555555"
WALLET_F = "WalletF666666666666666666666666666666666"

DAY = 86_400
HOUR = 3600


def _swap(side, sol, ts, wallet, usd=None, tags=None):
    """Tuple swap sesuai kontrak ``cvd.fetch_gmgn_swaps`` (7 elemen)."""
    return (side, float(sol), int(ts), wallet, None,
            float(usd if usd is not None else sol * 100.0), list(tags or []))


def _point(index, buckets, *, ts=None, dust_pct=0.5):
    return {"ts": int(ts if ts is not None else (index + 1) * 14_400),
            "dust_pct_mc": dust_pct, "dust_count": buckets.get(">$0-$10", 0),
            "buckets": dict(buckets)}


# ---------------------------------------------------------------------------
# 1 — Tier Migration Velocity
# ---------------------------------------------------------------------------
class TierMigrationTest(unittest.TestCase):
    def test_mid_tiers_up_with_stable_dust_is_positive(self):
        points = [
            _point(0, {">$0-$10": 500, "$10-$100": 120, "$100-$1k": 40,
                       "$1k-$10k": 10}),
            _point(1, {">$0-$10": 505, "$10-$100": 125, "$100-$1k": 46,
                       "$1k-$10k": 12}),
        ]
        result = acc.tier_migration_velocity(points)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertEqual(result["nilai"]["deltas"]["$100-$1k"], 6)
        self.assertEqual(result["nilai"]["deltas"]["$1k-$10k"], 2)
        self.assertIn("$100-$1k", result["detail"]["mid_up"])

    def test_dust_spike_is_rejected_as_spam(self):
        points = [
            _point(0, {">$0-$10": 500, "$100-$1k": 40, "$1k-$10k": 10}),
            _point(1, {">$0-$10": 900, "$100-$1k": 44, "$1k-$10k": 11}),
        ]
        result = acc.tier_migration_velocity(points)
        self.assertEqual(result["status"], acc.NEGATIF)
        self.assertIn("spam", result["penjelasan"])

    def test_mid_tier_shrinking_is_negative(self):
        points = [
            _point(0, {">$0-$10": 500, "$100-$1k": 40, "$1k-$10k": 10}),
            _point(1, {">$0-$10": 500, "$100-$1k": 31, "$1k-$10k": 8}),
        ]
        self.assertEqual(acc.tier_migration_velocity(points)["status"],
                         acc.NEGATIF)

    def test_flat_tiers_are_neutral(self):
        points = [_point(0, {">$0-$10": 500, "$100-$1k": 40, "$1k-$10k": 10}),
                  _point(1, {">$0-$10": 500, "$100-$1k": 40, "$1k-$10k": 10})]
        self.assertEqual(acc.tier_migration_velocity(points)["status"],
                         acc.NETRAL)

    def test_single_snapshot_has_no_data(self):
        result = acc.tier_migration_velocity(
            [_point(0, {">$0-$10": 500, "$100-$1k": 40})])
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["status"], acc.NO_DATA)

    def test_points_without_buckets_have_no_data(self):
        result = acc.tier_migration_velocity(
            [{"ts": 100}, {"ts": 200, "buckets": {}}])
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["detail"]["snapshots"], 0)


# ---------------------------------------------------------------------------
# 2 — Diamond Hands Ratio
# ---------------------------------------------------------------------------
class DiamondHandsTest(unittest.TestCase):
    def test_all_holders_never_selling_is_positive(self):
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D, WALLET_E):
            swaps.append(_swap("buy", 1.0, 1_000, wallet))
            swaps.append(_swap("buy", 0.5, 2_000, wallet))
        result = acc.diamond_hands_ratio(swaps)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["nilai"], 100.0)
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertEqual(result["detail"]["diamond_wallets"], 5)

    def test_wallet_that_sold_once_is_not_diamond_hands(self):
        swaps = [
            _swap("buy", 2.0, 1_000, WALLET_A),
            _swap("sell", 0.5, 2_000, WALLET_A),   # pernah net-sell
            _swap("buy", 1.0, 3_000, WALLET_A),    # buy lagi tidak memulihkan
            _swap("buy", 1.0, 1_000, WALLET_B),
            _swap("buy", 1.0, 1_000, WALLET_C),
            _swap("buy", 1.0, 1_000, WALLET_D),
            _swap("buy", 1.0, 1_000, WALLET_E),
        ]
        result = acc.diamond_hands_ratio(swaps)
        self.assertEqual(result["nilai"], 80.0)
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertNotIn("WalletA…1111", result["detail"]["contoh_wallet"])

    def test_majority_sellers_is_negative(self):
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D):
            swaps.append(_swap("buy", 1.0, 1_000, wallet))
            swaps.append(_swap("sell", 1.0, 2_000, wallet))
        swaps.append(_swap("buy", 1.0, 1_000, WALLET_E))
        result = acc.diamond_hands_ratio(swaps)
        self.assertEqual(result["nilai"], 20.0)
        self.assertEqual(result["status"], acc.NEGATIF)

    def test_too_few_wallets_is_not_enough_data(self):
        result = acc.diamond_hands_ratio([_swap("buy", 1.0, 1_000, WALLET_A)])
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["status"], acc.NO_DATA)
        self.assertEqual(result["nilai_text"], "—")


# ---------------------------------------------------------------------------
# 3 — Pola DCA vs One-off Buy
# ---------------------------------------------------------------------------
class DcaPatternTest(unittest.TestCase):
    def test_repeated_small_buys_are_dca(self):
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D, WALLET_E):
            for step in range(4):
                swaps.append(_swap("buy", 0.2, 1_000 + step * 3_600, wallet))
        result = acc.dca_vs_oneoff(swaps)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertEqual(result["nilai"]["dca"], 5)
        self.assertEqual(result["nilai"]["avg_buy_tx"], 4.0)

    def test_single_large_buys_are_one_off(self):
        swaps = [_swap("buy", 5.0, 1_000, wallet)
                 for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D,
                                WALLET_E)]
        result = acc.dca_vs_oneoff(swaps)
        self.assertEqual(result["status"], acc.NEGATIF)
        self.assertEqual(result["nilai"]["oneoff"], 5)
        self.assertIn("one-off", result["penjelasan"])

    def test_dominant_buy_among_many_is_still_one_off(self):
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D, WALLET_E):
            swaps.append(_swap("buy", 9.0, 1_000, wallet))     # 90% dari total
            swaps.append(_swap("buy", 0.5, 2_000, wallet))
            swaps.append(_swap("buy", 0.5, 3_000, wallet))
        result = acc.dca_vs_oneoff(swaps)
        self.assertEqual(result["nilai"]["oneoff"], 5)
        self.assertEqual(result["nilai"]["dca"], 0)

    def test_too_few_buyers_is_not_enough_data(self):
        result = acc.dca_vs_oneoff([_swap("buy", 1.0, 1_000, WALLET_A),
                                    _swap("sell", 1.0, 2_000, WALLET_B)])
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["detail"]["buyers"], 1)


# ---------------------------------------------------------------------------
# 4 — Smart Money / PnL (GMGN saja)
# ---------------------------------------------------------------------------
class SmartMoneyPnlTest(unittest.TestCase):
    def test_smart_money_net_buyers_with_profit_are_positive(self):
        swaps = [
            _swap("buy", 3.0, 1_000, WALLET_A, tags=["smart_degen"]),
            _swap("buy", 2.0, 2_000, WALLET_B, tags=["smart_money"]),
            _swap("buy", 1.0, 3_000, WALLET_C),
        ]
        meta = {
            WALLET_A: {"maker_tags": ["smart_degen"], "realized_profit": 1200.0,
                       "unrealized_profit": 300.0},
            WALLET_B: {"maker_tags": ["smart_money"], "realized_profit": 800.0},
            WALLET_C: {"maker_tags": [], "realized_profit": -50.0},
        }
        result = acc.smart_money_pnl(swaps, meta)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertEqual(result["nilai"]["smart_wallets"], 2)
        self.assertEqual(result["nilai"]["net_buyers"], 2)
        self.assertEqual(result["nilai"]["profit_share_pct"], 100.0)
        self.assertEqual(result["nilai"]["median_realized_usd"], 1000.0)
        self.assertIn("GMGN", result["sumber"])

    def test_empty_wallet_metadata_is_not_enough_data(self):
        swaps = [_swap("buy", 3.0, 1_000, WALLET_A, tags=["smart_degen"])]
        result = acc.smart_money_pnl(swaps, {})
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["status"], acc.NO_DATA)
        # keputusan user: PnL lintas token lewat Helius tidak diimplementasikan
        self.assertIn("Helius", result["penjelasan"])

    def test_metadata_without_smart_tags_is_neutral_with_data(self):
        swaps = [_swap("buy", 3.0, 1_000, WALLET_A)]
        result = acc.smart_money_pnl(swaps, {WALLET_A: {"maker_tags": [],
                                                        "realized_profit": 10.0}})
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["status"], acc.NETRAL)
        self.assertEqual(result["nilai_text"], "0 wallet smart money")

    def test_smart_money_selling_is_negative(self):
        swaps = [
            _swap("buy", 3.0, 1_000, WALLET_A, tags=["smart_degen"]),
            _swap("sell", 4.0, 2_000, WALLET_A, tags=["smart_degen"]),
        ]
        meta = {WALLET_A: {"maker_tags": ["smart_degen"],
                           "realized_profit": 500.0}}
        result = acc.smart_money_pnl(swaps, meta)
        self.assertEqual(result["status"], acc.NEGATIF)
        self.assertEqual(result["nilai"]["net_buyers"], 0)

    def test_tags_from_swap_tuple_are_used_too(self):
        """Tag datang dari elemen ke-7 swap walau metadata GMGN minim."""
        swaps = [_swap("buy", 2.0, 1_000, WALLET_A, tags=["bluechip_owner"])]
        result = acc.smart_money_pnl(swaps, {WALLET_A: {"maker_tags": [],
                                                        "realized_profit": 0.0}})
        self.assertEqual(result["nilai"]["smart_wallets"], 1)


# ---------------------------------------------------------------------------
# 5 — Silent Range Accumulation
# ---------------------------------------------------------------------------
class SilentRangeTest(unittest.TestCase):
    @staticmethod
    def _volatility(stddev=0.8, history=2.0):
        return {"available": True, "price_stddev_4h": stddev,
                "history_stddev_pct": history}

    def test_quiet_volume_narrow_range_and_small_positive_cvd(self):
        swaps = [_swap("buy", 1.0, 1_000, WALLET_A, usd=600.0),
                 _swap("sell", 1.0, 2_000, WALLET_B, usd=500.0)]
        result = acc.silent_range_accumulation(
            volume_usd=45_000.0, volatility=self._volatility(), swaps=swaps)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertAlmostEqual(result["nilai"]["cvd_net_pct"], 9.09, places=2)

    def test_dead_token_below_volume_floor_is_not_accumulation(self):
        result = acc.silent_range_accumulation(
            volume_usd=800.0, volatility=self._volatility(), cvd_net=5.0)
        self.assertEqual(result["status"], acc.NEGATIF)
        self.assertIn("terlalu mati", result["penjelasan"])
        self.assertFalse(result["detail"]["volume_tenang"])

    def test_loud_volume_is_not_silent(self):
        result = acc.silent_range_accumulation(
            volume_usd=900_000.0, volatility=self._volatility(), cvd_net=5.0)
        self.assertEqual(result["status"], acc.NETRAL)
        self.assertIn("plafon", result["penjelasan"])

    def test_wide_range_blocks_the_signal(self):
        result = acc.silent_range_accumulation(
            volume_usd=45_000.0, volatility=self._volatility(stddev=3.0),
            cvd_net=5.0)
        self.assertEqual(result["status"], acc.NETRAL)
        self.assertFalse(result["detail"]["range_menyempit"])

    def test_negative_cvd_blocks_the_signal(self):
        result = acc.silent_range_accumulation(
            volume_usd=45_000.0, volatility=self._volatility(), cvd_net=-4.0)
        self.assertEqual(result["status"], acc.NETRAL)
        self.assertFalse(result["detail"]["cvd_positif_tipis"])

    def test_unavailable_volatility_is_not_enough_data(self):
        result = acc.silent_range_accumulation(volume_usd=45_000.0,
                                               volatility={"available": False},
                                               cvd_net=5.0)
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["status"], acc.NO_DATA)

    def test_missing_volume_is_not_enough_data(self):
        result = acc.silent_range_accumulation(volume_usd=None,
                                               volatility=self._volatility(),
                                               cvd_net=5.0)
        self.assertFalse(result["cukup_data"])


# ---------------------------------------------------------------------------
# 6 — Spring / Test Pattern
# ---------------------------------------------------------------------------
class SpringTestPatternTest(unittest.TestCase):
    @staticmethod
    def _candles():
        """Level support $0.010; candle ke-3 menusuk 0.0092 lalu close 0.0104."""
        base = 1_700_000_000
        rows = []
        for index in range(6):
            rows.append({"ts": base + index * 4 * HOUR, "open": 0.0105,
                         "high": 0.0108, "low": 0.0102, "close": 0.0105,
                         "volume_usd": 20_000.0})
        rows[3] = {"ts": base + 3 * 4 * HOUR, "open": 0.0104, "high": 0.0105,
                   "low": 0.0092, "close": 0.0104, "volume_usd": 4_000.0}
        return rows

    def test_quiet_spring_below_level_is_positive(self):
        result = acc.spring_test_pattern(self._candles(), level=0.010)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertLess(result["nilai"]["volume_ratio"], 1.0)
        self.assertGreater(result["nilai"]["close"], 0.010)
        self.assertLess(result["nilai"]["low"], 0.010)

    def test_loud_wick_is_neutral_not_spring(self):
        candles = self._candles()
        candles[3]["volume_usd"] = 90_000.0
        result = acc.spring_test_pattern(candles, level=0.010)
        self.assertEqual(result["status"], acc.NETRAL)
        self.assertFalse(result["detail"]["volume_tenang"])

    def test_no_wick_below_level_is_neutral(self):
        candles = [dict(row, low=0.0102) for row in self._candles()]
        result = acc.spring_test_pattern(candles, level=0.010)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["status"], acc.NETRAL)
        self.assertIn("Tidak ada candle", result["penjelasan"])

    def test_close_below_level_is_not_a_spring(self):
        candles = self._candles()
        candles[3]["close"] = 0.0095     # jeblok, bukan spring
        result = acc.spring_test_pattern(candles, level=0.010)
        self.assertEqual(result["status"], acc.NETRAL)

    def test_level_is_derived_from_daily_candles(self):
        daily = [{"date": "2026-09-01", "low": 0.011, "close": 0.012},
                 {"date": "2026-09-02", "low": 0.010, "close": 0.011},
                 {"date": "2026-09-03", "low": 0.0105, "close": 0.0108}]
        self.assertAlmostEqual(acc.derive_support_level(daily), 0.010)
        result = acc.spring_test_pattern(self._candles(), daily_candles=daily)
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertAlmostEqual(result["detail"]["level"], 0.010)

    def test_without_level_there_is_no_data(self):
        result = acc.spring_test_pattern(self._candles())
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["status"], acc.NO_DATA)

    def test_too_few_candles_is_not_enough_data(self):
        result = acc.spring_test_pattern(self._candles()[:2], level=0.010)
        self.assertFalse(result["cukup_data"])

    def test_hourly_candles_are_aggregated_to_four_hours(self):
        base = (1_700_000_400 // acc.INTERVAL_4H) * acc.INTERVAL_4H
        hourly = [{"ts": base + step * HOUR, "open": 0.01, "high": 0.011,
                   "low": 0.009, "close": 0.010, "volume_usd": 1_000.0}
                  for step in range(9)]
        rows = acc.aggregate_4h_candles(hourly)
        self.assertEqual(len(rows), 3)          # 9 jam → 3 bucket 4 jam
        self.assertEqual(rows[0]["volume_usd"], 4_000.0)
        self.assertEqual(rows[0]["hours"], 4)
        self.assertEqual(rows[2]["hours"], 1)
        result = acc.spring_test_pattern(hourly=hourly, level=0.0095)
        self.assertTrue(result["cukup_data"])   # low 0.009 < level, close di atas


# ---------------------------------------------------------------------------
# 7 — Fresh wallet prep (pengganti funder chain)
# ---------------------------------------------------------------------------
class FunderPrepTest(unittest.TestCase):
    def test_gradual_fresh_wallets_without_sells_are_positive(self):
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C):
            for step in range(3):
                swaps.append(_swap("buy", 0.4, 1_000 + step * 3_600, wallet,
                                   tags=["fresh_wallet"]))
        result = acc.funder_prep_cluster(swaps)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertEqual(result["nilai"]["gradual_no_sell"], 3)
        self.assertEqual(result["nilai"]["fresh_wallets"], 3)
        # disclaimer heuristik wajib ada (bukan bukti identitas funder)
        self.assertIn("funder", result["penjelasan"].lower())
        self.assertIn("Heuristik", result["penjelasan"])

    def test_instant_snipers_are_not_prep(self):
        swaps = [_swap("buy", 5.0, 1_000, wallet, tags=["fresh_wallet"])
                 for wallet in (WALLET_A, WALLET_B, WALLET_C)]
        result = acc.funder_prep_cluster(swaps)
        self.assertEqual(result["status"], acc.NEGATIF)
        self.assertEqual(result["nilai"]["gradual_no_sell"], 0)

    def test_fresh_wallet_that_sold_is_excluded(self):
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C):
            for step in range(3):
                swaps.append(_swap("buy", 0.4, 1_000 + step * 3_600, wallet,
                                   tags=["fresh_wallet"]))
        swaps.append(_swap("sell", 0.4, 90_000, WALLET_C,
                           tags=["fresh_wallet"]))
        result = acc.funder_prep_cluster(swaps)
        self.assertEqual(result["nilai"]["fresh_wallets"], 3)
        self.assertEqual(result["nilai"]["gradual_no_sell"], 2)
        self.assertEqual(result["status"], acc.NETRAL)

    def test_too_few_fresh_wallets_is_not_enough(self):
        swaps = [_swap("buy", 1.0, 1_000, WALLET_A, tags=["fresh_wallet"]),
                 _swap("buy", 1.0, 1_000, WALLET_B, tags=["fresh_wallet"])]
        result = acc.funder_prep_cluster(swaps)
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["status"], acc.NO_DATA)

    def test_tags_can_come_from_wallet_metadata(self):
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C):
            for step in range(2):
                swaps.append(_swap("buy", 0.3, 1_000 + step * 7_200, wallet))
        meta = {wallet: {"maker_tags": ["fresh_wallet"]}
                for wallet in (WALLET_A, WALLET_B, WALLET_C)}
        result = acc.funder_prep_cluster(swaps, meta)
        self.assertEqual(result["nilai"]["gradual_no_sell"], 3)


# ---------------------------------------------------------------------------
# 8 — Sell-Side Liquidity Thinning
# ---------------------------------------------------------------------------
class SellSideThinningTest(unittest.TestCase):
    def test_quiet_holders_dominate_supply(self):
        now = 100 * DAY
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D, WALLET_E):
            swaps.append(_swap("buy", 2.0, now - 30 * DAY, wallet))
        result = acc.sell_side_thinning(swaps, days=14, now=now)
        self.assertTrue(result["cukup_data"])
        self.assertEqual(result["nilai"]["quiet_share_pct"], 100.0)
        self.assertEqual(result["status"], acc.POSITIF)
        self.assertEqual(result["nilai"]["quiet_wallets"], 5)

    def test_recent_sellers_thicken_the_sell_side(self):
        now = 100 * DAY
        swaps = []
        for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D, WALLET_E):
            swaps.append(_swap("buy", 2.0, now - 30 * DAY, wallet))
            swaps.append(_swap("sell", 1.0, now - 2 * DAY, wallet))
        result = acc.sell_side_thinning(swaps, days=14, now=now)
        self.assertEqual(result["nilai"]["quiet_share_pct"], 0.0)
        self.assertEqual(result["status"], acc.NEGATIF)

    def test_partial_quiet_share_is_neutral(self):
        now = 100 * DAY
        swaps = []
        # 3 wallet tenang @ 1 SOL net (3 SOL) vs 2 wallet aktif @ 1 SOL net
        # (2 SOL) -> 3/5 = 60% pasokan teramati di tangan wallet tanpa jual.
        for wallet in (WALLET_A, WALLET_B, WALLET_C):
            swaps.append(_swap("buy", 1.0, now - 30 * DAY, wallet))
        for wallet in (WALLET_D, WALLET_E):
            swaps.append(_swap("buy", 2.0, now - 30 * DAY, wallet))
            swaps.append(_swap("sell", 1.0, now - 1 * DAY, wallet))
        result = acc.sell_side_thinning(swaps, days=14, now=now)
        self.assertEqual(result["nilai"]["quiet_share_pct"], 60.0)
        self.assertEqual(result["status"], acc.NETRAL)

    def test_previous_value_produces_a_delta(self):
        now = 100 * DAY
        swaps = [_swap("buy", 2.0, now - 30 * DAY, wallet)
                 for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D,
                                WALLET_E)]
        result = acc.sell_side_thinning(swaps, days=14, now=now, previous=70.0)
        self.assertEqual(result["nilai"]["delta_pp"], 30.0)
        self.assertIn("+30.00 pp", result["penjelasan"])

    def test_too_few_holders_is_not_enough_data(self):
        result = acc.sell_side_thinning([_swap("buy", 2.0, 1_000, WALLET_A)])
        self.assertFalse(result["cukup_data"])
        self.assertEqual(result["status"], acc.NO_DATA)


# ---------------------------------------------------------------------------
# Skor gabungan, laporan token, dan store snapshot
# ---------------------------------------------------------------------------
class ScoreAndReportTest(unittest.TestCase):
    @staticmethod
    def _result(key, status, cukup=True):
        return acc.metric_result(key, nilai=1, status=status,
                                 penjelasan="x", cukup_data=cukup)

    def test_all_positive_scores_100(self):
        results = [self._result(key, acc.POSITIF) for key in acc.METRIC_NAMES]
        summary = acc.accumulation_score(results)
        self.assertEqual(summary["skor"], 100.0)
        self.assertEqual(summary["status"], acc.TOKEN_AKUMULASI)
        self.assertEqual(summary["metrik_dipakai"], 8)

    def test_metrics_without_data_are_excluded_from_the_average(self):
        results = [self._result("tier_migration", acc.POSITIF),
                   self._result("diamond_hands", acc.POSITIF),
                   self._result("dca_pattern", acc.NO_DATA, cukup=False)]
        summary = acc.accumulation_score(results)
        self.assertEqual(summary["skor"], 100.0)
        self.assertEqual(summary["metrik_dipakai"], 2)

    def test_half_positive_half_negative_is_neutral(self):
        results = ([self._result(key, acc.POSITIF)
                    for key in list(acc.METRIC_NAMES)[:4]]
                   + [self._result(key, acc.NEGATIF)
                      for key in list(acc.METRIC_NAMES)[4:]])
        summary = acc.accumulation_score(results)
        self.assertEqual(summary["skor"], 50.0)
        self.assertEqual(summary["status"], acc.TOKEN_NETRAL)

    def test_no_data_at_all_is_tidak_cukup_data(self):
        results = [self._result(key, acc.NO_DATA, cukup=False)
                   for key in acc.METRIC_NAMES]
        summary = acc.accumulation_score(results)
        self.assertIsNone(summary["skor"])
        self.assertEqual(summary["status"], acc.TOKEN_NO_DATA)

    def test_report_collects_eight_metrics(self):
        points = [_point(0, {">$0-$10": 500, "$100-$1k": 40, "$1k-$10k": 10}),
                  _point(1, {">$0-$10": 502, "$100-$1k": 45, "$1k-$10k": 12})]
        # buy 5 x $120 vs sell $540 -> CVD net +5,26% (positif tipis, syarat
        # metrik 5) dan 5/6 wallet tidak pernah jual (syarat metrik 2).
        swaps = [_swap("buy", 1.0, 1_000, wallet, usd=120.0)
                 for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D,
                                WALLET_E)]
        swaps.append(_swap("sell", 1.0, 2_000, WALLET_F, usd=540.0))
        report = acc.build_token_report(
            "Mint111111111111111111111111111111111111", "tst",
            points=points, swaps=swaps,
            volatility={"available": True, "price_stddev_4h": 0.5,
                        "history_stddev_pct": 2.0},
            volume_usd=40_000.0, level=None, daily_candles=None)
        self.assertEqual(len(report["results"]), 8)
        self.assertEqual(set(report["metrics"]), set(acc.METRIC_NAMES))
        self.assertEqual(report["metrics"]["tier_migration"]["status"],
                         acc.POSITIF)
        self.assertEqual(report["metrics"]["diamond_hands"]["status"],
                         acc.POSITIF)
        # wallet F hanya menjual (net negatif) sehingga tidak dihitung holder;
        # 5 holder tersisa semuanya tanpa jual -> sisi jual tipis.
        self.assertEqual(report["metrics"]["sell_side_thinning"]["status"],
                         acc.POSITIF)
        self.assertEqual(report["metrics"]["silent_range"]["status"],
                         acc.POSITIF)
        # metrik tanpa bahan mentah ditandai, bukan dihitung netral
        self.assertIn("spring_test", report["missing"])
        self.assertIn("smart_money_pnl", report["missing"])
        self.assertEqual(report["metrics_total"], 8)
        self.assertIn(report["status"], (acc.TOKEN_AKUMULASI, acc.TOKEN_NETRAL,
                                         acc.TOKEN_NO_DATA))

    def test_every_result_has_the_render_contract(self):
        points = [_point(0, {">$0-$10": 500, "$100-$1k": 40})]
        report = acc.build_token_report("Mint", "tst", points=points, swaps=[])
        for result in report["results"]:
            for field in ("key", "nama", "nilai", "nilai_text", "status",
                          "status_label", "penjelasan", "cukup_data", "bobot",
                          "detail", "sumber"):
                self.assertIn(field, result)
            self.assertTrue(result["penjelasan"])
            self.assertIn(result["status"], acc.STATUS_LABEL)


class SnapshotStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "accumulation_history.json")
        self.addCleanup(self.tmp.cleanup)

    def test_snapshot_roundtrip_exposes_previous_thinning(self):
        report = {
            "symbol": "TST", "score": 72.5, "status": acc.TOKEN_AKUMULASI,
            "metrics_used": 6, "positives": ["tier_migration"],
            "metrics": {"sell_side_thinning": {
                "cukup_data": True,
                "nilai": {"quiet_share_pct": 82.0, "quiet_wallets": 9}}},
        }
        store = acc.record_snapshot(acc.empty_store(), "Mint1", report,
                                    now=1_700_000_000)
        self.assertEqual(acc.thinning_previous(store, "Mint1"), 82.0)
        acc.save_accumulation_history(store, self.path)
        loaded = acc.load_accumulation_history(self.path)
        self.assertEqual(loaded["schema"], "wallet-depth-accumulation-v1")
        self.assertEqual(acc.thinning_previous(loaded, "Mint1"), 82.0)
        self.assertEqual(loaded["tokens"]["Mint1"]["points"][-1]["score"], 72.5)

    def test_second_snapshot_allows_a_delta(self):
        store = acc.empty_store()
        for index, share in enumerate((60.0, 75.0)):
            report = {"symbol": "TST", "score": 50.0,
                      "status": acc.TOKEN_NETRAL, "metrics_used": 4,
                      "positives": [],
                      "metrics": {"sell_side_thinning": {
                          "cukup_data": True,
                          "nilai": {"quiet_share_pct": share,
                                    "quiet_wallets": 5}}}}
            previous = acc.thinning_previous(store, "Mint1")
            store = acc.record_snapshot(store, "Mint1", report,
                                        now=1_700_000_000 + index * DAY)
            if index == 1:
                self.assertEqual(previous, 60.0)
        result = acc.sell_side_thinning(
            [_swap("buy", 2.0, 1_000, wallet)
             for wallet in (WALLET_A, WALLET_B, WALLET_C, WALLET_D, WALLET_E)],
            now=1_700_000_000 + 2 * DAY,
            previous=acc.thinning_previous(store, "Mint1"))
        self.assertEqual(result["nilai"]["delta_pp"], 25.0)

    def test_missing_or_broken_file_returns_empty_store(self):
        self.assertEqual(acc.load_accumulation_history(self.path)["tokens"], {})
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{bukan json")
        self.assertEqual(acc.load_accumulation_history(self.path)["tokens"], {})

    def test_history_is_bounded(self):
        store = acc.empty_store()
        for index in range(70):
            store = acc.record_snapshot(store, "Mint1", {"symbol": "TST"},
                                        now=1_700_000_000 + index * 60)
        self.assertEqual(len(store["tokens"]["Mint1"]["points"]), 60)
        self.assertTrue(os.path.exists(self.path) is False)  # belum disimpan


class SwapNormalizationTest(unittest.TestCase):
    def test_legacy_short_tuples_are_tolerated(self):
        rows = acc.normalize_swaps([("buy", 1.0, 1_000),
                                    ("sell", 2.0, 2_000, WALLET_A),
                                    ("transfer", 3.0, 3_000, WALLET_B),
                                    ("buy", 0.0, 4_000, WALLET_C)])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["side"], "buy")
        self.assertEqual(rows[1]["wallet"], WALLET_A)

    def test_swaps_are_sorted_oldest_first(self):
        rows = acc.normalize_swaps([("buy", 1.0, 5_000, WALLET_A),
                                    ("buy", 1.0, 1_000, WALLET_B)])
        self.assertEqual([row["ts"] for row in rows], [1_000, 5_000])

    def test_window_filter_keeps_the_tuple_contract(self):
        swaps = [("buy", 1.0, 1_000, WALLET_A, None, 100.0, ["fresh_wallet"]),
                 ("buy", 1.0, 9_000, WALLET_B, None, 100.0, [])]
        rows = acc.window_swaps(swaps, since_ts=2_000)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], WALLET_B)
        self.assertEqual(len(rows[0]), 7)

    def test_cvd_net_pct_is_none_without_volume(self):
        self.assertIsNone(acc.cvd_net_pct([("buy", 1.0, 1_000, WALLET_A)]))
        self.assertEqual(acc.cvd_net_pct([
            ("buy", 1.0, 1_000, WALLET_A, None, 300.0, []),
            ("sell", 1.0, 2_000, WALLET_B, None, 100.0, [])]), 50.0)

    def test_pair_address_tolerates_an_empty_market_payload(self):
        """DexScreener tanpa pair tidak boleh melempar IndexError."""
        self.assertEqual(acc.select_pair_address({}), "")
        self.assertEqual(acc.select_pair_address({"pair_addresses": []}), "")
        self.assertEqual(acc.select_pair_address({"pair_addresses": [None]}), "")
        self.assertEqual(acc.select_pair_address(None), "")
        self.assertEqual(
            acc.select_pair_address({"pair_addresses": ["", "Pool111"]}),
            "Pool111")

    def test_mask_address_hides_the_middle(self):
        self.assertEqual(acc.mask_address(WALLET_A), "Wall…1111")
        self.assertEqual(acc.mask_address(""), "—")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
