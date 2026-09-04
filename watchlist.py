# -*- coding: utf-8 -*-
"""Shared watchlist helpers (used by app, watchlist page, and the cron job).

On Streamlit Cloud the filesystem is ephemeral: local writes are lost on
every redeploy. If a GitHub token is available (secrets/config/env), every
add/remove is also committed straight to the repo so it truly persists.
"""

import base64
import json
import os
import re
import sys
import time
from datetime import datetime

import requests

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
PENDING_PATH = os.path.join(BASE_DIR, "watchlist_pending.json")
GITHUB_REPO = "lparmycalprut/wallet-depth"

# Solana/Base58 mint addresses are case-sensitive.  EVM addresses are not,
# so only a syntactically valid 0x address is case-folded.
_EVM_ADDRESS_RE = re.compile(r"0x[0-9a-f]{40}", re.IGNORECASE)


def normalize_address(address: str) -> str:
    """Trim an address and canonicalize formats that are case-insensitive."""
    normalized = str(address or "").strip()
    if _EVM_ADDRESS_RE.fullmatch(normalized):
        return normalized.lower()
    return normalized


def address_key(address: str) -> str:
    """Comparison key for a contract/mint address."""
    return normalize_address(address)


def watchlist_address_keys(watchlist: dict | None) -> set[str]:
    """Normalized non-empty address keys in *watchlist*."""
    return {key for key in (address_key(raw) for raw in (watchlist or {}))
            if key}


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
        elif op.get("op") == "source":
            # Pindah card (Watchlist Holder <-> Chart LP): source terakhir
            # menang, field lain tidak disentuh. Entri disalin supaya dict
            # yang di-cache remote tidak ikut termutasi.
            entry = wl.get(op["ca"])
            if isinstance(entry, dict) and op.get("source"):
                wl[op["ca"]] = {**entry, "source": str(op["source"])}
    return wl


def _op_is_applied(op: dict, wl: dict) -> bool:
    """True bila isi repo *wl* sudah mencerminkan *op* (op boleh dibuang)."""
    ca = op.get("ca")
    if not ca:
        return True
    kind = op.get("op")
    entry = wl.get(ca)
    if kind == "add":
        return entry is not None
    if kind == "remove":
        return entry is None
    if kind == "source":
        return (isinstance(entry, dict)
                and str(entry.get("source") or "")
                == str(op.get("source") or ""))
    return True


def _prune_pending(pending: list, wl: dict) -> list:
    """Buang op journal yang sudah tercermin di repo."""
    still = []
    for op in pending:
        try:
            if _op_is_applied(op, wl):
                continue
        except Exception as exc:
            print(f"WARN: _prune_pending check failed: {exc} op={op}",
                  file=sys.stderr)
        still.append(op)
    return still


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
        still = _prune_pending(pending, raw)
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
            still = _prune_pending(pending, wl)
            if still != pending:
                _save_pending(still)
    else:
        print(f"WARN: save_watchlist push failed action={action}, pending journal kept", file=sys.stderr)
    return success


def _journal(op: dict) -> None:
    """Append an op to the pending journal; an add cancels earlier removes
    for the same CA and vice versa (last op wins)."""
    _journal_many([op])


def _journal_many(ops: list[dict]) -> None:
    """Journal multiple operations with one atomic write (last op wins)."""
    if not ops:
        return
    incoming: dict[str, dict] = {}
    for op in ops:
        key = address_key(op.get("ca"))
        if key:
            incoming[key] = op
    pending = []
    for op in _load_pending():
        key = address_key(op.get("ca"))
        if key not in incoming:
            pending.append(op)
            continue
        # "source" (pindah card) yang menyusul "add" belum ter-commit: lebur
        # ke op add supaya entri baru tidak hilang saat journal diputar ulang.
        if op.get("op") == "add" and incoming[key].get("op") == "source":
            incoming[key] = {**op, "source": incoming[key].get("source")}
    pending.extend(incoming.values())
    _save_pending(pending)


def fetch_token_symbol(ca: str) -> str:
    """Resolve ticker from DexScreener; return '?' if lookup fails."""
    try:
        from core import get_market
        market = get_market(ca) or {}
        symbol = str(market.get("symbol") or "").strip()
        if symbol and symbol != "?":
            return symbol
    except Exception as exc:
        print(f"WARN: fetch_token_symbol failed for {ca[:8]}: {exc}",
              file=sys.stderr)
    return "?"


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
    ca = normalize_address(ca)
    if not ca:
        return False
    if not symbol or symbol == "?":
        # Symbol tidak diketahui (manual add / pindah card) → ambil dari
        # DexScreener supaya card tidak menampilkan "$?".
        symbol = fetch_token_symbol(ca)
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
    saved = save_watchlist(wl, f"add {symbol} ({ca[:8]}…)")
    # Ask Actions to pull the last 48h immediately (best-effort).
    request_immediate_scan()
    return saved


