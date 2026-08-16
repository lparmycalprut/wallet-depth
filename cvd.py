# -*- coding: utf-8 -*-
"""Normalized Solana trade fetch layer for daily effort analysis."""
import json
import os
import time

import requests

from core import (HELIUS_ENHANCED_URL, atomic_write_json, helius_api_get,
                  helius_rpc_request as _core_helius_rpc_request,
                  select_dexscreener_pair)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
MIN_SOL = 0.05      # ignore swaps below (~$10) — bot/dust noise

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
        pair = select_dexscreener_pair(pairs, SOL_MINT)
        px = float(pair.get("priceUsd") or 0) if pair else 0.0
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
# ``error`` is reserved for an actual transport/API/mapping failure.
# A successful empty page (quiet token) is not an error: callers may still
# safely calculate a window from already-stored swaps.  Keeping the outcome
# separately prevents the cron from minting a "fresh" derived metric after
# a failed fetch while still allowing a genuinely quiet token to be handled
# normally.
_gmgn_last = {
    "error": "",
    "note": "",
    "ok": None,
    "complete": False,
    "outcome": "idle",
    "raw_seen": 0,
}
_gmgn_wallet_meta = {"data": {}}


def get_gmgn_wallet_metadata() -> dict:
    """Per-wallet metadata from the most recent GMGN fetch.

    Only populated when ``use_gmgn=True`` is used.  Keys are wallet
    addresses; values are dicts with ``maker_tags``, ``maker_token_tags``,
    ``maker_event_tags``, ``total_trade``, ``balance``,
    ``history_bought_amount``, ``history_sold_amount``, ``realized_profit``,
    ``unrealized_profit``.
    """
    return _gmgn_wallet_meta.get("data") or {}


