# -*- coding: utf-8 -*-
"""Page: deep CVD analysis — paste a CA, swaps are fetched live on the spot."""
import datetime as dtm
import os
import sys
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import load_config
from cvd import (MIN_SOL, WHALE_SOL, classify_swap, detect_divergence,
                 fetch_h4_price)

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
st.caption("Paste a CA — swaps are pulled **live** from the chain via Helius "
           "and classified with certainty (token out of pool = BUY, into "
           "pool = SELL). No aggressor guessing like on CEX.")

CONFIG = load_config()
helius_key = CONFIG.get("helius_api_key") or ""

c_in, c_opt1, c_opt2 = st.columns([3, 1, 1])
ca = c_in.text_input("Contract Address", placeholder="Solana CA...",
                     label_visibility="collapsed").strip()
hours_back = c_opt1.selectbox("Window", [6, 12, 24, 48], index=1,
                              format_func=lambda h: f"last {h}h")
bucket_min = c_opt2.selectbox("Candle", [15, 30, 60, 240], index=2,
                              format_func=lambda m: f"{m}m" if m < 60
                              else f"{m//60}h")

run = st.button("📊 Analyze CVD (live fetch)", type="primary",
                use_container_width=True)
if not ca:
    st.info("Paste a CA above. Live fetch pulls up to ~100 pages of swaps "
            "(newest first) — very active tokens may not cover the full "
            "window; the actual covered range is always shown.")
    st.stop()
if not run and f"cvd_live::{ca}" not in st.session_state:
    st.stop()
if not helius_key:
    st.error("Helius API key missing (config.json / secrets).")
    st.stop()


@st.cache_data(ttl=120, show_spinner=False)
def get_pool(ca: str):
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                     timeout=20)
    pairs = (r.json() or {}).get("pairs") or []
    if not pairs:
        return None, None, None
    pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
               reverse=True)
    b = pairs[0]
    return (b["pairAddress"], b["baseToken"].get("symbol", "?"),
            float(b.get("priceUsd") or 0))


def live_fetch(ca: str, pool: str, cutoff_ts: int, max_pages: int = 100):
    """Fetch swaps newest-first until cutoff_ts, with a progress bar.
    Returns list of (side, sol, ts, wallet)."""
    swaps, before = [], None
    pbar = st.progress(0.0, text="Fetching swaps from chain…")
    oldest = time.time()
    for page in range(max_pages):
        params = {"api-key": helius_key, "limit": 100, "type": "SWAP"}
        if before:
            params["before"] = before
        try:
            r = requests.get(
                f"https://api.helius.xyz/v0/addresses/{pool}/transactions",
                params=params, headers={"User-Agent": "Mozilla/5.0"},
                timeout=40)
            if r.status_code != 200:
                break
            data = r.json()
        except Exception:
            break
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
        span_done = min(1.0, max(0.02, (time.time() - oldest) /
                                 max(time.time() - cutoff_ts, 1)))
        pbar.progress(span_done,
                      text=f"Fetching… page {page+1}, {len(swaps):,} swaps, "
                           f"reached {dtm.datetime.utcfromtimestamp(oldest):%m-%d %H:%M} UTC")
        if done:
            break
        before = data[-1].get("signature")
        time.sleep(0.12)
    pbar.empty()
    return swaps


pool, symbol, price_now = get_pool(ca)
if not pool:
    st.error("Token not found on DexScreener.")
    st.stop()

# --- hybrid source: watchlist tokens use the incremental store (complete
# window that never gets cut off); others use live fetch --------------------
from watchlist import load_watchlist
from cvd import update_token_cvd, get_recent_swaps

_wl_cvd = load_watchlist()
in_watchlist = ca in _wl_cvd

cache_key = f"cvd_live::{ca}::{hours_back}"
if run or cache_key not in st.session_state:
    cutoff = int(time.time()) - hours_back * 3600
    if in_watchlist:
        with st.spinner("Topping up incremental store & loading window…"):
            try:
                update_token_cvd(helius_key, ca, pool, max_pages=60)
            except Exception:
                pass
            got = get_recent_swaps(ca, hours_back)
        if not got:  # store empty -> fall back to live
            got = live_fetch(ca, pool, cutoff)
            src = "live fetch"
        else:
            src = "incremental store (complete window)"
    else:
        got = live_fetch(ca, pool, cutoff)
        src = "live fetch"
    st.session_state[cache_key] = {
        "swaps": got, "cutoff": cutoff, "hours": hours_back,
        "ts": time.time(), "src": src}
