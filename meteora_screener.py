# -*- coding: utf-8 -*-
"""Scan regular pool Meteora DLMM (24 jam + 30 menit) lalu analisa holder dust.

Endpoint: ``pool-discovery-api.datapi.meteora.ag/pools``. Regular scan
mengambil dua lane secara berurutan: ``24h`` terlebih dahulu, lalu ``30m``.
Keduanya memakai ``pool_type=dlmm`` dan ``active_tvl >= 50K``; klasifikasi
berdasarkan metrik yang dikirim API, bukan threshold fee buatan di client:

- 24h: pool disembunyikan bila ``volatility >= fee_active_tvl_ratio``;
  pool dengan ``fee_active_tvl_ratio >= 5 × volatility`` diberi label **SAFE LP**
  dan catatan, sedangkan pool lain yang masih fee-dominant tetap dicatat;
- 30m: hanya pool dengan ``fee_active_tvl_ratio > volatility`` yang ditampilkan
  sebagai **HIGH RISK LP (PANTAU)**.

Urutan regular scan tidak memakai dust. Lane 24h tetap berada di atas lane 30m,
lalu pool di dalam masing-masing lane diurutkan dari perbandingan terbesar
``fee_active_tvl_ratio / volatility``. Dust holder tetap diperkaya dan dicatat
sebagai data saja.

**Dust %MC kartu ini memakai pembagi yang sama dengan kartu lain** (2026-09-13):
market cap dan harga diambil dari **DexScreener** lewat
``holder_analysis.analyze_token`` — angka listing Meteora (``market_cap or
fdv``) hanya cadangan bila DexScreener tidak membalas. Sebelumnya MC Meteora
yang menang, jadi Scan Meteora dan Scan Holder bisa menampilkan dua angka dust
%MC berbeda untuk token yang sama (dan titik history yang ditulis scan pool
tidak sebanding dengan titik cron). **Hasil scan holder tanpa bukti tidak
pernah tampil sebagai 0,000%**: fetch gagal / 0 wallet / terpotong / sampel
< 40 wallet → ``dust_pct_mc = None`` (``row_dust_pct``), barisnya diberi
``holders_note``, dan listing pool **quote-only** (SOL/USDC/USDT, tanpa sisi
memecoin — dust-nya dihitung terhadap MC SOL, jadi selalu “0,000%”) dibuang
sebelum fetch holder.
Setelah fetch holder, pool dengan dust holder **> 0,1% marketcap**
disembunyikan (sejak 2026-09-07; sebelumnya hanya ≥ 1% = BAHAYA). Badge
AMAN/HATI-HATI/BAHAYA **tidak lagi dipakai** di listing ini — yang lolos
sudah pasti ≤ 0,1%. Badge 🏆 BEST POOL (di UI ``app.py``) menambah syarat
data holder valid (≥ 40 wallet) **dan TVL pool ≥ 10K USD**.
Baris yang di-⭐ masuk watchlist terpisah **Chart LP** di dashboard.

**🏆 Scan Best Pool Meteora** — kriteria diganti total 2026-09-11 (lihat
blok konstanta ``BEST_*`` di bawah): listing API Meteora 24 jam
``pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000`` (category ``top``,
page_size 50), jadi **tier fee** dan **active TVL** sudah disaring di
server. Saringan layar tinggal tiga: dust holder **< 0,05% MC**,
volatility **>= 2%** ("minimal 2%"), dan **volume 24 jam >= 1 juta USD**
(``BEST_VOLUME_24H_MIN``, permintaan user 2026-09-12: "minimal volume 24
jam adalah 1M, dibawah itu jangan di show"). Urutannya: **volume 24 jam /
active TVL** (``volume_active_tvl_ratio``) terbesar → **dust % MC terkecil**
(sejak 2026-09-13; sebelumnya kenaikan volume 24 jam dulu, dan sebelum itu
dust dulu — permintaan user: "sort pertama adalah dari volume / active tvl
yang paling besar dulu, lalu dari %dust yang paling kecil"). Saringan lama active TVL > 10K,
fee/active TVL > 20%, top 10 holder < 30%, dan total LPs > 20 **dihapus**
(ambang volatility lama 5% turun jadi 2%); datanya tetap dibawa dan tetap
ditampilkan di tabel sebagai informasi.

Baris dengan dust **<= 0,035% MC** (``BEST_DUST_MARK_PCT``,
:func:`row_best_pool`, 2026-09-12) ditandai chip **🏆 BEST POOL** di kolom
Dust %MC — penanda murni visual, bukan saringan (saringan tetap 0,05%).
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from holder_history import (DUST_SCAN_HIDE_PCT, MIN_USABLE_WALLETS, dust_flag,
                            holders_usable, should_hide_dust)

POOLS_URL = "https://pool-discovery-api.datapi.meteora.ag/pools"
PAGE_SIZE = 50
# Regular Scan Meteora mengikuti filter listing yang diminta: active TVL
# minimal 50K. Nilai fee minimum tidak dipakai sebagai filter server karena
# keputusan tampil/klasifikasi harus dibuat dari perbandingan fee dan
# volatility payload untuk setiap lane.
TVL_MIN = 50_000.0
FEE_RATIO_24H = 0.0
FEE_RATIO_30M = 0.0
# Alias lama dipertahankan agar import/test konsumen lama tidak pecah; regular
# scan tidak lagi mengambil 1h.
FEE_RATIO_1H = FEE_RATIO_30M
REGULAR_TIMEFRAMES = ("24h", "30m")
SAFE_LP_MULTIPLIER = 5.0

# ---------------------------------------------------------------------------
# 🏆 Scan Best Pool Meteora — ambang filter (kriteria diganti total
# 2026-09-11 sesuai request UI Meteora). Dua lapis: ``BEST_FEE_PCT_MIN`` +
# ``BEST_ACTIVE_TVL_MIN`` ikut dikirim ke API Meteora sebagai ``filter_by``
# (listing sudah tersaring di server, tidak diulang di layar), sisanya
# disaring di layar setelah data pool diambil. Semua angka persen API
# Meteora sudah dalam satuan persen (``fee_active_tvl_ratio`` 88.56 =
# 88,56%; ``volatility`` 6.2 = 6,2%; ``volume_change_pct`` 13.24 = +13,24%;
# ``top_holders_pct`` 35.75 = 35,75% supply di 10 holder teratas token base).
# ---------------------------------------------------------------------------
BEST_CARD_TITLE = "🏆 Scan Best Pool Meteora"
BEST_FEE_PCT_MIN = 2.0            # query API: fee_pct >= 2 (tier fee pool)
BEST_ACTIVE_TVL_MIN = 50_000.0    # query API: active TVL >= 50K USD
BEST_DUST_MAX_PCT = 0.05          # layar: dust holder < 0,05% MC
BEST_VOLATILITY_MIN = 2.0         # layar: volatility >= 2% ("minimal 2%")
# Layar: **volume 24 jam minimal 1 juta USD** (permintaan user 2026-09-12:
# "minimal volume 24 jam adalah 1M, dibawah itu jangan di show"). Batas
# inklusif (tepat $1.000.000 lolos); angka hilang (``None``) = gugur, sama
# seperti volatility — pool tanpa data volume tidak bisa dibuktikan ramai.
# Dicek di :func:`row_best_gaps`, jadi SEBELUM fetch holder: kuota Helius
# tidak terbakar untuk pool sepi yang pasti gugur.
BEST_VOLUME_24H_MIN = 1_000_000.0
# Tanda 🏆 BEST POOL di kolom Dust %MC (permintaan user 2026-09-12): baris
# dengan dust **<= 0,035% MC** (inklusif — 0,035 persis ikut ditandai)
# diberi chip emas di ``best_pool_ui``. Ini BUKAN saringan tambahan: saringan
# layar tetap ``BEST_DUST_MAX_PCT`` (0,05%, lebih longgar); tanda hanya
# memudahkan melihat pool yang benar-benar bersih di dalam listing.
BEST_DUST_MARK_PCT = 0.035
# Presisi kunci urut dust % MC di listing Best Pool — sama dengan angka yang
# tampil di card, jadi dua pool yang di layar sama-sama "0,041%" benar-benar
# dianggap seri dan simbol alfabetis yang menentukan (lihat
# :func:`sort_best_rows`). Dust adalah kunci urut KEDUA (sejak 2026-09-13;
# kunci pertamanya **volume 24 jam / active TVL** — sebelumnya kenaikan
# volume 24 jam, dan sebelum itu dust).
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
              fee_ratio_min: float | None = None) -> str:
    """Query ``filter_by`` persis seperti UI Meteora (&&-join).

    ``fee_ratio_min=None`` sengaja tidak menambahkan filter fee: regular scan
    harus melihat seluruh payload lalu menerapkan rule fee-versus-volatility
    yang berbeda untuk lane 24h dan 30m.
    """
    text = (f"pool_type={pool_type}"
            f"&&active_tvl>={int(tvl_min) if tvl_min == int(tvl_min) else tvl_min}")
    if fee_ratio_min is not None:
        text += f"&&fee_active_tvl_ratio>={float(fee_ratio_min):g}"
    return text


def fetch_pools(*, timeframe: str = "24h",
                fee_ratio_min: float | None = None,
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


def unanalysable_row(row: dict | None) -> str:
    """Alasan baris **tidak punya token base** yang bisa di-analisa (kosong = bisa).

    ``base_token()`` mengembalikan ``token_x or token_y`` bila kedua sisi pool
    adalah token quote (SOL / USDC / USDT) — pool semacam ini tidak punya sisi
    memecoin sama sekali (USDT-USDC, SOL-USDC, SOL-USDT). Holder yang di-scan
    lalu = holder SOL/USDC dan MC pembaginya = MC SOL (miliaran dolar), jadi
    dust % MC-nya **selalu** ≈ 0,000% — pool "paling bersih" di listing dan
    langsung menyabet 🏆 BEST POOL, padahal angkanya tidak pernah berarti apa
    apa untuk token itu. Baris tanpa mint sama sekali juga dibuang.
    """
    row = row or {}
    mint = str(row.get("ca") or "").strip()
    if not mint:
        return "mint token base tidak terbaca"
    if mint in QUOTE_MINTS:
        return "pool quote-only (SOL/USDC/USDT, tanpa sisi memecoin)"
    return ""


def drop_quote_rows(rows: list[dict] | None) -> tuple[list[dict], int]:
    """Buang baris yang tidak punya token base untuk di-analisa.

    Return ``(kept, dropped)``. Dipakai **sebelum** fetch holder supaya kuota
    Helius tidak terbakar untuk pool yang angkanya pasti tidak bermakna.
    """
    kept, dropped = [], 0
    for row in rows or []:
        if unanalysable_row(row):
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped


def fee_volatility_ratio(fee_active_tvl_ratio, volatility):
    """Perbandingan fee/active TVL terhadap volatility.

    Kedua field Meteora sudah berupa persen, jadi yang dibandingkan untuk
    urutan dan deteksi adalah quotient-nya, bukan nilai dust. ``None`` berarti
    payload tidak cukup; volatility nol dengan fee positif dianggap tak
    terbatas karena fee tetap dominan.
    """
    fee = _maybe_float(fee_active_tvl_ratio)
    vol = _maybe_float(volatility)
    if fee is None or vol is None:
        return None
    if vol == 0:
        return float("inf") if fee > 0 else 0.0
    return fee / vol


def regular_pool_classification(row: dict | None) -> dict:
    """Classify/filter satu regular row tanpa menyentuh dust.

    Return ``{show, label, note, ratio}``. Rule memakai perbandingan strict
    untuk filter (``volatility >= fee`` disembunyikan di 24h; ``fee <=
    volatility`` disembunyikan di 30m) dan ``>= 5×`` untuk SAFE LP 24h.
    """
    row = row or {}
    timeframe = str(row.get("timeframe") or row.get("source") or "24h").lower()
    if timeframe in ("1h", "30 menit", "30 min"):
        timeframe = "30m"
    elif timeframe in ("24 jam", "24 hours"):
        timeframe = "24h"
    fee = _maybe_float(row.get("fee_active_tvl_ratio"))
    volatility = _maybe_float(row.get("volatility"))
    ratio = fee_volatility_ratio(fee, volatility)
    if fee is None or volatility is None:
        return {"show": False, "label": "", "note":
                "metrik fee_active_tvl_ratio/volatility tidak tersedia",
                "ratio": ratio, "timeframe": timeframe}
    if timeframe == "30m":
        if not fee > volatility:
            return {"show": False, "label": "", "note":
                    "30m disembunyikan: volatility ≥ fee_active_tvl_ratio",
                    "ratio": ratio, "timeframe": timeframe}
        return {"show": True, "label": "HIGH RISK LP (PANTAU)",
                "note": "30m: fee_active_tvl_ratio > volatility — pantau risiko",
                "ratio": ratio, "timeframe": timeframe}
    if volatility >= fee:
        return {"show": False, "label": "", "note":
                "24h disembunyikan: volatility ≥ fee_active_tvl_ratio",
                "ratio": ratio, "timeframe": "24h"}
    if fee >= SAFE_LP_MULTIPLIER * volatility:
        return {"show": True, "label": "SAFE LP",
                "note": ("24h: fee_active_tvl_ratio ≥ 5× volatility — "
                         "SAFE LP"),
                "ratio": ratio, "timeframe": "24h"}
    return {"show": True, "label": "LP 24H",
            "note": ("24h: fee_active_tvl_ratio > volatility, tetapi belum "
                     "5× untuk SAFE LP"),
            "ratio": ratio, "timeframe": "24h"}


def filter_regular_rows(rows: list[dict] | None) -> tuple[list[dict], int]:
    """Terapkan rule lane regular; return ``(kept, hidden_rule_count)``."""
    kept, hidden = [], 0
    for row in rows or []:
        classification = regular_pool_classification(row)
        item = dict(row or {})
        item.update({
            "classification": classification.get("label") or "",
            "classification_note": classification.get("note") or "",
            "fee_volatility_ratio": classification.get("ratio"),
            "fee_active_tvl_ratio_vs_volatility": classification.get("ratio"),
        })
        if not classification.get("show"):
            hidden += 1
            continue
        kept.append(item)
    return kept, hidden


def sort_regular_rows(rows: list[dict] | None) -> list[dict]:
    """Order regular rows by lane then fee/volatility ratio, never by dust."""
    def _key(row):
        row = row or {}
        timeframe = str(row.get("timeframe") or row.get("source") or "24h").lower()
        if timeframe == "1h":
            timeframe = "30m"
        ratio = fee_volatility_ratio(row.get("fee_active_tvl_ratio"),
                                     row.get("volatility"))
        # Keep missing metrics at the bottom of their lane. ``sort_rows`` is
        # intentionally not used here; dust is only a recorded field.
        rank = 0 if timeframe == "24h" else 1
        return (rank, 0 if ratio is not None else 1,
                -(ratio if ratio is not None else 0.0),
                str(row.get("symbol") or "").upper(),
                str(row.get("pool_address") or ""))
    return sorted(list(rows or []), key=_key)


def _row_from_pool(pool: dict, *, timeframe: str = "24h",
                    in_24h: bool | None = None,
                    in_1h: bool | None = None) -> dict:
    """Normalisasi satu payload pool dan bawa metrik regular apa adanya.

    ``in_1h`` tetap diterima sebagai compatibility kwarg untuk konsumen lama;
    regular scan sekarang menggunakan ``timeframe`` ``24h`` atau ``30m``.
    """
    token = base_token(pool)
    mint = str(token.get("address") or "").strip()
    timeframe = str(timeframe or ("24h" if in_24h else "30m")).lower()
    if timeframe == "1h":
        timeframe = "30m"
    is_24h = timeframe == "24h" if in_24h is None else bool(in_24h)
    is_30m = timeframe == "30m" if in_1h is None else bool(in_1h)
    fee_ratio = _maybe_float(pool.get("fee_active_tvl_ratio"))
    volatility = _maybe_float(pool.get("volatility"))
    return {
        "pool_address": str(pool.get("pool_address") or "").strip(),
        "pool_name": str(pool.get("name") or ""),
        "pool_type": str(pool.get("pool_type") or "dlmm"),
        "ca": mint,
        "symbol": str(token.get("symbol") or pool.get("name") or "?").upper(),
        "name": str(token.get("name") or ""),
        # Cadangan pembagi dust saja — angka yang dipakai di layar datang dari
        # :func:`enrich_pools` (MC DexScreener, sama seperti kartu lain).
        "mc": _float(token.get("market_cap") or token.get("fdv")),
        "price": _float(token.get("price")),
        "holders_reported": token.get("holders"),
        "tvl": _float(pool.get("tvl")),
        "active_tvl": _maybe_float(pool.get("active_tvl")),
        "fee_active_tvl_ratio": fee_ratio,
        "volume": _float(pool.get("volume")),
        "fee_pct": _float(pool.get("fee_pct")),
        # Metrik pool dipakai regular scan + watchlist. Best Pool tetap
        # memakai field ini sebagai informasi dan pipeline-nya tidak berubah.
        "volatility": volatility,
        "total_lps": _float(pool.get("total_lps")),
        "top_holders_pct": _float(token.get("top_holders_pct")),
        "fee": _float(pool.get("fee")),
        "volume_change_pct": _float(pool.get("volume_change_pct")),
        "volume_active_tvl_ratio": _maybe_float(pool.get("volume_active_tvl_ratio")),
        # Source/timeframe wajib ikut ke hasil scan dan ke watchlist.
        "timeframe": timeframe,
        "source": timeframe,
        "in_24h": bool(is_24h),
        "in_30m": bool(is_30m),
        # Alias lama hanya untuk pembacaan session/test lama; tidak dipakai
        # sebagai lane baru dan tidak mengubah Scan Best Pool.
        "in_1h": bool(is_30m),
        "fee_volatility_ratio": fee_volatility_ratio(fee_ratio, volatility),
        "fee_active_tvl_ratio_vs_volatility": fee_volatility_ratio(
            fee_ratio, volatility),
        "analysis": None,
    }


def _regular_rows_from_lanes(pools_24h, pools_30m) -> list[dict]:
    """Catat lane 24h lalu 30m tanpa menggabungkan source yang berbeda.

    Satu pool yang muncul di dua timeframe sengaja menjadi dua record: rule
    24h (SAFE/fee-dominant) dan rule 30m (HIGH RISK) punya arti berbeda dan
    keduanya harus terlihat oleh user.
    """
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for timeframe, pools in (("24h", pools_24h), ("30m", pools_30m)):
        for pool in pools or []:
            row = _row_from_pool(pool, timeframe=timeframe)
            address = row["pool_address"]
            key = (timeframe, address or f"{timeframe}:{len(rows)}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def merge_pools(pools_24h, pools_1h, *, preserve_lanes: bool = False) -> list[dict]:
    """Merge compatibility helper; regular fetch keeps 24h before 30m.

    ``preserve_lanes=True`` is the new regular behavior: rows are not
    deduplicated across timeframes. The default retains the historical merged
    shape for external callers that still use ``merge_pools`` directly.
    """
    if preserve_lanes:
        return _regular_rows_from_lanes(pools_24h, pools_1h)

    # Compatibility shape for old callers: one row per pool address, with the
    # first (24h) payload winning and the second lane marked on that row.
    by_addr: dict[str, dict] = {}
    order: list[str] = []
    for pool in pools_24h or []:
        row = _row_from_pool(pool, timeframe="24h", in_24h=True,
                             in_1h=False)
        addr = row["pool_address"]
        if not addr or addr in by_addr:
            continue
        by_addr[addr] = row
        order.append(addr)
    for pool in pools_1h or []:
        row = _row_from_pool(pool, timeframe="30m", in_24h=False,
                             in_1h=True)
        addr = row["pool_address"]
        if not addr:
            continue
        if addr in by_addr:
            by_addr[addr]["in_30m"] = True
            by_addr[addr]["in_1h"] = True
            by_addr[addr]["source_timeframes"] = ["24h", "30m"]
            continue
        by_addr[addr] = row
        order.append(addr)
    for addr in order:
        by_addr[addr].setdefault("source_timeframes", [
            by_addr[addr].get("timeframe") or ("24h" if by_addr[addr].get("in_24h")
                                                else "30m")])
    return [by_addr[addr] for addr in order]


def fetch_listing(*, timeout: int = 25) -> tuple[list[dict], str]:
    """Return raw regular rows in lane order: 24h first, then 30m."""
    errors = []
    pools_24: list[dict] = []
    pools_30: list[dict] = []
    try:
        pools_24 = fetch_pools(timeframe="24h", fee_ratio_min=None,
                               tvl_min=TVL_MIN, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"24h: {exc}")
    try:
        pools_30 = fetch_pools(timeframe="30m", fee_ratio_min=None,
                               tvl_min=TVL_MIN, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"30m: {exc}")
    rows = _regular_rows_from_lanes(pools_24, pools_30)
    return rows, " · ".join(errors)


def fetch_watchlist_metric_snapshots(watchlist: dict | None,
                                     *, timeout: int = 25) -> dict:
    """Fetch current fee/volatility snapshots for Meteora watchlist entries.

    Holder scanning and pool-metric scanning are intentionally separate: this
    helper only calls the lightweight pool-discovery endpoint. A pool address
    stored when the star was clicked is preferred; mint matching is the
    fallback for older watchlist entries that predate source metadata.
    """
    from meteora_watchlist import (is_meteora_meta, snapshot_from_row,
                                   timeframe_for_meta)

    targets: dict[str, dict] = {
        str(mint): meta for mint, meta in (watchlist or {}).items()
        if mint and is_meteora_meta(meta)
    }
    if not targets:
        return {}
    requested = {timeframe_for_meta(meta) for meta in targets.values()}
    requested = [timeframe for timeframe in REGULAR_TIMEFRAMES
                 if timeframe in requested]
    pools_by_timeframe: dict[str, list[dict]] = {}
    for timeframe in requested:
        try:
            pools_by_timeframe[timeframe] = fetch_pools(
                timeframe=timeframe, fee_ratio_min=None,
                tvl_min=TVL_MIN, timeout=timeout)
        except Exception:
            pools_by_timeframe[timeframe] = []

    result: dict[str, dict] = {}
    for mint, meta in targets.items():
        timeframe = timeframe_for_meta(meta)
        candidates = []
        for pool in pools_by_timeframe.get(timeframe) or []:
            row = _row_from_pool(pool, timeframe=timeframe)
            if row.get("ca") == mint:
                candidates.append(row)
        pool_address = str(meta.get("pool_address") or "").strip()
        selected = next((row for row in candidates
                         if pool_address and row.get("pool_address") == pool_address),
                        candidates[0] if candidates else None)
        if selected:
            classification = regular_pool_classification(selected)
            selected = dict(selected)
            selected["classification"] = classification.get("label") or ""
            selected["classification_note"] = classification.get("note") or ""
            result[mint] = snapshot_from_row(selected)
    return result


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
    """Fetch holder per mint unik, tempel ``analysis`` ke setiap baris pool.

    Angka dust yang ditulis ke baris **hanya** dipakai bila hasil fetch
    holdernya bisa dipercaya (:func:`holder_history.holders_usable`): scan
    dengan 0 wallet, terpotong, atau sampel < 40 wallet menghasilkan
    ``dust_count = 0`` / ``dust_pct_mc = 0.0`` yang di layar terbaca sebagai
    **0,000% "pool paling bersih"** padahal itu kegagalan provider — angka
    itu tidak akan pernah cocok dengan hasil Scan Holder token yang sama
    (kasus nyata: user, 2026-09-13: "di scan meteora menunjukkan 0.000% baru
    saya scan, padahal di scan holder hasilnya beda"). Baris semacam itu
    sekarang ``dust_pct_mc = None`` + alasan di ``holders_note``, sehingga
    saringan Best Pool menggugurkannya (``None`` = tidak ada bukti) dan
    listing Scan Meteora menampilkannya tanpa angka.
    """
    if not rows:
        return rows
    from holder_analysis import analyze_token
    from holder_history import load_holder_history

    store = load_holder_history()
    mint_pools = _mint_pools(rows)
    mints = [mint for mint in mint_pools
             if mint and mint not in QUOTE_MINTS]
    total = len(mints)
    workers = max(1, min(int(workers), 8))
    analyses: dict[str, dict | None] = {}

    def _job(mint: str):
        meta = ((store.get("tokens") or {}).get(mint) or {})
        cohort = meta.get("cohort") if isinstance(meta.get("cohort"), dict) else {}
        addrs = list((cohort.get("balances") or {}).keys())
        symbol = next((str(r.get("symbol") or "?") for r in rows
                       if r.get("ca") == mint), "?")
        # MC/harga listing Meteora hanya **cadangan**: ``analyze_token``
        # memakai market cap DexScreener yang baru di-fetch sebagai
        # pembagi dust, supaya angka Dust %MC kartu ini sebanding dengan
        # Scan Holder / watchlist / titik history (lihat komentar di
        # ``holder_analysis.analyze_token``).
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
            # Hanya scan dengan **bukti** holder yang di-ingest (aturan yang
            # sama dengan lane Watchlist Meteora / cron): satu titik
            # ``dust_pct_mc = 0.0`` dari fetch yang gagal bisa menimpa titik
            # cron yang benar di dalam ``MIN_POINT_GAP_SEC`` (scan dobel =
            # timpa titik terakhir) sehingga grafik dust token watchlist
            # terlihat jatuh ke nol.
            ok = {mint: item for mint, item in analyses.items()
                  if isinstance(item, dict)
                  and holders_usable(item.get("holders"))}
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
        # MC yang benar-benar dipakai sebagai pembagi dust ditulis balik ke
        # baris, supaya kolom MC di card tidak pernah terlihat "berantakan"
        # dengan Dust %MC di sebelahnya (dua angka dari dua sumber berbeda).
        mc_used = _float((analysis or {}).get("marketcap"), 0.0)
        if mc_used > 0:
            item["mc"] = mc_used
        proof = holders_usable(holders)
        item["holders_proof"] = bool(proof)
        item["holders_note"] = "" if proof else _holder_gap(analysis, holders)
        item["dust_count"] = holders.get("dust_count") if proof else None
        item["dust_pct_mc"] = holders.get("dust_pct_mc") if proof else None
        item["real_count"] = holders.get("real_count") if proof else None
        out.append(item)
    return out


def _holder_gap(analysis, holders: dict) -> str:
    """Alasan pendek "angka dust tidak bisa dipercaya" untuk satu baris pool.

    Ditempel ke ``holders_note`` lalu ditampilkan UI di bawah Dust %MC —
    penggantinya angka **0,000%** palsu hasil scan holder yang gagal.
    """
    if not isinstance(analysis, dict):
        return "⚠️ holder gagal di-scan"
    error = str(holders.get("error") or holders.get("fetch_error") or "").strip()
    if holders.get("truncated"):
        return "⚠️ holder terpotong" + (f": {error[:48]}" if error else "")
    fetched = int(_float(holders.get("total_fetched"), 0.0))
    wallets = int(_float(holders.get("wallets_analyzed"), 0.0)) or fetched
    if fetched <= 0:
        return ("⚠️ 0 holder"
                + (f": {error[:48]}" if error else " (provider mati)"))
    return (f"⚠️ sampel {wallets} wallet — butuh "
            f"≥ {int(MIN_USABLE_WALLETS)} untuk dust %MC")


def row_dust_pct(row: dict | None):
    """Dust % MC satu baris pool: ``analysis`` dulu, fallback field baris.

    Dipakai bersama oleh :func:`hide_dust_limit`, :func:`row_flag`,
    ``best_pool_ui`` dan ``temp_ui.render_meteora_scan`` supaya angka yang
    menyaring, mengurutkan, dan yang tampil di layar **selalu** berasal dari
    sumber yang sama.

    Scan holder yang **tidak** bisa dipercaya (0 wallet / terpotong / sampel
    di bawah :data:`~holder_history.MIN_USABLE_WALLETS`) selalu mengembalikan
    ``None``, bukan ``0.0`` hasil klasifikasi kosong: tanpa bukti, barisnya
    dianggap "tanpa angka dust" — digugurkan saringan Best Pool, tidak bisa
    jadi BEST POOL, dan tidak pernah tampil sebagai **0,000%** yang menipu.
    """
    row = row or {}
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    holders = analysis.get("holders") if isinstance(analysis, dict) else None
    holders = holders if isinstance(holders, dict) else {}
    if holders and not holders_usable(holders):
        return None
    pct = holders.get("dust_pct_mc")
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
    """Compatibility sorter untuk konsumen lama, bukan regular scan.

    Regular Scan Meteora memakai :func:`sort_regular_rows`, yang mengurutkan
    lane 24h/30m dan quotient fee/volatility tanpa dust. Fungsi lama ini tetap
    tersedia untuk compatibility/test konsumen yang masih membutuhkan urutan
    BEST POOL berbasis dust; Scan Best Pool memiliki sorter sendiri.

    Kunci urut lama (kecil = atas):

    1. ``best`` (BEST POOL) di atas non-best;
    2. dust % MC **terkecil** dulu — makin sedikit dust makin bersih;
       baris tanpa angka dust (holder gagal) ditaruh paling bawah karena
       tidak ada bukti dan tidak pernah bisa jadi BEST POOL;
    3. **volume 24 jam / active TVL** terbesar (:func:`row_vol_tvl_ratio`,
       permintaan user 2026-09-13 — sebelumnya TVL terbesar) sebagai
       tie-break: pool yang ramai relatif terhadap likuiditas aktifnya naik;
    4. simbol alfabetis supaya urutannya deterministik (stabil antar scan).
    """
    def _key(row):
        row = row or {}
        pct = _float(row_dust_pct(row), None)
        ratio = row_vol_tvl_ratio(row)
        return (
            0 if row_flag(row).get("best") else 1,
            0 if pct is not None else 1,
            pct if pct is not None else 0.0,
            -(ratio if ratio is not None else -1.0),
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
    """Scan regular Meteora lanes 24h → 30m.

    Metrik rule diterapkan sebelum holder enrichment agar pool yang pasti tidak
    tampil tidak membakar kuota holder. Setelah holder diperkaya, filter dust
    lama tetap dijalankan; dust bukan kunci urut dan tidak memengaruhi
    klasifikasi SAFE/HIGH RISK.
    """
    if max_wallets is None:
        from holder_history import FULL_SCAN_MAX_WALLETS
        max_wallets = FULL_SCAN_MAX_WALLETS
    try:
        import activity_log as _alog
    except Exception:  # noqa: BLE001 - log hanya pelengkap
        _alog = None
    if _alog:
        _alog.info("scan-meteora", "scan mulai: listing pool DLMM Meteora 24h + 30m")
    rows, error = fetch_listing(timeout=timeout)
    if _alog and error:
        _alog.error("scan-meteora", f"listing Meteora gagal: {error[:160]}")
    fetched = len(rows)
    # Quote-only tidak punya token yang bisa dianalisa; buang lebih dulu agar
    # penghitung skip tetap akurat walau payload metriknya juga kosong.
    rows, quote_skipped = drop_quote_rows(rows)
    rows, hidden_rule = filter_regular_rows(rows)
    if rows:
        rows = enrich_pools(rows, max_wallets=max_wallets, workers=workers,
                            progress=progress)
        rows, hidden_dust = hide_dust_limit(rows)
        # Satu-satunya urutan regular: lane 24h/30m lalu quotient
        # fee_active_tvl_ratio ÷ volatility. Tidak pernah memakai dust.
        rows = sort_regular_rows(rows)
    else:
        hidden_dust = 0
    hidden_total = hidden_rule + hidden_dust
    if _alog:
        _alog.info(
            "scan-meteora",
            f"scan selesai: {len(rows)} pool tampil dari {fetched} listing "
            f"({hidden_rule} gugur rule metrik, {hidden_dust} disembunyikan dust"
            + (f", {quote_skipped} pool quote dilewati" if quote_skipped else "")
            + ")")
    return {
        "rows": rows,
        "error": error,
        "fetched": fetched,
        "hidden_dust": hidden_dust,
        "hidden_rule": hidden_rule,
        "hidden_total": hidden_total,
        "skipped_quote": quote_skipped,
        "hide_pct": float(DUST_SCAN_HIDE_PCT),
        # Compatibility summary only; sorting does not use this value.
        "best_count": sum(1 for row in rows if row_flag(row).get("best")),
        "analyzed_at": int(time.time()),
    }


# ---------------------------------------------------------------------------
# 🏆 Scan Best Pool Meteora — listing khusus halaman utama ``app.py``.
# Kriteria diganti total 2026-09-11 (curl UI Meteora dari user). Dua lapis:
#
# 1. **server** (query API Meteora, sama seperti filter UI Meteora):
#    ``pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000``, timeframe 24 jam,
#    category ``top``, page_size 50 — tier fee dan active TVL TIDAK diulang
#    sebagai saringan layar;
# 2. **layar** (setelah data pool + holder ada): dust holder < 0,05% MC dan
#    volatility minimal 2%.
#
# Urutan baris: **volume 24 jam / active TVL** (``volume_active_tvl_ratio``)
# terbesar → **dust % MC terkecil** (permintaan user 2026-09-13; sebelumnya
# kenaikan volume 24 jam → dust → fee/active TVL, 2026-09-11 sore). Data yang hilang
# (``None``) selalu menggugurkan baris:
# card ini menjual bukti, jadi pool tanpa angka tidak ikut ditampilkan.
# ---------------------------------------------------------------------------
def _maybe_float(value):
    """Float atau ``None`` (NaN/Infinity/bool/tipe salah → ``None``).

    Berbeda dari :func:`_float` yang menelan ``None`` jadi 0: saringan Best
    Pool harus bisa membedakan "angkanya nol" dari "datanya tidak ada".
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def best_filter_by(pool_type: str = "dlmm",
                   fee_pct_min: float = BEST_FEE_PCT_MIN,
                   active_tvl_min: float = BEST_ACTIVE_TVL_MIN) -> str:
    """Query ``filter_by`` Scan Best Pool Meteora (&&-join ala UI Meteora).

    Hasil default (kriteria 2026-09-11):
    ``pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000`` — persis query yang
    dipakai UI Meteora di request user, dan satu-satunya tempat angka
    ``fee_pct`` / ``active_tvl`` Best Pool ditulis (API yang menyaring,
    bukan layar).
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


def row_vol_tvl_ratio(row: dict | None):
    """Rasio **volume 24 jam / active TVL** (%) — kunci urut pertama listing.

    Angka utama datang dari API Meteora (``volume_active_tvl_ratio``, mis.
    TACZ 1646,63 = volume 1,97 juta USD pada active TVL 119,4 ribu USD), jadi
    yang diurutkan card persis angka yang dilihat user di payload — bukan
    hitungan versi sendiri. Baris lama di ``session_state`` (hasil scan versi
    sebelumnya) belum punya field itu: di situ rasionya dihitung ulang
    ``volume / active_tvl × 100`` supaya kriteria urut tidak berubah hanya
    karena hasil lama masih tersimpan. ``None`` = tidak ada bahan hitung
    (volume/active TVL hilang) → ``-1`` di kunci urut, jadi barisnya paling
    bawah.
    """
    row = row or {}
    ratio = _maybe_float(row.get("volume_active_tvl_ratio"))
    if ratio is not None:
        return ratio
    volume = _maybe_float(row.get("volume"))
    tvl = _maybe_float(row.get("active_tvl"))
    if volume is None or tvl is None or tvl <= 0:
        return None
    return volume / tvl * 100.0


def row_volume_ok(row: dict | None) -> bool:
    """True bila volume 24 jam **>= 1 juta USD** (angka wajib ada).

    Dipakai bersama listing utama dan listing **disembunyikan** (klik pill)
    supaya keduanya tidak pernah menampilkan pool sepi. ``None`` = gugur.
    """
    volume = _maybe_float((row or {}).get("volume"))
    return bool(volume is not None and volume >= BEST_VOLUME_24H_MIN)


def row_best_gaps(row: dict | None) -> list[str]:
    """Label syarat **metrik pool** yang tidak dipenuhi (kosong = lolos).

    Tier fee dan active TVL sudah disaring API lewat ``filter_by``, jadi yang
    diuji di layar tinggal dua: volatility minimal
    :data:`BEST_VOLATILITY_MIN` (2026-09-11) dan **volume 24 jam minimal
    :data:`BEST_VOLUME_24H_MIN`** (1 juta USD, 2026-09-12 — permintaan user:
    "minimal volume 24 jam adalah 1M, dibawah itu jangan di show"). Keduanya
    inklusif (tepat di ambang = lolos). Saringan fee/active TVL, top 10
    holder, dan total LPs yang lama **dihapus** (datanya tetap dibawa di
    baris untuk ditampilkan). Data hilang (``None``) = gugur. Syarat ini
    jalan SEBELUM fetch holder supaya kuota Helius tidak terbakar untuk pool
    yang pasti gugur; dust holder dicek terpisah oleh :func:`row_dust_ok`
    karena butuh analisa holder.
    """
    row = row or {}
    gaps: list[str] = []
    volatility = _maybe_float(row.get("volatility"))
    if volatility is None or volatility < BEST_VOLATILITY_MIN:
        gaps.append(f"volatility < {BEST_VOLATILITY_MIN:g}%")
    volume = _maybe_float(row.get("volume"))
    if volume is None or volume < BEST_VOLUME_24H_MIN:
        gaps.append(f"volume 24 jam < ${BEST_VOLUME_24H_MIN:,.0f}")
    return gaps


def row_dust_ok(row: dict | None) -> bool:
    """True bila dust holder **< 0,05% MC** (angka wajib ada).

    Lebih ketat dari ``DUST_SCAN_HIDE_PCT`` (0,1%): listing Best Pool hanya
    memuat pool dengan distribusi holder yang benar-benar bersih. Dust
    ``None`` (holder gagal di-fetch) **tidak** lolos — tidak ada bukti.
    """
    pct = _maybe_float(row_dust_pct(row))
    return bool(pct is not None and pct < BEST_DUST_MAX_PCT)


def row_best_pool(row: dict | None) -> bool:
    """True bila dust holder **<= 0,035% MC** → baris ditandai 🏆 BEST POOL.

    Penanda visual (2026-09-12, permintaan user: "tandai jika %dust <=
    0.035 menjadi Best Pool"), bukan saringan: saringan listing tetap
    :func:`row_dust_ok` (``BEST_DUST_MAX_PCT`` 0,05%, lebih longgar). Batas
    **inklusif** (dust 0,035 persis ikut ditandai); dust ``None`` (holder
    gagal di-fetch) tidak pernah ditandai — tidak ada bukti.
    """
    pct = _maybe_float(row_dust_pct(row))
    return bool(pct is not None and pct <= BEST_DUST_MARK_PCT)


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
    """Urutan listing Best Pool: **volume/active TVL** → dust %MC terkecil.

    Permintaan user 2026-09-13: "sort pertama adalah dari volume / active tvl
    yang paling besar dulu, lalu dari %dust yang paling kecil" — menggantikan
    urutan 2026-09-11 (kenaikan volume 24 jam → dust → fee/active TVL). Angka
    pertama diambil dari :func:`row_vol_tvl_ratio` (rasio ``volume`` /
    ``active_tvl`` yang dikirim API Meteora), jadi pool paling ramai relatif
    terhadap likuiditas aktifnya yang tampil paling atas.

    Kunci dust dibulatkan ke presisi tampilan (:data:`BEST_DUST_SORT_DECIMALS`,
    3 desimal = angka yang muncul di card), jadi pool yang di layar sama-sama
    "0,041%" dianggap seri; simbol alfabetis jadi tie-break terakhir supaya
    urutannya deterministik antar scan. Baris tanpa angka dust (holder gagal)
    tetap ditaruh paling bawah — tidak ada bukti, sebesar apa pun volumenya.
    """
    def _key(row):
        row = row or {}
        pct = _maybe_float(row_dust_pct(row))
        ratio = row_vol_tvl_ratio(row)
        return (
            0 if pct is not None else 1,
            -(ratio if ratio is not None else -1.0),
            round(pct, BEST_DUST_SORT_DECIMALS) if pct is not None else 0.0,
            str(row.get("symbol") or "").upper(),
        )

    return sorted(list(rows or []), key=_key)


def scan_best_meteora(*, max_wallets: int | None = None, workers: int = 6,
                      progress=None, timeout: int = 25,
                      timeframe: str = "24h",
                      page_size: int = PAGE_SIZE) -> dict:
    """Listing 24 jam + holder + saringan layar Scan Best Pool Meteora.

    Kriteria 2026-09-11 (+volume 2026-09-12): API sudah menyaring
    ``pool_type=dlmm``, ``fee_pct>=2``, ``active_tvl>=50000``; layar menambah
    volatility ``>= 2%`` dan **volume 24 jam ``>= 1 juta USD``** (keduanya
    dicek SEBELUM fetch holder supaya kuota Helius tidak terbakar) serta dust
    holder ``< 0,05% MC`` (butuh holder). Urutan hasil: volume 24 jam / active
    TVL terbesar → dust % MC terkecil (lihat :func:`sort_best_rows`).
    """
    # Default FULL seperti ``scan_meteora``: urutan getTokenAccounts Helius
    # tidak urut saldo, jadi cap kecil menghasilkan sampel bias dan angka
    # dust < 0,05% MC tidak bisa dipercaya.
    if max_wallets is None:
        from holder_history import FULL_SCAN_MAX_WALLETS
        max_wallets = FULL_SCAN_MAX_WALLETS
    try:
        import activity_log as _alog
    except Exception:  # noqa: BLE001 - log hanya pelengkap
        _alog = None
    if _alog:
        _alog.info("scan-best-pool", "scan mulai: listing Best Pool Meteora")
    try:
        pools = fetch_best_pools(timeframe=timeframe, page_size=page_size,
                                 timeout=timeout)
        error = ""
    except Exception as exc:  # noqa: BLE001 - kegagalan API jadi pesan card
        pools, error = [], str(exc)
        if _alog:
            _alog.error("scan-best-pool",
                        f"listing Meteora gagal: {str(exc)[:160]}")
    rows = rows_from_pools(pools)
    fetched = len(rows)
    # Pool quote-only (tanpa sisi memecoin) tidak dianalisa dan tidak ikut
    # listing — dust %-nya terhadap MC SOL/USDC selalu 0,000% (lihat
    # :func:`unanalysable_row`).
    rows, quote_skipped = drop_quote_rows(rows)
    # Volume 24 jam >= $1M wajib untuk listing utama **dan** listing
    # disembunyikan (permintaan user 2026-09-12: klik pill "N
    # disembunyikan" tetap kriteria 1M + dust < 0,05%). Pool sepi tidak
    # di-enrich (hemat kuota Helius). Volatility tetap saringan listing
    # utama — yang gagal volatility tapi lolos volume+dust masuk
    # ``hidden_rows``.
    volume_ok = [row for row in rows if row_volume_ok(row)]
    candidates = [row for row in volume_ok if not row_best_gaps(row)]
    hidden_metric = len(rows) - len(candidates)
    if volume_ok:
        volume_ok = enrich_pools(volume_ok, max_wallets=max_wallets,
                                 workers=workers, progress=progress)
        by_addr = {str(row.get("pool_address") or ""): row
                   for row in volume_ok}
        candidates = [by_addr.get(str(row.get("pool_address") or ""), row)
                      for row in candidates]
    kept, _, hidden_dust = filter_best_rows(candidates)
    kept = sort_best_rows(kept)
    kept_addrs = {str(row.get("pool_address") or "") for row in kept}
    hidden_rows = sort_best_rows([
        row for row in volume_ok
        if str(row.get("pool_address") or "") not in kept_addrs
        and row_dust_ok(row)
    ])
    if _alog:
        _alog.info("scan-best-pool",
                   f"scan selesai: {len(kept)} pool lolos dari {len(rows)} "
                   f"listing ({hidden_metric} gugur metrik, {hidden_dust} "
                   "gugur dust"
                   + (f", {quote_skipped} pool quote dilewati"
                      if quote_skipped else "") + ")")
    return {
        "rows": kept,
        "hidden_rows": hidden_rows,
        "error": error,
        "fetched": fetched,
        "hidden_metric": hidden_metric,
        "hidden_dust": hidden_dust,
        # Baris tanpa angka dust (holder gagal/terpotong) sudah dihitung di
        # ``hidden_dust``: tanpa bukti dust tidak ada tempat di card ini.
        "skipped_quote": quote_skipped,
        "analyzed_at": int(time.time()),
    }
