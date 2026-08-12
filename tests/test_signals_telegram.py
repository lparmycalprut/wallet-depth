# -*- coding: utf-8 -*-
"""Offline tests: Telegram only when all 4 daily pillars pass."""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "requests" not in sys.modules:
    dummy = types.ModuleType("requests")

    class _ReqErr(Exception):
        pass

    dummy.RequestException = _ReqErr
    dummy.get = lambda *a, **k: None
    dummy.post = lambda *a, **k: None
    sys.modules["requests"] = dummy
if "pandas" not in sys.modules:
    pd_dummy = types.ModuleType("pandas")
    pd_dummy.DataFrame = type("DataFrame", (), {})
    sys.modules["pandas"] = pd_dummy

import signals as sigmod  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def test_is_complete_daily_pass():
    print("\n[1] is_complete_daily_pass gates Telegram")
    seven = [
        {"id": f"c{i}", "passed": True} for i in range(7)
    ]
    check(sigmod.is_complete_daily_pass({
        "verdict": "SETUP EMAS", "passed": 7, "total": 7,
        "date": "2026-08-11", "stealth_dump": False,
        "checks": seven,
    }) is True, "SETUP EMAS 7/7 with date is complete")
    check(sigmod.is_complete_daily_pass({
        "verdict": "WATCH", "passed": 5, "total": 7,
        "date": "2026-08-11",
        "checks": seven[:5] + [{"id": "x", "passed": False},
                               {"id": "y", "passed": False}],
    }) is False, "WATCH 5/7 is not complete")
    check(sigmod.is_complete_daily_pass({
        "verdict": "FAIL", "passed": 1, "total": 7,
        "date": "2026-08-11",
    }) is False, "FAIL is not complete")
    check(sigmod.is_complete_daily_pass({
        "verdict": "STEALTH DUMP", "passed": 0, "total": 7,
        "date": "2026-08-11", "stealth_dump": True,
    }) is False, "STEALTH DUMP is not complete")
    check(sigmod.is_complete_daily_pass({
        "verdict": "SETUP EMAS", "passed": 7, "total": 7,
        "stealth_dump": False, "checks": seven,
    }) is False, "SETUP EMAS without a finished UTC date is rejected")
    check(sigmod.is_complete_daily_pass({
        "verdict": "SETUP EMAS", "passed": 7, "total": 7,
        "date": "2026-08-11", "stealth_dump": True,
        "checks": seven,
    }) is False, "stealth flag blocks SETUP EMAS")
    check(sigmod.is_complete_daily_pass({}) is False, "empty eval is False")
    check(sigmod.is_complete_daily_pass(None) is False, "None eval is False")


def test_maybe_queue_only_complete_and_dedupes():
    print("\n[2] maybe_queue_complete_prepump sends once per CA+date")
    tmp = tempfile.mkdtemp()
    orig_path = sigmod.SIGNALS_PATH
    orig_buf = list(sigmod._DIGEST_BUF)
    orig_mode = sigmod._DIGEST_MODE
    sigmod.SIGNALS_PATH = os.path.join(tmp, "signals.json")
    sigmod._DIGEST_BUF = []
    sigmod._DIGEST_MODE = True
    try:
        ev_pass = {
            "verdict": "SETUP EMAS", "passed": 7, "total": 7,
            "date": "2026-08-11", "stealth_dump": False,
            "setup_emas": True, "score": 100,
            "phase": "SETUP EMAS",
            "metrics": {"absorption_pct": 0.8, "buy_tx_pct": 58.0,
                        "sell_tx_pct": 42.0, "buy_tx": 58, "sell_tx": 42,
                        "avg_buy_sol": 0.2, "avg_sell_sol": 0.3},
            "checks": [
                {"id": "p1_absorption", "title": "CVD Absorption",
                 "passed": True},
                {"id": "p1_cvd_flat", "title": "Bullish Divergence",
                 "passed": True},
                {"id": "p2_buy_tx", "title": "Buy TX Dominance",
                 "passed": True},
                {"id": "p2_order_size", "title": "Order Size Discrepancy",
                 "passed": True},
                {"id": "p2_whale", "title": "Whale Pressure Absorbed",
                 "passed": True},
                {"id": "p3_lps", "title": "Volume Kering LPS",
                 "passed": True},
                {"id": "p3_lock", "title": "Retensi Akumulator Bottom",
                 "passed": True},
            ],
        }
        failed = [dict(c) for c in ev_pass["checks"]]
        failed[-1]["passed"] = False
        failed[-2]["passed"] = False
        ev_watch = dict(ev_pass, verdict="WATCH", passed=5,
                        setup_emas=False, score=72, checks=failed)
        check(sigmod.maybe_queue_complete_prepump(
            "CA1", "TOK", ev_watch) is False,
              "WATCH does not queue Telegram")
        check(len(sigmod._DIGEST_BUF) == 0, "digest empty after WATCH")

        # Persist the PASS first so telegram_sent can be stamped.
        sigmod.save_signals([{
            "ca": "CA1", "type": "prepump_4pilar",
            "date": "2026-08-11", "verdict": "PASS",
        }])
        check(sigmod.maybe_queue_complete_prepump(
            "CA1", "TOK", ev_pass) is True,
              "first complete PASS queues Telegram")
        check(len(sigmod._DIGEST_BUF) == 1, "one digest item queued")
        check("Buy TX" in sigmod._DIGEST_BUF[0]
              and "Sell TX" in sigmod._DIGEST_BUF[0],
              "message includes buy vs sell TX dominance")
        check(sigmod.maybe_queue_complete_prepump(
            "CA1", "TOK", ev_pass) is False,
              "second PASS same CA+date is deduped")
        check(len(sigmod._DIGEST_BUF) == 1, "dedupe does not re-queue")
        check(sigmod.queue_no_setup_message("2026-08-11", n_tokens=3)
              is True, "empty-day notice queues")
        check("TIDAK ADA SETUP HARI INI" in sigmod._DIGEST_BUF[-1],
              "empty-day text is explicit")
        check(sigmod.queue_no_setup_message("2026-08-11", n_tokens=3)
              is False, "empty-day notice is deduped")
    finally:
        sigmod.SIGNALS_PATH = orig_path
        sigmod._DIGEST_BUF = orig_buf
        sigmod._DIGEST_MODE = orig_mode


if __name__ == "__main__":
    test_is_complete_daily_pass()
    test_maybe_queue_only_complete_and_dedupes()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for item in failures:
        print("  -", item)
    sys.exit(1 if failures else 0)