data = st.session_state[cache_key]
swaps = data["swaps"]

if not swaps:
    st.warning("No swaps ≥ 0.05 SOL found in the window.")
    st.stop()

# ---------------------------------------------------------------------------
# Build dataframe
# ---------------------------------------------------------------------------
df = pd.DataFrame(swaps, columns=["side", "sol", "ts", "wallet"])
df["dt"] = pd.to_datetime(df["ts"], unit="s")
df["signed"] = df.apply(lambda r: r["sol"] if r["side"] == "buy"
                        else -r["sol"], axis=1)
oldest_dt, newest_dt = df["dt"].min(), df["dt"].max()
covered_h = (newest_dt - oldest_dt).total_seconds() / 3600

n_buy = int((df["side"] == "buy").sum())
n_sell = int((df["side"] == "sell").sum())
v_buy = float(df.loc[df["side"] == "buy", "sol"].sum())
v_sell = float(df.loc[df["side"] == "sell", "sol"].sum())
net = v_buy - v_sell
wh = df[df["sol"] >= WHALE_SOL]
wh_net = float(wh["signed"].sum())
rt_net = net - wh_net

# header
st.markdown(f"### ${symbol} — {len(df):,} swaps · "
            f"{oldest_dt:%m-%d %H:%M} → {newest_dt:%m-%d %H:%M} UTC "
            f"({covered_h:.1f}h covered)")
if covered_h < data["hours"] * 0.9:
    if in_watchlist:
        st.info(f"ℹ️ Store covers {covered_h:.1f}h so far — it keeps filling "
                f"incrementally (2-hourly cron + every run). The window "
                f"will soon be complete and stay complete.")
    else:
        st.warning(f"Requested {data['hours']}h but page limit only reached "
                   f"{covered_h:.1f}h back — token is very active. 💡 Add it "
                   f"to the watchlist for complete, never-cut windows.")
st.caption(f"Source: {data.get('src', 'live fetch')}")

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Buys", f"{n_buy:,}", f"{v_buy:,.1f} SOL", delta_color="off")
m2.metric("Sells", f"{n_sell:,}", f"{v_sell:,.1f} SOL", delta_color="off")
m3.metric("Net CVD", f"{net:+,.1f} SOL",
          "net buying" if net >= 0 else "net selling",
          delta_color="normal" if net >= 0 else "inverse")
m4.metric(f"🐋 Whale net (≥{WHALE_SOL:g} SOL)", f"{wh_net:+,.1f} SOL",
          f"{len(wh):,} swaps",
          delta_color="normal" if wh_net >= 0 else "inverse")
m5.metric("🐟 Retail net", f"{rt_net:+,.1f} SOL", delta_color="off")
avg_buy = v_buy / n_buy if n_buy else 0
avg_sell = v_sell / n_sell if n_sell else 0
m6.metric("Avg size B/S", f"{avg_buy:.2f} / {avg_sell:.2f}",
          "SOL per swap", delta_color="off")

if (wh_net >= 0) != (rt_net >= 0):
    msg = ("⚡ **Whales buy what retail sells — stealth accumulation**"
           if wh_net >= 0 else
           "⚡ **Whales sell into retail buying — distribution to retail**")
    (st.success if wh_net >= 0 else st.error)(msg)

# ---------------------------------------------------------------------------
# 💎 Pure flow — accumulators vs distributors (bots excluded)
# ---------------------------------------------------------------------------
from cvd import wallet_profiles, conviction_split

profiles = wallet_profiles(swaps)
conv = conviction_split(profiles, whale_min_sol=WHALE_SOL)

st.markdown("**💎 Pure flow — who bought & HELD vs sold & LEFT** "
            "<span style='opacity:0.6;font-size:0.75rem'>(two-way bots/MMs "
            "excluded — sells ≤5% of buys counts as pure)</span>",
            unsafe_allow_html=True)
