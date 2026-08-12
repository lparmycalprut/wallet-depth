# -*- coding: utf-8 -*-
"""
SOLANA MEMECOIN PRE-PUMP & WYCKOFF 15M CRON DETECTOR

Runs every 15 minutes (minute 14, 29, 44, 59 UTC) so C3 is the
clock-aligned 15m candle that is about to close.

Only Grade A (golden 3-candle spring + smart buyer) and other
high-conviction setups (Grade B, SOS, anti-trap, bearish) notify.
Routine single-candle noise is Grade C and is muted.
"""

import os
import sys
import time
import json
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watchlist import load_watchlist
from core import atomic_write_json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNALS_PATH = os.path.join(ROOT_DIR, "signals.json")
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

# Fallback SOL/USD used when a trade has no trustworthy quote.
SOL_PRICE_USD = 150.0
CANDLE_SEC = 900
N_BINS = 16

# Implied SOL price outside this band means quote_amount is glitched.
SOL_PRICE_MIN_USD = 10.0
SOL_PRICE_MAX_USD = 500.0

SMART_TAGS = frozenset({
    "top_holder",
    "smart_degen",
    "bundler",
    "axiom",
    "bluechip_owner",
})

SIGNAL_GRADE_A = "⭐ GRADE A: GOLDEN SPRING (3-Candle + Smart Buyer)"
SIGNAL_GRADE_B = "🟢 GRADE B: HIGH QUALITY ABSORPTION"
SIGNAL_GRADE_C = "⚪ GRADE C: ROUTINE NOISE"
SIGNAL_SOS = "🚀 SOS IGNITION BREAKOUT"
SIGNAL_TRAP = "🔴 EXIT LIQUIDITY TRAP (BULL TRAP)"
SIGNAL_BEARISH = "🔴 BEARISH DIVERGENCE (HARGA TURUN / DISTRIBUSI)"


# ---------------------------------------------------------------------------
# Numeric / tag helpers
# ---------------------------------------------------------------------------
def _as_float(value, default=0.0):
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _first(obj, *keys, default=None):
    if not isinstance(obj, dict):
        return default
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return default


