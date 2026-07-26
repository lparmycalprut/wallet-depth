# -*- coding: utf-8 -*-
"""Page: Riwayat analisa — jurnal semua CA yang pernah discan."""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import load_history, score_color

st.set_page_config(page_title="Riwayat Analisa", page_icon="📒",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
</style>""", unsafe_allow_html=True)

st.title("📒 Riwayat Analisa")
st.caption("Jurnal semua token yang pernah dianalisa + snapshot hariannya. "
           "Data tersimpan lokal di history.json.")

hist = load_history()
if not hist:
    st.info("Belum ada riwayat. Analisa token dulu di halaman utama.")
    st.stop()

rows = []
for ca, days in hist.items():
    dates = sorted(days.keys())
    last = days[dates[-1]]
    first = days[dates[0]]
    delta = last["total_holders"] - first["total_holders"] \
        if len(dates) > 1 else None
    rows.append({
        "ca": ca,
        "Token": last.get("symbol", ca[:8] + "…"),
        "Terakhir Scan": dates[-1],
        "Skor": last.get("score"),
        "Holder": last["total_holders"],
        "Δ Holder (sejak awal)": delta,
        "Real": last["real"],
        "Dust": last["dust"],
        "Real %MC": last.get("real_mc_pct"),
        "Top10 %": last.get("top10_pct"),
        "MC": last.get("marketcap"),
        "Jml Snapshot": len(dates),
    })

df = pd.DataFrame(rows).sort_values("Terakhir Scan", ascending=False)

show = df.copy()
show["Skor"] = show["Skor"].map(lambda v: f"{int(v)}/100" if pd.notna(v) else "—")
show["Holder"] = show["Holder"].map(lambda v: f"{v:,}")
show["Δ Holder (sejak awal)"] = show["Δ Holder (sejak awal)"].map(
    lambda v: f"{int(v):+,}" if pd.notna(v) else "—")
show["Real"] = show["Real"].map(lambda v: f"{v:,}")
show["Dust"] = show["Dust"].map(lambda v: f"{v:,}")
show["Real %MC"] = show["Real %MC"].map(
    lambda v: f"{v:.1f}%" if pd.notna(v) else "—")
show["Top10 %"] = show["Top10 %"].map(
    lambda v: f"{v:.1f}%" if pd.notna(v) else "—")
show["MC"] = show["MC"].map(lambda v: f"${v:,.0f}" if pd.notna(v) else "—")
show["CA"] = show["ca"]
st.dataframe(show[["Token", "Terakhir Scan", "Skor", "Holder",
                   "Δ Holder (sejak awal)", "Real", "Dust", "Real %MC",
                   "Top10 %", "MC", "Jml Snapshot", "CA"]],
             use_container_width=True, hide_index=True)

# Detail per token
st.markdown("### 🔍 Detail snapshot per token")
pilihan = st.selectbox(
    "Pilih token", df["ca"].tolist(),
    format_func=lambda c: f"{hist[c][sorted(hist[c])[-1]].get('symbol', '?')} "
                          f"— {c[:20]}…")
if pilihan:
    days = hist[pilihan]
    drows = []
    prev_h = None
    for d in sorted(days.keys()):
        s = days[d]
        drows.append({
            "Tanggal": d,
            "Holder": f"{s['total_holders']:,}",
            "Δ": (f"{s['total_holders']-prev_h:+,}" if prev_h is not None else "—"),
            "Real": f"{s['real']:,}",
            "Dust": f"{s['dust']:,}",
            "Real %MC": f"{s.get('real_mc_pct', 0):.1f}%",
            "Skor": (f"{int(s['score'])}" if s.get("score") is not None else "—"),
            "MC": f"${s.get('marketcap', 0):,.0f}",
            "Harga": f"${s.get('price', 0):.8f}",
        })
        prev_h = s["total_holders"]
    st.dataframe(pd.DataFrame(drows), use_container_width=True,
                 hide_index=True)

    import plotly.graph_objects as go
    dd = sorted(days.keys())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dd, y=[days[d]["total_holders"] for d in dd],
                             name="Holder", mode="lines+markers",
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
