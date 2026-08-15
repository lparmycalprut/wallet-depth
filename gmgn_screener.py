"""GMGN trending listing client without ranking or scoring."""
from __future__ import annotations

import json
import time
import uuid

DEVICE_ID = str(uuid.uuid4())
FP_DID = uuid.uuid4().hex
GMGN_ORIGIN = "https://gmgn.ai"
TRENDING_PATH = "/trs/api/v1/trending_rank"
VERSION_URL = GMGN_ORIGIN + "/version.json"
DEFAULT_BUILD = "20260728-2617-057cd43"
_build_cache = {"tag": "", "ts": 0.0}


def _build_tag(timeout=10):
    now = time.time()
    if _build_cache["tag"] and now - _build_cache["ts"] < 3600:
        return _build_cache["tag"]
    tag = DEFAULT_BUILD
    try:
        from curl_cffi import requests as client
        response = client.get(VERSION_URL, impersonate="chrome",
                              timeout=timeout)
        raw = (response.json() or {}).get("buildTag") \
            if response.status_code == 200 else ""
        parts = [part for part in str(raw or "").split("-")
                 if part and part != "master"]
        if len(parts) >= 3:
            tag = "-".join(parts[:3])
    except Exception:
        pass
    _build_cache.update(tag=tag, ts=now)
    return tag


def _trending_url():
    build = _build_tag()
    return (f"{GMGN_ORIGIN}{TRENDING_PATH}?device_id={DEVICE_ID}"
            f"&fp_did={FP_DID}&client_id=gmgn_web_{build}"
            f"&from_app=gmgn&app_ver={build}&tz_name=Asia%2FJakarta"
            "&tz_offset=25200&app_lang=en-US&os=web&worker=0")


HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "origin": GMGN_ORIGIN,
    "referer": GMGN_ORIGIN + "/trend?chain=sol",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 Chrome/150 Safari/537.36"),
}


def _body(interval="24h", degen=False):
    filters = {
        "filters": ["migrated", "not_wash_trading", "renounced", "frozen"],
        "min_created": "2880m",
        "max_created": "86400m" if degen else "43200m",
        "min_holder_count": 1000,
        "min_volume_24h": (1000 if interval == "1h" else 10000)
        if degen else (10000 if interval == "1h" else 100000),
    }
    if degen:
        filters.update(max_marketcap=250000, min_gas_fee=30)
    else:
        filters.update(min_marketcap=100000, min_liquidity=30000,
                       min_gas_fee=20, max_insider_ratio=0.15,
                       max_bundler_rate=0.15)
    return {"meta": {}, "params": [{"chain": "sol", "interval": interval,
                                      "filter": filters}]}


def fetch_trending(timeout=25, debug=False, filter_body=None):
    """Return raw tokens from GMGN's public listing endpoint."""
    try:
        from curl_cffi import requests as client
    except ImportError:
        return []
    last_error = ""
    for identity in ("chrome", "chrome131", "safari17_0"):
        try:
            response = client.post(
                _trending_url(), impersonate=identity, timeout=timeout,
                headers=HEADERS, data=json.dumps(filter_body or _body()))
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
                continue
            payload = response.json() or {}
            blocks = payload.get("data") or []
            if isinstance(blocks, dict):
                blocks = [blocks]
            tokens = []
            for block in blocks:
                tokens.extend((block or {}).get("tokens") or [])
            if tokens:
                return tokens
            last_error = "respons kosong"
        except Exception as exc:
            last_error = str(exc)
    if debug and last_error:
        print(f"GMGN listing gagal: {last_error}")
    return []


def _number(token, *keys):
    for key in keys:
        try:
            value = float(token.get(key))
            return value
        except (TypeError, ValueError):
            continue
    return 0.0


def listing_row(token: dict) -> dict:
    """Normalize display fields only; no quality verdict is calculated."""
    opened = _number(token, "ot", "open_timestamp", "created_timestamp")
    age_days = max(0.0, (time.time() - opened) / 86400) if opened else None
    top10 = _number(token, "t10", "top_10_holder_rate")
    if 0 < top10 <= 1:
        top10 *= 100
    return {
        "ca": token.get("a") or token.get("address") or "",
        "symbol": token.get("s") or token.get("symbol") or "?",
        "name": token.get("nm") or token.get("name") or "",
        "price": _number(token, "p", "price"),
        "mc": _number(token, "mc", "market_cap", "usd_market_cap"),
        "liq": _number(token, "lq", "liquidity"),
        "volume": _number(token, "v", "volume", "volume_24h"),
        "holders": int(_number(token, "hd", "holder_count")),
        "top10_pct": round(top10, 2),
        "change_24h": _number(token, "pcp", "price_change_percent24h"),
        "change_1h": _number(token, "pcp1h", "price_change_percent1h"),
        "age_days": round(age_days, 1) if age_days is not None else None,
        "logo": token.get("l") or "",
    }


def _screen(filter_body) -> list[dict]:
    rows, seen = [], set()
    for token in fetch_trending(filter_body=filter_body):
        if not isinstance(token, dict):
            continue
        row = listing_row(token)
        if not row["ca"] or row["ca"] in seen:
            continue
        seen.add(row["ca"])
        rows.append(row)
    rows.sort(key=lambda item: item["volume"], reverse=True)
    return rows


def screen():
    return _screen(_body("24h", False))


def screen_trending_h1():
    return _screen(_body("1h", False))


def screen_hrhr():
    return _screen(_body("24h", True))


def screen_hrhr_h1():
    return _screen(_body("1h", True))
