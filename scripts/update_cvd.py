#!/usr/bin/env python3
"""Daily effort anomaly updater (market-day / 00:00 UTC).

Exposes ``refresh_single_token`` — the reusable per-token pipeline — so the
manual CVD fetch on ``pages/4_📊_CVD.py`` reuses exactly the same code path as
the cron instead of shelling out to a subprocess.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date as _date
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import (get_daily_candles, get_helius_keys, get_market,
                  load_config)
from cvd import fetch_swaps
from cvd_daily import (MARKET_TZ, build_effort_rows,
                       fallback_candles_from_swaps)
from daily_store import (DAILY_EFFORT_PATH, STORAGE_WINDOW_DAYS,
                           load_daily_effort, merge_daily_effort,
                           rows_for_mint)
from watchlist import load_watchlist, update_local_meta


def _now_market() -> datetime:
    return datetime.now(MARKET_TZ)


def _redact(message, secret: str) -> str:
    """Remove API keys/credentials from an error message before logging."""
    message = str(message or "")
    secret = str(secret or "")
    if secret and secret in message:
        message = message.replace(secret, "[REDACTED]")
    # Generic scrub for any api-key=... token that might leak in an exception.
    parts = message.split("api-key=")
    if len(parts) > 1:
        message = parts[0] + "api-key=[REDACTED]"
    return message


def _as_market_midnight(value) -> datetime:
    """Return a timezone-aware market-day (UTC) midnight datetime."""
    if isinstance(value, datetime):
        value = value.astimezone(MARKET_TZ).date()
    elif isinstance(value, _date):
        value = value
    else:
        value = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    return datetime(value.year, value.month, value.day, tzinfo=MARKET_TZ)


def compute_lookback_window(now: datetime,
                            lookback_days: int) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` market-day (UTC) boundaries.

    ``end`` is today's 00:00 UTC (never includes the still-open current day)
    and ``start`` is ``lookback_days`` calendar days before it. The returned
    window is [start, end), i.e. ``end`` is exclusive. Both are timezone-aware
    in UTC so the fetch always honours the crypto-market day boundary.
    """
    now = (now or _now_market()).astimezone(MARKET_TZ)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=int(lookback_days))
    return start, end


