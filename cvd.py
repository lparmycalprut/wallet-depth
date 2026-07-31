# -*- coding: utf-8 -*-
"""On-chain CVD via Helius Enhanced API, with optional GMGN trades.

Every DEX swap has a definite direction (no aggressor guessing like on CEX):
  token OUT of pool  -> user BUY
  token INTO pool    -> user SELL
Volumes are measured in SOL (the quote side of the pool).

Data is stored in cvd.json as hourly buckets per CA:
  {ca: {"pool": str, "newest_sig": str, "newest_ts": int,
        "buckets": {hour_ts: {bs, ss, nb, ns, wbs, wss}}}}
  bs/ss  = buy/sell volume (SOL)   nb/ns = trade counts
  wbs/wss = whale buy/sell volume (SOL), swaps >= WHALE_SOL
Small swaps below MIN_SOL are ignored entirely (bot dust noise).
"""
import json
import math
import os
import time

import requests

from core import (HELIUS_ENHANCED_URL, helius_api_get,
                  helius_rpc_request as _core_helius_rpc_request)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CVD_PATH = os.path.join(BASE_DIR, "cvd.json")

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
MIN_SOL = 0.05      # ignore swaps below (~$10) — bot/dust noise
WHALE_SOL = 3.0     # swaps >= this (~$500+) count as whale flow
BUCKET = 3600       # 1-hour buckets (resampled to H4 for divergence)

_sol_price_cache = {"price": 0.0, "ts": 0.0}

# ---------------------------------------------------------------------------
# Compatibility wrapper; key discovery and rotation now live in core.py.
# ---------------------------------------------------------------------------
def helius_rpc_post(payload: dict, timeout: int = 30, retries: int = 3,
                    helius_keys=None):
    """JSON-RPC POST through core.py's shared 429/5xx key rotation."""
    try:
        return _core_helius_rpc_request(
            payload, helius_keys, timeout=timeout, max_attempts=retries)
    except Exception:
        return None


def get_sol_price() -> float:
    """SOL/USD price, cached 10 min — used to convert USDC/USDT-quoted
    pools into SOL-equivalent so thresholds stay consistent."""
    now = time.time()
    if _sol_price_cache["price"] > 0 and \
            now - _sol_price_cache["ts"] < 600:
        return _sol_price_cache["price"]
    try:
        r = requests.get(
            "https://api.dexscreener.com/latest/dex/tokens/" + SOL_MINT,
            timeout=15)
        pairs = (r.json() or {}).get("pairs") or []
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                   reverse=True)
        px = float(pairs[0].get("priceUsd") or 0) if pairs else 0.0
        if px > 0:
            _sol_price_cache.update(price=px, ts=now)
            return px
    except Exception:
        pass
    return _sol_price_cache["price"] or 150.0  # sane fallback


def _quote_rates() -> dict:
    """mint -> SOL per 1 unit of that quote token."""
    sp = get_sol_price()
    usd_to_sol = 1.0 / sp if sp else 0.0
    return {SOL_MINT: 1.0, USDC_MINT: usd_to_sol, USDT_MINT: usd_to_sol}

GMGN_TRADES_URL = "https://gmgn.ai/vas/api/v1/token_trades/sol/{ca}"
GMGN_PAGE_LIMIT = 100
GMGN_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "origin": "https://gmgn.ai",
    "referer": "https://gmgn.ai/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/150.0.0.0 Safari/537.36"),
    "sec-ch-ua": ('"Not;A=Brand";v="8", "Chromium";v="150", '
                  '"Google Chrome";v="150"'),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}
_gmgn_last = {"error": ""}
_gmgn_wallet_meta = {"data": {}}


def get_gmgn_wallet_metadata() -> dict:
    """Per-wallet metadata from the most recent GMGN fetch.

    Only populated when ``use_gmgn=True`` is used.  Keys are wallet
    addresses; values are dicts with ``maker_tags``, ``maker_token_tags``,
    ``total_trade``, ``balance``, ``history_bought_amount``,
    ``history_sold_amount``, ``realized_profit``, ``unrealized_profit``.
    """
    return _gmgn_wallet_meta.get("data") or {}


def _gmgn_build_params() -> dict:
    """Query params matching the live GMGN web client (build tag, device id)."""
    import uuid as _uuid
    params = {
        "from_app": "gmgn",
        "tz_name": "Asia%2FJakarta",
        "tz_offset": "25200",
        "app_lang": "en-US",
        "os": "web",
        "worker": "0",
    }
    try:
        from gmgn_screener import _build_tag, DEVICE_ID, FP_DID
        build = _build_tag()
        params["device_id"] = DEVICE_ID
        params["fp_did"] = FP_DID
        params["client_id"] = f"gmgn_web_{build}"
        params["app_ver"] = build
    except Exception:
        params["device_id"] = str(_uuid.uuid4())
        params["fp_did"] = _uuid.uuid4().hex
        params["client_id"] = "gmgn_web_20260728-2617-057cd43"
        params["app_ver"] = "20260728-2617-057cd43"
    return params


def _set_gmgn_error(message: str) -> None:
    _gmgn_last["error"] = str(message or "").strip()


def get_gmgn_last_error() -> str:
    """Last human-readable GMGN fetch problem, if any.

    The UI reads this after an empty GMGN result so users see whether the
    endpoint was empty, Cloudflare-blocked, rate-limited, or shape-changed.
    """
    return _gmgn_last.get("error") or ""


def _as_float(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value).strip().replace(",", "")
        if not s:
            return default
        return float(s)
    except Exception:
        return default


def _first_nested(obj, *paths, default=None):
    """First non-empty value from dotted paths in a nested GMGN dict."""
    if not isinstance(obj, dict):
        return default
    for path in paths:
        cur = obj
        ok = True
        for part in str(path).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur.get(part)
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return default


def _normalize_ts(value) -> int:
    ts = _as_float(value, 0.0)
    if ts > 10_000_000_000:  # milliseconds / microseconds-ish
        ts /= 1000.0
    if ts > 10_000_000_000:
        ts /= 1000.0
    return int(ts) if ts > 0 else 0


def _gmgn_trade_key(trade: dict) -> str:
    key = _first_nested(
        trade, "id", "transaction_hash", "tx_hash", "txHash", "signature",
        "hash", "tx", default="")
    if key:
        return str(key)
    maker = _first_nested(trade, "maker", "wallet", "maker_info.address",
                          "address", default="")
    ts = _normalize_ts(_first_nested(trade, "timestamp", "time",
                                     "block_time", "created_at"))
    ev = _first_nested(trade, "event", "side", "action", default="")
    return f"gmgn:{maker}:{ts}:{ev}"


def _gmgn_side(trade: dict) -> str | None:
    raw = str(_first_nested(trade, "event", "side", "action",
                            "trade_type", default="")).lower()
    if "buy" in raw:
        return "buy"
    if "sell" in raw:
        return "sell"
    return None


def _gmgn_sol_equivalent(trade: dict) -> float:
    """Map GMGN trade into SOL-equivalent volume.

    Priority:
      1. ``amount_usd`` → convert to SOL via SOL/USD price  (most reliable)
      2. ``quote_amount`` when quote is verifiably SOL       (lamports-aware)
      3. ``quote_amount`` when quote is USDC/USDT            (convert)
      4. fallback: 0.0

    IMPORTANT: never treat an unverified ``quote_amount`` as SOL.
    GMGN sometimes returns the *base token amount* in this field
    (e.g. 2.4M tokens of a micro-cap), which would inflate CVD
    by 6+ orders of magnitude.
    """
    sp = get_sol_price()

    # ── 1. amount_usd (GMGN-computed, most trustworthy) ──────────────
    usd_amount = _as_float(_first_nested(
        trade, "amount_usd", "amountUSD", "cost_usd", "costUsd", "usd",
        "value_usd", "valueUsd", "volume_usd", "volumeUsd",
        "trade_usd", "tradeUsd", "usd_value", "usdValue"), 0.0)
    if usd_amount > 0:
        return usd_amount / sp if sp else 0.0

    # ── 2. quote_amount (only when we can verify the quote token) ────
    quote_amount = _as_float(_first_nested(
        trade, "quote_amount", "quoteAmount", "quote_amount_ui",
        "quoteAmountUi", "quote_amount_decimal"), 0.0)
    quote_addr = str(_first_nested(
        trade, "quote_address", "quote_token_address", "quote_mint",
        "quote_token.address", "quoteToken.address", default="") or "")
    quote_sym = str(_first_nested(
        trade, "quote_symbol", "quote_token.symbol", "quoteToken.symbol",
        default="") or "").lower()

    if quote_amount <= 0:
        return 0.0

    # USDC/USDT-quoted pool: convert to SOL
    if quote_addr in (USDC_MINT, USDT_MINT) or quote_sym in ("usdc", "usdt"):
        return quote_amount / sp if sp else 0.0

    # SOL/WSOL-quoted pool: normalize lamports if needed
    if quote_addr == SOL_MINT or quote_sym in ("sol", "wsol"):
        if quote_amount > 10_000_000:          # raw lamports
            quote_amount /= 1_000_000_000
        return quote_amount

    # ── 3. Unknown quote token → do NOT guess ───────────────────────
    # Returning quote_amount when the quote currency is unknown is
    # dangerous — GMGN trades API sometimes puts the *base* token
    # amount here, which for a micro-cap looks like millions of "SOL".
    # Better to return 0.0 (the swap gets filtered by MIN_SOL anyway)
    # than produce nonsense CVD data.
    return 0.0

def gmgn_trade_to_swap(trade: dict):
    """Convert one GMGN trade into (side, sol_equivalent, ts, wallet)."""
    if not isinstance(trade, dict):
        return None
    side = _gmgn_side(trade)
    sol_eq = _gmgn_sol_equivalent(trade)
    ts = _normalize_ts(_first_nested(
        trade, "timestamp", "time", "block_time", "created_at",
        "createdAt"))
    wallet = _first_nested(trade, "maker", "wallet", "maker_info.address",
                           "address", "user_address", default="") or ""
    if side not in ("buy", "sell") or sol_eq <= 0 or ts <= 0:
        return None
    # ── Sanity cap: no single swap is legitimately > 1,000 SOL ─────
    # Values above this threshold are almost certainly a data-mapping
    # error (e.g. GMGN returned base-token raw amount in quote_amount).
    MAX_SWAP_SOL = 1000.0
    if sol_eq > MAX_SWAP_SOL:
        return None
    return (side, float(sol_eq), int(ts), str(wallet))

def _find_trade_list(obj):
    """Locate the trade array across several GMGN response shapes."""
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if not isinstance(obj, dict):
        return []
    priority = ("trades", "history", "activities", "items", "list",
                "rows", "transactions", "result", "data")
    for key in priority:
        if key in obj:
            found = _find_trade_list(obj.get(key))
            if found:
                return found
    for val in obj.values():
        found = _find_trade_list(val)
        if found:
            return found
    return []


def _gmgn_cursor(payload, trades) -> str | None:
    cur = _first_nested(
        payload, "data.next", "data.next_cursor", "data.nextCursor",
        "data.cursor", "pagination.next", "pagination.next_cursor",
        "next", "next_cursor", "nextCursor", "cursor", default=None)
    return str(cur) if cur else None


