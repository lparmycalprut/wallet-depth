# -*- coding: utf-8 -*-
"""Shared presentation helpers for the remaining Best Pool dashboard."""
from __future__ import annotations

import html

import streamlit as st


def render_styles() -> None:
    """Install the dashboard CSS, including the mobile Best Pool table.

    Best Pool deliberately remains a table on small screens.  Every header and
    value column keeps a compact fixed width and the row scrolls horizontally;
    columns are never hidden or converted into cards.
    """
    st.markdown("""
    <style>
    *, *::before, *::after {box-sizing:border-box;}
    html {-webkit-text-size-adjust:100%;}
    .main .block-container {max-width:1280px;padding-top:1.5rem;}
    html, body, p, span, div, label, li, td, th,
    h1, h2, h3, h4, h5, h6 {color:#000000;}
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p,
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"],
    [data-testid="stWidgetLabel"] p {color:#000000 !important;}

    .degen-stop-header {margin:.1rem 0 .9rem;padding:.75rem .9rem;
      border:3px solid #2563eb;border-radius:14px;background:#450a0a;
      background-image:linear-gradient(180deg,#450a0a 0%,#7f1d1d 55%,#450a0a 100%);
      box-shadow:0 0 14px rgba(37,99,235,.6),0 0 34px rgba(29,78,216,.4);
      animation:degen-stop-glow 1s ease-in-out infinite;}
    .degen-stop-line {display:block;font-size:clamp(1.4rem,3.6vw,2.6rem);
      font-weight:900;letter-spacing:.045em;line-height:1.18;color:#3b82f6;
      text-shadow:0 0 8px rgba(59,130,246,.95),0 0 20px rgba(37,99,235,.75),
      0 0 42px rgba(29,78,216,.55);animation:degen-stop-blink 1s ease-in-out infinite;}
    .degen-stop-line + .degen-stop-line {margin-top:.4rem;}
    .degen-stop-emoji {margin:0 .45rem;}
    @keyframes degen-stop-blink {
      0%,100% {opacity:1;text-shadow:0 0 8px rgba(59,130,246,.95),
        0 0 20px rgba(37,99,235,.75),0 0 42px rgba(29,78,216,.55);}
      50% {opacity:.3;text-shadow:0 0 4px rgba(37,99,235,.45);}}
    @keyframes degen-stop-glow {
      0%,100% {box-shadow:0 0 14px rgba(37,99,235,.6),0 0 34px rgba(29,78,216,.4)}
      50% {box-shadow:0 0 4px rgba(37,99,235,.2)}}
    @media (prefers-reduced-motion:reduce) {
      .degen-stop-header,.degen-stop-line {animation:none;opacity:1}}

    .lp-head {display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;padding:.5rem 0 .1rem;}
    .lp-title {font-size:1.15rem;font-weight:800;color:#000000;}
    .lp-title[title],.md-title-tip[title] {cursor:help;}
    .lp-count {font-size:.75rem;font-weight:700;color:#312e81;background:#e0e7ff;
      padding:.2rem .5rem;border-radius:999px;}
    .lp-warn {font-size:.75rem;font-weight:700;color:#7f1d1d;background:#fee2e2;
      padding:.2rem .5rem;border-radius:999px;}

    .watchlist-token {display:flex;flex-direction:column;gap:.25rem;}
    .watchlist-symbol {font-size:1.2rem;font-weight:800;color:#000000;}
    .watchlist-pair {font-size:.86rem;font-weight:800;color:#000000;
      font-family:monospace;letter-spacing:.01em;white-space:nowrap;}
    .watchlist-mint {font-size:.84rem;color:#000000;font-family:monospace;white-space:nowrap;}
    .watchlist-links {display:flex;gap:.5rem;margin-top:.25rem;}
    .watchlist-links a,.pool-links a {font-size:.84rem;color:#1d4ed8;
      font-weight:700;text-decoration:none;}
    .watchlist-links a:hover,.pool-links a:hover {color:#000000;text-decoration:underline;}
    .watchlist-metric {text-align:center;}
    .watchlist-metric-value {font-size:1.05rem;font-weight:700;color:#000000;
      line-height:1.25;white-space:nowrap;}
    .watchlist-metric-sub {font-size:.74rem;color:#000000;line-height:1.3;white-space:nowrap;}
    .pool-links {display:flex;gap:.45rem;flex-wrap:nowrap;justify-content:center;}
    .pool-links .hawkfi-copy-btn {background:transparent;border:none;padding:0;
      margin:0;font-size:.9rem;line-height:1;cursor:pointer;}
    .pool-links .hawkfi-copy-btn:hover {transform:scale(1.15);}
    .bp-col-title {font-size:.82rem;color:#000000;font-weight:700;text-align:center;
      white-space:nowrap;line-height:1.3;}
    .bp-strategy-range,.bp-tax-dividend {white-space:nowrap;}
    .bp-dividend {color:#15803d;font-weight:700;}
    .bp-table-scroll {width:100%;max-width:100%;overflow-x:auto;
      -webkit-overflow-scrolling:touch;scrollbar-width:thin;}
    .bp-table {border-collapse:collapse;width:max-content;min-width:100%;
      table-layout:fixed;background:#ffffff;}
    .bp-table th,.bp-table td {vertical-align:top;border-right:1px solid #cbd5e1;
      border-bottom:1px solid #e2e8f0;padding:.38rem .32rem;min-width:76px;}
    .bp-table th:last-child,.bp-table td:last-child {border-right:none;}
    .bp-table th {position:sticky;top:0;z-index:1;background:#f8fafc;}
    .bp-table th:nth-child(1),.bp-table td:nth-child(1) {width:145px;min-width:145px;}
    .bp-table th:nth-child(2),.bp-table td:nth-child(2) {width:104px;min-width:104px;}
    .bp-table th:nth-child(3),.bp-table td:nth-child(3) {width:88px;min-width:88px;}
    .bp-table th:nth-child(5),.bp-table td:nth-child(5) {width:104px;min-width:104px;}
    .bp-table th:nth-child(6),.bp-table td:nth-child(6) {width:60px;min-width:60px;}
    .bp-table th:nth-child(8),.bp-table td:nth-child(8) {width:68px;min-width:68px;}
    .bp-table th:nth-child(9),.bp-table td:nth-child(9) {width:82px;min-width:82px;}
    .bp-table th:nth-child(10),.bp-table td:nth-child(10) {width:92px;min-width:92px;}
    .bp-table th:nth-child(12),.bp-table td:nth-child(12) {width:110px;min-width:110px;}
    .bp-table th:nth-child(13),.bp-table td:nth-child(13) {width:104px;min-width:104px;}
    .bp-table th:nth-child(14),.bp-table td:nth-child(14) {width:122px;min-width:122px;}
    .bp-table th:nth-child(15),.bp-table td:nth-child(15) {width:150px;min-width:150px;}

    @media (max-width:768px) {
      .main .block-container {max-width:100% !important;padding:.8rem .65rem 1rem !important;}
      h1 {font-size:clamp(1.35rem,5vw,1.7rem) !important;line-height:1.2 !important;}
      h2 {font-size:clamp(1.15rem,4vw,1.4rem) !important;line-height:1.25 !important;}
      h3 {font-size:clamp(1.02rem,3.6vw,1.2rem) !important;}
      .degen-stop-header {padding:.55rem .5rem;}
      .degen-stop-line {font-size:clamp(1.05rem,5vw,1.45rem);}
      .lp-head {gap:.4rem;padding:.35rem 0 .15rem;}
      .lp-title {font-size:1.02rem;}
      .lp-count,.lp-warn {font-size:.68rem;padding:.18rem .44rem;}
      [data-testid="stForm"] [data-testid="stHorizontalBlock"] {flex-wrap:wrap !important;}
      [data-testid="stForm"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
      [data-testid="stForm"] [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        flex:1 1 100% !important;min-width:100% !important;}
      .stButton > button,[data-testid="stFormSubmitButton"] > button {
        min-height:42px !important;font-size:.9rem !important;}
      [data-testid="stCaptionContainer"] p {font-size:.76rem !important;line-height:1.45 !important;}
      input,select,textarea {font-size:16px !important;}

      /* One real table wrapper owns the scrollbar, so its header and every
         row remain aligned while all fifteen columns stay available. */
      .bp-table-scroll {overflow-x:auto !important;max-width:100% !important;
        -webkit-overflow-scrolling:touch;scrollbar-width:thin;}
      .bp-table {width:max-content !important;min-width:1320px !important;}
      .bp-table th,.bp-table td {padding:.28rem .22rem;}
      .watchlist-symbol {font-size:1rem;}
      .watchlist-pair {font-size:.74rem;}
      .watchlist-mint {font-size:.7rem;}
      .watchlist-metric-value {font-size:.9rem;}
      .watchlist-metric-sub {font-size:.66rem;}
      .watchlist-links a,.pool-links a {font-size:.72rem;}
      .bp-col-title {font-size:.72rem;}
    }
    @media print {.main .block-container {max-width:none !important;}}
    </style>
    """, unsafe_allow_html=True)


