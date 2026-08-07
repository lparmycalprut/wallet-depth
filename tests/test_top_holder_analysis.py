# -*- coding: utf-8 -*-
"""Offline tests for the CVD Top 100 holder analysis."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import top_holder_analysis


def swap(side, sol, ts, wallet):
    return (side, sol, ts, wallet)


def test_diamond_hand_boundary_and_real_dust():
    holders = [
        {"owner": "A", "amount": 100},
        {"owner": "B", "amount": 20},
        {"owner": "C", "amount": 5},
    ]
    swaps = [
        swap("buy", 10, 1, "A"),
        swap("sell", 1, 2, "A"),       # exactly 10%: qualifies
        swap("buy", 10, 1, "B"),
        swap("sell", 2, 2, "B"),       # 20%: does not qualify
    ]
    result = top_holder_analysis(
        holders, swaps, price_usd=0.10, dust_limit_usd=5, supply=200
    )
    assert result["n_top"] == 3
    assert result["diamond_hands"] == 2  # A + C (no sell observed)
    assert abs(result["diamond_pct"] - 100 * 2 / 3) < 1e-9
    assert result["observed_wallets"] == 2
    assert result["observed_diamond_hands"] == 1
    assert result["real_holders"] == 1  # A = $10, B = $2, C = $0.50
    assert abs(result["top_supply_pct"] - 62.5) < 1e-9
    assert result["rows"][0]["sell_pct"] == 10.0
    assert result["rows"][0]["real_holder"] is True
    assert result["rows"][1]["diamond_hand"] is False
    print("  ok   diamond boundary + real/dust counts")


def test_top_limit_sort_and_duplicate_owner():
    holders = [("low", 1), ("high", 10), ("high", 5)]
    result = top_holder_analysis(
        holders, [], price_usd=1, dust_limit_usd=2, supply=20, limit=1
    )
    assert result["n_top"] == 1
    assert result["rows"][0]["wallet"] == "high"
    # Duplicate account rows are aggregated before rank limiting.
    assert result["rows"][0]["amount"] == 15
    assert result["real_holders"] == 1
    print("  ok   top limit + owner aggregation")


def test_empty_inputs_are_safe():
    result = top_holder_analysis([], [], price_usd=1, dust_limit_usd=5)
    assert result["rows"] == []
    assert result["n_top"] == 0
    assert result["diamond_pct"] == 0.0
    assert result["real_pct"] == 0.0
    print("  ok   empty top-holder input")


if __name__ == "__main__":
    test_diamond_hand_boundary_and_real_dust()
    test_top_limit_sort_and_duplicate_owner()
    test_empty_inputs_are_safe()
    print("\nALL PASSED")
