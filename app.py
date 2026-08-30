# -*- coding: utf-8 -*-
"""Wallet Depth — Silent Accumulation 12 jam + holder real vs dust."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html

import streamlit as st

from links import CVD_PAGE_PATH, external_links_html
from silent_accumulation import (DUST_LIMIT_USD, analyze_token)
from silent_status import (load_silent_status, publish_silent_status)
from trending_ui import (render_trending, run_screen, run_screen_h1,
                         run_screen_hrhr, run_screen_hrhr_h1,
                         scan_with_analysis)
from watchlist import (add_to_watchlist, get_last_push_error, load_watchlist,
                       remove_from_watchlist)

st.set_page_config(page_title="Wallet Depth — Silent Accumulation 12H",
                   page_icon="🔇", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
.main .block-container {max-width: 1280px; padding-top: 1.5rem;}
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
.silent-badge {display:inline-block;padding:.28rem .58rem;border-radius:8px;
 font-size:.78rem;font-weight:800}
.silent-yes {background:#14532d;color:#dcfce7}
.silent-buy {background:#1e3a8a;color:#dbeafe}
.silent-sell {background:#7f1d1d;color:#fee2e2}
.silent-none {background:#e2e8f0;color:#000000}
.watchlist-row {display:flex;align-items:center;padding:.75rem 0;
 border-bottom:1px solid #cbd5e1;}
.watchlist-token {display:flex;flex-direction:column;gap:.25rem;}
.watchlist-symbol {font-size:1.1rem;font-weight:800;color:#000000;}
.watchlist-mint {font-size:.75rem;color:#000000;font-family:monospace;}
.watchlist-links {display:flex;gap:.5rem;margin-top:.25rem;}
.watchlist-links a {font-size:.75rem;color:#1d4ed8;font-weight:600;
 text-decoration:none;}
.watchlist-links a:hover {color:#000000;text-decoration:underline;}
.watchlist-metric {text-align:center;}
.watchlist-metric-label {font-size:.65rem;color:#000000;text-transform:uppercase;
 letter-spacing:.04em;}
.watchlist-metric-value {font-size:.95rem;font-weight:700;color:#000000;}
.watchlist-metric-sub {font-size:.65rem;color:#000000;}
</style>
<div class="hero"><h1>🔇 Wallet Depth</h1>
<p>Fokus: silent accumulation 12 jam terakhir + perbandingan real holder
(&gt;$10 value) vs dust holder, serta berapa % marketcap yang dipegang dust.</p></div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _number(value, pattern=".1f"):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


def _signed(value, pattern="+.1f"):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


def _compact(value, signed=False):
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if signed and n > 0 else ""
    if abs(n) >= 1e6:
        return f"{sign}${n / 1e6:.2f}M"
    if abs(n) >= 1e3:
        return f"{sign}${n / 1e3:.1f}K"
    return f"{sign}${n:,.0f}"


def _wib(ts):
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(hours=7)
    return when.strftime("%d %b %H:%M") + " WIB"


def _silent_badge(token):
    """Badge status 12 jam dari snapshot status token."""
    token = token or {}
    silent = token.get("silent") or {}
    flow = token.get("flow") or {}
    if silent.get("silent"):
        return '<span class="silent-badge silent-yes">🔇 SILENT ACCUMULATION</span>'
    net = flow.get("net_usd")
    if net is not None and float(net) < 0:
        return '<span class="silent-badge silent-sell">➖ DISTRIBUSI 12J</span>'
    if net is not None and float(net) > 0:
        return '<span class="silent-badge silent-buy">➕ NET BELI 12J</span>'
    return '<span class="silent-badge silent-none">BELUM ADA DATA</span>'


def _dust_pct(token):
    holders = (token or {}).get("holders") or {}
    pct = holders.get("dust_pct_mc")
    if pct is None:
        return "—"
    return f"{float(pct):.2f}%"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
watchlist = load_watchlist()
force_status = bool(st.session_state.pop("status_force_refresh", False))
silent_status = load_silent_status(force_refresh=force_status)
status_tokens = silent_status.get("tokens") or {}

st.subheader("📋 Watchlist — Silent Accumulation 12J")
st.caption(
    "Setiap token dicek 12 jam terakhir: net flow, wallet akumulator, "
    "real holder (>$10 value) vs dust, dan **dust % dari marketcap**. "
    f"Ambang dust: ${DUST_LIMIT_USD:.0f}. "
    f"Terakhir scan: {_wib(silent_status.get('updated_at'))}. "
    "GitHub Actions memindai tiap ~15 menit; tombol di bawah untuk "
    "pemindaian lokal langsung."
)

if st.button("🔄 Scan watchlist sekarang (12 jam)", type="primary",
             use_container_width=True):
    analyses = {}
    total = len(watchlist)
    bar = st.progress(0.0, text=f"Scan 0/{total} token…")
    done = 0
    for mint, meta in watchlist.items():
        try:
            analyses[mint] = analyze_token(
                mint, (meta or {}).get("symbol") or "?",
                max_wallets=2000, max_trade_pages=6, fetch_market=True)
        except Exception:  # noqa: BLE001 - lanjut ke token berikutnya
            analyses[mint] = None
        done += 1
        bar.progress(done / total,
                     text=f"Scan {done}/{total} · "
                          f"{str((meta or {}).get('symbol') or '?')}")
    if analyses:
        publish_silent_status(analyses, watchlist, push=False)
    st.session_state["status_force_refresh"] = True
    st.rerun()

if not watchlist:
    st.info("Watchlist masih kosong. Tambahkan contract address di bawah.")
else:
    header_cols = st.columns(
        [1.5, 1.3, 0.9, 0.9, 0.8, 0.7, 0.9, 1.0, 0.5, 0.5])
    header_style = "font-size:0.78rem;color:#000000;font-weight:700;"
    center = "text-align:center;" + header_style
    header_titles = ["Token", "Status 12 Jam", "Net 12j", "Harga 12j",
                     "Real >$10", "Dust", "Dust %MC", "Scan", "", ""]
    header_css = [header_style, center, center, center, center, center,
                  center, center, center, center]
    for col, style, title in zip(header_cols, header_css, header_titles):
        col.markdown(f'<div style="{style}">{title}</div>',
                     unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:0.65rem;color:#64748b;margin:0.3rem 0;">'
        '🕸 GMGN · 🛰 Helius · ≥ batas pencarian holder tercapai'
        '</div>',
        unsafe_allow_html=True)

    st.markdown('<hr style="margin:0.5rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)

    ordered = sorted(watchlist.items(),
                     key=lambda item: str(
                         (status_tokens.get(item[0]) or {}).get("symbol")
                         or item[1].get("symbol") or item[0]).upper())
    for mint, meta in ordered:
        token = status_tokens.get(mint) or {}
        symbol = str(meta.get("symbol") or token.get("symbol") or "?").upper()
        holders = token.get("holders") or {}
        flow = token.get("flow") or {}
        net_txt = _compact(flow.get("net_usd"), signed=True)
        price_txt = (f"{_signed(flow.get('price_chg_pct'), '+.1f')}%"
                     if flow.get("price_chg_pct") is not None else "—")
        scanned = _wib(token.get("analyzed_at"))
        holder_source = str(holders.get("source") or "gmgn").lower()
        source_icon = "🛰" if holder_source == "helius" else "🕸"
        truncated = holders.get("truncated", False)
        real_count = holders.get("real_count")
        dust_count = holders.get("dust_count")
        real_txt = f"≥{int(real_count)}" if truncated and real_count is not None else _number(real_count, ".0f")
        dust_txt = f"≥{int(dust_count)}" if truncated and dust_count is not None else _number(dust_count, ".0f")

        cols = st.columns(
            [1.5, 1.3, 0.9, 0.9, 0.8, 0.7, 0.9, 1.0, 0.5, 0.5])
        cols[0].markdown(
            f'<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'<span class="watchlist-mint">{html.escape(mint[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(mint)}</div>'
            f'</div>', unsafe_allow_html=True)
        cols[1].markdown(_silent_badge(token), unsafe_allow_html=True)
        cols[2].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{net_txt}</div>'
            f'<div class="watchlist-metric-sub">USD</div></div>',
            unsafe_allow_html=True)
        cols[3].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{price_txt}</div>'
            f'<div class="watchlist-metric-sub">12 jam</div></div>',
            unsafe_allow_html=True)
        cols[4].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">'
            f'{source_icon} {real_txt}</div>'
            f'<div class="watchlist-metric-sub">wallet</div></div>',
            unsafe_allow_html=True)
        cols[5].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">'
            f'{dust_txt}</div>'
            f'<div class="watchlist-metric-sub">wallet</div></div>',
            unsafe_allow_html=True)
        cols[6].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{_dust_pct(token)}</div>'
            f'<div class="watchlist-metric-sub">dari MC</div></div>',
            unsafe_allow_html=True)
        cols[7].markdown(
            f'<div style="font-size:0.75rem;color:#000000;text-align:center;">'
            f'{html.escape(scanned)}</div>', unsafe_allow_html=True)
        if cols[8].button("📈", key=f"chart-{mint}", help="Buka flow chart",
                          use_container_width=True):
            st.session_state["effort_mint"] = mint
            st.switch_page(CVD_PAGE_PATH, query_params={"mint": mint})
        if cols[9].button("✕", key=f"remove-{mint}", help="Hapus watchlist",
                          use_container_width=True):
            remove_from_watchlist(mint)
            st.rerun()
        st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)

with st.expander("➕ Tambah token", expanded=not bool(watchlist)):
    with st.form("add-token", clear_on_submit=True):
        mint_input = st.text_input(
            "Contract address",
            help="Symbol di-fetch otomatis dari DexScreener")
        submitted = st.form_submit_button("Tambah ke watchlist")
        if submitted and mint_input.strip():
            added = add_to_watchlist(mint_input.strip(), "?", source="manual")
            if added:
                st.success("Token ditambahkan.")
            else:
                error = get_last_push_error()
                st.warning(error.get("message")
                           or "Tersimpan lokal; sinkronisasi GitHub belum berhasil.")
            st.rerun()

st.divider()
st.subheader("🔍 Temukan Token — Holder Depth")
st.caption(
    "Scan Trending/Degen akan **langsung** menganalisis tiap token: "
    "perbandingan real holder (>$10 value) vs dust, dust % dari marketcap, "
    "dan silent accumulation 12 jam terakhir.")

st.markdown("""
<style>
div[data-testid="stButtonGroup"] button {
    font-size: 0.9rem !important;
    padding: 0.5rem 1.1rem !important;
    font-weight: 700 !important;
}
</style>
""", unsafe_allow_html=True)

TREND_TAB = "📈 Trending"
DEGEN_TAB = "🔥 Degen"
DISCOVER_TABS = [TREND_TAB, DEGEN_TAB]

active_tab = st.session_state.get("discover_tab_active", TREND_TAB)
selected_tab = st.segmented_control(
    "Mode listing", DISCOVER_TABS, default=active_tab,
    key="discover_tab", label_visibility="collapsed")
if selected_tab not in DISCOVER_TABS:
    selected_tab = active_tab
st.session_state["discover_tab_active"] = selected_tab

if selected_tab == DEGEN_TAB:
    if st.button("🔥 Scan Degen + Holder Depth", use_container_width=True):
        rows_24, error_24 = run_screen_hrhr(force=True)
        rows_1, error_1 = run_screen_hrhr_h1(force=True)
        combined = rows_24 + [row for row in rows_1
                              if row.get("ca") not in
                              {item.get("ca") for item in rows_24}]
        with st.container():
            combined = scan_with_analysis(combined, key_prefix="degen")
        st.session_state["degen_combined"] = combined
        st.session_state["degen_error"] = error_24 or error_1
    if st.session_state.get("degen_error"):
        st.error(st.session_state["degen_error"])
    render_trending(st.session_state.get("degen_combined", []),
                    key_prefix="degen", source="degen")
else:
    if st.button("🔎 Scan Trending + Holder Depth", use_container_width=True):
        rows_24, error_24 = run_screen(force=True)
        rows_1, error_1 = run_screen_h1(force=True)
        combined = rows_24 + [row for row in rows_1
                              if row.get("ca") not in
                              {item.get("ca") for item in rows_24}]
        with st.container():
            combined = scan_with_analysis(combined, key_prefix="trend")
        st.session_state["trend_combined"] = combined
        st.session_state["trend_error"] = error_24 or error_1
    if st.session_state.get("trend_error"):
        st.error(st.session_state["trend_error"])
    render_trending(st.session_state.get("trend_combined", []),
                    key_prefix="trend", source="trending")
