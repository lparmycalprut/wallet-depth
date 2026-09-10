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
POOL = "0x" + "ab" * 20
WALLET = "0x" + "cd" * 20
DUST = "0x" + "ef" * 20


class _CsvResponse:
    """Response minimal ala requests untuk CSV export Blockscout."""

    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        return None


class _JsonResponse:
    def __init__(self, payload):
        self._payload = payload
        self.text = ""
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _only_rpc():
    """Matikan CSV + v2 + counters supaya jalur legacy RPC yang diuji."""
    return mock.patch.multiple(
        rh,
        fetch_holders_csv=mock.Mock(side_effect=RuntimeError("csv off")),
        fetch_holders_v2=mock.Mock(return_value=[]),
        fetch_holders_count=mock.Mock(return_value=0),
    )


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
    def setUp(self):
        rh.clear_holder_cache()

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

        # CSV + v2 tidak tersedia → jatuh ke legacy RPC
        with _only_rpc(), \
                mock.patch.object(rh, "_jsjson", side_effect=fake_json):
            out = rh.fetch_holders(EV_LOWER, price_usd=1.0, decimals=18,
                                   total_supply=1_000_000.0)
        self.assertEqual(out["source"], rh.SOURCE_RPC)
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

        with _only_rpc(), \
                mock.patch.object(rh, "_jsjson", side_effect=fake_json):
            out = rh.fetch_holders(
                EV_LOWER, price_usd=1.0, decimals=18, total_supply=1_000.0,
                max_wallets=3)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["fetched"], 3)

    def test_fetch_holders_csv_primary(self):
        """CSV export berhasil → satu request, tanpa paginasi sama sekali."""
        csv_rows = [{"address": EV_LOWER, "balance": 100.0, "usd_value": 50.0,
                     "amount_pct": 0.01, "is_wallet": True}]
        with mock.patch.object(rh, "fetch_holders_csv",
                               return_value=csv_rows) as csv_call, \
                mock.patch.object(rh, "fetch_holders_count", return_value=1), \
                mock.patch.object(rh, "fetch_holders_v2") as v2_call, \
                mock.patch.object(rh, "_jsjson") as rpc_call:
            out = rh.fetch_holders(EV_LOWER, price_usd=0.5, decimals=18,
                                   total_supply=1_000.0)
        self.assertEqual(out["source"], rh.SOURCE_CSV)
        self.assertEqual(out["fetched"], 1)
        self.assertEqual(out["pages"], 1)
        self.assertFalse(out["truncated"])
        csv_call.assert_called_once()
        v2_call.assert_not_called()
        rpc_call.assert_not_called()

    def test_fetch_holders_csv_parses_decimal_balances(self):
        """CSV Blockscout sudah ter-scale decimals → jangan dibagi lagi."""
        body = ("HolderAddress,Balance\n"
                f"{EV},90.15199648\n"
                "0x" + "2" * 40 + ",0.000000000000000001\n"
                "0x" + "3" * 40 + ",0\n"
                "bukan-address,5\n")
        with mock.patch.object(rh, "_http_get",
                               return_value=_CsvResponse(body)):
            rows = rh.fetch_holders_csv(EV_LOWER, price_usd=2.0,
                                        supply=1_000.0)
        self.assertEqual(len(rows), 2)          # nol + address invalid dibuang
        self.assertAlmostEqual(rows[0]["balance"], 90.15199648)
        self.assertAlmostEqual(rows[0]["usd_value"], 180.30399296)
        self.assertAlmostEqual(rows[0]["amount_pct"], 90.15199648 / 1_000.0)
        self.assertEqual(rows[0]["address"], EV_LOWER)   # ter-lowercase
        self.assertTrue(rows[0]["is_wallet"])

    def test_fetch_holders_rpc_offset_max_400(self):
        """Regresi: offset > 400 ditolak Blockscout ("Something went wrong")."""
        seen = []

        def fake_json(params):
            seen.append(params)
            if int(params.get("offset", 0)) > 400:
                return {"status": "0", "message": "Something went wrong."}
            return {"status": "1", "message": "OK", "result": [
                {"address": f"0x{a:040x}", "value": "1000000000000000000"}
                for a in range(3)]}

        with _only_rpc(), mock.patch.object(rh, "_jsjson",
                                            side_effect=fake_json):
            out = rh.fetch_holders(EV_LOWER, price_usd=1.0, decimals=18,
                                   total_supply=1_000.0)
        self.assertEqual(rh.HOLDER_PAGE_SIZE, 400)
        self.assertTrue(seen)
        self.assertTrue(all(int(p["offset"]) <= 400 for p in seen))
        self.assertEqual(out["fetched"], 3)
        self.assertEqual(out["error"], "")

    def test_fetch_holders_v2_keyset_pagination(self):
        """v2 mengikuti cursor next_page_params dan menandai kontrak = pool."""
        pages = [
            {"items": [{"address": {"hash": EV, "is_contract": False},
                        "value": "2000000000000000000"},
                       {"address": {"hash": "0x" + "4" * 40, "is_contract": True,
                                    "name": "UniswapV3Pool"},
                        "value": "9000000000000000000"}],
             "next_page_params": {"address_hash": "0x" + "4" * 40,
                                  "value": "9"}},
            {"items": [{"address": {"hash": "0x" + "5" * 40,
                                    "is_contract": False},
                        "value": "1000000000000000000"}],
             "next_page_params": None},
        ]
        calls = []

        def fake_get(url, params=None, **kw):
            calls.append(dict(params or {}))
            return _JsonResponse(pages[len(calls) - 1])

        with mock.patch.object(rh, "_http_get", side_effect=fake_get):
            rows = rh.fetch_holders_v2(EV_LOWER, price_usd=1.0,
                                       supply=1_000.0, decimals=18)
        self.assertEqual(len(rows), 3)
        self.assertEqual(calls[0]["items_count"], 50)
        self.assertEqual(calls[1]["address_hash"], "0x" + "4" * 40)
        by_addr = {r["address"]: r for r in rows}
        self.assertTrue(by_addr[EV_LOWER]["is_wallet"])
        pool = by_addr["0x" + "4" * 40]
        self.assertFalse(pool["is_wallet"])          # kontrak = pool/LP
        self.assertEqual(pool["wallet_tag"], "UniswapV3Pool")


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
        with _only_rpc(), \
                mock.patch.object(rh, "fetch_token_info",
                                  side_effect=RuntimeError("getToken down")):
            out = rh.fetch_holders(EV_LOWER, price_usd=1.0, decimals=None)
        self.assertEqual(out["fetched"], 0)
        self.assertEqual(out["holders"], [])
        self.assertIn("getToken down", out["error"])

    def test_analyze_token_membawa_fetch_error_ke_hasil(self):
        with mock.patch.object(rh, "get_market", return_value={
                "price_usd": 0.5, "marketcap": 1000.0, "symbol": "VLAD"}), \
                _only_rpc(), \
                mock.patch.object(rh, "fetch_token_info",
                                  side_effect=RuntimeError("429 rate limit")):
            result = rh.analyze_token(EV_LOWER, "VLAD", fetch_market=True)
        holders = result["holders"]
        self.assertEqual(holders["total_fetched"], 0)
        self.assertIn("429 rate limit", holders["fetch_error"])


