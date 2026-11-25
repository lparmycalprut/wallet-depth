# -*- coding: utf-8 -*-
"""Tes main app 🏆 Scan ALL (AppTest) dan tabel FEE PRINTER (24H) serta struktur workflow. Offline."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pool_flow as pf  # noqa: E402
from tests.test_pool_flow import _fp  # noqa: E402

FEE_A = _fp("A" * 44, fa=8.0, vol=2.0, net=25_000.0, symbol="ALPHA", mint="A" * 44)  # rasio 4
FEE_B = _fp("B" * 44, fa=6.0, vol=3.0, net=10_000.0, symbol="BETA", mint="B" * 44)   # rasio 2
OUT_OF_RULE = _fp("O" * 44, fa=30.0, vol=6.0, net=50_000.0, symbol="OUTX", mint="O" * 44)  # vol > 3
LISTING = [FEE_A, FEE_B, OUT_OF_RULE]


def _scan_result(rows=LISTING):
    return pf.scan_pools(listing=(rows, [], False))


class FeePrinterTableTest(unittest.TestCase):
    def test_tabel_memuat_kolom_fee_printer_baru(self):
        import pool_flow_ui as ui
        html = ui._fee_printer_table_html(pf.fee_printer_rows(_scan_result()["passing"]))
        header = html.split("<thead>", 1)[1].split("</thead>", 1)[0]
        for title in ("Fee/volume", "Volatility", "Fee/active TVL", "Net deposit",
                      "Fee/active TVL ÷ volatility", "Volume 24H (pool)"):
            self.assertIn(title, header)
        for title in ("Volume 12H", "Fee/TVL ÷ volatility", "Selisih fee/TVL", "Volatility 4H",
                      "Fee/TVL 4H", "Keseimbangan"):
            self.assertNotIn(title, header)

    def test_nilai_tampil_dengan_format_koma_dan_ringkas(self):
        import pool_flow_ui as ui
        html = ui._fee_printer_table_html(pf.fee_printer_rows(_scan_result()["passing"]))
        self.assertIn(">2,00%</td>", html)        # volatility ALPHA
        self.assertIn(">8,00%</td>", html)        # fee/active TVL ALPHA
        self.assertIn(">$25K</td>", html)         # net deposit ALPHA
        self.assertIn(">4,00</td>", html)         # rasio ALPHA
        self.assertIn(">2,00</td>", html)         # rasio BETA

    def test_urut_rasio_terbesar_dulu_di_tabel(self):
        import pool_flow_ui as ui
        html = ui._fee_printer_table_html(pf.fee_printer_rows(_scan_result()["passing"]))
        self.assertLess(html.index("ALPHA"), html.index("BETA"))  # 4 sebelum 2

    def test_pool_teratas_diberi_warna_kuning_tanpa_emoji(self):
        import pool_flow_ui as ui
        rows = pf.fee_printer_rows(_scan_result()["passing"])
        html = ui._fee_printer_table_html(rows, FEE_A["pool_address"])
        body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0].split("</tr>")
        alpha = next(r for r in body if FEE_A["pool_address"] in r)
        beta = next(r for r in body if FEE_B["pool_address"] in r)
        self.assertIn(ui.TOP_ROW_SOLID, alpha)
        self.assertNotIn(ui.TOP_ROW_SOLID, beta)
        self.assertNotIn("🔥", html)

    def test_tabel_hanya_memuat_baris_yang_diberikan(self):
        import pool_flow_ui as ui
        rows = [r for r in pf.fee_printer_rows(_scan_result()["passing"]) if r["symbol"] == "ALPHA"]
        html = ui._fee_printer_table_html(rows)
        self.assertIn("ALPHA", html)
        self.assertNotIn("BETA", html)

    def test_pool_di_luar_aturan_tidak_ada_di_tabel(self):
        import pool_flow_ui as ui
        html = ui._fee_printer_table_html(pf.fee_printer_rows(_scan_result()["passing"]))
        self.assertNotIn("OUTX", html)


class AppMainTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "pool_flow_state.json"
        self._patches = [
            mock.patch.object(pf, "STATE_PATH", self.state_path),
            mock.patch.object(pf, "fetch_listing",
                              side_effect=lambda *a, **k: (LISTING, [], False)),
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

    def _scan(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        return at

    def _body(self, at):
        parts = [str(node.value) for node in at.markdown]
        parts += [str(node.proto.srcdoc) for node in at.get("iframe")]
        return "\n".join(parts)

    def test_halaman_utama_hanya_scan_all(self):
        at = self._app()
        self.assertFalse(at.exception)
        self.assertIn("SCAN ALL", [b.label for b in at.button])
        body = self._body(at)
        self.assertNotIn("Watchlist", body)
        self.assertNotIn("Cek LP Keluar", body)

    def test_ringkasan_di_atas_tabel_dan_hanya_fee_printer(self):
        at = self._scan()
        summary = next(str(n.proto.srcdoc) for n in at.get("iframe")
                       if "Asal tabel" in str(n.proto.srcdoc))
        self.assertIn(">FEE PRINTER</span>", summary)
        self.assertIn(FEE_A["pool_address"], summary)
        self.assertIn(FEE_B["pool_address"], summary)
        self.assertNotIn(OUT_OF_RULE["pool_address"], summary)
        order = [str(m.value) for m in at.markdown]
        title = 'class="fee-printer-title">FEE PRINTER'
        idx = {key: next(i for i, v in enumerate(order) if key in v) for key in ("RINGKASAN", title)}
        self.assertLess(idx["RINGKASAN"], idx[title])

    def test_caption_dan_aturan_24h(self):
        at = self._scan()
        captions = " ".join(str(c.value) for c in at.caption)
        self.assertIn("Timeframe 24H", captions)
        self.assertNotIn("12H", captions)
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertIn("volatility 0,01–3 %", markdown)
        self.assertIn("fee/active TVL ≥ 2 × volatility", markdown)
        self.assertIn("net deposit ≥ $10.000", markdown)

    def test_tombol_copy_ca_tepat_di_samping_hawkfi(self):
        at = self._scan()
        rows = pf.fee_printer_rows(_scan_result()["passing"])
        doc = self._body(at)
        # satu tombol CA per baris tabel + satu per baris RINGKASAN
        self.assertEqual(doc.count('class="copy-ca"'), 2 * len(rows))
        for row in rows:
            self.assertIn(f'data-ca="{row["mint"]}"', doc)
        self.assertRegex(doc, r'🦅HawkFi</a><button type="button" class="copy-ca" '
                              r'data-ca="[^"]+" onclick="copyCa\(this\)">📋 CA</button>')
        self.assertIn("navigator.clipboard.writeText", doc)
        self.assertNotIn("<script", str(at.markdown))

    def test_hasil_scan_berupa_tabel_html_dengan_scroll_horizontal(self):
        at = self._scan()
        body = self._body(at)
        self.assertIn("overflow-x:auto", body)
        self.assertIn("<table", body)
        self.assertIn("min-width:1100px", body)
        self.assertIn("Volume 24H (pool)", body)
        self.assertIn("Geser tabel ke kanan", " ".join(str(c.value) for c in at.caption))

    def test_peringatan_listing_terpotong_muncul_hanya_bila_terpotong(self):
        at = self._app()
        with mock.patch.object(pf, "fetch_listing", side_effect=lambda *a, **k: (LISTING, [], True)):
            next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertTrue(any("Listing belum lengkap" in str(w.value) for w in at.warning))

    def test_tanpa_terpotong_tidak_ada_peringatan(self):
        at = self._scan()
        self.assertFalse(any("Listing belum lengkap" in str(w.value) for w in at.warning))

    def test_scan_tidak_menulis_state(self):
        self._scan()
        self.assertFalse(self.state_path.exists())

    def test_judul_hijau_dan_tanpa_tabel_lama(self):
        at = self._scan()
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertIn('<span class="fee-printer-title">FEE PRINTER</span>', markdown)
        for gone in ("HIGH RISK", "VERY HIGH", "SPOT", "SLOW FEE PRINTER", "DETEKSI 4H",
                     "Log Aktivitas", "BEST POOL"):
            self.assertNotIn(gone, markdown + self._body(at), gone)

    def test_app_utama_tidak_mengimpor_watchlist_atau_lp_keluar(self):
        body = (ROOT / "app.py").read_text(encoding="utf-8").lower()
        for forbidden in ("sweep", "early", "lp_entry", "lp_exit", "best_pool_ui", "watchlist"):
            self.assertNotIn(forbidden, body, forbidden)


class WorkflowAndPagesTest(unittest.TestCase):
    def _load(self, rel):
        return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))

    def test_alert_ringkasan_terjadwal_tiap_15_menit_tanpa_mode(self):
        best = self._load(".github/workflows/pool-flow-best.yml")
        self.assertEqual(best[True]["schedule"][0]["cron"], "7,22,37,52 * * * *")  # tiap 15 menit
        text = (ROOT / ".github/workflows/pool-flow-best.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/pool_flow_alert.py", text)
        self.assertNotIn("--mode", text)
        self.assertIn("workflow_dispatch:", text)  # pemicu eksternal (cron luar) lewat API

    def test_workflow_watchlist_sudah_dihapus(self):
        self.assertFalse((ROOT / ".github/workflows/pool-flow-watch.yml").exists())

    def test_halaman_lp_keluar_dan_modulnya_sudah_dihapus(self):
        self.assertFalse((ROOT / "lp_exit_ui.py").exists())
        self.assertFalse((ROOT / "tools" / "lp_exit_check").exists())
        self.assertFalse(any("Cek_LP_Keluar" in p.name for p in (ROOT / "pages_archived").iterdir()))


if __name__ == "__main__":
    unittest.main()
