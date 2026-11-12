# -*- coding: utf-8 -*-
"""UI main app: 🏆 SCAN BEST POOL (timeframe 12H).

Logika ada di ``pool_flow.py``; modul ini hanya menampilkan hasil scan.
Scan tidak menulis berkas apa pun.

Tabel dibuat HTML dengan lebar minimum dan scroll horizontal (AGENTS.md,
"Mobile UI invariant": semua kolom tetap ada, tanpa kartu dan tanpa kolom
yang disembunyikan).
"""
from __future__ import annotations

import html as _html

import pool_flow as pf
from links import external_links_html, pool_links_html

RESULT_KEY = "pool_flow_result"
BUTTON_LABEL = "SCAN BEST POOL"

TABLE_HEADERS = ["Token / pool", "TVL", "Fee tier", "Open pos.",
                 "In-range", "Volatility", "Fee/active TVL"]


def _filter_caption() -> str:
    return (f"Timeframe 12H · fee tier ≥ {pf.FLOW_FEE_TIER_MIN:g}% · open positions ≥ "
            f"{pf.FLOW_OPEN_POSITIONS_MIN} · TVL ≥ {pf.fmt_usd(pf.FLOW_TVL_MIN)} · "
            f"volatility ≥ {pf.FLOW_VOLATILITY_MIN:g}% · fee/active TVL ≥ "
            f"{pf.FLOW_FEE_ACTIVE_TVL_MIN:g}% · in-range ≥ {pf.FLOW_IN_RANGE_MIN:g}% "
            "dari open positions · urut in-range terbesar.")


def _render_scan_result(result: dict) -> None:
    import streamlit as st

    passing = result.get("passing") or []
    st.caption(
        f"Listing {result.get('listing_rows', 0)} baris · pool dievaluasi "
        f"{result.get('candidates', 0)} · lolos semua filter {len(passing)} · "
        f"dicatat {result.get('scanned_at', '')}"
        + (f" · {result['listing_errors']} halaman listing gagal"
           if result.get("listing_errors") else ""))
    if result.get("truncated"):
        st.warning(f"Listing belum lengkap: {pf.FLOW_MAX_PAGES} halaman masih penuh, "
                   "sebagian pool belum terambil.")
    if not passing:
        st.info("Tidak ada pool yang lolos semua filter.")
        return
    st.caption("Geser tabel ke kanan untuk melihat semua kolom.")
    st.markdown(_result_table_html(passing), unsafe_allow_html=True)


def _result_table_html(passing: list) -> str:
    """Tabel HTML satu baris per pool. Tanpa baris kosong agar markdown tidak rusak."""
    head = "".join(
        "<th style='text-align:left;padding:6px 8px;white-space:nowrap;"
        "border-bottom:1px solid rgba(128,128,128,.45)'>"
        f"{_html.escape(title)}</th>"
        for title in TABLE_HEADERS)
    body = []
    for row in passing:
        cells = [
            _cell_token_html(row),
            _html.escape(pf.fmt_usd(row["tvl"])),
            _html.escape(f"{row['fee_tier']:g}%"),
            _html.escape(f"{row['open_positions']:g}"),
            _html.escape(pf.fmt_pct(row["in_range"])),
            _html.escape(pf.fmt_pct(row["volatility"])),
            _html.escape(pf.fmt_pct(row["fee_active_tvl"])),
        ]
        tds = "".join(
            f"<td style='padding:6px 8px;vertical-align:top;border-bottom:1px solid "
            f"rgba(128,128,128,.2);white-space:{'normal' if i == 0 else 'nowrap'}'>{cell}</td>"
            for i, cell in enumerate(cells))
        body.append(f"<tr>{tds}</tr>")
    return (
        "<div style='overflow-x:auto;-webkit-overflow-scrolling:touch;"
        "border:1px solid rgba(128,128,128,.35);border-radius:8px'>"
        "<table style='border-collapse:collapse;width:100%;min-width:820px;"
        "font-size:13px;line-height:1.4'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _cell_token_html(row: dict) -> str:
    """Nama token + pool, CA lengkap, dan link. Dipakai di dalam sel tabel."""
    name = _html.escape(f"{row['symbol']} · {row['pool_name'] or row['pool'][:8]}")
    ca = _html.escape(row.get("mint") or "")
    parts = [f"<b style='font-size:14px'>{name}</b>"]
    if ca:
        parts.append(f"<code style='font-size:11px;word-break:break-all;"
                     f"white-space:normal'>{ca}</code>")
    links_html = " &nbsp; ".join(part for part in (
        external_links_html(row.get("mint") or ""),
        pool_links_html(row.get("pool") or ""),
    ) if part)
    if links_html:
        parts.append(f"<span style='font-size:12px'>{links_html}</span>")
    return "<br>".join(parts)


def render_pool_flow_page() -> None:
    import streamlit as st

    with st.container(border=True):
        st.markdown("## 🏆 Scan Best Pool")
        st.caption(_filter_caption())
        if st.button(BUTTON_LABEL, type="primary", key="pool_flow_scan",
                     use_container_width=True):
            with st.spinner("Memindai listing Meteora (12H)…"):
                result = pf.scan_pools()
            st.session_state[RESULT_KEY] = result
        result = st.session_state.get(RESULT_KEY)
        if not result:
            st.info("Belum di-scan. Tekan SCAN BEST POOL.")
        else:
            _render_scan_result(result)
