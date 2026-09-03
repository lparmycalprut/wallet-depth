# -*- coding: utf-8 -*-
"""Kronologi holder antar-scan FULL — deterministik, tanpa LLM.

Membandingkan snapshot wallet bounded dari scan FULL pertama (baseline
immutable) dengan scan FULL berikutnya. Pergerakan dihitung dari
**balance token**, bukan nilai USD, supaya kenaikan harga tidak dianggap
pembelian.

Payload sengaja dibatasi: yang disimpan adalah sampel wallet + ringkasan
interval, bukan respons Helius mentah.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

from links import solscan_account_url
from solscan_holders import (CATEGORY_ORDER, DEPTH_BUCKETS, DUST_CATEGORY,
                             EXITED_CATEGORY, UNKNOWN_CATEGORY, holder_category)

# --- Batas payload (jelas & deterministik) ---------------------------------
MAX_SNAPSHOT_WALLETS = 400
MAX_MOVEMENTS_PER_INTERVAL = 40
MAX_CHRONOLOGY_INTERVALS = 24
MAX_TOP_PER_CATEGORY = 8
NEAR_BOUNDARY_FRAC = 0.20

# Status remote (holder-live) lebih ketat supaya JSON dashboard tetap kecil.
STATUS_MAX_WALLETS = 200
STATUS_MAX_MOVEMENTS = 20
STATUS_MAX_INTERVALS = 12

# Toleransi float vs perubahan nyata.
BALANCE_EPS = 1e-9
REL_NOISE = 1e-6          # di bawah ini dianggap noise float
REL_SIGNIFICANT = 0.01    # 1% — "signifikan" untuk wallet yang tetap di kategori

# Pencilan non-wallet (disalin kecil agar tidak impor sirkular).
NOISE_TAGS = frozenset(("sandwich_bot", "mev_bot", "mev"))

SNAPSHOT_AWAL_MESSAGE = (
    "Ini adalah snapshot awal. Data pembanding belum cukup untuk membuat "
    "kronologi perubahan holder. Jalankan Scan holder FULL berikutnya untuk "
    "melihat wallet yang bertambah, berkurang, berpindah kategori, atau keluar."
)
NO_SIGNIFICANT_MOVE = (
    "Belum ada perpindahan kategori holder yang signifikan sejak snapshot "
    "sebelumnya."
)
SAMPLED_NOTE = (
    "Detail wallet adalah sampel terbatas, bukan daftar lengkap."
)
TRUNCATED_NOTE = (
    "Scan terbaru terpotong (truncated); wallet yang tidak teramati belum "
    "dapat dipastikan keluar total."
)
PRICE_MISSING_NOTE = (
    "Harga atau market cap tidak tersedia pada salah satu snapshot, jadi "
    "nilai USD / dust % MC tidak dapat dibandingkan secara penuh."
)
SELL_VS_TRANSFER_NOTE = (
    "Perubahan saldo token saja tidak dapat membedakan swap dengan transfer. "
    "Buka Solscan untuk verifikasi."
)

_KIND_PRIORITY = (
    "dust_grew_out",
    "dust_price_exit",
    "shrank_to_dust",
    "category_up",
    "category_down",
    "exited_total",
    "unobserved",
    "new_wallet",
    "increased_same",
    "decreased_same",
)


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
    # Solana Base58 case-sensitive; hanya trim whitespace.
    return str(value or "").strip()


def _pool_set(pool_addresses) -> set[str]:
    return {str(item or "").strip().lower()
            for item in (pool_addresses or []) if item}


def shorten_address(address) -> str:
    addr = _address(address)
    if len(addr) <= 10:
        return addr
    return f"{addr[:4]}...{addr[-4:]}"


def format_wib(ts, *, with_tz: bool = True) -> str:
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(hours=7)
    text = when.strftime("%d %b %H:%M")
    return f"{text} WIB" if with_tz else text


def format_duration(seconds) -> str:
    try:
        span = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if span < 0:
        return "—"
    if span < 60:
        return "kurang dari 1 menit"
    minutes = span // 60
    hours = minutes // 60
    days = hours // 24
    hours %= 24
    minutes %= 60
    parts = []
    if days:
        parts.append(f"{days} hari")
    if hours:
        parts.append(f"{hours} jam")
    if minutes and not days:
        parts.append(f"{minutes} menit")
    return " ".join(parts) or "—"


def fmt_id_decimal(value, digits: int = 2) -> str:
    number = _float(value, None)
    if number is None:
        return "—"
    return f"{number:.{digits}f}".replace(".", ",")


def fmt_id_int(value) -> str:
    number = _float(value, None)
    if number is None:
        return "—"
    return f"{int(round(number)):,}".replace(",", ".")


def solscan_link(address) -> str:
    addr = _address(address)
    return solscan_account_url(addr) if addr else ""


def _is_noise(row: dict) -> bool:
    tags = {str(tag or "").strip().lower() for tag in (row.get("tags") or [])}
    tags.update(str(tag or "").strip().lower()
                for tag in (row.get("maker_token_tags") or []))
    wallet_tag = str(row.get("wallet_tag") or "").strip().lower()
    if wallet_tag:
        tags.add(wallet_tag)
    return bool(tags & NOISE_TAGS)


def is_pure_wallet(row: dict | None, pool_addresses=None) -> bool:
    """True hanya untuk wallet murni (bukan LP/pool/noise)."""
    if not isinstance(row, dict) or not row.get("is_wallet"):
        return False
    addr = _address(row.get("address"))
    if not addr:
        return False
    if addr.lower() in _pool_set(pool_addresses):
        return False
    if _is_noise(row):
        return False
    return True


def _category_rank(label: str) -> int:
    try:
        return CATEGORY_ORDER.index(label)
    except ValueError:
        return -1


def _near_boundary(usd: float) -> bool:
    if usd <= 0:
        return False
    for _label, _lo, hi in DEPTH_BUCKETS:
        if hi is None:
            continue
        if hi <= 0:
            continue
        if abs(usd - hi) / hi <= NEAR_BOUNDARY_FRAC:
            return True
    return False


def _balance_move(before: float, after: float) -> str:
    """``up`` / ``down`` / ``flat`` setelah toleransi float."""
    noise = max(BALANCE_EPS, abs(before) * REL_NOISE)
    if after > before + noise:
        return "up"
    if after + noise < before:
        return "down"
    return "flat"


def _significant_balance_move(before: float, after: float) -> bool:
    threshold = max(BALANCE_EPS, abs(before) * REL_SIGNIFICANT)
    return abs(after - before) > threshold


def _wallet_record(balance: float, usd: float) -> dict:
    category = holder_category(usd, balance)
    return {
        "balance": float(balance),
        "usd": float(usd),
        "category": category,
        "dust": category == DUST_CATEGORY,
    }


def wallet_records(holders: Iterable[dict] | None,
                   *, pool_addresses=None) -> dict[str, dict]:
    """Peta address → {balance, usd, category, dust} untuk wallet murni."""
    rows: dict[str, dict] = {}
    for raw in holders or []:
        if not is_pure_wallet(raw, pool_addresses):
            continue
        addr = _address(raw.get("address"))
        balance = _float(raw.get("balance"), 0.0) or 0.0
        usd = _float(raw.get("usd_value", raw.get("usd")), 0.0) or 0.0
        if balance < 0:
            balance = 0.0
        old = rows.get(addr)
        if old is None or balance > old["balance"]:
            rows[addr] = _wallet_record(balance, usd)
    return rows


def _select_addresses(records: dict[str, dict], *, tracked=None,
                      previous=None, limit: int = MAX_SNAPSHOT_WALLETS
                      ) -> tuple[list[str], bool]:
    limit = max(1, int(limit))
    if len(records) <= limit:
        return sorted(records), False

    groups: list[list[str]] = []

    tracked_clean: list[str] = []
    seen_tracked: set[str] = set()
    for raw in tracked or []:
        addr = _address(raw)
        if addr and addr not in seen_tracked:
            tracked_clean.append(addr)
            seen_tracked.add(addr)
    groups.append([addr for addr in tracked_clean if addr in records])

    dust = [addr for addr, rec in records.items() if rec.get("dust")]
    dust.sort(key=lambda addr: (-records[addr]["usd"], addr))
    groups.append(dust)

    near = [addr for addr, rec in records.items()
            if _near_boundary(rec.get("usd") or 0.0)]
    near.sort(key=lambda addr: (-records[addr]["usd"], addr))
    groups.append(near)

    prev_map = previous if isinstance(previous, dict) else {}
    if prev_map:
        changes = []
        for addr, rec in records.items():
            prev = prev_map.get(addr)
            if not isinstance(prev, dict):
                continue
            before = _float(prev.get("balance"), 0.0) or 0.0
            delta = abs(rec["balance"] - before)
            changes.append((delta, addr))
        changes.sort(key=lambda item: (-item[0], item[1]))
        groups.append([addr for _delta, addr in changes])

    per_cat: list[str] = []
    by_cat: dict[str, list[str]] = {}
    for addr, rec in records.items():
        by_cat.setdefault(str(rec.get("category") or UNKNOWN_CATEGORY),
                          []).append(addr)
    for cat in CATEGORY_ORDER:
        addrs = by_cat.get(cat) or []
        addrs.sort(key=lambda addr: (-records[addr]["usd"], addr))
        per_cat.extend(addrs[:MAX_TOP_PER_CATEGORY])
    for cat, addrs in by_cat.items():
        if cat in CATEGORY_ORDER:
            continue
        addrs.sort(key=lambda addr: (-records[addr]["usd"], addr))
        per_cat.extend(addrs[:MAX_TOP_PER_CATEGORY])
    groups.append(per_cat)

    rest = sorted(records, key=lambda addr: (-records[addr]["usd"], addr))
    groups.append(rest)

    selected: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for addr in group:
            if addr in seen or addr not in records:
                continue
            selected.append(addr)
            seen.add(addr)
            if len(selected) >= limit:
                return selected, True
    return selected, len(records) > len(selected)


def empty_wallet_snapshot(ts: int | None = None, **metrics) -> dict:
    payload = {
        "ts": _int(ts or time.time()),
        "price": _float(metrics.get("price"), None),
        "mc": _float(metrics.get("mc", metrics.get("market_cap")), None),
        "holder_count": _int(metrics.get("holder_count")),
        "dust_count": _int(metrics.get("dust_count")),
        "dust_pct_mc": _float(metrics.get("dust_pct_mc"), None),
        "truncated": bool(metrics.get("truncated")),
        "sampled": bool(metrics.get("sampled")),
        "wallets_seen": _int(metrics.get("wallets_seen")),
        "wallets": {},
    }
    return payload


def compact_wallet_snapshot(snapshot: dict | None, *,
                            max_wallets: int = MAX_SNAPSHOT_WALLETS) -> dict:
    """Rapikan snapshot wallet dan terapkan batas address."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    raw_wallets = snapshot.get("wallets")
    records: dict[str, dict] = {}
    if isinstance(raw_wallets, dict):
        items = raw_wallets.items()
    elif isinstance(raw_wallets, list):
        items = ((_address(row.get("address")), row)
                 for row in raw_wallets if isinstance(row, dict))
    else:
        items = ()
    for addr, rec in items:
        addr = _address(addr)
        if not addr or not isinstance(rec, dict):
            continue
        balance = _float(rec.get("balance"), 0.0) or 0.0
        usd = _float(rec.get("usd", rec.get("usd_value")), 0.0) or 0.0
        record = _wallet_record(balance, usd)
        if rec.get("category"):
            record["category"] = str(rec.get("category"))
            record["dust"] = record["category"] == DUST_CATEGORY
        records[addr] = record

    tracked = list(records)
    selected, sampled_now = _select_addresses(
        records, tracked=tracked, limit=max_wallets)
    sampled = bool(snapshot.get("sampled")) or sampled_now
    return {
        "ts": _int(snapshot.get("ts") or time.time()),
        "price": _float(snapshot.get("price"), None),
        "mc": _float(snapshot.get("mc", snapshot.get("market_cap")), None),
        "holder_count": _int(snapshot.get("holder_count")),
        "dust_count": _int(snapshot.get("dust_count")),
        "dust_pct_mc": _float(snapshot.get("dust_pct_mc"), None),
        "truncated": bool(snapshot.get("truncated")),
        "sampled": sampled,
        "wallets_seen": max(_int(snapshot.get("wallets_seen"), len(records)),
                            len(records)),
        "wallets": {addr: records[addr] for addr in selected if addr in records},
    }


