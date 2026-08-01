# -*- coding: utf-8 -*-
"""Shared renderer for the GMGN trending screener results.

Both the main dashboard (``app.py``) and the 🔎 Screener page call
:func:`render_trending` so the **exact same full detail** is shown in either
place — one table, one set of columns, one caption, one code path to fix.
"""
import re
import requests
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

from gmgn_screener import (FIT_OK, FIT_PRIME, FIT_WEAK, fit_color,
                           screen as gmgn_screen, screen_hrhr as gmgn_screen_hrhr)

#: layout of the result table (label, relative width)
COLUMNS = [("Fit", 0.75), ("Token", 1.5), ("MC", 1.1), ("Liq", 0.9),
           ("Top 10", 0.7), ("Holders", 0.9), ("24h", 0.8), ("ATH", 0.7),
           ("AvgCost", 0.8), ("Age", 0.6), ("🕸️ Risk", 1.5), ("Notes", 2.2),
           ("", 1.25)]

CAPTION = (
    f"**Fit struktural (strict):** Top-10 concentration (30) + liquidity/MC "
    f"(30) + rug score (25) + volume/MC sanity (15), **minus penalties** "
    f"for bundler/insider pressure, entrapment & bot-degen flow, snipers "
    f"still holding, rug risk, concentration, dan thin liquidity. Harga "
    f"24h/1h dan umur token hanya konteks tampilan, bukan input Fit. "
    f"Smart-money dan KOL tidak dipakai atau ditampilkan. Holder count "
    f"tidak mendapat poin, "
    f"tetapi holder base <1.000 tetap menjadi safety gate. Broken structural "
    f"gate (Top 10 >25%, liq <5% MC, rug >0.45, holder <1.000, atau pressure "
    f"wallet berbahaya) membatasi grade; hard red flag membatasi Fit ke 40. "
    f"Setiap pillar dan gate memakai **continuous ramp**, bukan threshold "
    f"yang melompat. Jadi **≥{FIT_PRIME} 🟢 PRIME hanya untuk struktur yang "
    f"bersih**. "
    f"{FIT_OK}-{FIT_PRIME - 1} 🟡 OK = worth a manual check · "
    f"{FIT_WEAK}-{FIT_OK - 1} ⚪ WEAK · <{FIT_WEAK} POOR. "
    "🕸️ Risk column: bndl = bundler-traded supply · insd = dev/team hold · "
    "bndl/insd <15% = 🟢 hijau · bndl/insd >=15% = 🔴 merah · "
    "trap = entrapment traders · bot = bot-degen flow. "
    "Kolom **ATH** = jarak harga saat ini dari ATH (display-only, "
    "hijau bila retrace ≥90%). Kolom **AvgCost** = % harga saat ini vs "
    "rata-rata harga beli holder dari GMGN (`avg_cost_change`; negatif = "
    "holder rata-rata rugi, merah ≤ -50%, oranye <0%, hijau ≥0%; "
    "— = data belum tersedia, bukan 0; "
    "display-only, tidak menambah Fit). HRHR **Down dari ATH** dan pola "
    "candle H4 hanya konteks visual; keduanya "
    "tidak menambah Fit. Source: GMGN internal API (unofficial, may break "
    "anytime). Always run a "
    "full **Analyze** before acting — this is a filter, not a signal."
)


def _clear_ctx_cache():
    """Drop the cached ATH / avg-cost context so a rescan re-fetches it."""
    try:
        from token_context import clear_cache
        clear_cache()
    except Exception:                                    # noqa: BLE001
        pass


def run_screen(force: bool = False, key: str = "screener_rows"):
    """Fetch + score the trending list, caching the result in session state.

    Returns ``(rows, error)`` — *error* is a string when the fetch blew up.
    """
    if force or key not in st.session_state:
        if force:
            _clear_ctx_cache()
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
        if force:
            _clear_ctx_cache()
        with st.spinner("Fetching GMGN HRHR list…"):
            try:
                st.session_state[key] = gmgn_screen_hrhr()
                st.session_state[key + "_err"] = ""
            except Exception as exc:                     # noqa: BLE001
                st.session_state[key] = []
                st.session_state[key + "_err"] = str(exc)
    return (st.session_state.get(key) or [],
            st.session_state.get(key + "_err") or "")


def _resolve_pair(ca: str):
    """Return the best DexScreener pair address for a token CA, or None."""
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
            timeout=10)
        pairs = (r.json() or {}).get("pairs") or []
        if not pairs:
            return None
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                   reverse=True)
        return pairs[0].get("pairAddress")
    except Exception:
        return None


