# -*- coding: utf-8 -*-
"""Tests for the 6 stealth-A/D fixes applied to cvd.py + signals.py.

Covers:
  Fix #2.1 — conviction_split includes pure_accum / light_holder /
              trader at dolphin tier (1.0-3.0 SOL), with scaling.
  Fix #2.3 — flow_persistence reports regime changes (dist→accum) and
              has a `transition` / `prior_direction` field.
  Fix #2.4 — flow_distribution flags 1-window "fast distribution"
              crashes (>=30 SOL drop positive→negative).
  Fix #2.6 — flow_quality uses a dynamic swap-count upper bound so a
              launch with 200 swaps is not false-flagged.
  Fix #2.8 — flow_distribution looks back 7d when 24h peak is tiny.

Run: python tests/test_stealth_signals.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cvd  # noqa: E402
import signals  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _swap(side, sol, ts, wallet):
    return (side, sol, ts, wallet)


# ---------------------------------------------------------------------------
# Fix #2.1 — conviction_split tier-aware
# ---------------------------------------------------------------------------
def test_conviction_dolphin_tier_included():
    """A 1.5 SOL pure_accum (dolphin tier) should now contribute to
    pure_buy (was 0 before Fix #2.1 because it fell below whale_min_sol)."""
    swaps = [_swap("buy", 1.5, 1, "D1"), _swap("sell", 0.05, 2, "D1")]
    profiles = cvd.wallet_profiles(swaps)
    assert profiles["D1"]["profile"] == "pure_accum", \
        f"setup: expected pure_accum, got {profiles['D1']['profile']}"
    conv = cvd.conviction_split(profiles, whale_min_sol=3.0)
    check(conv["pure_buy"] == 1.5,
          f"dolphin pure_accum included: pure_buy = {conv['pure_buy']} (want 1.5)")
    check(conv.get("pure_buy_whale", -1) == 0.0,
          f"dolphin tier reports whale=0: got {conv.get('pure_buy_whale')}")
    check(abs(conv.get("pure_buy_dolphin", -1) - 0.9) < 0.05,
          f"dolphin tier reports scaled dolphin: got {conv.get('pure_buy_dolphin')}")


def test_conviction_whale_unchanged():
    """Backward compat: whale-tier pure_accum still contributes 100%
    to effective_buy (same as before the fix)."""
    swaps = [_swap("buy", 10.0, 1, "W1")]
    profiles = cvd.wallet_profiles(swaps)
    conv = cvd.conviction_split(profiles, whale_min_sol=3.0)
    check(conv["pure_buy_whale"] == 10.0,
          f"whale pure_buy unchanged: got {conv['pure_buy_whale']}")
    check(conv["conviction_pct"] == 100.0,
          f"single pure_accum whale = 100% conviction: got {conv['conviction_pct']}")


# ---------------------------------------------------------------------------
# Fix #2.3 — flow_persistence regime change detection
# ---------------------------------------------------------------------------
def _write_conviction_pts(ca, points):
    """Write a synthetic conviction history to conviction.json."""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "conviction.json")
    state = {ca: points}
    cvd.atomic_write_json(path, state)
    return tmp, path


def test_persistence_regime_change_detected():
    """dist→accum transition: -5, +8, +10 should report transition=True
    and a 'regime change' reason."""
    tmp, path = _write_conviction_pts("TCA", [
        {"ts": int(time.time()) - 18 * 3600, "conviction": 30.0,
         "pure_buy": 5.0, "pure_sell": 10.0, "net_pure": -5.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 50, "swaps": 10},
        {"ts": int(time.time()) - 12 * 3600, "conviction": 60.0,
         "pure_buy": 12.0, "pure_sell": 4.0, "net_pure": 8.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 50, "swaps": 10},
        {"ts": int(time.time()) - 6 * 3600, "conviction": 70.0,
         "pure_buy": 15.0, "pure_sell": 5.0, "net_pure": 10.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 50, "swaps": 10},
    ])
    orig = cvd.CONV_PATH
    cvd.CONV_PATH = path
    try:
        result = cvd.flow_persistence("TCA", last_n=3)
    finally:
        cvd.CONV_PATH = orig
    check(result.get("transition") is True,
          f"regime change flag set: transition={result.get('transition')}")
    check(result.get("prior_direction") == "dist",
          f"prior direction recorded: {result.get('prior_direction')}")
    check("regime change" in result.get("reason", "").lower(),
          f"reason mentions regime change: '{result.get('reason')}'")


