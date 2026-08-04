# -*- coding: utf-8 -*-
"""Page: Memecoin Scanner — watchlist monitoring with 15-minute Telegram updates."""

import json
import os
import sys
import time

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watchlist import load_watchlist
from memecoin_scanner import (
    load_state, save_state, send_telegram, fetch_dexscreener_batch,
    scan_token, build_summary_message, build_quiet_message,
)

st.set_page_config(page_title="Memecoin Scanner", page_icon="🤖",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.72rem !important;}
.scanner-card {
    background: #131a26;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 10px;
}
.scanner-card.urgent {
    border: 2px solid #ef4444;
}
.scanner-card.notable {
    border: 1px solid #facc15;
}
.alert-chip {
    display: inline-block;
    background: rgba(148,163,184,0.1);
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.75rem;
    margin: 2px 3px;
}
</style>""", unsafe_allow_html=True)

st.title("🤖 Memecoin Scanner")
st.caption("Memantau watchlist setiap 15 menit dan mengirim update via Telegram bot. "
           "Menggunakan wallet depth untuk detail akun setiap token.")

# ---------------------------------------------------------------------------
# Configuration panel
# ---------------------------------------------------------------------------
with st.expander("⚙️ Scanner Configuration", expanded=False):
    st.markdown("""
    **How it works:**
    - Scan dilakukan setiap **15 menit** oleh GitHub Actions cron
    - Update dikirim ke Telegram hanya jika ada perubahan notable
    - Quiet message (all clear) dikirim setiap jam ke-4
    - Data diambil dari: DexScreener (price), CVD store (conviction/flow),
      holder snapshots (delta), signals.json (alerts)

    **Alert thresholds:**
    - 🚨 Price change ≥15% (1h)
    - ⚠️ Price change ≥25% (6h)
    - 🔥 Price change ≥50% (24h)
    - 🔥 Conviction rising 3+ times consecutively
    - 💎 Accumulation / stealth accumulation signal
    - 🩸 Distribution signal
    - 📈📉 Holder delta ≥10

    **Setup:**
    1. Pastikan `telegram_bot_token` dan `telegram_chat_id` di config.json
    2. Workflow `memecoin-scanner.yml` berjalan setiap 15 menit
    3. Watchlist token otomatis di-scan
    """)

    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        if st.button("🔄 Run Scan Now", type="primary", use_container_width=True):
            from memecoin_scanner import run_scan
            result = run_scan(quiet_every=0)  # force send for manual trigger
            if result["sent"]:
                st.success(f"✅ Scan complete! {result['tokens_scanned']} tokens scanned, "
                          f"{result['tokens_notable']} notable. Message sent to Telegram.")
            else:
                st.info(f"ℹ️ Scan complete. {result['tokens_scanned']} tokens scanned, "
                       f"{result['tokens_notable']} notable. {result['message']}")
            st.rerun()

    with col_cfg2:
        state = load_state()
        last_scan = state.get("last_scan_time", "never")
        last_sent = state.get("last_sent_ts", 0)
        if last_sent:
            ago_min = (time.time() - last_sent) / 60
            st.metric("Last scan", f"{last_scan} WIB",
                     f"{ago_min:.0f} min ago")
        else:
            st.metric("Last scan", "never")

# ---------------------------------------------------------------------------
# Scanner status
# ---------------------------------------------------------------------------
state = load_state()
scanner_results = {}
try:
    results_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scanner_results.json")
    with open(results_path, "r") as f:
        scanner_results = json.load(f) or {}
except Exception:
    pass

# Status bar
status_col1, status_col2, status_col3, status_col4 = st.columns([1, 1, 1, 1])

with status_col1:
    last_time = scanner_results.get("time_wib", "—")
    st.metric("📅 Last Scan", last_time + " WIB" if last_time != "—" else "—")

with status_col2:
    n_scanned = len(scanner_results.get("results", []))
    st.metric("📊 Tokens Scanned", n_scanned)

with status_col3:
    n_notable = scanner_results.get("notable_count", 0)
    st.metric("⚡ Notable", n_notable)

with status_col4:
    sent_status = "✅ Sent" if scanner_results.get("message_sent") else "⏸️ Queued"
    st.metric("📱 Telegram", sent_status)

st.divider()

# ---------------------------------------------------------------------------
# Live scan results
# ---------------------------------------------------------------------------
wl = load_watchlist()

if not wl:
    st.warning("Watchlist kosong. Tambahkan token di halaman ⭐ Watchlist terlebih dahulu.")
    st.stop()

# Fetch live data for display
cas = list(wl.keys())
markets = fetch_dexscreener_batch(cas)

if not markets:
    st.warning("Tidak bisa mengambil data harga dari DexScreener. Coba refresh.")
    st.stop()

# Scan all tokens for display
scan_results = []
for ca, meta in wl.items():
    market = markets.get(ca)
    if not market:
        continue
    try:
        result = scan_token(ca, meta, market)
        if result:
            scan_results.append(result)
    except Exception:
        pass

# Sort: urgent first, then by conviction trend, then by 1h change
scan_results.sort(key=lambda r: (
    0 if r.get("has_urgent") else (1 if r.get("has_notable") else 2),
    -abs(r.get("chg1", 0)),
))

# ---------------------------------------------------------------------------
# Token cards
# ---------------------------------------------------------------------------
if scan_results:
    # Filter controls
    filter_col1, filter_col2 = st.columns([1, 3])
    with filter_col1:
        filter_mode = st.radio("Filter", ["All", "Notable Only", "Urgent Only"],
                              horizontal=True, label_visibility="collapsed")

    with filter_col2:
        st.caption(f"Menampilkan {len(scan_results)} token dari watchlist · "
                  f"Data live dari DexScreener + CVD store")

    filtered = scan_results
    if filter_mode == "Notable Only":
        filtered = [r for r in scan_results if r.get("has_notable")]
    elif filter_mode == "Urgent Only":
        filtered = [r for r in scan_results if r.get("has_urgent")]

    if not filtered:
        st.info(f"Tidak ada token yang {'urgent' if filter_mode == 'Urgent Only' else 'notable'} saat ini.")
        if filter_mode == "All":
            st.caption("Semua token dalam kondisi normal — tidak ada perubahan signifikan.")

    for r in filtered:
        ca = r["ca"]
        sym = r["symbol"]
        price = r["price"]
        chg1 = r.get("chg1", 0)
        chg6 = r.get("chg6", 0)
        chg24 = r.get("chg24", 0)
        mc = r.get("mc", 0)
        vol24 = r.get("vol24", 0)
        liq = r.get("liq", 0)
        conv = r.get("conviction")
        trend = r.get("conv_trend", "flat")
        net_pure = r.get("net_pure")
        alerts = r.get("alerts", [])
        signals = r.get("signals", [])

        # Card styling
        card_class = "scanner-card"
        if r.get("has_urgent"):
            card_class += " urgent"
        elif r.get("has_notable"):
            card_class += " notable"

        # Price formatting
        if price >= 1:
            price_str = f"${price:,.4f}"
        elif price >= 0.001:
            price_str = f"${price:.6f}"
        else:
            price_str = f"${price:.10f}".rstrip("0")

        # MC / Vol / Liq formatting
        def fmt_usd(v):
            if v >= 1e6:
                return f"${v/1e6:.2f}M"
            elif v >= 1e3:
                return f"${v/1e3:.1f}K"
            return f"${v:.0f}"

        # Change display
        def chg_html(v):
            if v == 0:
                return f'<span style="color:#94a3b8;">{v:+.1f}%</span>'
            color = "#22c55e" if v > 0 else "#ef4444"
            arrow = "▲" if v > 0 else "▼"
            return f'<span style="color:{color};font-weight:700;">{arrow} {abs(v):.1f}%</span>'

        # Conviction bar
        conv_bar = ""
        if conv is not None:
            conv_color = "#22c55e" if conv >= 50 else "#facc15" if conv >= 30 else "#ef4444"
            trend_icon = {"rising": "📈", "falling": "📉", "flat": "➡️"}.get(trend, "➡️")
            conv_bar = (
                f'<div style="display:flex;align-items:center;gap:6px;margin-top:6px;">'
                f'<span style="font-size:0.75rem;color:#94a3b8;">Conviction</span>'
                f'<div style="flex:1;height:6px;background:rgba(148,163,184,0.15);'
                f'border-radius:3px;overflow:hidden;">'
                f'<div style="width:{conv}%;height:100%;background:{conv_color};'
                f'border-radius:3px;"></div></div>'
                f'<span style="color:{conv_color};font-weight:800;font-size:0.85rem;">'
                f'{conv:.0f}% {trend_icon}</span></div>'
            )

        # Net pure indicator
        net_html = ""
        if net_pure is not None:
            net_color = "#22c55e" if net_pure >= 0 else "#ef4444"
            net_icon = "💚" if net_pure >= 0 else "💔"
            net_html = (f'<span style="color:{net_color};font-size:0.75rem;">'
                       f'{net_icon} Net: {net_pure:+.0f} SOL</span>')

        # Alerts chips
        alerts_html = ""
        if alerts:
            chips = "".join(f'<span class="alert-chip">{a}</span>' for a in alerts)
            alerts_html = f'<div style="margin-top:8px;">{chips}</div>'

        # Signals detail
        signals_html = ""
        if signals:
            sig_lines = []
            for sig in signals[:3]:
                sig_type = sig.get("type", "?")
                detail = (sig.get("detail") or "")[:80]
                emoji = {"accumulation": "💎", "stealth_accumulation": "🕵️",
                        "distribution": "🩸", "bullish_div": "📈",
                        "bearish_div": "📉"}.get(sig_type, "📊")
                sig_lines.append(f'{emoji} <b>{sig_type}</b>: {detail}')
            signals_html = (
                f'<div style="margin-top:6px;padding:6px 10px;'
                f'background:rgba(148,163,184,0.06);border-radius:6px;'
                f'font-size:0.75rem;color:#94a3b8;">'
                + "<br>".join(sig_lines) + "</div>"
            )

        # Links
        links = (
            f'<div style="display:flex;gap:10px;margin-top:8px;font-size:0.75rem;">'
            f'<a href="https://dexscreener.com/solana/{ca}" target="_blank" '
            f'style="color:#64748b;text-decoration:none;">🦆 DexScreener</a>'
            f'<a href="https://gmgn.ai/sol/token/{ca}" target="_blank" '
            f'style="color:#64748b;text-decoration:none;">⚡ GMGN</a>'
            f'<a href="/CVD?ca={ca}" target="_self" '
            f'style="color:#64748b;text-decoration:none;">📊 CVD</a>'
            f'</div>'
        )

        # Render card
        header_emoji = "🚨" if r.get("has_urgent") else ("⚡" if r.get("has_notable") else "•")
        html = f"""
        <div class="{card_class}">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                    <span style="font-size:1.1rem;font-weight:800;color:#e2e8f0;">
                        {header_emoji} ${sym}
                    </span>
                    <span style="font-size:0.75rem;color:#64748b;margin-left:8px;">
                        {ca[:8]}…{ca[-4:]}
                    </span>
                </div>
                <div style="text-align:right;">
                    <span style="font-size:1rem;font-weight:800;color:#e2e8f0;">
                        {price_str}
                    </span>
                </div>
            </div>

            <div style="display:flex;gap:16px;margin-top:8px;font-size:0.8rem;">
                <span>1h {chg_html(chg1)}</span>
                <span>6h {chg_html(chg6)}</span>
                <span>24h {chg_html(chg24)}</span>
            </div>

            <div style="display:flex;gap:16px;margin-top:6px;font-size:0.75rem;color:#94a3b8;">
                <span>MC {fmt_usd(mc)}</span>
                <span>Vol {fmt_usd(vol24)}</span>
                <span>LiQ {fmt_usd(liq)}</span>
            </div>

            {conv_bar}

            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">
                {net_html}
            </div>

            {alerts_html}
            {signals_html}
            {links}
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)

