# -*- coding: utf-8 -*-
"""🏆 Scan Best Pool Meteora — logika inti, tanpa Streamlit.

Permintaan user (2026-11-14, terbaru):
- Listing Meteora pool-discovery, timeframe 12h, category=all,
  dengan filter server-side persis dari request user (FLOW_SERVER_FILTER).
- Tidak ada filter seleksi lokal (avg volume, fee/active TVL, volatility, fee tier dihapus).
- Keamanan tetap (2026-11-14): blokir bila mint/freeze authority aktif atau top holders > 30 %;
  peringatan bila top holders > 15 %, dev > 5 %, atau LP keluar > masuk saat TVL < $50K.
- Urutan: rasio avg volume per menit ÷ TVL terbesar dulu (permintaan user 2026-11-15). Seri: urutan listing.
- Alert Telegram (tiap jam) berisi RINGKASAN saja: BEST POOL (HIGH RISK) dan 4H ≥ 10% (CURVE) SL OOR (2026-11-18).
"""
from __future__ import annotations

import html as _html
import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import links

POOLS_URL = "https://pool-discovery-api.datapi.meteora.ag/pools"
HTTP_TIMEOUT = 25
USER_AGENT = "Mozilla/5.0 (wallet-depth-pool-flow)"

FLOW_TIMEFRAME = "12h"
# Listing = curl user terbaru (12H, category all, urut fee/TVL, filter umur token). Tidak ada filter lokal.
FLOW_CATEGORY = "all"
FLOW_SORT_BY = "fee_tvl_ratio:desc"  # dikembalikan sesuai curl user terbaru
# Pemisahan tabel (permintaan user 2026-11-15). Fee/TVL = fee_tvl_ratio (%, 12H),
# volatility dalam %. Volatility di bawah 0,01 % dianggap tidak terukur (tidak masuk tabel mana pun).
FLOW_VOLATILITY_MEASURABLE_MIN = 0.01
FLOW_FEE_PRINTER_MULT = 2.0   # FEE PRINTER (SPOT): fee/TVL > 2 × volatility
FLOW_BAND_LOW_MULT = 0.75     # SLOW FEE PRINTER: 0,75 × volatility ≤ fee/TVL ≤ 1,5 × volatility (permintaan user, 2026-11-19)
FLOW_BAND_HIGH_MULT = 1.5     # batas atas SLOW FEE PRINTER (inklusif)
FLOW_HIGH_RISK_MIN_MULT = 3.0   # HIGH RISK FEE PRINTER: 3 × volatility < fee/TVL (permintaan user, 2026-11-19)
FLOW_HIGH_RISK_MAX_MULT = 10.0  # HIGH RISK FEE PRINTER: fee/TVL < 10 × volatility (2026-11-19, user request)
FLOW_HIGH_RISK_MIN_FEE_TVL = 10.0  # %: HIGH RISK FEE PRINTER hanya fee/TVL minimal 10 % (permintaan user, 2026-11-19)
FLOW_MIN_FEE_TVL_12H = 5.0  # %: tabel 12H hanya pool dengan fee/TVL minimal 5 % (permintaan user, 2026-11-19)
FLOW_SLOW_MIN_TOKEN_AGE_HOURS = 24.0  # SLOW FEE PRINTER: umur token dasar minimal 24 jam (permintaan user, 2026-11-19)
FLOW_VERY_HIGH_MIN_MULT = 20.0  # VERY HIGH RISK POOL / BISA DUMP SEWAKTU2: fee/TVL ≥ 20 × volatility (2026-11-18)
# Peringatan keamanan (label saja, tidak menyaring).
# tampil dengan label. Field kosong tidak dihitung sebagai masalah.
FLOW_SEC_HOLDERS_BLOCK = 30.0           # % top_holders_pct token dasar, blokir di atas ini
FLOW_SEC_HOLDERS_WARN = 15.0            # % top_holders_pct, peringatan di atas ini
FLOW_SEC_DEV_WARN = 5.0                 # % dev_balance_pct, peringatan di atas ini
FLOW_SEC_LP_OUTFLOW_TVL_MAX = 50_000.0  # USD: peringatan LP keluar hanya bila TVL di bawah ini
# Filter server (curl user terbaru, persis). Satu-satunya filter seleksi pool.
# Tanpa batas umur token (2026-11-18, user request).
FLOW_SERVER_FILTER = (
    "base_token_has_critical_warnings=false"
    "&&quote_token_has_critical_warnings=false"
    "&&base_token_has_high_supply_concentration=false"
    "&&base_token_has_high_single_ownership=false"
    "&&pool_type=dlmm"
    "&&tvl>=10000"
    "&&fee_tvl_ratio>=2"
    "&&fee_pct>=0.5"
)
# Deteksi 4H (curl user terbaru, 2026-11-15): timeframe 4h, category top, TANPA sort_by.
# avg_volume dan avg_fee per menit = nilai 4H ÷ 240 (dicek: HOGE volume 56.513,30 ÷ 240 = 235,47).
FLOW_4H_TIMEFRAME = "4h"
FLOW_4H_CATEGORY = "top"
# Tabel 4H hanya memuat pool dengan avg volume/menit ÷ TVL di atas ini (permintaan user, 2026-11-15).
FLOW_4H_MIN_VOLUME_TVL = 0.02  # 2 %, batas eksklusif: tepat 2 % tidak tampil (2026-11-15, user)
# Ringkasan (permintaan user): kriteria 1 = avg volume/menit ÷ TVL 4H minimal 10 % (inklusif, 2026-11-18).
FLOW_SUMMARY_4H_MIN = 0.10
SUMMARY_BEST = "BEST POOL (HIGH RISK)"
SUMMARY_4H = "4H ≥ 10% (CURVE) SL OOR"
FLOW_4H_SERVER_FILTER = (
    "base_token_has_high_supply_concentration=false"
    "&&base_token_has_high_single_ownership=false"
    "&&pool_type=dlmm"
    "&&base_token_market_cap>=20000"
    "&&base_token_holders>=1500"
    "&&tvl>=10000"
    "&&fee_tvl_ratio>=1"
    "&&fee_pct>=0.5"
    "&&active_tvl>=10000"
)
FLOW_MAX_PAGES = 100             # batas keamanan: 100 × 50 = 5.000 pool (cursor after_key)
FLOW_PAGE_SIZE = 50
FLOW_ALERT_CAP = 300             # riwayat alert yang disimpan

