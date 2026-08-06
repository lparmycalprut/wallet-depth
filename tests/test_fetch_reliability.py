# -*- coding: utf-8 -*-
"""Regression tests for reliable GMGN CVD fetching (no network).

Run with:
    python tests/test_fetch_reliability.py
"""
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cvd  # noqa: E402

failures = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)


class Response:
    """Small response double used by HTTP fallback and remote-history tests."""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def _entry(now):
    return {
        "pool": "known-pool",
        "newest_sig": "known-cursor",
        "newest_ts": now - 3600,
        "buckets": {
            str(now // 3600 * 3600): {
                "bs": 1.0, "ss": 0.0, "nb": 1, "ns": 0,
                "wbs": 0.0, "wss": 0.0,
            }
        },
        "swaps": [["buy", 1.0, now - 1800, "old-wallet"]],
    }


def test_params_and_runtime_tls_fallback():
    print("\n[GMGN HTTP] params are encoded once and curl failure falls back")
    params = cvd._gmgn_build_params()
    check(params["tz_name"] == "Asia/Jakarta",
          "timezone is plain before the HTTP client URL-encodes it")

    calls = []

    def bad_curl(*args, **kwargs):
        calls.append("curl")
        raise RuntimeError("TLS reset")

    fallback = Response({"ok": True})
    fake_curl = types.ModuleType("curl_cffi")
    fake_curl.requests = types.SimpleNamespace(get=bad_curl)
    with patch.dict(sys.modules, {"curl_cffi": fake_curl}), \
            patch.object(cvd.requests, "get", return_value=fallback) as get:
        got = cvd._gmgn_http_get("https://example.test", params=params,
                                 timeout=1)

    check(got is fallback, "ordinary requests response is used after curl TLS failure")
    check(len(calls) == 3, "all browser profiles are attempted before fallback")
    check(get.call_count == 1, "ordinary requests is attempted exactly once")


def test_complete_and_capped_gmgn_status():
    print("\n[GMGN pagination] completion status distinguishes complete from capped")
    now = int(time.time())
    trade = {"id": "new-trade", "timestamp": now, "event": "buy"}

    with patch.object(cvd, "_fetch_gmgn_page",
                      side_effect=[([trade], "older-cursor"), ([], None)]), \
            patch.object(cvd, "gmgn_trade_to_swap",
                         return_value=("buy", 1.0, now, "wallet")), \
            patch.object(cvd.time, "sleep", return_value=None):
        swaps, _, _, _ = cvd.fetch_gmgn_swaps(
            "test-ca", max_pages=3, page_limit=1)
    status = cvd.get_gmgn_fetch_status()
    check(len(swaps) == 1, "complete fetch maps the eligible trade")
    check(status["ok"] is True and status["complete"] is True,
          "empty terminal page marks GMGN pagination complete")

    with patch.object(cvd, "_fetch_gmgn_page", return_value=([], None)):
        cvd.fetch_gmgn_swaps("quiet-ca", max_pages=1)
    status = cvd.get_gmgn_fetch_status()
    check(status["ok"] is True and status["outcome"] == "empty",
          "a quiet token is a successful empty fetch, not a transport error")
    check("no trades" in cvd.get_gmgn_last_error(),
          "legacy UI still receives a readable no-trades explanation")

    with patch.object(cvd, "_fetch_gmgn_page",
                      return_value=([trade], "older-cursor")), \
            patch.object(cvd, "gmgn_trade_to_swap",
                         return_value=("buy", 1.0, now, "wallet")), \
            patch.object(cvd.time, "sleep", return_value=None):
        cvd.fetch_gmgn_swaps("test-ca", max_pages=1, page_limit=1)
    status = cvd.get_gmgn_fetch_status()
    check(status["ok"] is False and status["complete"] is False,
          "page cap is a fetch failure, not a complete CVD window")
    check("safety cap" in status["error"],
          "capped pagination carries an actionable error")


