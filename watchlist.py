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
import time
from datetime import datetime

import requests

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
PENDING_PATH = os.path.join(BASE_DIR, "watchlist_pending.json")
GITHUB_REPO = "lparmycalprut/wallet-depth"

# ---- short TTL cache for load_watchlist (avoid hammering API each rerun) ---
_CACHE_TTL = 15  # seconds
_REMOTE_CACHE = {"data": None, "ts": 0.0}

# ---- last push error (surfaced to UI) ---------------------------------------
_LAST_PUSH_ERROR = {"msg": "", "ts": 0.0, "status": None}


def _set_last_error(msg: str, status=None):
    _LAST_PUSH_ERROR["msg"] = str(msg or "")
    _LAST_PUSH_ERROR["ts"] = time.time()
    _LAST_PUSH_ERROR["status"] = status


def get_last_push_error() -> dict:
    """Return last push error info: {msg, ts, status}."""
    return dict(_LAST_PUSH_ERROR)


def _reset_cache():
    """Reset in-memory cache (used by tests)."""
    _REMOTE_CACHE["data"] = None
    _REMOTE_CACHE["ts"] = 0.0
    _LAST_PUSH_ERROR["msg"] = ""
    _LAST_PUSH_ERROR["ts"] = 0.0
    _LAST_PUSH_ERROR["status"] = None


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
        print(f"WARN: failed to save {PENDING_PATH}: {exc}", file=sys.stderr)


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

    Order:
      1. GitHub API with token (no CDN cache)
      2. GitHub API without token (avoids raw CDN, but rate-limited 60/h)
      3. raw.githubusercontent.com with cache-busting + no-cache headers
    """
    tok = _github_token()

    # 1) API with token
    if tok:
        try:
            r = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/"
                f"watchlist.json",
                headers={"Authorization": f"Bearer {tok}",
                         "Accept": "application/vnd.github.raw+json"},
                timeout=10)
            if r.status_code == 200:
                try:
                    data = r.json()  # single parse
                except Exception as je:
                    print(f"WARN: _github_pull token api json parse failed: {je} body={r.text[:200]}", file=sys.stderr)
                    data = None
                if isinstance(data, dict):
                    return data
                if data is not None:
                    print(f"WARN: _github_pull token api returned non-dict {type(data)}", file=sys.stderr)
            else:
                print(f"WARN: _github_pull token API failed {r.status_code}: {r.text[:200]}", file=sys.stderr)
        except requests.RequestException as exc:
            print(f"WARN: _github_pull token API network error: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"WARN: _github_pull token API unexpected: {exc}", file=sys.stderr)

    # 2) API without token (avoids CDN stale cache, even when no token configured)
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/"
            f"watchlist.json",
            headers={"Accept": "application/vnd.github.raw+json"},
            timeout=10)
        if r.status_code == 200:
            try:
                data = r.json()
            except Exception as je:
                print(f"WARN: _github_pull anon api json parse failed: {je}", file=sys.stderr)
                data = None
            if isinstance(data, dict):
                print("INFO: _github_pull using anon API (no token / fallback)", file=sys.stderr)
                return data
        else:
            # 404 is fine (file not exists yet), not worth warning loudly for other codes just info
            if r.status_code != 404:
                print(f"INFO: _github_pull anon API status {r.status_code}: {r.text[:200]}", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"WARN: _github_pull anon API network error: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"WARN: _github_pull anon API unexpected: {exc}", file=sys.stderr)

    # 3) raw CDN fallback (can be stale, but better than nothing)
    try:
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/watchlist.json"
        params = {"t": int(time.time())}
        hdrs = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
        r = requests.get(url, params=params, headers=hdrs, timeout=10)
        if r.status_code == 200:
            try:
                data = r.json()
                return data or {}
            except Exception as je:
                print(f"WARN: _github_pull raw CDN json parse failed: {je}", file=sys.stderr)
                return {}
        else:
            print(f"WARN: _github_pull raw CDN failed {r.status_code}", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"WARN: _github_pull raw CDN network error: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"WARN: _github_pull raw CDN unexpected: {exc}", file=sys.stderr)

    return None


def _github_push(wl: dict, action: str, max_retries: int = 3) -> bool:
    """Commit watchlist.json to the repo with retry + re-fetch sha on 409.

    On 409 conflict it re-fetches the latest remote, merges pending ops
    (and the original wl) to avoid lost-update, then retries.
    """
    tok = _github_token()
    if not tok:
        _set_last_error("no github_token configured", status=0)
        print(f"WARN: _github_push no token, action={action}", file=sys.stderr)
        return False

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/watchlist.json"
    hdrs = {"Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json"}

    last_err_msg = ""
    for attempt in range(1, max_retries + 1):
        try:
            # --- GET current file to obtain sha + latest remote content ----------
            sha = None
            latest_remote = None
            try:
                g = requests.get(url, headers=hdrs, timeout=15)
            except requests.RequestException as exc:
                print(f"WARN: _github_push GET attempt {attempt}/{max_retries} network error: {exc} action={action}", file=sys.stderr)
                _set_last_error(f"GET network error: {exc}", status=None)
                last_err_msg = f"GET network error: {exc}"
                if attempt < max_retries:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                return False

            if g.status_code == 200:
                try:
                    wrapper = g.json()  # single parse, do not call twice
                except Exception as je:
                    print(f"WARN: _github_push GET json parse failed attempt {attempt}: {je} body={g.text[:200]} action={action}", file=sys.stderr)
                    wrapper = {}
                    _set_last_error(f"GET json parse failed: {je}", status=g.status_code)
                if isinstance(wrapper, dict):
                    sha = wrapper.get("sha")
                    content_b64 = wrapper.get("content", "")
                    if content_b64:
                        try:
                            decoded = base64.b64decode(content_b64).decode("utf-8")
                            latest_remote = json.loads(decoded) if decoded.strip() else {}
                            if not isinstance(latest_remote, dict):
                                print(f"WARN: _github_push decoded content not dict type={type(latest_remote)} action={action}", file=sys.stderr)
                                latest_remote = {}
                        except Exception as de:
                            print(f"WARN: _github_push content decode failed attempt {attempt}: {de} action={action}", file=sys.stderr)
                            latest_remote = None
                    else:
                        latest_remote = {}
                else:
                    print(f"WARN: _github_push GET returned non-dict wrapper type={type(wrapper)} action={action}", file=sys.stderr)
                    latest_remote = None
            elif g.status_code == 404:
                sha = None
                latest_remote = {}
                print(f"INFO: _github_push GET 404 (file not exists yet) action={action}", file=sys.stderr)
            elif g.status_code in (401, 403):
                msg = f"GET auth failed {g.status_code}: {g.text[:200]}"
                print(f"ERROR: _github_push {msg} action={action}", file=sys.stderr)
                _set_last_error(msg, status=g.status_code)
                return False
            elif g.status_code == 409:
                msg = f"GET 409 conflict attempt {attempt}"
                print(f"WARN: _github_push {msg} action={action}", file=sys.stderr)
                _set_last_error(msg, status=409)
                if attempt < max_retries:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                return False
            elif g.status_code == 429 or g.status_code >= 500:
                msg = f"GET {g.status_code}: {g.text[:200]}"
                print(f"WARN: _github_push {msg} attempt {attempt}/{max_retries} action={action}", file=sys.stderr)
                _set_last_error(msg, status=g.status_code)
                last_err_msg = msg
                if attempt < max_retries:
                    sleep = 1.0 * (2 ** (attempt - 1))
                    time.sleep(sleep)
                    continue
                return False
            else:
                msg = f"GET unexpected {g.status_code}: {g.text[:200]}"
                print(f"WARN: _github_push {msg} attempt {attempt} action={action}", file=sys.stderr)
                _set_last_error(msg, status=g.status_code)
                last_err_msg = msg
                # don't retry on other 4xx
                return False

            # --- decide wl_to_push: always merge latest_remote + pending to avoid lost-update ---
            # On first attempt we already have latest_remote from the GET.
            # Merging it with pending ensures a concurrent writer (e.g. cron) that added
            # a token between our earlier load and this push does not get overwritten.
            if latest_remote is not None:
                try:
                    pending_now = _load_pending()
                    merged = dict(latest_remote)
                    if pending_now:
                        merged = _apply_ops(merged, pending_now)
                    # pending adds should win with the newest metadata from wl
                    pending_add_map = {op["ca"]: op for op in pending_now if op.get("op") == "add"}
                    pending_remove = {op["ca"] for op in pending_now if op.get("op") == "remove"}
                    for ca in pending_add_map:
                        if ca in wl:
                            merged[ca] = wl[ca]
                    # safety union: keep keys from original wl that are not pending removals
                    # (covers direct edits not via pending, though normally pending covers all)
                    for k, v in wl.items():
                        if k not in merged and k not in pending_remove:
                            merged[k] = v
                    wl_to_push = merged
                    if attempt > 1:
                        print(f"INFO: _github_push retry merge: latest {len(latest_remote)} + pending {len(pending_now)} => {len(merged)} action={action}", file=sys.stderr)
                except Exception as me:
                    print(f"WARN: _github_push merge failed: {me}, using original wl action={action}", file=sys.stderr)
                    wl_to_push = wl
            else:
                wl_to_push = wl

            body = {
                "message": f"watchlist: {action} (attempt {attempt})" if attempt > 1 else f"watchlist: {action}",
                "content": base64.b64encode(json.dumps(wl_to_push, indent=1).encode()).decode(),
            }
            if sha:
                body["sha"] = sha

            try:
                p = requests.put(url, headers=hdrs, json=body, timeout=15)
            except requests.RequestException as exc:
                print(f"WARN: _github_push PUT network error attempt {attempt}/{max_retries}: {exc} action={action}", file=sys.stderr)
                _set_last_error(f"PUT network error: {exc}", status=None)
                last_err_msg = f"PUT network error: {exc}"
                if attempt < max_retries:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                return False

            if p.status_code in (200, 201):
                _REMOTE_CACHE["data"] = dict(wl_to_push)
                _REMOTE_CACHE["ts"] = time.time()
                _set_last_error("", status=p.status_code)
                print(f"INFO: _github_push success attempt {attempt} status {p.status_code} action={action}", file=sys.stderr)
                return True

            last_err_msg = f"PUT {p.status_code}: {p.text[:300]}"
            print(f"WARN: _github_push PUT failed attempt {attempt}/{max_retries} status {p.status_code}: {p.text[:300]} action={action}", file=sys.stderr)
            _set_last_error(last_err_msg, status=p.status_code)

            if p.status_code == 409:
                print(f"INFO: _github_push PUT 409 conflict, will re-fetch sha and retry action={action}", file=sys.stderr)
                if attempt < max_retries:
                    time.sleep(0.5 * (2 ** (attempt - 1)) + 0.1 * attempt)
                    continue
                return False
            elif p.status_code == 429 or p.status_code >= 500:
                if attempt < max_retries:
                    sleep = 1.0 * (2 ** (attempt - 1))
                    print(f"INFO: _github_push retrying after {sleep}s due to {p.status_code} action={action}", file=sys.stderr)
                    time.sleep(sleep)
                    continue
                return False
            elif p.status_code in (401, 403):
                print(f"ERROR: _github_push PUT auth error {p.status_code} action={action} check token rotation", file=sys.stderr)
                return False
            else:
                return False

        except Exception as exc:
            print(f"ERROR: _github_push unexpected error attempt {attempt}/{max_retries}: {exc} action={action}", file=sys.stderr)
            _set_last_error(f"unexpected: {exc}", status=None)
            last_err_msg = f"unexpected: {exc}"
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False

    print(f"ERROR: _github_push failed after {max_retries} attempts action={action} last={last_err_msg}", file=sys.stderr)
    return False


def _fetch_raw_remote(force_refresh: bool = False) -> dict | None:
    """Fetch raw remote with TTL cache, returning a copy or None."""
    now = time.time()
    if not force_refresh and _REMOTE_CACHE["data"] is not None and (now - _REMOTE_CACHE["ts"]) < _CACHE_TTL:
        try:
            return dict(_REMOTE_CACHE["data"])
        except Exception:
            return _REMOTE_CACHE["data"]

    remote = _github_pull()
    if remote is not None:
        if not isinstance(remote, dict):
            print(f"WARN: _fetch_raw_remote got non-dict {type(remote)}, coercing to {{}}", file=sys.stderr)
            remote = {}
        _REMOTE_CACHE["data"] = dict(remote)
        _REMOTE_CACHE["ts"] = now
        try:
            return dict(remote)
        except Exception:
            return remote

    # fallback to stale cache if pull failed
    if _REMOTE_CACHE["data"] is not None:
        age = now - _REMOTE_CACHE["ts"]
        print(f"WARN: _github_pull returned None, using stale cache age {age:.0f}s", file=sys.stderr)
        try:
            return dict(_REMOTE_CACHE["data"])
        except Exception:
            return _REMOTE_CACHE["data"]
    return None


def _load_and_merge(force_refresh: bool = False) -> dict:
    """Load raw remote + pending journal merged, without pushing.

    This is the non-pushing core used by add/remove to avoid double-push.
    """
    raw = _fetch_raw_remote(force_refresh=force_refresh)
    if raw is None:
        # offline fallback to local file
        try:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f) or {}
                raw = loaded if isinstance(loaded, dict) else {}
        except Exception:
            raw = {}

    if not isinstance(raw, dict):
        print(f"WARN: raw watchlist not dict type={type(raw)}, resetting", file=sys.stderr)
        raw = {}

    pending = _load_pending()
    if pending:
        still = []
        for op in pending:
            try:
                ca = op.get("ca")
                if not ca:
                    continue
                in_repo = ca in raw
                if (op.get("op") == "add" and in_repo) or (op.get("op") == "remove" and not in_repo):
                    continue
                still.append(op)
            except Exception as exc:
                print(f"WARN: _load_and_merge pending check failed: {exc} op={op}", file=sys.stderr)
                still.append(op)
        if still != pending:
            _save_pending(still)
            pending = still
        if pending:
            raw = _apply_ops(raw, pending)
    return raw


def load_watchlist(force_refresh: bool = False) -> dict:
    """Merge: repo copy (durable truth) + pending journal (recent local ops).

    Pending ops always win; they are dropped only once the repo reflects them.
    An add/remove therefore never visually reverts.

    Uses a short TTL cache to avoid hammering GitHub on every Streamlit rerun.
    """
    merged = _load_and_merge(force_refresh=force_refresh)
    pending = _load_pending()
    if pending:
        # opportunistic flush: try committing the merged state once per load
        if _github_token():
            if _github_push(merged, "sync pending ops"):
                _save_pending([])
            else:
                print(f"WARN: load_watchlist sync pending ops push failed, keeping {len(pending)} pending ops", file=sys.stderr)
    try:
        atomic_write_json(WATCHLIST_PATH, merged, indent=1)
    except Exception as exc:
        print(f"WARN: failed to save {WATCHLIST_PATH}: {exc}", file=sys.stderr)
    return merged


def save_watchlist(wl: dict, action: str = "update") -> bool:
    """Write locally AND commit to GitHub. Returns True if committed."""
    try:
        atomic_write_json(WATCHLIST_PATH, wl, indent=1)
    except Exception as exc:
        print(f"WARN: failed to save {WATCHLIST_PATH}: {exc}", file=sys.stderr)

    success = _github_push(wl, action)
    if success:
        pending = _load_pending()
        if pending:
            still = []
            for op in pending:
                try:
                    ca = op.get("ca")
                    if not ca:
                        continue
                    in_repo = ca in wl
                    if (op.get("op") == "add" and in_repo) or (op.get("op") == "remove" and not in_repo):
                        continue
                    still.append(op)
                except Exception as exc:
                    print(f"WARN: save_watchlist pending check failed: {exc}", file=sys.stderr)
                    still.append(op)
            if still != pending:
                _save_pending(still)
    else:
        print(f"WARN: save_watchlist push failed action={action}, pending journal kept", file=sys.stderr)
    return success


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
    # Flag the CA for the main app's auto-refresh sweep
    try:
        import streamlit as st
        pending = st.session_state.setdefault(
            "watchlist_auto_refresh_cas", set())
        pending.add(ca)
    except Exception:
        pass
    # use non-pushing loader to avoid double push
    wl = _load_and_merge(force_refresh=False)
    wl[ca] = {**entry, **(wl.get(ca) or {})}
    if symbol and symbol != "?":
        wl[ca]["symbol"] = symbol
    if source:
        wl[ca]["source"] = source
    if avg_cost is not None:
        wl[ca]["avg_cost"] = float(avg_cost)
    return save_watchlist(wl, f"add {symbol} ({ca[:8]}…)")


def remove_from_watchlist(ca: str) -> bool:
    _journal({"op": "remove", "ca": ca})
    wl = _load_and_merge(force_refresh=False)
    meta = wl.pop(ca, None) or {}
    return save_watchlist(wl, f"remove {meta.get('symbol', '?')} "
                              f"({ca[:8]}…)")


# ---------------------------------------------------------------------------
# 15m Wyckoff snapshot (cron writes local; workflow commits watchlist.json)
# ---------------------------------------------------------------------------
WYCKOFF_FRESH_SEC = 45 * 60
TRIGGER_HOLD_SEC = 3 * 3600
DETAILS_STALE_SEC = 12 * 3600
_GRADE_C_TYPE = "⚪ GRADE C: ROUTINE NOISE"
_NORMAL_TYPES = frozenset({
    "", "➖ NORMAL", "PRE_PUMP_DETECTION", _GRADE_C_TYPE,
})


def update_local_meta(ca, fields):
    """Merge ``fields`` into local watchlist.json without a GitHub push.

    The 15m cron uses this so the workflow commit picks up the latest
    lock / vol / CVD / score even when no Telegram trigger fired.
    """
    ca = str(ca or "").strip()
    if not ca or not isinstance(fields, dict):
        return None
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            wl = json.load(f) or {}
    except Exception:
        wl = {}
    if not isinstance(wl, dict):
        wl = {}
    entry = dict(wl.get(ca) or {})
    for key, value in fields.items():
        if value is not None:
            entry[key] = value
    wl[ca] = entry
    try:
        atomic_write_json(WATCHLIST_PATH, wl, indent=1)
    except Exception as exc:
        print(f"WARN: failed to save {WATCHLIST_PATH}: {exc}",
              file=sys.stderr)
        return None
    return entry


def meta_details_stale(meta, now_ts=None):
    """True when diamond / real-dust should be refreshed from live APIs."""
    now_ts = int(now_ts or time.time())
    ts = (meta or {}).get("details_ts")
    if ts in (None, "", 0, "0"):
        return True
    try:
        return (now_ts - int(ts)) > DETAILS_STALE_SEC
    except (TypeError, ValueError):
        return True


PREPUMP_FRESH_SEC = 36 * 3600


def resolve_prepump_row(meta, sig=None, now_ts=None):
    """Pick the freshest 4-pillar snapshot for one watchlist row.

    Preference: ``prepump_*`` fields written by the daily/4h cron, then
    a ``prepump_4pilar`` row in ``signals.json``.
    """
    now_ts = int(now_ts or time.time())
    meta = meta or {}
    sig = sig or {}
    snap_ts = 0
    try:
        snap_ts = int(meta.get("prepump_ts") or 0)
    except (TypeError, ValueError):
        snap_ts = 0
    sig_ts = 0
    try:
        sig_ts = int(sig.get("ts") or 0)
    except (TypeError, ValueError):
        sig_ts = 0
    use_snap = snap_ts > 0 and snap_ts >= sig_ts
    if use_snap:
        src_ts = snap_ts
        verdict = meta.get("prepump_verdict") or ""
        phase = meta.get("prepump_phase") or ""
        passed = meta.get("prepump_passed")
        total = meta.get("prepump_total")
        stealth = bool(meta.get("prepump_stealth_dump"))
        absorption = meta.get("prepump_absorption_pct")
        buy_tx = meta.get("prepump_buy_tx_pct")
        avg_buy = meta.get("prepump_avg_buy_sol")
        avg_sell = meta.get("prepump_avg_sell_sol")
        vol_change = meta.get("prepump_vol_change_pct")
        source = "snapshot"
    elif sig_ts > 0 and sig.get("type") == "prepump_4pilar":
        src_ts = sig_ts
        verdict = sig.get("verdict") or ""
        phase = sig.get("phase") or ""
        passed = sig.get("passed")
        total = sig.get("total")
        stealth = bool(sig.get("stealth_dump"))
        detail = sig.get("detail") or {}
        metrics = detail.get("metrics") or {}
        absorption = metrics.get("absorption_pct")
        buy_tx = metrics.get("buy_tx_pct")
        avg_buy = metrics.get("avg_buy_sol")
        avg_sell = metrics.get("avg_sell_sol")
        vol_change = metrics.get("volume_change_pct")
        source = "signal"
    else:
        return {
            "verdict": "",
            "phase": "",
            "passed": None,
            "total": None,
            "stealth_dump": False,
            "absorption_pct": None,
            "buy_tx_pct": None,
            "avg_buy_sol": None,
            "avg_sell_sol": None,
            "vol_change_pct": None,
            "ts": None,
            "stale": False,
            "source": "none",
        }
    return {
        "verdict": verdict,
        "phase": phase,
        "passed": passed,
        "total": total,
        "stealth_dump": stealth,
        "absorption_pct": absorption,
        "buy_tx_pct": buy_tx,
        "avg_buy_sol": avg_buy,
        "avg_sell_sol": avg_sell,
        "vol_change_pct": vol_change,
        "ts": src_ts,
        "stale": (now_ts - src_ts) > PREPUMP_FRESH_SEC,
        "source": source,
    }


def resolve_wyckoff_row(meta, sig, now_ts=None):
    """Pick the freshest 15m numbers for one watchlist row.

    Preference:
      1. ``wyckoff_*`` snapshot on the watchlist entry (written every
         cron cycle, pulled live from GitHub on Streamlit Cloud)
      2. latest triggered Wyckoff row in signals.json
    Trigger badges older than ``TRIGGER_HOLD_SEC`` expire to NORMAL so
    a 4-hour-old absorption does not look current. Grade C is shown as
    NORMAL (muted noise) but vol / CVD / lock / score stay visible.
    """
    now_ts = int(now_ts or time.time())
    meta = meta or {}
    sig = sig or {}
    snap_ts = 0
    try:
        snap_ts = int(meta.get("wyckoff_ts") or 0)
    except (TypeError, ValueError):
        snap_ts = 0
    sig_ts = 0
    try:
        sig_ts = int(sig.get("ts") or 0)
    except (TypeError, ValueError):
        sig_ts = 0

    use_snap = snap_ts > 0 and snap_ts >= sig_ts
    if use_snap:
        raw_type = str(meta.get("wyckoff_type") or "")
        score = meta.get("wyckoff_score")
        vol_sol = meta.get("wyckoff_volume_sol")
        cvd_sol = meta.get("wyckoff_cvd_sol")
        lock_pct = meta.get("wyckoff_lock_pct")
        if lock_pct is None:
            lock_pct = meta.get("holder_lock_pct")
        src_ts = snap_ts
        source = "snapshot"
    elif sig_ts > 0 and "score" in sig:
        raw_type = str(sig.get("type") or "")
        score = sig.get("score")
        vol_sol = sig.get("volume_sol")
        cvd_sol = sig.get("cvd_sol")
        lock_pct = sig.get("holder_lock_pct")
        if lock_pct is None:
            lock_pct = meta.get("holder_lock_pct")
        src_ts = sig_ts
        source = "signal"
    else:
        return {
            "raw_type": "",
            "score": None,
            "ts": None,
            "vol_sol": None,
            "cvd_sol": None,
            "lock_pct": meta.get("holder_lock_pct"),
            "stale": False,
            "source": "none",
        }

    age = now_ts - src_ts
    if raw_type in _NORMAL_TYPES:
        raw_type = ""
    elif source == "signal" and age > TRIGGER_HOLD_SEC:
        raw_type = ""
    return {
        "raw_type": raw_type,
        "score": score,
        "ts": src_ts,
        "vol_sol": vol_sol,
        "cvd_sol": cvd_sol,
        "lock_pct": lock_pct,
        "stale": age > WYCKOFF_FRESH_SEC,
        "source": source,
    }
