# -*- coding: utf-8 -*-
"""Wallet Depth — dashboard 3 sinyal bottom (CVD × volume USD harian)."""
from __future__ import annotations

import html

import streamlit as st

from effort_detector import (SIGNAL_META, classify_effort, load_daily_effort,
                             rows_for_mint)
from links import external_links_html
from trending_ui import (render_trending, run_screen, run_screen_h1,
                         run_screen_hrhr, run_screen_hrhr_h1)
from watchlist import (add_to_watchlist, get_last_push_error, load_watchlist,
                       remove_from_watchlist)

st.set_page_config(page_title="Wallet Depth — 3 Sinyal Bottom",
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
.rev{background:#4c1d95;color:#ede9fe}.aku{background:#1e3a8a;color:#dbeafe}
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
.badge-neutral {background:#e2e8f0;color:#000000}
/* Detail sinyal selalu putih agar terbaca di background badge. */
.signal-detail,
.signal-detail.bull,
.signal-detail.rev,
.signal-detail.aku,
.signal-detail.neutral {color:#ffffff !important}
</style>
<div class="hero"><h1>⚡ Wallet Depth</h1>
<p>Deteksi bottom 3 sinyal: 🟢 SELLER EXHAUSTION, 🟣 REVERSAL, 🔵 AKUMULASI —
membaca hubungan ΔCVD harian (SOL) dan volume antar-hari (USD) dengan batas
hari 00:00 UTC.</p></div>
""", unsafe_allow_html=True)


def _signal_tone(result):
    """Tone visual mengikuti sinyal: hijau exhaustion, ungu reversal, biru akumulasi."""
    signal = result.get("signal") or ""
    meta = SIGNAL_META.get(signal)
    if meta:
        return meta.get("tone") or "neutral"
    bias = result.get("bias") or "neutral"
    return "bull" if bias == "bullish" else "bear" if bias == "bearish" \
        else "neutral"


def _signal_badge(result):
    signal = result.get("signal") or "—"
    css = _signal_tone(result)
    label = (SIGNAL_META.get(signal) or {}).get("label") or signal
    return f'<span class="signal {css}">{html.escape(label)}</span>'


def _number(value, pattern=".3f"):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


def _signed(value, pattern="+.1f", suffix=""):
    """Format a signed number, or ``—`` when it is unavailable."""
    if value is None:
        return "—"
    try:
        return format(float(value), pattern) + suffix
    except (TypeError, ValueError):
        return "—"


def _signal_detail_html(result):
    """Narasi bottom untuk kolom detail: flush/volume, penanda whale & on-chain."""
    signal = result.get("signal") or "—"
    tone = _signal_tone(result)
    is_signal = signal in SIGNAL_META
    lines = []

    if is_signal:
        flush_date = result.get("flush_date")
        if flush_date:
            lines.append(
                f"Flush {flush_date} · CVD "
                f"{_signed(result.get('flush_cvd'), '+.2f')} SOL → "
                f"{_signed(result.get('cvd_delta'), '+.2f')} SOL")
        else:
            lines.append(
                f"Δ{_signed(result.get('price_chg_pct'))}% · CVD "
                f"{_signed(result.get('cvd_delta'), '+.2f')} SOL")
        volume_pct = result.get("volume_pct")
        if volume_pct is not None:
            lines.append(f"Volume {_number(volume_pct, '.0f')}% dari kemarin")

    reason = str(result.get("reason") or "").strip()
    if reason:
        lines.append(reason)

    # Penanda info (bukan syarat sinyal)
    extras = []
    if result.get("whale_driven"):
        extras.append(f"⚠️ whale top-1 {_number(result.get('top_wallet_pct'), '.0f')}%")
    if result.get("wash_blocked"):
        extras.append("⚠️ volume > 3× MC (wash?)")
    smart = result.get("smart_money_buy") or 0
    fresh = result.get("fresh_buy") or 0
    bot = result.get("bot_sell") or 0
    mev = result.get("mev_noise") or 0
    if smart or fresh or bot or mev:
        extras.append(f"smart {smart} · fresh {fresh} · bot {bot} · mev {mev}")
    lines.extend(extras)

    if not lines:
        return ""
    weight = "700" if is_signal else "600"
    body = "<br>".join(html.escape(line) for line in lines)
    return (f'<div class="signal-detail {tone}" '
            f'style="font-size:0.62rem;line-height:1.35;'
            f'font-weight:{weight};text-align:center;margin-top:0.15rem;">'
            f'{body}</div>')


watchlist = load_watchlist()
effort_rows = load_daily_effort()
st.subheader("📋 Watchlist")
st.caption("Candle & ΔCVD harian: 00:00–23:59 UTC | Volume dibandingkan "
           "antar-hari dalam USD | Flush = hari CVD ≤ -30 SOL (lookback 5 hari)")

if not watchlist:
    st.info("Watchlist masih kosong. Tambahkan contract address di bawah.")
else:
    # Header row with styled columns
    header_cols = st.columns([1.5, 0.95, 1.6, 0.9, 2.3, 0.85, .5, .5])
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
    header_titles = ["Token", "Tanggal", "Sinyal", "CVD", "Detail & flush", "Volume", "Chart", ""]
    for col, style, title in zip(header_cols, header_styles, header_titles):
        col.markdown(f'<div style="{style}">{title}</div>', unsafe_allow_html=True)

    st.markdown('<hr style="margin:0.5rem 0;border-color:#cbd5e1;">', unsafe_allow_html=True)

    for mint, meta in watchlist.items():
        history = rows_for_mint(effort_rows, mint)
        result = classify_effort(history, mint)

        symbol = str((meta or {}).get("symbol") or "?").upper()
        date = result.get("date") or "—"
        cvd_n = _signed(result.get('cvd_delta'), '+.2f')
        volume_pct = result.get('volume_pct')
        volume_txt = (f"{_number(volume_pct, '.0f')}%"
                      if volume_pct is not None else "—")
        status = result.get("status") or "missing"

        badges_html = _signal_badge(result)
        if result.get("whale_driven"):
            badges_html += '<br><span class="status-badge badge-warning">🐋 WHALE &ge;40%</span>'
        elif status == "missing":
            badges_html += '<br><span class="status-badge badge-info">⚠️ BELUM ADA DATA</span>'

        # Detail: flush reference, volume vs kemarin, penanda on-chain
        detail_html = _signal_detail_html(result)

        # Render row with clean layout
        cols = st.columns([1.5, 0.95, 1.6, 0.9, 2.3, 0.85, .5, .5])

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

        # CVD column (hari N)
        cols[3].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{cvd_n}</div>'
            f'<div class="watchlist-metric-sub">SOL</div>'
            f'</div>',
            unsafe_allow_html=True)

        # Detail column (narasi sinyal + penanda info)
        cols[4].markdown(
            f'<div class="watchlist-metric">{detail_html}</div>',
            unsafe_allow_html=True)

        # Volume vs kemarin column
        cols[5].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{volume_txt}</div>'
            f'<div class="watchlist-metric-sub">vs kemarin</div>'
            f'</div>',
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
st.caption("Listing GMGN sebagai konteks pasar. Sinyal bottom hanya dari "
           "ΔCVD dan volume USD harian.")

# Tab styling: segmented control dipakai agar pilihan tab bertahan saat scan
# memicu rerun (st.tabs selalu balik ke tab pertama).
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

# Pilihan tab disimpan di session_state supaya rerun setelah "Scan Degen"
# tidak melempar tampilan kembali ke Trending.
active_tab = st.session_state.get("discover_tab_active", TREND_TAB)
selected_tab = st.segmented_control(
    "Mode listing", DISCOVER_TABS, default=active_tab,
    key="discover_tab", label_visibility="collapsed")
if selected_tab not in DISCOVER_TABS:
    # Klik ulang pada tab aktif tidak boleh mengosongkan pilihan.
    selected_tab = active_tab
st.session_state["discover_tab_active"] = selected_tab

if selected_tab == DEGEN_TAB:
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
else:
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
