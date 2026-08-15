#!/usr/bin/env python3
"""Daily effort anomaly updater (00:00 WIB / 17:00 UTC).

Exposes ``refresh_single_token`` — the reusable per-token pipeline — so the
manual CVD fetch on ``pages/4_📊_CVD.py`` reuses exactly the same code path as
the cron instead of shelling out to a subprocess.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import (get_daily_candles_wib, get_helius_keys, get_market,
                  load_config)
from cvd import fetch_swaps, get_gmgn_fetch_status
from cvd_daily import (WIB, build_effort_rows,
                       fallback_candles_from_swaps)
from effort_detector import (RETENTION_DAYS, classify_effort,
                             load_daily_effort, merge_daily_effort,
                             rows_for_mint)
from signals import format_effort_alert, send_telegram, should_send_telegram
from watchlist import load_watchlist, update_local_meta

ALERT_SIGNALS = {
    "S1_PENYERAPAN", "S2_DUMP_DISTRIBUSI",
    "S3_DISTRIBUSI_KE_KUAT", "S4_PUMP_ASLI",
}


def _now_wib() -> datetime:
    return datetime.now(WIB)


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


def compute_lookback_window(now: datetime,
                            lookback_days: int) -> tuple[datetime, datetime]:
    """Return inclusive ``(start, end)`` WIB-midnight boundaries.

    ``end`` is today's 00:00 WIB (never includes the still-open current day)
    and ``start`` is ``lookback_days`` calendar days before it. Both are
    timezone-aware in Asia/Jakarta so the fetch always honours WIB boundaries.
    """
    now = (now or _now_wib()).astimezone(WIB)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=int(lookback_days))
    return start, end


def _pool_and_symbol(mint: str, meta: dict) -> tuple[str, str]:
    market = get_market(mint) or {}
    pools = market.get("pair_addresses") or []
    pool = str((meta or {}).get("pool") or (pools[0] if pools else ""))
    symbol = str((meta or {}).get("symbol")
                 or market.get("symbol") or "?")
    return pool, symbol


def _fetch_history_with_source(mint: str, pool: str, api_key: str,
                               now: datetime,
                               lookback_days: int = 4) -> tuple:
    """Fetch trades (GMGN first, Helius fallback) plus source metadata.

    Returns ``(swaps, source, fallback)`` where ``source`` is ``"gmgn"`` or
    ``"helius_fallback"`` and ``fallback`` is a boolean describing whether the
    Helius path was used because GMGN was incomplete/failed.
    """
    start, end = compute_lookback_window(now, lookback_days)
    swaps = fetch_swaps(
        api_key, pool, mint, stop_ts=int(start.timestamp()) - 1,
        from_ts=int(start.timestamp()), to_ts=int(end.timestamp()),
        max_pages=80, use_gmgn=True)[0]
    status = get_gmgn_fetch_status()
    gmgn_ok = bool(status.get("ok")) and bool(status.get("complete"))
    fallback = not gmgn_ok
    source = "gmgn" if not fallback else "helius_fallback"
    return swaps, source, fallback


def _fetch_history(mint: str, pool: str, api_key: str,
                   now: datetime, lookback_days: int = 4):
    """Backward-compatible trades-only fetch (kept for external callers)."""
    return _fetch_history_with_source(mint, pool, api_key, now,
                                      lookback_days)[0]


def refresh_single_token(mint: str, meta: dict | None = None, *,
                         now: datetime | None = None, api_key: str = "",
                         lookback_days: int = 4, log: list | None = None,
                         path: str | None = None,
                         on_progress=None) -> dict:
    """Run the complete effort pipeline for one token and return a structured
    result.

    This is the single reusable refresh path shared by the daily cron and the
    manual CVD fetch. It never sends Telegram alerts and never modifies the
    watchlist; it only writes ``daily_effort.json`` idempotently. The returned
    dict (including ``log``) is safe to store in Streamlit session state — it
    contains no credentials or API keys.

    ``on_progress`` is an optional callback invoked with each log entry so a
    UI can stream progress while the pipeline runs.
    """
    now = (now or _now_wib()).astimezone(WIB)
    meta = meta or {}
    requested = max(2, int(lookback_days))
    log_entries = log if log is not None else []
    started = time.monotonic()
    result = {
        "mint": str(mint), "symbol": str(meta.get("symbol") or "?"),
        "ok": False, "error": None, "requested_days": requested,
        "source": None, "fallback": False, "trades_count": 0,
        "rows_created": 0, "rows_updated": 0, "duration_ms": 0,
        "log": log_entries, "result": None,
    }

    def _stage(stage: str, message: str, *, ok: bool = True):
        entry = {"ts_wib": _now_wib().strftime("%Y-%m-%d %H:%M:%S"),
                 "stage": stage, "message": str(message), "ok": bool(ok)}
        log_entries.append(entry)
        if on_progress is not None:
            try:
                on_progress(entry)
            except Exception:
                pass
        return entry

    _stage("start", f"mulai fetch manual {requested} hari "
                    f"untuk ${result['symbol']}")
    try:
        # 1. market / pool lookup
        pool, symbol = _pool_and_symbol(mint, meta)
        result["symbol"] = symbol
        if not pool:
            raise RuntimeError("pair market tidak ditemukan")
        _stage("market_lookup", f"pool ditemukan ({pool[:8]}…)")

        # 2. fetch trades (GMGN -> Helius fallback handled internally)
        swaps, source, fallback = _fetch_history_with_source(
            mint, pool, api_key, now, lookback_days=requested)
        result["source"] = source
        result["fallback"] = bool(fallback)
        result["trades_count"] = len(swaps or [])
        _stage("fetch_trades",
               f"{len(swaps)} trades diterima (sumber: {source}"
               f"{', fallback Helius' if fallback else ''})")

        # 3. daily candles (market candles merged over trade-price fallback)
        market_candles = get_daily_candles_wib(
            pool, limit_days=max(7, requested + 1))
        trade_candles = fallback_candles_from_swaps(swaps)
        by_date = {row["date"]: row for row in trade_candles}
        by_date.update({row["date"]: row for row in market_candles})
        candles = sorted(by_date.values(), key=lambda row: row["date"])
        _stage("fetch_candle",
               f"{len(candles)} candle harian disiapkan "
               f"(market={len(market_candles)}, trades={len(trade_candles)})")

        # 4. aggregate daily CVD -> effort rows (excludes open WIB day)
        fresh = build_effort_rows(mint, swaps, candles, now=now)
        _stage("aggregate",
               f"{len(fresh)} daily row dibangun dari {len(swaps)} trades")

        # 5. persist idempotently (respects retention per mint)
        existing = load_daily_effort(path)
        before_keys = {(row.get("mint"), row.get("date"))
                       for row in existing if row.get("mint") == mint}
        merged = merge_daily_effort(fresh, path=path,
                                    retention_days=RETENTION_DAYS)
        fresh_keys = {(row.get("mint"), row.get("date")) for row in fresh}
        created = len(fresh_keys - before_keys)
        result["rows_created"] = created
        result["rows_updated"] = len(fresh) - created
        _stage("persist", f"{created} dibuat, "
                          f"{result['rows_updated']} di-update (idempoten)")

        # 6. classify and finish
        history = rows_for_mint(merged, mint)
        effort = classify_effort(history, mint)
        result["result"] = effort
        _stage("classify", f"sinyal={effort.get('signal')} "
                           f"baseline={effort.get('baseline_status')}")
        result["ok"] = True
        _stage("success", "fetch manual berhasil")
    except Exception as exc:  # noqa: BLE001 - surface a clean structured error
        result["ok"] = False
        result["error"] = _redact(str(exc), api_key)
        _stage("error", result["error"], ok=False)
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def run_daily(watchlist: dict, *, now=None, api_key: str = "",
              send_alerts: bool = True) -> list[dict]:
    """Refresh every token, persist idempotently, and alert only S1-S4."""
    now = (now or _now_wib()).astimezone(WIB)
    existing = load_daily_effort()
    existing_keys = {(row.get("mint"), row.get("date")) for row in existing}
    results = []

    for mint, meta in (watchlist or {}).items():
        symbol = str((meta or {}).get("symbol") or "?")
        res = refresh_single_token(
            mint, meta or {}, now=now, api_key=api_key, lookback_days=4)
        results.append(res)
        if not res["ok"]:
            print(f"{symbol}: update failed: {res['error']}")
            continue
        result = res["result"]
        history = rows_for_mint(load_daily_effort(), mint)
        newest_key = (mint, result.get("date"))
        should_alert = (should_send_telegram(result)
                        and newest_key not in existing_keys)
        sent = bool(send_alerts and should_alert
                    and send_telegram(format_effort_alert(symbol, result)))
        res["alert_sent"] = sent
        update_local_meta(mint, {
            "symbol": symbol,
            "effort_ts": int(now.timestamp()),
            "effort_date": result.get("date"),
            "effort_signal": result.get("signal"),
            "effort_bias": result.get("bias"),
            "effort_ratio": result.get("ratio_N"),
            "effort_previous_ratio": result.get("ratio_N_minus_1"),
            "effort_multiplier": result.get("multiplier"),
            "effort_divergence": result.get("flag_divergence"),
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
          f"time={_now_wib().isoformat()}")
    if watchlist:
        run_daily(watchlist, api_key=keys[0] if keys else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
