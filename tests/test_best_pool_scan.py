"""Coverage 🏆 Scan Best Pool Meteora (kriteria 2026-09-13: dua tombol 24H / 30M).

Permintaan user 2026-09-13: *"kayaknya untuk timeframe 30m harus kita pisah
tombol deteksinya dan tabel serta fungsi fee/v lebih besar … di scan meteora
pool, kita akan punya 2 tombol 24H dan 30M"*. Yang di-pin di file ini:

- **dua tombol card**, satu per timeframe: ``best-pool-scan-24h`` dan
  ``best-pool-scan-30m``; satu tombol hanya mengambil ``timeframe`` itu di API
  (bukan lagi satu listing gabungan 24H + 30M);
- **saringan lane sebelum enrichment**: 24H ``F/V >= BEST_FV_24H_MIN`` (5×,
  inklusif), 30M ``F/V > BEST_FV_30M_MIN`` (1× = fee harus lebih besar dari
  volatility). Di bawah ambang → **langsung skip**, ``enrich_pools`` tidak
  pernah dipanggil (kuota Helius aman), barisnya masuk ``hidden_rows`` dengan
  alasan di ``best_gaps`` — **kecuali** volatility 0: dibuang penuh dari
  listing (2026-09-14 lanjutan, permintaan user: *"jika volatility 0 jangan
  tampilkan, karena tidak ada pergerakan disitu"*), tidak dihitung di
  ``hidden_metric``, jumlah pembuangannya tercatat di ``dropped_volatility``;
- query API: ``pool_type=dlmm&&active_tvl>=50000`` (``fee_pct>=2`` **dihapus**
  2026-09-13; pool ber-fee rendah seperti EMBER/USDC harus muncul);
- urutan tiap tabel (permintaan user 2026-09-15 lanjutan: *"sebentar, kita
  urutkan fee/TVL paling besar dulu, baru perkalian f/v"*): **Fee/TVL
  terbesar** → **F/V terbesar** → volume/active TVL → dust %MC terkecil;
- dust, volatility minimal, volume 24 jam, tier fee dan LPs **bukan**
  saringan — dan tidak boleh dihidupkan balik;
- **Top10 holder di atas 20% supply dibuang** (``BEST_TOP10_MAX_PCT``,
  permintaan user 2026-09-16: *"scan meteora, TOP 10 diatas 20% jangan
  ditampilkan lagi"*) — saringan kedua di :func:`row_best_gaps` setelah ambang
  F/V lane, ikut **sebelum** fetch holder, di kedua lane; batas inklusif
  (20,0% persis masih tampil) dan ``None`` (tidak terukur) tidak gugur;
- **satu tabel per lane** di ``best_pool_ui``: hasil disimpan di
  ``best_pool_scan_24h`` / ``best_pool_scan_30m``, kolom ``Src`` dihapus,
  toggle "disembunyikan" + prefix key ⭐ ikut per-lane, dan hasil sesi lama
  (gabungan) dipecah sekali saat render;
- **tata letak kolom 2026-09-14**: Token, F/V, **Fee/TVL tepat di kanan F/V**
  (permintaan user), Volat, Dust %MC, lalu Fee % (fee trading pool), MC,
  A.TVL di depan; kolom Dust (jumlah wallet) dihapus, judul kolom volume
  mengikuti window lane ("Vol 24h"/"Vol 30m", begitu pula tooltip
  fee/volume), dan sel volatility terbesar + F/V tertinggi + **Fee/TVL
  tertinggi** tabel utama disorot **hijau tua menyala**
  (``TOP_HIGHLIGHT_COLOR``, seri ikut semua, tabel
  dilewati tidak ditandai).
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
import meteora_screener as ms

APP = str(Path(__file__).resolve().parent.parent / "app.py")
SOL = ms.SOL_MINT
QUERY = "pool_type=dlmm&&active_tvl>=50000"


def _token(addr, symbol="TOK", mc=1_000_000, top10=20.0):
    return {"address": addr, "symbol": symbol, "name": symbol,
            "market_cap": mc, "fdv": mc, "price": 0.01, "holders": 1200,
            "top_holders_pct": top10}


def _pool(addr="P1", mint="MintAAA", *, active_tvl=60_000, ratio=40.0,
          volatility=6.2, total_lps=88, fee_pct=2.0, volume=1_200_000,
          fee=24_000.0, volume_change_pct=12.5, top10=20.0):
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
        "total_lps": 88, "top_holders_pct": 20.0,
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
        """Query server = DLMM + active TVL; fee_pct sudah DIHAPUS."""
        self.assertEqual(ms.best_filter_by(), QUERY)
        self.assertNotIn("fee_pct", ms.best_filter_by())
        self.assertEqual(ms.BEST_ACTIVE_TVL_MIN, 50_000.0)

    def test_fetch_sends_lane_params(self):
        for lane in ("24h", "30m"):
            with self.subTest(lane=lane):
                with mock.patch.object(ms, "_http_get",
                                       return_value={"data": []}) as http:
                    ms.fetch_best_pools(timeframe=lane)
                args, _kwargs = http.call_args
                self.assertEqual(args[0], ms.POOLS_URL)
                self.assertEqual(args[1], {
                    "page_size": 50, "timeframe": lane, "category": "top",
                    "filter_by": QUERY,
                })

    def test_payload_rows_only(self):
        with mock.patch.object(ms, "_http_get",
                               return_value={"data": [{"pool_address": "P1"},
                                                      "rusak", None]}):
            pools = ms.fetch_best_pools()
        self.assertEqual(pools, [{"pool_address": "P1"}])


class LaneRuleTest(unittest.TestCase):
    """Satu ambang per lane, semua teks UI membaca konstanta yang sama."""

    def test_constants(self):
        self.assertEqual(ms.BEST_FV_24H_MIN, 5.0)
        self.assertEqual(ms.BEST_FV_30M_MIN, 1.0)
        self.assertTrue(ms.lane_fv_inclusive("24h"))
        self.assertFalse(ms.lane_fv_inclusive("30m"))
        self.assertEqual(ms.lane_fv_sign("24h"), "≥")
        self.assertEqual(ms.lane_fv_sign("30m"), ">")
        self.assertEqual(ms.BEST_LANES, ("24h", "30m"))

    def test_normalize_alias(self):
        self.assertEqual(ms.normalize_best_lane("24H"), "24h")
        self.assertEqual(ms.normalize_best_lane("24 jam"), "24h")
        self.assertEqual(ms.normalize_best_lane("30m"), "30m")
        self.assertEqual(ms.normalize_best_lane("1h"), "30m")
        self.assertEqual(ms.normalize_best_lane(None), "24h")
        self.assertEqual(ms.normalize_best_lane("", default=None), None)
        self.assertEqual(ms.normalize_best_lane("5m", default=None), None)
        self.assertEqual(ms.best_lane_lanes("both"), ("24h", "30m"))
        self.assertEqual(ms.best_lane_lanes("30m"), ("30m",))

    def test_gate_label_ikuti_konstanta(self):
        self.assertEqual(ms.best_lane_gate_label("24h"), "24H: F/V ≥ 5×")
        self.assertEqual(ms.best_lane_gate_label("30m"), "30M: F/V > 1×")
        with mock.patch.object(ms, "BEST_FV_30M_MIN", 3.0):
            self.assertEqual(ms.best_lane_gate_label("30m"), "30M: F/V > 3×")


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

    def test_lanes_keep_separate_records(self):
        """``both``: satu pool di dua timeframe = dua record (compat)."""
        rows = ms.best_rows_from_lanes([_pool("P1")], [_pool("P1")])
        self.assertEqual([(r["timeframe"], r["pool_address"]) for r in rows],
                         [("24h", "P1"), ("30m", "P1")])

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
        # Saringan lane tetap lolos (F/V jauh di atas 5×) — formatnya tidak
        # mengubah keputusan apa pun.
        self.assertEqual(ms.row_best_gaps(row, lane="24h"), [])

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
        self.assertEqual(ms.row_best_gaps(_row()), [])
        self.assertEqual(ms.row_best_gaps(_row(timeframe="30m",
                                               **_fv(12.4, 6.2))), [])

    def test_24h_boundary_inklusif(self):
        self.assertEqual(ms.row_best_gaps(_row(**_fv(50.0, 10.0))), [])
        self.assertEqual(ms.row_best_gaps(_row(**_fv(49.999, 10.0))),
                         ["24H: F/V < 5×"])

    def test_30m_boundary_strict(self):
        """Fee "lebih besar" = strict: F == V (rasio tepat 1×) di-skip."""
        self.assertEqual(ms.row_best_gaps(_row(timeframe="30m", **_fv(10, 10))),
                         ["30M: F/V ≤ 1×"])
        self.assertEqual(ms.row_best_gaps(_row(timeframe="30m",
                                               **_fv(10.001, 10))), [])

    def test_volatility_nol_selalu_gugur(self):
        """V=0 (F/V ∞) bukan kelolosan di lane mana pun (2026-09-14)."""
        self.assertEqual(ms.row_best_gaps(_row(**_fv(0.5, 0))),
                         ["24H: volatility 0 — F/V tidak terukur"])
        self.assertEqual(ms.row_best_gaps(_row(timeframe="30m",
                                               **_fv(0.5, 0))),
                         ["30M: volatility 0 — F/V tidak terukur"])

    def test_metrik_hilang_atau_asing_gugur(self):
        self.assertEqual(len(ms.row_best_gaps(_row(volatility=None))), 1)
        self.assertEqual(len(ms.row_best_gaps(_row(fee_active_tvl_ratio=None))), 1)
        self.assertEqual(ms.row_best_gaps(_row(fee_active_tvl_ratio=float("nan"),
                                               volatility=1.0)),
                         ["metrik F/V tidak tersedia atau tidak valid"])
        self.assertEqual(ms.row_best_gaps(_row(timeframe="5m")),
                         ["timeframe tidak dikenal"])

    def test_teks_gap_ikuti_konstanta(self):
        with mock.patch.object(ms, "BEST_FV_24H_MIN", 8.0):
            self.assertEqual(ms.row_best_gaps(_row(**_fv(20.0, 5.0))),
                             ["24H: F/V < 8×"])
        with mock.patch.object(ms, "BEST_FV_30M_MIN", 2.0):
            self.assertEqual(
                ms.row_best_gaps(_row(timeframe="30m", **_fv(10.0, 5.0))),
                ["30M: F/V ≤ 2×"])

    def test_saringan_lama_tetap_mati(self):
        """Dust / volatility / volume / tier fee / LPs bukan syarat — Top10 ya.

        Kriteria 2026-09-13 menghapus saringan-saringan itu (permintaan user:
        "dust% syaratnya hapus saja", "minimal volume" dicabut, chip BEST
        POOL dihapus) — angka-angkanya boleh diacak, barisnya tetap lolos.
        **Top10 dikecualikan sejak 2026-09-16**: ambangnya dihidupkan lagi
        dengan angka baru (20%, bukan 30% lama) atas permintaan user
        "TOP 10 diatas 20% jangan ditampilkan lagi" — jadi baris ini tetap
        lolos karena `_row()` membawa Top10 20,0% (batas inklusif).
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
        # mengubah kelolosan siapa pun.
        with mock.patch.object(ms, "BEST_DUST_MAX_PCT", 0.0), \
                mock.patch.object(ms, "BEST_VOLATILITY_MIN", 99.0), \
                mock.patch.object(ms, "BEST_VOLUME_24H_MIN", 1e12):
            self.assertEqual(ms.row_best_gaps(_row()), [])
            self.assertTrue(ms.row_dust_ok(_row()))
            self.assertTrue(ms.row_volume_ok(_row()))

    def test_filter_best_rows_memakai_lane_yang_dipaksa(self):
        rows = [_row(pool_address="KECIL", **_fv(20.0, 10.0)),
                _row(pool_address="BESAR", **_fv(60.0, 10.0))]
        kept, hidden_metric, hidden_dust = ms.filter_best_rows(rows)
        self.assertEqual([r["pool_address"] for r in kept], ["BESAR"])
        self.assertEqual((hidden_metric, hidden_dust), (1, 0))
        kept, hidden_metric, _ = ms.filter_best_rows(rows, lane="30m")
        self.assertEqual([r["pool_address"] for r in kept], ["KECIL", "BESAR"])
        self.assertEqual(hidden_metric, 0)

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
        """Batas "di atas 20%" = > 20 gugur; tepat 20,0% masih tampil."""
        self.assertEqual(ms.BEST_TOP10_MAX_PCT, 20.0)
        self.assertEqual(ms.row_top10_pct(_row(top_holders_pct=23.5)), 23.5)
        self.assertIsNone(ms.row_top10_pct(_row(top_holders_pct=None)))
        self.assertIsNone(ms.row_top10_pct(None))
        for pct, ok in ((0.0, True), (19.999, True), (20.0, True),
                        (20.01, False), (45.0, False), (100.0, False)):
            with self.subTest(pct=pct):
                row = _row(top_holders_pct=pct)
                self.assertEqual(ms.row_top10_ok(row), ok)
                self.assertEqual(not ms.row_best_gaps(row), ok)
                if ok:
                    self.assertIsNone(ms.row_top10_over(row))
                else:
                    self.assertEqual(ms.row_top10_over(row), pct)

    def test_top10_hilang_tidak_gugur(self):
        """Tanpa angka Top10 tidak ada bukti konsentrasi — barisnya tetap lolos."""
        for missing in (None, "", "bukan angka", True, float("nan")):
            with self.subTest(top10=missing):
                row = _row(top_holders_pct=missing)
                self.assertIsNone(ms.row_top10_pct(row))
                self.assertTrue(ms.row_top10_ok(row))
                self.assertEqual(ms.row_best_gaps(row), [])

    def test_top10_gugur_di_kedua_lane_dengan_alasan(self):
        """Satu aturan untuk 24H dan 30M; teks gap menyebut lane + angkanya."""
        self.assertEqual(
            ms.row_best_gaps(_row(top_holders_pct=45.0)),
            ["24H: Top10 45% > 20% — holder terpusat"])
        self.assertEqual(
            ms.row_best_gaps(_row(timeframe="30m", top_holders_pct=20.5,
                                  **_fv(30.0, 10.0))),
            ["30M: Top10 20.5% > 20% — holder terpusat"])

    def test_top10_hanya_dicek_setelah_ambang_lane_lolos(self):
        """Gugur F/V sudah cukup jadi alasan — tidak ada gap kedua."""
        row = _row(top_holders_pct=99.0, **_fv(2.0, 10.0))
        self.assertEqual(ms.row_best_gaps(row), ["24H: F/V < 5×"])

    def test_teks_dan_keputusan_top10_ikuti_konstanta(self):
        with mock.patch.object(ms, "BEST_TOP10_MAX_PCT", 12.0):
            self.assertEqual(ms.row_best_gaps(_row(top_holders_pct=15.0)),
                             ["24H: Top10 15% > 12% — holder terpusat"])
            self.assertFalse(ms.row_top10_ok(_row(top_holders_pct=15.0)))
        with mock.patch.object(ms, "BEST_TOP10_MAX_PCT", 90.0):
            self.assertEqual(ms.row_best_gaps(_row(top_holders_pct=45.0)), [])
            self.assertTrue(ms.row_top10_ok(_row(top_holders_pct=45.0)))

    def test_filter_best_rows_menghitung_top10_sebagai_dilewati(self):
        """Gugur Top10 dihitung sama seperti gugur F/V (tetap auditabel 24H)."""
        rows = [_row(pool_address="BERSIH", top_holders_pct=12.0),
                _row(pool_address="PUSAT", top_holders_pct=88.0),
                _row(pool_address="NOLVOL", top_holders_pct=88.0,
                     **_fv(50.0, 0))]
        kept, hidden_metric, hidden_dust = ms.filter_best_rows(rows)
        self.assertEqual([r["pool_address"] for r in kept], ["BERSIH"])
        self.assertEqual((hidden_metric, hidden_dust), (1, 0))


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


