"""Coverage dasar scanner cron analisis holder."""
from __future__ import annotations

import time
import types
import unittest
from unittest import mock

from scripts.scan_holders import scan_watchlist

# Catatan: seluruh modul ini tetap offline karena ``tests/__init__.py``
# men-stub ``robinhood_watchlist.load_watchlist/load_status/load_history``
# (kill-switch suite). Test yang menguji blok Robinhood menimpa stub-nya
# sendiri lewat ``mock.patch.object`` — termasuk ScanCadenceTest di bawah.


class ScanWatchlistTest(unittest.TestCase):
    def test_collects_success_and_skips_failures(self):
        def fake(ca, *args, **kwargs):
            if ca == "BAD":
                raise RuntimeError("gagal")
            return {"ca": ca, "symbol": args[0] if args else "?"}

        watchlist = {
            "GOOD": {"symbol": "GD"},
            "BAD": {"symbol": "BD"},
        }
        with mock.patch("scripts.scan_holders.analyze_token",
                        side_effect=fake):
            out = scan_watchlist(watchlist, workers=1)
        self.assertEqual(set(out), {"GOOD"})

    def test_empty_watchlist_returns_empty(self):
        self.assertEqual(scan_watchlist({}), {})

    def test_uses_passed_history_and_tracks_alert_wallets(self):
        store = {"tokens": {"GOOD": {
            "cohort": {"balances": {"COHORT": 5.0}},
            "alert_state": {
                "baseline": {"balances": {"BASE": 1.0}},
                "rolling": {"balances": {"ROLL": 2.0}},
            },
        }}}
        with mock.patch("scripts.scan_holders.load_holder_history") as load, \
                mock.patch("scripts.scan_holders.analyze_token",
                           return_value={"ca": "GOOD"}) as analyze:
            out = scan_watchlist(
                {"GOOD": {"symbol": "GD"}}, workers=1,
                history_store=store)
        self.assertEqual(out, {"GOOD": {"ca": "GOOD"}})
        load.assert_not_called()
        kwargs = analyze.call_args.kwargs
        self.assertEqual(kwargs["cohort_addrs"], ["COHORT"])
        self.assertEqual(set(kwargs["tracked_wallet_addrs"]), {"BASE", "ROLL"})


