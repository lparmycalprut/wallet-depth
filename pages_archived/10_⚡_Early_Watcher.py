# -*- coding: utf-8 -*-
"""Page **⚡ Early Watcher** — read-only, data dari ``early_watch_state.json``.

Logika di :mod:`early_watch`, UI di :mod:`early_ui`. Tidak ada fetch dan tidak
ada kirim Telegram dari halaman ini.
"""
from __future__ import annotations

import streamlit as st

from dashboard_components import render_styles
from early_ui import render_early_page

st.set_page_config(page_title="Wallet Depth — Early Watcher", page_icon="⚡",
                   layout="wide", initial_sidebar_state="expanded")

render_styles()
render_early_page()