def add_many_to_watchlist(rows, *, source: str = "") -> dict:
    """Add unique scan rows in one local save/GitHub push.

    Each row must contain ``ca`` (``mint`` is accepted as a fallback) and may
    contain ``symbol``. Existing and input-duplicate addresses are not
    written again. The returned counters describe local durable intent; a
    failed remote push remains protected by the existing pending journal.
    """
    rows = list(rows or [])
    watchlist = dict(_load_and_merge(force_refresh=False) or {})
    known = watchlist_address_keys(watchlist)
    seen: set[str] = set()
    operations: list[dict] = []
    added_addresses: list[str] = []
    skipped = duplicates = invalid = 0

    for raw in rows:
        if not isinstance(raw, dict):
            invalid += 1
            continue
        ca = normalize_address(raw.get("ca") or raw.get("mint"))
        key = address_key(ca)
        if not key:
            invalid += 1
            continue
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        if key in known:
            skipped += 1
            continue

        symbol = str(raw.get("symbol") or "?").strip() or "?"
        entry = {
            "symbol": symbol,
            "note": str(raw.get("note") or ""),
            "added": datetime.now().strftime("%Y-%m-%d"),
        }
        row_source = str(source or raw.get("source") or "").strip()
        if row_source:
            entry["source"] = row_source
        for field in ("down_ath", "avg_cost"):
            if raw.get(field) is not None:
                try:
                    entry[field] = float(raw[field])
                except (TypeError, ValueError):
                    pass

        watchlist[ca] = entry
        known.add(key)
        added_addresses.append(ca)
        operations.append({"op": "add", "ca": ca, **entry})

    if not operations:
        return {
            "added": 0, "skipped": skipped, "duplicates": duplicates,
            "invalid": invalid, "saved": None, "addresses": [],
        }

    # Journal before any write/network operation, matching add_to_watchlist's
    # durability guarantee while avoiding N journal writes and N commits.
    _journal_many(operations)
    try:
        import streamlit as st
        pending = st.session_state.setdefault("watchlist_auto_refresh_cas", set())
        pending.update(added_addresses)
    except Exception:
        pass

    label = f"add {len(added_addresses)} token dari {source or 'scanner'}"
    saved = save_watchlist(watchlist, label)
    request_immediate_scan()
    return {
        "added": len(added_addresses), "skipped": skipped,
        "duplicates": duplicates, "invalid": invalid,
        "saved": bool(saved), "addresses": added_addresses,
    }


def request_immediate_scan() -> bool:
    """Dispatch the scanner workflow so a new CA is fetched within seconds."""
    tok = _github_token()
    if not tok:
        return False
    try:
        response = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/"
            f"daily-effort.yml/dispatches",
            headers={"Authorization": f"Bearer {tok}",
                     "Accept": "application/vnd.github+json"},
            json={"ref": "main"},
            timeout=15)
        if response.status_code in (201, 204):
            return True
        print(f"WARN: request_immediate_scan {response.status_code}: "
              f"{response.text[:200]}", file=sys.stderr)
    except Exception as exc:
        print(f"WARN: request_immediate_scan failed: {exc}", file=sys.stderr)
    return False


def remove_from_watchlist(ca: str) -> bool:
    ca = normalize_address(ca)
    if not ca:
        return False
    _journal({"op": "remove", "ca": ca})
    wl = _load_and_merge(force_refresh=False)
    meta = wl.pop(ca, None) or {}
    return save_watchlist(wl, f"remove {meta.get('symbol', '?')} "
                              f"({ca[:8]}…)")


def set_watchlist_source(ca: str, source: str) -> bool:
    """Pindahkan token antar card watchlist dengan mengubah ``source``.

    ``source="meteora"`` → masuk card **Chart LP** (watchlist Meteora di
    bagian atas dashboard); ``source="manual"`` → kembali ke watchlist
    holder biasa. Entri yang belum ada di watchlist tidak dibuat.
    """
    ca = normalize_address(ca)
    source = str(source or "").strip().lower()
    if not ca or not source:
        return False
    wl = _load_and_merge(force_refresh=False)
    entry = wl.get(ca)
    if not isinstance(entry, dict):
        # Tidak membuat entri baru: hanya token yang sudah ada yang dipindah.
        return False
    if str(entry.get("source") or "").strip().lower() == source:
        return True
    _journal({"op": "source", "ca": ca, "source": source})
    wl[ca] = {**entry, "source": source}
    symbol = entry.get("symbol") or "?"
    return save_watchlist(wl, f"move {symbol} ({ca[:8]}…) → {source}")


def update_local_meta(ca, fields):
    """Merge detector fields into the local watchlist without a remote push."""
    ca = str(ca or "").strip()
    if not ca or not isinstance(fields, dict):
        return None
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as handle:
            watchlist = json.load(handle) or {}
    except (OSError, ValueError, TypeError):
        watchlist = {}
    entry = dict(watchlist.get(ca) or {})
    entry.update({key: value for key, value in fields.items()
                  if value is not None})
    watchlist[ca] = entry
    try:
        atomic_write_json(WATCHLIST_PATH, watchlist, indent=1)
    except Exception as exc:
        print(f"WARN: failed to save {WATCHLIST_PATH}: {exc}", file=sys.stderr)
        return None
    return entry
