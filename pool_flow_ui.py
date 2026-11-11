# -*- coding: utf-8 -*-
"""UI main app: 🏆 SCAN BEST POOL (net deposit) + watchlist + detail pool.

Logika ada di ``pool_flow.py``; modul ini hanya menampilkan hasil dan
menyimpan watchlist/riwayat ke ``pool_flow_state.json``.
"""
from __future__ import annotations

import html as _html

import pool_flow as pf
from links import external_links_html, pool_links_html

RESULT_KEY = "pool_flow_result"
BUTTON_LABEL = "SCAN BEST POOL"


def _filter_caption() -> str:
    return (f"Filter: fee tier ≥ {pf.FLOW_FEE_TIER_MIN:g}% · TVL ≥ "
            f"${pf.FLOW_TVL_MIN:,.0f} · fee/menit ≥ ${pf.FLOW_AVG_FEE_MIN:g} · "
            "net deposit POSITIF di H1, H4, H12, dan H24.")


def _watch_pools(state: dict) -> set:
    return {item["pool"] for item in state["watchlist"]}


def _render_scan_result(result: dict, state: dict) -> None:
    import streamlit as st

    passing = result.get("passing") or []
    st.caption(
        f"Listing {result.get('listing_rows', 0)} baris · kandidat setelah filter "
        f"dasar {result.get('candidates', 0)} · lolos semua filter "
        f"{len(passing)} · dicatat {result.get('scanned_at', '')}"
        + (f" · {result['listing_errors']} halaman listing gagal"
           if result.get("listing_errors") else ""))
    if not passing:
        st.info(f"Tidak ada pool yang lolos: harus fee tier ≥ {pf.FLOW_FEE_TIER_MIN:g}%, TVL ≥ $50K, "
                "fee/menit ≥ $5, dan net deposit positif di H1, H4, H12, dan H24.")
        return

    watched = _watch_pools(state)
    widths = [2.6, 1.2, 1, 1.2, 1.2, 1.2, 1.2, 1.2, 1.4]
    head = st.columns(widths)
    for col, title in zip(head, ["Token / pool", "TVL", "Fee tier", "Fee/menit",
                                 "Net H1", "Net H4", "Net H12", "Net H24", "Watchlist"]):
        col.markdown(f"**{title}**")
    for row in passing:
        cols = st.columns(widths)
        cols[0].markdown(_token_cell_html(row), unsafe_allow_html=True)
        cols[1].write(pf.fmt_usd(row["tvl"]))
        cols[2].write(f"{row['fee_tier']:g}%" if row["fee_tier"] is not None else "—")
        cols[3].write("—" if row["avg_fee"] is None else f"${row['avg_fee']:,.2f}/menit")
        for col, window in zip(cols[4:8], pf.FLOW_WINDOWS):
            col.write(pf.fmt_usd(row["nets"].get(window)))
        if row["pool"] in watched:
            cols[8].button("✔ Di watchlist", key=f"pf_in_{row['pool']}", disabled=True)
        elif cols[8].button("＋ Watchlist", key=f"pf_add_{row['pool']}"):
            st.session_state["pf_pending_add"] = row
            st.rerun()


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


def _apply_pending_add() -> None:
    import streamlit as st

    row = st.session_state.pop("pf_pending_add", None)
    if not row:
        return
    state = pf.load_state()
    if pf.watch_add(state, pool=row["pool"], mint=row["mint"],
                    symbol=row["symbol"], name=row["pool_name"]):
        pf.save_state(state)
        st.toast(f"{row['symbol']} ditambahkan ke watchlist")


def _refresh_watchlist(state: dict) -> None:
    for item in state["watchlist"]:
        nets = {}
        for window in pf.FLOW_WINDOWS:
            try:
                nets[window] = pf.net_of(
                    pf.pool_row_for_window(item["mint"], item["pool"], window))
            except Exception:  # noqa: BLE001 — satu window gagal = tidak terukur
                nets[window] = None
        pf.record_snapshot(state, item["pool"], nets)
    pf.save_state(state)


