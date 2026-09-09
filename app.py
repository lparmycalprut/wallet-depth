# -*- coding: utf-8 -*-
"""Wallet Depth — analisa holder (dust % MC) + Scan Meteora."""
from __future__ import annotations

from datetime import datetime, timezone
import html

import matplotlib.pyplot as plt
import streamlit as st

from helius_holders import depth_bar_chart, scan_token_holders
from holder_history import (DUST_BEST_MIN_TVL_USD,
                            DUST_BEST_PCT, DUST_CAUTION_PCT,
                            DUST_DANGER_PCT, DUST_SCAN_HIDE_PCT, FULL_SCAN_MAX_WALLETS,
                            holders_usable, ingest_many,
                            usable_points)
from links import (external_links_html, holder_analytic_link_html,
                   pool_links_html)
from lp_watchlist import (LP_SOURCE, lp_card_rows, lp_chart_figure,
                          lp_summary, split_watchlist)
from meteora_screener import row_flag, scan_meteora, sort_rows
import page_router
from dashboard_components import (_ca_error, _compact, _dust_badge_html, _dust_best_html,
                                  _number, _render_alert_note, _render_depth,
                                  _render_rh_card, _store_alert_note, _wib,
                                  _depth_tables_html, ALERT_NOTE_KEY,
                                  SOLANA_CA_RE, load_dashboard_data,
                                  render_styles)
from telegram_alerts import process_holder_alerts
import robinhood_holders
from robinhood_watchlist import (split_robinhood_watchlist)
from holder_analysis import analyze_token
from holder_status import (load_holder_status, publish_holder_status)
from watchlist import (add_to_watchlist, remove_from_watchlist, set_watchlist_source)

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


_autorefresh_col = st.columns([0.30, 0.70])
_autorefresh_col[0].toggle(
    "🔄 Auto-refresh ±60 dtk",
    value=st.session_state.get("autorefresh_on", True),
    key="autorefresh_on",
    help="Lempar ulang halaman otomatis saat snapshot cron baru "
         "muncul (±60 dtk sekali cek). OFF = halaman hanya "
         "terupdate saat ada interaksi manual.")
