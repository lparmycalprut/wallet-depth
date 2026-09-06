# -*- coding: utf-8 -*-
"""Flow & CVD harian — Wallet Depth (tanpa sinyal).

Menampilkan pergerakan harga, CVD harian, dan volume USD untuk token
terpilih. Analisa holder (dust) ada di halaman Holder Analytic.
"""
from __future__ import annotations

from datetime import datetime
import csv
import io
import re

import matplotlib.pyplot as plt
import streamlit as st

from cvd_daily import MARKET_TZ
from daily_store import load_daily_effort, rows_for_mint
from links import external_links_html
from scripts.update_cvd import refresh_single_token
from watchlist import add_to_watchlist, load_watchlist

st.set_page_config(page_title="Flow & CVD Harian", page_icon="📊",
                   layout="wide")
st.title("📊 Flow & CVD Harian")
st.caption("Harga, ΔCVD (SOL), dan volume USD harian memakai batas hari "
           "market (00:00 UTC). Analisa dust/holder ada di halaman "
           "🧮 Holder Analytic.")

EXPORT_COLUMNS = [
    "mint", "date", "open", "close", "price_chg_pct", "cvd_delta",
    "direction", "volume_usd", "marketcap_close", "coverage_hours",
    "top_wallet_pct", "unique_makers", "smart_money_buy", "fresh_buy",
    "bot_sell", "mev_noise",
]

# Solana addresses are base58 (no 0/O/I/l) and 32-44 chars.
SOLANA_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _normalize_ca(value) -> str:
    return str(value or "").strip()


def _valid_solana_ca(value) -> bool:
    return bool(SOLANA_CA_RE.match(_normalize_ca(value)))


def _render_charts(rows):
    dates = [row["date"] for row in rows]
    closes = [float(row.get("close") or 0) for row in rows]
    running = []
    total = 0.0
    for row in rows:
        total += float(row.get("cvd_delta") or 0)
        running.append(total)

    fig, axis_price = plt.subplots(figsize=(11, 4.8))
    axis_cvd = axis_price.twinx()
    axis_price.plot(dates, closes, color="#2563eb", marker="o", linewidth=2.2,
                    label="Harga close (USD)")
    axis_cvd.plot(dates, running, color="#f59e0b", marker="s", linewidth=2,
                  label="CVD kumulatif (SOL)")
    axis_price.set_ylabel("Harga USD", color="#2563eb")
    axis_cvd.set_ylabel("CVD kumulatif (SOL)", color="#b45309")
    axis_price.tick_params(axis="x", rotation=35)
    axis_price.grid(alpha=.2)
    fig.legend(loc="upper left", bbox_to_anchor=(.09, .9), frameon=False)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    volumes = [row.get("volume_usd") for row in rows]
    fig_vol, axis = plt.subplots(figsize=(11, 3.4))
    axis.bar(dates, [float(value or 0) for value in volumes], color="#64748b",
             alpha=.85, label="Volume USD harian")
    axis.set_ylabel("Volume USD")
    axis.tick_params(axis="x", rotation=35)
    axis.grid(axis="y", alpha=.2)
    axis.legend(frameon=False)
    fig_vol.tight_layout()
    st.pyplot(fig_vol, use_container_width=True)
    plt.close(fig_vol)


watchlist = load_watchlist()
mints = list(watchlist)

query_mint = str(st.query_params.get("mint") or "") if "mint" in st.query_params else ""
session_mint = st.session_state.get("effort_mint") or ""
# Session state wins over the URL: switching from the selectbox keeps the
# user's most recent choice even if the old mint remains in the URL.
candidate = session_mint or query_mint
selected = candidate if candidate in mints else (candidate or (mints[0] if mints else ""))

# --- Cek CVD manual: input CA apa pun, tanpa harus ada di watchlist. ---------
with st.expander("🔍 Cek CVD manual — input CA", expanded=not bool(selected)):
    st.caption("Tempel contract address (CA) Solana untuk cek CVD/flow token "
               "apa pun. Token tidak harus ada di watchlist; fetch manual "
               "hanya menulis data harian.")
    with st.form("manual-ca-form"):
        ca_input = st.text_input(
            "Contract address (CA)",
            placeholder="So11111111111111111111111111111111111111112",
        )
        submitted = st.form_submit_button("🔍 Cek CVD", type="primary")
    if submitted:
        manual_ca = _normalize_ca(ca_input)
        if not manual_ca:
            st.warning("Masukkan contract address terlebih dahulu.")
        elif not _valid_solana_ca(manual_ca):
            st.warning("Format CA Solana tidak valid. Gunakan address "
                       "base58 sepanjang 32–44 karakter.")
        else:
            st.session_state["effort_mint"] = manual_ca
            st.query_params["mint"] = manual_ca
            st.rerun()

