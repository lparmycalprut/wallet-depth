# -*- coding: utf-8 -*-
"""Price, daily CVD, and volume-USD charts with backtest history + manual fetch.

3 sinyal bottom: classify_all memindai seluruh window — setiap hari (idx>=1)
dievaluasi terhadap flush CVD 5 hari sebelumnya dan volume USD hari
sebelumnya. Batas hari 00:00 UTC.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import csv
import io

import matplotlib.pyplot as plt
import streamlit as st

from core import get_helius_keys
from cvd_daily import MARKET_TZ
from effort_detector import (EXPORT_COLUMNS, SIGNAL_META, classify_all,
                             classify_effort, load_daily_effort,
                             rows_for_mint, rows_with_signals)
from links import external_links_html
from scripts.update_cvd import refresh_single_token
from watchlist import add_to_watchlist, load_watchlist

st.set_page_config(page_title="3 Sinyal Bottom", page_icon="⚡",
                   layout="wide")
st.title("⚡ 3 Sinyal Bottom")
st.caption("Harga, ΔCVD (SOL), dan volume USD harian memakai batas hari "
           "market (00:00 UTC, sesuai GMGN/Helius/Solscan). Sinyal: 🟢 SELLER "
           "EXHAUSTION (CVD runtuh + volume kering ≤40%), 🟣 REVERSAL (CVD "
           "runtuh + volume naik ≥130%), 🔵 AKUMULASI (CVD ≥ +5 SOL + volume "
           "naik ≥130%). Chart tidak melakukan fetch otomatis; data "
           "diperbarui cron setiap 00:00 UTC atau lewat panel fetch manual.")

# Warna & label marker per sinyal
SIGNAL_COLORS = {"SELLER_EXHAUSTION": "#16a34a", "REVERSAL": "#7c3aed",
                 "AKUMULASI": "#2563eb"}
SIGNAL_MARK = {"SELLER_EXHAUSTION": "EXH", "REVERSAL": "REV",
               "AKUMULASI": "AKU"}


def _render_metrics(rows, mint):
    """Render signal metrics for the newest row in ``rows``."""
    latest = classify_effort(rows, mint)
    signal = str(latest.get("signal") or "—")
    meta = SIGNAL_META.get(signal) or {}
    left, middle, right, last = st.columns(4)
    left.metric("Sinyal", f"{meta.get('emoji', '')} {signal}"
                .strip() if meta else signal)
    cvd = latest.get("cvd_delta")
    middle.metric("CVD hari ini",
                  f"{cvd:+.2f} SOL" if cvd is not None else "—")
    volume_pct = latest.get("volume_pct")
    right.metric("Volume vs kemarin",
                 f"{volume_pct:.0f}%" if volume_pct is not None else "—")
    last.metric("Bias", str(latest.get("bias") or "—").upper())

    if signal in SIGNAL_META:
        flush_date = latest.get("flush_date")
        if flush_date:
            st.success(
                f"✅ {signal} — flush {flush_date} "
                f"(CVD {latest.get('flush_cvd'):+.2f} SOL), runtuh jadi "
                f"{(latest.get('collapse_pct') or 0):.1f}%, volume "
                f"{(latest.get('volume_pct') or 0):.0f}% dari kemarin")
        else:
            st.success(f"✅ {signal} — {latest.get('reason') or ''}")
        # Penanda on-chain (info, bukan syarat)
        tags = [f"smart money buy {latest.get('smart_money_buy') or 0}",
                f"fresh buy {latest.get('fresh_buy') or 0}",
                f"bot sell {latest.get('bot_sell') or 0}",
                f"mev noise {latest.get('mev_noise') or 0}"]
        caption = " · ".join(tags)
        if latest.get("whale_driven"):
            caption += (f" · ⚠️ dominasi whale (top-1 "
                        f"{(latest.get('top_wallet_pct') or 0):.0f}%)")
        st.caption(caption)
    else:
        status = latest.get("status")
        if status == "missing":
            st.info("Belum ada data harian — lakukan fetch terlebih dahulu.")
        elif status == "first_day":
            st.info("Baru hari pertama window — sinyal butuh hari pembanding.")
        elif latest.get("wash_blocked"):
            st.warning("⚠️ Volume melebihi 3× marketcap close — kemungkinan "
                       "wash-trade, sinyal dibatalkan.")
        reason = str(latest.get("reason") or "").strip()
        if reason:
            st.caption(reason)


def _render_charts(rows, mint):
    """Render price/CVD and volume-USD charts with per-day signal markers."""
    classified = classify_all(rows)
    signals_by_date = {res.get("date"): res for res in classified}

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
    for date in dates:
        result = signals_by_date.get(date) or {}
        sig = result.get("signal") or ""
        if sig in SIGNAL_COLORS:
            try:
                idx = dates.index(date)
            except ValueError:
                continue
            color = SIGNAL_COLORS[sig]
            axis_price.scatter(date, closes[idx], s=90, color=color,
                               edgecolor="white", zorder=5)
            axis_price.annotate(SIGNAL_MARK[sig],
                                (date, closes[idx]), xytext=(0, 10),
                                textcoords="offset points", ha="center",
                                color=color, fontweight="bold", fontsize=8)
    fig.legend(loc="upper left", bbox_to_anchor=(.09, .9), frameon=False)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    # Chart 2: volume USD harian, diwarnai mengikuti sinyal
    volumes = [row.get("volume_usd") for row in rows]
    fig_vol, axis = plt.subplots(figsize=(11, 3.4))
    colors = []
    for date in dates:
        sig = (signals_by_date.get(date) or {}).get("signal") or ""
        colors.append(SIGNAL_COLORS.get(sig, "#64748b"))
    axis.bar(dates, [float(value or 0) for value in volumes], color=colors,
             alpha=.85, label="Volume USD harian")
    axis.set_ylabel("Volume USD")
    axis.tick_params(axis="x", rotation=35)
    axis.grid(axis="y", alpha=.2)
    axis.legend(frameon=False)
    fig_vol.tight_layout()
    st.pyplot(fig_vol, use_container_width=True)
    plt.close(fig_vol)


def _rows_in_range(all_rows, start_date, end_date):
    """Return mint rows whose calendar date falls in ``[start, end]``."""
    s = str(start_date)
    e = str(end_date)
    return [dict(row) for row in (all_rows or [])
            if s <= str(row.get("date") or "") <= e]


watchlist = load_watchlist()
mints = list(watchlist)

# --- Resolve the selected token --------------------------------------------
query_mint = str(st.query_params.get("mint") or "") \
    if "mint" in st.query_params else ""
session_mint = st.session_state.get("effort_mint") or ""
candidate = query_mint or session_mint
if candidate in mints:
    selected = candidate
elif candidate:
    selected = candidate
else:
    selected = mints[0] if mints else ""

if not selected:
    st.info("Belum ada token dipilih. Tambahkan token ke watchlist atau gunakan "
            "shortcut 📊 CVD dari halaman utama.")
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
    st.warning(
        "Token ini dipilih lewat shortcut tetapi belum ada di watchlist. "
        "Shortcut tidak mengubah watchlist. Fetch manual tetap bisa dijalankan "
        "dan hanya menulis data harian; token ini tidak dilacak oleh cron.")
    st.markdown(f"**${symbol.upper()}** — `{mint}`")
    st.markdown(f"{external_links_html(mint)}", unsafe_allow_html=True)
    if st.button("➕ Tambahkan ke watchlist"):
        add_to_watchlist(mint, symbol, source="manual")
        st.rerun()

# --- Manual fetch panel (last-N-days, preserved behavior) --------------------
with st.expander("🔁 Fetch data manual", expanded=False):
    st.caption("Hanya token yang sedang dipilih yang diproses. Hari berjalan "
               "(yang belum selesai di market/UTC) tidak dimasukkan. Fetch "
               "manual tidak mengirim alert Telegram.")
    col_l, col_b = st.columns([2, 1])
    days = col_l.number_input("Jumlah hari terakhir yang diambil (2–30)",
                              min_value=2, max_value=30, value=7, step=1)
    fetched = col_b.button("Fetch sekarang", type="primary",
                           use_container_width=True)
    if fetched:
        keys = get_helius_keys()
        api_key = keys[0] if keys else ""
        log_entries = []
        with st.status("Mengambil data manual…", expanded=True) as status:
            result = refresh_single_token(
                mint, watchlist.get(mint) or {},
                api_key=api_key, lookback_days=int(days), log=log_entries,
                on_progress=lambda entry: status.write(
                    f"`{entry['ts_market']}` **{entry['stage']}** — "
                    f"{entry['message']}"))
        st.session_state["manual_result"] = result
        st.rerun()


# --- Backtest control -------------------------------------------------------
today = datetime.now(MARKET_TZ).date()
yesterday = today - timedelta(days=1)
min_start = today - timedelta(days=30)

with st.expander("📅 Backtest history", expanded=True):
    st.caption("Pilih tanggal awal dan berapa hari ke depan. Data diambil "
               "otomatis saat input berubah, atau manual lewat tombol di "
               "bawah (idempoten, tidak mengirim alert). Rentang dibatasi "
               "maksimal 30 hari dan tidak melewati kemarin.")
    c1, c2 = st.columns([1, 1])
    default_start = st.session_state.get("bt_start") or (
        yesterday - timedelta(days=6))
    default_days = int(st.session_state.get("bt_days") or 7)
    start_date = c1.date_input("Dari (market/UTC)", value=default_start,
                               min_value=min_start, max_value=yesterday)
    days_forward = c2.number_input("Berapa hari ke depan (2–30)",
                                   min_value=2, max_value=30,
                                   value=default_days, step=1)
    st.session_state["bt_start"] = start_date
    st.session_state["bt_days"] = int(days_forward)
    end_date = start_date + timedelta(days=int(days_forward) - 1)
    if end_date > yesterday:
        end_date = yesterday
    span = (end_date - start_date).days + 1
    st.caption(f"Rentang: **{start_date} s/d {end_date}** ({span} hari).")
    fetch_range_clicked = st.button("🔍 Fetch rentang ini",
                                    key="bt_fetch_range",
                                    use_container_width=True)

# Auto-fetch only when the start date or days-forward changes (never on the
# very first page load).
bt_key = (str(start_date), int(days_forward))
if "bt_initialized" not in st.session_state:
    st.session_state["bt_initialized"] = True
    st.session_state["bt_fetched"] = bt_key
    need_fetch = False
else:
    need_fetch = st.session_state.get("bt_fetched") != bt_key
    st.session_state["bt_fetched"] = bt_key

# --- Manual fetch log renderer -----------------------------------------------
def _render_manual_log():
    res = st.session_state.get("manual_result")
    if not res or res.get("mint") != mint:
        return
    with st.expander("📄 Log fetch manual", expanded=False):
        st.caption("Log ini tersimpan dalam sesi Streamlit saat ini dan tidak "
                   "ditulis ke Git. Tidak ada credential/API key yang dicatat.")
        cols = st.columns(6)
        cols[0].metric("Status", "✅ Sukses" if res.get("ok")
                       else "❌ Gagal")
        cols[1].metric("Sumber", str(res.get("source") or "—"))
        cols[2].metric("Trades", f"{res.get('trades_count') or 0}")
        cols[3].metric("Dibuat", f"{res.get('rows_created') or 0}")
        cols[4].metric("Diupdate", f"{res.get('rows_updated') or 0}")
        cols[5].metric("Durasi", f"{res.get('duration_ms') or 0} ms")
        if res.get("fallback"):
            st.info("Sumber GMGN tidak lengkap → fallback otomatis ke Helius.")
        if not res.get("ok") and res.get("error"):
            st.error(res["error"])
        st.dataframe(res.get("log") or [],
                     use_container_width=True, hide_index=True)


# --- Range fetch: explicit button first, then auto-fetch on change -----------
def _fetch_range(mint, meta, start_date, end_date):
    """Fetch the selected range and return a session-safe structured result."""
    keys = get_helius_keys()
    api_key = keys[0] if keys else ""
    log_entries = []
    with st.status("Mengambil data untuk rentang terpilih…",
                   expanded=True) as status:
        return refresh_single_token(
            mint, meta, api_key=api_key, start_date=start_date,
            end_date=end_date, log=log_entries,
            on_progress=lambda entry: status.write(
                f"`{entry['ts_market']}` **{entry['stage']}** — "
                f"{entry['message']}"))


if fetch_range_clicked:
    st.session_state["bt_result"] = _fetch_range(
        mint, watchlist.get(mint) or {}, start_date, end_date)
    st.session_state["bt_result_key"] = bt_key
elif need_fetch:
    st.session_state["bt_result"] = _fetch_range(
        mint, watchlist.get(mint) or {}, start_date, end_date)
    st.session_state["bt_result_key"] = bt_key
    st.rerun()

_render_manual_log()

# --- History view -------------------------------------------------------------
all_rows = rows_for_mint(load_daily_effort(), mint)
range_rows = _rows_in_range(all_rows, start_date, end_date)
bt_result = (st.session_state.get("bt_result")
             if st.session_state.get("bt_result_key") == bt_key else None)

st.subheader(f"History {start_date} s/d {end_date}")
if range_rows:
    _render_metrics(range_rows, mint)
    _render_charts(range_rows, mint)
    st.subheader("Data harian + sinyal per hari")
    classified = classify_all(range_rows)
    csv_rows = rows_with_signals(range_rows)
    # build enriched UI table from the daily CSV/export columns plus UI-only details
    enriched = []
    for csv_row, res in zip(csv_rows, classified):
        item = dict(csv_row)
        item.update({
            "bias": res.get("bias"),
            "volume_pct": res.get("volume_pct"),
            "reason": res.get("reason"),
        })
        enriched.append(item)
    st.dataframe(enriched, use_container_width=True, hide_index=True)
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(csv_rows)
    try:
        from effort_detector import format_recap
        export_text = f"{format_recap(mint, range_rows)}\n{csv_buffer.getvalue()}"
    except Exception:
        export_text = csv_buffer.getvalue()
    st.download_button(
        "⬇️ Download CSV harian + sinyal",
        data=export_text,
        file_name=f"wallet_depth_{mint}_{start_date}_{end_date}.csv",
        mime="text/csv",
    )
    st.caption("SELLER_EXHAUSTION: CVD runtuh ≤40% dari flush (≤ -30 SOL, "
               "5 hari) + volume ≤40% kemarin. REVERSAL: sama tapi volume "
               "≥130% kemarin. AKUMULASI: CVD ≥ +5 SOL, harga ≤ +0.5%, volume "
               "≥130%. Semua volume dibandingkan dalam USD. Tag on-chain "
               "(smart money/fresh/bot/mev) hanya info, bukan syarat.")
    # Optional recap block as comment-like text area for copy
    try:
        from effort_detector import format_recap
        recap_text = format_recap(mint, range_rows)
        with st.expander("📋 Rekapan teks (untuk CSV/export)", expanded=False):
            st.code(recap_text, language="text")
    except Exception:
        pass
elif bt_result is not None and not bt_result.get("ok"):
    st.error(f"Fetch gagal: {bt_result.get('error') or 'kesalahan tak dikenal'}")
    st.caption("Periksa koneksi atau API key Helius, lalu klik "
               "“🔍 Fetch rentang ini” untuk mencoba lagi.")
elif bt_result is not None and bt_result.get("ok"):
    st.info("Fetch berhasil, tetapi tidak ada data harian untuk rentang ini. "
            "Token mungkin belum punya aktivitas pasar pada rentang tersebut.")
else:
    st.info("Belum ada data harian untuk rentang ini. Klik "
            "“🔍 Fetch rentang ini” untuk mengambil datanya, atau ubah tanggal "
            "awal / jumlah hari untuk memicu fetch otomatis.")
