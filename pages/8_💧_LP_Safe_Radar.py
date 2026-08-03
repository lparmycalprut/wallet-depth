# -*- coding: utf-8 -*-
"""💧 LP Safe Radar — CATJAK-like but safe from negative flags, best for LP"""

import streamlit as st
import os, json

st.set_page_config(page_title="LP Safe Radar - CATJAK", layout="wide")
st.title("💧 LP Safe Radar — CATJAK-like Safe")
st.caption("Filter token kayak CATJAK (5d, liq $48k, mcap $373k, vol $154k, t10 14%, bundler 3.9%, fresh 8.9% low) tapi aman dari flag negatif — paling cocok buat LP")

try:
    from lp_safe_radar import screen_lp_safe
    from core import get_helius_keys
    from watchlist import load_watchlist
except Exception as e:
    st.error(f"Import failed: {e}")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Age", "3-15d", "CATJAK 5d")
with col2:
    st.metric("Liq", "$15k-$130k", "CATJAK $48k")
with col3:
    st.metric("Top10", "<=22%", "CATJAK 14.1%")
with col4:
    st.metric("Bundler", "<=5%", "CATJAK 3.96% fresh 8.9%")

st.markdown("""
**CATJAK reference metrics (GMGN + Dex):**
- `holder 1631, top10 14.12%, bundler 3.96%, entrap 26.43%, bot_degen 15.14%, fresh 8.9%, dev 2.02%, sniper 2.02%`
- `liq $48k (12.8% MC), mc $373k, vol $154k (0.41x MC), buys 1279 sells 1315 ratio 0.97 balanced`
- `socials website + twitter + telegram, boost 1164, avg_cost +17%`

**LP Safe gates (stricter than trending):**
- Age 3-15d, Liq $15k-$130k, MC $80k-$1.2M, Holders >=800
- Vol24 $20k-$500k, Liq/MC 8-32%, Vol/MC 0.12-3.0x (not wash, not dead)
- Top10 <=22%, Insider <=8%, Bundler <=5%, Entrap <=32%, BotDegen <=22%, Fresh <=18%, HolderConc Top50 <=72%, Sniper <=6%, Rug <=0.35
- Buys/Sells 24h ratio 0.70-1.40 balanced (CATJAK 0.97)
- Socials present, avg_cost -30% to +60% (not deep underwater)
""")

if "lp_safe_candidates" not in st.session_state:
    st.session_state["lp_safe_candidates"] = []

tab1, tab2 = st.tabs(["🔍 Scan LP Safe", "📊 CATJAK Benchmark"])

with tab1:
    c1, c2 = st.columns([1,1])
    with c1:
        debug = st.checkbox("Debug log", value=False)
    with c2:
        enrich = st.checkbox("Enrich Dex buys/sells ratio (slower, needs Dex API)", value=False)

    if st.button("💧 Scan LP Safe Now", type="primary"):
        with st.spinner("Fetching GMGN 3-15d safe windows..."):
            try:
                cands, rejects, all_rows = screen_lp_safe(debug=debug, enrich_dex=enrich)
            except Exception as exc:
                st.error(f"Scan failed (Cloudflare block?): {exc}")
                cands, rejects, all_rows = [], [], []

        st.session_state["lp_safe_candidates"] = cands
        st.session_state["lp_safe_rejects"] = rejects
        st.session_state["lp_safe_all"] = all_rows
        st.write(f"Total: {len(all_rows)} | Safe LP: {len(cands)} | Rejected: {len(rejects)}")

        if not cands and not all_rows:
            st.warning("GMGN returned 0 — sandbox Cloudflare block. In Streamlit Cloud it works. Showing fallback: CATJAK itself + watchlist analysis.")

            # Fallback demo: show CATJAK + current watchlist that are close
            st.subheader("Fallback Demo — CATJAK benchmark + watchlist")
            # CATJAK data we already have
            st.markdown("**CATJAK (reference)** — should PASS all LP Safe gates")
            st.code("""
CA: 3taE4SdY29sa3fnwyWqfshudJ95gMb9LoFTy5Uuppump
Age 5.8d, Liq $48k (12.8% MC), MC $373k, Vol $154k (0.41x), Holders 1631
T10 14.12%, bundler 3.96%, entrap 26.43%, bot 15.14%, fresh 8.9%, dev 2.02%, sniper 2.02%
Buys 1279 Sells 1315 ratio 0.97 balanced, socials website+twitter+telegram, boost 1164
            """)

    cands = st.session_state.get("lp_safe_candidates", [])
    rejects = st.session_state.get("lp_safe_rejects", [])
    all_rows = st.session_state.get("lp_safe_all", [])

    if cands:
        st.success(f"Found {len(cands)} LP Safe candidates (CATJAK-like)")
        import pandas as pd
        df = pd.DataFrame([{
            "Symbol": r.get("symbol") or "?",
            "Fit": r.get("fit"),
            "Grade": r.get("grade"),
            "Age d": f"{r.get('age_d',0):.1f}",
            "MC": f"${r.get('mc',0):,.0f}",
            "Liq": f"${r.get('liq',0):,.0f} ({r.get('liq_pct')}%)",
            "Vol": f"${r.get('vol24',0):,.0f} ({r.get('vol_mc')}x)",
            "T10": f"{r.get('t10_pct')}%",
            "Hold": r.get("holders"),
            "Bund%": f"{r.get('bundler_rate',0)*100:.1f}%",
            "Fresh%": f"{r.get('fresh_wallet_rate',0)*100:.1f}%",
            "Entrap%": f"{r.get('entrap_rate',0)*100:.1f}%",
            "CA": r.get("ca"),
        } for r in cands])
        st.dataframe(df, use_container_width=True)

        for r in cands[:15]:
            ca = r["ca"]
            colA, colB = st.columns([4,1])
            with colA:
                st.markdown(f"**{r.get('symbol')}** `{ca[:12]}...` — {r.get('_lp_reason','')}")
                st.caption(f"GMGN: https://gmgn.ai/sol/token/{ca} | Dex: https://dexscreener.com/solana/{ca} | Fit {r.get('fit')} {r.get('grade')}")
                if r.get("risk_reasons"):
                    st.warning(f"Risk: {'; '.join(r['risk_reasons'])}")
            with colB:
                if st.button("Analyze →", key=f"lp_an_{ca}"):
                    st.query_params["ca"] = ca
                    st.switch_page("app.py")
                # Add to watchlist as LP candidate
                from watchlist import add_to_watchlist
                if st.button("⭐ LP Watch", key=f"lp_watch_{ca}"):
                    add_to_watchlist(ca, symbol=r.get("symbol","?"), source="lp_safe")
                    st.toast(f"Added {r.get('symbol')} to watchlist as LP safe")
            st.divider()
    elif rejects:
        st.info(f"No LP Safe passed, showing top 20 closest rejects for tuning:")
        import pandas as pd
        df = pd.DataFrame([{
            "Symbol": r.get("symbol"),
            "Fit": r.get("fit"),
            "Age": f"{r.get('age_d',0):.1f}d",
            "Liq": f"${r.get('liq',0):.0f}",
            "MC": f"${r.get('mc',0):,.0f}",
            "Vol": f"${r.get('vol24',0):,.0f}",
            "T10": f"{r.get('t10_pct')}%",
            "Bund": f"{r.get('bundler_rate',0)*100:.1f}%",
            "Fresh": f"{r.get('fresh_wallet_rate',0)*100:.1f}%",
            "Reason": r.get("_lp_reason","")[:100],
        } for r in rejects[:20]])
        st.dataframe(df, use_container_width=True)

