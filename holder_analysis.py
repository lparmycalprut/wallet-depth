# -*- coding: utf-8 -*-
"""Analisis holder (real vs dust) untuk Wallet Depth.

1. ``fetch_holders`` / ``classify_holders``
   Membaca daftar holder token. Sumber utama = **Helius DAS**
   (``fetch_holders_helius``, paginasi cursor `getTokenAccounts`);
   GMGN dipakai untuk listing Trending/Degen dan sebagai fallback darurat.
   Memisahkan **real holder > $10 value** dengan **dust holder (0 < value
   <= $10)**, dan menghitung berapa % total marketcap yang dipegang dust.

2. ``analyze_token``
   Holder snapshot + klasifikasi + mid-tier/kohort untuk satu token
   (dipakai watchlist, Scan Meteora, halaman Holder, dan cron).
"""
from __future__ import annotations

import time
from core import get_market, load_config

# --- Ambang default -----------------------------------------------------------
DUST_LIMIT_USD = 10.0          # "> $10 value" = real holder; sisanya dust
DEFAULT_MAX_WALLETS = 3000     # batas holder yang dianalisis per token
HOLDER_PAGE_LIMIT = 1000

HOLDER_URL = "https://gmgn.ai/vas/api/v1/token_holders/sol/{ca}"

# --- Sumber data holder -------------------------------------------------------
# Helius adalah sumber utama data holder — data on-chain
# lengkap dan lancar. GMGN hanya dipakai untuk listing Trending/Degen dan
# sebagai fallback darurat bila Helius tidak tersedia. Solscan sudah
# dilepas total dari pipeline.
HOLDER_SOURCE_GMGN = "gmgn"
HOLDER_SOURCE_HELIUS = "helius"
HOLDER_SOURCE_AUTO = "auto"
HOLDER_SOURCE_OPTIONS = (HOLDER_SOURCE_GMGN, HOLDER_SOURCE_HELIUS,
                         HOLDER_SOURCE_AUTO)
# Watchlist (cron & tombol scan lokal) memakai "auto" → Helius dulu,
# fallback GMGN. Listing Trending/Degen tetap GMGN (default
# ``enrich_rows``) karena listing memang hanya tersedia dari GMGN.
HOLDER_SOURCE_DEFAULT = HOLDER_SOURCE_AUTO

# Pencilan non-wallet (LP/AMM/pool) dikeluarkan dari hitungan holder.
NOISE_TAGS = frozenset(("sandwich_bot", "mev_bot", "mev"))

# Cache in-memory per proses/sesi: TTL singkat supaya scan ulang tidak
# membanjiri GMGN dalam beberapa detik.
_CACHE_TTL = 600
_HOLDER_CACHE: dict[str, dict] = {}


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


def _http_get(url: str, params: dict, timeout: int = 20) -> dict:
    """GET JSON dengan TLS browser (curl_cffi), fallback requests."""
    headers = {
        "accept": "application/json, text/plain, */*",
        "origin": "https://gmgn.ai",
        "referer": "https://gmgn.ai/",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/150.0.0.0 Safari/537.36"),
    }
    try:
        from curl_cffi import requests as client
        for identity in ("chrome", "chrome131", "safari17_0"):
            try:
                response = client.get(url, params=params, timeout=timeout,
                                      impersonate=identity, headers=headers)
                if response.status_code == 200:
                    return response.json() or {}
            except Exception:
                continue
        raise RuntimeError("curl_cffi semua profil gagal")
    except ImportError:
        pass
    except Exception:
        # Lanjut fallback requests; error hanya dicatat di bawah.
        pass
    try:
        import requests
        response = requests.get(url, params=params, headers=headers,
                                timeout=timeout)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        return response.json() or {}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"holders GET gagal: {exc}") from exc


def _holder_params(next_cursor: str | None, limit: int) -> dict:
    """Param holder endpoint: wajib cost/orderby/direction + build web."""
    params = {
        "limit": max(1, min(int(limit), HOLDER_PAGE_LIMIT)),
        "cost": "20",
        "orderby": "amount_percentage",
        "direction": "desc",
    }
    if next_cursor:
        params["next"] = next_cursor
    try:
        from gmgn_screener import _build_tag, DEVICE_ID, FP_DID
        build = _build_tag()
        params.update(
            device_id=DEVICE_ID,
            fp_did=FP_DID,
            client_id=f"gmgn_web_{build}",
            app_ver=build,
            from_app="gmgn",
            tz_name="Asia/Jakarta",
            tz_offset="25200",
            app_lang="en-US",
            os="web",
            worker="0",
        )
    except Exception:
        import uuid
        params.update(device_id=str(uuid.uuid4()), fp_did=uuid.uuid4().hex)
    return params


