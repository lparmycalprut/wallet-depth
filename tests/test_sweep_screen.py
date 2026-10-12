# -*- coding: utf-8 -*-
"""Mesin skrining kelayakan sweep (:mod:`sweep_screen`).

Semua angka di sini berasal dari kasus nyata COCKROACH (``H4KUxs…nyJc``)
1 Okt 2026, jadi test mengunci **hasil verifikasi**, bukan sekadar bentuk
fungsi:

- rumus ``(akar(m)-1) x liq/MC`` direproduksi pada angka aktual
  (``(akar(8,67)-1) x 12,95% = 25,2%`` dan ``$58.778/$233.451 = 25,2%``);
- deteksi sweep harus menangkap candle 22:42 WIB (volume $180.744 vs $152
  menit sebelumnya, close +222,6%);
- kriteria shakeout harus menangkap pola 20:00/21:00 WIB (turun 47%, lalu low
  naik 17%).
"""
from __future__ import annotations

import unittest

import sweep_screen as ss


# --- angka nyata COCKROACH, 1 Okt 2026 (WIB = UTC+7) ---
BASE_PRICE = 0.00023768309790897773   # harga tenang sebelum sweep (22:41)
PEAK = 0.0020603307226025585          # puncak candle sweep (22:49)
LIQ_USD = 30232.0                     # reserve quote sebelum sweep
MC_USD = 233451.0                     # market cap sebelum sweep
NET_INFLOW = 58778.0                  # net inflow hasil rekonstruksi reserve
PAPER_MCAP = 1790194.0                # paper mcap yang diciptakan


def _candles(rows):
    """``[(ts, o, h, l, c, v), …]`` → list of list."""
    return [list(r) for r in rows]


class LeverageFormulaTest(unittest.TestCase):
    def test_cost_matches_cockroach_actual(self):
        mult = PEAK / BASE_PRICE
        liq_mc = LIQ_USD / MC_USD
        frac = ss.leverage_cost(mult, liq_mc)
        self.assertAlmostEqual(frac, NET_INFLOW / MC_USD, places=3)
        self.assertAlmostEqual(frac * MC_USD, NET_INFLOW, delta=60.0)

    def test_ratio_matches_cockroach_actual(self):
        mult = PEAK / BASE_PRICE
        liq_mc = LIQ_USD / MC_USD
        ratio = ss.leverage_ratio(mult, liq_mc)
        self.assertAlmostEqual(ratio, PAPER_MCAP / NET_INFLOW, places=1)

    def test_smaller_liq_mc_is_cheaper(self):
        cheap = ss.leverage_cost(10.0, 0.02)
        pricey = ss.leverage_cost(10.0, 0.30)
        self.assertLess(cheap, pricey)
        # liq/MC 5% → 10,81% MC untuk naik 10x; 30% → 64,87% MC.
        self.assertAlmostEqual(ss.leverage_cost(10.0, 0.05) * 100, 10.81, places=2)
        self.assertAlmostEqual(ss.leverage_cost(10.0, 0.30) * 100, 64.87, places=2)

    def test_invalid_input_returns_none(self):
        self.assertIsNone(ss.leverage_cost(None, 0.1))
        self.assertIsNone(ss.leverage_cost(5.0, 0))
        self.assertIsNone(ss.leverage_cost(-5.0, 0.1))
        self.assertIsNone(ss.leverage_ratio("x", 0.1))

    def test_target_costs_feasibility(self):
        rows = ss.target_costs(0.02, mults=(10.0,))
        self.assertTrue(rows[0]["feasible"])
        rows = ss.target_costs(0.30, mults=(50.0,))
        self.assertFalse(rows[0]["feasible"])


