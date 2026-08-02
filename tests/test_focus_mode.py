# -*- coding: utf-8 -*-
"""Tests for FOCUS_MODE (focus.py) and the FOCUS_MODE-related guards
added across the codebase (signals.py tier split, app.py ldivs init,
Degen Radar caption).

These tests pin down the behaviour so a future refactor can't silently
re-introduce the ``NameError: ldivs`` crash or the FOCUS_MODE/Telegram
contract (Tier 1 → Telegram, Tier 2 → signals.json only).
"""
import json
import os
import sys
import tempfile
import unittest

# Make sure the repo root is on the path when this test runs in
# isolation (pytest -q tests/test_focus_mode.py from the repo root).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FocusModeConfig(unittest.TestCase):
    """is_focus_mode() must default to ON when config is missing/empty,
    and obey the user's explicit choice otherwise."""

    def test_default_on_when_no_config(self):
        from focus import is_focus_mode
        self.assertTrue(is_focus_mode(None))
        self.assertTrue(is_focus_mode({}))

    def test_default_on_when_key_missing(self):
        from focus import is_focus_mode
        self.assertTrue(is_focus_mode({"helius_api_key": "abc"}))

    def test_explicit_true(self):
        from focus import is_focus_mode
        self.assertTrue(is_focus_mode({"focus_mode": True}))

    def test_explicit_false(self):
        from focus import is_focus_mode
        self.assertFalse(is_focus_mode({"focus_mode": False}))

    def test_string_true_truthy(self):
        """Belt-and-braces: a non-empty string config value should be
        honoured as truthy (matches the loose bool() semantics in the
        rest of the codebase)."""
        from focus import is_focus_mode
        # bool("false") in Python is True, so we don't expect a
        # string "false" to flip it off — just document the
        # behaviour so nobody changes it by accident.
        self.assertTrue(is_focus_mode({"focus_mode": "no"}))


class HealthBadge(unittest.TestCase):
    """health_badge(ca) must never raise — even when cvd is unavailable
    or flow_check_panel returns a malformed dict."""

    def test_returns_required_keys(self):
        from focus import health_badge
        out = health_badge("deadbeef-ca-does-not-exist")
        self.assertIn("level", out)
        self.assertIn("label", out)
        self.assertIn("reason", out)
        self.assertIn(out["level"], ("ok", "warn", "danger"))

    def test_falls_back_gracefully_when_cvd_breaks(self):
        """If flow_check_panel raises, health_badge must return a
        'warn' badge with a readable reason, NOT propagate."""
        from focus import health_badge
        # focus.py imports flow_check_panel at module level, so we
        # must patch it on the focus module (not on cvd).
        import focus

        original = focus.flow_check_panel
        focus.flow_check_panel = lambda ca: (_ for _ in ()).throw(
            RuntimeError("simulated cvd failure"))
        try:
            out = health_badge("any-ca")
        finally:
            focus.flow_check_panel = original
        self.assertEqual(out["level"], "warn")
        self.assertIn("simulated cvd failure", out["reason"])

    def test_worst_level_wins(self):
        """When one check is 'danger' and another is 'warn', the badge
        must be 'danger' (most-severe-wins rule)."""
        from focus import health_badge
        import focus

        def fake_panel(ca):
            return {
                "freshness": {"level": "danger",
                              "reason": "stale 9h"},
                "persistence": {"level": "warn",
                                "reason": "direction flipped"},
                "distribution": {"level": "ok",
                                 "reason": "no dumps"},
                "quality": {"level": "ok",
                            "reason": "healthy flow"},
            }
        original = focus.flow_check_panel
        focus.flow_check_panel = fake_panel
        try:
            out = health_badge("any-ca")
        finally:
            focus.flow_check_panel = original
        self.assertEqual(out["level"], "danger")
        # The reason must include BOTH failing checks so the user
        # gets the full picture.
        self.assertIn("stale 9h", out["reason"])
        self.assertIn("direction flipped", out["reason"])

    def test_all_ok_returns_ok_badge(self):
        from focus import health_badge
        import focus

        def fake_panel(ca):
            return {
                "freshness": {"level": "ok", "reason": "fresh"},
                "persistence": {"level": "ok", "reason": "stable"},
                "distribution": {"level": "ok", "reason": "no dumps"},
                "quality": {"level": "ok", "reason": "healthy"},
            }
        original = focus.flow_check_panel
        focus.flow_check_panel = fake_panel
        try:
            out = health_badge("any-ca")
        finally:
            focus.flow_check_panel = original
        self.assertEqual(out["level"], "ok")
        self.assertIn("all 4 checks ok", out["reason"])


