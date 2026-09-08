# -*- coding: utf-8 -*-
"""Holder analysis for **Robinhood Chain** (chain id 4663, EVM).

Robinhood Chain adalah EVM L2 (Arbitrum Orbit) dengan
contract-address ``0x…``. Sumber holder-nya **Blockscout saja** —
``robinhoodchain.blockscout.com``, explorer resmi chain ini. GMGN
**tidak dipakai lagi** (dilepas 2026-09-08): endpoint
``/vas/api/v1/token_holders/robinhood/<CA>`` memang menjawab
``code: 0`` tetapi ``data.list`` selalu **kosong** — GMGN tidak
meng-index chain 4663. Karena kode lama memperlakukan GMGN sebagai
*primary*, tiap scan membuang satu request lalu jatuh ke Blockscout,
dan bila Blockscout ikut tersendat hasilnya "0 holder" yang terbaca
seperti "dust hilang semua".

Tiga jalur Blockscout dipakai berurutan, dari yang paling lengkap:

1. **CSV export** (utama, TANPA limit paginasi) —
   ``/api/v2/tokens/<CA>/holders/csv`` mengembalikan **seluruh** holder
   dalam satu response, sudah ter-scale decimals
   (``HolderAddress,Balance``). Instance ini memakai mode sinkron
   (``/api/v2/config/csv-export`` → ``async_enabled: false``,
   ``limit: 10000``), jadi satu request = satu daftar penuh.
2. **REST v2 keyset** (fallback) — ``/api/v2/tokens/<CA>/holders``
   dengan cursor ``next_page_params`` (``address_hash`` + ``value``).
   Maksimum **50 baris/halaman** (``items_count`` > 50 ditolak 422),
   tetapi cursor-nya tidak punya batas kedalaman dan membawa metadata
   kontrak/pool (``is_contract``, ``name``) yang dipakai menandai LP.
3. **Legacy RPC** (fallback terakhir) —
   ``?module=token&action=getTokenHolders``. Perhatian: ``offset``
   dibatasi **≤ 400** (nilai lebih besar dijawab
   ``{"status":"0","message":"Something went wrong."}``) — inilah yang
   membuat versi lama, yang meminta ``offset=1000``, **selalu gagal**.

Modul ini menyediakan:

1. :func:`fetch_token_info` — decimals/symbol/supply dari Blockscout.
2. :func:`fetch_holders` — seluruh daftar holder ERC-20
   (``source: "blockscout-csv"`` / ``"blockscout-v2"`` /
   ``"blockscout-rpc"``).
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

import csv
import io
import time

import requests

from core import get_market
from holder_analysis import DUST_LIMIT_USD, DEFAULT_MAX_WALLETS, classify_holders
from solscan_holders import wallet_depth

CHAIN_SLUG = "robinhood"
CHAIN_ID = "4663"
CHAIN_NAME = "Robinhood Chain"
BLOCKSCOUT_API = "https://robinhoodchain.blockscout.com/api"
BLOCKSCOUT_BASE = "https://robinhoodchain.blockscout.com"
BLOCKSCOUT_V2 = f"{BLOCKSCOUT_BASE}/api/v2"
RH_SCAN_TOKEN_BASE = "https://rh-scan.com/token/"
DEXSCREENER_CHAIN = CHAIN_SLUG

SOURCE_CSV = "blockscout-csv"
SOURCE_V2 = "blockscout-v2"
SOURCE_RPC = "blockscout-rpc"

# Cache in-memory: TTL singkat supaya rerun Streamlit dalam hitungan detik
# tidak menembak Blockscout berkali-kali. HARUS jauh di bawah
# ``holder_history.LP_INTERVAL_SEC`` (300 dtk) supaya scan LP 5 menit selalu
# memotret data baru, bukan snapshot cache yang bikin grafik mendatar.
_HOLDER_CACHE_TTL = 90
_HOLDER_CACHE: dict[str, dict] = {}

# Batas nyata Blockscout (terukur di robinhoodchain.blockscout.com,
# 2026-09-08). Melewatinya = request ditolak, bukan sekadar dipotong.
V2_PAGE_SIZE = 50            # /api/v2/…/holders → items_count max 50
V2_PAGE_CAP = 600            # 600 × 50 = 30k wallet (jalur cadangan terakhir)
HOLDER_PAGE_SIZE = 400       # legacy RPC → offset max 400 (bukan 1000!)
HOLDER_PAGE_CAP = 500        # 500 × 400 = 200k wallet, cukup untuk token terbesar
PAGE_SLEEP_SEC = 0.6         # ~1,7 req/s — sopan untuk instance publik
CSV_TIMEOUT = 90             # satu response bisa memuat puluhan ribu baris

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


# ---------------------------------------------------------------------------
# Blockscout — satu-satunya sumber holder Robinhood Chain
# ---------------------------------------------------------------------------
# GMGN dilepas 2026-09-08: chain 4663 tidak di-index di sana (``data.list``
# selalu []), jadi memakainya sebagai primary hanya menambah satu request
# gagal per scan. Blockscout publik membatasi laju (HTTP 429) dan sesekali
# membalas 5xx, jadi transport-nya tetap memakai retry + backoff.
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SEC = 5.0


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
    jeda exponential (``RETRY_BACKOFF_SEC * 2^attempt``); error lain (dan
    kegagalan percobaan terakhir) dilempar supaya caller bisa fallback.
    """
    headers = {
        "accept": "application/json, text/plain; */*",
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
            time.sleep(RETRY_BACKOFF_SEC * (2 ** attempt))
    raise last_exc  # pragma: no cover - loop selalu return/raise


def _http_get(url: str, *, params: dict | None = None,
              retries: int = RETRY_ATTEMPTS, timeout: int = 25):
    """GET mentah ke Blockscout dengan retry yang sama seperti :func:`_jsjson`.

    Dipakai endpoint non-``/api`` (REST v2 + CSV export) yang tidak memakai
    bentuk ``module/action``. Response dikembalikan apa adanya supaya caller
    bisa membaca ``.json()`` maupun ``.text`` (CSV).
    """
    headers = {
        "accept": "application/json, text/csv, text/plain; */*",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/150.0.0.0 Safari/537.36"),
    }
    attempts = max(0, int(retries))
    last_exc: Exception | None = None
    for attempt in range(attempts + 1):
        try:
            response = requests.get(url, params=params, headers=headers,
                                    timeout=timeout)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001 - caller memutuskan fallback
            last_exc = exc
            if attempt >= attempts or not is_transient_error(exc):
                raise
            time.sleep(RETRY_BACKOFF_SEC * (2 ** attempt))
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


def clear_holder_cache() -> None:
    """Kosongkan cache holder in-memory (dipakai test & tombol refresh)."""
    _HOLDER_CACHE.clear()


def fetch_holders_count(ca: str) -> int:
    """Jumlah holder on-chain via ``/api/v2/tokens/<CA>/counters``.

    Dipakai sebagai sanity-check: kalau daftar yang berhasil ditarik jauh
    lebih pendek daripada angka ini, hasilnya ditandai ``truncated``.
    Mengembalikan 0 kalau endpoint tidak menjawab (bukan error fatal).
    """
    try:
        payload = _http_get(
            f"{BLOCKSCOUT_V2}/tokens/{normalize_address(ca)}/counters",
            timeout=20).json() or {}
    except Exception:  # noqa: BLE001 - counters hanya pelengkap
        return 0
    return _int(payload.get("token_holders_count"), 0)


def _holder_row(address: str, balance: float, price_usd: float,
                supply: float, pools: set, *, is_contract: bool = False,
                label: str = "") -> dict:
    """Bentuk baris holder yang dipakai classify_holders/wallet_depth."""
    addr_l = str(address or "").strip().lower()
    is_pool = bool(is_contract) or _is_pool_address(addr_l, pools)
    return {
        "address": addr_l,
        "account_address": addr_l,
        "balance": balance,
        "usd_value": balance * price_usd if price_usd > 0 else 0.0,
        # fraksi 0-1 (bukan persen) — holder_analysis yang mengalikan 100
        "amount_pct": (balance / supply) if supply > 0 else 0.0,
        "is_wallet": not is_pool,
        "is_new": False,
        "is_suspicious": False,
        "start_holding_at": None,
        "last_active_at": None,
        "netflow_usd": 0.0,
        "current_buy_amount": 0.0,
        "current_sell_amount": 0.0,
        "current_transfer_in": 0.0,
        "current_transfer_out": 0.0,
        "wallet_tag": label,
        "tags": [label] if label else [],
        "maker_token_tags": [],
    }


def fetch_holders_csv(ca: str, *, price_usd: float = 0.0,
                      supply: float = 0.0, pools: set | None = None,
                      max_wallets: int | None = None) -> list[dict]:
    """Seluruh holder lewat CSV export Blockscout — **satu request, tanpa paginasi**.

    ``GET /api/v2/tokens/<CA>/holders/csv`` membalas ``text/csv`` dengan
    header ``HolderAddress,Balance`` dan **balance yang sudah dibagi
    decimals**, jadi tidak perlu ``10**decimals`` lagi. Ini jalur paling
    lengkap sekaligus paling murah: token dengan 10 ribu holder pun cukup
    satu panggilan (instance ini sinkron, lihat ``/api/v2/config/csv-export``).

    Melempar exception kalau response bukan CSV holder yang valid supaya
    :func:`fetch_holders` bisa turun ke jalur v2.
    """
    pools = pools or set()
    response = _http_get(f"{BLOCKSCOUT_V2}/tokens/{normalize_address(ca)}"
                         "/holders/csv", timeout=CSV_TIMEOUT)
    text = response.text or ""
    if text.lstrip().startswith("<") or "HolderAddress" not in text[:200]:
        raise RuntimeError("CSV export Blockscout tidak mengembalikan tabel holder")
    rows: list[dict] = []
    limit = int(max_wallets) if max_wallets else 0
    for row in csv.DictReader(io.StringIO(text)):
        address = (row.get("HolderAddress") or "").strip()
        if not is_robinhood_address(address):
            continue
        balance = _float(row.get("Balance"), 0.0)
        if balance <= 0:
            continue
        rows.append(_holder_row(address, balance, price_usd, supply, pools))
        if limit and len(rows) >= limit:
            break
    if not rows:
        raise RuntimeError("CSV export Blockscout kosong")
    rows.sort(key=lambda item: item["balance"], reverse=True)
    return rows


def fetch_holders_v2(ca: str, *, price_usd: float = 0.0, supply: float = 0.0,
                     decimals: int = 18, pools: set | None = None,
                     max_wallets: int | None = None) -> list[dict]:
    """Holder via REST v2 keyset pagination (50/halaman, cursor tanpa batas).

    Lebih lambat daripada CSV tetapi membawa metadata address
    (``is_contract``, ``name``) sehingga LP/kontrak bisa ditandai otomatis —
    berguna untuk token yang tidak punya pair terdaftar di DexScreener.
    """
    pools = pools or set()
    scale = 10.0 ** int(decimals if decimals is not None and decimals >= 0 else 18)
    limit = int(max_wallets) if max_wallets else 0
    url = f"{BLOCKSCOUT_V2}/tokens/{normalize_address(ca)}/holders"
    params: dict = {"items_count": V2_PAGE_SIZE}
    rows: list[dict] = []
    for _ in range(V2_PAGE_CAP):
        payload = _http_get(url, params=params, timeout=30).json() or {}
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            info = item.get("address") if isinstance(item.get("address"), dict) \
                else {}
            address = str(info.get("hash") or "").strip()
            if not is_robinhood_address(address):
                continue
            balance = _float(item.get("value"), 0.0) / scale
            if balance <= 0:
                continue
            rows.append(_holder_row(
                address, balance, price_usd, supply, pools,
                is_contract=bool(info.get("is_contract")),
                label=str(info.get("name") or ""),
            ))
        if limit and len(rows) >= limit:
            rows = rows[:limit]
            break
        cursor = payload.get("next_page_params")
        if not isinstance(cursor, dict) or not cursor:
            break
        params = dict(cursor)
        params.setdefault("items_count", V2_PAGE_SIZE)
    return rows


def _is_pool_address(address: str, pools: set) -> bool:
    return str(address or "").lower() in pools


def fetch_holders_rpc(ca: str, *, price_usd: float = 0.0, supply: float = 0.0,
                      decimals: int = 18, pools: set | None = None,
                      max_wallets: int | None = None) -> tuple[list[dict], int, bool, str]:
    """Holder via legacy RPC ``getTokenHolders`` — fallback terakhir.

    ``offset`` **wajib <= 400**; nilai lebih besar (versi lama memakai
    1000) dijawab ``{"status":"0","message":"Something went wrong."}``
    sehingga scan pulang tanpa satu pun holder. Halaman setelah data
    habis membalas ``result: []`` — itulah kondisi berhenti.

    Return ``(rows, pages, truncated, error)``.
    """
    pools = pools or set()
    scale = 10.0 ** int(decimals if decimals is not None and decimals >= 0 else 18)
    limit = int(max_wallets or DEFAULT_MAX_WALLETS)
    seen: dict[str, dict] = {}
    pages = 0
    truncated = False
    error = ""
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
        if not rows:
            break
        pages += 1
        for raw in rows:
            if len(seen) >= limit:
                truncated = True
                break
            if not isinstance(raw, dict):
                continue
            addr = normalize_address(raw.get("address"))
            if not addr:
                continue
            balance = _float(raw.get("value")) / scale
            if balance <= 0:
                continue
            seen.setdefault(addr, _holder_row(addr, balance, price_usd,
                                              supply, pools))
        if len(seen) >= limit:
            truncated = True
            break
        if len(rows) < HOLDER_PAGE_SIZE:
            break
        if pages >= HOLDER_PAGE_CAP:
            truncated = True
            break
        # Jeda antar page — Blockscout publik rate-limit-nya cukup keras.
        time.sleep(PAGE_SLEEP_SEC)
        page += 1
    return list(seen.values()), pages, truncated, error


def fetch_holders(ca: str, *, max_wallets: int | None = None,
                  price_usd: float = 0.0, decimals: int | None = None,
                  total_supply: float | None = None) -> dict:
    """Ambil **seluruh** holder ERC-20 di Robinhood Chain dari Blockscout.

    Tiga jalur dicoba berurutan, berhenti pada yang pertama berhasil:

    1. **CSV export** (``source: "blockscout-csv"``) — satu request,
       tanpa paginasi, balance sudah ter-scale decimals. Ini jalur
       "tanpa limit" yang dipakai untuk hampir semua token.
    2. **REST v2 keyset** (``"blockscout-v2"``) — cursor 50/halaman,
       dipakai bila CSV ditolak atau hasilnya jelas terpotong
       (mis. token dengan lebih dari 10.000 holder).
    3. **Legacy RPC** (``"blockscout-rpc"``) — ``offset=400``.

    GMGN **tidak lagi dipakai**: chain 4663 tidak di-index di sana dan
    endpoint holder-nya selalu membalas list kosong.

    Return shape: ``{"holders": [...], "pages", "truncated", "fetched",
    "analyzed_at", "source", "decimals", "error", "holders_count"}``.
    """
    ca = normalize_address(ca)
    if not ca or price_usd <= 0:
        return {"holders": [], "pages": 0, "truncated": False, "fetched": 0,
                "analyzed_at": int(time.time()), "source": SOURCE_CSV,
                "decimals": decimals, "error": "price/address empty"}

    cache_key = f"{ca}:{int(max_wallets or 0)}:{round(float(price_usd), 10)}"
    cached = _HOLDER_CACHE.get(cache_key)
    if cached and (time.time() - cached.get("analyzed_at", 0)) < _HOLDER_CACHE_TTL:
        return dict(cached)

    supply = float(total_supply or 0.0)
    if decimals is None or decimals < 0 or supply <= 0:
        try:
            info = fetch_token_info(ca)
        except Exception as exc:  # noqa: BLE001 - decimals wajib untuk v2/rpc
            info = {}
            token_err = str(exc)
        else:
            token_err = ""
        if decimals is None or decimals < 0:
            decimals = info.get("decimals")
        if supply <= 0:
            supply = float(info.get("total_supply") or 0.0)
    else:
        token_err = ""

    limit = int(max_wallets or DEFAULT_MAX_WALLETS)
    pools: set = set()
    onchain_count = fetch_holders_count(ca)
    errors: list[str] = []
    if token_err:
        errors.append(f"getToken: {token_err}")

    # ---- 1) CSV export: satu request untuk seluruh daftar --------------------
    holders: list[dict] = []
    source = SOURCE_CSV
    pages = 1
    truncated = False
    try:
        holders = fetch_holders_csv(ca, price_usd=price_usd, supply=supply,
                                    pools=pools, max_wallets=max_wallets)
    except Exception as exc:  # noqa: BLE001 - lanjut ke jalur berikutnya
        errors.append(f"csv: {exc}")
        holders = []

    # CSV instance ini sinkron dengan plafon 10.000 baris. Kalau counters
    # bilang holder-nya lebih banyak (dan user memang minta lebih), daftar
    # CSV pasti terpotong -> lengkapi lewat jalur paginasi.
    csv_capped = bool(holders and onchain_count > len(holders)
                      and limit > len(holders))
    if csv_capped:
        errors.append(f"csv terpotong {len(holders)}/{onchain_count}")

    # ---- 2) Legacy RPC: 400 baris/halaman, 8x lebih hemat daripada v2 -------
    # Untuk token besar (85k holder) v2 butuh ~1.700 request sedangkan RPC
    # hanya ~213, jadi RPC yang dicoba lebih dulu saat CSV tidak cukup.
    if (not holders or csv_capped) and decimals is not None and decimals >= 0:
        rpc_rows, rpc_pages, rpc_trunc, rpc_err = fetch_holders_rpc(
            ca, price_usd=price_usd, supply=supply, decimals=_int(decimals, 18),
            pools=pools, max_wallets=max_wallets)
        if rpc_err:
            errors.append(f"rpc: {rpc_err}")
        if len(rpc_rows) > len(holders):
            holders = rpc_rows
            source = SOURCE_RPC
            pages = rpc_pages
            truncated = rpc_trunc

    # ---- 3) REST v2 keyset: paling lambat, tapi cursor-nya tak berbatas ------
    if not holders or (csv_capped and source == SOURCE_CSV):
        try:
            v2_rows = fetch_holders_v2(
                ca, price_usd=price_usd, supply=supply,
                decimals=_int(decimals, 18), pools=pools,
                max_wallets=max_wallets)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"v2: {exc}")
            v2_rows = []
        if len(v2_rows) > len(holders):
            holders = v2_rows
            source = SOURCE_V2
            pages = max(1, -(-len(v2_rows) // V2_PAGE_SIZE))
            truncated = bool(limit and len(v2_rows) >= limit)

    if not holders and (decimals is None or decimals < 0):
        return {
            "holders": [], "pages": 0, "truncated": False, "fetched": 0,
            "analyzed_at": int(time.time()),
            "source": f"{SOURCE_CSV}(fail)",
            "decimals": None, "holders_count": onchain_count,
            "error": "; ".join(errors) or "decimals mint tidak ditemukan",
        }

    if not holders:
        source = f"{SOURCE_CSV}(fail)"
    elif onchain_count and len(holders) < onchain_count and not truncated:
        truncated = bool(limit and len(holders) >= limit)

    result = {
        "holders": holders,
        "pages": pages if holders else 0,
        "truncated": truncated,
        "fetched": len(holders),
        "analyzed_at": int(time.time()),
        "source": source,
        "decimals": decimals,
        "holders_count": onchain_count,
        "error": "; ".join(e for e in errors if e) if not holders else "",
    }
    if holders:
        _HOLDER_CACHE[cache_key] = dict(result)
    return result


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


def scan_token_holders(ca: str, *, max_wallets: int | None = None,
                       include_pools: bool = False) -> dict:
    """Scan on-demand holder satu token Robinhood Chain (EVM, chain 4663).

    Padanan EVM dari ``helius_holders.scan_token_holders`` untuk section
    **Scan Holder Khusus** di halaman utama: alurnya sama —
    market (harga & marketcap) dari DexScreener
    (``chain_id=robinhood``), token info (decimals & supply) dari
    Blockscout, seluruh holder dari :func:`fetch_holders` (CSV export →
    REST v2 → legacy RPC), lalu Wallet Depth by Threshold dari
    ``solscan_holders.wallet_depth``.

    ``include_pools``: bila ``False`` (default) akun LP/pool yang dikenal
    (``pair_addresses`` DexScreener + kontrak yang ditandai Blockscout)
    **disingkirkan dari list/bucket holder** — pool AMM bisa menyerap
    puluhan persen supply dan menyesatkan bucket (sama dengan jalur
    Helius).

    Return dict — **shape-nya sama persis** dengan
    ``helius_holders.scan_token_holders`` sehingga UI Scan Holder Khusus
    dipakai ulang tanpa cabang::

        {
          "market": {...},            # dari get_market (bisa {})
          "snapshot": {...},          # dari fetch_holders
          "depth": {...},             # dari wallet_depth
          "source": str,              # "blockscout-csv" / "blockscout-v2" / …
          "no_helius_keys": False,    # selalu False (tidak butuh key Helius)
          "scan_failed": bool,
        }
    """
    ca = normalize_address(ca)
    market = {}
    try:
        market = get_market(ca, chain_id=DEXSCREENER_CHAIN) or {}
    except Exception:  # noqa: BLE001 - market gagal, lanjut dengan nilai kosong
        market = {}
    price = float(market.get("price_usd") or 0)
    mc = float(market.get("marketcap") or 0)
    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)

    info: dict = {}
    if price > 0:
        try:
            info = fetch_token_info(ca)
        except Exception:  # noqa: BLE001 - info gagal, fetch_holders coba lagi
            info = {}
    decimals = info.get("decimals")
    supply = info.get("total_supply")

    snapshot = fetch_holders(ca, max_wallets=max_wallets, price_usd=price,
                             decimals=decimals, total_supply=supply)
    pools = _known_pools(market)
    snapshot["holders"] = _mark_pools(snapshot.get("holders") or [], pools)
    depth = wallet_depth(snapshot.get("holders") or [], mc,
                         pool_addresses=pools, include_pools=include_pools)
    symbol = str(market.get("symbol")
                 or (info or {}).get("symbol") or "?").upper()
    return {
        "mint": ca,
        "symbol": symbol,
        "market": market,
        "snapshot": snapshot,
        "depth": depth,
        "source": str(snapshot.get("source") or "robinhood"),
        "no_helius_keys": False,
        "scan_failed": bool(not snapshot.get("holders") or price <= 0),
    }


def analyze_token(ca: str, symbol: str = "?", market_cap: float = 0.0,
                  *, dust_limit: float | None = None,
                  max_wallets: int | None = None,
                  fetch_market: bool = True,
                  timeout: int = 25,
                  price_usd: float = 0.0,
                  extra_pools=None,
                  cohort_addrs=None,
                  tracked_wallet_addrs=None,
                  detail: bool = True) -> dict:
    """Analisis holder token Robinhood Chain (Blockscout: CSV → v2 → RPC).

    Menghasilkan bentuk yang sama dengan
    ``holder_analysis.analyze_token`` sehingga seluruh alur watchlist,
    holder_history, dan telegram_alerts dapat dipakai langsung.
    ``detail=False`` (scan 5 menit LP): catat dust/holder saja.
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
    if detail:
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
    else:
        holder_stats["wallet_snapshot"] = {
            "ts": analyzed_at,
            "dust_pct_mc": holder_stats.get("dust_pct_mc"),
            "balances": {}, "dust": [], "wallets_seen": 0, "truncated": False,
        }

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
