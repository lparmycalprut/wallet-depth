# -*- coding: utf-8 -*-
"""Tests for accum_history (full-lifetime accumulation scanner).

Covers (all synthetic, no network — the sandbox blocks crypto API egress):
  * per-phase scoring ladders (identical thresholds to page 9)
  * full window scoring incl. estimated historical thin liquidity
  * MEMIPEDE-like event: spike 30 Jul 2026 16:00 UTC must be detected
  * rolling scan: event windows become candidates, quiet days do not
  * merge of adjacent windows (max score, union of phase hits)
  * edge cases: empty input, brand-new pair, no swap data, GMGN failure
  * candle pagination (before_timestamp walking, page cap, dedupe)

Run with:  python tests/test_accum_history.py   (no pytest, no network)
"""

import datetime as _dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import accum_history as ah  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def utc(y, m, d, h=0):
    """Unix seconds for a UTC datetime."""
    return int(_dt.datetime(y, m, d, h, tzinfo=_dt.timezone.utc).timestamp())


H = 3600
SOL_PRICE = 100.0

# MEMIPEDE-like timeline (pair created 2026-07-20 00:00 UTC).
CREATED = utc(2026, 7, 20)
EVENT_HOUR = utc(2026, 7, 30, 16)      # spike: hourly volume ~$16.6K
NOW = utc(2026, 8, 4)


def _candle(ts, close, vol, base=1e-6):
    """One hourly candle; price oscillates slightly around ``close``."""
    return {"ts": ts, "o": close * 0.99, "h": close * 1.05,
            "l": close * 0.95, "c": close, "v": vol}


def _mk_candles():
    """15 days of hourly candles: quiet base, ramp, spike, markup, decay.

    Price path (USD): 1.0e-6 base → 1.3e-6 pre-spike → 1.5e-6 spike hour →
    3.0e-6 markup → decay to 2.4e-6 now.
    """
    out = []
    ts = CREATED
    while ts < NOW:
        age_h = (ts - CREATED) / H
        if ts < utc(2026, 7, 28):            # quiet launch phase
            close, vol = 1.0e-6, 50.0
        elif ts < EVENT_HOUR:                # slow accumulation ramp
            ramp = (ts - utc(2026, 7, 28)) / H
            close = 1.0e-6 + 0.3e-6 * min(ramp / 60.0, 1.0)
            vol = 200.0 + 1800.0 * min(ramp / 60.0, 1.0)
        elif ts == EVENT_HOUR:               # the big spike
            close, vol = 1.5e-6, 16600.0
        elif ts == EVENT_HOUR + H:           # markup next hour
            close, vol = 3.0e-6, 25000.0
        else:                                # post-pump decay
            decay = min((ts - EVENT_HOUR) / H, 120.0)
            close = max(2.4e-6, 3.0e-6 - 0.6e-6 * decay / 120.0)
            vol = max(300.0, 25000.0 / (1.0 + decay * 0.5))
        out.append(_candle(ts, close, vol))
        ts += H
    return out


def _mk_event_swaps():
    """Swap-level data for the 48h window ending at the spike hour.

    Window [2026-07-28 16:00 UTC, 2026-07-30 16:00 UTC): quiet first 6h,
    growing activity, then two whale buys 1–2h before the spike hour and a
    busy spike hour (120 tx, ~$16.6K, 80 wallets).
    """
    t0 = utc(2026, 7, 28, 16)
    swaps = []
    for h_i in range(40):                    # hours 0..39 of the window
        hour_ts = t0 + h_i * H
        if h_i < 6:                          # quiet test-like start
            n, vol, wallets = 1, 20.0, 1
        elif h_i < 30:                       # slow ramp
            n, vol, wallets = 4 + h_i // 4, 60.0 * (1 + h_i // 3), 3 + h_i // 6
        else:                                # pre-spike build-up
            n, vol, wallets = 14 + (h_i - 30) * 4, 400.0 * (h_i - 28), 10 + (h_i - 30) * 2
        for j in range(n):
            size = vol / n
            side = "buy" if (j % 5) != 3 else "sell"
            swaps.append((side, size / SOL_PRICE, hour_ts + j * 37, f"w-{h_i}-{j}"))
    # Whale entries: $5,000 (50 SOL) 2h before spike, $3,000 (30 SOL) 1h before.
    swaps.append(("buy", 50.0, EVENT_HOUR - 2 * H, "whale-a"))
    swaps.append(("buy", 30.0, EVENT_HOUR - 1 * H, "whale-b"))
    # Spike hour: 120 tx, $16,600, 80 unique wallets.
    for j in range(120):
        side = "buy" if j < 78 else "sell"
        swaps.append((side, 16600.0 / 120.0 / SOL_PRICE, EVENT_HOUR + j * 13,
                      f"spike-{j % 80}"))
    return swaps


