# -*- coding: utf-8 -*-
"""Pencatatan analisa holder (dust + kohort mid-tier) untuk grafik 4 jam.

File store: ``holder_history.json``. Setiap scan menambahkan titik
(dust count, dust % MC, sisa token kohort Crab+Fish yang di-freeze).
Dashboard meresample ke bucket 4 jam. Snapshot ``holder_status``
menyimpan salinan ringkas ``history`` supaya cron GitHub tetap punya
jejak antar-run.

Store penuh (peta wallet alert/kohort, baseline scan FULL, kronologi)
dibackup terpisah sebagai ``holder_history.json.gz`` di ref ``holder-live``
oleh :func:`publish_holder_history` dan dipulihkan oleh
:func:`pull_holder_history` / :func:`load_durable_holder_history` — snapshot
dashboard sengaja tidak membawa peta itu lagi (94% byte).

Ambang dust (observasi dump) — dua garis:
- >= 0,5% MC → HATI-HATI (peringatan dini, tetap tampil di Scan Meteora)
- >= 1% MC   → BAHAYA (disembunyikan dari Scan Meteora)
"""
from __future__ import annotations

import copy
import gzip
import zlib
import json
import os
import tempfile
import time
from typing import Iterable

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE_DIR, "holder_history.json")


def _atomic_write_json(path: str, data, **dump_kwargs) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".hist-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, **dump_kwargs)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise

DUST_DANGER_PCT = 1.0
# HATI-HATI: dust sudah memegang >= 0,5% MC tapi belum sebatas BAHAYA.
DUST_CAUTION_PCT = 0.5
# BEST POOL: dust < 0,1% MC = distribusi holder sangat bersih (TAMBAHAN,
# bukan pengganti level AMAN/HATI-HATI/BAHAYA). Boundary sengaja **strict
# di bawah 0,1%**: nilai == 0,1% tidak mendapat badge BEST POOL dan juga
# tidak memicu alert ``early_dump`` (yang menyala saat > 0,1%), jadi badge
# dan alert tidak pernah tumpang tindih di angka yang sama.
DUST_BEST_PCT = 0.1
# Label badge BEST POOL (tampil apa adanya di UI — Scan Meteora).
DUST_BEST_LABEL = "BEST POOL"
# Data holder di bawah jumlah ini dianggap gagal/tidak representatif:
# dust "0,00%" dari data kosong/rusak TIDAK BOLEH jadi BEST POOL.
DUST_BEST_MIN_HOLDERS = 40
# Ambang yang sama dipakai sebagai lantai **kelayakan data** di seluruh
# dashboard/alert (lihat :func:`holders_usable` / :func:`point_usable`).
# Kasus nyata 2026-09-06: Helius gagal (rate limit) dan fallback GMGN
# mengembalikan satu halaman berisi **20** holder dengan
# ``truncated: False``. Wallet dust (nilai ≤ $10) ada di **ekor** daftar
# holder, jadi sampel 20 wallet selalu menghasilkan ``dust_count = 0`` /
# ``dust_pct_mc = 0.0`` — watchlist lalu menampilkan "dust turun -100%
# sejak masuk" untuk puluhan token padahal tidak ada yang menjual.
MIN_USABLE_WALLETS = DUST_BEST_MIN_HOLDERS
# alias lama (kompatibilitas import)
DUST_LIMIT_PCT = DUST_DANGER_PCT
# Urutan keparahan badge (dipakai sorting Chart LP / watchlist).
DUST_LEVEL_RANK = {"ok": 0, "caution": 1, "danger": 2}
INTERVAL_SEC = 4 * 3600          # grafik 4 jam sekali
COHORT_WINDOW_SEC = 4 * 3600     # freeze Crab+Fish tiap 4 jam
COHORT_MAX = 200                 # address yang diikuti
MID_USD_MIN = 100.0              # Crab bawah (wallet_depth: > $100)
MID_USD_MAX = 10_000.0           # Fish atas (<= $10k)
# 14 hari × 24 titik/jam: cron naik ke 1× per jam (2026-09-04), sehingga 84
# titik (kalibrasi 6×/hari) hanya muat 3,5 hari. 336 titik mentah per jam
# di-resample ke bucket 4 jam di UI (resample_4h), jadi grafik/chart tetap
# 14 hari × 6 bucket 4 jam dan snapshot dashboard tidak ikut membengkak
# (compact_history_for_status = resample_4h, maks 84 bucket).
MAX_POINTS = 336                 # 14 hari × 24 titik/jam (cron hourly)
# Ambang "scan dobel" (run ganda chain dispatch + schedule). Sejak
# 2026-09-06 lane **Robinhood LP** di-scan tiap **5 menit**, jadi ambang ini
# WAJIB di bawah kadens itu: dengan 8 menit tiap titik baru menimpa titik
# sebelumnya sehingga riwayat Robinhood berhenti tumbuh (selalu 1 titik).
# 4 menit = `scripts.scan_holders.MIN_RUN_GAP_SEC` — run yang benar-benar
# berjarak 5 menit tetap dicatat, tabungan 60 detik masih dibuang.
MIN_POINT_GAP_SEC = 4 * 60

# Volatilitas harga (konfirmasi alert dust) dari candle hourly GeckoTerminal.
VOLATILITY_WINDOW_HOURS = 4          # window "4 jam terakhir"
VOLATILITY_HISTORY_HOURS = 16        # konteks: 16 candle hourly terakhir
VOLATILITY_MIN_CANDLES = 2           # < 2 close → stddev tidak bermakna
HIGH_VOLATILITY_STDDEV_PCT = 3.0     # stddev close 4 jam > 3% = pasar liar
VOLATILITY_STALE_SEC = 2 * 3600      # candle terbaru lebih tua dari ini = basi

# Scan manual (halaman Holder) = FULL: ambil seluruh holder, bukan sampel.
# Sejak 2026-09-05 cron ikut FULL (default scripts/scan_holders.py), jadi
# detail hasil scan pertama tiap token watchlist (``baseline`` = titik awal
# holder analytic) tersimpan apa adanya dan kronologi terakumulasi otomatis.
FULL_SCAN_MAX_WALLETS = 100_000

# Kronologi wallet antar-scan FULL (lihat ``holder_chronology``). Cron
# scan FULL tiap jam sejak 2026-09-05 → interval per scan dipertahankan
# 24 terakhir; narasi kumulatif baseline → terbaru tidak ikut dipangkas.
MAX_CHRONOLOGY_INTERVALS = 24
MAX_SNAPSHOT_WALLETS = 400
MAX_MOVEMENTS_PER_INTERVAL = 40

# Crab $100–$1k + Fish $1k–$10k = pilar harga (bukan Shark, bukan dust).


