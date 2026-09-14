# -*- coding: utf-8 -*-
"""Listing pool **Krystal** (Robinhood Chain, chain id 4663) + rule F/V.

Card **🦅 Scan Best Pool Krystal** di halaman utama (``krystal_pool_ui.py``)
memakai modul ini sebagai satu-satunya sumber listing dan rule. Bentuknya
**menyalin** pipeline 🏆 Scan Best Pool Meteora (``meteora_screener`` +
``best_pool_ui``) — bukan mengubahnya — supaya dua card bisa dibandingkan
apple-to-apple:

- **Listing** — ``GET https://cloud-api.krystal.app/v1/pools`` dengan header
  ``KC-APIKey`` (10 unit/call). Chain Robinhood dikirim sebagai ``chainId``
  **integer** (``4663``) — sejak 2026-09-14 format lama ``robinhood@4663``
  ditolak API dengan 400 dan swagger mendeklarasikan ``chainId`` integer;
  :func:`fetch_pools` tetap retry otomatis dengan format lama bila integer
  ditolak. Empat protokol katalog Krystal untuk chain 4663
  diambil masing-masing satu request lalu digabung: **ramsescl, uniswapv2,
  uniswapv3, uniswapv4** (daftar diverifikasi publik lewat
  ``GET cloud-api.krystal.app/v1/chains`` — 0 unit — dan
  ``api.krystal.app/all/v1/lp_explorer/configs``). Detail field respons ada di
  ``docs/krystal_api.md``.
- **F = fee/TVL** = ``fee 24 jam ÷ TVL × 100`` (dari field Krystal
  ``stats24h.fee`` dan ``tvl``) — padanan ``fee_active_tvl_ratio`` Meteora.
- **V = volatility** = ``(max high − min low) ÷ min low × 100`` dari **24
  candle hourly** pool di GeckoTerminal network **robinhood**
  (``core.get_hourly_candles(..., network="robinhood")``). Pool tanpa candle =
  *volatility tidak tersedia*.
- **Gate lane 24H**: ``F/V ≥ KRYSTAL_FV_24H_MIN`` (5×, **inklusif** — tepat 5×
  lolos). V persis 0 → gugur **dan dibuang total dari listing** (tidak masuk
  tabel, tidak masuk "dilewati", tidak dihitung) — ∞ bukan kelolosan. Semua
  metrik wajib finite ≥ 0; metrik hilang → gugur "metrik tidak tersedia".
  Ambang dibaca dari konstanta **saat dipakai** (:func:`lane_fv_min`).
- **Lane 24H saja** (keputusan user 2026-09-14): fee Krystal yang tersedia
  baru berjendela 24 jam; lane 30M menyusul bila Krystal membuka window fee
  lebih pendek.
- **Urutan baris**: F/V terbesar → volume/TVL terbesar → dust %MC terkecil →
  simbol.
- **Holder**: hanya pool lolos gate yang di-enrich
  ``robinhood_holders.analyze_token`` (Blockscout chain 4663, FULL 100.000
  wallet, ``detail=False`` — hasilnya dipakai untuk tampilan saja, tidak
  menulis baseline/kronologi ke ``holder_history`` supaya tidak menggeser
  store yang dipakai fitur lain). Semua kandidat **ditunggu sampai selesai**
  (tidak ada budget waktu — yang lambat justru token ber-holder puluhan
  ribu). Kolom **Dust %MC** murni informasi, bukan syarat kelolosan.
- **Tanpa bukti = tanpa angka** (aturan yang sama dengan Meteora, 2026-09-13):
  hasil holder yang tidak layak (0 wallet / terpotong / sampel <
  ``MIN_USABLE_WALLETS``) menghasilkan ``dust_pct_mc = None`` + alasan di
  ``holders_note``, bukan ``0,000%`` palsu.

Semua fetch punya timeout dan kegagalan jadi **pesan di card** (``error``),
tidak pernah melempar ke halaman. Hasil scan dipakai bersama dengan cache
berkas (``scan_result_cache``) supaya refresh browser tidak menghapus tabel.
"""
from __future__ import annotations

import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

KRYSTAL_CARD_TITLE = "🦅 Scan Best Pool Krystal"

