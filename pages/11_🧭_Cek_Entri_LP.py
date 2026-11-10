# -*- coding: utf-8 -*-
"""Page **🧭 Cek Entri LP** — cek manual satu CA untuk entri LP Meteora.

Entri multipage terpisah dari 🏆 Best Pool, 🌊 Sweep, dan 🔍 Cek CA Sweep.
Logika ada di ``tools/lp_entry_check``, UI di :mod:`lp_entry_ui`.
"""
from __future__ import annotations

import streamlit as st

from dashboard_components import render_styles
from lp_entry_ui import render_lp_entry_page

st.set_page_config(page_title="Wallet Depth — Cek Entri LP", page_icon="🧭",
                   layout="wide", initial_sidebar_state="expanded")

render_styles()
render_lp_entry_page()
