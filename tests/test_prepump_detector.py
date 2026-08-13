# -*- coding: utf-8 -*-
"""Offline tests for the 4-pillar pre-pump detector.

Success fixtures (Ansem, Punch, Assface) must PASS all four pillars.
Trap fixtures (Callcat, Froge) must FAIL as STEALTH DUMP.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cvd_daily as daily
from cvd_daily import (aggregate_chunks_to_daily, calculate_daily_cvd,
                       chunk_key, save_4h_chunks_from_swaps,
                       swaps_from_4h_chunks, upsert_4h_chunk)
from prepump_detector import (BUY_TX_MIN_PCT, BUY_TX_RED_FLAG_PENALTY,
                              BUY_TX_RED_FLAG_PCT, BUY_TX_SCORE_FULL_PCT,
                              CVD_ABSORPTION_PCT, GOLDEN_TOTAL,
                              GOLDEN_WEIGHTS, STEALTH_BUY_TX_MAX,
                              VERDICT_EMAS, VERDICT_FAIL, VERDICT_PASS,
                              VERDICT_STEALTH, _is_absorbed_expansion,
                              _is_ignition_row, compute_window_metrics,
                              evaluate_golden_checks, evaluate_pillar1_flow,
                              evaluate_pillar2_participation,
                              evaluate_prepump, find_ignition, golden_score,
                              is_setup_emas, is_stealth_dump, metrics_for_day)

failures = []

# 2024-01-01 00:00 UTC and the two following days.
DAY0 = 1_704_067_200
DAY1 = DAY0 + 86400
DAY2 = DAY0 + 2 * 86400


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _swaps(spec, day_ts):
    """Build (side, sol, ts, wallet) rows from ``[(side, sol, n), ...]``."""
    rows = []
    offset = 60
    for i, (side, sol, n) in enumerate(spec):
        for j in range(n):
            rows.append((
                side, float(sol),
                day_ts + offset + i * 30 + j * 20,
                f"{side}{i}_{j}",
            ))
    return rows


def _ignition_swaps(day_ts, *, n_buy=20, buy_sol=0.40,
                    n_sell=8, sell_sol=0.20):
    """Cluster in the first 15 minutes of ``day_ts``."""
    rows = []
    for i in range(n_buy):
        rows.append(("buy", buy_sol, day_ts + 30 + i * 20, f"igb{i}"))
    for i in range(n_sell):
        rows.append(("sell", sell_sol, day_ts + 40 + i * 25, f"igs{i}"))
    return rows


def fixture_ansem():
    """Classic absorption + LPS + ignition (all 4 PASS)."""
    day0 = _swaps([("buy", 1.0, 50), ("sell", 1.0, 50)], DAY0)
    # Day 1: vol ~37.5 vs 100 = -62.5%, |CVD| 0.27%, buy TX 60%,
    # avg sell 0.348 > avg buy 0.231, whale net seller.
    day1 = _swaps([
        ("buy", 0.22, 80),
        ("buy", 1.10, 1),
        ("sell", 0.28, 50),
        ("sell", 1.20, 4),
    ], DAY1)
    day2 = _ignition_swaps(DAY2)
    return day0 + day1 + day2, 55.0


def fixture_punch():
    """Sleeper LPS: even drier volume, still absorbed."""
    day0 = _swaps([("buy", 1.2, 40), ("sell", 1.2, 40)], DAY0)
    # Day 1: vol ~26.95 vs 96 = -71.9%, |CVD| 1.30%, buy TX 57.7%.
    day1 = _swaps([
        ("buy", 0.18, 70),
        ("buy", 1.05, 1),
        ("sell", 0.22, 50),
        ("sell", 1.15, 2),
    ], DAY1)
    day2 = _ignition_swaps(DAY2, n_buy=18, buy_sol=0.45, n_sell=6,
                           sell_sol=0.18)
    return day0 + day1 + day2, 45.0


def fixture_assface():
    """Strong accumulation: buy TX 61%, absorption ~2%."""
    day0 = _swaps([("buy", 0.9, 55), ("sell", 0.9, 55)], DAY0)
    day1 = _swaps([
        ("buy", 0.20, 90),
        ("buy", 1.05, 2),
        ("sell", 0.30, 55),
        ("sell", 1.10, 3),
    ], DAY1)
    day2 = _ignition_swaps(DAY2, n_buy=22, buy_sol=0.38, n_sell=7,
                           sell_sol=0.15)
    return day0 + day1 + day2, 62.0


def fixture_callcat():
    """Retail FOMO big buys + insider dribble sells = stealth dump."""
    day0 = _swaps([("buy", 1.0, 30), ("sell", 1.0, 30)], DAY0)
    day1 = _swaps([
        ("buy", 1.50, 40),
        ("sell", 0.90, 55),
    ], DAY1)
    return day0 + day1, 18.0


def fixture_froge():
    """Same trap, even more lopsided retail size."""
    day0 = _swaps([("buy", 0.8, 25), ("sell", 0.8, 25)], DAY0)
    day1 = _swaps([
        ("buy", 2.20, 35),
        ("sell", 0.70, 50),
    ], DAY1)
    return day0 + day1, 12.0


def _setup_tmp_chunks():
    tmp = tempfile.mkdtemp()
    orig = daily.CHUNK_DIR
    daily.CHUNK_DIR = tmp
    return orig, tmp


def test_absorption_formula():
    print("\n[1] Pilar 1 absorption formula")
    m = compute_window_metrics([
        ("buy", 10.0, DAY1, "a"),
        ("sell", 10.2, DAY1 + 1, "b"),
    ])
    check(abs(m["absorption_pct"] - 0.990) < 0.02,
          f"abs(delta)/vol ≈ 0.99% (got {m['absorption_pct']:.3f})")
    p1 = evaluate_pillar1_flow(m)
    check(p1["passed"] is True, "0.99% < 3.0% is PASS")
    fat = compute_window_metrics([
        ("buy", 20.0, DAY1, "a"),
        ("sell", 10.0, DAY1 + 1, "b"),
    ])
    check(fat["absorption_pct"] > CVD_ABSORPTION_PCT,
          f"unbalanced flow {fat['absorption_pct']:.1f}% fails P1")
    check(evaluate_pillar1_flow(fat)["passed"] is False, "P1 FAIL when ≥ 3%")


def test_stealth_dump_filter():
    print("\n[2] Pilar 2 stealth-dump trap")
    trap = compute_window_metrics([
        ("buy", 1.5, DAY1 + i, f"b{i}") for i in range(40)
    ] + [
        ("sell", 0.9, DAY1 + 100 + i, f"s{i}") for i in range(55)
    ])
    check(trap["buy_tx_pct"] < STEALTH_BUY_TX_MAX,
          f"buy TX {trap['buy_tx_pct']:.1f}% < stealth gate "
          f"{STEALTH_BUY_TX_MAX:g}")
    check(trap["avg_buy_sol"] >= trap["avg_sell_sol"],
          "avg buy >= avg sell")
    check(is_stealth_dump(trap) is True, "trap filter fires")
    p2 = evaluate_pillar2_participation(trap)
    check(p2["passed"] is False and p2["stealth_dump"] is True,
          "P2 FAIL + stealth_dump flag")


def test_success_tokens_pass():
    print("\n[3] Success tokens PASS (Ansem, Punch, Assface)")
    for name, builder in (
        ("Ansem", fixture_ansem),
        ("Punch", fixture_punch),
        ("Assface", fixture_assface),
    ):
        swaps, lock = builder()
        ev = evaluate_prepump(
            swaps, holder_lock_pct=lock, now_ts=DAY2 + 3600,
            include_today=True)
        m = ev["metrics"]
        check(ev["verdict"] == VERDICT_EMAS,
              f"{name} verdict SETUP EMAS (got {ev['verdict']} "
              f"{ev['passed']}/{ev.get('total')} "
              f"stealth={ev['stealth_dump']})")
        check(ev["passed"] == GOLDEN_TOTAL,
              f"{name} all {GOLDEN_TOTAL} golden checks green")
        check(ev.get("setup_emas") is True, f"{name} setup_emas flag")
        check(is_setup_emas(ev) is True, f"{name} is_setup_emas")
        check(m["absorption_pct"] < 3.0,
              f"{name} absorption {m['absorption_pct']:.2f}% < 3")
        check(m["buy_tx_pct"] >= BUY_TX_MIN_PCT,
              f"{name} buy TX {m['buy_tx_pct']:.1f}% "
              f"≥ {BUY_TX_MIN_PCT:g}")
        check(abs(m["buy_tx_pct"] + m["sell_tx_pct"] - 100.0) < 0.01,
              f"{name} buy+sell TX % = 100")
        check(m["avg_sell_sol"] > m["avg_buy_sol"],
              f"{name} avg sell {m['avg_sell_sol']:.3f} > "
              f"buy {m['avg_buy_sol']:.3f}")
        check(ev["stealth_dump"] is False, f"{name} is not a stealth dump")


def test_trap_tokens_fail():
    print("\n[4] Trap tokens FAIL (Callcat, Froge)")
    for name, builder in (
        ("Callcat", fixture_callcat),
        ("Froge", fixture_froge),
    ):
        swaps, lock = builder()
        ev = evaluate_prepump(
            swaps, holder_lock_pct=lock, now_ts=DAY1 + 3600,
            include_today=True)
        check(ev["verdict"] == VERDICT_STEALTH,
              f"{name} verdict STEALTH DUMP (got {ev['verdict']})")
        check(ev["stealth_dump"] is True, f"{name} stealth_dump flag")
        check(ev["pillars"][0]["passed"] is False
              or ev["pillars"][1]["passed"] is False,
              f"{name} fails P1 or P2")
        check(ev["verdict"] != VERDICT_EMAS, f"{name} must not be SETUP EMAS")
        check(is_setup_emas(ev) is False, f"{name} is_setup_emas False")
        check(ev["verdict"] != VERDICT_FAIL or ev["stealth_dump"],
              f"{name} labelled as trap, not a generic fail-only")


def test_lps_and_ignition_helpers():
    print("\n[5] LPS daily status + ignition finder")
    swaps, lock = fixture_ansem()
    rows = calculate_daily_cvd(swaps)
    check(len(rows) >= 2, "at least two UTC days")
    setup = rows[1]
    check(setup["volume_change_pct"] <= -40.0,
          f"LPS drop {setup['volume_change_pct']}")
    check(setup["status"].startswith("KERING")
          or abs(setup["cvd_ratio_pct"]) < 3.0,
          f"setup day status {setup['status']}")
    hit = find_ignition(swaps, dry_hourly_sol=setup["volume_sol"] / 24.0,
                        after_ts=DAY2)
    check(hit is not None, "ignition candle found on day 2")
    check(hit["buy_tx_pct"] >= 55.0, f"ignition buy {hit['buy_tx_pct']:.1f}%")
    check(hit["delta_sol"] > 0, "ignition net delta positive")


def test_metrics_for_day_isolation():
    print("\n[6] metrics_for_day does not leak other days")
    swaps, _ = fixture_ansem()
    m0 = metrics_for_day(swaps, "2024-01-01")
    m1 = metrics_for_day(swaps, "2024-01-02")
    check(abs(m0["volume_sol"] - 100.0) < 1e-6,
          f"day0 volume 100 (got {m0['volume_sol']})")
    check(m1["volume_sol"] < 50,
          f"day1 is the dry day (vol {m1['volume_sol']:.1f})")
    check(m1["buy_tx"] == 81, f"day1 buy tx 81 (got {m1['buy_tx']})")


def test_4h_chunk_roundtrip():
    print("\n[7] 4-hour chunk persist + daily aggregate")
    orig, tmp = _setup_tmp_chunks()
    try:
        swaps, _ = fixture_ansem()
        doc = save_4h_chunks_from_swaps("CA_ANSEM", swaps, symbol="ANSEM")
        check(len(doc["chunks"]) >= 3, "several 4h windows stored")
        key = chunk_key(DAY1 + 100)
        check(key in doc["chunks"], f"day1 chunk {key} present")
        restored = swaps_from_4h_chunks("CA_ANSEM", days=7,
                                        now_ts=DAY2 + 8000)
        check(len(restored) == len(swaps),
              f"roundtrip {len(restored)} == {len(swaps)}")
        daily_rows = aggregate_chunks_to_daily(
            "CA_ANSEM", days=7, now_ts=DAY2 + 8000)
        direct = calculate_daily_cvd(swaps)
        check(len(daily_rows) == len(direct), "aggregated days match")
        check(abs(daily_rows[-1]["volume_sol"] - direct[-1]["volume_sol"])
              < 1e-6, "last-day volume matches after aggregate")
        # Incremental upsert does not duplicate.
        upsert_4h_chunk("CA_ANSEM", swaps[:5], symbol="ANSEM")
        again = swaps_from_4h_chunks("CA_ANSEM")
        check(len(again) == len(swaps),
              "re-upsert does not duplicate swaps")
    finally:
        daily.CHUNK_DIR = orig


def test_include_today_flag():
    print("\n[8] include_today vs complete-day scoring")
    swaps, lock = fixture_ansem()
    # Digest at DAY2 01:07 UTC — day 2 is still running.
    now_ts = DAY2 + 4020
    live = evaluate_prepump(
        swaps, holder_lock_pct=lock, now_ts=now_ts, include_today=True)
    digest = evaluate_prepump(
        swaps, holder_lock_pct=lock, now_ts=now_ts, include_today=False)
    # Ignition prints on 2024-01-03 must not replace the LPS setup day.
    check(live["date"] == "2024-01-02",
          f"live UI scores the setup day, not ignition ({live['date']})")
    check(digest["date"] == "2024-01-02",
          f"daily digest uses complete setup day ({digest['date']})")
    check(live["pillars"][3]["passed"] is True,
          "live eval still sees the ignition candle on day 3")


def test_kpi_cards_shape():
    print("\n[9] KPI cards match glowing PASS/FAIL")
    swaps, lock = fixture_ansem()
    ev = evaluate_prepump(
        swaps, holder_lock_pct=lock, now_ts=DAY2 + 3600)
    cards = ev["kpi"]
    check(len(cards) == 4, "exactly 4 KPI cards")
    check(cards[0]["id"] == "absorption" and cards[0]["passed"],
          "card 1 absorption PASS")
    check(cards[1]["id"] == "buy_tx" and cards[1]["passed"],
          "card 2 buy TX PASS")
    check(cards[2]["id"] == "order_size" and cards[2]["passed"],
          "card 3 order size PASS")
    check(cards[3]["id"] == "lps" and cards[3]["passed"],
          "card 4 LPS/ignition PASS")
    trap, _ = fixture_callcat()
    bad = evaluate_prepump(trap, now_ts=DAY1 + 3600)
    check(bad["kpi"][2]["passed"] is False,
          "Callcat order-size card is FAIL / stealth")


def test_golden_checks_lps_band_and_score():
    print("\n[10] Setup Emas 7 checks + LPS band + score")
    swaps, lock = fixture_ansem()
    ev = evaluate_prepump(
        swaps, holder_lock_pct=lock, now_ts=DAY2 + 3600)
    checks = {c["id"]: c for c in ev["checks"]}
    check(len(ev["checks"]) == 7, "exactly 7 golden checks")
    check(all(c["passed"] for c in ev["checks"]), "Ansem 7/7 pass")
    # Perfect tape = sum of positive weights (95), not 100.
    check(ev["score"] == 95, f"Ansem score 95 (got {ev['score']})")
    check(GOLDEN_WEIGHTS["p3_lock"] == 0, "p3_lock is display-only")
    check(GOLDEN_WEIGHTS["p1_absorption"] + GOLDEN_WEIGHTS["p1_cvd_flat"]
          == 35, "P1 family stays inside the 35-point budget")
    # Extreme dry (−90%) is dead tape, not LPS.
    m = ev["metrics"].copy()
    m["volume_change_pct"] = -90.0
    dry = evaluate_golden_checks(m, ev["usable_rows"], lock)
    lps = next(c for c in dry if c["id"] == "p3_lps")
    check(lps["passed"] is False, "−90% vol is outside LPS band")
    # Missing lock still fails the display check, but weight 0 so score
    # is unchanged (tautological Top-N lock is not a scored pillar).
    no_lock = evaluate_golden_checks(ev["metrics"], ev["usable_rows"], None)
    lock_chk = next(c for c in no_lock if c["id"] == "p3_lock")
    check(lock_chk["passed"] is False, "missing lock fails P3 retention")
    check(golden_score(no_lock) == golden_score(ev["checks"]),
          "p3_lock does not change the numeric score")
    check(is_setup_emas({"verdict": "WATCH", "passed": 6, "total": 7,
                         "date": "2024-01-02"}) is False,
          "WATCH 6/7 is not Setup Emas")


def test_absorbed_expansion_and_sisypuss():
    print("\n[11] Absorbed expansion + SISYPUSS 10 Agu is Setup Emas")
    # Vol +146%, CVD down, tight tape → setup, not ignition.
    row = {
        "date": "2026-08-10",
        "volume_change_pct": 146.63,
        "delta_sol": -9.66,
        "volume_sol": 902.77,
        "absorption_pct": 1.07,
        "cvd_ratio_pct": -1.07,
        "buy_tx_pct": 49.72,
    }
    check(_is_absorbed_expansion(146.63, row=row) is True,
          "SISYPUSS +146% / CVD down is absorbed expansion")
    check(_is_ignition_row(row) is False,
          "absorbed expansion is not scored as ignition")
    markup = dict(row, delta_sol=20.0, absorption_pct=8.0,
                  cvd_ratio_pct=8.0, buy_tx_pct=62.0)
    check(_is_ignition_row(markup) is True,
          "vol +100% with CVD up stays ignition")

    # Near-even tape (49.7%) must pass the new 49% floor.
    m = {
        "buy_tx": 541, "sell_tx": 547, "total_tx": 1088,
        "buy_tx_pct": 49.72, "sell_tx_pct": 50.28,
        "buy_sol": 446.56, "sell_sol": 456.22,
        "volume_sol": 902.77, "delta_sol": -9.66,
        "absorption_pct": 1.07,
        "avg_buy_sol": 0.825, "avg_sell_sol": 0.834,
        "whale_net_sol": -12.27,
        "volume_change_pct": 146.63,
    }
    daily = [
        {"date": "2026-08-09", "running_cvd_sol": -3.86,
         "volume_change_pct": None, "delta_sol": -3.86,
         "volume_sol": 366.0, "cvd_ratio_pct": -1.05},
        {"date": "2026-08-10", "running_cvd_sol": -13.51,
         "volume_change_pct": 146.63, "delta_sol": -9.66,
         "volume_sol": 902.77, "cvd_ratio_pct": -1.07},
    ]
    raw = evaluate_golden_checks(m, daily, 100.0)
    checks = {c["id"]: c for c in raw}
    check(checks["p2_buy_tx"]["passed"] is True,
          f"49.7% buy TX passes {BUY_TX_MIN_PCT:g}% floor")
    check(checks["p2_buy_tx"].get("score_override") == 0,
          "49.7% buy TX is the neutral 48–52 band (score 0)")
    check(checks["p3_lps"]["passed"] is True,
          "P3 passes on absorbed expansion")
    check(checks["p1_cvd_flat"]["passed"] is True,
          "P1 divergence passes when vol up + CVD down")
    check(all(c["passed"] for c in checks.values()),
          "synthetic SISYPUSS 10 Agu is 7/7")
    check(golden_score(raw) == 80,
          f"SISYPUSS 49.7% buy TX scores 80 (95-15, got {golden_score(raw)})")

    ca = "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump"
    cvd_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cvd.json")
    if os.path.exists(cvd_path):
        import json
        from datetime import datetime, timezone
        with open(cvd_path, encoding="utf-8") as f:
            rec = (json.load(f) or {}).get(ca) or {}
        swaps = rec.get("swaps") or []
        if swaps:
            now_ts = int(datetime(
                2026, 8, 11, 0, 5, tzinfo=timezone.utc).timestamp())
            ev = evaluate_prepump(
                swaps, holder_lock_pct=100.0, now_ts=now_ts,
                include_today=False)
            check(ev["date"] == "2026-08-10",
                  f"digest 11 Agu scores 10 Agu (got {ev['date']})")
            check(ev["verdict"] == VERDICT_EMAS,
                  f"SISYPUSS 10 Agu SETUP EMAS "
                  f"(got {ev['verdict']} {ev['passed']}/7 "
                  f"stealth={ev['stealth_dump']})")
            check(is_setup_emas(ev) is True,
                  "SISYPUSS 10 Agu would notify")
        else:
            check(True, "cvd.json has no SISYPUSS swaps — skip live replay")
    else:
        check(True, "cvd.json missing — skip live replay")


def _tape_metrics(buy_pct, **extra):
    """Near-even absorbed LPS tape with an overrideable buy-TX share."""
    m = {
        "buy_tx": 50, "sell_tx": 50, "total_tx": 100,
        "buy_tx_pct": buy_pct, "sell_tx_pct": 100.0 - buy_pct,
        "buy_sol": 10.0, "sell_sol": 12.0,
        "volume_sol": 22.0, "delta_sol": -2.0,
        "absorption_pct": 1.0,
        "avg_buy_sol": 0.20, "avg_sell_sol": 0.24,
        "whale_net_sol": -1.0,
        "volume_change_pct": -50.0,
    }
    m.update(extra)
    return m


def test_asymmetric_buy_tx_scoring():
    print("\n[12] Asymmetric p2_buy_tx scoring + p3_lock weight 0")
    daily = [
        {"date": "2024-01-01", "running_cvd_sol": -2.0,
         "volume_sol": 40.0, "delta_sol": 0.0},
        {"date": "2024-01-02", "running_cvd_sol": -1.5,
         "volume_change_pct": -50.0, "volume_sol": 22.0,
         "delta_sol": -2.0, "cvd_ratio_pct": -9.0},
    ]
    full = evaluate_golden_checks(_tape_metrics(55.0), daily, 80.0)
    mid = evaluate_golden_checks(_tape_metrics(50.0), daily, 80.0)
    flag = evaluate_golden_checks(_tape_metrics(45.0), daily, 80.0)
    by_full = {c["id"]: c for c in full}
    by_mid = {c["id"]: c for c in mid}
    by_flag = {c["id"]: c for c in flag}
    check(by_full["p2_buy_tx"]["passed"] is True
          and by_full["p2_buy_tx"]["score_override"]
          == GOLDEN_WEIGHTS["p2_buy_tx"],
          f">= {BUY_TX_SCORE_FULL_PCT:g}% earns full +15")
    check(by_mid["p2_buy_tx"]["passed"] is True
          and by_mid["p2_buy_tx"]["score_override"] == 0,
          "48–52% buy TX is netral (cek lulus, skor 0)")
    check(by_flag["p2_buy_tx"]["passed"] is False
          and by_flag["p2_buy_tx"]["score_override"]
          == BUY_TX_RED_FLAG_PENALTY,
          f"< {BUY_TX_RED_FLAG_PCT:g}% is the −20 red flag")
    check(golden_score(full) == 95, f"full tape scores 95 (got {golden_score(full)})")
    check(golden_score(mid) == 80, f"neutral buy TX scores 80 (got {golden_score(mid)})")
    check(golden_score(flag) == 60,
          f"red-flag buy TX scores 60 (80-20, got {golden_score(flag)})")
    locked = evaluate_golden_checks(_tape_metrics(55.0), daily, 90.0)
    unlocked = evaluate_golden_checks(_tape_metrics(55.0), daily, 10.0)
    check(golden_score(locked) == golden_score(unlocked) == 95,
          "holder lock cannot move the numeric score")
    check(STEALTH_BUY_TX_MAX == 52.0,
          "stealth verdict gate stays at 52% (wider than the 48% red flag)")


if __name__ == "__main__":
    test_absorption_formula()
    test_stealth_dump_filter()
    test_success_tokens_pass()
    test_trap_tokens_fail()
    test_lps_and_ignition_helpers()
    test_metrics_for_day_isolation()
    test_4h_chunk_roundtrip()
    test_include_today_flag()
    test_kpi_cards_shape()
    test_golden_checks_lps_band_and_score()
    test_absorbed_expansion_and_sisypuss()
    test_asymmetric_buy_tx_scoring()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for item in failures:
        print("  -", item)
    sys.exit(1 if failures else 0)
