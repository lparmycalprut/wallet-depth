"""Persistent transition-only state machine for realtime reversal alerts."""
from __future__ import annotations

import json
import os
import tempfile

from reversal_engine import REVERSAL_DOWN, REVERSAL_UP

FIRED_STATE = {
    REVERSAL_UP: "REVERSAL_UP_FIRED",
    REVERSAL_DOWN: "REVERSAL_DOWN_FIRED",
}
SETUP_SIGNALS = {"ACCUMULATION", "DISTRIBUTION"}


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
               reset_scans: int = 2) -> tuple[dict, bool]:
    """Advance one token state and return ``(new_state, should_alert)``.

    A reversal must appear in consecutive scans and only fires outside the
    cooldown. Repeated scans of an already-fired reversal never alert.
    """
    state = dict(token_state or {})
    state.setdefault("state", "NONE")
    state.setdefault("candidate_signal", None)
    state.setdefault("candidate_count", 0)
    state.setdefault("clear_count", 0)
    state["last_scan_ts"] = int(now_ts)
    state["observed_signal"] = signal
    alert = False

    if signal in FIRED_STATE:
        if state.get("candidate_signal") == signal:
            state["candidate_count"] = int(state.get("candidate_count", 0)) + 1
        else:
            state["candidate_signal"] = signal
            state["candidate_count"] = 1
        state["clear_count"] = 0
        cooldown_until = int(state.get("cooldown_until") or 0)
        already_fired = state.get("state") == FIRED_STATE[signal]
        if (state["candidate_count"] >= confirmations and now_ts >= cooldown_until
                and not already_fired):
            state["state"] = FIRED_STATE[signal]
            state["last_signal"] = signal
            state["last_fired_ts"] = int(now_ts)
            state["cooldown_until"] = int(now_ts + cooldown_hours * 3600)
            alert = True
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
