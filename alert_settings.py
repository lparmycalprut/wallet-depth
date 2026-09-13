# -*- coding: utf-8 -*-
"""Setelan alert Telegram yang bisa diubah dari dashboard.

Dua setelan:

1. **on/off notifikasi Telegram untuk watchlist biasa** (watchlist Solana
   ``source`` manual/degen — bukan Chart LP Meteora, bukan Robinhood).
   Permintaan user 2026-09-06: kadang watchlist biasa hanya ingin dipantau di
   dashboard tanpa dikirimi pesan Telegram.
2. **on/off notifikasi Telegram per token** (``muted_mints``) untuk token
   watchlist **Meteora** dan **Robinhood** — permintaan user 2026-09-11:
   *"kasih toggle alert on off per token … jadi misal saya sudah tau ada
   notif, saya bisa nonaktifkan. tapi pas awal memasukkan ke watchlist,
   otomatis on"*. Karena daftar ini **blocklist**, token baru otomatis ON:
   tidak perlu menulis apa pun saat token di-add, dan ``watchlist`` /
   ``robinhood_watchlist`` memanggil :func:`forget_mint_alert` supaya token
   yang di-add **ulang** tidak mewarisi pilihan OFF periode sebelumnya.

Notifikasinya kini satu: ⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE (dust
naik ≥ 0,02% MC dari angka saat token masuk watchlist, berulang tiap
kelipatan 0,02%; rule ambang 0,06% sudah diganti 2026-09-13). Pemakaiannya di
``telegram_alerts.process_holder_alerts(mute_mints=…)``: rule tetap
**dievaluasi** dan marker (``early_dump``) tetap dimajukan, hanya
pengiriman pesannya yang dilewati — jadi menyalakan notif lagi tidak
membanjiri user dengan pengingat episode lama.

Kenapa file terpisah dan bukan ``watchlist.json``: setelan ini bukan data
token, dan ``watchlist.json`` punya jalur journal + merge sendiri yang
sengaja tidak boleh kemasukan field lain. Satu file dipakai bersama kedua
jaringan (Solana & Robinhood) supaya cron cukup membaca satu kali.

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
import re
import sys
import time

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_REPO_PATH = "alert_settings.json"
SETTINGS_PATH = os.path.join(BASE_DIR, SETTINGS_REPO_PATH)

# Kunci setelan. Default: notif watchlist biasa ON + tidak ada token yang
# dimatikan (token baru selalu ON).
KEY_REGULAR_TELEGRAM = "telegram_regular_enabled"
KEY_MUTED_MINTS = "muted_mints"
DEFAULTS = {KEY_REGULAR_TELEGRAM: True, KEY_MUTED_MINTS: []}

# Pesan commit default; toggle per token menimpa lewat ``save_settings``.
COMMIT_MESSAGE = "alert-settings: update toggle Telegram [skip ci]"

_CACHE_TTL = 30
_CACHE: dict = {"data": None, "ts": 0.0}

_EVM_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}\Z")


def mint_key(mint) -> str:
    """Kunci perbandingan mint/CA: EVM (``0x…``) disamakan huruf kecilnya.

    Sama dengan ``watchlist.address_key`` (tanpa impor ``watchlist`` supaya
    modul ini tetap ringan dan bebas siklus impor).
    """
    text = str(mint or "").strip()
    if _EVM_ADDRESS_RE.match(text):
        return text.lower()
    return text


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


def _normalize_mints(value) -> list[str]:
    """Daftar mint unik berurut — bentuk kanonik isi ``muted_mints``.

    Menerima list/tuple/set **atau** satu string (toleran terhadap file yang
    ditulis tangan / versi lama), membuang entri kosong, dan mengurutkan
    supaya payload JSON stabil (tidak ada commit "berubah" tanpa perubahan).
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        key = mint_key(item)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return sorted(out)


def _normalize(data) -> dict:
    out = {KEY_REGULAR_TELEGRAM: True, KEY_MUTED_MINTS: []}
    if isinstance(data, dict):
        if KEY_REGULAR_TELEGRAM in data:
            out[KEY_REGULAR_TELEGRAM] = _as_bool(
                data.get(KEY_REGULAR_TELEGRAM), True)
        if KEY_MUTED_MINTS in data:
            out[KEY_MUTED_MINTS] = _normalize_mints(data.get(KEY_MUTED_MINTS))
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


