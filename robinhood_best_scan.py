# -*- coding: utf-8 -*-
"""Scan Best Robinhood Coin — listing GMGN (chain robinhood) + dust Blockscout.

Permintaan user 2026-09-10. Listing token Robinhood Chain (chain id 4663)
diambil dari endpoint **publik** GMGN (bukan endpoint ``follow_token`` yang
butuh auth + token 30 menit):

    GET https://gmgn.ai/defi/quotation/v1/rank/robinhood/swaps/6h
        ?orderby=volume&direction=desc&limit=50

(diverifikasi langsung 2026-09-10, lihat ``docs/gmgn_api.md``). Satu respons
listing sudah membawa ``top_10_holder_rate`` (untuk filter top holder) dan
penanda **Dexboost** (``dexscr_boost_ts`` / ``dexscr_boost_fee``). Dust
holder (0 < nilai ≤ $10) **tidak** ada di payload GMGN — dihitung dari
Blockscout lewat ``robinhood_holders.analyze_token`` (satu-satunya sumber
holder chain 4663; GMGN tidak meng-index chain ini).

Rule (permintaan user 2026-09-10):

- data = top token berdasarkan **volume 6 jam terakhir** (interval ``6h``),
- hanya tampilkan **top 10 holder < 30%**,
- hanya tampilkan **dust ≤ 0,05% MC** (dust = wallet 0 < nilai ≤ $10),
- urutan: **dust % MC terkecil** dulu, lalu **volume 6 jam terbesar**,
- pernah **Dexboost** = poin tambah (badge 🚀 + rekap di kepala card),
- **tidak ada budget waktu**: semua kandidat ditunggu sampai selesai (lihat
  :func:`scan_candidates`).

Card ini dirender di halaman utama (``app.py``) di bawah Watchlist Robinhood;
⭐-nya memasukkan token ke **Watchlist Robinhood** LP (scan cron ±5 menit).
Detail karakteristik card = tooltip pada teks judul (``RH_SCAN_TOOLTIP``),
bukan caption panjang di badan card (konvensi 2026-09-10).
"""
from __future__ import annotations

import html
import time

import holder_history

GMGN_ORIGIN = "https://gmgn.ai"
# Endpoint ranking publik (GET, tanpa auth) — chain di path, interval di path.
RANK_PATH = "/defi/quotation/v1/rank/robinhood/swaps/{interval}"

# "ini pakai volume 6 jam terakhir" (2026-09-10).
SCAN_INTERVAL = "6h"
# Jumlah kandidat dari listing GMGN (curl user memakai limit=50).
DEFAULT_LIMIT = 50
DEFAULT_WORKERS = 6
ORDER_BY = "volume"
DIRECTION = "desc"

# Ambang rule scan (permintaan user 2026-09-10):
# - hanya dust ≤ 0,05% MC yang ditampilkan (sama seperti DUST_SCAN_HIDE_PCT
#   milik Scan Meteora, cuma ambangnya lebih ketat);
# - hanya top 10 holder < 30% yang ditampilkan.
RH_SCAN_MAX_DUST_PCT = 0.05
RH_SCAN_MAX_TOP10_PCT = 30.0

CARD_TITLE = "🦅 Scan Best Robinhood Coin"
SESSION_KEY = "rh_best_scan"

# Detail karakteristik card = tooltip judul (konvensi 2026-09-10; permintaan
# user: "ini juga bikin tooltip saja") — caption panjang di badan card dihapus,
# seluruh isinya pindah ke sini. Atribut ``title`` browser tidak mengenal
# markdown, jadi teksnya plain tanpa ``**``; ambang diambil dari konstanta
# RH_SCAN_* di atas supaya tidak pernah beda dengan rule yang jalan.
RH_SCAN_TOOLTIP = (
    "Listing GMGN Robinhood Chain (defi/quotation/v1/rank/robinhood/swaps/6h, "
    "tanpa auth) diurutkan volume 6 jam terakhir. Yang ditampilkan hanya coin "
    f"dengan top 10 holder < {RH_SCAN_MAX_TOP10_PCT:g}% dan dust holder ≤ "
    f"{RH_SCAN_MAX_DUST_PCT:g}% MC — dust = wallet 0 < nilai ≤ $10 dari "
    "Blockscout (LP/pool disingkirkan, scan FULL). Urutan: dust % MC terkecil "
    "dulu, lalu volume 6 jam terbesar. Coin yang pernah Dexboost dapat poin "
    "tambah (badge 🚀). Honeypot otomatis dikeluarkan. Tombol per baris: 📋 "
    "copy CA · ⭐ tambah ke Watchlist Robinhood LP (halaman utama, scan cron "
    "±5 menit). Token ber-holder puluhan ribu butuh paginasi Blockscout yang "
    "panjang — semua kandidat tetap ditunggu sampai selesai (budget waktu per "
    "kandidat sudah dihapus), jadi scan bisa makan waktu puluhan menit.")


