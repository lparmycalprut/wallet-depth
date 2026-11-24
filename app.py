# -*- coding: utf-8 -*-
"""Wallet Depth — 🏆 Scan ALL (24H)."""
from __future__ import annotations

import streamlit as st

from dashboard_components import render_styles
from pool_flow_ui import render_pool_flow_page


st.set_page_config(page_title="Wallet Depth — Scan Best Pool",
                   page_icon="🏆", layout="wide",
                   initial_sidebar_state="collapsed")

render_styles()
render_pool_flow_page()
