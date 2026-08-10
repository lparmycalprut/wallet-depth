# -*- coding: utf-8 -*-
"""Daily CVD and priority-volume signal persistence and Telegram delivery."""
import json
import os
import sys
import time
import requests
from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_PATH = os.path.join(BASE_DIR, "signals.json")
DAILY_CVD_PATH = os.path.join(BASE_DIR, "cvd_daily.json")
MAX_SIGNALS = 2000
# Kept only as a compatibility constant for archived detector imports; the
# daily CVD path below does not use the old detector.
PREPUMP_DEDUPE_SEC = 20 * 3600
_DIGEST_BUF = []
_DIGEST_MODE = False


def load_signals():
    try:
        with open(SIGNALS_PATH, encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def save_signals(items):
    atomic_write_json(SIGNALS_PATH, items[-MAX_SIGNALS:], separators=(",", ":"))


def _telegram_creds():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    try:
        import streamlit as st
        token = token or str(st.secrets.get("telegram_bot_token", st.secrets.get("TELEGRAM_BOT_TOKEN", ""))).strip()
        chat = chat or str(st.secrets.get("telegram_chat_id", st.secrets.get("TELEGRAM_CHAT_ID", ""))).strip()
    except Exception:
        pass
    try:
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f) or {}
        token = token or str(cfg.get("telegram_bot_token", cfg.get("TELEGRAM_BOT_TOKEN", ""))).strip()
        chat = chat or str(cfg.get("telegram_chat_id", cfg.get("TELEGRAM_CHAT_ID", ""))).strip()
    except Exception:
        pass
    return token, chat


def send_telegram(text):
    token, chat = _telegram_creds()
    if not token or not chat:
        print("WARN: Telegram credentials missing", file=sys.stderr)
        return False
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}, timeout=15)
        return response.status_code == 200
    except requests.RequestException as exc:
        print(f"WARN: Telegram error: {exc}", file=sys.stderr)
        return False


def begin_digest():
    global _DIGEST_MODE, _DIGEST_BUF
    _DIGEST_MODE, _DIGEST_BUF = True, []


def _queue_or_send(text):
    if _DIGEST_MODE:
        _DIGEST_BUF.append(text)
        return True
    return send_telegram(text)


def flush_telegram_digest(*, title=None, send_fn=None):
    global _DIGEST_MODE, _DIGEST_BUF
    items, _DIGEST_BUF, _DIGEST_MODE = list(_DIGEST_BUF), [], False
    if not items:
        return 0
    title = title or "📊 <b>DAILY CVD — GMGN</b>"
    chunks, current = [], title + "\n\n"
    for item in items:
        if len(current) + len(item) + 2 > 3800:
            chunks.append(current)
            current = title + "\n\n"
        current += item + "\n\n"
    if current.strip() != title.strip():
        chunks.append(current)
    sender = send_fn or send_telegram
    return sum(bool(sender(chunk)) for chunk in chunks)


def record_daily_cvd(ca, symbol, rows, *, now_ts=None, price=None):
    """Record one daily CVD result; never emits intra-day/legacy signals."""
    now_ts = int(now_ts or time.time())
    latest = (rows or [])[-1] if rows else {}
    sig = {"ts": now_ts, "ca": ca, "symbol": symbol, "type": "cvd_daily",
           "src": "gmgn_extension_model", "daily": True,
           "date": latest.get("date"), "status": latest.get("status"),
           "detail": latest, "price": price}
    items = load_signals()
    if latest.get("date") and not any(x.get("ca") == ca and x.get("type") == "cvd_daily" and x.get("date") == latest["date"] for x in items[-500:]):
        items.append(sig)
        save_signals(items)
    try:
        with open(DAILY_CVD_PATH, encoding="utf-8") as f:
            daily = json.load(f) or {}
    except Exception:
        daily = {}
    daily.setdefault(ca, {})[latest.get("date", "unknown")] = {"symbol": symbol, "rows": rows, "ts": now_ts}
    atomic_write_json(DAILY_CVD_PATH, daily, separators=(",", ":"))
    return latest


def queue_daily_cvd_message(ca, symbol, rows, *, price=None):
    latest = (rows or [])[-1] if rows else {}
    if not latest:
        return
    icon = "🟠" if latest.get("status", "").startswith("KERING") else "📈"
    change = latest.get("volume_change_pct")
    change_text = "n/a" if change is None else f"{change:+.1f}%"
    text = (f"{icon} <b>DAILY CVD · {symbol}</b>\n"
            f"<code>{ca}</code>\n\n"
            f"<b>{latest.get('status', 'NORMAL')}</b>\n"
            f"📅 {latest.get('date', '-')}  ·  🔁 {latest.get('total_tx', 0):,} TX\n"
            f"💧 Volume <b>{latest.get('volume_sol', 0):,.2f} SOL</b> ({change_text} vs H-1)\n"
            f"⚖️ CVD <b>{latest.get('delta_sol', 0):+,.2f} SOL</b> · ratio {latest.get('cvd_ratio_pct', 0):+.1f}%\n"
            f"🟢 Buy {latest.get('buy_tx', 0):,} · 🔴 Sell {latest.get('sell_tx', 0):,}\n\n"
            f"<a href='https://dexscreener.com/solana/{ca}'>DexScreener</a>  ·  <a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>")
    _queue_or_send(text)


def record_priority_spike(ca, symbol, stats, *, now_ts=None, price=None):
    now_ts = int(now_ts or time.time())
    items = load_signals()
    if any(x.get("ca") == ca and x.get("type") == "priority_volume_spike" and now_ts - int(x.get("ts", 0)) < 14 * 60 for x in items[-300:]):
        return False
    items.append({"ts": now_ts, "ca": ca, "symbol": symbol, "type": "priority_volume_spike",
                  "src": "priority_15m", "daily": False, "detail": stats, "price": price})
    save_signals(items)
    text = (f"🚨 <b>PRIORITY VOLUME SPIKE · {symbol}</b> 🚨\n"
            f"<code>{ca}</code>\n\n🔥 <b>{stats['tx']:,} transaksi</b> dalam 15 menit\n"
            f"💰 Volume <b>{stats['volume_sol']:,.2f} SOL</b>\n"
            f"🟢 Buy {stats['buy_tx']:,}  ·  🔴 Sell {stats['sell_tx']:,}\n"
            f"⚖️ CVD <b>{stats['cvd_sol']:+,.2f} SOL</b>\n\n"
            f"<a href='https://dexscreener.com/solana/{ca}'>Open chart</a>  ·  <a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>")
    return bool(_queue_or_send(text))
