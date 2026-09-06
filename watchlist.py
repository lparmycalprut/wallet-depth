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
import threading
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
# 60 detik sejak 2026-09-06: satu klik di UI (tambah/hapus/pindah card) tidak
# lagi menarik GitHub dua kali — perubahan lokal **men-seed** cache ini (lihat
# :func:`_seed_remote_cache`), jadi render ulang langsung memakai state terbaru
# tanpa menunggu TTL kedaluwarsa. TTL panjang hanya memperlambat terlihatnya
# perubahan dari *sesi lain* (browser kedua), itu pun disusul paling lambat 60s.
_CACHE_TTL = 60  # seconds
# Cache per repo path: ``{repo_path: {"data": dict, "ts": float,
# "settled": bool}}`` supaya watchlist Solana dan Robinhood tidak saling
# menimpa dalam satu proses.
#
# ``settled`` membedakan dua isi cache:
#   * ``True``  -> isi **mencerminkan repo** (hasil pull GitHub atau push yang
#                  sudah sukses). Jurnal pending **boleh** di-prune terhadapnya.
#   * ``False`` -> isi **optimis belaka** (seed dari jalur UI saat perubahan baru
#                  saja ditulis lokal; commit GitHub belum tentu sampai).
#                  Jurnal **tidak boleh** di-prune terhadapnya — kalau di-prune,
#                  op (mis. ``remove``) hilang sebelum remote menerimanya, dan
#                  token yang dihapus muncul lagi di render berikutnya.
_REMOTE_CACHE: dict[str, dict] = {}

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
    _REMOTE_CACHE.clear()
    _LAST_PUSH_ERROR["msg"] = ""
    _LAST_PUSH_ERROR["ts"] = 0.0
    _LAST_PUSH_ERROR["status"] = None
    with _PUSH_LOCK:
        _PUSH_QUEUES.clear()
        _PUSH_RESULT.clear()
        _SCAN_DISPATCH["ts"] = 0.0


def _load_pending(path: str | None = None) -> list:
    target = str(path or PENDING_PATH)
    try:
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_pending(ops: list, path: str | None = None) -> None:
    target = str(path or PENDING_PATH)
    try:
        atomic_write_json(target, ops)
    except Exception as exc:
        print(f"WARN: failed to save {target}: {exc}", file=sys.stderr)


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


def _github_pull(repo_path: str | None = None) -> dict | None:
    """Read a watchlist file from the repo (source of truth).

    Order:
      1. GitHub API with token (no CDN cache)
      2. GitHub API without token (avoids raw CDN, but rate-limited 60/h)
      3. raw.githubusercontent.com with cache-busting + no-cache headers

    ``repo_path`` defaults to ``watchlist.json``; Robinhood uses its own
    file (``watchlist_robinhood.json``) so the two networks stay separate.
    """
    repo_path = str(repo_path or "watchlist.json").strip().lstrip("/")
    tok = _github_token()

    # 1) API with token
    if tok:
        try:
            r = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/"
                f"{repo_path}",
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
            f"{repo_path}",
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
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{repo_path}"
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


def _github_push(wl: dict, action: str, max_retries: int = 3,
                 repo_path: str | None = None,
                 pending_path: str | None = None,
                 merge_journal: bool = True) -> bool:
    """Commit a watchlist file to the repo with retry + re-fetch sha on 409.

    ``repo_path`` defaults to ``watchlist.json``; the Robinhood watchlist
    uses ``watchlist_robinhood.json`` while keeping the same durable
    journal/merge semantics.

    On 409 conflict it re-fetches the latest remote, merges pending ops
    (and the original wl) to avoid lost-update, then retries.

    ``pending_path`` **wajib** dipakai bersama file watchlist-nya: tanpa itu,
    jurnal Solana ikut di-merge ke payload Robinhood (dan sebaliknya) sehingga
    mint dari jaringan lain bisa nyempil di file yang salah.
    ``merge_journal=False`` menutup merge itu untuk file non-watchlist
    (``holder_status*.json`` memakai fungsi push yang sama tapi tidak punya
    jurnal operasi).
    """
    repo_path = str(repo_path or "watchlist.json").strip().lstrip("/")
    tok = _github_token()
    if not tok:
        _set_last_error("no github_token configured", status=0)
        print(f"WARN: _github_push no token, action={action}", file=sys.stderr)
        return False

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}"
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
                    pending_now = _load_pending(pending_path) \
                        if merge_journal else []
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
                # Push sukses = isi cache kini mencerminkan repo (settled=True),
                # sehingga jurnal pending boleh di-prune terhadapnya.
                _set_remote_cache(repo_path, wl_to_push, settled=True)
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


