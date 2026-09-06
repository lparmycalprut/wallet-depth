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


class ProviderFailureTest(unittest.TestCase):
    """Scan yang gagal tidak boleh terbaca seperti hasil (dust 0% = AMAN)."""

    @staticmethod
    def _http_error(status):
        import requests

        response = mock.Mock(status_code=status)
        return requests.exceptions.HTTPError(f"{status}", response=response)

    def test_transient_status_dicoba_ulang(self):
        calls = []
        ok = mock.Mock()
        ok.raise_for_status.return_value = None
        ok.json.return_value = {"status": "1", "result": {"decimals": "18"}}

        def fake_get(*args, **kwargs):
            calls.append(kwargs.get("params") or args)
            if len(calls) == 1:
                raise self._http_error(429)
            return ok

        with mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh.time, "sleep") as sleep:
            payload = rh._jsjson({"module": "token"})
        self.assertEqual(payload["status"], "1")
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once()

    def test_error_terminal_tidak_diulang(self):
        def fake_get(*args, **kwargs):
            raise self._http_error(404)

        with mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh.time, "sleep") as sleep:
            with self.assertRaises(Exception):
                rh._jsjson({"module": "token"})
        sleep.assert_not_called()

    def test_is_transient_error_jenis(self):
        import requests

        self.assertTrue(rh.is_transient_error(
            requests.exceptions.ConnectionError("closed")))
        self.assertTrue(rh.is_transient_error(self._http_error(503)))
        self.assertFalse(rh.is_transient_error(self._http_error(400)))
        self.assertFalse(rh.is_transient_error(ValueError("json")))

    def test_getToken_status_nol_dilempar(self):
        """Blockscout menolak (rate limit) → error, bukan decimals -1 diam-diam."""
        with mock.patch.object(rh, "_jsjson", return_value={
                "status": "0", "message": "Max rate limit reached",
                "result": None}):
            with self.assertRaises(RuntimeError) as ctx:
                rh.fetch_token_info(EV_LOWER)
        self.assertIn("Max rate limit reached", str(ctx.exception))

    def test_fetch_holders_menyalin_error_provider(self):
        with mock.patch.object(rh, "fetch_token_info",
                               side_effect=RuntimeError("getToken down")):
            out = rh.fetch_holders(EV_LOWER, price_usd=1.0, decimals=None)
        self.assertEqual(out["fetched"], 0)
        self.assertEqual(out["holders"], [])
        self.assertIn("getToken down", out["error"])

    def test_analyze_token_membawa_fetch_error_ke_hasil(self):
        with mock.patch.object(rh, "get_market", return_value={
                "price_usd": 0.5, "marketcap": 1000.0, "symbol": "VLAD"}), \
                mock.patch.object(rh, "fetch_token_info",
                                  side_effect=RuntimeError("429 rate limit")):
            result = rh.analyze_token(EV_LOWER, "VLAD", fetch_market=True)
        holders = result["holders"]
        self.assertEqual(holders["total_fetched"], 0)
        self.assertIn("429 rate limit", holders["fetch_error"])


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