def _float(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        return num if num == num else default
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    num = _float(value, None)
    return int(num) if num is not None else int(default)


def empty_store() -> dict:
    return {"updated_at": None, "tokens": {}}


def _holders_valid_for_best(holders) -> bool:
    """Guard kebenaran data badge **BEST POOL**.

    Dust ``0,00%`` bisa muncul bukan karena pool bersih, tapi karena data
    holder gagal/kosong (provider mati, fetch 0 wallet) atau sampel terlalu
    kecil untuk dipercaya. BEST POOL **hanya** boleh keluar bila:

    - ada hasil holder yang benar-benar terambil (``total_fetched > 0``),
    - jumlah wallet yang dianalisis ≥ :data:`DUST_BEST_MIN_HOLDERS` (40).

    Catatan (isu terbuka): ``dust_pct_supply`` di-hardcode 0 untuk sumber
    Helius — guard re-klasifikasi dust di ``TODO(alerts)`` bersifat anotasi
    (peringatan), bukan reject, dan tidak dipakai di sini.
    """
    if not isinstance(holders, dict):
        return False
    if _int(holders.get("total_fetched")) <= 0:
        return False
    wallets = _int(holders.get("wallets_analyzed"),
                   _int(holders.get("real_count")) + _int(holders.get("dust_count")))
    return wallets >= DUST_BEST_MIN_HOLDERS


def scan_degraded(holders, *, min_wallets: int = MIN_USABLE_WALLETS) -> bool:
    """True bila ada **bukti** scan holder tidak lengkap/gagal.

    Provider holder bisa mengembalikan daftar yang sangat pendek tanpa
    menandai ``truncated`` — kasus nyata 2026-09-06: Helius mati (rate
    limit) lalu fallback GMGN mengembalikan **20** holder dengan
    ``truncated: False``. Wallet dust (nilai ≤ $10) ada di ekor daftar,
    jadi sampel sependek itu selalu menghasilkan ``dust_count = 0`` /
    ``dust_pct_mc = 0.0`` yang **terlihat** seperti "semua dust keluar"
    (watchlist lalu mengklaim −100% sejak masuk).

    Bukti yang dipakai: ``total_fetched`` < :data:`MIN_USABLE_WALLETS`
    (termasuk 0 = fetch gagal) atau jumlah wallet dianalisis di bawah
    lantai yang sama. Dict tanpa bukti jumlah wallet sama sekali
    (snapshot skema lama/fixture) **tidak** dianggap degraded — tanpa
    bukti kita tidak menolak data.
    """
    if not isinstance(holders, dict) or not holders:
        return False
    if "total_fetched" in holders \
            and _int(holders.get("total_fetched")) < int(min_wallets):
        return True
    wallets = point_wallets(holders)
    return bool(0 < wallets < int(min_wallets))


def holders_usable(holders, *, min_wallets: int = MIN_USABLE_WALLETS) -> bool:
    """True bila hasil fetch holder layak **ditampilkan/dibandingkan**.

    Kebalikan dari :func:`scan_degraded`, plus syarat ada datanya: dict
    kosong/bukan dict → False (tidak ada bukti sama sekali).
    """
    if not isinstance(holders, dict) or not holders:
        return False
    return not scan_degraded(holders, min_wallets=min_wallets)


def point_wallets(point) -> int:
    """Jumlah wallet yang dianalisis satu titik/hasil holder.

    Dua bentuk dict diterima: titik history memakai ``holder_count``
    (diisi dari ``wallets_analyzed`` oleh :func:`_build_point`), sedangkan
    dict hasil ``classify_holders`` memakai ``wallets_analyzed``. Bila
    keduanya tidak ada (skema lama/fixture) dipakai
    ``real_count + dust_count``.
    """
    row = point if isinstance(point, dict) else {}
    explicit = [_int(row.get(key)) for key in ("wallets_analyzed",
                                               "holder_count")
                if key in row]
    if explicit:
        return max(explicit)
    return _int(row.get("real_count")) + _int(row.get("dust_count"))


def point_usable(point, *, min_wallets: int = MIN_USABLE_WALLETS) -> bool:
    """True bila satu titik history layak dipakai angka/grafik/pembanding.

    Titik dari scan yang datanya tidak lengkap (:func:`scan_degraded`)
    ditandai ``degraded`` saat di-ingest; titik lama yang belum punya
    penanda itu tetap tersaring dari lantai jumlah wallet
    (:data:`MIN_USABLE_WALLETS`) selama jumlahnya tercatat — titik tanpa
    informasi jumlah wallet (skema lama/fixture) tidak ditolak. Titik
    tanpa ``dust_pct_mc`` juga ditolak: nilainya tidak bisa dibandingkan
    dan biasanya ikut menandakan scan gagal.
    """
    row = point if isinstance(point, dict) else {}
    if not row:
        return False
    if row.get("degraded"):
        return False
    if _float(row.get("dust_pct_mc"), None) is None:
        return False
    wallets = point_wallets(row)
    if wallets <= 0:
        return True
    return wallets >= int(min_wallets)


def usable_points(points, *, min_wallets: int = MIN_USABLE_WALLETS) -> list:
    """Titik history yang layak tampil (urutan asli dipertahankan)."""
    return [row for row in (points or [])
            if isinstance(row, dict)
            and point_usable(row, min_wallets=min_wallets)]


def dust_flag(dust_pct_mc, prev_pct=None, *, holders=None) -> dict:
    """Klasifikasi dust % MC: ok / caution / danger (+ info ``best``).

    - ``>= 0,5% MC`` → **HATI-HATI** (``caution``): dust sudah memegang
      porsi MC yang berarti, pantau lebih ketat.
    - ``>= 1% MC`` → **BAHAYA** (``danger``): ``hide`` True, disembunyikan
      dari Scan Meteora.

    Level/label/hide yang lama **tidak berubah** (AMAN/HATI-HATI/BAHAYA
    tetap). Tambahan aditif: ``best`` True hanya untuk pool dengan
    ``dust_pct_mc < DUST_BEST_PCT`` (0,1%) **dan** data holder valid — lihat
    :func:`_holders_valid_for_best` (``holders`` = dict hasil
    ``analysis["holders"]``; ``None`` = tidak ada bukti → tidak pernah best,
    supaya pemanggil lama seperti watchlist/LP card tidak berubah perilaku).
    ``best`` tidak memengaruhi ``level``/``hide``/``dust_level_rank``.

    ``rising`` True jika % MC naik dibanding titik sebelumnya.
    """
    pct = _float(dust_pct_mc, None)
    prev = _float(prev_pct, None)
    rising = bool(pct is not None and prev is not None and pct > prev)
    best = bool(pct is not None and pct < DUST_BEST_PCT
                and _holders_valid_for_best(holders))
    if pct is None:
        return {"level": "unknown", "label": "—", "hide": False,
                "rising": False, "pct": None, "best": False}
    if pct >= DUST_DANGER_PCT:
        return {"level": "danger", "label": "BAHAYA", "hide": True,
                "rising": rising, "pct": pct, "best": False}
    if pct >= DUST_CAUTION_PCT:
        return {"level": "caution", "label": "HATI-HATI", "hide": False,
                "rising": rising, "pct": pct, "best": False}
    return {"level": "ok", "label": "AMAN", "hide": False,
            "rising": rising, "pct": pct, "best": best}


def dust_level_rank(level) -> int:
    """Bobot keparahan level dust (``unknown`` = -1, ``danger`` = 2)."""
    return int(DUST_LEVEL_RANK.get(str(level or ""), -1))


def should_hide_dust(dust_pct_mc) -> bool:
    """True bila dust holder memegang ≥ 1% marketcap (BAHAYA)."""
    return bool(dust_flag(dust_pct_mc)["hide"])


def _volatility_rows(values) -> dict[int, dict]:
    """Normalisasi candle hourly (dict atau baris OHLCV) → ``{ts: row}``.

    Baris tanpa timestamp/close yang usable dibuang; harga non-positif dan
    non-finite diabaikan supaya satu candle rusak tidak menghasilkan stddev
    ``nan`` yang lalu lolos ke aturan alert.
    """
    rows: dict[int, dict] = {}
    for value in values or []:
        if isinstance(value, dict):
            raw = (value.get("ts"), value.get("open"), value.get("high"),
                   value.get("low"), value.get("close"),
                   value.get("volume_usd", value.get("volume")))
        elif isinstance(value, (list, tuple)) and len(value) >= 6:
            raw = tuple(value[:6])
        else:
            continue
        ts = _float(raw[0], None)
        close = _float(raw[4], None)
        if ts is None or ts <= 0 or close is None or close <= 0:
            continue
        opening = _float(raw[1], None)
        high = _float(raw[2], None)
        low = _float(raw[3], None)
        volume = _float(raw[5], 0.0) or 0.0
        rows[int(ts)] = {
            "ts": int(ts),
            "open": close if opening is None or opening <= 0 else opening,
            "high": max(close, high if high is not None and high > 0 else close),
            "low": min(close, low if low is not None and low > 0 else close),
            "close": close,
            "volume_usd": max(0.0, volume),
        }
    return rows


def _stddev_pct(values, mean: float) -> float | None:
    """Sample standard deviation (n-1) of *values* as a percent of *mean*."""
    count = len(values)
    if count < 2 or mean <= 0:
        return None
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    return round((variance ** 0.5) / mean * 100.0, 4)


def calculate_volatility_metrics(candles, historical=None, *,
                                 window_hours: int = VOLATILITY_WINDOW_HOURS,
                                 history_hours: int = VOLATILITY_HISTORY_HOURS,
                                 now=None,
                                 high_volatility_pct: float = HIGH_VOLATILITY_STDDEV_PCT,
                                 stale_after_sec: int = VOLATILITY_STALE_SEC) -> dict:
    """Metrik volatilitas harga dari candle hourly (konfirmasi alert dust).

    ``candles`` adalah candle window berjalan (idealnya 4 jam terakhir) dan
    ``historical`` candle jam-jam sebelumnya (total ~16 candle = konteks
    beberapa hari). Keduanya boleh dict ``{ts, open, high, low, close,
    volume_usd}`` atau baris OHLCV mentah GeckoTerminal; timestamp duplikat
    dihitung sekali.

    Return (semua persentase terhadap harga rata-rata window):

    - ``price_stddev_4h``      : sample stddev close per jam di window 4 jam (%).
    - ``price_range_4h``       : (high tertinggi − low terendah) / rata-rata (%).
    - ``intra_hour_volatility``: rata-rata (high−low)/close tiap jam (%),
      plus ``intra_hour_volatility_max`` untuk jam paling liar.
    - ``high_volatility``      : True bila ``price_stddev_4h`` > ambang (3%).
    - ``price_change_4h_pct``  : open jam pertama → close jam terakhir (%).
    - ``volume_4h``            : total volume USD window 4 jam.
    - ``history_stddev_pct``   : stddev 16 jam sebagai pembanding.
    - ``available``            : False bila candle < 2 / harga rata-rata 0 —
      pemanggil wajib memperlakukannya sebagai "tidak tahu", bukan "tenang".
    - ``candles_in_window``, ``missing_hours``, ``stale``, ``avg_price_4h``,
      ``close_price``, ``window_hours``, ``history_hours``, ``anchor_ts``.

    ``now`` opsional: tanpa itu candle terbaru dipakai sebagai jangkar, jadi
    backfill data lama tetap konsisten. ``stale`` menandakan candle terbaru
    sudah lebih tua dari ``stale_after_sec`` (sumber data telat/lubang).
    """
    # Historical lebih dulu: bila ada timestamp kembar, candle window berjalan
    # (data yang lebih baru) yang menang.
    rows = _volatility_rows(historical)
    rows.update(_volatility_rows(candles))
    ordered = [rows[ts] for ts in sorted(rows)]
    window = max(1, int(window_hours or VOLATILITY_WINDOW_HOURS))
    history = max(window, int(history_hours or VOLATILITY_HISTORY_HOURS))
    high_threshold = _float(high_volatility_pct, HIGH_VOLATILITY_STDDEV_PCT)
    empty = {
        "available": False, "price_stddev_4h": None, "price_range_4h": None,
        "intra_hour_volatility": None, "intra_hour_volatility_max": None,
        "high_volatility": False, "price_change_4h_pct": None,
        "volume_4h": None, "history_stddev_pct": None, "avg_price_4h": None,
        "close_price": None, "candles_in_window": 0, "candles_total": len(ordered),
        "missing_hours": window, "stale": False, "anchor_ts": None,
        "window_hours": window, "history_hours": history,
        "high_volatility_pct": high_threshold,
    }
    if not ordered:
        return empty

    anchor = _float(now, None)
    anchor_ts = int(anchor) if anchor is not None else ordered[-1]["ts"]
    window_from = anchor_ts - window * 3600
    history_from = anchor_ts - history * 3600
    in_window = [row for row in ordered if row["ts"] > window_from
                 and row["ts"] <= anchor_ts]
    in_history = [row for row in ordered if row["ts"] > history_from
                  and row["ts"] <= anchor_ts]

    closes = [row["close"] for row in in_window]
    mean_price = (sum(closes) / len(closes)) if closes else 0.0
    stddev_pct = _stddev_pct(closes, mean_price)
    high = max((row["high"] for row in in_window), default=None)
    low = min((row["low"] for row in in_window), default=None)
    range_pct = (round((high - low) / mean_price * 100.0, 4)
                 if high is not None and low is not None and mean_price > 0
                 else None)
    intra = [round((row["high"] - row["low"]) / row["close"] * 100.0, 4)
             for row in in_window if row["close"] > 0 and row["high"] >= row["low"]]
    change_pct = None
    if in_window and in_window[0]["open"] > 0:
        change_pct = round((in_window[-1]["close"] - in_window[0]["open"])
                           / in_window[0]["open"] * 100.0, 4)
    history_closes = [row["close"] for row in in_history]
    history_mean = (sum(history_closes) / len(history_closes)) if history_closes else 0.0
    distinct_hours = len({row["ts"] // 3600 for row in in_window})
    available = len(closes) >= max(2, int(VOLATILITY_MIN_CANDLES)) and mean_price > 0
    return {
        "available": bool(available),
        "price_stddev_4h": stddev_pct if available else None,
        "price_range_4h": range_pct if available else None,
        "intra_hour_volatility": (round(sum(intra) / len(intra), 4)
                                  if available and intra else None),
        "intra_hour_volatility_max": (max(intra) if available and intra else None),
        "high_volatility": bool(available and stddev_pct is not None
                                and stddev_pct > high_threshold),
        "price_change_4h_pct": change_pct if available else None,
        "volume_4h": round(sum(row["volume_usd"] for row in in_window), 2),
        "history_stddev_pct": _stddev_pct(history_closes, history_mean),
        "avg_price_4h": round(mean_price, 12) if mean_price > 0 else None,
        "close_price": in_window[-1]["close"] if in_window else None,
        "candles_in_window": len(in_window),
        "candles_total": len(ordered),
        "missing_hours": max(0, window - distinct_hours),
        "stale": bool((anchor_ts - ordered[-1]["ts"])
                      > max(0, int(stale_after_sec))),
        "anchor_ts": anchor_ts,
        "window_hours": window,
        "history_hours": history,
        "high_volatility_pct": high_threshold,
    }


def _pool_set(pool_addresses) -> set[str]:
    return {str(p or "").strip().lower() for p in (pool_addresses or []) if p}


def _is_pool(row: dict, pools: set[str]) -> bool:
    if not row.get("is_wallet"):
        return True
    return str(row.get("address") or "").lower() in pools


def mid_tier_stats(holders: Iterable[dict] | None, market_cap: float = 0.0,
                   *, pool_addresses=None, cap: int = COHORT_MAX) -> dict:
    """Crab+Fish (>$100 ≤ $10k), wallet murni, freeze max ``cap`` address.

    ``count`` / ``value_usd`` / ``pct_mc`` dihitung atas **semua** mid,
    ``balances`` hanya top-N (buat kohort).
    """
    pools = _pool_set(pool_addresses)
    rows = []
    for row in holders or []:
        if not isinstance(row, dict) or _is_pool(row, pools):
            continue
        usd = _float(row.get("usd_value"), 0.0) or 0.0
        if MID_USD_MIN < usd <= MID_USD_MAX:
            rows.append(row)
    value = sum(_float(h.get("usd_value"), 0.0) or 0.0 for h in rows)
    mc = _float(market_cap, 0.0) or 0.0
    ranked = sorted(rows, key=lambda h: _float(h.get("usd_value"), 0.0) or 0.0,
                    reverse=True)[:max(1, int(cap))]
    balances = {}
    for row in ranked:
        addr = str(row.get("address") or "").strip()
        if addr:
            balances[addr] = _float(row.get("balance"), 0.0) or 0.0
    return {
        "count": len(rows),
        "value_usd": round(value, 2),
        "pct_mc": (round(value / mc * 100.0, 4) if mc > 0 else None),
        "balances": balances,
    }


def lookup_balances(holders: Iterable[dict] | None, addresses) -> dict:
    """Saldo token sekarang untuk address kohort (hilang = 0)."""
    want = {str(a or "").strip() for a in (addresses or []) if a}
    found = {addr: 0.0 for addr in want}
    if not want:
        return found
    for row in holders or []:
        if not isinstance(row, dict):
            continue
        addr = str(row.get("address") or "").strip()
        if addr in found:
            found[addr] = _float(row.get("balance"), 0.0) or 0.0
    return found


def score_cohort(frozen: dict | None, current: dict | None) -> dict:
    """Sisa token kohort beku vs sekarang (tahan harga, bukan USD).

    ``remaining_pct``: total token sekarang / total token saat freeze × 100.
    ``cut50_pct``: % address yang sisa ≤ 50% token (termasuk yang 0).
    """
    frozen = {str(k): (_float(v, 0.0) or 0.0)
              for k, v in (frozen or {}).items() if k}
    if not frozen:
        return {"remaining_pct": None, "cut50_pct": None, "n": 0}
    current = current or {}
    total0 = sum(frozen.values())
    remaining = 0.0
    cut50 = 0
    for addr, start in frozen.items():
        now_bal = _float(current.get(addr), 0.0) or 0.0
        remaining += now_bal
        if start > 0 and now_bal <= 0.5 * start:
            cut50 += 1
        elif start <= 0 and now_bal <= 0:
            cut50 += 1
    n = len(frozen)
    remaining_pct = (remaining / total0 * 100.0) if total0 > 0 else None
    return {
        "remaining_pct": (round(remaining_pct, 4)
                          if remaining_pct is not None else None),
        "cut50_pct": round(cut50 / n * 100.0, 4) if n else None,
        "n": n,
    }


def bucket_counts(depth: dict | None) -> dict:
    """Peta ``{label bucket: jumlah holder}`` dari hasil ``wallet_depth``.

    Dipakai sebagai isi titik history supaya grafik komposisi holder
    (Wallet Depth by Threshold) bisa digambar sepanjang waktu tanpa harus
    menyimpan seluruh daftar address tiap scan.
    """
    out: dict[str, int] = {}
    for row in ((depth or {}).get("buckets") or []):
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        if label:
            out[label] = _int(row.get("count"))
    return out


def detail_snapshot(analysis: dict | None, now: int | None = None) -> dict:
    """Rekaman **detail** satu scan penuh (baseline / scan full terakhir).

    Berisi ringkasan holder + seluruh bucket & tier hasil ``wallet_depth``
    (jumlah, nilai USD, % MC) — cukup untuk menggambar ulang distribusi
    holder tanpa scan lagi, tapi tanpa daftar address (file tetap kecil).
    """
    analysis = analysis or {}
    holders = analysis.get("holders") or {}
    depth = holders.get("depth") if isinstance(holders.get("depth"), dict) else {}
    mid = holders.get("mid") if isinstance(holders.get("mid"), dict) else {}
    stamp = _int(now or analysis.get("analyzed_at") or time.time())
    return {
        "ts": stamp,
        "symbol": str(analysis.get("symbol") or "?"),
        "price": _float(analysis.get("price"), None),
        "mc": _float(analysis.get("marketcap"), None),
        "source": str(holders.get("source") or analysis.get("source") or ""),
        "fetched": _int(holders.get("total_fetched")),
        "pages": _int(holders.get("pages")),
        "truncated": bool(holders.get("truncated")),
        "holder_count": _int(holders.get("wallets_analyzed")),
        "dust_count": _int(holders.get("dust_count")),
        "dust_pct_mc": _float(holders.get("dust_pct_mc"), None),
        "real_count": _int(holders.get("real_count")),
        "real_pct_mc": _float(holders.get("real_pct_mc"), None),
        "mid_count": _int(mid.get("count")),
        "mid_pct_mc": _float(mid.get("pct_mc"), None),
        "depth": {
            "buckets": [dict(b) for b in (depth.get("buckets") or [])
                        if isinstance(b, dict)],
            "tiers": [dict(t) for t in (depth.get("tiers") or [])
                      if isinstance(t, dict)],
            "buckets_include_pools": bool(depth.get("buckets_include_pools")),
            "holders_all": _int(depth.get("holders_all")),
            "holders_wallet": _int(depth.get("holders_wallet")),
            "pool_excluded": _int(depth.get("pool_excluded")),
            "market_cap": _float(depth.get("market_cap"), 0.0) or 0.0,
        },
    }


def baseline_for_mint(store: dict | None, mint: str) -> dict:
    """Detail scan **pertama** (baseline) token — {} bila belum ada."""
    slot = ((store or {}).get("tokens") or {}).get(str(mint) or "") or {}
    base = slot.get("baseline") if isinstance(slot, dict) else None
    return base if isinstance(base, dict) else {}


def latest_detail_for_mint(store: dict | None, mint: str) -> dict:
    """Detail scan full **terakhir** — fallback ke baseline."""
    slot = ((store or {}).get("tokens") or {}).get(str(mint) or "") or {}
    latest = slot.get("latest_detail") if isinstance(slot, dict) else None
    if isinstance(latest, dict) and latest:
        return latest
    return baseline_for_mint(store, mint)


def chronology_for_mint(store: dict | None, mint: str) -> dict:
    """Kronologi scan FULL per token; schema lama → struktur kosong aman."""
    slot = ((store or {}).get("tokens") or {}).get(str(mint) or "") or {}
    raw = slot.get("chronology") if isinstance(slot, dict) else None
    try:
        from holder_chronology import compact_chronology, empty_chronology
        if isinstance(raw, dict) and raw:
            return compact_chronology(raw)
        return empty_chronology()
    except Exception:  # noqa: BLE001 - schema lama tidak boleh merusak load
        return {"baseline_wallets": {}, "latest_wallets": {}, "intervals": []}


def tracked_chronology_addresses(store: dict | None, mint: str) -> list[str]:
    """Address yang harus diutamakan pada scan FULL berikutnya."""
    try:
        from holder_chronology import tracked_addresses
        return tracked_addresses(chronology_for_mint(store, mint))
    except Exception:  # noqa: BLE001
        return []


def chronology_view_for_mint(store: dict | None, mint: str) -> dict:
    """View model halaman Holder Analytic (aman untuk schema lama)."""
    try:
        from holder_chronology import build_chronology_view
        return build_chronology_view(
            baseline_for_mint(store, mint),
            latest_detail_for_mint(store, mint),
            chronology_for_mint(store, mint))
    except Exception:  # noqa: BLE001
        return {"state": "none", "intervals": []}


def compact_chronology_for_status(store: dict | None, mint: str) -> dict:
    """Salinan kronologi bounded untuk payload ``holder_status``."""
    try:
        from holder_chronology import compact_chronology_for_status as _pack
        return _pack(chronology_for_mint(store, mint))
    except Exception:  # noqa: BLE001
        return {"intervals": []}


def full_scan_usable(analysis: dict | None) -> bool:
    """False hanya jika scan FULL jelas gagal (0 holder terambil).

    Fixture lama tanpa ``total_fetched`` tetap dianggap usable supaya
    schema/test yang sudah ada tidak pecah. Scan non-detail tidak memakai
    helper ini.

    Catatan: scan yang holdernya **tidak lengkap** (sampel pendek, lihat
    :func:`scan_degraded`) masih lolos di sini — baseline/``latest_detail``
    tetap ditulis — tetapi titiknya ditandai ``degraded`` sehingga tidak
    pernah dipakai angka baris watchlist, grafik, maupun alert.
    """
    if not isinstance(analysis, dict):
        return False
    holders = analysis.get("holders") if isinstance(analysis.get("holders"),
                                                    dict) else {}
    if "total_fetched" in holders and _int(holders.get("total_fetched")) <= 0:
        return False
    return True


def bucket_delta(baseline: dict | None, latest: dict | None) -> list[dict]:
    """Perubahan tiap bucket antara baseline dan detail terbaru.

    Return list ``{"label", "base_count", "now_count", "delta",
    "base_value_usd", "now_value_usd"}`` mengikuti urutan bucket baseline
    (bucket baru yang belum ada di baseline ikut ditambahkan di belakang).
    """
    def _index(detail):
        rows = ((detail or {}).get("depth") or {}).get("buckets") or []
        return {str(r.get("label") or ""): r for r in rows
                if isinstance(r, dict)}

    base_rows = _index(baseline)
    now_rows = _index(latest)
    labels = list(base_rows) + [l for l in now_rows if l not in base_rows]
    out = []
    for label in labels:
        if not label:
            continue
        base = base_rows.get(label) or {}
        now = now_rows.get(label) or {}
        base_count = _int(base.get("count"))
        now_count = _int(now.get("count"))
        out.append({
            "label": label,
            "base_count": base_count,
            "now_count": now_count,
            "delta": now_count - base_count,
            "base_value_usd": _float(base.get("value_usd"), 0.0) or 0.0,
            "now_value_usd": _float(now.get("value_usd"), 0.0) or 0.0,
        })
    return out


def bucket_series(points: Iterable[dict] | None) -> tuple[list[int], list[str],
                                                          dict]:
    """Deret komposisi holder per bucket dari titik history 4 jam.

    Return ``(timestamps, labels, {label: [count per titik]})``. Titik
    tanpa data bucket (mis. scan lama) diisi 0 supaya panjang deret sama.
    """
    sampled = resample_4h(points)
    rows = [(p, p.get("buckets") or {}) for p in sampled]
    rows = [(p, b) for p, b in rows if isinstance(b, dict) and b]
    if not rows:
        return [], [], {}
    labels: list[str] = []
    for _point, buckets in rows:
        for label in buckets:
            if label not in labels:
                labels.append(label)
    stamps = [_int(p.get("ts")) for p, _b in rows]
    series = {label: [_int(b.get(label)) for _p, b in rows] for label in labels}
    return stamps, labels, series


def _parse_store(data) -> dict | None:
    if isinstance(data, dict) and isinstance(data.get("tokens"), dict):
        return {
            "updated_at": data.get("updated_at"),
            "tokens": data["tokens"],
        }
    return None


def load_holder_history(path: str | None = None) -> dict:
    target = path or HISTORY_PATH
    try:
        with open(target, encoding="utf-8") as handle:
            parsed = _parse_store(json.load(handle))
            if parsed is not None:
                return parsed
    except (OSError, ValueError, TypeError):
        pass
    return empty_store()


def save_holder_history(store: dict, path: str | None = None) -> dict:
    target = path or HISTORY_PATH
    payload = {
        "updated_at": store.get("updated_at"),
        "tokens": store.get("tokens") if isinstance(store.get("tokens"), dict)
        else {},
    }
    _atomic_write_json(target, payload, indent=2)
    return payload


def compact_point(point: dict | None) -> dict:
    """Titik history tanpa peta address (aman untuk holder_status).

    Penanda ``degraded`` (scan holder tidak lengkap — lihat
    :func:`scan_degraded`) ikut terbawa supaya filter display di
    ``watchlist_detail`` tetap mengenal titik itu setelah melewati
    ``resample_4h`` / snapshot.
    """
    point = point or {}
    keys = ("ts", "price", "mc", "dust_count", "dust_pct_mc", "dust_value_usd",
            "real_count", "real_pct_mc", "mid_count", "mid_pct_mc",
            "cohort_token_pct", "cohort_cut50_pct", "cohort_n",
            "holder_count", "buckets", "full", "degraded")
    out = {}
    for key in keys:
        if key in point:
            value = point[key]
            out[key] = dict(value) if key == "buckets" and isinstance(
                value, dict) else value
    return out


def resample_4h(points: Iterable[dict] | None, *,
                interval: int = INTERVAL_SEC) -> list[dict]:
    """Satu titik per bucket 4 jam (titik terakhir di bucket menang)."""
    interval = max(60, int(interval))
    buckets: dict[int, dict] = {}
    for raw in points or []:
        if not isinstance(raw, dict):
            continue
        ts = _int(raw.get("ts"))
        if ts <= 0:
            continue
        buckets[(ts // interval) * interval] = compact_point(raw)
    ordered = []
    for ts in sorted(buckets):
        row = dict(buckets[ts])
        row["ts"] = ts
        ordered.append(row)
    return ordered


def sparkline_svg(points: Iterable[dict] | None, *, key: str = "dust_pct_mc",
                  width: int = 140, height: int = 36) -> str:
    """Sparkline inline SVG dari titik 4 jam. Kosong jika < 2 nilai."""
    series = []
    for row in resample_4h(points):
        value = _float(row.get(key), None)
        if value is not None:
            series.append(value)
    if len(series) < 2:
        return ""
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1.0
    width = max(40, int(width))
    height = max(20, int(height))
    coords = []
    last = len(series) - 1
    for index, value in enumerate(series):
        x = 2.0 + index / last * (width - 4)
        y = (height - 4) - (value - lo) / span * (height - 8)
        coords.append((x, y))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    fill_pts = (f"2.0,{height - 2} " + line
                + f" {coords[-1][0]:.1f},{height - 2}")
    rising = series[-1] > series[0]
    stroke = "#b91c1c" if rising else "#15803d"
    fill = "#fecaca" if rising else "#bbf7d0"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="sparkline {key}">'
        f'<polyline points="{fill_pts}" fill="{fill}" fill-opacity="0.55" '
        f'stroke="none"/>'
        f'<polyline points="{line}" fill="none" stroke="{stroke}" '
        f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


def history_for_mint(store: dict | None, mint: str) -> list[dict]:
    token = ((store or {}).get("tokens") or {}).get(str(mint) or "") or {}
    points = token.get("points") if isinstance(token, dict) else None
    return [compact_point(p) for p in (points or []) if isinstance(p, dict)]


def merge_points(*groups) -> list[dict]:
    """Gabung titik dari beberapa sumber, unik per ts, urut naik."""
    by_ts: dict[int, dict] = {}
    for group in groups:
        for raw in group or []:
            if not isinstance(raw, dict):
                continue
            ts = _int(raw.get("ts"))
            if ts <= 0:
                continue
            by_ts[ts] = compact_point(raw)
            by_ts[ts]["ts"] = ts
    return [by_ts[ts] for ts in sorted(by_ts)]


def _token_slot(store: dict, mint: str, symbol: str = "?") -> dict:
    tokens = store.setdefault("tokens", {})
    slot = tokens.get(mint)
    if not isinstance(slot, dict):
        slot = {"symbol": symbol or "?", "cohort": {}, "points": []}
        tokens[mint] = slot
    slot.setdefault("points", [])
    slot.setdefault("cohort", {})
    slot.setdefault("baseline", {})
    if symbol and symbol != "?":
        slot["symbol"] = symbol
    return slot


def _ingest_full_detail(slot: dict, analysis: dict, now: int) -> None:
    """Tulis baseline/latest + interval kronologi setelah comparison selesai.

    Baseline **tidak pernah ditimpa**. Snapshot wallet pembanding
    (``latest_wallets``) baru diganti setelah interval dihitung terhadap
    snapshot sebelumnya.
    """
    from holder_chronology import (compact_chronology, compare_snapshots,
                                   snapshot_from_analysis)

    snapshot = detail_snapshot(analysis, now)
    wallets = snapshot_from_analysis(analysis, now)
    chrono = slot.get("chronology") if isinstance(slot.get("chronology"),
                                                  dict) else {}
    baseline = slot.get("baseline") if isinstance(slot.get("baseline"),
                                                  dict) else {}
    if not baseline:
        slot["baseline"] = snapshot
        slot["latest_detail"] = snapshot
        slot["chronology"] = compact_chronology({
            "baseline_wallets": wallets,
            "latest_wallets": wallets,
            "intervals": [],
        })
        return

    previous = {}
    if isinstance(chrono.get("latest_wallets"), dict) and (
            chrono.get("latest_wallets") or {}).get("wallets"):
        previous = chrono.get("latest_wallets")
    elif isinstance(chrono.get("baseline_wallets"), dict) and (
            chrono.get("baseline_wallets") or {}).get("wallets"):
        previous = chrono.get("baseline_wallets")

    intervals = [row for row in (chrono.get("intervals") or [])
                 if isinstance(row, dict)]
    if previous:
        latest_metrics = slot.get("latest_detail") if isinstance(
            slot.get("latest_detail"), dict) else baseline
        interval = compare_snapshots(
            previous, wallets,
            previous_metrics=latest_metrics, current_metrics=snapshot)
        intervals.append(interval)
    if len(intervals) > MAX_CHRONOLOGY_INTERVALS:
        intervals = intervals[-MAX_CHRONOLOGY_INTERVALS:]

    baseline_wallets = chrono.get("baseline_wallets") if isinstance(
        chrono.get("baseline_wallets"), dict) else {}
    if not (baseline_wallets or {}).get("wallets"):
        baseline_wallets = wallets

    slot["latest_detail"] = snapshot
    slot["chronology"] = compact_chronology({
        "baseline_wallets": baseline_wallets,
        "latest_wallets": wallets,
        "intervals": intervals,
    })


def _build_point(analysis: dict, score: dict, now: int) -> dict:
    holders = (analysis or {}).get("holders") or {}
    mid = holders.get("mid") if isinstance(holders.get("mid"), dict) else {}
    return {
        "ts": now,
        "price": _float((analysis or {}).get("price"), None),
        "mc": _float((analysis or {}).get("marketcap"), None),
        "dust_count": _int(holders.get("dust_count")),
        "dust_pct_mc": _float(holders.get("dust_pct_mc"), None),
        "dust_value_usd": _float(holders.get("dust_value_usd"), 0.0) or 0.0,
        "real_count": _int(holders.get("real_count")),
        "real_pct_mc": _float(holders.get("real_pct_mc"), None),
        "mid_count": _int(mid.get("count")),
        "mid_pct_mc": _float(mid.get("pct_mc"), None),
        "cohort_token_pct": score.get("remaining_pct"),
        "cohort_cut50_pct": score.get("cut50_pct"),
        "cohort_n": score.get("n") or 0,
        "holder_count": _int(holders.get("wallets_analyzed")),
        "buckets": bucket_counts(holders.get("depth")),
    }


def ingest_one(store: dict, mint: str, analysis: dict | None, *,
               now: int | None = None, detail: bool = False) -> dict:
    """Tambah satu titik + update kohort. Mutasi ``store``.

    ``detail=True`` (scan **full**) juga menyimpan rekaman detail:
    ``baseline`` ditulis sekali saja pada scan full pertama dan **tidak
    pernah ditimpa** (titik awal holder analytic), sementara
    ``latest_detail`` diperbarui tiap scan full. Cron sejak 2026-09-05
    ikut memakai ``detail=True`` (scan FULL tiap jam), jadi baseline +
    kronologi terbentuk otomatis untuk semua token watchlist.

    Titik dari scan yang holdernya terbukti tidak lengkap
    (:func:`scan_degraded`) ditandai ``degraded: True``: jejak run-nya
    tetap ada, tetapi tidak dipakai sebagai angka baris watchlist, titik
    grafik, pembanding "sejak masuk", maupun pemicu alert.
    """
    mint = str(mint or "").strip()
    if not mint or not isinstance(analysis, dict):
        return store
    if detail and not full_scan_usable(analysis):
        # Scan FULL gagal: jangan sentuh baseline, latest, kronologi, atau titik.
        return store
    now = int(now or analysis.get("analyzed_at") or time.time())
    slot = _token_slot(store, mint, str(analysis.get("symbol") or "?"))
    points = slot.setdefault("points", [])
    if points:
        last_ts = _int(points[-1].get("ts"))
        if last_ts and now - last_ts < MIN_POINT_GAP_SEC:
            # Scan dobel: timpa titik terakhir, kohort tetap dihitung ulang.
            points.pop()
    holders = analysis.get("holders") or {}
    mid = holders.get("mid") if isinstance(holders.get("mid"), dict) else {}
    mid_balances = dict(mid.get("balances") or {})
    cohort_now = dict(holders.get("cohort_now") or {})
    cohort = slot.get("cohort") if isinstance(slot.get("cohort"), dict) else {}
    frozen = dict(cohort.get("balances") or {})
    frozen_at = _int(cohort.get("frozen_at"))
    if not frozen:
        slot["cohort"] = {"frozen_at": now, "balances": mid_balances}
        score = {"remaining_pct": 100.0 if mid_balances else None,
                 "cut50_pct": 0.0 if mid_balances else None,
                 "n": len(mid_balances)}
    else:
        score = score_cohort(frozen, cohort_now)
        if now - frozen_at >= COHORT_WINDOW_SEC and mid_balances:
            slot["cohort"] = {"frozen_at": now, "balances": mid_balances}
    point = _build_point(analysis, score, now)
    if scan_degraded(holders):
        # Bukti scan tidak lengkap (mis. provider mengembalikan 20 holder):
        # titik tetap dicatat sebagai jejak run, tetapi UI/alert tidak
        # boleh memakainya sebagai angka (lihat watchlist_detail).
        point["degraded"] = True
    if detail:
        _ingest_full_detail(slot, analysis, now)
        point["full"] = True
    points.append(point)
    if len(points) > MAX_POINTS:
        del points[:-MAX_POINTS]
    store["updated_at"] = now
    return store


def ingest_many(analyses: dict | None, *, now: int | None = None,
                path: str | None = None, store: dict | None = None,
                detail: bool = False) -> dict:
    """Catat banyak token lalu tulis ``holder_history.json``.

    ``detail=True`` dipakai scan full manual dan cron (sejak 2026-09-05
    cron scan FULL — menyimpan baseline / detail terbaru / kronologi);
    ``detail=False`` hanya menambah titik ringkas.
    """
    store = dict(store or load_holder_history(path))
    store.setdefault("tokens", {})
    stamp = int(now or time.time())
    for mint, analysis in (analyses or {}).items():
        ingest_one(store, mint, analysis, now=stamp, detail=detail)
    return save_holder_history(store, path)


def _sanitize_remote_chronology(chrono) -> dict | None:
    """Buat kronologi dari snapshot aman untuk :func:`compact_chronology`.

    Snapshot ramping mengirim ``wallets`` sebagai **jumlah** (int), bukan peta;
    tanpa sanitasi nilai itu bisa bocor ke store dan merusak pembanding
    kronologi. Peta kosong membuat logika "local menang bila sudah ada wallet"
    di ``seed_from_status`` tetap benar.
    """
    if not isinstance(chrono, dict):
        return None
    out = dict(chrono)
    for key in ("baseline_wallets", "latest_wallets"):
        snap = out.get(key)
        if isinstance(snap, dict) and not isinstance(snap.get("wallets"), dict):
            snap = dict(snap)
            snap["wallets"] = {}
            out[key] = snap
    return out


def seed_from_status(store: dict, status: dict | None) -> dict:
    """Isi titik dari snapshot holder_status bila file history masih tipis."""
    store = store or empty_store()
    tokens = store.setdefault("tokens", {})
    for mint, token in ((status or {}).get("tokens") or {}).items():
        if not mint or not isinstance(token, dict):
            continue
        incoming = token.get("history") or []
        slot = _token_slot(store, mint, str(token.get("symbol") or "?"))
        if incoming:
            slot["points"] = merge_points(slot.get("points") or [], incoming)
            if len(slot["points"]) > MAX_POINTS:
                slot["points"] = slot["points"][-MAX_POINTS:]
        remote_cohort = token.get("cohort")
        # cohort ringkas ({"summary": True, "wallets": n}) tidak punya balance.
        if isinstance(remote_cohort, dict) and remote_cohort.get("summary") \
                and not isinstance(remote_cohort.get("balances"), dict):
            remote_cohort = None
        local_cohort = slot.get("cohort") if isinstance(slot.get("cohort"), dict) else {}
        if (isinstance(remote_cohort, dict) and remote_cohort.get("balances")
                and not (local_cohort or {}).get("balances")):
            slot["cohort"] = {
                "frozen_at": remote_cohort.get("frozen_at"),
                "balances": dict(remote_cohort.get("balances") or {}),
            }
        remote_alert = token.get("alert_state")
        # Snapshot ramping mengirim alert_state sebagai RINGKASAN (jumlah
        # wallet, bukan peta balance) — jangan timpa state penuh di store.
        # Snapshot format lama (peta balance) tetap dipulihkan seperti semula.
        if isinstance(remote_alert, dict) \
                and not _is_summary_alert_state(remote_alert):
            try:
                from telegram_alerts import compact_alert_state
                local_alert = slot.get("alert_state") or {}
                remote_ts = _int((remote_alert.get("rolling") or {}).get("ts"))
                local_ts = _int((local_alert.get("rolling") or {}).get("ts"))
                if not local_alert or remote_ts >= local_ts:
                    slot["alert_state"] = compact_alert_state(remote_alert)
            except Exception:  # noqa: BLE001 - history tetap dapat dipakai
                pass
        remote_chrono = _sanitize_remote_chronology(token.get("chronology"))
        local_chrono = slot.get("chronology") if isinstance(
            slot.get("chronology"), dict) else {}
        local_n = len(local_chrono.get("intervals") or [])
        remote_n = len((remote_chrono or {}).get("intervals") or []) if (
            isinstance(remote_chrono, dict)) else 0
        if isinstance(remote_chrono, dict) and remote_chrono and (
                not local_chrono or remote_n > local_n
                or (not (local_chrono.get("latest_wallets") or {}).get("wallets")
                    and (remote_chrono.get("latest_wallets") or {}).get(
                        "wallets"))):
            try:
                from holder_chronology import compact_chronology
                merged = {
                    "baseline_wallets": (
                        local_chrono.get("baseline_wallets")
                        or remote_chrono.get("baseline_wallets")),
                    "latest_wallets": (
                        local_chrono.get("latest_wallets")
                        if (local_chrono.get("latest_wallets") or {}).get(
                            "wallets")
                        else remote_chrono.get("latest_wallets")),
                    "intervals": (local_chrono.get("intervals")
                                  or remote_chrono.get("intervals") or []),
                }
                if remote_n > local_n:
                    merged["intervals"] = remote_chrono.get("intervals") or []
                    if (remote_chrono.get("latest_wallets") or {}).get(
                            "wallets"):
                        merged["latest_wallets"] = remote_chrono.get(
                            "latest_wallets")
                slot["chronology"] = compact_chronology(merged)
            except Exception:  # noqa: BLE001
                pass
        if not slot.get("baseline"):
            remote_base = token.get("baseline")
            if isinstance(remote_base, dict) and remote_base:
                slot["baseline"] = remote_base
        if not slot.get("latest_detail"):
            remote_latest = token.get("latest_detail")
            if isinstance(remote_latest, dict) and remote_latest:
                slot["latest_detail"] = remote_latest
    return store


def compact_history_for_status(store: dict | None, mint: str) -> list[dict]:
    """Salinan titik 4 jam (resampling) untuk payload dashboard."""
    return resample_4h(history_for_mint(store, mint))
# ---------------------------------------------------------------------------
# Backup durable store — holder_history.json.gz di ref holder-live
# ---------------------------------------------------------------------------
# Snapshot holder_status.json hanya untuk tampilan dashboard, jadi state kerja
# (peta balance alert/kohort, baseline scan FULL, kronologi) dibackup terpisah.
# Payload dikompresi gzip: JSON store penuh berpuluh MB jadi ±1/10-nya, sehingga
# satu file cukup (tanpa prune) dan pull di UI jauh lebih ringan.
BACKUP_FORMAT = "gzip+json"


def backup_enabled() -> bool:
    """Kill-switch backup durable: ``HOLDER_STORE_BACKUP=0`` mematikan pull+push.

    Berguna untuk dev offline / tes; default aktif supaya cron dan dashboard
    mendapat store yang sama meski filesystem-nya ephemeral.
    """
    value = os.environ.get("HOLDER_STORE_BACKUP", "1").strip().lower()
    return value not in ("0", "false", "no", "off")
MAX_BACKUP_BYTES = 3_500_000   # terkompresi; PUT 2,85 MB sudah terbukti jalan
DURABLE_CACHE_TTL = 600        # detik — UI/cron tidak pull di setiap rerun
_DURABLE_CACHE: dict[str, dict] = {}


def _int_ts(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def store_backup_bytes(store: dict | None) -> bytes:
    """Serialize store ke bytes gzip (JSON compact) untuk backup durable."""
    store = store if isinstance(store, dict) else {}
    tokens = store.get("tokens")
    payload = {
        "updated_at": store.get("updated_at"),
        "tokens": tokens if isinstance(tokens, dict) else {},
    }
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return gzip.compress(text.encode("utf-8"), 6)


def parse_store_backup(payload) -> dict | None:
    """Baca bytes backup → store. Toleran gzip maupun JSON polos."""
    if not payload:
        return None
    raw = payload if isinstance(payload, (bytes, bytearray)) else None
    if raw is None:
        return None
    text = None
    try:
        text = gzip.decompress(raw).decode("utf-8")
    except (OSError, EOFError, ValueError, UnicodeDecodeError, zlib.error):
        try:
            text = bytes(raw).decode("utf-8")
        except (TypeError, UnicodeDecodeError, ValueError):
            return None
    try:
        return _parse_store(json.loads(text))
    except (ValueError, TypeError):
        return None


def _pick_by_ts(current, incoming, *, oldest: bool = False) -> dict:
    """Pilih detail scan: default paling baru; ``oldest=True`` untuk baseline."""
    current = current if isinstance(current, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    if not incoming:
        return current
    if not current:
        return incoming
    left, right = _int_ts(current.get("ts")), _int_ts(incoming.get("ts"))
    if oldest:
        # baseline scan FULL immutable: yang paling tua yang dipertahankan.
        return current if (left and (not right or left <= right)) else incoming
    return incoming if right >= left else current


def _pick_cohort(current, incoming) -> dict:
    """Kohort beku: utamakan yang punya balance, lalu ``frozen_at`` terbaru."""
    current = current if isinstance(current, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}

    def _has(cohort):
        return bool(isinstance(cohort.get("balances"), dict)
                    and cohort.get("balances"))

    if _has(current) != _has(incoming):
        return current if _has(current) else incoming
    if not _has(current):
        return current or incoming
    if _int_ts(incoming.get("frozen_at")) >= _int_ts(current.get("frozen_at")):
        return incoming
    return current


def _is_summary_alert_state(state) -> bool:
    """True bila ``alert_state`` snapshot adalah RINGKASAN, bukan peta wallet.

    Snapshot ramping mengirim ``{"summary": True, "balances": <jumlah>}``;
    snapshot format lama mengirim peta balance. Yang lama tetap dipulihkan —
    termasuk saat petanya kosong — supaya ``sent_event_ids``/``last_sent``
    (dedup alert) tidak hilang ketika backup durable belum tersedia.
    """
    if not isinstance(state, dict) or state.get("summary"):
        return True
    for key in ("baseline", "rolling"):
        snap = state.get(key)
        if isinstance(snap, dict) and snap.get("balances") is not None \
                and not isinstance(snap.get("balances"), dict):
            return True
    return False


def _has_wallet_map(snap) -> bool:
    return bool(isinstance(snap, dict) and isinstance(snap.get("wallets"), dict)
                and snap.get("wallets"))


def _pick_chrono_snap(current, incoming, *, oldest: bool = False) -> dict:
    """Snapshot kronologi: utamakan yang masih membawa peta wallet."""
    current = current if isinstance(current, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    if not incoming:
        return current
    if not current:
        return incoming
    if _has_wallet_map(current) != _has_wallet_map(incoming):
        return current if _has_wallet_map(current) else incoming
    return _pick_by_ts(current, incoming, oldest=oldest)


def _merge_intervals(*groups) -> list:
    """Union interval kronologi per (from_ts, to_ts); movements terbanyak menang."""
    by_key: dict = {}
    for group in groups:
        for item in group or []:
            if not isinstance(item, dict):
                continue
            key = (_int_ts(item.get("from_ts")), _int_ts(item.get("to_ts")))
            previous = by_key.get(key)
            if previous is None or len(item.get("movements") or []) > len(
                    previous.get("movements") or []):
                by_key[key] = item
    return [by_key[key] for key in sorted(by_key)][-MAX_CHRONOLOGY_INTERVALS:]


def _merge_chronology(current, incoming) -> dict:
    current = current if isinstance(current, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    if not incoming:
        return current
    if not current:
        return incoming
    return {
        "baseline_wallets": _pick_chrono_snap(current.get("baseline_wallets"),
                                              incoming.get("baseline_wallets"),
                                              oldest=True),
        "latest_wallets": _pick_chrono_snap(current.get("latest_wallets"),
                                            incoming.get("latest_wallets")),
        "intervals": _merge_intervals(current.get("intervals"),
                                      incoming.get("intervals")),
    }


def _merge_alert_state(current, incoming) -> dict:
    """Gabung state alert: snapshot terbaru, event id union, last_sent max."""
    current = current if isinstance(current, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    if not incoming:
        return current
    if not current:
        return incoming
    try:
        from telegram_alerts import (MAX_LAST_SENT, MAX_REJECTED_SIGNALS,
                                     MAX_SENT_EVENT_IDS)
    except Exception:  # noqa: BLE001 - batas default bila import gagal
        MAX_SENT_EVENT_IDS, MAX_LAST_SENT, MAX_REJECTED_SIGNALS = 96, 8, 8
    merged = dict(current)
    for key in ("baseline", "rolling"):
        picked = _pick_by_ts(current.get(key), incoming.get(key))
        if picked:
            merged[key] = picked
    # Marker ``early_dump`` (titik terakhir yang direkam rule early dump) dan
    # marker ``high_drop`` (titik high rule HIGH DROP): yang paling baru
    # menang, sama seperti rolling/latest_detail.
    for key in ("early_dump", "high_drop"):
        picked = _pick_by_ts(current.get(key), incoming.get(key))
        if picked:
            merged[key] = picked
    ids = list(dict.fromkeys(
        [str(item) for item in (current.get("sent_event_ids") or []) if item]
        + [str(item) for item in (incoming.get("sent_event_ids") or []) if item]
    ))
    merged["sent_event_ids"] = ids[-MAX_SENT_EVENT_IDS:]
    last = {str(key): _int_ts(ts)
            for key, ts in (current.get("last_sent") or {}).items()
            if _int_ts(ts)}
    for key, ts in (incoming.get("last_sent") or {}).items():
        ts = _int_ts(ts)
        if ts and ts >= last.get(str(key), 0):
            last[str(key)] = ts
    merged["last_sent"] = dict(sorted(last.items(),
                                      key=lambda item: -item[1])[:MAX_LAST_SENT])
    rejected = ([row for row in (current.get("rejected_signals") or [])
                 if isinstance(row, dict)]
                + [row for row in (incoming.get("rejected_signals") or [])
                   if isinstance(row, dict)])
    merged["rejected_signals"] = rejected[-MAX_REJECTED_SIGNALS:]
    return merged


def merge_stores(*stores) -> dict:
    """Gabung beberapa store; **argumen belakang menang** bila timestamp seri.

    Cron memakai ``merge_stores(lokal, remote)`` (remote = akumulasi run
    sebelumnya), UI memakai ``merge_stores(remote, lokal)`` supaya scan manual
    yang baru ditulis tetap menang. Aturan per bagian:

    - ``points``        : union per timestamp (``merge_points``), cap MAX_POINTS.
    - ``baseline``      : yang paling **tua** (baseline scan FULL immutable).
    - ``latest_detail`` : yang paling baru.
    - ``cohort``        : yang punya balance, lalu ``frozen_at`` terbaru.
    - ``chronology``    : interval union; snapshot wallet yang punya peta menang
      (baseline paling tua, latest paling baru).
    - ``alert_state``   : snapshot baseline/rolling terbaru; ``sent_event_ids``
      union; ``last_sent`` max per kunci; ``rejected_signals`` gabungan;
      marker ``early_dump`` (rule EARLY DUMP) dan ``high_drop`` (titik high
      rule HIGH DROP) yang paling baru menang.
    """
    out = empty_store()
    stamps = []
    for store in stores:
        if not isinstance(store, dict):
            continue
        stamps.append(_int_ts(store.get("updated_at")))
        for mint, slot in (store.get("tokens") or {}).items():
            if not mint or not isinstance(slot, dict):
                continue
            target = _token_slot(out, str(mint), str(slot.get("symbol") or "?"))
            if slot.get("symbol") and not target.get("symbol"):
                target["symbol"] = slot.get("symbol")
            points = merge_points(target.get("points") or [],
                                  slot.get("points") or [])
            target["points"] = points[-MAX_POINTS:] if len(points) > MAX_POINTS \
                else points
            baseline = _pick_by_ts(target.get("baseline"),
                                   slot.get("baseline"), oldest=True)
            if baseline:
                target["baseline"] = baseline
            latest = _pick_by_ts(target.get("latest_detail"),
                                 slot.get("latest_detail"))
            if latest:
                target["latest_detail"] = latest
            cohort = _pick_cohort(target.get("cohort"), slot.get("cohort"))
            if cohort:
                target["cohort"] = cohort
            chronology = _merge_chronology(target.get("chronology"),
                                           slot.get("chronology"))
            if chronology:
                target["chronology"] = chronology
            state = _merge_alert_state(target.get("alert_state"),
                                       slot.get("alert_state"))
            if state:
                target["alert_state"] = state
    stamps = [stamp for stamp in stamps if stamp]
    out["updated_at"] = max(stamps) if stamps else None
    return out


def prune_store_for_backup(store: dict | None,
                           max_bytes: int = MAX_BACKUP_BYTES):
    """Pangkas store sampai payload gzip ≤ ``max_bytes``.

    Return ``(store, dropped)``. Urutan pembuangan (yang paling sedikit
    informasinya lebih dulu) — baseline scan FULL dibuang paling akhir karena
    itulah pembanding kronologi yang tidak bisa dibuat ulang tanpa scan FULL:

    1. movements pada interval kronologi lama (sisakan 3 interval terbaru),
    2. interval kronologi di luar 6 terbaru,
    3. peta wallet kronologi (jumlahnya tetap),
    4. ``points[].buckets`` (komposisi bucket per titik),
    5. titik di luar **42 bucket 4 jam terakhir** (7 hari grafik) — titik
       mentah per jam (cron hourly sejak 2026-09-04) di-resample dulu ke
       bucket 4 jam supaya backup tetap menyimpan ~7 hari grafik, bukan 42
       jam; ``resample_4h`` memakai titik terakhir per bucket,
    6. ``latest_detail``.
    """
    dropped: list = []
    if not isinstance(store, dict):
        return empty_store(), dropped
    if len(store_backup_bytes(store)) <= max_bytes:
        return store, dropped
    pruned = copy.deepcopy(store)
    tokens = pruned.get("tokens") if isinstance(pruned.get("tokens"), dict) \
        else {}

    def _each_slot():
        for slot in tokens.values():
            if isinstance(slot, dict):
                yield slot

    def drop_old_movements():
        for slot in _each_slot():
            chrono = slot.get("chronology")
            intervals = (chrono or {}).get("intervals") if isinstance(
                chrono, dict) else None
            if not isinstance(intervals, list) or len(intervals) <= 3:
                continue
            for interval in intervals[:-3]:
                if isinstance(interval, dict) and interval.get("movements"):
                    interval["movements"] = []

    def trim_intervals():
        for slot in _each_slot():
            chrono = slot.get("chronology")
            if isinstance(chrono, dict) and isinstance(
                    chrono.get("intervals"), list):
                chrono["intervals"] = chrono["intervals"][-6:]

    def drop_chrono_wallets():
        for slot in _each_slot():
            chrono = slot.get("chronology")
            if not isinstance(chrono, dict):
                continue
            for key in ("baseline_wallets", "latest_wallets"):
                snap = chrono.get(key)
                if isinstance(snap, dict) and isinstance(snap.get("wallets"),
                                                         dict):
                    snap["wallets"] = {}

    def drop_point_buckets():
        for slot in _each_slot():
            for point in slot.get("points") or []:
                if isinstance(point, dict):
                    point.pop("buckets", None)

    def trim_points():
        # 42 titik mentah per jam = 42 jam saja (sebelumnya 7 hari saat
        # cadence 6×/hari). Tangga pangkas ini mencari "grafik 7 hari di
        # backup": resample ke bucket 4 jam dulu, baru sisakan 42 bucket
        # terakhir (titik terakhir per bucket menang).
        for slot in _each_slot():
            points = slot.get("points")
            if isinstance(points, list) and len(points) > 42:
                slot["points"] = resample_4h(points)[-42:]

    def drop_latest_detail():
        for slot in _each_slot():
            slot.pop("latest_detail", None)

    steps = [
        ("chronology.movements interval lama", drop_old_movements),
        ("chronology.intervals di luar 6 terbaru", trim_intervals),
        ("chronology peta wallet", drop_chrono_wallets),
        ("points[].buckets", drop_point_buckets),
        ("points di luar 42 bucket 4 jam terakhir (7 hari)", trim_points),
        ("latest_detail", drop_latest_detail),
    ]
    for label, step in steps:
        step()
        dropped.append(label)
        if len(store_backup_bytes(pruned)) <= max_bytes:
            break
    return pruned, dropped


def publish_holder_history(store: dict | None, *, push: bool = True,
                           save_local: bool = False,
                           message: str | None = None,
                           path: str | None = None,
                           repo_path: str | None = None) -> dict:
    """Backup store penuh (gzip) ke ref ``holder-live``.

    ``repo_path`` default ``holder_history.json.gz``; Robinhood memakai
    ``holder_history_robinhood.json.gz`` supaya store kedua jaringan tidak
    tercampur.

    ``save_local=True`` juga menulis ``holder_history.json`` di disk — hanya
    untuk pemanggil yang belum menyimpan store (mis. pemulihan manual); cron
    memakai default ``False`` karena ``ingest_many`` sudah menyimpan store yang
    sama. ``push=False`` = tidak menyentuh GitHub (dipakai ``--no-push``/tes).
    Tidak pernah melempar: kegagalan backup dilaporkan lewat return value
    supaya cron tetap berjalan (snapshot dashboard lebih penting).
    """
    store = store if isinstance(store, dict) else empty_store()
    result = {"ok": None, "error": "", "bytes": 0, "pruned": [],
              "pushed": False, "over_budget": False, "saved_local": False}
    if save_local:
        try:
            save_holder_history(store, path)
            result["saved_local"] = True
        except Exception as exc:  # noqa: BLE001 - jangan matikan cron
            result["error"] = f"local write failed: {exc}"
            print(f"WARN: holder_history local write failed: {exc}")
            return result
    if not push:
        return result
    if not backup_enabled():
        result["error"] = "disabled (HOLDER_STORE_BACKUP=0)"
        return result
    try:
        from holder_status import push_store_backup
    except Exception as exc:  # noqa: BLE001 - transport opsional
        result.update(ok=False, error=f"transport unavailable: {exc}")
        return result
    payload = store_backup_bytes(store)
    if len(payload) > MAX_BACKUP_BYTES:
        pruned, dropped = prune_store_for_backup(store, MAX_BACKUP_BYTES)
        payload = store_backup_bytes(pruned)
        result["pruned"] = dropped
        print(f"WARN: holder_history backup dipangkas ({', '.join(dropped)}) "
              f"-> {len(payload)} bytes")
    stamp = store.get("updated_at") or int(time.time())
    try:
        ok = push_store_backup(
            payload, message or f"holder-history: backup {stamp} [skip ci]",
            repo_path=repo_path)
    except Exception as exc:  # noqa: BLE001 - backup tidak boleh mematikan cron
        result.update(ok=False, error=f"push raised: {exc}")
        print(f"WARN: holder_history backup push error: {exc}")
        return result
    result.update(ok=bool(ok), bytes=len(payload), pushed=bool(ok),
                  over_budget=bool(len(payload) > MAX_BACKUP_BYTES),
                  error="" if ok else "github push failed")
    if not ok:
        print("WARN: holder_history backup push gagal — store lokal tetap "
              "tersimpan, snapshot dashboard tidak terpengaruh")
    return result


def pull_holder_history(repo_path: str | None = None) -> dict | None:
    """Ambil backup store durable dari ref ``holder-live``; ``None`` bila gagal.

    ``repo_path`` default ``holder_history.json.gz``; Robinhood memakai
    ``holder_history_robinhood.json.gz``.
    """
    if not backup_enabled():
        return None
    try:
        from holder_status import pull_store_backup
    except Exception:  # noqa: BLE001 - transport opsional
        return None
    try:
        return parse_store_backup(pull_store_backup(repo_path=repo_path))
    except Exception as exc:  # noqa: BLE001 - backup tidak boleh mematikan cron
        print(f"WARN: holder_history backup parse failed: {exc}")
        return None


def load_durable_holder_history(*, ttl: int = DURABLE_CACHE_TTL,
                                force: bool = False,
                                path: str | None = None,
                                repo_path: str | None = None) -> dict:
    """Store lokal + backup durable (cache TTL) — dipakai UI dan cron.

    ``path``/``repo_path`` default Solana; Robinhood memakai
    ``holder_history_robinhood.json`` dan backup
    ``holder_history_robinhood.json.gz``.

    Lingkungan ephemeral (runner Actions, Streamlit Cloud) mulai dari file
    kosong; backup durable mengembalikan baseline scan FULL, kohort, state
    alert, dan kronologi. Store **lokal menang** bila timestamp seri, supaya
    scan manual yang baru dijalankan tidak ditimpa backup lama.
    """
    repo_path = str(repo_path or "holder_history.json.gz").strip().lstrip("/")
    local = load_holder_history(path)
    now = time.time()
    cached = _DURABLE_CACHE.get(repo_path) or {}
    if (not force and isinstance(cached.get("data"), dict)
            and (now - float(cached.get("ts") or 0.0)) < max(0, ttl)):
        remote = cached["data"]
    else:
        remote = pull_holder_history(repo_path=repo_path)
        if isinstance(remote, dict):
            _DURABLE_CACHE[repo_path] = {"data": remote, "ts": now}
        else:
            remote = cached.get("data") if isinstance(cached.get("data"), dict) else None
    if not isinstance(remote, dict):
        return local
    return merge_stores(remote, local)


def reset_durable_cache() -> None:
    """Test helper: kosongkan cache backup durable."""
    _DURABLE_CACHE.clear()
