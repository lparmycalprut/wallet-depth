"""Minimal daily CVD aggregation for the effort anomaly detector.

The daily boundary follows the crypto-market day, which matches what Helius
and Solscan use: the day starts at 00:00 UTC. This keeps a token's "day" in
sync with on-chain market data sources.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Crypto market day boundary (Helius/Solscan use UTC).
MARKET_TZ = timezone.utc

# Backward-compatible alias for code that still referenced the old WIB name.
WIB = MARKET_TZ


def day_key(timestamp) -> str:
    """Return the market-day (UTC) calendar date for a Unix timestamp."""
    return datetime.fromtimestamp(int(timestamp), MARKET_TZ).date().isoformat()


# Backward-compatible alias.
day_key_wib = day_key


def calculate_daily_cvd(swaps) -> list[dict]:
    """Aggregate normalized swap tuples into daily CVD rows in market (UTC).

    Input tuples use ``(side, amount_sol, timestamp, wallet, ...)``. Only the
    signed SOL delta and basic volume counts are retained because the anomaly
    detector intentionally consumes no wallet or order-size heuristics.
    """
    days = defaultdict(lambda: {
        "buy_sol": 0.0, "sell_sol": 0.0, "buy_tx": 0, "sell_tx": 0,
        "wallet_volume": defaultdict(float), "makers": set(),
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
        item = days[day_key(timestamp)]
        item[f"{side}_sol"] += amount
        item[f"{side}_tx"] += 1
        wallet = str(swap[3]).strip() if len(swap) >= 4 and swap[3] is not None else ""
        if wallet:
            item["wallet_volume"][wallet] += amount
            item["makers"].add(wallet)
    result = []
    running = 0.0
    for date in sorted(days):
        item = days[date]
        delta = item["buy_sol"] - item["sell_sol"]
        running += delta
        total_volume = item["buy_sol"] + item["sell_sol"]
        top_volume = max(item["wallet_volume"].values(), default=0.0)
        top_wallet_pct = (top_volume / total_volume * 100.0) if total_volume > 0 else 0.0
        result.append({
            "date": date,
            "buy_sol": round(item["buy_sol"], 8),
            "sell_sol": round(item["sell_sol"], 8),
            "cvd_delta": round(delta, 8),
            "running_cvd_sol": round(running, 8),
            "buy_tx": item["buy_tx"],
            "sell_tx": item["sell_tx"],
            "top_wallet_pct": round(top_wallet_pct, 8),
            "unique_makers": len(item["makers"]),
        })
    return result


def completed_dates(rows, now=None) -> list[dict]:
    """Exclude the currently open market-day (UTC) candle."""
    now = now or datetime.now(MARKET_TZ)
    today = now.astimezone(MARKET_TZ).date().isoformat()
    return [dict(row) for row in (rows or [])
            if str(row.get("date") or "") < today]


# Backward-compatible alias.
completed_wib_dates = completed_dates


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
        grouped[day_key(timestamp)].append((timestamp, price))
    return [{"date": date, "open": points[0][1], "close": points[-1][1],
             "source": "trades"}
            for date, points in sorted(grouped.items())]


def build_effort_rows(mint: str, swaps, candles, *, now=None) -> list[dict]:
    """Join complete market-day (UTC) CVD rows with same-date open/close candles."""
    from effort_detector import daily_effort_record

    now = now or datetime.now(MARKET_TZ)
    cvd_rows = completed_dates(calculate_daily_cvd(swaps), now=now)
    by_date = {row["date"]: row for row in cvd_rows}
    today = now.astimezone(MARKET_TZ).date().isoformat()
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
        row = daily_effort_record(
            mint, date, opening, closing, daily["cvd_delta"])
        row["coverage_hours"] = candle.get("coverage_hours", candle.get("hours", ""))
        row["top_wallet_pct"] = daily.get("top_wallet_pct", 0.0)
        row["unique_makers"] = daily.get("unique_makers", 0)
        if candle.get("pair") or candle.get("pair_address"):
            row["pair"] = candle.get("pair") or candle.get("pair_address")
        result.append(row)
    return result
