# -*- coding: utf-8 -*-
"""🏆 Scan ALL Meteora — logika inti, tanpa Streamlit.

FEE PRINTER (permintaan user, 2026-11-24):
- Listing Meteora pool-discovery, timeframe 24h, kategori top, dengan filter server
  (``flow_server_filter``, curl user) dan dua batas waktu yang dihitung ulang tiap scan.
- Syarat lokal: volatility 0,01–3 %, fee/active TVL ≥ 2 × volatility, net deposit ≥ 10.000 USD.
- Keamanan tetap: blokir bila mint/freeze authority aktif atau top holders > 30 %.
- Urutan: fee/active TVL ÷ volatility terbesar dulu.
- Alert Telegram (tiap 15 menit): RINGKASAN, atau heartbeat bila tidak ada pool.
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

FLOW_TIMEFRAME = "24h"  # listing 24 jam (curl user, 2026-11-24)
FLOW_CATEGORY = "top"  # kategori top (curl user, 2026-11-24)

# FEE PRINTER (permintaan user, 2026-11-24). Syarat lokal, di luar filter server:
FLOW_VOLATILITY_MEASURABLE_MIN = 0.01  # % — di bawah ini dianggap tidak terukur
FLOW_MAX_VOLATILITY = 3.0  # % — volatility maksimal (inklusif)
FLOW_FEE_ACTIVE_TVL_MULT = 2.0  # fee/active TVL ≥ 2 × volatility (inklusif)
FLOW_MIN_NET_DEPOSITS = 10_000.0  # USD — net deposit minimal (inklusif)

# Filter server (curl user, 2026-11-24). Dua batas waktu dihitung ulang tiap scan (lihat flow_server_filter).
FLOW_SERVER_MIN_MARKET_CAP = 20_000  # USD, market cap token base
FLOW_SERVER_MIN_HOLDERS = 1_500  # holder token base
FLOW_SERVER_MIN_TVL = 30_000  # USD
FLOW_SERVER_MIN_ACTIVE_TVL = 10_000  # USD
FLOW_SERVER_MIN_FEE_TVL = 1  # fee_tvl_ratio (%, 24H)
FLOW_SERVER_MIN_FEE_PCT = 0.5  # fee tier pool (%)
FLOW_POOL_MIN_AGE_HOURS = 24  # pool_created_at ≤ sekarang − 24 jam

# Peringatan keamanan (label saja, tidak menyaring).
FLOW_SEC_HOLDERS_BLOCK = 30.0           # % top_holders_pct token dasar, blokir di atas ini
FLOW_SEC_HOLDERS_WARN = 15.0            # % top_holders_pct, peringatan di atas ini
FLOW_SEC_DEV_WARN = 5.0                 # % dev_balance_pct, peringatan di atas ini
FLOW_SEC_LP_OUTFLOW_TVL_MAX = 50_000.0  # USD: peringatan LP keluar hanya bila TVL di bawah ini

# RINGKASAN: label asal, sama dengan judul tabel di halaman.
SUMMARY_LABEL = "FEE PRINTER"
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


def fmt_pct2(value) -> str:
    """Persen dengan 2 desimal (untuk volatility dan fee/active TVL, batas 3 % dan 2 × perlu presisi)."""
    if value is None:
        return "—"
    return f"{value:.2f}%".replace(".", ",")


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


def flow_server_filter(now_ms: float | None = None) -> str:
    """Filter server (curl user, 2026-11-24), urutan parameter persis seperti curl.

    Dua batas waktu di curl user adalah nilai tetap saat curl dibuat (2026-11-24 01:34 UTC).
    Di sini dihitung ulang tiap scan: token dibuat ≤ sekarang, dan pool dibuat ≤ sekarang − 24 jam.
    Tanpa ini, pool baru tidak pernah masuk listing.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    pool_cutoff = now - FLOW_POOL_MIN_AGE_HOURS * 3_600_000
    return (
        "base_token_has_high_supply_concentration=false"
        "&&base_token_has_high_single_ownership=false"
        "&&pool_type=dlmm"
        f"&&base_token_market_cap>={FLOW_SERVER_MIN_MARKET_CAP}"
        f"&&base_token_created_at<={now}"
        f"&&base_token_holders>={FLOW_SERVER_MIN_HOLDERS}"
        f"&&pool_created_at<={pool_cutoff}"
        f"&&tvl>={FLOW_SERVER_MIN_TVL}"
        f"&&fee_tvl_ratio>={FLOW_SERVER_MIN_FEE_TVL}"
        f"&&fee_pct>={FLOW_SERVER_MIN_FEE_PCT:g}"
        f"&&active_tvl>={FLOW_SERVER_MIN_ACTIVE_TVL}"
    )


