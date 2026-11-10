#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cek cepat: apakah LP di sebuah pool Meteora sedang KELUAR (likuiditas ditarik)?

Tempel contract address (CA). Tool mengambil data pool Meteora per window
(1H, 4H, 12H, 24H) lalu menghitung deposit, withdraw, dan net deposit.
Sinyal: net deposit negatif, yaitu total withdraw lebih besar dari total deposit.
Hanya heuristik, bukan saran investasi.

Pemakaian:
    python3 tools/lp_exit_check/lp_exit_check.py <CONTRACT_ADDRESS>
    python3 tools/lp_exit_check/lp_exit_check.py          # tempel CA saat diminta
    python3 tools/lp_exit_check/lp_exit_check.py <CA> --json

Hanya memakai pustaka standar Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

POOLS_URL = "https://pool-discovery-api.datapi.meteora.ag/pools"
WINDOWS = ("1h", "4h", "12h", "24h")
HTTP_TIMEOUT = 25

VERDICT_RECENT = "LP KELUAR TERBARU"        # net negatif pada 1H atau 4H
VERDICT_EARLIER = "LP KELUAR SEBELUMNYA"    # net negatif hanya pada 12H atau 24H
VERDICT_NONE = "TIDAK ADA SINYAL"           # semua window terukur dan net tidak negatif
VERDICT_DATA = "DATA KURANG"                # sebagian window tidak terukur, tidak ada sinyal
VERDICT_NO_POOL = "TIDAK ADA POOL"

# Base58 (tanpa 0, O, I, l), 32–44 karakter — format alamat Solana.
_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


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
        url, headers={"User-Agent": "Mozilla/5.0 (lp-exit-check)",
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
    """Field deposit/withdraw dari satu pool pada satu window."""
    if not pool:
        return None
    deposits = _num(pool.get("total_deposits"))
    withdraws = _num(pool.get("total_withdraws"))
    net = _num(pool.get("net_deposits"))
    if net is None and deposits is not None and withdraws is not None:
        net = deposits - withdraws
    if deposits is None or withdraws is None or net is None:
        return None
    return {
        "deposits": deposits,
        "withdraws": withdraws,
        "net": net,
        "tvl": _num(pool.get("tvl")),
    }


# ---------------------------------------------------------------------------
# Analisis (murni, tanpa jaringan)
# ---------------------------------------------------------------------------

def analyze(ca: str, rows_by_window: dict, *, errors: dict | None = None) -> dict:
    """Hitung sinyal LP keluar dari respons per window.

    ``rows_by_window[w]`` = list pool mentah dari API untuk window ``w``.
    ``errors[w]`` = pesan gagal fetch window ``w`` (window itu jadi tidak terukur).
    """
    errors = errors or {}
    warnings = [f"Data {w.upper()} gagal diambil: {msg}" for w, msg in errors.items()]

    candidates: dict[str, dict] = {}
    for window in ("1h",) + tuple(w for w in WINDOWS if w != "1h"):
        for pool in pools_for_mint(rows_by_window.get(window) or [], ca):
            address = str(pool.get("pool_address") or "")
            if address and address not in candidates:
                candidates[address] = pool

    if not candidates:
        return _empty_report(ca, VERDICT_NO_POOL, "Tidak ada pool Meteora untuk CA ini.", warnings)

    main_addr = max(candidates, key=lambda a: _num(candidates[a].get("tvl")) or 0.0)
    main_pool = candidates[main_addr]
    if len(candidates) > 1:
        warnings.append(f"Ada {len(candidates)} pool untuk token ini; "
                        "yang dinilai pool dengan TVL terbesar.")

    token_x = main_pool.get("token_x") or {}
    symbol = str(token_x.get("symbol") or "?") if str(token_x.get("address") or "") == ca \
        else str((main_pool.get("token_y") or {}).get("symbol") or "?")

    per_window = {}
    for window in WINDOWS:
        match = next((p for p in rows_by_window.get(window) or []
                      if str(p.get("pool_address") or "") == main_addr), None)
        per_window[window] = _metrics(match)

    exit_windows = [w for w in WINDOWS if per_window[w] and per_window[w]["net"] < 0]
    missing = [w for w in WINDOWS if per_window[w] is None]
    if missing:
        warnings.append("Window tidak terukur untuk pool ini: "
                        + ", ".join(w.upper() for w in missing) + ".")

    if any(w in exit_windows for w in ("1h", "4h")):
        verdict = VERDICT_RECENT
        reason = ("Net deposit negatif pada "
                  + ", ".join(w.upper() for w in exit_windows if w in ("1h", "4h"))
                  + ": total withdraw lebih besar dari total deposit, likuiditas sedang ditarik.")
    elif exit_windows:
        verdict = VERDICT_EARLIER
        reason = ("Net deposit negatif hanya pada "
                  + ", ".join(w.upper() for w in exit_windows)
                  + ". Penarikan terjadi lebih lama, belum terlihat di 1H dan 4H.")
    elif missing:
        verdict = VERDICT_DATA
        reason = "Tidak ada sinyal, tetapi sebagian window belum terukur."
    else:
        verdict = VERDICT_NONE
        reason = "Net deposit tidak negatif di semua window: tidak ada tanda LP keluar."

    return {
        "ca": ca,
        "symbol": symbol,
        "pool_address": main_addr,
        "pool_name": str(main_pool.get("name") or ""),
        "windows": per_window,
        "exit_windows": exit_windows,
        "verdict": verdict,
        "reason": reason,
        "warnings": warnings,
    }


def _empty_report(ca: str, verdict: str, reason: str, warnings: list) -> dict:
    return {
        "ca": ca, "symbol": "?", "pool_address": None, "pool_name": "",
        "windows": {w: None for w in WINDOWS}, "exit_windows": [],
        "verdict": verdict, "reason": reason, "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Pengambilan data & format
# ---------------------------------------------------------------------------

def run(ca: str, *, timeout: int = HTTP_TIMEOUT) -> dict:
    """Ambil semua window (paralel) lalu analisis. Raise bila semua window gagal."""
    rows_by_window: dict[str, list] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(WINDOWS)) as executor:
        futures = {w: executor.submit(fetch_window, ca, w, timeout=timeout) for w in WINDOWS}
        for window, future in futures.items():
            try:
                rows_by_window[window] = future.result()
            except Exception as exc:  # noqa: BLE001 — tampilkan alasan gagal apa adanya
                errors[window] = str(exc) or type(exc).__name__
    if len(errors) == len(WINDOWS):
        raise RuntimeError("Semua permintaan ke Meteora gagal: " + "; ".join(errors.values()))
    return analyze(ca, rows_by_window, errors=errors)


def _money(value) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}".replace(",", ".")


