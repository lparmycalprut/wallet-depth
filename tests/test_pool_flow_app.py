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
from tests.test_pool_flow import DUT_12H, HIGH_12H, LOW_12H, PASSING_12H  # noqa: E402

LOW_POOL = LOW_12H["pool_address"]  # FOOD (fee 2 % untuk uji)
DUT_POOL = DUT_12H["pool_address"]  # dilewati (volatility 6,71 %)
HIGH_POOL = HIGH_12H["pool_address"]


class AppMainTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "pool_flow_state.json"
        self._patches = [
            mock.patch.object(pf, "STATE_PATH", self.state_path),
            mock.patch.object(pf, "fetch_listing",
                              side_effect=lambda *a, **k: (PASSING_12H, [], False)),
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
        """Markdown + isi iframe (tabel hasil dirender di st.iframe agar tombol copy jalan)."""
        parts = [str(node.value) for node in at.markdown]
        parts += [str(node.proto.srcdoc) for node in at.get("iframe")]
        return "\n".join(parts)

    def test_tombol_copy_ca_tepat_di_samping_hawkfi(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        doc = self._body(at)
        self.assertEqual(doc.count('class="copy-ca"'), len(passing))
        for row in passing:
            self.assertTrue(row["mint"])
            self.assertIn(f'data-ca="{row["mint"]}"', doc)
        self.assertRegex(doc, r'🦅HawkFi</a><button type="button" class="copy-ca" '
                              r'data-ca="[^"]+" onclick="copyCa\(this\)">📋 CA</button>')
        self.assertIn("navigator.clipboard.writeText", doc)
        self.assertIn("execCommand('copy')", doc)
        self.assertNotIn("<script", str(at.markdown))  # skrip hanya di dalam iframe

    def test_halaman_utama_hanya_scan_best_pool(self):
        at = self._app()
        self.assertFalse(at.exception)
        self.assertIn("SCAN BEST POOL", [b.label for b in at.button])
        body = self._body(at)
        self.assertNotIn("Watchlist", body)
        self.assertNotIn("Cek LP Keluar", body)
        self.assertNotIn("Tambah watchlist manual", body)

    def test_scan_menampilkan_semua_pool_dari_listing_satu_tabel(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        body = self._body(at)
        self.assertIn(LOW_POOL, body)
        self.assertIn(HIGH_POOL, body)
        self.assertNotIn(DUT_POOL, body)  # volatility 6,71 % > 6 % dilewati
        self.assertIn("Timeframe 12H", " ".join(str(c.value) for c in at.caption))
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("LOW RISK", markdown)  # tabel LOW RISK sudah dihapus (2026-11-14)
        self.assertEqual(len(at.get("iframe")), 1)  # satu tabel untuk semua pool

    def test_hasil_scan_berupa_tabel_html_dengan_scroll_horizontal(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        body = self._body(at)
        self.assertIn("overflow-x:auto", body)
        self.assertIn("<table", body)
        self.assertIn("min-width:1100px", body)
        for header in ("Volatility", "Avg volume/menit (pool)",
                       "Volume 12H (pool)"):
            self.assertIn(header, body)
        for header in ("Open pos.", "In-range", "Rasio (×)", "4H", "24H"):
            self.assertNotIn(header, body)
        self.assertIn("Geser tabel ke kanan", " ".join(str(c.value) for c in at.caption))

    def test_peringatan_listing_terpotong_muncul_hanya_bila_terpotong(self):
        at = self._app()
        with mock.patch.object(pf, "fetch_listing",
                               side_effect=lambda *a, **k: (PASSING_12H, [], True)):
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

    def test_judul_dan_border_tabel_berbeda_warna(self):
        import pool_flow_ui as ui
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertIn(":red[HIGH RISK FEE PRINTER]", markdown)
        self.assertIn(":blue[FEE PRINTER]", markdown)
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        high = ui._result_table_html(passing, None, ui.HIGH_RISK_BORDER)
        band = ui._result_table_html(passing, None, ui.FEE_PRINTER_BORDER)
        self.assertIn(f"border:2px solid {ui.HIGH_RISK_BORDER}", high)
        self.assertNotIn(ui.FEE_PRINTER_BORDER, high)
        self.assertIn(f"border:2px solid {ui.FEE_PRINTER_BORDER}", band)

    def test_tabel_tanpa_penandaan_api_bakar(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        body = self._body(at)
        self.assertNotIn("🔥", body)
        for node in at.get("iframe"):
            self.assertNotIn("🔥", str(node.proto.srcdoc))
            self.assertNotIn("rgba(249,115,22", str(node.proto.srcdoc))

    def test_app_utama_tidak_mengimpor_watchlist_atau_lp_keluar(self):
        body = (ROOT / "app.py").read_text(encoding="utf-8").lower()
        for forbidden in ("sweep", "early", "lp_entry", "lp_exit", "best_pool_ui", "watchlist"):
            self.assertNotIn(forbidden, body, forbidden)


class WorkflowAndPagesTest(unittest.TestCase):
    def _load(self, rel):
        return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))

    def test_alert_best_terjadwal_tiap_4_jam_tanpa_mode(self):
        best = self._load(".github/workflows/pool-flow-best.yml")
        self.assertEqual(best[True]["schedule"][0]["cron"], "0 */4 * * *")
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
    def test_tabel_memuat_avg_volume_per_menit_per_pool(self):
        import pool_flow_ui as ui
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        html = ui._result_table_html(passing)
        self.assertIn("Avg volume/menit (pool)", html)
        self.assertIn(">$1,50K</td>", html)      # LOW_12H avg_volume
        self.assertIn(">$800,00</td>", html)     # HIGH_12H avg_volume
        self.assertIn("Avg volume/menit ÷ TVL", html)
        self.assertIn(">4,00%</td>", html)       # HIGH_12H: 800 ÷ 20.000
        self.assertIn(">1,66%</td>", html)       # LOW_12H: 1.500,59 ÷ 90.546,54
        self.assertNotIn("Rasio (×)", html)
        self.assertNotIn("rgba(249,115,22", html)  # tanpa highlight baris teratas

    def test_pool_teratas_diberi_warna_kuning_tanpa_emoji(self):
        import pool_flow_ui as ui
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        html = ui._result_table_html(passing, HIGH_POOL)
        rows = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0].split("</tr>")
        high_row = next(r for r in rows if HIGH_POOL in r)
        low_row = next(r for r in rows if LOW_POOL in r)
        self.assertIn(ui.TOP_ROW_BG, high_row)
        self.assertNotIn(ui.TOP_ROW_BG, low_row)
        self.assertNotIn("🔥", html)

    def test_kolom_fee_active_tvl_dihapus(self):
        import pool_flow_ui as ui
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        html = ui._result_table_html(passing, HIGH_POOL)
        self.assertNotIn("Fee/active TVL", html)
        self.assertNotIn("Fee/active TVL", " ".join(ui.TABLE_HEADERS))

    def test_tabel_hanya_memuat_baris_yang_diberikan(self):
        import pool_flow_ui as ui
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        only_low = [r for r in passing if r["pool"] == LOW_POOL]
        html = ui._result_table_html(only_low)
        self.assertIn(LOW_POOL, html)
        self.assertNotIn(HIGH_POOL, html)


if __name__ == "__main__":
    unittest.main()
