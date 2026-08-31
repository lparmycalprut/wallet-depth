# -*- coding: utf-8 -*-
"""Holder token dari Solscan + Wallet Depth by Threshold.

Sumber holder alternatif untuk token watchlist ("khusus holder kita ambil
dari Solscan"). Meniru dua tampilan halaman Solscan ``#analytics_holder``:

1. **Wallet Depth by Threshold** — jumlah holder per bucket nilai USD:
   ``>$0-$10``, ``$10-$100``, ``$100-$1k``, ``$1k-$10k``, ``$10k-$100k``,
   ``$100k-$500k``, ``>$500k`` (semua akun, termasuk LP/pool, seperti
   yang ditampilkan Solscan).
2. **Holder Distribution by Tier** — 🦐 Shrimp / 🦀 Crab / 🐟 Fish /
   🐬 Dolphin / 🦈 Shark, dihitung hanya untuk **wallet murni** (akun
   LP/pool yang dikenal dikecualikan).

Endpoint yang dipakai (berurutan):

- **Pro API v2.0** ``/v2.0/token/holders`` bila ``SOLSCAN_API_KEY``
  tersedia (config.json / env / Streamlit secrets). Tiap baris sudah
  membawa ``value`` (USD) dan ``percentage`` dari Solscan.
- **Public API** ``/token/holders`` (tanpa key; deprecated tapi masih
  berfungsi). Nilai USD dihitung ``balance × harga`` dari market app.

Bila keduanya gagal/kosong, pemanggil (``analyze_token``) otomatis
fallback ke GMGN/Helius seperti sebelumnya.
"""
from __future__ import annotations

import time

import requests

SOLSCAN_PRO_URL = "https://pro-api.solscan.io/v2.0/token/holders"
SOLSCAN_PUBLIC_URL = "https://public-api.solscan.io/token/holders"

# Public API maksimal 100 per halaman; Pro API page_size maksimal 100.
PAGE_LIMIT = 100
MAX_PAGES = 60
_CACHE_TTL = 600
_CACHE: dict[str, dict] = {}

# --- Wallet Depth by Threshold (seperti halaman analytics Solscan) ----------
DEPTH_BUCKETS = (
    (">$0-$10", 0.0, 10.0),
    ("$10-$100", 10.0, 100.0),
    ("$100-$1k", 100.0, 1_000.0),
    ("$1k-$10k", 1_000.0, 10_000.0),
    ("$10k-$100k", 10_000.0, 100_000.0),
    ("$100k-$500k", 100_000.0, 500_000.0),
    (">$500k", 500_000.0, None),
)

# --- Holder Distribution by Tier (wallet murni) ------------------------------
TIERS = (
    ("🦐", "Shrimp", 0.0, 100.0),
    ("🦀", "Crab", 100.0, 1_000.0),
    ("🐟", "Fish", 1_000.0, 10_000.0),
    ("🐬", "Dolphin", 10_000.0, 100_000.0),
    ("🦈", "Shark", 100_000.0, None),
)

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://solscan.io",
    "referer": "https://solscan.io/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/150.0.0.0 Safari/537.36"),
}


