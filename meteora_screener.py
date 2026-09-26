# -*- coding: utf-8 -*-
"""Meteora DLMM listing helpers and the Best Pool scanner.

Best Pool fetches the 24-hour listing with active TVL of at least $100K, then
applies the cheap F/V, Fee/TVL, volatility, LP-count, and Top-10 concentration
gates.  The final cheap gate fetches official Meteora pool details and requires
SOL-side USD liquidity to be at least two times token-side USD liquidity.
Only passing rows continue to optional GMGN, RugCheck, and tax enrichment.

"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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
BEST_FV_24H_MIN = 5.0           # 24H: F/V >= 5,0 (inklusif)
# Layar: **Fee/TVL minimal 30%** (permintaan user 2026-09-23: *"kita perketat
# filter yang boleh di show di hasil"* + *"Fee/TVL minimal 30%"* + *"dibawah itu
# jangan show"*). ``fee_active_tvl_ratio`` API Meteora sudah dalam satuan persen
# (88.56 = 88,56%), jadi ambangnya dibandingkan langsung sebagai persen: pool
# yang fee-nya kurang dari 30% terhadap active TVL dianggap kurang produktif
# untuk masuk tabel hasil — F/V setinggi apa pun tidak menolong, karena
# pembilangnya (fee) memang kecil. Batas **inklusif di sisi tampil**: tepat
# 30,0% lolos. Fee hilang/negatif/nonfinite sudah gugur lebih dulu di cabang
# "metrik F/V tidak tersedia" (:func:`row_best_gaps`), jadi saringan ini tidak
# pernah menghadapi kasus "tanpa bukti". Berbeda dari Top10 / volatility / LPs,
# baris yang gugur di sini **TIDAK dibuang total** (konfirmasi user 2026-09-23):
# ia masuk listing "▶ N pool dilewati" dengan alasan
# ``gugur: Fee/TVL … < 30%`` supaya tetap bisa dibandingkan, hanya tidak tampil
# di tabel hasil. Saringan ini hanya untuk card 🏆 Best Pool — regular scan
# (:func:`filter_regular_rows`) tidak ikut berubah.
BEST_FEE_TVL_MIN = 30.0
# Layar: **F/V di bawah 2× tidak ditampilkan sama sekali** (permintaan user
# 2026-09-24: *"jangan tampilkan sama sekali pool yang F/V nya kurang dari 2 di
# pool yang dilewati atau dimanapun"*). Beda dari ambang lane
# (:data:`BEST_FV_24H_MIN` 5×) yang hanya memindahkan baris ke listing
# "▶ N pool dilewati": di bawah lantai ini baris **dibuang total** — tidak
# masuk tabel hasil, tidak masuk ``hidden_rows``, tidak dihitung pill/caption
# "dilewati", dan tidak ikut rekap alasan tabel kosong. Jadi listing
# "dilewati" hanya memuat F/V ``>= 2×`` (yang tetap gugur ambang 5×) atau
# baris yang gugur Fee/TVL; baris F/V 0–2× lenyap sepenuhnya, selebar apa pun
# tabelnya. Batas **eksklusif di sisi buang** — kurang dari 2,0× dibuang,
# tepat 2,0× masih boleh tampil di "dilewati" (aturan repo: angka yang
# disebut user dibaca sebagai batas tampil). Angka F/V tanpa bukti
# (metrik hilang/nonfinite/volatility 0) **bukan** "kurang dari 2" — vol-0
# sudah dibuang lebih dulu (:func:`row_volatility_zero`) dan metrik tidak
# valid tetap terlihat di "dilewati" dengan alasannya sendiri. Saringan ini
# juga jalan saat render hasil scan LAMA (lewat :func:`row_best_dropped` di
# ``best_pool_ui``) tanpa perlu scan ulang. Hanya card 🏆 Best Pool —
# ``filter_regular_rows`` Scan Meteora regular tidak ikut berubah.
BEST_FV_HIDE_MIN = 2.0
BEST_CARD_TITLE = "🏆 Scan Best Pool Meteora"
# **Satu lane sejak 2026-09-16** (permintaan user: "hapus scan 30 menit, kita
# sisakan yang 24 jam saja"). Sejak 2026-09-13 card ini punya DUA tombol
# (24H + 30M, dua tabel, dua session key); yang 30M dicabut seluruhnya: tidak
# ada tombol, tidak ada tabel, tidak ada fetch ``timeframe=30m``, dan
# ``normalize_best_lane`` memetakan ulang alias lama ("30m", "1h", "both") ke
# 24H supaya hasil/cache lama tetap terbaca tanpa cabang mati di mana-mana.
BEST_LANES = ("24h",)
# Label "30m" sengaja dipertahankan: hasil/cache lama masih menyimpan
# timeframe itu dan teks rekap tidak boleh berubah jadi "30M".upper() yang
# aneh kalau suatu saat dibaca.
BEST_LANE_LABELS = {"24h": "24H", "30m": "30M"}
BEST_FV_30M_MIN = 1.0            # compatibility for cached lane labels
BEST_FEE_PCT_MIN = 2.0            # server-side pool fee tier
BEST_ACTIVE_TVL_MIN = 100_000.0
BEST_VOLATILITY_MIN = 2.0
BEST_VOLUME_24H_MIN = 1_000_000.0
# Independent concentration metric supplied by Meteora; this is not the
# removed wallet-depth analysis subsystem.
BEST_TOP10_MAX_PCT = 20.0
BEST_VOL_SHOW_MIN = 1.0
BEST_VOL_SHOW_MAX = 10.0
BEST_LPS_MIN = 100.0
# SOL USD liquidity must be at least 2× token USD liquidity.  Equivalently,
# token:SOL is at most 1:2; a more SOL-heavy ratio (for example 1:6.52) passes.
BEST_SOL_TOKEN_MIN_RATIO = 2.0
BEST_TOKEN_SOL_MAX_RATIO = 1.0 / BEST_SOL_TOKEN_MIN_RATIO
BEST_TOKEN_SOL_RATIO_LABEL = "1:2"
DLMM_POOLS_URL = "https://dlmm.datapi.meteora.ag/pools"

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


def dlmm_bin_step(pool: dict | None):
    """``bin_step`` pool DLMM (basis point) dari ``dlmm_params`` API Meteora.

    ``dlmm_params`` bisa ``None`` (pool non-DLMM) atau bukan dict sama
    sekali — kembalikan ``None`` supaya tidak pernah melempar di tengah scan.
    """
    params = (pool or {}).get("dlmm_params")
    if not isinstance(params, dict):
        return None
    return params.get("bin_step")


def unanalysable_row(row: dict | None) -> str:
    """Explain why a quote-only pair cannot represent a meme-token pool."""
    row = row or {}
    mint = str(row.get("ca") or "").strip()
    if not mint:
        return "mint token base tidak terbaca"
    if mint in QUOTE_MINTS:
        return "pool quote-only (SOL/USDC/USDT, tanpa sisi memecoin)"
    return ""


def drop_quote_rows(rows: list[dict] | None) -> tuple[list[dict], int]:
    """Drop quote-only rows before any pool-detail or market enrichment."""
    kept, dropped = [], 0
    for row in rows or []:
        if unanalysable_row(row):
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped


def fee_volatility_ratio(fee_active_tvl_ratio, volatility):
    """Return Fee/TVL divided by volatility, or ``None`` when invalid."""
    fee = _maybe_float(fee_active_tvl_ratio)
    vol = _maybe_float(volatility)
    if fee is None or vol is None:
        return None
    if vol == 0:
        return float("inf") if fee > 0 else 0.0
    return fee / vol


# ---------------------------------------------------------------------------
# Tampilan angka F/V di kolom card (permintaan user 2026-09-15: *"perbaiki"*
# atas laporan *"gold menunjukkan 6328266.1 F/V"*).
#
# `.1f` dulu dipakai untuk SEMUA besaran, jadi rasio besar terbaca sebagai
# ~10 digit tanpa pemisah (``6328266.1×``): angka aslinya benar (pool live
# GOLD-XAUt0 punya ``fee_active_tvl_ratio`` 0,013 ÷ ``volatility``
# 2,06e-09 = 6.328.266×), tetapi satu digit di belakang koma tidak ada
# artinya di besaran jutaan dan kolomnya jadi meluber. Aturannya sekarang:
#
# - di bawah :data:`FV_PLAIN_MAX` (100×) tetap satu desimal — presisi yang
#   sejak awal dipakai (``10,1×`` / ``6,4×``) dan memang berguna;
# - 100× ke atas jadi bilangan bulat **dengan pemisah ribuan**
#   (``6,328,266×``) — besaran langsung terbaca, tidak ada digit palsu;
# - ``∞`` (volatility 0 di atas fee positif) dan ``—`` (tidak terukur) tetap.
#
# Pemformat ini satu-satunya sumber teks kolom F/V: sel card, teks gap, dan
# bawaan test membacanya, jadi angka di layar tidak pernah beda dari angka
# yang dipakai menyaring + mengurutkan (:func:`row_fv_ratio`).
# ---------------------------------------------------------------------------
FV_DISPLAY_DECIMALS = 1     # digit di belakang koma untuk rasio < 100×
FV_PLAIN_MAX = 100.0        # >= 100× ditulis bulat + pemisah ribuan


def format_fv_ratio(value, *, decimals: int = FV_DISPLAY_DECIMALS):
    """Angka F/V siap tampil (``None`` bila tidak ada, ``"∞"`` bila tak hingga).

    ``None``/``NaN``/teks kosong → ``None`` supaya pemanggil bisa menulis
    ``—`` sendiri. ``inf`` → ``"∞"`` (volatility 0, pool tanpa pergerakan —
    baris seperti itu sudah dibuang card, kontrak teksnya tetap dijaga).
    ``1,4`` → ``"1.4×"``; ``6_328_266.05`` → ``"6,328,266×"``.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:                # NaN
        return None
    if math.isinf(number):
        return "∞"
    if abs(number) < FV_PLAIN_MAX:
        return f"{number:.{int(decimals)}f}×"
    return f"{number:,.0f}×"


