"""Telegram transport for daily effort anomaly alerts."""
from __future__ import annotations

import html
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


def send_telegram(text: str) -> bool:
    """Send one HTML Telegram message; return False when not configured."""
    token, chat_id = _telegram_credentials()
    if not token or not chat_id:
        return False
    try:
        import requests
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20)
        response.raise_for_status()
        return bool((response.json() or {}).get("ok"))
    except Exception as exc:
        print(f"Telegram send failed: {exc}")
        return False


def format_effort_alert(symbol: str, result: dict) -> str:
    """Render the only supported alert format."""
    signal = result.get("signal") or ""
    short = {
        "S1_PENYERAPAN": "S1_PENYERAPAN",
        "S2_DUMP_DISTRIBUSI": "S2_DUMP",
        "S3_DISTRIBUSI_KE_KUAT": "S3_DISTRIBUSI",
        "S4_PUMP_ASLI": "S4_PUMP",
    }.get(signal, signal)
    bias = result.get("bias") or "neutral"
    emoji = "🟢" if bias == "bullish" else "🔴"
    divergence = "\n⚠️ divergensi arah CVD" \
        if result.get("flag_divergence") else ""
    mint = str(result.get("mint") or "")
    return (
        f"⚡ <b>ANOMALI EFISIENSI — "
        f"${html.escape(str(symbol).upper())}</b>\n"
        f"Sinyal: {emoji} {html.escape(short)} ({bias})\n"
        f"Hari: {result.get('date')} (vs {result.get('previous_date')})\n"
        f"Ratio: {float(result.get('ratio_N') or 0):.3f} SOL/1% vs "
        f"{float(result.get('ratio_N_minus_1') or 0):.3f} SOL/1%  "
        f"(×{float(result.get('multiplier') or 0):.2f})\n"
        f"ΔHarga: {float(result.get('price_chg_pct') or 0):+.2f}% | "
        f"ΔCVD: {float(result.get('cvd_delta') or 0):+.2f} SOL"
        f"{divergence}\n"
        f"https://gmgn.ai/sol/token/{html.escape(mint)}"
    )
