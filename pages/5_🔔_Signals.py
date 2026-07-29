# -*- coding: utf-8 -*-
"""Page: Signal log — every CVD accumulation/distribution/divergence event
with the exact time it was detected, so you can line it up with the chart."""
import datetime as dtm
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from signals import load_signals

st.set_page_config(page_title="Signals", page_icon="🔔",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.72rem !important;}
</style>""", unsafe_allow_html=True)

st.title("🔔 Signal Log")
st.caption("Every CVD event the tool detects — stealth accumulation, "
           "distribution, price/CVD divergences — recorded with the exact "
           "detection time (WIB & UTC). The hourly cron watches your "
           "watchlist at minute :20 even when you're away; Analyze runs add "
           "signals too. "
           "Use the timestamps to line events up with your chart.")

TYPE_META = {
    "accumulation": ("🟢", "Stealth accumulation", "#22c55e"),
    "distribution": ("🔴", "Distribution to retail", "#ef4444"),
    "bullish_div": ("📈", "Bullish divergence", "#4ade80"),
    "bearish_div": ("📉", "Bearish divergence", "#f87171"),
    "breakout_real": ("🚀", "Breakout (real markup)", "#22c55e"),
    "breakout_trap": ("🪤", "Breakout (bull trap)", "#ef4444"),
    "breakout_unclear": ("❔", "Breakout (unclear)", "#facc15"),
    "breakdown": ("⬇️", "Support breakdown", "#f87171"),
    "guard_breakout": ("🚀", "Guard: breakout", "#22c55e"),
    "guard_failed_breakout": ("🪤", "Guard: failed breakout", "#ef4444"),
    "guard_breakdown": ("⬇️", "Guard: breakdown", "#f87171"),
    "guard_spring": ("🌱", "Guard: spring", "#4ade80"),
    "guard_reclaim": ("↩️", "Guard: reclaim", "#38bdf8"),
}
WIB = dtm.timezone(dtm.timedelta(hours=7))

sigs = load_signals()
if not sigs:
    st.info("No signals recorded yet. They appear automatically once the "
            "hourly cron (or an Analyze run) detects accumulation, "
            "distribution, or a divergence on a watchlist token.")
    st.stop()

df = pd.DataFrame(sigs)
df["dt_utc"] = pd.to_datetime(df["ts"], unit="s", utc=True)
df["dt_wib"] = df["dt_utc"].dt.tz_convert("Asia/Jakarta")
df = df.sort_values("ts", ascending=False)

# --- filters -----------------------------------------------------------------
f1, f2, f3 = st.columns([1.5, 1.5, 1])
tokens = ["All"] + sorted(df["symbol"].astype(str).unique().tolist())
pick_tok = f1.selectbox("Token", tokens)
types = ["All"] + [TYPE_META[t][1] for t in TYPE_META if t in
                   set(df["type"])]
pick_type = f2.selectbox("Signal type", types)
days_back = f3.selectbox("Range", [1, 3, 7, 30], index=2,
                         format_func=lambda d: f"last {d}d")

view = df[df["ts"] >= (pd.Timestamp.utcnow().timestamp() - days_back * 86400)]
if pick_tok != "All":
    view = view[view["symbol"] == pick_tok]
if pick_type != "All":
    inv = {v[1]: k for k, v in TYPE_META.items()}
    view = view[view["type"] == inv.get(pick_type, "")]

# --- summary chips -----------------------------------------------------------
cnt = view["type"].value_counts().to_dict()
chips = " ".join(
    f"<span style='background:{TYPE_META[t][2]}22;border:1px solid "
    f"{TYPE_META[t][2]};border-radius:8px;padding:3px 10px;margin-right:6px;"
    f"font-size:0.8rem;color:{TYPE_META[t][2]};'>{TYPE_META[t][0]} "
    f"{TYPE_META[t][1]}: <b>{cnt.get(t, 0)}</b></span>"
    for t in TYPE_META)
st.markdown(chips, unsafe_allow_html=True)
st.markdown("")

if view.empty:
    st.warning("No signals match the filters.")
    st.stop()

# --- timeline scatter (time vs token, colored by type) ------------------------
if len(view) >= 2:
    figt = go.Figure()
    for t, (emo, label, color) in TYPE_META.items():
        seg = view[view["type"] == t]
        if seg.empty:
            continue
        figt.add_trace(go.Scatter(
            x=seg["dt_wib"].dt.tz_localize(None), y=seg["symbol"],
            mode="markers", name=f"{emo} {label}",
            marker=dict(size=13, color=color,
                        symbol="triangle-up" if "bull" in t or t == "accumulation"
                        else "triangle-down"),
            customdata=seg[["detail"]].values,
            hovertemplate="<b>%{y}</b> · %{x|%d %b %H:%M} WIB<br>"
                          "%{customdata[0]}<extra></extra>"))
    figt.update_layout(height=max(200, 60 + 40 * view["symbol"].nunique()),
                       margin=dict(t=10, b=0, l=0, r=0),
                       legend=dict(orientation="h", font=dict(size=10)),
                       xaxis_title="time (WIB)")
    st.plotly_chart(figt, use_container_width=True,
                    config={"displayModeBar": False})

# --- table --------------------------------------------------------------------
rows = []
for _, s in view.iterrows():
    emo, label, _c = TYPE_META.get(s["type"], ("•", s["type"], "#888"))
    rows.append({
        "WIB": s["dt_wib"].strftime("%d %b %H:%M"),
        "UTC": s["dt_utc"].strftime("%d %b %H:%M"),
        "Token": s["symbol"],
        "Signal": f"{emo} {label}",
        "Detail": s["detail"],
        "🐋 net": (f"{s['whale_net']:+,.1f}"
                   if pd.notna(s.get("whale_net")) else "—"),
        "🐟 net": (f"{s['retail_net']:+,.1f}"
                   if pd.notna(s.get("retail_net")) else "—"),
        "Price then": (f"${s['price']:.8f}".rstrip("0")
                       if pd.notna(s.get("price")) and s.get("price")
                       else "—"),
        "Src": s.get("src", "?"),
        "Chart": f"https://dexscreener.com/solana/{s['ca']}",
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
             column_config={"Chart": st.column_config.LinkColumn(
                 "Chart", display_text="open 📊")})
st.caption("Dedupe: the same signal type per token is recorded at most once "
           "per 4h. 'Price then' = price at detection — compare it with the "
           "current chart to judge how the signal played out. Src: cron = "
           "automatic hourly check, analyze = you ran it.")
