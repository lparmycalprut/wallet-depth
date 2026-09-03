# -*- coding: utf-8 -*-
"""Scan khusus holder — satu token, data holder dari Helius.

Modul ringan untuk *holder scan* on-demand: user menempel contract address
(CA) satu token, lalu seluruh daftar holder token diambil dari **Helius DAS
``getTokenAccounts``** (paginasi cursor penuh) dan ditampilkan sebagai
**bar chart Wallet Depth by Threshold** (jumlah holder per range nilai USD,
mirip chart ``#analytics_holder`` Solscan).

Modul ini **memaksa Helius** sebagai sumber holder — Helius DAS memang
sumber data utama aplikasi (Solscan sudah dilepas; GMGN hanya untuk
listing Trending/Degen). Nilai USD holder = ``balance UI × harga token``
dari DexScreener (``core.get_market``); ``amount`` RAW dari DAS dikonversi
lewat decimals mint di ``fetch_holders_helius``.

Alur:
``scan_token_holders(ca)``
    → market (harga & marketcap) dari DexScreener
    → ``fetch_holders_helius`` (Helius DAS, paginasi cursor)
    → ``solscan_holders.wallet_depth`` (bucket & tier)
    → dict ringkas untuk UI.

``depth_bar_chart(depth, title)``
    → Figure matplotlib (bar chart distribusi holder per bucket).
"""
from __future__ import annotations

import matplotlib.pyplot as plt

from core import get_helius_keys, get_market
from holder_analysis import fetch_holders_helius
from solscan_holders import wallet_depth

# Default batas holder yang dianalisis saat scan satu token. Lebih besar dari
# nilai default global (3000) supaya distribusi bucket lebih mewakili; masih
# dibatasi keras oleh pengaman paginasi di fetch_holders_helius (60 halaman).
SCAN_DEFAULT_MAX_WALLETS = 20_000

# Warna per bucket, urut dari nilai kecil → besar (sekitar palette app).
_BUCKET_COLORS = (
    "#94a3b8", "#64748b", "#3b82f6", "#10b981",
    "#f59e0b", "#ef4444", "#8b5cf6",
)


def _float(value, default=0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        return num if num == num else default  # NaN guard
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    return int(_float(value, float(default)))


def _compact(value) -> str:
    """Format USD ringkas: 12.3K / 4.5M dst. ``None``/tidak valid → em-dash."""
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 1e6:
        return f"${n / 1e6:.2f}M"
    if abs(n) >= 1e3:
        return f"${n / 1e3:.1f}K"
    return f"${n:,.0f}"


def scan_token_holders(ca: str, *, max_wallets: int | None = None,
                       price_usd: float = 0.0,
                       market_cap: float = 0.0,
                       include_pools: bool = False) -> dict:
    """Scan holder satu token memakai Helius DAS sebagai sumber.

    Mengambil market (harga & marketcap) dari DexScreener, daftar holder
    dari Helius ``getTokenAccounts``, lalu menghitung Wallet Depth by
    Threshold (bucket) + tier (hanya wallet murni).

    ``include_pools``: bila ``False`` (default) akun LP/pool yang dikenal
    (``pair_addresses`` DexScreener) **disingkirkan dari list/bucket
    holder** — pool AMM yang menyerap dump bisa memegang puluhan persen
    supply dan menyesatkan bucket. Tier dan metrik ``pool_excluded``
    tetap dihitung normal; ``True`` mengembalikan perilaku lama (bucket
    memuat semua akun seperti chart analytics Solscan).

    Return dict::

        {
          "market": {...},            # dari get_market (bisa {})
          "snapshot": {...},          # dari fetch_holders_helius
          "depth": {...},             # dari wallet_depth
          "source": "helius",
          "scan_failed": bool,        # True bila tak ada holder/market valid
        }
    """
    ca = str(ca or "").strip()
    market = {}
    try:
        market = get_market(ca) or {}
    except Exception:  # noqa: BLE001 - market gagal, lanjut dengan nilai kosong
        market = {}
    price = _float(price_usd or market.get("price_usd"))
    mc = _float(market_cap or market.get("marketcap"))
    max_wallets = int(max_wallets or SCAN_DEFAULT_MAX_WALLETS)

    keys = get_helius_keys()
    no_keys = not keys
    snapshot = {}
    if price > 0 and not no_keys:
        snapshot = fetch_holders_helius(
            ca, max_wallets=max_wallets, price_usd=price, helius_keys=keys)
    else:
        snapshot = {"holders": [], "pages": 0, "truncated": False,
                    "fetched": 0, "source": "helius",
                    "error": "Helius key tidak ada atau harga belum tersedia"}

    pools = set(str(p or "").strip() for p in
                (market.get("pair_addresses") or []) if p)
    depth = wallet_depth(snapshot.get("holders") or [], mc,
                         pool_addresses=pools, include_pools=include_pools)
    scan_failed = not snapshot.get("holders") or price <= 0
    return {
        "mint": ca,
        "symbol": str(market.get("symbol") or "?"),
        "market": market,
        "snapshot": snapshot,
        "depth": depth,
        "source": "helius",
        "no_helius_keys": no_keys,
        "scan_failed": bool(scan_failed),
    }


def depth_bar_chart(depth: dict | None, *, title: str = "Holder") -> plt.Figure | None:
    """Bar chart distribusi holder per bucket nilai (Wallet Depth).

    Sumbu X = range nilai bucket, sumbu Y = jumlah holder. Setiap batang
    diberi label jumlah holder dan total nilai USD bucket. Mengembalikan
    ``None`` bila tak ada bucket yang bisa digambar (mis. depth kosong).
    Pemanggil wajib ``plt.close(fig)`` setelah ditampilkan.
    """
    buckets = (depth or {}).get("buckets") or []
    if not buckets:
        return None
    labels = [str(b.get("label") or "?") for b in buckets]
    counts = [_int(b.get("count")) for b in buckets]
    values = [_float(b.get("value_usd")) for b in buckets]
    pcts = [b.get("pct_mc") for b in buckets]

    fig, axis = plt.subplots(figsize=(11, 4.8))
    colors = list(_BUCKET_COLORS[:len(labels)])
    axis.bar(labels, counts, color=colors, alpha=.9, edgecolor="white")

    # Label pada tiap batang: jumlah holder + nilai USD (2 baris).
    for index, (count, value, pct) in enumerate(zip(counts, values, pcts)):
        line = f"{count:,}\n{_compact(value)}"
        if pct is not None and value > 0:
            line += f" · {_float(pct):.1f}%MC"
        axis.text(index, count, line, ha="center", va="bottom",
                  fontsize=9, fontweight="bold")

    ymax = max(counts) if counts else 1
    axis.set_ylim(0, ymax * 1.28)
    axis.set_ylabel("Jumlah holder")
    axis.set_xlabel("Range nilai USD per holder")
    axis.set_title(title)
    axis.tick_params(axis="x", rotation=20)
    axis.grid(axis="y", alpha=.2)
    axis.margins(x=0.02)
    fig.tight_layout()
    return fig