def build_chrono_snapshot(holders: Iterable[dict] | None, *,
                          tracked_addresses=None,
                          previous_wallets=None,
                          pool_addresses=None,
                          ts: int | None = None,
                          price=None, market_cap=None,
                          dust_pct_mc=None,
                          holder_count=None, dust_count=None,
                          truncated: bool = False,
                          max_wallets: int = MAX_SNAPSHOT_WALLETS) -> dict:
    """Snapshot bounded untuk perbandingan scan FULL berikutnya."""
    records = wallet_records(holders, pool_addresses=pool_addresses)
    previous = {}
    if isinstance(previous_wallets, dict):
        inner = previous_wallets.get("wallets")
        previous = inner if isinstance(inner, dict) else previous_wallets
    selected, sampled = _select_addresses(
        records, tracked=tracked_addresses, previous=previous,
        limit=max_wallets)
    return {
        "ts": _int(ts or time.time()),
        "price": _float(price, None),
        "mc": _float(market_cap, None),
        "holder_count": _int(holder_count, len(records)),
        "dust_count": _int(dust_count),
        "dust_pct_mc": _float(dust_pct_mc, None),
        "truncated": bool(truncated),
        "sampled": bool(sampled),
        "wallets_seen": len(records),
        "wallets": {addr: records[addr] for addr in selected},
    }