class ConvictionSummary(unittest.TestCase):
    """conviction_summary() reduces the conviction_split dict to the
    Tier 1 read: pure_buy whales + dolphins + conviction_pct."""

    def test_empty_input(self):
        from focus import conviction_summary
        self.assertEqual(conviction_summary({}), {})

    def test_none_input(self):
        from focus import conviction_summary
        self.assertEqual(conviction_summary(None), {})

    def test_strips_lh_buy_and_trader_buy(self):
        """In FOCUS_MODE, only the pure_buy + conviction_pct read
        matters. lh_buy and trader_buy are Tier 2 noise."""
        from focus import conviction_summary
        big = {
            "conviction_pct": 72.0,
            "pure_buy": 50.0,
            "pure_buy_whale": 30.0,
            "pure_buy_dolphin": 20.0,
            "n_pure": 4,
            "lh_buy": 999.0,                # should be dropped
            "trader_buy": 888.0,            # should be dropped
            "tw_buy": 777.0,                # should be dropped
            "pure_sell": 5.0,               # should be dropped
            "n_lh": 10, "n_trader": 6,
        }
        out = conviction_summary(big)
        self.assertEqual(out, {
            "conviction_pct": 72.0,
            "pure_buy_total": 50.0,
            "pure_buy_whale": 30.0,
            "pure_buy_dolphin": 20.0,
            "n_pure": 4,
        })


class SignalsTierSplit(unittest.TestCase):
    """signals.py must define the Tier 1 / Tier 2 split, and the
    _focus_mode() helper must default to ON."""

    def test_tier_lists(self):
        from signals import TIER1_SIGNAL_TYPES, TIER2_SIGNAL_TYPES
        # Tier 1 — these go to Telegram in any mode.
        self.assertIn("accumulation", TIER1_SIGNAL_TYPES)
        self.assertIn("stealth_accumulation", TIER1_SIGNAL_TYPES)
        self.assertIn("distribution", TIER1_SIGNAL_TYPES)
        # Tier 2 — signals.json only, NO Telegram in FOCUS_MODE.
        self.assertIn("bullish_div", TIER2_SIGNAL_TYPES)
        self.assertIn("bearish_div", TIER2_SIGNAL_TYPES)
        # No overlap.
        self.assertEqual(
            TIER1_SIGNAL_TYPES & TIER2_SIGNAL_TYPES, set())

    def test_focus_mode_helper_defaults_on(self):
        """When config.json is missing OR has no focus_mode key, the
        helper must default to ON (focus active, Tier 2 suppressed)."""
        import signals as _s
        old = _s.BASE_DIR
        with tempfile.TemporaryDirectory() as td:
            _s.BASE_DIR = td
            try:
                self.assertTrue(_s._focus_mode())
            finally:
                _s.BASE_DIR = old

    def test_focus_mode_helper_reads_explicit_false(self):
        import signals as _s
        old = _s.BASE_DIR
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "config.json"), "w") as f:
                json.dump({"focus_mode": False}, f)
            _s.BASE_DIR = td
            try:
                self.assertFalse(_s._focus_mode())
            finally:
                _s.BASE_DIR = old


class AppLdivsInit(unittest.TestCase):
    """Regression test for the FOCUS_MODE crash on the CVD path.

    The CVD section of app.py gates the divergence green/red strip
    behind ``if not FOCUS_MODE:`` and then unconditionally checks
    ``if FOCUS_MODE and ldivs:`` below to show a caption. If
    ``ldivs`` is not initialised (because the price series wasn't
    available), this raises NameError and the whole CVD block
    dies.

    We can't import app.py without Streamlit, so we reproduce the
    fix's invariant with a tiny script that reads the file and
    confirms the ``ldivs = []`` line appears BEFORE the
    ``if FOCUS_MODE and ldivs:`` check.
    """

    def test_ldivs_initialised_before_caption(self):
        app_path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            src = f.read()
        # Find both anchors; the init MUST come first.
        init_idx = src.find("ldivs = []")
        # There may be other ldivs =  / ldivs += lines after, but we
        # only care that the *initial* declaration (the one that
        # prevents NameError) sits BEFORE the FOCUS_MODE caption.
        self.assertGreater(init_idx, 0,
                           "app.py must initialise ldivs = [] "
                           "before the FOCUS_MODE caption")
        # Find the caption line that references the FOCUS_MODE+ldivs
        # check; the init must be earlier in the file.
        caption_idx = src.find("if FOCUS_MODE and ldivs:")
        self.assertGreater(init_idx, 0)
        self.assertGreater(caption_idx, 0)
        self.assertLess(init_idx, caption_idx,
                        "ldivs = [] must be declared before the "
                        "FOCUS_MODE caption check")


if __name__ == "__main__":
    unittest.main()
