"""Daily CVD calculations + incremental 4-hour chunk storage.

The browser extension is the reference for day-by-day accounting: buy volume
minus sell volume is CVD, total volume is buy plus sell, and a dry day is a
40%+ volume contraction with a nearly flat CVD ratio.

4-hour chunks live in ``data/cvd_4h_chunks/<mint>.json`` so the 00:00 UTC
daily job can aggregate six already-fetched windows instead of walking
24 hours of GMGN/Helius pages under a rate-limit budget.
"""
import json
import os
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _atomic_write_json(path, data, **dump_kwargs):
    """Local atomic JSON write — avoids importing core (pandas)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, **dump_kwargs)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


CHUNK_DIR = os.path.join(BASE_DIR, "data", "cvd_4h_chunks")
DAILY_CVD_PATH = os.path.join(BASE_DIR, "cvd_daily.json")

DRY_VOLUME_DROP_PCT = -40.0
DRY_CVD_RATIO_PCT = 10.0
CHUNK_SEC = 4 * 3600
WHALE_SOL_DAILY = 1.0


def _day_key(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()


def calculate_daily_cvd(swaps):
    """Return extension-compatible daily rows, oldest first.

    Extra fields (avg order size, whale net, absorption %) are additive so
    existing consumers of ``status`` / ``cvd_ratio_pct`` stay valid.
    """
    days = defaultdict(lambda: {
        "buy_tx": 0, "sell_tx": 0,
        "buy_sol": 0.0, "sell_sol": 0.0,
        "whale_buy_sol": 0.0, "whale_sell_sol": 0.0,
        "wallets": set(),
    })
    for row in swaps or []:
        if len(row) < 4:
            continue
        side = str(row[0]).lower()
        amount = float(row[1])
        ts = int(row[2])
        wallet = str(row[3])
        if side not in {"buy", "sell"} or amount <= 0:
            continue
        day = days[_day_key(ts)]
        day["wallets"].add(wallet)
        key = "buy" if side == "buy" else "sell"
        day[f"{key}_tx"] += 1
        day[f"{key}_sol"] += amount
        if amount >= WHALE_SOL_DAILY:
            day[f"whale_{key}_sol"] += amount
    result, running = [], 0.0
    previous_volume = None
    for date in sorted(days):
        d = days[date]
        volume = d["buy_sol"] + d["sell_sol"]
        delta = d["buy_sol"] - d["sell_sol"]
        running += delta
        change = ((volume - previous_volume) / previous_volume * 100.0
                  if previous_volume else None)
        ratio = delta / volume * 100.0 if volume else 0.0
        absorption = abs(ratio)
        tx = d["buy_tx"] + d["sell_tx"]
        buy_pct = d["buy_tx"] / tx * 100.0 if tx else 0.0
        sell_pct = d["sell_tx"] / tx * 100.0 if tx else 0.0
        avg_buy = d["buy_sol"] / d["buy_tx"] if d["buy_tx"] else 0.0
        avg_sell = d["sell_sol"] / d["sell_tx"] if d["sell_tx"] else 0.0
        whale_net = d["whale_buy_sol"] - d["whale_sell_sol"]
        if (change is not None and change <= DRY_VOLUME_DROP_PCT
                and abs(ratio) <= DRY_CVD_RATIO_PCT):
            status = "KERING / TEST SUPLAI (LPS)"
        elif abs(ratio) < 3.0:
            status = "DATAR / PENYERAPAN (ABSORPTION)"
        elif abs(ratio) <= 7.5:
            status = "DATAR / PENYERAPAN (ABSORPTION)"
        elif ratio > 7.5 and buy_pct >= 52:
            status = "NAIK TAJAM / AGGRESSIVE BUY (MARK-UP)"
        elif ratio < -15:
            status = "TURUN / DISTRIBUSI / DUMP"
        else:
            status = "NORMAL"
        result.append({
            "date": date,
            "total_tx": tx,
            "buy_tx": d["buy_tx"],
            "sell_tx": d["sell_tx"],
            "buy_tx_pct": round(buy_pct, 2),
            "sell_tx_pct": round(sell_pct, 2),
            "volume_sol": round(volume, 8),
            "volume_change_pct": (
                round(change, 2) if change is not None else None
            ),
            "delta_sol": round(delta, 8),
            "cvd_ratio_pct": round(ratio, 2),
            "absorption_pct": round(absorption, 2),
            "running_cvd_sol": round(running, 8),
            "status": status,
            "unique_wallets": len(d["wallets"]),
            "avg_buy_sol": round(avg_buy, 6),
            "avg_sell_sol": round(avg_sell, 6),
            "whale_buy_sol": round(d["whale_buy_sol"], 8),
            "whale_sell_sol": round(d["whale_sell_sol"], 8),
            "whale_net_sol": round(whale_net, 8),
        })
        previous_volume = volume
    return result


def tx_dominance_from_daily(rows):
    """Per-day buy vs sell TX counts and dominance percentages.

    ``dominant`` is ``buy`` / ``sell`` / ``even``. Percentages are
    recomputed from counts so a missing ``sell_tx_pct`` field on older
    snapshots still yields a complete row.
    """
    out = []
    for row in rows or []:
        try:
            buy_tx = int(row.get("buy_tx") or 0)
        except (TypeError, ValueError):
            buy_tx = 0
        try:
            sell_tx = int(row.get("sell_tx") or 0)
        except (TypeError, ValueError):
            sell_tx = 0
        total = buy_tx + sell_tx
        buy_pct = buy_tx / total * 100.0 if total else 0.0
        sell_pct = sell_tx / total * 100.0 if total else 0.0
        if buy_pct > sell_pct:
            dominant = "buy"
        elif sell_pct > buy_pct:
            dominant = "sell"
        else:
            dominant = "even"
        out.append({
            "date": row.get("date"),
            "buy_tx": buy_tx,
            "sell_tx": sell_tx,
            "total_tx": total,
            "buy_tx_pct": round(buy_pct, 2),
            "sell_tx_pct": round(sell_pct, 2),
            "dominant": dominant,
        })
    return out


def complete_daily_rows(rows, *, now_ts=None):
    """Return only rows for UTC days that have already finished.

    The daily digest runs shortly after 00:00 UTC, so the newest row produced
    by :func:`calculate_daily_cvd` is normally a still-running day holding
    barely an hour of swaps. Reporting that partial row as the daily status
    yields nonsense (a handful of TX, a fake -96..-100% volume change vs the
    full previous day, and bogus KERING/MARK-UP verdicts). Daily status is
    only valid for a day that is already complete, so drop any row dated
    today (or later) in UTC.
    """
    today = datetime.fromtimestamp(
        int(now_ts if now_ts is not None else time.time()),
        timezone.utc).date().isoformat()
    return [row for row in (rows or [])
            if str((row or {}).get("date") or "") < today]


def dry_baseline_stale(stored_date, rows, *, now_ts=None):
    """True when a stored dry-day baseline is no longer backed by real data.

    ``stored_date`` is the ``priority_dry_vol_date`` remembered on a watchlist
    entry and ``rows`` are complete daily rows (see
    :func:`complete_daily_rows`). A baseline is stale when either:

    * it was captured from a UTC day that had not finished yet — exactly what
      the partial-day bug produced, e.g. a 67-minute slice reported as
      "KERING" with a hourly baseline dozens of times too low; or
    * that day is now complete and turned out not to be dry at all.

    A date that simply fell out of the lookback window is left alone: absence
    of data is not evidence the baseline was wrong.
    """
    if not stored_date:
        return False
    today = datetime.fromtimestamp(
        int(now_ts if now_ts is not None else time.time()),
        timezone.utc).date().isoformat()
    if str(stored_date) >= today:
        return True
    for row in rows or []:
        if (row or {}).get("date") == stored_date:
            return not str(row.get("status") or "").startswith("KERING")
    return False


def latest_dry_signal(rows):
    """Return the latest dry-day row, or None."""
    for row in reversed(rows or []):
        if row.get("status", "").startswith("KERING"):
            return row
    return None


# ---------------------------------------------------------------------------
# Incremental 4-hour chunks
# ---------------------------------------------------------------------------
def chunk_floor_ts(ts):
    """UTC 4-hour window open: 00 / 04 / 08 / 12 / 16 / 20."""
    return int(ts) // CHUNK_SEC * CHUNK_SEC


def chunk_key(ts):
    """Filename-safe key, e.g. ``2026-08-12T16``."""
    start = chunk_floor_ts(ts)
    return datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H")


def chunk_path(ca):
    safe = "".join(ch for ch in str(ca or "") if ch.isalnum())
    return os.path.join(CHUNK_DIR, f"{safe}.json")


def load_4h_chunks(ca):
    """Return the on-disk chunk document for ``ca`` (or an empty shell)."""
    path = chunk_path(ca)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f) or {}
        if isinstance(data, dict):
            data.setdefault("ca", ca)
            data.setdefault("chunks", {})
            return data
    except Exception:
        pass
    return {"ca": ca, "symbol": "?", "updated": 0, "chunks": {}}


def save_4h_chunks(doc):
    os.makedirs(CHUNK_DIR, exist_ok=True)
    ca = (doc or {}).get("ca") or "unknown"
    _atomic_write_json(chunk_path(ca), doc, separators=(",", ":"))


def _chunk_metrics(swaps):
    buy_tx = sell_tx = 0
    buy_sol = sell_sol = 0.0
    for row in swaps or []:
        if len(row) < 2:
            continue
        side = str(row[0]).lower()
        amount = float(row[1])
        if side == "buy":
            buy_tx += 1
            buy_sol += amount
        elif side == "sell":
            sell_tx += 1
            sell_sol += amount
    return {
        "buy_tx": buy_tx,
        "sell_tx": sell_tx,
        "buy_sol": round(buy_sol, 8),
        "sell_sol": round(sell_sol, 8),
        "delta_sol": round(buy_sol - sell_sol, 8),
        "volume_sol": round(buy_sol + sell_sol, 8),
        "n": buy_tx + sell_tx,
    }


def _normalize_swap(row):
    if len(row) < 4:
        return None
    side = str(row[0]).lower()
    try:
        amount = float(row[1])
        ts = int(row[2])
    except (TypeError, ValueError):
        return None
    if side not in {"buy", "sell"} or amount <= 0 or ts <= 0:
        return None
    return [side, amount, ts, str(row[3])]


def upsert_4h_chunk(ca, swaps, *, symbol="?", start_ts=None, end_ts=None):
    """Merge ``swaps`` into the 4-hour chunk covering ``start_ts``.

    When ``start_ts`` is omitted the chunk is inferred from the swaps
    themselves (one call may touch several windows).
    """
    doc = load_4h_chunks(ca)
    doc["ca"] = ca
    if symbol and symbol != "?":
        doc["symbol"] = symbol
    grouped = defaultdict(list)
    for row in swaps or []:
        norm = _normalize_swap(row)
        if not norm:
            continue
        ts = norm[2]
        if start_ts is not None and ts < int(start_ts):
            continue
        if end_ts is not None and ts >= int(end_ts):
            continue
        grouped[chunk_key(ts)].append(norm)
    if start_ts is not None and not grouped:
        key = chunk_key(start_ts)
        grouped[key] = []
    for key, rows in grouped.items():
        existing = (doc["chunks"].get(key) or {}).get("swaps") or []
        seen = {}
        for item in list(existing) + rows:
            norm = _normalize_swap(item)
            if not norm:
                continue
            seen[(norm[0], norm[1], norm[2], norm[3])] = norm
        merged = [seen[k] for k in sorted(seen, key=lambda x: x[2])]
        if merged:
            win_start = chunk_floor_ts(merged[0][2])
        elif start_ts is not None:
            win_start = chunk_floor_ts(start_ts)
        else:
            continue
        doc["chunks"][key] = {
            "start_ts": win_start,
            "end_ts": win_start + CHUNK_SEC,
            "swaps": merged,
            "metrics": _chunk_metrics(merged),
        }
    doc["updated"] = int(time.time())
    save_4h_chunks(doc)
    return doc


def save_4h_chunks_from_swaps(ca, swaps, *, symbol="?"):
    """Split an arbitrary swap list into 4-hour chunks and persist them."""
    return upsert_4h_chunk(ca, swaps, symbol=symbol)


def swaps_from_4h_chunks(ca, *, days=None, date=None, now_ts=None):
    """Flatten stored chunks into a chronological swap list.

    ``date`` (YYYY-MM-DD UTC) returns that calendar day only. ``days``
    keeps the last N * 24 hours from ``now_ts``.
    """
    doc = load_4h_chunks(ca)
    rows = []
    now_ts = int(now_ts if now_ts is not None else time.time())
    cutoff = None if days is None else now_ts - int(days) * 86400
    for chunk in (doc.get("chunks") or {}).values():
        for row in chunk.get("swaps") or []:
            norm = _normalize_swap(row)
            if not norm:
                continue
            if date and _day_key(norm[2]) != date:
                continue
            if cutoff is not None and norm[2] < cutoff:
                continue
            rows.append(tuple(norm))
    rows.sort(key=lambda r: r[2])
    return rows


def aggregate_chunks_to_daily(ca, *, days=7, now_ts=None):
    """Build daily CVD rows from stored 4-hour chunks (no network)."""
    return calculate_daily_cvd(
        swaps_from_4h_chunks(ca, days=days, now_ts=now_ts)
    )


def chunk_coverage_hours(ca, date):
    """How many hours of the UTC ``date`` are covered by stored chunks."""
    rows = swaps_from_4h_chunks(ca, date=date)
    if not rows:
        return 0.0
    span = max(r[2] for r in rows) - min(r[2] for r in rows)
    # Six complete 4h windows = 24h even if first/last swap sit inside.
    keys = {chunk_key(r[2]) for r in rows}
    if len(keys) >= 6:
        return 24.0
    return max(span / 3600.0, len(keys) * 4.0)


def persist_daily_snapshot(ca, symbol, rows, *, now_ts=None):
    """Append / overwrite ``cvd_daily.json`` for one token."""
    now_ts = int(now_ts or time.time())
    try:
        with open(DAILY_CVD_PATH, encoding="utf-8") as f:
            daily = json.load(f) or {}
    except Exception:
        daily = {}
    if not isinstance(daily, dict):
        daily = {}
    latest = (rows or [])[-1] if rows else {}
    slot = latest.get("date") or "unknown"
    entry = daily.setdefault(ca, {})
    entry[slot] = {
        "symbol": symbol,
        "rows": rows,
        "ts": now_ts,
    }
    _atomic_write_json(DAILY_CVD_PATH, daily, separators=(",", ":"))
    return latest


def load_latest_daily(ca):
    """Most recently persisted daily snapshot for ``ca``, or None."""
    try:
        with open(DAILY_CVD_PATH, encoding="utf-8") as f:
            daily = json.load(f) or {}
    except Exception:
        return None
    entry = (daily or {}).get(ca) or {}
    if not entry:
        return None
    newest = max(entry.values(), key=lambda item: item.get("ts") or 0)
    return newest


# --- First Buy Surge (awal fase MARK-UP) ------------------------------------
# Deteksi "lonjakan buy pertama" pada token prioritas (volume sudah kering).
# Empat kaki wajib lolos dalam jendela sample (default 15 menit):
#   1. VOLUME SURGE   — volume jendela >= +100% vs volume rata-rata per jam
#                       di fase kering H-1 (zona valid +100% s/d +300%+),
#                       plus floor absolut anti-debu.
#   2. BUY TX RATIO   — >= 60% transaksi adalah BUY (sebelumnya ~48-52%),
#                       dari banyak wallet unik (bukan 1 wallet spam).
#   3. CVD VELOCITY   — (buy_sol - sell_sol) / volume >= +20% (CVD berbelok
#                       tajam ke atas).
#   4. BIG-BUY CLUSTER — >= 3 transaksi buy >= 1 SOL (rentang 0.5-2 SOL)
#                       bertubi-tubi dan TANPA sell besar yang membalas.
FIRST_BUY_SURGE_DEFAULTS = {
    "window_sec": 900,             # jendela sample (cron 15 menit)
    "min_surge_pct": 100.0,        # lonjakan volume vs baseline kering/jam
    "min_window_volume_sol": 5.0,  # floor absolut bila baseline kecil/unknown
    "min_tx": 10,                  # sampel minimal ("dari 10 transaksi...")
    "min_buy_ratio_pct": 60.0,     # minimal 6-8 dari 10 tx adalah BUY
    "min_unique_buy_wallets": 5,   # buy dari wallet unik, bukan 1 wallet
    "min_cvd_ratio_pct": 20.0,     # Delta/Volume >= +20% (CVD velocity)
    "big_buy_sol": 1.0,            # ukuran "big buy" (valid 0.5-2 SOL)
    "min_big_buys": 3,             # 3-5 big buy bertubi-tubi
    "max_big_sells": 0,            # tanpa sell besar pembalas
}


def first_buy_surge(swaps, *, baseline_hourly_sol=None, now_ts=None,
                    **overrides):
    """Deteksi Lonjakan Buy Pertama (MARK-UP) pada sample swap terbaru.

    ``swaps`` adalah baris ``(side, sol, ts, wallet)``; ``baseline_hourly_sol``
    adalah volume rata-rata per jam token saat fase kering (H-1). Bila
    baseline tidak diketahui, kaki volume memakai floor absolut saja.
    """
    cfg = dict(FIRST_BUY_SURGE_DEFAULTS)
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    window = int(cfg["window_sec"])

    rows = [r for r in (swaps or []) if len(r) >= 4 and float(r[1]) > 0]
    if rows and now_ts is not None:
        cutoff = int(now_ts) - window
        rows = [r for r in rows if int(r[2]) >= cutoff]

    tx = len(rows)
    buy_rows = [r for r in rows if str(r[0]).lower() == "buy"]
    sell_rows = [r for r in rows if str(r[0]).lower() != "buy"]
    buy_sol = sum(float(r[1]) for r in buy_rows)
    sell_sol = sum(float(r[1]) for r in sell_rows)
    volume = buy_sol + sell_sol
    cvd = buy_sol - sell_sol
    buy_tx, sell_tx = len(buy_rows), len(sell_rows)
    unique_buy_wallets = len({str(r[3]) for r in buy_rows})
    buy_ratio_pct = buy_tx / tx * 100.0 if tx else 0.0
    cvd_ratio_pct = cvd / volume * 100.0 if volume else 0.0

    big = float(cfg["big_buy_sol"])
    big_buys = [r for r in buy_rows if float(r[1]) >= big]
    big_sells = [r for r in sell_rows if float(r[1]) >= big]
    big_buy_sol_total = sum(float(r[1]) for r in big_buys)

    # --- Kaki 1: volume surge vs baseline kering per jam --------------------
    baseline = (float(baseline_hourly_sol)
                if baseline_hourly_sol is not None else None)
    surge_pct = None
    if baseline is not None and baseline > 0:
        surge_pct = (volume / baseline - 1.0) * 100.0
        volume_ok = (surge_pct >= float(cfg["min_surge_pct"])
                     and volume >= float(cfg["min_window_volume_sol"]))
    elif baseline is not None:  # baseline 0: fase kering benar-benar nol
        volume_ok = volume >= float(cfg["min_window_volume_sol"])
    else:  # baseline tak diketahui -> floor absolut saja
        volume_ok = volume >= float(cfg["min_window_volume_sol"])

    # --- Kaki 2: rasio buy tx (sampel & wallet unik) ------------------------
    ratio_ok = (tx >= int(cfg["min_tx"])
                and buy_ratio_pct >= float(cfg["min_buy_ratio_pct"])
                and unique_buy_wallets >= int(cfg["min_unique_buy_wallets"]))

    # --- Kaki 3: CVD velocity -----------------------------------------------
    cvd_ok = volume > 0 and cvd_ratio_pct >= float(cfg["min_cvd_ratio_pct"])

    # --- Kaki 4: cluster big buy tanpa sell besar pembalas ------------------
    cluster_ok = (len(big_buys) >= int(cfg["min_big_buys"])
                  and len(big_sells) <= int(cfg["max_big_sells"]))

    checks = {"volume": bool(volume_ok), "buy_ratio": bool(ratio_ok),
              "cvd_velocity": bool(cvd_ok), "big_buy_cluster": bool(cluster_ok)}
    reasons = []
    if volume_ok:
        reasons.append(
            f"volume {volume:.2f} SOL"
            + (f" ({surge_pct:+.0f}% vs {baseline:.2f} SOL/jam kering)"
               if surge_pct is not None else " (baseline n/a, floor ok)"))
    else:
        reasons.append(
            "volume kurang: "
            + (f"{surge_pct:+.0f}% < +{cfg['min_surge_pct']:g}%"
               if surge_pct is not None
               else f"{volume:.2f} < {cfg['min_window_volume_sol']:g} SOL"))
    reasons.append(
        f"buy ratio {buy_ratio_pct:.0f}% ({buy_tx}/{tx} tx, "
        f"{unique_buy_wallets} wallet)" + (" ✓" if ratio_ok else " ✗"))
    reasons.append(f"CVD velocity {cvd_ratio_pct:+.1f}%"
                   + (" ✓" if cvd_ok else " ✗"))
    reasons.append(f"big-buy {len(big_buys)}x ≥{big:g} SOL / big-sell "
                   f"{len(big_sells)}x" + (" ✓" if cluster_ok else " ✗"))

    return {"triggered": all(checks.values()), "checks": checks,
            "reasons": reasons, "tx": tx, "buy_tx": buy_tx,
            "sell_tx": sell_tx, "volume_sol": volume, "cvd_sol": cvd,
            "buy_ratio_pct": buy_ratio_pct, "cvd_ratio_pct": cvd_ratio_pct,
            "unique_buy_wallets": unique_buy_wallets,
            "big_buys": len(big_buys), "big_sells": len(big_sells),
            "big_buy_sol_total": big_buy_sol_total,
            "big_buy_sol": big, "baseline_hourly_sol": baseline,
            "surge_pct": surge_pct, "window_sec": window}
