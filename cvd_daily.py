"""Minimal daily CVD aggregation for the effort anomaly detector."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))


def day_key_wib(timestamp) -> str:
    """Return the Asia/Jakarta calendar date for a Unix timestamp."""
    return datetime.fromtimestamp(int(timestamp), WIB).date().isoformat()


def calculate_daily_cvd(swaps) -> list[dict]:
    """Aggregate normalized swap tuples into daily CVD rows in WIB.

    Input tuples use ``(side, amount_sol, timestamp, wallet, ...)``. Only the
    signed SOL delta and basic volume counts are retained because the anomaly
    detector intentionally consumes no wallet or order-size heuristics.
    """
    days = defaultdict(lambda: {
        "buy_sol": 0.0, "sell_sol": 0.0, "buy_tx": 0, "sell_tx": 0,
    })
    for swap in swaps or []:
        if not isinstance(swap, (list, tuple)) or len(swap) < 3:
            continue
        side = str(swap[0]).lower()
        try:
            amount = float(swap[1])
            timestamp = int(swap[2])
        except (TypeError, ValueError):
            continue
        if side not in {"buy", "sell"} or amount <= 0 or timestamp <= 0:
            continue
        item = days[day_key_wib(timestamp)]
        item[f"{side}_sol"] += amount
        item[f"{side}_tx"] += 1
    result = []
    running = 0.0
    for date in sorted(days):
        item = days[date]
        delta = item["buy_sol"] - item["sell_sol"]
        running += delta
        result.append({
            "date": date,
            "buy_sol": round(item["buy_sol"], 8),
            "sell_sol": round(item["sell_sol"], 8),
            "cvd_delta": round(delta, 8),
            "running_cvd_sol": round(running, 8),
            "buy_tx": item["buy_tx"],
            "sell_tx": item["sell_tx"],
        })
    return result


def completed_wib_dates(rows, now=None) -> list[dict]:
    """Exclude the currently open WIB candle."""
    now = now or datetime.now(WIB)
    today = now.astimezone(WIB).date().isoformat()
    return [dict(row) for row in (rows or [])
            if str(row.get("date") or "") < today]


def fallback_candles_from_swaps(swaps) -> list[dict]:
    """Build daily open/close from priced GMGN trades when candles fail."""
    priced = []
    for swap in swaps or []:
        if not isinstance(swap, (list, tuple)) or len(swap) < 5:
            continue
        try:
            timestamp = int(swap[2])
            price = float(swap[4])
        except (TypeError, ValueError):
            continue
        if timestamp > 0 and price > 0:
            priced.append((timestamp, price))
    grouped = defaultdict(list)
    for timestamp, price in sorted(priced):
        grouped[day_key_wib(timestamp)].append((timestamp, price))
    return [{"date": date, "open": points[0][1], "close": points[-1][1],
             "source": "trades"}
            for date, points in sorted(grouped.items())]


def build_effort_rows(mint: str, swaps, candles, *, now=None) -> list[dict]:
    """Join complete WIB CVD rows with same-date open/close candles."""
    from effort_detector import daily_effort_record

    now = now or datetime.now(WIB)
    cvd_rows = completed_wib_dates(calculate_daily_cvd(swaps), now=now)
    by_date = {row["date"]: row for row in cvd_rows}
    today = now.astimezone(WIB).date().isoformat()
    result = []
    for candle in candles or []:
        date = str(candle.get("date") or "")
        daily = by_date.get(date)
        if not daily or not date or date >= today:
            continue
        opening = candle.get("open")
        closing = candle.get("close")
        if opening is None or closing is None:
            continue
        result.append(daily_effort_record(
            mint, date, opening, closing, daily["cvd_delta"]))
    return result
