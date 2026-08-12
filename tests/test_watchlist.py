# -*- coding: utf-8 -*-
"""Tests for watchlist.py bugfixes (Bagian 1).

Covers:
  1. push gagal -> retry -> sukses (backoff + re-fetch sha)
  2. dua op bersamaan tidak saling menimpa (lost-update race on 409)
  3. pending journal tidak dibersihkan sebelum push benar-benar sukses
  4. double push eliminated (add_to_watchlist hanya 1 PUT)
  5. caching TTL avoids hammering GitHub on every rerun

No network, no pytest required:
    python tests/test_watchlist.py
"""

import base64
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import watchlist as wlmod  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or json.dumps(json_data or {})[:300]

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        # return a copy to mimic requests behavior (each call returns new dict)
        # but for our counting of r.json() double call, we need to track calls
        return json.loads(json.dumps(self._json))


def make_harness():
    tmp = tempfile.mkdtemp()
    # point watchlist module to tmp
    orig_base = wlmod.BASE_DIR
    orig_path = wlmod.WATCHLIST_PATH
    orig_pending = wlmod.PENDING_PATH
    wlmod.BASE_DIR = tmp
    wlmod.WATCHLIST_PATH = os.path.join(tmp, "watchlist.json")
    wlmod.PENDING_PATH = os.path.join(tmp, "watchlist_pending.json")
    wlmod._reset_cache()

    # fake remote state
    state = {
        "remote": {},  # dict
        "sha": "sha0",
        "get_calls": 0,
        "put_calls": 0,
        "put_history": [],
        "fail_next_put": [],  # list of status codes to return per PUT call
        "fail_next_get": [],  # list of status codes for GET
    }

    orig_get = wlmod.requests.get
    orig_put = wlmod.requests.put
    orig_token = wlmod._github_token
    orig_sleep = time.sleep

    def fake_token():
        return "fake-token"

    def fake_get(url, headers=None, params=None, timeout=None):
        state["get_calls"] += 1
        accept = (headers or {}).get("Accept", "")
        # decide if this is the wrapper GET (for push) or raw GET (for pull)
        # pull uses raw+json accept -> returns raw dict
        # push GET uses vnd.github+json -> returns wrapper with sha+content
        if state["fail_next_get"]:
            code = state["fail_next_get"].pop(0)
            if code != 200:
                return FakeResponse(code, {"message": f"forced {code}"}, text=f"forced {code}")

        if "raw+json" in accept:
            # _github_pull path -> return remote dict directly
            return FakeResponse(200, dict(state["remote"]), text=json.dumps(state["remote"]))

        # wrapper path (push flow)
        content_b64 = base64.b64encode(json.dumps(state["remote"], indent=1).encode()).decode()
        wrapper = {"sha": state["sha"], "content": content_b64, "encoding": "base64"}
        return FakeResponse(200, wrapper, text=json.dumps(wrapper)[:200])

    def fake_put(url, headers=None, json=None, timeout=None, **kwargs):
        # json param shadows json module, so capture as body_json first
        body_json = json
        import json as json_lib
        state["put_calls"] += 1
        body = body_json or {}
        state["put_history"].append(dict(body))
        if state["fail_next_put"]:
            code = state["fail_next_put"].pop(0)
            if code not in (200, 201):
                return FakeResponse(code, {"message": f"forced {code}"}, text=f"forced fail {code}")

        req_sha = body.get("sha")
        # if remote sha mismatch -> 409 conflict
        if req_sha and req_sha != state["sha"]:
            return FakeResponse(409, {"message": "conflict"}, text="409 conflict")

        # success: decode and store
        try:
            decoded = base64.b64decode(body.get("content", "")).decode()
            new_remote = json_lib.loads(decoded) if decoded.strip() else {}
        except Exception:
            new_remote = {}
        state["remote"] = new_remote
        # bump sha
        state["sha"] = f"sha{state['put_calls']}"
        return FakeResponse(200, {"content": {"sha": state["sha"]}}, text="ok")

    wlmod.requests.get = fake_get
    wlmod.requests.put = fake_put
    wlmod._github_token = fake_token
    # no actual sleep in tests
    time.sleep = lambda s: None
    wlmod.time.sleep = lambda s: None

    def restore():
        wlmod.BASE_DIR = orig_base
        wlmod.WATCHLIST_PATH = orig_path
        wlmod.PENDING_PATH = orig_pending
        wlmod.requests.get = orig_get
        wlmod.requests.put = orig_put
        wlmod._github_token = orig_token
        time.sleep = orig_sleep
        wlmod.time.sleep = orig_sleep
        wlmod._reset_cache()

    return state, restore


