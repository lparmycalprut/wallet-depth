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
    """
    selected = [dict(row) for row in (rows or [])
                if not mint or row.get("mint") == mint]
    selected.sort(key=lambda row: str(row.get("date") or ""))
    if len(selected) < 2:
        return _insufficient(mint or (selected[-1].get("mint")
                                      if selected else ""))
    previous, current = selected[-2], selected[-1]
    try:
        prev_date = datetime.strptime(previous["date"], "%Y-%m-%d").date()
        curr_date = datetime.strptime(current["date"], "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return _insufficient(mint or current.get("mint", ""))
    if (curr_date - prev_date).days != 1:
        return _insufficient(mint or current.get("mint", ""))

    ratio_n = current.get("ratio")
    ratio_prev = previous.get("ratio")
    if ratio_n is None or ratio_prev is None or _finite(ratio_prev) <= 0:
        return _insufficient(mint or current.get("mint", ""))
    ratio_n = max(0.0, _finite(ratio_n))
    ratio_prev = _finite(ratio_prev)
    multiplier = ratio_n / ratio_prev
    price_pct = _finite(current.get("price_chg_pct"))
    direction = current.get("direction") or "flat"

    if abs(price_pct) < MIN_PRICE_MOVE_PCT or direction == "flat":
        signal = "S5_NETRAL"
    elif direction == "down" and multiplier >= HIGH_MULTIPLIER:
        signal = "S1_PENYERAPAN"
    elif direction == "down" and multiplier <= LOW_MULTIPLIER:
        signal = "S2_DUMP_DISTRIBUSI"
    elif direction == "up" and multiplier >= HIGH_MULTIPLIER:
        signal = "S3_DISTRIBUSI_KE_KUAT"
    elif direction == "up" and multiplier <= LOW_MULTIPLIER:
        signal = "S4_PUMP_ASLI"
    else:
        signal = "S5_NETRAL"

    cvd_delta = _finite(current.get("cvd_delta"))
    flag_divergence = ((price_pct < 0 < cvd_delta)
                       or (price_pct > 0 > cvd_delta))
    bias = SIGNAL_META[signal][0]
    return {
        "mint": mint or current.get("mint", ""),
        "date": current.get("date"),
        "previous_date": previous.get("date"),
        "direction": direction,
        "ratio_N": round(ratio_n, 8),
        "ratio_N_minus_1": round(ratio_prev, 8),
        "multiplier": round(multiplier, 8),
        "signal": signal,
        "bias": bias,
        "flag_divergence": flag_divergence,
        "price_chg_pct": price_pct,
        "cvd_delta": cvd_delta,
    }


def _insufficient(mint: str) -> dict:
    return {
        "mint": mint,
        "date": None,
        "previous_date": None,
        "direction": "flat",
        "ratio_N": None,
        "ratio_N_minus_1": None,
        "multiplier": None,
        "signal": "insufficient_data",
        "bias": None,
        "flag_divergence": False,
    }


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
