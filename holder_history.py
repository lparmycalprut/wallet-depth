# -*- coding: utf-8 -*-
"""Pencatatan analisa holder (dust + kohort mid-tier) untuk grafik 4 jam.

File store: ``holder_history.json``. Setiap scan menambahkan titik
(dust count, dust % MC, sisa token kohort Crab+Fish yang di-freeze).
Dashboard meresample ke bucket 4 jam. Snapshot ``silent_status``
menyimpan salinan ringkas ``history`` supaya cron GitHub tetap punya
jejak antar-run.

Ambang dust (observasi dump) — satu garis:
- >= 1% MC  → BAHAYA (disembunyikan dari Scan Meteora)
"""
from __future__ import annotations

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
# alias lama (kompatibilitas import)
DUST_CAUTION_PCT = DUST_DANGER_PCT
DUST_LIMIT_PCT = DUST_DANGER_PCT
INTERVAL_SEC = 4 * 3600          # grafik 4 jam sekali
COHORT_WINDOW_SEC = 4 * 3600     # freeze Crab+Fish tiap 4 jam
COHORT_MAX = 200                 # address yang diikuti
MID_USD_MIN = 100.0              # Crab bawah (wallet_depth: > $100)
MID_USD_MAX = 10_000.0           # Fish atas (<= $10k)
MAX_POINTS = 84                  # 14 hari × 6 bucket 4 jam
MIN_POINT_GAP_SEC = 8 * 60       # jangan dobel-titik < 8 menit

# Scan manual (halaman Holder) = FULL: ambil seluruh holder, bukan sampel.
# Cron hanya mencatat perubahan (titik ringkas), jadi detail hasil scan
# pertama (``baseline``) tetap tersimpan apa adanya.
FULL_SCAN_MAX_WALLETS = 100_000

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


def dust_flag(dust_pct_mc, prev_pct=None) -> dict:
    """Klasifikasi dust % MC: ok / danger.

    ``hide`` True jika dust **≥ 1% MC** (BAHAYA — disembunyikan dari
    Scan Meteora).
    ``rising`` True jika % MC naik dibanding titik sebelumnya.
    """
    pct = _float(dust_pct_mc, None)
    prev = _float(prev_pct, None)
    rising = bool(pct is not None and prev is not None and pct > prev)
    if pct is None:
        return {"level": "unknown", "label": "—", "hide": False,
                "rising": False, "pct": None}
    if pct >= DUST_DANGER_PCT:
        return {"level": "danger", "label": "BAHAYA", "hide": True,
                "rising": rising, "pct": pct}
    return {"level": "ok", "label": "AMAN", "hide": False,
            "rising": rising, "pct": pct}


def should_hide_dust(dust_pct_mc) -> bool:
    """True bila dust holder memegang ≥ 1% marketcap (BAHAYA)."""
    return bool(dust_flag(dust_pct_mc)["hide"])


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
    """Titik history tanpa peta address (aman untuk silent_status)."""
    point = point or {}
    keys = ("ts", "price", "mc", "dust_count", "dust_pct_mc", "dust_value_usd",
            "real_count", "real_pct_mc", "mid_count", "mid_pct_mc",
            "cohort_token_pct", "cohort_cut50_pct", "cohort_n",
            "holder_count", "buckets", "full")
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

    ``detail=True`` (scan **full** manual) juga menyimpan rekaman detail:
    ``baseline`` ditulis sekali saja pada scan full pertama dan **tidak
    pernah ditimpa** (itu data awal milik user), sementara
    ``latest_detail`` diperbarui tiap scan full. Cron memakai
    ``detail=False`` sehingga hanya menambah titik perubahan.
    """
    mint = str(mint or "").strip()
    if not mint or not isinstance(analysis, dict):
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
    if detail:
        snapshot = detail_snapshot(analysis, now)
        if not (isinstance(slot.get("baseline"), dict)
                and slot.get("baseline")):
            slot["baseline"] = snapshot
        slot["latest_detail"] = snapshot
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

    ``detail=True`` hanya dipakai scan full manual (menyimpan baseline /
    detail terbaru); cron memakai default ``False``.
    """
    store = dict(store or load_holder_history(path))
    store.setdefault("tokens", {})
    stamp = int(now or time.time())
    for mint, analysis in (analyses or {}).items():
        ingest_one(store, mint, analysis, now=stamp, detail=detail)
    return save_holder_history(store, path)


def seed_from_status(store: dict, status: dict | None) -> dict:
    """Isi titik dari snapshot silent_status bila file history masih tipis."""
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
        local_cohort = slot.get("cohort") if isinstance(slot.get("cohort"), dict) else {}
        if (isinstance(remote_cohort, dict) and remote_cohort.get("balances")
                and not (local_cohort or {}).get("balances")):
            slot["cohort"] = {
                "frozen_at": remote_cohort.get("frozen_at"),
                "balances": dict(remote_cohort.get("balances") or {}),
            }
    return store


def compact_history_for_status(store: dict | None, mint: str) -> list[dict]:
    """Salinan titik 4 jam (resampling) untuk payload dashboard."""
    return resample_4h(history_for_mint(store, mint))
