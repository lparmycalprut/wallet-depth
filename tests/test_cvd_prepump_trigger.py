# -*- coding: utf-8 -*-
"""Unit tests for automatic Pre-Pump Checker trigger on the CVD page.

Run with: python3 tests/test_cvd_prepump_trigger.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from prepump_detector import evaluate_prepump, PREPUMP_SMART_TAGS, PREPUMP_TERMINAL_TAGS
from signals import detect_prepump_and_record, load_signals
from unittest.mock import patch

failures = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)


def _build_test_swaps(now_ts):
    """Synthetic swaps tailored to trigger high pre-pump score."""
    sw = []
    # Baseline prior 4h: 2 buys of 2 SOL
    sw.append(("buy", 2.0, now_ts - 3 * 3600, "w_prior1"))
    sw.append(("buy", 2.0, now_ts - 2 * 3600, "w_prior2"))
    # Recent 30m: 4 pure buys totaling 6 SOL, 1 micro sell
    sw.append(("buy", 1.5, now_ts - 10 * 60, "smart_w1"))
    sw.append(("buy", 1.5, now_ts - 8 * 60, "smart_w2"))
    sw.append(("buy", 1.5, now_ts - 5 * 60, "bot_w3"))
    sw.append(("buy", 1.5, now_ts - 2 * 60, "w_norm4"))
    sw.append(("sell", 0.05, now_ts - 1 * 60, "w_retail_seller"))
    return sw


def test_cvd_page_source_wiring():
    print("\n[CVD page] Pre-pump trigger wiring and UI elements in pages/4_📊_CVD.py")
    with open(os.path.join(ROOT, "pages", "4_📊_CVD.py"), encoding="utf-8") as f:
        src = f.read()

    check("from prepump_detector import evaluate_prepump" in src,
          "imports evaluate_prepump")
    check("from signals import detect_prepump_and_record" in src,
          "imports detect_prepump_and_record")
    check("detect_prepump_and_record(" in src,
          "calls detect_prepump_and_record on CVD analysis")
    check('src="analyze"' in src,
          "passes src='analyze' to detect_prepump_and_record")
    check("Pre-Pump Radar & Checker (30m window)" in src,
          "renders Pre-Pump section header")
    check("Breakdown 4 Pilar" in src,
          "renders 4-pillar breakdown")
    check("compression" in src and "asymmetry" in src and "accum" in src and "delta" in src,
          "references all 4 pillars (compression, asymmetry, accum, delta)")
    check("Detail Metrics Pre-Pump (JSON)" in src,
          "exposes JSON metrics expander")
    check("Pre-Pump Evaluation (30m window)" in src,
          "includes Pre-Pump section in export markdown report")


def test_prepump_checker_page_wiring():
    print("\n[Prepump page] query param support in pages/12_🎯_Prepump_Checker.py")
    with open(os.path.join(ROOT, "pages", "12_🎯_Prepump_Checker.py"), encoding="utf-8") as f:
        src = f.read()

    check("qp_ca = st.query_params.get(\"ca\"" in src,
          "reads ca query parameter")
    check("default_ca = qp_ca or" in src,
          "prefills ca_input with qp_ca if provided")


def test_prepump_evaluation_on_swaps():
    print("\n[evaluation] evaluate_prepump executes cleanly with multi-pillar score")
    now = int(time.time())
    sw = _build_test_swaps(now)
    wtags = {
        "smart_w1": {"maker_tags": ["bluechip_owner"]},
        "smart_w2": {"maker_tags": ["axiom"]},
        "bot_w3": {"maker_tags": ["photon"]},
    }
    tinfo = {"symbol": "TEST", "price_usd": 0.05, "mc": 150000.0}

    dummy_sigs = []
    with patch("signals.load_signals", side_effect=lambda: list(dummy_sigs)), \
            patch("signals.save_signals", side_effect=lambda s: dummy_sigs.clear() or dummy_sigs.extend(s)), \
            patch("signals._queue_or_send", return_value=None):
        res = detect_prepump_and_record(
            ca="test_ca_123",
            symbol="TEST",
            swaps=sw,
            token_info=tinfo,
            now_ts=now,
            src="analyze",
            window_min=30,
            whale_min_sol=3.0,
            wallet_tags=wtags,
            bullish_div=True,
        )

    check(res is not None, "evaluation returns result dict")
    check(res.get("score", 0) > 50, f"score is elevated (got {res.get('score')})")
    check(res.get("tier") in ("imminent", "forming"), f"tier is active (got {res.get('tier')})")
    check("pillars" in res, "pillars dictionary present")
    check("compression" in res["pillars"] and "asymmetry" in res["pillars"],
          "compression and asymmetry pillars present")
    check("accum" in res["pillars"] and "delta" in res["pillars"],
          "accum and delta pillars present")
    check("metrics" in res, "metrics dictionary present")
    check(res["metrics"]["buy_count"] == 4, f"buy count is 4 (got {res['metrics']['buy_count']})")
    check(res["metrics"]["smart_count"] >= 2, f"smart 0-sell count >= 2 (got {res['metrics']['smart_count']})")


def test_prepump_safety_block_handling():
    print("\n[safety] high markup or rug risk is flagged and blocked safely")
    now = int(time.time())
    sw = _build_test_swaps(now)
    tinfo_blocked = {"symbol": "RISKY", "markup_24h_pct": 120.0}

    res = evaluate_prepump(
        sw,
        token_info=tinfo_blocked,
        ca="risky_ca",
        now_ts=now,
    )

    check(res.get("blocked") is True, "marked as blocked")
    check(res.get("tier") == "blocked", "tier is blocked")
    check("price already +" in res.get("block_reason", ""),
          f"block reason specifies markup (got {res.get('block_reason')})")


if __name__ == "__main__":
    test_cvd_page_source_wiring()
    test_prepump_checker_page_wiring()
    test_prepump_evaluation_on_swaps()
    test_prepump_safety_block_handling()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for failure in failures:
        print("  -", failure)
    sys.exit(1 if failures else 0)