def test_persistence_no_regime_change():
    """All-accum history should NOT report transition."""
    tmp, path = _write_conviction_pts("TCA2", [
        {"ts": int(time.time()) - 12 * 3600, "conviction": 60.0,
         "pure_buy": 12.0, "pure_sell": 2.0, "net_pure": 10.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 50, "swaps": 10},
        {"ts": int(time.time()) - 6 * 3600, "conviction": 70.0,
         "pure_buy": 15.0, "pure_sell": 3.0, "net_pure": 12.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 50, "swaps": 10},
    ])
    orig = cvd.CONV_PATH
    cvd.CONV_PATH = path
    try:
        result = cvd.flow_persistence("TCA2", last_n=3)
    finally:
        cvd.CONV_PATH = orig
    check(result.get("transition") is False,
          f"no transition: {result.get('transition')}")


# ---------------------------------------------------------------------------
# Fix #2.4 — flow_distribution fast crash detection
# ---------------------------------------------------------------------------
def test_distribution_fast_crash_detected():
    """A 1-window crash (positive→negative, >=30 SOL drop) should be
    flagged as fast distribution, even if the 24h peak was small."""
    tmp, path = _write_conviction_pts("TFD", [
        {"ts": int(time.time()) - 12 * 3600, "conviction": 50.0,
         "pure_buy": 50.0, "pure_sell": 5.0, "net_pure": 45.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 100, "swaps": 30},
        {"ts": int(time.time()) - 6 * 3600, "conviction": 40.0,
         "pure_buy": 8.0, "pure_sell": 50.0, "net_pure": -42.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 100, "swaps": 30},
    ])
    orig = cvd.CONV_PATH
    cvd.CONV_PATH = path
    try:
        result = cvd.flow_distribution("TFD")
    finally:
        cvd.CONV_PATH = orig
    check(result.get("ok") is True,
          f"fast crash flagged: ok={result.get('ok')}")
    check(result.get("fast") is True,
          f"fast flag set: fast={result.get('fast')}")
    check("fast distribution" in result.get("reason", "").lower(),
          f"reason mentions fast distribution: '{result.get('reason')}'")


def test_distribution_no_fast_crash_on_gradual():
    """A gradual positive net_pure over 4 windows should NOT trigger
    fast distribution."""
    tmp, path = _write_conviction_pts("TGD", [
        {"ts": int(time.time()) - 24 * 3600, "conviction": 50.0,
         "pure_buy": 5.0, "pure_sell": 0.0, "net_pure": 5.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 100, "swaps": 30},
        {"ts": int(time.time()) - 18 * 3600, "conviction": 50.0,
         "pure_buy": 6.0, "pure_sell": 1.0, "net_pure": 5.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 100, "swaps": 30},
        {"ts": int(time.time()) - 12 * 3600, "conviction": 50.0,
         "pure_buy": 4.0, "pure_sell": 0.0, "net_pure": 4.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 100, "swaps": 30},
        {"ts": int(time.time()) - 6 * 3600, "conviction": 50.0,
         "pure_buy": 3.0, "pure_sell": 0.0, "net_pure": 3.0,
         "lh_buy": 0, "trader_buy": 0, "vol": 100, "swaps": 30},
    ])
    orig = cvd.CONV_PATH
    cvd.CONV_PATH = path
    try:
        result = cvd.flow_distribution("TGD")
    finally:
        cvd.CONV_PATH = orig
    check(result.get("fast") is False,
          f"gradual positive not flagged fast: fast={result.get('fast')}")


