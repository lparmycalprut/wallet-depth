# -*- coding: utf-8 -*-
"""Penyimpanan page **🌊 Sweep**: watchlist manual, snapshot, sinyal, statistik.

Tiga berkas:

``sweep_watchlist.json``
    Daftar mint yang dipantau — **di-commit** (user menambah manual dari UI).
``sweep_state.json``
    Snapshot per jam, riwayat sinyal + hasilnya, dan status alert — **di-commit**
    supaya statistik tidak hilang saat container Streamlit Cloud restart.
``sweep_cache.json``
    Cache HTTP (:mod:`sweep_data`) — **ephemeral**, masuk ``.gitignore``.

Streamlit Community Cloud punya filesystem ephemeral: tulisan lokal hilang tiap
redeploy. Karena itu :func:`push_json` menulis berkas state langsung ke repo
lewat GitHub Contents API — pola dan urutan token yang sama dengan
:mod:`watchlist` (Streamlit secrets → env → ``config.json``).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time

from core import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "sweep_watchlist.json")
STATE_PATH = os.path.join(BASE_DIR, "sweep_state.json")
#: ``config.json`` lokal (masuk .gitignore) — dipakai :mod:`sweep_alert` untuk
#: kredensial dan halaman ini sebagai cadangan watchlist kalau commit GitHub
#: gagal (Streamlit Cloud filesystem-nya ephemeral).
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
GITHUB_REPO = "lparmycalprut/wallet-depth"

STATE_VERSION = 1
HOUR = 3600
#: Simpan 7 hari snapshot per jam per mint.
MAX_BUCKETS_PER_MINT = 168
#: Batas riwayat sinyal yang disimpan.
MAX_SIGNALS = 1500
#: Sinyal lebih tua dari ini tidak lagi diperbarui hasilnya.
SIGNAL_TRACK_SEC = 72 * HOUR
#: Cooldown alert (detik): kelayakan jarang berubah, sweep cepat.
ELIG_COOLDOWN = 6 * HOUR
SWEEP_COOLDOWN = 30 * 60
#: Snapshot pembanding untuk mengukur inflow nyata (Δ likuiditas) tidak boleh
#: lebih tua dari ini — di luar itu selisihnya bukan lagi "inflow sweep".
NET_INFLOW_MAX_AGE = 3 * HOUR


def _now() -> int:
    return int(time.time())


def _f(value):
    """Angka float atau ``None`` (string kosong/NaN dianggap tidak ada data)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
def parse_mints(raw) -> list:
    """Normalisasi input user → daftar mint unik, urut sesuai kemunculan.

    Menerima list, atau teks dengan satu mint per baris (koma/spasi juga
    diterima) supaya textarea UI bisa langsung dioper.
    """
    # Mint Solana/EVM tidak pernah mengandung spasi, jadi koma, titik-koma,
    # dan seluruh whitespace aman dijadikan pemisah — user bisa menempel daftar
    # dalam format apa pun (satu per baris, CSV, atau dipisah spasi).
    # Komentar dibuang lebih dulu (`# …` sampai akhir baris): kalau tidak,
    # memisah berdasarkan spasi akan menyisakan kata komentarnya sebagai mint.
    def _split(text: str) -> list:
        return re.split(r"[\s,;]+", re.sub(r"#[^\n]*", " ", text or "").strip())

    if isinstance(raw, str):
        items = _split(raw)
    else:
        items = []
        for value in (raw or []):
            items.extend(_split(value) if isinstance(value, str)
                         else [str(value)])
    seen, out = set(), []
    for item in items:
        mint = str(item or "").strip()
        if not mint or mint.startswith("#") or mint in seen:
            continue
        seen.add(mint)
        out.append(mint)
    return out


def load_watchlist() -> list:
    """Daftar mint watchlist sweep (selalu list, tidak pernah melempar).

    Urutan: berkas lokal → cadangan ``config.json`` key ``sweep_watchlist``.
    Cadangan dipakai supaya daftar yang diketik di Streamlit Cloud (filesystem
    ephemeral) tetap terbaca setelah restart walau commit GitHub gagal.
    """
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):  # toleransi format lama {mint: {...}}
            return parse_mints(list(data.keys()))
        mints = parse_mints(data)
        if mints:
            return mints
    except Exception:  # noqa: BLE001 - berkas hilang = cek cadangan
        pass
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            config = json.load(handle)
        if isinstance(config, dict):
            return parse_mints(config.get("sweep_watchlist"))
    except Exception:  # noqa: BLE001 - cadangan opsional
        pass
    return []


