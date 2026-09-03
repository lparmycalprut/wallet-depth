"""Telegram alerts for holder-dust changes observed over four hours.

The module is deliberately side-effect free until ``send_alerts`` is called,
so the signal rules can be tested without Telegram credentials.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import requests

LOOKBACK_SECONDS = 4 * 3600
DUMP_DELTA_PCT = 0.25
ACCUMULATION_DELTA_PCT = 0.50


def _number(value):
    try:
        value = float(value)
        return value if value == value else None
    except (TypeError, ValueError):
        return None


def _wallets(value):
    return value if isinstance(value, dict) else {}


def _reference_point(history, now):
    """Return the latest known point no newer than the four-hour cutoff."""
    cutoff = int(now) - LOOKBACK_SECONDS
    points = [p for p in (history or []) if isinstance(p, dict)
              and _number(p.get("ts")) is not None
              and int(float(p["ts"])) <= cutoff]
    return max(points, key=lambda p: int(float(p["ts"]))) if points else None


def increased_wallets(previous, current):
    """Wallets whose token balance increased since the previous scan."""
    old = _wallets(previous)
    new = _wallets(current)
    changed = []
    for address, balance in new.items():
        before = _number(old.get(address))
        after = _number(balance)
        if after is not None and (before is None or after > before):
            changed.append({"address": str(address), "before": before or 0.0,
                            "after": after, "delta": after - (before or 0.0)})
    return sorted(changed, key=lambda row: row["delta"], reverse=True)


def evaluate_token(mint, token, previous_token, *, now=None):
    """Evaluate one token and return zero or more alert dictionaries.

    Dust comparison uses the latest status point at least four hours old.
    Accumulation additionally requires at least one wallet to have added
    tokens; a falling dust percentage alone is not enough.
    """
    now = int(now or time.time())
    token = token if isinstance(token, dict) else {}
    previous_token = previous_token if isinstance(previous_token, dict) else {}
    holders = token.get("holders") or {}
    old_holders = previous_token.get("holders") or {}
    current = _number(holders.get("dust_pct_mc"))
    reference = _reference_point(previous_token.get("history"), now)
    if current is None or not reference:
        return []
    old = _number(reference.get("dust_pct_mc"))
    if old is None:
        return []
    delta = current - old
    symbol = str(token.get("symbol") or mint[:8])
    bucket = now // LOOKBACK_SECONDS
    common = {"mint": mint, "symbol": symbol, "current": current,
              "reference": old, "delta": delta,
              "reference_ts": int(float(reference["ts"])),
              "event_bucket": bucket}
    alerts = []
    if delta >= DUMP_DELTA_PCT:
        alerts.append({**common, "kind": "dump", "event_id": f"{mint}:dump:{bucket}"})
    buyers = increased_wallets(old_holders.get("wallet_balances"),
                               holders.get("wallet_balances"))
    if delta <= -ACCUMULATION_DELTA_PCT and buyers:
        alerts.append({**common, "kind": "accumulation", "buyers": buyers,
                       "event_id": f"{mint}:accumulation:{bucket}"})
    return alerts


def evaluate(analyses, previous_status, *, now=None):
    """Evaluate all current analyses against the previously published status."""
    previous = (previous_status or {}).get("tokens") or {}
    out = []
    for mint, analysis in (analyses or {}).items():
        current_token = {
            "symbol": analysis.get("symbol") if isinstance(analysis, dict) else "?",
            "holders": (analysis or {}).get("holders") or {},
        }
        out.extend(evaluate_token(mint, current_token, previous.get(mint), now=now))
    return out


def format_alert(alert, *, now=None):
    now = int(now or time.time())
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    symbol = alert["symbol"]
    current = alert["current"]
    reference = alert["reference"]
    delta = alert["delta"]
    if alert["kind"] == "dump":
        return (f"🔴 DUMP TERDETEKSI — ${symbol}\n"
                f"Holding dust naik {delta:.2f} poin persentase dalam 4 jam\n"
                f"{reference:.2f}% MC → {current:.2f}% MC\n"
                f"Waktu: {stamp}\nMint: {alert['mint']}")
    buyers = alert.get("buyers") or []
    return (f"🟢 KEMUNGKINAN AKUMULASI — ${symbol}\n"
            f"Holding dust turun {abs(delta):.2f} poin persentase dalam 4 jam\n"
            f"{reference:.2f}% MC → {current:.2f}% MC\n"
            f"{len(buyers)} wallet menambah muatan token (membeli)\n"
            f"Waktu: {stamp}\nMint: {alert['mint']}")


def telegram_credentials():
    return (os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def send_alerts(alerts, *, token=None, chat_id=None, session=requests,
                timeout=15):
    """Send alerts; returns a result per alert and never raises network errors."""
    token = (token or telegram_credentials()[0]).strip()
    chat_id = (chat_id or telegram_credentials()[1]).strip()
    if not token or not chat_id:
        return [{"event_id": a.get("event_id"), "sent": False,
                 "skipped": True, "error": "Telegram credentials missing"}
                for a in alerts or []]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    results = []
    for alert in alerts or []:
        try:
            response = session.post(url, data={"chat_id": chat_id,
                                               "text": format_alert(alert)},
                                    timeout=timeout)
            ok = response.status_code == 200 and bool((response.json() or {}).get("ok"))
            results.append({"event_id": alert.get("event_id"), "sent": ok,
                            "error": "Telegram API rejected request" if not ok else ""})
        except (requests.RequestException, ValueError) as exc:
            results.append({"event_id": alert.get("event_id"), "sent": False,
                            "error": str(exc)})
    return results
