# -*- coding: utf-8 -*-
"""Shared renderer for the GMGN trending screener results.

Both the main dashboard (``app.py``) and the 🔎 Screener page call
:func:`render_trending` so the **exact same full detail** is shown in either
place — one table, one set of columns, one caption, one code path to fix.
"""
import streamlit as st

from gmgn_screener import (FIT_OK, FIT_PRIME, FIT_WEAK, fit_color,
                           screen as gmgn_screen)

#: layout of the result table (label, relative width)
COLUMNS = [("Fit", 0.75), ("Token", 1.6), ("MC", 1.15), ("Liq", 1.0),
           ("T10", 0.75), ("🧠 Smart", 0.85), ("Holders", 0.95),
           ("24h", 0.85), ("Age", 0.7), ("Notes", 2.6), ("", 1.3)]

CAPTION = (
    f"**Fit score (strict):** price base (22) + T10 concentration (20) + "
    f"liquidity (15) + smart money (14) + rug score (12) + volume sanity (9) "
    f"+ holders (4) + age (4), **minus penalties** for insider/bundler "
    f"pressure, rug risk and thin liquidity. A single broken pillar "
    f"(already pumped >25%, T10 >25%, liq <5% MC, <10 smart wallets, "
    f"<1000 holders, <2d old…) caps the score at {FIT_OK - 1}, and any hard "
    f"red flag caps it at 40 — so **≥{FIT_PRIME} 🟢 PRIME is rare and means "
    f"every pillar is clean**. {FIT_OK}-{FIT_PRIME - 1} 🟡 OK = worth a "
    f"manual check · {FIT_WEAK}-{FIT_OK - 1} ⚪ WEAK · <{FIT_WEAK} POOR. "
    "Source: GMGN internal API (unofficial, may break anytime). Always run a "
    "full **Analyze** before acting — this is a filter, not a signal."
)


def run_screen(force: bool = False, key: str = "screener_rows"):
    """Fetch + score the trending list, caching the result in session state.

    Returns ``(rows, error)`` — *error* is a string when the fetch blew up.
    """
    if force or key not in st.session_state:
        with st.spinner("Fetching GMGN trending…"):
            try:
                st.session_state[key] = gmgn_screen()
                st.session_state[key + "_err"] = ""
            except Exception as exc:                     # noqa: BLE001
                st.session_state[key] = []
                st.session_state[key + "_err"] = str(exc)
    return (st.session_state.get(key) or [],
            st.session_state.get(key + "_err") or "")


def risk_banner(row: dict, big: bool = False) -> None:
    """Red warning box for a high-risk token."""
    if not row.get("high_risk"):
        return
    reasons = " • ".join(row.get("risk_reasons") or [])
    pad, size = ("14px 20px", "1.05rem") if big else ("6px 10px", "0.85rem")
    title = ("🚨 <b>TOKEN SANGAT BERISIKO</b> 🚨<br>" if big
             else "🚨 HIGH RISK: ")
    st.markdown(
        f"<div style='background:#7f1d1d;border:2px solid #ef4444;"
        f"border-radius:10px;padding:{pad};margin:6px 0;color:#fecaca;"
        f"font-size:{size};font-weight:800;"
        f"{'text-align:center;' if big else ''}'>{title}"
        f"<span style='font-size:0.9em;font-weight:700;'>{reasons}</span>"
        f"</div>", unsafe_allow_html=True)


def render_trending(rows, *, key_prefix: str = "scr", show_watch: bool = True,
                    on_analyze=None) -> None:
    """Render the full scored trending table.

    ``on_analyze`` — optional ``callable(ca)`` used for the Analyze button
    (the main page loads the CA into its own input); when ``None`` a link to
    the main page with ``?ca=`` is used instead.
    """
    if not rows:
        return
    try:
        from watchlist import load_watchlist, add_to_watchlist
        wl = load_watchlist()
    except Exception:
        wl, add_to_watchlist = {}, None

    n_prime = sum(1 for r in rows if r["fit"] >= FIT_PRIME
                  and not r.get("high_risk"))
    n_risk = sum(1 for r in rows if r.get("high_risk"))
    st.markdown(
        f"**{len(rows)} tokens** · sorted by accumulation-fit · "
        f"<span style='color:#22c55e'>{n_prime} PRIME</span> · "
        f"<span style='color:#ef4444'>{n_risk} high-risk</span>",
        unsafe_allow_html=True)

    widths = [w for _, w in COLUMNS]
    hdr = st.columns(widths)
    for col, (label, _) in zip(hdr, COLUMNS):
        col.markdown(f"**{label}**")

    for r in rows:
        ca = r["ca"]
        fit, high_risk = r["fit"], r.get("high_risk")
        colr = fit_color(fit, high_risk)
        cc = st.columns(widths)
        cc[0].markdown(
            f"<span style='color:{colr};font-weight:800;font-size:1.15rem'>"
            f"{fit}</span><br><span style='color:{colr};font-size:0.6rem;"
            f"font-weight:700'>{r.get('grade', '')}</span>",
            unsafe_allow_html=True)
        cc[1].markdown(
            f"**{r['symbol'] or '?'}**  \n<span style='font-size:0.62rem;"
            f"opacity:0.6'>{(r.get('name') or '')[:18]}</span>",
            unsafe_allow_html=True)
        cc[2].write(f"${r['mc']:,.0f}")
        cc[3].write(f"{r['liq_pct']}% MC")
        cc[4].write(f"{r['t10_pct']}%")
        cc[5].write(f"{r['smart']}")
        cc[6].write(f"{r['holders']:,}")
        chg = r["chg24"]
        cc[7].markdown(
            f"<span style='color:{'#22c55e' if chg >= 0 else '#ef4444'}'>"
            f"{chg:+.0f}%</span>", unsafe_allow_html=True)
        cc[8].write(f"{r['age_d']}d")
        detail = r.get("notes") or r.get("wins") or "—"
        cc[9].caption(detail)
        with cc[10]:
            if on_analyze is not None:
                if st.button("Analyze →", key=f"{key_prefix}_an_{ca}",
                             use_container_width=True):
                    on_analyze(ca)
            else:
                st.link_button("Analyze →", f"/?ca={ca}",
                               use_container_width=True)
            if show_watch and add_to_watchlist is not None:
                if ca in wl:
                    st.caption("⭐ watched")
                elif st.button("⭐ watch", key=f"{key_prefix}_wl_{ca}",
                               use_container_width=True):
                    add_to_watchlist(ca, symbol=r["symbol"] or "?")
                    st.rerun()
        risk_banner(r)

    st.caption(CAPTION)
