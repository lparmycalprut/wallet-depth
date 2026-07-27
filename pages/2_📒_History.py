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

# ---------------------------------------------------------------------------
# 🔄 This session's full analyses — instant view, NO re-fetching
# ---------------------------------------------------------------------------
sess = st.session_state.get("analyses", {})
if sess:
    st.markdown("### ⚡ This session's analyses (no re-fetch needed)")
    pick_s = st.selectbox(
        "Open a stored analysis",
        list(sess.keys()),
        format_func=lambda c: f"{sess[c]['symbol']} — scanned "
                              f"{sess[c]['when']} — {c[:16]}…")
    if pick_s:
        a = sess[pick_s]
        h1, h2, h3, h4, h5, h6 = st.columns(6)
        from core import score_color as _sc
        h1.markdown(
            f"<div style='text-align:center;border:2px solid "
            f"{_sc(a['score'])};border-radius:10px;padding:6px;'>"
            f"<b style='font-size:1.4rem;color:{_sc(a['score'])}'>"
            f"{a['score']}</b><br><span style='font-size:0.7rem;color:"
            f"{_sc(a['score'])}'>{a['score_label']}</span></div>",
            unsafe_allow_html=True)
        h2.metric("Price", f"${a['price']:,.8f}".rstrip("0").rstrip("."))
        h3.metric("Marketcap", f"${a['marketcap']:,.0f}")
        h4.metric("Holders", f"{a['holders']:,}",
                  (f"{a['holder_delta']:+,}" if a.get("holder_delta")
                   is not None else None))
        h5.metric("Real / Dust", f"{a['real']:,} / {a['dust']:,}",
                  f"ratio {a['ratio_pct']:.0f}%", delta_color="off")
        h6.metric("Liquidity", f"${a['liq_usd']:,.0f}",
                  f"{a['liq_pct_mc']:.1f}% MC", delta_color="off")

        # security checklist snapshot
        if a.get("checks"):
            n_fail = sum(1 for ok, _ in a["checks"] if ok is False)
            items = "".join(
                f"<div style='flex:0 0 49%;padding:2px 6px;font-size:0.8rem;"
                f"color:{'#bbf7d0' if ok else '#fecaca'};'>"
                f"{'✅' if ok else '❌'} {lab}</div>"
                for ok, lab in a["checks"])
            hc = "#22c55e" if n_fail == 0 else "#ef4444"
            st.markdown(
                f"<div style='background:{'#14261b' if n_fail == 0 else '#2a1517'};"
                f"border:1px solid {hc};border-radius:10px;padding:6px 10px;"
                f"margin:4px 0;'><b style='color:{hc};font-size:0.82rem'>"
                f"🛡️ Security — "
                f"{'all passed' if n_fail == 0 else str(n_fail) + ' issue(s)'}"
                f"</b><div style='display:flex;flex-wrap:wrap;'>{items}</div>"
                f"</div>", unsafe_allow_html=True)

        t1, t2 = st.columns(2)
        with t1:
            st.markdown("**📶 Wallet Depth**")
            if a.get("tier_df") is not None:
                td = a["tier_df"].copy()
                td["Wallets"] = td["Wallets"].map(lambda v: f"{v:,}")
                td["USD Value"] = td["USD Value"].map(lambda v: f"${v:,.0f}")
                td["% MC"] = td["% MC"].map(lambda v: f"{v:.2f}%")
                td["% Holders"] = td["% Holders"].map(lambda v: f"{v:.2f}%")
                st.dataframe(td, use_container_width=True, hide_index=True)
            st.markdown("**🏆 Top 20 holders (at scan time)**")
            if a.get("top20") is not None:
                tp = a["top20"].copy()
                tp["Wallet"] = tp["owner"].map(
                    lambda w: f"https://solscan.io/account/{w}")
                tp["Tokens"] = tp["ui_amount"].map(lambda v: f"{v:,.0f}")
                tp["USD"] = tp["usd_value"].map(lambda v: f"${v:,.2f}")
                tp["% Supply"] = tp["pct_supply"].map(lambda v: f"{v:.2f}%")
                st.dataframe(tp[["Wallet", "Tokens", "USD", "% Supply"]],
                             use_container_width=True, hide_index=True,
                             column_config={"Wallet":
                                            st.column_config.LinkColumn(
                                                "Wallet",
                                                display_text=r"account/(.{6}).*")})
        with t2:
            if a.get("cvd"):
                c = a["cvd"]
                st.markdown(f"**📊 CVD at scan time (last {c['window_h']}h, "
                            f"{c['swaps']:,} swaps)**")
                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Net", f"{c['net']:+,.1f} SOL", delta_color="off")
                cc2.metric("🐋 Whale", f"{c['whale_net']:+,.1f}",
                           delta_color="off")
                cc3.metric("🐟 Retail", f"{c['retail_net']:+,.1f}",
                           delta_color="off")
                import plotly.graph_objects as go
                lagg = c["agg"]
                figc = go.Figure()
                figc.add_trace(go.Scatter(x=lagg.index, y=lagg["cvd"],
                                          name="CVD",
                                          line=dict(color="#38bdf8",
                                                    width=2.5)))
                figc.add_trace(go.Scatter(x=lagg.index, y=lagg["wcvd"],
                                          name="🐋",
                                          line=dict(color="#c084fc",
                                                    width=1.8)))
                figc.update_layout(height=220,
                                   margin=dict(t=10, b=0, l=0, r=0),
                                   legend=dict(orientation="h"))
                st.plotly_chart(figc, use_container_width=True,
                                config={"displayModeBar": False})
            if a.get("bundles") is not None:
                st.markdown("**🕸️ Clusters found**")
                bd = a["bundles"].copy()
                bd["Funder"] = bd["funder"].map(
                    lambda w: f"https://solscan.io/account/{w}")
                bd["% Supply"] = bd["pct_supply"].map(lambda v: f"{v:.2f}%")
                st.dataframe(bd[["Funder", "wallets", "% Supply"]].rename(
                    columns={"wallets": "Wallets"}),
                    use_container_width=True, hide_index=True,
                    column_config={"Funder": st.column_config.LinkColumn(
                        "Funder", display_text=r"account/(.{6}).*")})
        st.caption(f"Snapshot taken {a['when']} — data is frozen at scan "
                   f"time. Session-only: clears when the app restarts. For "
                   f"long-term daily history see the tables below.")
    st.divider()
else:
    st.info("💡 Analyses you run on the main page this session will appear "
            "here for instant re-viewing (no re-fetch). Long-term daily "
            "snapshots are below.")


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