def snapshot_from_analysis(analysis: dict | None,
                           now: int | None = None) -> dict:
    """Ambil/rapikan ``holders.chrono_snapshot`` dari hasil ``analyze_token``."""
    analysis = analysis or {}
    holders = analysis.get("holders") if isinstance(analysis.get("holders"),
                                                    dict) else {}
    raw = holders.get("chrono_snapshot")
    stamp = _int(now or analysis.get("analyzed_at") or time.time())
    if isinstance(raw, dict) and (raw.get("wallets") or raw.get("wallets_seen")):
        snap = compact_wallet_snapshot(raw)
        snap["ts"] = _int(snap.get("ts") or stamp)
        if snap.get("price") is None:
            snap["price"] = _float(analysis.get("price"), None)
        if snap.get("mc") is None:
            snap["mc"] = _float(analysis.get("marketcap"), None)
        if not snap.get("holder_count"):
            snap["holder_count"] = _int(holders.get("wallets_analyzed"))
        if not snap.get("dust_count"):
            snap["dust_count"] = _int(holders.get("dust_count"))
        if snap.get("dust_pct_mc") is None:
            snap["dust_pct_mc"] = _float(holders.get("dust_pct_mc"), None)
        if "truncated" not in raw:
            snap["truncated"] = bool(holders.get("truncated"))
        return snap
    return empty_wallet_snapshot(
        stamp,
        price=analysis.get("price"),
        mc=analysis.get("marketcap"),
        holder_count=holders.get("wallets_analyzed"),
        dust_count=holders.get("dust_count"),
        dust_pct_mc=holders.get("dust_pct_mc"),
        truncated=holders.get("truncated"),
    )


