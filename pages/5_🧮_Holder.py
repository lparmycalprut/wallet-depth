# -*- coding: utf-8 -*-
"""Analisa holder — dust % MC, grafik 4 jam, kohort mid-tier.

Halaman di bawah CVD. Fokus: dust nambah = indikasi dump.
- ≥ 1% MC → hati-hati
- >  2% MC → limit / DUMP
Kohort Crab+Fish di-freeze 4 jam; sisa token (bukan USD) mengukur exit pilar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

import matplotlib.pyplot as plt
import streamlit as st

from holder_history import (DUST_CAUTION_PCT, DUST_LIMIT_PCT, dust_flag,
                            history_for_mint, ingest_many,
                            load_holder_history, merge_points, resample_4h,
                            seed_from_status)
from links import external_links_html
from silent_accumulation import analyze_token
from silent_status import load_silent_status
from watchlist import add_to_watchlist, load_watchlist

st.set_page_config(page_title="Holder Analytic", page_icon="🧮",
                   layout="wide")
st.title("🧮 Holder Analytic")
st.caption(
    "Dust holder (nilai ≤ $10) sebagai jejak dump: **≥ 1% MC hati-hati**, "
    f"**> {DUST_LIMIT_PCT:.0f}% MC limit**. Grafik di-resample **4 jam sekali**. "
    "Pilar harga = kohort Crab+Fish yang di-freeze: yang diukur sisa "
    "**token**, bukan dollar.")

SOLANA_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _normalize_ca(value) -> str:
    return str(value or "").strip()


def _wib(ts):
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(hours=7)
    return when.strftime("%d %b %H:%M") + " WIB"


def _fmt_pct(value, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}%"


def _points_for(mint: str, status_token: dict | None, store: dict) -> list:
    status_pts = (status_token or {}).get("history") or []
    return merge_points(history_for_mint(store, mint), status_pts)


def _dust_badge(flag: dict) -> str:
    level = flag.get("level") or "unknown"
    label = str(flag.get("label") or "—")
    if flag.get("rising") and level in ("caution", "limit"):
        label = f"{label} ↑"
    colors = {
        "ok": ("#14532d", "#dcfce7"),
        "caution": ("#854d0e", "#fef9c3"),
        "limit": ("#7f1d1d", "#fee2e2"),
    }
    bg, fg = colors.get(level, ("#e2e8f0", "#000000"))
    return (f'<span style="display:inline-block;padding:.28rem .58rem;'
            f'border-radius:8px;font-size:.78rem;font-weight:800;'
            f'background:{bg};color:{fg};">{label}</span>')


def _history_charts(points: list[dict]) -> None:
    sampled = resample_4h(points)
    if len(sampled) < 2:
        st.info("Belum cukup titik untuk grafik 4 jam. Scan ulang beberapa "
                "kali (cron ~15 menit atau tombol di bawah) supaya bucket "
                "4 jam terisi.")
        return
    labels = [_wib(p.get("ts")) for p in sampled]
    dust_pct = [p.get("dust_pct_mc") if p.get("dust_pct_mc") is not None
                else float("nan") for p in sampled]
    dust_n = [p.get("dust_count") or 0 for p in sampled]
    cohort = [p.get("cohort_token_pct") if p.get("cohort_token_pct") is not None
              else float("nan") for p in sampled]

    fig, axis = plt.subplots(figsize=(11, 4.2))
    axis.plot(labels, dust_pct, color="#b45309", marker="o", linewidth=2.2,
              label="Dust % MC")
    axis.axhline(DUST_CAUTION_PCT, color="#ca8a04", linestyle="--",
                 linewidth=1, label="Hati-hati 1%")
    axis.axhline(DUST_LIMIT_PCT, color="#b91c1c", linestyle="--",
                 linewidth=1, label="Limit 2%")
    axis.set_ylabel("Dust % marketcap")
    axis.tick_params(axis="x", rotation=30)
    axis.grid(alpha=.2)
    axis.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    fig2, ax1 = plt.subplots(figsize=(11, 3.6))
    ax2 = ax1.twinx()
    ax1.bar(labels, dust_n, color="#f59e0b", alpha=.7, label="Dust wallet")
    ax2.plot(labels, cohort, color="#1d4ed8", marker="s", linewidth=2,
             label="Sisa token pilar (%)")
    ax1.set_ylabel("Jumlah dust wallet")
    ax2.set_ylabel("Kohort Crab+Fish sisa %")
    ax1.tick_params(axis="x", rotation=30)
    ax1.grid(axis="y", alpha=.2)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, frameon=False, loc="upper left")
    fig2.tight_layout()
    st.pyplot(fig2, use_container_width=True)
    plt.close(fig2)


watchlist = load_watchlist()
mints = list(watchlist)
status = load_silent_status()
store = seed_from_status(load_holder_history(), status)

query_mint = str(st.query_params.get("mint") or "") if "mint" in st.query_params else ""
session_mint = st.session_state.get("holder_mint") or ""
candidate = session_mint or query_mint
selected = candidate if candidate in mints else (candidate or (mints[0] if mints else ""))

with st.expander("🔍 Token di luar watchlist — tempel CA",
                 expanded=not bool(selected)):
    with st.form("holder-ca-form"):
        ca_input = st.text_input(
            "Contract address (CA)",
            placeholder="So11111111111111111111111111111111111111112")
        submitted = st.form_submit_button("Buka analisa", type="primary")
    if submitted:
        manual_ca = _normalize_ca(ca_input)
        if not manual_ca:
            st.warning("Masukkan contract address terlebih dahulu.")
        elif not SOLANA_CA_RE.match(manual_ca):
            st.warning("Format CA Solana tidak valid.")
        else:
            st.session_state["holder_mint"] = manual_ca
            st.query_params["mint"] = manual_ca
            st.rerun()

if not selected:
    st.info("Belum ada token. Tambah watchlist di halaman utama, atau "
            "tempel CA di atas.")
    st.stop()

st.session_state["holder_mint"] = selected
in_watchlist = selected in watchlist
labels = {mint: f"${str(watchlist[mint].get('symbol') or '?').upper()} — "
                f"{mint[:8]}…" for mint in mints}

if in_watchlist:
    mint = st.selectbox("Token", mints, index=mints.index(selected),
                        format_func=lambda value: labels[value])
    st.session_state["holder_mint"] = mint
else:
    mint = selected
    symbol = str((watchlist.get(mint) or {}).get("symbol") or "?")
    st.warning("Token belum ada di watchlist. Scan lokal tetap mencatat "
               "history di file holder_history.json.")
    st.markdown(f"**${symbol.upper()}** — `{mint}`")
    st.markdown(external_links_html(mint), unsafe_allow_html=True)
    if st.button("➕ Tambahkan ke watchlist"):
        add_to_watchlist(mint, symbol, source="manual")
        st.rerun()

token = (status.get("tokens") or {}).get(mint) or {}
holders = token.get("holders") or {}
points = _points_for(mint, token, store)
sampled = resample_4h(points)
prev_pct = sampled[-2].get("dust_pct_mc") if len(sampled) >= 2 else None
current_pct = holders.get("dust_pct_mc")
if current_pct is None and sampled:
    current_pct = sampled[-1].get("dust_pct_mc")
flag = dust_flag(current_pct, prev_pct)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Dust wallet", f"{int(holders.get('dust_count') or 0):,}")
c2.metric("Dust hold % MC", _fmt_pct(current_pct))
c3.metric("Real >$10", f"{int(holders.get('real_count') or 0):,}")
mid = holders.get("mid") if isinstance(holders.get("mid"), dict) else {}
c4.metric("Pilar Crab+Fish", f"{int(mid.get('count') or 0):,}",
          _fmt_pct(mid.get("pct_mc")))
st.markdown(_dust_badge(flag), unsafe_allow_html=True)
st.caption(
    f"Scan terakhir: {_wib(token.get('analyzed_at') or store.get('updated_at'))} "
    f"· dust ≥ {DUST_CAUTION_PCT:.0f}% MC = hati-hati · "
    f"dust > {DUST_LIMIT_PCT:.0f}% MC = limit/DUMP"
    + (" · dust sedang naik" if flag.get("rising") else "")
)

if sampled:
    last = sampled[-1]
    if last.get("cohort_token_pct") is not None:
        st.caption(
            f"Kohort beku {int(last.get('cohort_n') or 0)} wallet: sisa "
            f"{_fmt_pct(last.get('cohort_token_pct'))} token · "
            f"{_fmt_pct(last.get('cohort_cut50_pct'), 1)} sudah potong ≥50%."
        )

st.subheader("Grafik 4 jam")
_history_charts(points)

if st.button("🔄 Scan holder token ini", type="primary",
             use_container_width=True):
    cohort = ((store.get("tokens") or {}).get(mint) or {}).get("cohort") or {}
    addrs = list((cohort.get("balances") or {}).keys())
    with st.status("Mengambil holder…", expanded=False):
        try:
            analysis = analyze_token(
                mint, str((watchlist.get(mint) or {}).get("symbol")
                          or token.get("symbol") or "?"),
                max_wallets=2000, max_trade_pages=1, fetch_market=True,
                include_flow=False, cohort_addrs=addrs)
        except Exception as exc:  # noqa: BLE001
            analysis = None
            st.error(f"Gagal: {exc}")
    if analysis:
        ingest_many({mint: analysis})
        st.rerun()
