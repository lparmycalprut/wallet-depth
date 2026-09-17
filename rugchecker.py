# -*- coding: utf-8 -*-
"""RugCheck — cek honeypot + bendera keamanan + likuiditas per DEX.

Sumber data: **rugchecker.cc** (bukan rugcheck.xyz — permintaan user
2026-09-16, koreksi kedua: *"maaf salah, bukan dari rugcheck tapi dari sini"*
sambil menempel curl ``https://www.rugchecker.cc/api/honeypot/checker``).
Endpoint-nya publik (tanpa API key): hanya butuh header browser biasa —
``accept: */*``, ``referer: https://www.rugchecker.cc/`` dan User-Agent;
cookie ``_ga`` yang ikut terkirim di devtools pengguna adalah analytics
Google, bukan kredensial, jadi sengaja TIDAK dikirim.

Payload yang dipakai (semua lapangan lain diabaikan):

=========================  ====================================================
``data.is_honeypot``       bool — honeypot = tidak bisa jual = otomatis RUG.
``data.security``          9 bendera Token-2022/authority: ``mintable``,
                           ``freezable``, ``non_transferable``,
                           ``transfer_fee`` (angka persen), ``closable``,
                           ``balance_mutable``, ``metadata_mutable``,
                           ``transfer_fee_upgradable``,
                           ``transfer_hook_upgradable``.
``data.dex[]``             likuiditas per pool: ``dex_id``, ``quote``,
                           ``liquidity.usd``, ``market_cap``, ``pair_address``
                           — inilah "Liquidity Information" di UI rugchecker.cc
                           ("PUMPSWAP (SOL) — Liquidity: $114,959.09"), diminta
                           user dalam **versi lebih ringkas**.
``data.symbol`` / ``name`` pencocokan tampilan saja.
=========================  ====================================================

Yang dibaca card hanya :func:`summarize` → dict ringkas (verdict + angka +
teks), jadi pemformatan dan klasifikasi tinggal satu tempat. Kolom **RugCheck**
di 🏆 Scan Best Pool Meteora menampilkan verdict + likuiditas ringkas;
penjelasan lengkap (bendera mana yang nyala, apakah pool yang discan ini
cukup dalam) ada di tooltip sel.

**Sejak 2026-09-17 angka likuiditas kolom ini bersumber dari GMGN**
(:mod:`gmgn_liquidity`, permintaan user: *"ubah info liquidititas dari
rugchecker.cc ke gmgn saja"*): total likuiditas token di halaman gmgn.ai
(``row["gmgn_liq"]``), bukan lagi total per-DEX dari ``data.dex[]``.
Rincian per-DEX hanya dipakai internal (metode tambahan: kedalaman + share
pool; share-nya dihitung terhadap total GMGN) dan tidak lagi ditampilkan.
Bila nilai GMGN tak terbaca, kolom jatuh ke total per-DEX rugchecker.cc
(``liquidity_source`` = ``"rugchecker"``) — dan saringan "likuiditas < $1M
tidak ditampilkan" (lihat :mod:`gmgn_liquidity`) tidak pernah menyaring
baris tanpa bukti.

**Metode tambahan** (penjelasan ringkas yang diminta user: *"jika kamu
memiliki metode tambahan untuk check rug, bisa kamu tambahkan kolom juga
untuk penjelasanmu secara ringkas"*) — tiga pemeriksaan sendiri di atas payload
yang sama, tidak butuh request tambahan:

1. **kedalaman pool yang dipakai** — ``liquidity.usd`` pool ini (dicocokkan
   lewat ``pair_address`` listing Meteora) dibagi ambang :data:`POOL_MIN_LIQ_USD`;
   pool < $10K terlalu mudah digerakkan untuk posisi LP;
2. **sebaran likuiditas** — berapa persen likuiditas token yang duduk di pool
   ini (:data:`POOL_SHARE_MIN_PCT`); sisanya di DEX lain = harga pool ini bisa
   menyimpang dan fee pool ikut terkuras;
3. **konsentrasi pasar** — berapa pool yang total likuiditasnya ≥ 10% dari
   semuanya; satu pool dominan + banyak pool debu = pola launch yang gampang
   ditarik keluar.

Cache berkas (``rugchecker_cache.json``, TTL :data:`CACHE_TTL_OK`) menahan hasil
sukses :data:`CACHE_TTL_FAIL` detik untuk kegagalan, supaya rerun Streamlit
(setiap interaksi) tidak menembak endpoint pihak ketiga untuk mint yang sama.
Format cache: ``{mint: {"at": <epoch>, "ok": <bool>, "data": <payload>}}``.
"""
from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CHECK_URL = "https://www.rugchecker.cc/api/honeypot/checker"

