# -*- coding: utf-8 -*-
"""Page: Watchlist — tokens tracked by the daily snapshot cron."""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import load_history, score_color
from watchlist import load_watchlist, remove_from_watchlist, add_to_watchlist

st.set_page_config(page_title="Watchlist", page_icon="⭐",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.72rem !important;}
</style>""", unsafe_allow_html=True)

st.title("⭐ Watchlist")
st.caption("Tokens on this list are snapshotted automatically every day at "
           "00:00 WIB by the GitHub Actions cron — history keeps building "
           "even when you don't open the dashboard. Remove a CA when you're "
           "done with it.")

wl = load_watchlist()
hist = load_history()

# --- quick pick -------------------------------------------------------------
# Re-use tokens the user has already analyzed (or snapshotted) so adding to
# the watchlist is one click. Pulls from history.json (any CA with at least
# one local snapshot) and from the live GMGN trending screener rows the
# user has already loaded into this session. The manual CA input below
# stays the source of truth for brand-new CAs.
quick_pick_options = []
for ca_key, days in (hist or {}).items():
    if ca_key in wl:
        continue
    if not isinstance(days, dict) or not days:
        continue
    last_date = max(days.keys())
    snap = days.get(last_date) or {}
    sym = (snap.get("symbol") or "?").strip() or "?"
    quick_pick_options.append((ca_key, sym, last_date, "history"))
# also expose screener rows the user has already loaded in this session
for r in (st.session_state.get("screener_rows") or []):
    ca_r = r.get("ca")
    sym_r = (r.get("symbol") or "?").strip() or "?"
    if ca_r and ca_r not in wl and not any(
            q[0] == ca_r for q in quick_pick_options):
        quick_pick_options.append((ca_r, sym_r, "trending", "screener"))

quick_pick_options.sort(key=lambda x: (x[0] not in (hist or {}),
                                       -ord((x[1] or "?")[0])))

if quick_pick_options:
    with st.expander("⚡ Quick-pick — add a token you've already analyzed",
                     expanded=False):
        st.caption("Pick from CAs you've analyzed before (history) or that "
                   "are in this session's trending screener. Manual CA "
                   "input below still works for anything new.")
        qp_cols = st.columns([3, 1.2, 0.8])
        labels = [f"{sym}  ·  {ca[:8]}…{ca[-4:]}  ·  ({src})"
                  for ca, sym, _date, src in quick_pick_options]
        label_to_ca = {labels[i]: quick_pick_options[i][0]
                       for i in range(len(quick_pick_options))}
        chosen = qp_cols[0].selectbox(
            "Token", ["— pick one —"] + labels,
            label_visibility="collapsed")
        qp_note = qp_cols[1].text_input(
            "Note (optional)", placeholder="note...",
            key="qp_note_input",
            label_visibility="collapsed").strip()
        if qp_cols[2].button("Add", use_container_width=True,
                             type="primary", key="qp_add"):
            if chosen and chosen != "— pick one —":
                _picked_ca = label_to_ca[chosen]
                # Determine source from the quick-pick option
                _picked_src = next(
                    (src for ca, sym, _date, src in quick_pick_options
                     if ca == _picked_ca), "manual")
                if not add_to_watchlist(_picked_ca, note=qp_note,
                                        source=_picked_src):
                    st.warning("Added, but GitHub commit failed — set "
                               "`github_token` in Streamlit Secrets so "
                               "changes survive restarts.")
                    import time as _t
                    _t.sleep(2.5)
                st.rerun()
            else:
                st.warning("Pick a token first.")

# --- manual add -------------------------------------------------------------
with st.expander("➕ Add a CA manually", expanded=not wl):
    c1, c2, c3 = st.columns([3, 1.2, 0.8])
    new_ca = c1.text_input("Contract Address", placeholder="Solana CA...",
                           key="manual_ca_input",
                           label_visibility="collapsed").strip()
    new_note = c2.text_input("Note (optional)", placeholder="note...",
                             key="manual_note_input",
                             label_visibility="collapsed").strip()
    if c3.button("Add", use_container_width=True, type="primary"):
        if new_ca:
            if not add_to_watchlist(new_ca, note=new_note,
                                    source="manual"):
                st.warning("Added, but GitHub commit failed — set "
                           "`github_token` in Streamlit Secrets so changes "
                           "survive restarts.")
                import time as _t
                _t.sleep(2.5)
            st.rerun()
        else:
            st.warning("CA is empty.")

if not wl:
    st.info("Watchlist is empty. Add a CA above, or click "
            "**⭐ Add to watchlist** after analyzing a token on the main page.")
    st.stop()

# --- table ------------------------------------------------------------------
rows = []
for ca, meta in wl.items():
    days = hist.get(ca, {})
    dates = sorted(days.keys())
    last = days[dates[-1]] if dates else {}
    prev = days[dates[-2]] if len(dates) > 1 else {}
    d_hold = (last.get("total_holders", 0) - prev.get("total_holders", 0)
              if prev else None)
    rows.append({
        "ca": ca,
        "Token": meta.get("symbol", "?"),
        "Note": meta.get("note", ""),
        "Added": meta.get("added", "—"),
        "Last snapshot": dates[-1] if dates else "— (waiting for cron)",
        "Score": last.get("score"),
        "Holders": last.get("total_holders"),
        "Δ vs prev": d_hold,
        "Real %MC": last.get("real_mc_pct"),
        "Top10 %": last.get("top10_pct"),
        "MC": last.get("marketcap"),
        "Snapshots": len(dates),
    })

df = pd.DataFrame(rows)

hdr = st.columns([1.0, 1.6, 1.1, 0.7, 0.9, 0.8, 0.9, 0.9, 0.8, 1.0, 0.9, 0.6])
for col, label in zip(hdr, ["Token", "CA", "Last snapshot", "Score",
                            "Holders", "Δ prev", "Real %MC", "Top10 %",
                            "MC", "Note", "Snapshots", ""]):
    col.markdown(f"**{label}**")

for _, r in df.iterrows():
    c = st.columns([1.0, 1.6, 1.1, 0.7, 0.9, 0.8, 0.9, 0.9, 0.8, 1.0, 0.9, 0.6])
    c[0].markdown(f"**{r['Token']}**")
    c[1].markdown(f"[`{r['ca'][:14]}…`](https://solscan.io/token/{r['ca']})")
    c[2].write(r["Last snapshot"])
    if pd.notna(r["Score"]) and r["Score"] is not None:
        sc = int(r["Score"])
        c[3].markdown(f"<span style='color:{score_color(sc)};font-weight:700'>"
                      f"{sc}</span>", unsafe_allow_html=True)
    else:
        c[3].write("—")
    c[4].write(f"{int(r['Holders']):,}" if pd.notna(r["Holders"]) and
               r["Holders"] is not None else "—")
    if r["Δ vs prev"] is not None and pd.notna(r["Δ vs prev"]):
        dv = int(r["Δ vs prev"])
        c[5].markdown(f"<span style='color:{'#22c55e' if dv >= 0 else '#ef4444'}'>"
                      f"{dv:+,}</span>", unsafe_allow_html=True)
    else:
        c[5].write("—")
    c[6].write(f"{r['Real %MC']:.1f}%" if pd.notna(r["Real %MC"]) and
               r["Real %MC"] is not None else "—")
    c[7].write(f"{r['Top10 %']:.1f}%" if pd.notna(r["Top10 %"]) and
               r["Top10 %"] is not None else "—")
    c[8].write(f"${r['MC']:,.0f}" if pd.notna(r["MC"]) and
               r["MC"] is not None else "—")
    c[9].write(r["Note"] or "")
    c[10].write(str(r["Snapshots"]))
    if c[11].button("🗑️ Hapus", key=f"rm_{r['ca']}", help="Remove from watchlist", use_container_width=True, type="secondary"):
        if not remove_from_watchlist(r["ca"]):
            st.warning("Removed, but GitHub commit failed — set "
                       "`github_token` in Streamlit Secrets so changes "
                       "survive restarts.")
            import time as _t
            _t.sleep(2.5)
        st.rerun()

st.caption("🗑️ removes the CA from the watchlist (its history is kept in "
           "history.json). The cron needs the repo secret HELIUS_API_KEY — "
           "see README. You can also trigger it manually: GitHub → Actions → "
           "'Daily watchlist snapshot' → Run workflow.")
