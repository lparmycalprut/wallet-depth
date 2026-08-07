# -*- coding: utf-8 -*-
"""CVD Deep Analysis — minimalist (kept: swap fetch, conviction, prepump)."""
import datetime as dtm
import io
import json
import os
import sys
import time
import zoneinfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import get_helius_keys, get_market, helius_rpc, load_config, get_holders as core_get_holders, get_supply as core_get_supply
from cvd import (MIN_SOL, WHALE_SOL, analysis_windows, classify_swap, cohort_activity_summary, cohort_cvd_series, conviction_split, detect_cohort_divergences, detect_divergence, filter_swaps_by_time, get_gmgn_wallet_metadata, split_wallet_profile_cohorts, summarize_swap_range, wallet_profiles)
from prepump_detector import evaluate_prepump, compute_bullish_div, evaluate_prepump_multi_tf, PREPUMP_TF_ORDER, PREPUMP_TIER_BADGES
from signals import detect_prepump_and_record

st.set_page_config(page_title="CVD Analysis", page_icon="📊", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>.block-container {padding-top: 1.2rem; max-width: 1400px;} h1 {font-size: 1.3rem !important;} [data-testid="stMetric"] {padding: 0.2rem 0.5rem; background: rgba(128,128,128,0.07); border-radius: 8px;} [data-testid="stMetricLabel"] {font-size: 0.72rem !important;} [data-testid="stMetricValue"] {font-size: 1.1rem !important;}</style>""", unsafe_allow_html=True)

st.title("📊 CVD Deep Analysis")
st.caption("Analisis swap flow mendalam. Pilih window, evaluasi conviction, whale/dolphin, dan sinyal prepump.")

CONFIG = load_config()
helius_keys = tuple(get_helius_keys(config=CONFIG))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
qp_ca = st.query_params.get("ca", "").strip()
ca = st.text_input("Contract Address", value=qp_ca, placeholder="Solana CA...").strip()
col1, col3 = st.columns([1, 3])
with col1:
    hours = st.selectbox("Time window", [4, 6, 8, 12, 24, 36, 48, 72], index=5, help="Fetch swaps for this many hours back")
use_gmgn_trades = True
with col3:
    run = st.button("📊 Analyze", type="primary", use_container_width=True)

if not ca:
    st.info("Paste CA. Fetch akan mengambil history swap lengkap untuk window terpilih — token sangat aktif bisa beberapa menit.")
    st.stop()

source_key = "gmgn" if use_gmgn_trades else "helius"
skey = f"cvd::{source_key}::{hours}h::{ca}"
if not run and skey not in st.session_state:
    st.stop()

@st.cache_data(ttl=120, show_spinner=False)
def get_pool(ca: str):
    market = get_market(ca)
    pools = market.get("pair_addresses") or []
    if not market or not pools:
        return None, None, None, None
    return (pools[0], market.get("symbol", "?"), float(market.get("price_usd") or 0), float(market.get("marketcap") or 0))

def full_fetch(ca: str, pool: str, cutoff_ts: int, *, use_gmgn: bool = False):
    if use_gmgn:
        from cvd import fetch_swaps, get_gmgn_last_error
        pbar = st.progress(0.0, text=f"Fetching GMGN {hours}h…")
        try:
            swaps, _sig, _ts, _hit = fetch_swaps("", pool or "", ca, stop_ts=cutoff_ts, max_pages=120, sleep=0.05, use_gmgn=True)
        except Exception as exc:
            st.warning(f"GMGN fetch failed: {exc}")
            swaps = []
        finally:
            pbar.empty()
        err = get_gmgn_last_error()
        if err and not swaps:
            st.warning("GMGN kosong: " + err)
        return swaps
    from cvd import _fetch_page
    swaps, before = [], None
    pbar = st.progress(0.0, text=f"Fetching swaps for {hours}h…")
    t0 = time.time()
    oldest = time.time()
    consecutive_fail = 0
    for page in range(1500):
        data = _fetch_page(helius_keys, pool, before)
        if data is None:
            consecutive_fail += 1
            if consecutive_fail >= 3:
                st.warning(f"Fetch aborted after repeated failures at page {page+1}")
                break
            time.sleep(2.0)
            continue
        consecutive_fail = 0
        if not data:
            break
        done = False
        for tx in data:
            ts = tx.get("timestamp") or 0
            if ts <= cutoff_ts:
                done = True
                break
            s = classify_swap(tx, pool, ca)
            if s and s[1] >= MIN_SOL:
                swaps.append(s)
        oldest = data[-1].get("timestamp") or oldest
        frac = min(1.0, max(0.02, (time.time() - oldest) / max(time.time() - cutoff_ts, 1)))
        pbar.progress(frac, text=f"Fetching… page {page+1} · {len(swaps):,} swaps")
        if done:
            break
        before = data[-1].get("signature")
        time.sleep(0.1)
    pbar.empty()
    return swaps

pool, symbol, price_now, mc_now = get_pool(ca)
if not pool:
    st.error("Token tidak ditemukan di DexScreener.")
    st.stop()

WINDOWS = analysis_windows(hours)

if run or skey not in st.session_state:
    cutoff = int(time.time()) - hours * 3600
    got = []
    if use_gmgn_trades:
        st.info(f"Fetching last {hours}h from GMGN Trades API…")
        got = full_fetch(ca, pool, cutoff, use_gmgn=True)
        src = "GMGN Trades API"
    else:
        from watchlist import load_watchlist
        from cvd import update_token_cvd, get_recent_swaps
        src = "full fetch"
        if ca in load_watchlist():
            with st.spinner("Topping up incremental store…"):
                try:
                    update_token_cvd(helius_keys, ca, pool, max_pages=200)
                except Exception:
                    pass
                got = get_recent_swaps(ca, hours)
                src = "incremental store"
        if not got:
            st.info(f"Fetching last {hours}h of swaps…")
            got = full_fetch(ca, pool, cutoff)
            src = "full fetch"
    st.session_state[skey] = {"swaps": got, "ts": time.time(), "src": src}
swaps_all = st.session_state[skey]["swaps"]
fetched_at = st.session_state[skey]["ts"]
st.caption(f"Source: {st.session_state[skey].get('src', '?')}")
if not swaps_all:
    st.warning(f"No swaps ≥ {MIN_SOL:g} SOL in last {hours}h.")
    st.stop()

_seen_all = {}
for s in swaps_all:
    if len(s) >= 4:
        _seen_all[(s[0], float(s[1]), int(s[2]), str(s[3]))] = s
swaps_all = [list(k) for k in sorted(_seen_all.keys(), key=lambda x: x[2])]
df = pd.DataFrame(swaps_all, columns=["side", "sol", "ts", "wallet"])
df["dt"] = pd.to_datetime(df["ts"], unit="s")
df["signed"] = df.apply(lambda r: r["sol"] if r["side"] == "buy" else -r["sol"], axis=1)
now_ts = fetched_at
covered_h = max(0.0, (now_ts - df["ts"].min()) / 3600)

win_stats = {}
for h in WINDOWS:
    seg = df[df["ts"] >= now_ts - h * 3600]
    if seg.empty:
        continue
    vb = float(seg.loc[seg["side"] == "buy", "sol"].sum())
    vs = float(seg.loc[seg["side"] == "sell", "sol"].sum())
    wseg = seg[seg["sol"] >= WHALE_SOL]
    wnet = float(wseg["signed"].sum())
    prof = wallet_profiles(list(seg[["side", "sol", "ts", "wallet"]].itertuples(index=False, name=None)))
    conv = conviction_split(prof, whale_min_sol=WHALE_SOL)
    net_pure = conv["pure_buy"] - conv["pure_sell"]
    if conv["conviction_pct"] >= 50 and net_pure > 0 and conv["pure_buy"] >= 10:
        verdict = "💎 HIGH-CONVICTION ACCUM"
    elif conv["pure_sell"] >= 10 and net_pure < 0:
        verdict = "🩸 hard distribution"
    elif wnet < -5 and (vb - vs - wnet) > 5:
        verdict = "⚡ whales→retail dist"
    elif wnet > 5 and (vb - vs - wnet) < -5:
        verdict = "⚡ stealth accum (check conv!)"
    else:
        verdict = "— neutral/churn"
    win_stats[h] = {"swaps": len(seg), "buy": vb, "sell": vs, "net": vb - vs, "whale_net": wnet, "retail_net": vb - vs - wnet, "pure_buy": conv["pure_buy"], "pure_sell": conv["pure_sell"], "conviction": conv["conviction_pct"], "net_pure": net_pure, "verdict": verdict, "profiles": prof}

st.markdown(f"### ${symbol} · {len(df):,} swaps · {covered_h:.1f}h covered · MC ${mc_now:,.0f}")
best_h = max(win_stats, key=lambda h: win_stats[h]["conviction"])
best = win_stats[best_h]
convs = [win_stats[h]["conviction"] for h in sorted(win_stats)]
conv_rising = len(convs) >= 2 and convs[0] > convs[-1]
is_candidate = (best["conviction"] >= 50 and best["net_pure"] > 0 and best["pure_buy"] >= 10)
if is_candidate:
    st.success(f"💎 **WHALE ACCUMULATION CANDIDATE** — conviction {best['conviction']:.0f}% in {best_h}h, {best['pure_buy']:.0f} SOL held, net pure {best['net_pure']:+.0f} SOL" + (" · conviction RISING ✅" if conv_rising else ""))
elif conv_rising and win_stats[min(win_stats)]["conviction"] >= 35:
    st.warning(f"⏳ **Building** — conviction {convs[-1]:.0f}% → {convs[0]:.0f}%, belum ≥50%. Watch.")
else:
    st.info(f"❌ Not accumulation candidate — best {best['conviction']:.0f}% ({best_h}h). {best['verdict']}")

_cohort_stats = {}
for h in sorted(win_stats):
    _cohort_stats[h] = cohort_activity_summary(win_stats[h].get("profiles", {}), whale_min_sol=WHALE_SOL)
mw_rows = []
for h in sorted(win_stats):
    s = win_stats[h]
    _cs = _cohort_stats.get(h, {})
    mw_rows.append({"Window": f"{h}h", "Swaps": f"{s['swaps']:,}", "Net CVD": f"{s['net']:+,.0f}", "🐋 Whale": f"{s['whale_net']:+,.0f}", "🐋 Whale held": f"{_cs.get('whale_net', 0):+,.0f}", "🐬 Dolphin": f"{_cs.get('dolphin_net', 0):+,.0f}", "🐟 Retail": f"{s['retail_net']:+,.0f}", "💎 Pure buy": f"{s['pure_buy']:,.0f}", "🩸 Pure sell": f"{s['pure_sell']:,.0f}", "Net pure": f"{s['net_pure']:+,.0f}", "Conviction": f"{s['conviction']:.0f}%", "Verdict": s["verdict"]})
st.dataframe(pd.DataFrame(mw_rows), use_container_width=True, hide_index=True)
st.caption("Healthy accumulation: conviction RISING di window pendek + 🩸 mengecil.")

figc = go.Figure()
figc.add_trace(go.Scatter(x=[f"{h}h" for h in sorted(win_stats, reverse=True)], y=[win_stats[h]["conviction"] for h in sorted(win_stats, reverse=True)], mode="lines+markers+text", text=[f"{win_stats[h]['conviction']:.0f}%" for h in sorted(win_stats, reverse=True)], textposition="top center", line=dict(color="#38bdf8", width=3)))
figc.add_hline(y=50, line_dash="dot", line_color="#22c55e", annotation_text="entry 50%")
figc.add_hline(y=30, line_dash="dot", line_color="#ef4444", annotation_text="noise <30%")
figc.update_layout(height=220, margin=dict(t=10, b=0, l=0, r=0), yaxis=dict(title="conviction %", range=[0, 100]), title=dict(text=f"Conviction across windows ({hours}h → {WINDOWS[0]}h)", font=dict(size=13)))
st.plotly_chart(figc, use_container_width=True, config={"displayModeBar": False})

full_profiles = win_stats[max(win_stats)]["profiles"]

g = df.set_index("dt").sort_index()
agg = g.groupby([pd.Grouper(freq="60min"), "side"])["sol"].sum().unstack(fill_value=0.0)
agg["buy"] = agg.get("buy", 0.0)
agg["sell"] = agg.get("sell", 0.0)
agg["delta"] = agg["buy"] - agg["sell"]
agg["cvd"] = agg["delta"].cumsum()
wagg = (g[g["sol"] >= WHALE_SOL].groupby([pd.Grouper(freq="60min"), "side"])["sol"].sum().unstack(fill_value=0.0)).reindex(agg.index, fill_value=0.0)
agg["wcvd"] = (wagg.get("buy", 0.0) - wagg.get("sell", 0.0)).cumsum()
agg["rcvd"] = agg["cvd"] - agg["wcvd"]
fig = go.Figure()
fig.add_trace(go.Scatter(x=agg.index, y=agg["cvd"], name="CVD (all)", line=dict(color="#38bdf8", width=3)))
fig.add_trace(go.Scatter(x=agg.index, y=agg["wcvd"], name="🐋 Whale", line=dict(color="#c084fc", width=2)))
fig.add_trace(go.Scatter(x=agg.index, y=agg["rcvd"], name="🐟 Retail", line=dict(color="#64748b", width=1.5, dash="dot")))
fig.add_bar(x=agg.index, y=agg["delta"], name="Δ/h", yaxis="y2", opacity=0.3, marker=dict(color=["#22c55e" if v >= 0 else "#ef4444" for v in agg["delta"]]))
fig.update_layout(height=320, margin=dict(t=25, b=0, l=0, r=0), legend=dict(orientation="h", font=dict(size=10)), yaxis=dict(title="cumulative SOL"), yaxis2=dict(overlaying="y", side="right", visible=False), title=dict(text=f"{hours}h CVD — hourly", font=dict(size=13)))
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

try:
    r = requests.get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/hour", params={"aggregate": 1, "limit": 60}, headers={"accept": "application/json"}, timeout=20)
    lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    pmap = {int(v[0]): float(v[4]) for v in lst}
except Exception:
    pmap = {}
pser, lastp = [], None
for t in agg.index:
    lastp = pmap.get(int(t.timestamp()), lastp)
    pser.append(lastp)
if pser and pser[0] is None:
    fv = next((p for p in pser if p is not None), None)
    pser = [fv if p is None else p for p in pser]
div_lines = []
if pser and all(p is not None for p in pser) and len(pser) >= 7:
    divs = detect_divergence(pser, list(agg["cvd"]))
    divs += [dict(d, src="whale") for d in detect_divergence(pser, list(agg["wcvd"]))]
    seen = set()
    for d in divs:
        k = (d["type"], d["kind"], d.get("src", "a"))
        if k in seen:
            continue
        seen.add(k)
        src = "Whale CVD" if d.get("src") == "whale" else "CVD"
        line = f"{d['kind']} {d['type']} divergence ({src}): {d['detail']}"
        div_lines.append(line)
        (st.success if d["type"] == "bullish" else st.error)(("📈 " if d["type"] == "bullish" else "📉 ") + "**" + d["kind"].upper() + " " + d["type"].upper() + f" ({src})** — " + d["detail"])

_wmeta = get_gmgn_wallet_metadata()
_has_bullish_div = any(d.get("type") == "bullish" for d in divs) if ("divs" in locals() and divs) else False
if not _has_bullish_div and pool:
    try:
        _has_bullish_div = compute_bullish_div(ca, pool)
    except Exception:
        pass

_pp_token_info = {"symbol": symbol, "price_usd": price_now, "mc": mc_now}
try:
    prepump_res = detect_prepump_and_record(ca, symbol, swaps_all, token_info=_pp_token_info, now_ts=int(now_ts), src="analyze", window_min=30, whale_min_sol=WHALE_SOL, wallet_tags=_wmeta, bullish_div=_has_bullish_div, pool=pool)
except Exception:
    try:
        prepump_res = evaluate_prepump(swaps_all, token_info=_pp_token_info, ca=ca, now_ts=int(now_ts), window_min=30, whale_min_sol=WHALE_SOL, wallet_tags=_wmeta, bullish_div=_has_bullish_div)
    except Exception:
        prepump_res = None

if prepump_res:
    st.markdown("#### 🎯 Pre-Pump Radar (30m)")
    pp_score = float(prepump_res.get("score", 0))
    pp_tier = prepump_res.get("tier", "neutral")
    pp_blocked = prepump_res.get("blocked", False)
    pp_stage = prepump_res.get("stage", "")
    pp_comp = float(prepump_res.get("compression_pct", 0))
    pp_pillars = prepump_res.get("pillars", {})
    pp_metrics = prepump_res.get("metrics", {})
    badge_color = {"imminent": "#ef4444", "forming": "#fb923c", "neutral": "#64748b", "blocked": "#9ca3af"}.get(pp_tier, "#94a3b8")
    tier_emoji = {"imminent": "🚨", "forming": "👀", "neutral": "➖", "blocked": "🚫"}.get(pp_tier, "❓")
    pp_col1, pp_col2 = st.columns([1, 1])
    with pp_col1:
        st.markdown(f"""<div style="padding:12px 16px;border-radius:10px;background:{badge_color}18;border-left:5px solid {badge_color};margin-bottom:8px;"><div style="display:flex;justify-content:space-between;align-items:center;"><h3 style="margin:0;color:{badge_color};font-size:1.15rem;">{tier_emoji} {pp_tier.upper()}</h3><span style="font-size:1.25rem;font-weight:700;color:{badge_color};">{pp_score:.0f}/100</span></div><p style="margin:4px 0 0;font-size:0.88rem;color:#334155;"><b>Status:</b> {pp_stage}</p></div>""", unsafe_allow_html=True)
        if pp_blocked:
            st.error(f"🚫 Blocked: {prepump_res.get('block_reason', '')}")
        else:
            st.success("✅ Safety lolos")
    with pp_col2:
        pm1, pm2 = st.columns(2)
        pm1.write(f"📉 **Compression:** `{pp_comp:.1f}%`")
        pm1.write(f"⚖️ **Avg Buy/Sell:** `{pp_metrics.get('avg_buy', 0):.2f}` / `{pp_metrics.get('avg_sell', 0):.2f}` SOL (`{pp_metrics.get('ratio', 0):.1f}×`)")
        pm1.write(f"🐋 **Whale Dumper:** `{'Ya ⚠️' if pp_metrics.get('whale_dumper') else 'Tidak ✅'}`")
        pm2.write(f"💰 **Flow 30m:** Net `{pp_metrics.get('net_sol', 0):+.2f}` SOL")
        pm2.write(f"💎 **Pure Accum:** `{pp_metrics.get('pct_pure', 0)*100:.0f}%` ({pp_metrics.get('n_pure', 0)} wallet)")
        _active_terms = ", ".join(pp_metrics.get('active_terminals', [])) or "—"
        pm2.write(f"🔥 **Smart / Terminals:** `{pp_metrics.get('smart_count', 0)}` · `{_active_terms}`")
    st.markdown("##### 📊 Breakdown 4 Pilar")
    pcols = st.columns(4)
    for idx, (label, key, icon) in enumerate([("Compression", "compression", "📉"), ("Asymmetry", "asymmetry", "⚖️"), ("Accumulation", "accum", "🐋"), ("Ignition / Delta", "delta", "🔥")]):
        val = float(pp_pillars.get(key, 0))
        with pcols[idx]:
            st.metric(label=f"{icon} {label}", value=f"{val:.0f}/25")

pp_multi_res = None
try:
    from cvd import get_recent_swaps as _grs_mtf
    _sw_long = [tuple(s) for s in (_grs_mtf(ca, 72) or []) if len(s) >= 4]
    _seen_long = {(s[0], float(s[1]), int(s[2]), str(s[3])) for s in _sw_long}
    _sw_merged = list(_sw_long)
    for s in swaps_all:
        if len(s) >= 4:
            k = (s[0], float(s[1]), int(s[2]), str(s[3]))
            if k not in _seen_long:
                _sw_merged.append(tuple(s))
    _sw_merged.sort(key=lambda x: x[2])
    _h4_div_mtf = False
    if pool:
        try:
            _h4_div_mtf = compute_bullish_div(ca, pool, bucket_hours=4, hours_span=96)
        except Exception:
            _h4_div_mtf = False
    pp_multi_res = evaluate_prepump_multi_tf(_sw_merged, token_info=_pp_token_info, ca=ca, now_ts=int(now_ts), wallet_tags=_wmeta, bullish_div_h1=_has_bullish_div, bullish_div_h4=_h4_div_mtf)
except Exception:
    pp_multi_res = None

if pp_multi_res:
    _conf = pp_multi_res.get("confluence", {})
    _tfr = pp_multi_res.get("timeframes", {})
    st.markdown("#### 🧭 Multi-Timeframe (30m / 1h / 4h / 12h)")
    _conf_color = {"golden": "#eab308", "dead_cat": "#ef4444", "sleeper": "#38bdf8", "normal": "#64748b"}.get(_conf.get("status"), "#64748b")
    st.markdown(f"""<div style="padding:10px 14px;border-radius:10px;background:{_conf_color}18;border-left:5px solid {_conf_color};margin-bottom:8px;"><b style="color:{_conf_color};font-size:1.05rem;">🎯 Confluence: {_conf.get('emoji','➖')} {_conf.get('label','-')}</b><span style="color:#475569;"> — {_conf.get('desc','')}</span><br><span style="font-size:0.82rem;color:#64748b;">Macro (4h/12h): <b>{_conf.get('macro_score',0):g}/100</b> · Micro (30m/1h): <b>{_conf.get('micro_score',0):g}/100</b></span></div>""", unsafe_allow_html=True)
    _mtf_rows = []
    for _tf in PREPUMP_TF_ORDER:
        _r_tf = _tfr.get(_tf)
        if not _r_tf:
            continue
        _m_tf = _r_tf.get("metrics", {})
        _tier_tf = _r_tf.get("tier", "neutral")
        _mtf_rows.append({"Timeframe": _tf, "Role": _r_tf.get("tf_role", "-"), "Score": _r_tf.get("score", 0), "Tier": f"{PREPUMP_TIER_BADGES.get(_tier_tf, '❓')} {_tier_tf.upper()}", "Confluence": f"{_conf.get('emoji','➖')} {_conf.get('label','-')}", "Compression %": f"{_r_tf.get('compression_pct', 0):.1f}%", "Buy/Sell Ratio": f"{_m_tf.get('ratio', 0):.2f}×", "Net Flow SOL": f"{_m_tf.get('net_sol', 0):+.2f}", "Pure Accum %": f"{_m_tf.get('pct_pure', 0)*100:.0f}%"})
    st.dataframe(pd.DataFrame(_mtf_rows), use_container_width=True, hide_index=True)

# Whale/dolphin held flow
profile_groups = split_wallet_profile_cohorts(full_profiles, whale_min_sol=WHALE_SOL)
cohort_summary = cohort_activity_summary(full_profiles, whale_min_sol=WHALE_SOL)
st.markdown("#### 🐋 Whale & 🐬 Dolphin held-flow")
wm1, wm2, wm3, wm4 = st.columns(4)
wm1.metric("🐋 Whale held buy", f"{cohort_summary['whale_buy']:,.1f} SOL", f"{cohort_summary['whale_buyers']} buyers")
wm2.metric("🐋 Whale pure sell", f"{cohort_summary['whale_sell']:,.1f} SOL", f"{cohort_summary['whale_sellers']} sellers")
wm3.metric("🐋 Whale net", f"{cohort_summary['whale_net']:+,.1f} SOL")
wm4.metric("🐋 vs 🐬 net", f"{cohort_summary['whale_net']:+,.0f} / {cohort_summary['dolphin_net']:+,.0f}")

