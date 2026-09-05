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
# Backup store penuh (holder_history.json) dipublish ke ref yang sama dalam
# bentuk gzip: isinya 10x lebih kecil daripada JSON dan memuat peta wallet
# (alert state, kohort, kronologi, baseline scan FULL) yang sengaja TIDAK
# dikirim lagi di holder_status.json.
HISTORY_REPO_PATH = "holder_history.json.gz"

_CACHE_TTL = 15
# Cache per repo path (Solana ``holder_status.json`` vs Robinhood
# ``holder_status_robinhood.json``) supaya kedua jaringan tidak saling
# menimpa dalam satu proses.
_CACHE: dict[str, dict] = {}

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
    holders.pop("wallet_snapshot", None)
    holders.pop("chrono_snapshot", None)
    mid = holders.get("mid")
    if isinstance(mid, dict):
        holders["mid"] = {
            "count": mid.get("count"),
            "value_usd": mid.get("value_usd"),
            "pct_mc": mid.get("pct_mc"),
        }
    return holders


# Kunci ``st.session_state`` untuk hasil scan manual halaman Holder Analytic.
MANUAL_SCAN_KEY = "holder_manual_scan"


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def compact_manual_scan(mint: str, analysis: dict | None,
                        saved_at: int | None = None) -> dict:
    """Payload ringkas scan manual untuk ``st.session_state[MANUAL_SCAN_KEY]``.

    Hanya bagian yang dibutuhkan kartu metrik UI (holders ringkas, harga,
    marketcap, waktu). Peta wallet / snapshot alert / kronologi yang berat
    dibuang lewat :func:`_holders_for_status` supaya session state tidak
    membengkak.
    """
    analysis = analysis if isinstance(analysis, dict) else {}
    holders = analysis.get("holders")
    return {
        "mint": str(mint or ""),
        "saved_at": _as_int(saved_at) or int(time.time()),
        "analysis": {
            "symbol": analysis.get("symbol"),
            "marketcap": analysis.get("marketcap"),
            "price": analysis.get("price"),
            "analyzed_at": analysis.get("analyzed_at"),
            "holders": _holders_for_status(
                holders if isinstance(holders, dict) else {}),
        },
    }


def resolve_token_view(status_token: dict | None,
                       manual_scan: dict | None = None,
                       mint: str | None = None) -> dict:
    """Gabungkan snapshot terpublikasi dengan scan manual yang lebih baru.

    Halaman Holder Analytic menulis hasil scan manual ke
    ``holder_history.json`` (``ingest_many``) tetapi **tidak** mempublish
    ``holder_status.json`` — publish hanya dilakukan cron/scan watchlist, dan
    :func:`snapshot_status` membangun ``tokens`` dari analyses yang diberikan
    saja (tidak merge), jadi publish satu token akan menghapus token lain dari
    dashboard. Akibatnya kartu metrik (Dust hold % MC, badge, jumlah wallet)
    tetap menampilkan angka cron terakhir sementara grafik sudah memuat titik
    scan manual: dua angka berbeda untuk satu token. Selisihnya bisa besar
    bila harga bergerak cepat, karena cutoff dust **$10 per wallet dalam USD**
    membuat klasifikasi wallet bergantung harga (harga naik → wallet "lulus"
    ke >$10 → dust % MC turun walau tidak ada yang jual).

    Scan manual dipakai hanya bila ``analyzed_at``-nya tidak lebih tua dari
    snapshot dan ``holders``-nya terisi; selain itu snapshot yang menang.
    Return dict snapshot (atau ``{}``) dengan ``holders``/``price``/
    ``marketcap``/``symbol``/``analyzed_at`` dari sumber terbaru, plus
    ``view_source`` = ``"manual"`` atau ``"snapshot"``. ``history``,
    ``cohort``, ``alert_state``, dan ``chronology`` selalu dari snapshot.
    """
    token = dict(status_token) if isinstance(status_token, dict) else {}
    token.setdefault("view_source", "snapshot")
    scan = manual_scan if isinstance(manual_scan, dict) else {}
    if not scan:
        return token
    if mint is not None and str(scan.get("mint") or "") != str(mint or ""):
        return token
    if str(scan.get("mint") or "") and str(token.get("mint") or "") \
            and str(scan.get("mint")) != str(token.get("mint")):
        return token
    analysis = scan.get("analysis")
    if not isinstance(analysis, dict):
        return token
    holders = analysis.get("holders")
    if not isinstance(holders, dict) or not holders:
        return token
    manual_ts = (_as_int(analysis.get("analyzed_at"))
                 or _as_int(scan.get("saved_at")))
    if manual_ts < _as_int(token.get("analyzed_at")):
        return token
    token["holders"] = holders
    for key in ("price", "marketcap", "symbol"):
        if analysis.get(key) is not None:
            token[key] = analysis[key]
    token["analyzed_at"] = analysis.get("analyzed_at") or scan.get("saved_at")
    token["view_source"] = "manual"
    return token


