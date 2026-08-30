# -*- coding: utf-8 -*-
"""Silent accumulation (12 jam) & holder dust analysis untuk Wallet Depth.

Modul pengganti seluruh engine sinyal lama (reversal / serok / telegram):

1. ``fetch_holders`` / ``classify_holders``
   Membaca daftar holder dari GMGN (paginasi penuh via cursor ``next``),
   memisahkan **real holder > $10 value** dengan **dust holder (0 < value
   <= $10)**, dan menghitung berapa % total marketcap yang dipegang dust.

2. ``fetch_12h_flow``
   Mengambil trade 12 jam terakhir dari GMGN ``token_trades`` lalu
   menghitung net flow USD, jumlah wallet yang mengakumulasi, dan
   perubahan harga — dasar deteksi **silent accumulation**.

3. ``analyze_token``
   Gabungan dua data di atas untuk satu token (dipakai scanning Trending,
   Degen, watchlist, dan cron).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from core import get_market, load_config

# --- Ambang default -----------------------------------------------------------
DUST_LIMIT_USD = 10.0          # "> $10 value" = real holder; sisanya dust
SILENT_WINDOW_HOURS = 12       # window pengecekan 12 jam terakhir
SILENT_NET_USD_MIN = 50.0      # net flow minimum agar layak disebut akumulasi
SILENT_ACC_WALLETS_MIN = 3     # minimal wallet net-beli
SILENT_PRICE_CHG_MAX = 5.0     # harga boleh bergerak maksimal ±5% (diam-diam)
SILENT_BOT_SHARE_MAX = 0.35    # share volume mev/bot maksimal
DEFAULT_MAX_WALLETS = 3000     # batas holder yang dianalisis per token
DEFAULT_MAX_TRADE_PAGES = 8    # maks 800 trade / 12 jam per token
HOLDER_PAGE_LIMIT = 1000

HOLDER_URL = "https://gmgn.ai/vas/api/v1/token_holders/sol/{ca}"

# Pencilan non-wallet (LP/AMM/pool) dikeluarkan dari hitungan holder.
NOISE_TAGS = frozenset(("sandwich_bot", "mev_bot", "mev"))

# Cache in-memory per proses/sesi: TTL singkat supaya scan ulang tidak
# membanjiri GMGN dalam beberapa detik.
_CACHE_TTL = 600
_HOLDER_CACHE: dict[str, dict] = {}
_FLOW_CACHE: dict[str, dict] = {}


def _float(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        return num if num == num else default  # NaN guard
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    return int(_float(value, float(default)))


def _http_get(url: str, params: dict, timeout: int = 20) -> dict:
    """GET JSON dengan TLS browser (curl_cffi), fallback requests."""
    headers = {
        "accept": "application/json, text/plain, */*",
        "origin": "https://gmgn.ai",
        "referer": "https://gmgn.ai/",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/150.0.0.0 Safari/537.36"),
    }
    try:
        from curl_cffi import requests as client
        for identity in ("chrome", "chrome131", "safari17_0"):
            try:
                response = client.get(url, params=params, timeout=timeout,
                                      impersonate=identity, headers=headers)
                if response.status_code == 200:
                    return response.json() or {}
            except Exception:
                continue
        raise RuntimeError("curl_cffi semua profil gagal")
    except ImportError:
        pass
    except Exception:
        # Lanjut fallback requests; error hanya dicatat di bawah.
        pass
    try:
        import requests
        response = requests.get(url, params=params, headers=headers,
                                timeout=timeout)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        return response.json() or {}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"holders GET gagal: {exc}") from exc


def _holder_params(next_cursor: str | None, limit: int) -> dict:
    """Param holder endpoint: wajib cost/orderby/direction + build web."""
    params = {
        "limit": max(1, min(int(limit), HOLDER_PAGE_LIMIT)),
        "cost": "20",
        "orderby": "amount_percentage",
        "direction": "desc",
    }
    if next_cursor:
        params["next"] = next_cursor
    try:
        from gmgn_screener import _build_tag, DEVICE_ID, FP_DID
        build = _build_tag()
        params.update(
            device_id=DEVICE_ID,
            fp_did=FP_DID,
            client_id=f"gmgn_web_{build}",
            app_ver=build,
            from_app="gmgn",
            tz_name="Asia/Jakarta",
            tz_offset="25200",
            app_lang="en-US",
            os="web",
            worker="0",
        )
    except Exception:
        import uuid
        params.update(device_id=str(uuid.uuid4()), fp_did=uuid.uuid4().hex)
    return params


def _normalize_holder(raw: dict) -> dict | None:
    """Satu baris holder GMGN -> dict ringkas yang siap dianalisis."""
    if not isinstance(raw, dict):
        return None
    addr = str(raw.get("address") or raw.get("account_address") or "")
    if not addr:
        return None
    balance = _float(raw.get("balance", raw.get("amount_cur")))
    usd_value = _float(raw.get("usd_value"))
    exchange = str(raw.get("exchange") or "").strip()
    is_wallet = (int(_float(raw.get("addr_type"), 1)) == 0 and not exchange)
    return {
        "address": addr,
        "account_address": str(raw.get("account_address") or ""),
        "balance": balance,
        "usd_value": usd_value,
        "amount_pct": _float(raw.get("amount_percentage")),  # fraksi 0-1
        "is_wallet": is_wallet,
        "is_new": bool(raw.get("is_new")),
        "is_suspicious": bool(raw.get("is_suspicious")),
        "start_holding_at": _int(raw.get("start_holding_at")),
        "last_active_at": _int(raw.get("last_active_timestamp")),
        "netflow_usd": _float(raw.get("netflow_usd")),
        "current_buy_amount": _float(raw.get("current_buy_amount")),
        "current_sell_amount": _float(raw.get("current_sell_amount")),
        "current_transfer_in": _float(raw.get("current_transfer_in_amount")),
        "current_transfer_out": _float(raw.get("current_transfer_out_amount")),
        "wallet_tag": str(raw.get("wallet_tag_v2") or ""),
        "tags": [str(tag) for tag in (raw.get("tags") or [])],
        "maker_token_tags": [str(tag) for tag in
                             (raw.get("maker_token_tags") or [])],
    }


def fetch_holders(ca: str, *, max_wallets: int | None = None,
                  page_limit: int = HOLDER_PAGE_LIMIT,
                  timeout: int = 20) -> dict:
    """Ambil daftar holder (paginasi ``next``) sampai batas ``max_wallets``.

    Return ``{"holders": [...], "pages": n, "truncated": bool,
    "fetched": n, "analyzed_at": ts}``.
    """
    ca = str(ca or "").strip()
    if not ca:
        return {"holders": [], "pages": 0, "truncated": False,
                "fetched": 0, "analyzed_at": int(time.time())}
    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)
    cache_key = f"{ca}:{max_wallets}"
    cached = _HOLDER_CACHE.get(cache_key)
    if cached and time.time() - cached.get("analyzed_at", 0) < _CACHE_TTL:
        return dict(cached)

    holders: dict[str, dict] = {}
    cursor = None
    pages = 0
    seen_cursors = set()
    truncated = False
    last_error = ""
    while True:
        payload = _http_get(
            HOLDER_URL.format(ca=ca),
            params=_holder_params(cursor, page_limit), timeout=timeout)
        code = payload.get("code")
        if code not in (None, 0, "0", "success"):
            raise RuntimeError(f"GMGN holders code={code}"
                               f" {payload.get('message') or ''}".strip())
        data = payload.get("data") or {}
        rows = data.get("list") or []
        pages += 1
        for raw in rows:
            holder = _normalize_holder(raw)
            if holder and holder["address"] not in holders:
                holders[holder["address"]] = holder
        next_cursor = str(data.get("next") or "").strip()
        if len(holders) >= max_wallets:
            truncated = len(holders) >= max_wallets
            break
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        if pages >= 60:  # pengaman keras
            truncated = True
            break
    result = {
        "holders": list(holders.values()),
        "pages": pages,
        "truncated": truncated,
        "fetched": len(holders),
        "analyzed_at": int(time.time()),
    }
    _HOLDER_CACHE[cache_key] = result
    return result


def classify_holders(snapshot: dict | None, market_cap: float = 0.0,
                     *, dust_limit: float | None = None) -> dict:
    """Pisahkan real holder (>$10 value) vs dust (0 < value <= $10).

    Return metrik: jumlah wallet, nilai USD kedua kelompok, dan
    **dust % dari marketcap** (dust_value / marketcap * 100) plus
    dust % supply (dari amount_percentage) bila tersedia.
    """
    dust_limit = float(DUST_LIMIT_USD if dust_limit is None else dust_limit)
    holders = (snapshot or {}).get("holders") or []
    real = [h for h in holders
            if h.get("is_wallet") and h.get("usd_value", 0) > dust_limit]
    dust = [h for h in holders
            if h.get("is_wallet")
            and 0 < h.get("usd_value", 0) <= dust_limit]
    real_value = sum(h.get("usd_value", 0) for h in real)
    dust_value = sum(h.get("usd_value", 0) for h in dust)
    real_supply = sum(h.get("amount_pct", 0) for h in real)
    dust_supply = sum(h.get("amount_pct", 0) for h in dust)
    mc = float(market_cap or 0)
    dust_pct_mc = (dust_value / mc * 100.0) if mc > 0 else None
    real_pct_mc = (real_value / mc * 100.0) if mc > 0 else None
    return {
        "dust_limit_usd": dust_limit,
        "real_count": len(real),
        "dust_count": len(dust),
        "wallets_analyzed": len(real) + len(dust),
        "total_fetched": len(holders),
        "truncated": bool((snapshot or {}).get("truncated")),
        "pages": int((snapshot or {}).get("pages") or 0),
        "real_value_usd": round(real_value, 2),
        "dust_value_usd": round(dust_value, 2),
        "dust_pct_mc": round(dust_pct_mc, 4) if dust_pct_mc is not None else None,
        "real_pct_mc": round(real_pct_mc, 4) if real_pct_mc is not None else None,
        "dust_pct_supply": round(dust_supply * 100.0, 4),
        "real_pct_supply": round(real_supply * 100.0, 4),
        "new_real": sum(1 for h in real if h.get("is_new")),
        "new_dust": sum(1 for h in dust if h.get("is_new")),
        "suspicious_dust": sum(1 for h in dust if h.get("is_suspicious")),
    }


def fetch_12h_flow(ca: str, *, now_ts: int | None = None,
                   hours: float = SILENT_WINDOW_HOURS,
                   max_pages: int = DEFAULT_MAX_TRADE_PAGES) -> dict:
    """Net flow 12 jam terakhir dari GMGN token_trades.

    Mengembalikan buy/sell USD, net, jumlah wallet akumulator vs
    distributor, bot share, dan price change dari trade pertama/terakhir.
    Trade di luar window disaring ulang secara lokal (GMGN kadang
    mengabaikan param from/to).
    """
    ca = str(ca or "").strip()
    now_ts = int(now_ts or time.time())
    from_ts = now_ts - int(float(hours) * 3600)
    cache_key = f"{ca}:{now_ts // 300}:{hours}:{max_pages}"
    cached = _FLOW_CACHE.get(cache_key)
    if cached and time.time() - cached.get("analyzed_at", 0) < _CACHE_TTL:
        return dict(cached)

    from cvd import fetch_gmgn_swaps
    try:
        swaps, _sig, _ts, _hit = fetch_gmgn_swaps(
            ca, from_ts=from_ts, to_ts=now_ts, max_pages=max_pages,
            page_limit=100, sleep=0.0)
    except Exception as exc:  # noqa: BLE001
        swaps = []

    buy_usd = sell_usd = buy_sol = sell_sol = 0.0
    buy_tx = sell_tx = 0
    per_wallet: dict[str, dict] = {}
    prices: list[tuple[int, float]] = []
    bot_usd = 0.0
    for swap in swaps or []:
        if not isinstance(swap, (list, tuple)) or len(swap) < 7:
            continue
        side = str(swap[0]).lower()
        ts = _int(swap[2])
        if side not in ("buy", "sell") or ts <= 0:
            continue
        if not (from_ts <= ts <= now_ts):  # filter lokal
            continue
        wallet = str(swap[3] or "").strip()
        usd = _float(swap[5])
        sol = _float(swap[1])
        tags = set(str(tag).strip().lower() for tag in (swap[6] or []))
        if side == "buy":
            buy_usd += usd
            buy_sol += sol
            buy_tx += 1
        else:
            sell_usd += usd
            sell_sol += sol
            sell_tx += 1
        if wallet:
            slot = per_wallet.setdefault(wallet, {"buy_usd": 0.0,
                                                  "sell_usd": 0.0,
                                                  "buy_tx": 0, "sell_tx": 0})
            slot[f"{side}_usd"] += usd
            slot[f"{side}_tx"] += 1
        price = _float(swap[4])
        if price > 0:
            prices.append((ts, price))
        if tags & NOISE_TAGS:
            bot_usd += usd

    accumulators = [w for w, s in per_wallet.items()
                    if s["buy_usd"] > s["sell_usd"] and s["buy_usd"] > 0]
    distributors = [w for w, s in per_wallet.items()
                    if s["sell_usd"] > s["buy_usd"] and s["sell_usd"] > 0]
    flat = [w for w, s in per_wallet.items()
            if w not in accumulators and w not in distributors]

    volume = buy_usd + sell_usd
    price_start = price_end = None
    if prices:
        prices.sort(key=lambda item: item[0])
        price_start = prices[0][1]
        price_end = prices[-1][1]
    price_chg = None
    if price_start and price_end and price_start > 0:
        price_chg = (price_end / price_start - 1.0) * 100.0
    result = {
        "window_hours": float(hours),
        "from_ts": from_ts,
        "to_ts": now_ts,
        "analyzed_at": int(now_ts),
        "buy_usd": round(buy_usd, 2),
        "sell_usd": round(sell_usd, 2),
        "net_usd": round(buy_usd - sell_usd, 2),
        "volume_usd": round(volume, 2),
        "buy_tx": buy_tx,
        "sell_tx": sell_tx,
        "wallets": len(per_wallet),
        "accumulators": len(accumulators),
        "distributors": len(distributors),
        "flat_wallets": len(flat),
        "bot_usd": round(bot_usd, 2),
        "bot_share": (bot_usd / volume) if volume > 0 else 0.0,
        "price_start": price_start,
        "price_end": price_end,
        "price_chg_pct": round(price_chg, 4) if price_chg is not None else None,
        "trades": len(swaps or []),
    }
    _FLOW_CACHE[cache_key] = result
    return result


def detect_silent(flow: dict | None, holders: dict | None = None,
                  *, net_min: float | None = None,
                  acc_wallets_min: int | None = None,
                  price_max: float | None = None,
                  bot_share_max: float | None = None) -> dict:
    """Deteksi silent accumulation 12 jam: net-beli, harga belum bergerak.

    Tidak ada sinyal / alert — hanya klasifikasi deskriptif untuk tabel.
    """
    flow = flow or {}
    net = _float(flow.get("net_usd"))
    acc = _int(flow.get("accumulators"))
    price_chg = flow.get("price_chg_pct")
    bot_share = _float(flow.get("bot_share"))
    net_min = float(net_min if net_min is not None else SILENT_NET_USD_MIN)
    acc_min = int(acc_wallets_min or SILENT_ACC_WALLETS_MIN)
    price_max = float(price_max if price_max is not None
                      else SILENT_PRICE_CHG_MAX)
    bot_max = float(bot_share_max if bot_share_max is not None
                    else SILENT_BOT_SHARE_MAX)

    price_ok = price_chg is None or abs(_float(price_chg)) <= price_max
    checks = {
        "net_positive": net >= net_min,
        "wallets_accumulating": acc >= acc_min,
        "price_silent": price_ok,
        "bot_share_low": bot_share <= bot_max,
    }
    silent = all(checks.values())
    if silent:
        strength = ("kuat" if (net >= net_min * 10 and acc >= acc_min * 3)
                    else "sedang" if (net >= net_min * 3 and acc >= acc_min * 2)
                    else "lemah")
        reason = (f"net +${net:,.0f} dari {acc} wallet · harga "
                  f"{_float(price_chg):+.1f}% / 12j · bot "
                  f"{bot_share * 100:.0f}%")
    else:
        strength = "tidak"
        reason = "net-belum-memenuhi"
    return {
        "silent": bool(silent),
        "strength": strength,
        "reason": reason,
        "checks": checks,
        "net_usd": net,
        "accumulators": acc,
        "price_chg_pct": price_chg,
        "bot_share": round(bot_share, 4),
    }


def analyze_token(ca: str, symbol: str = "?", market_cap: float = 0.0,
                  *, dust_limit: float | None = None,
                  max_wallets: int | None = None,
                  max_trade_pages: int | None = None,
                  fetch_market: bool = True,
                  timeout: int = 20) -> dict:
    """Analisis lengkap satu token: holder (real vs dust) + flow 12 jam.

    Dipakai langsung oleh scan Trending/Degen dan cron watchlist.
    """
    ca = str(ca or "").strip()
    dust_limit = float(DUST_LIMIT_USD if dust_limit is None else dust_limit)
    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)
    max_trade_pages = int(max_trade_pages or DEFAULT_MAX_TRADE_PAGES)
    market = {}
    if fetch_market:
        try:
            market = get_market(ca) or {}
        except Exception:
            market = {}
    mc = float(market_cap or market.get("marketcap") or 0)
    price = float(market.get("price_usd") or 0)

    snapshot = fetch_holders(ca, max_wallets=max_wallets, timeout=timeout)
    flow = fetch_12h_flow(ca, max_pages=max_trade_pages)
    holder_stats = classify_holders(snapshot, mc, dust_limit=dust_limit)
    silent = detect_silent(flow, holder_stats)
    return {
        "ca": ca,
        "symbol": str(symbol or market.get("symbol") or "?"),
        "marketcap": mc,
        "price": price,
        "analyzed_at": int(time.time()),
        "holders": holder_stats,
        "flow": flow,
        "silent": silent,
    }


def enrich_rows(rows: list[dict], *, dust_limit: float | None = None,
                max_wallets: int | None = None,
                max_trade_pages: int | None = None,
                workers: int = 6,
                progress=None) -> list[dict]:
    """Perkaya daftar listing (trending/degen) dengan analisis holder+12j.

    ``progress`` opsional: callable ``(index, total, label)``.
    Setiap baris gagal analisis tetap tampil dengan ``analysis=None``.
    """
    out = list(rows or ())
    if not out:
        return out
    total = len(out)
    workers = max(1, min(int(workers), 8))

    def _job(idx_row):
        idx, row = idx_row
        try:
            analysis = analyze_token(
                row.get("ca") or "", row.get("symbol") or "?",
                float(row.get("mc") or 0),
                dust_limit=dust_limit, max_wallets=max_wallets,
                max_trade_pages=max_trade_pages, fetch_market=False)
        except Exception:  # noqa: BLE001 - satu token gagal jangan batalkan
            analysis = None
        return idx, analysis

    results: dict[int, dict | None] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_job, item): item[0] for item in enumerate(out)}
        done = 0
        for future in as_completed(futures):
            idx, analysis = future.result()
            results[idx] = analysis
            done += 1
            if progress:
                try:
                    bar_label = (f"{done}/{total} · "
                                 f"{(out[idx] or {}).get('symbol') or '?'}")
                    progress(done, total, bar_label)
                except Exception:
                    pass
    for idx, analysis in results.items():
        out[idx]["analysis"] = analysis
    return out
