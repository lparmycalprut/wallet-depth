"""Coverage for token identity layout in Trending and Degen listings."""
from __future__ import annotations

import unittest
from unittest import mock

try:  # Streamlit is optional in the minimal test environment.
    import trending_ui
    from trending_ui import _navigate_to_cvd, _token_identity_html
except ModuleNotFoundError as exc:
    if exc.name not in {"streamlit", "requests"}:
        raise
    _token_identity_html = None
    _navigate_to_cvd = None
    trending_ui = None


@unittest.skipIf(_token_identity_html is None, "UI dependencies are not installed")
class TrendingTokenLayoutTest(unittest.TestCase):
    def test_token_name_and_ca_are_separate_block_lines(self):
        rendered = _token_identity_html("LICKINGCAT", "EjD5Y9NVabcdefgh")
        self.assertIn(
            '<div class="trending-symbol">$LICKINGCAT</div>'
            '<div class="trending-mint">EjD5Y9NV…</div>',
            rendered,
        )

    def test_token_identity_is_html_escaped(self):
        rendered = _token_identity_html("<cat>", "ab&cdefgh")
        self.assertIn("$&lt;CAT&gt;", rendered)
        self.assertIn("ab&amp;cdefg…", rendered)
        self.assertNotIn("$<CAT>", rendered)


@unittest.skipIf(_navigate_to_cvd is None,
                 "UI dependencies are not installed")
class TrendingNavigateCvdTest(unittest.TestCase):
    CA = "So11111111111111111111111111111111111111112"

    def test_navigate_uses_query_params_not_url_suffix(self):
        """st.switch_page must receive a page path, not ``page?mint=...``."""
        app_state = {}
        with mock.patch("streamlit.session_state", app_state), \
             mock.patch("streamlit.switch_page") as switch:
            _navigate_to_cvd(self.CA)
        switch.assert_called_once_with(
            "pages/4_📊_CVD.py", query_params={"mint": self.CA})
        self.assertEqual(app_state["effort_mint"], self.CA)


if __name__ == "__main__":
    unittest.main()
