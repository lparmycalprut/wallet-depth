# -*- coding: utf-8 -*-
"""Page 🦅 Robinhood — Watchlist Robinhood + Scan Best Pool Krystal.

Dipindah dari halaman utama (app.py) atas permintaan user:
- 🦅 Watchlist Robinhood (LP, scan ±5 menit)
- 🦅 Scan Best Pool Krystal (Robinhood Chain 4663, rule F/V 24H)

Format penataan dikembalikan: dua card full-width bertumpuk dengan divider
konsisten, masing-masing border container (seperti card di halaman utama
sebelum grid 2 kolom). Tidak ada grid kosong, tidak ada duplikasi data —
semua store, cron, dan alert tetap sama (hanya penempatan UI yang pindah).

Akan disempurnakan nanti kalau ada waktu (TODO: filter, sorting, dll).
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from krystal_pool_ui import render_krystal_pool_scan
from dashboard_components import _render_rh_card, load_dashboard_data, render_styles
from robinhood_watchlist import split_robinhood_watchlist
import activity_log

st.set_page_config(page_title="Robinhood", page_icon="🦅", layout="wide")

render_styles()

# Navigasi cepat — aman untuk AppTest (entrypoint = file ini): page_link
# bisa melempar StreamlitPageNotFoundError bila path tidak ditemukan relatif
# terhadap entrypoint. Bungkus try/except supaya tes tetap hijau; di runtime
# Streamlit normal, link tetap muncul.
def _safe_page_link(path: str, label: str, icon: str = ""):
    try:
        st.page_link(path, label=label, icon=icon)
    except Exception:
        try:
            if not path.startswith("pages/") and not path.startswith(".."):
                alt = f"../{path}" if path == "app.py" else path
                st.page_link(alt, label=label, icon=icon)
            else:
                st.caption(f"{icon} {label} ({path})")
        except Exception:
            st.caption(f"{icon} {label} ({path})")

col_nav1, col_nav2, col_nav3 = st.columns([0.26, 0.22, 0.52])
with col_nav1:
    _safe_page_link("app.py", label="Kembali ke halaman utama", icon="🏠")
with col_nav2:
    _safe_page_link("pages/8_temp.py", label="temp", icon="📦")
with col_nav3:
    _safe_page_link("pages/5_🧮_Holder.py", label="Holder Analytic", icon="🧮")

st.title("🦅 Robinhood")
st.caption(
    "Watchlist Robinhood Chain (EVM, chain id 4663) + Scan Best Pool Krystal "
    "— dipindah dari halaman utama ke page ini. Data, cron ±5 menit, dan "
    "notifikasi ⚡ EARLY DUMP tetap sama; hanya penataan UI yang dipindah."
)

# ---------------------------------------------------------------------------
# Shared stores — sama persis dengan yang dipakai app.py sebelumnya
# ---------------------------------------------------------------------------
data = load_dashboard_data()
rh_lp_watch, rh_regular_watch = split_robinhood_watchlist(data.rh_watchlist)
rh_status_tokens = data.rh_status.get("tokens") or {}
now_ts = int(datetime.now(timezone.utc).timestamp())

# ---------------------------------------------------------------------------
# 🦅 Watchlist Robinhood — full-width, format penataan dikembalikan
# ---------------------------------------------------------------------------
_render_rh_card(
    rh_lp_watch,
    rh_status_tokens,
    data.rh_history,
    now_ts,
    variant="lp",
    merge_status=data.rh_status,
)

# Catatan: Watchlist Robinhood biasa (regular) tetap di halaman temp (📦)
# untuk menghindari duplikasi key form ``rh-add-token`` yang dipakai
# ``dashboard_components._render_rh_card`` di kedua varian. Page ini hanya
# menampilkan lane LP (scan cepat ±5 menit) — yang sebelumnya di halaman
# utama — supaya format penataan tetap 1 card full-width tanpa tabrakan key.
# Token regular bisa dipindah ke LP via tombol ⚡ di temp, lalu muncul di sini.

# ---------------------------------------------------------------------------
# 🦅 Scan Best Pool Krystal — full-width, di bawah watchlist
# ---------------------------------------------------------------------------
st.divider()
render_krystal_pool_scan()

# ---------------------------------------------------------------------------
# 🧾 Log Aktivitas — biar troubleshooting Blockscout PRO key tetap di page ini
# ---------------------------------------------------------------------------
st.divider()
activity_log.render_activity_log()
