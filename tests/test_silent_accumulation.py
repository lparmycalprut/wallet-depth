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
    def test_aggregates_net_and_accumulators(self):
        now = 1_800_000_000
        swaps = [
            ("buy", 1.0, now - 3600, "A", 0.01, 100.0, []),
            ("buy", 1.0, now - 1800, "B", 0.011, 110.0, []),
            ("sell", 0.5, now - 900, "A", 0.012, 50.0, []),
            ("sell", 2.0, now - 600, "C", 0.012, 200.0, ["mev"]),
            ("buy", 1.0, now - 60, "D", 0.013, 130.0, []),
        ]
        with mock.patch("cvd.fetch_gmgn_swaps", return_value=(swaps, "s", 0, True)):
            flow = sa.fetch_12h_flow("CA", now_ts=now, max_pages=2)
        self.assertEqual(flow["buy_tx"], 3)
        self.assertEqual(flow["sell_tx"], 2)
        self.assertAlmostEqual(flow["net_usd"], 90.0, places=2)
        self.assertEqual(flow["accumulators"], 3)  # A net +50, B, D
        self.assertEqual(flow["distributors"], 1)
        self.assertAlmostEqual(flow["bot_share"], 200 / 590, places=3)
        self.assertAlmostEqual(flow["price_chg_pct"],
                               (0.013 / 0.01 - 1) * 100, places=2)

    def test_out_of_window_trades_are_filtered(self):
        now = 1_800_000_000
        swaps = [("buy", 1.0, now - 13 * 3600, "OLD", 0.01, 100.0, []),
                 ("buy", 1.0, now - 60, "NEW", 0.011, 110.0, [])]
        with mock.patch("cvd.fetch_gmgn_swaps", return_value=(swaps, "s", 0, False)):
            flow = sa.fetch_12h_flow("CA", now_ts=now, max_pages=1)
        self.assertEqual(flow["buy_tx"], 1)
        self.assertEqual(flow["wallets"], 1)


class EnrichRowsTest(unittest.TestCase):
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
