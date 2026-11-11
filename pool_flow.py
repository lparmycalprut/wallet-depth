# -*- coding: utf-8 -*-
"""🏆 Scan Best Pool (net deposit) — logika inti, tanpa Streamlit.

Permintaan user (2026-11-10):
- Filter minimum: fee tier ≥ 1 %, TVL ≥ 50.000 USD, avg fee/menit ≥ 5 USD
  (fee 24J ÷ 1440; asumsi, dikonfirmasi user).
- Tampilkan hanya pool yang net deposit-nya POSITIF di semua window
  1H, 4H, 12H, dan 24H.
- Watchlist: pool yang dipilih user; detail mencatat net deposit tiap scan.
- Alert 1 (tiap 30 menit): pool terbaik yang lolos filter. Pool yang sudah
  pernah muncul di alert sebelumnya diberi tanda nomor alert terakhirnya.
- Alert 2 (tiap 10 menit): watchlist; alert saat net deposit H1 + H4 berubah
  menjadi negatif (tanda awal likuiditas ditarik).

Keterbatasan: Meteora tidak punya filter TVL/fee di sisi server (diuji:
``min_tvl`` diabaikan), dan total listing ±310.000 pool. Karena itu daftar
kandidat diambil dari ``category=top`` sampai ``FLOW_MAX_PAGES`` halaman, lalu
setiap kandidat dicek per window memakai ``query=<mint>``.
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

FLOW_WINDOWS = ("1h", "4h", "12h", "24h")
FLOW_FEE_TIER_MIN = 1.0        # fee tier pool (%), di bawah ini dilewati (diubah 2→1, 2026-11-11)
FLOW_TVL_MIN = 50_000.0        # USD
FLOW_AVG_FEE_MIN = 5.0         # USD per menit = fee 24J ÷ 1440 (lihat avg_fee_per_min)
FLOW_LISTING_MINUTES = 24 * 60  # window listing 24H dalam menit
FLOW_MAX_PAGES = 100           # 100 × 50 = 5.000 pool teratas kategori top
FLOW_PAGE_SIZE = 50
FLOW_LIST_WORKERS = 8
FLOW_HISTORY_CAP = 2000        # snapshot per pool yang disimpan
FLOW_ALERT_CAP = 300           # riwayat alert yang disimpan

STATE_PATH = Path(__file__).resolve().parent / "pool_flow_state.json"

ENV_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_CHAT = "TELEGRAM_CHAT_ID"


# ---------------------------------------------------------------------------
# Angka & waktu
# ---------------------------------------------------------------------------

def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def net_of(row: dict | None):
    """Net deposit (USD) satu pool pada satu window; ``None`` bila tidak terukur."""
    if not row:
        return None
    net = _num(row.get("net_deposits"))
    if net is not None:
        return net
    deposits = _num(row.get("total_deposits"))
    withdraws = _num(row.get("total_withdraws"))
    if deposits is None or withdraws is None:
        return None
    return deposits - withdraws


# ---------------------------------------------------------------------------
# Pengambilan data Meteora
# ---------------------------------------------------------------------------

def _get_json(params: dict, *, timeout: int = HTTP_TIMEOUT):
    url = POOLS_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    rows = payload.get("data") if isinstance(payload, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def fetch_top_page(timeframe: str, page: int) -> list:
    """Satu halaman listing kategori ``top`` untuk ``timeframe``."""
    return _get_json({"page_size": FLOW_PAGE_SIZE, "timeframe": timeframe,
                      "category": "top", "page": page})


def fetch_top_listing(timeframe: str = "24h", *, max_pages: int = FLOW_MAX_PAGES,
                      workers: int = FLOW_LIST_WORKERS) -> tuple[list, list]:
    """Ambil halaman 1..max_pages paralel. Kembalikan (rows, errors)."""
    rows: list = []
    errors: list = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(fetch_top_page, timeframe, page)
                   for page in range(1, max(1, max_pages) + 1)]
        for future in futures:
            try:
                rows.extend(future.result())
            except Exception as exc:  # noqa: BLE001 — catat, lanjut halaman lain
                errors.append(str(exc) or type(exc).__name__)
    return rows, errors


def fetch_mint_window(mint: str, timeframe: str) -> list:
    """Semua pool yang memuat ``mint`` pada ``timeframe``."""
    return _get_json({"page_size": FLOW_PAGE_SIZE, "timeframe": timeframe,
                      "category": "top", "query": mint})


def pool_row_for_window(mint: str, pool_address: str, timeframe: str):
    """Baris pool ``pool_address`` pada ``timeframe`` (atau ``None``)."""
    for row in fetch_mint_window(mint, timeframe):
        if str(row.get("pool_address") or "") == pool_address:
            return row
    return None


# ---------------------------------------------------------------------------
# Filter (murni)
# ---------------------------------------------------------------------------

def base_passes(row: dict) -> tuple[bool, str]:
    """Filter dasar dari baris listing 24H. Kembalikan (lolos, alasan_gagal)."""
    fee_tier = _num(row.get("fee_pct"))
    if fee_tier is None or fee_tier < FLOW_FEE_TIER_MIN:
        return False, f"fee tier < {FLOW_FEE_TIER_MIN:g}%"
    tvl = _num(row.get("tvl"))
    if tvl is None or tvl < FLOW_TVL_MIN:
        return False, f"TVL < ${FLOW_TVL_MIN:,.0f}"
    avg_fee = avg_fee_per_min(row)
    if avg_fee is None or avg_fee < FLOW_AVG_FEE_MIN:
        return False, f"fee/menit < ${FLOW_AVG_FEE_MIN:g}"
    return True, ""


def avg_fee_per_min(row: dict):
    """Rata-rata fee per menit (USD) pada window listing 24H.

    Meteora tidak mengirim field ``avg_fee``; yang ada adalah ``fee`` (USD
    fee dalam window). Dibagi jumlah menit window → fee per menit.
    """
    fee = _num(row.get("fee"))
    if fee is None:
        return None
    return fee / FLOW_LISTING_MINUTES


def token_info(row: dict, mint: str) -> tuple[str, str]:
    """(symbol, name) token ``mint`` di dalam baris pool."""
    for side_key in ("token_x", "token_y"):
        side = row.get(side_key) or {}
        if str(side.get("address") or "") == mint:
            return str(side.get("symbol") or "?"), str(side.get("name") or "")
    other = row.get("token_x") or {}
    return str(other.get("symbol") or "?"), str(other.get("name") or "")


def mint_of_pool(row: dict) -> str:
    """Mint non-SOL dari pool (token_x kecuali itu SOL)."""
    sol = "So11111111111111111111111111111111111111112"
    x = str((row.get("token_x") or {}).get("address") or "")
    y = str((row.get("token_y") or {}).get("address") or "")
    return y if x == sol else x


def evaluate_pool(row24: dict, nets_by_window: dict) -> dict:
    """Gabungkan baris 24H dan net per window menjadi satu hasil kandidat."""
    pool = str(row24.get("pool_address") or "")
    mint = mint_of_pool(row24)
    symbol, name = token_info(row24, mint)
    nets = {w: net_of(nets_by_window.get(w)) for w in FLOW_WINDOWS}
    base_ok, base_reason = base_passes(row24)
    missing = [w for w in FLOW_WINDOWS if nets[w] is None]
    negative = [w for w in FLOW_WINDOWS if nets[w] is not None and nets[w] <= 0]
    if not base_ok:
        reason = base_reason
    elif missing:
        reason = "net tidak terukur: " + ", ".join(w.upper() for w in missing)
    elif negative:
        reason = "net tidak positif: " + ", ".join(w.upper() for w in negative)
    else:
        reason = ""
    return {
        "pool": pool,
        "mint": mint,
        "symbol": symbol,
        "name": name,
        "pool_name": str(row24.get("name") or ""),
        "tvl": _num(row24.get("tvl")),
        "fee_tier": _num(row24.get("fee_pct")),
        "avg_fee": avg_fee_per_min(row24),
        "nets": nets,
        "passes": not reason,
        "reason": reason,
    }


def candidates_from_listing(rows: list) -> dict:
    """Pool unik dari listing 24H yang lolos filter dasar (dedupe per pool)."""
    out: dict[str, dict] = {}
    for row in rows:
        address = str(row.get("pool_address") or "")
        if not address or address in out:
            continue
        if base_passes(row)[0]:
            out[address] = row
    return out


def scan_candidates(max_pages: int = FLOW_MAX_PAGES, *,
                    listing: tuple | None = None) -> dict:
    """Scan lengkap: listing 24H → filter dasar → net per window per kandidat.

    ``listing`` bisa diisi (rows, errors) untuk tes tanpa jaringan.
    Kembalikan dict dengan ``results`` (semua kandidat yang dievaluasi),
    ``passing`` (yang lolos semua), dan statistik.
    """
    rows, errors = listing if listing is not None else fetch_top_listing(max_pages=max_pages)
    candidates = candidates_from_listing(rows)
    results = []
    for address, row24 in candidates.items():
        nets_by_window = {"24h": row24}
        mint = mint_of_pool(row24)
        for window in ("1h", "4h", "12h"):
            try:
                nets_by_window[window] = pool_row_for_window(mint, address, window)
            except Exception:  # noqa: BLE001 — jaringan gagal = tidak terukur
                nets_by_window[window] = None
        results.append(evaluate_pool(row24, nets_by_window))
    passing = sorted((r for r in results if r["passes"]),
                     key=lambda r: -(r["nets"].get("24h") or 0.0))
    return {
        "scanned_at": now_iso(),
        "listing_rows": len(rows),
        "listing_errors": len(errors),
        "candidates": len(candidates),
        "results": results,
        "passing": passing,
    }


# ---------------------------------------------------------------------------
# State (watchlist, riwayat, alert)
# ---------------------------------------------------------------------------

def empty_state() -> dict:
    return {
        "version": 1,
        "watchlist": [],
        "history": {},
        "best_alert": {"next_no": 1, "last_no": {}},
        "watch_negative": {},
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
        state.update({k: v for k, v in data.items() if k in state})
    return state


def save_state(state: dict, path: Path | None = None) -> None:
    path = Path(path) if path is not None else STATE_PATH
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")


def watch_add(state: dict, *, pool: str, mint: str, symbol: str, name: str) -> bool:
    """Tambah ke watchlist. ``False`` bila sudah ada."""
    if any(item["pool"] == pool for item in state["watchlist"]):
        return False
    state["watchlist"].append({"pool": pool, "mint": mint, "symbol": symbol,
                               "name": name, "added_at": now_iso()})
    return True


def watch_remove(state: dict, pool: str) -> bool:
    before = len(state["watchlist"])
    state["watchlist"] = [i for i in state["watchlist"] if i["pool"] != pool]
    state["watch_negative"].pop(pool, None)
    return len(state["watchlist"]) != before


def record_snapshot(state: dict, pool: str, nets: dict, *, tvl=None,
                    ts: str | None = None) -> None:
    """Catat net deposit satu pool. Riwayat dipangkas ke ``FLOW_HISTORY_CAP``."""
    entry = {"ts": ts or now_iso(), "tvl": tvl}
    for window in FLOW_WINDOWS:
        entry[f"net_{window}"] = nets.get(window)
    history = state["history"].setdefault(pool, [])
    history.append(entry)
    if len(history) > FLOW_HISTORY_CAP:
        del history[:len(history) - FLOW_HISTORY_CAP]


def record_scan(state: dict, results: list, *, ts: str | None = None) -> int:
    """Catat snapshot semua kandidat yang dievaluasi. Kembalikan jumlahnya."""
    for result in results:
        record_snapshot(state, result["pool"], result["nets"], tvl=result["tvl"], ts=ts)
    return len(results)


# ---------------------------------------------------------------------------
# Alert: pool terbaik (tiap 30 menit)
# ---------------------------------------------------------------------------

def _h(value) -> str:
    """Escape untuk Telegram HTML."""
    return _html.escape(str(value or ""), quote=True)


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


def best_alert_text(no: int, passing: list, last_no: dict) -> str:
    """Alert pool terbaik. Pool yang sudah pernah muncul diberi nomor alert terakhirnya."""
    lines = [
        f"🏆 <b>BEST POOL</b> · alert #{no}",
        f"🎯 fee ≥ {FLOW_FEE_TIER_MIN:g}% · 💰 TVL ≥ {fmt_usd(FLOW_TVL_MIN)} · "
        f"⚡ ≥ {fmt_usd(FLOW_AVG_FEE_MIN)}/mnt",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for index, row in enumerate(passing, start=1):
        rank = MEDALS[index - 1] if index <= len(MEDALS) else f"{index}."
        seen = last_no.get(row["pool"])
        tag = f"🔁 sudah pernah · alert #{seen}" if seen else "🆕 baru"
        name = row["pool_name"] or row["pool"][:6]
        nets = "  ".join(f"{w.upper()} {fmt_signed(row['nets'][w])}" for w in FLOW_WINDOWS)
        lines.append("")
        lines.append(f"{rank} <b>{_h(row['symbol'])}</b> · {_h(name)}  {tag}")
        lines.append(f"💰 TVL {fmt_usd(row['tvl'])} · 🏷 fee {row['fee_tier']:g}% · "
                     f"⚡ {fmt_usd(row.get('avg_fee'))}/mnt")
        lines.append(f"📈 {nets}")
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
# Alert: watchlist (tiap 10 menit)
# ---------------------------------------------------------------------------

def watch_sum_h1_h4(nets: dict):
    """Net H1 + H4; ``None`` bila salah satunya tidak terukur."""
    h1, h4 = nets.get("1h"), nets.get("4h")
    if h1 is None or h4 is None:
        return None
    return h1 + h4


def watch_transition_alerts(state: dict, checks: list) -> list[str]:
    """``checks`` = [{pool, symbol, nets}]. Alert hanya saat berubah menjadi negatif.

    Keadaan disimpan di ``state["watch_negative"]``, sehingga alert tidak
    berulang selama net masih negatif.
    """
    messages: list[str] = []
    for check in checks:
        pool = check["pool"]
        total = watch_sum_h1_h4(check["nets"])
        if total is None:
            continue
        was_negative = bool(state["watch_negative"].get(pool))
        is_negative = total < 0
        state["watch_negative"][pool] = is_negative
        if is_negative and not was_negative:
            h1, h4 = check["nets"].get("1h"), check["nets"].get("4h")
            text_lines = [
                "🚨 <b>LIKUIDITAS DITARIK?</b>",
                f"🪙 <b>{_h(check['symbol'])}</b>",
                f"📉 Net H1 + H4 jadi <b>{fmt_signed(total)}</b>",
                f"   ⏱ H1 {fmt_signed(h1)}  ·  H4 {fmt_signed(h4)}",
            ]
            text_lines.extend(alert_link_lines(check.get("mint") or "", pool))
            messages.append("\n".join(text_lines))
    return messages


def fmt_signed(value) -> str:
    """Seperti ``fmt_usd`` tetapi nilai positif diberi tanda +."""
    text = fmt_usd(value)
    return f"+{text}" if value is not None and value > 0 else text


def fmt_usd(value) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}".replace(",", ".")


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


def send_telegram(text: str) -> tuple[bool, str]:
    """Kirim pesan (dipecah bila panjang). ``(False, alasan)`` bila gagal."""
    chunks = split_for_telegram(text)
    for chunk in chunks:
        ok, error = _send_telegram_once(chunk)
        if not ok:
            return False, error
    return True, ""


def _send_telegram_once(text: str) -> tuple[bool, str]:
    token = (os.environ.get(ENV_TOKEN) or "").strip()
    chat = (os.environ.get(ENV_CHAT) or "").strip()
    if not token or not chat:
        return False, "kredensial Telegram belum dipasang"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat, "text": text,
                          "parse_mode": "HTML",
                          "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT):
            return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:160]