def fetch_top_page(after_key: str | None = None, *, timeframe: str = FLOW_TIMEFRAME,
                   category: str = FLOW_CATEGORY, server_filter: str | None = None,
                   sort_by: str | None = None) -> tuple[list, str | None, bool]:
    """Satu halaman listing Meteora (24H, kategori ``top``), tanpa ``sort_by`` (curl user).

    Meteora memakai cursor: halaman berikutnya diminta dengan ``after_key`` dari
    respons sebelumnya (parameter ``page`` diabaikan API). Kembalikan (rows, next_after_key, has_more).
    """
    params: dict = {"page_size": FLOW_PAGE_SIZE}
    if sort_by:
        params["sort_by"] = sort_by
    params.update({"timeframe": timeframe, "category": category,
                   "filter_by": server_filter or flow_server_filter()})
    if after_key:
        params["after_key"] = after_key
    payload = _get_payload(params)
    rows = [row for row in (payload.get("data") or []) if isinstance(row, dict)]
    next_key = payload.get("after_key") or None
    return rows, (str(next_key) if next_key else None), bool(payload.get("has_more"))


def fetch_listing(max_pages: int = FLOW_MAX_PAGES, **listing) -> tuple[list, list, bool]:
    """Ambil seluruh listing lewat cursor ``after_key``, berurutan, sampai
    ``has_more`` = false. ``listing`` = argumen ``fetch_top_page`` (default 24H).

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

    Filter FEE PRINTER (volatility, fee/active TVL, net deposit) dicek di ``fee_printer_rows``.
    Di sini pool hanya gagal bila kena blokir keamanan (``reasons`` berisi ``keamanan: …``).
    Peringatan tetap tampil sebagai label.
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
        "pool_created_at": _num(row.get("pool_created_at")),  # ms sejak epoch (umur pool)
        "fee_tvl": _num(row.get("fee_tvl_ratio")),  # % (fee 24H ÷ TVL × 100)
        "net_deposits": _num(row.get("net_deposits")),  # USD: net deposit pool
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
    """Ringkasan aktivitas satu pool (timeframe 24H) dari baris Meteora."""
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


def fmt_times_plain(value) -> str:
    """Angka rasio dengan 2 desimal, mis. ``24,55``. ``—`` bila kosong."""
    if value is None:
        return "—"
    return f"{value:.2f}".replace(".", ",")


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


def fee_active_per_volatility(item: dict):
    """Fee/active TVL ÷ volatility. Dasar urutan FEE PRINTER (permintaan user, 2026-11-24).

    ``None`` bila salah satu tidak ada atau volatility ≤ 0.
    """
    fee_active = item.get("fee_active_tvl")
    vol = item.get("volatility")
    if fee_active is None or vol is None or vol <= 0:
        return None
    return fee_active / vol


def fee_printer_ok(item: dict) -> bool:
    """Syarat FEE PRINTER (permintaan user, 2026-11-24), inklusif di semua batas:

    - volatility 0,01 % sampai 3 % (di bawah 0,01 % dianggap tidak terukur),
    - fee/active TVL ≥ 2 × volatility,
    - net deposit ≥ +10.000 USD.
    Pool tanpa salah satu nilai ini tidak lolos.
    """
    vol = item.get("volatility")
    fee_active = item.get("fee_active_tvl")
    net = item.get("net_deposits")
    if vol is None or fee_active is None or net is None:
        return False
    if not (FLOW_VOLATILITY_MEASURABLE_MIN <= vol <= FLOW_MAX_VOLATILITY):
        return False
    return fee_active >= FLOW_FEE_ACTIVE_TVL_MULT * vol and net >= FLOW_MIN_NET_DEPOSITS


def fee_printer_rows(passing: list) -> list:
    """Pool FEE PRINTER: lolos ``fee_printer_ok``, urut fee/active TVL ÷ volatility terbesar dulu.

    Seri: urutan listing (sort stabil).
    """
    rows = [item for item in passing if fee_printer_ok(item)]
    return sorted(rows, key=lambda item: -(fee_active_per_volatility(item) or 0.0))


def summary_rows(result: dict) -> list:
    """RINGKASAN: hanya pool dari tabel FEE PRINTER. Daftar (row, label), label ``SUMMARY_LABEL``."""
    return [(row, SUMMARY_LABEL) for row in fee_printer_rows(result.get("passing") or [])]


def ranked(passing: list) -> list:
    """Pool diurutkan dari avg volume per menit ÷ TVL terbesar (urutan top-pool, sama untuk tabel dan alert)."""
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


def _scan(rows: list, errors: list, truncated: bool, timeframe: str) -> dict:
    """Evaluasi baris listing (tanpa duplikat pool). ``passing`` = pool yang tidak kena blokir keamanan.

    Urutan tampilan ada di ``fee_printer_rows``; ``passing`` hanya urut ``sort_key`` (untuk top-pool).
    """
    unique: dict[str, dict] = {}
    for row in rows:
        address = str(row.get("pool_address") or "")
        if address and address not in unique:
            unique[address] = row
    results = [evaluate_pool(row) for row in unique.values()]
    passing = sorted((r for r in results if r["passes"]), key=sort_key)
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


def scan_pools(max_pages: int = FLOW_MAX_PAGES, *, listing: tuple | None = None,
               now_ms: float | None = None) -> dict:
    """Scan lengkap: listing 24H (filter server-side) → cek keamanan → urutan.

    ``listing`` = (rows, errors, truncated) untuk tes tanpa jaringan.
    ``now_ms`` (opsional): waktu acuan filter server, untuk tes.
    """
    if listing is not None:
        rows, errors, truncated = listing
    else:
        rows, errors, truncated = fetch_listing(max_pages, server_filter=flow_server_filter(now_ms))
    return _scan(rows, errors, truncated, FLOW_TIMEFRAME)


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


def summary_alert_text(no: int, entries: list, seen: dict) -> str:
    """Alert Telegram RINGKASAN: pool dari tabel FEE PRINTER, satu blok per pool.

    Tiap blok: nama, label asal tabel, tag baru/sudah pernah, fee/TVL dan volatility, peringatan, tautan.
    ``entries`` = hasil ``summary_rows`` (row, label). ``seen`` = ``best_alert.last_no`` sebelum alert ini.
    """
    lines = [
        f"<b>alert #{no}</b>",
        "📋 RINGKASAN Scan ALL (24H)",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for row, label in entries:
        pool = row["pool"]
        seen_no = seen.get(pool)
        tag = f"🔁 sudah pernah · alert #{seen_no}" if seen_no else "🆕 baru"
        name = row.get("pool_name") or pool[:6]
        lines.append("")
        lines.append(f"<b>{_h(row['symbol'])}</b> · {_h(name)}  [{_h(label)}]  {tag}")
        ratio = fee_active_per_volatility(row)
        lines.append(f"📊 fee/active TVL {fmt_pct2(row.get('fee_active_tvl'))} · volatility {fmt_pct2(row.get('volatility'))}"
                     f" · net {fmt_usd(row.get('net_deposits'))} · fee/active ÷ volatility {fmt_times_plain(ratio)}")
        if row.get("warnings"):
            lines.append("⚠️ Peringatan keamanan: " + _h("; ".join(row["warnings"])))
        lines.extend(alert_link_lines(row.get("mint") or "", pool))
    return "\n".join(lines)


def heartbeat_text(result: dict | None = None, error: str | None = None, now: str | None = None) -> str:
    """Pesan cron (permintaan user, 2026-11-24): dikirim tiap run bila tidak ada pool FEE PRINTER,
    atau saat scan gagal. Tujuannya agar user tahu cron berjalan. Tidak mengubah state.
    """
    lines = [f"💓 <b>Pool Flow cron jalan</b> · {_h(now or now_iso())}"]
    if error is not None:
        lines.append(f"❌ Scan gagal: {_h(error)}")
        return "\n".join(lines)
    result = result or {}
    lines.append(f"📡 listing 24H: {result.get('listing_rows', 0)} baris · "
                 f"dievaluasi {result.get('candidates', 0)} · lolos {len(result.get('passing') or [])}")
    lines.append("🔎 FEE PRINTER: 0 pool (tidak ada yang memenuhi kriteria)")
    if result.get("listing_errors"):
        lines.append(f"⚠️ halaman listing gagal: {result['listing_errors']}")
    if result.get("truncated"):
        lines.append("⚠️ listing belum lengkap (terpotong)")
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
