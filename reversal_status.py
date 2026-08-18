# -*- coding: utf-8 -*-
"""Dashboard snapshot of the realtime reversal scanner.

The scanner persists full state in ``last_scan_result.json`` (Actions cache).
That file never reached Streamlit, so the main watchlist froze on stale
``daily_effort.json`` rows. This module publishes a compact public snapshot
the dashboard can pull on every rerun — same GitHub Contents pattern as the
watchlist.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time

import requests

from reversal_engine import (ACCUMULATION, DISTRIBUTION, NEUTRAL,
                             REVERSAL_DOWN, REVERSAL_UP)
from reversal_state import load_state

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_PATH = os.path.join(BASE_DIR, "reversal_status.json")
SCAN_STATE_PATH = os.path.join(BASE_DIR, "last_scan_result.json")
GITHUB_REPO = "lparmycalprut/wallet-depth"
STATUS_REPO_PATH = "reversal_status.json"
# Dedicated ref so 10-minute snapshots do not reboot a Streamlit Cloud
# app that tracks ``main``.
STATUS_REF = "reversal-live"

_CACHE_TTL = 15
_CACHE = {"data": None, "ts": 0.0}

WINDOW_KEYS = (
    "cvd_delta_clean", "wash_pct", "price_chg_pct", "tx_count", "vol_sol",
    "unique_makers", "smart_money_buy", "smart_net_sol", "fresh_buy",
    "fresh_buy_sol", "bot_sell", "top_wallet_pct", "top3_wallet_pct",
    "top_wallet_net_sol", "top_wallet_churn_pct",
)

SIGNAL_META = {
    REVERSAL_UP: {
        "emoji": "🟢", "label": "REVERSAL UP", "tone": "bull",
        "bias": "bullish", "rank": 0,
    },
    REVERSAL_DOWN: {
        "emoji": "🔴", "label": "REVERSAL DOWN", "tone": "bear",
        "bias": "bearish", "rank": 0,
    },
    ACCUMULATION: {
        "emoji": "🔵", "label": "ACCUMULATION", "tone": "aku",
        "bias": "bullish", "rank": 1,
    },
    DISTRIBUTION: {
        "emoji": "🟠", "label": "DISTRIBUTION", "tone": "dist",
        "bias": "bearish", "rank": 1,
    },
    NEUTRAL: {
        "emoji": "⚪", "label": "NEUTRAL", "tone": "neutral",
        "bias": "neutral", "rank": 2,
    },
}

_CONFIDENCE_RANK = {"strong": 0, "watch": 1, "info": 2}


def _pick(window: dict, keys=WINDOW_KEYS) -> dict:
    out = {}
    for key in keys:
        if key in (window or {}) and window[key] is not None:
            out[key] = window[key]
    return out


def _empty_status() -> dict:
    return {"updated_at": None, "scanner": "rolling-6h-v1", "tokens": {}}


def snapshot_status(scan_state: dict | None,
                    watchlist: dict | None = None) -> dict:
    """Build the public dashboard payload from scanner state."""
    tokens = {}
    for mint, token_state in (scan_state or {}).items():
        if not mint or mint.startswith("_") or not isinstance(token_state, dict):
            continue
        result = token_state.get("result") if isinstance(
            token_state.get("result"), dict) else {}
        meta = (watchlist or {}).get(mint) or {}
        signal = (result.get("signal")
                  or token_state.get("observed_signal")
                  or NEUTRAL)
        structure = token_state.get("structure")
        tokens[mint] = {
            "symbol": str(meta.get("symbol") or mint[:8]),
            "signal": signal,
            "state": token_state.get("state") or "NONE",
            "confidence": result.get("confidence") or "info",
            "bias": result.get("bias"),
            "reason": result.get("reason") or "",
            "last_scan_ts": token_state.get("last_scan_ts"),
            "current": _pick(result.get("current") or {}),
            "context": _pick(result.get("context") or {}),
            "structure": structure if isinstance(structure, dict) else None,
        }
    meta = (scan_state or {}).get("_meta") if isinstance(
        (scan_state or {}).get("_meta"), dict) else {}
    updated = meta.get("updated_at")
    if updated is None:
        stamps = [row.get("last_scan_ts") for row in tokens.values()
                  if row.get("last_scan_ts")]
        updated = max(stamps) if stamps else None
    return {
        "updated_at": updated,
        "scanner": meta.get("scanner") or "rolling-6h-v1",
        "tokens": tokens,
    }


def status_sort_key(mint: str, row: dict | None) -> tuple:
    """Reversals first, then setups, then neutral / missing."""
    row = row or {}
    signal = row.get("signal") or ""
    meta = SIGNAL_META.get(signal) or {}
    return (
        meta.get("rank", 3),
        _CONFIDENCE_RANK.get(row.get("confidence") or "info", 9),
        str((row.get("symbol") or mint or "")).upper(),
    )


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
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as handle:
            return str((json.load(handle) or {}).get("github_token", "")).strip()
    except Exception:
        return ""


def _parse_status_payload(data) -> dict | None:
    if isinstance(data, dict) and isinstance(data.get("tokens"), dict):
        return {
            "updated_at": data.get("updated_at"),
            "scanner": data.get("scanner") or "rolling-6h-v1",
            "tokens": data["tokens"],
        }
    if isinstance(data, dict):
        # A raw last_scan_result.json can be snapshotted on the fly.
        snap = snapshot_status(data)
        if snap["tokens"]:
            return snap
    return None


def _contents_url(ref: str | None = None) -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATUS_REPO_PATH}"
    if ref:
        return f"{url}?ref={ref}"
    return url


def _github_pull() -> dict | None:
    """Read reversal_status.json from the live status ref, then main."""
    tok = _github_token()
    headers = {"Accept": "application/vnd.github.raw+json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    for ref in (STATUS_REF, "main"):
        try:
            response = requests.get(_contents_url(ref), headers=headers,
                                    timeout=10)
        except requests.RequestException as exc:
            print(f"WARN: reversal_status API {ref} network error: {exc}",
                  file=sys.stderr)
            continue
        if response.status_code != 200:
            if response.status_code != 404:
                print(f"WARN: reversal_status API {ref} {response.status_code}: "
                      f"{response.text[:200]}", file=sys.stderr)
            continue
        try:
            parsed = _parse_status_payload(response.json())
        except Exception as exc:
            print(f"WARN: reversal_status API {ref} parse failed: {exc}",
                  file=sys.stderr)
            parsed = None
        if parsed is not None:
            return parsed

    try:
        raw = (f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
               f"{STATUS_REF}/{STATUS_REPO_PATH}")
        response = requests.get(
            raw, params={"t": int(time.time())},
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            timeout=10)
        if response.status_code == 200:
            return _parse_status_payload(response.json()) or _empty_status()
    except (requests.RequestException, ValueError) as exc:
        print(f"WARN: reversal_status raw CDN failed: {exc}", file=sys.stderr)
    return None


def _ensure_status_branch(headers: dict) -> bool:
    """Create ``STATUS_REF`` from the default branch when it does not exist."""
    refs = f"https://api.github.com/repos/{GITHUB_REPO}/git/ref/heads/{STATUS_REF}"
    try:
        existing = requests.get(refs, headers=headers, timeout=10)
    except requests.RequestException as exc:
        print(f"WARN: reversal_status ref lookup failed: {exc}", file=sys.stderr)
        return False
    if existing.status_code == 200:
        return True
    try:
        repo = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}",
            headers=headers, timeout=10)
        default = ((repo.json() or {}).get("default_branch") or "main"
                   if repo.status_code == 200 else "main")
        head = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/git/ref/heads/{default}",
            headers=headers, timeout=10)
        sha = ((head.json() or {}).get("object") or {}).get("sha")
        if not sha:
            return False
        created = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{STATUS_REF}", "sha": sha},
            timeout=15)
        if created.status_code in (201, 422):
            return True
        print(f"WARN: reversal_status create ref {created.status_code}: "
              f"{created.text[:200]}", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"WARN: reversal_status create ref failed: {exc}", file=sys.stderr)
    return False


def _github_push(status: dict, message: str, max_retries: int = 3) -> bool:
    tok = _github_token()
    if not tok:
        print("WARN: reversal_status push skipped (no github_token)",
              file=sys.stderr)
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATUS_REPO_PATH}"
    headers = {"Authorization": f"Bearer {tok}",
               "Accept": "application/vnd.github+json"}
    target_ref = STATUS_REF if _ensure_status_branch(headers) else "main"
    if target_ref == "main":
        print("WARN: reversal_status falling back to main", file=sys.stderr)
    body_content = base64.b64encode(
        json.dumps(status, indent=2, sort_keys=True).encode()).decode()
    for attempt in range(1, max_retries + 1):
        try:
            current = requests.get(_contents_url(target_ref), headers=headers,
                                   timeout=15)
        except requests.RequestException as exc:
            print(f"WARN: reversal_status GET failed: {exc}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        sha = None
        if current.status_code == 200:
            try:
                sha = (current.json() or {}).get("sha")
            except Exception:
                sha = None
        elif current.status_code != 404:
            if current.status_code in (401, 403):
                print(f"ERROR: reversal_status GET auth {current.status_code}",
                      file=sys.stderr)
                return False
            retryable = current.status_code in (409, 429) or current.status_code >= 500
            if attempt < max_retries and retryable:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        payload = {
            "message": message,
            "content": body_content,
            "branch": STATUS_REF,
        }
        if sha:
            payload["sha"] = sha
        try:
            put = requests.put(url, headers=headers, json=payload, timeout=15)
        except requests.RequestException as exc:
            print(f"WARN: reversal_status PUT failed: {exc}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        if put.status_code in (200, 201):
            return True
        print(f"WARN: reversal_status PUT {put.status_code}: {put.text[:200]}",
              file=sys.stderr)
        if put.status_code in (409, 429) or put.status_code >= 500:
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
        return False
    return False


def _read_local(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return _parse_status_payload(json.load(handle))
    except (OSError, ValueError, TypeError):
        return None


def _write_local(status: dict, path: str | None = None) -> None:
    from reversal_state import save_state
    save_state(path or STATUS_PATH, status)


def load_reversal_status(force_refresh: bool = False) -> dict:
    """Merge: GitHub snapshot (durable) + local file + last scan state."""
    now = time.time()
    if (not force_refresh and _CACHE["data"] is not None
            and (now - _CACHE["ts"]) < _CACHE_TTL):
        return dict(_CACHE["data"])

    remote = _github_pull()
    local = _read_local(STATUS_PATH)
    scan = snapshot_status(load_state(SCAN_STATE_PATH))
    # Prefer the newest updated_at among sources that actually have tokens.
    candidates = [item for item in (remote, local, scan)
                  if item and item.get("tokens")]
    if not candidates:
        status = remote or local or scan or _empty_status()
    else:
        def _stamp(item):
            try:
                return float(item.get("updated_at") or 0)
            except (TypeError, ValueError):
                return 0.0
        status = max(candidates, key=_stamp)
    _CACHE["data"] = dict(status)
    _CACHE["ts"] = now
    return dict(status)


def publish_reversal_status(scan_state: dict,
                            watchlist: dict | None = None,
                            *, push: bool = True) -> dict:
    """Write the dashboard snapshot locally and (optionally) to GitHub."""
    status = snapshot_status(scan_state, watchlist)
    _write_local(status)
    _CACHE["data"] = dict(status)
    _CACHE["ts"] = time.time()
    if push:
        stamp = status.get("updated_at") or int(time.time())
        ok = _github_push(
            status, f"reversal-status: snapshot {stamp} [skip ci]")
        if not ok:
            print("WARN: reversal_status GitHub publish failed; "
                  "dashboard will use the next successful push",
                  file=sys.stderr)
    return status


def reset_cache() -> None:
    """Test helper."""
    _CACHE["data"] = None
    _CACHE["ts"] = 0.0