# ---------------------------------------------------------------------------
# Endpoint + katalog chain ( Krystal Cloud )
# ---------------------------------------------------------------------------
KRYSTAL_POOLS_URL = "https://cloud-api.krystal.app/v1/pools"
KRYSTAL_CHAINS_URL = "https://cloud-api.krystal.app/v1/chains"
# Format chainId Krystal: dulu ``nama@id`` (contoh resmi lama:
# ``ethereum@1``); sejak 2026-09-14 API menolak format itu dengan **400
# Bad Request** dan swagger (``cloud-api.krystal.app/swagger/doc.json``)
# mendeklarasikan ``chainId`` sebagai **integer** (mis. ``4663``).
KRYSTAL_CHAIN_ID = 4663
KRYSTAL_CHAIN_SLUG = "robinhood"
# Format lama ``nama@id`` — hanya tinggal sebagai label baris/tooltip dan
# cadangan fallback :func:`fetch_pools` bila API kembali menerimanya.
KRYSTAL_CHAIN_PARAM = f"{KRYSTAL_CHAIN_SLUG}@{KRYSTAL_CHAIN_ID}"
# Nilai ``chainId`` yang dikirim ke API sekarang: integer polos.
KRYSTAL_CHAIN_QUERY = KRYSTAL_CHAIN_ID
# Empat protokol katalog Krystal untuk chain 4663 (verifikasi 2026-09-14 lewat
# /v1/chains + lp_explorer/configs). Urutan = urutan request.
KRYSTAL_PROTOCOLS = ("ramsescl", "uniswapv2", "uniswapv3", "uniswapv4")
KRYSTAL_PROTOCOL_LABELS = {
    "ramsescl": "Ramses CL",
    "uniswapv2": "Uniswap V2",
    "uniswapv3": "Uniswap V3",
    "uniswapv4": "Uniswap V4",
}
# sortBy: 0 = APR, 1 = TVL, 2 = Volume 24h, 3 = Fee (dokumentasi swagger).
KRYSTAL_SORT_APR = 0
KRYSTAL_SORT_TVL = 1
KRYSTAL_SORT_VOLUME = 2
KRYSTAL_SORT_FEE = 3
KRYSTAL_TIMEOUT = 25
KRYSTAL_LIMIT = 20          # pool per protokol (4 protokol = 4 x 10 unit/scan)
KRYSTAL_MIN_TVL = 1_000.0   # default server; diturunkan bila perlu lewat kwarg
KRYSTAL_VOLATILITY_HOURS = 24
KRYSTAL_WORKERS = 4

# ---------------------------------------------------------------------------
# Rule lane (salinan rule 🏆 Best Pool Meteora, angka dibaca saat dipakai)
# ---------------------------------------------------------------------------
KRYSTAL_FV_24H_MIN = 5.0
KRYSTAL_LANES = ("24h",)
KRYSTAL_LANE_LABELS = {"24h": "24H"}
# Tie-break dust dibulatkan ke presisi tampilan card (3 desimal).
KRYSTAL_DUST_SORT_DECIMALS = 3

# Token sisi quote Robinhood (stable/WETH/USDG): sisi ini bukan yang
# dihitung dust-nya. Pool yang dua-duanya quote dibuang
# (:func:`unanalysable_row`) — holder WETH dibagi MC WETH selalu ≈ 0,000%.
KRYSTAL_QUOTE_SYMBOLS = frozenset({
    "WETH", "ETH", "WBTC", "BTC", "USDC", "USDT", "USDG", "USDE", "USDF",
    "DAI", "USDS", "USD+", "WSTETH",
})

# Nama key API key — **tidak pernah** di-commit nilainya.
KRYSTAL_KEY_ENV = "KRYSTAL_API_KEY"
KRYSTAL_KEY_SECRETS = "KRYSTAL_API_KEY"
KRYSTAL_KEY_CONFIG = "krystal_api_key"

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "config.json")


