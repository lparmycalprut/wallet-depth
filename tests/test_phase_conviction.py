# -*- coding: utf-8 -*-
"""Unit tests for conviction_avg_window and the 6-48h Distribution-Early logic.

Run without pytest, without network — all data is synthetic. The network-free
:func:`cvd.detect_phase` reads conviction via ``cvd.load_conviction()``, which
we patch to a controlled dataset so no file / GitHub access happens.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cvd

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL {msg}")
    else:
        print(f"  ok   {msg}")


def _pt(ts, conviction, net_pure=0.0, vol=100.0):
    return {"ts": ts, "conviction": conviction, "net_pure": net_pure,
            "vol": vol}


def test_conviction_avg_window():
    ref = 1_000_000
    pts = [
        _pt(ref - 24 * 3600, 55.0),
        _pt(ref - 12 * 3600, 45.0),
        _pt(ref - 5 * 3600, 30.0),   # inside 6h window -> excluded
        _pt(ref, 20.0),              # newest point = reference
    ]
    avg, n = cvd.conviction_avg_window(pts, min_age_h=6, max_age_h=48)
    check(n == 2, f"avg window picks 2 points, got {n}")
    check(avg is not None and abs(avg - 50.0) < 1e-9,
          f"avg of 55 & 45 == 50, got {avg}")


def test_conviction_avg_window_too_short():
    ref = 1_000_000
    pts = [_pt(ref - 2 * 3600, 40.0), _pt(ref, 20.0)]
    avg, n = cvd.conviction_avg_window(pts, min_age_h=6, max_age_h=48)
    check(avg is None and n == 0, "no point in 6-48h -> (None, 0)")


def test_distribution_early_uses_6_48h_avg():
    """Current conviction below the 6-48h average => Distribution-Early."""
    ref = 1_000_000
    pts = [
        _pt(ref - 24 * 3600, 55.0),
        _pt(ref - 12 * 3600, 45.0),
        _pt(ref - 4 * 3600, 30.0),
        _pt(ref, 20.0, net_pure=-5.0),   # now < avg(50) - 5, net pure < 0
    ]
    orig = cvd.load_conviction
    cvd.load_conviction = lambda: {"TESTCA": pts}
    try:
        r = cvd.detect_phase("TESTCA", None, None)
    finally:
        cvd.load_conviction = orig
    check(r["phase"] == "Distribution-Early",
          f"phase == Distribution-Early, got {r.get('phase')}")
    check("rata2 6-48h" in r.get("reason", ""),
          f"reason mentions the 6-48h average: {r.get('reason')}")


def test_no_distribution_when_cv_above_avg():
    """A single dip below the last point but still near the 6-48h average
    should NOT fire Distribution-Early (old logic only looked at ~6h)."""
    ref = 1_000_000
    # Last point dips a bit vs the previous point but stays near the 6-48h
    # average AND net_pure stays positive (so np_flipped_neg doesn't fire) —
    # this isolates the average-conviction path and must NOT be distribution.
    pts = [
        _pt(ref - 24 * 3600, 55.0),
        _pt(ref - 12 * 3600, 45.0),
        _pt(ref - 4 * 3600, 48.0),
        _pt(ref, 48.0, net_pure=1.0),    # above avg(50)-5, net still positive
    ]
    orig = cvd.load_conviction
    cvd.load_conviction = lambda: {"TESTCA": pts}
    try:
        r = cvd.detect_phase("TESTCA", None, None)
    finally:
        cvd.load_conviction = orig
    check(r["phase"] != "Distribution-Early",
          f"should NOT be Distribution-Early, got {r.get('phase')}")


if __name__ == "__main__":
    print("\n[phase & conviction]")
    test_conviction_avg_window()
    test_conviction_avg_window_too_short()
    test_distribution_early_uses_6_48h_avg()
    test_no_distribution_when_cv_above_avg()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL PASSED")
