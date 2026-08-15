# -*- coding: utf-8 -*-
"""Seven-day price, daily CVD, and effort-ratio charts."""
from __future__ import annotations

import matplotlib.pyplot as plt
import streamlit as st

from effort_detector import (classify_effort, load_daily_effort,
                             rows_for_mint)
from watchlist import load_watchlist

st.set_page_config(page_title="Efisiensi Anomali", page_icon="⚡",
                   layout="wide")
st.title("⚡ Efisiensi Anomali")
st.caption("Harga dan ΔCVD harian menggunakan batas kalender WIB. Chart tidak "
           "melakukan fetch otomatis; data diperbarui cron setiap 00:00 WIB.")

watchlist = load_watchlist()
if not watchlist:
    st.info("Tambahkan token ke watchlist terlebih dahulu.")
    st.stop()

mints = list(watchlist)
selected = st.session_state.get("effort_mint")
if selected not in watchlist:
    selected = mints[0]
labels = {mint: f"${str(watchlist[mint].get('symbol') or '?').upper()} — "
                 f"{mint[:8]}…" for mint in mints}
mint = st.selectbox("Token", mints, index=mints.index(selected),
                    format_func=lambda value: labels[value])
st.session_state["effort_mint"] = mint

rows = rows_for_mint(load_daily_effort(), mint)[-7:]
if not rows:
    st.warning("Belum ada data harian. Tunggu cron berikutnya atau jalankan "
               "workflow Daily Effort Anomaly secara manual.")
    st.stop()

latest = classify_effort(rows, mint)
left, middle, right, last = st.columns(4)
left.metric("Sinyal", str(latest.get("signal") or "insufficient_data"))
middle.metric("Ratio hari ini",
              f"{latest['ratio_N']:.3f} SOL/1%"
              if latest.get("ratio_N") is not None else "—")
right.metric("Multiplier",
             f"×{latest['multiplier']:.2f}"
             if latest.get("multiplier") is not None else "—")
last.metric("Bias", str(latest.get("bias") or "—").upper())

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
    if result.get("signal") in {
            "S1_PENYERAPAN", "S2_DUMP_DISTRIBUSI",
            "S3_DISTRIBUSI_KE_KUAT", "S4_PUMP_ASLI"}:
        index = dates.index(date)
        color = "#16a34a" if result.get("bias") == "bullish" else "#dc2626"
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
    if result.get("bias") == "bullish" and result.get("signal") != "S5_NETRAL":
        colors.append("#16a34a")
    elif result.get("bias") == "bearish" and result.get("signal") != "S5_NETRAL":
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
