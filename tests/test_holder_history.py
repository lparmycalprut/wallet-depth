"""Coverage dust flag, kohort mid-tier, resample 4 jam, sparkline."""
from __future__ import annotations

import os
import tempfile
import unittest

import holder_history as hh


def _h(addr, usd, balance=None, is_wallet=True):
    return {
        "address": addr, "usd_value": usd,
        "balance": usd if balance is None else balance,
        "is_wallet": is_wallet,
    }


class DustFlagTest(unittest.TestCase):
    def test_danger_at_one_percent(self):
        flag = hh.dust_flag(1.0)
        self.assertEqual(flag["level"], "danger")
        self.assertEqual(flag["label"], "BAHAYA")
        self.assertTrue(flag["hide"])
        self.assertTrue(hh.should_hide_dust(1.0))
        self.assertTrue(hh.should_hide_dust(2.01))

    def test_caution_from_half_percent(self):
        flag = hh.dust_flag(0.5)
        self.assertEqual(flag["level"], "caution")
        self.assertEqual(flag["label"], "HATI-HATI")
        # HATI-HATI masih di bawah BAHAYA: tidak disembunyikan dari Meteora.
        self.assertFalse(flag["hide"])
        self.assertFalse(hh.should_hide_dust(0.5))
        self.assertEqual(hh.dust_flag(0.99)["level"], "caution")

    def test_ok_below_caution_threshold(self):
        flag = hh.dust_flag(0.49)
        self.assertEqual(flag["level"], "ok")
        self.assertEqual(flag["label"], "AMAN")
        self.assertFalse(flag["hide"])
        self.assertFalse(hh.should_hide_dust(0.0))

    def test_unknown_without_pct(self):
        flag = hh.dust_flag(None)
        self.assertEqual(flag["level"], "unknown")
        self.assertFalse(flag["hide"])
        self.assertFalse(flag["rising"])

    def test_level_rank_orders_severity(self):
        self.assertLess(hh.dust_level_rank("ok"), hh.dust_level_rank("caution"))
        self.assertLess(hh.dust_level_rank("caution"),
                        hh.dust_level_rank("danger"))
        self.assertEqual(hh.dust_level_rank(None), -1)

    def test_rising_compared_to_previous(self):
        flag = hh.dust_flag(1.4, 1.1)
        self.assertTrue(flag["rising"])
        self.assertFalse(hh.dust_flag(1.4, 1.4)["rising"])
        # naik di dalam zona HATI-HATI juga terdeteksi
        self.assertTrue(hh.dust_flag(0.7, 0.55)["rising"])


class MidTierAndCohortTest(unittest.TestCase):
    def test_mid_excludes_pool_and_dust(self):
        stats = hh.mid_tier_stats([
            _h("dust", 9),
            _h("crab", 250, balance=1000),
            _h("fish", 4000, balance=2000),
            _h("shark", 50_000, balance=9000),
            _h("POOL", 800, balance=500, is_wallet=True),
        ], market_cap=100_000, pool_addresses=["POOL"])
        self.assertEqual(stats["count"], 2)
        self.assertIn("crab", stats["balances"])
        self.assertIn("fish", stats["balances"])
        self.assertNotIn("POOL", stats["balances"])
        self.assertAlmostEqual(stats["pct_mc"], 4.25, places=2)

    def test_score_cohort_uses_token_not_usd(self):
        frozen = {"A": 100.0, "B": 100.0}
        current = {"A": 100.0, "B": 40.0}  # B potong 60% token
        score = hh.score_cohort(frozen, current)
        self.assertAlmostEqual(score["remaining_pct"], 70.0, places=2)
        self.assertAlmostEqual(score["cut50_pct"], 50.0, places=2)

    def test_missing_address_counts_as_full_exit(self):
        score = hh.score_cohort({"A": 10.0}, {})
        self.assertAlmostEqual(score["remaining_pct"], 0.0)
        self.assertAlmostEqual(score["cut50_pct"], 100.0)

    def test_lookup_fills_zero_for_missing(self):
        found = hh.lookup_balances([_h("A", 5, balance=3)], ["A", "B"])
        self.assertEqual(found["A"], 3)
        self.assertEqual(found["B"], 0.0)


class HistoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "hist.json")

    def _analysis(self, *, dust_pct=0.4, dust_count=10, mid_balances=None,
                  cohort_now=None, ts=1_800_000_000):
        return {
            "symbol": "TST", "marketcap": 50_000, "price": 0.01,
            "analyzed_at": ts,
            "holders": {
                "dust_count": dust_count, "dust_pct_mc": dust_pct,
                "dust_value_usd": 200, "real_count": 8, "real_pct_mc": 12.0,
                "mid": {"count": len(mid_balances or {}), "pct_mc": 5.0,
                        "balances": mid_balances or {"A": 10.0}},
                "cohort_now": cohort_now or {},
            },
        }

    def test_first_ingest_freezes_cohort_at_100(self):
        store = hh.empty_store()
        hh.ingest_one(store, "MINT", self._analysis(mid_balances={"A": 10}),
                      now=100)
        self.assertEqual(store["tokens"]["MINT"]["cohort"]["balances"]["A"], 10)
        pt = store["tokens"]["MINT"]["points"][0]
        self.assertAlmostEqual(pt["cohort_token_pct"], 100.0)

    def test_second_ingest_scores_against_frozen_tokens(self):
        store = hh.empty_store()
        hh.ingest_one(store, "MINT", self._analysis(mid_balances={"A": 10},
                                                    ts=100), now=100)
        hh.ingest_one(store, "MINT", self._analysis(
            mid_balances={"A": 4}, cohort_now={"A": 4}, ts=100 + 900),
                      now=100 + 900)
        pt = store["tokens"]["MINT"]["points"][-1]
        self.assertAlmostEqual(pt["cohort_token_pct"], 40.0)
        self.assertAlmostEqual(pt["cohort_cut50_pct"], 100.0)

    def test_resample_4h_keeps_last_in_bucket(self):
        points = [
            {"ts": 0, "dust_pct_mc": 0.5},
            {"ts": 100, "dust_pct_mc": 0.8},
            {"ts": 4 * 3600 + 10, "dust_pct_mc": 1.2},
        ]
        sampled = hh.resample_4h(points)
        self.assertEqual(len(sampled), 2)
        self.assertAlmostEqual(sampled[0]["dust_pct_mc"], 0.8)
        self.assertAlmostEqual(sampled[1]["dust_pct_mc"], 1.2)

    def test_sparkline_needs_two_values(self):
        self.assertEqual(hh.sparkline_svg([{"ts": 1, "dust_pct_mc": 1}]), "")
        svg = hh.sparkline_svg([
            {"ts": 100, "dust_pct_mc": 0.4},
            {"ts": 4 * 3600 + 100, "dust_pct_mc": 1.5},
        ])
        self.assertIn("<svg", svg)
        self.assertIn("#b91c1c", svg)  # rising → merah

    def test_detail_scan_writes_baseline_once(self):
        store = hh.empty_store()
        first = self._analysis(dust_count=10)
        first["holders"]["depth"] = {
            "buckets": [{"label": ">$0-$10", "count": 10, "value_usd": 50},
                        {"label": "$10-$100", "count": 4, "value_usd": 200}],
            "tiers": [{"tier": "Shrimp", "emoji": "🦐", "count": 12,
                       "pct_mc": 1.0}],
            "holders_all": 14, "holders_wallet": 14,
        }
        first["holders"]["wallets_analyzed"] = 14
        hh.ingest_one(store, "MINT", first, now=100, detail=True)
        baseline = hh.baseline_for_mint(store, "MINT")
        self.assertEqual(baseline["ts"], 100)
        self.assertEqual(len(baseline["depth"]["buckets"]), 2)

        second = self._analysis(dust_count=30)
        second["holders"]["depth"] = {
            "buckets": [{"label": ">$0-$10", "count": 30, "value_usd": 120},
                        {"label": "$10-$100", "count": 3, "value_usd": 150}],
            "tiers": [], "holders_all": 33, "holders_wallet": 33,
        }
        second["holders"]["wallets_analyzed"] = 33
        hh.ingest_one(store, "MINT", second, now=100 + 3600, detail=True)
        # Baseline tetap scan pertama, detail terbaru ikut yang kedua.
        self.assertEqual(hh.baseline_for_mint(store, "MINT")["ts"], 100)
        self.assertEqual(hh.latest_detail_for_mint(store, "MINT")["ts"],
                         100 + 3600)
        delta = {r["label"]: r["delta"] for r in hh.bucket_delta(
            hh.baseline_for_mint(store, "MINT"),
            hh.latest_detail_for_mint(store, "MINT"))}
        self.assertEqual(delta[">$0-$10"], 20)
        self.assertEqual(delta["$10-$100"], -1)

    def test_cron_point_never_overwrites_baseline(self):
        store = hh.empty_store()
        full = self._analysis()
        full["holders"]["depth"] = {
            "buckets": [{"label": ">$0-$10", "count": 5, "value_usd": 20}],
            "tiers": [],
        }
        hh.ingest_one(store, "MINT", full, now=100, detail=True)
        hh.ingest_one(store, "MINT", self._analysis(dust_count=99),
                      now=100 + 3600)  # scan non-detail: hanya titik ringkas
        self.assertEqual(hh.baseline_for_mint(store, "MINT")["ts"], 100)
        self.assertEqual(
            hh.latest_detail_for_mint(store, "MINT")["ts"], 100)
        self.assertEqual(store["tokens"]["MINT"]["points"][-1]["dust_count"],
                         99)
        self.assertTrue(store["tokens"]["MINT"]["points"][0].get("full"))
        self.assertNotIn("full", store["tokens"]["MINT"]["points"][-1])

    def test_bucket_counts_and_series(self):
        self.assertEqual(
            hh.bucket_counts({"buckets": [{"label": "$10-$100", "count": 7}]}),
            {"$10-$100": 7})
        points = [
            {"ts": 100, "buckets": {"a": 1, "b": 2}},
            {"ts": 4 * 3600 + 100, "buckets": {"a": 4}},
        ]
        stamps, labels, series = hh.bucket_series(points)
        self.assertEqual(len(stamps), 2)
        self.assertEqual(labels, ["a", "b"])
        self.assertEqual(series["a"], [1, 4])
        self.assertEqual(series["b"], [2, 0])

    def test_detail_survives_save_and_load(self):
        analysis = self._analysis()
        analysis["holders"]["depth"] = {
            "buckets": [{"label": ">$0-$10", "count": 3, "value_usd": 9}],
            "tiers": [],
        }
        hh.ingest_many({"MINT": analysis}, path=self.path, now=50,
                       detail=True)
        loaded = hh.load_holder_history(self.path)
        self.assertEqual(hh.baseline_for_mint(loaded, "MINT")["ts"], 50)
        self.assertEqual(
            hh.baseline_for_mint(loaded, "MINT")["depth"]["buckets"][0][
                "count"], 3)

    def test_ingest_many_roundtrip_file(self):
        hh.ingest_many({"MINT": self._analysis()}, path=self.path, now=50)
        loaded = hh.load_holder_history(self.path)
        self.assertIn("MINT", loaded["tokens"])
        self.assertEqual(len(loaded["tokens"]["MINT"]["points"]), 1)

    def test_seed_from_status_restores_alert_state_for_next_cron(self):
        remote_state = {
            "baseline": {"ts": 100, "dust_pct_mc": 0.2,
                         "balances": {"A": 1.0}, "dust": ["A"]},
            "rolling": {"ts": 200, "dust_pct_mc": 0.4,
                        "balances": {"A": 2.0}, "dust": ["A"]},
            "sent_event_ids": ["event-1"],
        }
        store = hh.seed_from_status(
            hh.empty_store(),
            {"tokens": {"MINT": {"symbol": "TST", "history": [],
                                  "alert_state": remote_state}}},
        )
        restored = store["tokens"]["MINT"]["alert_state"]
        self.assertEqual(restored["rolling"]["ts"], 200)
        self.assertEqual(restored["sent_event_ids"], ["event-1"])




