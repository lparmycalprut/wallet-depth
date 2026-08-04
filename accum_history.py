# -*- coding: utf-8 -*-
"""Accumulation History — full-lifetime 5-phase accumulation scanner.

Detects historical accumulation windows across the WHOLE life of a Solana
token pair (not just the last 48h like page 9 "Accumulation Detector").

Design contract:
  * Every scoring / scanning / merging function in this module is PURE —
    no Streamlit, no network, no global state.  They can be unit-tested
    offline with synthetic fixtures (see ``tests/test_accum_history.py``).
  * Phase definitions and thresholds mirror ``pages/9_🔍_Accumulation_Detector.py``
    EXACTLY so a historical window is comparable with page 9's live verdict:
      Phase 1 Liquidity Test    (15 pts)
      Phase 2 Slow Accumulation (20 pts)
      Phase 3 Whale Entry       (20 pts)
      Phase 4 Volume Spike      (25 pts)
      Phase 5 Thin Liquidity    (20 pts)
    The only deliberate difference: for historical windows, Phase 5 is
    computed from an ESTIMATED liquidity/FDV (current value scaled by the
    candle price ratio) and is always labelled as an estimate.
  * Phases that need wallet-level data (tx count, unique wallets, whale
    entry, test transactions) cannot be computed from candles alone.  The
    candle-only pre-score marks them "unverified" and the caller verifies
    only candidate windows with GMGN swap fetches.

Candle shape used everywhere: ``{"ts", "o", "h", "l", "c", "v"}`` with
``ts`` = candle OPEN time in unix seconds (GeckoTerminal convention, same
as ``cvd.fetch_candles``).  Swaps are the standard CVD tuple
``(side, sol, ts, wallet)``.
"""

from __future__ import annotations

import requests  # only used by the optional network helpers at the bottom

# ── Tunables (mirror page 9 / task spec) ─────────────────────────────────
WINDOW_H = 48               # rolling window length (hours), same as page 9
SCAN_STEP_H = 6             # rolling scan step (3–6h recommended)
PHASE_HIT_RATIO = 0.5       # a phase "hits" when score >= max * ratio
CANDIDATE_MIN_SCORE = 40    # candle pre-score needed to become a candidate
RESULT_MIN_SCORE = 40       # verified windows below this are not listed
MAX_VERIFY_CANDIDATES = 8   # cap on GMGN-verified windows per scan
VERIFY_MAX_PAGES = 60       # max GMGN pages per candidate window (100/page)
MERGE_GAP_H = 12            # adjacent windows closer than this get merged
MAX_CANDLE_PAGES = 20       # pagination safety cap (1000 candles/page)
CANDLE_PAGE_LIMIT = 1000    # GeckoTerminal max limit per request

PHASES = [
    ("liquidity_test", "Liquidity Test", 15),
    ("slow_accumulation", "Slow Accumulation", 20),
    ("whale_entry", "Whale Entry", 20),
    ("volume_spike", "Volume Spike", 25),
    ("thin_liquidity", "Thin Liquidity", 20),
]
PHASE_MAX = {k: m for k, _n, m in PHASES}

# ── Small pure helpers ───────────────────────────────────────────────────


