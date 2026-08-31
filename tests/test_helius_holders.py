# -*- coding: utf-8 -*-
"""Coverage untuk scan khusus holder via Helius (helius_holders)."""
from __future__ import annotations

import unittest
from unittest import mock

import matplotlib.pyplot as plt

import helius_holders as hh


class ScanTokenHoldersTest(unittest.TestCase):
    def test_scan_uses_helius_and_builds_depth(self):
        """Scan mengambil market, fetch Helius, lalu menghitung depth."""
        market = {"symbol": "TST", "price_usd": 0.01, "marketcap": 100_000}
        snapshot = {
            "holders": [
                {"address": "A", "usd_value": 500.0, "is_wallet": True},
                {"address": "B", "usd_value": 5.0, "is_wallet": True},
                {"address": "POOL", "usd_value": 90_000.0, "is_wallet": False},
            ],
            "pages": 1, "fetched": 3, "truncated": False,
            "source": "helius",
        }

        with mock.patch("helius_holders.get_market", return_value=market):
            with mock.patch("helius_holders.get_helius_keys",
                            return_value=["KEY"]) as mock_keys:
                with mock.patch(
                        "helius_holders.fetch_holders_helius",
                        return_value=snapshot) as mock_fetch:
                    with mock.patch("helius_holders.wallet_depth",
                                    wraps=hh.wallet_depth) as mock_depth:
                        result = hh.scan_token_holders("MINT")

        self.assertEqual(result["mint"], "MINT")
        self.assertEqual(result["symbol"], "TST")
        self.assertEqual(result["source"], "helius")
        self.assertFalse(result["no_helius_keys"])
        self.assertFalse(result["scan_failed"])
        # Helius dipaksa sebagai sumber
        self.assertIs(mock_fetch.call_args.args[0], "MINT")
        self.assertIn("price_usd", mock_fetch.call_args.kwargs)
        self.assertEqual(mock_fetch.call_args.kwargs["helius_keys"], ["KEY"])
        self.assertIn("depth", result)
        # bucket nilai USD dari wallet_depth
        by_label = {b["label"]: b for b in result["depth"]["buckets"]}
        self.assertEqual(by_label[">$0-$10"]["count"], 1)   # B
        self.assertEqual(by_label["$100-$1k"]["count"], 1)  # A
        self.assertEqual(by_label["$10k-$100k"]["count"], 1)  # POOL
        self.assertEqual(result["depth"]["holders_all"], 3)
        self.assertEqual(result["depth"]["holders_wallet"], 2)
        self.assertEqual(result["depth"]["pool_excluded"], 1)

    def test_no_helius_keys_flags_and_no_fetch(self):
        """Tanpa key Helius → scan_failed & no_helius_keys=True."""
        with mock.patch("helius_holders.get_market",
                        return_value={"price_usd": 0.01,
                                      "marketcap": 1000}):
            with mock.patch("helius_holders.get_helius_keys",
                            return_value=[]):
                with mock.patch("helius_holders.fetch_holders_helius") as mf:
                    result = hh.scan_token_holders("MINT")
        self.assertTrue(result["no_helius_keys"])
        self.assertTrue(result["scan_failed"])
        mf.assert_not_called()

    def test_market_failure_does_not_raise(self):
        """get_market error → market kosong, tetap tidak crash."""
        with mock.patch("helius_holders.get_market",
                        side_effect=RuntimeError("down")):
            with mock.patch("helius_holders.get_helius_keys",
                            return_value=[]):
                result = hh.scan_token_holders("MINT")
        self.assertEqual(result["market"], {})
        self.assertTrue(result["scan_failed"])


class DepthBarChartTest(unittest.TestCase):
    def test_chart_returns_figure_with_buckets(self):
        depth = {
            "buckets": [
                {"label": ">$0-$10", "count": 50, "value_usd": 100.0,
                 "pct_mc": 0.1},
                {"label": "$10-$100", "count": 10, "value_usd": 300.0,
                 "pct_mc": 0.3},
            ]
        }
        fig = hh.depth_bar_chart(depth, title="TST")
        self.assertIsNotNone(fig)
        self.assertEqual(len(fig.axes), 1)
        axis = fig.axes[0]
        self.assertEqual(axis.get_title(), "TST")
        self.assertEqual(axis.get_ylabel(), "Jumlah holder")
        # dua batang
        self.assertEqual(len(axis.patches), 2)
        plt.close(fig)

    def test_empty_depth_returns_none(self):
        self.assertIsNone(hh.depth_bar_chart({}, title="X"))
        self.assertIsNone(hh.depth_bar_chart({"buckets": []}, title="X"))

    def test_compact_formatting(self):
        self.assertEqual(hh._compact(0), "$0")
        self.assertEqual(hh._compact(1_500), "$1.5K")
        self.assertEqual(hh._compact(2_000_000), "$2.00M")
        self.assertEqual(hh._compact(None), "—")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
