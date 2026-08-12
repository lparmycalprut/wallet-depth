# -*- coding: utf-8 -*-
"""CVD Deep Analysis — 4-pillar pre-pump + multi-day manual fetch."""
import os
import sys
import time

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import (get_helius_keys, get_market,
                  get_holders as core_get_holders,
                  get_supply as core_get_supply, load_config)
from cvd import (MIN_SOL, top_holder_analysis)
from cvd_daily import (calculate_daily_cvd, persist_daily_snapshot,
                       save_4h_chunks_from_swaps)
from prepump_detector import evaluate_prepump
from signals import record_prepump_4pilar


st.set_page_config(page_title="CVD 4 Pilar", page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown(
    """<style>
    .block-container {padding-top: 1.2rem; max-width: 1400px;}
    h1 {font-size: 1.3rem !important;}
    [data-testid="stMetric"] {padding: 0.2rem 0.5rem;
      background: rgba(128,128,128,0.07); border-radius: 8px;}
    [data-testid="stMetricLabel"] {font-size: 0.72rem !important;}
    [data-testid="stMetricValue"] {font-size: 1.1rem !important;}

    .glowing-pass {
        background-color: rgba(0, 255, 136, 0.08);
        border: 1.5px solid #00ff88 !important;
        box-shadow: 0 0 15px rgba(0, 255, 136, 0.4),
                    inset 0 0 8px rgba(0, 255, 136, 0.2);
        color: #00ff88 !important;
        border-radius: 8px;
        padding: 12px;
        font-weight: bold;
    }
    .glowing-fail {
        background-color: rgba(255, 77, 77, 0.08);
        border: 1.5px solid #ff4d4d !important;
        box-shadow: 0 0 15px rgba(255, 77, 77, 0.4),
                    inset 0 0 8px rgba(255, 77, 77, 0.2);
        color: #ff4d4d !important;
        border-radius: 8px;
        padding: 12px;
        font-weight: bold;
    }
    .kpi-title {font-size: 0.72rem; letter-spacing: 0.04em;
                text-transform: uppercase; opacity: 0.85; margin: 0;}
    .kpi-value {font-size: 1.55rem; margin: 4px 0 2px 0; line-height: 1.2;}
    .kpi-label {font-size: 0.82rem; margin: 0;}
    .kpi-hint {font-size: 0.68rem; opacity: 0.7; margin: 4px 0 0 0;
               font-weight: 500;}
    </style>""",
    unsafe_allow_html=True,
)

DAY_OPTIONS = {
    "1 Hari (24 Jam)": 1,
    "2 Hari (48 Jam)": 2,
    "3 Hari (72 Jam)": 3,
    "4 Hari (96 Jam)": 4,
    "5 Hari (120 Jam)": 5,
    "6 Hari (144 Jam)": 6,
    "7 Hari (168 Jam - Full Week Cycle)": 7,
}

st.title("📊 CVD — 4 Pilar Pre-Pump")
st.caption(
    "Evaluasi Wyckoff multi-hari: Absorption |CVD/Vol| < 3.0%, "
    "Buy TX ≥ 52%, Avg Sell > Avg Buy, LPS volume kering, ignition 15m/1h. "
    "Fetch inkremental 1–7 hari disimpan ke cache 4 jam + `cvd_daily.json`."
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

col_days, col_btn = st.columns([2, 1])
day_label = col_days.selectbox(
    "Rentang fetch multi-hari",
    list(DAY_OPTIONS.keys()),
    index=2,
)
days = DAY_OPTIONS[day_label]
run = col_btn.button(
    "⚡ Fetch & Analisis Multi-Hari",
    type="primary",
    use_container_width=True,
)

if not ca:
    st.info(
        "Paste CA lalu pilih 1–7 hari. Tombol fetch mengambil swap GMGN "
        "(fallback Helius), mengevaluasi 4 pilar, dan menyimpan hasil."
    )
    st.stop()


@st.cache_data(ttl=120, show_spinner=False)
def get_pool(contract: str):
    market = get_market(contract)
    pools = market.get("pair_addresses") or []
    if not market or not pools:
        return None, None, None, None
    return (
        pools[0],
        market.get("symbol", "?"),
        float(market.get("price_usd") or 0),
        float(market.get("marketcap") or 0),
    )


@st.cache_data(ttl=300, show_spinner=False)
def fetch_holder_snapshot(contract: str, key_pool: tuple) -> dict:
    if key_pool:
        try:
            supply, decimals = core_get_supply(key_pool, contract)
            holders = core_get_holders(key_pool, contract)
            if (holders is not None and not holders.empty
                    and "owner" in holders.columns
                    and "raw_amount" in holders.columns):
                normalized = holders[["owner", "raw_amount"]].copy()
                normalized["owner"] = normalized["owner"].astype(str)
                normalized["amount"] = (
                    pd.to_numeric(normalized["raw_amount"], errors="coerce")
                    .fillna(0.0) / (10 ** int(decimals))
                )
                normalized = normalized[normalized["amount"] > 0]
                normalized = normalized.sort_values(
                    "amount", ascending=False)
                return {
                    "ok": True,
                    "holders": normalized[["owner", "amount"]].to_dict(
                        "records"),
                    "supply": float(supply or 0.0),
                    "total_holders": int(len(normalized)),
                    "source": "Helius",
                }
        except Exception:
            pass
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
                    "total_holders": len(holders_records),
                    "source": "Cron Snapshot",
                }
    except Exception:
        pass
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
                "total_holders": int(
                    stat.get("total_holders") or len(holders_records)),
                "source": "GMGN (Top Holders)",
            }
    except Exception:
        pass
    return {"ok": False, "error": "Data holder tidak tersedia."}


