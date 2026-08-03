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
    test_cron_skips_conviction_after_failed_fetch()
    test_remote_history_refresh_is_per_required_ca_and_cached()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for failure in failures:
        print("  -", failure)
    sys.exit(1 if failures else 0)
