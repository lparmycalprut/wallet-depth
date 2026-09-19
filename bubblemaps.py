# -*- coding: utf-8 -*-
"""Bubblemaps — status cluster & holder terbesar untuk scan Meteora.

Permintaan user 2026-09-18: *\"bisa gak kamu tambahkan status bubble map?
untuk hasil scan token meteora cluster berapa, dan holder terbesar berapa
jika dikira terlalu besar, kasih warning\"* + link
``https://v2.bubblemaps.io/map?address=...&chain=solana``

Apa yang ditampilkan:

- **cluster** = jumlah cluster yang terdeteksi Bubblemaps (wallet yang saling
  terhubung lewat transfer SOL — ``clusters`` di Data API, atau blok
  ``Cluster N (size) pct`` di halaman v2).
- **holder terbesar** = holder tunggal dengan % supply terbesar di top 80
  (atau 150) — ``nodes`` / ``holders`` di API, atau ``#1 … pct`` di halaman v2.
- **warning** bila distribusi terlalu terkonsentrasi — ambang di bawah.

Sumber data (berlapis, tanpa API key tetap jalan walau terbatas):

1. **Data API** ``https://api.bubblemaps.io/v0/tokens/map/{chain}/{token}``
   — bila env ``BUBBLEMAPS_API_KEY`` ada, ini sumber utama. Return
   ``clusters[]`` (``share`` 0-1, ``holder_count``) + ``nodes[]`` (holder
   ``share``) + ``metrics`` (``bubblemaps_score`` dll). Credit cost 25+ tapi
   paling akurat.
2. **Fallback scraping** halaman v2 ``https://v2.bubblemaps.io/map?address=...``
   — tidak butuh key, hanya HTTP GET biasa (dipakai bila key tidak ada atau
   API gagal). Parser membaca blok ``Cluster`` dan ``#N`` dari markdown hasil
   ``fetch_page`` (tool) atau HTML mentah. Fragile, tapi untuk token Solana
   yang ada di Bubblemaps halaman ini selalu berisi daftar holder + cluster
   seperti contoh MCAT di prompt (``Cluster 1 (8) 1.34%`` / ``#1 Meteora … 4.85%``).

Cache berkas (``bubblemaps_cache.json``, TTL 15 menit) supaya rerun Streamlit
tidak menembak endpoint pihak ketiga untuk mint yang sama — mirip
``rugchecker`` / ``gmgn_liquidity``.

Risk logic (konservatif, bisa di-tune):

- Top holder ≥ 10%  → BERISIKO (merah)
- Top holder ≥ 5%   → WASPADA (kuning tua)
- Largest cluster ≥ 15% → BERISIKO
- Largest cluster ≥ 8%  → WASPADA
- Cluster count ≥ 10 → WASPADA (banyak wallet saling terhubung)
- Total cluster supply (sum share) ≥ 20% → BERISIKO
- Bubblemaps score (0-100, tinggi = lebih desentral) < 30 → BERISIKO,
  < 60 → WASPADA (bila ada)

Verdict akhir = level terburuk dari semua rule. Warning text = gabungan alasan.

Kolom **Bubble Map** di 🏆 Scan Best Pool dulu menampilkan:

- Baris utama: ``X cluster · Top Y%``
- Baris kecil: ``largest Z% (N wallet)`` atau ``score S``
- Tooltip: rincian semua cluster + top holders + link v2 + alasan warning

Tidak pernah membuang baris — hanya informasi, seperti RugCheck.

**Update 2026-09-19 — kolomnya DIHAPUS** (permintaan user: *"hapus tentang
bubblemap, sisakan hyperlink ke bubblemapnya saja"*). Yang tersisa di UI
hanya tautan 🫧 ke ``v2.bubblemaps.io`` di kolom **Pool**
(:func:`links.bubblemap_icon_link_html`), dan
:func:`meteora_screener.scan_best_lane` tidak lagi memanggil
:func:`attach_to_rows` (kwarg ``bubblemap`` default ``False``). Modul ini
**tidak dihapus**: fungsinya tetap utuh dan bisa dinyalakan lagi dengan
``scan_best_lane(..., bubblemap=True)`` — laporan cluster/holder-nya masih
bisa dipakai tooling/skrip di luar tabel, hanya tidak ditampilkan lagi.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Konstanta & threshold warning
# ---------------------------------------------------------------------------

API_BASE = "https://api.bubblemaps.io"
MAP_ENDPOINT = "/v0/tokens/map/{chain}/{token_address}"
V2_PAGE_URL = "https://v2.bubblemaps.io/map?address={address}&chain={chain}"

CACHE_PATH = Path(__file__).resolve().parent / "bubblemaps_cache.json"
CACHE_TTL_OK = 900          # 15 menit — cluster tidak berubah tiap detik
CACHE_TTL_FAIL = 300        # 5 menit untuk kegagalan
CACHE_MAX_ENTRIES = 400

REQUEST_TIMEOUT = 18
WORKERS = 4
CHAIN = "solana"

# Threshold warning — bisa di-tune
TOP_HOLDER_RISK_PCT = 10.0
TOP_HOLDER_WARN_PCT = 5.0
LARGEST_CLUSTER_RISK_PCT = 15.0
LARGEST_CLUSTER_WARN_PCT = 8.0
CLUSTER_COUNT_WARN = 10
TOTAL_CLUSTER_RISK_PCT = 20.0
TOTAL_CLUSTER_WARN_PCT = 12.0
SCORE_RISK = 30.0
SCORE_WARN = 60.0

VERDICT_RISK = ("BERISIKO", "#dc2626")
VERDICT_WARN = ("WASPADA", "#b45309")
VERDICT_SAFE = ("AMAN", "#15803d")
VERDICT_UNKNOWN = ("—", "")

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/152.0.0.0 Safari/537.36"),
}

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _float(v, default=0.0) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return n if math.isfinite(n) else default


def _float_or_none(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def compact_pct(v: float | None) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except Exception:
        return "—"
    if not math.isfinite(n):
        return "—"
    return f"{n:.2f}%"


def _cache_load() -> dict:
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _cache_save(cache: dict) -> None:
    try:
        if len(cache) > CACHE_MAX_ENTRIES:
            ordered = sorted(cache.items(),
                             key=lambda kv: _float((kv[1] or {}).get("at")))
            cache = dict(ordered[-CACHE_MAX_ENTRIES:])
        p = Path(CACHE_PATH)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _cache_get(mint: str) -> tuple[bool, dict | None]:
    entry = _cache_load().get(mint)
    if not isinstance(entry, dict):
        return False, None
    age = time.time() - _float(entry.get("at"))
    ttl = CACHE_TTL_OK if entry.get("ok") else CACHE_TTL_FAIL
    if age > ttl:
        return False, None
    data = entry.get("data")
    return True, data if isinstance(data, dict) else None


def _cache_put(mint: str, payload: dict, *, ok: bool) -> None:
    cache = _cache_load()
    cache[mint] = {"at": int(time.time()), "ok": bool(ok), "data": payload}
    _cache_save(cache)


def bubblemap_url(mint: str, chain: str = CHAIN) -> str:
    """Link ke v2 bubblemaps untuk token."""
    from links import safe_url_part
    addr = safe_url_part(mint)
    ch = safe_url_part(chain)
    return V2_PAGE_URL.format(address=addr, chain=ch)


# ---------------------------------------------------------------------------
# Fetch — API dengan key, fallback scraping
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    # env var utama, plus fallback nama lain
    for k in ("BUBBLEMAPS_API_KEY", "BUBBLEMAPS_KEY", "BMT_API_KEY"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return ""


def _http_get_json(url: str, *, headers: dict | None = None, timeout: int = REQUEST_TIMEOUT):
    """GET JSON — coba curl_cffi dulu (TLS browser), lalu requests."""
    hdrs = {**_HEADERS, **(headers or {})}
    # curl_cffi
    try:
        from curl_cffi import requests as creq
        for ident in ("chrome", "chrome131", "safari17_0"):
            try:
                r = creq.get(url, impersonate=ident, timeout=timeout, headers=hdrs)
                if r.status_code == 200:
                    try:
                        return r.json()
                    except Exception:
                        # bukan JSON — mungkin HTML (untuk scraping path)
                        return r.text
                if r.status_code in (401, 403):
                    # auth error — jangan coba identitas lain
                    raise RuntimeError(f"bubblemaps HTTP {r.status_code}")
            except RuntimeError:
                raise
            except Exception:
                continue
    except ImportError:
        pass
    except Exception:
        pass
    # requests fallback
    try:
        import requests
        r = requests.get(url, headers=hdrs, timeout=timeout)
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return r.text
        raise RuntimeError(f"bubblemaps HTTP {r.status_code}")
    except ImportError as e:
        raise RuntimeError(f"bubblemaps: no http client ({e})") from e


def fetch_raw_api(mint: str, *, chain: str = CHAIN, timeout: int = REQUEST_TIMEOUT) -> dict:
    """Fetch dari Data API resmi — butuh API key."""
    key = _get_api_key()
    if not key:
        raise RuntimeError("bubblemaps API key tidak ada")
    url = f"{API_BASE}{MAP_ENDPOINT.format(chain=chain, token_address=mint)}?limit=80&return_clusters=true&return_nodes=true"
    headers = {"X-ApiKey": key}
    payload = _http_get_json(url, headers=headers, timeout=timeout)
    if not isinstance(payload, dict):
        raise RuntimeError("bubblemaps API: respons bukan JSON")
    return payload


def fetch_raw_scrape(mint: str, *, chain: str = CHAIN, timeout: int = REQUEST_TIMEOUT) -> str:
    """Fallback: scrape halaman v2 — return HTML/markdown text."""
    url = V2_PAGE_URL.format(address=mint, chain=chain)
    # coba JSON API tanpa key via fetch_page? tapi di sini pakai http client biasa
    # yang mungkin diblokir di sandbox, tapi di prod biasanya jalan.
    # Kita coba ambil HTML mentah.
    try:
        data = _http_get_json(url, timeout=timeout)
        if isinstance(data, str):
            return data
        # kalau kebetulan JSON, stringify
        return json.dumps(data)
    except Exception as exc:
        raise RuntimeError(f"bubblemaps scrape: {exc}") from exc


# ---------------------------------------------------------------------------
# Parse — API JSON vs scraped v2 page
# ---------------------------------------------------------------------------

def _parse_api_payload(payload: dict) -> dict:
    """Parse MapDataV0 dari API resmi."""
    if not isinstance(payload, dict):
        return {}
    clusters_raw = payload.get("clusters") or []
    nodes_raw = payload.get("nodes") or {}
    # nodes bisa dict dengan holders list atau langsung list
    holders = []
    if isinstance(nodes_raw, dict):
        # NodesDataV0: punya 'nodes' key?
        inner = nodes_raw.get("nodes") or nodes_raw.get("holders") or []
        if isinstance(inner, list):
            holders = inner
        else:
            # mungkin nodes_raw sendiri adalah list? (fallback)
            holders = []
    elif isinstance(nodes_raw, list):
        holders = nodes_raw

    # Normalize clusters
    clusters = []
    for c in clusters_raw:
        if not isinstance(c, dict):
            continue
        share = _float_or_none(c.get("share"))
        # share 0-1 → %
        pct = share * 100.0 if share is not None else None
        clusters.append({
            "share": share,
            "pct": pct,
            "amount": _float_or_none(c.get("amount")),
            "holder_count": int(_float(c.get("holder_count"), 0)),
            "holders": list(c.get("holders") or []),
        })

    # Normalize holders/nodes
    top_holders = []
    for n in holders:
        if not isinstance(n, dict):
            continue
        # holder_data atau langsung share
        hd = n.get("holder_data") if isinstance(n.get("holder_data"), dict) else n
        share = _float_or_none(hd.get("share") if isinstance(hd, dict) else n.get("share"))
        pct = share * 100.0 if share is not None else None
        addr = str(n.get("address") or hd.get("address") or "").strip()
        rank = int(_float(hd.get("rank") or n.get("rank"), 0))
        amount = _float_or_none(hd.get("amount") or n.get("amount"))
        top_holders.append({
            "address": addr,
            "share": share,
            "pct": pct,
            "rank": rank,
            "amount": amount,
        })

    # Sort holders by share desc
    top_holders.sort(key=lambda x: -(x.get("pct") or 0))

    metrics = payload.get("metrics") or {}
    scores = metrics.get("scores") or {}
    supply_stats = metrics.get("supply_stats") or {}

    return {
        "clusters": clusters,
        "holders": top_holders,
        "metrics": metrics,
        "scores": scores,
        "supply_stats": supply_stats,
    }


# Regex untuk scraping v2 page (markdown converted)
# Contoh blok:
# Cluster 1
# (8)
# 1.34%
# dan
# #1
# Meteora Authority...
# 4.85%

_CLUSTER_RE = re.compile(
    r"Cluster\s+(\d+)\s*[\r\n]+\s*\(?\s*(\d+)\s*\)?\s*[\r\n]+\s*([\d.,]+)\s*%",
    re.IGNORECASE,
)
_HOLDER_RE = re.compile(
    r"#\s*(\d+)\s*[\r\n]+\s*(.+?)\s*[\r\n]+\s*([\d.,]+)\s*%",
    re.IGNORECASE | re.DOTALL,
)

def _parse_scraped_text(text: str) -> dict:
    """Parse teks halaman v2 (markdown) jadi clusters + holders."""
    if not text:
        return {"clusters": [], "holders": []}
    # Normalisasi: ganti \r, trim
    txt = str(text)
    # Cluster
    clusters = []
    for m in _CLUSTER_RE.finditer(txt):
        try:
            num = int(m.group(1))
            size = int(m.group(2)) if m.group(2) else 0
            pct_str = m.group(3).replace(",", ".")
            pct = float(pct_str)
            clusters.append({
                "share": pct / 100.0,
                "pct": pct,
                "holder_count": size,
                "holders": [],
                "cluster_num": num,
            })
        except Exception:
            continue

    # Holders — hanya ambil #N yang jelas holder (bukan cluster)
    holders = []
    for m in _HOLDER_RE.finditer(txt):
        try:
            rank = int(m.group(1))
            # filter: kalau label mengandung "Cluster" skip (sudah ditangani)
            label = m.group(2).strip()
            if "Cluster" in label:
                continue
            pct_str = m.group(3).replace(",", ".")
            pct = float(pct_str)
            # label bisa alamat singkat atau nama
            # alamat: ambil yang mirip base58
            # Simpan label sebagai address placeholder
            holders.append({
                "address": label[:80],
                "share": pct / 100.0,
                "pct": pct,
                "rank": rank,
                "amount": None,
                "label": label,
            })
        except Exception:
            continue

    # Sort holders by rank, lalu pct desc
    holders.sort(key=lambda x: (x.get("rank", 9999), -(x.get("pct") or 0)))
    # Deduplicate by rank keeping first
    seen_rank = set()
    uniq_holders = []
    for h in holders:
        r = h.get("rank")
        if r in seen_rank:
            continue
        seen_rank.add(r)
        uniq_holders.append(h)
    holders = uniq_holders
    holders.sort(key=lambda x: -(x.get("pct") or 0))

    return {"clusters": clusters, "holders": holders, "metrics": {}, "scores": {}, "supply_stats": {}}


# ---------------------------------------------------------------------------
# Summarize — verdict + warning
# ---------------------------------------------------------------------------

def summarize(payload: dict | str, *, source: str = "api") -> dict:
    """Ringkasan satu laporan Bubblemaps untuk kolom Bubble Map.

    ``payload`` bisa dict (API) atau str (scraped HTML). Return selalu dict
    dengan ``ok`` bool.

    Struktur return:
    {
      ok: bool,
      cluster_count: int,
      largest_cluster_pct: float|None,
      largest_cluster_size: int|None,
      total_cluster_pct: float|None,
      top_holder_pct: float|None,
      top_holder_address: str,
      top_holder_label: str,
      clusters: [...],
      holders: [...],
      bubblemaps_score: float|None,
      gini: float|None,
      verdict: "AMAN"/"WASPADA"/"BERISIKO"/"—",
      color: hex,
      warning: bool,
      warnings: [str],
      checked_at: epoch,
      source: "api"/"scrape"/"cache",
      url: bubblemap_url
    }
    """
    now = int(time.time())
    if isinstance(payload, str):
        parsed = _parse_scraped_text(payload)
        src = "scrape"
    elif isinstance(payload, dict) and payload.get("clusters") is not None or payload.get("holders") is not None:
        # sudah parsed intermediate
        if "clusters" in payload and "holders" in payload and "metrics" in payload:
            parsed = payload
        else:
            parsed = _parse_api_payload(payload)
        src = source
    elif isinstance(payload, dict):
        # raw API payload
        if payload.get("error"):
            return {
                "ok": False,
                "error": str(payload.get("error"))[:200],
                "verdict": VERDICT_UNKNOWN[0],
                "color": VERDICT_UNKNOWN[1],
                "cluster_count": 0,
                "checked_at": now,
                "source": src if 'src' in locals() else source,
            }
        parsed = _parse_api_payload(payload)
        src = source
    else:
        return {
            "ok": False,
            "error": "payload tidak dikenal",
            "verdict": VERDICT_UNKNOWN[0],
            "color": VERDICT_UNKNOWN[1],
            "cluster_count": 0,
            "checked_at": now,
            "source": "unknown",
        }

    clusters = parsed.get("clusters") or []
    holders = parsed.get("holders") or []
    scores = parsed.get("scores") or {}
    metrics = parsed.get("metrics") or {}

    cluster_count = len(clusters)
    largest = max(clusters, key=lambda c: c.get("pct") or 0) if clusters else None
    largest_pct = largest.get("pct") if largest else None
    largest_size = largest.get("holder_count") if largest else None
    total_cluster_pct = sum(c.get("pct") or 0 for c in clusters) if clusters else 0.0

    top_holder = holders[0] if holders else None
    top_pct = top_holder.get("pct") if top_holder else None
    top_addr = str(top_holder.get("address") or "") if top_holder else ""
    top_label = str(top_holder.get("label") or top_addr) if top_holder else ""

    bubblemaps_score = _float_or_none(scores.get("bubblemaps_score"))
    gini = _float_or_none(scores.get("gini_index"))
    hhi = _float_or_none(scores.get("herfindahl_hirschman_index"))
    naka = scores.get("nakamoto_coefficient")

    # Risk evaluation
    warnings = []
    level = 0  # 0 aman, 1 waspada, 2 berisiko

    if top_pct is not None:
        if top_pct >= TOP_HOLDER_RISK_PCT:
            warnings.append(f"holder terbesar {top_pct:.2f}% ≥ {TOP_HOLDER_RISK_PCT:g}% — dominan")
            level = max(level, 2)
        elif top_pct >= TOP_HOLDER_WARN_PCT:
            warnings.append(f"holder terbesar {top_pct:.2f}% ≥ {TOP_HOLDER_WARN_PCT:g}% — cukup besar")
            level = max(level, 1)

    if largest_pct is not None:
        if largest_pct >= LARGEST_CLUSTER_RISK_PCT:
            warnings.append(f"cluster terbesar {largest_pct:.2f}% ≥ {LARGEST_CLUSTER_RISK_PCT:g}% — terpusat")
            level = max(level, 2)
        elif largest_pct >= LARGEST_CLUSTER_WARN_PCT:
            warnings.append(f"cluster terbesar {largest_pct:.2f}% ≥ {LARGEST_CLUSTER_WARN_PCT:g}% — waspada")
            level = max(level, 1)

    if cluster_count >= CLUSTER_COUNT_WARN:
        warnings.append(f"{cluster_count} cluster terdeteksi — banyak wallet saling terhubung")
        level = max(level, 1)

    if total_cluster_pct >= TOTAL_CLUSTER_RISK_PCT:
        warnings.append(f"total cluster {total_cluster_pct:.2f}% ≥ {TOTAL_CLUSTER_RISK_PCT:g}% supply — bundling besar")
        level = max(level, 2)
    elif total_cluster_pct >= TOTAL_CLUSTER_WARN_PCT:
        warnings.append(f"total cluster {total_cluster_pct:.2f}% ≥ {TOTAL_CLUSTER_WARN_PCT:g}%")
        level = max(level, 1)

    if bubblemaps_score is not None:
        if bubblemaps_score < SCORE_RISK:
            warnings.append(f"bubblemaps score {bubblemaps_score:.0f} < {SCORE_RISK:g} — distribusi buruk")
            level = max(level, 2)
        elif bubblemaps_score < SCORE_WARN:
            warnings.append(f"bubblemaps score {bubblemaps_score:.0f} < {SCORE_WARN:g} — kurang desentral")
            level = max(level, 1)

    if level == 2:
        verdict, color = VERDICT_RISK
    elif level == 1:
        verdict, color = VERDICT_WARN
    else:
        verdict, color = VERDICT_SAFE
        if not clusters and not holders:
            # tanpa bukti jangan klaim aman
            verdict, color = VERDICT_UNKNOWN

    # Jika tidak ada data sama sekali, ok=False
    if not clusters and not holders:
        # tapi kalau ada score, tetap ok
        if bubblemaps_score is None and not metrics:
            return {
                "ok": False,
                "error": "bubblemaps tidak mengembalikan holder/cluster",
                "verdict": VERDICT_UNKNOWN[0],
                "color": VERDICT_UNKNOWN[1],
                "cluster_count": 0,
                "checked_at": now,
                "source": src,
            }

    return {
        "ok": True,
        "cluster_count": cluster_count,
        "largest_cluster_pct": largest_pct,
        "largest_cluster_size": largest_size,
        "largest_cluster": largest,
        "total_cluster_pct": total_cluster_pct,
        "top_holder_pct": top_pct,
        "top_holder_address": top_addr,
        "top_holder_label": top_label,
        "clusters": clusters[:20],  # batasi untuk tooltip
        "holders": holders[:15],
        "all_clusters_count": cluster_count,
        "bubblemaps_score": bubblemaps_score,
        "gini_index": gini,
        "hhi": hhi,
        "nakamoto": naka,
        "supply_stats": parsed.get("supply_stats") or {},
        "verdict": verdict,
        "color": color,
        "warning": level >= 1,
        "risk_level": level,  # 0,1,2
        "warnings": warnings,
        "checked_at": now,
        "source": src,
    }


def fetch_one(mint: str, *, chain: str = CHAIN, timeout: int = REQUEST_TIMEOUT, use_cache: bool = True) -> dict:
    """Fetch + summarize satu mint — cache + API + scrape fallback."""
    mint = str(mint).strip()
    if not mint:
        return {"ok": False, "error": "mint kosong", "verdict": VERDICT_UNKNOWN[0], "color": VERDICT_UNKNOWN[1]}

    if use_cache:
        fresh, cached = _cache_get(mint)
        if fresh and isinstance(cached, dict):
            # cached sudah dalam bentuk summary? kita simpan summary langsung
            # supaya tidak parse ulang
            return cached

    # 1) coba API resmi bila key ada
    api_key = _get_api_key()
    last_err = ""
    if api_key:
        try:
            raw = fetch_raw_api(mint, chain=chain, timeout=timeout)
            summ = summarize(raw, source="api")
            summ["url"] = bubblemap_url(mint, chain)
            if use_cache and summ.get("ok"):
                _cache_put(mint, summ, ok=True)
            elif use_cache:
                _cache_put(mint, {"ok": False, "error": summ.get("error", "api gagal")}, ok=False)
            return summ
        except Exception as exc:
            last_err = str(exc)[:200]

    # 2) fallback scraping v2 page
    try:
        raw_text = fetch_raw_scrape(mint, chain=chain, timeout=timeout)
        summ = summarize(raw_text, source="scrape")
        summ["url"] = bubblemap_url(mint, chain)
        if use_cache and summ.get("ok"):
            _cache_put(mint, summ, ok=True)
        else:
            # scrape gagal parse → simpan fail singkat
            if use_cache and not summ.get("ok"):
                _cache_put(mint, {"ok": False, "error": summ.get("error", last_err or "scrape gagal")}, ok=False)
        return summ
    except Exception as exc:
        err = str(exc)[:200] or last_err
        if use_cache:
            _cache_put(mint, {"ok": False, "error": err}, ok=False)
        return {
            "ok": False,
            "error": err or "bubblemaps gagal",
            "verdict": VERDICT_UNKNOWN[0],
            "color": VERDICT_UNKNOWN[1],
            "cluster_count": 0,
            "checked_at": int(time.time()),
            "source": "fail",
            "url": bubblemap_url(mint, chain),
        }


def check_tokens(mints, *, chain: str = CHAIN, workers: int = WORKERS,
                 timeout: int = REQUEST_TIMEOUT, use_cache: bool = True) -> dict[str, dict]:
    """{mint: summary} — paralel, cache, gagal jadi —."""
    wanted = [str(m).strip() for m in (mints or []) if str(m).strip()]
    ordered = list(dict.fromkeys(wanted))
    out: dict[str, dict] = {}
    todo: list[str] = []
    for mint in ordered:
        if use_cache:
            fresh, cached = _cache_get(mint)
            if fresh and isinstance(cached, dict):
                out[mint] = cached
                continue
        todo.append(mint)

    if not todo:
        return out

    def _job(m: str):
        try:
            return m, fetch_one(m, chain=chain, timeout=timeout, use_cache=use_cache)
        except Exception as exc:
            return m, {"ok": False, "error": str(exc)[:200], "verdict": VERDICT_UNKNOWN[0], "color": VERDICT_UNKNOWN[1]}

    workers = max(1, min(int(workers), 6))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, mint) for mint in todo]
        for fut in as_completed(futures):
            mint, summ = fut.result()
            out[mint] = summ
    # urutkan sesuai input
    return {m: out.get(m, {"ok": False, "error": "tanpa respons", "verdict": "—", "color": ""}) for m in ordered}


def attach_to_rows(rows, *, chain: str = CHAIN, workers: int = WORKERS,
                   timeout: int = REQUEST_TIMEOUT, use_cache: bool = True) -> list[dict]:
    """Tempel row['bubblemap'] ke baris listing Best Pool."""
    rows = [dict(r or {}) for r in (rows or [])]
    if not rows:
        return rows
    mints = [str(r.get("ca") or "").strip() for r in rows]
    reports = check_tokens(mints, chain=chain, workers=workers, timeout=timeout, use_cache=use_cache)
    for r in rows:
        mint = str(r.get("ca") or "").strip()
        r["bubblemap"] = reports.get(mint) or {"ok": False, "error": "mint tidak terbawa", "verdict": "—", "color": ""}
    return rows


def cell_parts(summary) -> tuple[str, str, str]:
    """(angka, baris kecil, tooltip) kolom Bubble Map — dibaca UI.

    Tanpa laporan → — + alasan.
    Dengan laporan → verdict + cluster + top holder.
    """
    item = summary if isinstance(summary, dict) else None
    if not item or not item.get("ok"):
        err = str((item or {}).get("error") or "belum di-fetch")
        url = (item or {}).get("url") or ""
        tip = f"bubblemaps tidak menghasilkan laporan: {err} — kolom menulis —, bukan AMAN (tanpa bukti tidak ada verdict)"
        if url:
            tip += f" — cek manual: {url}"
        return ("—", "bubblemap", tip)

    cluster_count = int(item.get("cluster_count") or 0)
    largest_pct = item.get("largest_cluster_pct")
    top_pct = item.get("top_holder_pct")
    verdict = str(item.get("verdict") or "—")
    color = str(item.get("color") or "")

    # baris utama: verdict + cluster count
    main = verdict
    if color and verdict != "—":
        # warna akan di-apply di UI layer, di sini plain
        pass

    # sub: cluster + top holder
    sub_bits = []
    sub_bits.append(f"{cluster_count} cluster" if cluster_count != 1 else "1 cluster")
    if top_pct is not None:
        sub_bits.append(f"Top {top_pct:.2f}%")
    elif largest_pct is not None:
        sub_bits.append(f"Largest {largest_pct:.2f}%")
    sub = " · ".join(sub_bits) if sub_bits else "bubblemap"

    # tooltip panjang
    head = f"Bubble Map {verdict} — {cluster_count} cluster"
    bits = []
    if top_pct is not None:
        bits.append(f"holder terbesar {top_pct:.2f}% ({item.get('top_holder_label') or item.get('top_holder_address') or 'unknown'})")
    if largest_pct is not None:
        size = item.get("largest_cluster_size")
        size_txt = f" ({size} wallet)" if size else ""
        bits.append(f"cluster terbesar {largest_pct:.2f}%{size_txt}")
    total_pct = item.get("total_cluster_pct")
    if total_pct:
        bits.append(f"total cluster {total_pct:.2f}% supply")
    score = item.get("bubblemaps_score")
    if score is not None:
        bits.append(f"bubblemaps score {score:.0f}/100 (tinggi = lebih desentral)")
    gini = item.get("gini_index")
    if gini is not None:
        bits.append(f"gini {gini:.3f}")
    # list cluster kecil
    clusters = item.get("clusters") or []
    if clusters:
        cl_txt = ", ".join(f"{c.get('pct',0):.2f}% ({c.get('holder_count',0)}w)" for c in clusters[:8])
        bits.append(f"clusters: {cl_txt}" + (f" +{len(clusters)-8} lain" if len(clusters) > 8 else ""))
    holders = item.get("holders") or []
    if holders:
        h_txt = ", ".join(f"#{h.get('rank', '?')} {h.get('pct',0):.2f}%" for h in holders[:5])
        bits.append(f"top holders: {h_txt}")

    if item.get("warnings"):
        bits.append("⚠️ " + " · ".join(item["warnings"]))

    url = item.get("url") or ""
    if url:
        bits.append(f"link: {url}")

    tooltip = head + ". " + " · ".join(bits) if bits else head
    return main, sub, tooltip


def warning_badge(summary) -> tuple[bool, str, str]:
    """Helper untuk UI — (is_warning, badge_text, color).

    is_warning True bila risk_level >=1.
    badge_text mis. '⚠️ Top 12% · Cluster 18%'.
    """
    item = summary if isinstance(summary, dict) else None
    if not item or not item.get("ok"):
        return False, "", ""
    if not item.get("warning"):
        return False, "", ""
    lvl = int(item.get("risk_level") or 0)
    color = "#dc2626" if lvl >= 2 else "#b45309"
    warns = item.get("warnings") or []
    # ringkas 2 alasan pertama
    txt = " · ".join(warns[:2]) if warns else item.get("verdict") or "WASPADA"
    # potong panjang
    if len(txt) > 80:
        txt = txt[:77] + "..."
    return True, f"⚠️ {txt}", color