class DurableStoreBackupTest(unittest.TestCase):
    """Cron harus memulihkan + membackup store penuh (holder_history.json.gz)."""

    ANALYSES = {"A": {"symbol": "AA", "analyzed_at": 200,
                      "holders": {"total_fetched": 5, "dust_count": 2,
                                  "dust_pct_mc": 0.4}}}

    def _durable(self):
        return {"updated_at": 150, "tokens": {"OLD": {
            "symbol": "OLD",
            "points": [{"ts": 150, "dust_count": 9, "dust_pct_mc": 0.9}],
            "baseline": {"ts": 100, "dust_count": 7},
            "cohort": {"frozen_at": 120, "balances": {"W": 1.0}},
            "alert_state": {"rolling": {"ts": 150, "balances": {"W": 1.0}},
                            "sent_event_ids": ["e0"]},
        }}}

    def test_backup_durable_dipulihkan_dan_digabung(self):
        captured = {}
        code = MainExitCodeTest()._run(
            self.ANALYSES, publish_ok=True, durable=self._durable(),
            capture=captured)
        self.assertEqual(code, 0)
        store = captured["alerts"].call_args.args[1]
        # token dari backup durable ikut terbawa ke run ini
        self.assertIn("OLD", store.get("tokens") or {})
        self.assertEqual(store["tokens"]["OLD"]["baseline"]["ts"], 100)
        self.assertEqual(store["tokens"]["OLD"]["alert_state"]["sent_event_ids"],
                         ["e0"])

    def test_backup_dipublish_setelah_status(self):
        captured = {}
        code = MainExitCodeTest()._run(
            self.ANALYSES, publish_ok=True, capture=captured)
        self.assertEqual(code, 0)
        backup = captured["backup"]
        self.assertEqual(backup.call_count, 1)
        self.assertTrue(backup.call_args.kwargs.get("push"))
        # store yang dibackup = hasil ingest_many (state terbaru)
        self.assertEqual(backup.call_args.args[0], {"tokens": {}})

    def test_no_push_juga_menonaktifkan_backup(self):
        captured = {}
        code = MainExitCodeTest()._run(
            self.ANALYSES, publish_ok=True, argv=["--no-push"],
            capture=captured)
        self.assertEqual(code, 0)
        self.assertFalse(captured["backup"].call_args.kwargs.get("push"))

    def test_backup_gagal_tidak_membuat_cron_merah(self):
        code = MainExitCodeTest()._run(
            self.ANALYSES, publish_ok=True,
            backup={"ok": False, "pushed": False, "bytes": 0, "pruned": [],
                    "over_budget": False, "error": "github push failed"})
        self.assertEqual(code, 0)

    def test_publish_status_gagal_tetap_merah_meski_backup_ok(self):
        code = MainExitCodeTest()._run(
            self.ANALYSES, publish_ok=False,
            backup={"ok": True, "pushed": True, "bytes": 10, "pruned": [],
                    "over_budget": False, "error": ""})
        self.assertEqual(code, 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class MainExitCodeTest(unittest.TestCase):
    """Cron harus MERAH bila data holder/publish gagal (bukan hijau palsu)."""

    def _run(self, analyses, publish_ok=None, watchlist=None, durable=None,
             backup=None, argv=None, local_store=None, capture=None):
        """Jalankan ``main()`` dengan semua I/O di-mock.

        ``durable`` = store hasil pull backup (None = tidak ada backup),
        ``backup`` = return value ``publish_holder_history``,
        ``capture`` = dict yang diisi mock supaya bisa diassert pemanggilnya.
        ``merge_stores``/``pull_holder_history`` asli tetap dipakai bila tidak
        di-mock, jadi wiring cron benar-benar teruji.
        """
        import scripts.scan_holders as mod
        wl = ({"A": {"symbol": "AA", "source": "meteora"}}
              if watchlist is None else watchlist)
        store = {"tokens": {}} if local_store is None else local_store
        backup_result = ({"ok": True, "pushed": True, "bytes": 1234,
                          "pruned": [], "over_budget": False, "error": ""}
                         if backup is None else backup)
        with mock.patch.object(mod, "load_watchlist", return_value=wl), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "load_holder_history",
                                  return_value=store), \
                mock.patch.object(mod, "pull_holder_history",
                                  return_value=durable), \
                mock.patch.object(mod, "seed_from_status",
                                  side_effect=lambda s, _st: s), \
                mock.patch.object(mod, "scan_watchlist",
                                  return_value=analyses), \
                mock.patch.object(mod, "ingest_many",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "publish_holder_status",
                                  return_value={"updated_at": 1}), \
                mock.patch.object(mod, "publish_holder_history",
                                  return_value=backup_result) as backup_mock, \
                mock.patch.object(mod, "process_holder_alerts",
                                  return_value=[]) as alert_mock, \
                mock.patch.object(mod, "last_publish_result",
                                  return_value={"ok": publish_ok,
                                                "error": "x"}):
            code = mod.main(argv if argv is not None else [])
        if isinstance(capture, dict):
            capture["backup"] = backup_mock
            capture["alerts"] = alert_mock
        return code

    def test_ok(self):
        out = self._run({"A": {"symbol": "AA", "holders": {
            "total_fetched": 5, "dust_count": 1}}}, publish_ok=True)
        self.assertEqual(out, 0)

    def test_zero_holders_fails(self):
        out = self._run({"A": {"symbol": "AA", "holders": {
            "total_fetched": 0}}}, publish_ok=True)
        self.assertEqual(out, 2)

    def test_no_analysis_fails(self):
        self.assertEqual(self._run({}, publish_ok=True), 2)

    def test_publish_failure_fails(self):
        out = self._run({"A": {"symbol": "AA", "holders": {
            "total_fetched": 5}}}, publish_ok=False)
        self.assertEqual(out, 3)

    def test_no_push_ignores_publish(self):
        import scripts.scan_holders as mod
        with mock.patch.object(mod, "load_watchlist",
                               return_value={"A": {"source": "meteora"}}), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "load_holder_history",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "pull_holder_history",
                                  return_value=None), \
                mock.patch.object(mod, "publish_holder_history",
                                  return_value={"pushed": False}), \
                mock.patch.object(mod, "seed_from_status",
                                  side_effect=lambda s, _st: s), \
                mock.patch.object(mod, "scan_watchlist", return_value={
                    "A": {"holders": {"total_fetched": 1}}}), \
                mock.patch.object(mod, "ingest_many",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "publish_holder_status",
                                  return_value={}):
            self.assertEqual(mod.main(["--no-push"]), 0)

    def test_alert_evaluation_happens_before_latest_snapshot_ingest(self):
        import scripts.scan_holders as mod
        store = {"tokens": {}}
        analyses = {"A": {"symbol": "AA", "analyzed_at": 100,
                           "holders": {"total_fetched": 1,
                                       "dust_pct_mc": 0.4}}}
        order = []
        seen = {}

        def process(items, supplied_store, **kwargs):
            # Store yang dipakai aturan alert adalah store hasil merge
            # (lokal + backup durable), dan objek yang SAMA harus mengalir ke
            # ingest_many lalu publish_holder_status.
            self.assertIsNotNone(supplied_store)
            self.assertIsInstance(supplied_store.get("tokens"), dict)
            seen["store"] = supplied_store
            self.assertEqual(items, analyses)
            # Scan 5 menit LP: tanpa konteks volume (fitur 4 jam dimatikan).
            self.assertIsNone(kwargs.get("context_provider"))
            self.assertFalse(kwargs.get("volume_rules"))
            order.append("alert")
            supplied_store["alert_evaluated"] = True
            return []

        def ingest(items, **kwargs):
            self.assertIs(kwargs["store"], seen["store"])
            self.assertTrue(kwargs["store"]["alert_evaluated"])
            order.append("ingest")
            return kwargs["store"]

        def publish(*_args, **kwargs):
            self.assertIs(kwargs["history_store"], seen["store"])
            self.assertTrue(kwargs["history_store"]["alert_evaluated"])
            # Cache konteks provider diteruskan supaya volatilitas/volume
            # tersimpan di holder_status berdampingan dust % MC.
            self.assertIsInstance(kwargs.get("contexts"), dict)
            order.append("publish")
            return {"updated_at": 100}

        with mock.patch.object(mod, "load_watchlist",
                               return_value={"A": {"symbol": "AA", "source": "meteora"}}), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "load_holder_history",
                                  return_value=store), \
                mock.patch.object(mod, "pull_holder_history",
                                  return_value=None), \
                mock.patch.object(mod, "publish_holder_history",
                                  return_value={"pushed": True}), \
                mock.patch.object(mod, "seed_from_status",
                                  side_effect=lambda current, _status: current), \
                mock.patch.object(mod, "scan_watchlist",
                                  return_value=analyses), \
                mock.patch.object(mod, "process_holder_alerts",
                                  side_effect=process), \
                mock.patch.object(mod, "ingest_many", side_effect=ingest), \
                mock.patch.object(mod, "publish_holder_status",
                                  side_effect=publish):
            self.assertEqual(mod.main(["--no-push"]), 0)
        self.assertEqual(order, ["alert", "ingest", "publish"])


