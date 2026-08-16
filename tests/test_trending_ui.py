"""Coverage for token identity layout in Trending and Degen listings."""
from __future__ import annotations

import unittest

try:  # Streamlit is optional in the minimal test environment.
    from trending_ui import _token_identity_html
except ModuleNotFoundError as exc:
    if exc.name not in {"streamlit", "requests"}:
        raise
    _token_identity_html = None


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


if __name__ == "__main__":
    unittest.main()
