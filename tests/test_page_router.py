# -*- coding: utf-8 -*-
"""Router deep-link ?mint= / ?page= untuk app multipage pages/."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:
    from streamlit.testing.v1 import AppTest
except Exception:
    AppTest = None

import page_router as pr

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")

SOL = "So11111111111111111111111111111111111111112"
HOLDER = "pages/5_🧮_Holder.py"
# Halaman CVD / Deteksi Akumulasi / Pre-Pump dihapus 2026-09-07; page
# 🦅 Robinhood + page temp dihapus 2026-09-15.
GONE = ("cvd", "4", "pages/4_📊_CVD.py", "deteksi_akumulasi",
        "deteksi-akumulasi", "akumulasi", "pre-pump", "prepump", "7",
        "robinhood", "6", "pages/6_🦅_Robinhood.py", "temp", "8",
        "pages/8_temp.py")


class ResolveTest(unittest.TestCase):
    def test_token_saja_ke_holder(self):
        out = pr.resolve({"mint": [SOL]})
        self.assertEqual(out["page"], HOLDER)
        self.assertEqual(out["params"], {"mint": SOL})

    def test_kunci_address_alternatif(self):
        for key in ("mint", "ca", "token", "address"):
            self.assertEqual(pr.resolve({key: SOL})["page"], HOLDER, key)

    def test_page_memilih_halaman(self):
        cases = {
            "holder": HOLDER,
            "5_🧮_holder": HOLDER,
            "Holder": HOLDER,
            "pages/5_🧮_Holder.py": HOLDER,
            "dust": HOLDER,
            "analytic": HOLDER,
        }
        for value, expected in cases.items():
            self.assertEqual(pr.resolve({"page": value}).get("page"), expected, value)

    def test_page_dan_mint_bersama(self):
        out = pr.resolve({"page": "holder", "mint": SOL})
        self.assertEqual(out["page"], HOLDER)
        self.assertEqual(out["params"], {"mint": SOL})

    def test_halaman_yang_dihapus_tidak_di_router(self):
        for value in GONE:
            self.assertEqual(pr.resolve({"page": value}), {}, value)
        for value in GONE:
            self.assertEqual(pr.resolve({"page": value, "mint": SOL})["page"], HOLDER, value)

    def test_tanpa_param_tidak_di_router(self):
        for query in ({}, {"mint": ""}, {"page": ""}, {"page": None}):
            self.assertEqual(pr.resolve(query), {}, query)

    def test_halaman_utama_dan_nilai_asing_dibiarkan(self):
        junk = {"page": "tidak-ada", "mint": "nonsense"}
        for query in ({"page": "main"}, {"page": "dashboard"}, {"page": "index"}, {"mint": "nonsense"}, {"mint": "0x123"}, junk):
            self.assertEqual(pr.resolve(query), {}, query)

    def test_page_tidak_dikenali_dengan_token_tetap_ke_holder(self):
        out = pr.resolve({"page": "entah-apa", "mint": SOL})
        self.assertEqual(out["page"], HOLDER)
        self.assertEqual(out["params"], {"mint": SOL})

    def test_mint_list_ambil_nilai_terakhir(self):
        other = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        out = pr.resolve({"mint": [SOL, other]})
        self.assertEqual(out["mint"], other)

    def test_invalid_ca_format(self):
        self.assertTrue(pr.is_valid_ca(SOL))
        # Address EVM (0x…) bukan lagi CA yang dikenal: page 🦅 Robinhood dan
        # seluruh dukungan Robinhood Chain dihapus 2026-09-15.
        for bad in ("", None, "0x", "0x" + "a" * 40, "0x" + "z" * 40,
                    "hello world", "l" * 44,
                    "https://example.com/?a=1", "../etc/passwd"):
            self.assertFalse(pr.is_valid_ca(bad), bad)

    def test_alias_hanya_dari_folder_pages(self):
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
            mock.patch("holder_status.load_holder_status", return_value={"updated_at": None, "tokens": {}}),
            mock.patch("holder_history.load_holder_history", return_value={"tokens": {}}),
            mock.patch("holder_history.pull_holder_history", return_value=None),
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
        app, switch = self._run({"mint": [SOL]})
        self.assertEqual(len(app.exception), 0)
        switch.assert_called_once_with(HOLDER, query_params={"mint": SOL})

    def test_halaman_tanpa_token_tidak_berpindah(self):
        app, switch = self._run({})
        self.assertEqual(len(app.exception), 0)
        switch.assert_not_called()

    def test_token_sampah_tidak_berpindah(self):
        app, switch = self._run({"mint": ["<script>alert(1)</script>"]})
        self.assertEqual(len(app.exception), 0)
        switch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
