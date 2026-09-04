# -*- coding: utf-8 -*-
"""Wallet Depth — analisa holder (dust % MC) + Scan Meteora."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import re

import matplotlib.pyplot as plt
import streamlit as st

from helius_holders import depth_bar_chart, scan_token_holders
from holder_history import (DUST_BEST_LABEL, DUST_BEST_PCT, DUST_CAUTION_PCT,
                            DUST_DANGER_PCT, dust_flag,
                            history_for_mint, ingest_many,
                            load_durable_holder_history, merge_points,
                            resample_4h,
                            seed_from_status, sparkline_svg)
from links import HOLDER_PAGE_PATH, external_links_html, pool_links_html
from lp_watchlist import (LP_SOURCE, lp_card_rows, lp_chart_figure,
                          lp_overlay_figure, lp_summary, split_watchlist)
from meteora_screener import scan_meteora
import pre_pump_screener
from holder_analysis import DUST_LIMIT_USD, analyze_token
from holder_status import (MANUAL_SCAN_KEY, apply_manual_scan,
                           load_holder_status, publish_holder_status)
from trending_ui import (merge_scan_rows, render_trending, run_screen,
                         run_screen_h1, run_screen_hrhr, run_screen_hrhr_h1)
from watchlist import (add_to_watchlist, get_last_push_error, load_watchlist,
                       remove_from_watchlist, set_watchlist_source)
from watchlist_detail import (SOURCE_HISTORY, change_html,
                              dust_change_since_added, format_wib,
                              previous_pct, resolve_view, sync_caption_text,
                              sync_summary)

st.set_page_config(page_title="Wallet Depth — Holder Analytic",
                   page_icon="🧮", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
.main .block-container {max-width: 1280px; padding-top: 1.5rem;}
html, body, p, span, div, label, li, td, th,
h1, h2, h3, h4, h5, h6 {color:#000000;}
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"],
[data-testid="stWidgetLabel"] p {color:#000000 !important;}
.hero {padding:1.4rem 1.6rem;border:1px solid #334155;border-radius:18px;
 background:linear-gradient(135deg,#0f172a,#172554);
 margin-bottom:1.2rem}
.hero h1, .hero p, .hero {color:#ffffff;}
.hero h1 {font-size:2rem;margin:0 0 .4rem}.hero p{color:#ffffff;margin:0}
.dust-badge {display:inline-block;padding:.28rem .58rem;border-radius:8px;
 font-size:.78rem;font-weight:800}
.dust-ok {background:#14532d;color:#dcfce7}
.dust-caution {background:#78350f;color:#fef3c7}
.dust-danger {background:#7f1d1d;color:#fee2e2}
.dust-none {background:#e2e8f0;color:#000000}
.dust-best {background:#3b2f0a;color:#fde047;border:1px solid #facc15}
.lp-head {display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;
 padding:.5rem 0 .1rem}
.lp-title {font-size:1.15rem;font-weight:800;color:#000000}
.lp-count {font-size:.75rem;font-weight:700;color:#312e81;background:#e0e7ff;
 padding:.2rem .5rem;border-radius:999px}
.lp-warn {font-size:.75rem;font-weight:700;color:#7f1d1d;background:#fee2e2;
 padding:.2rem .5rem;border-radius:999px}
.lp-delta-up {color:#b91c1c;font-weight:800}
.lp-delta-down {color:#15803d;font-weight:800}
.watchlist-row {display:flex;align-items:center;padding:.75rem 0;
 border-bottom:1px solid #cbd5e1;}
.watchlist-token {display:flex;flex-direction:column;gap:.25rem;}
.watchlist-symbol {font-size:1.1rem;font-weight:800;color:#000000;}
.watchlist-mint {font-size:.75rem;color:#000000;font-family:monospace;}
.watchlist-links {display:flex;gap:.5rem;margin-top:.25rem;}
.watchlist-links a {font-size:.75rem;color:#1d4ed8;font-weight:600;
 text-decoration:none;}
.watchlist-links a:hover {color:#000000;text-decoration:underline;}
.watchlist-metric {text-align:center;}
.watchlist-metric-label {font-size:.65rem;color:#000000;text-transform:uppercase;
 letter-spacing:.04em;}
.watchlist-metric-value {font-size:.95rem;font-weight:700;color:#000000;}
.watchlist-metric-sub {font-size:.65rem;color:#000000;}
.pool-links {display:flex;gap:.5rem;flex-wrap:wrap;justify-content:center;}
.pool-links a {font-size:.75rem;color:#1d4ed8;font-weight:700;
 text-decoration:none;}
.pool-links a:hover {color:#000000;text-decoration:underline;}
</style>
<div class="hero"><h1>🧮 Wallet Depth</h1>
<p>Fokus analisa holder: dust wallet (≤ $10) sebagai jejak dump.
≥ 0,5% MC = HATI-HATI · ≥ 1% MC = BAHAYA. Grafik 4 jam + Scan Meteora DLMM.</p></div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _number(value, pattern=".1f"):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


def _compact(value, signed=False):
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if signed and n > 0 else ""
    if abs(n) >= 1e6:
        return f"{sign}${n / 1e6:.2f}M"
    if abs(n) >= 1e3:
        return f"{sign}${n / 1e3:.1f}K"
    return f"{sign}${n:,.0f}"


def _wib(ts):
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(hours=7)
    return when.strftime("%d %b %H:%M") + " WIB"


def _dust_badge_html(flag: dict) -> str:
    level = flag.get("level") or "unknown"
    label = str(flag.get("label") or "—")
    if flag.get("rising") and level in ("danger", "caution"):
        label = f"{label} ↑"
    cls = {"ok": "dust-ok", "caution": "dust-caution",
           "danger": "dust-danger"}.get(level, "dust-none")
    return f'<span class="dust-badge {cls}">{html.escape(label)}</span>'


def _dust_best_html(flag: dict) -> str:
    """Chip 🏆 BEST POOL — hanya Scan Meteora (permintaan user 2026-09-04).

    ``flag["best"]`` sudah dijamin oleh ``dust_flag(..., holders=...)``:
    dust % MC < 0,1% **dan** data holder valid (total_fetched > 0,
    wallets_analyzed ≥ 40) — dust "0,00%" dari data gagal tidak pernah
    mendapat chip ini. Level badge (AMAN) tidak berubah.
    """
    if not flag.get("best"):
        return ""
    label = html.escape(str(DUST_BEST_LABEL))
    return f'<span class="dust-badge dust-best">🏆 {label}</span>'


def _delta_pp_html(delta, digits: int = 2) -> str:
    """Perubahan dust % MC dalam poin persentase (merah bila naik)."""
    if delta is None:
        return '<span style="color:#64748b;">—</span>'
    try:
        value = float(delta)
    except (TypeError, ValueError):
        return '<span style="color:#64748b;">—</span>'
    cls = "lp-delta-up" if value > 0 else (
        "lp-delta-down" if value < 0 else "")
    text = f"{value:+.{digits}f} pp"
    return f'<span class="{cls}">{text}</span>' if cls else text


SOLANA_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_CA_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _ca_error(value) -> str:
    """Pesan error validasi CA; string kosong bila address terlihat valid."""
    ca = str(value or "").strip()
    if not ca:
        return "Masukkan contract address terlebih dahulu."
    if not (SOLANA_CA_RE.match(ca) or EVM_CA_RE.match(ca)):
        return ("Format CA tidak valid. Solana: base58 32–44 karakter · "
                "EVM: 0x + 40 hex.")
    return ""


def _points_for(mint, token, store):
    return merge_points(history_for_mint(store, mint),
                        (token or {}).get("history") or [])


def _depth_tables_html(depth: dict) -> str:
    """Tabel Wallet Depth by Threshold + tier ala Solscan (HTML)."""
    def _pct(item):
        pct = item.get("pct_mc")
        return "—" if pct is None else f"{float(pct):.2f}%"

    def _count(item):
        return "—" if item.get("count") is None else f"{int(item['count']):,}"

    bucket_rows = "".join(
        f"<tr><td>{html.escape(str(b.get('label') or ''))}</td>"
        f"<td style='text-align:center'>{_count(b)}</td>"
        f"<td style='text-align:right'>{_compact(b.get('value_usd'))}</td>"
        f"<td style='text-align:right'>{_pct(b)}</td></tr>"
        for b in (depth.get("buckets") or []))
    tier_rows = "".join(
        f"<tr><td>{html.escape(str(t.get('emoji') or ''))} "
        f"{html.escape(str(t.get('tier') or ''))}</td>"
        f"<td style='text-align:center'>{_count(t)}</td>"
        f"<td style='text-align:right'>{_compact(t.get('value_usd'))}</td>"
        f"<td style='text-align:right'>{_pct(t)}</td></tr>"
        for t in (depth.get("tiers") or []))
    style = ("border-collapse:collapse;font-size:.8rem;color:#000000;"
             "margin:0 .6rem .4rem 0;")
    th = "border:1px solid #cbd5e1;padding:.3rem .6rem;background:#f1f5f9;"
    td = "border:1px solid #cbd5e1;padding:.25rem .6rem;"
    return f"""
