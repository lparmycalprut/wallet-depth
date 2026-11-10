# -*- coding: utf-8 -*-
"""Tes offline tool 🚪 Cek LP Keluar (tanpa jaringan)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lp_exit_check"))

import lp_exit_check as lxc  # noqa: E402

CA = "9VZerdNL1x6EjetDqRnh5bYcdmk1y8sLAGs1ybzGpump"
OTHER = "DKYcjobF7HPtL9RyQBRdeRQ2iWvizpfbgWwPWNXdpump"
SOL = "So11111111111111111111111111111111111111112"
POOL = "38hkfLZhhtjhn9t49LhCkconQ297ad5fnoZ3Mj7w5wEk"
POOL2 = "CPWA5ufjXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"


def _pool(address=POOL, *, ca=CA, tvl=34055.46, deposits=120202.34,
          withdraws=154788.07, net=None):
    row = {
        "pool_address": address,
        "name": "X-SOL",
        "token_x": {"address": ca, "symbol": "X"},
        "token_y": {"address": SOL, "symbol": "SOL"},
        "tvl": tvl,
        "total_deposits": deposits,
        "total_withdraws": withdraws,
    }
    if net is not None:
        row["net_deposits"] = net
    return row


def _all(rows):
    return {w: rows for w in lxc.WINDOWS}


class ValidCaTest(unittest.TestCase):
    def test_ca_valid_dan_rapi(self):
        self.assertEqual(lxc.valid_ca(f"  {CA}\n"), CA)

    def test_input_salah_ditolak(self):
        for bad in ("abc", "", "0" * 40, "I" * 40):
            with self.assertRaises(ValueError):
                lxc.valid_ca(bad)


class MetricsTest(unittest.TestCase):
    def test_net_dari_api_dipakai(self):
        m = lxc._metrics(_pool(net=-34585.72))
        self.assertAlmostEqual(m["net"], -34585.72)

    def test_net_dihitung_bila_api_tidak_memberi(self):
        m = lxc._metrics(_pool())
        self.assertAlmostEqual(m["net"], 120202.34 - 154788.07, places=2)

    def test_pool_tanpa_field_withdraw_tidak_terukur(self):
        row = _pool()
        del row["total_withdraws"]
        self.assertIsNone(lxc._metrics(row))


class AnalyzeTest(unittest.TestCase):
    def test_lp_keluar_1h_dan_4h_verdict_terbaru(self):
        report = lxc.analyze(CA, _all([_pool(net=-34585.72)]))
        self.assertEqual(report["verdict"], lxc.VERDICT_RECENT)
        self.assertEqual(report["exit_windows"], ["1h", "4h", "12h", "24h"])
        self.assertEqual(report["pool_address"], POOL)

    def test_net_negatif_hanya_12h_24h_verdict_sebelumnya(self):
        rows = {
            "1h": [_pool(deposits=100, withdraws=50, net=50)],
            "4h": [_pool(deposits=100, withdraws=50, net=50)],
            "12h": [_pool(deposits=100, withdraws=150, net=-50)],
            "24h": [_pool(deposits=100, withdraws=150, net=-50)],
        }
        report = lxc.analyze(CA, rows)
        self.assertEqual(report["verdict"], lxc.VERDICT_EARLIER)
        self.assertEqual(report["exit_windows"], ["12h", "24h"])

    def test_net_positif_semua_window_tidak_ada_sinyal(self):
        report = lxc.analyze(CA, _all([_pool(deposits=200, withdraws=100, net=100)]))
        self.assertEqual(report["verdict"], lxc.VERDICT_NONE)
        self.assertEqual(report["exit_windows"], [])

    def test_net_nol_bukan_sinyal(self):
        report = lxc.analyze(CA, _all([_pool(deposits=100, withdraws=100, net=0)]))
        self.assertEqual(report["verdict"], lxc.VERDICT_NONE)

    def test_window_hilang_tanpa_sinyal_jadi_data_kurang(self):
        rows = {"1h": [_pool(deposits=200, withdraws=100, net=100)],
                "4h": [_pool(deposits=200, withdraws=100, net=100)],
                "12h": [_pool(deposits=200, withdraws=100, net=100)],
                "24h": []}
        report = lxc.analyze(CA, rows)
        self.assertEqual(report["verdict"], lxc.VERDICT_DATA)
        self.assertIsNone(report["windows"]["24h"])
        self.assertTrue(any("24H" in w for w in report["warnings"]))

    def test_window_hilang_tapi_ada_sinyal_tetap_keluar(self):
        rows = {"1h": [_pool(net=-10.0)], "4h": [], "12h": [], "24h": []}
        report = lxc.analyze(CA, rows)
        self.assertEqual(report["verdict"], lxc.VERDICT_RECENT)

    def test_tidak_ada_pool(self):
        report = lxc.analyze(CA, _all([_pool(ca=OTHER)]))
        self.assertEqual(report["verdict"], lxc.VERDICT_NO_POOL)
        self.assertIsNone(report["pool_address"])

    def test_banyak_pool_yang_dinilai_tvl_terbesar(self):
        rows = {w: [_pool(POOL2, tvl=500.0, deposits=200, withdraws=100, net=100),
                    _pool(POOL, tvl=34055.0, net=-34585.72)] for w in lxc.WINDOWS}
        report = lxc.analyze(CA, rows)
        self.assertEqual(report["pool_address"], POOL)
        self.assertEqual(report["verdict"], lxc.VERDICT_RECENT)
        self.assertTrue(any("2 pool" in w for w in report["warnings"]))

    def test_error_fetch_dicatat_sebagai_peringatan(self):
        rows = {"1h": [_pool(net=-10.0)], "4h": [], "12h": [], "24h": []}
        report = lxc.analyze(CA, rows, errors={"4h": "timeout"})
        self.assertTrue(any("4H gagal" in w and "timeout" in w for w in report["warnings"]))


class FormatTest(unittest.TestCase):
    def test_laporan_memuat_verdict_dan_tabel(self):
        report = lxc.analyze(CA, _all([_pool(net=-34585.72)]))
        text = lxc.format_report(report)
        self.assertIn("VERDICT: " + lxc.VERDICT_RECENT, text)
        self.assertIn("1H", text)
        self.assertIn("KELUAR", text)
        self.assertIn("-$34.586", text)

    def test_laporan_tanpa_pool(self):
        text = lxc.format_report(lxc.analyze(CA, _all([_pool(ca=OTHER)])))
        self.assertIn(lxc.VERDICT_NO_POOL, text)


class RunTest(unittest.TestCase):
    def test_semua_window_gagal_raise(self):
        original = lxc.fetch_window

        def boom(ca, timeframe, *, timeout=0):
            raise OSError("jaringan mati")

        lxc.fetch_window = boom
        try:
            with self.assertRaises(RuntimeError):
                lxc.run(CA)
        finally:
            lxc.fetch_window = original

    def test_sebagian_gagal_tetap_analisis(self):
        original = lxc.fetch_window

        def partial(ca, timeframe, *, timeout=0):
            if timeframe == "24h":
                raise OSError("timeout")
            return [_pool(net=-10.0)]

        lxc.fetch_window = partial
        try:
            report = lxc.run(CA)
        finally:
            lxc.fetch_window = original
        self.assertEqual(report["verdict"], lxc.VERDICT_RECENT)
        self.assertTrue(any("24H gagal" in w for w in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