# ---- background push: UI tidak menunggu GitHub ------------------------------
# Satu klik ✕/➕/📋 di watchlist dulu memblokir rerun Streamlit sampai
# commit GitHub selesai: 1 pull (≤3 GET × 10 dtk) + 1 push (GET+PUT ×3
# percobaan, timeout 15 dtk) — terukur 2,4 s per klik pada RTT 0,8 dtk dan
# bisa mendekati dua menit saat API lambat. Perubahan watchlist sekarang
# ditulis lokal + di-journal **lalu** dikirim ke GitHub di thread latar:
# UI repaint instan, jurnal dibersihkan saat commit sukses.
PUSH_DEBOUNCE_SEC = 0.35   # klik beruntun dalam jendela ini jadi satu commit
_PUSH_LOCK = threading.Lock()
# ``{repo_path: {"job": (wl, action, pending_path) | None, "running": bool,
#                "thread": Thread | None}}`` — satu worker per file watchlist.
_PUSH_QUEUES: dict[str, dict] = {}
_PUSH_RESULT: dict[str, dict] = {}
_SCAN_DISPATCH: dict = {"ts": 0.0}   # rem dispatch "scan sekarang" (anti-banjir)
# Jurnal pending dibaca-ubah-tulis (bukan append atomik): worker latar
# belakang mem-prune jurnal tepat setelah commit sukses, dan pada saat yang
# sama thread UI bisa menambahkan op baru. Tanpa lock, op yang baru ditulis
# bisa hilang tertimpa hasil prune (token muncul lagi). RLock: jalur load
# kadang sudah memegangnya.
_JOURNAL_LOCK = threading.RLock()


def _norm_repo_path(repo_path) -> str:
    return str(repo_path or "watchlist.json").strip().lstrip("/")


def _set_remote_cache(repo_path: str, data: dict, settled: bool) -> None:
    """Tulis entri cache remote untuk *repo_path* dengan penanda ``settled``.

    ``settled=True`` berarti *data* adalah pandangan **terkonfirmasi** isi repo
    (hasil pull GitHub atau push yang sukses); ``settled=False`` berarti *data*
    adalah state **optimis** hasil perubahan lokal yang commit-nya belum tentu
    sampai ke GitHub (lihat :func:`_seed_remote_cache`).
    """
    _REMOTE_CACHE[_norm_repo_path(repo_path)] = {
        "data": dict(data), "ts": time.time(), "settled": bool(settled)}


def _seed_remote_cache(repo_path: str, data: dict) -> None:
    """Pakai state hasil perubahan lokal sebagai "remote terbaru" sementara.

    Tanpa ini, rerun tepat setelah klik akan menarik GitHub lagi (dan bisa
    menampilkan state **lama** karena write remote belum tentu sampai).
    :func:`_github_push` menimpa seed ini dengan isi yang benar-benar ter-commit.

    Seed ditandai ``settled=False``: ia *bukan* bukti remote menerima perubahan,
    jadi jurnal pending tidak boleh di-prune terhadapnya (lihat
    :func:`_load_and_merge`).
    """
    _set_remote_cache(repo_path, data, settled=False)


def _read_local_watchlist(local_path) -> dict | None:
    """Isi file watchlist lokal (``None`` bila tidak ada/rusak)."""
    try:
        with open(str(local_path or WATCHLIST_PATH), "r",
                  encoding="utf-8") as handle:
            loaded = json.load(handle) or {}
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def _local_entry(ca: str, *, repo_path: str | None = None,
                 local_path: str | None = None) -> dict:
    """Entri token dari state lokal (cache remote → file lokal).

    Dipakai jalur ``background`` untuk mengambil simbol sebelum journal
    applied (journal remove sudah menghapus entry-nya di state gabungan),
    supaya pesan commit tetap menyebut tickernya, bukan ``?``.
    """
    sources = (_REMOTE_CACHE.get(_norm_repo_path(repo_path), {}).get("data"),
               _read_local_watchlist(local_path))
    for source in sources:
        if isinstance(source, dict):
            entry = source.get(ca)
            if isinstance(entry, dict):
                return dict(entry)
    return {}


def push_inflight(repo_path=None) -> bool:
    """True bila masih ada antrian/pekerjaan commit untuk file watchlist ini."""
    with _PUSH_LOCK:
        queue = _PUSH_QUEUES.get(_norm_repo_path(repo_path)) or {}
        return bool(queue.get("running")) or queue.get("job") is not None


