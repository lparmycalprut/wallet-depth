# -*- coding: utf-8 -*-
"""Shared configuration and market/trade fetch infrastructure."""
from datetime import datetime, timezone
import json
import math
import os
import re
import tempfile
import threading
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HELIUS_RPC_URL = "https://mainnet.helius-rpc.com/"
HELIUS_ENHANCED_URL = "https://api.helius.xyz"

_helius_rotation_lock = threading.Lock()
_helius_rotation_index = 0

# Pemakaian Helius lokal (panel 🧾 Log Aktivitas, 2026-09-10): berapa request
# yang **dibuat proses ini** lewat pool key di bawah. Helius menagih kredit per
# request, jadi angka ini pelengkap "sisa kredit" ketika Helius tidak mau
# mengirim angka kreditnya (plan tertentu tidak lapor).
_helius_call_lock = threading.Lock()
_helius_calls = 0


def atomic_write_json(path: str, data, **dump_kwargs) -> None:
    """Write JSON to path atomically: write to a temp file in the same
    directory, flush+fsync, then os.replace() over the target. Prevents
    truncated/corrupt files if the process dies mid-write."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


# Nilai placeholder yang hidup di config.example.json / template README. Kalau
# tidak disaring, key "PASTE-API-KEY-KAMU-DISINI" menang atas secrets asli
# (sumber pertama yang menang di pool) dan SEMUA request Helius — scan holder,
# watchlist, cron — gagal 401 padahal kuncinya sudah dipasang (bug nyata yang
# bikin sisa kredit terbaca tidak tersedia).
_KEY_PLACEHOLDER_RE = re.compile(
    r"(paste|your[-_ ]?api|your[-_ ]?key|dummy|example|changeme|replace|xxx+)",
    re.IGNORECASE)


def merge_helius_keys(*values) -> list[str]:
    """Normalize comma/newline-separated Helius keys and de-duplicate them.

    Values may be strings or iterables, which keeps this helper usable for
    config.json, environment variables, Streamlit secrets, and UI fields.
    The first occurrence wins so the configured primary key stays first.
    Placeholder teks (``PASTE-API-KEY-…``) dibuang supaya tidak menutupi key
    asli dari sumber lain.
    """
    keys = []

    def _add(value):
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _add(item)
            return
        for key in str(value or "").replace("\r", "\n").replace(
                "\n", ",").split(","):
            key = key.strip()
            if not key or _KEY_PLACEHOLDER_RE.search(key):
                continue
            if key not in keys:
                keys.append(key)

    for value in values:
        _add(value)
    return keys


def _config_file() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _streamlit_helius_keys() -> list[str]:
    try:
        import streamlit as st
        return merge_helius_keys(st.secrets.get("helius_api_key", ""),
                                 st.secrets.get("helius_extra_keys", ""))
    except Exception:
        return []


def get_helius_keys(*, primary=None, extras=None, config=None) -> list[str]:
    """Return one de-duplicated Helius key pool from every supported source.

    Explicit values (for example the live sidebar fields) come first, then an
    optional config mapping, Streamlit secrets, environment variables, and
    finally config.json.  Reading every source instead of overriding one source
    with another ensures extra keys are never silently dropped.

    Streamlit secrets didapung **di depan** config.json karena repo ini
    menyimpan ``config.json`` berisi placeholder (``"helius_api_key":
    "PASTE-API-KEY-KAMU-DISINI"``) yang di Streamlit Cloud ikut ter-bundle:
    sumber pertama yang menang akan memilih placeholder itu dan key asli dari
    secrets tidak pernah dipakai. Placeholder juga disaring di
    :func:`merge_helius_keys`, jadi key lama yang memang valid tetap menang
    atas config.json lokal.
    """
    passed = config or {}
    disk = _config_file()
    return merge_helius_keys(
        primary, extras,
        passed.get("helius_api_key"), passed.get("helius_extra_keys"),
        _streamlit_helius_keys(),
        os.environ.get("HELIUS_API_KEY"),
        os.environ.get("HELIUS_API_KEYS"),
        disk.get("helius_api_key"), disk.get("helius_extra_keys"),
    )


def get_holder_source(default: str = "auto") -> str:
    """Preferensi sumber holder: ``gmgn`` / ``helius`` / ``auto``.

    Dibaca dari config.json ``holder_source`` lalu env ``HOLDER_SOURCE``.
    ``auto`` = Helius dulu untuk watchlist, fallback GMGN. Nilai lama
    ``solscan`` (sudah dilepas) dianggap tidak valid → jatuh ke ``auto``.
    """
    value = str(default or "auto").strip().lower()
    try:
        cfg = str(_config_file().get("holder_source") or "").strip().lower()
        if cfg:
            value = cfg
    except Exception:
        pass
    env_value = str(os.environ.get("HOLDER_SOURCE") or "").strip().lower()
    if env_value:
        value = env_value
    if value not in ("gmgn", "helius", "auto"):
        value = "auto"
    return value


def _reset_helius_rotation() -> None:
    """Reset round-robin state (primarily useful for deterministic tests)."""
    global _helius_rotation_index
    with _helius_rotation_lock:
        _helius_rotation_index = 0


def _helius_candidates(helius_keys=None, max_attempts=None) -> list[str]:
    """Build a round-robin request order, including every configured key."""
    # Resolved tuples/lists are passed through every paginated flow; avoid
    # re-reading config.json and Streamlit secrets on every page.
    if isinstance(helius_keys, (list, tuple)):
        keys = merge_helius_keys(helius_keys)
    else:
        keys = get_helius_keys(primary=helius_keys)
    if not keys:
        raise RuntimeError("Helius API key missing")
    global _helius_rotation_index
    with _helius_rotation_lock:
        start = _helius_rotation_index % len(keys)
        _helius_rotation_index = (_helius_rotation_index + 1) % len(keys)
    attempts = max(len(keys), int(max_attempts or 0))
    return [keys[(start + offset) % len(keys)] for offset in range(attempts)]


def _transient_rpc_error(error) -> bool:
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    message = str(error.get("message") or error).lower()
    return (code in (408, 425, 429, -32429) or
            "rate limit" in message or "too many requests" in message or
            "temporarily unavailable" in message or
            "service unavailable" in message or "internal error" in message)


def _response_error(response, label: str):
    # Do not surface response.url: it contains the API key query parameter.
    return RuntimeError(f"{label} HTTP {response.status_code}")


def _count_helius_call() -> None:
    """Satu request Helius sukses lewat pool key modul ini."""
    global _helius_calls
    with _helius_call_lock:
        _helius_calls += 1


def helius_request_count() -> int:
    """Jumlah request Helius yang dibuat proses ini (estimasi pemakaian)."""
    with _helius_call_lock:
        return _helius_calls


def _reset_helius_request_count() -> None:
    """Zerokan counter (tes deterministik)."""
    global _helius_calls
    with _helius_call_lock:
        _helius_calls = 0


# ---------------------------------------------------------------------------
# Sisa kredit Helius — dipakai panel 🧾 Log Aktivitas (permintaan user
# 2026-09-10: "tampilkan juga berapa kredit tersisa dari helius key kita").
#
# Helius membebankan **kredit per request** dengan plafon bulanan per project
# (plan Free V3 = 1.000.000 kredit/bulan). Angka sisanya dibaca lewat
# metadata key, dua host yang sama-sama melayani ``/v0``:
#
#     GET https://api.helius.xyz/v0/keys?api-key=…
#     GET https://mainnet.helius-rpc.com/v0/keys?api-key=…
#
# Bentuk responsnya tidak dijamin sama antar plan/era API — ``credits`` bisa
# berupa objek ``{total, used, available}``, angka tunggal, atau field datar
# ``creditsRemaining`` — jadi :func:`parse_helius_credits` menerima semuanya
# dan mengembalikan ``None`` bila Helius memang tidak mengirim angka. Kalau
# begitu terjadi, panel log menampilkan **hitungan lokal** (berapa request yang
# app ini kirim ke Helius) alih-alih mengarang angka kredit.
# ---------------------------------------------------------------------------
HELIUS_RPC_ORIGIN = HELIUS_RPC_URL.rstrip("/")
HELIUS_USAGE_PATHS = ("/v0/keys",)
HELIUS_USAGE_TIMEOUT_SEC = 10.0
# Cache per proses: header app auto-refresh tiap ±60 dtk, jadi status key
# tidak boleh menembak Helius pada setiap render.
HELIUS_USAGE_TTL_SEC = 300.0
# Pemakaian di atas ambang ini → ⚠️ warn di log; sisa ≤ 0 → ❗ action
# (merah bold = perlu perubahan manual user: tambah kredit / rotasi key).
HELIUS_CREDIT_WARN_PCT = 90.0

_CREDITS_TOTAL = ("total", "total_credits", "totalCredits", "monthly_credits",
                  "monthlyCredits", "plan_credits", "planCredits",
                  "credits_total", "creditsTotal", "quota", "limit")
_CREDITS_USED = ("used", "used_credits", "usedCredits", "credits_used",
                 "creditsUsed", "consumed", "consumed_credits",
                 "consumedCredits", "usage")
_CREDITS_LEFT = ("available", "available_credits", "availableCredits",
                 "remaining", "remaining_credits", "remainingCredits",
                 "credits_remaining", "creditsRemaining", "credits_left",
                 "creditsLeft", "remaining_this_period")
_CREDITS_CONTAINERS = ("credits", "credit", "api_credits", "apiCredits",
                       "usage", "quota")

_helius_usage_lock = threading.Lock()
_helius_usage_cache: dict = {"keys": (), "ts": 0.0, "rows": []}
# Ada probe latar yang sedang jalan? (menjaga rerun Streamlit agar
# tidak menumpuk thread probe.)
_helius_usage_inflight = False


def _env_float(name: str, default: float) -> float:
    """``float`` dari env; nilai kosong/jelek → ``default``."""
    try:
        value = float(str(os.environ.get(name) or "").strip())
    except (TypeError, ValueError):
        return float(default)
    return value if value > 0 else float(default)


def _credit_number(value) -> int | None:
    """Int dari angka atau string angka (``"1,234"`` ikut); None bila jelek."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        return int(value)
    try:
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return None


