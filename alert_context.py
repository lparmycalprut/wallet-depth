# -*- coding: utf-8 -*-
"""Konteks pasar (volume + harga + volatilitas) untuk konfirmasi alert dust.

Modul ini menjawab satu pertanyaan: *apakah perubahan dust barusan disertai
perdagangan yang nyata?* Hasilnya sebuah dict konteks yang dikonsumsi
``telegram_alerts.volume_verdict`` — aturan alert tetap murni dan bebas
jaringan.

Dipanggil **lazy** oleh cron: hanya token yang dust-nya sudah melewati ambang
yang menarik data ini, jadi scan 1 jam yang tenang tidak menambah satu pun
request.

Urutan sumber (paling akurat lebih dulu):

1. **Candle hourly GeckoTerminal** (168 jam, satu request per token) →
   volume 4 jam sebenarnya, rata-rata volume per window 4 jam selama 7 hari,
   perubahan harga 4 jam, dan metrik volatilitas
   (``holder_history.calculate_volatility_metrics``).
2. **DexScreener** — sudah diambil ``holder_analysis.analyze_token`` dan
   diteruskan lewat ``analysis["market"]``, jadi *tanpa request tambahan*:
   ``volume.h6/h24`` (diskalakan ke window 4 jam), ``priceChange.h6``,
   ``txns.h6.buys/sells``.
3. **``daily_effort.json``** (cron CVD) → rata-rata volume USD harian 7 hari.

Setiap kegagalan bersifat *degraded*, bukan fatal: field yang tidak ada
dilaporkan lewat ``missing`` sehingga alert tetap dikirim dengan tanda
"TIDAK TERVERIFIKASI" alih-alih hilang senyap.

Satuan penting: ``avg_volume_7d`` selalu **rata-rata volume per window 4 jam**
selama 7 hari (bukan total harian), supaya sebanding dengan ``volume_4h``.
"""
from __future__ import annotations

import math
import sys
import time

VOLUME_WINDOW_HOURS = 4          # window yang dibandingkan dengan dust 4 jam
BASELINE_DAYS = 7                # rata-rata 7 hari
BASELINE_HOURS = BASELINE_DAYS * 24
MIN_BASELINE_HOURS = 24          # coverage minimum agar baseline tidak bias
HOURS_PER_DAY = 24
# DexScreener tidak punya window 4 jam; h6 (6 jam) yang paling dekat.
DEX_VOLUME_WINDOW = "h6"
DEX_PRICE_WINDOW = "h6"
DEX_PRESSURE_WINDOWS = ("h6", "h1", "h24")


def _num(value, default=None):
    """Finite float atau *default* (None/NaN/inf/bool/teks → default)."""
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _int(value, default=0) -> int:
    number = _num(value, None)
    return int(number) if number is not None else int(default)


def _round(value, digits=4):
    number = _num(value, None)
    return None if number is None else round(number, digits)


def _market_dict(analysis=None, market=None) -> dict:
    """Ambil data DexScreener: argumen → ``analysis["market"]`` → kosong."""
    if isinstance(market, dict) and market:
        return market
    if isinstance(analysis, dict):
        embedded = analysis.get("market")
        if isinstance(embedded, dict):
            return embedded
    return {}