def regular_pool_classification(row: dict | None) -> dict:
    """Classify one legacy regular-listing row from pool metrics."""
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
    """Order legacy regular rows by lane and fee/volatility ratio."""
    def _key(row):
        row = row or {}
        timeframe = str(row.get("timeframe") or row.get("source") or "24h").lower()
        if timeframe == "1h":
            timeframe = "30m"
        ratio = fee_volatility_ratio(row.get("fee_active_tvl_ratio"),
                                     row.get("volatility"))
        # Keep missing metrics at the bottom of their lane. ``sort_rows`` is
        rank = 0 if timeframe == "24h" else 1
        return (rank, 0 if ratio is not None else 1,
                -(ratio if ratio is not None else 0.0),
                str(row.get("symbol") or "").upper(),
                str(row.get("pool_address") or ""))
    return sorted(list(rows or []), key=_key)


def _transfer_fee_pct(token) -> float | None:
    """Persen pajak transfer dari peringatan Jupiter di token base, atau None.

    Bukan penanda dividend. Import di dalam fungsi supaya modul pajak tidak
    ikut termuat saat screener diimpor.
    """
    from token_tax import transfer_fee_pct_from_token

    return transfer_fee_pct_from_token(token)


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
        "mc": _float(token.get("market_cap") or token.get("fdv")),
        "price": _float(token.get("price")),
        "tvl": _float(pool.get("tvl")),
        "active_tvl": _maybe_float(pool.get("active_tvl")),
        # 📏 Active Range (2026-09-14): API Meteora mengirim harga bin aktif
        # (``pool_price``) dan tepi range likuiditas (``min_price`` /
        # ``max_price``) — ketiganya terbukti harga bin DLMM persis (lihat
        # :func:`active_range_pct`). ``bin_step`` (basis point) dipakai untuk
        # menghitung jumlah bin di tooltip.
        "pool_price": _maybe_float(pool.get("pool_price")),
        "range_min_price": _maybe_float(pool.get("min_price")),
        "range_max_price": _maybe_float(pool.get("max_price")),
        "bin_step": _maybe_float(dlmm_bin_step(pool)),
        "fee_active_tvl_ratio": fee_ratio,
        "volume": _float(pool.get("volume")),
        "fee_pct": _float(pool.get("fee_pct")),
        # Pool metrics used by the Best Pool filters and table.
        "volatility": volatility,
        "total_lps": _maybe_float(pool.get("total_lps")),
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
        # Pajak transfer dari peringatan Jupiter di token base (bukan dividend).
        # Hasil scan lama tidak punya field ini → kolom menulis — sampai rescan.
        "transfer_fee_pct": _transfer_fee_pct(token),
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


#: Alias lama yang DULU berarti lane 30M / gabungan — dipetakan ke 24H sejak
#: 2026-09-16 (permintaan user: "hapus scan 30 menit, kita sisakan yang 24 jam
#: saja"). Jadi sesi/cache/URL lama tidak pernah lagi memicu cabang mati.
RETIRED_LANE_ALIASES = ("30m", "1h", "30 menit", "30 min", "30menit",
                        "both", "all", "24h+30m", "24jam+30menit", "gabungan")


def normalize_best_lane(value, *, default: str | None = "24h") -> str | None:
    """Normalisasi nama lane Best Pool → **selalu ``"24h"``** untuk yang dikenal.

    Lane 30M (dan mode gabungan ``both``) dihapus 2026-09-16, tetapi aliasnya
    sengaja TETAP dikenali dan dipetakan ke 24H: session key lama, hasil scan
    lama di ``session_state``/cache berkas, dan URL ``?timeframe=30m`` masih
    bisa muncul, dan tidak ada satu pun dari itu yang boleh menghasilkan
    tabel/tombol 30M lagi. Nama yang sama sekali tidak dikenal tetap
    :data:`default` (``None`` dengan ``default=None``) — dipakai
    :func:`row_best_gaps` untuk menolak baris rusak.
    """
    text = str(value if value is not None else "").strip().lower()
    if text in ("24h", "24 jam", "24hours", "24 hours", "1d"):
        return "24h"
    if text in RETIRED_LANE_ALIASES:
        return "24h"
    return default


def lane_fv_min(lane) -> float:
    """Ambang F/V lane 24H — dibaca dari konstanta **saat dipanggil**.

    :data:`BEST_FV_24H_MIN` (inklusif: tepat 5× lolos). Argumen ``lane`` dibiarkan
    ada dipanggilan lama (tombol card, tooltip, label sel F/V, teks gap,
    saringan scan semuanya membaca fungsi ini) tetapi tidak mengubah apa pun
    sejak 30M dihapus 2026-09-16 — :func:`normalize_best_lane` memetakan semua
    alias lama ke 24H, jadi tidak ada cabang ``30m`` lagi di sini.
    """
    return float(BEST_FV_24H_MIN)


def lane_fv_inclusive(lane) -> bool:
    """Selalu ``True``: satu-satunya ambang lane (24H) bersifat ``>=``."""
    return True


def lane_fv_sign(lane) -> str:
    """Tanda pembanding ambang lane untuk teks UI (``≥``)."""
    return "≥" if lane_fv_inclusive(lane) else ">"


def best_lane_gate_label(lane) -> str:
    """Label ambang satu lane untuk UI/tooltip, angka dibaca dari konstanta."""
    normalized = normalize_best_lane(lane)
    return (f"{BEST_LANE_LABELS.get(normalized, str(normalized).upper())}: "
            f"F/V {lane_fv_sign(normalized)} {lane_fv_min(normalized):g}×")


def best_lane_lanes(lane) -> tuple[str, ...]:
    """Lane yang benar-benar diambil — **selama-lamanya ``(24h,)``** (30M dihapus).

    ``lane`` tetap diterima supaya pemanggil lama tidak pecah; nilai apa pun
    yang dikenali :func:`normalize_best_lane` menghasilkan satu lane 24H.
    """
    return tuple(BEST_LANES)


def row_fv_ratio(row: dict | None):
    """``fee_active_tvl_ratio ÷ volatility`` satu baris (``None`` = tidak ada).

    Satu sumber angka untuk saringan, urutan, DAN kolom F/V di card, jadi
    angka yang diprioritaskan tidak pernah beda dengan angka yang tampil.
    Volatility nol dengan fee positif → ``inf`` (sama seperti
    :func:`fee_volatility_ratio`) — baris seperti itu **gugur** di saringan
    lane (:func:`row_best_gaps`, sejak 2026-09-14), dan sejak lanjutan hari
    yang sama juga **dibuang dari listing**: card membuangnya sebelum tabel
    (:func:`row_volatility_zero`), jadi ∞ praktis tidak pernah tampil.
    """
    row = row or {}
    return fee_volatility_ratio(row.get("fee_active_tvl_ratio"),
                                row.get("volatility"))


def row_fv_under_hide(row: dict | None):
    """Nilai F/V bila **< BEST_FV_HIDE_MIN** (2×) → dibuang total; selain itu ``None``.

    Permintaan user 2026-09-24: *"jangan tampilkan sama sekali pool yang F/V nya
    kurang dari 2 di pool yang dilewati atau dimanapun"*. Satu-satunya pembaca
    lantai :data:`BEST_FV_HIDE_MIN` supaya keputusan "dibuang total" dan
    hitungan audit ``dropped_fv`` tidak pernah bisa beda.

    Angka dibaca lewat :func:`row_fv_ratio` — sumber yang sama dengan kolom
    F/V dan urutan tabel — jadi rasio yang dibuang persis rasio yang akan
    tampil. ``None`` (metrik hilang/nonfinite, volatility nol, atau F/V tidak
    bisa dihitung) berarti **bukan** "kurang dari 2": tanpa angka tidak ada
    bukti rasio kecil (vol-0 sudah dibuang lebih dulu lewat
    :func:`row_volatility_zero`, metrik tidak valid tetap masuk listing
    "dilewati" dengan alasannya sendiri). Batas **eksklusif di sisi buang** —
    F/V tepat 2,0× **tidak** dibuang (masih boleh tampil di "dilewati" selama
    masih di bawah ambang lane 5×).
    """
    ratio = row_fv_ratio(row)
    if ratio is None:
        return None
    if not math.isfinite(ratio):
        # ∞ (volatility 0, fee positif) bukan "kurang dari 2" — baris seperti
        # itu ditangani saringan sendiri (row_volatility_zero).
        return None
    if ratio < float(BEST_FV_HIDE_MIN):
        return ratio
    return None


def fv_hide_label() -> str:
    """Teks lantai F/V untuk UI/tooltip: ``F/V < 2×`` (angka dari konstanta)."""
    return f"F/V < {float(BEST_FV_HIDE_MIN):g}×"