class WrapperTest(unittest.TestCase):
    """Wrapper Robinhood hanya memilih trio path + meneruskan ``background``.

    ``background`` adalah jalur UI non-blocking (lihat 2026-09-06): default
    ``False`` untuk pemanggil script/cron, ``True`` untuk tombol di card
    supaya commit GitHub tidak memblokir rerun Streamlit.
    """

    def test_add_passes_robinhood_paths(self):
        with mock.patch.object(wl, "add_to_watchlist", return_value=True) as add:
            self.assertTrue(rw.add_to_robinhood_watchlist(EV, "VLAD"))
        add.assert_called_once_with(
            EV, "VLAD", note="", source="manual",
            repo_path="watchlist_robinhood.json",
            local_path=rw.WATCHLIST_LOCAL_PATH,
            pending_path=rw.WATCHLIST_PENDING_PATH,
            chain_id="robinhood", background=False)

    def test_add_background_flag_diteruskan(self):
        with mock.patch.object(wl, "add_to_watchlist", return_value=True) as add:
            self.assertTrue(rw.add_to_robinhood_watchlist(
                EV, "VLAD", source="lp", background=True))
        self.assertTrue(add.call_args.kwargs["background"])
        self.assertEqual(add.call_args.kwargs["repo_path"],
                         "watchlist_robinhood.json")

    def test_remove_passes_robinhood_paths(self):
        with mock.patch.object(wl, "remove_from_watchlist",
                               return_value=True) as remove:
            self.assertTrue(rw.remove_from_robinhood_watchlist(EV))
        remove.assert_called_once_with(
            EV, repo_path="watchlist_robinhood.json",
            local_path=rw.WATCHLIST_LOCAL_PATH,
            pending_path=rw.WATCHLIST_PENDING_PATH, background=False)

    def test_remove_background_flag_diteruskan(self):
        with mock.patch.object(wl, "remove_from_watchlist",
                               return_value=True) as remove:
            self.assertTrue(rw.remove_from_robinhood_watchlist(
                EV, background=True))
        remove.assert_called_once_with(
            EV, repo_path="watchlist_robinhood.json",
            local_path=rw.WATCHLIST_LOCAL_PATH,
            pending_path=rw.WATCHLIST_PENDING_PATH, background=True)

    def test_move_background_flag_diteruskan(self):
        with mock.patch.object(wl, "set_watchlist_source",
                               return_value=True) as move:
            self.assertTrue(rw.set_robinhood_watchlist_source(
                EV, rw.RH_REGULAR_SOURCE, background=True))
        self.assertEqual(move.call_args.args, (EV, rw.RH_REGULAR_SOURCE))
        self.assertTrue(move.call_args.kwargs["background"])

    def test_sync_state_membaca_status_push_file_robinhood(self):
        with mock.patch.object(wl, "push_status",
                               return_value={"state": "syncing"}) as status:
            self.assertEqual(rw.sync_state(), {"state": "syncing"})
        status.assert_called_once_with("watchlist_robinhood.json")


