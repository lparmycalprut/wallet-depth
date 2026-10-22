# -*- coding: utf-8 -*-
"""Catatan kondisi token sebelum sweep (permintaan user 2026-10-21).

Angka di tes ini dihitung manual dari contoh kecil, bukan dari kode yang diuji.
"""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import sweep_scan as scan  # noqa: E402
import sweep_store as store  # noqa: E402

NOW = 1_792_500_000  # detik; kelipatan jam supaya bucket mudah dihitung


class ScanLogEntryTest(unittest.TestCase):
    def test_keeps_only_compact_fields_and_criteria_status(self):
        metrics = {"price_usd": 0.5, "holder_count": 10, "secret_blob": "x"}
        result = {"verdict": "KANDIDAT", "eligible": False, "liq_mc": 0.2,
                  "checks": [{"key": "a", "passed": True, "has_data": True},
                             {"key": "b", "passed": False, "has_data": True},
                             {"key": "c", "passed": False, "has_data": False},
                             {"passed": True}]}  # tanpa key: diabaikan
        entry = store.scan_log_entry(metrics, result, ts=3600, hidden=True)
        self.assertEqual(entry["ts"], 3600)
        self.assertTrue(entry["hidden"])
        self.assertEqual(entry["metrics"], {"price_usd": 0.5, "holder_count": 10})
        self.assertEqual(entry["result"]["verdict"], "KANDIDAT")
        self.assertEqual(entry["criteria"], {"a": "lolos", "b": "gagal", "c": "n/a"})


class ScanLogAddTest(unittest.TestCase):
    def test_keeps_last_six_scans_sorted_by_ts(self):
        state = store.empty_state()
        for ts in (5, 1, 3, 2, 4, 6, 7, 8):  # urutan acak
            store.scan_log_add(state, "M", {"ts": ts})
        kept = [row["ts"] for row in state["scan_log"]["M"]]
        self.assertEqual(kept, [3, 4, 5, 6, 7, 8])  # 6 terbaru

    def test_same_ts_replaces_instead_of_duplicating(self):
        state = store.empty_state()
        store.scan_log_add(state, "M", {"ts": 10, "v": "lama"})
        store.scan_log_add(state, "M", {"ts": 10, "v": "baru"})
        self.assertEqual(len(state["scan_log"]["M"]), 1)
        self.assertEqual(state["scan_log"]["M"][0]["v"], "baru")


class SweepDetailTest(unittest.TestCase):
    def _state(self):
        state = store.empty_state()
        # scan pada 500, 1000, 1800, 2400 (sebelum candle 2500), 2700 (deteksi)
        for ts in (500, 1000, 1800, 2400, 2700):
            store.scan_log_add(state, "M", {"ts": ts, "hidden": ts == 2700})
        return state

    def test_three_scans_before_candle_plus_detecting_scan(self):
        detail = store.sweep_detail(self._state(), "M", 2500, [])
        # 500 terpotong: hanya 3 scan terakhir sebelum candle yang disimpan.
        self.assertEqual([s["ts"] for s in detail["scans"]], [1000, 1800, 2400, 2700])
        self.assertTrue(detail["hidden"])

    def test_candles_window_is_twelve_bars_ending_at_sweep_candle(self):
        candles = [[2200, 1, 1, 1, 1, 1], [2500, 2, 2, 2, 2, 2],
                   [2800, 3, 3, 3, 3, 3],   # setelah candle sweep: dibuang
                   [1000, 4, 4, 4, 4, 4],   # di luar jendela 1 jam: (−1100, 2500]
                   ["bad"]]                 # format salah: dibuang
        detail = store.sweep_detail(self._state(), "M", 2500, candles)
        self.assertEqual([c[0] for c in detail["candles"]], [1000, 2200, 2500])

    def test_no_detecting_scan_means_hidden_unknown(self):
        state = store.empty_state()
        store.scan_log_add(state, "M", {"ts": 100, "hidden": False})
        detail = store.sweep_detail(state, "M", 2500, [])
        self.assertIsNone(detail["hidden"])
        self.assertEqual([s["ts"] for s in detail["scans"]], [100])


