# -*- coding: utf-8 -*-
"""Overlay scan manual di atas snapshot terpublikasi (holder_status).

Latar belakang kasus nyata (AGENTHQ, 2026-09-03): halaman Holder Analytic
menulis hasil scan manual ke ``holder_history.json`` tetapi tidak mempublish
``holder_status.json``, sehingga kartu "Dust hold % MC" menampilkan angka cron
2 jam lebih tua (1,16%) sementara grafik sudah memuat titik scan manual (0,7%).
Selisihnya besar karena harga naik 1,74x dan cutoff dust **$10 per wallet dalam
USD** menggeser klasifikasi wallet — dust % MC tidak invariant terhadap harga.
"""
from __future__ import annotations

import time
import unittest

import holder_status as ss

MINT = "FnLox4hs8zB3YefUyBdwFtTmZm7cMaNSHr5utV4Yswrm"
OTHER = "So11111111111111111111111111111111111111112"
SNAP_TS = 1_788_446_127
MANUAL_TS = 1_788_453_000


def _snapshot_token(**over):
    token = {
        "symbol": "AGENTHQ",
        "price": 0.0001085,
        "marketcap": 108_545.0,
        "analyzed_at": SNAP_TS,
        "holders": {"dust_count": 833, "dust_pct_mc": 1.1578,
                    "real_count": 405, "dust_value_usd": 1256.73,
                    "mid": {"count": 173, "pct_mc": 76.1726}},
        "history": [{"ts": SNAP_TS, "dust_pct_mc": 1.1578}],
        "cohort": {"frozen_at": SNAP_TS, "balances": {"A": 10.0}},
        "alert_state": {"sent_event_ids": ["x"]},
        "chronology": {"intervals": []},
    }
    token.update(over)
    return token


def _status(**over):
    status = {"updated_at": SNAP_TS, "scanner": "holder-dust-v1",
              "tokens": {MINT: _snapshot_token()}}
    status.update(over)
    return status


def _analysis(dust_pct=0.70, dust_count=712, ts=MANUAL_TS, price=0.0001889,
              mc=188_968.0, **extra_holders):
    holders = {"dust_count": dust_count, "dust_pct_mc": dust_pct,
               "real_count": 526, "dust_value_usd": 1323.0,
               "mid": {"count": 173, "pct_mc": 76.17, "balances": {"A": 9.0}},
               "wallet_snapshot": {"wallets": [{"address": "A" * 40}]},
               "cohort_now": {"A": 9.0},
               "chrono_snapshot": {"wallets": {"A": 9.0}}}
    holders.update(extra_holders)
    return {"ca": MINT, "symbol": "AGENTHQ", "marketcap": mc, "price": price,
            "analyzed_at": ts, "holders": holders}


class CompactManualScanTest(unittest.TestCase):
    def test_payload_keeps_metric_fields_only(self):
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        self.assertEqual(scan["mint"], MINT)
        self.assertEqual(scan["saved_at"], MANUAL_TS)
        analysis = scan["analysis"]
        self.assertEqual(analysis["price"], 0.0001889)
        self.assertEqual(analysis["marketcap"], 188_968.0)
        self.assertEqual(analysis["analyzed_at"], MANUAL_TS)
        self.assertEqual(analysis["holders"]["dust_pct_mc"], 0.70)
        self.assertEqual(analysis["holders"]["dust_count"], 712)

    def test_payload_drops_heavy_maps(self):
        holders = ss.compact_manual_scan(MINT, _analysis())["analysis"]["holders"]
        self.assertNotIn("wallet_snapshot", holders)
        self.assertNotIn("cohort_now", holders)
        self.assertNotIn("chrono_snapshot", holders)
        self.assertNotIn("balances", holders["mid"])
        self.assertEqual(sorted(holders["mid"]),
                         ["count", "pct_mc", "value_usd"])

    def test_payload_survives_missing_or_bad_analysis(self):
        for bad in (None, {}, "bukan-dict", 42):
            scan = ss.compact_manual_scan(MINT, bad, saved_at=MANUAL_TS)
            self.assertEqual(scan["mint"], MINT)
            self.assertEqual(scan["analysis"]["holders"], {})
            self.assertEqual(scan["saved_at"], MANUAL_TS)

    def test_saved_at_defaults_to_now(self):
        before = int(time.time())
        scan = ss.compact_manual_scan(MINT, _analysis())
        self.assertGreaterEqual(scan["saved_at"], before)
        self.assertLessEqual(scan["saved_at"], int(time.time()) + 1)

    def test_mint_dinormalisasi_ke_string(self):
        self.assertEqual(ss.compact_manual_scan(None, _analysis())["mint"], "")
        self.assertEqual(ss.compact_manual_scan(123, None)["mint"], "123")


