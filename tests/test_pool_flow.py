# -*- coding: utf-8 -*-
"""Tes logika Scan Best Pool (timeframe 12H, avg volume per menit, satu tabel) — tanpa jaringan.

Tidak ada filter seleksi lokal (permintaan user 2026-11-14): seleksi hanya dari filter server.
``PASSING_12H`` berisi dua baris nyata dari respons Meteora timeframe=12h dengan filter user.
``METEORA_24H`` adalah fixture lama (14 pool) untuk tes paginasi dan alert.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pool_flow as pf  # noqa: E402

SOL = "So11111111111111111111111111111111111111112"


def _row(pool, symbol, *, fee=2.0, tvl=20_000.0, active_tvl=5_000.0, holders=2_000,
         mcap=500_000.0, vol=2.0, fa=10.0, open_pos=50, active=40, mint=None,
         volume=720_000.0, swaps=500.0, traders=200.0, ftvl=20.0):
    mint = mint or ("M" + pool[:8].ljust(43, "x"))
    return {"pool_address": pool, "name": f"{symbol}-SOL", "pool_type": "dlmm",
            "token_x": {"address": mint, "symbol": symbol, "name": symbol,
                        "market_cap": mcap},
            "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
            "fee_pct": fee, "tvl": tvl, "active_tvl": active_tvl,
            "base_token_holders": holders, "open_positions": open_pos,
            "active_positions": active, "volatility": vol, "fee_active_tvl_ratio": fa,
            "volume": volume, "avg_volume": volume / 720.0,
            "swap_count": swaps, "unique_traders": traders,
            "fee_tvl_ratio": ftvl}  # nilai uji untuk pemisahan tabel (2026-11-15)


# pool, symbol, fee, tvl, active_tvl, holders, mcap, volatility, fee/active TVL, open, active
METEORA_24H = [
    ("91iHWaWXneUyoNDJhSno7ezxQg1VW5P6PdarNGyFfPCz", "STANK", 2.0, 100873.57, 97133.86, 5083, 1958893.17, 2.730948306399437, 14.182777407121913, 238, 190),
    ("9JZrcAScnGQp7DSV4kBWfmGH2ao31sz5JbJ8cnpZ9uwv", "CHOO", 2.0, 86042.99, 84760.24, 7201, 1152810.07, 1.5618331251100772, 7.469201539173313, 173, 129),
    ("GWe6KGwM4tUyBFMWe1xjLYZu7dmmEDex5ScoJ1oiuacY", "USELESS", 2.0, 18418.43, 2018.085, 69203, 134961507.10, 0.4268159179118895, 1.6401911898189765, 18, 3),
    ("5Dc4s9fxxQoPfaMUaxFKB5v1Nh6FPqest7usgyvGXwWw", "DacityCoin", 2.0, 117707.18, 114211.47, 12435, 4772220.09, 2.4218466831988774, 9.157669232739185, 232, 153),
    ("9ViFN1A2FG2aL69Uu3dZwVMbcSdKuuMM5PLouZmguK2e", "mihao", 2.0, 107119.48, 103862.48, 31615, 14361538.78, 2.197522427661364, 8.145744362117817, 201, 142),
    ("BADiqzWTYyZPbcqKgNtgy6KB5ZhmPrgq9qguPnpjXHf8", "Rocco", 2.0, 13217.43, 12110.51, 2222, 586541.14, 2.8478107097362697, 9.63119736506875, 49, 42),
    # gagal:
    ("DnmL7vYnNTACb8e6a4EpbeeeNDW8hwp1EvQZ4BWKCgjK", "GATO", 3.0, 135395.37, 133647.02, 11769, 4969076.57, 1.819463479422516, 4.508445441715985, 183, 158),  # 2,48x
    ("EWBCL4hKY6VdzZVcCY7pMPvRhG78koHY6nQnt8EW99Br", "LMAO!", 2.0, 134591.59, 131647.48, 15791, 1039609.05, 2.942714221664328, 3.6073866134371526, 78, 66),  # 1,23x
    ("5WVURqJSLRFNZDVDF2njtjZihRLeALvt5tss3yjt2Vik", "paws", 2.0, 47308.20, 46647.47, 2789, 895713.73, 3.346236475355708, 11.025536070549084, 155, 84),  # 3,29x, vol 3,35% (lolos di batas 5%)
    ("FSb7qz3cMGjYacrLfoKumozoqFibiAtzjDq97FxHivYP", "DacityCoin", 5.0, 13452.87, 12153.33, 12435, 4772220.09, 3.0831077573643584, 8.639426602320858, 37, 32),  # 2,80x (gagal)
    ("2wqaQVQ54bayWCjfsV391BQHA13qiVgjagSRtQPFJ6wu", "PUMPCADE", 2.0, 13964.92, 13611.18, 5189, 16268607.69, 4.6566128730773926e-08, 0.41077066347875446, 18, 18),  # vol ≈ 0
    ("3Keu4gPtDUnkoLpas8HauhPZgpiiADPNtJAB4UDQWbpi", "MET", 5.0, 18357.78, 11461.53, 43957, 163835898.74, 1.6463612699567982e-08, 0.0970318184860885, 45, 2),  # vol ≈ 0
    ("8tp8GJADuYu2czhnaWzXYxpXTq2dwjribGwSav4J4m7e", "xHYPE", 2.0, 104436.62, 100742.69, 6642, 616063.37, 1.0094755398497184, 0.4270554720456035, 106, 39),  # 0,42x
    ("BiNnErm2VDkbKGiABj9ZRUjybz879NhH2heeWE7m5M6d", "OMFG", 2.0, 21675.94, 21916.94, 1734, 1850686.66, 0.0, 0.00217943551742239, 3, 2),  # vol 0
]


def meteora_rows():
    return [_row(p, s, fee=f, tvl=t, active_tvl=at, holders=h, mcap=m, vol=v, fa=fa,
                 open_pos=o, active=a)
            for p, s, f, t, at, h, m, v, fa, o, a in METEORA_24H]


FOOD_12H = {  # respons Meteora timeframe=12h (filter user), baris nyata
    "pool_address": "3gH2fgs9XuQiEEnLd7bHp6XqoeHHZgajUeaHAPu1BGQK", "name": "FOOD-SOL",
    "token_x": {"address": "FTu55MyigXns96jz4nTCDDiTCjYJjyrHSceCgG9Upump", "symbol": "FOOD",
                "name": "Foodcoin", "market_cap": 1550966.5513647932},
    "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
    "pool_type": "dlmm", "fee_pct": 0.8, "tvl": 90546.53933826268,
    "active_tvl": 88168.47686717712, "base_token_holders": 7315,
    "volatility": 3.0727226280906574, "fee_active_tvl_ratio": 19.2580460899264,
    "volume": 1080422.1793620202, "avg_volume": 1500.586360225028,
    "swap_count": 10269.0, "unique_traders": 2975.0,
    "fee_tvl_ratio": 9.5,  # nilai uji (fee/TVL tidak ada di fixture): > 2 × 3,07 % → FEE PRINTER
}
DUT_12H = {  # respons Meteora timeframe=12h (filter user), baris nyata; volatility ≥ 5 %
    "pool_address": "DutNdXzYJ1bWZk8EnSyi5oCD5fApwnShUaECZgAVwmDR", "name": "Sakura-SOL",
    "token_x": {"address": "9sFGCTjEsBk78uC2bCdxtwuUM1aartbBhe8WQXwRpump", "symbol": "Sakura",
                "name": "サクラ", "market_cap": 413699.2590807437},
    "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
    "pool_type": "dlmm", "fee_pct": 3.0, "tvl": 21082.437468700755,
    "active_tvl": 21296.248429951927, "base_token_holders": 4762,
    "volatility": 6.714632474296901, "fee_active_tvl_ratio": 68.31188525088334,
    "volume": 355696.57481688383, "avg_volume": 494.02302057900533,
    "swap_count": 5360.0, "unique_traders": 1828.0,
    "fee_tvl_ratio": 20.0,  # nilai uji
}
REAL_12H = [FOOD_12H, DUT_12H]
# FOOD dengan fee 2 % agar lolos filter fee tier 1 % (uji jalur lolos; FOOD asli fee 0,8 % dilewati)
LOW_12H = dict(FOOD_12H, fee_pct=2.0)
HIGH_12H = _row("H" * 44, "HIGHX", fa=12.0, vol=5.5, volume=720.0 * 800)  # volatility 5,5 %
PASSING_12H = [LOW_12H, HIGH_12H]
# FOOD-SOL pool DQjZ… (fee 2 %), respons Meteora timeframe=12h nyata: LP keluar > masuk, TVL < $50K
FOOD2_12H = {
    "pool_address": "DQjZKw199L4788unoRUf9FMw63suJJ45hc9brXV3oQec", "name": "FOOD-SOL",
    "token_x": {"address": "FTu55MyigXns96jz4nTCDDiTCjYJjyrHSceCgG9Upump", "symbol": "FOOD",
                "name": "Foodcoin", "market_cap": 1006687.6790911813,
                "has_mint_authority": False, "has_freeze_authority": False,
                "top_holders_pct": 13.328027576488733, "dev_balance_pct": 0.01673305387042115},
    "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
    "pool_type": "dlmm", "fee_pct": 2.0, "tvl": 23407.6551364514,
    "active_tvl": 22287.135273606633, "base_token_holders": 7077,
    "volatility": 3.095570505242116, "fee_active_tvl_ratio": 15.732076557116905,
    "volume": 142016.8152715878, "avg_volume": 197.2455767660942,
    "swap_count": 2283.0, "unique_traders": 779.0, "fee_tvl_ratio": 5.0,  # nilai uji (band 0,5–2×)
    "total_deposits": 439629.8261476154, "total_withdraws": 508479.7435556029,
    "net_deposits": -68849.91740798746,
}


class NoLocalFilterTest(unittest.TestCase):
    """Permintaan user 2026-11-14: semua filter seleksi lokal dihapus. Pool hanya dari listing."""

    def test_fee_tier_rendah_tetap_lolos(self):
        self.assertTrue(pf.evaluate_pool(_row("T" * 44, "TIERX", fee=0.1))["passes"])

    def test_avg_volume_rendah_tetap_lolos(self):
        result = pf.evaluate_pool(_row("A" * 44, "SMALLV", volume=720.0 * 10))  # avg 10
        self.assertTrue(result["passes"])
        self.assertEqual(result["reasons"], [])

    def test_fee_active_tvl_rendah_tetap_lolos(self):
        self.assertTrue(pf.evaluate_pool(_row("F" * 44, "FAX", fa=0.5))["passes"])

    def test_volatility_tinggi_tetap_lolos(self):
        self.assertTrue(pf.evaluate_pool(_row("V" * 44, "VOLX", vol=9.5))["passes"])

    def test_volatility_tidak_terukur_tetap_lolos(self):
        self.assertTrue(pf.evaluate_pool(_row("N" * 44, "NOVOL", vol=None))["passes"])

    def test_dut_12h_tetap_lolos(self):
        self.assertTrue(pf.evaluate_pool(DUT_12H)["passes"])

    def test_scan_memuat_semua_baris_unik_dari_listing(self):
        extra = [DUT_12H, _row("S" * 44, "SHORT", volume=720.0 * 100)]
        result = pf.scan_pools(listing=(PASSING_12H + extra, [], False))
        self.assertEqual(result["candidates"], 4)
        self.assertEqual(sorted(r["pool"] for r in result["passing"]),
                         sorted([LOW_12H["pool_address"], HIGH_12H["pool_address"],
                                 DUT_12H["pool_address"], "S" * 44]))


def _sec(*, tvl=20_000.0, deposits=None, withdraws=None, fa=10.0, avg=None, **token):
    """Baris pool dengan field keamanan yang diatur tes (fa/avg ke baris pool, sisanya ke token_x)."""
    row = _row("S" * 44, "SECX", tvl=tvl, fa=fa)
    row["token_x"].update(token)
    if avg is not None:
        row["avg_volume"] = avg
    if deposits is not None:
        row["total_deposits"] = deposits
    if withdraws is not None:
        row["total_withdraws"] = withdraws
    return row


class SecurityTest(unittest.TestCase):
    """Filter keamanan (permintaan user 2026-11-14): blokir vs peringatan."""

    def test_mint_authority_aktif_diblokir(self):
        result = pf.evaluate_pool(_sec(has_mint_authority=True))
        self.assertFalse(result["passes"])
        self.assertIn("keamanan: mint authority masih aktif", result["reasons"])

    def test_freeze_authority_aktif_diblokir(self):
        result = pf.evaluate_pool(_sec(has_freeze_authority=True))
        self.assertFalse(result["passes"])
        self.assertIn("keamanan: freeze authority masih aktif", result["reasons"])

    def test_authority_nonaktif_lolos(self):
        result = pf.evaluate_pool(_sec(has_mint_authority=False, has_freeze_authority=False))
        self.assertTrue(result["passes"])

    def test_top_holders_di_atas_30_diblokir(self):
        self.assertFalse(pf.evaluate_pool(_sec(top_holders_pct=30.5))["passes"])

    def test_top_holders_tepat_30_tidak_diblokir(self):
        result = pf.evaluate_pool(_sec(top_holders_pct=30.0))
        self.assertTrue(result["passes"])
        self.assertEqual(result["warnings"], ["top holders 30,0%"])

    def test_top_holders_16_persen_hanya_peringatan(self):
        result = pf.evaluate_pool(_sec(top_holders_pct=16.0))
        self.assertTrue(result["passes"])
        self.assertEqual(result["warnings"], ["top holders 16,0%"])

    def test_top_holders_tepat_15_tanpa_peringatan(self):
        result = pf.evaluate_pool(_sec(top_holders_pct=15.0))
        self.assertEqual(result["warnings"], [])

    def test_dev_di_atas_5_persen_peringatan(self):
        result = pf.evaluate_pool(_sec(dev_balance_pct=6.0))
        self.assertTrue(result["passes"])
        self.assertEqual(result["warnings"], ["dev 6,0%"])

    def test_lp_keluar_di_bawah_50k_peringatan(self):
        result = pf.evaluate_pool(_sec(tvl=23_000.0, deposits=100.0, withdraws=200.0))
        self.assertTrue(result["passes"])
        self.assertTrue(any(w.startswith("LP keluar") for w in result["warnings"]))

    def test_lp_keluar_di_atas_50k_tanpa_peringatan(self):
        result = pf.evaluate_pool(_sec(tvl=60_000.0, deposits=100.0, withdraws=200.0))
        self.assertFalse(any(w.startswith("LP keluar") for w in result["warnings"]))

    def test_lp_tidak_keluar_lebih_besar_tanpa_peringatan(self):
        result = pf.evaluate_pool(_sec(tvl=23_000.0, deposits=300.0, withdraws=200.0))
        self.assertEqual(result["warnings"], [])

    def test_field_kosong_tidak_dihitung(self):
        result = pf.evaluate_pool(_row("K" * 44, "NOSEC"))
        self.assertTrue(result["passes"])
        self.assertEqual(result["warnings"], [])

    def test_food2_nyata_hanya_peringatan_lp_keluar(self):
        result = pf.evaluate_pool(FOOD2_12H)
        self.assertEqual(result["warnings"], ["LP keluar > masuk (TVL < $50K)"])
        self.assertTrue(result["passes"])
        self.assertEqual(result["reasons"], [])

    def test_pool_terblokir_tidak_masuk_hasil_scan(self):
        blocked = _sec(has_mint_authority=True, fa=50.0, avg=9000.0)
        result = pf.scan_pools(listing=(PASSING_12H + [blocked], [], False))
        self.assertNotIn(blocked["pool_address"], [r["pool"] for r in result["passing"]])
        self.assertIn(blocked["pool_address"], [r["pool"] for r in result["results"]])

    def test_alert_memuat_peringatan_keamanan(self):
        warned = _sec(top_holders_pct=20.0, fa=50.0, avg=9000.0)
        result = pf.scan_pools(listing=(PASSING_12H + [warned], [], False))
        top = pf.most_crowded(result)
        self.assertEqual(top["pool"], warned["pool_address"])
        text = pf.crowded_alert_text(1, top, None)
        self.assertIn("Peringatan keamanan", text)
        self.assertIn("top holders 20,0%", text)

    def test_alert_tanpa_peringatan_tidak_memuat_baris_keamanan(self):
        result = pf.scan_pools(listing=(PASSING_12H, [], False))
        text = pf.crowded_alert_text(1, pf.most_crowded(result), None)
        self.assertNotIn("Peringatan keamanan", text)

    def test_tabel_memuat_kolom_peringatan_keamanan(self):
        import pool_flow_ui as ui
        row = pf.evaluate_pool(FOOD2_12H)
        html = ui._result_table_html([row])
        self.assertIn("Peringatan keamanan", html)
        self.assertIn("LP keluar &gt; masuk", html)


class RiskTest(unittest.TestCase):
    def test_tvl_kecil_tidak_difilter_lokal(self):
        row = _row("P" * 44, "SMALLX", tvl=100.0, active_tvl=10.0, holders=10, mcap=1.0)
        self.assertTrue(pf.evaluate_pool(row)["passes"])

    def test_evaluate_pool_membawa_avg_volume(self):
        row = _row("Q" * 44, "HIGHX", vol=5.5, volume=7200.0 * 72)  # avg 720
        result = pf.evaluate_pool(row)
        self.assertAlmostEqual(result["avg_volume"], 720.0)


def _fp(pool, fee_tvl, vol, symbol="FP"):
    """Baris pool dengan fee/TVL (%) dan volatility (%) yang diatur tes."""
    row = _row(pool, symbol, vol=vol)
    row["fee_tvl_ratio"] = fee_tvl
    return row


class FeePrinterSplitTest(unittest.TestCase):
    """Permintaan user 2026-11-15: FEE PRINTER (SPOT) bila fee/TVL > 2 × volatility;
    tabel kedua bila 0,5 × volatility ≤ fee/TVL ≤ 2 × volatility."""

    def _split(self, *rows):
        result = pf.scan_pools(listing=(list(rows), [], False))
        return pf.fee_printer_split(result["passing"])

    def test_fee_tvl_di_atas_2x_volatility_masuk_fee_printer(self):
        spot, band = self._split(_fp("1" * 44, fee_tvl=2.5, vol=1.0))
        self.assertEqual([r["pool"] for r in spot], ["1" * 44])
        self.assertEqual(band, [])

    def test_batas_tepat_2x_masuk_tabel_kedua(self):
        # contoh user: volatility 1 %, fee/TVL 2 % -> tabel kedua
        spot, band = self._split(_fp("2" * 44, fee_tvl=2.0, vol=1.0))
        self.assertEqual(spot, [])
        self.assertEqual([r["pool"] for r in band], ["2" * 44])

    def test_batas_tepat_0_5x_masuk_tabel_kedua(self):
        # contoh user: volatility 1 %, fee/TVL 0,5 % -> tabel kedua
        spot, band = self._split(_fp("3" * 44, fee_tvl=0.5, vol=1.0))
        self.assertEqual(spot, [])
        self.assertEqual([r["pool"] for r in band], ["3" * 44])

    def test_fee_tvl_di_bawah_0_5x_tidak_masuk_tabel_mana_pun(self):
        spot, band = self._split(_fp("4" * 44, fee_tvl=0.4, vol=1.0))
        self.assertEqual((spot, band), ([], []))

    def test_volatility_tidak_terukur_tidak_masuk_tabel_mana_pun(self):
        rows = [_fp("5" * 44, fee_tvl=9.0, vol=None),
                _fp("6" * 44, fee_tvl=9.0, vol=0.005)]  # di bawah 0,01 %
        self.assertEqual(self._split(*rows), ([], []))

    def test_fee_tvl_hilang_tidak_masuk_tabel_mana_pun(self):
        self.assertEqual(self._split(_fp("7" * 44, fee_tvl=None, vol=1.0)), ([], []))

    def test_volatility_0_01_persen_masih_terukur(self):
        spot, band = self._split(_fp("8" * 44, fee_tvl=0.02, vol=0.01))
        self.assertEqual(spot, [])
        self.assertEqual([r["pool"] for r in band], ["8" * 44])

    def test_urut_di_tiap_tabel_fee_active_lalu_avg_volume(self):
        rows = [_fp("A" * 44, fee_tvl=3.0, vol=1.0),
                _fp("B" * 44, fee_tvl=5.0, vol=1.0),
                _fp("C" * 44, fee_tvl=1.5, vol=1.0),
                _fp("D" * 44, fee_tvl=1.0, vol=1.0)]
        for r, fa in zip(rows, (5.0, 8.0, 5.0, 8.0)):
            r["fee_active_tvl_ratio"] = fa
        spot, band = self._split(*rows)
        self.assertEqual([r["pool"] for r in spot], ["B" * 44, "A" * 44])  # fee/active 8 dulu
        self.assertEqual([r["pool"] for r in band], ["D" * 44, "C" * 44])

    def test_pool_terblokir_keamanan_tidak_masuk_tabel(self):
        blocked = _fp("E" * 44, fee_tvl=9.0, vol=1.0)
        blocked["token_x"]["has_mint_authority"] = True
        spot, band = self._split(blocked)
        self.assertEqual((spot, band), ([], []))

    def test_evaluate_pool_membawa_fee_tvl(self):
        self.assertEqual(pf.evaluate_pool(_fp("F" * 44, fee_tvl=4.2, vol=1.0))["fee_tvl"], 4.2)


class ServerFilterTest(unittest.TestCase):
    def test_filter_server_persis_request_user(self):
        self.assertEqual(
            pf.FLOW_SERVER_FILTER,
            "base_token_has_critical_warnings=false"
            "&&quote_token_has_critical_warnings=false"
            "&&base_token_has_high_supply_concentration=false"
            "&&base_token_has_high_single_ownership=false"
            "&&pool_type=dlmm"
            "&&tvl>=10000"
            "&&fee_tvl_ratio>=2"
            "&&fee_pct>=0.5")
        self.assertEqual(pf.FLOW_TIMEFRAME, "12h")
        self.assertEqual(pf.FLOW_CATEGORY, "all")


class RealResponseTest(unittest.TestCase):
    def test_urut_fee_active_lalu_avg_volume(self):
        result = pf.scan_pools(listing=(PASSING_12H, [], False))
        # LOW_12H fee/active 19,26 % > HIGH_12H 12 %
        self.assertEqual([r["symbol"] for r in result["passing"]], ["FOOD", "HIGHX"])
        self.assertEqual(result["candidates"], 2)

    def test_pool_teratas_untuk_alert(self):
        result = pf.scan_pools(listing=(PASSING_12H, [], False))
        top = pf.most_crowded(result)
        self.assertEqual(top["pool"], LOW_12H["pool_address"])


class ScanTest(unittest.TestCase):
    def test_urut_fee_active_lalu_avg_volume_lalu_volume(self):
        rows = [_row("A" * 44, "AAA", fa=5.0, volume=720.0 * 1000),
                _row("B" * 44, "BBB", fa=8.0, volume=720.0 * 600),
                _row("C" * 44, "CCC", fa=5.0, volume=720.0 * 2000)]
        result = pf.scan_pools(listing=(rows, [], False))
        # fee/active tertinggi dulu (B); seri 5 %: avg volume terbesar (C lalu A)
        self.assertEqual([r["pool"] for r in result["passing"]],
                         ["B" * 44, "C" * 44, "A" * 44])

    def test_pool_duplikat_dihitung_sekali(self):
        rows = PASSING_12H + [LOW_12H]
        result = pf.scan_pools(listing=(rows, [], False))
        self.assertEqual(result["candidates"], 2)
        self.assertEqual(len(result["passing"]), 2)

    def test_truncated_dan_error_ikut_dilaporkan(self):
        result = pf.scan_pools(listing=(PASSING_12H, ["gagal"], True))
        self.assertTrue(result["truncated"])
        self.assertEqual(result["listing_errors"], 1)

    def test_fetch_listing_mengirim_request_12h_sesuai_curl_user(self):
        captured = []

        def fake_get(params, **kwargs):
            captured.append(dict(params))
            return {"data": [], "has_more": False}

        with mock.patch.object(pf, "_get_payload", side_effect=fake_get):
            rows, errors, truncated = pf.fetch_listing()
        self.assertEqual((rows, errors, truncated), ([], [], False))
        self.assertEqual(len(captured), 1)
        params = captured[0]
        self.assertEqual(params["timeframe"], "12h")
        self.assertEqual(params["category"], "all")
        self.assertNotIn("sort_by", params)  # curl user 2026-11-15 tanpa sort_by
        self.assertEqual(params["page_size"], 50)
        self.assertNotIn("after_key", params)
        self.assertNotIn("page", params)  # page diabaikan API Meteora
        self.assertEqual(params["filter_by"], pf.FLOW_SERVER_FILTER)


class PaginationTest(unittest.TestCase):
    """Paginasi cursor: halaman berikutnya diminta dengan ``after_key``."""

    def _cursor(self, sizes, errors_at=(), stuck=False):
        """Fake API. ``sizes`` = jumlah baris tiap halaman. Panggilan ke-n (0-based)
        diidentifikasi dari ``after_key`` = ``k<n>``."""
        calls = []

        def fake(params, **kwargs):
            key = params.get("after_key")
            index = 0 if key is None else (0 if stuck and key == "stuck" else int(key[1:]))
            calls.append(dict(params))
            if index in errors_at:
                raise RuntimeError("boom")
            size = sizes[index] if index < len(sizes) else 0
            has_more = index + 1 < len(sizes)
            next_key = ("stuck" if stuck else f"k{index + 1}") if has_more else None
            data = [{"pool_address": f"P{index}-{i}"} for i in range(size)]
            return {"data": data, "after_key": next_key, "has_more": has_more}

        return mock.patch.object(pf, "_get_payload", side_effect=fake), calls

    def test_berhenti_saat_has_more_false(self):
        patcher, calls = self._cursor([50, 50, 3])
        with patcher:
            rows, errors, truncated = pf.fetch_listing(max_pages=10)
        self.assertEqual(len(rows), 103)
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(len(calls), 3)
        self.assertNotIn("after_key", calls[0])
        self.assertEqual([c.get("after_key") for c in calls[1:]], ["k1", "k2"])
        self.assertTrue(all("page" not in c for c in calls))

    def test_tanpa_pool_tidak_ada_halaman_tambahan(self):
        patcher, calls = self._cursor([50])
        with patcher:
            rows, _, truncated = pf.fetch_listing()
        self.assertEqual(len(rows), 50)
        self.assertFalse(truncated)
        self.assertEqual(len(calls), 1)

    def test_truncated_bila_batas_tercapai_selagi_masih_ada_halaman(self):
        patcher, calls = self._cursor([50, 50, 50, 50])
        with patcher:
            rows, _, truncated = pf.fetch_listing(max_pages=3)
        self.assertEqual(len(rows), 150)
        self.assertTrue(truncated)
        self.assertEqual(len(calls), 3)

    def test_error_halaman_menghentikan_dan_menandai_tidak_lengkap(self):
        patcher, _ = self._cursor([50, 50, 4], errors_at=(1,))
        with patcher:
            rows, errors, truncated = pf.fetch_listing()
        self.assertEqual(errors, ["boom"])
        self.assertEqual(len(rows), 50)
        self.assertTrue(truncated)

    def test_cursor_macet_dihentikan(self):
        patcher, calls = self._cursor([50, 50, 50], stuck=True)
        with patcher:
            rows, errors, truncated = pf.fetch_listing(max_pages=100)
        self.assertTrue(truncated)
        self.assertEqual(len(calls), 2)
        self.assertEqual(errors, [])

    def test_halaman_pertama_gagal_tanpa_baris(self):
        patcher, _ = self._cursor([50], errors_at=(0,))
        with patcher:
            rows, errors, truncated = pf.fetch_listing()
        self.assertEqual(rows, [])
        self.assertEqual(errors, ["boom"])
        self.assertTrue(truncated)

    def test_truncated_diteruskan_ke_scan(self):
        result = pf.scan_pools(listing=([], [], True))
        self.assertTrue(result["truncated"])


def rows_pool(index: int) -> str:
    """Alamat pool fixture METEORA_24H ke-index (0-based)."""
    return METEORA_24H[index][0]


class AlertTest(unittest.TestCase):
    """Alert Telegram: hanya pool paling ramai (avg volume per menit terbesar)."""

    def test_tanpa_pool_paling_ramai_tidak_ada_alert(self):
        state = pf.empty_state()
        self.assertIsNone(pf.apply_crowded_alert(state, None))
        self.assertEqual(state["alerts"], [])
        self.assertEqual(state["best_alert"]["next_no"], 1)

    def test_alert_hanya_memuat_satu_pool_paling_ramai(self):
        result = pf.scan_pools(listing=(PASSING_12H, [], False))
        state = pf.empty_state()
        text = pf.apply_crowded_alert(state, pf.most_crowded(result))
        self.assertIn("POOL PALING RAMAI", text)
        self.assertIn("FOOD", text)
        self.assertNotIn("Sakura", text)
        self.assertEqual(len(state["alerts"]), 1)
        self.assertEqual(state["alerts"][0]["pools"], [LOW_12H["pool_address"]])
        self.assertEqual(list(state["best_alert"]["last_no"]), [LOW_12H["pool_address"]])

    def test_alert_memilih_pool_teratas_urutan_fee_active(self):
        rows = [_row("H" * 44, "HIGHX", vol=6.0, volume=720.0 * 900),   # avg 900, HIGH
                _row("L" * 44, "LOWY", vol=2.0, volume=720.0 * 100)]    # avg 100, LOW
        result = pf.scan_pools(listing=(rows, [], False))
        top = pf.most_crowded(result)
        self.assertEqual(top["symbol"], "HIGHX")
        text = pf.apply_crowded_alert(pf.empty_state(), top)
        self.assertNotIn("RISK", text)

    def test_alert_memberi_nomor_dan_tag_sudah_pernah(self):
        result = pf.scan_pools(listing=(PASSING_12H, [], False))
        state = pf.empty_state()
        top = pf.most_crowded(result)
        first = pf.apply_crowded_alert(state, top)
        self.assertIn("alert #1", first)
        self.assertIn("🆕 baru", first)
        second = pf.apply_crowded_alert(state, top)
        self.assertIn("alert #2", second)
        self.assertIn("🔁 sudah pernah · alert #1", second)
        self.assertEqual(state["best_alert"]["next_no"], 3)

    def test_alert_memuat_avg_volume_12h_dan_tautan(self):
        result = pf.scan_pools(listing=(PASSING_12H, [], False))
        text = pf.apply_crowded_alert(pf.empty_state(), pf.most_crowded(result))
        self.assertIn("avg volume/menit", text)
        self.assertIn("volume 12H", text)
        self.assertNotIn("RISK", text)
        self.assertNotIn("4H", text)
        self.assertNotIn("24H", text)
        for host in ("gmgn.ai", "meteora.ag", "hawkfi.ag", "dexscreener.com"):
            self.assertIn(host, text)

    def test_split_telegram_tiap_bagian_di_bawah_batas(self):
        long_text = "\n".join(["baris panjang " * 20] * 400)
        parts = pf.split_for_telegram(long_text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= pf.TELEGRAM_CHUNK for part in parts))


class TelegramCopyTest(unittest.TestCase):
    """Tombol 📋 CA (copy_text) pada alert Telegram dan jadwal 4 jam."""

    def _passing(self):
        return pf.scan_pools(listing=(meteora_rows(), [], False))["passing"]

    def test_satu_tombol_copy_per_pool_dengan_ca_lengkap(self):
        passing = self._passing()
        markup = pf.alert_copy_markup(passing)
        rows = markup["inline_keyboard"]
        self.assertEqual(len(rows), len(passing))
        for row, pool in zip(rows, passing):
            (button,) = row
            self.assertEqual(button["copy_text"], {"text": pool["mint"]})
            self.assertIn(pool["symbol"], button["text"])
            self.assertLessEqual(len(button["copy_text"]["text"]), 256)

    def test_tanpa_pool_atau_tanpa_ca_tidak_ada_tombol(self):
        self.assertIsNone(pf.alert_copy_markup([]))
        self.assertIsNone(pf.alert_copy_markup([{"mint": "", "symbol": "X"}]))

    def _capture(self):
        sent = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=None):
            sent.append(json.loads(request.data.decode("utf-8")))
            return Resp()

        return mock.patch.object(pf.urllib.request, "urlopen", side_effect=fake_urlopen), sent

    def test_payload_menyertakan_reply_markup(self):
        patcher, sent = self._capture()
        markup = pf.alert_copy_markup(self._passing())
        with patcher, mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t",
                                                     "TELEGRAM_CHAT_ID": "1"}):
            ok, error = pf.send_telegram("pendek", reply_markup=markup)
        self.assertTrue(ok, error)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["reply_markup"], markup)
        self.assertEqual(sent[0]["parse_mode"], "HTML")

    def test_pesan_terpecah_hanya_bagian_terakhir_punya_tombol(self):
        patcher, sent = self._capture()
        markup = pf.alert_copy_markup(self._passing())
        text = "\n".join("baris " + "x" * 90 for _ in range(200))
        with patcher, mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t",
                                                     "TELEGRAM_CHAT_ID": "1"}):
            ok, _ = pf.send_telegram(text, reply_markup=markup)
        self.assertTrue(ok)
        self.assertGreater(len(sent), 1)
        self.assertTrue(all("reply_markup" not in body for body in sent[:-1]))
        self.assertEqual(sent[-1]["reply_markup"], markup)

    def test_tanpa_markup_payload_tidak_berisi_reply_markup(self):
        patcher, sent = self._capture()
        with patcher, mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t",
                                                     "TELEGRAM_CHAT_ID": "1"}):
            pf.send_telegram("pendek")
        self.assertNotIn("reply_markup", sent[0])

    def _alert_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pool_flow_alert", ROOT / "scripts" / "pool_flow_alert.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_run_best_satu_pesan_satu_tombol_tanpa_fetch_per_token(self):
        alert = self._alert_module()
        state = pf.empty_state()
        messages = alert.run_best(state, scan=lambda: pf.scan_pools(
            listing=(PASSING_12H, [], False)))
        self.assertEqual(len(messages), 1)
        text, markup = messages[0]
        self.assertIn("POOL PALING RAMAI", text)
        self.assertEqual(len(markup["inline_keyboard"]), 1)
        (button,) = markup["inline_keyboard"][0]
        self.assertEqual(button["copy_text"]["text"], pf.mint_of_pool(LOW_12H))
        self.assertEqual(state["best_alert"]["next_no"], 2)

    def test_run_best_tanpa_pool_lolos_tidak_mengirim(self):
        alert = self._alert_module()
        state = pf.empty_state()
        self.assertEqual(alert.run_best(state, scan=lambda: {
            "passing": [], "listing_rows": 0, "candidates": 0,
            "listing_errors": 0, "truncated": False}), [])
        self.assertEqual(state["alerts"], [])


class FormatTest(unittest.TestCase):
    """Format angka ringkas (K/M, tanpa pemisah ribuan titik)."""

    def test_fmt_ringkas_k_dan_m(self):
        self.assertEqual(pf.fmt_usd(500), "$500")
        self.assertEqual(pf.fmt_usd(999.4), "$999")
        self.assertEqual(pf.fmt_usd(999.6), "$1K")          # pembulatan naik ke ribuan
        self.assertEqual(pf.fmt_usd(23407.65), "$23,4K")
        self.assertEqual(pf.fmt_usd(50000), "$50K")
        self.assertEqual(pf.fmt_usd(1_080_422), "$1,1M")
        self.assertEqual(pf.fmt_usd(-68849.9), "-$68,8K")
        self.assertEqual(pf.fmt_usd2(1500.59), "$1,50K")
        self.assertEqual(pf.fmt_usd2(688.33), "$688,33")
        self.assertEqual(pf.fmt_int(999), "999")
        self.assertEqual(pf.fmt_int(10269), "10,3K")
        self.assertNotIn(".", pf.fmt_usd(1234567) + pf.fmt_usd2(9876.5) + pf.fmt_int(4321))


    def test_fmt_usd2_dan_fmt_int(self):
        self.assertEqual(pf.fmt_usd2(57.08), "$57,08")
        self.assertEqual(pf.fmt_usd2(1234.5), "$1,23K")
        self.assertEqual(pf.fmt_usd2(None), "—")
        self.assertEqual(pf.fmt_int(13633), "13,6K")
        self.assertEqual(pf.fmt_int(None), "—")



class StateTest(unittest.TestCase):
    def test_state_tidak_lagi_menyimpan_watchlist_dan_membuang_kunci_lama(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"watchlist": [{"pool": "x"}], "history": {"x": []},
                                        "watch_negative": {}, "best_alert": {"next_no": 3,
                                        "last_no": {"p": 2}}, "alerts": []}), encoding="utf-8")
            state = pf.load_state(path)
            self.assertNotIn("watchlist", state)
            self.assertNotIn("history", state)
            self.assertEqual(state["best_alert"]["next_no"], 3)
            pf.save_state(state, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("watchlist", saved)

    def test_scan_tidak_menulis_berkas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool_flow_state.json"
            pf.scan_pools(listing=(meteora_rows(), [], False))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Aktivitas per token (permintaan user 2026-11-13): semua pool token, timeframe 4H
# Angka dari respons Meteora query=9sFG…&timeframe=4h (2026-11-13).
# ---------------------------------------------------------------------------

