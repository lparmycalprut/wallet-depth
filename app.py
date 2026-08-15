# -*- coding: utf-8 -*-
"""Wallet Depth — daily effort anomaly dashboard."""
from __future__ import annotations

import html

import streamlit as st

from effort_detector import (classify_effort, load_daily_effort,
                             rows_for_mint)
from trending_ui import (render_trending, run_screen, run_screen_h1,
                         run_screen_hrhr, run_screen_hrhr_h1)
from watchlist import (add_to_watchlist, get_last_push_error, load_watchlist,
                       remove_from_watchlist)

st.set_page_config(page_title="Wallet Depth — Efisiensi Anomali",
                   page_icon="⚡", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
.main .block-container {max-width: 1240px; padding-top: 1.5rem;}
.hero {padding:1.4rem 1.6rem;border:1px solid #334155;border-radius:18px;
 background:linear-gradient(135deg,#0f172a,#172554);color:#f8fafc;
 margin-bottom:1.2rem}
.hero h1 {font-size:2rem;margin:0 0 .4rem}.hero p{color:#cbd5e1;margin:0}
.signal {display:inline-block;padding:.28rem .58rem;border-radius:8px;
 font-size:.8rem;font-weight:800}.bull{background:#14532d;color:#dcfce7}
.bear{background:#7f1d1d;color:#fee2e2}.neutral{background:#334155;color:#e2e8f0}
.metric-label{font-size:.72rem;color:#64748b;text-transform:uppercase;
 letter-spacing:.04em}.metric-value{font-size:1rem;font-weight:750}
div[data-testid="stHorizontalBlock"]{align-items:center}
</style>
<div class="hero"><h1>⚡ Wallet Depth</h1>
<p>Deteksi tunggal berbasis efisiensi anomali: berapa SOL ΔCVD yang dibutuhkan
untuk menggerakkan harga 1% dibandingkan hari sebelumnya.</p></div>
""", unsafe_allow_html=True)


def _signal_badge(result):
    signal = result.get("signal") or "insufficient_data"
    bias = result.get("bias") or "neutral"
    css = "bull" if bias == "bullish" else "bear" if bias == "bearish" \
        else "neutral"
    label = signal.replace("_", " ")
    return f'<span class="signal {css}">{html.escape(label)}</span>'


def _number(value, pattern=".3f"):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


watchlist = load_watchlist()
effort_rows = load_daily_effort()
st.subheader("Watchlist")
st.caption("Candle harian memakai batas 00:00–23:59 WIB. Sinyal memerlukan "
           "dua hari berturut-turut; multiplier 2× / 0,5× bersifat tetap.")

if not watchlist:
    st.info("Watchlist masih kosong. Tambahkan contract address di bawah.")
else:
    headers = st.columns([1.45, 1.35, 1.75, 1, 1, 1, .65, .55])
    for column, title in zip(headers, ["Token", "Tanggal", "Sinyal",
                                       "Ratio", "Baseline", "Multiplier",
                                       "Chart", "Hapus"]):
        column.markdown(f"**{title}**")
    for mint, meta in watchlist.items():
        history = rows_for_mint(effort_rows, mint)
        result = classify_effort(history, mint)
        columns = st.columns([1.45, 1.35, 1.75, 1, 1, 1, .65, .55])
        symbol = str((meta or {}).get("symbol") or "?").upper()
        columns[0].markdown(
            f"**${html.escape(symbol)}**  \n`{html.escape(mint[:8])}…`")
        date = result.get("date") or "Butuh ≥2 hari"
        columns[1].markdown(str(date))
        columns[2].markdown(_signal_badge(result), unsafe_allow_html=True)
        columns[3].markdown(
            f"**{_number(result.get('ratio_N'))}**  \nSOL/1%")
        columns[4].markdown(
            f"**{_number(result.get('ratio_N_minus_1'))}**  \nSOL/1%")
        columns[5].markdown(
            f"**×{_number(result.get('multiplier'), '.2f')}**")
        if columns[6].button("📈", key=f"chart-{mint}",
                             help="Buka chart 7 hari"):
            st.session_state["effort_mint"] = mint
            st.switch_page("pages/4_📊_CVD.py")
        if columns[7].button("✕", key=f"remove-{mint}"):
            remove_from_watchlist(mint)
            st.rerun()
        st.divider()

with st.expander("➕ Tambah token", expanded=not bool(watchlist)):
    with st.form("add-token", clear_on_submit=True):
        left, right = st.columns([3, 1])
        mint_input = left.text_input("Contract address")
        symbol_input = right.text_input("Ticker", value="?")
        submitted = st.form_submit_button("Tambah ke watchlist")
        if submitted and mint_input.strip():
            added = add_to_watchlist(mint_input.strip(),
                                     symbol_input.strip() or "?",
                                     source="manual")
            if added:
                st.success("Token ditambahkan.")
            else:
                error = get_last_push_error()
                st.warning(error.get("message") or
                           "Tersimpan lokal; sinkronisasi GitHub belum berhasil.")
            st.rerun()

st.divider()
st.subheader("Temukan token")
st.caption("Scanner hanya listing dan konteks pasar. Ia tidak menghasilkan "
           "verdict. Setelah token masuk watchlist, cron harian mengukurnya.")
trend_tab, degen_tab = st.tabs(["Trending", "Degen"])
with trend_tab:
    if st.button("🔎 Scan Trending", use_container_width=True):
        rows_24, error_24 = run_screen(force=True)
        rows_1, error_1 = run_screen_h1(force=True)
        st.session_state["trend_combined"] = rows_24 + [
            row for row in rows_1
            if row.get("ca") not in {item.get("ca") for item in rows_24}]
        st.session_state["trend_error"] = error_24 or error_1
    if st.session_state.get("trend_error"):
        st.error(st.session_state["trend_error"])
    render_trending(st.session_state.get("trend_combined", []),
                    key_prefix="trend", source="trending")
with degen_tab:
    if st.button("🔥 Scan Degen", use_container_width=True):
        rows_24, error_24 = run_screen_hrhr(force=True)
        rows_1, error_1 = run_screen_hrhr_h1(force=True)
        st.session_state["degen_combined"] = rows_24 + [
            row for row in rows_1
            if row.get("ca") not in {item.get("ca") for item in rows_24}]
        st.session_state["degen_error"] = error_24 or error_1
    if st.session_state.get("degen_error"):
        st.error(st.session_state["degen_error"])
    render_trending(st.session_state.get("degen_combined", []),
                    key_prefix="degen", source="degen")
