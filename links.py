# -*- coding: utf-8 -*-
"""Shared external-link and CVD-shortcut URL helpers.

Keeping these helpers together guarantees every surface (watchlist rows and
Trending/Degen listings) builds the same, URL-encoded links and that a token
contract address can never break out of a URL or HTML attribute.
"""
from __future__ import annotations

import html as _html
import os
import re
from pathlib import Path as _Path
from urllib.parse import quote

CVD_PAGE_PATH = "pages/4_📊_CVD.py"
HOLDER_PAGE_PATH = "pages/5_🧮_Holder.py"
GMGN_TOKEN_BASE = "https://gmgn.ai/sol/token/"
DEXSCREENER_TOKEN_BASE = "https://dexscreener.com/solana/"
DEXSCREENER_ROBINHOOD_BASE = "https://dexscreener.com/robinhood/"
RH_SCAN_TOKEN_BASE = "https://rh-scan.com/token/"
BLOCKSCOUT_BASE = "https://robinhoodchain.blockscout.com"
BLOCKSCOUT_TOKEN_BASE = f"{BLOCKSCOUT_BASE}/token/"
BLOCKSCOUT_ADDRESS_BASE = f"{BLOCKSCOUT_BASE}/address/"
METEORA_DLMM_BASE = "https://app.meteora.ag/dlmm/"
HAWKFI_METEORA_BASE = "https://www.hawkfi.ag/meteora/"
SOLSCAN_ACCOUNT_BASE = "https://solscan.io/account/"

_EVM_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def _is_evm(address) -> bool:
    return bool(_EVM_RE.fullmatch(str(address or "").strip()))


def safe_url_part(value) -> str:
    """URL-encode a token address so it is safe in a URL path segment.

    Solana addresses are case-sensitive base58 strings; ``quote`` leaves the
    unreserved characters (letters/digits) untouched while escaping anything
    that could alter the URL structure (``?``, ``#``, spaces, ``&``, ...).
    """
    return quote(str(value or ""), safe="")


# ---------------------------------------------------------------------------
# URL halaman internal (multipage ``pages/``)
# ---------------------------------------------------------------------------
# Streamlit TIDAK melayani file di ``pages/`` lewat path file-nya. Untuk app
# gaya lama (folder ``pages/``), Streamlit menyetel ``url_pathname`` sebuah
# halaman dari NAMA FILE yang sudah dibersihkan: prefiks nomor ("5_") dan emoji
# leading ("🧮") dibuang, sisanya dipakai apa adanya (case-sensitive).
# Frontend mencocokkan URL dengan ``pathname.endsWith('/' + urlPathname)``,
# jadi ``/pages/5_🧮_Holder.py`` BUKAN halaman Holder — tidak ada halaman yang
# cocok, Streamlit menampilkan "Page not found" dan menjalankan halaman utama
# (``app.py``) sehingga ``?mint=`` di URL tidak pernah dibaca. Bentuk yang
# benar: ``/Holder?mint=…`` — sama seperti tautan navigasi sidebar Streamlit
# sendiri (``buildAppPageURL`` memakai ``urlPathname`` yang sama).
_PAGE_FILENAME_RE = re.compile(r"([0-9]*)[_ -]*(.*)\.py\Z")


