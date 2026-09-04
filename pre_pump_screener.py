# -*- coding: utf-8 -*-
"""🚀 Pre-Pump Screener — sinyal on-chain untuk token yang mendekati pump.

Empat sinyal independen, masing-masing mengembalikan ``confidence`` 0–1 yang
dirata-rata berbobot jadi **PUMP SCORE** 0–10:

A. **Liquidity wave** — DexScreener tidak punya endpoint riwayat likuiditas,
   jadi setiap run mencatat ``liquidity.usd`` pool ke journal lokal
   (``pre_pump_liq.json``) dan pola *dua gelombang add* (test kecil → add ≥ 5x
   dalam 48 jam) dibaca dari journal itu. Run pertama hanya mengisi journal:
   tanpa ≥ 2 observasi confidence dikunci ke ``LIQ_MISSING_CONFIDENCE`` 0,3.
B. **Holder consolidation** — bandingkan snapshot holder sekarang dengan titik
   ± 24 jam lalu di ``holder_history`` / ``holder_status``. Wallet dust yang
   tumbuh melewati batas $10 (``dust_grew_out`` dari kronologi, fallback
   selisih ``dust_count``) + rata-rata bag ≥ 2x = fase akumulasi awal.
C. **Volume calm-before-storm** — candle hourly 7 hari: 24 jam *sebelum*
   window 6 jam terakhir ≤ 30% rata-rata harian, lalu 6 jam terakhir
   melonjak ≥ 2x baseline 6 jam. (Dua window itu tidak boleh tumpang tindih —
   lihat docstring :func:`detect_volume_anomaly`.)
D. **TX velocity** — swap Helius per jam (fallback agregat ``txns``
   DexScreener): akselerasi 2 jam terakhir vs 2 jam pertama ≥ 1,5 dan
   ``buy_pressure`` ≥ 0,65.

Hanya token watchlist ``source=degen`` yang dianalisa (token LP/Meteora
dikecualikan — lihat :func:`load_degen_watchlist`).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html as _html
import json
import os
import time

import streamlit as st

from core import (atomic_write_json, get_helius_keys, get_hourly_candles,
                  get_market)
from holder_history import load_durable_holder_history
from holder_status import load_holder_status
from links import (CVD_PAGE_PATH, HOLDER_PAGE_PATH, dexscreener_token_url,
                   external_links_html)
from lp_watchlist import points_for_mint
from watchlist import load_watchlist

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIQ_JOURNAL_PATH = os.path.join(BASE_DIR, "pre_pump_liq.json")

# ---------------------------------------------------------------------------
# Ambang sinyal
# ---------------------------------------------------------------------------
DEGEN_SOURCE = "degen"          # hanya token hasil Scan Degen

# A. liquidity wave
LIQ_LOOKBACK_HOURS = 48
LIQ_SECOND_WAVE_MULT = 5.0          # add kedua ≥ 5x add pertama
LIQ_SECOND_WAVE_MULT_LOW_VOL = 3.0  # token berlikuiditas kecil: 3x cukup
LIQ_LOW_VOLUME_USD = 25_000.0       # likuiditas di bawah ini = "sangat kecil"
LIQ_MIN_ADD_USD = 500.0             # kenaikan di bawah ini = noise harga
LIQ_MIN_ADD_PCT = 5.0               # ... dan minimal 5% dari likuiditas awal
LIQ_WAVE_MERGE_MIN = 30             # add beruntun < 30 menit = satu gelombang
LIQ_MISSING_CONFIDENCE = 0.3        # spec: data likuiditas tidak ada → 0,3
LIQ_KEEP_HOURS = 72                 # journal disisakan 3 hari
LIQ_MAX_POINTS = 900                # ~3 hari @ 5 menit

# B. holder consolidation
CONSOL_WINDOW_HOURS = 24
CONSOL_MIN_WALLETS = 5              # ≥ 5 wallet keluar dari dust
CONSOL_MIN_BAG_GROWTH = 2.0         # rata-rata bag ≥ 2x (+100%)
CONSOL_STALE_TOLERANCE_HOURS = 8    # titik 24 jam ± 8 jam masih dipakai (stale)

# C. volume profile
VOLUME_LOOKBACK_DAYS = 7
VOLUME_CALM_RATIO = 0.3             # vol 24 jam ≤ 30% rata-rata harian = tenang
VOLUME_SPIKE_RATIO = 2.0            # lonjakan ≥ 2x baseline
VOLUME_SPIKE_BASE = "6h"            # "6h" = baseline 6 jam; "daily" = rata-rata harian
VOLUME_6H_HOURS = 6
VOLUME_MIN_HOURS = 24               # coverage minimum supaya baseline berarti

# D. tx velocity
VELOCITY_LOOKBACK_HOURS = 6
VELOCITY_MIN = 1.5                  # (avg 2 jam akhir - avg 2 jam awal) / awal
BUY_PRESSURE_MIN = 0.65
VELOCITY_MIN_TX = 8                 # sampel < 8 swap = confidence rendah
VELOCITY_MAX_PAGES = 3              # 3 halaman Helius = 300 swap
VELOCITY_SOURCE_CONFIDENCE = {"helius_swaps": 1.0,
                              "dexscreener_txns": 0.6}

REFRESH_SEC = 300                   # auto-refresh 5 menit
RESULTS_KEY = "pre_pump_results"
DUE_KEY = "pre_pump_due"
DEFAULT_MAX_TOKENS = 24

SIGNAL_KEYS = ("liq", "consol", "vol", "vel")
SIGNAL_WEIGHT = 0.25                # 4 sinyal × 0,25 = 1,0


# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------
def _num(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and number != float("inf") else default


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, low: float = 0.0, high: float = 1.0) -> float:
    """Batasi ``value`` ke ``[low, high]``; ``None``/bukan angka → ``low``.

    Confidence sinyal yang datanya tidak ada datang sebagai ``None``, dan
    ``float(None)`` melempar — satu confidence kosong tidak boleh mematikan
    perhitungan skor seluruh kartu.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(low)
    if number != number:  # NaN
        return float(low)
    return max(float(low), min(float(high), number))


def _now() -> int:
    return int(time.time())


def _hours(seconds) -> float:
    return round(float(seconds or 0) / 3600.0, 2)


def _pair_addresses(market) -> list[str]:
    pairs = (market or {}).get("pair_addresses") if isinstance(market, dict) \
        else None
    return [str(pair) for pair in (pairs or []) if pair]


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
def load_degen_watchlist(watchlist: dict | None = None) -> dict:
    """Token watchlist ``source=degen`` saja (token LP/Meteora dikecualikan).

    ``source`` ditulis listing Degen GMGN (``render_trending(...,
    source="degen")``); token ``meteora`` adalah pool LP yang di-chart
    terpisah dan ``manual`` tidak selalu memecoin — keduanya keluar dari
    screener. Urutan watchlist dipertahankan.
    """
    source = watchlist if watchlist is not None else load_watchlist()
    if not isinstance(source, dict):
        return {}
    picked = {}
    for ca, meta in source.items():
        meta = meta if isinstance(meta, dict) else {}
        if str(meta.get("source") or "").strip().lower() != DEGEN_SOURCE:
            continue
        if str(ca or "").strip():
            picked[str(ca).strip()] = meta
    return picked


