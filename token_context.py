# -*- coding: utf-8 -*-
"""Real per-token display context: distance from ATH + holder average cost.

Both numbers used to be *invented* by ``gmgn_screener._get_avg_cost_and_ath``
(a hard-coded ``-90%`` ATH and ``-65%`` avg cost whenever GMGN did not send
a field with that exact name — which is always, because the trending payload
has no such field). That is why every row read "🟢 Down 90.0% dari ATH" and
why the LP/Degen cards never showed an avg cost.

This module fetches the real thing:

* **avg cost** — from GMGN's per-token holder list
  (``GET /vas/api/v1/token_holders/sol/<CA>?limit=100&cost=20
  &orderby=unrealized_profit&direction=desc`` with a per-token Referer).
  The aggregate is ``sum(cost) / sum(balance)`` (remaining USD cost basis
  divided by token count), because most wallets carry ``avg_cost: null``
  while their ``cost`` field is still populated.  AMM/pool rows
  (``addr_type != 0`` or a non-empty ``exchange``) are skipped.
* **down from ATH** — the token's all-time-high close from GeckoTerminal
  daily candles (pair resolved via DexScreener), or from an ATH-ish field
  when GMGN happens to send one.

Every function is failure-tolerant and returns ``None`` when the value is
genuinely unknown. **Never** guess: the UI renders ``—`` for ``None``, which
is honest, whereas a fabricated ``-90%`` on every row is not.
"""
import time

__all__ = [
    "holder_avg_cost", "avg_cost_change_pct", "down_from_ath_pct",
    "token_context", "enrich_rows", "clear_cache",
]

GMGN_ORIGIN = "https://gmgn.ai"

#: verified holder endpoint (captured from browser HAR 2026-07-31).
#: Path: ``/vas/api/v1/token_holders/sol/<CA>``.
#: Required query params: ``cost=20&orderby=unrealized_profit&direction=desc``
#: (without these the response is empty or lacks the ``cost`` field).
#: Referer must be per-token: ``https://gmgn.ai/sol/token/<CA>``.
HOLDER_PATH = "/vas/api/v1/token_holders/sol/{ca}"

#: cache: ca -> (ts, dict). GMGN/GeckoTerminal are rate-limited and these
#: numbers are display-only, so a few minutes of staleness is fine.
_CACHE_TTL = 300.0
_cache = {}


def clear_cache():
    """Drop the per-CA context cache (used by the 'force rescan' buttons)."""
    _cache.clear()


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _f(v, default=None):
    """float() that never raises and rejects NaN/inf/None/''."""
    try:
        if v is None or isinstance(v, bool) or v == "":
            return default
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return f


def _http_get(url, *, params=None, timeout=15, headers=None):
    """GET with curl_cffi browser TLS when available, plain requests else."""
    hdrs = headers or _HEADERS
    try:
        from curl_cffi import requests as cr
        last = None
        for imp in ("chrome", "chrome131", "safari17_0"):
            try:
                return cr.get(url, params=params, headers=hdrs,
                              impersonate=imp, timeout=timeout)
            except Exception as exc:                      # noqa: BLE001
                last = exc
        if last:
            raise last
    except ImportError:
        pass
    import requests
    return requests.get(url, params=params, headers=hdrs, timeout=timeout)


_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "origin": GMGN_ORIGIN,
    "referer": GMGN_ORIGIN + "/",
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


def _gmgn_params():
    try:
        from gmgn_screener import _build_tag, DEVICE_ID, FP_DID
        build = _build_tag()
        return {"device_id": DEVICE_ID, "fp_did": FP_DID,
                "client_id": f"gmgn_web_{build}", "app_ver": build,
                "from_app": "gmgn", "tz_name": "Asia/Jakarta",
                "tz_offset": "25200", "app_lang": "en-US", "os": "web",
                "worker": "0"}
    except Exception:                                     # noqa: BLE001
        return {"from_app": "gmgn", "os": "web", "app_lang": "en-US"}


