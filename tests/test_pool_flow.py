# -*- coding: utf-8 -*-
"""Tes logika Scan Best Pool (24H, volatility vs fee/active TVL) — tanpa jaringan.

``METEORA_24H`` berisi 14 pool dari respons Meteora timeframe=24h yang dikirim
user (2026-11-13). Batas volatility 5%, rasio minimal 2x, fee/active TVL minimal 5% (permintaan user 2026-11-13): tujuh lolos.
Hasil yang diharapkan dihitung manual dari aturan.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pool_flow as pf  # noqa: E402

SOL = "So11111111111111111111111111111111111111112"


def _row(pool, symbol, *, fee=2.0, tvl=20_000.0, active_tvl=5_000.0, holders=2_000,
         mcap=500_000.0, vol=2.0, fa=10.0, open_pos=50, active=40, mint=None,
         volume=10_000.0, swaps=500.0, traders=200.0):
    mint = mint or ("M" + pool[:8].ljust(43, "x"))
    return {"pool_address": pool, "name": f"{symbol}-SOL", "pool_type": "dlmm",
            "token_x": {"address": mint, "symbol": symbol, "name": symbol,
                        "market_cap": mcap},
            "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
            "fee_pct": fee, "tvl": tvl, "active_tvl": active_tvl,
            "base_token_holders": holders, "open_positions": open_pos,
            "active_positions": active, "volatility": vol, "fee_active_tvl_ratio": fa,
            "volume": volume, "swap_count": swaps, "unique_traders": traders}


def _good(**over):
    """Lolos semua aturan; rasio = 10 ÷ 2 = 5x."""
    base = dict(fee=2.0, tvl=20_000.0, active_tvl=5_000.0, holders=2_000, mcap=500_000.0,
                vol=2.0, fa=10.0)
    base.update(over)
    return _row("PoolGood" + "1" * 30, "GOOD", **base)


# pool, symbol, fee, tvl, active_tvl, holders, mcap, volatility, fee/active TVL, open, active
METEORA_24H = [
    ("91iHWaWXneUyoNDJhSno7ezxQg1VW5P6PdarNGyFfPCz", "STANK", 2.0, 100873.57, 97133.86, 5083, 1958893.17, 2.730948306399437, 14.182777407121913, 238, 190),
    ("9JZrcAScnGQp7DSV4kBWfmGH2ao31sz5JbJ8cnpZ9uwv", "CHOO", 2.0, 86042.99, 84760.24, 7201, 1152810.07, 1.5618331251100772, 7.469201539173313, 173, 129),
    ("GWe6KGwM4tUyBFMWe1xjLYZu7dmmEDex5ScoJ1oiuacY", "USELESS", 2.0, 18418.43, 2018.085, 69203, 134961507.10, 0.4268159179118895, 1.6401911898189765, 18, 3),
    ("5Dc4s9fxxQoPfaMUaxFKB5v1Nh6FPqest7usgyvGXwWw", "DacityCoin", 2.0, 117707.18, 114211.47, 12435, 4772220.09, 2.4218466831988774, 9.157669232739185, 232, 153),
    ("9ViFN1A2FG2aL69Uu3dZwVMbcSdKuuMM5PLouZmguK2e", "mihao", 2.0, 107119.48, 103862.48, 31615, 14361538.78, 2.197522427661364, 8.145744362117817, 201, 142),
    ("BADiqzWTYyZPbcqKgNtgy6KB5ZhmPrgq9qguPnpjXHf8", "Rocco", 2.0, 13217.43, 12110.51, 2222, 586541.14, 2.8478107097362697, 9.63119736506875, 49, 42),
    # gagal:
    ("DnmL7vYnNTACb8e6a4EpbeeeNDW8hwp1EvQZ4BWKCgjK", "GATO", 3.0, 135395.37, 133647.02, 11769, 4969076.57, 1.819463479422516, 4.508445441715985, 183, 158),  # 2,48x
    ("EWBCL4hKY6VdzZVcCY7pMPvRhG78koHY6nQnt8EW99Br", "LMAO!", 2.0, 134591.59, 131647.48, 15791, 1039609.05, 2.942714221664328, 3.6073866134371526, 78, 66),  # 1,23x
    ("5WVURqJSLRFNZDVDF2njtjZihRLeALvt5tss3yjt2Vik", "paws", 2.0, 47308.20, 46647.47, 2789, 895713.73, 3.346236475355708, 11.025536070549084, 155, 84),  # 3,29x, vol 3,35% (lolos di batas 5%)
    ("FSb7qz3cMGjYacrLfoKumozoqFibiAtzjDq97FxHivYP", "DacityCoin", 5.0, 13452.87, 12153.33, 12435, 4772220.09, 3.0831077573643584, 8.639426602320858, 37, 32),  # 2,80x (gagal)
    ("2wqaQVQ54bayWCjfsV391BQHA13qiVgjagSRtQPFJ6wu", "PUMPCADE", 2.0, 13964.92, 13611.18, 5189, 16268607.69, 4.6566128730773926e-08, 0.41077066347875446, 18, 18),  # vol ≈ 0
    ("3Keu4gPtDUnkoLpas8HauhPZgpiiADPNtJAB4UDQWbpi", "MET", 5.0, 18357.78, 11461.53, 43957, 163835898.74, 1.6463612699567982e-08, 0.0970318184860885, 45, 2),  # vol ≈ 0
    ("8tp8GJADuYu2czhnaWzXYxpXTq2dwjribGwSav4J4m7e", "xHYPE", 2.0, 104436.62, 100742.69, 6642, 616063.37, 1.0094755398497184, 0.4270554720456035, 106, 39),  # 0,42x
    ("BiNnErm2VDkbKGiABj9ZRUjybz879NhH2heeWE7m5M6d", "OMFG", 2.0, 21675.94, 21916.94, 1734, 1850686.66, 0.0, 0.00217943551742239, 3, 2),  # vol 0
]


def meteora_rows():
    return [_row(p, s, fee=f, tvl=t, active_tvl=at, holders=h, mcap=m, vol=v, fa=fa,
                 open_pos=o, active=a)
            for p, s, f, t, at, h, m, v, fa, o, a in METEORA_24H]


PASSING_ORDER = [  # rasio terbesar dulu
    "91iHWaWXneUyoNDJhSno7ezxQg1VW5P6PdarNGyFfPCz",  # STANK 5,19x
    "9JZrcAScnGQp7DSV4kBWfmGH2ao31sz5JbJ8cnpZ9uwv",  # CHOO 4,78x
    "5Dc4s9fxxQoPfaMUaxFKB5v1Nh6FPqest7usgyvGXwWw",  # DacityCoin 3,78x
    "9ViFN1A2FG2aL69Uu3dZwVMbcSdKuuMM5PLouZmguK2e",  # mihao 3,71x
    "BADiqzWTYyZPbcqKgNtgy6KB5ZhmPrgq9qguPnpjXHf8",  # Rocco 3,38x
    "5WVURqJSLRFNZDVDF2njtjZihRLeALvt5tss3yjt2Vik",  # paws 3,29x
    "FSb7qz3cMGjYacrLfoKumozoqFibiAtzjDq97FxHivYP",  # DacityCoin FSb7 2,80x
]


class RuleTest(unittest.TestCase):
    def test_pool_lolos_semua_aturan(self):
        result = pf.evaluate_pool(_good())
        self.assertTrue(result["passes"], result["reasons"])
        self.assertAlmostEqual(result["multiple"], 5.0)

    def test_batas_inklusif(self):
        cases = [
            ("fee tier", dict(fee=2.0), True), ("fee tier", dict(fee=1.99), False),
            ("TVL", dict(tvl=10_000.0), True), ("TVL", dict(tvl=9_999.0), False),
            ("active TVL", dict(active_tvl=2_000.0), True), ("active TVL", dict(active_tvl=1_999.0), False),
            ("holders", dict(holders=1_500), True), ("holders", dict(holders=1_499), False),
            ("market cap", dict(mcap=100_000.0), True), ("market cap", dict(mcap=99_999.0), False),
            ("volatilitas", dict(vol=5.0, fa=20.0), True), ("volatilitas", dict(vol=5.01, fa=20.0), False),
            ("rasio", dict(fa=10.0, vol=5.0), True), ("rasio", dict(fa=9.99, vol=5.0), False),
        ]
        for label, over, expected in cases:
            with self.subTest(rule=label, over=over):
                self.assertEqual(pf.evaluate_pool(_good(**over))["passes"], expected)

    def test_volatilitas_nol_atau_hilang_tidak_terukur(self):
        for over in (dict(vol=0.0), dict(vol=4.6e-8), dict(vol=None)):
            with self.subTest(over=over):
                result = pf.evaluate_pool(_good(**over))
                self.assertFalse(result["passes"])
                self.assertIsNone(result["multiple"])
                self.assertTrue(any("tidak terukur" in r or "≈ 0" in r for r in result["reasons"]))

    def test_fee_active_hilang_gagal(self):
        result = pf.evaluate_pool(_good(fa=None))
        self.assertFalse(result["passes"])
        self.assertIn("fee/active TVL tidak terukur", result["reasons"])

    def test_alasan_gagal_menyebut_semua_aturan_yang_dilanggar(self):
        result = pf.evaluate_pool(_good(fee=1.0, tvl=100.0, vol=6.0, fa=1.0))
        self.assertEqual(len(result["reasons"]), 5)  # fee tier, TVL, vol, rasio, fee/active
        self.assertTrue(any("volatility > 5" in r for r in result["reasons"]))
        self.assertTrue(any("÷ volatility" in r for r in result["reasons"]))

    def test_fee_active_tvl_minimal_5_persen(self):
        self.assertTrue(pf.evaluate_pool(_good(fa=5.0, vol=1.0))["passes"])  # tepat 5% tampil
        result = pf.evaluate_pool(_good(fa=4.99, vol=1.0))
        self.assertFalse(result["passes"])
        self.assertIn("fee/active TVL < 5%", result["reasons"])

    def test_in_range_tetap_dihitung_untuk_tampilan(self):
        self.assertAlmostEqual(pf.in_range_pct(_good(open_pos=50, active=25)), 50.0)


class RealResponseTest(unittest.TestCase):
    def test_tujuh_pool_lolos_urut_rasio_dari_respons_meteora(self):
        result = pf.scan_pools(listing=(meteora_rows(), [], False))
        self.assertEqual(result["candidates"], 14)
        self.assertEqual([r["pool"] for r in result["passing"]], PASSING_ORDER)

    def test_rasio_stank_sesuai_hitung_manual(self):
        results = {r["pool"]: r for r in pf.scan_pools(listing=(meteora_rows(), [], False))["results"]}
        self.assertAlmostEqual(results[PASSING_ORDER[0]]["multiple"], 14.182777 / 2.730948, places=3)

    def test_alasan_gagal_sesuai_hitung_manual(self):
        results = {r["pool"]: r for r in pf.scan_pools(listing=(meteora_rows(), [], False))["results"]}
        lmao = results["EWBCL4hKY6VdzZVcCY7pMPvRhG78koHY6nQnt8EW99Br"]
        self.assertTrue(any("÷ volatility" in r for r in lmao["reasons"]))  # 1,23x
        paws = results["5WVURqJSLRFNZDVDF2njtjZihRLeALvt5tss3yjt2Vik"]
        self.assertTrue(paws["passes"])  # vol 3,35% ≤ 5%, rasio 3,29x
        pump = results["2wqaQVQ54bayWCjfsV391BQHA13qiVgjagSRtQPFJ6wu"]
        self.assertTrue(any("≈ 0" in r for r in pump["reasons"]))
        omfg = results["BiNnErm2VDkbKGiABj9ZRUjybz879NhH2heeWE7m5M6d"]
        self.assertTrue(any("≈ 0" in r for r in omfg["reasons"]))


class ScanTest(unittest.TestCase):
    def test_urut_rasio_lalu_fee_active(self):
        a = _good(vol=2.0, fa=8.0)     # 4x, fee/active 8
        b = _good(vol=1.5, fa=6.0)     # 4x, fee/active 6
        c = _good(vol=1.0, fa=12.0)    # 12x
        a["pool_address"], b["pool_address"], c["pool_address"] = "A" * 44, "B" * 44, "C" * 44
        passing = pf.scan_pools(listing=([a, b, c], [], False))["passing"]
        self.assertEqual([r["pool"] for r in passing], ["C" * 44, "A" * 44, "B" * 44])

    def test_pool_duplikat_dihitung_sekali(self):
        row = _good()
        result = pf.scan_pools(listing=([row, dict(row)], [], False))
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(len(result["passing"]), 1)

    def test_truncated_dan_error_ikut_dilaporkan(self):
        result = pf.scan_pools(listing=([], ["timeout"], True))
        self.assertTrue(result["truncated"])
        self.assertEqual(result["listing_errors"], 1)
        self.assertEqual(result["passing"], [])

    def test_fetch_listing_mengirim_request_24h(self):
        captured = []

        def fake_get(params, **kwargs):
            captured.append(dict(params))
            return {"data": [], "has_more": False}

        with mock.patch.object(pf, "_get_payload", side_effect=fake_get):
            rows, errors, truncated = pf.fetch_listing()
        self.assertEqual((rows, errors, truncated), ([], [], False))
        self.assertEqual(len(captured), 1)
        params = captured[0]
        self.assertEqual(params["timeframe"], "24h")
        self.assertEqual(params["category"], "top")
        self.assertEqual(params["page_size"], 50)
        self.assertNotIn("after_key", params)
        self.assertNotIn("page", params)  # page diabaikan API Meteora
        for piece in ("pool_type=dlmm", "base_token_holders>=1500", "tvl>=10000",
                      "fee_pct>=2", "active_tvl>=2000", "base_token_market_cap>=100000",
                      "base_token_has_high_supply_concentration=false",
                      "base_token_has_high_single_ownership=false"):
            self.assertIn(piece, params["filter_by"])


class PaginationTest(unittest.TestCase):
    """Paginasi cursor: halaman berikutnya diminta dengan ``after_key``."""

    def _cursor(self, sizes, errors_at=(), stuck=False):
        """Fake API. ``sizes`` = jumlah baris tiap halaman. Panggilan ke-n (0-based)
        diidentifikasi dari ``after_key`` = ``k<n>``."""
        calls = []

        def fake(params, **kwargs):
            key = params.get("after_key")
            index = 0 if key is None else (0 if stuck and key == "stuck" else int(key[1:]))
            calls.append(dict(params))
            if index in errors_at:
                raise RuntimeError("boom")
            size = sizes[index] if index < len(sizes) else 0
            has_more = index + 1 < len(sizes)
            next_key = ("stuck" if stuck else f"k{index + 1}") if has_more else None
            data = [{"pool_address": f"P{index}-{i}"} for i in range(size)]
            return {"data": data, "after_key": next_key, "has_more": has_more}

        return mock.patch.object(pf, "_get_payload", side_effect=fake), calls

    def test_berhenti_saat_has_more_false(self):
        patcher, calls = self._cursor([50, 50, 3])
        with patcher:
            rows, errors, truncated = pf.fetch_listing(max_pages=10)
        self.assertEqual(len(rows), 103)
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        self.assertEqual(len(calls), 3)
        self.assertNotIn("after_key", calls[0])
        self.assertEqual([c.get("after_key") for c in calls[1:]], ["k1", "k2"])
        self.assertTrue(all("page" not in c for c in calls))

    def test_tanpa_pool_tidak_ada_halaman_tambahan(self):
        patcher, calls = self._cursor([50])
        with patcher:
            rows, _, truncated = pf.fetch_listing()
        self.assertEqual(len(rows), 50)
        self.assertFalse(truncated)
        self.assertEqual(len(calls), 1)

    def test_truncated_bila_batas_tercapai_selagi_masih_ada_halaman(self):
        patcher, calls = self._cursor([50, 50, 50, 50])
        with patcher:
            rows, _, truncated = pf.fetch_listing(max_pages=3)
        self.assertEqual(len(rows), 150)
        self.assertTrue(truncated)
        self.assertEqual(len(calls), 3)

    def test_error_halaman_menghentikan_dan_menandai_tidak_lengkap(self):
        patcher, _ = self._cursor([50, 50, 4], errors_at=(1,))
        with patcher:
            rows, errors, truncated = pf.fetch_listing()
        self.assertEqual(errors, ["boom"])
        self.assertEqual(len(rows), 50)
        self.assertTrue(truncated)

    def test_cursor_macet_dihentikan(self):
        patcher, calls = self._cursor([50, 50, 50], stuck=True)
        with patcher:
            rows, errors, truncated = pf.fetch_listing(max_pages=100)
        self.assertTrue(truncated)
        self.assertEqual(len(calls), 2)
        self.assertEqual(errors, [])

    def test_halaman_pertama_gagal_tanpa_baris(self):
        patcher, _ = self._cursor([50], errors_at=(0,))
        with patcher:
            rows, errors, truncated = pf.fetch_listing()
        self.assertEqual(rows, [])
        self.assertEqual(errors, ["boom"])
        self.assertTrue(truncated)

    def test_truncated_diteruskan_ke_scan(self):
        result = pf.scan_pools(listing=([], [], True))
        self.assertTrue(result["truncated"])


class AlertTest(unittest.TestCase):
    def _passing(self):
        return pf.scan_pools(listing=(meteora_rows(), [], False))["passing"]

    def test_tanpa_pool_lolos_tidak_ada_alert(self):
        state = pf.empty_state()
        self.assertIsNone(pf.apply_best_alert(state, []))
        self.assertEqual(state["alerts"], [])
        self.assertEqual(state["best_alert"]["next_no"], 1)

    def test_alert_memberi_nomor_dan_menandai_pool_yang_sudah_pernah_muncul(self):
        state = pf.empty_state()
        passing = self._passing()
        first = pf.apply_best_alert(state, passing)
        self.assertIn("alert #1", first)
        self.assertEqual(first.count("🆕 baru"), len(passing))
        self.assertEqual(state["best_alert"]["next_no"], 2)
        second = pf.apply_best_alert(state, passing)
        self.assertIn("alert #2", second)
        self.assertEqual(second.count("🔁 sudah pernah · alert #1"), len(passing))
        self.assertNotIn("🆕 baru", second)

    def test_alert_memuat_tautan_dan_filter_24h(self):
        text = pf.best_alert_text(1, self._passing(), {})
        self.assertIn("24H", text)
        self.assertIn("÷ vol", text)
        self.assertIn("gmgn.ai", text)
        self.assertIn("meteora.ag", text)

    def test_split_telegram_tiap_bagian_di_bawah_batas(self):
        text = "\n".join("baris " + "x" * 90 for _ in range(200))
        parts = pf.split_for_telegram(text, limit=500)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 500 for p in parts))
        self.assertEqual("\n".join(parts), text)


class TelegramCopyTest(unittest.TestCase):
    """Tombol 📋 CA (copy_text) pada alert Telegram dan jadwal 4 jam."""

    def _passing(self):
        return pf.scan_pools(listing=(meteora_rows(), [], False))["passing"]

    def test_satu_tombol_copy_per_pool_dengan_ca_lengkap(self):
        passing = self._passing()
        markup = pf.alert_copy_markup(passing)
        rows = markup["inline_keyboard"]
        self.assertEqual(len(rows), len(passing))
        for row, pool in zip(rows, passing):
            (button,) = row
            self.assertEqual(button["copy_text"], {"text": pool["mint"]})
            self.assertIn(pool["symbol"], button["text"])
            self.assertLessEqual(len(button["copy_text"]["text"]), 256)

    def test_tanpa_pool_atau_tanpa_ca_tidak_ada_tombol(self):
        self.assertIsNone(pf.alert_copy_markup([]))
        self.assertIsNone(pf.alert_copy_markup([{"mint": "", "symbol": "X"}]))

    def _capture(self):
        sent = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=None):
            sent.append(json.loads(request.data.decode("utf-8")))
            return Resp()

        return mock.patch.object(pf.urllib.request, "urlopen", side_effect=fake_urlopen), sent

    def test_payload_menyertakan_reply_markup(self):
        patcher, sent = self._capture()
        markup = pf.alert_copy_markup(self._passing())
        with patcher, mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t",
                                                     "TELEGRAM_CHAT_ID": "1"}):
            ok, error = pf.send_telegram("pendek", reply_markup=markup)
        self.assertTrue(ok, error)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["reply_markup"], markup)
        self.assertEqual(sent[0]["parse_mode"], "HTML")

    def test_pesan_terpecah_hanya_bagian_terakhir_punya_tombol(self):
        patcher, sent = self._capture()
        markup = pf.alert_copy_markup(self._passing())
        text = "\n".join("baris " + "x" * 90 for _ in range(200))
        with patcher, mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t",
                                                     "TELEGRAM_CHAT_ID": "1"}):
            ok, _ = pf.send_telegram(text, reply_markup=markup)
        self.assertTrue(ok)
        self.assertGreater(len(sent), 1)
        self.assertTrue(all("reply_markup" not in body for body in sent[:-1]))
        self.assertEqual(sent[-1]["reply_markup"], markup)

    def test_tanpa_markup_payload_tidak_berisi_reply_markup(self):
        patcher, sent = self._capture()
        with patcher, mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t",
                                                     "TELEGRAM_CHAT_ID": "1"}):
            pf.send_telegram("pendek")
        self.assertNotIn("reply_markup", sent[0])

    def test_run_best_mengembalikan_teks_dan_tombol(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pool_flow_alert", ROOT / "scripts" / "pool_flow_alert.py")
        alert = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(alert)
        state = pf.empty_state()
        messages = alert.run_best(state, scan=lambda: pf.scan_pools(
            listing=(meteora_rows(), [], False)))
        self.assertEqual(len(messages), 1)
        text, markup = messages[0]
        self.assertIn("BEST POOL", text)
        self.assertEqual(len(markup["inline_keyboard"]), len(self._passing()))
        self.assertEqual(alert.run_best(pf.empty_state(), scan=lambda: {
            "passing": [], "listing_rows": 0, "candidates": 0,
            "listing_errors": 0, "truncated": False}), [])


class StateTest(unittest.TestCase):
    def test_state_tidak_lagi_menyimpan_watchlist_dan_membuang_kunci_lama(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"watchlist": [{"pool": "x"}], "history": {"x": []},
                                        "watch_negative": {}, "best_alert": {"next_no": 3,
                                        "last_no": {"p": 2}}, "alerts": []}), encoding="utf-8")
            state = pf.load_state(path)
            self.assertNotIn("watchlist", state)
            self.assertNotIn("history", state)
            self.assertEqual(state["best_alert"]["next_no"], 3)
            pf.save_state(state, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("watchlist", saved)

    def test_scan_tidak_menulis_berkas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool_flow_state.json"
            pf.scan_pools(listing=(meteora_rows(), [], False))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Aktivitas per token (permintaan user 2026-11-13): semua pool token 24H
# Angka dari respons Meteora query=9sFG…&timeframe=24h (2026-11-13).
# ---------------------------------------------------------------------------

SAKURA = "9sFGCTjEsBk78uC2bCdxtwuUM1aartbBhe8WQXwRpump"


def _sakura(pool, name, pool_type, fee, volume, swaps, traders, mint=SAKURA):
    return {"pool_address": pool, "name": name, "pool_type": pool_type,
            "token_x": {"address": mint, "symbol": "Sakura", "name": "Sakura",
                        "market_cap": 440_665.0},
            "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
            "fee_pct": fee, "tvl": 1000.0, "active_tvl": 900.0, "fee": volume * fee / 100,
            "volume": volume, "swap_count": swaps, "unique_traders": traders,
            "fee_active_tvl_ratio": 10.0, "volatility": 4.0}


SAKURA_24H = [
    _sakura("7knRBTadCAP7DDAze3miXbuKcyPvP2MMRWwhcdD5T9fs", "Sakura-SOL", "dlmm", 1.0,
            262915.9487727702, 5605.0, 1959.0),
    _sakura("DutNdXzYJ1bWZk8EnSyi5oCD5fApwnShUaECZgAVwmDR", "Sakura-SOL", "dlmm", 3.0,
            328806.0667192173, 5012.0, 1713.0),
    _sakura("F5vKxvm9Kiziw7ELUFzmfzVE3GKxpzdQ1p3KrkdzmhyH", "Sakura-SOL", "dlmm", 2.0,
            186403.12088436977, 2774.0, 1132.0),
    _sakura("37BBxNHsTMNuN7N5rAuJjjADaymLKmxChgpwKxJb19nv", "Sakura-SOL", "damm_v2", 6.0,
            5.356982188770377, 242.0, 42.0),
]


class TokenActivityTest(unittest.TestCase):
    def test_pools_of_mint_hanya_pool_token_dan_urut_volume(self):
        other = _sakura("OTHERPOOL" + "1" * 35, "X-SOL", "dlmm", 2.0, 1e9, 1, 1,
                        mint="Xmint" + "2" * 39)
        pools = pf.pools_of_mint(SAKURA_24H + [other, SAKURA_24H[0]], SAKURA)
        self.assertEqual(len(pools), 4)  # duplikat dan token lain dibuang
        self.assertEqual(pools[0]["pool"], SAKURA_24H[1]["pool_address"])  # DutNdX volume terbesar
        self.assertEqual([p["volume"] for p in pools],
                         sorted((p["volume"] for p in pools), reverse=True))

    def test_rata_rata_swap_per_pool(self):
        pools = {p["pool"]: p for p in pf.pools_of_mint(SAKURA_24H, SAKURA)}
        self.assertAlmostEqual(pools[SAKURA_24H[0]["pool_address"]]["avg_swap"], 46.91, places=2)
        self.assertAlmostEqual(pools[SAKURA_24H[1]["pool_address"]]["avg_swap"], 65.60, places=2)
        self.assertAlmostEqual(pools[SAKURA_24H[2]["pool_address"]]["avg_swap"], 67.20, places=2)

    def test_total_token_dan_rata_rata_tertimbang(self):
        total = pf.token_total(pf.pools_of_mint(SAKURA_24H, SAKURA))
        self.assertEqual(total["pools"], 4)
        self.assertAlmostEqual(total["volume"], 778130.49, places=2)
        self.assertEqual(total["swaps"], 13633)
        self.assertAlmostEqual(total["avg_swap"], 778130.49 / 13633, places=6)

    def test_pool_tanpa_swap_tidak_punya_rata_rata(self):
        row = _sakura("Z" * 44, "Z-SOL", "dlmm", 2.0, 100.0, 0.0, 0.0)
        self.assertIsNone(pf.pool_activity(row)["avg_swap"])
        self.assertIsNone(pf.token_total([pf.pool_activity(row)])["avg_swap"])

    def test_fetch_token_pools_kirim_query_dan_ikuti_cursor(self):
        pages = [
            {"data": [SAKURA_24H[0], SAKURA_24H[1]], "after_key": "k1", "has_more": True},
            {"data": [SAKURA_24H[2], SAKURA_24H[3]], "after_key": None, "has_more": False},
        ]
        calls = []

        def fake(params, **kwargs):
            calls.append(dict(params))
            return pages[len(calls) - 1]

        with mock.patch.object(pf, "_get_payload", side_effect=fake):
            rows, errors, truncated = pf.fetch_token_pools(SAKURA)
        self.assertEqual(len(rows), 4)
        self.assertEqual((errors, truncated), ([], False))
        self.assertEqual(calls[0]["query"], SAKURA)
        self.assertEqual(calls[0]["timeframe"], "24h")
        self.assertNotIn("after_key", calls[0])
        self.assertEqual(calls[1]["after_key"], "k1")
        self.assertNotIn("filter_by", calls[0])  # semua tipe pool, tanpa pra-saring listing

    def test_fetch_token_pools_error_dan_cursor_macet(self):
        with mock.patch.object(pf, "_get_payload", side_effect=RuntimeError("boom")):
            rows, errors, truncated = pf.fetch_token_pools(SAKURA)
        self.assertEqual((rows, errors, truncated), ([], ["boom"], True))

        stuck = {"data": [SAKURA_24H[0]], "after_key": "same", "has_more": True}
        with mock.patch.object(pf, "_get_payload", return_value=stuck) as fake:
            rows, errors, truncated = pf.fetch_token_pools(SAKURA, max_pages=10)
        self.assertTrue(truncated)
        self.assertEqual(fake.call_count, 2)

    def test_enrich_mengisi_token_stats_tanpa_mengubah_passing(self):
        rows = meteora_rows()
        result = pf.scan_pools(listing=(rows, [], False))
        passing_before = [r["pool"] for r in result["passing"]]

        def fake(mint):
            return ([r for r in rows if pf.mint_of_pool(r) == mint], [], False)

        pf.enrich_scan_result(result, fetch=fake)
        self.assertEqual([r["pool"] for r in result["passing"]], passing_before)
        self.assertEqual(len(result["token_stats"]), len(passing_before))
        stats = result["token_stats"][pf.mint_of_pool(rows[0])]
        self.assertEqual(stats["total"]["pools"], 1)
        self.assertFalse(stats["partial"])

    def test_enrich_gagal_memakai_pool_hasil_scan_dan_ditandai(self):
        result = pf.scan_pools(listing=(meteora_rows(), [], False))

        def boom(mint):
            raise RuntimeError("timeout")

        pf.enrich_scan_result(result, fetch=boom)
        for mint, stats in result["token_stats"].items():
            self.assertTrue(stats["fallback"])
            self.assertTrue(stats["partial"])
            self.assertEqual(stats["errors"], ["timeout"])
            self.assertEqual(stats["total"]["pools"], 1)

    def test_enrich_tanpa_passing_tidak_memanggil_jaringan(self):
        result = pf.scan_pools(listing=([], [], False))
        with mock.patch.object(pf, "fetch_token_pools") as fake:
            pf.enrich_scan_result(result)
        fake.assert_not_called()
        self.assertEqual(result["token_stats"], {})

    def test_paling_ramai_token_volume_terbesar_dan_pool_terbesarnya(self):
        rows = meteora_rows()
        result = pf.scan_pools(listing=(rows, [], False))
        pf.enrich_scan_result(result, fetch=lambda mint: (
            [dict(r, volume=(900_000.0 if pf.mint_of_pool(r) == pf.mint_of_pool(rows[3]) else 5.0))
             for r in rows if pf.mint_of_pool(r) == mint], [], False))
        top = pf.most_crowded(result)
        self.assertEqual(top["mint"], pf.mint_of_pool(rows[3]))
        self.assertEqual(top["symbol"], "DacityCoin")
        self.assertAlmostEqual(top["total"]["volume"], 900_000.0)
        self.assertEqual(top["busiest"]["pool"], rows[3]["pool_address"])
        self.assertIsNone(pf.most_crowded({"passing": [], "token_stats": {}}))

    def test_scan_dan_alert_tidak_memuat_token_stats(self):
        result = pf.scan_pools(listing=(meteora_rows(), [], False))
        self.assertNotIn("token_stats", result)  # alert memakai scan_pools tanpa enrichment
        self.assertNotIn("token_stats", result["passing"][0])

    def test_fmt_usd2_dan_fmt_int(self):
        self.assertEqual(pf.fmt_usd2(57.08), "$57,08")
        self.assertEqual(pf.fmt_usd2(1234.5), "$1.234,50")
        self.assertEqual(pf.fmt_usd2(None), "—")
        self.assertEqual(pf.fmt_int(13633), "13.633")
        self.assertEqual(pf.fmt_int(None), "—")