# ── Phase 1: Liquidity Test ──────────────────────────────────────────────


def test_phase1_ladder():
    print("\n[phase1] liquidity test ladder (page 9 thresholds)")
    def row(ts, tx, vol):
        return {"hour": ts, "tx_count": tx, "volume_usd": vol,
                "unique_wallets": tx, "buys": tx, "sells": 0,
                "bs_ratio": float("inf")}
    base = utc(2026, 7, 1)
    r = ah.score_phase1_liquidity_test(
        [row(base + i * H, 1, 100.0) for i in range(6)], [])
    check(r["score"] == 15, f"2–6 tx <$1K → 15 (got {r['score']})")
    r = ah.score_phase1_liquidity_test(
        [row(base + i * H, 2, 150.0) for i in range(5)], [])
    check(r["score"] == 10, f"7–15 tx <$2K → 10 (got {r['score']})")
    r = ah.score_phase1_liquidity_test(
        [row(base + i * H, 1, 800.0) for i in range(1)], [])
    check(r["score"] == 5, f"any small start <$5K → 5 (got {r['score']})")
    r = ah.score_phase1_liquidity_test(
        [row(base + i * H, 30, 9000.0) for i in range(6)], [])
    check(r["score"] == 0, f"too large for test → 0 (got {r['score']})")
    # Empty → 0 with a clear detail, never crashes.
    r = ah.score_phase1_liquidity_test([], [])
    check(r["score"] == 0 and "Insufficient" in r["detail"],
          "empty hourly → 0 + insufficient detail")


def test_phase1_candle_bonus():
    print("\n[phase1] tiny-body early candles raise score to 10")
    base = utc(2026, 7, 1)
    rows = [{"hour": base + i * H, "tx_count": 2, "volume_usd": 300.0,
             "unique_wallets": 2, "buys": 2, "sells": 0,
             "bs_ratio": float("inf")} for i in range(6)]
    flat = [{"ts": base + i * H, "o": 1e-6, "h": 1.00001e-6, "l": 0.99999e-6,
             "c": 1.000001e-6, "v": 100.0} for i in range(48)]
    r = ah.score_phase1_liquidity_test(rows, flat)
    check(r["score"] == 10 and "minimal price movement" in r["detail"],
          f"flat candles + small tx → 10 with bonus note (got {r['score']})")


# ── Phase 2: Slow Accumulation ───────────────────────────────────────────


def test_phase2_ladder():
    print("\n[phase2] growth ladder + buy-pressure note")
    base = utc(2026, 7, 1)

    def rows(tx_seq, bs=2.0):
        out = []
        for i, tx in enumerate(tx_seq):
            out.append({"hour": base + i * H, "tx_count": tx,
                        "volume_usd": tx * 50.0, "unique_wallets": tx,
                        "buys": tx, "sells": 0, "bs_ratio": float("inf")})
        return out

    r = ah.score_phase2_slow_accumulation(rows([1] * 16 + [20] * 16))
    check(r["score"] == 20, f"20x growth → 20 (got {r['score']})")
    r = ah.score_phase2_slow_accumulation(rows([2] * 16 + [12] * 16))
    check(r["score"] == 15, f"6x growth → 15 (got {r['score']})")
    r = ah.score_phase2_slow_accumulation(rows([3] * 16 + [8] * 16))
    check(r["score"] == 10, f"~2.7x growth → 10 (got {r['score']})")
    r = ah.score_phase2_slow_accumulation(rows([10] * 16 + [14] * 16))
    check(r["score"] == 5, f"1.4x growth → 5 (got {r['score']})")
    r = ah.score_phase2_slow_accumulation(rows([10] * 16 + [10] * 16))
    check(r["score"] == 0, f"flat → 0 (got {r['score']})")
    r = ah.score_phase2_slow_accumulation(rows([1, 2, 3]))
    check(r["score"] == 0 and "Insufficient" in r["detail"],
          "<4 active hours → 0 + insufficient detail")