pc1, pc2, pc3, pc4 = st.columns(4)
pc1.metric("💎 Pure accum (whale-size)", f"{conv['pure_buy']:+,.1f} SOL",
           "bought & held", delta_color="off")
pc2.metric("🩸 Pure distribution", f"-{conv['pure_sell']:,.1f} SOL",
           "sold & left", delta_color="off")
pc3.metric("🔄 Two-way churn",
           f"{conv['tw_buy']:,.0f}/{conv['tw_sell']:,.0f}",
           "bot/MM volume (noise)", delta_color="off")
pc4.metric("Conviction ratio", f"{conv['conviction_pct']:.0f}%",
           "of whale buys are held",
           delta_color="normal" if conv["conviction_pct"] >= 50
           else "inverse")

net_pure = conv["pure_buy"] - conv["pure_sell"]
if conv["pure_buy"] >= 10 and net_pure > 0 and conv["conviction_pct"] >= 50:
    st.success(f"💎 **High-conviction accumulation** — {conv['pure_buy']:,.0f} "
               f"SOL bought by wallets that did NOT sell "
               f"({conv['conviction_pct']:.0f}% conviction). The strongest "
               f"accumulation signature this tool can detect.")
elif conv["pure_sell"] >= 10 and net_pure < 0:
    st.error(f"🩸 **Hard distribution** — {conv['pure_sell']:,.0f} SOL sold "
             f"by wallets that did NOT buy back. The 'invisible seller': "
             f"steady one-way supply hitting every bounce.")

# --- enrichment data: session analysis (if the main page analyzed this CA),
#     funder cache (wallet ages) --------------------------------------------
_sess_a = (st.session_state.get("analyses") or {}).get(ca) or {}
holder_pct_map = {}
if _sess_a.get("top20") is not None:
    holder_pct_map = dict(zip(_sess_a["top20"]["owner"],
                              _sess_a["top20"]["pct_supply"]))
cluster_members = set()
if _sess_a.get("bundles") is not None:
    for ms in _sess_a["bundles"]["members"]:
        cluster_members.update(ms)
def load_funder_cache():
    """Read the shared funder cache directly (do NOT import app.py —
    importing it would execute the whole Streamlit script)."""
    import json as _j
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "funders_cache.json")) as f:
            return _j.load(f) or {}
    except Exception:
        return {}


funder_disk = load_funder_cache()


def _badges(w, d):
    b = []
    fu = funder_disk.get(w)
    if fu and fu[1]:
        ad = (time.time() - fu[1]) / 86400
        b.append("🐣<3d" if ad < 3 else f"🌳{ad:.0f}d")
    hp = holder_pct_map.get(w)
    if hp and hp >= 0.1:
        b.append(f"📦{hp:.2f}%")
    if w in cluster_members:
        b.append("🕸️CLUSTER")
    if d.get("dca"):
        b.append("🎯DCA")
    if (d["n_buy"] + d["n_sell"]) >= 30:
        b.append("🤖bot-like")
    return " ".join(b)


pa1, pa2 = st.columns(2)
with pa1:
    accs = sorted([(w, d) for w, d in profiles.items()
                   if d["profile"] == "pure_accum" and d["buy"] >= WHALE_SOL],
                  key=lambda x: -x[1]["buy"])[:10]
    if accs:
        fmap = {}
        for w, _d in accs:
            fu = funder_disk.get(w)
            if fu and fu[0]:
                fmap.setdefault(fu[0], []).append(w)
        same_funder = {w for ws in fmap.values() if len(ws) > 1 for w in ws}
        st.dataframe(pd.DataFrame([{
            "Wallet": f"https://solscan.io/account/{w}",
            "Bought": f"{d['buy']:,.1f}",
            "Swaps": d["n_buy"],
            "Badges": _badges(w, d) +
                      (" ⚠️same-funder" if w in same_funder else ""),
        } for w, d in accs]), use_container_width=True, hide_index=True,
            column_config={"Wallet": st.column_config.LinkColumn(
                "💎 Pure accumulator", display_text=r"account/(.{6}).*")})
        if same_funder:
            st.caption("⚠️ some accumulators share the SAME funder — likely "
                       "one entity split across wallets.")
    else:
        st.caption("No whale-size pure accumulators in this window.")
