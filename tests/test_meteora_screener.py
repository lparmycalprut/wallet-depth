"""Coverage listing Meteora 24h/1h + filter dust > 2% MC."""
from __future__ import annotations

import unittest
from unittest import mock

import meteora_screener as ms


SOL = ms.SOL_MINT


def _token(addr, symbol="TOK", mc=100_000):
    return {"address": addr, "symbol": symbol, "name": symbol,
            "market_cap": mc, "fdv": mc, "price": 0.01, "holders": 10}


def _pool(addr, mint, name="TOK-SOL"):
    return {
        "pool_address": addr, "name": name, "pool_type": "dlmm",
        "token_x": _token(mint, name.split("-")[0]),
        "token_y": _token(SOL, "SOL", mc=1e9),
        "tvl": 2000, "active_tvl": 1500, "fee_active_tvl_ratio": 300,
        "volume": 50_000, "fee_pct": 1.0,
    }


class BaseTokenTest(unittest.TestCase):
    def test_picks_non_quote_side(self):
        pool = _pool("P1", "MintAAA")
        self.assertEqual(ms.base_token(pool)["address"], "MintAAA")

    def test_falls_back_when_both_quote(self):
        pool = {
            "token_x": _token(SOL, "SOL"),
            "token_y": _token(ms.USDC_MINT, "USDC"),
        }
        self.assertEqual(ms.base_token(pool)["address"], SOL)


class MergePoolsTest(unittest.TestCase):
    def test_24h_still_shown_when_also_in_1h(self):
        p24 = [_pool("P1", "M1"), _pool("P2", "M2")]
        p1h = [_pool("P1", "M1"), _pool("P3", "M3")]
        rows = ms.merge_pools(p24, p1h)
        by = {r["pool_address"]: r for r in rows}
        self.assertEqual(set(by), {"P1", "P2", "P3"})
        self.assertTrue(by["P1"]["in_24h"] and by["P1"]["in_1h"])
        self.assertTrue(by["P2"]["in_24h"] and not by["P2"]["in_1h"])
        self.assertTrue(by["P3"]["in_1h"] and not by["P3"]["in_24h"])
        self.assertEqual(rows[0]["pool_address"], "P1")

    def test_filter_query_matches_ui(self):
        self.assertEqual(
            ms.filter_by(fee_ratio_min=250),
            "pool_type=dlmm&&active_tvl>=1000&&fee_active_tvl_ratio>=250")
        self.assertEqual(
            ms.filter_by(fee_ratio_min=1),
            "pool_type=dlmm&&active_tvl>=1000&&fee_active_tvl_ratio>=1")


class HideDustTest(unittest.TestCase):
    def test_hides_over_two_percent_keeps_rest(self):
        rows = [
            {"ca": "A", "dust_pct_mc": 2.4,
             "analysis": {"holders": {"dust_pct_mc": 2.4}}},
            {"ca": "B", "dust_pct_mc": 1.5,
             "analysis": {"holders": {"dust_pct_mc": 1.5}}},
            {"ca": "C", "dust_pct_mc": None, "analysis": None},
        ]
        kept, hidden = ms.hide_dust_limit(rows)
        self.assertEqual(hidden, 1)
        self.assertEqual([r["ca"] for r in kept], ["B", "C"])


class FetchListingTest(unittest.TestCase):
    def test_fetch_listing_merges_both_timeframes(self):
        with mock.patch.object(ms, "fetch_pools", side_effect=[
            [_pool("P1", "M1")],
            [_pool("P1", "M1")],
        ]):
            rows, error = ms.fetch_listing()
        self.assertEqual(error, "")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["in_24h"] and rows[0]["in_1h"])


if __name__ == "__main__":
    unittest.main()
