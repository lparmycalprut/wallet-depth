import unittest

from links import (cvd_shortcut_query, dexscreener_token_url,
                   external_links_html, gmgn_token_url, hawkfi_meteora_url,
                   meteora_dlmm_url, pool_links_html, safe_url_part,
                   solscan_account_html, solscan_account_url,
                   token_link_lines)


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

    def test_meteora_and_hawkfi_pool_urls(self):
        pool = "D49w4CQmXvbNpBikcpha3XKFbP5HtQjnMTKTqY1tXFLh"
        self.assertEqual(
            meteora_dlmm_url(pool), f"https://app.meteora.ag/dlmm/{pool}")
        self.assertEqual(
            hawkfi_meteora_url(pool),
            f"https://www.hawkfi.ag/meteora/{pool}")
        html_out = pool_links_html(pool)
        self.assertIn(f"https://app.meteora.ag/dlmm/{pool}", html_out)
        self.assertIn(f"https://www.hawkfi.ag/meteora/{pool}", html_out)
        self.assertIn("target=\"_blank\"", html_out)
        self.assertIn("rel=\"noopener", html_out)
        self.assertNotIn("\\", html_out)

    def test_pool_links_html_empty_pool(self):
        self.assertEqual(pool_links_html(""), "")

    def test_pool_links_html_encodes_unsafe_pool(self):
        html_out = pool_links_html("abc&def")
        self.assertIn("https://app.meteora.ag/dlmm/abc%26def", html_out)
        self.assertIn("https://www.hawkfi.ag/meteora/abc%26def", html_out)

    def test_solscan_account_url_uses_full_address(self):
        self.assertEqual(
            solscan_account_url(self.CA),
            f"https://solscan.io/account/{self.CA}")
        html_out = solscan_account_html(self.CA)
        self.assertIn(self.CA, html_out)
        self.assertIn("target=\"_blank\"", html_out)
        self.assertIn("rel=\"noopener", html_out)

    def test_solscan_account_url_encodes_unsafe(self):
        html_out = solscan_account_html("abc&def")
        self.assertIn("https://solscan.io/account/abc%26def", html_out)
        self.assertNotIn("abc&def", html_out)

    def test_token_link_lines_gmgn_dan_dexscreener(self):
        self.assertEqual(
            token_link_lines(self.CA),
            [f"\U0001f517 GMGN: https://gmgn.ai/sol/token/{self.CA}",
             f"\U0001f986 DexScreener: "
             f"https://dexscreener.com/solana/{self.CA}"])

    def test_token_link_lines_sumber_url_sama_dengan_helper(self):
        lines = token_link_lines(self.CA)
        self.assertIn(gmgn_token_url(self.CA), lines[0])
        self.assertIn(dexscreener_token_url(self.CA), lines[1])

    def test_token_link_lines_kosong_bila_tidak_ada_address(self):
        for empty in ("", None, "   ", 0):
            self.assertEqual(token_link_lines(empty), [], empty)

    def test_token_link_lines_mengencode_address_berbahaya(self):
        lines = token_link_lines(" a?b&c d#e/ ")
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertNotIn(" ", line.split(": ", 1)[1])
            self.assertNotIn("?", line.split(": ", 1)[1])
            self.assertNotIn("#", line.split(": ", 1)[1])
        self.assertIn("a%3Fb%26c%20d%23e", lines[0])


if __name__ == "__main__":
    unittest.main()
