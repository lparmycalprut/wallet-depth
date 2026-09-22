"""Coverage 🏆 Scan Best Pool Meteora (kriteria 2026-09-16: satu tombol 24H).

Permintaan user 2026-09-16 (batch ini): *"hapus scan 30 menit, kita sisakan
yang 24 jam saja"* + *"jika ada top 10 >= 20% jangan tampilkan"* + *"volatility
kurang dari 1 sembunyikan juga"* / *"volatility > 10 sembunyikan juga"* + *"scan
baru saya tambahkan jupiter safeguard untuk filter yang mungkin rug"* + *"kita
tambahkan kolom baru RugCheck dengan metode ini"* + *"kolom LPs … jika lebih
dari 100, kasih warna hijau"*. Yang di-pin di file ini:

- **satu tombol card**: ``best-pool-scan-24h`` saja (``best-pool-scan-30m``
  harus hilang); ``BEST_LANES == ("24h",)`` dan
  :func:`meteora_screener.normalize_best_lane` memetakan SEMUA alias lama
  (``30m``/``1h``/``both``) ke 24H, juga di :func:`fetch_best_pools` sehingga
  tidak ada jalur yang masih bisa menarik window 30 menit;
- **query API Best Pool** = ``pool_type=dlmm&&active_tvl>=50000``
  (``fee_pct>=2`` tetap DIHAPUS 2026-09-13). Filter server Jupiter safeguard
  yang dipasang 2026-09-16 **dimatikan default-nya** 2026-09-17 (membuang
  PAID diam-diam) — masih bisa diaktifkan dengan kwarg ``safeguard=True``.
  ``filter_by()`` regular scan/watchlist **tidak** ikut berubah;
- **saringan layar sebelum enrichment** (:func:`meteora_screener.row_best_gaps`):
  ``F/V >= BEST_FV_24H_MIN`` (5×, inklusif), volatility **1%–10%**
  (:data:`BEST_VOL_SHOW_MIN`/``BEST_VOL_SHOW_MAX``, inklusif di dua sisi), dan
  **Top10 < BEST_TOP10_MAX_PCT** (20%; tepat 20,0% ikut dibuang — batasnya di
  sisi buang). Di bawah itu → **langsung skip**, ``enrich_pools`` tidak pernah
  dipanggil (kuota Helius aman), barisnya masuk ``hidden_rows`` dengan alasan di
  ``best_gaps`` — **kecuali** volatility 0: dibuang penuh dari listing
  (2026-09-14 lanjutan), tidak dihitung di ``hidden_metric``, jumlahnya di
  ``dropped_volatility``;
- **kolom RugCheck** (baru): :func:`meteora_screener.scan_best_lane` menempel
  laporan rugchecker.cc ke baris yang LOLOS lewat :mod:`rugchecker`
  (``rugcheck=False`` untuk offline/test), dan kolomnya tidak pernah menyaring;
- urutan tiap tabel (2026-09-15): **Fee/TVL terbesar** → **F/V terbesar** →
  volume/active TVL → dust %MC terkecil; dust, volume 24 jam, tier fee dan LPs
  **bukan** saringan — dan tidak boleh dihidupkan balik;
- **tata letak kolom 2026-09-17** (13 kolom): Token, F/V, **Fee/TVL**, Volat,
  **Active Range**, **LPs** (permintaan user: *"Active Range kolom ini pindah ke
  kanan volat"* + *"kolom LPs pindah ke kanan active range setelah dipindah"*),
  Fee %, MC, A.TVL, Vol 24h, Top10, **RugCheck**, Pool — kolom **Dust %MC**
  dan **tombol ⭐ watchlist** dihapus 2026-09-17 (permintaan user: *"hapus
  kolom dust %"* + *"hapus tombol favorit / watchlist"*); kolom Pool kini
  memuat tombol 📋 **copy link HawkFi** (*"tambahkan copy link hawkfi
  dibagian scan"*), dan tiap kolom dibatasi **garis vertikal** lewat marker
  ``.bp-cols-next`` (*"batasi per kolom dengan garis naik turun"*); **LPs
  HIJAU** bila > 100 LP; sel volatility terbesar + F/V tertinggi + Fee/TVL
  tertinggi tabel utama tetap disorot **hijau tua menyala**
  (``TOP_HIGHLIGHT_COLOR``, seri ikut semua, tabel dilewati tidak ditandai);
- **penataan 2026-09-19** (permintaan user: *"hapus tentang bubblemap,
  sisakan hyperlink ke bubblemapnya saja"* + *"Kasih kolom baru dipaling kanan
  STRATEGY"* + *"agak perbesar tulisan table semuanya ya, tapi tidak
  mempengaruhi tampilan"*): kolom **Bubble Map** dihapus (tabel kembali 13
  kolom, enrichment Bubblemaps OFF default) dan yang tersisa hanya tautan 🫧
  ke ``v2.bubblemaps.io`` di kolom **Pool**; kolom **STRATEGY** baru di
  **paling kanan tabel utama saja** (tabel "▶ N pool dilewati" tetap 13
  kolom) dengan teks verbatim dari ambang likuiditas GMGN — > $500K
  ``hybird 7030, bidask 3070 - full range``, selain itu ``hybird 5050,
  bidask - full range``; ukuran huruf tabel (judul kolom + isi sel)
  diperbesar tanpa mengubah lebar kolom/tata letak;
- **penempatan sel 2026-09-21** (permintaan user: *"hybird 5050, bidask -
  full range — ini taruh di kolom strategy, bukan di pool"*): sel
  **STRATEGY** ditulis ke indeks kolomnya sendiri
  (``best_pool_ui.STRATEGY_COL_INDEX``, tepat di kanan ``POOL_COL_INDEX``) —
  versi awal mengirimnya lewat daftar ``cells`` yang dirender
  ``enumerate(cells, start=1)`` sampai ``POOL_COL_INDEX`` saja, sehingga teks
  strategi menumpuk di kolom **Pool** dan kolom **STRATEGY** kosong
  (:class:`StrategyColumnPlacementTest` memeriksa penempatan per indeks
  kolom lewat ``streamlit`` palsu).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scan_result_cache

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import best_pool_ui as bp
# Aturan teks kolom STRATEGY (2026-09-19) satu sumber di gmgn_liquidity, jadi
# tes UI + tes aturannya mengimpor modul yang sama.
import gmgn_liquidity as gl
import meteora_screener as ms

APP = str(Path(__file__).resolve().parent.parent / "app.py")
SOL = ms.SOL_MINT
QUERY = "pool_type=dlmm&&active_tvl>=50000"
# Jupiter safeguard (permintaan user 2026-09-16) — **dimatikan default-nya**
# 2026-09-17 karena filter server ini ternyata membuang token seperti PAID
# sebelum payload sampai ke client (lihat BEST_QUERY di bawah). Kwarg
# ``safeguard=True`` masih bisa dipakai caller yang ingin menyalakannya;
# stringnya di-pin supaya bila dipakai query tetap konsisten.
SAFEGUARD = ("base_token_has_critical_warnings=false&&"
             "quote_token_has_critical_warnings=false")
# Best query **default**: sama dengan regular scan — safeguard server tidak
# dipasang (bendera kritis sudah dilaporkan kolom RugCheck tanpa membuang
# baris; safeguard server membuang PAID diam-diam).
BEST_QUERY = QUERY
# Query dengan safeguard dihidupkan — masih tersedia lewat kwarg.
SAFEGUARD_QUERY = SAFEGUARD + "&&" + QUERY


def _token(addr, symbol="TOK", mc=1_000_000, top10=12.0):
    return {"address": addr, "symbol": symbol, "name": symbol,
            "market_cap": mc, "fdv": mc, "price": 0.01, "holders": 1200,
            "top_holders_pct": top10}


def _pool(addr="P1", mint="MintAAA", *, active_tvl=60_000, ratio=40.0,
          volatility=6.2, total_lps=88, fee_pct=2.0, volume=1_200_000,
          fee=24_000.0, volume_change_pct=12.5, top10=12.0):
    return {
        "pool_address": addr, "name": "TOK-SOL", "pool_type": "dlmm",
        "token_x": _token(mint, top10=top10),
        "token_y": _token(SOL, "SOL", mc=1e9, top10=0.5),
        "tvl": active_tvl * 1.1, "active_tvl": active_tvl,
        "fee_active_tvl_ratio": ratio, "volume": volume, "fee": fee,
        "volume_change_pct": volume_change_pct,
        "fee_pct": fee_pct, "volatility": volatility,
        "total_lps": total_lps,
    }


def _row(**over):
    # Default = baris 24H yang lolos ambang lane (F/V 40,0 ÷ 6,2 = 6,45× ≥ 5×)
    # dan punya bukti holder, supaya tiap tes cukup mengubah satu angka.
    row = {
        "pool_address": "P1", "ca": "MintAAA", "symbol": "AAA",
        "timeframe": "24h", "source": "24h",
        "mc": 1_000_000, "tvl": 66_000, "active_tvl": 60_000,
        "fee_active_tvl_ratio": 40.0, "volume": 1_200_000, "fee": 24_000.0,
        "volume_change_pct": 12.5, "fee_pct": 2.0, "volatility": 6.2,
        # Rasio volume/active TVL seperti API Meteora (kunci urut ketiga
        # sejak 2026-09-15; Fee/TVL dan F/V di depannya):
        # 1,2 juta / 60 ribu × 100 = 2000%.
        "volume_active_tvl_ratio": 2000.0,
        "total_lps": 88, "top_holders_pct": 12.0,   # < 20% → lolos saringan
        "analysis": {"holders": {"dust_pct_mc": 0.03, "dust_count": 12,
                                 "total_fetched": 1200,
                                 "wallets_analyzed": 1100}},
    }
    row.update(over)
    return row


def _dust(row, pct):
    row = dict(row)
    row["analysis"] = {"holders": {"dust_pct_mc": pct, "dust_count": 5,
                                   "total_fetched": 1000,
                                   "wallets_analyzed": 900}}
    return row


def _proof(pct, dust_count=5):
    """``analysis.holders`` satu scan FULL yang **membuktikan** jumlahnya.

    Bentuk persis keluaran ``classify_holders``. Baris tanpa bukti (fetch gagal,
    0 wallet, terpotong, sampel < ``MIN_USABLE_WALLETS``) tidak boleh
    menampilkan ``0,000%`` — fixture UI selalu membawa ``total_fetched`` /
    ``wallets_analyzed``.
    """
    return {"holders": {"dust_pct_mc": pct, "dust_count": dust_count,
                        "real_count": 1_095, "total_fetched": 1_200,
                        "wallets_analyzed": 1_100}}


def _fv(fee, vol):
    return dict(fee_active_tvl_ratio=fee, volatility=vol)


class BestFilterQueryTest(unittest.TestCase):
    def test_filter_by_matches_listing(self):
        """Query server = DLMM + active TVL (tanpa safeguard server); fee_pct
        dihapus.

        Permintaan user 2026-09-16 sempat menambahkan Jupiter safeguard di
        sisi server, tapi dimatikan default-nya 2026-09-17 (laporan user
        *"token PAID tetap tidak muncul di hasil scan"*) — filter server
        ``*_has_critical_warnings=false`` membuang token pump.fun yang baru
        launch (seperti PAID) sebelum payload sampai ke client; bendera
        kritis yang sama sudah dilaporkan kolom RugCheck tanpa membuang
        baris. Kwarg ``safeguard=True`` masih bisa dipakai untuk menyalakan
        kembali filter server.
        """
        self.assertEqual(ms.best_filter_by(), BEST_QUERY)
        self.assertEqual(ms.best_filter_by(safeguard=True), SAFEGUARD_QUERY)
        self.assertEqual(ms.JUPITER_SAFEGUARD_FILTERS,
                         ("base_token_has_critical_warnings=false",
                          "quote_token_has_critical_warnings=false"))
        self.assertNotIn("fee_pct", ms.best_filter_by())
        self.assertEqual(ms.BEST_ACTIVE_TVL_MIN, 50_000.0)
        # Regular scan + snapshot metrik watchlist memakai filter_by() lama
        # (mengubahnya = menghapus pool yang selama ini tampil di 🌊 Watchlist
        # Meteora / cron).
        self.assertEqual(ms.filter_by(), QUERY)
        self.assertEqual(ms.best_filter_by(safeguard=False), QUERY)

    def test_fetch_sends_lane_params(self):
        with mock.patch.object(ms, "_http_get",
                               return_value={"data": []}) as http:
            ms.fetch_best_pools(timeframe="24h")
        args, _kwargs = http.call_args
        self.assertEqual(args[0], ms.POOLS_URL)
        self.assertEqual(args[1], {
            "page_size": 50, "timeframe": "24h", "category": "top",
            "filter_by": BEST_QUERY,
        })

    def test_timeframe_lama_ditarik_ke_24h(self):
        """30M dihapus: permintaan ``30m``/``both``/sampah tetap window 24 jam.

        Satu-satunya jalan masuk listing Best Pool adalah :func:`scan_best_lane`
        (yang mengirim lane hasil normalisasi), tapi ``fetch_best_pools`` juga
        dinormalisasi supaya pemanggil lama/saya-cron tidak bisa lagi diam-diam
        menarik 30 menit.
        """
        for requested in ("30m", "1h", "both", "5m", None, "24H"):
            with self.subTest(requested=requested):
                with mock.patch.object(ms, "_http_get",
                                       return_value={"data": []}) as http:
                    ms.fetch_best_pools(timeframe=requested)
                args, _kwargs = http.call_args
                self.assertEqual(args[1]["timeframe"], "24h", requested)

    def test_payload_rows_only(self):
        with mock.patch.object(ms, "_http_get",
                               return_value={"data": [{"pool_address": "P1"},
                                                      "rusak", None]}):
            pools = ms.fetch_best_pools()
        self.assertEqual(pools, [{"pool_address": "P1"}])


class LaneRuleTest(unittest.TestCase):
    """Satu lane (24H), satu ambang; semua teks UI membaca konstanta yang sama."""

    def test_constants(self):
        self.assertEqual(ms.BEST_FV_24H_MIN, 5.0)
        self.assertTrue(ms.lane_fv_inclusive("24h"))
        self.assertEqual(ms.lane_fv_sign("24h"), "≥")
        self.assertEqual(ms.BEST_LANES, ("24h",))
        # 30M dihapus 2026-09-16 — konstanta lamanya DIBIARKAN ada (dipakai
        # teks/history), tapi tidak lagi masuk daftar lane.
        self.assertEqual(ms.BEST_FV_30M_MIN, 1.0)
        self.assertNotIn("30m", ms.BEST_LANES)
        # Label "30M" tetap ada hanya untuk membaca teks hasil scan lama.
        self.assertEqual(ms.BEST_LANE_LABELS.get("30m"), "30M")
        # Rentang volatility yang boleh tampil (inklusif di dua sisi).
        self.assertEqual(float(ms.BEST_VOL_SHOW_MIN), 1.0)
        self.assertEqual(float(ms.BEST_VOL_SHOW_MAX), 10.0)

    def test_normalize_alias(self):
        """Semua alias lama (30m/1h/both) dipetakan ke 24H, bukan ditolak."""
        self.assertEqual(ms.normalize_best_lane("24H"), "24h")
        self.assertEqual(ms.normalize_best_lane("24 jam"), "24h")
        for retired in ("30m", "30 menit", "30M", "1h", "both",
                        "24h+30m"):
            self.assertEqual(ms.normalize_best_lane(retired), "24h", retired)
        self.assertEqual(ms.normalize_best_lane(None), "24h")
        self.assertEqual(ms.normalize_best_lane("", default=None), None)
        # timeframe yang tidak pernah dikenal tidak dikarang jadi 24H.
        self.assertEqual(ms.normalize_best_lane("5m", default=None), None)
        self.assertEqual(ms.best_lane_lanes("24h"), ("24h",))
        self.assertEqual(ms.best_lane_lanes("30m"), ("24h",))

    def test_gate_label_ikuti_konstanta(self):
        self.assertEqual(ms.best_lane_gate_label("24h"), "24H: F/V ≥ 5×")
        # Alias lama → label + gate 24H (tidak ada lagi "30M: F/V > 1×").
        self.assertEqual(ms.best_lane_gate_label("30m"), "24H: F/V ≥ 5×")
        with mock.patch.object(ms, "BEST_FV_24H_MIN", 8.0):
            self.assertEqual(ms.best_lane_gate_label("24h"), "24H: F/V ≥ 8×")


class RowMetricsTest(unittest.TestCase):
    def test_row_captures_detail_and_sort_metrics(self):
        row = ms.rows_from_pools(
            [_pool(volatility=7.1, total_lps=64, top10=23.5,
                   fee=97_718.0, volume_change_pct=-34.46)],
            timeframe="30m")[0]
        self.assertEqual(row["volatility"], 7.1)
        self.assertEqual(row["total_lps"], 64)
        # top 10 holder diambil dari token base, bukan sisi quote (SOL 0,5%).
        self.assertEqual(row["top_holders_pct"], 23.5)
        # detail fee / active TVL + bahan urut.
        self.assertEqual(row["fee"], 97_718.0)
        self.assertEqual(row["volume_change_pct"], -34.46)
        self.assertEqual(row["active_tvl"], 60_000)
        self.assertEqual(row["ca"], "MintAAA")
        self.assertEqual(row["timeframe"], "30m")
        self.assertTrue(row["in_30m"])
        self.assertFalse(row["in_24h"])
        # kolom F/V = quotient yang dipakai saringan + urutan.
        self.assertAlmostEqual(row["fee_volatility_ratio"], 40.0 / 7.1)
        self.assertAlmostEqual(ms.row_fv_ratio(row), 40.0 / 7.1)

    def test_duplicate_pool_address_dropped(self):
        rows = ms.rows_from_pools([_pool("P1"), _pool("P1"), _pool("P2")])
        self.assertEqual([r["pool_address"] for r in rows], ["P1", "P2"])

    def test_best_rows_from_lanes_dihapus(self):
        """Fungsi penggabung dua lane (``both``) sudah tidak ada lagi.

        30M dihapus 2026-09-16 dan ``scan_best_lane`` hanya punya satu cabang;
        record ganda satu-pool-dua-lane tidak pernah dipakai siapa pun.
        """
        self.assertFalse(hasattr(ms, "best_rows_from_lanes"))

    def test_row_fv_ratio_inf_dan_none(self):
        self.assertIsNone(ms.row_fv_ratio(None))
        self.assertIsNone(ms.row_fv_ratio(_fv(None, 1.0)))
        self.assertEqual(ms.row_fv_ratio(_fv(5.0, 0)), float("inf"))
        self.assertEqual(ms.row_fv_ratio(_fv(0, 0)), 0.0)
        self.assertAlmostEqual(ms.row_fv_ratio(_fv(40.0, 8.0)), 5.0)

    def test_row_volatility_zero(self):
        """Hanya 0 persis yang dianggap tanpa pergerakan untuk dibuang."""
        self.assertTrue(ms.row_volatility_zero(_row(volatility=0)))
        self.assertTrue(ms.row_volatility_zero(_row(volatility=0.0)))
        self.assertFalse(ms.row_volatility_zero(_row()))
        self.assertFalse(ms.row_volatility_zero(None))
        self.assertFalse(ms.row_volatility_zero(_row(volatility=None)))
        # Hilang/negatif/nonfinite bukan nol — tetap masuk listing dilewati
        # dengan alasan metrik, bukan dibuang diam-diam.
        self.assertFalse(ms.row_volatility_zero(_row(volatility=-0.01)))
        self.assertFalse(ms.row_volatility_zero(_row(volatility=float("nan"))))
        self.assertFalse(ms.row_volatility_zero(_row(volatility=float("inf"))))

    def test_vol_tvl_ratio_dihitung_ulang_untuk_baris_lama(self):
        row = _row(volume_active_tvl_ratio=None)
        self.assertAlmostEqual(ms.row_vol_tvl_ratio(row), 2000.0)
        self.assertIsNone(ms.row_vol_tvl_ratio({"volume": 10.0,
                                               "active_tvl": None}))


class FvDisplayTest(unittest.TestCase):
    """Teks kolom F/V + pasangan pool (permintaan user 2026-09-15).

    Laporan user: *"coba cek last scan — gold menunjukkan 6328266.1 F/V —
    perbaiki"*. Angka aslinya benar (pool GOLD-XAUt0: ``fee_active_tvl_ratio``
    0,013 ÷ ``volatility`` 2,06e-09 = 6.328.266×), yang salah cuma formatnya:
    satu desimal untuk semua besaran membuat rasio jutaan tampil ~10 digit
    tanpa pemisah. Sekaligus kolom **Token** kini menulis pasangan pool-nya.
    """

    def test_di_bawah_100_tetap_satu_desimal(self):
        self.assertEqual(ms.format_fv_ratio(10.14), "10.1×")
        self.assertEqual(ms.format_fv_ratio(6.4516), "6.5×")
        self.assertEqual(ms.format_fv_ratio(5.0), "5.0×")
        self.assertEqual(ms.format_fv_ratio(1.0), "1.0×")

    def test_100_ke_atas_bulat_dengan_pemisah_ribuan(self):
        self.assertEqual(ms.format_fv_ratio(100.0), "100×")
        self.assertEqual(ms.format_fv_ratio(1234.6), "1,235×")
        # Angka yang dilaporkan user apa adanya: 6328266.1 → 6,328,266×.
        self.assertEqual(ms.format_fv_ratio(6328266.1), "6,328,266×")
        # Lompatan format ada di 100×: di bawahnya masih satu desimal.
        self.assertEqual(ms.format_fv_ratio(99.9), "99.9×")

    def test_none_nan_inf(self):
        """Tidak terukur → None (UI menulis —); tak hingga → ∞ (warisan)."""
        self.assertIsNone(ms.format_fv_ratio(None))
        self.assertIsNone(ms.format_fv_ratio(""))
        self.assertIsNone(ms.format_fv_ratio("bukan angka"))
        self.assertIsNone(ms.format_fv_ratio(float("nan")))
        self.assertIsNone(ms.format_fv_ratio(True))
        self.assertEqual(ms.format_fv_ratio(float("inf")), "∞")

    def test_satu_sumber_dengan_angka_yang_disaring(self):
        """Rasio yang tampil = rasio yang dipakai saringan + urutan."""
        row = _row(fee_active_tvl_ratio=0.013025137688422304,
                   volatility=2.057951587445997e-09)
        self.assertAlmostEqual(ms.row_fv_ratio(row) / 6_329_175.9, 1.0,
                               places=6)
        self.assertEqual(ms.format_fv_ratio(ms.row_fv_ratio(row)),
                         "6,329,176×")
        # Formatnya tidak mengubah keputusan F/V: rasio 6,3 juta× jauh di atas
        # 5×. Yang membuat baris ini gugur sejak 2026-09-16 adalah window
        # volatility (2e-09% < 1%) — persis pool "nyaris tidak bergerak" yang
        # user minta disembunyikan.
        self.assertEqual(
            ms.row_best_gaps(row, lane="24h"),
            ["24H: volatility 2.05795e-09% < 1% \u2014 pool nyaris tidak "
             "bergerak"])
        self.assertFalse(ms.row_volatility_zero(row))

    def test_pasangan_pool_dari_nama_pool_api(self):
        self.assertEqual(
            ms.row_pair_label(_row(pool_name="ALLINU/SOL")), "ALLINU/SOL")
        self.assertEqual(ms.row_pair_label(_row(pool_name="TOK-SOL")),
                         "TOK-SOL")
        # Huruf kecil + spasi ganda dirapikan; namanya tidak ditebak-tebak.
        self.assertEqual(ms.row_pair_label(_row(pool_name=" allinu/sol ")),
                         "ALLINU/SOL")
        self.assertEqual(ms.row_pair_label(_row(pool_name="TOK  -  SOL")),
                         "TOK - SOL")

    def test_pasangan_pool_kosong_tidak_dikarang(self):
        """Tanpa nama pool: baris pasangan tidak ditampilkan (bukan tebakan)."""
        self.assertEqual(ms.row_pair_label(_row()), "")          # name = "AAA"
        self.assertEqual(ms.row_pair_label(_row(name="Some Token")), "")
        self.assertEqual(ms.row_pair_label(None), "")
        # Nama token yang memang terlihat seperti pasangan masih dipakai
        # sebagai cadangan (hasil scan lama sebelum ``pool_name`` ada).
        self.assertEqual(ms.row_pair_label(_row(name="allinu/sol")),
                         "ALLINU/SOL")


class BestGatesTest(unittest.TestCase):
    """Saringan lane: 24H ``F/V >= 5×``; 30M ``F/V > 1×``."""

    def test_passing_rows_have_no_gap(self):
        """Baris bawaan fixture lolos semua saringan layar — tidak ada gap."""
        self.assertEqual(ms.row_best_gaps(_row()), [])
        # Boundary inklusif di dua sisi volatilitas + F/V tepat 5×.
        self.assertEqual(ms.row_best_gaps(_row(**_fv(50.0, 1.0))), [])
        self.assertEqual(ms.row_best_gaps(_row(**_fv(60.0, 10.0))), [])

    def test_24h_boundary_inklusif(self):
        """F/V tepat 5× lolos (inklusif); 4,999× gugur dengan teks < 5×."""
        self.assertEqual(ms.row_best_gaps(_row(**_fv(50.0, 10.0))), [])
        self.assertEqual(ms.row_best_gaps(_row(**_fv(49.999, 10.0))),
                         ["24H: F/V < 5\u00d7"])

    def test_volatility_boundary_inklusif(self):
        """Volat 1% dan 10% tetap tampil; di luar itu disembunyikan.

        Permintaan user 2026-09-16: *"volatility kurang dari 1 sembunyikan
        juga"* + *"volatility > 10 sembunyikan juga"* — keduanya ditulis sebagai
        gap (bukan pembuangan diam-diam) supaya tabel "dilewati" tetap bisa
        diaudit. 10,0% masih lolos karena user menyebut "< 1" dan "> 10".
        """
        self.assertEqual(ms.row_volatility_gap(1.0), "")
        self.assertEqual(ms.row_volatility_gap(10.0), "")
        self.assertEqual(ms.row_volatility_gap(6.2), "")
        self.assertIn("< 1%", ms.row_volatility_gap(0.999))
        self.assertIn("> 10%", ms.row_volatility_gap(10.001))
        self.assertEqual(
            ms.row_best_gaps(_row(**_fv(60.0, 0.5))),
            ["24H: volatility 0.5% < 1% \u2014 pool nyaris tidak bergerak"])
        self.assertEqual(
            ms.row_best_gaps(_row(**_fv(600.0, 10.5))),
            ["24H: volatility 10.5% > 10% \u2014 pergerakan lebih besar "
             "dari fee"])
        # Tanpa angka volatility tidak ada bukti: TIDAK gugur karena volat
        # (cabang metrik F/V yang bicara, bukan dua kali).
        self.assertEqual(ms.row_volatility_gap(None), "")

    def test_volatility_nol_selalu_gugur(self):
        """V=0 (F/V \u221e) bukan kelolosan dan tetap dibuang penuh (2026-09-14)."""
        self.assertEqual(ms.row_best_gaps(_row(**_fv(0.5, 0))),
                         ["24H: volatility 0 \u2014 F/V tidak terukur"])
        # ``row_volatility_zero`` memisahkan "dibuang total" dari "gugur biasa".
        self.assertTrue(ms.row_volatility_zero(_row(**_fv(0.5, 0))))
        self.assertFalse(ms.row_volatility_zero(_row(**_fv(0.5, 0.5))))

    def test_metrik_hilang_atau_asing_gugur(self):
        self.assertEqual(len(ms.row_best_gaps(_row(volatility=None))), 1)
        self.assertEqual(len(ms.row_best_gaps(_row(fee_active_tvl_ratio=None))), 1)
        self.assertEqual(ms.row_best_gaps(_row(fee_active_tvl_ratio=float("nan"),
                                               volatility=1.0)),
                         ["metrik F/V tidak tersedia atau tidak valid"])
        self.assertEqual(ms.row_best_gaps(_row(timeframe="5m")),
                         ["timeframe tidak dikenal"])

    def test_teks_gap_ikuti_konstanta(self):
        """Teks gap dibaca dari konstanta, tidak pernah ditulis ulang di UI."""
        with mock.patch.object(ms, "BEST_FV_24H_MIN", 8.0):
            self.assertEqual(ms.row_best_gaps(_row(**_fv(20.0, 5.0))),
                             ["24H: F/V < 8\u00d7"])
        with mock.patch.object(ms, "BEST_VOL_SHOW_MAX", 5.0):
            self.assertEqual(
                ms.row_best_gaps(_row(**_fv(60.0, 6.0))),
                ["24H: volatility 6% > 5% \u2014 pergerakan lebih besar "
                 "dari fee"])
        with mock.patch.object(ms, "BEST_VOL_SHOW_MIN", 3.0):
            self.assertEqual(
                ms.row_best_gaps(_row(**_fv(60.0, 2.0))),
                ["24H: volatility 2% < 3% \u2014 pool nyaris tidak bergerak"])

    def test_saringan_lama_tetap_mati(self):
        """Dust / volume / tier fee / LPs bukan syarat — volat + Top10 ya.

        Kriteria 2026-09-13 menghapus saringan-saringan itu (permintaan user:
        "dust% syaratnya hapus saja", "minimal volume" dicabut, chip BEST POOL
        dihapus) — angka-angkanya boleh diacak, barisnya tetap lolos. Yang
        **jadi** saringan setelahnya: Top10 (2026-09-16,
        *"jika ada top 10 >= 20% jangan tampilkan"* — batas di sisi BUANG, jadi
        fixture memakai 12%) dan rentang volatility 1%\u201310% (hari yang sama).
        """
        row = _row(active_tvl=0, total_lps=0, fee_pct=0.5, volume=0,
                   dust_count=99_999, analysis=_proof(9.9))
        self.assertEqual(ms.row_best_gaps(row), [])
        self.assertTrue(ms.row_dust_ok(row))
        self.assertTrue(ms.row_volume_ok(row))
        self.assertTrue(ms.row_top10_ok(row))
        for gone in ("BEST_FEE_RATIO_MIN", "BEST_TOTAL_LPS_MIN"):
            self.assertFalse(hasattr(ms, gone), gone)
        # Ambang lama masih ada sebagai konstanta mati: mengubahnya tidak boleh
        # mengubah kelolosan siapa pun. BEST_VOLATILITY_MIN LAMA tetap mati —
        # penyaringan volatilitas memakai BEST_VOL_SHOW_MIN/MAX yang baru.
        with mock.patch.object(ms, "BEST_DUST_MAX_PCT", 0.0), \
                mock.patch.object(ms, "BEST_VOLATILITY_MIN", 99.0), \
                mock.patch.object(ms, "BEST_VOLUME_24H_MIN", 1e12):
            self.assertEqual(ms.row_best_gaps(_row()), [])
            self.assertTrue(ms.row_dust_ok(_row()))
            self.assertTrue(ms.row_volume_ok(_row()))

    def test_filter_best_rows_memakai_lane_yang_dipaksa(self):
        """Lane lama "30m" tidak lagi melonggarkan apa pun (dipetakan ke 24H)."""
        rows = [_row(pool_address="KECIL", **_fv(20.0, 10.0)),
                _row(pool_address="BESAR", **_fv(60.0, 10.0))]
        kept, hidden_metric, hidden_dust = ms.filter_best_rows(rows)
        self.assertEqual([r["pool_address"] for r in kept], ["BESAR"])
        self.assertEqual((hidden_metric, hidden_dust), (1, 0))
        kept, hidden_metric, _ = ms.filter_best_rows(rows, lane="30m")
        self.assertEqual([r["pool_address"] for r in kept], ["BESAR"])
        self.assertEqual(hidden_metric, 1)

    def test_filter_best_rows_membuang_volatility_nol_dari_hitungan(self):
        """Vol 0 gugur gate DAN tidak dihitung hidden (2026-09-14 lanjutan)."""
        rows = [_row(pool_address="LOLOS"),
                _row(pool_address="GAGAL", **_fv(2.0, 10.0)),
                _row(pool_address="NOLVOL", **_fv(50.0, 0))]
        for lane in (None, "24h", "30m"):
            with self.subTest(lane=lane):
                kept, hidden_metric, hidden_dust = ms.filter_best_rows(
                    rows, lane=lane)
                self.assertEqual([r["pool_address"] for r in kept], ["LOLOS"])
                self.assertEqual((hidden_metric, hidden_dust), (1, 0))

    # ---- Top10 holder: saringan layar kedua (permintaan user 2026-09-16) ----

    def test_row_top10_dan_boundary_inklusif(self):
        """Batas di sisi BUANG: >= 20% gugur — termasuk tepat 20,0%.

        Permintaan user 2026-09-16: *"jika ada top 10 >= 20% jangan tampilkan"*.
        Aturan lama (16 September pagi: "di atas 20%" = > 20, batas tampil
        inklusif) dicabut; yang tetap lolos hanyalah yang **di bawah** 20%.
        """
        self.assertEqual(ms.BEST_TOP10_MAX_PCT, 20.0)
        self.assertEqual(ms.row_top10_pct(_row(top_holders_pct=23.5)), 23.5)
        self.assertIsNone(ms.row_top10_pct(_row(top_holders_pct=None)))
        self.assertIsNone(ms.row_top10_pct(None))
        for pct, ok in ((0.0, True), (19.999, True), (20.0, False),
                        (20.01, False), (45.0, False), (100.0, False)):
            with self.subTest(pct=pct):
                row = _row(top_holders_pct=pct)
                self.assertEqual(ms.row_top10_ok(row), ok)
                self.assertEqual(not ms.row_best_gaps(row), ok)
                if ok:
                    self.assertIsNone(ms.row_top10_over(row))
                else:
                    self.assertEqual(ms.row_top10_over(row), pct)
        # ``None`` (tidak terukur) BUKAN 0% — barisnya tetap tampil.
        self.assertTrue(ms.row_top10_ok(_row(top_holders_pct=None)))

    def test_top10_hilang_tidak_gugur(self):
        """Tanpa angka Top10 tidak ada bukti konsentrasi — barisnya tetap lolos."""
        for missing in (None, "", "bukan angka", True, float("nan")):
            with self.subTest(top10=missing):
                row = _row(top_holders_pct=missing)
                self.assertIsNone(ms.row_top10_pct(row))
                self.assertTrue(ms.row_top10_ok(row))
                self.assertEqual(ms.row_best_gaps(row), [])

    def test_top10_gugur_dengan_alasan_di_depan_lane(self):
        """Teks gap menyebut lane + angkanya; lane lama tetap berlabel 24H."""
        self.assertEqual(
            ms.row_best_gaps(_row(top_holders_pct=45.0)),
            ["24H: Top10 45% \u2265 20% \u2014 holder terpusat"])
        self.assertEqual(
            ms.row_best_gaps(_row(timeframe="30m", top_holders_pct=20.0,
                                  **_fv(30.0, 6.0))),
            ["24H: Top10 20% \u2265 20% \u2014 holder terpusat"])

    def test_top10_hanya_dicek_setelah_ambang_lane_lolos(self):
        """Gugur F/V sudah cukup jadi alasan — tidak ada gap kedua."""
        row = _row(top_holders_pct=99.0, **_fv(2.0, 10.0))
        self.assertEqual(ms.row_best_gaps(row), ["24H: F/V < 5×"])

    def test_teks_dan_keputusan_top10_ikuti_konstanta(self):
        with mock.patch.object(ms, "BEST_TOP10_MAX_PCT", 12.0):
            self.assertEqual(ms.row_best_gaps(_row(top_holders_pct=15.0)),
                             ["24H: Top10 15% \u2265 12% \u2014 holder terpusat"])
            self.assertFalse(ms.row_top10_ok(_row(top_holders_pct=15.0)))
        with mock.patch.object(ms, "BEST_TOP10_MAX_PCT", 90.0):
            self.assertEqual(ms.row_best_gaps(_row(top_holders_pct=45.0)), [])
            self.assertTrue(ms.row_top10_ok(_row(top_holders_pct=45.0)))

    def test_filter_best_rows_menghitung_top10_sebagai_dilewati(self):
        """Gugur Top10 & vol-0 dibuang penuh dari listing (tidak dihitung dilewati)."""
        rows = [_row(pool_address="BERSIH", top_holders_pct=12.0),
                _row(pool_address="PUSAT", top_holders_pct=88.0),
                _row(pool_address="NOLVOL", top_holders_pct=88.0,
                     **_fv(50.0, 0)),
                _row(pool_address="FAIL_FV", top_holders_pct=12.0,
                     **_fv(2.0, 6.0))]
        kept, hidden_metric, hidden_dust = ms.filter_best_rows(rows)
        self.assertEqual([r["pool_address"] for r in kept], ["BERSIH"])
        self.assertEqual((hidden_metric, hidden_dust), (1, 0))

    def test_row_best_dropped_top10_dan_volatility(self):
        """Top10 >= 20% dan volatility (0, <1%, >10%) disembunyikan total."""
        # Top10 >= 20% gugur -> dropped True
        self.assertTrue(ms.row_best_dropped(_row(top_holders_pct=45.0, **_fv(30.0, 6.0))))
        self.assertTrue(ms.row_best_dropped(_row(top_holders_pct=20.0, **_fv(30.0, 6.0))))
        # Volatility 0 -> dropped True
        self.assertTrue(ms.row_best_dropped(_row(**_fv(10.0, 0.0))))
        # Volatility < 1% -> dropped True
        self.assertTrue(ms.row_best_dropped(_row(**_fv(60.0, 0.5))))
        # Volatility > 10% -> dropped True
        self.assertTrue(ms.row_best_dropped(_row(**_fv(600.0, 42.0))))
        # F/V < 5x (volat normal 6.0%, top10 normal 10%) -> dropped False (masuk hidden_rows)
        self.assertFalse(ms.row_best_dropped(_row(top_holders_pct=10.0, **_fv(2.0, 6.0))))
        # Lolos semua saringan -> dropped False (masuk rows)
        self.assertFalse(ms.row_best_dropped(_row(top_holders_pct=10.0, **_fv(30.0, 5.0))))


class BestGapSummaryTest(unittest.TestCase):
    """Rekap alasan gugur — dipakai pesan "tabel kosong" card 🏆 Best Pool.

    Laporan user 2026-09-17: *"poolnya kok jadi kosong, padahal token PAID
    harusnya masuk"* — pesan kosong lama tidak menyebut saringan mana yang
    membuang listing, jadi user harus membuka daftar "dilewati" satu-satu.
    """

    @staticmethod
    def _liq(usd):
        return {"ok": True, "usd": usd, "below_cutoff": False,
                "source": "gmgn_token_info"}

    def test_kategori_dan_urutan(self):
        # Likuiditas GMGN rendah TIDAK lagi jadi alasan gugur (filter dihapus
        # 2026-09-17 malam) — L1/L2 lolos dan tidak masuk rekap.
        rows = [_row(pool_address="L1", gmgn_liq=self._liq(153_496.33)),
                _row(pool_address="L2", gmgn_liq=self._liq(149_542.09)),
                _row(pool_address="T1", top_holders_pct=22.2),
                _row(pool_address="F1", **_fv(2.0, 6.2)),
                _row(pool_address="V1", **_fv(50.0, 42.0))]
        self.assertEqual(ms.best_gap_counts(rows),
                         [("F/V", 1), ("Top10", 1), ("volatility", 1)])
        self.assertEqual(ms.best_gap_summary(rows),
                         "1 F/V · 1 Top10 · 1 volatility")

    def test_alasan_tersimpan_dipakai_tanpa_hitung_ulang(self):
        """Baris hasil scan membawa ``best_gaps`` — rekap membaca itu."""
        row = _row(best_gaps=["24H: Likuiditas GMGN $153.50K < $500K — "
                              "tidak ditampilkan"],
                   gmgn_liq=self._liq(9_000_000.0))
        self.assertEqual(ms.row_best_gap_label(row), "likuiditas GMGN")

    def test_cutoff_rank_tidak_lagi_menggugurkan(self):
        row = _row(gmgn_liq={"ok": True, "usd": None, "below_cutoff": True,
                             "source": "gmgn_rank", "cutoff_usd": 15_000.0})
        self.assertEqual(ms.row_best_gap_label(row), "")

    def test_baris_lolos_dan_daftar_kosong(self):
        self.assertEqual(ms.row_best_gap_label(_row()), "")
        self.assertEqual(ms.best_gap_summary([]), "")
        self.assertEqual(ms.best_gap_summary([_row()]), "")

    def test_label_ambang_dibaca_dari_gmgn_liquidity(self):
        """Teks ambang ikut konstanta — tidak boleh tertinggal bila diubah."""
        import gmgn_liquidity as gl

        self.assertEqual(ms.gmgn_min_label(), gl.MIN_LABEL)
        with mock.patch.object(gl, "MIN_LABEL", "$2M"):
            self.assertEqual(ms.gmgn_min_label(), "$2M")


class SafeguardDefaultOffTest(unittest.TestCase):
    """Filter server Jupiter safeguard DIMATIKAN default-nya (2026-09-17).

    Laporan user *"token PAID tetap tidak muncul di hasil scan — tidak ada di
    daftar disembunyikan juga"*: ``base_token_has_critical_warnings=false &&
    quote_token_has_critical_warnings=false`` membuang token PAID di sisi
    server Meteora, sehingga token itu tidak pernah sampai ke client dan
    ``hidden_rows`` pun kosong. Fix: safeguard tidak lagi dipasang di query
    default; bila caller ingin, kwarg ``safeguard=True`` masih menyalakannya.
    """

    def test_default_query_tanpa_safeguard(self):
        query = ms.best_filter_by()
        self.assertNotIn("critical_warnings", query)
        self.assertEqual(query, f"pool_type=dlmm&&active_tvl>={int(ms.BEST_ACTIVE_TVL_MIN)}")

    def test_safeguard_kwarg_masih_tersedia(self):
        query = ms.best_filter_by(safeguard=True)
        self.assertIn("base_token_has_critical_warnings=false", query)
        self.assertIn("quote_token_has_critical_warnings=false", query)
        # safeguard di DEPAN pool_type (cache key konsisten).
        self.assertLess(query.index("base_token_has_critical_warnings"),
                        query.index("pool_type=dlmm"))

    def test_fetch_best_pools_default_tanpa_safeguard(self):
        with mock.patch.object(ms, "_http_get",
                               return_value={"data": []}) as http:
            ms.fetch_best_pools(timeframe="24h")
        _url, params = http.call_args.args
        self.assertNotIn("critical_warnings", params["filter_by"])


class SortBestRowsTest(unittest.TestCase):
    """Urutan tiap tabel: **Fee/TVL terbesar** → F/V terbesar → vol/TVL → dust.

    Permintaan user 2026-09-15 (lanjutan): *"sebentar, kita urutkan fee/TVL
    paling besar dulu, baru perkalian f/v"* — Fee/TVL (``fee_active_tvl_ratio``)
    naik jadi kunci pertama, F/V turun ke kunci kedua.
    """

    def test_fee_tvl_kunci_pertama_baru_fv(self):
        """Fee/TVL memimpin sendirian; dua kunci sengaja berlawanan arah.

        FEE_TERBESAR punya Fee/TVL paling besar (60%) tapi F/V-nya paling
        kecil (5×) — kalau F/V masih kunci pertama dia akan jatuh ke bawah.
        FV_TERBESAR justru sebaliknya (Fee/TVL 10%, F/V 10×).
        """
        rows = [
            _row(pool_address="FV_TERBESAR", symbol="AAA", **_fv(10.0, 1.0)),
            _row(pool_address="FEE_TERBESAR", symbol="BBB", **_fv(60.0, 12.0)),
            _row(pool_address="TENGAH", symbol="CCC", **_fv(30.0, 3.0)),
        ]
        self.assertEqual([r["pool_address"] for r in ms.sort_best_rows(rows)],
                         ["FEE_TERBESAR", "TENGAH", "FV_TERBESAR"])

    def test_fv_kunci_kedua_saat_fee_tvl_seri(self):
        """Fee/TVL sama → baru F/V terbesar yang memutuskan."""
        rows = [
            _row(pool_address="FV_KECIL", symbol="AAA", **_fv(20.0, 4.0)),  # 5×
            _row(pool_address="FV_BESAR", symbol="BBB", **_fv(20.0, 2.0)),  # 10×
        ]
        self.assertEqual([r["pool_address"] for r in ms.sort_best_rows(rows)],
                         ["FV_BESAR", "FV_KECIL"])

    def test_infinity_paling_atas_di_kelompok_fee_tvl_sama(self):
        """Kontrak urut ∞ dipertahankan **di dalam** kelompok Fee/TVL yang sama.

        ∞ (volatility 0) tetap di atas angka apa pun, tapi tidak lagi melompati
        Fee/TVL yang lebih besar — Fee/TVL kunci pertama. Baris vol-0 dibuang
        card sebelum tabel (``row_volatility_zero``, 2026-09-14 lanjutan), jadi
        urutan ini praktis tidak pernah kelihatan.
        """
        rows = [_row(pool_address="NORMAL", symbol="AAA", **_fv(500.0, 1.0)),
                _row(pool_address="NOLVOL", symbol="ZZZ", **_fv(500.0, 0))]
        self.assertEqual([r["pool_address"] for r in ms.sort_best_rows(rows)],
                         ["NOLVOL", "NORMAL"])
        # Fee/TVL 900 > 500 → di atas, walau F/V-nya cuma 900× (bukan ∞).
        rows.append(_row(pool_address="FEE_LEBIH_BESAR", symbol="BBB",
                         **_fv(900.0, 1.0)))
        self.assertEqual([r["pool_address"] for r in ms.sort_best_rows(rows)],
                         ["FEE_LEBIH_BESAR", "NOLVOL", "NORMAL"])

    def test_tie_break_volume_tvl_lalu_dust(self):
        rows = [
            _dust(_row(pool_address="A", symbol="AAA", **_fv(20.0, 4.0),
                       volume_active_tvl_ratio=10.0), 0.030),
            _dust(_row(pool_address="B", symbol="BBB", **_fv(20.0, 4.0),
                       volume_active_tvl_ratio=5.0), 0.010),
            _dust(_row(pool_address="C", symbol="CCC", **_fv(20.0, 4.0),
                       volume_active_tvl_ratio=90.0), 0.030),
            _dust(_row(pool_address="D", symbol="DDD", **_fv(20.0, 4.0),
                       volume_active_tvl_ratio=90.0), 0.030),
        ]
        # F/V seri (5×) → rasio volume/active TVL memutuskan (C/D 90 di atas
        # A 10, B 5 paling bawah meski dust-nya terkecil); C vs D identik →
        # simbol alfabetis.
        self.assertEqual([r["pool_address"] for r in ms.sort_best_rows(rows)],
                         ["C", "D", "A", "B"])

    def test_tanpa_metrik_paling_bawah_di_kunci_nya_sendiri(self):
        """Tiap kunci punya aturan None-nya sendiri; Fee/TVL hilang = paling bawah.

        TANPA_FV dan LENGKAP Fee/TVL-nya sama (10%) jadi F/V yang memilih —
        LENGKAP (10×) di atas TANPA_FV (volatility hilang). Yang tidak punya
        Fee/TVL sama sekali (TANPA_FEE) tidak bisa dibandingkan di kunci
        pertama dan selalu paling bawah, walau dust-nya paling bersih.
        """
        rows = [
            _row(pool_address="TANPA_FEE", symbol="AAA", **_fv(None, 1.0)),
            _row(pool_address="TANPA_FV", symbol="BBB", **_fv(10.0, None)),
            _dust(_row(pool_address="LENGKAP", symbol="CCC", **_fv(10.0, 1.0)),
                  0.04),
            _row(pool_address="FV_BESAR", symbol="DDD", **_fv(90.0, 1.0),
                 analysis=None),
        ]
        order = [r["pool_address"] for r in ms.sort_best_rows(rows)]
        self.assertEqual(order, ["FV_BESAR", "LENGKAP", "TANPA_FV",
                                 "TANPA_FEE"])

    def test_tie_break_dust_pakai_presisi_tampilan(self):
        """0,0301% dan 0,0304% tampil sama (0,030%) → simbol yang menentukan."""
        rows = [
            _row(pool_address="MENTAH", symbol="ZZZ", **_fv(20.0, 4.0),
                 volume_active_tvl_ratio=7.0,
                 analysis={"holders": {"dust_pct_mc": 0.0301}}),
            _row(pool_address="TAMPIL", symbol="AAA", **_fv(20.0, 4.0),
                 volume_active_tvl_ratio=7.0,
                 analysis={"holders": {"dust_pct_mc": 0.0304}}),
        ]
        self.assertEqual([r["pool_address"] for r in ms.sort_best_rows(rows)],
                         ["TAMPIL", "MENTAH"])

    def test_sort_hidden_best_rows_fv_terbesar_lalu_fee_tvl(self):
        """Tabel disembunyikan: **F/V terbesar** kunci pertama, **Fee/TVL terbesar** kunci kedua."""
        rows = [
            # F/V 2.0x, Fee/TVL 20%
            _row(pool_address="FEE_BESAR", symbol="BBB", **_fv(20.0, 10.0)),
            # F/V 4.0x, Fee/TVL 8%
            _row(pool_address="FV_BESAR", symbol="AAA", **_fv(8.0, 2.0)),
            # F/V 3.0x, Fee/TVL 15%
            _row(pool_address="TENGAH_FEE_KECIL", symbol="CCC", **_fv(15.0, 5.0)),
            # F/V 3.0x, Fee/TVL 30%
            _row(pool_address="TENGAH_FEE_BESAR", symbol="DDD", **_fv(30.0, 10.0)),
        ]
        # sort_best_rows (tabel lolos) mendahulukan Fee/TVL terbesar
        self.assertEqual([r["pool_address"] for r in ms.sort_best_rows(rows)],
                         ["TENGAH_FEE_BESAR", "FEE_BESAR", "TENGAH_FEE_KECIL", "FV_BESAR"])
        # sort_hidden_best_rows (tabel disembunyikan) mendahulukan F/V terbesar
        self.assertEqual([r["pool_address"] for r in ms.sort_hidden_best_rows(rows)],
                         ["FV_BESAR", "TENGAH_FEE_BESAR", "TENGAH_FEE_KECIL", "FEE_BESAR"])

    def test_sort_hidden_best_rows_none_fv_paling_bawah(self):
        """Baris tanpa angka F/V diurutkan paling bawah di tabel disembunyikan."""
        rows = [
            _row(pool_address="TANPA_FV", symbol="AAA", **_fv(10.0, None)),
            _row(pool_address="FV_KECIL", symbol="BBB", **_fv(2.0, 2.0)),  # 1×
            _row(pool_address="FV_BESAR", symbol="CCC", **_fv(8.0, 2.0)),  # 4×
        ]
        self.assertEqual([r["pool_address"] for r in ms.sort_hidden_best_rows(rows)],
                         ["FV_BESAR", "FV_KECIL", "TANPA_FV"])


class ScanLaneTest(unittest.TestCase):
    """Satu tombol = satu lane; kandidat gagal tidak menyentuh Helius.

    ``setUp`` mematikan kolom RugCheck (:func:`meteora_screener.scan_best_lane`
    memakainya ``rugcheck=True`` secara default) — tanpa ini tiap test scan
    menghubungi rugchecker.cc. Kolomnya sendiri diuji di
    :class:`ScanRugCheckTest` dengan HTTP yang di-mock.
    """

    def setUp(self):
        # Semua pemanggilan scan di kelas ini berjalan offline.
        self._offline = mock.patch(
            "rugchecker.attach_to_rows",
            side_effect=lambda rows, **_kw: [dict(row, rugcheck={"ok": False})
                                             for row in rows])
        self._offline.start()
        self.addCleanup(self._offline.stop)
        # Likuiditas GMGN (2026-09-17): attach offline — likuiditas tak
        # terbaca (ok: False) = TIDAK menyaring, jadi isi hidden_rows/rows
        # tetap sama persis seperti sebelum saringan GMGN ada.
        def _fake_gmgn_attach(rows, **_kw):
            for row in rows:
                row["gmgn_liq"] = {"ok": False}
            return rows

        self._gmgn = mock.patch("gmgn_liquidity.attach_total_liquidity",
                                side_effect=_fake_gmgn_attach)
        self._gmgn.start()
        self.addCleanup(self._gmgn.stop)

    @staticmethod
    def _fake_enrich(rows, **_kw):
        out = []
        for row in rows:
            item = dict(row)
            item["analysis"] = {"holders": {"dust_pct_mc": 0.02,
                                             "dust_count": 5,
                                             "total_fetched": 1000,
                                             "wallets_analyzed": 900}}
            item["dust_pct_mc"] = 0.02
            item["dust_count"] = 5
            out.append(item)
        return out

    def test_24h_hanya_ambil_lane_dan_saring_5x(self):
        pools = [_pool("P-OK", "MintOK", ratio=40.0, volatility=6.2),   # 6,45\u00d7
                 _pool("P-KECIL", "MintKcl", ratio=12.4, volatility=6.2),  # 2\u00d7
                 _pool("P-NOL", "MintNol", ratio=0.0, volatility=6.2)]
        seen: list = []

        def fake_fetch(**kw):
            seen.append(kw["timeframe"])
            return pools

        with mock.patch.object(ms, "fetch_best_pools",
                               side_effect=fake_fetch), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertEqual(seen, ["24h"])
        self.assertEqual([r["pool_address"]
                          for r in enrich.call_args.args[0]], ["P-OK"])
        self.assertEqual([r["pool_address"] for r in result["rows"]], ["P-OK"])
        self.assertEqual([r["pool_address"] for r in result["hidden_rows"]],
                         ["P-KECIL", "P-NOL"])
        self.assertEqual(result["hidden_metric"], 2)
        self.assertEqual(result["fetched"], 3)
        self.assertEqual(result["lane"], "24h")
        self.assertEqual(result["gate"], "24H: F/V \u2265 5\u00d7")
        self.assertEqual(result["error"], "")

    def test_lane_lama_tetam_mendarat_di_24h(self):
        """``scan_best_lane("30m")`` = scan 24H (alias lama dipetakan).

        Pemanggil lama (cron, tombol lama di sesi browser yang belum di-reload,
        tautan ``?page=...&timeframe=30m``) tidak boleh lagi menarik window 30
        menit — yang terjadi hanyalah satu listing 24H.
        """
        seen: list = []

        def fake_fetch(**kw):
            seen.append(kw["timeframe"])
            return []

        for requested in ("30m", "both", "1h"):
            seen.clear()
            with self.subTest(requested=requested), \
                    mock.patch.object(ms, "fetch_best_pools",
                                     side_effect=fake_fetch):
                result = ms.scan_best_lane(requested, max_wallets=2000)
            self.assertEqual(seen, ["24h"], requested)
            self.assertEqual(result["lane"], "24h", requested)

    def test_volatility_nol_dibuang_dari_listing_dan_hitungan(self):
        """Vol 0: gugur gate, TANPA scan holder, dibuang dari hidden_rows.

        2026-09-14 lanjutan — pool tanpa pergerakan tidak ditampilkan di mana
        pun; sisa jejaknya hanya counter ``dropped_volatility`` untuk audit.
        """
        pools = [_pool("P-OK", "MintOK", ratio=40.0, volatility=6.2),   # 6,45\u00d7
                 _pool("P-KECIL", "MintKcl", ratio=12.4, volatility=6.2),  # 2\u00d7
                 _pool("P-NOL", "MintNol", ratio=50.0, volatility=0.0)]  # \u221e
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("24h", max_wallets=2000)
        # Vol 0 tidak pernah memicu scan holder (gate tetap jalan).
        self.assertEqual([r["pool_address"] for r in enrich.call_args.args[0]],
                         ["P-OK"])
        self.assertEqual([r["pool_address"] for r in result["rows"]], ["P-OK"])
        # ...dan tidak masuk hidden_rows/hidden_metric: dibuang penuh.
        self.assertEqual([r["pool_address"] for r in result["hidden_rows"]],
                         ["P-KECIL"])
        self.assertEqual(result["hidden_metric"], 1)
        self.assertEqual(result["dropped_volatility"], 1)
        self.assertEqual(result["fetched"], 3)

    def test_volatility_di_luar_rentang_dibuang_sebelum_holder(self):
        """Volat < 1% dan > 10%: skip holder DAN disembunyikan total.

        Permintaan user: gugur volatility langsung disembunyikan total,
        tidak ditampilkan di mana pun.
        """
        pools = [_pool("P-SEPI", "MintSepi", ratio=40.0, volatility=0.5),
                 _pool("P-BATAS", "MintBatas", ratio=40.0, volatility=1.0),
                 _pool("P-GEBUDEG", "MintGbd", ratio=40.0, volatility=42.0),
                 _pool("P-ATAS", "MintAtas", ratio=60.0, volatility=10.0)]
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertEqual(sorted(r["pool_address"]
                                for r in enrich.call_args.args[0]),
                         ["P-ATAS", "P-BATAS"])
        self.assertEqual(sorted(r["pool_address"] for r in result["rows"]),
                         ["P-ATAS", "P-BATAS"])
        # Volatility di luar rentang langsung disembunyikan total (tidak masuk hidden_rows)
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual(result["hidden_metric"], 0)
        self.assertEqual(result["dropped_volatility"], 2)

    def test_top10_di_atas_20_dibuang_sebelum_fetch_holder(self):
        """Saringan Top10 sejalur dengan ambang F/V: holder tidak pernah di-fetch.

        Permintaan user: gugur Top10 langsung disembunyikan total, tidak
        ditampilkan di mana pun.
        """
        pools = [_pool("P-BERSIH", "MintBersih", ratio=40.0, volatility=6.2,
                       top10=12.0),
                 _pool("P-NYARIS", "MintNyaris", ratio=30.0, volatility=6.0,
                       top10=19.999),
                 _pool("P-PAS", "MintPas", ratio=30.0, volatility=6.0,
                       top10=20.0),
                 _pool("P-PUSAT", "MintPusat", ratio=60.0, volatility=6.0,
                       top10=45.0)]
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertEqual(sorted(r["pool_address"] for r in enrich.call_args.args[0]),
                         ["P-BERSIH", "P-NYARIS"])
        self.assertEqual(sorted(r["pool_address"] for r in result["rows"]),
                         ["P-BERSIH", "P-NYARIS"])
        # Top10 >= 20% langsung disembunyikan total: tidak masuk hidden_rows
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual(result["hidden_metric"], 0)
        self.assertEqual(result["dropped_top10"], 2)
        # Baris yang dibuang tidak pernah sampai ke layar tabel utama.
        self.assertNotIn("P-PUSAT", [r["pool_address"] for r in result["rows"]])

    def test_semua_gugur_tanpa_fetch_holder(self):
        with mock.patch.object(ms, "fetch_best_pools",
                               return_value=[_pool(ratio=1.0, volatility=2.0)]), \
                mock.patch.object(ms, "enrich_pools") as enrich:
            result = ms.scan_best_lane("24h", max_wallets=2000)
        enrich.assert_not_called()
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["hidden_metric"], 1)
        self.assertEqual(len(result["hidden_rows"]), 1)

    def test_kegagalan_api_jadi_pesan_card(self):
        with mock.patch.object(ms, "fetch_best_pools",
                               side_effect=RuntimeError("Meteora HTTP 503")):
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertIn("24H: Meteora HTTP 503", result["error"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["fetched"], 0)
        self.assertEqual(result["rugcheck_failed"], 0)

    def test_pool_quote_dibuang_sebelum_holder(self):
        """USDC/USDT (tanpa sisi memecoin) tidak pernah di-enrich."""
        quote_pool = _pool("P-QUOTE", ms.USDC_MINT)
        quote_pool["token_y"] = _token(ms.USDT_MINT, "USDT")
        pools = [_pool("P-OK", "MintOK"), quote_pool]
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertEqual([r["pool_address"]
                          for r in enrich.call_args.args[0]], ["P-OK"])
        self.assertEqual(result["skipped_quote"], 1)

    def test_baris_tanpa_bukti_holder_tetap_tampil(self):
        """Dust bukan saringan: scan holder gagal → barisnya tetap ada (—)."""
        pools = [_pool("P-GAGAL", "MintGagal"), _pool("P-OK", "MintOK")]

        def enrich(rows, **_kw):
            out = []
            for row in rows:
                item = dict(row)
                if row["ca"] == "MintGagal":
                    item["analysis"] = {"holders": {
                        "dust_pct_mc": 0.0, "dust_count": 0, "real_count": 0,
                        "total_fetched": 0, "wallets_analyzed": 0}}
                    item["dust_pct_mc"] = None
                else:
                    item["analysis"] = _proof(0.02)
                    item["dust_pct_mc"] = 0.02
                out.append(item)
            return out

        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools", side_effect=enrich):
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertEqual([r["pool_address"] for r in result["rows"]],
                         ["P-OK", "P-GAGAL"])   # P-OK punya dust → tie-break dulu
        self.assertIsNone(ms.row_dust_pct(result["rows"][1]))
        self.assertEqual(result["hidden_dust"], 0)

    def test_wrapper_lama_meneruskan_timeframe(self):
        """``scan_best_meteora(timeframe="30m")`` = satu listing 24H."""
        seen: list = []

        def fake_fetch(**kw):
            seen.append(kw["timeframe"])
            return []

        with mock.patch.object(ms, "fetch_best_pools", side_effect=fake_fetch):
            result = ms.scan_best_meteora(max_wallets=2000, timeframe="30m")
        self.assertEqual(seen, ["24h"])
        self.assertEqual(result["lane"], "24h")

class ScanRugCheckTest(unittest.TestCase):
    """Kolom RugCheck (rugchecker.cc) ditempel ke baris LOLOS saja, offline-safe.

    :func:`meteora_screener.scan_best_lane` memanggil
    :func:`rugchecker.attach_to_rows` setelah enrichment; kolomnya tidak pernah
    menyaring dan kegagalan HTTP tidak boleh menjatuhkan scan.
    """

    def setUp(self):
        # Likuiditas GMGN (2026-09-17) offline — lihat ScanLaneTest.setUp.
        def _fake_gmgn_attach(rows, **_kw):
            for row in rows:
                row["gmgn_liq"] = {"ok": False}
            return rows

        self._gmgn = mock.patch("gmgn_liquidity.attach_total_liquidity",
                                side_effect=_fake_gmgn_attach)
        self._gmgn.start()
        self.addCleanup(self._gmgn.stop)

    @staticmethod
    def _fake_enrich(rows, **_kw):
        return [dict(row, analysis={"holders": {"dust_pct_mc": 0.02,
                                                "dust_count": 5,
                                                "total_fetched": 1000,
                                                "wallets_analyzed": 900}},
                     dust_pct_mc=0.02, dust_count=5) for row in rows]

    def test_hanya_baris_lolos_yang_ditempel(self):
        pools = [_pool("P-OK", "MintOK"),
                 _pool("P-GUGUR", "MintGugur", ratio=1.0)]
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich), \
                mock.patch("rugchecker.attach_to_rows") as attach:
            attach.side_effect = lambda rows, **kw: [
                dict(row, rugcheck={"ok": True, "verdict": "AMAN"})
                for row in rows]
            result = ms.scan_best_lane("24h", max_wallets=2000)
        # dipanggil sekali, hanya dengan baris lolos (bukan hidden_rows)
        self.assertEqual(attach.call_count, 1)
        self.assertEqual([r["pool_address"] for r in attach.call_args.args[0]],
                         ["P-OK"])
        self.assertEqual([r["rugcheck"]["verdict"] for r in result["rows"]],
                         ["AMAN"])
        self.assertNotIn("rugcheck", result["hidden_rows"][0])

    def test_can_skips_attach(self):
        """``rugcheck=False`` (test/offline) = tidak ada panggilan sama sekali."""
        with mock.patch.object(ms, "fetch_best_pools",
                               return_value=[_pool("P-OK", "MintOK")]), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich), \
                mock.patch("rugchecker.attach_to_rows") as attach:
            ms.scan_best_lane("24h", max_wallets=2000, rugcheck=False)
        attach.assert_not_called()

    def test_kegagalan_rugcheck_jadi_pesan_bukan_crash(self):
        """Attach yang melempar error → kolom — + pesan error, baris tetap ada."""
        with mock.patch.object(ms, "fetch_best_pools",
                               return_value=[_pool("P-OK", "MintOK")]), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich), \
                mock.patch("rugchecker.attach_to_rows",
                           side_effect=RuntimeError("rugchecker.cc HTTP 503")):
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertEqual([r["pool_address"] for r in result["rows"]], ["P-OK"])
        self.assertIn("rugchecker.cc HTTP 503", result["error"])



@unittest.skipIf(AppTest is None, "streamlit not installed")
class BestPoolCardTest(unittest.TestCase):
    """Card 🏆 Scan Best Pool Meteora: dua tombol + satu tabel per lane."""

    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: {}),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: {"updated_at": None,
                                                  "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: {"tokens": {}}),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=90).run()

    @staticmethod
    def _result(lane, rows, hidden=None, *, fetched=None, error=""):
        hidden = list(hidden or [])
        return {"rows": rows, "hidden_rows": hidden, "error": error,
                "fetched": fetched if fetched is not None else len(rows) + len(hidden),
                "hidden_metric": len(hidden), "hidden_dust": 0,
                "skipped_quote": 0, "dropped_volatility": 0, "lane": lane,
                "gate": ms.best_lane_gate_label(lane), "analyzed_at": 1}

    def test_satu_tombol_24h_dan_judul_card(self):
        """Satu tombol 24H saja — tombol 30M harus hilang dari card.

        Permintaan user 2026-09-16: *"hapus scan 30 menit, kita sisakan yang 24
        jam saja"*. Jangan sampai ada tombol kedua yang mencuri hasil (dulu
        ``best-pool-scan-now`` = satu listing dua lane).
        """
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(ms.BEST_CARD_TITLE, body)
        keys = [button.key or "" for button in app.button]
        self.assertIn("best-pool-scan-24h", keys)
        self.assertNotIn("best-pool-scan-30m", keys)
        self.assertNotIn("best-pool-scan-now", keys)
        labels = [button.label for button in app.button
                  if (button.key or "").startswith("best-pool-scan-")]
        self.assertEqual(labels, ["\U0001f3c6 Scan Best Pool 24H + Holder"])
        # Rekap hasil tersimpan di bawah tombol (bukan deskripsi rule).
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("belum di-scan", captions)

    def test_tombol_scan_24h_menyimpan_hasil_di_key_lane(self):
        """Tombol = satu kali ``scan_best_lane("24h")`` + simpan di key 24H."""
        app = self._app()
        calls: list = []
        result = self._result("24h", [_row(pool_address="P24", ca="M24",
                                           symbol="THR")])

        def fake_scan(lane, **_kwargs):
            calls.append(lane)
            return result

        with mock.patch.object(ms, "scan_best_lane", side_effect=fake_scan):
            app.button(key="best-pool-scan-24h").click().run()
        self.assertEqual(calls, ["24h"])
        stored = app.session_state["best_pool_scan_24h"]
        self.assertEqual([r["pool_address"] for r in stored["rows"]], ["P24"])
        # Key lama (per-lane 30M + state pemilih lane) tidak boleh ditulis lagi.
        self.assertNotIn("best_pool_scan_30m", app.session_state)
        self.assertNotIn("best_pool_lane", app.session_state)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$THR", body)
        self.assertIn("24H \u00b7 F/V \u2265 5\u00d7", body)   # pill lane + gate
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("1 pool tersimpan", captions)

    def test_hasil_30m_lama_tidak_pernah_tampil(self):
        """Key ``best_pool_scan_30m`` lama diabaikan; kolom Src tetap hilang.

        Sesi yang masih punya hasil 30M (cache lama) tidak boleh melihatnya
        lagi — card hanya membaca key 24H.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA")],
            fetched=4, hidden=[_row(pool_address="PoolHide", ca="MintHid",
                                    symbol="HID", **_fv(2.0, 10.0))])
        app.session_state["best_pool_scan_30m"] = self._result(
            "30m", [_row(pool_address="PoolLain", ca="MintLain", symbol="LN30",
                         timeframe="30m", **_fv(15.0, 5.0))])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$AAA", body)
        self.assertIn("MintAAA", body)
        self.assertNotIn("$LN30", body)
        self.assertNotIn("PoolLain", body)
        self.assertNotIn(">Src<", body)
        self.assertIn(">F/V<", body)
        self.assertIn("syarat F/V \u2265 5\u00d7", body)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("1 pool 24H tampil \u00b7 1 dilewati \u00b7 listing 4 pool.",
                      captions)
        keys = [button.key or "" for button in app.button]
        # Tombol ⭐ favorit/watchlist dihapus 2026-09-17 (permintaan user:
        # "hapus tombol favorit / watchlist") — tidak ada key "-star-" lagi.
        self.assertFalse(any("-star-" in key for key in keys), keys)
        # Pemilih lane/view tombol 30M sudah tidak ada.
        self.assertNotIn("best-pool-view-30m", keys)
        self.assertNotIn("best-pool-view-24h", keys)
        self.assertIn("best-pool-toggle-hidden-24h", keys)

    def test_klik_disembunyikan_menampilkan_kandidat_gagal_lane_itu(self):
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA")],
            hidden=[_row(pool_address="PoolHide", ca="MintHid", symbol="HID",
                         analysis=_proof(0.02, 3), **_fv(2.0, 10.0))])
        app.run()
        app.button(key="best-pool-toggle-hidden-24h").click().run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$HID", body)
        self.assertIn("MintHid", body)
        self.assertNotIn("$AAA", body)
        # F/V merah + alasan gugur, angka ambang dibaca dari konstanta.
        self.assertIn("gugur: F/V < 5×", body)
        # Tombol ⭐ watchlist dihapus 2026-09-17 — tabel "dilewati" juga tidak
        # lagi punya key "-star-".
        self.assertNotIn("-star-",
                         [key for button in app.button
                          for key in [button.key or ""] if "-star-" in key])
        captions = "\n".join(node.value for node in app.caption)
        # Caption = angka rekap + status barisnya, BUKAN teks rule/ambang
        # (ambang hanya di tooltip judul + sub sel F/V).
        self.assertIn("1 pool 24H disembunyikan ditampilkan", captions)
        self.assertNotIn("F/V ≤", captions)

    def test_tabel_kosong_menyebut_alasan_gugurnya(self):
        """Pesan "tidak ada pool lolos" harus menyebut PENYEBABNYA.

        Laporan user 2026-09-17: *"poolnya kok jadi kosong, padahal token PAID
        harusnya masuk"* — waktu itu seluruh listing terbuang saringan
        likuiditas GMGN ($1M) dan card hanya menulis "Tidak ada pool 24H yang
        lolos filter Best Pool (atau listing kosong)." tanpa petunjuk. Sekarang
        rekap alasannya ikut tertulis + ajakan membuka daftar "dilewati".
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [],
            fetched=3,
            # Saringan likuiditas GMGN dihapus 2026-09-17 malam — alasan
            # gugur yang tersisa: F/V, volatility, Top10.
            hidden=[_row(pool_address="PoolFV", ca="MintFV",
                         symbol="FV", **_fv(2.0, 6.2)),
                    _row(pool_address="PoolFV2", ca="MintFV2",
                         symbol="FV2", **_fv(1.5, 6.2)),
                    _row(pool_address="PoolPusat", ca="MintPusat",
                         symbol="PUSAT", top_holders_pct=45.0)])
        app.run()
        self.assertEqual(len(app.exception), 0)
        infos = "\n".join(node.body for node in app.info)
        self.assertIn("Tidak ada pool 24H yang lolos filter Best Pool", infos)
        # Top10 dibuang total, hanya 2 pool F/V yang masuk dilewati
        self.assertIn("2 pool dilewati: 2 F/V", infos)
        self.assertIn("▶ 2 pool dilewati", infos)

    def test_top10_di_atas_20_tidak_tampil_di_tabel(self):
        """24H: baris Top10 >= 20% hilang dari tabel lolos dan disembunyikan total.

        Permintaan user: hasil yang gugur karena gugur: Top10 langsung
        sembunyikan total, tidak ditampilkan di mana pun.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBersih", ca="MintBersih",
                         symbol="BERSIH", top_holders_pct=12.0),
                    _row(pool_address="PoolPusat", ca="MintPusat",
                         symbol="PUSAT", top_holders_pct=45.0),
                    _row(pool_address="PoolPas", ca="MintPas", symbol="TEPAT",
                         top_holders_pct=20.0)],
            fetched=3)
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$BERSIH", body)
        self.assertNotIn("$PUSAT", body)
        self.assertNotIn("MintPusat", body)
        self.assertNotIn("$TEPAT", body)
        captions = "\n".join(node.value for node in app.caption)
        # Top10 >= 20% dibuang total (0 dilewati)
        self.assertIn("1 pool 24H tampil \u00b7 0 dilewati \u00b7 listing 3 pool.",
                      captions)
        keys = [button.key or "" for button in app.button]
        self.assertNotIn("best-pool-toggle-hidden-24h", keys)
        self.assertNotIn("gugur: Top10", body)

    def test_volatility_nol_tidak_tampil_di_listing_dilewati_24h(self):
        """24H: pool vol-0 tidak ikut listing dilewati dan tidak dihitung
        (permintaan user 2026-09-14 lanjutan) — walau hasil scan lama masih
        membawanya di ``hidden_rows``."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA")],
            fetched=6,
            hidden=[_row(pool_address="PoolHide", ca="MintHid", symbol="HID",
                         **_fv(2.0, 10.0)),
                    _row(pool_address="PoolNol", ca="MintNol", symbol="NOLSYM",
                         **_fv(50.0, 0.0))])
        app.run()
        self.assertEqual(len(app.exception), 0)
        captions = "\n".join(node.value for node in app.caption)
        # Hitungan "dilewati" hanya kandidat gagal F/V — vol-0 dibuang penuh
        # (counter hidden_metric lama yang masih 2 tidak boleh bocor ke layar).
        self.assertIn("1 pool 24H tampil · 1 dilewati · listing 6 pool.",
                      captions)
        keys = [button.key or "" for button in app.button]
        self.assertIn("best-pool-toggle-hidden-24h", keys)
        app.button(key="best-pool-toggle-hidden-24h").click().run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$HID", body)
        # Vol-0: tidak ada barisnya di tabel disembunyikan.
        self.assertNotIn("NOLSYM", body)
        self.assertNotIn("PoolNol", body)
        self.assertNotIn("MintNol", body)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("1 pool 24H disembunyikan ditampilkan", captions)

    def test_tabel_disembunyikan_urut_fv_lalu_fee_tvl_dan_top10_volat_lenyap(self):
        """Hasil disembunyikan diurutkan F/V terbesar lalu Fee/TVL terbesar; Top10 & volat dibuang."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h",
            [_row(pool_address="PoolLolos", ca="MintLolos", symbol="LOLOS")],
            fetched=6,
            hidden=[
                # F/V 2.0x, Fee/TVL 20%
                _row(pool_address="PoolFvKecil", ca="MintB", symbol="B_FV2",
                     **_fv(20.0, 10.0)),
                # F/V 4.0x, Fee/TVL 8%
                _row(pool_address="PoolFvBesar1", ca="MintA", symbol="A_FV4_FEE8",
                     **_fv(8.0, 2.0)),
                # F/V 4.0x, Fee/TVL 16%
                _row(pool_address="PoolFvBesar2", ca="MintC", symbol="C_FV4_FEE16",
                     **_fv(16.0, 4.0)),
                # Gugur Top10 -> harus disembunyikan total
                _row(pool_address="PoolTop10", ca="MintTop", symbol="TOP10_FAIL",
                     top_holders_pct=45.0, **_fv(30.0, 6.0)),
                # Gugur volatility -> harus disembunyikan total
                _row(pool_address="PoolVol", ca="MintVol", symbol="VOL_FAIL",
                     **_fv(60.0, 0.5)),
            ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        captions = "\n".join(node.value for node in app.caption)
        # Hanya 3 pool F/V yang masuk dilewati (Top10 & Volat dibuang total)
        self.assertIn("1 pool 24H tampil \u00b7 3 dilewati \u00b7 listing 6 pool.", captions)
        app.button(key="best-pool-toggle-hidden-24h").click().run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        # Baris Top10 dan volatility sama sekali tidak ada di body
        self.assertNotIn("TOP10_FAIL", body)
        self.assertNotIn("VOL_FAIL", body)
        # Urutan: C_FV4_FEE16 dulu (F/V 4x, Fee/TVL 16%), lalu A_FV4_FEE8 (F/V 4x, Fee/TVL 8%), lalu B_FV2 (F/V 2x)
        idx_c = body.index("$C_FV4_FEE16")
        idx_a = body.index("$A_FV4_FEE8")
        idx_b = body.index("$B_FV2")
        self.assertLess(idx_c, idx_a, "F/V seri: Fee/TVL 16% harus di atas Fee/TVL 8%")
        self.assertLess(idx_a, idx_b, "F/V 4x harus di atas F/V 2x walau Fee/TVL-nya lebih kecil")

    def test_volatility_nol_di_rows_lama_ikut_hilang(self):
        """Baris vol-0 warisan sesi sebelum ∞ gugur (dulu teratas) lenyap."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA"),
                    _row(pool_address="PoolLama", ca="MintLama", symbol="LAMA",
                         **_fv(500.0, 0.0))],   # era lalu: tampil sebagai ∞
            fetched=2)
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$AAA", body)
        self.assertNotIn("LAMA", body)
        self.assertNotIn("PoolLama", body)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("1 pool 24H tampil · 0 dilewati · listing 2 pool.",
                      captions)
        keys = [button.key or "" for button in app.button]
        self.assertNotIn("best-pool-toggle-hidden-24h", keys)

    def test_hasil_lama_gabungan_diabaikan(self):
        """Key gabungan lama ``best_pool_scan`` (24H+30M campur) tidak dibaca.

        Dulu hasil itu dipecah per lane supaya tidak hilang; sejak 30M
        dihapus (2026-09-16) memecahnya justru berarti menarik baris 30M ke
        tabel 24H, jadi card mengabaikannya dan user menekan Scan ulang.
        """
        app = self._app()
        app.session_state["best_pool_scan"] = self._result(
            "both", [_row(pool_address="Pool24", ca="M24", symbol="DUA4",
                          timeframe="24h"),
                     _row(pool_address="Pool30", ca="M30", symbol="TIG0",
                          timeframe="30m", **_fv(15.0, 5.0))])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertNotIn("$DUA4", body)
        self.assertNotIn("$TIG0", body)
        self.assertNotIn("best_pool_scan_24h", app.session_state)
        self.assertNotIn("best_pool_scan_30m", app.session_state)

    def test_detail_karakteristik_di_tooltip_bukan_caption(self):
        """Rule card ada di tooltip judul; caption hanya angka rekap."""
        import html as _html

        app = self._app()
        body = _html.unescape("\n".join(node.value for node in app.markdown))
        self.assertIn("Satu tombol = satu lane", body)
        for label in (f"pool_type=dlmm&&active_tvl>={int(ms.BEST_ACTIVE_TVL_MIN)}",
                      f"24H: F/V \u2265 {ms.BEST_FV_24H_MIN:g}\u00d7",
                      "Urutan tiap tabel: Fee/TVL terbesar, lalu F/V terbesar",
                      # Saringan likuiditas GMGN dicabut 2026-09-17 malam
                      # (permintaan user: "filter likuiditas hapus coba") —
                      # tooltip harus menjelaskannya (dulu frasa "likuiditas
                      # total GMGN di bawah $500K" yang di-pin di sini, frasa
                      # itu tidak boleh balik: lihat test_tooltip_ambang).
                      "Likuiditas total GMGN TIDAK lagi menyaring",
                      f"HIJAU bila > {ms.gmgn_min_label()}",
                      "RugCheck",
                      # Safeguard Jupiter dimatikan di server (2026-09-17) —
                      # tooltip harus menjelaskan itu, agar user tahu kenapa
                      # token seperti PAID kini lolos.
                      "bendera safeguard Jupiter",
                      "bukan filter server"):
            self.assertIn(label, body)
        # Dua flag safeguard server TIDAK boleh lagi nongol di tooltip — ia
        # sudah tidak dipakai di query default (PAID dibuang diam-diam olehnya).
        for gone_flag in ("base_token_has_critical_warnings=false",
                          "quote_token_has_critical_warnings=false"):
            self.assertNotIn(gone_flag, body)
        # Teks dua-lane lama tidak boleh balik.
        for gone in ("Dua tombol = dua lane", "30M: F/V >", "Vol 30m",
                     "OK hijau"):
            self.assertNotIn(gone, body)
        captions = "\n".join(node.value for node in app.caption)
        for rule_text in ("Urutan:", "disaring", "SEBELUM scan", "syarat",
                          "F/V \u2265", "F/V >"):
            self.assertNotIn(rule_text, captions)
        # saringan yang sudah dicabut tidak boleh balik ke tooltip
        tooltip = bp.best_pool_tooltip()
        for gone in ("top 10 holder <", "total LPs >", "volatility >= 2%",
                     "volume 24 jam >= $1,000,000", "dust holder < 0,05%",
                     "fee_pct>="):
            self.assertNotIn(gone, tooltip)

    def test_tooltip_ambang_mengikuti_perubahan_konstanta(self):
        """Angka di tooltip dibaca dari konstanta screener, bukan ditulis tangan."""
        with mock.patch.object(ms, "BEST_FV_24H_MIN", 7.0):
            self.assertIn("24H: F/V \u2265 7\u00d7", bp.best_pool_tooltip())
            self.assertIn("F/V \u2265 7\u00d7", bp.best_lane_gate_text("24h"))
            # Label lama "30M" ikut membaca gate 24H (alias dipetakan).
            self.assertIn("F/V \u2265 7\u00d7", bp.best_lane_gate_text("30m"))
        with mock.patch.object(ms, "BEST_ACTIVE_TVL_MIN", 75_000.0):
            self.assertIn("active_tvl>=75000", bp.best_pool_tooltip())
        with mock.patch.object(ms, "BEST_TOP10_MAX_PCT", 15.0):
            self.assertIn("Top10 15% atau lebih gugur", bp.best_pool_tooltip())
        with mock.patch.object(ms, "BEST_VOL_SHOW_MIN", 2.0), \
                mock.patch.object(ms, "BEST_VOL_SHOW_MAX", 8.0):
            self.assertIn("2%\u20138%", bp.best_pool_tooltip())
        # Ambang WARNA likuiditas GMGN (bukan filter lagi sejak 2026-09-17
        # malam) juga dibaca dari konstanta, bukan "$500K" tulisan tangan.
        import gmgn_liquidity as gl

        with mock.patch.object(gl, "MIN_LABEL", "$250K"):
            tip = bp.best_pool_tooltip()
            self.assertIn("HIJAU bila > $250K", tip)
            self.assertNotIn("likuiditas total GMGN di bawah", tip)

    def test_urutan_kolom_2026_09_17(self):
        """Urutan header: Token, F/V, Fee/TVL, Volat, Active Range, LPs, Fee %…

        Permintaan user 2026-09-17: *"hapus kolom dust %"*, *"hapus tombol
        favorit / watchlist"*, *"tambahkan copy link hawkfi dibagian scan"*,
        dan *"batasi per kolom dengan garis naik turun"*. Kolom **Dust %MC**
        dihapus (kolom jumlah wallet sudah lebih dulu dihapus 2026-09-14),
        tombol ⭐ hilang, kolom **Pool** kini memuat tombol 📋 copy link
        HawkFi, dan tiap baris tabel didahului marker ``.bp-cols-next`` untuk
        garis vertikal pembatas kolom; **RugCheck** tetap sebelum Pool.

        **Update 2026-09-19** (permintaan user: *"hapus tentang bubblemap,
        sisakan hyperlink ke bubblemapnya saja"* + *"Kasih kolom baru dipaling
        kanan STRATEGY"*): kolom **Bubble Map** (sempat ditambah 2026-09-18)
        dihapus dan kolom **STRATEGY** duduk di paling kanan — tapi HANYA di
        tabel utama, jadi tabel ini 14 kolom (13 kolom dasar + STRATEGY) dan
        tabel "▶ N pool dilewati" tetap 13 kolom (lihat
        :class:`BubbleMapColumnRemovedTest` +
        :class:`StrategyColumnTest`).
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA")])
        app.run()
        body = "\n".join(node.value for node in app.markdown)
        headers = [">Token<", ">F/V<", ">Fee/TVL<", ">Volat<", ">Active Range<",
                   ">LPs<", ">Fee %<", ">MC<", ">A.TVL<", ">Vol 24h<",
                   ">Top10<", ">RugCheck<", ">Pool<", ">STRATEGY<"]
        for header in headers:
            self.assertIn(header, body)
        for kiri, kanan in zip(headers, headers[1:]):
            self.assertLess(body.index(kiri), body.index(kanan),
                            f"{kiri} harus di kiri {kanan}")
        self.assertLess(body.index(">Top10<"), body.index(">RugCheck<"))
        self.assertLess(body.index(">RugCheck<"), body.index(">Pool<"))
        # "hapus kolom dust %": kolom Dust %MC (dan kolom jumlah wallet lama)
        # tidak lagi dirender — header maupun sel/sub/tooltip-nya.
        self.assertNotIn(">Dust %MC<", body)
        self.assertNotIn(">Dust<", body)
        self.assertNotIn(">dust<", body)
        self.assertNotIn("dust holder — informasi", body)
        self.assertNotIn("jumlah wallet dust di bawah ambang dust", body)
        # "hapus tombol favorit / watchlist": tombol ⭐ hilang dari tabel.
        keys = [button.key or "" for button in app.button]
        self.assertFalse(any("-star-" in key for key in keys), keys)
        self.assertNotIn("Tambah ke Watchlist Meteora", body)
        # "tambahkan copy link hawkfi": tombol 📋 per baris, memuat URL
        # HawkFi pool di title + clipboard JS — bukan st.button (tanpa rerun).
        self.assertIn("hawkfi-copy-btn", body)
        self.assertIn("Copy link HawkFi: "
                      "https://www.hawkfi.ag/meteora/PoolBest", body)
        self.assertIn("navigator.clipboard", body)
        # "batasi per kolom dengan garis naik turun": marker pembatas kolom
        # ada sebelum header (bersama marker mobile) dan sebelum baris data;
        # CSS garis vertikalnya hidup di dashboard_components.render_styles.
        self.assertIn('class="mobile-hide-next bp-cols-next"', body)
        self.assertIn('<div class="bp-cols-next"></div>', body)
        styles_src = (Path(__file__).resolve().parent.parent
                      / "dashboard_components.py").read_text(encoding="utf-8")
        self.assertIn(".bp-cols-next", styles_src)
        self.assertIn("border-right", styles_src)
        # Selector-nya harus cocok dengan DOM Streamlit 1.61.1: marker
        # markdown di dalam stElementContainer, horizontal block kolom
        # sebagai saudara langsungnya, kolom ber-testid stColumn.
        self.assertIn('div[data-testid="stElementContainer"]:has(.bp-cols-next)',
                      styles_src)
        self.assertIn('div[data-testid="stHorizontalBlock"]', styles_src)
        self.assertIn('div[data-testid="stColumn"]', styles_src)
        # Judul, lebar kolom, dan sel harus selalu satu jumlah: 14 di tabel
        # utama (13 kolom dasar + STRATEGY) dan 13 di tabel "dilewati"
        # (penataan 2026-09-19).
        self.assertEqual(len(bp._lane_titles("24h")),
                         len(bp._col_spec(show_strategy=True)))
        self.assertEqual(len(bp._lane_titles("24h")), 14)
        self.assertEqual(len(bp._lane_titles("24h", show_strategy=False)),
                         len(bp._col_spec(show_strategy=False)))
        self.assertEqual(len(bp._lane_titles("24h", show_strategy=False)), 13)
        self.assertEqual(bp._lane_titles("24h")[-1], "STRATEGY")
        self.assertEqual(bp._lane_titles("24h", show_strategy=False)[-1],
                         "Pool")

    def test_kolom_fee_persen_menampilkan_fee_pool(self):
        """Fee % = fee trading pool (tier fee DLMM), bukan fee USD atau rasio.

        Nilai tampil sebagai persen di kanan LPs (dulu setelah Dust %MC,
        sebelum kolom itu dihapus 2026-09-17); baris tanpa ``fee_pct`` (data
        lama di session_state) menampilkan ``—``, bukan 0% palsu.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolFee", ca="MintFee", symbol="FEE",
                 fee_pct=0.5),
            _row(pool_address="PolTanpa", ca="MintNo", symbol="NOFE",
                 fee_pct=None),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(">Fee %<", body)
        self.assertIn('<div class="watchlist-metric-value">0.5%</div>', body)
        self.assertIn("pool fee", body)
        self.assertIn("fee trading pool", body)
        self.assertIn('<div class="watchlist-metric-value">\u2014</div>', body)
        self.assertNotIn('<div class="watchlist-metric-value">0%</div>', body)

    def test_kolom_volume_selalu_24h(self):
        """Window API selalu 24 jam — label "Vol 30m" tidak bisa muncul lagi.

        Alias lama (``"30m"``) yang mungkin masih menempel di baris hasil scan
        lama hanya mempengaruhi label, dan labelnya tetap 24 jam.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolLama", ca="MintLama", symbol="LAMA",
                         timeframe="30m")])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        start = body.find(ms.BEST_CARD_TITLE)
        body = body[start:]
        self.assertIn(">Vol 24h<", body)
        self.assertNotIn(">Vol 30m<", body)
        self.assertIn("volume 24 jam", body)
        self.assertIn("fee 24 jam", body)
        self.assertNotIn("volume 30 menit", body)
        self.assertNotIn("fee 30 menit", body)

    def test_sorot_hijau_menyala_volat_dan_fv_tertinggi(self):
        """24H: sel Volat terbesar & F/V tertinggi = hijau tua menyala + bold.

        Lanjutan permintaan user 2026-09-14: Fee/TVL tertinggi ikut disorot.
        """
        neon = bp.TOP_HIGHLIGHT_COLOR
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolTop", ca="MintTop", symbol="TOP",
                 fee_active_tvl_ratio=100.0, volatility=9.9),   # 10,1× · vol top
            _row(pool_address="PoolKedua", ca="MintKd", symbol="KDUA",
                 fee_active_tvl_ratio=50.0, volatility=6.2),    # 8,1×
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        # Volat terbesar (9,9), F/V tertinggi (10,1×), dan Fee/TVL tertinggi
        # (100,0%) tersorot neon.
        self.assertIn(
            f'<span style="color:{neon};font-weight:800;">9.9%</span>', body)
        self.assertIn(
            f'<span style="color:{neon};font-weight:800;">10.1×</span>', body)
        self.assertIn(
            f'<span style="color:{neon};font-weight:800;">100.0%</span>', body)
        # Yang bukan tertinggi TIDAK ikut menyala.
        self.assertNotIn(
            f'<span style="color:{neon};font-weight:800;">6.2%</span>', body)
        self.assertNotIn(
            f'<span style="color:{neon};font-weight:800;">8.1×</span>', body)
        self.assertNotIn(
            f'<span style="color:{neon};font-weight:800;">50.0%</span>', body)
        self.assertIn("volatility terbesar di tabel ini", body)
        self.assertIn("F/V tertinggi di tabel ini", body)
        self.assertIn("Fee/TVL tertinggi di tabel ini", body)

    def test_sorot_fee_tvl_tertinggi_bisa_baris_lain_dari_fv(self):
        """Fee/TVL tertinggi disorot walau barisnya bukan pemegang F/V tertinggi.

        Tiap kolom dicari maksimumnya sendiri-sendiri — baris F/V teratas
        boleh berbeda dari baris Fee/TVL teratas (permintaan user 2026-09-14
        lanjutan).
        """
        neon = bp.TOP_HIGHLIGHT_COLOR
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolFv", ca="MintFv", symbol="FVTOP",
                 fee_active_tvl_ratio=50.0, volatility=2.0),   # F/V 25,0×
            _row(pool_address="PoolFee", ca="MintFe", symbol="FEETOP",
                 fee_active_tvl_ratio=80.0, volatility=8.0),   # F/V 10,0×
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        # Fee/TVL tertinggi (80,0%) ada di baris FEETOP → tersorot.
        self.assertIn(
            f'<span style="color:{neon};font-weight:800;">80.0%</span>', body)
        self.assertNotIn(
            f'<span style="color:{neon};font-weight:800;">50.0%</span>', body)
        # F/V tertinggi (25,0×) ada di baris FVTOP → tersorot di sel-nya.
        self.assertIn(
            f'<span style="color:{neon};font-weight:800;">25.0×</span>', body)
        self.assertNotIn(
            f'<span style="color:{neon};font-weight:800;">10.0×</span>', body)

    def test_sorot_fee_tvl_seri_di_puncak_semua_ditandai(self):
        """Dua baris seri sebagai Fee/TVL tertinggi → dua-duanya menyala."""
        neon = bp.TOP_HIGHLIGHT_COLOR
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolA", ca="MintA", symbol="ASAT",
                 fee_active_tvl_ratio=70.0, volatility=9.9),
            # 10,0% = batas atas window (inklusif) → tetap tampil, Fee/TVL-nya
            # seri dengan baris pertama → dua-duanya harus menyala.
            _row(pool_address="PoolB", ca="MintB", symbol="BDUA",
                 fee_active_tvl_ratio=70.0, volatility=10.0),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertEqual(
            body.count(
                f'<span style="color:{neon};font-weight:800;">70.0%</span>'), 2)

    def test_seriketika_di_puncak_semuanya_ditandai(self):
        """Dua baris seri sebagai volatility terbesar → dua-duanya menyala."""
        neon = bp.TOP_HIGHLIGHT_COLOR
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolA", ca="MintA", symbol="ASAT",
                 fee_active_tvl_ratio=60.0, volatility=9.9),
            _row(pool_address="PoolB", ca="MintB", symbol="BDUA",
                 fee_active_tvl_ratio=55.0, volatility=9.9),
        ])
        app.run()
        body = "\n".join(node.value for node in app.markdown)
        self.assertEqual(
            body.count(
                f'<span style="color:{neon};font-weight:800;">9.9%</span>'), 2)

    def test_tabel_dilewati_tidak_diberi_sorot(self):
        """Listing dilewati 24H: baris tetap merah gugur, tanpa hijau neon."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA")],
            hidden=[_row(pool_address="PoolHide", ca="MintHid", symbol="HID",
                         **_fv(45.0, 9.9))])   # vol & fee besar tapi gugur
        app.run()
        app.button(key="best-pool-toggle-hidden-24h").click().run()
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$HID", body)
        # Tidak ada SATU pun sel yang memakai marker sorotan. (Warna mentahnya
        # tidak bisa dijadikan asersi ke seluruh body: CSS global halaman ikut
        # memakai hex yang sama untuk class lain.)
        self.assertNotIn(
            f'<span style="color:{bp.TOP_HIGHLIGHT_COLOR};font-weight:800;">',
            body)

    def test_baris_ditampilkan_urut_f_v_dan_siap_dibaca(self):
        """Fee/TVL seri → F/V terbesar di atas; F/V ditulis ``N,N×``."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolKecil", ca="MintKcl", symbol="KCL",
                 **_fv(40.0, 8.0)),        # Fee/TVL 40% · F/V 5,0\u00d7
            _row(pool_address="PoolBesar", ca="MintBsr", symbol="BSR",
                 **_fv(40.0, 4.0)),         # Fee/TVL 40% · F/V 10,0\u00d7
        ])
        app.run()
        body = "\n".join(node.value for node in app.markdown)
        self.assertLess(body.index("$BSR"), body.index("$KCL"))
        self.assertIn("10.0\u00d7", body)
        self.assertIn("5.0\u00d7", body)
        # detail fee/TVL + volume tetap informasi (bukan saringan)
        for title in ("A.TVL", "Fee/TVL", "Vol 24h", "Volat", "Dust %MC"):
            self.assertIn(title, body)
        self.assertIn("kunci urut kedua", body)

    def test_lps_hijau_hanya_di_atas_100(self):
        """LPs > 100 = hijau; <= 100 tidak berubah sama sekali.

        Permintaan user 2026-09-16: *"LPs jika lebih dari 100, kasih warna
        hijau jika tidak, tidak ada perubahan"*. Hijau ini **bukan**
        ``TOP_HIGHLIGHT_COLOR`` (penanda tertinggi tabel) dan bukan saringan:
        baris 12 LP tetap tampil.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolRamai", ca="MintRamai", symbol="RAMAI",
                 total_lps=1234),
            _row(pool_address="PoolPas", ca="MintPas", symbol="TEPAT",
                 total_lps=100),
            _row(pool_address="PoolSepi", ca="MintSepi", symbol="SEPI",
                 total_lps=12),
            _row(pool_address="PoolTanpa", ca="MintTanpa", symbol="TANPA",
                 total_lps=None),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        hijau = f'<span style="color:{bp.LP_GREEN_COLOR};font-weight:700;">'
        # `_num_or_dash` default ".0f" (tanpa pemisah ribuan) — yang berubah
        # hanya warnanya, angkanya tetap seperti sebelum batch ini.
        self.assertIn(hijau + "1234</span>", body)
        self.assertNotIn(hijau + "100</span>", body)
        self.assertNotIn(hijau + "12</span>", body)
        self.assertIn('>100</div>', body)
        self.assertIn(">12</div>", body)
        # tanpa angka tetap dash, tidak hijau, tidak error
        self.assertIn("lps", body)

    def test_kolom_rugcheck_tampil_dan_tidak_menyaring(self):
        """Kolom RugCheck menulis verdict + likuiditas ringkas (bukan saringan).

        Baris dengan laporan ``ok`` tampil berwarna sesuai verdict; baris tanpa
        laporan (hasil scan lama / mint gagal diambil) menulis ``—`` + "belum
        di-fetch" di tooltip — TIDAK pernah "AMAN". Keduanya tetap ada di
        tabel: kolom ini informasi.
        """
        app = self._app()
        laporan = {
            "ok": True, "verdict": "RUG", "color": "#dc2626",
            "honeypot": True, "critical": ["mintable"], "minor": [],
            "market_count": 2, "market_cap": 1_295_891.0,
            "liquidity_total_usd": 103_300.0,
            "liquidity_lines": ["METEORA\u00b7SOL $102.5K", "RAYDIUM\u00b7SOL $740"],
            "notes": ["pool terbesar 99% — sisanya debu"],
        }
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolRug", ca="MintRug", symbol="RUGY",
                 rugcheck=laporan),
            _row(pool_address="PoolBersih", ca="MintBersih", symbol="BERSIH"),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(">RugCheck<", body)
        self.assertIn('<span style="color:#dc2626;font-weight:700;">RUG'
                      "</span>", body)
        # $103.3K < ambang $500K → tulisan likuiditas MERAH (permintaan user
        # 2026-09-17); barisnya tetap tampil — kolom ini informasi.
        self.assertIn('<span style="color:#dc2626;font-weight:700;">$103.3K'
                      '</span> liq \u00b7 2 pool', body)
        self.assertIn("honeypot checker", body)
        # Baris tanpa laporan tetap tampil dengan — (bukan disaring keluar).
        self.assertIn("$BERSIH", body)
        angka_dash = '<div class="watchlist-metric-value">\u2014</div>'
        self.assertIn(angka_dash, body)
        self.assertIn("belum di-fetch", body)

    def test_volat_di_luar_rentang_alasannya_muncul_di_tabel_dilewati(self):
        """Volatility di luar rentang disembunyikan total, tidak tampil di mana pun.

        Permintaan user: hasil yang gugur karena gugur: volatility langsung
        sembunyikan total, tidak ditampilkana dimanapun.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA")],
            fetched=3,
            hidden=[_row(pool_address="PoolSepi", ca="MintSepi", symbol="SEPI",
                         **_fv(60.0, 0.5)),
                    _row(pool_address="PoolGede", ca="MintGede",
                         symbol="GEDE", **_fv(600.0, 42.0))])
        app.run()
        captions = "\n".join(node.value for node in app.caption)
        # Volatility gugur langsung dibuang total (0 dilewati)
        self.assertIn("1 pool 24H tampil \u00b7 0 dilewati \u00b7 listing 3 pool.",
                      captions)
        keys = [button.key or "" for button in app.button]
        self.assertNotIn("best-pool-toggle-hidden-24h", keys)
        body = "\n".join(node.value for node in app.markdown)
        self.assertNotIn("gugur: volatility", body)
        self.assertNotIn("SEPI", body)
        self.assertNotIn("GEDE", body)

    def test_f_v_besar_ditulis_bulat_dengan_pemisah_ribuan(self):
        """Rasio jutaan tidak lagi tampil ``6328266.1×`` (laporan user).

        Pool live GOLD-XAUt0 2026-09-15 (angka API apa adanya):
        ``fee_active_tvl_ratio`` 63291759.0 ÷ ``volatility`` 10.0 = 6.329.176×.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h",
            [_row(pool_address="PoolGold", ca="MintGold", symbol="GOLD",
                  pool_name="GOLD/XAUt0",
                  fee_active_tvl_ratio=63291759.0,
                  volatility=10.0)],
            fetched=1)
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("6,329,176×", body)
        # Format lama (satu desimal, tanpa pemisah ribuan) hilang total —
        # termasuk dari tooltip & atribut title.
        self.assertNotIn("6329175.9", body)
        self.assertNotIn("6329175.95", body)

    def test_kolom_token_menampilkan_pasangan_pool(self):
        """Kolom Token menulis pasangan pool-nya, mis. ``ALLINU/SOL``.

        Permintaan user 2026-09-15: *"kolom Token sekarang akan menunjukkan
        pasangan pairnya, misal ALLINU/SOL"* — simbol `$TOKEN` tetap baris
        pertama, pasangan pool di bawahnya, alamat mint tetap ada.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolAllinu", ca="MintAllinu",
                 symbol="ALLINU", pool_name="ALLINU/SOL"),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(">Token<", body)          # judul kolom tidak berubah
        self.assertIn("$ALLINU", body)
        self.assertIn('<span class="watchlist-pair"', body)
        self.assertIn(">ALLINU/SOL</span>", body)
        self.assertIn("MintAlli", body)         # alamat mint tetap tampil

    def test_tanpa_nama_pool_tidak_ada_baris_pasangan(self):
        """Hasil scan lama (tanpa ``pool_name``) tidak dikarang pasangannya."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolLawas", ca="MintLawas", symbol="LAWAS"),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$LAWAS", body)
        # CSS-nya ikut ter-render di body, jadi yang diperiksa elemen sel-nya.
        self.assertNotIn('<span class="watchlist-pair"', body)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class StrategyColumnTest(BestPoolCardTest):
    """Kolom **STRATEGY** paling kanan (permintaan user 2026-09-19).

    Permintaan user (verbatim): *"Kasih kolom baru dipaling kanan STRATEGY —
    jika total likuiditas >500K, dikolom strategy ditulis, hybird 7030,
    bidask 3070 - full range — jika total likuiditas <500K, dikolom strategy
    ditulis, hybird 5050, bidask - full range"*. Teksnya **verbatim**
    (termasuk "hybird"), aturannya satu sumber di :mod:`gmgn_liquidity`, dan
    kolomnya hanya ada di tabel utama — tabel "▶ N pool dilewati" tetap 13
    kolom (konfirmasi user 2026-09-19).
    """

    LIQ_TINGGI = 884_912.0     # > ambang $500K → hybird 7030, bidask 3070
    LIQ_RENDAH = 103_300.0     # < ambang $500K → hybird 5050, bidask

    def _laporan(self, usd):
        """Laporan RugCheck berisi likuiditas total GMGN (sumber angka STRATEGY)."""
        return {"ok": True, "verdict": "AMAN", "color": "#16a34a",
                "honeypot": False, "critical": [], "minor": [],
                "market_count": 1, "market_cap": 1_295_891.0,
                "liquidity_total_usd": usd, "liquidity_source": "gmgn",
                "liquidity_lines": [], "notes": []}

    def test_strategy_7030_bila_likuiditas_di_ambang(self):
        """> $500K → ``hybird 7030, bidask 3070 - full range``."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolGede", ca="MintGede", symbol="GEDE",
                 rugcheck=self._laporan(self.LIQ_TINGGI)),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        # Judul kolomnya ada di paling kanan (setelah Pool).
        self.assertIn(">STRATEGY<", body)
        self.assertLess(body.index(">Pool<"), body.index(">STRATEGY<"))
        # Teks verbatim — "- full range" dibungkus span nowrap supaya frasanya
        # tidak terpenggal (``best_pool_ui._strategy_cell_html``).
        self.assertIn("hybird 7030, bidask 3070", body)
        self.assertIn('<span class="bp-strategy-range"> - full range</span>',
                      body)
        # Baris kecil menulis bukti angkanya + ambang yang dipakai.
        self.assertIn("liq $884.9K \u00b7 $500K", body)
        # Sel tabelnya cuma satu dan memakai cabang ATAS. (Tooltip card +
        # komentar CSS di ``render_styles`` ikut ter-render di body, jadi
        # pemeriksaan cabang dilakukan pada elemen sel-nya.)
        sel = ('<div class="watchlist-metric-value">hybird 7030, bidask 3070'
               '<span class="bp-strategy-range"> - full range</span></div>')
        self.assertEqual(body.count(sel), 1)
        self.assertNotIn("hybird 5050, bidask<span", body)

    def test_strategy_5050_bila_likuiditas_di_bawah_ambang(self):
        """< $500K → ``hybird 5050, bidask - full range`` (tanpa angka 3070)."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolTipis", ca="MintTipis", symbol="TIPIS",
                 rugcheck=self._laporan(self.LIQ_RENDAH)),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        # Sel tabelnya memakai cabang BAWAH, verbatim dan tanpa angka 3070
        # (permintaan user menulis "bidask - full range").
        sel = ('<div class="watchlist-metric-value">hybird 5050, bidask'
               '<span class="bp-strategy-range"> - full range</span></div>')
        self.assertEqual(body.count(sel), 1)
        # Tooltip card + komentar CSS juga memuat teks cabang ATAS sebagai
        # riwayat permintaan user, jadi yang membuktikan baris ini dapat
        # cabang bawah adalah bentuk selnya di atas (bukan pencarian string
        # "7030" di seluruh body).
        # Barisnya tetap tampil — kolom STRATEGY tidak pernah menyaring.
        self.assertIn("$TIPIS", body)

    def test_strategy_tak_terukur_pakai_cabang_rendah_dengan_alasan(self):
        """Likuiditas tak terbaca → teks tetap ada + alasannya di tooltip."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolButa", ca="MintButa", symbol="BUTA"),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("hybird 5050, bidask", body)
        self.assertIn("liq \u2014 \u00b7 $500K", body)
        self.assertIn("likuiditas total tidak terbaca", body)

    def test_sel_strategy_di_kolom_strategy_bukan_di_kolom_pool(self):
        """Penempatan sel 2026-09-21: *"ini taruh di kolom strategy, bukan di
        pool"*.

        ``app.markdown`` mengumpulkan elemen per kolom kiri→kanan, jadi urutan
        di body = urutan visual: tautan kolom **Pool** harus muncul SEBELUM
        sel **STRATEGY**. Versi awal (2026-09-19) menaruh selnya menumpuk di
        kolom Pool (dua markdown dalam satu kolom) sehingga selnya justru
        muncul sebelum ``pool-links`` dan kolom STRATEGY kosong.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolTipis", ca="MintTipis", symbol="TIPIS",
                 rugcheck=self._laporan(self.LIQ_RENDAH)),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        sel = ('<div class="watchlist-metric-value">hybird 5050, bidask'
               '<span class="bp-strategy-range"> - full range</span></div>')
        self.assertEqual(body.count(sel), 1)
        pool_idx = body.index('<div class="pool-links">')
        strategy_idx = body.index(sel)
        self.assertLess(pool_idx, strategy_idx,
                        "sel STRATEGY harus di kanan kolom Pool, bukan "
                        "menumpuk di dalamnya")

    def test_tabel_dilewati_tanpa_kolom_strategy(self):
        """Tabel "▶ N pool dilewati" tetap 13 kolom (konfirmasi user)."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h",
            [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA",
                  rugcheck=self._laporan(self.LIQ_TINGGI))],
            fetched=3,
            hidden=[_row(pool_address="PoolSepi", ca="MintSepi", symbol="SEPI",
                         **_fv(2.0, 6.0))])
        app.run()
        app.button(key="best-pool-toggle-hidden-24h").click().run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$SEPI", body)
        self.assertIn(">Pool<", body)
        self.assertNotIn(">STRATEGY<", body)
        # Tidak ada SEL strategi (CSS ``render_styles`` ikut ter-render di
        # body, jadi yang dihitung elemen sel-nya).
        self.assertNotIn('<span class="bp-strategy-range">', body)
        self.assertNotIn("hybird 5050, bidask <", body)

    def test_ukuran_huruf_tabel_diperbesar_tanpa_ubah_tata_letak(self):
        """Tulisan tabel diperbesar, lebar kolom & tata letak tidak berubah.

        Permintaan user 2026-09-19: *"agak perbesar tulisan table semuanya ya,
        tapi tidak mempengaruhi tampilan"*. Judul kolom memakai
        :data:`best_pool_ui.HEADER_FONT_SIZE` (dulu 0.72rem inline), isi sel
        lewat class ``.watchlist-*``/``.pool-links`` di
        ``dashboard_components.render_styles``, dan **lebar kolom**
        (``_COL_SPEC`` / ``_col_spec``) tidak ikut berubah.
        """
        styles_src = (Path(__file__).resolve().parent.parent
                      / "dashboard_components.py").read_text(encoding="utf-8")
        self.assertEqual(bp.HEADER_FONT_SIZE, "0.82rem")
        self.assertIn(f".bp-col-title {{font-size:{bp.HEADER_FONT_SIZE};",
                      styles_src)
        # nowrap: judul tetap satu baris walau hurufnya lebih besar, jadi
        # tinggi header (dan tinggi tiap baris tabel) tidak bertambah.
        self.assertIn("white-space:nowrap", styles_src)
        # Ukuran huruf isi sel yang dipakai tabel listing ikut naik dari
        # nilai lamanya (0.95/0.65/0.75rem).
        for naik in (".watchlist-metric-value {font-size:1.05rem;",
                     ".watchlist-metric-sub {font-size:.74rem;",
                     ".watchlist-symbol {font-size:1.2rem;",
                     ".pool-links a {font-size:.84rem;"):
            self.assertIn(naik, styles_src)
        for lama in (".watchlist-metric-value {font-size:.95rem;}",
                     ".watchlist-metric-sub {font-size:.65rem;}",
                     ".pool-links a {font-size:.75rem;"):
            self.assertNotIn(lama, styles_src)
        # Override mobile ikut naik dengan perbandingan yang sama.
        self.assertIn(".watchlist-metric-value { font-size: 0.98rem !important; }",
                      styles_src)
        self.assertNotIn(".watchlist-metric-value { font-size: 0.88rem !important; }",
                         styles_src)
        # Tata letak TIDAK boleh ikut berubah: bobot kolom tetap sama persis
        # seperti sebelum STRATEGY (13 kolom dasar) + satu kolom STRATEGY.
        self.assertEqual(bp._COL_SPEC,
                         [1.4, 1.0, 0.75, 0.58, 0.95, 0.5, 0.58, 0.55, 0.68,
                          0.8, 0.6, 1.0, 1.05])
        self.assertEqual(bp._col_spec(show_strategy=True)[-1],
                         bp.STRATEGY_COL_WIDTH)
        self.assertEqual(len(bp._col_spec(show_strategy=True)),
                         len(bp._col_spec(show_strategy=False)) + 1)

    def test_tooltip_card_menjelaskan_aturan_strategy(self):
        tip = bp.best_pool_tooltip()
        self.assertIn("STRATEGY", tip)
        self.assertIn("hybird 7030, bidask 3070 - full range", tip)
        self.assertIn("hybird 5050, bidask - full range", tip)
        # Ambangnya tidak disalin di UI — dibaca dari konstanta GMGN.
        self.assertIn("$500K", tip)