_autorefresh_col[1].markdown(
    '<div style="font-size:.72rem;color:#64748b;align-self:center;">'
    "Data baris = snapshot cron (±5 menit); saat ada snapshot baru, "
    "halaman menyegarkan sendiri angkanya.</div>",
    unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Chart LP — watchlist terpisah untuk token dari Scan Meteora Pool
# ---------------------------------------------------------------------------
LP_CARD_TITLE = "🌊 Chart LP — Watchlist Meteora"
LP_ADD_FORM = "lp-add-token"


def _card_head_html(title: str, pills: list[str] | None = None) -> str:
    """Header card grid: judul tebal + pill ringkasan di sebelahnya.

    Dipakai card **Chart LP** (kolom kiri) dan **Scan Meteora Pool** (kolom
    kanan) supaya dua card yang sejajar itu berkepala sama.
    """
    chips = "".join(pills or [])
    return (f'<div class="lp-head"><span class="lp-title">{title}'
            f"</span>{chips}</div>")


def _lp_head_html(summary: dict) -> str:
    """Header card Chart LP: jumlah token + rekap level dust."""
    pills = [f'<span class="lp-count">{summary.get("total", 0)} token</span>']
    if summary.get("danger"):
        pills.append(f'<span class="lp-warn">BAHAYA {summary["danger"]}</span>')
    if summary.get("caution"):
        pills.append(f'<span class="lp-warn" style="color:#78350f;'
                     f'background:#fef3c7;">HATI-HATI {summary["caution"]}'
                     '</span>')
    if summary.get("rising"):
        pills.append(f'<span class="lp-count">dust naik {summary["rising"]}'
                     '</span>')
    return _card_head_html(LP_CARD_TITLE, pills)


def _render_lp_row(row: dict) -> None:
    """Satu baris token Chart LP + grafik perubahan dust holder."""
    mint = row.get("mint") or ""
    symbol = row.get("symbol") or "?"
    holders = row.get("holders") or {}
    flag = row.get("flag") or {}
    dust_pct = row.get("dust_pct")
    dust_count = row.get("dust_count")
    # ``truncated`` mengikuti **sumber angka yang benar-benar ditampilkan**
    # (snapshot ATAU titik history terbaru — lihat build_lp_row), bukan
    # selalu snapshot.
    truncated = bool(row.get("used_truncated",
                             holders.get("truncated")))
    dust_txt = ("—" if dust_count is None
                else (f"≥{int(dust_count)}" if truncated
                      else f"{int(dust_count):,}"))
    pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.2f}%"
    # Titik dari scan yang datanya tidak lengkap tidak digambar (lihat
    # holder_history.point_usable) — kalau tidak, grafik menukik ke 0%.
    chart_points = usable_points(row.get("points") or [])

    short_note = (" · ⚠️ scan terakhir tidak lengkap"
                  if row.get("degraded") else "")
    if row.get("drift"):
        short_note += " · ⚠️ snapshot ≠ history"
    if row.get("truncation_swap"):
        short_note += " · ⚠️ memakai scan lengkap sebelumnya"
    # Waktu ANGKA yang ditampilkan (used_ts), bukan selalu waktu snapshot —
    # dulu label selalu menampilkan analyzed_at snapshot, sehingga label
    # bisa menunjukkan jam yang beda dari angka yang tampil.
    scan_ts = row.get("used_ts") or row.get("analyzed_at")
    cols = st.columns([1.7, 0.75, 0.95, 0.42, 0.42, 0.42])
    cols[0].markdown(
        f'<div class="watchlist-token">'
        f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
        f'<span class="watchlist-mint">{html.escape(mint[:8])}…</span>'
        f'<span class="watchlist-metric-sub">MC {_compact(row.get("mc"))} · '
        f'scan {_wib(scan_ts)}{short_note}</span>'
        f'<div class="watchlist-links">{external_links_html(mint)}</div>'
        f"</div>", unsafe_allow_html=True)
    cols[1].markdown(
        f'<div class="watchlist-metric">'
        f'<div class="watchlist-metric-value">{dust_txt}</div>'
        f'<div class="watchlist-metric-sub">wallet dust</div></div>',
        unsafe_allow_html=True)
    cols[2].markdown(
        f'<div class="watchlist-metric">'
        f'<div class="watchlist-metric-value">{pct_txt}</div>'
        f'{_dust_badge_html(flag)}</div>', unsafe_allow_html=True)
    cols[3].markdown(holder_analytic_link_html(mint),
                     unsafe_allow_html=True)
    if cols[4].button("📋", key=f"lp-move-{mint}",
                      help="Pindahkan ke Watchlist Holder",
                      use_container_width=True):
        set_watchlist_source(mint, "manual", background=True)
        st.rerun()
    if cols[5].button("✕", key=f"lp-remove-{mint}",
                      help="Hapus dari Chart LP", use_container_width=True):
        remove_from_watchlist(mint, background=True)
        st.rerun()

    with st.expander(f"📈 Grafik perubahan dust holder — ${symbol}",
                     expanded=False):
        figure = lp_chart_figure(chart_points, symbol)
        if figure is None:
            st.info("Butuh minimal 2 titik bucket 5 menit. Cron watchlist LP "
                    "(tiap ±5 menit) atau tombol **Scan sekarang** di card "
                    "ini akan mengisinya.")
        else:
            st.pyplot(figure, use_container_width=True)
            plt.close(figure)
        st.caption(
            f"Garis = dust % marketcap · batang = jumlah wallet dust · "
            f"ambang HATI-HATI {DUST_CAUTION_PCT:g}% / BAHAYA "
            f"{DUST_DANGER_PCT:g}% · titik per 5 menit "
            f"({len(row.get('sampled') or [])} bucket).")
        if isinstance(holders.get("depth"), dict):
            _render_depth(holders, symbol)
    st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)


