"""Coverage listing Meteora 24h/1h + filter dust > 0,1% MC."""
from __future__ import annotations

import unittest
from unittest import mock

import meteora_screener as ms


SOL = ms.SOL_MINT


def _token(addr, symbol="TOK", mc=100_000):
    return {"address": addr, "symbol": symbol, "name": symbol,
            "market_cap": mc, "fdv": mc, "price": 0.01, "holders": 10}


def _pool(addr, mint, name="TOK-SOL"):
    return {
        "pool_address": addr, "name": name, "pool_type": "dlmm",
        "token_x": _token(mint, name.split("-")[0]),
        "token_y": _token(SOL, "SOL", mc=1e9),
        "tvl": 2000, "active_tvl": 1500, "fee_active_tvl_ratio": 300,
        "volume": 50_000, "fee_pct": 1.0,
    }


class BaseTokenTest(unittest.TestCase):
    def test_picks_non_quote_side(self):
        pool = _pool("P1", "MintAAA")
        self.assertEqual(ms.base_token(pool)["address"], "MintAAA")

    def test_falls_back_when_both_quote(self):
        pool = {
            "token_x": _token(SOL, "SOL"),
            "token_y": _token(ms.USDC_MINT, "USDC"),
        }
        self.assertEqual(ms.base_token(pool)["address"], SOL)


class MergePoolsTest(unittest.TestCase):
    def test_24h_still_shown_when_also_in_1h(self):
        p24 = [_pool("P1", "M1"), _pool("P2", "M2")]
        p1h = [_pool("P1", "M1"), _pool("P3", "M3")]
        rows = ms.merge_pools(p24, p1h)
        by = {r["pool_address"]: r for r in rows}
        self.assertEqual(set(by), {"P1", "P2", "P3"})
        self.assertTrue(by["P1"]["in_24h"] and by["P1"]["in_1h"])
        self.assertTrue(by["P2"]["in_24h"] and not by["P2"]["in_1h"])
        self.assertTrue(by["P3"]["in_1h"] and not by["P3"]["in_24h"])
        self.assertEqual(rows[0]["pool_address"], "P1")

    def test_filter_query_matches_ui(self):
        self.assertEqual(
            ms.filter_by(fee_ratio_min=250),
            "pool_type=dlmm&&active_tvl>=1000&&fee_active_tvl_ratio>=250")
        self.assertEqual(
            ms.filter_by(fee_ratio_min=1),
            "pool_type=dlmm&&active_tvl>=1000&&fee_active_tvl_ratio>=1")


class HideDustTest(unittest.TestCase):
    def test_hides_above_01_percent_keeps_rest(self):
        # Sejak 2026-09-07: hanya dust ≤ 0,1% MC yang tampil. BAHAYA (2,4%),
        # HATI-HATI (0,5%) dan AMAN-tapi->0,1% (0,2%) sama-sama dibuang.
        rows = [
            {"ca": "A", "dust_pct_mc": 2.4,
             "analysis": {"holders": {"dust_pct_mc": 2.4}}},
            {"ca": "B", "dust_pct_mc": 0.5,
             "analysis": {"holders": {"dust_pct_mc": 0.5}}},
            {"ca": "B2", "dust_pct_mc": 0.2,
             "analysis": {"holders": {"dust_pct_mc": 0.2}}},
            {"ca": "C", "dust_pct_mc": None, "analysis": None},
            {"ca": "D", "dust_pct_mc": 0.1,
             "analysis": {"holders": {"dust_pct_mc": 0.1}}},
            {"ca": "E", "dust_pct_mc": 0.03,
             "analysis": {"holders": {"dust_pct_mc": 0.03}}},
        ]
        kept, hidden = ms.hide_dust_limit(rows)
        self.assertEqual(hidden, 3)
        self.assertEqual([r["ca"] for r in kept], ["C", "D", "E"])

    def test_analysis_pct_wins_over_row_pct(self):
        rows = [{"ca": "A", "dust_pct_mc": 0.05,
                 "analysis": {"holders": {"dust_pct_mc": 0.8}}}]
        kept, hidden = ms.hide_dust_limit(rows)
        self.assertEqual((len(kept), hidden), (0, 1))

    def test_scan_result_reports_hide_pct(self):
        with mock.patch.object(ms, "fetch_listing", return_value=([], "")):
            result = ms.scan_meteora()
        self.assertEqual(result["hide_pct"], ms.DUST_SCAN_HIDE_PCT)
        self.assertEqual(result["hide_pct"], 0.1)


class FetchListingTest(unittest.TestCase):
    def test_fetch_listing_merges_both_timeframes(self):
        with mock.patch.object(ms, "fetch_pools", side_effect=[
            [_pool("P1", "M1")],
            [_pool("P1", "M1")],
        ]):
            rows, error = ms.fetch_listing()
        self.assertEqual(error, "")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["in_24h"] and rows[0]["in_1h"])