class ScanLaneTest(unittest.TestCase):
    """Satu tombol = satu lane; kandidat gagal tidak menyentuh Helius."""

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
        pools = [_pool("P-OK", "MintOK", ratio=40.0, volatility=6.2),   # 6,45×
                 _pool("P-KECIL", "MintKcl", ratio=12.4, volatility=6.2),  # 2×
                 _pool("P-NOL", "MintNol", ratio=0.0, volatility=6.2)]
        seen: list = []

        with mock.patch.object(ms, "fetch_best_pools",
                               side_effect=lambda **kw: seen.append(kw["timeframe"]) or pools), \
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
        self.assertEqual(result["gate"], "24H: F/V ≥ 5×")
        self.assertEqual(result["error"], "")

    def test_30m_hanya_ambil_lane_dan_saring_strict(self):
        pools = [_pool("P-SAMA", "MintSma", ratio=10.0, volatility=10.0),  # 1×
                 _pool("P-DOMINAN", "MintDom", ratio=30.0, volatility=10.0),  # 3×
                 _pool("P-SEPI", "MintSep", ratio=1.0, volatility=10.0)]
        seen: list = []
        with mock.patch.object(ms, "fetch_best_pools",
                               side_effect=lambda **kw: seen.append(kw["timeframe"]) or pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("30m", max_wallets=2000)
        self.assertEqual(seen, ["30m"])
        self.assertEqual([r["pool_address"]
                          for r in enrich.call_args.args[0]], ["P-DOMINAN"])
        self.assertEqual([r["pool_address"] for r in result["rows"]],
                         ["P-DOMINAN"])
        self.assertEqual({tuple(r["best_gaps"]) for r in result["hidden_rows"]},
                         {("30M: F/V ≤ 1×",)})
        self.assertEqual(result["gate"], "30M: F/V > 1×")

    def test_volatility_nol_dibuang_dari_listing_dan_hitungan(self):
        """Vol 0: gugur gate, TANPA scan holder, dibuang dari hidden_rows.

        2026-09-14 lanjutan — pool tanpa pergerakan tidak ditampilkan di mana
        pun; sisa jejaknya hanya counter ``dropped_volatility`` untuk audit.
        """
        pools = [_pool("P-OK", "MintOK", ratio=40.0, volatility=6.2),   # 6,45×
                 _pool("P-KECIL", "MintKcl", ratio=12.4, volatility=6.2),  # 2×
                 _pool("P-NOL", "MintNol", ratio=50.0, volatility=0.0)]  # ∞
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

    def test_volatility_nol_dibuang_di_lane_30m(self):
        pools = [_pool("P-DOM", "MintDom", ratio=30.0, volatility=10.0),  # 3×
                 _pool("P-SAMA", "MintSma", ratio=10.0, volatility=10.0),  # 1×
                 _pool("P-NOL", "MintNol", ratio=1.0, volatility=0.0)]   # ∞
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("30m", max_wallets=2000)
        self.assertEqual([r["pool_address"] for r in enrich.call_args.args[0]],
                         ["P-DOM"])
        self.assertEqual([r["pool_address"] for r in result["hidden_rows"]],
                         ["P-SAMA"])
        self.assertEqual({tuple(r["best_gaps"]) for r in result["hidden_rows"]},
                         {("30M: F/V ≤ 1×",)})
        self.assertEqual(result["hidden_metric"], 1)
        self.assertEqual(result["dropped_volatility"], 1)

    def test_top10_di_atas_20_dibuang_sebelum_fetch_holder(self):
        """Saringan Top10 sejalur dengan ambang F/V: holder tidak pernah di-fetch.

        Permintaan user 2026-09-16: *"scan meteora, TOP 10 diatas 20% jangan
        ditampilkan lagi"*. Yang di atas batas gugur sebelum ``enrich_pools``
        (kuota Helius aman) dan masuk ``hidden_rows`` dengan alasannya; yang
        tepat 20% dan yang tanpa angka tetap lolos.
        """
        pools = [_pool("P-BERSIH", "MintBersih", ratio=40.0, volatility=6.2,
                       top10=12.0),
                 _pool("P-PAS", "MintPas", ratio=30.0, volatility=6.0,
                       top10=20.0),
                 _pool("P-PUSAT", "MintPusat", ratio=60.0, volatility=6.0,
                       top10=45.0)]
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertEqual(sorted(r["pool_address"] for r in enrich.call_args.args[0]),
                         ["P-BERSIH", "P-PAS"])
        self.assertEqual(sorted(r["pool_address"] for r in result["rows"]),
                         ["P-BERSIH", "P-PAS"])
        self.assertEqual([r["pool_address"] for r in result["hidden_rows"]],
                         ["P-PUSAT"])
        self.assertEqual({tuple(r["best_gaps"]) for r in result["hidden_rows"]},
                         {("24H: Top10 45% > 20% — holder terpusat",)})
        self.assertEqual(result["hidden_metric"], 1)
        # Baris yang dibuang tidak pernah sampai ke layar tabel utama.
        self.assertNotIn("P-PUSAT", [r["pool_address"] for r in result["rows"]])

    def test_top10_gugur_di_lane_30m_pula(self):
        """Satu aturan untuk kedua tombol — 30M juga membuang Top10 > 20%."""
        pools = [_pool("P-PUSAT", "MintPusat", ratio=30.0, volatility=10.0,
                       top10=21.0),
                 _pool("P-DOMINAN", "MintDom", ratio=30.0, volatility=10.0,
                       top10=5.0)]
        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=self._fake_enrich) as enrich:
            result = ms.scan_best_lane("30m", max_wallets=2000)
        self.assertEqual([r["pool_address"] for r in enrich.call_args.args[0]],
                         ["P-DOMINAN"])
        self.assertEqual([r["pool_address"] for r in result["rows"]],
                         ["P-DOMINAN"])
        self.assertEqual([r["pool_address"] for r in result["hidden_rows"]],
                         ["P-PUSAT"])

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
            result = ms.scan_best_lane("30m", max_wallets=2000)
        self.assertIn("30M: Meteora HTTP 503", result["error"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["fetched"], 0)

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
        """``scan_best_meteora(timeframe=...)`` = satu lane (bukan dua lagi)."""
        seen: list = []
        with mock.patch.object(ms, "fetch_best_pools",
                               side_effect=lambda **kw: seen.append(kw["timeframe"]) or []):
            ms.scan_best_meteora(max_wallets=2000, timeframe="30m")
        self.assertEqual(seen, ["30m"])


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

    def test_dua_tombol_lane_dan_judul_card(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(ms.BEST_CARD_TITLE, body)
        keys = [button.key or "" for button in app.button]
        self.assertIn("best-pool-scan-24h", keys)
        self.assertIn("best-pool-scan-30m", keys)
        # Tombol lama satu-listing-dua-lane harus hilang, jangan sampai ada
        # dua jalan masuk yang hasilnya beda.
        self.assertNotIn("best-pool-scan-now", keys)
        labels = [button.label for button in app.button
                  if (button.key or "").startswith("best-pool-scan-")]
        self.assertIn("🏆 Scan Best Pool 24H + Holder", labels)
        self.assertIn("🏆 Scan Best Pool 30M + Holder", labels)
        # Label "belum di-scan" = rekap, bukan deskripsi rule.
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("belum di-scan", captions)

    def test_tombol_scan_hanya_ambil_lane_yang_ditekan(self):
        app = self._app()
        calls: list = []
        result = self._result("30m", [_row(pool_address="P30", ca="M30",
                                           symbol="THR", timeframe="30m",
                                           **_fv(30.0, 10.0))])

        def fake_scan(lane, **_kwargs):
            calls.append(lane)
            return result

        with mock.patch.object(ms, "scan_best_lane", side_effect=fake_scan):
            app.button(key="best-pool-scan-30m").click().run()
        # Tombol 30M = satu scan lane 30M (bukan dua lane seperti dulu).
        self.assertEqual(calls, ["30m"])
        self.assertEqual(app.session_state["best_pool_lane"], "30m")
        stored = app.session_state["best_pool_scan_30m"]
        self.assertEqual([r["pool_address"] for r in stored["rows"]], ["P30"])
        # Lane 24H tidak disentuh sama sekali.
        self.assertNotIn("best_pool_scan_24h", app.session_state)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$THR", body)
        self.assertIn("30M · F/V > 1×", body)   # pill lane aktif
        self.assertIn("1 pool tersimpan", "\n".join(
            node.value for node in app.caption))

    def test_tabel_lane_aktif_saja_dan_tanpa_kolom_src(self):
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
        # Baris lane 30M tidak boleh ikut tampil di tabel 24H.
        self.assertNotIn("$LN30", body)
        self.assertNotIn("PoolLain", body)
        # Kolom Src dihapus bersama pemisahan lane; kolom F/V naik ke depan.
        self.assertNotIn(">Src<", body)
        self.assertIn(">F/V<", body)
        self.assertIn("syarat F/V ≥ 5×", body)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("1 pool 24H tampil · 1 dilewati · listing 4 pool.",
                      captions)
        keys = [button.key or "" for button in app.button]
        self.assertIn("best-pool-24h-star-PoolBest", keys)
        self.assertIn("best-pool-view-30m", keys)
        self.assertIn("best-pool-toggle-hidden-24h", keys)

    def test_30m_lolos_tampil_ok_dan_kandidat_gagal_tidak_tampil(self):
        """30M: sel F/V = OK untuk yang lolos; yang gagal tidak tampil sama
        sekali (tanpa toggle disembunyikan) — permintaan user 2026-09-14."""
        app = self._app()
        app.session_state["best_pool_scan_30m"] = self._result(
            "30m", [_row(pool_address="PoolOk", ca="MintOK", symbol="OKSYM",
                         timeframe="30m", **_fv(30.0, 10.0))],
            fetched=3, hidden=[_row(pool_address="PoolGagal", ca="MintFail",
                                    symbol="FAILSYM", timeframe="30m",
                                    **_fv(10.0, 10.0))])
        app.session_state["best_pool_lane"] = "30m"
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$OKSYM", body)
        # Baris lolos 30M: sel F/V menulis OK, bukan angka quotient.
        self.assertIn("syarat F/V > 1× terpenuhi", body)
        self.assertNotIn("3.0×", body)
        # Kandidat gagal 30M tidak ditampilkan dan tidak ada tombol toggle.
        self.assertNotIn("$FAILSYM", body)
        self.assertNotIn("MintFail", body)
        keys = [button.key or "" for button in app.button]
        self.assertNotIn("best-pool-toggle-hidden-30m", keys)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("1 pool 30M tampil · listing 3 pool.", captions)
        self.assertNotIn("dilewati", captions)

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
        self.assertIn("best-pool-hidden-24h-star-PoolHide",
                      [button.key or "" for button in app.button])
        captions = "\n".join(node.value for node in app.caption)
        # Caption = angka rekap + status barisnya, BUKAN teks rule/ambang
        # (ambang hanya di tooltip judul + sub sel F/V).
        self.assertIn("1 pool 24H disembunyikan ditampilkan", captions)
        self.assertNotIn("F/V ≤", captions)

    def test_top10_di_atas_20_tidak_tampil_di_tabel(self):
        """24H: baris Top10 45% hilang dari tabel lolos, muncul sebagai "dilewati".

        Sekaligus pin bahwa **hasil scan lama** yang sudah tersimpan di
        session_state dibersihkan ulang saat render — user tidak perlu scan
        lagi supaya pool berkonsentrasi tinggi hilang dari layar.
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBersih", ca="MintBersih",
                         symbol="BERSIH", top_holders_pct=12.0),
                    _row(pool_address="PoolPusat", ca="MintPusat",
                         symbol="PUSAT", top_holders_pct=45.0)],
            fetched=2)
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$BERSIH", body)
        self.assertNotIn("$PUSAT", body)
        self.assertNotIn("MintPusat", body)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("1 pool 24H tampil · 1 dilewati · listing 2 pool.",
                      captions)
        # Kandidat Top10 tetap bisa diaudit lewat listing disembunyikan 24H.
        app.button(key="best-pool-toggle-hidden-24h").click().run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$PUSAT", body)
        self.assertIn("gugur: Top10 45% > 20% — holder terpusat", body)

    def test_top10_di_atas_20_tidak_tampil_sama_sekali_di_30m(self):
        """30M: kandidat gugur (F/V atau Top10) memang tidak pernah ditampilkan."""
        app = self._app()
        app.session_state["best_pool_scan_30m"] = self._result(
            "30m", [_row(pool_address="PoolPusat", ca="MintPusat",
                         symbol="PUSAT30", timeframe="30m",
                         top_holders_pct=45.0, **_fv(30.0, 10.0))],
            fetched=2,
            hidden=[_row(pool_address="PoolKecil", ca="MintKecil",
                         symbol="KECIL30", timeframe="30m",
                         **_fv(10.0, 10.0))])
        app.session_state["best_pool_lane"] = "30m"
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertNotIn("$PUSAT30", body)
        self.assertNotIn("MintPusat", body)
        keys = [button.key or "" for button in app.button]
        self.assertNotIn("best-pool-toggle-hidden-30m", keys)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("0 pool 30M tampil · listing 2 pool.", captions)

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

    def test_hasil_lama_gabungan_dipecah_per_lane(self):
        """Sesi lama cuma punya ``best_pool_scan`` (24H+30M campur) → dipecah."""
        app = self._app()
        app.session_state["best_pool_scan"] = self._result(
            "both", [_row(pool_address="Pool24", ca="M24", symbol="DUA4",
                          timeframe="24h"),
                     _row(pool_address="Pool30", ca="M30", symbol="TIG0",
                          timeframe="30m", **_fv(15.0, 5.0))])
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([r["pool_address"] for r in
                          app.session_state["best_pool_scan_24h"]["rows"]],
                         ["Pool24"])
        self.assertEqual([r["pool_address"] for r in
                          app.session_state["best_pool_scan_30m"]["rows"]],
                         ["Pool30"])
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$DUA4", body)         # lane aktif default: 24H
        self.assertNotIn("$TIG0", body)
        app.button(key="best-pool-view-30m").click().run()
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$TIG0", body)
        self.assertNotIn("$DUA4", body)

    def test_error_lama_tetap_terbaca_setelah_migrasi(self):
        """Hasil lama tanpa baris (listing API gagal) tidak kehilangan pesan."""
        app = self._app()
        app.session_state["best_pool_scan"] = self._result(
            "both", [], fetched=0, error="Meteora HTTP 503")
        app.run()
        self.assertEqual(len(app.exception), 0)
        warnings = "\n".join(node.value for node in app.warning)
        self.assertIn("Meteora API: Meteora HTTP 503", warnings)
        self.assertEqual(app.session_state["best_pool_scan_24h"]["rows"], [])

    def test_detail_karakteristik_di_tooltip_bukan_caption(self):
        """Rule dua tombol ada di tooltip judul; caption hanya angka rekap."""
        import html as _html

        app = self._app()
        body = _html.unescape("\n".join(node.value for node in app.markdown))
        self.assertIn("title=\"Dua tombol = dua lane terpisah", body)
        for label in (f"pool_type=dlmm&&active_tvl>={int(ms.BEST_ACTIVE_TVL_MIN)}",
                      f"24H: F/V ≥ {ms.BEST_FV_24H_MIN:g}×",
                      f"30M: F/V > {ms.BEST_FV_30M_MIN:g}×",
                      "Urutan tiap tabel: Fee/TVL terbesar, lalu F/V terbesar"):
            self.assertIn(label, body)
        captions = "\n".join(node.value for node in app.caption)
        for rule_text in ("Urutan:", "disaring", "SEBELUM scan", "syarat",
                          "F/V ≥", "F/V >"):
            self.assertNotIn(rule_text, captions)
        # saringan yang sudah dicabut tidak boleh balik ke tooltip
        tooltip = bp.best_pool_tooltip()
        for gone in ("top 10 holder <", "total LPs >", "volatility >= 2%",
                     "volume 24 jam >= $1,000,000", "dust holder < 0,05%",
                     "fee_pct>="):
            self.assertNotIn(gone, tooltip)

    def test_tooltip_ambang_mengikuti_perubahan_konstanta(self):
        with mock.patch.object(ms, "BEST_FV_30M_MIN", 3.0):
            self.assertIn("30M: F/V > 3×", bp.best_pool_tooltip())
            self.assertIn("F/V > 3×", bp.best_lane_gate_text("30m"))
        with mock.patch.object(ms, "BEST_FV_24H_MIN", 7.0):
            self.assertIn("24H: F/V ≥ 7×", bp.best_pool_tooltip())
        with mock.patch.object(ms, "BEST_ACTIVE_TVL_MIN", 75_000.0):
            self.assertIn("active_tvl>=75000", bp.best_pool_tooltip())

    def test_empat_kolom_inti_di_depan_dan_kolom_dust_dihapus(self):
        """Urutan header: Token, F/V, Fee/TVL, Volat, Dust %MC … Dust dihapus."""
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result(
            "24h", [_row(pool_address="PoolBest", ca="MintAAA", symbol="AAA")])
        app.run()
        body = "\n".join(node.value for node in app.markdown)
        for header in (">Token<", ">F/V<", ">Fee/TVL<", ">Volat<", ">Dust %MC<"):
            self.assertIn(header, body)
        self.assertLess(body.index(">Token<"), body.index(">F/V<"))
        self.assertLess(body.index(">F/V<"), body.index(">Fee/TVL<"))
        self.assertLess(body.index(">Fee/TVL<"), body.index(">Volat<"))
        self.assertLess(body.index(">Volat<"), body.index(">Dust %MC<"))
        # Kolom konteks tetap ada SETELAH kolom depan; Fee % (fee trading
        # pool, mis. 0.5%/2%) tepat setelah Dust %MC (permintaan user
        # 2026-09-14).
        self.assertLess(body.index(">Dust %MC<"), body.index(">Fee %<"))
        self.assertLess(body.index(">Fee %<"), body.index(">MC<"))
        self.assertLess(body.index(">MC<"), body.index(">A.TVL<"))
        self.assertLess(body.index(">A.TVL<"), body.index(">Vol 24h<"))
        # "Dust hapus": kolom jumlah wallet tidak lagi dirender — header dan
        # sel sub "wallet" hilang dari tabel.
        self.assertNotIn(">Dust<", body)
        self.assertNotIn("jumlah wallet dust di bawah ambang dust", body)

    def test_kolom_fee_persen_menampilkan_fee_pool(self):
        """Fee % = fee trading pool (tier fee DLMM), bukan fee USD atau rasio.

        Nilai tampil sebagai persen tepat setelah Dust %MC; baris tanpa
        ``fee_pct`` (data lama di session_state) menampilkan ``—``.
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
        # Sel fee tampil sebagai nilai utama (bukan baris kecil) + sub label.
        self.assertIn('<div class="watchlist-metric-value">0.5%</div>', body)
        self.assertIn("pool fee", body)
        self.assertIn("fee trading pool", body)
        # Baris tanpa fee_pct → dash, bukan error / 0%.
        self.assertIn('<div class="watchlist-metric-value">—</div>', body)
        self.assertNotIn('<div class="watchlist-metric-value">0%</div>', body)
        # Kolom fee tampil untuk kedua lane (judul tabel 30M ikut dirender
        # lewat header yang sama, jadi cukup cek di 24H + lane 30M di bawah).
        app.session_state["best_pool_scan_30m"] = self._result(
            "30m", [_row(pool_address="PoolFee30", ca="MintF30", symbol="F30",
                         timeframe="30m", fee_pct=1.0, **_fv(30.0, 10.0))])
        app.session_state["best_pool_lane"] = "30m"
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn('<div class="watchlist-metric-value">1%</div>', body)

    def test_label_vol_dan_tooltip_fee_mengikuti_lane(self):
        """30M tidak boleh memakai label 24 jam — kolom Vol mengikuti lane."""
        app = self._app()
        app.session_state["best_pool_scan_30m"] = self._result(
            "30m", [_row(pool_address="Pool30", ca="Mint30", symbol="T30",
                         timeframe="30m", **_fv(30.0, 10.0))])
        app.session_state["best_pool_lane"] = "30m"
        app.run()
        self.assertEqual(len(app.exception), 0)
        # Batasi pembacaan ke card 🏆 Scan Best Pool Meteora saja.
        body = "\n".join(node.value for node in app.markdown)
        start = body.find(ms.BEST_CARD_TITLE)
        body = body[start:]
        self.assertIn(">Vol 30m<", body)
        self.assertNotIn(">Vol 24h<", body)
        self.assertIn("volume 30 menit", body)
        self.assertIn("fee 30 menit", body)
        self.assertNotIn("volume 24 jam", body)
        self.assertNotIn("fee 24 jam", body)

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
            _row(pool_address="PoolB", ca="MintB", symbol="BDUA",
                 fee_active_tvl_ratio=70.0, volatility=13.0),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertEqual(
            body.count(
                f'<span style="color:{neon};font-weight:800;">70.0%</span>'), 2)

    def test_sorot_hijau_ok_tertinggi_30m(self):
        """30M: semua OK tetap hijau biasa, hanya F/V tertinggi yang menyala."""
        neon = bp.TOP_HIGHLIGHT_COLOR
        app = self._app()
        app.session_state["best_pool_scan_30m"] = self._result("30m", [
            _row(pool_address="PoolTop30", ca="MintT30", symbol="T30",
                 timeframe="30m", fee_active_tvl_ratio=30.0, volatility=10.0),
            _row(pool_address="PoolLow30", ca="MintL30", symbol="L30",
                 timeframe="30m", fee_active_tvl_ratio=12.0, volatility=10.0),
        ])
        app.session_state["best_pool_lane"] = "30m"
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(f'<span style="color:{neon};font-weight:800;">OK</span>',
                      body)
        self.assertIn('<span style="color:#16a34a;">OK</span>', body)
        # Fee/TVL tertinggi lane 30M (30,0%) ikut disorot; 12,0% tidak.
        self.assertIn(
            f'<span style="color:{neon};font-weight:800;">30.0%</span>', body)
        self.assertNotIn(
            f'<span style="color:{neon};font-weight:800;">12.0%</span>', body)

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
                 **_fv(40.0, 8.0)),        # Fee/TVL 40% · F/V 5,0×
            _row(pool_address="PoolBesar", ca="MintBsr", symbol="BSR",
                 **_fv(40.0, 4.0)),         # Fee/TVL 40% · F/V 10,0×
        ])
        app.run()
        body = "\n".join(node.value for node in app.markdown)
        self.assertLess(body.index("$BSR"), body.index("$KCL"))
        self.assertIn("10.0×", body)
        self.assertIn("5.0×", body)
        # detail fee/TVL + volume tetap informasi (bukan saringan)
        for title in ("A.TVL", "Fee/TVL", "Vol 24h", "Volat", "Dust %MC"):
            self.assertIn(title, body)
        self.assertIn("kunci urut kedua", body)

    def test_f_v_besar_ditulis_bulat_dengan_pemisah_ribuan(self):
        """Rasio jutaan tidak lagi tampil ``6328266.1×`` (laporan user).

        Pool live GOLD-XAUt0 2026-09-15 (angka API apa adanya):
        ``fee_active_tvl_ratio`` 0,013025137688422304 ÷ ``volatility``
        2,057951587445997e-09 = 6.329.175,9×. Angka seperti inilah yang dulu
        tampil apa adanya sebagai ``6329175.9×`` (laporan user menyebut
        sampelnya sendiri: *"gold menunjukkan 6328266.1 F/V"*).
        """
        app = self._app()
        app.session_state["best_pool_scan_24h"] = self._result("24h", [
            _row(pool_address="PoolGold", ca="MintGold", symbol="GOLD",
                 pool_name="GOLD/XAUt0",
                 fee_active_tvl_ratio=0.013025137688422304,
                 volatility=2.057951587445997e-09),
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("6,329,176×", body)
        # Format lama (satu desimal, tanpa pemisah ribuan) hilang total —
        # termasuk dari tooltip & atribut title.
        self.assertNotIn("6329175.9", body)
        self.assertNotIn("6329175.95", body)
        # Volatility sekecil itu tidak boleh tertulis "0.00%" di tooltip:
        # justru angka itu penyebab rasio F/V-nya jutaan.
        self.assertIn("volatility 2.06e-09%", body)
        self.assertNotIn("volatility 0.00%", body)

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
