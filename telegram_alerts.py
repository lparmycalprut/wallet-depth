# -*- coding: utf-8 -*-
"""Telegram rules and transport for holder-dust scans.

The rule functions are deliberately independent from the HTTP transport so a
scan can be evaluated in unit tests without sending a Telegram request. Dust
changes are *percentage-point* changes of ``dust_pct_mc``, never relative
percentage changes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import os
import sys
import time
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import requests

DUMP_THRESHOLD_PP = 0.25
ACCUMULATION_THRESHOLD_PP = 0.50
BASELINE_SHIFT_THRESHOLD_PP = 1.00
ALERT_WINDOW_SEC = 4 * 3600
# The scheduled job runs every 15 minutes. Allow a delayed run while still
# rejecting a recent snapshot or a stale snapshot after a long outage.
ALERT_WINDOW_MIN_SEC = ALERT_WINDOW_SEC - 15 * 60
ALERT_WINDOW_MAX_SEC = ALERT_WINDOW_SEC + 60 * 60
EVENT_BUCKET_SEC = ALERT_WINDOW_SEC

# Two compact anchors are persisted per token: the immutable initial snapshot
# and a rolling ~4-hour snapshot. Current analysis may temporarily include the
# union of addresses from both anchors so movements can be classified.
MAX_STORED_WALLETS = 300
# Union of two 300-wallet anchors plus room for newly observed wallets.
MAX_COMPARISON_WALLETS = 800
MAX_SENT_EVENT_IDS = 96
BALANCE_EPSILON = 1e-12
STATE_KEY = "alert_state"


def _float(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _int(value, default=0) -> int:
    number = _float(value, None)
    return int(number) if number is not None else int(default)


def _address(value) -> str:
    # Wallet/mint addresses in this repository are Solana Base58 and therefore
    # case-sensitive. Whitespace is still never part of an address.
    return str(value or "").strip()


def build_wallet_snapshot(holders: Iterable[dict] | None, *,
                          dust_pct_mc=None, dust_limit_usd: float = 10.0,
                          tracked_addresses=None, ts: int | None = None,
                          max_wallets: int = MAX_COMPARISON_WALLETS,
                          truncated: bool = False) -> dict:
    """Build the bounded balance payload needed by alert comparisons.

    Previously tracked addresses are included with balance zero when no longer
    present so a dust wallet that sold everything can be distinguished. New
    dust wallets and largest remaining wallets fill the bounded payload.
    """
    rows: dict[str, tuple[float, float]] = {}
    for raw in holders or []:
        if not isinstance(raw, dict) or not raw.get("is_wallet"):
            continue
        address = _address(raw.get("address"))
        balance = _float(raw.get("balance"), 0.0) or 0.0
        usd_value = _float(raw.get("usd_value"), 0.0) or 0.0
        if not address or balance <= 0:
            continue
        # Holder fetchers already deduplicate owners. max() is a safe guard
        # against malformed duplicate rows without inflating token balances.
        old = rows.get(address)
        if old is None or balance > old[0]:
            rows[address] = (balance, usd_value)

    dust_limit = max(0.0, _float(dust_limit_usd, 10.0) or 10.0)
    current_dust = {
        address for address, (_balance, usd) in rows.items()
        if 0 < usd <= dust_limit
    }
    tracked = []
    tracked_seen = set()
    for raw in tracked_addresses or []:
        address = _address(raw)
        if address and address not in tracked_seen:
            tracked.append(address)
            tracked_seen.add(address)

    limit = max(1, min(_int(max_wallets, MAX_COMPARISON_WALLETS),
                       MAX_COMPARISON_WALLETS))
    # Priority: retain old addresses for movement comparison, then reserve
    # roughly half of the remaining room for current dust and use the rest for
    # largest balances. This keeps new wallets observable even when two old
    # anchors together contain hundreds of different addresses.
    tracked = tracked[:limit]
    room = max(0, limit - len(tracked))
    dust_ranked = sorted(current_dust, key=lambda address: (
        -rows[address][1], address))
    priority = list(tracked)
    priority += dust_ranked[:max(1, room // 2)] if room else []
    priority += sorted(rows, key=lambda address: (-rows[address][0], address))
    priority += dust_ranked

    selected: list[str] = []
    selected_set: set[str] = set()
    for address in priority:
        if address in selected_set:
            continue
        selected.append(address)
        selected_set.add(address)
        if len(selected) >= limit:
            break

    balances = {
        address: rows.get(address, (0.0, 0.0))[0]
        for address in selected
    }
    return {
        "ts": _int(ts or time.time()),
        "dust_pct_mc": _float(dust_pct_mc, None),
        "balances": balances,
        "dust": sorted(address for address in selected_set
                       if address in current_dust),
        "wallets_seen": len(rows),
        "truncated": bool(truncated),
    }


def _snapshot_balances(snapshot: dict | None) -> dict[str, float]:
    balances = {}
    for raw_address, raw_balance in ((snapshot or {}).get("balances") or {}).items():
        address = _address(raw_address)
        balance = _float(raw_balance, None)
        if address and balance is not None and balance >= 0:
            balances[address] = balance
    return balances


def compact_wallet_snapshot(snapshot: dict | None,
                            max_wallets: int = MAX_STORED_WALLETS) -> dict:
    """Bound an alert anchor while retaining both dust and large wallets."""
    snapshot = snapshot or {}
    balances = _snapshot_balances(snapshot)
    # Zeros are useful only in the transient current comparison; persisting
    # them would make a missing wallet look like a real historical holder.
    balances = {address: value for address, value in balances.items()
                if value > BALANCE_EPSILON}
    dust = {address for address in (snapshot.get("dust") or [])
            if address in balances}
    limit = max(1, min(_int(max_wallets, MAX_STORED_WALLETS),
                       MAX_STORED_WALLETS))
    dust_quota = max(1, limit // 2)
    priority = sorted(dust, key=lambda address: (-balances[address], address))[
        :dust_quota]
    priority += sorted(balances, key=lambda address: (-balances[address], address))
    priority += sorted(dust, key=lambda address: (-balances[address], address))

    selected = []
    seen = set()
    for address in priority:
        if address in seen:
            continue
        selected.append(address)
        seen.add(address)
        if len(selected) >= limit:
            break
    return {
        "ts": _int(snapshot.get("ts")),
        "dust_pct_mc": _float(snapshot.get("dust_pct_mc"), None),
        "balances": {address: balances[address] for address in selected},
        "dust": sorted(address for address in selected if address in dust),
        "wallets_seen": max(0, _int(snapshot.get("wallets_seen"), len(balances))),
        "truncated": bool(snapshot.get("truncated")),
    }


def tracked_wallet_addresses(state: dict | None) -> list[str]:
    """Addresses needed to compare current balances to both saved anchors."""
    out = []
    seen = set()
    for name in ("baseline", "rolling"):
        for address in _snapshot_balances((state or {}).get(name)):
            if address not in seen:
                out.append(address)
                seen.add(address)
            if len(out) >= MAX_COMPARISON_WALLETS:
                return out
    return out


def wallet_movements(previous: dict | None, current: dict | None) -> dict:
    """Summarize balance changes and movement into/out of the dust group."""
    before = _snapshot_balances(previous)
    after = _snapshot_balances(current)
    previous_dust = {_address(a) for a in ((previous or {}).get("dust") or [])
                     if _address(a)}
    current_dust = {_address(a) for a in ((current or {}).get("dust") or [])
                    if _address(a)}

    common = set(before) & set(after)
    increased = {
        address for address in common
        if before[address] > BALANCE_EPSILON
        and after[address] > before[address] + BALANCE_EPSILON
    }
    decreased = {
        address for address in common
        if after[address] + BALANCE_EPSILON < before[address]
    }
    new_wallets = {
        address for address, balance in after.items()
        if balance > BALANCE_EPSILON and address not in before
    }

    exited = previous_dust - current_dust
    dust_grew_out = {
        address for address in exited
        if after.get(address, 0.0) > before.get(address, 0.0) + BALANCE_EPSILON
    }
    dust_sold_out = {
        address for address in exited
        if after.get(address, 0.0) <= BALANCE_EPSILON
    }
    dust_left_other = exited - dust_grew_out - dust_sold_out

    entered = current_dust - previous_dust
    larger_shrank_into_dust = {
        address for address in entered
        if address in before
        and after.get(address, 0.0) + BALANCE_EPSILON < before[address]
    }
    new_dust = {address for address in entered if address not in before}
    dust_entered_other = entered - larger_shrank_into_dust - new_dust

    return {
        "increased": len(increased),
        "decreased": len(decreased),
        "new_wallets": len(new_wallets),
        "dust_grew_out": len(dust_grew_out),
        "dust_sold_out": len(dust_sold_out),
        "dust_left_other": len(dust_left_other),
        "larger_shrank_into_dust": len(larger_shrank_into_dust),
        "new_dust": len(new_dust),
        "dust_entered_other": len(dust_entered_other),
        "compared_wallets": len(common),
    }


def is_valid_4h_snapshot(previous: dict | None, current: dict | None) -> bool:
    """Whether *previous* is close enough to four hours before *current*."""
    age = _int((current or {}).get("ts")) - _int((previous or {}).get("ts"))
    return ALERT_WINDOW_MIN_SEC <= age <= ALERT_WINDOW_MAX_SEC


def _event_id(mint: str, kind: str, current_ts: int,
              direction: str = "") -> str:
    bucket = max(0, _int(current_ts)) // EVENT_BUCKET_SEC
    suffix = f":{direction}" if direction else ""
    return f"holder-dust:{_address(mint)}:{kind}:{bucket}{suffix}"


def _event(kind: str, previous: dict, current: dict, *, mint: str,
           symbol: str, scope: str) -> dict:
    old = _float(previous.get("dust_pct_mc"), 0.0) or 0.0
    new = _float(current.get("dust_pct_mc"), 0.0) or 0.0
    change = new - old
    movement = wallet_movements(previous, current)
    direction = "up" if change >= 0 else "down"
    return {
        "id": _event_id(mint, kind, _int(current.get("ts")),
                        direction if kind == "baseline_shift" else ""),
        "kind": kind,
        "scope": scope,
        "mint": _address(mint),
        "symbol": str(symbol or "?").strip().upper() or "?",
        "previous_dust_pct_mc": old,
        "current_dust_pct_mc": new,
        "change_pp": change,
        "previous_ts": _int(previous.get("ts")),
        "current_ts": _int(current.get("ts")),
        "wallet_increases": movement["increased"],
        "movements": movement,
    }


def evaluate_4h_rules(previous: dict | None, current: dict | None, *,
                      mint: str, symbol: str = "?",
                      sent_event_ids=()) -> list[dict]:
    """Evaluate dump/accumulation rules against one valid ~4-hour anchor."""
    if not is_valid_4h_snapshot(previous, current):
        return []
    old = _float((previous or {}).get("dust_pct_mc"), None)
    new = _float((current or {}).get("dust_pct_mc"), None)
    if old is None or new is None:
        return []
    change = new - old
    movement = wallet_movements(previous, current)
    events = []
    if change + BALANCE_EPSILON >= DUMP_THRESHOLD_PP:
        events.append(_event("dump", previous, current, mint=mint,
                             symbol=symbol, scope="~4 jam"))
    if (-change + BALANCE_EPSILON >= ACCUMULATION_THRESHOLD_PP
            and movement["increased"] > 0):
        events.append(_event("accumulation", previous, current, mint=mint,
                             symbol=symbol, scope="~4 jam"))
    sent = set(sent_event_ids or [])
    return [event for event in events if event["id"] not in sent]


def evaluate_baseline_rule(baseline: dict | None, current: dict | None, *,
                           mint: str, symbol: str = "?",
                           sent_event_ids=()) -> list[dict]:
    """Alert when dust moved at least ±1 point from the initial snapshot."""
    old = _float((baseline or {}).get("dust_pct_mc"), None)
    new = _float((current or {}).get("dust_pct_mc"), None)
    if old is None or new is None:
        return []
    if abs(new - old) + BALANCE_EPSILON < BASELINE_SHIFT_THRESHOLD_PP:
        return []
    event = _event("baseline_shift", baseline, current, mint=mint,
                   symbol=symbol, scope="sejak snapshot awal")
    return [] if event["id"] in set(sent_event_ids or []) else [event]


def evaluate_alert_events(mint: str, analysis: dict,
                          state: dict | None = None) -> tuple[list[dict], dict]:
    """Pure state transition: evaluate old anchors, then advance snapshots."""
    state = dict(state or {})
    sent = list(dict.fromkeys(str(item) for item in
                              (state.get("sent_event_ids") or []) if item))
    holders = (analysis or {}).get("holders") or {}
    raw_current = holders.get("wallet_snapshot") or {}
    current = dict(raw_current)
    current["ts"] = _int(current.get("ts")
                         or (analysis or {}).get("analyzed_at") or time.time())
    current["dust_pct_mc"] = _float(
        current.get("dust_pct_mc", holders.get("dust_pct_mc")), None)
    symbol = str((analysis or {}).get("symbol") or "?")

    next_state = {
        "baseline": state.get("baseline") or {},
        "rolling": state.get("rolling") or {},
        "sent_event_ids": sent[-MAX_SENT_EVENT_IDS:],
    }
    if current["dust_pct_mc"] is None:
        return [], next_state

    events = []
    baseline = state.get("baseline") if isinstance(state.get("baseline"), dict) \
        else {}
    if baseline and baseline.get("dust_pct_mc") is not None:
        events.extend(evaluate_baseline_rule(
            baseline, current, mint=mint, symbol=symbol,
            sent_event_ids=sent))
    else:
        next_state["baseline"] = compact_wallet_snapshot(current)

    rolling = state.get("rolling") if isinstance(state.get("rolling"), dict) \
        else {}
    if not rolling or rolling.get("dust_pct_mc") is None:
        next_state["rolling"] = compact_wallet_snapshot(current)
    else:
        age = current["ts"] - _int(rolling.get("ts"))
        if is_valid_4h_snapshot(rolling, current):
            events.extend(evaluate_4h_rules(
                rolling, current, mint=mint, symbol=symbol,
                sent_event_ids=sent))
            next_state["rolling"] = compact_wallet_snapshot(current)
        elif age > ALERT_WINDOW_MAX_SEC or age < 0:
            # Stale/out-of-order anchors are unsafe for a four-hour rule.
            next_state["rolling"] = compact_wallet_snapshot(current)
        # A young anchor remains frozen until it reaches the valid window.

    # A dump and baseline-shift can coexist; each has a distinct event id.
    unique = {event["id"]: event for event in events}
    return list(unique.values()), next_state


def compact_alert_state(state: dict | None) -> dict:
    """Sanitize/bound state before persisting it in history/status JSON."""
    state = state or {}
    return {
        "baseline": compact_wallet_snapshot(state.get("baseline")),
        "rolling": compact_wallet_snapshot(state.get("rolling")),
        "sent_event_ids": list(dict.fromkeys(
            str(item) for item in (state.get("sent_event_ids") or []) if item
        ))[-MAX_SENT_EVENT_IDS:],
    }


def _format_time(timestamp: int) -> str:
    moment = datetime.fromtimestamp(_int(timestamp), tz=timezone.utc)
    try:
        local = moment.astimezone(ZoneInfo("Asia/Jakarta"))
        return f"{local:%Y-%m-%d %H:%M:%S WIB} ({moment:%H:%M UTC})"
    except Exception:  # pragma: no cover - tz database is available in CI
        return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_alert_message(event: dict) -> str:
    """Human-readable Telegram message containing all required fields."""
    kind = event.get("kind")
    change = _float(event.get("change_pp"), 0.0) or 0.0
    if kind == "dump":
        title = "🚨 INDIKASI DUMP — HOLDER DUST NAIK"
    elif kind == "accumulation":
        title = "🟢 KEMUNGKINAN AKUMULASI — HOLDER DUST TURUN"
    else:
        direction = "NAIK" if change >= 0 else "TURUN"
        title = f"🔎 CEK PERUBAHAN DUST DARI SNAPSHOT AWAL — {direction}"

    movement = event.get("movements") or {}
    lines = [
        title,
        f"Token: ${event.get('symbol') or '?'}",
        f"Dust sebelumnya: {float(event.get('previous_dust_pct_mc') or 0):.2f}% MC",
        f"Dust terbaru: {float(event.get('current_dust_pct_mc') or 0):.2f}% MC",
        f"Perubahan: {change:+.2f} poin persentase",
        f"Periode: {event.get('scope') or '~4 jam'}",
        f"Wallet saldo meningkat: {int(event.get('wallet_increases') or 0)}",
        "Pergerakan sampel wallet dust:",
        f"- Membesar / keluar dust: {int(movement.get('dust_grew_out') or 0)}",
        f"- Jual habis / hilang: {int(movement.get('dust_sold_out') or 0)}",
        f"- Keluar dust lainnya: {int(movement.get('dust_left_other') or 0)}",
        f"- Mengecil / masuk dust: {int(movement.get('larger_shrank_into_dust') or 0)}",
        f"- Wallet dust baru: {int(movement.get('new_dust') or 0)}",
        f"- Masuk dust lainnya: {int(movement.get('dust_entered_other') or 0)}",
        f"Waktu: {_format_time(event.get('current_ts') or time.time())}",
        f"Mint: {event.get('mint') or '-'}",
    ]
    return "\n".join(lines)


def _safe_transport_error(exc: Exception, token: str) -> str:
    """Render a transport error without leaking the bot token from its URL."""
    message = str(exc)
    return message.replace(token, "[REDACTED]") if token else message


def send_telegram_message(text: str, *, bot_token: str | None = None,
                          chat_id: str | None = None, timeout: float = 10,
                          post: Callable | None = None) -> dict:
    """Send one Bot API ``sendMessage`` request; never raise to the scanner."""
    token = (os.environ.get("TELEGRAM_BOT_TOKEN", "")
             if bot_token is None else str(bot_token)).strip()
    target = (os.environ.get("TELEGRAM_CHAT_ID", "")
              if chat_id is None else str(chat_id)).strip()
    if not token or not target:
        return {"ok": False, "skipped": True,
                "error": "Telegram credentials are not configured"}

    request_post = post or requests.post
    try:
        response = request_post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": target, "text": str(text)}, timeout=timeout)
    except requests.RequestException as exc:
        return {"ok": False, "skipped": False,
                "error": "Telegram request failed: "
                         f"{_safe_transport_error(exc, token)}"}
    except Exception as exc:  # noqa: BLE001 - transport must never kill scan
        return {"ok": False, "skipped": False,
                "error": "Telegram transport failed: "
                         f"{_safe_transport_error(exc, token)}"}

    if getattr(response, "status_code", 0) != 200:
        return {"ok": False, "skipped": False,
                "status": getattr(response, "status_code", None),
                "error": f"Telegram HTTP {getattr(response, 'status_code', '?')}"}
    try:
        payload = response.json() or {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skipped": False,
                "status": 200, "error": f"Telegram response invalid: {exc}"}
    if payload.get("ok") is not True:
        description = str(payload.get("description") or "API returned ok=false")
        return {"ok": False, "skipped": False, "status": 200,
                "error": f"Telegram API failed: {description}"}
    return {"ok": True, "skipped": False, "status": 200}


def send_telegram_alert(event: dict) -> dict:
    return send_telegram_message(format_alert_message(event))


def send_test_alert() -> dict:
    """Send a harmless deployment test using the same transport as alerts."""
    stamp = _format_time(int(time.time()))
    return send_telegram_message(
        "✅ TEST ALERT HOLDER DUST\n"
        "Integrasi Telegram Wallet Depth aktif.\n"
        f"Waktu: {stamp}\n"
        "Pesan ini hanya pengujian, bukan sinyal token."
    )


def process_holder_alerts(analyses: dict | None, history_store: dict,
                          *, sender: Callable[[dict], dict] | None = None) -> list[dict]:
    """Evaluate/send alerts, mutating state *before* history ingests new points."""
    sender = sender or send_telegram_alert
    tokens = history_store.setdefault("tokens", {})
    deliveries = []
    for mint, analysis in (analyses or {}).items():
        if not isinstance(analysis, dict):
            continue
        holders = analysis.get("holders") or {}
        # A provider outage can still return an analysis object with zero
        # fetched holders. Never advance anchors or emit a false baseline drop
        # from that failed scan.
        if ("total_fetched" in holders
                and _int(holders.get("total_fetched")) <= 0):
            continue
        slot = tokens.setdefault(mint, {"symbol": analysis.get("symbol") or "?",
                                        "cohort": {}, "points": []})
        old_state = slot.get(STATE_KEY) if isinstance(slot.get(STATE_KEY), dict) \
            else {}
        events, next_state = evaluate_alert_events(mint, analysis, old_state)
        sent = list(next_state.get("sent_event_ids") or [])
        for event in events:
            try:
                result = sender(event)
                if isinstance(result, bool):
                    result = {"ok": result, "skipped": False}
                elif not isinstance(result, dict):
                    result = {"ok": False, "skipped": False,
                              "error": "invalid sender result"}
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "skipped": False,
                          "error": f"Telegram sender failed: {exc}"}
            deliveries.append({"event": event, "delivery": result})
            if result.get("ok"):
                sent.append(event["id"])
            elif not result.get("skipped"):
                print(f"WARN: Telegram alert {event['id']} gagal: "
                      f"{result.get('error') or 'unknown error'}", file=sys.stderr)
        next_state["sent_event_ids"] = sent[-MAX_SENT_EVENT_IDS:]
        slot[STATE_KEY] = compact_alert_state(next_state)
    return deliveries
