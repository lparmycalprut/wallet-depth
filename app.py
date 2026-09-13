# -*- coding: utf-8 -*-
"""Wallet Depth — analisa holder (dust % MC) + Scan Meteora."""
from __future__ import annotations

from datetime import datetime, timezone
import html

import matplotlib.pyplot as plt
import streamlit as st

from helius_holders import depth_bar_chart, scan_token_holders
from best_pool_ui import render_best_pool_scan
from holder_history import (FULL_SCAN_MAX_WALLETS, LP_INTERVAL_SEC,
                            holders_usable, ingest_many)
from links import external_links_html, holder_analytic_link_html
from lp_watchlist import (LP_SOURCE, lp_card_rows,
                          lp_summary, split_watchlist)
import page_router
from alert_settings import mutes_for
from dashboard_components import (_alert_toggle_button, _ca_error, _compact,
                                  _dust_badge_html, _mint_alert_on,
                                  _muted_pill_html, _render_dust_change,
                                  _render_rh_card, _render_toggle_note,
                                  _scan_best_badge_html,
                                  _wib, _depth_tables_html,
                                  card_head_html, hover_title_html,
                                  SOLANA_CA_RE, load_dashboard_data,
                                  render_styles)
import activity_log
import robinhood_holders
from robinhood_watchlist import (split_robinhood_watchlist)
from holder_analysis import analyze_token
from holder_status import (load_holder_status, publish_holder_status)
from meteora_screener import fetch_watchlist_metric_snapshots
from meteora_watchlist import apply_metric_snapshots, send_metric_alerts
from watchlist import (add_to_watchlist, remove_from_watchlist, save_watchlist,
                       set_watchlist_source)

st.set_page_config(page_title="Wallet Depth — Holder Analytic",
                   page_icon="🧮", layout="wide",
                   initial_sidebar_state="collapsed")

# Deep link ``?mint=…`` / ``?page=…`` harus diselesaikan SEBELUM ada elemen
# lain: kalau tidak cocok dengan slug halaman (mis. tautan lama berbentuk
# ``pages/5_🧮_Holder.py?mint=…``), Streamlit menjalankan halaman utama ini dan
# router memantulkannya ke halaman Holder. switch_page menghentikan run ini,
# jadi tidak ada work/scan yang terbuang.
page_router.apply()

render_styles()
st.page_link("pages/8_temp.py", label="temp", icon="📦")


# ---------------------------------------------------------------------------
# Auto-refresh data (±60 detik)
# ---------------------------------------------------------------------------
# Cron menulis ``holder_status.json`` baru tiap ±5 menit (lane LP), tapi
# halaman Streamlit hanya meng-fetch ulang saat user berinteraksi (rerun).
# Tanpa ini, card yang sudah terbuka bisa memamerkan snapshot lama selama
# beberapa menit — "di watchlist masih 0,05%" padahal Telegram/cron sudah
# 0,1% (kasus nyata 2026-09-08, $Nasduck). Fragment di bawah jalan tiap 60
# detik: bandingkan ``updated_at`` status (fetch ringan, cache 15 detik),
# dan bila ada snapshot baru → rerun penuh halaman dengan data baru.
AUTOREFRESH_SEC = 60


def _autorefresh_status_ts() -> int:
    try:
        latest = load_holder_status()
        value = (latest or {}).get("updated_at") or 0
        return int(value)
    except (TypeError, ValueError, OSError):
        return 0


@st.fragment(run_every=f"{AUTOREFRESH_SEC}s")
def _autorefresh_tick():
    if not st.session_state.get("autorefresh_on", True):
        return
    latest_ts = _autorefresh_status_ts()
    if not latest_ts:
        return
    if st.session_state.get("autorefresh_seen_ts") != latest_ts:
        st.session_state["autorefresh_seen_ts"] = latest_ts
        st.rerun()


# Teks penjelas di samping toggle **dihapus** (permintaan user 2026-09-11:
# "sudah ada di tooltip") — help toggle di bawah ini sudah bilang hal yang
# sama, jadi tidak ada lagi baris abu-abu di bawahnya.
_autorefresh_col = st.columns([0.30, 0.70])
_autorefresh_col[0].toggle(
    "🔄 Auto-refresh ±60 dtk",
    value=st.session_state.get("autorefresh_on", True),
    key="autorefresh_on",
    help="Lempar ulang halaman otomatis saat snapshot cron baru "
         "muncul (±60 dtk sekali cek). Data baris = snapshot cron "
         "(±5 menit); OFF = halaman hanya terupdate saat ada interaksi "
         "manual.")