def _short_error(error) -> str:
    """Ringkasan error koneksi untuk caption UI (bukan trace mentah)."""
    text = str(error or "").strip()
    if not text:
        return ""
    if "SSLError" in text or "TLS/SSL" in text:
        return ("koneksi TLS ke gmgn.ai terputus — host/jaringan "
                "(sandbox/datacenter) memblokir; dari browser & Streamlit "
                "Cloud endpoint ini publik dan normal")
    if "timed out" in text.lower() or "Timeout" in text:
        return "timeout koneksi ke gmgn.ai"
    return text[:200]


HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "origin": GMGN_ORIGIN,
    "referer": GMGN_ORIGIN + "/trend?chain=robinhood",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/152.0.0.0 Safari/537.36"),
}


# ---------------------------------------------------------------------------
# Klien listing GMGN (GET publik)
# ---------------------------------------------------------------------------
def _rank_url(interval: str = SCAN_INTERVAL,
              limit: int = DEFAULT_LIMIT) -> str:
    return (f"{GMGN_ORIGIN}{RANK_PATH.format(interval=interval)}"
            f"?orderby={ORDER_BY}&direction={DIRECTION}&limit={int(limit)}")


def _get_json(url: str, timeout: int = 25):
    """GET JSON GMGN: curl_cffi (fingerprint browser) → requests biasa.

    GMGN di balik Cloudflare; fingerprint browser terbukti diperlukan untuk
    endpoint ``trs/…`` (lihat ``gmgn_screener.py``), jadi urutan coba-nya
    sama. Return ``(payload, error)`` — ``payload`` None bila semua jalur
    gagal / ``code`` API tidak 0.
    """
    last_error = ""

    def _parse(response):
        nonlocal last_error
        if response.status_code == 200:
            try:
                payload = response.json() or {}
            except Exception as exc:  # noqa: BLE001
                last_error = f"bukan JSON: {exc}"
                return None
            if payload.get("code") == 0:
                return payload
            last_error = (f"API code {payload.get('code')}: "
                          f"{payload.get('message') or payload.get('reason')}")
        else:
            last_error = f"HTTP {response.status_code}"
        return None

    try:
        from curl_cffi import requests as client
    except ImportError:
        client = None
    if client is not None:
        for identity in ("chrome", "chrome131", "safari17_0"):
            try:
                payload = _parse(client.get(url, impersonate=identity,
                                            timeout=timeout,
                                            headers=HEADERS))
                if payload is not None:
                    return payload, ""
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
    try:
        import requests
        payload = _parse(requests.get(url, timeout=timeout, headers=HEADERS))
        if payload is not None:
            return payload, ""
    except Exception as exc:  # noqa: BLE001
        last_error = str(exc)
    return None, last_error