def _normalize_holder(raw: dict) -> dict | None:
    """Satu baris holder GMGN -> dict ringkas yang siap dianalisis."""
    if not isinstance(raw, dict):
        return None
    addr = str(raw.get("address") or raw.get("account_address") or "")
    if not addr:
        return None
    balance = _float(raw.get("balance", raw.get("amount_cur")))
    usd_value = _float(raw.get("usd_value"))
    exchange = str(raw.get("exchange") or "").strip()
    is_wallet = (int(_float(raw.get("addr_type"), 1)) == 0 and not exchange)
    return {
        "address": addr,
        "account_address": str(raw.get("account_address") or ""),
        "balance": balance,
        "usd_value": usd_value,
        "amount_pct": _float(raw.get("amount_percentage")),  # fraksi 0-1
        "is_wallet": is_wallet,
        "is_new": bool(raw.get("is_new")),
        "is_suspicious": bool(raw.get("is_suspicious")),
        "start_holding_at": _int(raw.get("start_holding_at")),
        "last_active_at": _int(raw.get("last_active_timestamp")),
        "netflow_usd": _float(raw.get("netflow_usd")),
        "current_buy_amount": _float(raw.get("current_buy_amount")),
        "current_sell_amount": _float(raw.get("current_sell_amount")),
        "current_transfer_in": _float(raw.get("current_transfer_in_amount")),
        "current_transfer_out": _float(raw.get("current_transfer_out_amount")),
        "wallet_tag": str(raw.get("wallet_tag_v2") or ""),
        "tags": [str(tag) for tag in (raw.get("tags") or [])],
        "maker_token_tags": [str(tag) for tag in
                             (raw.get("maker_token_tags") or [])],
    }


def _mint_decimals_helius(ca: str, keys) -> int | None:
    """Decimals mint untuk konversi ``amount`` RAW → unit UI.

    DAS ``getTokenAccounts`` mengembalikan ``amount`` dalam unit raw
    (bilangan bulat terkecil token, belum dibagi 10**decimals) dan itemnya
    tidak selalu membawa ``decimals``, jadi decimals mint di-lookup sekali:
    DAS ``getAsset`` (``token_info.decimals``) dulu, fallback RPC standar
    ``getTokenSupply``. Return ``None`` bila dua-duanya gagal.
    """
    from core import helius_rpc

    try:
        asset = helius_rpc("getAsset", {"id": ca}, helius_keys=keys)
        info = (asset or {}).get("token_info") if isinstance(asset, dict) \
            else None
        dec = _int((info or {}).get("decimals"), -1)
        if 0 <= dec <= 18:
            return dec
    except Exception:  # noqa: BLE001 - lanjut ke fallback RPC standar
        pass
    try:
        supply = helius_rpc("getTokenSupply", [ca], helius_keys=keys)
        info = (supply or {}).get("value") if isinstance(supply, dict) \
            else None
        dec = _int((info or {}).get("decimals"), -1)
        if 0 <= dec <= 18:
            return dec
    except Exception:  # noqa: BLE001
        pass
    return None


