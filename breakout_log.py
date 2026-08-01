# -*- coding: utf-8 -*-
"""Structured log of every level event (breakout / breakdown / spring /
failed breakout / reclaim) — kept in its OWN file, ``breakouts.json``.

Why a separate file from ``signals.json``: a level event is not a one-off
notification, it is the start of a story. A breakdown may be reclaimed
three H4 candles later; a breakout may fail. Each record therefore keeps
the full candle, the on-chain flow *inside that candle* (who bought, who
sold), the verdict, and a ``parent_id`` / ``outcome`` pair that links the
follow-up back to the original break. That is what makes "harga spring,
ayo kita analisa" possible after the fact.

Record shape::

    {"id", "ts", "ca", "symbol", "event", "level", "level_kind",
     "levels_tf", "candle": {ts,o,h,l,c,v}, "penetration_pct",
     "flow": {...}, "verdict", "why", "parent_id", "outcome",
     "outcome_ts", "alerted", "msg"}

``msg`` holds the rendered Telegram text until it is delivered; it is
cleared once sent, so an alert is never silently lost when Telegram is
down (the next cron run retries it).
"""
import json
import os
import sys
import time

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
#: module-level so tests can point it at a temp file
LOG_PATH = os.path.join(BASE_DIR, "breakouts.json")
MAX_EVENTS = 500
#: an undelivered alert older than this is dropped instead of retried
RETRY_MAX_H = 8


def load_events() -> list:
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def save_events(events: list) -> None:
    try:
        atomic_write_json(LOG_PATH, events[-MAX_EVENTS:],
                          separators=(",", ":"))
    except Exception as exc:
        print(f"WARN: failed to save {LOG_PATH}: {exc}", file=sys.stderr)


def make_id(ca: str, event: str, candle_ts: int) -> str:
    """Stable id — same candle + same event can never be logged twice."""
    return f"{(ca or '?')[:8]}-{event}-{int(candle_ts)}"


def record_event(rec: dict) -> str | None:
    """Append *rec* (needs at least id/ca/event). Returns the id, or None
    when an event with that id is already logged (idempotent re-runs)."""
    eid = rec.get("id")
    if not eid:
        return None
    events = load_events()
    if any(e.get("id") == eid for e in events):
        return None
    rec.setdefault("ts", int(time.time()))
    rec.setdefault("alerted", False)
    rec.setdefault("parent_id", None)
    rec.setdefault("outcome", None)
    rec.setdefault("outcome_ts", None)
    events.append(rec)
    save_events(events)
    return eid


def mark_alerted(event_id: str) -> None:
    """Flag an event as delivered and drop its cached message text."""
    events = load_events()
    for e in events:
        if e.get("id") == event_id:
            e["alerted"] = True
            e["msg"] = ""
            break
    save_events(events)


def set_outcome(event_id: str, outcome: str, *, child_id: str = None) -> None:
    """Close the story on an earlier event.

    outcome: ``reclaimed`` · ``failed`` · ``held`` · ``no_reclaim``
    """
    if not event_id:
        return
    events = load_events()
    for e in events:
        if e.get("id") == event_id:
            e["outcome"] = outcome
            e["outcome_ts"] = int(time.time())
            if child_id:
                e["child_id"] = child_id
            break
    save_events(events)


def pending_alerts(max_age_h: int = RETRY_MAX_H, *,
                   now: float = None) -> list:
    """Events whose Telegram send never succeeded and are still fresh.

    ``now`` overrides the clock for tests, matching
    :func:`breakout_guard.run_guard`.
    """
    cut = (time.time() if now is None else now) - max_age_h * 3600
    return [e for e in load_events()
            if not e.get("alerted") and e.get("msg")
            and (e.get("ts") or 0) >= cut]


def events_for(ca: str, *, limit: int = 20) -> list:
    """Most recent events for one token, newest first."""
    out = [e for e in load_events() if e.get("ca") == ca]
    return list(reversed(out))[:limit]


def history_line(e: dict) -> str:
    """One-line summary of a past event, for the 'what happened last
    time this level was tested' block in a new alert."""
    when = time.strftime("%d %b %H:%M", time.gmtime(e.get("ts") or 0))
    out = e.get("outcome") or "open"
    return (f"{when} UTC · {e.get('event')} @ {e.get('level')} "
            f"→ {e.get('verdict') or '?'} ({out})")
