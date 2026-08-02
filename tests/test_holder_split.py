# -*- coding: utf-8 -*-
"""Tests for the Helius-based real-vs-dust holder split helper.

Covers:
  - core.gmgn_token_stat: shape + graceful failure modes (kept: the
    helper is still used by scripts/update_cvd.py — but it is NO LONGER
    a holder-data source for the screener)
  - trending_ui._real_holder_split: per-token Helius full scan
  - trending_ui._format_holder_split_note: HTML note generation
  - trending_ui.enrich_rows_with_holder_split: Helius-only, in-place +
    cached (no GMGN fallback of any kind)
  - app._real_dust_card_html: card-level rendering with the colored
    ratio pill (this is the user-visible feature we just added)

The tests are offline: we monkey-patch the network-touching helpers and
``st.session_state`` so no network or streamlit runtime is required.
"""
import os
import sys
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# core.gmgn_token_stat — shape + failure modes
# ---------------------------------------------------------------------------
def _gmgn_http_patch(**kwargs):
    """Return mock patches for the HTTP client(s) ``gmgn_token_stat`` may
    use: ``curl_cffi.requests`` (its primary path) when importable, plus
    plain ``requests`` (the fallback). Tests stay offline in any env."""
    import requests
    patches = [mock.patch.object(requests, "get", **kwargs)]
    try:
        from curl_cffi import requests as cr
    except ImportError:
        pass
    else:
        patches.append(mock.patch.object(cr, "get", **kwargs))
    return patches


class GmgnTokenStat(unittest.TestCase):
    def test_returns_empty_on_network_failure(self):
        """A network error must NOT raise; it returns an empty dict
        so callers can use a single truthy check."""
        import contextlib
        import requests
        with contextlib.ExitStack() as stack:
            for p in _gmgn_http_patch(
                    side_effect=requests.exceptions.SSLError("boom")):
                stack.enter_context(p)
            from core import gmgn_token_stat
            out = gmgn_token_stat("any-ca")
        self.assertEqual(out, {"holders": [], "total_holders": None,
                               "supply": None, "raw": None})

    def test_returns_empty_on_http_non_200(self):
        import contextlib
        fake_resp = mock.Mock(status_code=503)
        with contextlib.ExitStack() as stack:
            for p in _gmgn_http_patch(return_value=fake_resp):
                stack.enter_context(p)
            from core import gmgn_token_stat
            out = gmgn_token_stat("any-ca")
        self.assertEqual(out["holders"], [])
        self.assertIsNone(out["total_holders"])

    def test_parses_holders_and_total(self):
        """A well-formed response populates holders + total_holders."""
        import contextlib
        fake = {
            "holders": [
                {"address": "A", "amount": "100.0"},
                {"address": "B", "amount": "50.0"},
                {"address": "C", "amount": "5.0"},
            ],
            "holder_count": 1234,
            "total_supply": "1000000",
        }
        fake_resp = mock.Mock(status_code=200,
                              json=mock.Mock(return_value=fake))
        with contextlib.ExitStack() as stack:
            for p in _gmgn_http_patch(return_value=fake_resp):
                stack.enter_context(p)
            from core import gmgn_token_stat
            out = gmgn_token_stat("any-ca")
        self.assertEqual(out["holders"], [["A", 100.0], ["B", 50.0],
                                          ["C", 5.0]])
        self.assertEqual(out["total_holders"], 1234)
        self.assertEqual(out["supply"], 1000000.0)

    def test_falls_back_to_alternate_keys(self):
        """Some GMGN responses put holders under top10_holders."""
        import contextlib
        fake = {
            "top10_holders": [{"address": "X", "amount": "1"}],
            "holders_count": 99,
        }
        fake_resp = mock.Mock(status_code=200,
                              json=mock.Mock(return_value=fake))
        with contextlib.ExitStack() as stack:
            for p in _gmgn_http_patch(return_value=fake_resp):
                stack.enter_context(p)
            from core import gmgn_token_stat
            out = gmgn_token_stat("any-ca")
        self.assertEqual(out["holders"], [["X", 1.0]])
        self.assertEqual(out["total_holders"], 99)