def fetch_holders_helius(ca: str, *, max_wallets: int | None = None,
                         price_usd: float = 0.0,
                         helius_keys=None) -> dict:
    """Ambil holder via Helius DAS getTokenAccounts (fallback GMGN).

    Paginasi cursor, USD = balance UI × harga token. **Penting:** field
    ``amount`` dari DAS adalah unit RAW, jadi harus dibagi
    ``10 ** decimals`` mint dulu — kalau tidak, nilai USD tiap holder
    bengkak 10^decimals× (tier/bucket jadi tidak masuk akal). Bila
    decimals tidak ditemukan, return kosong + error (lebih aman daripada
    angka salah). Hanya jalan bila ``price_usd > 0`` dan Helius key
    tersedia.
    """
    from core import helius_rpc, get_helius_keys

    ca = str(ca or "").strip()
    if not ca or price_usd <= 0:
        return {"holders": [], "pages": 0, "truncated": False,
                "fetched": 0, "analyzed_at": int(time.time()),
                "source": "helius"}

    keys = helius_keys or get_helius_keys()
    if not keys:
        return {"holders": [], "pages": 0, "truncated": False,
                "fetched": 0, "analyzed_at": int(time.time()),
                "source": "helius"}

    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)
    holders: dict[str, dict] = {}
    cursor = None
    pages = 0
    truncated = False
    page_limit = 1000
    # Pengaman paginasi: default 60 halaman (60k akun), tapi naik mengikuti
    # ``max_wallets`` supaya scan FULL manual benar-benar mengambil semua
    # holder (batas keras 200 halaman = 200k akun).
    page_cap = max(60, min(200, -(-max_wallets // page_limit) + 5))
    mint_decimals: int | None = None
    decimals_checked = False
    error = ""

    while True:
        params = {"mint": ca, "limit": page_limit}
        if cursor:
            params["cursor"] = cursor
        try:
            result = helius_rpc("getTokenAccounts", params, helius_keys=keys)
        except Exception:  # noqa: BLE001
            error = "getTokenAccounts gagal"
            break

        if not isinstance(result, dict):
            error = "respons getTokenAccounts tidak valid"
            break
        accounts = result.get("token_accounts") or []
        pages += 1
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            addr = str(acc.get("owner") or "").strip()
            if not addr:
                continue
            dec = _int(acc.get("decimals"), -1)  # bila item membawa decimals
            if dec < 0:
                if not decimals_checked:
                    decimals_checked = True
                    mint_decimals = _mint_decimals_helius(ca, keys)
                dec = mint_decimals if mint_decimals is not None else -1
            if dec < 0:
                # Tanpa decimals nilai USD pasti salah (10^dec× lebih
                # besar) — hentikan bersih, jangan kirim angka sampah.
                error = ("decimals mint tidak ditemukan "
                         "(getAsset & getTokenSupply gagal)")
                return {"holders": [], "pages": pages, "truncated": False,
                        "fetched": 0, "analyzed_at": int(time.time()),
                        "source": "helius", "decimals": None,
                        "error": error}
            balance = _float(acc.get("amount")) / (10.0 ** dec)
            usd_value = balance * price_usd
            if addr not in holders:
                holders[addr] = {
                    "address": addr,
                    "account_address": str(acc.get("address") or ""),
                    "balance": balance,
                    "usd_value": usd_value,
                    "amount_pct": 0.0,  # DAS tidak beri %
                    "is_wallet": True,
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
                    "tags": [],
                    "maker_token_tags": [],
                }
        next_cursor = str(result.get("cursor") or "").strip()
        if len(holders) >= max_wallets:
            truncated = True
            break
        if not next_cursor:
            break
        cursor = next_cursor
        if pages >= page_cap:
            truncated = True
            break

    return {
        "holders": list(holders.values()),
        "pages": pages,
        "truncated": truncated,
        "fetched": len(holders),
        "analyzed_at": int(time.time()),
        "source": "helius",
        "decimals": mint_decimals,
        "error": error,
    }


def fetch_holders(ca: str, *, max_wallets: int | None = None,
                  page_limit: int = HOLDER_PAGE_LIMIT,
                  timeout: int = 20,
                  price_usd: float = 0.0) -> dict:
    """Ambil daftar holder GMGN (paginasi ``next``) sampai ``max_wallets``.

    Ini jalur GMGN — dipakai oleh listing Trending/Degen dan sebagai
    fallback darurat dari jalur Helius-first (``_fetch_holders_snapshot``).
    Fallback ke Helius DAS bila GMGN error/kosong (asalkan price_usd > 0
    dan Helius key ada).

    Return ``{"holders": [...], "pages": n, "truncated": bool,
    "fetched": n, "analyzed_at": ts, "source": "gmgn"|"helius"}``.
    """
    ca = str(ca or "").strip()
    if not ca:
        return {"holders": [], "pages": 0, "truncated": False,
                "fetched": 0, "analyzed_at": int(time.time()),
                "source": "gmgn"}
    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)
    cache_key = f"{ca}:{max_wallets}"
    cached = _HOLDER_CACHE.get(cache_key)
    if cached and time.time() - cached.get("analyzed_at", 0) < _CACHE_TTL:
        return dict(cached)

    holders: dict[str, dict] = {}
    cursor = None
    pages = 0
    seen_cursors = set()
    truncated = False
    last_error = ""
    source = "gmgn"
    while True:
        try:
            payload = _http_get(
                HOLDER_URL.format(ca=ca),
                params=_holder_params(cursor, page_limit), timeout=timeout)
        except Exception:  # noqa: BLE001
            break
        code = payload.get("code")
        if code not in (None, 0, "0", "success"):
            break
        data = payload.get("data") or {}
        rows = data.get("list") or []
        pages += 1
        for raw in rows:
            holder = _normalize_holder(raw)
            if holder and holder["address"] not in holders:
                holders[holder["address"]] = holder
        next_cursor = str(data.get("next") or "").strip()
        if len(holders) >= max_wallets:
            truncated = len(holders) >= max_wallets
            break
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        if pages >= 60:  # pengaman keras
            truncated = True
            break

    # Fallback ke Helius bila GMGN kosong/error
    if not holders and price_usd > 0:
        helius_result = fetch_holders_helius(
            ca, max_wallets=max_wallets, price_usd=price_usd)
        if helius_result.get("holders"):
            _HOLDER_CACHE[cache_key] = helius_result
            return helius_result

    result = {
        "holders": list(holders.values()),
        "pages": pages,
        "truncated": truncated,
        "fetched": len(holders),
        "analyzed_at": int(time.time()),
        "source": source,
    }
    _HOLDER_CACHE[cache_key] = result
    return result


def classify_holders(snapshot: dict | None, market_cap: float = 0.0,
                     *, dust_limit: float | None = None) -> dict:
    """Pisahkan real holder (>$10 value) vs dust (0 < value <= $10).

    Return metrik: jumlah wallet, nilai USD kedua kelompok, dan
    **dust % dari marketcap** (dust_value / marketcap * 100) plus
    dust % supply (dari amount_percentage) bila tersedia.
    Field ``source`` diteruskan dari snapshot (gmgn/helius).
    """
    dust_limit = float(DUST_LIMIT_USD if dust_limit is None else dust_limit)
    holders = (snapshot or {}).get("holders") or []
    source = str((snapshot or {}).get("source") or "gmgn")
    real = [h for h in holders
            if h.get("is_wallet") and h.get("usd_value", 0) > dust_limit]
    dust = [h for h in holders
            if h.get("is_wallet")
            and 0 < h.get("usd_value", 0) <= dust_limit]
    real_value = sum(h.get("usd_value", 0) for h in real)
    dust_value = sum(h.get("usd_value", 0) for h in dust)
    real_supply = sum(h.get("amount_pct", 0) for h in real)
    dust_supply = sum(h.get("amount_pct", 0) for h in dust)
    mc = float(market_cap or 0)
    dust_pct_mc = (dust_value / mc * 100.0) if mc > 0 else None
    real_pct_mc = (real_value / mc * 100.0) if mc > 0 else None
    return {
        "dust_limit_usd": dust_limit,
        "real_count": len(real),
        "dust_count": len(dust),
        "wallets_analyzed": len(real) + len(dust),
        "total_fetched": len(holders),
        "truncated": bool((snapshot or {}).get("truncated")),
        "pages": int((snapshot or {}).get("pages") or 0),
        "real_value_usd": round(real_value, 2),
        "dust_value_usd": round(dust_value, 2),
        "dust_pct_mc": round(dust_pct_mc, 4) if dust_pct_mc is not None else None,
        "real_pct_mc": round(real_pct_mc, 4) if real_pct_mc is not None else None,
        "dust_pct_supply": round(dust_supply * 100.0, 4),
        "real_pct_supply": round(real_supply * 100.0, 4),
        "new_real": sum(1 for h in real if h.get("is_new")),
        "new_dust": sum(1 for h in dust if h.get("is_new")),
        "suspicious_dust": sum(1 for h in dust if h.get("is_suspicious")),
        "source": source,
    }


def resolve_holder_source(requested: str | None = None) -> str:
    """Prioritas sumber holder: param → config/env ``holder_source`` → auto.

    - ``gmgn``    : GMGN (listing Trending/Degen), fallback Helius.
    - ``helius``  : Paksa Helius DAS, fallback GMGN.
    - ``auto``    : Helius dulu untuk token watchlist, fallback GMGN.
    """
    value = str(requested or "").strip().lower()
    if value in HOLDER_SOURCE_OPTIONS:
        return value
    try:
        from core import get_holder_source
        configured = get_holder_source(default=HOLDER_SOURCE_DEFAULT)
        if configured in HOLDER_SOURCE_OPTIONS:
            return configured
    except Exception:
        pass
    return HOLDER_SOURCE_DEFAULT


def _fetch_holders_snapshot(ca: str, source: str, *, max_wallets: int,
                            timeout: int, price_usd: float,
                            market_cap: float, market: dict,
                            ) -> tuple[dict, dict | None]:
    """Snapshot holder: Helius prioritas, + depth bila holder dari Helius.

    ``source`` sudah di-resolve. Return ``(snapshot, depth)``; ``depth``
    (Wallet Depth by Threshold + tier) dihitung saat snapshot berasal dari
    Helius. Bila Helius tidak tersedia/gagal → fallback GMGN
    (:func:`fetch_holders`, yang sendirinya masih fallback ke Helius).
    """
    if source != HOLDER_SOURCE_GMGN and price_usd > 0:
        try:
            from core import get_helius_keys
            keys = get_helius_keys()
        except Exception:  # noqa: BLE001 - tanpa key → fallback GMGN
            keys = []
        if keys:
            try:
                from solscan_holders import wallet_depth
                pools = set(str(p or "").strip() for p in
                            (market.get("pair_addresses") or []) if p)
                snapshot = fetch_holders_helius(
                    ca, max_wallets=max_wallets, price_usd=price_usd,
                    helius_keys=keys)
                if snapshot.get("holders"):
                    # Bucket default tanpa LP/pool — pool AMM yang menyerap
                    # dump (bisa 25-40% supply) bukan "holder" dan bikin
                    # distribusi menyesatkan. Tier memang selalu wallet-only.
                    depth = wallet_depth(snapshot.get("holders") or [],
                                         market_cap, pool_addresses=pools,
                                         include_pools=False)
                    return snapshot, depth
            except Exception:  # noqa: BLE001 - fallback GMGN
                pass
    return fetch_holders(ca, max_wallets=max_wallets, timeout=timeout,
                         price_usd=price_usd), None


def analyze_token(ca: str, symbol: str = "?", market_cap: float = 0.0,
                  *, dust_limit: float | None = None,
                  max_wallets: int | None = None,
                  fetch_market: bool = True,
                  timeout: int = 20,
                  price_usd: float = 0.0,
                  holder_source: str | None = None,
                  extra_pools=None,
                  cohort_addrs=None) -> dict:
    """Analisis holder (real vs dust + mid-tier + kohort).

    ``extra_pools``: address LP tambahan (mis. pool Meteora) yang dibuang
    dari hitungan wallet. ``cohort_addrs``: address Crab+Fish yang di-freeze
    pada scan sebelumnya — saldonya dikembalikan di ``holders.cohort_now``.
    """
    ca = str(ca or "").strip()
    dust_limit = float(DUST_LIMIT_USD if dust_limit is None else dust_limit)
    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)
    source = resolve_holder_source(holder_source)
    market = {}
    if fetch_market:
        try:
            market = get_market(ca) or {}
        except Exception:
            market = {}
    mc = float(market_cap or market.get("marketcap") or 0)
    price = float(price_usd or market.get("price_usd") or 0)

    extra = set(str(p or "").strip() for p in (extra_pools or []) if p)
    if extra:
        market = dict(market)
        existing = [str(p or "").strip() for p in
                    (market.get("pair_addresses") or []) if p]
        market["pair_addresses"] = list(dict.fromkeys([*existing, *extra]))

    snapshot, depth = _fetch_holders_snapshot(
        ca, source, max_wallets=max_wallets, timeout=timeout,
        price_usd=price, market_cap=mc, market=market)
    holder_stats = classify_holders(snapshot, mc, dust_limit=dust_limit)
    # Keep a compact balance snapshot so the cron can distinguish a genuine
    # buy (wallet balance increased) from dust merely leaving the bucket.
    holder_stats["wallet_balances"] = {
        str(row.get("address")): row.get("balance")
        for row in (snapshot.get("holders") or [])
        if isinstance(row, dict) and row.get("is_wallet") and row.get("address")
        and row.get("balance") is not None
    }
    if depth is not None:
        holder_stats["depth"] = depth
    pools = set(str(p or "").strip() for p in
                (market.get("pair_addresses") or []) if p)
    try:
        from holder_history import lookup_balances, mid_tier_stats
        holder_stats["mid"] = mid_tier_stats(
            snapshot.get("holders") or [], mc, pool_addresses=pools)
        holder_stats["cohort_now"] = lookup_balances(
            snapshot.get("holders") or [], cohort_addrs or [])
    except Exception:  # noqa: BLE001 - analisa holder jangan gagal total
        holder_stats.setdefault("mid", {"count": 0, "balances": {}})
        holder_stats.setdefault("cohort_now", {})
    return {
        "ca": ca,
        "symbol": str(symbol or market.get("symbol") or "?"),
        "marketcap": mc,
        "price": price,
        "analyzed_at": int(time.time()),
        "holders": holder_stats,
    }