class StrategyColumnPlacementTest(unittest.TestCase):
    """Sel STRATEGY harus ditulis ke kolom STRATEGY — bukan menumpuk di Pool.

    Permintaan user 2026-09-21 (verbatim): *"hybird 5050, bidask - full range
    — ini taruh di kolom strategy, bukan di pool"*. Versi awal kolom
    (2026-09-19) mengirim selnya lewat daftar ``cells`` yang dirender
    ``enumerate(cells, start=1)`` — daftar itu hanya sampai
    ``POOL_COL_INDEX``, jadi teks strategi menumpuk di kolom **Pool** (dua
    elemen dalam satu kolom) sementara kolom **STRATEGY** kosong.

    Tes ini memasang ``streamlit`` palsu yang merekam markdown per indeks
    kolom — penempatannya jadi diuji persis per kolom, tanpa AppTest dan
    tanpa runtime Streamlit.
    """

    def _render(self, rows, **kw):
        """``_render_best_table`` dengan streamlit palsu.

        Return: daftar per pemanggilan ``st.columns`` — ``[0]`` baris judul,
        ``[1..]`` baris data; tiap baris = list objek kolom ber-``.html``.
        """
        import types

        panggilan = []

        class _Kolom:
            def __init__(self, indeks):
                self.indeks = indeks
                self.html = []

            def markdown(self, html, **_kw):
                self.html.append(html)

        def _columns(spec):
            baris = [_Kolom(i) for i in range(len(spec))]
            panggilan.append(baris)
            return baris

        st_palsu = types.ModuleType("streamlit")
        st_palsu.columns = _columns
        st_palsu.markdown = lambda *a, **k: None
        args = {"lane": "24h", "mark_tops": False}
        args.update(kw)
        with mock.patch.dict("sys.modules", {"streamlit": st_palsu}):
            bp._render_best_table(rows, **args)
        return panggilan

    def test_index_kolom_strategy_tepat_di_kanan_pool(self):
        """``STRATEGY_COL_INDEX`` = kolom ke-14, tepat di kanan kolom Pool."""
        self.assertEqual(bp.POOL_COL_INDEX, 12)
        self.assertEqual(bp.STRATEGY_COL_INDEX, bp.POOL_COL_INDEX + 1)
        titles = bp._lane_titles("24h")
        self.assertEqual(titles[bp.POOL_COL_INDEX], "Pool")
        self.assertEqual(titles[bp.STRATEGY_COL_INDEX], "STRATEGY")
        self.assertEqual(bp.STRATEGY_COL_TITLE, titles[bp.STRATEGY_COL_INDEX])

    def test_sel_strategy_hanya_di_kolom_strategy(self):
        """Kolom Pool berisi tautan pool saja; kolom STRATEGY berisi selnya."""
        rows = [_row(pool_address="PoolTipis", ca="MintTipis", symbol="TIPIS")]
        header, baris = self._render(rows)[:2]
        # Judul kolom masing-masing di kolomnya sendiri.
        self.assertIn(">Pool<", header[bp.POOL_COL_INDEX].html[0])
        self.assertIn(">STRATEGY<", header[bp.STRATEGY_COL_INDEX].html[0])
        # Kolom Pool: SATU elemen (tautan pool) — bug lama menumpuk sel
        # strategi di sini sehingga kolomnya punya dua elemen.
        isi_pool = "".join(baris[bp.POOL_COL_INDEX].html)
        self.assertEqual(len(baris[bp.POOL_COL_INDEX].html), 1)
        self.assertIn('<div class="pool-links">', isi_pool)
        self.assertNotIn("hybird", isi_pool)
        self.assertNotIn("bp-strategy-range", isi_pool)
        # Kolom STRATEGY: SATU elemen, teks verbatim cabang rendah (baris
        # tanpa laporan likuiditas = tak terukur → cabang < $500K).
        isi_strategy = "".join(baris[bp.STRATEGY_COL_INDEX].html)
        self.assertEqual(len(baris[bp.STRATEGY_COL_INDEX].html), 1)
        self.assertIn('<div class="watchlist-metric-value">hybird 5050, bidask'
                      '<span class="bp-strategy-range"> - full range</span>'
                      '</div>', isi_strategy)
        self.assertNotIn("pool-links", isi_strategy)
        # Tidak ada kolom lain yang boleh memuat teks strategi.
        for indeks, kolom in enumerate(baris):
            if indeks != bp.STRATEGY_COL_INDEX:
                self.assertNotIn("hybird", "".join(kolom.html),
                                 f"kolom {indeks} tidak boleh memuat teks "
                                 "strategi")

    def test_sel_strategy_cabang_tinggi_juga_di_kolom_strategy(self):
        """Cabang > $500K juga di kolom STRATEGY, bukan di kolom Pool."""
        rows = [_row(pool_address="PoolGede", ca="MintGede", symbol="GEDE",
                     rugcheck={"ok": True, "verdict": "AMAN",
                               "liquidity_total_usd": 884_912.0,
                               "liquidity_source": "gmgn"})]
        _header, baris = self._render(rows)[:2]
        isi_pool = "".join(baris[bp.POOL_COL_INDEX].html)
        isi_strategy = "".join(baris[bp.STRATEGY_COL_INDEX].html)
        self.assertNotIn("hybird", isi_pool)
        self.assertIn('<div class="watchlist-metric-value">hybird 7030, '
                      'bidask 3070<span class="bp-strategy-range"> '
                      '- full range</span></div>', isi_strategy)

    def test_tabel_dilewati_tanpa_sel_strategy_sama_sekali(self):
        """``show_strategy=False`` (tabel dilewati): 13 kolom, teks strategi
        tidak muncul di kolom mana pun — termasuk bukan di kolom Pool."""
        rows = [_row(pool_address="PoolSepi", ca="MintSepi", symbol="SEPI")]
        panggilan = self._render(rows, show_strategy=False)
        self.assertEqual(len(panggilan), 2)  # header + satu baris data
        for baris in panggilan:
            self.assertEqual(len(baris), 13)
            isi_semua = "".join("".join(kol.html) for kol in baris)
            self.assertNotIn("hybird", isi_semua)
            self.assertNotIn("bp-strategy-range", isi_semua)
        isi_pool = "".join(panggilan[1][bp.POOL_COL_INDEX].html)
        self.assertIn('<div class="pool-links">', isi_pool)