def _pick_number(mapping: dict, names) -> int | None:
    """Ambil angka dari field pertama yang ada (bentuk respons beda-beda)."""
    for name in names:
        if name in mapping:
            value = _credit_number(mapping.get(name))
            if value is not None:
                return value
    return None


def parse_helius_credits(payload) -> tuple[int | None, int | None,
                                            int | None]:
    """``(total, used, remaining)`` dari bentuk respons Helius apa pun.

    Angka yang tidak dikirim Helius tetap ``None`` — jangan ditebak. List
    berarti beberapa key dalam satu project: plafon kredit dihitung di level
    project sehingga nilainya **tidak dijumlah** (akan berlipat) tapi diambil
    yang terbesar.
    """
    if payload is None or isinstance(payload, bool):
        return (None, None, None)
    if isinstance(payload, (int, float, str)):
        single = _credit_number(payload)
        if single is None:
            return (None, None, None)
        # Angka tunggal = laporan "sisa" (bentuk lama / field ``credits``
        # dashboard); tanpa total, persen pemakaian tidak dihitung.
        return (None, None, single)
    if isinstance(payload, list):
        merged: dict = {}
        for item in payload:
            triple = parse_helius_credits(item)
            for index, name in enumerate(("total", "used", "remaining")):
                value = triple[index]
                if value is None:
                    continue
                merged[name] = (value if name not in merged
                                else max(merged[name], value))
        return (merged.get("total"), merged.get("used"),
                merged.get("remaining"))
    if not isinstance(payload, dict):
        return (None, None, None)
    total = _pick_number(payload, _CREDITS_TOTAL)
    used = _pick_number(payload, _CREDITS_USED)
    remaining = _pick_number(payload, _CREDITS_LEFT)
    for name in _CREDITS_CONTAINERS:
        if name not in payload:
            continue
        sub = parse_helius_credits(payload.get(name))
        total = total if total is not None else sub[0]
        used = used if used is not None else sub[1]
        remaining = remaining if remaining is not None else sub[2]
    if remaining is None and total is not None and used is not None:
        remaining = max(0, total - used)
    return (total, used, remaining)


