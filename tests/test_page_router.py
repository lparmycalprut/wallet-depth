# -*- coding: utf-8 -*-
"""Router deep-link ``?mint=`` / ``?page=`` untuk app multipage ``pages/``.

Bagian resolusi murni (tanpa Streamlit) + satu uji AppTest bahwa halaman utama
memang memantulkan ``?mint=`` ke Holder Analytic lewat ``st.switch_page``.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import page_router as pr

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")

SOL = "So11111111111111111111111111111111111111112"
EVM = "0x1a3876a32619cf2668e91ebcd90a596537ec8695"
HOLDER = "pages/5_🧮_Holder.py"
CVD = "pages/4_📊_CVD.py"
DETEKSI = "pages/6_🔎_Deteksi_Akumulasi.py"
PREPUMP = "pages/7_🚀_Pre-Pump.py"


class ResolveTest(unittest.TestCase):
    def test_token_saja_ke_holder(self):
        for mint in (SOL, EVM):
            out = pr.resolve({"mint": [mint]})
            self.assertEqual(out["page"], HOLDER)
            self.assertEqual(out["params"], {"mint": mint})

    def test_kunci_address_alternatif(self):
        for key in ("mint", "ca", "token", "address"):
            self.assertEqual(pr.resolve({key: EVM})["page"], HOLDER, key)

    def test_page_memilih_halaman(self):
        cases = {
            "cvd": CVD,
            "4": CVD,
            "4_📊_cvd": CVD,
            "pages/4_📊_CVD.py": CVD,
            "holder": HOLDER,
            "5_🧮_holder": HOLDER,
            "Holder": HOLDER,          # kapital berbeda tetap dikenali
            "pages/5_🧮_Holder.py": HOLDER,   # tautan lama (path file)
            "dust": HOLDER,
            "analytic": HOLDER,
            "deteksi_akumulasi": DETEKSI,
            "deteksi-akumulasi": DETEKSI,
            "akumulasi": DETEKSI,
            "6": DETEKSI,
            "pre-pump": PREPUMP,
            "prepump": PREPUMP,
            "7": PREPUMP,
        }
        for value, expected in cases.items():
            self.assertEqual(pr.resolve({"page": value}).get("page"), expected,
                             value)

    def test_page_dan_mint_bersama(self):
        out = pr.resolve({"page": "cvd", "mint": SOL})
        self.assertEqual(out["page"], CVD)
        self.assertEqual(out["params"], {"mint": SOL})

    def test_tanpa_param_tidak_di_router(self):
        for query in ({}, {"mint": ""}, {"page": ""}, {"page": None}):
            self.assertEqual(pr.resolve(query), {}, query)

    def test_halaman_utama_dan_nilai_asing_dibiarkan(self):
        junk = {"page": "tidak-ada", "mint": "nonsense"}
        for query in ({"page": "main"}, {"page": "dashboard"},
                      {"page": "index"}, {"mint": "nonsense"},
                      {"mint": "0x123"}, junk):
            self.assertEqual(pr.resolve(query), {}, query)

    def test_page_tidak_dikenali_dengan_token_tetap_ke_holder(self):
        """Target asing + CA valid: jangan diam, pakai default Holder."""
        out = pr.resolve({"page": "entah-apa", "mint": EVM})
        self.assertEqual(out["page"], HOLDER)
        self.assertEqual(out["params"], {"mint": EVM})

    def test_mint_list_ambil_nilai_terakhir(self):
        out = pr.resolve({"mint": [SOL, EVM]})
        self.assertEqual(out["mint"], EVM)

    def test_invalid_ca_format(self):
        self.assertTrue(pr.is_valid_ca(SOL))
        self.assertTrue(pr.is_valid_ca(EVM))
        self.assertTrue(pr.is_valid_ca("0x" + "a" * 40))
        for bad in ("", None, "0x", "0x" + "z" * 40, "hello world",
                    "l" * 44, "https://example.com/?a=1", "../etc/passwd"):
            self.assertFalse(pr.is_valid_ca(bad), bad)

    def test_alias_hanya_dari_folder_pages(self):
        """Registry dibangun dari file nyata — tidak ada path hardcoded basi."""
        aliases = pr.known_pages()
        for name in sorted(p.name for p in (ROOT / "pages").glob("*.py")):
            rel = f"pages/{name}"
            self.assertIn(rel, aliases.values(), name)
        self.assertNotIn("pages/Tidak_Ada.py", aliases.values())
        self.assertEqual(aliases.get("main"), None)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class ApplyTest(unittest.TestCase):
    def _offline_app(self):
        patches = (
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value={"tokens": {}}),
            mock.patch("holder_history.pull_holder_history", return_value=None),
            mock.patch("robinhood_watchlist.load_watchlist", return_value={}),
            mock.patch("robinhood_watchlist.load_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("robinhood_watchlist.load_history",
                       return_value={"updated_at": None, "tokens": {}}),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60)
        return app

    def _run(self, query_params):
        app = self._offline_app()
        app.query_params = dict(query_params)
        with mock.patch("streamlit.switch_page") as switch:
            app.run()
        return app, switch

    def test_main_page_switch_page_ke_holder(self):
        app, switch = self._run({"mint": [EVM]})
        self.assertEqual(len(app.exception), 0)
        switch.assert_called_once_with(HOLDER, query_params={"mint": EVM})

    def test_halaman_tanpa_token_tidak_berpindah(self):
        app, switch = self._run({})
        self.assertEqual(len(app.exception), 0)
        switch.assert_not_called()

    def test_token_sampah_tidak_berpindah(self):
        app, switch = self._run({"mint": ["<script>alert(1)</script>"]})
        self.assertEqual(len(app.exception), 0)
        switch.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
