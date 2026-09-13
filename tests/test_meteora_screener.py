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


def _sort_row(symbol, pct, ratio, *, tvl=20_000.0, wallets=80, fetched=200):
    """Baris pool untuk uji urutan.

    ``ratio`` = ``volume_active_tvl_ratio`` (angka API Meteora, persen) —
    kunci urut **pertama** sejak 2026-09-13; ``wallets=None`` = data holder
    gagal (tanpa angka dust).
    """
    analysis = None
    if wallets is not None:
        analysis = {"holders": {"total_fetched": fetched,
                                "wallets_analyzed": wallets,
                                "real_count": wallets, "dust_count": 2,
                                "dust_pct_mc": pct}}
    return {"ca": symbol * 4, "symbol": symbol, "pool_address": "P" + symbol,
            "tvl": tvl, "mc": 1_000_000.0, "dust_pct_mc": pct,
            "volume_active_tvl_ratio": ratio,
            "in_24h": True, "in_1h": False, "analysis": analysis}


class SortRowsTest(unittest.TestCase):
    """Listing Scan Meteora: 🏆 BEST POOL dulu, lalu rasio volume/active TVL.

    Permintaan user 2026-09-13: *"sort pertama adalah dari volume / active tvl
    yang paling besar dulu, lalu dari %dust yang paling kecil"*. Badge 🏆
    (permintaan 2026-09-08) tetap di urutan teratas — kunci urut pertama di
    dalam kelompoknya yang berubah: rasio ``volume_active_tvl_ratio`` (angka
    API Meteora, bukan hitungan sendiri) menggantikan TVL sebagai tie-break.
    """

    def _rows(self):
        # Sengaja diacak seperti urutan mentah API.
        return [
            _sort_row("THIN", 0.01, 9.0, tvl=4_000.0),   # TVL < 10K → bukan best
            _sort_row("BEST2", 0.05, 3.0, tvl=12_000.0),
            _sort_row("NODATA", None, 2.0, tvl=90_000.0, wallets=None),
            _sort_row("BEST1", 0.01, 1.5, tvl=20_000.0),  # dust terkecil → juara
            _sort_row("BOGUS", 0.0, 7.0, tvl=50_000.0, wallets=0, fetched=0),
            _sort_row("BEST3", 0.05, 5.0, tvl=80_000.0),  # dust seri → rasio menang
        ]

    def _rows_by_symbol(self):
        return {row["symbol"]: row for row in self._rows()}

    def test_best_pool_naik_ke_atas(self):
        out = ms.sort_rows(self._rows())
        flags = [ms.row_flag(row)["best"] for row in out]
        self.assertEqual(flags, sorted(flags, reverse=True))
        self.assertEqual([r["symbol"] for r in out][:3],
                         ["BEST1", "BEST3", "BEST2"])

    def test_dust_terkecil_dulu_lalu_rasio_volume_active_tvl(self):
        out = [r["symbol"] for r in ms.sort_rows(self._rows())]
        # BEST1 (0,01%) < BEST3/BEST2 (0,05%); BEST3 rasio 5× > BEST2 3×.
        self.assertLess(out.index("BEST1"), out.index("BEST3"))
        self.assertLess(out.index("BEST3"), out.index("BEST2"))

    def test_rasio_volume_active_tvl_mengalahkan_tvl(self):
        """TVL besar tidak lagi menang: rasionya yang dilihat (2026-09-13)."""
        rows = [_sort_row("TEBAL", 0.02, 1.0, tvl=900_000.0),
                _sort_row("RAMAI", 0.02, 40.0, tvl=15_000.0)]
        self.assertEqual([r["symbol"] for r in ms.sort_rows(rows)],
                         ["RAMAI", "TEBAL"])

    def test_baris_tanpa_data_dust_paling_bawah(self):
        out = [r["symbol"] for r in ms.sort_rows(self._rows())]
        # BOGUS ikut ke bawah: dust 0,0 dari scan holder 0 wallet BUKAN "pool
        # bersih", melainkan tidak ada bukti — diperlakukan sama seperti baris
        # tanpa angka (NODATA). Di dalam kelompok tanpa bukti rasio
        # volume/active TVL terbesar yang lebih dulu, jadi BOGUS (7×) di atas
        # NODATA (2×) walau TVL-nya lebih kecil.
        self.assertEqual(out[-2:], ["BOGUS", "NODATA"])
        self.assertIsNone(ms.row_dust_pct(
            self._rows_by_symbol()["BOGUS"]))
        self.assertIsNone(ms.row_dust_pct(
            self._rows_by_symbol()["NODATA"]))

    def test_rasio_dipakai_apa_adanya_dan_ada_fallback(self):
        self.assertAlmostEqual(
            ms.row_vol_tvl_ratio({"volume_active_tvl_ratio": 1646.6332}),
            1646.6332)
        # Baris lama (hasil scan sebelum field ini ada): hitung ulang.
        self.assertAlmostEqual(
            ms.row_vol_tvl_ratio({"volume": 300_000.0,
                                  "active_tvl": 100_000.0}), 300.0)
        self.assertIsNone(ms.row_vol_tvl_ratio({"volume": 1.0}))
        self.assertIsNone(ms.row_vol_tvl_ratio({}))

    def test_row_dari_pool_membawa_rasio_meteora(self):
        pool = _pool("P1", "M1")
        pool["volume_active_tvl_ratio"] = 1646.63
        row = ms.merge_pools([pool], [])[0]
        self.assertAlmostEqual(row["volume_active_tvl_ratio"], 1646.63)
        self.assertAlmostEqual(ms.row_vol_tvl_ratio(row), 1646.63)

    def test_scan_holder_gagal_bukan_angka_nol(self):
        """Akar "0,000% di Scan Meteora, beda dengan Scan Holder" (2026-09-13).

        Provider holder mati → 0 wallet → ``classify_holders`` memang
        mengembalikan ``dust_pct_mc = 0.0`` (nol aritmatik dari daftar kosong).
        Kartu tidak boleh menampilkannya sebagai angka: tanpa bukti = ``None``,
        lalu digugurkan saringan / tidak dapat BEST POOL.
        """
        bogus = self._rows_by_symbol()["BOGUS"]
        self.assertFalse(ms.row_dust_ok(bogus))
        self.assertFalse(ms.row_best_pool(bogus))
        self.assertFalse(ms.row_flag(bogus)["best"])
        # Angka dust yang BENAR (scan lengkap) tetap lolos — guardnya bukti,
        # bukan nilainya.
        self.assertTrue(ms.row_dust_ok(self._rows_by_symbol()["BEST1"]))

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
        self.assertTrue(ms.row_flag(_sort_row("A", 0.01, 5.0))["best"])
        # holder gagal (0 wallet) → bukan best walau dust 0
        self.assertFalse(ms.row_flag(
            _sort_row("B", 0.0, 30.0, wallets=0, fetched=0))["best"])
        # TVL < 10K → bukan best (rasio sebesar apa pun tidak menolong)
        self.assertFalse(ms.row_flag(
            _sort_row("C", 0.01, 400.0, tvl=4_000.0))["best"])


