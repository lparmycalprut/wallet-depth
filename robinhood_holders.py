# -*- coding: utf-8 -*-
"""Holder analysis for **Robinhood Chain** (chain id 4663, EVM).

Walpaper Depth saat ini dominan memalai Solana (Helius/GMGN). Robinhood
Chain adalah EVM L2 (Arbitrum Orbit), jadi jangkar contract-address-nya
``0x…`` dan data holder diambil dari Blockscout
(``robinhoodchain.blockscout.com``) — Etherscan/Helius tidak mendukung
chain id 4663. Modul ini menyediakan:

1. :func:`fetch_token_info` — decimals/symbol/supply dari Blockscout.
2. :func:`fetch_holders` — seluruh daftar holder ERC-20 terpaginasi,
   nilai token diubah ke unit UI lalu ke USD memakai harga DexScreener.
3. :func:`analyze_token` — output yang bentuknya sama persis dengan
   :func:`holder_analysis.analyze_token` sehingga rule dust holder,
   chart 4 jam, kronologi, dan alert Telegram dipakai ulang tanpa logika
   baru.

Semua rule sama dengan Solana:
- dust wallet = ``0 < value <= $10`` (``holder_analysis.DUST_LIMIT_USD``);
- dust % MC >= 0,5% = HATI-HATI, >= 1% = BAHAYA;
- grafik 4 jam memakai ``holder_history`` yang sama.
"""
from __future__ import annotations

import time

import requests

from core import get_market
from holder_analysis import DUST_LIMIT_USD, DEFAULT_MAX_WALLETS, classify_holders

CHAIN_SLUG = "robinhood"
CHAIN_ID = "4663"
CHAIN_NAME = "Robinhood Chain"
BLOCKSCOUT_API = "https://robinhoodchain.blockscout.com/api"
BLOCKSCOUT_BASE = "https://robinhoodchain.blockscout.com"
RH_SCAN_TOKEN_BASE = "https://rh-scan.com/token/"
DEXSCREENER_CHAIN = CHAIN_SLUG
# Blockscout pagination; cukup besar supaya scan FULL tidak perlu ratusan
# request untuk token biasa.
HOLDER_PAGE_SIZE = 1000
HOLDER_PAGE_CAP = 200

_EVM_ADDRESS_RE = __import__("re").compile(r"0x[0-9a-fA-F]{40}")


