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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class MainExitCodeTest(unittest.TestCase):
    """Cron harus MERAH bila data holder/publish gagal (bukan hijau palsu)."""

    def _run(self, analyses, publish_ok=None, watchlist=None):
        import scripts.scan_holders as mod
        wl = {"A": {"symbol": "AA"}} if watchlist is None else watchlist
        with mock.patch.object(mod, "load_watchlist", return_value=wl), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "load_holder_history",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "seed_from_status",
                                  side_effect=lambda s, _st: s), \
                mock.patch.object(mod, "scan_watchlist",
                                  return_value=analyses), \
                mock.patch.object(mod, "ingest_many",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "publish_holder_status",
                                  return_value={"updated_at": 1}), \
                mock.patch.object(mod, "last_publish_result",
                                  return_value={"ok": publish_ok,
                                                "error": "x"}):
            return mod.main([])

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

        def process(items, supplied_store):
            self.assertIs(supplied_store, store)
            self.assertEqual(items, analyses)
            order.append("alert")
            supplied_store["alert_evaluated"] = True
            return []

        def ingest(items, **kwargs):
            self.assertTrue(kwargs["store"]["alert_evaluated"])
            order.append("ingest")
            return kwargs["store"]

        def publish(*_args, **kwargs):
            self.assertTrue(kwargs["history_store"]["alert_evaluated"])
            order.append("publish")
            return {"updated_at": 100}

        with mock.patch.object(mod, "load_watchlist",
                               return_value={"A": {"symbol": "AA"}}), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "load_holder_history",
                                  return_value=store), \
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