# ---------------------------------------------------------------------------
# Journal likuiditas (DexScreener tidak menyediakan riwayat likuiditas)
# ---------------------------------------------------------------------------
def load_liquidity_journal(path: str | None = None) -> dict:
    """Journal ``{ca: [{ts, liq_usd, mc, pool}]}``; payload rusak → ``{}``."""
    try:
        with open(path or LIQ_JOURNAL_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:  # noqa: BLE001 - journal hilang/rusak bukan fatal
        return {}
    if not isinstance(data, dict):
        return {}
    journal = {}
    for ca, rows in data.items():
        if not isinstance(rows, list):
            continue
        clean = [row for row in rows
                 if isinstance(row, dict) and _int(row.get("ts")) > 0
                 and _num(row.get("liq_usd"), None) is not None]
        if clean:
            journal[str(ca)] = sorted(clean, key=lambda row: _int(row["ts"]))
    return journal


def record_liquidity_observations(rows, *, now: int | None = None,
                                  path: str | None = None,
                                  min_gap_sec: int = 60) -> dict:
    """Catat satu observasi likuiditas per token lalu tulis journal.

    ``rows`` = ``[{ca, liq_usd, mc, pool}]``. Observasi yang lebih muda dari
    ``min_gap_sec`` dari titik terakhir token itu dilewati supaya rerun cepat
    tidak menggandakan titik (satu titik per interval refresh sudah cukup),
    dan journal dipangkas ke ``LIQ_KEEP_HOURS`` / ``LIQ_MAX_POINTS``.
    """
    stamp = _int(now) or _now()
    journal = load_liquidity_journal(path)
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ca = str(row.get("ca") or "").strip()
        liq = _num(row.get("liq_usd"), None)
        if not ca or liq is None or liq < 0:
            continue
        series = journal.setdefault(ca, [])
        last_ts = _int(series[-1].get("ts")) if series else 0
        if series and stamp - last_ts < max(0, int(min_gap_sec)):
            continue
        series.append({"ts": stamp, "liq_usd": round(liq, 2),
                       "mc": _num(row.get("mc"), None),
                       "pool": str(row.get("pool") or "")})
        floor = stamp - LIQ_KEEP_HOURS * 3600
        series[:] = [item for item in series if _int(item.get("ts")) >= floor]
        if len(series) > LIQ_MAX_POINTS:
            del series[:-LIQ_MAX_POINTS]
        if not series:
            journal.pop(ca, None)
    try:
        atomic_write_json(path or LIQ_JOURNAL_PATH, journal, indent=1)
    except Exception:  # noqa: BLE001 - journal gagal tulis = sinyal lain jalan
        pass
    return journal


def liquidity_series_for(journal: dict | None, ca: str, *,
                         lookback_hours: int = LIQ_LOOKBACK_HOURS,
                         now: int | None = None) -> list[dict]:
    """Observasi likuiditas satu token dalam window (urut naik)."""
    stamp = _int(now) or _now()
    floor = stamp - max(1, int(lookback_hours)) * 3600
    rows = ((journal or {}).get(str(ca or "")) or [])
    return [dict(row) for row in rows
            if isinstance(row, dict)
            and floor < _int(row.get("ts")) <= stamp]


def liquidity_waves(series, *, min_add_usd: float = LIQ_MIN_ADD_USD,
                    min_add_pct: float = LIQ_MIN_ADD_PCT,
                    merge_min: int = LIQ_WAVE_MERGE_MIN) -> list[dict]:
    """Kelompokkan kenaikan likuiditas beruntun jadi gelombang *add*.

    Kenaikan dihitung antar observasi berurutan; yang berjarak ≤
    ``merge_min`` menit digabung supaya satu add besar tidak terhitung
    beberapa kali (tiap run menambah satu titik). Kenaikan kecil
    (< ``min_add_usd`` atau < ``min_add_pct``) diabaikan karena likuiditas
    USD juga bergerak mengikuti harga.
    """
    rows = sorted((row for row in (series or [])
                   if isinstance(row, dict) and _int(row.get("ts")) > 0
                   and _num(row.get("liq_usd"), None) is not None),
                  key=lambda row: _int(row["ts"]))
    waves: list[dict] = []
    for previous, current in zip(rows, rows[1:]):
        before = _num(previous.get("liq_usd"), 0.0)
        after = _num(current.get("liq_usd"), 0.0)
        delta = after - before
        pct = (delta / before * 100.0) if before > 0 else None
        if delta < max(0.0, float(min_add_usd)):
            continue
        if pct is not None and pct < float(min_add_pct):
            continue
        ts = _int(current.get("ts"))
        if waves and ts - _int(waves[-1]["end_ts"]) <= int(merge_min) * 60:
            wave = waves[-1]
            wave["add_usd"] = round(wave["add_usd"] + delta, 2)
            wave["end_ts"] = ts
            wave["end_liq_usd"] = after
            continue
        waves.append({"start_ts": _int(previous.get("ts")), "end_ts": ts,
                      "add_usd": round(delta, 2), "start_liq_usd": before,
                      "end_liq_usd": after})
    return waves


def _best_wave_pair(waves, lookback_hours: int) -> dict | None:
    """Pasangan gelombang (add kecil → add besar) dengan rasio tertinggi."""
    best = None
    for index, first in enumerate(waves):
        first_add = _num(first.get("add_usd"), 0.0)
        if first_add <= 0:
            continue
        for second in waves[index + 1:]:
            second_add = _num(second.get("add_usd"), 0.0)
            if second_add <= 0:
                continue
            diff_h = _hours(_int(second.get("start_ts"))
                            - _int(first.get("start_ts")))
            if diff_h > lookback_hours:
                continue
            mult = second_add / first_add
            if best is None or mult > best["mult"]:
                best = {"mult": mult, "first_add_usd": first_add,
                        "second_add_usd": second_add, "time_diff_hours": diff_h}
    return best


def _liq_confidence(detected: bool, pair: dict | None, threshold: float,
                    observations: int) -> float:
    """Confidence 0–1 untuk sinyal likuiditas.

    - Observasi < 2: ``LIQ_MISSING_CONFIDENCE`` (spec 7 — data likuiditas
      hilang tidak dibaca sebagai "aman", tapi juga tidak menyumbang skor).
    - Terdeteksi: 0,55 + margin di atas ambang + coverage observasi.
    - Ada gelombang tetapi belum menembus ambang: kredit parsial ≤ 0,35.
    """
    if observations < 2:
        return LIQ_MISSING_CONFIDENCE
    mult = _num((pair or {}).get("mult"), None)
    if detected and mult:
        margin = _clamp((mult - threshold) / max(threshold, 1e-9))
        coverage = _clamp(observations / 6.0)
        return round(_clamp(0.55 + 0.3 * margin + 0.15 * coverage, 0.55, 1.0),
                     3)
    if mult is None:
        return 0.25
    return round(_clamp(0.05 + 0.3 * (mult / max(threshold, 1e-9)), 0.0, 0.35),
                 3)


def detect_liquidity_add_pattern(token_ca: str,
                                 lookback_hours: int = LIQ_LOOKBACK_HOURS, *,
                                 series=None, market: dict | None = None,
                                 now: int | None = None) -> dict:
    """Deteksi pola *dua gelombang add likuiditas* dalam ``lookback_hours``.

    ``is_pump_prep = (second_add >= 5 * first_add) and (time_between <= 48h)``
    — token berlikuiditas < ``LIQ_LOW_VOLUME_USD`` memakai ambang 3x (spec 7:
    token bervolume sangat rendah tidak wajib 5x). ``series`` boleh disuntikkan
    (test); tanpa itu journal lokal dibaca.
    """
    stamp = _int(now) or _now()
    ca = str(token_ca or "").strip()
    lookback_hours = max(1, int(lookback_hours))
    if series is None:
        series = liquidity_series_for(load_liquidity_journal(), ca,
                                      lookback_hours=lookback_hours, now=stamp)
    rows = sorted((row for row in (series or [])
                   if isinstance(row, dict) and _int(row.get("ts")) > 0),
                  key=lambda row: _int(row["ts"]))
    floor = stamp - lookback_hours * 3600
    rows = [row for row in rows if floor < _int(row["ts"]) <= stamp]
    liq_now = _num(rows[-1].get("liq_usd"), None) if rows else None
    if liq_now is None:
        liq_now = _num((market or {}).get("liquidity_usd"), None)
    threshold = (LIQ_SECOND_WAVE_MULT_LOW_VOL
                 if liq_now is not None and liq_now < LIQ_LOW_VOLUME_USD
                 else LIQ_SECOND_WAVE_MULT)
    out = {
        "detected": False, "first_add_usd": None, "second_add_usd": None,
        "mult": None, "best_mult": None, "time_diff_hours": None,
        "threshold": threshold, "waves": [], "observations": len(rows),
        "liq_usd": liq_now, "confidence": LIQ_MISSING_CONFIDENCE,
        "available": len(rows) >= 2, "note": "",
    }
    if len(rows) < 2:
        out["note"] = ("observasi likuiditas < 2 — journal baru terisi tiap "
                       "run screener; confidence dikunci 0,3")
        return out
    waves = liquidity_waves(rows)
    out["waves"] = waves
    best = _best_wave_pair(waves, lookback_hours)
    detected = best is not None and best["mult"] >= threshold
    out["confidence"] = _liq_confidence(detected, best, threshold, len(rows))
    if best is None:
        out["note"] = (f"{len(waves)} gelombang add teramati, tidak ada "
                       f"pasangan dalam {lookback_hours} jam")
        return out
    out["best_mult"] = round(best["mult"], 2)
    if not detected:
        out["note"] = (f"add terbesar {best['mult']:.1f}x — di bawah ambang "
                       f"{threshold:g}x")
        return out
    out.update({"detected": True, "mult": round(best["mult"], 2),
                "first_add_usd": round(best["first_add_usd"], 2),
                "second_add_usd": round(best["second_add_usd"], 2),
                "time_diff_hours": best["time_diff_hours"]})
    out["note"] = (f"add ${best['first_add_usd']:,.0f} → "
                   f"${best['second_add_usd']:,.0f} ({best['mult']:.1f}x) "
                   f"dalam {best['time_diff_hours']} jam")
    return out


# ---------------------------------------------------------------------------
# B. Holder consolidation
# ---------------------------------------------------------------------------
def _snapshot_from_status(token: dict | None) -> dict:
    """Titik "sekarang" dari snapshot holder (format ``holder_status``)."""
    token = token if isinstance(token, dict) else {}
    holders = token.get("holders") if isinstance(token.get("holders"),
                                                 dict) else {}
    mid = holders.get("mid") if isinstance(holders.get("mid"), dict) else {}
    return {
        "ts": _int(token.get("analyzed_at")),
        "dust_count": _int(holders.get("dust_count")),
        "real_count": _int(holders.get("real_count")),
        "real_pct_mc": _num(holders.get("real_pct_mc"), None),
        "dust_pct_mc": _num(holders.get("dust_pct_mc"), None),
        "mc": _num(token.get("marketcap"), None),
        "holder_count": _int(holders.get("wallets_analyzed")),
        "mid_count": _int(mid.get("count")),
        "mid_pct_mc": _num(mid.get("pct_mc"), None),
    }


def _snapshot_usable(point: dict | None) -> bool:
    """Snapshot holder punya isi (bukan hasil ``{}`` dari token tak discan).

    Tanpa guard ini token tanpa data holder akan dibandingkan dengan titik 24
    jam sebagai "dust sekarang = 0", dan selisih ``dust_count`` terbaca
    sebagai ribuan wallet keluar dari dust — sinyal palsu paling berbahaya di
    halaman ini.
    """
    point = point if isinstance(point, dict) else {}
    if _int(point.get("ts")) <= 0:
        return False
    return any(_int(point.get(key)) > 0
               for key in ("holder_count", "dust_count", "real_count"))


def _avg_bag_usd(point: dict | None) -> float | None:
    """Rata-rata nilai USD bag wallet **real** (> $10, bukan dust)."""
    point = point if isinstance(point, dict) else {}
    count = _int(point.get("real_count"))
    pct = _num(point.get("real_pct_mc"), None)
    mc = _num(point.get("mc"), None)
    if mc is None:
        mc = _num(point.get("marketcap"), None)
    if count <= 0 or pct is None or mc is None or mc <= 0:
        return None
    return (pct / 100.0 * mc) / count


def _pick_previous_point(points, target_ts: int,
                         tolerance_hours: int = CONSOL_STALE_TOLERANCE_HOURS
                         ) -> tuple[dict | None, bool]:
    """Titik terdekat ``target_ts``; ``(None, False)`` bila tidak ada titik."""
    rows = [row for row in (points or [])
            if isinstance(row, dict) and _int(row.get("ts")) > 0
            and _int(row.get("ts")) <= target_ts + 3600]
    if not rows:
        return None, False
    best = min(rows, key=lambda row: abs(_int(row["ts"]) - target_ts))
    stale = abs(_int(best["ts"]) - target_ts) > tolerance_hours * 3600
    return best, stale


def _dust_exits_from_chronology(intervals, from_ts: int, to_ts: int):
    """Jumlah wallet dust yang tumbuh keluar dari dust dalam window.

    ``holder_chronology`` sudah mengklasifikasikan ``dust_grew_out`` per
    interval (balance naik melewati batas dust) — itu ukuran "wallet keluar
    dari dust" yang sebenarnya, bukan selisih agregat. ``None`` bila tidak ada
    interval yang menumpang window.
    """
    total = 0
    matched = 0
    for interval in intervals or []:
        if not isinstance(interval, dict):
            continue
        start = _int(interval.get("from_ts"))
        end = _int(interval.get("to_ts"))
        if end <= from_ts or start >= to_ts:
            continue
        counts = interval.get("counts") if isinstance(
            interval.get("counts"), dict) else {}
        total += _int(counts.get("dust_grew_out"))
        matched += 1
    return total if matched else None


def consolidation_from_snapshots(current: dict | None, prev: dict | None, *,
                                 hours_ago: int = CONSOL_WINDOW_HOURS,
                                 now: int | None = None, intervals=None,
                                 stale: bool = False,
                                 days_active: float | None = None) -> dict:
    """Bandingkan snapshot holder sekarang vs ``hours_ago`` jam lalu.

    ``consolidating`` = ≥ ``CONSOL_MIN_WALLETS`` wallet keluar dari dust **dan**
    rata-rata bag real ≥ ``CONSOL_MIN_BAG_GROWTH`` kali. Fase ini dibaca
    sebagai akumulasi awal (chip pindah ke wallet lebih besar) sebelum pump.
    """
    stamp = _int(now) or _now()
    hours_ago = max(1, int(hours_ago))
    out = {
        "consolidating": False, "wallets_exited_dust": 0,
        "wallets_moved_out": 0, "avg_bag_growth_pct": None,
        "avg_bag_now_usd": None, "avg_bag_prev_usd": None,
        "dust_delta": None, "real_delta": None, "days_active": days_active,
        "hours_compared": None, "stale": bool(stale), "confidence": 0.0,
        "available": False, "source": "", "note": "",
    }
    if not _snapshot_usable(current) or _int((prev or {}).get("ts")) <= 0:
        out["note"] = "butuh 2 snapshot holder (sekarang + 24 jam lalu)"
        return out
    prev = prev if isinstance(prev, dict) else {}
    now_ts = _int(current.get("ts")) or stamp
    prev_ts = _int(prev.get("ts"))
    hours = _hours(now_ts - prev_ts)
    out.update({
        "available": True, "hours_compared": hours,
        "stale": bool(stale) or abs(hours - hours_ago)
        > CONSOL_STALE_TOLERANCE_HOURS,
    })

    prev_dust = _int(prev.get("dust_count"))
    now_dust = _int(current.get("dust_count"))
    out["dust_delta"] = now_dust - prev_dust
    out["real_delta"] = _int(current.get("real_count")) - _int(
        prev.get("real_count"))

    exits = _dust_exits_from_chronology(intervals,
                                        now_ts - hours_ago * 3600, now_ts)
    if exits is None:
        # Fallback agregat: dust menyusut = ada wallet yang naik kelas.
        exits = max(0, prev_dust - now_dust)
        out["source"] = "dust_count_delta"
    else:
        out["source"] = "chronology_dust_grew_out"
    out["wallets_exited_dust"] = int(exits)
    out["wallets_moved_out"] = int(exits)

    bag_now = _avg_bag_usd(current)
    bag_prev = _avg_bag_usd(prev)
    out["avg_bag_now_usd"] = round(bag_now, 2) if bag_now else None
    out["avg_bag_prev_usd"] = round(bag_prev, 2) if bag_prev else None
    growth = None
    if bag_now is not None and bag_prev not in (None, 0):
        growth = (bag_now / bag_prev - 1.0) * 100.0
        out["avg_bag_growth_pct"] = round(growth, 1)

    wallets_ok = out["wallets_exited_dust"] >= CONSOL_MIN_WALLETS
    growth_ok = growth is not None and (
        growth >= (CONSOL_MIN_BAG_GROWTH - 1.0) * 100.0)
    out["consolidating"] = bool(wallets_ok and growth_ok)

    if out["consolidating"]:
        confidence = (0.5 + 0.25 * _clamp(out["wallets_exited_dust"] / 15.0)
                      + 0.25 * _clamp((growth or 0.0) / 300.0))
    elif wallets_ok or growth_ok:
        confidence = (0.35 * _clamp(out["wallets_exited_dust"]
                                    / float(CONSOL_MIN_WALLETS))
                      + 0.15 * _clamp((growth or 0.0) / 100.0))
    else:
        confidence = 0.1 * _clamp(out["wallets_exited_dust"]
                                  / float(CONSOL_MIN_WALLETS))
    if out["stale"]:
        confidence *= 0.8
    out["confidence"] = round(_clamp(confidence), 3)
    note = f"{out['wallets_exited_dust']} wallet keluar dari dust"
    if growth is None:
        note += ", avg bag tidak bisa dihitung"
    else:
        note += f", avg bag {growth:+.0f}%"
    if out["stale"]:
        note += " · snapshot basi (tidak tepat 24 jam)"
    out["note"] = note
    return out


def detect_holder_consolidation(token_ca: str,
                                hours_ago: int = CONSOL_WINDOW_HOURS, *,
                                status_tokens: dict | None = None,
                                store: dict | None = None,
                                market: dict | None = None,
                                now: int | None = None) -> dict:
    """Sinyal B untuk satu token memakai ``holder_status`` + ``holder_history``.

    Snapshot "sekarang" diambil dari ``holder_status`` (cron hourly) atau
    ``latest_detail`` store; pembandingnya titik history terdekat 24 jam lalu.
    Bila titik 24 jam tidak ada, titik tertua dipakai dan hasil ditandai
    ``stale`` (spec 7: pakai data terbaik yang ada, jangan diam-diam).
    """
    stamp = _int(now) or _now()
    ca = str(token_ca or "").strip()
    hours_ago = max(1, int(hours_ago))
    tokens = status_tokens if isinstance(status_tokens, dict) else {}
    history = store if isinstance(store, dict) else {}
    slot = ((history.get("tokens") or {}).get(ca) or {})
    current = _snapshot_from_status(tokens.get(ca))
    if not _snapshot_usable(current):
        detail = slot.get("latest_detail") if isinstance(
            slot.get("latest_detail"), dict) else {}
        if detail:
            current = {
                "ts": _int(detail.get("ts")),
                "dust_count": _int(detail.get("dust_count")),
                "real_count": _int(detail.get("real_count")),
                "real_pct_mc": _num(detail.get("real_pct_mc"), None),
                "dust_pct_mc": _num(detail.get("dust_pct_mc"), None),
                "mc": _num(detail.get("marketcap"), None),
                "holder_count": _int(detail.get("holder_count")),
                "mid_count": _int(detail.get("mid_count")),
                "mid_pct_mc": _num(detail.get("mid_pct_mc"), None),
            }
    points = points_for_mint(ca, tokens, history)
    target = stamp - hours_ago * 3600
    prev, stale = _pick_previous_point(points, target)
    if prev is None and points:
        prev = min((row for row in points
                    if isinstance(row, dict) and _int(row.get("ts")) > 0),
                   key=lambda row: _int(row["ts"]), default=None)
        stale = True
    oldest = min((_int(row.get("ts")) for row in points
                  if isinstance(row, dict) and _int(row.get("ts")) > 0),
                 default=0)
    days_active = round((stamp - oldest) / 86400.0, 2) if oldest else None
    if days_active is None:
        created = _num((market or {}).get("pair_created_at"), None)
        if created and created > 1_000_000_000_000:  # milidetik
            days_active = round((stamp - created / 1000.0) / 86400.0, 2)
    chrono = slot.get("chronology") if isinstance(slot.get("chronology"),
                                                  dict) else {}
    intervals = chrono.get("intervals") if isinstance(
        chrono.get("intervals"), list) else []
    result = consolidation_from_snapshots(
        current, prev, hours_ago=hours_ago, now=stamp, intervals=intervals,
        stale=bool(stale), days_active=days_active)
    result["holder_count"] = _int(current.get("holder_count"))
    return result


# ---------------------------------------------------------------------------
# C. Volume profile — calm before storm
# ---------------------------------------------------------------------------
def volume_profile(hourly, *, now: int | None = None,
                   days: int = VOLUME_LOOKBACK_DAYS) -> dict:
    """Ringkasan volume dari candle hourly: rata-rata harian, 24 jam, 6 jam.

    ``available`` False berarti "tidak tahu" (history < ``VOLUME_MIN_HOURS``
    jam), bukan "tenang" — sama seperti ``calculate_volatility_metrics`` di
    ``holder_history``. ``vol_24h_prior`` adalah 24 jam yang berakhir 6 jam
    lalu (window tenang), ``vol_24h`` adalah 24 jam trailing.
    """
    rows = []
    for row in hourly or []:
        if not isinstance(row, dict):
            continue
        ts = _int(row.get("ts"))
        if ts <= 0:
            continue
        rows.append((ts, max(0.0, _num(row.get("volume_usd"), 0.0) or 0.0)))
    if not rows:
        return {"available": False, "candles": 0, "coverage_hours": 0}
    rows.sort(key=lambda item: item[0])
    stamp = _int(now) or rows[-1][0]
    days = max(1, int(days))
    baseline = [row for row in rows
                if stamp - days * 24 * 3600 < row[0] <= stamp]
    if len(baseline) > 1:
        span = (baseline[-1][0] - baseline[0][0]) // 3600 + 1
    else:
        span = 1
    coverage_hours = min(days * 24, span)
    out = {
        "available": coverage_hours >= min(VOLUME_MIN_HOURS, days * 24),
        "candles": len(rows), "coverage_hours": coverage_hours,
        "avg_daily_7d": None, "vol_24h": None, "vol_24h_prior": None,
        "vol_6h": None, "anchor_ts": stamp,
    }
    if not out["available"] or not baseline:
        return out
    total = sum(row[1] for row in baseline)
    covered_days = max(1.0, coverage_hours / 24.0)

    def _sum_between(start: int, end: int) -> float:
        return round(sum(row[1] for row in rows if start < row[0] <= end), 2)

    out["avg_daily_7d"] = round(total / covered_days, 2)
    out["vol_24h"] = _sum_between(stamp - 24 * 3600, stamp)
    out["vol_6h"] = _sum_between(stamp - VOLUME_6H_HOURS * 3600, stamp)
    # Window "tenang" = 24 jam SEBELUM window 6 jam terakhir. Lihat
    # detect_volume_anomaly: memakai 24 jam trailing membuat dua syarat
    # sinyal ini mustahil terpenuhi bersamaan.
    out["vol_24h_prior"] = _sum_between(stamp - (24 + VOLUME_6H_HOURS) * 3600,
                                        stamp - VOLUME_6H_HOURS * 3600)
    return out


def detect_volume_anomaly(token_ca: str,
                          lookback_days: int = VOLUME_LOOKBACK_DAYS, *,
                          hourly=None, market: dict | None = None,
                          now: int | None = None) -> dict:
    """Sinyal C: 24 jam tenang (≤ 30% rata-rata) lalu 6 jam melonjak.

    Dua penyesuaian terhadap blueprint, keduanya karena rumus aslinya tidak
    mungkin terpenuhi:

    1. **Window tenang = 24 jam sebelum window 6 jam**, bukan 24 jam
       trailing. Window 6 jam terakhir ada *di dalam* 24 jam trailing, jadi
       syarat ``vol_6h ≥ 2x baseline 6 jam`` (= 0,5x rata-rata harian) dan
       ``vol_24h ≤ 0,3x rata-rata harian`` tidak bisa benar bersamaan — sinyal
       tidak akan pernah menyala. Rasio 24 jam trailing tetap dilaporkan
       sebagai ``vol_ratio_24h_trailing``.
    2. ``VOLUME_SPIKE_BASE`` menentukan pembanding lonjakan 6 jam. Blueprint
       menulis ``vol_6h >= 2.0 * avg_7d`` dengan ``avg_7d`` = rata-rata
       **harian** (8x baseline 6 jam); default di sini ``"6h"`` (≥ 2x baseline
       6 jam). Ubah konstanta ke ``"daily"`` untuk membaca blueprint harfiah.
       Kedua rasio (``vol_ratio_6h_norm`` dan ``vol_ratio_6h``) tetap ada.
    """
    stamp = _int(now) or _now()
    ca = str(token_ca or "").strip()
    lookback_days = max(1, int(lookback_days))
    out = {
        "is_calm_before_storm": False, "is_calm": False, "is_spike": False,
        "vol_ratio_24h": None, "vol_ratio_24h_trailing": None,
        "vol_ratio_6h": None, "vol_ratio_6h_norm": None,
        "avg_daily_7d": None, "vol_24h": None, "vol_24h_prior": None,
        "vol_6h": None, "anomaly_strength": 0.0, "confidence": 0.0,
        "available": False, "coverage_hours": 0, "note": "",
    }
    if hourly is None:
        pools = _pair_addresses(market)
        if not pools:
            try:
                pools = _pair_addresses(get_market(ca))
            except Exception:  # noqa: BLE001 - pasar tidak boleh fatal
                pools = []
        hourly = (get_hourly_candles(pools[0],
                                     limit_hours=lookback_days * 24 + 24)
                  if pools else [])
    profile = volume_profile(hourly, now=stamp, days=lookback_days)
    out["coverage_hours"] = _int(profile.get("coverage_hours"))
    avg_daily = _num(profile.get("avg_daily_7d"), None)
    vol_24h = _num(profile.get("vol_24h"), None)
    vol_24h_prior = _num(profile.get("vol_24h_prior"), None)
    vol_6h = _num(profile.get("vol_6h"), None)
    out.update({"avg_daily_7d": avg_daily, "vol_24h": vol_24h,
                "vol_24h_prior": vol_24h_prior, "vol_6h": vol_6h})
    if not profile.get("available") or not avg_daily:
        out["note"] = (f"history < {VOLUME_MIN_HOURS} jam — sinyal volume "
                       "dilewati (spec 7)")
        return out
    out["available"] = True
    ratio_24 = (vol_24h_prior or 0.0) / avg_daily
    ratio_24_trailing = (vol_24h or 0.0) / avg_daily
    ratio_6_daily = (vol_6h or 0.0) / avg_daily
    base_6h = avg_daily * VOLUME_6H_HOURS / 24.0
    ratio_6_norm = ((vol_6h or 0.0) / base_6h) if base_6h > 0 else 0.0
    out.update({"vol_ratio_24h": round(ratio_24, 3),
                "vol_ratio_24h_trailing": round(ratio_24_trailing, 3),
                "vol_ratio_6h": round(ratio_6_daily, 3),
                "vol_ratio_6h_norm": round(ratio_6_norm, 3)})
    is_calm = ratio_24 <= VOLUME_CALM_RATIO
    spike_ratio = ratio_6_norm if VOLUME_SPIKE_BASE == "6h" else ratio_6_daily
    is_spike = spike_ratio >= VOLUME_SPIKE_RATIO
    calm_component = (_clamp((VOLUME_CALM_RATIO - ratio_24) / VOLUME_CALM_RATIO)
                      if is_calm else 0.0)
    spike_component = _clamp((spike_ratio - VOLUME_SPIKE_RATIO)
                             / VOLUME_SPIKE_RATIO)
    strength = _clamp(0.45 * calm_component + 0.55 * spike_component)
    out.update({"is_calm": bool(is_calm), "is_spike": bool(is_spike),
                "is_calm_before_storm": bool(is_calm and is_spike),
                "anomaly_strength": round(strength, 3)})
    out["confidence"] = round(_clamp(
        strength if out["is_calm_before_storm"] else 0.35 * strength), 3)
    out["note"] = (f"24 jam pra-spike {ratio_24 * 100:.0f}% rata-rata"
                   f"{' (tenang)' if is_calm else ''}, 6 jam terakhir "
                   f"{spike_ratio:.1f}x baseline"
                   f"{' (spike)' if is_spike else ''}")
    return out


# ---------------------------------------------------------------------------
# D. TX velocity
# ---------------------------------------------------------------------------
def _swap_ts(swap) -> int:
    """Timestamp swap Helius (tuple) atau dict ``{ts: ...}``."""
    if isinstance(swap, (list, tuple)):
        return _int(swap[2]) if len(swap) > 2 else 0
    if isinstance(swap, dict):
        return _int(swap.get("ts"))
    return 0


def _swap_side(swap) -> str:
    if isinstance(swap, (list, tuple)):
        return str(swap[0] or "") if swap else ""
    if isinstance(swap, dict):
        return str(swap.get("side") or "")
    return ""


def tx_buckets(swaps, *, now: int | None = None,
               hours: int = VELOCITY_LOOKBACK_HOURS) -> list[int]:
    """Jumlah swap per jam (urutan lama → baru) untuk ``hours`` jam terakhir."""
    stamp = _int(now) or _now()
    hours = max(2, int(hours))
    buckets = [0] * hours
    for swap in swaps or []:
        ts = _swap_ts(swap)
        if ts <= 0:
            continue
        age_hours = (stamp - ts) // 3600
        if 0 <= age_hours < hours:
            buckets[hours - 1 - int(age_hours)] += 1
    return buckets


def velocity_from_buckets(buckets) -> dict:
    """Akselerasi: rata-rata 2 jam terakhir vs 2 jam pertama.

    ``velocity = (latest_2h_avg - first_2h_avg) / first_2h_avg``. Dari 0
    transaksi menjadi ada aktivitas dilaporkan ``inf`` (akselerasi tak
    terhingga), bukan dibagi nol.
    """
    rows = [max(0, _int(value)) for value in (buckets or [])]
    out = {"tx_count_by_hour": rows, "first_2h_avg": None, "latest_2h_avg": None,
           "velocity": None, "total_tx": sum(rows)}
    if len(rows) < 4:
        return out
    first = sum(rows[:2]) / 2.0
    latest = sum(rows[-2:]) / 2.0
    out["first_2h_avg"] = round(first, 2)
    out["latest_2h_avg"] = round(latest, 2)
    if first > 0:
        out["velocity"] = round((latest - first) / first, 3)
    elif latest > 0:
        out["velocity"] = float("inf")
    return out


def velocity_from_txns(txns: dict | None) -> dict:
    """Fallback tanpa Helius: agregat ``txns`` DexScreener (m5/h1/h6/h24).

    DexScreener hanya memberi agregat, jadi dua jam pertama diaproksimasi
    rata-rata per jam dari ``h6 - h1`` dan dua jam terakhir dari ``h1``. Hasil
    ditandai ``source=dexscreener_txns`` dan confidence-nya dibatasi
    ``VELOCITY_SOURCE_CONFIDENCE``.
    """
    txns = txns if isinstance(txns, dict) else {}

    def _count(window: str):
        bucket = txns.get(window)
        if not isinstance(bucket, dict):
            return None
        buys = _num(bucket.get("buys"), None)
        sells = _num(bucket.get("sells"), None)
        if buys is None and sells is None:
            return None
        return int((buys or 0) + (sells or 0))

    out = {"tx_count_by_hour": [], "first_2h_avg": None, "latest_2h_avg": None,
           "velocity": None, "total_tx": None, "buys": None, "sells": None}
    h1 = _count("h1")
    if h1 is None:
        return out
    h6 = _count("h6")
    older = max(0, (h6 or 0) - h1)
    per_hour = older / 5.0 if h6 is not None else None
    out["first_2h_avg"] = round(per_hour, 2) if per_hour is not None else None
    out["latest_2h_avg"] = float(h1)
    out["total_tx"] = int(h6 if h6 is not None else h1)
    if per_hour is not None:
        if per_hour > 0:
            out["velocity"] = round((h1 - per_hour) / per_hour, 3)
        elif h1 > 0:
            out["velocity"] = float("inf")
    bucket = txns.get("h1") if isinstance(txns.get("h1"), dict) else {}
    out["buys"] = _int(bucket.get("buys")) or None
    out["sells"] = _int(bucket.get("sells")) or None
    return out


def _fetch_swaps(ca: str, *, market: dict | None = None, pool: str | None = None,
                 api_key=None, lookback_hours: int = VELOCITY_LOOKBACK_HOURS
                 ) -> tuple[list | None, str]:
    """Ambil swap Helius untuk window velocity.

    ``(None, "")`` = tidak bisa fetch (tanpa key / tanpa pool / error) →
    pemanggil jatuh ke agregat DexScreener. ``([], "helius_swaps")`` = fetch
    berhasil tetapi memang tidak ada swap.
    """
    if not ca:
        return None, ""
    keys = api_key if isinstance(api_key, (list, tuple)) else (
        [api_key] if api_key else [])
    if not keys:
        try:
            keys = get_helius_keys()
        except Exception:  # noqa: BLE001 - tanpa key → fallback DexScreener
            keys = []
    if not keys:
        return None, ""
    address = str(pool or "").strip()
    if not address:
        pools = _pair_addresses(market)
        address = pools[0] if pools else ""
    if not address:
        try:
            pools = _pair_addresses(get_market(ca))
            address = pools[0] if pools else ""
        except Exception:  # noqa: BLE001 - pasar tidak boleh menggagalkan scan
            address = ""
    if not address:
        return None, ""
    try:
        from cvd import fetch_swaps
        swaps, _sig, _ts, _hit = fetch_swaps(
            keys[0], address, ca,
            stop_ts=_now() - max(2, int(lookback_hours)) * 3600,
            max_pages=VELOCITY_MAX_PAGES, sleep=0.05)
    except Exception:  # noqa: BLE001 - Helius gagal → fallback DexScreener
        return None, ""
    return list(swaps or []), "helius_swaps"


def detect_tx_velocity_spike(token_ca: str,
                             lookback_hours: int = VELOCITY_LOOKBACK_HOURS, *,
                             swaps=None, market: dict | None = None,
                             txns: dict | None = None, pool: str | None = None,
                             api_key=None, now: int | None = None) -> dict:
    """Sinyal D: akselerasi jumlah transaksi + tekanan beli.

    Sumber utama swap Helius (``cvd.fetch_swaps``, key pool Helius yang sudah
    dipakai halaman CVD). Tanpa key Helius — atau bila fetch gagal — dipakai
    agregat ``txns`` DexScreener dari ``get_market`` supaya sinyal tetap ada,
    dengan confidence dibatasi ``VELOCITY_SOURCE_CONFIDENCE``.

    Blueprint menulis ``velocity >= 1.5`` lalu menyebutnya "50%+"; rumus
    ``(latest - first) / first`` dengan ambang 1,5 berarti **+150%**. Angka
    1,5 yang dipakai (lihat ``VELOCITY_MIN``) dan ``velocity_pct`` melaporkan
    persentase sebenarnya.
    """
    stamp = _int(now) or _now()
    ca = str(token_ca or "").strip()
    lookback_hours = max(2, int(lookback_hours))
    out = {
        "accelerating": False, "whale_accumulation": False, "velocity": None,
        "velocity_pct": None, "buy_pressure": None, "tx_count_by_hour": [],
        "total_tx": 0, "buys": 0, "sells": 0,
        "tx_velocity_confidence": 0.0, "source": "", "available": False,
        "note": "",
    }
    source = ""
    if swaps is None and txns is None:
        swaps, source = _fetch_swaps(ca, market=market, pool=pool,
                                     api_key=api_key,
                                     lookback_hours=lookback_hours)
    if swaps is not None:
        source = source or "helius_swaps"
        rows = [swap for swap in swaps
                if stamp - lookback_hours * 3600 < _swap_ts(swap) <= stamp]
        buys = sum(1 for swap in rows if _swap_side(swap) == "buy")
        sells = sum(1 for swap in rows if _swap_side(swap) == "sell")
        velocity = velocity_from_buckets(tx_buckets(rows, now=stamp,
                                                    hours=lookback_hours))
        total = len(rows)
        out.update({"tx_count_by_hour": velocity["tx_count_by_hour"],
                    "total_tx": total, "buys": buys, "sells": sells,
                    "velocity": velocity["velocity"],
                    "buy_pressure": round(buys / total, 3) if total else None,
                    "available": total > 0})
    else:
        source = "dexscreener_txns"
        dex = txns if isinstance(txns, dict) else (market or {}).get("txns")
        velocity = velocity_from_txns(dex)
        buys = _int(velocity.get("buys"))
        sells = _int(velocity.get("sells"))
        total = buys + sells
        total_tx = _int(velocity.get("total_tx"))
        out.update({"tx_count_by_hour": velocity["tx_count_by_hour"],
                    "total_tx": total_tx,
                    "buys": buys, "sells": sells,
                    "velocity": velocity.get("velocity"),
                    "buy_pressure": round(buys / total, 3) if total else None,
                    "available": total_tx > 0})
    out["source"] = source
    if not out["available"]:
        out["note"] = f"tidak ada data transaksi {lookback_hours} jam terakhir"
        return out

    raw = out["velocity"]
    infinite = raw == float("inf")
    velocity = None if raw is None else (float("inf") if infinite
                                         else _num(raw, None))
    accelerating = velocity is not None and velocity >= VELOCITY_MIN
    pressure = _num(out["buy_pressure"], None)
    whale = pressure is not None and pressure >= BUY_PRESSURE_MIN
    out.update({
        "accelerating": bool(accelerating),
        "whale_accumulation": bool(whale),
        "velocity_pct": (None if velocity is None or infinite
                         else round(velocity * 100.0, 1)),
    })
    size = _clamp(out["total_tx"] / float(max(VELOCITY_MIN_TX, 1) * 3))
    source_cap = VELOCITY_SOURCE_CONFIDENCE.get(source, 0.5)
    if accelerating:
        confidence = (0.5 + 0.25 * size
                      + (0.25 if whale else 0.1 * _clamp(pressure or 0.0)))
    elif whale:
        confidence = 0.3 + 0.15 * size
    else:
        confidence = 0.1 * size
    out["tx_velocity_confidence"] = round(_clamp(confidence * source_cap), 3)
    speed = "∞" if infinite else f"{(velocity or 0.0) * 100.0:+.0f}%"
    out["note"] = (f"{out['total_tx']} tx {lookback_hours} jam · {speed} "
                   f"akselerasi · {int((pressure or 0.0) * 100)}% buy")
    return out


# ---------------------------------------------------------------------------
# Skor
# ---------------------------------------------------------------------------
def calculate_pump_score(liq_conf, consol_conf, vol_conf, vel_conf) -> float:
    """Rata-rata berbobot 4 confidence (masing-masing 0,25) → skala 0–10."""
    parts = (_clamp(liq_conf), _clamp(consol_conf), _clamp(vol_conf),
             _clamp(vel_conf))
    return round(sum(SIGNAL_WEIGHT * part for part in parts) * 10.0, 2)


def signal_confidences(signals: dict | None) -> dict:
    """Confidence tiap sinyal dari dict hasil ``analyze_token_signals``."""
    signals = signals if isinstance(signals, dict) else {}
    inner = signals.get("signals") if isinstance(signals.get("signals"),
                                                 dict) else signals

    def _get(key: str, field: str) -> float:
        block = inner.get(key) if isinstance(inner.get(key), dict) else {}
        return _clamp(block.get(field))

    return {"liq": _get("liq", "confidence"),
            "consol": _get("consol", "confidence"),
            "vol": _get("vol", "confidence"),
            "vel": _get("vel", "tx_velocity_confidence")}


def active_signals(signals: dict | None) -> list[str]:
    """Sinyal yang flag deteksinya menyala."""
    signals = signals if isinstance(signals, dict) else {}
    inner = signals.get("signals") if isinstance(signals.get("signals"),
                                                 dict) else signals
    flags = {"liq": "detected", "consol": "consolidating",
             "vol": "is_calm_before_storm", "vel": "accelerating"}
    active = []
    for key in SIGNAL_KEYS:
        block = inner.get(key) if isinstance(inner.get(key), dict) else {}
        if block.get(flags[key]):
            active.append(key)
    return active


def summarize(signals: dict | None) -> dict:
    """PUMP SCORE + jumlah sinyal aktif + confidence rata-rata sinyal aktif.

    ``confidence_pct`` = rata-rata confidence sinyal **aktif** saja (spec 4):
    token tanpa sinyal aktif dibaca 0%, bukan rata-rata confidence pasif.
    """
    confidences = signal_confidences(signals)
    active = active_signals(signals)
    score = calculate_pump_score(*[confidences[key] for key in SIGNAL_KEYS])
    confidence_pct = (round(sum(confidences[key] for key in active)
                            / len(active) * 100.0) if active else 0)
    return {"score": score, "active": active, "active_count": len(active),
            "confidence_pct": confidence_pct, "confidences": confidences,
            "alpha_window": estimate_alpha_window(score, active, signals)}


def estimate_alpha_window(score: float, active,
                          signals: dict | None = None) -> str:
    """Perkiraan window entry dari skor + apakah akselerasi sudah jalan."""
    signals = signals if isinstance(signals, dict) else {}
    inner = signals.get("signals") if isinstance(signals.get("signals"),
                                                 dict) else signals
    vel = inner.get("vel") if isinstance(inner.get("vel"), dict) else {}
    count = len(active or [])
    if count >= 3 and score >= 6.5 and vel.get("accelerating"):
        return "0–2 jam (akselerasi sudah jalan)"
    if count >= 3 and score >= 6.5:
        return "2–6 jam"
    if score >= 5.0:
        return "6–24 jam"
    if score >= 3.0:
        return "1–3 hari (setup awal)"
    return "belum ada window"


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
def analyze_token_signals(ca: str, meta: dict | None = None, *,
                          status_tokens: dict | None = None,
                          store: dict | None = None,
                          market: dict | None = None, api_key=None,
                          now: int | None = None) -> dict:
    """Jalankan 4 sinyal untuk satu token + hitung PUMP SCORE.

    Tiap sinyal dibungkus try/except: satu sumber yang rusak tidak boleh
    mematikan kartu token (dan tidak boleh menaikkan skor diam-diam).
    """
    stamp = _int(now) or _now()
    meta = meta if isinstance(meta, dict) else {}
    symbol = str(meta.get("symbol") or "?")
    market_data = market if isinstance(market, dict) and market else {}
    if not market_data:
        try:
            market_data = get_market(ca) or {}
        except Exception:  # noqa: BLE001 - pasar tidak boleh menggagalkan scan
            market_data = {}
    try:
        liq = detect_liquidity_add_pattern(ca, market=market_data, now=stamp)
    except Exception as exc:  # noqa: BLE001
        liq = {"detected": False, "confidence": LIQ_MISSING_CONFIDENCE,
               "note": f"error: {exc}"}
    try:
        consol = detect_holder_consolidation(ca, status_tokens=status_tokens,
                                             store=store, market=market_data,
                                             now=stamp)
    except Exception as exc:  # noqa: BLE001
        consol = {"consolidating": False, "confidence": 0.0, "note": str(exc)}
    try:
        vol = detect_volume_anomaly(ca, market=market_data, now=stamp)
    except Exception as exc:  # noqa: BLE001
        vol = {"is_calm_before_storm": False, "confidence": 0.0,
               "note": str(exc)}
    try:
        vel = detect_tx_velocity_spike(ca, market=market_data, api_key=api_key,
                                       now=stamp)
    except Exception as exc:  # noqa: BLE001
        vel = {"accelerating": False, "tx_velocity_confidence": 0.0,
               "note": str(exc)}
    signals = {"liq": liq, "consol": consol, "vol": vol, "vel": vel}
    result = {"ca": ca, "symbol": symbol, "market": market_data,
              "signals": signals, "analyzed_at": stamp}
    result.update(summarize(signals))
    return result


def run_screen(watchlist: dict | None = None, *,
               status_tokens: dict | None = None, store: dict | None = None,
               api_key=None, now: int | None = None, progress=None,
               max_tokens: int | None = DEFAULT_MAX_TOKENS,
               workers: int = 6, record_liq: bool = True) -> list[dict]:
    """Scan token degen → daftar hasil terurut PUMP SCORE menurun.

    Likuiditas DexScreener dicatat ke journal **sebelum** sinyal dibaca supaya
    token baru langsung punya titik pertama; pola dua gelombang baru terbaca
    setelah beberapa run (tiap 5 menit). ``max_tokens=0`` = seluruh watchlist
    degen (68 token × DexScreener + candle 7 hari + swap Helius = berat).
    """
    stamp = _int(now) or _now()
    degen = load_degen_watchlist(watchlist)
    ordered = sorted(degen.items(),
                     key=lambda item: (str((item[1] or {}).get("added") or ""),
                                       str((item[1] or {}).get("symbol") or "")),
                     reverse=True)
    if max_tokens and int(max_tokens) > 0:
        ordered = ordered[:int(max_tokens)]
    if not ordered:
        return []

    def _market(ca: str) -> dict:
        try:
            return get_market(ca) or {}
        except Exception:  # noqa: BLE001 - pasar tidak boleh menggagalkan scan
            return {}

    if workers and int(workers) > 1 and len(ordered) > 1:
        with ThreadPoolExecutor(max_workers=int(workers)) as pool:
            fetched = list(pool.map(lambda item: _market(item[0]),
                                    [ca for ca, _meta in ordered]))
    else:
        fetched = [_market(ca) for ca, _meta in ordered]
    markets = {ca: market for (ca, _meta), market in zip(ordered, fetched)}
    if record_liq:
        record_liquidity_observations(
            [{"ca": ca,
              "liq_usd": _num((markets.get(ca) or {}).get("liquidity_usd"),
                              None),
              "mc": _num((markets.get(ca) or {}).get("marketcap"), None),
              "pool": (_pair_addresses(markets.get(ca)) or [""])[0]}
             for ca, _meta in ordered], now=stamp)
    keys = api_key
    if keys is None:
        try:
            keys = get_helius_keys()
        except Exception:  # noqa: BLE001 - tanpa key → fallback DexScreener
            keys = []
    results: list[dict] = []
    for index, (ca, meta) in enumerate(ordered):
        symbol = str((meta or {}).get("symbol") or "?")
        if progress:
            progress(index + 1, len(ordered), symbol)
        results.append(analyze_token_signals(
            ca, meta, status_tokens=status_tokens, store=store,
            market=markets.get(ca) or {}, api_key=keys, now=stamp))
    results.sort(key=lambda row: (-_num(row.get("score"), 0.0),
                                  str(row.get("symbol") or "").upper()))
    return results


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.markdown("""
<style>
.pp-head {display:flex;flex-wrap:wrap;align-items:baseline;gap:.55rem;}
.pp-symbol {font-size:1.15rem;font-weight:800;color:#000000;}
.pp-mint {font-size:.72rem;font-family:monospace;color:#000000;}
.pp-meta {font-size:.78rem;color:#000000;margin:.25rem 0 .5rem;}
.pp-signals {font-size:.8rem;color:#000000;line-height:1.7;
 font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;}
.pp-score {font-size:.92rem;font-weight:800;color:#000000;margin-top:.35rem;}
.pp-sub {font-size:.75rem;color:#000000;margin-top:.1rem;}
.pp-window {font-size:.8rem;font-weight:700;color:#1d4ed8;margin-top:.2rem;}
</style>
""", unsafe_allow_html=True)


def _compact_usd(value) -> str:
    number = _num(value, None)
    if number is None:
        return "—"
    if number >= 1_000_000:
        return f"${number / 1_000_000:.2f}M"
    if number >= 1_000:
        return f"${number / 1_000:.1f}K"
    return f"${number:,.0f}"


def _price(value) -> str:
    number = _num(value, None)
    if number is None:
        return "—"
    if number >= 1:
        return f"${number:,.4f}"
    if number >= 0.0001:
        return f"${number:.6f}"
    return f"${number:.10f}".rstrip("0")


def _count(value) -> str:
    number = _num(value, None)
    if number is None:
        return "—"
    if number >= 1_000:
        return f"{number / 1_000:.1f}k"
    return f"{int(number)}"


def _liq_line(liq: dict) -> str:
    liq = liq if isinstance(liq, dict) else {}
    mult = _num(liq.get("mult"), None)
    if liq.get("detected") and mult is not None:
        icon = "✅"
        detail = (f"{mult:.1f}x detected  "
                  f"({_compact_usd(liq.get('first_add_usd'))} → "
                  f"{_compact_usd(liq.get('second_add_usd'))})")
    elif not liq.get("available"):
        icon = "❔"
        detail = "data likuiditas belum cukup (journal terisi tiap run)"
    else:
        icon = "•"
        best = _num(liq.get("best_mult"), None)
        if best is None:
            detail = (f"{_int(len(liq.get('waves')))} wave, belum ada pasangan "
                      "add")
        else:
            detail = (f"{len(liq.get('waves') or [])} wave, terbesar "
                      f"{best:.1f}x (ambang "
                      f"{_num(liq.get('threshold'), LIQ_SECOND_WAVE_MULT):g}x)")
    return f"{icon} Liquidity Wave:       {detail}"


def _consol_line(consol: dict) -> str:
    consol = consol if isinstance(consol, dict) else {}
    growth = _num(consol.get("avg_bag_growth_pct"), None)
    growth_txt = "n/a avg bag" if growth is None else f"{growth:+.0f}% avg bag"
    if consol.get("consolidating"):
        icon = "⚠️"
    elif consol.get("available"):
        icon = "•"
    else:
        icon = "❔"
    stale = " · stale" if consol.get("stale") else ""
    return (f"{icon} Holder Consolidation: "
            f"{_int(consol.get('wallets_moved_out'))} wallets out "
            f"({growth_txt}){stale}")


def _vol_line(vol: dict) -> str:
    vol = vol if isinstance(vol, dict) else {}
    if not vol.get("available"):
        return "❔ Volume Spike:          tidak ada history 7 hari"
    ratio_24 = _num(vol.get("vol_ratio_24h"), None)
    ratio_6 = _num(vol.get("vol_ratio_6h_norm"), None)
    if vol.get("is_calm_before_storm"):
        icon = "🔥"
    elif vol.get("is_calm") or vol.get("is_spike"):
        icon = "•"
    else:
        icon = "—"
    state = "Calm" if vol.get("is_calm") else "Normal"
    pct = "n/a" if ratio_24 is None else f"{ratio_24 * 100:.0f}% of avg"
    spike = "" if ratio_6 is None else f" → 6h {ratio_6:.1f}x"
    return f"{icon} Volume Spike:         {state} ({pct} 24h pra-spike){spike}"


def _vel_line(vel: dict) -> str:
    vel = vel if isinstance(vel, dict) else {}
    if not vel.get("available"):
        return "❔ TX Velocity:           tidak ada data tx"
    pct = _num(vel.get("velocity_pct"), None)
    pressure = _num(vel.get("buy_pressure"), None)
    icon = "📊" if vel.get("accelerating") else "—"
    if vel.get("velocity") == float("inf"):
        speed = "∞ (dari 0 tx)"
    elif pct is None:
        speed = "n/a"
    else:
        speed = f"{pct:+.0f}% last 6h"
    buys = "n/a buys" if pressure is None else f"{pressure * 100:.0f}% buys"
    whale = " · whale" if vel.get("whale_accumulation") else ""
    return f"{icon} TX Velocity:          {speed}   ({buys}){whale}"


def _navigate(page: str, ca: str) -> None:
    st.session_state["effort_mint"] = ca
    st.switch_page(page, query_params={"mint": ca})


def render_token_card(token_ca: str, symbol: str, signals: dict) -> None:
    """Satu kartu token: 4 sinyal + PUMP SCORE + shortcut Chart/Holders/CVD.

    ``signals`` = dict hasil :func:`analyze_token_signals` (``market``,
    ``signals``, ``score``, ``active_count``, ``confidence_pct``,
    ``alpha_window``); dict sinyal yang rata (tanpa key ``signals``) juga
    diterima. Key yang hilang dirender "—" supaya kartu tidak pernah melempar.
    """
    ca = str(token_ca or "")
    signals = signals if isinstance(signals, dict) else {}
    market = signals.get("market") if isinstance(signals.get("market"),
                                                 dict) else {}
    inner = signals.get("signals") if isinstance(signals.get("signals"),
                                                 dict) else signals

    def _block(key: str) -> dict:
        return inner.get(key) if isinstance(inner.get(key), dict) else {}

    liq, consol = _block("liq"), _block("consol")
    vol, vel = _block("vol"), _block("vel")
    score = _num(signals.get("score"), 0.0)
    lines = [_liq_line(liq), _consol_line(consol), _vol_line(vol),
             _vel_line(vel)]
    holders = _int(consol.get("holder_count"))
    with st.container(border=True):
        st.markdown(
            '<div class="pp-head">'
            '<span class="pp-symbol">$'
            f"{_html.escape(str(symbol or '?').upper())}</span>"
            f'<span class="pp-mint">CA: {_html.escape(ca[:8])}…'
            f"{_html.escape(ca[-6:]) if len(ca) > 14 else ''}</span>"
            "</div>"
            '<div class="pp-meta">'
            f"Price: {_price(market.get('price_usd'))} | "
            f"MC: {_compact_usd(market.get('marketcap'))} | "
            f"Liq: {_compact_usd(market.get('liquidity_usd'))} | "
            f"Holders: {_count(holders) if holders else '—'}"
            "</div>"
            f'<div class="pp-signals">{_html.escape(chr(10).join(lines))}</div>'
            f'<div class="pp-score">PUMP SCORE: {score:.1f}/10</div>'
            '<div class="pp-sub">'
            f"SIGNALS: {_int(signals.get('active_count'))}/4 active  |  "
            f"Confidence: {_int(signals.get('confidence_pct'))}%"
            "</div>"
            '<div class="pp-window">EST. ALPHA WINDOW: '
            f"{_html.escape(str(signals.get('alpha_window') or '—'))}</div>",
            unsafe_allow_html=True)
        st.progress(_clamp(score / 10.0), text=f"Pump score {score:.1f}/10")
        cols = st.columns([1, 1, 1, 3])
        cols[0].link_button("🔗 Chart", dexscreener_token_url(ca),
                            key=f"pp-chart-{ca}", use_container_width=True)
        if cols[1].button("👥 Holders", key=f"pp-holders-{ca}",
                          use_container_width=True):
            _navigate(HOLDER_PAGE_PATH, ca)
        if cols[2].button("📈 CVD", key=f"pp-cvd-{ca}",
                          use_container_width=True):
            _navigate(CVD_PAGE_PATH, ca)
        cols[3].markdown(
            '<div style="font-size:.7rem;padding-top:.45rem;">'
            f"{external_links_html(ca)}</div>", unsafe_allow_html=True)


@st.fragment(run_every=REFRESH_SEC)
def _auto_refresh(*, enabled: bool, last_ts: int, has_results: bool,
                  seconds: int = REFRESH_SEC) -> None:
    """Rerun penuh tiap ``seconds`` detik setelah scan terakhir.

    Blueprint meminta ``while True: ... time.sleep(300)`` di akhir script.
    Streamlit menjalankan ulang seluruh script per interaksi, jadi loop seperti
    itu tidak pernah kembali: UI membeku dan hasil scan tidak pernah dirender.
    ``st.fragment(run_every=…)`` memberi efek yang sama (refresh 5 menit) tanpa
    memblokir thread script.

    Guard ``age >= seconds`` wajib: fragment ini ikut dieksekusi pada rerun
    penuh, jadi tanpa guard ia akan memanggil ``st.rerun`` terus-menerus.
    """
    if not enabled:
        st.caption(f"Auto-refresh mati · interval {seconds // 60} menit.")
        return
    age = _now() - _int(last_ts)
    if not has_results:
        st.caption("Auto-refresh aktif · jalankan scan pertama dulu.")
        return
    if age >= seconds:
        st.session_state[DUE_KEY] = True
        st.rerun(scope="app")
        return
    left = max(0, seconds - age)
    st.caption(f"Auto-refresh tiap {seconds // 60} menit · scan berikutnya "
               f"±{left // 60} menit {left % 60:02d} detik lagi.")


def _cached_results() -> dict:
    cached = st.session_state.get(RESULTS_KEY)
    return cached if isinstance(cached, dict) else {}


def _scan(watchlist: dict | None, status_tokens: dict | None,
          store: dict | None, *, max_tokens: int | None) -> None:
    """Jalankan scan dengan progress bar lalu simpan ke session state."""
    bar = st.progress(0.0, text="Menyiapkan scan…")

    def _progress(done: int, total: int, symbol: str) -> None:
        bar.progress(min(1.0, done / max(total, 1)),
                     text=f"Scan {done}/{total} · {symbol}")

    try:
        results = run_screen(watchlist, status_tokens=status_tokens,
                             store=store, progress=_progress,
                             max_tokens=max_tokens)
        payload = {"results": results, "ts": _now(), "error": "",
                   "max_tokens": _int(max_tokens)}
    except Exception as exc:  # noqa: BLE001 - satu token rusak ≠ scan mati
        payload = {"results": [], "ts": _now(), "error": str(exc),
                   "max_tokens": _int(max_tokens)}
    finally:
        bar.empty()
    st.session_state[RESULTS_KEY] = payload


def main(*, configure_page: bool = True, watchlist: dict | None = None,
         status_tokens: dict | None = None, store: dict | None = None) -> None:
    """Halaman/section 🚀 Pre-Pump Screener.

    ``configure_page=False`` dipakai ``app.py`` (``st.set_page_config`` hanya
    boleh dipanggil sekali per halaman). Data holder boleh disuntikkan supaya
    dashboard tidak menarik ``holder_status`` / store durable dua kali.
    """
    if configure_page:
        st.set_page_config(page_title="Pre-Pump Screener", page_icon="🚀",
                           layout="wide", initial_sidebar_state="collapsed")
        st.title("🚀 Pre-Pump Screener")
    else:
        st.divider()
        st.subheader("🚀 Pre-Pump Screener")
    st.caption(
        "Empat sinyal on-chain untuk token watchlist **source=degen**: "
        f"gelombang add likuiditas ({LIQ_LOOKBACK_HOURS} jam), konsolidasi "
        f"holder ({CONSOL_WINDOW_HOURS} jam), volume calm-before-storm "
        f"({VOLUME_LOOKBACK_DAYS} hari), dan akselerasi transaksi "
        f"({VELOCITY_LOOKBACK_HOURS} jam). PUMP SCORE = rata-rata berbobot "
        "empat confidence (0–10). **Bukan saran beli** — baca bersama dust "
        "% MC di watchlist.")

    if watchlist is None:
        watchlist = load_watchlist()
    degen = load_degen_watchlist(watchlist)
    if status_tokens is None:
        status_tokens = load_holder_status().get("tokens") or {}
    if store is None:
        store = load_durable_holder_history()
    if not degen:
        st.info("Tidak ada token watchlist dengan `source=degen`. Tambahkan "
                "token lewat **🔥 Scan Degen** di bawah (Add All memakai "
                "source degen).")
        return

    controls = st.columns([1.3, 1.5, 1.2])
    with controls[0].form("pre-pump-controls", clear_on_submit=False):
        limit = st.number_input(
            "Token per scan (0 = semua)", min_value=0, max_value=len(degen),
            value=min(DEFAULT_MAX_TOKENS, len(degen)), step=6, key="pp-limit",
            help="Setiap token menarik DexScreener + candle 7 hari + swap "
                 "Helius. Mulai kecil dulu, naikkan bila responsif.")
        submit = st.form_submit_button("🚀 Jalankan Pre-Pump Scan",
                                       type="primary", use_container_width=True)
    auto = controls[1].toggle(
        f"Auto-refresh {REFRESH_SEC // 60} menit", value=False, key="pp-auto",
        help="Rerun otomatis lewat st.fragment(run_every=…). Hasil di-cache di "
             "session state, jadi rerun biasa tidak menarik API lagi.")
    controls[2].metric("Token degen", f"{len(degen)}")

    cached = _cached_results()
    due = bool(st.session_state.pop(DUE_KEY, False))
    if submit:
        _scan(watchlist, status_tokens, store, max_tokens=int(limit))
        cached = _cached_results()
    elif due and cached.get("results"):
        # Auto-refresh memakai batas token scan sebelumnya, bukan "semua".
        _scan(watchlist, status_tokens, store,
              max_tokens=_int(cached.get("max_tokens")))
        cached = _cached_results()
    results = cached.get("results") or []
    if cached.get("error"):
        st.error(f"Scan gagal: {cached['error']}")
    if not results:
        st.info("Belum ada hasil. Klik **🚀 Jalankan Pre-Pump Scan**. Run "
                "pertama juga mengisi journal likuiditas, jadi sinyal "
                "gelombang add baru terbaca setelah beberapa run.")
    else:
        stamp = _int(cached.get("ts"))
        when = (datetime.fromtimestamp(stamp, timezone.utc)
                .strftime("%Y-%m-%d %H:%M UTC") if stamp else "—")
        hotest = [row for row in results if _num(row.get("score"), 0.0) >= 6.0]
        st.caption(f"{len(results)} token dianalisa · {len(hotest)} dengan "
                   f"skor ≥ 6,0 · diurut PUMP SCORE menurun · terakhir: {when}")
        for row in results:
            render_token_card(str(row.get("ca") or ""),
                              str(row.get("symbol") or "?"), row)
        st.info(f"Last updated: {when}")
    _auto_refresh(enabled=bool(auto), last_ts=_int(cached.get("ts")),
                  has_results=bool(results))


if __name__ == "__main__":  # pragma: no cover - dijalankan Streamlit
    main()