STATE_PATH = Path(__file__).resolve().parent / "pool_flow_state.json"

ENV_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_CHAT = "TELEGRAM_CHAT_ID"

SOL_MINT = "So11111111111111111111111111111111111111112"


# ---------------------------------------------------------------------------
# Angka & format
# ---------------------------------------------------------------------------

def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact(value, prefix: str, small_digits: int, big_digits: int) -> str:
    """Angka ringkas: di bawah 1.000 apa adanya; 1.000–999.999 memakai K; 1.000.000 ke atas memakai M.

    Tanpa pemisah ribuan titik (permintaan user 2026-11-15). Desimal memakai koma.
    """
    if value is None:
        return "—"
    number = float(value)
    sign = "-" if number < 0 else ""
    size = abs(number)
    if size >= 1_000_000:
        scaled, unit, digits = size / 1_000_000, "M", big_digits
    elif size >= 1_000:
        scaled, unit, digits = size / 1_000, "K", big_digits
    else:
        scaled, unit, digits = size, "", small_digits
    text = f"{scaled:.{digits}f}"
    if unit == "" and float(text) >= 1_000:  # pembulatan naik ke ribuan: tampilkan K
        scaled, unit, digits = size / 1_000, "K", big_digits
        text = f"{scaled:.{digits}f}"
    text = text.replace(".", ",")
    if digits == 1 and text.endswith(",0"):  # 50,0K → 50K
        text = text[:-2]
    return f"{sign}{prefix}{text}{unit}"


def fmt_usd(value) -> str:
    return _compact(value, "$", 0, 1)


def fmt_usd2(value) -> str:
    return _compact(value, "$", 2, 2)


def fmt_int(value) -> str:
    if value is None:
        return "—"
    return _compact(round(value), "", 0, 1)


def fmt_pct(value) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%".replace(".", ",")


def _h(value) -> str:
    """Escape untuk Telegram HTML."""
    return _html.escape(str(value or ""), quote=True)


# ---------------------------------------------------------------------------
# Pengambilan data Meteora
# ---------------------------------------------------------------------------

def _get_payload(params: dict, *, timeout: int = HTTP_TIMEOUT) -> dict:
    url = POOLS_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return payload if isinstance(payload, dict) else {}


LISTING_12H = {"timeframe": FLOW_TIMEFRAME, "category": FLOW_CATEGORY,
               "server_filter": FLOW_SERVER_FILTER, "sort_by": FLOW_SORT_BY}
