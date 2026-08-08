# -*- coding: utf-8 -*-
"""CVD Deep Analysis — conviction windows and top-holder retention."""
import os
import sys
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import (get_helius_keys, get_market,
                  get_holders as core_get_holders,
                  get_supply as core_get_supply, load_config)
from cvd import (MIN_SOL, WHALE_SOL, conviction_split, top_holder_analysis,
                 wallet_profiles)


st.set_page_config(page_title="CVD Analysis", page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(
    """<style>
    .block-container {padding-top: 1.2rem; max-width: 1400px;}
    h1 {font-size: 1.3rem !important;}
    [data-testid="stMetric"] {padding: 0.2rem 0.5rem;
      background: rgba(128,128,128,0.07); border-radius: 8px;}
    [data-testid="stMetricLabel"] {font-size: 0.72rem !important;}
    [data-testid="stMetricValue"] {font-size: 1.1rem !important;}
    </style>""",
    unsafe_allow_html=True,
)

CONVICTION_WINDOWS = (4, 6, 12, 24, 48, 72)
FETCH_HOURS = 72

st.title("📊 CVD Deep Analysis")
st.caption(
    "Analisis conviction flow pada window 4h–72h dan pemeriksaan 100 top holder. "
    "Data swap diambil untuk 72 jam agar semua window tetap comparable."
)

CONFIG = load_config()
helius_keys = tuple(get_helius_keys(config=CONFIG))
try:
    dust_limit_usd = float(CONFIG.get("dust_limit_usd", 5.0))
except (TypeError, ValueError):
    dust_limit_usd = 5.0

qp_ca = st.query_params.get("ca", "").strip()
ca = st.text_input("Contract Address", value=qp_ca,
                   placeholder="Solana CA...").strip()
run = st.button("📊 Analyze", type="primary", use_container_width=True)

if not ca:
    st.info(
        "Paste CA. Analyze akan mengambil history swap 72 jam dari GMGN "
        "dan data holder lengkap dari Helius."
    )
    st.stop()

source_key = "gmgn"
skey = f"cvd::{source_key}::{FETCH_HOURS}h::{ca}"
if not run and skey not in st.session_state:
    st.stop()


@st.cache_data(ttl=120, show_spinner=False)
def get_pool(ca: str):
    market = get_market(ca)
    pools = market.get("pair_addresses") or []
    if not market or not pools:
        return None, None, None, None
    return (
        pools[0],
        market.get("symbol", "?"),
        float(market.get("price_usd") or 0),
        float(market.get("marketcap") or 0),
    )


def full_fetch(contract: str, pool: str, cutoff_ts: int):
    """Fetch the complete 72-hour GMGN trade range for this page."""
    from cvd import fetch_swaps, get_gmgn_last_error

    progress = st.progress(0.0, text=f"Fetching GMGN {FETCH_HOURS}h…")
    try:
        swaps, _sig, _ts, _hit = fetch_swaps(
            "", pool or "", contract, stop_ts=cutoff_ts,
            max_pages=120, sleep=0.05, use_gmgn=True,
        )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"GMGN fetch failed: {exc}")
        swaps = []
    finally:
        progress.empty()
    error = get_gmgn_last_error()
    if error and not swaps:
        st.warning("GMGN kosong: " + error)
    return swaps


