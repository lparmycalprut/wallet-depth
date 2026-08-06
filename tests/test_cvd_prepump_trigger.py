# -*- coding: utf-8 -*-
"""Unit tests for automatic Pre-Pump Checker trigger on the CVD page,
plus the multi-timeframe (30m/1h/4h/12h) radar + Telegram formatting.

Run with: python3 tests/test_cvd_prepump_trigger.py
"""
import importlib.util
import os
import sys
import time
import types

# --- stub heavy runtime deps only when they are not installed -------------
# (overwriting sys.modules unconditionally would leak bare stubs into other
# test modules under `python -m unittest discover tests`)
_stubbed = []
for _m in ('requests', 'pandas', 'numpy'):
    if _m not in sys.modules and importlib.util.find_spec(_m) is None:
        sys.modules[_m] = types.ModuleType(_m)
        _stubbed.append(_m)
if 'pandas' in _stubbed:
    pd = sys.modules['pandas']
    pd.DataFrame = object
    pd.Series = object
if 'numpy' in _stubbed:
    np = sys.modules['numpy']
    np.ndarray = object
    np.float64 = float
if 'requests' in _stubbed:
    _req = sys.modules['requests']
    _req.get = lambda *a, **k: None
    _req.post = lambda *a, **k: None
    _req.exceptions = types.SimpleNamespace(RequestException=Exception)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from prepump_detector import (evaluate_prepump, evaluate_prepump_multi_tf,
                              compute_confluence, format_prepump_telegram,
                              format_prepump_digest_pill)  # noqa: E402