def test_push_retry_success():
    print("\n[1] push gagal -> retry -> sukses")
    state, restore = make_harness()
    try:
        state["remote"] = {"EXIST": {"symbol": "EXIST"}}
        state["sha"] = "sha0"
        # first PUT fails 500, second succeeds
        state["fail_next_put"] = [500, 200]
        wl = {"EXIST": {"symbol": "EXIST"}, "NEW": {"symbol": "NEW"}}
        ok = wlmod._github_push(wl, "add NEW")
        check(ok is True, f"push eventually succeeds after retry (ok={ok})")
        check(state["put_calls"] == 2, f"PUT called twice (got {state['put_calls']})")
        check("NEW" in state["remote"], f"remote contains NEW after retry: {state['remote'].keys()}")
        check(state["get_calls"] >= 2, f"GET called at least twice for sha re-fetch (got {state['get_calls']})")
    finally:
        restore()


def test_concurrent_no_overwrite():
    print("\n[2] dua op bersamaan tidak saling menimpa (409 merge)")
    state, restore = make_harness()
    try:
        # initial remote has X
        state["remote"] = {"X": {"symbol": "X"}}
        state["sha"] = "sha0"

        # Writer A adds A successfully
        wl_a = {"X": {"symbol": "X"}, "A": {"symbol": "A"}}
        # push A (should succeed)
        ok_a = wlmod._github_push(wl_a, "add A")
        check(ok_a is True, "writer A push succeeds")
        check("A" in state["remote"], "remote has A after writer A")
        sha_after_a = state["sha"]

        # Writer B started earlier with old sha sha0, wants to add B
        # Simulate: writer B's pending journal has B, and its wl is {"X","B"} based on old remote
        # It will try to PUT with old sha0 -> our fake_put will return 409 because sha mismatch
        # Then retry logic should merge latest remote (which has A) + pending B => {X,A,B}
        wl_b_old = {"X": {"symbol": "X"}, "B": {"symbol": "B"}}
        # Manually set pending to contain B so retry merge can pick it up
        wlmod._save_pending([{"op": "add", "ca": "B", "symbol": "B", "added": "2024-01-01"}])
        # Ensure GET will return latest remote with A
        # No forced failures, just sha mismatch will trigger 409
        # We need to call _github_push with old wl (writer B's view)
        ok_b = wlmod._github_push(wl_b_old, "add B")
        check(ok_b is True, f"writer B push succeeds after 409 retry (ok={ok_b})")
        check("A" in state["remote"] and "B" in state["remote"] and "X" in state["remote"],
              f"final remote has X,A,B not lost: {list(state['remote'].keys())}")
        check(state["put_calls"] >= 2, "writer B retried after 409")

    finally:
        restore()