def _metrics_from_detail(detail: dict | None, fallback: dict | None = None
                         ) -> dict:
    detail = detail if isinstance(detail, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    return {
        "ts": _int(detail.get("ts") or fallback.get("ts")),
        "holder_count": _int(detail.get("holder_count"),
                             _int(fallback.get("holder_count"))),
        "dust_count": _int(detail.get("dust_count"),
                           _int(fallback.get("dust_count"))),
        "dust_pct_mc": _float(detail.get("dust_pct_mc"),
                              _float(fallback.get("dust_pct_mc"), None)),
        "price": _float(detail.get("price"),
                        _float(fallback.get("price"), None)),
        "mc": _float(detail.get("mc"), _float(fallback.get("mc"), None)),
        "truncated": bool(detail.get("truncated", fallback.get("truncated"))),
        "sampled": bool(detail.get("sampled", fallback.get("sampled"))),
    }


def _interpretation(kind: str, *, from_cat: str, to_cat: str) -> str:
    if kind == "dust_grew_out":
        return (f"Wallet menambah muatan dan berpindah dari Dust ke {to_cat}.")
    if kind == "dust_price_exit":
        return ("Wallet keluar dari Dust terutama karena perubahan harga; "
                "tidak ada kenaikan balance token yang signifikan.")
    if kind == "exited_total":
        return ("Saldo token menjadi 0 / wallet keluar total. Ini dapat "
                "berarti jual seluruh holding atau transfer keluar; buka "
                "Solscan untuk verifikasi.")
    if kind == "unobserved":
        return ("Wallet tidak teramati pada snapshot terbaru; status keluar "
                "total belum dapat dipastikan.")
    if kind == "shrank_to_dust":
        return (f"Wallet mengurangi muatan dan turun dari {from_cat} ke Dust.")
    if kind == "new_wallet":
        return "Wallet baru teramati pada snapshot terbaru."
    if kind == "increased_same":
        return (f"Wallet tetap di {to_cat} tetapi balance token meningkat.")
    if kind == "decreased_same":
        return (f"Wallet tetap di {to_cat} tetapi balance token menurun.")
    if kind == "category_up":
        return (f"Wallet menambah muatan dan berpindah dari {from_cat} "
                f"ke {to_cat}.")
    if kind == "category_down":
        return (f"Wallet mengurangi muatan dan turun dari {from_cat} "
                f"ke {to_cat}.")
    return "Perubahan wallet teramati pada snapshot terbaru."


def _movement_dict(address: str, *, kind: str, before: dict | None,
                   after: dict | None) -> dict:
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    bal0 = _float(before.get("balance"), 0.0) or 0.0
    bal1 = _float(after.get("balance"), 0.0) or 0.0
    if kind == "unobserved":
        bal1 = None
    delta = None if bal1 is None else (bal1 - bal0)
    delta_pct = None
    if delta is not None and bal0 > BALANCE_EPS:
        delta_pct = delta / bal0 * 100.0
    from_cat = str(before.get("category") or EXITED_CATEGORY)
    if kind == "new_wallet":
        from_cat = "—"
    to_cat = str(after.get("category") or EXITED_CATEGORY)
    if kind == "unobserved":
        to_cat = "Tidak teramati"
    if kind == "exited_total":
        to_cat = EXITED_CATEGORY
    usd0 = _float(before.get("usd"), None)
    usd1 = None if kind == "unobserved" else _float(after.get("usd"), None)
    return {
        "address": address,
        "from_category": from_cat,
        "to_category": to_cat,
        "balance_before": bal0,
        "balance_after": bal1,
        "delta_balance": delta,
        "delta_pct": delta_pct,
        "usd_before": usd0,
        "usd_after": usd1,
        "kind": kind,
        "interpretation": _interpretation(kind, from_cat=from_cat,
                                          to_cat=to_cat),
        "solscan": solscan_link(address),
    }


def classify_wallet_movement(address: str, before: dict | None,
                             after: dict | None, *,
                             current_truncated: bool) -> dict | None:
    """Klasifikasi satu wallet. ``None`` jika tidak ada pergerakan relevan."""
    addr = _address(address)
    if not addr:
        return None
    before = before if isinstance(before, dict) else None
    after = after if isinstance(after, dict) else None
    before_bal = _float((before or {}).get("balance"), 0.0) or 0.0
    after_bal = _float((after or {}).get("balance"), 0.0) or 0.0
    had_before = before is not None and before_bal > BALANCE_EPS

    if after is None:
        if not had_before:
            return None
        kind = "unobserved" if current_truncated else "exited_total"
        return _movement_dict(addr, kind=kind, before=before, after=None)

    if after_bal <= BALANCE_EPS:
        if not had_before:
            return None
        return _movement_dict(addr, kind="exited_total", before=before,
                              after=after)

    if not had_before:
        return _movement_dict(addr, kind="new_wallet", before=None, after=after)

    move = _balance_move(before_bal, after_bal)
    from_cat = str(before.get("category") or UNKNOWN_CATEGORY)
    to_cat = str(after.get("category") or UNKNOWN_CATEGORY)
    was_dust = bool(before.get("dust") or from_cat == DUST_CATEGORY)
    now_dust = bool(after.get("dust") or to_cat == DUST_CATEGORY)

    if was_dust and not now_dust and to_cat not in (EXITED_CATEGORY,
                                                    UNKNOWN_CATEGORY):
        if move == "up":
            return _movement_dict(addr, kind="dust_grew_out", before=before,
                                  after=after)
        if move == "flat":
            return _movement_dict(addr, kind="dust_price_exit", before=before,
                                  after=after)
        # Balance turun tetapi USD naik menembus dust — tetap karena harga.
        return _movement_dict(addr, kind="dust_price_exit", before=before,
                              after=after)

    if (not was_dust and now_dust and move == "down"
            and from_cat not in (EXITED_CATEGORY, DUST_CATEGORY, "—")):
        return _movement_dict(addr, kind="shrank_to_dust", before=before,
                              after=after)

    if from_cat != to_cat and to_cat != UNKNOWN_CATEGORY:
        rank0 = _category_rank(from_cat)
        rank1 = _category_rank(to_cat)
        if rank0 >= 0 and rank1 >= 0 and rank1 > rank0:
            kind = "category_up" if move == "up" else (
                "dust_price_exit" if was_dust and move == "flat"
                else "category_up")
            if move != "up":
                # Naik kategori tanpa naik balance = efek harga, bukan beli.
                row = _movement_dict(addr, kind="dust_price_exit"
                                     if was_dust else "category_up",
                                     before=before, after=after)
                if not was_dust:
                    row["kind"] = "category_up"
                    row["interpretation"] = (
                        f"Wallet berpindah dari {from_cat} ke {to_cat} "
                        "terutama karena perubahan harga; tidak ada kenaikan "
                        "balance token yang signifikan.")
                return row
            return _movement_dict(addr, kind="category_up", before=before,
                                  after=after)
        if rank0 >= 0 and rank1 >= 0 and rank1 < rank0:
            if move == "down":
                return _movement_dict(addr, kind="category_down",
                                      before=before, after=after)
            row = _movement_dict(addr, kind="category_down", before=before,
                                 after=after)
            row["interpretation"] = (
                f"Wallet berpindah dari {from_cat} ke {to_cat} terutama "
                "karena perubahan harga; balance token tidak menurun "
                "signifikan.")
            return row

    if from_cat == to_cat and _significant_balance_move(before_bal, after_bal):
        kind = "increased_same" if move == "up" else (
            "decreased_same" if move == "down" else None)
        if kind:
            return _movement_dict(addr, kind=kind, before=before, after=after)
    return None


def _count_template() -> dict:
    return {
        "increased": 0,
        "decreased": 0,
        "new_wallets": 0,
        "exited_total": 0,
        "unobserved": 0,
        "dust_grew_out": 0,
        "dust_price_exit": 0,
        "shrank_to_dust": 0,
        "category_moves": 0,
        "same_increased": 0,
        "same_decreased": 0,
        "compared_wallets": 0,
    }


def _apply_count(counts: dict, movement: dict, *, had_before: bool) -> None:
    kind = movement.get("kind")
    if kind == "new_wallet":
        counts["new_wallets"] += 1
        return
    if kind == "unobserved":
        counts["unobserved"] += 1
        return
    if kind == "exited_total":
        counts["exited_total"] += 1
        counts["decreased"] += 1
        return
    delta = _float(movement.get("delta_balance"), None)
    if had_before and delta is not None:
        if delta > BALANCE_EPS:
            counts["increased"] += 1
        elif delta < -BALANCE_EPS:
            counts["decreased"] += 1
    if kind == "dust_grew_out":
        counts["dust_grew_out"] += 1
        counts["category_moves"] += 1
    elif kind == "dust_price_exit":
        counts["dust_price_exit"] += 1
        counts["category_moves"] += 1
    elif kind == "shrank_to_dust":
        counts["shrank_to_dust"] += 1
        counts["category_moves"] += 1
    elif kind in ("category_up", "category_down"):
        counts["category_moves"] += 1
    elif kind == "increased_same":
        counts["same_increased"] += 1
    elif kind == "decreased_same":
        counts["same_decreased"] += 1


def _sort_movements(rows: list[dict]) -> list[dict]:
    order = {kind: index for index, kind in enumerate(_KIND_PRIORITY)}

    def key(row):
        delta = _float(row.get("delta_balance"), 0.0) or 0.0
        return (order.get(row.get("kind"), 99), -abs(delta),
                str(row.get("address") or ""))

    return sorted(rows, key=key)


def compare_snapshots(previous: dict | None, current: dict | None, *,
                      previous_metrics=None, current_metrics=None
                      ) -> dict:
    """Bandingkan dua snapshot wallet → satu interval kronologi."""
    previous = compact_wallet_snapshot(previous) if previous else empty_wallet_snapshot()
    current = compact_wallet_snapshot(current) if current else empty_wallet_snapshot()
    before_wallets = previous.get("wallets") or {}
    after_wallets = current.get("wallets") or {}
    truncated = bool(current.get("truncated"))
    sampled = bool(previous.get("sampled") or current.get("sampled"))

    addresses = set(before_wallets) | set(after_wallets)
    counts = _count_template()
    movements: list[dict] = []
    for addr in addresses:
        before = before_wallets.get(addr)
        after = after_wallets.get(addr)
        had_before = isinstance(before, dict) and (
            _float(before.get("balance"), 0.0) or 0.0) > BALANCE_EPS
        if had_before and after is not None:
            counts["compared_wallets"] += 1
        row = classify_wallet_movement(
            addr, before, after, current_truncated=truncated)
        if not row:
            continue
        _apply_count(counts, row, had_before=had_before)
        movements.append(row)

    movements = _sort_movements(movements)[:MAX_MOVEMENTS_PER_INTERVAL]
    from_metrics = _metrics_from_detail(previous_metrics, previous)
    to_metrics = _metrics_from_detail(current_metrics, current)
    return {
        "from_ts": from_metrics.get("ts") or previous.get("ts"),
        "to_ts": to_metrics.get("ts") or current.get("ts"),
        "from_metrics": from_metrics,
        "to_metrics": to_metrics,
        "counts": counts,
        "movements": movements,
        "truncated": truncated,
        "sampled": sampled,
        "complete": not truncated,
    }


def compact_interval(interval: dict | None, *,
                     max_movements: int = MAX_MOVEMENTS_PER_INTERVAL) -> dict:
    interval = interval if isinstance(interval, dict) else {}
    movements = [row for row in (interval.get("movements") or [])
                 if isinstance(row, dict) and _address(row.get("address"))]
    movements = _sort_movements(movements)[:max(1, int(max_movements))]
    counts = dict(_count_template())
    incoming = interval.get("counts") if isinstance(interval.get("counts"),
                                                    dict) else {}
    for key in counts:
        counts[key] = _int(incoming.get(key))
    return {
        "from_ts": _int(interval.get("from_ts")),
        "to_ts": _int(interval.get("to_ts")),
        "from_metrics": _metrics_from_detail(interval.get("from_metrics")),
        "to_metrics": _metrics_from_detail(interval.get("to_metrics")),
        "counts": counts,
        "movements": movements,
        "truncated": bool(interval.get("truncated")),
        "sampled": bool(interval.get("sampled")),
        "complete": bool(interval.get("complete",
                                      not interval.get("truncated"))),
    }


def compact_chronology(chrono: dict | None, *,
                       max_wallets: int = MAX_SNAPSHOT_WALLETS,
                       max_movements: int = MAX_MOVEMENTS_PER_INTERVAL,
                       max_intervals: int = MAX_CHRONOLOGY_INTERVALS) -> dict:
    chrono = chrono if isinstance(chrono, dict) else {}
    intervals = [compact_interval(row, max_movements=max_movements)
                 for row in (chrono.get("intervals") or [])
                 if isinstance(row, dict)]
    intervals = sorted(intervals, key=lambda row: (
        _int(row.get("from_ts")), _int(row.get("to_ts"))))
    if len(intervals) > max_intervals:
        intervals = intervals[-max_intervals:]
    return {
        "baseline_wallets": compact_wallet_snapshot(
            chrono.get("baseline_wallets"), max_wallets=max_wallets),
        "latest_wallets": compact_wallet_snapshot(
            chrono.get("latest_wallets"), max_wallets=max_wallets),
        "intervals": intervals,
    }


def compact_chronology_for_status(chrono: dict | None) -> dict:
    """Versi ringkas untuk ``holder_status`` (survive redeploy, tetap bounded)."""
    packed = compact_chronology(
        chrono, max_wallets=STATUS_MAX_WALLETS,
        max_movements=STATUS_MAX_MOVEMENTS,
        max_intervals=STATUS_MAX_INTERVALS)
    # Jangan kirim peta wallet penuh ke dashboard — cukup interval + flag.
    for key in ("baseline_wallets", "latest_wallets"):
        snap = packed.get(key) or {}
        packed[key] = {
            "ts": snap.get("ts"),
            "price": snap.get("price"),
            "mc": snap.get("mc"),
            "holder_count": snap.get("holder_count"),
            "dust_count": snap.get("dust_count"),
            "dust_pct_mc": snap.get("dust_pct_mc"),
            "truncated": snap.get("truncated"),
            "sampled": snap.get("sampled"),
            "wallets_seen": snap.get("wallets_seen"),
            "wallets": snap.get("wallets") or {},
        }
    return packed


def empty_chronology() -> dict:
    return {
        "baseline_wallets": empty_wallet_snapshot(),
        "latest_wallets": empty_wallet_snapshot(),
        "intervals": [],
    }


def tracked_addresses(chrono: dict | None) -> list[str]:
    """Address yang harus diprioritaskan pada scan FULL berikutnya."""
    chrono = chrono if isinstance(chrono, dict) else {}
    out: list[str] = []
    seen: set[str] = set()
    for key in ("latest_wallets", "baseline_wallets"):
        wallets = ((chrono.get(key) or {}).get("wallets")
                   if isinstance(chrono.get(key), dict) else {}) or {}
        for addr in wallets:
            cleaned = _address(addr)
            if cleaned and cleaned not in seen:
                out.append(cleaned)
                seen.add(cleaned)
            if len(out) >= MAX_SNAPSHOT_WALLETS:
                return out
    return out


def _sum_counts(intervals: Iterable[dict]) -> dict:
    total = _count_template()
    for interval in intervals or []:
        counts = (interval or {}).get("counts") or {}
        for key in total:
            total[key] += _int(counts.get(key))
    return total


def _has_category_move(counts: dict) -> bool:
    return any(_int(counts.get(key)) > 0 for key in (
        "dust_grew_out", "dust_price_exit", "shrank_to_dust",
        "category_moves"))


def cumulative_narrative(baseline: dict | None, latest: dict | None,
                         counts: dict, *, sampled: bool = False,
                         truncated: bool = False) -> str:
    """Paragraf ringkasan Bahasa Indonesia dari baseline → terbaru."""
    base_dust = _float((baseline or {}).get("dust_pct_mc"), None)
    now_dust = _float((latest or {}).get("dust_pct_mc"), None)
    parts = []
    if base_dust is not None and now_dust is not None:
        direction = "turun" if now_dust < base_dust else (
            "naik" if now_dust > base_dust else "tetap")
        parts.append(
            f"Sejak snapshot awal, dust {direction} dari "
            f"{fmt_id_decimal(base_dust)}% MC menjadi "
            f"{fmt_id_decimal(now_dust)}% MC.")
    elif base_dust is None or now_dust is None:
        parts.append(PRICE_MISSING_NOTE)

    sample_prefix = ("Dari sampel wallet yang dapat dibandingkan, "
                     if sampled else "Dari wallet yang dapat dibandingkan, ")
    bits = []
    grew = _int(counts.get("dust_grew_out"))
    if grew:
        bits.append(f"{grew} wallet dust menambah balance dan naik ke "
                    "kategori lebih besar")
    price_exit = _int(counts.get("dust_price_exit"))
    if price_exit:
        bits.append(f"{price_exit} wallet keluar dari Dust terutama karena "
                    "perubahan harga")
    shrank = _int(counts.get("shrank_to_dust"))
    if shrank:
        bits.append(f"{shrank} wallet turun ke Dust")
    exited = _int(counts.get("exited_total"))
    unobs = _int(counts.get("unobserved"))
    if exited or unobs:
        bits.append(
            f"{exited + unobs} wallet menjadi saldo nol/tidak ditemukan")
    new_n = _int(counts.get("new_wallets"))
    if new_n:
        bits.append(f"{new_n} wallet baru teramati")
    if bits:
        parts.append(sample_prefix + ", ".join(bits) + ".")
    elif not _has_category_move(counts):
        parts.append(NO_SIGNIFICANT_MOVE)

    if truncated:
        parts.append(TRUNCATED_NOTE)
    elif sampled:
        parts.append(SAMPLED_NOTE)
    parts.append(SELL_VS_TRANSFER_NOTE)
    return " ".join(p for p in parts if p)


def interval_narrative(interval: dict | None) -> str:
    interval = interval or {}
    counts = interval.get("counts") or {}
    sampled = bool(interval.get("sampled"))
    truncated = bool(interval.get("truncated"))
    if not _has_category_move(counts) and not _int(counts.get("new_wallets")) \
            and not _int(counts.get("exited_total")) \
            and not _int(counts.get("unobserved")) \
            and not _int(counts.get("same_increased")) \
            and not _int(counts.get("same_decreased")):
        text = NO_SIGNIFICANT_MOVE
    else:
        text = cumulative_narrative(
            interval.get("from_metrics"), interval.get("to_metrics"),
            counts, sampled=sampled, truncated=truncated)
        # cumulative_narrative always appends sell-vs-transfer; keep one copy
        # at the section level by stripping the trailing note here? Keep it —
        # each expander should stand alone.
        return text
    notes = []
    if truncated:
        notes.append(TRUNCATED_NOTE)
    if sampled:
        notes.append(SAMPLED_NOTE)
    return " ".join([text, *notes]).strip()


def interval_title(interval: dict | None) -> str:
    interval = interval or {}
    start = format_wib(interval.get("from_ts"), with_tz=False)
    end = format_wib(interval.get("to_ts"), with_tz=False)
    return f"{start} → {end}"


def movement_table_rows(movements: Iterable[dict] | None) -> list[dict]:
    """Baris tabel UI: address dipendekkan, link Solscan memakai address penuh."""
    rows = []
    for raw in movements or []:
        if not isinstance(raw, dict):
            continue
        addr = _address(raw.get("address"))
        if not addr:
            continue
        delta = _float(raw.get("delta_balance"), None)
        delta_pct = _float(raw.get("delta_pct"), None)
        bal0 = _float(raw.get("balance_before"), None)
        bal1 = raw.get("balance_after")
        rows.append({
            "Wallet": shorten_address(addr),
            "Kategori awal": raw.get("from_category") or "—",
            "Kategori terbaru": raw.get("to_category") or "—",
            "Balance awal": bal0,
            "Balance terbaru": bal1 if bal1 is not None else "—",
            "Delta balance token": delta if delta is not None else "—",
            "Nilai USD awal": _float(raw.get("usd_before"), None),
            "Nilai USD terbaru": (_float(raw.get("usd_after"), None)
                                  if raw.get("kind") != "unobserved" else "—"),
            "Interpretasi": raw.get("interpretation") or "—",
            "Solscan": raw.get("solscan") or solscan_link(addr),
            "Ringkas": (
                f"{shorten_address(addr)} — "
                f"{raw.get('from_category') or '—'} → "
                f"{raw.get('to_category') or '—'} — "
                + (f"balance {delta_pct:+.0f}% — " if delta_pct is not None
                   else "")
                + f"{raw.get('interpretation') or '—'}"
            ),
        })
    return rows


def claims_are_non_definitive(text: str) -> bool:
    """True bila narasi tidak mengklaim jual/beli pasti."""
    lowered = str(text or "").lower()
    forbidden = (
        "pasti menjual", "pasti membeli", "pasti jual", "pasti beli",
        "pasti membeli", "definitely sold", "definitely bought",
    )
    return not any(token in lowered for token in forbidden)


def build_chronology_view(baseline: dict | None, latest: dict | None,
                          chrono: dict | None) -> dict:
    """View model murni untuk halaman Holder Analytic."""
    baseline = baseline if isinstance(baseline, dict) and baseline else {}
    latest = latest if isinstance(latest, dict) and latest else baseline
    chrono = compact_chronology(chrono) if chrono else empty_chronology()
    intervals = list(chrono.get("intervals") or [])
    if not baseline:
        return {"state": "none", "intervals": []}
    if not intervals:
        return {
            "state": "initial",
            "message": SNAPSHOT_AWAL_MESSAGE,
            "baseline_ts": baseline.get("ts"),
            "latest_ts": (latest or baseline).get("ts"),
            "intervals": [],
            "sampled": bool((chrono.get("baseline_wallets") or {}).get(
                "sampled")),
            "truncated": bool(baseline.get("truncated")),
        }

    sampled = bool(
        (chrono.get("baseline_wallets") or {}).get("sampled")
        or (chrono.get("latest_wallets") or {}).get("sampled")
        or any(row.get("sampled") for row in intervals))
    truncated = bool((latest or {}).get("truncated")
                     or (chrono.get("latest_wallets") or {}).get("truncated"))

    # Ringkasan kumulatif: bandingkan sampel baseline vs terbaru (bukan jumlah
    # interval) agar "sejak snapshot awal" tidak dobel-hitung wallet yang
    # bolak-balik. Interval tetap ditampilkan terpisah di bawah.
    cumulative = compare_snapshots(
        chrono.get("baseline_wallets"), chrono.get("latest_wallets"),
        previous_metrics=baseline, current_metrics=latest)
    # compare_snapshots membatasi movements; counts-nya atas irisan sampel.
    counts = cumulative.get("counts") or _count_template()
    from_ts = _int(baseline.get("ts") or cumulative.get("from_ts"))
    to_ts = _int((latest or {}).get("ts") or cumulative.get("to_ts"))
    narrative = cumulative_narrative(
        baseline, latest, counts, sampled=sampled, truncated=truncated)
    wallet_start = _int((chrono.get("baseline_wallets") or {}).get("ts"))
    return {
        "state": "ready",
        "baseline_ts": from_ts,
        "latest_ts": to_ts,
        "wallet_sample_lag": bool(
            wallet_start and from_ts and wallet_start - from_ts > 8 * 60),
        "duration_sec": max(0, to_ts - from_ts),
        "duration_label": format_duration(max(0, to_ts - from_ts)),
        "holder_count_from": _int(baseline.get("holder_count")),
        "holder_count_to": _int((latest or {}).get("holder_count")),
        "dust_count_from": _int(baseline.get("dust_count")),
        "dust_count_to": _int((latest or {}).get("dust_count")),
        "dust_pct_from": _float(baseline.get("dust_pct_mc"), None),
        "dust_pct_to": _float((latest or {}).get("dust_pct_mc"), None),
        "counts": counts,
        "narrative": narrative,
        "sampled": sampled,
        "truncated": truncated,
        "price_missing": (
            _float(baseline.get("price"), None) is None
            or _float((latest or {}).get("price"), None) is None
            or _float(baseline.get("mc"), None) in (None, 0.0)
            or _float((latest or {}).get("mc"), None) in (None, 0.0)
        ),
        "intervals": intervals,
        "cumulative_movements": cumulative.get("movements") or [],
    }
