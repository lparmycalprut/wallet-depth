# -*- coding: utf-8 -*-
"""Offline tests for the CVD Top 100 holder analysis and all-holder split."""
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
    assert result["all_holders"] == 3
    assert result["all_real_holders"] == 1
    assert result["all_dust_holders"] == 2
    assert abs(result["all_real_pct"] - 100 * 1 / 3) < 1e-9
    assert abs(result["all_dust_pct"] - 100 * 2 / 3) < 1e-9
    assert abs(result["top_supply_pct"] - 62.5) < 1e-9
    assert result["rows"][0]["sell_pct"] == 10.0
    assert result["rows"][0]["real_holder"] is True
    assert result["rows"][1]["diamond_hand"] is False
    print("  ok   diamond boundary + real/dust counts")


def test_top_100_cap_and_overall_real_dust_split():
    """Top 100 is capped at 100 wallets while all-holder metrics use all wallets."""
    # 150 holders total:
    # - Top 100 wallets: 100 tokens each ($10 @ $0.10 >= $5 -> Real)
    # - 20 wallets outside top 100: 60 tokens each ($6 @ $0.10 >= $5 -> Real outside Top 100)
    # - 30 wallets outside top 100: 10 tokens each ($1 @ $0.10 < $5 -> Dust outside Top 100)
    holders = []
    for i in range(100):
        holders.append({"owner": f"top_{i}", "amount": 100.0})
    for i in range(20):
        holders.append({"owner": f"outside_real_{i}", "amount": 60.0})
    for i in range(30):
        holders.append({"owner": f"outside_dust_{i}", "amount": 10.0})

    result = top_holder_analysis(
        holders, [], price_usd=0.10, dust_limit_usd=5.0, supply=20000.0, limit=100
    )
    # Top 100 table & metrics remain strictly capped at 100
    assert result["n_top"] == 100
    assert len(result["rows"]) == 100
    assert result["diamond_hands"] == 100
    assert result["real_holders"] == 100
    assert result["real_pct"] == 100.0

    # Full holder list metrics count all 150 holders (120 real, 30 dust)
    assert result["all_holders"] == 150
    assert result["all_real_holders"] == 120
    assert result["all_dust_holders"] == 30
    assert abs(result["all_real_pct"] - 120 / 150 * 100.0) < 1e-9
    assert abs(result["all_dust_pct"] - 30 / 150 * 100.0) < 1e-9
    print("  ok   top 100 cap + full holder list real/dust split")


def test_dust_holders_inside_and_outside_top_100():
    """Dust holders both inside and outside the Top 100 are properly counted."""
    # 120 holders total:
    # - 10 holders: 100 tokens ($10 -> Real in Top 100)
    # - 90 holders: 20 tokens ($2 -> Dust in Top 100)
    # - 20 holders outside top 100: 10 tokens ($1 -> Dust outside Top 100)
    holders = []
    for i in range(10):
        holders.append({"owner": f"whale_{i}", "amount": 100.0})
    for i in range(90):
        holders.append({"owner": f"top_dust_{i}", "amount": 20.0})
    for i in range(20):
        holders.append({"owner": f"outside_dust_{i}", "amount": 10.0})

    result = top_holder_analysis(
        holders, [], price_usd=0.10, dust_limit_usd=5.0, supply=5000.0, limit=100
    )
    assert result["n_top"] == 100
    assert result["real_holders"] == 10
    assert result["real_pct"] == 10.0

    assert result["all_holders"] == 120
    assert result["all_real_holders"] == 10
    assert result["all_dust_holders"] == 110
    assert abs(result["all_real_pct"] - 10 / 120 * 100.0) < 1e-9
    assert abs(result["all_dust_pct"] - 110 / 120 * 100.0) < 1e-9
    print("  ok   dust inside and outside top 100 counted")


def test_exact_dust_threshold_boundary_is_real():
    """A balance value exactly equal to dust_limit_usd qualifies as Real (>=)."""
    # dust_limit_usd = 5.0
    # A has 50 * $0.10 = $5.00 -> exactly equal -> Real
    # B has 49.99 * $0.10 = $4.999 -> strictly less -> Dust
    holders = [
        {"owner": "exact_boundary", "amount": 50.0},
        {"owner": "below_boundary", "amount": 49.99},
    ]
    result = top_holder_analysis(holders, [], price_usd=0.10, dust_limit_usd=5.0)
    assert result["all_holders"] == 2
    assert result["all_real_holders"] == 1
    assert result["all_dust_holders"] == 1
    assert result["rows"][0]["wallet"] == "exact_boundary"
    assert result["rows"][0]["real_holder"] is True
    assert result["rows"][1]["wallet"] == "below_boundary"
    assert result["rows"][1]["real_holder"] is False
    print("  ok   exact dust threshold boundary (>= is Real)")


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
    assert result["all_holders"] == 2
    assert result["all_real_holders"] == 1
    assert result["all_dust_holders"] == 1
    print("  ok   top limit + owner aggregation")


def test_empty_inputs_are_safe():
    result = top_holder_analysis([], [], price_usd=1, dust_limit_usd=5)
    assert result["rows"] == []
    assert result["n_top"] == 0
    assert result["diamond_pct"] == 0.0
    assert result["real_pct"] == 0.0
    assert result["all_holders"] == 0
    assert result["all_real_holders"] == 0
    assert result["all_dust_holders"] == 0
    assert result["all_real_pct"] == 0.0
    assert result["all_dust_pct"] == 0.0
    print("  ok   empty top-holder input")


if __name__ == "__main__":
    test_diamond_hand_boundary_and_real_dust()
    test_top_100_cap_and_overall_real_dust_split()
    test_dust_holders_inside_and_outside_top_100()
    test_exact_dust_threshold_boundary_is_real()
    test_top_limit_sort_and_duplicate_owner()
    test_empty_inputs_are_safe()
    print("\nALL PASSED")
