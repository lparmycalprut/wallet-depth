# -*- coding: utf-8 -*-
"""Deteksi bundler token Solana dari statistik per-token GMGN.

GMGN exposes ``top_bundler_trader_percentage`` as a fraction (0-1) at
``/api/v1/token_stat/sol/<mint>``.  The value is the share of token supply
traded by wallets GMGN classifies as bundlers; it is not a count of Jito
bundles and must not be inferred when the field is absent.

Best Pool uses the sum of bundler and GMGN's entrapment/phishing trader rate
as its final risk gate. Results are cached briefly because the endpoint is
unofficial and one request is needed per mint.
"""
from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

TOKEN_STAT_URL = "https://gmgn.ai/api/v1/token_stat/sol/{mint}"
CACHE_PATH = Path(__file__).resolve().parent / "gmgn_bundler_cache.json"
CACHE_TTL_OK = 900
CACHE_TTL_FAIL = 120
CACHE_MAX_ENTRIES = 400
REQUEST_TIMEOUT = 10
WORKERS = 6

# Final gate requested for Best Pool: bundler + phishing may be at most 25%.
MAX_COMBINED_RATE = 0.25
WARN_COMBINED_RATE = 0.15
SAFE_COLOR = "#15803d"
WARN_COLOR = "#b45309"
RISK_COLOR = "#dc2626"

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "origin": "https://gmgn.ai",
    "referer": "https://gmgn.ai/sol/trending",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/152.0.0.0 Safari/537.36"),
}
_IMPERSONATIONS = ("chrome", "chrome131", "safari17_0")
_lock = threading.Lock()


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(value) -> float | None:
    """Normalize a GMGN fraction while rejecting impossible values."""
    result = _number(value)
    if result is None or result < 0 or result > 1:
        return None
    return result


def _cache_load() -> dict:
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cache_save(cache: dict) -> None:
    try:
        if len(cache) > CACHE_MAX_ENTRIES:
            ordered = sorted(cache.items(), key=lambda item: _number(
                (item[1] or {}).get("at")) or 0)
            cache = dict(ordered[-CACHE_MAX_ENTRIES:])
        tmp = CACHE_PATH.with_suffix(CACHE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_PATH)
    except OSError:
        pass


def _cached(mint: str) -> dict | None:
    entry = _cache_load().get(mint)
    if not isinstance(entry, dict):
        return None
    timestamp = _number(entry.get("at")) or 0
    ttl = CACHE_TTL_OK if entry.get("ok") else CACHE_TTL_FAIL
    if time.time() - timestamp > ttl:
        return None
    report = entry.get("report")
    if not isinstance(report, dict):
        return None
    # Invalidate cache schema from the bundler-only implementation.
    if "phishing_rate" not in report or "combined_rate" not in report:
        return None
    return dict(report)


