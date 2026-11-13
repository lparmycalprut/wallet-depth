# -*- coding: utf-8 -*-
"""🏆 Scan Best Pool Meteora — logika inti, tanpa Streamlit.

Request 24H (user, 2026-11-13) + filter volatility vs fee/active TVL:
- Listing Meteora pool-discovery, timeframe 24h, kategori top, dengan filter
  dari request user (market cap, holders, TVL, fee tier, active TVL, dlmm).
- Volatility ≤ 5 %.
- Fee/Active TVL ≥ 5 %  → tampil (permintaan user 2026-11-13).
- Rasio = Fee/Active TVL ÷ Volatility ≥ 2×  → tampil.
- Urutan: rasio terbesar dulu (seri: Fee/Active TVL terbesar).

Volatility di bawah FLOW_VOLATILITY_EPS dianggap tidak terukur (≈ 0), supaya
rasio tidak meledak. Alert pool terbaik (tiap 4 jam) memakai hasil yang sama.
"""
from __future__ import annotations

import html as _html
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import links

POOLS_URL = "https://pool-discovery-api.datapi.meteora.ag/pools"
HTTP_TIMEOUT = 25
USER_AGENT = "Mozilla/5.0 (wallet-depth-pool-flow)"

FLOW_TIMEFRAME = "24h"
FLOW_FEE_TIER_MIN = 2.0          # % (fee_pct)
FLOW_TVL_MIN = 10_000.0          # USD (tvl)
FLOW_ACTIVE_TVL_MIN = 2_000.0    # USD (active_tvl)
FLOW_HOLDERS_MIN = 1_500         # base_token_holders
FLOW_MARKET_CAP_MIN = 100_000.0  # USD (market cap token base)
FLOW_VOLATILITY_MAX = 5.0        # % (volatility)
FLOW_VOLATILITY_EPS = 0.01       # % — di bawah ini dianggap tidak terukur (≈ 0)
FLOW_FEE_ACTIVE_TVL_MIN = 5.0   # % — fee/active TVL minimal untuk tampil (permintaan user 2026-11-13)
FLOW_MULTIPLE_MIN = 2.0          # (Fee/Active TVL %) ÷ volatility % (permintaan user 2026-11-13)

# Pra-saring di sisi server (request user 24H). Semua aturan tetap dicek ulang
# di ``evaluate_pool``, jadi pra-saring hanya memangkas listing.
FLOW_SERVER_FILTER = (
    "base_token_has_high_supply_concentration=false"
    "&&base_token_has_high_single_ownership=false"
    "&&pool_type=dlmm"
    f"&&base_token_market_cap>={FLOW_MARKET_CAP_MIN:g}"
    f"&&base_token_holders>={FLOW_HOLDERS_MIN}"
    f"&&tvl>={FLOW_TVL_MIN:g}"
    f"&&fee_pct>={FLOW_FEE_TIER_MIN:g}"
    f"&&active_tvl>={FLOW_ACTIVE_TVL_MIN:g}"
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


def fmt_usd(value) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}".replace(",", ".")


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


def fetch_top_page(after_key: str | None = None) -> tuple[list, str | None, bool]:
    """Satu halaman listing kategori ``top`` pada timeframe 24H.

    Meteora memakai cursor: halaman berikutnya diminta dengan ``after_key`` dari
    respons sebelumnya (parameter ``page`` diabaikan API dan selalu memberi
    pool yang sama). Kembalikan (rows, next_after_key, has_more).
    """
    params = {"page_size": FLOW_PAGE_SIZE, "timeframe": FLOW_TIMEFRAME,
              "category": "top", "filter_by": FLOW_SERVER_FILTER}
    if after_key:
        params["after_key"] = after_key
    payload = _get_payload(params)
    rows = [row for row in (payload.get("data") or []) if isinstance(row, dict)]
    next_key = payload.get("after_key") or None
    return rows, (str(next_key) if next_key else None), bool(payload.get("has_more"))


def fetch_listing(max_pages: int = FLOW_MAX_PAGES) -> tuple[list, list, bool]:
    """Ambil seluruh listing lewat cursor ``after_key``, berurutan, sampai
    ``has_more`` = false.

    Kembalikan (rows, errors, truncated). ``truncated`` = True bila listing belum
    lengkap: batas ``max_pages`` tercapai selagi masih ada halaman, cursor tidak
    maju, atau ada halaman yang gagal diambil.
    """
    rows: list = []
    errors: list = []
    cursor = None
    for _ in range(max(1, max_pages)):
        try:
            page_rows, next_key, has_more = fetch_top_page(cursor)
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