class CriteriaTest(unittest.TestCase):
    def test_liq_mc_threshold(self):
        self.assertTrue(ss.criterion_liq_mc(100.0, 1000.0)["passed"])
        self.assertFalse(ss.criterion_liq_mc(200.0, 1000.0)["passed"])
        self.assertIsNone(ss.criterion_liq_mc(None, 1000.0)["passed"])

    def test_lp_locked_requires_closed_authority(self):
        ok = ss.criterion_lp_locked(95.0, None, None)
        self.assertTrue(ok["passed"])
        bad = ss.criterion_lp_locked(95.0, "SomeAuthority111", None)
        self.assertFalse(bad["passed"])
        # 89,82% (nilai COCKROACH nyata) harus LOLOS di ambang 85%.
        self.assertTrue(ss.criterion_lp_locked(89.81783209657127, None, None)["passed"])
        low = ss.criterion_lp_locked(50.0, None, None)
        self.assertFalse(low["passed"])

    def test_float_spread_uses_percent_input(self):
        # 18,92% top-10 + holder terbesar 3,00% → tidak lulus (harus < 3,00)
        self.assertFalse(
            ss.criterion_float_spread(18.92, [3.0, 2.7, 2.11])["passed"])
        self.assertTrue(
            ss.criterion_float_spread(18.92, [2.99, 2.7, 2.11])["passed"])
        # Terkonsentrasi → gagal
        self.assertFalse(ss.criterion_float_spread(40.0, [12.0])["passed"])
        self.assertIsNone(ss.criterion_float_spread(None, [])["passed"])

    def test_absorption_needs_history_then_scores(self):
        self.assertIsNone(ss.criterion_absorption([])["passed"])
        self.assertIsNone(ss.criterion_absorption([{"ts": 1}])["passed"])
        rows = [
            {"ts": 1, "vol_1h": 10000, "buys_1h": 60, "sells_1h": 40,
             "price": 0.001},
            {"ts": 2, "vol_1h": 12000, "buys_1h": 70, "sells_1h": 30,
             "price": 0.00102},
            {"ts": 3, "vol_1h": 9000, "buys_1h": 55, "sells_1h": 45,
             "price": 0.00099},
        ]
        self.assertTrue(ss.criterion_absorption(rows)["passed"])
        # Harga sudah lari → bukan akumulasi. Yang diubah hanya harga
        # terakhir: menskalakan seluruh harga dengan faktor sama tidak
        # mengubah drift, jadi tidak menguji apa pun.
        rows[-1]["price"] = 0.001 * 3
        self.assertFalse(ss.criterion_absorption(rows)["passed"])
        # Net negatif (distribusi) dengan harga sideways juga bukan akumulasi
        distribute = [dict(r, buys_1h=30, sells_1h=70) for r in rows[:3]]
        self.assertFalse(ss.criterion_absorption(distribute)["passed"])

    def test_vol_expansion_detects_trough_then_growth(self):
        rows = [
            {"ts": 1, "vol_1h": 50000, "price": 0.001},
            {"ts": 2, "vol_1h": 3000, "price": 0.001},   # titik tersepi
            {"ts": 3, "vol_1h": 12000, "price": 0.0013},
            {"ts": 4, "vol_1h": 30000, "price": 0.0014},
        ]
        check = ss.criterion_vol_expansion(rows)
        self.assertTrue(check["passed"])
        self.assertIn("10.0x", check["detail"])
        # Sudah vertikal → sweep, bukan base. Harga terakhir dinaikkan relatif
        # terhadap titik tersepi (menskalakan semua harga dengan faktor sama
        # tidak mengubah rasio, jadi test seperti itu tidak menguji apa pun).
        rows[2]["price"] = 0.001 * 6
        rows[3]["price"] = 0.001 * 8
        self.assertFalse(ss.criterion_vol_expansion(rows)["passed"])

    def test_shakeout_with_higher_low(self):
        # Bentuk nyata COCKROACH 1 Okt, **sebelum** candle sweep:
        # 19:00 naik → 20:00 turun 47% → 21:00 higher low.
        candles = _candles([
            (1, 0.00040, 0.00048, 0.000395, 0.000482, 22781),
            (2, 0.000482, 0.000495, 0.000260, 0.000318, 30539),
            (3, 0.000318, 0.000375, 0.000303, 0.000343, 18699),
        ])
        check = ss.criterion_shakeout(candles)
        self.assertTrue(check["passed"])
        self.assertIn("47%", check["detail"])
        # candle test memakai nilai bulat 0,000260 → 0,000303 = +16,5%
        self.assertIn("+16.5%", check["detail"])

    def test_sweep_candle_removes_the_higher_low(self):
        # Candle sweep COCKROACH (22:00) menyapu low sampai 0,00021623 —
        # **di bawah** low shakeout 0,00026020. Karena itu kriteria kelayakan
        # dan status "sweep terjadi" saling eksklusif: begitu sweep jalan,
        # bukti higher-low-nya hilang. Ini perilaku yang diinginkan, bukan bug.
        with_sweep = _candles([
            (1, 0.00040, 0.00048, 0.000395, 0.000482, 22781),
            (2, 0.000482, 0.000495, 0.000260, 0.000318, 30539),
            (3, 0.000318, 0.000375, 0.000303, 0.000343, 18699),
            (4, 0.000343, 0.002060, 0.000216, 0.001826, 1536017),
        ])
        self.assertFalse(ss.criterion_shakeout(with_sweep)["passed"])

    def test_shakeout_without_higher_low(self):
        candles = _candles([
            (1, 0.00040, 0.00048, 0.000395, 0.000482, 22781),
            (2, 0.000482, 0.000495, 0.000260, 0.000318, 30539),
            (3, 0.000318, 0.000375, 0.000200, 0.000343, 18699),
        ])
        self.assertFalse(ss.criterion_shakeout(candles)["passed"])

    def test_shakeout_needs_candles(self):
        self.assertIsNone(ss.criterion_shakeout([])["passed"])
        self.assertIsNone(ss.criterion_shakeout([[1, 1, 1, 1, 1, 1]])["passed"])