def _sort_row(symbol, pct, tvl, *, wallets=80, fetched=200):
    """Baris pool untuk uji urutan; ``wallets=None`` = data holder gagal."""
    analysis = None
    if wallets is not None:
        analysis = {"holders": {"total_fetched": fetched,
                                "wallets_analyzed": wallets,
                                "real_count": wallets, "dust_count": 2,
                                "dust_pct_mc": pct}}
    return {"ca": symbol * 4, "symbol": symbol, "pool_address": "P" + symbol,
            "tvl": tvl, "mc": 1_000_000.0, "dust_pct_mc": pct,
            "in_24h": True, "in_1h": False, "analysis": analysis}


class SortRowsTest(unittest.TestCase):
    """Listing Scan Meteora: 🏆 BEST POOL wajib di urutan teratas.

    Permintaan user 2026-09-08. Sebelumnya baris tampil apa adanya mengikuti
    urutan API Meteora sehingga pool terbaik terselip di tengah.
    """

    def _rows(self):
        # Sengaja diacak seperti urutan mentah API.
        return [
            _sort_row("THIN", 0.01, 4_000.0),         # TVL < 10K → bukan best
            _sort_row("BEST2", 0.05, 12_000.0),
            _sort_row("NODATA", None, 90_000.0, wallets=None),
            _sort_row("BEST1", 0.01, 20_000.0),       # dust terkecil → juara
            _sort_row("BOGUS", 0.0, 50_000.0, wallets=0, fetched=0),
            _sort_row("BEST3", 0.05, 80_000.0),       # dust seri → TVL menang
        ]

    def test_best_pool_naik_ke_atas(self):
        out = ms.sort_rows(self._rows())
        flags = [ms.row_flag(row)["best"] for row in out]
        self.assertEqual(flags, sorted(flags, reverse=True))
        self.assertEqual([r["symbol"] for r in out][:3],
                         ["BEST1", "BEST3", "BEST2"])

    def test_dust_terkecil_dulu_lalu_tvl_terbesar(self):
        out = [r["symbol"] for r in ms.sort_rows(self._rows())]
        # BEST1 (0,01%) < BEST3/BEST2 (0,05%); BEST3 TVL 80K > BEST2 12K.
        self.assertLess(out.index("BEST1"), out.index("BEST3"))
        self.assertLess(out.index("BEST3"), out.index("BEST2"))

    def test_baris_tanpa_data_dust_paling_bawah(self):
        out = [r["symbol"] for r in ms.sort_rows(self._rows())]
        self.assertEqual(out[-1], "NODATA")

    def test_urutan_deterministik(self):
        rows = self._rows()
        first = [r["symbol"] for r in ms.sort_rows(rows)]
        second = [r["symbol"] for r in ms.sort_rows(list(reversed(rows)))]
        self.assertEqual(first, second)

    def test_sort_rows_tidak_mengubah_list_asli(self):
        rows = self._rows()
        before = [r["symbol"] for r in rows]
        ms.sort_rows(rows)
        self.assertEqual([r["symbol"] for r in rows], before)

    def test_input_kosong_aman(self):
        self.assertEqual(ms.sort_rows([]), [])
        self.assertEqual(ms.sort_rows(None), [])

    def test_scan_meteora_mengurutkan_dan_menghitung_best(self):
        rows = self._rows()
        with mock.patch.object(ms, "fetch_listing", return_value=(rows, "")), \
                mock.patch.object(ms, "enrich_pools", side_effect=lambda r, **k: r):
            result = ms.scan_meteora()
        self.assertEqual([r["symbol"] for r in result["rows"]][:3],
                         ["BEST1", "BEST3", "BEST2"])
        self.assertEqual(result["best_count"], 3)


class RowFlagTest(unittest.TestCase):
    def test_row_dust_pct_analysis_menang(self):
        row = {"dust_pct_mc": 0.05,
               "analysis": {"holders": {"dust_pct_mc": 0.8}}}
        self.assertEqual(ms.row_dust_pct(row), 0.8)

    def test_row_dust_pct_fallback_ke_field_baris(self):
        self.assertEqual(ms.row_dust_pct({"dust_pct_mc": 0.02}), 0.02)
        self.assertIsNone(ms.row_dust_pct({}))
        self.assertIsNone(ms.row_dust_pct(None))

    def test_row_flag_butuh_holder_valid_dan_tvl(self):
        self.assertTrue(ms.row_flag(_sort_row("A", 0.01, 20_000.0))["best"])
        # holder gagal (0 wallet) → bukan best walau dust 0
        self.assertFalse(ms.row_flag(
            _sort_row("B", 0.0, 50_000.0, wallets=0, fetched=0))["best"])
        # TVL < 10K → bukan best
        self.assertFalse(ms.row_flag(_sort_row("C", 0.01, 4_000.0))["best"])


if __name__ == "__main__":
    unittest.main()
