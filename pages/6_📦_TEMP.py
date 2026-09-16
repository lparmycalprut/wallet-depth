# -*- coding: utf-8 -*-
"""Halaman **📦 TEMP** — 🌊 Watchlist Meteora + 🛰 Scan Holder Solana.

Dua card itu pindah ke halaman ini 2026-09-16 per permintaan user (*"🌊
Watchlist Meteora pindah ke page baru TEMP"* + *"🛰 Scan Holder Solana pindah ke
page baru TEMP"*), jadi halaman utama tinggal **🏆 Scan Best Pool Meteora** +
**🧾 Log Aktivitas**. Nomor 6 dipakai lagi (halaman 🦅 Robinhood dihapus
2026-09-15) dan slug-nya otomatis dikenal :mod:`page_router` —
``?page=temp`` / ``?page=6`` / ``?page=6_📦_temp`` semuanya mendarat di sini.

Seluruh logika render ada di :mod:`temp_ui` (bukan ``app.py`` — halaman
Streamlit tidak boleh mengimpor halaman lain).
"""
from __future__ import annotations

import streamlit as st

from dashboard_components import render_styles
from temp_ui import render_temp_page

st.set_page_config(page_title="TEMP — Watchlist Meteora + Scan Holder",
                   page_icon="📦", layout="wide",
                   initial_sidebar_state="collapsed")

render_styles()

st.title("📦 TEMP")
st.caption(
    "Card yang dipindah dari halaman utama: **🌊 Watchlist Meteora** (snapshot "
    "cron ±5 menit + grafik dust) dan **🛰 Scan Holder Solana** (scan Helius "
    "FULL satu mint). Auto-refresh ±60 detik berlaku di halaman ini juga — "
    "halaman utama punya card sendiri (🏆 Best Pool Meteora).")

render_temp_page()
