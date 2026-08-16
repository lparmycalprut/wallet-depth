"""Bottom detector — 3 sinyal bottom dari ΔCVD harian dan volume USD.

Konsep (divalidasi empiris pada 8 token pump historis: hoppy, assface,
grail, bountywork, ansem, chance, testicle, punch):

- ΔCVD (SOL) = Σ(buy_quote_sol) − Σ(sell_quote_sol) dalam 1 hari
- Volume     = buy + sell dalam USD (``amount_usd``) — SELALU USD, bukan SOL,
  karena saat token dump nilai SOL ikut menyusut sehingga rasio SOL ≠ USD.
- Batas hari = 00:00 UTC (= 07:00 WIB, konvensi GMGN).

Tiga sinyal (semua bias "bullish"), dicek berurutan per hari:
  1. SELLER_EXHAUSTION — CVD runtuh vs flush, volume KERING (≤40% kemarin)
  2. REVERSAL          — CVD runtuh vs flush, volume NAIK (≥130% kemarin)
  3. AKUMULASI         — CVD positif nyata, harga belum naik, volume NAIK
  4. lainnya           — "—"

Threshold di bawah final — jangan diubah. Deteksi lama (4-pilar,
effort-to-result R = |CVD|/|ΔHarga%|, multiplier M, baseline sehat, S1..S5,
ABSORBSI LANGSUNG, PENYERAPAN, retention/diamond-hands) sudah dihapus.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Iterable


def _atomic_write_json(path, data, **kwargs):
    """Write JSON atomically without importing the network/data stack."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".effort-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, **kwargs)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_EFFORT_PATH = os.path.join(BASE_DIR, "daily_effort.json")

# --- Threshold FINAL (§1 prompt; jangan diubah) ------------------------------
# Seller exhaustion / reversal (bersama)
SELLING_FLUSH_CVD = 30.0            # flush = hari dgn CVD <= -30 SOL
SELLING_COLLAPSE_RATIO = 0.40       # hari N |CVD| <= 40% dari flush (runtuh)
SELLING_LOOKBACK_DAYS = 5           # cari flush dalam 5 hari ke belakang
SELLING_PRICE_CAP_PCT = 0.5         # harga hari N <= +0.5% (belum rebound)
SELLING_VOLUME_SHRINK_RATIO = 0.40  # exhaustion: volume <= 40% hari sebelumnya
REVERSAL_VOLUME_SURGE_RATIO = 1.30  # reversal: volume >= 130% hari sebelumnya

# Akumulasi
ACCUM_CVD_MIN = 5.0                 # CVD hari N >= +5 SOL
ACCUM_PRICE_CAP_PCT = 0.5           # harga hari N <= +0.5%
ACCUM_VOLUME_SURGE_RATIO = 1.30     # volume >= 130% hari sebelumnya

# Flag
WHALE_PCT_THRESHOLD = 40.0          # top-1 wallet >= 40% volume = dominasi whale
VOLUME_MC_MAX_RATIO = 3.0           # volume <= 3x marketcap close (anti wash-trade)

# Storage window untuk daily_effort.json (bukan sinyal holder/retensi;
# murni berapa hari baris harian yang disimpan per mint).
STORAGE_WINDOW_DAYS = 30

# --- Nama sinyal --------------------------------------------------------------
SELLER_EXHAUSTION = "SELLER_EXHAUSTION"
REVERSAL = "REVERSAL"
AKUMULASI = "AKUMULASI"
NO_SIGNAL = "—"
SIGNALS = (SELLER_EXHAUSTION, REVERSAL, AKUMULASI)

SIGNAL_META = {
    SELLER_EXHAUSTION: {
        "emoji": "🟢", "label": "SELLER EXHAUSTION", "tone": "bull",
        "bias": "bullish",
        "description": "Panic seller habis — CVD runtuh & volume kering"},
    REVERSAL: {
        "emoji": "🟣", "label": "REVERSAL", "tone": "rev",
        "bias": "bullish",
        "description": "Penjual habis + buyer mulai masuk — volume naik"},
    AKUMULASI: {
        "emoji": "🔵", "label": "AKUMULASI", "tone": "aku",
        "bias": "bullish",
        "description": "Buyer masuk diam-diam — CVD positif, harga belum naik"},
}

