# -*- coding: utf-8 -*-
"""CVD flow safety diagnostics + new GMGN penalty curves.

Tests for the LP Radar / CVD feature additions from PR #5 (LP Radar
4-window conviction, CVD flow quality / distribution / persistence /
freshness checks) and the fresh-wallet / holder-concentration penalties
in the GMGN screener.

Run with:  python tests/test_flow_safety.py   (no pytest, no network)
"""
import json
import os
import sys
import time
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cvd  # noqa: E402
import gmgn_screener as g  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def write_conviction(history):
    """Write the supplied conviction history into the patched CONV_PATH."""
    with open(cvd.CONV_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f)


def write_cvd_swaps(ca, swaps, pool="pool"):
    """Write a minimal cvd.json entry with a raw swap list for `ca`."""
    with open(cvd.CVD_PATH, "w", encoding="utf-8") as f:
        json.dump({ca: {"pool": pool, "buckets": {},
                        "swaps": [list(s) for s in swaps]}}, f)


class TempPaths:
    """Keep cvd paths pointed at tmpdir so tests don't touch real data."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (cvd.CVD_PATH, cvd.CONV_PATH)
        cvd.CVD_PATH = os.path.join(self.tmp.name, "cvd.json")
        cvd.CONV_PATH = os.path.join(self.tmp.name, "conviction.json")
        # also flush the remote-cache so a previous run can't pollute
        cvd._conv_remote_cache.update(data=None, ts=0.0)
        return self

    def __exit__(self, *args):
        cvd.CVD_PATH, cvd.CONV_PATH = self.saved
        self.tmp.cleanup()


def point(ts, conviction, net_pure, vol=10, swaps=5):
    return {"ts": int(ts), "conviction": conviction, "net_pure": net_pure,
            "vol": vol, "swaps": swaps, "pure_buy": max(net_pure, 0),
            "pure_sell": max(-net_pure, 0)}


# ---------------------------------------------------------------------------
# CVD flow freshness
# ---------------------------------------------------------------------------
def test_flow_freshness():
    print("\n[freshness] conviction age is reported correctly")
    now = time.time()
    with TempPaths():
        # no history at all
        fr = cvd.flow_freshness("missing")
        check(fr["ok"] is False, "no history → not ok")
        check(fr["level"] == "danger",
              f"no history → level is danger, got {fr['level']!r}")
        check(fr["age_min"] == float("inf"), "no history → age is inf")
        check("never seen" in fr["reason"],
              f"no-history reason is human readable: {fr['reason']!r}")

        # fresh point (30 min old — well within 2.5h band)
        write_conviction({"abc": [point(now - 30 * 60, 40, 10)]})
        fr = cvd.flow_freshness("abc")
        check(fr["ok"] is True, "30-min-old point is fresh")
        check(fr["level"] == "ok",
              f"fresh level is ok, got {fr['level']!r}")
        check("fresh" in fr["reason"], f"reason: {fr['reason']!r}")

        # stale (4h — one missed cron, but still useful)
        write_conviction({"abc": [point(now - 4 * 3600, 40, 10)]})
        fr = cvd.flow_freshness("abc")
        check(fr["ok"] is False, "4h-old point is not fresh")
        check(fr["level"] == "warn",
              f"4h-old point is warn, got {fr['level']!r}")
        check("stale" in fr["reason"], f"stale reason: {fr['reason']!r}")

        # very stale (16h — 4+ missed runs)
        write_conviction({"abc": [point(now - 16 * 3600, 40, 10)]})
        fr = cvd.flow_freshness("abc")
        check(fr["ok"] is False, "16h-old point is not ok")
        check(fr["level"] == "danger",
              f"16h-old point is danger, got {fr['level']!r}")
        check("very stale" in fr["reason"],
              f"very-stale reason: {fr['reason']!r}")
        check("do not trust" in fr["reason"],
              f"very-stale reason warns not to trust: {fr['reason']!r}")

        # edge: exactly at the 2.5h fresh threshold is still ok
        write_conviction({"abc": [point(now - 149 * 60, 40, 10)]})
        fr = cvd.flow_freshness("abc")
        check(fr["ok"] is True, "149-min-old point is still ok")
        check(fr["level"] == "ok", "149-min edge → level=ok")

        # edge: 3h is warn (between 2.5h and 12h)
        write_conviction({"abc": [point(now - 3 * 3600, 40, 10)]})
        fr = cvd.flow_freshness("abc")
        check(fr["level"] == "warn", "3h → level=warn")

        # edge: 11.9h is still warn
        write_conviction({"abc": [point(now - 11.9 * 3600, 40, 10)]})
        fr = cvd.flow_freshness("abc")
        check(fr["level"] == "warn", "11.9h → level=warn (just under danger)")

        # edge: 12.1h just crossed into danger
        write_conviction({"abc": [point(now - 12.1 * 3600, 40, 10)]})
        fr = cvd.flow_freshness("abc")
        check(fr["level"] == "danger", "12.1h → level=danger")


# ---------------------------------------------------------------------------
# CVD flow persistence
# ---------------------------------------------------------------------------
def test_flow_persistence():
    print("\n[persistence] consecutive-window runs are detected")
    now = time.time()
    with TempPaths():
        # not enough points
        write_conviction({"a": [point(now - 60, 30, 5),
                                point(now, 35, 8)]})
        p = cvd.flow_persistence("a")
        check(p["ok"] is False, "2 points → not enough history")
        check(p["direction"] == "accum",
              f"2 positive nets → accum direction, got {p['direction']}")

        # 3-point accumulation run, each big enough → ok
        write_conviction({"a": [point(now - 6 * 3600, 30, 8),
                               point(now - 3 * 3600, 35, 10),
                               point(now, 40, 12)]})
        p = cvd.flow_persistence("a")
        check(p["ok"] is True, "3 consecutive ≥5 SOL accum runs")
        check(p["direction"] == "accum", "direction is accum")
        check("sustained" in p["reason"], f"reason: {p['reason']!r}")

        # 3-point distribution run
        write_conviction({"a": [point(now - 6 * 3600, 30, -8),
                               point(now - 3 * 3600, 25, -10),
                               point(now, 20, -12)]})
        p = cvd.flow_persistence("a")
        check(p["ok"] is True, "3 consecutive ≥5 SOL dist runs")
        check(p["direction"] == "dist", "direction is dist")

        # 3 points all positive but each <5 SOL → not "real" persistence
        write_conviction({"a": [point(now - 6 * 3600, 20, 1),
                               point(now - 3 * 3600, 22, 2),
                               point(now, 24, 3)]})
        p = cvd.flow_persistence("a")
        check(p["ok"] is False,
              "small repeated moves are NOT flagged as persistent")
        check("small" in p["reason"] or "noise" in p["reason"],
              f"small-run reason: {p['reason']!r}")

        # mixed direction → last sign picks direction, only 1 trailing run
        write_conviction({"a": [point(now - 6 * 3600, 20, 8),
                               point(now - 3 * 3600, 30, -10),
                               point(now, 25, 12)]})
        p = cvd.flow_persistence("a")
        check(p["direction"] == "accum",
              f"sign-flip ending positive → accum, got {p['direction']}")
        check(p["runs"] == 1,
              f"only the last point matches the accum direction, "
              f"got runs={p['runs']}")
        check(p["ok"] is False, "1-of-3 trailing run is not persistent")

        # zero at the end → choppy
        write_conviction({"a": [point(now - 6 * 3600, 20, 8),
                               point(now - 3 * 3600, 30, 10),
                               point(now, 25, 0)]})
        p = cvd.flow_persistence("a")
        check(p["direction"] == "choppy",
              f"zero-net trailing point → choppy, got {p['direction']}")


# ---------------------------------------------------------------------------
# CVD flow distribution
# ---------------------------------------------------------------------------
def test_flow_distribution():
    print("\n[distribution] drop-from-peak is detected with correct level")
    now = time.time()
    with TempPaths():
        # not enough history
        write_conviction({"a": [point(now - 3600, 30, 5),
                                point(now, 28, 3)]})
        d = cvd.flow_distribution("a")
        check(d["level"] == "ok", "≤3 points → no distribution flag")
        check(d["ok"] is False, "≤3 points → ok is False")

        # no net-buy peak → nothing to drop from
        write_conviction({"a": [point(now - 6 * 3600, 30, -5),
                               point(now - 3 * 3600, 28, -8),
                               point(now, 25, -10),
                               point(now, 20, -15)]})
        d = cvd.flow_distribution("a")
        check(d["level"] == "ok",
              "never had net-positive flow → not a distribution event")

        # mild drop (25%) → ok
        write_conviction({"a": [point(now - 6 * 3600, 30, 20),
                               point(now - 3 * 3600, 32, 18),
                               point(now, 28, 15),
                               point(now, 25, 15)]})
        d = cvd.flow_distribution("a")
        check(d["level"] == "ok", "25% drop is within normal volatility")
        check(d["ok"] is False, "25% drop → ok")

        # 40% drop with conviction falling → warn
        write_conviction({"a": [point(now - 9 * 3600, 30, 30),
                               point(now - 6 * 3600, 32, 28),
                               point(now - 3 * 3600, 30, 25),
                               point(now, 25, 18)]})
        d = cvd.flow_distribution("a")
        check(d["ok"] is True, "40% drop → flagged")
        check(d["level"] in ("warn", "danger"),
              f"40% drop level is warn/danger, got {d['level']}")
        check(d["drop_pct"] >= 30,
              f"drop_pct ≥ 30, got {d['drop_pct']}")


# ---------------------------------------------------------------------------
# CVD flow quality
# ---------------------------------------------------------------------------
def test_flow_quality():
    print("\n[quality] quiet / concentrated windows are flagged")
    with TempPaths():
        # no history
        write_conviction({})
        q = cvd.flow_quality("a")
        check(q["ok"] is False, "no history → not ok")

        # below volume threshold
        write_conviction({"a": [point(time.time(), 30, 10, vol=5, swaps=5)]})
        q = cvd.flow_quality("a")
        check(q["ok"] is False, "very low vol → not ok")
        check("quiet" in q["reason"] or "low" in q["reason"],
              f"quiet reason: {q['reason']!r}")

        # normal volume, normal swap count → ok
        write_conviction({"a": [point(time.time(), 30, 10,
                                      vol=80, swaps=20)]})
        q = cvd.flow_quality("a")
        check(q["ok"] is True, "normal window is ok")
        check("real flow" in q["reason"],
              f"normal reason: {q['reason']!r}")


def test_flow_quality_uses_point_own_window():
    """Regression: a STALE cron point must still count wallets from ITS
    OWN 6h window, not "now minus 6h". Before the fix, flow_quality()
    always called get_recent_swaps(ca, 6) which looks at [now-6h, now] —
    for a point that is hours old, that window has no data at all, so
    n_wallets came back 0 and a perfectly healthy, many-wallet window
    got mislabeled "one or two wallets dominate"."""
    print("\n[quality] stale point still reads its OWN window's wallets")
    with TempPaths():
        now = time.time()
        point_ts = now - 7 * 3600   # point is already "very stale" (>6h old)
        write_conviction({"a": [point(point_ts, 64, 11,
                                      vol=177, swaps=177)]})
        # 100 distinct wallets, all inside [point_ts-6h, point_ts) —
        # i.e. the point's own window, not "now"'s window.
        swaps = [("buy", 1.0, point_ts - 60 - i * 60, f"wallet{i}")
                for i in range(100)]
        write_cvd_swaps("a", swaps)

        q = cvd.flow_quality("a")
        check(q["n_wallets"] == 100,
              f"stale point still resolves its own window's wallets, "
              f"got n_wallets={q['n_wallets']}")
        check(q["ok"] is True,
              "100 wallets across 177 swaps must NOT be flagged as "
              "'one or two wallets dominate'")
        check("wallets" in q["reason"] and "one or two" not in q["reason"],
              f"reason should read as real flow, got: {q['reason']!r}")


# ---------------------------------------------------------------------------
# flow_check_panel — convenience wrapper
# ---------------------------------------------------------------------------
def test_check_panel():
    print("\n[panel] flow_check_panel returns all four sub-checks")
    now = time.time()
    with TempPaths():
        write_conviction({"a": [point(now - 6 * 3600, 30, 8),
                               point(now - 3 * 3600, 35, 10),
                               point(now, 40, 12)]})
        panel = cvd.flow_check_panel("a")
        for key in ("freshness", "persistence", "distribution", "quality"):
            check(key in panel, f"panel has {key}")
            check("reason" in panel[key],
                  f"{key} has a human reason")


# ---------------------------------------------------------------------------
# GMGN — fresh-wallet penalty
# ---------------------------------------------------------------------------
NOW = time.time()
GOOD_BASE = {"a": "Good", "s": "GOOD", "mc": 1_000_000, "lq": 180_000,
             "v": 800_000, "hd": 6000, "t10": 0.10, "smt": 35,
             "rug": 0.05, "ot": NOW - 12 * 86400, "pcp": 2.0, "pcp1h": 0.5,
             "bdrr": 0.01, "dhr": 0.005, "etpr": 0.05, "bdr": 0.08,
             "t70_shr": 0.001, "snp": 2, "kol": 8}


def test_fresh_wallet_penalty():
    print("\n[gmgn] fresh-wallet penalty is continuous and capped at AVOID")
    # no fresh wallet data → 0 penalty (curve is anchored at 0.15 → 0)
    r0 = g.score_token(dict(GOOD_BASE))
    base_score = r0["fit_exact"]
    # 25% fresh wallets → first anchor, small penalty
    r25 = g.score_token(dict(GOOD_BASE, fwr=0.25))
    check(r25["fit_exact"] < base_score,
          f"25% fresh-wallet lowers the score: "
          f"{base_score:.1f} → {r25['fit_exact']:.1f}")
    check(r25["fit_exact"] >= base_score - 8,
          "25% fresh-wallet penalty is bounded (≤ 8 pts at the anchor)")
    # 50% fresh wallets → risk flag trips, score capped at HIGH_RISK_CAP
    r55 = g.score_token(dict(GOOD_BASE, fwr=0.55))
    check(r55["high_risk"] is True,
          f"55% fresh-wallet → high_risk (got {r55['high_risk']})")
    check(r55["fit"] <= g.HIGH_RISK_CAP,
          f"55% fresh-wallet → fit ≤ {g.HIGH_RISK_CAP} (got {r55['fit']})")
    check(any("Fresh-wallet" in r for r in r55["risk_reasons"]),
          f"risk reason mentions Fresh-wallet: {r55['risk_reasons']}")
    # continuity: 24.9% → 25.1% must NOT jump more than 4 points
    s_lo = g.score_token(dict(GOOD_BASE, fwr=0.249))["fit_exact"]
    s_hi = g.score_token(dict(GOOD_BASE, fwr=0.251))["fit_exact"]
    check(abs(s_hi - s_lo) < 4.0,
          f"fresh-wallet curve is continuous: "
          f"0.249→0.251 = {s_lo:.1f}→{s_hi:.1f}")


# ---------------------------------------------------------------------------
# GMGN — holder-concentration penalty
# ---------------------------------------------------------------------------
def test_holder_concentration_penalty():
    print("\n[gmgn] holder-concentration penalty is continuous and capped")
    r0 = g.score_token(dict(GOOD_BASE))
    base_score = r0["fit_exact"]
    # 0.65 (top-50 = 65%) → small penalty
    r65 = g.score_token(dict(GOOD_BASE, t50=0.65))
    check(r65["fit_exact"] < base_score,
          f"top-50 = 65% lowers the score: "
          f"{base_score:.1f} → {r65['fit_exact']:.1f}")
    # 0.90 → cap kicks in
    r90 = g.score_token(dict(GOOD_BASE, t50=0.90))
    check(r90["high_risk"] is True,
          f"top-50 = 90% → high_risk (got {r90['high_risk']})")
    check(r90["fit"] <= g.HIGH_RISK_CAP,
          f"top-50 = 90% → fit ≤ {g.HIGH_RISK_CAP} (got {r90['fit']})")
    check(any("Top-50" in r for r in r90["risk_reasons"]),
          f"risk reason mentions Top-50: {r90['risk_reasons']}")
    # continuity check
    s_lo = g.score_token(dict(GOOD_BASE, t50=0.649))["fit_exact"]
    s_hi = g.score_token(dict(GOOD_BASE, t50=0.651))["fit_exact"]
    check(abs(s_hi - s_lo) < 4.0,
          f"holder-conc curve is continuous: "
          f"0.649→0.651 = {s_lo:.1f}→{s_hi:.1f}")


def test_new_fields_in_output():
    print("\n[contract] new fields are present in the row")
    r = g.score_token(GOOD_BASE)
    check("fresh_wallet_rate" in r,
          "fresh_wallet_rate is in the row")
    check("holder_conc" in r,
          "holder_conc is in the row")
    # 0.0 default when no fresh-wallet data was sent
    check(r["fresh_wallet_rate"] == 0.0,
          f"missing fresh-wallet data defaults to 0 (got "
          f"{r['fresh_wallet_rate']})")
    # top-50 falls back to top-10*1.1 when no t50 was sent
    expected_fallback = min(1.0, 0.10 * 1.1)
    check(abs(r["holder_conc"] - expected_fallback) < 1e-9,
          f"missing t50 falls back to top-10*1.1 = {expected_fallback:.2f} "
          f"(got {r['holder_conc']:.2f})")


def test_cvd_flow_signals():
    print("\n[signals] accumulation/distribution use LH/trader/pure profiles")
    import signals as sig
    with TempPaths() as tp:
        saved_sig = sig.SIGNALS_PATH
        sig.SIGNALS_PATH = os.path.join(tp.tmp.name, "signals.json")
        try:
            now = int(time.time())
            # 3 wallets buying and holding -> light_holder / pure_accum / trader
            swaps = [
                ("buy", 12.0, now - 1000, "w_lh"),
                ("sell", 1.0, now - 900, "w_lh"),
                ("buy", 8.0, now - 800, "w_tr"),
                ("sell", 3.0, now - 700, "w_tr"),
                ("buy", 10.0, now - 600, "w_pure"),
            ]
            write_cvd_swaps("ca_accum", swaps)
            res = sig.detect_and_record("ca_accum", "TEST", window_h=6)
            check("accumulation" in res, "accumulation signal recorded")
            logs = sig.load_signals()
            last = logs[-1] if logs else {}
            check("holders +" in last.get("detail", ""),
                  f"detail names holders: {last.get('detail')}")
            check("LH" in last.get("detail", "") and "Traders" in last.get("detail", ""),
                  "detail includes LH and Traders metrics")
            check("vs retail" not in last.get("detail", ""),
                  "detail no longer uses 'vs retail'")

            # Dump scenario: dumpers sell 30 SOL while holders are quiet
            swaps_dump = [
                ("sell", 20.0, now - 1000, "w_dist1"),
                ("sell", 15.0, now - 900, "w_dist2"),
                ("buy", 5.0, now - 800, "w_lh2"),
                ("sell", 1.0, now - 700, "w_lh2"),
            ]
            write_cvd_swaps("ca_dump", swaps_dump)
            res_dump = sig.detect_and_record("ca_dump", "DUMP", window_h=6)
            check("distribution" in res_dump, "distribution signal recorded")
            last_dump = sig.load_signals()[-1]
            check("distribution pressure: dumpers" in last_dump.get("detail", ""),
                  f"detail names dumpers vs holders: {last_dump.get('detail')}")
        finally:
            sig.SIGNALS_PATH = saved_sig


if __name__ == "__main__":
    test_flow_freshness()
    test_flow_persistence()
    test_flow_distribution()
    test_flow_quality()
    test_flow_quality_uses_point_own_window()
    test_check_panel()
    test_fresh_wallet_penalty()
    test_holder_concentration_penalty()
    test_new_fields_in_output()
    test_cvd_flow_signals()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for f in failures:
        print("  -", f)
    sys.exit(1 if failures else 0)
