# -*- coding: utf-8 -*-
"""Tests for the GMGN-based real-vs-dust holder split helper.

Covers:
  - core.gmgn_token_stat: shape + graceful failure modes
  - trending_ui._approximate_holder_split: top-10 split + long-tail
    dust assumption + ratios + edge cases
  - trending_ui._format_holder_split_note: HTML note generation
  - trending_ui.enrich_rows_with_holder_split: in-place + cached
  - app._real_dust_card_html: card-level rendering with the colored
    ratio pill (this is the user-visible feature we just added)

The tests are offline: we monkey-patch ``core.gmgn_token_stat`` and
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
class GmgnTokenStat(unittest.TestCase):
    def test_returns_empty_on_network_failure(self):
        """A network error must NOT raise; it returns an empty dict
        so callers can use a single truthy check."""
        import requests
        with mock.patch.object(requests, "get",
                               side_effect=requests.exceptions.SSLError("boom")):
            from core import gmgn_token_stat
            out = gmgn_token_stat("any-ca")
        self.assertEqual(out, {"holders": [], "total_holders": None,
                               "supply": None, "raw": None})

    def test_returns_empty_on_http_non_200(self):
        import requests
        fake_resp = mock.Mock(status_code=503)
        with mock.patch.object(requests, "get", return_value=fake_resp):
            from core import gmgn_token_stat
            out = gmgn_token_stat("any-ca")
        self.assertEqual(out["holders"], [])
        self.assertIsNone(out["total_holders"])

    def test_parses_holders_and_total(self):
        """A well-formed response populates holders + total_holders."""
        import requests
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
        with mock.patch.object(requests, "get", return_value=fake_resp):
            from core import gmgn_token_stat
            out = gmgn_token_stat("any-ca")
        self.assertEqual(out["holders"], [["A", 100.0], ["B", 50.0],
                                          ["C", 5.0]])
        self.assertEqual(out["total_holders"], 1234)
        self.assertEqual(out["supply"], 1000000.0)

    def test_falls_back_to_alternate_keys(self):
        """Some GMGN responses put holders under top10_holders."""
        import requests
        fake = {
            "top10_holders": [{"address": "X", "amount": "1"}],
            "holders_count": 99,
        }
        fake_resp = mock.Mock(status_code=200,
                              json=mock.Mock(return_value=fake))
        with mock.patch.object(requests, "get", return_value=fake_resp):
            from core import gmgn_token_stat
            out = gmgn_token_stat("any-ca")
        self.assertEqual(out["holders"], [["X", 1.0]])
        self.assertEqual(out["total_holders"], 99)


# ---------------------------------------------------------------------------
# trending_ui._approximate_holder_split — top-10 + long-tail dust
# ---------------------------------------------------------------------------
class ApproximateHolderSplit(unittest.TestCase):
    def _row(self, ca="CA1", price=0.001):
        return {"ca": ca, "price": price, "mc": 1_000_000, "holders": 1000}

    def test_missing_price_returns_none(self):
        # If price is 0 we cannot compute USD value, so we skip the
        # note (avoids noisy "n/a" everywhere on a fresh scan).
        from trending_ui import _approximate_holder_split
        self.assertIsNone(_approximate_holder_split({"ca": "X", "price": 0},
                                                    5.0))

    def test_missing_ca_returns_none(self):
        from trending_ui import _approximate_holder_split
        self.assertIsNone(_approximate_holder_split({"price": 0.001},
                                                    5.0))

    def test_top10_split_when_price_is_known(self):
        """With price=1.0 and 10 holders in the top-10 split:
           - holders with >= 5 tokens: real
           - holders with < 5 tokens: dust
        Long-tail = total_holders - 10 is added to dust (worst case)."""
        from trending_ui import _approximate_holder_split

        fake_holders = [
            [f"w{i}", float(i + 1)] for i in range(10)
        ]  # amounts 1..10; at price=1.0, threshold 5.0
        # 1,2,3,4 → dust (4 holders)
        # 5,6,7,8,9,10 → real (6 holders)
        fake_stat = {"holders": fake_holders, "total_holders": 1000,
                     "supply": None, "raw": None}

        with mock.patch("core.gmgn_token_stat", return_value=fake_stat):
            row = self._row(ca="CA1", price=1.0)
            out = _approximate_holder_split(row, dust_limit_usd=5.0)

        self.assertEqual(out["n_real"], 6)
        # 4 (top-10 dust) + 990 (long-tail) = 994
        self.assertEqual(out["n_dust"], 994)
        self.assertAlmostEqual(out["ratio"], 6 / 994, places=4)
        self.assertEqual(out["n_top_used"], 10)
        self.assertEqual(out["total_holders"], 1000)
        self.assertEqual(out["src"], "GMGN approx")

    def test_no_total_holders_falls_back_to_top10_only(self):
        """When GMGN doesn't report a total, the long-tail = 0
        (we don't make one up). Ratio is then top-only."""
        from trending_ui import _approximate_holder_split

        # w1: 100 tokens × price 1.0 = $100 → real
        # w2:   1 token  × price 1.0 = $1   → dust
        fake_holders = [["w1", 100.0], ["w2", 1.0]]
        fake_stat = {"holders": fake_holders, "total_holders": None,
                     "supply": None, "raw": None}

        with mock.patch("core.gmgn_token_stat", return_value=fake_stat):
            out = _approximate_holder_split(self._row(price=1.0), 5.0)
        self.assertEqual(out["n_real"], 1)   # w1
        self.assertEqual(out["n_dust"], 1)   # w2
        # n_real == n_dust → ratio = 1.0
        self.assertEqual(out["ratio"], 1.0)
        self.assertIsNone(out["total_holders"])

    def test_gmgn_failure_returns_none(self):
        from trending_ui import _approximate_holder_split
        with mock.patch("core.gmgn_token_stat",
                        return_value={"holders": [], "total_holders": None,
                                      "supply": None, "raw": None}):
            self.assertIsNone(_approximate_holder_split(self._row(), 5.0))


# ---------------------------------------------------------------------------
# trending_ui._format_holder_split_note — the inline note string
# ---------------------------------------------------------------------------
class FormatHolderSplitNote(unittest.TestCase):
    def test_returns_empty_when_no_holder_split(self):
        from trending_ui import _format_holder_split_note
        self.assertEqual(_format_holder_split_note({}), "")
        self.assertEqual(_format_holder_split_note({"holder_split": None}),
                         "")

    def test_includes_real_dust_ratio_and_disclaimer(self):
        from trending_ui import _format_holder_split_note
        row = {"holder_split": {"n_real": 6, "n_dust": 994,
                                "ratio": 6/994, "src": "GMGN approx"}}
        out = _format_holder_split_note(row)
        self.assertIn("6", out)               # n_real
        self.assertIn("994", out)             # n_dust
        self.assertIn("💎 Real", out)
        self.assertIn("🪙 Dust", out)
        self.assertIn("GMGN approx", out)     # disclaimer

    def test_color_codes_healthy_ratio_green(self):
        from trending_ui import _format_holder_split_note
        row = {"holder_split": {"n_real": 100, "n_dust": 100,
                                "ratio": 1.0, "src": "GMGN approx"}}
        out = _format_holder_split_note(row)
        self.assertIn("#22c55e", out)  # green

    def test_color_codes_low_ratio_red(self):
        from trending_ui import _format_holder_split_note
        row = {"holder_split": {"n_real": 1, "n_dust": 1000,
                                "ratio": 0.001, "src": "GMGN approx"}}
        out = _format_holder_split_note(row)
        self.assertIn("#ef4444", out)  # red

    def test_color_codes_infinite_ratio_green(self):
        """When n_dust = 0 the ratio is ∞; that should be green and
        display as the literal '∞' symbol (not 'inf%')."""
        from trending_ui import _format_holder_split_note
        row = {"holder_split": {"n_real": 5, "n_dust": 0,
                                "ratio": float("inf"),
                                "src": "GMGN approx"}}
        out = _format_holder_split_note(row)
        self.assertIn("∞", out)
        self.assertIn("#22c55e", out)


# ---------------------------------------------------------------------------
# trending_ui.enrich_rows_with_holder_split — in-place + cached
# ---------------------------------------------------------------------------
class EnrichRowsWithHolderSplit(unittest.TestCase):
    def test_empty_rows_returns_empty(self):
        from trending_ui import enrich_rows_with_holder_split
        self.assertEqual(enrich_rows_with_holder_split([]), [])

    def test_attaches_holder_split_to_each_row(self):
        from trending_ui import enrich_rows_with_holder_split

        rows = [{"ca": "A", "price": 1.0},
                {"ca": "B", "price": 1.0}]

        def fake_approx(row, dust_limit_usd=5.0):
            return {"n_real": 5, "n_dust": 10,
                    "ratio": 0.5, "src": "GMGN approx",
                    "n_top_used": 10, "total_holders": 100}

        with mock.patch("trending_ui._approximate_holder_split",
                        side_effect=fake_approx):
            with mock.patch("trending_ui.st") as fake_st:
                fake_st.session_state = {}
                # The spinner + ThreadPoolExecutor need __enter__/__exit__.
                fake_st.spinner.return_value.__enter__ = mock.Mock()
                fake_st.spinner.return_value.__exit__ = mock.Mock()
                result = enrich_rows_with_holder_split(rows)

        self.assertEqual(len(result), 2)
        for r in result:
            self.assertIn("holder_split", r)
            self.assertEqual(r["holder_split"]["n_real"], 5)

    def test_uses_session_cache_for_repeat_cas(self):
        """Second call for the same CA must not re-fetch GMGN."""
        from trending_ui import enrich_rows_with_holder_split

        rows = [{"ca": "A", "price": 1.0}]

        with mock.patch("trending_ui._approximate_holder_split",
                        return_value={"n_real": 1, "n_dust": 0,
                                      "ratio": float("inf"),
                                      "src": "GMGN approx",
                                      "n_top_used": 1,
                                      "total_holders": 1}) as m_approx:
            with mock.patch("trending_ui.st") as fake_st:
                fake_st.session_state = {}
                fake_st.spinner.return_value.__enter__ = mock.Mock()
                fake_st.spinner.return_value.__exit__ = mock.Mock()
                enrich_rows_with_holder_split(rows)
            # Reset call count and run again with cached value
            m_approx.reset_mock()
            with mock.patch("trending_ui.st") as fake_st:
                fake_st.session_state = {"screener_holder_split":
                                         {"A": {"n_real": 99, "n_dust": 0,
                                                "ratio": float("inf"),
                                                "src": "GMGN approx",
                                                "n_top_used": 1,
                                                "total_holders": 1}}}
                # We still need the spinner wrapper even with cache hit;
                # the function only enters the spinner block when there
                # are new CAs to refresh. Empty cas_to_refresh means
                # no spinner context is entered.
                result = enrich_rows_with_holder_split(rows)
            # Cache hit → no fresh GMGN call
            m_approx.assert_not_called()
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
