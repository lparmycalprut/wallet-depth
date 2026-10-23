# -*- coding: utf-8 -*-
"""UI read-only Early Watcher (dipanggil dari ``pages/10_⚡_Early_Watcher.py``).

Halaman ini hanya membaca ``early_watch_state.json``. Tidak ada fetch GMGN dan
tidak ada kirim Telegram dari UI. Data diisi oleh ``scripts/early_watch.py``
di GitHub Actions.
"""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

import early_watch as ew


def _wib(ts) -> str:
    if not ts:
        return "—"
    return time.strftime("%d %b %H:%M:%S", time.gmtime(int(ts) + 7 * 3600))


def _mint_rows(state: dict, mints: list, labels: dict | None = None) -> list:
    labels = labels or {}
    rows = []
    for mint in mints:
        rec = state.get("mints", {}).get(mint, {})
        last_alert = rec.get("last_alert") or {}
        rows.append({
            "Status": rec.get("status") or "BELUM ADA DATA",
            "Koin": ew.coin_label(labels, mint),
            "Poll terakhir (WIB)": _wib(rec.get("last_poll")),
            "Aktivitas terakhir (WIB)": _wib(rec.get("last_active_ts")),
            "Putaran/60 dtk (puncak)": rec.get("rt_peak", 0),
            "Wallet/60 dtk (puncak)": rec.get("wallets_peak", 0),
            "Selisih maks %": round(float(rec.get("max_spread") or 0) * 100, 1),
            "Jual besar tersimpan": len(rec.get("dumps") or []),
            "Harga terakhir": rec.get("last_price"),
            "Jumlah alert": int(rec.get("alerts") or 0),
            "Alert terakhir terkirim": ("ya" if last_alert.get("sent") else
                                        ("gagal" if last_alert else "—")),
            "Data terpotong": "ya" if rec.get("partial") else "",
            "Error": rec.get("error") or "",
        })
    return rows


def render_early_page() -> None:
    st.title("⚡ Early Watcher")
    st.caption(
        "Info saja. Tidak mengubah verdict, skor, atau filter 🌊 Sweep. "
        "Semua mint watchlist dipantau, termasuk yang di-mute atau tersembunyi di Sweep.")

    state = ew.load_state()
    mints = ew.load_watchlist()
    labels = ew.load_coin_labels()
    updated = state.get("updated") or 0
    st.info(
        f"Snapshot disimpan: **{_wib(updated)} WIB**. Snapshot diperbarui saat keputusan "
        "berubah (alert, status, cooldown, atau jual besar). Poll 2 menit tercatat di log "
        "GitHub Actions dan bagian log di bawah.")

    st.subheader("Kriteria")
    st.markdown(
        f"- **Putaran**: satu wallet, satu tx, beli di satu pasar dan jual di pasar lain; "
        f"selisih {ew.ROUND_TRIP_MIN_SPREAD * 100:.0f}%–{ew.ROUND_TRIP_MAX_SPREAD * 100:.0f}%.\n"
        f"- **Aktif**: ≥ {ew.ACTIVE_MIN_TRADES} putaran dari ≥ {ew.ACTIVE_MIN_WALLETS} wallet "
        f"dalam {ew.WINDOW_SEC} detik.\n"
        f"- **Jual besar sebelum aktif**: satu jual ≥ ${ew.DUMP_MIN_USD:,.0f} "
        f"dalam {ew.DUMP_LOOKBACK_SEC // 60} menit sebelum awal aktivitas "
        "(usulan, belum dikonfirmasi user). Aktivitas tanpa jual besar tidak dikirim sebagai alert.\n"
        f"- **Awal**: aktif setelah {ew.QUIET_SEC // 60} menit tanpa aktivitas; "
        f"cooldown alert {ew.COOLDOWN_SEC // 60} menit.")

    st.subheader("Status per mint")
    if not mints:
        st.warning("Watchlist kosong (`early_watch_watchlist.json`).")
    else:
        df = pd.DataFrame(_mint_rows(state, mints, labels))
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("Log poll terakhir")
    log = list(state.get("log") or [])[-100:]
    if log:
        log_df = pd.DataFrame([{
            "Waktu (WIB)": _wib(row.get("t")),
            "Koin": ew.coin_label(labels, str(row.get("mint", ""))),
            "Status": row.get("status"), "Trade": row.get("trades", 0),
            "Putaran": row.get("rt", 0), "Wallet": row.get("wallets", 0),
            "Terpotong": "ya" if row.get("partial") else "",
            "Error": row.get("error", ""),
        } for row in reversed(log)])
        st.dataframe(log_df, use_container_width=True, hide_index=True)
    else:
        st.caption("Belum ada log. Workflow `early-watch` belum berjalan atau belum di-merge ke main.")
