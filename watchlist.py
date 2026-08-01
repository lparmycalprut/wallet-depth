# -*- coding: utf-8 -*-
"""Shared watchlist helpers (used by app, watchlist page, and the cron job).

On Streamlit Cloud the filesystem is ephemeral: local writes are lost on
every redeploy. If a GitHub token is available (secrets/config/env), every
add/remove is also committed straight to the repo so it truly persists.
"""
import base64
import json
import os
import sys
from datetime import datetime

import requests

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
PENDING_PATH = os.path.join(BASE_DIR, "watchlist_pending.json")
GITHUB_REPO = "lparmycalprut/wallet-depth"


def _load_pending() -> list:
    try:
        with open(PENDING_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_pending(ops: list) -> None:
    try:
        atomic_write_json(PENDING_PATH, ops)
    except Exception as exc:
        print(f"WARN: failed to save {PENDING_PATH}: {exc}",
              file=sys.stderr)


def _apply_ops(wl: dict, ops: list) -> dict:
    for op in ops:
        if op.get("op") == "add":
            entry = wl.setdefault(op["ca"], {})
            # Copy every journaled field (symbol/note/added/source/
            # down_ath/avg_cost) — dropping e.g. `source` here made
            # HRHR adds fall back to the LP Radar's default ("trending").
            for _k in ("symbol", "note", "added", "source", "down_ath",
                       "avg_cost"):
                if op.get(_k) is not None and _k not in entry:
                    entry[_k] = op[_k]
        elif op.get("op") == "remove":
            wl.pop(op["ca"], None)
    return wl


def _github_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    try:
        import streamlit as st
        if "github_token" in st.secrets:
            return str(st.secrets["github_token"]).strip()
    except Exception:
        pass
    try:
        with open(os.path.join(BASE_DIR, "config.json")) as f:
            return str((json.load(f) or {}).get("github_token", "")).strip()
    except Exception:
        return ""


def _github_pull() -> dict | None:
    """Read watchlist.json from the repo (source of truth).
    Uses the API (no CDN cache) when a token exists; raw URL otherwise."""
    tok = _github_token()
    try:
        if tok:
            r = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/"
                f"watchlist.json",
                headers={"Authorization": f"Bearer {tok}",
                         "Accept": "application/vnd.github.raw+json"},
                timeout=10)
            if r.status_code == 200:
                return r.json() if isinstance(r.json(), dict) else {}
        r = requests.get(
            f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/"
            f"watchlist.json", params={"t": int(__import__('time').time())},
            timeout=10)
        if r.status_code == 200:
            return r.json() or {}
    except Exception:
        pass
    return None


def _github_push(wl: dict, action: str) -> bool:
    """Commit watchlist.json to the repo. Returns True on success."""
    tok = _github_token()
    if not tok:
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/watchlist.json"
    hdrs = {"Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json"}
    try:
        sha = None
        g = requests.get(url, headers=hdrs, timeout=15)
        if g.status_code == 200:
            sha = g.json().get("sha")
        body = {
            "message": f"watchlist: {action}",
            "content": base64.b64encode(
                json.dumps(wl, indent=1).encode()).decode(),
        }
        if sha:
            body["sha"] = sha
        p = requests.put(url, headers=hdrs, json=body, timeout=15)
        return p.status_code in (200, 201)
    except Exception:
        return False


def load_watchlist() -> dict:
    """Merge: repo copy (durable truth) + pending journal (recent local
    ops). Pending ops always win; they are dropped only once the repo
    reflects them. An add/remove therefore never visually reverts."""
    remote = _github_pull()
    if remote is None:  # offline -> local file
        try:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                remote = json.load(f) or {}
        except Exception:
            remote = {}
    pending = _load_pending()
    if pending:
        still = []
        for op in pending:
            in_repo = op["ca"] in remote
            if (op["op"] == "add" and in_repo) or \
               (op["op"] == "remove" and not in_repo):
                continue  # repo caught up -> journal entry done
            still.append(op)
        if still != pending:
            _save_pending(still)
        if still:
            remote = _apply_ops(remote, still)
            # opportunistic flush: try committing the merged state
            if _github_token() and _github_push(remote, "sync pending ops"):
                _save_pending([])
    try:
        atomic_write_json(WATCHLIST_PATH, remote, indent=1)
    except Exception as exc:
        print(f"WARN: failed to save {WATCHLIST_PATH}: {exc}",
              file=sys.stderr)
    return remote


def save_watchlist(wl: dict, action: str = "update") -> bool:
    """Write locally AND commit to GitHub. Returns True if committed."""
    try:
        atomic_write_json(WATCHLIST_PATH, wl, indent=1)
    except Exception as exc:
        print(f"WARN: failed to save {WATCHLIST_PATH}: {exc}",
              file=sys.stderr)
    return _github_push(wl, action)


def _journal(op: dict) -> None:
    """Append an op to the pending journal; an add cancels earlier removes
    for the same CA and vice versa (last op wins)."""
    pending = [p for p in _load_pending() if p.get("ca") != op.get("ca")]
    pending.append(op)
    _save_pending(pending)


def add_to_watchlist(ca: str, symbol: str = "?", note: str = "",
                     source: str = "", down_ath: float = None,
                     avg_cost: float = None) -> bool:
    """Add *ca* to the watchlist.

    *source* tracks where the token came from (``"trending"``,
    ``"hrhr"``, ``"manual"``).  LP Radar uses it to decide which
    card section to show a token in.

    *down_ath* (optional) is the % the current price is below the
    all-time high, captured when the token was added from a screener.
    The LP/Degen Radar cards show it as ATH context.

    *avg_cost* (optional) is GMGN's holder average-cost change % —
    how far the current price is above/below the average holder buy
    price. Cards show it as an "avg cost" stat.
    """
    entry = {"symbol": symbol, "note": note,
             "added": datetime.now().strftime("%Y-%m-%d")}
    if source:
        entry["source"] = source
    if down_ath is not None:
        entry["down_ath"] = float(down_ath)
    if avg_cost is not None:
        entry["avg_cost"] = float(avg_cost)
    # journal FIRST -> the change can never visually revert (stale reads,
    # failed commits, redeploys); journal is cleaned once repo reflects it
    _journal({"op": "add", "ca": ca, **entry})
    # Flag the CA for the main app's auto-refresh sweep: the next rerun
    # backfills its CVD/conviction data immediately (the manual "Force
    # refresh now" button was removed). Best-effort — Streamlit may not
    # be present (cron).
    try:
        import streamlit as st
        pending = st.session_state.setdefault(
            "watchlist_auto_refresh_cas", set())
        pending.add(ca)
    except Exception:
        pass
    wl = load_watchlist()
    wl[ca] = {**entry, **(wl.get(ca) or {})}
    if symbol and symbol != "?":
        wl[ca]["symbol"] = symbol
    if source:
        # Latest add wins: an explicit source (trending/hrhr/manual)
        # overrides a stale/missing one so HRHR adds never land in the
        # LP Radar section by accident.
        wl[ca]["source"] = source
    if avg_cost is not None:
        # Fresh GMGN avg-cost capture wins over a stale/missing one.
        wl[ca]["avg_cost"] = float(avg_cost)
    return save_watchlist(wl, f"add {symbol} ({ca[:8]}…)")


def remove_from_watchlist(ca: str) -> bool:
    _journal({"op": "remove", "ca": ca})
    wl = load_watchlist()
    meta = wl.pop(ca, None) or {}
    return save_watchlist(wl, f"remove {meta.get('symbol', '?')} "
                              f"({ca[:8]}…)")
