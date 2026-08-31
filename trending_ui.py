# -*- coding: utf-8 -*-
"""Streamlit renderer listing GMGN + analisis holder (real vs dust).

Scan Trending/Degen otomatis memperkaya tiap token dengan:
- real holder (> $10 value) vs dust holder,
- dust holder berapa % dari marketcap,
- net flow 12 jam terakhir + deteksi silent accumulation.
"""
from __future__ import annotations

import html as _html

import streamlit as st

from gmgn_screener import (screen, screen_hrhr, screen_hrhr_h1,
                           screen_trending_h1)
from links import CVD_PAGE_PATH, external_links_html
from silent_accumulation import (FILTER_LP, FILTER_OPTIONS, FILTER_PUMPDUMP,
                                 FILTER_SILENT, apply_filters, enrich_rows,
                                 filter_counts, holder_filter_match)
from watchlist import add_to_watchlist

# Inject consistent styling
st.markdown("""
<style>
.trending-row {padding: 0.6rem 0; border-bottom: 1px solid #cbd5e1;}
.depth-tag {display:inline-block;margin-top:.15rem;margin-right:.25rem;
 padding:.12rem .4rem;border-radius:6px;font-size:.58rem;font-weight:800;}
.tag-silent {background:#14532d;color:#dcfce7}
.tag-lp {background:#854d0e;color:#fef9c3}
.tag-pumpdump {background:#7f1d1d;color:#fee2e2}
.trending-token {display: block;}
.trending-symbol {display: block; margin-bottom: 0.4rem; font-size: 1rem;
    font-weight: 800; line-height: 1.25; color: #000000;}
.trending-mint {display: block; font-size: 0.7rem; line-height: 1.2;
    color: #000000; font-family: monospace;}
.trending-links {display: flex; gap: 0.5rem; margin-top: 0.2rem;}
.trending-links a {font-size: 0.7rem; color: #1d4ed8; font-weight: 600;
    text-decoration: none;}
.trending-links a:hover {color: #000000; text-decoration: underline;}
.trending-metric {text-align: center; padding-top: 0.3rem;}
.trending-metric-label {font-size: 0.6rem; color: #000000;
    text-transform: uppercase; letter-spacing: 0.03em;}
.trending-metric-value {font-size: 0.85rem; font-weight: 700;
    color: #000000;}
.silent-badge {display: inline-block; padding: 0.22rem 0.5rem;
    border-radius: 8px; font-size: 0.7rem; font-weight: 800;}
.silent-yes {background: #14532d; color: #dcfce7;}
.silent-buy {background: #1e3a8a; color: #dbeafe;}
.silent-sell {background: #7f1d1d; color: #fee2e2;}
.silent-none {background: #e2e8f0; color: #000000;}
</style>
""", unsafe_allow_html=True)


def _navigate_to_cvd(ca: str):
    """Preselect *ca* on the CVD page via session + query params."""
    ca = str(ca or "")
    st.session_state["effort_mint"] = ca
    st.switch_page(CVD_PAGE_PATH, query_params={"mint": ca})


def _compact(value):
    value = float(value or 0)
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def _color_change(value):
    """Return color based on positive/negative change."""
    try:
        v = float(value)
        if v > 0:
            return f'<span style="color:#15803d;font-weight:700;">{v:+.1f}%</span>'
        elif v < 0:
            return f'<span style="color:#b91c1c;font-weight:700;">{v:+.1f}%</span>'
        return f'{v:+.1f}%'
    except Exception:  # noqa: BLE001
        return '—'


def _fmt(value, digits=1, suffix=""):
    if value is None:
        return "—"
    try:
        return f"{float(value):+.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def _analysis(row):
    return (row or {}).get("analysis") if isinstance(row, dict) else None


FILTER_LABELS = {
    FILTER_SILENT: "🔇 SILENT",
    FILTER_LP: "🏦 LP",
    FILTER_PUMPDUMP: "🎢 PUMPDUMP",
}

FILTER_HELP = {
    FILTER_SILENT: ("Silent accumulation 12 jam: net ≥ $50, ≥3 wallet "
                    "akumulator, harga ≤ ±5%, bot ≤ 35%."),
    FILTER_LP: ("Dust > 50% dari real (jumlah wallet) DAN real+dust hanya "
                "< 0.5% marketcap — supply hampir semua di LP/pool."),
    FILTER_PUMPDUMP: ("Real hanya < 20% dari dust — dominan dust, "
                      "real sangat sedikit."),
}


