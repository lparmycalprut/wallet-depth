# -*- coding: utf-8 -*-
"""Deep CVD analysis for a user-selected 4-72h swap window.

Flags high-conviction whale accumulation, exports reports, and builds an
honest, ready-to-copy prompt for an external AI chat.
"""
import datetime as dtm
import io
import json
import math
import os
import sys
import time
import zoneinfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_prompt import build_ai_prompt
from core import (atomic_write_json, get_helius_keys, get_market,
                  helius_rpc, load_config,
                  get_holders as core_get_holders,
                  get_supply as core_get_supply)
from cvd import (MIN_SOL, WHALE_SOL, analysis_windows, classify_holders,
                 classify_swap, cohort_activity_summary, cohort_cvd_series,
                 conviction_split, detect_cohort_divergences,
                 detect_divergence, detect_no_buy_holders,
                 filter_swaps_by_time, fresh_wallet_growth,
                 pure_accumulator_growth, pure_distributor_growth,
                 get_gmgn_wallet_metadata,
                 split_wallet_profile_cohorts, summarize_swap_range,
                 wallet_profiles)
from monitor_alerts import (build_monitor_rows,
                           detect_stealth_accumulation, detect_distribution)
from prepump_detector import evaluate_prepump, compute_bullish_div
from signals import detect_prepump_and_record

