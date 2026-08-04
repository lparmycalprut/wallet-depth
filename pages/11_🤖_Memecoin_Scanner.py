# -*- coding: utf-8 -*-
"""Page: Memecoin Scanner — 5 Fase Scoring System untuk deteksi pola akumulasi.

Logic port dari https://github.com/lparmycalprut/memecoin_scanner
Scan setiap 15 menit via GitHub Actions cron.
"""

import json
import os
import sys
import time

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watchlist import load_watchlist
from memecoin_scanner import (
    load_state, load_config, send_telegram, fetch_token_data,
    analyze_token, ScanResult,
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
.scanner-card.alert {
    border: 2px solid #22c55e;
    box-shadow: 0 0 10px rgba(34, 197, 94, 0.3);
}
.phase-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 3px 0;
    font-size: 0.8rem;
}
.phase-label {
    min-width: 140px;
    color: #94a3b8;
}
.phase-bar-bg {
    flex: 1;
    height: 8px;
    background: rgba(148,163,184,0.15);
    border-radius: 4px;
    overflow: hidden;
}
.phase-bar-fill {
    height: 100%;
    border-radius: 4px;
}
.phase-score {
    min-width: 50px;
    text-align: right;
    font-weight: 700;
}
</style>""", unsafe_allow_html=True)

st.title("🤖 Memecoin Scanner")
st.caption("5 Fase Scoring System — deteksi pola akumulasi early stage token. "
           "Logic port dari [memecoin_scanner](https://github.com/lparmycalprut/memecoin_scanner)")

# ---------------------------------------------------------------------------
# Info panel
# ---------------------------------------------------------------------------
with st.expander("📊 Cara Kerja Scanner (5 Fase Scoring)", expanded=False):
    st.markdown("""
    **5 Fase Scoring System** (total 100 poin):
    
    | Fase | Max Pts | Apa yang dinilai |
    |------|---------|-----------------|
    | 1. Liquidity Test | 15 | Tx count & volume 1 jam (early stage detection) |
    | 2. Slow Accumulation | 20 | Transaction growth h1 vs h6 |
    | 3. Whale Entry | 20 | Whale transactions dari Helius onchain |
    | 4. Volume Spike | 25 | Volume h1 vs avg h6 |
    | 5. Thin Liquidity | 20 | Likuiditas tipis = early opportunity |
    
    **Alert threshold:** Score >= 60/100
    
    **Scan interval:** Setiap 15 menit (cron)
    
    **Data source:** DexScreener + Helius (untuk whale detection)
    
    **Konfigurasi threshold** (di config.json):
    ```json
    {
      "alert_score_threshold": 60,
      "liquidity_threshold": 300000,
      "fdv_threshold": 2000000,
      "volume_spike_x": 10,
      "tx_spike_x": 10,
      "whale_min_amount": 1000,
      "whale_lookback_hours": 3
    }
    ```
    """)

# ---------------------------------------------------------------------------
# Config & status
# ---------------------------------------------------------------------------
config = load_config()
state = load_state()

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("⏱️ Scan Interval", f"{config['scan_interval_minutes']} menit")
with col2:
    st.metric("🎯 Alert Threshold", f"{config['alert_score_threshold']}/100")
with col3:
    last_scan = state.get("last_scan_ts")
    if last_scan:
        ago_min = (time.time() - last_scan) / 60
        st.metric("📅 Last Scan", f"{ago_min:.0f} min ago")
    else:
        st.metric("📅 Last Scan", "never")
with col4:
    if st.button("🔄 Run Scan Now", type="primary", use_container_width=True):
        with st.spinner("Running 5-phase scan..."):
            from memecoin_scanner import run_scan
            result = run_scan()
            st.success(f"✅ Done! Scanned {result['tokens_scanned']} tokens, "
                      f"{result['alerts_sent']} alert(s) sent to Telegram.")
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Load watchlist & run scan for display
# ---------------------------------------------------------------------------
wl = load_watchlist()

if not wl:
    st.warning("⚠️ Watchlist kosong. Tambahkan token di halaman ⭐ Watchlist terlebih dahulu.")
    st.stop()

# Run scan for display (fetch + analyze all tokens)
scan_results = []
progress_bar = st.progress(0, text="Scanning tokens...")

for i, (ca, meta) in enumerate(wl.items()):
    progress_bar.progress(
        (i + 1) / len(wl), 
        text=f"Scanning {i+1}/{len(wl)}: {meta.get('symbol', ca[:8])}..."
    )
    
    try:
        data = fetch_token_data(ca)
        if not data:
            continue
        result = analyze_token(data, config)
        if result:
            scan_results.append({
                "ca": ca,
                "symbol": result.symbol,
                "score": result.score,
                "phases": result.phases,
                "has_alert": result.alert_message is not None,
                "alert_message": result.alert_message,
                "data": data,
                "timestamp": result.timestamp,
            })
    except Exception as exc:
        st.warning(f"Error scanning {ca[:8]}: {exc}")

progress_bar.empty()

if not scan_results:
    st.info("Tidak ada data scan. Coba klik **Run Scan Now** di atas.")
    st.stop()

# Sort by score descending
scan_results.sort(key=lambda r: r["score"], reverse=True)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total_tokens = len(scan_results)
alerts_count = sum(1 for r in scan_results if r["has_alert"])
avg_score = sum(r["score"] for r in scan_results) / total_tokens if total_tokens else 0

sum_col1, sum_col2, sum_col3 = st.columns(3)
with sum_col1:
    st.metric("📊 Total Tokens", total_tokens)
with sum_col2:
    st.metric("🚨 Alerts (≥60 pts)", alerts_count)
with sum_col3:
    st.metric("📈 Avg Score", f"{avg_score:.0f}/100")

st.divider()

# ---------------------------------------------------------------------------
# Token cards with phase breakdown
# ---------------------------------------------------------------------------
PHASE_NAMES = {
    "liquidity_test": ("1. Liquidity Test", 15),
    "slow_accumulation": ("2. Slow Accumulation", 20),
    "whale_entry": ("3. Whale Entry", 20),
    "volume_spike": ("4. Volume Spike", 25),
    "thin_liquidity": ("5. Thin Liquidity", 20),
}

for r in scan_results:
    ca = r["ca"]
    symbol = r["symbol"]
    score = r["score"]
    phases = r["phases"]
    data = r["data"]
    has_alert = r["has_alert"]

    # Card class
    card_class = "scanner-card alert" if has_alert else "scanner-card"

    # Score color
    if score >= 60:
        score_color = "#22c55e"
        score_emoji = "🟢"
    elif score >= 40:
        score_color = "#facc15"
        score_emoji = "🟡"
    else:
        score_color = "#ef4444"
        score_emoji = "🔴"

    # Phase bars HTML
    phase_bars_html = ""
    for phase_key, (phase_name, max_pts) in PHASE_NAMES.items():
        phase_data = phases.get(phase_key, {})
        phase_score = phase_data.get("score", 0)
        phase_detail = phase_data.get("detail", "")
        
        # Color based on score percentage
        pct = phase_score / max_pts if max_pts > 0 else 0
        if pct >= 0.7:
            fill_color = "#22c55e"
        elif pct >= 0.4:
            fill_color = "#facc15"
        else:
            fill_color = "#ef4444"
        
        phase_bars_html += f"""
        <div class="phase-bar">
            <span class="phase-label">{phase_name}</span>
            <div class="phase-bar-bg">
                <div class="phase-bar-fill" style="width:{pct*100:.0f}%;background:{fill_color};"></div>
            </div>
            <span class="phase-score" style="color:{fill_color};">{phase_score}/{max_pts}</span>
        </div>
        <div style="font-size:0.72rem;color:#64748b;margin-left:148px;margin-bottom:4px;">
            {phase_detail}
        </div>
        """

    # Token info
    price = data.get("price_usd", 0)
    liq = data.get("liquidity_usd", 0)
    fdv = data.get("fdv", 0)
    vol_h1 = data.get("volume_h1", 0)
    tx_h1 = data.get("txns_h1", {})
    buys = tx_h1.get("buys", 0)
    sells = tx_h1.get("sells", 0)

    # Format helpers
    def fmt_price(v):
        if v >= 1:
            return f"${v:,.4f}"
        elif v >= 0.001:
            return f"${v:.6f}"
        else:
            return f"${v:.10f}".rstrip("0")

    def fmt_usd(v):
        if v >= 1e6:
            return f"${v/1e6:.2f}M"
        elif v >= 1e3:
            return f"${v/1e3:.1f}K"
        return f"${v:.0f}"

    # Render card
    html = f"""
    <div class="{card_class}">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
                <span style="font-size:1.2rem;font-weight:800;color:#e2e8f0;">
                    {score_emoji} ${symbol}
                </span>
                <span style="font-size:0.75rem;color:#64748b;margin-left:8px;">
                    {ca[:8]}…{ca[-4:]}
                </span>
            </div>
            <div style="text-align:right;">
                <span style="font-size:1.5rem;font-weight:800;color:{score_color};">
                    {score}
                </span>
                <span style="font-size:0.85rem;color:#94a3b8;">/100</span>
            </div>
        </div>

        <div style="display:flex;gap:16px;margin-top:8px;font-size:0.8rem;color:#94a3b8;">
            <span>💰 {fmt_price(price)}</span>
            <span>💧 Liq {fmt_usd(liq)}</span>
            <span>📊 FDV {fmt_usd(fdv)}</span>
            <span>📈 Vol 1h {fmt_usd(vol_h1)}</span>
            <span>🔄 Tx {buys}B / {sells}S</span>
        </div>

        <div style="margin-top:12px;padding-top:12px;border-top:1px solid #334155;">
            <div style="font-size:0.85rem;font-weight:700;color:#94a3b8;margin-bottom:8px;">
                📊 Phase Breakdown
            </div>
            {phase_bars_html}
        </div>

        <div style="display:flex;gap:10px;margin-top:12px;font-size:0.75rem;">
            <a href="https://dexscreener.com/solana/{ca}" target="_blank" 
               style="color:#64748b;text-decoration:none;">🦆 DexScreener</a>
            <a href="https://gmgn.ai/sol/token/{ca}" target="_blank" 
               style="color:#64748b;text-decoration:none;">⚡ GMGN</a>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(f"🤖 Memecoin Scanner · 5 Fase Scoring System · "
           f"Port dari [memecoin_scanner](https://github.com/lparmycalprut/memecoin_scanner) · "
           f"Data: DexScreener + Helius")