def _dedupe_swaps(swaps):
    seen = {}
    for swap in swaps or []:
        if len(swap) < 4:
            continue
        key = (swap[0], float(swap[1]), int(swap[2]), str(swap[3]))
        seen[key] = list(key)
    return [seen[k] for k in sorted(seen, key=lambda item: item[2])]


def render_kpi_card(card):
    css = "glowing-pass" if card.get("passed") else "glowing-fail"
    st.markdown(
        f"<div class='{css}'>"
        f"<p class='kpi-title'>{card.get('title', '')}</p>"
        f"<p class='kpi-value'>{card.get('value', '—')}</p>"
        f"<p class='kpi-label'>{card.get('label', '')}</p>"
        f"<p class='kpi-hint'>{card.get('hint', '')}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_daily_chart(rows):
    if not rows:
        st.info("Belum ada baris harian untuk digambar.")
        return
    dates = [r["date"] for r in rows]
    volumes = [float(r.get("volume_sol") or 0) for r in rows]
    running = [float(r.get("running_cvd_sol") or 0) for r in rows]
    ratios = [abs(float(r.get("cvd_ratio_pct") or 0)) for r in rows]
    colors = []
    for row in rows:
        status = str(row.get("status") or "")
        change = row.get("volume_change_pct")
        if status.startswith("KERING"):
            colors.append("#38bdf8")
        elif change is not None and float(change) >= 100:
            colors.append("#f97316")
        elif abs(float(row.get("cvd_ratio_pct") or 99)) < 3.0:
            colors.append("#00ff88")
        else:
            colors.append("#64748b")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=dates, y=volumes, name="Volume SOL",
            marker=dict(color=colors, line=dict(color="#0f172a", width=0.4)),
            opacity=0.85,
            hovertemplate="%{x}<br>Vol %{y:.2f} SOL<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=dates, y=running, name="Running CVD SOL",
            mode="lines+markers",
            line=dict(color="#e2e8f0", width=2.4),
            marker=dict(size=7),
            hovertemplate="%{x}<br>CVD %{y:+.2f} SOL<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=dates, y=ratios, name="|CVD/Vol| %",
            mode="lines+markers",
            line=dict(color="#fbbf24", width=2, dash="dot"),
            marker=dict(size=6),
            hovertemplate="%{x}<br>|CVD/Vol| %{y:.2f}%<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.add_hline(
        y=3.0, line_dash="dash", line_color="#00ff88",
        annotation_text="3.0% absorption", secondary_y=True,
    )
    fig.update_layout(
        height=420,
        margin=dict(t=40, b=20, l=10, r=10),
        legend=dict(orientation="h", y=1.12),
        title=dict(
            text="Volume harian · Running CVD · |CVD/Vol| %",
            font=dict(size=13),
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(title_text="SOL", secondary_y=False)
    fig.update_yaxes(title_text="|CVD/Vol| %", secondary_y=True,
                     range=[0, max(8, max(ratios or [0]) * 1.2)])
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})


