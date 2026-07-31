# -*- coding: utf-8 -*-
"""Unit tests for wallet_profiles and conviction_split with new categories.

Run without pytest, without network — all data is synthetic.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import wallet_profiles, conviction_split, PROFILE_WEIGHTS


def _swap(side, sol, ts, wallet):
    return (side, sol, ts, wallet)


def test_pure_accum():
    """Wallet that sells <= 5% of buys is pure_accum."""
    swaps = [_swap("buy", 10, 1, "W1"), _swap("sell", 0.4, 2, "W1")]
    p = wallet_profiles(swaps)
    assert p["W1"]["profile"] == "pure_accum", f"expected pure_accum, got {p['W1']['profile']}"
    print("  ok   pure_accum: sell <= 5% of buy")


def test_light_holder():
    """Wallet that sells > 5% but < 10% of buys is light_holder."""
    swaps = [_swap("buy", 10, 1, "W1"), _swap("sell", 0.7, 2, "W1")]
    p = wallet_profiles(swaps)
    assert p["W1"]["profile"] == "light_holder", f"expected light_holder, got {p['W1']['profile']}"
    print("  ok   light_holder: 5% < sell < 10% of buy")


def test_trader():
    """Wallet that sells >= 10% but <= 50% of buys is trader."""
    swaps = [_swap("buy", 10, 1, "W1"), _swap("sell", 3.0, 2, "W1")]
    p = wallet_profiles(swaps)
    assert p["W1"]["profile"] == "trader", f"expected trader, got {p['W1']['profile']}"
    print("  ok   trader: 10% <= sell <= 50% of buy")


def test_two_way():
    """Wallet that sells > 50% of buys and buys > 5% of sells is two_way."""
    swaps = [_swap("buy", 10, 1, "W1"), _swap("sell", 8, 2, "W1")]
    p = wallet_profiles(swaps)
    assert p["W1"]["profile"] == "two_way", f"expected two_way, got {p['W1']['profile']}"
    print("  ok   two_way: sell > 50% of buy, buy > 5% of sell")


def test_pure_dist():
    """Wallet that buys <= 5% of sells is pure_dist."""
    swaps = [_swap("sell", 10, 1, "W1"), _swap("buy", 0.3, 2, "W1")]
    p = wallet_profiles(swaps)
    assert p["W1"]["profile"] == "pure_dist", f"expected pure_dist, got {p['W1']['profile']}"
    print("  ok   pure_dist: buy <= 5% of sell")


def test_boundary_pure_to_light():
    """Exactly 5% sell is pure_accum (boundary)."""
    swaps = [_swap("buy", 10, 1, "W1"), _swap("sell", 0.5, 2, "W1")]
    p = wallet_profiles(swaps)
    assert p["W1"]["profile"] == "pure_accum", f"expected pure_accum at boundary, got {p['W1']['profile']}"
    print("  ok   boundary: exactly 5% sell = pure_accum")


def test_boundary_light_to_trader():
    """Exactly 10% sell is trader (boundary, >= 10%)."""
    swaps = [_swap("buy", 10, 1, "W1"), _swap("sell", 1.0, 2, "W1")]
    p = wallet_profiles(swaps)
    assert p["W1"]["profile"] == "trader", f"expected trader at boundary, got {p['W1']['profile']}"
    print("  ok   boundary: exactly 10% sell = trader")


def test_boundary_trader_to_two_way():
    """Exactly 50% sell is trader (boundary, <= 50%)."""
    swaps = [_swap("buy", 10, 1, "W1"), _swap("sell", 5.0, 2, "W1")]
    p = wallet_profiles(swaps)
    assert p["W1"]["profile"] == "trader", f"expected trader at boundary, got {p['W1']['profile']}"
    print("  ok   boundary: exactly 50% sell = trader")


def test_conviction_split_weights():
    """Conviction uses weighted volumes: pure_accum 100%, light_holder 75%, trader 30%."""
    swaps = [
        _swap("buy", 10, 1, "PA"),   # pure_accum: 10 SOL buy
        _swap("buy", 10, 1, "LH"),   # light_holder: 10 SOL buy
        _swap("sell", 0.7, 2, "LH"), # 7% sell -> light_holder
        _swap("buy", 10, 1, "TR"),   # trader: 10 SOL buy
        _swap("sell", 2.0, 2, "TR"), # 20% sell -> trader
    ]
    profiles = wallet_profiles(swaps)
    assert profiles["PA"]["profile"] == "pure_accum"
    assert profiles["LH"]["profile"] == "light_holder"
    assert profiles["TR"]["profile"] == "trader"

    conv = conviction_split(profiles, whale_min_sol=1.0)
    # effective_buy = 10*1.0 + 10*0.75 + 10*0.30 = 10 + 7.5 + 3 = 20.5
    # total_buy = 10 + 10 + 10 = 30
    # conviction = 20.5 / 30 * 100 = 68.33%
    assert abs(conv["conviction_pct"] - 68.33) < 1.0, f"expected ~68.33%, got {conv['conviction_pct']:.2f}%"
    assert conv["n_pure"] == 1
    assert conv["n_lh"] == 1
    assert conv["n_trader"] == 1
    print("  ok   conviction_split weights: pure 100%, light_holder 75%, trader 30%")


def test_profile_weights_complete():
    """Every profile has a weight in PROFILE_WEIGHTS."""
    for profile in ["pure_accum", "light_holder", "trader", "two_way", "pure_dist"]:
        assert profile in PROFILE_WEIGHTS, f"missing weight for {profile}"
    print("  ok   PROFILE_WEIGHTS has all profiles")


def test_multiple_wallets():
    """Multiple wallets of different profiles are counted correctly."""
    swaps = [
        _swap("buy", 5, 1, "PA1"),  # pure_accum
        _swap("buy", 5, 1, "PA2"),  # pure_accum
        _swap("buy", 5, 1, "LH1"),  # light_holder
        _swap("sell", 0.35, 2, "LH1"),  # 7% sell
        _swap("buy", 5, 1, "TW1"),  # two_way
        _swap("sell", 4.0, 2, "TW1"),  # 80% sell
    ]
    profiles = wallet_profiles(swaps)
    conv = conviction_split(profiles, whale_min_sol=1.0)
    assert conv["n_pure"] == 2
    assert conv["n_lh"] == 1
    assert conv["n_trader"] == 0
    print("  ok   multiple wallets counted correctly")


if __name__ == "__main__":
    test_pure_accum()
    test_light_holder()
    test_trader()
    test_two_way()
    test_pure_dist()
    test_boundary_pure_to_light()
    test_boundary_light_to_trader()
    test_boundary_trader_to_two_way()
    test_conviction_split_weights()
    test_profile_weights_complete()
    test_multiple_wallets()
    print("\nALL PASSED")
