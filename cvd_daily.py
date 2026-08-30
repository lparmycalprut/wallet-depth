"""Daily CVD + volume-USD + on-chain tag aggregation for the bottom detector.

The daily boundary follows the crypto-market day, which matches what Helius
and Solscan use (and the GMGN convention): the day starts at 00:00 UTC.

Volume untuk perbandingan antar-hari SELALU dalam USD (``amount_usd``),
bukan SOL — token yang sedang dump membuat rasio SOL ≠ USD karena nilai SOL
ikut menyusut. Tag maker (maker_tags / maker_token_tags / maker_event_tags)
diagregasi per hari menjadi 4 penanda on-chain yang hanya menjadi info di
output, bukan syarat sinyal:
  smart_money_buy, fresh_buy, bot_sell, mev_noise.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

# Crypto market day boundary (GMGN/Helius/Solscan use UTC).
MARKET_TZ = timezone.utc

# --- 4 penanda on-chain (§4; dicapture untuk analisa, bukan syarat sinyal) ---
SMART_MONEY_TAGS = frozenset({
    "axiom", "padre", "bluechip_owner", "trojan", "top_holder",
    "smart_degen", "smart_money",
})
FRESH_WALLET_TAG = "fresh_wallet"
BOT_SELL_TAGS = frozenset({"bundler", "paper_hands"})
MEV_NOISE_TAG = "sandwich_bot"


def normalize_tag(tag) -> str:
    """Lowercase snake_case tag so GMGN variants match the marker sets."""
    return str(tag or "").strip().lower().replace(" ", "_").replace("-", "_")


def _swap_tags(swap) -> set:
    """Normalized tag set from element 6 of an enriched swap tuple."""
    if not isinstance(swap, (list, tuple)) or len(swap) < 7:
        return set()
    raw = swap[6]
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {normalize_tag(tag) for tag in raw if normalize_tag(tag)}


def day_key(timestamp) -> str:
    """Return the market-day (UTC) calendar date for a Unix timestamp."""
    return datetime.fromtimestamp(int(timestamp), MARKET_TZ).date().isoformat()


def calculate_daily_cvd(swaps) -> list[dict]:
    """Aggregate normalized swap tuples into daily market-day (UTC) rows.

    Swap tuple shape (backward compatible, only first 3 are required):
    ``(side, amount_sol, timestamp, wallet, price_usd, amount_usd, tags)``

    ``amount_usd`` (index 5) feeds the daily USD volume used by the bottom
    detector; ``tags`` (index 6) feeds the 4 on-chain markers. Missing
    elements are tolerated (legacy 3–5 element tuples aggregate with
    ``volume_usd = 0`` and all markers at 0).
    """
    days = defaultdict(lambda: {
        "buy_sol": 0.0, "sell_sol": 0.0, "buy_usd": 0.0, "sell_usd": 0.0,
        "buy_tx": 0, "sell_tx": 0,
        "wallet_volume": defaultdict(float), "makers": set(),
        "smart_money_buy": 0, "fresh_buy": 0, "bot_sell": 0, "mev_noise": 0,
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
        amount_usd = 0.0
        if len(swap) >= 6 and swap[5] is not None \
                and not isinstance(swap[5], bool):
            try:
                amount_usd = float(swap[5])
            except (TypeError, ValueError):
                amount_usd = 0.0
        if amount_usd > 0:
            item[f"{side}_usd"] += amount_usd
        tags = _swap_tags(swap)
        if side == "buy":
            if tags & SMART_MONEY_TAGS:
                item["smart_money_buy"] += 1
            if FRESH_WALLET_TAG in tags:
                item["fresh_buy"] += 1
        elif tags & BOT_SELL_TAGS:
            item["bot_sell"] += 1
        if MEV_NOISE_TAG in tags:
            item["mev_noise"] += 1
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
            "buy_usd": round(item["buy_usd"], 8),
            "sell_usd": round(item["sell_usd"], 8),
            "volume_usd": round(item["buy_usd"] + item["sell_usd"], 8),
            "buy_tx": item["buy_tx"],
            "sell_tx": item["sell_tx"],
            "top_wallet_pct": round(top_wallet_pct, 8),
            "unique_makers": len(item["makers"]),
            "smart_money_buy": item["smart_money_buy"],
            "fresh_buy": item["fresh_buy"],
            "bot_sell": item["bot_sell"],
            "mev_noise": item["mev_noise"],
        })
    return result


def completed_dates(rows, now=None) -> list[dict]:
    """Exclude the currently open market-day (UTC) candle."""
    now = now or datetime.now(MARKET_TZ)
    today = now.astimezone(MARKET_TZ).date().isoformat()
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
        grouped[day_key(timestamp)].append((timestamp, price))
    return [{"date": date, "open": points[0][1], "close": points[-1][1],
             "source": "trades"}
            for date, points in sorted(grouped.items())]


def build_effort_rows(mint: str, swaps, candles, *, now=None,
                      supply=None) -> list[dict]:
    """Join complete market-day (UTC) CVD rows with same-date open/close candles.

    Tambahan field per hari (dari agregasi ``calculate_daily_cvd``):
    ``volume_usd`` (USD!), ``buy_usd``/``sell_usd``, 4 penanda on-chain
    (``smart_money_buy``, ``fresh_buy``, ``bot_sell``, ``mev_noise``), dan —
    bila ``supply`` diketahui — ``marketcap_close`` = close × supply untuk
    gerbang anti wash-trade (volume ≤ 3× MC close).
    """
    from daily_store import daily_effort_record

    now = now or datetime.now(MARKET_TZ)
    cvd_rows = completed_dates(calculate_daily_cvd(swaps), now=now)
    by_date = {row["date"]: row for row in cvd_rows}
    today = now.astimezone(MARKET_TZ).date().isoformat()
    try:
        token_supply = float(supply) if supply else None
    except (TypeError, ValueError):
        token_supply = None
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
        row["volume_usd"] = daily.get("volume_usd", 0.0)
        row["buy_usd"] = daily.get("buy_usd", 0.0)
        row["sell_usd"] = daily.get("sell_usd", 0.0)
        for marker in ("smart_money_buy", "fresh_buy", "bot_sell",
                       "mev_noise"):
            row[marker] = daily.get(marker, 0)
        if token_supply and token_supply > 0:
            try:
                close_price = float(closing)
            except (TypeError, ValueError):
                close_price = 0.0
            if close_price > 0:
                row["marketcap_close"] = round(close_price * token_supply, 2)
        if candle.get("pair") or candle.get("pair_address"):
            row["pair"] = candle.get("pair") or candle.get("pair_address")
        result.append(row)
    return result