# ---------------------------------------------------------------------------
# Watchlist Meteora — watchlist terpisah untuk token dari Scan Meteora Pool
# (card ⭐ yang memasukkan token ada di halaman temp sejak 2026-09-10).
# ---------------------------------------------------------------------------
LP_CARD_TITLE = "🌊 Watchlist Meteora"
# Detail karakteristik card (2026-09-10) tidak lagi jadi caption panjang di
# badan card — pindah ke tooltip judul: hanya muncul saat kursor digeser ke
# atas teks "Watchlist Meteora" (atribut title native browser). Kalau
# karakteristiknya berubah nanti, ubah teks di sini; rule metric dipusatkan di
# meteora_watchlist/meteora_screener supaya tooltip tidak pernah menjelaskan
# alert dust lama. Atribut title tidak mengenal markdown (plain text).
LP_CARD_TOOLTIP = (
    "Watchlist terpisah untuk pool yang ditambahkan dari Scan Meteora "
    "(⭐) atau ditambah manual. Source/timeframe 24 jam atau 30 menit dan "
    "snapshot fee_active_tvl_ratio + volatility ditampilkan di setiap baris. "
    "Baseline metrik disimpan saat masuk watchlist. Deteksi 24h muncul bila "
    "perbandingan fee_active_tvl_ratio terhadap volatility turun minimal 30% "
    "dari baseline; deteksi 30m muncul pada snapshot baru bila volatility > "
    "fee_active_tvl_ratio. Notifikasi lama berbasis dust holder tidak dipakai "
    "lagi untuk Watchlist Meteora. Dust holder tetap tersedia sebagai data "
    "historis, bukan rule alert. Tombol 🔔/🔕 mengatur notif metrik per token.")
LP_ADD_FORM = "lp-add-token"


def _lp_head_html(summary: dict) -> str:
    """Header card Watchlist Meteora: jumlah token + rekap level dust.

    Kepala card dibuat ``dashboard_components.card_head_html`` (pembuat
    bersama dengan card Scan Meteora Pool di halaman temp); detail
    karakteristik card ada di tooltip judul (``LP_CARD_TOOLTIP``).
    """
    pills = [f'<span class="lp-count">{summary.get("total", 0)} token</span>']
    _muted_pill = _muted_pill_html(summary.get("muted"))
    if _muted_pill:
        pills.append(_muted_pill)
    if summary.get("danger"):
        pills.append(f'<span class="lp-warn">BAHAYA {summary["danger"]}</span>')
    if summary.get("caution"):
        pills.append(f'<span class="lp-warn" style="color:#78350f;'
                     f'background:#fef3c7;">HATI-HATI {summary["caution"]}'
                     '</span>')
    if summary.get("safe_lp"):
        pills.append(f'<span class="lp-count">SAFE LP {summary["safe_lp"]}</span>')
    if summary.get("high_risk"):
        pills.append(f'<span class="lp-warn">HIGH RISK {summary["high_risk"]}</span>')
    if summary.get("metric_alerts"):
        pills.append(f'<span class="lp-warn">⚠️ METRIK {summary["metric_alerts"]}</span>')
    return card_head_html(LP_CARD_TITLE, pills, tooltip=LP_CARD_TOOLTIP)



def _metric_display(value, *, decimals: int = 2, suffix: str = "",
                    signed: bool = False, infinity: str = "∞") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number:
        return "—"
    if number == float("inf"):
        return str(infinity)
    prefix = "+" if signed and number > 0 else ""
    return f"{prefix}{number:.{int(decimals)}f}{suffix}"


