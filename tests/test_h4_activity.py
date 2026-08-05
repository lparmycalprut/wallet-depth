# -*- coding: utf-8 -*-
"""Tests for cvd.h4_activity_series (grafik TX & volume per 4 jam).

Covers:
  * fixed 4h bucketing aligned to the epoch, zero-filled, oldest->newest
  * growth measured on the last two *closed* bins (current bin ignored)
  * >=5x spike warning (up) and <=1/5 collapse warning (down)
  * micro-noise (1 tx -> 4 tx) never warns
  * zero -> something is flagged as an infinite spike
  * dust filter (SOL x price < limit dropped)
  * empty / malformed input never crashes

Run with:  python tests/test_h4_activity.py  (no pytest, no network)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cvd  # noqa: E402

failures = []
STEP = 14400
NOW = 1_700_000_000 // STEP * STEP + 600   # 10 min into the current bin
CUR = NOW // STEP * STEP


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def sw(side, sol, ts, w="w1"):
    return (side, sol, ts, w)


def test_bucketing():
    print("test_bucketing")
    swaps = [sw("buy", 1.0, CUR - STEP * 2 + 60),
             sw("sell", 2.0, CUR - STEP * 2 + 120),
             sw("buy", 3.0, CUR - STEP + 60)]
    r = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW)
    b = r["bins"]
    check(len(b) == 6, f"6 bins returned (got {len(b)})")
    check(b[-1]["ts"] == CUR, "last bin is the current one")
    check([x["ts"] for x in b] == sorted(x["ts"] for x in b),
          "bins ordered oldest -> newest")
    check(b[-3]["tx"] == 2 and abs(b[-3]["vol"] - 3.0) < 1e-9,
          f"prev-closed bin: 2 tx / 3 SOL (got {b[-3]})")
    check(abs(b[-3]["buy"] - 1.0) < 1e-9 and abs(b[-3]["sell"] - 2.0) < 1e-9,
          "buy/sell split recorded")
    check(b[-2]["tx"] == 1, "last closed bin: 1 tx")
    check(b[-1]["tx"] == 0, "current bin empty here")
    check(b[0]["tx"] == 0 and b[0]["vol"] == 0.0, "old bins zero-filled")


def test_uses_closed_bins_only():
    print("test_uses_closed_bins_only")
    # heavy activity in the still-filling current bin must not drive growth
    swaps = ([sw("buy", 1.0, CUR + 10)] * 50
             + [sw("buy", 1.0, CUR - STEP + 10)] * 10
             + [sw("buy", 1.0, CUR - STEP * 2 + 10)] * 10)
    r = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW)
    check(r["cur"]["ts"] == CUR - STEP, "cur = last closed bin")
    check(r["prev"]["ts"] == CUR - STEP * 2, "prev = bin before that")
    check(r["d_tx_pct"] == 0.0, f"flat growth (got {r['d_tx_pct']})")
    check(r["dir"] == "flat", f"dir flat (got {r['dir']})")
    check(r["warnings"] == [], "no warning from the filling bin")


def test_spike_up_warning():
    print("test_spike_up_warning")
    swaps = ([sw("buy", 1.0, CUR - STEP * 2 + 10)] * 4
             + [sw("buy", 1.0, CUR - STEP + 10)] * 40)
    r = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW)
    check(abs(r["tx_mult"] - 10.0) < 1e-9, f"tx_mult 10x (got {r['tx_mult']})")
    kinds = {w["kind"]: w for w in r["warnings"]}
    check("tx" in kinds and kinds["tx"]["dir"] == "up", "tx spike-up warning")
    check("vol" in kinds and kinds["vol"]["dir"] == "up",
          "vol spike-up warning")
    check(r["dir"] == "up", "direction up")


def test_collapse_warning():
    print("test_collapse_warning")
    swaps = ([sw("sell", 1.0, CUR - STEP * 2 + 10)] * 50
             + [sw("sell", 1.0, CUR - STEP + 10)] * 5)
    r = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW)
    kinds = {w["kind"]: w for w in r["warnings"]}
    check("tx" in kinds and kinds["tx"]["dir"] == "down",
          f"tx collapse warning (got {r['warnings']})")
    check(abs(kinds["tx"]["mult"] - 10.0) < 1e-9,
          f"reported as 10x drop (got {kinds['tx']['mult']})")
    check(r["dir"] == "down", "direction down")


def test_no_warning_below_threshold():
    print("test_no_warning_below_threshold")
    swaps = ([sw("buy", 1.0, CUR - STEP * 2 + 10)] * 10
             + [sw("buy", 1.0, CUR - STEP + 10)] * 30)   # 3x only
    r = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW)
    check(r["warnings"] == [], f"3x does not warn (got {r['warnings']})")


def test_micro_noise_ignored():
    print("test_micro_noise_ignored")
    swaps = [sw("buy", 0.01, CUR - STEP * 2 + 10),
             sw("buy", 0.01, CUR - STEP + 10),
             sw("buy", 0.01, CUR - STEP + 20),
             sw("buy", 0.01, CUR - STEP + 30),
             sw("buy", 0.01, CUR - STEP + 40)]   # 1 -> 4 tx, tiny volume
    r = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW)
    check(r["warnings"] == [], f"micro noise silent (got {r['warnings']})")


def test_zero_to_something():
    print("test_zero_to_something")
    swaps = [sw("buy", 2.0, CUR - STEP + 10)] * 8   # prev bin empty
    r = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW)
    check(r["tx_mult"] == float("inf"), "0 -> 8 tx is an infinite mult")
    check(any(w["kind"] == "tx" and w["dir"] == "up"
              for w in r["warnings"]), "zero-base spike warns")


def test_dust_filter():
    print("test_dust_filter")
    swaps = ([sw("buy", 0.001, CUR - STEP + 10)] * 20
             + [sw("buy", 1.0, CUR - STEP + 20)] * 3)
    r = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW,
                               dust_limit_usd=5.0, sol_price=200.0)
    check(r["cur"]["tx"] == 3,
          f"only >=$5 swaps counted (got {r['cur']['tx']})")
    r2 = cvd.h4_activity_series(swaps, bins=6, now_ts=NOW)
    check(r2["cur"]["tx"] == 23, "no filter when limit/price absent")


def test_empty_and_malformed():
    print("test_empty_and_malformed")
    r = cvd.h4_activity_series([], bins=6, now_ts=NOW)
    check(len(r["bins"]) == 6 and all(b["tx"] == 0 for b in r["bins"]),
          "empty input -> zero-filled bins")
    check(r["warnings"] == [] and r["dir"] == "flat", "empty input is flat")
    bad = [("buy",), ("buy", "x", "y", "w"), None, ("buy", float("nan"), CUR),
           ("buy", -5.0, CUR - STEP + 5)]
    r = cvd.h4_activity_series(bad, bins=6, now_ts=NOW)
    check(all(b["tx"] == 0 for b in r["bins"]),
          f"malformed rows skipped (got {[b['tx'] for b in r['bins']]})")
    r = cvd.h4_activity_series([sw("buy", 1.0, CUR)], bins=2, now_ts=NOW)
    check(r["cur"] is None and r["warnings"] == [],
          "fewer than 3 bins -> no growth math")


if __name__ == "__main__":
    test_bucketing()
    test_uses_closed_bins_only()
    test_spike_up_warning()
    test_collapse_warning()
    test_no_warning_below_threshold()
    test_micro_noise_ignored()
    test_zero_to_something()
    test_dust_filter()
    test_empty_and_malformed()
    print()
    if failures:
        print(f"{len(failures)} FAILURES:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("ALL PASSED")
