# -*- coding: utf-8 -*-
"""Unit tests for detect_candle_patterns (small-body H4 reversal patterns).

Run without pytest, without network — all data is synthetic.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import detect_candle_patterns, PATTERN_EMOJI
import cvd


def _candle(o, h, l, c):
    """Helper to build a candle dict."""
    return {"ts": 0, "o": o, "h": h, "l": l, "c": c, "v": 100}


def test_no_candles():
    """Empty input returns empty dict."""
    r = detect_candle_patterns([])
    assert r == {}, f"expected empty, got {r}"
    print("  ok   empty input returns empty")


def test_doji():
    """Standard doji: body ~1% of range, balanced shadows."""
    candles = [_candle(100, 110, 90, 100.5)]  # body=0.5, range=20
    r = detect_candle_patterns(candles)
    assert "Doji" in r, f"expected Doji, got {r}"
    assert r["Doji"] == 1
    print("  ok   standard doji detected")


def test_dragonfly_doji():
    """Dragonfly doji: body tiny, long lower shadow, almost no upper."""
    candles = [_candle(100, 100.5, 80, 100)]  # body=0, range=20.5
    r = detect_candle_patterns(candles)
    assert "Dragonfly Doji" in r, f"expected Dragonfly Doji, got {r}"
    print("  ok   dragonfly doji detected")


def test_gravestone_doji():
    """Gravestone doji: body tiny, long upper shadow, almost no lower."""
    candles = [_candle(100, 120, 99.5, 100)]  # body=0, range=20.5
    r = detect_candle_patterns(candles)
    assert "Gravestone Doji" in r, f"expected Gravestone Doji, got {r}"
    print("  ok   gravestone doji detected")


def test_hammer():
    """Hammer: small body at top, long lower shadow."""
    candles = [_candle(100, 105, 80, 104)]  # body=4, range=25, ls=20, us=1
    r = detect_candle_patterns(candles)
    assert "Hammer" in r, f"expected Hammer, got {r}"
    print("  ok   hammer detected")


def test_inverted_hammer():
    """Inverted hammer: small body at bottom, long upper shadow."""
    candles = [_candle(100, 120, 97, 103)]  # body=3, range=23, us=17, ls=3
    r = detect_candle_patterns(candles)
    assert "Inverted Hammer" in r, f"expected Inverted Hammer, got {r}"
    print("  ok   inverted hammer detected")


def test_spinning_top():
    """Spinning top: small body, both shadows significant."""
    candles = [_candle(100, 110, 90, 105)]  # body=5, range=20, us=5, ls=10
    r = detect_candle_patterns(candles)
    assert "Spinning Top" in r, f"expected Spinning Top, got {r}"
    print("  ok   spinning top detected")


def test_big_body_candle_not_detected():
    """A big-body candle should not match any small-body pattern."""
    candles = [_candle(100, 120, 90, 115)]  # body=15, range=30
    r = detect_candle_patterns(candles)
    assert r == {}, f"expected no patterns for big-body, got {r}"
    print("  ok   big-body candle not detected")


def test_multiple_patterns_counted():
    """Multiple pattern occurrences across candles are counted."""
    candles = [
        _candle(100, 110, 90, 100.5),   # doji
        _candle(100, 105, 80, 104),      # hammer
        _candle(100, 110, 90, 100.5),   # doji again
    ]
    r = detect_candle_patterns(candles)
    assert r.get("Doji") == 2, f"expected Doji 2x, got {r}"
    assert r.get("Hammer") == 1, f"expected Hammer 1x, got {r}"
    print("  ok   multiple pattern occurrences counted correctly")


def test_zero_range_candle_skipped():
    """A candle with h==l (zero range) is skipped gracefully."""
    candles = [_candle(100, 100, 100, 100)]
    r = detect_candle_patterns(candles)
    assert r == {}, f"expected empty for zero-range, got {r}"
    print("  ok   zero-range candle skipped")


def test_pattern_emoji_map_complete():
    """Every pattern name returned by detect_candle_patterns has an emoji."""
    # Test all patterns by constructing candles that trigger each
    test_candles = [
        _candle(100, 110, 90, 100.5),   # Doji
        _candle(100, 100.5, 80, 100),    # Dragonfly Doji
        _candle(100, 120, 99.5, 100),    # Gravestone Doji
        _candle(100, 105, 80, 104),      # Hammer
        _candle(100, 120, 97, 103),      # Inverted Hammer
        _candle(100, 110, 90, 105),      # Spinning Top
    ]
    r = detect_candle_patterns(test_candles)
    for name in r:
        assert name in PATTERN_EMOJI, f"missing emoji for {name}"
    print("  ok   all patterns have emoji in PATTERN_EMOJI")


# ---------------------------------------------------------------------------
# candle_pattern_summary — counts + price range of small-body candles
# ---------------------------------------------------------------------------
def test_pattern_summary_ranges():
    """candle_pattern_summary returns counts AND the low/high price range."""
    from cvd import candle_pattern_summary
    candles = [
        _candle(100, 110, 90, 100.5),   # Doji   -> low 90, high 110
        _candle(100, 105, 80, 104),     # Hammer -> low 80, high 105
        _candle(100, 155, 95, 150),     # big body -> NOT a pattern
    ]
    s = candle_pattern_summary(candles)
    assert s["n"] == 2, f"expected 2 pattern candles, got {s['n']}"
    assert s["counts"].get("Doji") == 1
    assert s["counts"].get("Hammer") == 1
    assert s["low"] == 80.0, f"low should be the lowest pattern low: {s}"
    assert s["high"] == 110.0, f"high should be the highest pattern high: {s}"
    print("  ok   summary counts + price range")

    empty = candle_pattern_summary([])
    assert empty == {"counts": {}, "low": None, "high": None, "n": 0}
    print("  ok   empty input -> empty summary")


def test_aggregate_candles_h1_to_h4():
    """4x H1 aggregate into 1 H4; trailing partial group is dropped."""
    from cvd import aggregate_candles
    h1 = [
        {"ts": 100, "o": 10, "h": 12, "l": 9, "c": 11, "v": 1},
        {"ts": 200, "o": 11, "h": 13, "l": 10, "c": 12, "v": 2},
        {"ts": 300, "o": 12, "h": 14, "l": 11, "c": 13, "v": 3},
        {"ts": 400, "o": 13, "h": 15, "l": 12, "c": 14, "v": 4},
        {"ts": 500, "o": 14, "h": 16, "l": 13, "c": 15, "v": 5},  # partial
    ]
    h4 = aggregate_candles(h1, 4)
    assert len(h4) == 1, f"partial group must be dropped: {h4}"
    c = h4[0]
    assert c["ts"] == 100 and c["o"] == 10 and c["c"] == 14
    assert c["h"] == 15 and c["l"] == 9 and c["v"] == 10.0
    print("  ok   H1->H4 aggregation with closed bars only")

    empty = aggregate_candles([], 4)
    assert empty == []
    print("  ok   empty aggregation")


# ---------------------------------------------------------------------------
# conviction_avg — 6-48h average used by detect_phase
# ---------------------------------------------------------------------------
def test_conviction_avg():
    """conviction_avg averages the last 48h of points (6h cron windows)."""
    import time
    from cvd import conviction_avg
    now = int(time.time())
    # +120s margin so the 48h-oldest point is never cut by float drift
    # between int(time.time()) here and time.time() inside conviction_avg.
    pts = [{"ts": now - h * 3600 + 120, "conviction": cv}
           for h, cv in ((48, 10), (42, 20), (36, 30), (30, 40),
                         (24, 50), (18, 60), (12, 70), (6, 80))]
    avg = conviction_avg(pts)
    assert abs(avg - 45.0) < 1e-9, f"expected 45.0, got {avg}"
    print("  ok   average over the full 48h window")

    # Points older than 48h are excluded.
    pts_old = [{"ts": now - 60 * 3600, "conviction": 99}] + pts
    avg2 = conviction_avg(pts_old)
    assert abs(avg2 - 45.0) < 1e-9, f"48h window must ignore old points: {avg2}"
    print("  ok   points older than 48h are excluded")

    # Sparse history falls back to the last 8 points instead of 0.
    sparse = [{"ts": now - 100 * 3600, "conviction": 50}]
    avg3 = conviction_avg(sparse)
    assert abs(avg3 - 50.0) < 1e-9, f"sparse fallback failed: {avg3}"
    assert conviction_avg([]) == 0.0
    print("  ok   sparse fallback + empty input")


def test_detect_phase_uses_48h_average():
    """All phase messages/logic use avg conviction 6-48h, not last 6h."""
    import time
    from cvd import detect_phase
    now = int(time.time())

    # CASE 1: last-6h conviction is HIGH (55%) but the 6-48h average is
    # still LOW (34%). Using only the last point would read as mature
    # accumulation (>=50%); the average says early accumulation.
    pts = [{"ts": now - h * 3600 + 120, "conviction": cv,
            "net_pure": 5.0, "vol": 100.0, "swaps": 10}
           for h, cv in ((48, 30), (42, 30), (36, 30), (30, 30),
                         (24, 30), (18, 30), (12, 40), (6, 55))]
    orig_load = cvd.load_conviction
    cvd.load_conviction = lambda: {"tok": pts}
    try:
        ph = detect_phase("tok", price_change_24h=5.0)
    finally:
        cvd.load_conviction = orig_load
    assert ph["phase"] == "Accumulation-Early", f"got {ph}"
    assert "avg conviction 34% (6-48h)" in ph["reason"], ph["reason"]
    print("  ok   level uses the 6-48h average (34%), not the 55% point")

    # CASE 2: Distribution-Early message must also show the average.
    pts_dist = [{"ts": now - h * 3600 + 120, "conviction": cv,
                 "net_pure": -8.0 if h == 6 else 5.0,
                 "vol": 100.0, "swaps": 10}
                for h, cv in ((48, 60), (42, 60), (36, 60), (30, 60),
                              (24, 60), (18, 60), (12, 60), (6, 50))]
    cvd.load_conviction = lambda: {"tok2": pts_dist}
    try:
        ph2 = detect_phase("tok2", price_change_24h=5.0)
    finally:
        cvd.load_conviction = orig_load
    assert ph2["phase"] == "Distribution-Early", f"got {ph2}"
    assert "avg conviction" in ph2["reason"] and "(6-48h)" in ph2["reason"], \
        ph2["reason"]
    print("  ok   Distribution-Early shows the 6-48h average")


if __name__ == "__main__":
    test_no_candles()
    test_doji()
    test_dragonfly_doji()
    test_gravestone_doji()
    test_hammer()
    test_inverted_hammer()
    test_spinning_top()
    test_big_body_candle_not_detected()
    test_multiple_patterns_counted()
    test_zero_range_candle_skipped()
    test_pattern_emoji_map_complete()
    test_pattern_summary_ranges()
    test_aggregate_candles_h1_to_h4()
    test_conviction_avg()
    test_detect_phase_uses_48h_average()
    print("\nALL PASSED")
