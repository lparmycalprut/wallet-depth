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
                       save_4h_chunks_from_swaps, tx_dominance_from_daily)
from prepump_detector import evaluate_prepump
from signals import maybe_queue_complete_prepump, record_prepump_4pilar


# Deep (tua) greens / reds — no neon, no glow.
GREEN_DEEP = "#14532d"
GREEN_MID = "#166534"
GREEN_SOFT = "#dcfce7"
RED_DEEP = "#7f1d1d"
RED_MID = "#991b1b"
RED_SOFT = "#fee2e2"
SLATE = "#334155"
SLATE_SOFT = "#64748b"
AMBER = "#92400e"
INK = "#1e293b"
PAPER = "#f8fafc"

st.set_page_config(page_title="CVD Setup Emas", page_icon="📊",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown(
    f"""<style>
    .block-container {{padding-top: 1.4rem; max-width: 1180px;}}
    h1 {{font-size: 1.4rem !important; letter-spacing: -0.02em;
        color: {INK};}}
    .stMarkdown, .stCaption {{line-height: 1.55;}}
    [data-testid="stMetric"] {{padding: 0.35rem 0.6rem;
      background: {PAPER}; border-radius: 10px; border: 1px solid #e2e8f0;}}
    [data-testid="stMetricLabel"] {{font-size: 0.78rem !important;}}
    [data-testid="stMetricValue"] {{font-size: 1.15rem !important;}}

    .kpi-pass {{
        background: {GREEN_DEEP};
        border: 1px solid {GREEN_MID};
        color: {GREEN_SOFT};
        border-radius: 10px;
        padding: 14px 16px;
    }}
    .kpi-fail {{
        background: {RED_DEEP};
        border: 1px solid {RED_MID};
        color: {RED_SOFT};
        border-radius: 10px;
        padding: 14px 16px;
    }}
    .kpi-watch {{
        background: #422006;
        border: 1px solid {AMBER};
        color: #fef3c7;
        border-radius: 10px;
        padding: 14px 16px;
    }}
    .kpi-title {{font-size: 0.72rem; letter-spacing: 0.05em;
                text-transform: uppercase; opacity: 0.82; margin: 0;}}
    .kpi-value {{font-size: 1.45rem; margin: 6px 0 4px 0; line-height: 1.25;
                 font-weight: 700;}}
    .kpi-label {{font-size: 0.86rem; margin: 0; line-height: 1.4;}}
    .kpi-hint {{font-size: 0.74rem; opacity: 0.78; margin: 6px 0 0 0;
               font-weight: 500; line-height: 1.4;}}
    .idle-card {{
        background: {PAPER};
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 18px 20px;
        color: {INK};
        line-height: 1.55;
    }}
    .idle-card code {{
        background: #e2e8f0;
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 0.86rem;
    }}
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

st.title("📊 CVD — Setup Emas")
st.caption(
    "7 cek harian: |CVD/Vol| < 3.0% · CVD datar/naik · Buy TX ≥ 52% · "
    "Avg Sell > Buy · Whale diserap · LPS −40%…−75% · Lock ≥ 40%. "
    "Telegram hanya jika 7/7 Setup Emas. Fetch hanya setelah tombol diklik."
)

CONFIG = load_config()
helius_keys = tuple(get_helius_keys(config=CONFIG))
try:
    dust_limit_usd = float(CONFIG.get("dust_limit_usd", 5.0))
except (TypeError, ValueError):
    dust_limit_usd = 5.0

# Prefill from watchlist link (?ca=) without fetching.
qp_ca = (st.query_params.get("ca") or "").strip()
if qp_ca and st.session_state.get("cvd_last_qp") != qp_ca:
    st.session_state["cvd_ca_input"] = qp_ca
    st.session_state["cvd_last_qp"] = qp_ca

ca = st.text_input(
    "Contract Address",
    key="cvd_ca_input",
    placeholder="Tempel Solana CA, lalu klik Fetch…",
).strip()

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
        "Tempel CA atau buka tautan CVD dari watchlist, pilih 1–7 hari, "
        "lalu klik **Fetch**. Tidak ada request ke GMGN/Helius sampai "
        "tombol diklik."
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


def _banner_cls(verdict):
    if verdict in ("SETUP EMAS", "PASS"):
        return "kpi-pass"
    if verdict == "WATCH":
        return "kpi-watch"
    return "kpi-fail"


def render_kpi_card(card):
    css = "kpi-pass" if card.get("passed") else "kpi-fail"
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
            colors.append("#1e3a5f")
        elif change is not None and float(change) >= 100:
            colors.append(AMBER)
        elif abs(float(row.get("cvd_ratio_pct") or 99)) < 3.0:
            colors.append(GREEN_MID)
        else:
            colors.append(SLATE_SOFT)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=dates, y=volumes, name="Volume SOL",
            marker=dict(color=colors, line=dict(color=INK, width=0.3)),
            opacity=0.88,
            hovertemplate="%{x}<br>Vol %{y:.2f} SOL<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=dates, y=running, name="Running CVD SOL",
            mode="lines+markers",
            line=dict(color=SLATE, width=2.2),
            marker=dict(size=7, color=SLATE),
            hovertemplate="%{x}<br>CVD %{y:+.2f} SOL<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=dates, y=ratios, name="|CVD/Vol| %",
            mode="lines+markers",
            line=dict(color=AMBER, width=2, dash="dot"),
            marker=dict(size=6, color=AMBER),
            hovertemplate="%{x}<br>|CVD/Vol| %{y:.2f}%<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.add_hline(
        y=3.0, line_dash="dash", line_color=GREEN_MID,
        annotation_text="3.0% absorption", secondary_y=True,
    )
    fig.update_layout(
        height=400,
        margin=dict(t=48, b=24, l=12, r=12),
        legend=dict(orientation="h", y=1.14, font=dict(size=12, color=INK)),
        title=dict(
            text="Volume harian · Running CVD · |CVD/Vol| %",
            font=dict(size=14, color=INK),
        ),
        plot_bgcolor=PAPER,
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=12),
        hoverlabel=dict(font_size=12),
    )
    fig.update_yaxes(title_text="SOL", secondary_y=False, gridcolor="#e2e8f0")
    fig.update_yaxes(title_text="|CVD/Vol| %", secondary_y=True,
                     range=[0, max(8, max(ratios or [0]) * 1.2)],
                     gridcolor="#e2e8f0")
    fig.update_xaxes(gridcolor="#e2e8f0")
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})


def render_tx_dominance(rows):
    """Buy TX vs Sell TX dominance % per UTC day."""
    dom = tx_dominance_from_daily(rows)
    if not dom:
        st.info("Belum ada transaksi harian untuk dominasi Buy/Sell TX.")
        return
    dates = [r["date"] for r in dom]
    buy_pcts = [r["buy_tx_pct"] for r in dom]
    sell_pcts = [r["sell_tx_pct"] for r in dom]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Buy TX %", x=dates, y=buy_pcts,
        marker=dict(color=GREEN_MID),
        text=[f"{v:.0f}%" for v in buy_pcts],
        textposition="inside",
        textfont=dict(color=GREEN_SOFT, size=12),
        hovertemplate=("%{x}<br>Buy %{y:.1f}% · "
                       "%{customdata} TX<extra></extra>"),
        customdata=[r["buy_tx"] for r in dom],
    ))
    fig.add_trace(go.Bar(
        name="Sell TX %", x=dates, y=sell_pcts,
        marker=dict(color=RED_MID),
        text=[f"{v:.0f}%" for v in sell_pcts],
        textposition="inside",
        textfont=dict(color=RED_SOFT, size=12),
        hovertemplate=("%{x}<br>Sell %{y:.1f}% · "
                       "%{customdata} TX<extra></extra>"),
        customdata=[r["sell_tx"] for r in dom],
    ))
    fig.add_hline(
        y=52, line_dash="dash", line_color=GREEN_DEEP,
        annotation_text="Buy 52%",
        annotation_font=dict(size=11, color=GREEN_DEEP),
    )
    fig.update_layout(
        barmode="stack",
        height=340,
        margin=dict(t=48, b=24, l=12, r=12),
        legend=dict(orientation="h", y=1.14, font=dict(size=12, color=INK)),
        title=dict(
            text="Dominasi Buy TX vs Sell TX per hari (%)",
            font=dict(size=14, color=INK),
        ),
        yaxis=dict(title="Dominasi %", range=[0, 100],
                   gridcolor="#e2e8f0"),
        xaxis=dict(gridcolor="#e2e8f0"),
        plot_bgcolor=PAPER,
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=12),
        bargap=0.28,
    )
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})

    table = []
    for row in dom:
        side = {"buy": "Buy mendominasi",
                "sell": "Sell mendominasi",
                "even": "Seimbang"}.get(row["dominant"], "—")
        table.append({
            "Tanggal": row["date"],
            "Buy TX": row["buy_tx"],
            "Sell TX": row["sell_tx"],
            "Total": row["total_tx"],
            "Buy %": f"{row['buy_tx_pct']:.1f}%",
            "Sell %": f"{row['sell_tx_pct']:.1f}%",
            "Dominasi": side,
        })
    st.dataframe(pd.DataFrame(table), use_container_width=True,
                 hide_index=True)


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
        buy_pct = float(row.get("buy_tx_pct") or 0)
        sell_pct = row.get("sell_tx_pct")
        if sell_pct is None:
            sell_pct = 100.0 - buy_pct
        table.append({
            "Tanggal": row.get("date"),
            "Buy TX": int(row.get("buy_tx") or 0),
            "Sell TX": int(row.get("sell_tx") or 0),
            "Buy %": f"{buy_pct:.1f}%",
            "Sell %": f"{float(sell_pct):.1f}%",
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


skey = f"cvd4p::{days}d::{ca}"
cached = st.session_state.get(skey)

if not run and not cached:
    short = f"{ca[:8]}…{ca[-4:]}" if len(ca) > 14 else ca
    st.markdown(
        f"<div class='idle-card'>"
        f"<b>Siap dianalisis</b> — <code>{short}</code><br>"
        f"Rentang: <b>{day_label}</b>. "
        f"Klik <b>Fetch &amp; Analisis Multi-Hari</b> untuk mengambil "
        f"swap GMGN (fallback Helius), mengevaluasi Setup Emas 7 cek, "
        f"dan menghitung dominasi Buy TX vs Sell TX per hari. "
        f"Tidak ada fetch otomatis."
        f"</div>",
        unsafe_allow_html=True,
    )
    st.stop()

if run:
    pool, symbol, price_now, mc_now = get_pool(ca)
    if not pool:
        st.error("Token tidak ditemukan di DexScreener.")
        st.stop()
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
    progress.progress(0.75, text="Menyimpan chunk 4 jam + Setup Emas…")
    swaps = _dedupe_swaps(bundle.get("swaps") or [])
    save_4h_chunks_from_swaps(ca, swaps, symbol=symbol)
    daily = bundle.get("daily") or calculate_daily_cvd(swaps)
    persist_daily_snapshot(ca, symbol, daily)
    ev = bundle.get("evaluation") or evaluate_prepump(
        swaps, daily_rows=daily, include_today=True)
    ev_daily = evaluate_prepump(
        swaps, daily_rows=daily, include_today=False)
    try:
        record_prepump_4pilar(ca, symbol, ev_daily, price=price_now)
    except Exception:
        pass
    tg_sent = False
    try:
        tg_sent = bool(maybe_queue_complete_prepump(
            ca, symbol, ev_daily, price=price_now))
    except Exception:
        tg_sent = False
    holder_data = fetch_holder_snapshot(ca, helius_keys)
    st.session_state[skey] = {
        "swaps": swaps,
        "daily": daily,
        "evaluation": ev,
        "evaluation_daily": ev_daily,
        "ts": time.time(),
        "src": "GMGN / Helius · Setup Emas",
        "days": days,
        "pool": pool,
        "symbol": symbol,
        "price_now": price_now,
        "mc_now": mc_now,
        "holders": holder_data,
        "telegram_queued": tg_sent,
    }
    progress.empty()

state = st.session_state[skey]
swaps_all = _dedupe_swaps(state.get("swaps") or [])
daily_rows = state.get("daily") or calculate_daily_cvd(swaps_all)
evaluation = state.get("evaluation") or evaluate_prepump(
    swaps_all, daily_rows=daily_rows, include_today=True)
ev_daily = state.get("evaluation_daily") or evaluate_prepump(
    swaps_all, daily_rows=daily_rows, include_today=False)
fetched_at = float(state.get("ts") or time.time())
symbol = state.get("symbol") or "?"
mc_now = float(state.get("mc_now") or 0)
price_now = float(state.get("price_now") or 0)
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
total = int(evaluation.get("total") or 7)
score = evaluation.get("score")
score_txt = f" · skor {int(score)}" if score is not None else ""
st.markdown(
    f"<div class='{_banner_cls(verdict)}' style='margin-bottom:14px'>"
    f"<p class='kpi-title'>${symbol} · Setup Emas</p>"
    f"<p class='kpi-value'>{verdict} · {passed}/{total}"
    f"{score_txt} · {phase}</p>"
    f"<p class='kpi-hint'>7 cek: |CVD/Vol| &lt; 3.0% · CVD datar/naik · "
    f"Buy TX ≥ 52% · Avg Sell &gt; Buy · Whale diserap · "
    f"LPS −40%…−75% · Lock ≥ 40%. Telegram hanya 7/7 hari UTC penuh.</p>"
    f"</div>",
    unsafe_allow_html=True,
)
if state.get("telegram_queued"):
    st.success(
        "Sinyal Telegram diantrikan — Setup Emas 7/7 "
        f"({ev_daily.get('date') or '—'})."
    )
elif ev_daily.get("setup_emas") or ev_daily.get("verdict") in (
        "SETUP EMAS", "PASS"):
    st.caption(
        "Setup Emas hari UTC penuh sudah 7/7 — Telegram sudah "
        "pernah dikirim untuk tanggal ini, atau sedang di-dedupe."
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

# ---- TX dominance ---------------------------------------------------------
st.markdown("#### ⚖️ Buy TX vs Sell TX — dominasi per hari")
st.caption(
    "Persentase jumlah transaksi (bukan volume SOL). "
    "Buy ≥ 52% = akumulasi cicil (Pilar 2)."
)
render_tx_dominance(daily_rows)

# ---- Chart + table --------------------------------------------------------
st.markdown("#### 📈 Day-by-day progression")
render_daily_chart(daily_rows)
render_daily_table(daily_rows, evaluation)

# ---- Holder lock (feeds Pilar 3 when available) --------------------------
st.markdown("#### 👥 Top 100 Holder / Supply Lock")
holder_data = state.get("holders") or {}
if not holder_data.get("ok"):
    st.caption(holder_data.get("error")
               or "Holder tidak dimuat. Klik Fetch untuk mengambil.")
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
    if run:
        ev_locked = evaluate_prepump(
            swaps_all, daily_rows=daily_rows,
            holder_lock_pct=diamond_pct, include_today=True)
        st.session_state[skey]["evaluation"] = ev_locked
        ev_locked_daily = evaluate_prepump(
            swaps_all, daily_rows=daily_rows,
            holder_lock_pct=diamond_pct, include_today=False)
        st.session_state[skey]["evaluation_daily"] = ev_locked_daily
        try:
            record_prepump_4pilar(
                ca, symbol, ev_locked_daily, price=price_now)
            if maybe_queue_complete_prepump(
                    ca, symbol, ev_locked_daily, price=price_now):
                st.session_state[skey]["telegram_queued"] = True
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
    "`data/cvd_4h_chunks/<mint>.json`. Ubah CA atau rentang hari lalu "
    "klik Fetch lagi — tidak ada fetch otomatis."
)