class StrategyRuleTest(unittest.TestCase):
    """Aturan teks STRATEGY satu sumber di :mod:`gmgn_liquidity`.

    Ambangnya ambang yang sama dengan warna angka likuiditas kolom RugCheck
    (:data:`gmgn_liquidity.MIN_TOTAL_LIQ_USD`), jadi tidak ada dua angka 500K
    yang bisa lari sendiri-sendiri.
    """

    def test_teks_verbatim_permintaan_user(self):
        self.assertEqual(gl.STRATEGY_LIQ_HIGH,
                         "hybird 7030, bidask 3070 - full range")
        self.assertEqual(gl.STRATEGY_LIQ_LOW, "hybird 5050, bidask - full range")

    def test_strategy_for_liquidity_ikuti_ambang(self):
        tinggi, rendah = gl.STRATEGY_LIQ_HIGH, gl.STRATEGY_LIQ_LOW
        self.assertEqual(gl.strategy_for_liquidity(500_000.01), tinggi)
        self.assertEqual(gl.strategy_for_liquidity(884_912.0), tinggi)
        self.assertEqual(gl.strategy_for_liquidity(499_999.99), rendah)
        self.assertEqual(gl.strategy_for_liquidity(0), rendah)
        # Tepat di ambang + tak terukur → cabang rendah (user hanya memberi
        # dua cabang; tiap baris harus punya saran, tidak boleh sel kosong).
        self.assertEqual(gl.strategy_for_liquidity(gl.MIN_TOTAL_LIQ_USD), rendah)
        self.assertEqual(gl.strategy_for_liquidity(None), rendah)
        self.assertEqual(gl.strategy_for_liquidity("bukan angka"), rendah)

    def test_row_total_liquidity_pakai_laporan_rugcheck_dulu(self):
        row = {"rugcheck": {"ok": True, "liquidity_total_usd": 750_000.0,
                            "liquidity_source": "gmgn"},
               "gmgn_liq": {"ok": True, "usd": 120_000.0, "source": "gmgn"}}
        usd, source = gl.row_total_liquidity_usd(row)
        self.assertEqual(usd, 750_000.0)
        self.assertIn("RugCheck", source)
        # Laporan rugcheck gagal → fallback ke tempelan gmgn_liq.
        usd, source = gl.row_total_liquidity_usd(
            {"rugcheck": {"ok": False}, "gmgn_liq": {"ok": True,
                                                     "usd": 120_000.0,
                                                     "source": "gmgn"}})
        self.assertEqual(usd, 120_000.0)
        self.assertIn("GMGN", source)

    def test_row_strategy_menulis_bukti_untuk_tooltip(self):
        info = gl.row_strategy({"rugcheck": {"ok": True,
                                             "liquidity_total_usd": 884_912.0,
                                             "liquidity_source": "gmgn"}})
        self.assertEqual(info["text"], gl.STRATEGY_LIQ_HIGH)
        self.assertTrue(info["measured"])
        self.assertIn("$884.9K", info["reason"])
        self.assertIn("> $500K", info["reason"])

        buta = gl.row_strategy({})
        self.assertEqual(buta["text"], gl.STRATEGY_LIQ_LOW)
        self.assertFalse(buta["measured"])
        self.assertIn("tidak terukur", buta["reason"])

    def test_di_bawah_cutoff_peringkat_dihitung_cabang_rendah(self):
        """GMGN tanpa angka tapi mint terbukti di bawah cutoff → rendah."""
        row = {"gmgn_liq": {"ok": True, "usd": None, "below_cutoff": True,
                            "cutoff_usd": 149_000.0, "source": "gmgn_rank"}}
        usd, source = gl.row_total_liquidity_usd(row)
        self.assertIsNone(usd)
        self.assertIn("cutoff", source)
        info = gl.row_strategy(row)
        self.assertEqual(info["text"], gl.STRATEGY_LIQ_LOW)
        self.assertFalse(info["measured"])

    def test_sel_strategy_ui_memakai_aturan_yang_sama(self):
        """``best_pool_ui._strategy_cell`` tidak menyalin ambangnya sendiri."""
        nilai, sub, tip = bp._strategy_cell(
            {"rugcheck": {"ok": True, "liquidity_total_usd": 103_300.0,
                          "liquidity_source": "gmgn"}})
        self.assertIn("hybird 5050, bidask", nilai)
        self.assertIn('<span class="bp-strategy-range"> - full range</span>',
                      nilai)
        self.assertIn("liq $103.3K \u00b7 $500K", sub)
        self.assertIn("STRATEGY dari likuiditas total", tip)

        # Ambang digeser → teks UI ikut (bukti tidak ada angka hardcoded).
        with mock.patch.object(gl, "MIN_TOTAL_LIQ_USD", 50_000.0), \
                mock.patch.object(gl, "LIQ_GREEN_MIN_USD", 50_000.0), \
                mock.patch.object(gl, "MIN_LABEL", "$50K"):
            nilai2, sub2, _tip2 = bp._strategy_cell(
                {"rugcheck": {"ok": True, "liquidity_total_usd": 103_300.0,
                              "liquidity_source": "gmgn"}})
        self.assertIn("hybird 7030, bidask 3070", nilai2)
        self.assertIn("$50K", sub2)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class BubbleMapColumnRemovedTest(BestPoolCardTest):
    """Kolom Bubble Map dihapus, tautan 🫧-nya pindah ke kolom Pool.

    Permintaan user 2026-09-19 (verbatim): *"hapus tentang bubblemap, sisakan
    hyperlink ke bubblemapnya saja"*. Status cluster/top holder/warning tidak
    ditampilkan lagi, enrichment Bubblemaps tidak dijalankan saat scan, dan
    satu-satunya yang tersisa adalah tautan ke ``v2.bubblemaps.io``.
    """

    # ``row["bubblemap"]["url"]`` baris hasil scan 2026-09-18 berisi URL
    # BERSIH (``bubblemaps.bubblemap_url`` tidak pernah meng-escape HTML);
    # ``links`` yang meng-escape-nya sekali saat menulis atribut ``href`` —
    # jadi yang muncul di body adalah bentuk ``&amp;``.
    URL_MINT_RAW = ("https://v2.bubblemaps.io/map?address=MintBub"
                    "&chain=solana")
    URL_MINT = URL_MINT_RAW.replace("&", "&amp;")

    def test_tidak_ada_kolom_bubble_map_hanya_tautan(self):
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolBub", ca="MintBub", symbol="BUBY",
                 # Hasil scan 2026-09-18 masih membawa laporan Bubblemaps —
                 # isinya tidak boleh tampil lagi, tapi URL-nya tetap dipakai
                 # supaya tautan baris lama tidak berubah tujuan.
                 bubblemap={"ok": True, "clusters": 4, "top_holder_pct": 7.2,
                            "largest_cluster_pct": 9.1, "level": "WASPADA",
                            "color": "#a16207", "warning": "Top holder 7.2%",
                            "url": self.URL_MINT_RAW}),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        # Kolomnya hilang total: judul, angka cluster, holder terbesar,
        # warning. (Body ikut memuat CSS ``render_styles``, jadi yang di-pin
        # teks SEL-nya, bukan kata "cluster" mentah.)
        self.assertNotIn(">Bubble Map<", body)
        self.assertNotIn("Top holder 7.2%", body)
        self.assertNotIn("largest", body)
        self.assertNotIn("bubblemap_failed", body)
        # Tooltip card boleh menyebut penghapusannya (riwayat permintaan user),
        # tapi SEL kolomnya tidak boleh dirender lagi — modul ``bubblemaps``
        # bahkan tidak diimpor ``best_pool_ui`` sama sekali sejak 2026-09-19.
        ui_src = (Path(__file__).resolve().parent.parent
                  / "best_pool_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("from bubblemaps import", ui_src)
        self.assertNotIn("_bubble_cell_parts", ui_src)
        # Yang tersisa: tautan 🫧 di kolom Pool (bareng 🌊/🦅/📋).
        self.assertIn('class="bubblemap-link"', body)
        self.assertIn(self.URL_MINT, body)
        self.assertIn("\U0001f9e7", body)
        self.assertIn("Copy link HawkFi: "
                      "https://www.hawkfi.ag/meteora/PoolBub", body)
        # Caption rekap tidak lagi menyebut "N tanpa Bubble Map".
        captions = "\n".join(node.value for node in app.caption)
        self.assertNotIn("Bubble Map", captions)

    def test_tautan_dihitung_dari_mint_bila_laporan_tidak_ada(self):
        """Baris baru (tanpa ``row["bubblemap"]``) tetap punya tautan 🫧."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolBaru", ca="MintBub", symbol="BARU"),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(self.URL_MINT, body)
        self.assertIn('class="bubblemap-link"', body)

    def test_scan_tidak_menjalankan_enrichment_bubblemaps(self):
        """``_run_lane_scan`` mengirim ``bubblemap=False`` secara eksplisit."""
        app = self._app()
        kwargs_seen: list = []

        def fake_scan(lane, **kwargs):
            kwargs_seen.append(kwargs)
            return self._result("24h", [_row(pool_address="P24", ca="M24",
                                             symbol="THR")])

        with mock.patch.object(ms, "scan_best_lane", side_effect=fake_scan):
            app.button(key="best-pool-scan-24h").click().run()
        self.assertEqual(len(kwargs_seen), 1)
        self.assertIs(kwargs_seen[0].get("bubblemap"), False)

    def test_tooltip_card_tidak_menjelaskan_kolom_bubble_map(self):
        """Tooltip tidak lagi menjelaskan ISI kolom Bubble Map.

        Kutipan permintaan user (*"hapus tentang bubblemap …"*) sengaja tetap
        ada di tooltip sebagai riwayat — konvensi repo: permintaan user
        dikutip apa adanya. Yang harus hilang adalah penjelasan kolomnya
        (cluster, holder terbesar, ambang warning Bubblemaps).
        """
        tip = bp.best_pool_tooltip()
        for lama in ("menampilkan status Bubblemaps",
                     "jumlah cluster, % holder terbesar",
                     "cluster terbesar \u22658% WASPADA",
                     "Bubble Map, Pool"):
            self.assertNotIn(lama, tip)
        # Penjelasannya diganti: tautan 🫧 di kolom Pool + alasan penghapusan.
        self.assertIn("v2.bubblemaps.io", tip)
        self.assertIn("hapus tentang bubblemap", tip)


class BubbleMapScanDefaultTest(unittest.TestCase):
    """``scan_best_lane`` tidak lagi memanggil Bubblemaps secara default."""

    def setUp(self):
        def _fake_gmgn_attach(rows, **_kw):
            for row in rows:
                row["gmgn_liq"] = {"ok": False}
            return rows

        for patch in (
                mock.patch("gmgn_liquidity.attach_total_liquidity",
                           side_effect=_fake_gmgn_attach),
                mock.patch("rugchecker.attach_to_rows",
                           side_effect=lambda rows, **_kw: [
                               dict(row, rugcheck={"ok": False})
                               for row in rows])):
            patch.start()
            self.addCleanup(patch.stop)

    @staticmethod
    def _fake_enrich(rows, **_kw):
        return [dict(row, analysis={"holders": {"dust_pct_mc": 0.02,
                                                "dust_count": 5,
                                                "total_fetched": 1000,
                                                "wallets_analyzed": 900}},
                     dust_pct_mc=0.02, dust_count=5) for row in rows]

    def _scan(self, **kwargs):
        with mock.patch.object(ms, "fetch_best_pools",
                               return_value=[_pool("P-OK", "MintOK")]), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich), \
                mock.patch("bubblemaps.attach_to_rows") as attach:
            attach.side_effect = lambda rows, **_kw: [
                dict(row, bubblemap={"ok": True, "clusters": 2})
                for row in rows]
            result = ms.scan_best_lane("24h", max_wallets=2000, **kwargs)
        return result, attach

    def test_default_tidak_memanggil_bubblemaps(self):
        result, attach = self._scan()
        attach.assert_not_called()
        self.assertNotIn("bubblemap", result["rows"][0])
        self.assertEqual(result["bubblemap_failed"], 0)

    def test_kwarg_true_masih_bisa_menyalakan(self):
        """Kwarg-nya tetap ada (pola ``safeguard=True``) untuk tooling."""
        result, attach = self._scan(bubblemap=True)
        self.assertEqual(attach.call_count, 1)
        self.assertEqual(result["rows"][0]["bubblemap"]["clusters"], 2)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class BestPoolCacheTest(unittest.TestCase):
    """Persistensi hasil scan 🏆 Best Pool Meteora (cache berkas lokal).

    Streamlit membuat session baru tiap refresh browser (F5), sehingga tanpa
    cache hasil scan lenyap padahal enrichment holder-nya memakan menit.
    """

    def setUp(self):
        # Runner pytest sudah memasang fixture ``_iso_scan_cache``; runner
        # ``unittest`` mematikan cache (``tests/__init__.py``), jadi tes ini
        # menyiapkan direktorinya sendiri.
        tmp = tempfile.TemporaryDirectory(prefix="best-pool-cache-")
        self.addCleanup(tmp.cleanup)
        previous = {name: os.environ.get(name)
                    for name in ("SCAN_CACHE", "SCAN_CACHE_DIR")}

        def _restore():
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.addCleanup(_restore)
        os.environ["SCAN_CACHE"] = "1"
        os.environ["SCAN_CACHE_DIR"] = tmp.name

    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: {}),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: {"updated_at": None,
                                                  "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: {"tokens": {}}),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=90)

    def test_scan_menyimpan_hasil_ke_cache(self):
        app = self._app()
        app.run()
        with mock.patch.object(ms, "scan_best_lane",
                               return_value={"rows": [
                                   _row(pool_address="PoolCache",
                                        ca="MintCache", symbol="CACHE")],
                                   "hidden_rows": [], "error": "",
                                   "fetched": 1, "hidden_metric": 0,
                                   "hidden_dust": 0, "skipped_quote": 0,
                                   "dropped_volatility": 0, "lane": "24h",
                                   "analyzed_at": 1}):
            app.button(key="best-pool-scan-24h").click().run()
        self.assertEqual(len(app.exception), 0)
        key = bp.best_lane_session_key("24h")
        self.assertTrue(scan_result_cache.cache_path(key).exists())
        payload = scan_result_cache.load_result(key)
        self.assertEqual([row["pool_address"] for row in payload["rows"]],
                         ["PoolCache"])

    def test_refresh_browser_memulihkan_hasil_dari_cache(self):
        """Sesi baru tetap menampilkan tabel; cache dihapus → kembali kosong."""
        key = bp.best_lane_session_key("24h")
        scan_result_cache.save_result(key, {
            "rows": [_row(pool_address="PoolCache", ca="MintCache",
                          symbol="CACHE")],
            "hidden_rows": [], "error": "", "fetched": 3, "hidden_metric": 0,
            "hidden_dust": 0, "skipped_quote": 0, "dropped_volatility": 0,
            "lane": "24h", "analyzed_at": 1})
        fresh = self._app()
        fresh.run()
        self.assertEqual(len(fresh.exception), 0)
        body = "\n".join(node.value for node in fresh.markdown)
        self.assertIn("$CACHE", body)
        self.assertEqual(fresh.session_state[key]["fetched"], 3)

        scan_result_cache.clear_result(key)
        kosong = self._app()
        kosong.run()
        self.assertEqual(len(kosong.exception), 0)
        self.assertNotIn("$CACHE", "\n".join(node.value
                                             for node in kosong.markdown))
        self.assertIn("belum di-scan", "\n".join(node.value
                                                 for node in kosong.caption))


if __name__ == "__main__":
    unittest.main()
