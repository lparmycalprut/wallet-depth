# -*- coding: utf-8 -*-
"""Daily CVD + Prepump BARU updater (cron at 07:00 WIB = 00:00 UTC).

Daily-only per owner request 2026-08-07 (revised 07:00 WIB):
  - Fetch GMGN Token Trades for each watchlist CA (no Helius needed for swaps)
  - Update cvd.json + conviction.json (72h window)
  - Daily snapshot to history.json (DexScreener+GMGN lightweight)
  - Evaluate prepump BARU (7 checks validated 10 pump + LUNA) via prepump_baru_detector
  - Telegram digest ONCE per day at 07:00 WIB (00:00 UTC, GMGN candle flip)

Usage: python scripts/update_cvd.py [max_pages]
  max_pages default 60 (GMGN pages)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import (
    record_conviction,
    update_token_cvd,
    get_gmgn_last_error,
    get_recent_swaps,
)
from signals import begin_digest, flush_telegram_digest
from watchlist import load_watchlist, save_watchlist

try:
    from core import get_market
except Exception:
    def get_market(_ca):
        return {}


def main_pool(ca: str):
    try:
        market = get_market(ca)
        pools = market.get("pair_addresses") or []
        if not market or not pools:
            return None, None, None
        return (pools[0], float(market.get("price_usd") or 0), market.get("symbol") or "?")
    except Exception:
        return None, None, None


def daily_snapshot_one(ca: str):
    """Lightweight daily snapshot (DexScreener+GMGN) for history.json. Reuses scripts/daily_snapshot.snapshot_one if available."""
    try:
        from scripts.daily_snapshot import snapshot_one
        return snapshot_one(ca)
    except Exception:
        # Fallback minimal: try import directly
        try:
            import importlib.util, pathlib
            p = pathlib.Path(__file__).parent / "daily_snapshot.py"
            spec = importlib.util.spec_from_file_location("daily_snapshot_fallback", str(p))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.snapshot_one(ca)
        except Exception as e:
            raise RuntimeError(f"snapshot fallback failed: {e}")


def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    wl = load_watchlist()
    if not wl:
        print("Watchlist empty — nothing to do.")
        return

    wl_changed = False
    begin_digest()
    print(f"Starting daily prepump BARU update for {len(wl)} token(s) at {time.strftime('%Y-%m-%d %H:%M WIB', time.gmtime(time.time()+7*3600))} (07:00 WIB = 00:00 UTC)")

    for ca, meta in list(wl.items()):
        try:
            pool, price_now, live_sym = main_pool(ca)
            if not pool:
                print(f"❌ {ca[:8]}… no pool found (DexScreener)")
                continue
            if (meta.get("symbol") in (None, "", "?")) and live_sym and live_sym != "?":
                meta["symbol"] = live_sym
                wl_changed = True

            # --- CVD via GMGN ---
            res = update_token_cvd(None, ca, pool, max_pages=max_pages, use_gmgn=True)
            gap = " ⚠️gap" if res.get("gap") else ""
            gmgn_err = res.get("error") or get_gmgn_last_error()
            if not res.get("fetch_ok", True):
                coverage_from = res.get("coverage_from")
                partial_ok = (res.get("partial") and coverage_from is not None and (time.time() - coverage_from) <= 4 * 3600)
                if not partial_ok:
                    print(f"⚠️ {meta.get('symbol','?'):>10} {ca[:8]}… CVD skip: {gmgn_err or 'incomplete'}")
                    continue
            if gmgn_err and res.get("new_swaps", 0) == 0:
                gap += f" gmgn:{gmgn_err[:60]}"

            # --- Conviction ---
            cp = record_conviction(ca, window_h=4)
            conv_txt = f" conv={cp['conviction']:.0f}%" if cp else ""

            # --- Daily snapshot to history.json (best effort, idempotent) ---
            hist_txt = ""
            try:
                # Use daily_snapshot helper directly (writes history.json)
                import json, datetime
                from core import atomic_write_json
                hist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history.json")
                try:
                    with open(hist_path, "r", encoding="utf-8") as f:
                        hist = json.load(f) or {}
                except Exception:
                    hist = {}
                today = datetime.date.today().isoformat()
                if ca not in hist or today not in hist[ca]:
                    snap = daily_snapshot_one(ca)
                    hist.setdefault(ca, {})[today] = snap
                    atomic_write_json(hist_path, hist, indent=1)
                    hist_txt = f" hist:{snap.get('total_holders','?')}h"
                else:
                    hist_txt = " hist:skip(today exists)"
            except Exception as e:
                hist_txt = f" hist-err:{str(e)[:20]}"

            # --- Prepump BARU (prepump_baru_detector) ---
            pp_txt = ""
            try:
                from prepump_baru_detector import evaluate_baru_daily, detect_baru_and_record
                # Daily window: last 24h (previous UTC day)
                swaps_24h = get_recent_swaps(ca, hours=24)
                # Try to get price info for pantul check (best effort)
                tinfo = {"symbol": meta.get("symbol", "?"), "price_usd": price_now}
                # Optionally fetch candles for low/close — skip if fails
                candles = None
                try:
                    from cvd import fetch_candles
                    # Fetch 24h of hourly candles for low detection
                    if pool:
                        candles = fetch_candles(pool, timeframe="hour", aggregate=1, limit=24, timeout=6)
                except Exception:
                    candles = None
                res_baru = evaluate_baru_daily(swaps_24h, token_info=tinfo, candles=candles, now_ts=int(time.time()))
                # Record + queue Telegram if sinyal_muncul
                rec = detect_baru_and_record(ca, meta.get("symbol", "?"), swaps_24h, token_info=tinfo, candles=candles, now_ts=int(time.time()))
                tier = res_baru.get("tier", "belum")
                lolos = res_baru.get("lolos", 0)
                total = res_baru.get("total", 7)
                if tier == "sinyal_muncul":
                    pp_txt = f" 🎯baru:SINYAL {lolos}/{total}"
                else:
                    pp_txt = f" 🎯baru:belum {lolos}/{total}"
            except Exception as e:
                pp_txt = f" baru_err:{str(e)[:30]}"

            print(f"✅ {meta.get('symbol','?'):>10} {ca[:8]}… +{res.get('new_swaps',0)} swaps{gap}{conv_txt}{hist_txt}{pp_txt}")

        except Exception as e:
            print(f"❌ {ca[:8]}… error: {str(e)[:120]}")

    # Flush telegram digest (once per day at 07:00 WIB)
    try:
        n = flush_telegram_digest(title="📬 <b>DAILY PRE-PUMP BARU — 07:00 WIB (00:00 UTC)</b>")
        if n:
            print(f"📬 Telegram digest sent: {n} message(s)")
        else:
            print("📬 Telegram digest: no baru sinyal to send")
    except Exception as e:
        print(f"digest-err: {e}")

    if wl_changed:
        save_watchlist(wl, "auto-fix symbols daily")
        print("watchlist symbols updated")

if __name__ == "__main__":
    main()