from signals import detect_prepump_and_record  # noqa: E402
from unittest.mock import patch  # noqa: E402

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

    check("from prepump_detector import evaluate_prepump" in src or
          "evaluate_prepump," in src,
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

    # --- multi-timeframe wiring ---
    check("evaluate_prepump_multi_tf" in src,
          "imports/calls evaluate_prepump_multi_tf")
    check("Multi-Timeframe Pre-Pump Radar" in src,
          "renders multi-timeframe section header")
    check("PREPUMP_TF_ORDER" in src,
          "references the shared timeframe order")
    check("st.tabs(" in src,
          "renders per-timeframe detail tabs")
    check("Confluence" in src,
          "renders confluence status")
    for col in ("Score (0-100)", "Compression %", "Buy/Sell Ratio",
                "Net Flow SOL", "Pure Accum %", "Smart Wallets"):
        check(col in src, f"summary matrix has '{col}' column")
    check("## 🧭 Multi-Timeframe Pre-Pump Radar (30m / 1h / 4h / 12h)" in src,
          "export markdown includes multi-timeframe table")


def test_prepump_checker_page_wiring():
    print("\n[Prepump page] query param + multi-TF support in pages/12_🎯_Prepump_Checker.py")
    with open(os.path.join(ROOT, "pages", "12_🎯_Prepump_Checker.py"), encoding="utf-8") as f:
        src = f.read()

    check("qp_ca = st.query_params.get(\"ca\"" in src,
          "reads ca query parameter")
    check("default_ca = qp_ca or" in src,
          "prefills ca_input with qp_ca if provided")
    check("evaluate_prepump_multi_tf" in src,
          "evaluates all four timeframes")
    check("Matriks Multi-Timeframe" in src,
          "renders multi-timeframe summary matrix")
    check("st.tabs(" in src,
          "renders per-timeframe tabs")
    check("st.download_button" in src,
          "offers markdown report download")
    check("Confluence" in src,
          "renders confluence banner")


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
            full_swaps=sw,
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

    # --- multi-timeframe attachment on the recorded result ---
    multi = res.get("multi_tf")
    check(multi is not None, "result carries multi_tf evaluation")
    if multi:
        check(set(multi.get("timeframes", {})) == {"30m", "1h", "4h", "12h"},
              "multi_tf covers 30m/1h/4h/12h")
        check(multi.get("primary_tf") == "30m", "primary TF is 30m")
        check(multi.get("confluence", {}).get("status") in
              ("golden", "dead_cat", "sleeper", "normal"),
              f"confluence status valid ({multi.get('confluence', {}).get('status')})")
    if dummy_sigs:
        sig = dummy_sigs[-1]
        check("tf_scores" in sig, "signals.json entry stores per-TF scores")
        check("confluence" in sig, "signals.json entry stores confluence")


def test_multi_tf_telegram_formatting():
    print("\n[telegram] multi-TF message, confluence & digest pill")
    now = int(time.time())
    sw = _build_test_swaps(now)
    wtags = {
        "smart_w1": {"maker_tags": ["bluechip_owner"]},
        "smart_w2": {"maker_tags": ["axiom"]},
        "bot_w3": {"maker_tags": ["photon"]},
    }
    tinfo = {"symbol": "TEST", "price_usd": 0.05, "mc": 150000.0,
             "liquidity": 42000.0}
    multi = evaluate_prepump_multi_tf(sw, tinfo, ca="tg_ca", now_ts=now,
                                      wallet_tags=wtags, bullish_div_h1=True)
    primary = multi["timeframes"]["30m"]
    msg = format_prepump_telegram(primary, "tg_ca", tinfo, multi=multi)

    check("PRE-PUMP IMMINENT" in msg or "PRE-PUMP FORMING" in msg,
          "title carries the tier badge")
    check("Multi-TF:" in msg, "message shows the multi-TF score row")
    check(all(tf + ":" in msg for tf in ("30m", "1h", "4h", "12h")),
          "all four timeframes appear in the row")
    check("Confluence:" in msg, "message shows the confluence verdict")
    check("Order Asymmetry" in msg and "Order Flow" in msg and
          "Pure Accumulator" in msg and "Active Terminals" in msg,
          "on-chain signature breakdown present")

    pill = format_prepump_digest_pill(multi)
    check(pill.startswith("[") and all(tf + ":" in pill for tf in
                                       ("30m", "1h", "4h", "12h")),
          f"digest pill compact with all TFs ({pill})")

    # digest pill inside the combined monitor digest (telegram_monitor_alerts)
    import monitor_alerts as ma
    digest = ma.format_combined_digest(
        prepump=[{"symbol": "TEST", "ca": "tg_ca", "result": primary,
                  "multi": multi}])
    check(digest is not None and "[" in digest and pill in digest,
          "combined monitor digest embeds the multi-TF pill")


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

    # multi-TF respects the same safety gate on every timeframe
    multi = evaluate_prepump_multi_tf(sw, tinfo_blocked, ca="risky_ca",
                                      now_ts=now)
    check(all(r.get("blocked") for r in multi["timeframes"].values()),
          "all timeframes blocked for a risky token")
    check(multi["confluence"]["status"] == "normal" or
          multi["confluence"]["macro_score"] == 0.0,
          "blocked scores do not fake a confluence")


def test_confluence_logic():
    print("\n[confluence] golden / dead-cat / sleeper / normal detection")
    cases = [
        ({"30m": 90, "1h": 40, "4h": 65, "12h": 20}, "golden"),
        ({"30m": 85, "1h": 50, "4h": 30, "12h": 10}, "dead_cat"),
        ({"30m": 20, "1h": 55, "4h": 70, "12h": 66}, "sleeper"),
        ({"30m": 50, "1h": 45, "4h": 50, "12h": 40}, "normal"),
    ]
    for scores, want in cases:
        got = compute_confluence(scores)["status"]
        check(got == want, f"scores {scores} -> {want} (got {got})")


if __name__ == "__main__":
    test_cvd_page_source_wiring()
    test_prepump_checker_page_wiring()
    test_prepump_evaluation_on_swaps()
    test_multi_tf_telegram_formatting()
    test_prepump_safety_block_handling()
    test_confluence_logic()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for failure in failures:
        print("  -", failure)
    sys.exit(1 if failures else 0)