def _number(token: dict, key: str) -> float:
    try:
        return float(token.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def rank_row(token: dict) -> dict:
    """Normalisasi satu token listing GMGN (``data.rank[]``) ke baris scan.

    ``volume`` mengikuti interval URL (default 6 jam — ``SCAN_INTERVAL``).
    ``top_10_holder_rate`` datang sebagai fraksi 0-1 → disimpan persen.
    **Dexboost** = pernah ada boost DEX Screener: ``dexscr_boost_ts > 0``
    (timestamp boost terakhir) atau ``dexscr_boost_fee > 0`` (biaya boost).
    """
    created = _number(token, "creation_timestamp")
    if created <= 0:
        created = _number(token, "open_timestamp")
    age_hours = (max(0.0, (time.time() - created) / 3600.0)
                 if created > 0 else None)
    top10 = _number(token, "top_10_holder_rate")
    if 0 < top10 <= 1:
        top10 *= 100.0
    boost_ts = _number(token, "dexscr_boost_ts")
    boost_fee = _number(token, "dexscr_boost_fee")
    return {
        "ca": str(token.get("address") or "").strip().lower(),
        "symbol": str(token.get("symbol") or "?"),
        "name": str(token.get("name") or ""),
        "price": _number(token, "price"),
        "mc": _number(token, "market_cap"),
        "liq": _number(token, "liquidity"),
        "volume": _number(token, "volume"),
        "swaps": int(_number(token, "swaps")),
        "buys": int(_number(token, "buys")),
        "sells": int(_number(token, "sells")),
        "holders": int(_number(token, "holder_count")),
        "top10_pct": round(top10, 2),
        "change_pct": _number(token, "price_change_percent"),
        "change_1h": _number(token, "price_change_percent1h"),
        "honeypot": bool(_number(token, "is_honeypot")),
        "renounced": bool(_number(token, "is_renounced")),
        "dexboost": bool(boost_ts > 0 or boost_fee > 0),
        "dexboost_fee": int(boost_fee),
        "created_at": int(created) if created > 0 else 0,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "launchpad": str(token.get("launchpad_platform")
                         or token.get("launchpad") or ""),
    }


def fetch_ranking(interval: str = SCAN_INTERVAL, limit: int = DEFAULT_LIMIT,
                  timeout: int = 25, debug: bool = False):
    """Top token GMGN chain robinhood. Return ``(rows, error)``."""
    payload, error = _get_json(_rank_url(interval, limit), timeout=timeout)
    if payload is None:
        if debug and error:
            print(f"GMGN robinhood listing gagal: {error}")
        return [], error or "respons kosong"
    rank = (payload.get("data") or {}).get("rank") or []
    rows: list[dict] = []
    seen: set[str] = set()
    for token in rank:
        if not isinstance(token, dict):
            continue
        row = rank_row(token)
        if not row["ca"] or row["ca"] in seen:
            continue
        seen.add(row["ca"])
        rows.append(row)
    return rows, ""


# ---------------------------------------------------------------------------
# Scan: filter listing + dust holder Blockscout
# ---------------------------------------------------------------------------
def sort_rows(rows: list | None) -> list:
    """Urutan listing (permintaan user 2026-09-10): **dust % MC terkecil**
    dulu, lalu **volume 6 jam terbesar**; tie terakhir simbol A-Z supaya
    deterministik. Input tidak diubah."""
    out = [dict(row) for row in (rows or [])]
    out.sort(key=lambda r: (float(r.get("dust_pct_mc") or 0.0),
                            -float(r.get("volume") or 0.0),
                            str(r.get("symbol") or "").upper()))
    return out


# TIDAK ada budget waktu per kandidat (permintaan user 2026-09-10 setelah
# kejadian "macet 6/7"): yang bikin lama bukan scan-nya hang, tapi jumlah
# holder kandidat terakhir yang memang puluhan ribu — paginasi Blockscout 400
# akun/halaman + jeda 0,6 dtk ≈ 10-15 menit untuk satu token. Jadi semua
# kandidat **ditunggu sampai selesai**; progress bar ikut diperbarui saat
# kandidat mulai digiling (label "sedang: SYMBOL") supaya yang lama tetap
# kelihatan hidup.


def scan_candidates(candidates: list, *, max_wallets: int | None = None,
                    workers: int = DEFAULT_WORKERS, progress=None) -> dict:
    """Dust holder Blockscout per kandidat; return ``{ca: analysis}``.

    Harga & marketcap diambil dari baris GMGN (bukan DexScreener) supaya
    dust % MC konsisten dengan sumber listing; ``fetch_market=True`` tetap
    dinyalakan **hanya** untuk metadata pool DexScreener (LP/pool
    disingkirkan dari hitungan dust) — satu panggilan ringan per token.

    ``progress(done, total, label)`` dipanggil saat kandidat **mulai**
    dikerjakan dan saat selesai — label menyebut simbol/CA yang sedang
    digiling supaya "6/7" tidak terlihat seperti hang.
    """
    import threading

    import holder_analysis
    import robinhood_holders
    from concurrent.futures import ThreadPoolExecutor, as_completed

    max_wallets = int(max_wallets or holder_history.FULL_SCAN_MAX_WALLETS)
    analyses: dict = {}
    total = len(candidates or [])
    if not total:
        return analyses
    workers = max(1, min(int(workers), 8))

    active: dict[str, str] = {}   # ca → label yang sedang jalan
    active_lock = threading.Lock()
    done = 0

    def _emit(label: str) -> None:
        if progress:
            try:
                progress(done, total, label)
            except Exception:  # noqa: BLE001
                pass

    def _running_label() -> str:
        with active_lock:
            running = list(active.values())
        if not running:
            return ""
        label = running[0]
        if len(running) > 1:
            label += f" (+{len(running) - 1} lagi)"
        return f"sedang: {label}"

    def _job(row):
        ca = str(row.get("ca") or "")
        label = str(row.get("symbol") or ca[:8] or "?").upper()
        with active_lock:
            active[ca] = label
        _emit(_running_label())
        try:
            analysis = robinhood_holders.analyze_token(
                ca, str(row.get("symbol") or "?"),
                market_cap=float(row.get("mc") or 0),
                price_usd=float(row.get("price") or 0),
                dust_limit=holder_analysis.DUST_LIMIT_USD,
                max_wallets=max_wallets,
                fetch_market=True,
                detail=False)
            return ca, analysis, None
        except Exception as exc:  # noqa: BLE001
            return ca, None, str(exc)
        finally:
            with active_lock:
                active.pop(ca, None)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, row) for row in (candidates or [])]
        # as_completed TANPA timeout: kandidat terakhir yang holdernya puluhan
        # ribu memang butuh 10-15 menit — hasilnya tetap dipakai, tidak
        # dibuang hanya karena lama.
        for future in as_completed(futures):
            ca, analysis, error = future.result()
            if analysis is not None:
                analyses[ca] = analysis
            elif error:
                print(f"WARN rh-best {ca[:8]}: {error}",
                      file=__import__("sys").stderr)
                try:
                    import activity_log
                    activity_log.error(
                        "scan-best-rh",
                        f"kandidat {ca[:10]}… gagal: {error[:140]}")
                except Exception:  # noqa: BLE001
                    pass
            done += 1
            _emit(_running_label() or ca[:8])
    return analyses


