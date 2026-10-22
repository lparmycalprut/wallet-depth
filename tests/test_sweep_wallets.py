# -*- coding: utf-8 -*-
"""Fitur wallet sebelum sweep (permintaan user 2026-10-22).

Angka tes dihitung manual dari contoh kecil, bukan dari kode yang diuji.
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
import sweep_wallets as wallets  # noqa: E402

NOW = 1_792_500_000


def _swap(side, ts, wallet, usd, tags=()):
    return (side, 0.1, ts, wallet, 0.0001, usd, list(tags))


class WalletFeaturesTest(unittest.TestCase):
    """Contoh: jendela 1000–5000, 7 trade di dalamnya (1 di luar, 1 nol, 1 rusak)."""

    def _swaps(self):
        return [
            _swap("buy", 1100, "W1", 100, ["fresh_wallet"]),
            _swap("buy", 1150, "W2", 50, ["bundler"]),
            _swap("buy", 1200, "W3", 30, []),
            _swap("buy", 1500, "W1", 20, ["fresh_wallet"]),
            _swap("sell", 1600, "W3", 40, ["sandwich_bot"]),
            _swap("sell", 2000, "W2", 60, []),
            _swap("buy", 4000, "W4", 500, ["fresh_wallet"]),
            _swap("buy", 900, "W5", 999, []),        # di luar jendela
            _swap("buy", 1300, "W6", 0, []),         # nominal nol
            ("buy", 0.1, 1400),                       # tuple rusak
        ]

    def test_totals_and_wallet_concentration(self):
        f = wallets.wallet_features(self._swaps(), start=1000, end=5000)
        self.assertEqual(f["trades"], 7)
        self.assertEqual((f["buys"], f["sells"]), (5, 2))
        self.assertEqual(f["buy_usd"], 700.0)          # 100+50+30+20+500
        self.assertEqual(f["sell_usd"], 100.0)         # 40+60
        self.assertEqual(f["buy_sell_ratio"], 7.0)
        self.assertEqual(f["buy_wallets"], 4)          # W1, W2, W3, W4
        self.assertEqual(f["median_buy_wallet_usd"], 85.0)  # median [30,50,120,500]
        self.assertEqual(f["top_buy_wallet_usd"], 500.0)
        self.assertEqual(f["top_buy_share"], 0.7143)   # 500/700

    def test_fresh_bundler_and_sandwich_shares(self):
        f = wallets.wallet_features(self._swaps(), start=1000, end=5000)
        self.assertEqual(f["fresh_buy_wallets"], 2)    # W1, W4
        self.assertEqual(f["fresh_buy_share"], 0.8857)  # (100+20+500)/700
        self.assertEqual(f["bundler_buy_wallets"], 1)  # W2
        self.assertEqual(f["bundler_buy_share"], 0.0714)  # 50/700
        self.assertEqual(f["sandwich_share"], 0.05)    # 40/(700+100)

    def test_longest_fresh_bundler_run(self):
        # buy fresh/bundler: 1100 (W1,100), 1150 (W2,50), 1500 (W1,20), 4000 (W4,500).
        # Jarak 50 s → satu rangkaian; 350 s dan 2500 s memutus rangkaian.
        f = wallets.wallet_features(self._swaps(), start=1000, end=5000)
        self.assertEqual(f["run_len"], 2)
        self.assertEqual(f["run_wallets"], 2)
        self.assertEqual(f["run_usd"], 150.0)
        self.assertEqual(f["run_start_ts"], 1100)

    def test_window_bounds_are_inclusive(self):
        swaps = [_swap("buy", 1000, "A", 10), _swap("buy", 2000, "B", 10)]
        f = wallets.wallet_features(swaps, start=1000, end=2000)
        self.assertEqual(f["buy_wallets"], 2)
        f = wallets.wallet_features(swaps, start=1001, end=2000)
        self.assertEqual(f["buy_wallets"], 1)

    def test_no_buys_gives_none_not_zero_division(self):
        # Hanya sell: rasio buy/sell = 0 / 10 = 0 (penyebut > 0).
        f = wallets.wallet_features([_swap("sell", 1100, "A", 10)], start=1000, end=2000)
        self.assertEqual(f["buy_sell_ratio"], 0.0)
        # Hanya buy: penyebut (sell) nol, rasio harus None.
        g = wallets.wallet_features([_swap("buy", 1100, "A", 10)], start=1000, end=2000)
        self.assertIsNone(g["buy_sell_ratio"])
        self.assertIsNone(f["fresh_buy_share"])
        self.assertIsNone(f["top_buy_share"])
        self.assertEqual(f["run_len"], 0)


class VolSpikeTest(unittest.TestCase):
    def _bars(self, last_vol, order=None):
        vols = [10, 20, 30, 40, 50, 60, 70]  # median = 40
        bars = [[1000 + 300 * i, 1, 1, 1, 1, v] for i, v in enumerate(vols)]
        bars.append([1000 + 300 * 7, 1, 1, 1, 1, last_vol])
        if order == "shuffled":
            bars = bars[::-1]
        return bars

    def test_ratio_is_last_volume_over_prior_median(self):
        self.assertEqual(wallets.vol_spike_x(self._bars(200)), 5.0)   # 200/40
        self.assertEqual(wallets.vol_spike_x(self._bars(100)), 2.5)   # 100/40

    def test_order_does_not_matter(self):
        self.assertEqual(wallets.vol_spike_x(self._bars(200, "shuffled")), 5.0)

    def test_too_few_bars_gives_none(self):
        self.assertIsNone(wallets.vol_spike_x(self._bars(200)[:5]))


class WalletFlowStoreTest(unittest.TestCase):
    def test_keeps_last_48_and_replaces_same_ts(self):
        state = store.empty_state()
        for ts in range(60):
            store.wallet_flow_add(state, "M", {"ts": ts, "kind": "spike"})
        store.wallet_flow_add(state, "M", {"ts": 59, "kind": "sweep"})
        rows = state["wallet_flow"]["M"]
        self.assertEqual(len(rows), store.WALLET_FLOW_KEEP)
        self.assertEqual(rows[0]["ts"], 60 - store.WALLET_FLOW_KEEP)
        self.assertEqual(rows[-1]["kind"], "sweep")

    def test_merge_and_load_keep_wallet_flow(self):
        import json
        import tempfile
        local = store.empty_state()
        store.wallet_flow_add(local, "M", {"ts": 7, "kind": "spike"})
        merged = store.merge_states(store.empty_state(), local)
        self.assertEqual([r["ts"] for r in merged["wallet_flow"]["M"]], [7])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.json"
            path.write_text(json.dumps(local), encoding="utf-8")
            with mock.patch.object(store, "STATE_PATH", str(path)):
                loaded = store.load_state()
        self.assertEqual(loaded["wallet_flow"]["M"][0]["ts"], 7)


class RunScanWalletTest(unittest.TestCase):
    """Alur penuh: lonjakan volume mencatat pembanding; sweep baru membawa wallet_pre."""

    def _bundle(self, candles):
        metrics = {"mint": "M", "ok": True, "symbol": "TST", "price_usd": 0.5,
                   "holder_min_avg_cost": 1.0, "pair_created_at": 1000,
                   "liq_usd": 1000.0, "fdv_usd": 10000.0,
                   "mint_authority": None, "freeze_authority": None,
                   "top10_holder_pct": 18.0, "holder_pcts": [2.0],
                   "top_bundler_trader_percentage": 0.5}
        return {"mint": "M", "metrics": metrics, "candles_hour": [],
                "candles_min5": candles, "cohort_candles": [], "cohort_error": ""}

    def _spike_candles(self, last_vol):
        vols = [10, 20, 30, 40, 50, 60, 70]
        bars = [[NOW - 300 * (8 - i), 1, 1, 1, 1, v] for i, v in enumerate(vols)]
        bars.append([NOW, 1, 1, 1, 1, last_vol])
        return bars

    def test_spike_records_comparison_window(self):
        from _offline_delta import start as offline_start
        patch = offline_start()
        self.addCleanup(patch.stop)
        state = store.empty_state()
        swaps = [_swap("buy", NOW - 100, "W1", 80, ["fresh_wallet"])]
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: self._bundle(self._spike_candles(400))), \
                mock.patch.object(scan, "_gmgn_wallet_swaps",
                                  return_value=(swaps, True)) as fetch, \
                mock.patch.object(scan.screen, "detect_sweep", return_value=None):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=NOW)
        fetch.assert_called_once_with("M", NOW - wallets.WINDOW_SEC, NOW)
        entry = state["wallet_flow"]["M"][-1]
        self.assertEqual(entry["kind"], "spike")
        self.assertEqual(entry["spike_x"], 10.0)       # 400 / median(10..70)=40
        self.assertEqual(entry["features"]["fresh_buy_wallets"], 1)

    def test_no_spike_records_nothing(self):
        from _offline_delta import start as offline_start
        patch = offline_start()
        self.addCleanup(patch.stop)
        state = store.empty_state()
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: self._bundle(self._spike_candles(100))), \
                mock.patch.object(scan, "_gmgn_wallet_swaps", return_value=([], True)) as fetch, \
                mock.patch.object(scan.screen, "detect_sweep", return_value=None):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=NOW)
        fetch.assert_not_called()
        self.assertNotIn("M", state.get("wallet_flow", {}))

    def test_sweep_signal_gets_wallet_pre_window_before_candle(self):
        from _offline_delta import start as offline_start
        patch = offline_start()
        self.addCleanup(patch.stop)
        state = store.empty_state()
        candle_ts = NOW - 600
        context = {"sweep_ts": candle_ts, "close": 0.5, "base_price": 0.4,
                   "peak": 0.6, "liq_mc": 0.1, "vol_x": 90.0,
                   "price_mult": 1.25, "peak_mult": 1.5}
        swaps = [_swap("buy", candle_ts - 60, "W9", 300, ["bundler"])]
        with mock.patch.object(scan, "_fetch_bundle",
                               side_effect=lambda m, **kw: self._bundle([])), \
                mock.patch.object(scan, "_gmgn_wallet_swaps",
                                  return_value=(swaps, True)) as fetch, \
                mock.patch.object(scan.screen, "detect_sweep",
                                  return_value={"ts": candle_ts}), \
                mock.patch.object(scan.screen, "sweep_context", return_value=context):
            scan.run_scan(["M"], state=state, use_cache=False, send_alerts=False,
                          workers=1, now=NOW)
        fetch.assert_any_call("M", candle_ts - wallets.WINDOW_SEC, candle_ts)
        sweep = [s for s in state["signals"] if s.get("kind") == "sweep"][0]
        self.assertEqual(sweep["wallet_pre"]["window_sec"], wallets.WINDOW_SEC)
        self.assertIs(sweep["wallet_pre"]["complete"], True)
        self.assertEqual(sweep["wallet_pre"]["features"]["bundler_buy_wallets"], 1)
        self.assertEqual(sweep["wallet_pre"]["features"]["top_buy_wallet_usd"], 300.0)
        kinds = [r["kind"] for r in state["wallet_flow"]["M"]]
        self.assertIn("sweep", kinds)


if __name__ == "__main__":
    unittest.main()