def test_incomplete_fetch_does_not_advance_cvd_cursor():
    print("\n[CVD persistence] incomplete GMGN fetch keeps the last good state")
    now = int(time.time())
    ca = "test-ca"
    initial = {ca: _entry(now)}
    fetched = [("sell", 2.0, now - 60, "new-wallet")]
    status = {"ok": False, "complete": False,
              "error": "GMGN pagination reached cap", "raw_seen": 100}

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cvd.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(initial, handle)
        with patch.object(cvd, "CVD_PATH", path), \
                patch.object(cvd, "fetch_swaps",
                             return_value=(fetched, "new-cursor", now, False)), \
                patch.object(cvd, "get_gmgn_fetch_status", return_value=status):
            result = cvd.update_token_cvd(
                (), ca, "", use_gmgn=True, max_pages=1)
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)[ca]

    check(result["fetch_ok"] is False and result["gap"] is True,
          "caller receives an explicit failed/incomplete result")
    check(saved["newest_sig"] == "known-cursor",
          "incomplete fetch never advances the durable cursor")
    check(saved["swaps"] == initial[ca]["swaps"],
          "partial raw swaps are not persisted and cannot double-count later")
    check(saved["buckets"] == initial[ca]["buckets"],
          "partial buckets are not persisted as complete data")
    check(saved["pool"] == "known-pool",
          "empty manual GMGN pool does not erase the last known pool")


def test_complete_gmgn_fetch_can_recover_without_pool():
    print("\n[CVD backfill] GMGN recovery does not require a DexScreener pool")
    now = int(time.time())
    ca = "pool-less-ca"
    fetched = [("buy", 2.0, now - 60, "wallet")]
    status = {"ok": True, "complete": True, "error": "", "raw_seen": 1}

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cvd.json")
        with patch.object(cvd, "CVD_PATH", path), \
                patch.object(cvd, "fetch_swaps",
                             return_value=(fetched, "cursor", now, True)), \
                patch.object(cvd, "get_gmgn_fetch_status", return_value=status):
            result = cvd.update_token_cvd((), ca, "", use_gmgn=True)
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)[ca]

    check(result["fetch_ok"] is True and result["new_swaps"] == 1,
          "complete GMGN fetch succeeds without Helius or a pool")
    check(saved["pool"] == "" and saved["newest_sig"] == "cursor",
          "pool-less GMGN result still persists its CVD cursor")


def _cap_status():
    return {"ok": False, "complete": False,
            "error": ("GMGN pagination reached its 80-page safety cap "
                      "before the requested cutoff."),
            "raw_seen": 8000}


def _fake_gmgn_fetch_recorder(fetch_calls, result):
    """Build a fetch_swaps stand-in that records its cutoff arguments."""

    def fake_fetch(api_key, pool, ca_arg, *, stop_sig=None, stop_ts=None,
                   max_pages=40, sleep=0.15, use_gmgn=False, from_ts=None,
                   to_ts=None):
        fetch_calls.append({"stop_sig": stop_sig, "stop_ts": stop_ts,
                            "max_pages": max_pages})
        return result

    return fake_fetch


def _reset_cvd_cache():
    """Drop load_cvd()'s mtime cache so a swapped CVD_PATH is always
    re-read from disk (two temp files written back-to-back can share the
    same coarse mtime, which would otherwise serve a stale state)."""
    cvd._cvd_cache = {"data": None, "mtime": 0}


def test_first_backfill_shrinks_window_on_safety_cap():
    print("\n[CVD backfill] capped first backfill retries with shrinking windows")
    now = int(time.time())
    ca = "busy-ca"
    fetched = [("buy", 4.0, now - 120, "whale-wallet")]
    ok_status = {"ok": True, "complete": True, "error": "", "raw_seen": 400}
    fetch_calls = []

    _reset_cvd_cache()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cvd.json")
        with patch.object(cvd, "CVD_PATH", path), \
                patch.object(
                    cvd, "fetch_swaps",
                    side_effect=_fake_gmgn_fetch_recorder(
                        fetch_calls, (fetched, "cursor-3h", now - 60, True))), \
                patch.object(cvd, "get_gmgn_fetch_status",
                             side_effect=[_cap_status(), _cap_status(),
                                          ok_status]):
            result = cvd.update_token_cvd(
                (), ca, "", max_pages=80, use_gmgn=True)
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)[ca]

    check(result["fetch_ok"] is True and result["gap"] is False,
          "a successful shrunk window recovers the stuck first backfill")
    check(len(fetch_calls) == 3,
          "retry stops at the first successful window (no 1h attempt)")
    windows = [now - call["stop_ts"] for call in fetch_calls]
    check(all(call["stop_sig"] is None for call in fetch_calls),
          "backfill retries never use a signature cursor")
    # First backfill walks the full 72h raw-store retention window (raised
    # from 48h when the swap store grew to 72h — see AGENTS.md §2.5).
    check(abs(windows[0] - 72 * 3600) <= 60,
          "first attempt keeps the regular 72h cutoff")
    check(abs(windows[1] - 12 * 3600) <= 60,
          "second attempt shrinks the cutoff to 12h")
    check(abs(windows[2] - 3 * 3600) <= 60,
          "third attempt shrinks the cutoff to 3h")
    check(saved["newest_sig"] == "cursor-3h" and
          saved["newest_ts"] == now - 60,
          "the successful shrunk window persists its cursor so future runs "
          "are cheap incremental fetches")
    check(result["new_swaps"] == 1,
          "swaps from the successful retry reach the normal persist path")


