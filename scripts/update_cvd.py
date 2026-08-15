#!/usr/bin/env python3
"""Daily effort anomaly updater (00:00 WIB / 17:00 UTC)."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import (get_daily_candles_wib, get_helius_keys, get_market,
                  load_config)
from cvd import fetch_swaps
from cvd_daily import (WIB, build_effort_rows,
                       fallback_candles_from_swaps)
from effort_detector import (classify_effort, load_daily_effort,
                             merge_daily_effort, rows_for_mint)
from signals import format_effort_alert, send_telegram, should_send_telegram
from watchlist import load_watchlist, update_local_meta

ALERT_SIGNALS = {
    "S1_PENYERAPAN", "S2_DUMP_DISTRIBUSI",
    "S3_DISTRIBUSI_KE_KUAT", "S4_PUMP_ASLI",
}


def _now_wib() -> datetime:
    return datetime.now(WIB)


def _pool_and_symbol(mint: str, meta: dict) -> tuple[str, str]:
    market = get_market(mint) or {}
    pools = market.get("pair_addresses") or []
    pool = str((meta or {}).get("pool") or (pools[0] if pools else ""))
    symbol = str((meta or {}).get("symbol")
                 or market.get("symbol") or "?")
    return pool, symbol


def _fetch_history(mint: str, pool: str, api_key: str,
                   now: datetime, lookback_days: int = 4):
    start = now.astimezone(WIB) - timedelta(days=lookback_days)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.astimezone(WIB).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return fetch_swaps(
        api_key, pool, mint, stop_ts=int(start.timestamp()) - 1,
        from_ts=int(start.timestamp()), to_ts=int(end.timestamp()),
        max_pages=80, use_gmgn=True)[0]


def run_daily(watchlist: dict, *, now=None, api_key: str = "",
              send_alerts: bool = True) -> list[dict]:
    """Refresh every token, persist idempotently, and alert only S1-S4."""
    now = (now or _now_wib()).astimezone(WIB)
    existing = load_daily_effort()
    existing_keys = {(row.get("mint"), row.get("date")) for row in existing}
    pending_rows = []
    token_info = []
    results = []

    for mint, meta in (watchlist or {}).items():
        symbol = str((meta or {}).get("symbol") or "?")
        try:
            pool, symbol = _pool_and_symbol(mint, meta or {})
            if not pool:
                raise RuntimeError("pair market tidak ditemukan")
            swaps = _fetch_history(mint, pool, api_key, now)
            market_candles = get_daily_candles_wib(pool, limit_days=5)
            fallback = fallback_candles_from_swaps(swaps)
            candles_by_date = {row["date"]: row for row in fallback}
            candles_by_date.update({row["date"]: row
                                    for row in market_candles})
            candles = sorted(candles_by_date.values(),
                             key=lambda row: row["date"])
            fresh = build_effort_rows(mint, swaps, candles, now=now)
            pending_rows.extend(fresh)
            token_info.append((mint, symbol, fresh))
            print(f"{symbol}: {len(swaps)} trades, {len(fresh)} daily rows")
        except Exception as exc:
            print(f"{symbol}: update failed: {exc}")
            results.append({"mint": mint, "symbol": symbol,
                            "ok": False, "error": str(exc)})

    merged = merge_daily_effort(pending_rows)
    for mint, symbol, fresh in token_info:
        history = rows_for_mint(merged, mint)
        result = classify_effort(history, mint)
        newest_key = (mint, result.get("date"))
        should_alert = (should_send_telegram(result)
                        and newest_key not in existing_keys)
        sent = bool(send_alerts and should_alert
                    and send_telegram(format_effort_alert(symbol, result)))
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
        results.append({"mint": mint, "symbol": symbol, "ok": True,
                        "result": result, "alert_sent": sent})
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