def _gmgn_build_params() -> dict:
    """Query params matching the live GMGN web client (build tag, device id).

    ``requests``/``curl_cffi`` URL-encode ``params`` themselves, so timezone
    must be passed as plain ``Asia/Jakarta``.  Passing ``Asia%2FJakarta``
    here produces ``Asia%252FJakarta`` on the wire and can make GMGN reject
    an otherwise valid browser-shaped request.
    """
    import uuid as _uuid
    params = {
        "from_app": "gmgn",
        "tz_name": "Asia/Jakarta",
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


def _reset_gmgn_fetch_status() -> None:
    """Clear outcome metadata before a new GMGN trades request."""
    _gmgn_last.update(error="", note="", ok=None, complete=False,
                      outcome="fetching", raw_seen=0)


def _set_gmgn_error(message: str) -> None:
    _gmgn_last["error"] = str(message or "").strip()


def get_gmgn_last_error() -> str:
    """Last human-readable GMGN fetch result/problem, if any.

    Kept for compatibility with existing UI callers: a valid empty response
    still returns its explanatory note here. New persistence code must use
    :func:`get_gmgn_fetch_status` and inspect ``status['error']``/``ok`` so
    a quiet token is not mistaken for a failed fetch.
    """
    return _gmgn_last.get("error") or _gmgn_last.get("note") or ""


def get_gmgn_fetch_status() -> dict:
    """Return metadata for the most recent GMGN trades fetch.

    ``ok`` means the endpoint and trade mapping were usable. ``complete``
    additionally guarantees that pagination reached the requested cutoff/end
    instead of stopping at a transport error, duplicate cursor, or page cap.
    Consumers that persist daily data must require both values before advancing the
    cursor or recording a derived metric.
    """
    return dict(_gmgn_last)


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


def _gmgn_amount_usd(trade: dict) -> float:
    """USD value of one GMGN trade — the canonical daily-volume unit.

    Semua perbandingan volume antar-hari memakai USD (bukan SOL). Prioritas:
      1. ``amount_usd`` langsung dari GMGN                    (paling akurat)
      2. ``quote_amount`` USDC/USDT yang terverifikasi        (1:1 dengan USD)
      3. ``quote_amount`` SOL/WSOL × harga SOL/USD            (estimasi)
      4. 0.0 bila tidak bisa diverifikasi (pemanggil bisa fallback ke
         ``sol_eq × harga SOL`` agar baris tetap punya volume USD).
    """
    # ── 1. amount_usd ───────────────────────────────────────────────
    usd_amount = _as_float(_first_nested(
        trade, "amount_usd", "amountUSD", "cost_usd", "costUsd", "usd",
        "value_usd", "valueUsd", "volume_usd", "volumeUsd",
        "trade_usd", "tradeUsd", "usd_value", "usdValue"), 0.0)
    if usd_amount > 0:
        return usd_amount

    # ── 2/3. quote_amount dengan quote token yang terverifikasi ─────
    quote_amount = _as_float(_first_nested(
        trade, "quote_amount", "quoteAmount", "quote_amount_ui",
        "quoteAmountUi", "quote_amount_decimal"), 0.0)
    if quote_amount <= 0:
        return 0.0
    quote_addr = str(_first_nested(
        trade, "quote_address", "quote_token_address", "quote_mint",
        "quote_token.address", "quoteToken.address", default="") or "")
    quote_sym = str(_first_nested(
        trade, "quote_symbol", "quote_token.symbol", "quoteToken.symbol",
        default="") or "").lower()
    if quote_addr in (USDC_MINT, USDT_MINT) or quote_sym in ("usdc", "usdt"):
        return quote_amount
    if quote_addr == SOL_MINT or quote_sym in ("sol", "wsol"):
        if quote_amount > 10_000_000:          # raw lamports
            quote_amount /= 1_000_000_000
        sp = get_sol_price()
        return quote_amount * sp if sp else 0.0
    return 0.0


def _gmgn_trade_tags(trade: dict) -> list:
    """Normalized union of maker_tags / maker_token_tags / maker_event_tags.

    Tags dinormalisasi (lowercase snake_case) supaya pencocokan 4 penanda
    on-chain di cvd_daily konsisten. Urutan dipertahankan, duplikat dibuang.
    """
    tags = []
    for raw in (
        _first_nested(trade, "maker_tags", "makerTags", default=[]),
        _first_nested(trade, "maker_token_tags", "makerTokenTags",
                      default=[]),
        _first_nested(trade, "maker_event_tags", "makerEventTags",
                      "event_tags", "eventTags", default=[]),
    ):
        if isinstance(raw, str):
            raw = [t.strip() for t in raw.split(",") if t.strip()]
        if isinstance(raw, (list, tuple)):
            tags.extend(raw)
    normalized = []
    seen = set()
    for tag in tags:
        clean = str(tag or "").strip().lower().replace(" ", "_") \
            .replace("-", "_")
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized


def gmgn_trade_to_swap(trade: dict):
    """Convert a GMGN trade into an enriched swap tuple.

    ``(side, sol_eq, ts, wallet, price_usd, amount_usd, tags)`` — legacy
    4/5-element consumers keep working; the USD volume and maker tags feed
    the bottom detector's daily aggregation.
    """
    if not isinstance(trade, dict):
        return None
    side = _gmgn_side(trade)
    sol_eq = _gmgn_sol_equivalent(trade)
    ts = _normalize_ts(_first_nested(
        trade, "timestamp", "time", "block_time", "created_at",
        "createdAt"))
    wallet = _first_nested(trade, "maker", "wallet", "maker_info.address",
                           "address", "user_address", default="") or ""
    price = _as_float(_first_nested(
        trade, "price_usd", "priceUsd", "token_price_usd",
        "tokenPriceUsd", "price", default=0), 0.0)
    if side not in ("buy", "sell") or sol_eq <= 0 or ts <= 0:
        return None
    # ── Sanity cap: no single swap is legitimately > 1,000 SOL ─────
    # Values above this threshold are almost certainly a data-mapping
    # error (e.g. GMGN returned base-token raw amount in quote_amount).
    MAX_SWAP_SOL = 1000.0
    if sol_eq > MAX_SWAP_SOL:
        return None
    amount_usd = _gmgn_amount_usd(trade)
    if amount_usd <= 0:
        # Fallback terakhir: estimasi dari SOL-equivalent × harga SOL saat
        # ini agar baris harian tetap punya volume USD yang sebanding.
        sp = get_sol_price()
        amount_usd = sol_eq * sp if sp else 0.0
    return (side, float(sol_eq), int(ts), str(wallet),
            float(price) if price > 0 else None, float(amount_usd),
            _gmgn_trade_tags(trade))

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
    """GET GMGN with browser TLS, then a normal-requests fallback.

    ``curl_cffi`` can be installed but fail at runtime (unsupported browser
    profile, OpenSSL issue, or a transient TLS reset).  The old fallback ran
    only when the package was absent, so a runtime curl failure made every
    GMGN fetch fail without even trying the ordinary HTTP client.
    """
    curl_error = None
    try:
        from curl_cffi import requests as cr
    except Exception as exc:  # broken optional install must not block fallback
        cr = None
        curl_error = exc
    if cr is not None:
        for imp in ("chrome", "chrome131", "safari17_0"):
            try:
                return cr.get(url, params=params, headers=GMGN_HEADERS,
                              impersonate=imp, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                curl_error = exc
    try:
        return requests.get(url, params=params, headers=GMGN_HEADERS,
                            timeout=timeout)
    except Exception as exc:
        if curl_error is not None:
            raise RuntimeError(
                f"browser TLS failed ({type(curl_error).__name__}: "
                f"{curl_error}); requests fallback failed "
                f"({type(exc).__name__}: {exc})") from exc
        raise


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
    evt_tags_raw = _first_nested(trade, "maker_event_tags", "makerEventTags",
                                 "event_tags", "eventTags", default=[])
    if isinstance(evt_tags_raw, str):
        evt_tags_raw = [t.strip() for t in evt_tags_raw.split(",")
                        if t.strip()]
    return {
        "maker_tags": list(tags_raw) if isinstance(tags_raw, list) else [],
        "maker_token_tags": (list(tok_tags_raw)
                             if isinstance(tok_tags_raw, list) else []),
        "maker_event_tags": (list(evt_tags_raw)
                             if isinstance(evt_tags_raw, list) else []),
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
    """Fetch GMGN Token Trades and map them to normalized swap tuples.

    GMGN fields are mapped as requested:
    ``event`` -> buy/sell, ``quote_amount``/``amount_usd`` -> SOL-equivalent,
    ``timestamp`` -> ts, and ``maker`` -> wallet.

    Returns ``(swaps, newest_sig, newest_ts, hit_stop)``. GMGN swap rows are
    enriched: element 4 = trade price USD (candle fallback), element 5 =
    ``amount_usd`` (unit kanonik volume harian USD), element 6 = normalized
    maker tag list (maker_tags/maker_token_tags/maker_event_tags). Completion
    metadata is exposed separately via :func:`get_gmgn_fetch_status` so
    legacy callers keep their tuple contract while persistence callers can
    reject partial data safely.
    """
    _reset_gmgn_fetch_status()
    _gmgn_wallet_meta["data"] = {}
    swaps, cursor = [], None
    newest_sig, newest_ts, hit_stop = None, None, False
    seen_trades, seen_cursors = set(), set()
    raw_seen = mapped_seen = 0
    stopped_by_cutoff = False
    complete = False
    wallet_meta = {}

    for _ in range(max_pages):
        raw_trades, next_cursor = _fetch_gmgn_page(
            ca, cursor=cursor, limit=page_limit,
            from_ts=from_ts, to_ts=to_ts)
        if raw_trades is None:
            # _fetch_gmgn_page already recorded a transport/API error.
            break
        if not raw_trades:
            # A successful empty page means pagination reached its end.
            complete = True
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
                # Collect per-wallet metadata (last trade wins).
                w = s[3]
                if w:
                    try:
                        wallet_meta[w] = _extract_gmgn_trade_meta(trade)
                    except Exception:
                        pass
        if hit_stop:
            # Sorted newest→oldest, so crossing the stored cursor/cutoff
            # proves that all requested newer trades were visited.
            complete = True
            break
        if new_on_page == 0:
            _set_gmgn_error("GMGN pagination returned duplicate trades only.")
            break
        cursor = next_cursor
        if not cursor and len(raw_trades) >= page_limit:
            # Some responses omit ``next``.  Their cursor is the oldest
            # trade id, matching the live web client convention.
            cursor = _gmgn_trade_key(raw_trades[-1])
        if not cursor:
            complete = True
            break
        if cursor in seen_cursors:
            _set_gmgn_error("GMGN pagination repeated its cursor.")
            break
        seen_cursors.add(cursor)
        time.sleep(sleep)
    else:
        _set_gmgn_error(
            f"GMGN pagination reached its {max_pages}-page safety cap "
            "before the requested cutoff.")

    # Do not use get_gmgn_last_error() here: that compatibility helper also
    # returns a benign "no eligible trades" note for legacy UI callers.
    error = _gmgn_last.get("error") or ""
    note = ""
    outcome = "ok"
    if error:
        outcome = "error"
    elif not raw_seen:
        outcome = "empty"
        note = "GMGN returned no trades for this token."
    elif stopped_by_cutoff and not swaps:
        outcome = "empty"
        note = "GMGN returned no eligible trades newer than the cutoff."
    elif raw_seen and not mapped_seen:
        _set_gmgn_error(
            "GMGN returned trades, but none had event/timestamp/volume "
            "fields that could be mapped to normalized swaps.")
        error = _gmgn_last.get("error") or ""
        outcome = "error"
    elif mapped_seen and not swaps:
        outcome = "below_min"
        note = (f"GMGN returned trades, but all were below "
                f"{MIN_SOL:g} SOL.")

    _gmgn_last.update(error=error, note=note, ok=not bool(error),
                      complete=bool(complete and not error),
                      outcome=outcome, raw_seen=raw_seen)
    _gmgn_wallet_meta["data"] = wallet_meta
    return swaps, newest_sig, newest_ts, hit_stop



def classify_swap(tx: dict, pool: str, ca: str):
    """Return enriched swap tuple or None.

    ``(side, sol_eq, ts, wallet, None, amount_usd, tags)`` — works for
    SOL-quoted AND USDC/USDT-quoted pools (converted to SOL). Helius tidak
    memberi tag maker, jadi ``tags`` kosong; ``amount_usd`` diestimasi dari
    SOL-equivalent × harga SOL/USD saat fetch (path fallback saja — GMGN
    tetap menjadi sumber utama ``amount_usd`` yang akurat).
    """
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
    sp = get_sol_price()
    if ca_out > ca_in and q_in > 0:        # token left pool -> BUY
        return ("buy", q_in, ts, wallet, None,
                q_in * sp if sp else 0.0, [])
    if ca_in > ca_out and q_out > 0:       # token entered pool -> SELL
        return ("sell", q_out, ts, wallet, None,
                q_out * sp if sp else 0.0, [])
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
        gmgn_result = fetch_gmgn_swaps(
            ca, stop_sig=stop_sig, stop_ts=stop_ts, max_pages=max_pages,
            sleep=sleep, from_ts=from_ts, to_ts=to_ts)
        status = get_gmgn_fetch_status()
        # Auto-fallback to Helius if GMGN fails (incomplete / error / cap)
        if (not status.get("ok") or not status.get("complete") or
                (status.get("error") and status.get("error"))):
            # Try Helius with same parameters; pool/api_key already available.
            # Note: Helius requires pool; if empty we skip fallback gracefully.
            if pool and api_key:
                try:
                    return fetch_swaps(
                        api_key, pool, ca, stop_sig=stop_sig,
                        stop_ts=stop_ts, max_pages=max_pages,
                        sleep=sleep, use_gmgn=False,
                        from_ts=from_ts, to_ts=to_ts)
                except Exception:
                    pass  # keep original GMGN failure result
        return gmgn_result
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
