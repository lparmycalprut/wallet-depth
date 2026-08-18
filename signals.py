"""Telegram transport untuk alert 3 sinyal bottom.

Hanya SELLER_EXHAUSTION / REVERSAL / AKUMULASI yang dikirim (bukan "—").
Format konsisten (§6):

    ⚡ BOTTOM TERDETEKSI — $SYMBOL
    Sinyal: 🟢 SELLER EXHAUSTION / 🟣 REVERSAL / 🔵 AKUMULASI
    Hari: <date> (flush <date>)
    CVD: X SOL | Volume: Y% dari kemarin
    🔗 GMGN   ← hyperlink ke halaman token
"""
from __future__ import annotations

import html
import os

from effort_detector import SIGNAL_META, SIGNALS
from links import gmgn_token_url

ALLOWED_SIGNALS = set(SIGNALS)


def _telegram_credentials() -> tuple[str, str]:
    try:
        from core import load_config
        config = load_config()
    except Exception:
        config = {}
    token = (os.getenv("TELEGRAM_BOT_TOKEN")
             or config.get("telegram_bot_token") or "")
    chat_id = (os.getenv("TELEGRAM_CHAT_ID")
               or config.get("telegram_chat_id") or "")
    return str(token).strip(), str(chat_id).strip()


def send_telegram(text: str, reply_markup: dict | None = None) -> bool:
    """Send one HTML Telegram message; return False when not configured."""
    token, chat_id = _telegram_credentials()
    if not token or not chat_id:
        return False
    try:
        import requests
        payload = {"chat_id": chat_id, "text": text,
                   "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=20)
        response.raise_for_status()
        return bool((response.json() or {}).get("ok"))
    except Exception as exc:
        print(f"Telegram send failed: {exc}")
        return False


def should_send_telegram(result: dict) -> bool:
    """Gate: HANYA 3 sinyal bottom dengan tanggal valid yang dikirim."""
    signal = result.get("signal") or ""
    return (signal in ALLOWED_SIGNALS
            and result.get("date") not in (None, ""))


def _fmt_signed(value, pattern="+.1f", suffix=""):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern) + suffix
    except (TypeError, ValueError):
        return "—"


def format_effort_alert(symbol: str, result: dict) -> str:
    """Render alert bottom terdeteksi sesuai format §6."""
    signal = result.get("signal") or ""
    meta = SIGNAL_META.get(signal) or {}
    emoji = meta.get("emoji", "⚡")
    label = meta.get("label", signal.replace("_", " "))

    symbol_txt = html.escape(str(symbol or "?").upper())
    gmgn = html.escape(gmgn_token_url(result.get("mint")), quote=True)
    date = html.escape(str(result.get("date") or "?"))
    flush_date = result.get("flush_date")
    flush_txt = f" (flush {html.escape(str(flush_date))})" if flush_date else ""

    cvd = _fmt_signed(result.get("cvd_delta"), "+.1f")
    volume = result.get("volume_pct")
    volume_txt = (f"{float(volume):.0f}%"
                  if isinstance(volume, (int, float)) else "—")

    return (
        f"⚡ <b>BOTTOM TERDETEKSI — ${symbol_txt}</b>\n"
        f"Sinyal: {emoji} {html.escape(label)}\n"
        f"Hari: {date}{flush_txt}\n"
        f"CVD: {cvd} SOL | Volume: {volume_txt} dari kemarin\n"
        f"🔗 <a href=\"{gmgn}\">GMGN</a>"
    )
