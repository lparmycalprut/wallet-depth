# -*- coding: utf-8 -*-
"""Offline tests for the M15 activity flag and fund-source (funder) analysis.

No network: funder_wallet_analysis is exercised with stubbed core helpers
(helius_api_get / helius_rpc), everything else is pure.

Run: python tests/test_m15_and_funder.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import (m15_activity_flag, _parse_funder_transfers,
                 exchange_wallet_labels, is_exchange_wallet,
                 funder_wallet_analysis)


def swap(side, sol, ts, wallet):
    return (side, sol, ts, wallet)


def test_m15_empty_and_small():
    r = m15_activity_flag([])
    assert r["hit"] is False
    assert r["best_tx"] == 0 and r["best_vol_sol"] == 0.0
    assert r["candles"] == 0
    # one small candle, far below thresholds (same 900s bucket)
    swaps = [swap("buy", 1.0, 1_700_000_000, "A"),
             swap("sell", 0.5, 1_700_000_050, "B")]
    r = m15_activity_flag(swaps)
    assert r["hit"] is False
    assert r["best_tx"] == 2 and r["candles"] == 1
    assert r["total_tx"] == 2
    print("  ok   empty + small sample")


def test_m15_bucket_alignment():
    """Swaps are bucketed into 15-minute candles (ts // 900)."""
    base = 1_700_000_000
    start = base - base % 900  # candle open ts
    swaps = [swap("buy", 1.0, start + 10, "A"),
             swap("buy", 2.0, start + 800, "B"),   # same candle
             swap("buy", 3.0, start + 901, "C")]   # next candle
    r = m15_activity_flag(swaps)
    assert r["candles"] == 2
    assert r["best_tx"] == 2
    assert r["best_vol_sol"] == 3.0
    assert r["best_start_ts"] == start
    print("  ok   15-minute bucket alignment")


def test_m15_hit_requires_both_thresholds_strict():
    """>500 tx AND >500 SOL in a single candle; thresholds are strict."""
    base = 900 * 1_888_888  # 1_699_999_200 — aligned to a 900s boundary
    # 501 tx but only ~0.5 SOL each -> vol ~250 SOL -> NOT a hit
    # (1-second spacing keeps all swaps inside one 900s candle)
    swaps = [swap("buy", 0.5, base + i, f"w{i}") for i in range(501)]
    r = m15_activity_flag(swaps)
    assert r["best_tx"] == 501
    assert r["hit"] is False, "vol below threshold must not hit"

    # 501 tx * 1.1 SOL -> vol 551.1 SOL -> hit
    swaps = [swap("buy", 1.1, base + i, f"w{i}") for i in range(501)]
    r = m15_activity_flag(swaps)
    assert r["hit"] is True, r

    # exactly 500 tx -> strict >, not a hit even with big volume
    swaps = [swap("buy", 5.0, base + i, f"w{i}") for i in range(500)]
    r = m15_activity_flag(swaps)
    assert r["best_tx"] == 500 and r["best_vol_sol"] == 2500.0
    assert r["hit"] is False, "exactly 500 tx must NOT hit (>500)"
    print("  ok   strict >500 tx and >500 SOL")


def test_m15_custom_thresholds():
    base = 1_700_000_000
    swaps = [swap("buy", 2.0, base + i, f"w{i}") for i in range(10)]
    r = m15_activity_flag(swaps, min_tx=5, min_vol_sol=15.0)
    assert r["hit"] is True
    r = m15_activity_flag(swaps, min_tx=5, min_vol_sol=25.0)
    assert r["hit"] is False
    print("  ok   custom thresholds")


def test_parse_funder_transfers():
    txs = [
        {"signature": "s1",
         "nativeTransfers": [
             {"fromUserAccount": "FUNDER1", "toUserAccount": "HOLDER",
              "amount": 1_500_000_000},          # 1.5 SOL
             {"fromUserAccount": "HOLDER", "toUserAccount": "POOL",
              "amount": 2_000_000_000},          # out — ignored
         ]},
        {"signature": "s2",
         "nativeTransfers": [
             {"fromUserAccount": "FUNDER2", "toUserAccount": "HOLDER",
              "amount": 500_000_000},            # 0.5 SOL
         ]},
        {"signature": "s3",
         "nativeTransfers": [
             {"fromUserAccount": "HOLDER", "toUserAccount": "HOLDER",
              "amount": 999_000_000},            # self — ignored
         ]},
        {"signature": "s4",
         "nativeTransfers": [
             {"fromUserAccount": "FUNDER3", "toUserAccount": "OTHER",
              "amount": 999_000_000},            # wrong recipient — ignored
         ]},
    ]
    out = _parse_funder_transfers(txs, "HOLDER")
    assert ("FUNDER1", 1.5) in out
    assert ("FUNDER2", 0.5) in out
    assert len(out) == 2, out
    # empty / malformed safe
    assert _parse_funder_transfers([], "H") == []
    assert _parse_funder_transfers([None, {"nativeTransfers": None}], "H") == []
    print("  ok   funder transfer parsing")


def test_exchange_wallet_labels_and_exclusion():
    labels = exchange_wallet_labels()
    assert "3j98t1wpez73cnmqviecrnyiwrnqrhwnly" in labels  # Binance 8
    assert "Binance 8" in labels.values()
    assert is_exchange_wallet("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
    assert is_exchange_wallet("3j98t1wpez73cnmqviecrnyiwrnqrhwnly")  # case
    assert not is_exchange_wallet("FUNDER1")
    # extra config addresses are merged
    extra = ["FUNDER1", "FUNDER2"]
    assert is_exchange_wallet("FUNDER1", extra)
    assert is_exchange_wallet("funder2", extra)
    assert not is_exchange_wallet("FUNDER3", extra)
    print("  ok   exchange labels / exclusion")


def _stub_core():
    """Patch core.helius_api_get / helius_rpc with in-memory fakes."""
    import core
    orig_get, orig_rpc = core.helius_api_get, core.helius_rpc
    balances = {}
    tx_by_holder = {}

    def fake_api_get(url, *, params=None, headers=None, helius_keys=None,
                     timeout=40, max_attempts=None):
        # .../v0/addresses/{HOLDER}/transactions -> second-to-last segment
        holder = url.rstrip("/").rsplit("/", 2)[-2]
        return tx_by_holder.get(holder, [])

    def fake_rpc(method, params, helius_keys=None, *, timeout=60,
                 max_attempts=None):
        if method == "getBalance":
            return {"value": int(balances.get(params[0], 0) * 1e9)}
        raise AssertionError(f"unexpected rpc method {method}")

    core.helius_api_get = fake_api_get
    core.helius_rpc = fake_rpc
    return orig_get, orig_rpc, tx_by_holder, balances


def test_funder_wallet_analysis_ranking_and_exclusion():
    import core
    orig_get, orig_rpc, tx_by_holder, balances = _stub_core()
    try:
        holders = [["HOLDER_A", 100.0], ["HOLDER_B", 90.0],
                   ["HOLDER_C", 80.0]]
        # HOLDER_A funded by FUNDER_BIG (50 SOL balance) and EXCHANGE
        # HOLDER_B funded by FUNDER_BIG too
        tx_by_holder["HOLDER_A"] = [{
            "nativeTransfers": [
                {"fromUserAccount": "FUNDER_BIG", "toUserAccount": "HOLDER_A",
                 "amount": int(2.0 * 1e9)},
                {"fromUserAccount": "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
                 "toUserAccount": "HOLDER_A", "amount": int(5.0 * 1e9)},
            ]}]
        tx_by_holder["HOLDER_B"] = [{
            "nativeTransfers": [
                {"fromUserAccount": "FUNDER_BIG", "toUserAccount": "HOLDER_B",
                 "amount": int(1.5 * 1e9)},
            ]}]
        tx_by_holder["HOLDER_C"] = [{
            "nativeTransfers": [
                {"fromUserAccount": "FUNDER_SMALL",
                 "toUserAccount": "HOLDER_C", "amount": int(0.2 * 1e9)},
            ]}]
        balances.clear()  # mutate the dict the stub closure captured
        balances.update({"FUNDER_BIG": 500.0, "FUNDER_SMALL": 2.0})

        res = funder_wallet_analysis(
            holders, helius_keys=("k1",), top_n=100, max_tx_per_holder=20,
            min_fund_sol=0.1, exclude_exchanges=True, max_funders=40,
            exclude_addresses=("POOL",))
        assert res["ok"] is True, res
        rows = res["rows"]
        # exchange wallet excluded from rows
        assert all(r["address"] != "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
                   for r in rows)
        # sorted by SOL balance descending (bigger is better)
        assert [r["sol_balance"] for r in rows] == \
            sorted((r["sol_balance"] for r in rows), reverse=True)
        assert rows[0]["address"] == "FUNDER_BIG"
        assert rows[0]["sol_balance"] == 500.0
        assert rows[0]["funded_sol"] == 3.5
        assert rows[0]["n_holders"] == 2
        assert res["holders_scanned"] == 3
        print("  ok   funder ranking, exchange exclusion, sorting")
    finally:
        core.helius_api_get, core.helius_rpc = orig_get, orig_rpc


def test_funder_wallet_analysis_no_keys_and_empty():
    import core
    orig_get, orig_rpc, tx_by_holder, balances = _stub_core()
    try:
        res = funder_wallet_analysis([["H", 1.0]], helius_keys=())
        assert res["ok"] is False and "Helius" in res["error"]
        res = funder_wallet_analysis([], helius_keys=("k1",))
        assert res["ok"] is False
        # holder with no transfers -> no funders
        res = funder_wallet_analysis([["H", 1.0]], helius_keys=("k1",))
        assert res["ok"] is False
        assert res["holders_scanned"] == 0
        print("  ok   no-key / empty paths")
    finally:
        core.helius_api_get, core.helius_rpc = orig_get, orig_rpc


if __name__ == "__main__":
    test_m15_empty_and_small()
    test_m15_bucket_alignment()
    test_m15_hit_requires_both_thresholds_strict()
    test_m15_custom_thresholds()
    test_parse_funder_transfers()
    test_exchange_wallet_labels_and_exclusion()
    test_funder_wallet_analysis_ranking_and_exclusion()
    test_funder_wallet_analysis_no_keys_and_empty()
    print("\nALL PASSED")