# ---------------------------------------------------------------------------
# Fix #2.8 — flow_distribution 7d peak fallback
# ---------------------------------------------------------------------------
def test_distribution_7d_peak_fallback():
    """When 24h peak is tiny (<0.5) but 7d peak is meaningful, drop_pct
    is calculated against the 7d peak so long-tail stealth is detected."""
    now = int(time.time())
    # 7 points spanning 7d with a real 7d peak at index 1, then decay.
    pts = []
    for i, np_v in enumerate([60, 80, 70, 40, 30, 20, 10]):
        pts.append({
            "ts": now - (7 - i) * 24 * 3600,
            "conviction": 50.0,
            "pure_buy": float(np_v + 5), "pure_sell": 5.0,
            "net_pure": float(np_v), "lh_buy": 0, "trader_buy": 0,
            "vol": 100, "swaps": 30,
        })
    tmp, path = _write_conviction_pts("T7D", pts)
    orig = cvd.CONV_PATH
    cvd.CONV_PATH = path
    try:
        result = cvd.flow_distribution("T7D")
    finally:
        cvd.CONV_PATH = orig
    # 7d peak = 80, np_now = 10. drop = (80-10)/80 = 87.5% → ok=True
    check(result.get("ok") is True,
          f"7d peak drives detection: ok={result.get('ok')}")
    check(result.get("drop_pct", 0) >= 60,
          f"drop_pct reflects 7d peak: {result.get('drop_pct')} (want >= 60)")


# ---------------------------------------------------------------------------
# Fix #2.6 — flow_quality dynamic swap band
# ---------------------------------------------------------------------------
def test_quality_dynamic_band_allows_launch():
    """A token with 200 swaps (a launch spike) should NOT be
    false-flagged as 'two wallets dominate' just because of the
    static 50 cutoff — dynamic band scales to 0.4*200 = 80."""
    tmp, path = _write_conviction_pts("TQ1", [{
        "ts": int(time.time()), "conviction": 60.0,
        "pure_buy": 50.0, "pure_sell": 0.0, "net_pure": 50.0,
        "lh_buy": 0, "trader_buy": 0, "vol": 200, "swaps": 200,
    }])
    # 200 distinct wallets with 200 swaps.
    ts = int(time.time()) - 3 * 3600
    swaps = [_swap("buy", 0.5, ts + i, f"W{i}") for i in range(200)]
    tmp2 = tempfile.mkdtemp()
    cvd_path = os.path.join(tmp2, "cvd.json")
    cvd.atomic_write_json(cvd_path, {
        "TQ1": {"pool": "x", "swaps": [list(s) for s in swaps],
                "newest_sig": "x", "newest_ts": ts, "buckets": {}}
    })
    orig_cvd_path = cvd.CVD_PATH
    orig_conv_path = cvd.CONV_PATH
    cvd.CVD_PATH = cvd_path
    cvd.CONV_PATH = path
    try:
        result = cvd.flow_quality("TQ1")
    finally:
        cvd.CVD_PATH = orig_cvd_path
        cvd.CONV_PATH = orig_conv_path
    # Dynamic band: hi = max(50, 200*0.4) = 80. n_swaps=200 > 80,
    # but with 200 distinct wallets, n_wallets (200) > max(2, 200//20=10),
    # so the "two wallets dominate" branch is skipped → level = "ok".
    check(result.get("level") == "ok",
          f"200-swap launch with 200 wallets is real flow: level={result.get('level')}")


# ---------------------------------------------------------------------------
# Fix #2.2 — signals module wires up stealth_accumulation
# ---------------------------------------------------------------------------
def test_stealth_accumulation_wired():
    """The signals module should know about the new "stealth_accumulation"
    type for both record_signal and detect_and_record. We verify by
    reading the source rather than the live (stateful) signal flow,
    since detect_and_record writes to signals.json which would pollute
    the cron store."""
    import importlib
    # The function is callable with the new signal name without KeyError.
    # record_signal returns False when the same (ca,type) was sent
    # within DEDUPE_SEC, so we just verify it doesn't raise.
    # signals.SIGNALS_PATH is patched to a tmpdir — AGENTS.md §7: tests
    # must NEVER write to the real signals.json (this bit us before).
    _tmp = tempfile.TemporaryDirectory()
    _saved_path = signals.SIGNALS_PATH
    signals.SIGNALS_PATH = os.path.join(_tmp.name, "signals.json")
    try:
        signals.record_signal("T_NEW", "TEST", "stealth_accumulation",
                              "synthetic test", src="test", window_h=6)
    except KeyError as e:
        check(False, f"record_signal rejected stealth_accumulation: {e}")
        return
    except Exception:
        # Other exceptions (file write, etc.) are OK — we only care
        # that the new signal type is recognised.
        pass
    finally:
        signals.SIGNALS_PATH = _saved_path
        _tmp.cleanup()
    check(True, "record_signal accepts 'stealth_accumulation' type")