LISTING_4H = {"timeframe": FLOW_4H_TIMEFRAME, "category": FLOW_4H_CATEGORY,
              "server_filter": FLOW_4H_SERVER_FILTER, "sort_by": None}


def fetch_top_page(after_key: str | None = None, *, timeframe: str = FLOW_TIMEFRAME,
                   category: str = FLOW_CATEGORY, server_filter: str = FLOW_SERVER_FILTER,
                   sort_by: str | None = FLOW_SORT_BY) -> tuple[list, str | None, bool]:
    """Satu halaman listing Meteora (default 12H, kategori ``all``).

    Meteora memakai cursor: halaman berikutnya diminta dengan ``after_key`` dari
    respons sebelumnya (parameter ``page`` diabaikan API dan selalu memberi
    pool yang sama). Kembalikan (rows, next_after_key, has_more).
    """
    params: dict = {"page_size": FLOW_PAGE_SIZE}
    if sort_by:
        params["sort_by"] = sort_by
    params.update({"timeframe": timeframe, "category": category, "filter_by": server_filter})
    if after_key:
        params["after_key"] = after_key
    payload = _get_payload(params)
    rows = [row for row in (payload.get("data") or []) if isinstance(row, dict)]
    next_key = payload.get("after_key") or None
    return rows, (str(next_key) if next_key else None), bool(payload.get("has_more"))


def fetch_listing(max_pages: int = FLOW_MAX_PAGES, **listing) -> tuple[list, list, bool]:
    """Ambil seluruh listing lewat cursor ``after_key``, berurutan, sampai
    ``has_more`` = false. ``listing`` = argumen ``fetch_top_page`` (default 12H).

    Kembalikan (rows, errors, truncated). ``truncated`` = True bila listing belum
    lengkap: batas ``max_pages`` tercapai selagi masih ada halaman, cursor tidak
    maju, atau ada halaman yang gagal diambil.
    """
    rows: list = []
    errors: list = []
    cursor = None
    for _ in range(max(1, max_pages)):
        try:
            page_rows, next_key, has_more = fetch_top_page(cursor, **listing)
        except Exception as exc:  # noqa: BLE001 — catat; tanpa cursor tidak bisa lanjut
            errors.append(str(exc) or type(exc).__name__)
            return rows, errors, True
        rows.extend(page_rows)
        if not has_more or not next_key:
            return rows, errors, False
        if next_key == cursor:  # cursor macet: hentikan, jangan loop
            return rows, errors, True
        cursor = next_key
    return rows, errors, True


# ---------------------------------------------------------------------------
# Data baris pool (murni)
# ---------------------------------------------------------------------------

def mint_of_pool(row: dict) -> str:
    """Mint non-SOL dari pool (token_x kecuali itu SOL)."""
    x = str((row.get("token_x") or {}).get("address") or "")
    y = str((row.get("token_y") or {}).get("address") or "")
    return y if x == SOL_MINT else x


def token_info(row: dict, mint: str) -> tuple[str, str]:
    """(symbol, name) token ``mint`` di dalam baris pool."""
    for side_key in ("token_x", "token_y"):
        side = row.get(side_key) or {}
        if str(side.get("address") or "") == mint:
            return str(side.get("symbol") or "?"), str(side.get("name") or "")
    other = row.get("token_x") or {}
    return str(other.get("symbol") or "?"), str(other.get("name") or "")


# ---------------------------------------------------------------------------
# Filter (murni)
# ---------------------------------------------------------------------------

def base_market_cap(row: dict):
    """Market cap token base (token_x, sisi token di listing Meteora)."""
    return _num((row.get("token_x") or {}).get("market_cap"))


