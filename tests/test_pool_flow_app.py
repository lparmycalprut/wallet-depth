# -*- coding: utf-8 -*-
"""Tes main app 🏆 Scan Best Pool (AppTest) dan struktur halaman/workflow. Offline."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pool_flow as pf  # noqa: E402

POOL = "38hkfLZhhtjhn9t49LhCkconQ297ad5fnoZ3Mj7w5wEk"
MINT = "9VZerdNL1x6EjetDqRnh5bYcdmk1y8sLAGs1ybzGpump"
SOL = "So11111111111111111111111111111111111111112"
POOL2 = "CPWA5ufjXEyC7DTd7g5fVUxJYZ81kxvbC8f9R9XFx1Y8"


def _row(pool=POOL, net=800.0):
    return {"pool_address": pool, "name": "X-SOL",
            "token_x": {"address": MINT, "symbol": "X", "name": "apeonx"},
            "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
            "fee_pct": 2.0, "tvl": 60_000.0, "fee": 6.0 * 1440, "net_deposits": net}


def _fake_scan():
    passing = pf.evaluate_pool(_row(), {w: _row(net=800.0) for w in pf.FLOW_WINDOWS})
    return {"scanned_at": "2026-11-10T00:00:00Z", "listing_rows": 1, "listing_errors": 0,
            "candidates": 1, "results": [passing], "passing": [passing]}


class AppMainTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "pool_flow_state.json"
        self._patches = [
            mock.patch.object(pf, "STATE_PATH", self.state_path),
            mock.patch.object(pf, "scan_candidates", side_effect=lambda *a, **k: _fake_scan()),
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

    def test_halaman_utama_tampil_dengan_tombol_scan_best_pool(self):
        at = self._app()
        self.assertFalse(at.exception)
        labels = [b.label for b in at.button]
        self.assertIn("SCAN BEST POOL", labels)
        self.assertNotIn("🏆 Scan Best Pool 24H", labels)

    def test_scan_menampilkan_pool_dan_bisa_masuk_watchlist(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        add = [b for b in at.button if b.key == f"pf_add_{POOL}"]
        self.assertEqual(len(add), 1)
        add[0].click().run()
        self.assertFalse(at.exception)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual([i["pool"] for i in saved["watchlist"]], [POOL])
        self.assertEqual(saved["watchlist"][0]["symbol"], "X")

    def test_hasil_scan_menampilkan_ca_dan_link_di_bawahnya(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        self.assertFalse(at.exception)
        body = "\n".join(str(node.value) for node in at.markdown)
        self.assertIn(MINT, body)  # CA lengkap
        self.assertIn("https://gmgn.ai/sol/token/" + MINT, body)
        self.assertIn("https://dexscreener.com/solana/" + MINT, body)
        self.assertIn("https://app.meteora.ag/dlmm/" + POOL, body)
        self.assertIn("https://www.hawkfi.ag/meteora/" + POOL, body)
        # CA harus muncul sebelum link (link berada di bawah CA)
        self.assertLess(body.index(MINT), body.index("https://gmgn.ai/sol/token/" + MINT))

    def test_watchlist_menampilkan_ca_dan_link(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        next(b for b in at.button if b.key == f"pf_add_{POOL}").click().run()
        body = "\n".join(str(node.value) for node in at.markdown)
        self.assertGreaterEqual(body.count(MINT), 2)  # hasil scan + watchlist
        self.assertIn("https://gmgn.ai/sol/token/" + MINT, body)
        self.assertIn("https://www.hawkfi.ag/meteora/" + POOL, body)

    def test_scan_menyimpan_riwayat_net_per_pool(self):
        at = self._app()
        next(b for b in at.button if b.label == "SCAN BEST POOL").click().run()
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["history"][POOL]), 1)
        self.assertEqual(saved["history"][POOL][0]["net_24h"], 800.0)


class ManualAndLpExitOnMainTest(unittest.TestCase):
    # Pakai ulang fixture AppMainTest tanpa mewarisi tes-tesnya.
    setUp = AppMainTest.setUp
    tearDown = AppMainTest.tearDown
    _app = AppMainTest._app

    def test_kartu_cek_lp_keluar_manual_ada_di_main(self):
        at = self._app()
        self.assertFalse(at.exception)
        body = "\n".join(str(node.value) for node in at.markdown)
        self.assertIn("Cek LP Keluar (manual)", body)
        self.assertIn("🚪 Cek sekarang", [b.label for b in at.button])

    def test_tambah_watchlist_manual_dari_ca(self):
        def _pool(pool, tvl):
            return {"pool_address": pool, "name": "X-SOL", "fee_pct": 2.0, "tvl": tvl,
                    "fee": 6.0 * 1440, "net_deposits": 1.0,
                    "token_x": {"address": MINT, "symbol": "X", "name": "apeonx"},
                    "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"}}

        rows = [_pool(POOL, 60_000.0), _pool(POOL2, 90_000.0)]
        at = self._app()
        with mock.patch.object(pf, "fetch_mint_window", return_value=rows):
            at.text_input(key="pf_manual_ca").set_value(MINT).run()
            next(b for b in at.button if b.label == "🔍 Cari pool").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.selectbox(key="pf_manual_pick").options), 2)
            next(b for b in at.button if b.label == "➕ Tambahkan ke watchlist").click().run()
        self.assertFalse(at.exception)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        # default pilihan = TVL terbesar (POOL2)
        self.assertEqual([i["pool"] for i in saved["watchlist"]], [POOL2])
        self.assertEqual(saved["watchlist"][0]["mint"], MINT)

    def test_ca_tidak_valid_ditolak_tanpa_panggilan_jaringan(self):
        at = self._app()
        with mock.patch.object(pf, "fetch_mint_window") as fetch:
            at.text_input(key="pf_manual_ca").set_value("bukan-ca").run()
            next(b for b in at.button if b.label == "🔍 Cari pool").click().run()
        fetch.assert_not_called()
        self.assertTrue(any("valid" in str(e.value) for e in at.error))


class PagesAndWorkflowsTest(unittest.TestCase):
    HIDDEN = ["8_🌊_Sweep.py", "9_🔍_Cek_CA_Sweep.py", "10_⚡_Early_Watcher.py",
              "11_🧭_Cek_Entri_LP.py", "12_🚪_Cek_LP_Keluar.py"]

    def test_lima_halaman_pindah_ke_arsip_bukan_dihapus(self):
        self.assertFalse((ROOT / "pages").exists() and any((ROOT / "pages").glob("*.py")))
        for name in self.HIDDEN:
            self.assertTrue((ROOT / "pages_archived" / name).exists(), name)

    def _load(self, rel):
        return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))

    def test_alert_sweep_dan_early_watcher_sudah_dihapus(self):
        # Keputusan user (2026-11-11): alert lama dihapus, termasuk workflow
        # terjadwal dan state alert-nya. Halaman tetap ada di pages_archived/.
        for rel in (".github/workflows/sweep-scan.yml",
                    ".github/workflows/early-watch.yml",
                    "sweep_state.json", "early_watch_state.json"):
            self.assertFalse((ROOT / rel).exists(), rel)

    def test_workflow_pool_flow_terjadwal_30_dan_10_menit(self):
        best = self._load(".github/workflows/pool-flow-best.yml")
        watch = self._load(".github/workflows/pool-flow-watch.yml")
        self.assertEqual(best[True]["schedule"][0]["cron"], "*/30 * * * *")
        self.assertEqual(watch[True]["schedule"][0]["cron"], "*/10 * * * *")
        self.assertIn("--mode best", (ROOT / ".github/workflows/pool-flow-best.yml").read_text(encoding="utf-8"))
        self.assertIn("--mode watch", (ROOT / ".github/workflows/pool-flow-watch.yml").read_text(encoding="utf-8"))

    def test_app_utama_tidak_mengimpor_modul_sweep_atau_early(self):
        body = (ROOT / "app.py").read_text(encoding="utf-8")
        # lp_exit_ui sengaja diimpor (permintaan user 2026-11-11: cek LP keluar
        # manual di main page). Modul lain tetap dilarang.
        for forbidden in ("sweep", "early", "lp_entry", "best_pool_ui"):
            self.assertNotIn(forbidden, body.lower(), forbidden)


if __name__ == "__main__":
    unittest.main()
