"""Effort-to-result anomaly calculation and durable daily storage.

v3 final logic "Efisiensi Anomali":
- Day boundary = 00:00 UTC (GMGN convention)
- 7 signals: 2 new pra-pump (ABSORBSI_LANGSUNG, SELLING_EXHAUSTION) checked BEFORE all gates
- 5 old signals with divergence requirement for high multiplier
- Baseline = walk-back nearest healthy day before idx (|CVD|>=1, |price|>=3%, ratio>=0.05)
- Current floor |CVD|>=5 SOL
- Scan whole window via classify_all
"""
from __future__ import annotations

import datetime
import json
import math
import os
import tempfile
from typing import Iterable


def _atomic_write_json(path, data, **kwargs):
    """Write JSON atomically without importing the network/data stack."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".effort-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, **kwargs)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_EFFORT_PATH = os.path.join(BASE_DIR, "daily_effort.json")

# --- Floor / Gate FINAL (GMGN v4 final; do not change) ---
MIN_CURRENT_CVD_SOL = 5.0    # hari N wajib |CVD| >= 5 SOL, selain itu noise
MIN_PRICE_MOVE_PCT = 3.0     # hari N & baseline wajib bergerak >= 3%
MIN_BASELINE_CVD_SOL = 1.0   # baseline wajib |CVD| >= 1 SOL
MIN_BASELINE_RATIO = 0.05    # baseline ratio wajib >= 0.05
ANOMALY_UP = 2.0             # M >= 2.0
ANOMALY_DOWN = 0.5           # M <= 0.5
WHALE_PCT_THRESHOLD = 40.0   # flag whale (top-1 wallet >= 40% volume)

# Backward-compat names used by older tests/imports.
HIGH_MULTIPLIER = ANOMALY_UP
LOW_MULTIPLIER = ANOMALY_DOWN
RETENTION_DAYS = 30  # storage window only; not a holder/diamond-hands signal

# Selling exhaustion + direct absorption thresholds.
ABSORBSI_MIN_CVD_SOL = MIN_CURRENT_CVD_SOL
ABSORBSI_MAX_PRICE_PCT = 0.5
SELLING_FLUSH_CVD = 30.0
SELLING_COLLAPSE_RATIO = 0.40
SELLING_LOOKBACK_DAYS = 5
SELLING_PRICE_CAP_PCT = 0.5

# Backward-compat names for the same final constants.
EXHAUSTION_FLUSH_CVD_SOL = -SELLING_FLUSH_CVD
EXHAUSTION_PCT = SELLING_COLLAPSE_RATIO
EXHAUSTION_LOOKBACK_DAYS = SELLING_LOOKBACK_DAYS

SIGNAL_META = {
    "S1_PENYERAPAN": ("bullish", "Buyer menyerap supply"),
    "S2_DUMP_DISTRIBUSI": ("bearish", "Buyer absen; harga jatuh bebas"),
    "S3_DISTRIBUSI_KE_KUAT": ("bearish", "Seller menyerap demand"),
    "S4_PUMP_ASLI": ("bullish", "Seller absen; kenaikan efisien"),
    "S5_NETRAL": ("neutral", "Tidak ada anomali efisiensi"),
    "ABSORBSI_LANGSUNG": ("bullish", "Pembelian besar diam-diam, harga tidak naik = stealth accumulation"),
    "SELLING_EXHAUSTION": ("bullish", "Tekanan jual runtuh setelah flush besar, siap reversal"),
}


def _days_between(earlier: str | None, later: str | None):
    """Whole days between two ``YYYY-MM-DD`` strings, or ``None`` if unknown."""
    if not earlier or not later:
        return None
    try:
        start = datetime.date.fromisoformat(str(earlier))
        end = datetime.date.fromisoformat(str(later))
    except (TypeError, ValueError):
        return None
    return (end - start).days


def _finite(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def daily_effort_record(mint: str, date: str, open_price: float,
                        close_price: float, cvd_delta: float) -> dict:
    """Build one canonical daily effort row.

    ``ratio`` is always non-negative. A zero open or flat candle cannot have
    a meaningful SOL-per-percent ratio, so its ratio is stored as ``None``.

    ΔPrice% = (Close-Open)/Open*100  (day boundary 00:00 UTC = 07:00 WIB)
    ΔCVD = Σ(delta_sol) hari itu
    R = |ΔCVD|/|ΔPrice%|
    """
    opening = _finite(open_price)
    closing = _finite(close_price)
    delta = _finite(cvd_delta)
    price_pct = ((closing - opening) / opening * 100.0
                 if opening > 0 else 0.0)
    if price_pct > 0:
        direction = "up"
    elif price_pct < 0:
        direction = "down"
    else:
        direction = "flat"
    ratio = abs(delta) / abs(price_pct) if price_pct else None
    return {
        "mint": str(mint),
        "date": str(date),
        "open": opening,
        "close": closing,
        "price_chg_pct": round(price_pct, 8),
        "cvd_delta": round(delta, 8),
        "direction": direction,
        "ratio": round(ratio, 8) if ratio is not None else None,
    }


def _build_result(*, mint_or_empty: str, current: dict | None,
                   previous: dict | None, baseline_status: str,
                   baseline_reason: str, raw_multiplier: float | None,
                   signal: str, bias: str | None,
                   flag_divergence: bool) -> dict:
    """Construct a standardized result dict, including baseline fields."""
    direction_n = (current.get("direction") if current else None) or "flat"
    price_pct_n = _finite(current.get("price_chg_pct")) if current else 0.0
    cvd_delta_n = _finite(current.get("cvd_delta")) if current else 0.0
    ratio_n_raw = current.get("ratio") if current else None
    ratio_n = max(0.0, _finite(ratio_n_raw)) if ratio_n_raw is not None else None
    ratio_prev_raw = previous.get("ratio") if previous else None
    ratio_prev = _finite(ratio_prev_raw) if ratio_prev_raw is not None else None

    raw_mult_rounded = None
    if raw_multiplier is not None and math.isfinite(raw_multiplier):
        raw_mult_rounded = round(raw_multiplier, 8)

    baseline_date = previous.get("date") if previous else None
    baseline_price_pct = (round(_finite(previous.get("price_chg_pct")), 8)
                          if previous else None)
    baseline_cvd = (round(_finite(previous.get("cvd_delta")), 8)
                    if previous else None)
    baseline_direction = (previous.get("direction") if previous else None)
    baseline_gap_days = _days_between(baseline_date,
                                      current.get("date") if current else None)

    top_wallet_pct = _finite(current.get("top_wallet_pct")) if current else 0.0

    return {
        "mint": mint_or_empty or (current.get("mint", "") if current else ""),
        "date": current.get("date") if current else None,
        "previous_date": previous.get("date") if previous else None,
        "direction": direction_n,
        "ratio_N": round(ratio_n, 8) if ratio_n is not None else None,
        "ratio_N_minus_1": round(ratio_prev, 8) if ratio_prev is not None else None,
        "multiplier": raw_mult_rounded,
        "raw_multiplier": raw_mult_rounded,
        "signal": signal,
        "bias": bias,
        "flag_divergence": flag_divergence,
        "price_chg_pct": price_pct_n,
        "cvd_delta": cvd_delta_n,
        "baseline_status": baseline_status,
        "baseline_reason": baseline_reason,
        "baseline_date": baseline_date,
        "baseline_ratio": round(ratio_prev, 8) if ratio_prev is not None else None,
        "baseline_price_chg_pct": baseline_price_pct,
        "baseline_cvd_delta": baseline_cvd,
        "baseline_direction": baseline_direction,
        "baseline_gap_days": baseline_gap_days,
        "whale_driven": bool(top_wallet_pct >= WHALE_PCT_THRESHOLD),
        "top_wallet_pct": round(top_wallet_pct, 8) if current else None,
        "pair": ((current.get("pair") or current.get("pair_address"))
                 if current else None),
        "reason": baseline_reason,
    }


def _find_healthy_baseline(sorted_rows: list[dict], idx: int):
    """Walk-back nearest healthy baseline before idx.

    Healthy = |CVD|>=1, |ΔHarga|>=3%, ratio>=0.05, ratio finite>0.
    Does NOT require consecutive dates or same direction (final v3).
    Returns (baseline_idx, baseline_row) or (None, None).
    """
    for j in range(idx - 1, -1, -1):
        row = sorted_rows[j]
        cvd = _finite(row.get("cvd_delta"))
        price = _finite(row.get("price_chg_pct"))
        ratio_raw = row.get("ratio")
        if ratio_raw is None:
            continue
        ratio = _finite(ratio_raw)
        if not math.isfinite(ratio) or ratio <= 0:
            continue
        if abs(cvd) < MIN_BASELINE_CVD_SOL:
            continue
        if abs(price) < MIN_PRICE_MOVE_PCT:
            continue
        if ratio < MIN_BASELINE_RATIO:
            continue
        return j, row
    return None, None


def classify_at(rows: Iterable[dict], idx: int) -> dict:
    """Classify ONE day at index idx (as N) vs healthy baseline before idx.

    New v3 logic:
    - Check ABSORBSI_LANGSUNG and SELLING_EXHAUSTION BEFORE all other gates
    - ABSORBSI valid even for first window day
    - Current floor |CVD|>=5 else noise -> S5_NETRAL
    - Baseline walk-back (no direction / consecutiveness requirement)
    - S1/S3 require divergence, else fall to S5 with explanatory reason
    """
    selected = [dict(r) for r in (rows or [])]
    selected.sort(key=lambda r: str(r.get("date") or ""))

    if not selected or idx < 0 or idx >= len(selected):
        return _build_result(
            mint_or_empty="",
            current=None,
            previous=None,
            baseline_status="missing",
            baseline_reason="index di luar rentang atau tidak ada data",
            raw_multiplier=None,
            signal="insufficient_data",
            bias=None,
            flag_divergence=False,
        )

    current = selected[idx]
    mint_val = str(current.get("mint") or "")
    price_pct_n = _finite(current.get("price_chg_pct"))
    cvd_n = _finite(current.get("cvd_delta"))
    ratio_n_raw = current.get("ratio")
    ratio_n = max(0.0, _finite(ratio_n_raw)) if ratio_n_raw is not None else None
    direction_n = current.get("direction") or ("up" if price_pct_n > 0 else "down" if price_pct_n < 0 else "flat")
    flag_div = ((price_pct_n < 0 < cvd_n) or (price_pct_n > 0 > cvd_n))

    # --- 2a. ABSORBSI_LANGSUNG (priority highest, no baseline) ---
    # ΔCVD >= +5 SOL AND ΔPrice% <= +0.5%
    if cvd_n >= ABSORBSI_MIN_CVD_SOL and price_pct_n <= ABSORBSI_MAX_PRICE_PCT:
        prev_for_display = selected[idx - 1] if idx >= 1 else None
        res = _build_result(
            mint_or_empty=mint_val,
            current=current,
            previous=prev_for_display,
            baseline_status="direct",
            baseline_reason="ABSORBSI_LANGSUNG: CVD>=5 dan harga<=+0.5% — akumulasi stealth",
            raw_multiplier=None,
            signal="ABSORBSI_LANGSUNG",
            bias="bullish",
            flag_divergence=True,
        )
        # enrich
        res["flush_date"] = None
        res["flush_cvd"] = None
        res["exhaustion_pct"] = None
        return res

    # --- 2a. SELLING_EXHAUSTION (needs idx>=1, check flush in lookback 5) ---
    if idx >= 1 and cvd_n < 0 and price_pct_n <= SELLING_PRICE_CAP_PCT:
        look_start = max(0, idx - SELLING_LOOKBACK_DAYS)
        flush_row = None
        flush_cvd_val = None
        for j in range(look_start, idx):
            r = selected[j]
            c = _finite(r.get("cvd_delta"))
            if c <= -SELLING_FLUSH_CVD:
                if flush_row is None or c < flush_cvd_val:
                    flush_row = r
                    flush_cvd_val = c
        if flush_row is not None:
            # |CVD today| <= 40% * |CVD flush|
            if (flush_cvd_val != 0 and abs(cvd_n) <= SELLING_COLLAPSE_RATIO * abs(flush_cvd_val)):
                exhaustion_pct = (abs(cvd_n) / abs(flush_cvd_val) * 100.0) if flush_cvd_val != 0 else 0.0
                res = _build_result(
                    mint_or_empty=mint_val,
                    current=current,
                    previous=flush_row,
                    baseline_status="direct",
                    baseline_reason=(
                        f"SELLING_EXHAUSTION: flush {flush_row.get('date')} "
                        f"CVD {flush_cvd_val:.2f} → {cvd_n:.2f}, "
                        f"runtuh {exhaustion_pct:.1f}%"
                    ),
                    raw_multiplier=None,
                    signal="SELLING_EXHAUSTION",
                    bias="bullish",
                    flag_divergence=False,
                )
                res["flush_date"] = flush_row.get("date")
                res["flush_cvd"] = round(flush_cvd_val, 8)
                res["exhaustion_pct"] = round(exhaustion_pct, 8)
                # keep previous_date as flush date (for alert vs flush)
                return res

    # --- 3. Ranging gate: |ΔPrice% hari N| < 3% -> S5_NETRAL ---
    # This is intentionally checked before the current CVD noise floor to match
    # GMGN content.js ordering. Direct pra-pump signals above can still fire.
    if abs(price_pct_n) < MIN_PRICE_MOVE_PCT or direction_n == "flat":
        return _build_result(
            mint_or_empty=mint_val,
            current=current,
            previous=selected[idx - 1] if idx >= 1 else None,
            baseline_status="ranging",
            baseline_reason=f"|ΔHarga| {abs(price_pct_n):.2f}% < minimum {MIN_PRICE_MOVE_PCT:.2f}% — ranging",
            raw_multiplier=None,
            signal="S5_NETRAL",
            bias="neutral",
            flag_divergence=flag_div,
        )

    # --- 4. Noise gate: current |CVD| >=5 else S5_NETRAL ---
    if abs(cvd_n) < MIN_CURRENT_CVD_SOL:
        return _build_result(
            mint_or_empty=mint_val,
            current=current,
            previous=selected[idx - 1] if idx >= 1 else None,
            baseline_status="noise",
            baseline_reason=f"|ΔCVD| {abs(cvd_n):.2f} < minimum {MIN_CURRENT_CVD_SOL:.2f} SOL — noise",
            raw_multiplier=None,
            signal="S5_NETRAL",
            bias="neutral",
            flag_divergence=flag_div,
        )

    # --- 5. Baseline healthy walk-back ---
    baseline_idx, baseline_row = _find_healthy_baseline(selected, idx)
    if baseline_row is None:
        return _build_result(
            mint_or_empty=mint_val,
            current=current,
            previous=selected[idx - 1] if idx >= 1 else None,
            baseline_status="insufficient_baseline",
            baseline_reason="tidak ada baseline sehat dalam lookback (butuh |CVD|≥1, |ΔHarga|≥3%, ratio≥0.05)",
            raw_multiplier=None,
            signal="insufficient_data",
            bias=None,
            flag_divergence=flag_div,
        )

    # --- 6. Hitung M = R(N)/R(baseline) ---
    ratio_prev = _finite(baseline_row.get("ratio")) if baseline_row.get("ratio") is not None else None
    raw_multiplier = None
    if ratio_n is not None and ratio_prev is not None and math.isfinite(ratio_prev) and ratio_prev > 0 and math.isfinite(ratio_n):
        raw_multiplier = ratio_n / ratio_prev

    # --- 2b. Old signals with divergence requirement for M>=2 ---
    signal = "S5_NETRAL"
    bias = "neutral"
    reason = ""

    if direction_n == "down":
        if raw_multiplier is not None and raw_multiplier >= HIGH_MULTIPLIER:
            if flag_div:
                signal = "S1_PENYERAPAN"
                bias = "bullish"
            else:
                signal = "S5_NETRAL"
                bias = "neutral"
                reason = "M besar tapi CVD searah harga — bukan penyerapan/distribusi murni"
        elif raw_multiplier is not None and raw_multiplier <= LOW_MULTIPLIER:
            signal = "S2_DUMP_DISTRIBUSI"
            bias = "bearish"
        else:
            signal = "S5_NETRAL"
            bias = "neutral"
    elif direction_n == "up":
        if raw_multiplier is not None and raw_multiplier >= HIGH_MULTIPLIER:
            if flag_div:
                signal = "S3_DISTRIBUSI_KE_KUAT"
                bias = "bearish"
            else:
                signal = "S5_NETRAL"
                bias = "neutral"
                reason = "M besar tapi CVD searah harga — bukan penyerapan/distribusi murni"
        elif raw_multiplier is not None and raw_multiplier <= LOW_MULTIPLIER:
            signal = "S4_PUMP_ASLI"
            bias = "bullish"
        else:
            signal = "S5_NETRAL"
            bias = "neutral"
    else:
        signal = "S5_NETRAL"
        bias = "neutral"

    res = _build_result(
        mint_or_empty=mint_val,
        current=current,
        previous=baseline_row,
        baseline_status="stable",
        baseline_reason=reason,
        raw_multiplier=raw_multiplier,
        signal=signal,
        bias=bias,
        flag_divergence=flag_div,
    )
    return res


def classify_effort(rows: Iterable[dict], mint: str | None = None) -> dict:
    """Classify newest day (compatibility: = classify_at last index)."""
    selected = [dict(row) for row in (rows or [])
                if not mint or row.get("mint") == mint]
    selected.sort(key=lambda row: str(row.get("date") or ""))
    if not selected:
        return _build_result(
            mint_or_empty=mint or "",
            current=None,
            previous=None,
            baseline_status="missing",
            baseline_reason="tidak ada data",
            raw_multiplier=None,
            signal="insufficient_data",
            bias=None,
            flag_divergence=False,
        )
    return classify_at(selected, len(selected) - 1)


def classify_all(rows: Iterable[dict]) -> list[dict]:
    """Scan whole window, return array results aligned to sorted rows.

    Day 0 = "—" (insufficient) or ABSORBSI_LANGSUNG if passes direct check.
    """
    selected = [dict(row) for row in (rows or [])]
    selected.sort(key=lambda row: str(row.get("date") or ""))
    results: list[dict] = []
    for idx in range(len(selected)):
        if idx == 0:
            first = classify_at(selected, 0)
            if first.get("signal") == "ABSORBSI_LANGSUNG":
                results.append(first)
            else:
                results.append(_build_result(
                    mint_or_empty=str(selected[0].get("mint") or ""),
                    current=selected[0],
                    previous=None,
                    baseline_status="first_day",
                    baseline_reason="hari pertama window: hanya ABSORBSI_LANGSUNG yang dievaluasi; selain itu —",
                    raw_multiplier=None,
                    signal="—",
                    bias=None,
                    flag_divergence=False,
                ))
        else:
            results.append(classify_at(selected, idx))
    return results


def _insufficient(mint: str) -> dict:
    return _build_result(
        mint_or_empty=mint,
        current=None,
        previous=None,
        baseline_status="missing",
        baseline_reason="kurang dari dua hari data",
        raw_multiplier=None,
        signal="insufficient_data",
        bias=None,
        flag_divergence=False,
    )


def load_daily_effort(path: str = DAILY_EFFORT_PATH) -> list[dict]:
    """Load canonical rows; malformed files safely produce an empty list."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def merge_daily_effort(new_rows: Iterable[dict], *,
                       path: str = DAILY_EFFORT_PATH,
                       retention_days: int = RETENTION_DAYS) -> list[dict]:
    """Idempotently upsert mint/date rows and retain newest N per mint."""
    merged = {}
    for row in [*load_daily_effort(path), *(new_rows or [])]:
        if not isinstance(row, dict):
            continue
        mint = str(row.get("mint") or "").strip()
        date = str(row.get("date") or "").strip()
        if mint and date:
            merged[(mint, date)] = dict(row)
    by_mint = {}
    for row in merged.values():
        by_mint.setdefault(row["mint"], []).append(row)
    kept = []
    limit = max(2, int(retention_days))
    for mint_rows in by_mint.values():
        mint_rows.sort(key=lambda row: row["date"])
        kept.extend(mint_rows[-limit:])
    kept.sort(key=lambda row: (row["mint"], row["date"]))
    _atomic_write_json(path, kept, indent=2)
    return kept


