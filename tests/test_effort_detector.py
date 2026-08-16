"""Unit test detektor 3 sinyal bottom (SELLER_EXHAUSTION / REVERSAL / AKUMULASI).

Meliputi definition-of-done:
  (a) exhaustion (volume turun ≤40%)
  (b) reversal   (volume naik ≥130%, CVD negatif runtuh)
  (c) akumulasi  (CVD positif ≥ +5 SOL, volume naik ≥130%)
  (d) batas hari UTC (00:00 UTC = 07:00 WIB)
plus gerbang flush/collapse/price-cap, anti wash-trade, flag whale,
penanda on-chain, export CSV, rekapan, dan storage window idempoten.
"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from cvd_daily import calculate_daily_cvd, day_key
from effort_detector import (
    ACCUM_CVD_MIN,
    ACCUM_PRICE_CAP_PCT,
    ACCUM_VOLUME_SURGE_RATIO,
    AKUMULASI,
    EXPORT_COLUMNS,
    NO_SIGNAL,
    REVERSAL,
    REVERSAL_VOLUME_SURGE_RATIO,
    SELLER_EXHAUSTION,
    SELLING_COLLAPSE_RATIO,
    SELLING_FLUSH_CVD,
    SELLING_LOOKBACK_DAYS,
    SELLING_PRICE_CAP_PCT,
    SELLING_VOLUME_SHRINK_RATIO,
    SIGNALS,
    VOLUME_MC_MAX_RATIO,
    WHALE_PCT_THRESHOLD,
    classify_all,
    classify_at,
    classify_effort,
    daily_effort_record,
    format_recap,
    merge_daily_effort,
    rows_with_signals,
)


def make_row(date, open_, close, cvd, *, mint="M", volume_usd=None,
             marketcap_close=None, top_wallet_pct=None, **tags):
    """Daily row builder; extra keyword args become on-chain marker counts."""
    row = daily_effort_record(mint, date, open_, close, cvd)
    if volume_usd is not None:
        row["volume_usd"] = volume_usd
    if marketcap_close is not None:
        row["marketcap_close"] = marketcap_close
    if top_wallet_pct is not None:
        row["top_wallet_pct"] = top_wallet_pct
    for key, value in tags.items():
        if key in ("smart_money_buy", "fresh_buy", "bot_sell", "mev_noise"):
            row[key] = value
    return row


class ThresholdContractTest(unittest.TestCase):
    """Threshold §1 harus persis — pengujian ini pengaman regresi."""

    def test_thresholds_exact(self):
        self.assertEqual(SELLING_FLUSH_CVD, 30.0)
        self.assertEqual(SELLING_COLLAPSE_RATIO, 0.40)
        self.assertEqual(SELLING_LOOKBACK_DAYS, 5)
        self.assertEqual(SELLING_PRICE_CAP_PCT, 0.5)
        self.assertEqual(SELLING_VOLUME_SHRINK_RATIO, 0.40)
        self.assertEqual(REVERSAL_VOLUME_SURGE_RATIO, 1.30)
        self.assertEqual(ACCUM_CVD_MIN, 5.0)
        self.assertEqual(ACCUM_PRICE_CAP_PCT, 0.5)
        self.assertEqual(ACCUM_VOLUME_SURGE_RATIO, 1.30)
        self.assertEqual(WHALE_PCT_THRESHOLD, 40.0)
        self.assertEqual(VOLUME_MC_MAX_RATIO, 3.0)

    def test_signal_names(self):
        self.assertEqual(SIGNALS, ("SELLER_EXHAUSTION", "REVERSAL", "AKUMULASI"))
        self.assertEqual(NO_SIGNAL, "—")


class DailyRecordTest(unittest.TestCase):
    def test_price_pct_and_direction(self):
        row = daily_effort_record("M", "2026-08-01", 100, 80, -10)
        self.assertAlmostEqual(row["price_chg_pct"], -20)
        self.assertEqual(row["direction"], "down")
        # Framework lama (R/M/baseline) tidak boleh kembali.
        self.assertNotIn("ratio", row)

    def test_flat_day(self):
        row = daily_effort_record("M", "2026-08-01", 100, 100, 3)
        self.assertEqual(row["price_chg_pct"], 0)
        self.assertEqual(row["direction"], "flat")


class SellerExhaustionTest(unittest.TestCase):
    """(a) SELLER_EXHAUSTION: CVD runtuh vs flush + volume KERING (≤40%)."""

    def _rows(self, *, today_volume, prev_volume=1000.0, cvd_today=-15.4,
              price_close=29.0, mc=None):
        flush = make_row("2026-07-10", 100, 40, -946.0, volume_usd=9000.0)
        gap1 = make_row("2026-07-11", 40, 38, -2.0, volume_usd=prev_volume)
        gap2 = make_row("2026-07-12", 38, 37, -1.0, volume_usd=prev_volume)
        prev = make_row("2026-07-15", 37, 36, -2.5, volume_usd=prev_volume)
        today = make_row("2026-07-16", 36, price_close, cvd_today,
                         volume_usd=today_volume, marketcap_close=mc)
        rows = [flush, gap1, gap2, prev, today]
        rows.sort(key=lambda r: r["date"])
        return rows, len(rows) - 1

    def test_exhaustion_fires(self):
        # -15.4 vs flush -946 (1.6% ≤ 40%), volume 280/1000 = 28% ≤ 40%
        rows, idx = self._rows(today_volume=280.0)
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], SELLER_EXHAUSTION)
        self.assertEqual(res["bias"], "bullish")
        self.assertEqual(res["status"], "signal")
        self.assertEqual(res["flush_date"], "2026-07-10")
        self.assertAlmostEqual(res["flush_cvd"], -946.0)
        self.assertAlmostEqual(res["cvd_delta"], -15.4)
        self.assertAlmostEqual(res["volume_usd"], 280.0)
        self.assertAlmostEqual(res["volume_pct"], 28.0)
        self.assertFalse(res["flag_divergence"])

    def test_exhaustion_boundary_volume_40pct(self):
        rows, idx = self._rows(today_volume=400.0)  # tepat 40%
        self.assertEqual(classify_at(rows, idx)["signal"], SELLER_EXHAUSTION)
        rows, idx = self._rows(today_volume=400.01)
        self.assertEqual(classify_at(rows, idx)["signal"], NO_SIGNAL)

    def test_exhaustion_boundary_collapse_40pct(self):
        # |cvd| = 0.40 × 946 = 378.4 → lolos; 378.41 → gagal
        rows, idx = self._rows(today_volume=280.0, cvd_today=-378.4)
        self.assertEqual(classify_at(rows, idx)["signal"], SELLER_EXHAUSTION)
        rows, idx = self._rows(today_volume=280.0, cvd_today=-378.41)
        self.assertEqual(classify_at(rows, idx)["signal"], NO_SIGNAL)

    def test_exhaustion_needs_flush(self):
        rows = [
            make_row("2026-07-10", 100, 80, -10.0, volume_usd=900.0),
            make_row("2026-07-11", 80, 79, -4.0, volume_usd=300.0),
        ]
        # tidak ada flush ≤ -30 SOL → tanpa sinyal
        res = classify_at(rows, 1)
        self.assertEqual(res["signal"], NO_SIGNAL)
        self.assertIsNone(res["flush_date"])

    def test_exhaustion_flush_lookback_5_days(self):
        flush = make_row("2026-07-10", 100, 40, -50.0, volume_usd=1000.0)
        quiet = [make_row(f"2026-07-{day}", 40, 39, -2.0, volume_usd=800.0)
                 for day in (11, 12, 13, 14)]
        # flush tepat 5 hari sebelum hari N (2026-07-15) → masih dihitung
        rows = [flush, *quiet,
                make_row("2026-07-15", 39, 38, -5.0, volume_usd=200.0)]
        self.assertEqual(classify_at(rows, 5)["signal"], SELLER_EXHAUSTION)
        # flush 6 hari sebelum (hari N = 2026-07-16) → di luar lookback
        rows2 = rows + [make_row("2026-07-16", 38, 37, -5.0,
                                 volume_usd=200.0)]
        self.assertEqual(classify_at(rows2, 6)["signal"], NO_SIGNAL)

    def test_exhaustion_price_cap(self):
        rows, idx = self._rows(today_volume=280.0, price_close=36.18)  # +0.5%
        self.assertEqual(classify_at(rows, idx)["signal"], SELLER_EXHAUSTION)
        rows, idx = self._rows(today_volume=280.0, price_close=36.19)  # >+0.5%
        self.assertEqual(classify_at(rows, idx)["signal"], NO_SIGNAL)

    def test_exhaustion_needs_negative_cvd(self):
        rows, idx = self._rows(today_volume=280.0, cvd_today=6.0)
        # CVD positif + volume turun → bukan exhaustion (dan bukan akumulasi)
        self.assertEqual(classify_at(rows, idx)["signal"], NO_SIGNAL)

    def test_exhaustion_needs_prev_volume(self):
        rows, idx = self._rows(today_volume=280.0)
        rows[idx - 1].pop("volume_usd", None)  # volume N-1 tak diketahui
        self.assertEqual(classify_at(rows, idx)["signal"], NO_SIGNAL)

    def test_wash_trade_gate(self):
        # volume 280 ≤ 40% dari kemarin, tapi > 3× MC close (80) → dibatalkan
        rows, idx = self._rows(today_volume=280.0, mc=80.0)
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], NO_SIGNAL)
        self.assertTrue(res["wash_blocked"])
        # MC tidak tersedia → gerbang wash dilewati
        rows, idx = self._rows(today_volume=280.0)
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], SELLER_EXHAUSTION)
        self.assertFalse(res["wash_blocked"])
        # volume tepat 3× MC → lolos
        rows, idx = self._rows(today_volume=240.0, mc=80.0)
        self.assertEqual(classify_at(rows, idx)["signal"], SELLER_EXHAUSTION)


class ReversalTest(unittest.TestCase):
    """(b) REVERSAL: CVD runtuh vs flush + volume NAIK (≥130%)."""

    def _rows(self, *, today_volume, prev_volume=200.0, cvd_today=-36.0):
        flush = make_row("2026-06-26", 100, 55, -90.0, volume_usd=3000.0)
        prev = make_row("2026-06-27", 55, 52, -4.0, volume_usd=prev_volume)
        today = make_row("2026-06-28", 52, 42.5, cvd_today,
                         volume_usd=today_volume)
        return [flush, prev, today], 2

    def test_reversal_fires(self):
        # -36 vs flush -90 (40% ≤ 40%), volume 262/200 = 131% ≥ 130%
        rows, idx = self._rows(today_volume=262.0)
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], REVERSAL)
        self.assertEqual(res["bias"], "bullish")
        self.assertEqual(res["flush_date"], "2026-06-26")
        self.assertAlmostEqual(res["volume_pct"], 131.0, places=3)

    def test_reversal_boundary_volume_130pct(self):
        rows, idx = self._rows(today_volume=260.0)  # tepat 130%
        self.assertEqual(classify_at(rows, idx)["signal"], REVERSAL)
        # di antara 40%..130% → tidak exhaustion, tidak reversal
        rows, idx = self._rows(today_volume=259.99)
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], NO_SIGNAL)

    def test_volume_mid_band_no_signal(self):
        rows, idx = self._rows(today_volume=150.0, prev_volume=200.0)  # 75%
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], NO_SIGNAL)
        self.assertIn("di antara", res["reason"])

    def test_reversal_wash_gate_inherited(self):
        # Gerbang anti wash-trade diwarisi dari exhaustion.
        rows, idx = self._rows(today_volume=262.0)
        rows[idx]["marketcap_close"] = 50.0   # 262 > 3×50 → wash
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], NO_SIGNAL)
        self.assertTrue(res["wash_blocked"])

    def test_reversal_needs_collapse(self):
        # CVD -50 masih 55% dari flush -90 → belum runtuh
        rows, idx = self._rows(today_volume=262.0, cvd_today=-50.0)
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], NO_SIGNAL)
        self.assertIn("belum runtuh", res["reason"])


class AkumulasiTest(unittest.TestCase):
    """(c) AKUMULASI: CVD ≥ +5 SOL + harga ≤ +0.5% + volume ≥130%."""

    def _rows(self, *, cvd=72.2, volume=700.0, prev_volume=500.0,
              close=98.0):
        prev = make_row("2025-12-24", 100, 99, 2.0, volume_usd=prev_volume)
        today = make_row("2025-12-25", 99, close, cvd, volume_usd=volume)
        return [prev, today], 1

    def test_akumulasi_fires(self):
        rows, idx = self._rows()  # CVD +72.2, harga -1.0%, volume 140%
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], AKUMULASI)
        self.assertEqual(res["bias"], "bullish")
        self.assertIsNone(res["flush_date"])
        self.assertTrue(res["flag_divergence"])  # harga turun, CVD naik
        self.assertAlmostEqual(res["volume_pct"], 140.0)

    def test_akumulasi_cvd_boundary(self):
        rows, idx = self._rows(cvd=5.0)  # tepat +5 SOL
        self.assertEqual(classify_at(rows, idx)["signal"], AKUMULASI)
        rows, idx = self._rows(cvd=4.99)
        self.assertEqual(classify_at(rows, idx)["signal"], NO_SIGNAL)

    def test_akumulasi_price_cap(self):
        rows, idx = self._rows(close=99.495)   # +0.5% → lolos
        self.assertEqual(classify_at(rows, idx)["signal"], AKUMULASI)
        rows, idx = self._rows(close=99.496)   # > +0.5% → gagal
        self.assertEqual(classify_at(rows, idx)["signal"], NO_SIGNAL)

    def test_akumulasi_volume_surge_required(self):
        rows, idx = self._rows(volume=649.9, prev_volume=500.0)  # 129.98%
        res = classify_at(rows, idx)
        self.assertEqual(res["signal"], NO_SIGNAL)
        self.assertIn("akumulasi tidak terkonfirmasi", res["reason"])

    def test_akumulasi_flat_price_ok(self):
        rows, idx = self._rows(close=99.0)  # harga flat 0%
        self.assertEqual(classify_at(rows, idx)["signal"], AKUMULASI)

    def test_akumulasi_needs_first_comparison_day(self):
        row = make_row("2025-12-25", 99, 98, 72.2, volume_usd=700.0)
        res = classify_at([row], 0)
        self.assertEqual(res["signal"], NO_SIGNAL)
        self.assertEqual(res["status"], "first_day")


class ScanAndOrderTest(unittest.TestCase):
    """Scan seluruh window (§5), urutan cek (§3), flag & tag (§4)."""

    def test_classify_all_scans_each_day(self):
        flush = make_row("2026-07-10", 100, 60, -946.0, volume_usd=6000.0)
        dry = make_row("2026-07-11", 60, 59, -4.0, volume_usd=900.0)
        up = make_row("2026-07-12", 59, 59.2, 30.0, volume_usd=1600.0)
        none_day = make_row("2026-07-13", 59.2, 58.7, -500.0,
                            volume_usd=1000.0)  # 52.9% dari flush → belum runtuh
        ex = make_row("2026-07-14", 58.7, 57.2, -12.0, volume_usd=300.0)
        rows = [flush, dry, up, none_day, ex]
        results = classify_all(rows)
        self.assertEqual(len(results), 5)
        self.assertEqual(results[0]["signal"], NO_SIGNAL)  # hari pertama "—"
        self.assertEqual(results[1]["signal"], SELLER_EXHAUSTION)
        self.assertEqual(results[2]["signal"], AKUMULASI)
        self.assertEqual(results[3]["signal"], NO_SIGNAL)
        self.assertEqual(results[4]["signal"], SELLER_EXHAUSTION)

    def test_classify_effort_picks_last_day(self):
        rows = [
            make_row("2026-07-10", 100, 60, -946.0, volume_usd=6000.0),
            make_row("2026-07-11", 60, 59, -10.0, volume_usd=1000.0),
            make_row("2026-07-12", 59, 58, 40.0, volume_usd=1400.0),
        ]
        res = classify_effort(rows, "M")
        self.assertEqual(res["date"], "2026-07-12")
        self.assertEqual(res["signal"], AKUMULASI)

    def test_classify_effort_empty(self):
        res = classify_effort([], "M")
        self.assertEqual(res["signal"], NO_SIGNAL)
        self.assertEqual(res["status"], "missing")

    def test_exhaustion_checked_before_reversal(self):
        # Volume turun → exhaustion walaupun hari itu juga memenuhi gerbang CVD.
        rows = [
            make_row("2026-07-10", 100, 60, -100.0, volume_usd=1000.0),
            make_row("2026-07-11", 60, 59, -20.0, volume_usd=300.0),
        ]
        res = classify_at(rows, 1)
        self.assertEqual(res["signal"], SELLER_EXHAUSTION)
        # Dan CVD negatif tidak pernah bisa menyentuh cabang AKUMULASI.
        self.assertNotEqual(res["signal"], AKUMULASI)

    def test_whale_flag(self):
        rows = [
            make_row("2026-07-10", 100, 60, -100.0, volume_usd=1000.0),
            make_row("2026-07-11", 60, 59, -10.0, volume_usd=300.0,
                     top_wallet_pct=45.0),
        ]
        res = classify_at(rows, 1)
        self.assertEqual(res["signal"], SELLER_EXHAUSTION)
        self.assertTrue(res["whale_driven"])
        rows[1]["top_wallet_pct"] = 39.9
        self.assertFalse(classify_at(rows, 1)["whale_driven"])

    def test_onchain_tags_passthrough(self):
        rows = [
            make_row("2026-07-10", 100, 60, -100.0, volume_usd=1000.0,
                     smart_money_buy=1, fresh_buy=0, bot_sell=2, mev_noise=5),
            make_row("2026-07-11", 60, 59, -10.0, volume_usd=300.0,
                     smart_money_buy=3, fresh_buy=1, bot_sell=1, mev_noise=2),
        ]
        res = classify_at(rows, 1)
        self.assertEqual(res["smart_money_buy"], 3)
        self.assertEqual(res["fresh_buy"], 1)
        self.assertEqual(res["bot_sell"], 1)
        self.assertEqual(res["mev_noise"], 2)

    def test_rows_unsorted_input(self):
        # classify harus toleran urutan acak
        rows = [
            make_row("2026-07-11", 60, 59, -10.0, volume_usd=300.0),
            make_row("2026-07-10", 100, 60, -100.0, volume_usd=1000.0),
        ]
        self.assertEqual(classify_at(rows, 1)["signal"], SELLER_EXHAUSTION)


class ExportAndRecapTest(unittest.TestCase):
    def _rows(self):
        return [
            make_row("2026-06-26", 100, 55, -90.0, volume_usd=3000.0,
                     top_wallet_pct=41.0, smart_money_buy=1),
            make_row("2026-06-27", 55, 50, -4.0, volume_usd=200.0,
                     fresh_buy=2),
            make_row("2026-06-28", 50, 41, -36.0, volume_usd=270.0,
                     bot_sell=1, mev_noise=1),
        ]

    def test_export_columns_and_first_day_dash(self):
        exported = rows_with_signals(self._rows())
        self.assertEqual(list(exported[0].keys()), EXPORT_COLUMNS)
        self.assertEqual(exported[0]["signal"], "—")
        self.assertEqual(exported[1]["signal"], SELLER_EXHAUSTION)
        self.assertEqual(exported[2]["signal"], REVERSAL)
        # kolom info ikut terbawa
        self.assertEqual(exported[0]["top_wallet_pct"], 41.0)
        self.assertEqual(exported[0]["smart_money_buy"], 1)
        self.assertEqual(exported[2]["bot_sell"], 1)
        self.assertEqual(exported[2]["flush_date"], "2026-06-26")

    def test_recap_format(self):
        recap = format_recap("M", self._rows())
        lines = recap.splitlines()
        self.assertEqual(lines[0], "# === REKAPAN 3 SINYAL BOTTOM ===")
        self.assertIn("# Mint: M", lines)
        # hanya hari bersinyal yang direkap
        body = [line for line in lines if "|" in line]
        self.assertEqual(len(body), 2)
        self.assertRegex(body[0], r"^# 2026-06-27  SELLER_EXHAUSTION  \| "
                                  r"Δ-9\.1% \| CVD -4\.0 \| vol 7% "
                                  r"dari kemarin$")
        self.assertIn("# 2026-06-28  REVERSAL           | Δ-18.0% | "
                      "CVD -36.0 | vol 135% dari kemarin", body[1])

    def test_recap_skips_neutral_days(self):
        rows = [
            make_row("2026-07-10", 100, 99, 0.5, volume_usd=100.0),
            make_row("2026-07-11", 99, 98.5, 0.4, volume_usd=110.0),
        ]
        recap = format_recap("M", rows)
        self.assertNotIn("SELLER_EXHAUSTION", recap)
        self.assertNotIn("REVERSAL", recap)
        self.assertNotIn("AKUMULASI", recap)


class StorageTest(unittest.TestCase):
    def test_merge_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "daily.json")
            rows = [daily_effort_record("M", f"2026-08-{day:02d}", 100, 90,
                                        -day)
                    for day in range(1, 6)]
            first = merge_daily_effort(rows, path=path, window_days=3)
            second = merge_daily_effort(rows[-1:], path=path, window_days=3)
            self.assertEqual(first, second)
            self.assertEqual([row["date"] for row in second],
                             ["2026-08-03", "2026-08-04", "2026-08-05"])
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), second)


class DayBoundaryTest(unittest.TestCase):
    """(d) Batas hari = 00:00 UTC (= 07:00 WIB, konvensi GMGN)."""

    def test_day_boundary_is_utc(self):
        ts1 = int(datetime.fromisoformat("2026-08-01T00:30:00+00:00").timestamp())
        rows = calculate_daily_cvd([("buy", 3.0, ts1, "A"),
                                    ("sell", 1.0, ts1 + 60, "B")])
        self.assertEqual(rows[0]["date"], "2026-08-01")

        ts2 = int(datetime.fromisoformat("2026-08-01T23:59:00+00:00").timestamp())
        rows2 = calculate_daily_cvd([("buy", 3.0, ts2, "A"),
                                     ("sell", 1.0, ts2 + 120, "B")])
        self.assertEqual([row["date"] for row in rows2],
                         ["2026-08-01", "2026-08-02"])

        # 00:00 WIB = 17:00 UTC hari sebelumnya → tetap hari UTC yang sama
        ts_wib_midnight = int(datetime.fromisoformat(
            "2026-08-01T17:00:00+00:00").timestamp())
        self.assertEqual(day_key(ts_wib_midnight), "2026-08-01")
        # 00:00 UTC persis → hari baru (walaupun baru 07:00 WIB)
        ts_utc_midnight = int(datetime.fromisoformat(
            "2026-08-02T00:00:00+00:00").timestamp())
        self.assertEqual(day_key(ts_utc_midnight), "2026-08-02")


if __name__ == "__main__":
    unittest.main()