def _render_lp_row(row: dict) -> None:
    """Satu baris Watchlist Meteora dengan snapshot fee/volatility."""
    mint = row.get("mint") or ""
    symbol = row.get("symbol") or "?"
    holders = row.get("holders") or {}
    flag = row.get("flag") or {}
    dust_pct = row.get("dust_pct")
    dust_count = row.get("dust_count")
    truncated = bool(row.get("used_truncated", holders.get("truncated")))
    dust_txt = ("—" if dust_count is None
                else (f"≥{int(dust_count)}" if truncated
                      else f"{int(dust_count):,}"))
    pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.3f}%"

    timeframe = str(row.get("timeframe") or "24h")
    source_label = "24 jam" if timeframe == "24h" else "30 menit"
    fee_txt = _metric_display(row.get("fee_active_tvl_ratio"))
    volatility_txt = _metric_display(row.get("volatility"))
    metric_ratio_txt = _metric_display(row.get("fee_volatility_ratio"),
                                       decimals=2, infinity="∞")
    metric_alert = row.get("metric_alert") or {}
    metric_active = bool(row.get("metric_alert_active")
                         or metric_alert.get("active"))
    metric_label = str(row.get("metric_classification") or "")
    metric_note = str(row.get("metric_note") or "")
    if metric_active:
        alert_note = str(metric_alert.get("condition") or
                          "deteksi perubahan metrik")
        metric_note = f"⚠️ {alert_note}"
    elif not metric_note:
        metric_note = "snapshot metrik belum tersedia"

    short_note = (" · ⚠️ scan holder terakhir tidak lengkap"
                  if row.get("degraded") else "")
    if row.get("drift"):
        short_note += " · ⚠️ snapshot holder ≠ history"
    if row.get("truncation_swap"):
        short_note += " · ⚠️ memakai scan holder lengkap sebelumnya"
    scan_ts = row.get("used_ts") or row.get("analyzed_at")
    alert_on = _mint_alert_on(mint)
    if not alert_on:
        short_note += " · 🔕 metrik notif off"

    # Source + fee/active TVL + volatility tampil langsung; dust hanya tetap
    # tersedia sebagai data holder, tidak menjadi dasar deteksi LP.
    cols = st.columns([1.42, 0.7, 0.78, 0.72, 0.62, 0.8, 0.78,
                       0.35, 0.35, 0.35, 0.35])
    cols[0].markdown(
        f'<div class="watchlist-token">'
        f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
        f'<span class="watchlist-mint">{html.escape(mint[:8])}…</span>'
        f'<span class="watchlist-metric-sub">MC {_compact(row.get("mc"))} · '
        f'scan {_wib(scan_ts)}{short_note}</span>'
        f'<span class="watchlist-metric-sub">{html.escape(metric_label)} · '
        f'{html.escape(metric_note)}</span>'
        f'<div class="watchlist-links">{external_links_html(mint)}</div>'
        f"</div>", unsafe_allow_html=True)
    cols[1].markdown(
        f'<div class="watchlist-metric"><div '
        f'class="watchlist-metric-value">{html.escape(source_label)}</div>'
        f'<div class="watchlist-metric-sub">source</div></div>',
        unsafe_allow_html=True)
    cols[2].markdown(
        f'<div class="watchlist-metric"><div '
        f'class="watchlist-metric-value">{fee_txt}</div>'
        f'<div class="watchlist-metric-sub">fee/active TVL</div></div>',
        unsafe_allow_html=True)
    cols[3].markdown(
        f'<div class="watchlist-metric"><div '
        f'class="watchlist-metric-value">{volatility_txt}</div>'
        f'<div class="watchlist-metric-sub">volatility</div></div>',
        unsafe_allow_html=True)
    cols[4].markdown(
        f'<div class="watchlist-metric"><div '
        f'class="watchlist-metric-value">{dust_txt}</div>'
        f'<div class="watchlist-metric-sub">wallet dust</div></div>',
        unsafe_allow_html=True)
    cols[5].markdown(
        f'<div class="watchlist-metric"><div '
        f'class="watchlist-metric-value">{pct_txt}</div>'
        f'{_dust_badge_html(flag)}</div>', unsafe_allow_html=True)
    change = metric_alert.get("change_pct")
    change_txt = _metric_display(change, suffix="%", signed=True)
    cols[6].markdown(
        f'<div class="watchlist-metric" title="{html.escape(metric_note)}">'
        f'<div class="watchlist-metric-value">{change_txt}</div>'
        f'<div class="watchlist-metric-sub">rasio vs masuk · {metric_ratio_txt}×'
        f'</div></div>', unsafe_allow_html=True)
    cols[7].markdown(holder_analytic_link_html(mint), unsafe_allow_html=True)
    _alert_toggle_button(cols[8], mint, symbol, scope="lp", alert_on=alert_on)
    if cols[9].button("📋", key=f"lp-move-{mint}",
                      help="Pindahkan ke Watchlist Holder",
                      use_container_width=True):
        set_watchlist_source(mint, "manual", background=True)
        st.rerun()
    if cols[10].button("✕", key=f"lp-remove-{mint}",
                       help="Hapus dari Watchlist Meteora",
                       use_container_width=True):
        remove_from_watchlist(mint, background=True)
        st.rerun()

    # Holder dust graph tetap tersedia sebagai data historis, tetapi tidak
    # dipakai rule/notifikasi Meteora LP baru.
    _render_dust_change(row.get("points"), holders, symbol,
                        interval=LP_INTERVAL_SEC, meta=row,
                        current_pct=dust_pct)
    st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)