def _valid_holders(fetched=55, wallets=45):
    return {"total_fetched": fetched, "wallets_analyzed": wallets,
            "real_count": wallets - 3, "dust_count": 3}


class DustBestFlagTest(unittest.TestCase):
    """Badge BEST POOL (dust < 0,1% MC) + guard kebenaran data (2026-09-04)."""

    def test_best_hanya_di_bawah_01_persen_dengan_data_valid(self):
        flag = hh.dust_flag(0.08, holders=_valid_holders())
        self.assertTrue(flag["best"])
        # Level lama tidak berubah: badge BEST POOL bersifat penanda tambahan.
        self.assertEqual(flag["level"], "ok")
        self.assertEqual(flag["label"], "AMAN")
        self.assertFalse(flag["hide"])

    def test_pas_di_01_persen_tidak_best_dan_tidak_memicu_alert(self):
        # Boundary sengaja strict: == 0,1% bukan BEST POOL (< 0,1%) dan juga
        # tidak memicu rule early_dump (> 0,1%) — dua sinyal tidak tumpang
        # tindih di angka yang sama (dokumentasi PROGRESS.md).
        flag = hh.dust_flag(0.1, holders=_valid_holders())
        self.assertFalse(flag["best"])
        self.assertEqual(flag["level"], "ok")

    def test_di_atas_01_persen_tidak_best_walau_data_valid(self):
        self.assertFalse(hh.dust_flag(0.1001, holders=_valid_holders())[
                         "best"])
        self.assertFalse(hh.dust_flag(0.5, holders=_valid_holders())["best"])

    def test_tanpa_holders_tidak_pernah_best(self):
        # Pemanggil lama (watchlist / Chart LP) tidak mengirim bukti data →
        # perilaku default tidak berubah: tidak ada badge BEST POOL.
        self.assertFalse(hh.dust_flag(0.05)["best"])
        self.assertFalse(hh.dust_flag(0.05, holders=None)["best"])
        self.assertFalse(hh.dust_flag(0.05, holders={})["best"])

    def test_data_kosong_tidak_best(self):
        # dust 0,00% juga muncul saat fetch holder gagal/kosong.
        self.assertFalse(hh.dust_flag(0.0, holders={
            "total_fetched": 0, "wallets_analyzed": 0})["best"])
        self.assertFalse(hh.dust_flag(0.0, holders={
            "total_fetched": 0, "wallets_analyzed": 45})["best"])

    def test_holder_di_bawah_min_40_tidak_best(self):
        self.assertFalse(hh.dust_flag(0.05, holders=_valid_holders(
            fetched=39, wallets=38))["best"])
        self.assertFalse(hh.dust_flag(0.05, holders={
            "total_fetched": 400, "wallets_analyzed": 39})["best"])

    def test_fallback_wallets_analyzed_dari_real_dan_dust(self):
        holders = {"total_fetched": 80, "real_count": 30, "dust_count": 12}
        self.assertTrue(hh.dust_flag(0.03, holders=holders)["best"])
        holders = {"total_fetched": 80, "real_count": 20, "dust_count": 12}
        self.assertFalse(hh.dust_flag(0.03, holders=holders)["best"])

    def test_flag_tetap_aman_walau_unknown(self):
        flag = hh.dust_flag(None, holders=_valid_holders())
        self.assertFalse(flag["best"])
        self.assertEqual(flag["level"], "unknown")


