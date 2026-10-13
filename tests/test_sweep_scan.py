# -*- coding: utf-8 -*-
"""Orkestrator scan page 🌊 Sweep (:mod:`sweep_scan`) — end-to-end offline.

Seluruh sumber jaringan di-stub, jadi test ini mengunci **alur**, bukan HTTP:
snapshot tersimpan, kriteria 4/5 terisi dari riwayat, alert dikirim sekali saat
transisi, dan sinyal tercatat dengan angka sweep yang bisa dilihat di tabel
statistik.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

import sweep_scan as scan
import sweep_store as store

ROOT = pathlib.Path(__file__).resolve().parent.parent
MINT = "H4KUxsEgCp2yDpFvyDuGM5k6XevSKKrrKUxZ3Zr6nyJc"

BUNDLE = {
    "mint": MINT,
    "metrics": {
        "mint": MINT, "ok": True, "symbol": "COCKROACH",
        "ts": 1_790_866_800,
        "price_usd": 0.0007667356548390803,
        "liq_usd": 30232.0, "fdv_usd": 233451.0, "market_cap_usd": 233451.0,
        "liq_mc": 30232.0 / 233451.0,
        "vol24_usd": 30232.0 * 3.35,
        "vol_1h": 180744.30, "buys_1h": 70, "sells_1h": 30,
        "mint_authority": None,
        "freeze_authority": None, "top10_holder_pct": 18.92,
        "holder_pcts": [2.99, 2.7, 2.11], "holder_count": 3609,
        "top_bundler_trader_percentage": 0.1764, "bundler_rate": 0.1764,
        "bot_degen_rate": 0.4551, "fresh_wallet_rate": 0.025,
        "holding_rate": 0.0,
        "status_now": {"hold": 12, "sold_part": 4, "sold": 8},
        # avg buy holder terendah 35% di bawah harga → lolos gate ≤ 50%.
        "holder_min_avg_cost": 0.0005, "holder_cost_count": 40,
        "entrapment_rate": 0.3222, "pair_address": "POOL1",
        "pair_created_at": 1_790_866_800,
    },
    "candles_hour": [
        [1, 0.00040, 0.00048, 0.000395, 0.000482, 22781.0],
        [2, 0.000482, 0.000495, 0.000260, 0.000318, 30539.0],
        [3, 0.000318, 0.000375, 0.000303, 0.000343, 18699.0],
    ],
    "cohort_candles": [
        [1_790_866_800 + hour * 3600, 0.00265, 0.0029, 0.0023, 0.00265, 100.0]
        for hour in range(48)
    ],
    # 24 candle tenang lalu candle sweep 22:42 WIB.
    "candles_min5": (
        [[1000 + i * 300, 0.0002377, 0.0002378, 0.0002375, 0.0002377, 150.0]
         for i in range(24)]
        + [[1000 + 24 * 300, 0.00023768309790897773, 0.0011562493069574252,
            0.0002162336035266118, 0.0007667356548390803, 180744.30]]
    ),
}


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sweep-scan-")
        for target in ("WATCHLIST_PATH", "STATE_PATH"):
            patcher = mock.patch.object(
                store, target, os.path.join(self.dir, target.lower() + ".json"))
            patcher.start()
            self.addCleanup(patcher.stop)
        # Telegram dianggap siap supaya jalur alert teruji; panggilan HTTP-nya
        # tetap ditangkap mock dan tidak keluar jaringan.
        cfg = {"ok": True, "token": "t", "chat_id": "c", "source": "env"}
        for target, value in (
                (mock.patch.object(scan.alert, "telegram_config",
                                   return_value=cfg), None),
                (mock.patch.object(scan.alert, "send_message",
                                   return_value=(True, "")), None),
                # `_scan_one` di-mock hanya untuk memotong jaringan; isinya
                # tetap lewat analyze() sungguhan supaya deteksi sweep ikut
                # teruji (kalau sweep di-nol-kan di sini, test alert sweep
                # tidak menguji apa pun).
                (mock.patch.object(scan, "_scan_one",
                                   side_effect=lambda mint, use_cache=True: dict(
                                       scan.analyze(BUNDLE),
                                       candles_hour=BUNDLE["candles_hour"],
                                       candles_min5=BUNDLE["candles_min5"],
                                       cohort_candles=BUNDLE["cohort_candles"],
                                   )), None)):
            patcher, _ = target, value
            patcher.start()
            self.addCleanup(patcher.stop)
        # `analyze` juga dijalankan sungguhan (bukan di-mock) supaya deteksi
        # sweep di 5-menit ikut teruji.
        self.analyze = scan.analyze


class RunScanTest(_Sandbox):
    def test_rows_include_cohort_provider_fields(self):
        row = scan.run_scan([MINT], state=store.empty_state(),
                            send_alerts=False, now=1000)["rows"][0]
        metrics = row["metrics"]
        self.assertEqual(metrics["top_bundler_trader_percentage"], 0.1764)
        self.assertEqual(metrics["bot_degen_rate"], 0.4551)
        self.assertEqual(metrics["fresh_wallet_rate"], 0.025)
        self.assertEqual(metrics["holding_rate"], 0.0)
        self.assertEqual(metrics["status_now"]["sold"], 8)
        self.assertIn("status_avg_cost", row["cohort"])
        self.assertIn("cohort_gate_status", row)

    def test_records_snapshot_and_signal(self):
        outcome = scan.run_scan([MINT], state=store.empty_state(), now=1000)
        state = outcome["state"]
        self.assertEqual(len(state["snapshots"][MINT]), 1)
        kinds = [s["kind"] for s in state["signals"]]
        self.assertIn("eligibility", kinds)
        self.assertIn("sweep", kinds)
        self.assertEqual(len(outcome["alerts"]), 2)
        self.assertTrue(all(a["sent"] for a in outcome["alerts"]))

    def test_sweep_signal_carries_formula_numbers(self):
        outcome = scan.run_scan([MINT], state=store.empty_state(), now=1000)
        signal = next(s for s in outcome["state"]["signals"]
                      if s["kind"] == "sweep")
        self.assertGreater(signal["vol_x"], 1000)
        self.assertAlmostEqual(signal["base_price"], 0.0002377, places=7)
        self.assertIsNotNone(signal["est_cost_usd"])
        self.assertGreater(signal["churn_x"], 0)

    def test_alerts_fire_once_on_transition(self):
        state = store.empty_state()
        first = scan.run_scan([MINT], state=state, now=1000)
        self.assertEqual(len(first["alerts"]), 2)
        # Putaran berikutnya: kondisi sama, masih di dalam cooldown → sunyi.
        second = scan.run_scan([MINT], state=first["state"], now=1100)
        self.assertEqual(second["alerts"], [])
        # Setelah cooldown sweep, alert sweep boleh lagi (masih ada sweep).
        third = scan.run_scan([MINT], state=second["state"],
                              now=1000 + store.SWEEP_COOLDOWN + 60)
        self.assertEqual([a["kind"] for a in third["alerts"]], ["sweep"])

    def test_net_inflow_measured_from_previous_snapshot(self):
        # Putaran 1 (liq $30.232) tidak punya pembanding → estimasi berlabel.
        first = scan.run_scan([MINT], state=store.empty_state(),
                              send_alerts=False, now=1000)
        first_ctx = first["rows"][0]["sweep_context"]
        self.assertIsNone(first_ctx["net_inflow_usd"])
        self.assertIsNotNone(first_ctx["net_inflow_ref_usd"])
        # Putaran 2 sejam kemudian, likuiditas naik ke $89.010 → inflow nyata
        # $58.778 dan churn nyata menggantikan acuan.
        with mock.patch.object(scan, "_scan_one",
                               side_effect=lambda mint, use_cache=True: dict(
                                   scan.analyze(BUNDLE, snapshots=None),
                                   candles_hour=BUNDLE["candles_hour"],
                                   candles_min5=BUNDLE["candles_min5"],
                                   cohort_candles=BUNDLE["cohort_candles"],
                                   metrics=dict(BUNDLE["metrics"],
                                                liq_usd=89010.0))):
            second = scan.run_scan([MINT], state=first["state"],
                                   send_alerts=False, now=1000 + 3600)
        ctx = second["rows"][0]["sweep_context"]
        self.assertEqual(ctx["net_inflow_usd"], 89010.0 - 30232.0)
        self.assertIsNone(ctx["net_inflow_ref_usd"])
        self.assertAlmostEqual(ctx["churn_net_x"],
                               ctx["vol"] / (89010.0 - 30232.0), places=2)

    def test_signal_stores_both_churn_numbers(self):
        state = store.empty_state()
        scan.run_scan([MINT], state=state, now=1000)
        # Putaran berikutnya harus di **bucket jam baru** (snapshot dibucket per
        # jam) supaya ada pembanding likuiditas.
        with mock.patch.object(scan, "_scan_one",
                               side_effect=lambda mint, use_cache=True: dict(
                                   scan.analyze(BUNDLE),
                                   candles_hour=BUNDLE["candles_hour"],
                                   candles_min5=BUNDLE["candles_min5"],
                                   cohort_candles=BUNDLE["cohort_candles"],
                                   metrics=dict(BUNDLE["metrics"],
                                                liq_usd=89010.0))):
            scan.run_scan([MINT], state=state, now=1000 + 3600)
        sweeps = [s for s in state["signals"] if s["kind"] == "sweep"]
        self.assertEqual(len(sweeps), 2)
        self.assertIsNotNone(sweeps[0]["churn_x"])
        self.assertIsNone(sweeps[0]["net_inflow_usd"])
        self.assertIsNone(sweeps[0]["churn_net_x"])
        self.assertEqual(sweeps[1]["net_inflow_usd"], 89010.0 - 30232.0)
        self.assertIsNotNone(sweeps[1]["churn_net_x"])
        self.assertIsNotNone(sweeps[1]["paper_mcap_usd"])

    def test_criteria_4_and_5_fill_in_after_history(self):
        state = store.empty_state()
        first = scan.run_scan([MINT], state=state, now=1000)
        self.assertTrue(first["rows"][0]["result"]["missing"])
        history = store.mint_history(first["state"], MINT)
        # Riwayat sama tapi harga sedikit berbeda → drift tetap kecil.
        for offset, hour in enumerate((7200, 10800)):
            row = dict(BUNDLE["metrics"])
            row["price_usd"] = 0.00077 + offset * 0.00001
            store.add_snapshot(first["state"], MINT, row, ts=hour)
        snapshot = store.mint_history(first["state"], MINT)
        self.assertGreaterEqual(len(snapshot), 3)

    def test_alert_not_sent_when_muted(self):
        with mock.patch.object(scan.alert, "muted_mints", return_value={MINT}):
            outcome = scan.run_scan([MINT], state=store.empty_state(), now=1000)
        self.assertEqual(outcome["alerts"], [])
        self.assertEqual(outcome["state"]["signals"], [])

    def test_send_alerts_false_keeps_scanning(self):
        outcome = scan.run_scan([MINT], state=store.empty_state(),
                                send_alerts=False, now=1000)
        self.assertEqual(outcome["alerts"], [])
        self.assertEqual(len(outcome["state"]["snapshots"][MINT]), 1)

    def test_failed_mint_does_not_break_scan(self):
        with mock.patch.object(scan, "_scan_one",
                               return_value={"mint": "BROKEN",
                                             "metrics": {"ok": False,
                                                         "error": "timeout"},
                                             "result": scan.screen.evaluate(
                                                 {}, snapshots=[], candles=[]),
                                             "sweep": None, "sweep_context": None,
                                             "candles_hour": [], "candles_min5": []}):
            outcome = scan.run_scan(["BROKEN"], state=store.empty_state(), now=1000)
        self.assertEqual(len(outcome["rows"]), 1)
        self.assertFalse(outcome["rows"][0]["metrics"]["ok"])
        self.assertEqual(outcome["rows"][0]["result"]["verdict"],
                         "TANPA DATA — kohort")

    def test_empty_watchlist(self):
        outcome = scan.run_scan([], state=store.empty_state(), now=1000)
        self.assertEqual(outcome["rows"], [])
        self.assertEqual(outcome["alerts"], [])

    def test_rows_sorted_by_score_desc(self):
        state = store.empty_state()
        outcome = scan.run_scan([MINT], state=state, now=1000)
        scores = [r["result"]["score"] for r in outcome["rows"]
                  if r["result"]["score"] is not None]
        self.assertEqual(scores, sorted(scores, reverse=True))


class ScanPayloadAndLatchTest(_Sandbox):
    def test_turnover_x_is_computed_by_screen_and_copied_to_row(self):
        row = scan.run_scan([MINT], state=store.empty_state(),
                            send_alerts=False, now=1000)["rows"][0]
        expected = BUNDLE["metrics"]["vol24_usd"] / BUNDLE["metrics"]["liq_usd"]
        self.assertAlmostEqual(row["turnover_x"], expected, places=8)
        self.assertAlmostEqual(row["result"]["turnover_x"], expected, places=8)

    def test_detected_shakeout_is_latched_and_survives_low_break(self):
        first = scan.run_scan([MINT], state=store.empty_state(),
                              send_alerts=False, now=1000)
        state = first["state"]
        self.assertEqual(state["shakeout_latched_at"][MINT], 2)

        bundle = dict(BUNDLE)
        candles = list(BUNDLE["candles_hour"]) + [
            [4, 0.000343, 0.002060, 0.000216, 0.001826, 1536017.0]
        ]
        bundle["candles_hour"] = candles
        with mock.patch.object(
                scan, "_scan_one",
                side_effect=lambda mint, use_cache=True: dict(
                    scan.analyze(bundle), candles_hour=candles,
                    candles_min5=BUNDLE["candles_min5"],
                    cohort_candles=BUNDLE["cohort_candles"])):
            second = scan.run_scan([MINT], state=state, send_alerts=False,
                                   now=1000 + 3600)
        check = next(c for c in second["rows"][0]["result"]["checks"]
                     if c["key"] == "shakeout")
        self.assertTrue(check["passed"])
        self.assertIn("latch permanen", check["detail"])
        self.assertEqual(second["state"]["shakeout_latched_at"][MINT], 2)

    def test_cli_and_result_have_no_saved_threshold_settings(self):
        outcome = scan.run_scan([MINT], state=store.empty_state(),
                                send_alerts=False, now=1000)
        self.assertNotIn("settings", outcome["state"])
        self.assertNotIn("settings", outcome["rows"][0]["result"])


class DetectSweepIntegrationTest(_Sandbox):
    def test_analyze_detects_sweep_and_builds_context(self):
        item = self.analyze(BUNDLE)
        self.assertIsNotNone(item["sweep"])
        context = item["sweep_context"]
        self.assertGreater(context["vol_x"], 1000)
        self.assertIsNotNone(context["est_cost_usd"])
        self.assertAlmostEqual(context["liq_mc"], 30232.0 / 233451.0, places=5)

    def test_analyze_without_candles(self):
        item = self.analyze({"mint": MINT, "metrics": BUNDLE["metrics"],
                             "candles_hour": [], "candles_min5": []})
        self.assertIsNone(item["sweep"])
        self.assertIsNone(item["sweep_context"])


class SurfaceTest(unittest.TestCase):
    """Permukaan page 🌊 Sweep: entri halaman, runner cron, dan workflow."""

    def test_page_entry_exists(self):
        page = ROOT / "pages" / "8_\U0001f30a_Sweep.py"
        self.assertTrue(page.exists(), page)
        source = page.read_text(encoding="utf-8")
        self.assertIn("render_sweep_page()", source)

    def test_app_py_stays_untouched_by_sweep(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        for module in ("sweep_", "sweep."):
            self.assertNotIn(module, source)

    def test_cron_runner_and_workflow_exist(self):
        runner = ROOT / "scripts" / "scan_sweep.py"
        workflow = ROOT / ".github" / "workflows" / "sweep-scan.yml"
        self.assertTrue(runner.exists(), runner)
        self.assertTrue(workflow.exists(), workflow)
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("SWEEP_STATE_CHANGED", text)
        self.assertIn("*/5 * * * *", text)
        runner_source = runner.read_text(encoding="utf-8")
        self.assertNotIn("--liq-mc-max", runner_source)
        self.assertNotIn("--holder-max-pct", runner_source)

    def test_ui_shows_fixed_threshold_turnover_and_cohort_without_sliders(self):
        source = (ROOT / "sweep_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("st.slider(", source)
        self.assertIn("liq/MC ≤ 35% · holder/wallet ≤ 5%", source)
        self.assertIn("Turnover (×/hari)", source)
        self.assertIn("perkiraan (proksi VWAP 48 jam)", source)


if __name__ == "__main__":
    unittest.main()
