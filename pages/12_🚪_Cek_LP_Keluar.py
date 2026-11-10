# -*- coding: utf-8 -*-
"""Page **🚪 Cek LP Keluar** — cek manual satu CA untuk sinyal likuiditas ditarik.

Entri multipage terpisah dari 🏆 Best Pool, 🌊 Sweep, 🔍 Cek CA Sweep, dan 🧭 Cek Entri LP.
Logika ada di ``tools/lp_exit_check``, UI di :mod:`lp_exit_ui`.
"""
from __future__ import annotations

import streamlit as st

from dashboard_components import render_styles
from lp_exit_ui import render_lp_exit_page

st.set_page_config(page_title="Wallet Depth — Cek LP Keluar", page_icon="🚪",
                   layout="wide", initial_sidebar_state="expanded")

render_styles()
render_lp_exit_page()