def push_status(repo_path=None) -> dict:
    """Status sinkronisasi latar belakang: ``{state, ts, msg}``.

    ``state`` = ``idle`` (tidak pernah ada antrian) / ``syncing`` (masih
    jalan) / ``ok`` (commit terakhir sukses) / ``error`` (gagal, jurnal
    dipertahankan dan dicoba lagi saat load berikutnya).
    """
    key = _norm_repo_path(repo_path)
    with _PUSH_LOCK:
        queue = _PUSH_QUEUES.get(key) or {}
        busy = bool(queue.get("running")) or queue.get("job") is not None
        result = dict(_PUSH_RESULT.get(key) or {})
    if busy:
        return {"state": "syncing", "ts": result.get("ts"), "msg": ""}
    return {"state": result.get("state") or "idle",
            "ts": result.get("ts"), "msg": result.get("msg") or ""}


def wait_for_pushes(repo_path=None, timeout: float = 30.0) -> None:
    """Join worker thread satu (atau semua) file watchlist.

    Hanya untuk uji/dev: menunggu commit latar belakang selesai supaya jurnal
    bisa diperiksa. Tidak dipakai jalur UI.
    """
    key = _norm_repo_path(repo_path) if repo_path else None
    for _round in range(4):
        with _PUSH_LOCK:
            threads = [queue.get("thread")
                       for path, queue in _PUSH_QUEUES.items()
                       if (key is None or path == key) and queue.get("running")]
        live = [thread for thread in threads if thread is not None]
        if not live:
            return
        for thread in live:
            thread.join(timeout)


def _set_push_result(repo_path: str, state: str, msg: str = "") -> None:
    _PUSH_RESULT[repo_path] = {"state": state, "ts": time.time(),
                                "msg": str(msg or "")}


def _queue_github_push(wl: dict, action: str, *, repo_path: str,
                       pending_path: str | None = None) -> None:
    """Serahkan commit ke thread latar (fire-and-forget, satu job terakhir menang).

    Job di-*coalesce*: kalau worker masih jalan, state terbaru cukup ditulis ke
    antrian — worker mengambilnya lagi setelah commit sebelumnya, jadi klik
    cepat beruntun tidak memicu balap commit.
    """
    key = _norm_repo_path(repo_path)
    job = (dict(wl), str(action), str(pending_path or PENDING_PATH))
    with _PUSH_LOCK:
        queue = _PUSH_QUEUES.setdefault(key, {"job": None, "running": False,
                                              "thread": None})
        queue["job"] = job
        if queue["running"]:
            _set_push_result(key, "syncing")
            return
        queue["running"] = True
        _set_push_result(key, "syncing")
        worker = threading.Thread(target=_push_worker, args=(key,),
                                  name=f"watchlist-push-{key}", daemon=True)
        queue["thread"] = worker
    worker.start()


def _push_worker(repo_path: str) -> None:
    """Loop commit: ambil job terbaru → ``_github_push`` → bersihkan jurnal."""
    while True:
        with _PUSH_LOCK:
            queue = _PUSH_QUEUES.get(repo_path) or {}
            job = queue.get("job")
            queue["job"] = None
            if job is None:
                queue["running"] = False
                return
        if PUSH_DEBOUNCE_SEC > 0:
            # Tunggu sebentar supaya rentetan klik (hapus 2 token cepat)
            # ter-bitih jadi satu commit; state terbaru yang menang.
            time.sleep(PUSH_DEBOUNCE_SEC)
            with _PUSH_LOCK:
                queue = _PUSH_QUEUES.get(repo_path) or {}
                if queue.get("job") is not None:
                    continue   # job lebih baru sudah masuk: lewati yang ini
        wl, action, pending_path = job
        try:
            ok = _github_push(wl, action, repo_path=repo_path,
                              pending_path=pending_path)
        except Exception as exc:  # jangan pernah membahayakan proses UI
            print(f"WARN: background _github_push raised: {exc} "
                  f"repo_path={repo_path} action={action}", file=sys.stderr)
            ok = False
            _set_last_error(f"background push error: {exc}", status=None)
        if ok:
            try:
                # Push sukses: remote kini mencerminkan ``wl`` yang kita commit.
                # Prune jurnal terhadap ``wl`` — bukan cache — supaya benar meski
                # ``_github_push`` di-stub (yang tidak menulis cache) dan tetap
                # aman bila mutation lain men-seed cache kembali saat push jalan:
                # op yang belum dicerminkan ``wl`` (mis. operasi yang masuk
                # belakangan lewat coalescing) tidak ikut terhapus.
                with _JOURNAL_LOCK:
                    pending = _load_pending(pending_path)
                    if pending:
                        still = _prune_pending(pending, wl)
                        if still != pending:
                            _save_pending(still, pending_path)
            except Exception as exc:
                print(f"WARN: background pending prune failed: {exc}",
                      file=sys.stderr)
            _set_push_result(repo_path, "ok")
        else:
            _set_push_result(repo_path, "error",
                             str(_LAST_PUSH_ERROR.get("msg") or ""))
            print(f"WARN: background push failed repo_path={repo_path} "
                  f"action={action} — jurnal pending dipertahankan",
                  file=sys.stderr)


