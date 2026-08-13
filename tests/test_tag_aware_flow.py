# -*- coding: utf-8 -*-
"""Offline tests for tag-aware flow weighting (smart money / bundler /
top holder / fresh wallet points for the CVD filter)."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import (TAG_FLOW_FLOOR, wallet_profiles,
                 tag_wallet_meta_tags, tag_wallets,
                 wallet_tag_points, tagged_flow_report)


def _swap(side, sol, ts, wallet):
    return (side, sol, ts, wallet)


def test_tag_wallet_meta_tags_detection():
    """maker_tags fragments map to smart / bundler / fresh tag names."""
    assert tag_wallet_meta_tags({"maker_tags": ["Smart Money", "Diamond"]}) \
        == ["smart_money"]
    assert tag_wallet_meta_tags({"maker_tags": ["Bundler  #1"]}) \
        == ["bundler"]
    assert tag_wallet_meta_tags({"maker_tags": ["Fresh Wallet"]}) \
        == ["fresh_wallet"]
    # multiple tags
    got = tag_wallet_meta_tags(
        {"maker_tags": ["Smart Money", "bundler", "Fresh"]})
    assert got == ["smart_money", "bundler", "fresh_wallet"]
    # no tags / empty meta
    assert tag_wallet_meta_tags({}) == []
    assert tag_wallet_meta_tags(None) == []
    print("  ok   tag_wallet_meta_tags detection")


def test_tag_wallets_top_holder_and_age():
    """top_holder_ranks and wallet_ages add tags deterministically."""
    profiles = {"W1": {"buy": 5.0}, "W2": {"buy": 5.0},
                "W3": {"buy": 5.0}}
    now = time.time()
    tags = tag_wallets(
        profiles,
        wallet_meta={"W1": {"maker_tags": ["Smart Money"]}},
        top_holder_ranks={"W2": 3},
        wallet_ages={"W3": [None, now - 3600]},  # 1h old -> fresh
        fresh_days=7.0)
    assert "smart_money" in tags["W1"]["tags"]
    assert tags["W2"]["top_rank"] == 3 and "top_holder" in tags["W2"]["tags"]
    assert "fresh_wallet" in tags["W3"]["tags"]
    # old wallet is not fresh
    tags_old = tag_wallets(
        profiles, wallet_ages={"W1": now - 30 * 86400}, fresh_days=7.0)
    assert "fresh_wallet" not in tags_old["W1"]["tags"]
    assert tags_old["W1"]["age_days"] > 7.0
    print("  ok   tag_wallets top holder + fresh age")


def test_wallet_tag_points_and_cap():
    """Sum per-tag points, capped per wallet."""
    assert wallet_tag_points(["smart_money", "top_holder"], side="accum") \
        == 30 + 25
    assert wallet_tag_points(["bundler"], side="accum") == -25
    assert wallet_tag_points(["bundler"], side="dist") == 35
    # many tags capped at 60
    big = wallet_tag_points(["smart_money", "top_holder", "fresh_wallet"],
                            side="accum")
    assert big == 60.0
    print("  ok   wallet_tag_points + cap")


def test_tagged_flow_trusted_accumulation():
    """A smart-money pure accumulator lifts tag_score and trusted share."""
    now = int(time.time())
    swaps = [
        _swap("buy", 5.0, now - 3600, "W1"),   # smart accumulator
        _swap("buy", 2.0, now - 7200, "W2"),   # anonymous accumulator
    ]
    report = tagged_flow_report(
        swaps,
        wallet_meta={"W1": {"maker_tags": ["Smart Money"]}},
        min_buy_sol=0.1, sell_tol=0.10)
    assert report["ok"] is True
    assert report["n_accum"] == 2
    assert report["tagged_accum_points"] >= 30
    assert report["trusted_accum_wallets"] == 1
    assert report["smart_accum_buy_sol"] > 5.0   # boosted by 1.6x weight
    assert report["trusted_accum_share"] > 0.5
    assert report["tag_score"] > 50.0
    print("  ok   trusted smart-money accumulation scored")


def test_tagged_flow_bundler_distribution():
    """A bundler dumping is boosted and drags tag_score down."""
    now = int(time.time())
    swaps = [
        _swap("sell", 5.0, now - 3600, "B1"),   # bundler distributor
        _swap("sell", 2.0, now - 7200, "B2"),   # anonymous distributor
    ]
    report = tagged_flow_report(
        swaps, wallet_meta={"B1": {"maker_tags": ["Bundler"]}},
        min_sell_sol=0.1, buy_tol=0.10)
    assert report["ok"] is True
    assert report["n_dist"] == 2
    assert report["tagged_dist_points"] >= 35
    assert report["bundler_dist_sell_sol"] > 5.0  # boosted
    assert report["tag_score"] < 50.0
    print("  ok   bundler distribution penalised")


def test_tagged_flow_untagged_is_neutral():
    """No tags -> zero points and a neutral 50 tag_score."""
    now = int(time.time())
    swaps = [_swap("buy", 3.0, now - 3600, "A")]
    report = tagged_flow_report(swaps, min_buy_sol=0.1, sell_tol=0.10)
    assert report["n_accum"] == 1
    assert report["tagged_accum_points"] == 0.0
    assert report["tagged_dist_points"] == 0.0
    assert report["tag_score"] == 50.0
    assert report["smart_accum_buy_sol"] == 0.0
    print("  ok   untagged flow is neutral")


def test_tagged_flow_empty():
    """No swaps -> ok False, neutral score, no crash."""
    report = tagged_flow_report([])
    assert report["ok"] is False
    assert report["tag_score"] == 50.0
    assert report["n_accum"] == 0 and report["n_dist"] == 0
    print("  ok   empty window handled")


def test_eff_multiplier_floor():
    """Effective volume never drops below the floor, even for bundlers."""
    now = int(time.time())
    swaps = [_swap("buy", 3.0, now - 3600, "B1")]
    report = tagged_flow_report(
        swaps, wallet_meta={"B1": {"maker_tags": ["Bundler"]}},
        min_buy_sol=0.1, sell_tol=0.10)
    row = report["accum_rows"][0]
    assert row["eff_buy"] >= 3.0 * TAG_FLOW_FLOOR - 1e-9
    assert row["eff_buy"] < 3.0  # bundler accumulation discounted
    print("  ok   effective multiplier floor respected")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"- {name}")
            fn()
    print("\nALL PASS")
