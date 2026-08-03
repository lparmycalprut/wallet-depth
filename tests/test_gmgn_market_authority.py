# -*- coding: utf-8 -*-
"""Acceptance tests: GMGN is the sole market source for CTO Incubation Radar.

Covers the follow-up of PR #38:

  1. Stage 1 (``incubation_radar.is_incubation_candidate``) admits the
     documented MEMIPEDE mock row (MC $189k, vol24 $70k, vol/MC ~0.37,
     liq <$45k, holders/T10/risk fields within gates).
  2. The same row with GMGN vol24 $99,064 FAILS (``vol24 > 90000``) at both
     Stage 1 (strict and relaxed) and deep-scan strict.
  3. With ``get_market()`` monkeypatched to a DexScreener payload whose
     vol24 is $45,000, a deep scan fed the GMGN row still uses GMGN:
     market volume stays $70,000, ``market_source == "gmgn"``, and the Dex
     figure never feeds pass/fail (it only appears in divergence notes).
  4. Without any GMGN snapshot the deep scan FAILS CLOSED — even when
     DexScreener/history would have had "good" numbers.
  5. Live per-CA snapshot path (``fetch_gmgn_market_row``) normalises the
     long-form token_stat fields into a radar-shaped row.
  6. Runtime signatures: ``screen_incubation(relaxed=False, debug=False)``
     and ``deep_scan_token(ca, relaxed=False, do_cluster=False,
     helius_keys=None, gmgn_row=None)``.

Runs WITHOUT pytest and WITHOUT network (all external calls monkeypatched):
    python tests/test_gmgn_market_authority.py
"""
import inspect
import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cto_deep_scan as cds
from incubation_radar import is_incubation_candidate, screen_incubation

MEMIPEDE_CA = "MEMipedEMEMipedEMEMipedEMEMipedEMEMipedE111"


def memipede_row(vol24=70000.0):
    """Mock of a scored GMGN incubation row for MEMIPEDE.

    Numbers from the incident report: GMGN MC ~$189k, vol24 ~$70k across all
    pools (DexScreener's deepest pair only shows ~$45k), vol/MC ~0.37.
    """
    return {
        "ca": MEMIPEDE_CA,
        "symbol": "MEMIPEDE",
        "name": "Millipede",
        "mc": 189000.0,
        "liq": 26500.0,            # below the $45k deep strict cap, above $3k floor
        "liq_pct": 14.0,
        "vol24": vol24,
        "vol_mc": round(vol24 / 189000.0, 2),
        "holders": 1250,
        "t10_pct": 18.5,
        "rug": 0.18,
        "age_d": 6.0,
        "chg24": 3.2,
        "chg1h": 0.5,
        "fit": 62,
        "fit_exact": 61.8,
        "grade": "OK",
        "insider_ratio": 0.03,
        "bundler_rate": 0.06,
        "fresh_wallet_rate": 0.11,
        "entrap_rate": 0.10,
        "botdegen_rate": 0.10,
        "sniper_hold": 0.02,
        "snipers": 10,
        "holder_conc": 0.50,
        "price": 0.00019,
        "logo": "",
        "_window": "5-10d",
    }


#: DexScreener payload with DIFFERENT volume (single deepest pair only).
#: liq differs by $500 (inside the divergence tolerance) so the only note
#: fired is the volume one.
DEX_MARKET = {
    "name": "Millipede",
    "symbol": "MEMIPEDE",
    "price_usd": 0.00019,
    "marketcap": 189000.0,
    "liquidity_usd": 26000.0,
    "volume": {"h24": 45000.0},
    "url": f"https://dexscreener.com/solana/{MEMIPEDE_CA}",
}


def _patched_network():
    """Common monkeypatch stack so deep_scan_token never touches network."""
    return [
        mock.patch.object(cds, "get_market", lambda ca: dict(DEX_MARKET)),
        mock.patch.object(cds, "is_cto_via_dexscreener",
                          lambda ca: (False, "mock: no cto keywords")),
        mock.patch.object(cds, "get_conviction_flip",
                          lambda ca: {"rising": True, "conv": 55, "persist": 3,
                                      "ups": 3, "net_pos": 2,
                                      "reason": "mock rising conviction",
                                      "last": {"net_pure": 5, "conviction": 55}}),
        mock.patch.object(cds, "gmgn_token_stat", lambda ca, timeout=15: {}),
        mock.patch.object(cds, "fetch_gmgn_market_row", lambda ca: None),
    ]


class _patches:
    """Tiny context manager entering a list of mock.patch objects."""

    def __init__(self, patch_list):
        self._patch_list = patch_list

    def __enter__(self):
        for p in self._patch_list:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patch_list):
            p.stop()
        return False


