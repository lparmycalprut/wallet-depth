# -*- coding: utf-8 -*-
"""Offline regression tests for the manual six-check signal refresh."""
import importlib
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "requests" not in sys.modules:
    requests_dummy = types.ModuleType("requests")

    class _RequestError(Exception):
        pass

    requests_dummy.RequestException = _RequestError
    requests_dummy.get = lambda *args, **kwargs: None
    requests_dummy.post = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_dummy
if "pandas" not in sys.modules:
    pandas_dummy = types.ModuleType("pandas")
    pandas_dummy.DataFrame = type("DataFrame", (), {})
    sys.modules["pandas"] = pandas_dummy

import signals as sigmod  # noqa: E402
import scripts.update_cvd as updater  # noqa: E402

failures = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)


def _six_check_evaluation(score=83):
    checks = [
        {"id": check_id, "passed": check_id != "p3_lps"}
        for check_id in (
            "p1_absorption", "p1_cvd_flat", "p2_buy_tx",
            "p2_order_size", "p2_whale", "p3_lps",
        )
    ]
    return {
        "date": "2026-08-13",
        "verdict": "WATCH",
        "phase": "LPS",
        "passed": 5,
        "total": 6,
        "score": score,
        "checks": checks,
        "pillars": [],
        "metrics": {"buy_tx_pct": 55.0},
    }


def test_legacy_record_is_replaced():
    print("\n[1] Seven-check row migrates to the current six-check schema")
    tmp = tempfile.mkdtemp()
    original_path = sigmod.SIGNALS_PATH
    original_pull = sigmod._pull_remote_signals
    sigmod.SIGNALS_PATH = os.path.join(tmp, "signals.json")
    sigmod._pull_remote_signals = lambda: None
    legacy_checks = [
        {"id": check_id, "passed": True}
        for check_id in (
            "p1_absorption", "p1_cvd_flat", "p2_buy_tx",
            "p2_order_size", "p2_whale", "p3_lps", "p3_lock",
        )
    ]
    try:
        sigmod.save_signals([{
            "ts": 1,
            "ca": "CA1",
            "symbol": "OLD",
            "type": "prepump_4pilar",
            "date": "2026-08-13",
            "passed": 6,
            "total": 7,
            "telegram_sent": True,
            "detail": {"checks": legacy_checks},
        }])
        sigmod.record_prepump_4pilar(
            "CA1", "NEW", _six_check_evaluation(), now_ts=2)
        rows = json.load(open(sigmod.SIGNALS_PATH, encoding="utf-8"))
        check(len(rows) == 1, "same CA/date remains one signal row")
        check(rows[0]["total"] == 6, "stored total is 6")
        check(len(rows[0]["detail"]["checks"]) == 6,
              "stored row has exactly six checks")
        check(not any(c.get("id") == "p3_lock"
                      for c in rows[0]["detail"]["checks"]),
              "legacy p3_lock filter is removed")
        check(rows[0]["schema_version"] == sigmod.PREPUMP_SCHEMA_VERSION,
              "new schema version is stamped")
        check(rows[0].get("telegram_sent") is True,
              "Telegram dedupe survives migration")

        sigmod.record_prepump_4pilar(
            "CA1", "NEW", _six_check_evaluation(score=99), now_ts=3,
            replace_existing=True)
        rows = json.load(open(sigmod.SIGNALS_PATH, encoding="utf-8"))
        check(len(rows) == 1 and rows[0]["score"] == 99,
              "manual force refresh replaces a current same-day row")
    finally:
        sigmod.SIGNALS_PATH = original_path
        sigmod._pull_remote_signals = original_pull


