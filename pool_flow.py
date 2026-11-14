# -*- coding: utf-8 -*-
"""🏆 Scan Best Pool Meteora — logika inti, tanpa Streamlit.

Permintaan user (2026-11-13):
- Listing Meteora pool-discovery, timeframe 12h, kategori top, dengan filter
  server-side yang diminta user (dlmm, market cap, holders, TVL, active TVL,
  tanpa konsentrasi/kepemilikan tunggal tinggi). Filter lokal: fee tier, fee/active
  avg volume/menit < $500, fee/active TVL < 1 %, dan volatility > 6 % dilewati
  (2026-11-13).
- Urutan: fee/active TVL terbesar dulu, seri: avg volume per menit (``avg_volume``) terbesar.
- Satu tabel saja, tanpa pemisahan risiko (2026-11-14).
- Alert Telegram (tiap 4 jam) memakai pool teratas dari urutan yang sama.
"""
from __future__ import annotations

import html as _html
import json
import math
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import links

POOLS_URL = "https://pool-discovery-api.datapi.meteora.ag/pools"
HTTP_TIMEOUT = 25
USER_AGENT = "Mozilla/5.0 (wallet-depth-pool-flow)"

FLOW_TIMEFRAME = "12h"
FLOW_TOKEN_TIMEFRAME = "12h"     # pool per token (permintaan user 2026-11-13: 12H)
FLOW_TVL_MIN = 10_000.0          # USD (tvl)
FLOW_ACTIVE_TVL_MIN = 10_000.0   # USD (active_tvl)
FLOW_HOLDERS_MIN = 1_500         # base_token_holders
FLOW_MARKET_CAP_MIN = 100_000.0  # USD (market cap token base)
# Filter lokal (permintaan user 2026-11-13, menggantikan semua filter lokal sebelumnya).
# Nilai yang tidak terukur (hilang) juga dilewati.
FLOW_AVG_VOLUME_MIN = 500.0      # USD per menit (avg_volume = volume 12H ÷ 720)
FLOW_FEE_ACTIVE_TVL_MIN = 1.0    # % (fee_active_tvl_ratio, fee ÷ active TVL)
FLOW_VOLATILITY_MAX = 6.0        # % (volatility), di atas ini dilewati
# Pra-saring di sisi server (request user 12H). Tidak ada filter lokal lain.
FLOW_SERVER_FILTER = (
    "base_token_has_high_supply_concentration=false"
    "&&base_token_has_high_single_ownership=false"
    "&&pool_type=dlmm"
    f"&&base_token_market_cap>={FLOW_MARKET_CAP_MIN:g}"
    f"&&base_token_holders>={FLOW_HOLDERS_MIN}"
    f"&&tvl>={FLOW_TVL_MIN:g}"
    f"&&active_tvl>={FLOW_ACTIVE_TVL_MIN:g}"
)
FLOW_MAX_PAGES = 100             # batas keamanan: 100 × 50 = 5.000 pool (cursor after_key)
FLOW_PAGE_SIZE = 50
FLOW_ALERT_CAP = 300             # riwayat alert yang disimpan
FLOW_TOKEN_PAGE_SIZE = 50       # pool per halaman untuk query per token
FLOW_TOKEN_MAX_PAGES = 20       # batas keamanan per token (20 × 50 pool)
FLOW_TOKEN_WORKERS = 4          # permintaan per token berjalan paralel

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


def fmt_usd2(value) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    text = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}${text}"


