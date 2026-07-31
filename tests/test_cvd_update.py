# -*- coding: utf-8 -*-
"""Regression tests for CVD persistence used by manual stale backfill.

Runs without pytest and without network:
    python3 tests/test_cvd_update.py
"""
import json
import os
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cvd  # noqa: E402

failures = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)


def test_update_persists_deduplicated_recent_swaps():
    print("\n[CVD update] raw swaps are deduplicated, pruned, and persisted")
    now = int(time.time())
    ca = "test-ca"
    pool = "test-pool"
    duplicate = ["buy", 1.25, now - 3600, "wallet-a"]
    expired = ["sell", 2.0, now - 49 * 3600, "wallet-old"]
    new_swap = ("sell", 3.5, now - 60, "wallet-b")

    initial = {
        ca: {
            "pool": pool,
            "newest_sig": "old-signature",
            "newest_ts": now - 7200,
            "buckets": {},
            "swaps": [duplicate, list(duplicate), expired],
        }
    }

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cvd.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(initial, handle)

        fetched = ([tuple(duplicate), new_swap], "new-signature",
                   now - 60, True)
        with patch.object(cvd, "CVD_PATH", path), \
                patch.object(cvd, "fetch_swaps", return_value=fetched):
            result = cvd.update_token_cvd(
                ("fake-key",), ca, pool, max_pages=1)

        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)[ca]

    check(result["new_swaps"] == 2,
          "update completes instead of raising NameError")
    check(len(saved["swaps"]) == 2,
          "duplicate and >48h swap are removed")
    check(saved["swaps"][0] == duplicate and
          saved["swaps"][1] == list(new_swap),
          "remaining swaps are stored oldest to newest")
    check(saved["newest_sig"] == "new-signature",
          "updated state reaches the atomic JSON save")


def test_dashboard_reports_actual_backfill_results():
    print("\n[backfill UI] success count comes from completed tokens")
    app_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
    with open(app_path, "r", encoding="utf-8") as handle:
        source = handle.read()
    start = source.index("# Force-refresh button")
    end = source.index("# 💧 LP Radar", start)
    block = source[start:end]

    check("Backfilled {len(_to_refresh)}" not in block,
          "requested-token count is never shown as the success count")
    check("Backfilled {len(_fr_succeeded)}" in block,
          "green notification counts only completed tokens")
    check("if _fr_failed:" in block and "st.error(" in block,
          "failed tokens produce non-success summary UI")
    point_check = block.index("if _fr_point is None:")
    session_mark = block.index(
        "st.session_state[_freshness_state_key].add", point_check)
    check(session_mark > point_check,
          "CA is marked refreshed only after a conviction point exists")


def test_conviction_write_failure_is_reported():
    print("\n[conviction save] persistence errors reach the UI caller")
    now = int(time.time())
    swaps = [("buy", 4.0, now - 60, "wallet-a")]

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "conviction.json")
        raised = None
        with patch.object(cvd, "CONV_PATH", path), \
                patch.object(cvd, "get_recent_swaps", return_value=swaps), \
                patch.object(cvd, "load_conviction", return_value={}), \
                patch.object(cvd.os, "replace",
                             side_effect=OSError("disk unavailable")):
            try:
                cvd.record_conviction("test-ca", window_h=6)
            except Exception as exc:  # the dashboard must count this as failed
                raised = exc

        leftovers = [name for name in os.listdir(tmp)
                     if name.startswith("conv_temp_")]

    check(isinstance(raised, OSError),
          "atomic save error is raised instead of returning false success")
    check(not leftovers, "failed atomic save cleans up its temp file")


if __name__ == "__main__":
    test_update_persists_deduplicated_recent_swaps()
    test_dashboard_reports_actual_backfill_results()
    test_conviction_write_failure_is_reported()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for failure in failures:
        print("  -", failure)
    sys.exit(1 if failures else 0)
