"""Effort-to-result anomaly calculation and durable daily storage.

The detector compares the absolute daily CVD delta (SOL) required for each
one percent of price movement. It deliberately has no secondary scoring or
wallet-based criteria.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime
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
MIN_PRICE_MOVE_PCT = 3.0
HIGH_MULTIPLIER = 2.0
LOW_MULTIPLIER = 0.5
RETENTION_DAYS = 30

MIN_BASELINE_RATIO = 0.05
MIN_BASELINE_CVD_SOL = 1.0

SIGNAL_META = {
    "S1_PENYERAPAN": ("bullish", "Buyer menyerap supply"),
    "S2_DUMP_DISTRIBUSI": ("bearish", "Buyer absen; harga jatuh bebas"),
    "S3_DISTRIBUSI_KE_KUAT": ("bearish", "Seller menyerap demand"),
    "S4_PUMP_ASLI": ("bullish", "Seller absen; kenaikan efisien"),
    "S5_NETRAL": ("neutral", "Tidak ada anomali efisiensi"),
}


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


def classify_effort(rows: Iterable[dict], mint: str | None = None) -> dict:
    """Classify the newest pair of consecutive daily rows.

    Detection requires two calendar-consecutive rows and a positive baseline
    ratio. Missing or invalid input returns ``insufficient_data`` rather than
    manufacturing a signal.

    Added baseline quality gates (MIN_BASELINE_RATIO, MIN_BASELINE_CVD_SOL)
    prevent extreme multipliers caused by very small denominator ratios.
    """
    selected = [dict(row) for row in (rows or [])
                if not mint or row.get("mint") == mint]
    selected.sort(key=lambda row: str(row.get("date") or ""))

    # --- Step 1: data availability ---
    if len(selected) < 2:
        return _build_result(
            mint_or_empty=mint or (selected[-1].get("mint", "") if selected else ""),
            current=selected[-1] if selected else None,
            previous=selected[-2] if len(selected) >= 2 else None,
            baseline_status="missing",
            baseline_reason="kurang dari dua hari data atau tanggal tidak berurutan",
            raw_multiplier=None,
            signal="insufficient_data",
            bias=None,
            flag_divergence=False,
        )

    previous, current = selected[-2], selected[-1]
    try:
        prev_date = datetime.strptime(previous.get("date", ""), "%Y-%m-%d").date()
        curr_date = datetime.strptime(current.get("date", ""), "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return _build_result(
            mint_or_empty=mint or current.get("mint", ""),
            current=current,
            previous=previous,
            baseline_status="missing",
            baseline_reason="tanggal tidak dapat diurai",
            raw_multiplier=None,
            signal="insufficient_data",
            bias=None,
            flag_divergence=False,
        )
    if (curr_date - prev_date).days != 1:
        return _build_result(
            mint_or_empty=mint or current.get("mint", ""),
            current=current,
            previous=previous,
            baseline_status="missing",
            baseline_reason="tanggal tidak berurutan (gap bukan 1 hari)",
            raw_multiplier=None,
            signal="insufficient_data",
            bias=None,
            flag_divergence=False,
        )

    # --- Extract current and previous values ---
    price_pct_n = _finite(current.get("price_chg_pct"))
    direction_n = current.get("direction") or "flat"
    cvd_delta_n = _finite(current.get("cvd_delta"))
    ratio_n_raw = current.get("ratio")
    ratio_n = max(0.0, _finite(ratio_n_raw)) if ratio_n_raw is not None else None

    price_pct_prev = _finite(previous.get("price_chg_pct"))
    direction_prev = previous.get("direction") or "flat"
    cvd_delta_prev = _finite(previous.get("cvd_delta"))
    ratio_prev_raw = previous.get("ratio")
    ratio_prev = _finite(ratio_prev_raw) if ratio_prev_raw is not None else None

    # --- Step 3: calculate raw multiplier if possible ---
    raw_multiplier = None
    if (ratio_n is not None and ratio_prev is not None
            and math.isfinite(ratio_prev) and ratio_prev > 0
            and math.isfinite(ratio_n)):
        raw_multiplier = ratio_n / ratio_prev

    # --- Step 4: baseline stability validation (rules 2-5) ---
    baseline_errors = []
    if ratio_prev is None or not math.isfinite(ratio_prev) or ratio_prev <= 0:
        baseline_errors.append(
            "ratio hari N-1 tidak tersedia, tidak finite, atau tidak positif")
    else:
        if ratio_prev < MIN_BASELINE_RATIO:
            baseline_errors.append(
                f"Baseline ratio {ratio_prev:.5f} < minimum {MIN_BASELINE_RATIO} SOL/1%")

    if not math.isfinite(price_pct_prev) or abs(price_pct_prev) < 3.0:
        baseline_errors.append(
            f"Baseline |ΔHarga| {abs(price_pct_prev):.2f} < minimum 3,00%")

    if not math.isfinite(cvd_delta_prev) or abs(cvd_delta_prev) < MIN_BASELINE_CVD_SOL:
        baseline_errors.append(
            f"Baseline |ΔCVD| {abs(cvd_delta_prev):.2f} < minimum {MIN_BASELINE_CVD_SOL:.2f} SOL")

    # If ratio_prev is None/non-positive, ratio comparison with MIN_BASELINE_RATIO
    # is already covered by the first check. We also need to ensure ratio_prev
    # meets the minimum when it's positive.
    if (ratio_prev is not None and math.isfinite(ratio_prev)
            and ratio_prev > 0 and ratio_prev < MIN_BASELINE_RATIO):
        # Already added above; keep for consistency
        pass

    # --- Step 5: direction compatibility (rule 6) ---
    direction_compatible = (direction_n == direction_prev)

    # --- Determine baseline status ---
    if baseline_errors:
        baseline_status = "unstable"
        baseline_reason = "; ".join(baseline_errors)
    elif not direction_compatible:
        baseline_status = "incompatible_direction"
        baseline_reason = "direction hari N berbeda dari baseline"
    else:
        baseline_status = "stable"
        baseline_reason = ""

    # --- Compute divergence flag (always possible) ---
    flag_divergence = ((price_pct_n < 0 < cvd_delta_n)
                       or (price_pct_n > 0 > cvd_delta_n))

    # --- Signal determination ---
    # Rules 2-5 fail -> insufficient_data
    if baseline_errors:
        signal = "insufficient_data"
        bias = None
    # Direction different -> insufficient_data
    elif not direction_compatible:
        signal = "insufficient_data"
        bias = None
    # Stable baseline and compatible direction
    else:
        # Small price move or flat -> neutral
        if abs(price_pct_n) < MIN_PRICE_MOVE_PCT or direction_n == "flat":
            signal = "S5_NETRAL"
        elif direction_n == "down" and raw_multiplier is not None and raw_multiplier >= HIGH_MULTIPLIER:
            signal = "S1_PENYERAPAN"
        elif direction_n == "down" and raw_multiplier is not None and raw_multiplier <= LOW_MULTIPLIER:
            signal = "S2_DUMP_DISTRIBUSI"
        elif direction_n == "up" and raw_multiplier is not None and raw_multiplier >= HIGH_MULTIPLIER:
            signal = "S3_DISTRIBUSI_KE_KUAT"
        elif direction_n == "up" and raw_multiplier is not None and raw_multiplier <= LOW_MULTIPLIER:
            signal = "S4_PUMP_ASLI"
        else:
            signal = "S5_NETRAL"
        bias = SIGNAL_META[signal][0]

    # For baseline errors or direction mismatch, bias stays None (already set)
    # and signal stays insufficient_data (already set)

    # --- Build final output ---
    multiplier_for_output = None
    if raw_multiplier is not None and math.isfinite(raw_multiplier):
        multiplier_for_output = round(raw_multiplier, 8)

    # Backward-compatible fields
    ratio_n_for_output = round(ratio_n, 8) if ratio_n is not None else None
    ratio_prev_for_output = round(ratio_prev, 8) if ratio_prev is not None else None

    result = {
        "mint": mint or current.get("mint", ""),
        "date": current.get("date"),
        "previous_date": previous.get("date"),
        "direction": direction_n,
        "ratio_N": ratio_n_for_output,
        "ratio_N_minus_1": ratio_prev_for_output,
        "multiplier": multiplier_for_output,
        "raw_multiplier": multiplier_for_output,
        "signal": signal,
        "bias": bias,
        "flag_divergence": flag_divergence,
        "price_chg_pct": price_pct_n,
        "cvd_delta": cvd_delta_n,
        "baseline_status": baseline_status,
        "baseline_reason": baseline_reason,
    }
    return result


def _build_result(*, mint_or_empty: str, current: dict | None,
                   previous: dict | None, baseline_status: str,
                   baseline_reason: str, raw_multiplier: float | None,
                   signal: str, bias: str | None,
                   flag_divergence: bool) -> dict:
    """Construct a standardized result dict, including new baseline fields."""
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
    }


def _insufficient(mint: str) -> dict:
    return _build_result(
        mint_or_empty=mint,
        current=None,
        previous=None,
        baseline_status="missing",
        baseline_reason="kurang dari dua hari data atau tanggal tidak berurutan",
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
    return [row for row in data if isinstance(row, dict)] \
        if isinstance(data, list) else []


def merge_daily_effort(new_rows: Iterable[dict], *,
                       path: str = DAILY_EFFORT_PATH,
                       retention_days: int = RETENTION_DAYS) -> list[dict]:
    """Idempotently upsert mint/date rows and retain the newest N per mint."""
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