def scan_best(limit: int = DEFAULT_LIMIT, workers: int = DEFAULT_WORKERS,
              max_wallets: int | None = None, progress=None) -> dict:
    """**Scan Best Robinhood Coin**: listing GMGN volume 6 jam → filter
    top 10 holder < 30% → dust holder Blockscout → filter dust ≤ 0,05% MC
    → urut dust terkecil, lalu volume 6 jam terbesar."""
    from holder_history import holders_usable

    limit = max(1, int(limit))
    try:
        import activity_log as _alog
    except Exception:  # noqa: BLE001 - log hanya pelengkap
        _alog = None
    if _alog:
        _alog.info("scan-best-rh",
                   f"scan mulai: listing GMGN top {limit} (volume "
                   f"{SCAN_INTERVAL})")
    fetched_rows, error = fetch_ranking(interval=SCAN_INTERVAL, limit=limit)
    if _alog and error:
        _alog.error("scan-best-rh",
                    f"listing GMGN gagal: {_short_error(error)}")
    result = {
        "rows": [],
        "error": error,
        "fetched": len(fetched_rows),
        "interval": SCAN_INTERVAL,
        "limit": limit,
        "skipped": {"honeypot": 0, "top10": 0, "no_quote": 0,
                    "failed": 0, "dust": 0},
        "blocked": 0,
        "dexboost": 0,
    }
    candidates: list[dict] = []
    for row in fetched_rows:
        if row["honeypot"]:
            result["skipped"]["honeypot"] += 1
            continue
        if row["top10_pct"] >= RH_SCAN_MAX_TOP10_PCT:
            result["skipped"]["top10"] += 1
            continue
        # Dust % MC butuh harga & marketcap; tanpa keduanya dust tidak
        # bisa dihitung (jangan tampilkan "0,000%" palsu).
        if row["price"] <= 0 or row["mc"] <= 0:
            result["skipped"]["no_quote"] += 1
            continue
        candidates.append(row)

    analyses = scan_candidates(candidates, max_wallets=max_wallets,
                               workers=workers, progress=progress)
    kept: list[dict] = []
    for row in candidates:
        analysis = analyses.get(row["ca"])
        holders = (analysis or {}).get("holders") or {}
        # Guard kelayakan sama dengan cron: sampel terpotong / 0 wallet
        # tidak boleh dibaca seperti "dust bersih 0,000%".
        if not holders_usable(holders):
            result["skipped"]["failed"] += 1
            if holders.get("blocked"):
                result["blocked"] += 1
            continue
        pct = holders.get("dust_pct_mc")
        if pct is None or float(pct) > RH_SCAN_MAX_DUST_PCT:
            result["skipped"]["dust"] += 1
            continue
        item = dict(row)
        item["dust_pct_mc"] = float(pct)
        item["dust_count"] = int(holders.get("dust_count") or 0)
        item["wallets_analyzed"] = int(holders.get("wallets_analyzed") or 0)
        kept.append(item)

    result["rows"] = sort_rows(kept)
    result["dexboost"] = sum(1 for r in result["rows"] if r.get("dexboost"))
    if _alog:
        sk = result["skipped"]
        _alog.info(
            "scan-best-rh",
            f"scan selesai: {len(result['rows'])} coin lolos dari "
            f"{len(fetched_rows)} listing (dust>{RH_SCAN_MAX_DUST_PCT:g}%="
            f"{sk['dust']}, top10={sk['top10']}, honeypot={sk['honeypot']}, "
            f"gagal={sk['failed']})")
        if result.get("blocked"):
            _alog.warn("scan-best-rh",
                       f"{int(result['blocked'])} kandidat tertolak "
                       "Blockscout 403 — lihat entri blockscout di log")
    return result