def _float(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        return num if num == num else default
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    return int(_float(value, float(default)))


# Blockscout publik membatasi laju (HTTP 429) dan sesekali membalas 5xx.
# Satu request yang gagal pernah membuat seluruh scan satu token pulang
# dengan 0 wallet — dan karena ``classify_holders`` tidak membawa pesan
# error, angka "dust 0,00%" tampil seperti hasil scan yang sungguh-sungguh.
# Karena itu error sementara diulang satu kali dengan jeda pendek.
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 1
RETRY_BACKOFF_SEC = 3.0


def _status_code(exc) -> int:
    response = getattr(exc, "response", None)
    try:
        return int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def is_transient_error(exc) -> bool:
    """True untuk kegagalan jaringan/HTTP yang layak dicoba ulang."""
    if _status_code(exc) in TRANSIENT_STATUS:
        return True
    return isinstance(exc, (requests.exceptions.Timeout,
                            requests.exceptions.ConnectionError))


def _jsjson(params: dict, *, retries: int = RETRY_ATTEMPTS,
            timeout: int = 25) -> dict:
    """GET JSON dari Blockscout dengan header browser sederhana.

    Kegagalan sementara (429/5xx/timeout) diulang ``retries`` kali dengan
    jeda :data:`RETRY_BACKOFF_SEC`; error lain (dan kegagalan percobaan
    terakhir) dilempar seperti sebelumnya supaya pemanggil tetap bisa
    memutuskan sendiri (``fetch_holders`` mencatatnya sebagai ``error``).
    """
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/150.0.0.0 Safari/537.36"),
    }
    attempts = max(0, int(retries))
    last_exc: Exception | None = None
    for attempt in range(attempts + 1):
        try:
            response = requests.get(BLOCKSCOUT_API, params=params,
                                    headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json() or {}
        except Exception as exc:  # noqa: BLE001 - jenis error ditentukan caller
            last_exc = exc
            if attempt >= attempts or not is_transient_error(exc):
                raise
            time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
    raise last_exc  # pragma: no cover - loop selalu return/raise


def normalize_address(address: str) -> str:
    """Trim plus lower-case ``0x`` EVM address; Solana left intact."""
    ca = str(address or "").strip()
    if ca.lower().startswith("0x") and len(ca) == 42:
        return ca.lower()
    return ca


def is_robinhood_address(address: str) -> bool:
    """True untuk address EVM 0x + 40 hex (Robinhood Chain)."""
    return bool(_EVM_ADDRESS_RE.fullmatch(str(address or "").strip()))


def fetch_token_info(ca: str) -> dict:
    """``{name, symbol, decimals, total_supply}`` dari Blockscout.

    Blockscout menjawab dengan ``status: "0"`` + ``message`` untuk request
    yang ditolak (rate limit, token belum di-index). payload seperti itu dulu
    jatuh diam-diam ke ``decimals: -1`` lalu membuat seluruh scan holder
    pulang dengan 0 wallet tanpa keterangan — jadi sekarang di-lempar;
    ``analyze_token`` / ``scan_watchlist`` sudah menangkap exception itu dan
    menuliskan error provider di log.
    """
    payload = _jsjson({
        "module": "token",
        "action": "getToken",
        "contractaddress": normalize_address(ca),
    })
    status = str(payload.get("status") or "").strip()
    if status not in ("1", ""):
        raise RuntimeError(str(payload.get("message")
                               or "Blockscout getToken menolak request"))
    result = payload.get("result") if isinstance(payload.get("result"), dict) \
        else {}
    decimals = _int(result.get("decimals"), -1)
    supply_raw = _float(result.get("totalSupply"), None)
    return {
        "name": str(result.get("name") or "?"),
        "symbol": str(result.get("symbol") or "?"),
        "decimals": decimals,
        "total_supply": (supply_raw / (10.0 ** decimals)) if (
            decimals is not None and decimals >= 0 and supply_raw is not None
        ) else None,
        "type": str(result.get("type") or "ERC-20"),
    }


def _is_pool_address(address: str, pools: set) -> bool:
    return str(address or "").lower() in pools


def fetch_holders(ca: str, *, max_wallets: int | None = None,
                  price_usd: float = 0.0, decimals: int | None = None,
                  total_supply: float | None = None) -> dict:
    """Ambil seluruh holder ERC-20 di Robinhood Chain via Blockscout.

    Return shape sama dengan ``holder_analysis.fetch_holders``:
    ``{"holders": [...], "pages", "truncated", "fetched", "analyzed_at",
    "source", "decimals", "error"}``.

    ``value`` dari Blockscout adalah unit RAW ERC-20, jadi harus dibagi
    ``10 ** decimals`` sebelum dihitung USD (sama seperti amount RAW
    Helius).
    """
    ca = normalize_address(ca)
    if not ca or price_usd <= 0:
        return {"holders": [], "pages": 0, "truncated": False, "fetched": 0,
                "analyzed_at": int(time.time()), "source": "blockscout",
                "decimals": decimals, "error": "price/address empty"}
    if decimals is None or decimals < 0:
        try:
            info = fetch_token_info(ca)
        except Exception as exc:  # noqa: BLE001 - kontrak: selalu kembalikan dict
            return {"holders": [], "pages": 0, "truncated": False,
                    "fetched": 0, "analyzed_at": int(time.time()),
                    "source": "blockscout", "decimals": None,
                    "error": f"Blockscout getToken: {exc}"}
        decimals = info.get("decimals")
        if decimals is None or decimals < 0:
            return {"holders": [], "pages": 0, "truncated": False,
                    "fetched": 0, "analyzed_at": int(time.time()),
                    "source": "blockscout", "decimals": None,
                    "error": "decimals mint tidak ditemukan"}

    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)
    holders: dict[str, dict] = {}
    pages = 0
    truncated = False
    error = ""
    divisor = 10.0 ** decimals
    page = 1
    while True:
        try:
            payload = _jsjson({
                "module": "token",
                "action": "getTokenHolders",
                "contractaddress": ca,
                "page": page,
                "offset": HOLDER_PAGE_SIZE,
            })
        except Exception as exc:  # noqa: BLE001 - provider outage -> clean stop
            error = str(exc)
            break
        if str(payload.get("status") or "").strip() not in ("1", ""):
            error = str(payload.get("message") or "Blockscout error")
            break
        rows = payload.get("result") or []
        if not isinstance(rows, list):
            error = "Blockscout return holder tidak valid"
            break
        pages += 1
        for raw in rows:
            if len(holders) >= max_wallets:
                truncated = True
                break
            if not isinstance(raw, dict):
                continue
            addr = normalize_address(raw.get("address"))
            if not addr:
                continue
            balance = _float(raw.get("value")) / divisor
            if balance <= 0:
                continue
            if addr not in holders:
                holders[addr] = {
                    "address": addr,
                    "account_address": addr,
                    "balance": balance,
                    "usd_value": balance * float(price_usd),
                    "amount_pct": (balance / float(total_supply)
                                   if total_supply and total_supply > 0
                                   else 0.0),
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
        if len(holders) >= max_wallets:
            truncated = True
            break
        if len(rows) < HOLDER_PAGE_SIZE:
            break
        if pages >= HOLDER_PAGE_CAP:
            truncated = True
            break
        page += 1
    return {
        "holders": list(holders.values()),
        "pages": pages,
        "truncated": truncated,
        "fetched": len(holders),
        "analyzed_at": int(time.time()),
        "source": "blockscout",
        "decimals": decimals,
        "error": error,
    }


def _mark_pools(holders: list[dict], pool_addresses) -> list[dict]:
    """Tandai address LP/pool DexScreener sebagai bukan wallet murni."""
    pools = {normalize_address(p) for p in (pool_addresses or []) if p}
    if not pools:
        return holders
    out = []
    for row in holders or []:
        if not isinstance(row, dict):
            continue
        if _is_pool_address(row.get("address"), pools):
            row = dict(row)
            row["is_wallet"] = False
            row["wallet_tag"] = "pool"
        out.append(row)
    return out


def _known_pools(market: dict | None, extra_pools=None) -> list[str]:
    pool = list((market or {}).get("pair_addresses") or [])
    pool.extend(str(p or "").strip() for p in (extra_pools or []) if p)
    return list(dict.fromkeys(pool))


def analyze_token(ca: str, symbol: str = "?", market_cap: float = 0.0,
                  *, dust_limit: float | None = None,
                  max_wallets: int | None = None,
                  fetch_market: bool = True,
                  timeout: int = 25,
                  price_usd: float = 0.0,
                  extra_pools=None,
                  cohort_addrs=None,
                  tracked_wallet_addrs=None) -> dict:
    """Analisis holder token Robinhood Chain (Blockscout + DexScreener).

    Menghasilkan bentuk yang sama dengan
    ``holder_analysis.analyze_token`` sehingga seluruh alur watchlist,
    holder_history, dan telegram_alerts dapat dipakai langsung.
    """
    ca = normalize_address(ca)
    dust_limit = float(DUST_LIMIT_USD if dust_limit is None else dust_limit)
    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)

    market = {}
    if fetch_market:
        try:
            market = get_market(ca, chain_id=DEXSCREENER_CHAIN) or {}
        except Exception:  # noqa: BLE001 - lanjut, token info tetap bisa
            market = {}
    mc = float(market_cap or market.get("marketcap") or 0)
    price = float(price_usd or market.get("price_usd") or 0)

    info = {}
    if price > 0:
        try:
            info = fetch_token_info(ca)
        except Exception as exc:  # noqa: BLE001
            info = {"error": str(exc), "decimals": None, "symbol": "?"}
    symbol = str(symbol or market.get("symbol") or (info or {}).get("symbol")
                 or "?").upper()
    supply = None
    if isinstance(info, dict):
        supply = info.get("total_supply")

    snapshot = fetch_holders(
        ca, max_wallets=max_wallets, price_usd=price,
        decimals=(info or {}).get("decimals"), total_supply=supply)

    pools = _known_pools(market, extra_pools)
    snapshot["holders"] = _mark_pools(snapshot.get("holders") or [], pools)
    holder_stats = classify_holders(snapshot, mc, dust_limit=dust_limit)
    # Alasan provider (rate limit, token belum di-index) dulu hilang di sini,
    # sehingga scan yang pulang dengan 0 wallet terbaca seperti hasil sungguhan
    # ("dust 0 wallet = AMAN"). Dibawa terus supaya UI + snapshot bisa jujur.
    fetch_error = str(snapshot.get("error") or "")
    if fetch_error:
        holder_stats["fetch_error"] = fetch_error

    try:
        from solscan_holders import wallet_depth
        holder_stats["depth"] = wallet_depth(
            snapshot.get("holders") or [], mc, pool_addresses=pools,
            include_pools=False)
    except Exception:  # noqa: BLE001 - depth pelengkap
        holder_stats.setdefault("depth", {})

    try:
        from holder_history import lookup_balances, mid_tier_stats
        holder_stats["mid"] = mid_tier_stats(
            snapshot.get("holders") or [], mc, pool_addresses=pools)
        holder_stats["cohort_now"] = lookup_balances(
            snapshot.get("holders") or [], cohort_addrs or [])
    except Exception:  # noqa: BLE001
        holder_stats.setdefault("mid", {"count": 0, "balances": {}})
        holder_stats.setdefault("cohort_now", {})

    analyzed_at = int(time.time())
    try:
        from telegram_alerts import build_wallet_snapshot
        holder_stats["wallet_snapshot"] = build_wallet_snapshot(
            snapshot.get("holders") or [],
            dust_pct_mc=holder_stats.get("dust_pct_mc"),
            dust_limit_usd=dust_limit,
            tracked_addresses=tracked_wallet_addrs or [],
            ts=analyzed_at,
            truncated=bool(snapshot.get("truncated")),
        )
    except Exception:  # noqa: BLE001
        holder_stats.setdefault("wallet_snapshot", {})
    try:
        from holder_chronology import build_chrono_snapshot
        holder_stats["chrono_snapshot"] = build_chrono_snapshot(
            snapshot.get("holders") or [],
            tracked_addresses=tracked_wallet_addrs or [],
            pool_addresses=pools,
            ts=analyzed_at,
            price=price,
            market_cap=mc,
            dust_pct_mc=holder_stats.get("dust_pct_mc"),
            holder_count=holder_stats.get("wallets_analyzed"),
            dust_count=holder_stats.get("dust_count"),
            truncated=bool(snapshot.get("truncated")),
        )
    except Exception:  # noqa: BLE001 - kronologi tidak boleh mematikan scan
        holder_stats.setdefault("chrono_snapshot", {})

    return {
        "ca": ca,
        "symbol": symbol,
        "marketcap": mc,
        "price": price,
        "analyzed_at": analyzed_at,
        "holders": holder_stats,
        "market": {
            "price_usd": price or _float(market.get("price_usd"), 0.0),
            "marketcap": mc,
            "volume": market.get("volume") or {},
            "price_change": market.get("price_change") or {},
            "txns": market.get("txns") or {},
            "pair_addresses": pools,
            "dex": market.get("dex") or "?",
        },
    }
