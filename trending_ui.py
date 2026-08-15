"""Streamlit renderer for unscored GMGN token listings."""
from __future__ import annotations

import html

import streamlit as st

from gmgn_screener import (screen, screen_hrhr, screen_hrhr_h1,
                           screen_trending_h1)
from watchlist import add_to_watchlist


def _compact(value):
    value = float(value or 0)
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def run_screen(force=False, key="trending_rows", **_kwargs):
    if force or key not in st.session_state:
        try:
            st.session_state[key] = screen()
            st.session_state[key + "_error"] = ""
        except Exception as exc:
            st.session_state[key] = []
            st.session_state[key + "_error"] = str(exc)
    return st.session_state[key], st.session_state[key + "_error"]


def run_screen_h1(force=False, key="trending_h1_rows", **_kwargs):
    if force or key not in st.session_state:
        try:
            st.session_state[key] = screen_trending_h1()
            st.session_state[key + "_error"] = ""
        except Exception as exc:
            st.session_state[key] = []
            st.session_state[key + "_error"] = str(exc)
    return st.session_state[key], st.session_state[key + "_error"]


def run_screen_hrhr(force=False, key="degen_rows", **_kwargs):
    if force or key not in st.session_state:
        try:
            st.session_state[key] = screen_hrhr()
            st.session_state[key + "_error"] = ""
        except Exception as exc:
            st.session_state[key] = []
            st.session_state[key + "_error"] = str(exc)
    return st.session_state[key], st.session_state[key + "_error"]


def run_screen_hrhr_h1(force=False, key="degen_h1_rows", **_kwargs):
    if force or key not in st.session_state:
        try:
            st.session_state[key] = screen_hrhr_h1()
            st.session_state[key + "_error"] = ""
        except Exception as exc:
            st.session_state[key] = []
            st.session_state[key + "_error"] = str(exc)
    return st.session_state[key], st.session_state[key + "_error"]


def render_trending(rows, *, key_prefix="listing", source="trending"):
    """Render market context and watchlist action without a ranking column."""
    if not rows:
        st.info("Tidak ada token dari respons GMGN saat ini.")
        return
    st.caption(
        "Listing GMGN ditampilkan sebagai konteks pasar saja. Tidak ada skor "
        "atau verdict; sinyal hanya berasal dari rasio effort harian.")
    for index, row in enumerate(rows):
        columns = st.columns([1.5, 1.1, 1, 1, 1, 1.15])
        symbol = html.escape(str(row.get("symbol") or "?").upper())
        columns[0].markdown(
            f"**${symbol}**  \n`{str(row.get('ca') or '')[:8]}…`")
        columns[1].markdown(f"MC  \n**{_compact(row.get('mc'))}**")
        columns[2].markdown(f"Liq  \n**{_compact(row.get('liq'))}**")
        columns[3].markdown(
            f"Volume  \n**{_compact(row.get('volume'))}**")
        columns[4].markdown(
            f"24h  \n**{float(row.get('change_24h') or 0):+.1f}%**")
        if columns[5].button("⭐ Watchlist", key=f"{key_prefix}-{index}",
                             use_container_width=True):
            add_to_watchlist(row["ca"], row.get("symbol") or "?",
                             source=source)
            st.success(f"${symbol} ditambahkan")
