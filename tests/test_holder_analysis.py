"""Coverage analisis holder real vs dust (GMGN + Helius)."""
from __future__ import annotations

import unittest
from unittest import mock

import holder_analysis as sa


def _holder(address, usd_value, *, is_wallet=True, amount_pct=0.001,
            is_new=False, is_suspicious=False):
    return {
        "address": address, "usd_value": float(usd_value),
        "balance": float(usd_value), "is_wallet": is_wallet,
        "amount_pct": float(amount_pct), "is_new": is_new,
        "is_suspicious": is_suspicious, "start_holding_at": 0,
        "last_active_at": 0, "netflow_usd": 0.0,
        "current_buy_amount": 0.0, "current_sell_amount": 0.0,
        "current_transfer_in": 0.0, "current_transfer_out": 0.0,
        "wallet_tag": "", "tags": [], "maker_token_tags": [],
    }


class ClassifyHoldersTest(unittest.TestCase):
    def test_splits_real_and_dust_with_dust_pct_mc(self):
        snapshot = {"holders": [
            _holder("real1", 500.0, amount_pct=0.05),
            _holder("real2", 11.0, amount_pct=0.002),
            _holder("dust1", 9.5, amount_pct=0.0002),
            _holder("dust2", 0.5, amount_pct=0.0001),
            # bukan wallet / kosong / LP → dikecualikan
            _holder("pool", 50_000.0, is_wallet=False),
            _holder("zero", 0.0),
        ]}
        stats = sa.classify_holders(snapshot, market_cap=10_000)
        self.assertEqual(stats["real_count"], 2)
        self.assertEqual(stats["dust_count"], 2)
        self.assertEqual(stats["wallets_analyzed"], 4)
        # dust value = 10.0 → 0.1% dari 10.000
        self.assertAlmostEqual(stats["dust_pct_mc"], 0.10, places=4)
        self.assertAlmostEqual(stats["real_pct_mc"], 5.11, places=2)

    def test_missing_marketcap_returns_none_pct(self):
        stats = sa.classify_holders(
            {"holders": [_holder("a", 5.0)]}, market_cap=0)
        self.assertIsNone(stats["dust_pct_mc"])

    def test_custom_dust_limit(self):
        stats = sa.classify_holders(
            {"holders": [_holder("a", 15.0)]}, market_cap=0, dust_limit=20.0)
        self.assertEqual(stats["dust_count"], 1)
        self.assertEqual(stats["real_count"], 0)


