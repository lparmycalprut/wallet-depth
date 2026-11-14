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
            # Semua pool per token: offline, dari fixture yang sama dengan listing.
            mock.patch.object(pf, "fetch_token_pools", side_effect=self._token_pools),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    @staticmethod
    def _token_pools(mint, *a, **k):
        return ([r for r in PASSING_12H if pf.mint_of_pool(r) == mint], [], False)

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

    def test_scan_menampilkan_semua_pool_dari_listing_dua_tabel_risiko(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        body = self._body(at)
        self.assertIn(LOW_POOL, body)
        self.assertIn(HIGH_POOL, body)
        self.assertNotIn(DUT_POOL, body)  # volatility 6,71 % > 6 % dilewati
        self.assertIn("Timeframe 12H", " ".join(str(c.value) for c in at.caption))
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertIn("HIGH RISK", markdown)
        self.assertIn("LOW RISK", markdown)
        self.assertEqual(len(at.get("iframe")), 2)  # satu tabel per kelompok risiko

    def test_hasil_scan_berupa_tabel_html_dengan_scroll_horizontal(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        body = self._body(at)
        self.assertIn("overflow-x:auto", body)
        self.assertIn("<table", body)
        self.assertIn("min-width:1100px", body)
        for header in ("Volatility", "Fee/active TVL", "Avg volume/menit (pool)",
                       "Volume 12H (pool)", "Volume 12H (token)", "Rata² swap (token)"):
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

    def test_headline_paling_ramai_dan_dropdown_per_token(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        headline = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("Paling ramai", headline)  # headline perhitungan sudah dihapus (2026-11-13)
        self.assertNotIn("avg volume/menit", headline)
        mints = {row["mint"] for row in pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]}
        self.assertEqual(len(at.expander), len(mints))
        self.assertTrue(all("pool" in e.label for e in at.expander))

    def test_dropdown_memuat_pool_dan_tautan_tanpa_perubahan(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        detail = "\n".join(str(node.proto.body) for node in at.get("html"))
        self.assertIn("Total 12H", detail)
        self.assertIn("Trader unik", detail)
        self.assertIn(f"https://app.meteora.ag/dlmm/{LOW_POOL}", detail)
        self.assertIn(f"https://www.hawkfi.ag/meteora/{LOW_POOL}", detail)
        self.assertIn("✅ lolos", detail)
        self.assertNotIn("onclick", detail)  # dropdown tanpa skrip

    def test_baris_teratas_paling_ramai_diberi_emoji_bakar(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        body = self._body(at)
        hot_table = next(str(node.proto.srcdoc) for node in at.get("iframe")
                         if "🔥🔥🔥" in str(node.proto.srcdoc))
        first_row = hot_table.split("<tbody>", 1)[1].split("</tr>", 1)[0]
        self.assertIn("🔥🔥🔥", first_row)
        self.assertIn(LOW_POOL, first_row)  # avg volume/menit terbesar = FOOD (LOW RISK)
        self.assertEqual(body.count("🔥🔥🔥"), 1)  # hanya baris teratas tabel (headline sudah dihapus)
        dropdown = "\n".join(str(node.proto.body) for node in at.get("html"))
        self.assertEqual(dropdown.count("🔥🔥🔥"), 1)
        self.assertIn("background:rgba(249,115,22,.14)", first_row)

    def test_gagal_ambil_pool_token_memberi_peringatan_di_dropdown(self):
        with mock.patch.object(pf, "fetch_token_pools", side_effect=RuntimeError("timeout")):
            at = self._app()
            next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        detail = "\n".join(str(node.proto.body) for node in at.get("html"))
        self.assertIn("Gagal mengambil semua pool token ini", detail)

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
        html = ui._result_table_html(passing, None, LOW_POOL)
        self.assertIn("Avg volume/menit (pool)", html)
        self.assertIn(">$1.500,59</td>", html)   # LOW_12H avg_volume
        self.assertIn(">$800,00</td>", html)     # HIGH_12H avg_volume
        self.assertNotIn("Rasio (×)", html)
        first_row = html.split("<tbody>", 1)[1].split("</tr>", 1)[0]
        self.assertIn("background:rgba(249,115,22,.14)", first_row)

    def test_tabel_hanya_memuat_baris_yang_diberikan(self):
        import pool_flow_ui as ui
        passing = pf.scan_pools(listing=(PASSING_12H, [], False))["passing"]
        high, low = pf.split_by_risk(passing)
        html = ui._result_table_html(high)
        self.assertIn(HIGH_POOL, html)
        self.assertNotIn(LOW_POOL, html)


if __name__ == "__main__":
    unittest.main()