def volume_from_candles(hourly, *, now=None,
                        window_hours: int = VOLUME_WINDOW_HOURS,
                        days: int = BASELINE_DAYS,
                        min_baseline_hours: int = MIN_BASELINE_HOURS) -> dict:
    """Volume + perubahan harga dari candle hourly (sumber paling akurat).

    Return ``{}`` bila candle tidak usable. ``avg_volume_7d`` hanya dihitung
    bila coverage-nya ≥ ``min_baseline_hours`` jam; pool berumur 3 jam tidak
    boleh menyamar sebagai baseline 7 hari (rasio akan meledak dan meloloskan
    sinyal apa pun).
    """
    rows = []
    for row in hourly or []:
        if not isinstance(row, dict):
            continue
        ts = _num(row.get("ts"), None)
        if ts is None or ts <= 0:
            continue
        rows.append((int(ts), max(0.0, _num(row.get("volume_usd"), 0.0) or 0.0),
                     _num(row.get("close"), None), _num(row.get("open"), None)))
    if not rows:
        return {}
    rows.sort(key=lambda item: item[0])
    window = max(1, int(window_hours))
    anchor = _int(now, 0) or rows[-1][0]
    window_from = anchor - window * 3600
    baseline_from = anchor - max(window, int(days)) * 24 * 3600

    in_window = [row for row in rows if window_from < row[0] <= anchor]
    in_baseline = [row for row in rows if baseline_from < row[0] <= anchor]
    volume_window = sum(row[1] for row in in_window)
    baseline_hours = len(in_baseline)
    out = {
        "candles": len(rows),
        "candles_in_window": len(in_window),
        "baseline_hours": baseline_hours,
        "volume_4h": _round(volume_window, 2) if in_window else None,
        "avg_volume_7d": None,
        "avg_volume_daily_7d": None,
        "price_change_pct": None,
        "volume_source": "geckoterminal_hourly",
    }
    if baseline_hours >= max(1, int(min_baseline_hours)):
        total = sum(row[1] for row in in_baseline)
        windows = baseline_hours / window
        out["avg_volume_7d"] = _round(total / windows, 2) if windows > 0 else None
        out["avg_volume_daily_7d"] = _round(total / (baseline_hours / HOURS_PER_DAY), 2)
    closes = [row for row in in_window if row[2] is not None and row[2] > 0]
    if closes:
        first_open = next((row[3] for row in closes
                           if row[3] is not None and row[3] > 0), None)
        reference = first_open or closes[0][2]
        if reference and reference > 0:
            out["price_change_pct"] = _round(
                (closes[-1][2] - reference) / reference * 100.0, 4)
            out["price_change_window"] = f"candles_{window}h"
    return out


def volume_from_dexscreener(market: dict, *,
                            window_hours: int = VOLUME_WINDOW_HOURS) -> dict:
    """Perkiraan volume/harga dari DexScreener (tanpa request tambahan).

    DexScreener hanya menyediakan m5/h1/h6/h24, jadi volume 4 jam di-skala
    dari ``h6`` dan baseline per-window dari ``h24`` (proxy 1 hari, bukan
    rata-rata 7 hari sebenarnya — ditandai lewat ``volume_source``/``notes``
    supaya angka di pesan Telegram tidak mengklaim presisi yang tidak ada).
    """
    market = market if isinstance(market, dict) else {}
    volume = market.get("volume") if isinstance(market.get("volume"), dict) else {}
    change = (market.get("price_change") if isinstance(
        market.get("price_change"), dict) else {})
    window = max(1, int(window_hours))
    out: dict = {"notes": []}

    h6 = _num(volume.get("h6"), None)
    h1 = _num(volume.get("h1"), None)
    h24 = _num(volume.get("h24"), None)
    if h6 is not None:
        out["volume_4h"] = _round(h6 * window / 6.0, 2)
        out["volume_source"] = "dexscreener_h6_scaled"
    elif h1 is not None:
        out["volume_4h"] = _round(h1 * window, 2)
        out["volume_source"] = "dexscreener_h1_scaled"
    elif h24 is not None:
        out["volume_4h"] = _round(h24 * window / HOURS_PER_DAY, 2)
        out["volume_source"] = "dexscreener_h24_scaled"
    if h24 is not None and h24 > 0:
        out["avg_volume_7d"] = _round(h24 / (HOURS_PER_DAY / window), 2)
        out["avg_volume_daily_7d"] = _round(h24, 2)
        out.setdefault("volume_source", "dexscreener_h24")
        out["notes"].append("baseline volume dari h24 DexScreener "
                            "(proxy 1 hari, bukan 7 hari)")
    for key in (DEX_PRICE_WINDOW, "h1", "h24"):
        value = _num(change.get(key), None)
        if value is not None:
            out["price_change_pct"] = _round(value, 4)
            out["price_change_window"] = f"dexscreener_{key}"
            break
    out["price"] = _num(market.get("price_usd"), None)
    return out