def _render_lp_card(lp_watch: dict, status_tokens: dict,
                    history_store: dict) -> None:
    """Card kolom kiri grid: watchlist Meteora + grafik perubahan dust."""
    rows = lp_card_rows(lp_watch, status_tokens, history_store)
    summary = lp_summary(rows)
    with st.container(border=True):
        st.markdown(_lp_head_html(summary), unsafe_allow_html=True)
        st.caption(
            "Watchlist terpisah untuk token yang ditambahkan dari **Scan "
            "Meteora Pool** (⭐) atau ditambah manual ke card ini. Di-scan "
            "cron **tiap ±5 menit** supaya exit LP lebih awal dan perubahan "
            "holder langsung kelihatan: selama "
            f"hold % MC dust di atas **{DUST_BEST_PCT:g}%**, alert ⚡ "
            "Telegram dikirim **berulang tiap scan** — berhenti bila token "
            "dihapus (✕) atau dipindah ke watchlist biasa (📋). Grafik "
            "menampilkan **perubahan dust holder** per bucket 5 menit: "
            f"≥ {DUST_CAUTION_PCT:g}% MC = HATI-HATI, "
            f"≥ {DUST_DANGER_PCT:g}% MC = BAHAYA.")

        with st.expander("➕ Tambah CA manual ke Chart LP",
                         expanded=not rows):
            with st.form(LP_ADD_FORM, clear_on_submit=True):
                lp_ca = st.text_input(
                    "Contract address", key="lp-ca-input",
                    help="Symbol diambil otomatis dari DexScreener")
                if st.form_submit_button("🌊 Tambah ke Chart LP"):
                    ca = str(lp_ca or "").strip()
                    ca_error = _ca_error(ca)
                    if ca_error:
                        st.warning(ca_error)
                    else:
                        add_to_watchlist(ca, "?", source=LP_SOURCE,
                                         background=True)
                        st.success(f"{ca[:8]}… masuk Chart LP.")
                        st.rerun()

        if st.button("🔄 Scan sekarang Chart LP", type="primary",
                     key="lp-scan-now", use_container_width=True):
            analyses = {}
            total = len(lp_watch or {})
            bar = st.progress(0.0, text=f"Scan Chart LP 0/{total}…")
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
                             text=f"Scan Chart LP {done}/{total} · "
                                  f"{str((meta or {}).get('symbol') or '?')}")
            bar.empty()
            ok = {mint: item for mint, item in analyses.items()
                  if isinstance(item, dict)}
            fresh = {mint: item for mint, item in ok.items()
                     if holders_usable(item.get("holders"))}
            skipped_short = sorted(set(ok) - set(fresh))
            failed = sorted(mint for mint, item in analyses.items()
                            if not isinstance(item, dict))
            published = None
            if fresh:
                # Alert ikut dievaluasi + dikirim dari scan manual (permintaan
                # user 2026-09-09), bukan hanya dari cron. HARUS sebelum
                # ingest_many: rule membaca anchor lama, lalu state hasil
                # evaluasi (sent_event_ids/last_sent/marker episode) ikut
                # tertulis saat ingest_many menyimpan store — pola yang sama
                # dengan cron scripts/scan_holders.py. volume_rules=False:
                # hanya rule lane LP (⚡ EARLY DUMP + eskalasi EXIT), anchor
                # 4 jam / peta wallet cron tidak digeser scan ad-hoc.
                _store_alert_note(process_holder_alerts(
                    fresh, history_store, lp_mints=set(lp_watch),
                    high_mints=set(), watchlist_meta=lp_watch,
                    volume_rules=False), f"{ALERT_NOTE_KEY}lp")
                ingest_many(fresh, store=history_store, detail=False)
                published = publish_holder_status(
                    fresh, watchlist, push=False,
                    history_store=history_store,
                    merge_status=holder_status)
            st.session_state["lp_scan_report"] = {
                "total": total, "updated": len(fresh), "failed": len(failed),
                "short": len(skipped_short),
                "snapshot_ts": ((published or holder_status).get("updated_at")),
            }
            st.session_state["status_force_refresh"] = True
            st.rerun()

        _lp_report = st.session_state.pop("lp_scan_report", None)
        if isinstance(_lp_report, dict):
            bits = [f"{_lp_report.get('updated') or 0} token Chart LP "
                    "diperbarui"]
            if _lp_report.get("failed"):
                bits.append(f"{_lp_report['failed']} gagal")
            if _lp_report.get("short"):
                bits.append(f"{_lp_report['short']} scan tidak lengkap "
                            "dilewati")
            st.info("Scan sekarang selesai: " + " · ".join(bits) + ".",
                    icon="✅")
        _render_alert_note(f"{ALERT_NOTE_KEY}lp")

        if not rows:
            st.info("Chart LP masih kosong. Tambahkan token dari **⭐ Scan "
                    "Meteora Pool** di kolom kanan atau tempel CA di form "
                    "atas.")
            return

        header = st.columns([1.7, 0.75, 0.95, 0.42, 0.42, 0.42])
        style = "font-size:0.72rem;color:#000000;font-weight:700;"
        titles = ["Token", "Dust", "Hold %MC", "", "", ""]
        for col, title in zip(header, titles):
            align = "" if title == "Token" else "text-align:center;"
            col.markdown(f'<div style="{style}{align}">{title}</div>',
                         unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)
        for row in rows:
            _render_lp_row(row)