def fmt_int(value) -> str:
    if value is None:
        return "—"
    return f"{int(round(value)):,}".replace(",", ".")


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
    """Satu halaman listing kategori ``top`` pada timeframe 12H.

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


def fetch_token_pools(mint: str, max_pages: int = FLOW_TOKEN_MAX_PAGES) -> tuple[list, list, bool]:
    """Semua pool (semua tipe) yang memuat token ``mint`` pada timeframe 12H.

    Memakai ``query=<mint>`` dan cursor ``after_key`` seperti listing. Kembalikan
    (rows, errors, truncated), sama seperti ``fetch_listing``.
    """
    rows: list = []
    errors: list = []
    cursor = None
    for _ in range(max(1, max_pages)):
        params = {"query": mint, "timeframe": FLOW_TOKEN_TIMEFRAME,
                  "page_size": FLOW_TOKEN_PAGE_SIZE}
        if cursor:
            params["after_key"] = cursor
        try:
            payload = _get_payload(params)
        except Exception as exc:  # noqa: BLE001 — catat; tanpa cursor tidak bisa lanjut
            errors.append(str(exc) or type(exc).__name__)
            return rows, errors, True
        rows.extend(row for row in (payload.get("data") or []) if isinstance(row, dict))
        next_key = payload.get("after_key") or None
        if not payload.get("has_more") or not next_key:
            return rows, errors, False
        if str(next_key) == cursor:  # cursor macet: hentikan, jangan loop
            return rows, errors, True
        cursor = str(next_key)
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


def evaluate_pool(row: dict) -> dict:
    """Ambil field tampilan satu baris pool dan terapkan filter lokal 1 %.

    Filter server (listing) sudah dilakukan Meteora. Di sini dilewati:
    avg volume/menit < $500, fee/active TVL < 1 %, volatility > 6 % (atau tidak terukur).
    """
    pool = str(row.get("pool_address") or "")
    mint = mint_of_pool(row)
    symbol, name = token_info(row, mint)
    fee_tier = _num(row.get("fee_pct"))
    fee_active_tvl = _num(row.get("fee_active_tvl_ratio"))
    volatility = _num(row.get("volatility"))
    avg_volume = _num(row.get("avg_volume"))

    reasons: list[str] = []
    if avg_volume is None or avg_volume < FLOW_AVG_VOLUME_MIN:
        reasons.append(f"avg volume/menit < ${FLOW_AVG_VOLUME_MIN:g}")
    if fee_active_tvl is None or fee_active_tvl < FLOW_FEE_ACTIVE_TVL_MIN:
        reasons.append(f"fee/active TVL < {FLOW_FEE_ACTIVE_TVL_MIN:g}%")
    if volatility is None:
        reasons.append("volatility tidak terukur")
    elif volatility > FLOW_VOLATILITY_MAX:
        reasons.append(f"volatility > {FLOW_VOLATILITY_MAX:g}%")

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
        "avg_volume": avg_volume,
        "passes": not reasons,
        "reasons": reasons,
        "activity": pool_activity(row),
    }


# ---------------------------------------------------------------------------
# Aktivitas per token (permintaan user 2026-11-13). Hanya untuk tampilan scan;
# alert Telegram tidak memakai bagian ini.
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


def pools_of_mint(rows: list, mint: str) -> list[dict]:
    """Pool yang memuat ``mint`` (token_x atau token_y), tanpa duplikat, volume terbesar dulu."""
    seen: dict[str, dict] = {}
    for row in rows:
        address = str(row.get("pool_address") or "")
        sides = {str((row.get(key) or {}).get("address") or "") for key in ("token_x", "token_y")}
        if not address or mint not in sides or address in seen:
            continue
        seen[address] = pool_activity(row)
    return sorted(seen.values(), key=lambda item: -(item["volume"] or 0.0))


def token_total(pools: list[dict]) -> dict:
    """Total semua pool token. Rata² swap = total volume ÷ total swap (rata-rata tertimbang).

    Trader unik tidak dijumlahkan karena trader yang sama bisa ada di beberapa pool.
    """
    def total(key):
        values = [item[key] for item in pools if item[key] is not None]
        return sum(values) if values else None

    volume = total("volume")
    swaps = total("swaps")
    avg_swap = volume / swaps if (volume is not None and swaps and swaps > 0) else None
    return {"pools": len(pools), "volume": volume, "swaps": swaps, "avg_swap": avg_swap,
            "fee": total("fee"), "tvl": total("tvl"), "active_tvl": total("active_tvl")}


def build_token_stats(mint: str, rows: list, errors: list, truncated: bool,
                      fallback: dict | None = None) -> dict:
    """Gabungkan hasil fetch satu token. Bila tidak ada pool sama sekali, pakai pool hasil scan."""
    pools = pools_of_mint(rows, mint)
    used_fallback = False
    if not pools and fallback is not None:
        pools = [fallback]
        used_fallback = True
    return {
        "mint": mint,
        "pools": pools,
        "total": token_total(pools),
        "errors": list(errors),
        "truncated": bool(truncated),
        "fallback": used_fallback,
        "partial": bool(errors) or bool(truncated) or used_fallback,
    }


def enrich_scan_result(result: dict, fetch=None) -> dict:
    """Ambil semua pool untuk setiap token yang lolos, lalu simpan di ``result['token_stats']``.

    Daftar ``passing`` tidak diubah, jadi alert Telegram tetap sama.
    """
    fetch = fetch or fetch_token_pools
    fallback_by_mint: dict[str, dict] = {}
    for row in result.get("passing") or []:
        mint = row.get("mint") or ""
        if mint:
            fallback_by_mint.setdefault(mint, row.get("activity"))
    stats: dict[str, dict] = {}
    if fallback_by_mint:
        with ThreadPoolExecutor(max_workers=FLOW_TOKEN_WORKERS) as executor:
            futures = {mint: executor.submit(fetch, mint) for mint in fallback_by_mint}
            for mint, future in futures.items():
                try:
                    rows, errors, truncated = future.result()
                except Exception as exc:  # noqa: BLE001
                    rows, errors, truncated = [], [str(exc) or type(exc).__name__], True
                stats[mint] = build_token_stats(mint, rows, errors, truncated,
                                                fallback_by_mint.get(mint))
    result["token_stats"] = stats
    return result


def pool_item_12h(stats: dict | None, pool: str):
    """Baris pool (timeframe 12H) dari ``token_stats``; ``None`` bila tidak ada atau hasil fallback."""
    if not stats or stats.get("fallback"):
        return None
    return next((item for item in stats["pools"] if item["pool"] == pool), None)


def sort_key(result: dict):
    """Urutan tampilan dan alert: fee/active TVL terbesar dulu, seri: avg volume per menit terbesar."""
    return (-(result["fee_active_tvl"] or 0.0), -(result["avg_volume"] or 0.0))


def ranked(passing: list) -> list:
    """Pool diurutkan dari avg volume per menit terbesar (sama untuk tabel dan alert)."""
    return sorted(passing, key=sort_key)


def most_crowded(result: dict):
    """Pool paling ramai = avg volume per menit terbesar di seluruh hasil scan.

    Hanya memakai data listing (tanpa fetch per token), jadi alert tetap ringan.
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


