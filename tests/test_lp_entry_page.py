# -*- coding: utf-8 -*-
"""Tes halaman 🧭 Cek Entri LP (tanpa jaringan).

Tes yang memakai Streamlit dilewati bila paket streamlit tidak terpasang.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "pages_archived" / "11_🧭_Cek_Entri_LP.py"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


class PageFileTest(unittest.TestCase):
    def test_halaman_ada_dan_tidak_mengimpor_sweep_atau_best_pool(self):
        self.assertTrue(PAGE.exists())
        body = PAGE.read_text(encoding="utf-8")
        self.assertIn("from lp_entry_ui import render_lp_entry_page", body)
        imports = [line.lower() for line in body.splitlines()
                   if line.lstrip().startswith(("import ", "from "))]
        for forbidden in ("sweep", "best_pool_ui", "telegram"):
            self.assertFalse(any(forbidden in line for line in imports), forbidden)

    def test_app_utama_tidak_mengimpor_modul_baru(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("lp_entry", app)


@unittest.skipUnless(HAS_STREAMLIT, "streamlit tidak terpasang")
class VerdictLevelTest(unittest.TestCase):
    def test_level_per_verdict(self):
        sys.path.insert(0, str(ROOT))
        import lp_entry_ui as ui
        import lp_entry_check as lec
        self.assertEqual(ui.verdict_level(lec.VERDICT_GOOD), "success")
        self.assertEqual(ui.verdict_level(lec.VERDICT_WAIT), "warning")
        self.assertEqual(ui.verdict_level(lec.VERDICT_AVOID), "error")
        self.assertEqual(ui.verdict_level(lec.VERDICT_BAD_FEE), "error")
        self.assertEqual(ui.verdict_level(lec.VERDICT_DATA), "info")
        self.assertEqual(ui.verdict_level("apa saja"), "info")


@unittest.skipUnless(HAS_STREAMLIT, "streamlit tidak terpasang")
class PageRunTest(unittest.TestCase):
    def test_ca_tidak_valid_menampilkan_error_tanpa_jaringan(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(PAGE), default_timeout=60).run()
        at.text_input[0].set_value("abc").run()
        at.button[0].click().run()
        self.assertEqual(list(at.exception), [])
        self.assertTrue(any("abc" in e.value for e in at.error))


if __name__ == "__main__":
    unittest.main()
