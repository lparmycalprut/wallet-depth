# -*- coding: utf-8 -*-
"""Thread-safe in-memory activity log rendered below the Best Pool scanner.

Levels are ``info``, ``warn``, ``error``, and ``action``; action entries use
bold red text because they require manual intervention. Identical entries are
deduplicated within a short window and increment a counter instead of flooding
the panel. State lasts for the current application process only.
"""
from __future__ import annotations

import html as _html
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"
LEVEL_ACTION = "action"
_LEVELS = (LEVEL_INFO, LEVEL_WARN, LEVEL_ERROR, LEVEL_ACTION)

MAX_ENTRIES = 400          # ring buffer; yang lama terdorong keluar
DEFAULT_DEDUP_SEC = 60.0   # entri identik < 60 dtk = bump count saja
RENDER_LIMIT = 120         # baris maksimum yang dirender di panel

_WIB = timezone(timedelta(hours=7))
_LOCK = threading.Lock()
_ENTRIES: deque = deque(maxlen=MAX_ENTRIES)

# Gaya per level — hanya ``action`` yang merah **bold** (permintaan user:
# merah bold = perlu perubahan manual). ``error`` merah biasa supaya beda.
_LEVEL_STYLE = {
    LEVEL_INFO: "color:#475569;",
    LEVEL_WARN: "color:#b45309;",
    LEVEL_ERROR: "color:#b91c1c;",
    LEVEL_ACTION: "color:#dc2626;font-weight:700;",
}
_LEVEL_ICON = {LEVEL_INFO: "·", LEVEL_WARN: "⚠️", LEVEL_ERROR: "✖",
               LEVEL_ACTION: "❗"}


def log(level: str, source: str, message: str, *,
        dedup_sec: float = DEFAULT_DEDUP_SEC, echo: bool | None = None) -> None:
    """Catat satu kejadian. ``source`` = modul/card asal (mis. ``helius``).

    ``echo`` None = level selain info ikut dicetak ke stderr (kelihatan di
    log terminal/cron); info hanya masuk buffer.
    """
    level = level if level in _LEVELS else LEVEL_INFO
    source = str(source or "app")
    message = str(message or "").strip()
    if not message:
        return
    now = time.time()
    with _LOCK:
        if dedup_sec > 0:
            for entry in reversed(_ENTRIES):
                if now - entry["ts"] > dedup_sec:
                    break
                if (entry["level"] == level and entry["source"] == source
                        and entry["message"] == message):
                    entry["count"] += 1
                    entry["ts"] = now
                    return
        _ENTRIES.append({"ts": now, "level": level, "source": source,
                         "message": message, "count": 1})
    if echo is None:
        echo = level != LEVEL_INFO
    if echo:
        print(f"LOG[{level}] {source}: {message}", file=sys.stderr)


def info(source: str, message: str, **kwargs) -> None:
    log(LEVEL_INFO, source, message, **kwargs)


def warn(source: str, message: str, **kwargs) -> None:
    log(LEVEL_WARN, source, message, **kwargs)


def error(source: str, message: str, **kwargs) -> None:
    log(LEVEL_ERROR, source, message, **kwargs)


def action(source: str, message: str, **kwargs) -> None:
    """Kejadian yang **perlu perubahan manual user** → merah bold di panel."""
    log(LEVEL_ACTION, source, message, **kwargs)


def entries(limit: int | None = None) -> list[dict]:
    """Salinan entri, terbaru dulu."""
    with _LOCK:
        items = [dict(entry) for entry in reversed(_ENTRIES)]
    return items[: int(limit)] if limit else items


def counts() -> dict:
    """Jumlah entri per level (untuk pill kepala panel)."""
    out = {level: 0 for level in _LEVELS}
    with _LOCK:
        for entry in _ENTRIES:
            out[entry["level"]] = out.get(entry["level"], 0) + 1
    return out


def clear() -> None:
    with _LOCK:
        _ENTRIES.clear()


def _fmt_wib(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts), _WIB).strftime("%H:%M:%S")
    except (OSError, OverflowError, TypeError, ValueError):
        return "--:--:--"


def entry_html(entry: dict) -> str:
    """Satu baris log sebagai HTML (dipisah supaya bisa dites murni)."""
    level = str(entry.get("level") or LEVEL_INFO)
    style = _LEVEL_STYLE.get(level, _LEVEL_STYLE[LEVEL_INFO])
    icon = _LEVEL_ICON.get(level, "·")
    count = int(entry.get("count") or 1)
    suffix = f" ×{count}" if count > 1 else ""
    return (
        '<div style="font-size:0.78rem;line-height:1.5;font-family:monospace;'
        f'{style}">'
        f'<span style="color:#94a3b8;">{_fmt_wib(entry.get("ts", 0))} WIB</span> '
        f'{icon} <span style="opacity:.75;">[{_html.escape(str(entry.get("source") or "app"))}]</span> '
        f'{_html.escape(str(entry.get("message") or ""))}{suffix}</div>'
    )


def render_activity_log() -> None:
    """Panel **🧾 Log Aktivitas** — dipanggil di paling bawah ``app.py``.

    Kepala panel menampilkan pill jumlah ❗ action / ✖ error / ⚠️ warning.
    Sistem Holder dan status kuota Helius telah dihapus dari aplikasi.
    """
    import streamlit as st

    from dashboard_components import card_head_html

    stats = counts()
    pills = []
    if stats.get(LEVEL_ACTION):
        pills.append('<span class="lp-count" style="color:#ffffff;'
                     'background:#dc2626;font-weight:700;">'
                     f'❗ {stats[LEVEL_ACTION]} perlu tindakan</span>')
    if stats.get(LEVEL_ERROR):
        pills.append('<span class="lp-count" style="color:#7f1d1d;'
                     f'background:#fecaca;">✖ {stats[LEVEL_ERROR]} error</span>')
    if stats.get(LEVEL_WARN):
        pills.append('<span class="lp-count" style="color:#78350f;'
                     f'background:#fde68a;">⚠️ {stats[LEVEL_WARN]} '
                     'warning</span>')
    total = sum(stats.values())
    pills.append(f'<span class="lp-count">{total} entri</span>')

    with st.container(border=True):
        st.markdown(card_head_html(
            "🧾 Log Aktivitas", pills,
            tooltip=("Kejadian penting sesi aplikasi ini: scan mulai/selesai "
                     "dan kegagalan listing/enrichment. Merah bold menandakan "
                     "masalah yang perlu tindakan manual. Log hidup di memori "
                     "proses dan kosong kembali setelah restart.")),
            unsafe_allow_html=True)

        rows = entries(RENDER_LIMIT)
        if not rows:
            st.caption("Belum ada kejadian tercatat di sesi ini.")
        else:
            st.markdown(
                '<div style="max-height:320px;overflow-y:auto;">'
                + "".join(entry_html(entry) for entry in rows)
                + "</div>", unsafe_allow_html=True)
        if rows and st.button("🧹 Bersihkan log", key="activity-log-clear"):
            clear()
            st.rerun()