def pressure_from_txns(market: dict) -> dict:
    """Buy/sell pressure dari jumlah transaksi DexScreener (window terdekat)."""
    market = market if isinstance(market, dict) else {}
    txns = market.get("txns") if isinstance(market.get("txns"), dict) else {}
    for window in DEX_PRESSURE_WINDOWS:
        bucket = txns.get(window)
        if not isinstance(bucket, dict):
            continue
        buys = _num(bucket.get("buys"), None)
        sells = _num(bucket.get("sells"), None)
        if buys is None and sells is None:
            continue
        return {"buy_pressure": buys if buys is not None else 0.0,
                "sell_pressure": sells if sells is not None else 0.0,
                "pressure_window": f"dexscreener_txns_{window}",
                "pressure_unit": "tx_count"}
    return {}


def pressure_from_daily_rows(rows) -> dict:
    """Buy/sell USD dari baris ``daily_effort.json`` (cron CVD), hari terakhir."""
    latest = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if latest is None or str(row.get("date") or "") > str(latest.get("date") or ""):
            latest = row
    if not isinstance(latest, dict):
        return {}
    buys = _num(latest.get("buy_usd"), None)
    sells = _num(latest.get("sell_usd"), None)
    if buys is None and sells is None:
        return {}
    return {"buy_pressure": buys if buys is not None else 0.0,
            "sell_pressure": sells if sells is not None else 0.0,
            "pressure_window": f"daily_effort:{latest.get('date') or '?'}",
            "pressure_unit": "usd"}


def baseline_from_daily_rows(rows, *, days: int = BASELINE_DAYS,
                             window_hours: int = VOLUME_WINDOW_HOURS) -> dict:
    """Rata-rata volume per window 4 jam dari ``volume_usd`` harian (7 hari)."""
    volumes = []
    for row in sorted((rows or []), key=lambda item: str(
            (item or {}).get("date") or ""))[-max(1, int(days)):]:
        if not isinstance(row, dict):
            continue
        value = _num(row.get("volume_usd"), None)
        if value is not None and value > 0:
            volumes.append(value)
    if not volumes:
        return {}
    daily = sum(volumes) / len(volumes)
    windows = max(1, HOURS_PER_DAY / max(1, int(window_hours)))
    return {"avg_volume_7d": _round(daily / windows, 2),
            "avg_volume_daily_7d": _round(daily, 2),
            "baseline_days": len(volumes),
            "volume_source": "daily_effort_7d"}


