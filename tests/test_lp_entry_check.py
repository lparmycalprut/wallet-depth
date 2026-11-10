# -*- coding: utf-8 -*-
"""Tes offline untuk tools/lp_entry_check (tanpa jaringan).

Fixture pool 38hkf memakai angka asli dari API Meteora yang sudah diambil
(perubahan harga 1H −46,71%, 4H +233,07%, fee/TVL 1H 4,13%, 4H 20,57%).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL_DIR = ROOT / "tools" / "lp_entry_check"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import lp_entry_check as lec  # noqa: E402

CA = "9VZerdNL1x6EjetDqRnh5bYcdmk1y8sLAGs1ybzGpump"
NOW = 1_800_000_000_000.0
HOUR = 3_600_000.0


def _pool(addr, *, change, fee, tvl=50_000.0, active=None, created=None,
          vol=0.0, name="X-SOL", ca=CA):
    return {
        "pool_address": addr,
        "name": name,
        "token_x": {"address": ca, "symbol": "X"},
        "token_y": {"address": "So11111111111111111111111111111111111111112",
                    "symbol": "SOL"},
        "pool_price_change_pct": change,
        "fee_active_tvl_ratio": fee,
        "volume_change_pct": vol,
        "tvl": tvl,
        "active_tvl": tvl if active is None else active,
        "pool_created_at": created,
    }


def _by_window(**windows):
    """``_by_window(**{"1h": pool, ...})`` → dict window → list pool."""
    return {w: ([p] if p else []) for w, p in windows.items()}


def _status(report, name_start):
    for check in report["checks"]:
        if check["name"].startswith(name_start):
            return check["status"]
    raise AssertionError(f"cek {name_start!r} tidak ada")


class ValidCaTest(unittest.TestCase):
    def test_ca_valid_diterima_dan_spasi_dibuang(self):
        self.assertEqual(lec.valid_ca(f"  {CA}\n"), CA)

    def test_ca_tidak_valid_ditolak(self):
        for bad in ("", "abc", "0" * 44, CA + " extra-ish!", "O" * 40):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    lec.valid_ca(bad)


class FixtureRealPoolTest(unittest.TestCase):
    """Pool 38hkf (dibuat ~6 jam sebelum data diambil)."""

    def setUp(self):
        created = NOW - 6 * HOUR
        self.rows = _by_window(
            **{"1h": _pool("38hk", change=-46.71340579391891, fee=4.130823880374351,
                           tvl=48986.5467296352, active=48556.220656967256, created=created),
               "4h": _pool("38hk", change=233.0737053959754, fee=20.574874236296193,
                           created=created),
               "12h": _pool("38hk", change=0.0, fee=21.58320225501165, created=created),
               "24h": _pool("38hk", change=0.0, fee=21.58320225501165, created=created)})

    def test_gerak_ekstrem_1h_hasilkan_hindari(self):
        report = lec.analyze(CA, self.rows, now_ms=NOW)
        self.assertEqual(report["verdict"], lec.VERDICT_AVOID)
        self.assertEqual(_status(report, "Gerak ekstrem 1H"), "fail")

    def test_perubahan_12h_0_pool_muda_tidak_terukur(self):
        report = lec.analyze(CA, self.rows, now_ms=NOW)
        self.assertIsNone(report["changes"]["12h"])
        self.assertEqual(_status(report, "Harga tenang 12H"), "unknown")

    def test_fee_stabil_tidak_jadi_fail_saat_laju_sama(self):
        # laju 1H = 4,13; laju 4H = 20,57/4 = 5,14 → rasio ~0,80 (dalam 0,5–2,0)
        report = lec.analyze(CA, self.rows, now_ms=NOW)
        self.assertEqual(_status(report, "Fee stabil"), "ok")

    def test_label_fee_untuk_pool_muda(self):
        report = lec.analyze(CA, self.rows, now_ms=NOW)
        names = [c["name"] for c in report["checks"]]
        self.assertTrue(any("sejak dibuat" in n for n in names))
        self.assertAlmostEqual(report["pool_age_hours"], 6.0, places=3)

    def test_format_report_memuat_verdict(self):
        report = lec.analyze(CA, self.rows, now_ms=NOW)
        text = lec.format_report(report)
        self.assertIn("VERDICT: HINDARI", text)
        self.assertIn("−46,71%".replace("−", "-"), text)


class SyntheticVerdictTest(unittest.TestCase):
    def _calm(self, **override):
        created = NOW - 72 * HOUR  # pool 3 hari: 12H & 24H terukur
        base = {
            "1h": dict(change=2.0, fee=0.5, created=created),
            "4h": dict(change=-3.0, fee=2.0, created=created),
            "12h": dict(change=5.0, fee=6.0, created=created),
            "24h": dict(change=8.0, fee=12.0, created=created),
        }
        for window, values in override.items():
            base[window] = dict(base[window], **values)
        return _by_window(**{w: _pool("PoolA", **v) for w, v in base.items()})

    def test_semua_cek_lolos_bagus_untuk_entri(self):
        report = lec.analyze(CA, self._calm(), now_ms=NOW)
        self.assertEqual(report["verdict"], lec.VERDICT_GOOD)
        self.assertEqual(report["warnings"], [])

    def test_harga_4h_bergerak_jauh_tunggu(self):
        rows = self._calm(**{"4h": {"change": 35.0}})
        report = lec.analyze(CA, rows, now_ms=NOW)
        self.assertEqual(report["verdict"], lec.VERDICT_WAIT)
        self.assertEqual(_status(report, "Harga tenang 4H"), "fail")

    def test_fee_24h_rendah_tidak_cocok(self):
        rows = self._calm(**{"24h": {"fee": 3.0}})
        report = lec.analyze(CA, rows, now_ms=NOW)
        self.assertEqual(report["verdict"], lec.VERDICT_BAD_FEE)

    def test_likuiditas_aktif_rendah_tunggu(self):
        created = NOW - 72 * HOUR
        rows = _by_window(**{
            "1h": _pool("PoolA", change=2.0, fee=0.5, tvl=1000.0, active=100.0, created=created),
            "4h": _pool("PoolA", change=-3.0, fee=2.0, tvl=1000.0, active=100.0, created=created),
            "12h": _pool("PoolA", change=5.0, fee=6.0, tvl=1000.0, active=100.0, created=created),
            "24h": _pool("PoolA", change=8.0, fee=12.0, tvl=1000.0, active=100.0, created=created),
        })
        report = lec.analyze(CA, rows, now_ms=NOW)
        self.assertEqual(report["verdict"], lec.VERDICT_WAIT)
        self.assertEqual(_status(report, "Likuiditas aktif"), "fail")

    def test_pool_muda_tanpa_data_12h_belum_cukup_data(self):
        created = NOW - 3 * HOUR
        rows = _by_window(**{
            "1h": _pool("PoolA", change=2.0, fee=0.5, created=created),
            "4h": _pool("PoolA", change=-3.0, fee=2.0, created=created),
            "12h": _pool("PoolA", change=0.0, fee=3.0, created=created),
            "24h": _pool("PoolA", change=0.0, fee=6.0, created=created),
        })
        report = lec.analyze(CA, rows, now_ms=NOW)
        self.assertEqual(report["verdict"], lec.VERDICT_DATA)

    def test_tidak_ada_pool_untuk_ca(self):
        other = _pool("PoolB", change=1.0, fee=10.0, ca="Other" + "1" * 39)
        rows = _by_window(**{"1h": other})
        report = lec.analyze(CA, rows, now_ms=NOW)
        self.assertEqual(report["verdict"], lec.VERDICT_NO_POOL)

    def test_gagal_fetch_1h_jadi_belum_cukup_data_bukan_bagus(self):
        rows = self._calm()
        rows["1h"] = []
        report = lec.analyze(CA, rows, now_ms=NOW, errors={"1h": "HTTP 502"})
        self.assertNotEqual(report["verdict"], lec.VERDICT_GOOD)
        self.assertTrue(any("1H" in w for w in report["warnings"]))

    def test_lonjakan_volume_1h_hanya_catatan(self):
        rows = self._calm(**{"1h": {"vol": 250.0}})
        report = lec.analyze(CA, rows, now_ms=NOW)
        self.assertEqual(report["verdict"], lec.VERDICT_GOOD)
        self.assertTrue(any("Volume 1H" in w for w in report["warnings"]))


class ParseHelpersTest(unittest.TestCase):
    def test_pools_for_mint_hanya_pool_yang_memuat_ca(self):
        mine = _pool("A", change=0.0, fee=1.0)
        other = _pool("B", change=0.0, fee=1.0, ca="X" * 44)
        self.assertEqual([p["pool_address"] for p in lec.pools_for_mint([mine, other], CA)], ["A"])

    def test_usable_change_aturan_app(self):
        now = NOW
        self.assertIsNone(lec._usable_change({"change": 0.0, "created": now - HOUR}, now - HOUR, now))
        self.assertEqual(lec._usable_change({"change": 0.0, "created": now - 48 * HOUR}, now - 48 * HOUR, now), 0.0)
        self.assertIsNone(lec._usable_change(None, None, now))


if __name__ == "__main__":
    unittest.main()