def _write_remote(payload: dict, message: str) -> bool:
    """Commit setelan ke ref durable ``holder-live`` (transport snapshot).

    Dipisah sebagai fungsi modul supaya suite tes bisa mematikannya tanpa
    menyentuh jaringan (``tests/__init__.py``) dan supaya satu-satunya tempat
    yang tahu bentuk JSON + pesan commit ada di sini.
    """
    from holder_status import _github_put_bytes
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return bool(_github_put_bytes(SETTINGS_REPO_PATH, body, str(message)))


def save_settings(settings: dict, *, push: bool = True,
                  message: str | None = None) -> bool:
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
        return bool(_write_remote(payload, str(message or COMMIT_MESSAGE)))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: alert_settings push gagal: {exc}", file=sys.stderr)
        return False


def regular_telegram_enabled(force_refresh: bool = False) -> bool:
    """True bila alert Telegram watchlist biasa (Solana) boleh dikirim."""
    return bool(load_settings(force_refresh=force_refresh).get(
        KEY_REGULAR_TELEGRAM, True))


def set_regular_telegram_enabled(enabled: bool) -> bool:
    settings = load_settings()
    settings[KEY_REGULAR_TELEGRAM] = bool(enabled)
    return save_settings(settings)


# ---------------------------------------------------------------------------
# Toggle alert per token (watchlist Meteora + Robinhood)
# ---------------------------------------------------------------------------

def muted_mints(force_refresh: bool = False) -> set[str]:
    """Token yang notif Telegram-nya dimatikan user (selain ON = default)."""
    return {str(item) for item in
            (load_settings(force_refresh=force_refresh).get(KEY_MUTED_MINTS)
             or []) if item}


def is_mint_muted(mint, force_refresh: bool = False) -> bool:
    """True bila notif Telegram untuk token ini sedang dimatikan user."""
    key = mint_key(mint)
    if not key:
        return False
    return key in muted_mints(force_refresh=force_refresh)


def mutes_for(mints, force_refresh: bool = False) -> set[str]:
    """Irisan ``mints`` dengan daftar mute — siap dipakai sebagai ``mute_mints``."""
    wanted = {mint_key(item) for item in (mints or []) if mint_key(item)}
    return wanted & muted_mints(force_refresh=force_refresh)


def set_mint_alert_enabled(mint, enabled: bool, *,
                           push: bool = True) -> bool:
    """Nyalakan/matikan notif Telegram satu token; ``False`` = push gagal.

    ``enabled=False`` menulis token ke ``muted_mints`` (cron + scan manual
    melewati pengiriman, evaluasi & marker tetap jalan); ``enabled=True``
    menghapusnya. Default (token baru / tidak ada di daftar) selalu ON.
    """
    key = mint_key(mint)
    if not key:
        return False
    settings = load_settings()
    muted = set(_normalize_mints(settings.get(KEY_MUTED_MINTS)))
    if enabled:
        muted.discard(key)
    else:
        muted.add(key)
    settings[KEY_MUTED_MINTS] = sorted(muted)
    label = "on" if enabled else "off"
    return save_settings(
        settings, push=push,
        message=(f"alert-settings: notif {label} {key[:12]} [skip ci]"))


def forget_mint_alert(mint, *, push: bool = True) -> bool:
    """Buang setelan OFF token — dipakai ``watchlist`` saat token **di-add**.

    Permintaan user: token yang baru masuk watchlist selalu ON. Tanpa ini,
    token yang pernah dimatikan lalu dihapus dan di-add ulang akan mewarisi
    ``muted_mints`` lamanya. Mint yang memang tidak ada di daftar **tidak**
    menulis/meng-commit apa pun (jalur add harus tetap cepat).
    """
    key = mint_key(mint)
    if not key:
        return False
    settings = load_settings()
    muted = _normalize_mints(settings.get(KEY_MUTED_MINTS))
    if key not in muted:
        return True
    settings[KEY_MUTED_MINTS] = [item for item in muted if item != key]
    return save_settings(
        settings, push=push,
        message=f"alert-settings: notif on {key[:12]} (add ulang) [skip ci]")