class AlertScopeWiringTest(unittest.TestCase):
    """Cron meneruskan state watchlist ke rule 🚨 WAKTUNYA GANTI STRATEGI.

    Sejak 2026-09-11 notifikasinya satu dan tidak ada lagi **scope flag**
    (``lp_mints``/``high_mints``/``volume_rules``): tiap token yang di-scan
    run ini dievaluasi. Yang tetap harus diteruskan adalah
    ``watchlist_meta`` — dipakai untuk membuang marker episode lama ketika
    token di-add ulang ke watchlist.
    """

    def test_meta_diteruskan_dan_scope_flag_hilang(self):
        captured = {}
        watchlist = {
            "LpMint11111111111111111111111111111111111":
                {"symbol": "LPT", "source": "meteora"},
            "RegMint22222222222222222222222222222222222":
                {"symbol": "REG", "source": "degen"},
        }
        analyses = {
            "LpMint11111111111111111111111111111111111":
                {"symbol": "LPT", "holders": {"total_fetched": 5}},
            "RegMint22222222222222222222222222222222222":
                {"symbol": "REG", "holders": {"total_fetched": 5}},
        }
        code = MainExitCodeTest()._run(analyses, publish_ok=True,
                                       watchlist=watchlist, capture=captured)
        self.assertEqual(code, 0)
        kwargs = captured["alerts"].call_args.kwargs
        self.assertEqual(kwargs.get("watchlist_meta"),
                         {"LpMint11111111111111111111111111111111111":
                          {"symbol": "LPT", "source": "meteora"}})
        # (Scope lane = token LP saja — dijaga ScanLaneScopeTest.)
        for gone in ("lp_mints", "high_mints", "volume_rules"):
            self.assertNotIn(gone, kwargs)
        # Run LP biasa (tanpa --full) tidak menggeser anchor peta wallet.
        self.assertFalse(kwargs.get("advance_anchors"))


