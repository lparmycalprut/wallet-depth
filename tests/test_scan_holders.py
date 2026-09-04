"""Coverage dasar scanner cron analisis holder."""
from __future__ import annotations

import unittest
from unittest import mock

from scripts.scan_holders import scan_watchlist


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
