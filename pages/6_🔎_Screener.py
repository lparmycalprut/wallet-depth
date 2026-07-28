# -*- coding: utf-8 -*-
"""Page: GMGN trending screener scored by our accumulation criteria."""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gmgn_screener import screen
from watchlist import load_watchlist, add_to_watchlist

st.set_page_config(page_title="Screener", page_icon="🔎",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.72rem !important;}
</style>""", unsafe_allow_html=True)

st.title("🔎 Screener — GMGN trending, scored our way")
st.caption("Pulls GMGN's trending list (pre-filtered: age 2-30d, migrated, "
           "renounced+frozen, no wash trading, liq ≥$30K, MC ≥$100K, "
           "holders ≥1000, vol ≥$100K, insiders/bundlers ≤15%) and scores "
           "each token for ACCUMULATION fit: flat price + low concentration "
           "+ healthy liquidity + smart money + low rug risk.")

scan = st.button("🔎 Scan trending now", type="primary",
                 use_container_width=True)
if scan or "screener_rows" in st.session_state:
    if scan or "screener_rows" not in st.session_state:
        with st.spinner("Fetching GMGN trending…"):
            st.session_state["screener_rows"] = screen()
    rows = st.session_state.get("screener_rows") or []
    if not rows:
        st.warning("GMGN returned nothing (Cloudflare block or empty "
                   "filter). Try again in a minute.")
        st.stop()

    wl = load_watchlist()
    st.markdown(f"**{len(rows)} tokens** · sorted by accumulation-fit score")
    hdr = st.columns([0.6, 1.6, 1.2, 1.2, 1.0, 1.0, 0.9, 2.4, 1.4])
    for c, t in zip(hdr, ["Fit", "Token", "MC", "Liq", "T10", "🧠 Smart",
                          "24h", "Notes", ""]):
        c.markdown(f"**{t}**")
    for r in rows:
        fit = r["fit"]
        col = "#22c55e" if fit >= 80 else ("#facc15" if fit >= 60
                                           else "#64748b")
        in_wl = r["ca"] in wl
        cc = st.columns([0.6, 1.6, 1.2, 1.2, 1.0, 1.0, 0.9, 2.4, 1.4])
        cc[0].markdown(f"<span style='color:{col};font-weight:800;"
                       f"font-size:1.1rem'>{fit}</span>",
                       unsafe_allow_html=True)
        cc[1].markdown(f"**{r['symbol']}**  \n<span style='font-size:0.65rem;"
                       f"opacity:0.6'>{r['age_d']}d old</span>",
                       unsafe_allow_html=True)
        cc[2].write(f"${r['mc']:,.0f}")
        cc[3].write(f"{r['liq_pct']}% MC")
        cc[4].write(f"{r['t10_pct']}%")
        cc[5].write(str(r["smart"]))
        cc[6].write(f"{r['chg24']:+.0f}%")
        cc[7].caption(r["notes"] or "—")
        with cc[8]:
            st.link_button("Analyze →", f"/CVD?ca={r['ca']}",
                           use_container_width=True)
            if not in_wl:
                if st.button("⭐ watch", key=f"wl_{r['ca']}",
                             use_container_width=True):
                    add_to_watchlist(r["ca"], symbol=r["symbol"] or "?")
                    st.rerun()
            else:
                st.caption("⭐ watched")
    st.caption("Fit score: flat price (25) + low T10 (20) + liq health (15) "
               "+ smart money (15) + rug score (15) + sane vol/MC (10). "
               "≥80 = prime accumulation candidates — already-pumped tokens "
               "score low on purpose. Source: GMGN internal API "
               "(unofficial, may break anytime). Always verify with a full "
               "Analyze before acting.")
else:
    st.info("Click **Scan trending now** to pull and score the current "
            "GMGN trending list.")