def in_range_pct(row: dict):
    """Persen posisi aktif (in-range) dari open positions; ``None`` bila tidak terukur."""
    open_positions = _num(row.get("open_positions"))
    active_positions = _num(row.get("active_positions"))
    if open_positions is None or active_positions is None or open_positions <= 0:
        return None
    return active_positions / open_positions * 100.0


# ---------------------------------------------------------------------------
# Filter (murni)
# ---------------------------------------------------------------------------

def base_market_cap(row: dict):
    """Market cap token base (token_x, sisi token di listing Meteora)."""
    return _num((row.get("token_x") or {}).get("market_cap"))


def volatility_multiple(fee_active_tvl, volatility):
    """(Fee/Active TVL %) ÷ volatility %. ``None`` bila volatility tidak terukur."""
    if fee_active_tvl is None or volatility is None or volatility < FLOW_VOLATILITY_EPS:
        return None
    return fee_active_tvl / volatility


def evaluate_pool(row: dict) -> dict:
    """Terapkan semua aturan filter pada satu baris pool. Kembalikan hasil lengkap."""
    pool = str(row.get("pool_address") or "")
    mint = mint_of_pool(row)
    symbol, name = token_info(row, mint)
    fee_tier = _num(row.get("fee_pct"))
    tvl = _num(row.get("tvl"))
    active_tvl = _num(row.get("active_tvl"))
    holders = _num(row.get("base_token_holders"))
    market_cap = base_market_cap(row)
    volatility = _num(row.get("volatility"))
    fee_active_tvl = _num(row.get("fee_active_tvl_ratio"))
    multiple = volatility_multiple(fee_active_tvl, volatility)

    reasons: list[str] = []
    if fee_tier is None or fee_tier < FLOW_FEE_TIER_MIN:
        reasons.append(f"fee tier < {FLOW_FEE_TIER_MIN:g}%")
    if tvl is None or tvl < FLOW_TVL_MIN:
        reasons.append(f"TVL < {fmt_usd(FLOW_TVL_MIN)}")
    if active_tvl is None or active_tvl < FLOW_ACTIVE_TVL_MIN:
        reasons.append(f"active TVL < {fmt_usd(FLOW_ACTIVE_TVL_MIN)}")
    if holders is None or holders < FLOW_HOLDERS_MIN:
        reasons.append(f"holders < {FLOW_HOLDERS_MIN:,}".replace(",", "."))
    if market_cap is None or market_cap < FLOW_MARKET_CAP_MIN:
        reasons.append(f"market cap < {fmt_usd(FLOW_MARKET_CAP_MIN)}")
    if volatility is None:
        reasons.append("volatility tidak terukur")
    elif volatility < FLOW_VOLATILITY_EPS:
        reasons.append("volatility ≈ 0 (tidak terukur)")
    elif volatility > FLOW_VOLATILITY_MAX:
        reasons.append(f"volatility > {FLOW_VOLATILITY_MAX:g}%")
    if fee_active_tvl is None:
        reasons.append("fee/active TVL tidak terukur")
    elif fee_active_tvl < FLOW_FEE_ACTIVE_TVL_MIN:
        reasons.append(f"fee/active TVL < {FLOW_FEE_ACTIVE_TVL_MIN:g}%")
    if multiple is None:
        if volatility is None or volatility < FLOW_VOLATILITY_EPS or fee_active_tvl is None:
            pass  # sudah dicatat di atas
        else:
            reasons.append("fee/active TVL tidak terukur")
    elif multiple < FLOW_MULTIPLE_MIN:
        reasons.append(f"fee/active ÷ volatility < {FLOW_MULTIPLE_MIN:g}x")

    return {
        "pool": pool,
        "mint": mint,
        "symbol": symbol,
        "name": name,
        "pool_name": str(row.get("name") or ""),
        "fee_tier": fee_tier,
        "tvl": tvl,
        "active_tvl": active_tvl,
        "holders": holders,
        "market_cap": market_cap,
        "open_positions": _num(row.get("open_positions")),
        "in_range": in_range_pct(row),
        "volatility": volatility,
        "fee_active_tvl": fee_active_tvl,
        "multiple": multiple,
        "passes": not reasons,
        "reasons": reasons,
    }