class CronFullScanTest(unittest.TestCase):
    """Sejak 2026-09-05 cron scan holder **FULL** + simpan detail.

    Tiap token watchlist (sudah ada maupun baru ditambahkan) menjadi titik
    awal holder analytic: ``ingest_many(detail=True)`` menulis baseline pada
    scan pertama, lalu kronologi antar-scan FULL terakumulasi otomatis.
    """

    def test_main_ingests_detail_true(self):
        import scripts.scan_holders as mod
        import holder_history as hh
        seen = {}
        analyses = {"A": {"symbol": "AA", "holders": {"total_fetched": 5}}}
        with mock.patch.object(mod, "load_watchlist",
                               return_value={"A": {"symbol": "AA", "source": "meteora"}}), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "load_holder_history",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "pull_holder_history",
                                  return_value=None), \
                mock.patch.object(mod, "seed_from_status",
                                  side_effect=lambda s, _st: s), \
                mock.patch.object(mod, "scan_watchlist",
                                  side_effect=lambda *a, **kw:
                                  (seen.update(max_wallets=kw.get(
                                      "max_wallets")) or analyses)), \
                mock.patch.object(mod, "ingest_many",
                                  side_effect=lambda *a, **kw:
                                  (seen.update(detail=kw.get("detail")) or
                                   {"tokens": {}})), \
                mock.patch.object(mod, "process_holder_alerts",
                                  return_value=[]), \
                mock.patch.object(mod, "publish_holder_status",
                                  return_value={"updated_at": 1}), \
                mock.patch.object(mod, "publish_holder_history",
                                  return_value={"ok": True, "pushed": True,
                                                "bytes": 1, "pruned": [],
                                                "over_budget": False,
                                                "error": ""}), \
                mock.patch.object(mod, "last_publish_result",
                                  return_value={"ok": True, "error": ""}):
            self.assertEqual(mod.main([]), 0)
        self.assertEqual(seen.get("max_wallets"), hh.FULL_SCAN_MAX_WALLETS)
        # Cron auto 5 menit: pencatatan holder, bukan kronologi FULL.
        self.assertFalse(seen.get("detail"))

    def test_scan_watchlist_defaults_to_full(self):
        import holder_history as hh
        seen = {}
        with mock.patch("scripts.scan_holders.analyze_token",
                        side_effect=lambda *a, **kw:
                        (seen.update(kw) or {"ca": "A"})):
            out = scan_watchlist({"A": {"symbol": "AA"}}, workers=1)
        self.assertEqual(set(out), {"A"})
        self.assertEqual(seen.get("max_wallets"), hh.FULL_SCAN_MAX_WALLETS)
        self.assertTrue(seen.get("detail", True))

    def test_scan_watchlist_detail_false_skips_tracked_wallets(self):
        store = {"tokens": {"A": {
            "cohort": {"balances": {"COHORT": 5.0}},
            "alert_state": {"baseline": {"balances": {"BASE": 1.0}}},
        }}}
        seen = {}
        with mock.patch("scripts.scan_holders.analyze_token",
                        side_effect=lambda *a, **kw:
                        (seen.update(kw) or {"ca": "A"})):
            scan_watchlist({"A": {"symbol": "AA"}}, workers=1,
                           history_store=store, detail=False)
        self.assertEqual(seen.get("cohort_addrs"), [])
        self.assertEqual(seen.get("tracked_wallet_addrs"), [])
        self.assertFalse(seen.get("detail"))


class RobinhoodAlertWiringTest(unittest.TestCase):
    """Cron juga mengevaluasi notifikasi 🚨 untuk watchlist Robinhood LP.

    Watchlist RH tidak dipecah Chart LP seperti Meteora, jadi seluruh token
    `0x…` yang di-scan dievaluasi — rule-nya sama persis dengan lane Solana
    (dust ≥ 0,06% MC, tanpa gerbang volume).
    """

    def test_rh_watchlist_diteruskan_keproses_alerts(self):
        import scripts.scan_holders as mod
        import robinhood_watchlist as rw_mod
        ca = "0x" + "a" * 40
        rh_watch = {ca: {"symbol": "VLAD", "source": "manual"}}
        rh_analyses = {ca: {"symbol": "VLAD", "analyzed_at": 100,
                            "holders": {"total_fetched": 5,
                                        "dust_pct_mc": 0.4}}}
        seen = {}

        def _process(items, store, **kwargs):
            seen["meta"] = kwargs.get("watchlist_meta")
            seen["advance"] = kwargs.get("advance_anchors")
            seen["kwargs"] = kwargs
            self.assertEqual(items, rh_analyses)
            return []

        with mock.patch.object(mod, "load_watchlist", return_value={}), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "load_holder_history",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "pull_holder_history",
                                  return_value=None), \
                mock.patch.object(mod, "seed_from_status",
                                  side_effect=lambda s, _st: s), \
                mock.patch.object(mod, "publish_holder_status",
                                  return_value={"updated_at": 1}), \
                mock.patch.object(mod, "last_publish_result",
                                  return_value={"ok": True, "error": ""}), \
                mock.patch.object(rw_mod, "load_watchlist",
                                  return_value=rh_watch), \
                mock.patch.object(rw_mod, "load_status",
                                  return_value={"updated_at": None,
                                                "tokens": {}}), \
                mock.patch.object(rw_mod, "load_history",
                                  return_value={"tokens": {}}), \
                mock.patch.object(rw_mod, "scan_watchlist",
                                  return_value=rh_analyses), \
                mock.patch.object(rw_mod, "publish_scan",
                                  return_value={"updated_at": 2}), \
                mock.patch.object(mod, "process_holder_alerts",
                                  side_effect=_process):
            self.assertEqual(mod.main([]), 0)
        self.assertEqual(seen.get("meta"), rh_watch)
        self.assertFalse(seen.get("advance"))
        for gone in ("lp_mints", "high_mints", "volume_rules"):
            self.assertNotIn(gone, seen["kwargs"])


