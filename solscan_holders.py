# -*- coding: utf-8 -*-
"""Wallet Depth by Threshold + Holder Distribution by Tier (kalkulasi).

Modul ini dulunya mengambil daftar holder dari Solscan API. Sumber data
holder sekarang **sepenuhnya Helius** (lihat
``holder_analysis.fetch_holders_helius`` + ``helius_holders``) — nama
file dipertahankan supaya perubahan impor tidak merembet.

Yang tersisa di sini adalah definisi ambang & kalkulasi ``wallet_depth``:

1. **Wallet Depth by Threshold** — jumlah holder per bucket nilai USD:
   ``>$0-$10``, ``$10-$100``, ``$100-$1k``, ``$1k-$10k``, ``$10k-$100k``,
   ``$100k-$500k``, ``>$500k``. Default sekarang **wallet murni saja**
   (LP/pool disingkirkan) karena pool AMM yang menyerap jualan bisa
   mendominasi bucket dan menyesatkan pembacaan; mode lama (semua akun,
   termasuk LP/pool, seperti chart analytics Solscan) tetap tersedia
   via ``include_pools=True``.
2. **Holder Distribution by Tier** — 🦐 Shrimp / 🦀 Crab / 🐟 Fish /
   🐬 Dolphin / 🦈 Shark, dihitung hanya untuk **wallet murni** (akun
   LP/pool yang dikenal dikecualikan via ``pool_addresses``).

Akun dianggap LP/pool bila: GMGN menandainya bukan wallet
(``is_wallet=False`` — ``addr_type`` non-zero / ada field ``exchange``)
**atau** address-nya ada di ``pool_addresses`` (pair DexScreener —
menutup jalur Helius yang menandai semua akun ``is_wallet=True``).
"""
from __future__ import annotations

import time

# --- Wallet Depth by Threshold (seperti halaman analytics Solscan) ----------
DEPTH_BUCKETS = (
    (">$0-$10", 0.0, 10.0),
    ("$10-$100", 10.0, 100.0),
    ("$100-$1k", 100.0, 1_000.0),
    ("$1k-$10k", 1_000.0, 10_000.0),
    ("$10k-$100k", 10_000.0, 100_000.0),
    ("$100k-$500k", 100_000.0, 500_000.0),
    (">$500k", 500_000.0, None),
)

# --- Holder Distribution by Tier (wallet murni) ------------------------------
TIERS = (
    ("🦐", "Shrimp", 0.0, 100.0),
    ("🦀", "Crab", 100.0, 1_000.0),
    ("🐟", "Fish", 1_000.0, 10_000.0),
    ("🐬", "Dolphin", 10_000.0, 100_000.0),
    ("🦈", "Shark", 100_000.0, None),
)


def _float(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        return num if num == num else default  # NaN guard
    except (TypeError, ValueError):
        return default


def wallet_depth(holders, market_cap: float = 0.0, *,
                 pool_addresses=None, include_pools: bool = True) -> dict:
    """Wallet Depth by Threshold + Holder Distribution by Tier.

    - ``buckets``: per bucket nilai USD atas akun bernilai > $0 —
      **dengan** ``include_pools=True`` (default historis) semua akun
      termasuk LP/pool (seperti chart Solscan); dengan
      ``include_pools=False`` hanya wallet murni (LP/pool disingkirkan
      dari list holder).
    - ``tiers``: selalu hanya wallet murni (LP/pool dikecualikan), per
      tier.

    Setiap entri: ``{"label"/"tier"/"emoji", "min", "max", "count",
    "value_usd", "pct_mc"}`` — ``pct_mc`` = None bila marketcap 0.
    Field hasil tambahan: ``buckets_include_pools`` (mode bucket yang
    dipakai) — UI memakainya untuk caption/metrik yang tepat.
    """
    pool_set = {str(p or "").strip().lower() for p in (pool_addresses or [])
                if p}
    all_rows = [h for h in (holders or [])
                if isinstance(h, dict) and _float(h.get("usd_value")) > 0]

    def _is_pool(row) -> bool:
        return (not row.get("is_wallet")
                or str(row.get("address") or "").lower() in pool_set)

    wallet_rows = [h for h in all_rows if not _is_pool(h)]
    bucket_rows = all_rows if include_pools else wallet_rows
    mc = float(market_cap or 0)

    # Tiers: wallet murni saja, ambang mengikuti konvensi Solscan.
    tier_rows = []
    for emoji, name, lo, hi in TIERS:
        items = [h for h in wallet_rows
                 if _float(h.get("usd_value")) > lo
                 and (hi is None or _float(h.get("usd_value")) <= hi)]
        value = sum(_float(h.get("usd_value")) for h in items)
        tier_rows.append({
            "tier": name,
            "emoji": emoji,
            "min": lo,
            "max": hi,
            "count": len(items),
            "value_usd": round(value, 2),
            "pct_mc": (round(value / mc * 100.0, 4) if mc > 0 else None),
        })

    buckets = []
    for label, lo, hi in DEPTH_BUCKETS:
        items = [h for h in bucket_rows
                 if _float(h.get("usd_value")) > lo
                 and (hi is None or _float(h.get("usd_value")) <= hi)]
        value = sum(_float(h.get("usd_value")) for h in items)
        buckets.append({
            "label": label,
            "min": lo,
            "max": hi,
            "count": len(items),
            "value_usd": round(value, 2),
            "pct_mc": (round(value / mc * 100.0, 4) if mc > 0 else None),
        })

    return {
        "buckets": buckets,
        "buckets_include_pools": bool(include_pools),
        "tiers": tier_rows,
        "holders_all": len(all_rows),
        "holders_wallet": len(wallet_rows),
        "pool_excluded": len(all_rows) - len(wallet_rows),
        "market_cap": mc,
        "computed_at": int(time.time()),
    }
