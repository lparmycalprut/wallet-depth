"""Telegram transport for daily effort anomaly alerts — v3 final."""
from __future__ import annotations

import html
import os

ALLOWED_SIGNALS = {
    "S1_PENYERAPAN",
    "S2_DUMP_DISTRIBUSI",
    "S3_DISTRIBUSI_KE_KUAT",
    "S4_PUMP_ASLI",
    "ABSORBSI_LANGSUNG",
    "SELLING_EXHAUSTION",
}


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


def should_send_telegram(result: dict) -> bool:
    """Gate for Telegram alerts: S1-S4 (stable) + 2 new pra-pump signals."""
    signal = result.get("signal") or ""
    if signal in {"ABSORBSI_LANGSUNG", "SELLING_EXHAUSTION"}:
        # Direct signals have no baseline requirement; just need valid date & not noise
        return signal in ALLOWED_SIGNALS and result.get("date") not in (None, "")
    stable = result.get("baseline_status") == "stable"
    return signal in {"S1_PENYERAPAN", "S2_DUMP_DISTRIBUSI",
                      "S3_DISTRIBUSI_KE_KUAT", "S4_PUMP_ASLI"} and stable


def format_effort_alert(symbol: str, result: dict) -> str:
    """Render alert format v3 with 2 new signals."""
    signal = result.get("signal") or ""
    short_map = {
        "S1_PENYERAPAN": "S1_PENYERAPAN",
        "S2_DUMP_DISTRIBUSI": "S2_DUMP",
        "S3_DISTRIBUSI_KE_KUAT": "S3_DISTRIBUSI",
        "S4_PUMP_ASLI": "S4_PUMP",
        "ABSORBSI_LANGSUNG": "ABSORBSI LANGSUNG",
        "SELLING_EXHAUSTION": "SELLING EXHAUSTION",
    }
    short = short_map.get(signal, signal)
    bias = result.get("bias") or "neutral"
    emoji = "🟢" if bias == "bullish" else "🔴" if bias == "bearish" else "⚪"
    divergence = "\n⚠️ divergensi arah CVD" if result.get("flag_divergence") else ""
    mint = str(result.get("mint") or "")

    date = result.get("date") or "?"
    prev = result.get("previous_date") or "?"
    # Ratio line handling
    if signal == "SELLING_EXHAUSTION":
        flush_cvd = result.get("flush_cvd")
        cvd = result.get("cvd_delta")
        pct = result.get("exhaustion_pct")
        if flush_cvd is not None and cvd is not None:
            try:
                runtuh = float(pct) if pct is not None else 0.0
            except Exception:
                runtuh = 0.0
            ratio_line = f"flush {float(flush_cvd):+.2f} → {float(cvd):+.2f}, runtuh {runtuh:.1f}%"
        else:
            ratio_line = (
                f"{float(result.get('ratio_N') or 0):.3f} SOL/1% "
                f"(flush vs hari ini)"
            )
    elif signal == "ABSORBSI_LANGSUNG":
        ratio_n = result.get("ratio_N")
        cvd = result.get("cvd_delta")
        if ratio_n is not None:
            ratio_line = f"{float(ratio_n):.3f} SOL/1% (direct, CVD {float(cvd or 0):+.2f})"
        else:
            ratio_line = f"direct, CVD {float(cvd or 0):+.2f} SOL"
    else:
        ratio_line = (
            f"{float(result.get('ratio_N') or 0):.3f} SOL/1% vs "
            f"{float(result.get('ratio_N_minus_1') or 0):.3f} SOL/1%  "
            f"(×{float(result.get('multiplier') or 0):.2f})"
        )

    return (
        f"⚡ <b>ANOMALI EFISIENSI — "
        f"${html.escape(str(symbol).upper())}</b>\n"
        f"Sinyal: {emoji} {html.escape(short)} ({bias})\n"
        f"Hari: {date} (vs {prev})\n"
        f"Ratio: {ratio_line}\n"
        f"ΔHarga: {float(result.get('price_chg_pct') or 0):+.2f}% | "
        f"ΔCVD: {float(result.get('cvd_delta') or 0):+.2f} SOL"
        f"{divergence}\n"
        f"https://gmgn.ai/sol/token/{html.escape(mint)}"
    )