class LoadStateKeepsScanLogTest(unittest.TestCase):
    def test_scan_log_survives_save_and_load(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.json"
            state = store.empty_state()
            store.scan_log_add(state, "M", {"ts": 42, "hidden": True})
            path.write_text(json.dumps(state), encoding="utf-8")
            with mock.patch.object(store, "STATE_PATH", str(path)):
                loaded = store.load_state()
        self.assertEqual(loaded["scan_log"]["M"][0]["ts"], 42)


class MergeScanLogTest(unittest.TestCase):
    def test_union_by_ts_local_wins_and_trimmed(self):
        remote = {"M": [{"ts": 1, "v": "r"}, {"ts": 2, "v": "r"}]}
        local = {"M": [{"ts": 2, "v": "l"}, {"ts": 3, "v": "l"}]}
        merged = store._merge_scan_log(remote, local)
        self.assertEqual([row["ts"] for row in merged["M"]], [1, 2, 3])
        self.assertEqual(merged["M"][1]["v"], "l")

    def test_merge_states_carries_scan_log(self):
        remote = store.empty_state()
        local = store.empty_state()
        store.scan_log_add(local, "M", {"ts": 7})
        merged = store.merge_states(remote, local)
        self.assertEqual([row["ts"] for row in merged["scan_log"]["M"]], [7])


class RunScanRecordsPreSweepTest(unittest.TestCase):
    """Alur penuh: scan pertama (tanpa sweep), lalu scan kedua mendeteksi sweep."""

    def _bundle(self, bundler: float, candles_min5):
        metrics = {"mint": "M", "ok": True, "symbol": "TST", "price_usd": 0.5,
                   "holder_min_avg_cost": 1.0, "pair_created_at": 1000,
                   "liq_usd": 1000.0, "fdv_usd": 10000.0,
                   "mint_authority": None, "freeze_authority": None,
                   "top10_holder_pct": 18.0, "holder_pcts": [2.0],
                   "top_bundler_trader_percentage": bundler}
        return {"mint": "M", "metrics": metrics, "candles_hour": [],
                "candles_min5": candles_min5, "cohort_candles": [],
                "cohort_error": ""}

    def test_sweep_on_hidden_mint_keeps_prior_scan_and_candles(self):
        from _offline_delta import start as _offline_start  # noqa: WPS433
        patch = _offline_start()
        self.addCleanup(patch.stop)
        state = store.empty_state()
        t0 = NOW
        t1 = NOW + 1800  # scan kedua, 30 menit kemudian
        candle_ts = t0 + 600  # candle sweep terjadi setelah scan pertama
        candles = [[candle_ts - 300, 1, 1, 1, 0.4, 10],
                   [candle_ts, 1, 1, 0.3, 0.5, 900]]
        context = {"sweep_ts": candle_ts, "close": 0.5, "base_price": 0.4,
                   "peak": 0.6, "liq_mc": 0.1, "vol_x": 90.0,
                   "price_mult": 1.25, "peak_mult": 1.5}
        # Scan pertama: bundler 5% → tersembunyi; belum ada sweep.
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: self._bundle(0.05, [])), \
                mock.patch.object(scan.screen, "detect_sweep", return_value=None):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=t0)
        self.assertEqual(
            [s for s in state.get("signals", []) if s.get("kind") == "sweep"], [])
        # Scan kedua: sweep terdeteksi di mint yang sama.
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: self._bundle(0.05, candles)), \
                mock.patch.object(scan.screen, "detect_sweep",
                                  return_value={"ts": candle_ts}), \
                mock.patch.object(scan.screen, "sweep_context", return_value=context):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=t1)
        sweeps = [s for s in state["signals"] if s.get("kind") == "sweep"]
        self.assertEqual(len(sweeps), 1)
        signal = sweeps[0]
        # Scan sebelum candle (t0) dan scan yang mendeteksi (t1), keduanya tersembunyi.
        self.assertEqual([s["ts"] for s in signal["pre_sweep"]], [t0, t1])
        self.assertEqual([s["hidden"] for s in signal["pre_sweep"]], [True, True])
        self.assertIs(signal["hidden_at_detect"], True)
        # Candle sweep dan satu candle sebelumnya ikut tersimpan.
        self.assertEqual([c[0] for c in signal["pre_candles"]],
                         [candle_ts - 300, candle_ts])


if __name__ == "__main__":
    unittest.main()
