#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cek cepat: apakah sebuah token bagus untuk entri LP di Meteora DLMM?

Tempel contract address (CA), tool mengambil data pool Meteora per window
(1H, 4H, 12H, 24H) lalu memberi verdict. Hanya heuristik, bukan saran
investasi dan bukan hasil backtest — ambang ada di blok KONSTANTA di bawah.

Pemakaian:
    python3 tools/lp_entry_check/lp_entry_check.py <CONTRACT_ADDRESS>
    python3 tools/lp_entry_check/lp_entry_check.py          # tempel CA saat diminta
    python3 tools/lp_entry_check/lp_entry_check.py <CA> --json

Hanya memakai pustaka standar Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

POOLS_URL = "https://pool-discovery-api.datapi.meteora.ag/pools"
WINDOWS = ("1h", "4h", "12h", "24h")
WINDOW_HOURS = {"1h": 1.0, "4h": 4.0, "12h": 12.0, "24h": 24.0}
POOL_WINDOW_MS = 24 * 3600 * 1000
HTTP_TIMEOUT = 25

# ---------------------------------------------------------------------------
# KONSTANTA — ambang heuristik. Bukan hasil backtest; kalibrasi dulu sebelum
# dianggap andal.
# ---------------------------------------------------------------------------
PUMP_DUMP_1H_MIN = 30.0                    # |Δ harga 1H| ≥ ini → HINDARI
CALM_MAX_ABS = {"1h": 10.0, "4h": 20.0, "12h": 30.0}  # |Δ harga| ≤ batas → tenang
FEE_TVL_MIN_24H = 5.0                      # sama dengan BEST_FEE_TVL_MIN di app (%)
FEE_STABLE_RATIO = (0.5, 2.0)              # laju fee 1H ÷ laju fee 4H
ACTIVE_TVL_SHARE_MIN = 0.50                # active_tvl ÷ tvl
VOLUME_SPIKE_1H = 200.0                    # info saja (%)

VERDICT_GOOD = "BAGUS UNTUK ENTRI"
VERDICT_WAIT = "TUNGGU"
VERDICT_BAD_FEE = "TIDAK COCOK"
VERDICT_AVOID = "HINDARI"
VERDICT_DATA = "BELUM CUKUP DATA"
VERDICT_NO_POOL = "TIDAK ADA POOL"

# Base58 (tanpa 0, O, I, l), 32–44 karakter — format alamat Solana.
_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


# ---------------------------------------------------------------------------
# Input & pengambilan data
# ---------------------------------------------------------------------------
def valid_ca(text: str) -> str:
    """Rapikan spasi lalu pastikan bentuknya alamat Solana. Raise ValueError bila tidak."""
    ca = (text or "").strip()
    if not _CA_RE.match(ca):
        raise ValueError(f"Bukan contract address Solana yang valid: {ca!r}")
    return ca


