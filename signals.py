# -*- coding: utf-8 -*-
"""Daily CVD and first-buy-surge signal persistence and Telegram delivery."""
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
PREPUMP_SCHEMA_VERSION = 2
PREPUMP_CHECK_TOTAL = 6
# Kept only as a compatibility constant for archived detector imports; the
# daily CVD path below does not use the old detector.
PREPUMP_DEDUPE_SEC = 20 * 3600
_DIGEST_BUF = []
_DIGEST_MODE = False

# ============================================================
# 🚨 RISK WARNING TEMPLATE - BESAR BOLD MERAH + ANIMASI 🚨
# Ini muncul di SEMUA notifikasi Telegram biar tidak lupa!
# ============================================================
RISK_EMOJI_LINE = "🚨" * 20
RISK_STOP_LINE = "⛔" * 12
RISK_ANIM_LINE = "⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️🔴"
RISK_DANGER_LINE = "🟥" * 14

# Template utama - dipakai di semua notif Telegram
# Telegram HTML tidak support warna/size, jadi pakai:
# <b> = bold besar, 🟥🔴 = simulasi warna merah, emoji = animasi visual
RISK_WARNING_BLOCK = (
    f"{RISK_EMOJI_LINE}\n"
    f"⛔⛔⛔ <b>⚠️⚠️⚠️ BACA INI!!!! ⚠️⚠️⚠️</b> ⛔⛔⛔\n"
    f"{RISK_EMOJI_LINE}\n"
    f"{RISK_ANIM_LINE}\n\n"
    f"{RISK_DANGER_LINE}\n"
    f"🟥 <b>🔴🔴🔴 PERINGATAN KERAS 🔴🔴🔴</b> 🟥\n"
    f"{RISK_DANGER_LINE}\n\n"
    f"🔴 <b>❗❗ SELALU HITUNG RISK JANGAN TERLALU BESAR, JANGAN TERJEBAK LAGI ❗❗</b> 🔴\n\n"
    f"🔴 <b>❗❗ SELALU PASANG BAGIAN BAWAH LEBIH BESAR KARENA HARGA TURUN ITU PASTI, HARGA NAIK HANYA KEMUNGKINAN ❗❗</b> 🔴\n\n"
    f"🔴 <b>❗❗ BACA INI!!!! ❗❗</b> 🔴\n\n"
    f"⚠️⚠️⚠️ <b>👉 RISK MANAGEMENT NO.1 - JANGAN SERAKAH 👈</b> ⚠️⚠️⚠️\n"
    f"{RISK_ANIM_LINE}\n"
    f"{RISK_EMOJI_LINE}\n"
)

# Versi compact untuk daily / no-setup (lebih pendek biar tidak spam)
RISK_WARNING_COMPACT = (
    f"🚨🚨🚨 <b>⚠️ BACA INI!!!! ⚠️</b> 🚨🚨🚨\n"
    f"🟥 <b>🔴 SELALU HITUNG RISK JANGAN TERLALU BESAR, JANGAN TERJEBAK LAGI 🔴</b> 🟥\n"
    f"🟥 <b>🔴 SELALU PASANG BAGIAN BAWAH LEBIH BESAR KARENA HARGA TURUN ITU PASTI, HARGA NAIK HANYA KEMUNGKINAN 🔴</b> 🟥\n"
    f"🟥 <b>🔴 BACA INI!!!! 🔴</b> 🟥\n"
    f"⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️🔴⚠️\n"
)


_SIGNALS_CACHE = {"data": None, "ts": 0.0}
_SIGNALS_TTL = 30
_SIGNALS_REMOTE = (
    "https://raw.githubusercontent.com/lparmycalprut/wallet-depth"
    "/main/signals.json"
)


