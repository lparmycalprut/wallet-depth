# -*- coding: utf-8 -*-
"""Deep CVD analysis for a user-selected 4-48h swap window.

Flags high-conviction whale accumulation, exports reports, and builds an
honest, ready-to-copy prompt for an external AI chat.
"""
import datetime as dtm
import io
import json
import os
import sys
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_prompt import build_ai_prompt
from core import load_config
from cvd import (MIN_SOL, WHALE_SOL, analysis_windows, classify_swap,
                 conviction_split, detect_divergence, wallet_profiles)

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
helius_key = CONFIG.get("helius_api_key") or ""
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# CA can arrive via query param (?ca=...) from the LP Radar cards on the
# main page — prefill but do NOT auto-analyze, user picks hours first.
qp_ca = st.query_params.get("ca", "").strip()

ca = st.text_input("Contract Address", value=qp_ca,
                   placeholder="Solana CA...").strip()

col1, col2 = st.columns([1, 2])
with col1:
    hours = st.selectbox("Time window", [4, 6, 8, 12, 24, 36, 48],
                         index=5, help="Fetch swaps for this many hours back")
with col2:
    run = st.button("📊 Analyze", type="primary",
                    use_container_width=True)

if not ca:
    st.info("Paste a CA. The fetch pulls the complete swap history for the "
            "selected time window — very active tokens can take a few "
            "minutes, progress is shown.")
    st.stop()

# Keep a completed analysis renderable across reruns. This is required for
# the Prompt to AI button: clicking it reruns Streamlit but must not force a
# second fetch or a second time-window selector.
skey = f"cvd::{hours}h::{ca}"
if not run and skey not in st.session_state:
    st.stop()
if not helius_key and (run or skey not in st.session_state):
    st.error("Helius API key missing (config.json / secrets).")
    st.stop()


@st.cache_data(ttl=120, show_spinner=False)
def get_pool(ca: str):
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                     timeout=20)
    pairs = (r.json() or {}).get("pairs") or []
    if not pairs:
        return None, None, None, None
    pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
               reverse=True)
    b = pairs[0]
    return (b["pairAddress"], b["baseToken"].get("symbol", "?"),
            float(b.get("priceUsd") or 0),
            float(b.get("marketCap") or b.get("fdv") or 0))


def full_fetch(ca: str, pool: str, cutoff_ts: int):
    """Fetch ALL swaps back to cutoff — no page cap (hard safety 1500).
    Uses per-page retries with backoff so transient 429/5xx don't abort."""
    from cvd import _fetch_page
    swaps, before = [], None
    pbar = st.progress(0.0, text=f"Fetching swaps for {hours}h…")
    t0 = time.time()
    oldest = time.time()
    consecutive_fail = 0
    for page in range(1500):
        data = _fetch_page(helius_key, pool, before)
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
        with open(os.path.join(BASE, "funders_cache.json"), "w") as f:
            json.dump(c, f, separators=(",", ":"))
    except Exception:
        pass


def lookup_first_tx(wallet, max_pages=2):
    url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
    before, last_sig, last_bt = None, None, None
    for _ in range(max_pages):
        params = [wallet, {"limit": 1000}]
        if before:
            params[1]["before"] = before
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1,
                                         "method": "getSignaturesForAddress",
                                         "params": params}, timeout=30)
            res = r.json().get("result") or []
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
        r = requests.post(url, json={
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [last_sig, {"encoding": "jsonParsed",
                                  "maxSupportedTransactionVersion": 0}]},
            timeout=30)
        tx = r.json().get("result")
        keys = tx["transaction"]["message"]["accountKeys"]
        fp = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
        return (fp if fp != wallet else None), last_bt
    except Exception:
        return None, last_bt


pool, symbol, price_now, mc_now = get_pool(ca)
if not pool:
    st.error("Token not found on DexScreener.")
    st.stop()

# Every analysis row must fit inside the selected/fetched time range.
WINDOWS = analysis_windows(hours)