class ScanTokenHoldersTest(unittest.TestCase):
    """Scan Holder Solana / Robinhood (section app) untuk CA Robinhood Chain.

    Shape hasil harus **sama persis** dengan
    ``helius_holders.scan_token_holders`` supaya UI Scan Holder Solana / Robinhood
    dipakai ulang tanpa cabang.
    """

    MARKET = {"symbol": "VLAD", "price_usd": 1.0, "marketcap": 100_000.0,
              "pair_addresses": [POOL.upper()]}
    SNAPSHOT = {
        "holders": [
            {"address": WALLET, "balance": 500.0, "usd_value": 500.0,
             "amount_pct": 0.5, "is_wallet": True},
            {"address": DUST, "balance": 5.0, "usd_value": 5.0,
             "amount_pct": 0.005, "is_wallet": True},
            # Pool AMM (di market.pair_addresses) — default harus keluar
            # dari bucket, tetap dihitung pool_excluded.
            {"address": POOL, "balance": 90_000.0, "usd_value": 90_000.0,
             "amount_pct": 90.0, "is_wallet": True},
        ],
        "pages": 1, "truncated": False, "fetched": 3, "analyzed_at": 0,
        "source": rh.SOURCE_CSV, "decimals": 18, "error": ""}

    def _patch(self, snapshot=None, market=None, decimals=18,
               total_supply=100_000.0):
        snapshot = self.SNAPSHOT if snapshot is None else snapshot
        market = self.MARKET if market is None else market
        return (
            mock.patch.object(rh, "get_market",
                              return_value=dict(market)),
            mock.patch.object(rh, "fetch_token_info",
                              return_value={"name": "Vlad",
                                            "symbol": "VLAD",
                                            "decimals": decimals,
                                            "total_supply": total_supply}),
            mock.patch.object(rh, "fetch_holders",
                              return_value=dict(snapshot)),
        )

    def test_scan_uses_robinhood_holders_and_builds_depth(self):
        """CSV Blockscout berhasil → source blockscout-csv, depth seperti Helius."""
        patches = self._patch()
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        result = rh.scan_token_holders(EV)

        # shape identik dengan helius_holders.scan_token_holders
        for key in ("mint", "symbol", "market", "snapshot", "depth",
                    "source", "no_helius_keys", "scan_failed"):
            self.assertIn(key, result)
        self.assertEqual(result["mint"], EV_LOWER)  # EVM di-normalize
        self.assertEqual(result["symbol"], "VLAD")
        self.assertEqual(result["source"], rh.SOURCE_CSV)
        self.assertFalse(result["no_helius_keys"])
        self.assertFalse(result["scan_failed"])
        # default: LP/pool disingkirkan dari bucket
        by_label = {b["label"]: b for b in result["depth"]["buckets"]}
        self.assertEqual(by_label[">$0-$10"]["count"], 1)   # DUST
        self.assertEqual(by_label["$100-$1k"]["count"], 1)  # WALLET
        self.assertEqual(by_label["$10k-$100k"]["count"], 0)  # POOL keluar
        self.assertFalse(result["depth"]["buckets_include_pools"])
        self.assertEqual(result["depth"]["holders_all"], 3)
        self.assertEqual(result["depth"]["holders_wallet"], 2)
        self.assertEqual(result["depth"]["pool_excluded"], 1)

    def test_scan_include_pools_keeps_pool_in_buckets(self):
        patches = self._patch()
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        result = rh.scan_token_holders(EV, include_pools=True)
        by_label = {b["label"]: b for b in result["depth"]["buckets"]}
        self.assertEqual(by_label["$10k-$100k"]["count"], 1)  # POOL masuk
        self.assertTrue(result["depth"]["buckets_include_pools"])

    def test_scan_passes_max_wallets_decimals_and_supply(self):
        with mock.patch.object(rh, "get_market",
                               return_value=dict(self.MARKET)), \
                mock.patch.object(rh, "fetch_token_info",
                                  return_value={"decimals": 18,
                                                "total_supply": 100_000.0}), \
                mock.patch.object(rh, "fetch_holders",
                                  return_value=dict(self.SNAPSHOT)) as fetch:
            rh.scan_token_holders(EV, max_wallets=2000)
        self.assertEqual(fetch.call_args.kwargs["max_wallets"], 2000)
        self.assertEqual(fetch.call_args.kwargs["price_usd"], 1.0)
        self.assertEqual(fetch.call_args.kwargs["decimals"], 18)
        self.assertEqual(fetch.call_args.kwargs["total_supply"], 100_000.0)

    def test_scan_without_price_flags_failed(self):
        """DexScreener kosong → tanpa fetch holder, scan_failed=True."""
        market_empty = {"symbol": "VLAD", "price_usd": 0.0, "marketcap": 0.0,
                        "pair_addresses": []}
        no_price = {"holders": [], "pages": 0, "truncated": False,
                    "fetched": 0, "analyzed_at": 0, "source": rh.SOURCE_CSV,
                    "decimals": None, "error": "price/address empty"}
        with mock.patch.object(rh, "get_market", return_value=market_empty), \
                mock.patch.object(rh, "fetch_token_info") as info, \
                mock.patch.object(rh, "fetch_holders",
                                  return_value=no_price) as fetch:
            result = rh.scan_token_holders(EV)
        self.assertTrue(result["scan_failed"])
        self.assertFalse(result["no_helius_keys"])
        info.assert_not_called()  # tanpa harga tidak perlu decimals
        self.assertEqual(fetch.call_args.kwargs["price_usd"], 0.0)

    def test_scan_provider_failure_flags_failed_with_detail(self):
        """Semua jalur Blockscout gagal → scan_failed + alasan provider."""
        failed = {"holders": [], "pages": 0, "truncated": False,
                  "fetched": 0, "analyzed_at": 0,
                  "source": f"{rh.SOURCE_CSV}(fail)",
                  "decimals": None,
                  "error": "csv: 429; rpc: 429 Too Many Requests"}
        patches = self._patch(snapshot=failed)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        result = rh.scan_token_holders(EV)
        self.assertTrue(result["scan_failed"])
        self.assertIn("blockscout", result["source"])
        self.assertIn("429", result["snapshot"]["error"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
