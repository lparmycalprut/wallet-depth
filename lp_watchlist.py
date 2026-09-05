# -*- coding: utf-8 -*-
"""Watchlist terpisah **Chart LP** — token dari Scan Meteora Pool.

Token yang ditambahkan dari Scan Meteora (``source="meteora"``) atau
ditambahkan manual ke card LP dikumpulkan di card paling atas dashboard.
Card ini menampilkan **grafik perubahan dust holder** (dust % MC per bucket
4 jam + jumlah wallet dust) beserta garis ambang:

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

from holder_history import (DUST_CAUTION_PCT, DUST_DANGER_PCT, dust_flag,
                            dust_level_rank, history_for_mint, merge_points,
                            resample_4h)

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
    return merge_points(history_for_mint(store, mint),
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
    """Satu baris data card Chart LP (siap dirender ``app.py``)."""
    meta = meta or {}
    token = (status_tokens or {}).get(mint) or {}
    holders = token.get("holders") if isinstance(token.get("holders"), dict) \
        else {}
    points = points_for_mint(mint, status_tokens, store)
    sampled = resample_4h(points)

    dust_pct = _float(holders.get("dust_pct_mc"), None)
    if dust_pct is None and sampled:
        dust_pct = _float(sampled[-1].get("dust_pct_mc"), None)
    dust_count = holders.get("dust_count")
    if dust_count is None and sampled:
        dust_count = sampled[-1].get("dust_count")
    prev_pct = sampled[-2].get("dust_pct_mc") if len(sampled) >= 2 else None
    first_pct = sampled[0].get("dust_pct_mc") if sampled else None

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
        "delta_4h": _delta_pp(prev_pct, dust_pct),
        "delta_total": _delta_pp(first_pct, dust_pct),
        "mc": _float(token.get("marketcap"), None),
        "price": _float(token.get("price"), None),
        "analyzed_at": token.get("analyzed_at"),
        "has_chart": len(sampled) >= 2,
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
    """Grafik perubahan dust holder satu token (bucket 4 jam).

    Garis = dust % MC (sumbu kiri), batang = jumlah wallet dust (sumbu
    kanan), plus garis ambang HATI-HATI/BAHAYA. ``None`` bila titik 4 jam
    belum cukup (< 2). Pemanggil wajib ``plt.close(fig)``.
    """
    sampled = resample_4h(points)
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
    axis.set_title(f"Perubahan dust holder ${str(symbol).upper()} (4 jam)")
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
        sampled = resample_4h((row or {}).get("points") or [])
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
    axis.set_title("Chart LP — dust % MC semua token watchlist Meteora")
    axis.tick_params(axis="x", rotation=30, labelsize=8)
    axis.grid(alpha=.2)
    axis.legend(frameon=False, loc="upper left", fontsize=8, ncols=3)
    fig.tight_layout()
    return fig