if run or skey not in st.session_state:
    st.session_state.pop(f"ai_prompt::{skey}", None)
    cutoff = int(time.time()) - hours * 3600
    # Hybrid: watchlist tokens use the incremental store (top-up only the
    # missing newest part — fast). Others need a full historical fetch.
    from watchlist import load_watchlist
    from cvd import update_token_cvd, get_recent_swaps
    got, src = [], "full fetch"
    if ca in load_watchlist():
        with st.spinner("Topping up incremental store (only new swaps)…"):
            try:
                update_token_cvd(helius_key, ca, pool, max_pages=200)
            except Exception:
                pass
            got = get_recent_swaps(ca, hours)
            src = "incremental store"
    if not got:
        st.info(f"Fetching last {hours}h of swaps — very active tokens can "
                "take several minutes. 💡 Watchlist tokens skip this via "
                "the incremental store.")
        got = full_fetch(ca, pool, cutoff)
        src = "full fetch"
    st.session_state[skey] = {"swaps": got, "ts": time.time(), "src": src}
swaps_all = st.session_state[skey]["swaps"]
fetched_at = st.session_state[skey]["ts"]
st.caption(f"Source: {st.session_state[skey].get('src', '?')}")
if not swaps_all:
    st.warning(f"No swaps ≥ 0.05 SOL found in the last {hours}h.")
    st.stop()

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
mw_rows = []
for h in sorted(win_stats):
    s = win_stats[h]
    mw_rows.append({
        "Window": f"{h}h", "Swaps": f"{s['swaps']:,}",
        "Net CVD": f"{s['net']:+,.0f}",
        "🐋 Whale": f"{s['whale_net']:+,.0f}",
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
# Pure accumulators / distributors in the full selected window, with age
# ---------------------------------------------------------------------------
full_profiles = win_stats[max(win_stats)]["profiles"]
accs = sorted([(w, d) for w, d in full_profiles.items()
               if d["profile"] == "pure_accum" and d["buy"] >= WHALE_SOL],
              key=lambda x: -x[1]["buy"])[:10]
dists = sorted([(w, d) for w, d in full_profiles.items()
                if d["profile"] == "pure_dist" and d["sell"] >= WHALE_SOL],
               key=lambda x: -x[1]["sell"])[:10]

fcache = load_funder_cache()
targets = [w for w, _ in accs + dists if w not in fcache]
if targets:
    apb = st.progress(0.0, text="Looking up wallet ages…")
    for i, w in enumerate(targets[:20]):
        fcache[w] = list(lookup_first_tx(w))
        apb.progress((i + 1) / min(len(targets), 20),
                     text=f"Wallet ages… {i+1}/{min(len(targets), 20)}")
        time.sleep(0.1)
    apb.empty()
    save_funder_cache(fcache)


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
for w, _d in accs:
    fu = fcache.get(w)
    if fu and fu[0]:
        fmap.setdefault(fu[0], []).append(w)
same_funder = {w for ws in fmap.values() if len(ws) > 1 for w in ws}

pa1, pa2 = st.columns(2)
acc_rows, dist_rows = [], []
with pa1:
    if accs:
        acc_rows = [{
            "Wallet": f"https://solscan.io/account/{w}",
            "Bought": f"{d['buy']:,.1f}", "Swaps": d["n_buy"],
            "Age": age_str(w),
            "Flags": ("🎯DCA " if d.get("dca") else "") +
                     ("⚠️same-funder" if w in same_funder else ""),
        } for w, d in accs]
        st.dataframe(pd.DataFrame(acc_rows), use_container_width=True,
                     hide_index=True,
                     column_config={"Wallet": st.column_config.LinkColumn(
                         f"💎 Pure accumulator ({hours}h)",
                         display_text=r"account/(.{6}).*")})
    else:
        st.caption(f"No whale-size pure accumulators in {hours}h.")
with pa2:
    if dists:
        dist_rows = [{
            "Wallet": f"https://solscan.io/account/{w}",
            "Sold": f"{d['sell']:,.1f}", "Swaps": d["n_sell"],
            "Age": age_str(w),
            "Flags": "🎯DCA" if d.get("dca") else "",
        } for w, d in dists]
        st.dataframe(pd.DataFrame(dist_rows), use_container_width=True,
                     hide_index=True,
                     column_config={"Wallet": st.column_config.LinkColumn(
                         f"🩸 Pure distributor ({hours}h)",
                         display_text=r"account/(.{6}).*")})
    else:
        st.caption(f"No whale-size pure distributors in {hours}h.")

# ---------------------------------------------------------------------------
# 🤖 Ready-to-copy prompt for a free AI chat
# ---------------------------------------------------------------------------
prompt_wallets = []
for wallet, profile in accs:
    flags = (("DCA; " if profile.get("dca") else "") +
             ("same-funder" if wallet in same_funder else "")).strip("; ")
    prompt_wallets.append({
        "wallet": wallet, "role": "pure accumulator",
        "buy": profile["buy"], "sell": profile["sell"],
        "swaps": profile["n_buy"] + profile["n_sell"],
        "age": age_str(wallet), "flags": flags,
    })
for wallet, profile in dists:
    prompt_wallets.append({
        "wallet": wallet, "role": "pure distributor",
        "buy": profile["buy"], "sell": profile["sell"],
        "swaps": profile["n_buy"] + profile["n_sell"],
        "age": age_str(wallet),
        "flags": "DCA" if profile.get("dca") else "",
    })

prompt_key = f"ai_prompt::{skey}"
if st.button("🤖 Prompt to AI", use_container_width=True,
             help="Build a copy-ready Indonesian prompt for DeepSeek"):
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
rep.write("| Window | Swaps | Net CVD | Whale | Retail | Pure buy | "
          "Pure sell | Net pure | Conviction | Verdict |\n")
rep.write("|---|---|---|---|---|---|---|---|---|---|\n")
for h in sorted(win_stats):
    s = win_stats[h]
    rep.write(f"| {h}h | {s['swaps']:,} | {s['net']:+,.0f} | "
              f"{s['whale_net']:+,.0f} | {s['retail_net']:+,.0f} | "
              f"{s['pure_buy']:,.0f} | {s['pure_sell']:,.0f} | "
              f"{s['net_pure']:+,.0f} | {s['conviction']:.0f}% | "
              f"{s['verdict']} |\n")
if div_lines:
    rep.write(f"\n## Divergences (H1, {hours}h)\n\n")
    for line in div_lines:
        rep.write(f"- {line}\n")
rep.write(f"\n## Top pure accumulators ({hours}h)\n\n")
if acc_rows:
    rep.write("| Wallet | Bought (SOL) | Swaps | Age | Flags |\n")
    rep.write("|---|---|---|---|---|\n")
    for r_ in acc_rows:
        w = r_["Wallet"].split("account/")[-1]
        rep.write(f"| [{w[:8]}…]({r_['Wallet']}) | {r_['Bought']} | "
                  f"{r_['Swaps']} | {r_['Age']} | {r_['Flags']} |\n")
else:
    rep.write("None.\n")
rep.write(f"\n## Top pure distributors ({hours}h)\n\n")
if dist_rows:
    rep.write("| Wallet | Sold (SOL) | Swaps | Age | Flags |\n")
    rep.write("|---|---|---|---|---|\n")
    for r_ in dist_rows:
        w = r_["Wallet"].split("account/")[-1]
        rep.write(f"| [{w[:8]}…]({r_['Wallet']}) | {r_['Sold']} | "
                  f"{r_['Swaps']} | {r_['Age']} | {r_['Flags']} |\n")
else:
    rep.write("None.\n")
rep.write("\n---\n*Whale = swap ≥3 SOL · pure = one-way (≤5% tol) · "
          "conviction = % of whale-size buys that were held · generated by "
          "Wallet Depth by Threshold*\n")
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
wallets_csv = pd.DataFrame(
    [{"type": "accumulator", **r_} for r_ in acc_rows] +
    [{"type": "distributor", **r_} for r_ in dist_rows]).to_csv(index=False) \
    if (acc_rows or dist_rows) else "no wallets"
e3.download_button("⬇️ Wallets (CSV)", wallets_csv,
                   file_name=f"{symbol}_cvd_wallets.csv",
                   mime="text/csv", use_container_width=True)

with st.expander("👁 Preview report"):
    st.markdown(report_md)

st.caption(f"Fetched {dtm.datetime.utcfromtimestamp(fetched_at):%H:%M:%S} "
           f"UTC · click Analyze again to refresh · swaps <{MIN_SOL:g} SOL "
           f"filtered · whale ≥{WHALE_SOL:g} SOL.")