# ── Phase 3: Whale Entry ─────────────────────────────────────────────────


def test_phase3_whale_timing():
    print("\n[phase3] whale entry timing ladder")
    base = utc(2026, 7, 1)
    peak = base + 20 * H
    hourly = [{"hour": base + i * H, "tx_count": 10, "volume_usd": 500.0,
               "unique_wallets": 5, "buys": 6, "sells": 4, "bs_ratio": 1.5}
              for i in range(24)]
    hourly[20] = dict(hourly[20], volume_usd=30000.0, tx_count=200,
                      unique_wallets=100)
    # $5,000 whale 2h before peak → 20.
    swaps = [("buy", 50.0, peak - 2 * H, "whale-1"),
             ("buy", 0.1, peak - 2 * H + 10, "retail")]
    r = ah.score_phase3_whale_entry(swaps, hourly, SOL_PRICE)
    check(r["score"] == 20 and "perfect timing" in r["detail"],
          f"$5K whale 2h before spike → 20 (got {r['score']})")
    # $1,500 whale 3h before peak → 15.
    swaps = [("buy", 15.0, peak - 3 * H, "whale-1")]
    r = ah.score_phase3_whale_entry(swaps, hourly, SOL_PRICE)
    check(r["score"] == 15, f"$1.5K whale 3h before → 15 (got {r['score']})")
    # Whale 30h before peak (outside 1–4h window) → 5.
    swaps = [("buy", 50.0, peak - 30 * H, "whale-1")]
    r = ah.score_phase3_whale_entry(swaps, hourly, SOL_PRICE)
    check(r["score"] == 5, f"$5K whale 30h before → 5 (got {r['score']})")
    # No whale → 0, no crash.
    r = ah.score_phase3_whale_entry([], hourly, SOL_PRICE)
    check(r["score"] == 0 and "No swap data" in r["detail"],
          "no swaps → 0 with clear detail")
    r = ah.score_phase3_whale_entry([("buy", 1.0, peak - 2 * H, "x")],
                                    hourly, SOL_PRICE)
    check(r["score"] == 0 and "No whale entry" in r["detail"],
          "swaps below $1K → 0 (got {r['score']})")


# ── Phase 4: Volume Spike ────────────────────────────────────────────────


def test_phase4_ladder():
    print("\n[phase4] volume spike ladder (page 9 thresholds)")

    def rows(peak_tx, peak_vol, peak_w):
        out = [{"hour": base + i * H, "tx_count": 3, "volume_usd": 300.0,
                "unique_wallets": 2, "buys": 2, "sells": 1, "bs_ratio": 2.0}
               for i in range(24)]
        out[12] = {"hour": base + 12 * H, "tx_count": peak_tx,
                   "volume_usd": peak_vol, "unique_wallets": peak_w,
                   "buys": peak_tx, "sells": 0, "bs_ratio": float("inf")}
        return out

    base = utc(2026, 7, 1)
    r = ah.score_phase4_volume_spike(rows(350, 60000, 250))
    check(r["score"] == 25, f"300tx/$50K/200w → 25 (got {r['score']})")
    r = ah.score_phase4_volume_spike(rows(150, 25000, 90))
    check(r["score"] == 20, f"100tx/$20K → 20 (got {r['score']})")
    r = ah.score_phase4_volume_spike(rows(60, 12000, 40))
    check(r["score"] == 15, f"50tx/$10K → 15 (got {r['score']})")
    r = ah.score_phase4_volume_spike(rows(25, 6000, 20))
    check(r["score"] == 10, f"20tx OR $5K → 10 (got {r['score']})")
    r = ah.score_phase4_volume_spike(rows(6, 1500, 5))
    check(r["score"] == 5, f"5tx OR $1K → 5 (got {r['score']})")
    r = ah.score_phase4_volume_spike(rows(2, 300, 2))
    check(r["score"] == 0, f"quiet → 0 (got {r['score']})")
    # Fallback ladder when < 3 active hours.
    few = [{"hour": base + i * H, "tx_count": 2, "volume_usd": 300.0,
            "unique_wallets": 2, "buys": 2, "sells": 0,
            "bs_ratio": float("inf")} for i in range(2)]
    r = ah.score_phase4_volume_spike(few, vol_24h_fallback=60000)
    check(r["score"] == 15, f"24h fallback $60K → 15 (got {r['score']})")


