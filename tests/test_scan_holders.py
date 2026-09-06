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
        wl = {"A": {"symbol": "AA"}} if watchlist is None else watchlist
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
                               return_value={"A": {}}), \
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
            # Konteks volume/harga harus disuntikkan sebagai provider lazy.
            self.assertTrue(callable(kwargs.get("context_provider")))
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
                               return_value={"A": {"symbol": "AA"}}), \
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


class EarlyDumpScopeWiringTest(unittest.TestCase):
    """Cron harus meneruskan scope rule ⚡ EARLY DUMP (token Chart LP)."""

    def test_lp_mints_diteruskan_dari_split_watchlist(self):
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
        self.assertEqual(kwargs.get("lp_mints"),
                         {"LpMint11111111111111111111111111111111111"})


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
                               return_value={"A": {"symbol": "AA"}}), \
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
        self.assertTrue(seen.get("detail"))

    def test_scan_watchlist_defaults_to_full(self):
        import holder_history as hh
        seen = {}
        with mock.patch("scripts.scan_holders.analyze_token",
                        side_effect=lambda *a, **kw:
                        (seen.update(kw) or {"ca": "A"})):
            out = scan_watchlist({"A": {"symbol": "AA"}}, workers=1)
        self.assertEqual(set(out), {"A"})
        self.assertEqual(seen.get("max_wallets"), hh.FULL_SCAN_MAX_WALLETS)


class RobinhoodEarlyDumpScopeWiringTest(unittest.TestCase):
    """Cron harus meneruskan scope rule ⚡ EARLY DUMP untuk watchlist Robinhood.

    Watchlist RH tidak dipecah Chart LP seperti Meteora, jadi seluruh token
    `0x…` di watchlist ikut scope early_dump (kriteria sama: crossing naik
    dust holder > 0,1% MC tanpa gerbang volume keras).
    """

    def test_rh_watchlist_menjadi_lp_mints_alert(self):
        import scripts.scan_holders as mod
        import robinhood_watchlist as rw_mod
        ca = "0x" + "a" * 40
        rh_watch = {ca: {"symbol": "VLAD", "source": "manual"}}
        rh_analyses = {ca: {"symbol": "VLAD", "analyzed_at": 100,
                            "holders": {"total_fetched": 5,
                                        "dust_pct_mc": 0.4}}}
        seen = {}

        def _process(items, store, **kwargs):
            seen["lp_mints"] = kwargs.get("lp_mints")
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
        self.assertEqual(seen.get("lp_mints"), {ca})