with pa2:
    dists = sorted([(w, d) for w, d in profiles.items()
                    if d["profile"] == "pure_dist" and
                    d["sell"] >= WHALE_SOL],
                   key=lambda x: -x[1]["sell"])[:10]
    if dists:
        st.dataframe(pd.DataFrame([{
            "Wallet": f"https://solscan.io/account/{w}",
            "Sold": f"{d['sell']:,.1f}",
            "Swaps": d["n_sell"],
            "Badges": _badges(w, d),
        } for w, d in dists]), use_container_width=True, hide_index=True,
            column_config={"Wallet": st.column_config.LinkColumn(
                "🩸 Pure distributor", display_text=r"account/(.{6}).*")})
    else:
        st.caption("No whale-size pure distributors in this window.")
st.caption("💎 bought & never sold (≤5% tol) · 🩸 sold & never bought back · "
           "🎯DCA = ≥4 spread-out swaps · 📦/🕸️ badges need a main-page "
           "Analyze of this CA in the current session · conviction ≥50% + "
           "🌳 aged + 📦 holding = battle-tested accumulation profile.")

# ---------------------------------------------------------------------------
# 🔎 Wallet drill-down
# ---------------------------------------------------------------------------
_drill = ([w for w, _ in accs] if accs else []) + \
         ([w for w, _ in dists] if dists else [])
if _drill:
    dd_badge = {w: _badges(w, profiles[w]) for w in _drill}
    pick_w = st.selectbox(
        "🔎 Inspect a wallet in detail",
        ["— select —"] + _drill,
        format_func=lambda w: (w if w == "— select —" else
                               f"{w[:8]}…{w[-4:]} · "
                               f"{'💎' if profiles[w]['profile'] == 'pure_accum' else '🩸'} "
                               f"{dd_badge.get(w, '')}"))
    if pick_w != "— select —":
        wdf = df[df["wallet"] == pick_w].sort_values("dt")
        wb = float(wdf.loc[wdf["side"] == "buy", "sol"].sum())
        ws_ = float(wdf.loc[wdf["side"] == "sell", "sol"].sum())
        fu = funder_disk.get(pick_w) or [None, None]
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Bought", f"{wb:,.2f} SOL",
                  f"{int((wdf['side'] == 'buy').sum())} swaps",
                  delta_color="off")
        d2.metric("Sold", f"{ws_:,.2f} SOL",
                  f"{int((wdf['side'] == 'sell').sum())} swaps",
                  delta_color="off")
        d3.metric("Net", f"{wb - ws_:+,.2f} SOL",
                  delta_color="normal" if wb >= ws_ else "inverse")
        d4.metric("Profile", profiles[pick_w]["profile"].replace("_", " "),
                  delta_color="off")
        if fu[1]:
            age_days = (time.time() - fu[1]) / 86400
            fu_txt = (f"First tx: {age_days:.1f} days ago · funded by "
                      f"[`{str(fu[0])[:8]}…`]"
                      f"(https://solscan.io/account/{fu[0]})"
                      if fu[0] else f"First tx: {age_days:.1f} days ago")
            st.markdown(f"🧬 {fu_txt} · [open on Solscan]"
                        f"(https://solscan.io/account/{pick_w})")
        figw = go.Figure()
        figw.add_bar(x=wdf["dt"], y=wdf["signed"],
                     marker=dict(color=["#22c55e" if v >= 0 else "#ef4444"
                                        for v in wdf["signed"]]),
                     hovertemplate="%{x}<br>%{y:+.2f} SOL<extra></extra>")
        figw.add_trace(go.Scatter(x=wdf["dt"], y=wdf["signed"].cumsum(),
                                  name="cum net",
                                  line=dict(color="#38bdf8", width=2)))
        figw.update_layout(height=200, showlegend=False,
                           margin=dict(t=20, b=0, l=0, r=0),
                           yaxis_title="SOL",
                           title=dict(text=f"Swap timeline — {pick_w[:8]}…",
                                      font=dict(size=12)))
        st.plotly_chart(figw, use_container_width=True,
                        config={"displayModeBar": False})