def test_incremental_update_never_shrinks_window():
    print("\n[CVD backfill] stored-cursor update never retries shrinking windows")
    now = int(time.time())
    ca = "known-ca"
    initial = {ca: _entry(now)}
    fetched = [("sell", 2.0, now - 60, "new-wallet")]
    fetch_calls = []

    _reset_cvd_cache()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cvd.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(initial, handle)
        with patch.object(cvd, "CVD_PATH", path), \
                patch.object(
                    cvd, "fetch_swaps",
                    side_effect=_fake_gmgn_fetch_recorder(
                        fetch_calls, (fetched, "new-cursor", now, False))), \
                patch.object(cvd, "get_gmgn_fetch_status",
                             side_effect=[_cap_status(), _cap_status()]):
            result = cvd.update_token_cvd(
                (), ca, "", max_pages=80, use_gmgn=True)
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)[ca]

    check(len(fetch_calls) == 1,
          "incremental update makes exactly one fetch (no shrunk retry)")
    check(fetch_calls[0]["stop_ts"] == initial[ca]["newest_ts"],
          "incremental update keeps the stored cursor time as its cutoff")
    check(result["fetch_ok"] is False and result["gap"] is True,
          "capped incremental update is still reported as a failed fetch")
    # Safety-cap with non-empty partial swaps now triggers partial-walk
    # recovery (documented in update_token_cvd): partial swaps/buckets are
    # persisted with gap + history_gap markers and the cursor moves to the
    # OLDEST visible trade, so the next run refetches the in-between window
    # instead of leaving a silent hole.
    check(result.get("partial") is True and result.get("history_gap") is True,
          "capped incremental update marks the partial recovery explicitly")
    check(saved.get("history_gap") is True and saved.get("gap") is True,
          "partial recovery is flagged on the stored entry")
    check(fetched[0] in [tuple(s) for s in saved["swaps"]],
          "partial swaps are persisted (deduplicated) for the next run")
    check(saved["newest_ts"] == fetched[0][2],
          "cursor points at the oldest visible trade, not blindly forward")


def test_incremental_cap_without_swaps_keeps_state_intact():
    print("\n[CVD backfill] capped incremental with zero usable swaps keeps state")
    now = int(time.time())
    ca = "known-ca"
    initial = {ca: _entry(now)}
    fetch_calls = []

    _reset_cvd_cache()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cvd.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(initial, handle)
        with patch.object(cvd, "CVD_PATH", path), \
                patch.object(
                    cvd, "fetch_swaps",
                    side_effect=_fake_gmgn_fetch_recorder(
                        fetch_calls, ([], None, now, False))), \
                patch.object(cvd, "get_gmgn_fetch_status",
                             side_effect=[_cap_status(), _cap_status()]):
            result = cvd.update_token_cvd(
                (), ca, "", max_pages=80, use_gmgn=True)
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)[ca]

    check(len(fetch_calls) == 1,
          "no shrunk retry for an incremental update without partial swaps")
    check(result["fetch_ok"] is False and result["gap"] is True,
          "still reported as a failed fetch")
    check(result.get("partial") is not True,
          "no partial recovery when there is nothing usable to persist")
    check(saved["newest_sig"] == "known-cursor" and
          saved["swaps"] == initial[ca]["swaps"] and
          saved["buckets"] == initial[ca]["buckets"],
          "capped incremental update keeps cursor, swaps and buckets intact")


