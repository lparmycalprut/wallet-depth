# -*- coding: utf-8 -*-
"""Analisa holder — dust % MC, grafik 4 jam, kohort mid-tier.

Halaman di bawah CVD. Fokus: dust nambah = indikasi dump.
- ≥ 0,5% MC → HATI-HATI
- ≥ 1% MC   → BAHAYA
Kohort Crab+Fish di-freeze 4 jam; sisa token (bukan USD) mengukur exit pilar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

import matplotlib.pyplot as plt
import streamlit as st

from helius_holders import depth_bar_chart
from holder_chronology import (SAMPLED_NOTE, SNAPSHOT_AWAL_MESSAGE,
                               TRUNCATED_NOTE, fmt_id_decimal, fmt_id_int,
                               format_wib as _chrono_wib, interval_narrative,
                               interval_title, movement_table_rows)
from holder_history import (DUST_CAUTION_PCT, DUST_DANGER_PCT,
                            FULL_SCAN_MAX_WALLETS, baseline_for_mint,
                            bucket_delta, bucket_series,
                            chronology_view_for_mint, dust_flag,
                            history_for_mint, ingest_many,
                            latest_detail_for_mint, load_holder_history,
                            merge_points, resample_4h, seed_from_status,
                            tracked_chronology_addresses)
from links import external_links_html
from holder_analysis import analyze_token
from holder_status import load_holder_status
from watchlist import add_to_watchlist, load_watchlist

st.set_page_config(page_title="Holder Analytic", page_icon="🧮",
                   layout="wide")
st.title("🧮 Holder Analytic")
st.caption(
    f"Dust holder (nilai ≤ $10) sebagai jejak dump: **≥ {DUST_CAUTION_PCT:g}% "
    f"MC = HATI-HATI**, **≥ {DUST_DANGER_PCT:g}% MC = BAHAYA**. Grafik "
    "di-resample **4 jam sekali**. "
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
    if flag.get("rising") and level in ("danger", "caution"):
        label = f"{label} ↑"
    colors = {
        "ok": ("#14532d", "#dcfce7"),
        "caution": ("#78350f", "#fef3c7"),
        "danger": ("#7f1d1d", "#fee2e2"),
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
    axis.axhline(DUST_CAUTION_PCT, color="#b45309", linestyle=":",
                 linewidth=1, label=f"Hati-hati {DUST_CAUTION_PCT:g}%")
    axis.axhline(DUST_DANGER_PCT, color="#b91c1c", linestyle="--",
                 linewidth=1, label=f"Bahaya {DUST_DANGER_PCT:g}%")
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


def _fmt_int(value) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "—"


def _holder_count_chart(points: list[dict]) -> None:
    """Grafik jumlah holder 4 jam: total + pecahan dust / real / pilar."""
    sampled = resample_4h(points)
    rows = [p for p in sampled if p.get("holder_count")
            or p.get("dust_count") or p.get("real_count")]
    if len(rows) < 2:
        st.info("Grafik jumlah holder butuh minimal 2 titik. Tekan "
                "**Scan holder FULL** lagi setelah beberapa jam, atau tunggu "
                "cron (~15 menit) mencatat perubahan.")
        return
    labels = [_wib(p.get("ts")) for p in rows]
    dust_n = [int(p.get("dust_count") or 0) for p in rows]
    real_n = [int(p.get("real_count") or 0) for p in rows]
    total_n = [int(p.get("holder_count") or 0) or (d + r)
               for p, d, r in zip(rows, dust_n, real_n)]
    mid_n = [int(p.get("mid_count") or 0) for p in rows]

    fig, axis = plt.subplots(figsize=(11, 4.0))
    axis.stackplot(labels, dust_n, real_n, colors=("#f59e0b", "#0ea5e9"),
                   alpha=.55, labels=("Dust ≤ $10", "Real > $10"))
    axis.plot(labels, total_n, color="#0f172a", marker="o", linewidth=2,
              label="Total holder")
    axis.plot(labels, mid_n, color="#7c3aed", marker="^", linewidth=1.6,
              linestyle="--", label="Pilar Crab+Fish")
    axis.set_ylabel("Jumlah holder")
    axis.tick_params(axis="x", rotation=30)
    axis.grid(alpha=.2)
    axis.legend(frameon=False, loc="upper left", ncols=2, fontsize=8)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    first, last = rows[0], rows[-1]
    delta_total = (int(last.get("holder_count") or 0)
                   - int(first.get("holder_count") or 0))
    delta_dust = int(last.get("dust_count") or 0) - int(first.get("dust_count") or 0)
    st.caption(
        f"Sejak {_wib(first.get('ts'))}: total holder "
        f"{delta_total:+,} · dust {delta_dust:+,} wallet.")


def _bucket_trend_chart(points: list[dict]) -> None:
    """Komposisi holder per range nilai USD sepanjang waktu (area bertumpuk)."""
    stamps, labels, series = bucket_series(points)
    if len(stamps) < 2:
        return
    x_labels = [_wib(ts) for ts in stamps]
    colors = ("#94a3b8", "#64748b", "#3b82f6", "#10b981", "#f59e0b",
              "#ef4444", "#8b5cf6")
    fig, axis = plt.subplots(figsize=(11, 3.8))
    axis.stackplot(x_labels, *[series[label] for label in labels],
                   labels=labels, colors=colors[:len(labels)], alpha=.85)
    axis.set_ylabel("Holder per range USD")
    axis.tick_params(axis="x", rotation=30)
    axis.grid(alpha=.15)
    axis.legend(frameon=False, loc="upper left", ncols=4, fontsize=7)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def _distribution_section(mint: str, symbol: str, store: dict) -> None:
    """Bar chart Wallet Depth + tabel perubahan vs baseline scan pertama."""
    baseline = baseline_for_mint(store, mint)
    latest = latest_detail_for_mint(store, mint)
    if not latest:
        st.info("Belum ada scan FULL untuk token ini. Tekan tombol "
                "**Scan holder FULL** di bawah — hasil detailnya disimpan "
                "sebagai baseline dan tidak akan ditimpa cron.")
        return

    depth = latest.get("depth") or {}
    fig = depth_bar_chart(
        depth, title=f"Distribusi holder ${symbol.upper()} per range nilai (USD)")
    if fig is not None:
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)

    st.caption(
        f"Scan FULL terakhir: {_wib(latest.get('ts'))} · "
        f"{_fmt_int(latest.get('fetched'))} akun diambil "
        f"({_fmt_int(latest.get('pages'))} halaman)"
        + (" · masih terpotong limit" if latest.get("truncated") else "")
        + f" · baseline pertama: {_wib(baseline.get('ts'))}.")

    tiers = depth.get("tiers") or []
    if tiers:
        cols = st.columns(len(tiers))
        for col, tier in zip(cols, tiers):
            col.metric(
                f"{tier.get('emoji') or ''} {tier.get('tier') or '?'}",
                _fmt_int(tier.get("count")),
                _fmt_pct(tier.get("pct_mc")))

    rows = bucket_delta(baseline, latest)
    if rows and baseline.get("ts") and baseline.get("ts") != latest.get("ts"):
        st.markdown("**Perubahan vs scan pertama (baseline)**")
        st.dataframe(
            [{"Range": r["label"], "Baseline": r["base_count"],
              "Sekarang": r["now_count"], "Δ": f"{r['delta']:+,}"}
             for r in rows],
            use_container_width=True, hide_index=True)


def _delta_int(before, after) -> str:
    try:
        return f"{int(after or 0) - int(before or 0):+,}"
    except (TypeError, ValueError):
        return "—"


def _delta_pct_points(before, after) -> str:
    if before is None or after is None:
        return "—"
    try:
        return f"{float(after) - float(before):+.2f} poin"
    except (TypeError, ValueError):
        return "—"


def _movement_dataframe(movements) -> None:
    rows = movement_table_rows(movements)
    if not rows:
        return
    display = [{
        "Wallet": row["Wallet"],
        "Kategori awal": row["Kategori awal"],
        "Kategori terbaru": row["Kategori terbaru"],
        "Balance awal": row["Balance awal"],
        "Balance terbaru": row["Balance terbaru"],
        "Delta balance token": row["Delta balance token"],
        "Nilai USD awal": row["Nilai USD awal"],
        "Nilai USD terbaru": row["Nilai USD terbaru"],
        "Interpretasi": row["Interpretasi"],
        "Solscan": row["Solscan"],
    } for row in rows]
    kwargs = {
        "use_container_width": True,
        "hide_index": True,
    }
    try:
        kwargs["column_config"] = {
            "Solscan": st.column_config.LinkColumn("Solscan",
                                                   display_text="Solscan"),
        }
    except Exception:  # noqa: BLE001 - Streamlit lama tanpa LinkColumn
        pass
    st.dataframe(display, **kwargs)


def _chronology_section(mint: str, store: dict) -> None:
    """Kronologi holder sejak snapshot FULL pertama — survive rerun."""
    view = chronology_view_for_mint(store, mint)
    st.subheader("🧭 Kronologi Holder Sejak Snapshot Awal")
    state = view.get("state") or "none"
    if state == "none":
        st.info("Belum ada snapshot FULL. Jalankan **Scan holder FULL** untuk "
                "menyimpan snapshot awal. Kronologi perubahan baru muncul "
                "setelah scan FULL berikutnya.")
        return
    if state == "initial":
        st.caption(
            f"Snapshot awal: {_chrono_wib(view.get('baseline_ts'))}.")
        st.info(view.get("message") or SNAPSHOT_AWAL_MESSAGE)
        if view.get("sampled"):
            st.caption(SAMPLED_NOTE)
        if view.get("truncated"):
            st.caption(TRUNCATED_NOTE)
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Snapshot awal", _chrono_wib(view.get("baseline_ts")))
    c2.metric("Snapshot terbaru", _chrono_wib(view.get("latest_ts")))
    c3.metric("Periode", view.get("duration_label") or "—")

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Jumlah holder",
              _fmt_int(view.get("holder_count_to")),
              _delta_int(view.get("holder_count_from"),
                         view.get("holder_count_to")))
    d2.metric("Dust wallet",
              _fmt_int(view.get("dust_count_to")),
              _delta_int(view.get("dust_count_from"),
                         view.get("dust_count_to")))
    d3.metric("dust % MC",
              _fmt_pct(view.get("dust_pct_to")),
              _delta_pct_points(view.get("dust_pct_from"),
                                view.get("dust_pct_to")))
    counts = view.get("counts") or {}
    d4.metric("Wallet baru", fmt_id_int(counts.get("new_wallets")))

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Saldo meningkat", fmt_id_int(counts.get("increased")))
    e2.metric("Saldo menurun", fmt_id_int(counts.get("decreased")))
    e3.metric("Saldo 0 / tidak ditemukan",
              fmt_id_int((counts.get("exited_total") or 0)
                         + (counts.get("unobserved") or 0)))
    e4.metric("Pindah kategori", fmt_id_int(counts.get("category_moves")))

    st.write(view.get("narrative") or "")
    if view.get("wallet_sample_lag"):
        st.caption("Sampel wallet mulai dicatat setelah snapshot awal. "
                   "Perpindahan wallet dihitung sejak sampel wallet pertama.")
    if view.get("sampled"):
        st.caption(SAMPLED_NOTE)
    if view.get("truncated"):
        st.caption(TRUNCATED_NOTE)
    if view.get("price_missing"):
        st.caption("Harga atau market cap tidak tersedia pada salah satu "
                   "snapshot, jadi nilai USD / dust % MC mungkin tidak lengkap.")

    cumulative = view.get("cumulative_movements") or []
    if cumulative:
        st.markdown("**Perpindahan wallet sejak snapshot awal (sampel)**")
        _movement_dataframe(cumulative)

    st.markdown("**Kronologi per Scan holder FULL**")
    for interval in view.get("intervals") or []:
        with st.expander(interval_title(interval), expanded=False):
            from_m = interval.get("from_metrics") or {}
            to_m = interval.get("to_metrics") or {}
            st.caption(
                f"{_chrono_wib(interval.get('from_ts'))} → "
                f"{_chrono_wib(interval.get('to_ts'))} · holder "
                f"{fmt_id_int(from_m.get('holder_count'))} → "
                f"{fmt_id_int(to_m.get('holder_count'))} · dust "
                f"{fmt_id_decimal(from_m.get('dust_pct_mc'))}% MC → "
                f"{fmt_id_decimal(to_m.get('dust_pct_mc'))}% MC"
                + (" · scan terpotong" if interval.get("truncated") else "")
                + (" · sampel wallet" if interval.get("sampled") else ""))
            st.write(interval_narrative(interval))
            icounts = interval.get("counts") or {}
            st.caption(
                f"Saldo naik {fmt_id_int(icounts.get('increased'))} · "
                f"saldo turun {fmt_id_int(icounts.get('decreased'))} · "
                f"baru {fmt_id_int(icounts.get('new_wallets'))} · "
                f"keluar/0 {fmt_id_int(icounts.get('exited_total'))} · "
                f"tidak teramati {fmt_id_int(icounts.get('unobserved'))} · "
                f"pindah kategori {fmt_id_int(icounts.get('category_moves'))}.")
            _movement_dataframe(interval.get("movements") or [])


watchlist = load_watchlist()
mints = list(watchlist)
status = load_holder_status()
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
    f"· dust ≥ {DUST_CAUTION_PCT:g}% MC = HATI-HATI"
    f" · ≥ {DUST_DANGER_PCT:g}% MC = BAHAYA"
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

st.subheader("Grafik dust & pilar (4 jam)")
_history_charts(points)

st.subheader("📊 Grafik holder")
st.caption(
    "Jumlah holder sepanjang waktu (total, dust ≤ $10, real > $10, pilar "
    "Crab+Fish) dan komposisi holder per range nilai USD. Titik diambil dari "
    "scan FULL manual + pencatatan perubahan oleh cron.")
_holder_count_chart(points)
_bucket_trend_chart(points)

st.subheader("🧱 Distribusi holder (scan FULL)")
_distribution_section(
    mint, str((watchlist.get(mint) or {}).get("symbol")
              or token.get("symbol") or "?"), store)

_chronology_section(mint, store)

st.divider()
st.caption(
    f"Scan manual = **FULL holder** (hingga {FULL_SCAN_MAX_WALLETS:,} akun, "
    "paginasi Helius sampai habis). Detail scan pertama disimpan permanen "
    "sebagai **baseline** di `holder_history.json`; cron 15 menit hanya "
    "menambah titik perubahan dan tidak pernah menimpa baseline.")
if st.button("🔄 Scan holder FULL token ini", type="primary",
             use_container_width=True):
    cohort = ((store.get("tokens") or {}).get(mint) or {}).get("cohort") or {}
    addrs = list((cohort.get("balances") or {}).keys())
    with st.status("Mengambil SELURUH holder dari Helius…", expanded=False):
        try:
            analysis = analyze_token(
                mint, str((watchlist.get(mint) or {}).get("symbol")
                          or token.get("symbol") or "?"),
                max_wallets=FULL_SCAN_MAX_WALLETS,
                fetch_market=True, cohort_addrs=addrs)
        except Exception as exc:  # noqa: BLE001
            analysis = None
            st.error(f"Gagal: {exc}")
    if analysis:
        ingest_many({mint: analysis}, detail=True)
        st.rerun()
