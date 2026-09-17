# -*- coding: utf-8 -*-
"""Likuiditas total per token dari **GMGN** — sumber angka kolom RugCheck.

Permintaan user 2026-09-17: *"kita rubah info liquidititas dari rugchecker.cc
ke gmgn saja"* + *"jika grand total liquiditas kurang dari 1M, jangan tampilkan
di hasil scan"*, lalu pada hari yang sama *"poolnya kok jadi kosong, padahal
token PAID harusnya masuk"* → ambangnya **$500K**
(:data:`MIN_TOTAL_LIQ_USD`; $1M ternyata membuang praktis seluruh listing —
lihat catatan di konstanta). Jadi:

1. **angka likuiditas** yang ditampilkan (sub-line kolom RugCheck) adalah
   likuiditas total GMGN, bukan lagi total per-DEX dari rugchecker.cc
   (rincian per-DEX di tooltip ikut diganti — sumber: *gmgn.ai*);
2. pool yang **terbukti** berlikuiditas total **< $500K** tidak lagi
   ditampilkan di hasil scan 🏆 Best Pool — barisnya masuk listing "dilewati"
   dengan alasan di ``best_gaps`` (satu jalur dengan saringan
   F/V/volat/Top10, lewat :func:`meteora_screener.row_best_gaps` →
   :func:`row_gmgn_gap`).

Sumber data (satu request untuk SEMUA mint dalam scan, bukan per token):

===========================  ====================================================
POST ``/api/v1/              **primer** — ``{"chain": "sol", "addresses":
``mutil_window_token_info``  [mint, …]}`` = sumber data halaman token GMGN;
                           ``liquidity`` (USD) di level atas token = angka
                           "Liquidity" yang user lihat di halaman gmgn.ai.
                           Batch :data:`BATCH_SIZE` mint per request.
GET ``/defi/quotation/v1/    **fallback** — peringkat 100 token teratas Solana
rank/sol/swaps/24h?          per likuiditas 24 jam (cap server 100 entri, cutoff
orderby=liquidity``          ≈ likuiditas terkecil di daftar). Mint yang
                           **tidak ada** di daftar pasti di bawah cutoff →
                           aman dianggap < ambang (baris ikut disaring, alasan
                           "di bawah cutoff").
===========================  ====================================================

Tanpa API key. HTTP memakai ``curl_cffi`` (impersonate TLS browser, pola yang
sama dengan :mod:`gmgn_screener`) dengan fallback ``requests`` polos;
endpoint rank terbukti menjawab GET polos, endpoint POST kadang menuntut
sidik jari TLS yang cocok dengan user-agent — karena itu POST mencoba
several identitas impersonate sebelum menyerah ke ``requests``.

Aturan saring (lihat :func:`row_gmgn_gap`):

* likuiditas diketahui dan **< :data:`MIN_TOTAL_LIQ_USD`** ($500K) → gugur;
  tepat $500K atau lebih → lolos (permintaan user: "**kurang dari** ambang
  jangan ditampilkan" — batasnya inklusif di sisi lolos);
* mint tak ada di fallback rank dan cutoff rank **< :data:`MIN_TOTAL_LIQ_USD`**
  → gugur (likuiditasnya pasti di bawah cutoff);
* sumber GMGN gagal total / mint tak terbaca → **tidak disaring**
  (tanpa bukti tidak ada verdict — filosofi repo: kolom menulis ``—``,
  baris tetap tampil).

Cache berkas (``gmgn_liquidity_cache.json``, TTL :data:`CACHE_TTL_OK`) menahan
hasil per-mint supaya rerun Streamlit (setiap interaksi) tidak menembak
endpoint pihak ketiga untuk mint yang sama dalam jeda pendek — likuiditas
bergeser cepat, jadi TTL-nya 5 menit (jauh lebih pendek dari cache
rugchecker 30 menit).
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

#: Ambang "grand total liquiditas" (permintaan user 2026-09-17: *"< 1M jangan
#: tampilkan"*, **diturunkan ke $500K** pada hari yang sama setelah user
#: melaporkan *"poolnya kok jadi kosong, padahal token PAID harusnya masuk"*).
#: Pengukuran langsung endpoint GMGN ``/api/v1/token_info/sol/<mint>`` saat itu:
#: PAID (``98kf…pump``) = **$884.912** — di bawah $1M, jadi ambang lama membuang
#: PAID dan praktis seluruh listing (pill $153.496, ELON $149.542; pool DLMM
#: teratas Meteora hampir tidak ada yang berlikuiditas ≥ $1M). $500K tetap
#: menyaring pool tipis ±$150K tetapi membiarkan kandidat seperti PAID lewat.
#: Baris dengan likuiditas total **di bawah** nilai ini tidak ditampilkan.
MIN_TOTAL_LIQ_USD = 500_000.0


def _label_usd(value) -> str:
    """Label ambang ringkas (``$500K`` / ``$1M``) untuk teks alasan.

    Dipakai alih-alih :func:`compact_usd` supaya teksnya tetap pendek
    (``compact_usd(500_000)`` = ``$500.00K``) dan tidak berubah sendiri bila
    :data:`MIN_TOTAL_LIQ_USD` dinaikkan/diturunkan lagi. Sengaja tidak memakai
    helper ``_float`` di bawah: label ini dihitung saat import, jadi harus
    berdiri sendiri.
    """
    number = float(value)
    if number >= 1_000_000:
        return f"${number / 1_000_000:g}M"
    return f"${number / 1_000:g}K"


#: Label ambang untuk teks alasan (``$500K``).
MIN_LABEL = _label_usd(MIN_TOTAL_LIQ_USD)

#: Sumber data halaman token GMGN (batch: ``{"chain": "sol", "addresses": […]}``).
TOKEN_INFO_URL = "https://gmgn.ai/api/v1/mutil_window_token_info"

#: Fallback — 100 token teratas Solana per likuiditas (cap server 100 entri).
RANK_URL = ("https://gmgn.ai/defi/quotation/v1/rank/sol/swaps/24h"
            "?orderby=liquidity&direction=desc")

#: Lokasi cache berkas (di repo supaya ikut persist antar-restart container).
CACHE_PATH = Path(__file__).resolve().parent / "gmgn_liquidity_cache.json"
CACHE_TTL_OK = 300          # hasil sukses: 5 menit (likuiditas bergerak cepat)
CACHE_TTL_FAIL = 120        # kegagalan: 2 menit (jangan menghukum selamanya)
CACHE_MAX_ENTRIES = 400     # pruning LRU sederhana

REQUEST_TIMEOUT = 20
BATCH_SIZE = 10             # mint per request POST
_IMPERSONATIONS = ("chrome", "chrome131", "safari17_0")

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "origin": "https://gmgn.ai",
    "referer": "https://gmgn.ai/sol/trending",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/152.0.0.0 Safari/537.36"),
}

_lock = threading.Lock()


def _float(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _float_or_none(value) -> float | None:
    """``float`` bila valid & finite; ``None`` bila hilang/invalid (unknown)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def compact_usd(value) -> str:
    """Format ringkas ala repo — disalin dari :mod:`rugchecker` (modul ini
    harus bisa dipakai skrip cron/tes tanpa Streamlit dan tanpa melingkari
    import)."""
    from rugchecker import compact_usd as _compact
    return _compact(value)


