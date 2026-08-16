"""Streamlit renderer for unscored GMGN token listings."""
from __future__ import annotations

import html as _html

import streamlit as st

from gmgn_screener import (screen, screen_hrhr, screen_hrhr_h1,
                           screen_trending_h1)
from links import (CVD_PAGE_PATH, cvd_shortcut_query, external_links_html)
from watchlist import add_to_watchlist

# Inject consistent styling
st.markdown("""
<style>
.trending-row {
    padding: 0.6rem 0;
    border-bottom: 1px solid #cbd5e1;
}
.trending-token {
    display: block;
}
.trending-symbol {
    display: block;
    margin-bottom: 0.4rem;
    font-size: 1rem;
    font-weight: 800;
    line-height: 1.25;
    color: #000000;
}
.trending-mint {
    display: block;
    font-size: 0.7rem;
    line-height: 1.2;
    color: #000000;
    font-family: monospace;
}
.trending-links {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.2rem;
}
.trending-links a {
    font-size: 0.7rem;
    color: #1d4ed8;
    font-weight: 600;
    text-decoration: none;
}
.trending-links a:hover {
    color: #000000;
    text-decoration: underline;
}
.trending-metric {
    text-align: center;
    padding-top: 0.3rem;
}
.trending-metric-label {
    font-size: 0.6rem;
    color: #000000;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.trending-metric-value {
    font-size: 0.85rem;
    font-weight: 700;
    color: #000000;
}
</style>
""", unsafe_allow_html=True)


def _navigate_to_cvd(ca: str):
    """Preselect *ca* on the CVD page via session + query params."""
    st.session_state["effort_mint"] = str(ca or "")
    st.switch_page(f"{CVD_PAGE_PATH}{cvd_shortcut_query(ca)}")


def _compact(value):
    value = float(value or 0)
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def _color_change(value):
    """Return color based on positive/negative change."""
    try:
        v = float(value)
        if v > 0:
            return f'<span style="color:#15803d;font-weight:700;">{v:+.1f}%</span>'
        elif v < 0:
            return f'<span style="color:#b91c1c;font-weight:700;">{v:+.1f}%</span>'
        return f'{v:+.1f}%'
    except:
        return '—'


def _token_identity_html(symbol, ca):
    """Render token name and CA prefix on clearly separated lines."""
    safe_symbol = _html.escape(str(symbol or "?").upper())
    safe_ca = _html.escape(str(ca or "")[:8])
    return (
        '<div class="trending-token">'
        f'<div class="trending-symbol">${safe_symbol}</div>'
        f'<div class="trending-mint">{safe_ca}…</div>'
        f'<div class="trending-links">{external_links_html(str(ca or ""))}</div>'
        '</div>'
    )


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
    
    # Header row
    header_cols = st.columns([1.6, 1.0, 1.0, 1.0, 0.9, 0.9, 1.1])
    header_titles = ["Token", "MC", "Liq", "Volume", "24h", "", ""]
    header_style = "font-size:0.75rem;color:#000000;font-weight:700;text-align:center;"
    
    for col, title in zip(header_cols, header_titles):
        col.markdown(f'<div style="{header_style}">{title}</div>', unsafe_allow_html=True)
    
    st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">', unsafe_allow_html=True)
    
    for index, row in enumerate(rows):
        ca = str(row.get("ca") or "")
        symbol = str(row.get("symbol") or "?").upper()
        mc = _compact(row.get('mc'))
        liq = _compact(row.get('liq'))
        vol = _compact(row.get('volume'))
        change = row.get('change_24h')
        change_html = _color_change(change)
        
        columns = st.columns([1.6, 1.0, 1.0, 1.0, 0.9, 0.9, 1.1])
        
        # Token name and CA use separate block lines with visible spacing.
        columns[0].markdown(_token_identity_html(symbol, ca),
                            unsafe_allow_html=True)
        
        # MC column
        columns[1].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{mc}</div>'
            f'</div>',
            unsafe_allow_html=True)
        
        # Liq column
        columns[2].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{liq}</div>'
            f'</div>',
            unsafe_allow_html=True)
        
        # Volume column
        columns[3].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{vol}</div>'
            f'</div>',
            unsafe_allow_html=True)
        
        # 24h change column
        columns[4].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{change_html}</div>'
            f'</div>',
            unsafe_allow_html=True)
        
        # CVD button
        if columns[5].button("📊", key=f"cvd-{key_prefix}-{index}",
                             help="Buka CVD", use_container_width=True):
            _navigate_to_cvd(ca)
        
        # Watchlist button
        if columns[6].button("⭐", key=f"{key_prefix}-{index}",
                             help="Tambah ke Watchlist", use_container_width=True):
            add_to_watchlist(row["ca"], row.get("symbol") or "?",
                             source=source)
            st.success(f"${symbol} ditambahkan")
        
        st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">', unsafe_allow_html=True)
