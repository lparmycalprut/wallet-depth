# -*- coding: utf-8 -*-
"""Tes main app 🏆 Scan Best Pool (AppTest) dan struktur workflow. Offline."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pool_flow as pf  # noqa: E402
from tests.test_pool_flow import meteora_rows  # noqa: E402

CHOO = "9JZrcAScnGQp7DSV4kBWfmGH2ao31sz5JbJ8cnpZ9uwv"
DACITY_5DC = "5Dc4s9fxxQoPfaMUaxFKB5v1Nh6FPqest7usgyvGXwWw"
LMAO = "EWBCL4hKY6VdzZVcCY7pMPvRhG78koHY6nQnt8EW99Br"


class AppMainTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "pool_flow_state.json"
        self._patches = [
            mock.patch.object(pf, "STATE_PATH", self.state_path),
            mock.patch.object(pf, "fetch_listing",
                              side_effect=lambda *a, **k: (meteora_rows(), [], False)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _app(self):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        at.run()
        return at

    def _body(self, at):
        return "\n".join(str(node.value) for node in at.markdown)

    def test_halaman_utama_hanya_scan_best_pool(self):
        at = self._app()
        self.assertFalse(at.exception)
        self.assertIn("SCAN BEST POOL", [b.label for b in at.button])
        body = self._body(at)
        self.assertNotIn("Watchlist", body)
        self.assertNotIn("Cek LP Keluar", body)
        self.assertNotIn("Tambah watchlist manual", body)

    def test_scan_menampilkan_pool_lolos_saja(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        body = self._body(at)
        self.assertIn(CHOO, body)
        self.assertIn(DACITY_5DC, body)
        self.assertNotIn("DnmL7vYnNTACb8e6a4EpbeeeNDW8hwp1EvQZ4BWKCgjK", body)  # GATO fee/active 4,5% gagal
        self.assertNotIn(LMAO, body)
        self.assertIn("Timeframe 24H", " ".join(str(c.value) for c in at.caption))

    def test_hasil_scan_berupa_tabel_html_dengan_scroll_horizontal(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        body = self._body(at)
        self.assertIn("overflow-x:auto", body)
        self.assertIn("<table", body)
        self.assertIn("min-width:820px", body)
        for header in ("Volatility", "Fee/active TVL", "Rasio (×)"):
            self.assertIn(header, body)
        for header in ("Open pos.", "In-range"):
            self.assertNotIn(header, body)
        self.assertIn("Geser tabel ke kanan", " ".join(str(c.value) for c in at.caption))

    def test_peringatan_listing_terpotong_muncul_hanya_bila_terpotong(self):
        at = self._app()
        with mock.patch.object(pf, "fetch_listing",
                               side_effect=lambda *a, **k: (meteora_rows(), [], True)):
            next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertTrue(any("Listing belum lengkap" in str(w.value) for w in at.warning))

    def test_tanpa_terpotong_tidak_ada_peringatan(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(any("Listing belum lengkap" in str(w.value) for w in at.warning))

    def test_scan_tidak_menulis_state_dan_tidak_ada_tombol_watchlist(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(self.state_path.exists())
        self.assertFalse([b for b in at.button if str(b.key).startswith("pf_add_")])

    def test_app_utama_tidak_mengimpor_watchlist_atau_lp_keluar(self):
        body = (ROOT / "app.py").read_text(encoding="utf-8").lower()
        for forbidden in ("sweep", "early", "lp_entry", "lp_exit", "best_pool_ui", "watchlist"):
            self.assertNotIn(forbidden, body, forbidden)


class WorkflowAndPagesTest(unittest.TestCase):
    def _load(self, rel):
        return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))

    def test_alert_best_terjadwal_tiap_30_menit_tanpa_mode(self):
        best = self._load(".github/workflows/pool-flow-best.yml")
        self.assertEqual(best[True]["schedule"][0]["cron"], "*/30 * * * *")
        text = (ROOT / ".github/workflows/pool-flow-best.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/pool_flow_alert.py", text)
        self.assertNotIn("--mode", text)

    def test_workflow_watchlist_sudah_dihapus(self):
        self.assertFalse((ROOT / ".github/workflows/pool-flow-watch.yml").exists())
        self.assertFalse((ROOT / "scripts/pool_flow_alert.py").read_text(encoding="utf-8").count("watch") > 0)

    def test_halaman_lp_keluar_dan_modulnya_sudah_dihapus(self):
        self.assertFalse((ROOT / "lp_exit_ui.py").exists())
        self.assertFalse((ROOT / "tools" / "lp_exit_check").exists())
        self.assertFalse(any("Cek_LP_Keluar" in p.name for p in (ROOT / "pages_archived").iterdir()))


class ResultTableTest(unittest.TestCase):
    def test_tabel_memuat_kolom_rasio_per_pool(self):
        import pool_flow_ui as ui
        passing = pf.scan_pools(listing=(meteora_rows(), [], False))["passing"]
        html = ui._result_table_html(passing[:2])
        self.assertIn("Rasio (×)", html)
        self.assertIn(">5,19x</td>", html)
        self.assertIn(">4,78x</td>", html)


if __name__ == "__main__":
    unittest.main()