def render_daily_table(rows, evaluation):
    phase_by_date = {}
    ev_date = (evaluation or {}).get("date")
    ev_phase = (evaluation or {}).get("phase")
    if ev_date:
        phase_by_date[ev_date] = ev_phase
    table = []
    for row in rows or []:
        change = row.get("volume_change_pct")
        phase = phase_by_date.get(row["date"]) or row.get("status") or "—"
        table.append({
            "Tanggal": row.get("date"),
            "TX B/S": f"{row.get('buy_tx', 0)}/{row.get('sell_tx', 0)}",
            "Buy TX %": f"{float(row.get('buy_tx_pct') or 0):.1f}%",
            "Volume SOL": round(float(row.get("volume_sol") or 0), 2),
            "% Vol vs H-1": (
                "—" if change is None else f"{float(change):+.1f}%"
            ),
            "Net Δ SOL": round(float(row.get("delta_sol") or 0), 2),
            "|CVD/Vol|": f"{abs(float(row.get('cvd_ratio_pct') or 0)):.2f}%",
            "Avg S/B": (
                f"{float(row.get('avg_sell_sol') or 0):.3f} / "
                f"{float(row.get('avg_buy_sol') or 0):.3f}"
            ),
            "Fase": phase,
        })
    st.dataframe(pd.DataFrame(table), use_container_width=True,
                 hide_index=True)


pool, symbol, price_now, mc_now = get_pool(ca)
if not pool:
    st.error("Token tidak ditemukan di DexScreener.")
    st.stop()

skey = f"cvd4p::{days}d::{ca}"
if run or skey not in st.session_state:
    from cvd import fetch_and_analyze_multiday
    api_key = helius_keys[0] if helius_keys else ""
    progress = st.progress(0.15, text=f"Fetching GMGN {days} hari…")
    try:
        bundle = fetch_and_analyze_multiday(
            ca, days, pool=pool, api_key=api_key, symbol=symbol,
            include_today=True,
        )
    except Exception as exc:  # noqa: BLE001
        progress.empty()
        st.error(f"Fetch gagal: {exc}")
        st.stop()
    progress.progress(0.85, text="Menyimpan chunk 4 jam + evaluasi 4 pilar…")
    swaps = _dedupe_swaps(bundle.get("swaps") or [])
    save_4h_chunks_from_swaps(ca, swaps, symbol=symbol)
    daily = bundle.get("daily") or calculate_daily_cvd(swaps)
    persist_daily_snapshot(ca, symbol, daily)
    ev = bundle.get("evaluation") or evaluate_prepump(
        swaps, daily_rows=daily, include_today=True)
    try:
        record_prepump_4pilar(ca, symbol, ev, price=price_now)
    except Exception:
        pass
    st.session_state[skey] = {
        "swaps": swaps,
        "daily": daily,
        "evaluation": ev,
        "ts": time.time(),
        "src": "GMGN / Helius · 4-pilar",
        "days": days,
    }
    progress.empty()

state = st.session_state[skey]
swaps_all = _dedupe_swaps(state.get("swaps") or [])
daily_rows = state.get("daily") or calculate_daily_cvd(swaps_all)
evaluation = state.get("evaluation") or evaluate_prepump(
    swaps_all, daily_rows=daily_rows, include_today=True)
fetched_at = float(state.get("ts") or time.time())
st.caption(
    f"Source: {state.get('src', '?')} · {len(swaps_all):,} swaps · "
    f"{state.get('days', days)} hari · MC ${mc_now:,.0f}"
)

if not swaps_all:
    st.warning(f"No swaps ≥ {MIN_SOL:g} SOL in the selected window.")