#: Lokasi cache berkas (di repo supaya ikut persist antar-restart container).
CACHE_PATH = Path(__file__).resolve().parent / "rugchecker_cache.json"
CACHE_TTL_OK = 1800          # hasil sukses: 30 menit
CACHE_TTL_FAIL = 300         # kegagalan: 5 menit (jangan menghukum selamanya)
CACHE_MAX_ENTRIES = 400      # pruning LRU sederhana

REQUEST_TIMEOUT = 12
WORKERS = 6

#: Berapa pool yang ditulis di baris likuiditas ringkas (kolomnya sempit).
MAX_LIQ_LINES = 3

#: Metode tambahan: ambang kedalaman pool + share minimum + ambang "pool besar".
POOL_MIN_LIQ_USD = 10_000.0
POOL_SHARE_MIN_PCT = 25.0
BIG_POOL_SHARE_PCT = 10.0

_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "referer": "https://www.rugchecker.cc/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/152.0.0.0 Safari/537.36"),
}

#: Bendera keamanan yang membuat token **bisa** dirug oleh penerbitnya.
CRITICAL_FLAGS = (
    ("mintable", "mintable", "penerbit masih bisa mencetak supply"),
    ("freezable", "freezable", "wallet bisa dibekukan → saldo tidak bisa dijual"),
    ("non_transferable", "non-transferable", "token tidak bisa ditransfer"),
    ("transfer_hook_upgradable", "transfer hook",
     "hook transfer bisa dipasang belakangan (jalur sensor jual)"),
)

#: Bendera yang mengganggu tapi bukan blocker jual — klasifikasi "waspada".
MINOR_FLAGS = (
    ("transfer_fee_upgradable", "fee upgradable",
     "pajak transfer bisa dinaikkan belakangan"),
    ("balance_mutable", "balance mutable",
     "saldo bisa diubah dari luar (token-2022 extension)"),
    ("metadata_mutable", "metadata mutable", "nama/simbol bisa diganti"),
    ("closable", "closable", "akun token bisa ditutup"),
)

#: Satu-satunya label yang membuat verdict langsung RUG, apa pun yang lain.
HONEYPOT_LABEL = "honeypot"

VERDICT_RUG = ("RUG", "#dc2626")
VERDICT_RISK = ("BERISIKO", "#b91c1c")
VERDICT_WATCH = ("WASPADA", "#b45309")
VERDICT_CLEAN = ("AMAN", "#15803d")
VERDICT_UNKNOWN = ("—", "")