def format_report(report: dict) -> str:
    lines = [f"{report['symbol']}  ·  {report['ca']}"]
    if report["pool_address"]:
        lines.append(f"Pool {report['pool_name']} · {report['pool_address']}")
    lines.append("")
    lines.append(f"VERDICT: {report['verdict']}")
    lines.append(report["reason"])
    if report["windows"] and any(report["windows"].values()):
        lines.append("")
        lines.append(f"{'Window':<8}{'Deposit':>14}{'Withdraw':>14}{'Net':>14}  Status")
        for w in WINDOWS:
            m = report["windows"][w]
            if m is None:
                lines.append(f"{w.upper():<8}{'—':>14}{'—':>14}{'—':>14}  tidak terukur")
                continue
            status = "KELUAR" if m["net"] < 0 else "ok"
            lines.append(f"{w.upper():<8}{_money(m['deposits']):>14}"
                         f"{_money(m['withdraws']):>14}{_money(m['net']):>14}  {status}")
    for warning in report["warnings"]:
        lines.append(f"⚠ {warning}")
    return "\n".join(lines)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cek LP keluar di pool Meteora untuk sebuah CA.")
    parser.add_argument("ca", nargs="?", help="contract address token Solana")
    parser.add_argument("--json", action="store_true", help="keluarkan hasil mentah sebagai JSON")
    args = parser.parse_args(argv)

    raw = args.ca or input("Tempel contract address (CA): ")
    try:
        ca = valid_ca(raw)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    try:
        report = run(ca)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: gagal mengambil data Meteora: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
