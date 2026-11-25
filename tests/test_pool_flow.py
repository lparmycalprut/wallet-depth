# -*- coding: utf-8 -*-
"""Tes logika Scan ALL, FEE PRINTER (timeframe 24H) — tanpa jaringan.

Aturan (permintaan user, 2026-11-24): volatility 0,01–3 %, fee/active TVL ≥ 2 × volatility,
net deposit ≥ +10.000 USD. Urut fee/active TVL ÷ volatility terbesar dulu.
Filter server = curl user (urutan parameter persis), dua batas waktu dihitung dari waktu scan.
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

OLD_TOKEN_MS = 1_700_000_000_000  # token berumur > 24 jam untuk tes (ms)
OLD_POOL_MS = 1_700_000_000_000  # pool berumur > 24 jam terhadap waktu tes (ms)

CURL_USER_FILTER = (
    "base_token_has_high_supply_concentration=false"
    "&&base_token_has_high_single_ownership=false"
    "&&pool_type=dlmm"
    "&&base_token_market_cap>=20000"
    "&&base_token_created_at<=1795484047775"
    "&&base_token_holders>=1500"
    "&&pool_created_at<=1795397647775"
    "&&tvl>=30000"
    "&&fee_tvl_ratio>=1"
    "&&fee_pct>=0.5"
    "&&active_tvl>=10000"
)


def _row(pool, symbol, *, fee=2.0, tvl=50_000.0, active_tvl=20_000.0, holders=2_000,
         mcap=500_000.0, vol=2.0, fa=10.0, net=20_000.0, ftvl=10.0,
         volume=720_000.0, swaps=500.0, traders=200.0, mint=None, open_pos=50, active=40):
    """Baris listing 24H tiruan. ``fa`` = fee_active_tvl_ratio (%), ``vol`` = volatility (%),
    ``net`` = net_deposits (USD)."""
    mint = mint or ("M" + pool[:8].ljust(43, "x"))
    return {"pool_address": pool, "name": f"{symbol}-SOL", "pool_type": "dlmm",
            "token_x": {"address": mint, "symbol": symbol, "name": symbol,
                        "market_cap": mcap, "created_at": OLD_TOKEN_MS},
            "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
            "fee_pct": fee, "tvl": tvl, "active_tvl": active_tvl,
            "pool_created_at": OLD_POOL_MS,
            "volume_tvl_ratio": (volume / tvl * 100) if tvl else None,
            "base_token_holders": holders, "open_positions": open_pos,
            "active_positions": active, "volatility": vol, "fee_active_tvl_ratio": fa,
            "net_deposits": net,
            "volume": volume, "fee": volume * fee / 100.0, "avg_volume": volume / 720.0,
            "swap_count": swaps, "unique_traders": traders,
            "fee_tvl_ratio": ftvl}


def _fp(pool, fa, vol, *, net=20_000.0, symbol="FP", mint=None):
    """Baris yang lolos FEE PRINTER bila ``fa`` ≥ 2 × ``vol``, 0,01 ≤ vol ≤ 3, dan net ≥ 10.000."""
    return _row(pool, symbol, fa=fa, vol=vol, net=net, mint=mint)


def _scan(rows):
    return pf.scan_pools(listing=(rows, [], False))


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
HIGH_12H = _row("H" * 44, "HIGHX", fa=12.0, vol=5.5, volume=720.0 * 800, ftvl=16.5)  # volatility 5,5 %, fee/TVL 3× (band 1–3 ×)
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


def _summary_entries(rows_12h):
    """Hasil ``summary_rows`` dari listing 12H tiruan (tanpa jaringan)."""
    return pf.summary_rows(pf.scan_pools(listing=(rows_12h, [], False)))


def _slow_pool(row):
    """Baris yang masuk SLOW FEE PRINTER: fee/TVL 10 % = 1 × volatility 10 %."""
    row["fee_tvl_ratio"] = 10.0
    row["volatility"] = 10.0
    return row


def _slow_row(symbol="SLW"):
    """Pool di band SLOW FEE PRINTER, untuk RINGKASAN."""
    return _fp("S" * 44, fee_tvl=10.0, vol=10.0, symbol=symbol)


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


    def test_fmt_ratio_pct(self):
        self.assertEqual(pf.fmt_ratio_pct(0.04), "4,00%")
        self.assertEqual(pf.fmt_ratio_pct(1500.586360225028 / 90546.53933826268), "1,66%")
        self.assertEqual(pf.fmt_ratio_pct(None), "—")

    def test_fmt_usd2_dan_fmt_int(self):
        self.assertEqual(pf.fmt_usd2(57.08), "$57,08")
        self.assertEqual(pf.fmt_usd2(1234.5), "$1,23K")
        self.assertEqual(pf.fmt_usd2(None), "—")
        self.assertEqual(pf.fmt_int(13633), "13,6K")
        self.assertEqual(pf.fmt_int(None), "—")





class FeePrinterRuleTest(unittest.TestCase):
    """Syarat FEE PRINTER (permintaan user, 2026-11-24)."""

    def _ok(self, **kw):
        return pf.fee_printer_ok(pf.evaluate_pool(_fp("F" * 44, **kw)))

    def test_volatility_3_persen_lolos(self):
        self.assertTrue(self._ok(fa=6.0, vol=3.0))

    def test_volatility_di_atas_3_persen_tidak_lolos(self):
        self.assertFalse(self._ok(fa=20.0, vol=3.01))

    def test_volatility_0_01_persen_masih_terukur(self):
        self.assertTrue(self._ok(fa=0.02, vol=0.01))

    def test_volatility_di_bawah_0_01_persen_tidak_terukur(self):
        self.assertFalse(self._ok(fa=1.0, vol=0.005))

    def test_volatility_nol_tidak_lolos(self):
        self.assertFalse(self._ok(fa=5.0, vol=0.0))

    def test_fee_active_tepat_2x_volatility_lolos(self):
        self.assertTrue(self._ok(fa=4.0, vol=2.0))

    def test_fee_active_di_bawah_2x_volatility_tidak_lolos(self):
        self.assertFalse(self._ok(fa=3.99, vol=2.0))

    def test_net_deposit_tepat_10000_lolos(self):
        self.assertTrue(self._ok(fa=8.0, vol=2.0, net=10_000.0))

    def test_net_deposit_di_bawah_10000_tidak_lolos(self):
        self.assertFalse(self._ok(fa=8.0, vol=2.0, net=9_999.99))

    def test_net_deposit_negatif_tidak_lolos(self):
        self.assertFalse(self._ok(fa=8.0, vol=2.0, net=-7_708.0))

    def test_tanpa_net_deposit_tidak_lolos(self):
        self.assertFalse(self._ok(fa=8.0, vol=2.0, net=None))

    def test_tanpa_volatility_atau_fee_active_tidak_lolos(self):
        self.assertFalse(self._ok(fa=8.0, vol=None))
        self.assertFalse(self._ok(fa=None, vol=2.0))

    def test_pool_lolos_filter_tapi_keamanan_diblokir_tidak_masuk(self):
        bad = _fp("K" * 44, fa=8.0, vol=2.0, mint="K" * 44)
        bad["token_x"]["has_mint_authority"] = True
        result = _scan([bad])
        self.assertEqual(pf.fee_printer_rows(result["passing"]), [])
        self.assertEqual(pf.summary_rows(result), [])

    def test_fee_printer_tidak_tergantung_avg_volume(self):
        """Avg volume dan TVL tidak menentukan lolos (filter baru hanya tiga syarat)."""
        row = _fp("V" * 44, fa=8.0, vol=2.0, net=10_000.0)
        row["avg_volume"] = 0.0
        self.assertTrue(pf.fee_printer_ok(pf.evaluate_pool(row)))


class FeePrinterOrderTest(unittest.TestCase):
    def test_urut_rasio_terbesar_dulu(self):
        # fee/active TVL ÷ volatility: A = 2, B = 9, C = 4
        rows = [_fp("A" * 44, fa=4.0, vol=2.0, symbol="A"),
                _fp("B" * 44, fa=9.0, vol=1.0, symbol="B"),
                _fp("C" * 44, fa=12.0, vol=3.0, symbol="C")]
        result = _scan(rows)
        ordered = [r["symbol"] for r in pf.fee_printer_rows(result["passing"])]
        self.assertEqual(ordered, ["B", "C", "A"])

    def test_seri_ikut_urutan_listing(self):
        rows = [_fp("X" * 44, fa=4.0, vol=2.0, symbol="XX"),   # 2
                _fp("Y" * 44, fa=4.0, vol=2.0, symbol="YY")]   # 2
        result = _scan(rows)
        ordered = [r["symbol"] for r in pf.fee_printer_rows(result["passing"])]
        self.assertEqual(ordered, ["XX", "YY"])

    def test_rasio_dihitung_fee_active_bagi_volatility(self):
        row = pf.evaluate_pool(_fp("P" * 44, fa=8.0, vol=2.5))
        self.assertAlmostEqual(pf.fee_active_per_volatility(row), 3.2)
        self.assertIsNone(pf.fee_active_per_volatility({"fee_active_tvl": 8.0, "volatility": 0.0}))

    def test_summary_hanya_pool_fee_printer_dengan_label(self):
        ok = _fp("S" * 44, fa=8.0, vol=2.0, symbol="OKK")
        low_fee = _fp("L" * 44, fa=3.0, vol=2.0, symbol="LOW")
        result = _scan([low_fee, ok])
        entries = pf.summary_rows(result)
        self.assertEqual([(row["symbol"], label) for row, label in entries],
                         [("OKK", "FEE PRINTER")])

    def test_aturan_lama_sudah_dihapus(self):
        for name in ("LISTING_4H", "LISTING_12H", "band_12h_ok", "band_4h_ok", "fee_printer_split",
                     "sort_key_slow", "fee_volatility_ratio", "FLOW_BAND_LOW_MULT",
                     "FLOW_BAND_HIGH_MULT", "FLOW_SERVER_FILTER", "FLOW_CONFIRM_TIMEFRAME",
                     "FLOW_MIN_FEE_TVL_12H", "FLOW_FEE_PRINTER_MULT", "SUMMARY_LABEL_SLOW"):
            self.assertFalse(hasattr(pf, name), name)


class ServerFilterTest(unittest.TestCase):
    def test_filter_server_sama_persis_curl_user(self):
        self.assertEqual(pf.flow_server_filter(1795484047775), CURL_USER_FILTER)

    def test_batas_waktu_mengikuti_waktu_scan(self):
        now = 1_800_000_000_000
        text = pf.flow_server_filter(now)
        self.assertIn(f"base_token_created_at<={now}", text)
        self.assertIn(f"pool_created_at<={now - 86_400_000}", text)
        self.assertNotIn("1795484047775", text)  # nilai tetap dari curl tidak dipakai di scan

    def test_fetch_listing_mengirim_24h_top_tanpa_sort(self):
        captured = []

        def fake_get(params, **kwargs):
            captured.append(dict(params))
            return {"data": [], "has_more": False}

        with mock.patch.object(pf, "_get_payload", side_effect=fake_get):
            rows, errors, truncated = pf.fetch_listing()
        self.assertEqual((rows, errors, truncated), ([], [], False))
        params = captured[0]
        self.assertEqual(params["timeframe"], "24h")
        self.assertEqual(params["category"], "top")
        self.assertEqual(params["page_size"], 50)
        self.assertNotIn("sort_by", params)
        self.assertNotIn("after_key", params)
        self.assertNotIn("page", params)
        self.assertTrue(params["filter_by"].startswith(
            "base_token_has_high_supply_concentration=false"))
        self.assertIn("active_tvl>=10000", params["filter_by"])


class ScanTest(unittest.TestCase):
    def test_pool_duplikat_dihitung_sekali(self):
        row = _fp("D" * 44, fa=8.0, vol=2.0)
        result = _scan([row, dict(row)])
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(len(result["passing"]), 1)

    def test_truncated_dan_error_ikut_dilaporkan(self):
        result = pf.scan_pools(listing=([_fp("T" * 44, fa=8.0, vol=2.0)], ["gagal"], True))
        self.assertTrue(result["truncated"])
        self.assertEqual(result["listing_errors"], 1)

    def test_scan_tidak_menulis_berkas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool_flow_state.json"
            _scan([_fp("W" * 44, fa=8.0, vol=2.0)])
            self.assertFalse(path.exists())


class AlertTest(unittest.TestCase):
    def test_ringkasan_memuat_label_rumus_dan_tautan(self):
        row = pf.evaluate_pool(_fp("A" * 44, fa=8.0, vol=2.0, net=25_000.0, symbol="ALP"))
        text = pf.summary_alert_text(1, [(row, "FEE PRINTER")], {})
        self.assertIn("RINGKASAN Scan ALL (24H)", text)
        self.assertIn("[FEE PRINTER]", text)
        self.assertIn("fee/active TVL 8,00%", text)
        self.assertIn("volatility 2,00%", text)
        self.assertIn("net $25K", text)
        self.assertIn("fee/active ÷ volatility 4,00", text)
        self.assertIn("🆕 baru", text)
        self.assertNotIn("12H", text)

    def test_alert_memberi_nomor_dan_tag_sudah_pernah(self):
        state = pf.empty_state()
        entries = [(pf.evaluate_pool(_fp("A" * 44, fa=8.0, vol=2.0)), "FEE PRINTER")]
        text1, _ = pf.apply_summary_alert(state, entries)
        self.assertIn("<b>alert #1</b>", text1)
        text2, _ = pf.apply_summary_alert(state, entries)
        self.assertIn("<b>alert #2</b>", text2)
        self.assertIn("sudah pernah · alert #1", text2)
        self.assertEqual(state["best_alert"]["next_no"], 3)

    def test_tanpa_pool_tidak_ada_alert(self):
        state = pf.empty_state()
        self.assertEqual(pf.apply_summary_alert(state, []), (None, None))
        self.assertEqual(state["alerts"], [])

    def test_heartbeat_menyebut_jumlah_dan_tanpa_fee_printer(self):
        result = _scan([_fp("H" * 44, fa=1.0, vol=2.0)])
        text = pf.heartbeat_text(result, now="2026-11-24T02:00:00Z")
        self.assertIn("Pool Flow cron jalan", text)
        self.assertIn("listing 24H: 1 baris", text)
        self.assertIn("FEE PRINTER: 0 pool", text)

    def test_heartbeat_scan_gagal(self):
        text = pf.heartbeat_text(error="timeout")
        self.assertIn("❌ Scan gagal: timeout", text)


class TelegramCopyTest(unittest.TestCase):
    def test_satu_tombol_copy_per_pool_dengan_ca_lengkap(self):
        rows = [pf.evaluate_pool(_fp("A" * 44, fa=8.0, vol=2.0, mint="MINTA" + "a" * 39)),
                pf.evaluate_pool(_fp("B" * 44, fa=8.0, vol=2.0, mint="MINTB" + "b" * 39))]
        markup = pf.alert_copy_markup(rows)
        buttons = [btn for row in markup["inline_keyboard"] for btn in row]
        self.assertEqual([b["copy_text"]["text"] for b in buttons],
                         [r["mint"] for r in rows])

    def test_pesan_terpecah_hanya_bagian_terakhir_punya_tombol(self):
        markup = {"inline_keyboard": [[{"text": "x", "copy_text": {"text": "y"}}]]}
        sent = []

        def fake_send(chunk, reply_markup=None):
            sent.append(reply_markup)
            return True, ""

        long_text = "\n".join(["baris " + "x" * 200] * 60)
        with mock.patch.object(pf, "_send_telegram_once", side_effect=fake_send):
            ok, _ = pf.send_telegram(long_text, reply_markup=markup)
        self.assertTrue(ok)
        self.assertGreater(len(sent), 1)
        self.assertTrue(all(m is None for m in sent[:-1]))
        self.assertEqual(sent[-1], markup)

    def test_split_tiap_bagian_di_bawah_limit(self):
        parts = pf.split_for_telegram("a" * 9000)
        self.assertTrue(all(len(p) <= pf.TELEGRAM_CHUNK for p in parts))
        self.assertEqual("".join(parts), "a" * 9000)


def _alert_main():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pool_flow_alert_main", ROOT / "scripts" / "pool_flow_alert.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AlertCronTest(unittest.TestCase):
    """Cron tiap 15 menit: RINGKASAN bila ada pool, heartbeat bila tidak; state hanya tersimpan bila berhasil."""

    CREDS = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "pool_flow_state.json"
        self.alert = _alert_main()

    def tearDown(self):
        self._tmp.cleanup()

    def test_ada_pool_kirim_ringkasan(self):
        messages = self.alert.run_summary(
            pf.empty_state(),
            scan=lambda: _scan([_fp("R" * 44, fa=8.0, vol=2.0, symbol="RNG")]))
        self.assertEqual(len(messages), 1)
        self.assertIn("RINGKASAN", messages[0][0])
        self.assertIn("RNG", messages[0][0])
        self.assertIsNotNone(messages[0][1])

    def test_tanpa_pool_kirim_heartbeat(self):
        messages = self.alert.run_summary(pf.empty_state(), scan=lambda: _scan([]))
        self.assertEqual(len(messages), 1)
        self.assertIn("Pool Flow cron jalan", messages[0][0])
        self.assertNotIn("RINGKASAN", messages[0][0])
        self.assertIsNone(messages[0][1])

    def test_listing_terpotong_diberi_peringatan(self):
        messages = self.alert.run_summary(
            pf.empty_state(),
            scan=lambda: pf.scan_pools(listing=([_fp("Z" * 44, fa=8.0, vol=2.0)], [], True)))
        self.assertIn("listing belum lengkap", messages[0][0])

    def _main(self, rows, send=(True, "")):
        with mock.patch.dict("os.environ", self.CREDS), \
                mock.patch.object(pf, "fetch_listing", side_effect=lambda *a, **k: (rows, [], False)), \
                mock.patch.object(pf, "send_telegram", return_value=send) as sender:
            code = self.alert.main(["--state", str(self.path)])
        return code, sender

    def test_main_ada_pool_simpan_state_dan_tandai_berubah(self):
        rows = [_fp("M" * 44, fa=8.0, vol=2.0, symbol="MAIN")]
        code, sender = self._main(rows)
        self.assertEqual(code, 0)
        self.assertTrue(self.path.exists())
        self.assertEqual(sender.call_count, 1)
        self.assertIn("RINGKASAN", sender.call_args[0][0])

    def test_main_tanpa_pool_tidak_menulis_state(self):
        code, sender = self._main([])
        self.assertEqual(code, 0)
        self.assertFalse(self.path.exists())
        self.assertIn("Pool Flow cron jalan", sender.call_args[0][0])

    def test_main_kirim_gagal_state_tidak_disimpan(self):
        code, _sender = self._main([_fp("G" * 44, fa=8.0, vol=2.0)], send=(False, "jaringan"))
        self.assertEqual(code, 1)
        self.assertFalse(self.path.exists())

    def test_main_tanpa_kredensial_exit_1(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            code = self.alert.main(["--state", str(self.path)])
        self.assertEqual(code, 1)
        self.assertFalse(self.path.exists())


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



if __name__ == "__main__":
    unittest.main()


class FeeVolumeTest(unittest.TestCase):
    def test_fee_volume_dihitung_fee_dibagi_volume(self):
        # _row: fee = volume × fee_pct ÷ 100 → fee/volume = fee_pct
        row = pf.evaluate_pool(_fp("V" * 44, fa=8.0, vol=2.0))
        self.assertAlmostEqual(pf.fee_volume_pct(row), 2.0)

    def test_fee_volume_kosong_bila_volume_nol_atau_tanpa_fee(self):
        row = pf.evaluate_pool(_fp("W" * 44, fa=8.0, vol=2.0))
        row["activity"]["volume"] = 0.0
        self.assertIsNone(pf.fee_volume_pct(row))
        row["activity"]["volume"] = 1000.0
        row["activity"]["fee"] = None
        self.assertIsNone(pf.fee_volume_pct(row))


class FeeVolumeExcessRuleTest(unittest.TestCase):
    """Syarat selisih fee/volume − tarif dasar ≤ 0,25 poin (permintaan user, 2026-11-25)."""

    def _row_with_excess(self, excess, pool="E" * 44):
        # fee_pct (tarif dasar) = 2,0; fee/volume = 2,0 + excess (field mentah, sebelum evaluate_pool)
        row = _fp(pool, fa=8.0, vol=2.0)
        row["fee"] = row["volume"] * (2.0 + excess) / 100.0
        return pf.evaluate_pool(row)

    def test_selisih_di_bawah_ambang_lolos(self):
        self.assertTrue(pf.fee_printer_ok(self._row_with_excess(0.10)))

    def test_selisih_tepat_ambang_lolos_inklusif(self):
        self.assertTrue(pf.fee_printer_ok(self._row_with_excess(0.25)))

    def test_selisih_di_atas_ambang_gugur(self):
        self.assertFalse(pf.fee_printer_ok(self._row_with_excess(0.26)))

    def test_tanpa_data_fee_volume_gugur(self):
        raw = _fp("F" * 44, fa=8.0, vol=2.0)
        raw["volume"] = 0.0
        self.assertFalse(pf.fee_printer_ok(pf.evaluate_pool(raw)))

    def test_selisih_dihitung_fee_volume_dikurangi_tarif_dasar(self):
        row = self._row_with_excess(0.40)
        self.assertAlmostEqual(pf.fee_volume_excess(row), 0.40, places=6)


class ExcessRowsTest(unittest.TestCase):
    """RINGKASAN di halaman memuat pool SELISIH BESAR (fee/volume − tarif > 0,25) tanpa filter lain
    (permintaan user, 2026-11-25). Alert Telegram tetap FEE PRINTER saja."""

    def _ex(self, pool, symbol, excess, *, vol=2.0, fa=10.0, net=20_000.0, top_holders=None):
        row = _row(pool, symbol, fee=2.0, vol=vol, fa=fa, net=net)
        row["fee"] = row["volume"] * (2.0 + excess) / 100.0
        if top_holders is not None:
            row["token_x"]["top_holders_pct"] = top_holders
        return row

    def _result(self):
        rows = [
            self._ex("A" * 44, "JIMMY", 0.85, vol=3.67, fa=15.0, net=366_000.0),  # gagal volatility
            self._ex("B" * 44, "MIHAO", 0.40, net=-31_000.0),                      # net negatif
            self._ex("C" * 44, "ANSEM", 0.79, top_holders=57.8),                  # blokir keamanan
            self._ex("D" * 44, "FP", 0.10),                                        # lolos FEE PRINTER
            self._ex("E" * 44, "KECIL", 0.20),                                     # di bawah ambang
            self._ex("F" * 44, "PAS", 0.25),                                       # tepat ambang: bukan selisih besar
        ]
        return _scan(rows)

    def test_selisih_besar_urut_terbesar_dan_tanpa_filter_lain(self):
        symbols = [r["symbol"] for r in pf.excess_rows(self._result())]
        self.assertEqual(symbols, ["JIMMY", "ANSEM"])  # MIHAO (net negatif) tidak ditampilkan

    def test_ringkasan_halaman_fee_printer_dulu_lalu_selisih_besar(self):
        pairs = [(r["symbol"], label) for r, label in pf.summary_table_rows(self._result())]
        self.assertEqual(pairs, [("FP", pf.SUMMARY_LABEL),
                                 ("KECIL", pf.SUMMARY_LABEL),
                                 ("PAS", pf.SUMMARY_LABEL),
                                 ("JIMMY", pf.SUMMARY_LABEL_EXCESS),
                                 ("ANSEM", pf.SUMMARY_LABEL_EXCESS)])

    def test_alert_tetap_fee_printer_saja(self):
        pairs = [(r["symbol"], label) for r, label in pf.summary_rows(self._result())]
        self.assertEqual(pairs, [("FP", pf.SUMMARY_LABEL), ("KECIL", pf.SUMMARY_LABEL), ("PAS", pf.SUMMARY_LABEL)])

    def test_net_negatif_tidak_ditampilkan_net_kosong_tetap(self):
        neg = self._ex("I" * 44, "NEG", 0.90, net=-5_000.0)
        kosong = self._ex("J" * 44, "KOSONG", 0.70)
        kosong["net_deposits"] = None
        symbols = [r["symbol"] for r in pf.excess_rows(_scan([neg, kosong]))]
        self.assertEqual(symbols, ["KOSONG"])

    def test_tanpa_data_selisih_tidak_masuk(self):
        row = self._ex("G" * 44, "NOFEE", 0.5)
        row["volume"] = 0.0
        self.assertEqual(pf.excess_rows(_scan([row])), [])