# ── Phase 5: Thin Liquidity ──────────────────────────────────────────────


def test_phase5_ladder():
    print("\n[phase5] thin liquidity ladder (page 9 thresholds)")
    r = ah.score_phase5_thin_liquidity(40000, 400000)
    check(r["score"] == 20, f"liq<$50K & FDV<$500K → 20 (got {r['score']})")
    r = ah.score_phase5_thin_liquidity(80000, 800000)
    check(r["score"] == 15, f"liq<$100K & FDV<$1M → 15 (got {r['score']})")
    r = ah.score_phase5_thin_liquidity(200000, 1500000)
    check(r["score"] == 10, f"liq<$300K & FDV<$2M → 10 (got {r['score']})")
    r = ah.score_phase5_thin_liquidity(450000, 3000000)
    check(r["score"] == 5, f"liq<$500K → 5 (got {r['score']})")
    r = ah.score_phase5_thin_liquidity(600000, 8000000)
    check(r["score"] == 0, f"too liquid → 0 (got {r['score']})")


# ── Full window scoring (MEMIPEDE-like event) ────────────────────────────


def test_score_window_memipede_like_event():
    print("\n[window] MEMIPEDE-like event window (spike 30 Jul 16:00 UTC)")
    candles = _mk_candles()
    swaps = _mk_event_swaps()
    t0 = utc(2026, 7, 28, 16)
    t1 = t0 + 48 * H
    r = ah.score_window(swaps, candles, sol_price=SOL_PRICE, liq_now=45000,
                        fdv_now=189000, price_now=2.4e-6, t0=t0, t1=t1,
                        launch_ts=CREATED)
    check(r["score"] >= 70,
          f"event window scores >= 70 (got {r['score']})")
    check("whale_entry" in r["phase_hits"],
          f"whale_entry is a hit (hits={r['phase_hits']})")
    check("volume_spike" in r["phase_hits"],
          "volume_spike is a hit")
    check("thin_liquidity" in r["phase_hits"],
          "thin_liquidity (estimated) is a hit")
    check(r["estimated"] is True and r["est_liq"] < 50000,
          f"historical window uses estimated liq {r['est_liq']:,.0f}")
    check(r["recommendation"] in ("BUY WATCH", "ACCUMULATING"),
          f"recommendation = {r['recommendation']}")
    check(r["support"]["peak_tx"] == 120 and
          abs(r["support"]["peak_vol_usd"] - 16600) < 1,
          f"support peaks from swap data ({r['support']})")
    check(r["launch_window"] is False, "event window is not the launch window")

    # Same window with current (non-estimated) liquidity values.
    r2 = ah.score_window(swaps, candles, sol_price=SOL_PRICE, liq_now=45000,
                         fdv_now=189000, price_now=2.4e-6, t0=t0, t1=t1,
                         use_current_liq=True, launch_ts=CREATED)
    check(r2["estimated"] is False and r2["est_liq"] == 45000,
          "use_current_liq=True keeps current values")


def test_score_window_quiet_window_is_avoid():
    print("\n[window] quiet pre-launch window scores low (no false signal)")
    candles = _mk_candles()
    t0 = utc(2026, 7, 21)          # quiet days right after launch
    t1 = t0 + 48 * H
    swaps = [("buy", 0.1, t0 + i * H * 3, f"q-{i}") for i in range(20)]
    r = ah.score_window(swaps, candles, sol_price=SOL_PRICE, liq_now=45000,
                        fdv_now=189000, price_now=2.4e-6, t0=t0, t1=t1,
                        launch_ts=CREATED)
    check(r["score"] < 50,
          f"quiet window stays below accumulation bar (got {r['score']})")
    check(r["recommendation"] == "AVOID",
          f"quiet window → AVOID (got {r['recommendation']})")
    check("volume_spike" not in r["phase_hits"],
          "no volume-spike hit on quiet days (no false signal)")