# ---------------------------------------------------------------------------
# CVD chart (chosen bucket) + price overlay
# ---------------------------------------------------------------------------
freq = f"{bucket_min}min"
g = df.set_index("dt").sort_index()
# pivot by side
agg = g.groupby([pd.Grouper(freq=freq), "side"])["sol"].sum().unstack(
    fill_value=0.0)
agg["buy"] = agg.get("buy", 0.0)
agg["sell"] = agg.get("sell", 0.0)
agg["delta"] = agg["buy"] - agg["sell"]
agg["cvd"] = agg["delta"].cumsum()
wagg = (g[g["sol"] >= WHALE_SOL]
        .groupby([pd.Grouper(freq=freq), "side"])["sol"].sum()
        .unstack(fill_value=0.0)).reindex(agg.index, fill_value=0.0)
wagg["delta"] = wagg.get("buy", 0.0) - wagg.get("sell", 0.0)
agg["wcvd"] = wagg["delta"].cumsum()
agg["rcvd"] = agg["cvd"] - agg["wcvd"]

x = agg.index
fig = go.Figure()
fig.add_trace(go.Scatter(x=x, y=agg["cvd"], name="CVD (all)",
                         line=dict(color="#38bdf8", width=3)))
fig.add_trace(go.Scatter(x=x, y=agg["wcvd"], name="🐋 Whale CVD",
                         line=dict(color="#c084fc", width=2)))
fig.add_trace(go.Scatter(x=x, y=agg["rcvd"], name="🐟 Retail CVD",
                         line=dict(color="#64748b", width=1.5, dash="dot")))
fig.add_bar(x=x, y=agg["delta"], name="Δ per candle", yaxis="y2", opacity=0.3,
            marker=dict(color=["#22c55e" if v >= 0 else "#ef4444"
                               for v in agg["delta"]]))
fig.update_layout(height=340, margin=dict(t=25, b=0, l=0, r=0),
                  legend=dict(orientation="h", font=dict(size=10)),
                  yaxis=dict(title="cumulative SOL"),
                  yaxis2=dict(overlaying="y", side="right", visible=False),
                  title=dict(text=f"CVD — {bucket_min}m buckets",
                             font=dict(size=13)))
st.plotly_chart(fig, use_container_width=True,
                config={"displayModeBar": False})

# ---------------------------------------------------------------------------
# Divergence vs price (on the chosen buckets, using GeckoTerminal candles)
# ---------------------------------------------------------------------------
tf_map = {15: ("minute", 15), 30: ("minute", 15), 60: ("hour", 1),
          240: ("hour", 4)}
res, aggr = tf_map[bucket_min]
try:
    r = requests.get(
        f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/"
        f"ohlcv/{res}", params={"aggregate": aggr, "limit": 200},
        headers={"accept": "application/json"}, timeout=20)
    lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
        .get("ohlcv_list") or []
    price_map = {int(v[0]): float(v[4]) for v in lst}
except Exception:
    price_map = {}

price_series = []
for t in x:
    key = int(t.timestamp()) // (bucket_min * 60) * (bucket_min * 60)
    price_series.append(price_map.get(key))

valid = [p for p in price_series if p is not None]
st.markdown("**🔀 Price vs CVD divergence (pivot-based, non-repainting)**")
if len(valid) >= max(7, len(price_series) * 0.6):
    # forward-fill tiny gaps
    ps, last = [], None
    for p in price_series:
        last = p if p is not None else last
        ps.append(last)
    if ps[0] is None:
        first = next((p for p in ps if p is not None), None)
        ps = [first if p is None else p for p in ps]
    divs = detect_divergence(ps, list(agg["cvd"]))
    divs += [dict(dv, src="whale") for dv in
             detect_divergence(ps, list(agg["wcvd"]))]
    if divs:
        seen = set()
        for dv in divs:
            k = (dv["type"], dv["kind"], dv.get("src", "all"))
            if k in seen:
                continue
            seen.add(k)
            src = "Whale CVD" if dv.get("src") == "whale" else "CVD"
            rng = f"{x[dv['i1']]:%m-%d %H:%M} → {x[dv['i2']]:%m-%d %H:%M}"
            if dv["type"] == "bullish":
                st.success(f"📈 **{dv['kind'].upper()} BULLISH ({src})** · "
                           f"{rng} — {dv['detail']}")
            else:
                st.error(f"📉 **{dv['kind'].upper()} BEARISH ({src})** · "
                         f"{rng} — {dv['detail']}")
    else:
        st.info("No divergence at the last confirmed pivots (2-bar "
                "confirmation each side).")
