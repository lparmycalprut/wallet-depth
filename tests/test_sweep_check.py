# -*- coding: utf-8 -*-
"""Cek sweep manual satu CA (permintaan user 2026-10-20).

Yang dijaga:
- input hanya menerima tepat satu alamat Solana yang valid;
- pemindaian tidak menulis apa pun ke state/berkas, tidak mengirim alert, dan
  tidak menambah mint ke watchlist;
- hasil memakai bentuk baris yang sama dengan run_scan.
"""
from __future__ import annotations

import copy
import unittest
from unittest import mock

import sweep_check as check
import sweep_scan as scan
import sweep_store as store
from tests.test_sweep_screen import _birth_candles

NOW = 1000 + 49 * 3600
CA = "8nPoBHiBM6pybxMws9PA2JRb9BjkppBfqcZGmot4DMBC"  # 44 karakter base58


def _metrics(mint="M", price=0.7):
    return {"mint": mint, "ok": True, "symbol": "TST", "price_usd": price,
            "pair_created_at": 1000, "pair_address": "P",
            "holder_cost_basis": 1.0, "holder_cost_balance": 1.0,
            "liq_usd": 1000.0, "fdv_usd": 10000.0,
            "mint_authority": None, "freeze_authority": None,
            "top10_holder_pct": 18.0, "holder_pcts": [2.0]}


def _bundle(mint="M", metrics=None):
    return {"mint": mint, "metrics": metrics or _metrics(mint),
            "candles_hour": [], "candles_min5": [],
            "cohort_candles": _birth_candles(), "cohort_error": ""}


_DELTA_PATCH = None


def setUpModule():
    global _DELTA_PATCH
    import _offline_delta
    _DELTA_PATCH = _offline_delta.start()


def tearDownModule():
    if _DELTA_PATCH is not None:
        _DELTA_PATCH.stop()


class ParseSingleCaTest(unittest.TestCase):
    def test_valid_single_ca(self):
        self.assertEqual(check.parse_single_ca(CA), (CA, ""))

    def test_surrounding_whitespace_and_newlines_are_fine(self):
        self.assertEqual(check.parse_single_ca(f"  \n{CA}\n "), (CA, ""))

    def test_comment_line_is_ignored(self):
        self.assertEqual(check.parse_single_ca(f"# catatan\n{CA}"), (CA, ""))

    def test_empty_is_rejected(self):
        mint, error = check.parse_single_ca("   ")
        self.assertEqual(mint, "")
        self.assertIn("Masukkan", error)

    def test_multiple_cas_are_rejected(self):
        mint, error = check.parse_single_ca(f"{CA}\n{CA[:-1]}A")
        self.assertEqual(mint, "")
        self.assertIn("hanya satu CA", error)

    def test_invalid_base58_is_rejected(self):
        # '0' dan 'O' tidak ada di base58 Solana.
        for bad in ("0" + CA[1:], CA[:-1] + "O", "short123"):
            mint, error = check.parse_single_ca(bad)
            self.assertEqual(mint, "", bad)
            self.assertTrue(error, bad)


class CheckMintTest(unittest.TestCase):
    def test_ok_scan_returns_row_without_persisting(self):
        state = store.empty_state()
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: _bundle(m)), \
                mock.patch.object(store, "save_state") as save, \
                mock.patch.object(store, "load_watchlist", return_value=[]):
            out = check.check_mint("M", now=NOW, state=state)
        self.assertTrue(out["ok"])
        self.assertEqual(out["error"], "")
        self.assertEqual(out["ts"], NOW)
        self.assertFalse(out["in_watchlist"])
        row = out["row"]
        self.assertEqual(row["mint"], "M")
        self.assertEqual(row["ts"], NOW)
        self.assertIn("verdict", row["result"])
        save.assert_not_called()

    def test_no_alert_is_sent(self):
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: _bundle(m)), \
                mock.patch.object(scan.alert, "send_message") as send, \
                mock.patch.object(store, "load_watchlist", return_value=[]):
            check.check_mint("M", now=NOW, state=store.empty_state())
        send.assert_not_called()

    def test_stored_state_is_read_not_written(self):
        stored = {"snapshots": {"M": {"h1": {"ts": NOW - 7200, "price": 0.45,
                                              "liq_usd": 1000.0,
                                              "fdv_usd": 10000.0}}},
                  "cohort_latched": {}}
        before = copy.deepcopy(stored)
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: _bundle(m, _metrics(m, price=0.7))), \
                mock.patch.object(store, "load_state", return_value=stored), \
                mock.patch.object(store, "save_state") as save, \
                mock.patch.object(store, "load_watchlist", return_value=[]):
            out = check.check_mint("M", now=NOW)
        self.assertEqual(stored, before)
        save.assert_not_called()
        # Riwayat tersimpan tetap dipakai: harga pernah -50% lalu naik → lolos.
        self.assertTrue(out["row"]["result"]["cohort_gate_passed"])

    def test_in_watchlist_flag(self):
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: _bundle(m)), \
                mock.patch.object(store, "load_watchlist", return_value=["M"]):
            out = check.check_mint("M", now=NOW, state=store.empty_state())
        self.assertTrue(out["in_watchlist"])

    def test_metrics_not_ok_reports_error(self):
        bad = {"mint": "M", "ok": False, "error": "DexScreener HTTP 429"}
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: _bundle(m, bad)), \
                mock.patch.object(store, "load_watchlist", return_value=[]):
            out = check.check_mint("M", now=NOW, state=store.empty_state())
        self.assertFalse(out["ok"])
        self.assertIn("429", out["error"])

    def test_fetch_exception_is_reported_not_raised(self):
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=RuntimeError("GeckoTerminal timeout")), \
                mock.patch.object(store, "load_watchlist", return_value=[]):
            out = check.check_mint("M", now=NOW, state=store.empty_state())
        self.assertFalse(out["ok"])
        self.assertIn("timeout", out["error"])

    def test_default_state_is_loaded_from_store(self):
        with mock.patch.object(store, "load_state",
                               return_value=store.empty_state()) as load, \
                mock.patch.object(scan, "_fetch_bundle",
                                  side_effect=lambda m, **kw: _bundle(m)), \
                mock.patch.object(store, "load_watchlist", return_value=[]):
            check.check_mint("M", now=NOW)
        load.assert_called_once()


if __name__ == "__main__":
    unittest.main()