# ---- Verdict banner -------------------------------------------------------
verdict = evaluation.get("verdict") or "FAIL"
phase = evaluation.get("phase") or "NORMAL"
passed = int(evaluation.get("passed") or 0)
banner_cls = (
    "glowing-pass" if verdict == "PASS"
    else ("glowing-fail" if verdict in ("FAIL", "STEALTH DUMP")
          else "glowing-pass")
)
if verdict == "WATCH":
    banner_cls = "glowing-pass"
st.markdown(
    f"<div class='{banner_cls}' style='margin-bottom:12px'>"
    f"<p class='kpi-title'>${symbol} · 4 Pilar Pre-Pump</p>"
    f"<p class='kpi-value'>{verdict} · {passed}/4 · {phase}</p>"
    f"<p class='kpi-hint'>Ambang ketat: |CVD/Vol| &lt; 3.0% · "
    f"Buy TX ≥ 52% · Avg Sell &gt; Avg Buy · LPS −40% s/d −85%</p>"
    f"</div>",
    unsafe_allow_html=True,
)

# ---- 4 KPI cards ----------------------------------------------------------
kpi = evaluation.get("kpi") or []
if kpi:
    cols = st.columns(4)
    for col, card in zip(cols, kpi):
        with col:
            render_kpi_card(card)

# ---- Pillar details -------------------------------------------------------
with st.expander("Rincian 4 pilar", expanded=False):
    for pillar in evaluation.get("pillars") or []:
        mark = "✅ PASS" if pillar.get("passed") else "❌ FAIL"
        st.markdown(f"**{mark} · {pillar.get('id')}** — "
                    f"{pillar.get('detail')}")

# ---- Chart + table --------------------------------------------------------
st.markdown("#### 📈 Day-by-day progression")
render_daily_chart(daily_rows)
render_daily_table(daily_rows, evaluation)

# ---- Holder lock (feeds Pilar 3 when available) --------------------------
st.markdown("#### 👥 Top 100 Holder / Supply Lock")
with st.spinner("Mengambil holder…"):
    holder_data = fetch_holder_snapshot(ca, helius_keys)
if not holder_data.get("ok"):
    st.caption(holder_data.get("error", "Holder tidak tersedia."))
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
    diamond_pct = float(holder_analysis.get("diamond_pct") or 0.0)
    lock_ok = diamond_pct >= 40.0
    lock_card = {
        "title": "Top 100 Supply Lock",
        "value": f"{diamond_pct:.1f}%",
        "passed": lock_ok,
        "label": ("✅ PURE ACC ≥ 40%" if lock_ok
                  else "❌ LOCK < 40%"),
        "hint": f"{diamond_count}/{n_top} diamond · "
                f"sumber {holder_data.get('source', '?')}",
    }
    render_kpi_card(lock_card)
    # Re-evaluate P3 with the live lock if the user just fetched.
    if run:
        ev_locked = evaluate_prepump(
            swaps_all, daily_rows=daily_rows,
            holder_lock_pct=diamond_pct, include_today=True)
        st.session_state[skey]["evaluation"] = ev_locked
        try:
            record_prepump_4pilar(ca, symbol, ev_locked, price=price_now)
        except Exception:
            pass

    detail_rows = []
    for row in (holder_analysis.get("rows") or []):
        detail_rows.append({
            "Rank": row["rank"],
            "Wallet": row["wallet"],
            "Holding": f"{row['amount']:,.6g}",
            "Supply %": f"{row['supply_pct']:.3f}%",
            "Value USD": f"${row['value_usd']:,.2f}",
            "Buy SOL": f"{row['buy_sol']:,.2f}",
            "Sell SOL": f"{row['sell_sol']:,.2f}",
            "Sold/Buy": f"{row['sell_pct']:.1f}%",
            "Diamond": "✅" if row["diamond_hand"] else "❌",
        })
    with st.expander("Detail 100 top holder", expanded=False):
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True,
                     hide_index=True)

st.caption(
    f"Diambil {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(fetched_at))}. "
    "Data transaksi di-append ke `cvd_daily.json` dan "
    "`data/cvd_4h_chunks/<mint>.json`."
)