def _read_local_signals():
    try:
        with open(SIGNALS_PATH, encoding="utf-8") as f:
            data = json.load(f) or []
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _newest_ts(items):
    newest = 0
    for item in items or []:
        try:
            ts = int((item or {}).get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts > newest:
            newest = ts
    return newest


def _pull_remote_signals():
    """Best-effort live copy from main so Cloud is not stuck on a stale checkout."""
    now = time.time()
    cached = _SIGNALS_CACHE.get("data")
    if cached is not None and (now - _SIGNALS_CACHE.get("ts", 0)) < _SIGNALS_TTL:
        return cached
    try:
        r = requests.get(
            _SIGNALS_REMOTE,
            params={"t": int(now)},
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                _SIGNALS_CACHE["data"] = data
                _SIGNALS_CACHE["ts"] = now
                return data
    except Exception:
        pass
    return cached


def load_signals():
    local = _read_local_signals()
    remote = _pull_remote_signals()
    if remote and _newest_ts(remote) > _newest_ts(local):
        return remote
    return local


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


def drain_digest():
    """Drop any queued digest messages without sending (manual test runs)."""
    global _DIGEST_MODE, _DIGEST_BUF
    _DIGEST_BUF = []
    _DIGEST_MODE = False


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


def record_daily_cvd(ca, symbol, rows, *, now_ts=None, price=None,
                     replace_existing=False):
    """Record one daily CVD result; optionally refresh the same UTC date."""
    now_ts = int(now_ts or time.time())
    latest = (rows or [])[-1] if rows else {}
    sig = {"ts": now_ts, "ca": ca, "symbol": symbol, "type": "cvd_daily",
           "src": "gmgn_extension_model", "daily": True,
           "date": latest.get("date"), "status": latest.get("status"),
           "detail": latest, "price": price, "complete_day": True}
    if not latest.get("date"):
        # No complete UTC day yet — nothing trustworthy to record.
        return latest
    items = load_signals()
    matches = [
        idx for idx, item in enumerate(items)
        if item.get("ca") == ca and item.get("type") == "cvd_daily"
        and item.get("date") == latest["date"] and item.get("complete_day")
    ]
    # A manual force refresh must persist the newly fetched daily metrics,
    # rather than silently retaining the first record written for that date.
    if replace_existing and matches:
        items = [
            item for item in items
            if not (item.get("ca") == ca and item.get("type") == "cvd_daily"
                    and item.get("date") == latest["date"])
        ]
        items.append(sig)
        save_signals(items)
    elif not matches:
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
    text = (
            f"{RISK_WARNING_BLOCK}\n\n"
            f"{icon} <b>DAILY CVD · {symbol}</b>\n"
            f"<code>{ca}</code>\n\n"
            f"<b>{latest.get('status', 'NORMAL')}</b>\n"
            f"📅 {latest.get('date', '-')} (hari UTC penuh)  ·  "
            f"🔁 {latest.get('total_tx', 0):,} TX\n"
            f"💧 Volume <b>{latest.get('volume_sol', 0):,.2f} SOL</b> ({change_text} vs H-1)\n"
            f"⚖️ CVD <b>{latest.get('delta_sol', 0):+,.2f} SOL</b> · ratio {latest.get('cvd_ratio_pct', 0):+.1f}%\n"
            f"🟢 Buy {latest.get('buy_tx', 0):,} · 🔴 Sell {latest.get('sell_tx', 0):,}\n\n"
            f"<a href='https://dexscreener.com/solana/{ca}'>DexScreener</a>  ·  <a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>\n\n"
            f"{RISK_WARNING_COMPACT}")
    _queue_or_send(text)


def is_complete_daily_pass(evaluation) -> bool:
    """True when Setup Emas (6/6 scored checks) fired on a finished UTC day.

    Telegram is reserved for this case. WATCH / FAIL / STEALTH DUMP and
    intra-day partial prints never notify.
    """
    try:
        from prepump_detector import is_setup_emas
        return bool(is_setup_emas(evaluation))
    except Exception:
        ev = evaluation or {}
        if ev.get("stealth_dump") or not ev.get("date"):
            return False
        if ev.get("verdict") not in ("SETUP EMAS", "PASS"):
            return False
        try:
            passed = int(ev.get("passed") or 0)
            total = int(ev.get("total") or 6)
        except (TypeError, ValueError):
            return False
        return passed >= 6 and total >= 6 and passed >= total


def _telegram_already_sent(ca, date, *, kind="prepump_4pilar") -> bool:
    items = _read_local_signals()
    return any(
        x.get("ca") == ca and x.get("type") == kind
        and x.get("date") == date and x.get("telegram_sent")
        for x in items[-500:]
    )


def _mark_telegram_sent(ca, date, *, kind="prepump_4pilar") -> None:
    items = _read_local_signals()
    changed = False
    for item in reversed(items[-500:]):
        if (item.get("ca") == ca and item.get("type") == kind
                and item.get("date") == date):
            if not item.get("telegram_sent"):
                item["telegram_sent"] = True
                changed = True
            break
    if changed:
        save_signals(items)


def maybe_queue_complete_prepump(ca, symbol, evaluation, *, price=None):
    """Queue Telegram only when every daily pillar is complete.

    Deduped once per CA + UTC date so a manual CVD re-fetch and the
    07:00 WIB digest cannot spam the same PASS.
    """
    if not is_complete_daily_pass(evaluation):
        return False
    date = evaluation.get("date")
    if _telegram_already_sent(ca, date):
        return False
    sent = queue_prepump_4pilar_message(
        ca, symbol, evaluation, price=price)
    if sent:
        _mark_telegram_sent(ca, date)
    return bool(sent)


def _is_current_prepump_schema(item):
    """Return whether a stored signal uses the six scored-check format."""
    detail = (item or {}).get("detail") or {}
    checks = detail.get("checks") or []
    ids = {check.get("id") for check in checks}
    try:
        total = int((item or {}).get("total") or 0)
        version = int((item or {}).get("schema_version") or 0)
    except (TypeError, ValueError):
        return False
    return (version >= PREPUMP_SCHEMA_VERSION
            and total == PREPUMP_CHECK_TOTAL
            and len(checks) == PREPUMP_CHECK_TOTAL
            and "p3_lock" not in ids)


def record_prepump_4pilar(ca, symbol, evaluation, *, now_ts=None, price=None,
                           replace_existing=False):
    """Persist a daily evaluation and migrate legacy seven-check records.

    The normal cron remains idempotent for records already using the current
    six-check schema. A legacy same-day row is always replaced, while a manual
    force refresh can replace any same-day row with newly fetched metrics.
    """
    now_ts = int(now_ts or time.time())
    ev = evaluation or {}
    date = ev.get("date")
    if not date:
        return ev
    sig = {
        "ts": now_ts,
        "ca": ca,
        "symbol": symbol,
        "type": "prepump_4pilar",
        "src": "four_pillar",
        "schema_version": PREPUMP_SCHEMA_VERSION,
        "daily": True,
        "date": date,
        "verdict": ev.get("verdict"),
        "phase": ev.get("phase"),
        "passed": ev.get("passed"),
        "total": ev.get("total", PREPUMP_CHECK_TOTAL),
        "score": ev.get("score"),
        "setup_emas": bool(ev.get("setup_emas")),
        "stealth_dump": bool(ev.get("stealth_dump")),
        "detail": {
            "metrics": ev.get("metrics") or {},
            "pillars": ev.get("pillars") or [],
            "checks": ev.get("checks") or [],
            "holder_lock_pct": ev.get("holder_lock_pct"),
        },
        "price": price,
        "complete_day": True,
    }
    items = load_signals()
    matches = [
        item for item in items
        if item.get("ca") == ca and item.get("type") == "prepump_4pilar"
        and item.get("date") == date
    ]
    migrate_legacy = any(not _is_current_prepump_schema(item)
                         for item in matches)
    if not matches or replace_existing or migrate_legacy:
        # Keep Telegram dedupe state when replacing a row. Without this, a
        # format-only migration could resend an already delivered Setup Emas.
        telegram_sent = any(item.get("telegram_sent") for item in matches)
        if telegram_sent:
            sig["telegram_sent"] = True
        items = [
            item for item in items
            if not (item.get("ca") == ca
                    and item.get("type") == "prepump_4pilar"
                    and item.get("date") == date)
        ]
        items.append(sig)
        save_signals(items)
    try:
        from cvd_daily import persist_daily_snapshot
        persist_daily_snapshot(ca, symbol, ev.get("daily_rows") or [],
                               now_ts=now_ts)
    except Exception:
        pass
    return ev


def queue_no_setup_message(date, *, n_tokens=0):
    """Queue the empty-morning notice. Deduped once per UTC date."""
    if not date:
        return False
    if _telegram_already_sent("_digest_", date, kind="setup_emas_empty"):
        return False
    text = (
        f"{RISK_WARNING_BLOCK}\n\n"
        f"⚪ <b>TIDAK ADA SETUP HARI INI</b>\n"
        f"📅 {date} (hari UTC penuh)\n"
        f"Watchlist dipindai: {int(n_tokens)} token.\n"
        f"Tidak ada yang lolos 6/6 Setup Emas.\n\n"
        f"{RISK_WARNING_COMPACT}"
    )
    sent = _queue_or_send(text)
    if sent:
        items = _read_local_signals()
        items.append({
            "ts": int(time.time()),
            "ca": "_digest_",
            "symbol": "-",
            "type": "setup_emas_empty",
            "date": date,
            "telegram_sent": True,
            "daily": True,
        })
        save_signals(items)
    return bool(sent)


def queue_prepump_4pilar_message(ca, symbol, evaluation, *, price=None):
    ev = evaluation or {}
    if not ev:
        return
    verdict = ev.get("verdict") or "FAIL"
    stealth = bool(ev.get("stealth_dump"))
    if stealth or verdict == "STEALTH DUMP":
        icon = "🔴"
    elif verdict in ("SETUP EMAS", "PASS"):
        icon = "🥇"
    elif verdict == "WATCH":
        icon = "🟡"
    else:
        icon = "⚪"
    metrics = ev.get("metrics") or {}
    absorption = metrics.get("absorption_pct", 0.0)
    buy_pct = metrics.get("buy_tx_pct", 0.0)
    sell_pct = metrics.get("sell_tx_pct")
    if sell_pct is None:
        sell_pct = 100.0 - float(buy_pct or 0)
    avg_buy = metrics.get("avg_buy_sol", 0.0)
    avg_sell = metrics.get("avg_sell_sol", 0.0)
    change = metrics.get("volume_change_pct")
    change_txt = "n/a" if change is None else f"{change:+.1f}%"
    check_bits = []
    for item in ev.get("checks") or ev.get("pillars") or []:
        mark = "✅" if item.get("passed") else "❌"
        check_bits.append(
            f"{mark} {item.get('title') or item.get('id', '?')}"
        )
    score = ev.get("score")
    score_txt = f" · skor {int(score)}" if score is not None else ""
    lock = ev.get("holder_lock_pct")
    lock_txt = (f"🔒 Retensi Top-100 <b>{float(lock):.1f}%</b> (info)\n"
                if lock is not None else "")
    text = (
        f"{RISK_WARNING_BLOCK}\n\n"
        f"{icon} <b>SETUP EMAS · {symbol}</b>\n"
        f"<code>{ca}</code>\n\n"
        f"<b>{verdict}</b> · {ev.get('phase', '-')}{score_txt}\n"
        f"📅 {ev.get('date', '-')}  ·  "
        f"{int(ev.get('passed') or 0)}/{int(ev.get('total') or 6)} cek\n"
        f"💧 |CVD/Vol| <b>{absorption:.2f}%</b> "
        f"(ambang &lt; 3.0%)\n"
        f"Buy TX <b>{buy_pct:.1f}%</b> vs "
        f"Sell TX <b>{float(sell_pct):.1f}%</b> "
        f"({int(metrics.get('buy_tx') or 0)}/"
        f"{int(metrics.get('sell_tx') or 0)})\n"
        f"Avg S {avg_sell:.3f} / B {avg_buy:.3f} SOL\n"
        f"📉 Vol vs H-1 {change_txt}\n"
        f"{lock_txt}"
        f"{' · '.join(check_bits)}\n\n"
        f"<a href='https://dexscreener.com/solana/{ca}'>DexScreener</a>  ·  "
        f"<a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>\n\n"
        f"{RISK_WARNING_BLOCK}"
    )
    return _queue_or_send(text)


def record_first_buy_surge(ca, symbol, stats, *, now_ts=None, price=None,
                           cooldown_sec=4 * 3600):
    """Record & broadcast a First Buy Surge (awal fase MARK-UP) alert.

    ``stats`` adalah hasil ``cvd_daily.first_buy_surge``. Dedupe per CA selama
    ``cooldown_sec`` (default 4 jam — lonjakan pertama adalah momen sekali,
    bukan alarm berulang tiap 15 menit).
    """
    now_ts = int(now_ts or time.time())
    items = load_signals()
    if any(x.get("ca") == ca and x.get("type") == "first_buy_surge"
           and now_ts - int(x.get("ts", 0)) < cooldown_sec
           for x in items[-300:]):
        return False
    items.append({"ts": now_ts, "ca": ca, "symbol": symbol,
                  "type": "first_buy_surge", "src": "priority_15m",
                  "daily": False, "detail": stats, "price": price})
    save_signals(items)
    surge = stats.get("surge_pct")
    base = stats.get("baseline_hourly_sol")
    surge_txt = (f"{surge:+,.0f}% vs baseline kering {base:,.2f} SOL/jam"
                 if surge is not None and base is not None
                 else "baseline kering n/a")
    text = (
            f"{RISK_WARNING_BLOCK}\n\n"
            f"🚀 <b>FIRST BUY SURGE · {symbol}</b> 🚀\n"
            f"<code>{ca}</code>\n\n"
            f"<b>Awal fase MARK-UP terdeteksi</b> (token sebelumnya kering)\n\n"
            f"📊 Volume {stats.get('window_sec', 900) // 60}m "
            f"<b>{stats.get('volume_sol', 0):,.2f} SOL</b> ({surge_txt})\n"
            f"🟢 Buy ratio <b>{stats.get('buy_ratio_pct', 0):.0f}%</b> "
            f"({stats.get('buy_tx', 0)}/{stats.get('tx', 0)} TX · "
            f"{stats.get('unique_buy_wallets', 0)} wallet unik)\n"
            f"⚖️ CVD velocity <b>{stats.get('cvd_ratio_pct', 0):+.1f}%</b> "
            f"(Δ {stats.get('cvd_sol', 0):+,.2f} SOL)\n"
            f"🐋 Big-buy cluster: <b>{stats.get('big_buys', 0)}x</b> "
            f"≥{stats.get('big_buy_sol', 1):g} SOL "
            f"({stats.get('big_buy_sol_total', 0):,.2f} SOL) · "
            f"big-sell {stats.get('big_sells', 0)}x\n\n"
            f"<a href='https://dexscreener.com/solana/{ca}'>DexScreener</a>  ·  "
            f"<a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>\n\n"
            f"{RISK_WARNING_BLOCK}")
    return bool(_queue_or_send(text))
