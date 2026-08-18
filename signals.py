"""Transport Telegram bersama (HTML parse mode).

Hanya alert reversal realtime yang masih memakai Telegram:
🟢 REVERSAL UP / 🔴 REVERSAL DOWN dari ``scripts/realtime_reversal.py``,
itu pun hanya setelah struktur harga (SBR) mengonfirmasi. Alert harian
"BOTTOM TERDETEKSI" (SELLER_EXHAUSTION / REVERSAL / AKUMULASI) sudah
dipensiunkan — detektor hariannya tetap hidup untuk tampilan dashboard.
"""
from __future__ import annotations

import os


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
