# -*- coding: utf-8 -*-
"""Scan pool Meteora DLMM (24 jam + 1 jam) lalu analisa holder dust.

Endpoint: ``pool-discovery-api.datapi.meteora.ag/pools``
- 24h: DLMM, active_tvl >= 1000, fee_active_tvl_ratio >= 250
- 1h : DLMM, active_tvl >= 1000, fee_active_tvl_ratio >= 1

Pool 24 jam yang masih muncul di 1 jam **tetap ditampilkan**. Pool 1 jam
yang belum ada di 24 jam ikut digabung (sama seperti listing Trending).
Setelah fetch holder, pool dengan dust holder **> 0,1% marketcap**
disembunyikan (sejak 2026-09-07; sebelumnya hanya ≥ 1% = BAHAYA). Badge
AMAN/HATI-HATI/BAHAYA **tidak lagi dipakai** di listing ini — yang lolos
sudah pasti ≤ 0,1%. Badge 🏆 BEST POOL (di UI ``app.py``) menambah syarat
data holder valid (≥ 40 wallet) **dan TVL pool ≥ 10K USD**.
Baris yang di-⭐ masuk watchlist terpisah **Chart LP** di dashboard.

**🏆 Scan Best Pool Meteora** (permintaan user 2026-09-10) = replika
listing di atas untuk **halaman utama** dengan filter baru (lihat blok
konstanta ``BEST_*`` di bawah): query API
``pool_type=dlmm&&fee_pct>=5&&active_tvl>=10000`` (timeframe 24 jam,
category top), lalu saringan layar dust holder **< 0,05% MC**, active TVL
**> 10K**, fee/active TVL **> 20%**, volatility **> 5%**, top 10 holder
**< 30%**, dan total LPs **> 20**. Urutannya: **dust % MC terkecil dulu,
lalu volume terbesar** sebagai tie-break — "ambil yang terbesar dan
terbaik".
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from holder_history import DUST_SCAN_HIDE_PCT, dust_flag, should_hide_dust

POOLS_URL = "https://pool-discovery-api.datapi.meteora.ag/pools"
PAGE_SIZE = 50
TVL_MIN = 1000.0
FEE_RATIO_24H = 250.0
FEE_RATIO_1H = 1.0

# ---------------------------------------------------------------------------
# 🏆 Scan Best Pool Meteora (permintaan user 2026-09-10) — ambang filter.
# Dua lapis: ``BEST_FEE_PCT_MIN`` + ``BEST_ACTIVE_TVL_MIN`` ikut dikirim ke
# API Meteora sebagai ``filter_by`` (listing sudah tersaring di server),
# sisanya disaring di layar setelah data pool + holder diambil. Semua angka
# persen API Meteora sudah dalam satuan persen (``fee_active_tvl_ratio``
# 88.56 = 88,56%; ``volatility`` 6.2 = 6,2%; ``top_holders_pct`` 35.75 =
# 35,75% supply di 10 holder teratas token base).
# ---------------------------------------------------------------------------
BEST_CARD_TITLE = "🏆 Scan Best Pool Meteora"
BEST_FEE_PCT_MIN = 5.0            # query API: fee_pct >= 5 (tier fee pool)
BEST_ACTIVE_TVL_MIN = 10_000.0    # query API + layar: active TVL > 10K USD
BEST_DUST_MAX_PCT = 0.05          # layar: dust holder < 0,05% MC
BEST_FEE_RATIO_MIN = 20.0         # layar: fee / active TVL > 20%
BEST_VOLATILITY_MIN = 5.0         # layar: volatility > 5%
BEST_TOP10_MAX_PCT = 30.0         # layar: top 10 holder < 30% supply
BEST_TOTAL_LPS_MIN = 20.0         # layar: total LPs > 20
# Presisi kunci urut dust % MC di listing Best Pool — sama dengan angka yang
# tampil di card, jadi dua pool yang di layar sama-sama "0,041%" benar-benar
# dianggap seri dan **volume terbesar** yang menentukan urutannya.
BEST_DUST_SORT_DECIMALS = 3

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
        # Metrik tambahan untuk 🏆 Scan Best Pool Meteora (2026-09-10):
        # volatility pool (%), jumlah LP total, dan konsentrasi 10 holder
        # teratas token base (% supply, dari pool-discovery API).
        "volatility": _float(pool.get("volatility")),
        "total_lps": _float(pool.get("total_lps")),
        "top_holders_pct": _float(token.get("top_holders_pct")),
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


def row_dust_pct(row: dict | None):
    """Dust % MC satu baris pool: ``analysis`` dulu, fallback field baris.

    Dipakai bersama oleh :func:`hide_dust_limit`, :func:`row_flag`, dan
    ``app._render_meteora_scan`` supaya angka yang menyaring, mengurutkan,
    dan yang tampil di layar **selalu** berasal dari sumber yang sama.
    """
    row = row or {}
    pct = ((row.get("analysis") or {}).get("holders") or {}).get("dust_pct_mc")
    if pct is None:
        pct = row.get("dust_pct_mc")
    return pct


def row_flag(row: dict | None) -> dict:
    """``dust_flag`` satu baris pool lengkap dengan guard holder + TVL.

    ``best`` hanya True bila dust < 0,1% MC, data holder valid (≥ 40 wallet),
    dan TVL pool ≥ 10K USD — persis syarat badge 🏆 BEST POOL di UI.
    """
    row = row or {}
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    holders = (analysis.get("holders")
               if isinstance(analysis.get("holders"), dict) else None)
    return dust_flag(row_dust_pct(row), holders=holders, tvl=row.get("tvl"))


def sort_rows(rows: list[dict]) -> list[dict]:
    """Urutkan listing Scan Meteora: **BEST POOL dulu**, lalu yang lain.

    Permintaan user 2026-09-08: badge 🏆 BEST POOL tidak lagi tersebar acak
    mengikuti urutan API Meteora — pool terbaik harus tampil paling atas.

    Kunci urut (kecil = atas):

    1. ``best`` (BEST POOL) di atas non-best;
    2. dust % MC **terkecil** dulu — makin sedikit dust makin bersih;
       baris tanpa angka dust (holder gagal) ditaruh paling bawah karena
       tidak ada bukti dan tidak pernah bisa jadi BEST POOL;
    3. TVL **terbesar** dulu sebagai tie-break (likuiditas lebih tebal);
    4. simbol alfabetis supaya urutannya deterministik (stabil antar scan).
    """
    def _key(row):
        row = row or {}
        pct = _float(row_dust_pct(row), None)
        tvl = _float(row.get("tvl"), 0.0)
        return (
            0 if row_flag(row).get("best") else 1,
            0 if pct is not None else 1,
            pct if pct is not None else 0.0,
            -tvl,
            str(row.get("symbol") or "").upper(),
        )

    return sorted(list(rows or []), key=_key)


def hide_dust_limit(rows: list[dict]) -> tuple[list[dict], int]:
    """Buang pool dust > ``DUST_SCAN_HIDE_PCT`` (0,1% MC). Return (kept, n_hidden).

    Dust ``None`` (holder gagal di-fetch) tetap ditampilkan tanpa angka —
    tidak ada bukti dust, tetapi juga tidak akan mendapat BEST POOL.
    """
    kept, hidden = [], 0
    for row in rows or []:
        if should_hide_dust(row_dust_pct(row)):
            hidden += 1
            continue
        kept.append(row)
    return kept, hidden


def scan_meteora(*, max_wallets: int | None = None, workers: int = 6,
                 progress=None, timeout: int = 25) -> dict:
    """Listing + holder + filter dust > 0,1% MC (``DUST_SCAN_HIDE_PCT``)."""
    # Default FULL (holder_history.FULL_SCAN_MAX_WALLETS): urutan
    # getTokenAccounts Helius tidak urut saldo → cap kecil menghasilkan
    # sampel acak yang bias (dust ≤$10 kurang terhitung) dan filter
    # ``DUST_SCAN_HIDE_PCT`` bisa salah menyembunyikan/menampilkan pool.
    if max_wallets is None:
        from holder_history import FULL_SCAN_MAX_WALLETS
        max_wallets = FULL_SCAN_MAX_WALLETS
    rows, error = fetch_listing(timeout=timeout)
    fetched = len(rows)
    if rows:
        rows = enrich_pools(rows, max_wallets=max_wallets, workers=workers,
                            progress=progress)
        rows, hidden = hide_dust_limit(rows)
        # BEST POOL di urutan teratas (permintaan user 2026-09-08); urutan
        # mentah dari API Meteora menyebar pool terbaik ke tengah listing.
        rows = sort_rows(rows)
    else:
        hidden = 0
    return {
        "rows": rows,
        "error": error,
        "fetched": fetched,
        "hidden_dust": hidden,
        "hide_pct": float(DUST_SCAN_HIDE_PCT),
        "best_count": sum(1 for row in rows if row_flag(row).get("best")),
        "analyzed_at": int(time.time()),
    }


# ---------------------------------------------------------------------------
# 🏆 Scan Best Pool Meteora — replika listing untuk halaman utama ``app.py``
# (permintaan user 2026-09-10). Dua lapis saringan:
#
# 1. **server** (query API Meteora, sama seperti filter UI Meteora):
#    ``pool_type=dlmm&&fee_pct>=5&&active_tvl>=10000``, timeframe 24 jam,
#    category ``top``;
# 2. **layar** (setelah data pool + holder ada): dust holder < 0,05% MC,
#    active TVL > 10K USD, fee/active TVL > 20%, volatility > 5%, top 10
#    holder < 30% supply, total LPs > 20.
#
# Urutan baris: **dust % MC terkecil dulu, lalu volume terbesar** sebagai
# tie-break — "ambil yang terbesar dan terbaik" (permintaan user 2026-09-10).
# Data yang hilang (``None``) selalu menggugurkan baris: card ini menjual
# bukti, jadi pool tanpa angka tidak ikut ditampilkan.
# ---------------------------------------------------------------------------
def _maybe_float(value):
    """Float atau ``None`` (NaN/bool/tipe salah → ``None``).

    Berbeda dari :func:`_float` yang menelan ``None`` jadi 0: saringan Best
    Pool harus bisa membedakan "angkanya nol" dari "datanya tidak ada".
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num == num else None


