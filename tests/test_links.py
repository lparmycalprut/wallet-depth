"""External-link helpers retained by Best Pool and CVD."""
from __future__ import annotations

import unittest

import links


class LinkTest(unittest.TestCase):
    def test_token_urls_are_encoded(self):
        ca = "abc&def?x=1"
        self.assertEqual(links.gmgn_token_url(ca),
                         "https://gmgn.ai/sol/token/abc%26def%3Fx%3D1")
        self.assertEqual(links.dexscreener_token_url(ca),
                         "https://dexscreener.com/solana/abc%26def%3Fx%3D1")
        self.assertEqual(links.cvd_shortcut_query(ca),
                         "?mint=abc%26def%3Fx%3D1")

    def test_pool_links_include_every_retained_action(self):
        body = links.pool_links_html("Pool A", mint="Mint&B")
        self.assertIn("https://app.meteora.ag/dlmm/Pool%20A", body)
        self.assertIn("https://www.hawkfi.ag/meteora/Pool%20A", body)
        self.assertIn('class="hawkfi-copy-btn"', body)
        self.assertIn("v2.bubblemaps.io/map?address=Mint%26B", body)
        self.assertIn('target="_blank"', body)

    def test_empty_inputs_do_not_make_dangling_links(self):
        self.assertEqual(links.external_links_html(""), "")
        self.assertEqual(links.pool_links_html(""), "")
        self.assertEqual(links.bubblemap_icon_link_html(""), "")
        self.assertEqual(links.solscan_account_html(""), "")

    def test_solscan_html_escapes_label(self):
        body = links.solscan_account_html("wallet", text="<wallet>")
        self.assertIn("https://solscan.io/account/wallet", body)
        self.assertIn("&lt;wallet&gt;", body)


if __name__ == "__main__":
    unittest.main()
