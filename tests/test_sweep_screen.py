# -*- coding: utf-8 -*-
"""Mesin skrining kelayakan sweep (:mod:`sweep_screen`).

Semua angka di sini berasal dari kasus nyata COCKROACH (``H4KUxs…nyJc``)
1 Okt 2026, jadi test mengunci **hasil verifikasi**, bukan sekadar bentuk
fungsi:

- rumus ``(akar(m)-1) x liq/MC`` direproduksi pada angka aktual
  (``(akar(8,67)-1) x 12,95% / 2 = 12,6%`` = uang quote masuk, cocok dengan
  biaya acuan COCKROACH; Δ TVL dua sisi ``$58.778`` = 2× uang masuk);
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
CLOSE = 0.0007667356548390803         # harga penutupan candle sweep (22:42)
LIQ_USD = 30232.0                     # reserve quote sebelum sweep
MC_USD = 233451.0                     # market cap sebelum sweep
NET_INFLOW = 58778.0                  # Δ TVL dua sisi hasil rekonstruksi reserve
NET_INFLOW_MONEY = NET_INFLOW / 2.0    # uang quote yang benar-benar masuk (Δ TVL / 2)
PAPER_GAIN = 1790194.0                # kenaikan MC kertas sampai puncak
PAPER_MCAP_CLOSE = 752939.0           # paper MC di close (besaran berbeda)
SUPPLY = 982_000_000                  # supply token (standar pump.fun)

# Turunan dari angka di atas
PEAK_MULT = PEAK / BASE_PRICE          # 8,669x
PRICE_MULT = CLOSE / BASE_PRICE        # 3,226x
EST_COST_PEAK = (PEAK_MULT ** 0.5 - 1.0) * LIQ_USD / 2.0   # ≈ 29.389 (uang masuk)
EST_COST_CLOSE = (PRICE_MULT ** 0.5 - 1.0) * LIQ_USD / 2.0  # ≈ 12.033
LEVERAGE = (PEAK_MULT ** 0.5 + 1.0) / (LIQ_USD / MC_USD / 2.0)  # ≈ 60,9x


def _candles(rows):
    """``[(ts, o, h, l, c, v), …]`` → list of list."""
    return [list(r) for r in rows]


def _birth_candles(created=1000, *, low=0.9, high=1.1, price=1.0):
    """48 hourly bars with unit volume and VWAP 1.0 for cohort-gate tests."""
    return [[created + hour * 3600, price, high, low, price, 100.0]
            for hour in range(48)]


class LeverageFormulaTest(unittest.TestCase):
    def test_cost_matches_cockroach_actual_peak(self):
        """Biaya dorong ke PUNCAK = uang quote masuk ≈ $29.389 (Δ TVL / 2)."""
        liq_mc = LIQ_USD / MC_USD
        frac = ss.leverage_cost(PEAK_MULT, liq_mc)
        self.assertAlmostEqual(frac, NET_INFLOW_MONEY / MC_USD, places=3)
        self.assertAlmostEqual(frac * MC_USD, NET_INFLOW_MONEY, delta=60.0)

    def test_cost_matches_cockroach_actual_formula(self):
        """est_cost_usd = (akar(peak_mult) - 1) × liq / 2 ≈ $29.389."""
        self.assertAlmostEqual(EST_COST_PEAK, NET_INFLOW_MONEY, delta=100.0)

    def test_ratio_matches_cockroach_actual(self):
        """leverage = paper gain / uang quote masuk ≈ 60,9x (basis setengah)."""
        liq_mc = LIQ_USD / MC_USD
        ratio = ss.leverage_ratio(PEAK_MULT, liq_mc)
        self.assertAlmostEqual(ratio, PAPER_GAIN / NET_INFLOW_MONEY, places=1)

    def test_cost_to_close_is_less_than_cost_to_peak(self):
        """est_cost_close_usd ≈ $12.033, beda > 2× dari biaya ke puncak."""
        self.assertGreater(EST_COST_PEAK / EST_COST_CLOSE, 2.0)
        self.assertAlmostEqual(EST_COST_CLOSE, 12033.5, delta=12033.5 * 0.001)

    def test_smaller_liq_mc_is_cheaper(self):
        cheap = ss.leverage_cost(10.0, 0.02)
        pricey = ss.leverage_cost(10.0, 0.30)
        self.assertLess(cheap, pricey)
        # liq/MC 5% → 5,41% MC untuk naik 10x; 30% → 32,43% MC (basis setengah).
        self.assertAlmostEqual(ss.leverage_cost(10.0, 0.05) * 100, 5.41, places=2)
        self.assertAlmostEqual(ss.leverage_cost(10.0, 0.30) * 100, 32.43, places=2)

    def test_invalid_input_returns_none(self):
        self.assertIsNone(ss.leverage_cost(None, 0.1))
        self.assertIsNone(ss.leverage_cost(5.0, 0))
        self.assertIsNone(ss.leverage_cost(-5.0, 0.1))
        self.assertIsNone(ss.leverage_ratio("x", 0.1))

    def test_target_costs_feasibility(self):
        rows = ss.target_costs(0.02, mults=(10.0,))
        self.assertTrue(rows[0]["feasible"])
        # 50x di liq/MC 60% → (√50−1) × 30% = 182% MC > 100%: tidak feasible.
        rows = ss.target_costs(0.60, mults=(50.0,))
        self.assertFalse(rows[0]["feasible"])


class CriteriaTest(unittest.TestCase):
    def test_token_mc_threshold_is_fixed_at_17_5_percent_inclusive(self):
        # Keputusan 2026-10-14: float tipis diukur dari sisi token pool.
        self.assertEqual(ss.TOKEN_MC_MAX, 0.175)
        self.assertTrue(ss.criterion_token_mc(100.0, 1000.0)["passed"])
        self.assertTrue(ss.criterion_token_mc(175.0, 1000.0)["passed"])
        self.assertFalse(ss.criterion_token_mc(176.0, 1000.0)["passed"])
        # Snapshot lama tanpa pool_base_usd = belum ada data, bukan tebakan.
        self.assertIsNone(ss.criterion_token_mc(None, 1000.0)["passed"])
        self.assertIsNone(ss.criterion_token_mc(100.0, None)["passed"])

    def test_authority_gate_requires_closed_authority_and_is_not_scored(self):
        ok = ss.criterion_authority(None, None)
        self.assertTrue(ok["passed"])
        self.assertFalse(ok["scored"])
        self.assertFalse(ss.criterion_authority("SomeAuthority111", None)["passed"])
        self.assertFalse(ss.criterion_authority(None, "FreezeAuth111")["passed"])
        self.assertIsNone(ss.criterion_authority(None, None, known=False)["passed"])

    def test_float_spread_uses_percent_input(self):
        # 18,92% top-10 + holder terbesar 3,00% → LULUS (batas default 5%)
        self.assertTrue(
            ss.criterion_float_spread(18.92, [3.0, 2.7, 2.11])["passed"])
        # holder terbesar 2,99% → tetap LULUS
        self.assertTrue(
            ss.criterion_float_spread(18.92, [2.99, 2.7, 2.11])["passed"])
        # Terkonsentrasi (holder 12%) → gagal
        self.assertFalse(ss.criterion_float_spread(40.0, [12.0])["passed"])
        # Holder/wallet maksimum tetap 5%, dan tepat 5% masih diterima.
        self.assertTrue(ss.criterion_float_spread(18.0, [5.0])["passed"])
        self.assertFalse(ss.criterion_float_spread(18.0, [5.5])["passed"])
        self.assertIsNone(ss.criterion_float_spread(None, [])["passed"])

    def test_holder_threshold_is_fixed_at_five_percent(self):
        self.assertEqual(ss.HOLDER_MAX_PCT, 5.0)
        self.assertIn("lolos batas holder 5%",
                      ss.criterion_float_spread(18.97, [3.94])["detail"])

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


class FixedThresholdTest(unittest.TestCase):
    def test_evaluate_uses_fixed_thresholds_without_overrides(self):
        self.assertEqual(ss.TOKEN_MC_MAX, 0.175)
        self.assertEqual(ss.HOLDER_MAX_PCT, 5.0)
        metrics = {
            "liq_usd": 350.0, "fdv_usd": 1000.0, "pool_base_usd": 175.0,
            "mint_authority": None, "freeze_authority": None,
            "top10_holder_pct": 18.0, "holder_pcts": [5.0],
        }
        result = ss.evaluate(metrics)
        checks = {row["key"]: row for row in result["checks"]}
        self.assertTrue(checks["token_mc"]["passed"])
        self.assertTrue(checks["float_spread"]["passed"])
        metrics["pool_base_usd"] = 176.0
        self.assertFalse({row["key"]: row for row in
                          ss.evaluate(metrics)["checks"]}["token_mc"]["passed"])

class EvaluateTest(unittest.TestCase):
    def _metrics(self, **over):
        metrics = {
            "mint": "M", "price_usd": 0.29, "pair_created_at": 1000,
            "holder_min_avg_cost": 0.2,  # jarak 31% < 50% → gate holder lolos
            # avg buy GMGN tertimbang 2,0 → status GMGN ≈ −85% (kohort C lolos)
            "holder_cost_basis": 2.0, "holder_cost_balance": 1.0,
            "liq_usd": LIQ_USD, "fdv_usd": MC_USD,
            # Token pool 10% MC (di bawah batas 17,5%).
            "pool_base_usd": MC_USD * 0.10,
            "mint_authority": None,
            "freeze_authority": None, "top10_holder_pct": 18.92,
            "holder_pcts": [2.99, 2.7, 2.11],
        }
        metrics.update(over)
        return metrics

    def test_lp_locked_is_not_checked_or_scored(self):
        result = ss.evaluate(self._metrics(), snapshots=[], candles=[])
        keys = [c["key"] for c in result["checks"]]
        self.assertNotIn("lp_locked", keys)
        self.assertNotIn("lp_locked", result["missing"])
        self.assertIn("authority", keys)
        self.assertEqual(result["scored_count"], 2)
        self.assertTrue(result["structural_ok"])

    def test_open_or_unknown_authority_blocks_structure(self):
        open_mint = ss.evaluate(self._metrics(mint_authority="MintAuth111"),
                                snapshots=[], candles=[])
        self.assertFalse(open_mint["structural_ok"])
        unknown = ss.evaluate(self._metrics(rugcheck_ok=False),
                              snapshots=[], candles=[])
        self.assertFalse(unknown["structural_ok"])

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
                             candles=candles, cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["verdict"], ss.VERDICT_LAYAK[0])
        self.assertEqual(result["passed_count"], 5)
        self.assertTrue(result["structural_ok"])
        self.assertFalse(result["missing"])
        # Dengan data lengkap ambangnya kembali ke 4 dari 6.
        self.assertEqual(result["required_count"], 4)

    def test_not_eligible_when_token_mc_too_high(self):
        result = ss.evaluate(self._metrics(pool_base_usd=MC_USD * 0.25),
                             snapshots=[], candles=[])
        self.assertFalse(result["eligible"])
        self.assertFalse(result["structural_ok"])

    def test_missing_data_is_reported_not_punished(self):
        result = ss.evaluate(self._metrics(), snapshots=[], candles=[])
        self.assertIn("absorption", result["missing"])
        self.assertIn("vol_expansion", result["missing"])
        self.assertIn("shakeout", result["missing"])
        # 2 kriteria skor yang punya data (token/MC, float) lulus → skor 100%
        # (authority adalah gate, tidak dihitung skor).
        self.assertEqual(result["scored_count"], 2)
        self.assertEqual(result["passed_count"], 2)
        self.assertAlmostEqual(result["score"], 1.0)
        # Tanpa OHLCV kelahiran gate kohort tetap menahan kandidat.
        self.assertEqual(result["required_count"], 2)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["verdict"], "TANPA DATA — kohort")
        self.assertEqual(result["cohort_gate_status"], "TANPA DATA — kohort")

    def test_evaluate_preserves_shakeout_latch_after_sweep_breaks_low(self):
        candles = _candles([
            (1, 0.00040, 0.00048, 0.000395, 0.000482, 22781),
            (2, 0.000482, 0.000495, 0.000260, 0.000318, 30539),
            (3, 0.000318, 0.000375, 0.000303, 0.000343, 18699),
            (4, 0.000343, 0.002060, 0.000216, 0.001826, 1536017),
        ])
        # Tanpa latch, pola dinilai gagal kembali di candle yang menyapu low.
        self.assertFalse(ss.criterion_shakeout(candles)["passed"])
        result = ss.evaluate(self._metrics(), candles=candles,
                             state={"shakeout_latched_at": {"M": 2}}, mint="M")
        shakeout = next(c for c in result["checks"] if c["key"] == "shakeout")
        self.assertTrue(shakeout["passed"])
        self.assertIn("latch permanen", shakeout["detail"])

    def test_cohort_gate_plus_wait_and_minus_50(self):
        candles = _birth_candles()
        now = 1000 + 49 * 3600

        plus = ss.evaluate(self._metrics(price_usd=1.05),
                           cohort_candles=candles, now=now)
        self.assertEqual(plus["cohort_gate_status"], "SKIP — kohort plus")
        self.assertFalse(plus["eligible"])

        # VWAP kelahiran ≈ 1,0: harga 0,52 = minus ~48% → belum lolos.
        minus_48 = ss.evaluate(self._metrics(price_usd=0.52),
                               cohort_candles=candles, now=now)
        self.assertEqual(minus_48["cohort_gate_status"],
                         "TUNGGU — kohort belum minus 50%")
        self.assertFalse(minus_48["eligible"])

        # harga 0,49 = minus ~51% → lolos gate kohort.
        minus_51 = ss.evaluate(self._metrics(price_usd=0.49),
                               cohort_candles=candles, now=now)
        self.assertEqual(minus_51["cohort_gate_status"], "LOLOS")
        self.assertTrue(minus_51["cohort_gate_passed"])

    def test_gmgn_avg_cost_must_also_be_minus_50(self):
        candles = _birth_candles()
        now = 1000 + 49 * 3600
        # VWAP minus 51% lolos; avg buy GMGN 0,8 → harga 0,49 = minus ~39%.
        below = ss.evaluate(self._metrics(price_usd=0.49, holder_cost_basis=0.8,
                                          holder_cost_balance=1.0),
                            cohort_candles=candles, now=now)
        self.assertEqual(below["cohort_gate_status"],
                         "TUNGGU — kohort GMGN belum minus 50%")
        self.assertFalse(below["cohort_gate_passed"])
        self.assertFalse(below["eligible"])
        self.assertTrue(below["verdict"].startswith("TUNGGU — kohort GMGN"))
        self.assertAlmostEqual(below["gmgn_status_avg_cost"], 0.49 / 0.8 - 1)

    def test_gmgn_avg_cost_plus_waits(self):
        result = ss.evaluate(self._metrics(price_usd=0.49, holder_cost_basis=0.3,
                                           holder_cost_balance=1.0),
                             cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertEqual(result["cohort_gate_status"], "TUNGGU — kohort GMGN plus")
        self.assertFalse(result["eligible"])

    def test_missing_gmgn_holder_data_is_tanpa_data_kohort_gmgn(self):
        # avg buy holder terendah 0,4 → jarak 18% < 50%, gate holder lolos.
        result = ss.evaluate(self._metrics(price_usd=0.49, holder_cost_basis=None,
                                           holder_cost_balance=None,
                                           holder_min_avg_cost=0.4),
                             cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertTrue(result["cohort"]["available"])
        self.assertEqual(result["cohort_gate_status"], "TANPA DATA — kohort GMGN")
        self.assertIsNone(result["gmgn_status_avg_cost"])
        self.assertFalse(result["eligible"])
        self.assertEqual(result["color"], "#64748b")

    def test_gmgn_status_formula(self):
        # 1.000 saldo @ avg 0,5 → harga 0,25 = minus 50% tepat.
        self.assertAlmostEqual(ss.gmgn_cohort_status(500.0, 1000.0, 0.25), -0.5)
        self.assertIsNone(ss.gmgn_cohort_status(None, 1000.0, 0.25))
        self.assertIsNone(ss.gmgn_cohort_status(0.0, 0.0, 0.25))
        self.assertIsNone(ss.gmgn_cohort_status(500.0, 1000.0, None))

    def test_display_sort_plus_last_and_closest_to_eligible_first(self):
        def row(status, verdict="TIDAK LAYAK", passed=1, avg=None, gate=False):
            return {"cohort_gate_status": status, "verdict": verdict,
                    "passed_count": passed, "cohort_gate_passed": gate,
                    "cohort": {"status_avg_cost": avg}}

        def scored(status, passed, scored_n, **kw):
            item = row(status, passed=passed, **kw)
            item["score"] = passed / scored_n
            return item

        def with_ref(item, x):
            item["reference_fund_x"] = x
            return item

        rows = {
            "plus": with_ref(scored("SKIP — kohort plus", 6, 6, avg=0.2), 1.0),
            "missing": {"cohort_gate_status": "MENUNGGU SNAPSHOT",
                        "passed_count": None, "score": None},
            "far": with_ref(scored("TUNGGU — kohort belum minus 50%", 3, 6,
                                   avg=-0.10), 2.0),
            "near": with_ref(scored("TUNGGU — kohort belum minus 50%", 3, 6,
                                    avg=-0.45), 0.9),
            "kandidat": with_ref(scored("LOLOS", 2, 3, verdict="KANDIDAT",
                                        avg=-0.6, gate=True), 1.2),
            "nodata": with_ref(scored("TANPA DATA — kohort", 5, 6), 1.15),
            "layak": with_ref(scored("LOLOS", 4, 4, verdict="LAYAK SWEEP",
                                     avg=-0.6, gate=True), 0.5),
            # Tanpa reference_fund_x: dihitung ulang dari liq/MC COCK (≈1,0×).
            "cock": {**scored("TUNGGU — kohort belum minus 50%", 1, 6, avg=-0.2),
                     "liq_mc": 30232.0 / 233451.0},
        }
        order = sorted(rows, key=lambda k: ss.display_sort_key(rows[k]))
        # Blok kandidat dulu (KANDIDAT 0,2 > LAYAK 0,5 menurut jarak ke acuan 1,0×),
        # lalu jarak ke acuan dana 10x: cock ≈0 > near 0,1 > nodata 0,15 > far 1,0;
        # baris tanpa acuan; PLUS paling bawah.
        self.assertEqual(order, ["kandidat", "layak", "cock", "near", "nodata",
                                 "far", "missing", "plus"])

    def test_cohort_no_data_never_passes_gate_and_partial_window_is_labeled(self):
        no_data = ss.evaluate(self._metrics(), cohort_candles=[])
        self.assertEqual(no_data["cohort_gate_status"], "TANPA DATA — kohort")
        self.assertFalse(no_data["eligible"])
        partial = ss.cohort_profile(_birth_candles()[:12], 1000, 0.29,
                                    now=1000 + 12 * 3600)
        self.assertTrue(partial["available"])
        self.assertTrue(partial["partial_window"])
        self.assertLessEqual(partial["status_avg_cost"], -0.50)

    def test_turnover_and_cock_reference_multiple(self):
        metrics = self._metrics(vol24_usd=30232.0 * 3.35)
        result = ss.evaluate(metrics, cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertAlmostEqual(result["turnover_x"], 3.35, places=6)
        self.assertAlmostEqual(result["reference_fund_x"], 1.0, places=2)

    def test_targets_only_when_liq_mc_known(self):
        with_targets = ss.evaluate(self._metrics(), snapshots=[], candles=[])
        self.assertTrue(with_targets["targets"])
        without = ss.evaluate({"liq_usd": None, "fdv_usd": None},
                              snapshots=[], candles=[])
        self.assertEqual(without["targets"], [])


class CostGateTest(unittest.TestCase):
    """Gate biaya 10x: biaya ≤ 28% MC; di atas itu atau tanpa data = TUNGGU."""

    def test_limit_is_fixed_at_28_percent_of_mc_for_10x(self):
        # 2× acuan dana COCK 10x (14,0% MC), keputusan user 2026-10-14.
        self.assertEqual(ss.COST_GATE_MULT, 10.0)
        self.assertEqual(ss.COST_GATE_MAX_FRAC, 0.28)

    def test_boundary_uses_liq_mc_near_25_9_percent(self):
        # (√10 − 1)/2 = 1,0811 → batas 28% dicapai di liq/MC ≈ 25,90%.
        self.assertTrue(ss.cost_gate(ss.leverage_cost(10.0, 0.2589))["passed"])
        self.assertFalse(ss.cost_gate(ss.leverage_cost(10.0, 0.2591))["passed"])
        self.assertTrue(ss.cost_gate(0.28)["passed"])  # tepat 28% lolos
        self.assertFalse(ss.cost_gate(0.2801)["passed"])

    def test_missing_cost_is_not_passed(self):
        gate = ss.cost_gate(None)
        self.assertFalse(gate["passed"])
        self.assertTrue(gate["status"].startswith("TUNGGU"))
        self.assertIn("belum ada data", gate["status"])

    def test_cockroach_reference_passes(self):
        # COCK liq/MC 12,95% → biaya 10x = 14,0% MC, di bawah batas 28% (2× acuan).
        gate = ss.cost_gate(ss.leverage_cost(10.0, 0.1295))
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["status"], "LOLOS")


class CostUsdTest(unittest.TestCase):
    def test_usd_equals_cost_frac_times_market_cap(self):
        liq, mc = 30232.0, 233451.0
        targets = ss.target_costs(liq / mc, liq_usd=liq)
        ten_x = next(t for t in targets if t["mult"] == 10.0)
        self.assertAlmostEqual(ten_x["cost_usd"], (10 ** 0.5 - 1) * liq / 2, places=6)
        self.assertAlmostEqual(ten_x["cost_usd"], ten_x["cost_frac"] * mc, places=4)

    def test_usd_absent_without_liq_usd(self):
        targets = ss.target_costs(0.1295)
        self.assertTrue(all(t["cost_usd"] is None for t in targets))

    def test_reference_fund_usd_matches_cockroach_10x(self):
        # Acuan dana = biaya 10x COCK = (√10−1) × cash $15.116 ≈ $32.684 (14,0% MC).
        metrics = {"liq_usd": 30232.0, "fdv_usd": 233451.0}
        result = ss.evaluate(metrics, snapshots=[], candles=[])
        self.assertAlmostEqual(result["reference_fund_usd"], 32684, delta=1)
        self.assertAlmostEqual(result["reference_fund_usd"],
                               result["reference_fund_x"] * 32684, delta=1)

    def test_cockroach_10x_reference_constants(self):
        self.assertEqual(ss.REFERENCE_MULT, 10.0)
        self.assertAlmostEqual(ss.COCK_REFERENCE_COST_10X_USD, 32684, delta=1)
        self.assertAlmostEqual(ss.COCK_REFERENCE_COST_10X_MC_FRAC, 0.1400, places=4)
        # Biaya 10x pada liq/MC COCK 12,95% = acuan persis (1,0×).
        self.assertAlmostEqual(ss.reference_fund_multiple(30232.0 / 233451.0), 1.0,
                               places=3)


class CostGateEvaluateTest(unittest.TestCase):
    def _metrics(self, **over):
        metrics = {"mint": "M", "price_usd": 0.49, "pair_created_at": 1000,
                   "holder_cost_basis": 2.0, "holder_cost_balance": 1.0,
                   "liq_usd": MC_USD * 0.35, "fdv_usd": MC_USD,
                   "mint_authority": None, "freeze_authority": None,
                   "top10_holder_pct": 18.92, "holder_pcts": [2.99, 2.7]}
        metrics.update(over)
        return metrics

    def test_cost_over_28_percent_turns_verdict_to_tunggu_even_if_cohort_passes(self):
        # liq/MC 80% → biaya 10x ≈ 86,5% MC > 28%.
        result = ss.evaluate(self._metrics(liq_usd=MC_USD * 0.80), snapshots=[], candles=[],
                             cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertTrue(result["cohort_gate_passed"])
        self.assertFalse(result["cost_gate_passed"])
        self.assertFalse(result["eligible"])
        self.assertTrue(result["verdict"].startswith("TUNGGU — biaya 10x"))
        self.assertIn("batas 28%", result["verdict"])
        self.assertGreater(result["cost_10x_mc_frac"], 0.28)

    def test_liq_mc_at_old_structural_max_now_fails_cost_gate(self):
        # liq/MC 35% → biaya 10x ≈ 37,8% MC > 28%: kriteria token/MC tidak
        # membatasi sisi quote, jadi gate biaya yang menahan.
        result = ss.evaluate(self._metrics(), snapshots=[], candles=[],
                             cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertFalse(result["cost_gate_passed"])
        self.assertTrue(result["verdict"].startswith("TUNGGU — biaya 10x"))

    def test_liq_mc_at_cockroach_reference_passes_cost_gate(self):
        # liq/MC COCK 12,95% → biaya 10x 14,0% MC ≤ 28%.
        result = ss.evaluate(self._metrics(liq_usd=30232.0), snapshots=[], candles=[],
                             cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertTrue(result["cost_gate_passed"])

    def test_missing_liq_mc_is_tunggu_not_eligible(self):
        result = ss.evaluate({"liq_usd": None, "fdv_usd": None,
                              "price_usd": 0.49, "pair_created_at": 1000,
                              "holder_cost_basis": 2.0,
                              "holder_cost_balance": 1.0},
                             snapshots=[], candles=[],
                             cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertFalse(result["cost_gate_passed"])
        self.assertFalse(result["eligible"])
        self.assertTrue(result["verdict"].startswith("TUNGGU"))

    def test_cohort_gate_still_wins_when_it_fails(self):
        # harga 0,52 = minus ~48% → kohort belum lolos, biaya tidak relevan.
        result = ss.evaluate(self._metrics(price_usd=0.52),
                             cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertEqual(result["cohort_gate_status"],
                         "TUNGGU — kohort belum minus 50%")
        self.assertEqual(result["verdict"], result["cohort_gate_status"])

    def test_cost_gate_does_not_break_stored_view_keys(self):
        import sweep_store
        for key in ("cost_10x_mc_frac", "cost_gate_status", "cost_gate_passed",
                    "cost_gate_detail", "reference_fund_usd"):
            self.assertIn(key, sweep_store.VIEW_RESULT_KEYS)


class HolderCostGateTest(unittest.TestCase):
    """Gate avg buy holder: avg buy terendah tidak boleh > 50% di bawah harga."""

    def test_rari_case_is_tunggu(self):
        # RARI 2026-10-13: avg buy terendah ~7,07e-5 (TOP31), harga ~7,0e-4.
        gate = ss.holder_cost_gate(7.07e-5, 7.0e-4)
        self.assertFalse(gate["passed"])
        self.assertGreater(gate["gap"], 0.5)
        self.assertTrue(gate["status"].startswith("TUNGGU — avg buy holder"))
        self.assertIn("90%", gate["status"])

    def test_exactly_half_of_price_passes(self):
        gate = ss.holder_cost_gate(0.5, 1.0)
        self.assertTrue(gate["passed"])
        self.assertAlmostEqual(gate["gap"], 0.5)
        self.assertEqual(gate["status"], "LOLOS")

    def test_just_below_half_is_tunggu(self):
        self.assertFalse(ss.holder_cost_gate(0.499, 1.0)["passed"])

    def test_holder_above_price_passes(self):
        gate = ss.holder_cost_gate(1.2, 1.0)
        self.assertTrue(gate["passed"])
        self.assertLess(gate["gap"], 0)

    def test_missing_data_is_tunggu_without_data(self):
        for avg, price in ((None, 1.0), (0.5, None), (0, 1.0), (0.5, 0)):
            gate = ss.holder_cost_gate(avg, price)
            self.assertFalse(gate["passed"], (avg, price))
            self.assertIsNone(gate["gap"])
            self.assertIn("belum ada data", gate["status"])


class HolderCostGateEvaluateTest(unittest.TestCase):
    def _metrics(self, **over):
        # liq/MC 10% → biaya 10x ≈ 21,6% MC, jadi gate biaya tidak ikut kalah.
        metrics = {"mint": "M", "price_usd": 0.49, "pair_created_at": 1000,
                   "holder_cost_basis": 2.0, "holder_cost_balance": 1.0,
                   "liq_usd": MC_USD * 0.1, "fdv_usd": MC_USD,
                   "mint_authority": None, "freeze_authority": None,
                   "top10_holder_pct": 18.92, "holder_pcts": [2.99, 2.7]}
        metrics.update(over)
        return metrics

    def _run(self, **over):
        return ss.evaluate(self._metrics(**over), snapshots=[], candles=[],
                           cohort_candles=_birth_candles(),
                           now=1000 + 49 * 3600)

    def test_low_holder_avg_cost_turns_verdict_to_tunggu(self):
        result = self._run(holder_min_avg_cost=0.1)
        self.assertTrue(result["cohort_gate_passed"])
        self.assertTrue(result["cost_gate_passed"])
        self.assertFalse(result["holder_gate_passed"])
        self.assertFalse(result["eligible"])
        self.assertTrue(result["verdict"].startswith("TUNGGU — avg buy holder"))
        self.assertAlmostEqual(result["holder_min_avg_cost"], 0.1)
        self.assertAlmostEqual(result["holder_gap"], 1 - 0.1 / 0.49)

    def test_holder_avg_cost_within_50_percent_does_not_block(self):
        result = self._run(holder_min_avg_cost=0.3)
        self.assertTrue(result["holder_gate_passed"])
        self.assertFalse(result["verdict"].startswith("TUNGGU — avg buy"))

    def test_missing_holder_data_is_tunggu(self):
        result = self._run()
        self.assertFalse(result["holder_gate_passed"])
        self.assertFalse(result["eligible"])
        self.assertTrue(result["verdict"].startswith("TUNGGU — avg buy holder belum"))

    def test_holder_wait_shows_even_when_cohort_data_missing(self):
        result = ss.evaluate(self._metrics(holder_min_avg_cost=0.1),
                             snapshots=[], candles=[], cohort_candles=None,
                             now=1000 + 49 * 3600)
        self.assertEqual(result["cohort_gate_status"], "TANPA DATA — kohort")
        self.assertFalse(result["holder_gate_passed"])
        self.assertFalse(result["eligible"])
        self.assertTrue(result["verdict"].startswith("TUNGGU — avg buy holder"))
        self.assertEqual(result["color"], "#b45309")

    def test_missing_holder_data_keeps_cohort_tanpa_data_verdict(self):
        result = ss.evaluate(self._metrics(), snapshots=[], candles=[],
                             cohort_candles=None, now=1000 + 49 * 3600)
        self.assertEqual(result["verdict"], "TANPA DATA — kohort")
        self.assertEqual(result["color"], "#64748b")

    def test_cost_gate_still_wins_over_holder_gate(self):
        result = ss.evaluate(self._metrics(liq_usd=MC_USD * 0.80,
                                           holder_min_avg_cost=0.1),
                             snapshots=[], candles=[],
                             cohort_candles=_birth_candles(),
                             now=1000 + 49 * 3600)
        self.assertFalse(result["cost_gate_passed"])
        self.assertTrue(result["verdict"].startswith("TUNGGU — biaya 10x"))


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

    def test_sweep_context_uses_peak_not_close(self):
        """Biaya ke puncak pakai peak_mult, bukan price_mult."""
        # Gunakan synthetic event dengan peak riil (bukan dari detect_sweep
        # yang menggunakan high dari test series = 0.00115625)
        event = {
            "vol": 1242746.0, "base_price": BASE_PRICE,
            "close": CLOSE, "peak": PEAK,
            "price_mult": PRICE_MULT, "vol_x": 1190.0,
            "bars_ago": 0,
        }
        # MC di harga dasar = supply × base_price = 982jt × 0.00023768 ≈ 233.451
        mc_base = SUPPLY * BASE_PRICE
        context = ss.sweep_context(event, LIQ_USD / mc_base, None,
                                   market_cap_usd=mc_base)
        # peak_mult harus ≈ 8,669 (bukan 3,226 dari price_mult)
        self.assertAlmostEqual(context["peak_mult"], PEAK_MULT, places=1)
        # est_cost_usd pakai peak_mult → ≈ $29.389 (uang masuk)
        self.assertAlmostEqual(
            context["est_cost_usd"],
            EST_COST_PEAK,
            delta=100.0)
        # est_cost_close_usd pakai price_mult → ≈ $24.067
        self.assertAlmostEqual(
            context["est_cost_close_usd"],
            EST_COST_CLOSE,
            delta=100.0)
        # Beda harus > 2×
        self.assertGreater(
            context["est_cost_usd"] / context["est_cost_close_usd"], 2.0)

    def test_paper_gain_vs_paper_mcap_are_different(self):
        """paper_gain_usd ≈ $1.79 juta, paper_mcap_usd ≈ $752rb (berbeda)."""
        event = {"vol": 1242746.0, "base_price": BASE_PRICE,
                 "close": CLOSE, "peak": PEAK,
                 "price_mult": PRICE_MULT, "vol_x": 1190.0,
                 "bars_ago": 0}
        # supply = 982jt → market_cap di close = 982jt × close ≈ 752.939
        mc_at_close = SUPPLY * CLOSE
        context = ss.sweep_context(event, LIQ_USD / mc_at_close, None,
                                   market_cap_usd=mc_at_close,
                                   price_usd=CLOSE, liq_usd=LIQ_USD)
        # paper_gain = supply × (peak - base) ≈ $1.79 juta
        self.assertAlmostEqual(context["paper_gain_usd"], PAPER_GAIN, delta=PAPER_GAIN * 0.01)
        # paper_mcap = supply × close ≈ $752.939
        self.assertAlmostEqual(context["paper_mcap_usd"], PAPER_MCAP_CLOSE, delta=PAPER_MCAP_CLOSE * 0.01)
        # Dua besaran harus berbeda (bukan sama)
        self.assertNotAlmostEqual(context["paper_gain_usd"],
                                  context["paper_mcap_usd"],
                                  places=0)

    def test_leverage_uses_peak_mult(self):
        """leverage ≈ 30,5x di tiga jalur: leverage(), leverage_net, dan manual."""
        event = {"vol": 1242746.0, "base_price": BASE_PRICE,
                 "close": CLOSE, "peak": PEAK,
                 "price_mult": PRICE_MULT, "vol_x": 1190.0,
                 "bars_ago": 0}
        # supply = 982jt → market_cap di close = 982jt × close ≈ 752.939
        mc_at_close = SUPPLY * CLOSE
        # liq/MC = 12.95% (nilai COCKROACH riil), bukan liq_usd/mc_at_close
        # karena mc_at_close berbeda dari mc_base
        liq_mc = LIQ_USD / (SUPPLY * BASE_PRICE)  # 30232 / 233451 ≈ 0.1295
        context = ss.sweep_context(event, liq_mc, None,
                                   market_cap_usd=mc_at_close,
                                   price_usd=CLOSE, liq_usd=LIQ_USD,
                                   net_inflow_usd=NET_INFLOW)

        # Jalur 1: leverage() dengan peak_mult
        self.assertAlmostEqual(context["leverage"], LEVERAGE, places=1)

        # Jalur 2: leverage_net = paper_gain / net_inflow
        self.assertAlmostEqual(context["leverage_net"],
                               PAPER_GAIN / NET_INFLOW_MONEY, places=1)

        # Jalur 3: manual dari angka
        self.assertAlmostEqual(context["leverage_net"],
                               context["paper_gain_usd"] / context["net_inflow_usd"],
                               places=1)

    def test_churn_uses_peak_cost(self):
        """churn_x = vol / est_cost_usd (peak-based) ≈ 21,1x."""
        event = {"vol": 1242746.0, "base_price": BASE_PRICE,
                 "close": CLOSE, "peak": PEAK,
                 "price_mult": PRICE_MULT, "vol_x": 1190.0,
                 "bars_ago": 0}
        # supply = 982jt → market_cap di close = 982jt × close ≈ 752.939
        mc_at_close = SUPPLY * CLOSE
        # liq/MC = 12.95% (nilai COCKROACH riil)
        liq_mc = LIQ_USD / (SUPPLY * BASE_PRICE)
        context = ss.sweep_context(event, liq_mc, None,
                                   market_cap_usd=mc_at_close,
                                   price_usd=CLOSE, liq_usd=LIQ_USD,
                                   net_inflow_usd=NET_INFLOW)
        self.assertAlmostEqual(context["churn_x"],
                               1242746.0 / EST_COST_PEAK, places=1)
        self.assertAlmostEqual(context["churn_net_x"],
                               1242746.0 / NET_INFLOW_MONEY, places=1)
        # Saat inflow ≈ biaya ke puncak, churn_x ≈ churn_net_x
        self.assertAlmostEqual(context["churn_x"], context["churn_net_x"], places=0)

    def test_event_without_peak_falls_back_to_price_mult(self):
        """Kalau peak tidak ada, pakai price_mult (bukan None)."""
        event = {"vol": 1000.0, "base_price": 1.0, "close": 1.6,
                 "price_mult": 1.6, "vol_x": 25.0, "bars_ago": 0}
        # Tanpa peak → fallback ke price_mult
        context = ss.sweep_context(event, None, None,
                                   market_cap_usd=100000.0,
                                   price_usd=1.6, liq_usd=1000.0)
        self.assertIsNotNone(context["peak_mult"])
        self.assertAlmostEqual(context["peak_mult"], 1.6, places=1)
        self.assertIsNotNone(context["est_cost_usd"])

    def test_candle_without_peak_field_still_works(self):
        """Kalau event tidak ada 'peak' sama sekali, fungsi tidak error."""
        event = {"vol": 1000.0, "base_price": 1.0, "close": 1.6,
                 "price_mult": 1.6, "vol_x": 25.0, "bars_ago": 0}
        context = ss.sweep_context(event, None, None)
        self.assertIsNotNone(context)
        self.assertIsNone(context["paper_gain_usd"])  # perlu peak + base_price


class SweepContextTest(unittest.TestCase):
    """Test khusus untuk sweep_context dengan angka COCKROACH riil."""

    def test_biaya_dorong_peak_sesuai_angka_terkirim(self):
        """est_cost_usd = (akar(peak_mult) - 1) × liq = $58.778."""
        event = {"vol": 1242746.0, "base_price": BASE_PRICE,
                 "close": CLOSE, "peak": PEAK,
                 "price_mult": PRICE_MULT, "vol_x": 1190.0,
                 "bars_ago": 0}
        context = ss.sweep_context(event, LIQ_USD / MC_USD, MC_USD,
                                   market_cap_usd=MC_USD, liq_usd=LIQ_USD)
        self.assertAlmostEqual(context["est_cost_usd"], EST_COST_PEAK,
                               delta=EST_COST_PEAK * 0.001)
        # est_cost_frac ≈ 12,6% (fraksi MC, uang masuk)
        self.assertAlmostEqual(context["est_cost_frac"],
                               NET_INFLOW_MONEY / MC_USD, places=3)

    def test_biaya_dorong_close_legacy_value(self):
        """est_cost_close_usd = (akar(price_mult) - 1) × liq / 2 = $12.033."""
        event = {"vol": 1242746.0, "base_price": BASE_PRICE,
                 "close": CLOSE, "peak": PEAK,
                 "price_mult": PRICE_MULT, "vol_x": 1190.0,
                 "bars_ago": 0}
        context = ss.sweep_context(event, LIQ_USD / MC_USD, MC_USD,
                                   market_cap_usd=MC_USD, liq_usd=LIQ_USD)
        self.assertAlmostEqual(context["est_cost_close_usd"], EST_COST_CLOSE,
                               delta=EST_COST_CLOSE * 0.001)

    def test_paper_gain_formula(self):
        """paper_gain_usd = supply × (peak - base_price) ≈ $1.79 juta."""
        event = {"vol": 1242746.0, "base_price": BASE_PRICE,
                 "close": CLOSE, "peak": PEAK,
                 "price_mult": PRICE_MULT, "vol_x": 1190.0,
                 "bars_ago": 0}
        # supply = MC / price_now (gunakan close sebagai harga sekarang)
        supply_calc = MC_USD / CLOSE
        expected = supply_calc * (PEAK - BASE_PRICE)
        context = ss.sweep_context(event, LIQ_USD / MC_USD, None,
                                   market_cap_usd=MC_USD,
                                   price_usd=CLOSE, liq_usd=LIQ_USD)
        self.assertAlmostEqual(context["paper_gain_usd"], expected,
                               delta=expected * 0.01)

    def test_inflow_terukur_menang_atas_acuan(self):
        # Inflow nyata COCKROACH 1 Okt: Δ TVL $58.778 = uang masuk $29.389 →
        # churn nyata 42,3x dan leverage_net 60,9x.
        event = {"vol": 1242746.0, "base_price": BASE_PRICE,
                 "close": CLOSE, "peak": PEAK,
                 "price_mult": PRICE_MULT, "vol_x": 1190.0,
                 "bars_ago": 0}
        # supply = 982jt → market_cap di close = 982jt × close ≈ 752.939
        mc_at_close = SUPPLY * CLOSE
        context = ss.sweep_context(event, 0.0, None,
                                   market_cap_usd=mc_at_close,
                                   price_usd=CLOSE, liq_usd=LIQ_USD,
                                   net_inflow_usd=NET_INFLOW)
        self.assertEqual(context["net_inflow_usd"], NET_INFLOW_MONEY)
        self.assertIsNone(context["net_inflow_ref_usd"])
        self.assertAlmostEqual(context["churn_net_x"],
                               1242746.0 / NET_INFLOW_MONEY, places=1)
        self.assertAlmostEqual(context["leverage_net"], LEVERAGE, places=1)
        self.assertNotEqual(context["churn_x"], context["churn_net_x"])

    def test_acuan_dipakai_hanya_saat_belum_terukur(self):
        event = {"vol": 1000.0, "base_price": 1.0, "close": 1.6,
                 "price_mult": 1.6, "vol_x": 25.0, "bars_ago": 0}
        context = ss.sweep_context(event, None, None, market_cap_usd=100000.0,
                                   price_usd=1.6, liq_usd=1000.0)
        self.assertIsNone(context["net_inflow_usd"])
        self.assertIsNone(context["churn_net_x"])
        # REF_NET_COST_MULT sekarang 1,0 (bukan 2,44)
        self.assertAlmostEqual(context["net_inflow_ref_usd"],
                               context["est_cost_usd"] * ss.REF_NET_COST_MULT,
                               places=2)
        self.assertEqual(ss.REF_NET_COST_MULT, 1.0)

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


class CohortFetchErrorTest(unittest.TestCase):
    def test_fetch_error_reason_is_surfaced_and_gate_holds(self):
        profile = ss.cohort_profile([], 1_000, 1.0, now=1_000 + 3600,
                                        fetch_error="GeckoTerminal HTTP 429")
        self.assertEqual(profile["error"], "GeckoTerminal HTTP 429")
        gate = ss.cohort_gate(profile)
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["status"], "TANPA DATA — kohort")

    def test_generic_message_kept_without_fetch_error(self):
        profile = ss.cohort_profile([], 1_000, 1.0, now=1_000 + 3600)
        self.assertEqual(profile["error"], "OHLCV 48 jam pertama tidak tersedia")
