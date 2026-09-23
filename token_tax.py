# -*- coding: utf-8 -*-
"""Pajak transfer + dividend holder untuk kolom **TAX/DIVIDEND**.

Permintaan user 2026-09-23: kolom **tax/dividend** di tabel 🏆 Best Pool, tepat
di kiri **STRATEGY**. Bila token **punya dividend**, sel STRATEGY ditulis
persis ``30 70 spotbidask full range`` (verbatim, bukan frasa ``hybird …``
yang dipakai aturan likuiditas). Pajak saja tidak boleh mengubah strategi.

**Dividend** (satu-satunya pemicu override) = konfirmasi positif dari salah
satu sumber ini:

* **StonkFun** ``GET /api/public/v1/tokens/{mint}`` — ``mode == "reward"``
  (pajak transfer Token-2022 dibayarkan ke holder). ``mode == "standard"``,
  ``quoteOnlyFees``, dan jawaban ``not_found`` bukan dividend;
* **pump.fun** ``GET /coins-v2/{mint}`` — ``is_holder_reward is True``.
  ``is_cashback_enabled`` dan ``creator_reward`` / ``bonus_category`` bukan
  dividend.

**Pajak** (informasi saja, tidak pernah mengubah STRATEGY):

* ``transferFee.bps`` StonkFun (100 bps = 1%);
* peringatan Jupiter/Meteora ``TRANSFER_FEE_CONFIGURED`` (persen di pesan);
* ``security.transfer_fee`` rugchecker.cc (sudah persen).

Tidak terbaca (jaringan gagal, fetch dimatikan, hasil scan lama) → sel ``—``,
strategi likuiditas tetap, **baris tidak dibuang**. Suite tes mematikan HTTP
lewat ``TOKEN_TAX_FETCH=0`` (``tests/__init__.py``).
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
from urllib.parse import quote

STONKFUN_TOKEN_URL = "https://www.stonkfun.xyz/api/public/v1/tokens/{mint}"
PUMP_COIN_URL = "https://frontend-api-v3.pump.fun/coins-v2/{mint}"

#: Env kill-switch. ``0`` = jangan HTTP (suite tes). Selain itu fetch menyala.
FETCH_ENV = "TOKEN_TAX_FETCH"

CACHE_PATH = Path(__file__).resolve().parent / "token_tax_cache.json"
CACHE_TTL_OK = 1800
CACHE_TTL_FAIL = 300
CACHE_MAX_ENTRIES = 400

REQUEST_TIMEOUT = 12
WORKERS = 6

_FEE_RE = re.compile(
    r"transfer fee of\s+([0-9]+(?:[.,][0-9]+)?)\s*%",
    re.IGNORECASE,
)
_PCT_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*%")

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/152.0.0.0 Safari/537.36"),
}

_lock = threading.Lock()


def fetch_enabled() -> bool:
    """``False`` bila suite/offline mematikan HTTP (``TOKEN_TAX_FETCH=0``)."""
    return os.environ.get(FETCH_ENV, "1") != "0"


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_pct(value) -> float | None:
    number = _num(value)
    if number is None or number <= 0:
        return None
    return number


def format_tax_pct(pct) -> str:
    """Persen siap tampil: ``1%`` / ``1.5%`` / ``1.25%`` (bukan ``1.00%``)."""
    number = _num(pct)
    if number is None:
        return ""
    if abs(number - round(number)) < 1e-6:
        return f"{int(round(number))}%"
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def label_for(tax_pct, dividend: bool) -> str:
    """Teks sel: ``tax 1%`` / ``dividend`` / ``tax 1% · dividend`` / ``—``."""
    parts: list[str] = []
    if _positive_pct(tax_pct) is not None:
        parts.append(f"tax {format_tax_pct(tax_pct)}")
    if dividend:
        parts.append("dividend")
    return " · ".join(parts) if parts else "—"


def _warning_items(token) -> list:
    if not isinstance(token, dict):
        return []
    items: list = []
    for key in ("warnings", "critical_warnings", "warning"):
        value = token.get(key)
        if isinstance(value, list):
            items.extend(value)
        elif isinstance(value, (dict, str)) and value:
            items.append(value)
    return items


def _warning_text(item) -> tuple[str, str]:
    if isinstance(item, str):
        return item, ""
    if not isinstance(item, dict):
        return "", ""
    kind = str(item.get("type") or item.get("warning") or item.get("code") or "")
    message = str(item.get("message") or item.get("msg") or item.get("text") or "")
    return f"{kind} {message}".strip(), kind.upper()


def transfer_fee_pct_from_token(token) -> float | None:
    """Persen pajak transfer dari peringatan Jupiter/Meteora, atau ``None``.

    ``TRANSFER_FEE_CONFIGURED`` + pesan ``transfer fee of 1.00%`` → ``1.0``.
    Tanpa angka yang terbaca → ``None`` (bukan 0 palsu). Bukan penanda dividend.
    """
    for item in _warning_items(token):
        text, kind = _warning_text(item)
        if "TRANSFER_FEE" not in kind and "transfer fee" not in text.lower():
            continue
        match = _FEE_RE.search(text) or _PCT_RE.search(text)
        if not match:
            continue
        pct = _positive_pct(str(match.group(1)).replace(",", "."))
        if pct is not None:
            return pct
    return None


def _modes(payload) -> list[str]:
    modes: list[str] = []

    def add(value):
        if not isinstance(value, str):
            return
        text = value.strip().lower()
        if text in ("reward", "standard") and text not in modes:
            modes.append(text)

    if not isinstance(payload, dict):
        return modes
    add(payload.get("mode"))
    token = payload.get("token")
    if isinstance(token, dict):
        add(token.get("mode"))
    data = payload.get("data")
    if isinstance(data, dict):
        add(data.get("mode"))
        for key in ("token", "launch", "pool"):
            node = data.get(key)
            if isinstance(node, dict):
                add(node.get("mode"))
    return modes


def _bps_from_node(node) -> float | None:
    if not isinstance(node, dict):
        return None
    fee = node.get("transferFee")
    if isinstance(fee, dict):
        for key in ("bps", "transferFeeBps", "basisPoints"):
            if key in fee:
                return _num(fee.get(key))
        return None
    if isinstance(fee, (int, float)) and not isinstance(fee, bool):
        return _num(fee)
    for key in ("transferFeeBps", "transfer_fee_bps"):
        if key in node:
            return _num(node.get(key))
    return None


def _bps(payload) -> float | None:
    if not isinstance(payload, dict):
        return None
    nodes = [payload]
    token = payload.get("token")
    if isinstance(token, dict):
        nodes.append(token)
    data = payload.get("data")
    if isinstance(data, dict):
        nodes.append(data)
        for key in ("token", "launch", "pool"):
            node = data.get(key)
            if isinstance(node, dict):
                nodes.append(node)
    for node in nodes:
        bps = _bps_from_node(node)
        if bps is not None:
            return bps
    return None


def _not_found(payload, status: int) -> bool:
    if int(status or 0) == 404:
        return True
    if not isinstance(payload, dict):
        return False
    err = payload.get("error")
    if isinstance(err, dict):
        code = str(err.get("code") or "").strip().lower()
        if code in ("not_found", "404"):
            return True
    code = str(payload.get("code") or "").strip().lower()
    return code in ("not_found", "404")


def _blank_parse(*, answered: bool = False, dividend: bool = False,
                 not_found: bool = False, mode: str = "",
                 tax_pct=None) -> dict:
    return {
        "answered": answered,
        "dividend": dividend,
        "not_found": not_found,
        "mode": mode,
        "tax_pct": tax_pct,
    }


def parse_stonkfun(payload, *, status: int = 200) -> dict:
    """Baca satu jawaban ``GET /tokens/{mint}``.

    ``mode == "reward"`` (di ``data.token`` atau ``data.launch``) = dividend.
    ``standard`` / ``not_found`` = bukan dividend, tetapi **terjawab**.
    ``quoteOnlyFees`` dan ``creator_reward`` tidak pernah jadi dividend.
    """
    status = int(status or 0)
    if _not_found(payload, status):
        return _blank_parse(answered=True, not_found=True)
    if status != 200:
        return _blank_parse()
    modes = _modes(payload)
    if not modes:
        return _blank_parse()
    dividend = "reward" in modes
    bps = _bps(payload)
    tax = None if bps is None or bps <= 0 else bps / 100.0
    return _blank_parse(answered=True, dividend=dividend,
                        mode="reward" if dividend else "standard",
                        tax_pct=tax)


def parse_pump(payload, *, status: int = 200) -> dict:
    """Baca satu jawaban ``coins-v2``. Hanya ``is_holder_reward is True``.

    Cashback (``is_cashback_enabled``) dan ``creator_reward`` /
    ``bonus_category`` diabaikan. 404 = terjawab, bukan holder reward.
    Tanpa field ``is_holder_reward`` = tidak terjawab (jangan menebak).
    """
    status = int(status or 0)
    if status == 404:
        return _blank_parse(answered=True)
    if status != 200 or not isinstance(payload, dict):
        return _blank_parse()
    node = payload
    if "is_holder_reward" not in node:
        data = payload.get("data")
        if isinstance(data, dict) and "is_holder_reward" in data:
            node = data
        else:
            coin = payload.get("coin")
            if isinstance(coin, dict) and "is_holder_reward" in coin:
                node = coin
            else:
                return _blank_parse()
    return _blank_parse(answered=True, dividend=node.get("is_holder_reward") is True,
                        mode="holder_reward" if node.get("is_holder_reward") is True else "")


def combine(stonk: dict | None, pump: dict | None) -> dict:
    """Gabungkan dua sumber. Dividend hanya bila salah satu mengonfirmasi.

    ``dividend_known`` True bila ada konfirmasi positif, atau kedua sumber
    menjawab dan tidak ada yang reward/holder-reward. Satu sumber gagal dan
    yang lain tidak mengonfirmasi → belum diketahui (jangan override STRATEGY).
    """
    stonk = stonk or _blank_parse()
    pump = pump or _blank_parse()
    dividend = bool(stonk.get("dividend") or pump.get("dividend"))
    if dividend or (stonk.get("answered") and pump.get("answered")):
        known = True
    else:
        known = False
    tax = _positive_pct(stonk.get("tax_pct"))
    if tax is None:
        tax = _positive_pct(pump.get("tax_pct"))
    if stonk.get("dividend"):
        mode, source = "reward", "stonkfun"
    elif pump.get("dividend"):
        mode, source = "holder_reward", "pump"
    elif stonk.get("answered"):
        mode, source = str(stonk.get("mode") or ""), "stonkfun"
    elif pump.get("answered"):
        mode, source = "", "pump"
    else:
        mode, source = "", ""
    return {
        "ok": bool(known or stonk.get("answered") or pump.get("answered")),
        "dividend": dividend,
        "dividend_known": known,
        "tax_pct": tax,
        "mode": mode,
        "source": source,
        "fetched": True,
        "error": "",
    }


def _unknown(*, fetched: bool = False, error: str = "") -> dict:
    return {
        "ok": False,
        "dividend": False,
        "dividend_known": False,
        "tax_pct": None,
        "mode": "",
        "source": "",
        "fetched": fetched,
        "error": error[:200],
    }


def _local_tax_pct(row: dict) -> float | None:
    pct = _positive_pct(row.get("transfer_fee_pct"))
    if pct is not None:
        return pct
    rug = row.get("rugcheck")
    if isinstance(rug, dict):
        return _positive_pct(rug.get("transfer_fee"))
    return None


def row_tax_dividend(row: dict | None) -> dict:
    """Rangkuman siap UI: pajak lokal + flag dividend dari attach.

    Dividend **hanya** ``tax_dividend.dividend is True`` (konfirmasi parser).
    ``mode`` saja, pajak, cashback, dan ``creator_reward`` tidak dihitung.
    """
    row = row or {}
    stored = row.get("tax_dividend") if isinstance(row.get("tax_dividend"), dict) else {}
    dividend = stored.get("dividend") is True
    known = bool(stored.get("dividend_known")) or dividend
    tax = _positive_pct(stored.get("tax_pct"))
    if tax is None:
        tax = _local_tax_pct(row)
    source = str(stored.get("source") or "")
    if not source and _positive_pct(row.get("transfer_fee_pct")) is not None:
        source = "meteora"
    elif not source and tax is not None and isinstance(row.get("rugcheck"), dict):
        source = "rugcheck"
    label = label_for(tax, dividend)
    if dividend:
        sub = "holder reward"
        reason = ("dividend terkonfirmasi (holder reward) — STRATEGY memakai "
                  "\"30 70 spotbidask full range\"")
    elif known:
        sub = "transfer fee" if tax is not None else "—"
        reason = ("bukan dividend (bukan StonkFun reward dan bukan pump "
                  "holder reward)")
    else:
        sub = "transfer fee" if tax is not None else "—"
        reason = ("dividend belum terbaca — STRATEGY tidak diubah; hasil scan "
                  "sebelum kolom ini perlu di-scan ulang")
    if tax is not None:
        reason += f" · pajak transfer {format_tax_pct(tax)}"
        if not dividend:
            reason += " · pajak saja tidak mengubah STRATEGY"
    reason += " · kolom informasi, baris tidak dibuang"
    if source:
        reason += f" · sumber {source}"
    return {
        "ok": bool(stored.get("ok") or tax is not None or known),
        "tax_pct": tax,
        "dividend": dividend,
        "dividend_known": known,
        "source": source,
        "mode": str(stored.get("mode") or ""),
        "label": label,
        "sub": sub,
        "reason": reason,
    }


def row_has_dividend(row: dict | None) -> bool:
    """True hanya bila dividend terkonfirmasi. Pajak saja → False."""
    return row_tax_dividend(row).get("dividend") is True


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
                             key=lambda kv: _num((kv[1] or {}).get("at")) or 0)
            cache = dict(ordered[-CACHE_MAX_ENTRIES:])
        path = Path(CACHE_PATH)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _cache_get(mint: str) -> dict | None:
    entry = _cache_load().get(mint)
    if not isinstance(entry, dict):
        return None
    age = time.time() - (_num(entry.get("at")) or 0)
    ttl = CACHE_TTL_OK if entry.get("ok") else CACHE_TTL_FAIL
    if age > ttl:
        return None
    report = entry.get("report")
    return report if isinstance(report, dict) else None


def _cache_put(mint: str, report: dict) -> None:
    with _lock:
        cache = _cache_load()
        cache[mint] = {"at": int(time.time()),
                       "ok": bool(report.get("dividend_known") or report.get("ok")),
                       "report": report}
        _cache_save(cache)


def _get_json(url: str, *, timeout: int, referer: str = "") -> tuple[int, object]:
    """``(status, payload)``. Melempar ``RuntimeError`` bila transport gagal.

    404 dikembalikan (bukan exception) supaya parser bisa menandai "bukan
    token platform ini". Kill-switch ditolak di sini juga, supaya satu jalur
    yang lupa cek ``fetch_enabled`` tidak menyentuh jaringan saat tes.
    """
    if not fetch_enabled():
        raise RuntimeError("TOKEN_TAX_FETCH=0")
    headers = dict(_HEADERS)
    if referer:
        headers["referer"] = referer
    last = ""
    try:
        import requests
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            status = int(getattr(resp, "status_code", 0) or 0)
            if status in (200, 404):
                try:
                    return status, resp.json()
                except Exception:
                    return status, {}
            last = f"HTTP {status}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:160]
    except ImportError:
        last = "requests tidak terpasang"
    try:
        from curl_cffi import requests as client
        for identity in ("chrome", "chrome131", "safari17_0"):
            try:
                resp = client.get(url, impersonate=identity, timeout=timeout,
                                  headers=headers)
                status = int(getattr(resp, "status_code", 0) or 0)
                if status in (200, 404):
                    try:
                        return status, resp.json()
                    except Exception:
                        return status, {}
                last = f"HTTP {status}"
            except Exception as exc:  # noqa: BLE001
                last = str(exc)[:160]
    except ImportError:
        pass
    raise RuntimeError(last or "tanpa respons")


def fetch_report(mint: str, *, timeout: int = REQUEST_TIMEOUT,
                 use_cache: bool = True) -> dict:
    """Laporan remote satu mint. Tidak pernah melempar.

    StonkFun dulu. Pump hanya bila StonkFun belum mengonfirmasi dividend
    (hemat request; reward StonkFun sudah cukup untuk override).
    """
    mint = str(mint or "").strip()
    if not mint:
        return _unknown(error="mint kosong")
    if not fetch_enabled():
        return _unknown(error="TOKEN_TAX_FETCH=0")
    if use_cache:
        cached = _cache_get(mint)
        if isinstance(cached, dict):
            return dict(cached)
    try:
        status, payload = _get_json(
            STONKFUN_TOKEN_URL.format(mint=quote(mint, safe="")),
            timeout=timeout, referer="https://www.stonkfun.xyz/")
        stonk = parse_stonkfun(payload, status=status)
    except Exception as exc:  # noqa: BLE001 - satu mint mati ≠ scan mati
        stonk = _blank_parse()
        stonk_error = str(exc)[:160]
    else:
        stonk_error = ""
    pump = _blank_parse()
    pump_error = ""
    if not stonk.get("dividend"):
        try:
            status, payload = _get_json(
                PUMP_COIN_URL.format(mint=quote(mint, safe="")),
                timeout=timeout, referer="https://pump.fun/")
            pump = parse_pump(payload, status=status)
        except Exception as exc:  # noqa: BLE001
            pump_error = str(exc)[:160]
    report = combine(stonk, pump if not stonk.get("dividend") else _blank_parse())
    # StonkFun reward: pump tidak dipanggil, tetapi dividend sudah pasti.
    if stonk.get("dividend"):
        report["dividend_known"] = True
        report["dividend"] = True
    if not report.get("dividend_known"):
        report["error"] = " · ".join(part for part in (stonk_error, pump_error) if part)
        report["ok"] = False
    if use_cache and (report.get("dividend_known") or report.get("ok")):
        _cache_put(mint, report)
    return report


def attach_to_rows(rows, *, workers: int = WORKERS,
                   timeout: int = REQUEST_TIMEOUT,
                   use_cache: bool = True) -> list[dict]:
    """Tempel ``row["tax_dividend"]``. Tidak menyaring dan tidak melempar.

    Fetch dimatikan (``TOKEN_TAX_FETCH=0``) tetap mengisi laporan lokal supaya
    pajak dari peringatan Meteora tetap tampil, tanpa menyentuh jaringan dan
    tanpa menandai dividend.
    """
    copied = [dict(row) if isinstance(row, dict) else {} for row in (rows or [])]
    if not copied:
        return copied
    if not fetch_enabled():
        for row in copied:
            row["tax_dividend"] = _unknown(error="TOKEN_TAX_FETCH=0")
        return copied

    mints = list(dict.fromkeys(
        str(row.get("ca") or "").strip() for row in copied
        if str(row.get("ca") or "").strip()))
    reports: dict[str, dict] = {}
    if mints:
        workers = max(1, min(int(workers or 1), 8))

        def _job(mint: str):
            return mint, fetch_report(mint, timeout=timeout, use_cache=use_cache)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_job, mint) for mint in mints]
            for future in as_completed(futures):
                try:
                    mint, report = future.result()
                except Exception as exc:  # noqa: BLE001
                    continue
                reports[mint] = report
    for row in copied:
        mint = str(row.get("ca") or "").strip()
        row["tax_dividend"] = reports.get(mint) or _unknown(
            fetched=bool(mint), error="" if mint else "mint kosong")
    return copied