def test_pending_not_cleared_on_fail():
    print("\n[3] pending journal tidak dibersihkan sebelum push sukses")
    state, restore = make_harness()
    try:
        state["remote"] = {}
        state["sha"] = "sha0"
        # make PUT always fail
        state["fail_next_put"] = [500, 500, 500]
        # journal an add
        wlmod._journal({"op": "add", "ca": "TOKEN123", "symbol": "T123", "added": "2024-01-01"})
        pending_before = wlmod._load_pending()
        check(len(pending_before) == 1 and pending_before[0]["ca"] == "TOKEN123",
              "pending contains TOKEN123 after journal")

        wl = wlmod._load_and_merge(force_refresh=True)
        check("TOKEN123" in wl, "merged wl contains TOKEN123 (pending always win)")

        # try to push via save_watchlist (will fail)
        ok = wlmod.save_watchlist(wl, "add T123")
        check(ok is False, "save_watchlist returns False on push failure")
        pending_after_fail = wlmod._load_pending()
        check(len(pending_after_fail) == 1,
              f"pending NOT cleared after failed push (len={len(pending_after_fail)})")

        # now make next push succeed
        state["fail_next_put"] = [200]
        # load again, should still have TOKEN123 visible
        wl2 = wlmod._load_and_merge(force_refresh=True)
        check("TOKEN123" in wl2, "TOKEN123 still visible after failed push (pending win)")

        ok2 = wlmod.save_watchlist(wl2, "add T123 retry")
        check(ok2 is True, "retry push succeeds")
        pending_after_success = wlmod._load_pending()
        check(len(pending_after_success) == 0,
              f"pending cleared after successful push (len={len(pending_after_success)})")
        check("TOKEN123" in state["remote"], "remote finally has TOKEN123")

    finally:
        restore()


def test_double_push_eliminated():
    print("\n[4] double push redundant eliminated")
    state, restore = make_harness()
    try:
        state["remote"] = {}
        state["sha"] = "sha0"
        # track puts
        wlmod._save_pending([])  # clean
        # add_to_watchlist should journal + do ONE push (not load's push + save's push)
        # Our new implementation uses _load_and_merge (no push) then save_push
        # So put_calls should be 1
        ok = wlmod.add_to_watchlist("CA_DOUBLE", symbol="DBL", source="trending")
        check(ok is True, "add_to_watchlist succeeds")
        check(state["put_calls"] == 1,
              f"add_to_watchlist does only 1 PUT (got {state['put_calls']}) not 2 (double push fixed)")
        # remove should also be 1 more
        prev_puts = state["put_calls"]
        ok2 = wlmod.remove_from_watchlist("CA_DOUBLE")
        check(ok2 is True, "remove_from_watchlist succeeds")
        check(state["put_calls"] == prev_puts + 1,
              f"remove_from_watchlist does 1 PUT (total {state['put_calls']})")

    finally:
        restore()


def test_cache_ttl():
    print("\n[5] caching TTL avoids hammering API")
    state, restore = make_harness()
    try:
        state["remote"] = {"CACHED": {"symbol": "C"}}
        state["sha"] = "sha0"
        wlmod._reset_cache()
        # first load fetches remote
        wl1 = wlmod.load_watchlist(force_refresh=False)
        calls_after_first = state["get_calls"]
        check(calls_after_first >= 1, f"first load does GET (calls={calls_after_first})")
        # second load immediately should use cache, no new GET
        wl2 = wlmod.load_watchlist(force_refresh=False)
        calls_after_second = state["get_calls"]
        check(calls_after_second == calls_after_first,
              f"second load within TTL uses cache (calls {calls_after_first}->{calls_after_second})")
        # force refresh should bypass cache
        wl3 = wlmod.load_watchlist(force_refresh=True)
        calls_after_third = state["get_calls"]
        check(calls_after_third > calls_after_second,
              f"force_refresh bypasses cache (calls {calls_after_second}->{calls_after_third})")
    finally:
        restore()