# ---------------------------------------------------------------------------
# trending_ui._real_holder_split — the per-token Helius full scan
# ---------------------------------------------------------------------------
class RealHolderSplit(unittest.TestCase):
    def _row(self, ca="CA1", price=0.001):
        return {"ca": ca, "price": price, "mc": 1_000_000, "holders": 1000}

    def test_missing_price_returns_none(self):
        # If price is 0 we cannot compute USD value, so we skip the
        # note (avoids noisy "n/a" everywhere on a fresh scan).
        from trending_ui import _real_holder_split
        self.assertIsNone(_real_holder_split({"ca": "X", "price": 0},
                                             ("hk",), 5.0))

    def test_missing_ca_returns_none(self):
        from trending_ui import _real_holder_split
        self.assertIsNone(_real_holder_split({"price": 0.001},
                                             ("hk",), 5.0))

    def test_splits_full_holder_list(self):
        """raw_amount amounts are scaled by decimals and compared against
        the USD dust limit at the row's current price."""
        from trending_ui import _real_holder_split

        # price=1.0, dust_limit=5.0, decimals=0 → 6 real, 4 dust
        df = pd.DataFrame({"raw_amount": [float(i + 1) for i in range(10)]})

        with mock.patch("core.get_supply", return_value=(10.0, 0)), \
                mock.patch("core.get_holders", return_value=df):
            out = _real_holder_split(self._row(price=1.0), ("hk",), 5.0)

        self.assertEqual(out["n_real"], 6)     # amounts 5..10
        self.assertEqual(out["n_dust"], 4)     # amounts 1..4
        self.assertAlmostEqual(out["ratio"], 6 / 4, places=4)
        self.assertEqual(out["total_holders"], 10)
        self.assertEqual(out["src"], "Helius full scan")

    def test_helius_failure_returns_none_no_gmgn_fallback(self):
        """A Helius failure must NOT fall back to GMGN — GMGN holder data
        was dropped as inaccurate. The row simply gets no split."""
        from trending_ui import _real_holder_split
        with mock.patch("core.get_supply", side_effect=RuntimeError("boom")):
            self.assertIsNone(_real_holder_split(self._row(), ("hk",), 5.0))

    def test_empty_holder_list_returns_none(self):
        from trending_ui import _real_holder_split
        with mock.patch("core.get_supply", return_value=(10.0, 0)), \
                mock.patch("core.get_holders",
                           return_value=pd.DataFrame(columns=["raw_amount"])):
            self.assertIsNone(_real_holder_split(self._row(), ("hk",), 5.0))


# ---------------------------------------------------------------------------
# trending_ui._format_holder_split_note — the inline note string
# ---------------------------------------------------------------------------
class FormatHolderSplitNote(unittest.TestCase):
    def test_returns_empty_when_no_holder_split(self):
        from trending_ui import _format_holder_split_note
        self.assertEqual(_format_holder_split_note({}), "")
        self.assertEqual(_format_holder_split_note({"holder_split": None}),
                         "")

    def test_includes_real_dust_ratio_and_source_label(self):
        from trending_ui import _format_holder_split_note
        row = {"holder_split": {"n_real": 6, "n_dust": 994,
                                "ratio": 6/994, "src": "Helius full scan"}}
        out = _format_holder_split_note(row)
        self.assertIn("6", out)               # n_real
        self.assertIn("994", out)             # n_dust
        self.assertIn("💎 Real", out)
        self.assertIn("🪙 Dust", out)
        self.assertIn("Helius full scan", out)

    def test_color_codes_healthy_ratio_green(self):
        from trending_ui import _format_holder_split_note
        row = {"holder_split": {"n_real": 100, "n_dust": 100,
                                "ratio": 1.0, "src": "Helius full scan"}}
        out = _format_holder_split_note(row)
        self.assertIn("#22c55e", out)  # green

    def test_color_codes_low_ratio_red(self):
        from trending_ui import _format_holder_split_note
        row = {"holder_split": {"n_real": 1, "n_dust": 1000,
                                "ratio": 0.001, "src": "Helius full scan"}}
        out = _format_holder_split_note(row)
        self.assertIn("#ef4444", out)  # red

    def test_color_codes_infinite_ratio_green(self):
        """When n_dust = 0 the ratio is ∞; that should be green and
        display as the literal '∞' symbol (not 'inf%')."""
        from trending_ui import _format_holder_split_note
        row = {"holder_split": {"n_real": 5, "n_dust": 0,
                                "ratio": float("inf"),
                                "src": "Helius full scan"}}
        out = _format_holder_split_note(row)
        self.assertIn("∞", out)
        self.assertIn("#22c55e", out)


