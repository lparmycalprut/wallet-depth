# -*- coding: utf-8 -*-
"""Page **🌊 Sweep** — entri multipage Streamlit.

Halaman ini terpisah dari **🏆 Scan Best Pool Meteora** di ``app.py``
(permintaan user 2026-10-12: *"jangan taruh di main app, tapi buat page baru"*).
Isi dan logikanya ada di :mod:`sweep_ui`.
"""
from __future__ import annotations

import streamlit as st

from dashboard_components import render_styles
from sweep_ui import render_sweep_page

st.set_page_config(page_title="Wallet Depth — Sweep Screener", page_icon="🌊",
                   layout="wide", initial_sidebar_state="expanded")

render_styles()
render_sweep_page()
