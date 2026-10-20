# -*- coding: utf-8 -*-
"""CVD & delta sejak harga di bawah lowest avg buy (info saja, 2026-10-20).

Aturan yang dijaga:
- episode mulai hanya saat harga ≤ lowest avg buy DAN mint lolos (tidak
  tersembunyi, kandidat delta);
- mint tersembunyi tidak diambil tradenya; episode yang sudah terbuka dijeda;
- episode selesai saat harga kembali di atas lowest avg buy;
- baris tabel hanya untuk mint yang sedang di bawah lowest avg buy;
- tidak mengubah vonis, eligible, atau urutan (tidak diuji di sini, dijaga
  oleh tes sweep_screen yang sudah ada).
"""
from __future__ import annotations

import copy
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import sweep_scan as scan
import sweep_screen as ss
import sweep_store as store

NOW = 1_800_000_000  # detik, tetap agar tes deterministik
HOUR = 3600


def _lowest(entry_price=1.0, price=0.9):
    return {"price_usd": price, "ok": True, "symbol": "TST"}


def _result(low=1.0, verdict="KANDIDAT", status="LOLOS"):
    return {"holder_min_avg_cost": low, "verdict": verdict,
            "cohort_gate_status": status}


class BelowLowestBuyTest(unittest.TestCase):
    def test_at_or_below_lowest_is_true(self):
        self.assertTrue(ss.below_lowest_buy(0.9, 1.0))
        self.assertTrue(ss.below_lowest_buy(1.0, 1.0))

    def test_above_lowest_is_false(self):
        self.assertFalse(ss.below_lowest_buy(1.1, 1.0))

    def test_missing_or_zero_data_is_none(self):
        self.assertIsNone(ss.below_lowest_buy(None, 1.0))
        self.assertIsNone(ss.below_lowest_buy(0.9, None))
        self.assertIsNone(ss.below_lowest_buy(0.9, 0))
        self.assertIsNone(ss.below_lowest_buy(0, 1.0))


class EpisodeStepTest(unittest.TestCase):
    def test_no_episode_when_above(self):
        out = ss.flow_episode_step(None, price=1.1, min_avg_cost=1.0,
                                   eligible=True, now=NOW)
        self.assertIsNone(out["active"])

    def test_hidden_mint_below_does_not_start(self):
        out = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                   eligible=False, now=NOW)
        self.assertIsNone(out["active"])

    def test_lolos_below_starts_episode(self):
        out = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                   eligible=True, now=NOW)
        active = out["active"]
        self.assertEqual(active["start_ts"], NOW)
        self.assertEqual(active["start_price"], 0.9)
        self.assertEqual(active["min_avg_start"], 1.0)
        self.assertEqual(active["hourly"], {})

    def test_hidden_while_open_pauses_without_closing(self):
        first = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                     eligible=True, now=NOW)
        paused = ss.flow_episode_step(first, price=0.8, min_avg_cost=1.0,
                                      eligible=False, now=NOW + HOUR)
        self.assertIsNotNone(paused["active"])
        self.assertEqual(paused["active"]["start_ts"], NOW)
        self.assertEqual(paused["past"], [])

    def test_above_closes_and_moves_to_past(self):
        first = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                     eligible=True, now=NOW)
        closed = ss.flow_episode_step(first, price=1.2, min_avg_cost=1.0,
                                      eligible=True, now=NOW + 2 * HOUR)
        self.assertIsNone(closed["active"])
        self.assertEqual(len(closed["past"]), 1)
        self.assertEqual(closed["past"][0]["end_ts"], NOW + 2 * HOUR)
        self.assertEqual(closed["past"][0]["end_price"], 1.2)

    def test_closed_even_when_hidden(self):
        first = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                     eligible=True, now=NOW)
        closed = ss.flow_episode_step(first, price=1.2, min_avg_cost=1.0,
                                      eligible=False, now=NOW + HOUR)
        self.assertIsNone(closed["active"])
        self.assertEqual(len(closed["past"]), 1)

    def test_new_episode_after_close_keeps_history(self):
        e1 = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                  eligible=True, now=NOW)
        e2 = ss.flow_episode_step(e1, price=1.2, min_avg_cost=1.0,
                                  eligible=True, now=NOW + HOUR)
        e3 = ss.flow_episode_step(e2, price=0.95, min_avg_cost=1.0,
                                  eligible=True, now=NOW + 3 * HOUR)
        self.assertEqual(e3["active"]["start_ts"], NOW + 3 * HOUR)
        self.assertEqual(len(e3["past"]), 1)
        self.assertEqual(e3["past"][0]["start_ts"], NOW)

    def test_missing_price_leaves_entry_unchanged(self):
        first = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                     eligible=True, now=NOW)
        same = ss.flow_episode_step(first, price=None, min_avg_cost=1.0,
                                    eligible=True, now=NOW + HOUR)
        self.assertEqual(same["active"]["start_ts"], NOW)