def _filter_bar(rows, *, key_prefix):
    """Filter SILENT / LP / PUMPDUMP untuk hasil scan. Return (rows, n_total)."""
    counts = filter_counts(rows)
    total = len(rows)
    selected = st.multiselect(
        "Filter holder depth",
        options=list(FILTER_OPTIONS),
        format_func=lambda name: (
            f"{FILTER_LABELS.get(name, name)} ({counts.get(name, 0)})"),
        key=f"{key_prefix}_holder_filters",
        help="\n".join(f"{FILTER_LABELS.get(n, n)}: {FILTER_HELP.get(n, '')}"
                       for n in FILTER_OPTIONS))
    matched = apply_filters(rows, selected)
    if selected:
        st.caption(f"Menampilkan **{len(matched)}** dari **{total}** token "
                   f"(filter: {' + '.join(FILTER_LABELS.get(n, n) for n in selected)}).")
    else:
        st.caption(f"{total} token · filter: SILENT {counts.get('SILENT', 0)} · "
                   f"LP {counts.get('LP', 0)} · "
                   f"PUMPDUMP {counts.get('PUMPDUMP', 0)}")
    return matched


def _silent_badge_html(row):
    """Badge 12 jam: silent accumulation / net beli / distribusi / tanpa data."""
    analysis = _analysis(row)
    if not analysis:
        return ('<span class="silent-badge silent-none">BELUM</span>')
    silent = analysis.get("silent") or {}
    flow = analysis.get("flow") or {}
    if (silent or {}).get("silent"):
        return ('<span class="silent-badge silent-yes">🔇 SILENT</span>')
    net = flow.get("net_usd")
    if net is not None and float(net) < 0:
        return ('<span class="silent-badge silent-sell">➖ DIST</span>')
    return ('<span class="silent-badge silent-buy">➕ NET BELI</span>')


def _token_identity_html(symbol, ca, row=None):
    """Render token name and CA prefix on clearly separated lines."""
    safe_symbol = _html.escape(str(symbol or "?").upper())
    safe_ca = _html.escape(str(ca or "")[:8])
    tags = ""
    analysis = _analysis(row)
    if analysis:
        tag_html = []
        if holder_filter_match(analysis, FILTER_SILENT):
            tag_html.append('<span class="depth-tag tag-silent">🔇 SILENT</span>')
        if holder_filter_match(analysis, FILTER_LP):
            tag_html.append('<span class="depth-tag tag-lp">🏦 LP</span>')
        if holder_filter_match(analysis, FILTER_PUMPDUMP):
            tag_html.append('<span class="depth-tag tag-pumpdump">🎢 PUMPDUMP</span>')
        tags = f'<div>{"".join(tag_html)}</div>'
    return (
        '<div class="trending-token">'
        f'<div class="trending-symbol">${safe_symbol}</div>'
        f'<div class="trending-mint">{safe_ca}…</div>'
        f'{tags}'
        f'<div class="trending-links">{external_links_html(str(ca or ""))}</div>'
        '</div>'
    )


def run_screen(force=False, key="trending_rows", **_kwargs):
    if force or key not in st.session_state:
        try:
            st.session_state[key] = screen()
            st.session_state[key + "_error"] = ""
        except Exception as exc:  # noqa: BLE001
            st.session_state[key] = []
            st.session_state[key + "_error"] = str(exc)
    return st.session_state[key], st.session_state[key + "_error"]


def run_screen_h1(force=False, key="trending_h1_rows", **_kwargs):
    if force or key not in st.session_state:
        try:
            st.session_state[key] = screen_trending_h1()
            st.session_state[key + "_error"] = ""
        except Exception as exc:  # noqa: BLE001
            st.session_state[key] = []
            st.session_state[key + "_error"] = str(exc)
    return st.session_state[key], st.session_state[key + "_error"]


def run_screen_hrhr(force=False, key="degen_rows", **_kwargs):
    if force or key not in st.session_state:
        try:
            st.session_state[key] = screen_hrhr()
            st.session_state[key + "_error"] = ""
        except Exception as exc:  # noqa: BLE001
            st.session_state[key] = []
            st.session_state[key + "_error"] = str(exc)
    return st.session_state[key], st.session_state[key + "_error"]


def run_screen_hrhr_h1(force=False, key="degen_h1_rows", **_kwargs):
    if force or key not in st.session_state:
        try:
            st.session_state[key] = screen_hrhr_h1()
            st.session_state[key + "_error"] = ""
        except Exception as exc:  # noqa: BLE001
            st.session_state[key] = []
            st.session_state[key + "_error"] = str(exc)
    return st.session_state[key], st.session_state[key + "_error"]