def build_market_context(mint: str, analysis: dict | None = None, *,
                         market: dict | None = None, hourly=None,
                         daily_rows=None, now=None, fetch: bool = True,
                         window_hours: int = VOLUME_WINDOW_HOURS,
                         days: int = BASELINE_DAYS,
                         hourly_fetcher=None,
                         market_loader=None) -> dict:
    """Susun konteks volume/harga/volatilitas untuk satu token.

    Tidak pernah melempar: sumber yang gagal ditandai di ``missing``/``notes``.
    ``fetch=False`` mematikan semua jaringan (dipakai test dan jalur offline) —
    hanya data yang sudah ada di ``analysis``/``market``/``hourly`` yang dipakai.
    """
    started = time.time()
    anchor = _int(now, 0) or int(time.time())
    market_data = _market_dict(analysis, market)
    if not market_data and fetch and callable(market_loader):
        try:
            loaded = market_loader(str(mint or "").strip())
            market_data = loaded if isinstance(loaded, dict) else {}
        except Exception as exc:  # noqa: BLE001 - konteks tidak boleh fatal
            print(f"WARN: market {_address(mint)[:8]} gagal diambil: {exc}",
                  file=sys.stderr)
            market_data = {}

    hourly_rows = list(hourly or [])
    if not hourly_rows and fetch:
        fetcher = hourly_fetcher
        if fetcher is None:
            try:
                from core import get_hourly_candles as fetcher  # noqa: F401
            except Exception:  # pragma: no cover - core selalu tersedia
                fetcher = None
        pair_addresses = [str(pair or "").strip() for pair in
                          (market_data.get("pair_addresses") or []) if pair]
        if callable(fetcher):
            for pair in pair_addresses[:2]:
                try:
                    rows = fetcher(pair, BASELINE_HOURS)
                except Exception as exc:  # noqa: BLE001
                    print(f"WARN: candle {_address(mint)[:8]} gagal: {exc}",
                          file=sys.stderr)
                    rows = None
                if rows:
                    hourly_rows = list(rows)
                    break

    context = {
        "mint": str(mint or "").strip(),
        "ts": anchor,
        "window_hours": int(window_hours),
        "baseline_days": int(days),
        "volume_4h": None,
        "avg_volume_7d": None,
        "avg_volume_daily_7d": None,
        "volume_ratio": None,
        "price": _num((analysis or {}).get("price"), None),
        "price_change_pct": None,
        "price_change_window": "",
        "buy_pressure": None,
        "sell_pressure": None,
        "pressure_window": "",
        "pressure_unit": "",
        "volatility": None,
        "volume_source": "",
        "candles": 0,
        "notes": [],
        "missing": [],
    }

    # 1) DexScreener dulu (selalu ada, gratis) sebagai lantai.
    dex = volume_from_dexscreener(market_data, window_hours=window_hours)
    for key in ("volume_4h", "avg_volume_7d", "avg_volume_daily_7d",
                "price_change_pct", "price_change_window", "volume_source"):
        if dex.get(key) not in (None, ""):
            context[key] = dex[key]
    if context["price"] is None:
        context["price"] = dex.get("price")
    context["notes"].extend(dex.get("notes") or [])
    context.update(pressure_from_txns(market_data))

    # 2) Rata-rata 7 hari dari daily_effort.json (lebih jujur dari proxy h24).
    rows = daily_rows
    if rows is None and fetch:
        try:
            from daily_store import load_daily_effort, rows_for_mint
            rows = rows_for_mint(load_daily_effort(), str(mint or "").strip())
        except Exception:  # noqa: BLE001 - file lokal opsional
            rows = []
    baseline = baseline_from_daily_rows(rows, days=days,
                                        window_hours=window_hours)
    if baseline.get("avg_volume_7d"):
        context.update(baseline)
        context["notes"] = [note for note in context["notes"]
                            if "proxy 1 hari" not in note]
    pressure_rows = pressure_from_daily_rows(rows)
    if pressure_rows.get("buy_pressure") is not None:
        # USD lebih bermakna daripada jumlah transaksi bila tersedia.
        context.update(pressure_rows)

    # 3) Candle hourly menimpa semuanya bila berhasil diambil.
    candles = volume_from_candles(hourly_rows, now=anchor,
                                  window_hours=window_hours, days=days)
    if candles:
        for key in ("volume_4h", "avg_volume_7d", "avg_volume_daily_7d",
                    "price_change_pct", "price_change_window",
                    "volume_source", "candles", "candles_in_window",
                    "baseline_hours"):
            if candles.get(key) not in (None, ""):
                context[key] = candles[key]
        if candles.get("avg_volume_7d") is None:
            context["notes"].append(
                f"coverage candle {candles.get('baseline_hours') or 0} jam "
                f"< {MIN_BASELINE_HOURS} jam → baseline 7 hari tidak dipakai")
    volatility = _volatility(hourly_rows, now=anchor,
                             window_hours=window_hours)
    if volatility:
        context["volatility"] = volatility
        if volatility.get("price_change_4h_pct") is not None:
            context["price_change_pct"] = volatility["price_change_4h_pct"]
            context["price_change_window"] = f"candles_{window_hours}h"
        if context["volume_4h"] is None:
            context["volume_4h"] = volatility.get("volume_4h")

    volume = _num(context.get("volume_4h"), None)
    baseline_value = _num(context.get("avg_volume_7d"), None)
    if volume is not None and baseline_value:
        context["volume_ratio"] = round(volume / baseline_value, 4)
    for key in ("volume_4h", "avg_volume_7d", "price_change_pct"):
        if context.get(key) is None:
            context["missing"].append(key)
    if context.get("buy_pressure") is None or context.get("sell_pressure") is None:
        context["missing"].append("buy/sell_pressure")
    context["available"] = not ({"volume_4h", "avg_volume_7d",
                                 "price_change_pct"} & set(context["missing"]))
    if not context["available"]:
        context["reason"] = ("data pasar tidak lengkap: "
                             + ", ".join(context["missing"]))
    context["fetch_ms"] = int((time.time() - started) * 1000)
    return context


