# ⚠️ CATATAN: Page ini baru dibuat 2026-08-06 untuk manual check prepump.
# Tidak sedang dinonaktifkan — ini halaman baru (tidak ada di DISABLED.md).
# Referensi: DISABLED.md (untuk halaman 1/10/11 yang dimatikan).
# Update 2026-08-06: Multi-Timeframe Pre-Pump Radar (30m/1h/4h/12h) +
# confluence status + export Markdown multi-timeframe.
# -*- coding: utf-8 -*-
"""🎯 Prepump Checker — manual cek fase prepump multi-timeframe untuk 1 token.

Usage:
  1. Masukkan CA token Solana (atau pilih dari watchlist)
  2. Klik "Cek Prepump"
  3. Lihat matriks skor 30m/1h/4h/12h, confluence status, breakdown 4 pilar
     per timeframe (tab), dan export report Markdown.

Timeframes (PREPUMP_TF_CONFIGS di prepump_detector.py):
  - 30m Micro Ignition / Timing      (window 30m,  baseline 4h,  min 3 buys)
  - 1h  Hourly Setup / Base          (window 60m,  baseline 8h,  min 5 buys)
  - 4h  Swing Channel / Wyckoff      (window 240m, baseline 24h, min 12 buys)
  - 12h Macro Cycle Base             (window 720m, baseline 48h, min 25 buys)

Confluence:
  🌟 GOLDEN (macro ≥60 & micro ≥75) · 🪤 DEAD CAT (micro 30m ≥70, macro <35)
  ⏳ SLEEPER (macro ≥65, 30m <40) · ➖ NORMAL/FORMING

Data diambil dari cvd.json (swap store 72h). Jika data CVD stale (>1-2 jam),
hasil bisa 0/neutral karena tidak ada swap dalam window terbaru.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from cvd import get_recent_swaps
from prepump_detector import (evaluate_prepump_multi_tf, PREPUMP_TF_ORDER,
                              PREPUMP_TIER_BADGES)

st.set_page_config(page_title="Prepump Checker", page_icon="🎯", layout="wide")

st.markdown("# 🎯 Prepump Checker — Multi-Timeframe")
st.caption("Manual cek fase pre-pump (30m / 1h / 4h / 12h) dari data CVD lokal. "
           "Lihat DISABLED.md jika mencari halaman yang dimatikan.")

# --- Input ---
qp_ca = st.query_params.get("ca", "").strip()
default_ca = qp_ca or "AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump"
col_c, col_btn = st.columns([3, 1])
ca_input = col_c.text_input("Contract Address (CA)", placeholder="AkchGAUd... atau CA lain", value=default_ca)
check_now = col_btn.button("Cek Prepump", type="primary") or bool(qp_ca)

_CONF_COLORS = {"golden": "#eab308", "dead_cat": "#ef4444",
                "sleeper": "#38bdf8", "normal": "#64748b"}
_TIER_COLORS = {"imminent": "#ef4444", "forming": "#fb923c",
                "neutral": "#64748b", "blocked": "#9ca3af"}
_PILLARS = [("Compression", "compression", "📉"),
            ("Asymmetry", "asymmetry", "⚖️"),
            ("Accumulation", "accum", "🐋"),
            ("Delta/Ignition", "delta", "🔥")]


# --- Helpers ---
@st.cache_data(ttl=60, show_spinner=False)
def _eval_multi(ca):
    """Evaluate all 4 timeframes from the local swap store (72h max).

    Uses the newest swap ts as the reference clock so the result reflects
    the stored data even when the store is a bit stale.
    """
    try:
        swaps = get_recent_swaps(ca, hours=72)
        if not swaps:
            return None, "Tidak ada swap dalam 72 jam terakhir (CVD mungkin stale)."
        newest_ts = max(int(s[2]) for s in swaps)
        multi = evaluate_prepump_multi_tf(
            swaps, token_info={"symbol": "?"}, ca=ca, now_ts=newest_ts)
        return multi, f"Evaluasi multi-TF dari {len(swaps)} swap (ref ts={newest_ts})"
    except Exception as exc:
        return None, f"Error evaluasi: {exc}"


def _build_markdown(ca, multi):
    """Markdown report with the multi-timeframe pre-pump summary table."""
    conf = multi.get("confluence", {})
    tfr = multi.get("timeframes", {})
    out = []
    out.append(f"# 🎯 Multi-Timeframe Pre-Pump Report — `{ca}`\n")
    out.append(f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    out.append(f"- Primary TF: **{multi.get('primary_tf', '30m')}** · "
               f"Overall: **{multi.get('overall_score', 0):g}/100 "
               f"{str(multi.get('overall_tier', '?')).upper()}**")
    out.append(f"- Confluence: **{conf.get('emoji', '➖')} {conf.get('label', '-')}** — "
               f"{conf.get('desc', '')} (macro 4h/12h {conf.get('macro_score', 0):g}/100 · "
               f"micro 30m/1h {conf.get('micro_score', 0):g}/100)\n")
    out.append("## 📊 Multi-Timeframe Summary\n")
    out.append("| Timeframe | Role | Score (0-100) | Tier | Confluence | "
               "Compression % | Buy/Sell Ratio | Net Flow SOL | Pure Accum % | "
               "Smart Wallets |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for tf in PREPUMP_TF_ORDER:
        r = tfr.get(tf)

        if not r:
            continue
        m = r.get("metrics", {})
        tier = r.get("tier", "neutral")
        badge = PREPUMP_TIER_BADGES.get(tier, "❓")
        out.append(f"| {tf} | {r.get('tf_role', '-')} | {r.get('score', 0):g} | "
                   f"{badge} {tier.upper()} | "
                   f"{conf.get('emoji', '➖')} {conf.get('label', '-')} | "
                   f"{r.get('compression_pct', 0):.1f}% | "
                   f"{m.get('ratio', 0):.2f}× | {m.get('net_sol', 0):+.2f} | "
                   f"{m.get('pct_pure', 0)*100:.0f}% | {m.get('smart_count', 0)} |")
    out.append("\n## 🧱 Pillar Breakdown per Timeframe\n")
    for tf in PREPUMP_TF_ORDER:
        r = tfr.get(tf)
        if not r:
            continue
        p = r.get("pillars", {})
        rs = r.get("reasons", {})
        m = r.get("metrics", {})
        out.append(f"### {tf} — {r.get('tf_role', '')} "
                   f"({r.get('score', 0):g}/100 {str(r.get('tier', '?')).upper()})")
        out.append(f"- P1 Compression: **{p.get('compression', 0):.0f}/25** — {rs.get('compression', '')}")
        out.append(f"- P2 Asymmetry: **{p.get('asymmetry', 0):.0f}/25** — {rs.get('asymmetry', '')}")
        out.append(f"- P3 Accumulation: **{p.get('accum', 0):.0f}/25** — {rs.get('accum', '')}")
        out.append(f"- P4 Delta/Ignition: **{p.get('delta', 0):.0f}/25** — {rs.get('delta', '')}")
        out.append(f"- Status: {r.get('stage', '-')} · Buys: {m.get('buy_count', 0)} "
                   f"(min {m.get('min_buy', 0)}) · Large dump ≥{m.get('large_dump_sol', 0):g} SOL: "
                   f"{'yes' if m.get('whale_dumper') else 'no'}\n")
    return "\n".join(out)


if check_now and ca_input:
    with st.spinner("Mengevaluasi prepump multi-timeframe dari CVD..."):
        multi, msg = _eval_multi(ca_input.strip())

    if multi is None:
        st.error(msg)
        st.info("Tips: pastikan CA ada di `watchlist.json` dan `cvd.json`. Cek `DISABLED.md` jika bingung.")
    else:
        conf = multi.get("confluence", {})
        tfr = multi.get("timeframes", {})
        st.caption(msg)

        # --- Confluence banner ---
        conf_color = _CONF_COLORS.get(conf.get("status"), "#64748b")
        st.markdown(f"""
        <div style="padding:12px 16px;border-radius:10px;background:{conf_color}18;border-left:5px solid {conf_color};margin-bottom:8px;">
            <b style="color:{conf_color};font-size:1.1rem;">🎯 Confluence: {conf.get('emoji', '➖')} {conf.get('label', '-')}</b>
            <span style="color:#475569;"> — {conf.get('desc', '')}</span><br>
            <span style="font-size:0.85rem;color:#64748b;">Macro (4h/12h): <b>{conf.get('macro_score', 0):g}/100</b> · Micro (30m/1h): <b>{conf.get('micro_score', 0):g}/100</b> · Best TF: <b>{multi.get('best_tf', '-')}</b></span>
        </div>
        """, unsafe_allow_html=True)

        # --- Multi-timeframe summary matrix ---
        st.subheader("📊 Matriks Multi-Timeframe")
        mtf_rows = []
        for tf in PREPUMP_TF_ORDER:
            r = tfr.get(tf)
            if not r:
                continue
            m = r.get("metrics", {})
            tier = r.get("tier", "neutral")
            mtf_rows.append({
                "Timeframe": tf,
                "Role": r.get("tf_role", "-"),
                "Score (0-100)": r.get("score", 0),
                "Tier": f"{PREPUMP_TIER_BADGES.get(tier, '❓')} {tier.upper()}",
                "Confluence": f"{conf.get('emoji', '➖')} {conf.get('label', '-')}",
                "Compression %": f"{r.get('compression_pct', 0):.1f}%",
                "Buy/Sell Ratio": f"{m.get('ratio', 0):.2f}×",
                "Net Flow SOL": f"{m.get('net_sol', 0):+.2f}",
                "Pure Accum %": f"{m.get('pct_pure', 0)*100:.0f}%",
                "Smart Wallets": m.get("smart_count", 0),
            })
        import pandas as pd
        st.dataframe(pd.DataFrame(mtf_rows), use_container_width=True, hide_index=True)

        # --- Per-timeframe detail tabs ---
        st.subheader("🧱 Detail per Timeframe")
        tabs = st.tabs([f"{tf} · {tfr[tf].get('score', 0):g}/100 {PREPUMP_TIER_BADGES.get(tfr[tf].get('tier'), '❓')}"
                        if tf in tfr else tf for tf in PREPUMP_TF_ORDER])
        for tab, tf in zip(tabs, PREPUMP_TF_ORDER):
            r = tfr.get(tf)
            if not r:
                continue
            with tab:
                m = r.get("metrics", {})
                p = r.get("pillars", {})
                rs = r.get("reasons", {})
                tier = r.get("tier", "neutral")
                tcolor = _TIER_COLORS.get(tier, "#94a3b8")
                st.markdown(
                    f"<b style='color:{tcolor}'>{PREPUMP_TIER_BADGES.get(tier, '❓')} {tier.upper()}</b> — "
                    f"{r.get('tf_role', '')} · window {r.get('window_min', 0)}m",
                    unsafe_allow_html=True)
                st.caption(f"Status: {r.get('stage', '-')}")
                if r.get("blocked"):
                    st.error(f"🚫 Blocked: {r.get('block_reason', '')}")
                pcols = st.columns(4)
                for idx, (label, key, icon) in enumerate(_PILLARS):
                    with pcols[idx]:
                        st.metric(label=f"{icon} {label}",
                                  value=f"{float(p.get(key, 0)):.0f}/25",
                                  help=rs.get(key, ""))
                sub_m = m.get("sub_window_min", 0)
                term_m = m.get("terminal_min", 0)
                mc1, mc2 = st.columns(2)
                mc1.write(f"📉 **Compression:** `{r.get('compression_pct', 0):.1f}%` (vol {sub_m}m `{m.get('vol_sub_window', 0):.2f}` vs baseline/jam `{m.get('baseline_vol_1h', 0):.2f}` SOL)")
                mc1.write(f"⚖️ **Avg Buy/Sell:** `{m.get('avg_buy', 0):.2f}` / `{m.get('avg_sell', 0):.2f}` SOL (`{m.get('ratio', 0):.2f}×`) dari `{m.get('buy_count', 0)}` buys (min `{m.get('min_buy', 0)}`)")
                mc1.write(f"💥 **Large Dump ≥{m.get('large_dump_sol', 0):g} SOL:** `{'Ya ⚠️' if m.get('whale_dumper') else 'Tidak ✅'}`")
                mc2.write(f"💰 **Net Flow:** sub-{sub_m}m `{m.get('net_sub_sol', 0):+.2f}` / window-{r.get('window_min', 0)}m `{m.get('net_sol', 0):+.2f}` SOL")
                mc2.write(f"💎 **Pure Accum:** `{m.get('pct_pure', 0)*100:.0f}%` ({m.get('n_pure', 0)} wallet) · target serapan `{m.get('absorp_target_sol', 0):g}` SOL (cap-tier ×{m.get('absorp_mult', 1):g})")
                mc2.write(f"🔥 **Smart 0-sell:** `{m.get('smart_count', 0)}` · **Terminals ({term_m}m):** `{', '.join(m.get('active_terminals', [])) or '—'}`")
                with st.expander("🔍 Raw result (JSON)", expanded=False):
                    st.json({k: v for k, v in r.items()
                             if k in ["tf", "score", "tier", "tf_role", "stage",
                                      "compression_pct", "pillars", "metrics",
                                      "reasons", "smart_tags_found"]})

        # --- Export Markdown report ---
        st.subheader("📄 Export Report")
        md_report = _build_markdown(ca_input.strip(), multi)
        st.download_button("⬇️ Download Markdown Report (Multi-TF)",
                           data=md_report,
                           file_name=f"prepump_multi_tf_{ca_input.strip()[:8]}.md",
                           mime="text/markdown")
        with st.expander("Preview Markdown", expanded=False):
            st.code(md_report, language="markdown")

        st.info("💡 Tips: kalau semua score 0 dan swap kosong → CVD mungkin stale (>1 jam). "
                "Cek `cvd.json` atau tunggu cron jam :20.")
else:
    st.info("Masukkan CA token, lalu klik **Cek Prepump**.")
    st.markdown("""
    **Contoh CA yang sudah ada di repo:**
    - `AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump` (looong)

    **Timeframes:**
    - `30m` Micro Ignition / Timing — trigger entry jangka pendek
    - `1h` Hourly Setup / Base — konfirmasi setup intraday
    - `4h` Swing Channel / Wyckoff Accumulation — struktur swing
    - `12h` Macro Cycle Base — konteks macro cycle

    Lihat `DISABLED.md` jika mencari halaman lain yang dinonaktifkan.
    """)