st.set_page_config(page_title="CVD Analysis", page_icon="📊",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
h1 {font-size: 1.3rem !important;}
[data-testid="stMetric"] {padding: 0.2rem 0.5rem;
        background: rgba(128,128,128,0.07); border-radius: 8px;}
[data-testid="stMetricLabel"] {font-size: 0.72rem !important;}
[data-testid="stMetricValue"] {font-size: 1.1rem !important;}
[data-testid="stMetricDelta"] {font-size: 0.72rem !important;}
[data-testid="stCaptionContainer"] {font-size: 0.72rem !important;}
</style>""", unsafe_allow_html=True)

st.title("📊 CVD Deep Analysis")
st.caption("Pick a time window and analyze swap data for conviction, "
           "whale accumulation, and CVD trends.")

CONFIG = load_config()
helius_keys = tuple(get_helius_keys(config=CONFIG))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# CA can arrive via query param (?ca=...) from the LP Radar cards on the
# main page — prefill but do NOT auto-analyze, user picks hours first.
qp_ca = st.query_params.get("ca", "").strip()

ca = st.text_input("Contract Address", value=qp_ca,
                   placeholder="Solana CA...").strip()

col1, col3 = st.columns([1, 3])
with col1:
    hours = st.selectbox("Time window", [4, 6, 8, 12, 24, 36, 48, 72],
                         index=5, help="Fetch swaps for this many hours back")
use_gmgn_trades = True
with col3:
    run = st.button("📊 Analyze", type="primary",
                    use_container_width=True)

# ---------------------------------------------------------------------------
# Focus time range (WIB) — optional deep-dive into a specific window
# ---------------------------------------------------------------------------
WIB = zoneinfo.ZoneInfo("Asia/Jakarta")
_now_wib = dtm.datetime.now(WIB)
focus_start_ts = None
focus_end_ts = None
focus_enabled = False

with st.expander("🔎 Focus time range (WIB)", expanded=False):
    focus_enabled = st.checkbox(
        "Enable custom time range", value=False,
        help=("Focus analysis on a specific date/time window. "
              "All timestamps shown in WIB (Asia/Jakarta, UTC+7)."))
    if focus_enabled:
        _preset = st.radio(
            "Quick preset",
            ["Last 15m", "Last 1h", "Last 4h", "Custom"],
            horizontal=True, index=3)
        if _preset == "Last 15m":
            focus_end_ts = int(time.time())
            focus_start_ts = focus_end_ts - 15 * 60
            _s_wib = dtm.datetime.fromtimestamp(focus_start_ts, WIB)
            _e_wib = dtm.datetime.fromtimestamp(focus_end_ts, WIB)
            st.caption(f"▶ {_s_wib:%Y-%m-%d %H:%M} → {_e_wib:%Y-%m-%d %H:%M} WIB")
        elif _preset == "Last 1h":
            focus_end_ts = int(time.time())
            focus_start_ts = focus_end_ts - 3600
            _s_wib = dtm.datetime.fromtimestamp(focus_start_ts, WIB)
            _e_wib = dtm.datetime.fromtimestamp(focus_end_ts, WIB)
            st.caption(f"▶ {_s_wib:%Y-%m-%d %H:%M} → {_e_wib:%Y-%m-%d %H:%M} WIB")
        elif _preset == "Last 4h":
            focus_end_ts = int(time.time())
            focus_start_ts = focus_end_ts - 4 * 3600
            _s_wib = dtm.datetime.fromtimestamp(focus_start_ts, WIB)
            _e_wib = dtm.datetime.fromtimestamp(focus_end_ts, WIB)
            st.caption(f"▶ {_s_wib:%Y-%m-%d %H:%M} → {_e_wib:%Y-%m-%d %H:%M} WIB")
        else:  # Custom
            _cs1, _cs2 = st.columns(2)
            with _cs1:
                _start_date = st.date_input(
                    "Start date (WIB)", value=_now_wib.date())
                _start_time = st.time_input(
                    "Start time (WIB)",
                    value=_now_wib.replace(minute=0, second=0,
                                           microsecond=0).time())
            with _cs2:
                _end_date = st.date_input(
                    "End date (WIB)", value=_now_wib.date())
                _end_time = st.time_input(
                    "End time (WIB)", value=_now_wib.time())
            _start_wib = dtm.datetime.combine(
                _start_date, _start_time, tzinfo=WIB)
            _end_wib = dtm.datetime.combine(
                _end_date, _end_time, tzinfo=WIB)
            focus_start_ts = int(_start_wib.timestamp())
            focus_end_ts = int(_end_wib.timestamp())
            # validations
            if focus_start_ts >= focus_end_ts:
                st.error("Start must be before end.")
                focus_start_ts = focus_end_ts = None
            else:
                _now_ts = int(time.time())
                if focus_end_ts > _now_ts + 300:
                    st.warning("End time is in the future — clamping to now.")
                    focus_end_ts = _now_ts
                _range_h = (focus_end_ts - focus_start_ts) / 3600
                if focus_start_ts and focus_start_ts > _now_ts:
                    st.warning("Start time is in the future — no data.")
                    focus_start_ts = focus_end_ts = None

if not ca:
    st.info("Paste a CA. The fetch pulls the complete swap history for the "
            "selected time window — very active tokens can take a few "
            "minutes, progress is shown.")
    st.stop()

# Keep a completed analysis renderable across reruns. This is required for
# the Prompt to AI button: clicking it reruns Streamlit but must not force a
# second fetch or a second time-window selector.
source_key = "gmgn" if use_gmgn_trades else "helius"
_focus_key = ""
if focus_enabled and focus_start_ts and focus_end_ts:
    _focus_key = f"::f({focus_start_ts},{focus_end_ts})"
skey = f"cvd::{source_key}::{hours}h::{ca}{_focus_key}"
if not run and skey not in st.session_state:
    st.stop()
if (not helius_keys and not use_gmgn_trades and
        (run or skey not in st.session_state)):
    st.error("Helius API key missing (config.json / secrets).")
    st.stop()


@st.cache_data(ttl=120, show_spinner=False)
def get_pool(ca: str):
    """Resolve a CA through the shared identity-safe market helper."""
    market = get_market(ca)
    pools = market.get("pair_addresses") or []
    if not market or not pools:
        return None, None, None, None
    return (pools[0], market.get("symbol", "?"),
            float(market.get("price_usd") or 0),
            float(market.get("marketcap") or 0))


def full_fetch(ca: str, pool: str, cutoff_ts: int, *,
               use_gmgn: bool = False, from_ts=None, to_ts=None):
    """Fetch ALL swaps back to cutoff for the selected data source.

    When *from_ts*/*to_ts* are given and *use_gmgn* is True, the GMGN API
    receives ``from``/``to`` query params for efficient server-side filtering.
    """
    if use_gmgn:
        from cvd import fetch_swaps, get_gmgn_last_error
        _lbl = "GMGN focus range" if (from_ts and to_ts) else f"GMGN {hours}h"
        pbar = st.progress(0.0, text=f"Fetching {_lbl}…")
        try:
            swaps, _sig, _ts, _hit = fetch_swaps(
                "", pool or "", ca, stop_ts=cutoff_ts, max_pages=120,
                sleep=0.05, use_gmgn=True, from_ts=from_ts, to_ts=to_ts)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"GMGN Trades API fetch failed: {exc}")
            swaps = []
        finally:
            pbar.empty()
        err = get_gmgn_last_error()
        if err and not swaps:
            st.warning("GMGN Trades API gagal/kosong: " + err +
                       " Matikan checkbox untuk memakai Helius RPC.")
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
                st.warning(f"Fetch aborted after repeated API failures at "
                           f"page {page+1} — showing the "
                           f"{len(swaps):,} swaps retrieved so far.")
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
        frac = min(1.0, max(0.02, (time.time() - oldest) /
                            max(time.time() - cutoff_ts, 1)))
        pbar.progress(frac, text=f"Fetching… page {page+1} · "
                                 f"{len(swaps):,} swaps · reached "
                                 f"{dtm.datetime.utcfromtimestamp(oldest):%m-%d %H:%M} UTC "
                                 f"· {time.time()-t0:.0f}s")
        if done:
            break
        before = data[-1].get("signature")
        time.sleep(0.1)
    pbar.empty()
    return swaps


def load_funder_cache():
    try:
        with open(os.path.join(BASE, "funders_cache.json")) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_funder_cache(c):
    try:
        atomic_write_json(os.path.join(BASE, "funders_cache.json"), c,
                          separators=(",", ":"))
    except Exception as exc:
        print(f"WARN: failed to save funders_cache.json: {exc}",
              file=sys.stderr)


def lookup_first_tx(wallet, max_pages=2):
    before, last_sig, last_bt = None, None, None
    for _ in range(max_pages):
        params = [wallet, {"limit": 1000}]
        if before:
            params[1]["before"] = before
        try:
            res = helius_rpc(
                "getSignaturesForAddress", params, helius_keys,
                timeout=30) or []
        except Exception:
            return None, None
        if not res:
            break
        last_sig = res[-1]["signature"]
        last_bt = res[-1].get("blockTime")
        if len(res) < 1000:
            break
        before = last_sig
    else:
        return None, None
    if not last_sig:
        return None, None
    try:
        tx = helius_rpc(
            "getTransaction",
            [last_sig, {"encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0}],
            helius_keys, timeout=30)
        keys = tx["transaction"]["message"]["accountKeys"]
        fp = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
        return (fp if fp != wallet else None), last_bt
    except Exception:
        return None, last_bt


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_current_holder_rows(_helius_keys: tuple, ca: str):
    """Fetch current holders for no-buy holder detection.

    Returns ``(rows, supply)`` where rows carry owner, token balance, and
    pct_supply.  The leading underscore keeps Streamlit from hashing the
    API-key tuple contents.
    """
    supply, decimals = core_get_supply(_helius_keys, ca)
    hdf = core_get_holders(_helius_keys, ca)
    if hdf is None or hdf.empty:
        return [], float(supply or 0.0)
    hdf = hdf.copy()
    hdf["ui_amount"] = hdf["raw_amount"] / (10 ** int(decimals or 0))
    hdf = hdf[hdf["ui_amount"] > 0]
    hdf["pct_supply"] = (
        hdf["ui_amount"] / float(supply) * 100 if supply else 0.0)
    hdf = hdf.sort_values("ui_amount", ascending=False)
    rows = hdf[["owner", "ui_amount", "pct_supply"]].to_dict("records")
    return rows, float(supply or 0.0)


pool, symbol, price_now, mc_now = get_pool(ca)
if not pool:
    st.error("Token not found on DexScreener.")
    st.stop()

# Every analysis row must fit inside the selected/fetched time range.
WINDOWS = analysis_windows(hours)

if run or skey not in st.session_state:
    st.session_state.pop(f"ai_prompt::{skey}", None)
    cutoff = int(time.time()) - hours * 3600
    # If focus range needs a wider fetch window, extend cutoff
    if focus_enabled and focus_start_ts:
        _needed_h = math.ceil((time.time() - focus_start_ts) / 3600)
        _extended_h = max(hours, _needed_h)
        cutoff = int(time.time()) - _extended_h * 3600
    got = []
    if use_gmgn_trades:
        if focus_enabled and focus_start_ts and focus_end_ts:
            st.info("Fetching focus range from GMGN Trades API…")
            got = full_fetch(ca, pool, cutoff, use_gmgn=True,
                             from_ts=focus_start_ts, to_ts=focus_end_ts)
        else:
            st.info(f"Fetching last {hours}h from GMGN Trades API…")
            got = full_fetch(ca, pool, cutoff, use_gmgn=True)
        src = "GMGN Trades API"
    else:
        # Hybrid: watchlist tokens use the incremental store (top-up only
        # newest swaps). Others need a full historical Helius fetch.
        from watchlist import load_watchlist
        from cvd import update_token_cvd, get_recent_swaps
        src = "full fetch"
        if ca in load_watchlist():
            with st.spinner("Topping up incremental store (only new swaps)…"):
                try:
                    update_token_cvd(helius_keys, ca, pool, max_pages=200)
                except Exception:
                    pass
                got = get_recent_swaps(ca, hours)
                src = "incremental store"
        if not got:
            st.info(f"Fetching last {hours}h of swaps — very active tokens "
                    "can take several minutes. 💡 Watchlist tokens skip "
                    "this via the incremental store.")
            got = full_fetch(ca, pool, cutoff)
            src = "full fetch"
    st.session_state[skey] = {
        "swaps": got, "ts": time.time(), "src": src,
        "focus_start": focus_start_ts if focus_enabled else None,
        "focus_end": focus_end_ts if focus_enabled else None,
    }
swaps_all = st.session_state[skey]["swaps"]
fetched_at = st.session_state[skey]["ts"]
st.caption(f"Source: {st.session_state[skey].get('src', '?')}")
if not swaps_all:
    if use_gmgn_trades:
        from cvd import get_gmgn_last_error
        st.warning("No usable GMGN swaps ≥ 0.05 SOL found in the last "
                   f"{hours}h. {get_gmgn_last_error()}")
    else:
        st.warning(f"No swaps ≥ 0.05 SOL found in the last {hours}h.")
    st.stop()

# Deduplicate defensively to ensure clean calculations
_seen_all = {}
for s in swaps_all:
    if len(s) >= 4:
        _seen_all[(s[0], float(s[1]), int(s[2]), str(s[3]))] = s
swaps_all = [list(k) for k in sorted(_seen_all.keys(), key=lambda x: x[2])]

df = pd.DataFrame(swaps_all, columns=["side", "sol", "ts", "wallet"])
df["dt"] = pd.to_datetime(df["ts"], unit="s")
df["signed"] = df.apply(lambda r: r["sol"] if r["side"] == "buy"
                        else -r["sol"], axis=1)
# Anchor all windows to the fetch snapshot. A later Streamlit rerun (for
# example, Prompt to AI) must not make stale swaps appear to cover more time.
now_ts = fetched_at
covered_h = max(0.0, (now_ts - df["ts"].min()) / 3600)

# ---------------------------------------------------------------------------
# Multi-window analysis
# ---------------------------------------------------------------------------
win_stats = {}
for h in WINDOWS:
    seg = df[df["ts"] >= now_ts - h * 3600]
    if seg.empty:
        continue
    vb = float(seg.loc[seg["side"] == "buy", "sol"].sum())
    vs = float(seg.loc[seg["side"] == "sell", "sol"].sum())
    wseg = seg[seg["sol"] >= WHALE_SOL]
    wnet = float(wseg["signed"].sum())
    prof = wallet_profiles(list(seg[["side", "sol", "ts", "wallet"]]
                                .itertuples(index=False, name=None)))
    conv = conviction_split(prof, whale_min_sol=WHALE_SOL)
    net_pure = conv["pure_buy"] - conv["pure_sell"]
    if conv["conviction_pct"] >= 50 and net_pure > 0 and \
            conv["pure_buy"] >= 10:
        verdict = "💎 HIGH-CONVICTION ACCUM"
    elif conv["pure_sell"] >= 10 and net_pure < 0:
        verdict = "🩸 hard distribution"
    elif wnet < -5 and (vb - vs - wnet) > 5:
        verdict = "⚡ whales→retail dist"
    elif wnet > 5 and (vb - vs - wnet) < -5:
        verdict = "⚡ stealth accum (check conv!)"
    else:
        verdict = "— neutral/churn"
    win_stats[h] = {"swaps": len(seg), "buy": vb, "sell": vs,
                    "net": vb - vs, "whale_net": wnet,
                    "retail_net": vb - vs - wnet,
                    "pure_buy": conv["pure_buy"],
                    "pure_sell": conv["pure_sell"],
                    "conviction": conv["conviction_pct"],
                    "net_pure": net_pure, "verdict": verdict,
                    "profiles": prof}

# ---------------------------------------------------------------------------
# Header + big verdict
# ---------------------------------------------------------------------------
st.markdown(f"### ${symbol} · {len(df):,} swaps · {covered_h:.1f}h covered "
            f"· MC ${mc_now:,.0f}")

best_h = max(win_stats, key=lambda h: win_stats[h]["conviction"])
best = win_stats[best_h]
convs = [win_stats[h]["conviction"] for h in sorted(win_stats)]
conv_rising = len(convs) >= 2 and convs[0] > convs[-1]  # short > long window

is_candidate = (best["conviction"] >= 50 and best["net_pure"] > 0 and
                best["pure_buy"] >= 10)
if is_candidate:
    st.success(f"💎 **WHALE ACCUMULATION CANDIDATE** — conviction "
               f"{best['conviction']:.0f}% in the {best_h}h window, "
               f"{best['pure_buy']:.0f} SOL bought & held, net pure "
               f"{best['net_pure']:+.0f} SOL"
               + (" · conviction RISING toward recent windows ✅"
                  if conv_rising else ""))
elif conv_rising and win_stats[min(win_stats)]["conviction"] >= 35:
    st.warning(f"⏳ **Building** — conviction rising into recent windows "
               f"({convs[-1]:.0f}% → {convs[0]:.0f}%), not yet ≥50%. Watch.")
else:
    st.info(f"❌ Not an accumulation candidate — best conviction "
            f"{best['conviction']:.0f}% ({best_h}h). "
            f"{best['verdict']}")

# ---------------------------------------------------------------------------
# Multi-window table
# ---------------------------------------------------------------------------
# Compute whale/dolphin pure-held stats per window.
_cohort_stats = {}
for h in sorted(win_stats):
    _cohort_stats[h] = cohort_activity_summary(
        win_stats[h].get("profiles", {}), whale_min_sol=WHALE_SOL)

mw_rows = []
for h in sorted(win_stats):
    s = win_stats[h]
    _cs = _cohort_stats.get(h, {})
    mw_rows.append({
        "Window": f"{h}h", "Swaps": f"{s['swaps']:,}",
        "Net CVD": f"{s['net']:+,.0f}",
        "🐋 Whale": f"{s['whale_net']:+,.0f}",
        "🐋 Whale held": f"{_cs.get('whale_net', 0):+,.0f}",
        "🐬 Dolphin": f"{_cs.get('dolphin_net', 0):+,.0f}",
        "🐟 Retail": f"{s['retail_net']:+,.0f}",
        "💎 Pure buy": f"{s['pure_buy']:,.0f}",
        "🩸 Pure sell": f"{s['pure_sell']:,.0f}",
        "Net pure": f"{s['net_pure']:+,.0f}",
        "Conviction": f"{s['conviction']:.0f}%",
        "Verdict": s["verdict"],
    })
mw_df = pd.DataFrame(mw_rows)
st.dataframe(mw_df, use_container_width=True, hide_index=True)
st.caption("Read across the rows: healthy accumulation shows conviction "
           "RISING in shorter windows + 🩸 shrinking. All values in SOL.")

# conviction trend mini-chart
figc = go.Figure()
figc.add_trace(go.Scatter(
    x=[f"{h}h" for h in sorted(win_stats, reverse=True)],
    y=[win_stats[h]["conviction"] for h in sorted(win_stats, reverse=True)],
    mode="lines+markers+text",
    text=[f"{win_stats[h]['conviction']:.0f}%"
          for h in sorted(win_stats, reverse=True)],
    textposition="top center", line=dict(color="#38bdf8", width=3)))
figc.add_hline(y=50, line_dash="dot", line_color="#22c55e",
               annotation_text="entry bar 50%")
figc.add_hline(y=30, line_dash="dot", line_color="#ef4444",
               annotation_text="noise <30%")
figc.update_layout(height=220, margin=dict(t=10, b=0, l=0, r=0),
                   yaxis=dict(title="conviction %", range=[0, 100]),
                   title=dict(text=f"Conviction across windows ({hours}h → {WINDOWS[0]}h)",
                              font=dict(size=13)))
st.plotly_chart(figc, use_container_width=True,
                config={"displayModeBar": False})

# Full-window wallet profiles are reused by the cohort detail tables and by
# advanced divergence.  Keep this anchored to the selected fetch window.
full_profiles = win_stats[max(win_stats)]["profiles"]

# ---------------------------------------------------------------------------
# CVD chart for the selected window, bucketed hourly
# ---------------------------------------------------------------------------
g = df.set_index("dt").sort_index()
agg = g.groupby([pd.Grouper(freq="60min"), "side"])["sol"].sum() \
    .unstack(fill_value=0.0)
agg["buy"] = agg.get("buy", 0.0)
agg["sell"] = agg.get("sell", 0.0)
agg["delta"] = agg["buy"] - agg["sell"]
agg["cvd"] = agg["delta"].cumsum()
wagg = (g[g["sol"] >= WHALE_SOL]
        .groupby([pd.Grouper(freq="60min"), "side"])["sol"].sum()
        .unstack(fill_value=0.0)).reindex(agg.index, fill_value=0.0)
agg["wcvd"] = (wagg.get("buy", 0.0) - wagg.get("sell", 0.0)).cumsum()
agg["rcvd"] = agg["cvd"] - agg["wcvd"]

fig = go.Figure()
fig.add_trace(go.Scatter(x=agg.index, y=agg["cvd"], name="CVD (all)",
                         line=dict(color="#38bdf8", width=3)))
fig.add_trace(go.Scatter(x=agg.index, y=agg["wcvd"], name="🐋 Whale",
                         line=dict(color="#c084fc", width=2)))
fig.add_trace(go.Scatter(x=agg.index, y=agg["rcvd"], name="🐟 Retail",
                         line=dict(color="#64748b", width=1.5, dash="dot")))
fig.add_bar(x=agg.index, y=agg["delta"], name="Δ/h", yaxis="y2", opacity=0.3,
            marker=dict(color=["#22c55e" if v >= 0 else "#ef4444"
                               for v in agg["delta"]]))
fig.update_layout(height=320, margin=dict(t=25, b=0, l=0, r=0),
                  legend=dict(orientation="h", font=dict(size=10)),
                  yaxis=dict(title="cumulative SOL"),
                  yaxis2=dict(overlaying="y", side="right", visible=False),
                  title=dict(text=f"{hours}h CVD — hourly", font=dict(size=13)))
st.plotly_chart(fig, use_container_width=True,
                config={"displayModeBar": False})

# divergence on H1
try:
    r = requests.get(
        f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/"
        f"ohlcv/hour", params={"aggregate": 1, "limit": 60},
        headers={"accept": "application/json"}, timeout=20)
    lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
        .get("ohlcv_list") or []
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
    divs += [dict(d, src="whale") for d in
             detect_divergence(pser, list(agg["wcvd"]))]
    seen = set()
    for d in divs:
        k = (d["type"], d["kind"], d.get("src", "a"))
        if k in seen:
            continue
        seen.add(k)
        src = "Whale CVD" if d.get("src") == "whale" else "CVD"
        line = f"{d['kind']} {d['type']} divergence ({src}): {d['detail']}"
        div_lines.append(line)
        (st.success if d["type"] == "bullish" else st.error)(
            ("📈 " if d["type"] == "bullish" else "📉 ") + "**" +
            d["kind"].upper() + " " + d["type"].upper() + f" ({src})** — " +
            d["detail"])

# ---------------------------------------------------------------------------
# 🎯 Automatic Pre-Pump Trigger & Evaluation (30m window)
# ---------------------------------------------------------------------------
_wmeta = get_gmgn_wallet_metadata()
_has_bullish_div = any(d.get("type") == "bullish" for d in divs) if ("divs" in locals() and divs) else False
if not _has_bullish_div and pool:
    try:
        _has_bullish_div = compute_bullish_div(ca, pool)
    except Exception:
        pass

_pp_token_info = {
    "symbol": symbol,
    "price_usd": price_now,
    "mc": mc_now,
}

try:
    prepump_res = detect_prepump_and_record(
        ca, symbol, swaps_all,
        token_info=_pp_token_info,
        now_ts=int(now_ts),
        src="analyze",
        window_min=30,
        whale_min_sol=WHALE_SOL,
        wallet_tags=_wmeta,
        bullish_div=_has_bullish_div,
        pool=pool,
    )
except Exception:
    try:
        prepump_res = evaluate_prepump(
            swaps_all,
            token_info=_pp_token_info,
            ca=ca,
            now_ts=int(now_ts),
            window_min=30,
            whale_min_sol=WHALE_SOL,
            wallet_tags=_wmeta,
            bullish_div=_has_bullish_div,
        )
    except Exception:
        prepump_res = None

if prepump_res:
    st.markdown("#### 🎯 Pre-Pump Radar & Checker (30m window)")
    st.caption("Otomatis dievaluasi saat check CVD selesai: Volume Compression & Seller Exhaustion, "
               "Order-Flow Size Asymmetry, Pure Accumulator Conviction, dan Order-Flow Delta / Ignition. "
               "🎯 Imminent ≥75 · 👀 Forming 55–74 · ➖ Neutral <55.")

    pp_score = float(prepump_res.get("score", 0))
    pp_tier = prepump_res.get("tier", "neutral")
    pp_blocked = prepump_res.get("blocked", False)
    pp_stage = prepump_res.get("stage", "")
    pp_comp = float(prepump_res.get("compression_pct", 0))
    pp_pillars = prepump_res.get("pillars", {})
    pp_metrics = prepump_res.get("metrics", {})
    pp_reasons = prepump_res.get("reasons", {})

    badge_color = {
        "imminent": "#ef4444",
        "forming": "#fb923c",
        "neutral": "#64748b",
        "blocked": "#9ca3af",
    }.get(pp_tier, "#94a3b8")
    tier_emoji = {
        "imminent": "🚨",
        "forming": "👀",
        "neutral": "➖",
        "blocked": "🚫",
    }.get(pp_tier, "❓")

    pp_col1, pp_col2 = st.columns([1, 1])
    with pp_col1:
        st.markdown(
            f"""
            <div style="padding:12px 16px;border-radius:10px;background:{badge_color}18;border-left:5px solid {badge_color};margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <h3 style="margin:0;color:{badge_color};font-size:1.15rem;">{tier_emoji} {pp_tier.upper()}</h3>
                    <span style="font-size:1.25rem;font-weight:700;color:{badge_color};">{pp_score:.0f}/100</span>
                </div>
                <p style="margin:4px 0 0;font-size:0.88rem;color:#334155;"><b>Status:</b> {pp_stage}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if pp_blocked:
            st.error(f"🚫 **Safety Blocked**: {prepump_res.get('block_reason', '')}")
        else:
            st.success("✅ **Safety Check**: Lolos (rug, markup, & likuiditas)")

    with pp_col2:
        pm1, pm2 = st.columns(2)
        pm1.write(f"📉 **Compression:** `{pp_comp:.1f}%`")
        pm1.write(f"⚖️ **Avg Buy/Sell:** `{pp_metrics.get('avg_buy', 0):.2f}` / `{pp_metrics.get('avg_sell', 0):.2f}` SOL (`{pp_metrics.get('ratio', 0):.1f}×`)")
        pm1.write(f"🐋 **Whale Dumper:** `{'Ya ⚠️' if pp_metrics.get('whale_dumper') else 'Tidak ✅'}`")

        pm2.write(f"💰 **Flow 30m:** Net `{pp_metrics.get('net_sol', 0):+.2f}` SOL (B `{pp_metrics.get('buy_vol', 0):.1f}` / S `{pp_metrics.get('sell_vol', 0):.1f}`)")
        pm2.write(f"💎 **Pure Accum:** `{pp_metrics.get('pct_pure', 0)*100:.0f}%` ({pp_metrics.get('n_pure', 0)} wallet)")
        _active_terms = ", ".join(pp_metrics.get('active_terminals', [])) or "—"
        pm2.write(f"🔥 **Smart / Terminals:** `{pp_metrics.get('smart_count', 0)}` smart | `{_active_terms}`")

    # 4 Pilar Breakdown
    st.markdown("##### 📊 Breakdown 4 Pilar Pre-Pump")
    pcols = st.columns(4)
    for idx, (label, key, icon, desc) in enumerate([
        ("Compression", "compression", "📉", "Vol drop vs 4h baseline & no large dump"),
        ("Asymmetry", "asymmetry", "⚖️", "Avg buy vs avg sell ratio (MEV clean)"),
        ("Accumulation", "accum", "🐋", "Pure accumulator share & smart holders"),
        ("Ignition / Delta", "delta", "🔥", "Positive flow delta & terminal bots"),
    ]):
        val = float(pp_pillars.get(key, 0))
        with pcols[idx]:
            st.metric(
                label=f"{icon} {label}",
                value=f"{val:.0f}/25",
                help=f"{desc} | {pp_reasons.get(key, '')}",
            )

    with st.expander("🔍 Detail Metrics Pre-Pump (JSON)", expanded=False):
        st.json({
            "score": pp_score,
            "tier": pp_tier,
            "stage": pp_stage,
            "blocked": pp_blocked,
            "block_reason": prepump_res.get("block_reason", ""),
            "compression_pct": pp_comp,
            "bullish_div": prepump_res.get("bullish_div", False),
            "pillars": pp_pillars,
            "metrics": pp_metrics,
            "reasons": pp_reasons,
            "smart_tags_found": prepump_res.get("smart_tags_found", []),
            "token_info": prepump_res.get("token_info", {}),
        })

# Advanced divergence: price vs wallet-profile cohort CVD.  This keeps the
# old All/Whale-swap divergence intact, then adds a lower-noise explanation
# of which wallet cohort is actually confirming or rejecting the price move.
cohort_div_lines = []
cohort_cvd = cohort_cvd_series(
    swaps_all, full_profiles, [int(t.timestamp()) for t in agg.index],
    whale_min_sol=WHALE_SOL)
cohort_divs = []
if pser and all(p is not None for p in pser) and len(pser) >= 7:
    cohort_divs = detect_cohort_divergences(pser, cohort_cvd)

with st.expander("🧭 Advanced cohort divergence", expanded=False):
    st.caption("Advisory only: compares price pivots vs profile-based CVD "
               "(whale held, dolphin held, trader, pure distributor). "
               "Signals are filtered by minimum SOL movement to avoid dust.")
    if cohort_divs:
        seen = set()
        for d in cohort_divs:
            k = (d["type"], d["kind"], d.get("src"))
            if k in seen:
                continue
            seen.add(k)
            line = (f"{d['kind']} {d['type']} divergence "
                    f"({d['label']}): {d['detail']}")
            cohort_div_lines.append(line)
            (st.success if d["type"] == "bullish" else st.error)(
                ("📈 " if d["type"] == "bullish" else "📉 ") +
                "**" + d["kind"].upper() + " " +
                d["type"].upper() + f" ({d['label']})** — " +
                d["detail"])
    else:
        st.caption("No meaningful cohort divergence after volume filtering.")

    colors = {
        "whale_held": "#c084fc",
        "dolphin_held": "#38bdf8",
        "trader": "#facc15",
        "distributor": "#ef4444",
    }
    fig_cohort = go.Figure()
    for key, vals in cohort_cvd.get("series", {}).items():
        meta = cohort_cvd.get("meta", {}).get(key, {})
        if float(meta.get("volume") or 0.0) <= 0:
            continue
        fig_cohort.add_trace(go.Scatter(
            x=agg.index, y=vals, name=meta.get("label", key),
            line=dict(color=colors.get(key, "#94a3b8"), width=2)))
    if fig_cohort.data:
        fig_cohort.update_layout(
            height=240, margin=dict(t=15, b=0, l=0, r=0),
            legend=dict(orientation="h", font=dict(size=10)),
            yaxis=dict(title="cumulative SOL"),
            title=dict(text="Profile-cohort CVD", font=dict(size=12)))
        st.plotly_chart(fig_cohort, use_container_width=True,
                        config={"displayModeBar": False})

# ---------------------------------------------------------------------------
# Pure accumulators/distributors and holder-style cohorts in the full window
# ---------------------------------------------------------------------------
cohort_summary = cohort_activity_summary(
    full_profiles, whale_min_sol=WHALE_SOL)
profile_groups = split_wallet_profile_cohorts(
    full_profiles, whale_min_sol=WHALE_SOL)
whale_accs = profile_groups["whale_accumulators"][:15]
dolphin_accs = profile_groups["dolphin_accumulators"][:15]
whale_dists = profile_groups["whale_distributors"][:15]
dolphin_dists = profile_groups["dolphin_distributors"][:15]
light_holders = profile_groups["light_holders"][:20]
traders = profile_groups["traders"][:20]

st.markdown("#### 🐋 Whale & 🐬 Dolphin held-flow activity")
wm1, wm2, wm3, wm4 = st.columns(4)
wm1.metric("🐋 Whale held buy", f"{cohort_summary['whale_buy']:,.1f} SOL",
           f"{cohort_summary['whale_buyers']} buyers ≥{WHALE_SOL:g} SOL",
           delta_color="off")
wm2.metric("🐋 Whale pure sell", f"{cohort_summary['whale_sell']:,.1f} SOL",
           f"{cohort_summary['whale_sellers']} sellers ≥{WHALE_SOL:g} SOL",
           delta_color="off")
wm3.metric("🐋 Whale net", f"{cohort_summary['whale_net']:+,.1f} SOL",
           "buying" if cohort_summary["whale_net"] >= 0 else "selling",
           delta_color="normal" if cohort_summary["whale_net"] >= 0
           else "inverse")
wm4.metric("🐋 vs 🐬 net",
           f"{cohort_summary['whale_net']:+,.0f} / "
           f"{cohort_summary['dolphin_net']:+,.0f}",
           "held whale / held dolphin", delta_color="off")

dm1, dm2, dm3, dm4 = st.columns(4)
dm1.metric("🐬 Dolphin held buy",
           f"{cohort_summary['dolphin_buy']:,.1f} SOL",
           "1.0–3.0 SOL pure/light buyers", delta_color="off")
dm2.metric("🐬 Dolphin pure sell",
           f"{cohort_summary['dolphin_sell']:,.1f} SOL",
           "1.0–3.0 SOL sellers", delta_color="off")
dm3.metric("🐬 Dolphin net",
           f"{cohort_summary['dolphin_net']:+,.1f} SOL",
           "buying" if cohort_summary["dolphin_net"] >= 0 else "selling",
           delta_color="normal" if cohort_summary["dolphin_net"] >= 0
           else "inverse")
dm4.metric("🐬 Dolphin wallets",
           f"{cohort_summary['dolphin_buyers']} / "
           f"{cohort_summary['dolphin_sellers']}",
           "buyers / sellers", delta_color="off")
st.caption("Held buy = pure accumulator + light holder. Trader buy is "
           "listed separately because it is lower-conviction flow.")

# Age lookup covers every wallet displayed in the separated detail lists.
fcache = load_funder_cache()
_detail_items = (whale_accs + dolphin_accs + whale_dists + dolphin_dists +
                 light_holders + traders)
targets = [w for w, _, _ in _detail_items if w not in fcache]
if targets and helius_keys:
    apb = st.progress(0.0, text="Looking up wallet ages…")
    for i, w in enumerate(targets[:24]):
        fcache[w] = list(lookup_first_tx(w))
        apb.progress((i + 1) / min(len(targets), 24),
                     text=f"Wallet ages… {i+1}/{min(len(targets), 24)}")
        time.sleep(0.1)
    apb.empty()
    save_funder_cache(fcache)
elif targets:
    st.caption("Wallet age lookup skipped: Helius API key missing.")


def age_str(w):
    fu = fcache.get(w)
    if fu and fu[1]:
        ad = (time.time() - fu[1]) / 86400
        if ad < 1:
            return f"🐣 {ad*24:.0f}h"
        if ad < 3:
            return f"🐣 {ad:.1f}d"
        if ad < 14:
            return f"🌱 {ad:.0f}d"
        return f"🌳 {ad:.0f}d"
    if fu:
        return "🌳 aged*"
    return "—"


fmap = {}
for w, _d, _cohort in whale_accs + dolphin_accs + light_holders:
    fu = fcache.get(w)
    if fu and fu[0]:
        fmap.setdefault(fu[0], []).append(w)
same_funder = {w for ws in fmap.values() if len(ws) > 1 for w in ws}


def _held_pct(d):
    buy = float(d.get("buy") or 0.0)
    sell = float(d.get("sell") or 0.0)
    if buy <= 0:
        return "—"
    held = max(0.0, (buy - sell) / buy * 100)
    return f"{held:.0f}%"


def _detail_flags(w, d, cohort):
    bits = [cohort]
    if d.get("dca"):
        bits.append("🎯DCA")
    if w in same_funder:
        bits.append("⚠️same-funder")
    return " ".join(bits)


def _profile_rows(items):
    return [{
        "Wallet": f"https://solscan.io/account/{w}",
        "Buy": f"{float(d.get('buy') or 0):,.1f}",
        "Sell": f"{float(d.get('sell') or 0):,.1f}",
        "Net": f"{float(d.get('buy') or 0) - float(d.get('sell') or 0):+,.1f}",
        "Held %": _held_pct(d),
        "Swaps": int(d.get("n_buy") or 0) + int(d.get("n_sell") or 0),
        "Age": age_str(w),
        "Flags": _detail_flags(w, d, cohort),
    } for w, d, cohort in items]


def _show_profile_table(title, items, empty):
    rows = _profile_rows(items)
    if not rows:
        st.caption(empty)
        return []
    st.dataframe(pd.DataFrame(rows), use_container_width=True,
                 hide_index=True,
                 column_config={"Wallet": st.column_config.LinkColumn(
                     title, display_text=r"account/(.{6}).*")})
    return rows


with st.expander("#### Separate wallet lists", expanded=False):
    wpa, wpd = st.columns(2)
    with wpa:
        whale_acc_rows = _show_profile_table(
            f"🐋 Whale pure accumulators ({hours}h)", whale_accs,
            f"No whale pure accumulators in {hours}h.")
    with wpd:
        whale_dist_rows = _show_profile_table(
            f"🐋 Whale pure distributors ({hours}h)", whale_dists,
            f"No whale pure distributors in {hours}h.")

    dpa, dpd = st.columns(2)
    with dpa:
        dolphin_acc_rows = _show_profile_table(
            f"🐬 Dolphin pure accumulators ({hours}h)", dolphin_accs,
            f"No dolphin pure accumulators in {hours}h.")
    with dpd:
        dolphin_dist_rows = _show_profile_table(
            f"🐬 Dolphin pure distributors ({hours}h)", dolphin_dists,
            f"No dolphin pure distributors in {hours}h.")

    lha, tra = st.columns(2)
    with lha:
        light_rows = _show_profile_table(
            f"🛡️ Light holder details ({hours}h)", light_holders,
            f"No light holders ≥1 SOL in {hours}h.")
    with tra:
        trader_rows = _show_profile_table(
            f"📊 Trader details ({hours}h)", traders,
            f"No traders ≥1 SOL in {hours}h.")
accs = sorted(whale_accs + dolphin_accs + light_holders + traders,
              key=lambda x: -float(x[1].get("buy") or 0.0))[:15]
dists = sorted(whale_dists + dolphin_dists,
               key=lambda x: -float(x[1].get("sell") or 0.0))[:15]
acc_rows = whale_acc_rows + dolphin_acc_rows + light_rows + trader_rows
dist_rows = whale_dist_rows + dolphin_dist_rows

# ---------------------------------------------------------------------------
# 🌱 Fresh-wallet growth: wallets that buy and never sell >10% of holdings
# ---------------------------------------------------------------------------
st.markdown("#### 🌱 Fresh wallet growth — beli tanpa jual >10%")
st.caption("Fresh wallet = umur akun (tx pertama) di bawah ambang yang "
           "dipilih. Analisa menghitung wallet yang **hanya beli** dan "
           "tidak menjual >10% dari total belinya dalam timeframe ini "
           "(≈ pure accumulator + light holder, ≥90% kepemilikan "
           "dipertahankan). Detail wallet ada di tabel bawah.")

fw_c1, fw_c2 = st.columns([1, 1])
with fw_c1:
    fw_max_age_days = st.selectbox(
        "🌱 Max umur fresh wallet", [1, 3, 7, 14, 30], index=2,
        help="Wallet dengan umur (sejak tx pertama) di bawah batas ini "
             "dianggap FRESH.")
with fw_c2:
    fw_min_buy = st.number_input(
        "Min total beli (SOL)", min_value=0.05, max_value=500.0,
        value=0.1, step=0.05,
        help="Abaikan fresh wallet dengan total beli di bawah ini "
             "(anti dust).")

fw_max_h = max(win_stats)
fw_t0 = now_ts - fw_max_h * 3600
fw_window_swaps = [s for s in swaps_all if int(s[2]) >= fw_t0]

# Age lookups for fresh candidates not already cached by the lists above.
fw_candidates = [w for w, d in full_profiles.items()
                 if float(d.get("buy") or 0.0) > 0 and
                 float(d.get("sell") or 0.0) <=
                 0.10 * float(d.get("buy") or 0.0)]
fw_targets = [w for w in fw_candidates if w not in fcache]
if fw_targets and helius_keys:
    fw_pb = st.progress(0.0, text="Looking up fresh-wallet ages…")
    for i, w in enumerate(fw_targets[:30]):
        fcache[w] = list(lookup_first_tx(w))
        fw_pb.progress((i + 1) / min(len(fw_targets), 30),
                       text=f"Fresh-wallet ages… {i+1}/"
                            f"{min(len(fw_targets), 30)}")
        time.sleep(0.05)
    fw_pb.empty()
    save_funder_cache(fcache)
elif fw_targets:
    st.caption("Fresh-wallet age lookup skipped: Helius API key missing.")

fw = fresh_wallet_growth(fw_window_swaps, full_profiles, fcache,
                         max_age_days=float(fw_max_age_days),
                         sell_tol=0.10, min_buy_sol=float(fw_min_buy),
                         start_ts=fw_t0, end_ts=now_ts, bucket_s=3600)

if fw["count"]:
    _fw_pb_vol = float(win_stats[fw_max_h].get("pure_buy") or 0.0)
    _fw_share = (f"{fw['total_buy'] / _fw_pb_vol * 100:.0f}% dari "
                 f"pure buy window" if _fw_pb_vol > 0 else "—")
    fwm1, fwm2, fwm3, fwm4 = st.columns(4)
    fwm1.metric("🌱 Fresh wallets", f"{fw['count']:,}",
                f"{fw['n_pure_accum']} pure accum · "
                f"{fw['n_light_holder']} light holder")
    fwm2.metric("💰 Total beli", f"{fw['total_buy']:,.1f} SOL",
                f"avg {fw['avg_buy']:.2f} SOL/wallet", delta_color="off")
    fwm3.metric("🧊 Net hold", f"{fw['net_hold']:,.1f} SOL",
                f"{fw['n_zero_sell']} tanpa jual sama sekali",
                delta_color="off")
    fwm4.metric("🐋 / 🐬 / 🐟",
                f"{fw['whale_count']} / {fw['dolphin_count']} / "
                f"{fw['minnow_count']}",
                _fw_share, delta_color="off")
else:
    st.caption(f"Belum ada fresh wallet (umur ≤{fw_max_age_days}d, "
               f"beli ≥{fw_min_buy:g} SOL, jual ≤10% dari beli) dalam "
               f"{fw_max_h}h terakhir.")

if fw["series"]:
    fw_x = [dtm.datetime.fromtimestamp(r["bucket_ts"], WIB)
            for r in fw["series"]]
    fig_fw = go.Figure()
    fig_fw.add_bar(x=fw_x, y=[r["new_wallets"] for r in fw["series"]],
                   name="Fresh wallet baru / jam", yaxis="y2", opacity=0.35,
                   marker=dict(color="#38bdf8"))
    fig_fw.add_scatter(x=fw_x, y=[r["cum_wallets"] for r in fw["series"]],
                       name="Kumulatif wallet", mode="lines+markers",
                       line=dict(color="#22c55e", width=2.5))
    fig_fw.add_scatter(x=fw_x, y=[r["cum_buy_sol"] for r in fw["series"]],
                       name="Kumulatif beli (SOL)", mode="lines",
                       line=dict(color="#c084fc", width=2), yaxis="y2")
    fig_fw.update_layout(
        height=300, margin=dict(t=20, b=0, l=0, r=0),
        legend=dict(orientation="h", font=dict(size=10)),
        yaxis=dict(title="jumlah wallet", rangemode="tozero"),
        yaxis2=dict(overlaying="y", side="right", title="SOL",
                    rangemode="tozero"),
        title=dict(text=f"Pertumbuhan fresh wallet ({fw_max_h}h, "
                        f"jual ≤10% dari beli)", font=dict(size=13)))
    st.plotly_chart(fig_fw, use_container_width=True,
                    config={"displayModeBar": False})

if fw["unknown_age"] > 0:
    st.caption(f"ℹ️ {fw['unknown_age']} wallet beli-tanpa-jual-berlebih "
               "tidak punya data umur (age lookup gagal / tanpa Helius "
               "key) sehingga tidak ikut dihitung.")

# Same-funder flags for fresh wallets (reuses the freshly looked-up ages).
fw_fmap = dict(fmap)
for w, _d, _a, _fb in fw["wallets"]:
    fu = fcache.get(w)
    if fu and fu[0]:
        fw_fmap.setdefault(fu[0], []).append(w)
fw_same_funder = {w for ws in fw_fmap.values()
                  if len(ws) > 1 for w in ws}

fw_rows = []
for w, d, _age_days, fbt in fw["wallets"][:15]:
    buy = float(d.get("buy") or 0.0)
    sell = float(d.get("sell") or 0.0)
    held = max(0.0, (buy - sell) / buy * 100) if buy > 0 else 0.0
    bits = [d.get("profile", "")]
    if d.get("dca"):
        bits.append("🎯DCA")
    if w in same_funder or w in fw_same_funder:
        bits.append("⚠️same-funder")
    fw_rows.append({
        "Wallet": f"https://solscan.io/account/{w}",
        "Buy": f"{buy:,.2f}",
        "Sell": f"{sell:,.2f}",
        "Net": f"{buy - sell:+,.2f}",
        "Held %": f"{held:.0f}%",
        "Swaps": int(d.get("n_buy") or 0) + int(d.get("n_sell") or 0),
        "Age": age_str(w),
        "Beli pertama": (dtm.datetime.fromtimestamp(fbt, WIB)
                         .strftime("%m-%d %H:%M") if fbt else "—"),
        "Flags": " ".join(bits),
    })
if fw_rows:
    with st.expander("🌱 Detail fresh wallet — top 15 by total beli "
                     "(di bawah tabel dolphin pure accumulator)",
                     expanded=False):
        st.dataframe(pd.DataFrame(fw_rows), use_container_width=True,
                     hide_index=True,
                     column_config={"Wallet": st.column_config.LinkColumn(
                         "🌱 Fresh wallet detail",
                         display_text=r"account/(.{6}).*")})
else:
    st.caption(f"No fresh wallets in {fw_max_h}h.")

# ---------------------------------------------------------------------------
# Four-hour monitoring dashboard — all series use the same requested window.
# ---------------------------------------------------------------------------
_mon_bin_h = int((CONFIG or {}).get("monitor_bin_h", 4) or 4)
monitor_rows = build_monitor_rows(
    swaps_all, full_profiles, ca, hours, _mon_bin_h, now_ts)

st.markdown(f"### 📡 Monitor pertumbuhan {_mon_bin_h} jam")
st.caption(f"Pure accumulator = wallet beli ≥0.1 SOL & jual ≤10% beli. Pure distributor = wallet jual ≥0.1 SOL & beli ≤10% jual. Semua grafik dibagi bucket {_mon_bin_h} jam. Alert: 🟢 STEALTH ACCUM (accumulator↑ · conviction↑ · buy-dominan · distributor↓ · TX↓ · volume↓) dan 🔴 DISTRIBUSI (distributor↑ · accumulator↓ · conviction↓ · sell-dominan · TX↑ · volume↑).")
if monitor_rows:
    _mx = [dtm.datetime.fromtimestamp(r["ts"], WIB) for r in monitor_rows]
    _m1, _m2 = st.columns(2)
    with _m1:
        _fig = go.Figure()
        _fig.add_bar(x=_mx, y=[r["accum"] for r in monitor_rows], name="Akumulator kumulatif", marker_color="#22c55e")
        _fig.add_scatter(x=_mx, y=[r["volume"] for r in monitor_rows], name="Buy SOL kumulatif", yaxis="y2", line=dict(color="#a78bfa"))
        _fig.update_layout(title="Pure accumulator growth", height=280, margin=dict(t=35,b=0,l=0,r=0), yaxis2=dict(overlaying="y", side="right", title="SOL"), legend=dict(orientation="h"))
        st.plotly_chart(_fig, use_container_width=True, config={"displayModeBar": False})
    with _m2:
        _fig = go.Figure()
        _fig.add_scatter(x=_mx, y=[r["conviction"] for r in monitor_rows], name="Conviction", connectgaps=True, line=dict(color="#f59e0b", width=3))
        _fig.update_layout(title="Conviction dari waktu ke waktu", height=280, margin=dict(t=35,b=0,l=0,r=0), yaxis=dict(range=[0, 100], title="%"))
        st.plotly_chart(_fig, use_container_width=True, config={"displayModeBar": False})
    _fig = go.Figure()
    _fig.add_bar(x=_mx, y=[r["tx"] for r in monitor_rows], name="TX", marker_color="#38bdf8")
    _fig.add_scatter(x=_mx, y=[r["volume"] for r in monitor_rows], name="Volume SOL", yaxis="y2", line=dict(color="#f97316", width=2))
    _fig.update_layout(title=f"TX & volume growth / {_mon_bin_h} jam", height=280, margin=dict(t=35,b=0,l=0,r=0), yaxis2=dict(overlaying="y", side="right", title="SOL"), legend=dict(orientation="h"))
    st.plotly_chart(_fig, use_container_width=True, config={"displayModeBar": False})
    # Buy/Sell ratio per bucket — dominan BUY vs SELL (ditambahkan ke gabungan indikator)
    _fig = go.Figure()
    _bsr_y = []
    for r in monitor_rows:
        _b = r.get("buy_sell_ratio")
        if isinstance(_b, float) and _b == float("inf"):
            _bsr_y.append(9.0)
        elif isinstance(_b, (int, float)):
            _bsr_y.append(min(_b, 9.0))
        else:
            _bsr_y.append(None)
    _fig.add_scatter(x=_mx, y=_bsr_y, name="Buy/Sell ratio", mode="lines+markers",
                     line=dict(color="#34d399", width=3), marker=dict(size=7))
    _fig.add_hline(y=1.0, line_dash="dot", line_color="#94a3b8",
                   annotation_text="seimbang (1.0)")
    _fig.update_layout(title=f"Buy/Sell ratio / {_mon_bin_h} jam (≥1 = dominan BUY, capped 9)", height=280, margin=dict(t=35,b=0,l=0,r=0), yaxis=dict(title="buy ÷ sell (SOL)", rangemode="tozero"))
    st.plotly_chart(_fig, use_container_width=True, config={"displayModeBar": False})
    # Pure accumulator vs Pure distributor (cumulative wallets) — dinamika
    # akumulasi vs distribusi. Distributor naik = supply pressure / dump.
    _fig = go.Figure()
    _fig.add_scatter(x=_mx, y=[r["accum"] for r in monitor_rows],
                     name="Pure accumulator", mode="lines+markers",
                     line=dict(color="#22c55e", width=3))
    _fig.add_scatter(x=_mx, y=[r["dist"] for r in monitor_rows],
                     name="Pure distributor", mode="lines+markers",
                     line=dict(color="#f87171", width=3))
    _fig.update_layout(title=f"Pure accumulator vs distributor (cum wallets) / {_mon_bin_h} jam", height=280, margin=dict(t=35,b=0,l=0,r=0), yaxis=dict(title="wallet (cum)", rangemode="tozero"), legend=dict(orientation="h"))
    st.plotly_chart(_fig, use_container_width=True, config={"displayModeBar": False})
    # Indexed chart makes direction directly comparable despite different units.
    _fig = go.Figure()
    for _key, _label, _color in (("accum", "Pure accumulator", "#22c55e"),
                                  ("conviction", "Conviction", "#f59e0b"),
                                  ("tx", "TX", "#38bdf8"),
                                  ("volume", "Volume", "#f97316"),
                                  ("dist", "Pure distributor", "#f87171"),
                                  ("buy_sell_ratio", "Buy/Sell ratio", "#34d399")):
        _values = []
        for r in monitor_rows:
            v = r.get(_key)
            if _key == "buy_sell_ratio" and v == float("inf"):
                _values.append(None)
            else:
                _values.append(v)
        _base = next((v for v in _values if v not in (None, 0)), None)
        if _base is not None:
            _fig.add_scatter(x=_mx, y=[None if v is None else v / _base * 100 for v in _values],
                             name=_label, line=dict(color=_color, width=2),
                             connectgaps=True)
    _fig.update_layout(title="Gabungan indikator — index basis 100", height=330, margin=dict(t=35,b=0,l=0,r=0), yaxis=dict(title="Index (awal = 100)"), legend=dict(orientation="h"))
    st.plotly_chart(_fig, use_container_width=True, config={"displayModeBar": False})
    # --- Deteksi & alert (gabungan indikator basis 100) ---
    _stealth = detect_stealth_accumulation(monitor_rows)
    _dist = detect_distribution(monitor_rows)
    if _stealth["triggered"]:
        st.success(
            "🟢 **STEALTH ACCUMULATION** — basis 100: pure accumulator ↑, "
            "conviction ↑, Buy/Sell dominan BUY, pure distributor ↓, "
            "tapi TX & volume TURUN. Akumulasi diam tanpa hype "
            "(whale/insider menumpuk saat volume mengecil).")
    else:
        st.info("🔎 Akumulasi diam: " + _stealth["msg"] +
                ". (Belum semua syarat terpenuhi.)")
    if _dist["triggered"]:
        st.error(
            "🔴 **DISTRIBUSI** — basis 100: pure distributor ↑, "
            "pure accumulator ↓, conviction ↓, Buy/Sell dominan SELL, "
            "TX & volume NAIK. Supply pressure / dump sedang berlangsung.")
    else:
        st.info("🔎 Distribusi: " + _dist["msg"] +
                ". (Belum semua syarat terpenuhi.)")

# No-buy holder inspection is intentionally disabled for now.  It adds an
# expensive holder RPC call and is not part of the active CVD decision flow.
# The export report + wallets CSV still reference these lists; keep them
# empty so those sections render as "skipped" instead of raising a NameError.
silent_holder_rows = []
no_buy_meta_rows = []
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 🔎 Focus range deep analysis
# ---------------------------------------------------------------------------
_f_start = st.session_state[skey].get("focus_start")
_f_end = st.session_state[skey].get("focus_end")
if _f_start and _f_end and swaps_all:
    focus_swaps = filter_swaps_by_time(swaps_all, _f_start, _f_end)
    if focus_swaps:
        fs = summarize_swap_range(focus_swaps, whale_min_sol=WHALE_SOL)
        _f_accs = sorted([(w, d) for w, d in fs["profiles"].items()
                          if d["profile"] in ("pure_accum", "light_holder") and d["buy"] >= WHALE_SOL],
                         key=lambda x: -x[1]["buy"])[:10]
        _f_dists = sorted([(w, d) for w, d in fs["profiles"].items()
                           if d["profile"] == "pure_dist" and d["sell"] >= WHALE_SOL],
                          key=lambda x: -x[1]["sell"])[:10]
        _f_s_wib = dtm.datetime.fromtimestamp(_f_start, WIB)
        _f_e_wib = dtm.datetime.fromtimestamp(_f_end, WIB)
        _f_dur_min = (_f_end - _f_start) / 60

        st.markdown(f"### 🔎 Focus range: {_f_s_wib:%Y-%m-%d %H:%M} → "
                    f"{_f_e_wib:%H:%M} WIB ({_f_dur_min:.0f}m)")

        # Coverage check — does fetched data actually cover the range?
        if focus_swaps:
            _earliest = focus_swaps[0][2]
            _latest = focus_swaps[-1][2]
            _gap_start = _earliest > _f_start + 300  # 5 min tolerance
            _gap_end = _latest < _f_end - 300
            if _gap_start or _gap_end:
                _labels = []
                if _gap_start:
                    _labels.append("start not covered")
                if _gap_end:
                    _labels.append("end not covered")
                st.warning(
                    f"⚠️ Data coverage: SEBAGIAN — {', '.join(_labels)}. "
                    f"Earliest swap: {dtm.datetime.fromtimestamp(_earliest, WIB):%H:%M} WIB, "
                    f"Latest: {dtm.datetime.fromtimestamp(_latest, WIB):%H:%M} WIB.")

        # Summary metrics
        fm1, fm2, fm3, fm4 = st.columns(4)
        fm1.metric("Swaps", f"{fs['swaps']:,}",
                   delta=f"{fs['net_sol']:+.1f} SOL net")
        fm2.metric("Buy / Sell",
                   f"{fs['buy_sol']:+,.0f} / {fs['sell_sol']:+,.0f}")
        fm3.metric("🐋 Whale net", f"{fs['whale_net']:+,.1f}",
                   delta=f"buy {fs['whale_buy']:.0f} / sell {fs['whale_sell']:.0f}")
        fm4.metric("🐟 Retail net", f"{fs['retail_net']:+,.1f}")

        # Conviction + dominance
        _conv = fs["conviction"]
        _net_pure = _conv["pure_buy"] - _conv["pure_sell"]
        fm5, fm6, fm7, fm8, fm9 = st.columns(5)
        fm5.metric("💎 Pure buy", f"{_conv['pure_buy']:,.1f}")
        fm6.metric("🛡️ Light holder", f"{_conv['lh_buy']:,.1f}")
        fm7.metric("🩸 Pure sell", f"{_conv['pure_sell']:,.1f}")
        fm8.metric("Conviction", f"{_conv['conviction_pct']:.0f}%")
        fm9.metric("Dominance", f"{fs['dominance_pct']:.1f}%",
                   help="Largest single wallet's share of total volume")

        # Verdict for the focus range
        if _conv["conviction_pct"] >= 50 and _net_pure > 0 and \
                _conv["pure_buy"] >= 3:
            _fv = "💎 FOCUS: HIGH-CONVICTION ACCUMULATION"
            st.success(_fv)
        elif _conv["pure_sell"] >= 3 and _net_pure < 0:
            _fv = "🩸 FOCUS: DISTRIBUTION"
            st.error(_fv)
        elif fs["dominance_pct"] > 50:
            _fv = "⚠️ FOCUS: DOMINATED by 1-2 wallets — fake/churn risk"
            st.warning(_fv)
        elif _net_pure > 0:
            _fv = "🟢 FOCUS: Net buying, moderate conviction"
            st.info(_fv)
        else:
            _fv = "⚪ FOCUS: Neutral / churn"
            st.caption(_fv)

        # GMGN wallet metadata enrichment
        gmgn_meta = get_gmgn_wallet_metadata()
        if gmgn_meta:
            # Build enriched buyer/seller tables
            _tag_counts = {}
            _tok_tag_counts = {}
            _zero_balance_buys = 0
            _high_trade_wallets = 0
            _paper_hands = 0
            _bundlers = 0
            for w in set(fs["profiles"]):
                m = gmgn_meta.get(w)
                if not m:
                    continue
                for t in m.get("maker_tags", []):
                    _tag_counts[t] = _tag_counts.get(t, 0) + 1
                for t in m.get("maker_token_tags", []):
                    _tok_tag_counts[t] = _tok_tag_counts.get(t, 0) + 1
                if m.get("balance", -1) == 0:
                    _zero_balance_buys += 1
                if m.get("total_trade", 0) > 20:
                    _high_trade_wallets += 1
                if "paper_hands" in (m.get("maker_tags") or []):
                    _paper_hands += 1
                if "bundler" in (m.get("maker_token_tags") or []):
                    _bundlers += 1

            # GMGN flags summary
            st.markdown("#### 🏷️ GMGN wallet flags")
            _flag_cols = st.columns(4)
            _flag_cols[0].metric("Fresh wallets",
                                str(_tag_counts.get("fresh_wallet", 0)))
            _flag_cols[1].metric("Paper hands", str(_paper_hands))
            _flag_cols[2].metric("Bundlers", str(_bundlers))
            _flag_cols[3].metric("High-trade (bot?)",
                                str(_high_trade_wallets))

            if _zero_balance_buys > 0:
                st.warning(
                    f"⚠️ {_zero_balance_buys} buyer wallet(s) have "
                    "balance=0 after buying — possible sold-out / exit "
                    "liquidity / bot.")

            # Enriched top buyers table
            if fs["top_buyers"]:
                _brows = []
                for w, sol in fs["top_buyers"]:
                    m = gmgn_meta.get(w) or {}
                    tags = ", ".join(m.get("maker_tags", [])) or "—"
                    tok_tags = ", ".join(m.get("maker_token_tags", [])) or "—"
                    bal = m.get("balance", "")
                    tt = m.get("total_trade", "")
                    hb = m.get("history_bought_amount", 0)
                    hs = m.get("history_sold_amount", 0)
                    _brows.append({
                        "Wallet": f"https://solscan.io/account/{w}",
                        "Bought (SOL)": f"{sol:,.2f}",
                        "Tags": tags,
                        "Token tags": tok_tags,
                        "Balance": f"{bal}" if bal != "" else "—",
                        "Trades": f"{tt}" if tt != "" else "—",
                        "Hist bought": f"{hb:,.2f}" if hb else "—",
                        "Hist sold": f"{hs:,.2f}" if hs else "—",
                        "Hold?" : ("✅" if (isinstance(bal, (int, float))
                                            and bal > 0) else
                                   ("❌ sold" if bal == 0 else "—")),
                    })
                st.dataframe(
                    pd.DataFrame(_brows), use_container_width=True,
                    hide_index=True,
                    column_config={"Wallet": st.column_config.LinkColumn(
                        "🔎 Top buyers (focus)", display_text=r"account/(.{6}).*")})

            # 🔍 Focus Buyers Holdings & Retention Status (Only buyers in this timeframe checked)
            if fs["top_buyers"]:
                st.markdown("#### 🔎 Focus Buyers Holdings & Retention Status")
                st.caption("Menunjukkan status kepemilikan pembeli dari timeframe ini setelah difilter (no dust <$5, no bots, no churn).")
                
                from cvd import get_sol_price
                _sol_price = get_sol_price() or 150.0
                _dust_limit_sol = 5.0 / _sol_price # $5 limit
                
                _ret_rows = []
                for w, sol in fs["top_buyers"]:
                    # Filter dust < $5
                    if sol < _dust_limit_sol:
                        continue
                        
                    m = gmgn_meta.get(w) or {}
                    tags = [t.lower() for t in m.get("maker_tags", [])]
                    tok_tags = [t.lower() for t in m.get("maker_token_tags", [])]
                    
                    # Filter bots and churn
                    is_bot = m.get("total_trade", 0) > 20 or any("bot" in t for t in tags + tok_tags) or any("churn" in t for t in tags + tok_tags)
                    if is_bot:
                        continue
                        
                    bal = m.get("balance", -1.0)
                    hb = m.get("history_bought_amount", 0.0)
                    hs = m.get("history_sold_amount", 0.0)
                    
                    # Compute status
                    if bal == 0 or (hb > 0 and bal / hb <= 0.15):
                        status = "🔴 Jual Sebagian Besar / Habis"
                        status_color = "#ef4444"
                    elif hb > 0 and bal / hb >= 0.95 and m.get("total_trade", 0) > 1 and hs == 0:
                        status = "🟢 Tambah Muatan (Accumulating)"
                        status_color = "#22c55e"
                    elif hb > 0 and bal / hb >= 0.80:
                        status = "🟢 Masih Hold"
                        status_color = "#22c55e"
                    elif hb > 0 and 0.15 < bal / hb < 0.80:
                        status = "🟡 Jual Sebagian"
                        status_color = "#facc15"
                    else:
                        status = "🟢 Masih Hold" # standard fallback for hold
                        status_color = "#22c55e"
                        
                    tags_str = ", ".join(m.get("maker_tags", [])) or "—"
                    
                    _ret_rows.append({
                        "Wallet": f"https://solscan.io/account/{w}",
                        "Beli di Focus (SOL)": f"{sol:,.2f}",
                        "Current Balance": f"{bal:,.2f}" if isinstance(bal, (int, float)) and bal >= 0 else "—",
                        "Hist Bought": f"{hb:,.2f}" if hb else "—",
                        "Hist Sold": f"{hs:,.2f}" if hs else "—",
                        "Tags": tags_str,
                        "Status": f"<span style='color:{status_color};font-weight:700;'>{status}</span>"
                    })
                    
                if _ret_rows:
                    st.dataframe(
                        pd.DataFrame(_ret_rows), use_container_width=True,
                        hide_index=True,
                        column_config={"Wallet": st.column_config.LinkColumn(
                            "Buyer", display_text=r"account/(.{6}).*")})
                else:
                    st.info("Tidak ada pembeli yang memenuhi kriteria filter (semua disaring sebagai dust, bot, atau churn).")

            # Enriched top sellers table
            if fs["top_sellers"]:
                _srows = []
                for w, sol in fs["top_sellers"]:
                    m = gmgn_meta.get(w) or {}
                    tags = ", ".join(m.get("maker_tags", [])) or "—"
                    tok_tags = ", ".join(m.get("maker_token_tags", [])) or "—"
                    rp = m.get("realized_profit", 0)
                    _srows.append({
                        "Wallet": f"https://solscan.io/account/{w}",
                        "Sold (SOL)": f"{sol:,.2f}",
                        "Tags": tags,
                        "Token tags": tok_tags,
                        "Realized P/L": f"{rp:+,.2f}" if rp else "—",
                    })
                st.dataframe(
                    pd.DataFrame(_srows), use_container_width=True,
                    hide_index=True,
                    column_config={"Wallet": st.column_config.LinkColumn(
                        "🔎 Top sellers (focus)", display_text=r"account/(.{6}).*")})

            # Churn / fake verdict enrichment
            _churn_signals = []
            if _paper_hands >= max(2, fs["wallets"] * 0.2):
                _churn_signals.append(
                    f"{_paper_hands} paper_hands wallets")
            if _bundlers >= max(2, fs["wallets"] * 0.15):
                _churn_signals.append(
                    f"{_bundlers} bundler wallets")
            if _high_trade_wallets >= max(2, fs["wallets"] * 0.15):
                _churn_signals.append(
                    f"{_high_trade_wallets} high-trade (bot/churn) wallets")
            if _zero_balance_buys >= max(2, fs["buyers"] * 0.3):
                _churn_signals.append(
                    f"{_zero_balance_buys} buyers with balance=0")
            if fs["dominance_pct"] > 40:
                _churn_signals.append(
                    f"single-wallet dominance {fs['dominance_pct']:.0f}%")
            if _churn_signals:
                st.warning(
                    "🚨 **Fake/churn/exit-liquidity signals:** " +
                    "; ".join(_churn_signals))
            else:
                st.success("✅ No major fake/churn flags detected in focus range.")
        else:
            st.caption("GMGN metadata not available (Helius source or "
                       "empty GMGN response). Enable GMGN Trades API for "
                       "wallet tags, balance, and churn detection.")

        # Top net wallets (cross-side)
        if fs["top_net_wallets"]:
            st.markdown("#### 📊 Top net wallets (buy − sell)")
            _nrows = []
            for w, net in fs["top_net_wallets"]:
                p = fs["profiles"].get(w, {})
                profile = p.get("profile", "?")
                _nrows.append({
                    "Wallet": f"https://solscan.io/account/{w}",
                    "Net (SOL)": f"{net:+,.2f}",
                    "Buy": f"{p.get('buy', 0):,.2f}",
                    "Sell": f"{p.get('sell', 0):,.2f}",
                    "Profile": profile,
                    "Swaps": p.get("n_buy", 0) + p.get("n_sell", 0),
                })
            st.dataframe(
                pd.DataFrame(_nrows), use_container_width=True,
                hide_index=True,
                column_config={"Wallet": st.column_config.LinkColumn(
                    "Net wallets", display_text=r"account/(.{6}).*")})

    elif focus_enabled:
        _f_s_wib = dtm.datetime.fromtimestamp(_f_start, WIB)
        _f_e_wib = dtm.datetime.fromtimestamp(_f_end, WIB)
        st.warning(
            f"⚠️ No swaps found in focus range "
            f"{_f_s_wib:%Y-%m-%d %H:%M} → {_f_e_wib:%H:%M} WIB. "
            "Data may not cover this period — TIDAK TERCAKUP.")

# ---------------------------------------------------------------------------
# 🤖 Ready-to-copy prompt for a free AI chat
# ---------------------------------------------------------------------------
prompt_wallets = []
_role_name = {
    "pure_accum": "pure accumulator",
    "light_holder": "light holder",
    "trader": "trader",
    "pure_dist": "pure distributor",
}
for wallet, profile, cohort in accs + dists:
    flags = (("DCA; " if profile.get("dca") else "") +
             ("same-funder" if wallet in same_funder else "")).strip("; ")
    prompt_wallets.append({
        "wallet": wallet,
        "role": f"{_role_name.get(profile.get('profile'), 'wallet')} "
                f"({cohort})",
        "buy": profile["buy"], "sell": profile["sell"],
        "swaps": profile["n_buy"] + profile["n_sell"],
        "age": age_str(wallet), "flags": flags,
    })

prompt_key = f"ai_prompt::{skey}"
if st.button("🤖 Prompt to AI", use_container_width=True,
             help="Build a copy-ready Indonesian prompt for DeepSeek"):
    if focus_enabled and _f_start and _f_end and 'focus_swaps' in locals() and focus_swaps:
        # Use focus-range specific stats for the AI Prompt
        _f_dur_h = (_f_end - _f_start) / 3600
        
        # Simple stats over focus swaps
        _focus_win_stats = {
            _f_dur_h: {
                "swaps": len(focus_swaps),
                "net": fs["net_sol"],
                "whale_net": fs["whale_net"],
                "retail_net": fs["retail_net"],
                "pure_buy": fs["conviction"]["pure_buy"],
                "pure_sell": fs["conviction"]["pure_sell"],
                "net_pure": fs["conviction"]["pure_buy"] - fs["conviction"]["pure_sell"],
                "conviction": fs["conviction"]["conviction_pct"],
                "verdict": _fv,
            }
        }
        
        # Build focus prompt wallets
        _focus_prompt_wallets = []
        for wallet, profile in _f_accs:
            _focus_prompt_wallets.append({
                "wallet": wallet, "role": "pure accumulator",
                "buy": profile["buy"], "sell": profile["sell"],
                "swaps": profile["n_buy"] + profile["n_sell"],
                "age": age_str(wallet),
                "flags": "DCA" if profile.get("dca") else "",
            })
        for wallet, profile in _f_dists:
            _focus_prompt_wallets.append({
                "wallet": wallet, "role": "pure distributor",
                "buy": profile["buy"], "sell": profile["sell"],
                "swaps": profile["n_buy"] + profile["n_sell"],
                "age": age_str(wallet),
                "flags": "DCA" if profile.get("dca") else "",
            })
            
        st.session_state[prompt_key] = build_ai_prompt(
            symbol=symbol, ca=ca, requested_hours=_f_dur_h,
            available_hours=_f_dur_h, swaps=focus_swaps,
            window_stats=_focus_win_stats, wallet_rows=_focus_prompt_wallets,
            price_now=price_now, market_cap=mc_now, now_ts=_f_end)
    else:
        st.session_state[prompt_key] = build_ai_prompt(
            symbol=symbol, ca=ca, requested_hours=hours,
            available_hours=covered_h, swaps=swaps_all,
            window_stats=win_stats, wallet_rows=prompt_wallets,
            price_now=price_now, market_cap=mc_now, now_ts=now_ts)
if prompt_key in st.session_state:
    st.markdown("### 🤖 Prompt siap salin")
    st.caption("Klik ikon copy pada blok berikut, lalu tempel ke DeepSeek. "
               "Prompt sudah membawa definisi, batas data, urutan waktu, "
               "dan umur dompet; tidak ada data yang dikirim otomatis.")
    st.code(st.session_state[prompt_key], language=None)
    st.markdown("[Buka DeepSeek gratis ↗](https://chat.deepseek.com/)")

# ---------------------------------------------------------------------------
# 📄 Exportable report
# ---------------------------------------------------------------------------
st.markdown("### 📄 Export report")
now_str = dtm.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
wib_str = (dtm.datetime.utcnow() + dtm.timedelta(hours=7)) \
    .strftime("%Y-%m-%d %H:%M WIB")

rep = io.StringIO()
rep.write(f"# CVD Report — ${symbol}\n\n")
rep.write(f"- CA: `{ca}`\n- Generated: {now_str} ({wib_str})\n")
rep.write(f"- Price: ${price_now:.10f} · MC: ${mc_now:,.0f}\n")
rep.write(f"- Data: {len(df):,} swaps, {covered_h:.1f}h covered "
          f"(fetch: {hours}h window)\n\n")
rep.write("## Verdict\n\n")
if is_candidate:
    rep.write(f"**💎 WHALE ACCUMULATION CANDIDATE** — conviction "
              f"{best['conviction']:.0f}% ({best_h}h), pure buy "
              f"{best['pure_buy']:.0f} SOL, net pure "
              f"{best['net_pure']:+.0f} SOL"
              + (", conviction rising ✅" if conv_rising else "") + "\n\n")
else:
    rep.write(f"Not a candidate — best conviction "
              f"{best['conviction']:.0f}% ({best_h}h). "
              f"{best['verdict']}\n\n")
rep.write("## Windows\n\n")
rep.write("| Window | Swaps | Net CVD | Whale swap | Whale held | "
          "Dolphin held | Retail | Pure buy | Pure sell | Net pure | "
          "Conviction | Verdict |\n")
rep.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
for h in sorted(win_stats):
    s = win_stats[h]
    _cs = _cohort_stats.get(h, {})
    rep.write(f"| {h}h | {s['swaps']:,} | {s['net']:+,.0f} | "
              f"{s['whale_net']:+,.0f} | "
              f"{_cs.get('whale_net', 0):+,.0f} | "
              f"{_cs.get('dolphin_net', 0):+,.0f} | "
              f"{s['retail_net']:+,.0f} | {s['pure_buy']:,.0f} | "
              f"{s['pure_sell']:,.0f} | {s['net_pure']:+,.0f} | "
              f"{s['conviction']:.0f}% | {s['verdict']} |\n")
if div_lines:
    rep.write(f"\n## Divergences (H1, {hours}h)\n\n")
    for line in div_lines:
        rep.write(f"- {line}\n")
if cohort_div_lines:
    rep.write(f"\n## Advanced cohort divergences (H1, {hours}h)\n\n")
    for line in cohort_div_lines:
        rep.write(f"- {line}\n")
if prepump_res:
    rep.write(f"\n## 🎯 Pre-Pump Evaluation (30m window)\n\n")
    rep.write(f"- Score: **{pp_score:.0f}/100** ({pp_tier.upper()})\n")
    rep.write(f"- Status / Stage: {pp_stage}\n")
    rep.write(f"- Safety Check: {'BLOCKED: ' + prepump_res.get('block_reason', '') if pp_blocked else 'Passed'}\n")
    rep.write(f"- Compression: {pp_comp:.1f}% · Net Flow (30m): {pp_metrics.get('net_sol', 0):+.2f} SOL (Buy: {pp_metrics.get('buy_vol', 0):.2f}, Sell: {pp_metrics.get('sell_vol', 0):.2f})\n")
    rep.write(f"- Order Asymmetry: Avg Buy {pp_metrics.get('avg_buy', 0):.2f} SOL vs Sell {pp_metrics.get('avg_sell', 0):.2f} SOL ({pp_metrics.get('ratio', 0):.2f}×)\n")
    rep.write(f"- Pure Accumulators: {pp_metrics.get('pct_pure', 0)*100:.0f}% volume hold ({pp_metrics.get('n_pure', 0)} wallets, {pp_metrics.get('smart_count', 0)} smart wallets)\n")
    rep.write(f"- Pillars: P1 Compression={pp_pillars.get('compression', 0):.0f}/25 · P2 Asymmetry={pp_pillars.get('asymmetry', 0):.0f}/25 · P3 Accum={pp_pillars.get('accum', 0):.0f}/25 · P4 Delta={pp_pillars.get('delta', 0):.0f}/25\n")
rep.write(f"\n## Whale & Dolphin held-flow activity ({hours}h)\n\n")
rep.write(f"- Whale held buy: {cohort_summary['whale_buy']:,.1f} SOL · "
          f"pure sell: {cohort_summary['whale_sell']:,.1f} SOL · "
          f"net: {cohort_summary['whale_net']:+,.1f} SOL\n")
rep.write(f"- Dolphin held buy: {cohort_summary['dolphin_buy']:,.1f} SOL · "
          f"pure sell: {cohort_summary['dolphin_sell']:,.1f} SOL · "
          f"net: {cohort_summary['dolphin_net']:+,.1f} SOL\n")
rep.write(f"- Whale / dolphin net ratio: "
          f"{cohort_summary['whale_net']:+,.0f} / "
          f"{cohort_summary['dolphin_net']:+,.0f}\n")


def _write_detail_section(title, rows):
    rep.write(f"\n## {title}\n\n")
    if not rows:
        rep.write("None.\n")
        return
    rep.write("| Wallet | Buy | Sell | Net | Held % | Swaps | Age | Flags |\n")
    rep.write("|---|---|---|---|---|---|---|---|\n")
    for r_ in rows:
        w = r_["Wallet"].split("account/")[-1]
        rep.write(f"| [{w[:8]}…]({r_['Wallet']}) | {r_['Buy']} | "
                  f"{r_['Sell']} | {r_['Net']} | {r_['Held %']} | "
                  f"{r_['Swaps']} | {r_['Age']} | {r_['Flags']} |\n")


_write_detail_section(f"Whale pure accumulators ({hours}h)", whale_acc_rows)
_write_detail_section(f"Whale pure distributors ({hours}h)", whale_dist_rows)
_write_detail_section(f"Dolphin pure accumulators ({hours}h)",
                      dolphin_acc_rows)
_write_detail_section(f"Dolphin pure distributors ({hours}h)",
                      dolphin_dist_rows)
_write_detail_section(f"Light holder details ({hours}h)", light_rows)
_write_detail_section(f"Trader details ({hours}h)", trader_rows)

if fw["count"]:
    rep.write(f"\\n## Fresh wallet growth — beli tanpa jual >10% "
              f"({hours}h)\\n\\n")
    rep.write(f"- Fresh wallets (umur ≤{fw_max_age_days}d, "
              f"beli ≥{fw_min_buy:g} SOL, jual ≤10% dari beli): "
              f"**{fw['count']}**\\n")
    rep.write(f"- Total beli: {fw['total_buy']:,.1f} SOL · "
              f"Net hold: {fw['net_hold']:,.1f} SOL · "
              f"avg {fw['avg_buy']:.2f} SOL/wallet\\n")
    rep.write(f"- Komposisi: {fw['n_pure_accum']} pure accum · "
              f"{fw['n_light_holder']} light holder · "
              f"{fw['n_zero_sell']} tanpa jual sama sekali · "
              f"🐋{fw['whale_count']} / 🐬{fw['dolphin_count']} / "
              f"🐟{fw['minnow_count']}\\n")
_write_detail_section(f"Fresh wallet growth — beli tanpa jual >10% "
                      f"({hours}h, umur ≤{fw_max_age_days}d)",
                      fw_rows)

if silent_holder_rows or no_buy_meta_rows:
    rep.write(f"\n## Holders with no buy in window ({hours}h)\n\n")
    if silent_holder_rows:
        rep.write("### Current whale/dolphin holders\n\n")
        rep.write("| Wallet | Tier | Balance | % Supply | Window sell | "
                  "Window profile |\n")
        rep.write("|---|---|---|---|---|---|\n")
        for r_ in silent_holder_rows:
            w = r_["Wallet"].split("account/")[-1]
            rep.write(f"| [{w[:8]}…]({r_['Wallet']}) | {r_['Tier']} | "
                      f"{r_['Balance']} | {r_['% Supply']} | "
                      f"{r_['Window sell']} | {r_['Window profile']} |\n")
    if no_buy_meta_rows:
        rep.write("\n### GMGN sell-only wallets still holding\n\n")
        rep.write("| Wallet | Cohort | Window sell | Token balance | "
                  "Swaps | Tags |\n")
        rep.write("|---|---|---|---|---|---|\n")
        for r_ in no_buy_meta_rows:
            w = r_["wallet"]
            tags = ", ".join(r_["tags"] + r_["token_tags"]) or "—"
            rep.write(f"| [{w[:8]}…](https://solscan.io/account/{w}) | "
                      f"{r_['cohort']} | {r_['sell']:,.2f} | "
                      f"{r_['balance']:,.2f} | {r_['n_sell']} | "
                      f"{tags} |\n")
# Focus range section (if enabled)
_f_s = st.session_state[skey].get("focus_start")
_f_e = st.session_state[skey].get("focus_end")
if _f_s and _f_e:
    _fs_swaps = filter_swaps_by_time(swaps_all, _f_s, _f_e)
    if _fs_swaps:
        _fs = summarize_swap_range(_fs_swaps, whale_min_sol=WHALE_SOL)
        _fs_wib_s = dtm.datetime.fromtimestamp(_f_s, WIB)
        _fs_wib_e = dtm.datetime.fromtimestamp(_f_e, WIB)
        rep.write(f"\n## Focus Range ({_fs_wib_s:%Y-%m-%d %H:%M} → "
                  f"{_fs_wib_e:%H:%M} WIB)\n\n")
        rep.write(f"- Swaps: {_fs['swaps']:,}\n")
        rep.write(f"- Buy: {_fs['buy_sol']:+,.1f} SOL · "
                  f"Sell: {_fs['sell_sol']:+,.1f} SOL · "
                  f"Net: {_fs['net_sol']:+,.1f}\n")
        rep.write(f"- Whale net: {_fs['whale_net']:+,.1f} · "
                  f"Retail net: {_fs['retail_net']:+,.1f}\n")
        _fconv = _fs["conviction"]
        rep.write(f"- Conviction: {_fconv['conviction_pct']:.0f}% · "
                  f"Dominance: {_fs['dominance_pct']:.1f}%\n")
        if _fs["top_buyers"]:
            rep.write("\n### Top buyers (focus)\n\n")
            rep.write("| Wallet | SOL | Profile |\n|---|---|---|\n")
            for _w, _sol in _fs["top_buyers"][:5]:
                _p = _fs["profiles"].get(_w, {}).get("profile", "?")
                rep.write(f"| {_w[:8]}… | {_sol:,.2f} | {_p} |\n")
        if _fs["top_sellers"]:
            rep.write("\n### Top sellers (focus)\n\n")
            rep.write("| Wallet | SOL | Profile |\n|---|---|---|\n")
            for _w, _sol in _fs["top_sellers"][:5]:
                _p = _fs["profiles"].get(_w, {}).get("profile", "?")
                rep.write(f"| {_w[:8]}… | {_sol:,.2f} | {_p} |\n")

rep.write("\n---\n*Flow whale = wallet/side ≥3 SOL in-window · "
          "holder-rank whale = top 1% current holders · "
          "pure = one-way (≤5% tol) · conviction = % of whale-size buys "
          "that were held · generated by Wallet Depth by Threshold*\n")
report_md = rep.getvalue()

csv_buf = io.StringIO()
pd.DataFrame([{"window_h": h, **{k: v for k, v in s.items()
                                 if k != "profiles"}}
              for h, s in sorted(win_stats.items())]).to_csv(
    csv_buf, index=False)

e1, e2, e3 = st.columns(3)
e1.download_button("⬇️ Report (Markdown)", report_md,
                   file_name=f"{symbol}_cvd_report.md",
                   mime="text/markdown", use_container_width=True)
e2.download_button("⬇️ Windows (CSV)", csv_buf.getvalue(),
                   file_name=f"{symbol}_cvd_windows.csv",
                   mime="text/csv", use_container_width=True)
_wallet_csv_rows = (
    [{"type": "whale_accumulator", **r_} for r_ in whale_acc_rows] +
    [{"type": "whale_distributor", **r_} for r_ in whale_dist_rows] +
    [{"type": "dolphin_accumulator", **r_} for r_ in dolphin_acc_rows] +
    [{"type": "dolphin_distributor", **r_} for r_ in dolphin_dist_rows] +
    [{"type": "light_holder", **r_} for r_ in light_rows] +
    [{"type": "trader", **r_} for r_ in trader_rows] +
    [{"type": "fresh_wallet", **r_} for r_ in fw_rows] +
    [{"type": "no_buy_current_holder", **r_}
     for r_ in silent_holder_rows] +
    [{"type": "gmgn_no_buy_holder", **r_}
     for r_ in no_buy_meta_rows]
)
wallets_csv = pd.DataFrame(_wallet_csv_rows).to_csv(index=False) \
    if _wallet_csv_rows else "no wallets"
e3.download_button("⬇️ Wallets (CSV)", wallets_csv,
                   file_name=f"{symbol}_cvd_wallets.csv",
                   mime="text/csv", use_container_width=True)

with st.expander("👁 Preview report"):
    st.markdown(report_md)

st.caption(f"Fetched {dtm.datetime.utcfromtimestamp(fetched_at):%H:%M:%S} "
           f"UTC · click Analyze again to refresh · swaps <{MIN_SOL:g} SOL "
           f"filtered · whale ≥{WHALE_SOL:g} SOL.")
