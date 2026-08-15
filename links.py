# -*- coding: utf-8 -*-
"""Shared external-link and CVD-shortcut URL helpers.

Keeping these helpers together guarantees every surface (watchlist rows and
Trending/Degen listings) builds the same, URL-encoded links and that a token
contract address can never break out of a URL or HTML attribute.
"""
from __future__ import annotations

import html as _html
from urllib.parse import quote

CVD_PAGE_PATH = "pages/4_📊_CVD.py"
GMGN_TOKEN_BASE = "https://gmgn.ai/sol/token/"
DEXSCREENER_TOKEN_BASE = "https://dexscreener.com/solana/"


def safe_url_part(value) -> str:
    """URL-encode a token address so it is safe in a URL path segment.

    Solana addresses are case-sensitive base58 strings; ``quote`` leaves the
    unreserved characters (letters/digits) untouched while escaping anything
    that could alter the URL structure (``?``, ``#``, spaces, ``&``, ...).
    """
    return quote(str(value or ""), safe="")


def gmgn_token_url(ca) -> str:
    """Return the GMGN token page URL for a contract address."""
    return f"{GMGN_TOKEN_BASE}{safe_url_part(ca)}"


def dexscreener_token_url(ca) -> str:
    """Return the DexScreener Solana token URL for a contract address."""
    return f"{DEXSCREENER_TOKEN_BASE}{safe_url_part(ca)}"


def cvd_shortcut_query(ca) -> str:
    """Return the ``?mint=...`` query fragment that preselects a token on the
    CVD page (``pages/4_📊_CVD.py``)."""
    return f"?mint={safe_url_part(ca)}"


def external_links_html(ca) -> str:
    """Render new-tab GMGN + DexScreener anchor links for a token.

    ``target=\"_blank\"`` keeps the links from disturbing the surrounding
    Chart/Hapus/CVD buttons. The URL is HTML-escaped after URL-encoding so the
    contract address stays safe inside the attribute.
    """
    ca = str(ca or "")
    if not ca:
        return ""
    gmgn = _html.escape(gmgn_token_url(ca), quote=True)
    dexscreener = _html.escape(dexscreener_token_url(ca), quote=True)
    return (
        f"<a href=\"{gmgn}\" target=\"_blank\" rel=\"noopener noreferrer\">"
        f"🔗GMGN</a> &nbsp; "
        f"<a href=\"{dexscreener}\" target=\"_blank\" "
        f"rel=\"noopener noreferrer\">🦆Dex</a>")