def _render_lp_card(lp_watch: dict, status_tokens: dict,
                    history_store: dict) -> None:
    """Card kolom kiri grid: watchlist Meteora + grafik perubahan dust.

    Detail karakteristik card tidak dirender sebagai caption — semua
    keterangan ada di tooltip judul card (``LP_CARD_TOOLTIP``) supaya card
    tetap ramping (permintaan user 2026-09-10).
    """
    rows = lp_card_rows(lp_watch, status_tokens, history_store)
    summary = lp_summary(rows)
    # Jumlah token yang notif Telegram-nya dimatikan user (toggle 🔔/🔕 di
    # baris) — ditampilkan sebagai pill di kepala card.
    summary["muted"] = len(mutes_for(lp_watch or {}))
    with st.container(border=True):
        st.markdown(_lp_head_html(summary), unsafe_allow_html=True)

        with st.expander("➕ Tambah CA manual ke Watchlist Meteora",
                         expanded=not rows):
            with st.form(LP_ADD_FORM, clear_on_submit=True):
                lp_ca = st.text_input(
                    "Contract address", key="lp-ca-input",
                    help="Symbol diambil otomatis dari DexScreener")
                if st.form_submit_button("🌊 Tambah ke Watchlist Meteora"):
                    ca = str(lp_ca or "").strip()
                    ca_error = _ca_error(ca)
                    if ca_error:
                        st.warning(ca_error)
                    else:
                        add_to_watchlist(ca, "?", source=LP_SOURCE,
                                         background=True)
                        st.success(f"{ca[:8]}… masuk Watchlist Meteora.")
                        st.rerun()

        if st.button("🔄 Scan sekarang Watchlist Meteora", type="primary",
                     key="lp-scan-now", use_container_width=True):
            analyses = {}
            total = len(lp_watch or {})
            bar = st.progress(0.0, text=f"Scan Watchlist Meteora 0/{total}…")
            done = 0
            for mint, meta in (lp_watch or {}).items():
                try:
                    # FULL (100.000): urutan getTokenAccounts Helius tidak
                    # urut saldo → cap kecil (dulu 2000) = sampel acak yang
                    # bias, dust terpotong → angka tidak sinkron dgn cron.
                    analyses[mint] = analyze_token(
                        mint, (meta or {}).get("symbol") or "?",
                        max_wallets=FULL_SCAN_MAX_WALLETS,
                        fetch_market=True, detail=False)
                except Exception:  # noqa: BLE001
                    analyses[mint] = None
                done += 1
                bar.progress(done / max(total, 1),
                             text=f"Scan Watchlist Meteora {done}/{total} · "
                                  f"{str((meta or {}).get('symbol') or '?')}")
            bar.empty()
            ok = {mint: item for mint, item in analyses.items()
                  if isinstance(item, dict)}
            fresh = {mint: item for mint, item in ok.items()
                     if holders_usable(item.get("holders"))}
            skipped_short = sorted(set(ok) - set(fresh))
            failed = sorted(mint for mint, item in analyses.items()
                            if not isinstance(item, dict))
            # Alert Watchlist Meteora hanya berasal dari metrik pool. Scan
            # holder manual tetap menambah data/chart, tetapi tidak memanggil
            # process_holder_alerts (rule dust lama sudah dihentikan untuk LP).
            metric_result = {"watchlist": lp_watch, "metrics": {},
                             "events": [], "baseline_changed": []}
            metric_deliveries = []
            try:
                metric_snapshots = fetch_watchlist_metric_snapshots(lp_watch)
                metric_result = apply_metric_snapshots(
                    lp_watch, metric_snapshots,
                    previous_tokens=status_tokens, now=int(datetime.now(
                        timezone.utc).timestamp()))
                if metric_result.get("baseline_changed"):
                    full_watchlist = dict(watchlist)
                    for mint in metric_result["baseline_changed"]:
                        old = dict(full_watchlist.get(mint) or {})
                        fresh_meta = metric_result["watchlist"].get(mint) or {}
                        for key in ("metric_baseline", "metric_baseline_ts",
                                    "timeframe", "pool_timeframe", "pool_address"):
                            if fresh_meta.get(key) is not None:
                                old[key] = fresh_meta[key]
                        full_watchlist[mint] = old
                    save_watchlist(full_watchlist,
                                   "meteora: simpan baseline metrik",
                                   background=True)
                metric_deliveries = send_metric_alerts(
                    metric_result.get("events"),
                    mute_mints=mutes_for(lp_watch))
            except Exception as exc:  # noqa: BLE001 - holder scan tetap tampil
                st.warning(f"Snapshot metrik Meteora gagal: {exc}")
            published = None
            if fresh:
                ingest_many(fresh, store=history_store, detail=False)
            if fresh or metric_result.get("metrics"):
                published = publish_holder_status(
                    fresh, watchlist, push=False,
                    history_store=history_store,
                    merge_status=holder_status,
                    meteora_metrics=metric_result.get("metrics") or {})
            st.session_state["lp_scan_report"] = {
                "total": total, "updated": len(fresh), "failed": len(failed),
                "short": len(skipped_short),
                "metric_alerts": len(metric_result.get("events") or []),
                "metric_sent": sum(1 for item in metric_deliveries
                                    if (item.get("delivery") or {}).get("ok")),
                "snapshot_ts": ((published or holder_status).get("updated_at")),
            }
            st.session_state["status_force_refresh"] = True
            st.rerun()

        _lp_report = st.session_state.pop("lp_scan_report", None)
        if isinstance(_lp_report, dict):
            bits = [f"{_lp_report.get('updated') or 0} token Watchlist "
                    "Meteora diperbarui"]
            if _lp_report.get("failed"):
                bits.append(f"{_lp_report['failed']} gagal")
            if _lp_report.get("short"):
                bits.append(f"{_lp_report['short']} scan holder tidak lengkap "
                            "dilewati")
            if _lp_report.get("metric_alerts"):
                bits.append(f"{_lp_report['metric_alerts']} deteksi metrik baru")
            if _lp_report.get("metric_sent"):
                bits.append(f"{_lp_report['metric_sent']} notif metrik dikirim")
            st.info("Scan sekarang selesai: " + " · ".join(bits) + ".",
                    icon="✅")
        _render_toggle_note("lp")

        if not rows:
            st.info("Watchlist Meteora masih kosong. Tambahkan token dari "
                    "**⭐ Scan Meteora Pool** di halaman temp (📦) atau "
                    "tempel CA di form atas.")
            return

        header = st.columns([1.42, 0.7, 0.78, 0.72, 0.62, 0.8, 0.78,
                              0.35, 0.35, 0.35, 0.35])
        style = "font-size:0.68rem;color:#000000;font-weight:700;"
        titles = ["Token", "Sumber", "Fee/ATVL", "Volatility", "Dust",
                  "Hold %MC", "Δ rasio", "", "", "", ""]
        for col, title in zip(header, titles):
            align = "" if title == "Token" else "text-align:center;"
            col.markdown(f'<div style="{style}{align}">{title}</div>',
                         unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)
        for row in rows:
            _render_lp_row(row)


