# ⚠️ CATATAN: Page ini baru dibuat 2026-08-06 untuk manual check prepump.
# Tidak sedang dinonaktifkan — ini halaman baru (tidak ada di DISABLED.md).
# Referensi: DISABLED.md (untuk halaman 1/10/11 yang dimatikan).
# -*- coding: utf-8 -*-
"""🎯 Prepump Checker — manual cek fase prepump untuk 1 token (CA).

Usage:
  1. Masukkan CA token Solana (atau pilih dari watchlist)
  2. Klik "Cek Prepump"
  3. Lihat score, tier, pillar breakdown, dan metrik dari 30 menit terakhir

Data diambil dari cvd.json (swap store 72h). Jika data CVD stale (>1-2 jam),
hasil bisa 0/neutral karena tidak ada swap dalam 30 menit window.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from cvd import get_recent_swaps
from prepump_detector import evaluate_prepump

st.set_page_config(page_title="Prepump Checker", page_icon="🎯", layout="centered")

st.markdown("# 🎯 Prepump Checker")
st.caption("Manual cek fase pre-pump (30m window) dari data CVD lokal. Lihat DISABLED.md jika mencari halaman yang dimatikan.")

# --- Input ---
qp_ca = st.query_params.get("ca", "").strip()
default_ca = qp_ca or "AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump"
col_c, col_btn = st.columns([3, 1])
ca_input = col_c.text_input("Contract Address (CA)", placeholder="AkchGAUd... atau CA lain", value=default_ca)
check_now = col_btn.button("Cek Prepump", type="primary") or bool(qp_ca)

# --- Helper ---
@st.cache_data(ttl=60, show_spinner=False)
def _eval(ca, now_ts):
    try:
        swaps = get_recent_swaps(ca, hours=1)
        # If 1h empty, try 3h so we still have data for evaluation at newest point
        if not swaps:
            swaps = get_recent_swaps(ca, hours=3)
        if not swaps:
            return None, "Tidak ada swap dalam 3 jam terakhir (CVD mungkin stale)."
        # Use newest swap ts as reference for evaluation so we measure at data time
        newest_ts = max(int(s[2]) for s in swaps)
        result = evaluate_prepump(
            swaps,
            token_info={"symbol": "?"},
            ca=ca,
            now_ts=newest_ts,
            window_min=30,
        )
        return result, f"Evaluasi menggunakan data terakhir {len(swaps)} swap (ts={newest_ts})"
    except Exception as exc:
        return None, f"Error evaluasi: {exc}"

if check_now and ca_input:
    with st.spinner("Mengevaluasi prepump dari CVD..."):
        res, msg = _eval(ca_input.strip(), int(time.time()))

    if res is None:
        st.error(msg)
        st.info("Tips: pastikan CA ada di `watchlist.json` dan `cvd.json`. Cek `DISABLED.md` jika bingung.")
    else:
        score = float(res.get("score", 0))
        tier = res.get("tier", "?")
        blocked = res.get("blocked")
        stage = res.get("stage", "")
        comp = float(res.get("compression_pct", 0))
        pillars = res.get("pillars", {})
        metrics = res.get("metrics", {})

        # Tier badge
        badge_color = {"imminent": "#ef4444", "forming": "#fb923c", "neutral": "#64748b", "blocked": "#9ca3af"}.get(tier, "#94a3b8")
        tier_emoji = {"imminent": "🚨", "forming": "👀", "neutral": "➖", "blocked": "🚫"}.get(tier, "❓")

        st.metric(label="Prepump Score", value=f"{score}/100", delta=tier.upper() if tier != "neutral" else "neutral")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"""
            <div style="padding:12px;border-radius:8px;background:{badge_color}22;border-left:5px solid {badge_color}">
                <h3 style="margin:0;color:{badge_color}">{tier_emoji} {tier.upper()}</h3>
                <p style="margin:4px 0 0;font-size:0.95rem;color:#334155"><b>Score:</b> {score}/100</p>
                <p style="margin:2px 0 0;font-size:0.85rem;color:#64748b"><b>Stage:</b> {stage}</p>
            </div>
            """, unsafe_allow_html=True)
            st.caption(f"{msg}")

        with col2:
            if blocked:
                st.error(f"**Blocked**: {res.get('block_reason', '')}")
            else:
                st.success("Tidak diblokir (safety check lolos)")
            st.write(f"**Compression:** {comp:.1f}%")
            st.write(f"**Buy/Sell 30m:** {metrics.get('buy_vol', 0):.2f} / {metrics.get('sell_vol', 0):.2f} SOL")
            st.write(f"**Avg Buy vs Sell:** {metrics.get('avg_buy', 0):.2f} vs {metrics.get('avg_sell', 0):.2f} SOL (ratio {metrics.get('ratio', 0):.2f}×)")
            st.write(f"**Pure Accum %:** {metrics.get('pct_pure', 0)*100:.1f}%")
            st.write(f"**Smart (0-sell):** {metrics.get('smart_count', 0)} | **Active Terminals:** {metrics.get('active_terminals', []) or '-'}")
            st.write(f"**Whale Dumper:** {'Ya' if metrics.get('whale_dumper') else 'Tidak'}")

        # Pillar breakdown
        st.subheader("📊 Breakdown 4 Pilar")
        p = pillars
        pcols = st.columns(4)
        for idx, (label, key, icon) in enumerate([
            ("Compression", "compression", "📉"),
            ("Asymmetry", "asymmetry", "⚖️"),
            ("Accum", "accum", "🐋"),
            ("Delta/Ignition", "delta", "🔥"),
        ]):
            val = float(p.get(key, 0))
            color = "#22c55e" if val >= 15 else ("#f59e0b" if val >= 5 else "#94a3b8")
            with pcols[idx]:
                st.metric(label=f"{icon} {label}", value=f"{val:.0f}", help="Max 25 pts")

        # Raw metrics expandable
        with st.expander("🔍 Metrics Lengkap (JSON)"):
            st.json({k: v for k, v in res.items() if k in ["score","tier","stage","compression_pct","pillars","metrics","smart_tags_found","token_info"]})

        st.info("💡 Tips: kalau score 0 dan swap kosong → CVD mungkin stale (>1 jam). Cek `cvd.json` atau tunggu cron jam :30 WIB.")
else:
    st.info("Masukkan CA token, lalu klik **Cek Prepump**.")
    st.markdown("""
    **Contoh CA yang sudah ada di repo:**
    - `AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump` (looong)
    
    Lihat `DISABLED.md` jika mencari halaman lain yang dinonaktifkan.
    """)