# ---------------------------------------------------------------------------
# Scan Holder Khusus — Helius / Robinhood (satu token)
# ---------------------------------------------------------------------------
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
    st.subheader("🛰 Scan Holder Khusus — Helius / Robinhood")
    st.caption(
        "Tempel **contract address (CA)** satu token untuk mengambil seluruh "
        "daftar holder: Solana (base58) langsung dari **Helius DAS** "
        "(getTokenAccounts), **Robinhood Chain** (`0x…`) dari **Blockscout** "
        "(CSV export tanpa limit) — lalu menampilkan **bar chart distribusi "
        "holder** per range nilai USD (Wallet Depth by Threshold). "
        "**Default: LP/pool AMM disingkirkan dari bucket.**"
    )

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
    c1, c2, c3, c4 = st.columns(4)
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


METEORA_CARD_TITLE = "🌊 Scan Meteora Pool"


def _meteora_head_html(rows: list, hidden: int, best_count: int) -> str:
    """Header card Scan Meteora: jumlah pool + rekap BEST / disembunyikan."""
    pills = [f'<span class="lp-count">{len(rows)} pool</span>']
    if best_count:
        pills.append('<span class="lp-count" style="color:#3b2f0a;'
                     'background:#fde047;border:1px solid #facc15;">'
                     f'🏆 {best_count} BEST</span>')
    if hidden:
        pills.append('<span class="lp-count" style="color:#334155;'
                     f'background:#e2e8f0;">{hidden} disembunyikan</span>')
    return _card_head_html(METEORA_CARD_TITLE, pills)