# ---------------------------------------------------------------------------
# trending_ui.enrich_rows_with_holder_split — Helius-only, in-place + cached
# ---------------------------------------------------------------------------
class EnrichRowsWithHolderSplit(unittest.TestCase):
    def test_empty_rows_returns_empty(self):
        from trending_ui import enrich_rows_with_holder_split
        self.assertEqual(enrich_rows_with_holder_split([]), [])

    def test_no_helius_keys_returns_rows_untouched(self):
        """Helius is the ONLY holder source: without keys no split is
        attached at all (the inaccurate GMGN fallbacks were removed)."""
        from trending_ui import enrich_rows_with_holder_split

        rows = [{"ca": "A", "price": 1.0}]
        with mock.patch("trending_ui.st") as fake_st:
            fake_st.session_state = {}
            result = enrich_rows_with_holder_split(rows, helius_keys=None)
        self.assertNotIn("holder_split", result[0])

    def test_attaches_holder_split_to_each_row(self):
        from trending_ui import enrich_rows_with_holder_split

        rows = [{"ca": "A", "price": 1.0},
                {"ca": "B", "price": 1.0}]

        def fake_split(row, _keys, dust_limit_usd=5.0):
            return {"n_real": 5, "n_dust": 10,
                    "ratio": 0.5, "src": "Helius full scan",
                    "total_holders": 100, "supply": 1e6,
                    "dust_limit": 5.0}

        with mock.patch("trending_ui._real_holder_split",
                        side_effect=fake_split):
            with mock.patch("trending_ui.st") as fake_st:
                fake_st.session_state = {}
                # The spinner needs __enter__/__exit__.
                fake_st.spinner.return_value.__enter__ = mock.Mock()
                fake_st.spinner.return_value.__exit__ = mock.Mock()
                result = enrich_rows_with_holder_split(rows,
                                                       helius_keys=("hk",))

        self.assertEqual(len(result), 2)
        for r in result:
            self.assertIn("holder_split", r)
            self.assertEqual(r["holder_split"]["n_real"], 5)
            self.assertEqual(r["holder_split"]["src"], "Helius full scan")

    def test_uses_session_cache_for_repeat_cas(self):
        """Second call for the same CA must not re-run the Helius scan."""
        from trending_ui import enrich_rows_with_holder_split

        rows = [{"ca": "A", "price": 1.0}]

        with mock.patch("trending_ui._real_holder_split",
                        return_value={"n_real": 1, "n_dust": 0,
                                      "ratio": float("inf"),
                                      "src": "Helius full scan",
                                      "total_holders": 1, "supply": 1e6,
                                      "dust_limit": 5.0}) as m_split:
            with mock.patch("trending_ui.st") as fake_st:
                fake_st.session_state = {}
                fake_st.spinner.return_value.__enter__ = mock.Mock()
                fake_st.spinner.return_value.__exit__ = mock.Mock()
                enrich_rows_with_holder_split(rows, helius_keys=("hk",))
            # Reset call count and run again with cached value
            m_split.reset_mock()
            with mock.patch("trending_ui.st") as fake_st:
                fake_st.session_state = {
                    "screener_holder_split_helius_v1":
                        {"A": {"n_real": 99, "n_dust": 0,
                               "ratio": float("inf"),
                               "src": "Helius full scan",
                               "total_holders": 1, "supply": 1e6,
                               "dust_limit": 5.0}}}
                # Cache hit → the spinner block is not even entered.
                result = enrich_rows_with_holder_split(rows,
                                                       helius_keys=("hk",))
            # Cache hit → no fresh Helius scan
            m_split.assert_not_called()
            self.assertEqual(result[0]["holder_split"]["n_real"], 99)