def _fetch_raw_remote(force_refresh: bool = False,
                      repo_path: str | None = None) -> dict | None:
    """Fetch raw remote with TTL cache, returning a copy or None.

    ``repo_path`` isolates the Robinhood watchlist from the default
    Solana watchlist while still sharing the short TTL cache. The cache is
    keyed by file path so separate networks never shadow each other.
    """
    repo_path = str(repo_path or "watchlist.json").strip().lstrip("/")
    now = time.time()
    cached = _REMOTE_CACHE.get(repo_path) or {}
    if not force_refresh and cached.get("data") is not None \
            and (now - float(cached.get("ts") or 0.0)) < _CACHE_TTL:
        try:
            return dict(cached["data"])
        except Exception:
            return cached["data"]

    remote = _github_pull(repo_path)
    if remote is not None:
        if not isinstance(remote, dict):
            print(f"WARN: _fetch_raw_remote got non-dict {type(remote)}, coercing to {{}}", file=sys.stderr)
            remote = {}
        # Pull = isi repo langsung -> settled=True.
        _set_remote_cache(repo_path, remote, settled=True)
        try:
            return dict(remote)
        except Exception:
            return remote

    # fallback to stale cache if pull failed
    if cached.get("data") is not None:
        age = now - float(cached.get("ts") or 0.0)
        print(f"WARN: _github_pull returned None, using stale cache age {age:.0f}s", file=sys.stderr)
        try:
            return dict(cached["data"])
        except Exception:
            return cached["data"]
    return None


def _load_and_merge(force_refresh: bool = False,
                    repo_path: str | None = None,
                    local_path: str | None = None,
                    pending_path: str | None = None,
                    local_first: bool = False) -> dict:
    """Load raw remote + pending journal merged, without pushing.

    This is the non-pushing core used by add/remove to avoid double-push.
    ``repo_path``/``local_path``/``pending_path`` default to the Solana
    watchlist files; the Robinhood watchlist passes its own trio.

    ``local_first=True`` (dipakai jalur mutation di UI) sama sekali tidak
    menyentuh jaringan: state = cache remote (umurnya selalu hasil tulis/push
    terbaru) atau file lokal, lalu journal di atasnya. :func:`_github_push`
    tetap membaca remote terbaru sebelum commit, jadi tidak ada lost-update.
    """
    repo_path = str(repo_path or "watchlist.json").strip().lstrip("/")
    local_path = str(local_path or WATCHLIST_PATH)
    pending_path = str(pending_path or PENDING_PATH)
    if local_first:
        cached = _REMOTE_CACHE.get(repo_path) or {}
        raw = cached.get("data") if isinstance(cached.get("data"), dict) else None
        if raw is None:
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f) or {}
                    raw = loaded if isinstance(loaded, dict) else {}
            except Exception:
                raw = {}
        raw = dict(raw)
    else:
        raw = _fetch_raw_remote(force_refresh=force_refresh, repo_path=repo_path)
    if raw is None:
        # offline fallback to local file
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                loaded = json.load(f) or {}
                raw = loaded if isinstance(loaded, dict) else {}
        except Exception:
            raw = {}

    if not isinstance(raw, dict):
        print(f"WARN: raw watchlist not dict type={type(raw)}, resetting", file=sys.stderr)
        raw = {}

    with _JOURNAL_LOCK:
        pending = _load_pending(pending_path)
        if pending:
            settled = bool((_REMOTE_CACHE.get(repo_path) or {}).get("settled"))
            # Jurnal hanya boleh di-prune terhadap state yang **benar-benar**
            # mencerminkan repo (``settled=True``). State optimis (seed dari
            # jalur UI, ``settled=False``) atau local file bukan bukti remote
            # menerima op — mem-prune di sini menghapus jurnal sebelum push
            # berhasil, sehingga token yang dihapus muncul lagi di render
            # berikutnya saat cache kedaluwarsa dan server menarik ulang GitHub.
            if not local_first and settled:
                still = _prune_pending(pending, raw)
                if still != pending:
                    _save_pending(still, pending_path)
                    pending = still
            if pending:
                raw = _apply_ops(raw, pending)
    return raw