else:
    st.caption("Not enough price candles from GeckoTerminal for this "
               "bucket size — try a larger candle.")

# ---------------------------------------------------------------------------
# Top wallets by net flow + biggest swaps
# ---------------------------------------------------------------------------
cw1, cw2 = st.columns(2)
with cw1:
    st.markdown("**🏆 Top wallets by net flow (this window)**")
    wsum = df.groupby("wallet").agg(
        net=("signed", "sum"), n=("signed", "size"),
        vol=("sol", "sum")).sort_values("net")
    top_sell = wsum.head(8).reset_index()
    top_buy = wsum.tail(8).sort_values("net", ascending=False).reset_index()
    tbl = pd.concat([top_buy, top_sell])
    tbl["Wallet"] = tbl["wallet"].map(
        lambda w: f"https://solscan.io/account/{w}")
    tbl["Net SOL"] = tbl["net"].map(lambda v: f"{v:+,.1f}")
    tbl["Swaps"] = tbl["n"]
    tbl["Volume"] = tbl["vol"].map(lambda v: f"{v:,.1f}")
    st.dataframe(tbl[["Wallet", "Net SOL", "Swaps", "Volume"]],
                 use_container_width=True, hide_index=True,
                 column_config={"Wallet": st.column_config.LinkColumn(
                     "Wallet", display_text=r"account/(.{6}).*")})
    st.caption("Top 8 net buyers and top 8 net sellers. Click to inspect "
               "on Solscan.")
with cw2:
    st.markdown("**💥 Biggest single swaps**")
    big = df.nlargest(12, "sol").copy()
    big["Wallet"] = big["wallet"].map(
        lambda w: f"https://solscan.io/account/{w}")
    big["Side"] = big["side"].map(
        lambda s: "🟢 BUY" if s == "buy" else "🔴 SELL")
    big["SOL"] = big["sol"].map(lambda v: f"{v:,.2f}")
    big["Time (UTC)"] = big["dt"].dt.strftime("%m-%d %H:%M")
    st.dataframe(big[["Time (UTC)", "Side", "SOL", "Wallet"]],
                 use_container_width=True, hide_index=True,
                 column_config={"Wallet": st.column_config.LinkColumn(
                     "Wallet", display_text=r"account/(.{6}).*")})

# size distribution
st.markdown("**📊 Flow by swap size**")
bins = [(MIN_SOL, 0.5, "0.05-0.5"), (0.5, 1, "0.5-1"), (1, 3, "1-3"),
        (3, 10, "3-10"), (10, 50, "10-50"), (50, 1e9, "50+")]
rows = []
for lo, hi, lab in bins:
    seg = df[(df["sol"] >= lo) & (df["sol"] < hi)]
    rows.append({"size": lab + " SOL",
                 "buy": float(seg.loc[seg["side"] == "buy", "sol"].sum()),
                 "sell": -float(seg.loc[seg["side"] == "sell", "sol"].sum())})
sd = pd.DataFrame(rows)
figd = go.Figure()
figd.add_bar(x=sd["size"], y=sd["buy"], name="Buys", marker_color="#22c55e")
figd.add_bar(x=sd["size"], y=sd["sell"], name="Sells", marker_color="#ef4444")
figd.update_layout(barmode="relative", height=260,
                   margin=dict(t=10, b=0, l=0, r=0),
                   yaxis_title="SOL", legend=dict(orientation="h"))
st.plotly_chart(figd, use_container_width=True,
                config={"displayModeBar": False})
st.caption(f"Positive = buy volume, negative = sell volume per size bracket. "
           f"Whale threshold: ≥{WHALE_SOL:g} SOL. Swaps <{MIN_SOL:g} SOL "
           f"excluded as bot noise. Fetched live at "
           f"{dtm.datetime.utcfromtimestamp(data['ts']):%H:%M:%S} UTC — "
           f"click Analyze again to refresh.")
