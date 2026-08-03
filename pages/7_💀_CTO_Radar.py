# -*- coding: utf-8 -*-
"""CTO Incubation Radar — Streamlit page (2d min, deep scan, auto-watchlist, telegram)

Stage 1: Incubation scan 2d-60d death valley via GMGN trending_rank (5 windows)
Stage 2: Deep scan via Helius (holders, concentration, real/dust, health) + CTO flag + conviction flip
Stage 3: Auto-watchlist + Telegram for cto_flag=1 + low liq
"""
import streamlit as st
import os, json, time

st.set_page_config(page_title="CTO Incubation Radar", layout="wide")
st.title("💀 CTO Incubation Radar — 2d min | Deep + Auto")
st.caption("Scan 2-60 hari dead token kayak assface day 3, punch, bountywork, ansem, grail, chance + deep scan Helius + auto-watchlist + Telegram")

try:
    from incubation_radar import screen_incubation
    from cto_deep_scan import deep_scan_token, auto_watchlist_and_telegram
    from core import get_helius_keys
    from watchlist import load_watchlist
except Exception as e:
    st.error(f"Import failed: {e}")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Min Age", "2 days", "assface day 3")
with col2:
    st.metric("Max Age", "60 days", "incubation")
with col3:
    st.metric("Liq Target", "$3k-40k", "death valley")
with col4:
    helius_keys = tuple(get_helius_keys())
    st.metric("Helius Keys", f"{len(helius_keys)}", "for deep scan" if helius_keys else "no key = soft")

st.markdown("""
**Pola 7 CTO:**
- Death Valley: 5M vol <$100, txns <10, 24h <$500 dulu
- Stealth cluster: 5-10 fresh wallets 1-3 SOL same funder (PUNCH 7.75% in 3 wallets)
- Float sink: 65% single whale (ANSEM) or cluster
- Trigger: Dexscreener `community claimed ownership` on pump date
- Conviction: 30% -> 50%+ rising, net_pure positive, persist bonus 3+
""")

# Session state for candidates
if "cto_candidates" not in st.session_state:
    st.session_state["cto_candidates"] = []
if "cto_deep_results" not in st.session_state:
    st.session_state["cto_deep_results"] = []

tab1, tab2, tab3 = st.tabs(["🔍 Stage 1: Incubation Scan", "🔬 Stage 2: Deep Scan Helius", "⭐ Stage 3: Auto Watchlist + Telegram"])

with tab1:
    if st.button("🔍 Scan Now (GMGN 2d-60d)", type="primary", key="scan_inc"):
        with st.spinner("Fetching 5 windows..."):
            try:
                candidates, rejects, all_rows = screen_incubation(debug=False)
            except Exception as exc:
                st.error(f"GMGN failed: {exc}")
                candidates, rejects, all_rows = [], [], []
        st.session_state["cto_candidates"] = candidates
        st.write(f"Total: {len(all_rows)} | Candidates: {len(candidates)} | Rejected: {len(rejects)}")
        if not candidates and not all_rows:
            st.warning("GMGN 0 — Cloudflare block in sandbox, but works on Streamlit Cloud. Using fallback watchlist for demo deep scan.")
            wl = load_watchlist()
            # fake candidates from watchlist that are low liq
            fallback = []
            hist_path = os.path.join(os.path.dirname(__file__), "..", "history.json")
            try:
                with open(hist_path) as f:
                    hist = json.load(f)
                for ca, meta in wl.items():
                    if ca in hist:
                        last = hist[ca][sorted(hist[ca].keys())[-1]]
                        if 3000 <= (last.get("marketcap",0)*last.get("liq_pct_mc",0)/100 if last.get("liq_pct_mc") else 0) <= 50000:
                            fallback.append({"ca": ca, "symbol": meta.get("symbol","?"), "mc": last.get("marketcap",0), "liq": last.get("marketcap",0)*last.get("liq_pct_mc",0)/100, "age_d": 6, "fit": 60, "grade":"OK", "_incubation_reason":"fallback watchlist", "vol24": last.get("vol24",0)})
            except Exception as e:
                st.error(f"fallback error {e}")
            if fallback:
                st.session_state["cto_candidates"] = fallback
                candidates = fallback

    cands = st.session_state.get("cto_candidates", [])
    if cands:
        st.success(f"Found {len(cands)} incubation candidates")
        import pandas as pd
        df = pd.DataFrame([{
            "Symbol": r.get("symbol") or "?",
            "Fit": r.get("fit"),
            "Age d": r.get("age_d"),
            "MC": f"${r.get('mc', r.get('marketcap',0)):,.0f}",
            "Liq": f"${r.get('liq',0):,.0f}",
            "Vol24": f"${r.get('vol24',0):,.0f}",
            "T10": f"{r.get('t10_pct','?')}%",
            "Reason": r.get("_incubation_reason","")[:80],
            "CA": r.get("ca"),
        } for r in cands])
        st.dataframe(df, use_container_width=True)
        for r in cands[:20]:
            ca = r["ca"]
            c1, c2 = st.columns([4,1])
            with c1:
                st.markdown(f"**{r.get('symbol','?')}** `{ca}` - {r.get('_incubation_reason','')}")
                st.caption(f"GMGN: https://gmgn.ai/sol/token/{ca} | Dex: https://dexscreener.com/solana/{ca}")
            with c2:
                if st.button("Deep Scan", key=f"deep_{ca}"):
                    st.session_state["cto_deep_single"] = ca
                    st.rerun()

