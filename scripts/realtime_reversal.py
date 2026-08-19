#!/usr/bin/env python3
"""Rolling GMGN wash-collapse scanner with transition-only Telegram alerts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import html
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import get_market
from cvd import (_fetch_gmgn_page, _first_nested, _gmgn_trade_key,
                 _normalize_ts, get_gmgn_last_error)
from links import dexscreener_token_url, gmgn_token_url
from price_structure import CONFIRMED, HIGHER_LOW
from reversal_engine import REVERSAL_UP, WASH_WINDOW_SEC, normalize_trade_item
from serok_engine import (BATTLE, NEUTRAL, SIAP2_PUMP, WASPADA_DUMP,
                          all_events, build_bars, classify)
from reversal_state import load_state, save_state, take_new_events, transition
from reversal_status import publish_reversal_status
from signals import _telegram_credentials, send_telegram
from watchlist import load_watchlist

STATE_PATH = os.path.join(ROOT, "last_scan_result.json")
CACHE_PATH = os.path.join(ROOT, ".cache", "reversal_trades.json.gz")
FETCH_HOURS = 48
MAX_PAGES = 200


def _raw_key(raw: dict) -> tuple:
    trade = normalize_trade_item(raw)
    if not trade:
        return ("", "", 0, "")
    explicit = (raw.get("tx_hash") or raw.get("tx_id") or
                raw.get("signature") or raw.get("hash") or raw.get("id"))
    # Cached overlap must de-duplicate deterministically even when GMGN omits a
    # transaction hash (the browser extension can safely use Math.random only
    # because it processes each API record once).
    identity = str(explicit or (
        f"{trade['maker']}:{trade['event']}:{trade['ts']}:"
        f"{trade['sol']:.12g}:{trade['token']:.12g}"))
    return (identity, trade["event"], trade["ts"], trade["maker"])


def fetch_raw_trades(mint: str, *, from_ts: int, to_ts: int,
                     max_pages: int = MAX_PAGES) -> list[dict]:
    """Fetch raw GMGN pages without the old 0.05-SOL dust filter."""
    cursor = None
    seen_cursors = set()
    by_key = {}
    for _ in range(max_pages):
        page, next_cursor = _fetch_gmgn_page(
            mint, cursor=cursor, limit=100, from_ts=from_ts, to_ts=to_ts)
        if page is None:
            detail = get_gmgn_last_error() or "respons kosong sebelum window lengkap"
            raise RuntimeError(detail)
        if not page:
            break
        oldest = to_ts
        for raw in page:
            ts = _normalize_ts(_first_nested(
                raw, "timestamp", "time", "block_time", "created_at"))
            oldest = min(oldest, ts or oldest)
            if from_ts <= ts <= to_ts:
                by_key[_raw_key(raw)] = raw
        if oldest <= from_ts or not next_cursor:
            break
        if next_cursor in seen_cursors:
            raise RuntimeError("cursor GMGN berulang; fetch tidak lengkap")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        raise RuntimeError(f"GMGN menyentuh page cap {max_pages}")
    return list(by_key.values())


def _cache_trade(raw: dict) -> dict | None:
    trade = normalize_trade_item(raw)
    if not trade:
        return None
    return {
        "maker": trade["maker"], "event": trade["event"],
        "quote_amount": trade["sol"], "price_usd": trade["price"],
        "timestamp": trade["ts"], "tx_hash": _raw_key(raw)[0],
        "base_amount": trade["token"], "amount_usd": trade["usd"],
        "tags": trade["tags"],
    }


def load_cache(path: str = CACHE_PATH) -> dict[str, list[dict]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict, path: str = CACHE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(cache, handle, separators=(",", ":"))
    os.replace(tmp, path)


def merge_cache(existing: list[dict], fresh: list[dict], *, cutoff_ts: int) -> list[dict]:
    merged = {}
    for raw in list(existing or ()) + list(fresh or ()):
        compact = _cache_trade(raw)
        if compact and compact["timestamp"] >= cutoff_ts:
            merged[_raw_key(compact)] = compact
    return sorted(merged.values(), key=lambda row: row["timestamp"])


def _market_guards(mint: str, meta: dict, now_ts: int) -> tuple[bool, str, dict]:
    """Apply guards when market metadata is available (never invent values)."""
    try:
        market = get_market(mint) or {}
    except Exception as exc:
        # Liquidity/age guards are conditional on metadata availability. A
        # transient DexScreener outage must not suppress GMGN order-flow scans.
        print(f"{mint[:8]}: market metadata unavailable ({type(exc).__name__})")
        market = {}
    minimum = float((meta or {}).get("min_liquidity_usd") or
                    os.getenv("MIN_LIQUIDITY_USD", "5000"))
    liquidity = float(market.get("liquidity_usd") or market.get("liquidity") or 0)
    if minimum > 0 and liquidity > 0 and liquidity < minimum:
        return False, f"liquidity ${liquidity:,.0f} < ${minimum:,.0f}", market
    created = market.get("pair_created_at") or market.get("created_at")
    try:
        created = int(created or 0)
        if created > 1_000_000_000_000:
            created //= 1000
    except (TypeError, ValueError):
        created = 0
    if created and now_ts - created < 24 * 3600:
        return False, "token/pair belum berumur 24 jam", market
    return True, "", market


def _fmt(value, signed=False, digits=1) -> str:
    try:
        return f"{float(value):+.{digits}f}" if signed else f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def process_telegram_callbacks(state: dict, now_ts: int) -> None:
    """Consume mute button callbacks; harmless when Telegram is unconfigured."""
    token, _chat_id = _telegram_credentials()
    if not token:
        return
    try:
        import requests
        params = {"timeout": 0, "allowed_updates": json.dumps(["callback_query"])}
        offset = int((state.get("_meta") or {}).get("telegram_update_offset") or 0)
        if offset:
            params["offset"] = offset
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params=params, timeout=10)
        updates = (response.json() or {}).get("result") or []
        for update in updates:
            query = update.get("callback_query") or {}
            data = str(query.get("data") or "")
            action, _, mint = data.partition(":")
            if mint and action in ("mute1h", "mute_token"):
                token_state = state.setdefault(mint, {})
                token_state["muted_until"] = (now_ts + 3600 if action == "mute1h"
                                               else 2_147_483_647)
                requests.post(
                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                    json={"callback_query_id": query.get("id"),
                          "text": "Token dibisukan 1 jam" if action == "mute1h"
                                  else "Token dibisukan"}, timeout=10)
            offset = max(offset, int(update.get("update_id") or 0) + 1)
        state.setdefault("_meta", {})["telegram_update_offset"] = offset
    except Exception as exc:
        print(f"Telegram callback poll failed: {exc}")


def _whale_verdict(top_pct: float, churn_pct: float, net_sol: float) -> str:
    """Short Indonesian read of what the dominant wallet is actually doing."""
    if top_pct < 25:
        return "terdistribusi"
    if churn_pct >= 60:
        return "muter sendiri"
    return "akumulasi" if net_sol > 0 else "distribusi"


def _confidence_gap(result: dict) -> str:
    """Explain what is still missing for a watch signal to become strong."""
    if result.get("confidence") == "strong":
        return ""
    current = result.get("current") or {}
    cvd = float(current.get("cvd_delta_clean") or 0)
    wash = float(current.get("wash_pct") or 0)
    need_cvd = 5.0 if result["signal"] == REVERSAL_UP else -5.0
    gaps = []
    if (cvd < need_cvd) if result["signal"] == REVERSAL_UP else (cvd > need_cvd):
        gaps.append(f"CVD bersih {_fmt(cvd, True)} belum {_fmt(need_cvd, True)} SOL")
    if wash > 3:
        gaps.append(f"wash {_fmt(wash)}% belum ≤3%")
    return f" (kurang: {', '.join(gaps)})" if gaps else ""


def format_wallet_lines(current: dict) -> str:
    """Two-line wallet breakdown: quality of buyers, then whale concentration."""
    smart_n = int(current.get("smart_money_buy") or 0)
    fresh_n = int(current.get("fresh_buy") or 0)
    makers = int(current.get("unique_makers") or 0)
    top_pct = float(current.get("top_wallet_pct") or 0)
    top3_pct = float(current.get("top3_wallet_pct") or 0)
    churn = float(current.get("top_wallet_churn_pct") or 0)
    net = float(current.get("top_wallet_net_sol") or 0)
    smart_net = float(current.get("smart_net_sol") or 0)
    fresh_sol = float(current.get("fresh_buy_sol") or 0)
    bot_sell = int(current.get("bot_sell") or 0)
    smart_bias = "net beli" if smart_net > 0 else ("net jual" if smart_net < 0 else "flat")
    return (
        f"👛 Wallet: {makers} maker · smart {smart_n} ({smart_bias} "
        f"{_fmt(smart_net, True)} SOL) · fresh {fresh_n} "
        f"({_fmt(fresh_sol)} SOL) · bot-sell {bot_sell}\n"
        f"🐋 Whale: top-1 {_fmt(top_pct)}% · top-3 {_fmt(top3_pct)}% · "
        f"net {_fmt(net, True)} SOL · churn {churn:.0f}% "
        f"→ {_whale_verdict(top_pct, churn, net)}"
    )


def _fmt_price(value) -> str:
    """Adaptive significant-digit price for SBR zones (microcap-friendly)."""
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return "—"


def _wib_hhmm(ts) -> str:
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "--:--"
    from datetime import timedelta
    when = datetime.fromtimestamp(stamp, timezone.utc).astimezone(
        timezone.utc).replace(tzinfo=None) + timedelta(hours=7)
    return f"{when:%H:%M}"


def format_structure_line(structure: dict | None) -> str:
    """Baris konfirmasi SBR untuk alert (hanya saat struktur CONFIRMED)."""
    struct = structure if isinstance(structure, dict) else {}
    zone = struct.get("zone") or {}
    if struct.get("state") != CONFIRMED or not zone:
        return ""
    up = struct.get("side") != "down"
    if struct.get("low_state") == HIGHER_LOW:
        tag = "higher-low ✓" if up else "lower-high ✓"
    else:
        tag = ""
    action = (f"ter-reclaim {_wib_hhmm(struct.get('reclaim_ts'))}"
              if up else f"tertembus {_wib_hhmm(struct.get('reclaim_ts'))}")
    tail = f" · {tag}" if tag else ""
    return (f"🧱 SBR {_fmt_price(zone.get('low'))}–"
            f"{_fmt_price(zone.get('high'))} {action} WIB{tail}")


def _fmt_mc(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "MC belum tersedia"
    if n <= 0:
        return "MC belum tersedia"
    if n >= 1e9:
        return f"${n / 1e9:.2f}B".replace(".00B", "B")
    if n >= 1e6:
        return f"${n / 1e6:.2f}M".replace(".00M", "M")
    if n >= 1e3:
        return f"${n / 1e3:.1f}K"
    return f"${n:.0f}"


_HARI = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")


def _wib_dt(ts):
    from datetime import timedelta
    return datetime.fromtimestamp(int(ts), timezone.utc).replace(
        tzinfo=None) + timedelta(hours=7)


def _wib_bar(ts) -> str:
    try:
        when = _wib_dt(ts)
    except (TypeError, ValueError, OSError):
        return "—"
    return f"{when:%m-%d %H}:00"


def _wib_range(start, end=None) -> tuple[str, str]:
    try:
        begin = _wib_dt(start)
        finish = _wib_dt(end if end else int(start) + 3600)
    except (TypeError, ValueError, OSError):
        return "—", "—"
    hari = _HARI[begin.weekday()]
    return f"{hari}, {begin:%d %b %Y}", f"{begin:%H:%M}–{finish:%H:%M} WIB"


def _px(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n == 0:
        return "0"
    if abs(n) < 0.01:
        return f"{n:.8f}".rstrip("0").rstrip(".")
    return f"{n:.6g}"


def format_alert(symbol: str, mint: str, result: dict, now_ts: int,
                 structure: dict | None = None) -> str:
    signal = result.get("signal") or NEUTRAL
    event = result.get("event") or {}
    ev = event.get("ev") or {}
    bar = event.get("setup") or result.get("current") or {}
    titles = {
        WASPADA_DUMP: "🔴 WASPADA DUMP",
        SIAP2_PUMP: "🟢 SIAP2 PUMP",
        BATTLE: "⚔️ BATTLE TERJADI",
    }
    title = titles.get(signal, signal)
    from datetime import timedelta
    wib = datetime.fromtimestamp(now_ts, timezone.utc).replace(
        tzinfo=None) + timedelta(hours=7)
    gmgn = html.escape(gmgn_token_url(mint), quote=True)
    dexscreener = html.escape(dexscreener_token_url(mint), quote=True)
    ticker = html.escape(str(symbol or "?").upper())
    bar_start = bar.get("start")
    bar_end = bar.get("end") or ((int(bar_start) + 3600) if bar_start else None)
    day, hours = _wib_range(bar_start, bar_end)
    historical = bool(result.get("historical"))
    age = ("📌 Historis (sudah terjadi di window 48 jam)"
           if historical else "📌 Sinyal baru")
    lines = [
        f"<b>{title} — ${ticker}</b>",
        age,
        "",
        f"🗓 {day}",
        f"⏰ Bar {hours}",
        f"📏 Range harga {_px(bar.get('low'))} — {_px(bar.get('high'))}",
        f"💰 Range MC {_fmt_mc(bar.get('lowMc') or ev.get('rangeLowMc'))} — "
        f"{_fmt_mc(bar.get('highMc') or ev.get('rangeHighMc'))}",
        "",
    ]
    if signal == BATTLE:
        lines += [
            "⚔️ BUY/SELL hampir seimbang · TX, wallet unik, dan fresh_wallet ≥ P65.",
            f"🎯 Pemicu: {html.escape(str(ev.get('triggerSignal') or '—'))} "
            f"{_wib_bar(ev.get('triggerStart'))} WIB · jarak {ev.get('gap', '—')} bar",
            f"📊 {_wib_bar(bar.get('start'))} WIB · BUY {_fmt(bar.get('buySol'))} vs "
            f"SELL {_fmt(bar.get('sellSol'))} SOL · gap {_fmt(ev.get('balanceGapPct'), digits=2)}%",
            f"💰 RANGE BATTLE MC: {_fmt_mc(ev.get('rangeLowMc'))} — {_fmt_mc(ev.get('rangeHighMc'))}",
            f"👥 {int(bar.get('txCount') or 0)} TX (≥{int(ev.get('txFloor') or 0)}) · "
            f"{int(bar.get('uniqueMakers') or 0)} wallet unik "
            f"(≥{int(ev.get('makersFloor') or 0)})",
            f"🌱 fresh {int(bar.get('freshWallets') or 0)} unik / "
            f"{_fmt(bar.get('freshWalletPct'))}% "
            f"(≥{int(ev.get('freshFloor') or 0)})",
            f"📈 harga candle {_fmt(ev.get('setupChg') or bar.get('price_chg_pct'), True)}% · "
            f"wash {_fmt(bar.get('washPct'))}%",
        ]
    else:
        if signal == WASPADA_DUMP:
            lines.append("🔴 Harga naik + cumCVD naik + R ≥10× bar sebelumnya + |R|≥10")
        else:
            lines.append("🟢 Harga turun + cumCVD turun + R ≥10× bar sebelumnya + |R|≥10")
        if ev.get("rMult") is not None:
            lines.append(
                f"📐 R {_fmt(ev.get('prevR'), digits=2)} → "
                f"{_fmt(abs(float(ev.get('setupR') or 0)), digits=2)} "
                f"({_fmt(ev.get('rMult'), digits=1)}×)")
        lines.append(
            f"📊 SETUP {_wib_bar(bar.get('start'))} WIB · harga "
            f"{_fmt(ev.get('setupChg') or bar.get('price_chg_pct'), True)}% · "
            f"R {_fmt(ev.get('setupR'), True, 2)} · CVD "
            f"{_fmt(ev.get('setupCvd') or bar.get('cvdClean'), True)} SOL")
        lines.append(
            f"🧼 wash {_fmt(bar.get('washPct') or result.get('current', {}).get('wash_pct'))}% · "
            f"{int(bar.get('txCount') or result.get('current', {}).get('tx_count') or 0)} TX · "
            f"{int(bar.get('uniqueMakers') or result.get('current', {}).get('unique_makers') or 0)} wallet")
    lines += [
        "",
        f"🕐 Scan {wib:%d %b %H:%M} WIB",
        f'🔗 <a href="{gmgn}">GMGN</a> · '
        f'<a href="{dexscreener}">DEXSCREENER</a>',
    ]
    return "\n".join(lines)


def scan_token(mint: str, meta: dict, *, now_ts: int, cache: dict,
               state: dict, fixture: list[dict] | None = None,
               send_alerts: bool = True) -> dict:
    token_state = state.get(mint) if isinstance(state.get(mint), dict) else {}
    guard_ok, guard_reason, market = _market_guards(mint, meta, now_ts) if fixture is None else (True, "", {})
    events = []
    if not guard_ok:
        result = {"signal": NEUTRAL, "reason": guard_reason, "current": {},
                  "context": {}, "event": None}
    else:
        try:
            old = cache.get(mint, [])
            first_fetch = not old
            last_ts = max((int(row.get("timestamp") or 0) for row in old), default=0)
            window_start = now_ts - FETCH_HOURS * 3600
            from_ts = window_start if first_fetch else max(
                window_start, last_ts - WASH_WINDOW_SEC * 2)
            fresh = fixture if fixture is not None else fetch_raw_trades(
                mint, from_ts=from_ts, to_ts=now_ts)
            cache[mint] = merge_cache(old, fresh, cutoff_ts=window_start)
            mc = float((market or {}).get("marketcap") or 0)
            price = float((market or {}).get("price_usd") or 0)
            supply = (mc / price) if mc > 0 and price > 0 else 0.0
            bars = build_bars(cache[mint], now_ts=now_ts, mc_usd=mc, supply=supply)
            classified = classify(bars)
            events = all_events(bars)
            result = {
                "signal": classified["signal"],
                "reason": classified.get("reason") or "",
                "current": classified.get("current") or {},
                "context": {},
                "event": classified.get("event"),
                "event_id": classified.get("event_id"),
                "confidence": "info",
                "events": events,
            }
        except Exception as exc:  # noqa: BLE001 — token stays on the dashboard
            detail = (get_gmgn_last_error() or "").strip()
            text = " ".join(str(exc).split())
            if detail and detail not in text:
                text = f"{text} ({detail})" if text else detail
            if len(text) > 280:
                text = text[:277] + "..."
            result = {
                "signal": NEUTRAL,
                "reason": f"GMGN fetch gagal: {text or type(exc).__name__}",
                "current": {}, "context": {}, "event": None,
            }
            events = []

    new_state, _legacy_alert = transition(
        token_state, result["signal"], now_ts,
        event_id=result.get("event_id"))
    new_state, pending = take_new_events(new_state, events)
    current = result.get("current") or {}
    context = result.get("context") or {}
    new_state["structure"] = None
    new_state["result"] = {
        "signal": result["signal"], "bias": result.get("bias"),
        "confidence": result.get("confidence"), "reason": result.get("reason"),
        "current": current, "context": context,
        "event": result.get("event"), "event_id": result.get("event_id"),
    }
    state[mint] = new_state
    symbol = str((meta or {}).get("symbol") or mint[:8])
    muted = now_ts < int(new_state.get("muted_until") or 0)
    sent = 0
    if send_alerts and not muted:
        buttons = {"inline_keyboard": [[
            {"text": "🔕 Mute 1h", "callback_data": f"mute1h:{mint}"},
            {"text": "🔇 Mute token", "callback_data": f"mute_token:{mint}"},
            {"text": "📊 Buka chart", "url": f"https://gmgn.ai/sol/token/{mint}"},
        ]]}
        latest_start = (result.get("event") or {}).get("setup", {}).get("start")
        for event in pending:
            bar_start = (event.get("setup") or {}).get("start")
            historical = bool(bar_start and latest_start
                              and bar_start != latest_start)
            payload = {
                **result,
                "signal": event.get("signal"),
                "event": event,
                "event_id": event.get("event_id"),
                "historical": historical,
            }
            if send_telegram(format_alert(symbol, mint, payload, now_ts),
                             reply_markup=buttons):
                sent += 1
    new_state["alert_sent"] = sent > 0
    new_state["alerts_sent"] = sent
    return {"mint": mint, "symbol": symbol, "signal": result["signal"],
            "should_alert": bool(pending), "state": new_state["state"],
            "reason": result.get("reason", ""), "alerts": sent,
            "pending": len(pending)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", help="offline GMGN JSON fixture")
    parser.add_argument("--mint", help="scan only one mint")
    parser.add_argument("--no-alert", action="store_true")
    parser.add_argument("--now-ts", type=int)
    args = parser.parse_args(argv)

    watchlist = load_watchlist()
    fixture = None
    if args.fixture:
        with open(args.fixture, encoding="utf-8") as handle:
            payload = json.load(handle)
        fixture = payload.get("history", payload) if isinstance(payload, dict) else payload
    if args.mint:
        watchlist = {args.mint: watchlist.get(args.mint, {"symbol": args.mint[:8]})}
    if fixture is not None and not watchlist:
        mint = args.mint or "fixture"
        watchlist = {mint: {"symbol": "FIXTURE"}}

    now_ts = int(args.now_ts or (max((_normalize_ts(row.get("timestamp")) for row in fixture), default=0)
                                 if fixture is not None else time.time()))
    state = load_state(STATE_PATH) if fixture is None else {}
    cache = load_cache() if fixture is None else {}
    if fixture is None:
        process_telegram_callbacks(state, now_ts)
    print(f"Realtime reversal scan @ {datetime.fromtimestamp(now_ts, timezone.utc).isoformat()}")
    failed = False
    succeeded = 0
    for mint, meta in watchlist.items():
        try:
            row = scan_token(mint, meta or {}, now_ts=now_ts, cache=cache,
                             state=state, fixture=fixture,
                             send_alerts=not args.no_alert)
            succeeded += 1
            print(f"{row['symbol']}: {row['signal']} -> {row['state']} | {row['reason']}")
        except Exception as exc:  # one token must not abort the watchlist
            failed = True
            print(f"{mint[:8]}: ERROR {type(exc).__name__}: {exc}")
    if fixture is None:
        save_cache(cache)
        state.setdefault("_meta", {}).update(
            updated_at=now_ts, scanner="serok-1h-v1")
        save_state(STATE_PATH, state)
        # Streamlit reads this snapshot via GitHub — Actions cache alone
        # never reached the main watchlist page.
        publish_reversal_status(state, watchlist)
    if failed:
        print(f"scan: {succeeded} token ok; errors logged above "
              "(job stays green so the dashboard still gets a snapshot)")
    # Fetch/classify failures are recorded as NETRAL + reason. Never fail
    # the Actions job: an empty watchlist used to no-op to 0, and a red
    # scan after adding MOMO hid the token from last_scan_result.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
