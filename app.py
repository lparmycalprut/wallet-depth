# -*- coding: utf-8 -*-
"""Wallet Depth — dashboard reversal realtime (wash-collapse)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html

import streamlit as st

from links import external_links_html
from reversal_status import (SIGNAL_META, load_reversal_status,
                             status_sort_key)
from trending_ui import (render_trending, run_screen, run_screen_h1,
                         run_screen_hrhr, run_screen_hrhr_h1)
from watchlist import (add_to_watchlist, get_last_push_error, load_watchlist,
                       remove_from_watchlist)

st.set_page_config(page_title="Wallet Depth — Reversal Realtime",
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
.badge-watch {background:#854d0e;color:#fef9c3}
.badge-strong {background:#14532d;color:#dcfce7}
.dist{background:#9a3412;color:#ffedd5}
/* Detail sinyal selalu putih agar terbaca di background badge. */
.signal-detail,
.signal-detail.bull,
.signal-detail.rev,
.signal-detail.aku,
.signal-detail.dist,
.signal-detail.bear,
.signal-detail.neutral {color:#ffffff !important}
</style>
<div class="hero"><h1>⚡ Wallet Depth</h1>
<p>Scanner realtime bidirectional: 🟢 REVERSAL UP, 🔴 REVERSAL DOWN,
🔵 ACCUMULATION, 🟠 DISTRIBUTION — wash-collapse 6 jam vs 24 jam sebelumnya.
Status watchlist mengikuti scan GitHub Actions (tiap ~10 menit), bukan candle
harian.</p></div>
""", unsafe_allow_html=True)


def _signal_tone(row):
    signal = (row or {}).get("signal") or ""
    meta = SIGNAL_META.get(signal)
    if meta:
        return meta.get("tone") or "neutral"
    return "neutral"


def _signal_badge(row):
    if not row:
        return ('<span class="signal neutral">—</span>'
                '<br><span class="status-badge badge-info">'
                '⚠️ BELUM ADA SCAN</span>')
    signal = row.get("signal") or "NEUTRAL"
    meta = SIGNAL_META.get(signal) or {}
    css = meta.get("tone") or "neutral"
    label = meta.get("label") or signal
    return f'<span class="signal {css}">{html.escape(label)}</span>'


def _number(value, pattern=".1f"):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


def _signed(value, pattern="+.1f", suffix=""):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern) + suffix
    except (TypeError, ValueError):
        return "—"


def _wib(ts):
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(hours=7)
    return when.strftime("%d %b %H:%M") + " WIB"


def _confidence_badge(row):
    if not row:
        return ""
    confidence = row.get("confidence") or ""
    if confidence == "strong":
        return '<br><span class="status-badge badge-strong">🟢 KUAT</span>'
    if confidence == "watch":
        return '<br><span class="status-badge badge-watch">🟡 WATCH</span>'
    return ""


def _signal_detail_html(row):
    """Narasi sama dengan alert Telegram: konteks, window sekarang, wallet."""
    if not row:
        return ('<div class="signal-detail neutral" style="font-size:0.62rem;'
                'line-height:1.35;font-weight:600;text-align:center;'
                'margin-top:0.15rem;">Menunggu hasil scanner realtime'
                '</div>')
    current = row.get("current") or {}
    context = row.get("context") or {}
    signal = row.get("signal") or ""
    tone = _signal_tone(row)
    lines = []
    context_name = "flush" if signal == "REVERSAL_UP" else (
        "pump" if signal == "REVERSAL_DOWN" else "konteks")
    if context:
        lines.append(
            f"{context_name.capitalize()} "
            f"{_signed(context.get('cvd_delta_clean'))} SOL · wash "
            f"{_number(context.get('wash_pct'))}%")
    if current:
        prior_wash = context.get("wash_pct")
        now_wash = current.get("wash_pct")
        collapse = ""
        try:
            if prior_wash and float(prior_wash) > 0 and now_wash is not None:
                pct = 100 * (1 - float(now_wash) / float(prior_wash))
                collapse = f" (runtuh {pct:.0f}%)"
        except (TypeError, ValueError, ZeroDivisionError):
            collapse = ""
        lines.append(
            f"CVD bersih {_signed(current.get('cvd_delta_clean'))} · "
            f"wash {_number(now_wash)}%{collapse} · harga "
            f"{_signed(current.get('price_chg_pct'))}%")
        makers = current.get("unique_makers")
        if makers:
            smart_net = current.get("smart_net_sol")
            if smart_net is None:
                smart_bias = "flat"
            elif float(smart_net) > 0:
                smart_bias = "net beli"
            elif float(smart_net) < 0:
                smart_bias = "net jual"
            else:
                smart_bias = "flat"
            lines.append(
                f"Wallet {makers} maker · smart "
                f"{int(current.get('smart_money_buy') or 0)} "
                f"({smart_bias} {_signed(smart_net)} SOL) · fresh "
                f"{int(current.get('fresh_buy') or 0)} "
                f"({_number(current.get('fresh_buy_sol'))} SOL) · "
                f"bot-sell {int(current.get('bot_sell') or 0)}")
            lines.append(
                f"Whale top-1 {_number(current.get('top_wallet_pct'))}% · "
                f"top-3 {_number(current.get('top3_wallet_pct'))}% · "
                f"net {_signed(current.get('top_wallet_net_sol'))} SOL · "
                f"churn {_number(current.get('top_wallet_churn_pct'), '.0f')}%")
    reason = str(row.get("reason") or "").strip()
    if reason:
        lines.append(reason)
    if not lines:
        return ""
    body = "<br>".join(html.escape(line) for line in lines)
    return (f'<div class="signal-detail {tone}" '
            f'style="font-size:0.62rem;line-height:1.35;'
            f'font-weight:700;text-align:center;margin-top:0.15rem;">'
            f'{body}</div>')


