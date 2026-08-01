# -*- coding: utf-8 -*-
"""Regression tests for token_context.py (holder avg cost + down from ATH).

Runs without pytest and without network:
    python tests/test_token_context.py

14 assertions covering:
  - _f() float coercion edge cases
  - _holder_list() payload extraction
  - holder_avg_cost() aggregation via sum(cost)/sum(balance)
  - holder_avg_cost() skips AMM/pool and null-cost rows
  - avg_cost_change_pct() percentage computation
  - down_from_ath_pct() with explicit ATH field
"""
import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import token_context as tc


def test_f_coercion():
    """_f handles valid, None, NaN, inf, bool, empty string."""
    assert tc._f("3.14") == 3.14
    assert tc._f(None, -1) == -1
    assert tc._f(float("nan"), -1) == -1
    assert tc._f(float("inf"), -1) == -1
    assert tc._f(True, -1) == -1
    assert tc._f("", -1) == -1

def test_holder_list_shapes():
    """_holder_list digs arrays out of various GMGN response shapes."""
    assert len(tc._holder_list({"code": 0, "data": [{"w": "A"}, {"w": "B"}]})) == 2
    assert tc._holder_list({"data": {"holders": [{"w": 1}]}}) == [{"w": 1}]
    assert len(tc._holder_list([{"a": 1}, {"a": 2}])) == 2
    assert tc._holder_list(None) == []

def test_avg_cost_basic():
    """sum(cost) / sum(balance) aggregation."""
    holders = [
        {"balance": 1000, "cost": 50.0, "addr_type": 0},
        {"balance": 3000, "cost": 150.0, "addr_type": 0},
    ]
    avg = tc.holder_avg_cost(holders)
    # (50+150) / (1000+3000) = 200/4000 = 0.05
    assert avg is not None and abs(avg - 0.05) < 1e-9

def test_avg_cost_skips_amm():
    """AMM/pool rows (addr_type != 0 or exchange filled) must be dropped."""
    holders = [
        {"balance": 1000, "cost": 100.0, "addr_type": 0},
        {"balance": 50000, "cost": 0.001, "addr_type": 1},
        {"balance": 9000, "cost": 1.0, "exchange": "pump_amm"},
    ]
    avg = tc.holder_avg_cost(holders)
    assert avg is not None and abs(avg - 0.1) < 1e-9

def test_avg_cost_skips_null_cost():
    """Wallets with cost=null or cost=0 are skipped."""
    holders = [
        {"balance": 1000, "cost": None, "addr_type": 0},
        {"balance": 2000, "cost": 0, "addr_type": 0},
        {"balance": 500, "cost": 25.0, "addr_type": 0},
    ]
    avg = tc.holder_avg_cost(holders)
    assert avg is not None and abs(avg - 0.05) < 1e-9

def test_avg_cost_all_null():
    """Returns None when no row has a usable cost."""
    holders = [
        {"balance": 1000, "cost": None, "addr_type": 0},
        {"balance": 2000, "cost": None, "addr_type": 0},
    ]
    assert tc.holder_avg_cost(holders) is None

def test_avg_cost_change_pct():
    """price=0.04, avg_cost=0.05 → (0.04/0.05 - 1)*100 = -20%."""
    holders = [{"balance": 1000, "cost": 50.0, "addr_type": 0}]
    pct = tc.avg_cost_change_pct(0.04, holders)
    assert pct is not None and abs(pct - (-20.0)) < 1e-6

def test_avg_cost_change_pct_unknown():
    assert tc.avg_cost_change_pct(None, [{"balance": 1, "cost": 1}]) is None

def test_down_from_ath_explicit():
    token = {"p": 0.001, "down_from_ath": -75.5}
    d = tc.down_from_ath_pct(token)
    assert d is not None and abs(d - 75.5) < 1e-6

def test_down_from_ath_from_price():
    token = {"p": 0.001, "ath": 0.01}
    d = tc.down_from_ath_pct(token)
    # (0.01 - 0.001) / 0.01 * 100 = 90%
    assert d is not None and abs(d - 90.0) < 1e-6


if __name__ == "__main__":
    import inspect
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    passed = failed = assertion_count = 0
    for name, fn in tests:
        # Count assert statements in the function source
        src = inspect.getsource(fn)
        n_asserts = sum(1 for line in src.splitlines()
                       if line.strip().startswith("assert "))
        try:
            fn()
            passed += 1
            assertion_count += n_asserts
            print(f"  \u2705 {name} ({n_asserts} assertions)")
        except AssertionError as e:
            failed += 1
            print(f"  \u274c {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  \u274c {name}: {type(e).__name__}: {e}")
    total = passed + failed
    print(f"\n{passed}/{total} tests passed, {assertion_count} assertions, "
          f"{failed} failed")
    if failed:
        sys.exit(1)
    print("ALL PASSED")
