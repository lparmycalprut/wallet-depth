# -*- coding: utf-8 -*-
"""🔎 Deteksi Akumulasi — 8 heuristik akumulasi untuk token watchlist.

Sumber token **selalu** ``watchlist.load_watchlist()`` (watchlist.json /
GitHub + journal pending) — bukan listing Meteora/trending. Semua bahan mentah
ditarik lewat fetcher yang sudah ada:

===========================================  =================================
Bahan                                        Fetcher yang dipakai (reuse)
===========================================  =================================
titik holder per scan (tier/dust)            ``holder_history`` + ``holder_status``
swap per wallet + tag maker + realized PnL   ``cvd.fetch_gmgn_swaps`` (GMGN)
volume 24 jam + marketcap                    ``core.get_market`` (DexScreener)
candle hourly → metrik volatilitas & 4 jam   ``core.get_hourly_candles``
candle harian → level support D1             ``core.aggregate_daily_candles``
===========================================  =================================

**Kuota Helius tidak dipakai sama sekali** di halaman ini: metrik 4 memakai
metadata GMGN (``realized_profit``/``maker_tags``) dan metrik 7 memakai tag
``fresh_wallet`` GMGN, jadi tidak ada scan holder/funder Helius tambahan
(keputusan user 2026-09-04).

⚠️ Semua metrik **heuristik** — penanda untuk diperiksa manual, **bukan** bukti
akumulasi dan **bukan** prediksi arah harga (disclaimer yang sama dipakai
README/AGENTS untuk rule dust, cluster, dan funder).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import streamlit as st

import accumulation as acc
import core
import cvd
from holder_history import (calculate_volatility_metrics, history_for_mint,
                            load_durable_holder_history, merge_points,
                            seed_from_status)
from holder_status import (MANUAL_SCAN_KEY, apply_manual_scan,
                           load_holder_status)
from links import external_links_html
from watchlist import load_watchlist

st.set_page_config(page_title="Deteksi Akumulasi", page_icon="🔎",
                   layout="wide")

st.title("🔎 Deteksi Akumulasi")
st.caption(
    "8 heuristik akumulasi untuk token **watchlist** (sumber daftar: "
    "`watchlist.json` lewat `watchlist.load_watchlist`). Skor 0–100 hanya "
    "menghitung metrik yang datanya cukup. **Heuristik, bukan bukti dan bukan "
    "prediksi arah harga.** Halaman ini **tidak** memakai kuota Helius: swap "
    "diambil dari GMGN, pasar dari DexScreener, candle dari GeckoTerminal, "
    "holder dari snapshot/store yang sudah ada.")

STATUS_COLORS = {
    acc.TOKEN_AKUMULASI: ("#14532d", "#dcfce7"),
    acc.TOKEN_NETRAL: ("#334155", "#e2e8f0"),
    acc.TOKEN_NO_DATA: ("#78350f", "#fef3c7"),
}
METRIC_COLORS = {
    acc.POSITIF: ("#14532d", "#dcfce7"),
    acc.NETRAL: ("#334155", "#e2e8f0"),
    acc.NEGATIF: ("#7f1d1d", "#fee2e2"),
    acc.NO_DATA: ("#78350f", "#fef3c7"),
}


def _chip(label: str, colors) -> str:
    bg, fg = colors
    return (f'<span style="display:inline-block;padding:.2rem .55rem;'
            f'border-radius:8px;font-size:.72rem;font-weight:800;'
            f'background:{bg};color:{fg};">{label}</span>')


def _points_for(mint: str, token: dict | None, store: dict) -> list[dict]:
    """Titik history file + salinan ringkas snapshot (pola ``app.py``)."""
    return merge_points(history_for_mint(store, mint),
                        (token or {}).get("history") or [])


def fetch_token_inputs(mint: str, *, window_days: int, max_pages: int) -> dict:
    """Tarik semua bahan mentah satu token lewat fetcher yang sudah ada.

    Tidak ada jalur API baru di sini; GMGN dibatasi ``max_pages`` + window
    ``stop_ts`` supaya kuota tidak jebol, dan satu token gagal tidak
    menghentikan token lain.
    """
    inputs: dict = {"mint": mint, "swaps": [], "wallet_meta": {},
                    "gmgn": {}, "market": {}, "volatility": None,
                    "hourly": [], "daily": [], "pair": "", "errors": []}

    # 1) Swap + metadata wallet (GMGN — fetcher cvd yang sudah ada).
    cutoff = int(time.time()) - int(window_days) * 86_400
    try:
        swaps, _sig, _ts, _hit = cvd.fetch_gmgn_swaps(
            mint, stop_ts=cutoff, max_pages=int(max_pages))
        inputs["swaps"] = list(swaps or [])
        # Metadata wajib dibaca langsung: cvd menyimpannya per fetch terakhir.
        inputs["wallet_meta"] = dict(cvd.get_gmgn_wallet_metadata() or {})
        inputs["gmgn"] = dict(cvd.get_gmgn_fetch_status() or {})
    except Exception as exc:  # noqa: BLE001 - satu token tidak boleh mematikan
        inputs["errors"].append(f"GMGN swaps: {exc}")

    # 2) Pasar (DexScreener — core.get_market yang sudah ada).
    try:
        inputs["market"] = core.get_market(mint) or {}
    except Exception as exc:  # noqa: BLE001
        inputs["errors"].append(f"DexScreener market: {exc}")

    # 3) Candle hourly (GeckoTerminal — core.get_hourly_candles) untuk metrik
    #    volatilitas/range (5) dan spring 4 jam (6). Candle harian diagregasi
    #    dari candle yang sama, jadi tidak ada request kedua.
    inputs["pair"] = acc.select_pair_address(inputs["market"])
    if inputs["pair"]:
        inputs["hourly"] = core.get_hourly_candles(inputs["pair"], 168) or []
        inputs["daily"] = core.aggregate_daily_candles(inputs["hourly"], 7)
        if inputs["hourly"]:
            inputs["volatility"] = calculate_volatility_metrics(
                inputs["hourly"][-4:], inputs["hourly"])
    return inputs


def analyze(mint: str, *, window_days: int, max_pages: int,
            points: list[dict] | None = None, store: dict | None = None) -> dict:
    """Satu token: fetch bahan mentah → ``accumulation.build_token_report``."""
    inputs = fetch_token_inputs(mint, window_days=window_days,
                                max_pages=max_pages)
    previous = acc.thinning_previous(store, mint) if store else None
    report = acc.build_token_report(
        mint, str((inputs.get("market") or {}).get("symbol") or "?"),
        points=points, swaps=inputs["swaps"],
        wallet_meta=inputs["wallet_meta"], market=inputs["market"],
        volatility=inputs["volatility"], hourly=inputs["hourly"],
        daily_candles=inputs["daily"], previous_thinning=previous,
        now=int(time.time()))
    report["inputs"] = {
        "swaps": len(inputs["swaps"]),
        "wallet_meta": len(inputs["wallet_meta"]),
        "gmgn": inputs["gmgn"],
        "points": len(points or []),
        "candles": len(inputs["hourly"]),
        "volume_h24": ((inputs["market"].get("volume") or {}).get("h24")
                       if isinstance(inputs["market"].get("volume"), dict)
                       else None),
        "errors": inputs["errors"],
    }
    return report


def _detail_lines(result: dict) -> list[str]:
    """Baris angka mentah untuk expander (di luar penjelasan teks)."""
    detail = result.get("detail") or {}
    nilai = result.get("nilai") if isinstance(result.get("nilai"), dict) else {}
    lines = []
    if result.get("nilai") is not None and not isinstance(result["nilai"], dict):
        lines.append(f"Nilai metrik: **{result['nilai']}**")
    for key, value in nilai.items():
        lines.append(f"`{key}` = {value}")
    for key in ("deltas", "mid_up", "mid_down", "level", "wick_pct",
                "volume_ratio", "quiet_wallets", "holders", "days",
                "previous_pct", "delta_pp", "smart_wallets", "net_buyers",
                "median_realized_usd", "fresh_wallets", "gradual",
                "range_menyempit", "volume_tenang", "cvd_positif_tipis",
                "lantai_usd", "plafon_usd", "price_stddev_4h",
                "history_stddev_pct", "cvd_net_pct", "dust_before",
                "dust_change_pct", "from_ts", "to_ts", "ambang_stabil_pct"):
        if key in detail and key not in nilai:
            lines.append(f"`{key}` = {detail[key]}")
    if result.get("sumber"):
        lines.append(f"Sumber data: {result['sumber']}")
    return lines


# ---------------------------------------------------------------------------
# Kontrol
# ---------------------------------------------------------------------------
watchlist = load_watchlist()
holder_status = apply_manual_scan(load_holder_status(),
                                  st.session_state.get(MANUAL_SCAN_KEY))
status_tokens = holder_status.get("tokens") or {}
history_store = seed_from_status(load_durable_holder_history(), holder_status)
accumulation_store = acc.load_accumulation_history()

if not watchlist:
    st.info("Watchlist kosong. Tambahkan token di halaman utama dulu — "
            "halaman ini hanya membaca daftar token dari watchlist yang "
            "sudah ada.")
    st.stop()

labels = {mint: f"${str((meta or {}).get('symbol') or '?').upper()} — "
                f"{mint[:8]}…" for mint, meta in watchlist.items()}

col_pick, col_days, col_pages = st.columns([3, 1, 1])
with col_pick:
    picked = st.multiselect(
        "Token watchlist", list(watchlist), default=list(watchlist)[:3],
        format_func=lambda value: labels.get(value, value),
        help="Sumber daftar: watchlist.json / GitHub (watchlist.load_watchlist).")
with col_days:
    window_days = st.number_input("Window swap (hari)", min_value=1,
                                  max_value=30, value=7, step=1,
                                  help="Berapa hari swap GMGN yang ditarik.")
with col_pages:
    max_pages = st.number_input("Maks halaman GMGN", min_value=1,
                                max_value=20, value=4, step=1,
                                help=("Batas halaman per token supaya kuota "
                                      "GMGN tidak jebol (100 trade/halaman)."))

st.caption("Fetch berjalan berurutan dengan jeda antar token (pola rate-limit "
           "yang sama dipakai cron). Hasil disimpan di session state; klik "
           "ulang untuk menghitung lagi.")

if st.button("🔎 Hitung akumulasi", type="primary",
             use_container_width=True, disabled=not picked):
    reports = {}
    total = len(picked)
    bar = st.progress(0.0, text=f"Hitung 0/{total} token…")
    for index, mint in enumerate(picked, start=1):
        meta = watchlist.get(mint) or {}
        points = _points_for(mint, status_tokens.get(mint) or {}, history_store)
        try:
            report = analyze(mint, window_days=int(window_days),
                             max_pages=int(max_pages), points=points,
                             store=accumulation_store)
            report["symbol"] = str(meta.get("symbol")
                                   or report.get("symbol") or "?").upper()
            accumulation_store = acc.record_snapshot(
                accumulation_store, mint, report)
        except Exception as exc:  # noqa: BLE001 - tampilkan, jangan berhenti
            report = {"mint": mint,
                      "symbol": str(meta.get("symbol") or "?").upper(),
                      "status": acc.TOKEN_NO_DATA, "score": None,
                      "results": [], "metrics": {}, "metrics_used": 0,
                      "metrics_total": 8, "positives": [],
                      "missing": list(acc.METRIC_NAMES),
                      "inputs": {"errors": [str(exc)]}}
        reports[mint] = report
        bar.progress(index / max(total, 1),
                     text=f"Hitung {index}/{total} · {report['symbol']}")
        if index < total:
            time.sleep(0.4)      # jeda antar token, pola rate-limit cron
    acc.save_accumulation_history(accumulation_store)
    st.session_state["accumulation_reports"] = reports
    st.session_state["accumulation_params"] = {
        "window_days": int(window_days), "max_pages": int(max_pages),
        "run_at": int(time.time())}

reports = st.session_state.get("accumulation_reports") or {}
params = st.session_state.get("accumulation_params") or {}
if not reports:
    st.info("Pilih token lalu klik **Hitung akumulasi**.")
    st.stop()

# ---------------------------------------------------------------------------
# Ringkasan + breakdown per token
# ---------------------------------------------------------------------------
st.subheader("Ringkasan")
summary_rows = []
for mint, report in reports.items():
    summary_rows.append({
        "Token": f"${report.get('symbol') or '?'}",
        "Skor": report.get("score") if report.get("score") is not None else "—",
        "Status": report.get("status") or acc.TOKEN_NO_DATA,
        "Metrik terpakai": f"{report.get('metrics_used', 0)}/"
                           f"{report.get('metrics_total', 8)}",
        "Terpenuhi": len(report.get("positives") or []),
        "Swap": (report.get("inputs") or {}).get("swaps", 0),
    })
st.dataframe(summary_rows, use_container_width=True, hide_index=True)
if params:
    when = datetime.fromtimestamp(params.get("run_at") or 0, timezone.utc)
    st.caption(f"Dihitung {when.strftime('%d %b %H:%M UTC')} · window swap "
               f"{params.get('window_days')} hari · maks "
               f"{params.get('max_pages')} halaman GMGN per token.")

for mint, report in reports.items():
    symbol = report.get("symbol") or "?"
    score = report.get("score")
    status = report.get("status") or acc.TOKEN_NO_DATA
    head_cols = st.columns([2.2, 1.0, 1.4, 3.4])
    head_cols[0].markdown(
        f'<div style="font-size:1.15rem;font-weight:800;">${symbol}</div>'
        f'<div style="font-size:.72rem;font-family:monospace;">{mint}</div>'
        f'<div>{external_links_html(mint)}</div>', unsafe_allow_html=True)
    head_cols[1].markdown(
        f'<div style="font-size:1.5rem;font-weight:800;text-align:center;">'
        f"{score if score is not None else '—'}</div>"
        f'<div style="font-size:.65rem;text-align:center;">skor 0–100</div>',
        unsafe_allow_html=True)
    head_cols[2].markdown(
        f'<div style="text-align:center;">{_chip(status, STATUS_COLORS.get(status, STATUS_COLORS[acc.TOKEN_NO_DATA]))}</div>'
        f'<div style="font-size:.65rem;text-align:center;">'
        f"metrik terpakai {report.get('metrics_used', 0)}/"
        f"{report.get('metrics_total', 8)}</div>", unsafe_allow_html=True)
    head_cols[3].markdown(
        '<div style="font-size:.7rem;color:#334155;">Heuristik: penanda untuk '
        "diperiksa manual, bukan bukti akumulasi dan bukan prediksi arah "
        "harga.</div>", unsafe_allow_html=True)

    inputs = report.get("inputs") or {}
    if inputs.get("errors"):
        st.warning("Sebagian data gagal diambil: "
                   + " · ".join(str(item) for item in inputs["errors"]))
    gmgn = inputs.get("gmgn") or {}
    st.caption(
        f"Bahan mentah: {inputs.get('swaps', 0)} swap GMGN"
        f"{' (lengkap)' if gmgn.get('complete') else ' (tidak lengkap)'} · "
        f"{inputs.get('wallet_meta', 0)} metadata wallet · "
        f"{inputs.get('points', 0)} titik holder · "
        f"{inputs.get('candles', 0)} candle hourly.")

    with st.expander(f"Breakdown 8 metrik — ${symbol}", expanded=False):
        results = report.get("results") or []
        if not results:
            st.write("Tidak ada metrik yang bisa dihitung.")
        for result in results:
            colors = METRIC_COLORS.get(result.get("status"),
                                       METRIC_COLORS[acc.NO_DATA])
            st.markdown(
                f"**{result.get('nama')}** &nbsp; "
                f"{_chip(result.get('status_label') or '', colors)} &nbsp; "
                f"<span style='font-size:.8rem;color:#334155;'>"
                f"{result.get('nilai_text') or ''}</span>",
                unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:.82rem;'>"
                        f"{result.get('penjelasan')}</div>",
                        unsafe_allow_html=True)
            for line in _detail_lines(result):
                st.markdown(f"<div style='font-size:.72rem;color:#475569;'>"
                            f"{line}</div>", unsafe_allow_html=True)
            st.markdown('<hr style="margin:.4rem 0;border-color:#e2e8f0;">',
                        unsafe_allow_html=True)
    st.divider()