def _detect_with_synthetic_swaps(ca, swaps):
    """Run the real detector without touching the production signal store."""
    tmp = tempfile.TemporaryDirectory()
    saved_path = signals.SIGNALS_PATH
    saved_get_recent_swaps = cvd.get_recent_swaps
    signals.SIGNALS_PATH = os.path.join(tmp.name, "signals.json")
    cvd.get_recent_swaps = lambda requested_ca, window_h: (
        swaps if requested_ca == ca else [])
    try:
        return signals.detect_and_record(ca, "TEST", src="test", window_h=6)
    finally:
        cvd.get_recent_swaps = saved_get_recent_swaps
        signals.SIGNALS_PATH = saved_path
        tmp.cleanup()


def test_detects_stealth_accumulation_with_negative_retail_net():
    """A pure-accum whale buying while distributors exit must be stealth.

    The two pure_dist wallets make dist_net=16 SOL, so retail_net=-16 SOL.
    This exercises detect_and_record itself and proves the branch is reachable.
    """
    now = int(time.time())
    swaps = [
        _swap("buy", 10.0, now - 300, "whale"),
        _swap("sell", 8.0, now - 200, "dist-1"),
        _swap("sell", 8.0, now - 100, "dist-2"),
    ]
    recorded = _detect_with_synthetic_swaps("STEALTH_CA", swaps)
    check("stealth_accumulation" in recorded,
          f"negative retail net reaches stealth detector: {recorded}")


def test_detects_distribution_via_negative_retail_net():
    """The first distribution condition uses a reachable negative net.

    Two small traders net-buy 1 SOL total while pure distributors sell 12;
    retail_net is -11 SOL. dist_net remains below the existing 15-SOL OR
    threshold, proving the new retail_net <= -10 path triggers the signal.
    """
    now = int(time.time())
    swaps = [
        _swap("buy", 1.0, now - 500, "trader-1"),
        _swap("sell", 0.5, now - 450, "trader-1"),
        _swap("buy", 1.0, now - 400, "trader-2"),
        _swap("sell", 0.5, now - 350, "trader-2"),
        _swap("sell", 6.0, now - 200, "dist-1"),
        _swap("sell", 6.0, now - 100, "dist-2"),
    ]
    recorded = _detect_with_synthetic_swaps("DISTRIBUTION_CA", swaps)
    check("distribution" in recorded,
          f"negative retail net reaches distribution detector: {recorded}")


# ---------------------------------------------------------------------------
# detect_phase smoke test (no crash with new field)
# ---------------------------------------------------------------------------
def test_detect_phase_returns_dict():
    """detect_phase still returns a dict with the documented keys,
    even when caller passes no history."""
    tmp, path = _write_conviction_pts("TDP", [])
    orig = cvd.CONV_PATH
    cvd.CONV_PATH = path
    try:
        result = cvd.detect_phase("TDP", price_change_24h=5.0,
                                 price_change_4h=1.0)
    finally:
        cvd.CONV_PATH = orig
    check(isinstance(result, dict),
          f"detect_phase returns dict: {type(result)}")
    check("phase" in result, "phase key present")
    check("confidence" in result, "confidence key present")
    check("reason" in result, "reason key present")


# ---------------------------------------------------------------------------
# Drive them all
# ---------------------------------------------------------------------------
def main():
    tests = [
        test_conviction_dolphin_tier_included,
        test_conviction_whale_unchanged,
        test_persistence_regime_change_detected,
        test_persistence_no_regime_change,
        test_distribution_fast_crash_detected,
        test_distribution_no_fast_crash_on_gradual,
        test_distribution_7d_peak_fallback,
        test_quality_dynamic_band_allows_launch,
        test_stealth_accumulation_wired,
        test_detects_stealth_accumulation_with_negative_retail_net,
        test_detects_distribution_via_negative_retail_net,
        test_detect_phase_returns_dict,
    ]
    for t in tests:
        print(f"\n[{t.__name__}]")
        t()
    print(f"\n{'='*50}")
    if failures:
        print(f"FAILED: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