class BackfillStartTest(unittest.TestCase):
    def _h(self, ts, price):
        return {"ts": ts, "price": price}

    def test_start_is_first_bucket_of_current_below_run(self):
        history = [self._h(100, 1.5), self._h(200, 0.8), self._h(300, 0.9),
                   self._h(400, 0.95)]
        out = ss.flow_backfill_start(history, 1.0)
        self.assertEqual(out, {"ts": 200, "price": 0.8})

    def test_latest_above_lowest_gives_none(self):
        history = [self._h(100, 0.8), self._h(200, 1.2)]
        self.assertIsNone(ss.flow_backfill_start(history, 1.0))

    def test_rows_are_sorted_before_use(self):
        history = [self._h(300, 0.9), self._h(100, 1.5), self._h(200, 0.8)]
        self.assertEqual(ss.flow_backfill_start(history, 1.0)["ts"], 200)

    def test_missing_data_gives_none(self):
        self.assertIsNone(ss.flow_backfill_start([], 1.0))
        self.assertIsNone(ss.flow_backfill_start([self._h(1, 0.5)], None))

    def test_hint_sets_start_and_source(self):
        out = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                   eligible=True, now=NOW,
                                   start_hint={"ts": NOW - 5 * HOUR, "price": 0.8})
        active = out["active"]
        self.assertEqual(active["start_ts"], NOW - 5 * HOUR)
        self.assertEqual(active["start_price"], 0.8)
        self.assertIn("perkiraan", active["start_source"])

    def test_live_start_is_labelled_live(self):
        out = ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                   eligible=True, now=NOW)
        self.assertEqual(out["active"]["start_source"], "scan live")

    def test_for_mint_uses_history_when_starting(self):
        flows = {}
        history = [{"ts": NOW - 4 * HOUR, "price": 0.8},
                   {"ts": NOW, "price": 0.9}]
        fetch = mock.Mock(return_value=([], True))
        scan.lowest_buy_flow_for_mint(
            "M", {"price_usd": 0.9, "ok": True}, _result(), candles=[],
            now=NOW, flows=flows, history=history, fetch=fetch)
        self.assertEqual(flows["M"]["active"]["start_ts"], NOW - 4 * HOUR)
        self.assertEqual(fetch.call_args[0][1], NOW - 4 * HOUR)


class FlowEligibleTest(unittest.TestCase):
    def test_tidak_layak_is_not_eligible(self):
        self.assertFalse(ss.flow_eligible(
            _result(verdict="TIDAK LAYAK", status="LOLOS"), {"ok": True}))

    def test_skip_kohort_plus_is_not_eligible(self):
        self.assertFalse(ss.flow_eligible(
            _result(verdict="SKIP — kohort plus", status="SKIP — kohort plus"),
            {"ok": True}))

    def test_kandidat_lolos_is_eligible(self):
        self.assertTrue(ss.flow_eligible(_result(), {"ok": True}))

    def test_filter_hidden_is_not_eligible(self):
        metrics = {"top_bundler_trader_percentage": 0.01}  # bundler < 10%
        self.assertFalse(ss.flow_eligible(_result(), metrics))


class FlowInfoTest(unittest.TestCase):
    def test_trades_before_start_are_ignored(self):
        start = NOW - 3 * HOUR
        trades = [("buy", 100.0, start - 600),   # sebelum mulai → dibuang
                  ("buy", 50.0, start + 60),
                  ("sell", 20.0, NOW - 60)]
        info = ss.flow_info(trades, [], now=NOW, start_ts=start)
        self.assertTrue(info["available"])
        self.assertEqual(info["buy_usd"], 50.0)
        self.assertEqual(info["sell_usd"], 20.0)
        self.assertAlmostEqual(info["cvd_usd"], 30.0)
        self.assertTrue(info["covers_start"])

    def test_old_start_is_capped_and_not_covering(self):
        start = NOW - 50 * HOUR
        info = ss.flow_info([("buy", 10.0, NOW - 60)], [], now=NOW,
                            start_ts=start)
        self.assertFalse(info["covers_start"])
        self.assertEqual(info["since_ts"], NOW - ss.FLOW_MAX_HOURS * HOUR)

    def test_incomplete_flag_passes_through(self):
        info = ss.flow_info([("buy", 10.0, NOW - 60)], [], now=NOW,
                            start_ts=NOW - 2 * HOUR, complete=False)
        self.assertFalse(info["complete"])

    def test_no_trades_is_not_available(self):
        info = ss.flow_info([], [], now=NOW, start_ts=NOW - 2 * HOUR)
        self.assertFalse(info["available"])
        self.assertIn("tidak ada trade", info["reason"])