def test_force_fetch_bypasses_complete_chunks():
    print("\n[2] Manual refresh bypasses complete cached chunks")
    original = {
        "coverage": updater.chunk_coverage_hours,
        "chunks": updater.swaps_from_4h_chunks,
        "fetch": updater.fetch_swaps,
        "upsert": updater.upsert_4h_chunk,
        "persist": updater.persist_swaps,
    }
    cached = [("buy", 1.0, 1786579201, "cached")]
    fresh = [("sell", 2.0, 1786579202, "fresh")]
    calls = {"fetch": 0, "upsert": 0}
    updater.chunk_coverage_hours = lambda ca, date: 24.0
    updater.swaps_from_4h_chunks = lambda ca, date=None, **kwargs: cached

    def fake_fetch(*args, **kwargs):
        calls["fetch"] += 1
        return fresh, None, None, None

    updater.fetch_swaps = fake_fetch
    updater.upsert_4h_chunk = lambda *a, **k: calls.__setitem__(
        "upsert", calls["upsert"] + 1)
    updater.persist_swaps = lambda *a, **k: None
    try:
        rows, source = updater._ensure_day_swaps(
            "CA1", "TOK", "POOL", "KEY", "2026-08-13",
            now_ts=int(datetime(2026, 8, 14, tzinfo=timezone.utc).timestamp()),
            force_fetch=False)
        check(rows == cached and source == "chunks",
              "normal cron reuses complete chunks")
        check(calls["fetch"] == 0, "normal path does not fetch again")

        rows, source = updater._ensure_day_swaps(
            "CA1", "TOK", "POOL", "KEY", "2026-08-13",
            now_ts=int(datetime(2026, 8, 14, tzinfo=timezone.utc).timestamp()),
            force_fetch=True)
        check(rows == fresh and source == "fetch-forced",
              "manual path returns freshly fetched rows")
        check(calls["fetch"] == 1 and calls["upsert"] == 1,
              "manual path fetches and persists the refresh")

        updater.fetch_swaps = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("offline"))
        rows, source = updater._ensure_day_swaps(
            "CA1", "TOK", "POOL", "KEY", "2026-08-13",
            now_ts=int(datetime(2026, 8, 14, tzinfo=timezone.utc).timestamp()),
            force_fetch=True)
        check(rows == cached and source == "chunks-fallback",
              "failed fresh fetch falls back to cached chunks explicitly")
    finally:
        updater.chunk_coverage_hours = original["coverage"]
        updater.swaps_from_4h_chunks = original["chunks"]
        updater.fetch_swaps = original["fetch"]
        updater.upsert_4h_chunk = original["upsert"]
        updater.persist_swaps = original["persist"]


def test_digest_compatibility_without_drain():
    print("\n[3] Mixed-version signals module can discard a digest")
    original_drain = getattr(updater.signals_store, "drain_digest", None)
    original_buffer = list(updater.signals_store._DIGEST_BUF)
    original_mode = updater.signals_store._DIGEST_MODE
    updater.signals_store._DIGEST_BUF = ["old"]
    updater.signals_store._DIGEST_MODE = True
    try:
        if hasattr(updater.signals_store, "drain_digest"):
            delattr(updater.signals_store, "drain_digest")
        updater._discard_telegram_digest()
        check(updater.signals_store._DIGEST_BUF == [],
              "fallback clears the queued messages")
        check(updater.signals_store._DIGEST_MODE is False,
              "fallback exits digest mode")
    finally:
        if original_drain is not None:
            updater.signals_store.drain_digest = original_drain
        updater.signals_store._DIGEST_BUF = original_buffer
        updater.signals_store._DIGEST_MODE = original_mode


def test_stale_module_is_reloaded_on_import():
    print("\n[4] Hot-deploy stale signals module reloads before binding")
    module_name = "scripts.update_cvd"
    real_signals = sys.modules["signals"]
    real_updater = sys.modules[module_name]
    stale = types.ModuleType("signals")
    stale.PREPUMP_SCHEMA_VERSION = 1
    try:
        sys.modules["signals"] = stale
        sys.modules.pop(module_name, None)
        reloaded_updater = importlib.import_module(module_name)
        check(reloaded_updater.signals_store.PREPUMP_SCHEMA_VERSION == 2,
              "stale module is reloaded from the current signals.py")
        check(callable(reloaded_updater.record_prepump_4pilar),
              "current persistence function is bound after reload")
    finally:
        sys.modules["signals"] = real_signals
        sys.modules[module_name] = real_updater


if __name__ == "__main__":
    test_legacy_record_is_replaced()
    test_force_fetch_bypasses_complete_chunks()
    test_digest_compatibility_without_drain()
    test_stale_module_is_reloaded_on_import()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for item in failures:
        print("  -", item)
    sys.exit(1 if failures else 0)
