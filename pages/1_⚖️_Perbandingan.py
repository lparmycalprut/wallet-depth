# -*- coding: utf-8 -*-
"""Page: Perbandingan beberapa token side-by-side."""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import (concentration, get_holders, get_market, get_rugcheck,
                  get_supply, health_score, load_config, score_color,
                  score_label)

st.set_page_config(page_title="Perbandingan Token", page_icon="⚖️",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.72rem !important;}
</style>""", unsafe_allow_html=True)

st.title("⚖️ Perbandingan Token")
st.caption("Bandingkan 2-3 token side-by-side: skor, holder, dust/real, "
           "konsentrasi, likuiditas, buy/sell.")

CONFIG = load_config()
helius_key = CONFIG.get("helius_api_key") or ""
dust_limit = float(CONFIG.get("dust_limit_usd", 10))

c1, c2, c3 = st.columns(3)
ca1 = c1.text_input("CA Token 1", placeholder="Contract address...").strip()
ca2 = c2.text_input("CA Token 2", placeholder="Contract address...").strip()
ca3 = c3.text_input("CA Token 3 (opsional)", placeholder="...").strip()
cas = [c for c in (ca1, ca2, ca3) if c]

if not st.button("⚖️ Bandingkan", type="primary", use_container_width=True):
    st.stop()
if len(cas) < 2:
    st.warning("Isi minimal 2 CA untuk dibandingkan.")
    st.stop()
if not helius_key:
    st.error("Helius API key belum diisi (config.json / secrets).")
    st.stop()


@st.cache_data(ttl=180, show_spinner=False)
def analyze(ca: str) -> dict:
    m = get_market(ca)
    if not m:
        return {"error": "tidak ditemukan di DexScreener"}
    supply, dec = get_supply(helius_key, ca)
    hd = get_holders(helius_key, ca)
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
prog = st.progress(0.0, text="Menganalisa...")
for i, ca in enumerate(cas):
    prog.progress((i) / len(cas), text=f"Menganalisa {ca[:10]}… "
                  f"({i+1}/{len(cas)})")
    try:
        results[ca] = analyze(ca)
    except Exception as e:
        results[ca] = {"error": str(e)[:120]}
prog.empty()

ok = {ca: r for ca, r in results.items() if "error" not in r}
for ca, r in results.items():
    if "error" in r:
        st.error(f"`{ca[:12]}…`: {r['error']}")
if len(ok) < 2:
    st.stop()

# --- Header kartu skor
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


def fmt_row(label, fn, best=None):
    row = {"Metrik": label}
    vals = {ca: fn(r) for ca, r in ok.items()}
    for ca, r in ok.items():
        row[r["name"]] = vals[ca]
    return row


rows = [
    fmt_row("Skor Kesehatan", lambda r: f"{r['score']}/100"),
    fmt_row("Marketcap", lambda r: f"${r['mc']:,.0f}"),
    fmt_row("Harga", lambda r: f"${r['price']:.10f}".rstrip("0")),
    fmt_row("Total Holder", lambda r: f"{r['holders']:,}"),
    fmt_row("Real Holder", lambda r: f"{r['real']:,} ({r['real_mc']:.1f}% MC)"),
    fmt_row("Dust Holder", lambda r: f"{r['dust']:,}"),
    fmt_row("Rasio Real/Dust", lambda r: f"{r['ratio_pct']:.1f}%"),
    fmt_row("Top-10 % Supply", lambda r: f"{r['top10']:.1f}%"),
    fmt_row("Likuiditas", lambda r: f"${r['liq_usd']:,.0f} ({r['liq_pct']:.1f}% MC)"),
    fmt_row("LP Locked", lambda r: (f"{r['lp_locked']:.0f}%"
                                    if r['lp_locked'] is not None else "n/a")),
    fmt_row("Buy/Sell 24h", lambda r: f"{r['buys']:,} / {r['sells']:,} "
            f"({r['bs']:.2f})"),
    fmt_row("Volume 24h", lambda r: f"${r['vol24']:,.0f}"),
    fmt_row("Mint Authority", lambda r: "⚠️ aktif" if r["mint_auth"] else "✅ dicabut"),
    fmt_row("Freeze Authority", lambda r: "⚠️ aktif" if r["freeze_auth"] else "✅ dicabut"),
    fmt_row("RugCheck Rugged", lambda r: "🚨 YA" if r["rugged"] else "✅ tidak"),
]
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
             height=560)
st.caption("👑 = skor tertinggi. Perbandingan tidak memasukkan cluster scan "
           "(terlalu lama untuk banyak token) — buka dashboard utama untuk "
           "analisa lengkap per token.")
