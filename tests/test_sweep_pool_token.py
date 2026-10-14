# -*- coding: utf-8 -*-
"""Token di sisi pool: jumlah, nilai USD, dan Token/MC — offline."""
from __future__ import annotations

import unittest
from unittest import mock

import sweep_data as data
import sweep_screen as screen
import sweep_ui as ui

MINT = "EFn88CiiFHhihqdr1Y11XBDxbbYarBf1ij92DsrigYwR"

# Potongan respons DexScreener RARI (pumpswap, pool terbesar).
PAIR = {
    "chainId": "solana", "dexId": "pumpswap",
    "pairAddress": "ioaDGkQUh6h5nNTmcv8k3NvAgSTiS3xMFNaN3j11KzV",
    "baseToken": {"address": MINT, "name": "No Risk No Rari", "symbol": "RARI"},
    "quoteToken": {"symbol": "RACE"},
    "priceUsd": "0.0005291",
    "volume": {"h24": 111420.23, "h1": 46714.49},
    "priceChange": {"h1": -25.03},
    "liquidity": {"usd": 80151.72, "base": 77016542, "quote": 101.1126},
    "fdv": 524721, "marketCap": 524721,
    "pairCreatedAt": 1791316357000,
}


class PoolTokenFracTest(unittest.TestCase):
    def test_rasio_token_terhadap_mc(self):
        frac = screen.pool_token_mc_frac(40748.0, 524721.0)
        self.assertAlmostEqual(frac, 40748.0 / 524721.0)
        self.assertAlmostEqual(frac, 0.0777, places=4)

    def test_tanpa_data_atau_mc_nol_none(self):
        self.assertIsNone(screen.pool_token_mc_frac(None, 524721.0))
        self.assertIsNone(screen.pool_token_mc_frac(40748.0, None))
        self.assertIsNone(screen.pool_token_mc_frac(40748.0, 0))
        self.assertIsNone(screen.pool_token_mc_frac(-1.0, 524721.0))


class DexSnapshotPoolTest(unittest.TestCase):
    def test_dex_snapshot_membaca_base_dan_menghitung_usd(self):
        payload = {"pairs": [PAIR]}
        with mock.patch.object(data, "_get_json", return_value=payload):
            snap = data.dex_snapshot(MINT, use_cache=False)
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["pool_base_amount"], 77016542.0)
        self.assertAlmostEqual(snap["pool_base_usd"], 77016542.0 * 0.0005291, places=4)
        # Sisi token ≈ separuh liquiditas dua sisi (sanity check).
        self.assertAlmostEqual(snap["pool_base_usd"] / snap["liq_usd"], 0.508, places=2)

    def test_tanpa_field_liquidity_base(self):
        pair = dict(PAIR, liquidity={"usd": 80151.72})
        with mock.patch.object(data, "_get_json", return_value={"pairs": [pair]}):
            snap = data.dex_snapshot(MINT, use_cache=False)
        self.assertIsNone(snap["pool_base_amount"])
        self.assertIsNone(snap["pool_base_usd"])


class TableColumnsTest(unittest.TestCase):
    def test_format_jumlah_token(self):
        self.assertEqual(ui._fmt_amount(77016542), "77.02M")
        self.assertEqual(ui._fmt_amount(1500), "1.5K")
        self.assertEqual(ui._fmt_amount(812), "812")
        self.assertEqual(ui._fmt_amount(None), "—")

    def test_kolom_token_pool_di_samping_liq_mc(self):
        metrics = {"symbol": "RARI", "fdv_usd": 524721.0, "liq_usd": 80151.72,
                   "pool_base_amount": 77016542.0,
                   "pool_base_usd": 77016542.0 * 0.0005291}
        row = {"mint": MINT, "ts": 1, "metrics": metrics,
               "result": {"liq_mc": 80151.72 / 524721.0, "checks": []}}
        out = ui._eligibility_rows([row])[0]
        cols = list(out.keys())
        i = cols.index("liq/MC")
        self.assertEqual(cols[i + 1:i + 4], ["Token pool", "Token pool $", "Token/MC"])
        self.assertEqual(out["Token pool"], "77.02M")
        self.assertEqual(out["Token pool $"], "$40,749")
        self.assertEqual(out["Token/MC"], "7.8%")

    def test_kolom_kosong_untuk_snapshot_lama(self):
        row = {"mint": MINT, "ts": 1, "metrics": {"symbol": "RARI"},
               "result": {"checks": []}}
        out = ui._eligibility_rows([row])[0]
        self.assertEqual((out["Token pool"], out["Token pool $"], out["Token/MC"]),
                         ("—", "—", "—"))


if __name__ == "__main__":
    unittest.main()
