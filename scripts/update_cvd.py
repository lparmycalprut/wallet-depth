# -*- coding: utf-8 -*-
"""Daily GMGN CVD updater (07:00 WIB / 00:00 UTC).

The daily calculation follows the companion GMGN browser extension. It is the
only source for CVD signal recording and Telegram notifications. A dry-volume
result marks a token priority for the separate 15-minute scanner.

Usage: python scripts/update_cvd.py [max_pages]
  max_pages default 60 (GMGN pages)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import (
    update_token_cvd,
    get_gmgn_last_error,
    get_recent_swaps,
    record_holder_snapshot,
    record_real_dust_point,
    top_holder_analysis,
)
from signals import (begin_digest, flush_telegram_digest, record_daily_cvd,
                     queue_daily_cvd_message)
from watchlist import load_watchlist, save_watchlist
from cvd_daily import calculate_daily_cvd, latest_dry_signal

try:
    from core import (get_helius_keys, get_holders, get_market,
                      get_supply, gmgn_token_stat)
except Exception:
    get_holders = None
    get_supply = None

    def get_helius_keys():
        return ()

    def get_market(_ca):
        return {}

    def gmgn_token_stat(_ca, timeout=15):
        return {}


def _cron_dust_limit() -> float:
    try:
        import json as _json
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            return float((_json.load(f) or {}).get("dust_limit_usd", 5.0))
    except Exception:
        return 5.0


def _gmgn_top_holders(ca: str, timeout: int = 15) -> tuple:
    stat = gmgn_token_stat(ca, timeout=timeout)
    return (stat.get("holders") or None), stat.get("supply")


def _try_snapshot(api_keys, ca: str, meta: dict,
                  price_now: float = 0.0) -> str:
    """Holder snapshot — Helius (preferred) → GMGN (fallback).
    Records to holder_snapshots.json & real_dust_history.json, and
    computes top holder metrics (diamond_pct, real_holders, dust_holders)
    to update watchlist metadata so the UI cards display them.
    """
    limit = _cron_dust_limit()
    holders_used = None
    supply_used = 0.0
    status_str = " snap-skip:no-source"

    if api_keys and get_holders is not None:
        try:
            df = get_holders(api_keys, ca)
            if df is not None and not df.empty:
                if get_supply is not None:
                    try:
                        supply_used, _ = get_supply(api_keys, ca)
                    except Exception:
                        supply_used = 0.0
                pairs = []
                amt_col = ("ui_amount" if "ui_amount" in df.columns
                           else "raw_amount")
                for _, row in df.iterrows():
                    owner = row.get("owner")
                    amt = row.get(amt_col)
                    if owner and amt and float(amt) > 0:
                        pairs.append([str(owner), float(amt)])
                if pairs:
                    holders_used = pairs
                    record_holder_snapshot(ca, pairs, supply_used or 0.0)
                    rd_txt = ""
                    try:
                        if price_now and price_now > 0:
                            n_real = sum(1 for _, amt in pairs
                                         if amt * price_now >= limit)
                            n_dust = len(pairs) - n_real
                            pt = record_real_dust_point(
                                ca, n_real, n_dust, price=price_now,
                                dust_limit=limit)
                            if pt is not None:
                                rd_txt = f" rd:{n_real}r/{n_dust}d"
                    except Exception:
                        pass
                    status_str = f" snap-helius:{len(pairs)} holders{rd_txt}"
        except Exception as e:
            print(f"WARN: helius holder snapshot failed for {ca}: {e}")

    if holders_used is None:
        try:
            holders, supply = _gmgn_top_holders(ca)
            if holders:
                holders_used = holders
                supply_used = supply or 0.0
                record_holder_snapshot(ca, holders, supply_used)
                status_str = f" snap-gmgn:{len(holders)} holders"
        except Exception:
            pass

    if holders_used:
        try:
            swaps_72h = get_recent_swaps(ca, hours=72)
            tha = top_holder_analysis(holders_used, swaps=swaps_72h,
                                      price_usd=price_now,
                                      dust_limit_usd=limit,
                                      supply=supply_used)
            meta["diamond_pct"] = round(float(tha.get("diamond_pct") or 0.0), 1)
            meta["real_holders"] = int(tha.get("all_real_holders") if tha.get("all_real_holders") is not None else (tha.get("real_holders") or 0))
            meta["dust_holders"] = int(tha.get("all_dust_holders") if tha.get("all_dust_holders") is not None else max(0, tha.get("all_holders", 0) - meta["real_holders"]))
        except Exception as e:
            print(f"WARN: top_holder_analysis failed for {ca}: {e}")

    return status_str


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

    api_keys = tuple(get_helius_keys())
    wl_changed = False
    begin_digest()
    print(f"Starting CVD & prepump BARU update for {len(wl)} token(s) at {time.strftime('%Y-%m-%d %H:%M WIB', time.gmtime(time.time()+7*3600))}")

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

            # --- Daily CVD (the extension's day-by-day calculation) ---
            daily_swaps = get_recent_swaps(ca, hours=72)
            daily_rows = calculate_daily_cvd(daily_swaps)
            record_daily_cvd(ca, meta.get("symbol", "?"), daily_rows,
                             price=price_now)
            queue_daily_cvd_message(ca, meta.get("symbol", "?"), daily_rows,
                                    price=price_now)
            dry = latest_dry_signal(daily_rows)
            if dry and meta.get("priority_dry_vol_date") != dry.get("date"):
                # Simpan baseline volume kering (per jam) — scanner 15 menit
                # memakainya sebagai pembanding lonjakan volume pada deteksi
                # First Buy Surge (awal mark-up).
                dry_vol = float(dry.get("volume_sol") or 0.0)
                meta["priority_dry_vol_date"] = dry.get("date")
                meta["priority_dry_volume_sol"] = round(dry_vol, 8)
                meta["priority_dry_hourly_sol"] = round(dry_vol / 24.0, 8)
                wl_changed = True
            if dry and not meta.get("priority"):
                # Priority is intentionally a watchlist state, not another
                # signal type: it is consumed by the 15-minute workflow.
                meta["priority"] = True
                meta["priority_since"] = dry.get("date")
                meta["priority_reason"] = "daily_volume_dry"
                wl_changed = True
            conv_txt = f" daily:{daily_rows[-1].get('status', '?')}" if daily_rows else ""

            # --- Holder snapshot + real/dust history (Helius / GMGN) ---
            snap_txt = _try_snapshot(api_keys, ca, meta,
                                     price_now=price_now or 0.0)
            if snap_txt and "snap-skip" not in snap_txt:
                wl_changed = True

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

            # Daily CVD above is the only daily signal source.
            print(f"✅ {meta.get('symbol','?'):>10} {ca[:8]}… +{res.get('new_swaps',0)} swaps{gap}{conv_txt}{hist_txt}{snap_txt}")

        except Exception as e:
            print(f"❌ {ca[:8]}… error: {str(e)[:120]}")

    # Flush telegram digest
    try:
        now_wib = time.strftime('%H:%M WIB', time.gmtime(time.time()+7*3600))
        n = flush_telegram_digest(title=f"📬 <b>DAILY GMGN CVD — {now_wib}</b>")
        if n:
            print(f"📬 Telegram digest sent: {n} message(s)")
        else:
            print("📬 Telegram digest: no daily CVD data to send")
    except Exception as e:
        print(f"digest-err: {e}")

    if wl_changed:
        save_watchlist(wl, "auto-fix symbols / top holders update")
        print("watchlist symbols and holder stats updated")

if __name__ == "__main__":
    main()
