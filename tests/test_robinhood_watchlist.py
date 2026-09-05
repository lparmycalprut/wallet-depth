# -*- coding: utf-8 -*-
"""Watchlist & holder helper untuk Robinhood Chain (EVM, chain id 4663).

Tidak menembus jaringan: transport Blockscout/daily/GitHub di-mock, dan
conftest menonaktifkan loader watchlist/status/history untuk suite umum.
"""
from __future__ import annotations

import unittest
from unittest import mock

import robinhood_holders as rh
import robinhood_watchlist as rw
import watchlist as wl


EV = "0x8490AcD2d52D0Ebd34CB13E01Bd9a9380b36411D"
EV_LOWER = EV.lower()


class AddressTest(unittest.TestCase):
    def test_normalize_lowercases_evm(self):
        self.assertEqual(rh.normalize_address(EV), EV_LOWER)

    def test_solana_base58_untouched(self):
        sol = "So11111111111111111111111111111111111111112"
        self.assertEqual(rh.normalize_address(sol), sol)
        self.assertFalse(rh.is_robinhood_address(sol))

    def test_is_robinhood_address(self):
        self.assertTrue(rh.is_robinhood_address(EV))
        self.assertFalse(rh.is_robinhood_address(""))
        self.assertFalse(rh.is_robinhood_address("0x1234"))


class FetchHoldersTest(unittest.TestCase):
    def test_fetch_holders_converts_raw_by_decimals(self):
        calls = []
        other = "0x" + "1" * 40

        def fake_json(params):
            calls.append(params)
            if params.get("action") == "getToken":
                return {"status": "1",
                        "result": {"decimals": "18", "symbol": "VLAD",
                                   "totalSupply": "1000000000000000000000000000"}}
            return {"status": "1", "message": "OK",
                    "result": [
                        {"address": other, "value": "2000000000000000000"},
                        {"address": EV_LOWER, "value": "500000000000000000"},
                    ]}

        with mock.patch.object(rh, "_jsjson", side_effect=fake_json):
            out = rh.fetch_holders(EV_LOWER, price_usd=1.0, decimals=18,
                                   total_supply=1_000_000.0)
        self.assertEqual(out["source"], "blockscout")
        self.assertEqual(out["fetched"], 2)
        by_addr = {row["address"]: row for row in out["holders"]}
        self.assertAlmostEqual(by_addr[EV_LOWER]["balance"], 0.5)
        self.assertAlmostEqual(by_addr[EV_LOWER]["usd_value"], 0.5)
        self.assertAlmostEqual(by_addr[EV_LOWER]["amount_pct"], 0.5 / 1e6)

    def test_fetch_holders_stops_on_max(self):
        def fake_json(params):
            return {"status": "1", "message": "OK", "result": [
                {"address": f"0x{a:040x}", "value": "1000000000000000000"}
                for a in range(5)
            ]}

        with mock.patch.object(rh, "_jsjson", side_effect=fake_json):
            out = rh.fetch_holders(
                EV_LOWER, price_usd=1.0, decimals=18, total_supply=1_000.0,
                max_wallets=3)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["fetched"], 3)


class WrapperTest(unittest.TestCase):
    def test_add_passes_robinhood_paths(self):
        with mock.patch.object(wl, "add_to_watchlist", return_value=True) as add:
            self.assertTrue(rw.add_to_robinhood_watchlist(EV, "VLAD"))
        add.assert_called_once_with(
            EV, "VLAD", note="", source="manual",
            repo_path="watchlist_robinhood.json",
            local_path=rw.WATCHLIST_LOCAL_PATH,
            pending_path=rw.WATCHLIST_PENDING_PATH,
            chain_id="robinhood")

    def test_remove_passes_robinhood_paths(self):
        with mock.patch.object(wl, "remove_from_watchlist",
                               return_value=True) as remove:
            self.assertTrue(rw.remove_from_robinhood_watchlist(EV))
        remove.assert_called_once_with(
            EV, repo_path="watchlist_robinhood.json",
            local_path=rw.WATCHLIST_LOCAL_PATH,
            pending_path=rw.WATCHLIST_PENDING_PATH)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
