"""`rugchecker.py` — ringkasan honeypot checker rugchecker.cc untuk kolom RugCheck.

Permintaan user 2026-09-16: *"scan baru saya tambahkan jupiter safeguard untuk
filter yang mungkin rug"* + *"kita tambahkan kolom baru RugCheck dengan metode
ini"* (koreksi kedua: sumbernya **rugchecker.cc**, bukan rugcheck.xyz, tanpa API
key) + *"tapi versi yang lebih ringkas"* + *"jika kamu memiliki metode tambahan
untuk check rug, bisa kamu tambahkan kolom juga untuk penjelasanmu secara
ringkas"*.

Semua tes di sini offline: satu-satunya pintu keluar jaringan adalah
:func:`rugchecker.fetch_raw`, dan itu selalu di-mock. Yang di-pin:

- klasifikasi verdict dari ``data.is_honeypot`` + ``data.security`` (RUG /
  BERISIKO / WASPADA / AMAN) beserta warnanya;
- baris likuiditas ``data.dex[]`` dalam versi ringkas (maks
  :data:`MAX_LIQ_LINES` baris lalu ``+N pool``), total, dan ``market_cap`` yang
  SELALU diambil dari pool terbesar (pool debu di token sampel melaporkan MC
  $1,9 M di likuiditas $0,16 — angka per-pool tidak bisa dipakai);
- metode tambahan (kedalaman pool ini, share likuiditas, konsentrasi pasar)
  dengan ambang yang dibaca live dari konstanta;
- kegagalan laporan → ``ok False`` + verdict ``—``, bukan ``AMAN``;
- cache berkas (TTL sukses/kegagalan, ``use_cache=False``) supaya tiap rerun
  Streamlit tidak menembak API pihak ketiga;
- RUGCHECK TIDAK PERNAH MEMBUANG BARIS: :func:`attach_to_rows` menempel, tidak
  menyaring.
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rugchecker as rc

MINT = "A9AHYeqb7nQk7LZUraw7rBCzYRjy2DRvE6NqWfFHKRdH"
FLAGS = ("transfer_fee", "mintable", "freezable", "closable",
         "non_transferable", "balance_mutable", "transfer_fee_upgradable",
         "transfer_hook_upgradable", "metadata_mutable")
SEC_CLEAN = dict.fromkeys(FLAGS, 0)

#: Dua pool seperti respons sampel user (HUHCAT): meteora $102.549,26 +
#: pumpswap $116.680,38 — diurut terbalik oleh ``_markets``.
def _payload(*, security=None, honeypot=False, dex=None, symbol="HUHCAT"):
    return {
        "code": 0,
        "message": "success",
        "data": {
            "chain_id": "solana",
            "token_address": MINT,
            "symbol": symbol,
            "name": "Huh Cat",
            "security": SEC_CLEAN if security is None else security,
            "is_honeypot": honeypot,
            "dex": [
                {"pair_address": "PUMP1", "dex_id": "pumpswap", "quote": "SOL",
                 "liquidity": {"usd": 116680.38, "base": 1.0, "quote": 2.0},
                 "market_cap": 1295891.0},
                {"pair_address": "METEORA1", "dex_id": "meteora", "quote": "SOL",
                 "liquidity": {"usd": 102549.26}, "market_cap": 1317971.0},
            ] if dex is None else dex,
        },
        "time": 0,
        "runtime": 0,
    }


def _patch_cache(tmp: Path):
    """Cache berkas diarahkan ke dir sementara (repo tidak dikotori)."""
    return patch.object(rc, "CACHE_PATH", tmp / "rugchecker_cache.json")


class CompactUsdTest(unittest.TestCase):
    def test_format_ringkas(self):
        for value, want in [(None, "—"), (0, "$0.00"), (42, "$42.00"),
                            (999, "$999"), (999.4, "$999"),
                            (1000, "$1.00K"), (6451, "$6.45K"),
                            (9999, "$10.00K"), (116680.38, "$116.7K"),
                            (1_234_567, "$1.23M"), (12_345_678, "$12.3M"),
                            (123_456_789, "$123M"), (2_500_000_000, "$2.50B")]:
            with self.subTest(value=value):
                self.assertEqual(rc.compact_usd(value), want)

    def test_sampah_menjadi_nol_bukan_traceback(self):
        for value in ("abc", float("nan"), float("inf"), [1], None):
            with self.subTest(value=value):
                self.assertIsInstance(rc.compact_usd(value), str)
        self.assertEqual(rc.compact_usd(float("nan")), "$0.00")


class VerdictTest(unittest.TestCase):
    def test_bersih_aman(self):
        summary = rc.summarize(_payload())
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["verdict"], "AMAN")
        self.assertEqual(summary["color"], rc.VERDICT_CLEAN[1])
        self.assertEqual(summary["critical"], [])
        self.assertEqual(summary["minor"], [])
        self.assertEqual(summary["flag_count"], 0)

    def test_honeypot_otomatis_rug(self):
        """``is_honeypot`` = satu-satunya jalur ke RUG, apa pun benderanya."""
        summary = rc.summarize(_payload(honeypot=True,
                                       security={**SEC_CLEAN, "mintable": 1}))
        self.assertEqual((summary["verdict"], summary["color"]), rc.VERDICT_RUG)
        self.assertTrue(summary["honeypot"])
        # tooltip harus menyebut honeypot, bukan menulis "bendera: tidak ada"
        tooltip = rc.cell_parts(summary)[2]
        self.assertIn("HONEYPOT", tooltip)
        self.assertIn("bendera keamanan: mintable, honeypot",
                      summary["notes"][-1])

    def test_bendera_kritis_berisiko(self):
        for key, label in [("mintable", "mintable"), ("freezable", "freezable"),
                           ("non_transferable", "non-transferable"),
                           ("transfer_hook_upgradable", "transfer hook")]:
            with self.subTest(flag=key):
                summary = rc.summarize(_payload(security={**SEC_CLEAN, key: True}))
                self.assertEqual((summary["verdict"], summary["color"]),
                                 rc.VERDICT_RISK)
                self.assertEqual(summary["critical"], [label])
                self.assertEqual(summary["minor"], [])

    def test_transfer_fee_angka_persen(self):
        """> 0 = pajak transfer (kritis); 0/None/Kosong = bersih."""
        self.assertEqual(rc.summarize(_payload(security={**SEC_CLEAN,
                                                        "transfer_fee": 5})
                                     )["critical"], ["transfer fee 5%"])
        for value in (0, 0.0, None, "", "0"):
            with self.subTest(value=value):
                summary = rc.summarize(_payload(
                    security={**SEC_CLEAN, "transfer_fee": value}))
                self.assertEqual(summary["verdict"], "AMAN")

    def test_bendera_minor_waspada(self):
        for key, label in [("transfer_fee_upgradable", "fee upgradable"),
                           ("balance_mutable", "balance mutable"),
                           ("metadata_mutable", "metadata mutable"),
                           ("closable", "closable")]:
            with self.subTest(flag=key):
                summary = rc.summarize(_payload(security={**SEC_CLEAN, key: 1}))
                self.assertEqual((summary["verdict"], summary["color"]),
                                 rc.VERDICT_WATCH)
                self.assertEqual(summary["minor"], [label])
        # kritis mengalahkan minor
        summary = rc.summarize(_payload(security={**SEC_CLEAN, "closable": 1,
                                                 "mintable": 1}))
        self.assertEqual(summary["verdict"], "BERISIKO")
        self.assertEqual(summary["flag_count"], 2)

    def test_laporan_rusak_tanpa_verdict(self):
        """Tidak ada ``AMAN`` untuk respons yang gagal/tidak dikenali."""
        cases = [{}, {"code": 1, "message": "rate limited"},
                 {"code": 0, "message": "ok"},          # code 0 tanpa data
                 {"code": 0, "data": "bukan dict"}, None,
                 "bukan dict", []]
        for payload in cases:
            with self.subTest(payload=str(payload)[:40]):
                summary = rc.summarize(payload)
                self.assertFalse(summary["ok"])
                self.assertEqual(summary["verdict"], "—")
                self.assertEqual(summary["color"], "")
                self.assertTrue(summary["error"])

    def test_alasan_kegagalan_dibawa_ke_tooltip(self):
        summary = rc.summarize({"code": 1, "message": "token tidak dikenal"})
        self.assertEqual(
            rc.cell_parts(summary),
            ("—", "rugcheck",
             'rugchecker.cc tidak menghasilkan laporan: token tidak dikenal — '
             'kolom menulis —, bukan "AMAN" (tanpa bukti tidak ada verdict)'))
        self.assertEqual(rc.cell_parts(None)[0], "—")
        self.assertIn("belum di-fetch", rc.cell_parts({})[2])


class LiquidityTest(unittest.TestCase):
    def test_baris_ringkas_dan_total(self):
        summary = rc.summarize(_payload())
        self.assertEqual(summary["liquidity_lines"],
                         ["PUMPSWAP·SOL $116.7K", "METEORA·SOL $102.5K"])
        self.assertAlmostEqual(summary["liquidity_total_usd"], 219229.64)
        self.assertEqual(summary["market_count"], 2)
        angka, sub, tooltip = rc.cell_parts(summary)
        self.assertEqual(angka, "AMAN")
        # $219.2K < ambang $500K → angka likuiditas MERAH (permintaan user
        # 2026-09-17: "tambahkan jika total likuiditas dibawah 500K, kasih
        # warna merah bagian tulisan likuiditasnya").
        self.assertEqual(sub, '<span style="color:#dc2626;font-weight:700;">'
                             '$219.2K</span> liq · 2 pool')
        self.assertIn("likuiditas (ringkas): PUMPSWAP·SOL $116.7K · "
                      "METEORA·SOL $102.5K — total $219.2K", tooltip)

    def test_market_cap_dari_pool_terbesar_saja(self):
        """Pool $0,16 di sampel melapor MC $1,9M — MC per-pool tidak dipakai."""
        dex = [{"pair_address": "BIG", "dex_id": "pumpswap",
                "liquidity": {"usd": 1000.0}, "market_cap": 1000.0},
               {"pair_address": "DUST", "dex_id": "meteora",
                "liquidity": {"usd": 0.16}, "market_cap": 1_900_000.0}]
        summary = rc.summarize(_payload(dex=dex))
        self.assertEqual(summary["market_cap"], 1000.0)
        self.assertEqual(summary["market_count"], 2)

    def test_baris_dibatasi_lalu_diringkas(self):
        dex = [{"pair_address": f"P{i}", "dex_id": f"dex{i}",
                "liquidity": {"usd": 1000.0 * (10 - i)}} for i in range(6)]
        summary = rc.summarize(_payload(dex=dex))
        self.assertEqual(len(summary["liquidity_lines"]), rc.MAX_LIQ_LINES + 1)
        self.assertEqual(summary["liquidity_lines"][-1],
                         f"+{6 - rc.MAX_LIQ_LINES} pool")
        self.assertEqual(summary["market_count"], 6)
        with patch.object(rc, "MAX_LIQ_LINES", 1):
            self.assertEqual(
                rc.liquidity_lines(rc._markets(_payload(dex=dex)["data"]))[0],
                ["DEX0 $10.0K", "+5 pool"])

    def test_entry_sampah_dibuang(self):
        dex = [{"pair_address": "A", "dex_id": "meteora",
                "liquidity": {"usd": "bukan angka"}},
               {"pair_address": "B", "dex_id": "meteora",
                "liquidity": {"usd": -5}},
               {"pair_address": "C", "dex_id": "meteora",
                "liquidity": {"usd": 500}},
               "bukan dict", {"liquidity": None}]
        summary = rc.summarize(_payload(dex=dex))
        self.assertEqual(summary["market_count"], 1)
        self.assertEqual(summary["liquidity_lines"], ["METEORA $500"])
        self.assertEqual(rc.cell_parts(summary)[1],
                         '<span style="color:#dc2626;font-weight:700;">$500'
                         '</span> liq · 1 pool')

    def test_tanpa_pool_sama_sekali(self):
        summary = rc.summarize(_payload(dex=[]))
        self.assertEqual(summary["market_count"], 0)
        self.assertEqual(summary["liquidity_lines"], [])
        self.assertEqual(summary["liquidity_total_usd"], 0.0)
        self.assertEqual(summary["market_cap"], 0.0)
        self.assertEqual(rc.cell_parts(summary)[1], "tanpa pool")


class PoolNotesTest(unittest.TestCase):
    """Metode tambahan: kedalaman pool, share likuiditas, konsentrasi pasar."""

    def _dex(self, meteora_usd, other_usd=116680.38):
        return [{"pair_address": "PUMP1", "dex_id": "pumpswap", "quote": "SOL",
                 "liquidity": {"usd": other_usd}, "market_cap": 1295891.0},
                {"pair_address": "METEORA1", "dex_id": "meteora",
                 "quote": "SOL", "liquidity": {"usd": meteora_usd},
                 "market_cap": 1317971.0}]

    def test_pool_dangkal_disebut_tipis(self):
        summary = rc.summarize(_payload(dex=self._dex(4000.0)),
                               pool_address="METEORA1")
        notes = "\n".join(summary["notes"])
        self.assertIn("kedalaman pool ini $4.00K (TIPIS — harga mudah digeser)",
                      notes)
        with patch.object(rc, "POOL_MIN_LIQ_USD", 1000.0):
            notes2 = "\n".join(rc.summarize(_payload(dex=self._dex(4000.0)),
                                            pool_address="METEORA1")["notes"])
            self.assertIn("(cukup)", notes2)
            self.assertNotIn("TIPIS", notes2)

    def test_share_kecil_disebut(self):
        summary = rc.summarize(_payload(dex=self._dex(20_000.0)),
                               pool_address="METEORA1")
        notes = "\n".join(summary["notes"])
        self.assertIn("share 14.6% dari likuiditas token", notes)
        self.assertIn(f"share pool < {rc.POOL_SHARE_MIN_PCT:g}%", notes)
        # pool dominan: share besar, tidak ada keluhan sebaran
        notes2 = "\n".join(rc.summarize(_payload(dex=self._dex(200_000.0)),
                                        pool_address="METEORA1")["notes"])
        self.assertNotIn("share pool <", notes2)

    def test_konsentrasi_ditulis_hanya_bila_ada_sisa(self):
        rata = "\n".join(rc.summarize(
            _payload(dex=[{"pair_address": "A", "dex_id": "meteora",
                           "liquidity": {"usd": 50_000.0}},
                          {"pair_address": "B", "dex_id": "raydium",
                           "liquidity": {"usd": 50_000.0}}]),
            pool_address="A")["notes"])
        self.assertIn("2 pool · 2 pool ≥ 10% likuiditas", rata)
        self.assertIn("tersebar merata", rata)
        self.assertNotIn("debu", rata)
        timpuk = "\n".join(rc.summarize(
            _payload(dex=self._dex(102_549.26)), pool_address="PUMP1")["notes"])
        self.assertIn("pool terbesar 53%", timpuk)

    def test_pool_tidak_dikenal_di_sumber(self):
        summary = rc.summarize(_payload(), pool_address="BUKAN-PAIR")
        self.assertTrue(any("tidak ada di daftar rugchecker" in note
                            for note in summary["notes"]))
        self.assertNotIn("kedalaman pool ini", "\n".join(summary["notes"]))

    def test_tanpa_pool_todo_tanpa_note_kedalaman(self):
        summary = rc.summarize(_payload(dex=[]), pool_address="X")
        self.assertTrue(any("tidak ada di daftar rugchecker" in note
                            for note in summary["notes"]))


class CheckTokensTest(unittest.TestCase):
    def test_satu_request_per_mint_dan_kirim_pair(self):
        seen = []

        def fake_fetch(mint, *, timeout=None):
            seen.append((mint, timeout))
            return _payload()

        with _patch_cache(Path(tempfile.mkdtemp())), \
                patch.object(rc, "fetch_raw", side_effect=fake_fetch):
            out = rc.check_tokens([MINT, "  ", MINT, "Other111"],
                                  pool_by_mint={MINT: "METEORA1"},
                                  workers=4, timeout=7)
        self.assertEqual(sorted(seen), sorted([(M, 7) for M in
                                               [MINT, "Other111"]]))
        self.assertEqual(sorted(out), sorted([MINT, "Other111"]))  # dedupe+trim
        self.assertEqual(out[MINT]["liquidity_lines"][1], "METEORA·SOL $102.5K")
        self.assertEqual(out["Other111"]["verdict"], "AMAN")

    def test_satu_mint_mati_tidak_menjatuhkan_scan(self):
        def fake_fetch(mint, *, timeout=None):
            if mint == "Bad111":
                raise RuntimeError("rugchecker HTTP 429")
            return _payload()

        with _patch_cache(Path(tempfile.mkdtemp())), \
                patch.object(rc, "fetch_raw", side_effect=fake_fetch):
            out = rc.check_tokens(["Bad111", MINT])
        self.assertFalse(out["Bad111"]["ok"])
        self.assertIn("HTTP 429", out["Bad111"]["error"])
        self.assertEqual(out["Bad111"]["verdict"], "—")
        self.assertTrue(out[MINT]["ok"])

    def test_cache_memakai_hasil_sebelum_ttl(self):
        tmp = Path(tempfile.mkdtemp())
        calls = []

        def fake_fetch(mint, *, timeout=None):
            calls.append(mint)
            return _payload()

        with _patch_cache(tmp), patch.object(rc, "fetch_raw",
                                             side_effect=fake_fetch):
            rc.check_tokens([MINT])
            rc.check_tokens([MINT])
            self.assertEqual(calls, [MINT])                      # 1× doang
            rc.check_tokens([MINT], use_cache=False)             # bypass
            self.assertEqual(calls, [MINT, MINT])
        # payload mentah yang disimpan, bukan summary — jadi pool yang berbeda
        # tetap menghasilkan catatan beda dari cache yang sama.
        cache = json.loads((tmp / "rugchecker_cache.json").read_text())
        self.assertEqual(list(cache), [MINT])
        self.assertTrue(cache[MINT]["ok"])
        self.assertIn("data", cache[MINT]["data"])
        # sukses pun ada masa berlakunya (CACHE_TTL_OK)
        with _patch_cache(tmp), patch.object(rc, "CACHE_TTL_OK", -1), \
                patch.object(rc, "fetch_raw", side_effect=fake_fetch):
            rc.check_tokens([MINT])
        self.assertEqual(calls, [MINT, MINT, MINT])

    def test_kegagalan_ditahan_lebih_pendek(self):
        tmp = Path(tempfile.mkdtemp())
        calls = []

        def fake_fetch(mint, *, timeout=None):
            calls.append(mint)
            raise RuntimeError("timeout")

        with _patch_cache(tmp), patch.object(rc, "fetch_raw",
                                             side_effect=fake_fetch):
            rc.check_tokens([MINT])
            rc.check_tokens([MINT])
            self.assertEqual(calls, [MINT])              # masih dalam TTL gagal
            with patch.object(rc, "CACHE_TTL_FAIL", -1):
                rc.check_tokens([MINT])
                self.assertEqual(calls, [MINT, MINT])    # TTL gagal habis → coba lagi

    def test_cache_buruk_dianggap_kosong(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "rugchecker_cache.json").write_text("{bukan json", encoding="utf-8")
        with _patch_cache(tmp), patch.object(rc, "fetch_raw",
                                              return_value=_payload()) as fetch:
            out = rc.check_tokens([MINT])
        fetch.assert_called_once()
        self.assertTrue(out[MINT]["ok"])

    def test_pruning_lru(self):
        """Lebih dari CACHE_MAX_ENTRIES → entri tertua (by ``at``) dibuang."""
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "rugchecker_cache.json"
        base = {f"M{i}": {"at": 1_700_000_000 + i, "ok": True, "data": _payload()}
                for i in range(5)}
        path.write_text(json.dumps(base), encoding="utf-8")
        with _patch_cache(tmp), patch.object(rc, "CACHE_MAX_ENTRIES", 3):
            rc._cache_put("NEW", _payload(), ok=True)
            cache = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(cache), ["M3", "M4", "NEW"])
        self.assertIn("NEW", cache)


class AttachToRowsTest(unittest.TestCase):
    def test_menempel_tanpa_menyaring(self):
        rows = [{"ca": MINT, "pool_address": "METEORA1", "fee_active_tvl_ratio": 60},
                {"ca": "", "pool_address": "NOPAIR"},
                None]
        with _patch_cache(Path(tempfile.mkdtemp())), \
                patch.object(rc, "fetch_raw", return_value=_payload()) as fetch:
            out = rc.attach_to_rows(rows)
        self.assertEqual(len(out), 3)
        self.assertEqual(len(rows), 3)
        self.assertNotIn("rugcheck", rows[0])          # baris asal tidak diubah
        self.assertEqual(out[0]["rugcheck"]["verdict"], "AMAN")
        for idx in (1, 2):
            self.assertEqual(out[idx]["rugcheck"]["verdict"], "—")
            self.assertIn("mint tidak terbawa", out[idx]["rugcheck"]["error"])
        self.assertEqual(fetch.call_count, 1)          # hanya mint yang dibawa
        # payload API tidak mengubah angka baris lain
        self.assertEqual(out[0]["fee_active_tvl_ratio"], 60)

    def test_baris_kosong_tanpa_request(self):
        with _patch_cache(Path(tempfile.mkdtemp())), \
                patch.object(rc, "fetch_raw") as fetch:
            self.assertEqual(rc.attach_to_rows([]), [])
        fetch.assert_not_called()


class TransportTest(unittest.TestCase):
    """URL, header browser, tanpa cookie analytics."""

    class _Resp:
        status_code = 200

        def json(self):
            return {"code": 0, "data": {"symbol": "TOK"}}

    def _fake_requests(self, captured):
        module = types.ModuleType("requests")

        def get(url, headers=None, timeout=None):
            captured.append((url, headers, timeout))
            return self._Resp()

        module.get = get
        return module

    def test_url_dan_header(self):
        captured = []
        with patch.dict(sys.modules, {"requests": self._fake_requests(captured)}):
            payload = rc.fetch_raw(MINT, timeout=5)
        self.assertEqual(payload["code"], 0)
        url, headers, timeout = captured[0]
        self.assertEqual(url, f"{rc.CHECK_URL}?address={MINT}")
        self.assertEqual(rc.CHECK_URL,
                         "https://www.rugchecker.cc/api/honeypot/checker")
        self.assertEqual(timeout, 5)
        self.assertEqual(headers["referer"], "https://www.rugchecker.cc/")
        self.assertIn("user-agent", headers)
        self.assertNotIn("cookie", {k.lower() for k in headers},
                         "cookie _ga analytics tidak boleh ikut dikirim")

    def test_kegagalan_dilempar_sebagai_runtimeerror(self):
        for status, body in [(429, None), (200, "bukan json")]:
            with self.subTest(status=status):
                captured = []
                module = self._fake_requests(captured)

                class Resp:
                    status_code = status

                    def json(self_inner):
                        raise ValueError(body)

                module.get = lambda url, headers=None, timeout=None: Resp()
                with patch.dict(sys.modules, {"requests": module}):
                    with self.assertRaises(RuntimeError) as ctx:
                        rc.fetch_raw(MINT)
                self.assertIn("429" if status == 429 else "bukan JSON",
                              str(ctx.exception))

    def test_modul_tidak_ketergantungan_streamlit(self):
        """RugCheck dipakai cron + tes: dilarang mengimpor Streamlit/UI."""
        src = (ROOT / "rugchecker.py").read_text(encoding="utf-8")
        for banned in ("streamlit", "dashboard_components", "best_pool_ui",
                       "helius", "matplotlib"):
            self.assertNotIn(f"import {banned}", src)
        # `requests` hanya di-import di dalam fungsi (lazy) supaya modul bisa
        # diimpor di lingkungan tanpa requests.
        self.assertIn("    import requests\n", src)
        self.assertNotIn("\nimport requests\n", src)


class UiContractTest(unittest.TestCase):
    """Card membaca konstanta modul lewat UI — jangan sampai namanya berubah."""

    def setUp(self):
        import meteora_screener as ms
        self.ms = ms
        self.screener = (ROOT / "meteora_screener.py").read_text()
        self.ui = (ROOT / "best_pool_ui.py").read_text()
        self.gitignore = (ROOT / ".gitignore").read_text()

    def test_kolom_ditampilkan_dari_cell_parts(self):
        """UI tidak boleh merakit ulang teks RugCheck — formatting di modul."""
        self.assertIn("from rugchecker import cell_parts", self.ui)
        self.assertIn('"rugcheck"', self.ui)
        self.assertIn('row.get("rugcheck")', self.ui)
        # nama lapangan payload + URL endpoint hanya boleh ada di rugchecker.py
        for raw in ("is_honeypot", "data.security", '"dex"', "honeypot/checker"):
            self.assertNotIn(raw, self.ui,
                           f"UI menyentuh payload mentah ({raw})")

    def test_skrining_rug_bukan_saringan_baris(self):
        """Safeguard Jupiter default-nya DIMATIKAN (2026-09-17); rugcheck tidak
        menyaring.

        Konstanta ``JUPITER_SAFEGUARD_FILTERS`` tetap ada di source (bisa
        diaktifkan via ``safeguard=True``) dan bendera kritis tetap
        dilaporkan kolom RugCheck — tetapi filter server tidak lagi dipasang
        di query default (membuang PAID diam-diam), dan RugCheck tidak
        pernah membuang baris.
        """
        # Konstanta tetap ada di source (kwarg safeguard=True masih hidup).
        self.assertIn("base_token_has_critical_warnings=false", self.screener)
        self.assertIn("quote_token_has_critical_warnings=false", self.screener)
        # Tapi query DEFAULT tidak lagi memuat flag itu (safeguard=False).
        query = self.ms.best_filter_by()
        self.assertNotIn("base_token_has_critical_warnings", query)
        self.assertNotIn("quote_token_has_critical_warnings", query)
        self.assertIn("pool_type=dlmm", query)
        # Kalau caller minta, safeguard masih bisa dipasang (di depan pool_type).
        sg_query = self.ms.best_filter_by(safeguard=True)
        self.assertLess(sg_query.index("base_token_has_critical_warnings"),
                        sg_query.index("pool_type=dlmm"))
        self.assertIn("def attach_to_rows", (ROOT / "rugchecker.py").read_text())
        self.assertNotIn("rugcheck", self.screener.split("def row_best_gaps")[1]
                         .split("\ndef ")[0],
                        "row_best_gaps tidak boleh menyaring lewat rugcheck")

    def test_cache_tidak_masuk_git(self):
        """Cache ditulis di repo (persist antar-restart) → wajib di-ignore.

        Repo ini publik; ``rugchecker_cache.json`` berisi daftar mint yang
        dipantau, jadi tidak boleh ikut ter-commit.
        """
        self.assertIn("rugchecker_cache.json", self.gitignore)


if __name__ == "__main__":
    unittest.main()
