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
# CVD sejak lowest buy (2026-10-20): batas penyimpanan per mint.
FLOW_HOURLY_KEEP = 168  # bucket jam per episode (7 hari)
FLOW_PAST_KEEP = 10     # episode selesai per mint

#: Sinyal lebih tua dari ini tidak lagi diperbarui hasilnya.
SIGNAL_TRACK_SEC = 72 * HOUR
#: Cooldown alert (detik): kelayakan jarang berubah, sweep cepat.
ELIG_COOLDOWN = 6 * HOUR
SWEEP_COOLDOWN = 30 * 60
#: Sinyal sweep hanya dicatat sekali per candle 5 menit (kunci = mint + ts candle).
#: Alert Telegram hanya dikirim bila candle belum terlalu tua saat terdeteksi;
#: sweep lama yang baru terlihat (mis. setelah jeda cron) tetap tercatat, tanpa notif.
SWEEP_CANDLE_SEC = 5 * 60
SWEEP_ALERT_MAX_AGE = 60 * 60
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
            "alerts": {}, "shakeout_latched_at": {}, "cohort_latched": {},
            "scan_status": {}, "flow_episodes": {}, "updated": 0}


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
    for key in ("shakeout_latched_at", "cohort_latched", "scan_status",
                "flow_episodes", "scan_log"):
        if isinstance(data.get(key), dict):
            state[key] = data[key]
    state["updated"] = int(data.get("updated") or 0)
    return state


def push_state(state: dict, reason: str = "") -> bool:
    """Commit state ke GitHub (dipakai UI tombol persist + cron)."""
    return push_json("sweep_state.json", state,
                     f"sweep: state {reason}".strip())


def _newer_row(current, incoming):
    """Baris bucket yang ts-nya lebih baru; seri → ``incoming``."""
    if not isinstance(current, dict):
        return incoming
    if not isinstance(incoming, dict):
        return current
    return incoming if int(incoming.get("ts") or 0) >= int(current.get("ts") or 0) \
        else current


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _merge_flow_episodes(remote, local) -> dict:
    """CVD sejak lowest buy (2026-10-20), digabung per mint.

    - Episode aktif dengan ``start_ts`` sama: bucket jam di-union; bila jam yang
      sama ada di keduanya, baris dengan ``ts`` lebih baru yang dipakai.
    - Episode aktif dengan ``start_ts`` berbeda: yang ``start_ts``-nya lebih awal.
    - Riwayat selesai: union berdasarkan ``start_ts``.
    """
    out: dict = {}
    for source in (remote, local):
        if not isinstance(source, dict):
            continue
        for mint, entry in source.items():
            if not isinstance(entry, dict):
                continue
            current = out.get(mint)
            if current is None:
                out[mint] = {"active": entry.get("active"),
                             "past": list(entry.get("past") or [])}
                continue
            a_cur, a_new = current.get("active"), entry.get("active")
            if isinstance(a_cur, dict) and isinstance(a_new, dict):
                if int(a_cur.get("start_ts") or 0) == int(a_new.get("start_ts") or 0):
                    hourly = dict(a_cur.get("hourly") or {})
                    for key, row in (a_new.get("hourly") or {}).items():
                        old = hourly.get(key)
                        if not isinstance(old, dict) or (
                                int((row or {}).get("ts") or 0) >= int(old.get("ts") or 0)):
                            hourly[key] = row
                    merged_active = dict(a_cur)
                    merged_active["hourly"] = hourly
                    newest = max(hourly.values(),
                                 key=lambda r: int((r or {}).get("ts") or 0),
                                 default=None)
                    merged_active["last"] = newest or a_cur.get("last")
                    current["active"] = merged_active
                elif int(a_new.get("start_ts") or 0) < int(a_cur.get("start_ts") or 0):
                    current["active"] = a_new
            elif current.get("active") is None and isinstance(a_new, dict):
                current["active"] = a_new
            seen = {int(p.get("start_ts") or 0): p for p in current.get("past") or []
                    if isinstance(p, dict)}
            for p in entry.get("past") or []:
                if isinstance(p, dict):
                    seen.setdefault(int(p.get("start_ts") or 0), p)
            current["past"] = [seen[k] for k in sorted(seen, reverse=True)]
    return out


