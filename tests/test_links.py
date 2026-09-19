import unittest
from pathlib import Path
from unittest import mock

import links
from links import (bubblemap_icon_link_html, bubblemaps_v2_url,
                   cvd_shortcut_query,
                   dexscreener_token_url, external_links_html,
                   gmgn_token_url, hawkfi_copy_html, hawkfi_meteora_url,
                   holder_analytic_url,
                   holder_analytic_link_html, meteora_dlmm_url, page_url,
                   page_url_path, pool_links_html,
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

    def test_hawkfi_copy_html(self):
        """📋 copy link HawkFi (permintaan user 2026-09-17: "tambahkan copy
        link hawkfi dibagian scan") — <button> HTML murni (tanpa rerun
        Streamlit) dengan URL pool HawkFi di title + clipboard JS."""
        pool = "D49w4CQmXvbNpBikcpha3XKFbP5HtQjnMTKTqY1tXFLh"
        html_out = hawkfi_copy_html(pool)
        self.assertIn('type="button"', html_out)
        self.assertIn('class="hawkfi-copy-btn"', html_out)
        self.assertIn("navigator.clipboard", html_out)
        self.assertIn("execCommand", html_out)   # fallback konteks non-https
        self.assertIn("onclick=", html_out)
        # URL pool HawkFi tampil di title (HTML-escaped) DAN di JS onclick
        # (entity &#x27; menggantikan kutip tunggal setelah escape atribut).
        self.assertIn(f"Copy link HawkFi: https://www.hawkfi.ag/meteora/{pool}",
                      html_out)
        self.assertIn(f"&#x27;https://www.hawkfi.ag/meteora/{pool}&#x27;",
                      html_out)
        self.assertIn("📋", html_out)
        # Bukan tirai JS mentah: tidak ada `<script>`, tidak ada href pool.
        self.assertNotIn("<script", html_out)
        self.assertNotIn("href=", html_out)

    def test_hawkfi_copy_html_empty_pool(self):
        self.assertEqual(hawkfi_copy_html(""), "")

    def test_bubblemap_icon_link_html(self):
        """🫧 tautan Bubblemaps (permintaan user 2026-09-19: *"hapus tentang
        bubblemap, sisakan hyperlink ke bubblemapnya saja"*).

        Kolom Bubble Map dihapus; yang tersisa hanya anchor ikon ini, dipakai
        kolom **Pool** tabel 🏆 Scan Best Pool. URL-nya URL v2 yang sama dengan
        :func:`bubblemaps_v2_url`, atribut ``href`` di-escape sekali.
        """
        ca = "MintBub"
        html_out = bubblemap_icon_link_html(ca)
        self.assertEqual(
            html_out,
            '<a class="bubblemap-link" href="'
            'https://v2.bubblemaps.io/map?address=MintBub&amp;chain=solana" '
            'target="_blank" rel="noopener noreferrer" '
            'title="Buka Bubble Map di v2.bubblemaps.io">\U0001fae7</a>')
        # Tanpa mint tidak ada tautan (bukan anchor kosong).
        self.assertEqual(bubblemap_icon_link_html(""), "")

    def test_bubblemap_icon_link_html_pakai_url_tersimpan(self):
        """URL laporan bubblemaps yang tersimpan di baris scan lama dipakai.

        Hasil scan 2026-09-18 menyimpan ``row["bubblemap"]["url"]`` — tautan
        baris lama harus tetap mengarah ke map yang sama, bukan dihitung ulang
        dari mint. ``&`` di URL di-escape sekali saat masuk atribut.
        """
        stored = "https://v2.bubblemaps.io/map?address=MintBub&chain=solana"
        html_out = bubblemap_icon_link_html("MintLain", url=stored)
        self.assertIn("address=MintBub&amp;chain=solana", html_out)
        self.assertNotIn("MintLain", html_out)
        # Aman walau URL-nya mengandung karakter yang bisa keluar atribut.
        nakal = bubblemap_icon_link_html("Mint", url='x" onclick="alert(1)')
        self.assertNotIn('onclick="alert(1)"', nakal)

    def test_bubblemap_icon_link_html_mint_aman(self):
        html_out = bubblemap_icon_link_html("abc&def")
        self.assertIn("address=abc%26def", html_out)

    def test_hawkfi_copy_html_encodes_unsafe_pool(self):
        html_out = hawkfi_copy_html("abc&def")
        self.assertIn("https://www.hawkfi.ag/meteora/abc%26def", html_out)
        self.assertNotIn("abc&def'", html_out)

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