def _fetch_h4_and_detect(ca: str) -> dict:
    """Resolve pair -> fetch 12 H4 candles -> detect patterns.

    Returns a dict of pattern name -> count, or empty dict on failure.
    """
    from cvd import fetch_candles, detect_candle_patterns
    pair = _resolve_pair(ca)
    if not pair:
        return {}
    candles = fetch_candles(pair, timeframe="hour", aggregate=4,
                            limit=12, timeout=8)
    if not candles:
        return {}
    return detect_candle_patterns(candles)


def enrich_hrhr_with_patterns(rows: list) -> list:
    """Enrich HRHR screener rows with H4 candle pattern detection.

    For each token, resolves its DexScreener pair, fetches the last
    12 H4 candles (48h), and detects small-body reversal / indecision
    patterns (Doji, Hammer, Inverted Hammer, Spinning Top, etc.).

    Adds a ``candle_patterns`` field (dict[str, int]) to each row.
    Rows that fail to resolve are left with an empty dict.
    """
    if not rows:
        return rows

    pattern_cache_key = "hrhr_candle_patterns"
    cached = st.session_state.get(pattern_cache_key, {})

    # Figure out which CAs need fresh data
    cas_to_fetch = [r["ca"] for r in rows if r.get("ca")
                    and r["ca"] not in cached]

    if cas_to_fetch:
        with st.spinner("🕯️ Scanning H4 candle patterns…"):
            workers = min(6, len(cas_to_fetch))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_fetch_h4_and_detect, ca): ca
                           for ca in cas_to_fetch}
                for fut in as_completed(futures):
                    ca = futures[fut]
                    try:
                        cached[ca] = fut.result()
                    except Exception:
                        cached[ca] = {}
        st.session_state[pattern_cache_key] = cached

    # Attach pattern data to each row
    for r in rows:
        r["candle_patterns"] = cached.get(r.get("ca", ""), {})

    return rows


def _format_candle_patterns(patterns: dict) -> str:
    """Format candle pattern counts into a green-glowing HTML string."""
    from cvd import PATTERN_EMOJI
    if not patterns:
        return ""
    parts = []
    for name, count in patterns.items():
        emoji = PATTERN_EMOJI.get(name, "🕯️")
        parts.append(f"{emoji} {name} {count}x")
    text = "; ".join(parts)
    return (
        f"<span style='color:#22c55e;font-weight:700;"
        f"text-shadow:0 0 6px #22c55e88,0 0 12px #22c55e44;"
        f"filter:brightness(1.2);'>{text}</span>"
    )


def _glowing_note(text: str, color: str) -> str:
    """Render one important screener note with a high-contrast glow."""
    return (
        f"<span style='color:{color};font-weight:800;"
        f"text-shadow:0 0 6px {color},0 0 14px {color}99;"
        f"filter:brightness(1.35);'>{text}</span>"
    )


def _risk_bit_color(val: float, thresh: float = 0.15) -> str:
    """Green below threshold, red at or above."""
    return "#22c55e" if val < thresh else "#ef4444"