class HeliusFallbackTest(unittest.TestCase):
    def setUp(self):
        sa._HOLDER_CACHE.clear()

    def test_helius_holder_pagination_and_usd_math(self):
        """Helius DAS paginasi cursor, USD = (amount raw ÷ 10^dec) × price."""
        page1 = {
            "token_accounts": [
                {"owner": "A", "amount": 1_000_000.0, "address": "acc1"},
                {"owner": "B", "amount": 500_000.0, "address": "acc2"},
            ],
            "cursor": "cursor1",
        }
        page2 = {
            "token_accounts": [
                {"owner": "C", "amount": 200_000.0, "address": "acc3"},
            ],
            "cursor": "",
        }

        def fake_rpc(method, params, helius_keys=None, **_kwargs):
            if method == "getAsset":
                return {"token_info": {"decimals": 6}}
            if method == "getTokenAccounts":
                return page2 if params.get("cursor") else page1
            raise AssertionError(f"method tak terduga: {method}")

        with mock.patch("core.helius_rpc", side_effect=fake_rpc):
            with mock.patch("core.get_helius_keys", return_value=["key1"]):
                result = sa.fetch_holders_helius(
                    "MINT", max_wallets=10, price_usd=0.05)
        self.assertEqual(len(result["holders"]), 3)
        self.assertEqual(result["source"], "helius")
        self.assertEqual(result["decimals"], 6)
        # 1.000.000 raw (6 desimal) = 1 token UI → USD = 1 × price
        holders_dict = {h["address"]: h for h in result["holders"]}
        self.assertAlmostEqual(holders_dict["A"]["balance"], 1.0)
        self.assertAlmostEqual(holders_dict["A"]["usd_value"], 0.05)
        self.assertAlmostEqual(holders_dict["B"]["usd_value"], 0.025)
        self.assertAlmostEqual(holders_dict["C"]["usd_value"], 0.01)

    def test_helius_decimals_fallback_gettokensupply(self):
        """getAsset gagal → decimals dari RPC standar getTokenSupply."""
        page = {
            "token_accounts": [
                {"owner": "A", "amount": 250_000_000.0, "address": "acc1"},
            ],
            "cursor": "",
        }

        def fake_rpc(method, params, helius_keys=None, **_kwargs):
            if method == "getAsset":
                raise RuntimeError("DAS down")
            if method == "getTokenSupply":
                return {"value": {"decimals": 8}}
            if method == "getTokenAccounts":
                return page
            raise AssertionError(f"method tak terduga: {method}")

        with mock.patch("core.helius_rpc", side_effect=fake_rpc):
            with mock.patch("core.get_helius_keys", return_value=["key1"]):
                result = sa.fetch_holders_helius(
                    "MINT", max_wallets=10, price_usd=2.0)
        self.assertEqual(result["decimals"], 8)
        self.assertAlmostEqual(result["holders"][0]["balance"], 2.5)
        self.assertAlmostEqual(result["holders"][0]["usd_value"], 5.0)

    def test_helius_row_decimals_dipakai_tanpa_lookup(self):
        """Item token_accounts yang membawa decimals → tanpa panggil mint."""
        page = {
            "token_accounts": [
                {"owner": "A", "amount": 3_000.0, "decimals": 3,
                 "address": "acc1"},
            ],
            "cursor": "",
        }
        with mock.patch("core.helius_rpc", return_value=page) as rpc:
            with mock.patch("core.get_helius_keys", return_value=["key1"]):
                result = sa.fetch_holders_helius(
                    "MINT", max_wallets=10, price_usd=1.0)
        for call in rpc.call_args_list:
            self.assertEqual(call.args[0], "getTokenAccounts")
        self.assertAlmostEqual(result["holders"][0]["balance"], 3.0)
        self.assertAlmostEqual(result["holders"][0]["usd_value"], 3.0)

    def test_helius_tanpa_decimals_berhenti_bersih(self):
        """Decimals tak ketemu → kosong + error, bukan nilai ÷10^dec meleset."""
        page = {
            "token_accounts": [
                {"owner": "A", "amount": 1_000_000.0, "address": "acc1"},
            ],
            "cursor": "",
        }

        def fake_rpc(method, params, helius_keys=None, **_kwargs):
            if method == "getTokenAccounts":
                return page
            raise RuntimeError("decimals tidak tersedia")

        with mock.patch("core.helius_rpc", side_effect=fake_rpc):
            with mock.patch("core.get_helius_keys", return_value=["key1"]):
                result = sa.fetch_holders_helius(
                    "MINT", max_wallets=10, price_usd=0.05)
        self.assertEqual(result["holders"], [])
        self.assertEqual(result["fetched"], 0)
        self.assertIn("decimals", result["error"])

    def test_holder_fallback_gmgn_to_helius(self):
        """GMGN error → otomatis fallback ke Helius."""
        with mock.patch("holder_analysis._http_get",
                        side_effect=RuntimeError("GMGN down")):
            with mock.patch("core.helius_rpc") as mock_helius:
                mock_helius.return_value = {
                    "token_accounts": [
                        {"owner": "X", "amount": 100.0, "decimals": 2,
                         "address": "acc_x"},
                    ],
                    "cursor": "",
                }
                with mock.patch("core.get_helius_keys",
                                return_value=["key1"]):
                    result = sa.fetch_holders(
                        "MINT", max_wallets=10, price_usd=0.1)
        self.assertEqual(result["source"], "helius")
        self.assertEqual(len(result["holders"]), 1)
        self.assertEqual(result["holders"][0]["address"], "X")
        # 100 raw (2 desimal) = 1 token UI → USD = 1 × $0.10
        self.assertAlmostEqual(result["holders"][0]["usd_value"], 0.1)

    def test_holder_no_fallback_without_price(self):
        """Tanpa price_usd, fallback Helius tidak jalan."""
        with mock.patch("holder_analysis._http_get",
                        side_effect=RuntimeError("GMGN down")):
            result = sa.fetch_holders("MINT", max_wallets=10, price_usd=0.0)
        self.assertEqual(result["source"], "gmgn")
        self.assertEqual(len(result["holders"]), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