def _float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def compact_usd(value) -> str:
    """``$1.25 jt`` gaya repo — angka USD bulat, ringkas, aman ``None``.

    Tidak memakai ``dashboard_components._compact`` (modul ini harus bisa
    dipakai skrip cron/tes tanpa Streamlit), jadi formatannya disalin:
    ``K``/``M``/``B`` di bawah 1000 digit, dua angka penting di belakang koma
    hanya di bilangan kecil.
    """
    if value is None:
        return "—"
    number = _float(value)
    sign = "-" if number < 0 else ""
    number = abs(number)
    for limit, suffix in ((1_000_000_000.0, "B"), (1_000_000.0, "M"),
                          (1_000.0, "K")):
        if number >= limit:
            scaled = number / limit
            # K boleh lebih rinci (likuiditas $6.45K vs $6K beda arti);
            # M/B cukup dua angka penting di depan koma.
            digits = 2 if scaled < 10 else 1
            if suffix != "K":
                digits = 2 if scaled < 10 else (1 if scaled < 100 else 0)
            return f"{sign}${scaled:.{digits}f}{suffix}"
    if number >= 100:
        return f"{sign}${number:,.0f}"
    return f"{sign}${number:,.2f}"


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
            # Prune LRU: buang entri tertua lewat "at".
            ordered = sorted(cache.items(),
                             key=lambda kv: _float((kv[1] or {}).get("at")))
            cache = dict(ordered[-CACHE_MAX_ENTRIES:])
        path = Path(CACHE_PATH)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _cache_get(mint: str) -> tuple[bool, dict | None]:
    """``(fresh, payload)`` — fresh False berarti perlu fetch ulang."""
    entry = _cache_load().get(mint)
    if not isinstance(entry, dict):
        return False, None
    age = time.time() - _float(entry.get("at"))
    ttl = CACHE_TTL_OK if entry.get("ok") else CACHE_TTL_FAIL
    if age > ttl:
        return False, None
    data = entry.get("data")
    return True, data if isinstance(data, dict) else None


def _cache_put(mint: str, payload, *, ok: bool) -> None:
    cache = _cache_load()
    cache[mint] = {"at": int(time.time()), "ok": bool(ok),
                   "data": payload if isinstance(payload, dict) else
                   {"error": str(payload or "respons kosong")[:200]}}
    _cache_save(cache)


