# -*- coding: utf-8 -*-
"""Pengambil data untuk page **🌊 Sweep** (DexScreener, RugCheck, GMGN, GeckoTerminal).

Empat provider (lima endpoint), semuanya publik dan **tanpa API key**:

===========================  ===========================================================
Sumber                       Dipakai untuk
===========================  ===========================================================
DexScreener                  harga, liq, FDV/MC, volume, buys/sells, pool utama
RugCheck                     ``lpLockedPct``, authority, top holder → kriteria 2 & 3
GMGN ``token_stat``          bundler, bot degen, fresh, entrapment, top-10
GMGN ``tokens/top_buyers``   ``holding_rate`` + ringkasan ``statusNow``
GeckoTerminal OHLCV          candle hourly/5m + jendela cohort 48 jam pertama
===========================  ===========================================================

Semua hasil di-cache ke ``sweep_cache.json`` (TTL sukses 90 detik, gagal 120
detik) supaya rerun Streamlit — yang terjadi tiap interaksi — tidak menembak
pihak ketiga berulang kali. Cache ini **ephemeral** (di-``.gitignore``), bukan
sumber kebenaran.

GMGN dipanggil dengan ``curl_cffi`` TLS-impersonation lebih dulu (pola yang sama
dengan :mod:`gmgn_bundler`), lalu jatuh ke ``requests``.
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from urllib.parse import quote

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"
RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
GMGN_STAT_URL = "https://gmgn.ai/api/v1/token_stat/sol/{mint}"
GMGN_TOP_BUYERS_URL = "https://gmgn.ai/api/v1/tokens/top_buyers/sol/{mint}"
GECKO_OHLCV_URL = ("https://api.geckoterminal.com/api/v2/networks/solana/pools/"
                   "{pool}/ohlcv/{frame}")
COHORT_WINDOW_HOURS = 48

CACHE_PATH = Path(__file__).resolve().parent / "sweep_cache.json"
CACHE_TTL_OK = 90
CACHE_TTL_FAIL = 120
CACHE_MAX_ENTRIES = 400
REQUEST_TIMEOUT = 12

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/152.0.0.0 Safari/537.36"),
}
_GMGN_HEADERS = dict(_HEADERS, origin="https://gmgn.ai",
                     referer="https://gmgn.ai/sol/trending")
_IMPERSONATIONS = ("chrome", "chrome131", "safari17_0")
_lock = threading.Lock()


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp_seconds(value):
    """DexScreener pairCreatedAt may be milliseconds; Gecko uses seconds."""
    timestamp = _num(value)
    if timestamp is None or timestamp <= 0:
        return None
    return timestamp / 1000.0 if timestamp > 1e12 else timestamp


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def _cache_load() -> dict:
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001 - cache rusak = mulai dari kosong
        return {}


def _cache_save(cache: dict) -> None:
    try:
        if len(cache) > CACHE_MAX_ENTRIES:
            ordered = sorted(cache.items(),
                             key=lambda kv: (kv[1] or {}).get("at") or 0,
                             reverse=True)
            cache = dict(ordered[:CACHE_MAX_ENTRIES])
        CACHE_PATH.write_text(json.dumps(cache, separators=(",", ":")),
                              encoding="utf-8")
    except Exception:  # noqa: BLE001 - cache hanya optimisasi
        pass


def _cache_get(key: str):
    with _lock:
        entry = (_cache_load() or {}).get(key)
    if not isinstance(entry, dict):
        return None
    age = time.time() - (_num(entry.get("at")) or 0)
    ttl = CACHE_TTL_OK if entry.get("ok") else CACHE_TTL_FAIL
    return entry.get("data") if age <= ttl else None


def _cache_put(key: str, data, *, ok: bool) -> None:
    with _lock:
        cache = _cache_load()
        cache[key] = {"at": time.time(), "ok": bool(ok), "data": data}
        _cache_save(cache)


def reset_cache() -> None:
    """Buang seluruh cache (dipakai tombol "Paksa refresh" di UI)."""
    with _lock:
        _cache_save({})


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _get_json(url: str, *, timeout: int = REQUEST_TIMEOUT,
              headers: dict | None = None) -> object:
    """GET JSON dengan TLS-impersonation, lalu fallback ``requests``."""
    head = headers or _HEADERS
    last = ""
    try:
        from curl_cffi import requests as client
        for identity in _IMPERSONATIONS:
            try:
                response = client.get(url, headers=head, timeout=timeout,
                                      impersonate=identity)
                if response.status_code == 200:
                    return response.json()
                last = f"HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001
                last = str(exc)[:160]
    except ImportError:
        pass
    try:
        import requests
        response = requests.get(url, headers=head, timeout=timeout)
        if response.status_code == 200:
            return response.json()
        last = f"HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        last = str(exc)[:160]
    raise RuntimeError(f"GET gagal: {last or 'tanpa respons'}")


# ---------------------------------------------------------------------------
# DexScreener — harga / liq / FDV / volume / buys-sells
# ---------------------------------------------------------------------------
def _pick_pair(pairs: list) -> dict | None:
    """Pilih pool terbesar (liquidity USD tertinggi) dari daftar pasangan."""
    best, best_liq = None, -1.0
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        liq = _num((pair.get("liquidity") or {}).get("usd")) or 0.0
        if liq > best_liq:
            best, best_liq = pair, liq
    return best


def dex_snapshot(mint: str, *, use_cache: bool = True) -> dict:
    """Snapshot DexScreener untuk satu mint (pool terbesar)."""
    mint = str(mint or "").strip()
    key = f"dex:{mint}"
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    result = {"ok": False, "mint": mint, "error": "", "source": "dexscreener"}
    try:
        payload = _get_json(DEX_URL.format(mint=quote(mint, safe="")))
        pair = _pick_pair((payload or {}).get("pairs") if isinstance(payload, dict) else None)
        if not pair:
            raise RuntimeError("tidak ada pasangan terdaftar")
        liq = _num((pair.get("liquidity") or {}).get("usd"))
        fdv = _num(pair.get("fdv")) or _num(pair.get("marketCap"))
        price = _num(pair.get("priceUsd"))
        txns = pair.get("txns") or {}
        volume = pair.get("volume") or {}
        change = pair.get("priceChange") or {}

        def _txn(frame, side):
            return _num(((txns.get(frame) or {}).get(side)))

        result.update({
            "ok": True,
            "name": ((pair.get("baseToken") or {}).get("name") or "")[:60],
            "symbol": ((pair.get("baseToken") or {}).get("symbol") or "")[:24],
            "pair_address": pair.get("pairAddress") or "",
            "dex_id": pair.get("dexId") or "",
            "labels": list(pair.get("labels") or []),
            "price_usd": price,
            "liq_usd": liq,
            "fdv_usd": fdv,
            "market_cap_usd": _num(pair.get("marketCap")),
            "vol_24h": _num(volume.get("h24")),
            "vol_6h": _num(volume.get("h6")),
            "vol_1h": _num(volume.get("h1")),
            "vol_5m": _num(volume.get("m5")),
            "buys_24h": _txn("h24", "buys"),
            "sells_24h": _txn("h24", "sells"),
            "buys_1h": _txn("h1", "buys"),
            "sells_1h": _txn("h1", "sells"),
            "buys_5m": _txn("m5", "buys"),
            "sells_5m": _txn("m5", "sells"),
            "change_5m": _num(change.get("m5")),
            "change_1h": _num(change.get("h1")),
            "change_24h": _num(change.get("h24")),
            "pair_created_at": _num(pair.get("pairCreatedAt")),
            "url": pair.get("url") or "",
        })
        if liq and fdv and fdv > 0:
            result["liq_mc"] = liq / fdv
    except Exception as exc:  # noqa: BLE001 - satu mint gagal ≠ scan gagal
        result["error"] = str(exc)[:160]
    if use_cache:
        _cache_put(key, result, ok=result.get("ok"))
    return result


# ---------------------------------------------------------------------------
# RugCheck — LP locked / authority / top holder
# ---------------------------------------------------------------------------
def _pool_owners(report: dict) -> set:
    owners = set()
    for market in (report.get("markets") or []):
        if not isinstance(market, dict):
            continue
        for field in ("pubkey", "liquidityA", "liquidityB"):
            value = market.get(field)
            if isinstance(value, str) and value:
                owners.add(value)
    return owners


def rugcheck_snapshot(mint: str, *, use_cache: bool = True) -> dict:
    """Snapshot RugCheck: LP locked, authority, dan holder **tanpa pool AMM**.

    Rank #1 daftar holder RugCheck hampir selalu akun pool itu sendiri
    (COCKROACH: 8,26% supply, ``owner`` = ``markets[].pubkey``). Kalau pool ikut
    dihitung, kriteria "tiap holder < 3%" selalu gagal karena satu akun
    infrastruktur — jadi akun pool dibuang lebih dulu.
    """
    mint = str(mint or "").strip()
    key = f"rug:{mint}"
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    result = {"ok": False, "mint": mint, "error": "", "source": "rugcheck",
              "holder_pcts": [], "holders": []}
    try:
        report = _get_json(RUGCHECK_URL.format(mint=quote(mint, safe="")))
        if not isinstance(report, dict):
            raise RuntimeError("respons bukan objek JSON")
        token = report.get("token") or {}
        pools = _pool_owners(report)
        holders, pcts = [], []
        for holder in (report.get("topHolders") or []):
            if not isinstance(holder, dict):
                continue
            owner = holder.get("owner")
            account = holder.get("address")
            if owner in pools or account in pools:
                continue
            pct = _num(holder.get("pct"))
            holders.append({"address": owner or account or "", "pct": pct})
            if pct is not None:
                pcts.append(pct)
        top10 = sum(sorted(pcts, reverse=True)[:10]) if pcts else None
        result.update({
            "ok": True,
            "lp_locked_pct": _num(report.get("lpLockedPct")),
            "score_normalised": _num(report.get("score_normalised")),
            "risks": [str(r.get("name") or r.get("description") or r)[:80]
                      for r in (report.get("risks") or [])][:4],
            "mint_authority": token.get("mintAuthority"),
            "freeze_authority": token.get("freezeAuthority"),
            "creator": report.get("creator") or "",
            "holder_pcts": pcts,
            "holders": holders[:20],
            # Persen (0-100) — kontrak skrining; lihat criterion_float_spread.
        "top10_holder_pct": top10,
            "pool_count": len(report.get("markets") or []),
        })
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[:160]
    if use_cache:
        _cache_put(key, result, ok=result.get("ok"))
    return result


# ---------------------------------------------------------------------------
# GMGN token_stat — bundler / bot degen / entrapment / top-10
# ---------------------------------------------------------------------------
def _rate(value):
    number = _num(value)
    if number is None or number < 0 or number > 1:
        return None
    return number


def gmgn_stat(mint: str, *, use_cache: bool = True) -> dict:
    """Statistik per-token GMGN (fraksi 0-1)."""
    mint = str(mint or "").strip()
    key = f"gmgn:{mint}"
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    result = {"ok": False, "mint": mint, "error": "", "source": "gmgn_token_stat"}
    try:
        payload = _get_json(GMGN_STAT_URL.format(mint=quote(mint, safe="")),
                            headers=_GMGN_HEADERS)
        data = payload
        for _ in range(3):
            if not isinstance(data, dict):
                data = {}
                break
            if "holder_count" in data or "top_bundler_trader_percentage" in data:
                break
            data = data.get("data") if isinstance(data.get("data"), dict) else {}
        if not isinstance(data, dict) or not data:
            raise RuntimeError("field statistik tidak ditemukan")
        bundler_rate = _rate(data.get("top_bundler_trader_percentage"))
        result.update({
            "ok": True,
            "holder_count": _num(data.get("holder_count")),
            "top_bundler_trader_percentage": bundler_rate,
            "bundler_rate": bundler_rate,
            "entrapment_rate": _rate(data.get("top_entrapment_trader_percentage")),
            "bot_degen_rate": _rate(data.get("bot_degen_rate")),
            "bot_degen_count": _num(data.get("bot_degen_count")),
            "fresh_wallet_rate": _rate(data.get("fresh_wallet_rate")),
            "top10_holder_rate": _rate(data.get("top_10_holder_rate")),
            "dev_team_hold_rate": _rate(data.get("dev_team_hold_rate")),
            "creator_hold_rate": _rate(data.get("creator_hold_rate")),
            "sniper_rate": _rate(data.get("top70_sniper_hold_rate")),
            "creator_created_count": _num(data.get("creator_created_count")),
        })
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[:160]
    if use_cache:
        _cache_put(key, result, ok=result.get("ok"))
    return result


# ---------------------------------------------------------------------------
# GMGN top_buyers — holding_rate and current holder status summary
# ---------------------------------------------------------------------------
def _status_number(value):
    """Read a count/rate from a scalar or a small status summary object."""
    if isinstance(value, dict):
        for key in ("count", "total", "value", "rate", "num"):
            number = _num(value.get(key))
            if number is not None:
                return number
        return None
    if isinstance(value, (list, tuple)):
        return float(len(value))
    return _num(value)


def gmgn_top_buyers(mint: str, *, use_cache: bool = True) -> dict:
    """Fetch GMGN holder ``holding_rate`` and ``statusNow`` (same TTL as stats).

    This endpoint is optional enrichment: errors become an empty metrics dict
    with ``ok: False`` and never interrupt a scan.
    """
    mint = str(mint or "").strip()
    key = f"gmgn_top_buyers:{mint}"
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    result = {"ok": False, "mint": mint, "holding_rate": None,
              "status_now": {}, "error": "", "source": "gmgn_top_buyers"}
    try:
        payload = _get_json(
            GMGN_TOP_BUYERS_URL.format(mint=quote(mint, safe="")),
            headers=_GMGN_HEADERS)
        current = payload
        for _ in range(4):
            if not isinstance(current, dict):
                current = {}
                break
            if isinstance(current.get("holders"), dict):
                break
            nested = current.get("data")
            if isinstance(nested, dict):
                current = nested
            else:
                break
        holders = current.get("holders") if isinstance(current, dict) else None
        holders = holders if isinstance(holders, dict) else {}
        status = (holders.get("statusNow") or holders.get("status_now")
                  or current.get("statusNow") or current.get("status_now")
                  or {})
        if not isinstance(status, dict):
            raise RuntimeError("field data.holders.statusNow tidak ditemukan")
        rate = status.get("holding_rate")
        if rate is None:
            rate = status.get("holdingRate")
        holding_rate = _rate(rate)
        aliases = {
            "hold": ("hold", "holding", "hold_count", "holding_count"),
            "sold_part": ("sold_part", "soldPart", "sold_part_count"),
            "sold": ("sold", "sold_count"),
        }
        summary = {}
        for output_key, keys in aliases.items():
            value = next((status[name] for name in keys if name in status), None)
            summary[output_key] = _status_number(value)
        if holding_rate is None and not any(value is not None
                                            for value in summary.values()):
            raise RuntimeError("field holding_rate/statusNow tidak ditemukan")
        result.update({"ok": True, "holding_rate": holding_rate,
                       "status_now": summary})
    except Exception as exc:  # noqa: BLE001 - GMGN enrichment is optional
        result["error"] = str(exc)[:160]
    if use_cache:
        _cache_put(key, result, ok=result.get("ok"))
    return result


# ---------------------------------------------------------------------------
# GeckoTerminal — candle
# ---------------------------------------------------------------------------
_FRAMES = {
    "hour": ("hour", 1),
    "min5": ("minute", 5),
    "min1": ("minute", 1),
}


def ohlcv(pool: str, frame: str = "hour", *, limit: int = 200,
          before: int | None = None, use_cache: bool = True) -> list:
    """Candle ``[[ts, o, h, l, c, v], …]`` menaik dari GeckoTerminal."""
    pool = str(pool or "").strip()
    if not pool:
        return []
    name, aggregate = _FRAMES.get(frame, _FRAMES["hour"])
    key = f"ohlcv:{pool}:{frame}:{limit}:{before or ''}"
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    rows: list = []
    try:
        url = (GECKO_OHLCV_URL.format(pool=quote(pool, safe=""), frame=name)
               + f"?aggregate={aggregate}&limit={int(limit)}&currency=usd"
                 "&token=base")
        if before:
            url += f"&before_timestamp={int(before)}"
        payload = _get_json(url)
        raw = (((payload or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list")
        for row in raw or []:
            if isinstance(row, (list, tuple)) and len(row) >= 6:
                rows.append([int(row[0])] + [_num(v) for v in row[1:6]])
        rows.sort(key=lambda r: r[0])
    except Exception:  # noqa: BLE001 - candle opsional untuk skrining
        rows = []
    if use_cache and rows:
        _cache_put(key, rows, ok=True)
    return rows


def cohort_ohlcv(pool: str, pair_created_at, *, use_cache: bool = True) -> list:
    """Fetch hourly candles covering the pool's first 48 hours, not its latest."""
    created = _timestamp_seconds(pair_created_at)
    if not pool or created is None:
        return []
    window_end = int(math.ceil(created + COHORT_WINDOW_HOURS * 3600))
    # An overlapping first-hour candle plus 48 following hours can require 49
    # bars; request 50 to leave room for Gecko's hour-boundary alignment.
    rows = ohlcv(pool, "hour", limit=50, before=window_end,
                 use_cache=use_cache)
    return [row for row in rows
            if row[0] + 3600 > created
            and row[0] < created + COHORT_WINDOW_HOURS * 3600]