if not selected:
    st.info("Belum ada token dipilih. Tambahkan token ke watchlist, "
            "gunakan shortcut 📊 dari halaman utama, atau ketik CA di atas.")
    st.stop()

st.session_state["effort_mint"] = selected
in_watchlist = selected in watchlist
labels = {mint: f"${str(watchlist[mint].get('symbol') or '?').upper()} — "
                f"{mint[:8]}…" for mint in mints}

if in_watchlist:
    mint = st.selectbox("Token", mints, index=mints.index(selected),
                        format_func=lambda value: labels[value])
    st.session_state["effort_mint"] = mint
else:
    mint = selected
    symbol = str((watchlist.get(mint) or {}).get("symbol") or "?")
    st.warning("Token dipilih lewat shortcut tetapi belum ada di watchlist. "
               "Fetch manual tetap bisa dijalankan dan hanya menulis data "
               "harian; token ini tidak dilacak oleh cron.")
    st.markdown(f"**${symbol.upper()}** — `{mint}`")
    st.markdown(f"{external_links_html(mint)}", unsafe_allow_html=True)
    if st.button("➕ Tambahkan ke watchlist"):
        add_to_watchlist(mint, symbol, source="manual",
                         background=True)
        st.rerun()

# --- Manual fetch panel -------------------------------------------------------
with st.expander("🔁 Fetch data harian manual", expanded=False):
    st.caption("Hari berjalan (belum selesai di market/UTC) tidak dimasukkan. "
               "Fetch manual tidak mengirim alert.")
    col_l, col_b = st.columns([2, 1])
    days = col_l.number_input("Jumlah hari terakhir yang diambil (2–30)",
                              min_value=2, max_value=30, value=7, step=1)
    fetched = col_b.button("Fetch sekarang", type="primary",
                           use_container_width=True)
    if fetched:
        from core import get_helius_keys
        keys = get_helius_keys()
        api_key = keys[0] if keys else ""
        log_entries = []
        with st.status("Mengambil data manual…", expanded=True) as box:
            result = refresh_single_token(
                mint, watchlist.get(mint) or {},
                api_key=api_key, lookback_days=int(days), log=log_entries,
                on_progress=lambda entry: box.write(
                    f"`{entry['ts_market']}` **{entry['stage']}** — "
                    f"{entry['message']}"))
        st.session_state["manual_result"] = result
        st.rerun()

result = st.session_state.get("manual_result")
if result and result.get("mint") == mint:
    with st.expander("📄 Log fetch manual", expanded=False):
        cols = st.columns(5)
        cols[0].metric("Status", "✅ Sukses" if result.get("ok")
                       else "❌ Gagal")
        cols[1].metric("Sumber", str(result.get("source") or "—"))
        cols[2].metric("Trades", f"{result.get('trades_count') or 0}")
        cols[3].metric("Dibuat", f"{result.get('rows_created') or 0}")
        cols[4].metric("Diupdate", f"{result.get('rows_updated') or 0}")
        if result.get("fallback"):
            st.info("Sumber Helius tidak lengkap → fallback otomatis ke GMGN.")
        if not result.get("ok") and result.get("error"):
            st.error(result["error"])
        st.dataframe(result.get("log") or [], use_container_width=True,
                     hide_index=True)

# --- History ------------------------------------------------------------------
all_rows = rows_for_mint(load_daily_effort(), mint)
st.subheader(f"History harian — {mint[:8]}…")
if all_rows:
    _render_charts(all_rows)
    st.dataframe(all_rows, use_container_width=True, hide_index=True)
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=EXPORT_COLUMNS,
                            extrasaction="ignore")
    writer.writeheader()
    writer.writerows(all_rows)
    st.download_button(
        "⬇️ Download CSV harian",
        data=csv_buffer.getvalue(),
        file_name=f"wallet_depth_{mint}.csv",
        mime="text/csv",
    )
    st.caption("Kolom smart_money_buy / fresh_buy / bot_sell / mev_noise "
               "adalah penanda on-chain (info, bukan sinyal).")
else:
    st.info("Belum ada data harian. Klik 'Fetch sekarang' untuk mengambilnya.")