def rows_for_mint(rows: Iterable[dict], mint: str) -> list[dict]:
    result = [dict(row) for row in (rows or []) if row.get("mint") == mint]
    return sorted(result, key=lambda row: row.get("date", ""))


def rows_with_signals(rows: Iterable[dict]) -> list[dict]:
    """Return daily CSV/export rows with one signal per day.

    Columns follow the GMGN v4 daily export contract. Missing operational
    fields default to blank/zero rather than inventing values.
    """
    sorted_rows = sorted([dict(r) for r in (rows or [])],
                         key=lambda r: str(r.get("date") or ""))
    classified = classify_all(sorted_rows)
    out = []
    for row, res in zip(sorted_rows, classified):
        out.append({
            "mint": row.get("mint"),
            "date": row.get("date"),
            "open": row.get("open"),
            "close": row.get("close"),
            "price_chg_pct": row.get("price_chg_pct"),
            "cvd_delta": row.get("cvd_delta"),
            "direction": row.get("direction"),
            "ratio": row.get("ratio"),
            "signal": res.get("signal"),
            "coverage_hours": row.get("coverage_hours", row.get("hours", "")),
            "top_wallet_pct": row.get("top_wallet_pct", ""),
            "unique_makers": row.get("unique_makers", ""),
        })
    return out


