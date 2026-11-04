# -*- coding: utf-8 -*-
"""Kolom info **Total IL** 12H / 4H / 1H di sebelah Fee-IL (2026-11-04).

Permintaan user: kolom baru hanya informasi. API Meteora tidak punya window
6 jam, jadi 4 jam dipakai (disetujui user). Semua tes offline: HTTP di-mock.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import meteora_screener as ms  # noqa: E402

OLD_POOL_MS = 1_700_000_000_000
NOW_MS = 1_800_000_000_000
YOUNG_MS = NOW_MS - 2 * 3600 * 1000  # dibuat 2 jam lalu


def _api_pool(address, change, created=OLD_POOL_MS):
    return {"pool_address": address, "pool_price_change_pct": change,
            "pool_created_at": created}


class FetchPoolPriceChangeTest(unittest.TestCase):
    def test_query_per_mint_dan_timeframe_dikirim(self):
        with patch.object(ms, "_http_get", return_value={"data": []}) as get:
            ms.fetch_pool_price_change("MintX", "12h", timeout=7)
        url, params = get.call_args[0][0], get.call_args[0][1]
        self.assertEqual(url, ms.POOLS_URL)
        self.assertEqual(params["query"], "MintX")
        self.assertEqual(params["timeframe"], "12h")
        self.assertEqual(get.call_args[1]["timeout"], 7)

    def test_petakan_per_pool_address(self):
        payload = {"data": [_api_pool("PoolA", -34.5), _api_pool("PoolB", 10.0),
                            "bukan dict"]}
        with patch.object(ms, "_http_get", return_value=payload):
            out = ms.fetch_pool_price_change("MintX", "1h")
        self.assertEqual(set(out), {"PoolA", "PoolB"})
        self.assertEqual(out["PoolA"]["price_change_pct"], -34.5)
        self.assertEqual(out["PoolB"]["price_change_pct"], 10.0)

    def test_payload_rusak_jadi_kosong(self):
        with patch.object(ms, "_http_get", return_value={"data": None}):
            self.assertEqual(ms.fetch_pool_price_change("MintX", "4h"), {})


class AttachIlWindowsTest(unittest.TestCase):
    def _run(self, responses, rows, now_ms=NOW_MS):
        def fake(ca, window, *, timeout=25):
            value = responses[(ca, window)]
            if isinstance(value, Exception):
                raise value
            return value
        with patch.object(ms, "fetch_pool_price_change", side_effect=fake):
            return ms.attach_il_windows(rows, workers=2, now_ms=now_ms)

    def test_il_per_window_dari_perubahan_harga_pool(self):
        rows = [{"ca": "MintX", "pool_address": "PoolA",
                 "price_change_pct": -57.17, "pool_created_at": OLD_POOL_MS}]
        responses = {
            ("MintX", "12h"): {"PoolA": {"price_change_pct": 100.0,
                                         "pool_created_at": OLD_POOL_MS}},
            ("MintX", "4h"): {"PoolA": {"price_change_pct": -50.0,
                                        "pool_created_at": OLD_POOL_MS}},
            ("MintX", "1h"): {"PoolA": {"price_change_pct": 0.0,
                                        "pool_created_at": OLD_POOL_MS}},
        }
        failed = self._run(responses, rows)
        self.assertEqual(failed, 0)
        windows = rows[0]["il_windows"]
        self.assertAlmostEqual(windows["12h"], -5.719, places=2)
        self.assertAlmostEqual(windows["4h"], -5.719, places=2)
        self.assertAlmostEqual(windows["1h"], 0.0, places=9)

    def test_pool_tidak_ditemukan_atau_belum_terukur_jadi_none(self):
        rows = [{"ca": "MintX", "pool_address": "PoolA",
                 "price_change_pct": -10.0, "pool_created_at": YOUNG_MS}]
        responses = {
            ("MintX", "12h"): {"PoolOther": {"price_change_pct": -10.0,
                                             "pool_created_at": OLD_POOL_MS}},
            # 0% pada pool < 24 jam = belum terukur (aturan row_il_pct).
            ("MintX", "4h"): {"PoolA": {"price_change_pct": 0.0,
                                        "pool_created_at": YOUNG_MS}},
            ("MintX", "1h"): {"PoolA": {"price_change_pct": -20.0,
                                        "pool_created_at": YOUNG_MS}},
        }
        failed = self._run(responses, rows)
        self.assertEqual(failed, 0)  # pool tidak ada bukan kegagalan request
        self.assertIsNone(rows[0]["il_windows"]["12h"])
        self.assertIsNone(rows[0]["il_windows"]["4h"])
        self.assertLess(rows[0]["il_windows"]["1h"], 0)

    def test_request_gagal_dihitung_dan_tidak_menjatuhkan_baris(self):
        rows = [{"ca": "MintX", "pool_address": "PoolA"}]
        responses = {
            ("MintX", "12h"): RuntimeError("HTTP 502"),
            ("MintX", "4h"): {"PoolA": {"price_change_pct": -3.0,
                                        "pool_created_at": OLD_POOL_MS}},
            ("MintX", "1h"): {"PoolA": {"price_change_pct": -3.0,
                                        "pool_created_at": OLD_POOL_MS}},
        }
        failed = self._run(responses, rows)
        self.assertEqual(failed, 1)
        self.assertIsNone(rows[0]["il_windows"]["12h"])
        self.assertIsNotNone(rows[0]["il_windows"]["4h"])

    def test_mint_sama_hanya_satu_request_per_timeframe(self):
        rows = [{"ca": "MintX", "pool_address": "PoolA"},
                {"ca": "MintX", "pool_address": "PoolB"}]
        calls = []

        def fake(ca, window, *, timeout=25):
            calls.append((ca, window))
            return {"PoolA": {"price_change_pct": -1.0,
                              "pool_created_at": OLD_POOL_MS},
                    "PoolB": {"price_change_pct": -2.0,
                              "pool_created_at": OLD_POOL_MS}}
        with patch.object(ms, "fetch_pool_price_change", side_effect=fake):
            ms.attach_il_windows(rows, workers=2, now_ms=NOW_MS)
        self.assertEqual(sorted(calls),
                         sorted([("MintX", w) for w in ms.IL_INFO_WINDOWS]))
        self.assertNotEqual(rows[0]["il_windows"]["1h"],
                            rows[1]["il_windows"]["1h"])


class InfoOnlyTest(unittest.TestCase):
    def test_il_windows_tidak_mengubah_saringan_fee_il(self):
        row = {"ca": "MintX", "pool_address": "PoolA",
               "fee_active_tvl_ratio": 20.0, "price_change_pct": 0.0,
               "pool_created_at": OLD_POOL_MS}
        before = ms.row_fee_il_gap(dict(row), now_ms=NOW_MS)
        row["il_windows"] = {"12h": -90.0, "4h": -90.0, "1h": -90.0}
        self.assertEqual(ms.row_fee_il_gap(row, now_ms=NOW_MS), before)

    def test_scan_default_tidak_memanggil_il_windows(self):
        with patch.object(ms, "attach_il_windows") as attach:
            with patch.object(ms, "fetch_best_pools", return_value=[]):
                ms.scan_best_lane("24h", rugcheck=False, gmgn=False,
                                  bundler=False, tax=False)
        attach.assert_not_called()


class ColumnOrderTest(unittest.TestCase):
    def test_total_il_tepat_di_kanan_fee_il(self):
        import best_pool_ui as bp
        titles = bp._lane_titles("24h", show_tax_dividend=True)
        self.assertEqual(titles[3], "Fee-IL")
        self.assertEqual(titles[4], "Total IL")
        self.assertEqual(len(titles), len(bp._col_spec(show_tax_dividend=True)))
        self.assertEqual(titles[bp.POOL_COL_INDEX], "Pool")
        self.assertEqual(titles[bp.TAX_DIVIDEND_COL_INDEX], "TAX/DIVIDEND")

    def test_sel_total_il_menampilkan_tiga_window(self):
        import best_pool_ui as bp
        row = {"ca": "MintX", "pool_address": "PoolA",
               "fee_active_tvl_ratio": 20.0, "price_change_pct": -10.0,
               "pool_created_at": OLD_POOL_MS,
               "il_windows": {"12h": -5.72, "4h": None, "1h": -0.11}}
        value, sub, tip = bp._total_il_cell(row)
        self.assertIn("12H -5.72%", value)
        self.assertIn("4H —", sub)
        self.assertIn("1H -0.11%", sub)
        self.assertIn("tidak menyaring", tip)


if __name__ == "__main__":
    unittest.main()