def merge_states(local: dict, remote: dict) -> dict:
    """Gabung state lokal dengan versi GitHub tanpa kehilangan snapshot.

    Cron (GitHub Actions) dan app (auto-refresh) sama-sama menulis
    ``sweep_state.json``. Tanpa merge, penulis yang terakhir menimpa snapshot
    jam yang sudah ditulis penulis lain.

    - ``snapshots``: union mint dan bucket jam; bucket yang sama memakai baris
      dengan ``ts`` terbaru.
    - ``signals``: union berdasarkan ``id`` (versi lokal menang), urut ``ts``.
    - ``shakeout_latched_at``: union; bila beda, latch paling awal yang dipakai
      (latch bersifat permanen).
    - ``alerts``: per mint, nilai numerik diambil maksimum (cooldown tidak
      mundur); field lain versi lokal.
    - ``updated``: maksimum. Field lain: versi lokal.
    """
    local = dict(local or {})
    remote = dict(remote or {})
    merged = dict(local)

    snapshots: dict = {}
    for source in (remote.get("snapshots"), local.get("snapshots")):
        if not isinstance(source, dict):
            continue
        for mint, buckets in source.items():
            target = snapshots.setdefault(mint, {})
            if not isinstance(buckets, dict):
                continue
            for key, row in buckets.items():
                target[key] = _newer_row(target.get(key), row)
    merged["snapshots"] = snapshots

    seen: dict = {}
    for row in list(remote.get("signals") or []) + list(local.get("signals") or []):
        if not isinstance(row, dict):
            continue
        key = row.get("id")
        if key is None:
            key = json.dumps(row, sort_keys=True, default=str)
        seen[key] = row
    signals = sorted(seen.values(), key=lambda row: float(row.get("ts") or 0))
    merged["signals"] = signals[-MAX_SIGNALS:]
    merged["scan_log"] = _merge_scan_log(remote.get("scan_log"), local.get("scan_log"))

    latches: dict = {}
    for source in (remote.get("shakeout_latched_at"), local.get("shakeout_latched_at")):
        if not isinstance(source, dict):
            continue
        for mint, ts in source.items():
            if ts is None:
                continue
            current = latches.get(mint)
            latches[mint] = ts if current is None else min(current, ts)
    merged["shakeout_latched_at"] = latches

    # Latch kohort (2026-10-14): permanen seperti shakeout — union, yang paling awal.
    cohort_latches: dict = {}
    for source in (remote.get("cohort_latched"), local.get("cohort_latched")):
        if not isinstance(source, dict):
            continue
        for mint, entry in source.items():
            if not isinstance(entry, dict):
                continue
            current = cohort_latches.get(mint)
            if current is None or float(entry.get("ts") or 0) < float(current.get("ts") or 0):
                cohort_latches[mint] = entry
    merged["cohort_latched"] = cohort_latches

    # Status scan terakhir per mint: entri dengan ts terbaru menang (sukses maupun
    # gagal), sehingga scan sukses menghapus tanda gagal yang lebih lama.
    scan_status: dict = {}
    for source in (remote.get("scan_status"), local.get("scan_status")):
        if not isinstance(source, dict):
            continue
        for mint, entry in source.items():
            if not isinstance(entry, dict):
                continue
            current = scan_status.get(mint)
            if current is None or float(entry.get("ts") or 0) >= float(current.get("ts") or 0):
                scan_status[mint] = entry
    merged["scan_status"] = scan_status

    alerts: dict = {}
    for source in (remote.get("alerts"), local.get("alerts")):
        if not isinstance(source, dict):
            continue
        for mint, entry in source.items():
            current = alerts.get(mint)
            if not (isinstance(current, dict) and isinstance(entry, dict)):
                alerts[mint] = entry
                continue
            combined = dict(current)
            for key, value in entry.items():
                old = combined.get(key)
                if _is_number(value) and _is_number(old):
                    combined[key] = max(old, value)
                else:
                    combined[key] = value
            alerts[mint] = combined
    merged["alerts"] = alerts

    merged["flow_episodes"] = _merge_flow_episodes(
        remote.get("flow_episodes"), local.get("flow_episodes"))

    merged["updated"] = max(int(local.get("updated") or 0),
                            int(remote.get("updated") or 0))
    merged["version"] = STATE_VERSION
    return merged