# Optional helper for CSV/recap output (spec 7a)
def format_recap(mint: str, rows: Iterable[dict]) -> str:
    """Build text recap block per spec 7a."""
    sorted_rows = sorted([dict(r) for r in (rows or []) if r.get("mint") == mint or not mint],
                         key=lambda r: str(r.get("date") or ""))
    if not sorted_rows:
        sorted_rows = sorted([dict(r) for r in (rows or [])], key=lambda r: str(r.get("date") or ""))
    results = classify_all(sorted_rows)
    lines = []
    lines.append("# === REKAPAN EFISIENSI ANOMALI ===")
    if mint:
        lines.append(f"# Mint: {mint}")
    if results:
        first = results[0].get("date") or "?"
        last = results[-1].get("date") or "?"
        lines.append(f"# Hari: N ({first} s/d {last})")
    for res in results:
        date = res.get("date") or "?"
        sig = res.get("signal") or "—"
        if sig in ("insufficient_data", "—"):
            continue
        bias = res.get("bias") or "neutral"
        price = res.get("price_chg_pct") or 0
        cvd = res.get("cvd_delta") or 0
        ratio = res.get("ratio_N")
        ratio_str = f"{ratio:.3f}" if ratio is not None else "—"
        lines.append(f"# {date}  {sig} ({bias})  | Δ{price:+.1f}% | CVD {cvd:+.2f} | R {ratio_str}")
    return "\n".join(lines)