def _render_watchlist() -> None:
    import streamlit as st

    state = pf.load_state()
    st.markdown("### 👁️ Watchlist")
    st.caption("Alert watchlist (tiap 10 menit) membaca `pool_flow_state.json` di "
               "branch main. Perubahan watchlist di sini baru ikut alert setelah "
               "berkas itu di-commit.")
    if not state["watchlist"]:
        st.info("Watchlist kosong. Tambahkan pool dari hasil SCAN BEST POOL.")
        return
    if st.button("🔄 Perbarui net deposit watchlist", key="pf_refresh_watch"):
        with st.spinner("Mengambil net deposit watchlist…"):
            _refresh_watchlist(state)
        st.rerun()

    for item in state["watchlist"]:
        history = state["history"].get(item["pool"]) or []
        last = history[-1] if history else {}
        h1, h4 = last.get("net_1h"), last.get("net_4h")
        flag = ""
        if h1 is not None and h4 is not None and h1 + h4 < 0:
            flag = " ⚠️ H1+H4 negatif"
        title = (f"{item['symbol']} · H1 {pf.fmt_usd(h1)} · H4 {pf.fmt_usd(h4)} · "
                 f"H12 {pf.fmt_usd(last.get('net_12h'))} · H24 "
                 f"{pf.fmt_usd(last.get('net_24h'))}{flag}")
        with st.expander(title):
            st.caption(f"Pool `{item['pool']}` · dicatat {last.get('ts', 'belum ada')}")
            st.markdown(_token_cell_html({"symbol": item["symbol"], "pool_name": item.get("name", ""),
                                           "pool": item["pool"], "mint": item["mint"]}),
                        unsafe_allow_html=True)
            _render_detail(item, history)
            if st.button("🗑️ Hapus dari watchlist", key=f"pf_rm_{item['pool']}"):
                state = pf.load_state()
                pf.watch_remove(state, item["pool"])
                pf.save_state(state)
                st.rerun()

    if state["alerts"]:
        st.markdown("**Riwayat alert terakhir**")
        for alert in reversed(state["alerts"][-5:]):
            st.caption(f"#{alert['no']} · {alert['kind']} · {alert['at']} · "
                       f"{len(alert['pools'])} pool")


def _render_detail(item: dict, history: list) -> None:
    import pandas as pd
    import streamlit as st

    if not history:
        st.info("Belum ada riwayat. Tekan 🔄 Perbarui atau SCAN BEST POOL.")
        return
    frame = pd.DataFrame(history)
    frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce")
    frame = frame.dropna(subset=["ts"]).set_index("ts")
    columns = [c for c in ("net_1h", "net_4h", "net_12h", "net_24h") if c in frame]
    st.line_chart(frame[columns].astype(float), height=220)
    negative = int(((frame.get("net_1h", 0) + frame.get("net_4h", 0)) < 0).sum())
    st.caption(f"{len(frame)} catatan · H1+H4 negatif di {negative} catatan · "
               f"net terakhir H24 {pf.fmt_usd(history[-1].get('net_24h'))}")
    st.dataframe(frame[columns].tail(20).round(0), use_container_width=True)


def render_pool_flow_page() -> None:
    import streamlit as st

    _apply_pending_add()
    state = pf.load_state()
    with st.container(border=True):
        st.markdown("## 🏆 Scan Best Pool")
        st.caption(_filter_caption())
        if st.button(BUTTON_LABEL, type="primary", key="pool_flow_scan",
                     use_container_width=True):
            with st.spinner("Memindai listing Meteora dan net deposit per window…"):
                result = pf.scan_candidates()
            st.session_state[RESULT_KEY] = result
            state = pf.load_state()
            pf.record_scan(state, result["results"], ts=result["scanned_at"])
            pf.save_state(state)
            st.rerun()
        result = st.session_state.get(RESULT_KEY)
        if not result:
            st.info("Belum di-scan. Tekan SCAN BEST POOL.")
        else:
            _render_scan_result(result, state)

    with st.container(border=True):
        _render_watchlist()
