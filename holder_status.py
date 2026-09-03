# -*- coding: utf-8 -*-
"""Snapshot status analisis holder (dust) untuk dashboard.

Scanner cron (GitHub Actions) menulis ``holder_status.json`` ke branch
``holder-live``, dashboard membacanya pada tiap rerun.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time

import requests

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_PATH = os.path.join(BASE_DIR, "holder_status.json")
GITHUB_REPO = "lparmycalprut/wallet-depth"
STATUS_REPO_PATH = "holder_status.json"
STATUS_REF = "holder-live"

_CACHE_TTL = 15
_CACHE = {"data": None, "ts": 0.0}

# Hasil publish terakhir (dipakai scanner cron untuk exit code).
_LAST_PUBLISH = {"ok": None, "error": ""}


def last_publish_result() -> dict:
    """``{"ok": bool|None, "error": str}`` dari publish_holder_status terakhir."""
    return dict(_LAST_PUBLISH)


def _empty_status() -> dict:
    return {"updated_at": None, "scanner": "holder-dust-v1", "tokens": {}}


def _holders_for_status(holders: dict | None) -> dict:
    """Buang peta address (berat) dari snapshot dashboard."""
    holders = dict(holders or {})
    holders.pop("cohort_now", None)
    mid = holders.get("mid")
    if isinstance(mid, dict):
        holders["mid"] = {
            "count": mid.get("count"),
            "value_usd": mid.get("value_usd"),
            "pct_mc": mid.get("pct_mc"),
        }
    return holders


def snapshot_status(analyses: dict | None,
                    watchlist: dict | None = None,
                    history_store: dict | None = None) -> dict:
    """Bangun payload dashboard dari hasil analisis per token."""
    try:
        from holder_history import (compact_history_for_status,
                                    load_holder_history)
        store = history_store if history_store is not None \
            else load_holder_history()
    except Exception:
        store = {"tokens": {}}
        compact_history_for_status = lambda *_a, **_k: []  # noqa: E731
    tokens = {}
    stamps = []
    for mint, result in (analyses or {}).items():
        if not mint or not isinstance(result, dict):
            continue
        meta = (watchlist or {}).get(mint) or {}
        hist_slot = ((store.get("tokens") or {}).get(mint) or {})
        token = {
            "symbol": str(meta.get("symbol")
                          or result.get("symbol") or mint[:8]),
            "marketcap": result.get("marketcap"),
            "price": result.get("price"),
            "analyzed_at": result.get("analyzed_at"),
            "holders": _holders_for_status(result.get("holders") or {}),
            "history": compact_history_for_status(store, mint),
            "cohort": hist_slot.get("cohort") or {},
        }
        tokens[mint] = token
        if token["analyzed_at"]:
            stamps.append(int(token["analyzed_at"]))
    return {
        "updated_at": max(stamps) if stamps else None,
        "scanner": "holder-dust-v1",
        "tokens": tokens,
    }


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
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as h:
            return str((json.load(h) or {}).get("github_token", "")).strip()
    except Exception:
        return ""


def _parse_status_payload(data) -> dict | None:
    if isinstance(data, dict) and isinstance(data.get("tokens"), dict):
        return {
            "updated_at": data.get("updated_at"),
            "scanner": data.get("scanner") or "holder-dust-v1",
            "tokens": data["tokens"],
        }
    return None


def _contents_url(ref: str | None = None) -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATUS_REPO_PATH}"
    return f"{url}?ref={ref}" if ref else url


def _github_pull() -> dict | None:
    tok = _github_token()
    headers = {"Accept": "application/vnd.github.raw+json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    for ref in (STATUS_REF, "main"):
        try:
            response = requests.get(_contents_url(ref), headers=headers,
                                    timeout=10)
        except requests.RequestException as exc:
            print(f"WARN: holder_status API {ref} network error: {exc}",
                  file=sys.stderr)
            continue
        if response.status_code != 200:
            if response.status_code != 404:
                print(f"WARN: holder_status API {ref} {response.status_code}: "
                      f"{response.text[:200]}", file=sys.stderr)
            continue
        try:
            parsed = _parse_status_payload(response.json())
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: holder_status API {ref} parse failed: {exc}",
                  file=sys.stderr)
            parsed = None
        if parsed is not None:
            return parsed
    try:
        raw = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{STATUS_REF}/{STATUS_REPO_PATH}"
        response = requests.get(raw, params={"t": int(time.time())},
                                headers={"Cache-Control": "no-cache",
                                         "Pragma": "no-cache"}, timeout=10)
        if response.status_code == 200:
            return _parse_status_payload(response.json()) or _empty_status()
    except (requests.RequestException, ValueError) as exc:
        print(f"WARN: holder_status raw CDN failed: {exc}", file=sys.stderr)
    return None


def _ensure_status_branch(headers: dict) -> bool:
    refs = f"https://api.github.com/repos/{GITHUB_REPO}/git/ref/heads/{STATUS_REF}"
    try:
        existing = requests.get(refs, headers=headers, timeout=10)
    except requests.RequestException as exc:
        print(f"WARN: holder_status ref lookup failed: {exc}", file=sys.stderr)
        return False
    if existing.status_code == 200:
        return True
    try:
        repo = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}",
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
            # Branch baru: beri GitHub waktu sebelum GET contents di
            # branch tersebut (kalau tidak, GET 404 → PUT tanpa sha → 422).
            time.sleep(2.0)
            return True
        print(f"WARN: holder_status create ref {created.status_code}: "
              f"{created.text[:200]}", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"WARN: holder_status create ref failed: {exc}", file=sys.stderr)
    return False


def _github_push(status: dict, message: str, max_retries: int = 4) -> bool:
    tok = _github_token()
    if not tok:
        print("WARN: holder_status push skipped (no github_token)",
              file=sys.stderr)
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATUS_REPO_PATH}"
    headers = {"Authorization": f"Bearer {tok}",
               "Accept": "application/vnd.github+json"}
    target_ref = STATUS_REF if _ensure_status_branch(headers) else "main"
    if target_ref == "main":
        print("WARN: holder_status falling back to main", file=sys.stderr)
    body_content = base64.b64encode(
        json.dumps(status, indent=2, sort_keys=True).encode()).decode()
    for attempt in range(1, max_retries + 1):
        try:
            current = requests.get(_contents_url(target_ref), headers=headers,
                                   timeout=15)
        except requests.RequestException as exc:
            print(f"WARN: holder_status GET failed: {exc}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        sha = None
        if current.status_code == 200:
            try:
                sha = (current.json() or {}).get("sha")
            except Exception:  # noqa: BLE001
                sha = None
        elif current.status_code != 404:
            if current.status_code in (401, 403):
                print(f"ERROR: holder_status GET auth {current.status_code}",
                      file=sys.stderr)
                return False
            if attempt < max_retries and (current.status_code in (409, 429)
                                          or current.status_code >= 500):
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        payload = {"message": message, "content": body_content,
                   "branch": STATUS_REF}
        if sha:
            payload["sha"] = sha
        try:
            put = requests.put(url, headers=headers, json=payload, timeout=15)
        except requests.RequestException as exc:
            print(f"WARN: holder_status PUT failed: {exc}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        if put.status_code in (200, 201):
            return True
        print(f"WARN: holder_status PUT {put.status_code}: "
              f"{put.text[:200]}", file=sys.stderr)
        # 422 "sha wasn't supplied": file sudah ada di branch (branch baru
        # dibuat dari main yang sudah punya holder_status.json, GET sesaat
        # sesudahnya masih 404). Tunggu lalu ulangi GET sha.
        if put.status_code in (409, 422, 429) or put.status_code >= 500:
            if attempt < max_retries:
                time.sleep(1.0 * (2 ** (attempt - 1)))
                continue
        return False
    return False


def load_holder_status(force_refresh: bool = False) -> dict:
    """Muat snapshot: GitHub (durable) → file lokal → kosong."""
    now = time.time()
    if (not force_refresh and _CACHE["data"] is not None
            and (now - _CACHE["ts"]) < _CACHE_TTL):
        return dict(_CACHE["data"])
    remote = _github_pull()
    local = None
    try:
        with open(STATUS_PATH, encoding="utf-8") as handle:
            local = _parse_status_payload(json.load(handle))
    except (OSError, ValueError, TypeError):
        local = None
    candidates = [item for item in (remote, local) if item and item.get("tokens")]
    if not candidates:
        status = remote or local or _empty_status()
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


def publish_holder_status(analyses: dict,
                          watchlist: dict | None = None,
                          *, push: bool = True) -> dict:
    """Tulis status lokal + (opsional) publish ke GitHub."""
    status = snapshot_status(analyses, watchlist)
    atomic_write_json(STATUS_PATH, status, indent=2)
    _CACHE["data"] = dict(status)
    _CACHE["ts"] = time.time()
    if push:
        stamp = status.get("updated_at") or int(time.time())
        if not _github_token():
            _LAST_PUBLISH["ok"] = False
            _LAST_PUBLISH["error"] = "no github_token"
        else:
            ok = _github_push(status,
                              f"holder-status: snapshot {stamp} [skip ci]")
            _LAST_PUBLISH["ok"] = bool(ok)
            _LAST_PUBLISH["error"] = "" if ok else "github push failed"
        if not _LAST_PUBLISH["ok"]:
            print("WARN: holder_status GitHub publish failed "
                  f"({_LAST_PUBLISH['error']}); dashboard akan pakai "
                  "snapshot lokal", file=sys.stderr)
    else:
        _LAST_PUBLISH["ok"] = None
        _LAST_PUBLISH["error"] = ""
    return status


def reset_cache() -> None:
    """Test helper."""
    _CACHE["data"] = None
    _CACHE["ts"] = 0.0