# ---------------------------------------------------------------------------
# app._real_dust_card_html — the big card-level render
# ---------------------------------------------------------------------------
class AppRealDustCardHtml(unittest.TestCase):
    """The card-level helper lives in app.py and depends on streamlit
    (which is not always installed in the test env), so we extract it
    by ``exec``-ing the function body in an isolated namespace. This
    still gives us a real-execution test of the rendered HTML."""

    def _load_helper(self):
        """Pull only the ``_real_dust_card_html`` function out of
        app.py without importing the rest of the module (which
        needs streamlit). Returns a callable.

        We extract the function by walking lines and stopping at the
        first non-empty line that has less indentation than the def
        itself (a clean, robust way to bound a Python function body
        even when the source uses mixed whitespace)."""
        import ast as _ast
        app_path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            src = f.read()
        module = _ast.parse(src)
        for node in module.body:
            if (isinstance(node, _ast.FunctionDef)
                    and node.name == "_real_dust_card_html"):
                code = _ast.get_source_segment(src, node)
                ns = {"REAL_RATIO_OK": 0.50, "REAL_RATIO_MIN": 0.30}
                exec(code, ns)               # noqa: S102
                return ns["_real_dust_card_html"]
        raise RuntimeError("_real_dust_card_html not found in app.py")

    def test_card_html_includes_real_dust_ratio_pill(self):
        fn = self._load_helper()
        html = fn({"n_real": 1470, "n_dust": 1634, "ratio": 0.9,
                   "dust_limit": 5.0})
        self.assertIn("1,470", html)
        self.assertIn("1,634", html)
        self.assertIn("90%", html)            # ratio rounded
        self.assertIn("💎 Real", html)
        self.assertIn("🪙 Dust", html)
        # Healthy ratio → green pill
        self.assertIn("#22c55e", html)

    def test_card_html_red_pill_for_unhealthy(self):
        fn = self._load_helper()
        html = fn({"n_real": 50, "n_dust": 5000, "ratio": 0.01,
                   "dust_limit": 5.0})
        self.assertIn("#ef4444", html)        # red
        self.assertIn("1%", html)              # 0.01 * 100 = 1%

    def test_card_html_yellow_pill_for_borderline(self):
        fn = self._load_helper()
        html = fn({"n_real": 200, "n_dust": 500, "ratio": 0.4,
                   "dust_limit": 5.0})
        self.assertIn("#facc15", html)        # yellow
        self.assertIn("40%", html)

    def test_card_html_infinite_ratio_uses_infinity_symbol(self):
        fn = self._load_helper()
        html = fn({"n_real": 100, "n_dust": 0, "ratio": float("inf"),
                   "dust_limit": 5.0})
        self.assertIn("∞", html)
        self.assertIn("#22c55e", html)         # green = healthy

    def test_card_html_empty_when_dict_missing(self):
        fn = self._load_helper()
        self.assertEqual(fn(None), "")
        self.assertEqual(fn({}), "")


if __name__ == "__main__":
    unittest.main()