def load_watchlist(force_refresh: bool = False,
                   repo_path: str | None = None,
                   local_path: str | None = None,
                   pending_path: str | None = None) -> dict:
    """Merge: repo copy (durable truth) + pending journal (recent local ops).

    Pending ops always win; they are dropped only once the repo reflects them.
    An add/remove therefore never visually reverts.

    Uses a short TTL cache to avoid hammering GitHub on every Streamlit rerun.
    ``repo_path``/``local_path``/``pending_path`` default to the Solana
    watchlist files; the Robinhood watchlist passes its own trio.
    """
    repo_path = str(repo_path or "watchlist.json").strip().lstrip("/")
    local_path = str(local_path or WATCHLIST_PATH)
    pending_path = str(pending_path or PENDING_PATH)
    merged = _load_and_merge(force_refresh=force_refresh, repo_path=repo_path,
                             local_path=local_path, pending_path=pending_path)
    pending = _load_pending(pending_path)
    if pending:
        # opportunistic flush: commit the merged state *di latar belakang*.
        #
        # Dulu flush ini sinkron (``_github_push`` langsung) — saat push
        # gagal, jurnal dipertahankan lalu **setiap** render ulang mencoba
        # push sinkron lagi (GET+PUT ×3 percobaan, bisa ±2 menit) dan UI
        # membeku. Sekarang diserahkan ke thread latar (fire-and-forget):
        # UI tidak menunggu, jurnal dibersihkan oleh worker setelah commit
        # sukses (lihat :func:`_push_worker`).
        if _github_token():
            if push_inflight(repo_path):
                print(f"INFO: load_watchlist skip flush — push {repo_path} "
                      "masih berjalan di latar belakang", file=sys.stderr)
            else:
                _queue_github_push(merged, "sync pending ops",
                                   repo_path=repo_path,
                                   pending_path=pending_path)
    try:
        atomic_write_json(local_path, merged, indent=1)
    except Exception as exc:
        print(f"WARN: failed to save {local_path}: {exc}", file=sys.stderr)
    return merged


def save_watchlist(wl: dict, action: str = "update",
                   repo_path: str | None = None,
                   local_path: str | None = None,
                   pending_path: str | None = None,
                   background: bool = False) -> bool:
    """Write locally AND commit to GitHub. Returns True if committed.

    ``background=True`` (jalur UI): tulis lokal + seed cache + serahkan commit
    ke thread latar → return ``True`` segera (perubahan sudah durable di file
    lokal & journal; sukses/gagal GitHub dibaca lewat :func:`push_status`).
    Commit model ini tetap memakai seluruh mekanisme merge-retry
    :func:`_github_push`, hanya tidak menunggu.
    """
    repo_path = str(repo_path or "watchlist.json").strip().lstrip("/")
    local_path = str(local_path or WATCHLIST_PATH)
    pending_path = str(pending_path or PENDING_PATH)
    try:
        atomic_write_json(local_path, wl, indent=1)
    except Exception as exc:
        print(f"WARN: failed to save {local_path}: {exc}", file=sys.stderr)

    if background:
        _seed_remote_cache(repo_path, wl)
        _queue_github_push(wl, action, repo_path=repo_path,
                           pending_path=pending_path)
        return True

    success = _github_push(wl, action, repo_path=repo_path,
                           pending_path=pending_path)
    if success:
        with _JOURNAL_LOCK:
            pending = _load_pending(pending_path)
            if pending:
                still = _prune_pending(pending, wl)
                if still != pending:
                    _save_pending(still, pending_path)
    else:
        print(f"WARN: save_watchlist push failed action={action}, pending journal kept", file=sys.stderr)
    return success


def _journal(op: dict, pending_path: str | None = None) -> None:
    """Append an op to the pending journal; an add cancels earlier removes
    for the same CA and vice versa (last op wins)."""
    _journal_many([op], pending_path=pending_path)


def _journal_many(ops: list[dict], pending_path: str | None = None) -> None:
    """Journal multiple operations with one atomic write (last op wins)."""
    if not ops:
        return
    with _JOURNAL_LOCK:
        _journal_many_locked(ops, pending_path)