# ---------------------------------------------------------------------------
# UI — card halaman utama
# ---------------------------------------------------------------------------
def _head_html(rows: list, skipped_total: int, dexboost_count: int) -> str:
    """Kepala card: jumlah coin lolos + rekap dexboost / dilewati."""
    from dashboard_components import card_head_html

    pills = [f'<span class="lp-count">{len(rows)} coin</span>']
    if dexboost_count:
        pills.append('<span class="lp-count" style="color:#3b2f0a;'
                     'background:#fde047;border:1px solid #facc15;">'
                     f'🚀 {dexboost_count} DEXBOOST</span>')
    if skipped_total:
        pills.append('<span class="lp-count" style="color:#334155;'
                     f'background:#e2e8f0;">{skipped_total} dilewati</span>')
    return card_head_html(CARD_TITLE, pills, tooltip=RH_SCAN_TOOLTIP)


def copy_ca_html(ca: str) -> str:
    """Tombol 📋 **copy CA** (JS clipboard + fallback ``execCommand``).

    Streamlit markdown men-trip tag ``<script>``, jadi tombol ini dirender
    lewat ``st.iframe`` (isi HTML disisipkan lewat ``srcdoc`` — script
    berjalan, origin ikut induknya sehingga ``navigator.clipboard`` sah
    pada context https). CA-nya di-escape sebelum masuk string JS dan
    tombol hanya pernah menerima CA ``0x…`` dari listing GMGN.
    """
    js_ca = html.escape(ca or "", quote=True).replace("'", "\\'")
    return (
        '<div style="display:flex;justify-content:center;padding:0.2rem 0;">'
        '<button id="rh-copy" title="Copy CA" style="cursor:pointer;'
        'font-size:1rem;line-height:1;padding:.35rem .5rem;border:1px solid '
        '#cbd5e1;border-radius:.35rem;background:#ffffff;">📋</button></div>'
        "<script>(function () {"
        f"var ca = '{js_ca}';"
        "var btn = document.getElementById('rh-copy');"
        "function done(ok) {"
        "btn.textContent = ok ? '✅' : '✖';"
        "setTimeout(function () { btn.textContent = '📋'; }, 1500);"
        "}"
        "function fallback() {"
        "var ta = document.createElement('textarea');"
        "ta.value = ca; ta.style.position = 'fixed'; ta.style.opacity = '0';"
        "document.body.appendChild(ta); ta.focus(); ta.select();"
        "var ok = false;"
        "try { ok = document.execCommand('copy'); } catch (e) {}"
        "document.body.removeChild(ta); done(ok);"
        "}"
        "if (navigator.clipboard && navigator.clipboard.writeText) {"
        "navigator.clipboard.writeText(ca).then"
        "(function () { done(true); }, fallback);"
        "} else { fallback(); }"
        "})();</script>"
    )