def _scrub_key_text(text) -> str:
    """Buang ``api-key=…`` dari pesan error — key tak pernah tampil."""
    return re.sub(r"api-key=[A-Za-z0-9_\.\-]+", "api-key=***",
                  str(text or ""))


def _helius_usage_rows(keys, *, timeout: float | None = None) -> list[dict]:
    """Probe metadata key Helius; satu baris status per key (tanpa exception)."""
    timeout = (HELIUS_USAGE_TIMEOUT_SEC if timeout is None else float(timeout))
    checked_at = int(time.time())
    rows: list[dict] = []
    for index, key in enumerate(keys):
        row = {"label": f"key#{index + 1}", "name": "", "status": "unknown",
               "total": None, "used": None, "remaining": None,
               "percent_used": None, "rate_limit": "", "permissions": "",
               "error": "", "checked_at": checked_at}
        payload = None
        for base in (HELIUS_ENHANCED_URL, HELIUS_RPC_ORIGIN):
            for path in HELIUS_USAGE_PATHS:
                try:
                    response = requests.get(f"{base}{path}",
                                            params={"api-key": key},
                                            timeout=timeout)
                except Exception as exc:  # noqa: BLE001 - jaringan/timeout
                    row["error"] = _scrub_key_text(
                        f"{type(exc).__name__}: {exc}")[:160]
                    continue
                status = int(getattr(response, "status_code", 0) or 0)
                if status in (401, 403):
                    # Key ditolak — bukan gangguan jaringan dan tidak pulih
                    # sendiri → perlu tindakan user (level action).
                    row["status"] = "rejected"
                    row["error"] = f"HTTP {status}"
                    break
                if status == 404:
                    continue      # host ini tidak melayani metadata key
                if status >= 400:
                    row["status"] = "unreachable"
                    row["error"] = f"HTTP {status}"
                    continue
                try:
                    payload = response.json()
                except Exception as exc:  # noqa: BLE001 - body bukan JSON
                    row["status"] = "unreachable"
                    row["error"] = (f"respons bukan JSON "
                                    f"({type(exc).__name__})")
                    continue
                break
            if payload is not None or row["status"] == "rejected":
                break
        if payload is None:
            if row["status"] == "unknown":
                row["status"] = "unreachable"
            rows.append(row)
            continue
        items = payload if isinstance(payload, list) else [payload]
        first = next((item for item in items if isinstance(item, dict)), {})
        row["name"] = str(first.get("name") or first.get("label") or "")[:40]
        row["permissions"] = str(first.get("permissions")
                                 or first.get("permission") or "")[:24]
        rate = first.get("rateLimit") or first.get("rate_limit") or {}
        if isinstance(rate, dict) and rate.get("max"):
            period = _positive_float(rate.get("period"), 1.0)
            try:
                row["rate_limit"] = f"{float(rate['max']) / period:g} rps"
            except (TypeError, ValueError, ZeroDivisionError):
                row["rate_limit"] = ""
        total, used, remaining = parse_helius_credits(payload)
        row["total"], row["used"], row["remaining"] = total, used, remaining
        if total:
            # _percent_used memilih `used` bila Helius mengirimnya, jika
            # tidak menghitungnya dari sisa.
            row["percent_used"] = _percent_used(total, used, remaining)
        if remaining is None and total is None and used is None:
            # Helius menjawab (key hidup) tapi plan ini tidak lapor kredit.
            row["status"] = "no_credit_data"
        else:
            row["status"] = "ok"
        rows.append(row)
    return rows


