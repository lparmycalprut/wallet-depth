# -*- coding: utf-8 -*-
"""Page: GMGN trending screener scored by structural LP criteria."""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trending_ui import render_trending, run_screen

st.set_page_config(page_title="Screener", page_icon="🔎",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.72rem !important;}
</style>""", unsafe_allow_html=True)

st.title("🔎 Screener — GMGN trending, scored our way")
st.caption("Pulls GMGN's trending list (pre-filtered: age 2-30d, migrated, "
           "renounced+frozen, no wash trading, liq ≥$30K, MC ≥$100K, "
           "holders ≥1000, vol ≥$100K, insiders/bundlers ≤15%) and scores "
           "each token for structural LP fit: low concentration + healthy "
           "liquidity + low rug risk + sane volume/MC. Price and age are "
           "context only; smart-money/KOL are no longer used or displayed.")

scan = st.button("🔎 Scan trending now", type="primary",
                 use_container_width=True)

if not scan and "screener_rows" not in st.session_state:
    st.info("Click **Scan trending now** to pull and score the current "
            "GMGN trending list.")
    st.stop()

rows, err = run_screen(force=scan)
if err:
    st.error(f"Failed to fetch trending: {err}")
if not rows:
    st.warning("GMGN returned nothing (Cloudflare block or every token was "
               "filtered out). Try again in a minute.")
    st.stop()

render_trending(rows, key_prefix="scr")