def render_robinhood_best_scan() -> None:
    """Card **Scan Best Robinhood Coin** (halaman utama, 2026-09-10) —
    bentuknya meniru **Scan Meteora Pool** (``temp_ui.render_meteora_scan``):
    tombol scan + progress, hasil disimpan di ``session_state`` (kepala
    card dan listing selalu satu sumber data), lalu baris per coin dengan
    tombol 📋 copy CA dan ⭐ Watchlist Robinhood LP."""
    import streamlit as st

    from dashboard_components import _compact
    from links import external_links_html
    from robinhood_watchlist import add_to_robinhood_watchlist

    with st.container(border=True):
        # Kepala card butuh angka hasil scan terakhir, jadi hasil disimpan /
        # dibaca lebih dulu (pola yang sama dengan card Scan Meteora: selesai
        # scan → ``st.rerun()``).
        col_limit, col_btn = st.columns([0.45, 0.55],
                                        vertical_alignment="bottom")
        limit = col_limit.number_input(
            "Jumlah kandidat", min_value=10, max_value=500,
            value=DEFAULT_LIMIT, step=10, key="rh-best-limit",
            help="Top N token Robinhood Chain berdasarkan volume 6 jam "
                 "terakhir dari GMGN; setiap kandidat dihitung dust "
                 "holdernya (Blockscout).")
        if col_btn.button(CARD_TITLE, type="primary", key="rh-best-scan-now",
                          use_container_width=True):
            bar = st.progress(0.0, text="Listing token GMGN (robinhood)…")

            def _progress(index, total, label):
                bar.progress(index / max(total, 1),
                             text=f"Holder {index}/{total} · {label}")

            try:
                # FULL (100.000): dust ada di ekor daftar holder, sampel
                # pendek selalu pulang 0,000% (lihat docs PARE/Blockscout).
                result = scan_best(limit=int(limit),
                                   max_wallets=holder_history.FULL_SCAN_MAX_WALLETS,
                                   workers=DEFAULT_WORKERS, progress=_progress)
            except Exception as exc:  # noqa: BLE001
                result = {"rows": [], "error": str(exc), "fetched": 0,
                          "skipped": {}, "blocked": 0, "dexboost": 0}
            finally:
                bar.empty()
            st.session_state[SESSION_KEY] = result
            st.rerun()

        result = st.session_state.get(SESSION_KEY) or {}
        error = result.get("error") or ""
        # sort_rows() lagi di sini: hasil lama di session_state (sebelum
        # fitur/urutan berubah) bisa belum terurut — listing konsisten
        # tanpa perlu scan ulang.
        rows = sort_rows(result.get("rows") or [])
        skipped = result.get("skipped") or {}
        skipped_total = sum(int(value or 0) for value in skipped.values())
        dexboost_count = int(result.get("dexboost") or 0)

        st.markdown(_head_html(rows, skipped_total, dexboost_count),
                    unsafe_allow_html=True)
        # Tanpa caption ambang: detail karakteristik card sudah pindah ke
        # tooltip judul (``RH_SCAN_TOOLTIP``) — permintaan user 2026-09-10.
        if error:
            st.warning(f"GMGN API: {_short_error(error) or error[:200]}")
        if int(result.get("blocked") or 0):
            st.warning(
                f"{int(result['blocked'])} holder scan tertolak Blockscout "
                "(HTTP 403 bot-protection) — pasang `BLOCKSCOUT_API_KEY` "
                "(key gratis, lihat card Scan Holder) supaya semua kandidat "
                "bisa dihitung dustnya.")
        if result:
            # Hanya rekap hasil scan (angka), TANPA menulis ulang ambangnya:
            # rule dust / top 10 / honeypot sudah ada di tooltip judul
            # (permintaan user 2026-09-11: "tulisan ini hapus, sudah ada di
            # tooltip").
            st.caption(
                f"Listing {int(result.get('fetched') or 0)} coin · "
                f"{skipped_total} dilewati · dust "
                f"{int(skipped.get('dust') or 0)} · top 10 "
                f"{int(skipped.get('top10') or 0)} · honeypot "
                f"{int(skipped.get('honeypot') or 0)} · holder gagal "
                f"{int(skipped.get('failed') or 0)}.")
        if not rows:
            if result:
                st.info("Tidak ada coin yang lolos filter (atau listing "
                        "kosong).")
            return

        col_spec = [1.55, 0.7, 0.8, 0.7, 0.7, 0.65, 0.9, 0.5, 0.5]
        header_cols = st.columns(col_spec)
        titles = ["Token", "MC", "Vol 6J", "Liq", "Holders", "Top10",
                  "Dust %MC", "", ""]
        style = ("font-size:0.72rem;color:#000000;font-weight:700;"
                 "text-align:center;")
        for col, title in zip(header_cols, titles):
            col.markdown(f'<div style="{style}">{title}</div>',
                         unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)

        for index, row in enumerate(rows):
            ca = str(row.get("ca") or "")
            symbol = str(row.get("symbol") or "?").upper()
            dust_pct = row.get("dust_pct_mc")
            top10 = row.get("top10_pct")
            cols = st.columns(col_spec)
            cols[0].markdown(
                f'<div class="watchlist-token">'
                f'<span class="watchlist-symbol">'
                f'${html.escape(symbol)}</span>'
                f'<span class="watchlist-mint">'
                f'{html.escape(ca[:10])}…</span>'
                f'<div class="watchlist-links">{external_links_html(ca)}'
                f"</div></div>", unsafe_allow_html=True)
            # `.6g`: presisi cukup untuk harga rendah (0.0073) tanpa
            # menumpuk nol di harga tinggi (223.28).
            price_txt = f"${float(row.get('price') or 0):.6g}"
            cols[1].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{_compact(row.get("mc"))}</div>'
                f'<div class="watchlist-metric-sub">{price_txt}'
                "</div></div>", unsafe_allow_html=True)
            cols[2].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{_compact(row.get("volume"))}</div>'
                '<div class="watchlist-metric-sub">6 jam</div></div>',
                unsafe_allow_html=True)
            cols[3].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{_compact(row.get("liq"))}</div>'
                '<div class="watchlist-metric-sub">liq</div></div>',
                unsafe_allow_html=True)
            cols[4].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{int(row.get("holders") or 0):,}</div>'
                '<div class="watchlist-metric-sub">holder</div></div>',
                unsafe_allow_html=True)
            top10_txt = "—" if top10 is None else f"{float(top10):.1f}%"
            cols[5].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f"{html.escape(top10_txt)}</div>"
                '<div class="watchlist-metric-sub">top 10</div></div>',
                unsafe_allow_html=True)
            pct_txt = ("—" if dust_pct is None
                       else f"{float(dust_pct):.3f}%")
            # Badge level (AMAN/HATI-HATI/BAHAYA) sengaja TIDAK dirender:
            # semua baris sudah ≤ 0,05% MC, jadi yang informatif hanya chip
            # 🚀 DEXBOOST (poin tambah bila pernah ada dexboost).
            boost = ('<span class="dust-badge dust-best">🚀 DEXBOOST</span>'
                     if row.get("dexboost") else "")
            cols[6].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f"{pct_txt}</div>{boost}</div>", unsafe_allow_html=True)
            # Tombol 📋 dirender DI kolom (bukan root) via st.iframe:
            # markdown men-trip <script>, iframe (srcdoc) membiarkannya.
            cols[7].iframe(copy_ca_html(ca), height=52)
            # Key diikat ke CA (bukan nomor baris): urutan bisa berubah
            # antar scan sehingga key berbasis index bisa menempel ke token
            # yang salah (pola yang sama dengan ⭐ Scan Meteora).
            # Tanpa st.rerun() (pola ⭐ Scan Meteora): hasil commit GitHub
            # jalan di latar belakang, pesan sukses tampil sampai rerun
            # berikutnya; auto-refresh app ikut menyegarkan card watchlist
            # via ``watchlist_auto_refresh_cas``.
            if cols[8].button("⭐", key=f"rh-best-star-{ca or index}",
                              help="Tambah ke Watchlist Robinhood LP "
                                   "(halaman utama, scan cron ±5 menit)",
                              use_container_width=True):
                if ca:
                    add_to_robinhood_watchlist(
                        ca, symbol, note="Scan Best Robinhood Coin",
                        background=True)
                    st.success(f"${symbol} masuk Watchlist Robinhood")
            st.markdown(
                '<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)