def test_memipede_stage1_is_candidate_strict_and_relaxed():
    row = memipede_row(vol24=70000.0)
    ok, reason = is_incubation_candidate(row, relaxed=False)
    assert ok, f"strict should pass, got: {reason}"
    assert "(0.37x)" in reason, reason  # GMGN vol/MC ~0.37 echoed in the reason
    ok_r, reason_r = is_incubation_candidate(row, relaxed=True)
    assert ok_r, f"relaxed should pass, got: {reason_r}"
    # vol/MC is computed from the GMGN v and mc fields: 70000/189000 ~= 0.37
    assert abs(row["vol24"] / row["mc"] - 0.3704) < 0.001


def test_vol99064_fails_vol24_gate_everywhere():
    row = memipede_row(vol24=99064.0)
    # vol/mc = 0.52 — comfortably inside the 0.8/1.2 caps, so the ONLY
    # failing gate must be the absolute $90k volume ceiling.
    assert row["vol_mc"] <= 0.8
    ok_s, reason_s = is_incubation_candidate(row, relaxed=False)
    assert not ok_s and "vol24 $99064 >90k" in reason_s, reason_s
    ok_r, reason_r = is_incubation_candidate(row, relaxed=True)
    # Stage-1 relaxed keeps the same absolute volume cap ($90k).
    assert not ok_r and "vol24 $99064 >90k" in reason_r, reason_r

    with _patches(_patched_network()):
        res = cds.deep_scan_token(MEMIPEDE_CA, relaxed=False, do_cluster=False,
                                  helius_keys=(), gmgn_row=row)
    assert res["pass"] is False
    assert any("vol24 $99064 >$90k" in r for r in res["reasons"]), res["reasons"]
    # only the volume gate failed
    assert not any("NOT in 3k" in r for r in res["reasons"]), res["reasons"]


def test_gmgn_row_overrides_dexscreener_in_deep_scan():
    """The exact acceptance case: Dex vol $45k monkeypatched, GMGN row $70k."""
    row = memipede_row(vol24=70000.0)
    with _patches(_patched_network()):
        res = cds.deep_scan_token(MEMIPEDE_CA, relaxed=False, do_cluster=False,
                                  helius_keys=(), gmgn_row=row)
    # market snapshot comes 100% from the GMGN row
    assert res["market"]["volume"]["h24"] == 70000.0
    assert res["market"]["marketcap"] == 189000.0
    assert res["market"]["liquidity_usd"] == 26500.0
    assert res["market"]["market_source"] == "gmgn"
    assert res["market_source"] == "gmgn"
    assert abs(res["market"]["vol_mc"] - 70000.0 / 189000.0) < 0.001
    assert res["market"]["t10_pct"] == 18.5
    assert res["market"]["holders"] == 1250
    # pass/fail must be driven by GMGN $70k, never by Dex $45k
    assert res["pass"] is True, res["reasons"]
    assert any("vol24 $70000 <=$90k" in r for r in res["reasons"]), res["reasons"]
    assert any("market source: GMGN" in r for r in res["reasons"])
    assert not any("$45,000" in r or "45000" in r for r in res["reasons"])
    # Dex numbers survive ONLY as divergence metadata
    assert res["dex_market"]["volume_h24"] == 45000.0
    div = res["market_divergence"]
    assert any("vol24" in n and "45,000" in n and "GMGN authoritative" in n
               for n in div), div


def test_fail_closed_without_gmgn_snapshot():
    """No gmgn_row + no live GMGN snapshot => FAIL, even with 'good' Dex."""
    with _patches(_patched_network()):
        res = cds.deep_scan_token(MEMIPEDE_CA, relaxed=False, do_cluster=False,
                                  helius_keys=(), gmgn_row=None)
    assert res["pass"] is False
    assert res["market_source"] is None
    assert res["market"].get("market_source") is None
    # Dex's $189k MC must NOT be copied into the market snapshot
    assert not res["market"].get("marketcap")
    assert not (res["market"].get("volume") or {}).get("h24")
    assert any("GMGN market snapshot unavailable" in r for r in res["reasons"]), \
        res["reasons"]
    # Dex metadata is recorded for transparency but flagged as non-authoritative
    assert res["dex_market"].get("marketcap") == 189000.0
    # no divergence notes without a GMGN baseline
    assert res["market_divergence"] == []