# ---------------------------------------------------------------------------
# Scan Holder Solana / Robinhood — satu token (2026-09-10, dulu "Scan Holder
# Khusus — Helius / Robinhood"). Detail karakteristik section pindah ke
# tooltip judul (hanya muncul saat kursor digeser ke teksnya), bukan caption.
# ---------------------------------------------------------------------------
SCAN_HOLDER_TITLE = "🛰 Scan Holder Solana / Robinhood"


def scan_holder_tooltip() -> str:
    """Detail karakteristik section — teks tooltip judul (bukan caption).

    Konvensi 2026-09-10: angka ambang **selalu** dibaca dari konstanta rule
    (di sini ``meteora_screener.BEST_DUST_MARK_PCT``, sumber tanda 🏆 BEST
    POOL) supaya tooltip tidak pernah beda dari yang benar-benar jalan;
    impornya di dalam fungsi seperti ``best_pool_ui.best_pool_tooltip``.
    Atribut ``title`` browser tidak mengenal markdown.
    """
    from meteora_screener import BEST_DUST_MARK_PCT
    return (
        "Tempel contract address (CA) satu token untuk mengambil seluruh "
        "daftar holder: Solana (base58) langsung dari Helius DAS "
        "(getTokenAccounts), Robinhood Chain (0x…) dari Blockscout (CSV "
        "export tanpa limit) — lalu menampilkan bar chart distribusi holder "
        "per range nilai USD (Wallet Depth by Threshold). Default: LP/pool "
        "AMM disingkirkan dari bucket. Metrik Dust %MC (kiri Akun holder) "
        "memakai definisi kolom Hold %MC watchlist: wallet 0 < nilai ≤ $10, "
        "bukan LP/pool. Semua persen %MC di section ini 3 desimal, termasuk "
        "label di grafik. Bila Dust %MC <= "
        f"{BEST_DUST_MARK_PCT:g}% marketcap (inklusif), di bawah metriknya "
        "muncul tulisan emas berkelap-kelip BEST — penanda visual saja "
        "(ambang yang sama dengan tanda 🏆 BEST POOL di card Scan Best Pool "
        "Meteora), bukan saringan; dust yang gagal diambil tidak pernah "
        "ditandai.")