def scan_pools(max_pages: int = FLOW_MAX_PAGES, *, listing: tuple | None = None) -> dict:
    """Scan lengkap: listing 12H (filter server-side) → urutan.

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


def _pct_or_dash(value) -> str:
    return f"{value:g}%" if value is not None else "—"


def crowded_alert_text(no: int, top: dict, seen_no: int | None) -> str:
    """Alert Telegram: hanya pool teratas (fee/active TVL terbesar, seri avg volume per menit)."""
    row = top["row"]
    tag = f"🔁 sudah pernah · alert #{seen_no}" if seen_no else "🆕 baru"
    name = top["pool_name"] or top["pool"][:6]
    lines = [
        f"🔥🔥🔥 <b>POOL PALING RAMAI</b> · alert #{no}",
        "🎯 hasil Scan Best Pool (filter 12H) · urut fee/active TVL, lalu avg volume/menit",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"🔥 <b>{_h(top['symbol'])}</b> · {_h(name)}  {tag}",
        f"📊 avg volume/menit {fmt_usd2(top['avg_volume'])} · volume 12H {fmt_usd(top['pool_volume'])}",
        f"🔁 {fmt_int(top['pool_swaps'])} swap · rata² swap {fmt_usd2(top['pool_avg_swap'])}",
        f"💰 TVL {fmt_usd(row['tvl'])} · 🏷 fee {_pct_or_dash(row['fee_tier'])} · "
        f"🪙 active {fmt_usd(row['active_tvl'])}",
        f"〰️ volatility {fmt_pct(row['volatility'])} · ⚡ fee/active TVL {fmt_pct(row['fee_active_tvl'])}",
    ]
    lines.extend(alert_link_lines(row.get("mint") or "", top["pool"]))
    return "\n".join(lines)


def apply_crowded_alert(state: dict, top: dict | None) -> str | None:
    """Buat teks alert pool paling ramai dan perbarui nomor alert. ``None`` bila tidak ada."""
    if top is None:
        return None
    pool = top["pool"]
    no = int(state["best_alert"]["next_no"])
    seen_no = state["best_alert"]["last_no"].get(pool)
    text = crowded_alert_text(no, top, seen_no)
    state["best_alert"]["last_no"][pool] = no
    state["best_alert"]["next_no"] = no + 1
    state["alerts"].append({"no": no, "kind": "best", "at": now_iso(), "pools": [pool]})
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
