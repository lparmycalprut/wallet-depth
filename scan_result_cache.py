# -*- coding: utf-8 -*-
"""Cache berkas lokal untuk hasil scan — **refresh browser tidak menghapus hasil**.

Masalah yang dipecahkan: hasil scan card **🏆 Scan Best Pool Meteora** hidup
di ``st.session_state``. Streamlit membuat session baru setiap kali browser
di-refresh (F5), tab dibuka ulang, atau koneksi putus — jadi listing yang sudah
dipindai ikut lenyap, padahal enrichment holder-nya (scan FULL Helius) bisa
memakan belasan menit dan kuota.

Modul ini menyimpan **satu berkas JSON per key** di direktori cache (default
``.scan_cache/`` di root repo — **git-ignored**, jadi pernah ikut ter-commit)
dan memulihkannya ke ``session_state`` bila sesi sedang kosong:

- :func:`save_result(key, result)` — dipanggil **sesudah** scan selesai;
- :func:`restore_into_session(st, key, session_key)` — dipanggil saat render
  bila ``session_state[session_key]`` kosong.

Kontrak yang sengaja dijaga:

- **Tidak pernah melempar.** Kegagalan baca/tulis (direktori tidak bisa ditulis,
  disk penuh, JSON rusak, payload aneh) mengembalikan ``None``/``False`` — cache
  adalah pelengkap, sumber kebenarannya tetap hasil scan di memori;
- **Tulis atomik**: berkas ditulis ke ``*.tmp`` lalu ``os.replace``, jadi refresh
  di tengah penulisan tidak pernah membaca JSON setengah jadi;
- **Ramping**: peta wallet hasil scan FULL (``wallet_snapshot`` /
  ``chrono_snapshot``) dibuang sebelum disimpan — tanpa itu satu hasil scan
  bisa puluhan megabita untuk sebaris tabel dust;
- **Key mentah tidak pernah disimpan**: payload cache hanya berisi angka pasar
  dan alamat publik; API key hidup di ``st.secrets``/env, tidak pernah di
  sini.

Suite tes mematikan cache lewat env ``SCAN_CACHE=0`` (``tests/__init__.py``) dan
mengarahkan direktorinya ke ``tmp_path`` lewat fixture ``_iso_scan_cache``
(``tests/conftest.py``), jadi tidak ada tes yang menulis ke repo.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Kill-switch + lokasi cache. Env dipakai supaya tes (dan cron yang tidak
# pernah merender UI) bisa mengarahkannya ke direktori sementara tanpa monkeypatch.
SCAN_CACHE_ENV = "SCAN_CACHE"
SCAN_CACHE_DIR_ENV = "SCAN_CACHE_DIR"
DEFAULT_CACHE_DIR = BASE_DIR / ".scan_cache"

# Batas ukuran: tabel card tidak pernah perlu lebih dari ini, dan berkas cache
# yang membengkak hanya memperlambat render berikutnya.
MAX_ROWS = 300
MAX_HIDDEN_ROWS = 300
MAX_BYTES = 2_000_000
KEEP_LIST_ITEMS = 50

# Peta/daftar hasil scan FULL yang tidak dipakai ulang oleh kartu mana pun
# (hanya alert/kronologi yang butuh) — dibuang sebelum payload ditulis.
HEAVY_KEYS = frozenset({"wallet_snapshot", "chrono_snapshot", "cohort",
                        "wallet_balances", "movements"})

_OFF_VALUES = frozenset({"0", "off", "false", "no", "none"})


def enabled() -> bool:
    """True bila cache boleh dipakai (env ``SCAN_CACHE=0`` mematikannya)."""
    return str(os.environ.get(SCAN_CACHE_ENV) or "1").strip().lower() not in _OFF_VALUES


def cache_dir() -> Path:
    """Direktori cache aktif (env ``SCAN_CACHE_DIR`` mengalahkan default)."""
    override = str(os.environ.get(SCAN_CACHE_DIR_ENV) or "").strip()
    if override:
        return Path(override)
    return Path(DEFAULT_CACHE_DIR)


def _safe_key(key: str) -> str:
    """Nama berkas aman dari satu key cache (``best_pool_scan_24h`` → sama)."""
    text = str(key or "").strip()
    out = []
    for char in text:
        out.append(char if (char.isalnum() or char in "-_.") else "_")
    safe = "".join(out).strip("._")
    return safe or "scan"


def cache_path(key: str) -> Path:
    """Berkas JSON untuk satu key cache."""
    return cache_dir() / f"{_safe_key(key)}.json"


def _strip_value(value, depth: int = 0):
    """Salin payload tanpa peta berat; daftar dipotong; angka dilewatkan apa adanya.

    Rekursif dengan ``depth`` sebagai rem: struktur hasil scan tidak pernah
    dalam, tetapi payload dari API luar tidak bisa dipercaya bentuknya, jadi
    kedalaman dibatasi (``depth > 6`` → nilai dikembalikan apa adanya kalau
    sudah sederhana, else ``None``).
    """
    if isinstance(value, dict):
        if depth > 6:
            return None
        out = {}
        for name, item in value.items():
            if name in HEAVY_KEYS:
                continue
            out[name] = _strip_value(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        if depth > 6:
            return []
        return [_strip_value(item, depth + 1)
                for item in list(value)[:KEEP_LIST_ITEMS]]
    if isinstance(value, float):
        # NaN/Infinity bukan JSON valid; ``json.dump`` menulisnya sebagai
        # ``NaN`` yang gagal di-parse pembaca JSON ketat.
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _strip_rows(rows, limit: int):
    """Baris tabel yang disimpan: tanpa ``analysis`` berat, maks ``limit`` baris."""
    kept = []
    for row in list(rows or [])[:max(0, int(limit))]:
        if not isinstance(row, dict):
            continue
        kept.append(_strip_value(row))
    return kept


def slim_result(result: dict) -> dict:
    """Salin hasil scan yang siap disimpan: baris dirapikan + dibatasi."""
    payload = _strip_value(result if isinstance(result, dict) else {})
    if not isinstance(payload, dict):
        return {}
    payload["rows"] = _strip_rows((result or {}).get("rows"), MAX_ROWS)
    payload["hidden_rows"] = _strip_rows((result or {}).get("hidden_rows"),
                                         MAX_HIDDEN_ROWS)
    return payload


def save_result(key: str, result: dict):
    """Simpan hasil scan ke berkas cache; return ``Path`` atau ``None`` bila gagal.

    Tidak pernah melempar: kegagalan tulis hanya berarti fitur "tahan refresh"
    tidak aktif untuk run itu, bukan halaman yang rusak. Payload yang melebihi
    :data:`MAX_BYTES` setelah dirampingkan **dibuang** (return ``None``) supaya
    direktori cache tidak tumbuh tanpa batas.
    """
    if not enabled() or not isinstance(result, dict):
        # Hasil kosong/None (belum ada scan) tidak boleh menimpa cache lama
        # dengan berkas "0 pool" palsu.
        return None
    try:
        payload = slim_result(result)
        if not payload:
            return None
        payload["cached_at"] = int(time.time())
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > MAX_BYTES:
            return None
        target = cache_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(target.parent),
            prefix=f".{target.stem}-", suffix=".tmp", delete=False)
        try:
            with handle:
                handle.write(text)
            os.replace(handle.name, target)
        except Exception:  # noqa: BLE001 - bersihkan berkas sementara
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
        return target
    except Exception:  # noqa: BLE001 - cache tidak boleh menggagalkan scan
        return None


def load_result(key: str):
    """Hasil scan tersimpan (``dict``) atau ``None`` (kosong/rusak/dimatikan)."""
    if not enabled():
        return None
    path = cache_path(key)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def clear_result(key: str) -> bool:
    """Hapus satu berkas cache. ``False`` bila tidak ada / gagal."""
    try:
        path = cache_path(key)
    except Exception:  # noqa: BLE001 - key aneh
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def clear_all() -> int:
    """Hapus semua berkas cache; return jumlah yang terhapus."""
    removed = 0
    try:
        directory = cache_dir()
        for path in directory.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    return removed


def restore_into_session(st, key: str, session_key: str) -> bool:
    """Muat hasil cache ke ``st.session_state[session_key]`` bila sesi kosong.

    Dipanggil **sebelum** card menggambar isinya:.session baru (habis refresh)
    tidak punya key itu, jadi berkas cache dipakai untuk mengisi ulang tabel
    tanpa scan ulang. Sesi yang sudah berisi hasil (scan baru saja selesai)
    never ditimpa. Return ``True`` bila sesi diisi dari cache.
    """
    try:
        if st.session_state.get(session_key):
            return False
    except Exception:  # noqa: BLE001 - session_state bisa belum siap
        return False
    payload = load_result(key)
    if not payload:
        return False
    try:
        st.session_state[session_key] = payload
        return True
    except Exception:  # noqa: BLE001
        return False
