# -*- coding: utf-8 -*-
"""Offline tests for 4-hourly CVD Detail & Top Holder Cron integration.

Covers:
  1. _try_snapshot() in scripts/update_cvd.py updates watchlist metadata
     with diamond_pct, real_holders, and dust_holders.
  2. get_watchlist_details() in app.py reads metadata and falls back to
     cron snapshots in holder_snapshots.json.
  3. fetch_holder_snapshot() in pages/4_📊_CVD.py falls back to cron
     snapshot when Helius API keys are not configured.

Usage: python tests/test_cron_top_holders.py
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod
from scripts.update_cvd import _try_snapshot

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def test_try_snapshot_updates_watchlist_meta():
    """Verify that _try_snapshot computes top holder metrics and updates meta."""
    meta = {"symbol": "TEST"}
    # Pass empty api_keys so it falls back to GMGN top holders
    # We mock core.gmgn_token_stat to return dummy holder list
    import core
    import scripts.update_cvd as upd
    orig_gmgn = getattr(core, "gmgn_token_stat", None)
    orig_upd_gmgn = getattr(upd, "gmgn_token_stat", None)
    try:
        def fake_gmgn(ca, timeout=15):
            return {
                "holders": [
                    ["wallet1", 100.0],
                    ["wallet2", 50.0],
                    ["wallet3", 10.0],
                ],
                "supply": 1000.0,
                "total_holders": 3,
            }
        core.gmgn_token_stat = fake_gmgn
        upd.gmgn_token_stat = fake_gmgn
        res_str = _try_snapshot((), "TEST_CA", meta, price_now=0.50)
        check("snap-gmgn" in res_str, f"_try_snapshot used gmgn fallback (got: {res_str})")
        check(meta.get("diamond_pct") == 100.0, f"diamond_pct is 100.0 (got: {meta.get('diamond_pct')})")
        check(meta.get("real_holders") == 3, f"real_holders is 3 (got: {meta.get('real_holders')})")
        check(meta.get("dust_holders") == 0, f"dust_holders is 0 (got: {meta.get('dust_holders')})")
    finally:
        if orig_gmgn:
            core.gmgn_token_stat = orig_gmgn
        if orig_upd_gmgn:
            upd.gmgn_token_stat = orig_upd_gmgn


def test_get_watchlist_details_reads_meta():
    """Verify that get_watchlist_details returns diamond_pct & real/dust from meta."""
    meta = {
        "symbol": "TEST",
        "diamond_pct": 85.5,
        "real_holders": 120,
        "dust_holders": 80,
        "avg_cost": 12.0,
    }
    details = appmod.get_watchlist_details("TEST_CA", meta)
    check(details["diamond_pct"] == 85.5, f"details['diamond_pct'] == 85.5 (got: {details['diamond_pct']})")
    check(details["real_holders"] == 120, f"details['real_holders'] == 120 (got: {details['real_holders']})")
    check(details["dust_holders"] == 80, f"details['dust_holders'] == 80 (got: {details['dust_holders']})")


def test_cvd_page_fallback_to_cron_snapshot():
    """Verify fetch_holder_snapshot in pages/4_📊_CVD.py falls back to cron snapshot."""
    import core
    orig_gm = getattr(core, "get_market", None)
    try:
        def fake_gm(ca):
            return {
                "name": "TEST",
                "symbol": "TEST",
                "price_usd": 1.0,
                "marketcap": 100000.0,
                "pair_addresses": ["fake_pool"],
            }
        core.get_market = fake_gm
        import importlib
        cvdpage = importlib.import_module("pages.4_📊_CVD")
        import cvd as cvdmod
        # Mock load_holder_snapshots
        orig_load = getattr(cvdmod, "load_holder_snapshots", None)
        try:
            def fake_load():
                return {
                    "TEST_CA": {
                        "b100": {
                            "ts": int(time.time()),
                            "supply": 10000.0,
                            "holders": [["ownerA", 500.0], ["ownerB", 100.0]],
                        }
                    }
                }
            cvdmod.load_holder_snapshots = fake_load
            res = cvdpage.fetch_holder_snapshot("TEST_CA", ())
            check(res.get("ok") is True, "fetch_holder_snapshot ok=True without Helius keys")
            check("Cron Snapshot" in res.get("source", ""), f"source is Cron Snapshot (got: {res.get('source')})")
            check(res.get("total_holders") == 2, f"total_holders is 2 (got: {res.get('total_holders')})")
        finally:
            if orig_load:
                cvdmod.load_holder_snapshots = orig_load
    finally:
        if orig_gm:
            core.get_market = orig_gm


if __name__ == "__main__":
    print("=== test_try_snapshot_updates_watchlist_meta ===")
    test_try_snapshot_updates_watchlist_meta()
    print("=== test_get_watchlist_details_reads_meta ===")
    test_get_watchlist_details_reads_meta()
    print("=== test_cvd_page_fallback_to_cron_snapshot ===")
    test_cvd_page_fallback_to_cron_snapshot()

    if failures:
        print(f"\nFAILED ({len(failures)} failures)")
        sys.exit(1)
    else:
        print("\nALL PASSED")