def _gmgn_http_get(url: str, *, params: dict, timeout: int):
    """GET GMGN with curl_cffi browser TLS when installed; fallback safe."""
    try:
        from curl_cffi import requests as cr
        last_exc = None
        for imp in ("chrome", "chrome131", "safari17_0"):
            try:
                return cr.get(url, params=params, headers=GMGN_HEADERS,
                              impersonate=imp, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        if last_exc:
            raise last_exc
    except ImportError:
        return requests.get(url, params=params, headers=GMGN_HEADERS,
                            timeout=timeout)


def _fetch_gmgn_page(ca: str, *, cursor=None, limit=GMGN_PAGE_LIMIT,
                     timeout=25, retries=3, from_ts=None, to_ts=None):
    url = GMGN_TRADES_URL.format(ca=ca)
    params = _gmgn_build_params()
    params["limit"] = max(1, min(int(limit or GMGN_PAGE_LIMIT), 100))
    if cursor:
        params["cursor"] = cursor
    if from_ts is not None:
        params["from"] = int(from_ts)
    if to_ts is not None:
        params["to"] = int(to_ts)
    delay = 0.5
    last = ""
    for _ in range(retries):
        try:
            r = _gmgn_http_get(url, params=params, timeout=timeout)
            status = getattr(r, "status_code", None)
            if status != 200:
                last = f"HTTP {status}"
                if status in (408, 425, 429) or (status and status >= 500):
                    time.sleep(delay)
                    delay *= 2
                    continue
                _set_gmgn_error(f"GMGN Trades API returned {last}.")
                return None, None
            payload = r.json() or {}
            if isinstance(payload, dict):
                code = payload.get("code")
                if code not in (None, 0, "0", "success"):
                    msg = payload.get("message") or payload.get("msg") or code
                    last = f"api code={code} {msg}"
                    _set_gmgn_error(f"GMGN Trades API returned {last}.")
                    return None, None
            trades = _find_trade_list(payload)
            return trades, _gmgn_cursor(payload, trades)
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(delay)
            delay *= 2
    _set_gmgn_error(f"GMGN Trades API fetch failed: {last or 'no response'}.")
    return None, None


def _extract_gmgn_trade_meta(trade: dict) -> dict:
    """Pull GMGN-specific metadata fields from one trade dict.

    Returns a dict suitable for per-wallet annotation — keys are the
    ``maker_tags``, ``balance``, ``total_trade``, etc. fields the user
    wants surfaced alongside the standard 4-tuple swap.
    """
    tags_raw = _first_nested(trade, "maker_tags", "makerTags", default=[])
    if isinstance(tags_raw, str):
        tags_raw = [t.strip() for t in tags_raw.split(",") if t.strip()]
    tok_tags_raw = _first_nested(trade, "maker_token_tags", "makerTokenTags",
                                 default=[])
    if isinstance(tok_tags_raw, str):
        tok_tags_raw = [t.strip() for t in tok_tags_raw.split(",")
                        if t.strip()]
    return {
        "maker_tags": list(tags_raw) if isinstance(tags_raw, list) else [],
        "maker_token_tags": (list(tok_tags_raw)
                             if isinstance(tok_tags_raw, list) else []),
        "total_trade": int(_as_float(
            _first_nested(trade, "total_trade", "totalTrade", default=0))),
        "balance": _as_float(
            _first_nested(trade, "balance", "token_balance", default=0)),
        "history_bought_amount": _as_float(_first_nested(
            trade, "history_bought_amount", "historyBoughtAmount",
            default=0)),
        "history_sold_amount": _as_float(_first_nested(
            trade, "history_sold_amount", "historySoldAmount", default=0)),
        "realized_profit": _as_float(_first_nested(
            trade, "realized_profit", "realizedProfit", default=0)),
        "unrealized_profit": _as_float(_first_nested(
            trade, "unrealized_profit", "unrealizedProfit", default=0)),
    }


def fetch_gmgn_swaps(ca: str, *, stop_sig=None, stop_ts=None, max_pages=40,
                     sleep=0.15, page_limit=GMGN_PAGE_LIMIT,
                     from_ts=None, to_ts=None):
    """Fetch GMGN Token Trades and map them to CVD swap tuples.

    GMGN fields are mapped as requested:
    ``event`` -> buy/sell, ``quote_amount``/``amount_usd`` -> SOL-equivalent,
    ``timestamp`` -> ts, and ``maker`` -> wallet.

    Returns the same tuple shape as :func:`fetch_swaps`:
    ``(swaps, newest_sig, newest_ts, hit_stop)``. On API failure or an empty
    response it returns an empty list and records a readable reason in
    :func:`get_gmgn_last_error` instead of raising.
    """
    _set_gmgn_error("")
    _gmgn_wallet_meta["data"] = {}
    swaps, cursor = [], None
    newest_sig, newest_ts, hit_stop = None, None, False
    seen_trades, seen_cursors = set(), set()
    raw_seen = mapped_seen = 0
    stopped_by_cutoff = False
    wallet_meta = {}

    for _ in range(max_pages):
        raw_trades, next_cursor = _fetch_gmgn_page(
            ca, cursor=cursor, limit=page_limit,
            from_ts=from_ts, to_ts=to_ts)
        if raw_trades is None:
            break
        if not raw_trades:
            break
        raw_seen += len(raw_trades)
        raw_trades = sorted(
            raw_trades,
            key=lambda t: _normalize_ts(_first_nested(
                t, "timestamp", "time", "block_time", "created_at")),
            reverse=True)
        new_on_page = 0
        for trade in raw_trades:
            key = _gmgn_trade_key(trade)
            if key in seen_trades:
                continue
            seen_trades.add(key)
            new_on_page += 1
            ts = _normalize_ts(_first_nested(
                trade, "timestamp", "time", "block_time", "created_at"))
            if newest_sig is None:
                newest_sig, newest_ts = key, ts
            if stop_sig and key == stop_sig:
                hit_stop = True
                break
            if stop_ts and ts and ts <= stop_ts:
                hit_stop = True
                stopped_by_cutoff = True
                break
            s = gmgn_trade_to_swap(trade)
            if s:
                mapped_seen += 1
                if s[1] >= MIN_SOL:
                    swaps.append(s)
                # collect per-wallet metadata (last trade wins)
                w = s[3]
                if w:
                    try:
                        wallet_meta[w] = _extract_gmgn_trade_meta(trade)
                    except Exception:
                        pass
        if hit_stop:
            break
        if new_on_page == 0:
            _set_gmgn_error("GMGN pagination returned duplicate trades only.")
            break
        cursor = next_cursor
        if not cursor and len(raw_trades) >= page_limit:
            cursor = _gmgn_trade_key(raw_trades[-1])
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        time.sleep(sleep)

    if not raw_seen and not get_gmgn_last_error():
        _set_gmgn_error("GMGN Trades API returned no trades for this token.")
    elif stopped_by_cutoff and not swaps and not get_gmgn_last_error():
        _set_gmgn_error("GMGN returned no trades newer than the selected "
                        "window.")
    elif raw_seen and not mapped_seen and not get_gmgn_last_error():
        _set_gmgn_error(
            "GMGN returned trades, but none had event/timestamp/volume "
            "fields that could be mapped to CVD swaps.")
    elif mapped_seen and not swaps and not get_gmgn_last_error():
        _set_gmgn_error(
            f"GMGN returned trades, but all were below {MIN_SOL:g} SOL.")
    _gmgn_wallet_meta["data"] = wallet_meta
    return swaps, newest_sig, newest_ts, hit_stop


def _load_json_tolerant(path):
    """Load JSON; if the file contains git conflict markers, parse the
    newest side of the conflict instead of failing."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    if "<<<<<<<" in raw:
        import re as _re
        m = _re.search(r"<<<<<<<[^\n]*\n(.*?)\n=======\n(.*?)\n>>>>>>>",
                       raw, _re.S)
        if m:
            for side in (m.group(2), m.group(1)):  # prefer incoming side
                try:
                    return json.loads(side)
                except Exception:
                    continue
    return None


def load_cvd() -> dict:
    return _load_json_tolerant(CVD_PATH) or {}


def save_cvd(state: dict) -> None:
    import tempfile
    dir_name = os.path.dirname(os.path.abspath(CVD_PATH))
    fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="cvd_temp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, separators=(",", ":"))
        os.replace(temp_path, CVD_PATH)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def classify_swap(tx: dict, pool: str, ca: str):
    """Return (side, sol_equivalent, ts, wallet) or None.
    Works for SOL-quoted AND USDC/USDT-quoted pools (converted to SOL)."""
    rates = _quote_rates()
    ca_in = ca_out = 0.0
    q_in = q_out = 0.0   # quote value in SOL-equivalent
    for x in (tx.get("tokenTransfers") or []):
        amt = float(x.get("tokenAmount") or 0)
        mint = x.get("mint")
        if mint == ca:
            if x.get("fromUserAccount") == pool:
                ca_out += amt
            elif x.get("toUserAccount") == pool:
                ca_in += amt
        elif mint in rates:
            sol_eq = amt * rates[mint]
            if mint == SOL_MINT and sol_eq > 10_000_000:
                sol_eq /= 1_000_000_000
            if x.get("fromUserAccount") == pool:
                q_out += sol_eq
            elif x.get("toUserAccount") == pool:
                q_in += sol_eq
    ts = tx.get("timestamp") or 0
    wallet = tx.get("feePayer") or ""
    if q_in > 1000.0 or q_out > 1000.0:
        return None
    if ca_out > ca_in and q_in > 0:        # token left pool -> BUY
        return ("buy", q_in, ts, wallet)
    if ca_in > ca_out and q_out > 0:       # token entered pool -> SELL
        return ("sell", q_out, ts, wallet)
    return None


def _fetch_page(api_key, pool: str, before=None, *, retries=4):
    """One Enhanced-API page using the shared rotating Helius key pool."""
    params = {"limit": 100, "type": "SWAP"}
    if before:
        params["before"] = before
    try:
        return helius_api_get(
            f"{HELIUS_ENHANCED_URL}/v0/addresses/{pool}/transactions",
            params=params, helius_keys=api_key,
            headers={"User-Agent": "Mozilla/5.0"}, timeout=40,
            max_attempts=retries)
    except Exception:
        return None


def fetch_swaps(api_key: str, pool: str, ca: str, *, stop_sig=None,
                stop_ts=None, max_pages=40, sleep=0.15,
                use_gmgn: bool = False, from_ts=None, to_ts=None):
    """Fetch swaps newest-first until stop_sig/stop_ts/max_pages.

    By default this uses the existing Helius Enhanced API path. When
    ``use_gmgn`` is true, it uses GMGN Token Trades API instead and returns
    the same tuple shape.
    """
    if use_gmgn:
        return fetch_gmgn_swaps(ca, stop_sig=stop_sig, stop_ts=stop_ts,
                                max_pages=max_pages, sleep=sleep,
                                from_ts=from_ts, to_ts=to_ts)
    swaps, before = [], None
    newest_sig, newest_ts, hit_stop = None, None, False
    for _ in range(max_pages):
        page = _fetch_page(api_key, pool, before)
        if page is None:   # all retries failed -> stop but keep what we have
            break
        if not page:
            break
        if newest_sig is None:
            newest_sig = page[0].get("signature")
            newest_ts = page[0].get("timestamp")
        for tx in page:
            if stop_sig and tx.get("signature") == stop_sig:
                hit_stop = True
                break
            if stop_ts and (tx.get("timestamp") or 0) <= stop_ts:
                hit_stop = True
                break
            s = classify_swap(tx, pool, ca)
            if s and s[1] >= MIN_SOL:
                swaps.append(s)
        if hit_stop:
            break
        before = page[-1].get("signature")
        time.sleep(sleep)
    return swaps, newest_sig, newest_ts, hit_stop


def bucketize(swaps) -> dict:
    out = {}
    for s in swaps:
        side, sol, ts = s[0], s[1], s[2]
        b = str(int(ts // BUCKET * BUCKET))
        c = out.setdefault(b, {"bs": 0.0, "ss": 0.0, "nb": 0, "ns": 0,
                               "wbs": 0.0, "wss": 0.0})
        if side == "buy":
            c["bs"] += sol
            c["nb"] += 1
            if sol >= WHALE_SOL:
                c["wbs"] += sol
        else:
            c["ss"] += sol
            c["ns"] += 1
            if sol >= WHALE_SOL:
                c["wss"] += sol
    return out


def update_token_cvd(api_key: str, ca: str, pool: str, *,
                     max_pages=40, use_gmgn: bool = False) -> dict:
    """Incremental update: fetch swaps since last stored signature.
    Also keeps raw swaps of the last 24h (with wallets) so the dashboard
    can show a COMPLETE window without a huge live fetch.

    When ``use_gmgn=True``, uses GMGN Token Trades API instead of Helius.
    No API key is required for GMGN — the ``api_key`` argument is ignored."""
    state = load_cvd()
    entry = state.get(ca) or {"pool": pool, "buckets": {}}
    stop_sig = entry.get("newest_sig") if not use_gmgn else None
    stop_ts = entry.get("newest_ts")
    swaps, new_sig, new_ts, hit = fetch_swaps(
        api_key, pool, ca, stop_sig=stop_sig, stop_ts=stop_ts,
        max_pages=max_pages, use_gmgn=use_gmgn)
    fresh = bucketize(swaps)
    for b, c in fresh.items():
        old = entry["buckets"].get(b)
        if old:
            for k in c:
                old[k] = old.get(k, 0) + c[k]
        else:
            entry["buckets"][b] = c
    # --- raw swap store (last 48h, incl. wallet) for complete-window UI ----
    cutoff_raw = time.time() - 48 * 3600
    raw = entry.get("swaps") or []
    raw.extend([list(s) for s in swaps])
    # deduplicate swaps to prevent inflated/duplicate values
    seen_swaps = {}
    for s in raw:
        if len(s) >= 4:
            key = (s[0], float(s[1]), int(s[2]), str(s[3]))
            seen_swaps[key] = s
    ordered_swap_keys = sorted(seen_swaps, key=lambda key: key[2])
    entry["swaps"] = [seen_swaps[key] for key in ordered_swap_keys
                      if key[2] >= cutoff_raw]
    if new_sig:
        entry["newest_sig"] = new_sig
        entry["newest_ts"] = new_ts
    entry["pool"] = pool
    entry["gap"] = bool(stop_sig) and not hit and bool(swaps)
    entry["updated"] = int(time.time())
    # keep last 14 days only
    cutoff = time.time() - 14 * 86400
    entry["buckets"] = {b: c for b, c in entry["buckets"].items()
                        if int(b) >= cutoff}
    state[ca] = entry
    save_cvd(state)
    return {"new_swaps": len(swaps), "buckets": len(entry["buckets"]),
            "gap": entry["gap"]}


# ---------------------------------------------------------------------------
# Wallet behaviour profiling — pure accumulators / light holders / traders
# ---------------------------------------------------------------------------
def wallet_profiles(swaps, *, pure_tol=0.05, light_tol=0.10, trader_tol=0.50):
    """Classify wallets by behaviour within the window.

    swaps: iterable of (side, sol, ts, wallet).

    Profile taxonomy (buy-side, sorted by conviction):
      - 'pure_accum'  : sells <= 5%  of buys  (bought & held, zero doubt)
      - 'light_holder' : sells > 5% but < 10%  of buys  (still holding 90%+)
      - 'trader'       : sells >= 10% but <= 50% of buys  (sold some, still long)
      - 'two_way'      : sells > 50% of buys AND buys > 5% of sells  (MM/bot)
      - 'pure_dist'    : buys <= 5% of sells  (sold & left)

    The same logic applies symmetrically on the sell side for pure_dist.
    """
    w = {}
    for side, sol, ts, wallet in swaps:
        if not wallet:
            continue
        d = w.setdefault(wallet, {"buy": 0.0, "sell": 0.0, "n_buy": 0,
                                  "n_sell": 0, "max_swap": 0.0,
                                  "first_ts": ts, "last_ts": ts})
        if side == "buy":
            d["buy"] += sol
            d["n_buy"] += 1
        else:
            d["sell"] += sol
            d["n_sell"] += 1
        d["max_swap"] = max(d["max_swap"], sol)
        d["first_ts"] = min(d["first_ts"], ts)
        d["last_ts"] = max(d["last_ts"], ts)
    for wallet, d in w.items():
        if d["buy"] > 0 and d["sell"] <= d["buy"] * pure_tol:
            d["profile"] = "pure_accum"
        elif d["buy"] > 0 and d["sell"] < d["buy"] * light_tol:
            d["profile"] = "light_holder"
        elif d["buy"] > 0 and d["sell"] <= d["buy"] * trader_tol:
            d["profile"] = "trader"
        elif d["sell"] > 0 and d["buy"] <= d["sell"] * pure_tol:
            d["profile"] = "pure_dist"
        else:
            d["profile"] = "two_way"
        vol = d["buy"] + d["sell"]
        d["dca"] = (d["n_buy"] + d["n_sell"]) >= 4 and \
            d["max_swap"] < vol * 0.5
    return w


# Weight applied to each profile's buy volume in conviction calculation.
# pure_accum = 100% (held everything), light_holder = 75%, trader = 30%.
PROFILE_WEIGHTS = {
    "pure_accum": 1.00,
    "light_holder": 0.75,
    "trader": 0.30,
    "two_way": 0.0,
    "pure_dist": 0.0,
}


def wallet_profile_cohort(profile: dict, *, side: str = "buy",
                          whale_min_sol: float = WHALE_SOL,
                          dolphin_min_sol: float = 1.0) -> str:
    """Return a display cohort for one wallet profile.

    The CVD UI uses volume cohorts, not holder-rank cohorts: whale means
    the relevant side's total SOL flow reached ``whale_min_sol``; dolphin
    means it reached ``dolphin_min_sol`` but stayed below whale size.
    ``side`` is usually ``"buy"`` for accumulator/light/trader rows and
    ``"sell"`` for distributor/no-buy-holder rows.
    """
    d = profile or {}
    key = "sell" if side == "sell" else "buy"
    try:
        vol = float(d.get(key) or 0.0)
    except Exception:
        vol = 0.0
    if vol >= whale_min_sol:
        return "🐋 WHALE"
    if vol >= dolphin_min_sol:
        return "🐬 DOLPHIN"
    return "🐟 MINNOW"


def split_wallet_profile_cohorts(profiles, *, whale_min_sol=WHALE_SOL,
                                 dolphin_min_sol=1.0) -> dict:
    """Split wallet profiles into the UI's separate cohort lists.

    Returns lists of ``(wallet, profile, cohort_label)`` sorted by the
    dominant side's SOL volume.  Pure accumulators/distributors are split
    into whale and dolphin buckets; light holders and traders are kept as
    their own lists with a whale/dolphin/minnow label attached.
    """
    out = {
        "whale_accumulators": [],
        "dolphin_accumulators": [],
        "whale_distributors": [],
        "dolphin_distributors": [],
        "light_holders": [],
        "traders": [],
    }
    for w, d in (profiles or {}).items():
        if not w or not isinstance(d, dict):
            continue
        p = d.get("profile")
        buy = float(d.get("buy") or 0.0)
        sell = float(d.get("sell") or 0.0)
        if p == "pure_accum":
            if buy >= whale_min_sol:
                out["whale_accumulators"].append((w, d, "🐋 WHALE"))
            elif buy >= dolphin_min_sol:
                out["dolphin_accumulators"].append((w, d, "🐬 DOLPHIN"))
        elif p == "pure_dist":
            if sell >= whale_min_sol:
                out["whale_distributors"].append((w, d, "🐋 WHALE"))
            elif sell >= dolphin_min_sol:
                out["dolphin_distributors"].append((w, d, "🐬 DOLPHIN"))
        elif p == "light_holder" and buy >= dolphin_min_sol:
            out["light_holders"].append(
                (w, d, wallet_profile_cohort(
                    d, side="buy", whale_min_sol=whale_min_sol,
                    dolphin_min_sol=dolphin_min_sol)))
        elif p == "trader" and buy >= dolphin_min_sol:
            out["traders"].append(
                (w, d, wallet_profile_cohort(
                    d, side="buy", whale_min_sol=whale_min_sol,
                    dolphin_min_sol=dolphin_min_sol)))

    for key in ("whale_accumulators", "dolphin_accumulators",
                "light_holders", "traders"):
        out[key].sort(key=lambda x: -float(x[1].get("buy") or 0.0))
    for key in ("whale_distributors", "dolphin_distributors"):
        out[key].sort(key=lambda x: -float(x[1].get("sell") or 0.0))
    return out


def cohort_activity_summary(profiles, *, whale_min_sol=WHALE_SOL,
                            dolphin_min_sol=1.0) -> dict:
    """Aggregate whale/dolphin buy/sell/net activity for the CVD UI."""
    c = split_wallet_profile_cohorts(
        profiles, whale_min_sol=whale_min_sol,
        dolphin_min_sol=dolphin_min_sol)
    whale_buy = sum(float(d.get("buy") or 0.0)
                    for _w, d, _co in c["whale_accumulators"] +
                    c["light_holders"]
                    if float(d.get("buy") or 0.0) >= whale_min_sol)
    whale_sell = sum(float(d.get("sell") or 0.0)
                     for _w, d, _co in c["whale_distributors"])
    dolphin_buy = sum(float(d.get("buy") or 0.0)
                      for _w, d, _co in c["dolphin_accumulators"] +
                      c["light_holders"]
                      if dolphin_min_sol <= float(d.get("buy") or 0.0)
                      < whale_min_sol)
    dolphin_sell = sum(float(d.get("sell") or 0.0)
                       for _w, d, _co in c["dolphin_distributors"])
    whale_buyers = {
        w for w, d, _co in c["whale_accumulators"] + c["light_holders"]
        if float(d.get("buy") or 0.0) >= whale_min_sol
    }
    dolphin_buyers = {
        w for w, d, _co in c["dolphin_accumulators"] + c["light_holders"]
        if dolphin_min_sol <= float(d.get("buy") or 0.0) < whale_min_sol
    }
    return {
        "whale_buy": whale_buy,
        "whale_sell": whale_sell,
        "whale_net": whale_buy - whale_sell,
        "whale_buyers": len(whale_buyers),
        "whale_sellers": len(c["whale_distributors"]),
        "dolphin_buy": dolphin_buy,
        "dolphin_sell": dolphin_sell,
        "dolphin_net": dolphin_buy - dolphin_sell,
        "dolphin_buyers": len(dolphin_buyers),
        "dolphin_sellers": len(c["dolphin_distributors"]),
    }


def detect_no_buy_holders(profiles, wallet_meta, *,
                          whale_min_sol=WHALE_SOL,
                          dolphin_min_sol=1.0,
                          min_balance: float = 0.0) -> list:
    """Find traded wallets that bought nothing in-window but still hold.

    ``wallet_meta`` is the GMGN per-wallet metadata collected during the
    trades fetch.  Because GMGN only annotates wallets seen in fetched
    trades, this detects *sell-only participants that still have a current
    token balance*.  Passive holders that made no swap at all require a
    separate holder-list scan in the UI.
    """
    rows = []
    for w, d in (profiles or {}).items():
        if not w or not isinstance(d, dict):
            continue
        if int(d.get("n_buy") or 0) > 0:
            continue
        m = (wallet_meta or {}).get(w) or {}
        try:
            bal = float(m.get("balance") or 0.0)
        except Exception:
            bal = 0.0
        if bal <= min_balance:
            continue
        cohort = wallet_profile_cohort(
            d, side="sell", whale_min_sol=whale_min_sol,
            dolphin_min_sol=dolphin_min_sol)
        rows.append({
            "wallet": w,
            "cohort": cohort,
            "profile": d.get("profile", "?"),
            "buy": float(d.get("buy") or 0.0),
            "sell": float(d.get("sell") or 0.0),
            "n_buy": int(d.get("n_buy") or 0),
            "n_sell": int(d.get("n_sell") or 0),
            "balance": bal,
            "history_bought_amount": float(
                m.get("history_bought_amount") or 0.0),
            "history_sold_amount": float(
                m.get("history_sold_amount") or 0.0),
            "total_trade": int(m.get("total_trade") or 0),
            "tags": list(m.get("maker_tags") or []),
            "token_tags": list(m.get("maker_token_tags") or []),
        })
    rows.sort(key=lambda r: (-r["sell"], -r["balance"]))
    return rows


def conviction_split(profiles, *, whale_min_sol=3.0):
    """How much buy volume is 'held' vs recycled by two-way traders.

    Each profile's buy volume is weighted by :data:`PROFILE_WEIGHTS`:
    pure_accum 100%, light_holder 75%, trader 30%, two_way 0%.

    Also returns per-profile counts and volumes for the UI.
    """
    pure_buy = lh_buy = trader_buy = tw_buy = 0.0
    pure_sell = tw_sell = 0.0
    n_pure = n_lh = n_trader = 0
    for d in profiles.values():
        p = d["profile"]
        if p == "pure_accum" and d["buy"] >= whale_min_sol:
            pure_buy += d["buy"]
            n_pure += 1
        elif p == "light_holder" and d["buy"] >= whale_min_sol:
            lh_buy += d["buy"]
            n_lh += 1
        elif p == "trader" and d["buy"] >= whale_min_sol:
            trader_buy += d["buy"]
            n_trader += 1
        elif p == "pure_dist" and d["sell"] >= whale_min_sol:
            pure_sell += d["sell"]
        elif p == "two_way":
            tw_buy += d["buy"]
            tw_sell += d["sell"]
    effective_buy = (pure_buy * PROFILE_WEIGHTS["pure_accum"]
                     + lh_buy * PROFILE_WEIGHTS["light_holder"]
                     + trader_buy * PROFILE_WEIGHTS["trader"])
    total_buy = pure_buy + lh_buy + trader_buy + tw_buy
    conviction = effective_buy / total_buy * 100 if total_buy else 0.0
    return {"pure_buy": pure_buy, "lh_buy": lh_buy, "trader_buy": trader_buy,
            "pure_sell": pure_sell,
            "tw_buy": tw_buy, "tw_sell": tw_sell,
            "effective_buy": effective_buy,
            "conviction_pct": conviction,
            "n_pure": n_pure, "n_lh": n_lh, "n_trader": n_trader}


# ---------------------------------------------------------------------------
# Conviction history — recorded by the cron every run, shown on the landing
# page so LP players can see at a glance whether a pair is still alive.
# ---------------------------------------------------------------------------
CONV_PATH = os.path.join(BASE_DIR, "conviction.json")


_conv_remote_cache = {"data": None, "ts": 0.0}


def load_conviction() -> dict:
    """{ca: [{ts, conviction, pure_buy, pure_sell, net_pure, vol}]}

    On Streamlit Cloud the local file is frozen at deploy time while the
    hourly cron keeps committing fresh points to the repo — so if the
    local copy looks stale (newest point older than ~90 min), pull the
    fresh copy from GitHub raw (cached 10 min) and merge."""
    local = _load_json_tolerant(CONV_PATH) or {}

    newest = 0
    for pts in local.values():
        if pts:
            newest = max(newest, pts[-1].get("ts") or 0)
    fresh_enough = newest and (time.time() - newest) < 90 * 60
    if fresh_enough:
        return local

    now = time.time()
    if _conv_remote_cache["data"] is not None and \
            now - _conv_remote_cache["ts"] < 600:
        remote = _conv_remote_cache["data"]
    else:
        remote = None
        try:
            r = requests.get(
                "https://raw.githubusercontent.com/lparmycalprut/"
                "wallet-depth/main/conviction.json",
                params={"t": int(now)}, timeout=10)
            if r.status_code == 200:
                remote = r.json() or {}
                _conv_remote_cache.update(data=remote, ts=now)
        except Exception:
            pass
    if not remote:
        return local

    # merge: union of points per CA, dedup by ts
    merged = dict(local)
    for ca, pts in remote.items():
        seen = {p["ts"] for p in merged.get(ca, [])}
        merged.setdefault(ca, [])
        merged[ca].extend([p for p in pts if p["ts"] not in seen])
        merged[ca].sort(key=lambda p: p["ts"])
    try:
        with open(CONV_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, separators=(",", ":"))
    except Exception:
        pass
    return merged


def record_conviction(ca: str, *, window_h: int = 6) -> dict | None:
    """Compute conviction over the last `window_h` from the swap store and
    append it to conviction.json. Returns the point or None.

    Persistence bonus: if the count of pure_accum + light_holder wallets
    increased compared to the previous cron point, conviction gets +3%
    per consecutive increase, capped at +15%.
    """
    swaps = get_recent_swaps(ca, window_h)
    if not swaps:
        return None
    profiles = wallet_profiles(swaps)
    conv = conviction_split(profiles, whale_min_sol=WHALE_SOL)
    vol = sum(s[1] for s in swaps)

    # Persistence bonus: +3% per consecutive increase in holder count,
    # capped at +15%.
    _PERSIST_STEP = 3.0
    _PERSIST_CAP = 15.0
    _holder_count = conv["n_pure"] + conv["n_lh"]
    _prev_holder_count = None
    _consecutive_ups = 0
    hist = load_conviction()
    arr = hist.get(ca, [])
    if arr:
        _prev_holder_count = arr[-1].get("holder_count")
        _consecutive_ups = arr[-1].get("consecutive_ups", 0)
    if _prev_holder_count is not None and _holder_count > _prev_holder_count:
        _consecutive_ups += 1
    else:
        _consecutive_ups = 0
    _persist_bonus = min(_consecutive_ups * _PERSIST_STEP, _PERSIST_CAP)
    _conv_final = min(conv["conviction_pct"] + _persist_bonus, 100.0)

    point = {"ts": int(time.time()),
             "conviction": round(_conv_final, 1),
             "conviction_base": round(conv["conviction_pct"], 1),
             "persist_bonus": round(_persist_bonus, 1),
             "pure_buy": round(conv["pure_buy"], 1),
             "lh_buy": round(conv["lh_buy"], 1),
             "trader_buy": round(conv["trader_buy"], 1),
             "pure_sell": round(conv["pure_sell"], 1),
             "net_pure": round(conv["pure_buy"] - conv["pure_sell"], 1),
             "vol": round(vol, 1), "swaps": len(swaps),
             "holder_count": _holder_count,
             "consecutive_ups": _consecutive_ups}
    arr = hist.setdefault(ca, [])
    arr.append(point)
    # keep last 7 days of points
    cutoff = time.time() - 7 * 86400
    hist[ca] = [p for p in arr if p["ts"] >= cutoff]
    import tempfile
    dir_name = os.path.dirname(os.path.abspath(CONV_PATH))
    fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="conv_temp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(hist, f, separators=(",", ":"))
        os.replace(temp_path, CONV_PATH)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        # Callers must not report a successful refresh when the new
        # conviction point never reached disk.
        raise
    return point


def get_recent_swaps(ca: str, hours: int = 12):
    """Raw swaps [(side, sol, ts, wallet)] from the store, last N hours (store keeps 48h)."""
    state = load_cvd()
    entry = state.get(ca)
    if not entry or not entry.get("swaps"):
        return []
    cutoff = time.time() - hours * 3600
    out = [tuple(s) for s in entry["swaps"] if (s[2] or 0) >= cutoff]
    out.sort(key=lambda s: s[2])
    return out


# ---------------------------------------------------------------------------
# Market phase detection (Wyckoff-style heuristic, read-only)
# ---------------------------------------------------------------------------
def detect_phase(ca: str, price_change_24h: float | None = None,
                 price_change_6h: float | None = None) -> dict:
    """Classify the market phase from data we ALREADY have:
    conviction history (conviction.json) + 24h/6h price change (DexScreener,
    passed in by the caller — no new fetches here).

    Returns {"phase": str, "confidence": "low"|"medium"|"high",
             "reason": short explanation for the tooltip}.
    Heuristic only — not a trading signal.
    """
    pts = (load_conviction() or {}).get(ca) or []
    if not pts:
        return {"phase": "Neutral/Choppy", "confidence": "low",
                "reason": "no conviction history yet (cron still filling)"}

    last = pts[-1]
    cv = float(last.get("conviction") or 0)
    np_now = float(last.get("net_pure") or 0)
    vol_now = float(last.get("vol") or 0)
    chg = price_change_24h  # may be None
    chg6 = price_change_6h  # may be None

    prev = pts[-2] if len(pts) >= 2 else None
    cv_prev = float(prev["conviction"]) if prev else None
    np_prev = float(prev.get("net_pure") or 0) if prev else None
    vol_prev = float(prev.get("vol") or 0) if prev else None

    cv_rising = cv_prev is not None and cv > cv_prev
    cv_falling = cv_prev is not None and cv < cv_prev
    np_flipped_neg = np_prev is not None and np_prev >= 0 and np_now < 0
    vol_rising = vol_prev is not None and vol_prev > 0 and         vol_now > vol_prev * 1.15

    # confidence: need >=3 cron points to talk about "trend"
    confidence = "low" if len(pts) < 3 else "medium"
    if len(pts) >= 3 and chg is not None:
        confidence = "high"

    # Price thresholds tuned for memecoins: 20% in 24h is still "flat",
    # a real Markup/Markdown needs 25%+ in 6h or 50%+ in 24h.
    price_flat = chg is not None and -20 <= chg <= 20
    price_up_big = (chg is not None and chg > 50) or         (chg6 is not None and chg6 > 25)
    price_up_small = chg is not None and 0 < chg <= 50 and not price_up_big
    price_down_big = (chg is not None and chg < -50) or         (chg6 is not None and chg6 < -25)
    price_down = chg is not None and chg < 0

    # --- ordered rules (most specific first) --------------------------------
    # 5. Distribution-Late / Markdown
    if (price_down_big or (price_down and np_now < -10)) and             np_now < 0 and cv < 30:
        r_bits = []
        if chg is not None:
            r_bits.append(f"price {chg:+.0f}% 24h")
        if chg6 is not None:
            r_bits.append(f"6h {chg6:+.0f}%")
        r_bits.append(f"net pure {np_now:+.0f} SOL (sellers one-way)")
        r_bits.append(f"conviction {cv:.0f}%")
        return {"phase": "Markdown", "confidence": confidence,
                "reason": ", ".join(r_bits) + " — distribution done, supply overhang"}
    # 4. Distribution-Early
    if (chg is None or chg > -20) and (cv_falling or np_flipped_neg) and             (np_now < 0 or (cv_prev is not None and cv < cv_prev - 5)):
        r_bits = []
        if chg is not None:
            r_bits.append(f"price still holding ({chg:+.0f}% 24h)")
        if chg6 is not None:
            r_bits.append(f"6h {chg6:+.0f}%")
        if cv_falling:
            r_bits.append(f"conviction dropping {cv_prev:.0f}→{cv:.0f}%")
        if np_flipped_neg:
            r_bits.append("net pure flipped negative")
        return {"phase": "Distribution-Early", "confidence": confidence,
                "reason": ", ".join(r_bits) or "early distribution signs"}
    # 3. Markup
    if price_up_big and np_now >= -5:
        r_bits = []
        if chg is not None:
            r_bits.append(f"price {chg:+.0f}% 24h")
        if chg6 is not None:
            r_bits.append(f"6h {chg6:+.0f}%")
        r_bits.append(f"net pure {np_now:+.0f} SOL")
        return {"phase": "Markup", "confidence": confidence,
                "reason": ", ".join(r_bits) + " — trend leg in progress"
                          f"{', volume rising' if vol_rising else ''}"}
    # 2. Accumulation-Late
    if cv >= 50 and (cv_rising or (cv_prev is not None and
                                   abs(cv - cv_prev) <= 5)) and             np_now > 0 and (chg is None or price_flat or price_up_small):
        return {"phase": "Accumulation-Late", "confidence": confidence,
                "reason": f"conviction {cv:.0f}% (high & holding), net pure "
                          f"{np_now:+.0f} SOL, price quiet — mature "
                          f"accumulation"}
    # 1. Accumulation-Early
    if cv_rising and np_now > 0 and             (chg is None or price_flat or price_down) and cv < 50:
        return {"phase": "Accumulation-Early", "confidence": confidence,
                "reason": f"conviction climbing {cv_prev:.0f}→{cv:.0f}% "
                          f"from a low base, net pure {np_now:+.0f} SOL"
                          f"{', volume picking up' if vol_rising else ''}"}
    # 6. fallback
    bits = [f"conviction {cv:.0f}%"]
    if cv_prev is not None:
        bits.append(f"prev {cv_prev:.0f}%")
    bits.append(f"net pure {np_now:+.0f}")
    if chg is not None:
        bits.append(f"price {chg:+.0f}%/24h")
    if chg6 is not None:
        bits.append(f"6h {chg6:+.0f}%")
    return {"phase": "Neutral/Choppy", "confidence": confidence,
            "reason": "mixed signals: " + ", ".join(bits)}


PHASE_COLORS = {
    "Accumulation-Early": "#38bdf8",   # blue
    "Accumulation-Late": "#2563eb",    # deeper blue
    "Markup": "#22c55e",               # green
    "Distribution-Early": "#fb923c",   # orange
    "Markdown": "#ef4444",             # red
    "Neutral/Choppy": "#64748b",       # grey
}


# ---------------------------------------------------------------------------
# Divergence detection (pivot-based, non-repainting)
# ---------------------------------------------------------------------------
def find_pivots(vals, left=2, right=2):
    """Indices of local highs/lows confirmed by `left`/`right` neighbours."""
    highs, lows = [], []
    for i in range(left, len(vals) - right):
        win_l = vals[i - left:i]
        win_r = vals[i + 1:i + 1 + right]
        if vals[i] > max(win_l) and vals[i] >= max(win_r):
            highs.append(i)
        if vals[i] < min(win_l) and vals[i] <= min(win_r):
            lows.append(i)
    return highs, lows


def detect_divergence(price, cvd, left=2, right=2):
    """Compare the two most recent confirmed pivots of price vs CVD.
    Returns list of dicts {type, kind, i1, i2, detail}."""
    out = []
    if len(price) < left + right + 3:
        return out
    ph, pl = find_pivots(price, left, right)
    # bearish regular: price HH, cvd LH
    if len(ph) >= 2:
        a, b = ph[-2], ph[-1]
        if price[b] > price[a] and cvd[b] < cvd[a]:
            out.append({"type": "bearish", "kind": "regular", "i1": a, "i2": b,
                        "detail": "price higher-high but CVD lower-high — "
                                  "buys are NOT confirming the pump"})
        elif price[b] < price[a] and cvd[b] > cvd[a]:
            out.append({"type": "bearish", "kind": "hidden", "i1": a, "i2": b,
                        "detail": "price lower-high but CVD higher-high — "
                                  "heavy buying absorbed without new highs "
                                  "(seller in control)"})
    # bullish regular: price LL, cvd HL
    if len(pl) >= 2:
        a, b = pl[-2], pl[-1]
        if price[b] < price[a] and cvd[b] > cvd[a]:
            out.append({"type": "bullish", "kind": "regular", "i1": a, "i2": b,
                        "detail": "price lower-low but CVD higher-low — "
                                  "selling is drying up / being absorbed "
                                  "(accumulation)"})
        elif price[b] > price[a] and cvd[b] < cvd[a]:
            out.append({"type": "bullish", "kind": "hidden", "i1": a, "i2": b,
                        "detail": "price higher-low but CVD lower-low — "
                                  "dip was sold hard yet price held "
                                  "(strong bid underneath)"})
    return out


def get_h4_series(ca: str, hours_span=None):
    """Resample the hourly buckets into H4: returns (ts_list, cvd, whale_cvd,
    retail_cvd, buy_vol, sell_vol) aligned oldest->newest."""
    state = load_cvd()
    entry = state.get(ca)
    if not entry or not entry.get("buckets"):
        return None
    buckets = {int(k): v for k, v in entry["buckets"].items()}
    tmin, tmax = min(buckets), max(buckets)
    if hours_span:
        tmin = max(tmin, tmax - hours_span * 3600)
    h4 = {}
    for ts, c in buckets.items():
        if ts < tmin:
            continue
        b4 = ts // 14400 * 14400
        agg = h4.setdefault(b4, {"bs": 0.0, "ss": 0.0, "wbs": 0.0,
                                 "wss": 0.0, "nb": 0, "ns": 0})
        for k in agg:
            agg[k] += c.get(k, 0)
    ts_sorted = sorted(h4)
    cvd, wcvd, rcvd, bv, sv = [], [], [], [], []
    c = w = rr = 0.0
    for t in ts_sorted:
        a = h4[t]
        c += a["bs"] - a["ss"]
        w += a["wbs"] - a["wss"]
        rr += (a["bs"] - a["wbs"]) - (a["ss"] - a["wss"])
        cvd.append(c)
        wcvd.append(w)
        rcvd.append(rr)
        bv.append(a["bs"])
        sv.append(a["ss"])
    return {"ts": ts_sorted, "cvd": cvd, "whale": wcvd, "retail": rcvd,
            "buy": bv, "sell": sv, "updated": entry.get("updated"),
            "gap": entry.get("gap", False)}


def get_series(ca: str, bucket_hours: int = 1, hours_span: int = None):
    """Resample hourly buckets into N-hour candles. Returns dict with ts,
    cvd, whale, retail, buy, sell lists (oldest->newest) or None."""
    state = load_cvd()
    entry = state.get(ca)
    if not entry or not entry.get("buckets"):
        return None
    buckets = {int(k): v for k, v in entry["buckets"].items()}
    tmax = max(buckets)
    tmin = min(buckets)
    if hours_span:
        tmin = max(tmin, tmax - hours_span * 3600)
    step = bucket_hours * 3600
    agg = {}
    for ts, c in buckets.items():
        if ts < tmin:
            continue
        b = ts // step * step
        a = agg.setdefault(b, {"bs": 0.0, "ss": 0.0, "wbs": 0.0,
                               "wss": 0.0, "nb": 0, "ns": 0})
        for k in a:
            a[k] += c.get(k, 0)
    ts_sorted = sorted(agg)
    cvd, wcvd, rcvd, bv, sv = [], [], [], [], []
    c = w = rr = 0.0
    for t in ts_sorted:
        a = agg[t]
        c += a["bs"] - a["ss"]
        w += a["wbs"] - a["wss"]
        rr += (a["bs"] - a["wbs"]) - (a["ss"] - a["wss"])
        cvd.append(c)
        wcvd.append(w)
        rcvd.append(rr)
        bv.append(a["bs"])
        sv.append(a["ss"])
    return {"ts": ts_sorted, "cvd": cvd, "whale": wcvd, "retail": rcvd,
            "buy": bv, "sell": sv, "updated": entry.get("updated"),
            "gap": entry.get("gap", False)}


def fetch_price_series(pool: str, bucket_hours: int = 1, limit: int = 100):
    """GeckoTerminal candles -> {bucket_ts: close}."""
    res, aggr = ("hour", bucket_hours) if bucket_hours in (1, 4, 12) else \
        ("hour", 1)
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pool}/ohlcv/{res}", params={"aggregate": aggr, "limit": limit},
            headers={"accept": "application/json"}, timeout=20)
        lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list") or []
    except Exception:
        return {}
    return {int(x[0]): float(x[4]) for x in reversed(lst)}


def fetch_h4_price(pool: str, limit=42):
    """GeckoTerminal 4h candles -> {ts: close} oldest->newest."""
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pool}/ohlcv/hour", params={"aggregate": 4, "limit": limit},
            headers={"accept": "application/json"}, timeout=20)
        lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list") or []
    except Exception:
        return {}
    return {int(x[0]): float(x[4]) for x in reversed(lst)}


# ---------------------------------------------------------------------------
# OHLC candles + flow attribution for the Breakout Guard
# ---------------------------------------------------------------------------
def fetch_candles(pool: str, *, timeframe: str = "hour", aggregate: int = 4,
                  limit: int = 100, timeout: int = 20):
    """GeckoTerminal OHLCV -> list of candle dicts, oldest -> newest.

    Each candle: ``{ts, o, h, l, c, v}`` with ``ts`` the candle's OPEN time
    (unix seconds), which is how GeckoTerminal labels them.

    ``timeframe`` is ``day`` / ``hour`` / ``minute``; ``aggregate`` multiplies
    it (``hour`` + 4 = H4). Returns [] on any failure — every caller must
    treat an empty list as "no data, do nothing".
    """
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pool}/ohlcv/{timeframe}",
            params={"aggregate": aggregate, "limit": limit},
            headers={"accept": "application/json"}, timeout=timeout)
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


def swaps_between(ca: str, t0: float, t1: float):
    """Raw swaps from the store with ``t0 <= ts < t1`` (oldest first)."""
    state = load_cvd()
    entry = state.get(ca)
    if not entry or not entry.get("swaps"):
        return []
    out = [tuple(s) for s in entry["swaps"]
           if t0 <= (s[2] or 0) < t1]
    out.sort(key=lambda s: s[2])
    return out


def filter_swaps_by_time(swaps, start_ts: int, end_ts: int) -> list:
    """Pure filter: return swaps where ``start_ts <= ts <= end_ts``.

    ``swaps`` is an iterable of ``(side, sol, ts, wallet)`` tuples (the
    standard CVD format).  Returns a new list, sorted by *ts* ascending.
    Useful for focus-range analysis after a broader fetch.
    """
    out = [s for s in swaps if start_ts <= (s[2] or 0) <= end_ts]
    out.sort(key=lambda s: s[2])
    return out


def summarize_swap_range(swaps, *, whale_min_sol=WHALE_SOL) -> dict:
    """Comprehensive summary of a swap list.

    Returns a dict with aggregate volume, wallet counts, conviction
    split, top actors, and dominance — everything the focus-range panel
    needs in a single call.

    Keys: ``swaps``, ``buy_sol``, ``sell_sol``, ``net_sol``, ``buyers``,
    ``sellers``, ``wallets``, ``whale_buy``, ``whale_sell``, ``whale_net``,
    ``retail_net``, ``profiles``, ``conviction``, ``top_buyers``,
    ``top_sellers``, ``top_net_wallets``, ``dominance_pct``.
    """
    if not swaps:
        return {
            "swaps": 0, "buy_sol": 0.0, "sell_sol": 0.0, "net_sol": 0.0,
            "buyers": 0, "sellers": 0, "wallets": 0,
            "whale_buy": 0.0, "whale_sell": 0.0, "whale_net": 0.0,
            "retail_net": 0.0, "profiles": {}, "conviction": {},
            "top_buyers": [], "top_sellers": [], "top_net_wallets": [],
            "dominance_pct": 0.0,
        }

    buy_vol = sell_vol = 0.0
    whale_buy = whale_sell = 0.0
    buyer_wallets, seller_wallets = set(), set()
    all_wallets = set()
    wallet_buy = {}
    wallet_sell = {}

    for side, sol, ts, wallet in swaps:
        sol = float(sol or 0)
        if wallet:
            all_wallets.add(wallet)
        if side == "buy":
            buy_vol += sol
            if wallet:
                buyer_wallets.add(wallet)
                wallet_buy[wallet] = wallet_buy.get(wallet, 0.0) + sol
            if sol >= whale_min_sol:
                whale_buy += sol
        else:
            sell_vol += sol
            if wallet:
                seller_wallets.add(wallet)
                wallet_sell[wallet] = wallet_sell.get(wallet, 0.0) + sol
            if sol >= whale_min_sol:
                whale_sell += sol

    profiles = wallet_profiles(swaps)
    conv = conviction_split(profiles, whale_min_sol=whale_min_sol)

    # top buyers by SOL volume
    top_buyers = sorted(
        [(w, wallet_buy.get(w, 0.0)) for w in buyer_wallets],
        key=lambda x: -x[1])[:10]
    # top sellers by SOL volume
    top_sellers = sorted(
        [(w, wallet_sell.get(w, 0.0)) for w in seller_wallets],
        key=lambda x: -x[1])[:10]
    # top net wallets (buy - sell)
    wallet_net = {}
    for w in all_wallets:
        wallet_net[w] = wallet_buy.get(w, 0.0) - wallet_sell.get(w, 0.0)
    top_net_wallets = sorted(wallet_net.items(), key=lambda x: -abs(x[1]))[:10]

    # dominance: largest single-wallet share of total volume
    total_vol = buy_vol + sell_vol
    max_single = max(
        [wallet_buy.get(w, 0) + wallet_sell.get(w, 0)
         for w in all_wallets] or [0])
    dominance_pct = (max_single / total_vol * 100) if total_vol > 0 else 0.0

    return {
        "swaps": len(swaps),
        "buy_sol": buy_vol,
        "sell_sol": sell_vol,
        "net_sol": buy_vol - sell_vol,
        "buyers": len(buyer_wallets),
        "sellers": len(seller_wallets),
        "wallets": len(all_wallets),
        "whale_buy": whale_buy,
        "whale_sell": whale_sell,
        "whale_net": whale_buy - whale_sell,
        "retail_net": (buy_vol - whale_buy) - (sell_vol - whale_sell),
        "profiles": profiles,
        "conviction": conv,
        "top_buyers": top_buyers,
        "top_sellers": top_sellers,
        "top_net_wallets": top_net_wallets,
        "dominance_pct": dominance_pct,
    }


def flow_report(swaps) -> dict:
    """Who was actually behind these swaps?

    Splits the window's flow into whale (>= :data:`WHALE_SOL`) vs retail,
    counts distinct wallets on each side, folds in the pure-accumulator /
    pure-distributor profiling, and names the dominant actor. This is what
    turns "price broke the level" into "whales sold into retail buying".
    """
    empty = {"n": 0, "buy_vol": 0.0, "sell_vol": 0.0, "net": 0.0,
             "whale_buy": 0.0, "whale_sell": 0.0, "whale_net": 0.0,
             "retail_buy": 0.0, "retail_sell": 0.0, "retail_net": 0.0,
             "n_whale_buyers": 0, "n_whale_sellers": 0,
             "n_retail_buyers": 0, "n_retail_sellers": 0,
             "biggest_buy": 0.0, "biggest_sell": 0.0,
             "pure_buy": 0.0, "pure_sell": 0.0, "net_pure": 0.0,
             "actor": "no data", "actor_side": "none"}
    if not swaps:
        return empty

    r = dict(empty)
    r["n"] = len(swaps)
    wb, ws, rb, rs = set(), set(), set(), set()
    for side, sol, _ts, w in swaps:
        sol = float(sol or 0)
        whale = sol >= WHALE_SOL
        if side == "buy":
            r["buy_vol"] += sol
            r["biggest_buy"] = max(r["biggest_buy"], sol)
            if whale:
                r["whale_buy"] += sol
                wb.add(w)
            else:
                r["retail_buy"] += sol
                rb.add(w)
        else:
            r["sell_vol"] += sol
            r["biggest_sell"] = max(r["biggest_sell"], sol)
            if whale:
                r["whale_sell"] += sol
                ws.add(w)
            else:
                r["retail_sell"] += sol
                rs.add(w)

    r["net"] = r["buy_vol"] - r["sell_vol"]
    r["whale_net"] = r["whale_buy"] - r["whale_sell"]
    r["retail_net"] = r["retail_buy"] - r["retail_sell"]
    r["n_whale_buyers"] = len(wb)
    r["n_whale_sellers"] = len(ws)
    r["n_retail_buyers"] = len(rb)
    r["n_retail_sellers"] = len(rs)

    prof = wallet_profiles(swaps)
    conv = conviction_split(prof, whale_min_sol=WHALE_SOL)
    r["pure_buy"] = conv["pure_buy"]
    r["pure_sell"] = conv["pure_sell"]
    r["net_pure"] = conv["pure_buy"] - conv["pure_sell"]

    # Who dominated? Compare the four flows by absolute size.
    flows = [("whale buying", r["whale_buy"], "buy"),
             ("whale selling", r["whale_sell"], "sell"),
             ("retail buying", r["retail_buy"], "buy"),
             ("retail selling", r["retail_sell"], "sell")]
    label, size, side = max(flows, key=lambda f: f[1])
    total = r["buy_vol"] + r["sell_vol"]
    if total <= 0 or size <= 0:
        r["actor"], r["actor_side"] = "no meaningful flow", "none"
    else:
        r["actor"] = f"{label} ({size / total * 100:.0f}% of window volume)"
        r["actor_side"] = side
    return r


def describe_flow(f: dict) -> str:
    """Plain-language read of :func:`flow_report`, for the alert body."""
    if not f or not f.get("n"):
        return ("\u26a0\ufe0f no on-chain swaps stored for this candle "
                "\u2014 flow unknown (cron may have missed the window)")
    bits = [
        f"\U0001F40B whales: <b>{f['whale_net']:+.1f}</b> SOL "
        f"(+{f['whale_buy']:.1f} / -{f['whale_sell']:.1f}) \u00b7 "
        f"{f['n_whale_buyers']} buyer / {f['n_whale_sellers']} seller",
        f"\U0001F41F retail: <b>{f['retail_net']:+.1f}</b> SOL "
        f"(+{f['retail_buy']:.1f} / -{f['retail_sell']:.1f}) \u00b7 "
        f"{f['n_retail_buyers']} buyer / {f['n_retail_sellers']} seller",
        f"\U0001F48E pure: +{f['pure_buy']:.1f} / -{f['pure_sell']:.1f} "
        f"(net {f['net_pure']:+.1f}) \u00b7 {f['n']} swaps",
        f"\U0001F3AD dominant: <b>{f['actor']}</b>",
    ]
    return "\n".join(bits)


def flow_warning(f: dict, direction: str = "up") -> str:
    """The 'so what do I do' line — the whole point of the flow block.

    *direction* is the direction of the price event (``up`` for a
    breakout/reclaim, ``down`` for a breakdown), because the same flow
    means opposite things depending on which way price moved.
    """
    if not f or not f.get("n"):
        return ("\u2753 no flow data \u2014 treat this level event as "
                "unconfirmed.")
    wn, rn = f["whale_net"], f["retail_net"]
    if direction == "up":
        if wn > 0 and rn < 0:
            return ("\u2705 whales BOUGHT this move while retail sold "
                    "\u2014 strongest confirmation.")
        if wn < 0 and rn > 0:
            return ("\U0001F6A8 CAREFUL: whales SOLD into retail buying "
                    "\u2014 classic distribution into strength.")
        if wn > 0 and rn > 0:
            return ("\u26a0\ufe0f everyone bought \u2014 real demand but "
                    "crowded; watch for a fast fade.")
        return ("\u26a0\ufe0f both sides net sellers \u2014 the move is not "
                "backed by buying, likely thin-liquidity drift.")
    if wn < 0 and rn > 0:
        return ("\U0001F6A8 CAREFUL: whales DUMPED and retail absorbed it "
                "\u2014 retail is holding the bag.")
    if wn > 0 and rn < 0:
        return ("\U0001F440 whales BOUGHT the breakdown while retail "
                "panic-sold \u2014 possible shakeout, watch for a reclaim.")
    if wn < 0 and rn < 0:
        return ("\U0001F6A8 broad selling from both whales and retail "
                "\u2014 no bid underneath.")
    return ("\u26a0\ufe0f whales quiet, retail drove it \u2014 low-conviction "
            "move, needs confirmation.")


def daily_levels(pool: str, *, limit: int = 60, left: int = 2, right: int = 2,
                 merge_pct: float = 0.015, max_levels: int = 6):
    """Support/resistance from DAILY candles (pivot highs/lows).

    Daily pivots are far fewer and far more meaningful than the H1 pivots
    this used to run on: a level that held for a day is a level other
    traders can see too.

    ``right`` bars must exist AFTER a pivot for it to be confirmed, so the
    still-forming session can never invent a level. Returns
    ``{"highs": [...], "lows": [...], "price": float, "candles": n}`` with
    highs sorted ascending (nearest resistance first) and lows descending
    (nearest support first), or None when there is not enough history.
    """
    candles = fetch_candles(pool, timeframe="day", aggregate=1, limit=limit)
    if len(candles) < left + right + 3:
        return None
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    price = candles[-1]["c"]

    piv_h, piv_l = [], []
    for i in range(left, len(candles) - right):
        seg_h = highs[i - left:i + right + 1]
        seg_l = lows[i - left:i + right + 1]
        if highs[i] == max(seg_h):
            piv_h.append(highs[i])
        if lows[i] == min(seg_l):
            piv_l.append(lows[i])

    def merge(vals, prefer_recent=True):
        """Collapse levels within merge_pct of each other."""
        out = []
        for v in (reversed(vals) if prefer_recent else vals):
            if v and not any(abs(v - o) / o < merge_pct for o in out if o):
                out.append(v)
        return out

    res = sorted(v for v in merge(piv_h) if v > price)[:max_levels]
    sup = sorted((v for v in merge(piv_l) if v < price),
                 reverse=True)[:max_levels]
    return {"highs": res, "lows": sup, "price": price,
            "candles": len(candles)}


# ---------------------------------------------------------------------------
# Short-term markup risk (48h window)
# ---------------------------------------------------------------------------
MARKUP_DANGER = 100.0   # +100% in 48h → red banner
MARKUP_WARN = 50.0      # +50%  in 48h → orange warning


def markup_from_candles(candles, price_now=None):
    """Measure current markup from the first candle's close in the window.

    This covers the last 24-48h (depending on what the caller fetched).
    The base is the closing price of the first candle, NOT the lowest low,
    so a token that launched cheap 30 days ago won't falsely trigger as
    ``+1500%`` — only the move within the window matters.

    ``candles`` uses the same ``{o, h, l, c}`` shape as
    :func:`fetch_candles`. At least three valid candles are required. When
    ``price_now`` is omitted, the newest candle close is used. The historical
    peak includes ``price_now`` so a fresh high cannot produce a positive
    ``off_peak_pct``.
    """
    valid = []
    for candle in (candles or []):
        try:
            low = float(candle["l"])
            high = float(candle["h"])
            close = float(candle["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if (math.isfinite(low) and math.isfinite(high) and
                math.isfinite(close) and low > 0 and high > 0 and close > 0):
            valid.append((low, high, close))
    if len(valid) < 3:
        return None

    try:
        price = valid[-1][2] if price_now is None else float(price_now)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None

    # Use the first candle's close as the base — measures move within window
    base = valid[0][2]
    peak = max(max(candle[1] for candle in valid), price)
    markup_pct = (price / base - 1.0) * 100.0
    peak_markup_pct = (peak / base - 1.0) * 100.0
    off_peak_pct = (price / peak - 1.0) * 100.0
    if markup_pct >= MARKUP_DANGER:
        level = "danger"
    elif markup_pct >= MARKUP_WARN:
        level = "warn"
    else:
        level = "ok"
    return {"markup_pct": markup_pct,
            "peak_markup_pct": peak_markup_pct,
            "off_peak_pct": off_peak_pct,
            "past_peak": price < peak,
            "level": level}


def markup_label(markup) -> str:
    """Short UI label for a :func:`markup_from_candles` result (48h window)."""
    level = (markup or {}).get("level") if isinstance(markup, dict) else markup
    return {"danger": "🔴 MARKUP DANGER",
            "warn": "🟠 MARKUP WARNING",
            "ok": "🟢 MARKUP OK"}.get(level, "")


def markup_warning(markup) -> str:
    """Action-oriented warning for elevated short-term markup."""
    if not isinstance(markup, dict) or markup.get("level") == "ok":
        return ""
    try:
        current = float(markup["markup_pct"])
        off_peak = float(markup.get("off_peak_pct") or 0)
    except (KeyError, TypeError, ValueError):
        return ""
    peak_note = ""
    if markup.get("past_peak") and off_peak < 0:
        peak_note = f", kini {abs(off_peak):.0f}% di bawah puncak"
    if markup.get("level") == "danger":
        return (f"Harga sudah +{current:.0f}% dari low 24-48h{peak_note}. "
                "Risiko mengejar markup dan menjadi exit liquidity sangat "
                "tinggi; conviction datar bukan tanda aman.")
    return (f"Harga sudah +{current:.0f}% dari low 24-48h{peak_note}. "
            "Entry mulai jauh dari base; tunggu struktur dan flow baru.")


def analysis_windows(requested_hours) -> list:
    """Nested CVD windows that never exceed the fetched time range.

    The old page always appended a 48h row, even after fetching only 4-36h.
    That mislabeled the same short dataset as a 48h reading. Keep a minimum
    useful slice of four hours and cap every row at the selected window.
    """
    try:
        requested = int(float(requested_hours))
    except (TypeError, ValueError, OverflowError):
        return []
    if requested < 4:
        return []
    candidates = (max(4, requested // 4),
                  max(4, requested // 2), requested)
    return sorted({window for window in candidates
                   if 4 <= window <= requested})


# ---------------------------------------------------------------------------
# Flow quality / distribution / persistence / freshness checks.
# A "check" is a single named flag the UI can surface in plain language,
# e.g. "🩸 hard distribution" or "⏰ data stale (4.2h)". They are *advisory*
# — none of them block scoring, they only colour the panel.
# ---------------------------------------------------------------------------
FRESH_MAX_AGE_S = 150 * 60       # 2.5h — covers the hourly cron with margin
STALE_MAX_AGE_S = 12 * 3600      # 12h — up to 12 missed hourly runs is still "stale"
PERSISTENCE_MIN_RUN = 3         # 3 consecutive cron points all the same way
PERSISTENCE_MIN_NET_SOL = 5.0   # each of those 3 points must move ≥5 SOL net
DISTRIBUTION_DROP_PCT = 30.0    # 30% drop of net_pure from peak = signal
QUALITY_MIN_SOL = 30.0          # window volume that earns a "real flow" tag
QUALITY_SWAP_BAND = (5, 50)     # swap count below this = dead window


def flow_freshness(ca: str) -> dict:
    """Is the conviction history still being updated?

    Returns ``{"ok": bool, "age_min": float, "level": str, "reason": str,
    "last_ts": int}``.

    The cron runs every 1h (GMGN), so a healthy point is always ≤1h old;
    the ``FRESH_MAX_AGE_S`` / ``STALE_MAX_AGE_S`` constants carve three
    bands:

    * **fresh** (<= ``FRESH_MAX_AGE_S``): ok=True, level="ok".
    * **stale** (≤``STALE_MAX_AGE_S``): ok=False, level="warn". The
      point is older than one full cron cycle but is still useful —
      at most a few missed runs.
    * **very stale** (>``STALE_MAX_AGE_S``): ok=False, level="danger".
      6+ missed runs; the UI should refuse to surface the conviction
      and offer a manual refresh.
    """
    pts = (load_conviction() or {}).get(ca) or []
    if not pts:
        return {"ok": False, "age_min": float("inf"), "level": "danger",
                "reason": "never seen — cron has not run for this CA yet",
                "last_ts": 0}
    last_ts = int(pts[-1].get("ts") or 0)
    if last_ts <= 0:
        return {"ok": False, "age_min": float("inf"), "level": "danger",
                "reason": "no timestamp on last point", "last_ts": 0}
    age = max(0.0, time.time() - last_ts)
    age_min = age / 60.0
    age_h = age / 3600.0
    if age <= FRESH_MAX_AGE_S:
        level = "ok"
        msg = f"fresh ({age_min:.0f} min ago)"
    elif age <= STALE_MAX_AGE_S:
        level = "warn"
        runs_behind = int(round(age_h))
        run_word = "run" if runs_behind == 1 else "runs"
        msg = (f"stale ({age_h:.1f}h ago — cron is "
               f"{runs_behind} {run_word} behind)")
    else:
        level = "danger"
        msg = (f"very stale ({age_h:.1f}h ago — do not trust the read, "
               f"hit 🔄 Force refresh to backfill)")
    return {"ok": level == "ok",
            "age_min": age_min, "level": level, "reason": msg,
            "last_ts": last_ts}


def flow_persistence(ca: str, *, last_n: int = 3) -> dict:
    """Are the last *last_n* points all pushing the same direction?

    A genuine accumulation rarely appears in a single 6h window — it shows
    up as several cron points in a row, each adding ≥
    :data:`PERSISTENCE_MIN_NET_SOL` SOL to ``net_pure``. Distribution
    persistence is the mirror image.

    Returns ``{"direction": "accum"|"dist"|"choppy",
                "runs": int, "delta": float, "ok": bool, "reason": str}``.
    *ok* is True only when the run length meets both the *count* and the
    *size* thresholds; the UI uses it to colour the persistence badge.
    """
    pts = (load_conviction() or {}).get(ca) or []
    if len(pts) < 2:
        return {"direction": "choppy", "runs": 0, "delta": 0.0,
                "ok": False, "reason": "not enough points yet"}
    window = pts[-last_n:]
    nets = [float(p.get("net_pure") or 0) for p in window]
    # A point with net_pure == 0 is noise (no flow at all) and never
    # contributes to a run. A point that flips sign (positive→negative or
    # vice-versa) breaks the run.
    signs = [(1 if n > 0 else (-1 if n < 0 else 0)) for n in nets]
    direction = ("accum" if signs[-1] > 0 else
                 "dist" if signs[-1] < 0 else "choppy")
    if direction == "choppy":
        return {"direction": "choppy", "runs": 0,
                "delta": float(nets[-1]), "ok": False,
                "reason": "last 3 windows mixed — no clear direction"}
    target = 1 if direction == "accum" else -1
    # Count consecutive trailing points matching the current direction.
    # Example [8, 10, 12] (all +) → runs = 3; [8, -10, 12] (last 1 +) → 1.
    runs = 0
    for s in reversed(signs):
        if s == target:
            runs += 1
        else:
            break
    if runs < PERSISTENCE_MIN_RUN:
        return {"direction": direction, "runs": runs,
                "delta": float(nets[-1]), "ok": False,
                "reason": (f"only {runs} consecutive "
                           f"{'buy' if direction == 'accum' else 'sell'} "
                           "window(s) — need 3 for persistence")}
    # All-N in the trailing run AND each ≥ min size = persistent run.
    if all(abs(n) >= PERSISTENCE_MIN_NET_SOL for n in nets[-runs:]):
        return {"direction": direction, "runs": runs,
                "delta": float(nets[-1]), "ok": True,
                "reason": (f"{runs} consecutive "
                           f"{'accumulation' if direction == 'accum' else 'distribution'} "
                           f"windows ≥{PERSISTENCE_MIN_NET_SOL:g} SOL — "
                           "this is a sustained run, not a single spike")}
    return {"direction": direction, "runs": runs,
            "delta": float(nets[-1]), "ok": False,
            "reason": (f"direction is consistent but each move is small "
                       f"(<{PERSISTENCE_MIN_NET_SOL:g} SOL) — could be noise")}


def flow_distribution(ca: str) -> dict:
    """Is the current read a distribution event?

    A distribution event needs both:
      * ``net_pure`` is now *materially* below its 24h peak, AND
      * at least one of: conviction also dropped, OR whale-side flipped
        negative while retail is still positive (classic dump into strength).

    Returns ``{"ok": bool, "drop_pct": float, "level": "ok"|"warn"|"danger",
                "reason": str}``. ``ok=False`` means a distribution event
    is currently being flagged. ``level`` follows the same warn/danger
    scale the markup warnings use, so the UI can colour consistently.
    """
    pts = (load_conviction() or {}).get(ca) or []
    if len(pts) < 4:
        return {"ok": False, "drop_pct": 0.0, "level": "ok",
                "reason": "not enough history (need ≥4 points)"}
    np_now = float(pts[-1].get("net_pure") or 0)
    # use the last 4 points (≈24h on a 6h cron) as the comparison window
    recent = [float(p.get("net_pure") or 0) for p in pts[-4:]]
    peak = max(recent)
    if peak <= 0:
        # never had net positive flow → not a distribution, just no inflow
        return {"ok": False, "drop_pct": 0.0, "level": "ok",
                "reason": "no net-buy peak in the last 24h — no "
                          "distribution to flag"}
    drop_pct = (peak - np_now) / peak * 100
    cv_now = float(pts[-1].get("conviction") or 0)
    cv_peak = max(float(p.get("conviction") or 0) for p in pts[-4:])
    cv_drop = (cv_peak - cv_now) / cv_peak * 100 if cv_peak else 0
    if drop_pct < DISTRIBUTION_DROP_PCT:
        return {"ok": False, "drop_pct": round(drop_pct, 1), "level": "ok",
                "reason": (f"net_pure only {drop_pct:.0f}% below 24h peak "
                           "— still well within normal volatility")}
    if drop_pct >= 60 and cv_drop >= 30:
        level = "danger"
        reason = (f"net_pure crashed {drop_pct:.0f}% from peak AND "
                  f"conviction fell {cv_drop:.0f}% — classic late-stage "
                  "distribution / supply overhang")
    elif drop_pct >= DISTRIBUTION_DROP_PCT:
        level = "warn"
        reason = (f"net_pure {drop_pct:.0f}% below 24h peak — early "
                  "distribution, watch for conviction to follow")
    else:
        level = "ok"
        reason = ""
    return {"ok": drop_pct >= DISTRIBUTION_DROP_PCT,
            "drop_pct": round(drop_pct, 1), "level": level,
            "reason": reason}


def flow_quality(ca: str) -> dict:
    """Coarse 'is this window worth reading' flag.

    Combines three things:
      * enough swap activity (``vol`` above :data:`QUALITY_MIN_SOL`),
      * swap count inside :data:`QUALITY_SWAP_BAND` (very low = dead
        token, very high = a single wash-trade event can look like
        a real move),
      * not all the volume is the same wallet (basic concentration).

    Returns ``{"ok": bool, "level": "ok"|"warn"|"danger", "reason": str,
                "vol": float, "n_swaps": int, "n_wallets": int}``.
    """
    pts = (load_conviction() or {}).get(ca) or []
    if not pts:
        return {"ok": False, "level": "ok", "reason": "no conviction yet",
                "vol": 0.0, "n_swaps": 0, "n_wallets": 0}
    last = pts[-1]
    vol = float(last.get("vol") or 0)
    n_swaps = int(last.get("swaps") or 0)
    # Count distinct wallets in the SAME window the conviction point covers
    # (the 6h ending at the point's own timestamp) — NOT "last 6h from now".
    # When the cron is lagging (stale point), "from now" would look at a
    # window that has no data yet and wrongly report 0 wallets, falsely
    # flagging a fresh/legit multi-wallet window as "one or two wallets
    # dominate".
    last_ts = int(last.get("ts") or 0)
    try:
        if last_ts:
            swaps = swaps_between(ca, last_ts - 6 * 3600, last_ts)
        else:
            swaps = get_recent_swaps(ca, 6)
    except Exception:
        swaps = []
    n_wallets = len({s[3] for s in swaps if s and s[3]})
    if vol < QUALITY_MIN_SOL:
        return {"ok": False, "level": "warn",
                "reason": (f"only {vol:.1f} SOL in 6h (below "
                           f"{QUALITY_MIN_SOL:g}) — too quiet to read "
                           "conviction meaningfully"),
                "vol": vol, "n_swaps": n_swaps, "n_wallets": n_wallets}
    lo, hi = QUALITY_SWAP_BAND
    if n_swaps and n_swaps < lo:
        return {"ok": False, "level": "warn",
                "reason": (f"only {n_swaps} swaps in 6h — window too thin "
                           "to draw a conclusion"),
                "vol": vol, "n_swaps": n_swaps, "n_wallets": n_wallets}
    if n_swaps and n_swaps > hi and n_wallets <= max(2, n_swaps // 20):
        return {"ok": False, "level": "warn",
                "reason": (f"{n_swaps} swaps but only {n_wallets} wallets "
                           "— one or two wallets dominate, treat the read "
                           "with caution"),
                "vol": vol, "n_swaps": n_swaps, "n_wallets": n_wallets}
    return {"ok": True, "level": "ok",
            "reason": (f"{vol:.0f} SOL · {n_swaps} swaps · "
                       f"{n_wallets} wallets — real flow"),
            "vol": vol, "n_swaps": n_swaps, "n_wallets": n_wallets}


def flow_check_panel(ca: str) -> dict:
    """Run every check at once and return a single dict the UI can iterate.

    Each entry has ``ok``, ``level`` ("ok"|"warn"|"danger") and a short
    ``reason`` string. The panel is the source of truth for the "CVD
    safety diagnostics" the LP Radar card surfaces.
    """
    return {
        "freshness": flow_freshness(ca),
        "persistence": flow_persistence(ca),
        "distribution": flow_distribution(ca),
        "quality": flow_quality(ca),
    }


# ---------------------------------------------------------------------------
# Holder delta — TRUE holdings change per tier (whale/dolphin/minnow)
# ---------------------------------------------------------------------------
# Unlike the swap-flow proxy (`flow_report`, which sees buys-sells in the
# window), this module compares the holder list at TWO points in time
# (T0 = baseline snapshot, T1 = now). A whale who bought 50 SOL and
# sold 30 SOL between T0 and T1 shows up as **net +20 SOL** here, not
# 50+30 of churn. That makes it the right signal for the LP Radar card
# "is the smart money accumulating or exiting" question.
#
# Trade-off: needs a snapshot store. The 4h cron (scripts/update_cvd.py)
# also commits a holder list per CA per snapshot to holder_snapshots.json,
# so the UI can look back up to the snapshot retention window (~30 days).
# ---------------------------------------------------------------------------
HOLDER_SNAPSHOT_PATH = os.path.join(BASE_DIR, "holder_snapshots.json")
# Per-tier % of holder COUNT (not supply). top 1% by holdings = whale,
# next 4% = dolphin, rest = minnow. This stays meaningful as the
# holder set grows: a 100-holder token still has ~1 whale, and a
# 10,000-holder token still has ~100 whales. Same shape, no re-tuning.
WHALE_PCT = 0.01
DOLPHIN_PCT = 0.05
# A wallet is counted as "exited" when its holdings drop to ≤ this
# fraction of its baseline (i.e. it sold ≥ 90% of what it held at T0).
EXIT_DROP_PCT = 0.90
# How many days of snapshots to keep. After that the file gets too
# large; 30 days covers any realistic LP watch window.
SNAPSHOT_KEEP_DAYS = 30
# Default per-tier |delta| threshold (SOL) before the UI surfaces a
# "whale moved" line. Owners tune in config.json. These constants are
# the in-code fallback when no config entry is present.
WHALE_DELTA_MIN_SOL = 1.0
DOLPHIN_DELTA_MIN_SOL = 2.0
# When a fresh snapshot is committed, skip if the previous one is
# younger than this many seconds. The 1h cron fires every hour, so
# 6h gives it plenty of slack for retries / slow networks.
SNAPSHOT_MIN_GAP_S = 6 * 3600


def load_holder_snapshots() -> dict:
    """{ca: {ts_iso: {"ts": int, "holders": [{"owner", "ui_amount"}]}}}.

    Git-merge tolerant (uses ``_load_json_tolerant``). Returns ``{}`` if
    the file is missing or malformed — every caller must treat empty as
    "no baseline yet" and surface a clear message, not crash.
    """
    return _load_json_tolerant(HOLDER_SNAPSHOT_PATH) or {}


def _save_holder_snapshots(state: dict) -> None:
    """Write the snapshot store back. Always atomic-ish: dump then
    rename via temp, so a crashed write doesn't leave a half-file."""
    import tempfile as _tf
    tmp = HOLDER_SNAPSHOT_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, separators=(",", ":"))
        os.replace(tmp, HOLDER_SNAPSHOT_PATH)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def classify_holders(holders, *, n_total: int = None) -> dict:
    """Tag every wallet as ``whale`` / ``dolphin`` / ``minnow`` based on
    its rank by holdings. The first ``WHALE_PCT`` of the sorted holders
    are whales, the next ``DOLPHIN_PCT - WHALE_PCT`` are dolphins, the
    rest are minnows. Returns ``{owner: tier}``.

    Tier thresholds are based on COUNT not supply, so they stay stable
    as the token grows: a 100-holder token still has 1 whale tier seat,
    a 10,000-holder token still has 100. What changes is the SOL held
    per tier (the analyzer reports both counts and totals).

    ``holders`` may be a list of ``[owner, raw_amount]`` pairs (as
    Helius returns) or a DataFrame with ``owner``/``ui_amount`` columns
    or a dict ``{owner: amount}`` — anything iterable of (owner, amount).
    """
    pairs = []
    for h in holders or []:
        try:
            if isinstance(h, (list, tuple)) and len(h) >= 2:
                owner, amt = h[0], h[1]
            elif isinstance(h, dict):
                owner = h.get("owner")
                amt = h.get("ui_amount") or h.get("raw_amount")
            else:
                continue
            if not owner or amt is None:
                continue
            pairs.append((str(owner), float(amt)))
        except Exception:
            continue
    if not pairs:
        return {}
    pairs.sort(key=lambda x: -x[1])
    n = n_total or len(pairs)
    whale_cut = max(1, int(round(n * WHALE_PCT)))
    dolphin_cut = max(whale_cut + 1, int(round(n * DOLPHIN_PCT)))
    tiers = {}
    for i, (owner, _) in enumerate(pairs):
        if i < whale_cut:
            tiers[owner] = "whale"
        elif i < dolphin_cut:
            tiers[owner] = "dolphin"
        else:
            tiers[owner] = "minnow"
    return tiers


