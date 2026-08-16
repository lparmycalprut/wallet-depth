# -*- coding: utf-8 -*-
"""Wallet Depth — daily effort anomaly dashboard (v3)."""
from __future__ import annotations

import html

import streamlit as st

from effort_detector import (classify_effort, load_daily_effort,
                             rows_for_mint)
from links import external_links_html
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
/* Base: semua teks hitam agar terbaca di background terang */
html, body, p, span, div, label, li, td, th,
h1, h2, h3, h4, h5, h6 {color:#000000;}
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"],
[data-testid="stWidgetLabel"] p {color:#000000 !important;}
.hero {padding:1.4rem 1.6rem;border:1px solid #334155;border-radius:18px;
 background:linear-gradient(135deg,#0f172a,#172554);
 margin-bottom:1.2rem}
.hero h1, .hero p, .hero {color:#ffffff;}
.hero h1 {font-size:2rem;margin:0 0 .4rem}.hero p{color:#ffffff;margin:0}
.signal {display:inline-block;padding:.28rem .58rem;border-radius:8px;
 font-size:.8rem;font-weight:800}.bull{background:#14532d;color:#dcfce7}
.bear{background:#7f1d1d;color:#fee2e2}.neutral{background:#334155;color:#e2e8f0}
.metric-label{font-size:.72rem;color:#000000;text-transform:uppercase;
 letter-spacing:.04em}.metric-value{font-size:1rem;font-weight:750}
div[data-testid="stHorizontalBlock"]{align-items:center}

/* Watchlist row styling */
.watchlist-row {
    display: flex;
    align-items: center;
    padding: 0.75rem 0;
    border-bottom: 1px solid #cbd5e1;
}
.watchlist-token {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
}
.watchlist-symbol {
    font-size: 1.1rem;
    font-weight: 800;
    color: #000000;
}
.watchlist-mint {
    font-size: 0.75rem;
    color: #000000;
    font-family: monospace;
}
.watchlist-links {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.25rem;
}
.watchlist-links a {
    font-size: 0.75rem;
    color: #1d4ed8;
    font-weight: 600;
    text-decoration: none;
}
.watchlist-links a:hover {
    color: #000000;
    text-decoration: underline;
}
.watchlist-metric {
    text-align: center;
}
.watchlist-metric-label {
    font-size: 0.65rem;
    color: #000000;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.watchlist-metric-value {
    font-size: 0.95rem;
    font-weight: 700;
    color: #000000;
}
.watchlist-metric-sub {
    font-size: 0.65rem;
    color: #000000;
}
.status-badge {
    display: inline-block;
    padding: 0.2rem 0.5rem;
    border-radius: 8px;
    font-size: 0.7rem;
    font-weight: 700;
    margin-top: 0.25rem;
}
.badge-warning {background:#7f1d1d;color:#fee2e2}
.badge-info {background:#334155;color:#e2e8f0}
.badge-direct {background:#14532d;color:#dcfce7}
.badge-neutral {background:#e2e8f0;color:#000000}
</style>
<div class="hero"><h1>⚡ Wallet Depth</h1>
<p>Deteksi tunggal berbasis efisiensi anomali: berapa SOL ΔCVD yang dibutuhkan
untuk menggerakkan harga 1% dibandingkan baseline sehat sebelumnya. Termasuk
2 sinyal pra-pump baru: ABSORBSI LANGSUNG & SELLING EXHAUSTION.</p></div>
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
st.subheader("📋 Watchlist")
st.caption("Candle harian: 00:00–23:59 UTC | Baseline = walk-back hari sehat "
           "(|CVD|≥1, |ΔHarga|≥3%, ratio≥0.05)")

if not watchlist:
    st.info("Watchlist masih kosong. Tambahkan contract address di bawah.")
else:
    # Header row with styled columns
    header_cols = st.columns([1.6, 1.2, 1.8, 1.1, 1.1, 1.0, .6, .6])
    header_styles = [
        "font-size:0.8rem;color:#000000;font-weight:700;",
        "font-size:0.8rem;color:#000000;font-weight:700;",
        "font-size:0.8rem;color:#000000;font-weight:700;",
        "text-align:center;font-size:0.8rem;color:#000000;font-weight:700;",
        "text-align:center;font-size:0.8rem;color:#000000;font-weight:700;",
        "text-align:center;font-size:0.8rem;color:#000000;font-weight:700;",
        "text-align:center;font-size:0.8rem;color:#000000;font-weight:700;",
        "text-align:center;font-size:0.8rem;color:#000000;font-weight:700;"
    ]
    header_titles = ["Token", "Tanggal", "Sinyal", "Ratio", "Baseline", "Multi", "Chart", ""]
    for col, style, title in zip(header_cols, header_styles, header_titles):
        col.markdown(f'<div style="{style}">{title}</div>', unsafe_allow_html=True)
    
    st.markdown('<hr style="margin:0.5rem 0;border-color:#cbd5e1;">', unsafe_allow_html=True)
    
    for mint, meta in watchlist.items():
        history = rows_for_mint(effort_rows, mint)
        result = classify_effort(history, mint)
        
        symbol = str((meta or {}).get("symbol") or "?").upper()
        date = result.get("date") or "—"
        ratio_N = _number(result.get('ratio_N'))
        ratio_prev = _number(result.get('ratio_N_minus_1'))
        multiplier = _number(result.get('multiplier'), '.2f')
        
        # Build status badges HTML
        baseline_status = result.get("baseline_status") or "missing"
        reason = result.get("baseline_reason") or ""
        
        badges_html = _signal_badge(result)
        
        if baseline_status == "unstable":
            badges_html += '<br><span class="status-badge badge-warning">⚠️ BASELINE TIDAK STABIL</span>'
        elif baseline_status == "insufficient_baseline":
            badges_html += '<br><span class="status-badge badge-info">⚠️ BUTUH BASELINE</span>'
        elif baseline_status == "noise":
            badges_html += '<br><span class="status-badge badge-neutral">⚪ NOISE &lt;5 SOL</span>'
        elif baseline_status == "incompatible_direction":
            badges_html += '<br><span class="status-badge badge-warning">⚠️ BASELINE BEDA ARAH</span>'
        elif baseline_status == "direct" and result.get("signal") in ("ABSORBSI_LANGSUNG", "SELLING_EXHAUSTION"):
            badges_html += '<br><span class="status-badge badge-direct">⚡ DIRECT</span>'
        
        # Multiplier with rejection indicator
        raw_multiplier = result.get('raw_multiplier')
        if baseline_status not in ("stable", "direct") and raw_multiplier is not None:
            multiplier_html = f'<span style="font-size:0.95rem;font-weight:700;">×{multiplier}</span><br><span style="font-size:0.65rem;color:#b91c1c;font-weight:600;">Raw: ×{_number(raw_multiplier, ".2f")}</span>'
        else:
            multiplier_html = f'<span style="font-size:0.95rem;font-weight:700;">×{multiplier}</span>'
        
        # Reason tooltip
        reason_html = f'<div style="font-size:0.62rem;color:#000000;line-height:1.3;">{str(reason).replace("; ", "<br>") if reason else ""}</div>'
        
        # Render row with clean layout
        cols = st.columns([1.6, 1.2, 1.8, 1.1, 1.1, 1.0, .6, .6])
        
        # Token column
        cols[0].markdown(
            f'<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'<span class="watchlist-mint">{html.escape(mint[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(mint)}</div>'
            f'</div>',
            unsafe_allow_html=True)
        
        # Date column
        cols[1].markdown(f'<div style="font-size:0.85rem;color:#000000;">{date}</div>', unsafe_allow_html=True)
        
        # Signal + badges column
        cols[2].markdown(badges_html, unsafe_allow_html=True)
        
        # Ratio N column (current)
        cols[3].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{ratio_N}</div>'
            f'<div class="watchlist-metric-sub">SOL/1%</div>'
            f'</div>',
            unsafe_allow_html=True)
        
        # Ratio N-1 column (baseline)
        cols[4].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{ratio_prev}</div>'
            f'<div class="watchlist-metric-sub">SOL/1%</div>'
            f'{reason_html}'
            f'</div>',
            unsafe_allow_html=True)
        
        # Multiplier column
        cols[5].markdown(
            f'<div class="watchlist-metric">{multiplier_html}</div>',
            unsafe_allow_html=True)
        
        # Chart button
        if cols[6].button("📈", key=f"chart-{mint}", help="Buka chart 7 hari", use_container_width=True):
            st.session_state["effort_mint"] = mint
            st.switch_page("pages/4_📊_CVD.py")
        
        # Remove button
        if cols[7].button("✕", key=f"remove-{mint}", help="Hapus dari watchlist", use_container_width=True):
            remove_from_watchlist(mint)
            st.rerun()
        
        st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">', unsafe_allow_html=True)

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
st.subheader("🔍 Temukan Token")
st.caption("Listing GMGN sebagai konteks pasar. Sinyal hanya dari rasio effort harian.")

# Add tab styling
st.markdown("""
<style>
[data-testid="stTabBar"] button {
    font-size: 0.9rem !important;
    padding: 0.5rem 1rem !important;
}
</style>
""", unsafe_allow_html=True)

trend_tab, degen_tab = st.tabs(["📈 Trending", "🔥 Degen"])
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