with tab2:
    st.markdown("**Stage 2: Deep Scan** — holders, supply, concentration, real/dust, health, CTO flag via DexScreener, conviction flip")
    
    single = st.session_state.get("cto_deep_single")
    if single:
        st.info(f"Deep scanning single CA: {single}")
        cas_to_scan = [single]
    else:
        cas_to_scan = [r["ca"] for r in st.session_state.get("cto_candidates", [])]
    
    if not cas_to_scan:
        st.warning("No candidates from Stage 1 — run Stage 1 first or use watchlist as fallback. For demo, scanning watchlist.")
        wl = load_watchlist()
        cas_to_scan = list(wl.keys())[:10]

    colA, colB = st.columns([1,1])
    with colA:
        do_cluster = st.checkbox("Enable cluster scan (needs Helius, slow)", value=False)
    with colB:
        limit = st.slider("Limit deep scan", 1, 30, min(10, len(cas_to_scan) or 4))

    if st.button("🔬 Run Deep Scan", type="primary", key="run_deep"):
        results = []
        prog = st.progress(0.0, text="Deep scanning...")
        helius_keys = tuple(get_helius_keys())
        for i, ca in enumerate(cas_to_scan[:limit]):
            prog.progress((i+1)/len(cas_to_scan[:limit]), text=f"Scanning {i+1}/{len(cas_to_scan[:limit])} {ca[:8]}...")
            try:
                res = deep_scan_token(ca, do_cluster=do_cluster, helius_keys=helius_keys)
                results.append(res)
            except Exception as e:
                st.error(f"{ca} failed: {e}")
        prog.empty()
        st.session_state["cto_deep_results"] = results

        passing = [r for r in results if r.get("pass")]
        st.success(f"Scanned {len(results)} | Passing {len(passing)}")

        for r in results:
            status = "✅ PASS" if r.get("pass") else "❌ FAIL"
            with st.expander(f"{status} {r.get('symbol','?')} {r['ca'][:12]}... MC ${r.get('market',{}).get('marketcap',0):,.0f} Liq ${r.get('market',{}).get('liquidity_usd',0):,.0f}"):
                st.write(f"**CTO:** {r.get('cto')} {r.get('cto_detail')}")
                st.write(f"**Conc Top10:** {r.get('concentration',{}).get('top10',0):.1f}%")
                st.write(f"**Health:** {r.get('health',{}).get('score',0)}")
                st.write(f"**Conviction:** {r.get('conviction',{}).get('reason','')}")
                st.write(f"**Reasons:** {' | '.join(r.get('reasons',[]))}")
                st.write(f"Links: [Dex](https://dexscreener.com/solana/{r['ca']}) [GMGN](https://gmgn.ai/sol/token/{r['ca']})")
                if r.get("pass"):
                    if st.button("Add to Watchlist + Telegram", key=f"add_{r['ca']}"):
                        from watchlist import add_to_watchlist
                        ok = add_to_watchlist(r['ca'], symbol=r.get('symbol','?'), source="cto_radar")
                        if ok:
                            st.toast(f"Added {r.get('symbol')}")
                        # telegram
                        try:
                            from breakout_guard import send_telegram
                            msg = f"💀 CTO Radar PASS: ${r.get('symbol')} {r['ca'][:8]} MC ${r.get('market',{}).get('marketcap',0):,.0f} Liq ${r.get('market',{}).get('liquidity_usd',0):,.0f} CTO {r.get('cto')} {r.get('cto_detail')} https://dexscreener.com/solana/{r['ca']}"
                            send_telegram(msg)
                            st.success("Telegram sent")
                        except Exception as e:
                            st.error(f"Telegram failed: {e}")

    # show previous deep results if exist
    deep_res = st.session_state.get("cto_deep_results", [])
    if deep_res:
        import pandas as pd
        df2 = pd.DataFrame([{
            "Symbol": r.get("symbol"),
            "Pass": r.get("pass"),
            "MC": r.get("market",{}).get("marketcap",0),
            "Liq": r.get("market",{}).get("liquidity_usd",0),
            "Top10": r.get("concentration",{}).get("top10",0),
            "Health": r.get("health",{}).get("score",0),
            "CTO": r.get("cto"),
            "Conv": r.get("conviction",{}).get("conv",0),
            "CA": r["ca"],
        } for r in deep_res])
        st.dataframe(df2, use_container_width=True)

with tab3:
    st.markdown("**Stage 3: Auto Watchlist + Telegram** — Otomatis add token yang lolos deep scan dan punya `cto_flag=1` / CTO claim + liq tipis")
    deep_res = st.session_state.get("cto_deep_results", [])
    if not deep_res:
        st.warning("Run Stage 2 deep scan first")
    else:
        passing = [r for r in deep_res if r.get("pass")]
        st.write(f"Passing candidates: {len(passing)}")
        if st.button("⭐ Auto Add All Passing to Watchlist + Telegram", type="primary", key="auto_add"):
            added = auto_watchlist_and_telegram(passing, do_telegram=True)
            st.success(f"Added {len(added)} tokens to watchlist")
            for r in added:
                st.write(f"✅ {r.get('symbol')} {r['ca']}")

st.markdown("---")
st.caption("Workflow: .github/workflows/cto-radar.yml runs hourly (15 * * * *) — incubation scan + deep scan + auto watchlist + Telegram. Set HELIUS_API_KEY and TELEGRAM_* in GitHub Secrets.")