def security_checks(row: dict) -> tuple[list[str], list[str]]:
    """(blokir, peringatan) dari field keamanan Meteora. Nilai kosong tidak dihitung.

    Blokir: mint/freeze authority masih aktif, atau top holders > FLOW_SEC_HOLDERS_BLOCK.
    Peringatan: top holders > FLOW_SEC_HOLDERS_WARN, dev balance > FLOW_SEC_DEV_WARN,
    atau total_withdraws > total_deposits saat TVL < FLOW_SEC_LP_OUTFLOW_TVL_MAX.
    """
    token = row.get("token_x") or {}
    blocks: list[str] = []
    warns: list[str] = []
    if token.get("has_mint_authority") is True:
        blocks.append("mint authority masih aktif")
    if token.get("has_freeze_authority") is True:
        blocks.append("freeze authority masih aktif")
    holders = _num(token.get("top_holders_pct"))
    if holders is not None:
        if holders > FLOW_SEC_HOLDERS_BLOCK:
            blocks.append(f"top holders > {FLOW_SEC_HOLDERS_BLOCK:g}%")
        elif holders > FLOW_SEC_HOLDERS_WARN:
            warns.append(f"top holders {fmt_pct(holders)}")
    dev = _num(token.get("dev_balance_pct"))
    if dev is not None and dev > FLOW_SEC_DEV_WARN:
        warns.append(f"dev {fmt_pct(dev)}")
    tvl = _num(row.get("tvl"))
    withdraws = _num(row.get("total_withdraws"))
    deposits = _num(row.get("total_deposits"))
    if (tvl is not None and tvl < FLOW_SEC_LP_OUTFLOW_TVL_MAX
            and withdraws is not None and deposits is not None and withdraws > deposits):
        warns.append(f"LP keluar > masuk (TVL < {fmt_usd(FLOW_SEC_LP_OUTFLOW_TVL_MAX)})")
    return blocks, warns


def evaluate_pool(row: dict) -> dict:
    """Ambil field tampilan satu baris pool dan terapkan cek keamanan.

    Tidak ada filter seleksi lokal (2026-11-14). Pool hanya gagal bila kena blokir
    keamanan (``reasons`` berisi ``keamanan: …``). Peringatan tetap tampil sebagai label.
    """
    pool = str(row.get("pool_address") or "")
    mint = mint_of_pool(row)
    symbol, name = token_info(row, mint)
    fee_tier = _num(row.get("fee_pct"))
    fee_active_tvl = _num(row.get("fee_active_tvl_ratio"))
    volatility = _num(row.get("volatility"))
    avg_volume = _num(row.get("avg_volume"))

    reasons: list[str] = []
    security_blocks, security_warnings = security_checks(row)
    reasons.extend(f"keamanan: {text}" for text in security_blocks)

    return {
        "pool": pool,
        "mint": mint,
        "symbol": symbol,
        "name": name,
        "pool_name": str(row.get("name") or ""),
        "fee_tier": fee_tier,
        "tvl": _num(row.get("tvl")),
        "active_tvl": _num(row.get("active_tvl")),
        "holders": _num(row.get("base_token_holders")),
        "market_cap": base_market_cap(row),
        "volatility": volatility,
        "fee_active_tvl": fee_active_tvl,
        "token_created_at": _num((row.get("token_x") or {}).get("created_at")),  # ms sejak epoch
        "fee_tvl": _num(row.get("fee_tvl_ratio")),
        "avg_volume": avg_volume,
        "avg_fee": _num(row.get("avg_fee")),
        "passes": not reasons,
        "reasons": reasons,
        "warnings": security_warnings,
        "activity": pool_activity(row),
    }


# ---------------------------------------------------------------------------
# Aktivitas per pool (volume, swap, rata² swap) untuk kolom tabel dan alert.
# ---------------------------------------------------------------------------

def pool_activity(row: dict) -> dict:
    """Ringkasan aktivitas satu pool (timeframe 12H) dari baris Meteora."""
    volume = _num(row.get("volume"))
    swaps = _num(row.get("swap_count"))
    avg_swap = volume / swaps if (volume is not None and swaps and swaps > 0) else None
    return {
        "pool": str(row.get("pool_address") or ""),
        "name": str(row.get("name") or ""),
        "pool_type": str(row.get("pool_type") or ""),
        "fee_tier": _num(row.get("fee_pct")),
        "tvl": _num(row.get("tvl")),
        "active_tvl": _num(row.get("active_tvl")),
        "fee": _num(row.get("fee")),
        "volume": volume,
        "swaps": swaps,
        "traders": _num(row.get("unique_traders")),
        "avg_swap": avg_swap,
        "fee_active_tvl": _num(row.get("fee_active_tvl_ratio")),
    }


def fmt_ratio_pct(value, digits: int = 2) -> str:
    """Rasio sebagai persen dengan ``digits`` desimal (nilainya kecil, mis. 1,66 %)."""
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%".replace(".", ",")


def avg_volume_tvl_ratio(result: dict):
    """Rasio avg volume per menit ÷ TVL (``None`` bila salah satu tidak ada atau TVL nol)."""
    avg = result.get("avg_volume")
    tvl = result.get("tvl")
    if avg is None or not tvl:
        return None
    return avg / tvl


