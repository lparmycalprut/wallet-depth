# -*- coding: utf-8 -*-
"""Telegram rules and transport for holder-dust scans.

The rule functions are deliberately independent from the HTTP transport so a
scan can be evaluated in unit tests without sending a Telegram request. Dust
changes are *percentage-point* changes of ``dust_pct_mc``, never relative
percentage changes.

Perubahan dust saja baru menjadi *kandidat* sinyal. Sebelum alert dikirim,
kandidat diperiksa silang terhadap pasar (volume + harga + volatilitas) oleh
:func:`validate_alert_with_volume` / :func:`volume_verdict`, sehingga dust yang
naik tanpa lonjakan volume atau tanpa tekanan harga dicatat lalu dibuang, bukan
mengganggu user. Fungsi aturan tidak pernah mengambil data itu sendiri: pemanggil
menyuntikkan dict konteks yang sudah jadi, atau ``context_provider(mint,
analysis)`` yang **hanya dipanggil bila ada kandidat** (lazy — cron 1 jam
tidak menambah satu pun API call saat pasar tenang).

Rule tambahan ``early_dump`` (⚡ EARLY DUMP, scope token pool Meteora/Chart
LP maupun watchlist Robinhood LP — pemanggil cron mengirim ``lp_mints``)
menyala **selama** dust berada di atas ambang absolut 0,1% MC
(:data:`holder_history.DUST_BEST_PCT`): sejak 2026-09-05 pengingat dikirim
ulang **tiap scan** (±15 menit) sampai token dihapus dari watchlist LP atau
dipindah ke watchlist biasa — tanpa gerbang volume keras (konteks pasar =
info di pesan, lihat :func:`early_dump_verdict`), dedup per bucket 15 menit
(:data:`FAST_BUCKET_SEC`) + jeda :data:`EARLY_DUMP_RESEND_SEC`; turun ke
<= 0,1% = reset; marker ``alert_state["early_dump"]`` = ``{ts,
dust_pct_mc}`` run terakhir (di-merge paling baru oleh
``holder_history._merge_alert_state``, dipertahankan
``compact_alert_state``).

Rule ``high_drop`` (🔔 HIGH DROP, scope watchlist **biasa** Solana/Robinhood
— pemanggil cron mengirim ``high_mints``): titik acuan = **hold % MC
terbesar** yang pernah tercatat (marker ``alert_state["high_drop"]`` =
``{ts, high, high_ts, notified_high}``); dust % MC yang turun >= 50%
(:data:`HIGH_DROP_RATIO`) dari titik high mengirim alert satu kali per titik
high (naik ke high baru / keluar zona drop = re-arm), tanpa gerbang volume
keras, dedup bucket 4 jam + ``MIN_RESEND_SEC``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import os
import sys
import time
from typing import Callable, Iterable, NamedTuple
from zoneinfo import ZoneInfo

import requests

from holder_history import DUST_BEST_PCT
from links import (hawkfi_meteora_url, meteora_dlmm_url, token_link_lines)

DUMP_THRESHOLD_PP = 0.25
ACCUMULATION_THRESHOLD_PP = 0.50
BASELINE_SHIFT_THRESHOLD_PP = 1.00

# --- Konfirmasi volume/harga/volatilitas (filter false positive) -------------
# ``avg_volume_7d`` SELALU berarti rata-rata volume per window 4 jam selama 7
# hari terakhir, jadi pembandingnya setara dengan ``volume_4h`` (bukan total
# volume harian — kalau harian, ambang 2x praktis tidak pernah tercapai).
DUMP_VOLUME_MULTIPLE = 2.0             # dump: volume 4 jam >= 2x rata-rata
ACCUMULATION_VOLUME_MULTIPLE = 1.5     # akumulasi: volume 4 jam >= 1,5x
DUMP_PRICE_CHANGE_PCT = -1.0           # dump: harga sudah turun >= 1%
VOLUME_FULL_BONUS_RATIO = 2.0          # bonus volume penuh pada 2x ambang rasio
DUMP_PRICE_FULL_BONUS_PCT = -5.0       # bonus harga penuh pada -5%
ACCUMULATION_PRESSURE_FULL_RATIO = 2.0  # bonus penuh saat buy >= 2x sell
MIN_CONFIDENCE = 0.70                  # ambang skor konfirmasi
MIN_CONFIDENCE_HIGH_VOLATILITY = 0.80  # ambang naik saat pasar sedang liar
UNVERIFIED_CONFIDENCE = 0.50           # skor "data tidak tersedia"
CONFIDENCE_BASE = 0.70                 # kedua gerbang keras terpenuhi
CONFIDENCE_VOLUME_BONUS = 0.15
CONFIDENCE_PRESSURE_BONUS = 0.10
CONFIDENCE_VOLATILITY_BONUS = 0.20     # volatilitas tinggi + arah harga cocok
# Volatilitas tinggi TANPA arah harga yang mendukung tidak memberi bonus:
# ambang justru naik ke 0,80, jadi sinyal seperti itu harus membuktikan diri
# lewat volume/tekanan beli yang lebih kuat (kalau tidak, ambang baru itu
# tidak pernah menyaring apa pun).
MAX_CONFIDENCE = 0.99
MAX_DIAGNOSTIC_CONFIDENCE = 0.40       # skor kandidat yang gagal gerbang
# Kebijakan saat konteks volume/harga tidak ada (API mati, pool < 7 hari):
# alert TETAP dikirim tetapi ditandai tidak terverifikasi pada pesan Telegram.
ALLOW_UNVERIFIED_ALERTS = True
# Event id memakai bucket 4 jam, jadi dua sinyal di dua sisi batas bucket bisa
# terkirim hanya berjarak menit. Jarak minimum per token+jenis(+arah) menutup
# celah duplikasi dalam 1 jam.
MIN_RESEND_SEC = 3600
# ⚡ EARLY DUMP (watchlist LP) sejak 2026-09-05: cron scan watchlist LP
# (Meteora + Robinhood LP) tiap ±15 menit dan pengingat "dust > 0,1% MC"
# dikirim ulang **tiap scan** selama masih di atas ambang — bukan hanya saat
# naik. Dedup memakai bucket 15 menit + cooldown 15 menit supaya run ganda
# dalam satu slot tidak mengirim dua pesan yang sama.
FAST_BUCKET_SEC = 15 * 60
EARLY_DUMP_RESEND_SEC = FAST_BUCKET_SEC
# 🔔 HIGH DROP (watchlist biasa Solana/Robinhood, permintaan user 2026-09-05):
# titik acuan alert bukan snapshot awal melainkan **hold % MC terbesar** yang
# pernah tercatat (titik high); dust % MC yang turun >= 50% dari titik high
# memicu alert Telegram.
HIGH_DROP_RATIO = 0.5
HIGH_DROP_KIND = "high_drop"
MAX_LAST_SENT = 8
MAX_REJECTED_SIGNALS = 8
ALERT_WINDOW_SEC = 4 * 3600
# The scheduled job targets 1 run/hour (since 2026-09-04; GitHub may delay).
# Toleransi tetap longgar supaya run yang telat tetap menemukan snapshot
# ~4 jam lalu, sementara snapshot terlalu muda/menua ditolak.
ALERT_WINDOW_MIN_SEC = ALERT_WINDOW_SEC - 15 * 60
ALERT_WINDOW_MAX_SEC = ALERT_WINDOW_SEC + 60 * 60
EVENT_BUCKET_SEC = ALERT_WINDOW_SEC

# Two compact anchors are persisted per token: the immutable initial snapshot
# and a rolling ~4-hour snapshot. Current analysis may temporarily include the
# union of addresses from both anchors so movements can be classified.
MAX_STORED_WALLETS = 300
# Union of two 300-wallet anchors plus room for newly observed wallets.
MAX_COMPARISON_WALLETS = 800
MAX_SENT_EVENT_IDS = 96
BALANCE_EPSILON = 1e-12
STATE_KEY = "alert_state"


def _float(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _int(value, default=0) -> int:
    number = _float(value, None)
    return int(number) if number is not None else int(default)


def _address(value) -> str:
    # Wallet/mint addresses in this repository are Solana Base58 and therefore
    # case-sensitive. Whitespace is still never part of an address.
    return str(value or "").strip()


def build_wallet_snapshot(holders: Iterable[dict] | None, *,
                          dust_pct_mc=None, dust_limit_usd: float = 10.0,
                          tracked_addresses=None, ts: int | None = None,
                          max_wallets: int = MAX_COMPARISON_WALLETS,
                          truncated: bool = False) -> dict:
    """Build the bounded balance payload needed by alert comparisons.

    Previously tracked addresses are included with balance zero when no longer
    present so a dust wallet that sold everything can be distinguished. New
    dust wallets and largest remaining wallets fill the bounded payload.
    """
    rows: dict[str, tuple[float, float]] = {}
    for raw in holders or []:
        if not isinstance(raw, dict) or not raw.get("is_wallet"):
            continue
        address = _address(raw.get("address"))
        balance = _float(raw.get("balance"), 0.0) or 0.0
        usd_value = _float(raw.get("usd_value"), 0.0) or 0.0
        if not address or balance <= 0:
            continue
        # Holder fetchers already deduplicate owners. max() is a safe guard
        # against malformed duplicate rows without inflating token balances.
        old = rows.get(address)
        if old is None or balance > old[0]:
            rows[address] = (balance, usd_value)

    dust_limit = max(0.0, _float(dust_limit_usd, 10.0) or 10.0)
    current_dust = {
        address for address, (_balance, usd) in rows.items()
        if 0 < usd <= dust_limit
    }
    tracked = []
    tracked_seen = set()
    for raw in tracked_addresses or []:
        address = _address(raw)
        if address and address not in tracked_seen:
            tracked.append(address)
            tracked_seen.add(address)

    limit = max(1, min(_int(max_wallets, MAX_COMPARISON_WALLETS),
                       MAX_COMPARISON_WALLETS))
    # Priority: retain old addresses for movement comparison, then reserve
    # roughly half of the remaining room for current dust and use the rest for
    # largest balances. This keeps new wallets observable even when two old
    # anchors together contain hundreds of different addresses.
    tracked = tracked[:limit]
    room = max(0, limit - len(tracked))
    dust_ranked = sorted(current_dust, key=lambda address: (
        -rows[address][1], address))
    priority = list(tracked)
    priority += dust_ranked[:max(1, room // 2)] if room else []
    priority += sorted(rows, key=lambda address: (-rows[address][0], address))
    priority += dust_ranked

    selected: list[str] = []
    selected_set: set[str] = set()
    for address in priority:
        if address in selected_set:
            continue
        selected.append(address)
        selected_set.add(address)
        if len(selected) >= limit:
            break

    balances = {
        address: rows.get(address, (0.0, 0.0))[0]
        for address in selected
    }
    return {
        "ts": _int(ts or time.time()),
        "dust_pct_mc": _float(dust_pct_mc, None),
        "balances": balances,
        "dust": sorted(address for address in selected_set
                       if address in current_dust),
        "wallets_seen": len(rows),
        "truncated": bool(truncated),
    }


def _snapshot_balances(snapshot: dict | None) -> dict[str, float]:
    balances = {}
    for raw_address, raw_balance in ((snapshot or {}).get("balances") or {}).items():
        address = _address(raw_address)
        balance = _float(raw_balance, None)
        if address and balance is not None and balance >= 0:
            balances[address] = balance
    return balances


def compact_wallet_snapshot(snapshot: dict | None,
                            max_wallets: int = MAX_STORED_WALLETS) -> dict:
    """Bound an alert anchor while retaining both dust and large wallets."""
    snapshot = snapshot or {}
    balances = _snapshot_balances(snapshot)
    # Zeros are useful only in the transient current comparison; persisting
    # them would make a missing wallet look like a real historical holder.
    balances = {address: value for address, value in balances.items()
                if value > BALANCE_EPSILON}
    dust = {address for address in (snapshot.get("dust") or [])
            if address in balances}
    limit = max(1, min(_int(max_wallets, MAX_STORED_WALLETS),
                       MAX_STORED_WALLETS))
    dust_quota = max(1, limit // 2)
    # ``dust`` diurut sekali (sebelumnya dua kali dengan key yang sama).
    dust_ranked = sorted(dust, key=lambda address: (-balances[address], address))
    priority = dust_ranked[:dust_quota]
    priority += sorted(balances, key=lambda address: (-balances[address], address))
    priority += dust_ranked

    selected = []
    seen = set()
    for address in priority:
        if address in seen:
            continue
        selected.append(address)
        seen.add(address)
        if len(selected) >= limit:
            break
    return {
        "ts": _int(snapshot.get("ts")),
        "dust_pct_mc": _float(snapshot.get("dust_pct_mc"), None),
        "balances": {address: balances[address] for address in selected},
        "dust": sorted(address for address in selected if address in dust),
        "wallets_seen": max(0, _int(snapshot.get("wallets_seen"), len(balances))),
        "truncated": bool(snapshot.get("truncated")),
    }


def tracked_wallet_addresses(state: dict | None) -> list[str]:
    """Addresses needed to compare current balances to both saved anchors."""
    out = []
    seen = set()
    for name in ("baseline", "rolling"):
        for address in _snapshot_balances((state or {}).get(name)):
            if address not in seen:
                out.append(address)
                seen.add(address)
            if len(out) >= MAX_COMPARISON_WALLETS:
                return out
    return out


def wallet_movements(previous: dict | None, current: dict | None) -> dict:
    """Summarize balance changes and movement into/out of the dust group."""
    before = _snapshot_balances(previous)
    after = _snapshot_balances(current)
    previous_dust = {_address(a) for a in ((previous or {}).get("dust") or [])
                     if _address(a)}
    current_dust = {_address(a) for a in ((current or {}).get("dust") or [])
                    if _address(a)}

    common = set(before) & set(after)
    increased = {
        address for address in common
        if before[address] > BALANCE_EPSILON
        and after[address] > before[address] + BALANCE_EPSILON
    }
    decreased = {
        address for address in common
        if after[address] + BALANCE_EPSILON < before[address]
    }
    new_wallets = {
        address for address, balance in after.items()
        if balance > BALANCE_EPSILON and address not in before
    }

    exited = previous_dust - current_dust
    dust_grew_out = {
        address for address in exited
        if after.get(address, 0.0) > before.get(address, 0.0) + BALANCE_EPSILON
    }
    dust_sold_out = {
        address for address in exited
        if after.get(address, 0.0) <= BALANCE_EPSILON
    }
    dust_left_other = exited - dust_grew_out - dust_sold_out

    entered = current_dust - previous_dust
    larger_shrank_into_dust = {
        address for address in entered
        if address in before
        and after.get(address, 0.0) + BALANCE_EPSILON < before[address]
    }
    new_dust = {address for address in entered if address not in before}
    dust_entered_other = entered - larger_shrank_into_dust - new_dust

    return {
        "increased": len(increased),
        "decreased": len(decreased),
        "new_wallets": len(new_wallets),
        "dust_grew_out": len(dust_grew_out),
        "dust_sold_out": len(dust_sold_out),
        "dust_left_other": len(dust_left_other),
        "larger_shrank_into_dust": len(larger_shrank_into_dust),
        "new_dust": len(new_dust),
        "dust_entered_other": len(dust_entered_other),
        "compared_wallets": len(common),
    }


def is_valid_4h_snapshot(previous: dict | None, current: dict | None) -> bool:
    """Whether *previous* is close enough to four hours before *current*."""
    age = _int((current or {}).get("ts")) - _int((previous or {}).get("ts"))
    return ALERT_WINDOW_MIN_SEC <= age <= ALERT_WINDOW_MAX_SEC


def _event_id(mint: str, kind: str, current_ts: int,
              direction: str = "", *, bucket_sec: int = EVENT_BUCKET_SEC) -> str:
    bucket = max(0, _int(current_ts)) // max(1, int(bucket_sec))
    suffix = f":{direction}" if direction else ""
    return f"holder-dust:{_address(mint)}:{kind}:{bucket}{suffix}"


def _event(kind: str, previous: dict, current: dict, *, mint: str,
           symbol: str, scope: str, movement: dict | None = None,
           volume_check: dict | None = None) -> dict:
    """Satu event alert.

    ``movement`` boleh dihitung sekali oleh pemanggil (satu snapshot bisa
    memicu dump **dan** baseline shift, dan ``wallet_movements`` berjalan di
    atas ratusan address). ``volume_check`` adalah verdict konfirmasi volume.
    """
    old = _float(previous.get("dust_pct_mc"), 0.0) or 0.0
    new = _float(current.get("dust_pct_mc"), 0.0) or 0.0
    change = new - old
    movement = (movement if isinstance(movement, dict)
                else wallet_movements(previous, current))
    direction = "up" if change >= 0 else "down"
    event = {
        "id": _event_id(mint, kind, _int(current.get("ts")),
                        direction if kind == "baseline_shift" else ""),
        "kind": kind,
        "scope": scope,
        "direction": direction,
        "mint": _address(mint),
        "symbol": str(symbol or "?").strip().upper() or "?",
        "previous_dust_pct_mc": old,
        "current_dust_pct_mc": new,
        "change_pp": change,
        "previous_ts": _int(previous.get("ts")),
        "current_ts": _int(current.get("ts")),
        "wallet_increases": _int(movement.get("increased"), 0),
        "movements": movement,
    }
    if isinstance(volume_check, dict):
        event["volume_check"] = volume_check
    return event


def dedup_key(event: dict | None) -> str:
    """Kunci dedup 1 jam: jenis event, plus arah hanya untuk baseline_shift.

    Mengikuti bentuk ``_event_id``: dump dan akumulasi sudah searah dengan
    tanda perubahan dust, sedangkan baseline_shift naik dan turun adalah dua
    kabar yang berbeda dan tidak boleh saling membungkam.
    """
    kind = str((event or {}).get("kind") or "")
    direction = str((event or {}).get("direction") or "")
    if kind == "baseline_shift" and direction:
        return f"{kind}:{direction}"
    return kind


def in_resend_cooldown(key: str, current_ts: int, last_sent=None, *,
                       min_resend_sec: int = MIN_RESEND_SEC) -> bool:
    """True bila kunci itu sudah dikirim kurang dari ``min_resend_sec`` lalu.

    Event id memakai bucket (4 jam untuk rule lama, 15 menit untuk pengingat
    LP), jadi dua sinyal di dua sisi batas bucket bisa terkirim hanya
    berjarak beberapa menit. Lapisan ini menutup celah duplikasi dalam satu
    interval tanpa mengubah granularitas bucket.
    """
    previous = _int((last_sent or {}).get(key), 0)
    if not previous:
        return False
    age = _int(current_ts) - previous
    return 0 <= age < min_resend_sec


def _cooldown_reason(key: str, current_ts: int, last_sent=None,
                     min_resend_sec: int = MIN_RESEND_SEC) -> str:
    """Alasan penahanan duplikat, lengkap dengan jeda yang sudah berjalan."""
    age = max(0, _int(current_ts) - _int((last_sent or {}).get(key), 0))
    return (f"alert {key} baru dikirim {age // 60} menit lalu "
            f"(jeda minimum {min_resend_sec // 60} menit)")


def _resolve_context(context_provider, mint: str):
    """Ambil konteks pasar lewat provider lazy; kegagalan tidak boleh melempar."""
    if not callable(context_provider):
        return None
    try:
        context = context_provider(mint)
    except Exception as exc:  # noqa: BLE001 - pasar tidak boleh mematikan aturan
        print(f"WARN: konteks volume {_address(mint)[:8]} gagal diambil: {exc}",
              file=sys.stderr)
        return None
    return context if isinstance(context, dict) else None


def _note_rejection(rejected, event: dict, verdict: dict, *, cooldown=False):
    """Catat + log kandidat sinyal yang tidak dikirim (audit false positive)."""
    record = {
        "ts": _int(event.get("current_ts")),
        "kind": str(event.get("kind") or ""),
        "change_pp": round(_float(event.get("change_pp"), 0.0) or 0.0, 4),
        "cooldown": bool(cooldown),
        "verified": bool(verdict.get("verified")),
        "confidence_score": _float(verdict.get("confidence_score"), 0.0),
        "required_confidence": _float(verdict.get("required_confidence"),
                                      MIN_CONFIDENCE),
        "reason": str(verdict.get("reason") or ""),
    }
    if isinstance(rejected, list):
        rejected.append(record)
    label = "suppressed (cooldown)" if cooldown else "rejected"
    print(f"Dust signal {label} {event.get('symbol') or '?'} "
          f"{record['kind']} {record['change_pp']:+.2f}pp - {record['reason']}",
          file=sys.stderr)


class VolumeValidation(NamedTuple):
    """Hasil validasi volume/harga untuk satu kandidat sinyal dust.

    Tiga field pertama adalah kontrak pemanggil (``is_valid``,
    ``confidence_score``, ``reason``) sehingga hasilnya bisa dibaca sebagai
    atribut (``check.is_valid``) maupun di-unpack (``check[:3]``). ``verified``
    False berarti konteks pasarnya tidak tersedia — lihat
    :data:`ALLOW_UNVERIFIED_ALERTS`; ``details`` memuat angka pembanding untuk
    log dan pesan Telegram.
    """

    is_valid: bool
    confidence_score: float
    reason: str
    verified: bool = True
    details: dict | None = None


def _clamp01(value) -> float:
    number = _float(value, 0.0) or 0.0
    return max(0.0, min(1.0, number))


def _is_accumulation(kind) -> bool:
    return str(kind or "").strip().lower().startswith("accum")


def is_high_volatility(volatility) -> bool:
    """True bila stddev close 4 jam melewati ambang pasar liar (default 3%).

    Metriknya dihitung :func:`holder_history.calculate_volatility_metrics`;
    di sini hanya dibaca supaya ``telegram_alerts`` tidak bergantung jaringan.
    """
    if not isinstance(volatility, dict) or not volatility.get("available"):
        return False
    flag = volatility.get("high_volatility")
    if flag is not None:
        return bool(flag)
    stddev = _float(volatility.get("price_stddev_4h"), None)
    threshold = _float(volatility.get("high_volatility_pct"), None)
    return bool(stddev is not None and threshold is not None
                and stddev > threshold)


def required_confidence(volatility=None) -> float:
    """Ambang skor konfirmasi: 0,80 saat pasar liar, selain itu 0,70."""
    return (MIN_CONFIDENCE_HIGH_VOLATILITY if is_high_volatility(volatility)
            else MIN_CONFIDENCE)


# TODO(alerts): guard "re-klasifikasi harga" untuk kandidat dump. dust % MC
# memakai cutoff **$10 per wallet dalam USD**, jadi saat harga TURUN banyak
# wallet jatuh ke tier dust dan dust % MC naik tanpa ada yang jual — efek harga
# saja bisa ±0,4-0,5 pp, sudah melewati ambang dump 0,25 pp, dan gerbang
# volume/harga di bawah justru LOLOS saat harga turun (kasus AGENTHQ
# 2026-09-03, arah sebaliknya: harga +74% membuat dust % MC turun 1,16% → 0,7%).
# Keputusan user: **annotate, bukan reject** — alert tetap dikirim dengan baris
# "⚠️ kemungkinan efek re-klasifikasi harga" dan skor dipotong, bila dust % MC
# naik tetapi ``dust_count`` / pangsa supply dust tidak naik. Prasyarat:
# ``dust_pct_supply`` harus terisi untuk sumber Helius — DAS tidak mengembalikan
# ``amount_percentage`` sehingga ``holder_analysis`` meng-hardcode 0.0; alternatif
# sementara adalah membandingkan ``dust_count`` dua titik history terakhir.
def validate_alert_with_volume(dust_change_pp, current_volume_4h,
                               avg_volume_7d, current_price, price_change_pct,
                               *, kind: str = "dump", buy_pressure=None,
                               sell_pressure=None,
                               volatility=None) -> VolumeValidation:
    """Konfirmasi satu kandidat sinyal dust dengan volume + harga + volatilitas.

    Gerbang keras (harus dua-duanya terpenuhi):

    - **dump**         : ``volume_4h >= avg_volume_7d * 2.0`` **dan**
      ``price_change_pct <= -1.0`` (dust naik harus disertai tekanan jual).
    - **akumulasi**    : ``volume_4h >= avg_volume_7d * 1.5`` **dan**
      ``buy_pressure > sell_pressure``.

    ``avg_volume_7d`` = rata-rata volume **per window 4 jam** selama 7 hari,
    jadi satuannya setara dengan ``current_volume_4h``.

    Skor konfirmasi (0..1) hanya dihitung bila gerbang lolos:
    ``0,70`` dasar + hingga ``0,15`` kekuatan volume (penuh pada 2× ambang)
    + hingga ``0,10`` kekuatan harga/tekanan beli + ``0,20`` bila volatilitas
    4 jam > 3% **dan** arah harga mendukung (tanpa dukungan arah tidak ada
    bonus, karena ambangnya justru naik). Kandidat yang gagal gerbang mendapat
    skor diagnostik ≤ 0,40 agar tetap informatif di log tanpa pernah lolos
    ambang. Contoh: gerbang tepat terpenuhi + stddev 4 jam 4,2% → 0,90
    (ambang 0,80); gerbang tepat terpenuhi tanpa volatilitas → 0,70.

    Ambang lolos: :func:`required_confidence` → 0,80 saat volatilitas tinggi,
    0,70 selain itu.

    Data hilang (``volume_4h`` None/negatif, ``avg_volume_7d`` None/0 — pool
    lebih muda dari 7 hari, atau sumber mati — maupun harga/tekanan beli yang
    tidak ada) menghasilkan ``verified=False``: fungsi ini **tidak** memblokir
    alert karena ketidaktahuan, dan pemanggil (lihat :func:`volume_verdict`)
    yang memutuskan kebijakan — default repo: tetap kirim, tandai.
    """
    accumulation = _is_accumulation(kind)
    required_ratio = (ACCUMULATION_VOLUME_MULTIPLE if accumulation
                      else DUMP_VOLUME_MULTIPLE)
    dust_pp = _float(dust_change_pp, 0.0) or 0.0
    volume = _float(current_volume_4h, None)
    baseline = _float(avg_volume_7d, None)
    price = _float(current_price, None)
    change = _float(price_change_pct, None)
    buys = _float(buy_pressure, None)
    sells = _float(sell_pressure, None)
    vol_metrics = volatility if isinstance(volatility, dict) else {}
    stddev = _float(vol_metrics.get("price_stddev_4h"), None)

    missing = []
    if volume is None or volume < 0:
        missing.append("volume_4h")
    if baseline is None or baseline <= 0:
        # Rata-rata 7 hari nol/absen = pool terlalu baru atau sumber mati.
        # Rasio tidak terdefinisi → diperlakukan sebagai data hilang, bukan
        # "volume tak terbatas" yang akan meloloskan sinyal apa pun.
        missing.append("avg_volume_7d")
    if accumulation and (buys is None or sells is None):
        missing.append("buy/sell_pressure")
    if not accumulation and change is None:
        missing.append("price_change_pct")

    details = {
        "kind": "accumulation" if accumulation else "dump",
        "dust_change_pp": round(dust_pp, 4),
        "volume_4h": volume,
        "avg_volume_7d": baseline,
        "volume_ratio": (round(volume / baseline, 4)
                         if volume is not None and baseline else None),
        "required_ratio": required_ratio,
        "price": price,
        "price_change_pct": change,
        "buy_pressure": buys,
        "sell_pressure": sells,
        "price_stddev_4h": stddev,
        "high_volatility": is_high_volatility(vol_metrics),
        "required_confidence": required_confidence(vol_metrics),
        "missing": missing,
    }
    if missing:
        return VolumeValidation(
            True, UNVERIFIED_CONFIDENCE,
            "data pasar tidak tersedia (" + ", ".join(missing)
            + ") — sinyal dikirim tanpa verifikasi volume",
            False, details)

    ratio = volume / baseline if baseline > 0 else 0.0
    volume_ok = ratio + BALANCE_EPSILON >= required_ratio
    if accumulation:
        confirm_ok = bool(buys > sells)
        confirm_text = f"buy {buys:.0f} > sell {sells:.0f}"
    else:
        confirm_ok = bool(change <= DUMP_PRICE_CHANGE_PCT + BALANCE_EPSILON)
        confirm_text = f"harga {change:+.2f}%"
    is_valid = bool(volume_ok and confirm_ok)

    volume_progress = _clamp01(
        (ratio / required_ratio - 1.0) / max(1e-9, VOLUME_FULL_BONUS_RATIO - 1.0)
    ) if required_ratio > 0 else 0.0
    if accumulation:
        if sells > 0:
            pressure_ratio = buys / sells
        else:
            pressure_ratio = ACCUMULATION_PRESSURE_FULL_RATIO if buys > 0 else 0.0
        confirm_progress = _clamp01(
            (pressure_ratio - 1.0)
            / max(1e-9, ACCUMULATION_PRESSURE_FULL_RATIO - 1.0))
        details["pressure_ratio"] = round(pressure_ratio, 4)
    else:
        span = abs(DUMP_PRICE_FULL_BONUS_PCT) - abs(DUMP_PRICE_CHANGE_PCT)
        confirm_progress = (_clamp01((abs(change) - abs(DUMP_PRICE_CHANGE_PCT)) / span)
                            if span > 0 and change <= 0 else 0.0)

    volatility_bonus = 0.0
    if is_high_volatility(vol_metrics):
        direction_ok = ((change >= 0) if accumulation
                        else (change <= DUMP_PRICE_CHANGE_PCT))
        if direction_ok:
            volatility_bonus = CONFIDENCE_VOLATILITY_BONUS

    details.update({"volume_ok": volume_ok, "confirm_ok": confirm_ok,
                    "volume_progress": round(volume_progress, 4),
                    "confirm_progress": round(confirm_progress, 4),
                    "volatility_bonus": volatility_bonus})

    if is_valid:
        confidence = min(MAX_CONFIDENCE,
                         CONFIDENCE_BASE
                         + CONFIDENCE_VOLUME_BONUS * volume_progress
                         + CONFIDENCE_PRESSURE_BONUS * confirm_progress
                         + volatility_bonus)
        reason = (f"volume 4 jam {ratio:.2f}x rata-rata 7d "
                  f"(ambang {required_ratio:.1f}x) & {confirm_text}")
        if volatility_bonus:
            reason += f"; stddev 4 jam {stddev:.2f}% menguatkan"
    else:
        confidence = MAX_DIAGNOSTIC_CONFIDENCE * (
            0.5 * _clamp01(ratio / required_ratio if required_ratio else 0.0)
            + 0.5 * confirm_progress)
        failed = []
        if not volume_ok:
            failed.append(f"volume 4 jam {ratio:.2f}x rata-rata 7d "
                          f"< {required_ratio:.1f}x")
        if not confirm_ok:
            if accumulation:
                failed.append(f"buy {buys:.0f} <= sell {sells:.0f} "
                              "(tekanan beli belum dominan)")
            else:
                failed.append(f"harga {change:+.2f}% > "
                              f"{DUMP_PRICE_CHANGE_PCT:.1f}% "
                              "(belum ada tekanan jual)")
        reason = "; ".join(failed) or "gerbang konfirmasi tidak terpenuhi"
    details["confidence_score"] = round(confidence, 4)
    return VolumeValidation(is_valid, round(confidence, 4), reason, True,
                            details)


def volume_verdict(kind: str, dust_change_pp, context=None) -> dict:
    """Terapkan kebijakan repo atas :func:`validate_alert_with_volume`.

    ``context`` adalah dict dari ``alert_context.build_market_context`` (boleh
    ``None``/kosong). Return dict ``allow``/``verified``/``is_valid``/
    ``confidence_score``/``required_confidence``/``reason`` + angka pembanding,
    siap ditempel ke event alert dan ke log cron.

    Kebijakan data hilang (:data:`ALLOW_UNVERIFIED_ALERTS` = True): alert tetap
    dikirim dengan tanda "tidak terverifikasi" — dump tidak boleh hilang hanya
    karena GeckoTerminal/DexScreener sedang tidak bisa diambil.
    """
    ctx = context if isinstance(context, dict) else {}
    volatility = ctx.get("volatility") if isinstance(ctx.get("volatility"),
                                                     dict) else None
    check = validate_alert_with_volume(
        dust_change_pp, ctx.get("volume_4h"), ctx.get("avg_volume_7d"),
        ctx.get("price"), ctx.get("price_change_pct"), kind=kind,
        buy_pressure=ctx.get("buy_pressure"),
        sell_pressure=ctx.get("sell_pressure"), volatility=volatility)
    required = required_confidence(volatility)
    verified = bool(check.verified and ctx.get("available", True))
    if verified:
        allow = bool(check.is_valid and check.confidence_score >= required)
        confidence = check.confidence_score
        reason = check.reason
    else:
        allow = bool(ALLOW_UNVERIFIED_ALERTS)
        confidence = UNVERIFIED_CONFIDENCE
        reason = (check.reason if not check.verified else
                  str(ctx.get("reason") or "konteks volume/harga tidak tersedia")
                  + " — sinyal dikirim tanpa verifikasi")
    verdict = dict(check.details or {})
    verdict.update({
        "kind": check.details.get("kind") if check.details else kind,
        "allow": allow,
        "verified": verified,
        "is_valid": bool(check.is_valid),
        "confidence_score": round(confidence, 4),
        "required_confidence": required,
        "reason": reason,
        "volume_source": str(ctx.get("volume_source") or ""),
        "price_change_window": str(ctx.get("price_change_window") or ""),
        "candles": _int(ctx.get("candles"), 0),
    })
    return verdict


def evaluate_4h_rules(previous: dict | None, current: dict | None, *,
                      mint: str, symbol: str = "?", sent_event_ids=(),
                      market_context=None, context_provider=None,
                      rejected=None, last_sent=None) -> list[dict]:
    """Evaluate dump/accumulation rules against one valid ~4-hour anchor.

    Ambang dust (dump +0,25 pp / akumulasi -0,50 pp dengan buyer) hanya
    menghasilkan **kandidat**. Setiap kandidat lalu dikonfirmasi volume +
    harga + volatilitas lewat :func:`volume_verdict`; yang gagal dicatat ke
    ``rejected`` (list keluaran) dan di-log, bukan dikirim.

    ``market_context`` adalah dict konteks yang sudah jadi. Bila ``None`` dan
    ``context_provider`` tersedia, provider dipanggil **hanya setelah ada
    kandidat** (lazy) — maksimal satu kali per evaluasi. ``last_sent``
    (``{kunci: ts}`` dari alert state) menahan duplikat dalam 1 jam.
    """
    if not is_valid_4h_snapshot(previous, current):
        return []
    old = _float((previous or {}).get("dust_pct_mc"), None)
    new = _float((current or {}).get("dust_pct_mc"), None)
    if old is None or new is None:
        return []
    change = new - old
    movement = wallet_movements(previous, current)
    current_ts = _int((current or {}).get("ts"))

    candidates = []
    if change + BALANCE_EPSILON >= DUMP_THRESHOLD_PP:
        candidates.append("dump")
    if (-change + BALANCE_EPSILON >= ACCUMULATION_THRESHOLD_PP
            and _int(movement.get("increased")) > 0):
        candidates.append("accumulation")

    sent = set(sent_event_ids or [])
    context = market_context if isinstance(market_context, dict) else None
    resolved = context is not None
    events = []
    for kind in candidates:
        event = _event(kind, previous, current, mint=mint, symbol=symbol,
                       scope="~4 jam", movement=movement)
        if event["id"] in sent:
            continue
        key = dedup_key(event)
        if in_resend_cooldown(key, current_ts, last_sent):
            _note_rejection(rejected, event, {
                "verified": True, "confidence_score": 0.0,
                "required_confidence": MIN_CONFIDENCE,
                "reason": _cooldown_reason(key, current_ts, last_sent)},
                cooldown=True)
            continue
        if not resolved:
            context = _resolve_context(context_provider, mint)
            resolved = True
        verdict = volume_verdict(kind, change, context)
        event["volume_check"] = verdict
        if verdict.get("allow"):
            events.append(event)
        else:
            _note_rejection(rejected, event, verdict)
    return events


def evaluate_baseline_rule(baseline: dict | None, current: dict | None, *,
                           mint: str, symbol: str = "?", sent_event_ids=(),
                           market_context=None, context_provider=None,
                           rejected=None, last_sent=None) -> list[dict]:
    """Alert when dust moved at least ±1 point from the initial snapshot.

    Konfirmasi volume/harga memakai window 4 jam terakhir (window terdekat
    yang tersedia): dust naik divalidasi sebagai **dump** (volume ≥ 2× dan
    harga ≤ -1%), dust turun sebagai **akumulasi** (volume ≥ 1,5× dan
    buy > sell). ``event["kind"]`` tetap ``baseline_shift``.
    """
    old = _float((baseline or {}).get("dust_pct_mc"), None)
    new = _float((current or {}).get("dust_pct_mc"), None)
    if old is None or new is None:
        return []
    change = new - old
    if abs(change) + BALANCE_EPSILON < BASELINE_SHIFT_THRESHOLD_PP:
        return []
    movement = wallet_movements(baseline, current)
    event = _event("baseline_shift", baseline, current, mint=mint,
                   symbol=symbol, scope="sejak snapshot awal",
                   movement=movement)
    if event["id"] in set(sent_event_ids or []):
        return []
    current_ts = _int((current or {}).get("ts"))
    key = dedup_key(event)
    if in_resend_cooldown(key, current_ts, last_sent):
        _note_rejection(rejected, event, {
            "verified": True, "confidence_score": 0.0,
            "required_confidence": MIN_CONFIDENCE,
            "reason": _cooldown_reason(key, current_ts, last_sent)},
            cooldown=True)
        return []
    context = market_context if isinstance(market_context, dict) else \
        _resolve_context(context_provider, mint)
    kind = "dump" if change >= 0 else "accumulation"
    verdict = volume_verdict(kind, change, context)
    verdict["event_kind"] = "baseline_shift"
    event["volume_check"] = verdict
    if not verdict.get("allow"):
        _note_rejection(rejected, event, verdict)
        return []
    return [event]


def _early_dump_event(previous: dict, current: dict, *, mint: str,
                      symbol: str, scope: str) -> dict:
    """Satu event ⚡ EARLY DUMP (tanpa peta wallet/movement).

    Marker ``previous`` hanya membawa ``ts`` + ``dust_pct_mc`` (bukan
    snapshot wallet), jadi event ini sengaja tidak memakai :func:`_event`
    yang menghitung ``wallet_movements`` di atas ratusan address. Bidang
    ``movements`` dikosongkan dan pesan early dump tidak menampilkan blok
    pergerakan wallet. Event id memakai **bucket 15 menit**
    (:data:`FAST_BUCKET_SEC`) karena pengingat dikirim ulang tiap scan LP.
    """
    current_ts = _int((current or {}).get("ts"))
    old = _float((previous or {}).get("dust_pct_mc"), 0.0) or 0.0
    new = _float((current or {}).get("dust_pct_mc"), 0.0) or 0.0
    return {
        "id": _event_id(mint, "early_dump", current_ts,
                        bucket_sec=FAST_BUCKET_SEC),
        "kind": "early_dump",
        "scope": scope,
        "direction": "up",
        "mint": _address(mint),
        "symbol": str(symbol or "?").strip().upper() or "?",
        "previous_dust_pct_mc": old,
        "current_dust_pct_mc": new,
        "change_pp": round(new - old, 6),
        "previous_ts": _int((previous or {}).get("ts")),
        "current_ts": current_ts,
        "wallet_increases": 0,
        "movements": {},
        # Pool address tidak disimpan di watchlist.json; pemanggil cron belum
        # bisa mengisinya (keterbatasan terdokumentasi). Field ini disiapkan
        # supaya pesan bisa memuat 🌊 Meteora + 🦅 HawkFi bila suatu saat
        # sumber pool address tersedia (mis. hasil scan_meteora).
        "pool_addresses": [str(p or "").strip()
                           for p in (current.get("pool_addresses") or []) if p],
    }


def early_dump_verdict(context=None, kind: str = "early_dump") -> dict:
    """Verdict **info saja** tanpa gerbang keras (early_dump / high_drop).

    Rule dump/akumulasi/baseline (delta 0,25/0,50/1,00 pp) memakai
    :func:`volume_verdict` sebagai gerbang konfirmasi. Crossing/pengingat
    ambang absolut 0,1% MC dan penurunan dari titik high bisa terjadi dengan
    delta jauh lebih kecil dari 0,25 pp, jadi gerbang itu tidak bisa dipakai
    apa adanya. Keputusan user (2026-09-04): early warning dikirim **tanpa**
    gerbang volume supaya bisa exit LP lebih cepat; volume/harga/volatilitas
    tetap disertakan sebagai konteks pesan, dan ``verified`` False (data
    pasar hilang) membuat pesan memuat baris ``⚠️ TIDAK TERVERIFIKASI``.
    ``allow`` selalu True.
    """
    ctx = context if isinstance(context, dict) else {}
    volatility = ctx.get("volatility") if isinstance(ctx.get("volatility"),
                                                     dict) else None
    volume = _float(ctx.get("volume_4h"), None)
    baseline = _float(ctx.get("avg_volume_7d"), None)
    change = _float(ctx.get("price_change_pct"), None)
    buys = _float(ctx.get("buy_pressure"), None)
    sells = _float(ctx.get("sell_pressure"), None)
    stddev = _float((volatility or {}).get("price_stddev_4h"), None)
    has_data = any(value is not None for value in
                   (volume, baseline, change, buys, sells, stddev))
    verified = bool(ctx.get("available", True) and has_data)
    return {
        "kind": kind,
        "allow": True,
        "verified": verified,
        "is_valid": True,
        "confidence_score": 0.0,
        "required_confidence": 0.0,
        "reason": ("" if verified else str(ctx.get("reason")
                                           or "data pasar tidak tersedia")),
        "volume_4h": volume,
        "avg_volume_7d": baseline,
        "volume_ratio": (round(volume / baseline, 4)
                         if volume is not None and baseline else None),
        "price": _float(ctx.get("price"), None),
        "price_change_pct": change,
        "buy_pressure": buys,
        "sell_pressure": sells,
        "price_stddev_4h": stddev,
        "high_volatility": is_high_volatility(volatility),
        "volume_source": str(ctx.get("volume_source") or ""),
        "price_change_window": str(ctx.get("price_change_window") or ""),
        "candles": _int(ctx.get("candles"), 0),
    }


def evaluate_early_dump_rule(previous: dict | None, current: dict | None, *,
                             mint: str, symbol: str = "?",
                             sent_event_ids=(), market_context=None,
                             context_provider=None, rejected=None,
                             last_sent=None) -> list[dict]:
    """⚡ EARLY DUMP: dust pool LP **masih di atas** 0,1% MC → pengingat tiap scan.

    Sejak 2026-09-05 (permintaan user, scan watchlist LP tiap ±15 menit) rule
    ini berubah dari *crossing-based* menjadi **level-based**: selama
    ``dust_pct_mc`` di atas :data:`holder_history.DUST_BEST_PCT` (0,1%),
    SETIAP evaluasi menghasilkan event — naik, turun sedikit, atau hover di
    nilai yang sama. Pengingat berhenti hanya bila:

    - dust kembali ``<= 0,1%`` MC (reset otomatis, tanpa notifikasi turun),
      atau
    - token dihapus dari watchlist LP / dipindah ke watchlist biasa (scope
      ``lp_mints`` di cron tidak lagi memuat token itu).

    Frekuensi tetap dibatasi: event id per **bucket 15 menit**
    (:data:`FAST_BUCKET_SEC`) + cooldown :data:`EARLY_DUMP_RESEND_SEC`, jadi
    run ganda dalam satu slot tidak mengirim pesan kembar. Rule lama (dump
    +0,25 pp dst dengan gerbang volume) tidak berubah dan tetap berjalan
    untuk token LP.

    Guard data: rule hanya dipanggil dengan ``dust_pct_mc`` yang valid
    (pemanggil melewati token ``total_fetched <= 0`` dan nilai None).
    Tanpa marker ``previous`` rule belum mengirim — cron selalu memajukan
    marker ``alert_state["early_dump"]`` tiap evaluasi, jadi token LP baru
    yang langsung > 0,1% MC mengirim pengingat pertama pada scan
    berikutnya (±15 menit) dan berulang setelahnya.
    """
    old = _float((previous or {}).get("dust_pct_mc"), None)
    new = _float((current or {}).get("dust_pct_mc"), None)
    if old is None or new is None:
        return []
    if new <= DUST_BEST_PCT:
        # Masih bersih / sudah turun lagi ke <= 0,1% = reset, bukan alert.
        return []
    had_marker = bool(previous) and old > 0
    if had_marker:
        scope = (f"masih di atas {DUST_BEST_PCT:g}% MC — pengingat berulang "
                 f"(scan ±{FAST_BUCKET_SEC // 60} menit)")
    else:
        scope = f"pertama kali terpantau di atas {DUST_BEST_PCT:g}% MC"
    current_ts = _int((current or {}).get("ts"))
    event = _early_dump_event(previous, current, mint=mint, symbol=symbol,
                              scope=scope)
    if event["id"] in set(sent_event_ids or []):
        return []
    key = dedup_key(event)
    if in_resend_cooldown(key, current_ts, last_sent,
                          min_resend_sec=EARLY_DUMP_RESEND_SEC):
        _note_rejection(rejected, event, {
            "verified": True, "confidence_score": 0.0,
            "required_confidence": MIN_CONFIDENCE,
            "reason": _cooldown_reason(key, current_ts, last_sent,
                                       min_resend_sec=EARLY_DUMP_RESEND_SEC)},
            cooldown=True)
        return []
    context = market_context if isinstance(market_context, dict) else \
        _resolve_context(context_provider, mint)
    event["volume_check"] = early_dump_verdict(context)
    return [event]


def high_drop_marker_next(marker: dict | None, current: dict,
                          emitted: bool) -> dict:
    """Majukan marker titik high (🔔 HIGH DROP) setelah satu evaluasi.

    Selalu dipanggil untuk token scope high (watchlist biasa), event dikirim
    atau tidak:

    - nilai sekarang >= high lama (atau marker kosong) → high baru, re-arm
      (``notified_high`` di-nol-kan);
    - nilai sekarang di luar zona drop tapi di bawah high → high
      dipertahankan; ``notified_high`` di-nol-kan bila nilai sudah keluar
      dari zona drop supaya penurunan berikutnya ke dalam zona bisa mengirim
      lagi;
    - event terkirim → ``notified_high`` = high ini (satu alert per titik
      high; naik ke high baru = titik high baru yang bisa mengirim lagi).
    """
    marker = marker if isinstance(marker, dict) else {}
    cur = _float(current.get("dust_pct_mc"), None)
    cur_ts = _int(current.get("ts"))
    high = _float(marker.get("high"), None)
    high_ts = _int(marker.get("high_ts"), 0)
    notified = _float(marker.get("notified_high"), 0.0) or 0.0
    if cur is None:
        return {"ts": _int(marker.get("ts"), 0), "high": high,
                "high_ts": high_ts, "notified_high": notified}
    if high is None or high <= 0 or cur >= high:
        return {"ts": cur_ts, "high": cur, "high_ts": cur_ts,
                "notified_high": 0.0}
    zone = high * (1.0 - HIGH_DROP_RATIO)
    if emitted:
        notified = high
    elif cur > zone:
        notified = 0.0
    return {"ts": cur_ts, "high": high,
            "high_ts": high_ts or _int(marker.get("ts"), 0),
            "notified_high": notified}


def evaluate_high_drop_rule(marker: dict | None, current: dict | None, *,
                            mint: str, symbol: str = "?",
                            sent_event_ids=(), market_context=None,
                            context_provider=None, rejected=None,
                            last_sent=None) -> list[dict]:
    """🔔 HIGH DROP: dust % MC turun >= 50% dari **titik high**-nya.

    Untuk watchlist **biasa** (selain Meteora/Robinhood LP), titik acuan
    alert bukan snapshot awal melainkan **hold % MC terbesar** yang pernah
    tercatat (permintaan user 2026-09-05). Bila dust % MC sekarang turun
    minimal :data:`HIGH_DROP_RATIO` (50%) dari titik high itu, kirim alert
    Telegram **tanpa gerbang volume keras** — konteks pasar info saja, pola
    yang sama dengan ⚡ EARLY DUMP (lihat :func:`early_dump_verdict`).

    - satu alert per titik high: ``notified_high`` menyimpan nilai high yang
      sudah pernah diberitahu (:func:`high_drop_marker_next`);
    - dedup bucket 4 jam + cooldown ``MIN_RESEND_SEC`` (1 jam) mencegah flap
      antar run;
    - token tanpa marker (belum pernah discan) tidak mengirim — high belum
      ada; marker dibangun :func:`high_drop_marker_next` pada evaluasi yang
      sama.
    """
    high = _float((marker or {}).get("high"), None)
    cur = _float((current or {}).get("dust_pct_mc"), None)
    if high is None or high <= 0 or cur is None or cur >= high:
        return []
    notified = _float((marker or {}).get("notified_high"), 0.0) or 0.0
    if notified and abs(notified - high) <= BALANCE_EPSILON:
        return []  # titik high ini sudah pernah diberitahu
    zone = high * (1.0 - HIGH_DROP_RATIO)
    if cur > zone:
        return []  # belum turun 50% dari high
    current_ts = _int((current or {}).get("ts"))
    high_ts = (_int((marker or {}).get("high_ts"), 0)
               or _int((marker or {}).get("ts"), 0))
    drop_pct = round((high - cur) / high * 100.0, 2)
    event = {
        "id": _event_id(mint, HIGH_DROP_KIND, current_ts),
        "kind": HIGH_DROP_KIND,
        "scope": f"dari titik high {high:.2f}% MC",
        "direction": "down",
        "mint": _address(mint),
        "symbol": str(symbol or "?").strip().upper() or "?",
        "previous_dust_pct_mc": high,
        "current_dust_pct_mc": cur,
        "change_pp": round(cur - high, 6),
        "drop_pct": drop_pct,
        "previous_ts": high_ts,
        "current_ts": current_ts,
        "wallet_increases": 0,
        "movements": {},
    }
    if event["id"] in set(sent_event_ids or []):
        return []
    key = dedup_key(event)
    if in_resend_cooldown(key, current_ts, last_sent):
        _note_rejection(rejected, event, {
            "verified": True, "confidence_score": 0.0,
            "required_confidence": MIN_CONFIDENCE,
            "reason": _cooldown_reason(key, current_ts, last_sent)},
            cooldown=True)
        return []
    context = market_context if isinstance(market_context, dict) else \
        _resolve_context(context_provider, mint)
    event["volume_check"] = early_dump_verdict(context, kind=HIGH_DROP_KIND)
    return [event]


def evaluate_alert_events(mint: str, analysis: dict,
                          state: dict | None = None, *,
                          market_context=None,
                          context_provider=None,
                          lp_mint: bool = False,
                          high_track: bool = False) -> tuple[list[dict], dict]:
    """Pure state transition: evaluate old anchors, then advance snapshots.

    ``market_context`` (dict siap pakai) atau ``context_provider(mint,
    analysis)`` memasok volume/harga/volatilitas untuk konfirmasi sinyal.
    Provider dipanggil **maksimal satu kali** per evaluasi dan hanya bila ada
    kandidat (lazy), jadi scan 1 jam yang tenang tidak menambah API call.
    Sinyal yang ditolak dikembalikan lewat ``next_state["rejected_signals"]``
    untuk audit. ``lp_mint=True`` (token pool Meteora/Chart LP atau watchlist
    Robinhood LP) mengaktifkan rule ``early_dump`` — pengingat berulang
    selama dust % MC > 0,1% — dan merekam marker
    ``next_state["early_dump"]``. ``high_track=True`` (watchlist biasa)
    mengaktifkan rule ``high_drop`` (turun ≥ 50% dari titik high) dengan
    marker ``next_state["high_drop"]`` (high = hold % MC terbesar).
    """
    state = dict(state or {})
    sent = list(dict.fromkeys(str(item) for item in
                              (state.get("sent_event_ids") or []) if item))
    last_sent = {str(key): _int(ts) for key, ts in
                 (state.get("last_sent") or {}).items()
                 if isinstance(state.get("last_sent"), dict)} \
        if isinstance(state.get("last_sent"), dict) else {}
    holders = (analysis or {}).get("holders") or {}
    raw_current = holders.get("wallet_snapshot") or {}
    current = dict(raw_current)
    current["ts"] = _int(current.get("ts")
                         or (analysis or {}).get("analyzed_at") or time.time())
    current["dust_pct_mc"] = _float(
        current.get("dust_pct_mc", holders.get("dust_pct_mc")), None)
    symbol = str((analysis or {}).get("symbol") or "?")

    previous_rejected = [row for row in (state.get("rejected_signals") or [])
                         if isinstance(row, dict)]
    raw_marker = state.get("early_dump")
    early_marker = dict(raw_marker) if isinstance(raw_marker, dict) else {}
    raw_high = state.get("high_drop")
    high_marker = dict(raw_high) if isinstance(raw_high, dict) else {}
    next_state = {
        "baseline": state.get("baseline") or {},
        "rolling": state.get("rolling") or {},
        "sent_event_ids": sent[-MAX_SENT_EVENT_IDS:],
        "last_sent": last_sent,
        "rejected_signals": previous_rejected[-MAX_REJECTED_SIGNALS:],
        "early_dump": early_marker,
        "high_drop": high_marker,
    }
    if current["dust_pct_mc"] is None:
        return [], next_state

    context = market_context if isinstance(market_context, dict) else None
    if context is None:
        embedded = (analysis or {}).get("market_context")
        context = embedded if isinstance(embedded, dict) else None

    shared: dict = {}

    def _lazy_context(_mint: str):
        """Provider yang sudah diikat ke *analysis* + memo satu kali per evaluasi."""
        if "ctx" not in shared:
            try:
                value = context_provider(mint, analysis)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: konteks volume {_address(mint)[:8]} gagal: {exc}",
                      file=sys.stderr)
                value = None
            shared["ctx"] = value if isinstance(value, dict) else None
        return shared["ctx"]

    lazy = _lazy_context if callable(context_provider) else None

    rejected: list[dict] = []
    events = []
    # ⚡ EARLY DUMP (scope pool Meteora/Chart LP + watchlist Robinhood LP):
    # pengingat level-based — selama dust % MC > 0,1%, setiap evaluasi
    # mengirim event (lihat evaluate_early_dump_rule). Marker selalu
    # dimajukan ke nilai run ini (nilai terakhir) — bahkan saat tidak ada
    # event. Token di luar scope tidak dievaluasi dan markernya dipertahankan
    # apa adanya.
    if lp_mint and current.get("dust_pct_mc") is not None:
        events.extend(evaluate_early_dump_rule(
            early_marker or None, current, mint=mint, symbol=symbol,
            sent_event_ids=sent, market_context=context,
            context_provider=lazy, rejected=rejected, last_sent=last_sent))
        next_state["early_dump"] = {
            "ts": current["ts"],
            "dust_pct_mc": current["dust_pct_mc"],
        }
    # 🔔 HIGH DROP (scope watchlist biasa Solana/Robinhood): titik acuan =
    # hold % MC terbesar yang pernah tercatat; turun >= 50% dari titik itu
    # mengirim alert. Marker (high + status notifikasi) selalu dimajukan.
    if high_track and current.get("dust_pct_mc") is not None:
        high_events = evaluate_high_drop_rule(
            high_marker or None, current, mint=mint, symbol=symbol,
            sent_event_ids=sent, market_context=context,
            context_provider=lazy, rejected=rejected, last_sent=last_sent)
        events.extend(high_events)
        next_state["high_drop"] = high_drop_marker_next(
            high_marker, current, emitted=bool(high_events))
    baseline = state.get("baseline") if isinstance(state.get("baseline"), dict) \
        else {}
    if baseline and baseline.get("dust_pct_mc") is not None:
        events.extend(evaluate_baseline_rule(
            baseline, current, mint=mint, symbol=symbol, sent_event_ids=sent,
            market_context=context, context_provider=lazy, rejected=rejected,
            last_sent=last_sent))
    else:
        next_state["baseline"] = compact_wallet_snapshot(current)

    rolling = state.get("rolling") if isinstance(state.get("rolling"), dict) \
        else {}
    if not rolling or rolling.get("dust_pct_mc") is None:
        next_state["rolling"] = compact_wallet_snapshot(current)
    else:
        age = current["ts"] - _int(rolling.get("ts"))
        if is_valid_4h_snapshot(rolling, current):
            events.extend(evaluate_4h_rules(
                rolling, current, mint=mint, symbol=symbol,
                sent_event_ids=sent, market_context=context,
                context_provider=lazy, rejected=rejected,
                last_sent=last_sent))
            next_state["rolling"] = compact_wallet_snapshot(current)
        elif age > ALERT_WINDOW_MAX_SEC or age < 0:
            # Stale/out-of-order anchors are unsafe for a four-hour rule.
            next_state["rolling"] = compact_wallet_snapshot(current)
        # A young anchor remains frozen until it reaches the valid window.

    if rejected:
        next_state["rejected_signals"] = (
            previous_rejected + rejected)[-MAX_REJECTED_SIGNALS:]
    # A dump and baseline-shift can coexist; each has a distinct event id.
    unique = {event["id"]: event for event in events}
    return list(unique.values()), next_state


def compact_alert_state(state: dict | None) -> dict:
    """Sanitize/bound state before persisting it in history/status JSON."""
    state = state or {}
    raw_last = state.get("last_sent") if isinstance(state.get("last_sent"),
                                                    dict) else {}
    last_sent = {str(key): _int(ts) for key, ts in raw_last.items() if _int(ts)}
    newest_first = sorted(last_sent.items(), key=lambda item: -item[1])
    raw_marker = state.get("early_dump")
    marker = dict(raw_marker) if isinstance(raw_marker, dict) else {}
    marker_ts = _int(marker.get("ts"))
    raw_high = state.get("high_drop")
    high_marker = dict(raw_high) if isinstance(raw_high, dict) else {}
    high_ts = _int(high_marker.get("ts"))
    return {
        "baseline": compact_wallet_snapshot(state.get("baseline")),
        "rolling": compact_wallet_snapshot(state.get("rolling")),
        "sent_event_ids": list(dict.fromkeys(
            str(item) for item in (state.get("sent_event_ids") or []) if item
        ))[-MAX_SENT_EVENT_IDS:],
        "last_sent": dict(newest_first[:MAX_LAST_SENT]),
        "rejected_signals": [row for row in (state.get("rejected_signals") or [])
                             if isinstance(row, dict)][-MAX_REJECTED_SIGNALS:],
        # Marker rule EARLY DUMP: ringkas (ts + dust % MC terakhir), tanpa
        # peta wallet — cukup untuk pengingat run berikutnya.
        "early_dump": ({"ts": marker_ts,
                        "dust_pct_mc": (_float(marker.get("dust_pct_mc"), None)
                                        if marker_ts else None)}
                       if marker_ts else {}),
        # Marker rule HIGH DROP: high = hold % MC terbesar + flag high yang
        # sudah pernah diberitahu (satu alert per titik high).
        "high_drop": ({"ts": high_ts,
                       "high": (_float(high_marker.get("high"), None)
                                if high_ts else None),
                       "high_ts": _int(high_marker.get("high_ts"), 0),
                       "notified_high": (_float(high_marker.get("notified_high"),
                                                0.0) if high_ts else 0.0)}
                      if high_ts else {}),
    }


def alert_state_summary(state: dict | None) -> dict:
    """Ringkasan alert state TANPA peta wallet, untuk ``holder_status.json``.

    Peta balance ``baseline``/``rolling`` (masing-masing sampai
    :data:`MAX_STORED_WALLETS` address) adalah state kerja aturan 4 jam dan
    memakan **83% byte** snapshot dashboard (terukur 1,85 MB dari 2,22 MB untuk
    36 token). Sejak store ``holder_history.json`` ikut dipublish ke ref
    ``holder-live`` (``holder_history.publish_holder_history``), peta itu tidak
    perlu dikirim ke dashboard — cukup jumlah + timestamp supaya kondisi alert
    tetap bisa diperiksa.

    Flag ``"summary": True`` dipakai ``holder_history.seed_from_status`` untuk
    mengenali payload ringkas dan **tidak** menimpanya sebagai state penuh
    (snapshot format lama yang masih membawa peta tetap dipulihkan seperti
    sebelumnya).
    """
    state = state if isinstance(state, dict) else {}

    def _snap(raw) -> dict:
        raw = raw if isinstance(raw, dict) else {}
        balances = raw.get("balances")
        dust = raw.get("dust")
        return {
            "ts": _int(raw.get("ts")),
            "wallets_seen": _int(raw.get("wallets_seen")),
            "balances": len(balances) if isinstance(balances, dict) else 0,
            "dust": len(dust) if isinstance(dust, (list, dict, set)) else 0,
            "dust_pct_mc": raw.get("dust_pct_mc"),
            "truncated": bool(raw.get("truncated")),
        }

    raw_last = state.get("last_sent") if isinstance(state.get("last_sent"),
                                                    dict) else {}
    last_sent = sorted(((str(key), _int(ts)) for key, ts in raw_last.items()
                        if _int(ts)), key=lambda item: -item[1])
    return {
        "summary": True,
        "baseline": _snap(state.get("baseline")),
        "rolling": _snap(state.get("rolling")),
        "sent_event_ids": len(state.get("sent_event_ids") or []),
        "last_sent": dict(last_sent[:MAX_LAST_SENT]),
        "rejected_signals": len(state.get("rejected_signals") or []),
    }


def _format_time(timestamp: int) -> str:
    moment = datetime.fromtimestamp(_int(timestamp), tz=timezone.utc)
    try:
        local = moment.astimezone(ZoneInfo("Asia/Jakarta"))
        return f"{local:%Y-%m-%d %H:%M:%S WIB} ({moment:%H:%M UTC})"
    except Exception:  # pragma: no cover - tz database is available in CI
        return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def _verification_lines(event: dict) -> list[str]:
    """Baris konfirmasi volume/harga untuk pesan Telegram (maks 2 baris)."""
    check = event.get("volume_check")
    if not isinstance(check, dict) or not check:
        return []
    if not check.get("verified"):
        return [f"Verifikasi volume: ⚠️ TIDAK TERVERIFIKASI — "
                f"{check.get('reason') or 'data pasar tidak tersedia'}"]
    parts = []
    ratio = _float(check.get("volume_ratio"), None)
    if ratio is not None:
        parts.append(f"volume 4 jam {ratio:.2f}× rata-rata 7d "
                     f"(ambang {_float(check.get('required_ratio'), 0):.1f}×)")
    change = _float(check.get("price_change_pct"), None)
    if change is not None:
        parts.append(f"harga {change:+.2f}%")
    buys = _float(check.get("buy_pressure"), None)
    sells = _float(check.get("sell_pressure"), None)
    if buys is not None and sells is not None:
        parts.append(f"buy {buys:.0f}/sell {sells:.0f}")
    mark = "✅" if check.get("is_valid") else "⚠️"
    lines = [f"Verifikasi volume: {mark} " + (" · ".join(parts) or "-")]
    score = _float(check.get("confidence_score"), None)
    required = _float(check.get("required_confidence"), None)
    if score is not None:
        tail = (f"Skor konfirmasi: {score:.2f}"
                + (f" (ambang {required:.2f})" if required is not None else ""))
        stddev = _float(check.get("price_stddev_4h"), None)
        if stddev is not None:
            tail += f" · stddev 4 jam {stddev:.2f}%"
            if check.get("high_volatility"):
                tail += " (pasar liar)"
        lines.append(tail)
    return lines


def _market_info_lines(check: dict | None) -> list[str]:
    """Baris konteks pasar untuk ⚡ EARLY DUMP — info saja, tanpa gerbang.

    Formatnya mirip :func:`_verification_lines` (angka pembanding volume /
    harga / tekanan / volatilitas) tapi sengaja memakai awalan
    ``Verifikasi:`` + penanda ℹ️ dan tidak menampilkan skor konfirmasi:
    rule early dump tidak memakai ambang skor, jadi skor 0,00 tidak boleh
    tampil seperti kegagalan verifikasi.
    """
    if not isinstance(check, dict) or not check:
        return []
    if not check.get("verified"):
        return [f"Verifikasi: ⚠️ TIDAK TERVERIFIKASI — "
                f"{check.get('reason') or 'data pasar tidak tersedia'} "
                "(info saja, early warning tanpa gerbang volume)"]
    parts = []
    ratio = _float(check.get("volume_ratio"), None)
    if ratio is not None:
        parts.append(f"volume 4 jam {ratio:.2f}× rata-rata 7d")
    change = _float(check.get("price_change_pct"), None)
    if change is not None:
        parts.append(f"harga {change:+.2f}%")
    buys = _float(check.get("buy_pressure"), None)
    sells = _float(check.get("sell_pressure"), None)
    if buys is not None and sells is not None:
        parts.append(f"buy {buys:.0f}/sell {sells:.0f}")
    stddev = _float(check.get("price_stddev_4h"), None)
    if stddev is not None:
        parts.append(f"stddev 4 jam {stddev:.2f}%")
    if not parts:
        return ["Verifikasi: ℹ️ data pasar tersedia "
                "(info saja, tanpa gerbang volume)"]
    return ["Verifikasi: ℹ️ " + " · ".join(parts)
            + " (info saja, tanpa gerbang volume)"]


def _pool_link_lines(pools) -> list[str]:
    """Baris 🌊 Meteora + 🦅 HawkFi per pool address (teks polos Telegram)."""
    lines = []
    for raw in pools or []:
        pool = str(raw or "").strip()
        if not pool:
            continue
        lines.append(f"🌊 Meteora: {meteora_dlmm_url(pool)}")
        lines.append(f"🦅 HawkFi: {hawkfi_meteora_url(pool)}")
    return lines


def format_alert_message(event: dict) -> str:
    """Human-readable Telegram message containing all required fields."""
    kind = event.get("kind")
    change = _float(event.get("change_pp"), 0.0) or 0.0
    if kind == "early_dump":
        title = f"⚡ EARLY DUMP — DUST HOLDER DI ATAS {DUST_BEST_PCT:g}%"
        lines = [
            title,
            f"Token: ${event.get('symbol') or '?'}",
            f"Dust sebelumnya: "
            f"{float(event.get('previous_dust_pct_mc') or 0):.2f}% MC",
            f"Dust terbaru: "
            f"{float(event.get('current_dust_pct_mc') or 0):.2f}% MC",
            f"Perubahan: {change:+.2f} poin persentase",
            f"Periode: {event.get('scope') or 'sejak run terakhir'}",
            # Pengingat berulang (permintaan user 2026-09-05): dikirim tiap
            # scan selama dust masih > 0,1% — sebutkan cara menghentikannya.
            "🔔 Pengingat berulang tiap ±15 menit selama dust di atas "
            f"{DUST_BEST_PCT:g}% MC. Hentikan dengan menghapus token dari "
            "watchlist LP atau memindahkannya ke watchlist biasa.",
            *_market_info_lines(event.get("volume_check")),
            f"Waktu: {_format_time(event.get('current_ts') or time.time())}",
            f"Mint: {event.get('mint') or '-'}",
            # Link token + pool: token selalu (GMGN/DexScreener, via
            # links.token_link_lines); pool (Meteora/HawkFi) hanya bila
            # event membawa pool address yang diketahui benar (lihat
            # keterbatasan cron di evaluate_early_dump_rule).
            *token_link_lines(event.get("mint")),
            *_pool_link_lines(event.get("pool_addresses")),
        ]
        return "\n".join(lines)
    if kind == HIGH_DROP_KIND:
        drop = _float(event.get("drop_pct"), None)
        title = f"🔔 DUST TURUN ≥ {HIGH_DROP_RATIO * 100:g}% DARI TITIK HIGH"
        drop_line = (f"Penurunan: −{drop:.1f}% dari titik high"
                     if drop is not None else
                     f"Perubahan: {change:+.2f} poin persentase")
        lines = [
            title,
            f"Token: ${event.get('symbol') or '?'}",
            f"Titik high: "
            f"{float(event.get('previous_dust_pct_mc') or 0):.2f}% MC",
            f"Dust terbaru: "
            f"{float(event.get('current_dust_pct_mc') or 0):.2f}% MC",
            drop_line,
            f"Periode: {event.get('scope') or 'sejak titik high'}",
            # Tanpa gerbang volume: konteks pasar = info saja (pola sama
            # dengan ⚡ EARLY DUMP).
            *_market_info_lines(event.get("volume_check")),
            f"Waktu: {_format_time(event.get('current_ts') or time.time())}",
            f"Mint: {event.get('mint') or '-'}",
            *token_link_lines(event.get("mint")),
        ]
        return "\n".join(lines)
    if kind == "dump":
        title = "🚨 INDIKASI DUMP — HOLDER DUST NAIK"
    elif kind == "accumulation":
        title = "🟢 KEMUNGKINAN AKUMULASI — HOLDER DUST TURUN"
    else:
        direction = "NAIK" if change >= 0 else "TURUN"
        title = f"🔎 CEK PERUBAHAN DUST DARI SNAPSHOT AWAL — {direction}"

    movement = event.get("movements") or {}
    lines = [
        title,
        f"Token: ${event.get('symbol') or '?'}",
        f"Dust sebelumnya: {float(event.get('previous_dust_pct_mc') or 0):.2f}% MC",
        f"Dust terbaru: {float(event.get('current_dust_pct_mc') or 0):.2f}% MC",
        f"Perubahan: {change:+.2f} poin persentase",
        f"Periode: {event.get('scope') or '~4 jam'}",
        *_verification_lines(event),
        f"Wallet saldo meningkat: {int(event.get('wallet_increases') or 0)}",
        "Pergerakan sampel wallet dust:",
        f"- Membesar / keluar dust: {int(movement.get('dust_grew_out') or 0)}",
        f"- Jual habis / hilang: {int(movement.get('dust_sold_out') or 0)}",
        f"- Keluar dust lainnya: {int(movement.get('dust_left_other') or 0)}",
        f"- Mengecil / masuk dust: {int(movement.get('larger_shrank_into_dust') or 0)}",
        f"- Wallet dust baru: {int(movement.get('new_dust') or 0)}",
        f"- Masuk dust lainnya: {int(movement.get('dust_entered_other') or 0)}",
        f"Waktu: {_format_time(event.get('current_ts') or time.time())}",
        f"Mint: {event.get('mint') or '-'}",
        # Link token supaya alert bisa langsung ditindaklanjuti di GMGN /
        # DexScreener; hilang bila mint tidak diketahui (tidak ada label
        # menggantung). URL dibangun links.py (satu sumber, sudah di-encode).
        *token_link_lines(event.get("mint")),
    ]
    return "\n".join(lines)


def _safe_transport_error(exc: Exception, token: str) -> str:
    """Render a transport error without leaking the bot token from its URL."""
    message = str(exc)
    return message.replace(token, "[REDACTED]") if token else message


# TODO(alerts): hormati 429 ``retry_after`` dari Bot API. Saat ini alert yang
# kena rate-limit hanya di-log; event id-nya tidak dicatat sehingga dikirim
# ulang pada run 1 jam berikutnya (aman, tapi bukan backoff sebenarnya).
# TODO(alerts): beri throttle bila suatu saat banyak token memicu alert
# bersamaan — GeckoTerminal publik ~30 request/menit dan konteks pasar ditarik
# lazy per token yang punya kandidat sinyal.
def send_telegram_message(text: str, *, bot_token: str | None = None,
                          chat_id: str | None = None, timeout: float = 10,
                          post: Callable | None = None) -> dict:
    """Send one Bot API ``sendMessage`` request; never raise to the scanner."""
    token = (os.environ.get("TELEGRAM_BOT_TOKEN", "")
             if bot_token is None else str(bot_token)).strip()
    target = (os.environ.get("TELEGRAM_CHAT_ID", "")
              if chat_id is None else str(chat_id)).strip()
    if not token or not target:
        return {"ok": False, "skipped": True,
                "error": "Telegram credentials are not configured"}

    request_post = post or requests.post
    try:
        response = request_post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": target, "text": str(text)}, timeout=timeout)
    except requests.RequestException as exc:
        return {"ok": False, "skipped": False,
                "error": "Telegram request failed: "
                         f"{_safe_transport_error(exc, token)}"}
    except Exception as exc:  # noqa: BLE001 - transport must never kill scan
        return {"ok": False, "skipped": False,
                "error": "Telegram transport failed: "
                         f"{_safe_transport_error(exc, token)}"}

    if getattr(response, "status_code", 0) != 200:
        return {"ok": False, "skipped": False,
                "status": getattr(response, "status_code", None),
                "error": f"Telegram HTTP {getattr(response, 'status_code', '?')}"}
    try:
        payload = response.json() or {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skipped": False,
                "status": 200, "error": f"Telegram response invalid: {exc}"}
    if payload.get("ok") is not True:
        description = str(payload.get("description") or "API returned ok=false")
        return {"ok": False, "skipped": False, "status": 200,
                "error": f"Telegram API failed: {description}"}
    return {"ok": True, "skipped": False, "status": 200}


def send_telegram_alert(event: dict) -> dict:
    return send_telegram_message(format_alert_message(event))


def send_test_alert() -> dict:
    """Send a harmless deployment test using the same transport as alerts."""
    stamp = _format_time(int(time.time()))
    return send_telegram_message(
        "✅ TEST ALERT HOLDER DUST\n"
        "Integrasi Telegram Wallet Depth aktif.\n"
        f"Waktu: {stamp}\n"
        "Pesan ini hanya pengujian, bukan sinyal token."
    )


def _reset_markers_on_readd(state: dict | None, meta) -> dict:
    """Buang marker LP/high bila token di-add **ulang** ke watchlist.

    ``meta`` entri watchlist membawa tanggal ``added``; marker (early_dump /
    high_drop) yang lebih tua dari tanggal itu berasal dari periode
    watchlist sebelumnya dan tidak boleh dipakai (high lama bisa memicu
    alert palsu begitu token dipantau lagi). State lain tidak disentuh.
    """
    state = dict(state or {})
    added = None
    try:
        from watchlist_detail import parse_added_ts
        added = parse_added_ts(meta)
    except Exception:  # noqa: BLE001 - reset bersifat pelengkap
        added = None
    if not added:
        return state
    for key in ("early_dump", "high_drop"):
        marker = state.get(key)
        if isinstance(marker, dict) and 0 < _int(marker.get("ts"), 0) < added:
            state[key] = {}
    return state


def process_holder_alerts(analyses: dict | None, history_store: dict,
                          *, sender: Callable[[dict], dict] | None = None,
                          market_contexts=None,
                          context_provider: Callable[[str, dict], dict] | None = None,
                          lp_mints: set | None = None,
                          high_mints: set | None = None,
                          watchlist_meta: dict | None = None) -> list[dict]:
    """Evaluate/send alerts, mutating state *before* history ingests new points.

    ``market_contexts`` (``{mint: context}``) dipakai bila konteks pasar sudah
    disiapkan pemanggil; selain itu ``context_provider(mint, analysis)``
    dipanggil lazy hanya untuk token yang punya kandidat sinyal. Setelah kirim
    berhasil, ``last_sent[kunci]`` diperbarui agar alert sejenis tidak
    berulang dalam interval dedupnya. ``lp_mints`` = mint token LP (Chart LP /
    ``source=meteora`` + watchlist Robinhood LP) — scope rule ``early_dump``
    (pengingat berulang > 0,1% MC); ``high_mints`` = mint watchlist biasa —
    scope rule ``high_drop`` (turun ≥ 50% dari titik high). Keduanya
    kosong/None = rule terkait tidak pernah menyala. ``watchlist_meta``
    (``{mint: meta}``, opsional) dipakai untuk me-reset marker bila token
    baru di-add ulang ke watchlist.
    """
    sender = sender or send_telegram_alert
    contexts = market_contexts if isinstance(market_contexts, dict) else {}
    meta_map = watchlist_meta if isinstance(watchlist_meta, dict) else {}
    lp = {str(item) for item in (lp_mints or []) if item}
    high = {str(item) for item in (high_mints or []) if item}
    tokens = history_store.setdefault("tokens", {})
    deliveries = []
    for mint, analysis in (analyses or {}).items():
        if not isinstance(analysis, dict):
            continue
        holders = analysis.get("holders") or {}
        # A provider outage can still return an analysis object with zero
        # fetched holders. Never advance anchors or emit a false baseline drop
        # from that failed scan.
        if ("total_fetched" in holders
                and _int(holders.get("total_fetched")) <= 0):
            continue
        slot = tokens.setdefault(mint, {"symbol": analysis.get("symbol") or "?",
                                        "cohort": {}, "points": []})
        old_state = slot.get(STATE_KEY) if isinstance(slot.get(STATE_KEY), dict) \
            else {}
        old_state = _reset_markers_on_readd(old_state, meta_map.get(mint))
        context = contexts.get(mint) if isinstance(contexts.get(mint), dict) \
            else None
        events, next_state = evaluate_alert_events(
            mint, analysis, old_state, market_context=context,
            context_provider=context_provider,
            lp_mint=bool(mint in lp), high_track=bool(mint in high))
        sent = list(next_state.get("sent_event_ids") or [])
        last_sent = dict(next_state.get("last_sent") or {})
        for event in events:
            try:
                result = sender(event)
                if isinstance(result, bool):
                    result = {"ok": result, "skipped": False}
                elif not isinstance(result, dict):
                    result = {"ok": False, "skipped": False,
                              "error": "invalid sender result"}
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "skipped": False,
                          "error": f"Telegram sender failed: {exc}"}
            deliveries.append({"event": event, "delivery": result})
            if result.get("ok"):
                sent.append(event["id"])
                last_sent[dedup_key(event)] = _int(event.get("current_ts"))
            elif not result.get("skipped"):
                print(f"WARN: Telegram alert {event['id']} gagal: "
                      f"{result.get('error') or 'unknown error'}", file=sys.stderr)
        next_state["sent_event_ids"] = sent[-MAX_SENT_EVENT_IDS:]
        next_state["last_sent"] = last_sent
        slot[STATE_KEY] = compact_alert_state(next_state)
    return deliveries