class ResolveTokenViewTest(unittest.TestCase):
    def test_without_manual_scan_snapshot_wins(self):
        view = ss.resolve_token_view(_snapshot_token(), None, mint=MINT)
        self.assertEqual(view["view_source"], "snapshot")
        self.assertEqual(view["holders"]["dust_pct_mc"], 1.1578)
        self.assertEqual(view["analyzed_at"], SNAP_TS)

    def test_manual_scan_newer_replaces_metrics(self):
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        view = ss.resolve_token_view(_snapshot_token(), scan, mint=MINT)
        self.assertEqual(view["view_source"], "manual")
        self.assertEqual(view["holders"]["dust_pct_mc"], 0.70)
        self.assertEqual(view["holders"]["dust_count"], 712)
        self.assertEqual(view["price"], 0.0001889)
        self.assertEqual(view["marketcap"], 188_968.0)
        self.assertEqual(view["analyzed_at"], MANUAL_TS)

    def test_history_cohort_alert_state_tetap_dari_snapshot(self):
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        view = ss.resolve_token_view(_snapshot_token(), scan, mint=MINT)
        self.assertEqual(view["history"], [{"ts": SNAP_TS, "dust_pct_mc": 1.1578}])
        self.assertEqual(view["cohort"], {"frozen_at": SNAP_TS,
                                          "balances": {"A": 10.0}})
        self.assertEqual(view["alert_state"], {"sent_event_ids": ["x"]})
        self.assertEqual(view["chronology"], {"intervals": []})

    def test_manual_scan_older_than_snapshot_ignored(self):
        scan = ss.compact_manual_scan(MINT, _analysis(ts=SNAP_TS - 600),
                                      saved_at=SNAP_TS - 600)
        view = ss.resolve_token_view(_snapshot_token(), scan, mint=MINT)
        self.assertEqual(view["view_source"], "snapshot")
        self.assertEqual(view["holders"]["dust_pct_mc"], 1.1578)

    def test_timestamp_sama_manual_menang(self):
        scan = ss.compact_manual_scan(MINT, _analysis(ts=SNAP_TS),
                                      saved_at=SNAP_TS)
        view = ss.resolve_token_view(_snapshot_token(), scan, mint=MINT)
        self.assertEqual(view["view_source"], "manual")
        self.assertEqual(view["holders"]["dust_pct_mc"], 0.70)

    def test_snapshot_tanpa_analyzed_at_diisi_dari_saved_at(self):
        scan = ss.compact_manual_scan(MINT, _analysis(ts=None),
                                      saved_at=MANUAL_TS)
        token = _snapshot_token(analyzed_at=None)
        view = ss.resolve_token_view(token, scan, mint=MINT)
        self.assertEqual(view["view_source"], "manual")
        self.assertEqual(view["analyzed_at"], MANUAL_TS)

    def test_timestamp_string_tetap_dibandingkan_benar(self):
        scan = ss.compact_manual_scan(MINT, _analysis(ts=str(MANUAL_TS)),
                                      saved_at=str(MANUAL_TS))
        view = ss.resolve_token_view(_snapshot_token(analyzed_at=str(SNAP_TS)),
                                     scan, mint=MINT)
        self.assertEqual(view["view_source"], "manual")

    def test_mint_berbeda_diabaikan(self):
        scan = ss.compact_manual_scan(OTHER, _analysis(), saved_at=MANUAL_TS)
        view = ss.resolve_token_view(_snapshot_token(), scan, mint=MINT)
        self.assertEqual(view["view_source"], "snapshot")
        self.assertEqual(view["holders"]["dust_pct_mc"], 1.1578)

    def test_mint_di_token_juga_dijaga(self):
        # tanpa argumen ``mint``: penjagaan memakai ``token["mint"]``.
        scan = ss.compact_manual_scan(OTHER, _analysis(), saved_at=MANUAL_TS)
        view = ss.resolve_token_view(_snapshot_token(mint=MINT), scan)
        self.assertEqual(view["view_source"], "snapshot")
        self.assertEqual(view["holders"]["dust_pct_mc"], 1.1578)
        # mint cocok -> manual dipakai
        cocok = ss.resolve_token_view(_snapshot_token(mint=OTHER), scan)
        self.assertEqual(cocok["view_source"], "manual")

    def test_holders_kosong_atau_rusak_diabaikan(self):
        for holders in ({}, None, "x", 0):
            analysis = _analysis()
            analysis["holders"] = holders
            scan = ss.compact_manual_scan(MINT, analysis, saved_at=MANUAL_TS)
            view = ss.resolve_token_view(_snapshot_token(), scan, mint=MINT)
            self.assertEqual(view["view_source"], "snapshot", holders)

    def test_scan_rusak_tidak_melempar(self):
        for bad in (None, {}, {"mint": MINT}, {"mint": MINT, "analysis": "x"},
                    {"mint": MINT, "analysis": {"holders": {"a": 1}}},
                    "bukan-dict", 7):
            view = ss.resolve_token_view(_snapshot_token(), bad, mint=MINT)
            self.assertIn(view["view_source"], ("snapshot", "manual"))
            self.assertIsInstance(view, dict)

    def test_token_kosong_plus_scan_manual(self):
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        view = ss.resolve_token_view({}, scan, mint=MINT)
        self.assertEqual(view["view_source"], "manual")
        self.assertEqual(view["holders"]["dust_pct_mc"], 0.70)
        self.assertEqual(view.get("history") or [], [])  # tanpa riwayat snapshot

    def test_status_token_bukan_dict(self):
        for bad in (None, [], "x"):
            view = ss.resolve_token_view(bad, None, mint=MINT)
            self.assertEqual(view, {"view_source": "snapshot"})

    def test_input_tidak_dimutasi(self):
        token = _snapshot_token()
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        before = repr(token)
        view = ss.resolve_token_view(token, scan, mint=MINT)
        self.assertEqual(repr(token), before)
        self.assertIsNot(view, token)