def sort_key(result: dict):
    """Urutan tampilan dan alert: rasio avg volume/menit ÷ TVL terbesar dulu.

    Pengurutan lama (fee/active TVL, lalu avg volume) sudah dihapus (2026-11-15).
    Seri: urutan listing (sort stabil).
    """
    return -(avg_volume_tvl_ratio(result) or 0.0)


def avg_fee_tvl_ratio(result: dict):
    """Rasio avg fee per menit ÷ TVL (``None`` bila salah satu tidak ada atau TVL nol)."""
    avg = result.get("avg_fee")
    tvl = result.get("tvl")
    if avg is None or not tvl:
        return None
    return avg / tvl


def fee_volatility_ratio(row: dict):
    """Fee/TVL ÷ volatility (kali). 1 = seimbang (fee/TVL sama dengan volatility). ``None`` bila tidak ada/0.

    Permintaan user (2026-11-19): mencari pool dengan keseimbangan volatility dan fee/TVL (fee printer).
    """
    fee_tvl = row.get("fee_tvl")
    vol = row.get("volatility")
    if fee_tvl is None or not vol:
        return None
    return fee_tvl / vol


def fee_volatility_diff(row: dict):
    """Fee/TVL − volatility dalam poin persen. 0 = seimbang; positif = fee/TVL di atas volatility."""
    fee_tvl = row.get("fee_tvl")
    vol = row.get("volatility")
    if fee_tvl is None or vol is None:
        return None
    return fee_tvl - vol


def fmt_times(value) -> str:
    """Rasio kali dengan 2 desimal, mis. ``1,50×``."""
    if value is None:
        return "—"
    return f"{value:.2f}×".replace(".", ",")


def fmt_signed_pct(value) -> str:
    """Selisih persen dengan tanda, mis. ``+2,00%`` / ``−1,25%``."""
    if value is None:
        return "—"
    return f"{value:+.2f}%".replace("-", "−").replace(".", ",")


def sort_key_slow(result: dict):
    """Urutan SLOW FEE PRINTER (permintaan user): selisih |fee/TVL − volatility| terkecil dulu,
    yaitu pool yang paling seimbang.

    Nilai absolut dipakai karena selisih negatif (fee/TVL di bawah volatility) juga tidak seimbang.
    Seri: urutan listing (sort stabil). Pool tanpa selisih dianggap paling belakang.
    """
    diff = fee_volatility_diff(result)
    return float("inf") if diff is None else abs(diff)


def sort_key_4h(result: dict):
    """Urutan deteksi 4H: avg volume/menit ÷ TVL terbesar dulu, lalu avg fee/menit ÷ TVL terbesar."""
    return (-(avg_volume_tvl_ratio(result) or 0.0), -(avg_fee_tvl_ratio(result) or 0.0))


def summary_rows(result_12h: dict, result_4h: dict) -> list:
    """Ringkasan: daftar (row, label), urut seperti tabel 4H.

    - ``BEST POOL (HIGH RISK)``: pool ada di HIGH RISK FEE PRINTER (12H) DAN di tabel 4H (kriteria 2).
    - ``4H ≥ 10% (CURVE) SL OOR``: pool di tabel 4H dengan avg volume/menit ÷ TVL minimal 10 % (kriteria 1).
    Pool yang memenuhi keduanya berlabel BEST POOL (HIGH RISK). Label itu tampil lebih dulu.
    """
    fee_printer, _band = fee_printer_split(result_12h.get("passing") or [])
    high_risk_pools = {row["pool"] for row in fee_printer_high_risk(fee_printer)}
    best: list = []
    others: list = []
    for row in result_4h.get("passing") or []:  # tabel 4H: sudah > 2 % dan sudah urut
        if row["pool"] in high_risk_pools:
            best.append((row, SUMMARY_BEST))
        elif (avg_volume_tvl_ratio(row) or 0.0) >= FLOW_SUMMARY_4H_MIN:
            others.append((row, SUMMARY_4H))
    return best + others


def token_old_enough(item: dict, now_ms: float | None = None) -> bool:
    """Umur token dasar ≥ ``FLOW_SLOW_MIN_TOKEN_AGE_HOURS`` jam (batas inklusif).

    ``token_created_at`` dari Meteora dalam milidetik. Tanpa data umur: tidak lolos.
    """
    created = item.get("token_created_at")
    if created is None:
        return False
    now = now_ms if now_ms is not None else time.time() * 1000
    return now - created >= FLOW_SLOW_MIN_TOKEN_AGE_HOURS * 3_600_000


