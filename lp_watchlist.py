# -*- coding: utf-8 -*-
"""Watchlist terpisah **Chart LP** — token dari Scan Meteora Pool.

Token yang ditambahkan dari Scan Meteora (``source="meteora"``) atau
ditambahkan manual ke card LP dikumpulkan di card **kolom kiri** grid
halaman utama (2026-09-09; dulu card paling atas dashboard).
Card ini menampilkan **grafik perubahan dust holder** (dust % MC per bucket
**5 menit** — mengikuti kadens cron lane LP — + jumlah wallet dust) beserta
garis ambang:

- ``>= 0,5% MC`` → HATI-HATI
- ``>= 1% MC``   → BAHAYA

Modul ini murni data + figure matplotlib (tanpa Streamlit) supaya bisa
diuji; ``app.py`` hanya merender hasilnya.

``matplotlib`` di-import **lazy** di dalam fungsi figure: cron
``scripts/scan_holders.py`` hanya memakai ``split_watchlist`` dan
workflow-nya cuma menginstal ``requests`` + ``curl_cffi`` (tanpa
matplotlib), jadi import top-level akan mematikan scan.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from holder_history import (DUST_CAUTION_PCT, DUST_DANGER_PCT,
                            LP_INTERVAL_SEC, dust_flag, dust_level_rank,
                            history_for_mint, holders_usable, merge_status_history,
                            point_usable, resample_5m, usable_points)
from watchlist_detail import DRIFT_TOLERANCE_PP

if TYPE_CHECKING:  # pragma: no cover - hanya untuk anotasi tipe
    from matplotlib.figure import Figure


def _pyplot():
    """Import ``matplotlib.pyplot`` saat dibutuhkan saja (lihat docstring)."""
    import matplotlib.pyplot as plt
    return plt

# ``source`` yang masuk card Chart LP (bukan watchlist holder biasa).
LP_SOURCES = ("meteora", "lp", "chart_lp")
LP_SOURCE = "meteora"

# Warna ambang dust (konsisten dengan badge UI).
COLOR_CAUTION = "#b45309"
COLOR_DANGER = "#b91c1c"
COLOR_OK = "#15803d"


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


def is_lp_source(meta) -> bool:
    """True bila entri watchlist berasal dari Scan Meteora / card LP."""
    source = str((meta or {}).get("source") or "").strip().lower()
    return source in LP_SOURCES


def split_watchlist(watchlist: dict | None) -> tuple[dict, dict]:
    """Pisah watchlist jadi ``(chart_lp, holder)`` tanpa mengubah urutan.

    Token LP tidak muncul dua kali: card Chart LP di atas dan watchlist
    holder di bawah saling eksklusif.
    """
    lp: dict = {}
    holder: dict = {}
    for mint, meta in (watchlist or {}).items():
        if not mint:
            continue
        if is_lp_source(meta):
            lp[mint] = meta or {}
        else:
            holder[mint] = meta or {}
    return lp, holder


def points_for_mint(mint: str, status_tokens: dict | None,
                    store: dict | None) -> list[dict]:
    """Gabung titik history file + salinan ringkas dari holder_status."""
    token = (status_tokens or {}).get(mint) or {}
    return merge_status_history(history_for_mint(store, mint),
                                (token or {}).get("history") or [])


def _delta_pp(before, after):
    """Selisih poin persentase; ``None`` bila salah satu sisi kosong."""
    left = _float(before, None)
    right = _float(after, None)
    if left is None or right is None:
        return None
    return round(right - left, 4)


def build_lp_row(mint: str, meta: dict | None, status_tokens: dict | None,
                 store: dict | None) -> dict:
    """Satu baris data card Chart LP (siap dirender ``app.py``).

    Snapshot/titik yang datanya tidak lengkap (:func:`holder_history.
    holders_usable` / :func:`point_usable`) **tidak** dipakai sebagai angka:
    provider holder bisa mengembalikan sampel pendek (kasus nyata 20 holder)
    yang selalu berisi ``dust 0`` / ``0,00% MC``. Baris memakai scan layak
    terbaru dan menandai ``degraded`` supaya UI bilang angka itu bukan hasil
    run terakhir.
    """
    meta = meta or {}
    token = (status_tokens or {}).get(mint) or {}
    holders = token.get("holders") if isinstance(token.get("holders"), dict) \
        else {}
    points = points_for_mint(mint, status_tokens, store)
    sampled = resample_5m(usable_points(points))

    holders_ok = bool(holders) and holders_usable(holders)
    # Sumber angka baris: kandidat TERBARU yang datanya layak menang
    # (snapshot cron ATAU titik history — scan manual app yang titik
    # history-nya lebih baru dari snapshot, atau sebaliknya). Dulu baris
    # selalu memprioritaskan snapshot walau titik history lebih baru,
    # sehingga baris bisa menampilkan angka basi sementara grafik di
    # bawahnya sudah menunjukkan titik yang baru ("tidak sinkron").
    snapshot_pct = _float(holders.get("dust_pct_mc"), None) if holders_ok \
        else None
    snapshot_count = holders.get("dust_count") if holders_ok else None
    snapshot_ts = _int(token.get("analyzed_at"), 0) if holders_ok else 0
    last_sampled = sampled[-1] if sampled else {}
    history_pct = _float(last_sampled.get("dust_pct_mc"), None)
    history_count = last_sampled.get("dust_count")
    history_ts = _int(last_sampled.get("ts"), 0) if sampled else 0

    use_history = (history_ts > snapshot_ts and history_pct is not None)
    # Truncated scans have already been rejected by the usability guards.
    # Keep the existing UI warning when a newer partial scan was skipped.
    newest_raw = points[-1] if points else {}
    truncation_swap = bool(holders_ok and newest_raw.get("truncated")
                           and _int(newest_raw.get("ts"), 0)
                           > max(snapshot_ts, history_ts))
    drift = (holders_ok and snapshot_pct is not None
             and history_pct is not None
             and abs(snapshot_pct - history_pct) > DRIFT_TOLERANCE_PP
             and snapshot_ts != history_ts
             and not truncation_swap)

    if use_history:
        dust_pct = history_pct
        dust_count = history_count
    else:
        dust_pct = snapshot_pct if snapshot_pct is not None else history_pct
        dust_count = (snapshot_count if snapshot_count is not None
                      else history_count)
    prev_pct = sampled[-2].get("dust_pct_mc") if len(sampled) >= 2 else None
    first_pct = sampled[0].get("dust_pct_mc") if sampled else None

    raw_rows = [row for row in points
                if isinstance(row, dict) and _int(row.get("ts")) > 0]
    last_raw = raw_rows[-1] if raw_rows else {}
    raw_snapshot_ts = _int(token.get("analyzed_at"), 0)
    newest_ts = max(raw_snapshot_ts if holders else 0,
                    _int(last_raw.get("ts"), 0))
    # Waktu ANGKA yang ditampilkan (bukan selalu waktu snapshot).
    used_ts = history_ts if use_history else (snapshot_ts or history_ts)
    degraded = bool(newest_ts) and newest_ts > used_ts and (
        (bool(holders) and not holders_ok)
        or (bool(last_raw) and not point_usable(last_raw)))

    return {
        "mint": str(mint),
        "symbol": str(meta.get("symbol") or token.get("symbol") or "?").upper(),
        "source": str(meta.get("source") or ""),
        "added": str(meta.get("added") or ""),
        "note": str(meta.get("note") or ""),
        "holders": holders,
        "points": points,
        "sampled": sampled,
        "dust_count": (None if dust_count is None else _int(dust_count)),
        "dust_pct": dust_pct,
        "prev_pct": _float(prev_pct, None),
        "first_pct": _float(first_pct, None),
        "flag": dust_flag(dust_pct, prev_pct),
        # Δ terhadap bucket 5 menit sebelumnya. Kolom ini tidak lagi
        # dirender di tabel (permintaan user 2026-09-07); tetap dihitung
        # untuk konsumen data lain.
        "delta_prev": _delta_pp(prev_pct, dust_pct),
        "delta_4h": _delta_pp(prev_pct, dust_pct),
        "delta_total": _delta_pp(first_pct, dust_pct),
        "mc": _float(token.get("marketcap"), None),
        "price": _float(token.get("price"), None),
        "analyzed_at": token.get("analyzed_at"),
        "has_chart": len(sampled) >= 2,
        "degraded": degraded,
        "drift": bool(drift),
        "truncation_swap": bool(truncation_swap),
        "snapshot_truncated": bool(holders.get("truncated") is True),
        "used_truncated": bool(
            (last_sampled.get("truncated") is True) if use_history
            else (holders.get("truncated") is True)),
        "used_ts": used_ts or None,
        "newest_ts": newest_ts or None,
    }


def lp_card_rows(watchlist: dict | None, status_tokens: dict | None = None,
                 store: dict | None = None) -> list[dict]:
    """Baris card Chart LP, urut dari yang paling perlu diwaspadai."""
    lp, _holder = split_watchlist(watchlist)
    rows = [build_lp_row(mint, meta, status_tokens, store)
            for mint, meta in lp.items()]
    return sort_lp_rows(rows)


def sort_lp_rows(rows) -> list[dict]:
    """Urutkan: BAHAYA → HATI-HATI → AMAN, lalu dust % MC terbesar."""
    def _key(row):
        row = row or {}
        pct = _float(row.get("dust_pct"), None)
        return (
            -dust_level_rank((row.get("flag") or {}).get("level")),
            -(pct if pct is not None else -1.0),
            str(row.get("symbol") or ""),
        )
    return sorted(list(rows or []), key=_key)


def lp_summary(rows) -> dict:
    """Rekap jumlah token per level dust (untuk header card)."""
    summary = {"total": 0, "danger": 0, "caution": 0, "ok": 0, "unknown": 0,
               "rising": 0, "with_chart": 0}
    for row in rows or []:
        summary["total"] += 1
        level = str((row or {}).get("flag", {}).get("level") or "unknown")
        summary[level if level in summary else "unknown"] += 1
        if (row or {}).get("flag", {}).get("rising"):
            summary["rising"] += 1
        if (row or {}).get("has_chart"):
            summary["with_chart"] += 1
    return summary


def _wib(ts) -> str:
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(hours=7)
    return when.strftime("%d %b %H:%M")


def _threshold_lines(axis) -> None:
    """Garis ambang HATI-HATI (0,5%) + BAHAYA (1%) pada sumbu dust % MC."""
    axis.axhline(DUST_CAUTION_PCT, color=COLOR_CAUTION, linestyle="--",
                 linewidth=1.1, label=f"Hati-hati {DUST_CAUTION_PCT:g}%")
    axis.axhline(DUST_DANGER_PCT, color=COLOR_DANGER, linestyle="--",
                 linewidth=1.1, label=f"Bahaya {DUST_DANGER_PCT:g}%")


def lp_chart_figure(points, symbol: str = "?") -> Figure | None:
    """Grafik perubahan dust holder satu token (bucket 5 menit).

    Garis = dust % MC (sumbu kiri), batang = jumlah wallet dust (sumbu
    kanan), plus garis ambang HATI-HATI/BAHAYA. ``None`` bila titik 5 menit
    belum cukup (< 2). Pemanggil wajib ``plt.close(fig)``.

    Titik dari scan yang datanya tidak lengkap dibuang lebih dulu
    (:func:`holder_history.point_usable`) supaya grafik tidak menggambar
    tebing palsu ke 0%.
    """
    sampled = resample_5m(usable_points(points))
    if len(sampled) < 2:
        return None
    labels = [_wib(row.get("ts")) for row in sampled]
    pct = [_float(row.get("dust_pct_mc"), float("nan")) for row in sampled]
    count = [_int(row.get("dust_count")) for row in sampled]

    plt = _pyplot()
    fig, axis = plt.subplots(figsize=(11, 3.4))
    twin = axis.twinx()
    twin.bar(labels, count, color="#f59e0b", alpha=.35, width=.6,
             label="Wallet dust")
    twin.set_ylabel("Jumlah wallet dust", color="#b45309")
    twin.tick_params(axis="y", labelcolor="#b45309")

    axis.plot(labels, pct, color="#0f172a", marker="o", linewidth=2.2,
              label="Dust % MC", zorder=3)
    _threshold_lines(axis)
    axis.set_ylabel("Dust % marketcap")
    axis.set_title(f"Perubahan dust holder ${str(symbol).upper()} "
                   f"({LP_INTERVAL_SEC // 60} menit)")
    axis.tick_params(axis="x", rotation=30, labelsize=8)
    axis.grid(alpha=.2)
    axis.margins(x=.02)
    handles, legend = axis.get_legend_handles_labels()
    twin_handles, twin_legend = twin.get_legend_handles_labels()
    axis.legend(handles + twin_handles, legend + twin_legend, frameon=False,
                loc="upper left", fontsize=8, ncols=2)
    fig.tight_layout()
    return fig


def lp_overlay_figure(rows) -> Figure | None:
    """Overlay dust % MC seluruh token Chart LP dalam satu grafik."""
    series = []
    for row in rows or []:
        sampled = resample_5m(usable_points((row or {}).get("points") or []))
        points = [(point.get("ts"), _float(point.get("dust_pct_mc"), None))
                  for point in sampled]
        points = [(ts, value) for ts, value in points if value is not None]
        if len(points) >= 2:
            series.append((str((row or {}).get("symbol") or "?").upper(),
                           points))
    if not series:
        return None

    stamps = sorted({ts for _label, points in series for ts, _v in points})
    labels = [_wib(ts) for ts in stamps]
    plt = _pyplot()
    fig, axis = plt.subplots(figsize=(11, 3.8))
    for label, points in series:
        values = dict(points)
        axis.plot(labels, [values.get(ts, float("nan")) for ts in stamps],
                  marker="o", linewidth=1.8, label=f"${label}")
    _threshold_lines(axis)
    axis.set_ylabel("Dust % marketcap")
    axis.set_title("Watchlist Meteora — dust % MC semua token")
    axis.tick_params(axis="x", rotation=30, labelsize=8)
    axis.grid(alpha=.2)
    axis.legend(frameon=False, loc="upper left", fontsize=8, ncols=3)
    fig.tight_layout()
    return fig