# ---------------------------------------------------------------------------
# cache berkas
# ---------------------------------------------------------------------------

def _cache_load() -> dict:
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _cache_save(cache: dict) -> None:
    """Tulis atomik; gagal tulis diam-diam (cache hanya pelengkap)."""
    try:
        if len(cache) > CACHE_MAX_ENTRIES:
            ordered = sorted(cache.items(),
                             key=lambda kv: _float((kv[1] or {}).get("at")))
            cache = dict(ordered[-CACHE_MAX_ENTRIES:])
        path = Path(CACHE_PATH)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _cache_get(mint: str) -> dict | None:
    """Entri cache segar mint (``None`` bila tak ada/expired)."""
    entry = _cache_load().get(mint)
    if not isinstance(entry, dict):
        return None
    age = time.time() - _float(entry.get("at"))
    ttl = CACHE_TTL_OK if entry.get("ok") else CACHE_TTL_FAIL
    if age > ttl:
        return None
    return entry


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _post_json(url: str, body: dict, *, timeout: int) -> object:
    """POST JSON — ``curl_cffi`` impersonate (giliran identitas) lalu
    ``requests`` polos. Melempar ``RuntimeError`` bila semua jalur gagal."""
    last = ""
    try:
        from curl_cffi import requests as client
        for identity in _IMPERSONATIONS:
            try:
                resp = client.post(
                    url, impersonate=identity, timeout=timeout,
                    headers={**_HEADERS, "content-type": "application/json"},
                    data=json.dumps(body))
                if resp.status_code == 200:
                    return resp.json()
                last = f"HTTP {resp.status_code}"
            except Exception as exc:  # noqa: BLE001 - coba identitas berikutnya
                last = str(exc)[:160]
    except ImportError:
        pass
    try:
        import requests
        resp = requests.post(url,
                             headers={**_HEADERS,
                                      "content-type": "application/json"},
                             json=body, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"gmgn POST: {str(exc)[:160] or last}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"gmgn POST HTTP {resp.status_code}")
    try:
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - HTML error page dll.
        raise RuntimeError("gmgn POST: respons bukan JSON") from exc


def _get_json(url: str, *, timeout: int) -> object:
    """GET JSON — ``requests`` polos dulu (endpoint rank terbukti menjawab
    tanpa impersonate), fallback ``curl_cffi`` bila Cloudflare menolak."""
    last = ""
    try:
        import requests
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            last = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:160]
    except ImportError:
        pass
    try:
        from curl_cffi import requests as client
        for identity in _IMPERSONATIONS:
            try:
                resp = client.get(url, impersonate=identity, timeout=timeout,
                                  headers=_HEADERS)
                if resp.status_code == 200:
                    return resp.json()
                last = f"HTTP {resp.status_code}"
            except Exception as exc:  # noqa: BLE001
                last = str(exc)[:160]
    except ImportError:
        pass
    raise RuntimeError(f"gmgn GET: {last or 'tanpa respons'}")