def _render_meteora_scan() -> None:
    """Scan pool Meteora DLMM 24h ∩ 1h + holder dust (card kolom kanan)."""
    with st.container(border=True):
        # Kepala card butuh angka hasil scan terakhir, jadi hasil disimpan /
        # dibaca lebih dulu — pill ringkasan dan listing di bawahnya selalu
        # satu sumber data (selesai scan → ``st.rerun()`` seperti card LP).
        if st.button("🌊 Scan Meteora + Holder", type="primary",
                     key="meteora-scan-now", use_container_width=True):
            bar = st.progress(0.0, text="Listing pool Meteora…")

            def _progress(index, total, label):
                bar.progress(index / max(total, 1),
                             text=f"Holder {index}/{total} · {label}")

            try:
                # FULL: filter dust > 0,1% MC di listing butuh dust akurat;
                # cap 2000 dulu = sampel bias (urutan Helius tidak urut
                # saldo).
                result = scan_meteora(max_wallets=FULL_SCAN_MAX_WALLETS,
                                      workers=6, progress=_progress)
            except Exception as exc:  # noqa: BLE001
                result = {"rows": [], "error": str(exc), "hidden_dust": 0,
                          "fetched": 0}
            finally:
                bar.empty()
            st.session_state["meteora_scan"] = result
            st.rerun()

        result = st.session_state.get("meteora_scan") or {}
        error = result.get("error") or ""
        # BEST POOL selalu di atas. scan_meteora() sudah mengurutkan, tapi
        # hasil lama yang tersimpan di session_state (sebelum fitur ini)
        # belum — urutkan lagi di sini supaya listing konsisten tanpa perlu
        # scan ulang.
        rows = sort_rows(result.get("rows") or [])
        hidden = int(result.get("hidden_dust") or 0)
        fetched = int(result.get("fetched") or 0)
        best_count = sum(1 for row in rows if row_flag(row).get("best"))

        st.markdown(_meteora_head_html(rows, hidden, best_count),
                    unsafe_allow_html=True)
        st.caption(
            "Top DLMM 24 jam (`active_tvl ≥ 1000`, "
            "`fee_active_tvl_ratio ≥ 250`) dibandingkan 1 jam "
            "(`fee_active_tvl_ratio ≥ 1`). Pool 24 jam yang masih muncul di "
            "1 jam **tetap ditampilkan**. Hanya pool dengan dust holder "
            f"**≤ {DUST_SCAN_HIDE_PCT:g}% MC** yang ditampilkan — sisanya "
            "disembunyikan (badge AMAN/HATI-HATI/BAHAYA tidak dipakai di "
            f"sini). Dust **< {DUST_BEST_PCT:g}% MC** + data holder valid "
            f"(≥ 40 wallet) + **TVL ≥ ${DUST_BEST_MIN_TVL_USD / 1000:g}K** "
            "diberi badge 🏆 BEST POOL — **BEST POOL diurutkan paling atas**,"
            " lalu dust % MC terkecil dan TVL terbesar. ⭐ memasukkan token "
            "ke card **Chart LP** di kolom kiri. Tombol kanan: Meteora + "
            "HawkFi."
        )
        if error:
            st.warning(f"Meteora API: {error}")
        if fetched:
            best_txt = (f" · 🏆 {best_count} BEST POOL di urutan teratas"
                        if best_count else "")
            st.caption(f"{len(rows)} pool ditampilkan · {hidden} "
                       f"disembunyikan (dust > {DUST_SCAN_HIDE_PCT:g}% MC) · "
                       f"listing {fetched}{best_txt}.")
        if not rows:
            if result:
                st.info("Tidak ada pool yang lolos filter dust (atau "
                        "listing kosong).")
            return

        col_spec = [1.6, 0.8, 0.8, 0.7, 0.9, 0.7, 1.2, 0.45]
        header_cols = st.columns(col_spec)
        titles = ["Token", "MC", "TVL", "Dust", "Dust %MC", "TF", "Pool", ""]
        style = ("font-size:0.72rem;color:#000000;font-weight:700;"
                 "text-align:center;")
        for col, title in zip(header_cols, titles):
            col.markdown(f'<div style="{style}">{title}</div>',
                         unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)

        for index, row in enumerate(rows):
            ca = str(row.get("ca") or "")
            symbol = str(row.get("symbol") or "?").upper()
            pool = str(row.get("pool_address") or "")
            dust_count = row.get("dust_count")
            dust_pct = row.get("dust_pct_mc")
            tvl = row.get("tvl")
            # BEST POOL butuh bukti data holder valid (bukan cuma angka) +
            # TVL pool ≥ 10K: guard ada di dust_flag(holders=…, tvl=…),
            # lihat holder_history._holders_valid_for_best /
            # _tvl_valid_for_best.
            flag = row_flag(row)
            tf = []
            if row.get("in_24h"):
                tf.append("24H")
            if row.get("in_1h"):
                tf.append("1H")
            tf_txt = "+".join(tf) or "—"
            cols = st.columns(col_spec)
            cols[0].markdown(
                f'<div class="watchlist-token">'
                f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
                f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
                f'<div class="watchlist-links">{external_links_html(ca)}</div>'
                f"</div>", unsafe_allow_html=True)
            cols[1].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{_compact(row.get("mc"))}</div></div>',
                unsafe_allow_html=True)
            tvl_txt = "—" if tvl is None else _compact(tvl)
            cols[2].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{tvl_txt}</div><div class="watchlist-metric-sub">tvl</div>'
                '</div>', unsafe_allow_html=True)
            cols[3].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{_number(dust_count, ".0f")}</div>'
                '<div class="watchlist-metric-sub">wallet</div></div>',
                unsafe_allow_html=True)
            pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.2f}%"
            # Badge level (AMAN/HATI-HATI/BAHAYA) sengaja TIDAK dirender di
            # listing ini sejak 2026-09-07: semua baris sudah ≤ 0,1% MC,
            # jadi hanya chip 🏆 BEST POOL yang informatif.
            cols[4].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f"{pct_txt}</div>{_dust_best_html(flag)}</div>",
                unsafe_allow_html=True)
            cols[5].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f"{html.escape(tf_txt)}</div></div>", unsafe_allow_html=True)
            pool_html = pool_links_html(pool) or '<span>—</span>'
            cols[6].markdown(
                f'<div class="pool-links">{pool_html}</div>',
                unsafe_allow_html=True)
            # Key diikat ke pool/CA, bukan nomor baris: urutan listing
            # berubah (BEST POOL naik ke atas) sehingga key berbasis index
            # bisa membuat klik ⭐ menempel ke token yang berbeda setelah
            # re-render.
            star_key = f"meteora-star-{pool or ca or index}"
            if cols[7].button("⭐", key=star_key,
                              help="Tambah ke Chart LP (kolom kiri)",
                              use_container_width=True):
                if ca:
                    add_to_watchlist(ca, symbol, source=LP_SOURCE,
                                     background=True)
                    st.success(f"${symbol} masuk Chart LP")
            st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Watchlist Robinhood Chain (EVM, chain id 4663) — dua card sejak 2026-09-05:
# **Robinhood LP** (scan cepat ±5 menit sejak 2026-09-06, pengingat ⚡ > 0,1%
# MC berulang) dan **Robinhood biasa** (scan ±4 jam, rule 🔔 HIGH DROP titik
# high). Sejak 2026-09-06 KEDUA card LP (Chart LP Meteora + Robinhood LP)
# ikut di-scan tiap run = ±5 menit; tinggal watchlist biasa yang 4 jam
# (LP_SCAN_RUN_MULTIPLIER tersedia kalau kuota Helius perlu dihemat).
# ---------------------------------------------------------------------------
# Shared stores; moving sections does not change watchlist sources or cron.
data = load_dashboard_data()
watchlist, holder_status, history_store = data.watchlist, data.status, data.history
status_tokens = holder_status.get("tokens") or {}
lp_watch, _ = split_watchlist(watchlist)

# ---------------------------------------------------------------------------
# Grid 2 kolom (permintaan user 2026-09-09): **kiri** Chart LP — Watchlist
# Meteora, **kanan** Scan Meteora Pool. Dua card sejajar, bukan tumpuk
# vertikal; ⭐ di kanan memasukkan token ke card kiri. Robinhood LP dan Scan
# Holder Khusus tetap full-width di bawah (baris + chart-nya lebar). Di layar
# sempit Streamlit otomatis menumpuk kolomnya.
# ---------------------------------------------------------------------------
_lp_col, _meteora_col = st.columns([1, 1], gap="medium")
with _lp_col:
    _render_lp_card(lp_watch, status_tokens, history_store)
with _meteora_col:
    _render_meteora_scan()

st.divider()
rh_lp_watch, _ = split_robinhood_watchlist(data.rh_watchlist)
_render_rh_card(rh_lp_watch, data.rh_status.get("tokens") or {}, data.rh_history,
                int(datetime.now(timezone.utc).timestamp()), variant="lp",
                merge_status=data.rh_status)
_render_helius_holder_scan()