class FlowRowsTest(unittest.TestCase):
    def _row(self, mint, price, low, *, active=True, verdict="KANDIDAT",
             status="LOLOS"):
        episode = {"start_ts": NOW - 2 * HOUR, "start_price": 1.0,
                   "hourly": {}, "last": {
                       "ts": NOW, "price": price, "available": True,
                       "complete": True, "covers_start": True,
                       "buy_usd": 60.0, "sell_usd": 10.0,
                       "cvd_usd": 50.0, "delta_last_usd": 5.0,
                       "labels": []}} if active else None
        row = {"mint": mint, "metrics": {"price_usd": price, "symbol": mint},
               "result": _result(low=low, verdict=verdict, status=status)}
        return row, {mint: {"active": episode, "past": []}}

    def test_only_visible_below_lowest_buy_included(self):
        r1, f1 = self._row("BELOW", price=0.9, low=1.0)
        r2, f2 = self._row("ABOVE", price=1.2, low=1.0)
        flows = {**f1, **f2}
        out = ss.flow_rows([r1, r2], flows)
        self.assertEqual([r["mint"] for r in out], ["BELOW"])
        self.assertAlmostEqual(out[0]["cvd_usd"], 50.0)
        self.assertAlmostEqual(out[0]["vs_lowest"], -0.1)

    def test_no_active_episode_excluded(self):
        r, f = self._row("NOEP", price=0.9, low=1.0, active=False)
        self.assertEqual(ss.flow_rows([r], f), [])

    def test_non_candidate_excluded(self):
        r, f = self._row("PLUS", price=0.9, low=1.0,
                         verdict="SKIP — kohort plus", status="SKIP — kohort plus")
        self.assertEqual(ss.flow_rows([r], f), [])


class ForMintTest(unittest.TestCase):
    def test_hidden_mint_never_fetches(self):
        flows = {}
        fetch = mock.Mock(return_value=([], True))
        out = scan.lowest_buy_flow_for_mint(
            "M", {"price_usd": 0.9}, _result(verdict="TIDAK LAYAK"),
            candles=[], now=NOW, flows=flows, fetch=fetch)
        self.assertIsNone(out)
        fetch.assert_not_called()
        self.assertIsNone(flows["M"]["active"])

    def test_visible_below_fetches_since_start_and_records(self):
        start = NOW - 2 * HOUR
        flows = {"M": ss.flow_episode_step(None, price=0.9, min_avg_cost=1.0,
                                           eligible=True, now=start)}
        fetch = mock.Mock(return_value=([("buy", 80.0, NOW - 60),
                                         ("sell", 30.0, NOW - 30)], True))
        out = scan.lowest_buy_flow_for_mint(
            "M", {"price_usd": 0.9, "ok": True}, _result(), candles=[],
            now=NOW, flows=flows, fetch=fetch)
        self.assertIsNotNone(out)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args[0][1], start)  # since = mulai episode
        active = flows["M"]["active"]
        self.assertEqual(active["last"], out)
        self.assertEqual(len(active["hourly"]), 1)
        self.assertAlmostEqual(out["cvd_usd"], 50.0)
        self.assertTrue(out["available"])

    def test_fetch_failure_is_recorded_not_raised(self):
        flows = {}
        fetch = mock.Mock(side_effect=RuntimeError("GMGN 429"))
        out = scan.lowest_buy_flow_for_mint(
            "M", {"price_usd": 0.9, "ok": True}, _result(), candles=[],
            now=NOW, flows=flows, fetch=fetch)
        self.assertFalse(out["available"])
        self.assertIn("429", out["reason"])

    def test_above_lowest_closes_without_fetch(self):
        flows = {}
        scan.lowest_buy_flow_for_mint(
            "M", {"price_usd": 0.9, "ok": True}, _result(), candles=[],
            now=NOW, flows=flows, fetch=mock.Mock(return_value=([], True)))
        fetch = mock.Mock(return_value=([], True))
        out = scan.lowest_buy_flow_for_mint(
            "M", {"price_usd": 1.3, "ok": True}, _result(), candles=[],
            now=NOW + HOUR, flows=flows, fetch=fetch)
        self.assertIsNone(out)
        fetch.assert_not_called()
        self.assertIsNone(flows["M"]["active"])
        self.assertEqual(len(flows["M"]["past"]), 1)