def _float(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        return num if num == num else default  # NaN guard
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    return int(_float(value, float(default)))


def _http_get(url: str, params: dict, headers: dict | None = None,
              timeout: int = 20) -> dict:
    """GET JSON sederhana; raise RuntimeError bila gagal/non-200."""
    try:
        response = requests.get(url, params=params, headers=headers,
                                timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"Solscan GET gagal: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"Solscan HTTP {response.status_code}")
    payload = response.json() or {}
    if not isinstance(payload, dict):
        raise RuntimeError("Solscan response bukan objek JSON")
    return payload


def _empty_snapshot(*, api=None, error="") -> dict:
    return {
        "holders": [],
        "pages": 0,
        "truncated": False,
        "fetched": 0,
        "analyzed_at": int(time.time()),
        "source": "solscan",
        "api": api,
        "total_known": None,
        "error": error,
    }


def _normalize(owner: str, account: str, balance_ui: float,
               usd_value: float, amount_pct: float, *,
               pool_set: set) -> dict | None:
    """Satu holder Solscan -> bentuk yang sama dengan holder GMGN."""
    owner = str(owner or "").strip()
    if not owner:
        return None
    is_pool = owner.lower() in pool_set
    return {
        "address": owner,
        "account_address": str(account or "").strip(),
        "balance": balance_ui,
        "usd_value": usd_value,
        "amount_pct": amount_pct,          # fraksi 0-1
        "is_wallet": not is_pool,
        "is_new": False,
        "is_suspicious": False,
        "start_holding_at": 0,
        "last_active_at": 0,
        "netflow_usd": 0.0,
        "current_buy_amount": 0.0,
        "current_sell_amount": 0.0,
        "current_transfer_in": 0.0,
        "current_transfer_out": 0.0,
        "wallet_tag": "",
        "tags": ["pool"] if is_pool else [],
        "maker_token_tags": [],
    }


def _fetch_pro(ca: str, *, price_usd: float, max_wallets: int,
               api_key: str, pool_set: set, timeout: int,
               fallback_decimals: float | None) -> dict:
    """Paginasi Pro API v2.0 token/holders (butuh api_key)."""
    headers = {**_HEADERS, "token": api_key, "x-api-key": api_key}
    base = {"address": ca}
    holders: dict[str, dict] = {}
    pages = 0
    truncated = False
    total = None
    max_pct_seen = 0.0
    raw_rows: list[dict] = []

    while True:
        payload = _http_get(
            SOLSCAN_PRO_URL,
            {**base, "page": pages + 1, "page_size": PAGE_LIMIT},
            headers=headers, timeout=timeout)
        if payload.get("success") is False:
            raise RuntimeError("Solscan pro: success=false")
        total = _int(payload.get("total"), total or 0)
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            break
        pages += 1
        for row in rows:
            if isinstance(row, dict):
                raw_rows.append(row)
                max_pct_seen = max(max_pct_seen,
                                   _float(row.get("percentage")))
        if len(raw_rows) >= max_wallets or not rows:
            if len(raw_rows) >= max_wallets:
                truncated = True
            break
        if total and pages * PAGE_LIMIT >= total:
            break
        if pages >= MAX_PAGES:
            truncated = True
            break

    # Solscan memberi percentage dalam skala persen (0-100) — normalisasi
    # otomatis kalau ternyata semua nilai <= 1 (skala fraksi).
    pct_scale = 100.0 if max_pct_seen > 1.5 else 1.0
    for row in raw_rows:
        owner = str(row.get("owner") or "").strip()
        if not owner:
            continue
        dec = _float(row.get("decimals"),
                     fallback_decimals if fallback_decimals is not None else 6)
        balance_ui = _float(row.get("amount")) / (10.0 ** max(0.0, dec))
        usd_value = _float(row.get("value"))
        if usd_value <= 0 and price_usd > 0:
            usd_value = balance_ui * price_usd
        pct = _float(row.get("percentage")) / pct_scale
        if pct < 0:
            pct = 0.0
        holder = _normalize(owner, row.get("address"), balance_ui,
                            usd_value, pct, pool_set=pool_set)
        if holder and holder["address"] not in holders:
            holders[holder["address"]] = holder
        if len(holders) >= max_wallets:
            truncated = True
            break

    return {
        "holders": list(holders.values()),
        "pages": pages,
        "truncated": truncated,
        "fetched": len(holders),
        "analyzed_at": int(time.time()),
        "source": "solscan",
        "api": "pro",
        "total_known": total,
        "error": "",
    }


def _fetch_public(ca: str, *, price_usd: float, market_cap: float,
                  max_wallets: int, pool_set: set, timeout: int,
                  fallback_decimals: float | None) -> dict:
    """Paginasi Public API /token/holders (tanpa key)."""
    holders: dict[str, dict] = {}
    offset = 0
    pages = 0
    truncated = False
    total = None
    errors = []

    while True:
        payload = None
        last_error = None
        # Parameter historis public API: tokenAddress (kadang token).
        for param_name in ("tokenAddress", "token"):
            try:
                payload = _http_get(
                    SOLSCAN_PUBLIC_URL,
                    {param_name: ca, "limit": PAGE_LIMIT, "offset": offset},
                    headers=_HEADERS, timeout=timeout)
                break
            except RuntimeError as exc:
                last_error = str(exc)
                payload = None
        if payload is None:
            errors.append(f"public: {last_error or 'gagal'}")
            break
        data = payload.get("data")
        if not isinstance(data, list):
            break
        if payload.get("total") is not None:
            total = _int(payload.get("total"), total or 0)
        pages += 1
        added = 0
        for row in data:
            if not isinstance(row, dict):
                continue
            owner = str(row.get("owner") or "").strip()
            if not owner:
                continue
            dec = _float(row.get("decimals"),
                         fallback_decimals if fallback_decimals is not None
                         else 6)
            balance_ui = _float(row.get("amount")) / (10.0 ** max(0.0, dec))
            usd_value = balance_ui * price_usd
            pct = (usd_value / market_cap) if market_cap > 0 else 0.0
            holder = _normalize(owner, row.get("token_account"),
                                balance_ui, usd_value, pct, pool_set=pool_set)
            if holder and holder["address"] not in holders:
                holders[holder["address"]] = holder
                added += 1
        if len(holders) >= max_wallets:
            truncated = True
            break
        if added < len(data) or not data:
            break  # halaman kosong / tidak ada progres
        offset += len(data)
        if total and offset >= total:
            break
        if pages >= MAX_PAGES:
            truncated = True
            break
        time.sleep(0.15)  # public API rate limit ketat; tetap santun

    return {
        "holders": list(holders.values()),
        "pages": pages,
        "truncated": truncated,
        "fetched": len(holders),
        "analyzed_at": int(time.time()),
        "source": "solscan",
        "api": "public",
        "total_known": total,
        "error": "; ".join(e for e in errors if e),
    }


def fetch_solscan_holders(ca: str, *, price_usd: float = 0.0,
                          market_cap: float = 0.0,
                          decimals: float | None = None,
                          max_wallets: int | None = None,
                          api_key: str | None = None,
                          pool_addresses=None,
                          timeout: int = 20) -> dict:
    """Ambil daftar holder token dari Solscan (Pro → Public API).

    Return snapshot dengan ``source="solscan"`` dan ``api`` =
    ``"pro"``/``"public"``. Bila gagal/kosong, return snapshot kosong
    (pemanggil boleh fallback ke GMGN/Helius).

    ``pool_addresses``: alamat LP/pool (mis. dari DexScreener pairs) yang
    ditandai ``is_wallet=False`` supaya klasifikasi real/dust & tier tetap
    menghitung wallet murni saja.
    """
    ca = str(ca or "").strip()
    if not ca:
        return _empty_snapshot(error="ca kosong")
    max_wallets = int(max_wallets or 3000)
    cache_key = f"solscan:{ca}:{max_wallets}"
    cached = _CACHE.get(cache_key)
    if cached and time.time() - cached.get("analyzed_at", 0) < _CACHE_TTL:
        return dict(cached)

    pool_set = {str(p or "").strip().lower() for p in (pool_addresses or [])
                if p}
    errors = []

    if api_key:
        try:
            snapshot = _fetch_pro(
                ca, price_usd=price_usd, max_wallets=max_wallets,
                api_key=api_key, pool_set=pool_set, timeout=timeout,
                fallback_decimals=decimals)
            if snapshot.get("holders"):
                _CACHE[cache_key] = snapshot
                return snapshot
            errors.append(snapshot.get("error") or "pro kosong")
        except RuntimeError as exc:
            errors.append(f"pro: {exc}")

    try:
        snapshot = _fetch_public(
            ca, price_usd=price_usd, market_cap=market_cap,
            max_wallets=max_wallets, pool_set=pool_set, timeout=timeout,
            fallback_decimals=decimals)
        if snapshot.get("holders"):
            _CACHE[cache_key] = snapshot
            return snapshot
        errors.append(snapshot.get("error") or "public kosong")
    except RuntimeError as exc:
        errors.append(f"public: {exc}")

    result = _empty_snapshot(error="; ".join(errors))
    _CACHE[cache_key] = result
    return result


def wallet_depth(holders, market_cap: float = 0.0, *,
                 pool_addresses=None) -> dict:
    """Wallet Depth by Threshold + Holder Distribution by Tier.

    - ``buckets``: semua akun dengan nilai > $0 (termasuk LP/pool, sama
      seperti chart Solscan), per bucket nilai USD.
    - ``tiers``: hanya wallet murni (LP/pool dikecualikan), per tier.

    Setiap entri: ``{"label"/"tier"/"emoji", "min", "max", "count",
    "value_usd", "pct_mc"}`` — ``pct_mc`` = None bila marketcap 0.
    """
    pool_set = {str(p or "").strip().lower() for p in (pool_addresses or [])
                if p}
    all_rows = [h for h in (holders or [])
                if isinstance(h, dict) and _float(h.get("usd_value")) > 0]
    wallet_rows = [h for h in all_rows
                   if h.get("is_wallet")
                   and str(h.get("address") or "").lower() not in pool_set]
    mc = float(market_cap or 0)

    # Tiers: wallet murni saja, ambang mengikuti konvensi Solscan.
    tier_rows = []
    for emoji, name, lo, hi in TIERS:
        items = [h for h in wallet_rows
                 if _float(h.get("usd_value")) > lo
                 and (hi is None or _float(h.get("usd_value")) <= hi)]
        value = sum(_float(h.get("usd_value")) for h in items)
        tier_rows.append({
            "tier": name,
            "emoji": emoji,
            "min": lo,
            "max": hi,
            "count": len(items),
            "value_usd": round(value, 2),
            "pct_mc": (round(value / mc * 100.0, 4) if mc > 0 else None),
        })

    buckets = []
    for label, lo, hi in DEPTH_BUCKETS:
        items = [h for h in all_rows
                 if _float(h.get("usd_value")) > lo
                 and (hi is None or _float(h.get("usd_value")) <= hi)]
        value = sum(_float(h.get("usd_value")) for h in items)
        buckets.append({
            "label": label,
            "min": lo,
            "max": hi,
            "count": len(items),
            "value_usd": round(value, 2),
            "pct_mc": (round(value / mc * 100.0, 4) if mc > 0 else None),
        })

    return {
        "buckets": buckets,
        "tiers": tier_rows,
        "holders_all": len(all_rows),
        "holders_wallet": len(wallet_rows),
        "pool_excluded": len(all_rows) - len(wallet_rows),
        "market_cap": mc,
        "computed_at": int(time.time()),
    }
