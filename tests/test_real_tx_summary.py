# -*- coding: utf-8 -*-
"""Tests for cvd.real_tx_summary (LP/Degen Radar "Rangkuman TX real").

Covers:
  * per-window counting with an explicit now_ts (deterministic)
  * USD-value threshold (SOL × sol_price >= dust_limit_usd)
  * net SOL sign (buy + / sell −)
  * boundary: a swap exactly at the threshold counts as real
  * empty / malformed input never crashes and yields safe zeros
  * coverage span (covered_h) so the UI can tell quiet from empty

Run with:  python tests/test_real_tx_summary.py  (no pytest, no network)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cvd  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


T0 = 1_760_000_000  # fixed base ts so tests are deterministic
WINDOWS = (6, 12, 24, 48)


def _swap(side, sol, hours_ago, wallet="wallet-x"):
    return (side, sol, T0 - hours_ago * 3600, wallet)


def test_basic_windows():
    print("\n[windows] per-window count + net SOL")
    swaps = [
        _swap("buy", 1.0, 1),          # in 6h
        _swap("sell", 2.0, 5),         # in 6h
        _swap("buy", 0.5, 10),         # in 12h
        _swap("sell", 3.0, 30),        # in 48h only
    ]
    s = cvd.real_tx_summary(swaps, dust_limit_usd=5.0, sol_price=100.0,
                            windows=WINDOWS, now_ts=T0)
    # 100 * 0.5 = $50 >= $5, so every swap is "real".
    check(s[6] == {"tx": 2, "net_sol": -1.0, "total_tx": 2},
          f"6h: 2 real, net -1.0 (got {s[6]})")
    check(s[12] == {"tx": 3, "net_sol": -0.5, "total_tx": 3},
          f"12h: 3 real, net -0.5 (got {s[12]})")
    check(s[24] == {"tx": 3, "net_sol": -0.5, "total_tx": 3},
          f"24h: 30h-old swap excluded (got {s[24]})")
    check(s[48] == {"tx": 4, "net_sol": -3.5, "total_tx": 4},
          f"48h: all 4, net -3.5 (got {s[48]})")
    check(abs(s["covered_h"] - 29.0) < 1e-6,
          f"covered_h = oldest→newest span 29h (got {s['covered_h']})")


def test_threshold_filters_dust():
    print("\n[threshold] swaps below dust_limit are not 'real'")
    swaps = [
        _swap("buy", 0.5, 1),     # $50  -> real at $5
        _swap("buy", 0.04, 2),    # $4   -> dust
        _swap("sell", 0.01, 3),   # $1   -> dust
    ]
    s = cvd.real_tx_summary(swaps, dust_limit_usd=5.0, sol_price=100.0,
                            windows=(6,), now_ts=T0)
    check(s[6]["tx"] == 1, f"only the $50 swap counts (got {s[6]})")
    check(s[6]["total_tx"] == 3, "all 3 swaps still counted as total")
    check(abs(s[6]["net_sol"] - 0.5) < 1e-9,
          "net only sums real swaps (+0.5)")

    # Higher threshold: the $50 swap still qualifies, $4 + $1 stay dust.
    s50 = cvd.real_tx_summary(swaps, dust_limit_usd=10.0, sol_price=100.0,
                              windows=(6,), now_ts=T0)
    check(s50[6]["tx"] == 1, "threshold $10 → only the $50 swap qualifies")
    check(abs(s50[6]["net_sol"] - 0.5) < 1e-9, "net stays +0.5")
    check(s50[6]["total_tx"] == 3, "total stays 3 regardless")


def test_boundary_exact():
    print("\n[boundary] swap exactly at dust_limit is real (>=)")
    # 0.05 SOL × $100 = exactly $5
    s = cvd.real_tx_summary([_swap("buy", 0.05, 1)],
                            dust_limit_usd=5.0, sol_price=100.0,
                            windows=(6,), now_ts=T0)
    check(s[6]["tx"] == 1, "exact $5 swap counts as real")
    s2 = cvd.real_tx_summary([_swap("buy", 0.0499, 1)],
                             dust_limit_usd=5.0, sol_price=100.0,
                             windows=(6,), now_ts=T0)
    check(s2[6]["tx"] == 0, "$4.99 swap stays dust")


def test_sol_price_zero():
    print("\n[price=0] no USD value → nothing real, totals still counted")
    s = cvd.real_tx_summary([_swap("buy", 10.0, 1), _swap("sell", 2.0, 2)],
                            dust_limit_usd=5.0, sol_price=0.0,
                            windows=(6,), now_ts=T0)
    check(s[6]["tx"] == 0, "sol_price 0 → no real swaps")
    check(s[6]["total_tx"] == 2, "totals counted regardless")
    check(abs(s[6]["net_sol"]) < 1e-9, "net stays 0 (no real swaps)")


def test_empty_and_malformed():
    print("\n[robust] empty list + malformed rows never crash")
    s = cvd.real_tx_summary([], dust_limit_usd=5.0, sol_price=100.0,
                            windows=WINDOWS, now_ts=T0)
    for h in WINDOWS:
        check(s[h] == {"tx": 0, "net_sol": 0.0, "total_tx": 0},
              f"empty → safe zeros for {h}h (got {s[h]})")
    check(s["covered_h"] == 0.0, "empty → covered_h 0")

    bad = [None, ("buy",), ("buy", "x", "not-a-ts"), ("buy", "nan", 1, "w"),
           [], ("SELL", 1.5, T0 - 3600, "w")]  # mixed caps ok, junk skipped
    s2 = cvd.real_tx_summary(bad, dust_limit_usd=5.0, sol_price=100.0,
                             windows=(6,), now_ts=T0)
    check(s2[6] == {"tx": 1, "net_sol": -1.5, "total_tx": 1},
          f"malformed skipped, valid 1.5 SOL sell counted (got {s2[6]})")


def test_net_sign():
    print("\n[net] buys add, sells subtract")
    s = cvd.real_tx_summary([_swap("buy", 3.0, 1), _swap("buy", 2.0, 2),
                             _swap("sell", 4.0, 3)],
                            dust_limit_usd=5.0, sol_price=100.0,
                            windows=(6,), now_ts=T0)
    check(abs(s[6]["net_sol"] - 1.0) < 1e-9,
          f"3 + 2 − 4 = +1.0 (got {s[6]['net_sol']})")
    check(s[6]["tx"] == 3, "all three swaps qualify")


def test_custom_windows_and_caps():
    print("\n[windows] custom window list + uppercase side")
    s = cvd.real_tx_summary([_swap("BUY", 1.0, 1), _swap("sell", 2.0, 20)],
                            dust_limit_usd=5.0, sol_price=100.0,
                            windows=(6, 48), now_ts=T0)
    check(s[6] == {"tx": 1, "net_sol": 1.0, "total_tx": 1},
          f"6h sees only the buy (got {s[6]})")
    check(s[48] == {"tx": 2, "net_sol": -1.0, "total_tx": 2},
          f"48h sees both, uppercase BUY handled (got {s[48]})")


if __name__ == "__main__":
    test_basic_windows()
    test_threshold_filters_dust()
    test_boundary_exact()
    test_sol_price_zero()
    test_empty_and_malformed()
    test_net_sign()
    test_custom_windows_and_caps()
    print()
    if failures:
        print(f"{len(failures)} FAILURES:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("ALL PASSED")