class ScanScopeMergeTest(unittest.TestCase):
    """Scope cron (2026-09-05): LP ±15 menit, biasa slot 4 jam, all = semua.

    - ``--scope fast``: hanya watchlist LP yang di-scan dan snapshot
      dipublish **dengan** ``merge_status`` (token watchlist biasa
      diwariskan dari snapshot sebelumnya);
    - ``--scope all``: seluruh watchlist di-scan dan snapshot dipublish
      **tanpa** ``merge_status`` (data penuh menang).
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
                                      {mint: {"symbol": "X", "holders": {
                                          "total_fetched": 1}}
                                       for mint in due}) as scan_mock, \
                mock.patch.object(mod, "ingest_many",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "publish_holder_status",
                                  return_value={"updated_at": 1}) as pub_mock, \
                mock.patch.object(mod, "publish_holder_history",
                                  return_value={"pushed": True,
                                                "bytes": 1, "pruned": [],
                                                "over_budget": False,
                                                "error": ""}), \
                mock.patch.object(mod, "process_holder_alerts",
                                  return_value=[]), \
                mock.patch.object(mod, "last_publish_result",
                                  return_value={"ok": True, "error": ""}):
            code = mod.main(list(argv))
        capture["scan_args"] = scan_mock.call_args
        capture["pub_kwargs"] = pub_mock.call_args.kwargs
        capture["current_status"] = status_mock.return_value
        return code

    def test_scope_fast_hanya_scan_watchlist_lp(self):
        wl = {"LpMint11111111111111111111111111111111111":
              {"symbol": "LP", "source": "meteora"},
              "Watch11111111111111111111111111111111111":
              {"symbol": "REG", "source": "manual"}}
        capture: dict = {}
        code = self._run(["--scope", "fast"], wl, capture)
        self.assertEqual(code, 0)
        scanned = set(capture["scan_args"].args[0])
        self.assertEqual(scanned, {"LpMint11111111111111111111111111111111111"})
        # Run cepat mewarisi snapshot token biasa (merge_status).
        self.assertEqual(capture["pub_kwargs"].get("merge_status"),
                         capture["current_status"])

    def test_scope_all_scan_semua_tanpa_merge(self):
        wl = {"LpMint11111111111111111111111111111111111":
              {"symbol": "LP", "source": "meteora"},
              "Watch11111111111111111111111111111111111":
              {"symbol": "REG", "source": "manual"}}
        capture: dict = {}
        code = self._run(["--scope", "all"], wl, capture)
        self.assertEqual(code, 0)
        scanned = set(capture["scan_args"].args[0])
        self.assertEqual(scanned, set(wl))
        self.assertIsNone(capture["pub_kwargs"].get("merge_status"))


class ScanCadenceTest(unittest.TestCase):
    """Cadens tiga jalur sejak 2026-09-06: Robinhood LP 5 menit per run.

    User minta **watchlist Robinhood** di-fetch tiap 5 menit "supaya exit bisa
    lebih awal", TAPI scan Solana (Chart LP Meteora) tetap ±15 menit: tiap
    scan Solana menarik Helius sampai 100 ribu wallet, dan watchlist biasa
    tetap slot 4 jam. Karena cron hanya punya satu jam dinding, kadens run
    turun ke 5 menit dan lane Solana digate lewat :func:`lp_slot_due`.
    """

    def test_konstanta_kadens(self):
        import scripts.scan_holders as mod
        self.assertEqual(mod.RH_FAST_SCAN_INTERVAL_SEC, 5 * 60)
        self.assertEqual(mod.RUN_SCAN_INTERVAL_SEC,
                         mod.RH_FAST_SCAN_INTERVAL_SEC)
        self.assertEqual(mod.FAST_SCAN_INTERVAL_SEC, mod.RUN_SCAN_INTERVAL_SEC)
        self.assertEqual(mod.METEORA_LP_SCAN_INTERVAL_SEC, 15 * 60)
        self.assertEqual(mod.REGULAR_SCAN_INTERVAL_SEC, 4 * 3600)
        self.assertEqual(mod.REGULAR_SLOTS, 48)   # 4 jam / 5 menit
        self.assertEqual(mod.REGULAR_CATCHUP_SEC, 4 * 3600 - 5 * 60)
        # Invarian penting: gate run ganda WAJIB lebih kecil dari kadens run,
        # kalau tidak lane Robinhood 5 menit dibungkam gate-nya sendiri.
        self.assertLess(mod.MIN_RUN_GAP_SEC, mod.RUN_SCAN_INTERVAL_SEC)
        self.assertEqual(mod.MIN_RUN_GAP_SEC, 4 * 60)

    def test_slot_4jam_masih_di_batas_4_jam(self):
        import scripts.scan_holders as mod
        boundary = (int(time.time()) // mod.REGULAR_SCAN_INTERVAL_SEC) \
            * mod.REGULAR_SCAN_INTERVAL_SEC
        self.assertTrue(mod.regular_slot_due(boundary))
        self.assertFalse(mod.regular_slot_due(boundary + mod.RUN_SCAN_INTERVAL_SEC))

    def test_lp_slot_due(self):
        import scripts.scan_holders as mod
        lp = mod.METEORA_LP_SCAN_INTERVAL_SEC
        boundary = (1_789_000_000 // lp) * lp
        self.assertTrue(mod.lp_slot_due(boundary, 0))          # bootstrap
        self.assertFalse(mod.lp_slot_due(boundary + 300, boundary))   # tengah slot
        self.assertFalse(mod.lp_slot_due(boundary + 600, boundary))
        self.assertTrue(mod.lp_slot_due(boundary + lp, boundary))     # slot baru
        self.assertTrue(mod.lp_slot_due(boundary + 5 * lp, boundary))  # run terlewat
        self.assertFalse(mod.lp_slot_due(boundary, boundary + lp))  # jam mundur

    def test_build_scan_plan_di_luar_slot_lp_tidak_menarik_solana(self):
        import scripts.scan_holders as mod
        lp_mint = "LpMint111111111111111111111111111111111111"
        reg_mint = "RegMint11111111111111111111111111111111111"
        wl = {lp_mint: {"symbol": "LP", "source": "meteora"},
              reg_mint: {"symbol": "REG", "source": "manual"}}
        # LP punya titik segar (barusaja di-scan), token biasa belum pernah.
        store = {"tokens": {lp_mint: {"points": [
            {"ts": 1_789_000_000 + 300, "dust_count": 5}]}}}
        plan = mod.build_scan_plan(wl, store, 1_789_000_000 + 300,
                                   lp_slot=False)
        self.assertFalse(plan["lp_slot"])
        self.assertEqual(set(plan["due"]), {reg_mint})
        plan = mod.build_scan_plan(wl, store, 1_789_000_000 + 300,
                                   lp_slot=True)
        self.assertEqual(set(plan["due"]), {lp_mint, reg_mint})

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

    def test_run_di_tengah_slot_hanya_scan_robinhood(self):
        """Inti perubahan: run tiap 5 menit = Robinhood saja, Solana diam."""
        import scripts.scan_holders as mod
        lp = mod.METEORA_LP_SCAN_INTERVAL_SEC
        boundary = (int(time.time()) // lp) * lp
        T = boundary + mod.RUN_SCAN_INTERVAL_SEC      # 5 menit ke dalam slot
        lp_mint = "LpMint111111111111111111111111111111111111"
        rh_ca = "0x" + "a" * 40
        mocks: dict = {}
        with self._cron_env(now_ts=T, status_ts=boundary,
                            solana_watch={lp_mint: {"symbol": "LP",
                                                    "source": "meteora"}},
                            rh_watch={rh_ca: {"symbol": "VLAD"}},
                            mocks=mocks):
            self.assertEqual(mod.main([]), 0)
        mocks["solana_scan"].assert_not_called()   # Helius hemat: belum slot LP
        mocks["rh_scan"].assert_called_once()      # Robinhood LP: tiap run
        self.assertEqual(set(mocks["rh_scan"].call_args.args[0]), {rh_ca})

    def test_run_di_slot_lp_tetap_scan_solana(self):
        """Pada slot 15 menit berikutnya lane Meteora tetap jalan."""
        import scripts.scan_holders as mod
        lp = mod.METEORA_LP_SCAN_INTERVAL_SEC
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
        lp = mod.METEORA_LP_SCAN_INTERVAL_SEC
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