def _positive_float(value, default: float) -> float:
    """``float`` positif dari nilai apa pun; kosong/jelek/nol → ``default``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if number > 0 else float(default)


def _percent_used(total, used, remaining) -> float | None:
    """Persen pemakaian plafon; dari ``used`` bila ada, jika tidak dari sisa."""
    try:
        total_f = float(total)
    except (TypeError, ValueError):
        return None
    if total_f <= 0:
        return None
    if used is not None:
        return max(0.0, min(100.0, 100.0 * float(used) / total_f))
    if remaining is not None:
        return max(0.0, min(100.0,
                            100.0 * (total_f - float(remaining)) / total_f))
    return None


def _helius_probe_enabled() -> bool:
    """Kill-switch probe status key. Suite tes menyetel ``HELIUS_USAGE_PROBE=0``
    (lihat ``tests/__init__.py``) supaya tidak ada satu pun request keluar;
    tes transport mengaktifkannya lagi dengan ``mock.patch.dict`` sendiri."""
    return str(os.environ.get("HELIUS_USAGE_PROBE") or "1").strip() != "0"


def _helius_usage_cached(signature: tuple) -> tuple[list[dict], float]:
    """``(rows, umur_cache_detik)`` — baca cache saja, tanpa jaringan."""
    with _helius_usage_lock:
        rows = [dict(row) for row in _helius_usage_cache.get("rows") or []] \
            if _helius_usage_cache.get("keys") == signature else []
        ts = float(_helius_usage_cache.get("ts") or 0.0)
    return rows, (time.time() - ts if ts else None)


def helius_key_status(*, refresh: bool = False, keys=None,
                      timeout: float | None = None) -> list[dict]:
    """Status + sisa kredit tiap key Helius (cache ``HELIUS_USAGE_TTL_SEC``).

    **Menunggu jaringan** bila cache basi — dipakai cron/CLI/tes. UI memakai
    :func:`helius_usage_status` yang tidak pernah memblokir render.

    Tidak pernah menaikkan exception: panel log harus tetap tampil walau
    Helius mati. Kejadian yang butuh tindakan user (key ditolak, kredit habis,
    kredit menipis) ikut dicatat ke :mod:`activity_log`.
    """
    resolved = list(keys) if keys is not None else get_helius_keys()
    if not resolved:
        return []
    if not _helius_probe_enabled():
        return _helius_usage_cached(tuple(resolved))[0]
    ttl = _env_float("HELIUS_USAGE_TTL_SEC", HELIUS_USAGE_TTL_SEC)
    signature = tuple(resolved)
    now = time.time()
    if not refresh:
        rows, age = _helius_usage_cached(signature)
        if rows and age is not None and age < ttl:
            return rows
    try:
        rows = _helius_usage_rows(resolved, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - status key hanya pelengkap
        rows = [{"label": f"key#{index + 1}", "name": "", "status": "error",
                 "total": None, "used": None, "remaining": None,
                 "percent_used": None, "rate_limit": "", "permissions": "",
                 "error": _scrub_key_text(exc)[:160],
                 "checked_at": int(now)}
                for index in range(len(resolved))]
    with _helius_usage_lock:
        _helius_usage_cache.update({"keys": signature, "ts": time.time(),
                                    "rows": [dict(row) for row in rows]})
    _log_helius_usage(rows)
    return [dict(row) for row in rows]


def refresh_helius_usage_async(*, keys=None, timeout: float | None = None) \
        -> bool:
    """Satu thread latar untuk segarkan cache status key; ``False`` bila sudah
    ada yang jalan (rerun Streamlit tiap 60 dtk tidak menumpuk probe)."""
    global _helius_usage_inflight
    if not _helius_probe_enabled():
        return False
    resolved = list(keys) if keys is not None else get_helius_keys()
    if not resolved:
        return False
    with _helius_usage_lock:
        if _helius_usage_inflight:
            return False
        _helius_usage_inflight = True

    def _run():
        global _helius_usage_inflight
        try:
            helius_key_status(refresh=True, keys=resolved, timeout=timeout)
        except Exception:  # noqa: BLE001 - status key tidak boleh menjatuhkan
            pass
        finally:
            with _helius_usage_lock:
                _helius_usage_inflight = False

    threading.Thread(target=_run, name="helius-usage", daemon=True).start()
    return True


def helius_usage_status(*, background: bool = True) -> dict:
    """Ringkasan status key Helius untuk UI/CLI.

    ``background=True`` (default — dipakai panel 🧾 Log Aktivitas): **tidak**
    menunggu jaringan; cache yang ada langsung dipakai dan bila basi satu
    thread latar mengisinya (render halaman berikutnya sudah punya angka).
    ``background=False``: probe inline (cron / skrip CLI / tes).

    Return ``{"rows": […], "total_keys": n, "refreshing": bool,
    "cache_age_sec": float|None}``.
    """
    keys = get_helius_keys()
    if not keys:
        return {"rows": [], "total_keys": 0, "refreshing": False,
                "cache_age_sec": None}
    if not background:
        return {"rows": helius_key_status(keys=keys), "total_keys": len(keys),
                "refreshing": False, "cache_age_sec": 0.0}
    rows, age = _helius_usage_cached(tuple(keys))
    ttl = _env_float("HELIUS_USAGE_TTL_SEC", HELIUS_USAGE_TTL_SEC)
    stale = not rows or (age is None) or age >= ttl
    refreshing = refresh_helius_usage_async(keys=keys) if stale else False
    return {"rows": rows, "total_keys": len(keys), "refreshing": refreshing,
            "cache_age_sec": age}


def _log_helius_usage(rows: list[dict]) -> None:
    """Kredit habis / key ditolak → ❗ ``action``; menipis → ⚠️ warn."""
    try:
        import activity_log
    except Exception:  # noqa: BLE001 - cron/tes boleh tanpa modul log
        return
    for row in rows:
        label = str(row.get("label") or "key")
        status = str(row.get("status") or "")
        error = str(row.get("error") or "")[:120]
        if status == "rejected":
            activity_log.action(
                "helius",
                f"{label} ditolak Helius ({error or 'HTTP 401'}) — periksa / "
                "ganti `HELIUS_API_KEY` (config.json / env / Streamlit "
                "secrets); scan holder Solana tidak bisa jalan tanpa key "
                "yang valid", dedup_sec=1800.0)
        elif status in ("unreachable", "error"):
            activity_log.warn(
                "helius", f"sisa kredit {label} tidak bisa dibaca: "
                          f"{error or status}", dedup_sec=1800.0)
            continue
        remaining, total = row.get("remaining"), row.get("total")
        if remaining is not None and remaining <= 0:
            activity_log.action(
                "helius",
                f"{label} kredit Helius HABIS (0"
                + (f" / {int(total):,}" if total else "")
                + ") — scan holder Solana akan gagal; tunggu reset bulanan, "
                  "tambah kredit, atau taruh key lain di `HELIUS_API_KEYS`",
                dedup_sec=1800.0)
        elif (row.get("percent_used") is not None
                and float(row["percent_used"]) >= HELIUS_CREDIT_WARN_PCT):
            activity_log.warn(
                "helius",
                f"{label} kredit Helius menipis: sisa "
                f"{_fmt_int(remaining)} / {_fmt_int(total)} "
                f"({float(row['percent_used']):.0f}% terpakai)",
                dedup_sec=1800.0)


def reset_helius_usage_cache() -> None:
    """Kosongkan cache status key (tes, atau setelah key dipasang ulang)."""
    global _helius_usage_inflight
    with _helius_usage_lock:
        _helius_usage_cache.update({"keys": (), "ts": 0.0, "rows": []})
        _helius_usage_inflight = False


def _fmt_int(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "?"


def helius_usage_summary(*, background: bool = True) -> str:
    """Satu baris "sisa kredit Helius" untuk panel 🧾.

    Contoh::

        Helius API: 1 key · key#1 (primary) kredit tersisa 912,345 dari
        1,000,000 (pakai 8.8%) · ±1,204 request sesi ini · dicek 3 mnt lalu

    Tanpa key, pesan tetap dikembalikan — itu justru informasi yang perlu
    tindakan. Plafon kredit Helius dihitung per project, jadi angka yang sama
    dari beberapa key dalam satu project hanya disebut sekali.
    """
    status = helius_usage_status(background=background)
    rows = status.get("rows") or []
    if not rows:
        if not status.get("total_keys"):
            return ("Helius API: belum ada key terpasang — tanpa key, dust "
                    "holder Solana (🛰 Scan Holder, 🌊 Watchlist Meteora, "
                    "🏆 Scan Best Pool) tidak bisa dihitung. Isi "
                    "`helius_api_key` di config.json / env `HELIUS_API_KEY` "
                    "/ Streamlit secrets.")
        # Key ada, cache masih kosong (probe pertama sedang jalan).
        return (f"Helius API: {int(status.get('total_keys') or 0)} key · "
                "sisa kredit sedang dicek (probe jalan di latar, angka "
                "muncul pada refresh berikutnya)")
    parts = [f"Helius API: {len(rows)} key"]
    notes: list[str] = []
    seen: set = set()
    for row in rows:
        label = str(row.get("label") or "key")
        name = str(row.get("name") or "").strip()
        tag = f"{label} ({name})" if name else label
        status_text = str(row.get("status") or "")
        remaining, total = row.get("remaining"), row.get("total")
        if status_text == "rejected":
            notes.append(f"{tag} DITOLAK {str(row.get('error') or 'HTTP 401')}")
            continue
        if status_text in ("unreachable", "error"):
            detail = str(row.get("error") or "")[:60]
            notes.append(f"{tag} tidak bisa dicek"
                         + (f" ({detail})" if detail else ""))
            continue
        if remaining is None and total is None:
            rate = f" · {row['rate_limit']}" if row.get("rate_limit") else ""
            notes.append(f"{tag} hidup{rate} — Helius tidak mengirim angka "
                         "kredit untuk plan ini (sisa hanya terlihat di "
                         "dashboard.helius.dev)")
            continue
        marker = (remaining, total)
        if marker in seen:
            continue
        seen.add(marker)
        text = f"{tag} kredit tersisa {_fmt_int(remaining)}"
        if total:
            text += f" dari {_fmt_int(total)}"
        percent = row.get("percent_used")
        if percent is not None:
            text += f" (pakai {float(percent):.1f}%)"
        notes.append(text)
    parts.extend(notes)
    parts.append(f"±{helius_request_count():,} request sesi ini")
    if status.get("refreshing"):
        parts.append("sedang dicek ulang")
    else:
        age = status.get("cache_age_sec")
        if age is not None:
            parts.append("dicek baru" if age < 60
                         else f"dicek {int(age) // 60} mnt lalu")
    return " · ".join(parts)


def helius_credit_remaining(*, use_cache: bool = False) -> int | None:
    """Total sisa kredit seluruh key; ``None`` bila Helius tidak melapor.

    ``use_cache=True`` tidak menyentuh jaringan (pakai cache UI). Key dari
    satu project berbagi plafon → nilai identik dihitung sekali.
    """
    rows = (helius_usage_status(background=True).get("rows") if use_cache
            else helius_key_status())
    values = [row.get("remaining") for row in (rows or [])
              if row.get("remaining") is not None]
    if not values:
        return None
    return sum(dict.fromkeys(values))


def helius_rpc_request(payload: dict, helius_keys=None, *, timeout: int = 60,
                       max_attempts=None) -> dict:
    """POST Helius JSON-RPC, rotating on HTTP 429/5xx and network errors."""
    last_error = None
    for key in _helius_candidates(helius_keys, max_attempts):
        try:
            response = requests.post(HELIUS_RPC_URL, params={"api-key": key},
                                     json=payload, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_error = _response_error(response, "Helius RPC")
            continue
        response.raise_for_status()
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            last_error = exc
            continue
        error = data.get("error") if isinstance(data, dict) else None
        if error:
            err = RuntimeError(f"Helius RPC error: {error}")
            if _transient_rpc_error(error):
                last_error = err
                continue
            raise err
        _count_helius_call()
        return data
    if last_error:
        raise last_error
    raise RuntimeError("Helius RPC failed without a response")


def helius_rpc(method: str, params, helius_keys=None, *, timeout: int = 60,
               max_attempts=None):
    """Call a Helius JSON-RPC method through the shared rotating key pool."""
    data = helius_rpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        helius_keys, timeout=timeout, max_attempts=max_attempts)
    if "result" not in data:
        raise RuntimeError("Helius RPC response has no result")
    return data["result"]


def helius_api_get(url: str, *, params=None, headers=None, helius_keys=None,
                   timeout: int = 40, max_attempts=None):
    """GET a Helius Enhanced API endpoint with the same rotating key pool."""
    last_error = None
    for key in _helius_candidates(helius_keys, max_attempts):
        query = dict(params or {})
        query["api-key"] = key
        try:
            response = requests.get(url, params=query, headers=headers,
                                    timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_error = _response_error(response, "Helius API")
            continue
        response.raise_for_status()
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            last_error = exc
            continue
        _count_helius_call()
        return data
    if last_error:
        raise last_error
    raise RuntimeError("Helius API failed without a response")


def load_config() -> dict:
    cfg = {"helius_api_key": "", "helius_extra_keys": "",
           "custom_rpc": "", "dust_limit_usd": 5,
           "cluster_warn_pct": 5, "cluster_scan_top_n": 50, "exclude_lp": True}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f) or {})
    except Exception:
        pass
    try:  # Streamlit Cloud secrets menimpa config.json
        import streamlit as st
        for k in list(cfg.keys()):
            if k in st.secrets:
                cfg[k] = st.secrets[k]
    except Exception:
        pass
    return cfg


def _dex_liquidity_usd(pair: dict) -> float:
    """Return a finite, non-negative DexScreener liquidity value."""
    try:
        value = float((pair.get("liquidity") or {}).get("usd") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    if value != value or value < 0 or value == float("inf"):
        return 0.0
    return value


def _dex_token_address(pair: dict, side: str) -> str:
    """Return a token address from a DexScreener pair without coercing case.

    Solana base58 addresses are case-sensitive, so this intentionally only
    strips surrounding whitespace rather than lower-casing the address.
    """
    token = pair.get(side) if isinstance(pair, dict) else None
    if not isinstance(token, dict):
        return ""
    return str(token.get("address") or "").strip()


def _address_matches_screening(left: str, right: str) -> bool:
    """Compare two token addresses for matching.

    Solana base58 is case-sensitive, while EVM/Robinhood ``0x`` addresses are
    case-insensitive. Normalizing only EVM addresses keeps existing Solana
    behavior unchanged while allowing Robinhood's mixed-case DexScreener
    payload (e.g. ``0x8490ACd2…``) to match a lower-cased watchlist key.
    """
    a = str(left or "").strip()
    b = str(right or "").strip()
    if a.startswith("0x") or b.startswith("0x"):
        return a.lower() == b.lower()
    return a == b


def matching_dexscreener_pairs(pairs, ca: str, *,
                               chain_id: str | None = None) -> list:
    """Return DexScreener pairs for exactly ``ca``, in safe display order.

    ``/latest/dex/tokens/<CA>`` can include a cross-pair where the requested
    CA is the *quote* token. Picking the raw highest-liquidity response and
    reading ``baseToken`` then labels the requested token as the other side
    of that pair (for example MEMIPEDE was shown as Cyclospora).

    Exact address matches are mandatory. Pairs where the queried token is
    ``baseToken`` come first, then quote-side fallbacks; each group is sorted
    by liquidity. This keeps DexScreener's normal price/FDV semantics while
    still allowing a quote-side-only token to be identified honestly.

    ``chain_id`` (e.g. ``robinhood``) optionally filters the chain so an EVM
    address reused on another network cannot leak its market data into the
    Robinhood watchlist.
    """
    target = str(ca or "").strip()
    if not target:
        return []
    wanted_chain = str(chain_id or "").strip()

    base_matches, quote_matches = [], []
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        if wanted_chain and str(pair.get("chainId") or "").strip() != wanted_chain:
            continue
        if _address_matches_screening(_dex_token_address(pair, "baseToken"),
                                      target):
            base_matches.append(pair)
        elif _address_matches_screening(_dex_token_address(pair, "quoteToken"),
                                        target):
            quote_matches.append(pair)

    def _sort_key(pair):
        return (-_dex_liquidity_usd(pair),
                str(pair.get("pairAddress") or ""))

    base_matches.sort(key=_sort_key)
    quote_matches.sort(key=_sort_key)
    return base_matches + quote_matches


def select_dexscreener_pair(pairs, ca: str) -> dict | None:
    """Choose the canonical DexScreener pair for ``ca``, or ``None``.

    See :func:`matching_dexscreener_pairs` for why this must not use raw
    ``pairs[0]``.
    """
    matches = matching_dexscreener_pairs(pairs, ca)
    return matches[0] if matches else None


def dexscreener_pair_token(pair: dict, ca: str) -> dict:
    """Return metadata for ``ca`` from either side of a matched pair.

    Returning the queried side rather than unconditionally ``baseToken``
    prevents a quote-side fallback from ever borrowing another token's name
    or symbol.
    """
    target = str(ca or "").strip()
    if not target or not isinstance(pair, dict):
        return {}
    for side in ("baseToken", "quoteToken"):
        if _address_matches_screening(_dex_token_address(pair, side), target):
            token = pair.get(side)
            return dict(token) if isinstance(token, dict) else {}
    return {}


def get_market(ca: str, *, chain_id: str | None = None) -> dict:
    """DexScreener market data for exactly one token contract address.

    The endpoint can return cross-pairs where ``ca`` is the quote token.
    Filter and order those responses before reading metadata so a liquid
    unrelated base token cannot replace the requested token in the UI.
    ``chain_id`` (e.g. ``robinhood``) keeps EVM networks isolated.
    """
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                     timeout=20)
    raw_pairs = (r.json() or {}).get("pairs") or []
    pairs = matching_dexscreener_pairs(raw_pairs, ca, chain_id=chain_id)
    if not pairs:
        return {}
    pair = pairs[0]
    token = dexscreener_pair_token(pair, ca)
    return {
        "name": token.get("name", "?"),
        "symbol": token.get("symbol", "?"),
        "chain_id": pair.get("chainId", ""),
        "price_usd": float(pair.get("priceUsd") or 0),
        "marketcap": float(pair.get("marketCap") or pair.get("fdv") or 0),
        "liquidity_usd": _dex_liquidity_usd(pair),
        "dex": pair.get("dexId", "?"),
        "pair_addresses": [p.get("pairAddress") for p in pairs
                           if p.get("pairAddress")],
        "url": pair.get("url", ""),
        "image": ((pair.get("info") or {}).get("imageUrl") or ""),
        "txns": pair.get("txns") or {},
        "volume": pair.get("volume") or {},
        "price_change": pair.get("priceChange") or {},
        "pair_created_at": pair.get("pairCreatedAt"),
        "pairs_detail": [{
            "dex": p.get("dexId", "?"),
            "pair": p.get("pairAddress"),
            "liq": _dex_liquidity_usd(p),
            "url": p.get("url", ""),
            "quote": (p.get("quoteToken") or {}).get("symbol", "?"),
        } for p in pairs],
    }


GECKOTERMINAL_OHLCV_URL = ("https://api.geckoterminal.com/api/v2/networks/"
                           "solana/pools/{pair}/ohlcv/hour")
GECKOTERMINAL_MAX_LIMIT = 1000
# 1e11 detik = tahun 5138: di atas itu timestamp pasti milidetik.
MILLISECOND_TS_THRESHOLD = 100_000_000_000


def _ohlcv_number(value) -> float | None:
    """Return a finite float for one OHLCV cell, or ``None`` when unusable.

    GeckoTerminal emits ``null`` cells for hours without trade, so every cell
    is validated before it can poison a daily aggregate or a stddev.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_hourly_candles(values) -> list[dict]:
    """Normalize a GeckoTerminal ``ohlcv_list`` payload into hourly candles.

    Output rows are ``{ts, open, high, low, close, volume_usd}`` sorted by
    timestamp ascending. A row is kept when it has a usable timestamp and a
    finite ``close``; ``null`` open/high/low (hours without trade) fall back to
    that close and missing volume falls back to zero, so a quiet hour still
    counts as coverage instead of punching a hole in the series. Rows without a
    usable close are dropped, and a repeated timestamp keeps the last
    occurrence so hourly volume can never be counted twice.
    """
    rows: dict[int, dict] = {}
    for value in values or []:
        if not isinstance(value, (list, tuple)) or len(value) < 6:
            continue
        ts = _ohlcv_number(value[0])
        close = _ohlcv_number(value[4])
        if ts is None or ts <= 0 or close is None:
            continue
        if ts > MILLISECOND_TS_THRESHOLD:
            # GeckoTerminal mengirim detik Unix; kalau suatu saat satuannya
            # berganti ke milidetik, setiap jam akan tampak sebagai "hari"
            # sendiri (tahun ~57.000) dan agregasi harian hening-heningan
            # menghasilkan nol baris. Dinormalisasi di satu tempat.
            ts = ts / 1000.0
        opening = _ohlcv_number(value[1])
        high = _ohlcv_number(value[2])
        low = _ohlcv_number(value[3])
        volume = _ohlcv_number(value[5]) or 0.0
        rows[int(ts)] = {
            "ts": int(ts),
            "open": close if opening is None else opening,
            "high": max(close, high if high is not None else close),
            "low": min(close, low if low is not None else close),
            "close": close,
            "volume_usd": max(0.0, volume),
        }
    return [rows[ts] for ts in sorted(rows)]