def _journal_many_locked(ops: list[dict], pending_path: str | None = None) -> None:
    target_pending = pending_path or PENDING_PATH
    incoming: dict[str, dict] = {}
    for op in ops:
        key = address_key(op.get("ca"))
        if key:
            incoming[key] = op
    pending = []
    for op in _load_pending(target_pending):
        key = address_key(op.get("ca"))
        if key not in incoming:
            pending.append(op)
            continue
        # "source" (pindah card) yang menyusul "add" belum ter-commit: lebur
        # ke op add supaya entri baru tidak hilang saat journal diputar ulang.
        if op.get("op") == "add" and incoming[key].get("op") == "source":
            incoming[key] = {**op, "source": incoming[key].get("source")}
    pending.extend(incoming.values())
    if pending_path is None:
        _save_pending(pending)
    else:
        _save_pending(pending, pending_path)


def fetch_token_symbol(ca: str, *, chain_id: str | None = None) -> str:
    """Resolve ticker from DexScreener; return '?' if lookup fails.

    ``chain_id`` (mis. ``robinhood``) memfilter DexScreener supaya address
    EVM yang kebetulan juga muncul di jaringan lain tidak mengambil simbol
    dari jaringan salah.
    """
    try:
        from core import get_market
        market = get_market(ca, chain_id=chain_id) or {}
        symbol = str(market.get("symbol") or "").strip()
        if symbol and symbol != "?":
            return symbol
    except Exception as exc:
        print(f"WARN: fetch_token_symbol failed for {ca[:8]}: {exc}",
              file=sys.stderr)
    return "?"


def add_to_watchlist(ca: str, symbol: str = "?", note: str = "",
                     source: str = "", down_ath: float = None,
                     avg_cost: float = None,
                     repo_path: str | None = None,
                     local_path: str | None = None,
                     pending_path: str | None = None,
                     chain_id: str | None = None,
                     background: bool = False) -> bool:
    """Add *ca* to a watchlist file.

    *source* tracks where the token came from (``"trending"``,
    ``"hrhr"``, ``"manual"``).  LP Radar uses it to decide which
    card section to show a token in.

    *down_ath* (optional) is the % the current price is below the
    all-time high, captured when the token was added from a screener.
    The LP/Degen Radar cards show it as ATH context.

    *avg_cost* (optional) is GMGN's holder average-cost change % —
    how far the current price is above/below the average holder buy
    price. Cards show it as an "avg cost" stat.

    The path trio defaults to the Solana ``watchlist.json``; the
    Robinhood watchlist passes ``watchlist_robinhood.json`` so both
    networks can coexist without losing either journal.

    ``background=True`` (jalur UI): tidak ada pull GitHub sebelum menulis,
    commit + dispatch scan dijalankan di thread latar sehingga tombol
    "tambah token" langsung menampilkan barisnya.
    """
    ca = normalize_address(ca)
    if not ca:
        return False
    if not symbol or symbol == "?":
        # Symbol tidak diketahui (manual add / pindah card) → ambil dari
        # DexScreener supaya card tidak menampilkan "$?".
        symbol = fetch_token_symbol(ca, chain_id=chain_id)
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
    if pending_path is None:
        _journal({"op": "add", "ca": ca, **entry})
    else:
        _journal({"op": "add", "ca": ca, **entry}, pending_path=pending_path)
    # Flag the CA for the main app's auto-refresh sweep
    try:
        import streamlit as st
        pending = st.session_state.setdefault(
            "watchlist_auto_refresh_cas", set())
        pending.add(ca)
    except Exception:
        pass
    # use non-pushing loader to avoid double push
    wl = _load_and_merge(force_refresh=False, repo_path=repo_path,
                         local_path=local_path, pending_path=pending_path,
                         local_first=background)
    wl[ca] = {**entry, **(wl.get(ca) or {})}
    if symbol and symbol != "?":
        wl[ca]["symbol"] = symbol
    if source:
        wl[ca]["source"] = source
    if avg_cost is not None:
        wl[ca]["avg_cost"] = float(avg_cost)
    saved = save_watchlist(wl, f"add {symbol} ({ca[:8]}…)",
                           repo_path=repo_path, local_path=local_path,
                           pending_path=pending_path, background=background)
    # Ask Actions to pull the last 48h immediately (best-effort, non-blocking).
    if background:
        dispatch_scan_async()
    else:
        request_immediate_scan()
    return saved


