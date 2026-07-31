# -*- coding: utf-8 -*-
"""Unit tests for wallet_profiles and conviction_split with new categories.

Run without pytest, without network — all data is synthetic.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import (PROFILE_WEIGHTS, cohort_activity_summary,
                 cohort_cvd_series, detect_cohort_divergences,
                 detect_no_buy_holders, split_wallet_profile_cohorts,
                 wallet_profiles, conviction_split)


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


def test_profile_cohort_split_and_summary():
    """UI cohort helpers split whale/dolphin/light/trader cleanly."""
    swaps = [
        _swap("buy", 5.0, 1, "WHALE_PA"),
        _swap("buy", 2.0, 1, "DOLPHIN_PA"),
        _swap("sell", 4.0, 1, "WHALE_PD"),
        _swap("sell", 2.0, 1, "DOLPHIN_PD"),
        _swap("buy", 4.0, 1, "LIGHT"),
        _swap("sell", 0.25, 2, "LIGHT"),
        _swap("buy", 4.0, 1, "TRADER"),
        _swap("sell", 1.0, 2, "TRADER"),
    ]
    profiles = wallet_profiles(swaps)
    cohorts = split_wallet_profile_cohorts(profiles, whale_min_sol=3.0)
    assert [w for w, _d, _c in cohorts["whale_accumulators"]] == ["WHALE_PA"]
    assert [w for w, _d, _c in cohorts["dolphin_accumulators"]] == ["DOLPHIN_PA"]
    assert [w for w, _d, _c in cohorts["whale_distributors"]] == ["WHALE_PD"]
    assert [w for w, _d, _c in cohorts["dolphin_distributors"]] == ["DOLPHIN_PD"]
    assert [w for w, _d, _c in cohorts["light_holders"]] == ["LIGHT"]
    assert [w for w, _d, _c in cohorts["traders"]] == ["TRADER"]

    summary = cohort_activity_summary(profiles, whale_min_sol=3.0)
    assert abs(summary["whale_buy"] - 9.0) < 1e-9
    assert abs(summary["whale_sell"] - 4.0) < 1e-9
    assert abs(summary["whale_net"] - 5.0) < 1e-9
    assert abs(summary["dolphin_buy"] - 2.0) < 1e-9
    assert abs(summary["dolphin_sell"] - 2.0) < 1e-9
    print("  ok   UI cohort split + whale/dolphin summary")


def test_cohort_cvd_series_and_divergence_filter():
    """Profile-cohort CVD detects meaningful, filtered divergences."""
    buckets = [i * 3600 for i in range(7)]
    swaps = [
        _swap("buy", 3.5, buckets[3], "WHALE_HELD"),
        _swap("buy", 2.0, buckets[4], "DOLPHIN_HELD"),
        _swap("buy", 4.0, buckets[1], "TRADER"),
        _swap("sell", 1.0, buckets[2], "TRADER"),
        _swap("sell", 3.0, buckets[4], "DIST"),
    ]
    profiles = wallet_profiles(swaps)
    data = cohort_cvd_series(swaps, profiles, buckets, whale_min_sol=3.0)
    assert data["series"]["whale_held"][-1] == 3.5
    assert data["series"]["dolphin_held"][-1] == 2.0
    assert data["series"]["trader"][-1] == 3.0
    assert data["series"]["distributor"][-1] == -3.0

    price = [10, 9, 8, 9, 10, 7.5, 9]
    divs = detect_cohort_divergences(price, data, left=1, right=1)
    labels = [d["label"] for d in divs]
    assert "Whale Held CVD" in labels
    assert any(d["type"] == "bullish" for d in divs)
    print("  ok   cohort CVD series + filtered divergence")


def test_detect_no_buy_holders_from_gmgn_meta():
    """Sell-only wallets with GMGN balance are surfaced separately."""
    swaps = [
        _swap("sell", 4.0, 1, "SELLER_HOLDING"),
        _swap("sell", 2.0, 1, "DOLPHIN_HOLDING"),
        _swap("sell", 5.0, 1, "SOLD_OUT"),
        _swap("buy", 4.0, 1, "BUYER"),
    ]
    profiles = wallet_profiles(swaps)
    meta = {
        "SELLER_HOLDING": {"balance": 123, "total_trade": 3},
        "DOLPHIN_HOLDING": {"balance": 45, "total_trade": 4},
        "SOLD_OUT": {"balance": 0, "total_trade": 9},
        "BUYER": {"balance": 50, "total_trade": 1},
    }
    rows = detect_no_buy_holders(profiles, meta, whale_min_sol=3.0)
    assert [r["wallet"] for r in rows] == ["SELLER_HOLDING", "DOLPHIN_HOLDING"]
    assert rows[0]["cohort"] == "🐋 WHALE"
    assert rows[1]["cohort"] == "🐬 DOLPHIN"
    print("  ok   no-buy GMGN holders: sell-only + balance > 0")


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
    test_profile_cohort_split_and_summary()
    test_cohort_cvd_series_and_divergence_filter()
    test_detect_no_buy_holders_from_gmgn_meta()
    print("\nALL PASSED")
