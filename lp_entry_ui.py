# -*- coding: utf-8 -*-
"""UI Streamlit untuk halaman **🧭 Cek Entri LP**.

Logika (ambil data, analisis, verdict) ada di ``tools/lp_entry_check``; modul
ini hanya menampilkan hasilnya. Halaman ini terpisah dari 🏆 Scan Best Pool dan
🌊 Sweep: tidak mengubah watchlist atau data scan apa pun.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_TOOL_DIR = Path(__file__).resolve().parent / "tools" / "lp_entry_check"
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

import lp_entry_check as lec  # noqa: E402

INPUT_KEY = "lp_entry_input"
RESULT_KEY = "lp_entry_result"
CACHE_TTL_SEC = 60

_STATUS_TEXT = {"ok": "✔ lolos", "fail": "✘ gagal", "unknown": "? tidak terukur"}

# Level tampilan per verdict: "success" | "warning" | "error" | "info".
_VERDICT_LEVEL = {
    lec.VERDICT_GOOD: "success",
    lec.VERDICT_WAIT: "warning",
    lec.VERDICT_BAD_FEE: "error",
    lec.VERDICT_AVOID: "error",
    lec.VERDICT_DATA: "info",
    lec.VERDICT_NO_POOL: "info",
}


def verdict_level(verdict: str) -> str:
    """Level tampilan untuk verdict; tidak dikenal → ``info``."""
    return _VERDICT_LEVEL.get(verdict, "info")


@st.cache_data(ttl=CACHE_TTL_SEC, show_spinner=False)
def _cached_run(ca: str) -> dict:
    """Ambil & analisis sekali per CA selama ``CACHE_TTL_SEC`` detik.

    Error tidak di-cache oleh Streamlit (exception dilempar ke pemanggil).
    """
    return lec.run(ca)


def render_lp_entry_page() -> None:
    st.markdown("## 🧭 Cek Entri LP (manual)")
    st.caption(
        "Tempel contract address (CA) Solana. Tool mengambil data pool Meteora "
        "(1H, 4H, 12H, 24H) dan memberi verdict: bagus untuk entri LP atau belum. "
        "Hasilnya hanya heuristik, bukan saran investasi. Halaman ini tidak "
        "menyimpan apa pun dan tidak mengubah watchlist.")

    with st.form("lp_entry_form", clear_on_submit=False):
        raw = st.text_input("Contract address (CA) Solana", key=INPUT_KEY,
                            placeholder="contoh: 9VZerdNL1x6EjetDqRnh5bYcdmk1y8sLAGs1ybzGpump")
        submitted = st.form_submit_button("🧭 Cek sekarang", type="primary")

    if submitted:
        try:
            ca = lec.valid_ca(raw)
        except ValueError as exc:
            st.session_state[RESULT_KEY] = {"error": str(exc)}
        else:
            with st.spinner(f"Mengambil data pool {ca[:8]}…"):
                try:
                    st.session_state[RESULT_KEY] = {"report": _cached_run(ca)}
                except Exception as exc:  # noqa: BLE001 - tampilkan ke pengguna
                    st.session_state[RESULT_KEY] = {"error": str(exc)}

    result = st.session_state.get(RESULT_KEY)
    if not result:
        st.info("Belum ada hasil. Masukkan CA lalu tekan **Cek sekarang**.")
        return
    if result.get("error"):
        st.error(result["error"])
        return
    _render_report(result["report"])


def _render_report(report: dict) -> None:
    level = verdict_level(report["verdict"])
    message = f"**VERDICT: {report['verdict']}** — {report['reason']}"
    getattr(st, level)(message)

    if report.get("pool_address"):
        tvl = report.get("tvl")
        age = report.get("pool_age_hours")
        cols = st.columns(3)
        cols[0].metric("Token", report.get("symbol") or "?")
        cols[1].metric("TVL", f"${tvl:,.0f}".replace(",", ".") if tvl is not None else "—")
        cols[2].metric("Umur pool", f"{age:.1f} jam" if age is not None else "—")
        st.caption(f"Pool {report.get('pool_name') or '?'} · {report['pool_address']}")

        changes = report.get("changes") or {}
        fees = report.get("fees") or {}
        st.markdown("**Perubahan harga & fee/TVL per window**")
        st.table({
            "Window": [w.upper() for w in lec.WINDOWS],
            "Perubahan harga": [_fmt_pct(changes.get(w), sign=True) for w in lec.WINDOWS],
            "Fee/TVL": [_fmt_pct(fees.get(w), sign=False) for w in lec.WINDOWS],
        })

    if report.get("checks"):
        st.markdown("**Cek**")
        st.table([
            {"Cek": c["name"],
             "Status": _STATUS_TEXT.get(c["status"], c["status"]),
             "Detail": c["detail"]}
            for c in report["checks"]
        ])

    for warning in report.get("warnings") or []:
        st.caption(f"Catatan: {warning}")
    st.caption("Ambang ada di konstanta `tools/lp_entry_check/lp_entry_check.py`.")


def _fmt_pct(value, *, sign: bool) -> str:
    if value is None:
        return "—"
    text = f"{value:+.2f}%" if sign else f"{value:.2f}%"
    return text.replace(".", ",")