def add_many_to_watchlist(rows, *, source: str = "",
                          repo_path: str | None = None,
                          local_path: str | None = None,
                          pending_path: str | None = None,
                          background: bool = False) -> dict:
    """Add unique scan rows in one local save/GitHub push.

    Each row must contain ``ca`` (``mint`` is accepted as a fallback) and may
    contain ``symbol``. Existing and input-duplicate addresses are not
    written again. The returned counters describe local durable intent; a
    failed remote push remains protected by the existing pending journal.
    """
    rows = list(rows or [])
    watchlist = dict(_load_and_merge(force_refresh=False, repo_path=repo_path,
                                     local_path=local_path,
                                     pending_path=pending_path,
                                     local_first=background) or {})
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
    if pending_path is None:
        _journal_many(operations)
    else:
        _journal_many(operations, pending_path=pending_path)
    try:
        import streamlit as st
        pending = st.session_state.setdefault("watchlist_auto_refresh_cas", set())
        pending.update(added_addresses)
    except Exception:
        pass

    label = f"add {len(added_addresses)} token dari {source or 'scanner'}"
    saved = save_watchlist(watchlist, label, repo_path=repo_path,
                           local_path=local_path, pending_path=pending_path,
                           background=background)
    if background:
        dispatch_scan_async()
    else:
        request_immediate_scan()
    return {
        "added": len(added_addresses), "skipped": skipped,
        "duplicates": duplicates, "invalid": invalid,
        "saved": bool(saved), "addresses": added_addresses,
    }


def dispatch_scan_async(*, min_gap_sec: float = 10.0) -> bool:
    """Dispatch workflow di thread latar (non-blocking) dengan rem anti-banjir.

    :func:`request_immediate_scan` adalah POST biasa yang best-effort: tidak
    ada hasilnya yang dibaca UI, jadi tidak perlu memblokir klik "tambah
    token". ``min_gap_sec`` menggabungkan rentetan tambah (mis. 5 token dari
    scanner) jadi satu dispatch — run ``scan_all`` toh memproses seluruh
    watchlist.
    """
    now = time.time()
    with _PUSH_LOCK:
        last = float(_SCAN_DISPATCH.get("ts") or 0.0)
        if now - last < max(0.0, float(min_gap_sec)):
            return False
        _SCAN_DISPATCH["ts"] = now
    threading.Thread(target=request_immediate_scan, daemon=True,
                     name="watchlist-scan-dispatch").start()
    return True


def request_immediate_scan() -> bool:
    """Dispatch the scanner workflow so a new CA is fetched within seconds.

    Input ``scan_all=true`` membuat run dispatch memakai ``--scope all
    --ignore-gap``: token yang baru ditambahkan (LP maupun biasa) di-scan
    segera tanpa menunggu slot 4 jam watchlist biasa dan tanpa gate run
    ganda (run cepat ±5 menit mungkin baru saja lewat).
    """
    tok = _github_token()
    if not tok:
        return False
    try:
        response = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/"
            f"daily-effort.yml/dispatches",
            headers={"Authorization": f"Bearer {tok}",
                     "Accept": "application/vnd.github+json"},
            json={"ref": "main", "inputs": {"scan_all": "true"}},
            timeout=15)
        if response.status_code in (201, 204):
            return True
        print(f"WARN: request_immediate_scan {response.status_code}: "
              f"{response.text[:200]}", file=sys.stderr)
    except Exception as exc:
        print(f"WARN: request_immediate_scan failed: {exc}", file=sys.stderr)
    return False


def remove_from_watchlist(ca: str, *, repo_path: str | None = None,
                          local_path: str | None = None,
                          pending_path: str | None = None,
                          background: bool = False) -> bool:
    """Hapus satu token dari watchlist.

    ``background=True`` dipakai tombol ✕ di UI: state dibaca dari cache/file
    lokal (tanpa pull GitHub), hasil penghapusan ditulis lokal + di-journal,
    dan commit ke GitHub jalan di thread latar — tabel langsung berubah tanpa
    membuat user menunggu round-trip API.
    """
    ca = normalize_address(ca)
    if not ca:
        return False
    if pending_path is None:
        _journal({"op": "remove", "ca": ca})
    else:
        _journal({"op": "remove", "ca": ca}, pending_path=pending_path)
    meta = (_local_entry(ca, repo_path=repo_path, local_path=local_path)
            if background else {})
    wl = _load_and_merge(force_refresh=False, repo_path=repo_path,
                         local_path=local_path, pending_path=pending_path,
                         local_first=background)
    meta = wl.pop(ca, None) or meta
    return save_watchlist(wl, f"remove {meta.get('symbol', '?')} "
                              f"({ca[:8]}…)",
                          repo_path=repo_path, local_path=local_path,
                          pending_path=pending_path, background=background)