def test_first_backfill_all_windows_failed_keeps_gap_state():
    print("\n[CVD backfill] when every shrunk window fails, gap state is kept")
    now = int(time.time())
    ca = "hopeless-ca"
    # Every window comes back EMPTY so the partial-walk recovery path has
    # nothing to persist — the token must stay in a clean gap state.
    fetched = []
    fetch_calls = []

    _reset_cvd_cache()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cvd.json")
        with patch.object(cvd, "CVD_PATH", path), \
                patch.object(
                    cvd, "fetch_swaps",
                    side_effect=_fake_gmgn_fetch_recorder(
                        fetch_calls,
                        (fetched, "partial-cursor", now - 60, False))), \
                patch.object(cvd, "get_gmgn_fetch_status",
                             side_effect=[_cap_status() for _ in range(4)]):
            result = cvd.update_token_cvd(
                (), ca, "", max_pages=80, use_gmgn=True)
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)[ca]

    check(len(fetch_calls) == 4,
          "72h, 12h, 3h and 1h windows are each attempted exactly once")
    expected = sorted((72 * 3600, 12 * 3600, 3 * 3600, 1 * 3600))
    windows = sorted(now - call["stop_ts"] for call in fetch_calls)
    check(all(abs(w - e) <= 60 for w, e in zip(windows, expected)),
          "retry walks the fixed 72h -> 12h -> 3h -> 1h ladder")
    check(result["fetch_ok"] is False and result["gap"] is True,
          "an all-attempts failure is still reported as a failed fetch")
    check(saved.get("gap") is True,
          "gap=True is persisted when no window can be backfilled")
    check(saved.get("last_fetch_error") == _cap_status()["error"],
          "last_fetch_error keeps the final actionable GMGN error")
    check("newest_sig" not in saved and "newest_ts" not in saved,
          "no partial cursor is persisted when every window fails")


def test_cron_skips_conviction_after_failed_fetch():
    print("\n[cron] failed GMGN fetch cannot create a fresh conviction timestamp")
    script = Path(ROOT, "scripts", "update_cvd.py").read_text()
    guard = script.index('if not res.get("fetch_ok", True):')
    record = script.index("cp = record_conviction", guard)
    check(guard < record,
          "cron checks fetch_ok before recording conviction/signals")
    check("CVD not updated" in script,
          "cron logs an actionable incomplete-fetch result")


def test_remote_history_refresh_is_per_required_ca_and_cached():
    print("\n[conviction history] remote merge is per-watchlist CA, not global")
    now = int(time.time())
    local = {"other": [{"ts": now - 60, "conviction": 40}]}
    remote = {"rako": [{"ts": now - 60, "conviction": 55}]}
    old_cache = dict(cvd._conv_remote_cache)

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "conviction.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(local, handle)
        cvd._conv_remote_cache.update(data=None, ts=0.0)
        with patch.object(cvd, "CONV_PATH", path), \
                patch.object(cvd.requests, "get",
                             return_value=Response(remote)) as get:
            merged = cvd.load_conviction(required_cas=("rako",))
            again = cvd.load_conviction(required_cas=("rako",))
        check("rako" in merged and merged["rako"][-1]["conviction"] == 55,
              "missing/stale required CA is merged from the cron copy")
        check(again["rako"][-1]["conviction"] == 55,
              "cached remote data remains visible in the same session")
        check(get.call_count == 1,
              "the remote copy is fetched once, not once per card")

        # No required_cas means an internal flow helper reads local/cache only.
        cvd._conv_remote_cache.update(data=None, ts=0.0)
        with patch.object(cvd, "CONV_PATH", path), \
                patch.object(cvd, "requests") as requests_mock:
            plain = cvd.load_conviction()
        check(plain["other"][-1]["conviction"] == 40,
              "ordinary local conviction read still works")
        check(requests_mock.get.call_count == 0,
              "internal freshness reads stay network-free")

    cvd._conv_remote_cache.clear()
    cvd._conv_remote_cache.update(old_cache)


if __name__ == "__main__":
    test_params_and_runtime_tls_fallback()
    test_complete_and_capped_gmgn_status()
    test_incomplete_fetch_does_not_advance_cvd_cursor()
    test_complete_gmgn_fetch_can_recover_without_pool()
    test_first_backfill_shrinks_window_on_safety_cap()
    test_incremental_update_never_shrinks_window()
    test_first_backfill_all_windows_failed_keeps_gap_state()
    test_cron_skips_conviction_after_failed_fetch()
    test_remote_history_refresh_is_per_required_ca_and_cached()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for failure in failures:
        print("  -", failure)
    sys.exit(1 if failures else 0)