def _float(value, default: float = 0.0) -> float:
    """Float aman: ``None``/teks kosong/NaN → ``default``."""
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _maybe_float(value):
    """Float atau ``None`` (NaN/Infinity/bool/tipe salah → ``None``).

    Saringan harus bisa membedakan \"angkanya nol\" dari \"datanya tidak ada\".
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# ---------------------------------------------------------------------------
# API key (Streamlit secrets -> env -> config.json; tidak pernah dilog)
# ---------------------------------------------------------------------------
def _secrets_api_key() -> str:
    try:
        import streamlit as st
        if KRYSTAL_KEY_SECRETS not in st.secrets:
            return ""
        value = st.secrets[KRYSTAL_KEY_SECRETS]
    except Exception:  # noqa: BLE001 - di luar Streamlit / tanpa secrets
        return ""
    return str(value or "").strip()


def _config_api_key() -> str:
    try:
        import json
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            cfg = json.load(handle) or {}
    except Exception:  # noqa: BLE001 - config opsional
        return ""
    return str(cfg.get(KRYSTAL_KEY_CONFIG) or "").strip()


def api_key() -> str:
    """API key Krystal aktif (``""`` bila belum dipasang).

    Urutan: Streamlit ``secrets`` (``KRYSTAL_API_KEY``) → env
    ``KRYSTAL_API_KEY`` → ``krystal_api_key`` di ``config.json``. Nilainya
    **tidak pernah** dicetak, di-log, atau disimpan ke cache hasil scan.
    """
    for value in (_secrets_api_key(),
                  str(os.environ.get(KRYSTAL_KEY_ENV) or "").strip(),
                  _config_api_key()):
        if value:
            return value
    return ""


def api_key_configured() -> bool:
    """True bila API key Krystal terpasang (card menampilkan pesan bila tidak)."""
    return bool(api_key())


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def _http_get(url: str, params: dict, *, timeout: int = KRYSTAL_TIMEOUT,
              with_key: bool = True) -> object:
    """GET JSON; raise bila HTTP/parse gagal (pemanggil yang menangani)."""
    headers = {"accept": "application/json"}
    if with_key:
        key = api_key()
        if not key:
            raise RuntimeError("KRYSTAL_API_KEY belum dipasang")
        headers["KC-APIKey"] = key
    response = requests.get(url, params=params, headers=headers,
                            timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_supported_chains(*, timeout: int = KRYSTAL_TIMEOUT) -> list[dict]:
    """``GET /v1/chains`` — katalog chain + protokol (publik, **0 unit**).

    Dipakai sebagai jaring pengaman: kalau Krystal mencabut dukungan chain
    4663, card bisa mengatakan itu daripada menampilkan tabel kosong tanpa
    alasan. Gagal → ``[]`` (bukan exception).
    """
    try:
        payload = _http_get(KRYSTAL_CHAINS_URL, {}, timeout=timeout,
                            with_key=False)
    except Exception:  # noqa: BLE001 - katalog hanya pelengkap
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def chain_supported(chain_id: int = KRYSTAL_CHAIN_ID, *,
                    timeout: int = KRYSTAL_TIMEOUT) -> bool:
    """True bila chain ada di katalog Krystal (publik, 0 unit)."""
    for row in fetch_supported_chains(timeout=timeout):
        if int(_float(row.get("id"), -1)) == int(chain_id):
            return True
    return False


def fetch_pools(*, protocol: str, chain: int | str = KRYSTAL_CHAIN_QUERY,
                limit: int = KRYSTAL_LIMIT,
                min_tvl: float | None = KRYSTAL_MIN_TVL,
                sort_by: int = KRYSTAL_SORT_APR,
                timeout: int = KRYSTAL_TIMEOUT) -> list[dict]:
    """Satu halaman pool Krystal untuk satu protokol. Gagal → raise.

    ``chainId`` dikirim sebagai **integer** (``4663``) sesuai swagger
    Krystal 2026-09-14; format lama ``robinhood@4663`` mulai ditolak 400.
    Bila integer justru ditolak 400 (mis. API berganti lagi), satu retry
    otomatis memakai format ``nama@id`` — dan sebaliknya.

    Biaya 10 unit per call (dokumentasi Krystal), jadi pemanggil
    (:func:`fetch_all_pools`) menjumlahkan protokolnya — jangan memanggil ini
    di dalam loop render.
    """
    params = {
        "chainId": chain,
        "protocol": str(protocol or ""),
        "sortBy": int(sort_by),
        "limit": max(1, min(int(limit), 5000)),
    }
    if min_tvl is not None:
        params["minTvl"] = int(min_tvl)
    try:
        payload = _http_get(KRYSTAL_POOLS_URL, params, timeout=timeout)
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 400:
            raise
        # 400 = parameter ditolak; coba satu kali dengan format chainId
        # lainnya sebelum menyerah (perubahan format 2026-09-14).
        fallback = (KRYSTAL_CHAIN_QUERY
                    if str(chain) == KRYSTAL_CHAIN_PARAM
                    else KRYSTAL_CHAIN_PARAM)
        payload = _http_get(KRYSTAL_POOLS_URL, dict(params,
                                                    chainId=fallback),
                            timeout=timeout)
    if isinstance(payload, dict):
        rows = payload.get("data")
        rows = rows if isinstance(rows, list) else []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def fetch_all_pools(*, protocols=KRYSTAL_PROTOCOLS, limit: int = KRYSTAL_LIMIT,
                    min_tvl: float | None = KRYSTAL_MIN_TVL,
                    timeout: int = KRYSTAL_TIMEOUT) -> tuple[list[dict], str]:
    """Pool semua protokol chain 4663 → ``(rows, error)``; dedup ``poolAddress``.

    Kegagalan satu protokol **tidak** menggagalkan yang lain: alasannya
    dikumpulkan di ``error`` (ditampilkan card) dan protokol itu dilewati.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []
    for protocol in protocols or ():
        try:
            payload = fetch_pools(protocol=protocol, limit=limit,
                                  min_tvl=min_tvl, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - kegagalan = pesan card
            errors.append(f"{protocol}: {exc}")
            continue
        for pool in payload:
            address = str(_first_key(pool, ("poolAddress", "pool_address",
                                            "address", "id")) or "").strip()
            key = address.lower() or f"{protocol}:{len(rows)}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(pool)
    return rows, " · ".join(errors)


# ---------------------------------------------------------------------------
# Normalisasi payload Krystal -> baris tabel
# ---------------------------------------------------------------------------
def _first_key(payload: dict, names) -> object:
    """Nilai pertama yang ada dari beberapa kemungkinan nama field.

    Field Krystal tidak dijanjikan stabil (dokumentasi menyebut ``stats24h``;
    contoh landing page memakai bentuk itu), jadi pembacaan dibuat toleran
    terhadap ``stats24h`` / ``stats_24h`` / ``fee24h`` tanpa menebak-nebak nilai.
    """
    for name in names:
        if isinstance(payload, dict) and payload.get(name) is not None:
            return payload.get(name)
    return None


def _stats(pool: dict, window: str = "24h") -> dict:
    """Blok statistik satu window: ``stats24h`` → ``stats_24h`` → ``{}``."""
    for name in (f"stats{window}", f"stats_{window}", window):
        value = pool.get(name) if isinstance(pool, dict) else None
        if isinstance(value, dict):
            return value
    return {}


def _token(pool: dict, index: int) -> dict:
    value = (pool or {}).get(f"token{index}")
    return value if isinstance(value, dict) else {}


def _protocol_name(pool: dict, default: str = "") -> str:
    value = (pool or {}).get("protocol")
    if isinstance(value, dict):
        return str(value.get("name") or default or "").strip().lower()
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return str(default or "").strip().lower()


def protocol_label(protocol: str) -> str:
    """Nama protokol siap tampil (``ramsescl`` → ``Ramses CL``)."""
    key = str(protocol or "").strip().lower()
    return KRYSTAL_PROTOCOL_LABELS.get(key, key.upper() or "?")


def base_token(pool: dict) -> tuple[dict, dict]:
    """``(token_base, token_quote)`` — base = sisi bukan stable/WETH/USDG.

    Fallback ``token0`` (aturan yang sama dengan ``meteora_screener``):
    bila dua sisi sama-sama quote atau sama-sama bukan quote, sisi pertama
    yang dianggap base, dan penanda ``quote_only`` yang menentukan barisnya
    dibuang (:func:`unanalysable_row`).
    """
    token0 = _token(pool, 0)
    token1 = _token(pool, 1)
    symbol0 = str(token0.get("symbol") or "").strip().upper()
    symbol1 = str(token1.get("symbol") or "").strip().upper()
    quote0 = symbol0 in KRYSTAL_QUOTE_SYMBOLS
    quote1 = symbol1 in KRYSTAL_QUOTE_SYMBOLS
    if quote0 and not quote1:
        return token1, token0
    if quote1 and not quote0:
        return token0, token1
    return token0, token1


def normalize_pool(pool: dict, *, protocol: str = "",
                   timeframe: str = "24h") -> dict:
    """Satu payload pool Krystal → baris tabel card.

    Field yang dipakai rule (F, TVL, volume, pasangan token, protokol,
    alamat pool) selalu diisi; field yang tidak terbaca jadi ``None`` supaya
    gate-nya menggugurkan baris ("metrik tidak tersedia") daripada
    menampilkan angka nol palsu.
    """
    pool = pool or {}
    window = "24h"
    stats = _stats(pool, window)
    base, quote = base_token(pool)
    tvl = _maybe_float(_first_key(pool, ("tvl", "tvlUsd", "totalTvl")))
    fee = _maybe_float(_first_key(stats, ("fee", "fees", "feeUsd")))
    volume = _maybe_float(_first_key(stats, ("volume", "volumeUsd")))
    apr = _maybe_float(_first_key(stats, ("apr", "apr24h")))
    symbol0 = str(base.get("symbol") or "").strip().upper()
    symbol1 = str(quote.get("symbol") or "").strip().upper()
    protocol_name = _protocol_name(pool, protocol)
    return {
        "source": "krystal",
        "timeframe": timeframe,
        "chain": KRYSTAL_CHAIN_PARAM,
        "pool_address": str(_first_key(pool, ("poolAddress", "pool_address",
                                              "address", "id")) or "").strip(),
        "protocol": protocol_name,
        "protocol_label": protocol_label(protocol_name or protocol),
        "fee_tier": _maybe_float(_first_key(pool, ("feeTier", "fee_tier"))),
        "ca": str(base.get("address") or "").strip(),
        "symbol": symbol0 or "?",
        "base_symbol": symbol0 or "?",
        "quote_symbol": symbol1 or "?",
        "pair": f"{symbol0 or '?'}/{symbol1 or '?'}",
        "quote_address": str(quote.get("address") or "").strip(),
        "quote_only": bool(symbol0 and symbol1
                           and symbol0 in KRYSTAL_QUOTE_SYMBOLS
                           and symbol1 in KRYSTAL_QUOTE_SYMBOLS),
        "tvl": tvl,
        "fee": fee,
        "volume": volume,
        "apr": apr,
        # F = fee 24 jam / TVL x 100 (padanan fee_active_tvl_ratio Meteora).
        "fee_tvl_ratio": (fee / tvl * 100.0
                          if (fee is not None and tvl not in (None, 0)
                              and tvl > 0) else None),
        # Kunci urut kedua: volume 24 jam / TVL x 100.
        "vol_tvl_ratio": (volume / tvl * 100.0
                          if (volume is not None and tvl not in (None, 0)
                              and tvl > 0) else None),
        # Diisi :func:`enrich_volatility` (V) lalu :func:`enrich_holders`.
        "volatility": None,
        "volatility_candles": 0,
        "volatility_note": "",
        "mc": None,
        "price": None,
        "analysis": None,
        "dust_pct_mc": None,
        "dust_count": None,
        "real_count": None,
        "holders_proof": False,
        "holders_note": "",
    }


def rows_from_pools(pools, *, protocol: str = "",
                    timeframe: str = "24h") -> list[dict]:
    """Baris listing (dedup ``pool_address``) dari payload pool Krystal."""
    rows: list[dict] = []
    seen: set[str] = set()
    for pool in pools or []:
        if not isinstance(pool, dict):
            continue
        row = normalize_pool(pool, protocol=protocol, timeframe=timeframe)
        address = str(row.get("pool_address") or "").lower()
        if address:
            if address in seen:
                continue
            seen.add(address)
        rows.append(row)
    return rows


def unanalysable_row(row: dict | None) -> str:
    """Alasan baris tidak punya token base yang bisa di-analisa (kosong = bisa).

    Sama seperti Meteora: pool ``WETH/USDC`` yang di-scan holder-nya lalu
    dibagi MC WETH selalu menghasilkan ``0,000%`` — angka "paling bersih" yang
    tidak berarti apa-apa. Baris tanpa alamat token base juga dibuang.
    """
    row = row or {}
    if not str(row.get("ca") or "").strip():
        return "mint token base tidak terbaca"
    if row.get("quote_only"):
        return "pool quote-only (tanpa sisi token yang bisa di-scan)"
    return ""


def drop_quote_rows(rows) -> tuple[list[dict], int]:
    """Buang baris tanpa sisi token; return ``(kept, dropped)``."""
    kept, dropped = [], 0
    for row in rows or []:
        if unanalysable_row(row):
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped


# ---------------------------------------------------------------------------
# Metrik + gate (salinan rule Meteora, ambang dibaca saat dipakai)
# ---------------------------------------------------------------------------
def normalize_krystal_lane(value, *, default: str | None = "24h") -> str | None:
    """Lane card Krystal — baru **24H**; nilai asing → ``default``."""
    text = str(value if value is not None else "").strip().lower()
    if text in ("24h", "24 jam", "24hours", "1d", ""):
        return "24h"
    return default


def lane_fv_min(lane="24h") -> float:
    """Ambang F/V lane — dibaca dari konstanta **saat dipanggil**."""
    return float(KRYSTAL_FV_24H_MIN)


def lane_fv_inclusive(lane="24h") -> bool:
    """Ambang lane 24H inklusif (``F/V >= 5×`` — tepat 5× lolos)."""
    return True


def lane_fv_sign(lane="24h") -> str:
    """Tanda pembanding ambang untuk teks UI (``≥``)."""
    return "≥" if lane_fv_inclusive(lane) else ">"


def krystal_lane_gate_label(lane="24h") -> str:
    """Label ambang lane untuk pill/tooltip, angkanya dari konstanta."""
    normalized = normalize_krystal_lane(lane)
    label = KRYSTAL_LANE_LABELS.get(normalized, str(normalized).upper())
    return f"{label}: F/V {lane_fv_sign(normalized)} {lane_fv_min(normalized):g}×"


def row_fv_ratio(row: dict | None):
    """``F ÷ V`` satu baris (``None`` = tidak ada; ``inf`` bila V = 0).

    Satu sumber angka untuk saringan, urutan, DAN kolom F/V card — angka yang
    diprioritaskan tidak pernah beda dengan angka yang tampil.
    """
    row = row or {}
    fee = _maybe_float(row.get("fee_tvl_ratio"))
    vol = _maybe_float(row.get("volatility"))
    if fee is None or vol is None:
        return None
    if vol == 0:
        return math.inf if fee > 0 else 0.0
    return fee / vol


def row_volatility_zero(row: dict | None) -> bool:
    """True bila volatility **persis 0** — pool tanpa pergerakan.

    Baris seperti itu gugur gate **dan** dibuang dari listing (permintaan
    user: "jika volatility 0 jangan tampilkan"): tidak masuk tabel lolos,
    tidak masuk "dilewati", tidak dihitung. ``None``/negatif/nonfinite
    **bukan** nol — tetap tampil di "dilewati" dengan alasan metriknya.
    """
    value = _maybe_float((row or {}).get("volatility"))
    return bool(value is not None and math.isfinite(value) and value == 0)


def row_krystal_gaps(row: dict | None, *, lane="24h") -> list[str]:
    """Saringan sebelum enrichment holder — satu aturan: ``F/V ≥ 5×``.

    - metrik (F atau V) tidak ada / nonfinite / negatif → **gugur**
      ``"metrik tidak tersedia"``;
    - V persis 0 → gugur ``"24H: volatility 0 — F/V tidak terukur"`` (dan
      dibuang penuh dari listing oleh :func:`row_volatility_zero`);
    - ``F < 5 × V`` → gugur ``"24H: F/V < 5×"`` (inklusif: tepat 5× lolos).
    """
    row = row or {}
    normalized = normalize_krystal_lane(lane, default=None)
    if normalized is None:
        return ["timeframe tidak dikenal"]
    label = KRYSTAL_LANE_LABELS.get(normalized, str(normalized).upper())
    fee = _maybe_float(row.get("fee_tvl_ratio"))
    vol = _maybe_float(row.get("volatility"))
    if any(x is None or x < 0 for x in (fee, vol)):
        return ["metrik tidak tersedia"]
    if vol == 0:
        return [f"{label}: volatility 0 — F/V tidak terukur"]
    minimum = lane_fv_min(normalized)
    passed = fee >= minimum * vol if lane_fv_inclusive(normalized) \
        else fee > minimum * vol
    if passed:
        return []
    sign = "<" if lane_fv_inclusive(normalized) else "≤"
    return [f"{label}: F/V {sign} {minimum:g}×"]


def row_vol_tvl_ratio(row: dict | None):
    """Rasio volume 24 jam / TVL (%) — kunci urut kedua."""
    row = row or {}
    ratio = _maybe_float(row.get("vol_tvl_ratio"))
    if ratio is not None:
        return ratio
    volume = _maybe_float(row.get("volume"))
    tvl = _maybe_float(row.get("tvl"))
    if volume is None or tvl is None or tvl <= 0:
        return None
    return volume / tvl * 100.0


def row_dust_pct(row: dict | None):
    """Dust % MC satu baris (``None`` bila tanpa bukti holder).

    Sumbernya ``analysis.holders`` hasil :func:`enrich_holders`; hasil holder
    yang tidak layak (0 wallet / terpotong / sampel < 40 wallet) selalu
    ``None`` — tanpa bukti, barisnya tidak pernah menampilkan ``0,000%``.
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


def holders_usable(holders) -> bool:
    """Kelayakan data holder (satu sumber: ``holder_history.holders_usable``)."""
    from holder_history import holders_usable as _usable
    return bool(_usable(holders or {}))


def sort_krystal_rows(rows) -> list[dict]:
    """Urutan tabel: **F/V terbesar → volume/TVL terbesar → dust terkecil**.

    Salinan :func:`meteora_screener.sort_best_rows`: baris tanpa F/V paling
    bawah; tie-break dust dibulatkan ke presisi tampilan card
    (:data:`KRYSTAL_DUST_SORT_DECIMALS`) supaya pool yang di layar sama-sama
    "0,030%" dianggap seri; simbol alfabetis jadi penentu terakhir.
    """
    def _key(row):
        row = row or {}
        pct = _maybe_float(row_dust_pct(row))
        ratio = row_vol_tvl_ratio(row)
        fv = row_fv_ratio(row)
        return (
            0 if fv is not None else 1,
            -(fv if fv is not None else 0.0),
            0 if ratio is not None else 1,
            -(ratio if ratio is not None else -1.0),
            round(pct, KRYSTAL_DUST_SORT_DECIMALS) if pct is not None else 0.0,
            str(row.get("symbol") or "").upper(),
        )

    return sorted(list(rows or []), key=_key)


def filter_krystal_rows(rows, *, lane="24h") -> tuple[list[dict], int]:
    """``(lolos gate, jumlah gagal yang TAMPIL di "dilewati")``.

    Baris volatility 0 **tidak ikut dihitung** — dibuang penuh dari listing.
    """
    rows = list(rows or [])
    kept = [row for row in rows if not row_krystal_gaps(row, lane=lane)]
    dropped = sum(1 for row in rows
                  if row_krystal_gaps(row, lane=lane)
                  and row_volatility_zero(row))
    return kept, len(rows) - len(kept) - dropped


# ---------------------------------------------------------------------------
# Volatility (V) — 24 candle hourly GeckoTerminal network "robinhood"
# ---------------------------------------------------------------------------
def volatility_from_candles(candles) -> tuple:
    """``(volatility %, jumlah candle)`` dari candle hourly.

    Rumus: ``(max high − min low) ÷ min low × 100`` — rentang tertinggi
    terhadap titik terendah di jendela 24 jam. ``(None, 0)`` bila tidak ada
    candle yang bisa dipakai (pool belum ter-indeks GeckoTerminal): V tidak
    tersedia, dan gate menggugurkan barisnya dengan alasan "metrik tidak
    tersedia" — bukan 0% (0% berarti "harga tidak bergerak", klaim yang tidak
    bisa dibuktikan tanpa data).
    """
    highs, lows = [], []
    for candle in candles or []:
        if not isinstance(candle, dict):
            continue
        high = _maybe_float(candle.get("high"))
        low = _maybe_float(candle.get("low"))
        if high is None or low is None or low <= 0:
            continue
        highs.append(high)
        lows.append(low)
    if not highs or not lows:
        return None, 0
    top, bottom = max(highs), min(lows)
    if bottom <= 0:
        return None, 0
    return (top - bottom) / bottom * 100.0, len(highs)


def fetch_pool_volatility(pool_address: str, *,
                          hours: int = KRYSTAL_VOLATILITY_HOURS,
                          timeout: int = KRYSTAL_TIMEOUT,
                          network: str = "robinhood") -> tuple:
    """``(volatility %, jumlah candle)`` satu pool dari GeckoTerminal.

    Network default **robinhood** (chain 4663). Kegagalan transport menghasilkan
    ``(None, 0)`` — pasar tidak pernah menggagalkan sebuah scan.
    """
    import core

    if not str(pool_address or "").strip():
        return None, 0
    try:
        candles = core.get_hourly_candles(pool_address, limit_hours=hours,
                                          network=network, timeout=timeout)
    except Exception:  # noqa: BLE001 - candle hanya konteks
        return None, 0
    return volatility_from_candles(candles)


def enrich_volatility(rows, *, hours: int = KRYSTAL_VOLATILITY_HOURS,
                      timeout: int = KRYSTAL_TIMEOUT, progress=None) -> list[dict]:
    """Isi V tiap baris dari 24 candle hourly ( sequential, murah, 1 req/pool ).

    Dijalankan **sebelum** gate dan jauh sebelum holder: candle GeckoTerminal
    gratis dan cepat, sedangkan holder Blockscout FULL bisa belasan menit per
    token — pool yang sudah pasti gugur tidak boleh membakar kuota itu.
    """
    rows = list(rows or [])
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        volatility, candles = fetch_pool_volatility(
            row.get("pool_address"), hours=hours, timeout=timeout)
        row["volatility"] = volatility
        row["volatility_candles"] = candles
        row["volatility_note"] = ("" if candles
                                  else "volatility tidak tersedia (tanpa candle)")
        if progress:
            try:
                progress(index, total, f"candle {row.get('symbol') or '?'}")
            except Exception:  # noqa: BLE001
                pass
    return rows


# ---------------------------------------------------------------------------
# Holder (Dust %MC) — Blockscout FULL, semua kandidat ditunggu
# ---------------------------------------------------------------------------
def _holders_gap(analysis, holders: dict) -> str:
    """Alasan singkat "angka dust tidak bisa dipercaya" (``holders_note``)."""
    if not isinstance(analysis, dict):
        return "⚠️ holder gagal di-scan"
    error = str(holders.get("error") or holders.get("fetch_error") or "").strip()
    if holders.get("blocked"):
        return "⚠️ Blockscout 403 — pasang BLOCKSCOUT_API_KEY"
    if holders.get("truncated"):
        return "⚠️ holder terpotong" + (f": {error[:48]}" if error else "")
    fetched = int(_float(holders.get("total_fetched"), 0.0))
    wallets = int(_float(holders.get("wallets_analyzed"), 0.0)) or fetched
    if fetched <= 0:
        return ("⚠️ 0 holder"
                + (f": {error[:48]}" if error else " (provider mati)"))
    from holder_history import MIN_USABLE_WALLETS
    return (f"⚠️ sampel {wallets} wallet — butuh "
            f"≥ {int(MIN_USABLE_WALLETS)} untuk dust %MC")


def enrich_holders(rows, *, max_wallets: int | None = None,
                   workers: int = KRYSTAL_WORKERS,
                   progress=None) -> list[dict]:
    """Dust %MC per token base (Blockscout, FULL) untuk baris yang diterima.

    - **FULL** (``holder_history.FULL_SCAN_MAX_WALLETS`` = 100.000): dust ada
      di ekor daftar holder, jadi cap kecil selalu menghasilkan 0,000%;
    - **tanpa budget waktu**: ``as_completed`` tanpa timeout — token
      ber-holder puluhan ribu memang butuh 10-15 menit dan hasilnya tetap
      dipakai (keputusan yang sama dengan card Best Robinhood Coin);
    - satu token base bisa muncul di beberapa pool → di-scan sekali.
    """
    rows = list(rows or [])
    if not rows:
        return rows
    import robinhood_holders
    from holder_history import FULL_SCAN_MAX_WALLETS

    max_wallets = int(max_wallets or FULL_SCAN_MAX_WALLETS)
    by_ca: dict[str, list[dict]] = {}
    for row in rows:
        ca = str(row.get("ca") or "").strip()
        if ca:
            by_ca.setdefault(ca, []).append(row)
    mints = list(by_ca)
    total = len(mints)
    analyses: dict[str, dict | None] = {}
    workers = max(1, min(int(workers), 8))

    def _job(ca: str):
        row = by_ca[ca][0]
        try:
            return ca, robinhood_holders.analyze_token(
                ca, str(row.get("symbol") or "?"),
                market_cap=_float(row.get("mc")),
                price_usd=_float(row.get("price")),
                max_wallets=max_wallets,
                fetch_market=True,
                detail=False), None
        except Exception as exc:  # noqa: BLE001 - kegagalan = tanpa angka
            return ca, None, str(exc)

    if mints:
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_job, mint): mint for mint in mints}
            for future in as_completed(futures):
                ca, analysis, error = future.result()
                analyses[ca] = analysis
                if error:
                    _log("error", f"holder {ca[:10]}… gagal: {str(error)[:140]}")
                done += 1
                if progress:
                    try:
                        progress(done, total, ca[:8])
                    except Exception:  # noqa: BLE001
                        pass

    for row in rows:
        analysis = analyses.get(str(row.get("ca") or ""))
        row["analysis"] = analysis
        holders = (analysis or {}).get("holders") or {}
        mc_used = _float((analysis or {}).get("marketcap"), 0.0)
        if mc_used > 0:
            # Pembagi dust = MC DexScreener yang benar-benar dipakai
            # ``analyze_token`` (aturan 2026-09-13): kolom MC dan Dust %MC
            # satu sumber, tidak pernah beda angka.
            row["mc"] = mc_used
        price_used = _float((analysis or {}).get("price"), 0.0)
        if price_used > 0:
            row["price"] = price_used
        proof = holders_usable(holders)
        row["holders_proof"] = bool(proof)
        row["holders_note"] = "" if proof else _holders_gap(analysis, holders)
        row["dust_count"] = holders.get("dust_count") if proof else None
        row["dust_pct_mc"] = holders.get("dust_pct_mc") if proof else None
        row["real_count"] = holders.get("real_count") if proof else None
    return rows


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
def _log(level: str, message: str) -> None:
    try:
        import activity_log
        getattr(activity_log, level, activity_log.info)("scan-krystal", message)
    except Exception:  # noqa: BLE001 - log hanya pelengkap
        pass


def scan_krystal_lane(lane: str = "24h", *, protocols=KRYSTAL_PROTOCOLS,
                      limit: int = KRYSTAL_LIMIT,
                      min_tvl: float | None = KRYSTAL_MIN_TVL,
                      max_wallets: int | None = None,
                      workers: int = KRYSTAL_WORKERS,
                      progress=None,
                      timeout: int = KRYSTAL_TIMEOUT) -> dict:
    """Scan **satu lane** (baru 24H) → dict hasil siap render.

    Alurnya persis 🏆 Best Pool Meteora:

    1. listing Krystal per protokol (4 request, dedup ``poolAddress``);
    2. normalisasi + buang pool tanpa sisi token (``skipped_quote``);
    3. **V** dari 24 candle hourly GeckoTerminal network robinhood;
    4. gate ``F/V ≥ 5×`` **sebelum** holder → yang gugur masuk
       ``hidden_rows`` (kecuali V=0: dibuang penuh, ``dropped_volatility``);
    5. holder FULL Blockscout hanya untuk yang lolos, lalu urut
       :func:`sort_krystal_rows`.

    Tidak pernah melempar: kegagalan API jadi ``error`` (pesan card).
    """
    normalized = normalize_krystal_lane(lane)
    label = KRYSTAL_LANE_LABELS.get(normalized, str(normalized).upper())
    gate = krystal_lane_gate_label(normalized)
    _log("info", f"scan mulai: listing Krystal {KRYSTAL_CHAIN_PARAM} "
                 f"({gate}, protokol {', '.join(protocols or [])})")
    errors: list[str] = []
    pools, pool_error = fetch_all_pools(protocols=protocols, limit=limit,
                                        min_tvl=min_tvl, timeout=timeout)
    if pool_error:
        errors.append(pool_error)
        _log("error", f"listing Krystal gagal: {pool_error[:160]}")
    rows = rows_from_pools(pools, timeframe=normalized)
    fetched = len(rows)
    rows, skipped_quote = drop_quote_rows(rows)
    rows = enrich_volatility(rows, timeout=timeout, progress=progress)
    failed_rows = [dict(row, krystal_gaps=row_krystal_gaps(row, lane=normalized))
                   for row in rows if row_krystal_gaps(row, lane=normalized)]
    hidden_rows = [row for row in failed_rows if not row_volatility_zero(row)]
    dropped_volatility = len(failed_rows) - len(hidden_rows)
    rows, hidden_metric = filter_krystal_rows(rows, lane=normalized)
    volatility_missing = sum(1 for row in hidden_rows
                             if _maybe_float(row.get("volatility")) is None)
    if rows:
        rows = enrich_holders(rows, max_wallets=max_wallets, workers=workers,
                              progress=progress)
    kept = sort_krystal_rows(rows)
    _log("info", f"scan selesai: {len(kept)} pool tampil dari {fetched} "
                 f"listing Krystal ({hidden_metric} gagal F/V tanpa scan holder"
                 + (f", {dropped_volatility} pool volatility 0 dibuang"
                    if dropped_volatility else "")
                 + (f", {skipped_quote} pool quote dilewati"
                    if skipped_quote else "") + ")")
    return {
        "rows": kept,
        "hidden_rows": hidden_rows,
        "error": " · ".join(errors),
        "fetched": fetched,
        "hidden_metric": hidden_metric,
        "dropped_volatility": dropped_volatility,
        "skipped_quote": skipped_quote,
        "volatility_missing": volatility_missing,
        "protocols": list(protocols or []),
        "lane": normalized,
        "timeframe": normalized,
        "gate": gate,
        "analyzed_at": int(time.time()),
    }