def sort_key(result: dict):
    """Rasio (Fee/Active TVL ÷ volatility) terbesar dulu; seri: Fee/Active TVL terbesar."""
    return (-(result["multiple"] or 0.0), -(result["fee_active_tvl"] or 0.0))


def scan_pools(max_pages: int = FLOW_MAX_PAGES, *, listing: tuple | None = None) -> dict:
    """Scan lengkap: listing 24H → filter → urutan.

    ``listing`` = (rows, errors, truncated) bisa diisi untuk tes tanpa jaringan.
    """
    rows, errors, truncated = (listing if listing is not None
                               else fetch_listing(max_pages))
    unique: dict[str, dict] = {}
    for row in rows:
        address = str(row.get("pool_address") or "")
        if address and address not in unique:
            unique[address] = row
    results = [evaluate_pool(row) for row in unique.values()]
    passing = sorted((r for r in results if r["passes"]), key=sort_key)
    return {
        "scanned_at": now_iso(),
        "listing_rows": len(rows),
        "listing_errors": len(errors),
        "truncated": bool(truncated),
        "candidates": len(unique),
        "results": results,
        "passing": passing,
    }


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
# Alert: pool terbaik (tiap 4 jam)
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


MEDALS = ("🥇", "🥈", "🥉")


def fmt_mult(value) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}x".replace(".", ",")


def filter_summary_text() -> str:
    return (f"🎯 fee tier ≥ {FLOW_FEE_TIER_MIN:g}% · 💰 TVL ≥ {fmt_usd(FLOW_TVL_MIN)} · "
            f"🪙 active TVL ≥ {fmt_usd(FLOW_ACTIVE_TVL_MIN)}\n"
            f"👥 holders ≥ {FLOW_HOLDERS_MIN:,} · 🏦 MC ≥ {fmt_usd(FLOW_MARKET_CAP_MIN)} · "
            f"⚡ fee/active TVL ≥ {FLOW_FEE_ACTIVE_TVL_MIN:g}% · 〰️ vol ≤ {FLOW_VOLATILITY_MAX:g}% · "
            f"✖️ fee/active ÷ vol ≥ {FLOW_MULTIPLE_MIN:g}x · ⏱ 24H")


def best_alert_text(no: int, passing: list, last_no: dict) -> str:
    """Alert pool terbaik. Pool yang sudah pernah muncul diberi nomor alert terakhirnya."""
    lines = [
        f"🏆 <b>BEST POOL</b> · alert #{no}",
        filter_summary_text(),
        "━━━━━━━━━━━━━━━━━━",
    ]
    for index, row in enumerate(passing, start=1):
        rank = MEDALS[index - 1] if index <= len(MEDALS) else f"{index}."
        seen = last_no.get(row["pool"])
        tag = f"🔁 sudah pernah · alert #{seen}" if seen else "🆕 baru"
        name = row["pool_name"] or row["pool"][:6]
        lines.append("")
        lines.append(f"{rank} <b>{_h(row['symbol'])}</b> · {_h(name)}  {tag}")
        lines.append(f"💰 TVL {fmt_usd(row['tvl'])} · 🏷 fee {row['fee_tier']:g}% · "
                     f"🪙 active {fmt_usd(row['active_tvl'])}")
        lines.append(f"〰️ vol {fmt_pct(row['volatility'])} · "
                     f"⚡ fee/active TVL {fmt_pct(row['fee_active_tvl'])} · "
                     f"✖️ {fmt_mult(row['multiple'])}")
        lines.extend(alert_link_lines(row.get("mint") or "", row["pool"]))
    return "\n".join(lines)


def apply_best_alert(state: dict, passing: list) -> str | None:
    """Buat teks alert dan perbarui nomor alert. ``None`` bila tidak ada pool lolos."""
    if not passing:
        return None
    no = int(state["best_alert"]["next_no"])
    last_no = dict(state["best_alert"]["last_no"])
    text = best_alert_text(no, passing, last_no)
    for row in passing:
        state["best_alert"]["last_no"][row["pool"]] = no
    state["best_alert"]["next_no"] = no + 1
    state["alerts"].append({"no": no, "kind": "best", "at": now_iso(),
                            "pools": [r["pool"] for r in passing]})
    del state["alerts"][:-FLOW_ALERT_CAP]
    return text


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