def ts_floor_hour(ts: int) -> int:
    """Floor a unix timestamp to the top of its hour."""
    return int(ts // 3600) * 3600


def candles_within(candles: list, t0: int, t1: int) -> list:
    """Candles whose OPEN time is within ``[t0, t1)`` (window is half-open)."""
    return [c for c in candles if t0 <= int(c.get("ts", 0)) < t1]


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_hourly_from_swaps(swaps: list, sol_price: float) -> list:
    """Aggregate swap tuples into hourly rows (page 9 semantics).

    Returns a list of dicts, sorted by hour ascending, with keys:
    ``hour`` (unix seconds, floored), ``tx_count``, ``volume_sol``,
    ``volume_usd`` (sol * sol_price), ``unique_wallets``,
    ``buys``, ``sells``, ``bs_ratio`` (buys/sells; ``float("inf")`` when no
    sells).  Only hours that actually contain swaps are present — exactly
    like page 9's ``hourly`` DataFrame.
    """
    buckets = {}
    for swap in swaps:
        if len(swap) < 4:
            continue
        side, sol, ts, wallet = swap[0], _safe_float(swap[1]), int(swap[2]), swap[3]
        hour = ts_floor_hour(ts)
        b = buckets.setdefault(hour, {
            "hour": hour, "tx_count": 0, "volume_sol": 0.0,
            "volume_usd": 0.0, "wallets": set(), "buys": 0, "sells": 0,
        })
        b["tx_count"] += 1
        b["volume_sol"] += sol
        b["volume_usd"] += sol * sol_price
        b["wallets"].add(wallet)
        if str(side).lower() == "buy":
            b["buys"] += 1
        else:
            b["sells"] += 1
    rows = []
    for hour in sorted(buckets):
        b = buckets[hour]
        sells = b["sells"]
        rows.append({
            "hour": hour,
            "tx_count": b["tx_count"],
            "volume_sol": b["volume_sol"],
            "volume_usd": b["volume_usd"],
            "unique_wallets": len(b["wallets"]),
            "buys": b["buys"],
            "sells": sells,
            "bs_ratio": b["buys"] / sells if sells > 0 else float("inf"),
        })
    return rows


def _mean(values) -> float:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def _median(values) -> float:
    values = sorted(v for v in values if v is not None)
    if not values:
        return 0.0
    n = len(values)
    mid = n // 2
    if n % 2:
        return float(values[mid])
    return (values[mid - 1] + values[mid]) / 2.0


def estimate_liq_fdv(liq_now: float, fdv_now: float, price_now: float,
                     candles: list) -> tuple:
    """Estimate historical liquidity/FDV for a window.

    Scaled by the ratio of the window's median candle close to the current
    price (per task spec: "FDV kini discale rasio harga").  Falls back to
    current values when no candle price is usable.  Always an ESTIMATE —
    callers must label it as such.
    """
    if candles and price_now and price_now > 0:
        closes = [_safe_float(c.get("c")) for c in candles]
        med_close = _median(closes)
        if med_close and med_close > 0:
            scale = med_close / price_now
            return liq_now * scale, fdv_now * scale
    return liq_now, fdv_now


# ── Phase scorers (pure, page 9 definitions) ─────────────────────────────


def score_phase1_liquidity_test(hourly_rows: list, candles: list) -> dict:
    """Phase 1 — Liquidity Test (max 15).

    First 6 hours of the window: 2–6 small tx with <$1K volume = classic
    test pattern (15).  7–15 tx <$2K = 10; any small start <$5K = 5.
    Bonus: earliest 3 candles with tiny bodies relative to the window range
    can raise the score to 10 (test-like minimal movement).
    """
    score = 0
    detail = ""
    if len(hourly_rows) >= 1:
        first = hourly_rows[:6]
        total_tx = sum(r["tx_count"] for r in first)
        total_vol = sum(r["volume_usd"] for r in first)
        if 2 <= total_tx <= 6 and total_vol < 1000:
            score = 15
            detail = (
                f"Exactly {total_tx} test transactions in first hours with "
                f"${total_vol:,.0f} total volume — classic liquidity test pattern."
            )
        elif 7 <= total_tx <= 15 and total_vol < 2000:
            score = 10
            detail = (
                f"{total_tx} small transactions in first hours "
                f"(${total_vol:,.0f} volume) — likely test phase."
            )
        elif total_tx > 0 and total_vol < 5000:
            score = 5
            detail = (
                f"Some small early transactions ({total_tx} tx, "
                f"${total_vol:,.0f}) but pattern is unclear."
            )
        else:
            detail = (
                f"No clear test transactions: {total_tx} tx / "
                f"${total_vol:,.0f} in first hours — too large for test phase."
            )

        if len(candles) >= 2:
            first_candles = candles[:3]  # earliest 3 hours of the window
            body_sizes = [abs(_safe_float(c["c"]) - _safe_float(c["o"]))
                          for c in first_candles]
            avg_body = _mean(body_sizes)
            price_range = (max(_safe_float(c["h"]) for c in candles) -
                           min(_safe_float(c["l"]) for c in candles))
            if price_range > 0 and avg_body / price_range < 0.1:
                score = max(score, 10)
                detail += " Early candles show minimal price movement (test-like)."
    else:
        detail = "Insufficient hourly data to detect liquidity test phase."
    return {"score": score, "max": PHASE_MAX["liquidity_test"],
            "detail": detail}


def score_phase2_slow_accumulation(hourly_rows: list) -> dict:
    """Phase 2 — Slow Accumulation (max 20).

    Growth of tx / volume / unique wallets between the first and last third
    of the window: composite >= 10x → 20, >= 5x → 15, >= 2x → 10,
    >= 1.3x → 5.  Buy-pressure / absorption notes mirror page 9.
    """
    score = 0
    detail = ""
    if len(hourly_rows) >= 4:
        n = len(hourly_rows)
        k = max(2, n // 3)
        early, late = hourly_rows[:k], hourly_rows[-k:]

        def _avg(rows, key):
            return _mean([r[key] for r in rows])

        early_tx, late_tx = _avg(early, "tx_count"), _avg(late, "tx_count")
        early_vol, late_vol = _avg(early, "volume_usd"), _avg(late, "volume_usd")
        early_w, late_w = _avg(early, "unique_wallets"), _avg(late, "unique_wallets")

        tx_growth = late_tx / early_tx if early_tx > 0 else 1
        vol_growth = late_vol / early_vol if early_vol > 0 else 1
        wallet_growth = late_w / early_w if early_w > 0 else 1
        composite = max(tx_growth, vol_growth, wallet_growth)

        early_bs = _mean([10.0 if r["bs_ratio"] == float("inf")
                          else r["bs_ratio"] for r in early])
        late_bs = _mean([10.0 if r["bs_ratio"] == float("inf")
                         else r["bs_ratio"] for r in late])

        if composite >= 10:
            score = 20
            detail = (
                f"Clear 10x+ accumulation: tx growth {tx_growth:.1f}x, "
                f"vol growth {vol_growth:.1f}x, wallet growth {wallet_growth:.1f}x. "
                f"Buy/sell ratio: {early_bs:.2f} → {late_bs:.2f}."
            )
        elif composite >= 5:
            score = 15
            detail = (
                f"5x-10x growth detected: tx {tx_growth:.1f}x, "
                f"vol {vol_growth:.1f}x, wallets {wallet_growth:.1f}x. "
                f"B/S ratio: {early_bs:.2f} → {late_bs:.2f}."
            )
        elif composite >= 2:
            score = 10
            detail = (
                f"2x-5x moderate accumulation: tx {tx_growth:.1f}x, "
                f"vol {vol_growth:.1f}x, wallets {wallet_growth:.1f}x."
            )
        elif composite >= 1.3:
            score = 5
            detail = (
                f"Minimal growth: tx {tx_growth:.1f}x, vol {vol_growth:.1f}x, "
                f"wallets {wallet_growth:.1f}x."
            )
        else:
            detail = (
                f"No accumulation phase detected. Growth: tx {tx_growth:.1f}x, "
                f"vol {vol_growth:.1f}x, wallets {wallet_growth:.1f}x."
            )

        if late_bs >= 1.2:
            detail += " Buy pressure dominant (B/S ≥ 1.2)."
        elif early_bs > late_bs and late_bs < 0.8:
            detail += " Sell pressure decreasing — absorption pattern."
    else:
        detail = "Insufficient hourly data for accumulation detection."
    return {"score": score, "max": PHASE_MAX["slow_accumulation"],
            "detail": detail}


def score_phase3_whale_entry(swaps: list, hourly_rows: list,
                             sol_price: float) -> dict:
    """Phase 3 — Whale Entry (max 20).

    Largest single-entry per wallet >= ~$1K, timed 1–4h BEFORE the window's
    peak-volume hour: >=$5K & 0<hbs<=4 → 20; >=$1K & 0<hbs<=4 → 15;
    below $1K → 10; bad timing → 5.  Identical ladder to page 9.
    """
    score = 0
    detail = ""
    if not swaps:
        return {"score": 0, "max": PHASE_MAX["whale_entry"],
                "detail": "No swap data available for whale detection."}

    whale_threshold_sol = 1000 / sol_price if sol_price and sol_price > 0 else 7

    # First big entry per wallet (page 9: groupby wallet, first by ts).
    first_entries = {}
    for swap in swaps:
        if len(swap) < 4:
            continue
        side, sol, ts, wallet = swap[0], _safe_float(swap[1]), int(swap[2]), swap[3]
        if sol < whale_threshold_sol:
            continue
        prev = first_entries.get(wallet)
        if prev is None or ts < prev["first_ts"]:
            first_entries[wallet] = {
                "wallet": wallet, "first_sol": sol, "first_ts": ts,
            }
    whale_txns = sorted(first_entries.values(),
                        key=lambda w: w["first_sol"], reverse=True)[:5]
    if not whale_txns:
        return {"score": 0, "max": PHASE_MAX["whale_entry"],
                "detail": "No whale entry (>$1K single transaction) detected."}

    if hourly_rows:
        peak = max(hourly_rows, key=lambda r: r["volume_usd"])
        peak_hour_epoch = int(peak["hour"])
        for wt in whale_txns:
            wt["hours_before_spike"] = (peak_hour_epoch - wt["first_ts"]) / 3600
        best = min(whale_txns, key=lambda w: abs(w.get("hours_before_spike", 999) - 2))
        hbs = best.get("hours_before_spike", 0)
        amount_usd = best["first_sol"] * sol_price

        if amount_usd >= 5000 and 0 < hbs <= 4:
            score = 20
            detail = (
                f"Whale entry ${amount_usd:,.0f} detected "
                f"{hbs:.1f}h before volume spike — perfect timing pattern."
            )
        elif amount_usd >= 1000 and 0 < hbs <= 4:
            score = 15
            detail = (
                f"Whale entry ${amount_usd:,.0f} detected "
                f"{hbs:.1f}h before volume spike."
            )
        elif amount_usd < 1000:
            score = 10
            detail = (
                f"Possible whale entry ${amount_usd:,.0f} "
                f"but below $1K threshold, or timing unclear ({hbs:.1f}h "
                f"before peak)."
            )
        elif hbs > 4 or hbs < 0:
            score = 5
            detail = (
                f"Whale entry ${amount_usd:,.0f} found but "
                f"timing unclear ({hbs:.1f}h relative to peak)."
            )
        else:
            score = 5
            detail = "Possible whale pattern but unclear."
    else:
        best = whale_txns[0]
        amount_usd = best["first_sol"] * sol_price
        if amount_usd >= 5000:
            score = 10
        elif amount_usd >= 1000:
            score = 5
        detail = (
            f"Whale entry ${amount_usd:,.0f} found but no "
            f"hourly data to confirm timing relative to volume spike."
        )

    # New-wallet note (page 9: minimal prior activity = stronger signal).
    for wt in whale_txns[:3]:
        n_prior = sum(1 for s in swaps
                      if len(s) >= 4 and s[3] == wt["wallet"])
        if n_prior <= 2:
            detail += (f" Wallet {str(wt['wallet'])[:8]}… is new/minimal "
                       f"activity ({n_prior} txs).")
    return {"score": score, "max": PHASE_MAX["whale_entry"],
            "detail": detail}


def score_phase4_volume_spike(hourly_rows: list,
                              vol_24h_fallback: float = 0.0) -> dict:
    """Phase 4 — Volume Spike (max 25).

    Peak hour ladder (page 9): >=300 tx & >=$50K & >=200 wallets → 25;
    >=100 tx & >=$20K → 20; >=50 tx & >=$10K → 15; >=20 tx OR >=$5K → 10;
    >=5 tx OR >=$1K → 5.  Falls back to a 24h-volume ladder when fewer
    than 3 active hours exist.
    """
    score = 0
    detail = ""
    if len(hourly_rows) >= 3:
        peak = max(hourly_rows, key=lambda r: r["volume_usd"])
        peak_tx = int(peak["tx_count"])
        peak_vol = float(peak["volume_usd"])
        peak_wallets = int(peak["unique_wallets"])
        baseline_tx = _median([r["tx_count"] for r in hourly_rows])
        baseline_vol = _median([r["volume_usd"] for r in hourly_rows])

        bs_values = [10.0 if r["bs_ratio"] == float("inf") else r["bs_ratio"]
                     for r in hourly_rows]
        bs_reversal = False
        if len(bs_values) >= 4:
            half = len(bs_values) // 2
            early_bs = _mean(bs_values[:half])
            late_bs = _mean(bs_values[half:])
            bs_reversal = ((early_bs > 1.2 and late_bs < 0.8) or
                           (early_bs < 0.8 and late_bs > 1.2))

        if peak_tx >= 300 and peak_vol >= 50000 and peak_wallets >= 200:
            score = 25
            detail = (
                f"Massive spike: {peak_tx} tx, ${peak_vol:,.0f} volume, "
                f"{peak_wallets} unique wallets in peak hour."
            )
        elif peak_tx >= 100 and peak_vol >= 20000:
            score = 20
            detail = (
                f"Strong spike: {peak_tx} tx, ${peak_vol:,.0f} volume, "
                f"{peak_wallets} wallets in peak hour."
            )
        elif peak_tx >= 50 and peak_vol >= 10000:
            score = 15
            detail = (
                f"Moderate spike: {peak_tx} tx, ${peak_vol:,.0f} volume, "
                f"{peak_wallets} wallets."
            )
        elif peak_tx >= 20 or peak_vol >= 5000:
            score = 10
            detail = (
                f"Moderate activity: {peak_tx} tx, ${peak_vol:,.0f} volume "
                f"in peak hour."
            )
        elif peak_tx >= 5 or peak_vol >= 1000:
            score = 5
            detail = (
                f"Minor spike: {peak_tx} tx, ${peak_vol:,.0f} volume."
            )
        else:
            detail = (
                f"No significant spike detected. Peak: {peak_tx} tx, "
                f"${peak_vol:,.0f} volume."
            )

        if baseline_tx > 0:
            detail += f" ({peak_tx / baseline_tx:.1f}x over median {int(baseline_tx)} tx/h)."
        if baseline_vol > 0:
            detail += f" Volume {peak_vol / baseline_vol:.1f}x over median."
        if bs_reversal:
            detail += " Shakeout pattern detected (B/S ratio reversal)."
    else:
        if vol_24h_fallback >= 50000:
            score = 15
            detail = f"24h volume ${vol_24h_fallback:,.0f} — significant but hourly data unavailable."
        elif vol_24h_fallback >= 10000:
            score = 10
            detail = f"24h volume ${vol_24h_fallback:,.0f} — moderate activity."
        elif vol_24h_fallback >= 1000:
            score = 5
            detail = f"24h volume ${vol_24h_fallback:,.0f} — low activity."
        else:
            detail = f"No hourly data. 24h volume only ${vol_24h_fallback:,.0f}."
    return {"score": score, "max": PHASE_MAX["volume_spike"],
            "detail": detail}


def score_phase5_thin_liquidity(liquidity: float, fdv: float) -> dict:
    """Phase 5 — Thin Liquidity (max 20).

    Page 9 ladder: liq <$50K & FDV <$500K → 20; <$100K & <$1M → 15;
    <$300K & <$2M → 10; liq <$500K → 5; else 0.
    """
    score = 0
    detail = ""
    if liquidity < 50000 and fdv < 500000:
        score = 20
        detail = (
            f"Liquidity ${liquidity:,.0f} (<$50K) + FDV ${fdv:,.0f} (<$500K) — "
            f"very thin, easy to manipulate, high pump potential."
        )
    elif liquidity < 100000 and fdv < 1000000:
        score = 15
        detail = (
            f"Liquidity ${liquidity:,.0f} (<$100K) + FDV ${fdv:,.0f} (<$1M) — "
            f"thin liquidity, good pump potential."
        )
    elif liquidity < 300000 and fdv < 2000000:
        score = 10
        detail = (
            f"Liquidity ${liquidity:,.0f} (<$300K) + FDV ${fdv:,.0f} (<$2M) — "
            f"moderate liquidity."
        )
    elif liquidity < 500000:
        score = 5
        detail = (
            f"Liquidity ${liquidity:,.0f} (<$500K) — somewhat liquid."
        )
    else:
        detail = (
            f"Liquidity ${liquidity:,.0f} (>$500K) — too liquid for easy "
            f"manipulation. Lower pump potential."
        )
    return {"score": score, "max": PHASE_MAX["thin_liquidity"],
            "detail": detail}


def score_phase4_candle_only(candle_rows: list) -> dict:
    """Candle-only Phase 4 estimate (volume data only, no tx/wallet).

    Highest rung justified by hourly volume alone:
      >=$50K → 25 but needs tx >= 300 & wallets >= 200 to confirm
      >=$20K → 20 but needs tx >= 100
      >=$10K → 15 but needs tx >= 50
      >=$5K  → 10 (deterministic: rung is tx>=20 OR vol>=5000)
      >=$1K  → 5  (deterministic: rung is tx>=5 OR vol>=1000)
    The caller must re-score with real swap data before trusting the value.
    """
    peak_vol = max((_safe_float(r["volume_usd"]) for r in candle_rows),
                   default=0.0)
    needs = []
    if peak_vol >= 50000:
        score = 25
        needs = ["tx >= 300", "wallets >= 200"]
    elif peak_vol >= 20000:
        score = 20
        needs = ["tx >= 100"]
    elif peak_vol >= 10000:
        score = 15
        needs = ["tx >= 50"]
    elif peak_vol >= 5000:
        score = 10
    elif peak_vol >= 1000:
        score = 5
    else:
        score = 0
    detail = (
        f"Peak hourly volume ${peak_vol:,.0f} — "
        f"{'perlu verifikasi: ' + ', '.join(needs) + '.' if needs else 'cukup dari volume.'}"
    )
    return {"score": score, "max": PHASE_MAX["volume_spike"],
            "detail": detail, "unverified": bool(needs)}


def score_phase2_candle_proxy(candle_rows: list) -> dict:
    """Candle-only Phase 2 proxy (volume growth only).

    Same ladder as the real Phase 2 but computed from hourly candle volume
    instead of swap tx/wallet counts — an upper-bound proxy used only for
    candidate selection; the verified score replaces it.
    """
    rows = [r for r in candle_rows if _safe_float(r["volume_usd"]) > 0]
    score = 0
    detail = "Insufficient hourly data for accumulation detection."
    if len(rows) >= 4:
        n = len(rows)
        k = max(2, n // 3)
        early_vol = _mean([_safe_float(r["volume_usd"]) for r in rows[:k]])
        late_vol = _mean([_safe_float(r["volume_usd"]) for r in rows[-k:]])
        vol_growth = late_vol / early_vol if early_vol > 0 else 1
        if vol_growth >= 10:
            score = 20
        elif vol_growth >= 5:
            score = 15
        elif vol_growth >= 2:
            score = 10
        elif vol_growth >= 1.3:
            score = 5
        detail = (
            f"Candle volume growth {vol_growth:.1f}x (early→late third) — "
            f"proxy, perlu verifikasi tx/wallet."
        )
    return {"score": score, "max": PHASE_MAX["slow_accumulation"],
            "detail": detail, "unverified": True}


# ── Window scoring (pure) ────────────────────────────────────────────────


def phase_hits(phase_scores: dict) -> list:
    """Keys of phases whose score >= 50% of their max (page 9 rule)."""
    return sorted(k for k, v in phase_scores.items()
                  if v.get("score", 0) >= v.get("max", 1) * PHASE_HIT_RATIO)


def pattern_from_hits(hits: list) -> str:
    """FULL (>=4 hits), PARTIAL (>=2), NONE — page 9 rule."""
    if len(hits) >= 4:
        return "FULL"
    if len(hits) >= 2:
        return "PARTIAL"
    return "NONE"


def recommendation(overall: int, hits: list, pattern: str,
                   liquidity: float, fdv: float) -> str:
    """Page 9 recommendation ladder (identical thresholds)."""
    if overall >= 75 and pattern == "FULL":
        return "BUY WATCH"
    if overall >= 50 and len(hits) >= 3:
        return "ACCUMULATING"
    if overall >= 60 and pattern == "PARTIAL":
        return "ACCUMULATING"
    if liquidity > 500000 or fdv > 5000000:
        return "TOO LATE"
    return "AVOID"


def score_window(swaps: list, candles: list, *, sol_price: float,
                 liq_now: float, fdv_now: float, price_now: float,
                 t0: int, t1: int, use_current_liq: bool = False,
                 launch_ts: int | None = None) -> dict:
    """Full 5-phase score for one 48h window (page 9 definitions).

    ``swaps`` must already be filtered to ``[t0, t1)``.  When
    ``use_current_liq`` is False (historical windows) Phase 5 uses the
    candle-price-scaled ESTIMATE of liquidity/FDV and the result is tagged
    ``estimated=True``.  ``launch_ts`` (pair creation, unix seconds) is only
    used to annotate whether the window covers the token's launch hours.
    """
    wc = candles_within(candles, t0, t1)
    hourly = build_hourly_from_swaps(swaps, sol_price)

    p1 = score_phase1_liquidity_test(hourly, wc)
    p2 = score_phase2_slow_accumulation(hourly)
    p3 = score_phase3_whale_entry(swaps, hourly, sol_price)
    p4 = score_phase4_volume_spike(hourly)
    if use_current_liq:
        est_liq, est_fdv, estimated = liq_now, fdv_now, False
    else:
        est_liq, est_fdv = estimate_liq_fdv(liq_now, fdv_now, price_now, wc)
        estimated = True
    p5 = score_phase5_thin_liquidity(est_liq, est_fdv)

    phase_scores = {"liquidity_test": p1, "slow_accumulation": p2,
                    "whale_entry": p3, "volume_spike": p4,
                    "thin_liquidity": p5}
    overall = sum(v["score"] for v in phase_scores.values())
    hits = phase_hits(phase_scores)
    pattern = pattern_from_hits(hits)
    rec = recommendation(overall, hits, pattern, est_liq, est_fdv)

    peak = max(hourly, key=lambda r: r["volume_usd"]) if hourly else None
    support = {
        "tx_total": sum(r["tx_count"] for r in hourly),
        "vol_usd_total": sum(r["volume_usd"] for r in hourly),
        "unique_wallets": len({s[3] for s in swaps if len(s) >= 4}),
        "peak_tx": int(peak["tx_count"]) if peak else 0,
        "peak_vol_usd": float(peak["volume_usd"]) if peak else 0.0,
        "peak_wallets": int(peak["unique_wallets"]) if peak else 0,
        "active_hours": len(hourly),
    }

    window_is_launch = bool(launch_ts and t0 <= launch_ts < t1)
    return {
        "t0": int(t0), "t1": int(t1),
        "score": overall,
        "overall": overall,
        "phase_scores": phase_scores,
        "phase_hits": hits,
        "pattern": pattern,
        "recommendation": rec,
        "estimated": estimated,
        "est_liq": est_liq, "est_fdv": est_fdv,
        "launch_window": window_is_launch,
        "support": support,
        "n_swaps": len(swaps),
    }


# ── Candle pre-score & rolling scan (pure) ───────────────────────────────


def candle_prescore(candles: list, *, liq_now: float, fdv_now: float,
                    price_now: float, t0: int, t1: int) -> dict | None:
    """Candle-only score for one window (no wallet data needed).

    Returns None when the window has no candles.  Phases needing wallet
    data (1 and 3) are 0 and marked unverified; 2 and 4 are candle proxies.
    Used to rank candidate windows BEFORE spending GMGN quota.
    """
    wc = candles_within(candles, t0, t1)
    if not wc:
        return None
    rows = [{"hour": int(c["ts"]), "volume_usd": _safe_float(c.get("v"))}
            for c in wc]
    p2 = score_phase2_candle_proxy(rows)
    p4 = score_phase4_candle_only(rows)
    est_liq, est_fdv = estimate_liq_fdv(liq_now, fdv_now, price_now, wc)
    p5 = score_phase5_thin_liquidity(est_liq, est_fdv)
    phase_scores = {
        "liquidity_test": {"score": 0, "max": PHASE_MAX["liquidity_test"],
                           "detail": "Belum diverifikasi (butuh data wallet).",
                           "unverified": True},
        "slow_accumulation": p2,
        "whale_entry": {"score": 0, "max": PHASE_MAX["whale_entry"],
                        "detail": "Belum diverifikasi (butuh data wallet).",
                        "unverified": True},
        "volume_spike": p4,
        "thin_liquidity": p5,
    }
    return {
        "t0": int(t0), "t1": int(t1),
        "score": sum(v["score"] for v in phase_scores.values()),
        "phase_scores": phase_scores,
        "phase_hits": phase_hits(phase_scores),
        "est_liq": est_liq, "est_fdv": est_fdv,
        "verified": False,
    }


def _overlap_hours(a0: int, a1: int, b0: int, b1: int) -> float:
    return max(0, min(a1, b1) - max(a0, b0)) / 3600.0


def rolling_scan(candles: list, *, liq_now: float, fdv_now: float,
                 price_now: float, window_h: int = WINDOW_H,
                 step_h: int = SCAN_STEP_H,
                 min_score: int = CANDIDATE_MIN_SCORE,
                 max_candidates: int = MAX_VERIFY_CANDIDATES) -> list:
    """Slide a ``window_h`` window across the whole candle history.

    Returns the best non-redundant candidates (desc by pre-score), each a
    ``candle_prescore`` dict.  A candidate overlapping an already-picked
    one by >= 75% of the window is skipped (redundant fetch); neighbours
    that only partially overlap are kept so the merge step can join them.
    """
    if not candles or window_h <= 0 or step_h <= 0:
        return []
    sorted_c = sorted(candles, key=lambda c: c["ts"])
    start = int(sorted_c[0]["ts"])
    end = int(sorted_c[-1]["ts"]) + 3600
    window_s = window_h * 3600
    overlap_s = window_s * 0.75

    scored = []
    t = start
    while t + window_s <= end:
        pre = candle_prescore(candles, liq_now=liq_now, fdv_now=fdv_now,
                              price_now=price_now, t0=t, t1=t + window_s)
        if pre is not None and pre["score"] >= min_score:
            scored.append(pre)
        t += step_h * 3600

    # Candidate selection heuristic: beyond the raw pre-score, a window must
    # show some REAL accumulation structure (slow-growth proxy OR volume
    # spike estimate).  Thin-liquidity points alone (present in every window
    # of a small token) must not turn quiet days into candidates.
    def _has_signal(w):
        p2 = w["phase_scores"]["slow_accumulation"]["score"]
        p4 = w["phase_scores"]["volume_spike"]["score"]
        return p2 >= 5 or p4 >= 10

    scored = [w for w in scored if _has_signal(w)]
    scored.sort(key=lambda w: w["score"], reverse=True)
    picked = []
    for w in scored:
        if len(picked) >= max_candidates:
            break
        if any(_overlap_hours(w["t0"], w["t1"], p["t0"], p["t1"]) > overlap_s
               for p in picked):
            continue
        picked.append(w)
    picked.sort(key=lambda w: w["t0"])  # chronological for stable UI order
    return picked


# ── Merge (pure) ─────────────────────────────────────────────────────────


def merge_windows(results: list, *, gap_h: float = MERGE_GAP_H) -> list:
    """Merge verified windows that are adjacent or overlapping.

    Gap rule: two windows merge when the next start is within ``gap_h``
    hours of the previous end.  Merged range takes min start / max end,
    the MAXIMUM score, and the union of phase hits (task spec).  The
    original window dicts are kept under ``windows`` for drill-down.
    """
    if not results:
        return []
    ordered = sorted(results, key=lambda r: r["t0"])
    merged = []
    for r in ordered:
        if merged and r["t0"] - merged[-1]["t1"] <= gap_h * 3600:
            prev = merged[-1]
            prev["t0"] = min(prev["t0"], r["t0"])
            prev["t1"] = max(prev["t1"], r["t1"])
            prev["n_windows"] += 1
            prev["phase_hits"] = sorted(set(prev["phase_hits"]) |
                                        set(r["phase_hits"]))
            prev["pattern"] = pattern_from_hits(prev["phase_hits"])
            if r["score"] > prev["score"]:
                prev["score"] = r["score"]
                prev["overall"] = r["overall"]
                prev["phase_scores"] = r["phase_scores"]
                prev["support"] = r["support"]
                prev["estimated"] = r["estimated"]
            prev["windows"].append(r)
        else:
            merged.append(dict(r, n_windows=1, windows=[r]))
    return merged


def window_confidence(overall: int, *, has_hourly: bool, has_candles: bool,
                      gmgn_ok: bool, gmgn_complete: bool,
                      estimated: bool) -> str:
    """Confidence label for a verified window (page 9 spirit + GMGN state).

    HIGH: score >= 60, GMGN complete and usable, >= 2 data sources.
    MEDIUM: score >= 40 with at least one source, GMGN usable.
    LOW: GMGN failed/partial or estimated-only history with score < 60.
    """
    data_quality = (1 if has_hourly else 0) + (1 if has_candles else 0)
    if not gmgn_ok:
        return "LOW"
    if estimated and not gmgn_complete:
        return "LOW"
    if overall >= 60 and gmgn_complete and data_quality >= 2:
        return "HIGH"
    if overall >= 40 and data_quality >= 1:
        return "MEDIUM"
    return "LOW"


# ── Network helpers (optional; injectable for offline tests) ─────────────


def _gecko_ohlcv_page(pool: str, timeframe: str, aggregate: int,
                      limit: int, before_ts: int | None,
                      timeout: int) -> list:
    """One GeckoTerminal OHLCV request → candle dicts (oldest→newest).

    Uses the documented ``before_timestamp`` parameter so full history can
    be paged backwards.  Returns [] on any failure (mirrors
    ``cvd.fetch_candles`` behaviour).
    """
    try:
        params = {"aggregate": aggregate, "limit": limit}
        if before_ts is not None:
            params["before_timestamp"] = int(before_ts)
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pool}/ohlcv/{timeframe}",
            params=params, headers={"accept": "application/json"},
            timeout=timeout)
        lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list") or []
    except Exception:
        return []
    out = []
    for x in lst:
        try:
            out.append({"ts": int(x[0]), "o": float(x[1]), "h": float(x[2]),
                        "l": float(x[3]), "c": float(x[4]),
                        "v": float(x[5] or 0)})
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda c: c["ts"])
    return out


