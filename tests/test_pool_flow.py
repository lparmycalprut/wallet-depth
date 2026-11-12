# -*- coding: utf-8 -*-
"""Tes logika Scan Best Pool (12H) — murni, tanpa jaringan dan tanpa Streamlit.

Fixture ``METEORA_12H`` adalah 12 pool asli dari respons Meteora (timeframe=12h,
2026-11-12) yang dikirim user. Hasil yang diharapkan dihitung manual dari aturan:
hanya BxyK (Dacity-SOL) dan HcyY (PUSSY-SOL) yang lolos.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pool_flow as pf  # noqa: E402

SOL = "So11111111111111111111111111111111111111112"


def _row(pool, symbol, *, fee, tvl, open_pos, active, vol, fa, mint=None):
    mint = mint or ("M" + pool[:8].ljust(43, "x"))
    return {"pool_address": pool, "name": f"{symbol}-SOL", "pool_type": "dlmm",
            "token_x": {"address": mint, "symbol": symbol, "name": symbol},
            "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
            "fee_pct": fee, "tvl": tvl, "open_positions": open_pos,
            "active_positions": active, "volatility": vol, "fee_active_tvl_ratio": fa}


def _good(**over):
    base = dict(fee=2.0, tvl=60_000.0, open_pos=60, active=40, vol=8.0, fa=30.0)
    base.update(over)
    return _row("PoolGood" + "1" * 30, "GOOD", **base)


# (pool, symbol, fee, tvl, open, active, volatility, fee/active TVL) — respons Meteora 12H
METEORA_12H = [
    ("7xg8P4oQEbUuEfQMTzcNgQRvYWPdze7Fsjbvp9BtHxCz", "Max", 3.0, 15934.53, 42, 14, 16.83, 338.67),
    ("BoTGzHBpCiMM255GmMUCzLGD4mLeX95g6eJKy7wjCBub", "Max", 3.0, 9918.85, 38, 24, 12.22, 440.51),
    ("5Dc4s9fxxQoPfaMUaxFKB5v1Nh6FPqest7usgyvGXwWw", "DacityCoin", 2.0, 164176.35, 261, 84, 3.15, 10.00),
    ("ARwLqJJHRzUwpL4LLTQMykuPLzUTwNSaezP9E85f7yht", "LuckyCoin", 2.0, 6321.82, 25, 21, 7.10, 43.63),
    ("tXzZcH3i1Ku5H54SNmrRbJYiZYqYto597xd1kWnnvom", "PAYDAY", 2.0, 9286.77, 38, 18, 4.29, 12.81),
    ("FSb7qz3cMGjYacrLfoKumozoqFibiAtzjDq97FxHivYP", "DacityCoin", 5.0, 11865.37, 39, 14, 4.09, 11.62),
    ("5WVURqJSLRFNZDVDF2njtjZihRLeALvt5tss3yjt2Vik", "paws", 2.0, 23231.38, 85, 64, 3.30, 9.34),
    ("HcyYBrZVFDDVBLtLxL5C1HDJND1p86BoNA6m7MjBKE3p", "PUSSY", 2.0, 14860.61, 73, 41, 11.42, 125.29),
    ("91iHWaWXneUyoNDJhSno7ezxQg1VW5P6PdarNGyFfPCz", "STANK", 2.0, 127366.79, 279, 217, 2.19, 10.66),
    ("BxyKfpuCn3qVi9gCYHKPYqo8L5mz9MiyAuZfQ7YGHchi", "Dacity", 3.0, 11354.96, 70, 44, 5.20, 46.18),
    ("C1Xwm4e8UEQRmhsmogn3HYoHLqJu7M7FVG7nrtPvqHVH", "HOLD", 2.0, 6634.68, 46, 21, 4.34, 62.44),
    ("Apb6s7SHxckEBHuJoKmidjQb6jggR2h8U7dtjZDdwvcV", "timmy", 2.0, 14389.52, 89, 65, 4.27, 14.95),
]


def _meteora_rows():
    return [_row(p, s, fee=f, tvl=t, open_pos=o, active=a, vol=v, fa=fa)
            for p, s, f, t, o, a, v, fa in METEORA_12H]


class RuleTest(unittest.TestCase):
    def test_baris_yang_memenuhi_semua_aturan_lolos(self):
        result = pf.evaluate_pool(_good())
        self.assertTrue(result["passes"], result["reasons"])
        self.assertAlmostEqual(result["in_range"], 66.666, places=2)

    def test_setiap_ambang_tepat_di_batas_lolos_dan_di_bawahnya_gagal(self):
        cases = [
            ("fee tier", dict(fee=2.0), True), ("fee tier", dict(fee=1.99), False),
            ("open", dict(open_pos=50), True), ("open", dict(open_pos=49), False),
            ("tvl", dict(tvl=5_000.0), True), ("tvl", dict(tvl=4_999.0), False),
            ("vol", dict(vol=5.0), True), ("vol", dict(vol=4.99), False),
            ("fa", dict(fa=20.0), True), ("fa", dict(fa=19.9), False),
            ("in-range", dict(open_pos=60, active=30), True),   # 50 % tepat
            ("in-range", dict(open_pos=60, active=29), False),  # 48,3 %
        ]
        for label, over, expected in cases:
            with self.subTest(rule=label, over=over):
                self.assertEqual(pf.evaluate_pool(_good(**over))["passes"], expected)

    def test_open_positions_nol_atau_hilang_tidak_terukur_dan_gagal(self):
        for over in (dict(open_pos=0, active=0), dict(open_pos=None, active=None)):
            with self.subTest(over=over):
                result = pf.evaluate_pool(_good(**over))
                self.assertFalse(result["passes"])
                self.assertIsNone(result["in_range"])

    def test_alasan_gagal_menyebut_semua_aturan_yang_dilanggar(self):
        result = pf.evaluate_pool(_good(fee=1.0, tvl=100.0, vol=1.0, fa=1.0))
        self.assertEqual(len(result["reasons"]), 4)
        self.assertTrue(any("fee tier" in r for r in result["reasons"]))
        self.assertTrue(any("volatility" in r for r in result["reasons"]))

    def test_in_range_pakai_active_positions_bukan_pct_dari_server(self):
        row = _good(open_pos=50, active=25)
        row["active_positions_pct"] = 99.0  # nilai server diabaikan
        self.assertAlmostEqual(pf.in_range_pct(row), 50.0)


class RealResponseTest(unittest.TestCase):
    """Dua pool yang lolos harus sama dengan hasil hitung manual dari respons Meteora."""

    def test_hanya_dua_pool_yang_lolos_dari_respons_meteora(self):
        result = pf.scan_pools(listing=(_meteora_rows(), [], False))
        self.assertEqual(result["candidates"], 12)
        self.assertEqual(
            [r["pool"] for r in result["passing"]],
            ["BxyKfpuCn3qVi9gCYHKPYqo8L5mz9MiyAuZfQ7YGHchi",   # in-range 62,9 %
             "HcyYBrZVFDDVBLtLxL5C1HDJND1p86BoNA6m7MjBKE3p"],  # in-range 56,2 %
        )

    def test_alasan_gagal_pool_terbesar_sesuai_perhitungan_manual(self):
        results = {r["pool"]: r for r in pf.scan_pools(listing=(_meteora_rows(), [], False))["results"]}
        stank = results["91iHWaWXneUyoNDJhSno7ezxQg1VW5P6PdarNGyFfPCz"]
        self.assertFalse(stank["passes"])
        self.assertTrue(any("volatility" in r for r in stank["reasons"]))
        self.assertTrue(any("fee/active" in r for r in stank["reasons"]))
        dacity_5dc = results["5Dc4s9fxxQoPfaMUaxFKB5v1Nh6FPqest7usgyvGXwWw"]
        self.assertTrue(any("in-range" in r for r in dacity_5dc["reasons"]))  # 32 %


class ScanTest(unittest.TestCase):
    def test_urut_in_range_terbesar_lalu_fee_active(self):
        rows = [_good(open_pos=60, active=30, fa=50.0),    # 50 %
                _good(open_pos=60, active=40, fa=25.0),    # 66,7 %
                _good(open_pos=60, active=40, fa=90.0)]    # 66,7 %, fee lebih besar
        rows[0]["pool_address"] = "A" * 44
        rows[1]["pool_address"] = "B" * 44
        rows[2]["pool_address"] = "C" * 44
        passing = pf.scan_pools(listing=(rows, [], False))["passing"]
        self.assertEqual([r["pool"] for r in passing], ["C" * 44, "B" * 44, "A" * 44])

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

    def test_fetch_listing_mengirim_timeframe_dan_pra_saring(self):
        captured = []

        def fake_get(params, **kwargs):
            captured.append(params)
            return []

        from unittest import mock
        with mock.patch.object(pf, "_get_json", side_effect=fake_get):
            rows, errors, truncated = pf.fetch_listing(max_pages=2, workers=2)
        self.assertEqual((rows, errors, truncated), ([], [], False))
        self.assertEqual(len(captured), 2)
        for params in captured:
            self.assertEqual(params["timeframe"], "12h")
            self.assertEqual(params["category"], "top")
            self.assertEqual(params["page_size"], 50)
            self.assertIn("fee_active_tvl_ratio>=20", params["filter_by"])
            self.assertIn("fee_pct>=2", params["filter_by"])


class PaginationTest(unittest.TestCase):
    def _pages(self, sizes, errors_at=()):
        """Fake _get_json: halaman ke-n berisi sizes[n-1] baris (atau raise)."""
        from unittest import mock

        calls = []

        def fake(params, **kwargs):
            page = params["page"]
            calls.append(page)
            if page in errors_at:
                raise RuntimeError("boom")
            size = sizes[page - 1] if page - 1 < len(sizes) else 0
            return [{"pool_address": f"P{page}-{i}"} for i in range(size)]

        return mock.patch.object(pf, "_get_json", side_effect=fake), calls

    def test_berhenti_di_halaman_pendek(self):
        patcher, calls = self._pages([50, 50, 3])  # halaman 4+ kosong (akhir listing)
        with patcher:
            rows, errors, truncated = pf.fetch_listing(max_pages=10, workers=2)
        self.assertEqual(len(rows), 103)
        self.assertEqual(errors, [])
        self.assertFalse(truncated)
        # gelombang berisi halaman 3–4; setelahnya tidak ada gelombang baru
        self.assertEqual(sorted(calls), [1, 2, 3, 4])

    def test_truncated_bila_batas_tercapai_dan_halaman_terakhir_penuh(self):
        patcher, _ = self._pages([50, 50, 50, 50])
        with patcher:
            rows, _, truncated = pf.fetch_listing(max_pages=3, workers=1)
        self.assertEqual(len(rows), 150)
        self.assertTrue(truncated)

    def test_error_halaman_dicatat_dan_listing_lanjut(self):
        patcher, _ = self._pages([50, 4], errors_at=(1,))
        with patcher:
            rows, errors, truncated = pf.fetch_listing(max_pages=5, workers=1)
        self.assertEqual(errors, ["boom"])
        self.assertEqual(len(rows), 4)
        self.assertFalse(truncated)

    def test_pool_terakhir_dari_listing_penuh_menandai_truncated_di_scan(self):
        rows = [_good()] * 0
        result = pf.scan_pools(listing=(rows, [], True))
        self.assertTrue(result["truncated"])


class AlertTest(unittest.TestCase):
    def _passing(self):
        return pf.scan_pools(listing=(_meteora_rows(), [], False))["passing"]

    def test_tanpa_pool_lolos_tidak_ada_alert(self):
        state = pf.empty_state()
        self.assertIsNone(pf.apply_best_alert(state, []))
        self.assertEqual(state["alerts"], [])
        self.assertEqual(state["best_alert"]["next_no"], 1)

    def test_alert_memberi_nomor_dan_menandai_pool_yang_sudah_pernah_muncul(self):
        state = pf.empty_state()
        first = pf.apply_best_alert(state, self._passing())
        self.assertIn("alert #1", first)
        self.assertEqual(first.count("🆕 baru"), 2)
        self.assertEqual(state["best_alert"]["next_no"], 2)
        second = pf.apply_best_alert(state, self._passing())
        self.assertIn("alert #2", second)
        self.assertEqual(second.count("🔁 sudah pernah · alert #1"), 2)
        self.assertNotIn("🆕 baru", second)

    def test_alert_memuat_tautan_dan_filter(self):
        text = pf.best_alert_text(1, self._passing(), {})
        self.assertIn("in-range", text)
        self.assertIn("gmgn.ai", text)
        self.assertIn("meteora.ag", text)
        self.assertIn("12H", text)

    def test_split_telegram_tiap_bagian_di_bawah_batas(self):
        text = "\n".join("baris " + "x" * 90 for _ in range(200))
        parts = pf.split_for_telegram(text, limit=500)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 500 for p in parts))
        self.assertEqual("\n".join(parts), text)


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
            pf.scan_pools(listing=(_meteora_rows(), [], False))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