def row_pair_label(row: dict | None) -> str:
    """Nama **pasangan pool** siap tampil, mis. ``ALLINU/SOL`` (``""`` bila tidak ada).

    Permintaan user 2026-09-15: *"kolom Token sekarang akan menunjukkan
    pasangan pairnya, misal ALLINU/SOL"* — pool DLMM selalu punya dua sisi,
    dan arah fee/likuiditasnya ditentukan pasangan itu, jadi kolom Token tidak
    cukup menulis simbol token base saja.

    Sumbernya nama pool apa adanya dari API Meteora
    (``pool-discovery-api.datapi.meteora.ag/pools`` → ``name``, disimpan ke
    baris sebagai ``pool_name`` oleh :func:`_row_from_pool`): itulah pasangan
    yang **benar-benar** ada di pool, bukan tebakan dari simbol
    (``TOK-USDC`` tetap ``TOK-USDC``, tidak dipaksa jadi ``TOK/SOL``).
    Pemisahnya dibiarkan seperti API (``-``); hanya spasi ganda yang dirapatkan
    supaya tidak memecah lebar kolom. Nama ditulis apa adanya (huruf besar dari
    Meteora); kalau kosong, ``name`` token dipakai **hanya bila** memang
    terlihat seperti pasangan (mengandung ``/`` atau ``-``) — kalau tidak,
    kembalikan ``""`` dan card tidak menampilkan baris pasangan sama sekali
    (hasil scan versi lama sebelum kolom ini ada).
    """
    row = row or {}
    pair = " ".join(str(row.get("pool_name") or "").split())
    if pair:
        return pair.upper()
    name = " ".join(str(row.get("name") or "").split())
    if name and ("/" in name or "-" in name):
        return name.upper()
    return ""


def row_volatility_zero(row: dict | None) -> bool:
    """True bila ``volatility`` baris persis 0 — pool tanpa pergerakan.

    Pool seperti itu gugur saringan lane (:func:`row_best_gaps`) DAN sejak
    2026-09-14 (lanjutan) **tidak ditampilkan sama sekali** di card Best Pool
    (permintaan user: *"jika volatility 0 jangan tampilkan, karena tidak ada
    pergerakan disitu"*): tidak masuk tabel lolos, tidak masuk listing
    "dilewati" 24H, dan tidak dihitung di pill/caption/hidden_metric.
    Volatility ``None``/hilang, negatif, atau nonfinite **bukan** nol — baris
    seperti itu tetap masuk listing dilewati dengan alasan metriknya.
    """
    value = _maybe_float((row or {}).get("volatility"))
    return bool(value is not None and math.isfinite(value) and value == 0)


#: Filter server Jupiter safeguard **dimatikan 2026-09-17** setelah laporan
#: user *"token PAID tetap tidak muncul di hasil scan — tidak ada di daftar
#: disembunyikan juga"*. Akar masalah: filter server Meteora
#: ``base_token_has_critical_warnings=false&&quote_token_has_critical_warnings=false``
#: membuang token (termasuk PAID ``98kf…pump``) **sebelum** payload sampai ke
#: kode — jadi mereka tidak pernah masuk ``hidden_rows`` dan user tidak punya
#: jejak kenapa hilang. Token pump.fun yang baru launch sering masih punya
#: freeze/metadata mutable yang Jupiter anggap "critical", walau kolom
#: RugCheck (:mod:`rugchecker`) sudah melaporkan bendera itu sebagai
#: **informasi** (filosofi repo: "RugCheck tidak pernah membuang baris").
#: Bendera tetap tersedia supaya caller/tes yang membutuhkan bisa memasangnya
#: lewat kwarg ``safeguard=True``, tapi default-nya sekarang ``False`` agar
#: token seperti PAID masuk listing, ikut saringan F/V/volat/Top10/GMGN
#: bersama kandidat lain, dan warning-nya tetap terlihat di kolom RugCheck.
JUPITER_SAFEGUARD_FILTERS = ("base_token_has_critical_warnings=false",
                             "quote_token_has_critical_warnings=false")


def best_filter_by(pool_type: str = "dlmm",
                   fee_pct_min: float | None = None,
                   active_tvl_min: float = BEST_ACTIVE_TVL_MIN,
                   *, safeguard: bool = False) -> str:
    """Query ``filter_by`` Scan Best Pool Meteora (&&-join ala UI Meteora).

    Sejak 2026-09-13 filter ``fee_pct>=2`` **dihapus** (permintaan user:
    pool dengan fee tier rendah seperti EMBER/USDC harus muncul). Filter
    server Jupiter safeguard (:data:`JUPITER_SAFEGUARD_FILTERS`) yang
    sempat dipasang 2026-09-16 **dimatikan default-nya** sehari kemudian
    (kwarg ``safeguard=False``) — terbukti membuang token seperti PAID
    sebelum listing sampai ke client, padahal bendera yang sama sudah
    dilaporkan kolom RugCheck tanpa membuang baris. Query default sekarang:
    ``pool_type=dlmm&&active_tvl>=100000``. Kwarg ``fee_pct_min``
    dipertahankan untuk kompatibilitas caller lama (``None`` = tidak
    menambah filter fee_pct); ``safeguard=True`` masih bisa dipakai caller
    yang memang ingin menyaring di sisi server (tes / tooling terpisah).
    """
    def _num(value: float) -> str:
        number = float(value)
        return str(int(number)) if number == int(number) else f"{number:g}"

    prefix = "".join(f"{flag}&&" for flag in JUPITER_SAFEGUARD_FILTERS) \
        if safeguard else ""
    text = (f"{prefix}pool_type={pool_type}"
            f"&&active_tvl>={_num(active_tvl_min)}")
    if fee_pct_min is not None:
        text += f"&&fee_pct>={_num(fee_pct_min)}"
    return text