class ScanLaneScopeTest(unittest.TestCase):
    """Cron 2026-09-07: **lane LP saja** (Chart LP Meteora + Robinhood LP).

    - token watchlist biasa (non-LP) tidak pernah ikut scan cron;
    - snapshot dipublish **tanpa** ``merge_status`` (tidak ada baris token
      biasa yang perlu diwariskan lagi);
    - backup durable dibatasi token LP aktif (``keep_mints``);
    - ``--full`` menghidupkan ``detail=True`` (baseline + kronologi wallet).
    """

    def _run(self, argv, watchlist, capture):
        import scripts.scan_holders as mod
        with mock.patch.object(mod, "load_watchlist",
                               return_value=watchlist), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"updated_at": 111,
                                                "tokens": {}}) as status_mock, \
                mock.patch.object(mod, "load_holder_history",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "pull_holder_history",
                                  return_value=None), \
                mock.patch.object(mod, "seed_from_status",
                                  side_effect=lambda s, _st: s), \
                mock.patch.object(mod, "scan_watchlist",
                                  side_effect=lambda due, **kw:
                                      (capture.update(scan_kwargs=kw) or
                                       {mint: {"symbol": "X", "holders": {
                                           "total_fetched": 1}}
                                        for mint in due})) as scan_mock, \
                mock.patch.object(mod, "ingest_many",
                                  return_value={"tokens": {}}) as ingest_mock, \
                mock.patch.object(mod, "publish_holder_status",
                                  return_value={"updated_at": 1}) as pub_mock, \
                mock.patch.object(mod, "publish_holder_history",
                                  return_value={"pushed": True, "bytes": 1,
                                                "pruned": [], "over_budget": False,
                                                "dropped_tokens": 0,
                                                "error": ""}) as backup_mock, \
                mock.patch.object(mod, "process_holder_alerts",
                                  return_value=[]), \
                mock.patch.object(mod, "last_publish_result",
                                  return_value={"ok": True, "error": ""}):
            code = mod.main(list(argv))
        capture["scan_args"] = scan_mock.call_args
        capture["pub_kwargs"] = pub_mock.call_args.kwargs
        capture["pub_args"] = pub_mock.call_args.args
        capture["backup_kwargs"] = backup_mock.call_args.kwargs
        capture["ingest_kwargs"] = ingest_mock.call_args.kwargs
        capture["current_status"] = status_mock.return_value
        return code

    WL = {"LpMint11111111111111111111111111111111111":
          {"symbol": "LP", "source": "meteora"},
          "Watch11111111111111111111111111111111111":
          {"symbol": "REG", "source": "manual"}}

    def test_hanya_token_lp_yang_discan(self):
        capture: dict = {}
        code = self._run([], self.WL, capture)
        self.assertEqual(code, 0)
        self.assertEqual(set(capture["scan_args"].args[0]),
                         {"LpMint11111111111111111111111111111111111"})
        # Snapshot + ingest + backup semuanya dibatasi lane LP.
        self.assertEqual(capture["pub_args"][1],
                         {"LpMint11111111111111111111111111111111111":
                          {"symbol": "LP", "source": "meteora"}})
        self.assertEqual(capture["backup_kwargs"].get("keep_mints"),
                         {"LpMint11111111111111111111111111111111111"})

    def test_tanpa_merge_status_dan_detail_off(self):
        capture: dict = {}
        code = self._run([], self.WL, capture)
        self.assertEqual(code, 0)
        # Tidak ada lagi pewarisan baris token watchlist biasa.
        self.assertNotIn("merge_status", capture["pub_kwargs"])
        # Cron = pencatatan titik holder, bukan kronologi FULL.
        self.assertFalse(capture["scan_kwargs"].get("detail"))
        self.assertFalse(capture["ingest_kwargs"].get("detail"))

    def test_flag_full_menyalakan_detail(self):
        capture: dict = {}
        code = self._run(["--full", "--ignore-gap"], self.WL, capture)
        self.assertEqual(code, 0)
        self.assertTrue(capture["scan_kwargs"].get("detail"))
        self.assertTrue(capture["ingest_kwargs"].get("detail"))
        # ``--full`` tetap lane LP saja — watchlist biasa tidak ikut.
        self.assertEqual(set(capture["scan_args"].args[0]),
                         {"LpMint11111111111111111111111111111111111"})

    def test_alias_scope_all_lama_dianggap_full(self):
        """Workflow lama masih mengirim ``--scope all`` — tidak boleh crash.

        Berkas workflow tidak bisa ditulis bot (403 tanpa izin ``workflows``),
        jadi input ``scan_all`` yang mengirim ``--scope all --ignore-gap``
        tetap harus jalan sampai ``daily-effort-5menit.yml`` disalin manual.
        """
        capture: dict = {}
        code = self._run(["--scope", "all", "--ignore-gap"], self.WL, capture)
        self.assertEqual(code, 0)
        self.assertTrue(capture["scan_kwargs"].get("detail"))
        self.assertEqual(set(capture["scan_args"].args[0]),
                         {"LpMint11111111111111111111111111111111111"})

    def test_alias_scope_fast_lama_tetap_lane_lp(self):
        capture: dict = {}
        code = self._run(["--scope", "fast"], self.WL, capture)
        self.assertEqual(code, 0)
        self.assertFalse(capture["scan_kwargs"].get("detail"))
        self.assertEqual(set(capture["scan_args"].args[0]),
                         {"LpMint11111111111111111111111111111111111"})