# ---------------------------------------------------------------------------
# Gabungan
# ---------------------------------------------------------------------------
def collect_metrics(mint: str, *, use_cache: bool = True) -> dict:
    """Combine market/risk snapshots and GMGN stat/top-buyer fields per mint."""
    dex = dex_snapshot(mint, use_cache=use_cache)
    rug = rugcheck_snapshot(mint, use_cache=use_cache)
    stat = gmgn_stat(mint, use_cache=use_cache)
    buyers = gmgn_top_buyers(mint, use_cache=use_cache)
    top10 = rug.get("top10_holder_pct")
    if top10 is None and stat.get("top10_holder_rate") is not None:
        top10 = (stat["top10_holder_rate"] or 0) * 100.0
    return {
        "mint": mint,
        "ts": int(time.time()),
        "ok": bool(dex.get("ok")),
        "error": dex.get("error") or rug.get("error") or stat.get("error") or "",
        "symbol": dex.get("symbol") or "",
        "name": dex.get("name") or "",
        "price_usd": dex.get("price_usd"),
        "liq_usd": dex.get("liq_usd"),
        "fdv_usd": dex.get("fdv_usd"),
        "market_cap_usd": dex.get("market_cap_usd"),
        "liq_mc": dex.get("liq_mc"),
        "vol_24h": dex.get("vol_24h"),
        "vol24_usd": dex.get("vol_24h"),
        "vol_6h": dex.get("vol_6h"),
        "vol_1h": dex.get("vol_1h"),
        "buys_1h": dex.get("buys_1h"),
        "sells_1h": dex.get("sells_1h"),
        "change_1h": dex.get("change_1h"),
        "change_24h": dex.get("change_24h"),
        "pair_address": dex.get("pair_address") or "",
        "pair_created_at": _timestamp_seconds(dex.get("pair_created_at")),
        "dex_id": dex.get("dex_id") or "",
        "pool_count": rug.get("pool_count"),
        "lp_locked_pct": rug.get("lp_locked_pct"),
        "mint_authority": rug.get("mint_authority"),
        "freeze_authority": rug.get("freeze_authority"),
        "risks": rug.get("risks") or [],
        "holder_pcts": rug.get("holder_pcts") or [],
        # Persen (0-100) — kontrak skrining; lihat criterion_float_spread.
        "top10_holder_pct": top10,
        "holder_count": stat.get("holder_count"),
        "top_bundler_trader_percentage": stat.get("top_bundler_trader_percentage"),
        "bundler_rate": stat.get("bundler_rate"),
        "entrapment_rate": stat.get("entrapment_rate"),
        "bot_degen_rate": stat.get("bot_degen_rate"),
        "bot_degen_count": stat.get("bot_degen_count"),
        "fresh_wallet_rate": stat.get("fresh_wallet_rate"),
        "holding_rate": buyers.get("holding_rate"),
        "status_now": buyers.get("status_now") or {},
        "dev_team_hold_rate": stat.get("dev_team_hold_rate"),
        "sniper_rate": stat.get("sniper_rate"),
        "creator_created_count": stat.get("creator_created_count"),
        "sources": {"dex": bool(dex.get("ok")), "rugcheck": bool(rug.get("ok")),
                    "gmgn": bool(stat.get("ok")),
                    "gmgn_top_buyers": bool(buyers.get("ok"))},
    }
