"""Safe external token, CVD, and pool-link helpers."""
from __future__ import annotations

import html as _html
from urllib.parse import quote

GMGN_TOKEN_BASE = "https://gmgn.ai/sol/token/"
DEXSCREENER_TOKEN_BASE = "https://dexscreener.com/solana/"
METEORA_DLMM_BASE = "https://app.meteora.ag/dlmm/"
HAWKFI_METEORA_BASE = "https://www.hawkfi.ag/meteora/"
SOLSCAN_ACCOUNT_BASE = "https://solscan.io/account/"
BUBBLEMAPS_V2_BASE = "https://v2.bubblemaps.io/map"
BUBBLEMAPS_APP_BASE = "https://app.bubblemaps.io/sol/token/"


def safe_url_part(value) -> str:
    return quote(str(value or ""), safe="")


def solscan_account_url(address) -> str:
    return f"{SOLSCAN_ACCOUNT_BASE}{safe_url_part(str(address or '').strip())}"


def solscan_account_html(address, *, text: str | None = None) -> str:
    address = str(address or "").strip()
    if not address:
        return ""
    href = _html.escape(solscan_account_url(address), quote=True)
    return (f'<a href="{href}" target="_blank" rel="noopener noreferrer">'
            f'{_html.escape(str(text or "Solscan"))}</a>')


def gmgn_token_url(ca) -> str:
    return f"{GMGN_TOKEN_BASE}{safe_url_part(ca)}"


def dexscreener_token_url(ca) -> str:
    return f"{DEXSCREENER_TOKEN_BASE}{safe_url_part(str(ca or '').strip())}"


def token_links(ca) -> list[tuple[str, str, str]]:
    address = str(ca or "").strip()
    if not address:
        return []
    return [("🔗", "GMGN", gmgn_token_url(address)),
            ("🦆", "DexScreener", dexscreener_token_url(address))]


def token_link_lines(ca) -> list[str]:
    return [f"{emoji} {label}: {url}" for emoji, label, url in token_links(ca)]


def cvd_shortcut_query(ca) -> str:
    return f"?mint={safe_url_part(ca)}"


def meteora_dlmm_url(pool) -> str:
    return f"{METEORA_DLMM_BASE}{safe_url_part(pool)}"


def hawkfi_meteora_url(pool) -> str:
    return f"{HAWKFI_METEORA_BASE}{safe_url_part(pool)}"


def bubblemaps_v2_url(ca, *, chain: str = "solana") -> str:
    address = str(ca or "").strip()
    if not address:
        return ""
    return (f"{BUBBLEMAPS_V2_BASE}?address={safe_url_part(address)}"
            f"&chain={safe_url_part(chain)}")


def bubblemaps_app_url(ca) -> str:
    address = str(ca or "").strip()
    return f"{BUBBLEMAPS_APP_BASE}{safe_url_part(address)}" if address else ""


def bubblemaps_links_html(ca) -> str:
    url = bubblemaps_v2_url(ca)
    if not url:
        return ""
    href = _html.escape(url, quote=True)
    return (f'<a href="{href}" target="_blank" rel="noopener noreferrer" '
            'title="Buka Bubble Map di v2.bubblemaps.io">🫧 Bubble</a>')


def bubblemap_icon_link_html(ca, *, url: str = "") -> str:
    target = str(url or "").strip() or bubblemaps_v2_url(ca)
    if not target:
        return ""
    href = _html.escape(target, quote=True)
    return (f'<a class="bubblemap-link" href="{href}" target="_blank" '
            'rel="noopener noreferrer" title="Buka Bubble Map">🫧</a>')


def external_links_html(ca) -> str:
    address = str(ca or "")
    if not address:
        return ""
    gmgn = _html.escape(gmgn_token_url(address), quote=True)
    dex = _html.escape(dexscreener_token_url(address), quote=True)
    return (f'<a href="{gmgn}" target="_blank" rel="noopener noreferrer">'
            '🔗GMGN</a> &nbsp; '
            f'<a href="{dex}" target="_blank" rel="noopener noreferrer">'
            '🦆Dex</a>')


def hawkfi_copy_html(pool) -> str:
    pool = str(pool or "")
    if not pool:
        return ""
    url = hawkfi_meteora_url(pool)
    js_url = url.replace("\\", "\\\\").replace("'", "\\'")
    onclick = (
        f"var u='{js_url}',b=this;"
        "var ok=function(){b.innerHTML='✓';setTimeout(function(){b.innerHTML='📋'},1200);};"
        "var fb=function(){var t=document.createElement('textarea');t.value=u;"
        "t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);"
        "t.select();try{document.execCommand('copy');}catch(e){}"
        "document.body.removeChild(t);ok();};"
        "if(navigator.clipboard&&navigator.clipboard.writeText){"
        "navigator.clipboard.writeText(u).then(ok,fb);}else{fb();}return false;"
    )
    return (f'<button type="button" class="hawkfi-copy-btn" '
            f'title="Copy link HawkFi: {_html.escape(url, quote=True)}" '
            f'onclick="{_html.escape(onclick, quote=True)}">📋</button>')


def pool_links_html(pool, *, mint: str = "") -> str:
    """Meteora, HawkFi, copy-HawkFi, and optional Bubblemaps shortcuts."""
    pool = str(pool or "")
    if not pool:
        return ""
    meteora = _html.escape(meteora_dlmm_url(pool), quote=True)
    hawkfi = _html.escape(hawkfi_meteora_url(pool), quote=True)
    bubble = bubblemap_icon_link_html(mint) if mint else ""
    return (
        f'<a href="{meteora}" target="_blank" rel="noopener noreferrer">🌊Meteora</a> &nbsp; '
        f'<a href="{hawkfi}" target="_blank" rel="noopener noreferrer">🦅HawkFi</a> '
        f'{hawkfi_copy_html(pool)} {bubble}'
    ).strip()