def record_holder_snapshot(ca: str, holders, supply: float) -> dict | None:
    """Commit a fresh holder snapshot for ``ca`` to disk. Returns the
    new point dict, or ``None`` if the previous snapshot is too recent
    (i.e. the cron has already covered this window) or holders is empty.

    Each snapshot is keyed by ISO date + window index in the same day, so
    a 4h cron can safely commit 6 snapshots per day without overwriting.
    For dedup across CRON_RESTARTS the same-day bucket uses the same
    ts-bucket derived from ``int(time.time() // SNAPSHOT_MIN_GAP_S)``.
    """
    pairs = []
    for h in holders or []:
        try:
            if isinstance(h, (list, tuple)) and len(h) >= 2:
                owner, amt = h[0], float(h[1])
            elif isinstance(h, dict):
                owner = h.get("owner")
                amt = float(h.get("ui_amount") or h.get("raw_amount") or 0)
            else:
                continue
            if owner and amt > 0:
                pairs.append([str(owner), float(amt)])
        except Exception:
            continue
    if not pairs:
        return None
    # Sort largest first so the tier classifier doesn't have to
    pairs.sort(key=lambda x: -x[1])

    state = load_holder_snapshots()
    bucket = int(time.time() // SNAPSHOT_MIN_GAP_S)
    bucket_key = f"b{bucket}"
    prior = (state.get(ca) or {})
    # Skip if the most recent committed snapshot is in the same bucket
    # (cron retry, or two crons racing on the same window).
    if prior and bucket_key in prior:
        return None

    point = {
        "ts": int(time.time()),
        "supply": float(supply) if supply else 0.0,
        "holders": pairs,
    }
    prior[bucket_key] = point
    # Trim: keep only the last SNAPSHOT_KEEP_DAYS days (~30), but always
    # at least the most recent 4 snapshots so a fresh deploy has
    # something to work with.
    cutoff = time.time() - SNAPSHOT_KEEP_DAYS * 86400
    recent_first = {k: v for k, v in prior.items()
                    if v.get("ts", 0) >= cutoff}
    if len(recent_first) >= 4 or not prior:
        trimmed = recent_first
    else:
        # not enough recent — pad with the latest older ones (by ts),
        # keeping the original keys so the dedup check above still works
        # (we sort by ts desc and take the 4 freshest).
        ordered = sorted(prior.items(), key=lambda kv: kv[1].get("ts", 0),
                         reverse=True)[:4]
        trimmed = dict(ordered)
    state[ca] = trimmed
    try:
        _save_holder_snapshots(state)
    except Exception:
        return None
    return point


def _nearest_snapshot(state: dict, ca: str, ts_window_start: int):
    """Return the newest committed snapshot with ``ts <= ts_window_start``,
    or None if no baseline exists in that window.

    We pick the NEWEST snapshot OLDER than the window start so the
    baseline reflects holdings BEFORE the window, not a snapshot taken
    mid-window (which would understate the delta).
    """
    snaps = state.get(ca) or {}
    candidates = [s for s in snaps.values()
                  if s.get("ts", 0) <= ts_window_start]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.get("ts", 0))