def apply_manual_scan(status: dict | None, manual_scan: dict | None) -> dict:
    """Status salinan dengan token hasil scan manual diganti view terbaru.

    Dipakai UI sebelum render: satu panggilan membuat kartu metrik, badge,
    watchlist, dan Chart LP membaca angka yang sama dengan grafik. Tidak
    menyentuh file ``holder_status.json`` maupun cache publish.
    """
    status = dict(status) if isinstance(status, dict) else {}
    scan = manual_scan if isinstance(manual_scan, dict) else {}
    mint = str(scan.get("mint") or "")
    if not mint:
        return status
    tokens = dict(status.get("tokens") or {})
    view = resolve_token_view(tokens.get(mint) or {}, scan, mint=mint)
    if view.get("view_source") != "manual":
        return status
    tokens[mint] = view
    status["tokens"] = tokens
    return status


def _cohort_for_status(cohort: dict | None) -> dict:
    """Ringkasan kohort beku tanpa peta balance (10,6% byte snapshot).

    Dashboard cukup tahu kapan kohort dibekukan dan berapa address yang
    dipantau; balance per address dipakai ``holder_history`` untuk mengukur
    sisa token dan ikut terbackup di store durable.
    """
    cohort = cohort if isinstance(cohort, dict) else {}
    balances = cohort.get("balances")
    return {
        "summary": True,
        "frozen_at": cohort.get("frozen_at"),
        "wallets": len(balances) if isinstance(balances, dict) else 0,
    }


def _chronology_for_status(packed: dict | None) -> dict:
    """Kronologi untuk dashboard: interval + metrik, peta wallet jadi jumlah.

    ``holder_chronology.compact_chronology_for_status`` masih membawa sampai
    ``STATUS_MAX_WALLETS`` (200) entri per snapshot wallet; yang ditampilkan
    UI hanyalah interval/pergerakan, jadi peta itu diganti jumlahnya. Snapshot
    format lama (peta penuh) tetap bisa dipulihkan ``seed_from_status``.
    """
    packed = dict(packed) if isinstance(packed, dict) else {}
    packed.setdefault("intervals", [])
    for key in ("baseline_wallets", "latest_wallets"):
        snap = packed.get(key)
        if not isinstance(snap, dict):
            continue
        snap = dict(snap)
        wallets = snap.get("wallets")
        snap["wallets"] = len(wallets) if isinstance(wallets, dict) else 0
        packed[key] = snap
    return packed