class StoreTest(unittest.TestCase):
    def _state_with(self, hourly, start=NOW, past=None):
        return {"active": {"start_ts": start, "start_price": 0.9,
                           "min_avg_start": 1.0, "hourly": hourly,
                           "last": None},
                "past": past or []}

    def test_merge_unions_hours_and_keeps_newest_row(self):
        local = {"flow_episodes": {"M": self._state_with(
            {"100": {"ts": 100, "cvd_usd": 1.0}, "200": {"ts": 200, "cvd_usd": 9.0}})}}
        remote = {"flow_episodes": {"M": self._state_with(
            {"100": {"ts": 100, "cvd_usd": 2.0}, "200": {"ts": 150, "cvd_usd": 5.0},
             "300": {"ts": 300, "cvd_usd": 7.0}})}}
        merged = store.merge_states(local, remote)["flow_episodes"]["M"]["active"]
        self.assertEqual(sorted(merged["hourly"]), ["100", "200", "300"])
        self.assertEqual(merged["hourly"]["200"]["cvd_usd"], 9.0)  # ts lebih baru
        self.assertEqual(merged["last"]["ts"], 300)

    def test_merge_prefers_earlier_start(self):
        local = {"flow_episodes": {"M": self._state_with({}, start=NOW + 10)}}
        remote = {"flow_episodes": {"M": self._state_with({}, start=NOW)}}
        merged = store.merge_states(local, remote)["flow_episodes"]["M"]
        self.assertEqual(merged["active"]["start_ts"], NOW)

    def test_merge_keeps_remote_only_mint(self):
        remote = {"flow_episodes": {"X": self._state_with({})}}
        merged = store.merge_states({"flow_episodes": {}}, remote)
        self.assertIn("X", merged["flow_episodes"])

    def test_fingerprint_stable_without_flow(self):
        base = store.empty_state()
        without_key = {k: v for k, v in base.items() if k != "flow_episodes"}
        self.assertEqual(store.fingerprint(base), store.fingerprint(without_key))

    def test_fingerprint_changes_on_new_flow_hour(self):
        state = store.empty_state()
        before = store.fingerprint(state)
        state["flow_episodes"] = {"M": self._state_with({"100": {"ts": 100}})}
        self.assertNotEqual(before, store.fingerprint(state))

    def test_prune_caps_hours_and_past(self):
        hourly = {str(i * HOUR): {"ts": i * HOUR} for i in range(200)}
        past = [{"start_ts": i} for i in range(25)]
        state = {"flow_episodes": {"M": self._state_with(hourly, past=past)}}
        store.prune(state)
        entry = state["flow_episodes"]["M"]
        self.assertEqual(len(entry["active"]["hourly"]), store.FLOW_HOURLY_KEEP)
        self.assertEqual(len(entry["past"]), store.FLOW_PAST_KEEP)

    def test_load_state_roundtrip(self):
        state = store.empty_state()
        state["flow_episodes"] = {"M": self._state_with({"100": {"ts": 100}})}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "sweep_state.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            with mock.patch.object(store, "STATE_PATH", path):
                loaded = store.load_state()
        self.assertEqual(loaded["flow_episodes"]["M"]["active"]["start_ts"], NOW)


_DELTA_PATCH = None


def setUpModule():
    global _DELTA_PATCH
    import _offline_delta
    _DELTA_PATCH = _offline_delta.start()


def tearDownModule():
    if _DELTA_PATCH is not None:
        _DELTA_PATCH.stop()


class RunScanFlowTest(unittest.TestCase):
    def _bundle(self, price, low):
        metrics = {"mint": "M", "ok": True, "symbol": "TST", "price_usd": price,
                   "holder_min_avg_cost": low, "pair_created_at": 1000,
                   "liq_usd": 1000.0, "fdv_usd": 10000.0,
                   "mint_authority": None, "freeze_authority": None,
                   "top10_holder_pct": 18.0, "holder_pcts": [2.0]}
        return {"mint": "M", "metrics": metrics, "candles_hour": [],
                "candles_min5": [], "cohort_candles": [], "cohort_error": ""}

    def test_below_visible_mint_gets_episode_in_state(self):
        state = store.empty_state()
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: self._bundle(0.5, 1.0)), \
                mock.patch.object(ss, "flow_eligible", return_value=True):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=NOW)
        entry = state["flow_episodes"]["M"]
        self.assertIsNotNone(entry["active"])
        self.assertEqual(entry["active"]["start_ts"], NOW)
        self.assertEqual(len(entry["active"]["hourly"]), 1)
        self.assertFalse(entry["active"]["last"]["available"])  # delta di-stub kosong

    def test_hidden_mint_gets_no_episode(self):
        state = store.empty_state()
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: self._bundle(0.5, 1.0)), \
                mock.patch.object(ss, "flow_eligible", return_value=False):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=NOW)
        self.assertIsNone(state["flow_episodes"].get("M", {}).get("active"))

    def test_scan_failure_does_not_touch_episode(self):
        state = store.empty_state()
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=RuntimeError("timeout")):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=NOW)
        self.assertNotIn("M", state["flow_episodes"])


if __name__ == "__main__":
    unittest.main()