def fee_printer_split(passing: list, now_ms: float | None = None) -> tuple[list, list]:
    """Pisahkan pool menjadi (fee_printer, band) memakai fee/TVL vs volatility.

    - fee_printer: fee/TVL > 2 × volatility (FEE PRINTER (SPOT)).
    - band (SLOW FEE PRINTER): 0,75 × volatility ≤ fee/TVL ≤ 1,5 × volatility, dan umur token
      minimal 24 jam (2026-11-19). Pool yang lebih muda hanya tidak masuk band; fee_printer tidak berubah.
    Pool tanpa volatility terukur (None atau < 0,01 %) atau tanpa fee/TVL tidak masuk keduanya.
    Pool dengan fee/TVL di luar band (mis. 1,5–2 × atau < 0,75 × volatility) tidak masuk keduanya.
    Urutan fee_printer: ``sort_key``; band (SLOW): ``sort_key_slow`` (|selisih| terkecil dulu).
    """
    fee_printer: list = []
    band: list = []
    for item in passing:
        vol = item.get("volatility")
        fee_tvl = item.get("fee_tvl")
        if vol is None or vol < FLOW_VOLATILITY_MEASURABLE_MIN or fee_tvl is None:
            continue
        if fee_tvl > FLOW_FEE_PRINTER_MULT * vol:
            fee_printer.append(item)
        elif (FLOW_BAND_LOW_MULT * vol <= fee_tvl <= FLOW_BAND_HIGH_MULT * vol
              and token_old_enough(item, now_ms)):
            band.append(item)
    return sorted(fee_printer, key=sort_key), sorted(band, key=sort_key_slow)


def fee_printer_high_risk(fee_printer: list) -> list:
    """Filter kedua di atas FEE PRINTER (SPOT) untuk HIGH RISK FEE PRINTER (2026-11-19, user request):

    3 × volatility < fee/TVL < 10 × volatility, dan fee/TVL ≥ 10 % (batas bawah inklusif).
    Input harus hasil ``fee_printer_split`` (sudah fee/TVL > 2 × volatility). Pool di 2–3 ×
    atau dengan fee/TVL ≥ 10 × volatility tidak ditampilkan di tabel ini. Urutan: ``sort_key``.
    """
    kept = [item for item in fee_printer
            if item["fee_tvl"] > FLOW_HIGH_RISK_MIN_MULT * item["volatility"]
            and item["fee_tvl"] >= FLOW_HIGH_RISK_MIN_FEE_TVL
            and item["fee_tvl"] < FLOW_HIGH_RISK_MAX_MULT * item["volatility"]]
    return sorted(kept, key=sort_key)


def very_high_risk(passing: list) -> list:
    """VERY HIGH RISK POOL / BISA DUMP SEWAKTU2 (2026-11-18): fee/TVL ≥ 20 × volatility (batas inklusif).

    Volatility harus terukur (≥ 0,01 %). Melengkapi HIGH RISK FEE PRINTER (2× < fee/TVL < 10×),
    sehingga kedua tabel tidak pernah memuat pool yang sama. Urutan: ``sort_key``.
    """
    kept: list = []
    for item in passing:
        vol = item.get("volatility")
        fee_tvl = item.get("fee_tvl")
        if vol is None or vol < FLOW_VOLATILITY_MEASURABLE_MIN or fee_tvl is None:
            continue
        if fee_tvl >= FLOW_VERY_HIGH_MIN_MULT * vol:
            kept.append(item)
    return sorted(kept, key=sort_key)


def ranked(passing: list) -> list:
    """Pool diurutkan dari avg volume per menit terbesar (sama untuk tabel dan alert)."""
    return sorted(passing, key=sort_key)


def most_crowded(result: dict):
    """Pool paling ramai = avg volume per menit terbesar di seluruh hasil scan.

    Hanya memakai data listing, jadi alert tetap ringan.
    """
    ordered = ranked(result.get("passing") or [])
    if not ordered:
        return None
    top = ordered[0]
    activity = top["activity"]
    return {
        "mint": top["mint"],
        "symbol": top["symbol"],
        "pool": top["pool"],
        "pool_name": top["pool_name"],
        "avg_volume": top["avg_volume"],
        "pool_volume": activity["volume"],
        "pool_swaps": activity["swaps"],
        "pool_avg_swap": activity["avg_swap"],
        "row": top,
    }


