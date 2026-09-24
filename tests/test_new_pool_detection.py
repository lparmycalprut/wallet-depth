"""🆕 Deteksi POOL BARU di 🏆 Scan Best Pool (permintaan user 2026-09-24).

Syarat (semua eksklusif): umur pool < 12 jam, active TVL > 75K, fee/active
TVL > 20%, volatility < 15%, top holders < 20%. Contoh acuan user:
familiars-SOL harus muncul di hasil scan, bertanda "POOL BARU", dengan
STRATEGY "50 50 spotba, bidask".
"""
import unittest
from unittest import mock

import meteora_screener as ms
from gmgn_liquidity import STRATEGY_NEW_POOL, row_strategy

# Potongan payload API asli (response user 2026-09-24).
FETCHED_AT = 1790206791 + 2 * 3600  # 2 jam setelah pool dibuat


def _familiars_pool(**over):
    pool = {
        "pool_address": "ET9QEc18XnEXNyz8ZuGkJfgSuDDqLDiA1U8bEpyuyLKC",
        "name": "familiars-SOL",
        "token_x": {
            "address": "2PENPmfgJfq6CG3k4byj4oWwHf8SerqakmYHMkUupump",
            "symbol": "familiars", "name": "familiars.family",
            "market_cap": 2078479.25, "price": 0.00218, "holders": 4258,
            "warnings": [], "top_holders_pct": 14.677167252514254,
        },
        "token_y": {"address": ms.SOL_MINT, "symbol": "SOL"},
        "pool_type": "dlmm", "fee_pct": 2.0,
        "pool_created_at": 1790206791000,
        "dlmm_params": {"bin_step": 100},
        "tvl": 112664.66744021911,
        "active_tvl": 112294.36385085656,
        "fee_active_tvl_ratio": 34.09200065211515,
        "volume_active_tvl_ratio": 1031.868642418687,
        "volume": 1158730.327780534, "fee": 38283.395256322576,
        "total_lps": 230.0,
        "volatility": 10.37084454997201,
    }
    pool.update(over)
    return pool


def _row(**over):
    with mock.patch.object(ms.time, "time", return_value=FETCHED_AT):
        return ms.rows_from_pools([_familiars_pool(**over)])[0]


class NewPoolDetectionTest(unittest.TestCase):
    def test_familiars_lolos_sebagai_pool_baru(self):
        row = _row()
        self.assertEqual(row["fetched_at"], FETCHED_AT)
        self.assertAlmostEqual(ms.row_pool_age_hours(row), 2.0, places=3)
        self.assertTrue(ms.row_new_pool(row))
        # Tanpa jalur pool baru ia gugur (F/V 3,3× & volatility > 10%).
        self.assertEqual(ms.row_best_gaps(row), [])
        self.assertFalse(ms.row_best_dropped(row))
        kept, hidden, _ = ms.filter_best_rows([row])
        self.assertEqual(len(kept), 1)
        self.assertEqual(hidden, 0)

    def test_strategy_pool_baru(self):
        info = row_strategy(_row())
        self.assertEqual(info["text"], "50 50 spotba, bidask")
        self.assertEqual(STRATEGY_NEW_POOL, "50 50 spotba, bidask")
        self.assertTrue(info.get("new_pool"))

    def test_batas_eksklusif_tiap_syarat(self):
        cases = {
            "umur": {"pool_created_at": (FETCHED_AT - 12 * 3600) * 1000},
            "active TVL": {"active_tvl": 75_000.0},
            "fee/active TVL": {"fee_active_tvl_ratio": 20.0},
            "volatility": {"volatility": 15.0},
        }
        for gap, over in cases.items():
            with self.subTest(gap=gap):
                row = _row(**over)
                self.assertIn(gap, ms.row_new_pool_gaps(row))
                self.assertFalse(ms.row_new_pool(row))
        pool = _familiars_pool()
        pool["token_x"] = dict(pool["token_x"], top_holders_pct=20.0)
        with mock.patch.object(ms.time, "time", return_value=FETCHED_AT):
            row = ms.rows_from_pools([pool])[0]
        self.assertIn("top holders", ms.row_new_pool_gaps(row))

    def test_volatility_nol_bukan_pool_baru(self):
        row = _row(volatility=0.0)
        self.assertFalse(ms.row_new_pool(row))
        self.assertTrue(ms.row_best_dropped(row))

    def test_pool_lama_tetap_aturan_reguler(self):
        # Umur 13 jam → jalur reguler: F/V 3,3× + volatility 10,37% → dibuang.
        row = _row(pool_created_at=(FETCHED_AT - 13 * 3600) * 1000)
        self.assertFalse(ms.row_new_pool(row))
        self.assertTrue(ms.row_best_gaps(row))
        self.assertTrue(ms.row_best_dropped(row))

    def test_render_ulang_tidak_menua(self):
        # Umur dihitung terhadap fetched_at, bukan jam render.
        row = _row()
        with mock.patch.object(ms.time, "time",
                               return_value=FETCHED_AT + 48 * 3600):
            self.assertTrue(ms.row_new_pool(row))

    def test_scan_best_lane_menampilkan_familiars(self):
        pools = [_familiars_pool()]
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=lambda rows, **kw: rows), \
                mock.patch.object(ms.time, "time", return_value=FETCHED_AT):
            result = ms.scan_best_lane(rugcheck=False, gmgn=False, tax=False,
                                       max_wallets=10)
        self.assertEqual([r["symbol"] for r in result["rows"]], ["FAMILIARS"])
        self.assertEqual(result["hidden_rows"], [])


if __name__ == "__main__":
    unittest.main()