class DropQuoteRowsTest(unittest.TestCase):
    """Pool tanpa sisi memecoin tidak di-analisa (2026-09-13).

    ``base_token()`` jatuh ke ``token_x`` bila KEDUA sisi pool adalah token
    quote, jadi listing USDC-USDT / SOL-USDC "berhak" ikut di-scan: mint yang
    dianalisa = SOL/USDC, MC pembagi = MC SOL → dust ≈ 0,000% → selalu paling
    "bersih" di listing dan dapat 🏆 BEST POOL. Barisnya dibuang sebelum
    fetch holder.
    """

    def _row(self, mint, **kw):
        row = {"ca": mint, "symbol": "X", "pool_address": "P1", "mc": 1.0}
        row.update(kw)
        return row

    def test_pool_kedua_sisi_quote_dibuang(self):
        pool = {"pool_address": "P1", "token_x": _token(SOL, "SOL"),
                "token_y": _token(ms.USDC_MINT, "USDC")}
        rows = ms.merge_pools([pool], [])
        self.assertEqual(rows[0]["ca"], SOL)  # fallback token_x
        kept, dropped = ms.drop_quote_rows(rows)
        self.assertEqual((kept, dropped), ([], 1))

    def test_mint_kosong_dibuang(self):
        kept, dropped = ms.drop_quote_rows([self._row("")])
        self.assertEqual((kept, dropped), ([], 1))

    def test_pool_memecoin_tetap_ikut(self):
        rows = [self._row("MintMemecoin"),
                self._row(ms.USDT_MINT, symbol="USDT")]
        kept, dropped = ms.drop_quote_rows(rows)
        self.assertEqual([r["ca"] for r in kept], ["MintMemecoin"])
        self.assertEqual(dropped, 1)

    def test_alasan_ditulis_di_unanalysable_row(self):
        self.assertIn("quote", ms.unanalysable_row(self._row(SOL)))
        self.assertEqual(ms.unanalysable_row(self._row("MintAA")), "")

    def test_scan_meteora_melaporkan_pool_quote_dilewati(self):
        rows = [self._row("MintMemecoin"), self._row(SOL, symbol="SOL")]
        with mock.patch.object(ms, "fetch_listing", return_value=(rows, "")), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=lambda r, **k: r) as enrich:
            result = ms.scan_meteora()
        self.assertEqual(result["skipped_quote"], 1)
        self.assertEqual(result["fetched"], 2)      # listing API utuh
        self.assertEqual([r["ca"] for r in result["rows"]], ["MintMemecoin"])
        # holder tidak pernah di-fetch untuk mint quote (hemat kuota Helius)
        self.assertEqual([r["ca"] for r in enrich.call_args[0][0]],
                         ["MintMemecoin"])

    def test_scan_best_meteora_membuang_pool_quote(self):
        pools = [{"pool_address": "P1",
                  "token_x": _token(SOL, "SOL"),
                  "token_y": _token(ms.USDC_MINT, "USDC"),
                  "tvl": 1e6, "active_tvl": 1e6, "fee_active_tvl_ratio": 9,
                  "volume": 5e6, "fee_pct": 5.0, "volatility": 9.0},
                 {"pool_address": "P2",
                  "token_x": _token("MintMemecoin", "MEME"),
                  "token_y": _token(SOL, "SOL"),
                  "tvl": 1e6, "active_tvl": 1e6, "fee_active_tvl_ratio": 9,
                  "volume": 5e6, "fee_pct": 5.0, "volatility": 9.0}]
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=lambda r, **k: r) as enrich:
            result = ms.scan_best_meteora()
        self.assertEqual(result["skipped_quote"], 1)
        self.assertEqual(result["fetched"], 2)
        self.assertEqual([r["pool_address"] for r in enrich.call_args[0][0]],
                         ["P2"])