def fetch_remote_state(timeout: int = 15):
    """State di GitHub: ``dict``; ``{}`` bila berkas belum ada; ``None`` bila gagal dibaca.

    ``None`` berarti jangan menimpa GitHub — lebih baik tidak commit daripada
    menghapus snapshot yang tidak terbaca.
    """
    import requests

    token = _github_token()
    if not token:
        return None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/sweep_state.json"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github.raw"}
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except Exception:  # noqa: BLE001 - offline ≠ crash aplikasi
        return None
    if response.status_code == 404:
        return {}
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def save_state(state: dict, *, persist: bool = False, reason: str = "") -> dict:
    """Tulis state lokal (atomik) + opsional commit ke GitHub.

    Dengan ``persist`` state digabung dulu dengan versi GitHub (lihat
    :func:`merge_states`). Bila versi GitHub tidak bisa dibaca, state hanya
    ditulis lokal dan tidak di-push.
    """
    state = dict(state or {})
    # Drop legacy UI settings on the next write; thresholds are fixed in
    # sweep_screen and no longer belong to persisted state.
    state.pop("settings", None)
    state.setdefault("shakeout_latched_at", {})
    state.setdefault("cohort_latched", {})
    state.setdefault("scan_status", {})
    state.setdefault("flow_episodes", {})
    state["version"] = STATE_VERSION
    state["updated"] = _now()
    pushable = False
    if persist:
        remote = fetch_remote_state()
        if remote is not None:
            state = prune(merge_states(state, remote))
            pushable = True
    atomic_write_json(STATE_PATH, state, separators=(",", ":"))
    if pushable:
        push_state(state, reason)
    return state


