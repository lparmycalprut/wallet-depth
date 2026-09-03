# -*- coding: utf-8 -*-
"""Coverage untuk wallet_depth (bucket & tier) + prioritas sumber holder.

Fetch Solscan API sudah dilepas total; sumber holder sekarang Helius
(fallback GMGN). Modul ``solscan_holders`` hanya tersisa sebagai kalkulasi
Wallet Depth by Threshold & tier.
"""
from __future__ import annotations

import unittest
from unittest import mock

import solscan_holders as sh


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

    def test_buckets_exclude_pools_when_requested(self):
        """include_pools=False → LP/pool hilang dari bucket (list holder)."""
        holders = [
            {"address": "POOL", "usd_value": 90000.0, "is_wallet": True},
            # GMGN path: pool dikenali dari is_wallet=False walau address
            # tidak ada di pool_addresses.
            {"address": "RAYDIUM-VAULT", "usd_value": 2500.0,
             "is_wallet": False},
            {"address": "W1", "usd_value": 1800.0, "is_wallet": True},
            {"address": "W2", "usd_value": 9.0, "is_wallet": True},
        ]
        depth = sh.wallet_depth(holders, market_cap=200_000,
                                pool_addresses=["POOL"],
                                include_pools=False)

        by_label = {b["label"]: b for b in depth["buckets"]}
        self.assertEqual(by_label[">$0-$10"]["count"], 1)      # W2
        self.assertEqual(by_label["$1k-$10k"]["count"], 1)    # W1
        self.assertEqual(by_label["$10k-$100k"]["count"], 0)  # POOL hilang
        # total nilai bucket = wallet murni saja (tanpa 90k + 2.5k pool)
        total_bucket_value = sum(b["value_usd"] for b in depth["buckets"])
        self.assertAlmostEqual(total_bucket_value, 1809.0)

        # metrik tetap: semua akun bernilai > $0 vs wallet murni
        self.assertEqual(depth["holders_all"], 4)
        self.assertEqual(depth["holders_wallet"], 2)
        self.assertEqual(depth["pool_excluded"], 2)
        self.assertFalse(depth["buckets_include_pools"])
        # tier tidak terpengaruh (memang selalu wallet murni)
        by_tier = {t["tier"]: t for t in depth["tiers"]}
        self.assertEqual(by_tier["Fish"]["count"], 1)   # W1
        self.assertEqual(by_tier["Shrimp"]["count"], 1)  # W2
        self.assertEqual(by_tier["Dolphin"]["count"], 0)

    def test_buckets_include_pools_flag_default_true(self):
        """Tanpa argumen: perilaku lama — bucket memuat LP/pool."""
        depth = sh.wallet_depth(
            [{"address": "POOL2", "usd_value": 5000.0, "is_wallet": False}],
            market_cap=10_000, pool_addresses=["POOL2"])
        by_label = {b["label"]: b for b in depth["buckets"]}
        self.assertEqual(by_label["$1k-$10k"]["count"], 1)
        self.assertTrue(depth["buckets_include_pools"])

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
        import holder_analysis as sa
        with mock.patch("core.get_holder_source", return_value="helius"):
            self.assertEqual(sa.resolve_holder_source(None), "helius")
        with mock.patch("core.get_holder_source", return_value="gmgn"):
            self.assertEqual(sa.resolve_holder_source("auto"), "auto")
        self.assertEqual(sa.resolve_holder_source("gmgn"), "gmgn")
        self.assertEqual(sa.resolve_holder_source("bogus"), "auto")
        # nilai legacy "solscan" tidak dikenali lagi → auto (Helius dulu)
        self.assertEqual(sa.resolve_holder_source("solscan"), "auto")

    def test_fetch_snapshot_helius_first_then_gmgn_fallback(self):
        """auto/helius → Helius dulu (dengan depth); kosong → GMGN."""
        import holder_analysis as sa

        # 1) Helius berisi data → snapshot helius + depth, GMGN tak dipanggil
        with mock.patch("core.get_helius_keys", return_value=["KEY"]):
            with mock.patch("holder_analysis.fetch_holders_helius"
                            ) as helius_mock:
                helius_mock.return_value = {"holders": [
                    {"address": "X", "usd_value": 1.0, "is_wallet": True}],
                    "source": "helius"}
                with mock.patch("solscan_holders.wallet_depth",
                                return_value={"buckets": []}) as depth_mock:
                    with mock.patch("holder_analysis.fetch_holders"
                                    ) as gmgn_mock:
                        snap, depth = sa._fetch_holders_snapshot(
                            "MINT", "auto", max_wallets=10, timeout=20,
                            price_usd=0.1, market_cap=100,
                            market={"pair_addresses": ["POOL"]})
                        self.assertEqual(snap["source"], "helius")
                        self.assertIsNotNone(depth)
                        gmgn_mock.assert_not_called()
                        helius_mock.assert_called_once()
                        self.assertEqual(
                            helius_mock.call_args.kwargs["helius_keys"],
                            ["KEY"])
                        # pool_addresses diteruskan ke wallet_depth
                        self.assertIn(
                            "POOL",
                            depth_mock.call_args.kwargs["pool_addresses"])

        # 2) Helius kosong → fallback fetch_holders (GMGN)
        with mock.patch("core.get_helius_keys", return_value=["KEY"]):
            with mock.patch("holder_analysis.fetch_holders_helius",
                            return_value={"holders": [], "source": "helius",
                                          "error": "kosong"}):
                with mock.patch("holder_analysis.fetch_holders"
                                ) as gmgn_mock:
                    gmgn_mock.return_value = {"holders": [{"address": "G"}],
                                              "source": "gmgn"}
                    snap, depth = sa._fetch_holders_snapshot(
                        "MINT", "auto", max_wallets=10, timeout=20,
                        price_usd=0.1, market_cap=100, market={})
                    self.assertEqual(snap["source"], "gmgn")
                    self.assertIsNone(depth)

        # 3) source=gmgn paksa → Helius tidak disentuh sama sekali
        with mock.patch("holder_analysis.fetch_holders_helius"
                        ) as helius_mock:
            with mock.patch("holder_analysis.fetch_holders") as gmgn_mock:
                gmgn_mock.return_value = {"holders": [], "source": "gmgn"}
                snap, depth = sa._fetch_holders_snapshot(
                    "MINT", "gmgn", max_wallets=10, timeout=20,
                    price_usd=0.1, market_cap=0, market={})
                self.assertEqual(snap["source"], "gmgn")
                self.assertIsNone(depth)
                helius_mock.assert_not_called()

        # 4) tanpa Helius key → langsung GMGN
        with mock.patch("core.get_helius_keys", return_value=[]):
            with mock.patch("holder_analysis.fetch_holders_helius"
                            ) as helius_mock:
                with mock.patch("holder_analysis.fetch_holders"
                                ) as gmgn_mock:
                    gmgn_mock.return_value = {"holders": [{"address": "G"}],
                                              "source": "gmgn"}
                    snap, depth = sa._fetch_holders_snapshot(
                        "MINT", "auto", max_wallets=10, timeout=20,
                        price_usd=0.1, market_cap=100, market={})
                    self.assertEqual(snap["source"], "gmgn")
                    self.assertIsNone(depth)
                    helius_mock.assert_not_called()

    def test_analyze_token_attaches_depth_for_helius(self):
        import holder_analysis as sa
        snapshot = {"holders": [
                        {"address": "W1", "usd_value": 500.0,
                         "is_wallet": True, "amount_pct": 0.0},
                        {"address": "W2", "usd_value": 5.0,
                         "is_wallet": True, "amount_pct": 0.0}],
                    "source": "helius"}
        with mock.patch("holder_analysis.get_market",
                        return_value={"symbol": "TST",
                                      "price_usd": 0.01,
                                      "marketcap": 100_000}):
            with mock.patch("holder_analysis._fetch_holders_snapshot",
                            return_value=(snapshot, {
                                "buckets": [], "tiers": []})):
                analysis = sa.analyze_token(
                    "MINT", "TST", holder_source="helius")
        self.assertEqual(analysis["holders"]["source"], "helius")
        self.assertIn("depth", analysis["holders"])
        self.assertNotIn("api", analysis["holders"])
        self.assertAlmostEqual(analysis["holders"]["real_count"], 1)

    def test_analyze_token_gmgn_source_has_no_depth(self):
        import holder_analysis as sa
        snapshot = {"holders": [{"address": "W1", "usd_value": 50.0,
                                 "is_wallet": True}],
                    "source": "gmgn", "pages": 1}
        with mock.patch("holder_analysis._fetch_holders_snapshot",
                        return_value=(snapshot, None)):
            analysis = sa.analyze_token(
                "MINT", "TST", market_cap=1000,
                holder_source="gmgn")
        self.assertEqual(analysis["holders"]["source"], "gmgn")
        self.assertNotIn("depth", analysis["holders"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
