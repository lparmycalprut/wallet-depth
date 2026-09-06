# -*- coding: utf-8 -*-
"""Setelan alert Telegram yang bisa diubah dari dashboard.

Saat ini isinya satu tombol: **on/off notifikasi Telegram untuk watchlist
biasa** (watchlist Solana ``source`` manual/degen — bukan Chart LP Meteora,
bukan Robinhood). Permintaan user 2026-09-06: kadang watchlist biasa hanya
ingin dipantau di dashboard tanpa dikirimi pesan 🔔 HIGH DROP / dump /
akumulasi.

Kenapa file terpisah dan bukan ``watchlist.json``: setelan ini bukan data
token, dan ``watchlist.json`` punya jalur journal + merge sendiri yang
sengaja tidak boleh kemasukan field lain.

Persistensi memakai transport durable yang sama dengan snapshot holder
(``holder_status._github_get_bytes`` / ``_github_put_bytes`` di ref
``holder-live``) sehingga:

- dashboard Streamlit Cloud (ephemeral) tetap mengingat pilihan user;
- cron GitHub Actions membaca pilihan yang sama sebelum mengirim Telegram.

Gagal baca remote = jatuh ke file lokal, lalu ke default (**aktif**):
mematikan alert harus selalu keputusan eksplisit user, bukan efek samping
API GitHub yang sedang error.
"""
from __future__ import annotations

import json
import os
import sys
import time

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_REPO_PATH = "alert_settings.json"
SETTINGS_PATH = os.path.join(BASE_DIR, SETTINGS_REPO_PATH)

# Kunci setelan. Default semuanya True (perilaku lama: alert menyala).
KEY_REGULAR_TELEGRAM = "telegram_regular_enabled"
DEFAULTS = {KEY_REGULAR_TELEGRAM: True}

_CACHE_TTL = 30
_CACHE: dict = {"data": None, "ts": 0.0}


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on", "ya"):
            return True
        if text in ("0", "false", "no", "off", "tidak"):
            return False
    return default


def _normalize(data) -> dict:
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        for key, default in DEFAULTS.items():
            if key in data:
                out[key] = _as_bool(data.get(key), default)
    return out


def _read_local() -> dict | None:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    return _normalize(data) if isinstance(data, dict) else None


def _read_remote() -> dict | None:
    try:
        from holder_status import _github_get_bytes
        body = _github_get_bytes(SETTINGS_REPO_PATH)
    except Exception as exc:  # noqa: BLE001 - offline/permission = pakai lokal
        print(f"WARN: alert_settings pull gagal: {exc}", file=sys.stderr)
        return None
    if not body:
        return None
    try:
        return _normalize(json.loads(body.decode("utf-8")))
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        print(f"WARN: alert_settings parse gagal: {exc}", file=sys.stderr)
        return None


def reset_cache() -> None:
    _CACHE["data"] = None
    _CACHE["ts"] = 0.0


def load_settings(force_refresh: bool = False) -> dict:
    """Setelan efektif: remote (durable) → file lokal → default."""
    now = time.time()
    if (not force_refresh and isinstance(_CACHE.get("data"), dict)
            and (now - float(_CACHE.get("ts") or 0.0)) < _CACHE_TTL):
        return dict(_CACHE["data"])
    settings = _read_remote()
    if settings is None:
        settings = _read_local()
    if settings is None:
        settings = dict(DEFAULTS)
    _CACHE["data"] = dict(settings)
    _CACHE["ts"] = now
    return dict(settings)


def save_settings(settings: dict, *, push: bool = True) -> bool:
    """Tulis setelan ke file lokal + (opsional) ref durable ``holder-live``.

    Return ``True`` bila push remote berhasil (atau ``push=False``); ``False``
    berarti pilihan tersimpan lokal saja — pemanggil UI memberi tahu user
    supaya tidak mengira cron sudah ikut berubah.
    """
    payload = _normalize(settings)
    try:
        atomic_write_json(SETTINGS_PATH, payload, indent=2, sort_keys=True)
    except OSError as exc:
        print(f"WARN: alert_settings tulis lokal gagal: {exc}", file=sys.stderr)
    # Cache di-seed optimis supaya UI langsung memantulkan pilihan user.
    _CACHE["data"] = dict(payload)
    _CACHE["ts"] = time.time()
    if not push:
        return True
    try:
        from holder_status import _github_put_bytes
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        ok = bool(_github_put_bytes(
            SETTINGS_REPO_PATH, body,
            "alert-settings: update toggle Telegram [skip ci]"))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: alert_settings push gagal: {exc}", file=sys.stderr)
        return False
    return ok


def regular_telegram_enabled(force_refresh: bool = False) -> bool:
    """True bila alert Telegram watchlist biasa (Solana) boleh dikirim."""
    return bool(load_settings(force_refresh=force_refresh).get(
        KEY_REGULAR_TELEGRAM, True))


def set_regular_telegram_enabled(enabled: bool) -> bool:
    settings = load_settings()
    settings[KEY_REGULAR_TELEGRAM] = bool(enabled)
    return save_settings(settings)