def get_hourly_candles(pair_address: str, limit_hours: int = 168, *,
                       timeout: int = 25) -> list[dict]:
    """Fetch hourly GeckoTerminal candles for one pool (oldest -> newest).

    ``limit_hours`` defaults to 7 x 24 so one request can serve both a
    four-hour volume window and a seven-day volume average. Transport or
    parse failures return ``[]``: market data must never raise into a scan.
    """
    pair = str(pair_address or "").strip()
    if not pair:
        return []
    try:
        limit = max(1, min(GECKOTERMINAL_MAX_LIMIT, int(limit_hours)))
        response = requests.get(
            GECKOTERMINAL_OHLCV_URL.format(pair=pair),
            params={"aggregate": 1, "limit": limit},
            headers={"accept": "application/json"}, timeout=timeout)
        response.raise_for_status()
        payload = (response.json() or {}).get("data") or {}
        values = ((payload.get("attributes") or {}).get("ohlcv_list")) or []
    except Exception:  # noqa: BLE001 - pasar tidak boleh menggagalkan scan
        return []
    return normalize_hourly_candles(values)


def aggregate_daily_candles(hourly, limit_days: int = 7) -> list[dict]:
    """Aggregate hourly candles into UTC calendar days (pure, no HTTP).

    The UTC day boundary matches the crypto-market day used by Helius and
    Solscan; ``datetime.date()`` carries month/year edges itself, so no manual
    day arithmetic is involved (verified untuk 31 Des → 1 Jan dan 28 → 29 Feb
    tahun kabisat di ``tests/test_core_candles.py``). ``hours`` reports coverage
    so a partial day stays recognizable — **hari UTC yang masih berjalan ikut
    ter-return**, jadi pemanggil yang butuh hari lengkap harus menyaringnya
    (lihat ``cvd_daily.completed_dates``). ``limit_days <= 0`` returns ``[]``
    instead of the whole history (``[-0:]`` would otherwise silently return
    everything).
    """
    try:
        days = int(limit_days)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return []
    grouped: dict[str, dict] = {}
    for candle in hourly or []:
        if not isinstance(candle, dict):
            continue
        ts = _ohlcv_number(candle.get("ts"))
        close = _ohlcv_number(candle.get("close"))
        if ts is None or ts <= 0 or close is None:
            continue
        high = _ohlcv_number(candle.get("high"))
        low = _ohlcv_number(candle.get("low"))
        opening = _ohlcv_number(candle.get("open"))
        volume = _ohlcv_number(candle.get("volume_usd")) or 0.0
        date = datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()
        day = grouped.get(date)
        if day is None:
            grouped[date] = {
                "date": date,
                "open": close if opening is None else opening,
                "high": close if high is None else high,
                "low": close if low is None else low,
                "close": close,
                "volume_usd": max(0.0, volume),
                "hours": 1,
            }
            continue
        day["high"] = max(day["high"], close if high is None else high)
        day["low"] = min(day["low"], close if low is None else low)
        day["close"] = close
        day["volume_usd"] += max(0.0, volume)
        day["hours"] += 1
    ordered = sorted(grouped.values(), key=lambda item: item["date"])
    return ordered[-days:]


def get_daily_candles(pair_address: str, limit_days: int = 7) -> list[dict]:
    """Fetch hourly GeckoTerminal candles and aggregate calendar days in UTC.

    Hourly candles are aggregated into calendar days using the UTC boundary,
    which matches the crypto-market day used by Helius and Solscan.
    """
    try:
        days = int(limit_days)
    except (TypeError, ValueError):
        return []
    if days <= 0:
        return []
    hourly = get_hourly_candles(pair_address, limit_hours=days * 24 + 24)
    return aggregate_daily_candles(hourly, limit_days=days)
