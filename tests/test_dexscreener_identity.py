# -*- coding: utf-8 -*-
"""Regression tests for DexScreener token identity selection.

The token endpoint can include a high-liquidity cross-pair where the queried
CA is the quote token.  The CVD page used to take that raw first pair and
read its base-token metadata, so MEMIPEDE was displayed as Cyclospora.

Runs without pytest and without network:
    python tests/test_dexscreener_identity.py
"""
import inspect
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import core  # noqa: E402


MEMIPEDE_CA = "6LLNiWXRZp8hn5oTFTHEo8ERbJS3QJfHSKhnTCqipump"
CYCLOSPORA_CA = "Cyclospora111111111111111111111111111111111"
SOL_CA = "So11111111111111111111111111111111111111112"
OTHER_CA = "OtherToken11111111111111111111111111111111111"


def _pair(address, base, quote, liquidity, price):
    """Small DexScreener pair fixture with only fields the selector needs."""
    return {
        "pairAddress": address,
        "baseToken": base,
        "quoteToken": quote,
        "liquidity": {"usd": liquidity},
        "priceUsd": price,
        "marketCap": 204_000,
        "dexId": "pumpswap",
    }


CROSS_PAIR = _pair(
    "cross-pair",
    {"address": CYCLOSPORA_CA, "name": "Cyclospora", "symbol": "CYC"},
    {"address": MEMIPEDE_CA, "name": "MEMIPEDE", "symbol": "MEMIPEDE"},
    9_999_999,
    "42.0",
)
MEMIPEDE_LOW_LIQ = _pair(
    "memipede-low-liq",
    {"address": MEMIPEDE_CA, "name": "MEMIPEDE", "symbol": "MEMIPEDE"},
    {"address": SOL_CA, "name": "Wrapped SOL", "symbol": "SOL"},
    10_000,
    "0.00019",
)
MEMIPEDE_CANONICAL = _pair(
    "memipede-canonical",
    {"address": MEMIPEDE_CA, "name": "MEMIPEDE", "symbol": "MEMIPEDE"},
    {"address": SOL_CA, "name": "Wrapped SOL", "symbol": "SOL"},
    50_000,
    "0.0002042",
)
UNRELATED_PAIR = _pair(
    "unrelated-pair",
    {"address": OTHER_CA, "name": "Other", "symbol": "OTHER"},
    {"address": SOL_CA, "name": "Wrapped SOL", "symbol": "SOL"},
    999_999_999,
    "1.0",
)


class _Response:
    def __init__(self, pairs):
        self._pairs = pairs

    def json(self):
        return {"pairs": self._pairs}


def test_selector_prefers_target_base_pair_over_liquid_cross_pair():
    """A quote-side cross-pair must never replace a canonical base pair."""
    pairs = [CROSS_PAIR, MEMIPEDE_LOW_LIQ, UNRELATED_PAIR,
             MEMIPEDE_CANONICAL]
    matches = core.matching_dexscreener_pairs(pairs, MEMIPEDE_CA)

    assert [pair["pairAddress"] for pair in matches] == [
        "memipede-canonical", "memipede-low-liq", "cross-pair",
    ]
    assert core.select_dexscreener_pair(pairs, MEMIPEDE_CA) is \
        MEMIPEDE_CANONICAL


def test_quote_side_fallback_keeps_the_queried_token_metadata():
    """Even a quote-only fallback must identify MEMIPEDE, never Cyclospora."""
    chosen = core.select_dexscreener_pair([CROSS_PAIR], MEMIPEDE_CA)
    token = core.dexscreener_pair_token(chosen, MEMIPEDE_CA)

    assert chosen is CROSS_PAIR
    assert token["name"] == "MEMIPEDE"
    assert token["symbol"] == "MEMIPEDE"
    assert token["address"] == MEMIPEDE_CA


def test_get_market_keeps_identity_for_quote_only_fallback():
    """A quote-only response must still name the queried token correctly."""
    response = _Response([CROSS_PAIR])
    with patch.object(core.requests, "get", return_value=response):
        market = core.get_market(MEMIPEDE_CA)

    assert market["name"] == "MEMIPEDE"
    assert market["symbol"] == "MEMIPEDE"
    assert market["pair_addresses"] == ["cross-pair"]


def test_selector_rejects_pairs_without_the_requested_ca():
    """Liquidity is irrelevant unless either token address exactly matches."""
    pairs = [UNRELATED_PAIR, MEMIPEDE_CANONICAL]

    assert core.matching_dexscreener_pairs(pairs, "not-the-token") == []
    assert core.select_dexscreener_pair(pairs, "not-the-token") is None
    assert core.dexscreener_pair_token(MEMIPEDE_CANONICAL,
                                       "not-the-token") == {}


def test_get_market_uses_canonical_token_metadata_and_price():
    """The shared market helper drives CVD with MEMIPEDE's own pair fields."""
    pairs = [CROSS_PAIR, UNRELATED_PAIR, MEMIPEDE_LOW_LIQ,
             MEMIPEDE_CANONICAL]
    with patch.object(core.requests, "get", return_value=_Response(pairs)):
        market = core.get_market(MEMIPEDE_CA)

    assert market["name"] == "MEMIPEDE"
    assert market["symbol"] == "MEMIPEDE"
    assert market["price_usd"] == 0.0002042
    assert market["pair_addresses"][0] == "memipede-canonical"
    assert "unrelated-pair" not in market["pair_addresses"]


def test_cvd_page_delegates_pool_resolution_to_shared_market_helper():
    """Keep the Streamlit CVD page on the identity-safe code path."""
    page_path = os.path.join(ROOT, "pages", "4_📊_CVD.py")
    with open(page_path, "r", encoding="utf-8") as handle:
        source = handle.read()
    start = source.index("def get_pool")
    end = source.index("def ", start + 1)
    get_pool_source = inspect.cleandoc(source[start:end])

    assert "market = get_market(" in get_pool_source
    assert "baseToken" not in get_pool_source
    assert "pools[0]" in get_pool_source


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    passed = failed = assertions = 0
    for name, fn in tests:
        n_asserts = sum(
            1 for line in inspect.getsource(fn).splitlines()
            if line.strip().startswith("assert "))
        try:
            fn()
            passed += 1
            assertions += n_asserts
            print(f"  ✅ {name} ({n_asserts} assertions)")
        except AssertionError as exc:
            failed += 1
            print(f"  ❌ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ❌ {name}: {type(exc).__name__}: {exc}")

    total = passed + failed
    print(f"\n{passed}/{total} tests passed, {assertions} assertions, "
          f"{failed} failed")
    if failed:
        sys.exit(1)
    print("ALL PASSED")