# ── Rolling scan & candidate selection ───────────────────────────────────


def test_rolling_scan_finds_event_not_quiet_days():
    print("\n[scan] rolling 48h scan over 15 days finds the event")
    candles = _mk_candles()
    cands = ah.rolling_scan(candles, liq_now=45000, fdv_now=189000,
                            price_now=2.4e-6, window_h=48, step_h=6,
                            min_score=40, max_candidates=8)
    check(len(cands) >= 1, f"at least one candidate (got {len(cands)})")
    for c in cands:
        check(c["score"] >= 40, f"candidate score >= 40 (got {c['score']})")
    event_t0 = utc(2026, 7, 28)
    event_t1 = utc(2026, 8, 1)
    near_event = [c for c in cands
                  if event_t0 <= c["t0"] <= event_t1]
    check(len(near_event) >= 1,
          f"candidate window starts around 28 Jul–1 Aug (got "
          f"{[(utc_str(c['t0']), c['score']) for c in cands]})")
    false_positives = [c for c in cands if c["t0"] < utc(2026, 7, 26)]
    check(not false_positives,
          f"no candidates on quiet pre-event days (got {len(false_positives)})")
    # The strongest candidate must carry a real volume-spike estimate.
    strongest = max(cands, key=lambda c: c["score"])
    p4 = strongest["phase_scores"]["volume_spike"]["score"]
    check(p4 >= 15, f"strongest candidate has real volume signal p4={p4}")


def test_rolling_scan_empty_and_new_pair():
    print("\n[scan] edge cases: empty candles / pair too new")
    check(ah.rolling_scan([], liq_now=45000, fdv_now=189000,
                          price_now=2.4e-6) == [],
          "empty candles → no candidates")
    # Pair created 2 days ago: 48h window barely fits → scan still safe.
    young = [_candle(CREATED + i * H, 1e-6, 100.0) for i in range(48)]
    cands = ah.rolling_scan(young, liq_now=45000, fdv_now=189000,
                            price_now=2.4e-6, window_h=48, step_h=6)
    check(cands == [], f"quiet young pair → no candidates (got {len(cands)})")


# ── Merge ────────────────────────────────────────────────────────────────


def _fake_result(t0, score, hits):
    return {"t0": t0, "t1": t0 + 48 * H, "score": score, "overall": score,
            "phase_scores": {}, "phase_hits": list(hits),
            "pattern": ah.pattern_from_hits(hits),
            "recommendation": "ACCUMULATING", "estimated": True,
            "est_liq": 20000, "est_fdv": 90000, "launch_window": False,
            "support": {"tx_total": 100, "vol_usd_total": 50000,
                        "unique_wallets": 30, "peak_tx": 50,
                        "peak_vol_usd": 20000, "peak_wallets": 25,
                        "active_hours": 40},
            "n_swaps": 100}


def test_merge_adjacent_and_far():
    print("\n[merge] adjacent windows merge, far ones stay separate")
    a0 = utc(2026, 7, 28, 16)
    a = _fake_result(a0, 55, ["volume_spike", "thin_liquidity"])
    b = _fake_result(a0 + 54 * H, 75, ["whale_entry", "volume_spike",
                                       "thin_liquidity"])  # 6h gap
    far = _fake_result(utc(2026, 6, 1), 60, ["volume_spike"])
    m = ah.merge_windows([a, far, b], gap_h=12)
    check(len(m) == 2, f"2 merged ranges (got {len(m)})")
    merged = [x for x in m if x["t0"] == a0][0]
    check(merged["t1"] == b["t1"], "merged range extends to latest end")
    check(merged["score"] == 75, f"merged score = max (got {merged['score']})")
    check(merged["phase_hits"] == ["thin_liquidity", "volume_spike",
                                   "whale_entry"],
          f"merged hits = union sorted (got {merged['phase_hits']})")
    check(merged["n_windows"] == 2, f"n_windows = 2 (got {merged['n_windows']})")
    check(merged["windows"][0]["score"] == 55, "original windows preserved")


def test_merge_empty_and_single():
    print("\n[merge] empty / single-window edge cases")
    check(ah.merge_windows([]) == [], "empty input → empty output")
    one = _fake_result(utc(2026, 7, 28, 16), 60, ["volume_spike"])
    m = ah.merge_windows([one])
    check(len(m) == 1 and m[0]["n_windows"] == 1,
          "single window stays a single row")


