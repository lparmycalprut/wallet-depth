"""Coverage untuk silent-accumulation 12 jam + holder real vs dust."""
from __future__ import annotations

import unittest
from unittest import mock

import silent_accumulation as sa


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


class DetectSilentTest(unittest.TestCase):
    def test_detects_silent_accumulation(self):
        flow = {"net_usd": 250.0, "accumulators": 6, "distributors": 1,
                "bot_share": 0.1, "price_chg_pct": 1.2}
        res = sa.detect_silent(flow)
        self.assertTrue(res["silent"])
        self.assertEqual(res["strength"], "sedang")

    def test_strong_silent(self):
        flow = {"net_usd": 600.0, "accumulators": 10, "bot_share": 0.05,
                "price_chg_pct": 0.5}
        self.assertEqual(sa.detect_silent(flow)["strength"], "kuat")

    def test_price_move_too_big_is_not_silent(self):
        flow = {"net_usd": 250.0, "accumulators": 5, "bot_share": 0.1,
                "price_chg_pct": 12.0}
        self.assertFalse(sa.detect_silent(flow)["silent"])

    def test_negative_net_is_not_silent(self):
        flow = {"net_usd": -50.0, "accumulators": 0, "bot_share": 0.1,
                "price_chg_pct": -2.0}
        self.assertFalse(sa.detect_silent(flow)["silent"])

    def test_few_accumulators_is_not_silent(self):
        flow = {"net_usd": 500.0, "accumulators": 1, "bot_share": 0.0,
                "price_chg_pct": 0.0}
        self.assertFalse(sa.detect_silent(flow)["silent"])


class Fetch12hFlowTest(unittest.TestCase):
    def setUp(self):
        sa._FLOW_CACHE.clear()
        sa._HOLDER_CACHE.clear()

    def test_aggregates_net_and_accumulators(self):
        now = 1_800_000_000
        swaps = [
            ("buy", 1.0, now - 3600, "A", 0.01, 100.0, []),
            ("buy", 1.0, now - 1800, "B", 0.011, 110.0, []),
            ("sell", 0.5, now - 900, "A", 0.012, 50.0, []),
            ("sell", 2.0, now - 600, "C", 0.012, 200.0, ["mev"]),
            ("buy", 1.0, now - 60, "D", 0.013, 130.0, []),
        ]
        # Tanpa Helius key → langsung jalur GMGN.
        with mock.patch("core.get_helius_keys", return_value=[]):
            with mock.patch("cvd.fetch_gmgn_swaps",
                            return_value=(swaps, "s", 0, True)):
                flow = sa.fetch_12h_flow("CA", now_ts=now, max_pages=2)
        self.assertEqual(flow["buy_tx"], 3)
        self.assertEqual(flow["sell_tx"], 2)
        self.assertAlmostEqual(flow["net_usd"], 90.0, places=2)
        self.assertEqual(flow["accumulators"], 3)  # A net +50, B, D
        self.assertEqual(flow["distributors"], 1)
        self.assertAlmostEqual(flow["bot_share"], 200 / 590, places=3)
        self.assertAlmostEqual(flow["price_chg_pct"],
                               (0.013 / 0.01 - 1) * 100, places=2)
        self.assertEqual(flow["source"], "gmgn")

    def test_out_of_window_trades_are_filtered(self):
        now = 1_800_000_000
        swaps = [("buy", 1.0, now - 13 * 3600, "OLD", 0.01, 100.0, []),
                 ("buy", 1.0, now - 60, "NEW", 0.011, 110.0, [])]
        with mock.patch("core.get_helius_keys", return_value=[]):
            with mock.patch("cvd.fetch_gmgn_swaps",
                            return_value=(swaps, "s", 0, False)):
                flow = sa.fetch_12h_flow("CA", now_ts=now, max_pages=1)
        self.assertEqual(flow["buy_tx"], 1)
        self.assertEqual(flow["wallets"], 1)


class HolderFilterTest(unittest.TestCase):
    def _analysis(self, *, real=100, dust=100, silent=False,
                  real_mc=5.0, dust_mc=1.0):
        """Analysis fiksi untuk tes filter holder depth."""
        return {
            "holders": {"real_count": real, "dust_count": dust,
                        "real_pct_mc": real_mc, "dust_pct_mc": dust_mc},
            "silent": {"silent": silent},
        }

    def test_silent_filter(self):
        self.assertTrue(sa.holder_filter_match(
            self._analysis(silent=True), "SILENT"))
        self.assertFalse(sa.holder_filter_match(
            self._analysis(silent=False), "SILENT"))
        self.assertFalse(sa.holder_filter_match(None, "SILENT"))

    def test_lp_filter_dust_more_than_half_real_and_below_half_pct_mc(self):
        # dust 120 > 0.5*100 dan total holder 0.4% MC → LP ✔
        self.assertTrue(sa.holder_filter_match(
            self._analysis(real=100, dust=120, real_mc=0.25, dust_mc=0.15),
            "LP"))
        # dust tidak > 50% real → bukan LP
        self.assertFalse(sa.holder_filter_match(
            self._analysis(real=100, dust=40, real_mc=0.25, dust_mc=0.15),
            "LP"))
        # holder total >= 0.5% MC → bukan LP
        self.assertFalse(sa.holder_filter_match(
            self._analysis(real=100, dust=120, real_mc=0.4, dust_mc=0.3),
            "LP"))
        # real_pct_mc tidak diketahui → bukan LP (jangan menebak)
        self.assertFalse(sa.holder_filter_match(
            {"holders": {"real_count": 100, "dust_count": 120,
                         "real_pct_mc": None, "dust_pct_mc": 0.1}}, "LP"))

    def test_pumpdump_filter_real_less_than_20_pct_of_dust(self):
        # real 15 < 0.2*100 → PUMPDUMP ✔
        self.assertTrue(sa.holder_filter_match(
            self._analysis(real=15, dust=100), "PUMPDUMP"))
        # real 25 >= 0.2*100 → bukan PUMPDUMP
        self.assertFalse(sa.holder_filter_match(
            self._analysis(real=25, dust=100), "PUMPDUMP"))
        self.assertFalse(sa.holder_filter_match(
            self._analysis(real=0, dust=0), "PUMPDUMP"))

    def test_apply_filters_and_count(self):
        rows = [
            {"ca": "S", "analysis": self._analysis(real=300, dust=400,
                                                   real_mc=0.2,
                                                   dust_mc=0.2, silent=True)},
            {"ca": "L", "analysis": self._analysis(real=100, dust=120,
                                                   real_mc=0.2,
                                                   dust_mc=0.2)},
            {"ca": "P", "analysis": self._analysis(real=10, dust=100)},
            {"ca": "X", "analysis": None},
        ]
        counts = sa.filter_counts(rows)
        self.assertEqual(counts["SILENT"], 1)
        # S (dust 400 > 150 & 0.4% < 0.5) dan L → 2
        self.assertEqual(counts["LP"], 2)
        self.assertEqual(counts["PUMPDUMP"], 1)
        self.assertEqual(len(sa.apply_filters(rows, ["SILENT"])), 1)
        self.assertEqual(len(sa.apply_filters(rows, ["LP", "SILENT"])), 1)
        self.assertEqual(len(sa.apply_filters(rows, [])), 4)
        self.assertEqual(len(sa.apply_filters(rows, ["TIDAK_ADA"])), 4)