def fetch_best_pools(*, timeframe: str = "24h", page_size: int = PAGE_SIZE,
                     fee_pct_min: float | None = None,
                     active_tvl_min: float = BEST_ACTIVE_TVL_MIN,
                     timeout: int = 25) -> list[dict]:
    """Top pool untuk Scan Best Pool Meteora. Gagal → raise.

    Filter ``fee_pct`` tetap dihapus (default ``None``): semua pool DLMM
    dengan ``active_tvl >= 100K`` dari API Best Pool ditampilkan, termasuk
    pool ber-fee rendah (EMBER/USDC, SOL/USDC, dll).

    ``timeframe`` dinormalisasi lewat :func:`normalize_best_lane` — sejak
    30M dihapus (2026-09-16) permintaan ``30m``/``1h``/``both`` dari pemanggil
    lama tetap mendarat di window 24 jam, jadi tidak ada jalur tersisa yang
    bisa menarik listing 30 menit.
    """
    params = {
        "page_size": max(1, min(int(page_size), 50)),
        "timeframe": normalize_best_lane(timeframe) or "24h",
        "category": "top",
        "filter_by": best_filter_by(fee_pct_min=fee_pct_min,
                                    active_tvl_min=active_tvl_min),
    }
    payload = _http_get(POOLS_URL, params, timeout=timeout)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def rows_from_pools(pools: list[dict] | None, *,
                    timeframe: str = "24h") -> list[dict]:
    """Baris listing (dedup ``pool_address``) dari payload pool-discovery.

    ``timeframe`` menandai source baris (``24h``/``30m``) supaya hasil lama
    masih bisa dikenali. Scan Best Pool hanya mengambil 24H sejak
    2026-09-16 — argumennya tetap ada karena ``_row_from_pool`` membacanya.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    is_24h = timeframe == "24h"
    for pool in pools or []:
        if not isinstance(pool, dict):
            continue
        row = _row_from_pool(pool, timeframe=timeframe,
                             in_24h=is_24h, in_1h=not is_24h)
        addr = row["pool_address"]
        if addr:
            if addr in seen:
                continue
            seen.add(addr)
        rows.append(row)
    return rows


def _liquidity_distribution_report(payload: dict | None, *,
                                   base_mint: str = "") -> dict:
    """Normalisasi detail pool resmi Meteora menjadi nilai USD token dan SOL.

    Endpoint ``dlmm.datapi.meteora.ag/pools/{address}`` memberi
    ``token_x_amount``/``token_y_amount`` beserta harga USD masing-masing token.
    Rasio wajib dihitung dari **nilai USD** (amount × price), bukan jumlah koin
    mentah. ``base_mint`` adalah token non-quote yang ditampilkan card.
    """
    payload = payload if isinstance(payload, dict) else {}
    sides: list[dict] = []
    for side in ("x", "y"):
        token = payload.get(f"token_{side}")
        token = token if isinstance(token, dict) else {}
        amount = _maybe_float(payload.get(f"token_{side}_amount"))
        price = _maybe_float(token.get("price"))
        value = (amount * price if amount is not None and price is not None
                 and math.isfinite(amount) and math.isfinite(price)
                 and amount >= 0 and price >= 0 else None)
        sides.append({
            "mint": str(token.get("address") or "").strip(),
            "symbol": str(token.get("symbol") or "?").strip(),
            "amount": amount,
            "price_usd": price,
            "value_usd": value,
        })

    sol = next((side for side in sides if side["mint"] == SOL_MINT), None)
    token = next((side for side in sides
                  if base_mint and side["mint"] == str(base_mint).strip()), None)
    if token is None:
        token = next((side for side in sides if side["mint"] != SOL_MINT), None)

    base = {
        "checked": True,
        "ok": False,
        "source": "meteora_dlmm_pool",
        "pool_address": str(payload.get("address") or "").strip(),
    }
    if sol is None or token is None or token.get("mint") == SOL_MINT:
        base["error"] = "pool bukan pasangan token-SOL"
        return base

    token_usd = _maybe_float(token.get("value_usd"))
    sol_usd = _maybe_float(sol.get("value_usd"))
    if (token_usd is None or sol_usd is None or token_usd <= 0
            or sol_usd <= 0):
        base.update({"token": token, "sol": sol,
                     "error": "nilai USD distribusi token/SOL tidak tersedia"})
        return base

    ratio = token_usd / sol_usd
    base.update({
        "ok": True,
        "token": token,
        "sol": sol,
        "token_value_usd": token_usd,
        "sol_value_usd": sol_usd,
        "token_to_sol_ratio": ratio,
        "error": "",
    })
    return base


def fetch_pool_liquidity_distribution(pool_address: str, *,
                                      base_mint: str = "",
                                      timeout: int = 25) -> dict:
    """Ambil distribusi nilai USD satu pool dari API detail DLMM resmi."""
    address = str(pool_address or "").strip()
    if not address or not address.isalnum():
        return {"checked": True, "ok": False,
                "source": "meteora_dlmm_pool",
                "pool_address": address, "error": "alamat pool tidak valid"}
    try:
        payload = _http_get(f"{DLMM_POOLS_URL}/{address}", {}, timeout=timeout)
        report = _liquidity_distribution_report(payload, base_mint=base_mint)
        report["pool_address"] = address
        return report
    except Exception as exc:  # noqa: BLE001 - kegagalan per-pool jadi gap
        return {"checked": True, "ok": False,
                "source": "meteora_dlmm_pool",
                "pool_address": address, "error": str(exc)[:160]}


def attach_liquidity_distribution(rows: list[dict] | None, *, workers: int = 6,
                                  timeout: int = 25) -> list[dict]:
    """Tempel ``liquidity_distribution`` secara paralel ke kandidat terakhir.

    Fungsi ini dipanggil **setelah** F/V dan seluruh prefilter murah lolos,
    tetapi **sebelum** RugCheck/GMGN/tax, sehingga enrichment pihak ketiga
    hanya dipakai kandidat yang relevan.
    """
    rows = list(rows or [])
    if not rows:
        return rows

    def _fetch(row):
        return fetch_pool_liquidity_distribution(
            row.get("pool_address"), base_mint=str(row.get("ca") or ""),
            timeout=timeout)

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers or 1), 8))) as executor:
        jobs = {executor.submit(_fetch, row): row for row in rows}
        for future in as_completed(jobs):
            row = jobs[future]
            try:
                row["liquidity_distribution"] = future.result()
            except Exception as exc:  # noqa: BLE001 - satu pool tidak jatuhkan scan
                row["liquidity_distribution"] = {
                    "checked": True, "ok": False,
                    "source": "meteora_dlmm_pool", "error": str(exc)[:160]}
    return rows


def row_token_sol_ratio(row: dict | None):
    """Rasio nilai USD ``token ÷ SOL`` atau ``None`` bila belum terukur."""
    report = (row or {}).get("liquidity_distribution")
    if not isinstance(report, dict) or not report.get("ok"):
        return None
    ratio = _maybe_float(report.get("token_to_sol_ratio"))
    if ratio is None or not math.isfinite(ratio) or ratio <= 0:
        return None
    return ratio


def liquidity_distribution_label(row: dict | None) -> str:
    """Label rasio mudah dibaca, mis. ``1:6.52`` atau ``2.3:1``."""
    ratio = row_token_sol_ratio(row)
    if ratio is None:
        return "—"
    left, right = (1.0, 1.0 / ratio) if ratio < 1.0 else (ratio, 1.0)

    def _part(value: float) -> str:
        # Empat desimal mencegah nilai sedikit di bawah boundary (mis. rasio
        # 0,4999 = 1:2,0004) dibulatkan menjadi "1:2" lalu tampak kontradiktif.
        return f"{value:.4f}".rstrip("0").rstrip(".")

    return f"{_part(left)}:{_part(right)}"


def row_liquidity_distribution_gap(row: dict | None, *, lane=None) -> str:
    """Alasan gagal bila SOL < 2× token; ``""`` bila gate akhir lolos.

    Dalam notasi token:SOL, nilai token tidak boleh melebihi 1:2 terhadap SOL.
    Distribusi hilang/error dan pasangan non-SOL gagal tertutup: syarat akhir
    wajib **terbukti**, bukan diasumsikan lolos saat API detail bermasalah.
    """
    normalized = normalize_best_lane(
        lane if lane is not None else
        ((row or {}).get("timeframe") or (row or {}).get("source") or "24h"),
        default="24h")
    prefix = f"{BEST_LANE_LABELS.get(normalized, '24H')}: "
    report = (row or {}).get("liquidity_distribution")
    if not isinstance(report, dict) or not report.get("checked"):
        return (prefix + "distribusi likuiditas token:SOL belum diperiksa — "
                "scan ulang")
    if not report.get("ok"):
        reason = str(report.get("error") or "tidak tersedia")
        return prefix + f"distribusi likuiditas token:SOL gagal — {reason}"
    ratio = row_token_sol_ratio(row)
    if ratio is None:
        return prefix + "distribusi likuiditas token:SOL tidak valid"
    maximum = float(BEST_TOKEN_SOL_MAX_RATIO)
    # Boundary token:SOL 1:2 inklusif. Rasio lebih kecil berarti sisi SOL
    # semakin besar (mis. 1:6,52) dan harus lolos. Toleransi hanya menyerap
    # noise floating-point dari dua perkalian amount×price.
    if ratio > maximum and not math.isclose(
            ratio, maximum, rel_tol=1e-12, abs_tol=1e-12):
        sol_multiple = 1.0 / ratio
        return (prefix + f"likuiditas SOL hanya {sol_multiple:.4g}× token < "
                f"minimum {BEST_SOL_TOKEN_MIN_RATIO:g}× "
                f"(token:SOL {liquidity_distribution_label(row)})")
    return ""


def row_best_final_gaps(row: dict | None, *, lane=None) -> list[str]:
    """Seluruh filter Best Pool, dengan rasio distribusi wajib di tahap akhir."""
    gaps = row_best_gaps(row, lane=lane)
    if gaps:
        return gaps
    gap = row_liquidity_distribution_gap(row, lane=lane)
    return [gap] if gap else []


def row_vol_tvl_ratio(row: dict | None):
    """Rasio **volume 24 jam / active TVL** (%) — kunci urut KEDUA listing.

    Angka utama datang dari API Meteora (``volume_active_tvl_ratio``, mis.
    TACZ 1646,63 = volume 1,97 juta USD pada active TVL 119,4 ribu USD), jadi
    yang diurutkan card persis angka yang dilihat user di payload — bukan
    hitungan versi sendiri. Baris lama di ``session_state`` (hasil scan versi
    sebelumnya) belum punya field itu: di situ rasionya dihitung ulang
    ``volume / active_tvl × 100`` supaya kriteria urut tidak berubah hanya
    karena hasil lama masih tersimpan. ``None`` = tidak ada bahan hitung
    (volume/active TVL hilang) → ``-1`` di kunci urut, jadi barisnya paling
    bawah. Sejak 2026-09-15 kunci urut 1-2 adalah **Fee/TVL** lalu **F/V**
    (:func:`row_fv_ratio`); rasio ini tie-break ketiga.
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


# ---------------------------------------------------------------------------
# 📏 Active Range — rentang bin berisi likuiditas (2026-09-14)
#
# DLMM Meteora adalah tangga **bin**: satu bin = satu harga, jarak antar bin
# = ``bin_step`` basis point (rumus resmi ``P_i = (1 + bin_step/10000)^i``,
# docs.meteora.ag → DLMM Formulas). Yang dipakai trader sehari-hari bukan
# harga absolutnya melainkan **berapa persen harga boleh bergerak sebelum
# keluar dari likuiditas**: di luar range itu posisi LP berhenti menghasilkan
# fee. API listing yang sudah dipakai card ini
# (``pool-discovery-api.datapi.meteora.ag/pools``) mengirim tiga angka
# kuncinya per pool:
#
# - ``pool_price`` = harga **bin aktif** (harga pool sekarang),
# - ``min_price`` / ``max_price`` = harga bin terendah / tertinggi yang masih
#   berisi likuiditas → tepi **active range** pool.
#
# Terverifikasi 2026-09-14 pada tiga pool live dengan ``bin_step`` berbeda
# (biketyson-SOL 100, ROUTER-SOL 250, CATE-USDC 20): ketiganya cocok dengan
# ``P_i`` sampai 0,000 ppm, jadi ``min_price``/``max_price`` memang tepi bin,
# **bukan** high/low 24 jam. Kolom **Active Range** di listing menuliskannya
# sebagai persen saja (permintaan user 2026-09-14: "tambahkan Active Range,
# tapi % saja, misal -30% +40") — angka harga mentahnya tetap ada di tooltip.
# ---------------------------------------------------------------------------


def _positive(value):
    """``float`` > 0 atau ``None`` (harga/bin_step tidak boleh 0 atau minus)."""
    number = _maybe_float(value)
    if number is None or number <= 0:
        return None
    return number