def snapshot_status(analyses: dict | None,
                    watchlist: dict | None = None,
                    history_store: dict | None = None,
                    contexts: dict | None = None,
                    merge_status: dict | None = None) -> dict:
    """Bangun payload dashboard dari hasil analisis per token.

    ``contexts`` = ``{mint: market_context}`` dari ``alert_context`` (opsional).
    Bila ada, metrik volatilitas + volume 4 jam disimpan **berdampingan dengan
    dust % MC** sebagai ``tokens[mint]["market_signal"]`` supaya jejak
    konfirmasi alert ikut terdokumentasi di snapshot.

    ``merge_status`` = snapshot publish sebelumnya. Dipakai cron sejak
    cadens dua tingkat (2026-09-05): run cepat ±15 menit hanya meng-analisis
    watchlist LP, jadi token watchlist biasa **diwariskikan** dari snapshot
    lama (kunci di luar watchlist saat ini dibuang supaya token yang
    dihapus tidak menggantung) alih-alih hilang dari dashboard sampai run
    4 jam berikutnya. Token yang ikut dianalisis selalu menimpa warisan.

    Payload ini untuk **tampilan dashboard**, jadi peta wallet tidak ikut:
    ``cohort`` dan ``alert_state`` diringkas jadi jumlah + timestamp
    (terukur 94% byte snapshot: 2,22 MB -> ±133 KB untuk 36 token) dan peta
    kronologi diganti jumlahnya. State penuh (balance per address, baseline
    scan FULL, interval kronologi) dibackup terpisah oleh
    ``holder_history.publish_holder_history`` ke ``holder_history.json.gz`` di
    ref yang sama. Snapshot format lama yang masih membawa peta tetap bisa
    dipulihkan ke store oleh ``holder_history.seed_from_status``.
    """
    try:
        from holder_history import (compact_chronology_for_status,
                                    compact_history_for_status,
                                    load_holder_history)
        from telegram_alerts import alert_state_summary
        store = history_store if history_store is not None \
            else load_holder_history()
    except Exception:
        store = {"tokens": {}}
        compact_history_for_status = lambda *_a, **_k: []  # noqa: E731
        compact_chronology_for_status = lambda *_a, **_k: {}  # noqa: E731
        alert_state_summary = lambda *_a, **_k: {"summary": True}  # noqa: E731
    try:
        from alert_context import compact_signal
    except Exception:  # noqa: BLE001 - konteks pasar bersifat pelengkap
        compact_signal = lambda *_a, **_k: {}  # noqa: E731
    signals = contexts if isinstance(contexts, dict) else {}
    allowed = {str(key) for key in (watchlist or {})} if watchlist else set()
    tokens: dict = {}
    stamps = []
    if isinstance(merge_status, dict):
        for mint, token in (merge_status.get("tokens") or {}).items():
            if not mint or mint in (analyses or {}):
                continue
            if not isinstance(token, dict):
                continue
            # Token yang sudah keluar watchlist tidak dipertahankan.
            if allowed and str(mint) not in allowed:
                continue
            tokens[mint] = token
            if token.get("analyzed_at"):
                try:
                    stamps.append(int(token["analyzed_at"]))
                except (TypeError, ValueError):
                    pass
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
            # Peta wallet (kohort, alert state, kronologi) TIDAK ikut snapshot:
            # 94% byte payload dashboard dan hanya dibutuhkan perhitungan
            # internal. Semuanya terbackup penuh di holder_history.json.gz
            # (ref holder-live) lewat publish_holder_history().
            "cohort": _cohort_for_status(hist_slot.get("cohort")),
            "alert_state": alert_state_summary(hist_slot.get("alert_state")
                                               or {}),
            "chronology": _chronology_for_status(
                compact_chronology_for_status(store, mint)),
        }
        context = signals.get(mint)
        if not isinstance(context, dict):
            context = result.get("market_context")
        if isinstance(context, dict):
            token["market_signal"] = compact_signal(context)
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


def _contents_url(ref: str | None = None,
                  repo_path: str = STATUS_REPO_PATH) -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}"
    return f"{url}?ref={ref}" if ref else url