class EvaluateTest(unittest.TestCase):
    def _metrics(self, **over):
        metrics = {
            "liq_usd": LIQ_USD, "fdv_usd": MC_USD,
            "lp_locked_pct": 89.82, "mint_authority": None,
            "freeze_authority": None, "top10_holder_pct": 18.92,
            "holder_pcts": [2.99, 2.7, 2.11],
        }
        metrics.update(over)
        return metrics

    def test_eligible_when_structure_and_score_pass(self):
        snapshots = [
            {"ts": 1, "vol_1h": 3000, "buys_1h": 60, "sells_1h": 40,
             "price": 0.00025},
            {"ts": 2, "vol_1h": 9000, "buys_1h": 65, "sells_1h": 35,
             "price": 0.00026},
            {"ts": 3, "vol_1h": 30000, "buys_1h": 70, "sells_1h": 30,
             "price": 0.00027},
        ]
        candles = _candles([
            (1, 0.00040, 0.00048, 0.000395, 0.000482, 22781),
            (2, 0.000482, 0.000495, 0.000260, 0.000318, 30539),
            (3, 0.000318, 0.000375, 0.000303, 0.000343, 18699),
        ])
        result = ss.evaluate(self._metrics(), snapshots=snapshots,
                             candles=candles)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["verdict"], ss.VERDICT_LAYAK[0])
        self.assertEqual(result["passed_count"], 6)
        self.assertTrue(result["structural_ok"])
        self.assertFalse(result["missing"])
        # Dengan data lengkap ambangnya kembali ke 4 dari 6.
        self.assertEqual(result["required_count"], 4)

    def test_not_eligible_when_liq_mc_too_high(self):
        result = ss.evaluate(self._metrics(liq_usd=MC_USD * 0.5),
                             snapshots=[], candles=[])
        self.assertFalse(result["eligible"])
        self.assertFalse(result["structural_ok"])

    def test_missing_data_is_reported_not_punished(self):
        result = ss.evaluate(self._metrics(), snapshots=[], candles=[])
        self.assertIn("absorption", result["missing"])
        self.assertIn("vol_expansion", result["missing"])
        self.assertIn("shakeout", result["missing"])
        # 3 kriteria struktural lulus → skor 100% dari yang punya data
        self.assertEqual(result["scored_count"], 3)
        self.assertEqual(result["passed_count"], 3)
        self.assertAlmostEqual(result["score"], 1.0)
        # Ambangnya menyesuaikan: 4 dari 3 mustahil, jadi cukup trio struktural
        # (tanpa ini, deploy baru tidak akan pernah memberi alert kelayakan).
        self.assertEqual(result["required_count"], 3)
        self.assertTrue(result["eligible"])

    def test_targets_only_when_liq_mc_known(self):
        with_targets = ss.evaluate(self._metrics(), snapshots=[], candles=[])
        self.assertTrue(with_targets["targets"])
        without = ss.evaluate({"liq_usd": None, "fdv_usd": None},
                              snapshots=[], candles=[])
        self.assertEqual(without["targets"], [])