def fetch_window(ca: str, timeframe: str, *, timeout: int = HTTP_TIMEOUT) -> list:
    """Semua pool yang memuat ``ca`` pada ``timeframe`` (list dict mentah dari API)."""
    params = {"page_size": 50, "timeframe": timeframe,
              "category": "top", "query": ca}
    url = POOLS_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (lp-entry-check)",
                      "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    rows = payload.get("data") if isinstance(payload, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def _num(value):
    """Float terbatas (finite) atau ``None``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def pools_for_mint(rows: list, ca: str) -> list:
    """Pool yang token_x atau token_y-nya adalah ``ca``."""
    out = []
    for pool in rows or []:
        sides = (pool.get("token_x") or {}, pool.get("token_y") or {})
        if any(str(side.get("address") or "") == ca for side in sides):
            out.append(pool)
    return out


def _metrics(pool: dict | None) -> dict | None:
    """Field yang dipakai dari satu pool pada satu window."""
    if not pool:
        return None
    return {
        "change": _num(pool.get("pool_price_change_pct")),
        "fee": _num(pool.get("fee_active_tvl_ratio")),
        "vol_change": _num(pool.get("volume_change_pct")),
        "tvl": _num(pool.get("tvl")),
        "active_tvl": _num(pool.get("active_tvl")),
        "created": _num(pool.get("pool_created_at")),
    }


def _usable_change(metrics: dict | None, created, now_ms: float):
    """Perubahan harga yang boleh dipakai. Sama dengan aturan app.

    0% pada pool yang belum genap 24 jam (atau tanpa tanggal dibuat) dianggap
    belum terukur, bukan "tidak berubah".
    """
    if metrics is None or metrics["change"] is None:
        return None
    change = metrics["change"]
    if change == 0:
        if created is None or now_ms - created < POOL_WINDOW_MS:
            return None
    return change


# ---------------------------------------------------------------------------
# Analisis (murni, tanpa jaringan)
# ---------------------------------------------------------------------------
def _pct(value, *, sign: bool = True) -> str:
    if value is None:
        return "—"
    text = f"{value:+.2f}%" if sign else f"{value:.2f}%"
    return text.replace(".", ",")


def analyze(ca: str, rows_by_window: dict, *, now_ms: float,
            errors: dict | None = None) -> dict:
    """Bangun laporan dari data per window. ``rows_by_window[w]`` = list pool mentah.

    ``errors[w]`` = pesan gagal fetch window ``w`` (window itu jadi "tidak terukur").
    """
    errors = errors or {}
    warnings: list[str] = []
    for window, message in errors.items():
        warnings.append(f"Data {window.upper()} gagal diambil: {message}")

    # Kandidat pool: dari 1H dulu, lalu window lain bila 1H tidak punya pool itu.
    candidates: dict[str, dict] = {}
    for window in ("1h",) + tuple(w for w in WINDOWS if w != "1h"):
        for pool in pools_for_mint(rows_by_window.get(window) or [], ca):
            address = str(pool.get("pool_address") or "")
            if address and address not in candidates:
                candidates[address] = pool

    if not candidates:
        return _empty_report(ca, VERDICT_NO_POOL,
                             "Tidak ada pool Meteora untuk CA ini.", warnings)

    main_addr = max(candidates,
                    key=lambda a: _num(candidates[a].get("tvl")) or 0.0)
    main_pool = candidates[main_addr]
    if len(candidates) > 1:
        warnings.append(f"Ada {len(candidates)} pool untuk token ini; "
                        "yang dinilai pool dengan TVL terbesar.")

    token_x = main_pool.get("token_x") or {}
    symbol = str(token_x.get("symbol") or "?") if str(token_x.get("address") or "") == ca \
        else str((main_pool.get("token_y") or {}).get("symbol") or "?")

    # Metrik per window untuk pool utama.
    per_window = {}
    for window in WINDOWS:
        match = next((p for p in rows_by_window.get(window) or []
                      if str(p.get("pool_address") or "") == main_addr), None)
        per_window[window] = _metrics(match)

    created = per_window["1h"]["created"] if per_window["1h"] else None
    if created is None:
        created = next((m["created"] for m in per_window.values() if m and m["created"]), None)
    age_hours = (now_ms - created) / 3_600_000.0 if created else None

    changes = {w: _usable_change(per_window[w], created, now_ms) for w in WINDOWS}
    fees = {w: (per_window[w] or {}).get("fee") for w in WINDOWS}
    h1 = per_window["1h"] or {}
    tvl = h1.get("tvl")
    active = h1.get("active_tvl")

    checks: list[dict] = []
    flags = {"extreme": False, "fee_fail": False}

    # 1) Gerak ekstrem 1 jam terakhir.
    c1 = changes["1h"]
    if c1 is None:
        checks.append(_check("Gerak ekstrem 1H", "unknown", "perubahan 1H tidak terukur"))
    elif abs(c1) >= PUMP_DUMP_1H_MIN:
        flags["extreme"] = True
        checks.append(_check("Gerak ekstrem 1H", "fail",
                             f"{_pct(c1)} (batas ±{PUMP_DUMP_1H_MIN:g}%)"))
    else:
        checks.append(_check("Gerak ekstrem 1H", "ok", f"{_pct(c1)}"))

    # 2) Harga tenang per window.
    for window in ("1h", "4h", "12h"):
        label = f"Harga tenang {window.upper()}"
        value = changes[window]
        limit = CALM_MAX_ABS[window]
        if value is None:
            checks.append(_check(label, "unknown", "tidak terukur"))
        elif abs(value) <= limit:
            checks.append(_check(label, "ok", f"{_pct(value)} (batas ±{limit:g}%)"))
        else:
            checks.append(_check(label, "fail", f"{_pct(value)} (batas ±{limit:g}%)"))

    # 3) Fee/TVL 24H (sejak dibuat bila pool < 24 jam).
    fee24 = fees["24h"]
    fee_label = "Fee/TVL 24H"
    if age_hours is not None and age_hours < 24:
        fee_label = f"Fee/TVL sejak dibuat (umur {age_hours:.1f} jam)"
    if fee24 is None:
        checks.append(_check("Fee/TVL", "unknown", "tidak terukur"))
    elif fee24 >= FEE_TVL_MIN_24H:
        checks.append(_check(fee_label, "ok", f"{_pct(fee24, sign=False)} (min {FEE_TVL_MIN_24H:g}%)"))
    else:
        flags["fee_fail"] = True
        checks.append(_check(fee_label, "fail",
                             f"{_pct(fee24, sign=False)} (min {FEE_TVL_MIN_24H:g}%)"))

    # 4) Fee stabil: laju fee 1H dibanding laju fee 4H (per jam).
    f1, f4 = fees["1h"], fees["4h"]
    if f1 is None or f4 is None:
        checks.append(_check("Fee stabil (1H vs 4H)", "unknown", "tidak terukur"))
    else:
        rate1 = f1 / WINDOW_HOURS["1h"]
        rate4 = f4 / WINDOW_HOURS["4h"]
        if rate4 <= 0:
            checks.append(_check("Fee stabil (1H vs 4H)", "fail",
                                 "fee 4 jam terakhir nol"))
        else:
            ratio = rate1 / rate4
            low, high = FEE_STABLE_RATIO
            detail = f"laju 1H ÷ laju 4H = {ratio:.2f}".replace(".", ",")
            status = "ok" if low <= ratio <= high else "fail"
            rng = f"{low:g}–{high:g}".replace(".", ",")
            checks.append(_check("Fee stabil (1H vs 4H)", status,
                                 f"{detail} (rentang {rng})"))

    # 5) Likuiditas aktif (sebagian besar TVL ada di bin aktif).
    if tvl is None or active is None or tvl <= 0:
        checks.append(_check("Likuiditas aktif", "unknown", "tidak terukur"))
    else:
        share = active / tvl
        status = "ok" if share >= ACTIVE_TVL_SHARE_MIN else "fail"
        checks.append(_check("Likuiditas aktif", status,
                             f"{share * 100:.0f}% TVL di bin aktif (min {ACTIVE_TVL_SHARE_MIN * 100:.0f}%)"))

    # Info saja: lonjakan volume 1H.
    v1 = h1.get("vol_change")
    if v1 is not None and v1 >= VOLUME_SPIKE_1H:
        warnings.append(f"Volume 1H melonjak {_pct(v1)} — waspada, bisa jadi awal pergerakan besar.")

    # Verdict: prioritas HINDARI > TIDAK COCOK > TUNGGU > BELUM CUKUP DATA > BAGUS.
    fails = [c for c in checks if c["status"] == "fail"]
    unknowns = [c for c in checks if c["status"] == "unknown"]
    if flags["extreme"]:
        verdict = VERDICT_AVOID
        reason = "Harga bergerak ekstrem dalam 1 jam terakhir (pump atau dump)."
    elif flags["fee_fail"]:
        verdict = VERDICT_BAD_FEE
        reason = "Fee/TVL di bawah ambang — posisi LP tidak menghasilkan cukup fee."
    elif fails:
        verdict = VERDICT_WAIT
        reason = "Belum tenang atau belum stabil: " + "; ".join(c["name"] for c in fails) + "."
    elif unknowns:
        verdict = VERDICT_DATA
        reason = "Sebagian data belum terukur: " + "; ".join(c["name"] for c in unknowns) + "."
    else:
        verdict = VERDICT_GOOD
        reason = "Semua cek lolos: harga tenang, fee/TVL cukup dan stabil, likuiditas aktif."

    return {
        "ca": ca,
        "symbol": symbol,
        "pool_address": main_addr,
        "pool_name": str(main_pool.get("name") or ""),
        "tvl": tvl,
        "active_tvl": active,
        "pool_age_hours": age_hours,
        "changes": changes,
        "fees": fees,
        "checks": checks,
        "verdict": verdict,
        "reason": reason,
        "warnings": warnings,
    }


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def _empty_report(ca: str, verdict: str, reason: str, warnings: list) -> dict:
    return {"ca": ca, "symbol": "", "pool_address": "", "pool_name": "",
            "tvl": None, "active_tvl": None, "pool_age_hours": None,
            "changes": {w: None for w in WINDOWS},
            "fees": {w: None for w in WINDOWS},
            "checks": [], "verdict": verdict, "reason": reason,
            "warnings": warnings}


# ---------------------------------------------------------------------------
# Keluaran teks
# ---------------------------------------------------------------------------
_MARK = {"ok": "✔", "fail": "✘", "unknown": "?"}


def format_report(report: dict) -> str:
    lines = []
    head = f"Token {report['symbol'] or '?'}  ({report['ca']})"
    lines.append(head)
    if report["pool_address"]:
        tvl = report["tvl"]
        tvl_text = f"${tvl:,.0f}".replace(",", ".") if tvl is not None else "—"
        age = report["pool_age_hours"]
        age_text = f"{age:.1f} jam" if age is not None else "—"
        lines.append(f"Pool  {report['pool_name'] or '?'}  {report['pool_address']}")
        lines.append(f"TVL {tvl_text}  ·  umur {age_text}")
        changes = "  |  ".join(
            f"{w.upper()} {_pct(report['changes'][w]) if report['changes'][w] is not None else 'tidak terukur'}"
            for w in WINDOWS)
        lines.append(f"Perubahan harga: {changes}")
    lines.append("")
    for check in report["checks"]:
        lines.append(f"  [{_MARK[check['status']]}] {check['name']}: {check['detail']}")
    lines.append("")
    lines.append(f"VERDICT: {report['verdict']}")
    lines.append(report["reason"])
    for warning in report["warnings"]:
        lines.append(f"Catatan: {warning}")
    lines.append("")
    lines.append("Heuristik, bukan saran investasi. Ambang ada di konstanta skrip.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def run(ca: str, *, timeout: int = HTTP_TIMEOUT) -> dict:
    """Ambil data semua window (paralel) lalu analisis."""
    rows_by_window: dict = {}
    errors: dict = {}
    with ThreadPoolExecutor(max_workers=len(WINDOWS)) as executor:
        futures = {w: executor.submit(fetch_window, ca, w, timeout=timeout)
                   for w in WINDOWS}
        for window, future in futures.items():
            try:
                rows_by_window[window] = future.result()
            except Exception as exc:  # noqa: BLE001 - tampilkan sebagai catatan
                rows_by_window[window] = []
                errors[window] = str(exc)[:160]
    if len(errors) == len(WINDOWS):
        raise RuntimeError("Semua permintaan ke API Meteora gagal: "
                           + "; ".join(f"{w}: {m}" for w, m in errors.items()))
    return analyze(ca, rows_by_window, now_ms=time.time() * 1000.0, errors=errors)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cek apakah token bagus untuk entri LP Meteora.")
    parser.add_argument("ca", nargs="?", help="contract address token (Solana)")
    parser.add_argument("--json", action="store_true", help="keluarkan JSON mentah")
    args = parser.parse_args(argv)

    raw = args.ca if args.ca else input("Tempel contract address: ")
    try:
        ca = valid_ca(raw)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    try:
        report = run(ca)
    except Exception as exc:  # noqa: BLE001 - pesan jelas untuk pengguna
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