def best_filter_by(pool_type: str = "dlmm",
                   fee_pct_min: float = BEST_FEE_PCT_MIN,
                   active_tvl_min: float = BEST_ACTIVE_TVL_MIN) -> str:
    """Query ``filter_by`` Scan Best Pool Meteora (&&-join ala UI Meteora).

    Hasil default: ``pool_type=dlmm&&fee_pct>=5&&active_tvl>=10000``.
    """
    def _num(value: float) -> str:
        number = float(value)
        return str(int(number)) if number == int(number) else f"{number:g}"

    return (f"pool_type={pool_type}"
            f"&&fee_pct>={_num(fee_pct_min)}"
            f"&&active_tvl>={_num(active_tvl_min)}")


def fetch_best_pools(*, timeframe: str = "24h", page_size: int = PAGE_SIZE,
                     fee_pct_min: float = BEST_FEE_PCT_MIN,
                     active_tvl_min: float = BEST_ACTIVE_TVL_MIN,
                     timeout: int = 25) -> list[dict]:
    """Top pool 24 jam untuk Scan Best Pool Meteora. Gagal → raise."""
    params = {
        "page_size": max(1, min(int(page_size), 50)),
        "timeframe": str(timeframe or "24h"),
        "category": "top",
        "filter_by": best_filter_by(fee_pct_min=fee_pct_min,
                                    active_tvl_min=active_tvl_min),
    }
    payload = _http_get(POOLS_URL, params, timeout=timeout)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def rows_from_pools(pools: list[dict] | None) -> list[dict]:
    """Baris listing (dedup ``pool_address``) dari payload pool-discovery."""
    rows: list[dict] = []
    seen: set[str] = set()
    for pool in pools or []:
        if not isinstance(pool, dict):
            continue
        row = _row_from_pool(pool, in_24h=True, in_1h=False)
        addr = row["pool_address"]
        if addr:
            if addr in seen:
                continue
            seen.add(addr)
        rows.append(row)
    return rows