<div style="display:flex;flex-wrap:wrap;gap:1rem;">
<table style="{style}">
<thead><tr><th style="{th}">Range</th><th style="{th}">Holder</th>
<th style="{th}">Total Value</th><th style="{th}">% Market Cap</th>
</tr></thead><tbody>{bucket_rows}</tbody></table>
<table style="{style}">
<thead><tr><th style="{th}">Tier</th><th style="{th}">Holder</th>
<th style="{th}">Total Value</th><th style="{th}">% Market Cap</th>
</tr></thead><tbody>{tier_rows}</tbody></table>
</div>"""


def _render_depth(holders: dict, symbol: str) -> None:
    """Render Wallet Depth by Threshold dari data holder Helius."""
    depth = holders.get("depth") if isinstance(holders.get("depth"), dict) \
        else None
    if not depth:
        return
    with st.expander(f"📊 Wallet Depth by Threshold — ${symbol} "
                     "(Helius)", expanded=False):
        st.markdown(_depth_tables_html(depth), unsafe_allow_html=True)
        total_all = depth.get("holders_all")
        total_wallet = depth.get("holders_wallet")
        pool_n = int(depth.get("pool_excluded") or 0)
        if depth.get("buckets_include_pools"):
            bucket_line = (f"Bucket dihitung atas semua akun bernilai >$0 "
                           f"({total_all:,} akun, termasuk LP/pool)")
        else:
            bucket_line = (f"Bucket dihitung atas wallet murni saja "
                           f"({total_wallet:,} akun — {pool_n:,} akun "
                           f"LP/pool disingkirkan dari list holder)")
        st.caption(
            f"{bucket_line}; tier atas wallet murni "
            f"({total_wallet:,} wallet). Nilai USD = "
            f"balance × harga token saat scan (DexScreener)."
        )


# ---------------------------------------------------------------------------
# Chart LP — watchlist terpisah untuk token dari Scan Meteora Pool
# ---------------------------------------------------------------------------
LP_CARD_TITLE = "🌊 Chart LP — Watchlist Meteora"
LP_ADD_FORM = "lp-add-token"
HOLDER_TAB = "📋 Watchlist Holder"
LP_TAB = "🌊 Chart LP (Meteora)"
ADD_TARGETS = [HOLDER_TAB, LP_TAB]
ADD_TARGET_SOURCE = {HOLDER_TAB: "manual", LP_TAB: LP_SOURCE}


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
    return (f'<div class="lp-head"><span class="lp-title">{LP_CARD_TITLE}'
            f"</span>{''.join(pills)}</div>")


def _render_lp_row(row: dict) -> None:
    """Satu baris token Chart LP + grafik perubahan dust holder."""
    mint = row.get("mint") or ""
    symbol = row.get("symbol") or "?"
    holders = row.get("holders") or {}
    flag = row.get("flag") or {}
    dust_pct = row.get("dust_pct")
    dust_count = row.get("dust_count")
    truncated = bool(holders.get("truncated"))
    dust_txt = ("—" if dust_count is None
                else (f"≥{int(dust_count)}" if truncated
                      else f"{int(dust_count):,}"))
    pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.2f}%"
    spark = sparkline_svg(row.get("points") or [], key="dust_pct_mc")
    if not spark:
        spark = ('<span style="font-size:.7rem;color:#64748b;">'
                 "belum ada grafik</span>")

    cols = st.columns([1.7, 0.75, 0.95, 0.9, 1.25, 0.42, 0.42, 0.42])
    cols[0].markdown(
        f'<div class="watchlist-token">'
        f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
        f'<span class="watchlist-mint">{html.escape(mint[:8])}…</span>'
        f'<span class="watchlist-metric-sub">MC {_compact(row.get("mc"))} · '
        f'scan {_wib(row.get("analyzed_at"))}</span>'
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
    cols[3].markdown(
        f'<div class="watchlist-metric">'
        f'<div class="watchlist-metric-value">'
        f'{_delta_pp_html(row.get("delta_4h"))}</div>'
        f'<div class="watchlist-metric-sub">total '
        f'{_delta_pp_html(row.get("delta_total"), 2)}</div></div>',
        unsafe_allow_html=True)
    cols[4].markdown(f'<div style="text-align:center;">{spark}</div>',
                     unsafe_allow_html=True)
    if cols[5].button("🧮", key=f"lp-holder-{mint}",
                      help="Buka Holder Analytic", use_container_width=True):
        st.session_state["holder_mint"] = mint
        st.switch_page(HOLDER_PAGE_PATH, query_params={"mint": mint})
    if cols[6].button("📋", key=f"lp-move-{mint}",
                      help="Pindahkan ke Watchlist Holder",
                      use_container_width=True):
        set_watchlist_source(mint, "manual")
        st.rerun()
    if cols[7].button("✕", key=f"lp-remove-{mint}",
                      help="Hapus dari Chart LP", use_container_width=True):
        remove_from_watchlist(mint)
        st.rerun()

    with st.expander(f"📈 Grafik perubahan dust holder — ${symbol}",
                     expanded=False):
        figure = lp_chart_figure(row.get("points") or [], symbol)
        if figure is None:
            st.info("Butuh minimal 2 titik bucket 4 jam. Cron (target ±1 jam, "
                    "best-effort) atau tombol **Scan holder watchlist** "
                    "akan mengisinya.")
        else:
            st.pyplot(figure, use_container_width=True)
            plt.close(figure)
        st.caption(
            f"Garis = dust % marketcap · batang = jumlah wallet dust · "
            f"ambang HATI-HATI {DUST_CAUTION_PCT:g}% / BAHAYA "
            f"{DUST_DANGER_PCT:g}% · titik per 4 jam "
            f"({len(row.get('sampled') or [])} bucket).")
        if isinstance(holders.get("depth"), dict):
            _render_depth(holders, symbol)
    st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)


def _render_lp_card(rows: list[dict]) -> None:
    """Card paling atas: watchlist Meteora + grafik perubahan dust holder."""
    summary = lp_summary(rows)
    with st.container(border=True):
        st.markdown(_lp_head_html(summary), unsafe_allow_html=True)
        st.caption(
            "Watchlist terpisah untuk token yang ditambahkan dari **Scan "
            "Meteora Pool** (⭐) atau ditambah manual ke card ini. Grafik "
            "menampilkan **perubahan dust holder** per bucket 4 jam: "
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
                        add_to_watchlist(ca, "?", source=LP_SOURCE)
                        st.success(f"{ca[:8]}… masuk Chart LP.")
                        st.rerun()

        if not rows:
            st.info("Chart LP masih kosong. Tambahkan token dari **⭐ Scan "
                    "Meteora Pool** di bawah atau tempel CA di form atas.")
            return

        overlay = lp_overlay_figure(rows)
        if overlay is not None:
            with st.expander("📈 Overlay dust % MC semua token LP",
                             expanded=True):
                st.pyplot(overlay, use_container_width=True)
                plt.close(overlay)

        header = st.columns([1.7, 0.75, 0.95, 0.9, 1.25, 0.42, 0.42, 0.42])
        style = "font-size:0.72rem;color:#000000;font-weight:700;"
        titles = ["Token", "Dust", "Hold %MC", "Δ 4 jam", "Grafik 4 jam",
                  "", "", ""]
        for col, title in zip(header, titles):
            align = "" if title == "Token" else "text-align:center;"
            col.markdown(f'<div style="{style}{align}">{title}</div>',
                         unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)
        for row in rows:
            _render_lp_row(row)


# ---------------------------------------------------------------------------
# Scan Holder Khusus — Helius (satu token)
# ---------------------------------------------------------------------------
def _render_helius_holder_scan() -> None:
    """Section: input CA satu token → scan holder via Helius + bar chart."""
    st.divider()
    st.subheader("🛰 Scan Holder Khusus — Helius")
    st.caption(
        "Tempel **contract address (CA)** satu token untuk mengambil seluruh "
        "daftar holder langsung dari **Helius DAS** (getTokenAccounts) dan "
        "menampilkan **bar chart distribusi holder** per range nilai USD "
        "(Wallet Depth by Threshold). **Default: LP/pool AMM disingkirkan "
        "dari bucket.**"
    )

    with st.form("helius-holder-form"):
        col_ca, col_max, col_pool, col_btn = st.columns([3, 1, 2, 1])
        ca_input = col_ca.text_input(
            "Contract address (CA)",
            placeholder="So11111111111111111111111111111111111111112")
        max_wallets = col_max.number_input(
            "Maks holder", min_value=1000, max_value=100_000,
            value=20_000, step=1_000)
        include_pools = col_pool.checkbox(
            "Sertakan LP/pool di bucket", value=False,
            help="Default OFF: pool/AMM disingkirkan dari list/bucket holder.")
        run = col_btn.form_submit_button("🛰 Scan Holder", type="primary")

    if run:
        ca = str(ca_input or "").strip()
        if not ca:
            st.warning("Masukkan contract address terlebih dahulu.")
        elif not SOLANA_CA_RE.match(ca):
            st.warning("Format CA Solana tidak valid. Gunakan address base58 "
                       "sepanjang 32–44 karakter.")
        else:
            with st.status("Mengambil holder dari Helius…",
                           expanded=False) as box:
                try:
                    result = scan_token_holders(
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
    """Tampilkan metrik + bar chart + tabel depth hasil scan holder Helius."""
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

    st.markdown(f"**${html.escape(symbol)}** — `{html.escape(mint)}`")
    st.markdown(external_links_html(mint), unsafe_allow_html=True)

    if result.get("no_helius_keys"):
        st.error("Belum ada Helius API key. Isi `helius_api_key` di "
                 "config.json / env `HELIUS_API_KEY` / Streamlit secrets.")
        return
    if result.get("scan_failed"):
        detail = str((result.get("snapshot") or {}).get("error") or "")
        detail = detail.strip()
        message = ("Scan tidak menghasilkan holder. Pastikan CA valid, harga "
                   "token tersedia (DexScreener), dan Helius API key aktif.")
        if detail:
            message += f" Detail: {detail}"
        st.error(message)
        return

    prefix = "≥" if truncated else ""
    buckets_with_pools = bool(depth.get("buckets_include_pools", True))
    pool_n = int(depth.get("pool_excluded") or 0)
    bucket_n = holders_all if buckets_with_pools else holders_wallet
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Akun holder (Helius)", f"{prefix}{fetched:,}",
              help="Akun token yang diambil dari Helius DAS getTokenAccounts.")
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
        f"Sumber holder: 🛰 Helius DAS getTokenAccounts · "
        f"{prefix}{fetched:,} akun dianalisis · {pages} halaman{pool_note} · "
        "nilai USD = balance × harga token (DexScreener)."
    )


def _render_meteora_scan() -> None:
    """Scan pool Meteora DLMM 24h ∩ 1h + holder dust."""
    st.divider()
    st.subheader("🌊 Scan Meteora Pool")
    st.caption(
        "Top DLMM 24 jam (`active_tvl ≥ 1000`, `fee_active_tvl_ratio ≥ 250`) "
        "dibandingkan 1 jam (`fee_active_tvl_ratio ≥ 1`). Pool 24 jam yang "
        "masih muncul di 1 jam **tetap ditampilkan**. Dust holder "
        f"**≥ {DUST_DANGER_PCT:g}% MC (BAHAYA)** disembunyikan, "
        f"**≥ {DUST_CAUTION_PCT:g}% MC** diberi badge **HATI-HATI**. "
        f"Dust **< {DUST_BEST_PCT:g}% MC** dengan data holder valid "
        "(≥ 40 wallet) diberi badge 🏆 BEST POOL — level AMAN tidak berubah, "
        "hanya penanda kebersihan distribusi. "
        "⭐ memasukkan token ke card **Chart LP** di bagian atas dashboard. "
        "Tombol kanan: Meteora + HawkFi."
    )
    if st.button("🌊 Scan Meteora + Holder", type="primary",
                 use_container_width=True):
        bar = st.progress(0.0, text="Listing pool Meteora…")

        def _progress(index, total, label):
            bar.progress(index / max(total, 1),
                         text=f"Holder {index}/{total} · {label}")

        try:
            result = scan_meteora(max_wallets=2000, workers=6,
                                  progress=_progress)
        except Exception as exc:  # noqa: BLE001
            result = {"rows": [], "error": str(exc), "hidden_dust": 0,
                      "fetched": 0}
        finally:
            bar.empty()
        st.session_state["meteora_scan"] = result

    result = st.session_state.get("meteora_scan") or {}
    error = result.get("error") or ""
    if error:
        st.warning(f"Meteora API: {error}")
    rows = result.get("rows") or []
    hidden = int(result.get("hidden_dust") or 0)
    fetched = int(result.get("fetched") or 0)
    if fetched:
        st.caption(f"{len(rows)} pool ditampilkan · {hidden} disembunyikan "
                   f"(dust ≥ {DUST_DANGER_PCT:.0f}% MC = BAHAYA) · listing {fetched}.")
    if not rows:
        if result:
            st.info("Tidak ada pool yang lolos filter dust (atau listing kosong).")
        return

    header_cols = st.columns([1.6, 0.8, 0.7, 0.9, 0.7, 1.2, 0.45])
    titles = ["Token", "MC", "Dust", "Dust %MC", "TF", "Pool", ""]
    style = "font-size:0.72rem;color:#000000;font-weight:700;text-align:center;"
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
        # BEST POOL butuh bukti data holder valid (bukan cuma angka): guard
        # ada di dust_flag(holders=…), lihat holder_history._holders_valid_for_best.
        analysis = (row.get("analysis")
                    if isinstance(row.get("analysis"), dict) else {})
        holders = (analysis.get("holders")
                   if isinstance(analysis.get("holders"), dict) else None)
        flag = dust_flag(dust_pct, holders=holders)
        tf = []
        if row.get("in_24h"):
            tf.append("24H")
        if row.get("in_1h"):
            tf.append("1H")
        tf_txt = "+".join(tf) or "—"
        cols = st.columns([1.6, 0.8, 0.7, 0.9, 0.7, 1.2, 0.45])
        cols[0].markdown(
            f'<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(ca)}</div>'
            f"</div>", unsafe_allow_html=True)
        cols[1].markdown(
            f'<div class="watchlist-metric"><div class="watchlist-metric-value">'
            f'{_compact(row.get("mc"))}</div></div>', unsafe_allow_html=True)
        cols[2].markdown(
            f'<div class="watchlist-metric"><div class="watchlist-metric-value">'
            f'{_number(dust_count, ".0f")}</div>'
            f'<div class="watchlist-metric-sub">wallet</div></div>',
            unsafe_allow_html=True)
        pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.2f}%"
        cols[3].markdown(
            f'<div class="watchlist-metric"><div class="watchlist-metric-value">'
            f"{pct_txt}</div>{_dust_badge_html(flag)}"
            f"{_dust_best_html(flag)}</div>",
            unsafe_allow_html=True)
        cols[4].markdown(
            f'<div class="watchlist-metric"><div class="watchlist-metric-value">'
            f"{html.escape(tf_txt)}</div></div>", unsafe_allow_html=True)
        pool_html = pool_links_html(pool) or '<span>—</span>'
        cols[5].markdown(
            f'<div class="pool-links">{pool_html}</div>',
            unsafe_allow_html=True)
        if cols[6].button("⭐", key=f"meteora-star-{index}",
                          help="Tambah ke Chart LP (watchlist Meteora di atas)",
                          use_container_width=True):
            if ca:
                add_to_watchlist(ca, symbol, source=LP_SOURCE)
                st.success(f"${symbol} masuk Chart LP")
        st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
watchlist = load_watchlist()
force_status = bool(st.session_state.pop("status_force_refresh", False))
# Overlay scan manual dari halaman Holder Analytic supaya dashboard, watchlist,
# dan Chart LP membaca angka yang sama dengan grafik (bukan snapshot cron lama).
holder_status = apply_manual_scan(
    load_holder_status(force_refresh=force_status),
    st.session_state.get(MANUAL_SCAN_KEY))
status_tokens = holder_status.get("tokens") or {}
# Store lokal + backup durable (ref holder-live) supaya lingkungan ephemeral
# tetap punya baseline scan FULL, kohort, dan kronologi.
history_store = seed_from_status(load_durable_holder_history(),
                                  holder_status)

# Watchlist dipecah dua: token Scan Meteora → card **Chart LP** paling atas,
# sisanya → watchlist holder biasa. Scan tombol di bawah tetap memproses
# seluruh watchlist supaya kedua card punya data.
lp_watch, holder_watch = split_watchlist(watchlist)
_render_lp_card(lp_card_rows(lp_watch, status_tokens, history_store))

# Satu angka per baris watchlist: snapshot cron **atau** titik history yang
# lebih baru (scan manual / cron yang publish snapshot-nya gagal). Dihitung
# sekali di sini supaya caption "scan terakhir" dan angka di baris selalu
# bicara tentang data yang sama (sebelumnya baris membaca snapshot sementara
# grafik membaca history — dua angka untuk satu token).
_now_ts = int(datetime.now(timezone.utc).timestamp())
_holder_points = {mint: _points_for(mint, status_tokens.get(mint) or {},
                                    history_store)
                  for mint in holder_watch}
_holder_views = {mint: resolve_view(status_tokens.get(mint) or {}, points,
                                    now=_now_ts)
                 for mint, points in _holder_points.items()}
_watch_sync = sync_summary(_holder_views.values(), now=_now_ts)

st.subheader("📋 Watchlist — Analisa Holder (Dust)")
st.caption(
    "Ringkasan dust: jumlah wallet dan **berapa % marketcap** yang mereka "
    f"pegang. ≥ {DUST_CAUTION_PCT:g}% MC = HATI-HATI · "
    f"≥ {DUST_DANGER_PCT:g}% MC = BAHAYA "
    "(dust nambah pesat = jejak distribusi). "
    f"Ambang dust: ${DUST_LIMIT_USD:.0f}. "
    "Grafik kecil = dust % MC tiap 4 jam. Kolom **Sejak masuk** = perubahan "
    "dust % MC sejak token ditambahkan sampai scan terakhir (hijau bila turun "
    "≥ 50%, merah bila naik ≥ 100%). Token dari Scan Meteora ada di "
    "card **Chart LP** di atas."
)
st.caption(sync_caption_text(_watch_sync,
                             status_updated_at=holder_status.get("updated_at")))


if watchlist and not status_tokens:
    st.warning(
        "Belum ada data holder dari cron (`holder_status.json` di branch "
        "`holder-live` kosong/tidak ada). Pastikan secret **HELIUS_API_KEY** "
        "dan **GITHUB_TOKEN/GH_TOKEN** terpasang di GitHub Actions, atau klik "
        "**Scan holder watchlist** untuk mengisi data sekarang.",
        icon="⚠️")
elif watchlist:
    _missing = [str((m or {}).get("symbol") or ca[:6]).upper()
                for ca, m in watchlist.items()
                if not ((status_tokens.get(ca) or {}).get("holders") or {}
                        ).get("total_fetched")]
    if _missing:
        st.info("Holder belum terambil untuk: " + ", ".join(_missing[:8])
                + (" …" if len(_missing) > 8 else "")
                + ". Cron akan mencoba lagi ±1 jam; atau scan manual.",
                icon="ℹ️")

if st.button("🔄 Scan holder watchlist", type="primary",
             use_container_width=True):
    analyses = {}
    total = len(watchlist)
    bar = st.progress(0.0, text=f"Scan 0/{total} token…")
    done = 0
    for mint, meta in watchlist.items():
        try:
            cohort = ((history_store.get("tokens") or {}).get(mint) or {}).get(
                "cohort") or {}
            addrs = list((cohort.get("balances") or {}).keys())
            analyses[mint] = analyze_token(
                mint, (meta or {}).get("symbol") or "?",
                max_wallets=2000, fetch_market=True, cohort_addrs=addrs)
        except Exception:  # noqa: BLE001
            analyses[mint] = None
        done += 1
        bar.progress(done / max(total, 1),
                     text=f"Scan {done}/{total} · "
                          f"{str((meta or {}).get('symbol') or '?')}")
    ok = {mint: item for mint, item in analyses.items()
          if isinstance(item, dict)}
    if ok:
        ingest_many(ok, store=history_store)
        publish_holder_status(ok, watchlist, push=False)
    st.session_state["status_force_refresh"] = True
    st.rerun()

if not holder_watch:
    st.info("Watchlist holder kosong. Tambahkan contract address di bawah, "
            "atau pindahkan token dari card Chart LP (📋).")
else:
    header_cols = st.columns([1.55, 0.85, 0.9, 1.05, 1.05, 0.4, 0.4, 0.4])
    header_style = "font-size:0.78rem;color:#000000;font-weight:700;"
    center = "text-align:center;" + header_style
    header_titles = ["Token", "Dust", "Hold %MC", "Sejak masuk", "4 jam",
                     "", "", ""]
    header_css = [header_style] + [center] * 7
    for col, style, title in zip(header_cols, header_css, header_titles):
        col.markdown(f'<div style="{style}">{title}</div>',
                     unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:0.65rem;color:#64748b;margin:0.3rem 0;">'
        "Dust = wallet 0 &lt; value ≤ $10 (bukan LP). Grafik 4 jam = "
        "perubahan dust % MC. <b>Sejak masuk</b> = perubahan dust % MC dari "
        "titik pertama setelah token ditambahkan sampai scan terakhir "
        "(<span style=\"color:#15803d;font-weight:700;\">hijau</span> turun "
        "≥ 50% · <span style=\"color:#b91c1c;font-weight:700;\">merah</span> "
        "naik ≥ 100%). 🧮 buka Holder Analytic · 🌊 pindahkan ke Chart LP."
        "</div>",
        unsafe_allow_html=True)

    st.markdown('<hr style="margin:0.5rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)

    ordered = sorted(holder_watch.items(),
                     key=lambda item: str(
                         (status_tokens.get(item[0]) or {}).get("symbol")
                         or item[1].get("symbol") or item[0]).upper())
    for mint, meta in ordered:
        token = status_tokens.get(mint) or {}
        symbol = str(meta.get("symbol") or token.get("symbol") or "?").upper()
        holders = token.get("holders") or {}
        points = _holder_points.get(mint) or _points_for(mint, token,
                                                         history_store)
        view = _holder_views.get(mint) or resolve_view(token, points,
                                                       now=_now_ts)
        sampled = resample_4h(points)
        # Angka baris = sumber terbaru (snapshot cron / titik history / scan
        # manual), bukan selalu snapshot — lihat sync_caption_text di atas.
        dust_count = view.get("dust_count")
        dust_pct = view.get("dust_pct")
        prev_pct = previous_pct(sampled, view)
        flag = dust_flag(dust_pct, prev_pct)
        change = dust_change_since_added(meta, points, view, now=_now_ts)
        truncated = holders.get("truncated", False)
        dust_txt = ("—" if dust_count is None
                    else (f"≥{int(dust_count)}" if truncated
                          else f"{int(dust_count):,}"))
        pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.2f}%"
        spark = sparkline_svg(points, key="dust_pct_mc")
        if not spark:
            spark = '<span style="font-size:.7rem;color:#64748b;">belum ada grafik</span>'
        scan_note = f"scan {format_wib(view.get('ts'))}"
        if view.get("source") == SOURCE_HISTORY:
            scan_note += " · titik history"
        if view.get("drift"):
            scan_note += " · ⚠️ snapshot ≠ history"
        if view.get("stale"):
            scan_note += " · basi"

        cols = st.columns([1.55, 0.85, 0.9, 1.05, 1.05, 0.4, 0.4, 0.4])
        cols[0].markdown(
            f'<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'<span class="watchlist-mint">{html.escape(mint[:8])}…</span>'
            f'<span class="watchlist-metric-sub">{scan_note}</span>'
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
            f'{_dust_badge_html(flag)}</div>',
            unsafe_allow_html=True)
        cols[3].markdown(change_html(change), unsafe_allow_html=True)
        cols[4].markdown(
            f'<div style="text-align:center;">{spark}</div>',
            unsafe_allow_html=True)
        if cols[5].button("🧮", key=f"holder-{mint}",
                          help="Buka Holder Analytic",
                          use_container_width=True):
            st.session_state["holder_mint"] = mint
            st.switch_page(HOLDER_PAGE_PATH, query_params={"mint": mint})
        if cols[6].button("🌊", key=f"to-lp-{mint}",
                          help="Pindahkan ke Chart LP (watchlist Meteora)",
                          use_container_width=True):
            set_watchlist_source(mint, LP_SOURCE)
            st.rerun()
        if cols[7].button("✕", key=f"remove-{mint}", help="Hapus watchlist",
                          use_container_width=True):
            remove_from_watchlist(mint)
            st.rerun()
        if isinstance(holders.get("depth"), dict):
            _render_depth(holders, symbol)
        st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)

with st.expander("➕ Tambah token", expanded=not bool(watchlist)):
    with st.form("add-token", clear_on_submit=True):
        mint_input = st.text_input(
            "Contract address", key="add-token-input",
            help="Symbol di-fetch otomatis dari DexScreener")
        target = st.radio(
            "Masuk ke card", ADD_TARGETS, index=0, horizontal=True,
            help=("📋 Watchlist Holder = daftar analisa dust biasa. "
                  "🌊 Chart LP = watchlist terpisah (card paling atas) untuk "
                  "token Meteora/LP beserta grafik perubahan dust holder."))
        submitted = st.form_submit_button("Tambah ke watchlist")
        if submitted:
            ca_error = _ca_error(mint_input)
            if ca_error:
                st.warning(ca_error)
            else:
                source = ADD_TARGET_SOURCE.get(target, "manual")
                added = add_to_watchlist(str(mint_input).strip(), "?",
                                         source=source)
                card = "Chart LP" if source == LP_SOURCE else "watchlist"
                if added:
                    st.success(f"Token ditambahkan ke {card}.")
                else:
                    error = get_last_push_error()
                    st.warning(error.get("msg")
                               or f"Tersimpan lokal di {card}; sinkronisasi "
                                  "GitHub belum berhasil.")
                st.rerun()

# ---------------------------------------------------------------------------
# 🚀 Pre-Pump Screener — 4 sinyal on-chain untuk token watchlist source=degen.
# ``configure_page=False``: st.set_page_config sudah dipanggil di atas dan
# hanya boleh sekali per halaman. Watchlist / snapshot holder / store durable
# disuntikkan supaya section ini tidak menarik GitHub + DexScreener dua kali.
# ---------------------------------------------------------------------------
pre_pump_screener.main(configure_page=False, watchlist=watchlist,
                       status_tokens=status_tokens, store=history_store)

st.divider()
st.subheader("🔍 Temukan Token")
st.caption("Scan Trending/Degen menampilkan listing GMGN. "
           "Analisa dust ada di Scan Meteora dan watchlist.")

st.markdown("""
<style>
div[data-testid="stButtonGroup"] button {
    font-size: 0.9rem !important;
    padding: 0.5rem 1.1rem !important;
    font-weight: 700 !important;
}
</style>
""", unsafe_allow_html=True)

TREND_TAB = "📈 Trending"
DEGEN_TAB = "🔥 Degen"
DISCOVER_TABS = [TREND_TAB, DEGEN_TAB]

active_tab = st.session_state.get("discover_tab_active", TREND_TAB)
selected_tab = st.segmented_control(
    "Mode listing", DISCOVER_TABS, default=active_tab,
    key="discover_tab", label_visibility="collapsed")
if selected_tab not in DISCOVER_TABS:
    selected_tab = active_tab
st.session_state["discover_tab_active"] = selected_tab

if selected_tab == DEGEN_TAB:
    if st.button("🔥 Scan Degen", use_container_width=True):
        rows_24, error_24 = run_screen_hrhr(force=True)
        rows_1, error_1 = run_screen_hrhr_h1(force=True)
        combined = merge_scan_rows(rows_24, rows_1)
        st.session_state["degen_combined"] = combined
        st.session_state["degen_error"] = error_24 or error_1
    if st.session_state.get("degen_error"):
        st.error(st.session_state["degen_error"])
    render_trending(st.session_state.get("degen_combined", []),
                    key_prefix="degen", source="degen", watchlist=watchlist)
else:
    if st.button("🔎 Scan Trending", use_container_width=True):
        rows_24, error_24 = run_screen(force=True)
        rows_1, error_1 = run_screen_h1(force=True)
        combined = merge_scan_rows(rows_24, rows_1)
        st.session_state["trend_combined"] = combined
        st.session_state["trend_error"] = error_24 or error_1
    if st.session_state.get("trend_error"):
        st.error(st.session_state["trend_error"])
    render_trending(st.session_state.get("trend_combined", []),
                    key_prefix="trend", source="trending", watchlist=watchlist)

_render_meteora_scan()
_render_helius_holder_scan()
