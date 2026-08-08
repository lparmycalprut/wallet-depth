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
    """Fetch and normalize the holder list for this CA (Helius → Cron Snapshot → GMGN)."""
    if key_pool:
        try:
            supply, decimals = core_get_supply(key_pool, contract)
            holders = core_get_holders(key_pool, contract)
            if holders is not None and not holders.empty and "owner" in holders.columns and "raw_amount" in holders.columns:
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
                    "source": "Helius",
                }
        except Exception:
            pass

    # Fallback 1: Cron Snapshot dari holder_snapshots.json (4-Hourly Cron)
    try:
        from cvd import load_holder_snapshots
        snaps = (load_holder_snapshots() or {}).get(contract) or {}
        if snaps:
            latest_snap = max(snaps.values(), key=lambda s: s.get("ts", 0))
            raw_holders = latest_snap.get("holders") or []
            holders_records = [
                {"owner": str(item[0]), "amount": float(item[1])}
                for item in raw_holders
                if len(item) >= 2 and float(item[1]) > 0
            ]
            if holders_records:
                holders_records.sort(key=lambda x: x["amount"], reverse=True)
                return {
                    "ok": True,
                    "holders": holders_records,
                    "supply": float(latest_snap.get("supply") or 0.0),
                    "decimals": 0,
                    "total_holders": len(holders_records),
                    "source": "Cron Snapshot (4-hourly)",
                }
    except Exception:
        pass

    # Fallback 2: GMGN token_stat
    try:
        from core import gmgn_token_stat
        stat = gmgn_token_stat(contract)
        raw_holders = stat.get("holders") or []
        holders_records = [
            {"owner": str(item[0]), "amount": float(item[1])}
            for item in raw_holders
            if len(item) >= 2 and float(item[1]) > 0
        ]
        if holders_records:
            holders_records.sort(key=lambda x: x["amount"], reverse=True)
            return {
                "ok": True,
                "holders": holders_records,
                "supply": float(stat.get("supply") or 0.0),
                "decimals": 0,
                "total_holders": int(stat.get("total_holders") or len(holders_records)),
                "source": "GMGN (Top Holders)",
            }
    except Exception:
        pass

    return {"ok": False, "error": "Data holder tidak tersedia dari Helius, Cron Snapshot, maupun GMGN."}


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
    # 1. Window saat ini [now - window_h*3600, now]
    if df.empty:
        segment_now = df
    else:
        segment_now = df[df["ts"] >= fetched_at - window_h * 3600]
    if segment_now.empty:
        profiles_now = {}
    else:
        profiles_now = wallet_profiles(
            list(segment_now[["side", "sol", "ts", "wallet"]]
                 .itertuples(index=False, name=None))
        )
    conv_now = conviction_split(profiles_now, whale_min_sol=WHALE_SOL)

    # 2. Window sebelumnya (periode lampau dengan durasi yang sama)
    # [now - 2*window_h*3600, now - window_h*3600]
    if df.empty:
        segment_prev = df
    else:
        segment_prev = df[(df["ts"] >= fetched_at - 2 * window_h * 3600) &
                          (df["ts"] < fetched_at - window_h * 3600)]
    if segment_prev.empty:
        conv_prev_pct = None
    else:
        profiles_prev = wallet_profiles(
            list(segment_prev[["side", "sol", "ts", "wallet"]]
                 .itertuples(index=False, name=None))
        )
        conv_prev_pct = conviction_split(profiles_prev, whale_min_sol=WHALE_SOL)["conviction_pct"]

    now_pct = conv_now["conviction_pct"]
    delta_pct = (now_pct - conv_prev_pct) if conv_prev_pct is not None else None
    net_pure = conv_now.get("pure_buy", 0.0) - conv_now.get("pure_sell", 0.0)

    win_stats[window_h] = {
        "conviction_pct": now_pct,
        "prev_pct": conv_prev_pct,
        "delta_pct": delta_pct,
        "net_pure": net_pure,
    }

fig_conviction = go.Figure()

x_vals = [f"{h}H" for h in CONVICTION_WINDOWS]
y_vals = [win_stats[h]["conviction_pct"] for h in CONVICTION_WINDOWS]
bar_colors = []
labels = []
hovers = []

