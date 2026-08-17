"""Bidirectional wash-collapse reversal engine.

This module is the Python port of SMART SEROK's trade normalization, FIFO
round-trip matcher, and clean-CVD aggregation.  It supports both UTC daily
buckets (parity/backtests) and rolling windows used by the realtime scanner.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import time
from typing import Iterable, Mapping

WASH_WINDOW_SEC = 60
NOISE_TAGS = frozenset(("sandwich_bot", "mev_bot", "mev"))
SMART_TAGS = frozenset((
    "axiom", "padre", "bluechip_owner", "trojan", "top_holder",
    "smart_degen", "smart_money",
))

REVERSAL_UP = "REVERSAL_UP"
REVERSAL_DOWN = "REVERSAL_DOWN"
ACCUMULATION = "ACCUMULATION"
DISTRIBUTION = "DISTRIBUTION"
NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class ReversalConfig:
    """Thresholds shared by daily and rolling detection."""

    wash_floor_pct: float = 6.0
    wash_collapse_ratio: float = 0.50
    context_cvd_min: float = 10.0
    current_cvd_min: float = 0.0
    context_price_pct: float = 15.0
    min_tx: int = 20
    min_volume_sol: float = 1.0
    setup_wash_pct: float = 10.0
    setup_price_cap_pct: float = 5.0


def _number(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        out = float(str(value).replace(",", "").strip())
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _first(item: Mapping, *names, default=None):
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return value
    return default


def _tags(item: Mapping) -> list[str]:
    found: list[str] = []
    for key in ("maker_tags", "maker_token_tags", "maker_event_tags", "tags"):
        value = item.get(key)
        if isinstance(value, str):
            value = [part.strip() for part in value.replace(";", ",").split(",")]
        if isinstance(value, (list, tuple)):
            for tag in value:
                clean = str(tag or "").strip().lower().replace(" ", "_").replace("-", "_")
                if clean and clean not in found:
                    found.append(clean)
    return found


def normalize_trade_item(item: Mapping | None) -> dict | None:
    """Normalize one GMGN trade, matching SMART SEROK field fallbacks.

    GMGN occasionally puts a broken SOL value in ``quote_amount``.  When the
    implied SOL/USD price is outside $10-$500, parity with the extension
    requires re-deriving SOL as ``amount_usd / 160``.
    """
    if not isinstance(item, Mapping):
        return None
    maker = _first(item, "maker", "maker_address", "wallet", "address",
                   "from_address", "owner", "trader", default="")
    if not maker:
        return None
    raw_event = _first(item, "event", "trade_type", "type", "direction",
                       "side", "action", default="")
    if not raw_event and "is_buy" in item:
        raw_event = "buy" if item.get("is_buy") else "sell"
    raw_event = str(raw_event).lower().strip()
    if "buy" in raw_event and "buyback" not in raw_event:
        event = "buy"
    elif "sell" in raw_event:
        event = "sell"
    elif "is_buy" in item:
        event = "buy" if item.get("is_buy") else "sell"
    else:
        return None

    ts = int(_number(_first(item, "timestamp", "time", "ts", "created_at",
                            "create_time", "block_time", "trade_time"), 0))
    if ts > 1_000_000_000_000:
        ts //= 1000
    if ts <= 0:
        return None

    sol = max(0.0, _number(_first(item, "quote_amount", "amount_sol",
                                  "sol_amount", "quote_volume", "sol", "quote")))
    token = _number(_first(item, "base_amount", "token_amount", "amount",
                           "token_volume", "token"))
    usd = _number(_first(item, "amount_usd", "usd_amount", "cost_usd", "usd",
                         "quote_value"))
    price = _number(_first(item, "price_usd", "price"))
    if usd <= 0 and token > 0 and price > 0:
        usd = token * price
    if usd > 0 and sol > 0:
        implied = usd / sol
        if implied < 10.0 or implied > 500.0:
            sol = usd / 160.0

    tx_hash = _first(item, "tx_hash", "tx_id", "signature", "hash")
    if not tx_hash:
        # The extension uses Math.random() here; object identity gives the same
        # per-record uniqueness without introducing nondeterministic test data.
        tx_hash = f"id_{item.get('id') or id(item)}"
    return {
        "maker": str(maker), "event": event, "sol": sol, "price": price,
        "ts": ts, "tx_hash": str(tx_hash), "token": token, "usd": usd,
        "tags": _tags(item), "matched": 0.0,
    }


def normalize_trades(items: Iterable[Mapping]) -> list[dict]:
    """Normalize, de-duplicate, and sort raw trades."""
    rows = []
    for raw in items or ():
        trade = normalize_trade_item(raw)
        if trade:
            rows.append(trade)
    # De-duplication belongs to the paginated fetcher.  Keeping normalization
    # one-to-one is required for parity with content.js and offline fixtures.
    return sorted(rows, key=lambda row: row["ts"])


def annotate_matched_amounts(trades: list[dict], window_sec: int = WASH_WINDOW_SEC) -> list[dict]:
    """Mark per-wallet opposite-side FIFO round trips within ``window_sec``."""
    for trade in trades:
        trade["matched"] = 0.0
    wallets: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        wallets[trade["maker"]].append(trade)
    for lots in wallets.values():
        lots.sort(key=lambda row: row["ts"])
        opened: list[dict] = []
        head = 0
        for trade in lots:
            remaining = trade["sol"] - trade["matched"]
            while head < len(opened):
                first = opened[head]
                if (first["sol"] - first["matched"] <= 1e-9 or
                        trade["ts"] - first["ts"] > window_sec):
                    head += 1
                else:
                    break
            for lot in opened[head:]:
                if remaining <= 1e-9:
                    break
                available = lot["sol"] - lot["matched"]
                if available <= 1e-9 or trade["event"] == lot["event"]:
                    continue
                matched = min(remaining, available)
                lot["matched"] += matched
                trade["matched"] += matched
                remaining -= matched
            if trade["sol"] - trade["matched"] > 1e-9:
                opened.append(trade)
    return trades


def aggregate_window(trades: Iterable[dict], *, start_ts: int | None = None,
                     end_ts: int | None = None, label: str = "") -> dict:
    """Aggregate already normalized/matched trades in ``[start_ts, end_ts)``."""
    rows = [row for row in trades
            if (start_ts is None or row["ts"] >= start_ts)
            and (end_ts is None or row["ts"] < end_ts)]
    rows.sort(key=lambda row: row["ts"])
    priced = [row for row in rows if row["price"] > 0]
    open_price = priced[0]["price"] if priced else None
    close_price = priced[-1]["price"] if priced else None
    cvd = clean = wash = buy_sol = sell_sol = vol_usd = 0.0
    buy_count = sell_count = 0
    maker_volume: dict[str, float] = defaultdict(float)
    smart_buy = fresh_buy = bot_sell = mev_noise = 0
    for row in rows:
        sign = 1 if row["event"] == "buy" else -1
        is_noise = bool(NOISE_TAGS.intersection(row.get("tags") or ()))
        removed = row["sol"] if is_noise else row.get("matched", 0.0)
        cvd += sign * row["sol"]
        clean += sign * (row["sol"] - removed)
        wash += removed
        vol_usd += row.get("usd", 0.0)
        maker_volume[row["maker"]] += row["sol"]
        tags = set(row.get("tags") or ())
        if row["event"] == "buy":
            buy_sol += row["sol"]
            buy_count += 1
            smart_buy += int(bool(SMART_TAGS.intersection(tags)))
            fresh_buy += int("fresh_wallet" in tags)
        else:
            sell_sol += row["sol"]
            sell_count += 1
            bot_sell += int(bool({"bundler", "paper_hands"}.intersection(tags)))
        mev_noise += int("sandwich_bot" in tags)
    vol_sol = buy_sol + sell_sol
    price_pct = None
    if open_price and close_price and open_price > 0:
        price_pct = (close_price / open_price - 1.0) * 100.0
    coverage = ((rows[-1]["ts"] - rows[0]["ts"]) / 3600.0) if rows else 0.0
    top_wallet_pct = (max(maker_volume.values(), default=0.0) / vol_sol * 100.0
                      if vol_sol > 0 else 0.0)
    return {
        "label": label, "start_ts": start_ts, "end_ts": end_ts,
        "open": open_price, "close": close_price, "price_chg_pct": price_pct,
        "cvd_delta": cvd, "cvd_delta_clean": clean,
        "wash_vol": wash, "wash_pct": wash / vol_sol * 100.0 if vol_sol else 0.0,
        "bot_masking": cvd - clean, "buy_sol": buy_sol, "sell_sol": sell_sol,
        "vol_sol": vol_sol, "vol_usd": vol_usd, "tx_count": len(rows),
        "buy_count": buy_count, "sell_count": sell_count,
        "coverage_hours": coverage, "top_wallet_pct": top_wallet_pct,
        "unique_makers": len(maker_volume), "smart_money_buy": smart_buy,
        "fresh_buy": fresh_buy, "bot_sell": bot_sell, "mev_noise": mev_noise,
    }


def build_daily(raw_trades: Iterable[Mapping], now_ts: int | None = None) -> list[dict]:
    """Build UTC daily rows with field parity to SMART SEROK ``buildDaily``."""
    trades = normalize_trades(raw_trades)
    annotate_matched_amounts(trades)
    buckets: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        date = datetime.fromtimestamp(trade["ts"], timezone.utc).strftime("%Y-%m-%d")
        buckets[date].append(trade)
    today = datetime.fromtimestamp(now_ts or int(time.time()), timezone.utc).strftime("%Y-%m-%d")
    result = []
    for date in sorted(buckets):
        row = aggregate_window(buckets[date], label=date)
        row["date"] = date
        row["partial"] = date == today or row["coverage_hours"] < 20
        result.append(row)
    return result


def build_rolling(raw_trades: Iterable[Mapping], *, now_ts: int | None = None,
                  current_hours: int = 6, baseline_hours: int = 24) -> dict:
    """Build current and preceding baseline windows from one wash annotation.

    ``current`` is the last six hours by default; ``baseline`` is the 24 hours
    immediately preceding it (i.e. 6-30 hours before ``now``).
    """
    now_ts = int(now_ts or time.time())
    trades = normalize_trades(raw_trades)
    annotate_matched_amounts(trades)
    current_start = now_ts - current_hours * 3600
    baseline_start = current_start - baseline_hours * 3600
    return {
        "generated_at": now_ts,
        "current": aggregate_window(trades, start_ts=current_start, end_ts=now_ts,
                                    label=f"last_{current_hours}h"),
        "baseline": aggregate_window(trades, start_ts=baseline_start,
                                     end_ts=current_start,
                                     label=f"prior_{baseline_hours}h"),
    }


def _base_result(current: dict, context: dict) -> dict:
    return {
        "signal": NEUTRAL, "bias": None, "confidence": "info",
        "reason": "", "current": current, "context": context,
        "wash_collapse": False,
    }


def detect_reversal(current: dict, context: dict,
                    config: ReversalConfig | None = None) -> dict:
    """Classify one current window against its prior context, both directions."""
    cfg = config or ReversalConfig()
    out = _base_result(current, context)
    if current.get("tx_count", 0) < cfg.min_tx:
        out["reason"] = f"current tx {current.get('tx_count', 0)} < {cfg.min_tx}"
        return out
    if current.get("vol_sol", 0) < cfg.min_volume_sol:
        out["reason"] = f"current volume {current.get('vol_sol', 0):.2f} SOL terlalu tipis"
        return out

    wash_now = float(current.get("wash_pct") or 0)
    wash_prior = float(context.get("wash_pct") or 0)
    collapse = (wash_now <= cfg.wash_floor_pct and wash_prior > 0 and
                wash_now <= wash_prior * cfg.wash_collapse_ratio)
    out["wash_collapse"] = collapse
    cvd_now = float(current.get("cvd_delta_clean") or 0)
    cvd_prior = float(context.get("cvd_delta_clean") or 0)
    prior_price = context.get("price_chg_pct")
    had_flush = (cvd_prior <= -cfg.context_cvd_min or
                 (prior_price is not None and prior_price <= -cfg.context_price_pct))
    had_pump = (cvd_prior >= cfg.context_cvd_min or
                (prior_price is not None and prior_price >= cfg.context_price_pct))

    if collapse and cvd_now > cfg.current_cvd_min and had_flush:
        out.update(signal=REVERSAL_UP, bias="bullish",
                   confidence="strong" if cvd_now >= 5 and wash_now <= 3 else "watch",
                   reason="wash runtuh + CVD bersih positif setelah flush")
    elif collapse and cvd_now < -cfg.current_cvd_min and had_pump:
        out.update(signal=REVERSAL_DOWN, bias="bearish",
                   confidence="strong" if cvd_now <= -5 and wash_now <= 3 else "watch",
                   reason="wash runtuh + CVD bersih negatif setelah pump")
    elif (wash_now >= cfg.setup_wash_pct and cvd_now > cfg.current_cvd_min and
          abs(float(current.get("price_chg_pct") or 0)) <= cfg.setup_price_cap_pct):
        out.update(signal=ACCUMULATION, bias="bullish", confidence="watch",
                   reason="CVD bersih positif masih dimasking wash tinggi")
    elif (wash_now >= cfg.setup_wash_pct and cvd_now < -cfg.current_cvd_min and
          float(current.get("price_chg_pct") or 0) >= -cfg.setup_price_cap_pct):
        out.update(signal=DISTRIBUTION, bias="bearish", confidence="watch",
                   reason="CVD bersih negatif masih dimasking wash tinggi")
    else:
        out["reason"] = "belum ada wash-collapse + arah CVD + konteks yang lengkap"
    return out


def detect_daily(daily: list[dict], idx: int = -1,
                 config: ReversalConfig | None = None) -> dict:
    """Detect reversal on daily rows, searching three prior days for context."""
    cfg = config or ReversalConfig()
    if not daily:
        return _base_result({}, {})
    idx = idx if idx >= 0 else len(daily) - 1
    current = daily[idx]
    prior = daily[max(0, idx - 3):idx]
    if not prior:
        result = _base_result(current, {})
        result["reason"] = "insufficient context"
        return result
    # Match extension behavior: choose deepest flush for UP, strongest pump for
    # DOWN. Evaluate each candidate and prefer a confirmed reversal.
    ordered = sorted(prior, key=lambda row: row.get("cvd_delta", 0))
    for context in (ordered[0], ordered[-1]):
        result = detect_reversal(current, context, cfg)
        if result["signal"] in (REVERSAL_UP, REVERSAL_DOWN):
            return result
    return detect_reversal(current, prior[-1], cfg)


def serializable_config(config: ReversalConfig | None = None) -> dict:
    return asdict(config or ReversalConfig())