class ScanCadenceTest(unittest.TestCase):
    """Cadens sejak 2026-09-06: KEDUA lane LP di-scan tiap run (±5 menit).

    User minta **watchlist Robinhood** di-fetch tiap 5 menit "supaya exit bisa
    lebih awal", lalu menambah "iya untuk watchlist meteora juga, per 5 menit,
    biar perubahan holder bisa langsung ketahuan". Jadi tiap run cron menarik
    kedua chain; yang sengaja TIDAK ikut dipercepat: watchlist biasa (slot 4
    jam, DIMATIKAN). Pengingat ⚡ Telegram = tiap scan 5 menit. Hemat kuota Helius
    tetap mungkin lewat ``LP_SCAN_RUN_MULTIPLIER`` (gate :func:`lp_slot_due`).
    """

    def test_konstanta_kadens(self):
        import scripts.scan_holders as mod
        self.assertEqual(mod.RH_FAST_SCAN_INTERVAL_SEC, 5 * 60)
        self.assertEqual(mod.RUN_SCAN_INTERVAL_SEC,
                         mod.RH_FAST_SCAN_INTERVAL_SEC)
        # Chart LP Meteora = laju yang sama dengan Robinhood LP & interval run.
        self.assertEqual(mod.METEORA_LP_SCAN_INTERVAL_SEC, 5 * 60)
        self.assertEqual(mod.LP_SCAN_INTERVAL_SEC, mod.RUN_SCAN_INTERVAL_SEC)
        self.assertEqual(mod.lp_slot_sec(), mod.RUN_SCAN_INTERVAL_SEC)
        self.assertEqual(mod.LP_SCAN_RUN_MULTIPLIER, 1)
        # Lane watchlist biasa (slot 4 jam + catch-up) dilepas dari cron
        # 2026-09-07: tidak boleh ada lagi pintu masuk yang menyalakannya.
        for name in ("REGULAR_SCAN_INTERVAL_SEC", "REGULAR_SLOTS",
                     "REGULAR_CATCHUP_SEC", "REGULAR_SCAN_ENABLED",
                     "FAST_SCAN_INTERVAL_SEC"):
            self.assertFalse(hasattr(mod, name), name)
        for name in ("regular_slot_due", "token_needs_scan",
                     "build_scan_plan"):
            self.assertFalse(hasattr(mod, name), name)
        # Invarian penting: gate run ganda WAJIB lebih kecil dari kadens run,
        # kalau tidak lane Robinhood 5 menit dibungkam gate-nya sendiri.
        self.assertLess(mod.MIN_RUN_GAP_SEC, mod.RUN_SCAN_INTERVAL_SEC)
        self.assertEqual(mod.MIN_RUN_GAP_SEC, 4 * 60)

    def test_lp_slot_due_default_setiap_run(self):
        import scripts.scan_holders as mod
        run = mod.RUN_SCAN_INTERVAL_SEC
        boundary = (1_789_000_000 // run) * run
        # Default multiplier=1: setiap cron run = slot LP baru, tidak ada yang
        # ditahan — itu isi permintaan user (holder berubah = langsung tahu).
        for ago in (300, 900, 2400, 48 * run):
            self.assertTrue(mod.lp_slot_due(boundary + ago, boundary),
                            f"ago={ago}")
        # Run ganda dalam satu slot (chain dispatch + schedule) = skip Helius.
        for ago in (0, 60, run - 1):
            self.assertFalse(mod.lp_slot_due(boundary + ago, boundary),
                             f"ago={ago}")
        self.assertTrue(mod.lp_slot_due(boundary, 0))     # belum pernah scan
        self.assertFalse(mod.lp_slot_due(boundary, boundary + run))  # jam mundur

    def test_lp_slot_due_dibatasi_kalau_hidelius_stres(self):
        """LP_SCAN_RUN_MULTIPLIER=3 -> scan Solana ±15 menit, Robinhood tetap."""
        import scripts.scan_holders as mod
        run, last = mod.RUN_SCAN_INTERVAL_SEC, 1_789_000_000 - 1_789_000_000 % 900
        with mock.patch.object(mod, "LP_SCAN_RUN_MULTIPLIER", 3):
            self.assertEqual(mod.lp_slot_sec(), 3 * run)
            self.assertFalse(mod.lp_slot_due(last, last))         # slot sama
            self.assertFalse(mod.lp_slot_due(last + run, last))   # 5 mnt kemudian
            self.assertFalse(mod.lp_slot_due(last + 2 * run, last))
            self.assertTrue(mod.lp_slot_due(last + 3 * run, last))  # slot baru
            self.assertTrue(mod.lp_slot_due(last + 9 * run, last))  # run terlewat
            self.assertTrue(mod.lp_slot_due(last + run, 0))       # bootstrap

    def test_token_biasa_tidak_discan_meski_datanya_basi(self):
        """Catch-up/bootstrap watchlist biasa sudah dilepas dari cron.

        Dulu token non-LP yang datanya menua ikut di-scan (``token_needs_scan``
        + slot 4 jam). Sejak 2026-09-07 cron hanya lane LP, jadi token biasa
        tidak pernah masuk rencana scan seberapa pun basi datanya.
        """
        import scripts.scan_holders as mod
        run = mod.RUN_SCAN_INTERVAL_SEC
        T = (int(time.time()) // run) * run + run
        lp_mint = "LpMint111111111111111111111111111111111111"
        reg_mint = "RegMint22222222222222222222222222222222222"
        mocks: dict = {}
        with self._cron_env(now_ts=T, status_ts=T - run,
                            solana_watch={
                                lp_mint: {"symbol": "LP", "source": "meteora"},
                                reg_mint: {"symbol": "REG",
                                           "source": "manual"}},
                            rh_watch={}, mocks=mocks):
            self.assertEqual(mod.main([]), 0)
        mocks["solana_scan"].assert_called_once()
        self.assertEqual(set(mocks["solana_scan"].call_args.args[0]), {lp_mint})

    def _cron_env(self, *, now_ts, status_ts, solana_watch, rh_watch, mocks):
        """Panggil ``main()`` dengan jam + IO terkendali (ExitStack + mocks)."""
        import contextlib
        import scripts.scan_holders as mod
        import robinhood_watchlist as rw_mod

        clock = types.SimpleNamespace(time=lambda: float(now_ts),
                                       monotonic=lambda: 0.0,
                                       sleep=lambda _s: None)
        rh_ok = {ca: {"symbol": "RH", "analyzed_at": now_ts,
                      "holders": {"total_fetched": 120,
                                  "wallets_analyzed": 120,
                                  "dust_count": 3, "dust_pct_mc": 0.2}}
                 for ca in rh_watch}
        published: dict = {}
        stack = contextlib.ExitStack()

        def add(name, patch):
            mocks[name] = stack.enter_context(patch)
            return mocks[name]

        add("time", mock.patch.object(mod, "time", clock))
        add("load_watchlist", mock.patch.object(mod, "load_watchlist",
                                                return_value=solana_watch))
        add("load_status", mock.patch.object(
            mod, "load_holder_status",
            return_value={"updated_at": status_ts, "tokens": {}}))
        add("load_history", mock.patch.object(mod, "load_holder_history",
                                               return_value={"tokens": {}}))
        add("pull_history", mock.patch.object(mod, "pull_holder_history",
                                              return_value=None))
        add("seed", mock.patch.object(mod, "seed_from_status",
                                      side_effect=lambda store, _s: store))
        solana_ok = {ca: {"symbol": (meta or {}).get("symbol") or "S",
                           "analyzed_at": now_ts,
                           "holders": {"total_fetched": 100,
                                       "wallets_analyzed": 100,
                                       "dust_count": 1,
                                       "dust_pct_mc": 0.1}}
                      for ca, meta in solana_watch.items()}
        add("solana_scan", mock.patch.object(mod, "scan_watchlist",
                                             return_value=solana_ok))
        add("ingest", mock.patch.object(mod, "ingest_many",
                                        return_value={"tokens": {}}))
        add("publish", mock.patch.object(mod, "publish_holder_status",
                                         return_value={"updated_at": now_ts}))
        add("backup", mock.patch.object(mod, "publish_holder_history",
                                        return_value={"pushed": True,
                                                      "bytes": 1, "pruned": [],
                                                      "over_budget": False,
                                                      "error": ""}))
        add("alerts", mock.patch.object(mod, "process_holder_alerts",
                                        return_value=[]))
        add("publish_result", mock.patch.object(
            mod, "last_publish_result",
            return_value={"ok": True, "error": ""}))
        add("rh_watchlist", mock.patch.object(rw_mod, "load_watchlist",
                                             return_value=rh_watch))
        add("rh_status", mock.patch.object(
            rw_mod, "load_status",
            return_value={"updated_at": status_ts, "tokens": {}}))
        add("rh_history", mock.patch.object(rw_mod, "load_history",
                                            return_value={"tokens": {}}))
        add("rh_scan", mock.patch.object(rw_mod, "scan_watchlist",
                                         return_value=rh_ok))
        add("rh_publish", mock.patch.object(
            rw_mod, "publish_scan",
            side_effect=lambda *a, **k: published.update(k)
            or {"updated_at": now_ts}))
        mocks["published"] = published
        return stack

    def test_run_biasa_scan_kedua_lane_lp(self):
        """Inti perubahan: tiap run = Robinhood LP **dan** Chart LP Meteora."""
        import scripts.scan_holders as mod
        run = mod.RUN_SCAN_INTERVAL_SEC
        T = (int(time.time()) // run) * run + run     # run 5 menit berikutnya
        lp_mint = "LpMint111111111111111111111111111111111111"
        rh_ca = "0x" + "a" * 40
        mocks: dict = {}
        with self._cron_env(now_ts=T, status_ts=T - run,
                            solana_watch={lp_mint: {"symbol": "LP",
                                                    "source": "meteora"}},
                            rh_watch={rh_ca: {"symbol": "VLAD"}},
                            mocks=mocks):
            self.assertEqual(mod.main([]), 0)
        mocks["solana_scan"].assert_called_once()   # Meteora LP: tiap run
        self.assertEqual(set(mocks["solana_scan"].call_args.args[0]), {lp_mint})
        mocks["rh_scan"].assert_called_once()       # Robinhood LP: tiap run
        self.assertEqual(set(mocks["rh_scan"].call_args.args[0]), {rh_ca})

    def test_workflow_small_cap_only_applies_to_solana_not_robinhood(self):
        import scripts.scan_holders as mod
        import holder_history as hh
        run = mod.RUN_SCAN_INTERVAL_SEC
        now = (int(time.time()) // run) * run + run
        mocks = {}
        with self._cron_env(now_ts=now, status_ts=now - run,
                            solana_watch={"SOL": {"source": "meteora"}},
                            rh_watch={"0x" + "a" * 40: {"source": "lp"}},
                            mocks=mocks):
            self.assertEqual(mod.main(["--max-wallets", "3000"]), 0)
        self.assertEqual(mocks["solana_scan"].call_args.kwargs["max_wallets"], 3000)
        self.assertEqual(mocks["rh_scan"].call_args.kwargs["max_wallets"],
                         hh.FULL_SCAN_MAX_WALLETS)
        self.assertFalse(mocks["rh_scan"].call_args.kwargs["detail"])

    def test_multiplier_menahan_solana_tetapi_tidak_robinhood(self):
        """Escape hatch kuota: LP_SCAN_RUN_MULTIPLIER=3 -> Solana tiap 15 mnt."""
        import scripts.scan_holders as mod
        run = mod.RUN_SCAN_INTERVAL_SEC
        T = (int(time.time()) // 900) * 900 + run     # 5 menit ke dalam slot LP
        lp_mint = "LpMint111111111111111111111111111111111111"
        rh_ca = "0x" + "a" * 40
        mocks: dict = {}
        with mock.patch.object(mod, "LP_SCAN_RUN_MULTIPLIER", 3):
            with self._cron_env(now_ts=T, status_ts=T - run,
                                solana_watch={lp_mint: {"symbol": "LP",
                                                        "source": "meteora"}},
                                rh_watch={rh_ca: {"symbol": "VLAD"}},
                                mocks=mocks):
                self.assertEqual(mod.main([]), 0)
        mocks["solana_scan"].assert_not_called()   # bukan slot LP (dibatasi)
        mocks["rh_scan"].assert_called_once()

    def test_run_di_slot_lp_tetap_scan_solana(self):
        """Lane Meteora jalan terus meski data LP terlihat masih 'segar'."""
        import scripts.scan_holders as mod
        lp = mod.lp_slot_sec()
        boundary = (int(time.time()) // lp) * lp
        T = boundary + lp
        lp_mint = "LpMint111111111111111111111111111111111111"
        mocks: dict = {}
        with self._cron_env(now_ts=T, status_ts=boundary,
                            solana_watch={lp_mint: {"symbol": "LP",
                                                    "source": "meteora"}},
                            rh_watch={}, mocks=mocks):
            self.assertEqual(mod.main([]), 0)
        mocks["solana_scan"].assert_called_once()
        self.assertEqual(set(mocks["solana_scan"].call_args.args[0]),
                         {lp_mint})

    def test_gate_run_ganda_tidak_membungkam_lane_robinhood(self):
        """Snapshot < 4 menit = run ganda (chain + schedule) → semua lane diam."""
        import scripts.scan_holders as mod
        lp = mod.lp_slot_sec()
        boundary = (int(time.time()) // lp) * lp
        T = boundary + lp
        rh_ca = "0x" + "a" * 40
        mocks: dict = {}
        with self._cron_env(now_ts=T, status_ts=T - 60,
                            solana_watch={"Lp11111111111111111111111111111111111111":
                                          {"symbol": "LP", "source": "meteora"}},
                            rh_watch={rh_ca: {"symbol": "VLAD"}},
                            mocks=mocks):
            self.assertEqual(mod.main([]), 0)
        mocks["solana_scan"].assert_not_called()
        mocks["rh_scan"].assert_not_called()

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