def watchlist_message(mints) -> str:
    """Pesan commit yang konsisten antara UI dan cron."""
    return f"sweep: watchlist ({len(parse_mints(mints))} mint)"


def push_watchlist(mints) -> bool:
    """Commit watchlist ke GitHub. ``False`` = hanya tersimpan lokal.

    Di Streamlit Cloud sistem berkasnya sementara, jadi UI **wajib** memberi
    tahu kalau push gagal — kalau tidak, daftar yang diketik user akan hilang
    saat container restart tanpa peringatan apa pun.
    """
    clean = parse_mints(mints)
    return push_json("sweep_watchlist.json", clean, watchlist_message(clean))


def save_watchlist(mints, *, persist: bool = True) -> list:
    """Tulis watchlist lokal (atomik) + opsional commit ke GitHub."""
    clean = parse_mints(mints)
    atomic_write_json(WATCHLIST_PATH, clean, indent=2)
    if persist:
        push_watchlist(clean)
    return clean


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def empty_state() -> dict:
    return {"version": STATE_VERSION, "snapshots": {}, "signals": [],
            "alerts": {}, "shakeout_latched_at": {}, "updated": 0}


def load_state() -> dict:
    """State lengkap; selalu dict dengan kunci yang dijamin ada."""
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:  # noqa: BLE001
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    state = empty_state()
    for key in ("snapshots", "signals", "alerts"):
        if isinstance(data.get(key), dict) or isinstance(data.get(key), list):
            state[key] = data[key]
    if isinstance(data.get("shakeout_latched_at"), dict):
        state["shakeout_latched_at"] = data["shakeout_latched_at"]
    state["updated"] = int(data.get("updated") or 0)
    return state


def push_state(state: dict, reason: str = "") -> bool:
    """Commit state ke GitHub (dipakai UI tombol persist + cron)."""
    return push_json("sweep_state.json", state,
                     f"sweep: state {reason}".strip())


def save_state(state: dict, *, persist: bool = False, reason: str = "") -> dict:
    """Tulis state lokal (atomik) + opsional commit ke GitHub."""
    state = dict(state or {})
    # Drop legacy UI settings on the next write; thresholds are fixed in
    # sweep_screen and no longer belong to persisted state.
    state.pop("settings", None)
    state.setdefault("shakeout_latched_at", {})
    state["version"] = STATE_VERSION
    state["updated"] = _now()
    atomic_write_json(STATE_PATH, state, separators=(",", ":"))
    if persist:
        push_state(state, reason)
    return state


