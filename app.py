# -*- coding: utf-8 -*-
"""Wallet Depth — 🏆 Scan Best Pool Meteora."""
from __future__ import annotations

import streamlit as st

import activity_log
from best_pool_ui import render_best_pool_scan
from dashboard_components import render_degen_stop_header, render_styles


st.set_page_config(page_title="Wallet Depth — Best Pool Meteora",
                   page_icon="🏆", layout="wide",
                   initial_sidebar_state="collapsed")

render_styles()
render_degen_stop_header()
render_best_pool_scan()

st.divider()
activity_log.render_activity_log()