else:
    st.info("Tidak ada data scan. Klik **Run Scan Now** di atas untuk memulai scan pertama.")

# ---------------------------------------------------------------------------
# Workflow info
# ---------------------------------------------------------------------------
st.divider()
with st.expander("📋 GitHub Actions Workflow Info", expanded=False):
    st.markdown("""
    **Workflow:** `.github/workflows/memecoin-scanner.yml`

    **Schedule:** Setiap 15 menit (`*/15 * * * *`)

    **Cara kerja:**
    1. Checkout repo
    2. Install dependencies
    3. Jalankan `python memecoin_scanner.py`
    4. Scanner membaca watchlist.json
    5. Untuk setiap token: fetch harga, conviction, holder delta, signals
    6. Jika ada perubahan notable → kirim Telegram
    7. Quiet message (semua normal) dikirim setiap jam ke-4

    **Required Secrets:**
    - `TELEGRAM_BOT_TOKEN` — token bot Telegram
    - `TELEGRAM_CHAT_ID` — chat ID target

    **Manual trigger:**
    - GitHub → Actions → Memecoin Scanner → Run workflow
    - Atau klik tombol "Run Scan Now" di atas (butuh config.json dengan Telegram credentials)
    """)

st.caption("🤖 Memecoin Scanner · Powered by wallet-depth · "
           "Data: DexScreener, CVD store, holder snapshots, signals")
