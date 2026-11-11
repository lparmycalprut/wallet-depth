# -*- coding: utf-8 -*-
"""Page **🔍 Cek CA Sweep** — cek manual satu CA (permintaan user 2026-10-20).

Entri multipage terpisah dari 🌊 Sweep. Logika ada di :mod:`sweep_check`, UI di
:mod:`sweep_ui`. ``app.py`` tidak mengimpor modul sweep.
"""
from __future__ import annotations

import streamlit as st

from dashboard_components import render_styles
from sweep_ui import render_check_page

st.set_page_config(page_title="Wallet Depth — Cek CA Sweep", page_icon="🔍",
                   layout="wide", initial_sidebar_state="expanded")

render_styles()
render_check_page()
