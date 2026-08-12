# -*- coding: utf-8 -*-
"""4-hour incremental CVD collector + daily 4-pillar evaluation.

Usage:
    python scripts/update_cvd.py            # auto (4h; + daily at 00:00 UTC)
    python scripts/update_cvd.py 4h
    python scripts/update_cvd.py daily

Schedule (WIB = UTC+7):
    03:00, 07:00, 11:00, 15:00, 19:00, 23:00 WIB  ==  0 */4 * * * UTC
    Daily aggregation runs at 00:00 UTC / 07:00 WIB from the six chunks
    already on disk so the midnight job never walks a full 24h of pages.
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import get_helius_keys, get_market, load_config
from cvd import fetch_swaps, persist_swaps
from cvd_daily import (CHUNK_SEC, aggregate_chunks_to_daily,
                       calculate_daily_cvd, chunk_coverage_hours,
                       chunk_floor_ts, complete_daily_rows,
                       persist_daily_snapshot, swaps_from_4h_chunks,
                       upsert_4h_chunk)
from prepump_detector import evaluate_prepump
from signals import (begin_digest, flush_telegram_digest,
                     queue_prepump_4pilar_message, record_daily_cvd,
                     record_prepump_4pilar)
from watchlist import load_watchlist, update_local_meta

UTC = timezone.utc


def _now():
    return datetime.now(UTC)


def _completed_window(now=None):
    """Previous closed 4-hour UTC window ``[start, end)``."""
    now = now or _now()
    end = chunk_floor_ts(int(now.timestamp()))
    # Cron fires on the hour; the window that just closed ends *now*.
    if int(now.timestamp()) - end < 60:
        pass
    start = end - CHUNK_SEC
    return start, end


def _pool_for(ca, meta):
    pool = (meta or {}).get("pool") or ""
    if pool:
        return pool
    try:
        market = get_market(ca)
        pools = (market or {}).get("pair_addresses") or []
        return pools[0] if pools else ""
    except Exception:
        return ""


def _symbol(ca, meta):
    return (meta or {}).get("symbol") or "?"


def run_4h(watchlist, *, now=None, api_key=""):
    """Fetch the just-closed 4-hour window for every watchlist token."""
    now = now or _now()
    start, end = _completed_window(now)
    print(f"4h chunk {start} → {end} "
          f"({datetime.fromtimestamp(start, UTC).isoformat()})")
    results = []
    for ca, meta in (watchlist or {}).items():
        symbol = _symbol(ca, meta)
        pool = _pool_for(ca, meta)
        try:
            swaps, _, _, _ = fetch_swaps(
                api_key, pool, ca,
                stop_ts=start - 300,
                max_pages=24,
                use_gmgn=True,
            )
        except Exception as exc:
            print(f"  {symbol} fetch failed: {exc}")
            results.append({"ca": ca, "symbol": symbol, "ok": False,
                            "error": str(exc)})
            continue
        window = [s for s in (swaps or [])
                  if len(s) >= 3 and start <= int(s[2]) < end]
        upsert_4h_chunk(ca, window, symbol=symbol,
                        start_ts=start, end_ts=end)
        persist_swaps(ca, window, retain_hours=168, pool=pool)
        print(f"  {symbol}: {len(window)} swaps in window "
              f"(fetched {len(swaps or [])})")
        results.append({"ca": ca, "symbol": symbol, "ok": True,
                        "n": len(window)})
    return results


def _yesterday(now=None):
    now = now or _now()
    return (now.date() - timedelta(days=1)).isoformat()


def _ensure_day_swaps(ca, symbol, pool, api_key, date, *, now_ts):
    """Return yesterday's swaps from chunks, or fall back to a 24h fetch."""
    covered = chunk_coverage_hours(ca, date)
    swaps = swaps_from_4h_chunks(ca, date=date)
    if covered >= 20.0 and swaps:
        print(f"  {symbol}: aggregating {covered:.1f}h of chunks "
              f"({len(swaps)} swaps)")
        return swaps, "chunks"
    print(f"  {symbol}: chunk coverage {covered:.1f}h — fallback 24h fetch")
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
    start = int(day.timestamp())
    end = start + 86400
    try:
        fetched, _, _, _ = fetch_swaps(
            api_key, pool, ca,
            stop_ts=start - 300,
            max_pages=80,
            use_gmgn=True,
        )
    except Exception as exc:
        print(f"  {symbol}: fallback fetch failed: {exc}")
        return swaps, "chunks-partial"
    window = [s for s in (fetched or [])
              if len(s) >= 3 and start <= int(s[2]) < end]
    upsert_4h_chunk(ca, window, symbol=symbol, start_ts=start, end_ts=end)
    persist_swaps(ca, window, retain_hours=168, pool=pool)
    return window, "fetch"


