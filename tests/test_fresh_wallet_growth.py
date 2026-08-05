# -*- coding: utf-8 -*-
"""Tests for cvd.fresh_wallet_growth (fresh wallets that buy & keep >=90%).

A "fresh wallet" buys inside the window and never sells more than
``sell_tol`` (default 10%) of what it bought, AND its first-ever tx is
younger than ``max_age_days``.

Covers:
  * buy-and-hold wallets qualify, sell >10% of buy are excluded
  * old wallets (older than max_age_days) are excluded
  * sell-only wallets and non-traders are excluded
  * wallets with missing age data are counted as unknown_age
  * `[funder, first_ts]` pair age format (as the page's funder cache)
  * hourly growth series: new wallets / cumulative wallets / cumulative
    SOL bought, anchored to the window start/end
  * min_buy_sol dust filter
  * empty input edge case

Run with:  python tests/test_fresh_wallet_growth.py  (no pytest, no network)
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


NOW = 1_800_000_000          # fixed reference "now"
WINDOW_H = 12                # analysis window length in hours
T0 = NOW - WINDOW_H * 3600   # window start


def make_swaps():
    """(side, sol, ts, wallet) fixture.

    fresh1    : 1.5 + 0.5 SOL bought, nothing sold  -> pure_accum, fresh
    fresh2    : 5.0 SOL bought, 0.4 sold (8%)       -> light_holder, fresh
    over_sold : 3.0 SOL bought, 1.0 sold (>10%)     -> excluded
    old_wallet: 4.0 SOL bought, 0.2 sold (≤10%) but 60 days old -> excluded
    seller_only: sells without buying               -> excluded
    no_age    : 2.0 SOL bought, no age data         -> unknown_age
    """
    return [
        ("buy", 1.5, T0, "fresh1"),
        ("buy", 0.5, T0 + 3600, "fresh1"),
        ("buy", 5.0, T0 + 3600, "fresh2"),
        ("sell", 0.4, T0 + 7200, "fresh2"),
        ("buy", 3.0, T0 + 3600, "over_sold"),
        ("sell", 1.0, T0 + 7200, "over_sold"),
        ("buy", 4.0, T0 + 1800, "old_wallet"),
        ("sell", 0.2, T0 + 7200, "old_wallet"),
        ("sell", 1.0, T0 + 3600, "seller_only"),
        ("buy", 2.0, T0 + 5400, "no_age"),
    ]


AGES = {
    "fresh1": [None, NOW - 2 * 86400],      # [funder, first_ts] pair style
    "fresh2": [None, NOW - 5 * 86400],
    "over_sold": [None, NOW - 1 * 86400],
    "old_wallet": [None, NOW - 60 * 86400],
    "seller_only": [None, NOW - 3 * 86400],
    # "no_age" intentionally absent
}


def run():
    swaps = make_swaps()
    profiles = cvd.wallet_profiles(swaps)

    res = cvd.fresh_wallet_growth(
        swaps, profiles, AGES, max_age_days=7.0, sell_tol=0.10,
        start_ts=T0, end_ts=NOW, bucket_s=3600)

    wallets = [w for w, _d, _a, _fb in res["wallets"]]
    check(res["count"] == 2,
          f"count == 2 (got {res['count']}: {wallets})")
    check("fresh1" in wallets and "fresh2" in wallets,
          "fresh1 & fresh2 qualify")
    check("over_sold" not in wallets, "over_sold excluded (sold >10%)")
    check("old_wallet" not in wallets, "old_wallet excluded (60 days old)")
    check("seller_only" not in wallets, "seller_only excluded (no buy)")
    check("no_age" not in wallets, "no_age excluded (unknown age)")
    check(res["unknown_age"] == 1, f"unknown_age == 1 (got {res['unknown_age']})")

    check(abs(res["total_buy"] - 7.0) < 1e-9,
          f"total_buy == 7.0 (got {res['total_buy']})")
    check(abs(res["total_sell"] - 0.4) < 1e-9,
          f"total_sell == 0.4 (got {res['total_sell']})")
    check(abs(res["net_hold"] - 6.6) < 1e-9,
          f"net_hold == 6.6 (got {res['net_hold']})")
    check(res["n_zero_sell"] == 1, f"n_zero_sell == 1 (got {res['n_zero_sell']})")
    check(res["n_pure_accum"] == 1 and res["n_light_holder"] == 1,
          f"pure_accum/light_holder split (got {res['n_pure_accum']}/"
          f"{res['n_light_holder']})")
    check(res["whale_count"] == 1 and res["dolphin_count"] == 1,
          f"whale/dolphin split (got {res['whale_count']}/{res['dolphin_count']})")

    # Sorted by total buy descending: fresh2 (5.0) before fresh1 (2.0).
    check(wallets == ["fresh2", "fresh1"], f"wallets sorted by buy (got {wallets})")
    # age_days in the wallet tuples.
    ages_map = {w: a for w, _d, a, _fb in res["wallets"]}
    check(abs(ages_map["fresh1"] - 2.0) < 0.01 and
          abs(ages_map["fresh2"] - 5.0) < 0.01,
          f"age_days recorded (got {ages_map})")

    # Growth series: 13 hourly buckets, monotone cumulatives.
    s = res["series"]
    check(len(s) == WINDOW_H + 1, f"series has {WINDOW_H + 1} buckets (got {len(s)})")
    check(s[0]["bucket_ts"] == T0, "series starts at window start")
    check(s[-1]["cum_wallets"] == 2 and abs(s[-1]["cum_buy_sol"] - 7.0) < 1e-9,
          f"final cumulatives 2 / 7.0 (got {s[-1]['cum_wallets']} / "
          f"{s[-1]['cum_buy_sol']})")
    new_in_first = s[0]["new_wallets"] + s[1]["new_wallets"]
    check(new_in_first == 2, f"2 wallets appear within first 2 buckets (got {new_in_first})")
    cums = [r["cum_wallets"] for r in s]
    check(cums == sorted(cums) and cums[-1] == 2,
          "cum_wallets monotone and ends at 2")

    # min_buy_sol dust filter: only fresh2 (5.0) clears 4.0 SOL.
    res2 = cvd.fresh_wallet_growth(
        swaps, profiles, AGES, max_age_days=7.0, sell_tol=0.10,
        min_buy_sol=4.0, start_ts=T0, end_ts=NOW, bucket_s=3600)
    check(res2["count"] == 1 and res2["wallets"][0][0] == "fresh2",
          f"min_buy_sol=4.0 keeps only fresh2 (got {[w for w, *_ in res2['wallets']]})")

    # Bare int age values are accepted too.
    res3 = cvd.fresh_wallet_growth(
        swaps, profiles, {w: ft for w, (f, ft) in AGES.items()},
        max_age_days=7.0, sell_tol=0.10,
        start_ts=T0, end_ts=NOW, bucket_s=3600)
    check(res3["count"] == 2, f"bare int ages work (got {res3['count']})")

    # Empty input edge case.
    res4 = cvd.fresh_wallet_growth([], {}, {})
    check(res4["count"] == 0 and res4["series"] == [] and
          res4["total_buy"] == 0.0, "empty swaps -> empty result")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        sys.exit(1)
    print("All fresh_wallet_growth checks passed.")


if __name__ == "__main__":
    run()
