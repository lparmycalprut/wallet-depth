# -*- coding: utf-8 -*-
"""Unit tests for detect_candle_patterns (small-body H4 reversal patterns).

Run without pytest, without network — all data is synthetic.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import detect_candle_patterns, PATTERN_EMOJI


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
    print("\nALL PASSED")