def test_fetch_gmgn_market_row_normalizes_token_stat():
    """Live path for --ca/watchlist scans: token_stat -> radar-shaped row."""
    raw = {
        "usd_market_cap": "189000",
        "liquidity": "26500",
        "volume": "70000",
        "holder_count": "1250",
        "top_10_holder_rate": "0.185",
        "fresh_wallet_rate": "0.11",
        "dev_team_hold_rate": "0.03",
        "top_bundler_trader_percentage": "0.06",
        "symbol": "MEMIPEDE",
        "price": "0.00019",
        "open_timestamp": int(time.time()) - 6 * 86400,
    }
    stat = {"holders": [], "total_holders": None, "supply": None, "raw": raw}
    with mock.patch.object(cds, "gmgn_token_stat", lambda ca, timeout=15: stat), \
         mock.patch.object(cds, "_fetch_gmgn_token_prices", lambda ca, timeout=15: None):
        fetched = cds.fetch_gmgn_market_row(MEMIPEDE_CA)
    assert fetched is not None
    row, stat_out = fetched
    assert row["mc"] == 189000.0
    assert row["liq"] == 26500.0
    assert row["vol24"] == 70000.0
    assert row["holders"] == 1250
    assert row["t10_pct"] == 18.5
    assert row["fresh_wallet_rate"] == 0.11
    assert row["symbol"] == "MEMIPEDE"

    # token_stat without market cap and token_prices also empty => unavailable
    stat_no_mc = {"holders": [], "total_holders": None, "supply": None,
                  "raw": {"holder_count": "1250"}}
    with mock.patch.object(cds, "gmgn_token_stat", lambda ca, timeout=15: stat_no_mc), \
         mock.patch.object(cds, "_fetch_gmgn_token_prices", lambda ca, timeout=15: None):
        assert cds.fetch_gmgn_market_row(MEMIPEDE_CA) is None

    # market_from_gmgn_row must never mislabel history/Dex fallbacks
    assert cds.market_from_gmgn_row(
        {"ca": "X", "mc": 1, "_source": "history_fallback"}) == {}
    assert cds.market_from_gmgn_row(
        {"ca": "X", "mc": 1, "market_source": "dexscreener"}) == {}
    assert cds.market_from_gmgn_row({"ca": "X", "liq": 5000}) == {}   # no mc
    assert cds.market_from_gmgn_row(None) == {}
    snap = cds.market_from_gmgn_row({"ca": "X", "mc": 189000, "vol24": 70000,
                                     "t10_pct": 18.5, "liq": 26500})
    assert snap["market_source"] == "gmgn"
    assert snap["volume"] == {"h24": 70000.0}
    assert round(snap["vol_mc"], 4) == round(70000.0 / 189000.0, 4)


def test_divergence_notes_only_fire_on_real_gaps():
    gmgn = {"marketcap": 189000.0, "liquidity_usd": 26500.0,
            "volume": {"h24": 70000.0}}
    # dex numbers close to gmgn => no note
    close = {"marketcap": 185000.0, "liquidity_usd": 26200.0,
             "volume": {"h24": 68000.0}}
    assert cds._divergence_notes(gmgn, close) == []
    # dex volume far below gmgn (the MEMIPEDE case) => exactly one vol note
    notes = cds._divergence_notes(gmgn, dict(DEX_MARKET))
    assert len(notes) == 1 and "vol24" in notes[0]
    assert "GMGN authoritative" in notes[0]
    # missing dex side => no crash, no notes
    assert cds._divergence_notes(gmgn, {}) == []
    assert cds._divergence_notes({}, dict(DEX_MARKET)) == []


def test_runtime_signatures():
    sig = inspect.signature(screen_incubation)
    params = list(sig.parameters)
    assert params == ["relaxed", "debug"], params
    assert sig.parameters["relaxed"].default is False
    assert sig.parameters["debug"].default is False

    sig2 = inspect.signature(cds.deep_scan_token)
    params2 = list(sig2.parameters)
    assert params2 == ["ca", "relaxed", "do_cluster", "helius_keys",
                       "gmgn_row"], params2
    assert sig2.parameters["relaxed"].default is False
    assert sig2.parameters["do_cluster"].default is False
    assert sig2.parameters["helius_keys"].default is None
    assert sig2.parameters["gmgn_row"].default is None
    # keyword-compatible call works
    with _patches(_patched_network()):
        res = cds.deep_scan_token(ca=MEMIPEDE_CA, relaxed=False,
                                  do_cluster=False, helius_keys=(),
                                  gmgn_row=memipede_row())
    assert res["market_source"] == "gmgn"


if __name__ == "__main__":
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    passed = failed = assertion_count = 0
    for name, fn in tests:
        src = inspect.getsource(fn)
        n_asserts = sum(1 for line in src.splitlines()
                        if line.strip().startswith("assert "))
        try:
            fn()
            passed += 1
            assertion_count += n_asserts
            print(f"  ✅ {name} ({n_asserts} assertions)")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
    total = passed + failed
    print(f"\n{passed}/{total} tests passed, {assertion_count} assertions, "
          f"{failed} failed")
    if failed:
        sys.exit(1)
    print("ALL PASSED")
