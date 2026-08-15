import unittest

from links import (cvd_shortcut_query, dexscreener_token_url,
                   external_links_html, gmgn_token_url, safe_url_part)


class LinksTest(unittest.TestCase):
    CA = "So11111111111111111111111111111111111111112"

    def test_gmgn_token_url(self):
        self.assertEqual(
            gmgn_token_url(self.CA),
            f"https://gmgn.ai/sol/token/{self.CA}")

    def test_dexscreener_token_url(self):
        self.assertEqual(
            dexscreener_token_url(self.CA),
            f"https://dexscreener.com/solana/{self.CA}")

    def test_ca_is_url_safe_when_embedded(self):
        nasty = "a?b&c d#e/так"
        encoded = safe_url_part(nasty)
        self.assertNotIn(" ", encoded)
        self.assertNotIn("?", encoded)
        self.assertNotIn("&", encoded)
        self.assertNotIn("#", encoded)
        self.assertNotIn("/", encoded)
        # round-trip survives path placement
        self.assertIn(encoded, gmgn_token_url(nasty))
        self.assertIn(encoded, dexscreener_token_url(nasty))

    def test_base58_ca_unchanged(self):
        # Normal Solana base58 addresses are unreserved and stay as-is.
        self.assertEqual(safe_url_part(self.CA), self.CA)

    def test_cvd_shortcut_query(self):
        self.assertEqual(cvd_shortcut_query(self.CA), f"?mint={self.CA}")

    def test_external_links_html_opens_new_tab_and_encodes(self):
        html_out = external_links_html("abc&def")
        self.assertIn("target=\"_blank\"", html_out)
        self.assertIn("rel=\"noopener", html_out)
        self.assertIn("https://gmgn.ai/sol/token/abc%26def", html_out)
        self.assertIn("https://dexscreener.com/solana/abc%26def", html_out)

    def test_external_links_html_empty_ca(self):
        self.assertEqual(external_links_html(""), "")


if __name__ == "__main__":
    unittest.main()