def _volatility(hourly, *, now=None, window_hours: int = VOLUME_WINDOW_HOURS):
    """Metrik volatilitas dari candle hourly (None bila candle tidak ada)."""
    if not hourly:
        return None
    try:
        from holder_history import (VOLATILITY_HISTORY_HOURS,
                                    calculate_volatility_metrics)
        return calculate_volatility_metrics(
            hourly, now=now, window_hours=window_hours,
            history_hours=max(VOLATILITY_HISTORY_HOURS, window_hours * 4))
    except Exception as exc:  # noqa: BLE001 - volatilitas bersifat pelengkap
        print(f"WARN: volatilitas gagal dihitung: {exc}", file=sys.stderr)
        return None


def _address(value) -> str:
    return str(value or "").strip()


def compact_signal(context: dict | None) -> dict:
    """Salinan ringkas konteks untuk disimpan di ``holder_status.json``."""
    ctx = context if isinstance(context, dict) else {}
    volatility = ctx.get("volatility") if isinstance(ctx.get("volatility"),
                                                     dict) else {}
    return {
        "ts": _int(ctx.get("ts")),
        "volume_4h": _round(ctx.get("volume_4h"), 2),
        "avg_volume_7d": _round(ctx.get("avg_volume_7d"), 2),
        "volume_ratio_7d": _round(ctx.get("volume_ratio"), 4),
        "price_change_pct": _round(ctx.get("price_change_pct"), 4),
        "price_change_window": str(ctx.get("price_change_window") or ""),
        "buy_pressure": _round(ctx.get("buy_pressure"), 2),
        "sell_pressure": _round(ctx.get("sell_pressure"), 2),
        "volume_source": str(ctx.get("volume_source") or ""),
        "candles": _int(ctx.get("candles")),
        "available": bool(ctx.get("available")),
        "missing": [str(item) for item in (ctx.get("missing") or [])][:6],
        "price_stddev_4h": _round(volatility.get("price_stddev_4h"), 4),
        "price_range_4h": _round(volatility.get("price_range_4h"), 4),
        "intra_hour_volatility": _round(volatility.get("intra_hour_volatility"), 4),
        "intra_hour_volatility_max": _round(
            volatility.get("intra_hour_volatility_max"), 4),
        "high_volatility": bool(volatility.get("high_volatility")),
        "volatility_available": bool(volatility.get("available")),
    }


def market_context_provider(*, fetch: bool = True, cache: dict | None = None,
                            hourly_fetcher=None, market_loader=None,
                            daily_loader=None, now=None):
    """Pabrik ``provider(mint, analysis)`` dengan memo per token.

    ``cache`` dipakai bersama antar-token dalam satu run scan sehingga satu
    token hanya pernah menarik konteks satu kali, walau aturan baseline dan
    aturan 4 jam sama-sama menanyakannya. ``daily_loader`` dimuat sekali per
    run (file lokal) bila disediakan.
    """
    store = cache if isinstance(cache, dict) else {}
    loaded: dict = {}
    per_mint: dict = {}

    def _daily(mint: str):
        """Baris ``daily_effort`` untuk *mint*; file lokal dimuat sekali per run."""
        if daily_loader is None:
            return None
        if "rows" not in loaded:
            try:
                rows = daily_loader()
                loaded["rows"] = rows if isinstance(rows, list) else []
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: daily_effort gagal dimuat: {exc}", file=sys.stderr)
                loaded["rows"] = []
        if mint not in per_mint:
            try:
                from daily_store import rows_for_mint
                per_mint[mint] = rows_for_mint(loaded["rows"], mint)
            except Exception:  # noqa: BLE001
                per_mint[mint] = []
        return per_mint[mint]

    def provider(mint: str, analysis: dict | None = None) -> dict:
        key = _address(mint)
        if key in store and isinstance(store.get(key), dict):
            return store[key]
        context = build_market_context(
            key, analysis, fetch=fetch, now=now, hourly_fetcher=hourly_fetcher,
            market_loader=market_loader,
            daily_rows=_daily(key) if daily_loader is not None else None)
        store[key] = context
        return context

    provider.cache = store
    return provider