class ApplyManualScanTest(unittest.TestCase):
    def test_token_diganti_bila_scan_lebih_baru(self):
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        status = _status()
        out = ss.apply_manual_scan(status, scan)
        self.assertEqual(out["tokens"][MINT]["holders"]["dust_pct_mc"], 0.70)
        self.assertEqual(out["tokens"][MINT]["view_source"], "manual")
        self.assertEqual(out["updated_at"], SNAP_TS)

    def test_status_asli_tidak_berubah(self):
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        status = _status()
        before = repr(status)
        out = ss.apply_manual_scan(status, scan)
        self.assertEqual(repr(status), before)
        self.assertIsNot(out, status)
        self.assertEqual(status["tokens"][MINT]["holders"]["dust_pct_mc"], 1.1578)

    def test_scan_basi_atau_mint_lain_tidak_menyentuh_status(self):
        stale = ss.compact_manual_scan(MINT, _analysis(ts=SNAP_TS - 60),
                                       saved_at=SNAP_TS - 60)
        lain = ss.compact_manual_scan(OTHER, _analysis(), saved_at=MANUAL_TS)
        for scan in (stale, lain, None, {}, {"mint": ""}):
            status = _status()
            out = ss.apply_manual_scan(status, scan)
            self.assertEqual(out["tokens"][MINT]["holders"]["dust_pct_mc"],
                             1.1578)
            self.assertNotIn("view_source", out["tokens"][MINT])

    def test_token_baru_ditambahkan_bila_belum_ada_di_snapshot(self):
        scan = ss.compact_manual_scan(OTHER, _analysis(), saved_at=MANUAL_TS)
        out = ss.apply_manual_scan(_status(), scan)
        self.assertIn(OTHER, out["tokens"])
        self.assertEqual(out["tokens"][OTHER]["view_source"], "manual")
        self.assertEqual(out["tokens"][OTHER]["holders"]["dust_pct_mc"], 0.70)
        self.assertIn(MINT, out["tokens"])  # token lama tidak dihapus

    def test_status_kosong_atau_rusak(self):
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        for bad in (None, {}, {"tokens": None}, "x"):
            out = ss.apply_manual_scan(bad, scan)
            self.assertIsInstance(out, dict)
        out = ss.apply_manual_scan(None, scan)
        self.assertEqual(out["tokens"][MINT]["holders"]["dust_pct_mc"], 0.70)

    def test_tanpa_tokens_key(self):
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        out = ss.apply_manual_scan({"updated_at": 1}, scan)
        self.assertEqual(out["tokens"][MINT]["view_source"], "manual")


class AgentHqRegressionTest(unittest.TestCase):
    """Skenario yang dilaporkan user: grafik 0,7% vs kartu 1,16%."""

    def test_metrik_dan_grafik_sepakat_setelah_scan_manual(self):
        status = _status()
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        view = ss.apply_manual_scan(status, scan)["tokens"][MINT]

        # kartu metrik membaca view["holders"], grafik membaca history store;
        # titik terakhir store = scan manual yang sama.
        last_point = {"ts": MANUAL_TS, "dust_pct_mc": 0.70,
                      "dust_count": 712, "mc": 188_968.0,
                      "price": 0.0001889}
        self.assertEqual(view["holders"]["dust_pct_mc"],
                         last_point["dust_pct_mc"])
        self.assertEqual(view["holders"]["dust_count"],
                         last_point["dust_count"])
        self.assertEqual(view["analyzed_at"], last_point["ts"])

    def test_badge_ikut_nilai_baru(self):
        from holder_history import dust_flag
        scan = ss.compact_manual_scan(MINT, _analysis(), saved_at=MANUAL_TS)
        view = ss.apply_manual_scan(_status(), scan)["tokens"][MINT]
        before = dust_flag(1.1578, 1.1087)
        after = dust_flag(view["holders"]["dust_pct_mc"], 1.1087)
        self.assertEqual(before["level"], "danger")   # >= 1% MC
        self.assertEqual(after["level"], "caution")   # 0.70% -> HATI-HATI


if __name__ == "__main__":
    unittest.main()
