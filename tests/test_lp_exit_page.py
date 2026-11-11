# -*- coding: utf-8 -*-
"""Tes halaman 🚪 Cek LP Keluar (file, verdict_level, AppTest tanpa jaringan)."""
import sys
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lp_exit_check"))

import lp_exit_check as lxc  # noqa: E402
import lp_exit_ui  # noqa: E402

PAGE = ROOT / "pages_archived" / "12_🚪_Cek_LP_Keluar.py"
CA = "9VZerdNL1x6EjetDqRnh5bYcdmk1y8sLAGs1ybzGpump"


class PageFileTest(unittest.TestCase):
    def test_halaman_ada_dan_tidak_mengimpor_best_pool_atau_sweep(self):
        self.assertTrue(PAGE.exists())
        body = PAGE.read_text(encoding="utf-8")
        self.assertIn("from lp_exit_ui import render_lp_exit_page", body)
        imports = [line.lower() for line in body.splitlines()
                   if line.lstrip().startswith(("import ", "from "))]
        for forbidden in ("sweep", "best_pool", "telegram"):
            self.assertFalse(any(forbidden in line for line in imports), forbidden)


class VerdictLevelTest(unittest.TestCase):
    def test_setiap_verdict_punya_level(self):
        self.assertEqual(lp_exit_ui.verdict_level(lxc.VERDICT_NONE), "success")
        self.assertEqual(lp_exit_ui.verdict_level(lxc.VERDICT_EARLIER), "warning")
        self.assertEqual(lp_exit_ui.verdict_level(lxc.VERDICT_RECENT), "error")
        self.assertEqual(lp_exit_ui.verdict_level(lxc.VERDICT_DATA), "info")
        self.assertEqual(lp_exit_ui.verdict_level(lxc.VERDICT_NO_POOL), "info")
        self.assertEqual(lp_exit_ui.verdict_level("apa saja"), "info")


class AppTestTest(unittest.TestCase):
    def _app(self):
        at = AppTest.from_file(str(PAGE), default_timeout=30)
        at.run()
        return at

    def test_halaman_tampil_tanpa_exception(self):
        at = self._app()
        self.assertFalse(at.exception)
        self.assertTrue(any("Belum ada hasil" in i.value for i in at.info))

    def test_ca_salah_menampilkan_error_input(self):
        at = self._app()
        at.text_input[0].input("abc")
        at.button[0].click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("valid" in e.value for e in at.error))

    def test_verdict_lp_keluar_tampil_sebagai_error(self):
        from unittest import mock

        def fake_run(ca):
            rows = {w: [{"pool_address": "P1", "name": "X-SOL",
                         "token_x": {"address": ca, "symbol": "X"},
                         "token_y": {"address": "So1", "symbol": "SOL"},
                         "tvl": 34055.0, "total_deposits": 120202.0,
                         "total_withdraws": 154788.0, "net_deposits": -34586.0}]
                    for w in lxc.WINDOWS}
            return lxc.analyze(ca, rows)

        with mock.patch.object(lp_exit_ui, "_cached_run", side_effect=fake_run):
            at = self._app()
            at.text_input[0].input(CA)
            at.button[0].click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any(lxc.VERDICT_RECENT in e.value for e in at.error))
        self.assertEqual(len(at.table), 1)


if __name__ == "__main__":
    unittest.main()
