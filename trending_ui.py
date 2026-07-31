# -*- coding: utf-8 -*-
"""Shared renderer for the GMGN trending screener results.

Both the main dashboard (``app.py``) and the 🔎 Screener page call
:func:`render_trending` so the **exact same full detail** is shown in either
place — one table, one set of columns, one caption, one code path to fix.
"""
import re
import streamlit as st

from gmgn_screener import (FIT_OK, FIT_PRIME, FIT_WEAK, fit_color,
                           screen as gmgn_screen, screen_hrhr as gmgn_screen_hrhr)

#: layout of the result table (label, relative width)
COLUMNS = [("Fit", 0.75), ("Token", 1.5), ("MC", 1.1), ("Liq", 0.9),
           ("T10", 0.7), ("🧠 Smart", 0.85), ("Holders", 0.9),
           ("24h", 0.8), ("Age", 0.6), ("🕸️ Risk", 1.5), ("Notes", 2.2),
           ("", 1.25)]

CAPTION = (
    f"**Fit score (strict):** price base (22) + T10 concentration (20) + "
    f"liquidity (15) + smart money (14) + rug score (12) + volume sanity (9) "
    f"+ holders (4) + age (4), **minus penalties** for bundler/insider "
    f"pressure, entrapment & bot-degen flow, snipers still holding, rug risk "
    f"and thin liquidity. A broken pillar (already pumped >25%, T10 >25%, "
    f"liq <5% MC, <10 smart wallets, <1000 holders, <2d old…) caps the score "
    f"at {FIT_OK - 1}, and the cap drops further with each extra flaw, while "
    f"any hard red flag caps it at 40. Every pillar and gate is a "
    f"**continuous ramp**, so a token just short of a threshold loses a "
    f"point or two rather than falling off a cliff — a 9th vs 10th smart "
    f"wallet is a nudge, not a 20-point swing. So **≥{FIT_PRIME} 🟢 "
    f"PRIME is rare and means every pillar is clean**. "
    f"{FIT_OK}-{FIT_PRIME - 1} 🟡 OK = worth a manual check · "
    f"{FIT_WEAK}-{FIT_OK - 1} ⚪ WEAK · <{FIT_WEAK} POOR. "
    "🕸️ Risk column: bndl = bundler-traded supply · insd = dev/team hold · "
    "trap = entrapment traders · bot = bot-degen flow. "
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


def run_screen_hrhr(force: bool = False, key: str = "screener_hrhr_rows"):
    """Fetch + score + filter the HRHR list, caching the result in session state.

    Returns ``(rows, error)`` — *error* is a string when the fetch blew up.
    """
    if force or key not in st.session_state:
        with st.spinner("Fetching GMGN HRHR list…"):
            try:
                st.session_state[key] = gmgn_screen_hrhr()
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
        # 🕸️ live risk metrics (real GMGN fields: bdrr / dhr / etpr / bdr)
        bits = []
        for lab, val, warn in (("bndl", r.get("bundler_rate", 0), 0.15),
                               ("insd", r.get("insider_ratio", 0), 0.10),
                               ("trap", r.get("entrap_rate", 0), 0.30),
                               ("bot", r.get("botdegen_rate", 0), 0.30)):
            if val:
                c = "#ef4444" if val >= warn else "#94a3b8"
                bits.append(f"<span style='color:{c}'>{lab} "
                            f"{val * 100:.0f}%</span>")
        cc[9].markdown(
            "<span style='font-size:0.80rem'>" +
            (" · ".join(bits) if bits else "—") + "</span>",
            unsafe_allow_html=True)
        detail = r.get("notes") or r.get("wins") or "—"
        # Highlight dangerous notes with red styling — only extreme %
        parts = detail.split("; ")
        highlighted = []
        for p in parts:
            is_danger = False
            # Check for extreme percentages (≥100%) in the note
            for kw in ["already ran", "downtrend", "entrapment", "trap",
                       "pump", "dumped", "distribution", "rug",
                       "insider", "bundler", "bot-degen"]:
                if kw in p.lower():
                    nums = re.findall(r'[+-]?\d+', p)
                    extreme = any(int(n) >= 100 for n in nums)
                    if extreme or kw in ("rug", "insider", "bundler",
                                        "entrapment", "trap", "bot-degen",
                                        "dumped", "distribution"):
                        is_danger = True
                    break
            if is_danger:
                highlighted.append(
                    f"<span style='color:#ef4444;font-weight:700;'>"
                    f"{p}</span>")
            else:
                highlighted.append(p)
        cc[10].markdown(
            "<span style='font-size:0.80rem'>" +
            "; ".join(highlighted) + "</span>",
            unsafe_allow_html=True)
        with cc[11]:
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
                    # Determine source from key_prefix so the watchlist
                    # knows whether this token came from trending or HRHR.
                    _src = "hrhr" if "hrhr" in key_prefix else "trending"
                    add_to_watchlist(ca, symbol=r["symbol"] or "?",
                                     source=_src)
                    st.rerun()
        risk_banner(r)

    st.caption(CAPTION)