def _scan_source_meta(result: dict) -> tuple[str, str, str]:
    """``(label metrik, help metrik, label caption)`` dari sumber holder.

    ``result["source"]`` berasal dari ``helius_holders.scan_token_holders``
    (``"helius"``) atau ``robinhood_holders.scan_token_holders``
    (``"blockscout-csv"`` / ``"blockscout-rpc"`` / ``"blockscout-v2"`` —
    ketiganya Blockscout, hanya beda jalur pengambilan; akhiran ``@pro`` /
    ``@public`` (sejak 2026-09-08) menandai transport: PRO API ber-key
    atau instance publik).
    """
    source = str(result.get("source") or "").lower()
    if "blockscout" in source or source in ("", "robinhood"):
        jalur = {"blockscout-csv": "CSV export",
                 "blockscout-v2": "REST v2",
                 "blockscout-rpc": "RPC"}.get(
                     robinhood_holders.source_base(source), "")
        detail = f" via {jalur}" if jalur else ""
        route = robinhood_holders.route_label(source)
        key_label = str((result.get("snapshot") or {}).get("pro_key") or "")
        if route and key_label:
            route = f"{route} {key_label}"
        transport = f" · {route}" if route else ""
        return ("Blockscout",
                f"Akun token yang diambil dari Blockscout{detail}{transport} "
                "(Robinhood Chain).",
                f"🦅 Blockscout (Robinhood Chain){transport}")
    return ("Helius",
            "Akun token yang diambil dari Helius DAS getTokenAccounts.",
            "🛰 Helius DAS getTokenAccounts")


def _render_helius_holder_scan() -> None:
    """Section: input CA satu token → scan holder (Solana via Helius,
    Robinhood Chain via Blockscout) + bar chart."""
    st.divider()
    st.markdown(hover_title_html(SCAN_HOLDER_TITLE, scan_holder_tooltip()),
                unsafe_allow_html=True)

    with st.form("helius-holder-form"):
        col_ca, col_max, col_pool, col_btn = st.columns([3, 1, 2, 1])
        ca_input = col_ca.text_input(
            "Contract address (CA)", key="helius-ca-input",
            placeholder="So1111… (Solana) atau 0x… (Robinhood Chain)")
        max_wallets = col_max.number_input(
            "Maks holder", min_value=1000, max_value=100_000,
            value=100_000, step=1_000,
            help=("FULL (default): untuk Solana, urutan getTokenAccounts "
                  "Helius tidak urut saldo, jadi cap kecil = sampel acak "
                  "yang bias — dust (≤$10) bisa kurang terhitung dan "
                  "angkanya tidak sinkron dengan cron/Telegram. Turunkan "
                  "hanya bila quota ketat."))
        include_pools = col_pool.checkbox(
            "Sertakan LP/pool di bucket", value=False,
            help="Default OFF: pool/AMM disingkirkan dari list/bucket holder.")
        run = col_btn.form_submit_button("🛰 Scan Holder", type="primary")

    if run:
        ca = str(ca_input or "").strip()
        is_evm = robinhood_holders.is_robinhood_address(ca)
        if not ca:
            st.warning("Masukkan contract address terlebih dahulu.")
        elif not (SOLANA_CA_RE.match(ca) or is_evm):
            st.warning("Format CA tidak valid. Solana: base58 sepanjang "
                       "32–44 karakter · Robinhood Chain: 0x + 40 hex.")
        else:
            if is_evm:
                ca = robinhood_holders.normalize_address(ca)
                scan_fn = robinhood_holders.scan_token_holders
                status_label = "Mengambil holder dari Blockscout " \
                               "(Robinhood Chain)…"
            else:
                scan_fn = scan_token_holders
                status_label = "Mengambil holder dari Helius…"
            with st.status(status_label, expanded=False) as box:
                try:
                    result = scan_fn(
                        ca, max_wallets=int(max_wallets),
                        include_pools=bool(include_pools))
                except Exception as exc:  # noqa: BLE001
                    result = None
                    box.write(f"Gagal: {exc}")
            if result is None:
                st.error("Terjadi kesalahan saat scan holder.")
            else:
                result["mint"] = ca
                st.session_state["helius_holder_result"] = result

    result = st.session_state.get("helius_holder_result")
    if result and result.get("mint"):
        _render_helius_holder_result(result)