def _holder_list(payload):
    """Dig the holder/trader array out of whatever shape GMGN replies with."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("list", "holders", "traders", "items", "rows"):
            arr = data.get(key)
            if isinstance(arr, list):
                return [x for x in arr if isinstance(x, dict)]
    return []


# ---------------------------------------------------------------------------
# holder average cost
# ---------------------------------------------------------------------------
def fetch_holders(ca: str, *, limit: int = 100, timeout: int = 15,
                  orderby: str = "unrealized_profit", tag: str = "",
                  all_pages: bool = False, max_pages: int = 100):
    """GMGN holder rows for one CA (``[]`` on any failure).

    Uses the verified ``/vas/api/v1/token_holders/sol/<CA>`` endpoint.
    The ``cost``, ``orderby``, and ``direction`` query params are mandatory
    — without them the server returns an empty list or rows without the
    ``cost`` field.  Referer must be the per-token page URL.
    """
    if not ca:
        return []
    params = _gmgn_params()
    params["limit"] = limit
    params["cost"] = 20
    params["orderby"] = orderby
    params["direction"] = "desc"
    if tag:
        params["tag"] = tag
    url = GMGN_ORIGIN + HOLDER_PATH.format(ca=ca)
    headers = dict(_HEADERS)
    headers["referer"] = f"{GMGN_ORIGIN}/sol/token/{ca}"
    out = []
    cursor = None
    seen = set()
    for _page in range(max(1, int(max_pages)) if all_pages else 1):
        query = dict(params)
        if cursor:
            query["cursor"] = cursor
        try:
            r = _http_get(url, params=query, timeout=timeout, headers=headers)
            if getattr(r, "status_code", None) != 200:
                break
            payload = r.json() or {}
        except Exception:                                     # noqa: BLE001
            break
        if isinstance(payload, dict) and \
                payload.get("code") not in (None, 0, "0", "success"):
            break
        page = _holder_list(payload)
        out.extend(page)
        if not all_pages or not page:
            break
        # GMGN puts the opaque continuation token under data.next; tolerate
        # top-level next/cursor too because this is an undocumented endpoint.
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = {}
        next_cursor = (data.get("next") or payload.get("next") or
                       data.get("cursor") or payload.get("cursor"))
        if not next_cursor or str(next_cursor) in seen:
            break
        seen.add(str(next_cursor))
        cursor = str(next_cursor)
    return out


def holder_avg_cost(holders) -> float:
    """Aggregate average entry price across holders, or ``None``.

    Uses ``sum(cost) / sum(balance)`` rather than the per-row ``avg_cost``
    field because many wallets (transfer-funded ones) have
    ``avg_cost: null`` while their ``cost`` field (remaining cost basis in
    USD) is still populated.  This gives much wider float coverage.

    AMM/pool rows (``addr_type != 0`` or a non-empty ``exchange`` field,
    e.g. ``pump_amm``) are discarded because they carry no meaningful
    cost basis.
    """
    total_cost = 0.0
    total_balance = 0.0
    for h in holders or []:
        if not isinstance(h, dict):
            continue
        # skip pools / AMM accounts — they have no cost basis
        if h.get("exchange") or h.get("addr_type") not in (0, None, "0"):
            continue
        bal = _f(h.get("balance"), None)
        if bal is None:
            bal = _f(h.get("amount_cur"), 0.0) or 0.0
        if bal <= 0:
            continue
        cost = _f(h.get("cost"), None)
        if cost is None or cost <= 0:
            continue
        total_cost += cost
        total_balance += bal
    if total_balance <= 0:
        return None
    return total_cost / total_balance


def avg_cost_change_pct(price: float, holders) -> float:
    """Current price vs holder average cost, in % (``None`` when unknown).

    ``-65`` means the average holder is 65% underwater; ``+20`` means the
    average holder is 20% in profit.
    """
    price = _f(price, None)
    avg = holder_avg_cost(holders)
    if not price or not avg or avg <= 0:
        return None
    return (price / avg - 1.0) * 100.0


# ---------------------------------------------------------------------------
# distance from ATH
# ---------------------------------------------------------------------------
def _resolve_pair(ca: str, timeout: int = 10):
    """Highest-liquidity DexScreener pair address for a CA, or ``None``."""
    try:
        r = _http_get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                      timeout=timeout, headers={"accept": "application/json"})
        pairs = (r.json() or {}).get("pairs") or []
    except Exception:                                     # noqa: BLE001
        return None
    pairs = [p for p in pairs if isinstance(p, dict)]
    if not pairs:
        return None
    pairs.sort(key=lambda p: _f((p.get("liquidity") or {}).get("usd"), 0.0)
               or 0.0, reverse=True)
    return pairs[0].get("pairAddress")


def _ath_from_candles(pair: str, timeout: int = 12):
    """All-time-high price from GeckoTerminal daily candles, or ``None``."""
    if not pair:
        return None
    try:
        r = _http_get(
            "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pair}/ohlcv/day",
            params={"aggregate": 1, "limit": 1000}, timeout=timeout,
            headers={"accept": "application/json"})
        lst = (((r.json() or {}).get("data") or {})
               .get("attributes") or {}).get("ohlcv_list") or []
    except Exception:                                     # noqa: BLE001
        return None
    highs = [_f(x[2], None) for x in lst if isinstance(x, (list, tuple))
             and len(x) > 2]
    highs = [h for h in highs if h and h > 0]
    return max(highs) if highs else None


def down_from_ath_pct(token: dict, *, ca: str = "", price: float = None):
    """% the current price sits below the all-time high (``None`` unknown).

    Order of preference:

    1. an explicit ATH-ish field on the GMGN token dict;
    2. an ATH derived from the market-cap high (``max_market_cap``) — same
       ratio as price when supply is constant;
    3. GeckoTerminal daily candles for the token's deepest pair.
    """
    token = token or {}
    price = _f(price if price is not None
               else token.get("p") or token.get("price"), None)

    for key in ("down_from_ath", "down_pct_from_ath", "ath_down_pct"):
        v = _f(token.get(key), None)
        if v is not None:
            return abs(v)

    ath = None
    for key in ("ath", "ath_price", "highest_price", "highestPrice",
                "max_price", "price_ath"):
        ath = _f(token.get(key), None)
        if ath and ath > 0:
            break
        ath = None

    if ath is None:
        mc = _f(token.get("mc") or token.get("market_cap"), None)
        mc_high = None
        for key in ("max_market_cap", "ath_market_cap", "mc_high",
                    "max_mc", "highest_market_cap"):
            mc_high = _f(token.get(key), None)
            if mc_high and mc_high > 0:
                break
            mc_high = None
        if price and mc and mc > 0 and mc_high and mc_high >= mc:
            ath = price * (mc_high / mc)

    if ath is None and ca:
        ath = _ath_from_candles(_resolve_pair(ca))

    if not ath or not price or ath <= 0:
        return None
    return max(0.0, (ath - price) / ath * 100.0)


# ---------------------------------------------------------------------------
# public entry points
# ---------------------------------------------------------------------------
def token_context(ca: str, token: dict = None, *, price: float = None,
                  use_cache: bool = True) -> dict:
    """``{"avg_cost": float|None, "down_ath": float|None}`` for one CA."""
    token = token or {}
    price = _f(price if price is not None
               else token.get("p") or token.get("price"), None)
    now = time.time()
    if use_cache and ca in _cache:
        ts, val = _cache[ca]
        if now - ts < _CACHE_TTL:
            return dict(val)

    try:
        holders = fetch_holders(ca)
    except Exception:                                     # noqa: BLE001
        holders = []
    try:
        avg = avg_cost_change_pct(price, holders)
    except Exception:                                     # noqa: BLE001
        avg = None
    try:
        down = down_from_ath_pct(token, ca=ca, price=price)
    except Exception:                                     # noqa: BLE001
        down = None

    out = {"avg_cost": avg, "down_ath": down}
    _cache[ca] = (now, dict(out))
    return out


def enrich_rows(rows, tokens_by_ca=None, *, max_workers: int = 6,
                limit: int = None):
    """Attach real ``avg_cost`` / ``down_ath`` to screener rows, in place.

    Network work runs in a small thread pool. Rows whose context cannot be
    resolved keep ``None`` — callers must render that as ``—``, never as a
    made-up number.
    """
    rows = rows or []
    todo = [r for r in rows if isinstance(r, dict) and r.get("ca")]
    if limit is not None:
        todo = todo[:limit]
    if not todo:
        return rows
    tokens_by_ca = tokens_by_ca or {}

    def _one(row):
        ca = row["ca"]
        return row, token_context(ca, tokens_by_ca.get(ca) or {},
                                  price=row.get("price"))

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers,
                                                       len(todo)))) as pool:
            futs = [pool.submit(_one, r) for r in todo]
            for fut in as_completed(futs):
                try:
                    row, ctx = fut.result()
                except Exception:                         # noqa: BLE001
                    continue
                row["avg_cost"] = ctx.get("avg_cost")
                row["down_ath"] = ctx.get("down_ath")
    except Exception:                                     # noqa: BLE001
        for row in todo:
            try:
                ctx = token_context(row["ca"],
                                    tokens_by_ca.get(row["ca"]) or {},
                                    price=row.get("price"))
            except Exception:                             # noqa: BLE001
                continue
            row["avg_cost"] = ctx.get("avg_cost")
            row["down_ath"] = ctx.get("down_ath")
    return rows
