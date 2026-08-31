# -*- coding: utf-8 -*-
"""Flow & CVD harian — Wallet Depth (tanpa sinyal).

Menampilkan pergerakan harga, CVD harian, volume USD, dan status
silent-accumulation 12 jam untuk token terpilih. Semua logika sinyal
lama dan alert Telegram sudah dihapus.
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
from silent_status import load_silent_status
from scripts.update_cvd import refresh_single_token
from watchlist import add_to_watchlist, load_watchlist

st.set_page_config(page_title="Flow & CVD Harian", page_icon="🔇",
                   layout="wide")
st.title("🔇 Flow & CVD Harian")
st.caption("Harga, ΔCVD (SOL), dan volume USD harian memakai batas hari "
           "market (00:00 UTC). Tidak ada sinyal dan tidak ada alert "
           "Telegram; fokus pada silent accumulation 12 jam terakhir.")

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


def _status_summary(mint, token):
    """Kartu status 12 jam + holder depth dari snapshot silent status."""
    if not token:
        st.info("Belum ada snapshot silent-accumulation untuk token ini. "
                "Jalankan scan di halaman utama atau tunggu cron ~15 menit.")
        return
    silent = token.get("silent") or {}
    flow = token.get("flow") or {}
    holders = token.get("holders") or {}
    left, mid, right, last = st.columns(4)
    label = ("🔇 SILENT ACCUMULATION" if silent.get("silent")
             else "NET BELI" if (flow.get("net_usd") or 0) > 0
             else "DISTRIBUSI" if (flow.get("net_usd") or 0) < 0
             else "NETRAL")
    left.metric("12 Jam", label)
    mid.metric("Net flow", f"${flow.get('net_usd') or 0:+,.0f}")
    right.metric("Real >$10", str(holders.get("real_count") or "—"))
    dust_pct = holders.get("dust_pct_mc")
    last.metric("Dust % MC",
                "—" if dust_pct is None else f"{float(dust_pct):.2f}%")
    st.caption(silent.get("reason") or "—")


def _fmt_pct(value, digits: int = 2) -> str:
    """Format angka persen; ``None`` → em-dash."""
    return "—" if value is None else f"{float(value):.{digits}f}%"


def _holder_share(part, total) -> float | None:
    """Persen ``part/total``; ``None`` bila total tidak bisa dipakai."""
    try:
        part, total = float(part or 0), float(total or 0)
    except (TypeError, ValueError):
        return None
    return (part / total * 100.0) if total > 0 else None


def _holder_float(holders: dict, key: str) -> float | None:
    value = holders.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _holder_analytics(mint, token):
    """Sesi holder analytic: real vs dust — jumlah wallet & % marketcap."""
    st.subheader("🧮 Holder Analytic")
    st.caption("Real holder = value > $10; dust holder = 0 < value ≤ $10. "
               "% jumlah dihitung dari wallet teranalisis, % marketcap = "
               "nilai USD kelompok ÷ marketcap pada snapshot terakhir.")
    holders = (token or {}).get("holders") or {}
    if not holders:
        st.info("Belum ada data holder untuk token ini. Jalankan scan di "
                "halaman utama atau tunggu cron ~15 menit; metrik di bawah "
                "terisi dari snapshot silent-accumulation.")
        return

    def _int(key: str) -> int:
        try:
            return int(float(holders.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    real_count = _int("real_count")
    dust_count = _int("dust_count")
    wallets = _int("wallets_analyzed") or (real_count + dust_count)
    real_pct_count = _holder_share(real_count, wallets)
    dust_pct_count = _holder_share(dust_count, wallets)
    real_mc = _holder_float(holders, "real_pct_mc")
    dust_mc = _holder_float(holders, "dust_pct_mc")
    real_usd = _holder_float(holders, "real_value_usd")
    dust_usd = _holder_float(holders, "dust_value_usd")
    truncated = bool(holders.get("truncated"))
    if wallets <= 0 and real_mc is None and dust_mc is None:
        st.warning("Snapshot holder tersedia tetapi kosong (0 wallet).")
        return

    prefix = "≥" if truncated else ""
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("% Real holder (jumlah)", _fmt_pct(real_pct_count, 1),
                f"{prefix}{real_count:,} wallet",
                help="Real holder (value > $10) ÷ total wallet teranalisis.")
    col2.metric("% Dust holder (jumlah)", _fmt_pct(dust_pct_count, 1),
                f"{prefix}{dust_count:,} wallet",
                help="Dust holder (0 < value ≤ $10) ÷ total wallet "
                     "teranalisis.")
    col3.metric("Real holder pegang MC", _fmt_pct(real_mc, 2),
                "—" if real_usd is None else f"${real_usd:,.0f}",
                help="Total nilai USD real holder sebagai % dari marketcap.")
    col4.metric("Dust holder pegang MC", _fmt_pct(dust_mc, 2),
                "—" if dust_usd is None else f"${dust_usd:,.0f}",
                help="Total nilai USD dust holder sebagai % dari marketcap.")

    # Bar bertumpuk: komposisi jumlah holder & komposisi % marketcap.
    bars = []
    if real_pct_count is not None or dust_pct_count is not None:
        bars.append(("Jumlah holder", real_pct_count or 0.0,
                     dust_pct_count or 0.0, 0.0))
    if real_mc is not None or dust_mc is not None:
        bars.append(("% Marketcap", real_mc or 0.0, dust_mc or 0.0,
                     max(0.0, 100.0 - (real_mc or 0.0) - (dust_mc or 0.0))))
    if bars:
        names = [bar[0] for bar in bars]
        real_vals = [bar[1] for bar in bars]
        dust_vals = [bar[2] for bar in bars]
        other_vals = [bar[3] for bar in bars]
        fig, axis = plt.subplots(figsize=(11, 1.4 + 0.85 * len(bars)))
        axis.barh(names, real_vals, color="#16a34a", label="Real holder")
        axis.barh(names, dust_vals, left=real_vals, color="#f59e0b",
                  label="Dust holder")
        if any(other_vals):
            base = [r + d for r, d in zip(real_vals, dust_vals)]
            axis.barh(names, other_vals, left=base, color="#475569",
                      alpha=.6, label="Di luar wallet teranalisis (LP/pool)")
        for index, (name, real, dust, other) in enumerate(bars):
            if real >= 8:
                axis.text(real / 2, index, f"{real:.1f}%", va="center",
                          ha="center", color="white", fontsize=9,
                          fontweight="bold")
            if dust >= 8:
                axis.text(real + dust / 2, index, f"{dust:.1f}%",
                          va="center", ha="center", color="white",
                          fontsize=9, fontweight="bold")
        axis.set_xlim(0, 100)
        axis.set_xlabel("%")
        axis.invert_yaxis()
        axis.grid(axis="x", alpha=.2)
        axis.legend(loc="upper center", bbox_to_anchor=(.5, -.3), ncol=3,
                    frameon=False)
        fig.subplots_adjust(left=.16, right=.98, top=.9, bottom=.42)
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)

    source = str(holders.get("source") or "gmgn").lower()
    extra = []
    if _int("pages"):
        extra.append(f"{_int('pages')} halaman")
    if _int("new_real") or _int("new_dust"):
        extra.append(f"wallet baru: {_int('new_real')} real / "
                     f"{_int('new_dust')} dust")
    if _int("suspicious_dust"):
        extra.append(f"{_int('suspicious_dust')} dust mencurigakan")
    if truncated:
        extra.append("terpotong batas maks. wallet → angka = batas bawah")
    dust_limit = _holder_float(holders, "dust_limit_usd")
    st.caption(f"Sumber holder: {source} • dust limit "
               f"${dust_limit if dust_limit is not None else 10.0:.0f}"
               + (f" • {' • '.join(extra)}" if extra else ""))


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
        add_to_watchlist(mint, symbol, source="manual")
        st.rerun()

# --- Status silent accumulation 12 jam ---------------------------------------
status = load_silent_status()
token_status = (status.get("tokens") or {}).get(mint)
_status_summary(mint, token_status)

# --- Holder analytic (real vs dust) -------------------------------------------
_holder_analytics(mint, token_status)

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