def _scan(rows: list, errors: list, truncated: bool, order, timeframe: str,
          min_fee_tvl: float | None = None) -> dict:
    """Evaluasi baris listing (tanpa duplikat pool) lalu urutkan dengan ``order``.

    ``min_fee_tvl`` (%): pool dengan fee/TVL di bawah ini (atau tanpa nilai) tidak lolos,
    dengan alasan ``fee/TVL di bawah …%`` di ``reasons``.
    """
    unique: dict[str, dict] = {}
    for row in rows:
        address = str(row.get("pool_address") or "")
        if address and address not in unique:
            unique[address] = row
    results = [evaluate_pool(row) for row in unique.values()]
    if min_fee_tvl is not None:
        for item in results:
            fee = item.get("fee_tvl")
            if fee is None or fee < min_fee_tvl:
                item["reasons"].append(f"fee/TVL di bawah {min_fee_tvl:g}%")
                item["passes"] = False
    passing = sorted((r for r in results if r["passes"]), key=order)
    return {
        "timeframe": timeframe,
        "scanned_at": now_iso(),
        "listing_rows": len(rows),
        "listing_errors": len(errors),
        "truncated": bool(truncated),
        "candidates": len(unique),
        "results": results,
        "passing": passing,
    }


def scan_pools(max_pages: int = FLOW_MAX_PAGES, *, listing: tuple | None = None) -> dict:
    """Scan lengkap: listing 12H (filter server-side) → urutan.

    ``listing`` = (rows, errors, truncated) bisa diisi untuk tes tanpa jaringan.
    """
    rows, errors, truncated = (listing if listing is not None
                               else fetch_listing(max_pages, **LISTING_12H))
    return _scan(rows, errors, truncated, sort_key, FLOW_TIMEFRAME,
                 min_fee_tvl=FLOW_MIN_FEE_TVL_12H)


def scan_4h(max_pages: int = FLOW_MAX_PAGES, *, listing: tuple | None = None) -> dict:
    """Deteksi 4H: listing 4h (kategori top, filter 4H) → urut avg volume/menit ÷ TVL, lalu avg fee/menit ÷ TVL.

    Aturan keamanan yang sama dengan 12H. Pool hanya tampil bila avg volume/menit ÷ TVL
    > ``FLOW_4H_MIN_VOLUME_TVL`` (2 %). ``listing`` untuk tes tanpa jaringan.
    """
    rows, errors, truncated = (listing if listing is not None
                               else fetch_listing(max_pages, **LISTING_4H))
    result = _scan(rows, errors, truncated, sort_key_4h, FLOW_4H_TIMEFRAME)
    ratio_ok = [r for r in result["passing"]
                if (avg_volume_tvl_ratio(r) or 0.0) > FLOW_4H_MIN_VOLUME_TVL]
    result["passing"] = ratio_ok
    return result


# ---------------------------------------------------------------------------
# State (hanya riwayat alert)
# ---------------------------------------------------------------------------

def empty_state() -> dict:
    return {
        "version": 2,
        "best_alert": {"next_no": 1, "last_no": {}},
        "alerts": [],
    }


def load_state(path: Path | None = None) -> dict:
    path = Path(path) if path is not None else STATE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return empty_state()
    state = empty_state()
    if isinstance(data, dict):
        # Kunci lama (watchlist, history, watch_negative) sengaja dibuang.
        state.update({k: v for k, v in data.items() if k in state})
    return state


def save_state(state: dict, path: Path | None = None) -> None:
    path = Path(path) if path is not None else STATE_PATH
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# Alert: RINGKASAN (tiap jam)
# ---------------------------------------------------------------------------

def alert_copy_markup(passing: list) -> dict | None:
    """Inline keyboard: satu tombol 📋 CA per pool. ``copy_text`` (Bot API 7.11+)
    menyalin CA lengkap ke clipboard di aplikasi Telegram. ``None`` bila tidak ada CA."""
    rows = []
    for row in passing:
        mint = row.get("mint") or ""
        if not mint:
            continue
        label = f"📋 CA {row.get('symbol') or '?'}"[:40]
        rows.append([{"text": label, "copy_text": {"text": mint}}])
    return {"inline_keyboard": rows} if rows else None