# Kolom export CSV harian (dipakai halaman backtest + rows_with_signals).
EXPORT_COLUMNS = [
    "mint", "date", "open", "close", "price_chg_pct", "cvd_delta",
    "direction", "volume_usd", "marketcap_close", "signal", "flush_date",
    "coverage_hours", "top_wallet_pct", "unique_makers",
    "smart_money_buy", "fresh_buy", "bot_sell", "mev_noise",
]

# 4 penanda on-chain yang di-pass-through ke output (info, bukan syarat).
ONCHAIN_TAG_KEYS = ("smart_money_buy", "fresh_buy", "bot_sell", "mev_noise")


def _finite(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _optional_float(value):
    """Finite float or ``None`` (missing/unparseable stays unknown)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_count(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def daily_effort_record(mint: str, date: str, open_price: float,
                        close_price: float, cvd_delta: float) -> dict:
    """Build one canonical daily row.

    ΔPrice% = (Close-Open)/Open*100  (batas hari 00:00 UTC)
    ΔCVD    = Σ(delta_sol) hari itu (SOL)

    Tanpa ``ratio``/R/M — metrik effort-to-result lama sudah dihapus.
    Volume USD, marketcap close, dan 4 penanda on-chain ditambahkan oleh
    ``cvd_daily.build_effort_rows``.
    """
    opening = _finite(open_price)
    closing = _finite(close_price)
    delta = _finite(cvd_delta)
    price_pct = ((closing - opening) / opening * 100.0
                 if opening > 0 else 0.0)
    if price_pct > 0:
        direction = "up"
    elif price_pct < 0:
        direction = "down"
    else:
        direction = "flat"
    return {
        "mint": str(mint),
        "date": str(date),
        "open": opening,
        "close": closing,
        "price_chg_pct": round(price_pct, 8),
        "cvd_delta": round(delta, 8),
        "direction": direction,
    }


def _find_flush(sorted_rows: list[dict], idx: int):
    """Cari flush = min(CVD) pada maks 5 hari sebelum ``idx``.

    Flush valid bila CVD <= -SELLING_FLUSH_CVD (-30 SOL).
    Return (flush_row, flush_cvd) atau (None, None).
    """
    look_start = max(0, idx - SELLING_LOOKBACK_DAYS)
    flush_row = None
    flush_cvd = None
    for j in range(look_start, idx):
        row = sorted_rows[j]
        cvd = _finite(row.get("cvd_delta"))
        if cvd <= -SELLING_FLUSH_CVD and (flush_cvd is None or cvd < flush_cvd):
            flush_row = row
            flush_cvd = cvd
    return flush_row, flush_cvd


def _result(current, previous, *, signal=NO_SIGNAL, bias=None, status,
            reason, flush_row=None, wash_blocked=False) -> dict:
    """Standard result dict per spesifikasi (§5):
    signal, bias, reason, flush_date, cvd_delta, volume_usd, flag_divergence,
    whale_driven — plus konteks operasional (volume vs kemarin, marketcap,
    4 penanda on-chain).
    """
    cur = current or {}
    prev = previous or {}
    price_pct = _finite(cur.get("price_chg_pct"))
    cvd = _finite(cur.get("cvd_delta"))
    direction = (cur.get("direction")
                 or ("up" if price_pct > 0
                     else "down" if price_pct < 0 else "flat"))
    volume_usd = _optional_float(cur.get("volume_usd"))
    volume_prev = _optional_float(prev.get("volume_usd")) if prev else None
    volume_pct = None
    if (volume_usd is not None and volume_prev is not None
            and volume_prev > 0):
        volume_pct = round(volume_usd / volume_prev * 100.0, 4)
    flush_cvd = _optional_float(flush_row.get("cvd_delta")) if flush_row else None
    collapse_pct = (round(abs(cvd) / abs(flush_cvd) * 100.0, 4)
                    if flush_cvd not in (None, 0) else None)
    marketcap = _optional_float(cur.get("marketcap_close"))
    top_pct = _finite(cur.get("top_wallet_pct"))
    return {
        "mint": str(cur.get("mint") or ""),
        "date": cur.get("date"),
        "previous_date": prev.get("date") if prev else None,
        "direction": direction,
        "signal": signal,
        "bias": bias,
        "status": status,
        "reason": reason,
        "price_chg_pct": price_pct,
        "cvd_delta": cvd,
        "flush_date": flush_row.get("date") if flush_row else None,
        "flush_cvd": round(flush_cvd, 8) if flush_cvd is not None else None,
        "collapse_pct": collapse_pct,
        "volume_usd": round(volume_usd, 2) if volume_usd is not None else None,
        "volume_prev_usd": (round(volume_prev, 2)
                            if volume_prev is not None else None),
        "volume_pct": volume_pct,
        "marketcap_close": (round(marketcap, 2)
                            if marketcap is not None else None),
        "wash_blocked": bool(wash_blocked),
        "flag_divergence": bool((price_pct < 0 < cvd)
                                or (price_pct > 0 > cvd)),
        "whale_driven": bool(top_pct >= WHALE_PCT_THRESHOLD),
        "top_wallet_pct": round(top_pct, 8) if cur else None,
        "pair": cur.get("pair") or cur.get("pair_address"),
        "smart_money_buy": _int_count(cur.get("smart_money_buy")),
        "fresh_buy": _int_count(cur.get("fresh_buy")),
        "bot_sell": _int_count(cur.get("bot_sell")),
        "mev_noise": _int_count(cur.get("mev_noise")),
    }


def _vol_txt(volume_pct) -> str:
    return (f"{volume_pct:.0f}%" if volume_pct is not None else "—")


def classify_at(rows: Iterable[dict], idx: int) -> dict:
    """Klasifikasi SATU hari (rows[idx] sebagai hari N) → 3 sinyal bottom.

    Urutan pengecekan persis (§3):
      1. SELLER_EXHAUSTION — CVD negatif runtuh vs flush + volume turun ≤40%
         + volume ≤ 3× marketcap close (anti wash, bila MC tersedia)
      2. REVERSAL          — gerbang sama, volume NAIK ≥130% (syarat volume
         berganti; gerbang anti-wash tetap diwarisi)
      3. AKUMULASI         — CVD ≥ +5 SOL + harga ≤ +0.5% + volume ≥130%
      4. selain itu        — "—"
    """
    selected = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    selected.sort(key=lambda r: str(r.get("date") or ""))

    try:
        index = int(idx)
    except (TypeError, ValueError):
        index = -1
    if not selected or index < 0 or index >= len(selected):
        return _result(None, None, status="missing",
                       reason="index di luar rentang atau tidak ada data")

    current = selected[index]
    previous = selected[index - 1] if index >= 1 else None
    cvd = _finite(current.get("cvd_delta"))
    price_pct = _finite(current.get("price_chg_pct"))
    volume_usd = _optional_float(current.get("volume_usd"))
    volume_prev = (_optional_float(previous.get("volume_usd"))
                   if previous is not None else None)
    vol_ok = (volume_usd is not None and volume_prev is not None
              and volume_prev > 0)
    volume_pct = (volume_usd / volume_prev * 100.0
                  if vol_ok else None)
    marketcap = _optional_float(current.get("marketcap_close"))

    if index < 1:
        return _result(current, previous, status="first_day",
                       reason="hari pertama window — tidak ada hari pembanding")

    price_capped = price_pct <= SELLING_PRICE_CAP_PCT
    shrunk = vol_ok and volume_usd <= SELLING_VOLUME_SHRINK_RATIO * volume_prev
    surged = vol_ok and volume_usd >= REVERSAL_VOLUME_SURGE_RATIO * volume_prev
    # Anti wash-trade: volume harian tidak boleh melebihi 3x marketcap close
    # (hanya ditegakkan bila MC tersedia).
    wash = bool(marketcap is not None and marketcap > 0
                and volume_usd is not None
                and volume_usd > VOLUME_MC_MAX_RATIO * marketcap)

    # --- 1 & 2. SELLER_EXHAUSTION / REVERSAL (CVD negatif yang runtuh) ------
    if cvd < 0 and price_capped:
        flush_row, flush_cvd = _find_flush(selected, index)
        if flush_row is None:
            return _result(
                current, previous, status="no_signal",
                reason=(f"CVD {cvd:+.2f} — tidak ada flush ≤ "
                        f"-{SELLING_FLUSH_CVD:g} SOL dalam "
                        f"{SELLING_LOOKBACK_DAYS} hari ke belakang"))
        collapse_pct = abs(cvd) / abs(flush_cvd) * 100.0 if flush_cvd else 0.0
        if abs(cvd) > SELLING_COLLAPSE_RATIO * abs(flush_cvd):
            return _result(
                current, previous, status="no_signal", flush_row=flush_row,
                reason=(f"CVD {cvd:+.2f} masih {collapse_pct:.0f}% dari flush "
                        f"{flush_row.get('date')} ({flush_cvd:+.2f}) — "
                        f"belum runtuh ≤{SELLING_COLLAPSE_RATIO * 100:g}%"))
        if not vol_ok:
            return _result(
                current, previous, status="no_signal", flush_row=flush_row,
                reason=("CVD runtuh vs flush, tetapi volume USD hari "
                        "N/N-1 tidak tersedia untuk perbandingan"))
        if shrunk or surged:
            if wash:
                return _result(
                    current, previous, status="no_signal",
                    flush_row=flush_row, wash_blocked=True,
                    reason=(f"volume {_vol_txt(volume_pct)} dari kemarin "
                            f"melebihi {VOLUME_MC_MAX_RATIO:g}x marketcap "
                            f"close — kemungkinan wash-trade, sinyal dibatalkan"))
            if shrunk:
                signal = SELLER_EXHAUSTION
                reason = (f"SELLER_EXHAUSTION: tekanan jual runtuh "
                          f"({collapse_pct:.1f}% dari flush "
                          f"{flush_row.get('date')} @ {flush_cvd:+.2f} SOL) "
                          f"dan volume kering ({_vol_txt(volume_pct)} dari "
                          f"kemarin)")
            else:
                signal = REVERSAL
                reason = (f"REVERSAL: penjual habis (CVD tinggal "
                          f"{collapse_pct:.1f}% dari flush "
                          f"{flush_row.get('date')} @ {flush_cvd:+.2f} SOL) "
                          f"dan buyer mulai masuk — volume naik "
                          f"{_vol_txt(volume_pct)} dari kemarin")
            return _result(current, previous, signal=signal, bias="bullish",
                           status="signal", reason=reason,
                           flush_row=flush_row)
        return _result(
            current, previous, status="no_signal", flush_row=flush_row,
            reason=(f"CVD runtuh ({collapse_pct:.1f}% dari flush), tetapi "
                    f"volume {_vol_txt(volume_pct)} dari kemarin berada di "
                    f"antara {SELLING_VOLUME_SHRINK_RATIO * 100:g}% dan "
                    f"{REVERSAL_VOLUME_SURGE_RATIO * 100:g}% — tanpa sinyal"))

    # --- 3. AKUMULASI --------------------------------------------------------
    if cvd >= ACCUM_CVD_MIN and price_pct <= ACCUM_PRICE_CAP_PCT:
        if surged:
            reason = (f"AKUMULASI: CVD {cvd:+.2f} SOL saat harga "
                      f"{price_pct:+.1f}% (belum bergerak), volume naik "
                      f"{_vol_txt(volume_pct)} dari kemarin")
            return _result(current, previous, signal=AKUMULASI,
                           bias="bullish", status="signal", reason=reason)
        if not vol_ok:
            return _result(
                current, previous, status="no_signal",
                reason=(f"CVD {cvd:+.2f} memenuhi ambang akumulasi, tetapi "
                        f"volume USD hari N/N-1 tidak tersedia"))
        return _result(
            current, previous, status="no_signal",
            reason=(f"CVD {cvd:+.2f} positif, tetapi volume "
                    f"{_vol_txt(volume_pct)} dari kemarin < "
                    f"{ACCUM_VOLUME_SURGE_RATIO * 100:g}% — akumulasi tidak "
                    f"terkonfirmasi"))

    return _result(current, previous, status="no_signal",
                   reason="tidak ada pola bottom yang terpenuhi")


def classify_all(rows: Iterable[dict]) -> list[dict]:
    """Scan seluruh window — tiap hari (idx>=1) dievaluasi; hari pertama "—"."""
    selected = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    selected.sort(key=lambda r: str(r.get("date") or ""))
    return [classify_at(selected, idx) for idx in range(len(selected))]


def classify_effort(rows: Iterable[dict], mint: str | None = None) -> dict:
    """Hari terakhir (untuk verdict)."""
    selected = [dict(row) for row in (rows or []) if isinstance(row, dict)
                and (not mint or row.get("mint") == mint)]
    selected.sort(key=lambda row: str(row.get("date") or ""))
    if not selected:
        result = _result(None, None, status="missing",
                         reason="tidak ada data")
        result["mint"] = str(mint or "")
        return result
    return classify_at(selected, len(selected) - 1)


# --- Storage harian (idempoten) ----------------------------------------------
def load_daily_effort(path: str = DAILY_EFFORT_PATH) -> list[dict]:
    """Load canonical rows; malformed files safely produce an empty list."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def merge_daily_effort(new_rows: Iterable[dict], *,
                       path: str = DAILY_EFFORT_PATH,
                       window_days: int = STORAGE_WINDOW_DAYS) -> list[dict]:
    """Idempotently upsert mint/date rows and keep the newest N days per mint."""
    merged = {}
    for row in [*load_daily_effort(path), *(new_rows or [])]:
        if not isinstance(row, dict):
            continue
        mint = str(row.get("mint") or "").strip()
        date = str(row.get("date") or "").strip()
        if mint and date:
            merged[(mint, date)] = dict(row)
    by_mint = {}
    for row in merged.values():
        by_mint.setdefault(row["mint"], []).append(row)
    kept = []
    limit = max(2, int(window_days))
    for mint_rows in by_mint.values():
        mint_rows.sort(key=lambda row: row["date"])
        kept.extend(mint_rows[-limit:])
    kept.sort(key=lambda row: (row["mint"], row["date"]))
    _atomic_write_json(path, kept, indent=2)
    return kept