# ── Recommendation & confidence ──────────────────────────────────────────


def test_recommendation_ladder():
    print("\n[rec] page 9 recommendation ladder (exact precedence)")
    check(ah.recommendation(80, ["a", "b", "c", "d"], "FULL", 40000, 400000)
          == "BUY WATCH", ">=75 + FULL → BUY WATCH")
    check(ah.recommendation(55, ["a", "b", "c"], "PARTIAL", 40000, 400000)
          == "ACCUMULATING", ">=50 + 3 hits → ACCUMULATING")
    check(ah.recommendation(65, ["a", "b"], "PARTIAL", 40000, 400000)
          == "ACCUMULATING", ">=60 + PARTIAL → ACCUMULATING")
    # Page 9 checks BUY WATCH before TOO LATE: a FULL pattern wins even when
    # the token is liquid now (identical precedence must be preserved).
    check(ah.recommendation(80, ["a", "b", "c", "d"], "FULL", 600000, 8000000)
          == "BUY WATCH", ">=75 + FULL wins over liq (page 9 precedence)")
    check(ah.recommendation(30, [], "NONE", 600000, 8000000)
          == "TOO LATE", "liq > $500K with no pattern → TOO LATE")
    check(ah.recommendation(30, [], "NONE", 40000, 400000) == "AVOID",
          "low score → AVOID")


def test_window_confidence():
    print("\n[conf] confidence ladder incl. GMGN failure")
    check(ah.window_confidence(80, has_hourly=True, has_candles=True,
                               gmgn_ok=True, gmgn_complete=True,
                               estimated=True) == "HIGH", "80 + complete → HIGH")
    check(ah.window_confidence(55, has_hourly=True, has_candles=True,
                               gmgn_ok=True, gmgn_complete=True,
                               estimated=True) == "MEDIUM", "55 → MEDIUM")
    check(ah.window_confidence(80, has_hourly=True, has_candles=True,
                               gmgn_ok=False, gmgn_complete=False,
                               estimated=True) == "LOW", "GMGN failed → LOW")
    check(ah.window_confidence(55, has_hourly=True, has_candles=True,
                               gmgn_ok=True, gmgn_complete=False,
                               estimated=True) == "LOW",
          "estimated + GMGN partial → LOW")


# ── Candle-only pre-score ────────────────────────────────────────────────


def test_candle_prescore_marks_unverified():
    print("\n[prescore] candle-only score flags wallet phases as unverified")
    candles = _mk_candles()
    # Window that INCLUDES the spike hour (30 Jul 16:00) + markup hour.
    t0 = utc(2026, 7, 29, 0)
    pre = ah.candle_prescore(candles, liq_now=45000, fdv_now=189000,
                             price_now=2.4e-6, t0=t0, t1=t0 + 48 * H)
    check(pre is not None, "prescore exists for event window")
    check(pre["phase_scores"]["whale_entry"]["score"] == 0 and
          pre["phase_scores"]["whale_entry"].get("unverified"),
          "whale_entry unverified (0) in prescore")
    check(pre["phase_scores"]["liquidity_test"].get("unverified"),
          "liquidity_test unverified in prescore")
    check(pre["phase_scores"]["volume_spike"]["score"] >= 15,
          f"volume spike est >= 15 (got {pre['phase_scores']['volume_spike']['score']})")
    check(pre["score"] >= 40, f"pre-score >= 40 → candidate (got {pre['score']})")
    check(ah.candle_prescore([], liq_now=1, fdv_now=1, price_now=1,
                             t0=0, t1=100) is None,
          "no candles in window → None")


# ── Candle pagination (network helper, injectable fetcher) ───────────────


