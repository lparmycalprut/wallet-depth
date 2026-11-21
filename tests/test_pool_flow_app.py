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


class SlowBalanceColumnsTest(unittest.TestCase):
    """Kolom keseimbangan hanya di tabel SLOW (permintaan user, 2026-11-19)."""

    def _row(self, fee_tvl, vol):
        from tests.test_pool_flow import _fp
        row = _fp("S" * 44, fee_tvl=fee_tvl, vol=vol)
        row["token_x"]["created_at"] = 1_700_000_000_000
        return pf.scan_pools(listing=([row], [], False))["passing"][0]

    def test_rasio_dan_selisih(self):
        row = self._row(fee_tvl=6.0, vol=4.0)
        self.assertAlmostEqual(pf.fee_volatility_ratio(row), 1.5)
        self.assertAlmostEqual(pf.fee_volatility_diff(row), 2.0)
        self.assertEqual(pf.fmt_times(1.5), "1,50×")
        self.assertEqual(pf.fmt_signed_pct(2.0), "+2,00%")
        self.assertEqual(pf.fmt_signed_pct(-1.25), "−1,25%")
        self.assertEqual(pf.fmt_times(None), "—")

    def test_tabel_slow_memuat_kolom_keseimbangan(self):
        import pool_flow_ui as ui
        row = self._row(fee_tvl=6.0, vol=4.0)
        html_slow = ui._slow_table_html([row])
        self.assertIn("Fee/TVL ÷ volatility", html_slow)
        self.assertIn("Selisih fee/TVL − volatility", html_slow)
        self.assertIn("1,50×", html_slow)
        self.assertIn("+2,00%", html_slow)
        # urutan kolom: keseimbangan tepat setelah Fee/TVL, sebelum Avg volume/menit (pool)
        header = html_slow.split("<thead>", 1)[1].split("</thead>", 1)[0]
        titles = [t.split("</th>")[0].split(">")[-1] for t in header.split("<th")[1:]]
        self.assertEqual(titles.index("Fee/TVL ÷ volatility"), titles.index("Fee/TVL") + 1)
        self.assertEqual(titles.index("Avg volume/menit (pool)"), titles.index("Selisih fee/TVL − volatility") + 1)

    def test_tabel_slow_dibuat_lebih_mudah_dibaca(self):
        """Permintaan user (2026-11-23): tabel SLOW dirapikan; semua kolom tetap ada."""
        import pool_flow_ui as ui
        row = self._row(fee_tvl=6.0, vol=4.0)
        slow = ui._slow_table_html([row])
        self.assertIn("position:sticky;left:0", slow)        # kolom Token menempel saat digeser
        self.assertIn("font-variant-numeric:tabular-nums", slow)
        self.assertIn("text-align:right", slow)              # angka rata kanan
        self.assertIn("background:#f8fafc", ui._slow_table_html([row, row]))  # baris belang
        plain = ui._result_table_html([row])
        self.assertNotIn("position:sticky", plain)           # tabel lain tidak berubah
        self.assertNotIn("text-align:right", plain)
        header = slow.split("<thead>", 1)[1].split("</thead>", 1)[0]
        self.assertEqual(header.count("<th"), len(ui.TABLE_HEADERS) + len(ui.BALANCE_HEADERS))

    def test_tabel_lain_tanpa_kolom_keseimbangan(self):
        import pool_flow_ui as ui
        plain = ui._result_table_html([self._row(fee_tvl=6.0, vol=4.0)])
        self.assertNotIn("Fee/TVL ÷ volatility", plain)
        self.assertNotIn("Selisih fee/TVL", plain)


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

    def test_ringkasan_di_bawah_tombol_dan_di_atas_tabel_12h(self):
        from tests.test_pool_flow import _fp
        slow = _fp("S" * 44, fee_tvl=10.0, vol=10.0, symbol="SLW")  # SLOW FEE PRINTER
        listing = PASSING_12H + [slow]  # HIGHX (HIGH RISK) tidak masuk RINGKASAN
        with mock.patch.object(pf, "fetch_listing", side_effect=lambda *a, **k: (listing, [], False)):
            at = self._app()
            next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        summary = next(str(n.proto.srcdoc) for n in at.get("iframe")
                       if "Asal tabel" in str(n.proto.srcdoc))
        self.assertIn(">FEE PRINTER</span>", summary)  # badge asal tabel
        self.assertIn(slow["pool_address"], summary)
        self.assertNotIn(HIGH_POOL, summary)
        # urutan di halaman: RINGKASAN sebelum HIGH RISK FEE PRINTER
        order = [str(m.value) for m in at.markdown]
        idx = {key: next(i for i, v in enumerate(order) if key in v)
               for key in ("RINGKASAN", "HIGH RISK FEE PRINTER")}
        self.assertLess(idx["RINGKASAN"], idx["HIGH RISK FEE PRINTER"])

    def test_tombol_copy_ca_tepat_di_samping_hawkfi(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        fee_printer, band = pf.fee_printer_split(passing)
        # pool yang tampil di tabel 12H (HIGH RISK, VERY HIGH, SLOW); FOOD tidak tampil di mana pun
        shown_12h = pf.fee_printer_high_risk(fee_printer) + pf.very_high_risk(passing) + band
        summary = pf.summary_rows(pf.scan_pools(listing=(PASSING_12H, [], False)))
        doc = self._body(at)
        # tombol CA: tabel 12H + baris RINGKASAN (satu per pool yang tampil di tabel 12H)
        self.assertEqual(doc.count('class="copy-ca"'), len(shown_12h) + len(summary))
        for row in shown_12h:
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
        self.assertIn("SCAN ALL", [b.label for b in at.button])
        body = self._body(at)
        self.assertNotIn("Watchlist", body)
        self.assertNotIn("Cek LP Keluar", body)
        self.assertNotIn("Tambah watchlist manual", body)

    def test_scan_menampilkan_semua_pool_dari_listing_satu_tabel(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        body = self._body(at)
        # FOOD fee/TVL 9,5 % < 10 % → tidak masuk HIGH RISK (dan tidak di SLOW)
        self.assertNotIn(LOW_POOL, body)
        self.assertIn(HIGH_POOL, body)
        self.assertNotIn(DUT_POOL, body)  # volatility 6,71 % > 6 % dilewati
        self.assertIn("Timeframe 12H", " ".join(str(c.value) for c in at.caption))
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("LOW RISK", markdown)  # tabel LOW RISK sudah dihapus (2026-11-14)
        twelve = [n for n in at.get("iframe") if "Volume 12H (pool)" in str(n.proto.srcdoc)]
        self.assertTrue(twelve)  # tabel 12H (HIGH RISK dan SLOW FEE PRINTER)

    def test_hasil_scan_berupa_tabel_html_dengan_scroll_horizontal(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        body = self._body(at)
        self.assertIn("overflow-x:auto", body)
        self.assertIn("<table", body)
        self.assertIn("min-width:1100px", body)
        for header in ("Volatility", "Avg volume/menit (pool)",
                       "Volume 12H (pool)"):
            self.assertIn(header, body)
        for header in ("Open pos.", "In-range", "Rasio (×)", "24H"):
            self.assertNotIn(header, body)
        self.assertNotIn(">4H</th>", body)  # kolom lama 4H; judul bagian Deteksi 4H tidak dihitung
        self.assertIn("Geser tabel ke kanan", " ".join(str(c.value) for c in at.caption))

    def test_peringatan_listing_terpotong_muncul_hanya_bila_terpotong(self):
        at = self._app()
        with mock.patch.object(pf, "fetch_listing",
                               side_effect=lambda *a, **k: (PASSING_12H, [], True)):
            next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertTrue(any("Listing belum lengkap" in str(w.value) for w in at.warning))

    def test_tanpa_terpotong_tidak_ada_peringatan(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(any("Listing belum lengkap" in str(w.value) for w in at.warning))

    def test_scan_tidak_menulis_state_dan_tidak_ada_tombol_watchlist(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(self.state_path.exists())
        self.assertFalse([b for b in at.button if str(b.key).startswith("pf_add_")])

    def test_judul_dan_border_tabel_berbeda_warna(self):
        import pool_flow_ui as ui
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertIn(":red[HIGH RISK FEE PRINTER]", markdown)
        self.assertIn('<span class="fee-printer-title">FEE PRINTER</span>', markdown)  # judul hijau tua
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        high = ui._result_table_html(passing, None, ui.HIGH_RISK_BORDER)
        band = ui._result_table_html(passing, None, ui.SLOW_FEE_PRINTER_BORDER)
        self.assertIn(f"border:2px solid {ui.HIGH_RISK_BORDER}", high)
        self.assertNotIn(ui.SLOW_FEE_PRINTER_BORDER, high)
        self.assertIn(f"border:2px solid {ui.SLOW_FEE_PRINTER_BORDER}", band)

    def test_high_risk_dan_very_high_tabel_di_dropdown_tertutup(self):
        """Permintaan user (2026-11-23): tabel dan detail HIGH RISK dan VERY HIGH ada di dropdown."""
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        labels = [e.label for e in at.expander]
        self.assertEqual(labels.count("Tabel dan detail · 1 pool"), 1)  # HIGH RISK (HIGH_12H)
        self.assertEqual(labels.count("Tabel dan detail · 0 pool"), 1)  # VERY HIGH (tidak ada di PASSING_12H)
        for exp in at.expander:
            self.assertFalse(exp.proto.expanded)  # tertutup sejak awal
        high_exp = next(e for e in at.expander if e.label == "Tabel dan detail · 1 pool")
        self.assertIn("Volume 12H (pool)", " ".join(str(f.proto.srcdoc) for f in high_exp.get("iframe")))

    def test_tanpa_panel_log_aktivitas(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("Log Aktivitas", markdown)  # panel dihapus dari halaman utama (2026-11-18)

    def test_tabel_very_high_risk_antara_high_risk_dan_slow_fee_printer(self):
        from tests.test_pool_flow import _fp
        very = _fp("V" * 44, fee_tvl=50.0, vol=1.0, symbol="VHX")  # 50 × volatility → VERY HIGH
        very["avg_volume"] = 900.0
        listing_12h = PASSING_12H + [very]

        with mock.patch.object(pf, "fetch_listing", side_effect=lambda *_a, **_k: (listing_12h, [], False)):
            at = self._app()
            next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        order = [str(m.value) for m in at.markdown]

        def index_of(key):
            return next(i for i, v in enumerate(order) if key in v)

        high = index_of("HIGH RISK FEE PRINTER")
        very_at = index_of("VERY HIGH RISK POOL / BISA DUMP SEWAKTU2 (Bid-Ask Limit 94.1)")
        slow = index_of('class="fee-printer-title">FEE PRINTER')  # judul tabel, bukan blok CSS
        self.assertLess(high, very_at)
        self.assertLess(very_at, slow)
        table_html = "\n".join(str(n.proto.srcdoc) for n in at.get("iframe"))
        self.assertIn("VHX", table_html)

    def test_tanpa_bagian_deteksi_4h(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
        self.assertFalse(at.exception)
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("DETEKSI 4H", markdown)  # bagian Deteksi 4H dihapus (2026-11-20)
        self.assertNotIn("Volume 4H (pool)", self._body(at))

    def test_tabel_tanpa_penandaan_api_bakar(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN ALL").click().run()
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

    def test_alert_ringkasan_terjadwal_tiap_15_menit_tanpa_mode(self):
        best = self._load(".github/workflows/pool-flow-best.yml")
        self.assertEqual(best[True]["schedule"][0]["cron"], "7,22,37,52 * * * *")  # tiap 15 menit
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
        self.assertIn("Avg fee/menit ÷ TVL", html)
        self.assertIn("Avg volume/menit ÷ TVL", html)
        self.assertIn(">1,66%</td>", html)       # LOW_12H: 1.500,59 ÷ 90.546,54
        self.assertNotIn("Rasio (×)", html)
        self.assertNotIn("rgba(249,115,22", html)  # tanpa highlight baris teratas

    def test_kolom_avg_fee_per_menit_per_tvl_12h(self):
        import pool_flow_ui as ui
        row = pf.evaluate_pool(dict(HIGH_12H, avg_fee=8.0))  # 8 ÷ 20.000 = 0,040 %
        html = ui._result_table_html([row])
        self.assertIn(">0,040%</td>", html)

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