def active_range_pct(row: dict | None) -> tuple:
    """``(turun %, naik %)`` dari harga pool ke tepi active range.

    Angka pertama = berapa persen harga masih boleh **turun** dari harga
    sekarang sebelum menyentuh ``min_price`` (bin berisi likuiditas paling
    bawah), angka kedua = berapa persen masih boleh **naik** sebelum menyentuh
    ``max_price``. Keduanya diukur **dari harga sekarang**, jadi simetris
    dengan cara user membaca pergerakan harga: harga × (1 − turun/100) = tepi
    bawah, harga × (1 + naik/100) = tepi atas.

    Contoh pool live 2026-09-14 (angka API Meteora apa adanya):

    - CATE-USDC: harga 0.0743180, tepi 0.0486561 … 0.0884272 → ``(34.5, 19.0)``
    - biketyson-SOL: 6.4807e-05, tepi 6.0447e-05 … 7.0177e-05 → ``(6.7, 8.3)``
    - ROUTER-SOL: 1.49369e-05 = tepi bawah persis → ``(0.0, 5.1)`` — harga
      nempel tepi bawah, sedikit saja turun langsung keluar range.

    Kembalikan ``(None, None)`` bila salah satu harga tidak ada / tidak valid
    (baris hasil scan lama yang belum menyimpan field ini, atau API tidak
    mengirimnya) — UI menulis ``—``, bukan ``-0.0% / +0.0%`` palsu.
    """
    row = row or {}
    price = _positive(row.get("pool_price"))
    low = _positive(row.get("range_min_price"))
    high = _positive(row.get("range_max_price"))
    if price is None or low is None or high is None:
        return None, None
    if high < low:
        low, high = high, low
    return (1.0 - low / price) * 100.0, (high / price - 1.0) * 100.0


def active_range_width_pct(row: dict | None):
    """Lebar seluruh active range (tepi bawah → tepi atas), dalam persen."""
    row = row or {}
    low = _positive(row.get("range_min_price"))
    high = _positive(row.get("range_max_price"))
    if low is None or high is None:
        return None
    low, high = min(low, high), max(low, high)
    return (high / low - 1.0) * 100.0


def active_range_bins(row: dict | None):
    """``(total bin, bin ke bawah, bin ke atas)`` atau ``None``.

    Dipakai di tooltip saja. Rasio desimal token X/Y tidak diperlukan karena
    yang dibandingkan harga-harga di pool yang sama (saling menghilangkan),
    jadi cukup ``bin_step``: jumlah bin = ``log(tepi/harga) / log(1 +
    bin_step/10000)``. ``None`` bila ``bin_step`` tidak ada / 0 (pool
    non-DLMM atau data lama).
    """
    row = row or {}
    step = _positive(row.get("bin_step"))
    price = _positive(row.get("pool_price"))
    low = _positive(row.get("range_min_price"))
    high = _positive(row.get("range_max_price"))
    if step is None or price is None or low is None or high is None:
        return None
    low, high = min(low, high), max(low, high)
    per_bin = math.log(1.0 + step / 10_000.0)
    if per_bin <= 0:
        return None
    down = round(math.log(price / low) / per_bin)
    up = round(math.log(high / price) / per_bin)
    return down + up + 1, down, up