def _github_get_bytes(repo_path: str = STATUS_REPO_PATH) -> bytes | None:
    """Ambil satu file mentah dari ref ``holder-live`` -> ``main`` -> CDN raw.

    ``Accept: application/vnd.github.raw+json`` wajib untuk file > 1 MB
    (endpoint contents biasa menolak blob besar); CDN raw jadi jaring terakhir
    bila API gagal/limit. Return ``None`` bila semua sumber gagal.
    """
    tok = _github_token()
    headers = {"Accept": "application/vnd.github.raw+json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    for ref in (STATUS_REF, "main"):
        try:
            response = requests.get(_contents_url(ref, repo_path),
                                    headers=headers, timeout=20)
        except requests.RequestException as exc:
            print(f"WARN: {repo_path} API {ref} network error: {exc}",
                  file=sys.stderr)
            continue
        if response.status_code != 200:
            if response.status_code != 404:
                print(f"WARN: {repo_path} API {ref} {response.status_code}: "
                      f"{response.text[:200]}", file=sys.stderr)
            continue
        body = response.content
        if body:
            return body
    try:
        raw = (f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
               f"{STATUS_REF}/{repo_path}")
        response = requests.get(raw, params={"t": int(time.time())},
                                headers={"Cache-Control": "no-cache",
                                         "Pragma": "no-cache"}, timeout=20)
        if response.status_code == 200 and response.content:
            return response.content
    except requests.RequestException as exc:
        print(f"WARN: {repo_path} raw CDN failed: {exc}", file=sys.stderr)
    return None


def _github_pull(repo_path: str | None = None) -> dict | None:
    """Muat file status dari GitHub (durable) sebagai dict.

    ``repo_path`` default ``holder_status.json``; Robinhood memakai
    ``holder_status_robinhood.json`` supaya status kedua jaringan tidak
    tercampur.
    """
    repo_path = str(repo_path or STATUS_REPO_PATH).strip().lstrip("/")
    body = _github_get_bytes(repo_path)
    if body is None:
        return None
    try:
        return _parse_status_payload(json.loads(body.decode("utf-8")))
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        print(f"WARN: holder_status API parse failed: {exc}", file=sys.stderr)
        return None


def pull_store_backup(repo_path: str | None = None) -> bytes | None:
    """Bytes mentah backup store (gzip) dari ref durable; ``None`` bila gagal.

    ``repo_path`` default ``holder_history.json.gz``; Robinhood memakai
    ``holder_history_robinhood.json.gz``.
    """
    repo_path = str(repo_path or HISTORY_REPO_PATH).strip().lstrip("/")
    return _github_get_bytes(repo_path)


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


def _github_put_bytes(repo_path: str, payload: bytes, message: str,
                      max_retries: int = 4) -> bool:
    """Tulis satu file (bytes) ke ref ``holder-live`` lewat Contents API.

    Retry dengan backoff untuk 409/422/429/5xx (422 "sha wasn't supplied"
    terjadi sesaat setelah branch dibuat dari ``main``). Bila ref tidak bisa
    disiapkan, jatuh ke ``main`` supaya data tidak hilang.
    """
    tok = _github_token()
    if not tok:
        print(f"WARN: {repo_path} push skipped (no github_token)",
              file=sys.stderr)
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}"
    headers = {"Authorization": f"Bearer {tok}",
               "Accept": "application/vnd.github+json"}
    target_ref = STATUS_REF if _ensure_status_branch(headers) else "main"
    if target_ref == "main":
        print(f"WARN: {repo_path} falling back to main", file=sys.stderr)
    body_content = base64.b64encode(payload).decode()
    for attempt in range(1, max_retries + 1):
        try:
            current = requests.get(_contents_url(target_ref, repo_path),
                                   headers=headers, timeout=20)
        except requests.RequestException as exc:
            print(f"WARN: {repo_path} GET failed: {exc}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        sha = None
        if current.status_code == 200:
            try:
                sha = (current.json() or {}).get("sha")
            except Exception:  # noqa: BLE001 - sha opsional (file baru)
                sha = None
        elif current.status_code != 404:
            if current.status_code in (401, 403):
                print(f"ERROR: {repo_path} GET auth {current.status_code}",
                      file=sys.stderr)
                return False
            if attempt < max_retries and (current.status_code in (409, 429)
                                          or current.status_code >= 500):
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        payload_json = {"message": message, "content": body_content,
                        "branch": target_ref}
        if sha:
            payload_json["sha"] = sha
        try:
            put = requests.put(url, headers=headers, json=payload_json,
                               timeout=30)
        except requests.RequestException as exc:
            print(f"WARN: {repo_path} PUT failed: {exc}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return False
        if put.status_code in (200, 201):
            return True
        print(f"WARN: {repo_path} PUT {put.status_code}: {put.text[:200]}",
              file=sys.stderr)
        if put.status_code in (409, 422, 429) or put.status_code >= 500:
            if attempt < max_retries:
                time.sleep(1.0 * (2 ** (attempt - 1)))
                continue
        return False
    return False


def _github_push(status: dict, message: str, max_retries: int = 4,
                 repo_path: str | None = None) -> bool:
    """Publish file status (payload dashboard) ke ref durable."""
    repo_path = str(repo_path or STATUS_REPO_PATH).strip().lstrip("/")
    body = json.dumps(status, indent=2, sort_keys=True).encode("utf-8")
    return _github_put_bytes(repo_path, body, message,
                             max_retries=max_retries)


def push_store_backup(payload: bytes, message: str,
                      max_retries: int = 4,
                      repo_path: str | None = None) -> bool:
    """Publish backup store (gzip) ke ref durable; ``False`` bila gagal."""
    if not payload:
        return False
    repo_path = str(repo_path or HISTORY_REPO_PATH).strip().lstrip("/")
    return _github_put_bytes(repo_path, payload, message,
                             max_retries=max_retries)


def load_holder_status(force_refresh: bool = False,
                       repo_path: str | None = None,
                       local_path: str | None = None) -> dict:
    """Muat snapshot: GitHub (durable) → file lokal → kosong.

    ``repo_path``/``local_path`` default Solana; Robinhood memakai
    ``holder_status_robinhood.json``.
    """
    repo_path = str(repo_path or STATUS_REPO_PATH).strip().lstrip("/")
    local_path = str(local_path or STATUS_PATH)
    now = time.time()
    cached = _CACHE.get(repo_path) or {}
    if (not force_refresh and cached.get("data") is not None
            and (now - float(cached.get("ts") or 0.0)) < _CACHE_TTL):
        return dict(cached["data"])
    remote = _github_pull(repo_path)
    local = None
    try:
        with open(local_path, encoding="utf-8") as handle:
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
    _CACHE[repo_path] = {"data": dict(status), "ts": now}
    return dict(status)


def publish_holder_status(analyses: dict,
                          watchlist: dict | None = None,
                          *, push: bool = True,
                          history_store: dict | None = None,
                          contexts: dict | None = None,
                          merge_status: dict | None = None,
                          repo_path: str | None = None,
                          local_path: str | None = None) -> dict:
    """Tulis status lokal + (opsional) publish ke GitHub.

    ``merge_status`` (snapshot sebelumnya) mewariskan token yang tidak
    ikut dianalisis run ini — lihat :func:`snapshot_status`.
    ``repo_path``/``local_path`` default Solana; Robinhood memakai
    ``holder_status_robinhood.json``.
    """
    repo_path = str(repo_path or STATUS_REPO_PATH).strip().lstrip("/")
    local_path = str(local_path or STATUS_PATH)
    status = snapshot_status(analyses, watchlist, history_store=history_store,
                             contexts=contexts, merge_status=merge_status)
    atomic_write_json(local_path, status, indent=2)
    _CACHE[repo_path] = {"data": dict(status), "ts": time.time()}
    if push:
        stamp = status.get("updated_at") or int(time.time())
        if not _github_token():
            _LAST_PUBLISH["ok"] = False
            _LAST_PUBLISH["error"] = "no github_token"
        else:
            ok = _github_push(status,
                              f"holder-status: snapshot {stamp} [skip ci]",
                              repo_path=repo_path)
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
    _CACHE.clear()
