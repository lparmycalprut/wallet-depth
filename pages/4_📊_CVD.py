# -*- coding: utf-8 -*-
"""Price, daily CVD, and effort-ratio charts with backtest history + manual fetch.

v3: uses classify_all to scan whole window, supports 2 new pra-pump signals.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import streamlit as st

from core import get_helius_keys
from cvd_daily import MARKET_TZ
from effort_detector import (classify_all, classify_effort, load_daily_effort,
                             rows_for_mint)
from links import external_links_html
from scripts.update_cvd import refresh_single_token
from watchlist import add_to_watchlist, load_watchlist

st.set_page_config(page_title="Efisiensi Anomali", page_icon="⚡",
                   layout="wide")
st.title("⚡ Efisiensi Anomali")
st.caption("Harga dan ΔCVD harian menggunakan batas hari market (00:00 UTC, "
           "sesuai GMGN/Helius/Solscan). Chart tidak melakukan fetch otomatis; "
           "data diperbarui cron setiap 00:00 UTC atau lewat panel fetch "
           "manual.")


def _render_metrics(rows, mint):
    """Render signal metrics for the newest row in ``rows``."""
    latest = classify_effort(rows, mint)
    left, middle, right, last = st.columns(4)
    left.metric("Sinyal", str(latest.get("signal") or "insufficient_data"))
    middle.metric("Ratio hari ini",
                  f"{latest['ratio_N']:.3f} SOL/1%"
                  if latest.get("ratio_N") is not None else "—")
    baseline_status = latest.get("baseline_status") or "missing"
    if baseline_status not in ("stable", "direct") and latest.get("raw_multiplier") is not None:
        right.metric("Multiplier",
                     f"Raw ×{latest['raw_multiplier']:.2f} — DITOLAK")
    else:
        right.metric("Multiplier",
                     f"×{latest['multiplier']:.2f}"
                     if latest.get("multiplier") is not None else "—")
    last.metric("Bias", str(latest.get("bias") or "—").upper())

    # Show baseline warnings for old logic + new explanation
    if baseline_status in ("unstable", "insufficient_baseline", "noise", "missing"):
        # For v3 we show reason if any, except direct signals which are valid
        reason = latest.get("baseline_reason", "")
        if baseline_status == "insufficient_baseline":
            st.warning("⚠️ BASELINE TIDAK CUKUP")
            if reason:
                st.caption(str(reason))
        elif baseline_status == "noise":
            st.warning("⚠️ NOISE — |CVD| < 5 SOL")
            if reason:
                st.caption(str(reason))
        elif baseline_status == "unstable":
            st.warning("⚠️ BASELINE TIDAK STABIL")
            if reason:
                st.caption(str(reason).replace("; ", "\n"))
        elif baseline_status == "missing" and latest.get("signal") == "insufficient_data":
            st.info("Butuh minimal 1 hari baseline sehat atau sinyal langsung.")
            if reason:
                st.caption(str(reason))
    elif baseline_status == "incompatible_direction":
        # Legacy compatibility: should no longer appear in v3 (direction no longer required)
        st.warning("⚠️ BASELINE BEDA ARAH (legacy)")
        reason = latest.get("baseline_reason", "")
        if reason:
            st.caption(str(reason))
    else:
        # For direct signals show their explanatory reason
        if latest.get("signal") in ("ABSORBSI_LANGSUNG", "SELLING_EXHAUSTION"):
            st.success(f"✅ {latest.get('baseline_reason') or latest.get('signal')}")
        elif latest.get("baseline_reason"):
            # Show divergence-murni reason when S5 due to non-divergent high M
            if "bukan penyerapan/distribusi murni" in str(latest.get("baseline_reason")):
                st.caption(str(latest.get("baseline_reason")))


def _render_charts(rows, mint):
    """Render price/CVD and ratio charts for the given rows using classify_all."""
    # v3: scan whole window
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
        if sig in {
            "S1_PENYERAPAN", "S2_DUMP_DISTRIBUSI",
            "S3_DISTRIBUSI_KE_KUAT", "S4_PUMP_ASLI",
            "ABSORBSI_LANGSUNG", "SELLING_EXHAUSTION"}:
            try:
                idx = dates.index(date)
            except ValueError:
                continue
            # bullish green, bearish red
            bias = result.get("bias") or ""
            color = "#16a34a" if bias == "bullish" else "#dc2626" if bias == "bearish" else "#64748b"
            axis_price.scatter(date, closes[idx], s=90, color=color,
                               edgecolor="white", zorder=5)
            # short label
            label = sig.split("_")[0]
            if sig == "ABSORBSI_LANGSUNG":
                label = "ABS"
            elif sig == "SELLING_EXHAUSTION":
                label = "EXH"
            axis_price.annotate(label,
                                (date, closes[idx]), xytext=(0, 10),
                                textcoords="offset points", ha="center",
                                color=color, fontweight="bold", fontsize=8)
    fig.legend(loc="upper left", bbox_to_anchor=(.09, .9), frameon=False)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    ratios = [row.get("ratio") for row in rows]
    # baseline for chart = ratio of previous healthy? For simplicity keep previous day's ratio as line (old behavior)
    baselines = [None] + ratios[:-1]
    fig_ratio, axis = plt.subplots(figsize=(11, 3.4))
    colors = []
    for date in dates:
        result = signals_by_date.get(date) or {}
        sig = result.get("signal") or ""
        if sig in ("S5_NETRAL", "insufficient_data", None, ""):
            colors.append("#64748b")
        elif (result.get("bias") == "bullish"):
            colors.append("#16a34a")
        elif (result.get("bias") == "bearish"):
            colors.append("#dc2626")
        else:
            colors.append("#64748b")
    axis.bar(dates, [value or 0 for value in ratios], color=colors, alpha=.85,
             label="Ratio SOL/1%")
    axis.plot(dates, [value if value is not None else float("nan")
                      for value in baselines], color="#0f172a",
              linestyle="--", marker=".", label="Baseline hari sebelumnya")
    axis.set_ylabel("SOL per 1%")
    axis.tick_params(axis="x", rotation=35)
    axis.grid(axis="y", alpha=.2)
    axis.legend(frameon=False)
    fig_ratio.tight_layout()
    st.pyplot(fig_ratio, use_container_width=True)
    plt.close(fig_ratio)


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
    st.subheader("Data harian + sinyal per hari (v3)")
    classified = classify_all(range_rows)
    # build enriched table
    enriched = []
    for row, res in zip(range_rows, classified):
        enriched.append({
            "date": row.get("date"),
            "open": row.get("open"),
            "close": row.get("close"),
            "price_chg_pct": row.get("price_chg_pct"),
            "cvd_delta": row.get("cvd_delta"),
            "direction": row.get("direction"),
            "ratio": row.get("ratio"),
            "signal": res.get("signal"),
            "bias": res.get("bias"),
            "multiplier": res.get("multiplier"),
            "baseline_status": res.get("baseline_status"),
            "baseline_reason": res.get("baseline_reason"),
        })
    st.dataframe(enriched, use_container_width=True, hide_index=True)
    st.caption("R = |ΔCVD| / |ΔHarga%|. Multiplier membandingkan R hari "
               "terbaru dengan baseline sehat sebelumnya. Sinyal ABSORBSI_LANGSUNG "
               "dan SELLING_EXHAUSTION dicek sebelum gate lain dan tidak butuh baseline.")
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