def scan_with_analysis(rows, *, key_prefix="scan", dust_limit=None,
                       max_wallets=2000, max_trade_pages=6, workers=6,
                       on_progress=None):
    """Scan listing lalu langsung analisis holder + 12 jam.

    Menyimpan hasil di ``st.session_state[key_prefix + '_analysis']`` supaya
    rerun berikutnya tidak memanggil GMGN lagi.
    """
    state_key = f"{key_prefix}_analysis"
    if not rows:
        st.session_state[state_key] = []
        return []
    total = len(rows)
    bar = st.progress(0.0, text=f"Analisis 0/{total} token…")

    def _progress(index, total_, label):
        bar.progress(index / total_, text=f"Analisis {index}/{total_} · {label}")

    try:
        enriched = enrich_rows(
            rows, dust_limit=dust_limit, max_wallets=max_wallets,
            max_trade_pages=max_trade_pages, workers=workers,
            progress=_progress)
    finally:
        bar.empty()
    st.session_state[state_key] = enriched
    return enriched


def _source_icon(source: str) -> str:
    """Ikon sumber data: 🛰 (Helius, utama) / 🕸 (GMGN, listing+ fallback)."""
    source = str(source or "gmgn").lower()
    if source == "helius":
        return '<span title="Helius" style="font-size:0.75rem;">🛰</span>'
    return '<span title="GMGN" style="font-size:0.75rem;">🕸</span>'


def _count_with_truncated(count, truncated: bool) -> str:
    """Format count dengan tanda ≥ bila pencarian holder terpotong."""
    if count is None:
        return "—"
    count_txt = str(int(count))
    if truncated:
        return f"≥{count_txt}"
    return count_txt


def render_trending(rows, *, key_prefix="listing", source="trending"):
    """Tabel listing + analisis holder real/dust & silent accumulation 12h."""
    if not rows:
        st.info("Tidak ada token dari respons GMGN saat ini.")
        return

    rows = _filter_bar(rows, key_prefix=key_prefix)
    if not rows:
        st.info("Tidak ada token yang cocok dengan filter terpilih. "
                "Hapus filter atau lakukan scan ulang.")
        return

    header_cols = st.columns(
        [1.6, 0.85, 0.8, 0.7, 0.95, 1.1, 0.9, 0.9, 0.55, 0.55])
    header_titles = ["Token", "MC", "Real >$10", "Dust", "Dust %MC",
                     "12 Jam", "Net 12j", "24h", "", ""]
    header_style = ("font-size:0.72rem;color:#000000;font-weight:700;"
                    "text-align:center;")
    for col, title in zip(header_cols, header_titles):
        col.markdown(f'<div style="{header_style}">{title}</div>',
                     unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:0.65rem;color:#64748b;margin:0.3rem 0;">'
        '🕸 GMGN (listing) · 🛰 Helius (fallback holder) · ≥ batas '
        'pencarian holder tercapai'
        '</div>',
        unsafe_allow_html=True)

    st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)

    for index, row in enumerate(rows):
        ca = str(row.get("ca") or "")
        symbol = str(row.get("symbol") or "?").upper()
        mc = _compact(row.get('mc'))
        analysis = _analysis(row)
        holders = (analysis or {}).get("holders") or {}
        flow = (analysis or {}).get("flow") or {}
        real_count = holders.get("real_count")
        dust_count = holders.get("dust_count")
        truncated = holders.get("truncated", False)
        holder_source = holders.get("source", "gmgn")
        dust_pct = holders.get("dust_pct_mc")
        dust_txt = ("—" if dust_pct is None
                    else f"{float(dust_pct):.2f}%")
        change = row.get('change_24h')
        change_html = _color_change(change)

        columns = st.columns(
            [1.6, 0.85, 0.8, 0.7, 0.95, 1.1, 0.9, 0.9, 0.55, 0.55])
        columns[0].markdown(_token_identity_html(symbol, ca, row),
                            unsafe_allow_html=True)
        columns[1].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{mc}</div></div>',
            unsafe_allow_html=True)
        columns[2].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">'
            f'{_source_icon(holder_source)} '
            f'{_count_with_truncated(real_count, truncated)}</div></div>',
            unsafe_allow_html=True)
        columns[3].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">'
            f'{_count_with_truncated(dust_count, truncated)}</div></div>',
            unsafe_allow_html=True)
        columns[4].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{dust_txt}</div>'
            f'</div>', unsafe_allow_html=True)
        columns[5].markdown(_silent_badge_html(row), unsafe_allow_html=True)
        columns[6].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">'
            f'{_fmt(flow.get("net_usd"), 0, "")}</div>'
            f'</div>', unsafe_allow_html=True)
        columns[7].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{change_html}</div>'
            f'</div>', unsafe_allow_html=True)
        if columns[8].button("📊", key=f"cvd-{key_prefix}-{index}",
                             help="Buka CVD", use_container_width=True):
            _navigate_to_cvd(ca)
        if columns[9].button("⭐", key=f"{key_prefix}-{index}",
                             help="Tambah ke Watchlist",
                             use_container_width=True):
            add_to_watchlist(row["ca"], row.get("symbol") or "?",
                             source=source)
            st.success(f"${symbol} ditambahkan")

        st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)