def _format_note_part(part: str, row: dict = None) -> str:
    """Apply semantic emphasis to one semicolon-separated screener note."""
    # The scoring gate emits this phrase from Top-10 >=25%. It is an
    # explicit concentration warning, so make it impossible to miss in
    # the notes. Matches the new "Top 10" phrasing and the legacy "T10".
    if re.search(r"\b(?:T10|Top\s*10)\s+\d+(?:\.\d+)?%\s+"
                 r"too\s+concentrated\b",
                 part, re.IGNORECASE):
        return _glowing_note(part, "#ef4444")

    # HRHR candidates at least 90% below ATH are visually highlighted as a
    # deep-retrace setup. This is display-only and does not add Fit points.
    ath_match = re.search(
        r"\bDown\s+(\d+(?:\.\d+)?)%\s+dari\s+ATH\b",
        part, re.IGNORECASE)
    if ath_match and float(ath_match.group(1)) >= 90.0:
        return _glowing_note(part, "#22c55e")

    # Insider / bundler pressure glow based on max of the two ratios.
    if row is not None and "insider/bundler pressure" in part.lower():
        insider = row.get("insider_ratio") or row.get("dhr") or 0
        bundler = row.get("bundler_rate") or row.get("bdrr") or 0
        max_val = max(float(insider), float(bundler))
        if max_val < 0.15:
            return _glowing_note(part, "#22c55e")
        else:
            return _glowing_note(part, "#ef4444")

    is_danger = False
    # Check for extreme percentages (>=100%) in generic risk notes.
    for keyword in ("already ran", "downtrend", "entrapment", "trap",
                    "pump", "dumped", "distribution", "rug", "insider",
                    "bundler", "bot-degen"):
        if keyword in part.lower():
            numbers = re.findall(r"[+-]?\d+", part)
            extreme = any(int(number) >= 100 for number in numbers)
            if extreme or keyword in (
                    "rug", "insider", "bundler", "entrapment", "trap",
                    "bot-degen", "dumped", "distribution"):
                is_danger = True
            break
    if is_danger:
        return f"<span style='color:#ef4444;font-weight:700;'>{part}</span>"
    return part


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
        f"**{len(rows)} tokens** · sorted by structural Fit · "
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
        ca = r["ca"]
        gmgn_link = (f"<a href='https://gmgn.ai/sol/token/{ca}' target='_blank' "
                     f"style='font-size:0.55rem;color:#f59e0b;text-decoration:none;"
                     f"margin-left:3px;'>↗GMGN</a>")
        dex_link = (f"<a href='https://dexscreener.com/solana/{ca}' target='_blank' "
                    f"style='font-size:0.55rem;color:#3b82f6;text-decoration:none;"
                    f"margin-left:3px;'>↗DEX</a>")
        cc[1].markdown(
            f"**{r['symbol'] or '?'}**  \n<span style='font-size:0.62rem;"
            f"opacity:0.6'>{(r.get('name') or '')[:18]}</span>"
            f"<span style='font-size:0.55rem;opacity:0.8'>{gmgn_link}"
            f"{dex_link}</span>",
            unsafe_allow_html=True)
        cc[2].write(f"${r['mc']:,.0f}")
        cc[3].write(f"{r['liq_pct']}% MC")
        if r["t10_pct"] >= 25:
            cc[4].markdown(
                _glowing_note(f"{r['t10_pct']}%", "#ef4444"),
                unsafe_allow_html=True)
        else:
            cc[4].write(f"{r['t10_pct']}%")
        cc[5].write(f"{r['holders']:,}")
        chg = r["chg24"]
        cc[6].markdown(
            f"<span style='color:{'#22c55e' if chg >= 0 else '#ef4444'}'>"
            f"{chg:+.0f}%</span>", unsafe_allow_html=True)
        # ATH column: how far the CURRENT price is below ATH (display-only).
        # Deep retrace (>=90%) glows green — same rule as the notes.
        _down = r.get("down_ath")
        if _down is not None:
            if _down >= 90.0:
                cc[7].markdown(_glowing_note(f"-{_down:.0f}%", "#22c55e"),
                               unsafe_allow_html=True)
            else:
                cc[7].write(f"-{_down:.0f}%")
        else:
            cc[7].write("—")
        # AvgCost column: current price vs GMGN holder average cost %
        # (display-only). Red <= -50% (deeply underwater), orange < 0%,
        # green >= 0% (holders on average in profit).
        _avg = r.get("avg_cost")
        if _avg is not None:
            _avg_col = ("#ef4444" if _avg <= -50.0
                        else ("#f59e0b" if _avg < 0.0 else "#22c55e"))
            cc[8].markdown(
                f"<span style='color:{_avg_col};font-weight:700'>"
                f"{_avg:+.0f}%</span>", unsafe_allow_html=True)
        else:
            cc[8].write("—")
        cc[9].write(f"{r['age_d']}d")
        # 🕸️ live risk metrics (real GMGN fields: bdrr / dhr / etpr / bdr)
        bits = []
        for lab, val, thresh in (("bndl", r.get("bundler_rate", 0), 0.15),
                                 ("insd", r.get("insider_ratio", 0), 0.15),
                                 ("trap", r.get("entrap_rate", 0), 0.30),
                                 ("bot", r.get("botdegen_rate", 0), 0.30)):
            if val is not None and val > 0:
                c = _risk_bit_color(val, thresh)
                bits.append(f"<span style='color:{c}'>{lab} "
                            f"{val * 100:.0f}%</span>")
        cc[10].markdown(
            "<span style='font-size:0.80rem'>" +
            (" · ".join(bits) if bits else "—") + "</span>",
            unsafe_allow_html=True)
        detail = r.get("notes") or r.get("wins") or "—"
        parts = detail.split("; ")
        highlighted = [_format_note_part(part, r) for part in parts]
        # Prepend H4 candle pattern info (green glowing) for degen rows
        _cpattern_html = _format_candle_patterns(r.get("candle_patterns", {}))
        _notes_html = "<span style='font-size:0.80rem'>" + "; ".join(highlighted) + "</span>"
        if _cpattern_html:
            _notes_html = (
                "<span style='font-size:0.80rem;display:block;"
                "margin-bottom:2px;'>" + _cpattern_html + "</span>"
                + _notes_html)
        cc[11].markdown(_notes_html, unsafe_allow_html=True)
        with cc[12]:
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
                                     source=_src,
                                     down_ath=r.get("down_ath"),
                                     avg_cost=r.get("avg_cost"))
                    st.rerun()
        risk_banner(r)

    st.caption(CAPTION)
