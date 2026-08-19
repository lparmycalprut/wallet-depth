"""Persistent transition-only state machine for realtime reversal alerts."""
from __future__ import annotations

import json
import os
import tempfile

from price_structure import CONFIRMED
from reversal_engine import REVERSAL_DOWN, REVERSAL_UP
from serok_engine import BATTLE, SIAP2_PUMP, WASPADA_DUMP

FIRED_STATE = {
    REVERSAL_UP: "REVERSAL_UP_FIRED",
    REVERSAL_DOWN: "REVERSAL_DOWN_FIRED",
    WASPADA_DUMP: "WASPADA_DUMP_FIRED",
    SIAP2_PUMP: "SIAP2_PUMP_FIRED",
    BATTLE: "BATTLE_FIRED",
}
SEROK_SIGNALS = {WASPADA_DUMP, SIAP2_PUMP, BATTLE}
SETUP_SIGNALS = {"ACCUMULATION", "DISTRIBUTION"}
# Sinyal flow sudah lolos ambang, tetapi struktur harga (SBR) belum
# mengonfirmasi — tampil di dashboard, TIDAK pernah alert Telegram.
WATCH = "WATCH"


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: str, state: dict) -> None:
    """Atomically persist scanner state."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".reversal-state-", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def transition(token_state: dict | None, signal: str, now_ts: int, *,
               confirmations: int = 2, cooldown_hours: int = 18,
               reset_scans: int = 2,
               structure_state: str = CONFIRMED,
               event_id: str | None = None) -> tuple[dict, bool]:
    """Advance one token state and return ``(new_state, should_alert)``.

    A reversal must appear in consecutive scans, only fires outside the
    cooldown, and (gate utama) hanya boleh alert setelah struktur harga
    terkonfirmasi (``structure_state == CONFIRMED``). Sinyal yang lolos ambang
    scan tetapi belum terkonfirmasi struktur diparkir di state ``WATCH`` —
    muncul di dashboard tanpa pernah menyentuh Telegram. Begitu struktur
    mengonfirmasi pada scan berikutnya (selama sinyal flow bertahan), alert
    langsung menyala dari posisi WATCH.
    """
    state = dict(token_state or {})
    state.setdefault("state", "NONE")
    state.setdefault("candidate_signal", None)
    state.setdefault("candidate_count", 0)
    state.setdefault("clear_count", 0)
    state["last_scan_ts"] = int(now_ts)
    state["observed_signal"] = signal
    alert = False

    if signal in SEROK_SIGNALS:
        # Extension signals are bar-identity unique: one Telegram per event_id.
        confirmations = 1
        cooldown_hours = 0
        structure_state = CONFIRMED
        already = state.get("last_event_id") == event_id and event_id
        if event_id and not already:
            state["state"] = FIRED_STATE[signal]
            state["last_signal"] = signal
            state["last_event_id"] = event_id
            state["last_fired_ts"] = int(now_ts)
            state["candidate_signal"] = signal
            state["candidate_count"] = 1
            state["clear_count"] = 0
            return state, True
        state["state"] = FIRED_STATE[signal]
        state["clear_count"] = 0
        return state, False

    if signal in FIRED_STATE:
        if state.get("candidate_signal") == signal:
            state["candidate_count"] = int(state.get("candidate_count", 0)) + 1
        else:
            state["candidate_signal"] = signal
            state["candidate_count"] = 1
        state["clear_count"] = 0
        cooldown_until = int(state.get("cooldown_until") or 0)
        already_fired = state.get("state") == FIRED_STATE[signal]
        if (state["candidate_count"] >= confirmations and not already_fired
                and now_ts >= cooldown_until):
            if structure_state == CONFIRMED:
                state["state"] = FIRED_STATE[signal]
                state["last_signal"] = signal
                state["last_fired_ts"] = int(now_ts)
                state["cooldown_until"] = int(now_ts + cooldown_hours * 3600)
                alert = True
            else:
                state["state"] = WATCH
        return state, alert

    state["candidate_signal"] = None
    state["candidate_count"] = 0
    if signal in SETUP_SIGNALS:
        state["state"] = signal
        state["clear_count"] = 0
    else:
        state["clear_count"] = int(state.get("clear_count", 0)) + 1
        if (state["clear_count"] >= reset_scans and
                now_ts >= int(state.get("cooldown_until") or 0)):
            state["state"] = "NONE"
    return state, False