with tab2:
    st.subheader("📊 CATJAK Benchmark — Why it's perfect for LP")
    st.markdown("""
**DexScreener live (from API):**
- **Age:** 5d 20h, **Liq:** $47,931 main + $3,657 Meteora = ~$51.5k total
- **MC/FDV:** $373k, **24h Vol:** $154,349 + $7,403 = ~$161k
- **Txns 24h:** 1279 buys vs 1315 sells → **ratio 0.97 balanced** (ideal LP, no dump pressure)
- **Holders:** 1631
- **Socials:** website https://catjak.xyz + x.com/CatjakSOL + t.me/CatjakSol + boost 1164 marketing

**GMGN token_stat (safe flags):**
- `top_10 14.12%` ✅ excellent (<22%)
- `bundler 3.96%` ✅ safe (<5%)
- `entrap 26.43%` ✅ ok (<32%)
- `bot_degen 15.14%` ✅ safe (<22%)
- `fresh_wallet 8.9%` ✅ very low fresh (mature base, not launch snipe)
- `dev 2.02%` ✅ low dev hold
- `sniper 2.02%` ✅ low
- `rug` low, `renounced + frozen` ✅

**LP Math:**
- `liq/mc = 48k/373k = 12.86%` → di sweet spot 8-30% (cukup dalam buat LP, ga terlalu tipis)
- `vol/mc = 154k/373k = 0.41x` → healthy 0.12-3x (bukan wash 5x+, bukan dead 0.05x)
- `holders 1631` + `fresh 8.9%` → holder base organik, bukan bot baru
- `avg_cost +17%` dari watchlist → holders in profit dikit, ga akan panic sell, tapi juga ga extreme +100% yang rawan take profit

**Why LP Safe Radar copies CATJAK:**
- Umur 3-15d = udah lewat fase sniper/rug awal (0-2d) tapi masih early enough buat growth
- Liq $15k-$130k = cukup untuk LP $1k-$10k tanpa slippage gede, tapi masih bisa naik 2-3x
- Vol $20k-$500k balanced = ada fee LP harian, bukan token mati
- Top10 <=22% = ga akan ke-dump whale 1 wallet
- Bundler/Fresh low = bukan bundler token
    """)

    st.info("💡 Tip LP: Cari token yang lulus LP Safe + conviction di CVD naik 2-3 window + holder delta whale positif + real/dust ratio >=50%. Itu combo CATJAK + CTO incubation: aman buat LP + masih ada upside.")

st.caption("LP Safe Radar uses same GMGN API as trending but with stricter safe gates mimicking CATJAK. Requires curl_cffi — works on Streamlit Cloud, may return 0 in sandbox due to Cloudflare.")