def page_url_path(page_path) -> str:
    """Return path URL Streamlit untuk sebuah file di folder ``pages/``.

    Menerima ``pages/5_🧮_Holder.py``, ``5_🧮_Holder.py`` maupun ``Holder``
    (idempoten: slug yang sudah bersih menghasilkan slug yang sama). Sumber
    aturan adalah Streamlit sendiri (``source_util.page_icon_and_name``,
    fungsi yang dipakai ``_mpa_v1`` saat membangun ``st.Page``); kalau streamlit
    tidak bisa diimpor, aturan yang sama ditiru secara lokal.
    """
    name = str(page_path or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return ""
    if not name.endswith(".py"):
        name += ".py"
    try:  # pragma: no cover - branch hanya dipakai bila streamlit absent
        from streamlit.source_util import page_icon_and_name

        _icon, inferred = page_icon_and_name(_Path(name))
        if inferred:
            return inferred
    except Exception:  # noqa: BLE001 - links.py harus tetap bisa diimpor polos
        pass
    match = _PAGE_FILENAME_RE.search(name)
    number, label = (match.group(1), match.group(2)) if match else ("", name)
    label = re.sub(r"[_ ]+", "_", label).strip() or number
    # Buang emoji/icon leading beserta pemisahnya (mirror extract_leading_emoji).
    return re.sub(r"^[^\w]+[_ ]*", "", label)


def base_url_path() -> str:
    """Prefix ``server.baseUrlPath`` sebagai path URL (``""`` atau ``/app``)."""
    base = ""
    try:  # pragma: no cover - konfigurasi deploy
        from streamlit import config

        base = str(config.get_option("server.baseUrlPath") or "")
    except Exception:  # noqa: BLE001
        base = os.environ.get("STREAMLIT_SERVER_BASE_URL_PATH", "")
    base = base.strip().strip("/")
    return f"/{base}" if base else ""


def page_url(page_path, **params) -> str:
    """Absolute-from-root URL for a ``pages/`` page plus encoded query params.

    Root-absolute (bukan relatif) supaya tautan tetap benar ketika halaman
    yang sedang dibuka punya path sendiri (``/Holder``) atau ketika app
    dipasang di bawah ``baseUrlPath``.
    """
    slug = page_url_path(page_path)
    path = f"{base_url_path()}/{slug}" if slug else (base_url_path() or "/")
    pairs = [f"{quote(str(key), safe='')}={safe_url_part(value)}"
             for key, value in params.items() if value not in (None, "")]
    return f"{path}?{'&'.join(pairs)}" if pairs else path


def solscan_account_url(address) -> str:
    """Return an account URL for a wallet address.

    Solana → Solscan. EVM (Robinhood Chain) → Blockscout address page.
    The address is trimmed then URL-encoded; Solana Base58 is case-sensitive
    and left intact by ``quote`` for the usual unreserved characters.
    """
    addr = str(address or "").strip()
    if _is_evm(addr):
        return f"{BLOCKSCOUT_ADDRESS_BASE}{safe_url_part(addr)}"
    return f"{SOLSCAN_ACCOUNT_BASE}{safe_url_part(addr)}"


def solscan_account_html(address, *, text: str | None = None) -> str:
    """Safe new-tab account anchor; ``href`` uses the full trimmed address.

    Ketika ``text`` tidak diberikan, EVM (Robinhood Chain) diberi label
    ``Blockscout`` dan Solana ``Solscan``.
    """
    addr = str(address or "").strip()
    if not addr:
        return ""
    label = str(text or ("Blockscout" if _is_evm(addr) else "Solscan"))
    url = _html.escape(solscan_account_url(addr), quote=True)
    label = _html.escape(label)
    return (f'<a href="{url}" target="_blank" rel="noopener noreferrer">'
            f"{label}</a>")


def gmgn_token_url(ca) -> str:
    """Return the GMGN token page URL for a Solana contract address."""
    return f"{GMGN_TOKEN_BASE}{safe_url_part(ca)}"


def dexscreener_token_url(ca) -> str:
    """Return the DexScreener token URL for a contract address.

    Solana → ``.../solana/<ca>``, EVM/Robinhood → ``.../robinhood/<ca>``.
    """
    addr = str(ca or "").strip()
    base = DEXSCREENER_ROBINHOOD_BASE if _is_evm(addr) else DEXSCREENER_TOKEN_BASE
    return f"{base}{safe_url_part(addr)}"


def rh_scan_token_url(ca) -> str:
    """Return the rh-scan.com token page URL for a Robinhood token."""
    return f"{RH_SCAN_TOKEN_BASE}{safe_url_part(ca)}"


def blockscout_token_url(ca) -> str:
    """Return the Blockscout token page URL for a Robinhood token."""
    return f"{BLOCKSCOUT_TOKEN_BASE}{safe_url_part(ca)}"


def token_link_lines(ca) -> list[str]:
    """Plain-text explorer/market links for surfaces without HTML.

    Solana → GMGN + DexScreener. EVM (Robinhood Chain) → rh-scan.com +
    DexScreener robinhood + Blockscout. Dipakai pesan Telegram (Bot API
    mengirim teks polos dan otomatis me-link URL). Return ``[]`` bila
    address kosong supaya pesan tidak berakhir dengan label menggantung.
    """
    addr = str(ca or "").strip()
    if not addr:
        return []
    if _is_evm(addr):
        return [f"\U0001f986 rh-scan: {rh_scan_token_url(addr)}",
                f"\U0001f986 DexScreener: {dexscreener_token_url(addr)}",
                f"\U0001f30f Blockscout: {blockscout_token_url(addr)}"]
    return [f"\U0001f517 GMGN: {gmgn_token_url(addr)}",
            f"\U0001f986 DexScreener: {dexscreener_token_url(addr)}"]


def cvd_shortcut_query(ca) -> str:
    """Return the ``?mint=...`` query fragment that preselects a token on the
    CVD page (``pages/4_📊_CVD.py``)."""
    return f"?mint={safe_url_part(ca)}"


def holder_analytic_url(ca) -> str:
    """URL Holder Analytic untuk satu token: ``/Holder?mint=<ca>``.

    Path yang dipakai adalah **slug halaman** yang diberikan Streamlit ke file
    ``pages/5_🧮_Holder.py`` (lihat :func:`page_url_path`), bukan path
    file. Hanya slug itu yang dikenali router Streamlit; ``pages/…py`` membuat
    app jatuh ke halaman utama ("Page not found") sehingga ``?mint=`` tidak
    pernah dibaca halaman Holder.
    """
    addr = str(ca or "").strip()
    if not addr:
        return ""
    return page_url(HOLDER_PAGE_PATH, mint=addr)


def holder_analytic_link_html(ca) -> str:
    """Render the watchlist Holder Analytic action as a background-tab link.

    Streamlit's ``st.switch_page`` navigates the current tab, which makes it
    awkward to inspect several watchlist tokens at once.  A normal anchor is
    deliberately used here so the browser can create a new tab without
    triggering a Streamlit rerun in the watchlist.  ``window.focus`` asks the
    browser to keep the watchlist tab active after opening the new one (where
    the browser permits that preference).

    Tujuannya :func:`holder_analytic_url` (slug halaman, root-absolute, aman
    untuk ``baseUrlPath``). Tautan lama yang sempat tersebar dengan bentuk
    ``pages/5_🧮_Holder.py?mint=…`` tetap dipakai bersama: Streamlit
    jatuh ke halaman utama, lalu router ``page_router`` di ``app.py`` melihat
    ``mint=`` di URL dan ``st.switch_page`` ke Holder.
    """
    url = holder_analytic_url(ca)
    if not url:
        return ""
    href = _html.escape(url, quote=True)
    return (
        f'<a class="watchlist-holder-link" href="{href}" target="_blank" '
        f'rel="noopener noreferrer" aria-label="Buka Holder Analytic" '
        f'onclick="setTimeout(function(){{window.focus();}},0);">🧮</a>')


def meteora_dlmm_url(pool) -> str:
    """Return the Meteora DLMM pool page URL."""
    return f"{METEORA_DLMM_BASE}{safe_url_part(pool)}"


def hawkfi_meteora_url(pool) -> str:
    """Return the HawkFi Meteora pool URL."""
    return f"{HAWKFI_METEORA_BASE}{safe_url_part(pool)}"


def external_links_html(ca) -> str:
    """Render new-tab GMGN + DexScreener anchor links for a token.

    ``target=\\\"_blank\\\"`` keeps the links from disturbing the surrounding
    Chart/Hapus/CVD buttons. The URL is HTML-escaped after URL-encoding so the
    contract address stays safe inside the attribute.
    """
    ca = str(ca or "")
    if not ca:
        return ""
    if _is_evm(ca):
        rh_scan = _html.escape(rh_scan_token_url(ca), quote=True)
        dexscreener = _html.escape(dexscreener_token_url(ca), quote=True)
        blockscout = _html.escape(blockscout_token_url(ca), quote=True)
        return (
            f'<a href="{rh_scan}" target="_blank" '
            f'rel="noopener noreferrer">🔍RH</a> &nbsp; '
            f'<a href="{dexscreener}" target="_blank" '
            f'rel="noopener noreferrer">🦆Dex</a> &nbsp; '
            f'<a href="{blockscout}" target="_blank" '
            f'rel="noopener noreferrer">🌐Blockscout</a>')
    gmgn = _html.escape(gmgn_token_url(ca), quote=True)
    dexscreener = _html.escape(dexscreener_token_url(ca), quote=True)
    return (
        f'<a href="{gmgn}" target="_blank" rel="noopener noreferrer">'
        f'🔗GMGN</a> &nbsp; '
        f'<a href="{dexscreener}" target="_blank" '
        f'rel="noopener noreferrer">🦆Dex</a>')


def pool_links_html(pool) -> str:
    """New-tab shortcuts: Meteora DLMM + HawkFi for a pool address."""
    pool = str(pool or "")
    if not pool:
        return ""
    meteora = _html.escape(meteora_dlmm_url(pool), quote=True)
    hawkfi = _html.escape(hawkfi_meteora_url(pool), quote=True)
    return (
        f'<a href="{meteora}" target="_blank" '
        f'rel="noopener noreferrer">🌊Meteora</a> &nbsp; '
        f'<a href="{hawkfi}" target="_blank" '
        f'rel="noopener noreferrer">🦅HawkFi</a>')