def row_best_gaps(row: dict | None) -> list[str]:
    """Label syarat **metrik pool** yang tidak dipenuhi (kosong = lolos).

    Lima syarat yang datanya sudah ada di response pool-discovery —
    dijalankan SEBELUM fetch holder supaya kuota Helius tidak terbakar
    untuk pool yang pasti gugur. Dust holder dicek terpisah oleh
    :func:`row_dust_ok` karena butuh analisa holder.
    """
    row = row or {}
    gaps: list[str] = []
    active = _maybe_float(row.get("active_tvl"))
    if active is None or active <= BEST_ACTIVE_TVL_MIN:
        gaps.append(f"active TVL ≤ ${BEST_ACTIVE_TVL_MIN / 1000:g}K")
    ratio = _maybe_float(row.get("fee_active_tvl_ratio"))
    if ratio is None or ratio <= BEST_FEE_RATIO_MIN:
        gaps.append(f"fee/active TVL ≤ {BEST_FEE_RATIO_MIN:g}%")
    volatility = _maybe_float(row.get("volatility"))
    if volatility is None or volatility <= BEST_VOLATILITY_MIN:
        gaps.append(f"volatility ≤ {BEST_VOLATILITY_MIN:g}%")
    top10 = _maybe_float(row.get("top_holders_pct"))
    if top10 is None or top10 >= BEST_TOP10_MAX_PCT:
        gaps.append(f"top 10 holder ≥ {BEST_TOP10_MAX_PCT:g}%")
    lps = _maybe_float(row.get("total_lps"))
    if lps is None or lps <= BEST_TOTAL_LPS_MIN:
        gaps.append(f"total LPs ≤ {BEST_TOTAL_LPS_MIN:g}")
    return gaps


