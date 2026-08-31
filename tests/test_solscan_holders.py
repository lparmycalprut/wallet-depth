# -*- coding: utf-8 -*-
"""Coverage untuk holder Solscan + Wallet Depth by Threshold."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import solscan_holders as sh

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures")


def _fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def _snapshot(*, api="pro", values=()):
    """Snapshot holder sintetis: values = [(address, usd_value, is_wallet)]."""
    holders = []
    for index, (addr, value, is_wallet) in enumerate(values):
        holders.append({
            "address": addr, "usd_value": float(value), "balance": 0.0,
            "amount_pct": 0.0, "is_wallet": is_wallet, "tags": [],
            "maker_token_tags": [],
        })
    return {"holders": holders, "source": "solscan", "api": api}


class NormalizeProTest(unittest.TestCase):
    def setUp(self):
        sh._CACHE.clear()

    def test_pro_rows_normalized_and_pool_marked(self):
        """Pro API: value & percentage dari Solscan; pool dikecualikan."""
        payload = _fixture("solscan_pro_holders.json")

        def fake_get(url, params, headers=None, timeout=20):
            self.assertIn("pro-api.solscan.io", url)
            self.assertEqual(params["address"], "MINT")
            self.assertEqual(headers.get("token"), "KEY123")
            return payload

        with mock.patch("solscan_holders._http_get", side_effect=fake_get):
            snapshot = sh.fetch_solscan_holders(
                "MINT", api_key="KEY123", max_wallets=3000,
                pool_addresses=["POOLRAY"], market_cap=200_000)

        self.assertEqual(snapshot["source"], "solscan")
        self.assertEqual(snapshot["api"], "pro")
        self.assertEqual(snapshot["total_known"], 6)
        self.assertEqual(len(snapshot["holders"]), 6)
        by_addr = {h["address"]: h for h in snapshot["holders"]}

        # balance = amount / 10^decimals; value USD dari Solscan
        self.assertAlmostEqual(by_addr["WAL1"]["balance"], 10_000.0)
        self.assertAlmostEqual(by_addr["WAL1"]["usd_value"], 1800.0)
        # percentage skala persen (45.0 → 0.45 fraksi)
        self.assertAlmostEqual(by_addr["POOLRAY"]["amount_pct"], 0.45)
        self.assertAlmostEqual(by_addr["WAL1"]["amount_pct"], 0.009)
        # LP/pool ditandai bukan wallet
        self.assertFalse(by_addr["POOLRAY"]["is_wallet"])
        self.assertTrue(by_addr["WAL1"]["is_wallet"])

    def test_no_key_uses_public_api(self):
        """Tanpa api_key → public API dipanggil, bukan pro."""
        payload = _fixture("solscan_public_holders.json")

        def fake_get(url, params, headers=None, timeout=20):
            self.assertIn("public-api.solscan.io", url)
            self.assertEqual(params.get("tokenAddress"), "MINT")
            return payload

        with mock.patch("solscan_holders._http_get", side_effect=fake_get):
            snapshot = sh.fetch_solscan_holders(
                "MINT", price_usd=0.0001, market_cap=100_000,
                max_wallets=3000)

        self.assertEqual(snapshot["api"], "public")
        self.assertEqual(len(snapshot["holders"]), 3)
        by_addr = {h["address"]: h for h in snapshot["holders"]}
        # USD = balance × price (20_000 × 0.0001 = 2.0)
        self.assertAlmostEqual(by_addr["WALA"]["usd_value"], 2.0)
        self.assertAlmostEqual(by_addr["WALB"]["usd_value"], 0.005)
        # amount_pct = value / marketcap
        self.assertAlmostEqual(by_addr["WALA"]["amount_pct"], 2e-5)

    def test_pro_fails_then_public_fallback(self):
        """Pro error → otomatis lanjut public API."""
        calls = []

        def fake_get(url, params, headers=None, timeout=20):
            calls.append(url)
            if "pro-api" in url:
                raise RuntimeError("pro down")
            return _fixture("solscan_public_holders.json")

        with mock.patch("solscan_holders._http_get", side_effect=fake_get):
            snapshot = sh.fetch_solscan_holders(
                "MINT", api_key="KEY123", price_usd=0.0001,
                max_wallets=3000)

        self.assertEqual(snapshot["api"], "public")
        self.assertEqual(len(snapshot["holders"]), 3)
        self.assertTrue(any("pro-api" in c for c in calls))

    def test_all_fail_returns_empty_snapshot(self):
        """Semua endpoint gagal → snapshot kosong + error tercatat."""
        with mock.patch("solscan_holders._http_get",
                        side_effect=RuntimeError("network")):
            snapshot = sh.fetch_solscan_holders(
                "MINT", api_key="KEY123", max_wallets=3000)
        self.assertEqual(snapshot["holders"], [])
        self.assertEqual(snapshot["source"], "solscan")
        self.assertIn("pro", snapshot["error"])
        self.assertIn("public", snapshot["error"])


class WalletDepthTest(unittest.TestCase):
    def test_buckets_include_pools_tiers_exclude(self):
        """Bucket = semua akun; tier = wallet murni (LP/pool keluar)."""
        holders = [
            {"address": "POOL", "usd_value": 90000.0, "is_wallet": False},
            {"address": "W1", "usd_value": 1800.0, "is_wallet": True},
            {"address": "W2", "usd_value": 900.0, "is_wallet": True},
            {"address": "W3", "usd_value": 180.0, "is_wallet": True},
            {"address": "W4", "usd_value": 9.0, "is_wallet": True},
            {"address": "W5", "usd_value": 0.18, "is_wallet": True},
        ]
        depth = sh.wallet_depth(holders, market_cap=200_000,
                                pool_addresses=["POOL"])

        by_label = {b["label"]: b for b in depth["buckets"]}
        self.assertEqual(by_label[">$0-$10"]["count"], 2)
        self.assertEqual(by_label["$10-$100"]["count"], 0)
        self.assertEqual(by_label["$100-$1k"]["count"], 2)  # W2, W3
        self.assertEqual(by_label["$1k-$10k"]["count"], 1)  # W1
        self.assertEqual(by_label["$10k-$100k"]["count"], 1)  # POOL
        self.assertEqual(by_label["$100k-$500k"]["count"], 0)
        self.assertEqual(by_label[">$500k"]["count"], 0)
        # 90.000 / 200.000 = 45%
        self.assertAlmostEqual(by_label["$10k-$100k"]["pct_mc"], 45.0)

        by_tier = {t["tier"]: t for t in depth["tiers"]}
        self.assertEqual(by_tier["Shrimp"]["count"], 2)   # W4, W5
        self.assertEqual(by_tier["Crab"]["count"], 2)     # W2, W3
        self.assertEqual(by_tier["Fish"]["count"], 1)     # W1
        self.assertEqual(by_tier["Dolphin"]["count"], 0)
        self.assertEqual(by_tier["Shark"]["count"], 0)    # POOL tidak masuk
        self.assertAlmostEqual(by_tier["Shrimp"]["pct_mc"],
                               9.18 / 200_000 * 100, places=4)
        self.assertEqual(depth["holders_all"], 6)
        self.assertEqual(depth["holders_wallet"], 5)
        self.assertEqual(depth["pool_excluded"], 1)

    def test_missing_marketcap_gives_none_pct(self):
        depth = sh.wallet_depth(
            [{"address": "A", "usd_value": 5.0, "is_wallet": True}],
            market_cap=0)
        self.assertIsNone(depth["buckets"][0]["pct_mc"])

    def test_zero_value_holders_excluded(self):
        depth = sh.wallet_depth(
            [{"address": "A", "usd_value": 0.0, "is_wallet": True},
             {"address": "B", "usd_value": -1.0, "is_wallet": True}],
            market_cap=1000)
        self.assertEqual(depth["holders_all"], 0)


class HolderSourceResolveTest(unittest.TestCase):
    def test_resolve_priority(self):
        import silent_accumulation as sa
        with mock.patch("core.get_holder_source", return_value="solscan"):
            self.assertEqual(sa.resolve_holder_source(None), "solscan")
        with mock.patch("core.get_holder_source", return_value="gmgn"):
            self.assertEqual(sa.resolve_holder_source("auto"), "auto")
        self.assertEqual(sa.resolve_holder_source("gmgn"), "gmgn")
        self.assertEqual(sa.resolve_holder_source("bogus"), "auto")

    def test_fetch_snapshot_solscan_first_then_gmgn_fallback(self):
        import silent_accumulation as sa

        with mock.patch("solscan_holders.fetch_solscan_holders") as mock_sh:
            with mock.patch("solscan_holders.wallet_depth",
                            return_value={"buckets": []}) as mock_depth:
                mock_sh.return_value = {"holders": [{"address": "X",
                                                     "usd_value": 1.0}],
                                        "source": "solscan", "api": "public"}
                with mock.patch("silent_accumulation.fetch_holders") as mock_fh:
                    snap, depth = sa._fetch_holders_snapshot(
                        "MINT", "auto", max_wallets=10, timeout=20,
                        price_usd=0.1, market_cap=100,
                        market={"pair_addresses": ["POOL"]})
                    self.assertEqual(snap["source"], "solscan")
                    self.assertIsNotNone(depth)
                    mock_fh.assert_not_called()
                    mock_sh.assert_called_once()
                    # pool_addresses diteruskan
                    self.assertIn("POOL", mock_sh.call_args.kwargs[
                        "pool_addresses"])
                    mock_depth.assert_called_once()

        with mock.patch("solscan_holders.fetch_solscan_holders") as mock_sh:
            mock_sh.return_value = {"holders": [], "source": "solscan",
                                    "api": "public", "error": "kosong"}
            with mock.patch("silent_accumulation.fetch_holders") as mock_fh:
                mock_fh.return_value = {"holders": [{"address": "G"}],
                                        "source": "gmgn"}
                snap, depth = sa._fetch_holders_snapshot(
                    "MINT", "auto", max_wallets=10, timeout=20,
                    price_usd=0.1, market_cap=100, market={})
                self.assertEqual(snap["source"], "gmgn")
                self.assertIsNone(depth)

        with mock.patch("silent_accumulation.fetch_holders") as mock_fh:
            mock_fh.return_value = {"holders": [], "source": "gmgn"}
            snap, depth = sa._fetch_holders_snapshot(
                "MINT", "gmgn", max_wallets=10, timeout=20,
                price_usd=0.0, market_cap=0, market={})
            self.assertEqual(snap["source"], "gmgn")
            self.assertIsNone(depth)

    def test_analyze_token_attaches_depth_for_solscan(self):
        import silent_accumulation as sa
        snapshot = _snapshot(api="pro",
                             values=[("W1", 500.0, True),
                                     ("W2", 5.0, True)])
        with mock.patch("silent_accumulation.get_market",
                        return_value={"symbol": "TST",
                                      "price_usd": 0.01,
                                      "marketcap": 100_000}):
            with mock.patch("silent_accumulation._fetch_holders_snapshot",
                            return_value=(snapshot, {
                                "buckets": [], "tiers": []})):
                with mock.patch("silent_accumulation.fetch_12h_flow",
                                return_value={"source": "gmgn"}):
                    analysis = sa.analyze_token(
                        "MINT", "TST", holder_source="solscan")
        self.assertEqual(analysis["holders"]["source"], "solscan")
        self.assertEqual(analysis["holders"]["api"], "pro")
        self.assertIn("depth", analysis["holders"])
        self.assertAlmostEqual(analysis["holders"]["real_count"], 1)

    def test_analyze_token_gmgn_source_has_no_depth(self):
        import silent_accumulation as sa
        snapshot = {"holders": [{"address": "W1", "usd_value": 50.0,
                                 "is_wallet": True}],
                    "source": "gmgn", "pages": 1}
        with mock.patch("silent_accumulation._fetch_holders_snapshot",
                        return_value=(snapshot, None)):
            with mock.patch("silent_accumulation.fetch_12h_flow",
                            return_value={"source": "gmgn"}):
                analysis = sa.analyze_token(
                    "MINT", "TST", market_cap=1000,
                    holder_source="gmgn")
        self.assertEqual(analysis["holders"]["source"], "gmgn")
        self.assertNotIn("depth", analysis["holders"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