def _get_json(url: str, *, timeout: int) -> object:
    last = ""
    try:
        from curl_cffi import requests as client
        for identity in _IMPERSONATIONS:
            try:
                response = client.get(url, headers=_HEADERS, timeout=timeout,
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
        response = requests.get(url, headers=_HEADERS, timeout=timeout)
        if response.status_code == 200:
            return response.json()
        last = f"HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        last = str(exc)[:160]
    raise RuntimeError(f"GMGN token_stat: {last or 'tanpa respons'}")


def _data_object(payload) -> dict:
    """Accept both a direct stats object and common API wrappers."""
    current = payload
    for _ in range(3):
        if not isinstance(current, dict):
            return {}
        if "top_bundler_trader_percentage" in current:
            return current
        nested = current.get("data")
        if isinstance(nested, dict):
            current = nested
            continue
        return current
    return current if isinstance(current, dict) else {}


def summarize(payload, *, mint: str = "") -> dict:
    """Build a stable bundler + phishing report from GMGN fractions."""
    data = _data_object(payload)
    bundler = _rate(data.get("top_bundler_trader_percentage"))
    phishing = _rate(data.get("top_entrapment_trader_percentage"))
    if bundler is None or phishing is None:
        missing = []
        if bundler is None:
            missing.append("bundler")
        if phishing is None:
            missing.append("phishing")
        return {"ok": False, "mint": mint, "bundler_rate": bundler,
                "phishing_rate": phishing, "combined_rate": None,
                "dev_rate": _rate(data.get("dev_team_hold_rate")),
                "sniper_rate": _rate(data.get("top70_sniper_hold_rate")),
                "error": f"field {' + '.join(missing)} tidak tersedia",
                "source": "gmgn"}
    combined = bundler + phishing
    if combined > MAX_COMBINED_RATE:
        verdict, color = "GAGAL", RISK_COLOR
    elif combined >= WARN_COMBINED_RATE:
        verdict, color = "WASPADA", WARN_COLOR
    else:
        verdict, color = "LOLOS", SAFE_COLOR
    return {
        "ok": True,
        "mint": mint,
        "bundler_rate": bundler,
        "phishing_rate": phishing,
        "combined_rate": combined,
        "dev_rate": _rate(data.get("dev_team_hold_rate")),
        "creator_rate": _rate(data.get("creator_hold_rate")),
        "sniper_rate": _rate(data.get("top70_sniper_hold_rate")),
        "fresh_wallet_rate": _rate(data.get("fresh_wallet_rate")),
        "verdict": verdict,
        "color": color,
        "source": "gmgn_token_stat",
        "error": "",
    }


def fetch_report(mint: str, *, timeout: int = REQUEST_TIMEOUT,
                 use_cache: bool = True) -> dict:
    mint = str(mint or "").strip()
    if not mint:
        return {"ok": False, "bundler_rate": None,
                "phishing_rate": None, "combined_rate": None,
                "error": "mint kosong", "source": "gmgn"}
    if use_cache:
        with _lock:
            cached = _cached(mint)
        if cached is not None:
            return cached
    try:
        payload = _get_json(TOKEN_STAT_URL.format(mint=quote(mint, safe="")),
                            timeout=max(1, int(timeout)))
        report = summarize(payload, mint=mint)
    except Exception as exc:  # noqa: BLE001 - optional enrichment
        report = {"ok": False, "mint": mint, "bundler_rate": None,
                  "phishing_rate": None, "combined_rate": None,
                  "error": str(exc)[:160], "source": "gmgn"}
    if use_cache:
        with _lock:
            cache = _cache_load()
            cache[mint] = {"at": int(time.time()), "ok": report.get("ok"),
                           "report": report}
            _cache_save(cache)
    return report


def attach_to_rows(rows, *, workers: int = WORKERS,
                   timeout: int = REQUEST_TIMEOUT,
                   use_cache: bool = True) -> list[dict]:
    """Attach ``row['bundler']`` concurrently; preserve rows and their order."""
    rows = list(rows or [])
    mints = list(dict.fromkeys(str(row.get("ca") or "").strip()
                              for row in rows if str(row.get("ca") or "").strip()))
    reports: dict[str, dict] = {}
    if mints:
        with ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(mints)))) as pool:
            futures = {pool.submit(fetch_report, mint, timeout=timeout,
                                   use_cache=use_cache): mint for mint in mints}
            for future in as_completed(futures):
                mint = futures[future]
                try:
                    reports[mint] = future.result()
                except Exception as exc:  # pragma: no cover - fetch catches
                    reports[mint] = {"ok": False, "mint": mint,
                                     "bundler_rate": None,
                                     "phishing_rate": None,
                                     "combined_rate": None,
                                     "error": str(exc)[:160], "source": "gmgn"}
    for row in rows:
        mint = str(row.get("ca") or "").strip()
        row["bundler"] = reports.get(mint, {
            "ok": False, "mint": mint, "bundler_rate": None,
            "phishing_rate": None, "combined_rate": None,
            "error": "mint kosong" if not mint else "tidak terbaca",
            "source": "gmgn"})
    return rows


def _pct(rate) -> str:
    number = _number(rate)
    return "—" if number is None or number < 0 else f"{number * 100:.1f}%"


def cell_parts(report: dict | None) -> tuple[str, str, str]:
    """Return ``(combined value, components, tooltip)`` for Best Pool."""
    item = report if isinstance(report, dict) else {}
    if not item.get("ok"):
        error = str(item.get("error") or "data GMGN tidak tersedia")
        return "—", "GMGN", f"Bundler + phishing tidak terukur: {error}"
    combined = _pct(item.get("combined_rate"))
    bundler = _pct(item.get("bundler_rate"))
    phishing = _pct(item.get("phishing_rate"))
    sub = f"B {bundler} · P {phishing}"
    extras = []
    if _rate(item.get("dev_rate")) is not None:
        extras.append(f"dev {_pct(item.get('dev_rate'))}")
    if _rate(item.get("sniper_rate")) is not None:
        extras.append(f"sniper {_pct(item.get('sniper_rate'))}")
    tip = (f"GMGN: bundler {bundler} + phishing/entrapment {phishing} = "
           f"{combined}. Filter terakhir: gabungan maksimal "
           f"{MAX_COMBINED_RATE * 100:g}% (tepat 25% lolos, di atasnya gagal). "
           "Angka ini statistik wallet GMGN, bukan bukti pasti manipulasi "
           "atau hitungan transaksi Jito.")
    if extras:
        tip += " · " + " · ".join(extras)
    return combined, sub, tip