class DetectSweepTest(unittest.TestCase):
    def _series(self):
        # 24 candle tenang (volume ~150) lalu candle sweep 22:42 WIB.
        rows = [[1000 + i * 60, 0.0002377, 0.0002378, 0.0002375, 0.0002377, 150.0]
                for i in range(24)]
        rows.append([1000 + 24 * 60, 0.00023768309790897773, 0.0011562493069574252,
                     0.0002162336035266118, 0.0007667356548390803, 180744.30])
        return rows

    def test_detects_real_sweep_candle(self):
        event = ss.detect_sweep(self._series())
        self.assertIsNotNone(event)
        self.assertGreater(event["vol_x"], 1000)
        self.assertAlmostEqual(event["price_mult"], 0.0007667356548390803 /
                               0.0002377, places=3)
        self.assertEqual(event["bars_ago"], 0)

    def test_ignores_volume_spike_without_price(self):
        rows = self._series()
        rows[-1][4] = 0.0002377      # volume besar, harga tidak bergerak
        self.assertIsNone(ss.detect_sweep(rows))

    def test_ignores_flat_series(self):
        rows = [[1000 + i * 60, 0.001, 0.0011, 0.0009, 0.001, 100.0]
                for i in range(30)]
        self.assertIsNone(ss.detect_sweep(rows))

    def test_needs_minimum_candles(self):
        self.assertIsNone(ss.detect_sweep([]))
        self.assertIsNone(ss.detect_sweep([[1, 1, 1, 1, 1, 1]]))

    def test_sweep_context_applies_formula(self):
        event = ss.detect_sweep(self._series())
        context = ss.sweep_context(event, LIQ_USD / MC_USD, MC_USD,
                                   market_cap_usd=MC_USD)
        self.assertAlmostEqual(context["liq_mc"], LIQ_USD / MC_USD, places=5)
        self.assertGreater(context["churn_x"], 0)
        # Tanpa price_usd, MC diperlakukan sebagai MC di titik terendah →
        # paper MC = m x MC0 (bukan (m-1) x MC0 — itu bahan bakar hitung 2x).
        self.assertAlmostEqual(context["paper_mcap_usd"],
                               event["price_mult"] * MC_USD, places=1)
        self.assertAlmostEqual(context["base_mcap_usd"], MC_USD, places=1)
        # Biaya dorong minimum = (akar(m) - 1) x liq.
        self.assertAlmostEqual(
            context["est_cost_usd"],
            ((event["price_mult"] ** 0.5) - 1.0) * LIQ_USD, places=0)

    def test_biaya_dorong_cockroach_sesuai_angka_terkirim(self):
        # Angka riil 1 Okt: m = 3,2256, liq sebelum sweep $30.232 →
        # biaya dorong $24.067 (bukan net inflow $58.778 — itu inflow nyata).
        event = {"vol": 1242746.0, "base_price": 0.00023768,
                 "close": 0.00076673, "price_mult": 3.2256, "vol_x": 1190.0,
                 "bars_ago": 0, "peak": 0.00206033}
        context = ss.sweep_context(event, LIQ_USD / MC_USD, MC_USD,
                                   market_cap_usd=MC_USD, liq_usd=LIQ_USD)
        self.assertAlmostEqual(context["est_cost_usd"], 24067.0,
                               delta=24067.0 * 0.001)

    def test_paper_mcap_pakai_supply_dari_harga(self):
        # Snapshot post-sweep: harga sekarang = close candle → paper MC harus
        # ≈ MC snapshot, dan MC di titik terendah = MC/m.
        event = {"vol": 1242746.0, "base_price": 0.00023768,
                 "close": 0.00076673, "price_mult": 3.2256, "vol_x": 1190.0,
                 "bars_ago": 0, "peak": 0.00206033}
        mc_now, price_now, liq = 1790194.0, 0.00076673, 30232.0
        context = ss.sweep_context(event, liq / mc_now, None,
                                   market_cap_usd=mc_now, price_usd=price_now,
                                   liq_usd=liq)
        self.assertAlmostEqual(context["paper_mcap_usd"], mc_now,
                               delta=mc_now * 0.001)
        self.assertAlmostEqual(context["base_mcap_usd"], mc_now / 3.2256,
                               delta=mc_now * 0.001)

    def test_inflow_terukur_menang_atas_acuan(self):
        # Inflow nyata COCKROACH 1 Okt = $58.778 (2,44x biaya dorong) →
        # churn nyata 21,1x dan leverage 30,5x, persis angka yang terkirim.
        event = {"vol": 1242746.0, "base_price": 0.00023768,
                 "close": 0.00076673, "price_mult": 3.2256, "vol_x": 1190.0,
                 "bars_ago": 0}
        context = ss.sweep_context(event, 0.0, None,
                                   market_cap_usd=1790194.0,
                                   price_usd=0.00076673, liq_usd=30232.0,
                                   net_inflow_usd=58778.0)
        self.assertEqual(context["net_inflow_usd"], 58778.0)
        self.assertIsNone(context["net_inflow_ref_usd"])
        self.assertAlmostEqual(context["churn_net_x"],
                               1242746.0 / 58778.0, places=1)
        self.assertAlmostEqual(context["leverage_net"], 30.46, places=1)
        self.assertNotEqual(context["churn_x"], context["churn_net_x"])

    def test_acuan_dipakai_hanya_saat_belum_terukur(self):
        event = {"vol": 1000.0, "base_price": 1.0, "close": 1.6,
                 "price_mult": 1.6, "vol_x": 25.0, "bars_ago": 0}
        context = ss.sweep_context(event, None, None, market_cap_usd=100000.0,
                                   price_usd=1.6, liq_usd=1000.0)
        self.assertIsNone(context["net_inflow_usd"])
        self.assertIsNone(context["churn_net_x"])
        self.assertAlmostEqual(context["net_inflow_ref_usd"],
                               context["est_cost_usd"] * ss.REF_NET_COST_MULT,
                               places=2)

    def test_inflow_nol_atau_negatif_tidak_dipakai(self):
        event = {"vol": 1000.0, "base_price": 1.0, "close": 1.6,
                 "price_mult": 1.6, "vol_x": 25.0, "bars_ago": 0}
        for value in (0.0, -500.0):
            context = ss.sweep_context(event, None, None,
                                       market_cap_usd=100000.0,
                                       price_usd=1.6, liq_usd=1000.0,
                                       net_inflow_usd=value)
            self.assertIsNone(context["churn_net_x"])