class FiveMinuteCadenceTest(unittest.TestCase):
    """Kadens 5 menit (Robinhood LP, 2026-09-06) tidak boleh membunuh history.

    ``MIN_POINT_GAP_SEC`` adalah ambang "scan dobel": titik yang lebih muda
    dari itu **ditimpa**, bukan ditambahkan. Di kalibrasi lama (8 menit) run
    tiap 5 menit akan saling menimpa selamanya — store Robinhood berhenti
    tumbuh dan grafik/Δ 4 jam membeku. Test ini mengunci invarian:
    ``MIN_POINT_GAP_SEC < kadens run tercepat``.
    """

    BASE = 1_800_000_000

    def _ingest_at(self, store, offset: int, dust: int) -> None:
        hh.ingest_one(store, "RH", {
            "symbol": "RH", "analyzed_at": self.BASE + offset,
            "holders": {"dust_count": dust, "dust_pct_mc": 0.2,
                        "dust_value_usd": 5.0, "real_count": 40,
                        "mid": {"count": 5, "balances": {}},
                        "cohort_now": {}}}, now=self.BASE + offset)

    def test_ambang_di_bawah_kadens_run(self):
        import scripts.scan_holders as scan
        self.assertLess(hh.MIN_POINT_GAP_SEC, scan.RUN_SCAN_INTERVAL_SEC)
        self.assertGreaterEqual(hh.MIN_POINT_GAP_SEC, scan.MIN_RUN_GAP_SEC)

    def test_titik_per_5_menit_semua_tersimpan(self):
        store = hh.empty_store()
        for run in range(6):     # 0, 5, 10, 15, 20, 25 menit
            self._ingest_at(store, run * 300, dust=run)
        points = store["tokens"]["RH"]["points"]
        self.assertEqual([p["ts"] for p in points],
                         [self.BASE + run * 300 for run in range(6)])
        self.assertEqual([p["dust_count"] for p in points], list(range(6)))

    def test_run_ganda_dalam_satu_menit_tetap_ditimpa(self):
        store = hh.empty_store()
        self._ingest_at(store, 0, dust=1)
        self._ingest_at(store, 60, dust=2)      # < MIN_POINT_GAP_SEC
        points = store["tokens"]["RH"]["points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["ts"], self.BASE + 60)
        self.assertEqual(points[0]["dust_count"], 2)


class HourlyCadenceTest(unittest.TestCase):
    """Cron 1×/jam (2026-09-04): MAX_POINTS 336 = 14 hari titik mentah."""

    def test_max_points_dikalibrasi_14_hari_x_24_jam(self):
        self.assertEqual(hh.MAX_POINTS, 24 * 14)

    def test_ingest_hourly_potong_ke_336_titik_terbaru(self):
        store = hh.empty_store()
        t0 = 1_800_000_000
        for hour in range(400):  # ~16,7 hari > 14 hari
            hh.ingest_one(store, "MINT", {
                "symbol": "TST", "analyzed_at": t0 + hour * 3600,
                "holders": {"dust_count": hour % 10, "dust_pct_mc": 0.1,
                            "dust_value_usd": 5.0, "real_count": 40,
                            "mid": {"count": 5, "balances": {"A": 1.0}},
                            "cohort_now": {}}}, now=t0 + hour * 3600)
        points = store["tokens"]["MINT"]["points"]
        self.assertEqual(len(points), hh.MAX_POINTS)
        # 336 jam terakhir yang tersisa, urut naik.
        self.assertEqual(points[0]["ts"], t0 + (400 - 336) * 3600)
        self.assertEqual(points[-1]["ts"], t0 + 399 * 3600)

    def test_resample_titik_per_jam_tetap_bucket_4_jam(self):
        # 336 titik per jam = 14 hari → maksimal 84 bucket 4 jam (sama
        # seperti sebelum cron hourly), nilai bucket = titik terakhir.
        t0 = 1_800_000_000
        points = [{"ts": t0 + hour * 3600, "dust_pct_mc": (hour % 7) / 10.0}
                  for hour in range(336)]
        sampled = hh.resample_4h(points)
        self.assertLessEqual(len(sampled), 85)
        last_bucket = sampled[-1]["ts"]
        self.assertEqual(last_bucket % hh.INTERVAL_SEC, 0)
        self.assertAlmostEqual(sampled[-1]["dust_pct_mc"], points[-1][
            "dust_pct_mc"])
        # Sparkline tetap jalan di atas titik mentah per jam.
        self.assertIn("<svg", hh.sparkline_svg(points))

    def test_merge_stores_ikut_batas_336(self):
        banyak = {"updated_at": 1, "tokens": {"MINT": {
            "symbol": "TST",
            "points": [{"ts": t, "dust_count": t} for t in range(400)]}}}
        merged = hh.merge_stores(banyak, {"updated_at": 2, "tokens": {}})
        self.assertLessEqual(len(merged["tokens"]["MINT"]["points"]),
                             hh.MAX_POINTS)
        self.assertEqual(len(merged["tokens"]["MINT"]["points"]), 336)


class HolderDataUsabilityTest(unittest.TestCase):
    """Lantai kelayakan data holder (perbaikan watchlist −100%, 2026-09-06).

    Kasus produksi: Helius mati lalu fallback GMGN mengembalikan 20 holder
    dengan ``truncated: False`` → ``dust_count 0`` / ``dust_pct_mc 0.0``.
    Angka itu tidak boleh dipakai sebagai nilai baris, titik grafik,
    pembanding "sejak masuk", maupun pemicu alert.
    """

    def test_sampel_pendek_terbukti_degraded(self):
        self.assertTrue(hh.scan_degraded(
            {"total_fetched": 20, "wallets_analyzed": 19, "dust_count": 0,
             "real_count": 19, "dust_pct_mc": 0.0}))
        self.assertFalse(hh.holders_usable(
            {"total_fetched": 20, "wallets_analyzed": 19}))

    def test_fetch_gagal_nol_wallet_degraded(self):
        self.assertTrue(hh.scan_degraded({"total_fetched": 0,
                                          "wallets_analyzed": 0}))

    def test_scan_lengkap_tetap_usable(self):
        holders = {"total_fetched": 999, "wallets_analyzed": 999,
                   "dust_count": 880, "real_count": 119,
                   "dust_pct_mc": 0.39}
        self.assertFalse(hh.scan_degraded(holders))
        self.assertTrue(hh.holders_usable(holders))

    def test_tanpa_bukti_jumlah_wallet_tidak_ditolak(self):
        # Snapshot skema lama / fixture tanpa info jumlah wallet: tidak ada
        # bukti sampel pendek, jadi perilaku lama dipertahankan.
        self.assertFalse(hh.scan_degraded({"dust_pct_mc": 1.3}))
        self.assertTrue(hh.holders_usable({"dust_pct_mc": 1.3}))
        # dict kosong = tidak ada bukti sama sekali → tidak usable.
        self.assertFalse(hh.holders_usable({}))
        self.assertFalse(hh.holders_usable(None))

    def test_ambang_40_wallet(self):
        self.assertTrue(hh.scan_degraded({"wallets_analyzed":
                                          hh.MIN_USABLE_WALLETS - 1}))
        self.assertFalse(hh.scan_degraded({"wallets_analyzed":
                                           hh.MIN_USABLE_WALLETS}))

    def test_titik_history_dari_scan_pendek_tidak_usable(self):
        pendek = {"ts": 100, "dust_pct_mc": 0.0, "dust_count": 0,
                  "real_count": 19, "holder_count": 19}
        bagus = {"ts": 200, "dust_pct_mc": 1.5, "dust_count": 1_400,
                 "real_count": 596, "holder_count": 1_996}
        ditandai = dict(bagus, ts=300, dust_pct_mc=0.0, degraded=True)
        self.assertFalse(hh.point_usable(pendek))
        self.assertTrue(hh.point_usable(bagus))
        self.assertFalse(hh.point_usable(ditandai))
        self.assertFalse(hh.point_usable({"ts": 400, "dust_pct_mc": None,
                                          "holder_count": 900}))
        self.assertEqual(hh.usable_points([bagus, pendek, ditandai]), [bagus])

    def test_penanda_degraded_ikut_lewat_compact_point(self):
        point = {"ts": 5, "dust_pct_mc": 0.0, "holder_count": 19,
                 "degraded": True}
        self.assertTrue(hh.compact_point(point).get("degraded"))
        self.assertFalse(hh.point_usable(hh.compact_point(point)))

    def test_ingest_menandai_scan_pendek(self):
        store = hh.empty_store()
        pendek = {"symbol": "TST", "marketcap": 50_000, "price": 0.01,
                  "analyzed_at": 100,
                  "holders": {"total_fetched": 20, "wallets_analyzed": 19,
                              "dust_count": 0, "dust_pct_mc": 0.0,
                              "real_count": 19}}
        lengkap = {"symbol": "TST", "marketcap": 50_000, "price": 0.01,
                   "analyzed_at": 100 + 3600,
                   "holders": {"total_fetched": 900, "wallets_analyzed": 900,
                               "dust_count": 700, "dust_pct_mc": 1.2,
                               "real_count": 200}}
        hh.ingest_one(store, "MINT", pendek, now=100)
        hh.ingest_one(store, "MINT", lengkap, now=100 + 3600)
        points = store["tokens"]["MINT"]["points"]
        self.assertTrue(points[0].get("degraded"))
        self.assertNotIn("degraded", points[1])
        # UI hanya melihat titik yang layak → nilai scan pendek tidak ikut.
        self.assertEqual([p["ts"] for p in hh.usable_points(points)],
                         [100 + 3600])


if __name__ == "__main__":
    unittest.main()