class EnrichRowsTest(unittest.TestCase):
    def setUp(self):
        sa._FLOW_CACHE.clear()
        sa._HOLDER_CACHE.clear()

    def test_enrich_marks_analysis_and_keeps_failures_null(self):
        def fake_analyze(ca, *args, **kwargs):
            if ca == "BAD":
                raise RuntimeError("boom")
            return {"ca": ca, "symbol": args[0] if args else "?"}

        rows = [{"ca": "GOOD", "symbol": "GD", "mc": 100},
                {"ca": "BAD", "symbol": "BD", "mc": 200}]
        with mock.patch.object(sa, "analyze_token", side_effect=fake_analyze):
            out = sa.enrich_rows(rows, max_wallets=10, max_trade_pages=1)
        self.assertIsNotNone(out[0]["analysis"])
        self.assertIsNone(out[1]["analysis"])


class HeliusFallbackTest(unittest.TestCase):
    def setUp(self):
        sa._FLOW_CACHE.clear()
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
        with mock.patch("silent_accumulation._http_get",
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
        with mock.patch("silent_accumulation._http_get",
                        side_effect=RuntimeError("GMGN down")):
            result = sa.fetch_holders("MINT", max_wallets=10, price_usd=0.0)
        self.assertEqual(result["source"], "gmgn")
        self.assertEqual(len(result["holders"]), 0)

    def test_flow_helius_prioritas_gmgn_tidak_dipanggil(self):
        """Helius mengembalikan swap 12 jam → GMGN tidak dipanggil sama sekali."""
        now = 1_800_000_000
        with mock.patch("cvd.fetch_gmgn_swaps") as mock_gmgn:
            with mock.patch("cvd.fetch_swaps") as mock_helius_swaps:
                mock_helius_swaps.return_value = (
                    [("buy", 1.0, now - 3600, "W", 0.01, 100.0, [])],
                    "sig", now - 3600, True)
                with mock.patch("core.get_helius_keys",
                                return_value=["key1"]):
                    with mock.patch("requests.get") as mock_get:
                        mock_get.return_value.json.return_value = {
                            "pairs": [{"pairAddress": "POOL",
                                       "baseToken": {"address": "MINT"}}]
                        }
                        flow = sa.fetch_12h_flow("MINT", now_ts=now)
        self.assertEqual(flow["source"], "helius")
        self.assertEqual(flow["buy_tx"], 1)
        mock_gmgn.assert_not_called()

    def test_flow_fallback_helius_kosong_ke_gmgn(self):
        """Helius kosong/gagal → fallback ke GMGN swaps."""
        now = 1_800_000_000
        gmgn_swaps = [("sell", 2.0, now - 7200, "W", 0.02, 50.0, [])]
        with mock.patch("cvd.fetch_swaps", return_value=([], "s", 0, False)):
            with mock.patch("cvd.fetch_gmgn_swaps",
                            return_value=(gmgn_swaps, "s", 0, True)):
                with mock.patch("core.get_helius_keys",
                                return_value=["key1"]):
                    with mock.patch("requests.get") as mock_get:
                        mock_get.return_value.json.return_value = {
                            "pairs": [{"pairAddress": "POOL",
                                       "baseToken": {"address": "MINT"}}]
                        }
                        flow = sa.fetch_12h_flow("MINT", now_ts=now)
        self.assertEqual(flow["source"], "gmgn")
        self.assertEqual(flow["sell_tx"], 1)

    def test_price_passthrough_to_holders(self):
        """price_usd diteruskan dari enrich_rows ke fetch_holders."""
        rows = [{"ca": "MINT", "symbol": "TST", "mc": 1000, "price": 0.05}]
        with mock.patch.object(sa, "analyze_token") as mock_analyze:
            mock_analyze.return_value = {"ca": "MINT", "symbol": "TST"}
            sa.enrich_rows(rows, max_wallets=10, max_trade_pages=1)
        # Cek price_usd diteruskan
        call_kwargs = mock_analyze.call_args[1]
        self.assertAlmostEqual(call_kwargs.get("price_usd"), 0.05)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