class StatisticsTest(unittest.TestCase):
    def test_summarize_signals(self):
        signals = [
            {"id": "a", "max_up_pct": 950.0, "max_down_pct": -31.0,
             "churn_x": 51.6, "churn_net_x": 21.1},
            {"id": "b", "max_up_pct": 55.0, "max_down_pct": -40.0,
             "churn_x": 8.0},
            {"id": "c", "max_up_pct": 420.0, "max_down_pct": -12.0,
             "churn_x": 13.0},
        ]
        stats = ss.summarize_signals(signals)
        self.assertEqual(stats["n"], 3)
        self.assertEqual(stats["n_win_100"], 2)
        self.assertEqual(stats["n_win_300"], 2)
        self.assertAlmostEqual(stats["hit_rate_100"], 2 / 3)
        self.assertAlmostEqual(stats["median_up"], 420.0)
        self.assertAlmostEqual(stats["median_down"], -31.0)
        self.assertAlmostEqual(stats["worst_down"], -40.0)
        self.assertAlmostEqual(stats["median_churn"], 13.0)

    def test_summarize_handles_empty(self):
        stats = ss.summarize_signals([])
        self.assertEqual(stats["n"], 0)
        self.assertIsNone(stats["hit_rate_100"])
        self.assertIsNone(stats["median_up"])

    def test_breakeven_hit_rate(self):
        # menang +200% / kalah -30% → 13,0%
        self.assertAlmostEqual(ss.breakeven_hit_rate(200.0, 30.0), 30 / 230, places=5)
        self.assertAlmostEqual(ss.breakeven_hit_rate(500.0, 40.0), 40 / 540, places=5)
        self.assertIsNone(ss.breakeven_hit_rate(0, 30))


if __name__ == "__main__":
    unittest.main()