def normalize_tags(raw):
    """Flatten GMGN tag fields (list / csv / dict) to lower-case names."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        parts = raw.replace(";", ",").split(",")
        return [p.strip().lower() for p in parts if p.strip()]
    if isinstance(raw, dict):
        name = raw.get("name") or raw.get("tag") or raw.get("type") or ""
        return [str(name).strip().lower()] if name else []
    if isinstance(raw, (list, tuple, set)):
        out = []
        for item in raw:
            out.extend(normalize_tags(item))
        return out
    return [str(raw).strip().lower()]


def short_wallet(addr):
    addr = str(addr or "")
    if len(addr) <= 10:
        return addr
    return f"{addr[:4]}...{addr[-4:]}"


def sanitize_sol_quote_amount(usd, quote_amount, sol_price=SOL_PRICE_USD):
    """Convert a GMGN quote to SOL and fix glitched SOL-price ratios.

    If ``usd / quote_amount`` implies a SOL price below $10 or above $500
    the quote is treated as garbage (base-token amount, bad decimals, …)
    and we fall back to ``usd / sane_sol_price``.
    """
    usd = _as_float(usd, 0.0)
    quote = _as_float(quote_amount, 0.0)
    if quote > 10_000_000:
        quote /= 1_000_000_000.0
    px = _as_float(sol_price, SOL_PRICE_USD)
    if px < SOL_PRICE_MIN_USD or px > SOL_PRICE_MAX_USD:
        px = SOL_PRICE_USD
    if quote > 0.0 and usd > 0.0:
        implied = usd / quote
        if implied < SOL_PRICE_MIN_USD or implied > SOL_PRICE_MAX_USD:
            return usd / px if px > 0 else 0.0
        return quote
    if usd > 0.0 and px > 0.0:
        return usd / px
    return max(quote, 0.0)


def trade_sol(trade, sol_price=SOL_PRICE_USD):
    if trade.get("sol") not in (None, ""):
        sol = _as_float(trade.get("sol"), 0.0)
        if sol > 0:
            return sol
    return sanitize_sol_quote_amount(
        trade.get("usd"), trade.get("quote_amount"), sol_price)


def holder_address(holder):
    return str(_first(
        holder, "address", "account_address", "owner", "wallet",
        "maker", default="") or "").strip()


def holder_rank(holder, fallback=0):
    rank = _first(holder, "rank", "holder_rank", default=None)
    if rank is None:
        return int(fallback)
    return _as_int(rank, fallback)


def collect_actor_tags(obj):
    tags = []
    if not isinstance(obj, dict):
        return []
    for key in (
        "tags", "maker_tags", "makerTags", "maker_token_tags",
        "makerTokenTags", "wallet_tags", "token_tags", "addr_tag",
    ):
        tags.extend(normalize_tags(obj.get(key)))
    for flag, tag in (
        ("is_smart_degen", "smart_degen"),
        ("smart_degen", "smart_degen"),
        ("is_bundler", "bundler"),
        ("is_axiom", "axiom"),
        ("axiom", "axiom"),
        ("is_bluechip_owner", "bluechip_owner"),
        ("bluechip_owner", "bluechip_owner"),
        ("is_top_holder", "top_holder"),
        ("top_holder", "top_holder"),
    ):
        val = obj.get(flag)
        if val is True:
            tags.append(tag)
        elif isinstance(val, str) and val.strip().lower() in (
                "1", "true", "yes", tag):
            tags.append(tag)
    return sorted({t for t in tags if t})


# ---------------------------------------------------------------------------
# GMGN payload parsers (network-free, dual response shapes)
# ---------------------------------------------------------------------------
def extract_holder_rows(payload):
    """Accept both GMGN holder shapes: ``data.holders`` and ``data.list``."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("holders", "list", "rows", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    for key in ("holders", "list"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def extract_trade_rows(payload):
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("trades", "list", "history", "activities", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    for key in ("trades", "list"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def extract_next_cursor(payload):
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        cur = data.get("next") or data.get("next_cursor") or data.get("cursor")
        if cur:
            return str(cur)
    cur = payload.get("next") or payload.get("next_cursor") or payload.get("cursor")
    return str(cur) if cur else None


def build_gmgn_trades_url(ca, cursor=None, limit=100):
    """VAS trades endpoint: buy+sell, $1 min, 100/page."""
    url = (
        f"https://gmgn.ai/vas/api/v1/token_trades/sol/{ca}"
        f"?event=buy&event=sell&limit={int(limit)}"
        f"&min_amount_usd=1"
    )
    if cursor:
        url += f"&cursor={cursor}"
    return url


def parse_gmgn_trade(raw, sol_price=SOL_PRICE_USD):
    """Map one GMGN trade dict into the detector's trade shape."""
    if not isinstance(raw, dict):
        return None
    event = str(_first(raw, "event", "side", "action", default="") or "").lower()
    if "buy" in event:
        side = "buy"
    elif "sell" in event:
        side = "sell"
    else:
        return None
    usd = _as_float(_first(raw, "amount_usd", "amountUSD", "usd",
                           "cost_usd", default=0), 0.0)
    token_amount = _as_float(_first(
        raw, "amount_token", "token_amount", "base_amount",
        "amount", default=0), 0.0)
    quote_amount = _as_float(_first(
        raw, "quote_amount", "quoteAmount", "quote_amount_ui",
        default=0), 0.0)
    price = _as_float(_first(raw, "price", "price_usd", "priceUsd", default=0), 0.0)
    if price <= 0 and token_amount > 0 and usd > 0:
        price = usd / token_amount
    ts = _as_int(_first(raw, "timestamp", "time", "block_time",
                        "created_at", default=0), 0)
    if ts > 10_000_000_000:
        ts = int(ts / 1000)
    if ts <= 0:
        return None
    sol = sanitize_sol_quote_amount(usd, quote_amount, sol_price)
    tags = collect_actor_tags(raw)
    wallet = str(_first(
        raw, "maker", "address", "wallet", "user_address",
        default="") or "").strip()
    return {
        "wallet": wallet,
        "side": side,
        "usd": usd,
        "token_amount": token_amount,
        "price": price,
        "ts": ts,
        "sol": sol,
        "quote_amount": quote_amount,
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _browser_headers(ca):
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,id;q=0.8",
        "referer": f"https://gmgn.ai/sol/token/{ca}",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
    }


def _http_get(url, headers, timeout=20):
    try:
        from curl_cffi import requests as cr
        return cr.get(url, impersonate="chrome", headers=headers, timeout=timeout)
    except Exception:
        import requests
        return requests.get(url, headers=headers, timeout=timeout)


def _client_query():
    device_id = str(uuid.uuid4())
    fp_did = uuid.uuid4().hex
    build_tag = "20260807-3117-f1d79dd"
    return (
        f"&device_id={device_id}&fp_did={fp_did}"
        f"&client_id=gmgn_web_{build_tag}&from_app=gmgn&app_ver={build_tag}"
        f"&tz_name=Asia%2FJakarta&tz_offset=25200&app_lang=en-US"
        f"&os=web&worker=0"
    )


def fetch_top_holders(ca, timeout=20):
    """Fetch top 100 holders from GMGN (handles data.list and data.holders)."""
    url = (
        f"https://gmgn.ai/vas/api/v1/token_holders/sol/{ca}"
        f"?limit=100&cost=20&orderby=amount_percentage&direction=desc"
        f"{_client_query()}"
    )
    r = _http_get(url, _browser_headers(ca), timeout=timeout)
    if r.status_code == 200:
        return extract_holder_rows(r.json() or {})
    raise Exception(f"HTTP {r.status_code} fetching holders")


def fetch_gmgn_trades(ca, limit=500, timeout=20, sol_price=SOL_PRICE_USD):
    """Fetch recent buy/sell trades from the VAS token_trades endpoint."""
    page_limit = 100
    max_pages = max(1, (int(limit) + page_limit - 1) // page_limit)
    all_trades = []
    cursor = None
    for _ in range(max_pages):
        url = build_gmgn_trades_url(ca, cursor=cursor, limit=page_limit)
        url += _client_query()
        r = _http_get(url, _browser_headers(ca), timeout=timeout)
        if r.status_code != 200:
            break
        payload = r.json() or {}
        raw_rows = extract_trade_rows(payload)
        if not raw_rows:
            break
        for raw in raw_rows:
            parsed = parse_gmgn_trade(raw, sol_price=sol_price)
            if parsed:
                all_trades.append(parsed)
        cursor = extract_next_cursor(payload)
        if not cursor or len(raw_rows) < page_limit:
            break
        if len(all_trades) >= limit:
            break
        time.sleep(0.15)
    return all_trades[:limit]


# ---------------------------------------------------------------------------
# Clock-aligned 15m candles
# ---------------------------------------------------------------------------
def clock_aligned_bucket(ts):
    """Official 15m open: ``(int(ts) // 900) * 900``."""
    return (int(ts) // CANDLE_SEC) * CANDLE_SEC


def c3_bucket_start(now_ts):
    """C3 is the clock-aligned candle that is about to close.

    Cron fires at :14/:29/:44/:59 UTC, so ``now`` is still inside C3.
    """
    return clock_aligned_bucket(now_ts)


def trade_price(trade):
    """USD price of one trade (explicit price, else usd / token_amount)."""
    price = _as_float((trade or {}).get("price"), 0.0)
    if price > 0:
        return price
    token_amount = _as_float((trade or {}).get("token_amount"), 0.0)
    usd = _as_float((trade or {}).get("usd"), 0.0)
    return usd / token_amount if token_amount > 0 and usd > 0 else 0.0


def _empty_bin(bin_index, start, end):
    return {
        "bin_index": bin_index,
        "bucket_ts": start,
        "start": start,
        "end": end,
        "trades": [],
        "volume_usd": 0.0,
        "volume_sol": 0.0,
        "open_price": 0.0,
        "close_price": 0.0,
        "first_trade_price": 0.0,
        "prev_close": 0.0,
        "open_source": "none",
        "price_change_pct": 0.0,
        "is_green": False,
        "buy_vol_usd": 0.0,
        "sell_vol_usd": 0.0,
        "buy_vol_sol": 0.0,
        "sell_vol_sol": 0.0,
        "cvd_sol": 0.0,
        "buy_count": 0,
        "sell_count": 0,
        "total_tx": 0,
        "buy_tx_ratio": 0.0,
    }


def seed_close_before(grouped, oldest_start):
    """Last trade price in buckets strictly older than ``oldest_start``."""
    older = []
    for bucket_ts, rows in (grouped or {}).items():
        if bucket_ts < oldest_start:
            older.extend(rows)
    older.sort(key=lambda t: _as_int(t.get("ts"), 0))
    for trade in reversed(older):
        price = trade_price(trade)
        if price > 0:
            return price
    return 0.0


def apply_continuous_opens(bins, seed_close=0.0):
    """Set each candle's open to the previous candle's close (TradingView).

    A gap-down first print no longer paints a fake green candle: colour is
    Close vs previous Close. Empty bins carry the last close forward
    (flat 0% bar) so the chain does not break.
    """
    last_close = _as_float(seed_close, 0.0)
    for slot in reversed(list(bins or [])):
        intra_close = _as_float(slot.get("close_price"), 0.0)
        first_px = _as_float(slot.get("first_trade_price"), 0.0)
        slot["prev_close"] = last_close
        if last_close > 0:
            slot["open_price"] = last_close
            slot["open_source"] = "prev_close"
        elif first_px > 0:
            slot["open_price"] = first_px
            slot["open_source"] = "first_trade"
        else:
            slot["open_price"] = 0.0
            slot["open_source"] = "none"
        if intra_close > 0:
            slot["close_price"] = intra_close
        elif slot["open_price"] > 0:
            slot["close_price"] = slot["open_price"]
        else:
            slot["close_price"] = 0.0
        open_p = _as_float(slot.get("open_price"), 0.0)
        close_p = _as_float(slot.get("close_price"), 0.0)
        if open_p > 0 and close_p > 0:
            change = (close_p - open_p) / open_p * 100.0
        else:
            change = 0.0
        slot["price_change_pct"] = change
        slot["is_green"] = open_p > 0 and close_p >= open_p and change >= 0.0
        if close_p > 0:
            last_close = close_p
    return bins


def process_trades_to_15m_bins(trades, now_ts, sol_price=SOL_PRICE_USD,
                               n_bins=N_BINS):
    """Bucket trades into clock-aligned 15m candles.

    ``bins[0]`` = C3 (current / about to close),
    ``bins[1]`` = C2 (previous),
    ``bins[2]`` = C1 (baseline, 30-45m ago).

    Open is the previous candle's close (TradingView / GMGN continuous
    series). Colour is Close vs that open — a gap-down first print that
    never reclaims the prior close is a red / bear candle.
    """
    c3_start = c3_bucket_start(now_ts)
    grouped = {}
    for trade in trades or []:
        ts = _as_int(trade.get("ts"), 0)
        if ts <= 0:
            continue
        grouped.setdefault(clock_aligned_bucket(ts), []).append(trade)

    bins = []
    for i in range(int(n_bins)):
        start = c3_start - i * CANDLE_SEC
        end = start + CANDLE_SEC
        bin_trades = list(grouped.get(start, []))
        bin_trades_asc = sorted(bin_trades, key=lambda t: _as_int(t.get("ts"), 0))
        slot = _empty_bin(i, start, end)
        slot["trades"] = bin_trades

        volume_usd = 0.0
        volume_sol = 0.0
        buy_usd = sell_usd = 0.0
        buy_sol = sell_sol = 0.0
        buy_count = sell_count = 0
        for trade in bin_trades:
            usd = _as_float(trade.get("usd"), 0.0)
            sol = trade_sol(trade, sol_price)
            volume_usd += usd
            volume_sol += sol
            if trade.get("side") == "buy":
                buy_usd += usd
                buy_sol += sol
                buy_count += 1
            else:
                sell_usd += usd
                sell_sol += sol
                sell_count += 1

        priced = [t for t in bin_trades_asc if trade_price(t) > 0]
        first_px = trade_price(priced[0]) if priced else 0.0
        last_px = trade_price(priced[-1]) if priced else 0.0
        total_tx = len(bin_trades)
        slot.update({
            "volume_usd": volume_usd,
            "volume_sol": volume_sol,
            # Intra-bin prints only — open is overwritten below to prev close.
            "open_price": first_px,
            "close_price": last_px,
            "first_trade_price": first_px,
            "buy_vol_usd": buy_usd,
            "sell_vol_usd": sell_usd,
            "buy_vol_sol": buy_sol,
            "sell_vol_sol": sell_sol,
            "cvd_sol": buy_sol - sell_sol,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_tx": total_tx,
            "buy_tx_ratio": (buy_count / total_tx) if total_tx else 0.0,
        })
        bins.append(slot)

    seed = 0.0
    if bins:
        seed = seed_close_before(grouped, bins[-1]["start"])
    apply_continuous_opens(bins, seed_close=seed)
    return bins


# ---------------------------------------------------------------------------
# 3-candle Wyckoff engine + smart-buyer filter
# ---------------------------------------------------------------------------
def is_c2_volume_dry(c1, c2):
    """C2 LPS: volume down >= 40% vs C1 (or C2 < 3 SOL) and |chg| <= 2.5%."""
    vol_c1 = _as_float((c1 or {}).get("volume_sol"), 0.0)
    vol_c2 = _as_float((c2 or {}).get("volume_sol"), 0.0)
    change = _as_float((c2 or {}).get("price_change_pct"), 0.0)
    drop_pct = ((vol_c1 - vol_c2) / vol_c1 * 100.0) if vol_c1 > 0 else 0.0
    consolidating = abs(change) <= 2.5
    # C1 must have been a real baseline so empty history is not "dry".
    relative_dry = vol_c1 >= 0.50 and drop_pct >= 40.0
    absolute_dry = vol_c1 >= 0.50 and vol_c2 < 3.0
    return consolidating and (relative_dry or absolute_dry), drop_pct


def is_c3_spring_divergence(c3):
    """C3 spring: green/flat candle, CVD < -0.05 SOL, volume >= 0.50 SOL."""
    c3 = c3 or {}
    open_p = _as_float(c3.get("open_price"), 0.0)
    close_p = _as_float(c3.get("close_price"), 0.0)
    change = _as_float(c3.get("price_change_pct"), 0.0)
    cvd = _as_float(c3.get("cvd_sol"), 0.0)
    vol = _as_float(c3.get("volume_sol"), 0.0)
    if open_p <= 0 or close_p <= 0:
        return False
    green_or_flat = close_p >= open_p and change >= 0.0
    return green_or_flat and cvd < -0.05 and vol >= 0.50


def find_smart_buyers(c3_trades, holders):
    """C3 BUY flow from tagged wallets or Top 100 (esp. Top 1-10)."""
    holder_by_addr = {}
    top100 = set()
    top10 = set()
    for i, holder in enumerate(holders or []):
        addr = holder_address(holder)
        if not addr:
            continue
        key = addr.lower()
        rank = holder_rank(holder, i + 1)
        holder_by_addr[key] = {
            "address": addr,
            "rank": rank,
            "tags": collect_actor_tags(holder),
        }
        if i < 100:
            top100.add(key)
        if rank <= 10 or i < 10:
            top10.add(key)

    buyers = {}
    for trade in c3_trades or []:
        if trade.get("side") != "buy":
            continue
        addr = str(trade.get("wallet") or "").strip()
        if not addr:
            continue
        key = addr.lower()
        info = holder_by_addr.get(key) or {}
        tags = set(normalize_tags(trade.get("tags"))) | set(info.get("tags") or [])
        in_top100 = key in top100
        in_top10 = key in top10 or _as_int(info.get("rank"), 999) <= 10
        if in_top100:
            tags.add("top_holder")
        if not (tags & SMART_TAGS) and not in_top100:
            continue
        rec = buyers.setdefault(key, {
            "address": addr,
            "short": short_wallet(addr),
            "tags": set(),
            "sol": 0.0,
            "rank": info.get("rank"),
            "in_top10": in_top10,
            "in_top100": in_top100,
        })
        rec["tags"].update(tags)
        rec["sol"] += trade_sol(trade)
        if in_top10:
            rec["in_top10"] = True
        if info.get("rank") is not None:
            rec["rank"] = info.get("rank")

    out = []
    for rec in buyers.values():
        rec["tags"] = sorted(rec["tags"])
        out.append(rec)
    out.sort(key=lambda r: (
        0 if r.get("in_top10") else 1,
        -float(r.get("sol") or 0.0),
        r.get("rank") or 999,
    ))
    return out


def classify_wyckoff_grade(c1, c2, c3, smart_buyers, holder_lock_pct=0.0):
    """Grade A / B / C from the 3-candle sequence + smart-buyer flag."""
    dry, drop_pct = is_c2_volume_dry(c1, c2)
    spring = is_c3_spring_divergence(c3)
    has_smart = bool(smart_buyers)
    lock = _as_float(holder_lock_pct, 0.0)
    base = {
        "c2_dry": dry,
        "c3_spring": spring,
        "has_smart": has_smart,
        "drop_pct": drop_pct,
        "muted": False,
    }
    if not spring:
        base.update(grade=None, score=0.0, signal_type=None)
        return base
    if dry and has_smart:
        score = 95.0
        if drop_pct >= 50.0:
            score += 1.0
        if any(b.get("in_top10") for b in smart_buyers):
            score += 1.0
        if _as_float((c3 or {}).get("cvd_sol"), 0.0) < -1.0:
            score += 1.0
        if len(smart_buyers) >= 2:
            score += 1.0
        if lock >= 80.0:
            score += 1.0
        base.update(
            grade="A",
            score=min(100.0, score),
            signal_type=SIGNAL_GRADE_A,
        )
        return base
    if dry or has_smart:
        base.update(grade="B", score=80.0, signal_type=SIGNAL_GRADE_B)
        return base
    score = 50.0
    if lock >= 70.0:
        score = 55.0
    base.update(
        grade="C",
        score=score,
        signal_type=SIGNAL_GRADE_C,
        muted=True,
    )
    return base


def evaluate_sos_ignition(c3, baseline_vol_sol):
    c3 = c3 or {}
    vol = _as_float(c3.get("volume_sol"), 0.0)
    baseline = _as_float(baseline_vol_sol, 0.0)
    ratio = (vol / baseline) if baseline > 0 else 1.0
    hit = (
        ratio >= 3.0
        and _as_float(c3.get("buy_tx_ratio"), 0.0) >= 0.60
        and _as_float(c3.get("cvd_sol"), 0.0) > 3.0
        and _as_float(c3.get("price_change_pct"), 0.0) >= 8.0
    )
    return hit, ratio


def evaluate_anti_trap(c3, holder_lock_pct):
    c3 = c3 or {}
    return (
        _as_float(c3.get("price_change_pct"), 0.0) >= 10.0
        and _as_float(c3.get("cvd_sol"), 0.0) < -2.0
        and _as_float(holder_lock_pct, 0.0) < 50.0
    )


def evaluate_bearish_divergence(c3):
    c3 = c3 or {}
    return (
        _as_float(c3.get("price_change_pct"), 0.0) < 0.0
        and _as_float(c3.get("cvd_sol"), 0.0) >= 1.0
    )


def baseline_avg_volume_sol(bins):
    """Average 15m volume from prior 1-3 hours (bins 4..11)."""
    window = list(bins[4:12]) if bins and len(bins) > 4 else []
    if not window or sum(_as_float(b.get("volume_sol"), 0.0) for b in window) <= 0:
        window = list(bins[3:]) if bins and len(bins) > 3 else list(bins[1:] or [])
    if not window:
        return 0.0
    return sum(_as_float(b.get("volume_sol"), 0.0) for b in window) / len(window)


# ---------------------------------------------------------------------------
# Pure-accumulator lock
# ---------------------------------------------------------------------------
def compute_holder_lock_pct(holders):
    total = len(holders or [])
    if total <= 0:
        return 0.0, 0, 0
    pure = 0
    for holder in holders:
        bought = _as_float(_first(
            holder, "history_bought_amount", "historyBoughtAmount",
            default=0), 0.0)
        sold = _as_float(_first(
            holder, "history_sold_amount", "historySoldAmount",
            default=0), 0.0)
        if bought > 0:
            is_pure = (sold / bought) <= 0.10
        else:
            is_pure = sold == 0
        if is_pure:
            pure += 1
    return pure / total * 100.0, pure, total


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def _html_esc(text):
    return (str(text or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def ticker_label(symbol):
    """Return $TICKER, or empty string when the symbol is unknown."""
    raw = str(symbol or "").strip()
    if raw.startswith("$"):
        raw = raw[1:].strip()
    if not raw or raw in ("?", "-", "—", "unknown", "None"):
        return ""
    if raw.isascii() and raw.replace("_", "").isalnum():
        raw = raw.upper()
    return f"${raw}"


def format_usd_price(price):
    px = _as_float(price, 0.0)
    if px <= 0:
        return "$0"
    return f"${px:.8f}".rstrip("0").rstrip(".")


def format_vol_sol(vol):
    """Human volume: ``12.30 SOL`` or an explicit empty-candle label."""
    vol = _as_float(vol, 0.0)
    if vol <= 0:
        return "0.00 SOL — sepi (tidak ada trade)"
    return f"{vol:.2f} SOL"


def format_smart_buyers_line(smart_buyers):
    """One-line fallback (kept for callers / older tests)."""
    if not smart_buyers:
        return "—"
    parts = []
    for buyer in smart_buyers[:4]:
        tags = ", ".join(buyer.get("tags") or []) or "top_holder"
        parts.append(
            f"{buyer.get('short') or short_wallet(buyer.get('address'))} "
            f"({tags}, {float(buyer.get('sol') or 0):.2f} SOL)"
        )
    extra = len(smart_buyers) - 4
    line = " · ".join(parts)
    if extra > 0:
        line += f" · +{extra} more"
    return line


def format_smart_buyers_block(smart_buyers):
    """One wallet per line so the alert is scannable on mobile."""
    if not smart_buyers:
        return "👤 Smart Buyers : —"
    lines = ["👤 Smart Buyers :"]
    for buyer in smart_buyers[:4]:
        tags = ", ".join(buyer.get("tags") or []) or "top_holder"
        short = buyer.get("short") or short_wallet(buyer.get("address"))
        sol = float(buyer.get("sol") or 0)
        lines.append(f"   • {short} — {tags} · {sol:.2f} SOL")
    extra = len(smart_buyers) - 4
    if extra > 0:
        lines.append(f"   • +{extra} more")
    return "\n".join(lines)


def format_candle_block(vol_c1, vol_c2, vol_c3, drop_pct,
                        c2_tag="", c3_tag=""):
    """3-line C1/C2/C3 volume. Empty C1 is labeled, not ``0.00S``."""
    c2_head = f"C2 ({c2_tag})" if c2_tag else "C2"
    c3_head = f"C3 ({c3_tag})" if c3_tag else "C3"
    drop_bit = ""
    if _as_float(vol_c1, 0.0) > 0:
        drop_bit = f"  · turun {drop_pct:.1f}% vs C1"
    return (
        "📝 Urutan Candle (volume 15m):\n"
        f"   C1 · 30-45m lalu : {format_vol_sol(vol_c1)}\n"
        f"   {c2_head} · 15-30m lalu : {format_vol_sol(vol_c2)}"
        f"{drop_bit}\n"
        f"   {c3_head} · sekarang    : {format_vol_sol(vol_c3)}"
    )


def format_grade_a_message(ca, score, price, change_pct, vol_sol, cvd_sol,
                           lock_pct, vol_c1, vol_c2, vol_c3, drop_pct,
                           smart_buyers, symbol="?"):
    return format_signal_message(
        SIGNAL_GRADE_A, ca, score, price, change_pct, vol_sol, cvd_sol,
        lock_pct, vol_c1, vol_c2, vol_c3, drop_pct, smart_buyers,
        extra_lines=None, warn_line="", symbol=symbol,
        c2_tag="Kering", c3_tag="Spring")


def format_signal_message(badge_title, ca, score, price, change_pct,
                          vol_sol, cvd_sol, lock_pct, vol_c1, vol_c2, vol_c3,
                          drop_pct, smart_buyers, extra_lines=None,
                          warn_line="", symbol="?", c2_tag="", c3_tag=""):
    price_sign = "+" if change_pct >= 0 else ""
    cvd_note = ("Net Sells Terserap!" if cvd_sol <= 0
                else "Net Buys Dominan!")
    ticker = ticker_label(symbol)
    title = badge_title
    if ticker:
        title = f"{badge_title}\n🪙 {ticker}"
    extras = ""
    if extra_lines:
        extras = "\n\n" + "\n".join(extra_lines)
    warn = f"\n\n{warn_line}" if warn_line else ""
    candle = format_candle_block(
        vol_c1, vol_c2, vol_c3, drop_pct, c2_tag=c2_tag, c3_tag=c3_tag)
    buyers = format_smart_buyers_block(smart_buyers)
    ca_esc = _html_esc(ca)
    return (
        f"{title}\n"
        f"\n"
        f"🎯 Skor Pre-Pump : {score:.0f} / 100\n"
        f"🧾 Mint          : <code>{ca_esc}</code>\n"
        f"💵 Harga         : {format_usd_price(price)} "
        f"({price_sign}{change_pct:.2f}%)\n"
        f"📊 15m Vol / CVD : {vol_sol:.2f} SOL | {cvd_sol:+.2f} SOL\n"
        f"   {cvd_note}\n"
        f"🔒 Top 100 Lock  : {lock_pct:.1f}% Pure Accumulators\n"
        f"\n"
        f"{candle}\n"
        f"\n"
        f"{buyers}"
        f"{extras}"
        f"{warn}\n"
        f"\n"
        f"🔗 GMGN : https://gmgn.ai/sol/token/{ca}"
    )


def _read_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def send_telegram_notif(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    cfg = _read_config()
    token = token or str(cfg.get("telegram_bot_token") or "")
    chat = chat or str(cfg.get("telegram_chat_id") or "")
    if not token or not chat:
        print("Telegram credentials not configured.")
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        res = requests.post(url, json=payload, timeout=15)
        return res.status_code == 200
    except Exception as exc:
        print("Error sending Telegram:", exc)
        return False


def send_discord_notif(text):
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    cfg = _read_config()
    url = url or str(cfg.get("discord_webhook_url") or "")
    if not url:
        print("Discord Webhook URL not configured.")
        return False
    try:
        import requests
        md_text = (
            text.replace("<b>", "**")
            .replace("</b>", "**")
            .replace("<i>", "*")
            .replace("</i>", "*")
            .replace("<code>", "`")
            .replace("</code>", "`")
        )
        res = requests.post(url, json={"content": md_text}, timeout=15)
        return res.status_code in (200, 204)
    except Exception as exc:
        print("Error sending Discord:", exc)
        return False


def load_signals():
    try:
        if os.path.exists(SIGNALS_PATH):
            with open(SIGNALS_PATH, encoding="utf-8") as f:
                return json.load(f) or []
    except Exception:
        pass
    return []


def save_signal_to_history(sig):
    items = load_signals()
    now = int(time.time())
    for prev in reversed(items[-100:]):
        if (prev.get("ca") == sig["ca"]
                and prev.get("type") == sig["type"]
                and (now - int(prev.get("ts") or 0)) < 3 * 3600):
            print(f"Signal for {sig['ca']} is a duplicate within 3 hours, "
                  "skipped recording.")
            return False
    items.append(sig)
    atomic_write_json(SIGNALS_PATH, items[-2000:], separators=(",", ":"))
    print(f"Recorded signal for {sig['ca']} in signals.json")
    return True


# ---------------------------------------------------------------------------
# Mock fixture (Grade A golden spring)
# ---------------------------------------------------------------------------
def get_mock_data(now_ts):
    """Clock-aligned Grade A fixture (SISYPUSS-style spring + rank-3 buy)."""
    c3 = c3_bucket_start(now_ts)
    c2 = c3 - CANDLE_SEC
    c1 = c3 - 2 * CANDLE_SEC
    holders = []
    for i in range(1, 101):
        wallet = (
            f"MockHolderAddress{i}xxxxxxxxxxxxxxxxxx"
            if i != 3 else "Rank3TopHolderWalletAddressxxxxxxxxxxxxxx"
        )
        holders.append({
            "address": wallet,
            "rank": i,
            "balance": 10000.0 / i,
            "history_bought_amount": 10000.0 / i,
            "history_sold_amount": 0.0,
            "cost": 0.000035,
            "avg_cost": 0.000035,
            "tags": ["top_holder"] if i <= 10 else [],
        })

    def _t(wallet, side, sol, price, ts, tags=None):
        return {
            "wallet": wallet,
            "side": side,
            "usd": sol * SOL_PRICE_USD,
            "token_amount": (sol * SOL_PRICE_USD) / price if price else 0.0,
            "price": price,
            "ts": ts,
            "sol": sol,
            "quote_amount": sol,
            "tags": list(tags or []),
        }

    trades = [
        _t("DummyWalletxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "buy",
           10.0, 0.000040, c1 + 5 * 60),
        _t("DummyWalletxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "sell",
           0.10, 0.0000398, c2 + 2 * 60),
        _t("DummyWalletxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "buy",
           2.00, 0.0000402, c2 + 8 * 60),
        _t("SellerWalletAddressxxxxxxxxxxxxxxxxxxxxxxx", "sell",
           7.13, 0.0000359, c3 + 2 * 60),
        _t("Rank3TopHolderWalletAddressxxxxxxxxxxxxxx", "buy",
           5.00, 0.00004398, c3 + 10 * 60, tags=["top_holder"]),
        _t("AnotherBuyerWalletAddressxxxxxxxxxxxxxxxxx", "buy",
           0.17, 0.00004398, c3 + 11 * 60),
    ]
    for idx in range(4, 16):
        b_start = c3 - idx * CANDLE_SEC
        trades.append(_t(
            "DummyWalletxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "buy",
            20.0, 0.000035, b_start + 5 * 60))
    return holders, trades


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def run_pipeline_for_ca(ca, symbol, now_ts, mock_mode=False):
    print(f"\nEvaluating CA: {ca} ({symbol})")

    holders = []
    trades = []
    if mock_mode:
        print("Using MOCK/SIMULATION data for evaluation.")
        holders, trades = get_mock_data(now_ts)
    else:
        try:
            print("Fetching real holders from GMGN...")
            holders = fetch_top_holders(ca)
            print(f"Successfully fetched {len(holders)} holders.")
        except Exception as exc:
            print(f"Warning: failed to fetch holders: {exc}")
        try:
            print("Fetching real trades from GMGN...")
            trades = fetch_gmgn_trades(ca, limit=500)
            print(f"Successfully fetched {len(trades)} trades.")
        except Exception as exc:
            print(f"Warning: failed to fetch trades: {exc}")

    if not holders or not trades:
        print(f"Skipping {ca} due to missing data.")
        return None

    lock_pct, pure_n, total_n = compute_holder_lock_pct(holders)
    print(f"Top Holders Supply Lock: {lock_pct:.2f}% "
          f"({pure_n}/{total_n} Pure Accumulators)")

    bins = process_trades_to_15m_bins(trades, now_ts)
    c3 = bins[0]
    c2 = bins[1] if len(bins) > 1 else _empty_bin(1, c3["start"] - CANDLE_SEC,
                                                 c3["start"])
    c1 = bins[2] if len(bins) > 2 else _empty_bin(2, c3["start"] - 2 * CANDLE_SEC,
                                                 c3["start"] - CANDLE_SEC)

    vol_c1 = _as_float(c1.get("volume_sol"), 0.0)
    vol_c2 = _as_float(c2.get("volume_sol"), 0.0)
    vol_c3 = _as_float(c3.get("volume_sol"), 0.0)
    cvd_sol = _as_float(c3.get("cvd_sol"), 0.0)
    change_pct = _as_float(c3.get("price_change_pct"), 0.0)
    buy_tx_ratio = _as_float(c3.get("buy_tx_ratio"), 0.0)

    baseline_sol = baseline_avg_volume_sol(bins)
    sos_hit, vol_ratio = evaluate_sos_ignition(c3, baseline_sol)
    trap_hit = evaluate_anti_trap(c3, lock_pct)
    bearish_hit = evaluate_bearish_divergence(c3)
    smart_buyers = find_smart_buyers(c3.get("trades") or [], holders)
    grade_info = classify_wyckoff_grade(
        c1, c2, c3, smart_buyers, holder_lock_pct=lock_pct)
    drop_pct = _as_float(grade_info.get("drop_pct"), 0.0)

    print(f"C1 vol {vol_c1:.2f}S | C2 vol {vol_c2:.2f}S "
          f"(drop {drop_pct:.1f}%, dry={grade_info['c2_dry']}) | "
          f"C3 vol {vol_c3:.2f}S CVD {cvd_sol:+.2f}S chg {change_pct:+.2f}% "
          f"spring={grade_info['c3_spring']}")
    print(f"Baseline 15m Vol Avg: {baseline_sol:.2f} SOL | "
          f"Ratio vs Baseline: {vol_ratio:.2f}x")
    print(f"Smart buyers on C3: {len(smart_buyers)}")

    reasons = []
    extra_lines = []
    warn_line = ""
    signal_type = None
    score = 0.0
    grade = grade_info.get("grade")
    muted = False

    # Priority: trap > SOS > Grade A > bearish > Grade B > Grade C (mute)
    if trap_hit:
        score = 25.0
        signal_type = SIGNAL_TRAP
        grade = None
        reasons.append(
            f"Bull Trap: Harga {change_pct:+.1f}% tp CVD {cvd_sol:+.2f} SOL "
            f"dan lock {lock_pct:.1f}% < 50%"
        )
        extra_lines.append(
            f"📝 Indikator : Exit Liquidity — jangan beli "
            f"(CVD {cvd_sol:+.2f} SOL, lock {lock_pct:.1f}%)"
        )
        warn_line = (
            "⚠️ HATI-HATI: kenaikan tanpa demand on-chain — "
            "dev/cabal dump ke market."
        )
    elif sos_hit:
        score = 90.0
        if vol_ratio >= 5.0:
            score += 4.0
        if change_pct >= 15.0:
            score += 3.0
        if cvd_sol > 5.0:
            score += 3.0
        score = min(100.0, score)
        signal_type = SIGNAL_SOS
        grade = None
        reasons.append(
            f"SOS Ignition: Vol {vol_ratio:.1f}x baseline, "
            f"Buy TX {buy_tx_ratio * 100:.1f}%, CVD {cvd_sol:+.2f} SOL, "
            f"Kenaikan {change_pct:+.1f}%"
        )
        extra_lines.append(
            f"📝 Indikator : SOS {vol_ratio:.1f}x · "
            f"Buy TX {buy_tx_ratio * 100:.1f}% · CVD {cvd_sol:+.2f} SOL"
        )
    elif grade == "A":
        score = float(grade_info["score"])
        signal_type = SIGNAL_GRADE_A
        reasons.append(
            f"Golden Spring: C2 kering {drop_pct:.1f}% + C3 divergensi "
            f"CVD {cvd_sol:+.2f} SOL tp hijau {change_pct:+.1f}% + smart buyer"
        )
    elif bearish_hit:
        score = max(0.0, lock_pct * 0.65 - 30.0)
        signal_type = SIGNAL_BEARISH
        grade = None
        reasons.append(
            f"Divergensi Distribusi: CVD {cvd_sol:+.2f} SOL tp Candle Turun "
            f"{change_pct:+.1f}% — HATI-HATI"
        )
        extra_lines.append(
            f"📝 Indikator : ⚠️ CVD plus tp candle merah — "
            f"buyer diserap seller"
        )
        warn_line = (
            "⚠️ HATI-HATI: harga turun tapi CVD plus — buyer "
            "diserap seller (potensi distribusi). Jangan entry dulu."
        )
    elif grade == "B":
        score = 80.0
        signal_type = SIGNAL_GRADE_B
        if grade_info["c2_dry"] and not grade_info["has_smart"]:
            reasons.append(
                f"Absorption parsial: C2 kering {drop_pct:.1f}% + C3 spring "
                f"(tanpa smart buyer)"
            )
        else:
            reasons.append(
                "Absorption parsial: C3 spring + smart buyer (C2 belum kering)"
            )
    elif grade == "C":
        score = float(grade_info["score"])
        signal_type = SIGNAL_GRADE_C
        muted = True
        reasons.append(
            "Routine noise: C3 hijau + CVD minus tanpa C2 kering / smart buyer"
        )
        print(f"Grade C muted (score {score:.0f}) — no notification.")
    else:
        score = min(100.0, lock_pct * 0.65)
        signal_type = None

    score = max(0.0, min(100.0, score))
    print(f"Pre-Pump Score: {score:.1f} / 100")
    if signal_type:
        print(f"Signal Detected: {signal_type} (grade={grade}, muted={muted})")

    current_price = c3["close_price"] if c3["close_price"] > 0 else 0.0
    c2_tag = "Kering" if grade_info.get("c2_dry") else ""
    c3_tag = "Spring" if grade_info.get("c3_spring") else ""
    if grade == "A":
        msg = format_grade_a_message(
            ca, score, current_price, change_pct, vol_c3, cvd_sol, lock_pct,
            vol_c1, vol_c2, vol_c3, drop_pct, smart_buyers, symbol=symbol)
    else:
        badge = signal_type if signal_type else "➖ NEUTRAL"
        msg = format_signal_message(
            badge, ca, score, current_price, change_pct, vol_c3, cvd_sol,
            lock_pct, vol_c1, vol_c2, vol_c3, drop_pct, smart_buyers,
            extra_lines=extra_lines, warn_line=warn_line, symbol=symbol,
            c2_tag=c2_tag, c3_tag=c3_tag)

    # Grade A always notifies. Grade B score is 80 so it notifies.
    # SOS / trap / bearish notify. Grade C is muted.
    is_triggered = False
    if muted:
        is_triggered = False
    elif grade == "A":
        is_triggered = True
    elif grade == "B" and score >= 80:
        is_triggered = True
    elif signal_type in (SIGNAL_SOS, SIGNAL_TRAP, SIGNAL_BEARISH):
        is_triggered = True

    if is_triggered:
        print("Sending notification...")
        send_telegram_notif(msg)
        send_discord_notif(msg)
        sig_data = {
            "ts": now_ts,
            "ca": ca,
            "symbol": symbol,
            "type": signal_type or "PRE_PUMP_DETECTION",
            "grade": grade,
            "score": score,
            "price_usd": current_price,
            "volume_sol": vol_c3,
            "cvd_sol": cvd_sol,
            "holder_lock_pct": lock_pct,
            "detail": {
                "price_change_pct": change_pct,
                "vol_ratio_vs_baseline": vol_ratio,
                "c1_vol_sol": vol_c1,
                "c2_vol_sol": vol_c2,
                "c3_vol_sol": vol_c3,
                "c2_drop_pct": drop_pct,
                "c2_dry": grade_info["c2_dry"],
                "c3_spring": grade_info["c3_spring"],
                "smart_buyers": [
                    {
                        "address": b.get("address"),
                        "short": b.get("short"),
                        "tags": b.get("tags"),
                        "sol": b.get("sol"),
                        "rank": b.get("rank"),
                    }
                    for b in smart_buyers
                ],
                "reasons": reasons,
            },
        }
        save_signal_to_history(sig_data)

    return {
        "ca": ca,
        "symbol": symbol,
        "score": score,
        "signal_type": signal_type,
        "grade": grade,
        "is_triggered": is_triggered,
        "muted": muted,
        "msg": msg,
        "smart_buyers": smart_buyers,
        "c1": c1,
        "c2": c2,
        "c3": c3,
        "drop_pct": drop_pct,
        "holder_lock_pct": lock_pct,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Run with mock data")
    parser.add_argument("--test-ca", type=str, default=None,
                        help="Evaluate a specific CA")
    args = parser.parse_args()

    print("=== SOLANA MEMECOIN PRE-PUMP & WYCKOFF 15M CRON DETECTOR ===")
    now_ts = int(time.time())
    print(f"now={now_ts} C3_bucket={c3_bucket_start(now_ts)}")

    watchlist = load_watchlist()
    if not watchlist:
        print("Watchlist is empty. Add tokens to watchlist.json first.")

    cas_to_evaluate = []
    if args.test_ca:
        symbol = watchlist.get(args.test_ca, {}).get("symbol", "?")
        cas_to_evaluate.append((args.test_ca, symbol))
    else:
        for ca, meta in (watchlist or {}).items():
            cas_to_evaluate.append((ca, meta.get("symbol", "?")))

    results = []
    for ca, symbol in cas_to_evaluate:
        res = run_pipeline_for_ca(ca, symbol, now_ts, mock_mode=args.mock)
        if res:
            results.append(res)

    print("\nEvaluation Summary:")
    for row in results:
        print(
            f"- CA: {row['ca']} | Score: {row['score']} | "
            f"Signal: {row['signal_type']} | Grade: {row.get('grade')} | "
            f"Triggered: {row['is_triggered']}"
        )


if __name__ == "__main__":
    main()