def fetch_candles_full(pool: str, *, timeframe: str = "hour",
                       aggregate: int = 1, limit: int = CANDLE_PAGE_LIMIT,
                       max_pages: int = MAX_CANDLE_PAGES,
                       until_ts: int | None = None, timeout: int = 20,
                       page_fetcher=None) -> dict:
    """Full-history OHLCV via backward pagination (oldest→newest output).

    ``page_fetcher`` defaults to :func:`_gecko_ohlcv_page` and is injectable
    so tests can simulate pages without network.  Returns
    ``{"candles": [...], "pages": n, "complete": bool, "oldest_ts": ...}``.
    ``complete`` is False when the page cap was hit before reaching
    ``until_ts`` (or before exhausting the API).
    """
    fetcher = page_fetcher or _gecko_ohlcv_page
    all_c: list = []
    before_ts = None
    pages = 0
    complete = False
    for _ in range(max_pages):
        page = fetcher(pool, timeframe, aggregate, limit, before_ts, timeout)
        if not page:
            complete = True  # API has nothing older — history exhausted
            break
        pages += 1
        all_c = page + all_c  # pages walk backwards; keep oldest→newest
        oldest = int(page[0]["ts"])
        if until_ts is not None and oldest <= until_ts:
            complete = True
            break
        before_ts = oldest - 1

    # Dedupe by ts (GeckoTerminal may repeat boundary candles) and sort.
    seen = set()
    dedup = []
    for c in sorted(all_c, key=lambda c: c["ts"]):
        if c["ts"] not in seen:
            seen.add(c["ts"])
            dedup.append(c)
    return {
        "candles": dedup,
        "pages": pages,
        "complete": complete,
        "oldest_ts": dedup[0]["ts"] if dedup else None,
    }