def remove_many_from_watchlist(cas, *, note: str = "",
                               repo_path: str | None = None,
                               local_path: str | None = None,
                               pending_path: str | None = None,
                               background: bool = False) -> dict:
    """Hapus banyak token sekaligus: satu tulis journal + satu commit.

    Dipakai tombol **🗑️ Hapus semua** di card watchlist biasa (``app.py``).
    Scope ditentukan **pemanggil** lewat daftar *cas* — fungsi ini tidak
    menyaring ``source`` (sama seperti :func:`remove_from_watchlist`), jadi
    UI-lah yang memastikan hanya token watchlist biasa yang dikirim, bukan
    Chart LP Meteora / Robinhood.

    Semantik durabilitas identik dengan hapus satu token, hanya di-batch:
    journal ``remove`` per CA ditulis **lebih dulu** dalam satu tulis atomik
    (:func:`_journal_many`), lalu file lokal, lalu **satu** commit GitHub
    (``background=True`` = thread latar) — bukan N journal write + N commit
    seperti kalau ✕ diklik N kali. Urutan load → journal → save mengikuti
    :func:`add_many_to_watchlist`: state dibaca sebelum journal supaya
    jumlah yang benar-benar terhapus bisa dihitung (setelah journal, op
    ``remove`` sudah diterapkan ke state gabungan).

    *note* (opsional) ditempel ke pesan commit, mis. ``"watchlist biasa"``.

    Mengembalikan ``{"removed", "missing", "saved", "addresses"}``:
    ``removed`` = CA yang memang ada di state dan dihapus; ``missing`` = CA
    valid yang tidak ditemukan — tetap di-journal supaya remote yang lebih
    baru daripada state lokal ikut dibersihkan (``_op_is_applied`` akan
    mem-prune op itu bila token memang sudah tidak ada). ``saved`` ``None``
    berarti tidak ada CA valid sehingga tidak ada yang ditulis.
    """
    seen: set[str] = set()
    targets: list[str] = []
    for raw in (cas or []):
        ca = normalize_address(raw)
        if not ca or ca in seen:
            continue
        seen.add(ca)
        targets.append(ca)
    if not targets:
        return {"removed": 0, "missing": 0, "saved": None, "addresses": []}

    wl = dict(_load_and_merge(force_refresh=False, repo_path=repo_path,
                              local_path=local_path,
                              pending_path=pending_path,
                              local_first=background) or {})
    removed = [ca for ca in targets if wl.pop(ca, None) is not None]

    # Journal SEBELUM tulis lokal/jaringan (kontrak durabilitas watchlist):
    # satu tulis atomik untuk semua op, last-op-wins per CA membatalkan
    # ``add`` yang masih tertunda untuk address yang sama.
    ops = [{"op": "remove", "ca": ca} for ca in targets]
    if pending_path is None:
        _journal_many(ops)
    else:
        _journal_many(ops, pending_path=pending_path)

    action = f"remove {len(removed)} token"
    if note:
        action += f" ({note})"
    saved = save_watchlist(wl, action, repo_path=repo_path,
                           local_path=local_path, pending_path=pending_path,
                           background=background)
    return {"removed": len(removed), "missing": len(targets) - len(removed),
            "saved": bool(saved), "addresses": removed}


def set_watchlist_source(ca: str, source: str, *,
                         repo_path: str | None = None,
                         local_path: str | None = None,
                         pending_path: str | None = None,
                         background: bool = False) -> bool:
    """Pindahkan token antar card watchlist dengan mengubah ``source``.

    ``source="meteora"`` → masuk card **Chart LP** (watchlist Meteora di
    bagian atas dashboard); ``source="manual"`` → kembali ke watchlist
    holder biasa. Entri yang belum ada di watchlist tidak dibuat.

    ``background=True`` = sama seperti tambah/hapus: state dibaca lokal,
    commit ke GitHub di thread latar (tombol 📋/⚡ di baris tidak menunggu).
    """
    ca = normalize_address(ca)
    source = str(source or "").strip().lower()
    if not ca or not source:
        return False
    wl = _load_and_merge(force_refresh=False, repo_path=repo_path,
                         local_path=local_path, pending_path=pending_path,
                         local_first=background)
    entry = wl.get(ca)
    if not isinstance(entry, dict):
        # Tidak membuat entri baru: hanya token yang sudah ada yang dipindah.
        return False
    if str(entry.get("source") or "").strip().lower() == source:
        return True
    if pending_path is None:
        _journal({"op": "source", "ca": ca, "source": source})
    else:
        _journal({"op": "source", "ca": ca, "source": source},
                 pending_path=pending_path)
    wl[ca] = {**entry, "source": source}
    symbol = entry.get("symbol") or "?"
    return save_watchlist(wl, f"move {symbol} ({ca[:8]}…) → {source}",
                          repo_path=repo_path, local_path=local_path,
                          pending_path=pending_path, background=background)


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
