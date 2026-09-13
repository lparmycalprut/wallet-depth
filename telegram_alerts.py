# -*- coding: utf-8 -*-
"""Telegram rules and transport for holder-dust scans.

**Satu notifikasi saja** (permintaan user 2026-09-13): **⚡ EARLY DUMP
TERJADI - GANTI WIDE RANGE** — menyala tiap ``dust % MC`` token watchlist
naik **≥ :data:`EARLY_DUMP_STEP_PCT`** (0,02%) dari **patokan saat token
masuk watchlist**, lalu berulang untuk tiap kelipatan 0,02% berikutnya.
Bukan lagi ambang batas (``≥ 0,06% MC`` seperti rule 2026-09-11): patokannya
delta terhadap titik add, jadi token yang dust-nya sudah tinggi tidak
otomatis berbunyi dan token yang masih rendah bisa berbunyi.

Patokan (``baseline_pct``) dipasang **sekali** per episode:

- idealnya dari titik history pertama setelah tanggal ``added`` watchlist
  (``add_baseline_for_mint`` — angka dust yang benar-benar terukur saat token
  dipantau, bukan angka scan pertama yang bisa datang berjam-jam kemudian di
  lane yang tidak di-scan cron);
- cadangannya angka dust pada evaluasi pertama setelah token di-add.

Evaluasi yang memasang patokan **tidak** mengirim notifikasi (menghindari
banjir pesan untuk token lama saat rule baru dipasang); setelah itu tiap
kenaikan satu langkah 0,02% yang belum pernah dikabarkan mengirim satu pesan.
Dedup per bucket :data:`FAST_BUCKET_SEC` + jeda
:data:`EARLY_DUMP_RESEND_SEC` menjaga run ganda (chain dispatch menabrak
schedule) tidak mengirim pesan kembar, dan langkah yang gagal terkirim
**tidak dimakan** — ia dicoba lagi di scan berikutnya. Marker
``alert_state["early_dump"]`` = ``{ts, dust_pct_mc, baseline_pct, baseline_ts,
step, baseline_src}``; di-merge paling baru oleh
``holder_history._merge_alert_state`` + dipertahankan ``compact_alert_state``
dan ``alert_state_summary`` (cron 5 menit yang ephemeral harus bisa
melanjutkan patokan/langkah dari snapshot status).

Rule lama **DIHAPUS** seluruhnya — tidak ada lagi ``🚨 WAKTUNYA GANTI
STRATEGI`` (level-based dust ≥ 0,06% MC, 2026-09-11), ``🔔 HIGH DROP``
(turun ≥ 50% dari titik high), ``🚨 WAKTUNYA EXIT / CUTLOSS``, ``✅ KEMBALI
KE TITIK AMAN``, dump/akumulasi 4 jam (delta 0,25/0,50 pp), baseline shift,
**beserta gerbang konfirmasi volume/harga/volatilitas**
(``validate_alert_with_volume``/``volume_verdict``) yang menyaringnya.
Alasan user: rule lama memakai **ambang** sehingga hanya berbunyi sekali di
titik tertentu; yang diinginkan sekarang adalah kabar **berulang** tiap dust
bertambah 0,02% dari titik add ("jadi sekarang bukan ambang batas, tapi notif
berulang ketika dust bertambah 0,02% dari pertama add watchlist").

Konteks pasar (``alert_context``) tetap **opsional** dan hanya diminta lewat
``context_provider`` **saat notifikasi benar-benar akan dikirim** (lazy — scan
yang tenang tidak menambah satu request pun). Ia tidak lagi menjadi gerbang:
kalau datanya ada, pesannya membawa satu baris
``📈 Pasar: vol 4j …× avg 7d · harga …%``; kalau tidak ada, barisnya hilang
dan alert tetap terkirim.

Fungsi aturan sengaja tidak menyentuh HTTP: ``evaluate_alert_events`` /
``process_holder_alerts`` boleh diuji tanpa request Telegram, dan transport
(:func:`send_telegram_message`) tidak pernah melempar ke pemanggil scan.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import os
import sys
import time
from typing import Callable, Iterable

import requests

from holder_history import holders_usable
from links import hawkfi_meteora_url, meteora_dlmm_url, token_links

# ---------------------------------------------------------------------------
# ⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE — satu-satunya notifikasi.
# ---------------------------------------------------------------------------
# Sejak 2026-09-13 notifikasinya **delta**, bukan ambang: patokannya angka
# dust token **saat masuk watchlist** (``baseline_pct`` di marker) dan pesan
# dikirim tiap kali dust naik kelipatan ``EARLY_DUMP_STEP_PCT`` (0,02% MC)
# dari patokan itu. Permintaan user: "notifikasi telegram akan muncul ketika
# %dust naik 0,02%, jadi sekarang bukan ambang batas, tapi notif berulang
# ketika dust bertambah 0,02% dari pertama add watchlist" + judul barunya
# "EARLY DUMP TERJADI - GANTI WIDE RANGE".
EARLY_DUMP_STEP_PCT = 0.02
EARLY_DUMP_KIND = "early_dump"
# Kunci marker di ``alert_state``:
# ``{ts, dust_pct_mc, baseline_pct, baseline_ts, step, baseline_src}``.
EARLY_DUMP_MARKER = "early_dump"
EARLY_DUMP_TITLE = "⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE"
# Ritme pencatatan LP = ±5 menit; bucket event id + jeda minimum kirim
# mengikuti ritme itu supaya run ganda (chain dispatch menabrak schedule)
# tidak mengirim pesan kembar. Langkah 0,02% sendiri sudah dijaga
# ``marker["step"]``, jadi jeda ini hanya lapisan kedua.
FAST_BUCKET_SEC = 5 * 60
EARLY_DUMP_RESEND_SEC = FAST_BUCKET_SEC
EVENT_BUCKET_SEC = FAST_BUCKET_SEC
MAX_LAST_SENT = 8
# Anchor wallet (baseline immutable + rolling) TIDAK lagi menjadi bahan
# evaluasi rule apa pun — dipertahankan karena ``tracked_wallet_addresses``
# memakainya untuk kesinambungan alamat yang dibandingkan antar-scan
# (kronologi wallet + ``build_wallet_snapshot``). ``ALERT_WINDOW_*`` menjaga
# supaya anchor yang digeser benar-benar berjarak ±4 jam, bukan 5 menit.
ALERT_WINDOW_SEC = 4 * 3600
ALERT_WINDOW_MIN_SEC = ALERT_WINDOW_SEC - 15 * 60
ALERT_WINDOW_MAX_SEC = ALERT_WINDOW_SEC + 60 * 60
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



def dedup_key(event: dict | None) -> str:
    """Kunci dedup per token: jenis event (satu-satunya arah yang ada).

    Mengikuti bentuk ``_event_id``. Dulu baseline_shift memakai arah
    (``"baseline_shift:up"``/``":down"``) supaya dua kabar tidak saling
    membungkam; dengan satu rule delta, arah tidak punya arti — cukup
    ``kind``.
    """
    return str((event or {}).get("kind") or "")


def in_resend_cooldown(key: str, current_ts: int, last_sent=None, *,
                       min_resend_sec: int = EARLY_DUMP_RESEND_SEC) -> bool:
    """True bila kunci itu sudah dikirim kurang dari ``min_resend_sec`` lalu.

    Event id memakai bucket (±5 menit), jadi dua run di dua sisi batas bucket
    bisa terkirim hanya berjarak beberapa menit. Lapisan ini menutup celah
    duplikasi dalam satu interval tanpa mengubah granularitas bucket.
    """
    previous = _int((last_sent or {}).get(key), 0)
    if not previous:
        return False
    age = _int(current_ts) - previous
    return 0 <= age < min_resend_sec


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


def _market_brief(context) -> dict:
    """Ringkas konteks pasar jadi beberapa angka untuk baris ``📈 Pasar``.

    Bukan gerbang — hanya pelengkap pesan. ``volume_ratio`` dihitung bila
    keduanya ada (``avg_volume_7d`` = rata-rata volume **per window 4 jam**),
    dan ``None`` untuk field yang tidak tersedia supaya pesannya tidak
    mengarang angka.
    """
    ctx = context if isinstance(context, dict) else {}
    volume = _float(ctx.get("volume_4h"), None)
    baseline = _float(ctx.get("avg_volume_7d"), None)
    volatility = ctx.get("volatility") if isinstance(ctx.get("volatility"),
                                                      dict) else {}
    return {
        "volume_4h": volume,
        "avg_volume_7d": baseline,
        "volume_ratio": (round(volume / baseline, 2)
                         if volume is not None and baseline else None),
        "price": _float(ctx.get("price"), None),
        "price_change_pct": _float(ctx.get("price_change_pct"), None),
        "price_stddev_4h": _float(volatility.get("price_stddev_4h"), None),
    }


def _steps_from_baseline(pct, baseline, *,
                         step: float = EARLY_DUMP_STEP_PCT) -> int:
    """Berapa **kelipatan penuh** ``step`` kenaikan dust dari patokan (≥ 0).

    Delta dihitung terhadap patokan watchlist, bukan antar-scan: dust yang
    turun tidak pernah mengurangi langkah (langkah bersifat *high water mark*
    — naik lagi ke level yang sudah dikabarkan tidak mengirim pesan ulang).
    Toleransi ``1e-9`` mencegah galat pembulatan float membuat 0,040% persis
    terbaca 1,999999 langkah.
    """
    current = _float(pct, None)
    base = _float(baseline, None)
    if current is None or base is None:
        return 0
    size = _float(step, None) or EARLY_DUMP_STEP_PCT
    delta = current - base
    if delta <= 0 or size <= 0:
        return 0
    return int(math.floor(delta / size + 1e-9))


def add_baseline_for_mint(history_store: dict | None, mint: str,
                          meta: dict | None = None):
    """``(dust_pct_mc, ts, "history")`` titik pertama setelah token di-add.

    Patokan 🚀 == "pertama add watchlist": entri watchlist menyimpan tanggal
    ``added`` (``watchlist_detail.parse_added_ts``), dan store history sudah
    memuat titik-titik dust token itu. Yang dipakai = titik **paling awal**
    yang tidak lebih tua dari tanggal add dan datanya layak
    (``holder_history.point_usable``: bukan scan yang gagal/terpotong dan
    jumlah wallet cukup untuk dust %MC).

    ``None`` bila tanggal add tidak terbaca, token belum punya titik history,
    atau semua titiknya tidak layak — pemanggil lalu jatuh ke angka dust pada
    evaluasi pertama (:func:`early_dump_marker_next`).
    """
    mint = _address(mint)
    if not mint:
        return None
    try:
        from watchlist_detail import parse_added_ts
        added = parse_added_ts(meta)
    except Exception:  # noqa: BLE001 - patokan bersifat pelengkap
        added = None
    if not added:
        return None
    slot = ((history_store or {}).get("tokens") or {}).get(mint) or {}
    points = slot.get("points") if isinstance(slot, dict) else None
    try:
        from holder_history import point_usable
    except Exception:  # noqa: BLE001
        return None
    candidates = []
    for point in points or []:
        if not isinstance(point, dict):
            continue
        ts = _int(point.get("ts"))
        pct = _float(point.get("dust_pct_mc"), None)
        if pct is None or ts < _int(added):
            continue
        if not point_usable(point):
            continue
        candidates.append((ts, pct))
    if not candidates:
        return None
    ts, pct = min(candidates, key=lambda item: item[0])
    return pct, ts, "history"


def _early_dump_event(marker: dict, current: dict, *, mint: str, symbol: str,
                      steps: int, baseline_src: str = "") -> dict:
    """Satu event ⚡ EARLY DUMP (delta dust terhadap patokan watchlist).

    Marker tidak membawa snapshot wallet (hanya angka dust + patokan), jadi
    event ini sengaja tidak menghitung ``wallet_movements``. Event id memakai
    **bucket 5 menit** (:data:`FAST_BUCKET_SEC`) supaya run ganda tidak
    mengirim pesan yang sama dua kali.
    """
    current_ts = _int((current or {}).get("ts"))
    baseline = _float((marker or {}).get("baseline_pct"), 0.0) or 0.0
    new = _float((current or {}).get("dust_pct_mc"), 0.0) or 0.0
    baseline_ts = _int((marker or {}).get("baseline_ts"), 0)
    event = {
        "id": _event_id(mint, EARLY_DUMP_KIND, current_ts,
                        bucket_sec=FAST_BUCKET_SEC),
        "kind": EARLY_DUMP_KIND,
        "direction": "up",
        "mint": _address(mint),
        "symbol": str(symbol or "?").strip().upper() or "?",
        # ``previous_dust_pct_mc`` = patokan watchlist (bukan angka scan
        # sebelumnya) — pesannya membaca "patokan → sekarang".
        "previous_dust_pct_mc": baseline,
        "current_dust_pct_mc": new,
        "change_pp": round(new - baseline, 6),
        "step": max(1, int(steps)),
        "step_pct": EARLY_DUMP_STEP_PCT,
        "baseline_ts": baseline_ts,
        "baseline_src": str(baseline_src or ""),
        "minutes_since_baseline": (max(0, (current_ts - baseline_ts) // 60)
                                   if baseline_ts else 0),
        "previous_ts": _int((marker or {}).get("ts")),
        "current_ts": current_ts,
        "wallet_increases": 0,
        "movements": {},
        # Pool address tidak disimpan di watchlist.json; pemanggil cron belum
        # bisa mengisinya (keterbatasan terdokumentasi). Field ini disiapkan
        # supaya pesan memuat 🌊 Meteora + 🦅 HawkFi bila sumber pool address
        # tersedia (mis. hasil scan_meteora).
        "pool_addresses": [str(p or "").strip()
                           for p in (current.get("pool_addresses") or []) if p],
    }
    return event


def evaluate_early_dump_rule(marker: dict | None, current: dict | None, *,
                             mint: str, symbol: str = "?",
                             sent_event_ids=(), market_context=None,
                             context_provider=None,
                             last_sent=None,
                             baseline_hint=None) -> list[dict]:
    """⚡ EARLY DUMP: dust naik ≥ **0,02% MC** dari patokan watchlist → notif.

    Delta, bukan ambang: ``marker["baseline_pct"]`` adalah angka dust saat
    token masuk watchlist, dan pesan dikirim tiap kali kenaikan melewati
    langkah 0,02% yang **belum pernah dikabarkan** (``marker["step"]``).
    Naik 0,02% → 1 pesan, naik lagi 0,02% → pesan berikutnya, dst.

    Marker **kosong** (token baru di-add, atau state lama yang belum punya
    patokan) = evaluasi ini hanya **memasang patokan**: ``baseline_hint``
    ``(pct, ts, src)`` dari history dipakai bila ada, kalau tidak angka dust
    run ini. Tanpa ``baseline_hint`` fungsi ini **tidak** mengirim apa pun —
    :func:`early_dump_marker_next` yang menulis patokannya, sehingga token
    yang sudah berjalan lama tidak membanjiri Telegram saat rule dipasang.

    Frekuensi dibatasi event id per **bucket 5 menit** + cooldown
    :data:`EARLY_DUMP_RESEND_SEC`. Tidak ada gerbang volume/harga — konteks
    pasar hanya melengkapi pesan (lihat :func:`_market_brief`).
    """
    new = _float((current or {}).get("dust_pct_mc"), None)
    if new is None:
        return []
    current_ts = _int((current or {}).get("ts"))
    marker = dict(marker) if isinstance(marker, dict) else {}
    baseline = _float(marker.get("baseline_pct"), None)
    baseline_src = str(marker.get("baseline_src") or "")
    if baseline is None:
        # Belum ada patokan: pakai hint history kalau ada (token di-add sebelum
        # rule ini melihatnya) supaya notifikasi pertama tidak "menghitung dari
        # sekarang" dan menghapus kenaikan yang sudah terjadi sejak add.
        hint = baseline_hint if isinstance(baseline_hint, (tuple, list)) \
            else None
        if not hint or _float(hint[0], None) is None:
            return []
        baseline = _float(hint[0], 0.0) or 0.0
        baseline_src = str(hint[2] if len(hint) > 2 else "history")
        marker["baseline_pct"] = baseline
        marker["baseline_ts"] = _int(hint[1]) if len(hint) > 1 else 0
        marker["baseline_src"] = baseline_src
    steps = _steps_from_baseline(new, baseline)
    notified = _int(marker.get("step"), 0)
    if steps <= notified:
        return []
    event = _early_dump_event(marker, current, mint=mint, symbol=symbol,
                              steps=steps, baseline_src=baseline_src)
    if event["id"] in set(sent_event_ids or []):
        return []
    if in_resend_cooldown(dedup_key(event), current_ts, last_sent,
                          min_resend_sec=EARLY_DUMP_RESEND_SEC):
        return []
    context = market_context if isinstance(market_context, dict) else \
        _resolve_context(context_provider, mint)
    brief = _market_brief(context)
    if any(value is not None for value in brief.values()):
        event["market"] = brief
    return [event]


def early_dump_marker_next(marker: dict | None, current: dict | None, *,
                           baseline_hint=None) -> dict:
    """Marker ``{ts, dust_pct_mc, baseline_pct, baseline_ts, step, …}`` run ini.

    ``ts``/``dust_pct_mc`` = angka run **terakhir** (walau tidak ada pesan
    karena langkahnya sudah dikabarkan), ``baseline_pct``/``baseline_ts`` =
    patokan watchlist yang **tidak pernah bergeser** selama token masih
    dipantau (inilah "pertama add watchlist"), dan ``step`` = langkah
    tertinggi yang sudah dianggap selesai (monoton naik, supaya satu langkah
    0,02% tidak dikabarkan dua kali).

    Marker dikosongkan (``{}``) bila angka dust run ini tidak ada; patokan
    episode baru dipasang di evaluasi berikutnya.
    """
    pct = _float((current or {}).get("dust_pct_mc"), None)
    ts = _int((current or {}).get("ts"))
    if pct is None:
        return {}
    marker = dict(marker) if isinstance(marker, dict) else {}
    baseline = _float(marker.get("baseline_pct"), None)
    baseline_ts = _int(marker.get("baseline_ts"), 0)
    baseline_src = str(marker.get("baseline_src") or "")
    if baseline is None:
        hint = baseline_hint if isinstance(baseline_hint, (tuple, list)) \
            else None
        if hint and _float(hint[0], None) is not None:
            baseline = _float(hint[0], 0.0) or 0.0
            baseline_ts = _int(hint[1]) if len(hint) > 1 else 0
            baseline_src = str(hint[2] if len(hint) > 2 else "history")
        else:
            baseline, baseline_ts, baseline_src = pct, ts, "first-scan"
    steps = max(_int(marker.get("step"), 0),
                _steps_from_baseline(pct, baseline))
    return {"ts": ts, "dust_pct_mc": pct, "baseline_pct": baseline,
            "baseline_ts": baseline_ts, "step": steps,
            "baseline_src": baseline_src}


def evaluate_alert_events(mint: str, analysis: dict,
                          state: dict | None = None, *,
                          market_context=None,
                          context_provider=None,
                          advance_anchors: bool = True,
                          baseline_hint=None) -> tuple[list[dict], dict]:
    """Pure state transition: evaluate the one rule, then advance the anchors.

    ``market_context`` (dict siap pakai) atau ``context_provider(mint,
    analysis)`` memasok volume/harga untuk **baris pelengkap** pesan. Provider
    dipanggil maksimal satu kali per evaluasi dan hanya bila notifikasi benar-
    benar terkirim (lazy), jadi scan yang tenang tidak menambah API call.
    ``advance_anchors=False`` (scan ad-hoc / lane 5 menit) menjaga peta wallet
    cron tetap utuh — anchor hanya dimajukan oleh scan FULL.

    ``baseline_hint`` = ``(dust %MC, ts, sumber)`` patokan ⚡ EARLY DUMP dari
    history (lihat :func:`add_baseline_for_mint`) untuk token yang baru
    pertama kali dievaluasi rule ini — tanpa itu patokannya angka dust run ini
    dan kenaikan yang sudah terjadi sejak add tidak kabar.

    State lama yang tidak dipakai lagi (``strategy_shift``/``high_drop``/
    ``rejected_signals``) **tidak** dipertahankan: compaction hanya menulis
    marker rule ini, jadi sisa state dari store lama hilang sendiri pada run
    berikutnya.
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
    raw_marker = state.get(EARLY_DUMP_MARKER)
    marker = dict(raw_marker) if isinstance(raw_marker, dict) else {}
    next_state = {
        "baseline": state.get("baseline") or {},
        "rolling": state.get("rolling") or {},
        "sent_event_ids": sent[-MAX_SENT_EVENT_IDS:],
        "last_sent": last_sent,
        EARLY_DUMP_MARKER: marker,
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

    # ⚡ EARLY DUMP: dievaluasi terhadap marker LAMA (patokan + langkah yang
    # sudah dikabarkan), lalu marker dimajukan ke angka run ini — patokan
    # dipasang di sini kalau belum ada, dan langkah yang sudah lewat ikut
    # dicatat supaya tidak dikabarkan ulang.
    events = evaluate_early_dump_rule(
        marker or None, current, mint=mint, symbol=symbol,
        sent_event_ids=sent, market_context=context, context_provider=lazy,
        last_sent=last_sent, baseline_hint=baseline_hint)
    next_state[EARLY_DUMP_MARKER] = early_dump_marker_next(
        marker, current, baseline_hint=baseline_hint)

    if advance_anchors:
        baseline = state.get("baseline") if isinstance(state.get("baseline"), dict) \
            else {}
        if not baseline or baseline.get("dust_pct_mc") is None:
            next_state["baseline"] = compact_wallet_snapshot(current)

        rolling = state.get("rolling") if isinstance(state.get("rolling"), dict) \
            else {}
        if not rolling or rolling.get("dust_pct_mc") is None:
            next_state["rolling"] = compact_wallet_snapshot(current)
        else:
            age = current["ts"] - _int(rolling.get("ts"))
            if is_valid_4h_snapshot(rolling, current):
                next_state["rolling"] = compact_wallet_snapshot(current)
            elif age > ALERT_WINDOW_MAX_SEC or age < 0:
                # Stale/out-of-order anchors are unsafe for any comparison.
                next_state["rolling"] = compact_wallet_snapshot(current)
            # A young anchor remains frozen until it reaches the valid window.

    unique = {event["id"]: event for event in events}
    return list(unique.values()), next_state


def summarize_deliveries(deliveries) -> dict:
    """Ringkasan hasil kirim alert — dipakai UI scan manual.

    :func:`process_holder_alerts` mengembalikan satu baris per event; UI butuh
    angka + alasan supaya user bisa membedakan **"tidak ada sinyal"** dari
    **"ada sinyal tapi gagal terkirim"** (mis. kredensial Telegram tidak
    terpasang di deployment dashboard).
    """
    rows = [row for row in (deliveries or []) if isinstance(row, dict)]
    sent = muted = failed = 0
    kinds: list[str] = []
    errors: list[str] = []
    for row in rows:
        event = row.get("event") or {}
        delivery = row.get("delivery") or {}
        kinds.append(str(event.get("kind") or "?"))
        if delivery.get("ok"):
            sent += 1
        elif delivery.get("muted"):
            muted += 1
        else:
            failed += 1
            error = str(delivery.get("error") or "").strip()
            if error and error not in errors:
                errors.append(error)
    return {"total": len(rows), "sent": sent, "muted": muted, "failed": failed,
            "kinds": kinds, "errors": errors}


def delivery_note(summary: dict | None) -> str:
    """Satu kalimat hasil kirim alert scan manual (ditampilkan di card).

    Sengaja menyebutkan kegagalan: scan manual adalah satu-satunya jalur
    alert untuk token yang tidak di-scan cron (watchlist biasa), jadi
    "kredensial tidak terpasang" tidak boleh terbaca seperti "aman".
    """
    summary = summary if isinstance(summary, dict) else {}
    if not int(summary.get("total") or 0):
        return "Tidak ada notifikasi dari hasil scan ini."
    bits = []
    if summary.get("sent"):
        bits.append(f"⚡ {int(summary['sent'])} notifikasi EARLY DUMP "
                    "TERJADI dikirim")
    if summary.get("muted"):
        # Sejak toggle 🔔/🔕 per token (2026-09-11) alasan "dilewati" tidak
        # lagi selalu toggle global watchlist biasa — sebut sebabnya netral.
        bits.append(f"{int(summary['muted'])} notifikasi dilewati "
                    "(notif token itu sedang dimatikan)")
    if summary.get("failed"):
        reason = ("; ".join(summary.get("errors") or [])
                  or "penyebab tidak diketahui")
        bits.append(f"{int(summary['failed'])} notifikasi GAGAL dikirim ({reason})")
    return " · ".join(bits) + "."


def compact_alert_state(state: dict | None) -> dict:
    """Sanitize/bound state before persisting it in history/status JSON."""
    state = state or {}
    raw_last = state.get("last_sent") if isinstance(state.get("last_sent"),
                                                    dict) else {}
    last_sent = {str(key): _int(ts) for key, ts in raw_last.items() if _int(ts)}
    newest_first = sorted(last_sent.items(), key=lambda item: -item[1])
    raw_marker = state.get(EARLY_DUMP_MARKER)
    marker = dict(raw_marker) if isinstance(raw_marker, dict) else {}
    marker_ts = _int(marker.get("ts"))
    return {
        "baseline": compact_wallet_snapshot(state.get("baseline")),
        "rolling": compact_wallet_snapshot(state.get("rolling")),
        "sent_event_ids": list(dict.fromkeys(
            str(item) for item in (state.get("sent_event_ids") or []) if item
        ))[-MAX_SENT_EVENT_IDS:],
        "last_sent": dict(newest_first[:MAX_LAST_SENT]),
        # Marker ⚡: ringkas (ts + dust % MC terakhir + **patokan** + langkah
        # yang sudah dikabarkan), tanpa peta wallet — cukup untuk melanjutkan
        # episode run berikutnya. Runner cron ephemeral kehilangan patokan
        # 0,02% (dan langsung berhenti berbunyi) tanpa field-field ini.
        EARLY_DUMP_MARKER: ({"ts": marker_ts,
                             "dust_pct_mc": (_float(marker.get("dust_pct_mc"),
                                                    None) if marker_ts
                                              else None),
                             "baseline_pct": _float(
                                 marker.get("baseline_pct"), None),
                             "baseline_ts": _int(marker.get("baseline_ts"), 0),
                             "step": _int(marker.get("step"), 0),
                             "baseline_src": str(
                                 marker.get("baseline_src") or "")}
                            if marker_ts else {}),
    }


def alert_state_summary(state: dict | None) -> dict:
    """Ringkasan alert state TANPA peta wallet, untuk ``holder_status.json``.

    Peta balance ``baseline``/``rolling`` (masing-masing sampai
    :data:`MAX_STORED_WALLETS` address) memakan **83% byte** snapshot dashboard
    (terukur 1,85 MB dari 2,22 MB untuk 36 token). Sejak store
    ``holder_history.json`` ikut dipublish ke ref ``holder-live``
    (``holder_history.publish_holder_history``), peta itu tidak perlu dikirim
    ke dashboard — cukup jumlah + timestamp supaya kondisi alert tetap bisa
    diperiksa.

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
    raw_marker = state.get(EARLY_DUMP_MARKER) \
        if isinstance(state.get(EARLY_DUMP_MARKER), dict) else {}
    marker_ts = _int(raw_marker.get("ts"))
    return {
        "summary": True,
        "baseline": _snap(state.get("baseline")),
        "rolling": _snap(state.get("rolling")),
        "sent_event_ids": len(state.get("sent_event_ids") or []),
        "last_sent": dict(last_sent[:MAX_LAST_SENT]),
        # Marker ringkas (bukan peta wallet) — runner GitHub ephemeral butuh
        # marker ini di snapshot status supaya scan 5 menit berikutnya tidak
        # kehilangan patokan/langkah 0,02% bila backup history gzip gagal
        # di-push.
        EARLY_DUMP_MARKER: ({"ts": marker_ts,
                             "dust_pct_mc": _float(raw_marker.get("dust_pct_mc"),
                                                   None),
                             "baseline_pct": _float(
                                 raw_marker.get("baseline_pct"), None),
                             "baseline_ts": _int(raw_marker.get("baseline_ts"), 0),
                             "step": _int(raw_marker.get("step"), 0),
                             "baseline_src": str(
                                 raw_marker.get("baseline_src") or "")}
                            if marker_ts else {}),
    }


def _format_wib(timestamp: int) -> str:
    """WIB (UTC+7) saja, tanpa detik atau ketergantungan database timezone."""
    moment = datetime.fromtimestamp(_int(timestamp),
                                    tz=timezone(timedelta(hours=7)))
    return f"{moment:%Y-%m-%d %H:%M} WIB"


def _market_line(event: dict) -> list[str]:
    """Satu baris ``📈 Pasar`` dari konteks yang tersedia (boleh tidak ada)."""
    market = event.get("market")
    if not isinstance(market, dict) or not market:
        return []
    parts = []
    ratio = _float(market.get("volume_ratio"), None)
    if ratio is not None:
        parts.append(f"vol 4j {ratio:.2f}× avg 7d")
    change = _float(market.get("price_change_pct"), None)
    if change is not None:
        parts.append(f"harga {change:+.2f}%")
    return [f"📈 Pasar: " + " · ".join(parts)] if parts else []


def _pool_links(pools) -> list[tuple[str, str, str]]:
    """``[(emoji, label, url), …]`` 🌊 Meteora + 🦅 HawkFi per pool address."""
    links = []
    for raw in pools or []:
        pool = str(raw or "").strip()
        if not pool:
            continue
        links.append(("🌊", "Meteora", meteora_dlmm_url(pool)))
        links.append(("🦅", "HawkFi", hawkfi_meteora_url(pool)))
    return links


def _utf16_len(text: str) -> int:
    """Panjang dalam unit UTF-16 — satuan offset/length entity Bot API."""
    return len(str(text).encode("utf-16-le")) // 2



def build_alert_message(event: dict) -> tuple[str, list[dict]]:
    """``(teks, entities)`` pesan alert — link sebagai **hyperlink** Telegram.

    Baris link ditulis ``"<emoji> <label>"`` saja dan ``label`` diberi entity
    ``text_link`` (URL tidak muncul di teks; permintaan user 2026-09-09 — URL
    polos 44+ karakter membuat pesan panjang dan tidak enak dibaca). Judul ⚡
    diberi entity ``bold``. Semua offset/length dihitung dalam **UTF-16**
    (emoji = dua unit). Teks lain tetap literal tanpa ``parse_mode`` sehingga
    nama token/mint tidak bisa menjadi markup.

    Isi pesan = **delta terhadap patokan watchlist** (⚡ EARLY DUMP): patokan →
    angka sekarang, perubahan kumulatif, dan langkah 0,02% ke berapa — supaya
    user tahu ini kenaikan pertama atau lanjutan.
    """
    change = _float(event.get("change_pp"), 0.0) or 0.0
    baseline = float(event.get("previous_dust_pct_mc") or 0)
    current = float(event.get("current_dust_pct_mc") or 0)
    step_pct = _float(event.get("step_pct"), EARLY_DUMP_STEP_PCT)
    step = max(1, _int(event.get("step"), 1))
    minutes = _int(event.get("minutes_since_baseline"))
    title = str(event.get("title") or EARLY_DUMP_TITLE)

    dust_line = (f"📊 Dust: {baseline:.3f}% → {current:.3f}% MC "
                 f"({change:+.3f} pp · langkah {step}× {step_pct:g}%)")
    lines = [title, "", f"🪙 ${event.get('symbol') or '?'}", dust_line]
    if minutes > 0:
        lines.append(f"⏱️ {minutes} menit sejak masuk watchlist")
    lines.extend(_market_line(event))
    lines.extend([
        f"🕒 {_format_wib(event.get('current_ts') or time.time())}",
        f"📋 Mint: {event.get('mint') or '-'}",
    ])
    # URL tetap dari satu sumber (links.py), ter-encode, dan tidak
    # ditambahkan bila mint kosong. Link preview dimatikan di transport.
    links = list(token_links(event.get("mint")))
    links.extend(_pool_links(event.get("pool_addresses")))

    entities: list[dict] = []
    # Telegram tidak mendukung ukuran/warna font atau teks berkedip — judul
    # cukup ditebalkan.
    entities.append({"type": "bold", "offset": 0,
                      "length": _utf16_len(title)})
    offset = _utf16_len("\n".join(lines)) + 1
    for emoji, label, url in links:
        prefix = f"{emoji} "
        lines.append(prefix + label)
        entities.append({"type": "text_link",
                         "offset": offset + _utf16_len(prefix),
                         "length": _utf16_len(label),
                         "url": url})
        offset += _utf16_len(prefix + label) + 1  # + "\n"
    return "\n".join(lines), entities


def format_alert_message(event: dict) -> str:
    """Teks pesan alert (tanpa entities) — untuk log, tes, dan tampilan polos.

    Sama persis dengan teks yang dikirim :func:`send_telegram_alert`; baris
    link hanya berisi ``"<emoji> <label>"`` karena URL-nya ada di entity
    hyperlink (lihat :func:`build_alert_message`).
    """
    return build_alert_message(event)[0]


def _safe_transport_error(exc: Exception, token: str) -> str:
    """Render a transport error without leaking the bot token from its URL."""
    message = str(exc)
    return message.replace(token, "[REDACTED]") if token else message

# TODO(alerts): hormati 429 ``retry_after`` dari Bot API. Saat ini notifikasi yang
# kena rate-limit hanya di-log; event id-nya tidak dicatat sehingga dikirim ulang
# pada scan berikutnya (aman, tapi bukan backoff sebenarnya).
_TELEGRAM_TOKEN_KEYS = ("TELEGRAM_BOT_TOKEN", "telegram_bot_token")
_TELEGRAM_CHAT_KEYS = ("TELEGRAM_CHAT_ID", "telegram_chat_id")

def _first_secret(source, *names) -> str:
    """Nilai non-kosong pertama dari mapping (env / config / ``st.secrets``)."""
    getter = getattr(source, "get", None)
    for name in names:
        try:
            raw = getter(name, "") if callable(getter) else source[name]
        except Exception:  # noqa: BLE001 - key absen / secrets belum ada
            continue
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def _telegram_credentials() -> tuple[str, str]:
    """``(bot_token, chat_id)`` dari env → ``config.json`` → Streamlit secrets.

    Cron (GitHub Actions) cukup dengan env ``TELEGRAM_BOT_TOKEN`` /
    ``TELEGRAM_CHAT_ID``. Scan manual di dashboard **tidak** melihat secret
    GitHub: itu runtime terpisah, jadi kredensial harus dipasang lagi di
    Streamlit Cloud **Secrets** (atau ``config.json`` lokal). Nama key
    huruf besar (konvensi GitHub/DEPLOY) dan huruf kecil (TOML Streamlit
    lama) keduanya diterima. Sumber tambahan dibaca lazy + di-``try``:
    runner Actions hanya memasang ``requests`` + ``curl_cffi``.
    """
    token = _first_secret(os.environ, *_TELEGRAM_TOKEN_KEYS)
    target = _first_secret(os.environ, *_TELEGRAM_CHAT_KEYS)
    if token and target:
        return token, target
    try:
        import core  # config.json (semua key); import ringan tanpa streamlit
        cfg = core.load_config()
        token = token or _first_secret(cfg, *_TELEGRAM_TOKEN_KEYS)
        target = target or _first_secret(cfg, *_TELEGRAM_CHAT_KEYS)
    except Exception:  # noqa: BLE001 - kredensial bersifat opsional
        pass
    if token and target:
        return token, target
    try:
        import streamlit as st
        # core.load_config hanya memetakan key yang ada di default-nya ke
        # st.secrets, jadi dua key Telegram dibaca langsung dari secrets.
        token = token or _first_secret(st.secrets, *_TELEGRAM_TOKEN_KEYS)
        target = target or _first_secret(st.secrets, *_TELEGRAM_CHAT_KEYS)
    except Exception:  # noqa: BLE001 - di luar Streamlit tidak ada secrets
        pass
    return token, target


def send_telegram_message(text: str, *, bot_token: str | None = None,
                          chat_id: str | None = None, timeout: float = 10,
                          post: Callable | None = None,
                          entities: list[dict] | None = None) -> dict:
    """Send one Bot API request; never raise to the scanner.

    Native entities format literal text without parsing token names/mints as
    markup. Link previews are disabled to keep every notification compact.
    """
    if bot_token is None or chat_id is None:
        cfg_token, cfg_target = _telegram_credentials()
    else:
        cfg_token, cfg_target = "", ""
    token = (str(bot_token).strip() if bot_token is not None else cfg_token)
    target = (str(chat_id).strip() if chat_id is not None else cfg_target)
    if not token or not target:
        return {"ok": False, "skipped": True,
                "error": "Telegram credentials are not configured"}

    request_post = post or requests.post
    try:
        body = {"chat_id": target, "text": str(text),
                "link_preview_options": {"is_disabled": True}}
        if entities:
            body["entities"] = entities
        response = request_post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=body, timeout=timeout)
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
    """Kirim satu notifikasi: teks literal + entities (judul bold, hyperlink)."""
    message, entities = build_alert_message(event)
    return send_telegram_message(message, entities=entities or None)


def send_test_alert() -> dict:
    """Send a harmless deployment test using the same transport as alerts."""
    stamp = _format_wib(int(time.time()))
    return send_telegram_message(
        "✅ TEST ALERT HOLDER DUST\n"
        "📡 Telegram Wallet Depth aktif.\n"
        "🧪 Uji koneksi, bukan sinyal token.\n"
        f"🕒 {stamp}"
    )



def _reset_markers_on_readd(state: dict | None, meta) -> dict:
    """Buang marker episode bila token di-add **ulang** ke watchlist.

    ``meta`` entri watchlist membawa tanggal ``added``; marker
    (``early_dump``) yang lebih tua dari tanggal itu berasal dari periode
    watchlist sebelumnya dan tidak boleh dipakai — patokan 0,02% harus dihitung
    dari add yang baru, bukan dari dust lama periode sebelumnya. State lain
    tidak disentuh.
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
    marker = state.get(EARLY_DUMP_MARKER)
    if isinstance(marker, dict) and 0 < _int(marker.get("ts"), 0) < added:
        state[EARLY_DUMP_MARKER] = {}
    return state


def process_holder_alerts(analyses: dict | None, history_store: dict,
                          *, sender: Callable[[dict], dict] | None = None,
                          market_contexts=None,
                          context_provider: Callable[[str, dict], dict] | None = None,
                          mute_mints: set | None = None,
                          watchlist_meta: dict | None = None,
                          advance_anchors: bool = True) -> list[dict]:
    """Evaluate/send alerts, mutating state *before* history ingests new points.

    ``market_contexts`` (``{mint: context}``) dipakai bila konteks pasar sudah
    disiapkan pemanggil; selain itu ``context_provider(mint, analysis)``
    dipanggil lazy hanya untuk token yang **akan** dikirim notifikasinya.
    Setelah kirim berhasil, ``last_sent[kunci]`` diperbarui agar notifikasi
    sejenis tidak berulang dalam interval dedupnya.
    ``advance_anchors=False`` melewati pemajuan anchor wallet (peta
    ``baseline``/``rolling``) — dipakai scan ad-hoc 5 menit supaya peta
    milik scan FULL tidak digeser. ``watchlist_meta`` (``{mint: meta}``,
    opsional) dipakai untuk me-reset marker bila token baru di-add ulang ke
    watchlist.

    ``mute_mints`` = token yang **pesan Telegram-nya dimatikan user** (tombol
    on/off notif watchlist biasa, lihat :mod:`alert_settings`). Rule tetap
    dievaluasi dan state/marker tetap ditulis — hanya pengirimannya yang
    dilewati — supaya begitu notif dinyalakan lagi user tidak langsung
    dibanjiri marker lama yang sudah basi.

    Patokan ⚡ EARLY DUMP (angka dust saat token **pertama** masuk watchlist)
    diambil dari history store lewat :func:`add_baseline_for_mint` bila ada —
    bukan dari scan pertama yang kebetulan melihat token itu, karena lane
    watchlist biasa baru di-scan saat user menekan tombol scan.
    """
    sender = sender or send_telegram_alert
    contexts = market_contexts if isinstance(market_contexts, dict) else {}
    meta_map = watchlist_meta if isinstance(watchlist_meta, dict) else {}
    muted = {str(item) for item in (mute_mints or []) if item}
    tokens = history_store.setdefault("tokens", {})
    deliveries = []
    for mint, analysis in (analyses or {}).items():
        if not isinstance(analysis, dict):
            continue
        holders = analysis.get("holders") or {}
        # A provider outage can still return an analysis object with zero
        # fetched holders — or, worse, a *short* page (Helius down → GMGN
        # returning 20 holders, `truncated: False`). Dust wallets sit at the
        # tail of the holder list, so a short sample always yields dust 0.
        # Never advance anchors or emit a false alert from a scan whose holder
        # data is unusable.
        if not holders_usable(holders):
            continue
        slot = tokens.setdefault(mint, {"symbol": analysis.get("symbol") or "?",
                                        "cohort": {}, "points": []})
        old_state = slot.get(STATE_KEY) if isinstance(slot.get(STATE_KEY), dict) \
            else {}
        old_state = _reset_markers_on_readd(old_state, meta_map.get(mint))
        context = contexts.get(mint) if isinstance(contexts.get(mint), dict) \
            else None
        # Patokan ⚡ EARLY DUMP: angka dust saat token di-add, dari history.
        baseline_hint = add_baseline_for_mint(history_store, mint,
                                              meta_map.get(mint))
        events, next_state = evaluate_alert_events(
            mint, analysis, old_state, market_context=context,
            context_provider=context_provider, advance_anchors=advance_anchors,
            baseline_hint=baseline_hint)
        sent = list(next_state.get("sent_event_ids") or [])
        last_sent = dict(next_state.get("last_sent") or {})
        if mint in muted:
            # Notif dimatikan user untuk token ini: rule sudah dievaluasi dan
            # marker ikut tersimpan di next_state, jadi state tidak melompat
            # saat notif dinyalakan lagi. Yang dilewati hanya pengirimannya.
            for event in events:
                deliveries.append({"event": event,
                                   "delivery": {"ok": False, "skipped": True,
                                                "muted": True,
                                                "error": "telegram muted"}})
            slot[STATE_KEY] = compact_alert_state(next_state)
            continue
        delivered = False
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
                delivered = True
                sent.append(event["id"])
                last_sent[dedup_key(event)] = _int(event.get("current_ts"))
            elif not result.get("skipped"):
                print(f"WARN: Telegram alert {event['id']} gagal: "
                      f"{result.get('error') or 'unknown error'}", file=sys.stderr)
        if events and not delivered:
            # Semua pengiriman gagal (kredensial mati / Telegram down):
            # **jangan makan langkah 0,02%** yang jadi pemicu event ini.
            # Langkah dikembalikan ke posisi sebelum evaluasi supaya scan
            # berikutnya mencoba lagi dengan pesan yang sama.
            slot[STATE_KEY] = compact_alert_state(_restore_step(old_state,
                                                               next_state))
            continue
        next_state["sent_event_ids"] = sent[-MAX_SENT_EVENT_IDS:]
        next_state["last_sent"] = last_sent
        slot[STATE_KEY] = compact_alert_state(next_state)
    return deliveries


def _restore_step(old_state: dict, next_state: dict) -> dict:
    """Kembalikan penghitung langkah ⚡ ke nilai sebelum evaluasi (retry).

    Dipakai saat **semua** notifikasi satu token gagal dikirim: pesan yang
    belum sampai ke Telegram tidak boleh menghabiskan langkah 0,02%-nya, kalau
    tidak user kehilangan kabar kenaikan itu untuk selamanya (langkah hanya
    naik). State lain (patokan, anchor wallet, event id) tetap dibawa.
    """
    merged = dict(next_state or {})
    marker = merged.get(EARLY_DUMP_MARKER)
    if not isinstance(marker, dict) or not marker:
        return merged
    old_marker = (old_state or {}).get(EARLY_DUMP_MARKER)
    old_marker = old_marker if isinstance(old_marker, dict) else {}
    restored = dict(marker)
    # Patokan tetap dipakai (jangan dipasang ulang dari scan berikutnya),
    # hanya penghitung langkahnya yang mundur.
    restored["step"] = _int(old_marker.get("step"), 0)
    merged[EARLY_DUMP_MARKER] = restored
    return merged