# ---------------------------------------------------------------------------
# parse respons
# ---------------------------------------------------------------------------

def _parse_token_info(payload) -> dict[str, float | None]:
    """``{address: liquidity_usd}`` dari respons ``mutil_window_token_info``.

    Bentuk respons: daftar token langsung (``[{address, liquidity, …}]``)
    atau terbungkus ``{"code": 0, "data": […]}`` — keduanya diterima.
    ``liquidity`` bisa string/angka (USD); hilang/invalid → ``None``
    (unknown, BUKAN 0 — token yang GMGN tidak lacak tidak boleh dianggap
    berlikuiditas nol).
    """
    items = payload
    if isinstance(payload, dict):
        code = payload.get("code")
        if code not in (0, "0", None):
            raise RuntimeError(f"gmgn token-info code {code}")
        items = payload.get("data")
        if items is None:
            items = [v for v in payload.values() if isinstance(v, list)]
            items = items[0] if items else None
    if not isinstance(items, list):
        raise RuntimeError("gmgn token-info: respons bukan daftar token")
    out: dict[str, float | None] = {}
    for tok in items:
        if not isinstance(tok, dict):
            continue
        addr = str(tok.get("address") or "").strip()
        if addr:
            out[addr] = _float_or_none(tok.get("liquidity"))
    if not out:
        raise RuntimeError("gmgn token-info: tidak ada token di respons")
    return out


def _parse_rank(payload) -> dict[str, float]:
    """``{address: liquidity_usd}`` dari rank 100 teratas (fallback)."""
    data = payload.get("data") if isinstance(payload, dict) else None
    rank = (data or {}).get("rank") if isinstance(data, dict) else None
    if not isinstance(rank, list) or not rank:
        raise RuntimeError("gmgn rank: respons kosong")
    out: dict[str, float] = {}
    for tok in rank:
        if not isinstance(tok, dict):
            continue
        addr = str(tok.get("address") or "").strip()
        liq = _float_or_none(tok.get("liquidity"))
        if addr and liq is not None and liq > 0:
            out[addr] = liq
    if not out:
        raise RuntimeError("gmgn rank: tidak ada token berlikuiditas")
    return out


