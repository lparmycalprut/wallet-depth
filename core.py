# -*- coding: utf-8 -*-
"""Shared configuration and market/trade fetch infrastructure."""
from datetime import datetime, timezone
import json
import math
import os
import tempfile
import threading

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HELIUS_RPC_URL = "https://mainnet.helius-rpc.com/"
HELIUS_ENHANCED_URL = "https://api.helius.xyz"

_helius_rotation_lock = threading.Lock()
_helius_rotation_index = 0


def atomic_write_json(path: str, data, **dump_kwargs) -> None:
    """Write JSON to path atomically: write to a temp file in the same
    directory, flush+fsync, then os.replace() over the target. Prevents
    truncated/corrupt files if the process dies mid-write."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def merge_helius_keys(*values) -> list[str]:
    """Normalize comma/newline-separated Helius keys and de-duplicate them.

    Values may be strings or iterables, which keeps this helper usable for
    config.json, environment variables, Streamlit secrets, and UI fields.
    The first occurrence wins so the configured primary key stays first.
    """
    keys = []

    def _add(value):
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _add(item)
            return
        for key in str(value or "").replace("\r", "\n").replace(
                "\n", ",").split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)

    for value in values:
        _add(value)
    return keys


def _config_file() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _streamlit_helius_keys() -> list[str]:
    try:
        import streamlit as st
        return merge_helius_keys(st.secrets.get("helius_api_key", ""),
                                 st.secrets.get("helius_extra_keys", ""))
    except Exception:
        return []


def get_helius_keys(*, primary=None, extras=None, config=None) -> list[str]:
    """Return one de-duplicated Helius key pool from every supported source.

    Explicit values (for example the live sidebar fields) come first, then an
    optional config mapping, config.json, environment variables, and
    Streamlit secrets.  Reading every source instead of overriding one source
    with another ensures extra keys are never silently dropped.
    """
    passed = config or {}
    disk = _config_file()
    return merge_helius_keys(
        primary, extras,
        passed.get("helius_api_key"), passed.get("helius_extra_keys"),
        disk.get("helius_api_key"), disk.get("helius_extra_keys"),
        os.environ.get("HELIUS_API_KEY"),
        os.environ.get("HELIUS_API_KEYS"),
        _streamlit_helius_keys(),
    )


def get_holder_source(default: str = "auto") -> str:
    """Preferensi sumber holder: ``gmgn`` / ``helius`` / ``auto``.

    Dibaca dari config.json ``holder_source`` lalu env ``HOLDER_SOURCE``.
    ``auto`` = Helius dulu untuk watchlist, fallback GMGN. Nilai lama
    ``solscan`` (sudah dilepas) dianggap tidak valid → jatuh ke ``auto``.
    """
    value = str(default or "auto").strip().lower()
    try:
        cfg = str(_config_file().get("holder_source") or "").strip().lower()
        if cfg:
            value = cfg
    except Exception:
        pass
    env_value = str(os.environ.get("HOLDER_SOURCE") or "").strip().lower()
    if env_value:
        value = env_value
    if value not in ("gmgn", "helius", "auto"):
        value = "auto"
    return value


def _reset_helius_rotation() -> None:
    """Reset round-robin state (primarily useful for deterministic tests)."""
    global _helius_rotation_index
    with _helius_rotation_lock:
        _helius_rotation_index = 0


def _helius_candidates(helius_keys=None, max_attempts=None) -> list[str]:
    """Build a round-robin request order, including every configured key."""
    # Resolved tuples/lists are passed through every paginated flow; avoid
    # re-reading config.json and Streamlit secrets on every page.
    if isinstance(helius_keys, (list, tuple)):
        keys = merge_helius_keys(helius_keys)
    else:
        keys = get_helius_keys(primary=helius_keys)
    if not keys:
        raise RuntimeError("Helius API key missing")
    global _helius_rotation_index
    with _helius_rotation_lock:
        start = _helius_rotation_index % len(keys)
        _helius_rotation_index = (_helius_rotation_index + 1) % len(keys)
    attempts = max(len(keys), int(max_attempts or 0))
    return [keys[(start + offset) % len(keys)] for offset in range(attempts)]


def _transient_rpc_error(error) -> bool:
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    message = str(error.get("message") or error).lower()
    return (code in (408, 425, 429, -32429) or
            "rate limit" in message or "too many requests" in message or
            "temporarily unavailable" in message or
            "service unavailable" in message or "internal error" in message)


def _response_error(response, label: str):
    # Do not surface response.url: it contains the API key query parameter.
    return RuntimeError(f"{label} HTTP {response.status_code}")


def helius_rpc_request(payload: dict, helius_keys=None, *, timeout: int = 60,
                       max_attempts=None) -> dict:
    """POST Helius JSON-RPC, rotating on HTTP 429/5xx and network errors."""
    last_error = None
    for key in _helius_candidates(helius_keys, max_attempts):
        try:
            response = requests.post(HELIUS_RPC_URL, params={"api-key": key},
                                     json=payload, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_error = _response_error(response, "Helius RPC")
            continue
        response.raise_for_status()
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            last_error = exc
            continue
        error = data.get("error") if isinstance(data, dict) else None
        if error:
            err = RuntimeError(f"Helius RPC error: {error}")
            if _transient_rpc_error(error):
                last_error = err
                continue
            raise err
        return data
    if last_error:
        raise last_error
    raise RuntimeError("Helius RPC failed without a response")


def helius_rpc(method: str, params, helius_keys=None, *, timeout: int = 60,
               max_attempts=None):
    """Call a Helius JSON-RPC method through the shared rotating key pool."""
    data = helius_rpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        helius_keys, timeout=timeout, max_attempts=max_attempts)
    if "result" not in data:
        raise RuntimeError("Helius RPC response has no result")
    return data["result"]


def helius_api_get(url: str, *, params=None, headers=None, helius_keys=None,
                   timeout: int = 40, max_attempts=None):
    """GET a Helius Enhanced API endpoint with the same rotating key pool."""
    last_error = None
    for key in _helius_candidates(helius_keys, max_attempts):
        query = dict(params or {})
        query["api-key"] = key
        try:
            response = requests.get(url, params=query, headers=headers,
                                    timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_error = _response_error(response, "Helius API")
            continue
        response.raise_for_status()
        try:
            return response.json()
        except (TypeError, ValueError) as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("Helius API failed without a response")


def load_config() -> dict:
    cfg = {"helius_api_key": "", "helius_extra_keys": "",
           "custom_rpc": "", "dust_limit_usd": 5,
           "cluster_warn_pct": 5, "cluster_scan_top_n": 50, "exclude_lp": True}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f) or {})
    except Exception:
        pass
    try:  # Streamlit Cloud secrets menimpa config.json
        import streamlit as st
        for k in list(cfg.keys()):
            if k in st.secrets:
                cfg[k] = st.secrets[k]
    except Exception:
        pass
    return cfg


def _dex_liquidity_usd(pair: dict) -> float:
    """Return a finite, non-negative DexScreener liquidity value."""
    try:
        value = float((pair.get("liquidity") or {}).get("usd") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    if value != value or value < 0 or value == float("inf"):
        return 0.0
    return value


def _dex_token_address(pair: dict, side: str) -> str:
    """Return a token address from a DexScreener pair without coercing case.

    Solana base58 addresses are case-sensitive, so this intentionally only
    strips surrounding whitespace rather than lower-casing the address.
    """
    token = pair.get(side) if isinstance(pair, dict) else None
    if not isinstance(token, dict):
        return ""
    return str(token.get("address") or "").strip()


def matching_dexscreener_pairs(pairs, ca: str) -> list:
    """Return DexScreener pairs for exactly ``ca``, in safe display order.

    ``/latest/dex/tokens/<CA>`` can include a cross-pair where the requested
    CA is the *quote* token. Picking the raw highest-liquidity response and
    reading ``baseToken`` then labels the requested token as the other side
    of that pair (for example MEMIPEDE was shown as Cyclospora).

    Exact address matches are mandatory. Pairs where the queried token is
    ``baseToken`` come first, then quote-side fallbacks; each group is sorted
    by liquidity. This keeps DexScreener's normal price/FDV semantics while
    still allowing a quote-side-only token to be identified honestly.
    """
    target = str(ca or "").strip()
    if not target:
        return []

    base_matches, quote_matches = [], []
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        if _dex_token_address(pair, "baseToken") == target:
            base_matches.append(pair)
        elif _dex_token_address(pair, "quoteToken") == target:
            quote_matches.append(pair)

    def _sort_key(pair):
        return (-_dex_liquidity_usd(pair),
                str(pair.get("pairAddress") or ""))

    base_matches.sort(key=_sort_key)
    quote_matches.sort(key=_sort_key)
    return base_matches + quote_matches


def select_dexscreener_pair(pairs, ca: str) -> dict | None:
    """Choose the canonical DexScreener pair for ``ca``, or ``None``.

    See :func:`matching_dexscreener_pairs` for why this must not use raw
    ``pairs[0]``.
    """
    matches = matching_dexscreener_pairs(pairs, ca)
    return matches[0] if matches else None


def dexscreener_pair_token(pair: dict, ca: str) -> dict:
    """Return metadata for ``ca`` from either side of a matched pair.

    Returning the queried side rather than unconditionally ``baseToken``
    prevents a quote-side fallback from ever borrowing another token's name
    or symbol.
    """
    target = str(ca or "").strip()
    if not target or not isinstance(pair, dict):
        return {}
    for side in ("baseToken", "quoteToken"):
        if _dex_token_address(pair, side) == target:
            token = pair.get(side)
            return dict(token) if isinstance(token, dict) else {}
    return {}


def get_market(ca: str) -> dict:
    """DexScreener market data for exactly one token contract address.

    The endpoint can return cross-pairs where ``ca`` is the quote token.
    Filter and order those responses before reading metadata so a liquid
    unrelated base token cannot replace the requested token in the UI.
    """
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                     timeout=20)
    raw_pairs = (r.json() or {}).get("pairs") or []
    pairs = matching_dexscreener_pairs(raw_pairs, ca)
    if not pairs:
        return {}
    pair = pairs[0]
    token = dexscreener_pair_token(pair, ca)
    return {
        "name": token.get("name", "?"),
        "symbol": token.get("symbol", "?"),
        "price_usd": float(pair.get("priceUsd") or 0),
        "marketcap": float(pair.get("marketCap") or pair.get("fdv") or 0),
        "liquidity_usd": _dex_liquidity_usd(pair),
        "dex": pair.get("dexId", "?"),
        "pair_addresses": [p.get("pairAddress") for p in pairs
                           if p.get("pairAddress")],
        "url": pair.get("url", ""),
        "image": ((pair.get("info") or {}).get("imageUrl") or ""),
        "txns": pair.get("txns") or {},
        "volume": pair.get("volume") or {},
        "price_change": pair.get("priceChange") or {},
        "pair_created_at": pair.get("pairCreatedAt"),
        "pairs_detail": [{
            "dex": p.get("dexId", "?"),
            "pair": p.get("pairAddress"),
            "liq": _dex_liquidity_usd(p),
            "url": p.get("url", ""),
            "quote": (p.get("quoteToken") or {}).get("symbol", "?"),
        } for p in pairs],
    }


GECKOTERMINAL_OHLCV_URL = ("https://api.geckoterminal.com/api/v2/networks/"
                           "solana/pools/{pair}/ohlcv/hour")
GECKOTERMINAL_MAX_LIMIT = 1000
# 1e11 detik = tahun 5138: di atas itu timestamp pasti milidetik.
MILLISECOND_TS_THRESHOLD = 100_000_000_000


def _ohlcv_number(value) -> float | None:
    """Return a finite float for one OHLCV cell, or ``None`` when unusable.

    GeckoTerminal emits ``null`` cells for hours without trade, so every cell
    is validated before it can poison a daily aggregate or a stddev.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_hourly_candles(values) -> list[dict]:
    """Normalize a GeckoTerminal ``ohlcv_list`` payload into hourly candles.

    Output rows are ``{ts, open, high, low, close, volume_usd}`` sorted by
    timestamp ascending. A row is kept when it has a usable timestamp and a
    finite ``close``; ``null`` open/high/low (hours without trade) fall back to
    that close and missing volume falls back to zero, so a quiet hour still
    counts as coverage instead of punching a hole in the series. Rows without a
    usable close are dropped, and a repeated timestamp keeps the last
    occurrence so hourly volume can never be counted twice.
    """
    rows: dict[int, dict] = {}
    for value in values or []:
        if not isinstance(value, (list, tuple)) or len(value) < 6:
            continue
        ts = _ohlcv_number(value[0])
        close = _ohlcv_number(value[4])
        if ts is None or ts <= 0 or close is None:
            continue
        if ts > MILLISECOND_TS_THRESHOLD:
            # GeckoTerminal mengirim detik Unix; kalau suatu saat satuannya
            # berganti ke milidetik, setiap jam akan tampak sebagai "hari"
            # sendiri (tahun ~57.000) dan agregasi harian hening-heningan
            # menghasilkan nol baris. Dinormalisasi di satu tempat.
            ts = ts / 1000.0
        opening = _ohlcv_number(value[1])
        high = _ohlcv_number(value[2])
        low = _ohlcv_number(value[3])
        volume = _ohlcv_number(value[5]) or 0.0
        rows[int(ts)] = {
            "ts": int(ts),
            "open": close if opening is None else opening,
            "high": max(close, high if high is not None else close),
            "low": min(close, low if low is not None else close),
            "close": close,
            "volume_usd": max(0.0, volume),
        }
    return [rows[ts] for ts in sorted(rows)]


