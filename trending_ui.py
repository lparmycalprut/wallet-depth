# -*- coding: utf-8 -*-
"""Streamlit renderer listing GMGN (Trending / Degen) tanpa sinyal 12 jam."""
from __future__ import annotations

import html as _html

import streamlit as st

from gmgn_screener import (screen, screen_hrhr, screen_hrhr_h1,
                           screen_trending_h1)
from links import CVD_PAGE_PATH, external_links_html
from watchlist import (add_many_to_watchlist, add_to_watchlist, address_key,
                       load_watchlist, normalize_address,
                       watchlist_address_keys)

st.markdown("""
<style>
.trending-row {padding: 0.6rem 0; border-bottom: 1px solid #cbd5e1;}
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
        return f"{v:+.1f}%"
    except Exception:  # noqa: BLE001
        return "—"


def _token_identity_html(symbol, ca, row=None):
    """Render token name and CA prefix on clearly separated lines."""
    safe_symbol = _html.escape(str(symbol or "?").upper())
    safe_ca = _html.escape(str(ca or "")[:8])
    return (
        '<div class="trending-token">'
        f'<div class="trending-symbol">${safe_symbol}</div>'
        f'<div class="trending-mint">{safe_ca}…</div>'
        f'<div class="trending-links">{external_links_html(str(ca or ""))}</div>'
        '</div>'
    )


def merge_scan_rows(*groups) -> list[dict]:
    """Merge screener groups, preserving order and deduplicating addresses."""
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group or []:
            if not isinstance(raw, dict):
                continue
            ca = normalize_address(raw.get("ca") or raw.get("mint"))
            key = address_key(ca)
            if not key or key in seen:
                continue
            seen.add(key)
            row = dict(raw)
            row["ca"] = ca
            merged.append(row)
    return merged


def filter_watchlisted_rows(rows, watchlist: dict | None) -> list[dict]:
    """Hide watchlisted mints and duplicate scan rows on every render."""
    hidden = watchlist_address_keys(watchlist)
    return [row for row in merge_scan_rows(rows)
            if address_key(row.get("ca")) not in hidden]


def add_all_scan_results(rows, *, source: str) -> dict:
    """Model-facing helper kept separate from Streamlit for unit tests."""
    return add_many_to_watchlist(rows, source=source)


def _add_all_feedback(result: dict) -> str:
    added = int(result.get("added") or 0)
    skipped = int(result.get("skipped") or 0)
    duplicate = int(result.get("duplicates") or 0)
    message = (f"{added} token berhasil ditambahkan; "
               f"{skipped} dilewati karena sudah ada di watchlist.")
    if duplicate:
        message += f" {duplicate} duplikat hasil scan diabaikan."
    return message


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


def render_trending(rows, *, key_prefix="listing", source="trending",
                    watchlist=None):
    """Tabel listing GMGN, selalu menyembunyikan token watchlist."""
    rows = list(rows or [])
    current_watchlist = (load_watchlist() if watchlist is None else watchlist)
    visible_rows = filter_watchlisted_rows(rows, current_watchlist)

    if st.button("⭐ Add All to Watchlist",
                 key=f"add-all-{key_prefix}", use_container_width=True):
        if not rows:
            st.info("Hasil scan kosong; tidak ada token untuk ditambahkan.")
        else:
            result = add_all_scan_results(rows, source=source)
            feedback = _add_all_feedback(result)
            if result.get("added"):
                st.success(feedback)
                # Semua address valid yang terlihat sekarang sudah masuk model.
                visible_rows = []
            else:
                st.info(feedback)

    if not rows:
        st.info("Tidak ada token dari respons GMGN saat ini.")
        return
    if not visible_rows:
        st.info("Semua token hasil scan sudah ada di watchlist.")
        return

    header_cols = st.columns([1.8, 1.0, 1.0, 0.55, 0.55])
    header_titles = ["Token", "MC", "24h", "", ""]
    header_style = ("font-size:0.72rem;color:#000000;font-weight:700;"
                    "text-align:center;")
    for col, title in zip(header_cols, header_titles):
        col.markdown(f'<div style="{header_style}">{title}</div>',
                     unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:0.65rem;color:#64748b;margin:0.3rem 0;">'
        "🕸 GMGN listing · analisa dust/holder ada di Scan Meteora "
        "dan halaman Holder Analytic"
        "</div>",
        unsafe_allow_html=True)

    st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)

    for index, row in enumerate(visible_rows):
        ca = str(row.get("ca") or "")
        symbol = str(row.get("symbol") or "?").upper()
        mc = _compact(row.get("mc"))
        change_html = _color_change(row.get("change_24h"))

        columns = st.columns([1.8, 1.0, 1.0, 0.55, 0.55])
        columns[0].markdown(_token_identity_html(symbol, ca, row),
                            unsafe_allow_html=True)
        columns[1].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{mc}</div></div>',
            unsafe_allow_html=True)
        columns[2].markdown(
            f'<div class="trending-metric">'
            f'<div class="trending-metric-value">{change_html}</div>'
            f"</div>", unsafe_allow_html=True)
        if columns[3].button("📊", key=f"cvd-{key_prefix}-{index}",
                             help="Buka CVD", use_container_width=True):
            _navigate_to_cvd(ca)
        if columns[4].button("⭐", key=f"{key_prefix}-{index}",
                             help="Tambah ke Watchlist",
                             use_container_width=True):
            add_to_watchlist(row["ca"], row.get("symbol") or "?",
                             source=source)
            st.success(f"${symbol} ditambahkan")

        st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)
