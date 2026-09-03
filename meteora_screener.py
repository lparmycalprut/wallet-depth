# -*- coding: utf-8 -*-
"""Scan pool Meteora DLMM (24 jam + 1 jam) lalu analisa holder dust.

Endpoint: ``pool-discovery-api.datapi.meteora.ag/pools``
- 24h: DLMM, active_tvl >= 1000, fee_active_tvl_ratio >= 250
- 1h : DLMM, active_tvl >= 1000, fee_active_tvl_ratio >= 1

Pool 24 jam yang masih muncul di 1 jam **tetap ditampilkan**. Pool 1 jam
yang belum ada di 24 jam ikut digabung (sama seperti listing Trending).
Setelah fetch holder, pool dengan dust holder **≥ 1% marketcap (BAHAYA)**
disembunyikan; **≥ 0,5% MC** tetap tampil dengan badge **HATI-HATI**.
Baris yang di-⭐ masuk watchlist terpisah **Chart LP** di dashboard.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from holder_history import should_hide_dust

POOLS_URL = "https://pool-discovery-api.datapi.meteora.ag/pools"
PAGE_SIZE = 50
TVL_MIN = 1000.0
FEE_RATIO_24H = 250.0
FEE_RATIO_1H = 1.0

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
QUOTE_MINTS = frozenset((SOL_MINT, USDC_MINT, USDT_MINT))

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "origin": "https://www.meteora.ag",
    "referer": "https://www.meteora.ag/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/151.0.0.0 Safari/537.36"),
}


def _float(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        return num if num == num else default
    except (TypeError, ValueError):
        return default


def _http_get(url: str, params: dict, timeout: int = 25) -> dict:
    """GET JSON: curl_cffi (browser TLS) dulu, fallback requests."""
    try:
        from curl_cffi import requests as client
        for identity in ("chrome", "chrome131", "safari17_0"):
            try:
                response = client.get(
                    url, params=params, timeout=timeout,
                    impersonate=identity, headers=_HEADERS)
                if response.status_code == 200:
                    return response.json() or {}
            except Exception:
                continue
    except ImportError:
        pass
    except Exception:
        pass
    import requests
    response = requests.get(url, params=params, headers=_HEADERS,
                            timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"Meteora HTTP {response.status_code}")
    return response.json() or {}


def filter_by(pool_type: str = "dlmm", tvl_min: float = TVL_MIN,
              fee_ratio_min: float = FEE_RATIO_24H) -> str:
    """Query ``filter_by`` persis seperti UI Meteora (&&-join)."""
    return (f"pool_type={pool_type}"
            f"&&active_tvl>={int(tvl_min) if tvl_min == int(tvl_min) else tvl_min}"
            f"&&fee_active_tvl_ratio>={fee_ratio_min:g}")


def fetch_pools(*, timeframe: str = "24h",
                fee_ratio_min: float = FEE_RATIO_24H,
                page_size: int = PAGE_SIZE,
                tvl_min: float = TVL_MIN,
                timeout: int = 25) -> list[dict]:
    """Ambil halaman top pool Meteora. Gagal → raise."""
    params = {
        "page_size": max(1, min(int(page_size), 50)),
        "timeframe": str(timeframe or "24h"),
        "category": "top",
        "filter_by": filter_by(tvl_min=tvl_min, fee_ratio_min=fee_ratio_min),
    }
    payload = _http_get(POOLS_URL, params, timeout=timeout)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def base_token(pool: dict | None) -> dict:
    """Token non-quote (bukan SOL/USDC/USDT). Fallback token_x."""
    pool = pool or {}
    token_x = pool.get("token_x") if isinstance(pool.get("token_x"), dict) else {}
    token_y = pool.get("token_y") if isinstance(pool.get("token_y"), dict) else {}
    addr_x = str(token_x.get("address") or "").strip()
    addr_y = str(token_y.get("address") or "").strip()
    if addr_x and addr_x not in QUOTE_MINTS:
        return token_x
    if addr_y and addr_y not in QUOTE_MINTS:
        return token_y
    return token_x or token_y


def _row_from_pool(pool: dict, *, in_24h: bool, in_1h: bool) -> dict:
    token = base_token(pool)
    mint = str(token.get("address") or "").strip()
    return {
        "pool_address": str(pool.get("pool_address") or "").strip(),
        "pool_name": str(pool.get("name") or ""),
        "pool_type": str(pool.get("pool_type") or "dlmm"),
        "ca": mint,
        "symbol": str(token.get("symbol") or pool.get("name") or "?").upper(),
        "name": str(token.get("name") or ""),
        "mc": _float(token.get("market_cap") or token.get("fdv")),
        "price": _float(token.get("price")),
        "holders_reported": token.get("holders"),
        "tvl": _float(pool.get("tvl")),
        "active_tvl": _float(pool.get("active_tvl")),
        "fee_active_tvl_ratio": _float(pool.get("fee_active_tvl_ratio")),
        "volume": _float(pool.get("volume")),
        "fee_pct": _float(pool.get("fee_pct")),
        "in_24h": bool(in_24h),
        "in_1h": bool(in_1h),
        "analysis": None,
    }


def merge_pools(pools_24h, pools_1h) -> list[dict]:
    """24 jam dulu; yang juga di 1 jam ditandai ``in_1h`` (tetap tampil).

    Pool yang hanya lolos filter 1 jam ditambahkan di belakang.
    """
    by_addr: dict[str, dict] = {}
    order: list[str] = []
    for pool in pools_24h or []:
        row = _row_from_pool(pool, in_24h=True, in_1h=False)
        addr = row["pool_address"]
        if not addr or addr in by_addr:
            continue
        by_addr[addr] = row
        order.append(addr)
    seen_1h = set()
    for pool in pools_1h or []:
        row = _row_from_pool(pool, in_24h=False, in_1h=True)
        addr = row["pool_address"]
        if not addr:
            continue
        seen_1h.add(addr)
        if addr in by_addr:
            by_addr[addr]["in_1h"] = True
            continue
        by_addr[addr] = row
        order.append(addr)
    for addr in order:
        if addr in seen_1h:
            by_addr[addr]["in_1h"] = True
    return [by_addr[addr] for addr in order]


def fetch_listing(*, timeout: int = 25) -> tuple[list[dict], str]:
    """(rows, error). error kosong bila 24h atau 1h berhasil."""
    errors = []
    pools_24: list[dict] = []
    pools_1h: list[dict] = []
    try:
        pools_24 = fetch_pools(timeframe="24h", fee_ratio_min=FEE_RATIO_24H,
                               timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"24h: {exc}")
    try:
        pools_1h = fetch_pools(timeframe="1h", fee_ratio_min=FEE_RATIO_1H,
                               timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"1h: {exc}")
    rows = merge_pools(pools_24, pools_1h)
    return rows, " · ".join(errors)


def _mint_pools(rows: list[dict]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for row in rows:
        mint = str(row.get("ca") or "").strip()
        pool = str(row.get("pool_address") or "").strip()
        if mint:
            mapping.setdefault(mint, set())
            if pool:
                mapping[mint].add(pool)
    return mapping


def enrich_pools(rows: list[dict], *, max_wallets: int = 2000,
                 workers: int = 6, progress=None) -> list[dict]:
    """Fetch holder per mint unik, tempel ``analysis`` ke setiap baris pool."""
    if not rows:
        return rows
    from holder_analysis import analyze_token
    from holder_history import load_holder_history

    store = load_holder_history()
    mint_pools = _mint_pools(rows)
    mints = [mint for mint in mint_pools if mint]
    total = len(mints)
    workers = max(1, min(int(workers), 8))
    analyses: dict[str, dict | None] = {}

    def _job(mint: str):
        meta = ((store.get("tokens") or {}).get(mint) or {})
        cohort = meta.get("cohort") if isinstance(meta.get("cohort"), dict) else {}
        addrs = list((cohort.get("balances") or {}).keys())
        symbol = next((str(r.get("symbol") or "?") for r in rows
                       if r.get("ca") == mint), "?")
        mc = next((_float(r.get("mc")) for r in rows if r.get("ca") == mint), 0.0)
        price = next((_float(r.get("price")) for r in rows if r.get("ca") == mint),
                     0.0)
        try:
            return mint, analyze_token(
                mint, symbol, mc, max_wallets=max_wallets,
                fetch_market=True, price_usd=price, cohort_addrs=addrs,
                extra_pools=mint_pools.get(mint) or []), None
        except Exception as exc:  # noqa: BLE001
            return mint, None, str(exc)

    if mints:
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_job, mint): mint for mint in mints}
            for future in as_completed(futures):
                mint, analysis, _error = future.result()
                analyses[mint] = analysis
                done += 1
                if progress:
                    try:
                        progress(done, total, mint[:8])
                    except Exception:
                        pass
        try:
            from holder_history import ingest_many
            ok = {mint: item for mint, item in analyses.items()
                  if isinstance(item, dict)}
            if ok:
                ingest_many(ok)
        except Exception:
            pass

    out = []
    for row in rows:
        item = dict(row)
        analysis = analyses.get(item.get("ca"))
        item["analysis"] = analysis
        holders = (analysis or {}).get("holders") or {}
        item["dust_count"] = holders.get("dust_count")
        item["dust_pct_mc"] = holders.get("dust_pct_mc")
        item["real_count"] = holders.get("real_count")
        out.append(item)
    return out


def hide_dust_limit(rows: list[dict]) -> tuple[list[dict], int]:
    """Buang pool dust ≥ 1% MC. Return (kept, n_hidden)."""
    kept, hidden = [], 0
    for row in rows or []:
        pct = ((row.get("analysis") or {}).get("holders") or {}).get("dust_pct_mc")
        if pct is None:
            pct = row.get("dust_pct_mc")
        if should_hide_dust(pct):
            hidden += 1
            continue
        kept.append(row)
    return kept, hidden


def scan_meteora(*, max_wallets: int = 2000, workers: int = 6,
                 progress=None, timeout: int = 25) -> dict:
    """Listing + holder + filter dust ≥ 1% MC."""
    rows, error = fetch_listing(timeout=timeout)
    fetched = len(rows)
    if rows:
        rows = enrich_pools(rows, max_wallets=max_wallets, workers=workers,
                            progress=progress)
        rows, hidden = hide_dust_limit(rows)
    else:
        hidden = 0
    return {
        "rows": rows,
        "error": error,
        "fetched": fetched,
        "hidden_dust": hidden,
        "analyzed_at": int(time.time()),
    }