def fingerprint(state: dict) -> str:
    """Fingerprint kunci bucket snapshot, signal ids, dan latch shakeout permanen.

    Hanya **kunci bucket** (jam) yang masuk, bukan isinya: bucket jam berjalan
    ditimpa tiap 5 menit (harga, likuiditas, view), dan kalau isinya ikut,
    cron 5 menitan membuat ~288 commit/hari. Jadi commit hanya terjadi saat
    snapshot jam baru muncul (atau bucket lama dipangkas), sesuai
    ``docs/sweep.md``. Field ``alerts``/``updated`` yang volatil juga dikecualikan.
    Legacy settings sengaja diabaikan karena ambang dikunci di ``sweep_screen``.
    """
    import hashlib

    snapshots = (state or {}).get("snapshots") or {}
    hour_keys = {
        mint: sorted(buckets.keys()) if isinstance(buckets, dict) else None
        for mint, buckets in snapshots.items()
    }
    payload = json.dumps({
        "snapshots": hour_keys,
        "signals": [(row or {}).get("id") for row in ((state or {}).get("signals") or [])
                    if isinstance(row, dict)],
        "shakeout_latched_at": (state or {}).get("shakeout_latched_at") or {},
    }, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def prune(state: dict) -> dict:
    """Batasi ukuran state: bucket per mint dan jumlah sinyal."""
    snapshots = state.get("snapshots")
    if isinstance(snapshots, dict):
        for mint, buckets in list(snapshots.items()):
            if not isinstance(buckets, dict):
                snapshots.pop(mint, None)
                continue
            if len(buckets) > MAX_BUCKETS_PER_MINT:
                keep = sorted(buckets.keys(), key=lambda k: float(k or 0),
                              reverse=True)[:MAX_BUCKETS_PER_MINT]
                snapshots[mint] = {k: buckets[k] for k in sorted(keep)}
    signals = state.get("signals")
    if isinstance(signals, list) and len(signals) > MAX_SIGNALS:
        state["signals"] = signals[-MAX_SIGNALS:]
    return state


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------
def snapshot_row(metrics: dict, *, ts: int | None = None) -> dict:
    """Ringkas metrik → satu baris snapshot (field yang dipakai kriteria 4/5)."""
    metrics = metrics or {}
    return {
        "ts": int(ts if ts is not None else (metrics.get("ts") or _now())),
        "price": metrics.get("price_usd"),
        "liq_usd": metrics.get("liq_usd"),
        "fdv_usd": metrics.get("fdv_usd"),
        "vol_1h": metrics.get("vol_1h"),
        "buys_1h": metrics.get("buys_1h"),
        "sells_1h": metrics.get("sells_1h"),
        "liq_mc": metrics.get("liq_mc"),
        "bundler": metrics.get("bundler_rate"),
        "bot_degen": metrics.get("bot_degen_rate"),
        "entrapment": metrics.get("entrapment_rate"),
        "fresh": metrics.get("fresh_wallet_rate"),
        "top10_pct": metrics.get("top10_holder_pct"),
        "holders": metrics.get("holder_count"),
    }


def add_snapshot(state: dict, mint: str, metrics: dict,
                 *, ts: int | None = None) -> dict:
    """Simpan snapshot mint ke bucket **per jam** dan kembalikan barisnya.

    Bucket per jam (bukan per 5 menit) disengaja: cron berjalan tiap 5 menit
    sehingga snapshot 5-menit akan menulis ~288 baris/hari/mint ke dalam berkas
    yang di-commit. Bucket per jam menjaga riwayat 7 hari tetap kecil, sementara
    deteksi sweep tetap 5-menitan karena dihitung dari candle GeckoTerminal
    (bukan dari state).
    """
    row = snapshot_row(metrics, ts=ts)
    bucket = int(row["ts"] // HOUR) * HOUR
    snapshots = state.setdefault("snapshots", {})
    buckets = snapshots.setdefault(mint, {})
    buckets[str(bucket)] = row
    return row


#: Field metrik yang ikut disimpan di "view" (tampilan halaman tanpa scan ulang).
#: Sengaja daftar eksplisit: holder list / risks / candles tidak masuk state.
VIEW_METRIC_KEYS = (
    "mint", "ok", "error", "symbol", "name", "price_usd", "liq_usd", "fdv_usd",
    "market_cap_usd", "vol_1h", "vol_24h", "buys_1h", "sells_1h", "pair_address",
    "dex_id", "pool_count", "url", "pair_created_at", "lp_locked_pct",
    "mint_authority", "freeze_authority", "top10_holder_pct", "holder_count",
    "top_bundler_trader_percentage", "bundler_rate", "bot_degen_rate",
    "fresh_wallet_rate", "status_now", "holding_rate",
)
VIEW_RESULT_KEYS = (
    "checks", "passed_count", "scored_count", "required_count", "score",
    "structural_ok", "eligible", "verdict", "color", "liq_mc", "targets",
    "reference_fund_x", "turnover_x", "cohort", "cohort_gate_status",
    "cohort_gate_passed", "cohort_gate_detail", "missing",
)


def make_view(mint: str, metrics: dict, result: dict, sweep_context=None,
              *, ts: int) -> dict:
    """Bentuk tampilan satu mint yang disimpan bersama snapshot terbaru."""
    metrics = metrics or {}
    result = result or {}
    return {
        "ts": int(ts),
        "mint": mint,
        "metrics": {k: metrics[k] for k in VIEW_METRIC_KEYS if k in metrics},
        "result": {k: result[k] for k in VIEW_RESULT_KEYS if k in result},
        "sweep_context": sweep_context or None,
        "turnover_x": result.get("turnover_x"),
    }


def set_view(state: dict, mint: str, snapshot_row: dict, view: dict) -> None:
    """Pasang ``view`` di snapshot terbaru mint; view snapshot lama dibuang.

    Hanya satu view per mint yang disimpan, supaya berkas state tetap kecil.
    """
    buckets = (state.get("snapshots") or {}).get(mint)
    if not isinstance(buckets, dict) or not isinstance(snapshot_row, dict):
        return
    for row in buckets.values():
        if isinstance(row, dict) and row is not snapshot_row:
            row.pop("view", None)
    snapshot_row["view"] = view


def latest_view(state: dict, mint: str) -> dict | None:
    """View terbaru yang tersimpan untuk mint (``None`` kalau belum ada)."""
    buckets = (state.get("snapshots") or {}).get(mint) or {}
    views = [row["view"] for row in buckets.values()
             if isinstance(row, dict) and isinstance(row.get("view"), dict)]
    if not views:
        return None
    return max(views, key=lambda view: int(view.get("ts") or 0))


def watchlist_views(state: dict, mints) -> tuple:
    """(views, missing): view per mint watchlist yang ada + daftar yang belum.

    Urutan ``views`` mengikuti urutan watchlist; penyusunan urut tampilan
    dilakukan di UI (``sweep_screen.display_sort_key``).
    """
    views, missing = [], []
    for mint in parse_mints(mints):
        view = latest_view(state, mint)
        if view is None:
            missing.append(mint)
        else:
            views.append(view)
    return views, missing


def mint_history(state: dict, mint: str, *, limit: int = 48) -> list:
    """Snapshot mint urut menaik (paling lama dulu), maksimum ``limit`` baris."""
    buckets = (state.get("snapshots") or {}).get(mint) or {}
    rows = [row for row in buckets.values() if isinstance(row, dict)]
    rows.sort(key=lambda row: row.get("ts") or 0)
    return rows[-limit:]


def previous_snapshot(state: dict, mint: str, now=None, *,
                      max_age: int = NET_INFLOW_MAX_AGE) -> dict | None:
    """Snapshot **sebelum** bucket jam saat ini — dasar ukur inflow nyata.

    Ukuran yang dipakai sama dengan waktu menghitung sweep COCKROACH 1 Okt
    secara manual: selisih likuiditas antar titik. Snapshot lama (> ``max_age``)
    atau tanpa ``liq_usd`` tidak dipakai — lebih baik tidak ada angka daripada
    angka dari celah waktu yang tidak sebanding.
    """
    ts = int(now if now is not None else _now())
    bucket = ts // 3600
    rows = [row for row in mint_history(state, mint, limit=200)
            if isinstance(row, dict)
            and int(row.get("ts") or 0) // 3600 < bucket
            and _f(row.get("liq_usd")) is not None
            and ts - int(row.get("ts") or 0) <= max_age]
    return rows[-1] if rows else None


def net_inflow(state: dict, mint: str, liq_now, now=None, *,
               max_age: int = NET_INFLOW_MAX_AGE) -> float | None:
    """Perkiraan uang yang benar-benar tinggal di pool = Δ likuiditas.

    Hanya nilai **positif** yang berarti uang masuk; kalau tidak ada snapshot
    pembanding atau likuiditas turun, hasilnya ``None`` (jangan menebak).
    """
    now_liq = _f(liq_now)
    if now_liq is None:
        return None
    prev = previous_snapshot(state, mint, now, max_age=max_age)
    if not prev:
        return None
    delta = now_liq - _f(prev.get("liq_usd"))
    return delta if delta > 0 else None


# ---------------------------------------------------------------------------
# Sinyal
# ---------------------------------------------------------------------------
def record_signal(state: dict, signal: dict) -> dict:
    """Tambahkan sinyal baru (dengan id unik) ke riwayat."""
    signal = dict(signal or {})
    signal.setdefault("ts", _now())
    signal["id"] = f"{signal.get('kind') or 'x'}:{signal.get('mint') or ''}:{signal['ts']}"
    signal.setdefault("max_up_pct", None)
    signal.setdefault("max_down_pct", None)
    signal.setdefault("max_price", None)
    signal.setdefault("min_price", None)
    signal.setdefault("status", "open")
    state.setdefault("signals", []).append(signal)
    return signal


def has_signal(state: dict, signal_id: str) -> bool:
    return any((row or {}).get("id") == signal_id
               for row in (state.get("signals") or []))


def update_outcomes(state: dict, prices: dict, *, now: int | None = None) -> int:
    """Perbarui ``max_up_pct`` / ``max_down_pct`` sinyal dari harga terkini.

    ``prices`` = ``{mint: harga_sekarang}``. Sinyal dianggap ``closed`` setelah
    :data:`SIGNAL_TRACK_SEC` jam. Mengembalikan jumlah sinyal yang diperbarui.
    """
    now = int(now if now is not None else _now())
    touched = 0
    for signal in (state.get("signals") or []):
        if not isinstance(signal, dict):
            continue
        if signal.get("status") == "closed":
            continue
        price = (prices or {}).get(signal.get("mint"))
        if not price:
            if now - int(signal.get("ts") or now) > SIGNAL_TRACK_SEC:
                signal["status"] = "closed"
            continue
        entry = signal.get("entry_price") or signal.get("base_price")
        if not entry:
            continue
        up = (price / entry - 1.0) * 100.0
        down = up
        signal["max_up_pct"] = max(signal.get("max_up_pct") or up, up)
        signal["max_down_pct"] = min(signal.get("max_down_pct") or down, down)
        signal["max_price"] = max(signal.get("max_price") or price, price)
        signal["min_price"] = min(signal.get("min_price") or price, price)
        signal["last_price"] = price
        signal["updated"] = now
        base = signal.get("base_price")
        if base:
            signal["from_base_up_pct"] = max(
                signal.get("from_base_up_pct") or 0.0,
                (price / base - 1.0) * 100.0)
        if now - int(signal.get("ts") or now) > SIGNAL_TRACK_SEC:
            signal["status"] = "closed"
        touched += 1
    return touched


def eligible_mints(state: dict) -> list:
    """Mint yang sinyal kelayakan terakhirnya masih berstatus ``open``."""
    latest: dict = {}
    for signal in (state.get("signals") or []):
        if not isinstance(signal, dict):
            continue
        if signal.get("kind") != "eligibility":
            continue
        mint = signal.get("mint")
        if not mint:
            continue
        if (latest.get(mint) or {}).get("ts", 0) <= (signal.get("ts") or 0):
            latest[mint] = signal
    return [mint for mint, sig in latest.items() if sig.get("status") != "closed"]


# ---------------------------------------------------------------------------
# Alert bookkeeping
# ---------------------------------------------------------------------------
def alert_gate(state: dict, mint: str, kind: str, *, now: int | None = None,
               cooldown: int | None = None) -> bool:
    """True bila alert ``kind`` untuk ``mint`` boleh dikirim sekarang.

    Aturan **transisi-only**: alert hanya saat status berpindah dari nonaktif →
    aktif, lalu diulang paling cepat setelah ``cooldown``. Ini mencegah notif
    berulang tiap 5 menit selama kondisi bertahan (masalah yang sama sudah
    dihindari di ``prepump_cron_detector.py``).
    """
    now = int(now if now is not None else _now())
    if cooldown is None:
        cooldown = ELIG_COOLDOWN if kind == "eligibility" else SWEEP_COOLDOWN
    entry = (state.setdefault("alerts", {})).setdefault(
        mint, {"eligibility": False, "last_elig_ts": 0, "last_sweep_ts": 0})
    if kind == "eligibility":
        last = int(entry.get("last_elig_ts") or 0)
        active = bool(entry.get("eligibility"))
        if active and (now - last) < cooldown:
            return False
        entry["eligibility"] = True
        entry["last_elig_ts"] = now
        return True
    last = int(entry.get("last_sweep_ts") or 0)
    if last and (now - last) < cooldown:
        return False
    entry["last_sweep_ts"] = now
    return True


def clear_eligibility(state: dict, mint: str) -> None:
    """Tandai kelayakan mint tidak lagi aktif (agar alert transisi berikutnya)."""
    entry = (state.setdefault("alerts", {}) or {}).get(mint)
    if isinstance(entry, dict):
        entry["eligibility"] = False


# ---------------------------------------------------------------------------
# Persistensi GitHub (Streamlit Cloud ephemeral FS)
# ---------------------------------------------------------------------------
def _github_token() -> str:
    """Token GitHub: Streamlit secrets → env → ``config.json``."""
    try:
        import streamlit as st
        if "github_token" in st.secrets:
            token = str(st.secrets["github_token"]).strip()
            if token:
                return token
    except Exception:  # noqa: BLE001 - di luar Streamlit/CLI tidak ada secrets
        pass
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as handle:
            return str((json.load(handle) or {}).get("github_token", "")).strip()
    except Exception:  # noqa: BLE001
        return ""


def push_json(repo_path: str, data, message: str,
              *, repo: str | None = None, timeout: int = 15) -> bool:
    """Commit satu berkas JSON ke repo lewat GitHub Contents API.

    Mengembalikan ``False`` (tanpa melempar) bila token belum dipasang atau
    jaringan gagal — persistensi adalah optimisasi, bukan syarat agar UI jalan.
    """
    import requests

    token = _github_token()
    if not token:
        return False
    repo = repo or GITHUB_REPO
    url = f"https://api.github.com/repos/{repo}/contents/{repo_path}"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    try:
        sha = None
        probe = requests.get(url, headers=headers, timeout=timeout)
        if probe.status_code == 200:
            sha = (probe.json() or {}).get("sha")
        payload = {
            "message": message or f"sweep: update {repo_path}",
            "content": base64.b64encode(
                json.dumps(data, separators=(",", ":")).encode("utf-8")
            ).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        response = requests.put(url, headers=headers, json=payload,
                                timeout=timeout)
        return response.status_code in (200, 201)
    except Exception:  # noqa: BLE001 - offline/rate-limited ≠ crash aplikasi
        return False