# ---------------------------------------------------------------------------
# API publik
# ---------------------------------------------------------------------------

def fetch_total_liquidity(mints, *, timeout: int = REQUEST_TIMEOUT,
                          use_cache: bool = True) -> dict[str, dict]:
    """``{mint: {"usd": float|None, "below_cutoff": bool, "source": str|None}}``.

    * ``source`` = ``"gmgn_token_info"`` (primer, angka halaman token) atau
      ``"gmgn_rank"`` (fallback peringkat 100) atau ``None`` (tak terbaca →
      caller TIDAK boleh menyaring berdasarkan mint ini);
    * ``usd`` = likuiditas total USD; ``None`` bila GMGN menjawab tapi tidak
      memuat mint itu (token tak terlacak) — hanya di fallback rank yang
      ``None`` ini pasti di bawah :data:`below_cutoff` (cutoff < ambang);
    * kegagalan satu batch POST tidak menggugurkan batch lain; mint batch
      yang gagal dialihkan ke fallback rank.

    Tidak pernah melempar: kegagalan total menghasilkan entri
    ``{"usd": None, "below_cutoff": False, "source": None}`` per mint.
    """
    wanted = [str(m).strip() for m in (mints or []) if str(m).strip()]
    ordered = list(dict.fromkeys(wanted))
    out: dict[str, dict] = {m: {"usd": None, "below_cutoff": False,
                                "source": None} for m in ordered}
    if not ordered:
        return out

    todo: list[str] = []
    with _lock:
        cache = _cache_load() if use_cache else {}
    for mint in ordered:
        entry = _cache_get(mint) if use_cache else None
        if isinstance(entry, dict) and entry.get("ok"):
            out[mint] = {"usd": _float_or_none(entry.get("usd")),
                         "below_cutoff": bool(entry.get("below_cutoff")),
                         "source": entry.get("source") or None,
                         "cutoff_usd": _float_or_none(entry.get("cutoff_usd"))}
        else:
            todo.append(mint)
    if not todo:
        return out

    post_failed: list[str] = []
    with _lock:
        cache = _cache_load() if use_cache else {}
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        try:
            payload = _post_json(TOKEN_INFO_URL,
                                 {"chain": "sol", "addresses": batch},
                                 timeout=timeout)
            parsed = _parse_token_info(payload)
        except Exception as exc:  # noqa: BLE001 - batch lain tetap jalan
            post_failed.extend(batch)
            for mint in batch:
                with _lock:
                    cache[mint] = {"at": int(time.time()), "ok": False,
                                   "error": str(exc)[:160]}
            continue
        for mint in batch:
            usd = parsed.get(mint)
            out[mint] = {"usd": usd, "below_cutoff": False,
                         "source": "gmgn_token_info"}
            with _lock:
                cache[mint] = {"at": int(time.time()), "ok": True,
                               "usd": usd, "source": "gmgn_token_info"}
    if use_cache:
        # Simpan selalu (sukses maupun gagal) — hanya kalau ada perubahan.
        with _lock:
            _cache_save(cache)

    if post_failed:
        rank_map: dict[str, float] = {}
        try:
            rank_map = _parse_rank(_get_json(RANK_URL, timeout=timeout))
            cutoff = min(rank_map.values())
        except Exception:  # noqa: BLE001 - rank mati → mint tetap unknown
            cutoff = None
        for mint in post_failed:
            if mint in rank_map:
                out[mint] = {"usd": rank_map[mint], "below_cutoff": False,
                             "source": "gmgn_rank"}
            elif cutoff is not None and cutoff < MIN_TOTAL_LIQ_USD:
                # tidak ada di 100 teratas → pasti di bawah cutoff
                # (< MIN_TOTAL_LIQ_USD) → ikut disaring.
                out[mint] = {"usd": None, "below_cutoff": True,
                             "source": "gmgn_rank", "cutoff_usd": cutoff}
            # cutoff >= ambang (jarang, tapi bisa): tak bisa
            # mengimplikasikan apa pun → mint tetap unknown (source None).
            if use_cache and out[mint]["source"] is not None:
                # Jawaban tegas dari rank dicache sebagai ok — selama outage
                # POST, scan berulang tidak perlu menembak API lagi.
                with _lock:
                    cache[mint] = {"at": int(time.time()), "ok": True,
                                   "usd": out[mint]["usd"],
                                   "below_cutoff": out[mint]["below_cutoff"],
                                   "source": out[mint]["source"],
                                   "cutoff_usd": out[mint].get("cutoff_usd")}
    return out