def rows_for_mint(rows: Iterable[dict], mint: str) -> list[dict]:
    result = [dict(row) for row in (rows or []) if row.get("mint") == mint]
    return sorted(result, key=lambda row: row.get("date", ""))


def rows_with_signals(rows: Iterable[dict]) -> list[dict]:
    """Export harian: satu sinyal per hari dengan kolom EXPORT_COLUMNS.

    Kolom operasional yang hilang diisi kosong, bukan diarang.
    """
    sorted_rows = sorted([dict(r) for r in (rows or []) if isinstance(r, dict)],
                         key=lambda r: str(r.get("date") or ""))
    classified = classify_all(sorted_rows)
    out = []
    for row, res in zip(sorted_rows, classified):
        entry = {}
        for column in EXPORT_COLUMNS:
            if column == "signal":
                entry[column] = res.get("signal")
            elif column == "flush_date":
                entry[column] = res.get("flush_date")
            elif column in ONCHAIN_TAG_KEYS:
                entry[column] = _int_count(row.get(column))
            else:
                entry[column] = row.get(column)
        out.append(entry)
    return out


# --- Rekapan teks per hari (blok komentar # di CSV / dashboard) --------------
def format_recap(mint: str, rows: Iterable[dict]) -> str:
    """Rekapan per hari sesuai §6:
    ``# <date>  <SIGNAL padded> | Δ<+%>% | CVD <+x> | vol <y>% dari kemarin``
    Hanya hari dengan sinyal yang direkap.
    """
    pool = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    if mint:
        filtered = [r for r in pool if r.get("mint") == mint]
        if filtered:
            pool = filtered
    pool.sort(key=lambda r: str(r.get("date") or ""))
    results = classify_all(pool)
    lines = ["# === REKAPAN 3 SINYAL BOTTOM ==="]
    if mint:
        lines.append(f"# Mint: {mint}")
    if results:
        first = results[0].get("date") or "?"
        last = results[-1].get("date") or "?"
        lines.append(f"# Hari: {len(results)} ({first} s/d {last})")
    for res in results:
        signal = res.get("signal")
        if signal not in SIGNALS:
            continue
        date = res.get("date") or "?"
        price = res.get("price_chg_pct") or 0.0
        cvd = res.get("cvd_delta") or 0.0
        lines.append(
            f"# {date}  {signal:<19}| Δ{price:+.1f}% | CVD {cvd:+.1f} | "
            f"vol {_vol_txt(res.get('volume_pct'))} dari kemarin")
    return "\n".join(lines)