watchlist = load_watchlist()
force_status = bool(st.session_state.pop("status_force_refresh", False))
reversal = load_reversal_status(force_refresh=force_status)
status_tokens = reversal.get("tokens") or {}

st.subheader("📋 Watchlist")
updated_label = _wib(reversal.get("updated_at"))
st.caption("Status dari scanner realtime (rolling 6 jam vs 24 jam sebelumnya), "
           f"bukan candle harian. Terakhir di-scan: {updated_label}. "
           "Klik muat ulang jika Telegram sudah kirim sinyal baru.")
refresh_col, _ = st.columns([1, 4])
if refresh_col.button("🔄 Muat ulang status", use_container_width=True):
    st.session_state["status_force_refresh"] = True
    st.rerun()

if not watchlist:
    st.info("Watchlist masih kosong. Tambahkan contract address di bawah.")
else:
    header_cols = st.columns([1.5, 1.7, 0.95, 0.85, 2.4, 1.0, .5, .5])
    header_style = "font-size:0.8rem;color:#000000;font-weight:700;"
    center = "text-align:center;" + header_style
    header_titles = ["Token", "Sinyal", "CVD bersih", "Wash",
                     "Detail", "Scan", "Chart", ""]
    header_css = [header_style, header_style, center, center,
                  center, center, center, center]
    for col, style, title in zip(header_cols, header_css, header_titles):
        col.markdown(f'<div style="{style}">{title}</div>',
                     unsafe_allow_html=True)

    st.markdown('<hr style="margin:0.5rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)

    ordered = sorted(watchlist.items(),
                     key=lambda item: status_sort_key(
                         item[0], status_tokens.get(item[0])))
    for mint, meta in ordered:
        row = status_tokens.get(mint)
        symbol = str((meta or {}).get("symbol")
                     or (row or {}).get("symbol") or "?").upper()
        current = (row or {}).get("current") or {}
        cvd_n = _signed(current.get("cvd_delta_clean"), "+.1f")
        wash_txt = (_number(current.get("wash_pct")) + "%"
                    if current.get("wash_pct") is not None else "—")
        badges_html = _signal_badge(row) + _confidence_badge(row)
        detail_html = _signal_detail_html(row)
        scanned = _wib((row or {}).get("last_scan_ts")
                       or reversal.get("updated_at"))

        cols = st.columns([1.5, 1.7, 0.95, 0.85, 2.4, 1.0, .5, .5])
        cols[0].markdown(
            f'<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'<span class="watchlist-mint">{html.escape(mint[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(mint)}</div>'
            f'</div>',
            unsafe_allow_html=True)
        cols[1].markdown(badges_html, unsafe_allow_html=True)
        cols[2].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{cvd_n}</div>'
            f'<div class="watchlist-metric-sub">SOL</div>'
            f'</div>',
            unsafe_allow_html=True)
        cols[3].markdown(
            f'<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{wash_txt}</div>'
            f'<div class="watchlist-metric-sub">6 jam</div>'
            f'</div>',
            unsafe_allow_html=True)
        cols[4].markdown(
            f'<div class="watchlist-metric">{detail_html}</div>',
            unsafe_allow_html=True)
        cols[5].markdown(
            f'<div style="font-size:0.75rem;color:#000000;text-align:center;">'
            f'{html.escape(scanned)}</div>',
            unsafe_allow_html=True)
        if cols[6].button("📈", key=f"chart-{mint}",
                          help="Buka chart historis",
                          use_container_width=True):
            st.session_state["effort_mint"] = mint
            st.switch_page("pages/4_📊_CVD.py")
        if cols[7].button("✕", key=f"remove-{mint}",
                          help="Hapus dari watchlist",
                          use_container_width=True):
            remove_from_watchlist(mint)
            st.rerun()
        st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)

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
st.caption("Listing GMGN sebagai konteks pasar. Status watchlist di atas "
           "mengikuti scanner reversal realtime, bukan candle harian.")

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