def fingerprint(state: dict) -> str:
    """Fingerprint kunci bucket snapshot, signal ids, dan latch shakeout permanen.

    Hanya **kunci bucket** (jam) yang masuk, bukan isinya: bucket jam berjalan
    ditimpa tiap run cron (harga, likuiditas, view), dan kalau isinya ikut,
    setiap run cron akan membuat commit. Jadi commit hanya terjadi saat
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
    flows = (state or {}).get("flow_episodes") or {}
    flow_hours = {
        mint: sorted(((entry.get("active") or {}).get("hourly") or {}).keys())
        for mint, entry in flows.items()
        if isinstance(entry, dict) and (entry.get("active") or {}).get("hourly")
    }
    extra = {"flow_hours": flow_hours} if flow_hours else {}
    payload = json.dumps({
        **extra,
        "snapshots": hour_keys,
        "signals": [(row or {}).get("id") for row in ((state or {}).get("signals") or [])
                    if isinstance(row, dict)],
        "shakeout_latched_at": (state or {}).get("shakeout_latched_at") or {},
        "cohort_latched": (state or {}).get("cohort_latched") or {},
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
    flows = state.get("flow_episodes")
    if isinstance(flows, dict):
        for mint, entry in list(flows.items()):
            if not isinstance(entry, dict):
                flows.pop(mint, None)
                continue
            active = entry.get("active")
            if isinstance(active, dict):
                hourly = active.get("hourly") or {}
                if len(hourly) > FLOW_HOURLY_KEEP:
                    keep = sorted(hourly, key=lambda k: float(k or 0))[-FLOW_HOURLY_KEEP:]
                    active["hourly"] = {k: hourly[k] for k in keep}
            entry["past"] = list(entry.get("past") or [])[:FLOW_PAST_KEEP]
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

    Bucket per jam (bukan per 5 menit) disengaja: cron berjalan tiap 30 menit
    dan snapshot 5-menit akan menulis ~288 baris/hari/mint ke dalam berkas
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
    "pool_base_amount", "pool_base_usd",
    "market_cap_usd", "vol_1h", "vol_24h", "buys_1h", "sells_1h", "pair_address",
    "dex_id", "pool_count", "url", "pair_created_at", "rugcheck_ok",
    "mint_authority", "freeze_authority", "top10_holder_pct", "holder_count",
    "top_bundler_trader_percentage", "bundler_rate", "bot_degen_rate",
    "fresh_wallet_rate", "status_now", "holding_rate",
    "holder_min_avg_cost", "holder_cost_count", "holder_cost_basis",
    "holder_cost_balance",
)
VIEW_RESULT_KEYS = (
    "checks", "passed_count", "scored_count", "required_count", "score",
    "structural_ok", "eligible", "verdict", "color", "liq_mc", "targets",
    "reference_fund_x", "reference_fund_usd", "turnover_x", "cohort",
    "cohort_gate_status", "cohort_gate_passed", "cohort_gate_detail",
    "cost_10x_mc_frac", "gmgn_status_avg_cost", "holder_min_avg_cost", "holder_gap",
    "holder_gate_status", "holder_gate_passed", "holder_gate_detail",
    "missing", "order_flow", "delta",
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


def record_scan_status(state: dict, mint: str, *, ok: bool, error: str = "",
                       ts: int | None = None) -> None:
    """Catat hasil scan terakhir mint (sukses atau gagal) di ``state.scan_status``.

    Scan yang gagal tidak menimpa view lama, jadi tanpa catatan ini baris lama
    (yang mungkin sudah memenuhi filter tampilan) tampil seolah tidak ada error.
    """
    status = state.setdefault("scan_status", {})
    if not isinstance(status, dict):
        status = state["scan_status"] = {}
    status[mint] = {"ts": int(ts if ts is not None else _now()), "ok": bool(ok),
                    "error": "" if ok else str(error or "sumber data tidak merespons")[:160]}


def scan_failure(state: dict, mint: str) -> dict | None:
    """Catatan scan terakhir bila scan itu GAGAL (``None`` bila sukses/belum ada)."""
    entry = ((state or {}).get("scan_status") or {}).get(mint)
    if isinstance(entry, dict) and entry.get("ok") is False:
        return entry
    return None


def watchlist_views(state: dict, mints) -> tuple:
    """(views, missing): view per mint watchlist yang ada + daftar yang belum.

    Bila scan terakhir mint gagal, salinan view diberi kunci ``scan_error``
    (catatan kegagalan). View di state tidak diubah. Urutan ``views`` mengikuti
    urutan watchlist; penyusunan urut tampilan dilakukan di UI
    (``sweep_screen.display_sort_key``).
    """
    views, missing = [], []
    for mint in parse_mints(mints):
        view = latest_view(state, mint)
        if view is None:
            missing.append(mint)
        else:
            view = dict(view)
            failure = scan_failure(state, mint)
            if failure is not None:
                view["scan_error"] = failure
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
# Catatan per scan (termasuk mint tersembunyi) dan detail sebelum sweep
# ---------------------------------------------------------------------------
#: Berapa scan terakhir per mint yang disimpan (cron 30 menit → 6 scan ≈ 3 jam).
SCAN_LOG_KEEP = 6
#: Berapa scan sebelum candle sweep yang ikut disimpan di sinyal sweep.
SWEEP_PRE_SCANS = 3
#: Berapa candle 5 menit (termasuk candle sweep) yang ikut disimpan (12 ≈ 1 jam).
SWEEP_PRE_CANDLES = 12

#: Field metrik kompak per scan. Sengaja kecil: catatan ini ditulis untuk setiap
#: mint di setiap scan, termasuk yang disembunyikan dari tabel.
SCAN_LOG_METRIC_KEYS = (
    "symbol", "price_usd", "liq_usd", "fdv_usd", "pool_base_usd", "vol_1h",
    "buys_1h", "sells_1h", "holder_count", "top10_holder_pct",
    "top_bundler_trader_percentage", "bundler_rate", "bot_degen_rate",
    "fresh_wallet_rate", "holder_min_avg_cost", "holder_cost_count",
)
SCAN_LOG_RESULT_KEYS = (
    "verdict", "eligible", "passed_count", "scored_count", "required_count",
    "liq_mc", "cohort_gate_status", "holder_gate_status", "holder_gap",
    "reference_fund_x", "turnover_x",
)


def scan_log_entry(metrics: dict, result: dict, *, ts: int, hidden: bool) -> dict:
    """Ringkasan kondisi satu mint pada satu scan (kompak, untuk riwayat)."""
    metrics = metrics or {}
    result = result or {}
    criteria = {}
    for check in result.get("checks") or []:
        if not isinstance(check, dict) or not check.get("key"):
            continue
        if not check.get("has_data"):
            criteria[check["key"]] = "n/a"
        else:
            criteria[check["key"]] = "lolos" if check.get("passed") else "gagal"
    return {
        "ts": int(ts),
        "hidden": bool(hidden),
        "metrics": {k: metrics[k] for k in SCAN_LOG_METRIC_KEYS if k in metrics},
        "result": {k: result[k] for k in SCAN_LOG_RESULT_KEYS if k in result},
        "criteria": criteria,
    }


def scan_log_add(state: dict, mint: str, entry: dict) -> None:
    """Tambahkan catatan scan untuk ``mint``; scan dengan ts sama menimpa.

    Hanya ``SCAN_LOG_KEEP`` entri terbaru per mint yang disimpan.
    """
    log = state.setdefault("scan_log", {})
    if not isinstance(log, dict):
        log = state["scan_log"] = {}
    rows = [row for row in (log.get(mint) or []) if isinstance(row, dict)]
    rows = [row for row in rows if row.get("ts") != entry.get("ts")]
    rows.append(entry)
    rows.sort(key=lambda row: int(row.get("ts") or 0))
    log[mint] = rows[-SCAN_LOG_KEEP:]


def sweep_detail(state: dict, mint: str, candle_ts: int, candles_min5,
                 ) -> dict:
    """Detail sebelum sweep: scan sebelum candle, scan yang mendeteksi, dan candle.

    ``scans`` berisi hingga ``SWEEP_PRE_SCANS`` catatan dengan ts < candle sweep,
    lalu catatan scan yang mendeteksi (ts >= candle). ``candles`` berisi candle
    5 menit dalam jendela ``SWEEP_PRE_CANDLES`` yang berakhir di candle sweep.
    """
    cts = int(candle_ts)
    log = [row for row in ((state.get("scan_log") or {}).get(mint) or [])
           if isinstance(row, dict)]
    before = [row for row in log if int(row.get("ts") or 0) < cts]
    detected = [row for row in log if int(row.get("ts") or 0) >= cts]
    scans = before[-SWEEP_PRE_SCANS:] + detected[:1]
    window_start = cts - SWEEP_PRE_CANDLES * SWEEP_CANDLE_SEC
    candles = []
    for row in candles_min5 or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            ts = int(row[0])
        except (TypeError, ValueError):
            continue
        if window_start < ts <= cts:
            candles.append([ts, row[1], row[2], row[3], row[4], row[5]])
    candles.sort(key=lambda row: row[0])
    hidden = bool(detected[0].get("hidden")) if detected else None
    return {"scans": scans, "candles": candles, "hidden": hidden}


def _merge_scan_log(*sources) -> dict:
    """Gabung ``scan_log`` beberapa state: per mint, ts unik, paling baru ``SCAN_LOG_KEEP``."""
    merged: dict = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for mint, rows in source.items():
            if not isinstance(rows, list):
                continue
            target = merged.setdefault(mint, {})
            for row in rows:
                if isinstance(row, dict) and row.get("ts") is not None:
                    target[int(row["ts"])] = row
    return {mint: [rows[ts] for ts in sorted(rows)][-SCAN_LOG_KEEP:]
            for mint, rows in merged.items()}


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


def find_sweep_signal(state: dict, mint: str, context: dict):
    """Sinyal sweep yang sudah mencatat candle ``context`` untuk ``mint``, atau None.

    Sinyal baru dikunci dengan ``sweep_ts`` (ts candle). Sinyal lama (sebelum
    field itu ada) dicocokkan lewat ``entry_price`` = close candle, yang memang
    disimpan sejak awal. Tanpa dedupe ini, candle sweep yang sama dicatat ulang
    setiap cron berjalan setelah cooldown dan statistik menghitung satu kejadian
    berkali-kali.
    """
    sweep_ts = (context or {}).get("sweep_ts")
    close = (context or {}).get("close")
    for signal in state.get("signals") or []:
        if not isinstance(signal, dict) or signal.get("kind") != "sweep":
            continue
        if signal.get("mint") != mint:
            continue
        if signal.get("sweep_ts") is not None:
            if sweep_ts is not None and int(signal["sweep_ts"]) == int(sweep_ts):
                return signal
        elif close is not None and signal.get("entry_price") == close:
            return signal
    return None


def backfill_sweep_inflow(signal: dict, context: dict, *, measured_at: int) -> bool:
    """Isi inflow NYATA ke sinyal yang sudah ada, bila snapshot berikutnya punya.

    Churn nyata butuh pembanding likuiditas dari snapshot SETELAH sweep. Karena
    satu candle hanya dicatat sekali, angka itu diisi ulang ke sinyal lama
    (bukan dicatat sebagai sinyal baru). Angka yang sudah terukur tidak ditimpa.
    """
    if not isinstance(signal, dict) or signal.get("net_inflow_usd") is not None:
        return False
    net = (context or {}).get("net_inflow_usd")
    if net is None:
        return False
    signal["net_inflow_usd"] = net
    signal["churn_net_x"] = context.get("churn_net_x")
    signal["leverage_net"] = context.get("leverage_net")
    signal["net_measured_at"] = int(measured_at)
    return True


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
