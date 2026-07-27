# -*- coding: utf-8 -*-
"""Shared watchlist helpers (used by app, watchlist page, and the cron job).

On Streamlit Cloud the filesystem is ephemeral: local writes are lost on
every redeploy. If a GitHub token is available (secrets/config/env), every
add/remove is also committed straight to the repo so it truly persists.
"""
import base64
import json
import os
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
GITHUB_REPO = "lparmycalprut/wallet-depth"


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
    """Repo copy is the source of truth (survives redeploys), BUT if the
    local file was written in the last 2 minutes (user just clicked
    add/remove), prefer it — the GitHub API can serve a stale read for a
    few seconds after a commit."""
    try:
        import time as _t
        if os.path.exists(WATCHLIST_PATH) and \
                _t.time() - os.path.getmtime(WATCHLIST_PATH) < 120:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    remote = _github_pull()
    if remote is not None:
        try:  # keep local copy in sync for cron/local runs
            with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
                json.dump(remote, f, indent=1)
            # don't let this sync-write count as a "fresh user edit"
            old = __import__("time").time() - 3600
            os.utime(WATCHLIST_PATH, (old, old))
        except Exception:
            pass
        return remote
    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_watchlist(wl: dict, action: str = "update") -> bool:
    """Write locally AND commit to GitHub (if token available).
    Returns True if the change is durable (committed to repo)."""
    try:
        with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
            json.dump(wl, f, indent=1)
    except Exception:
        pass
    return _github_push(wl, action)


def add_to_watchlist(ca: str, symbol: str = "?", note: str = "") -> bool:
    wl = load_watchlist()
    if ca not in wl:
        wl[ca] = {"symbol": symbol, "note": note,
                  "added": datetime.now().strftime("%Y-%m-%d")}
    elif symbol and symbol != "?":
        wl[ca]["symbol"] = symbol
    return save_watchlist(wl, f"add {symbol} ({ca[:8]}…)")


def remove_from_watchlist(ca: str) -> bool:
    wl = load_watchlist()
    meta = wl.pop(ca, None) or {}
    return save_watchlist(wl, f"remove {meta.get('symbol', '?')} "
                              f"({ca[:8]}…)")
