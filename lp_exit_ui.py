# -*- coding: utf-8 -*-
"""UI Streamlit untuk halaman **🚪 Cek LP Keluar**.

Logika (ambil data, analisis, verdict) ada di ``tools/lp_exit_check``; modul ini
hanya menampilkan hasilnya. Halaman ini terpisah dari 🏆 Best Pool, 🌊 Sweep, dan
🧭 Cek Entri LP: tidak menyimpan apa pun dan tidak mengubah watchlist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_TOOL_DIR = Path(__file__).resolve().parent / "tools" / "lp_exit_check"
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

import lp_exit_check as lxc  # noqa: E402

INPUT_KEY = "lp_exit_input"
RESULT_KEY = "lp_exit_result"
CACHE_TTL_SEC = 60

# Level tampilan per verdict: "success" | "warning" | "error" | "info".
_VERDICT_LEVEL = {
    lxc.VERDICT_NONE: "success",
    lxc.VERDICT_EARLIER: "warning",
    lxc.VERDICT_RECENT: "error",
    lxc.VERDICT_DATA: "info",
    lxc.VERDICT_NO_POOL: "info",
}


def verdict_level(verdict: str) -> str:
    """Level tampilan untuk verdict; tidak dikenal → ``info``."""
    return _VERDICT_LEVEL.get(verdict, "info")


@st.cache_data(ttl=CACHE_TTL_SEC, show_spinner=False)
def _cached_run(ca: str) -> dict:
    """Ambil & analisis sekali per CA selama ``CACHE_TTL_SEC`` detik.

    Error tidak di-cache oleh Streamlit (exception dilempar ke pemanggil).
    """
    return lxc.run(ca)


def render_lp_exit_page() -> None:
    st.markdown("## 🚪 Cek LP Keluar (manual)")
    st.caption(
        "Tempel contract address (CA) Solana. Tool mengecek apakah likuiditas pool "
        "Meteora sedang ditarik: net deposit negatif berarti total withdraw lebih besar "
        "dari total deposit. Hasilnya hanya sinyal, bukan saran investasi. Halaman ini "
        "tidak menyimpan apa pun dan tidak mengubah watchlist.")

    with st.form("lp_exit_form", clear_on_submit=False):
        raw = st.text_input("Contract address (CA) Solana", key=INPUT_KEY,
                            placeholder="contoh: 9VZerdNL1x6EjetDqRnh5bYcdmk1y8sLAGs1ybzGpump")
        submitted = st.form_submit_button("🚪 Cek sekarang", type="primary")

    if submitted:
        try:
            ca = lxc.valid_ca(raw)
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
    getattr(st, level)(f"**VERDICT: {report['verdict']}** — {report['reason']}")

    if report.get("pool_address"):
        st.metric("Token", report.get("symbol") or "?")
        st.caption(f"Pool {report.get('pool_name') or '?'} · {report['pool_address']}")

        windows = report.get("windows") or {}
        st.markdown("**Deposit, withdraw, dan net per window**")
        st.table({
            "Window": [w.upper() for w in lxc.WINDOWS],
            "Deposit": [_fmt_money(_get(windows, w, "deposits")) for w in lxc.WINDOWS],
            "Withdraw": [_fmt_money(_get(windows, w, "withdraws")) for w in lxc.WINDOWS],
            "Net deposit": [_fmt_money(_get(windows, w, "net")) for w in lxc.WINDOWS],
            "Status": [_status(windows.get(w)) for w in lxc.WINDOWS],
        })

    for warning in report.get("warnings") or []:
        st.caption(f"Catatan: {warning}")
    st.caption("Sinyal ini memakai `total_deposits`, `total_withdraws`, dan `net_deposits` "
               "dari Meteora per window. Net negatif = withdraw lebih besar dari deposit.")


def _get(windows: dict, window: str, key: str):
    metrics = windows.get(window)
    return metrics.get(key) if metrics else None


def _status(metrics) -> str:
    if metrics is None:
        return "tidak terukur"
    return "KELUAR" if metrics["net"] < 0 else "ok"


def _fmt_money(value) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}".replace(",", ".")
