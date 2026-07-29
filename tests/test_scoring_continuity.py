# -*- coding: utf-8 -*-
"""Continuity + calibration tests for the GMGN fit score.

The bug these guard against: the score used to be a stack of if/elif
threshold ladders, so a hair's-breadth move in one input could swing the
result by 20+ points. RAKO with 9 smart wallets scored 54 (WEAK); the same
token with 10 scored 77 (PRIME). Nothing about the token had changed.

Run with:  python tests/test_scoring_continuity.py   (no pytest needed)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmgn_screener as g  # noqa: E402

NOW = time.time()

#: the real RAKO reading (watchlist + history.json, 2026-07-28) — this is
#: the token that exposed the cliff
RAKO = {"a": "5sd8bKraewJNHFg72scxxYXNeLCASVct1gxqi3Xipump", "s": "RAKO",
        "mc": 497014, "lq": 61878, "v": 325110, "hd": 3367, "t10": 0.1564,
        "smt": 9, "rug": 0.16, "ot": NOW - 6.5 * 86400, "pcp": 4.2,
        "pcp1h": -1.1, "bdrr": 0.02, "dhr": 0.001, "etpr": 0.11,
        "bdr": 0.14, "t70_shr": 0.001, "snp": 4, "kol": 3}

#: a clean, boring, all-pillars-good token
GOOD = {"a": "Good", "s": "GOOD", "mc": 1_000_000, "lq": 180_000, "v": 800_000,
        "hd": 6000, "t10": 0.10, "smt": 35, "rug": 0.05,
        "ot": NOW - 12 * 86400, "pcp": 2.0, "pcp1h": 0.5, "bdrr": 0.01,
        "dhr": 0.005, "etpr": 0.05, "bdr": 0.08, "t70_shr": 0.001,
        "snp": 2, "kol": 8}

#: a token that should be nowhere near green
BAD = {"a": "Bad", "s": "BAD", "mc": 200_000, "lq": 4000, "v": 2_000_000,
       "hd": 600, "t10": 0.42, "smt": 1, "rug": 0.75,
       "ot": NOW - 0.5 * 86400, "pcp": 140.0, "pcp1h": 22.0, "bdrr": 0.35,
       "dhr": 0.28, "etpr": 0.5, "bdr": 0.5, "t70_shr": 0.2,
       "snp": 60, "kol": 0}

#: (field, sweep values) — every knob the score reads, swept finely across
#: the region where the old ladders had their steps
SWEEPS = {
    "smt": [x / 2 for x in range(0, 120)],
    "t10": [x / 2000 for x in range(0, 900)],
    "lq": [x * 500 for x in range(0, 500)],
    "hd": list(range(0, 8000, 20)),
    "pcp": [x / 2 for x in range(-200, 300)],
    "pcp1h": [x / 2 for x in range(-60, 60)],
    "rug": [x / 500 for x in range(0, 500)],
    "v": [x * 5000 for x in range(0, 600)],
    "dhr": [x / 1000 for x in range(0, 400)],
    "bdrr": [x / 1000 for x in range(0, 400)],
    "etpr": [x / 1000 for x in range(0, 700)],
    "bdr": [x / 1000 for x in range(0, 700)],
    "t70_shr": [x / 2000 for x in range(0, 300)],
    "snp": list(range(0, 80)),
    "kol": list(range(0, 30)),
    "ot": [NOW - d / 4 * 86400 for d in range(0, 80)],
}

#: biggest jump we tolerate between two adjacent sweep steps, in points.
#: Hard risk flags are a deliberate, documented cliff (score -> 40), so
#: transitions that flip ``high_risk`` are exempted below.
MAX_JUMP = 4.0

failures = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        failures.append(msg)


def score(tok):
    r = g.score_token(tok)
    return r["fit_exact"], r


def test_no_cliffs():
    """No small input change may move the score more than MAX_JUMP."""
    print("\n[continuity] sweeping every scored field on 3 base tokens")
    for name, base in (("RAKO", RAKO), ("GOOD", GOOD), ("BAD", BAD)):
        worst_field, worst_jump, worst_at = None, 0.0, None
        for field, values in SWEEPS.items():
            prev_s, prev_r, prev_v = None, None, None
            for v in values:
                s, r = score(dict(base, **{field: v}))
                if prev_s is not None:
                    # crossing a hard-risk flag is an intentional cliff
                    same_risk = r["high_risk"] == prev_r["high_risk"]
                    jump = abs(s - prev_s)
                    if same_risk and jump > worst_jump:
                        worst_jump, worst_field = jump, field
                        worst_at = (prev_v, v, prev_s, s)
                prev_s, prev_r, prev_v = s, r, v
        detail = ""
        if worst_at:
            a, b, sa, sb = worst_at
            detail = f" (worst: {worst_field} {a:g}→{b:g} = {sa:.1f}→{sb:.1f})"
        check(worst_jump <= MAX_JUMP,
              f"{name}: max jump {worst_jump:.1f} <= {MAX_JUMP}{detail}")


def test_rako_regression():
    """The exact case from the bug report: 9 vs 10 smart wallets."""
    print("\n[regression] RAKO 9 vs 10 smart wallets")
    s9, r9 = score(dict(RAKO, smt=9))
    s10, r10 = score(dict(RAKO, smt=10))
    check(abs(s10 - s9) < MAX_JUMP,
          f"one extra smart wallet moves score {s9:.1f}→{s10:.1f} "
          f"(was 54→77 before the fix)")
    # Grades are discrete, so *some* input will always sit on a band edge.
    # What must not happen is a grade change while the score barely moves
    # in the middle of a band — i.e. the grade may only flip when the two
    # scores straddle a band boundary by a narrow margin.
    if r9["grade"] != r10["grade"]:
        edges = [g.FIT_WEAK, g.FIT_OK, g.FIT_PRIME]
        lo, hi = min(s9, s10), max(s9, s10)
        check(any(lo <= e <= hi for e in edges),
              f"grade flip {r9['grade']}→{r10['grade']} is a band-edge "
              f"crossing ({s9:.1f}→{s10:.1f}), not a scoring cliff")
    else:
        check(True, f"grade stable ({r9['grade']})")
    # and the whole neighbourhood must be smooth, not just this one pair
    seq = [score(dict(RAKO, smt=n))[0] for n in range(5, 16)]
    steps = [abs(b - a) for a, b in zip(seq, seq[1:])]
    check(max(steps) < MAX_JUMP,
          f"smt 5→15 sweep is smooth, biggest step {max(steps):.1f}: "
          f"{[round(x) for x in seq]}")


def test_monotonic():
    """Better input never scores worse (and vice-versa for risk fields)."""
    print("\n[monotonicity] each pillar moves the score the right way")
    better = {"smt": [0, 5, 10, 20, 30, 50], "hd": [500, 1000, 2500, 5000],
              "lq": [10_000, 30_000, 60_000, 100_000, 150_000]}
    worse = {"t10": [0.10, 0.18, 0.25, 0.32, 0.40],
             "rug": [0.05, 0.2, 0.35, 0.5],
             "dhr": [0.0, 0.05, 0.10, 0.15, 0.20],
             "bdrr": [0.0, 0.05, 0.10, 0.15, 0.20],
             "etpr": [0.0, 0.2, 0.3, 0.4],
             "bdr": [0.0, 0.2, 0.3, 0.4],
             "t70_shr": [0.0, 0.03, 0.08, 0.15]}
    for field, vals in better.items():
        ss = [score(dict(GOOD, **{field: v}))[0] for v in vals]
        check(all(b >= a - 1e-9 for a, b in zip(ss, ss[1:])),
              f"{field} ↑ never lowers the score: "
              f"{[round(x, 1) for x in ss]}")
    for field, vals in worse.items():
        ss = [score(dict(GOOD, **{field: v}))[0] for v in vals]
        check(all(b <= a + 1e-9 for a, b in zip(ss, ss[1:])),
              f"{field} ↑ never raises the score: "
              f"{[round(x, 1) for x in ss]}")


def test_calibration_preserved():
    """The ramps must not turn the screener into a rubber stamp."""
    print("\n[calibration] grades still mean what the README says")
    sg, rg = score(GOOD)
    sb, rb = score(BAD)
    check(rg["grade"] == "PRIME", f"clean token is PRIME ({sg:.0f})")
    check(rb["high_risk"] and sb <= g.HIGH_RISK_CAP,
          f"junk token is capped at {g.HIGH_RISK_CAP} ({sb:.0f}, "
          f"{rb['grade']})")
    # a token that clearly breaks one gate must not reach PRIME
    for field, val, label in ((("pcp"), 60.0, "already pumped +60%"),
                              ("smt", 3, "3 smart wallets"),
                              ("t10", 0.32, "T10 32%"),
                              ("hd", 700, "700 holders")):
        s, r = score(dict(GOOD, **{field: val}))
        check(s < g.FIT_PRIME,
              f"{label} keeps it out of PRIME ({s:.0f} {r['grade']})")


def test_bounds_and_types():
    """Score stays 0-100 and the row keeps its old contract."""
    print("\n[contract] output shape / bounds")
    for name, tok in (("RAKO", RAKO), ("GOOD", GOOD), ("BAD", BAD),
                      ("empty", {})):
        r = g.score_token(tok)
        check(isinstance(r["fit"], int) and 0 <= r["fit"] <= 100,
              f"{name}: fit is an int in 0-100 ({r['fit']})")
        check(isinstance(r["penalty"], int) and r["penalty"] >= 0,
              f"{name}: penalty is a non-negative int ({r['penalty']})")
        check(r["grade"] == g.fit_grade(r["fit"], r["high_risk"]),
              f"{name}: grade matches fit_grade()")
    # junk / hostile input must not explode
    for junk in ({"mc": "abc", "smt": None, "t10": float("nan")},
                 {"mc": 0, "lq": 0, "v": float("inf")},
                 {"hd": True, "rug": "", "pcp": "1e999"}):
        r = g.score_token(junk)
        check(0 <= r["fit"] <= 100, f"junk input survives ({r['fit']})")


def test_ranking_resolution():
    """Near-identical tokens must still be rankable, not tied."""
    print("\n[ranking] ramps give finer separation than the ladders")
    toks = [dict(RAKO, a=f"t{i}", smt=8 + i) for i in range(5)]
    rows = sorted((g.score_token(t) for t in toks),
                  key=lambda r: -r["fit_exact"])
    exacts = [r["fit_exact"] for r in rows]
    check(len(set(exacts)) == len(exacts),
          f"5 tokens 1 smart wallet apart get 5 distinct scores: "
          f"{[round(x, 1) for x in exacts]}")
    check(exacts == sorted(exacts, reverse=True), "sorted descending")


if __name__ == "__main__":
    test_no_cliffs()
    test_rako_regression()
    test_monotonic()
    test_calibration_preserved()
    test_bounds_and_types()
    test_ranking_resolution()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for f in failures:
        print("  -", f)
    sys.exit(1 if failures else 0)