def test_update_local_meta_and_resolve_row():
    print("\n[6] 15m snapshot + stale/expired signal resolution")
    state, restore = make_harness()
    try:
        ca = "CA_SNAP"
        wlmod.atomic_write_json(wlmod.WATCHLIST_PATH, {
            ca: {"symbol": "hwg", "diamond_pct": 87.0,
                 "real_holders": 1749, "dust_holders": 103},
        }, indent=1)
        now = 1_700_000_000
        saved = wlmod.update_local_meta(ca, {
            "wyckoff_ts": now,
            "wyckoff_type": "🚀 SOS IGNITION BREAKOUT",
            "wyckoff_score": 93.0,
            "wyckoff_volume_sol": 8.62,
            "wyckoff_cvd_sol": 8.08,
            "wyckoff_lock_pct": 100.0,
            "holder_lock_pct": 100.0,
        })
        check(saved is not None and saved["symbol"] == "hwg",
              "snapshot keeps existing symbol")
        check(saved["wyckoff_score"] == 93.0, "snapshot stores score")
        on_disk = json.load(open(wlmod.WATCHLIST_PATH, encoding="utf-8"))
        check(on_disk[ca]["wyckoff_type"].startswith("🚀"),
              "local watchlist.json received the snapshot")
        check(state["put_calls"] == 0,
              "update_local_meta does not GitHub-push")

        row = wlmod.resolve_wyckoff_row(on_disk[ca], None, now_ts=now)
        check(row["source"] == "snapshot", "fresh snapshot is preferred")
        check(row["raw_type"].startswith("🚀"), "SOS badge stays while fresh")
        check(row["stale"] is False, "snapshot age 0 is not stale")

        old_sig = {
            "ts": now - 4 * 3600,
            "type": "🟢 ABSORPTION DIVERGENCE (WYCKOFF SPRING)",
            "score": 95.0,
            "volume_sol": 12.3,
            "cvd_sol": -1.96,
            "holder_lock_pct": 100.0,
        }
        expired = wlmod.resolve_wyckoff_row({}, old_sig, now_ts=now)
        check(expired["source"] == "signal", "falls back to signals.json")
        check(expired["raw_type"] == "",
              "trigger older than 3h expires to NORMAL")
        check(expired["stale"] is True, "4h-old signal is marked stale")
        check(expired["vol_sol"] == 12.3, "last vol is still shown")

        grade_c = dict(on_disk[ca])
        grade_c["wyckoff_type"] = "⚪ GRADE C: ROUTINE NOISE"
        quiet = wlmod.resolve_wyckoff_row(grade_c, None, now_ts=now)
        check(quiet["raw_type"] == "", "Grade C is shown as NORMAL")
        check(quiet["score"] == 93.0, "Grade C still exposes the score")

        check(wlmod.meta_details_stale({"diamond_pct": 87}, now_ts=now) is True,
              "missing details_ts is stale")
        check(wlmod.meta_details_stale({"details_ts": now}, now_ts=now) is False,
              "fresh details_ts is not stale")
        check(wlmod.meta_details_stale(
            {"details_ts": now - 13 * 3600}, now_ts=now) is True,
              "details older than 12h are stale")

        four = wlmod.resolve_prepump_row({
            "prepump_ts": now,
            "prepump_verdict": "PASS",
            "prepump_phase": "IGNITION",
            "prepump_passed": 4,
            "prepump_absorption_pct": 0.82,
            "prepump_buy_tx_pct": 58.0,
            "prepump_stealth_dump": False,
        }, None, now_ts=now)
        check(four["source"] == "snapshot", "4-pilar snapshot preferred")
        check(four["verdict"] == "PASS", "4-pilar verdict PASS")
        check(four["absorption_pct"] == 0.82, "absorption pct stored")
        check(four["stale"] is False, "fresh 4-pilar snapshot is not stale")
        old_four = wlmod.resolve_prepump_row({}, {
            "ts": now - 40 * 3600,
            "type": "prepump_4pilar",
            "verdict": "STEALTH DUMP",
            "stealth_dump": True,
            "detail": {"metrics": {"absorption_pct": 9.6,
                                   "buy_tx_pct": 42.0}},
        }, now_ts=now)
        check(old_four["source"] == "signal", "falls back to 4-pilar signal")
        check(old_four["stealth_dump"] is True, "stealth flag survives")
        check(old_four["stale"] is True, "40h-old 4-pilar row is stale")
    finally:
        restore()


if __name__ == "__main__":
    test_push_retry_success()
    test_concurrent_no_overwrite()
    test_pending_not_cleared_on_fail()
    test_double_push_eliminated()
    test_cache_ttl()
    test_update_local_meta_and_resolve_row()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for f in failures:
        print("  -", f)
    sys.exit(1 if failures else 0)