def _render_helius_holder_result(result: dict) -> None:
    """Tampilkan metrik + bar chart + tabel depth hasil scan holder
    (Solana/Helius atau Robinhood Chain — shape dict sama)."""
    mint = result.get("mint") or ""
    market = result.get("market") or {}
    snapshot = result.get("snapshot") or {}
    depth = result.get("depth") or {}
    symbol = str(result.get("symbol") or market.get("symbol") or "?").upper()
    fetched = int(snapshot.get("fetched") or 0)
    truncated = bool(snapshot.get("truncated"))
    holders_all = int(depth.get("holders_all") or 0)
    holders_wallet = int(depth.get("holders_wallet") or 0)
    mc = float(market.get("marketcap") or depth.get("market_cap") or 0)
    source_short, source_help, source_label = _scan_source_meta(result)

    st.markdown(f"**${html.escape(symbol)}** — `{html.escape(mint)}`")
    st.markdown(external_links_html(mint), unsafe_allow_html=True)

    if result.get("no_helius_keys"):
        st.error("Belum ada Helius API key. Isi `helius_api_key` di "
                 "config.json / env `HELIUS_API_KEY` / Streamlit secrets.")
        return
    if result.get("scan_failed"):
        snapshot_err = result.get("snapshot") or {}
        detail = str(snapshot_err.get("error") or "").strip()
        if snapshot_err.get("blocked"):
            # 403 bot-protection Blockscout publik: CA & harga tidak
            # salah. Tanpa key → suruh pasang key; key sudah ada → semua
            # key ditolak/kreditnya habis, arahkan ke dashboard.
            n_keys = int(snapshot_err.get("pro_keys") or 0)
            if n_keys:
                remedy = (f"{n_keys} key PRO API terpasang tetapi semuanya "
                          "ditolak / kredit hariannya habis — cek dashboard "
                          f"{robinhood_holders.BLOCKSCOUT_KEY_URL} "
                          "(`x-credits-remaining`) atau tambah key dari akun "
                          "lain ke `BLOCKSCOUT_API_KEYS`.")
            else:
                remedy = ("Pasang `BLOCKSCOUT_API_KEY` (key gratis: "
                          f"{robinhood_holders.BLOCKSCOUT_KEY_URL}; env / "
                          "`blockscout_api_key` di config.json / Streamlit "
                          "secrets; beberapa key dipisah koma di "
                          "`BLOCKSCOUT_API_KEYS`) supaya scan lewat PRO API.")
            st.error(
                "Blockscout publik menolak request scan (HTTP 403 "
                "bot-protection) — bukan karena CA salah. " + remedy
                + (f" Detail: {detail}" if detail else ""))
            return
        message = ("Scan tidak menghasilkan holder. Pastikan CA valid dan "
                   "harga token tersedia (DexScreener)"
                   + (" serta Helius API key aktif"
                      if source_short == "Helius" else "")
                   + ".")
        if detail:
            message += f" Detail: {detail}"
        st.error(message)
        return

    prefix = "≥" if truncated else ""
    buckets_with_pools = bool(depth.get("buckets_include_pools", True))
    pool_n = int(depth.get("pool_excluded") or 0)
    bucket_n = holders_all if buckets_with_pools else holders_wallet
    # Metrik detail **Dust %MC** di kiri "Akun holder" (permintaan user
    # 2026-09-12) — definisi persis kolom Hold %MC watchlist (dihitung
    # classify_holders di dalam scan_token_holders dan ditempel ke depth),
    # tampil 3 desimal seperti watchlist/grafik.
    dust_pct = depth.get("dust_pct_mc")
    dust_count = depth.get("dust_count")
    dust_value = depth.get("dust_value_usd")
    c0, c1, c2, c3, c4 = st.columns(5)
    c0.metric(
        "Dust %MC",
        "—" if dust_pct is None else f"{float(dust_pct):.3f}%",
        help=("Wallet dust: 0 < nilai ≤ "
              f"${float(depth.get('dust_limit_usd') or 10.0):.0f} per "
              "akun (bukan LP/pool) — "
              f"{prefix}{int(dust_count or 0):,} wallet, total "
              f"{_compact(dust_value)}. Persentase terhadap marketcap; "
              "angka ini sesuai kolom «Hold %MC» di card watchlist."))
    # Tulisan **BEST** emas berkelap-kelip (2026-09-12, permintaan user:
    # "jika kondisi %dust <= 0.035 kasih tulisan BEST yang agak besar, dengan
    # efek kelap kelip, warnanya GOLD") — persis di bawah metrik Dust %MC,
    # jadi tandanya menempel pada angka yang menjadi buktinya. Ambangnya satu
    # sumber dengan tanda 🏆 BEST POOL card Scan Best Pool Meteora
    # (``meteora_screener.BEST_DUST_MARK_PCT``); HTML/CSS-nya dibuat
    # ``dashboard_components._scan_best_badge_html`` (kosong bila tidak
    # memenuhi syarat → tidak ada elemen yang dirender).
    best_html = _scan_best_badge_html(dust_pct)
    if best_html:
        c0.markdown(best_html, unsafe_allow_html=True)
    c1.metric(f"Akun holder ({source_short})", f"{prefix}{fetched:,}",
              help=source_help)
    c2.metric(
        f"Bucket > $0 ({'semua akun' if buckets_with_pools else 'tanpa pool'})",
        f"{bucket_n:,}",
        help=("Semua akun bernilai > $0 termasuk LP/pool."
              if buckets_with_pools else
              f"Hanya wallet murni — {pool_n:,} akun LP/pool "
              "disingkirkan dari bucket."))
    c3.metric("Wallet murni (tier)", f"{holders_wallet:,}",
              help="Akun non-LP/pool yang dipakai hitungan tier.")
    c4.metric("Marketcap", _compact(mc) if mc else "—",
              help="Marketcap dari DexScreener.")

    fig = depth_bar_chart(
        depth, title=f"Distribusi holder ${symbol} per range nilai (USD)")
    if fig is not None:
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)
    else:
        st.info("Belum ada bucket holder untuk ditampilkan.")

    st.markdown(_depth_tables_html(depth), unsafe_allow_html=True)
    pages = int(snapshot.get("pages") or 0)
    pool_note = ("" if buckets_with_pools or not pool_n
                 else f" · 🚫 {pool_n:,} akun LP/pool disingkirkan dari bucket")
    st.caption(
        f"Sumber holder: {source_label} · "
        f"{prefix}{fetched:,} akun dianalisis · {pages} halaman{pool_note} · "
        "nilai USD = balance × harga token (DexScreener)."
    )