class EnrichPoolsProofTest(unittest.TestCase):
    """Scan holder tanpa bukti tidak menulis angka dust (2026-09-13)."""

    def _pool_row(self, ca="MintAA", **kw):
        row = {"ca": ca, "symbol": "AA", "pool_address": "P1",
               "mc": 50_000_000.0, "price": 0.001, "tvl": 20_000.0,
               "analysis": None}
        row.update(kw)
        return row

    def _run(self, analysis):
        with mock.patch("holder_analysis.analyze_token",
                        side_effect=lambda *a, **k: analysis), \
                mock.patch("holder_history.load_holder_history",
                           return_value={"tokens": {}}), \
                mock.patch("holder_history.ingest_many", return_value=None):
            return ms.enrich_pools([self._pool_row()])

    def test_fetch_gagal_nol_wallet_bukan_angka_nol(self):
        failed = {"holders": {"dust_pct_mc": 0.0, "dust_count": 0,
                              "real_count": 0, "total_fetched": 0,
                              "wallets_analyzed": 0},
                  "marketcap": 12_000_000.0}
        row = self._run(failed)[0]
        self.assertIsNone(row["dust_pct_mc"])
        self.assertIsNone(row["dust_count"])
        self.assertFalse(row["holders_proof"])
        self.assertIn("0 holder", row["holders_note"])
        self.assertIsNone(ms.row_dust_pct(row))

    def test_scan_terpotong_ditangguhkan(self):
        cut = {"holders": {"dust_pct_mc": 0.0, "dust_count": 0,
                           "real_count": 9_000, "total_fetched": 9_000,
                           "wallets_analyzed": 9_000, "truncated": True},
               "marketcap": 12_000_000.0}
        row = self._run(cut)[0]
        self.assertIsNone(row["dust_pct_mc"])
        self.assertIn("terpotong", row["holders_note"])

    def test_sampel_pendek_ditolak(self):
        short = {"holders": {"dust_pct_mc": 0.01, "dust_count": 2,
                             "real_count": 16, "total_fetched": 18,
                             "wallets_analyzed": 18},
                 "marketcap": 12_000_000.0}
        row = self._run(short)[0]
        self.assertIsNone(row["dust_pct_mc"])
        self.assertIn("sampel", row["holders_note"])

    def test_scan_lengkap_mempertahankan_angka(self):
        good = {"holders": {"dust_pct_mc": 0.021, "dust_count": 640,
                            "real_count": 1_100, "total_fetched": 1_740,
                            "wallets_analyzed": 1_740},
                "marketcap": 12_000_000.0}
        row = self._run(good)[0]
        self.assertEqual(row["dust_pct_mc"], 0.021)
        self.assertEqual(row["dust_count"], 640)
        self.assertTrue(row["holders_proof"])
        self.assertEqual(row["holders_note"], "")

    def test_mc_barik_ikut_pembagi_yang_dipakai(self):
        """Kolom MC = MC yang dipakai menghitung dust, bukan MC listing."""
        good = {"holders": {"dust_pct_mc": 0.021, "dust_count": 640,
                            "real_count": 1_100, "total_fetched": 1_740,
                            "wallets_analyzed": 1_740},
                "marketcap": 12_000_000.0}
        row = self._run(good)[0]
        self.assertEqual(row["mc"], 12_000_000.0)
        # Tanpa angka market dari analisis, MC listing tetap dipakai.
        self.assertEqual(self._run({"holders": {}})[0]["mc"],
                         50_000_000.0)

    def test_ingest_hanya_titik_yang_ada_bukti(self):
        """Titik 0,00% dari fetch gagal tidak menimpa titik cron yang benar."""
        failed = {"holders": {"dust_pct_mc": 0.0, "dust_count": 0,
                               "real_count": 0, "total_fetched": 0,
                               "wallets_analyzed": 0},
                  "marketcap": 12_000_000.0}
        with mock.patch("holder_analysis.analyze_token",
                        side_effect=lambda *a, **k: failed), \
                mock.patch("holder_history.load_holder_history",
                           return_value={"tokens": {}}), \
                mock.patch("holder_history.ingest_many") as ingest:
            ms.enrich_pools([self._pool_row()])
        ingest.assert_not_called()

        good = {"holders": {"dust_pct_mc": 0.021, "dust_count": 640,
                            "real_count": 1_100, "total_fetched": 1_740,
                            "wallets_analyzed": 1_740},
                "marketcap": 12_000_000.0}
        with mock.patch("holder_analysis.analyze_token",
                        side_effect=lambda *a, **k: good), \
                mock.patch("holder_history.load_holder_history",
                           return_value={"tokens": {}}), \
                mock.patch("holder_history.ingest_many") as ingest:
            ms.enrich_pools([self._pool_row()])
        self.assertEqual(list(ingest.call_args[0][0]), ["MintAA"])

    def test_mint_quote_tidak_dianalisa(self):
        row = self._pool_row(ca=SOL)
        with mock.patch("holder_analysis.analyze_token") as analyze, \
                mock.patch("holder_history.load_holder_history",
                           return_value={"tokens": {}}), \
                mock.patch("holder_history.ingest_many", return_value=None):
            out = ms.enrich_pools([row])[0]
        analyze.assert_not_called()
        self.assertIsNone(out["dust_pct_mc"])


if __name__ == "__main__":
    unittest.main()
