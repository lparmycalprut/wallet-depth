# -*- coding: utf-8 -*-
"""Seven-day price, daily CVD, and effort-ratio charts + manual fetch."""
from __future__ import annotations

import matplotlib.pyplot as plt
import streamlit as st

from core import get_helius_keys
from effort_detector import (classify_effort, load_daily_effort,
                             rows_for_mint)
from links import external_links_html
from scripts.update_cvd import refresh_single_token
from watchlist import add_to_watchlist, load_watchlist

st.set_page_config(page_title="Efisiensi Anomali", page_icon="⚡",
                   layout="wide")
st.title("⚡ Efisiensi Anomali")
st.caption("Harga dan ΔCVD harian menggunakan batas kalender WIB. Chart tidak "
           "melakukan fetch otomatis; data diperbarui cron setiap 00:00 WIB "
           "atau lewat panel “Fetch data manual” di bawah.")

watchlist = load_watchlist()
mints = list(watchlist)

# --- Resolve the selected token --------------------------------------------
# Query param (from the 📊 CVD shortcut) wins, then the session value, then the
# first watchlist entry. A token may be selected even if it is NOT in the
# watchlist so the manual fetch works for listing-shortcut tokens too.
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

# --- Manual fetch panel ------------------------------------------------------
with st.expander("🔁 Fetch data manual", expanded=not in_watchlist):
    st.caption("Hanya token yang sedang dipilih yang diproses. Hari berjalan "
               "(yang belum selesai di WIB) tidak dimasukkan. Fetch manual "
               "tidak mengirim alert Telegram.")
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
                    f"`{entry['ts_wib']}` **{entry['stage']}** — "
                    f"{entry['message']}"))
        st.session_state["manual_result"] = result
        st.rerun()

# --- Render manual-fetch log (persists in session state) ----------------------
def _render_manual_log():
    res = st.session_state.get("manual_result")
    if not res or res.get("mint") != mint:
        return
    with st.expander("📄 Log fetch manual", expanded=True):
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


_render_manual_log()

# --- Effort data + charts ------------------------------------------------------
rows = rows_for_mint(load_daily_effort(), mint)[-7:]
if not rows:
    st.info("Belum ada data harian untuk token ini. Gunakan panel “Fetch data "
            "manual” di atas atau tunggu cron harian (00:00 WIB).")
    st.stop()

latest = classify_effort(rows, mint)
left, middle, right, last = st.columns(4)
left.metric("Sinyal", str(latest.get("signal") or "insufficient_data"))
middle.metric("Ratio hari ini",
              f"{latest['ratio_N']:.3f} SOL/1%"
              if latest.get("ratio_N") is not None else "—")
# Show raw multiplier clearly; indicate rejection when baseline is not stable
baseline_status = latest.get("baseline_status") or "missing"
if baseline_status != "stable" and latest.get("raw_multiplier") is not None:
    right.metric("Multiplier",
                 f"Raw ×{latest['raw_multiplier']:.2f} — DITOLAK")
else:
    right.metric("Multiplier",
                 f"×{latest['multiplier']:.2f}"
                 if latest.get("multiplier") is not None else "—")
last.metric("Bias", str(latest.get("bias") or "—").upper())

# Baseline status and reason
if baseline_status == "unstable":
    st.warning("⚠️ BASELINE TIDAK STABIL")
    reason = latest.get("baseline_reason", "")
    if reason:
        st.caption(str(reason).replace("; ", "\n"))
elif baseline_status == "incompatible_direction":
    st.warning("⚠️ BASELINE BEDA ARAH")
    reason = latest.get("baseline_reason", "")
    if reason:
        st.caption(str(reason).replace("; ", "\n"))

# Build point-by-point classifications so historical markers are honest.
signals = {}
for index in range(1, len(rows)):
    result = classify_effort(rows[:index + 1], mint)
    signals[result.get("date")] = result

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
for date, result in signals.items():
    # Only show S1-S4 markers when baseline is stable (not rejected)
    if (result.get("baseline_status") == "stable" and
            result.get("signal") in {
            "S1_PENYERAPAN", "S2_DUMP_DISTRIBUSI",
            "S3_DISTRIBUSI_KE_KUAT", "S4_PUMP_ASLI"}):
        index = dates.index(date)
        color = ("#16a34a" if result.get("bias") == "bullish"
                 else "#dc2626")
        axis_price.scatter(date, closes[index], s=90, color=color,
                           edgecolor="white", zorder=5)
        axis_price.annotate(result["signal"].split("_")[0],
                            (date, closes[index]), xytext=(0, 10),
                            textcoords="offset points", ha="center",
                            color=color, fontweight="bold")
fig.legend(loc="upper left", bbox_to_anchor=(.09, .9), frameon=False)
fig.tight_layout()
st.pyplot(fig, use_container_width=True)
plt.close(fig)

ratios = [row.get("ratio") for row in rows]
baselines = [None] + ratios[:-1]
fig_ratio, axis = plt.subplots(figsize=(11, 3.4))
colors = []
for date in dates:
    result = signals.get(date) or {}
    # Only color as bullish/bearish when baseline is stable
    if result.get("baseline_status") == "stable" and result.get("bias") == "bullish" and result.get("signal") != "S5_NETRAL":
        colors.append("#16a34a")
    elif result.get("baseline_status") == "stable" and result.get("bias") == "bearish" and result.get("signal") != "S5_NETRAL":
        colors.append("#dc2626")
    else:
        colors.append("#64748b")
axis.bar(dates, [value or 0 for value in ratios], color=colors, alpha=.85,
         label="Ratio SOL/1%")
axis.plot(dates, [value if value is not None else float("nan")
                  for value in baselines], color="#0f172a", linestyle="--",
          marker=".", label="Baseline hari sebelumnya")
axis.set_ylabel("SOL per 1%")
axis.tick_params(axis="x", rotation=35)
axis.grid(axis="y", alpha=.2)
axis.legend(frameon=False)
fig_ratio.tight_layout()
st.pyplot(fig_ratio, use_container_width=True)
plt.close(fig_ratio)

st.subheader("Data harian")
st.dataframe(rows, use_container_width=True, hide_index=True)
st.caption("R = |ΔCVD| / |ΔHarga%|. Multiplier membandingkan R hari terbaru "
           "dengan R hari sebelumnya. Pergerakan di bawah 3% selalu netral.")