def run_daily(watchlist, *, now=None, api_key=""):
    """Aggregate yesterday's six 4h chunks and evaluate the 4 pillars."""
    now = now or _now()
    now_ts = int(now.timestamp())
    yesterday = _yesterday(now)
    print(f"Daily 4-pillar eval for UTC {yesterday}")
    begin_digest()
    results = []
    for ca, meta in (watchlist or {}).items():
        symbol = _symbol(ca, meta)
        pool = _pool_for(ca, meta)
        lock = meta.get("holder_lock_pct")
        if lock is None:
            lock = meta.get("wyckoff_lock_pct")
        day_swaps, src = _ensure_day_swaps(
            ca, symbol, pool, api_key, yesterday, now_ts=now_ts)
        history = swaps_from_4h_chunks(ca, days=7, now_ts=now_ts)
        if day_swaps:
            seen = {(s[0], float(s[1]), int(s[2]), str(s[3]))
                    for s in history if len(s) >= 4}
            for row in day_swaps:
                key = (row[0], float(row[1]), int(row[2]), str(row[3]))
                if key not in seen:
                    history.append(tuple(row) if not isinstance(row, tuple)
                                   else row)
                    seen.add(key)
        history.sort(key=lambda r: r[2])
        daily = calculate_daily_cvd(history) or aggregate_chunks_to_daily(
            ca, days=7, now_ts=now_ts)
        complete = complete_daily_rows(daily, now_ts=now_ts)
        persist_daily_snapshot(ca, symbol, complete, now_ts=now_ts)
        if complete:
            record_daily_cvd(ca, symbol, complete, now_ts=now_ts)
        ev = evaluate_prepump(
            history, daily_rows=complete, holder_lock_pct=lock,
            now_ts=now_ts, include_today=False)
        record_prepump_4pilar(ca, symbol, ev, now_ts=now_ts)
        if ev.get("verdict") in ("PASS", "WATCH", "STEALTH DUMP"):
            queue_prepump_4pilar_message(ca, symbol, ev)
        metrics = ev.get("metrics") or {}
        try:
            update_local_meta(ca, {
                "symbol": symbol,
                "prepump_ts": now_ts,
                "prepump_date": ev.get("date"),
                "prepump_verdict": ev.get("verdict"),
                "prepump_phase": ev.get("phase"),
                "prepump_passed": ev.get("passed"),
                "prepump_total": ev.get("total", 4),
                "prepump_stealth_dump": bool(ev.get("stealth_dump")),
                "prepump_absorption_pct": metrics.get("absorption_pct"),
                "prepump_buy_tx_pct": metrics.get("buy_tx_pct"),
                "prepump_avg_buy_sol": metrics.get("avg_buy_sol"),
                "prepump_avg_sell_sol": metrics.get("avg_sell_sol"),
                "prepump_vol_change_pct": metrics.get("volume_change_pct"),
                "prepump_delta_sol": metrics.get("delta_sol"),
                "prepump_src": src,
            })
        except Exception as exc:
            print(f"  {symbol}: watchlist meta failed: {exc}")
        print(f"  {symbol}: {ev.get('verdict')} "
              f"{ev.get('passed')}/{ev.get('total')} "
              f"abs={metrics.get('absorption_pct')}% src={src}")
        results.append({"ca": ca, "symbol": symbol, "evaluation": ev,
                        "src": src})
    flush_telegram_digest(
        title="🟢 <b>DAILY 4-PILAR PRE-PUMP — 07:00 WIB</b>")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", nargs="?", default="auto",
        choices=("auto", "4h", "daily", "60"),
        help="auto = 4h always, plus daily at 00:00 UTC "
             "(legacy '60' is treated as auto)",
    )
    args = parser.parse_args(argv)
    mode = "auto" if args.mode == "60" else args.mode
    now = _now()
    cfg = load_config()
    keys = get_helius_keys(config=cfg)
    api_key = keys[0] if keys else ""
    watchlist = load_watchlist()
    if not watchlist:
        print("Watchlist empty — nothing to do.")
        return 0
    print(f"=== CVD updater mode={mode} utc={now.isoformat()} "
          f"tokens={len(watchlist)} ===")
    do_4h = mode in ("auto", "4h")
    do_daily = mode == "daily" or (mode == "auto" and now.hour == 0)
    if do_4h:
        run_4h(watchlist, now=now, api_key=api_key)
    if do_daily:
        run_daily(watchlist, now=now, api_key=api_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