DEGEN_STOP_LINES = (
    ("STOP DEGEN, GAK BISA", "🚨"),
    ("SUDAH KALAH BERTUBI2 AKUI KALAU KAMU GAK BISA", "⚠️"),
)


def render_degen_stop_header() -> None:
    """Render the existing stop-degen warning above the scanner."""
    lines = "".join(
        f'<span class="degen-stop-line"><span class="degen-stop-emoji">{icon}</span>'
        f'{html.escape(text)}<span class="degen-stop-emoji">{icon}</span></span>'
        for text, icon in DEGEN_STOP_LINES
    )
    st.markdown(f'<div class="degen-stop-header" role="alert">{lines}</div>',
                unsafe_allow_html=True)


def _number(value, pattern: str = ".1f") -> str:
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


def _compact(value, signed: bool = False) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if signed and number > 0 else ""
    if abs(number) >= 1e6:
        return f"{sign}${number / 1e6:.2f}M"
    if abs(number) >= 1e3:
        return f"{sign}${number / 1e3:.1f}K"
    return f"{sign}${number:,.0f}"


def card_head_html(title: str, pills: list[str] | None = None,
                   tooltip: str = "") -> str:
    """Build a compact card heading and optional summary pills."""
    tip = f' title="{html.escape(tooltip)}"' if tooltip else ""
    chips = "".join(pills or [])
    return (f'<div class="lp-head"><span class="lp-title"{tip}>{title}'
            f"</span>{chips}</div>")
