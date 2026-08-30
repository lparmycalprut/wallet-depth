# -*- coding: utf-8 -*-
"""Penyimpanan harian (tanpa sinyal) untuk baris CVD/volume.

Semua logika sinyal lama (reversal / seller exhaustion / akumulasi harian)
sudah dihapus dari Wallet Depth. Modul ini hanya menyimpan baris agregasi
harian secara idempoten supaya halaman CVD tetap bisa menampilkan
pergerakan flow tanpa sinyal.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Iterable

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_EFFORT_PATH = os.path.join(BASE_DIR, "daily_effort.json")
STORAGE_WINDOW_DAYS = 30


def _atomic_write_json(path, data, **kwargs):
    """Write JSON atomically without importing the network/data stack."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".daily-", dir=directory)
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


def _finite(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def daily_effort_record(mint: str, date: str, open_price: float,
                        close_price: float, cvd_delta: float) -> dict:
    """Build one canonical daily row (tanpa sinyal).

    ΔPrice% = (Close-Open)/Open*100  (batas hari 00:00 UTC)
    ΔCVD    = Σ(delta_sol) hari itu (SOL)
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
    return {
        "mint": str(mint),
        "date": str(date),
        "open": opening,
        "close": closing,
        "price_chg_pct": round(price_pct, 8),
        "cvd_delta": round(delta, 8),
        "direction": direction,
    }


def load_daily_effort(path: str = DAILY_EFFORT_PATH) -> list[dict]:
    """Load canonical rows; malformed files safely produce an empty list."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(
        data, list) else []


def merge_daily_effort(new_rows: Iterable[dict], *,
                       path: str = DAILY_EFFORT_PATH,
                       window_days: int = STORAGE_WINDOW_DAYS) -> list[dict]:
    """Idempotently upsert mint/date rows and keep the newest N days per mint."""
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
    limit = max(2, int(window_days))
    for mint_rows in by_mint.values():
        mint_rows.sort(key=lambda row: row["date"])
        kept.extend(mint_rows[-limit:])
    kept.sort(key=lambda row: (row["mint"], row["date"]))
    _atomic_write_json(path, kept, indent=2)
    return kept


def rows_for_mint(rows: Iterable[dict], mint: str) -> list[dict]:
    result = [dict(row) for row in (rows or []) if row.get("mint") == mint]
    return sorted(result, key=lambda row: row.get("date", ""))