def _extract_data(payload: dict) -> dict | None:
    """Ambil ``data`` dari ``{code, message, data, …}``; ``None`` bila gagal."""
    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    if code not in (0, "0", None):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def fetch_raw(mint: str, *, timeout: int = REQUEST_TIMEOUT) -> dict:
    """SATU request honeypot-checker. Mengembalikan payload mentah.

    Melempar ``RuntimeError`` untuk kegagalan HTTP/parse — pemanggil
    (:func:`check_tokens`) yang mengubahnya menjadi ``{"error": …}``, supaya
    satu mint mati tidak menjatuhkan seluruh scan.
    """
    import requests

    url = f"{CHECK_URL}?address={str(mint).strip()}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    except Exception as exc:  # requests melempar banyak tipe
        raise RuntimeError(f"rugchecker: {str(exc)[:160]}") from exc
    status = getattr(resp, "status_code", 0)
    if status != 200:
        raise RuntimeError(f"rugchecker HTTP {status}")
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - HTML error page dll.
        raise RuntimeError("rugchecker: respons bukan JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("rugchecker: respons bukan objek JSON")
    return payload


def _markets(data: dict) -> list[dict]:
    """Normalisasi ``data.dex[]`` → list ``{dex, quote, usd, mcap, pair}``.

    Hanya entri ber-``liquidity.usd`` numerik yang dipakai; urut terbesar
    (itu urutan yang dibaca user di UI rugchecker.cc: PUMPSWAP, METEORA,
    RAYDIUM). ``market_cap`` ikut disimpan karena muncul di blok yang sama.
    """
    out: list[dict] = []
    for item in data.get("dex") or []:
        if not isinstance(item, dict):
            continue
        liq = item.get("liquidity") if isinstance(item.get("liquidity"),
                                                 dict) else {}
        usd = _float(liq.get("usd"), float("nan"))
        if not math.isfinite(usd) or usd < 0:
            continue
        out.append({
            "dex": str(item.get("dex_id") or "?").strip().lower(),
            "quote": str(item.get("quote") or "").strip().upper(),
            "usd": usd,
            "mcap": _float(item.get("market_cap")),
            "pair": str(item.get("pair_address") or "").strip(),
        })
    out.sort(key=lambda row: -row["usd"])
    return out


def liquidity_lines(markets: list[dict], *, limit: int | None = None
                    ) -> tuple[list[str], float]:
    """``(baris ringkas, total likuiditas USD)`` — versi pendek blok
    "Liquidity Information" rugchecker.cc.

    Satu baris = ``PUMPSWAP·SOL $116.7K`` (DEX + pasangan + likuiditas),
    maksimum ``limit`` baris; sisanya diringkas jadi ``+4 pool lain``.
    """
    # ``limit=None`` → dibaca dari konstanta saat panggil (bukan default yang
    # dibekukan saat definisi), supaya tes/uber ambang bisa mem-patch
    # :data:`MAX_LIQ_LINES` dan lihat hasilnya ikut berubah.
    if limit is None:
        limit = MAX_LIQ_LINES
    rows = list(markets or [])
    total = sum(row.get("usd") or 0.0 for row in rows)
    lines: list[str] = []
    for row in rows[:max(0, int(limit))]:
        label = str(row.get("dex") or "?").upper()
        quote = str(row.get("quote") or "").upper()
        if quote:
            label = f"{label}·{quote}"
        lines.append(f"{label} {compact_usd(row.get('usd'))}")
    extra = len(rows) - len(lines)
    if extra > 0:
        lines.append(f"+{extra} pool")
    return lines, total


def _notes(data: dict, markets: list[dict], *, pool: str,
           total_liq: float, flags: list[str]) -> list[str]:
    """Penjelasan ringkas metode tambahan (lihat docstring modul)."""
    notes: list[str] = []
    this = None
    if pool:
        for row in markets:
            if row.get("pair") and row["pair"] == pool:
                this = row
                break
    if this is None:
        notes.append("pool ini tidak ada di daftar rugchecker → "
                     "likuiditasnya tidak terkonfirmasi di sumber ini")
    else:
        share = (this["usd"] / total_liq * 100.0) if total_liq > 0 else 0.0
        depth = ("cukup" if this["usd"] >= POOL_MIN_LIQ_USD
                 else "TIPIS — harga mudah digeser")
        notes.append(
            f"kedalaman pool ini {compact_usd(this['usd'])} ({depth})"
            f" · share {share:.1f}% dari likuiditas token")
        if share < POOL_SHARE_MIN_PCT:
            notes.append(
                f"share pool < {POOL_SHARE_MIN_PCT:g}% → likuiditas tersebar "
                "di DEX lain, harga pool ini bisa menyimpang dan fee ikut "
                "terkuras")
    if markets:
        big = [row for row in markets if total_liq > 0
               and row["usd"] / total_liq * 100.0 >= BIG_POOL_SHARE_PCT]
        top_share = (markets[0]["usd"] / total_liq * 100.0) if total_liq > 0 \
            else 0.0
        # "sisanya debu" hanya boleh ditulis kalau memang ada sisanya: dengan
        # dua pool sama besar, menyebut salah satunya "debu" itu bohong — dan
        # kolom ini dibaca orang sebelum menaruh likuiditas.
        if len(big) >= len(markets):
            tail = " · tersebar merata"
        elif big:
            tail = " — sisanya debu, mudah ditarik keluar"
        else:
            tail = " — tidak ada pool dengan likuiditas berarti"
        notes.append(
            f"{len(markets)} pool · {len(big)} pool ≥ "
            f"{BIG_POOL_SHARE_PCT:g}% likuiditas · pool terbesar "
            f"{top_share:.0f}%" + tail)
    if flags:
        notes.append("bendera keamanan: " + ", ".join(flags))
    else:
        notes.append("bendera keamanan: tidak ada (mint/freeze/hook mati)")
    return notes


def summarize(payload, *, pool_address: str = "",
              gmgn_total_usd=None) -> dict:
    """Ringkasan satu laporan untuk kolom **RugCheck** (selalu dict).

    ``pool_address`` (alamat pool Meteora yang discan) dipakai metode
    tambahan untuk menilai kedalaman pool itu sendiri. Kegagalan API =
    ``{"ok": False, "error": …}`` → kolom menulis ``—`` (tidak pernah
    mengarang verdict untuk data yang tidak ada).

    ``gmgn_total_usd`` (sejak 2026-09-17, permintaan user *"ubah info
    liquidititas dari rugchecker.cc ke gmgn saja"*): bila ada (angka > 0),
    **angka likuiditas yang ditampilkan** = likuiditas total GMGN — baris
    per-DEX rugchecker.cc tidak lagi ditampilkan (``liquidity_lines`` kosong,
    ``liquidity_source`` ``"gmgn"``) dan share pool di catatan dihitung
    terhadap total GMGN; verdict + bendera tetap milik rugchecker.cc. Tanpa
    nilai GMGN → perilaku lama (total per-DEX, ``liquidity_source``
    ``"rugchecker"``).
    """
    data = _extract_data(payload if isinstance(payload, dict) else {})
    if data is None:
        error = ""
        if isinstance(payload, dict):
            error = str(payload.get("error") or payload.get("message") or "")
        return {"ok": False, "error": (error or "laporan tidak tersedia")[:200],
                "verdict": VERDICT_UNKNOWN[0], "color": VERDICT_UNKNOWN[1]}

    security = data.get("security") if isinstance(data.get("security"), dict) \
        else {}
    honeypot = bool(data.get("is_honeypot"))
    flags: list[str] = []
    critical: list[str] = []
    for key, label, _why in CRITICAL_FLAGS:
        if bool(security.get(key)):
            critical.append(label)
    for key, label, _why in MINOR_FLAGS:
        if bool(security.get(key)):
            flags.append(label)
    # transfer_fee adalah ANGKA persen (bukan bool) — > 0 = pajak transfer.
    fee = _float(security.get("transfer_fee"))
    if fee > 0:
        critical.append(f"transfer fee {fee:g}%")

    markets = _markets(data)
    lines, rc_total = liquidity_lines(markets)
    # Angka likuiditas yang ditampilkan (2026-09-17): total GMGN bila ada —
    # rincian per-DEX rugchecker.cc tidak lagi tampil; share pool di catatan
    # ikut dihitung terhadap total GMGN. (Nama variabel jangan sama dengan
    # fungsi :func:`liquidity_lines` — akan jadi UnboundLocalError.)
    gmgn_usd = _float(gmgn_total_usd) if gmgn_total_usd is not None else 0.0
    if gmgn_usd > 0:
        total_liq, liq_lines, liquidity_source = gmgn_usd, [], "gmgn"
    else:
        total_liq, liq_lines, liquidity_source = rc_total, lines, "rugchecker"
    if honeypot:
        label, color = VERDICT_RUG
    elif critical:
        label, color = VERDICT_RISK
    elif flags:
        label, color = VERDICT_WATCH
    else:
        label, color = VERDICT_CLEAN
    notes = _notes(data, markets, pool=pool_address, total_liq=total_liq,
                   flags=critical + flags
                   + ([HONEYPOT_LABEL] if honeypot else []))
    return {
        "ok": True,
        "verdict": label,
        "color": color,
        "honeypot": honeypot,
        "critical": critical,
        "minor": flags,
        "flag_count": len(critical) + len(flags),
        "markets": markets,
        "market_count": len(markets),
        "liquidity_lines": liq_lines,
        "liquidity_total_usd": total_liq,
        # Sumber angka likuiditas yang ditampilkan: "gmgn" (likuiditas total
        # GMGN, 2026-09-17) atau "rugchecker" (total per-DEX — fallback bila
        # nilai GMGN tidak terbaca).
        "liquidity_source": liquidity_source,
        "market_cap": _float(markets[0]["mcap"]) if markets else 0.0,
        "notes": notes,
        "symbol": str(data.get("symbol") or "").upper(),
        "checked_at": int(time.time()),
    }


def check_tokens(mints, *, pool_by_mint: dict | None = None,
                 gmgn_by_mint: dict | None = None,
                 workers: int = WORKERS, timeout: int = REQUEST_TIMEOUT,
                 use_cache: bool = True) -> dict[str, dict]:
    """``{mint: summary}`` — paralel, cache berkas, kegagalan jadi ``—``.

    Satu mint gagal tidak pernah menjatuhkan scan: ``summarize`` untuk mint itu
    mengembalikan ``{"ok": False, "error": …}`` dan kolomnya menulis ``—``.

    ``gmgn_by_mint`` (``{mint: likuiditas_total_usd}``, 2026-09-17) diteruskan
    ke :func:`summarize` supaya angka likuiditas yang ditampilkan memakai
    total GMGN; mint yang tidak ada di dict tetap memakai total rugchecker.cc.
    """
    pool_by_mint = pool_by_mint or {}
    gmgn_by_mint = gmgn_by_mint or {}
    wanted = [str(mint).strip() for mint in (mints or []) if str(mint).strip()]
    ordered = list(dict.fromkeys(wanted))
    out: dict[str, dict] = {}
    todo: list[str] = []
    for mint in ordered:
        fresh, cached = (_cache_get(mint) if use_cache else (False, None))
        if fresh:
            out[mint] = summarize(cached, pool_address=pool_by_mint.get(mint, ""),
                                  gmgn_total_usd=gmgn_by_mint.get(mint))
        else:
            todo.append(mint)
    if not todo:
        return out

    lock = threading.Lock()
    payloads: dict[str, dict] = {}

    def _job(mint: str):
        try:
            return mint, fetch_raw(mint, timeout=timeout), True
        except Exception as exc:  # noqa: BLE001 - satu mint mati ≠ scan mati
            return mint, {"error": str(exc)[:200]}, False

    workers = max(1, min(int(workers), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, mint) for mint in todo]
        for future in as_completed(futures):
            mint, payload, ok = future.result()
            with lock:
                payloads[mint] = payload
            if use_cache:
                _cache_put(mint, payload, ok=ok)
    for mint in ordered:
        if mint in out:
            continue
        out[mint] = summarize(payloads.get(mint) or {"error": "tanpa respons"},
                              pool_address=pool_by_mint.get(mint, ""),
                              gmgn_total_usd=gmgn_by_mint.get(mint))
    return out


def attach_to_rows(rows, *, workers: int = WORKERS,
                   timeout: int = REQUEST_TIMEOUT, use_cache: bool = True
                   ) -> list[dict]:
    """Tempel ``row["rugcheck"]`` ke baris listing Best Pool (baris baru).

    Hanya baris **lolos saringan** yang diperiksa (baris gugur tidak sampai ke
    layar, jadi tidak perlu menembak API pihak ketiga untuk mereka). Baris
    tanpa ``ca`` (mint) tetap dikembalikan dengan ``rugcheck`` = ``—``.

    Angka likuiditas kolom ini (sejak 2026-09-17) dibaca dari
    ``row["gmgn_liq"]`` — ditempel :mod:`gmgn_liquidity` oleh
    :func:`meteora_screener.scan_best_lane` **sebelum** step ini; bila baris
    tidak punya angka GMGN (``gmgn=False`` di test/offline, atau GMGN tak
    menjawab), kolom jatuh ke total per-DEX rugchecker.cc seperti dulu.
    """
    rows = [dict(row or {}) for row in (rows or [])]
    if not rows:
        return rows
    pool_by_mint: dict[str, str] = {}
    gmgn_by_mint: dict[str, float] = {}
    for row in rows:
        mint = str(row.get("ca") or "").strip()
        pool = str(row.get("pool_address") or "").strip()
        if mint and pool and mint not in pool_by_mint:
            pool_by_mint[mint] = pool
        gm = row.get("gmgn_liq") or {}
        if mint and gm.get("ok"):
            usd = _float(gm.get("usd"))
            if usd > 0 and mint not in gmgn_by_mint:
                gmgn_by_mint[mint] = usd
    reports = check_tokens([str(row.get("ca") or "").strip() for row in rows],
                           pool_by_mint=pool_by_mint, gmgn_by_mint=gmgn_by_mint,
                           workers=workers, timeout=timeout, use_cache=use_cache)
    for row in rows:
        row["rugcheck"] = reports.get(str(row.get("ca") or "").strip()) or {
            "ok": False, "error": "mint tidak terbawa", "verdict": "—",
            "color": ""}
    return rows


def cell_parts(summary) -> tuple[str, str, str]:
    """``(angka, baris kecil, tooltip)`` kolom RugCheck — dibaca UI.

    Dipisah dari UI supaya tes bisa memformat sel tanpa Streamlit dan supaya
    card tidak pernah menebak-nebak struktur :func:`summarize`. Tanpa laporan
    → ``—`` + alasan di tooltip: kolom **tidak** pernah menulis "AMAN" untuk
    mint yang gagal diperiksa.
    """
    item = summary if isinstance(summary, dict) else None
    if not item or not item.get("ok"):
        error = str((item or {}).get("error") or "belum di-fetch")
        return ("—", "rugcheck",
                f"rugchecker.cc tidak menghasilkan laporan: {error} — kolom "
                "menulis —, bukan \"AMAN\" (tanpa bukti tidak ada verdict)")

    lines = list(item.get("liquidity_lines") or [])
    total = compact_usd(item.get("liquidity_total_usd"))
    source = str(item.get("liquidity_source") or "rugchecker")
    # Baris kecil: angka likuiditas total — sumber GMGN (2026-09-17) tidak
    # punya rincian per-DEX, jadi tanpa penghitung pool; sumber rugchecker
    # (fallback) tetap menulis "N pool" seperti dulu.
    if lines:
        sub = f"{total} liq · {int(item.get('market_count') or 0)} pool"
    elif source == "gmgn":
        sub = f"{total} liq"
    else:
        sub = "tanpa pool"
    head = (f"verdict {item.get('verdict')} — rugchecker.cc honeypot checker "
            f"(pemeriksaan {time.strftime('%H:%M', time.gmtime(item.get('checked_at') or 0))} UTC)")
    bits: list[str] = []
    if item.get("honeypot"):
        bits.append("HONEYPOT: token tidak bisa dijual kembali")
    if item.get("critical"):
        bits.append("bendera kritis: " + ", ".join(item["critical"]))
    if item.get("minor"):
        bits.append("catatan: " + ", ".join(item["minor"]))
    if lines:
        bits.append("likuiditas (ringkas): " + " · ".join(lines)
                    + f" — total {total}"
                    + (f" · MC {compact_usd(item.get('market_cap'))}"
                       if item.get("market_cap") else ""))
    elif source == "gmgn":
        # Sumber angka likuiditas sudah GMGN (2026-09-17: permintaan user
        # "ubah info liquidititas dari rugchecker.cc ke gmgn saja") — rincian
        # per-DEX rugchecker.cc tidak lagi ditampilkan di tooltip.
        bits.append(f"likuiditas total (sumber: gmgn.ai): {total}"
                    + (f" · MC {compact_usd(item.get('market_cap'))}"
                       if item.get("market_cap") else ""))
    bits.extend(str(note) for note in (item.get("notes") or []))
    return str(item.get("verdict") or "—"), sub, head + ". " + " · ".join(bits)