# ---------------------------------------------------------------------------
# Watchlist Robinhood Chain (EVM, chain id 4663) — dua card sejak 2026-09-05:
# **Robinhood LP** (scan cepat ±5 menit sejak 2026-09-06) dan **Robinhood
# biasa** (scan manual). Notifikasinya satu untuk semua lane: ⚡ EARLY DUMP
# TERJADI - GANTI WIDE RANGE tiap dust naik ≥ 0,02% MC dari angka saat token
# masuk watchlist (2026-09-13; rule ambang 0,06% MC sudah diganti). Sejak
# 2026-09-06 KEDUA card LP (Chart LP
# Meteora + Robinhood LP) ikut di-scan tiap run = ±5 menit; tinggal watchlist
# biasa yang hanya jalan lewat tombol scan (LP_SCAN_RUN_MULTIPLIER tersedia
# kalau kuota Helius perlu dihemat).
# ---------------------------------------------------------------------------
# Shared stores; moving sections does not change watchlist sources or cron.
data = load_dashboard_data()
watchlist, holder_status, history_store = data.watchlist, data.status, data.history
status_tokens = holder_status.get("tokens") or {}
lp_watch, _ = split_watchlist(watchlist)

# ---------------------------------------------------------------------------
# Grid 2 kolom watchlist (2026-09-10): **kiri** 🌊 Watchlist Meteora,
# **kanan** 🦅 Watchlist Robinhood (LP).
# 🏆 Scan Best Pool Meteora **keluar dari grid** — permintaan user
# 2026-09-11: "jangan dibuat grid lagi" → full-width di bawah grid (posisi
# seperti sebelum grid 2 kolom 2026-09-10). 🦅 Scan Best Robinhood Coin
# diparkir di halaman temp (📦) 2026-09-11 ("belum berfungsi"). Scan Holder
# tetap full-width di bawah (form + chart-nya lebar). Di layar sempit
# Streamlit otomatis menumpuk kolomnya.
# ---------------------------------------------------------------------------
rh_lp_watch, _ = split_robinhood_watchlist(data.rh_watchlist)
_lp_col, _rh_col = st.columns([1, 1], gap="medium")
with _lp_col:
    _render_lp_card(lp_watch, status_tokens, history_store)
with _rh_col:
    _render_rh_card(rh_lp_watch, data.rh_status.get("tokens") or {},
                    data.rh_history,
                    int(datetime.now(timezone.utc).timestamp()), variant="lp",
                    merge_status=data.rh_status)

# 🏆 Scan Best Pool Meteora — full-width, **tidak** di dalam grid 2 kolom
# (permintaan user 2026-09-11: "jangan dibuat grid lagi"). Listing API
# Meteora 24 jam ``pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000``
# (kriteria 2026-09-11); saringan layar: dust holder < 0,05% MC +
# volatility >= 2%. Urut: kenaikan volume 24 jam terbesar → dust terkecil →
# fee/active TVL terbesar. ⭐ memasukkan token ke card Watchlist
# Meteora di atas.
st.divider()
render_best_pool_scan()

st.divider()
_render_helius_holder_scan()

# ---------------------------------------------------------------------------
# 🧾 Log Aktivitas (2026-09-10, paling bawah) — kejadian penting semua card:
# scan mulai/selesai (Meteora/Best Pool/Best Robinhood/Scan Holder), rate
# limit & parkir key PRO Blockscout, fallback instance publik, 403
# bot-protection, sync watchlist GitHub gagal. Merah bold = perlu perubahan
# manual user (pasang/ganti API key, kredit habis). Kepala panel menampilkan
# status pool key PRO (`pro_key_summary`) — jawaban langsung "kena limit di
# key mana".
# ---------------------------------------------------------------------------
st.divider()
activity_log.render_activity_log()