@st.cache_data(ttl=300, show_spinner=False)
def fetch_holder_snapshot(contract: str, key_pool: tuple) -> dict:
    """Fetch and normalize the full Helius holder list for this CA."""
    if not key_pool:
        return {"ok": False, "error": "Helius API key belum dikonfigurasi."}
    try:
        supply, decimals = core_get_supply(key_pool, contract)
        holders = core_get_holders(key_pool, contract)
        if holders is None or holders.empty:
            return {"ok": False, "error": "Helius tidak mengembalikan holder."}
        if "owner" not in holders.columns or "raw_amount" not in holders.columns:
            return {"ok": False, "error": "Format holder Helius tidak valid."}
        normalized = holders[["owner", "raw_amount"]].copy()
        normalized["owner"] = normalized["owner"].astype(str)
        normalized["amount"] = (
            pd.to_numeric(normalized["raw_amount"], errors="coerce")
            .fillna(0.0) / (10 ** int(decimals))
        )
        normalized = normalized[normalized["amount"] > 0]
        normalized = normalized.sort_values("amount", ascending=False)
        return {
            "ok": True,
            "holders": normalized[["owner", "amount"]].to_dict("records"),
            "supply": float(supply or 0.0),
            "decimals": int(decimals),
            "total_holders": int(len(normalized)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Helius holder fetch gagal: {exc}"}


pool, symbol, price_now, mc_now = get_pool(ca)
if not pool:
    st.error("Token tidak ditemukan di DexScreener.")
    st.stop()

if run or skey not in st.session_state:
    cutoff = int(time.time()) - FETCH_HOURS * 3600
    st.info(f"Fetching last {FETCH_HOURS}h from GMGN Trades API…")
    st.session_state[skey] = {
        "swaps": full_fetch(ca, pool, cutoff),
        "ts": time.time(),
        "src": "GMGN Trades API",
    }

swaps_all = st.session_state[skey].get("swaps") or []
fetched_at = float(st.session_state[skey].get("ts") or time.time())
st.caption(f"Source: {st.session_state[skey].get('src', '?')}")
if not swaps_all:
    st.warning(f"No swaps ≥ {MIN_SOL:g} SOL in last {FETCH_HOURS}h.")

# Keep one canonical swap row per side/volume/timestamp/wallet. GMGN can
# return the same trade on a retry or on two adjacent pages.
_seen_all = {}
for swap in swaps_all:
    if len(swap) >= 4:
        key = (swap[0], float(swap[1]), int(swap[2]), str(swap[3]))
        _seen_all[key] = key
swaps_all = [list(key) for key in sorted(_seen_all, key=lambda item: item[2])]

if swaps_all:
    df = pd.DataFrame(swaps_all,
                      columns=["side", "sol", "ts", "wallet"])
    df["dt"] = pd.to_datetime(df["ts"], unit="s")
    df["signed"] = df.apply(
        lambda row: row["sol"] if row["side"] == "buy" else -row["sol"],
        axis=1,
    )
    covered_h = max(0.0, (fetched_at - df["ts"].min()) / 3600)
else:
    df = pd.DataFrame(columns=["side", "sol", "ts", "wallet", "dt", "signed"])
    covered_h = 0.0

st.markdown(
    f"### ${symbol} · {len(df):,} swaps · {covered_h:.1f}h covered · "
    f"MC ${mc_now:,.0f}"
)

# ---------------------------------------------------------------------------
# Conviction graph — deliberately no conviction table.
# ---------------------------------------------------------------------------
win_stats = {}
for window_h in CONVICTION_WINDOWS:
    if df.empty:
        segment = df
    else:
        segment = df[df["ts"] >= fetched_at - window_h * 3600]
    if segment.empty:
        profiles = {}
    else:
        profiles = wallet_profiles(
            list(segment[["side", "sol", "ts", "wallet"]]
                 .itertuples(index=False, name=None))
        )
    conviction = conviction_split(profiles, whale_min_sol=WHALE_SOL)
    win_stats[window_h] = conviction

fig_conviction = go.Figure()

# Thin connecting line (tipis) untuk menunjukkan tren antar window
x_vals = [f"{h}h" for h in CONVICTION_WINDOWS]
y_vals = [win_stats[h]["conviction_pct"] for h in CONVICTION_WINDOWS]

fig_conviction.add_trace(go.Scatter(
    x=x_vals,
    y=y_vals,
    mode="lines",
    line=dict(color="#64748b", width=1.2, dash="dot"),
    name="Trend",
    hoverinfo="skip",
    showlegend=False,
))

# Warna terpisah untuk setiap window (agar garis conviction terlihat jelas)
window_colors = {
    4: "#22c55e",    # hijau
    6: "#eab308",    # kuning
    12: "#f59e0b",   # orange
    24: "#ef4444",   # merah
    48: "#a855f7",   # ungu
    72: "#3b82f6",   # biru
}

for window_h in CONVICTION_WINDOWS:
    pct = win_stats[window_h]["conviction_pct"]
    fig_conviction.add_trace(go.Scatter(
        x=[f"{window_h}h"],
        y=[pct],
        mode="markers+text",
        text=[f"{pct:.0f}%"],
        textposition="top center",
        marker=dict(
            size=14,
            color=window_colors.get(window_h, "#38bdf8"),
            line=dict(width=2, color="white")
        ),
        name=f"{window_h}h",
        hovertemplate=f"<b>{window_h}h</b><br>Conviction: {pct:.1f}%<extra></extra>",
    ))

# Garis referensi
fig_conviction.add_hline(
    y=50, line_dash="dot", line_color="#22c55e", annotation_text="50%"
)
fig_conviction.add_hline(
    y=30, line_dash="dot", line_color="#ef4444", annotation_text="30%"
)

fig_conviction.update_layout(
    height=300,
    margin=dict(t=30, b=10, l=10, r=10),
    yaxis=dict(title="conviction %", range=[0, 100]),
    xaxis=dict(title="lookback window"),
    title=dict(text="Conviction window (4H / 12H / 24H / 48H / 72H) — garis terpisah", font=dict(size=13)),
    showlegend=True,
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        font=dict(size=10)
    ),
)
st.plotly_chart(fig_conviction, use_container_width=True,
                config={"displayModeBar": False})
st.caption(
    "Conviction = effective buy flow dari wallet yang tidak menjual lebih "
    "dari ambang profilnya. Setiap window (4H/12H/24H/48H/72H) ditampilkan sebagai titik terpisah dengan warna berbeda."
)

# ---------------------------------------------------------------------------
# Top 100 holders: diamond hand + real-vs-dust.
# ---------------------------------------------------------------------------
with st.spinner("Mengambil holder lengkap dari Helius…"):
    holder_data = fetch_holder_snapshot(ca, helius_keys)

st.markdown("#### 👥 Top 100 Holder Analysis")
if not holder_data.get("ok"):
    st.warning(holder_data.get("error", "Data holder tidak tersedia."))
    st.caption(
        "Analisis top holder membutuhkan Helius API key. Swap conviction "
        "di atas tetap dapat dibaca dari GMGN."
    )
else:
    holder_analysis = top_holder_analysis(
        holder_data.get("holders", []),
        swaps_all,
        price_usd=price_now,
        dust_limit_usd=dust_limit_usd,
        supply=holder_data.get("supply", 0.0),
        limit=100,
        sell_tolerance=0.10,
    )
    n_top = int(holder_analysis.get("n_top") or 0)
    diamond_count = int(holder_analysis.get("diamond_hands") or 0)
    observed = int(holder_analysis.get("observed_wallets") or 0)
    diamond_pct = float(holder_analysis.get("diamond_pct") or 0.0)
    all_holders = int(holder_analysis.get("all_holders") or holder_data.get("total_holders") or n_top)
    all_real_holders = int(holder_analysis.get("all_real_holders") if holder_analysis.get("all_real_holders") is not None else (holder_analysis.get("real_holders") or 0))
    all_dust_holders = int(holder_analysis.get("all_dust_holders") if holder_analysis.get("all_dust_holders") is not None else max(0, all_holders - all_real_holders))
    all_real_pct = float(holder_analysis.get("all_real_pct") if holder_analysis.get("all_real_pct") is not None else (all_real_holders / all_holders * 100.0 if all_holders else 0.0))
    all_dust_pct = float(holder_analysis.get("all_dust_pct") if holder_analysis.get("all_dust_pct") is not None else (all_dust_holders / all_holders * 100.0 if all_holders else 0.0))

    hm1, hm2, hm3, hm4, hm5 = st.columns(5)
    hm1.metric("Top holder dianalisis", f"{n_top}/100",
               f"{all_holders:,} total holder")
    hm2.metric(
        "💎 Diamond hand",
        f"{diamond_count}/{n_top} ({diamond_pct:.1f}%)" if n_top else "—",
        "sell ≤10% dari buy · Top 100",
    )
    hm3.metric(
        "💰 Real holder",
        f"{all_real_holders:,}/{all_holders:,} ({all_real_pct:.1f}%)"
        if all_holders else "—",
        f"≥ ${dust_limit_usd:,.2f} · full list",
    )
    hm4.metric(
        "🪙 Dust holder",
        f"{all_dust_holders:,}/{all_holders:,} ({all_dust_pct:.1f}%)"
        if all_holders else "—",
        f"< ${dust_limit_usd:,.2f} · full list",
    )
    top_supply_pct = float(holder_analysis.get("top_supply_pct") or 0.0)
    hm5.metric("Top 100 supply", f"{top_supply_pct:.2f}%",
               f"${price_now:.8g} token price")

    st.caption(
        f"Diamond hand dianalisis dari {n_top} top holder berdasarkan aktivitas swap 72 jam "
        f"({observed}/{n_top} top holder punya aktivitas swap teramati; wallet tanpa sell "
        f"terdeteksi ikut dihitung sebagai diamond hand). Real dan Dust holder dihitung "
        f"dari seluruh ({all_holders:,}) holder token dari daftar lengkap Helius, "
        f"di mana Real holder memiliki nilai saldo token saat ini ≥ ${dust_limit_usd:,.2f} "
        f"dan Dust holder < ${dust_limit_usd:,.2f}."
    )

    detail_rows = []
    for row in (holder_analysis.get("rows") or []):
        detail_rows.append({
            "Rank": row["rank"],
            "Wallet": row["wallet"],
            "Holding": f"{row['amount']:,.6g}",
            "Supply %": f"{row['supply_pct']:.3f}%",
            "Value USD": f"${row['value_usd']:,.2f}",
            "Buy 72h SOL": f"{row['buy_sol']:,.2f}",
            "Sell 72h SOL": f"{row['sell_sol']:,.2f}",
            "Sold/Buy": f"{row['sell_pct']:.1f}%",
            "Diamond hand": "✅ Yes" if row["diamond_hand"] else "❌ >10%",
            "Real ≥ dust": "✅ Real" if row["real_holder"] else "🪙 Dust",
            "Activity": row["activity"],
        })
    with st.expander("Lihat detail 100 top holder", expanded=False):
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True,
                     hide_index=True)
