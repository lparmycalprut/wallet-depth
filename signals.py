# -*- coding: utf-8 -*-
"""Signal log for PRE-PUMP detection (minimalist reset 2026-08-07).

Only prepump signals are kept:
  - prepump_imminent (Tier 1, Telegram always)
  - prepump_forming  (Tier 2, Telegram only if focus_mode OFF)
  - prepump_cleared  (always Telegram)

Other legacy types (accumulation, distribution, bullish_div) are still
readable from old signals.json but not produced by the new daily cron.

Telegram is sent directly via requests (no breakout_guard dependency).
Digest mode is kept for multi-CA daily run (one combined message).
"""

import json
import os
import sys
import time

import requests

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_PATH = os.path.join(BASE_DIR, "signals.json")
DEDUPE_SEC = 4 * 3600
MAX_SIGNALS = 2000
PREPUMP_DEDUPE_SEC = 3 * 3600

TIER1_SIGNAL_TYPES = {"prepump_imminent"}
TIER2_SIGNAL_TYPES = {"prepump_forming"}


def _focus_mode() -> bool:
    """Read focus_mode from config.json; default True (focus ON)."""
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
        return bool(cfg.get("focus_mode", True))
    except Exception:
        return True


def load_signals() -> list:
    try:
        with open(SIGNALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def save_signals(sigs: list) -> None:
    try:
        atomic_write_json(SIGNALS_PATH, sigs[-MAX_SIGNALS:], separators=(",", ":"))
    except Exception as exc:
        print(f"WARN: failed to save {SIGNALS_PATH}: {exc}", file=sys.stderr)


def _telegram_creds():
    """Return (bot_token, chat_id) from env / secrets / config.json."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        return token, chat
    try:
        import streamlit as st
        if "telegram_bot_token" in st.secrets:
            token = str(st.secrets["telegram_bot_token"]).strip()
        if "telegram_chat_id" in st.secrets:
            chat = str(st.secrets["telegram_chat_id"]).strip()
        if token and chat:
            return token, chat
        if "TELEGRAM_BOT_TOKEN" in st.secrets:
            token = str(st.secrets["TELEGRAM_BOT_TOKEN"]).strip()
        if "TELEGRAM_CHAT_ID" in st.secrets:
            chat = str(st.secrets["TELEGRAM_CHAT_ID"]).strip()
        if token and chat:
            return token, chat
    except Exception:
        pass
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
        t = str(cfg.get("telegram_bot_token") or cfg.get("TELEGRAM_BOT_TOKEN") or "").strip()
        c = str(cfg.get("telegram_chat_id") or cfg.get("TELEGRAM_CHAT_ID") or "").strip()
        if t:
            token = t
        if c:
            chat = c
    except Exception:
        pass
    return token, chat


def send_telegram(text: str) -> bool:
    """Send HTML text to Telegram. Returns True on success."""
    token, chat = _telegram_creds()
    if not token or not chat:
        print("WARN: Telegram creds missing, skip send", file=sys.stderr)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        if r.status_code == 200:
            return True
        print(f"WARN: Telegram send failed {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"WARN: Telegram send error: {exc}", file=sys.stderr)
        return False


def record_signal(ca: str, symbol: str, sig_type: str, detail: str, *,
                  src: str = "cron", window_h: int = None,
                  whale_net: float = None, retail_net: float = None,
                  price: float = None) -> bool:
    """Append a signal unless same (ca, type) fired within DEDUPE_SEC. Returns True if recorded."""
    sigs = load_signals()
    now = int(time.time())
    for s in reversed(sigs[-200:]):
        if s.get("ca") == ca and s.get("type") == sig_type and now - (s.get("ts") or 0) < DEDUPE_SEC:
            return False
    sigs.append({"ts": now, "ca": ca, "symbol": symbol, "type": sig_type,
                 "src": src, "detail": detail, "window_h": window_h,
                 "whale_net": whale_net, "retail_net": retail_net,
                 "price": price})
    save_signals(sigs)
    # Telegram only for cron + tier gating
    if src != "cron":
        return True
    if sig_type in TIER2_SIGNAL_TYPES and _focus_mode():
        return True
    if sig_type not in TIER1_SIGNAL_TYPES and sig_type not in TIER2_SIGNAL_TYPES:
        # For prepump_imminent/forming/cleared we handle elsewhere, but generic
        # record_signal should still respect tier gating; unknown types don't spam.
        if sig_type not in {"prepump_cleared"}:
            return True
    try:
        emo = {"prepump_imminent": "🚨", "prepump_forming": "👀", "prepump_cleared": "✅"}.get(sig_type, "🔔")
        _queue_or_send(f"{emo} <b>${symbol}</b> — {sig_type.replace('_', ' ')}\n{detail}\n<a href='https://dexscreener.com/solana/{ca}'>chart</a>")
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# Digest buffering (daily cron sends one combined message)
# ---------------------------------------------------------------------------
_DIGEST_BUF: list = []
_DIGEST_MODE: bool = False


def begin_digest() -> None:
    global _DIGEST_MODE, _DIGEST_BUF
    _DIGEST_MODE = True
    _DIGEST_BUF = []


def _queue_or_send(text: str) -> bool:
    if not text:
        return False
    if _DIGEST_MODE:
        _DIGEST_BUF.append(text)
        return True
    return send_telegram(text)


def flush_telegram_digest(*, title=None, send_fn=None) -> int:
    global _DIGEST_MODE, _DIGEST_BUF
    items = list(_DIGEST_BUF)
    _DIGEST_BUF = []
    _DIGEST_MODE = False
    if not items:
        return 0
    try:
        hdr = title or "📬 <b>PRE-PUMP DIGEST — 00:00 WIB</b>"
        sep = "\n\n— — —\n\n"
        body = sep.join(items)
        chunks = [hdr + "\n\n" + body]
        if len(chunks[0]) > 3800:
            chunks, buf, n = [], [], 0
            overhead = len(hdr) + 2
            for it in items:
                add = len(it) + (len(sep) if buf else 0)
                if buf and overhead + n + add > 3800:
                    chunks.append(hdr + "\n\n" + sep.join(buf))
                    buf, n = [it], len(it)
                else:
                    buf.append(it)
                    n += add
            if buf:
                chunks.append(hdr + "\n\n" + sep.join(buf))
    except Exception:
        chunks = items
    sender = send_fn or send_telegram
    n = 0
    for chunk in chunks:
        try:
            if sender(chunk):
                n += 1
        except Exception:
            pass
    return n


def detect_prepump_and_record(ca, symbol, swaps, token_info=None, *, now_ts=None,
                              src="cron", window_min=30, whale_min_sol=3.0,
                              wallet_tags=None, bullish_div=False, pool=None,
                              pool_sol=None, bullish_div_h4=False,
                              full_swaps=None, multi_tf=True):
    """Run Pre-Pump Detector and record/alert. Returns evaluate_prepump result."""
    from prepump_detector import (
        evaluate_prepump, evaluate_prepump_multi_tf,
        format_prepump_telegram,
        format_prepump_cleared_telegram,
        prepump_already_sent, PREPUMP_DEDUPE_SEC,
    )
    now_ts = int(now_ts if now_ts is not None else time.time())
    result = evaluate_prepump(
        swaps, token_info, ca=ca, now_ts=now_ts, window_min=window_min,
        whale_min_sol=whale_min_sol, wallet_tags=wallet_tags,
        bullish_div=bullish_div, pool_sol=pool_sol,
        bullish_div_h4=bullish_div_h4)
    if multi_tf:
        try:
            long_swaps = full_swaps
            if long_swaps is None:
                from cvd import get_recent_swaps
                long_swaps = get_recent_swaps(ca, 72) or swaps
            result["multi_tf"] = evaluate_prepump_multi_tf(
                long_swaps, token_info, ca=ca, now_ts=now_ts,
                wallet_tags=wallet_tags, whale_min_sol=whale_min_sol,
                bullish_div_h1=bullish_div, bullish_div_h4=bullish_div_h4,
                pool_sol=pool_sol)
        except Exception:
            pass

    def _last_prepump(sigs, ca_):
        for s in reversed(sigs or []):
            if s.get("ca") == ca_ and s.get("type") in ("prepump_imminent", "prepump_forming", "prepump_cleared"):
                return s
        return None

    if result["score"] < 55 or result.get("tier") in ("neutral", "blocked"):
        prev = _last_prepump(load_signals(), ca)
        if prev and prev.get("type") in ("prepump_imminent", "prepump_forming"):
            if not prepump_already_sent(load_signals(), ca, "prepump_cleared", now_ts, PREPUMP_DEDUPE_SEC):
                detail = ("Pre-pump CLEARED (was %s @ %s/100 → now %s/100)" % (prev.get("type"), prev.get("score"), result["score"]))
                sigs = load_signals()
                sigs.append({
                    "ts": now_ts, "ca": ca, "symbol": symbol,
                    "type": "prepump_cleared", "src": src,
                    "detail": detail, "score": result["score"],
                    "prev_type": prev.get("type"),
                    "prev_score": prev.get("score"),
                    "window_min": window_min,
                    "price": (token_info or {}).get("price_usd"),
                })
                save_signals(sigs)
                try:
                    msg = format_prepump_cleared_telegram(ca, token_info or {"symbol": symbol}, last_score=prev.get("score"))
                    _queue_or_send(msg)
                except Exception:
                    pass
                result = dict(result)
                result["cleared"] = True
        return result

    sig_type = ("prepump_imminent" if result["tier"] == "imminent" else "prepump_forming")
    if prepump_already_sent(load_signals(), ca, sig_type, now_ts, PREPUMP_DEDUPE_SEC):
        return result
    detail = ("Pre-pump score %s/100 (%s) | compression %s, asymmetry %s, delta %s, accum %s"
              % (result["score"], result["tier"], result["pillars"]["compression"], result["pillars"]["asymmetry"], result["pillars"]["delta"], result["pillars"]["accum"]))
    entry = {"ts": now_ts, "ca": ca, "symbol": symbol, "type": sig_type,
             "src": src, "detail": detail, "score": result["score"],
             "window_min": window_min,
             "price": (token_info or {}).get("price_usd")}
    multi = result.get("multi_tf")
    if multi:
        conf = multi.get("confluence") or {}
        detail += (" | multi-TF %s | confluence: %s" % (multi.get("scores"), conf.get("label", "?")))
        entry["detail"] = detail
        entry["tf_scores"] = multi.get("scores")
        entry["confluence"] = conf.get("status")
    sigs = load_signals()
    sigs.append(entry)
    save_signals(sigs)
    send = True
    if result["tier"] != "imminent":
        send = not _focus_mode()
    if send:
        try:
            msg = format_prepump_telegram(result, ca, token_info, multi=multi)
            _queue_or_send(msg)
        except Exception:
            pass
    return result
