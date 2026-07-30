# -*- coding: utf-8 -*-
"""Page: Compare multiple tokens side-by-side."""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import (concentration, get_helius_keys, get_holders, get_market,
                  get_rugcheck, get_supply, health_score, load_config,
                  score_color, score_label)

st.set_page_config(page_title="Compare Tokens", page_icon="⚖️",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.72rem !important;}
</style>""", unsafe_allow_html=True)

st.title("⚖️ Compare Tokens")
st.caption("Compare 2-3 tokens side-by-side: score, holders, dust/real, "
           "concentration, liquidity, buy/sell.")

CONFIG = load_config()
helius_keys = tuple(get_helius_keys(config=CONFIG))
dust_limit = float(CONFIG.get("dust_limit_usd", 10))

c1, c2, c3 = st.columns(3)
ca1 = c1.text_input("Token 1 CA", placeholder="Contract address...").strip()
ca2 = c2.text_input("Token 2 CA", placeholder="Contract address...").strip()
ca3 = c3.text_input("Token 3 CA (optional)", placeholder="...").strip()
cas = [c for c in (ca1, ca2, ca3) if c]

if not st.button("⚖️ Compare", type="primary", use_container_width=True):
    st.stop()
if len(cas) < 2:
    st.warning("Enter at least 2 CAs to compare.")
    st.stop()
if not helius_keys:
    st.error("Helius API key missing (config.json / secrets).")
    st.stop()


@st.cache_data(ttl=180, show_spinner=False)
def analyze(ca: str, api_keys: tuple) -> dict:
    m = get_market(ca)
    if not m:
        return {"error": "not found on DexScreener"}
    supply, dec = get_supply(api_keys, ca)
    hd = get_holders(api_keys, ca)
    hd["ui_amount"] = hd["raw_amount"] / (10 ** dec)
    hd = hd[hd["ui_amount"] > 0]
    lp = set(m.get("pair_addresses") or [])
    hd = hd[~hd["owner"].isin(lp)]
    price = m["price_usd"]
    mc = m["marketcap"]
    hd["usd_value"] = hd["ui_amount"] * price
    dust = hd[hd["usd_value"] < dust_limit]
    real = hd[hd["usd_value"] >= dust_limit]
    ratio_pct = (len(real) / len(dust) * 100) if len(dust) else 100.0
    real_mc = real["usd_value"].sum() / mc * 100 if mc else 0
    conc = concentration(hd, supply)
    rug = get_rugcheck(ca)
    liq_pct = m["liquidity_usd"] / mc * 100 if mc else 0
    tx = (m.get("txns") or {}).get("h24") or {}
    buys, sells = int(tx.get("buys") or 0), int(tx.get("sells") or 0)
    score, _ = health_score(
        ratio_pct=ratio_pct, real_mc_pct=real_mc, top10_pct=conc["top10"],
        liq_pct_mc=liq_pct, lp_locked_pct=rug.get("lp_locked_pct"),
        mint_auth=rug.get("mint_authority"),
        freeze_auth=rug.get("freeze_authority"),
        holder_delta=None, max_cluster_pct=None, fresh_pct=None)
    return {
        "name": f"{m['name']} (${m['symbol']})", "score": score,
        "price": price, "mc": mc, "holders": len(hd),
        "dust": len(dust), "real": len(real), "ratio_pct": ratio_pct,
        "real_mc": real_mc, "top10": conc["top10"], "liq_pct": liq_pct,
        "liq_usd": m["liquidity_usd"],
        "lp_locked": rug.get("lp_locked_pct"),
        "buys": buys, "sells": sells,
        "bs": buys / sells if sells else float("inf"),
        "vol24": float((m.get("volume") or {}).get("h24") or 0),
        "mint_auth": bool(rug.get("mint_authority")),
        "freeze_auth": bool(rug.get("freeze_authority")),
        "rugged": bool(rug.get("rugged")),
        "image": m.get("image"),
    }


results = {}
prog = st.progress(0.0, text="Analyzing...")
for i, ca in enumerate(cas):
    prog.progress(i / len(cas), text=f"Analyzing {ca[:10]}… ({i+1}/{len(cas)})")
    try:
        results[ca] = analyze(ca, helius_keys)
    except Exception as e:
        results[ca] = {"error": str(e)[:120]}
prog.empty()

ok = {ca: r for ca, r in results.items() if "error" not in r}
for ca, r in results.items():
    if "error" in r:
        st.error(f"`{ca[:12]}…`: {r['error']}")
if len(ok) < 2:
    st.stop()

cols = st.columns(len(ok))
best_ca = max(ok, key=lambda c: ok[c]["score"])
for col, (ca, r) in zip(cols, ok.items()):
    sc = r["score"]
    color = score_color(sc)
    crown = " 👑" if ca == best_ca else ""
    with col:
        st.markdown(
            f"""<div style="border:2px solid {color};border-radius:12px;
            padding:10px;text-align:center;">
            <div style="font-size:0.9rem;font-weight:700;">{r['name']}{crown}</div>
            <div style="font-size:2.2rem;font-weight:800;color:{color};">{sc}</div>
            <div style="font-size:0.75rem;color:{color};font-weight:700;">
            {score_label(sc)}</div>
            <div style="font-size:0.65rem;opacity:0.6;">`{ca[:14]}…`</div>
            </div>""", unsafe_allow_html=True)

st.markdown("")


def fmt_row(label, fn):
    row = {"Metric": label}
    for ca, r in ok.items():
        row[r["name"]] = fn(r)
    return row


rows = [
    fmt_row("Health Score", lambda r: f"{r['score']}/100"),
    fmt_row("Marketcap", lambda r: f"${r['mc']:,.0f}"),
    fmt_row("Price", lambda r: f"${r['price']:.10f}".rstrip("0")),
    fmt_row("Total Holders", lambda r: f"{r['holders']:,}"),
    fmt_row("Real Holders", lambda r: f"{r['real']:,} ({r['real_mc']:.1f}% MC)"),
    fmt_row("Dust Holders", lambda r: f"{r['dust']:,}"),
    fmt_row("Real/Dust Ratio", lambda r: f"{r['ratio_pct']:.1f}%"),
    fmt_row("Top-10 % Supply", lambda r: f"{r['top10']:.1f}%"),
    fmt_row("Liquidity", lambda r: f"${r['liq_usd']:,.0f} ({r['liq_pct']:.1f}% MC)"),
    fmt_row("LP Locked", lambda r: (f"{r['lp_locked']:.0f}%"
                                    if r['lp_locked'] is not None else "n/a")),
    fmt_row("Buys/Sells 24h", lambda r: f"{r['buys']:,} / {r['sells']:,} "
            f"({r['bs']:.2f})"),
    fmt_row("Volume 24h", lambda r: f"${r['vol24']:,.0f}"),
    fmt_row("Mint Authority", lambda r: "⚠️ active" if r["mint_auth"] else "✅ revoked"),
    fmt_row("Freeze Authority", lambda r: "⚠️ active" if r["freeze_auth"] else "✅ revoked"),
    fmt_row("RugCheck Rugged", lambda r: "🚨 YES" if r["rugged"] else "✅ no"),
]
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
             height=560)
st.caption("👑 = highest score. Comparison skips the cluster scan (too slow "
           "for multiple tokens) — open the main dashboard for a full "
           "per-token analysis.")
