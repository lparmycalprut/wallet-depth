# -*- coding: utf-8 -*-
"""UI main app: 🏆 SCAN BEST POOL (timeframe 12H).

Logika ada di ``pool_flow.py``; modul ini hanya menampilkan hasil scan.
Scan tidak menulis berkas apa pun.
"""
from __future__ import annotations

import html as _html

import pool_flow as pf
from links import external_links_html, pool_links_html

RESULT_KEY = "pool_flow_result"
BUTTON_LABEL = "SCAN BEST POOL"


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
        st.warning("Listing terpotong: masih ada pool yang belum terambil.")
    if not passing:
        st.info("Tidak ada pool yang lolos semua filter.")
        return

    widths = [3, 1.2, 1, 1.1, 1.1, 1.1, 1.4]
    head = st.columns(widths)
    for col, title in zip(head, ["Token / pool", "TVL", "Fee tier", "Open pos.",
                                 "In-range", "Volatility", "Fee/active TVL"]):
        col.markdown(f"**{title}**")
    for row in passing:
        cols = st.columns(widths)
        cols[0].markdown(_token_cell_html(row), unsafe_allow_html=True)
        cols[1].write(pf.fmt_usd(row["tvl"]))
        cols[2].write(f"{row['fee_tier']:g}%")
        cols[3].write(f"{row['open_positions']:g}")
        cols[4].write(pf.fmt_pct(row["in_range"]))
        cols[5].write(pf.fmt_pct(row["volatility"]))
        cols[6].write(pf.fmt_pct(row["fee_active_tvl"]))


def _token_cell_html(row: dict) -> str:
    """Nama token + pool, lalu CA lengkap dan link di bawahnya."""
    name = _html.escape(f"{row['symbol']} · {row['pool_name'] or row['pool'][:8]}")
    ca = _html.escape(row.get("mint") or "")
    lines = [f"**{name}**"]
    if ca:
        lines.append(f"<code style='word-break:break-all'>{ca}</code>")
    links_html = " &nbsp; ".join(part for part in (
        external_links_html(row.get("mint") or ""),
        pool_links_html(row.get("pool") or ""),
    ) if part)
    if links_html:
        lines.append(links_html)
    return "  \n".join(lines)


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
