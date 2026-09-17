# -*- coding: utf-8 -*-
"""``gmgn_liquidity.py`` — likuiditas total GMGN: sumber angka + saringan.

Permintaan user 2026-09-17: *"kita rubah info liquidititas dari rugchecker.cc
ke gmgn saja"* + *"jika grand total liquiditas kurang dari 1M, jangan
tampilkan di hasil scan"*, disusul *"poolnya kok jadi kosong, padahal token
PAID harusnya masuk"* → ambangnya **$500K** (``MIN_TOTAL_LIQ_USD``); $1M
ternyata membuang seluruh listing (lihat ``AmbangTest``). Yang di-pin di file ini (semua offline —
:func:`gmgn_liquidity._post_json` / :func:`gmgn_liquidity._get_json` selalu
di-mock):

- parse respons ``mutil_window_token_info`` (daftar langsung / terbungkus
  ``{code, data}``; ``liquidity`` string/angka; hilang → ``None`` = unknown,
  BUKAN 0);
- parse fallback rank 100 teratas + inferensi *bawah cutoff* (mint yang tidak
  ada di daftar pasti di bawah cutoff → aman dianggap < ambang);
- ``fetch_total_liquidity``: batch POST (BATCH_SIZE per request), kegagalan
  satu batch → hanya batch itu yang turun ke rank, kegagalan total → source
  ``None`` (caller tidak boleh menyaring);
- cache berkas per-mint (TTL, ``use_cache=False``);
- ``row_gmgn_gap``: < ambang gugur, tepat ambang lolos (permintaan user:
  "kurang dari …"), tanpa bukti tidak pernah menyaring;
- integrasi: ``row_best_gaps`` memberi alasan GMGN sebagai saringan TERAKHIR
  (F/V/volat/Top10 tetap lebih keras), dan ``rugchecker.summarize`` /
  ``cell_parts`` menampilkan total GMGN (sumber "gmgn") — rincian per-DEX
  rugchecker.cc tidak lagi tampil; ``attach_to_rows` membaca ``row["gmgn_liq"]``.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gmgn_liquidity as gl
import meteora_screener as ms
import rugchecker as rc

MINT_A = "98kfF7rmsg1QDUEoCqNE7g7M1FdrTt92TEp2CLzypump"
MINT_B = "B9AHYeqb7nQk7LZUraw7rBCzYRjy2DRvE6NqWfFHKRdH2"
MINT_C = "C9AHYeqb7nQk7LZUraw7rBCzYRjy2DRvE6NqWfFHKRdH3"


def _patch_cache(tmp: Path):
    """Cache berkas diarahkan ke dir sementara (repo tidak dikotori)."""
    return patch.object(gl, "CACHE_PATH", tmp / "gmgn_liq_cache.json")


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

class ParseTokenInfoTest(unittest.TestCase):
    def test_daftar_langsung(self):
        out = gl._parse_token_info([
            {"address": MINT_A, "liquidity": "860179.5"},
            {"address": MINT_B, "liquidity": 2_000_000},
        ])
        self.assertEqual(out, {MINT_A: 860179.5, MINT_B: 2_000_000.0})

    def test_terbungkus_code_data(self):
        out = gl._parse_token_info({"code": 0, "data": [
            {"address": MINT_A, "liquidity": 1_900_000}]})
        self.assertEqual(out, {MINT_A: 1_900_000.0})

    def test_likuiditas_hilang_atau_junk_jadi_none(self):
        out = gl._parse_token_info([
            {"address": MINT_A},
            {"address": MINT_B, "liquidity": "n/a"},
            {"address": MINT_C, "liquidity": float("nan")},
        ])
        self.assertEqual(out, {MINT_A: None, MINT_B: None, MINT_C: None})

    def test_code_bukan_nol_melempar(self):
        with self.assertRaises(RuntimeError):
            gl._parse_token_info({"code": 403, "data": []})

    def test_bukan_daftar_melempar(self):
        with self.assertRaises(RuntimeError):
            gl._parse_token_info({"foo": "bar"})

    def test_kosong_melempar(self):
        with self.assertRaises(RuntimeError):
            gl._parse_token_info([])


class ParseRankTest(unittest.TestCase):
    def test_rank(self):
        out = gl._parse_rank({"data": {"rank": [
            {"address": MINT_A, "liquidity": 4_629_600},
            {"address": MINT_B, "liquidity": 15_000},
        ]}})
        self.assertEqual(out, {MINT_A: 4_629_600.0, MINT_B: 15_000.0})

    def test_kosong_melempar(self):
        with self.assertRaises(RuntimeError):
            gl._parse_rank({"data": {"rank": []}})


# ---------------------------------------------------------------------------
# fetch_total_liquidity
# ---------------------------------------------------------------------------

class FetchTest(unittest.TestCase):
    def test_post_sukses(self):
        calls = []

        def fake_post(url, body, *, timeout):
            calls.append(list(body["addresses"]))
            return [{"address": m, "liquidity": 860_179.0}
                    for m in body["addresses"]]

        with patch.object(gl, "_post_json", side_effect=fake_post):
            out = gl.fetch_total_liquidity([MINT_A, MINT_B], use_cache=False)
        self.assertEqual(calls, [[MINT_A, MINT_B]])
        for mint in (MINT_A, MINT_B):
            self.assertEqual(out[mint]["usd"], 860_179.0)
            self.assertEqual(out[mint]["source"], "gmgn_token_info")
            self.assertFalse(out[mint]["below_cutoff"])

    def test_mint_tidak_dilacak_gmgn_tetap_unknown(self):
        """GMGN menjawab tapi tidak memuat mint → unknown (Bukan 0), dan
        TIDAK ditandai below_cutoff — hanya fallback rank yang boleh
        mengimplikasikan 'pasti di bawah cutoff'."""
        with patch.object(gl, "_post_json",
                          return_value=[{"address": MINT_A,
                                         "liquidity": 2_000_000}]):
            out = gl.fetch_total_liquidity([MINT_A, MINT_B], use_cache=False)
        self.assertIsNone(out[MINT_B]["usd"])
        self.assertEqual(out[MINT_B]["source"], "gmgn_token_info")
        self.assertFalse(out[MINT_B]["below_cutoff"])

    def test_batch_dibagi_10(self):
        mints = [f"MINT{i:049d}" for i in range(25)]
        calls = []

        def fake_post(url, body, *, timeout):
            calls.append(len(body["addresses"]))
            return [{"address": m, "liquidity": 5_000_000}
                    for m in body["addresses"]]

        with patch.object(gl, "_post_json", side_effect=fake_post):
            gl.fetch_total_liquidity(mints, use_cache=False)
        self.assertEqual(calls, [10, 10, 5])

    def test_gagal_batch_turun_ke_rank(self):
        """Batch 1 gagal → hanya batch itu yang memakai rank: mint yang ada
        di rank dapat angkanya, yang tidak ada pasti di bawah cutoff."""
        mints1 = [f"MINT{i:049d}" for i in range(10)]      # batch GAGAL
        mints2 = [f"MINT{i:049d}" for i in range(10, 20)]  # batch sukses

        def fake_post(url, body, *, timeout):
            if any(m in mints1 for m in body["addresses"]):
                raise RuntimeError("HTTP 503")
            return [{"address": m, "liquidity": 7_000_000.0}
                    for m in body["addresses"]]

        with patch.object(gl, "_post_json", side_effect=fake_post), \
                patch.object(gl, "_get_json",
                             return_value={"data": {"rank": [
                                 {"address": mints1[0], "liquidity": 3_000_000},
                                 {"address": "LAST1", "liquidity": 15_000},
                             ]}}):
            out = gl.fetch_total_liquidity(mints1 + mints2, use_cache=False)
        # batch sukses: angka POST, sumber token-info
        for mint in mints2:
            self.assertEqual(out[mint]["usd"], 7_000_000.0)
            self.assertEqual(out[mint]["source"], "gmgn_token_info")
        # batch gagal + ada di rank: angka rank
        self.assertEqual(out[mints1[0]]["usd"], 3_000_000.0)
        self.assertEqual(out[mints1[0]]["source"], "gmgn_rank")
        # batch gagal + tidak ada di rank: pasti di bawah cutoff ($15K)
        for mint in mints1[1:]:
            self.assertTrue(out[mint]["below_cutoff"], mint)
            self.assertEqual(out[mint]["source"], "gmgn_rank")
            self.assertAlmostEqual(out[mint]["cutoff_usd"], 15_000.0)
            self.assertIsNone(out[mint]["usd"])

    def test_semua_gagal_source_none(self):
        with patch.object(gl, "_post_json",
                          side_effect=RuntimeError("HTTP 503")), \
                patch.object(gl, "_get_json",
                             side_effect=RuntimeError("HTTP 503")):
            out = gl.fetch_total_liquidity([MINT_A], use_cache=False)
        self.assertIsNone(out[MINT_A]["source"])
        self.assertIsNone(out[MINT_A]["usd"])
        self.assertFalse(out[MINT_A]["below_cutoff"])

    def test_cache_menahan_fetch_kedua(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        state = {"posts": 0}

        def fake_post(url, body, *, timeout):
            state["posts"] += 1
            return [{"address": m, "liquidity": 9_000_000}
                    for m in body["addresses"]]

        with _patch_cache(tmp), patch.object(gl, "_post_json",
                                             side_effect=fake_post):
            gl.fetch_total_liquidity([MINT_A], use_cache=True)
            gl.fetch_total_liquidity([MINT_A], use_cache=True)
        self.assertEqual(state["posts"], 1)

    def test_use_cache_false_tak_membaca_apa_pun(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        with _patch_cache(tmp), patch.object(gl, "_post_json",
                                             return_value=[
                                                 {"address": MINT_A,
                                                  "liquidity": 1}]) as post:
            gl.fetch_total_liquidity([MINT_A], use_cache=False)
        self.assertEqual(post.call_count, 1)
        self.assertFalse((tmp / "gmgn_liq_cache.json").exists())


# ---------------------------------------------------------------------------
# attach + saringan
# ---------------------------------------------------------------------------

def _row(mint="MINTX", **extra):
    row = {"ca": mint, "pool_address": "POOLX", "fee_active_tvl_ratio": 40.0,
           "volatility": 6.0, "top_holders_pct": 10.0,
           "timeframe": "24h"}
    row.update(extra)
    return row


class AttachTest(unittest.TestCase):
    def test_semua_baris_dapat_gmgn_liq(self):
        info = {MINT_A: {"usd": 860_179.0, "below_cutoff": False,
                         "source": "gmgn_token_info"}}
        rows = [_row(MINT_A), _row(MINT_B), _row("")]
        with patch.object(gl, "fetch_total_liquidity", return_value=info):
            out = gl.attach_total_liquidity(rows)
        self.assertIs(out, rows)  # mutasi di tempat, list yang sama
        self.assertTrue(rows[0]["gmgn_liq"]["ok"])
        self.assertEqual(rows[0]["gmgn_liq"]["usd"], 860_179.0)
        # MINT_B tak ada di respons → unknown
        self.assertFalse(rows[1]["gmgn_liq"]["ok"])
        # tanpa ca → unknown
        self.assertFalse(rows[2]["gmgn_liq"]["ok"])

    def test_below_cutoff_ok(self):
        info = {MINT_A: {"usd": None, "below_cutoff": True,
                         "source": "gmgn_rank", "cutoff_usd": 15_000}}
        with patch.object(gl, "fetch_total_liquidity", return_value=info):
            rows = gl.attach_total_liquidity([_row(MINT_A)])
        self.assertTrue(rows[0]["gmgn_liq"]["ok"])
        self.assertTrue(rows[0]["gmgn_liq"]["below_cutoff"])


class AmbangTest(unittest.TestCase):
    """Ambang $500K — dikalibrasi pakai angka GMGN yang benar-benar terukur.

    Laporan user 2026-09-17 (*"poolnya kok jadi kosong, padahal token PAID
    harusnya masuk"*): dengan ambang $1M, PAID (likuiditas GMGN
    ``/api/v1/token_info/sol/98kf…pump`` = **$884.912,398**) ikut terbuang
    bersama praktis seluruh listing (pill $153.496, ELON $149.542). Angka-angka
    itu di-pin di sini supaya ambang tidak bisa naik lagi tanpa tes ini
    diberitahu.
    """

    LIQ_PAID = 884_912.3982565559    # PAID 98kf…pump — harus TAMPIL
    LIQ_PILL = 153_496.33041956509   # pill — pool tipis, harus terbuang
    LIQ_ELON = 149_542.0879392728    # ELON — pool tipis, harus terbuang

    def test_ambang_500k(self):
        self.assertEqual(gl.MIN_TOTAL_LIQ_USD, 500_000.0)
        self.assertEqual(gl.MIN_LABEL, "$500K")

    def test_paid_di_atas_ambang_lolos(self):
        row = _row(MINT_A)
        row["gmgn_liq"] = {"ok": True, "usd": self.LIQ_PAID,
                           "below_cutoff": False, "source": "gmgn_token_info"}
        self.assertIsNone(gl.row_gmgn_gap(row))

    def test_pool_tipis_gugur(self):
        for liq in (self.LIQ_PILL, self.LIQ_ELON):
            row = _row(MINT_B)
            row["gmgn_liq"] = {"ok": True, "usd": liq, "below_cutoff": False,
                               "source": "gmgn_token_info"}
            gap = gl.row_gmgn_gap(row)
            self.assertIsNotNone(gap, liq)
            self.assertIn("< $500K", gap)

    def test_ambang_1m_lama_akan_membuang_paid(self):
        """Pin alasan penurunan ambang: $1M membuang PAID."""
        self.assertLess(self.LIQ_PAID, 1_000_000.0)
        self.assertGreater(self.LIQ_PAID, gl.MIN_TOTAL_LIQ_USD)


class GapTest(unittest.TestCase):
    def test_dibawah_ambang_gugur(self):
        row = _row()
        row["gmgn_liq"] = {"ok": True, "usd": 153_496.33,
                           "below_cutoff": False, "source": "gmgn_token_info"}
        gap = gl.row_gmgn_gap(row)
        self.assertIn("$153.5K", gap)
        self.assertIn(f"< {gl.MIN_LABEL}", gap)

    def test_tepat_ambang_lolos(self):
        """Permintaan user: "KURANG dari ambang" — tepat ambang tidak dibuang."""
        row = _row()
        row["gmgn_liq"] = {"ok": True, "usd": gl.MIN_TOTAL_LIQ_USD,
                           "below_cutoff": False, "source": "gmgn_token_info"}
        self.assertIsNone(gl.row_gmgn_gap(row))

    def test_nilai_mepet_ambang_tidak_terbaca_sama_dengan_ambang(self):
        """$499.999,99 tidak boleh tertulis "$500.0K < $500K" (kontradiktif).

        ``compact_usd`` membulatkan ke satu desimal, jadi nilai yang mepet
        ambang punya bentuk ringkas yang sama dengan ambangnya — di situ teks
        alasan memakai angka persis.
        """
        row = _row()
        row["gmgn_liq"] = {"ok": True, "usd": 499_999.99,
                           "below_cutoff": False, "source": "gmgn_token_info"}
        gap = gl.row_gmgn_gap(row)
        self.assertIn("$499,999.99 < $500K", gap)
        # Di luar kasus mepet: tetap ringkas.
        row["gmgn_liq"]["usd"] = 495_000.0
        self.assertIn("$495.0K < $500K", gl.row_gmgn_gap(row))

    def test_di_atas_ambang_lolos(self):
        row = _row()
        row["gmgn_liq"] = {"ok": True, "usd": 1_900_000.0,
                           "below_cutoff": False, "source": "gmgn_token_info"}
        self.assertIsNone(gl.row_gmgn_gap(row))

    def test_below_cutoff_gugur(self):
        row = _row()
        row["gmgn_liq"] = {"ok": True, "usd": None, "below_cutoff": True,
                           "source": "gmgn_rank", "cutoff_usd": 15_000}
        gap = gl.row_gmgn_gap(row)
        self.assertIn("cutoff peringkat", gap)
        self.assertIn("$15.0K", gap)

    def test_tanpa_bukti_tidak_menyaring(self):
        for gm in (None, {"ok": False}, {"ok": False, "usd": 10.0}):
            row = _row()
            if gm is not None:
                row["gmgn_liq"] = gm
            self.assertIsNone(gl.row_gmgn_gap(row))


class RowBestGapsIntegrationTest(unittest.TestCase):
    """GMGN = saringan TERAKHIR: alasan metrik lebih keras tetap menang."""

    def test_gmgn_gap_terakhir(self):
        row = _row()
        row["gmgn_liq"] = {"ok": True, "usd": 250_000.0,
                           "below_cutoff": False, "source": "gmgn_token_info"}
        gaps = ms.row_best_gaps(row, lane="24h")
        self.assertEqual(len(gaps), 1)
        self.assertIn("Likuiditas GMGN", gaps[0])

    def test_gmgn_lolos_tanpa_alasan(self):
        row = _row()
        row["gmgn_liq"] = {"ok": True, "usd": 2_500_000.0,
                           "below_cutoff": False, "source": "gmgn_token_info"}
        self.assertEqual(ms.row_best_gaps(row, lane="24h"), [])

    def test_tanpa_gmgn_liq_tidak_terpengaruh(self):
        """Baris hasil scan lama / ``gmgn=False``: perilaku seperti dulu."""
        self.assertEqual(ms.row_best_gaps(_row(), lane="24h"), [])

    def test_alasan_fv_tetap_lebih_keras(self):
        row = _row(fee_active_tvl_ratio=2.0)  # F/V = 0,33× < 5×
        row["gmgn_liq"] = {"ok": True, "usd": 10_000.0,
                           "below_cutoff": False, "source": "gmgn_token_info"}
        gaps = ms.row_best_gaps(row, lane="24h")
        self.assertEqual(len(gaps), 1)
        self.assertIn("F/V", gaps[0])
        self.assertNotIn("Likuiditas", gaps[0])


# ---------------------------------------------------------------------------
# kolom RugCheck: angka dari GMGN
# ---------------------------------------------------------------------------

def _rc_payload():
    """Payload rugchecker.cc bersih dengan dua pool (lihat test_rugchecker)."""
    flags = ("transfer_fee", "mintable", "freezable", "closable",
             "non_transferable", "balance_mutable",
             "transfer_fee_upgradable", "transfer_hook_upgradable",
             "metadata_mutable")
    return {"code": 0, "message": "success",
            "data": {"symbol": "PAID", "is_honeypot": False,
                     "security": dict.fromkeys(flags, 0),
                     "dex": [
                         {"pair_address": "PUMP1", "dex_id": "pumpswap",
                          "quote": "SOL",
                          "liquidity": {"usd": 116_680.38},
                          "market_cap": 1_295_891.0},
                         {"pair_address": "METEORA1", "dex_id": "meteora",
                          "quote": "SOL",
                          "liquidity": {"usd": 102_549.26},
                          "market_cap": 1_317_971.0}]}}


class CellPartsGmgnTest(unittest.TestCase):
    def test_angka_gmgn_ditampilkan(self):
        summary = rc.summarize(_rc_payload(), pool_address="METEORA1",
                               gmgn_total_usd=1_900_000.0)
        self.assertEqual(summary["liquidity_source"], "gmgn")
        self.assertEqual(summary["liquidity_total_usd"], 1_900_000.0)
        self.assertEqual(summary["liquidity_lines"], [])
        value, sub, tip = rc.cell_parts(summary)
        self.assertEqual(value, "AMAN")
        self.assertEqual(sub, "$1.90M liq")  # tanpa "N pool" (GMGN tak kirim)
        self.assertIn("likuiditas total (sumber: gmgn.ai): $1.90M", tip)
        self.assertNotIn("likuiditas (ringkas):", tip)

    def test_fallback_rugchecker_tetap_berlaku(self):
        summary = rc.summarize(_rc_payload(), pool_address="METEORA1")
        self.assertEqual(summary["liquidity_source"], "rugchecker")
        value, sub, tip = rc.cell_parts(summary)
        self.assertIn("liq · 2 pool", sub)
        self.assertIn("likuiditas (ringkas):", tip)

    def test_gmgn_nol_ataupun_hilang_bukan_sumber(self):
        for bad in (0, None, -5):
            summary = rc.summarize(_rc_payload(), gmgn_total_usd=bad)
            self.assertEqual(summary["liquidity_source"], "rugchecker")

    def test_share_pool_dihitung_terhadap_total_gmgn(self):
        # pool yang discan $102.5K dari total GMGN $1.9M ≈ 5,4% — catatan
        # kedalaman pool memakai total GMGN, bukan total per-DEX ($219K).
        summary = rc.summarize(_rc_payload(), pool_address="METEORA1",
                               gmgn_total_usd=1_900_000.0)
        share_txt = [n for n in summary["notes"]
                     if n.startswith("kedalaman pool ini")]
        self.assertTrue(share_txt)
        self.assertIn("5.4%", share_txt[0])

    def test_attach_to_rows_membaca_gmgn_liq(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        row = {"ca": MINT_A, "pool_address": "METEORA1",
               "gmgn_liq": {"ok": True, "usd": 1_900_000.0,
                            "below_cutoff": False,
                            "source": "gmgn_token_info"}}
        with _patch_rc_cache(tmp), \
                patch.object(rc, "fetch_raw", return_value=_rc_payload()):
            out = rc.attach_to_rows([dict(row)], use_cache=False)
        self.assertEqual(out[0]["rugcheck"]["liquidity_source"], "gmgn")
        self.assertEqual(out[0]["rugcheck"]["liquidity_total_usd"],
                         1_900_000.0)


def _patch_rc_cache(tmp: Path):
    return patch.object(rc, "CACHE_PATH", tmp / "rc_cache.json")


# ---------------------------------------------------------------------------
# alur scan end-to-end (offline)
# ---------------------------------------------------------------------------

def _best_pool(pool="P1", mint=MINT_A, *, ratio=40.0, volatility=6.2,
               top10=10.0):
    return {"pool_address": pool,
            "token_x": {"address": mint, "symbol": "PAID", "name": "Paid",
                        "market_cap": 10_000_000, "fdv": 10_000_000,
                        "price": 0.01, "holders": 20_000,
                        "top_holders_pct": top10},
            "token_y": {"address": ms.SOL_MINT, "symbol": "SOL",
                        "name": "Solana", "market_cap": 0, "fdv": 0,
                        "price": 100.0, "holders": 0, "top_holders_pct": 0},
            "tvl": 1_000_000, "active_tvl": 60_000,
            "fee_active_tvl_ratio": ratio, "volume": 1_200_000,
            "fee_pct": 2.0, "volatility": volatility}


class ScanLaneGmgnTest(unittest.TestCase):
    """``scan_best_lane``: baris di bawah ambang likuiditas GMGN masuk
    ``hidden_rows`` + alasan ``best_gaps``; di atas ambang tampil; GMGN mati →
    tidak ada yang dibuang (tanpa bukti)."""

    @staticmethod
    def _enrich(rows, **_kw):
        return [dict(r, analysis={"holders": {"dust_pct_mc": 0.02,
                                              "dust_count": 5,
                                              "total_fetched": 1000,
                                              "wallets_analyzed": 900}},
                     dust_pct_mc=0.02, dust_count=5) for r in rows]

    def _scan(self, pools, gmgn_map):
        def fake_fetch(*, timeframe, **_kw):
            return pools

        def fake_gmgn(rows, **_kw):
            for row in rows:
                mint = row.get("ca")
                info = gmgn_map.get(mint)
                if info is None:
                    row["gmgn_liq"] = {"ok": False}
                else:
                    row["gmgn_liq"] = {"ok": True, "usd": info,
                                       "below_cutoff": False,
                                       "source": "gmgn_token_info"}
            return rows

        with patch.object(ms, "fetch_best_pools", side_effect=fake_fetch), \
                patch.object(ms, "enrich_pools", side_effect=self._enrich), \
                patch("rugchecker.attach_to_rows",
                      side_effect=lambda rows, **_kw: [
                          dict(row, rugcheck={"ok": False})
                          for row in rows]), \
                patch("gmgn_liquidity.attach_total_liquidity",
                      side_effect=fake_gmgn):
            return ms.scan_best_lane("24h", max_wallets=2000,
                                     rugcheck=True)

    def test_dibawah_ambang_dilewati(self):
        pools = [_best_pool("P-BIG", MINT_A, ),
                 _best_pool("P-SMALL", MINT_B)]
        result = self._scan(pools, {MINT_A: 884_912.3982565559,   # PAID
                                    MINT_B: 153_496.33041956509})  # pill
        self.assertEqual([r["pool_address"] for r in result["rows"]],
                         ["P-BIG"])
        self.assertEqual([r["pool_address"] for r in result["hidden_rows"]],
                         ["P-SMALL"])
        reason = result["hidden_rows"][0]["best_gaps"][0]
        self.assertIn("Likuiditas GMGN", reason)
        self.assertIn("$153.5K", reason)
        self.assertIn("< $500K", reason)

    def test_paid_tidak_ikut_terbuang(self):
        """Regresi laporan user 2026-09-17: *"poolnya kok jadi kosong,
        padahal token PAID harusnya masuk"*.

        PAID lolos tiga saringan metrik (F/V 7,8×, volatility 3,0%, Top10
        15,18%) dan likuiditas GMGN-nya $884.912 — di atas ambang $500K, jadi
        barisnya harus ada di ``rows``, bukan ``hidden_rows``.
        """
        pools = [_best_pool("Gc5hVCBydc6k3Z7oc2cQEW4GThFQi2Fqk5HfKABqa2q8",
                            MINT_A, ratio=23.39434274894063,
                            volatility=2.9886436516396744, top10=15.177147896949576)]
        result = self._scan(pools, {MINT_A: 884_912.3982565559})
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual([r["pool_address"] for r in result["rows"]],
                         ["Gc5hVCBydc6k3Z7oc2cQEW4GThFQi2Fqk5HfKABqa2q8"])

    def test_gmgn_mati_tidak_membuang(self):
        pools = [_best_pool("P-BIG", MINT_A),
                 _best_pool("P-SMALL", MINT_B)]

        def fake_gmgn_dead(rows, **_kw):
            for row in rows:
                row["gmgn_liq"] = {"ok": False}
            return rows

        def fake_fetch(*, timeframe, **_kw):
            return pools

        with patch.object(ms, "fetch_best_pools", side_effect=fake_fetch), \
                patch.object(ms, "enrich_pools", side_effect=self._enrich), \
                patch("rugchecker.attach_to_rows",
                      side_effect=lambda rows, **_kw: [
                          dict(row, rugcheck={"ok": False})
                          for row in rows]), \
                patch("gmgn_liquidity.attach_total_liquidity",
                      side_effect=fake_gmgn_dead):
            result = ms.scan_best_lane("24h", max_wallets=2000)
        self.assertEqual([r["pool_address"] for r in result["rows"]],
                         ["P-BIG", "P-SMALL"])
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual(result["gmgn_failed"], 2)

    def test_gmgn_false_step_dilewati_total(self):
        pools = [_best_pool("P-BIG", MINT_A)]
        with patch.object(ms, "fetch_best_pools", return_value=pools), \
                patch.object(ms, "enrich_pools", side_effect=self._enrich), \
                patch("rugchecker.attach_to_rows",
                      side_effect=lambda rows, **_kw: rows), \
                patch("gmgn_liquidity.attach_total_liquidity") as attach:
            result = ms.scan_best_lane("24h", max_wallets=2000,
                                       rugcheck=True, gmgn=False)
        attach.assert_not_called()
        self.assertEqual([r["pool_address"] for r in result["rows"]],
                         ["P-BIG"])
        self.assertNotIn("gmgn_liq", result["rows"][0])


if __name__ == "__main__":
    unittest.main()
