# -*- coding: utf-8 -*-
"""Page: Scan history — journal of every CA analyzed."""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import load_history

st.set_page_config(page_title="Scan History", page_icon="📒",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
</style>""", unsafe_allow_html=True)

st.title("📒 Scan History")
st.caption("Journal of every token analyzed + its daily snapshots. "
           "Stored locally in history.json.")

hist = load_history()
if not hist:
    st.info("No history yet. Analyze a token on the main page first.")
    st.stop()

rows = []
for ca, days in hist.items():
    dates = sorted(days.keys())
    last = days[dates[-1]]
    first = days[dates[0]]
    delta = (last["total_holders"] - first["total_holders"]
             if len(dates) > 1 else None)
    rows.append({
        "ca": ca,
        "Token": last.get("symbol", ca[:8] + "…"),
        "Last Scan": dates[-1],
        "Score": last.get("score"),
        "Holders": last["total_holders"],
        "Δ Holders (since first)": delta,
        "Real": last["real"],
        "Dust": last["dust"],
        "Real %MC": last.get("real_mc_pct"),
        "Top10 %": last.get("top10_pct"),
        "MC": last.get("marketcap"),
        "Snapshots": len(dates),
    })

df = pd.DataFrame(rows).sort_values("Last Scan", ascending=False)

show = df.copy()
show["Score"] = show["Score"].map(lambda v: f"{int(v)}/100" if pd.notna(v) else "—")
show["Holders"] = show["Holders"].map(lambda v: f"{v:,}")
show["Δ Holders (since first)"] = show["Δ Holders (since first)"].map(
    lambda v: f"{int(v):+,}" if pd.notna(v) else "—")
show["Real"] = show["Real"].map(lambda v: f"{v:,}")
show["Dust"] = show["Dust"].map(lambda v: f"{v:,}")
show["Real %MC"] = show["Real %MC"].map(
    lambda v: f"{v:.1f}%" if pd.notna(v) else "—")
show["Top10 %"] = show["Top10 %"].map(
    lambda v: f"{v:.1f}%" if pd.notna(v) else "—")
show["MC"] = show["MC"].map(lambda v: f"${v:,.0f}" if pd.notna(v) else "—")
show["CA"] = show["ca"].map(lambda c: f"https://solscan.io/token/{c}")
st.dataframe(show[["Token", "Last Scan", "Score", "Holders",
                   "Δ Holders (since first)", "Real", "Dust", "Real %MC",
                   "Top10 %", "MC", "Snapshots", "CA"]],
             use_container_width=True, hide_index=True,
             column_config={"CA": st.column_config.LinkColumn(
                 "CA", display_text=r"token/(.{8}).*")})

st.markdown("### 🔍 Per-token snapshot detail")
pick = st.selectbox(
    "Select token", df["ca"].tolist(),
    format_func=lambda c: f"{hist[c][sorted(hist[c])[-1]].get('symbol', '?')} "
                          f"— {c[:20]}…")
if pick:
    days = hist[pick]
    drows = []
    prev_h = None
    for d in sorted(days.keys()):
        s = days[d]
        drows.append({
            "Date": d,
            "Holders": f"{s['total_holders']:,}",
            "Δ": (f"{s['total_holders']-prev_h:+,}" if prev_h is not None else "—"),
            "Real": f"{s['real']:,}",
            "Dust": f"{s['dust']:,}",
            "Real %MC": f"{s.get('real_mc_pct', 0):.1f}%",
            "Score": (f"{int(s['score'])}" if s.get("score") is not None else "—"),
            "MC": f"${s.get('marketcap', 0):,.0f}",
            "Price": f"${s.get('price', 0):.8f}",
        })
        prev_h = s["total_holders"]
    st.dataframe(pd.DataFrame(drows), use_container_width=True, hide_index=True)

    import plotly.graph_objects as go
    dd = sorted(days.keys())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dd, y=[days[d]["total_holders"] for d in dd],
                             name="Holders", mode="lines+markers",
                             line=dict(color="#38bdf8")))
    fig.add_trace(go.Scatter(x=dd, y=[days[d]["real"] for d in dd],
                             name="Real", mode="lines+markers",
                             line=dict(color="#22c55e")))
    fig.add_trace(go.Scatter(x=dd, y=[days[d]["dust"] for d in dd],
                             name="Dust", mode="lines+markers",
                             line=dict(color="#64748b")))
    fig.update_layout(height=300, margin=dict(t=20, b=10),
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})