for h in CONVICTION_WINDOWS:
    stats = win_stats[h]
    pct = stats["conviction_pct"]
    dpct = stats["delta_pct"]
    netp = stats["net_pure"]
    if dpct is None:
        bar_colors.append("#3b82f6")  # Biru netral jika belum ada data periode sebelumnya
        labels.append(f"{pct:.0f}%")
        delta_str = "Data awal"
    elif dpct >= 0:
        bar_colors.append("#22c55e")  # Hijau jika tumbuh/naik
        labels.append(f"{pct:.0f}%<br>(▲+{dpct:.1f}%)")
        delta_str = f"▲ +{dpct:.1f}% (Naik)"
    else:
        bar_colors.append("#ef4444")  # Merah jika turun
        labels.append(f"{pct:.0f}%<br>(▼{dpct:.1f}%)")
        delta_str = f"▼ {dpct:.1f}% (Turun)"

    prev_str = f"{stats['prev_pct']:.1f}%" if stats['prev_pct'] is not None else "—"
    hovers.append(
        f"<b>{h}H Timeframe</b><br>"
        f"Conviction Saat Ini: <b>{pct:.1f}%</b><br>"
        f"Periode Sebelumnya: <b>{prev_str}</b><br>"
        f"Pertumbuhan / Penurunan: <b>{delta_str}</b><br>"
        f"Net Pure Flow: <b>{netp:+.1f} SOL</b>"
    )

fig_conviction.add_trace(go.Bar(
    x=x_vals,
    y=y_vals,
    text=labels,
    textposition="outside",
    marker=dict(color=bar_colors, line=dict(color="white", width=1.5)),
    hoverinfo="text",
    hovertext=hovers,
    showlegend=False,
))

# Garis referensi
fig_conviction.add_hline(
    y=50, line_dash="dot", line_color="#22c55e", annotation_text="50% (Solid)"
)
fig_conviction.add_hline(
    y=30, line_dash="dot", line_color="#ef4444", annotation_text="30% (Weak)"
)

fig_conviction.update_layout(
    height=330,
    margin=dict(t=45, b=10, l=10, r=10),
    yaxis=dict(title="Conviction %", range=[0, 118]),
    xaxis=dict(title="Timeframe"),
    title=dict(
        text="Pertumbuhan & Penurunan Conviction per Timeframe (Tanpa Garis Gabungan)",
        font=dict(size=13)
    ),
)
st.plotly_chart(fig_conviction, use_container_width=True,
                config={"displayModeBar": False})

# Tampilkan metrik pertumbuhan/penurunan dalam bentuk kolom ringkas
st.markdown("##### 📈 Pertumbuhan / Penurunan Conviction vs Periode Sebelumnya")
cols_conv = st.columns(len(CONVICTION_WINDOWS))
for i, window_h in enumerate(CONVICTION_WINDOWS):
    stats = win_stats[window_h]
    now_pct = stats["conviction_pct"]
    d_pct = stats["delta_pct"]
    net_p = stats["net_pure"]
    cols_conv[i].metric(
        label=f"⏱️ {window_h}H",
        value=f"{now_pct:.1f}%",
        delta=f"{d_pct:+.1f}%" if d_pct is not None else "data awal",
        help=f"Net Pure Flow: {net_p:+.1f} SOL"
    )

st.caption(
    "Setiap batang mencatat tingkat conviction pada timeframe tersebut, dengan indikator warna "
    "(🟢 Naik / 🔴 Turun) serta nilai perubahan (Δ%) dibandingkan periode sebelumnya dengan durasi yang sama — "
    "bukan digabungkan menjadi garis tren."
)

# ---------------------------------------------------------------------------
# Top 100 holders: diamond hand + real-vs-dust.
# ---------------------------------------------------------------------------
with st.spinner("Mengambil holder lengkap dari Helius / Snapshot…"):
    holder_data = fetch_holder_snapshot(ca, helius_keys)

st.markdown("#### 👥 Top 100 Holder Analysis")
if not holder_data.get("ok"):
    st.warning(holder_data.get("error", "Data holder tidak tersedia."))
    st.caption(
        "Analisis top holder membutuhkan Helius API key, snapshot cron 4 jam, atau data GMGN. "
        "Swap conviction di atas tetap dapat dibaca dari GMGN."
    )
else:
    src = holder_data.get("source", "Helius")
    if src != "Helius":
        st.caption(f"ℹ️ Data top holder dimuat dari **{src}** (Helius live tidak dikonfigurasi).")
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
