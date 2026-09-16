# -*- coding: utf-8 -*-
"""Wallet Depth — 🏆 Scan Best Pool Meteora (halaman utama).

🌊 Watchlist Meteora + 🛰 Scan Holder Solana pindah ke halaman
**📦 TEMP** (2026-09-16, ``pages/6_📦_TEMP.py`` + ``temp_ui.py``);
``page_router`` tetap memantulkan deep-link ``?mint=`` ke halaman
🧾 Holder.
"""
from __future__ import annotations

import streamlit as st

# Hanya dua hal yang masih dipakai halaman utama sejak 2026-09-16: card Best
# Pool + router deep-link. Import card watchlist/holder (matplotlib,
# helius_holders, lp_watchlist, holder_status, alert_settings, links,
# dashboard data …) ikut pindah ke temp_ui.py bersama card-nya — membiarkan
# import tak terpakai di sini berarti tiap reload halaman utama memuat modul
# yang tidak pernah dirender.
from best_pool_ui import render_best_pool_scan
import page_router
from dashboard_components import render_styles
import activity_log


st.set_page_config(page_title="Wallet Depth — Holder Analytic",
                   page_icon="🧮", layout="wide",
                   initial_sidebar_state="collapsed")

# Deep link ``?mint=…`` / ``?page=…`` harus diselesaikan SEBELUM ada elemen
# lain: kalau tidak cocok dengan slug halaman (mis. tautan lama berbentuk
# ``pages/5_🧮_Holder.py?mint=…``), Streamlit menjalankan halaman utama ini dan
# router memantulkannya ke halaman Holder. switch_page menghentikan run ini,
# jadi tidak ada work/scan yang terbuang.
page_router.apply()

render_styles()

# Baris navigasi header DIHAPUS 2026-09-14 per permintaan user ("hilangkan
# link ke sini pada header") — navigasi antar halaman tetap tersedia lewat
# sidebar Streamlit.


# ---------------------------------------------------------------------------
# Layout utama (halaman 1) — sejak 2026-09-16 hanya dua card:
# **🏆 Scan Best Pool Meteora** + **🧾 Log Aktivitas**. 🌊 Watchlist
# Meteora dan 🛰 Scan Holder Solana pindah ke halaman baru **📦 TEMP**
# (``pages/6_📦_TEMP.py`` + ``temp_ui.py``) per permintaan user:
# "pindah ke page baru TEMP". Store (watchlist / holder_status /
# holder_history) tidak lagi dibaca di sini — tidak ada card yang
# memakainya, dan load_dashboard_data() hanya membaca (tanpa efek
# samping), jadi tidak perlu "dipanggil dulu" untuk halaman lain.
# ---------------------------------------------------------------------------
render_best_pool_scan()

# ---------------------------------------------------------------------------
# 🧾 Log Aktivitas (2026-09-10, paling bawah)
# ---------------------------------------------------------------------------
st.divider()
activity_log.render_activity_log()
