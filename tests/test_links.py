import unittest
from pathlib import Path
from unittest import mock

import links
from links import (blockscout_token_url, cvd_shortcut_query,
                   dexscreener_token_url, external_links_html,
                   gmgn_token_url, hawkfi_meteora_url, holder_analytic_url,
                   holder_analytic_link_html, meteora_dlmm_url, page_url,
                   page_url_path, pool_links_html, rh_scan_token_url,
                   safe_url_part, solscan_account_html, solscan_account_url,
                   token_link_lines)

PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"


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


class LinksEvmTest(unittest.TestCase):
    CA = "0x8490acd2d52d0ebd34cb13e01bd9a9380b36411d"

    def test_dexscreener_robinhood_url(self):
        self.assertEqual(
            dexscreener_token_url(self.CA),
            f"https://dexscreener.com/robinhood/{self.CA}")

    def test_rh_scan_dan_blockscout_urls(self):
        self.assertEqual(
            rh_scan_token_url(self.CA),
            f"https://rh-scan.com/token/{self.CA}")
        self.assertEqual(
            blockscout_token_url(self.CA),
            f"https://robinhoodchain.blockscout.com/token/{self.CA}")

    def test_external_links_html_evm(self):
        html_out = external_links_html(self.CA)
        self.assertIn(f"https://rh-scan.com/token/{self.CA}", html_out)
        self.assertIn(f"https://dexscreener.com/robinhood/{self.CA}", html_out)
        self.assertIn(
            f"https://robinhoodchain.blockscout.com/token/{self.CA}", html_out)
        self.assertIn("\U0001f50dRH", html_out)
        self.assertIn("\U0001f986Dex", html_out)
        self.assertIn("\U0001f310Blockscout", html_out)
        self.assertNotIn("gmgn.ai/sol/token/", html_out)
        self.assertIn("target=\"_blank\"", html_out)
        self.assertIn("rel=\"noopener", html_out)

    def test_solscan_account_routes_evm_to_blockscout(self):
        self.assertEqual(
            solscan_account_url(self.CA),
            f"https://robinhoodchain.blockscout.com/address/{self.CA}")
        html_out = solscan_account_html(self.CA)
        self.assertIn(
            f"https://robinhoodchain.blockscout.com/address/{self.CA}",
            html_out)
        self.assertIn("Blockscout", html_out)
        self.assertNotIn("solscan.io/account/", html_out)

    def test_token_link_lines_evm(self):
        lines = token_link_lines(self.CA)
        self.assertEqual(len(lines), 3)
        self.assertIn(f"https://rh-scan.com/token/{self.CA}", lines[0])
        self.assertIn(f"https://dexscreener.com/robinhood/{self.CA}", lines[1])
        self.assertIn(
            f"https://robinhoodchain.blockscout.com/token/{self.CA}", lines[2])


class HolderDeepLinkTest(unittest.TestCase):
    """Tautan 🧮 harus memakai slug halaman Streamlit, bukan path file."""

    SOL = "So11111111111111111111111111111111111111112"
    EVM = "0x1a3876a32619cf2668e91ebcd90a596537ec8695"

    def test_url_solana_dan_evm(self):
        self.assertEqual(holder_analytic_url(self.SOL),
                         f"/Holder?mint={self.SOL}")
        self.assertEqual(holder_analytic_url(self.EVM),
                         f"/Holder?mint={self.EVM}")
        self.assertEqual(holder_analytic_url(f"  {self.EVM}  "),
                         f"/Holder?mint={self.EVM}")

    def test_url_kosong(self):
        for empty in ("", None, "   "):
            self.assertEqual(holder_analytic_url(empty), "")
            self.assertEqual(holder_analytic_link_html(empty), "")

    def test_anchor_baru_tab_dengan_mint_terencode(self):
        html_out = holder_analytic_link_html("abc&def?x=1")
        self.assertIn('target="_blank"', html_out)
        self.assertIn('rel="noopener', html_out)
        self.assertIn('href="/Holder?mint=abc%26def%3Fx%3D1"', html_out)
        self.assertNotIn("pages/", html_out)
        self.assertNotIn("\\", html_out)

    def test_anchor_tidak_lagi_mengarah_ke_path_file(self):
        """Regresi: ``pages/5_🧮_Holder.py`` bukan route → app balas 404."""
        html_out = holder_analytic_link_html(self.SOL)
        self.assertNotIn("5_\U0001f9ee_Holder.py", html_out)

    def test_slug_sama_dengan_streamlit(self):
        """Slug harus sama dengan yang dihitung Streamlit untuk tiap halaman."""
        try:
            from streamlit.source_util import page_icon_and_name
        except Exception:  # pragma: no cover - streamlit selalu ada di suite ini
            self.skipTest("streamlit tidak tersedia")
        names = sorted(p.name for p in PAGES_DIR.glob("*.py"))
        self.assertTrue(names, "folder pages/ kosong?")
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(page_url_path(name),
                                 page_icon_and_name(Path(name))[1])

    def test_slug_semua_halaman(self):
        expected = {"4_📊_CVD.py": "CVD",
                    "5_🧮_Holder.py": "Holder",
                    "6_🔎_Deteksi_Akumulasi.py": "Deteksi_Akumulasi",
                    "7_🚀_Pre-Pump.py": "Pre-Pump"}
        for name, slug in expected.items():
            self.assertEqual(page_url_path("pages/" + name), slug, name)

    def test_slug_idempoten_dan_input_kosong(self):
        self.assertEqual(page_url_path("Holder"), "Holder")
        self.assertEqual(page_url_path("pages/5_🧮_Holder"), "Holder")
        self.assertEqual(page_url_path(""), "")
        self.assertEqual(page_url_path(None), "")

    def test_halaman_tanpa_nomor_tetap_punya_slug(self):
        self.assertEqual(page_url_path("Lima_Halaman.py"), "Lima_Halaman")

    def test_query_params_diurlencode(self):
        self.assertEqual(page_url("pages/5_🧮_Holder.py", mint="a b&c"),
                         "/Holder?mint=a%20b%26c")
        self.assertEqual(page_url("pages/5_🧮_Holder.py"), "/Holder")

    def test_base_url_path_dihormati(self):
        with mock.patch.object(links, "base_url_path",
                               return_value="/wallet-depth"):
            self.assertEqual(holder_analytic_url(self.SOL),
                             f"/wallet-depth/Holder?mint={self.SOL}")

    def test_base_url_path_dari_konfigurasi_streamlit(self):
        with mock.patch("streamlit.config.get_option",
                        return_value="dashboard"):
            self.assertEqual(links.base_url_path(), "/dashboard")
        with mock.patch("streamlit.config.get_option", return_value=None):
            self.assertEqual(links.base_url_path(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