def get_hourly_candles(pair_address: str, limit_hours: int = 168, *,
                       timeout: int = 25) -> list[dict]:
    """Fetch hourly GeckoTerminal candles for one pool (oldest -> newest).

    ``limit_hours`` defaults to 7 x 24 so one request can serve both a
    four-hour volume window and a seven-day volume average. Transport or
    parse failures return ``[]``: market data must never raise into a scan.
    """
    pair = str(pair_address or "").strip()
    if not pair:
        return []
    try:
        limit = max(1, min(GECKOTERMINAL_MAX_LIMIT, int(limit_hours)))
        response = requests.get(
            GECKOTERMINAL_OHLCV_URL.format(pair=pair),
            params={"aggregate": 1, "limit": limit},
            headers={"accept": "application/json"}, timeout=timeout)
        response.raise_for_status()
        payload = (response.json() or {}).get("data") or {}
        values = ((payload.get("attributes") or {}).get("ohlcv_list")) or []
    except Exception:  # noqa: BLE001 - pasar tidak boleh menggagalkan scan
        return []
    return normalize_hourly_candles(values)


def aggregate_daily_candles(hourly, limit_days: int = 7) -> list[dict]:
    """Aggregate hourly candles into UTC calendar days (pure, no HTTP).

    The UTC day boundary matches the crypto-market day used by Helius and
    Solscan; ``datetime.date()`` carries month/year edges itself, so no manual
    day arithmetic is involved (verified untuk 31 Des → 1 Jan dan 28 → 29 Feb
    tahun kabisat di ``tests/test_core_candles.py``). ``hours`` reports coverage
    so a partial day stays recognizable — **hari UTC yang masih berjalan ikut
    ter-return**, jadi pemanggil yang butuh hari lengkap harus menyaringnya
    (lihat ``cvd_daily.completed_dates``). ``limit_days <= 0`` returns ``[]``
    instead of the whole history (``[-0:]`` would otherwise silently return
    everything).
    """
    try:
        days = int(limit_days)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return []
    grouped: dict[str, dict] = {}
    for candle in hourly or []:
        if not isinstance(candle, dict):
            continue
        ts = _ohlcv_number(candle.get("ts"))
        close = _ohlcv_number(candle.get("close"))
        if ts is None or ts <= 0 or close is None:
            continue
        high = _ohlcv_number(candle.get("high"))
        low = _ohlcv_number(candle.get("low"))
        opening = _ohlcv_number(candle.get("open"))
        volume = _ohlcv_number(candle.get("volume_usd")) or 0.0
        date = datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()
        day = grouped.get(date)
        if day is None:
            grouped[date] = {
                "date": date,
                "open": close if opening is None else opening,
                "high": close if high is None else high,
                "low": close if low is None else low,
                "close": close,
                "volume_usd": max(0.0, volume),
                "hours": 1,
            }
            continue
        day["high"] = max(day["high"], close if high is None else high)
        day["low"] = min(day["low"], close if low is None else low)
        day["close"] = close
        day["volume_usd"] += max(0.0, volume)
        day["hours"] += 1
    ordered = sorted(grouped.values(), key=lambda item: item["date"])
    return ordered[-days:]


def get_daily_candles(pair_address: str, limit_days: int = 7) -> list[dict]:
    """Fetch hourly GeckoTerminal candles and aggregate calendar days in UTC.

    Hourly candles are aggregated into calendar days using the UTC boundary,
    which matches the crypto-market day used by Helius and Solscan.
    """
    try:
        days = int(limit_days)
    except (TypeError, ValueError):
        return []
    if days <= 0:
        return []
    hourly = get_hourly_candles(pair_address, limit_hours=days * 24 + 24)
    return aggregate_daily_candles(hourly, limit_days=days)