def row_dust_ok(row: dict | None) -> bool:
    """True bila dust holder **< 0,05% MC** (angka wajib ada).

    Lebih ketat dari ``DUST_SCAN_HIDE_PCT`` (0,1%): listing Best Pool hanya
    memuat pool dengan distribusi holder yang benar-benar bersih. Dust
    ``None`` (holder gagal di-fetch) **tidak** lolos — tidak ada bukti.
    """
    pct = _maybe_float(row_dust_pct(row))
    return bool(pct is not None and pct < BEST_DUST_MAX_PCT)


def filter_best_rows(rows: list[dict] | None) -> tuple[list[dict], int, int]:
    """Terapkan semua saringan layar. Return (kept, hidden_metric, hidden_dust)."""
    kept: list[dict] = []
    hidden_metric = hidden_dust = 0
    for row in rows or []:
        if row_best_gaps(row):
            hidden_metric += 1
            continue
        if not row_dust_ok(row):
            hidden_dust += 1
            continue
        kept.append(row)
    return kept, hidden_metric, hidden_dust


def sort_best_rows(rows: list[dict] | None) -> list[dict]:
    """Urutan listing Best Pool: **dust % MC terkecil**, lalu **volume terbesar**.

    Permintaan user 2026-09-10: setelah % dust terkecil, pool bervolume
    terbesar naik — supaya yang teratas adalah pool "terbesar dan terbaik".
    Kunci dust dibulatkan ke presisi tampilan
    (:data:`BEST_DUST_SORT_DECIMALS`, 3 desimal = angka yang muncul di card),
    jadi pool yang di layar sama-sama "0,041%" dianggap seri dan **volume
    terbesar** yang menentukan urutannya. Baris tanpa angka dust (holder
    gagal) ditaruh paling bawah, lalu simbol alfabetis sebagai tie-break
    terakhir supaya urutan deterministik antar scan.
    """
    def _key(row):
        row = row or {}
        pct = _maybe_float(row_dust_pct(row))
        volume = _float(row.get("volume"), 0.0)
        return (
            0 if pct is not None else 1,
            round(pct, BEST_DUST_SORT_DECIMALS) if pct is not None else 0.0,
            -volume,
            str(row.get("symbol") or "").upper(),
        )

    return sorted(list(rows or []), key=_key)


def scan_best_meteora(*, max_wallets: int | None = None, workers: int = 6,
                      progress=None, timeout: int = 25,
                      timeframe: str = "24h",
                      page_size: int = PAGE_SIZE) -> dict:
    """Listing 24 jam + holder + 6 saringan layar Scan Best Pool Meteora.

    Saringan metrik pool jalan lebih dulu (data API), baru holder di-fetch
    untuk sisanya — jadi 5 syarat yang tidak butuh Helius tidak membakar
    kuota. Urutan hasil: dust % MC terkecil → volume terbesar.
    """
    # Default FULL seperti ``scan_meteora``: urutan getTokenAccounts Helius
    # tidak urut saldo, jadi cap kecil menghasilkan sampel bias dan angka
    # dust < 0,05% MC tidak bisa dipercaya.
    if max_wallets is None:
        from holder_history import FULL_SCAN_MAX_WALLETS
        max_wallets = FULL_SCAN_MAX_WALLETS
    try:
        pools = fetch_best_pools(timeframe=timeframe, page_size=page_size,
                                 timeout=timeout)
        error = ""
    except Exception as exc:  # noqa: BLE001 - kegagalan API jadi pesan card
        pools, error = [], str(exc)
    rows = rows_from_pools(pools)
    candidates = [row for row in rows if not row_best_gaps(row)]
    hidden_metric = len(rows) - len(candidates)
    if candidates:
        candidates = enrich_pools(candidates, max_wallets=max_wallets,
                                  workers=workers, progress=progress)
    kept, _, hidden_dust = filter_best_rows(candidates)
    kept = sort_best_rows(kept)
    return {
        "rows": kept,
        "error": error,
        "fetched": len(rows),
        "hidden_metric": hidden_metric,
        "hidden_dust": hidden_dust,
        "analyzed_at": int(time.time()),
    }
