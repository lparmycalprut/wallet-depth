# -*- coding: utf-8 -*-
"""Header "STOP DEGEN" dihapus dari halaman utama (permintaan user, sesi ini).

Banner merah berkedip di atas card 🏆 Scan ALL tidak lagi dirender, dan CSS-nya ikut dihapus.
Card 🏆 Scan ALL tetap ada.
"""
from __future__ import annotations

import unittest
from pathlib import Path

try:  # dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
CARD_MARK = "## 🏆 Scan ALL"
DEGEN_TEXT = ("STOP DEGEN", "BERTUBI2", "degen-stop")


@unittest.skipIf(AppTest is None, "streamlit belum terpasang")
class NoDegenHeaderPageTest(unittest.TestCase):
    def test_header_stop_degen_tidak_dirender(self):
        app = AppTest.from_file(APP, default_timeout=90).run()
        self.assertEqual(app.exception, [], "halaman utama gagal render")
        body = "\n".join(str(node.value) for node in app.markdown)
        for text in DEGEN_TEXT:
            self.assertNotIn(text, body)
        self.assertIn(CARD_MARK, body)  # card Scan ALL tetap ada

    def test_css_header_stop_degen_dihapus(self):
        import dashboard_components as dc
        self.assertFalse(hasattr(dc, "render_degen_stop_header"))
        self.assertFalse(hasattr(dc, "DEGEN_STOP_LINES"))
        self.assertNotIn("degen-stop", (ROOT / "dashboard_components.py").read_text(encoding="utf-8"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
