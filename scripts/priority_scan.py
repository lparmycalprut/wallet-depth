# -*- coding: utf-8 -*-
"""Scan priority (volume-kering) watchlist tokens every 15 minutes for the
First Buy Surge — awal fase MARK-UP.

Token menjadi prioritas saat job harian menyatakan volumenya KERING. Scanner
ini kemudian mencari lonjakan buy pertama yang valid (lihat
``cvd_daily.first_buy_surge``):

  1. Volume 15 menit melonjak >= +100% vs volume rata-rata per jam fase
     kering H-1 (zona valid +100% s/d +300%+).
  2. Rasio buy tx >= 60% dari >= 10 tx, dari >= 5 wallet unik.
  3. CVD velocity (Delta/Volume) >= +20%.
  4. Cluster >= 3 big-buy (>= 1 SOL) tanpa sell besar pembalas.

Baseline kering di-resolve berurutan: metadata watchlist
(``priority_dry_hourly_sol``, disimpan job harian) -> baris KERING terakhir
di ``cvd_daily.json`` -> rata-rata per jam 24 jam sebelumnya dari store swap
lokal.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd import fetch_swaps, get_recent_swaps
from cvd_daily import (FIRST_BUY_SURGE_DEFAULTS, complete_daily_rows,
                       first_buy_surge, latest_dry_signal)
from signals import record_first_buy_surge
from watchlist import load_watchlist

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _thresholds(cfg):
    """Merge config.json blok ``first_buy_surge`` ke default detektor."""
    thr = dict(FIRST_BUY_SURGE_DEFAULTS)
    try:
        thr.update({k: v for k, v in (cfg.get("first_buy_surge") or {}).items()
                    if k in thr and v is not None})
    except Exception:
        pass
    return thr


def _baseline_from_daily_file(ca):
    """Volume/jam dari baris KERING terakhir di cvd_daily.json."""
    try:
        with open(os.path.join(BASE_DIR, "cvd_daily.json"), encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        return None
    dates = data.get(ca) or {}
    for date in sorted(dates, reverse=True):
        rows = (dates.get(date) or {}).get("rows") or []
        # Entri lama bisa memuat baris hari UTC yang saat itu masih berjalan;
        # baseline dari potongan ~1 jam jauh terlalu kecil dan membuat volume
        # normal terbaca sebagai lonjakan ratusan persen.
        dry = latest_dry_signal(complete_daily_rows(rows))
        if dry is not None:
            return float(dry.get("volume_sol") or 0.0) / 24.0
    return None


def _baseline_from_store(ca, now_ts):
    """Rata-rata volume per jam 24 jam sebelumnya dari store swap lokal."""
    swaps = get_recent_swaps(ca, hours=25)
    if not swaps:
        return None
    cutoff_end, cutoff_start = now_ts - 3600, now_ts - 25 * 3600
    vol = sum(float(s[1]) for s in swaps
              if cutoff_start <= int(s[2]) < cutoff_end)
    if vol <= 0:
        return None
    return vol / 24.0


def _dry_baseline_hourly(ca, meta, now_ts):
    """Baseline volume kering per jam: watchlist meta -> cvd_daily -> store."""
    try:
        stored = float(meta.get("priority_dry_hourly_sol") or 0.0)
        if stored > 0:
            return stored, "meta"
    except Exception:
        pass
    daily = _baseline_from_daily_file(ca)
    if daily is not None:
        return daily, "cvd_daily"
    store = _baseline_from_store(ca, now_ts)
    if store is not None:
        return store, "store"
    return None, "unknown"


def main():
    cfg = _config()
    thr = _thresholds(cfg)
    cooldown_min = float(cfg.get("first_buy_surge_cooldown_min", 240))
    now = int(time.time())
    window = int(thr.get("window_sec", 900))
    for ca, meta in load_watchlist().items():
        if not meta.get("priority"):
            continue
        symbol = meta.get("symbol", "?")
        try:
            swaps, _, _, _ = fetch_swaps("", "", ca, stop_ts=now - window,
                                         max_pages=10, sleep=0.1,
                                         use_gmgn=True)
            baseline, base_src = _dry_baseline_hourly(ca, meta, now)
            stats = first_buy_surge(swaps, baseline_hourly_sol=baseline,
                                    now_ts=now, **thr)
            base_txt = (f"{baseline:.3f} SOL/jam[{base_src}]"
                        if baseline is not None else f"n/a[{base_src}]")
            verdict = " | ".join(stats["reasons"])
            if stats["triggered"]:
                sent = record_first_buy_surge(
                    ca, symbol, stats, cooldown_sec=int(cooldown_min * 60))
                print(f"🚀 {symbol} FIRST BUY SURGE · {stats['tx']} tx / "
                      f"{stats['volume_sol']:.2f} SOL · baseline {base_txt} · "
                      f"sent={sent}\n   {verdict}")
            else:
                print(f"· {symbol} {stats['tx']} tx / "
                      f"{stats['volume_sol']:.2f} SOL · baseline {base_txt}\n"
                      f"   {verdict}")
        except Exception as exc:
            print(f"⚠️ {ca[:8]}… {exc}")


if __name__ == "__main__":
    main()