def _classify_snapshot(holders):
    """Shortcut: same as :func:`classify_holders` but on a snapshot dict.

    Snapshots store ``[[owner, amount], ...]`` sorted descending; we
    re-sort to be safe (the on-disk format may evolve). Returns the
    tier map and a parallel index map.
    """
    pairs = []
    for h in holders or []:
        try:
            owner, amt = h[0], float(h[1])
            if owner and amt > 0:
                pairs.append((str(owner), float(amt)))
        except Exception:
            continue
    if not pairs:
        return {}, {}
    pairs.sort(key=lambda x: -x[1])
    tiers = classify_holders(pairs, n_total=len(pairs))
    return tiers, {owner: amt for owner, amt in pairs}


def holder_delta(ca: str, *, window_h: int, current_holders,
                 current_supply: float,
                 whale_min_sol: float = None,
                 dolphin_min_sol: float = None) -> dict:
    """Compute true holdings delta per tier over ``window_h`` hours.

    Looks up the newest committed snapshot with ``ts <= now - window_h*3600``
    as the baseline (T0), and compares to ``current_holders`` (T1, usually
    the live holders_df passed in by the dashboard).

    Returns a dict with per-tier aggregates and a human-readable
    ``reason`` explaining what changed. **No-data cases return a dict with
    ``ok=False`` and a clear reason** — callers should surface, not
    crash.

    Returned keys:
      ``ok`` (bool — any meaningful delta?),
      ``baseline_ts`` (int, 0 if none),
      ``window_h`` (int),
      ``supply`` (float — current supply, for pct conversions),
      ``whale`` / ``dolphin`` / ``minnow``: each a dict with
        ``delta_sol`` (signed), ``wallets_added``, ``wallets_exited``,
        ``holders_now``, ``holders_before``,
      ``summary`` (str — short human label like
        "whale +12.5 (3 new, 0 exit) · dolphin -2.0 (0 new, 1 exit)"),
      ``reason`` (str — what the data says in plain English),
      ``level`` ("ok" if no large move, "warn" if one tier moved
        meaningfully, "danger" if a whale sold heavily or several
        wallets exited).
    """
    whale_min = WHALE_DELTA_MIN_SOL if whale_min_sol is None else whale_min_sol
    dolphin_min = (DOLPHIN_DELTA_MIN_SOL if dolphin_min_sol is None
                   else dolphin_min_sol)
    now = int(time.time())
    win_start = now - int(window_h) * 3600

    state = load_holder_snapshots()
    base = _nearest_snapshot(state, ca, win_start)
    if base is None:
        return {
            "ok": False,
            "baseline_ts": 0,
            "window_h": int(window_h),
            "supply": float(current_supply) if current_supply else 0.0,
            "whale": {"delta_sol": 0.0, "wallets_added": 0,
                      "wallets_exited": 0, "holders_now": 0,
                      "holders_before": 0},
            "dolphin": {"delta_sol": 0.0, "wallets_added": 0,
                        "wallets_exited": 0, "holders_now": 0,
                        "holders_before": 0},
            "minnow": {"delta_sol": 0.0, "wallets_added": 0,
                       "wallets_exited": 0, "holders_now": 0,
                       "holders_before": 0},
            "summary": "no snapshot",
            "reason": ("no baseline snapshot ≤ window start — the 1h "
                       "cron has not committed one yet for this CA"),
            "level": "ok",
        }

    base_tiers, base_amts = _classify_snapshot(base.get("holders", []))
    cur_tiers, cur_amts = _classify_snapshot(current_holders)

    # Union of all wallet addresses across the two snapshots (and any
    # current holders not in baseline) so we account for new entries.
    all_wallets = set(base_amts) | set(cur_amts)

    tier_fields = {
        "whale": {"delta_sol": 0.0, "wallets_added": 0,
                  "wallets_exited": 0, "holders_now": 0,
                  "holders_before": 0},
        "dolphin": {"delta_sol": 0.0, "wallets_added": 0,
                    "wallets_exited": 0, "holders_now": 0,
                    "holders_before": 0},
        "minnow": {"delta_sol": 0.0, "wallets_added": 0,
                   "wallets_exited": 0, "holders_now": 0,
                   "holders_before": 0},
    }

    # For tier classification, an address inherits the HIGHER of its two
    # tiers (whale > dolphin > minnow). Reasoning: a wallet that drops
    # from whale to minnow is still mostly a whale story, not a minnow
    # story. This keeps the "5 whale exited" signal stable.
    tier_rank = {"whale": 2, "dolphin": 1, "minnow": 0}

    def _tier(w):
        b = base_tiers.get(w)
        c = cur_tiers.get(w)
        rb = tier_rank.get(b, -1)
        rc = tier_rank.get(c, -1)
        if rb < 0 and rc < 0:
            return None
        if rb >= rc:
            return b
        return c

    for w in all_wallets:
        t = _tier(w)
        if t is None:
            continue
        before = base_amts.get(w, 0.0)
        now_amt = cur_amts.get(w, 0.0)
        delta = now_amt - before
        if abs(delta) < 1e-9 and before > 0 and now_amt > 0:
            # no change for this wallet — counts as "still in tier"
            tier_fields[t]["holders_before"] += 1 if w in base_amts else 0
            tier_fields[t]["holders_now"] += 1 if w in cur_amts else 0
            continue
        tier_fields[t]["delta_sol"] += delta
        if w not in base_amts and w in cur_amts:
            tier_fields[t]["wallets_added"] += 1
        elif w in base_amts and w not in cur_amts:
            tier_fields[t]["wallets_exited"] += 1
        elif w in base_amts and w in cur_amts:
            # exited if the drop ≥ 90% of baseline (configurable).
            # Use a small epsilon to avoid floating-point edge cases
            # (e.g. 100 * 0.10 = 9.99999… where 10 SOL is "exited" but
            # the strict ≤ fails).
            if before > 0 and now_amt <= before * (1 - EXIT_DROP_PCT) + 1e-9:
                tier_fields[t]["wallets_exited"] += 1
        if w in base_amts:
            tier_fields[t]["holders_before"] += 1
        if w in cur_amts:
            tier_fields[t]["holders_now"] += 1

    # Round deltas for the UI / log
    for t in tier_fields:
        tier_fields[t]["delta_sol"] = round(tier_fields[t]["delta_sol"], 2)

    def _tier_label(t, f, min_sol):
        d = f["delta_sol"]
        # 'minnow' has min_sol=0.0 — for it, a tier entry is only
        # meaningful if SOMETHING happened (delta != 0, or wallets
        # added/exited). Otherwise we would always emit "M +0.0".
        if min_sol > 0:
            threshold_ok = abs(d) >= min_sol
        else:
            threshold_ok = (abs(d) > 1e-6) or f["wallets_added"] > 0 \
                or f["wallets_exited"] > 0
        if not threshold_ok:
            return None
        sign = "+" if d >= 0 else ""
        parts = [f"{t[0].upper()} {sign}{d:.1f}"]
        if f["wallets_added"]:
            parts.append(f"{f['wallets_added']} new")
        if f["wallets_exited"]:
            parts.append(f"{f['wallets_exited']} exit")
        return " · ".join(parts)

    parts = []
    for t, min_sol in (("whale", whale_min),
                       ("dolphin", dolphin_min),
                       ("minnow", 0.0)):
        lab = _tier_label(t, tier_fields[t], min_sol)
        if lab:
            parts.append(lab)
    summary = " · ".join(parts) if parts else "no meaningful move"

    # Plain-English reason + warn/danger level
    level = "ok"
    bits = []
    w = tier_fields["whale"]
    d = tier_fields["dolphin"]
    if abs(w["delta_sol"]) >= whale_min:
        if w["delta_sol"] <= -whale_min * 2 and w["wallets_exited"] >= 1:
            level = "danger"
            bits.append(f"🐋 whales dumped {abs(w['delta_sol']):.1f} SOL "
                       f"({w['wallets_exited']} exited) — heavy distribution")
        elif w["delta_sol"] <= -whale_min:
            level = "warn" if level == "ok" else level
            bits.append(f"🐋 whales sold {abs(w['delta_sol']):.1f} SOL in the window")
        elif w["delta_sol"] >= whale_min:
            bits.append(f"🐋 whales added {w['delta_sol']:.1f} SOL "
                        f"({w['wallets_added']} new)")
    if abs(d["delta_sol"]) >= dolphin_min:
        if d["delta_sol"] <= -dolphin_min:
            level = "warn" if level == "ok" else level
            bits.append(f"🐬 dolphins sold {abs(d['delta_sol']):.1f} SOL")
        elif d["delta_sol"] >= dolphin_min:
            bits.append(f"🐬 dolphins added {d['delta_sol']:.1f} SOL "
                        f"({d['wallets_added']} new)")
    if not bits:
        bits.append(f"no tier moved ≥ whale {whale_min:g} or "
                    f"dolphin {dolphin_min:g} SOL in the last {window_h}h")

    return {
        "ok": bool(parts),
        "baseline_ts": int(base.get("ts", 0)),
        "window_h": int(window_h),
        "supply": float(current_supply) if current_supply else 0.0,
        "whale": tier_fields["whale"],
        "dolphin": tier_fields["dolphin"],
        "minnow": tier_fields["minnow"],
        "summary": summary,
        "reason": " · ".join(bits),
        "level": level,
    }