def attach_total_liquidity(rows, *, timeout: int = REQUEST_TIMEOUT,
                           use_cache: bool = True) -> list[dict]:
    """Tempel ``row["gmgn_liq"]`` ke tiap baris (mutasi di tempat, list sama
    dikembalikan). Baris tanpa ``ca`` mendapat entri ``ok: False``.

    ``gmgn_liq = {"ok": bool, "usd": float|None, "below_cutoff": bool,
    "source": str|None, "cutoff_usd": float|None}`` — ``ok`` True hanya bila
    GMGN memberi jawaban tegas (angka, atau "pasti di bawah cutoff" via
    fallback rank); ``ok`` False = tak terbaca → :func:`row_gmgn_gap`
    tidak menyaring apa pun.
    """
    mints = [str(row.get("ca") or "").strip() for row in (rows or [])]
    info_map = fetch_total_liquidity(mints, timeout=timeout,
                                     use_cache=use_cache)
    for row in rows or []:
        mint = str(row.get("ca") or "").strip()
        info = info_map.get(mint) if mint else None
        if not isinstance(info, dict):
            row["gmgn_liq"] = {"ok": False, "usd": None,
                               "below_cutoff": False, "source": None,
                               "cutoff_usd": None,
                               "error": "mint tidak terbawa"}
            continue
        row["gmgn_liq"] = {
            "ok": info.get("source") is not None,
            "usd": info.get("usd"),
            "below_cutoff": bool(info.get("below_cutoff")),
            "source": info.get("source"),
            "cutoff_usd": info.get("cutoff_usd"),
        }
    return rows


def _gap_amount(usd) -> str:
    """Angka likuiditas untuk teks alasan gugur.

    :func:`compact_usd` membulatkan ke satu desimal (``$499.999,99`` →
    ``$500.0K``), jadi nilai yang hanya sedikit di bawah ambang terbaca sama
    persis dengan ambangnya — ``"Likuiditas GMGN $500.0K < $500K"`` terlihat
    kontradiktif. Bila pembulatannya menabrak angka ambang, tulis nilai
    persisnya (``$499,999.99``); di luar kasus sempit itu tetap ringkas.
    """
    text = compact_usd(usd)
    if text != compact_usd(MIN_TOTAL_LIQ_USD):
        return text
    return f"${_float(usd):,.2f}"


def row_gmgn_gap(row: dict | None) -> str | None:
    """Alasan gugur bila likuiditas total GMGN **< :data:`MIN_TOTAL_LIQ_USD`**
    ($500K sejak 2026-09-17 sore; sebelumnya $1M yang ternyata mengosongkan
    seluruh tabel — PAID sendiri $884.912); ``None`` bila lolos/tak terbaca.

    Dipakai :func:`meteora_screener.row_best_gaps` sebagai saringan TERAKHIR
    (setelah volat 0 → volat 1–10% → F/V → Top10), jadi baris yang sudah
    gugur dengan alasan lebih keras tidak diberi alasan kedua. Tanpa bukti
    (``gmgn_liq`` absen/``ok: False``) tidak pernah menyaring.
    """
    row = row or {}
    item = row.get("gmgn_liq")
    if not isinstance(item, dict) or not item.get("ok"):
        return None
    usd = _float_or_none(item.get("usd"))
    if usd is not None:
        if usd < MIN_TOTAL_LIQ_USD:
            return (f"Likuiditas GMGN {_gap_amount(usd)} < "
                    f"{MIN_LABEL} — tidak ditampilkan")
        return None
    if item.get("below_cutoff"):
        cutoff = item.get("cutoff_usd")
        return (f"Likuiditas GMGN di bawah cutoff peringkat "
                f"({compact_usd(cutoff)}) < {MIN_LABEL} — tidak ditampilkan")
    return None