def test_fetch_candles_full_pagination():
    print("\n[paging] backward pagination with before_timestamp")
    all_candles = [_candle(i * H, 1e-6, 100.0) for i in range(2500)]

    def fake_fetcher(pool, timeframe, aggregate, limit, before_ts, timeout):
        assert pool == "pool-x" and timeframe == "hour" and limit == 1000
        if before_ts is None:
            return [c for c in all_candles if 1500 <= c["ts"] // H < 2500]
        if before_ts == 1500 * H - 1:
            return [c for c in all_candles if 500 <= c["ts"] // H < 1500]
        if before_ts == 500 * H - 1:
            return [c for c in all_candles if c["ts"] // H < 500]
        return []

    res = ah.fetch_candles_full("pool-x", timeframe="hour", max_pages=5,
                                until_ts=0, page_fetcher=fake_fetcher)
    check(len(res["candles"]) == 2500, f"all 2500 candles collected (got {len(res['candles'])})")
    check(res["pages"] == 3, f"3 pages walked (got {res['pages']})")
    check(res["complete"] is True, "complete when until_ts reached")
    check(res["candles"][0]["ts"] == 0 and res["candles"][-1]["ts"] == 2499 * H,
          "output ordered oldest → newest")

    # Page cap reached before until_ts → complete=False, partial data kept.
    res = ah.fetch_candles_full("pool-x", timeframe="hour", max_pages=2,
                                until_ts=0, page_fetcher=fake_fetcher)
    check(len(res["candles"]) == 2000 and res["complete"] is False,
          f"page cap → partial + complete=False (got {len(res['candles'])}, {res['complete']})")

    # Empty first page → empty history, complete.
    res = ah.fetch_candles_full("pool-x", page_fetcher=lambda *a, **k: [])
    check(res["candles"] == [] and res["complete"] is True,
          "empty API → empty result + complete")

    # Boundary duplicates are deduped.
    def dup_fetcher(pool, timeframe, aggregate, limit, before_ts, timeout):
        if before_ts is None:
            return [_candle(10 * H, 1e-6, 1.0), _candle(11 * H, 1e-6, 1.0)]
        if before_ts == 10 * H - 1:
            return [_candle(10 * H, 1e-6, 1.0), _candle(9 * H, 1e-6, 1.0)]
        return []
    res = ah.fetch_candles_full("pool-x", max_pages=3, page_fetcher=dup_fetcher)
    check(len(res["candles"]) == 3, f"duplicate boundary candle deduped (got {len(res['candles'])})")


# ── Hourly aggregation helpers ───────────────────────────────────────────


def test_build_hourly_from_swaps():
    print("\n[hourly] swap → hourly aggregation (page 9 semantics)")
    base = utc(2026, 7, 28, 16)
    swaps = [("buy", 1.0, base + 60, "a"),
             ("sell", 2.0, base + 120, "b"),
             ("buy", 0.5, base + 3600 + 10, "a"),
             ("BUY", 0.5, base + 3600 + 20, "c")]
    rows = ah.build_hourly_from_swaps(swaps, SOL_PRICE)
    check(len(rows) == 2, f"2 active hours (got {len(rows)})")
    r0, r1 = rows[0], rows[1]
    check(r0["tx_count"] == 2 and r0["buys"] == 1 and r0["sells"] == 1,
          f"hour 0 counts (got {r0})")
    check(r0["bs_ratio"] == 1.0, "bs_ratio = buys/sells")
    check(r1["bs_ratio"] == float("inf"), "no sells → inf bs_ratio")
    check(abs(r1["volume_usd"] - 100.0) < 1e-9, "volume_usd = sol × price")
    check(r0["unique_wallets"] == 2, "unique wallets per hour")
    check(ah.build_hourly_from_swaps([], SOL_PRICE) == [],
          "empty swaps → empty rows")
    check(ah.build_hourly_from_swaps([("buy", 1.0)], SOL_PRICE) == [],
          "malformed swap skipped")


def utc_str(ts):
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    test_phase1_ladder()
    test_phase1_candle_bonus()
    test_phase2_ladder()
    test_phase3_whale_timing()
    test_phase4_ladder()
    test_phase5_ladder()
    test_score_window_memipede_like_event()
    test_score_window_quiet_window_is_avoid()
    test_rolling_scan_finds_event_not_quiet_days()
    test_rolling_scan_empty_and_new_pair()
    test_merge_adjacent_and_far()
    test_merge_empty_and_single()
    test_recommendation_ladder()
    test_window_confidence()
    test_candle_prescore_marks_unverified()
    test_fetch_candles_full_pagination()
    test_build_hourly_from_swaps()
    print()
    if failures:
        print(f"{len(failures)} FAILURES:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("ALL PASSED")
