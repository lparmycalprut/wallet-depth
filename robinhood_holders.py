# -*- coding: utf-8 -*-
"""Holder analysis for **Robinhood Chain** (chain id 4663, EVM).

Robinhood Chain adalah EVM L2 (Arbitrum Orbit) dengan
contract-address ``0x…``. Sumber holder-nya **Blockscout saja** —
``robinhoodchain.blockscout.com``, explorer resmi chain ini. GMGN
**tidak dipakai lagi** (dilepas 2026-09-08): endpoint
``/vas/api/v1/token_holders/robinhood/<CA>`` memang menjawab
``code: 0`` tetapi ``data.list`` selalu **kosong** — GMGN tidak
meng-index chain 4663. Karena kode lama memperlakukan GMGN sebagai
*primary*, tiap scan membuang satu request lalu jatuh ke Blockscout,
dan bila Blockscout ikut tersendat hasilnya "0 holder" yang terbaca
seperti "dust hilang semua".

**Transport (sejak 2026-09-08 sore): PRO API → instance publik.**
Instance publik ``robinhoodchain.blockscout.com`` kini duduk di belakang
bot-protection (Cloudflare): request "script" (TLS ``python-requests``,
UA apa pun) dijawab **HTTP 403** berbadan HTML "Just a moment…" — request
tidak pernah sampai ke Blockscout, jadi ``getToken`` / CSV / v2 gagal
serentak dan scan pulang "0 holder" walau CA valid dan harga DexScreener
tersedia (kejadian nyata: CA Pusheen ``0x1209ec…``, 409 holder). Jalur
resmi untuk akses programatik adalah **PRO API**
``https://api.blockscout.com/4663/…`` (key gratis di
https://dev.blockscout.com — 5 RPS, 100K kredit/hari ≈ 5.000 panggilan).
Karena itu setiap request lewat :func:`_blockscout_get`:

1. **PRO API** bila ada key (env ``BLOCKSCOUT_API_KEY`` /
   ``BLOCKSCOUT_API_KEYS`` daftar koma, ``config.json``
   ``blockscout_api_key(s)``, Streamlit secrets) — path **sama persis**,
   hanya host + prefiks chain id; key dikirim sebagai header
   ``Authorization: Bearer`` (bukan query) supaya tidak bocor ke URL di
   pesan error/log. **Beberapa key** (sejak 2026-09-09) dipakai
   round-robin lewat :class:`_ProKeyPool`: key yang dijawab 401/403
   (ditolak), 402 (kredit harian habis) atau 429 (RPS) diparkir sementara
   dan request pindah ke key berikutnya di putaran yang sama — kuota
   free tier (100K kredit/hari, 5 RPS) dihitung per akun, jadi N akun =
   N× plafon. Baru bila semua key diparkir / PRO 404 → jalur publik.
2. **Instance publik** dengan TLS browser (``curl_cffi``, profil dirotasi
   saat 403 — pola yang sama dengan GMGN di ``cvd.py``), lalu ``requests``
   biasa. 403/challenge dilaporkan sebagai :class:`BlockscoutBlocked`
   (bukan transient: tidak diulang, pesannya menyebut cara memperbaiki).

Tiga jalur Blockscout dipakai berurutan, dari yang paling lengkap:

1. **CSV export** (utama, TANPA limit paginasi) —
   ``/api/v2/tokens/<CA>/holders/csv`` mengembalikan **seluruh** holder
   dalam satu response, sudah ter-scale decimals
   (``HolderAddress,Balance``). Instance ini memakai mode sinkron
   (``/api/v2/config/csv-export`` → ``async_enabled: false``,
   ``limit: 10000``), jadi satu request = satu daftar penuh.
2. **REST v2 keyset** (fallback) — ``/api/v2/tokens/<CA>/holders``
   dengan cursor ``next_page_params`` (``address_hash`` + ``value``).
   Maksimum **50 baris/halaman** (``items_count`` > 50 ditolak 422),
   tetapi cursor-nya tidak punya batas kedalaman dan membawa metadata
   kontrak/pool (``is_contract``, ``name``) yang dipakai menandai LP.
3. **Legacy RPC** (fallback terakhir) —
   ``?module=token&action=getTokenHolders``. Perhatian: ``offset``
   dibatasi **≤ 400** (nilai lebih besar dijawab
   ``{"status":"0","message":"Something went wrong."}``) — inilah yang
   membuat versi lama, yang meminta ``offset=1000``, **selalu gagal**.

Modul ini menyediakan:

1. :func:`fetch_token_info` — decimals/symbol/supply dari Blockscout.
2. :func:`fetch_holders` — seluruh daftar holder ERC-20
   (``source: "blockscout-csv"`` / ``"blockscout-v2"`` /
   ``"blockscout-rpc"``).
3. :func:`analyze_token` — output yang bentuknya sama persis dengan
   :func:`holder_analysis.analyze_token` sehingga rule dust holder,
   chart 4 jam, kronologi, dan alert Telegram dipakai ulang tanpa logika
   baru.

Semua rule sama dengan Solana:
- dust wallet = ``0 < value <= $10`` (``holder_analysis.DUST_LIMIT_USD``);
- dust % MC >= 0,5% = HATI-HATI, >= 1% = BAHAYA;
- grafik 4 jam memakai ``holder_history`` yang sama.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import threading
import time

import requests

from core import CONFIG_PATH, get_market, merge_helius_keys
from holder_analysis import DUST_LIMIT_USD, classify_holders
from holder_history import FULL_SCAN_MAX_WALLETS
from solscan_holders import wallet_depth

# Same coverage for watchlist, cron and the dedicated holder scan.
DEFAULT_MAX_WALLETS = FULL_SCAN_MAX_WALLETS

CHAIN_SLUG = "robinhood"
CHAIN_ID = "4663"
CHAIN_NAME = "Robinhood Chain"
BLOCKSCOUT_API = "https://robinhoodchain.blockscout.com/api"
BLOCKSCOUT_BASE = "https://robinhoodchain.blockscout.com"
BLOCKSCOUT_V2 = f"{BLOCKSCOUT_BASE}/api/v2"
# PRO API multichain Blockscout: host tunggal + prefiks chain id, path sisanya
# identik dengan instance publik (``/api?module=…`` maupun ``/api/v2/…``).
BLOCKSCOUT_PRO_BASE = "https://api.blockscout.com"
BLOCKSCOUT_PRO_CHAIN_BASE = f"{BLOCKSCOUT_PRO_BASE}/{CHAIN_ID}"
BLOCKSCOUT_KEY_URL = "https://dev.blockscout.com"
RH_SCAN_TOKEN_BASE = "https://rh-scan.com/token/"
DEXSCREENER_CHAIN = CHAIN_SLUG

SOURCE_CSV = "blockscout-csv"
SOURCE_V2 = "blockscout-v2"
SOURCE_RPC = "blockscout-rpc"

# Cache in-memory: TTL singkat supaya rerun Streamlit dalam hitungan detik
# tidak menembak Blockscout berkali-kali. HARUS jauh di bawah
# ``holder_history.LP_INTERVAL_SEC`` (300 dtk) supaya scan LP 5 menit selalu
# memotret data baru, bukan snapshot cache yang bikin grafik mendatar.
_HOLDER_CACHE_TTL = 90
_HOLDER_CACHE: dict[str, dict] = {}

# Batas nyata Blockscout (terukur di robinhoodchain.blockscout.com,
# 2026-09-08). Melewatinya = request ditolak, bukan sekadar dipotong.
V2_PAGE_SIZE = 50            # /api/v2/…/holders → items_count max 50
V2_PAGE_CAP = 600            # 600 × 50 = 30k wallet (jalur cadangan terakhir)
HOLDER_PAGE_SIZE = 400       # legacy RPC → offset max 400 (bukan 1000!)
HOLDER_PAGE_CAP = 500        # 500 × 400 = 200k wallet, cukup untuk token terbesar
PAGE_SLEEP_SEC = 0.6         # ~1,7 req/s — sopan untuk instance publik
CSV_EXPORT_LIMIT = 10_000    # server-side synchronous export ceiling
CSV_TIMEOUT = 90             # satu response bisa memuat puluhan ribu baris

_EVM_ADDRESS_RE = __import__("re").compile(r"0x[0-9a-fA-F]{40}")


def _float(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        return num if num == num else default
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    return int(_float(value, float(default)))


# ---------------------------------------------------------------------------
# Blockscout — satu-satunya sumber holder Robinhood Chain
# ---------------------------------------------------------------------------
# GMGN dilepas 2026-09-08: chain 4663 tidak di-index di sana (``data.list``
# selalu []), jadi memakainya sebagai primary hanya menambah satu request
# gagal per scan. Blockscout publik membatasi laju (HTTP 429) dan sesekali
# membalas 5xx, jadi transport-nya tetap memakai retry + backoff.
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SEC = 5.0

# Bot-protection instance publik (terlihat 2026-09-08 sore): HTTP 403 dengan
# badan HTML "Just a moment…" / cf-mitigated=challenge. Bukan error API dan
# bukan transient — mengulang request yang sama hanya membuang waktu. Profil
# TLS browser dirotasi dulu (pola GMGN di ``cvd.py``); kalau semuanya ditolak,
# hasilnya :class:`BlockscoutBlocked` dengan petunjuk perbaikan.
BLOCKED_STATUS = frozenset({403})
BLOCKSCOUT_IMPERSONATE = (
    "chrome",
    "chrome136",
    "chrome131",
    "safari184",
    "safari17_0",
    "firefox133",
)
BROWSER_HEADERS = {
    "accept": "application/json, text/csv, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "referer": f"{BLOCKSCOUT_BASE}/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/150.0.0.0 Safari/537.36"),
}
# ``impersonate`` curl_cffi memasang UA + Client Hints yang cocok dengan JA3;
# header kita yang sama tidak boleh menimpanya.
_IMPERSONATE_OWNED_HEADERS = {"user-agent", "sec-ch-ua", "sec-ch-ua-mobile",
                              "sec-ch-ua-platform"}

# Jalur transport yang dipakai satu request — dilaporkan di ``source`` hasil
# scan (``blockscout-csv@pro``) supaya UI/log tahu request lewat mana.
ROUTE_PRO = "pro"
ROUTE_PUBLIC = "public"

# Key PRO API boleh **lebih dari satu** (sejak 2026-09-09). Kuota free tier
# dihitung per akun (100K kredit/hari, 5 RPS), jadi beberapa key dari akun
# berbeda menaikkan plafon harian dan RPS. Request dibagi rata (round-robin)
# ke semua key; key yang dijawab 401/403 (ditolak), 402 (kredit habis) atau
# 429 (RPS) "diparkir" sementara dan request langsung pindah ke key
# berikutnya — scan tidak gagal selama masih ada satu key yang hidup.
# Konvensi sumber sama dengan Helius: env tunggal + env daftar (koma/baris
# baru) + config.json + Streamlit secrets, semuanya digabung & didedup.
_PRO_KEY_ENV = ("BLOCKSCOUT_API_KEY", "BLOCKSCOUT_API_KEYS",
                "BLOCKSCOUT_PRO_API_KEY")
_PRO_KEY_CONFIG = ("blockscout_api_key", "blockscout_api_keys")
# Status PRO API yang berkaitan dengan *key*, bukan data → parkir key itu dan
# coba key lain. 404 (rute/chain tidak dikenal) tidak diparkir: langsung ke
# instance publik.
PRO_ROTATE_STATUS = frozenset({401, 402, 403, 429})
PRO_FALLBACK_STATUS = PRO_ROTATE_STATUS | {404}
# Lama parkir per status (detik). 402 free tier reset harian pada jam yang
# tidak dipublikasikan → probe ulang tiap 30 menit (satu request 402 murah).
# 429 memakai header ``x-ratelimit-reset`` (ms) bila ada, dibatasi 60 dtk.
PRO_PARK_SEC = {401: 3600.0, 403: 300.0, 402: 1800.0, 429: 2.0}
PRO_PARK_429_MAX_SEC = 60.0


class BlockscoutBlocked(RuntimeError):
    """Instance publik menolak request lewat bot-protection (HTTP 403).

    Dipisah dari error HTTP biasa supaya (1) tidak masuk retry transient,
    (2) pesannya menjelaskan penyebab + perbaikan, bukan sekadar
    ``403 Client Error: Forbidden for url: …``.
    """

    HINT_NO_KEY = (f"pasang BLOCKSCOUT_API_KEY (key gratis: "
                   f"{BLOCKSCOUT_KEY_URL}) agar scan lewat PRO API")
    HINT_KEYS_FAILED = ("key PRO API ada tetapi semuanya ditolak / kreditnya "
                        f"habis — periksa dashboard {BLOCKSCOUT_KEY_URL}")

    def __init__(self, url: str, detail: str = "", hint: str | None = None):
        self.url = str(url or "")
        self.detail = str(detail or "")
        self.hint = self.HINT_NO_KEY if hint is None else str(hint)
        path = self.url.split("?", 1)[0]
        for base in (BLOCKSCOUT_BASE, BLOCKSCOUT_PRO_CHAIN_BASE):
            if path.startswith(base):
                path = path[len(base):] or "/"
                break
        msg = (f"Blockscout publik menolak request (HTTP 403 bot-protection) "
               f"di {path}")
        if self.detail:
            msg += f" [{self.detail}]"
        if self.hint:
            msg += f" — {self.hint}"
        super().__init__(msg)


class ProApiError(requests.exceptions.HTTPError):
    """PRO API menjawab status yang berkaitan dengan key/kuota/rute.

    ``status`` 401/403 = key ditolak, 402 = kredit habis, 429 = RPS key itu
    terlampaui, 404 = rute/chain tidak dikenal. ``key_label`` hanya
    ``key#N`` — key aslinya tidak pernah ikut ke pesan.
    """

    def __init__(self, status: int, detail: str, response, key_label: str):
        self.status = int(status)
        self.detail = str(detail or "")
        self.key_label = str(key_label or "")
        msg = f"PRO API {self.status}"
        if self.detail:
            msg += f" {self.detail}"
        if self.key_label:
            msg += f" ({self.key_label})"
        super().__init__(msg, response=response)


class ProKeysParked(RuntimeError):
    """Semua key PRO sedang diparkir (ditolak / kredit habis / RPS)."""


# ---------------------------------------------------------------------------
# Log aktivitas (panel 🧾 di bawah halaman utama, 2026-09-10) — kejadian pool
# key PRO / bot-protection dicatat supaya user melihat "kena limit di key
# mana" tanpa membuka terminal. Import ditunda + dibungkus supaya modul ini
# tetap jalan di cron/tes tanpa activity_log.
# ---------------------------------------------------------------------------
def _log_key_parked(label: str, status: int, detail: str = "") -> None:
    try:
        import activity_log
    except Exception:  # noqa: BLE001 - log hanya pelengkap
        return
    status = int(status)
    minutes = int(PRO_PARK_SEC.get(status, 300) // 60)
    if status == 402:
        activity_log.action(
            "blockscout", f"PRO API {label}: kredit harian HABIS (402) — "
            f"parkir {minutes} mnt; tunggu reset harian atau tambah key "
            "akun lain ke BLOCKSCOUT_API_KEYS")
    elif status in (401, 403):
        activity_log.action(
            "blockscout", f"PRO API {label}: key DITOLAK ({status}"
            f"{', ' + detail if detail else ''}) — parkir {minutes} mnt; "
            f"periksa key di dashboard {BLOCKSCOUT_KEY_URL}")
    else:  # 429 — pulih sendiri, cukup warning
        activity_log.warn(
            "blockscout", f"PRO API {label}: rate limit RPS (429) — key "
            "diparkir sebentar, request pindah ke key berikutnya")


def _log_all_keys_parked(pool) -> None:
    try:
        import activity_log
    except Exception:  # noqa: BLE001
        return
    activity_log.warn(
        "blockscout", f"SEMUA {len(pool.keys)} key PRO diparkir — request "
        f"jatuh ke instance publik (lambat). {pool.summary()}")


def _log_blocked(exc) -> None:
    try:
        import activity_log
    except Exception:  # noqa: BLE001
        return
    keys = len(get_pro_api_keys())
    if keys:
        activity_log.action(
            "blockscout", "Instance publik menolak request (403 "
            f"bot-protection) dan {keys} key PRO tidak menolong — "
            f"periksa kredit/status key di {BLOCKSCOUT_KEY_URL}")
    else:
        activity_log.action(
            "blockscout", "Instance publik menolak request (403 "
            "bot-protection) — pasang BLOCKSCOUT_API_KEY (key gratis: "
            f"{BLOCKSCOUT_KEY_URL}) supaya scan lewat PRO API")


def _status_code(exc) -> int:
    response = getattr(exc, "response", None)
    try:
        return int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def is_transient_error(exc) -> bool:
    """True untuk kegagalan jaringan/HTTP yang layak dicoba ulang."""
    if isinstance(exc, BlockscoutBlocked):
        return False
    if _status_code(exc) in TRANSIENT_STATUS:
        return True
    if isinstance(exc, (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError)):
        return True
    # curl_cffi punya hierarki exception sendiri (bukan subclass requests).
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    return module.startswith("curl_cffi") and name in (
        "Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError",
        "DNSError", "SSLError", "ChunkedEncodingError", "IncompleteRead")


def is_blocked_error(exc) -> bool:
    """True bila kegagalan berasal dari bot-protection (403/challenge)."""
    return isinstance(exc, BlockscoutBlocked) or _status_code(exc) in BLOCKED_STATUS


def _config_pro_keys() -> list[str]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            cfg = json.load(handle) or {}
    except Exception:  # noqa: BLE001 - config opsional
        return []
    return merge_helius_keys(*(cfg.get(name) for name in _PRO_KEY_CONFIG))


def _secrets_pro_keys() -> list[str]:
    try:
        import streamlit as st
        values = []
        for name in _PRO_KEY_CONFIG + _PRO_KEY_ENV:
            if name in st.secrets:
                values.append(st.secrets[name])
        return merge_helius_keys(*values)
    except Exception:  # noqa: BLE001 - di luar Streamlit / tanpa secrets
        return []


def get_pro_api_keys() -> list[str]:
    """Semua key PRO API (``proapi_…``), urut & tanpa duplikat.

    Sumber digabung (bukan saling menimpa) — env ``BLOCKSCOUT_API_KEY`` /
    ``BLOCKSCOUT_API_KEYS`` (koma/baris baru) / ``BLOCKSCOUT_PRO_API_KEY``,
    lalu ``blockscout_api_key`` / ``blockscout_api_keys`` di config.json, lalu
    Streamlit secrets dengan nama-nama yang sama. Urutan ini menentukan
    label ``key#1``, ``key#2``, … di log/UI. Kosong = jalur publik saja.
    Key **tidak pernah** ditulis ke URL, log, atau pesan error.
    """
    return merge_helius_keys(
        *(os.environ.get(name) for name in _PRO_KEY_ENV),
        _config_pro_keys(),
        _secrets_pro_keys(),
    )


def get_pro_api_key() -> str:
    """Key pertama dari :func:`get_pro_api_keys` (kompatibilitas)."""
    keys = get_pro_api_keys()
    return keys[0] if keys else ""


def pro_keys_configured() -> bool:
    """True bila minimal satu key PRO API terpasang."""
    return bool(get_pro_api_keys())


class _ProKeyPool:
    """Round-robin + parkir sementara untuk sekumpulan key PRO API.

    Aman dipakai dari beberapa thread (``scan_watchlist`` memakai
    ThreadPool). State hanya in-memory: proses cron yang baru mulai dari
    nol (paling banter satu request probe per key yang tadinya diparkir).
    """

    def __init__(self, keys) -> None:
        self.keys: tuple[str, ...] = tuple(keys)
        self._lock = threading.Lock()
        self._cursor = 0
        self._parked: dict[str, tuple[float, int, str]] = {}
        self._credits: dict[str, int] = {}
        self._rps_left: dict[str, int] = {}
        self._used: dict[str, int] = {}
        self._warned: set[str] = set()

    # -- identitas tanpa membocorkan key ----------------------------------
    def label(self, key: str) -> str:
        try:
            return f"key#{self.keys.index(key) + 1}"
        except ValueError:
            return "key#?"

    # -- pemilihan key ------------------------------------------------------
    def candidates(self) -> list[str]:
        """Key yang boleh dipakai sekarang, mulai dari giliran round-robin."""
        now = time.time()
        with self._lock:
            active = []
            for key in self.keys:
                parked = self._parked.get(key)
                if parked and parked[0] > now:
                    continue
                if parked:
                    del self._parked[key]   # masa parkir habis → dicoba lagi
                active.append(key)
            if not active:
                return []
            # Giliran dihitung di antara key yang aktif saja supaya beban
            # tetap rata walau sebagian key sedang diparkir.
            start = self._cursor % len(active)
            self._cursor += 1
            return active[start:] + active[:start]

    def park(self, key: str, status: int, response=None, detail: str = "") -> None:
        seconds = float(PRO_PARK_SEC.get(int(status), 300.0))
        if int(status) == 429:
            reset_ms = _header_int(response, "x-ratelimit-reset")
            if reset_ms and reset_ms > 0:
                seconds = min(PRO_PARK_429_MAX_SEC, max(0.5, reset_ms / 1000.0))
        with self._lock:
            self._parked[key] = (time.time() + seconds, int(status), str(detail or ""))
            if int(status) == 402:
                self._credits[key] = 0

    def note_success(self, key: str, response) -> None:
        credits = _header_int(response, "x-credits-remaining")
        rps_left = _header_int(response, "x-ratelimit-remaining")
        with self._lock:
            self._used[key] = self._used.get(key, 0) + 1
            if credits is not None and credits >= 0:
                self._credits[key] = credits
            if rps_left is not None and rps_left >= 0:
                self._rps_left[key] = rps_left

    def warn_once(self, key: str) -> bool:
        """True hanya pada peringatan pertama untuk key ini (log tidak banjir)."""
        with self._lock:
            if key in self._warned:
                return False
            self._warned.add(key)
            return True

    # -- pelaporan ----------------------------------------------------------
    def status(self) -> list[dict]:
        now = time.time()
        with self._lock:
            rows = []
            for key in self.keys:
                parked = self._parked.get(key)
                active = not (parked and parked[0] > now)
                rows.append({
                    "label": self.label(key),
                    "active": active,
                    "parked_status": None if active else parked[1],
                    "parked_detail": "" if active else parked[2],
                    "parked_for_sec": 0 if active else max(0, int(parked[0] - now)),
                    "credits_remaining": self._credits.get(key),
                    "requests": self._used.get(key, 0),
                })
            return rows

    def summary(self) -> str:
        rows = self.status()
        if not rows:
            return ""
        parts = []
        for row in rows:
            if row["active"]:
                credits = row["credits_remaining"]
                note = (f"sisa {credits:,} kredit" if credits is not None
                        else "siap")
                if row["requests"]:
                    note += f", {row['requests']} req"
            else:
                mins = -(-row["parked_for_sec"] // 60)
                reason = {401: "ditolak", 403: "ditolak", 402: "kredit habis",
                          429: "RPS"}.get(row["parked_status"],
                                          str(row["parked_status"]))
                note = f"parkir {row['parked_status']} {reason} ({mins} mnt)"
            parts.append(f"{row['label']} {note}")
        return " · ".join(parts)


_PRO_POOL: _ProKeyPool | None = None
_PRO_POOL_LOCK = threading.Lock()


def _pro_pool() -> _ProKeyPool:
    """Pool key aktif; dibangun ulang bila daftar key berubah (secrets/env)."""
    global _PRO_POOL
    keys = tuple(get_pro_api_keys())
    with _PRO_POOL_LOCK:
        if _PRO_POOL is None or _PRO_POOL.keys != keys:
            _PRO_POOL = _ProKeyPool(keys)
        return _PRO_POOL


def reset_pro_key_pool() -> None:
    """Lupakan status parkir/kredit semua key (test, tombol refresh)."""
    global _PRO_POOL
    with _PRO_POOL_LOCK:
        _PRO_POOL = None


def pro_key_status() -> list[dict]:
    """Status tiap key PRO (label ``key#N``, aktif/parkir, sisa kredit) — tanpa key."""
    return _pro_pool().status()


def pro_key_summary() -> str:
    """Satu baris ringkasan pool key untuk log cron/UI; ``""`` bila tanpa key."""
    pool = _pro_pool()
    if not pool.keys:
        return ""
    return f"Blockscout PRO API: {len(pool.keys)} key · {pool.summary()}"


def _header_int(response, name: str) -> int | None:
    try:
        headers = getattr(response, "headers", None) or {}
        for key, value in dict(headers).items():
            if str(key).lower() == name:
                return int(float(str(value).strip()))
    except Exception:  # noqa: BLE001 - header hanya pelengkap
        return None
    return None


def _pro_url(url: str) -> str:
    """Padanan PRO API dari URL instance publik (path identik)."""
    if url.startswith(BLOCKSCOUT_PRO_CHAIN_BASE):
        return url
    if url.startswith(BLOCKSCOUT_BASE):
        return BLOCKSCOUT_PRO_CHAIN_BASE + url[len(BLOCKSCOUT_BASE):]
    return url


def _looks_like_challenge(response) -> bool:
    """Deteksi halaman challenge Cloudflare (HTML) yang menyamar 403/503."""
    try:
        headers = {str(k).lower(): str(v)
                   for k, v in dict(getattr(response, "headers", {}) or {}).items()}
    except Exception:  # noqa: BLE001
        headers = {}
    if headers.get("cf-mitigated"):
        return True
    try:
        head = (getattr(response, "text", None) or "")[:600].lower()
    except Exception:  # noqa: BLE001
        head = ""
    return "just a moment" in head or "cf-chl" in head or "_cf_chl_opt" in head


def _describe_block(response) -> str:
    parts = []
    try:
        headers = {str(k).lower(): str(v)
                   for k, v in dict(getattr(response, "headers", {}) or {}).items()}
    except Exception:  # noqa: BLE001
        headers = {}
    if headers.get("cf-mitigated"):
        parts.append(f"cf-mitigated={headers['cf-mitigated']}")
    if "cloudflare" in (headers.get("server") or "").lower():
        parts.append("Cloudflare")
    return " ".join(parts)


def _status_of(response) -> int:
    """``status_code`` sebagai int; 0 bila tidak ada/bukan angka (mis. stub)."""
    value = getattr(response, "status_code", None)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _raise_for_status(response, url: str) -> None:
    """``raise_for_status`` yang membedakan 403 bot-protection dari error lain.

    403 (atau 503 berbadan halaman challenge) → :class:`BlockscoutBlocked`;
    4xx/5xx lain → ``requests.exceptions.HTTPError`` dengan ``response``
    terpasang (supaya :func:`is_transient_error` bisa membaca statusnya).
    Response tanpa ``status_code`` numerik (stub/test) diserahkan ke
    ``raise_for_status()`` miliknya sendiri.
    """
    status = _status_of(response)
    if not status:
        raiser = getattr(response, "raise_for_status", None)
        if callable(raiser):
            raiser()
        return
    if status in BLOCKED_STATUS or (status == 503 and _looks_like_challenge(response)):
        raise BlockscoutBlocked(url, _describe_block(response))
    if status >= 400:
        raise requests.exceptions.HTTPError(
            f"{status} untuk {url.split('?', 1)[0]}", response=response)


def _pro_get(url: str, params: dict | None, key: str, timeout: int,
             key_label: str = "") -> object:
    """Satu GET ke PRO API dengan satu key. Response 2xx atau melempar.

    Status key/kuota/rute (:data:`PRO_FALLBACK_STATUS`) dilempar sebagai
    :class:`ProApiError` supaya :func:`_pro_round` bisa memutuskan: parkir
    key & coba key lain (401/402/403/429) atau langsung ke publik (404).
    """
    headers = {"accept": BROWSER_HEADERS["accept"],
               "authorization": f"Bearer {key}",
               "user-agent": "wallet-depth/robinhood-holders"}
    response = requests.get(url, params=params, headers=headers,
                            timeout=timeout)
    status = _status_of(response)
    if status in PRO_FALLBACK_STATUS:
        detail = ""
        try:
            detail = str((response.json() or {}).get("error") or "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise ProApiError(status, detail, response, key_label)
    _raise_for_status(response, url)
    return response


def _pro_round(pool: _ProKeyPool, url: str, params: dict | None,
               timeout: int) -> tuple[object | None, Exception | None]:
    """Satu putaran PRO API lewat key yang tersedia → ``(response, error)``.

    Key dicoba mulai dari giliran round-robin; 401/402/403/429 memarkir key
    itu dan lanjut ke key berikutnya **dalam request yang sama**. Error lain
    (404 rute, 5xx, timeout) dikembalikan apa adanya — pemanggil yang
    memutuskan retry/backoff atau jatuh ke instance publik.
    """
    candidates = pool.candidates()
    if not candidates:
        _log_all_keys_parked(pool)
        return None, ProKeysParked(
            f"semua {len(pool.keys)} key PRO diparkir ({pool.summary()})")
    last: Exception | None = None
    for key in candidates:
        label = pool.label(key)
        try:
            response = _pro_get(_pro_url(url), params, key, timeout, label)
        except ProApiError as exc:
            last = exc
            if exc.status in PRO_ROTATE_STATUS:
                pool.park(key, exc.status, exc.response, exc.detail)
                if exc.status in (401, 402, 403) and pool.warn_once(key):
                    print(f"WARN: Blockscout PRO API {label} {exc.status} "
                          f"{exc.detail or ''} — key diparkir "
                          f"{int(PRO_PARK_SEC.get(exc.status, 300) // 60)} mnt",
                          file=sys.stderr)
                _log_key_parked(label, exc.status, exc.detail)
                continue
            return None, exc
        except Exception as exc:  # noqa: BLE001 - jaringan/5xx: retry di luar
            return None, exc
        pool.note_success(key, response)
        try:
            response.blockscout_route = ROUTE_PRO
            response.blockscout_key = label
        except Exception:  # noqa: BLE001 - atribut hanya pelengkap
            pass
        return response, None
    return None, last


def _curl_requests():
    """Modul ``curl_cffi.requests`` bila terpasang & bisa dipakai, else None.

    Dipisah supaya test bisa mematikannya (``mock.patch.object(rh,
    "_curl_requests", return_value=None)``) dan supaya install curl_cffi yang
    rusak tidak menggagalkan fallback ``requests``.
    """
    try:
        from curl_cffi import requests as cr
        return cr
    except Exception:  # noqa: BLE001 - opsional
        return None


def _public_get(url: str, params: dict | None, timeout: int):
    """GET ke instance publik: TLS browser (curl_cffi) dulu, lalu ``requests``.

    Profil ``impersonate`` dirotasi saat 403 — Cloudflare sering menolak satu
    JA3 dan menerima yang lain. Baru bila **semua** profil dan ``requests``
    biasa ditolak, :class:`BlockscoutBlocked` dilempar. Kegagalan runtime
    curl_cffi (profil tidak dikenal, TLS reset) tidak menghentikan fallback.
    """
    blocked: BlockscoutBlocked | None = None
    cr = _curl_requests()
    if cr is not None:
        headers = {k: v for k, v in BROWSER_HEADERS.items()
                   if k.lower() not in _IMPERSONATE_OWNED_HEADERS}
        for profile in BLOCKSCOUT_IMPERSONATE:
            try:
                response = cr.get(url, params=params, headers=headers,
                                  impersonate=profile, timeout=timeout)
            except Exception:  # noqa: BLE001 - profil lain / requests biasa
                continue
            try:
                _raise_for_status(response, url)
            except BlockscoutBlocked as exc:
                blocked = exc
                continue
            return response
    # ``requests`` biasa = percobaan terakhir; error-nya yang dilaporkan
    # (kecuali sudah jelas kena bot-protection di profil browser).
    try:
        response = requests.get(url, params=params, headers=BROWSER_HEADERS,
                                timeout=timeout)
    except Exception:
        if blocked is not None:
            raise blocked
        raise
    try:
        _raise_for_status(response, url)
    except BlockscoutBlocked:
        raise
    except Exception:
        if blocked is not None:
            raise blocked
        raise
    return response


def _blockscout_get(url: str, *, params: dict | None = None,
                    retries: int = RETRY_ATTEMPTS, timeout: int = 25):
    """GET ke Blockscout: **PRO API (bila ada key) → instance publik**.

    ``url`` selalu ditulis sebagai URL instance publik; padanan PRO-nya
    dibentuk otomatis (host + ``/4663`` prefiks, path sama). Response yang
    dikembalikan diberi atribut ``blockscout_route`` (``"pro"`` /
    ``"public"``) untuk pelaporan ``source``.

    Kegagalan sementara (429/5xx/timeout) diulang ``retries`` kali dengan
    jeda exponential (``RETRY_BACKOFF_SEC * 2^attempt``); 403 bot-protection
    (:class:`BlockscoutBlocked`) dan error lain langsung dilempar supaya
    caller bisa fallback ke jalur data berikutnya.
    """
    attempts = max(0, int(retries))
    pool = _pro_pool()
    last_exc: Exception | None = None
    for attempt in range(attempts + 1):
        pro_exc: Exception | None = None
        if pool.keys:
            response, pro_exc = _pro_round(pool, url, params, timeout)
            if response is not None:
                return response
            if pro_exc is not None and is_transient_error(pro_exc) \
                    and attempt < attempts:
                last_exc = pro_exc
                time.sleep(RETRY_BACKOFF_SEC * (2 ** attempt))
                continue
        try:
            response = _public_get(url, params, timeout)
            try:
                response.blockscout_route = ROUTE_PUBLIC
                response.blockscout_key = ""
            except Exception:  # noqa: BLE001
                pass
            return response
        except Exception as exc:  # noqa: BLE001 - jenis error ditentukan caller
            last_exc = exc
            if isinstance(exc, BlockscoutBlocked) and pro_exc is not None:
                # Dua-duanya gagal: sebut alasan PRO juga supaya key yang
                # salah/kuota habis tidak tersamar di balik 403 publik —
                # dan petunjuknya bukan lagi "pasang key" (key sudah ada).
                last_exc = BlockscoutBlocked(
                    url, f"{exc.detail + '; ' if exc.detail else ''}"
                         f"PRO: {pro_exc}",
                    hint=BlockscoutBlocked.HINT_KEYS_FAILED)
            if attempt >= attempts or not is_transient_error(exc):
                if isinstance(last_exc, BlockscoutBlocked):
                    _log_blocked(last_exc)
                raise last_exc
            time.sleep(RETRY_BACKOFF_SEC * (2 ** attempt))
    raise last_exc  # pragma: no cover - loop selalu return/raise


def _route_of(response) -> str:
    return str(getattr(response, "blockscout_route", "") or "")


# Rute request Blockscout terakhir yang sukses **di thread ini** —
# ``fetch_holders`` (dipanggil paralel oleh ``scan_watchlist``) membacanya
# untuk melabeli ``source`` (``blockscout-csv@pro``). Thread-local supaya
# worker yang berbeda tidak saling menimpa.
_ROUTE_STATE = threading.local()


def _remember_route(response) -> None:
    route = _route_of(response)
    if route:
        _ROUTE_STATE.last = route
        _ROUTE_STATE.last_key = str(
            getattr(response, "blockscout_key", "") or "")


def last_route() -> str:
    """Rute (``"pro"``/``"public"``) request Blockscout sukses terakhir."""
    return str(getattr(_ROUTE_STATE, "last", "") or "")


def last_key_label() -> str:
    """Label key PRO (``key#N``) request sukses terakhir; ``""`` bila publik."""
    return str(getattr(_ROUTE_STATE, "last_key", "") or "")


def source_with_route(source: str, route: str | None = None) -> str:
    """``blockscout-csv`` + rute → ``blockscout-csv@pro`` (tanpa rute: apa adanya)."""
    base = str(source or "")
    route = str(route if route is not None else last_route())
    if not base or not route or "@" in base or base.endswith("(fail)"):
        return base
    return f"{base}@{route}"


def source_base(source: str) -> str:
    """Kebalikan :func:`source_with_route`: buang akhiran ``@pro``/``@public``."""
    return str(source or "").split("@", 1)[0]


ROUTE_LABELS = {ROUTE_PRO: "PRO API", ROUTE_PUBLIC: "instance publik"}


def route_label(source: str) -> str:
    """Label rute untuk UI dari ``source`` (``…@pro`` → ``"PRO API"``; else ``""``)."""
    _, _, route = str(source or "").partition("@")
    return ROUTE_LABELS.get(route.strip().lower(), "")


def _jsjson(params: dict, *, retries: int = RETRY_ATTEMPTS,
            timeout: int = 25) -> dict:
    """GET JSON endpoint legacy ``/api?module=…&action=…`` (PRO → publik)."""
    response = _blockscout_get(BLOCKSCOUT_API, params=params,
                               retries=retries, timeout=timeout)
    _remember_route(response)
    return response.json() or {}


def _http_get(url: str, *, params: dict | None = None,
              retries: int = RETRY_ATTEMPTS, timeout: int = 25):
    """GET mentah (REST v2 + CSV export) lewat :func:`_blockscout_get`.

    Response dikembalikan apa adanya supaya caller bisa membaca ``.json()``
    maupun ``.text`` (CSV) dan atribut ``blockscout_route``.
    """
    response = _blockscout_get(url, params=params, retries=retries,
                               timeout=timeout)
    _remember_route(response)
    return response


def normalize_address(address: str) -> str:
    """Trim plus lower-case ``0x`` EVM address; Solana left intact."""
    ca = str(address or "").strip()
    if ca.lower().startswith("0x") and len(ca) == 42:
        return ca.lower()
    return ca


def is_robinhood_address(address: str) -> bool:
    """True untuk address EVM 0x + 40 hex (Robinhood Chain)."""
    return bool(_EVM_ADDRESS_RE.fullmatch(str(address or "").strip()))


def fetch_token_info(ca: str) -> dict:
    """``{name, symbol, decimals, total_supply}`` dari Blockscout.

    Blockscout menjawab dengan ``status: "0"`` + ``message`` untuk request
    yang ditolak (rate limit, token belum di-index). payload seperti itu dulu
    jatuh diam-diam ke ``decimals: -1`` lalu membuat seluruh scan holder
    pulang dengan 0 wallet tanpa keterangan — jadi sekarang di-lempar;
    ``analyze_token`` / ``scan_watchlist`` sudah menangkap exception itu dan
    menuliskan error provider di log.
    """
    payload = _jsjson({
        "module": "token",
        "action": "getToken",
        "contractaddress": normalize_address(ca),
    })
    status = str(payload.get("status") or "").strip()
    if status not in ("1", ""):
        raise RuntimeError(str(payload.get("message")
                               or "Blockscout getToken menolak request"))
    result = payload.get("result") if isinstance(payload.get("result"), dict) \
        else {}
    decimals = _int(result.get("decimals"), -1)
    supply_raw = _float(result.get("totalSupply"), None)
    return {
        "name": str(result.get("name") or "?"),
        "symbol": str(result.get("symbol") or "?"),
        "decimals": decimals,
        "total_supply": (supply_raw / (10.0 ** decimals)) if (
            decimals is not None and decimals >= 0 and supply_raw is not None
        ) else None,
        "type": str(result.get("type") or "ERC-20"),
    }


def clear_holder_cache() -> None:
    """Kosongkan cache holder in-memory + status parkir key PRO (test/refresh)."""
    _HOLDER_CACHE.clear()
    reset_pro_key_pool()


def fetch_holders_count(ca: str) -> int:
    """Jumlah holder on-chain via ``/api/v2/tokens/<CA>/counters``.

    Dipakai sebagai sanity-check: kalau daftar yang berhasil ditarik jauh
    lebih pendek daripada angka ini, hasilnya ditandai ``truncated``.
    Mengembalikan 0 kalau endpoint tidak menjawab (bukan error fatal).
    """
    try:
        payload = _http_get(
            f"{BLOCKSCOUT_V2}/tokens/{normalize_address(ca)}/counters",
            timeout=20).json() or {}
    except Exception:  # noqa: BLE001 - counters hanya pelengkap
        return 0
    return _int(payload.get("token_holders_count"), 0)


def _holder_row(address: str, balance: float, price_usd: float,
                supply: float, pools: set, *, is_contract: bool = False,
                label: str = "") -> dict:
    """Bentuk baris holder yang dipakai classify_holders/wallet_depth."""
    addr_l = str(address or "").strip().lower()
    is_pool = bool(is_contract) or _is_pool_address(addr_l, pools)
    return {
        "address": addr_l,
        "account_address": addr_l,
        "balance": balance,
        "usd_value": balance * price_usd if price_usd > 0 else 0.0,
        # fraksi 0-1 (bukan persen) — holder_analysis yang mengalikan 100
        "amount_pct": (balance / supply) if supply > 0 else 0.0,
        "is_wallet": not is_pool,
        "is_new": False,
        "is_suspicious": False,
        "start_holding_at": None,
        "last_active_at": None,
        "netflow_usd": 0.0,
        "current_buy_amount": 0.0,
        "current_sell_amount": 0.0,
        "current_transfer_in": 0.0,
        "current_transfer_out": 0.0,
        "wallet_tag": label,
        "tags": [label] if label else [],
        "maker_token_tags": [],
    }


def fetch_holders_csv(ca: str, *, price_usd: float = 0.0,
                      supply: float = 0.0, pools: set | None = None,
                      max_wallets: int | None = None) -> list[dict]:
    """Seluruh holder lewat CSV export Blockscout — **satu request, tanpa paginasi**.

    ``GET /api/v2/tokens/<CA>/holders/csv`` membalas ``text/csv`` dengan
    header ``HolderAddress,Balance`` dan **balance yang sudah dibagi
    decimals**, jadi tidak perlu ``10**decimals`` lagi. Ini jalur paling
    lengkap sekaligus paling murah: token dengan 10 ribu holder pun cukup
    satu panggilan (instance ini sinkron, lihat ``/api/v2/config/csv-export``).

    Melempar exception kalau response bukan CSV holder yang valid supaya
    :func:`fetch_holders` bisa turun ke jalur v2.
    """
    pools = pools or set()
    response = _http_get(f"{BLOCKSCOUT_V2}/tokens/{normalize_address(ca)}"
                         "/holders/csv", timeout=CSV_TIMEOUT)
    text = response.text or ""
    if text.lstrip().startswith("<") or "HolderAddress" not in text[:200]:
        raise RuntimeError("CSV export Blockscout tidak mengembalikan tabel holder")
    rows: list[dict] = []
    limit = int(max_wallets) if max_wallets else 0
    for row in csv.DictReader(io.StringIO(text)):
        address = (row.get("HolderAddress") or "").strip()
        if not is_robinhood_address(address):
            continue
        balance = _float(row.get("Balance"), 0.0)
        if balance <= 0:
            continue
        rows.append(_holder_row(address, balance, price_usd, supply, pools))
        if limit and len(rows) >= limit:
            break
    if not rows:
        raise RuntimeError("CSV export Blockscout kosong")
    rows.sort(key=lambda item: item["balance"], reverse=True)
    return rows


def fetch_holders_v2(ca: str, *, price_usd: float = 0.0, supply: float = 0.0,
                     decimals: int = 18, pools: set | None = None,
                     max_wallets: int | None = None) -> list[dict]:
    """Holder via REST v2 keyset pagination (50/halaman, cursor tanpa batas).

    Lebih lambat daripada CSV tetapi membawa metadata address
    (``is_contract``, ``name``) sehingga LP/kontrak bisa ditandai otomatis —
    berguna untuk token yang tidak punya pair terdaftar di DexScreener.
    """
    pools = pools or set()
    scale = 10.0 ** int(decimals if decimals is not None and decimals >= 0 else 18)
    limit = int(max_wallets) if max_wallets else 0
    url = f"{BLOCKSCOUT_V2}/tokens/{normalize_address(ca)}/holders"
    params: dict = {"items_count": V2_PAGE_SIZE}
    rows: list[dict] = []
    for _ in range(V2_PAGE_CAP):
        payload = _http_get(url, params=params, timeout=30).json() or {}
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            info = item.get("address") if isinstance(item.get("address"), dict) \
                else {}
            address = str(info.get("hash") or "").strip()
            if not is_robinhood_address(address):
                continue
            balance = _float(item.get("value"), 0.0) / scale
            if balance <= 0:
                continue
            rows.append(_holder_row(
                address, balance, price_usd, supply, pools,
                is_contract=bool(info.get("is_contract")),
                label=str(info.get("name") or ""),
            ))
        if limit and len(rows) >= limit:
            rows = rows[:limit]
            break
        cursor = payload.get("next_page_params")
        if not isinstance(cursor, dict) or not cursor:
            break
        params = dict(cursor)
        params.setdefault("items_count", V2_PAGE_SIZE)
    return rows


def _is_pool_address(address: str, pools: set) -> bool:
    return str(address or "").lower() in pools


def fetch_holders_rpc(ca: str, *, price_usd: float = 0.0, supply: float = 0.0,
                      decimals: int = 18, pools: set | None = None,
                      max_wallets: int | None = None) -> tuple[list[dict], int, bool, object]:
    """Holder via legacy RPC ``getTokenHolders`` — fallback terakhir.

    ``offset`` **wajib <= 400**; nilai lebih besar (versi lama memakai
    1000) dijawab ``{"status":"0","message":"Something went wrong."}``
    sehingga scan pulang tanpa satu pun holder. Halaman setelah data
    habis membalas ``result: []`` — itulah kondisi berhenti.

    Return ``(rows, pages, truncated, error)`` — ``error`` berupa string,
    atau instance :class:`BlockscoutBlocked` bila request ditolak 403.
    """
    pools = pools or set()
    scale = 10.0 ** int(decimals if decimals is not None and decimals >= 0 else 18)
    limit = int(max_wallets or DEFAULT_MAX_WALLETS)
    seen: dict[str, dict] = {}
    pages = 0
    truncated = False
    error = ""
    page = 1
    while True:
        try:
            payload = _jsjson({
                "module": "token",
                "action": "getTokenHolders",
                "contractaddress": ca,
                "page": page,
                "offset": HOLDER_PAGE_SIZE,
            })
        except Exception as exc:  # noqa: BLE001 - provider outage -> clean stop
            # BlockscoutBlocked dikembalikan apa adanya (bukan str) supaya
            # fetch_holders bisa mengenali 403 bot-protection dari jalur ini.
            error = exc if isinstance(exc, BlockscoutBlocked) else str(exc)
            break
        if str(payload.get("status") or "").strip() not in ("1", ""):
            error = str(payload.get("message") or "Blockscout error")
            break
        rows = payload.get("result") or []
        if not isinstance(rows, list):
            error = "Blockscout return holder tidak valid"
            break
        if not rows:
            break
        pages += 1
        for raw in rows:
            if len(seen) >= limit:
                truncated = True
                break
            if not isinstance(raw, dict):
                continue
            addr = normalize_address(raw.get("address"))
            if not addr:
                continue
            balance = _float(raw.get("value")) / scale
            if balance <= 0:
                continue
            seen.setdefault(addr, _holder_row(addr, balance, price_usd,
                                              supply, pools))
        if len(seen) >= limit:
            truncated = True
            break
        if len(rows) < HOLDER_PAGE_SIZE:
            break
        if pages >= HOLDER_PAGE_CAP:
            truncated = True
            break
        # Jeda antar page — Blockscout publik rate-limit-nya cukup keras.
        time.sleep(PAGE_SLEEP_SEC)
        page += 1
    return list(seen.values()), pages, truncated or bool(error), error


def fetch_holders(ca: str, *, max_wallets: int | None = None,
                  price_usd: float = 0.0, decimals: int | None = None,
                  total_supply: float | None = None) -> dict:
    """Ambil **seluruh** holder ERC-20 di Robinhood Chain dari Blockscout.

    Tiga jalur dicoba berurutan, berhenti pada yang pertama berhasil:

    1. **CSV export** (``source: "blockscout-csv"``) — satu request,
       tanpa paginasi, balance sudah ter-scale decimals. Ini jalur
       "tanpa limit" yang dipakai untuk hampir semua token.
    2. **REST v2 keyset** (``"blockscout-v2"``) — cursor 50/halaman,
       dipakai bila CSV ditolak atau hasilnya jelas terpotong
       (mis. token dengan lebih dari 10.000 holder).
    3. **Legacy RPC** (``"blockscout-rpc"``) — ``offset=400``.

    GMGN **tidak lagi dipakai**: chain 4663 tidak di-index di sana dan
    endpoint holder-nya selalu membalas list kosong.

    Setiap request lewat :func:`_blockscout_get` (PRO API bila ada
    ``BLOCKSCOUT_API_KEY`` → instance publik dengan TLS browser). ``source``
    diberi akhiran rute yang benar-benar dipakai — ``blockscout-csv@pro`` /
    ``blockscout-csv@public`` — dan bila semua jalur ditolak bot-protection
    (403), ``error`` menyebutkan itu satu kali dengan petunjuk key, bukan
    tiga baris ``403 Client Error: Forbidden for url: …``.

    Return shape: ``{"holders": [...], "pages", "truncated", "fetched",
    "analyzed_at", "source", "decimals", "error", "holders_count",
    "blocked", "pro_key", "pro_keys"}``.
    """
    ca = normalize_address(ca)
    if not ca or price_usd <= 0:
        return {"holders": [], "pages": 0, "truncated": False, "fetched": 0,
                "analyzed_at": int(time.time()), "source": SOURCE_CSV,
                "decimals": decimals, "error": "price/address empty",
                "blocked": False, "pro_key": "",
                "pro_keys": len(get_pro_api_keys())}

    cache_key = f"{ca}:{int(max_wallets or 0)}:{round(float(price_usd), 10)}"
    cached = _HOLDER_CACHE.get(cache_key)
    if cached and (time.time() - cached.get("analyzed_at", 0)) < _HOLDER_CACHE_TTL:
        return dict(cached)
    _ROUTE_STATE.last = ""
    _ROUTE_STATE.last_key = ""

    blocked_hits: list[BlockscoutBlocked] = []
    errors: list[str] = []

    def _note(label: str, exc: Exception) -> None:
        # 403 bot-protection dicatat sekali di akhir (bukan per jalur) supaya
        # pesan ke user tidak berupa tiga URL 403 yang sama.
        if isinstance(exc, BlockscoutBlocked):
            blocked_hits.append(exc)
            return
        errors.append(f"{label}: {exc}")

    supply = float(total_supply or 0.0)
    if decimals is None or decimals < 0 or supply <= 0:
        try:
            info = fetch_token_info(ca)
        except Exception as exc:  # noqa: BLE001 - decimals wajib untuk v2/rpc
            info = {}
            _note("getToken", exc)
        if decimals is None or decimals < 0:
            decimals = info.get("decimals")
        if supply <= 0:
            supply = float(info.get("total_supply") or 0.0)

    limit = int(max_wallets or DEFAULT_MAX_WALLETS)
    pools: set = set()
    onchain_count = fetch_holders_count(ca)

    # ---- 1) CSV export: satu request untuk seluruh daftar --------------------
    holders: list[dict] = []
    source = SOURCE_CSV
    pages = 1
    truncated = False
    try:
        holders = fetch_holders_csv(ca, price_usd=price_usd, supply=supply,
                                    pools=pools, max_wallets=limit)
    except Exception as exc:  # noqa: BLE001 - lanjut ke jalur berikutnya
        _note("csv", exc)
        holders = []

    # CSV instance ini sinkron dengan plafon 10.000 baris. Kalau counters
    # bilang holder-nya lebih banyak (dan user memang minta lebih), daftar
    # CSV pasti terpotong -> lengkapi lewat jalur paginasi.
    csv_incomplete = bool(holders and (
        onchain_count > len(holders)
        or (not onchain_count and len(holders) >= min(limit, CSV_EXPORT_LIMIT))))
    truncated = csv_incomplete
    csv_capped = csv_incomplete and limit > len(holders)
    if csv_capped:
        errors.append(f"csv terpotong {len(holders)}/{onchain_count or '?'}")

    # ---- 2) Legacy RPC: 400 baris/halaman, 8x lebih hemat daripada v2 -------
    # Untuk token besar (85k holder) v2 butuh ~1.700 request sedangkan RPC
    # hanya ~213, jadi RPC yang dicoba lebih dulu saat CSV tidak cukup.
    if (not holders or csv_capped) and decimals is not None and decimals >= 0:
        rpc_rows, rpc_pages, rpc_trunc, rpc_err = fetch_holders_rpc(
            ca, price_usd=price_usd, supply=supply, decimals=_int(decimals, 18),
            pools=pools, max_wallets=max_wallets)
        if rpc_err:
            if isinstance(rpc_err, BlockscoutBlocked):
                _note("rpc", rpc_err)
            else:
                errors.append(f"rpc: {rpc_err}")
        if len(rpc_rows) > len(holders):
            holders = rpc_rows
            source = SOURCE_RPC
            pages = rpc_pages
            truncated = rpc_trunc

    # ---- 3) REST v2 keyset: paling lambat, tapi cursor-nya tak berbatas ------
    if not holders or (csv_capped and source == SOURCE_CSV):
        try:
            v2_rows = fetch_holders_v2(
                ca, price_usd=price_usd, supply=supply,
                decimals=_int(decimals, 18), pools=pools,
                max_wallets=max_wallets)
        except Exception as exc:  # noqa: BLE001
            _note("v2", exc)
            v2_rows = []
        if len(v2_rows) > len(holders):
            holders = v2_rows
            source = SOURCE_V2
            pages = max(1, -(-len(v2_rows) // V2_PAGE_SIZE))
            truncated = len(v2_rows) >= min(limit, V2_PAGE_CAP * V2_PAGE_SIZE)

    blocked = bool(blocked_hits) and not holders
    if blocked:
        # Satu kalimat untuk semua jalur yang kena 403 — pesan
        # BlockscoutBlocked sudah memuat path + petunjuk BLOCKSCOUT_API_KEY.
        errors.append(str(blocked_hits[0]))

    if not holders and (decimals is None or decimals < 0):
        return {
            "holders": [], "pages": 0, "truncated": False, "fetched": 0,
            "analyzed_at": int(time.time()),
            "source": f"{SOURCE_CSV}(fail)",
            "decimals": None, "holders_count": onchain_count,
            "error": "; ".join(errors) or "decimals mint tidak ditemukan",
            "blocked": blocked, "pro_key": "",
            "pro_keys": len(_pro_pool().keys),
        }

    if not holders:
        source = f"{SOURCE_CSV}(fail)"
    elif onchain_count and len(holders) < onchain_count:
        # A provider cap or failed fallback is incomplete even BELOW our limit.
        truncated = True
    if holders and truncated:
        errors.append(f"holder tidak lengkap: {len(holders)}/{onchain_count or '?'}; "
                      "dust % MC belum dapat dipakai")
    try:
        import activity_log
        short = f"{ca[:10]}…"
        if not holders:
            activity_log.error(
                "blockscout", f"fetch holder {short} GAGAL: "
                f"{'; '.join(errors)[:160] or 'tanpa detail'}")
        elif truncated:
            activity_log.warn(
                "blockscout", f"fetch holder {short}: TERPOTONG "
                f"{len(holders)}/{onchain_count or '?'} via {source} — "
                "dust % MC tidak dipakai")
        else:
            activity_log.info(
                "blockscout", f"fetch holder {short}: {len(holders):,} "
                f"wallet via {source}{' (' + last_key_label() + ')' if last_key_label() else ''}")
    except Exception:  # noqa: BLE001 - log hanya pelengkap
        pass

    result = {
        "holders": holders,
        "pages": pages if holders else 0,
        "truncated": truncated,
        "fetched": len(holders),
        "analyzed_at": int(time.time()),
        "source": source_with_route(source) if holders else source,
        "decimals": decimals,
        "holders_count": onchain_count,
        "error": "; ".join(e for e in errors if e) if not holders or truncated else "",
        "blocked": blocked,
        # Label key PRO (``key#N``) request sukses terakhir — untuk caption
        # UI/log; kosong bila lewat instance publik atau gagal. ``pro_keys``
        # = jumlah key terpasang, supaya UI tahu apakah petunjuk "pasang
        # key" masih relevan saat 403.
        "pro_key": last_key_label() if holders else "",
        "pro_keys": len(_pro_pool().keys),
    }
    if holders:
        _HOLDER_CACHE[cache_key] = dict(result)
    return result


def _mark_pools(holders: list[dict], pool_addresses) -> list[dict]:
    """Tandai address LP/pool DexScreener sebagai bukan wallet murni."""
    pools = {normalize_address(p) for p in (pool_addresses or []) if p}
    if not pools:
        return holders
    out = []
    for row in holders or []:
        if not isinstance(row, dict):
            continue
        if _is_pool_address(row.get("address"), pools):
            row = dict(row)
            row["is_wallet"] = False
            row["wallet_tag"] = "pool"
        out.append(row)
    return out


def _known_pools(market: dict | None, extra_pools=None) -> list[str]:
    pool = list((market or {}).get("pair_addresses") or [])
    pool.extend(str(p or "").strip() for p in (extra_pools or []) if p)
    return list(dict.fromkeys(pool))


def scan_token_holders(ca: str, *, max_wallets: int | None = None,
                       include_pools: bool = False) -> dict:
    """Scan on-demand holder satu token Robinhood Chain (EVM, chain 4663).

    Padanan EVM dari ``helius_holders.scan_token_holders`` untuk section
    **Scan Holder Solana / Robinhood** di halaman utama: alurnya sama —
    market (harga & marketcap) dari DexScreener
    (``chain_id=robinhood``), token info (decimals & supply) dari
    Blockscout, seluruh holder dari :func:`fetch_holders` (CSV export →
    REST v2 → legacy RPC), lalu Wallet Depth by Threshold dari
    ``solscan_holders.wallet_depth``.

    ``include_pools``: bila ``False`` (default) akun LP/pool yang dikenal
    (``pair_addresses`` DexScreener + kontrak yang ditandai Blockscout)
    **disingkirkan dari list/bucket holder** — pool AMM bisa menyerap
    puluhan persen supply dan menyesatkan bucket (sama dengan jalur
    Helius).

    Return dict — **shape-nya sama persis** dengan
    ``helius_holders.scan_token_holders`` sehingga UI Scan Holder Solana /
    Robinhood dipakai ulang tanpa cabang::

        {
          "market": {...},            # dari get_market (bisa {})
          "snapshot": {...},          # dari fetch_holders
          "depth": {...},             # dari wallet_depth
          "source": str,              # "blockscout-csv" / "blockscout-v2" / …
          "no_helius_keys": False,    # selalu False (tidak butuh key Helius)
          "scan_failed": bool,
        }
    """
    ca = normalize_address(ca)
    market = {}
    try:
        market = get_market(ca, chain_id=DEXSCREENER_CHAIN) or {}
    except Exception:  # noqa: BLE001 - market gagal, lanjut dengan nilai kosong
        market = {}
    price = float(market.get("price_usd") or 0)
    mc = float(market.get("marketcap") or 0)
    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)

    info: dict = {}
    if price > 0:
        try:
            info = fetch_token_info(ca)
        except Exception:  # noqa: BLE001 - info gagal, fetch_holders coba lagi
            info = {}
    decimals = info.get("decimals")
    supply = info.get("total_supply")

    snapshot = fetch_holders(ca, max_wallets=max_wallets, price_usd=price,
                             decimals=decimals, total_supply=supply)
    pools = _known_pools(market)
    snapshot["holders"] = _mark_pools(snapshot.get("holders") or [], pools)
    depth = wallet_depth(snapshot.get("holders") or [], mc,
                         pool_addresses=pools, include_pools=include_pools)
    symbol = str(market.get("symbol")
                 or (info or {}).get("symbol") or "?").upper()
    return {
        "mint": ca,
        "symbol": symbol,
        "market": market,
        "snapshot": snapshot,
        "depth": depth,
        "source": str(snapshot.get("source") or "robinhood"),
        "no_helius_keys": False,
        "scan_failed": bool(not snapshot.get("holders") or price <= 0),
    }


def analyze_token(ca: str, symbol: str = "?", market_cap: float = 0.0,
                  *, dust_limit: float | None = None,
                  max_wallets: int | None = None,
                  fetch_market: bool = True,
                  timeout: int = 25,
                  price_usd: float = 0.0,
                  extra_pools=None,
                  cohort_addrs=None,
                  tracked_wallet_addrs=None,
                  detail: bool = True) -> dict:
    """Analisis holder token Robinhood Chain (Blockscout: CSV → v2 → RPC).

    Menghasilkan bentuk yang sama dengan
    ``holder_analysis.analyze_token`` sehingga seluruh alur watchlist,
    holder_history, dan telegram_alerts dapat dipakai langsung.
    ``detail=False`` (scan 5 menit LP): catat dust/holder saja.
    """
    ca = normalize_address(ca)
    dust_limit = float(DUST_LIMIT_USD if dust_limit is None else dust_limit)
    max_wallets = int(max_wallets or DEFAULT_MAX_WALLETS)

    market = {}
    if fetch_market:
        try:
            market = get_market(ca, chain_id=DEXSCREENER_CHAIN) or {}
        except Exception:  # noqa: BLE001 - lanjut, token info tetap bisa
            market = {}
    mc = float(market_cap or market.get("marketcap") or 0)
    price = float(price_usd or market.get("price_usd") or 0)

    info = {}
    if price > 0:
        try:
            info = fetch_token_info(ca)
        except Exception as exc:  # noqa: BLE001
            info = {"error": str(exc), "decimals": None, "symbol": "?"}
    symbol = str(symbol or market.get("symbol") or (info or {}).get("symbol")
                 or "?").upper()
    supply = None
    if isinstance(info, dict):
        supply = info.get("total_supply")

    snapshot = fetch_holders(
        ca, max_wallets=max_wallets, price_usd=price,
        decimals=(info or {}).get("decimals"), total_supply=supply)

    pools = _known_pools(market, extra_pools)
    snapshot["holders"] = _mark_pools(snapshot.get("holders") or [], pools)
    holder_stats = classify_holders(snapshot, mc, dust_limit=dust_limit)
    # Alasan provider (rate limit, token belum di-index) dulu hilang di sini,
    # sehingga scan yang pulang dengan 0 wallet terbaca seperti hasil sungguhan
    # ("dust 0 wallet = AMAN"). Dibawa terus supaya UI + snapshot bisa jujur.
    fetch_error = str(snapshot.get("error") or "")
    if fetch_error:
        holder_stats["fetch_error"] = fetch_error
    if snapshot.get("blocked"):
        # 403 bot-protection: bukan "token ini tidak punya holder" —
        # penanda dibawa supaya cron/UI bisa membedakan dari kegagalan biasa.
        holder_stats["blocked"] = True
    # Jumlah key PRO terpasang + key yang benar-benar dipakai (``key#N``),
    # supaya pesan UI/cron tepat: "pasang key" vs "key ditolak/kredit habis".
    holder_stats["pro_keys"] = int(snapshot.get("pro_keys") or 0)
    if snapshot.get("pro_key"):
        holder_stats["pro_key"] = str(snapshot.get("pro_key"))

    try:
        from solscan_holders import wallet_depth
        holder_stats["depth"] = wallet_depth(
            snapshot.get("holders") or [], mc, pool_addresses=pools,
            include_pools=False)
    except Exception:  # noqa: BLE001 - depth pelengkap
        holder_stats.setdefault("depth", {})

    try:
        from holder_history import lookup_balances, mid_tier_stats
        holder_stats["mid"] = mid_tier_stats(
            snapshot.get("holders") or [], mc, pool_addresses=pools)
        holder_stats["cohort_now"] = lookup_balances(
            snapshot.get("holders") or [], cohort_addrs or [])
    except Exception:  # noqa: BLE001
        holder_stats.setdefault("mid", {"count": 0, "balances": {}})
        holder_stats.setdefault("cohort_now", {})

    analyzed_at = int(time.time())
    if detail:
        try:
            from telegram_alerts import build_wallet_snapshot
            holder_stats["wallet_snapshot"] = build_wallet_snapshot(
                snapshot.get("holders") or [],
                dust_pct_mc=holder_stats.get("dust_pct_mc"),
                dust_limit_usd=dust_limit,
                tracked_addresses=tracked_wallet_addrs or [],
                ts=analyzed_at,
                truncated=bool(snapshot.get("truncated")),
            )
        except Exception:  # noqa: BLE001
            holder_stats.setdefault("wallet_snapshot", {})
        try:
            from holder_chronology import build_chrono_snapshot
            holder_stats["chrono_snapshot"] = build_chrono_snapshot(
                snapshot.get("holders") or [],
                tracked_addresses=tracked_wallet_addrs or [],
                pool_addresses=pools,
                ts=analyzed_at,
                price=price,
                market_cap=mc,
                dust_pct_mc=holder_stats.get("dust_pct_mc"),
                holder_count=holder_stats.get("wallets_analyzed"),
                dust_count=holder_stats.get("dust_count"),
                truncated=bool(snapshot.get("truncated")),
            )
        except Exception:  # noqa: BLE001 - kronologi tidak boleh mematikan scan
            holder_stats.setdefault("chrono_snapshot", {})
    else:
        holder_stats["wallet_snapshot"] = {
            "ts": analyzed_at,
            "dust_pct_mc": holder_stats.get("dust_pct_mc"),
            "balances": {}, "dust": [], "wallets_seen": 0, "truncated": False,
        }

    return {
        "ca": ca,
        "symbol": symbol,
        "marketcap": mc,
        "price": price,
        "analyzed_at": analyzed_at,
        "holders": holder_stats,
        "market": {
            "price_usd": price or _float(market.get("price_usd"), 0.0),
            "marketcap": mc,
            "volume": market.get("volume") or {},
            "price_change": market.get("price_change") or {},
            "txns": market.get("txns") or {},
            "pair_addresses": pools,
            "dex": market.get("dex") or "?",
        },
    }