def alert_link_lines(mint: str, pool: str) -> list[str]:
    """Baris CA (tap untuk salin) dan tautan berlabel: GMGN · Dex · Meteora · HawkFi."""
    lines: list[str] = []
    if mint:
        lines.append(f"🧬 <code>{_h(mint)}</code>")
    links_row = []
    if mint:
        links_row.append(f'<a href="{_h(links.gmgn_token_url(mint))}">GMGN</a>')
        links_row.append(f'<a href="{_h(links.dexscreener_token_url(mint))}">DexScreener</a>')
    if pool:
        links_row.append(f'<a href="{_h(links.meteora_dlmm_url(pool))}">Meteora</a>')
        links_row.append(f'<a href="{_h(links.hawkfi_meteora_url(pool))}">HawkFi</a>')
    if links_row:
        lines.append("🔗 " + " · ".join(links_row))
    return lines


def _pct_or_dash(value) -> str:
    return f"{value:g}%" if value is not None else "—"


def summary_alert_text(no: int, entries: list, seen: dict) -> str:
    """Alert Telegram RINGKASAN (2026-11-18): BEST POOL (HIGH RISK) dan 4H ≥ 10% (CURVE) SL OOR, satu blok per pool.

    ``entries`` = hasil ``summary_rows`` (row, label). ``seen`` = ``best_alert.last_no`` sebelum alert ini.
    """
    lines = [
        f"<b>alert #{no}</b>",
        "📋 RINGKASAN Scan ALL (12H + 4H)",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for row, label in entries:
        pool = row["pool"]
        seen_no = seen.get(pool)
        tag = f"🔁 sudah pernah · alert #{seen_no}" if seen_no else "🆕 baru"
        name = row.get("pool_name") or pool[:6]
        lines.append("")
        lines.append(f"<b>{_h(row['symbol'])}</b> · {_h(name)}  [{_h(label)}]  {tag}")
        lines.append(f"📊 avg volume/menit ÷ TVL 4H {fmt_ratio_pct(avg_volume_tvl_ratio(row))}")
        if row.get("warnings"):
            lines.append("⚠️ Peringatan keamanan: " + _h("; ".join(row["warnings"])))
        lines.extend(alert_link_lines(row.get("mint") or "", pool))
    return "\n".join(lines)


def apply_summary_alert(state: dict, entries: list) -> tuple[str | None, dict | None]:
    """Teks RINGKASAN + tombol 📋 CA per pool. ``(None, None)`` bila tidak ada pool yang memenuhi kriteria."""
    if not entries:
        return None, None
    no = int(state["best_alert"]["next_no"])
    seen = state["best_alert"]["last_no"]
    text = summary_alert_text(no, entries, seen)
    pools = [row["pool"] for row, _label in entries]
    for pool in pools:
        seen[pool] = no
    state["best_alert"]["next_no"] = no + 1
    state["alerts"].append({"no": no, "kind": "summary", "at": now_iso(), "pools": pools})
    del state["alerts"][:-FLOW_ALERT_CAP]
    return text, alert_copy_markup([row for row, _label in entries])


# ---------------------------------------------------------------------------
# Telegram (secret yang sama dengan Sweep: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
# ---------------------------------------------------------------------------

TELEGRAM_CHUNK = 3800  # batas Telegram 4096 karakter; sisakan ruang


def split_for_telegram(text: str, limit: int = TELEGRAM_CHUNK) -> list[str]:
    """Pecah teks per baris agar tiap bagian ≤ ``limit`` karakter."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # baris tunggal yang terlalu panjang
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def send_telegram(text: str, reply_markup: dict | None = None) -> tuple[bool, str]:
    """Kirim pesan (dipecah bila panjang). ``reply_markup`` (mis. tombol copy CA)
    dipasang di bagian terakhir. ``(False, alasan)`` bila gagal."""
    chunks = split_for_telegram(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        ok, error = _send_telegram_once(chunk, markup)
        if not ok:
            return False, error
    return True, ""


def _send_telegram_once(text: str, reply_markup: dict | None = None) -> tuple[bool, str]:
    token = (os.environ.get(ENV_TOKEN) or "").strip()
    chat = (os.environ.get(ENV_CHAT) or "").strip()
    if not token or not chat:
        return False, "kredensial Telegram belum dipasang"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = {"chat_id": chat, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True}
    if reply_markup:
        body["reply_markup"] = reply_markup
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT):
            return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:160]