def compute_date_window(start_date, end_date, now: datetime | None = None,
                        max_span_days: int = 30) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` market-day (UTC) boundaries.

    ``start_date``/``end_date`` are inclusive calendar dates (ISO strings or
    ``datetime.date``). ``end`` is capped at yesterday so the still-open
    market day is never fetched, and the span is clamped to ``max_span_days``.
    The returned window is [start, end) with ``end`` exclusive.
    """
    now = (now or _now_market()).astimezone(MARKET_TZ)
    today = now.date()
    latest = today - timedelta(days=1)  # never include the open day
    start_d = min(_as_date(start_date), latest)
    end_d = min(_as_date(end_date), latest)
    if start_d > end_d:
        start_d, end_d = end_d, start_d
    max_span = max(2, int(max_span_days))
    if (end_d - start_d).days + 1 > max_span:
        start_d = end_d - timedelta(days=max_span - 1)
    return _as_market_midnight(start_d), _as_market_midnight(end_d) + timedelta(days=1)


def _as_date(value) -> _date:
    if isinstance(value, datetime):
        return value.astimezone(MARKET_TZ).date()
    if isinstance(value, _date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _pool_and_symbol(mint: str, meta: dict, market: dict | None = None) -> tuple[str, str]:
    market = market if market is not None else (get_market(mint) or {})
    pools = market.get("pair_addresses") or []
    pool = str((meta or {}).get("pool") or (pools[0] if pools else ""))
    symbol = str((meta or {}).get("symbol")
                 or market.get("symbol") or "?")
    return pool, symbol


def _token_supply(market: dict):
    """Perkiraan total supply = marketcap / harga sekarang.

    Dipakai untuk ``marketcap_close`` historis (close × supply) pada gerbang
    anti wash-trade. Return ``None`` bila data market tidak cukup — detektor
    lalu melewatkan gerbang MC ("bila MC tersedia").
    """
    try:
        marketcap = float((market or {}).get("marketcap") or 0)
        price = float((market or {}).get("price_usd") or 0)
    except (TypeError, ValueError):
        return None
    if marketcap <= 0 or price <= 0:
        return None
    return marketcap / price


def _fetch_history_with_source(mint: str, pool: str, api_key: str,
                               start: datetime,
                               end: datetime) -> tuple:
    """Fetch trades (Helius first, GMGN fallback) for ``[start, end)``.

    ``start``/``end`` are timezone-aware market-day (UTC) datetimes (``end`` exclusive).
    Returns ``(swaps, source, fallback)`` where ``source`` is ``"helius"``,
    ``"gmgn_fallback"``, or ``"gmgn"`` (bila Helius key/pool tidak tersedia)
    and ``fallback`` is True bila jalur GMGN dipakai karena Helius kosong/
    gagal.
    """
    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
    if pool and api_key:
        try:
            swaps = fetch_swaps(
                api_key, pool, mint, stop_ts=start_ts - 1,
                from_ts=start_ts, to_ts=end_ts,
                max_pages=80)[0] or []
        except Exception:  # noqa: BLE001 - lanjut ke fallback GMGN
            swaps = []
        if swaps:
            return swaps, "helius", False
        swaps = fetch_swaps(
            api_key, pool, mint, stop_ts=start_ts - 1,
            from_ts=start_ts, to_ts=end_ts,
            max_pages=80, use_gmgn=True)[0]
        return swaps, "gmgn_fallback", True
    swaps = fetch_swaps(
        api_key, pool, mint, stop_ts=start_ts - 1,
        from_ts=start_ts, to_ts=end_ts,
        max_pages=80, use_gmgn=True)[0]
    return swaps, "gmgn", False


def _fetch_history(mint: str, pool: str, api_key: str,
                   now: datetime, lookback_days: int = 4):
    """Backward-compatible trades-only fetch (kept for external callers)."""
    start, end = compute_lookback_window(now, lookback_days)
    return _fetch_history_with_source(mint, pool, api_key, start, end)[0]


def _resolve_window(now: datetime, lookback_days: int = 4,
                    start_date=None,
                    end_date=None) -> tuple[datetime, datetime, int]:
    """Return ``(start, end, span_days)`` for the requested fetch.

    When ``start_date``/``end_date`` are given they define an inclusive market-day
    calendar window; otherwise ``lookback_days`` defines the window relative to
    ``now``. The returned window is ``[start, end)`` (``end`` exclusive) and
    ``span_days`` is the number of completed calendar days it covers.
    """
    if start_date is not None and end_date is not None:
        start, end = compute_date_window(start_date, end_date, now=now)
    else:
        start, end = compute_lookback_window(now, lookback_days)
    span = int((end - start).total_seconds() // 86400)
    return start, end, span


def refresh_single_token(mint: str, meta: dict | None = None, *,
                         now: datetime | None = None, api_key: str = "",
                         lookback_days: int = 4, start_date=None,
                         end_date=None, log: list | None = None,
                         path: str | None = None,
                         on_progress=None) -> dict:
    """Run the complete effort pipeline for one token and return a structured
    result.

    This is the single reusable refresh path shared by the daily cron and the
    manual CVD fetch. It never modifies the watchlist; it only writes
    ``daily_effort.json`` idempotently. The returned dict (including ``log``)
    is safe to store in Streamlit session state — it contains no credentials
    or API keys.

    ``on_progress`` is an optional callback invoked with each log entry so a
    UI can stream progress while the pipeline runs.
    """
    now = (now or _now_market()).astimezone(MARKET_TZ)
    meta = meta or {}
    path = path or DAILY_EFFORT_PATH
    start, end, span_days = _resolve_window(
        now, lookback_days=lookback_days, start_date=start_date,
        end_date=end_date)
    requested = max(2, span_days)
    log_entries = log if log is not None else []
    started = time.monotonic()
    result = {
        "mint": str(mint), "symbol": str(meta.get("symbol") or "?"),
        "ok": False, "error": None, "requested_days": requested,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "source": None, "fallback": False, "trades_count": 0,
        "rows_created": 0, "rows_updated": 0, "duration_ms": 0,
        "log": log_entries, "result": None,
    }

    def _stage(stage: str, message: str, *, ok: bool = True):
        entry = {"ts_market": _now_market().strftime("%Y-%m-%d %H:%M:%S"),
                 "stage": stage, "message": str(message), "ok": bool(ok)}
        log_entries.append(entry)
        if on_progress is not None:
            try:
                on_progress(entry)
            except Exception:
                pass
        return entry

    _stage("start", f"mulai fetch manual {result['start_date']} s/d "
                    f"{result['end_date']} ({requested} hari) "
                    f"untuk ${result['symbol']}")
    try:
        # 1. market / pool lookup (+ supply untuk marketcap_close historis)
        market = get_market(mint) or {}
        pool, symbol = _pool_and_symbol(mint, meta, market=market)
        supply = _token_supply(market)
        result["symbol"] = symbol
        if not pool:
            raise RuntimeError("pair market tidak ditemukan")
        _stage("market_lookup", f"pool ditemukan ({pool[:8]}…)")

        # 2. fetch trades (Helius -> GMGN fallback handled internally)
        swaps, source, fallback = _fetch_history_with_source(
            mint, pool, api_key, start, end)
        result["source"] = source
        result["fallback"] = bool(fallback)
        result["trades_count"] = len(swaps or [])
        _stage("fetch_trades",
               f"{len(swaps)} trades diterima (sumber: {source}"
               f"{', fallback GMGN' if fallback else ''})")

        # 3. daily candles (market candles merged over trade-price fallback)
        market_candles = get_daily_candles(
            pool, limit_days=max(7, span_days + 1))
        trade_candles = fallback_candles_from_swaps(swaps)
        by_date = {row["date"]: row for row in trade_candles}
        by_date.update({row["date"]: row for row in market_candles})
        candles = sorted(by_date.values(), key=lambda row: row["date"])
        _stage("fetch_candle",
               f"{len(candles)} candle harian disiapkan "
               f"(market={len(market_candles)}, trades={len(trade_candles)})")

        # 4. aggregate daily CVD -> effort rows (excludes open market day)
        fresh = build_effort_rows(mint, swaps, candles, now=now,
                                  supply=supply)
        _stage("aggregate",
               f"{len(fresh)} daily row dibangun dari {len(swaps)} trades")

        # 5. persist idempotently (respects storage window per mint)
        existing = load_daily_effort(path)
        before_keys = {(row.get("mint"), row.get("date"))
                       for row in existing if row.get("mint") == mint}
        merged = merge_daily_effort(fresh, path=path,
                                    window_days=STORAGE_WINDOW_DAYS)
        fresh_keys = {(row.get("mint"), row.get("date")) for row in fresh}
        created = len(fresh_keys - before_keys)
        result["rows_created"] = created
        result["rows_updated"] = len(fresh) - created
        _stage("persist", f"{created} dibuat, "
                          f"{result['rows_updated']} di-update (idempoten)")

        # 6. finish (tanpa klasifikasi sinyal)
        history = rows_for_mint(merged, mint)
        result["result"] = history[-1] if history else None
        _stage("finish", f"{len(history)} baris harian tersimpan")
        result["ok"] = True
        _stage("success", "fetch manual berhasil")
    except Exception as exc:  # noqa: BLE001 - surface a clean structured error
        result["ok"] = False
        result["error"] = _redact(str(exc), api_key)
        _stage("error", result["error"], ok=False)
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def run_daily(watchlist: dict, *, now=None, api_key: str = "") -> list[dict]:
    """Refresh setiap token dan simpan idempoten (tanpa sinyal)."""
    now = (now or _now_market()).astimezone(MARKET_TZ)
    results = []

    for mint, meta in (watchlist or {}).items():
        symbol = str((meta or {}).get("symbol") or "?")
        res = refresh_single_token(
            mint, meta or {}, now=now, api_key=api_key, lookback_days=4)
        results.append(res)
        if not res["ok"]:
            print(f"{symbol}: update failed: {res['error']}")
            continue
        result = res["result"] or {}
        update_local_meta(mint, {
            "symbol": symbol,
            "effort_ts": int(now.timestamp()),
            "effort_date": result.get("date"),
            "effort_cvd": result.get("cvd_delta"),
            "effort_volume_usd": result.get("volume_usd"),
        })
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default="daily",
                        choices=("daily", "auto"))
    args = parser.parse_args(argv)
    config = load_config()
    keys = get_helius_keys(config=config)
    watchlist = load_watchlist()
    print(f"Effort updater mode={args.mode}; tokens={len(watchlist)}; "
          f"time={_now_market().isoformat()}")
    if watchlist:
        run_daily(watchlist, api_key=keys[0] if keys else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