def load_holder_delta_config() -> dict:
    """Read the owner-tunable thresholds from ``config.json`` if present.

    The dashboard keeps a ``whale_delta_min_sol`` and
    ``dolphin_delta_min_sol`` field on its CONFIG dict. This helper just
    picks them up so :func:`holder_delta` can default to them.
    Returns ``{}`` if no config is reachable — callers should fall back
    to the module-level constants in that case.
    """
    try:
        with open(os.path.join(BASE_DIR, "config.json"),
                  "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
        return {
            "whale_delta_min_sol": float(
                cfg.get("whale_delta_min_sol", WHALE_DELTA_MIN_SOL)),
            "dolphin_delta_min_sol": float(
                cfg.get("dolphin_delta_min_sol", DOLPHIN_DELTA_MIN_SOL)),
        }
    except Exception:
        return {}


def holder_delta_panel(ca: str, *, current_holders, supply: float,
                       window_h: int = 6) -> dict:
    """Convenience wrapper: read config + call :func:`holder_delta`.

    Returns the same dict but with config applied. Used by the UI so
    it doesn't have to import the loader separately.
    """
    cfg = load_holder_delta_config()
    return holder_delta(
        ca, window_h=window_h, current_holders=current_holders,
        current_supply=supply,
        whale_min_sol=cfg.get("whale_delta_min_sol"),
        dolphin_min_sol=cfg.get("dolphin_delta_min_sol"),
    )


# ---------------------------------------------------------------------------
# Candle pattern detection (small-body patterns on H4 for degen screener)
# ---------------------------------------------------------------------------
PATTERN_EMOJI = {
    "Doji": "🕯️",
    "Hammer": "🔨",
    "Inverted Hammer": "🔄",
    "Spinning Top": "🌀",
    "Dragonfly Doji": "🕊️",
    "Gravestone Doji": "⚰️",
}


def detect_candle_patterns(candles: list[dict]) -> dict[str, int]:
    """Detect small-body candle patterns in H4 candles.

    Scans the last 48h of H4 candles (up to 12 bars) for reversal /
    indecision patterns: Doji, Hammer, Inverted Hammer, Spinning Top,
    Dragonfly Doji, Gravestone Doji.

    Each candle dict must have keys ``o, h, l, c`` (floats).

    Returns a dict mapping pattern name -> count of occurrences.
    Heuristic only — not a trading signal.
    """
    if not candles:
        return {}

    counts: dict[str, int] = {}

    for c in candles:
        o, h, l, cl = c["o"], c["h"], c["l"], c["c"]
        rng = h - l
        if rng <= 0:
            continue

        body = abs(cl - o)
        body_ratio = body / rng
        upper_shadow = h - max(o, cl)
        lower_shadow = min(o, cl) - l
        us_ratio = upper_shadow / rng
        ls_ratio = lower_shadow / rng

        # Doji family: body ≤ 10% of range
        if body_ratio <= 0.10:
            if ls_ratio >= 0.60 and us_ratio <= 0.15:
                name = "Dragonfly Doji"
            elif us_ratio >= 0.60 and ls_ratio <= 0.15:
                name = "Gravestone Doji"
            else:
                name = "Doji"
            counts[name] = counts.get(name, 0) + 1

        # Hammer: body ≤ 30%, long lower shadow (≥ 60%), small upper shadow
        elif body_ratio <= 0.30 and ls_ratio >= 0.60 and us_ratio <= 0.15:
            name = "Hammer"
            counts[name] = counts.get(name, 0) + 1

        # Inverted Hammer / Shooting Star: body ≤ 30%, long upper shadow
        # (≥ 60%), small lower shadow
        elif body_ratio <= 0.30 and us_ratio >= 0.60 and ls_ratio <= 0.15:
            name = "Inverted Hammer"
            counts[name] = counts.get(name, 0) + 1

        # Spinning Top: body ≤ 25%, both shadows ≥ 25%
        elif body_ratio <= 0.25 and us_ratio >= 0.25 and ls_ratio >= 0.25:
            name = "Spinning Top"
            counts[name] = counts.get(name, 0) + 1

    return counts