def _pct_signed(value, digits: int = 1) -> str:
    """Persen bertanda siap tampil: ``-34.5%`` / ``+19.0%`` / ``0.0%``.

    Nol sengaja ditulis tanpa tanda (bukan ``+0.0%``): itu artinya harga
    persis di tepi range (contoh nyata ROUTER-SOL 2026-09-14, ``min_price``
    == ``pool_price``), dan ``-0.0%`` / ``+0.0%`` hanya membingungkan.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number) or abs(number) < 0.5 * 10.0 ** -digits:
        return f"{0.0:.{digits}f}%"
    return f"{number:+.{digits}f}%"


def active_range_text(row: dict | None, digits: int = 1) -> str:
    """Teks Active Range siap tampil: ``-52.7% / +19.0%`` (turun / naik).

    ``None`` (data tidak ada) → ``—``. Hanya persen, sesuai permintaan user
    2026-09-14; harga mentah + jumlah bin ada di tooltip sel.
    """
    down, up = active_range_pct(row)
    if down is None or up is None:
        return "—"
    return f"{_pct_signed(-down, digits)} / {_pct_signed(up, digits)}"


def row_volume_ok(row: dict | None) -> bool:
    """Volume filter **dinonaktifkan** 2026-09-13 per request user.

    Sebelumnya: True bila volume 24 jam >= 1 juta USD.
    Sekarang: selalu True — semua pool dari API ditampilkan, volume tetap
    jadi informasi di kolom Vol 24h dan tie-break urut (rasio volume/active
    TVL = kunci kedua, setelah F/V).
    """
    return True


def row_top10_pct(row: dict | None):
    """Meteora Top-10 account supply percentage, or ``None``."""
    return _maybe_float((row or {}).get("top_holders_pct"))


def row_top10_over(row: dict | None):
    """Persen Top10 **bila >= :data:`BEST_TOP10_MAX_PCT`**, selain itu ``None``.

    Satu-satunya pembaca batas: dipakai :func:`row_top10_ok`, teks alasan di
    :func:`row_best_gaps`, dan tes — jadi angka di tooltip card, teks "gugur"
    di listing disembunyikan, dan keputusan saringan tidak pernah bisa beda.
    Batas diarahkan seperti permintaan user ("jika ada top 10 >= 20% jangan
    tampilkan"): Top10 tepat 20,0% **ikut dibuang**.
    """
    pct = row_top10_pct(row)
    if pct is None or pct < float(BEST_TOP10_MAX_PCT):
        return None
    return pct


def row_volatility_gap(volatility) -> str:
    """Alasan gugur bila volatility **di luar** 1%–10%, selain itu ``""``.

    Permintaan user 2026-09-16: "volatility kurang dari 1 sembunyikan juga" +
    "volatility > 10 sembunyikan juga". Batas inklusif di kedua sisi (1,0% dan
    10,0% persis masih tampil) — "kurang dari" dan "lebih dari" dibaca apa
    adanya. ``None``/bukan-angka TIDAK diurus di sini: itu sudah gugur lebih
    dulu di :func:`row_best_gaps` lewat cabang "metrik F/V tidak tersedia".
    Volatility 0 persis juga tidak lewat sini — ia dibuang total dari listing
    oleh :func:`row_volatility_zero` (aturan 2026-09-14), sebelum gap.
    """
    value = _maybe_float(volatility)
    if value is None:
        return ""
    if value < float(BEST_VOL_SHOW_MIN):
        return (f"volatility {value:g}% < {float(BEST_VOL_SHOW_MIN):g}% — "
                "pool nyaris tidak bergerak")
    if value > float(BEST_VOL_SHOW_MAX):
        return (f"volatility {value:g}% > {float(BEST_VOL_SHOW_MAX):g}% — "
                "pergerakan lebih besar dari fee")
    return ""


def row_top10_ok(row: dict | None) -> bool:
    """Return true unless Meteora reports Top-10 concentration >= 20%."""
    return row_top10_over(row) is None


def row_fee_tvl_pct(row: dict | None):
    """**Fee/TVL** satu baris (``fee_active_tvl_ratio``, persen) — ``None`` bila tidak ada.

    Satu sumber angka untuk saringan (:func:`row_fee_tvl_under`), urutan
    (:func:`sort_best_rows`) dan kolom **Fee/TVL** di card, jadi angka yang
    menyaring tidak pernah beda dengan angka yang tampil. API Meteora mengirim
    angka ini sudah dalam persen (88.56 = 88,56% fee terhadap active TVL).
    """
    return _maybe_float((row or {}).get("fee_active_tvl_ratio"))


def row_fee_tvl_under(row: dict | None):
    """Nilai Fee/TVL bila ``< BEST_FEE_TVL_MIN``, selain itu ``None``.

    Satu-satunya pembaca batas (dipakai :func:`row_best_gaps` + tes) supaya
    teks alasan, angka di tooltip dan keputusan saringan tidak pernah bisa
    beda. Batas inklusif di sisi tampil: Fee/TVL tepat 30,0% **lolos**.
    ``None``/hilang dikembalikan sebagai ``None`` juga — bukan karena lolos,
    tetapi karena kasus itu sudah ditolak lebih dulu oleh cabang
    "metrik F/V tidak tersedia" di :func:`row_best_gaps`.
    """
    pct = row_fee_tvl_pct(row)
    if pct is None:
        return None
    if pct < float(BEST_FEE_TVL_MIN):
        return pct
    return None


def row_fee_tvl_ok(row: dict | None) -> bool:
    """True bila Fee/TVL **>= 30%** (atau angkanya tidak ada)."""
    return row_fee_tvl_under(row) is None


def row_lps_count(row: dict | None):
    """Jumlah LP pool (``total_lps``) — ``None`` bila tidak ada."""
    return _maybe_float((row or {}).get("total_lps"))


def row_lps_under(row: dict | None):
    """Nilai LPs bila ``< BEST_LPS_MIN``; selain itu ``None``.

    Batas inklusif di sisi tampil: tepat 100 lolos. Angka hilang juga tidak
    dikarang menjadi nol; :func:`row_lps_ok` dan :func:`row_best_gaps`
    menolaknya secara eksplisit karena minimal LP wajib terbukti.
    """
    count = row_lps_count(row)
    if count is None:
        return None
    if count < float(BEST_LPS_MIN):
        return count
    return None


def row_lps_ok(row: dict | None) -> bool:
    """True hanya bila LPs terukur dan **>= BEST_LPS_MIN**."""
    count = row_lps_count(row)
    return bool(count is not None and math.isfinite(count)
                and count >= float(BEST_LPS_MIN))


def row_best_gaps(row: dict | None, *, lane=None) -> list[str]:
    """Return the first failed cheap Best Pool gate.

    Gates are validated in this order: finite F/V inputs, non-zero volatility,
    LP count >= 100, volatility range, F/V >= 5, Fee/TVL >= 30%, then Meteora's
    independent Top-10 supply concentration metric below 20%.
    """
    row = row or {}
    fee = _maybe_float(row.get("fee_active_tvl_ratio"))
    vol = _maybe_float(row.get("volatility"))
    if any(x is None or not math.isfinite(x) or x < 0 for x in (fee, vol)):
        return ["metrik F/V tidak tersedia atau tidak valid"]
    wanted: str | None = None
    if lane is not None:
        wanted = normalize_best_lane(lane, default=None)
        if wanted is None:
            return ["timeframe tidak dikenal"]
    normalized = normalize_best_lane(
        wanted if wanted is not None
        else (row.get("timeframe") or row.get("source") or "24h"),
        default=None)
    if normalized not in BEST_LANES:
        return ["timeframe tidak dikenal"]
    if vol == 0:
        # ∞ bukan kelolosan: F/V hanya bisa dibandingkan kalau volatility-nya
        # ada. Sebelum 2026-09-14 V=0 dengan F>0 lolos dan tampil sebagai ∞;
        # sejak paginya gugur dengan alasan ini, dan sejak lanjutannya baris
        # vol-0 juga dibuang dari listing oleh card (lihat
        # :func:`row_volatility_zero`) — pool tanpa pergerakan tidak ditampilkan.
        return [f"{BEST_LANE_LABELS[normalized]}: volatility 0 — "
                "F/V tidak terukur"]
    lps = row_lps_count(row)
    if lps is None or not math.isfinite(lps):
        return [f"{BEST_LANE_LABELS[normalized]}: LPs tidak tersedia — "
                f"minimal {float(BEST_LPS_MIN):g} wajib terbukti"]
    under = row_lps_under(row)
    if under is not None:
        return [f"{BEST_LANE_LABELS[normalized]}: LPs {under:g} < "
                f"{float(BEST_LPS_MIN):g} — LP terlalu sedikit"]
    rentang = row_volatility_gap(vol)
    if rentang:
        return [f"{BEST_LANE_LABELS[normalized]}: {rentang}"]
    minimum = lane_fv_min(normalized)
    threshold = minimum * vol
    passed = fee >= threshold if lane_fv_inclusive(normalized) else fee > threshold
    if fee > 0 and passed:
        # Fee/TVL < 30% (2026-09-23) — dicek SETELAH ambang F/V supaya baris
        # yang memang gagal F/V tetap melaporkan "F/V < 5×" (alasan yang lebih
        # dikenal user), dan sebelum Top10 karena Top10 satu-satunya alasan
        # yang membuang baris total dari listing. Baris gugur di sini TIDAK
        # dibuang total (:func:`row_best_dropped`): ia masuk tabel "dilewati".
        tipis = row_fee_tvl_under(row)
        if tipis is not None:
            return [f"{BEST_LANE_LABELS[normalized]}: Fee/TVL {tipis:g}% < "
                    f"{float(BEST_FEE_TVL_MIN):g}% — fee pool terlalu kecil"]
        # Saringan terakhir setelah ambang lane: Top10 >= 20% (2026-09-16).
        # Label lane ikut di depan supaya teks "gugur" di tabel disembunyikan
        # konsisten dengan teks F/V.
        over = row_top10_over(row)
        if over is not None:
            return [f"{BEST_LANE_LABELS[normalized]}: Top10 {over:g}% ≥ "
                    f"{float(BEST_TOP10_MAX_PCT):g}% — supply terpusat"]
        # Saringan likuiditas total GMGN (< $500K) DIHAPUS 2026-09-17 malam
        # (permintaan user: "filter likuiditas hapus coba") — angkanya tetap
        # ditempel ke row["gmgn_liq"] untuk kolom RugCheck (hijau > $500K,
        # merah di bawahnya — lihat gmgn_liquidity.liq_color).
        return []
    sign = "<" if lane_fv_inclusive(normalized) else "≤"
    return [f"{BEST_LANE_LABELS[normalized]}: F/V {sign} {minimum:g}×"]


def gmgn_min_label() -> str:
    """Label ambang WARNA likuiditas GMGN (``$500K``) untuk teks log/UI.

    Sejak 2026-09-17 malam bukan lagi ambang saringan — hanya batas WARNA
    angka likuiditas di kolom RugCheck (hijau di atasnya, merah di bawahnya;
    :func:`gmgn_liquidity.liq_color`). Dibaca dari :mod:`gmgn_liquidity` tiap
    dipanggil supaya teks tidak pernah
    tertinggal bila :data:`gmgn_liquidity.MIN_TOTAL_LIQ_USD` diubah lagi; modul
    tidak terbaca → ``"?"`` (bukan angka lama yang salah).
    """
    try:
        from gmgn_liquidity import MIN_LABEL

        return str(MIN_LABEL)
    except Exception:  # noqa: BLE001 - teks pelengkap, jangan menjatuhkan scan
        return "?"


#: Jarum → label kategori alasan gugur :func:`row_best_gaps`. Urutan menentukan
#: prioritas bila satu teks memuat lebih dari satu jarum (tidak terjadi saat
#: ini — satu alasan per baris — tetapi rekapnya harus tetap deterministik).
#: ``Fee/TVL`` ditulis sebelum ``F/V``: teksnya (``Fee/TVL 20% < 30% …``) memang
#: tidak memuat jarum ``F/V``, tapi urutan ini membuat rekap tabel kosong
#: (:func:`best_gap_summary`) menyebut Fee/TVL apa adanya bila suatu saat teks
#: alasan berubah.
BEST_GAP_CATEGORIES = (("LPs", "LPs"),
                       ("LP", "LPs"),
                       ("likuiditas token:SOL", "likuiditas token:SOL"),
                       ("distribusi likuiditas", "likuiditas token:SOL"),
                       ("Likuiditas GMGN", "likuiditas GMGN"),
                       ("cutoff peringkat", "likuiditas GMGN"),
                       ("Top10", "Top10"),
                       ("volatility", "volatility"),
                       ("Fee/TVL", "Fee/TVL"),
                       ("F/V", "F/V"))


def row_best_gap_label(row: dict | None, *, lane=None) -> str:
    """Kategori alasan gugur satu baris (``"likuiditas GMGN"``/``"Top10"``/…).

    Alasan yang sudah dihitung scan (``row["best_gaps"]``) dipakai apa adanya;
    baris hasil lama tanpa key itu dihitung ulang lewat
    :func:`row_best_gaps`. ``""`` bila barisnya tidak gugur.
    """
    row = row or {}
    gaps = row.get("best_gaps")
    if not isinstance(gaps, list) or not gaps:
        gaps = row_best_gaps(row, lane=lane)
    text = str(gaps[0] or "") if gaps else ""
    if not text:
        return ""
    for needle, label in BEST_GAP_CATEGORIES:
        if needle in text:
            return label
    return "metrik tidak valid"


def row_best_dropped(row: dict | None, *, lane=None) -> bool:
    """True bila pool gugur karena Top10, volatility, LPs < 100/tidak terukur, atau F/V < 2×.

    Baris seperti ini langsung disembunyikan total, tidak ditampilkan
    di mana pun (baik di tabel utama yang lolos maupun di listing
    disembunyikan/dilewati).

    Permintaan user:
    "hasil yang gugur karena
    gugur: Top10
    gugur: volatility
    gugur: LPs
    langsung sembunyikan total, tidak ditampilkana dimanapun"

    Permintaan user 2026-09-24 (lanjutan aturan yang sama): *"jangan tampilkan
    sama sekali pool yang F/V nya kurang dari 2 di pool yang dilewati atau
    dimanapun"* — F/V di bawah :data:`BEST_FV_HIDE_MIN` (2×) ikut dibuang
    total lewat :func:`row_fv_under_hide`, jadi listing "▶ N pool dilewati"
    hanya berisi F/V ``>= 2×`` (yang masih di bawah ambang lane) atau baris
    Fee/TVL tipis.

    **Gugur Fee/TVL < 30% (2026-09-23) SENGAJA tidak ikut dibuang total**
    (konfirmasi user: baris di bawah ambang masuk daftar "▶ N pool dilewati",
    bukan hilang) — pool seperti itu tetap tercatat di ``hidden_rows`` dengan
    alasan ``gugur: Fee/TVL … < 30%``, hanya tidak tampil di tabel hasil.
    Karena itu label ``"Fee/TVL"`` tidak ada di daftar label di bawah, dan
    tidak ada fallback ``row_fee_tvl_under`` di sini.
    """
    row = row or {}
    gaps = row.get("best_gaps")
    if gaps is None:
        gaps = row_best_gaps(row, lane=lane)
    if not gaps:
        return False
    label = row_best_gap_label(dict(row, best_gaps=gaps), lane=lane)
    if label in ("Top10", "volatility", "LPs"):
        return True
    if row_lps_under(row) is not None:
        return True
    if row_volatility_zero(row):
        return True
    vol = _maybe_float(row.get("volatility"))
    if vol is not None and bool(row_volatility_gap(vol)):
        return True
    if row_top10_over(row) is not None:
        return True
    # Lantai F/V (2026-09-24): di bawah 2× lenyap dari listing mana pun.
    if row_fv_under_hide(row) is not None:
        return True
    return False


def best_gap_counts(rows: list | None) -> list[tuple[str, int]]:
    """``[(label, jumlah)]`` alasan gugur, terbanyak dulu (seri: abjad).

    Dipakai card 🏆 Best Pool untuk menjelaskan tabel kosong — permintaan user
    2026-09-17 (*"poolnya kok jadi kosong"*) sesudah ambang likuiditas GMGN
    membuang seluruh listing tanpa pesan yang menyebut penyebabnya.
    """
    counts: dict[str, int] = {}
    for row in rows or []:
        label = row_best_gap_label(row)
        if label:
            counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def best_gap_summary(rows: list | None) -> str:
    """Rekap satu baris alasan gugur: ``"8 likuiditas GMGN · 3 Top10"``.

    ``""`` bila tidak ada baris gugur yang bisa dikategorikan.
    """
    return " · ".join(f"{count} {label}"
                      for label, count in best_gap_counts(rows))


def filter_best_rows(rows: list[dict] | None, *, lane=None,
                     require_distribution: bool = False) -> tuple[list[dict], int, int]:
    """Return ``(lolos saringan layar, jumlah gagal yang TAMPIL dilewati, 0)``.

    ``lane`` memaksa satu aturan ambang untuk seluruh baris (dipakai
    :func:`scan_best_lane` saat satu tombol lane ditekan); tanpa itu setiap
    baris dinilai dari ``timeframe``-nya sendiri. Saringannya lima: ambang F/V
    lane, rentang volatility 1%–10%, LPs ``>= BEST_LPS_MIN``, **Fee/TVL ``>=
    BEST_FEE_TVL_MIN`` (30%, permintaan user 2026-09-23)** dan Top10 ``<
    BEST_TOP10_MAX_PCT`` — semuanya lewat
    :func:`row_best_gaps`. Hitungan kedua hanya memuat baris yang masih bisa
    dilihat di listing "dilewati", yaitu gugur **F/V (>= 2×) atau Fee/TVL**;
    yang dibuang total (F/V < 2× — aturan 2026-09-24 —, volatility / LPs /
    Top10) tidak dihitung. Kandidat gagal dengan
    **volatility 0 tidak ikut dihitung** (2026-09-14 lanjutan): pool tanpa
    pergerakan dibuang dari listing (:func:`row_volatility_zero`), jadi
    hitungan kedua selalu cocok dengan ``len(hidden_rows)`` yang dibangun
    :func:`scan_best_lane`.
    """
    rows = list(rows or [])

    def _gaps(row):
        return (row_best_final_gaps(row, lane=lane) if require_distribution
                else row_best_gaps(row, lane=lane))

    kept = [row for row in rows if not _gaps(row)]
    dropped = sum(1 for row in rows
                  if _gaps(row) and row_best_dropped(row, lane=lane))
    return kept, len(rows) - len(kept) - dropped, 0


def sort_best_rows(rows: list[dict] | None) -> list[dict]:
    """Sort visible pools by Fee/TVL, F/V, volume/TVL, then symbol."""
    def _key(row):
        row = row or {}
        ratio = row_vol_tvl_ratio(row)
        fee_tvl = _maybe_float(row.get("fee_active_tvl_ratio"))
        fv = row_fv_ratio(row)
        return (
            0 if fee_tvl is not None else 1,
            -(fee_tvl if fee_tvl is not None else 0.0),
            0 if fv is not None else 1,
            -(fv if fv is not None else 0.0),
            -(ratio if ratio is not None else -1.0),
            str(row.get("symbol") or "").upper(),
        )

    return sorted(list(rows or []), key=_key)


def sort_hidden_best_rows(rows: list[dict] | None) -> list[dict]:
    """Sort skipped pools by F/V, Fee/TVL, volume/TVL, then symbol."""
    def _key(row):
        row = row or {}
        ratio = row_vol_tvl_ratio(row)
        fee_tvl = _maybe_float(row.get("fee_active_tvl_ratio"))
        fv = row_fv_ratio(row)
        return (
            0 if fv is not None else 1,
            -(fv if fv is not None else 0.0),
            0 if fee_tvl is not None else 1,
            -(fee_tvl if fee_tvl is not None else 0.0),
            -(ratio if ratio is not None else -1.0),
            str(row.get("symbol") or "").upper(),
        )

    return sorted(list(rows or []), key=_key)


def scan_best_lane(lane: str = "24h", *, workers: int = 6,
                   timeout: int = 25, page_size: int = PAGE_SIZE,
                   rugcheck: bool = True,
                   gmgn: bool = True, bubblemap: bool = False,
                   tax: bool = True) -> dict:
    """Scan the single 24H Best Pool lane.

    The pipeline is listing → cheap metric gates → official Meteora side-value
    distribution gate → optional GMGN/RugCheck/tax information.  Every row must
    satisfy SOL USD liquidity >= 2 × token USD liquidity; failures are closed.
    """
    normalized = normalize_best_lane(lane)
    try:
        import activity_log as _alog
    except Exception:  # noqa: BLE001 - log hanya pelengkap
        _alog = None
    lane_label = BEST_LANE_LABELS.get(normalized, str(normalized).upper())
    gate = f" ({best_lane_gate_label(normalized)})"
    if _alog:
        _alog.info("scan-best-pool",
                   f"scan mulai: listing Best Pool Meteora {lane_label}{gate}")
    errors: list[str] = []
    try:
        pools = fetch_best_pools(timeframe=normalized, page_size=page_size,
                                 timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - kegagalan API jadi pesan card
        errors.append(f"{lane_label}: {exc}")
        pools = []
        if _alog:
            _alog.error("scan-best-pool",
                        f"listing Meteora {lane_label} gagal: {str(exc)[:160]}")
    error = " · ".join(errors)
    rows = rows_from_pools(pools, timeframe=normalized)
    fetched = len(rows)
    rows, quote_skipped = drop_quote_rows(rows)

    # Tahap murah lebih dulu (F/V, Fee/TVL, volatility, LPs, Top10). Tidak ada
    # jalur bypass: semua kandidat harus membuktikan seluruh syarat reguler.
    preliminary_failed = [
        dict(row, best_gaps=row_best_gaps(row, lane=normalized))
        for row in rows if row_best_gaps(row, lane=normalized)
    ]
    candidates = [row for row in rows
                  if not row_best_gaps(row, lane=normalized)]

    # FILTER TERAKHIR: nilai USD SOL minimal 2× token (token:SOL maksimal 1:2).
    # Detail resmi Meteora hanya diambil untuk kandidat yang lolos semua tahap
    # murah. Gagal API/non-SOL/tanpa angka = gagal tertutup dan masuk listing
    # "dilewati"; enrichment GMGN, RugCheck, dan tax tidak dipanggil.
    distribution_failed = 0
    if candidates:
        try:
            attach_liquidity_distribution(candidates, workers=workers,
                                          timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - tandai semua, jangan lolos terbuka
            if _alog:
                _alog.error("scan-best-pool",
                            f"distribusi likuiditas gagal: {str(exc)[:160]}")
            for row in candidates:
                row["liquidity_distribution"] = {
                    "checked": True, "ok": False,
                    "source": "meteora_dlmm_pool", "error": str(exc)[:160]}
        distribution_failed = sum(
            1 for row in candidates
            if not (row.get("liquidity_distribution") or {}).get("ok"))

    final_failed = [
        dict(row, best_gaps=row_best_final_gaps(
            row, lane=normalized))
        for row in candidates
        if row_best_final_gaps(
            row, lane=normalized)
    ]
    rows = [row for row in candidates
            if not row_best_final_gaps(
                row, lane=normalized)]

    failed_rows = preliminary_failed + final_failed
    hidden_rows = [row for row in failed_rows
                   if not row_best_dropped(row, lane=normalized)]
    dropped_volatility = sum(1 for row in failed_rows
                             if row_best_gap_label(row, lane=normalized) == "volatility"
                             or row_volatility_zero(row))
    dropped_top10 = sum(1 for row in failed_rows
                        if row_best_gap_label(row, lane=normalized) == "Top10"
                        or row_top10_over(row) is not None)
    dropped_lps = sum(1 for row in failed_rows
                      if row_best_gap_label(row, lane=normalized) == "LPs"
                      or row_lps_under(row) is not None
                      or row_lps_count(row) is None)
    dropped_fv = sum(1 for row in failed_rows
                     if row_fv_under_hide(row) is not None)
    failed_liquidity_ratio = sum(
        1 for row in final_failed
        if (row.get("liquidity_distribution") or {}).get("ok")
        and (row_token_sol_ratio(row) or 0.0)
            > float(BEST_TOKEN_SOL_MAX_RATIO))
    dropped_total = len(failed_rows) - len(hidden_rows)
    hidden_metric = len(hidden_rows)

    # GMGN bukan filter. Tempel hanya ke baris yang sudah lolos rasio akhir.
    gmgn_failed = 0
    if rows and gmgn:
        try:
            from gmgn_liquidity import attach_total_liquidity

            attach_total_liquidity(rows, timeout=timeout)
            gmgn_failed = sum(1 for row in rows
                              if not (row.get("gmgn_liq") or {}).get("ok"))
        except Exception as exc:  # noqa: BLE001 - kolom opsional, scan tetap jalan
            error = " · ".join(
                part for part in (error, f"Likuiditas GMGN: {exc}") if part)
            if _alog:
                _alog.error("scan-best-pool",
                            f"Likuiditas GMGN gagal: {str(exc)[:160]}")
            for row in rows:
                row.setdefault("gmgn_liq",
                               {"ok": False, "usd": None,
                                "below_cutoff": False, "source": None,
                                "cutoff_usd": None,
                                "error": str(exc)[:160]})
    rug_failed = 0
    if rows and rugcheck:
        try:
            from rugchecker import attach_to_rows

            rows = attach_to_rows(rows, workers=workers)
            rug_failed = sum(1 for row in rows
                             if not (row.get("rugcheck") or {}).get("ok"))
        except Exception as exc:  # noqa: BLE001 - kolom opsional, scan tetap jalan
            error = " · ".join(part for part in (error, f"RugCheck: {exc}") if part)
            if _alog:
                _alog.error("scan-best-pool",
                            f"RugCheck gagal: {str(exc)[:160]}")
    # Bubble Map — status cluster & holder terbesar (permintaan user 2026-09-18).
    # **Default-nya OFF sejak 2026-09-19** (permintaan user: *"hapus tentang
    # bubblemap, sisakan hyperlink ke bubblemapnya saja"*): kolom Bubble Map
    # dihapus dari tabel 🏆 Scan Best Pool sehingga laporan cluster/holder
    # tidak dibaca lagi, dan tautan 🫧 yang tersisa dihitung UI langsung dari
    # mint tanpa fetch laporan apa pun. Kwarg-nya
    # tetap ada (pola ``JUPITER_SAFEGUARD_FILTERS``/``safeguard=True``) supaya
    # pemanggil/tooling yang masih butuh laporannya bisa menyalakannya lagi;
    # ``best_pool_ui._run_lane_scan`` mengirim ``bubblemap=False`` secara
    # eksplisit.
    bubblemap_failed = 0
    if rows and bubblemap:
        try:
            from bubblemaps import attach_to_rows as _bubble_attach
            rows = _bubble_attach(rows, workers=workers, timeout=timeout)
            bubblemap_failed = sum(1 for row in rows
                                   if not (row.get("bubblemap") or {}).get("ok"))
        except Exception as exc:  # noqa: BLE001 - kolom opsional
            error = " · ".join(part for part in (error, f"BubbleMap: {exc}") if part)
            if _alog:
                _alog.error("scan-best-pool",
                            f"BubbleMap gagal: {str(exc)[:160]}")
    # Pajak + dividend (2026-09-23) — hanya baris yang lolos, setelah RugCheck
    # supaya ``transfer_fee`` rugchecker.cc ikut jadi cadangan pajak. Kolomnya
    # informasi: kegagalan HTTP tidak membuang baris dan tidak mengubah
    # strategi (dividend belum terbaca ≠ bukan dividend). ``tax=False``
    # (test/offline) melewatkan step ini; suite juga mematikan HTTP lewat
    # ``TOKEN_TAX_FETCH=0``.
    tax_failed = 0
    if rows and tax:
        try:
            from token_tax import attach_to_rows as _tax_attach

            rows = _tax_attach(rows, workers=workers,
                               timeout=min(int(timeout), 12))
            tax_failed = sum(
                1 for row in rows
                if (row.get("tax_dividend") or {}).get("fetched")
                and not (row.get("tax_dividend") or {}).get("dividend")
                and not (row.get("tax_dividend") or {}).get("dividend_known"))
        except Exception as exc:  # noqa: BLE001 - kolom opsional, scan tetap jalan
            error = " · ".join(
                part for part in (error, f"Tax/dividend: {exc}") if part)
            if _alog:
                _alog.error("scan-best-pool",
                            f"Tax/dividend gagal: {str(exc)[:160]}")
    kept = sort_best_rows(rows)
    hidden_rows = sort_hidden_best_rows(hidden_rows)
    if _alog:
        _alog.info("scan-best-pool",
                   f"scan selesai: {len(kept)} pool tampil dari {fetched} "
                   f"listing {lane_label} ({hidden_metric} kandidat dilewati"
                   + (f", {dropped_volatility} pool volatility dibuang"
                      if dropped_volatility else "")
                   + (f", {dropped_top10} pool Top10 dibuang"
                      if dropped_top10 else "")
                   + (f", {dropped_lps} pool LPs dibuang"
                      if dropped_lps else "")
                   + (f", {dropped_fv} pool F/V < "
                      f"{float(BEST_FV_HIDE_MIN):g}× dibuang"
                      if dropped_fv else "")
                   + (f", {failed_liquidity_ratio} pool dengan SOL < "
                      f"{BEST_SOL_TOKEN_MIN_RATIO:g}× token"
                      if failed_liquidity_ratio else "")
                   + (f", {distribution_failed} distribusi tak terbaca/non-SOL"
                      if distribution_failed else "")
                   + (f", {quote_skipped} pool quote dilewati"
                      if quote_skipped else "")
                   + (f", {rug_failed} laporan RugCheck gagal"
                      if rug_failed else "")
                   + (f", {gmgn_failed} likuiditas GMGN tak terbaca"
                      if gmgn_failed else "")
                   + (f", {bubblemap_failed} BubbleMap tak terbaca"
                      if bubblemap_failed else "")
                   + (f", {tax_failed} tax/dividend tak terbaca"
                      if tax_failed else "") + ")")
    return {
        "rows": kept,
        "hidden_rows": hidden_rows,
        "error": error,
        "fetched": fetched,
        "hidden_metric": hidden_metric,
        "skipped_quote": quote_skipped,
        # Pool gugur Top10 / volatility / LPs / F/V < 2× yang dibuang dari
        # listing (tidak ditampilkan di mana pun).
        "dropped_volatility": dropped_volatility,
        "dropped_top10": dropped_top10,
        "dropped_lps": dropped_lps,
        # F/V di bawah lantai BEST_FV_HIDE_MIN (2×) — 2026-09-24.
        "dropped_fv": dropped_fv,
        "dropped_total": dropped_total,
        # Filter akhir: nilai USD SOL minimal 2× token (token:SOL maks. 1:2).
        "failed_liquidity_ratio": failed_liquidity_ratio,
        "liquidity_distribution_failed": distribution_failed,
        "liquidity_distribution_filter": True,
        # Mint yang tidak mendapat laporan rugchecker.cc (HTTP gagal / kode
        # bukan 0) — kolom RugCheck menulis — untuk mereka; angka ini supaya
        # caption bisa membedakan "semua AMAN" dari "belum teriksa".
        "rugcheck_failed": rug_failed,
        # Kandidat yang likuiditas GMGN-nya tak terbaca (GMGN mati / token
        # tak terlacak) — TIDAK disaring (tanpa bukti tidak ada verdict),
        # kolom RugCheck menulis — untuk mereka (2026-09-17).
        "gmgn_failed": gmgn_failed,
        # BubbleMap tak terbaca (2026-09-18) — kolom Bubble Map menulis —.
        # Sejak 2026-09-19 kolomnya dihapus dan enrichment-nya OFF default,
        # jadi angka ini praktis selalu 0; key-nya tetap dikirim supaya
        # pembaca hasil scan lama (cache/session) tidak KeyError.
        "bubblemap_failed": bubblemap_failed,
        # Mint yang dividend-nya tidak terjawab (kedua sumber gagal). Pajak
        # lokal tetap bisa tampil; strategi tidak diubah. 0 bila fetch
        # dimatikan atau ``tax=False``.
        "tax_failed": tax_failed,
        # Lane hasil scan — UI memakainya untuk judul/pill tabel. Sejak 30M
        # dihapus (2026-09-16) ini selalu "24h".
        "lane": normalized,
        "timeframe": normalized,
        "gate": gate.strip(" ()"),
        "analyzed_at": int(time.time()),
    }


def scan_best_meteora(*, workers: int = 6, timeout: int = 25,
                      timeframe: str = "24h",
                      page_size: int = PAGE_SIZE,
                      rugcheck: bool = True,
                      gmgn: bool = True,
                      bubblemap: bool = False,
                      tax: bool = True) -> dict:
    """Wrapper lama :func:`scan_best_lane` (satu-satunya lane: 24H).

    Sejak 2026-09-13 kwarg ``timeframe`` **membatasi fetch**; sejak 2026-09-16
    hanya 24H yang ada, dan ``timeframe`` apa pun yang pernah dikenali
    (termasuk ``"30m"``/``"both"``) dipetakan ke 24H oleh
    :func:`normalize_best_lane`. ``rugcheck``, ``gmgn``, ``bubblemap`` dan
    ``tax`` diteruskan apa adanya (``bubblemap`` default-nya ``False`` sejak
    2026-09-19 — kolom Bubble Map dihapus, lihat :func:`scan_best_lane`).
    ``tax=False`` melewatkan tempelan pajak/dividend (test/offline).
    """
    return scan_best_lane(timeframe, workers=workers,
                          timeout=timeout, page_size=page_size,
                          rugcheck=rugcheck, gmgn=gmgn, bubblemap=bubblemap,
                          tax=tax)
