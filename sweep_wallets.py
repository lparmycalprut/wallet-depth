# -*- coding: utf-8 -*-
"""Fitur wallet dari trade GMGN untuk membandingkan jendela sebelum sweep.

Permintaan user 2026-10-22: membandingkan pola per wallet (bundler/fresh wallet
yang beli beruntun, nominal buy per wallet) antara jendela sebelum sweep dan
jendela pembanding. Modul ini murni: tidak ada jaringan dan tidak menulis state.

Format swap (dari ``cvd.gmgn_trade_to_swap``):
``(side, sol_eq, ts, wallet, price_usd, amount_usd, tags)``.
"""
from __future__ import annotations

import statistics

FRESH_TAG = "fresh_wallet"
BUNDLER_TAG = "bundler"
SANDWICH_TAG = "sandwich_bot"

#: Dua buy fresh/bundler dianggap satu rangkaian bila jaraknya ≤ detik ini.
RUN_GAP_SEC = 120
#: Jendela pembanding dan jendela sebelum sweep (detik).
WINDOW_SEC = 3 * 3600
#: Lonjakan volume 5m (kali median 24 bar sebelumnya) untuk memicu pencatatan pembanding.
SPIKE_VOL_X = 5.0
SPIKE_BASELINE_BARS = 24


def vol_spike_x(candles, baseline: int = SPIKE_BASELINE_BARS):
    """Volume bar terakhir dibagi median ``baseline`` bar sebelumnya (``None`` bila data kurang)."""
    rows = [c for c in (candles or []) if isinstance(c, (list, tuple)) and len(c) >= 6]
    try:
        rows.sort(key=lambda c: int(c[0]))
    except (TypeError, ValueError):
        return None
    if len(rows) < 7:
        return None
    last = _f(rows[-1][5])
    prior = [_f(c[5]) for c in rows[-1 - baseline:-1]]
    if len(prior) < 6:
        return None
    med = statistics.median(prior)
    if med <= 0:
        return None
    return round(last / med, 2)


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _longest_run(buys: list, gap: int = RUN_GAP_SEC) -> dict:
    """Rangkaian buy terpanjang (jumlah trade) dengan jarak antar buy ≤ ``gap``.

    ``buys`` harus sudah urut waktu dan hanya berisi buy fresh/bundler.
    """
    best = {"len": 0, "wallets": 0, "usd": 0.0, "start": None}
    current: list = []
    for row in buys:
        if current and row[0] - current[-1][0] > gap:
            current = []
        current.append(row)
        if len(current) > best["len"]:
            best = {"len": len(current),
                    "wallets": len({r[2] for r in current}),
                    "usd": round(sum(r[3] for r in current), 2),
                    "start": current[0][0]}
    return best


def wallet_features(swaps, *, start: int, end: int) -> dict:
    """Fitur per wallet untuk trade dalam jendela ``[start, end]`` (detik).

    Tanpa ambang dan tanpa penilaian: angka mentah saja. Nilai ``None`` berarti
    penyebut nol (mis. tidak ada buy sama sekali).
    """
    rows = []
    for swap in swaps or []:
        if not isinstance(swap, (list, tuple)) or len(swap) < 7:
            continue
        side, _sol, ts, wallet, _price, usd, tags = swap[:7]
        if side not in ("buy", "sell") or not wallet:
            continue
        try:
            ts = int(ts or 0)
        except (TypeError, ValueError):
            continue
        usd = _f(usd)
        if not (start <= ts <= end) or usd <= 0:
            continue
        rows.append((ts, side, str(wallet), usd, set(tags or [])))
    rows.sort(key=lambda r: r[0])

    buys = [r for r in rows if r[1] == "buy"]
    sells = [r for r in rows if r[1] == "sell"]
    buy_usd = sum(r[3] for r in buys)
    sell_usd = sum(r[3] for r in sells)
    per_wallet: dict = {}
    for r in buys:
        per_wallet[r[2]] = per_wallet.get(r[2], 0.0) + r[3]

    fresh = [r for r in buys if FRESH_TAG in r[4]]
    bundler = [r for r in buys if BUNDLER_TAG in r[4]]
    sandwich = [r for r in rows if SANDWICH_TAG in r[4]]
    run = _longest_run([r for r in buys if FRESH_TAG in r[4] or BUNDLER_TAG in r[4]])
    total_usd = buy_usd + sell_usd
    top = max(per_wallet.values()) if per_wallet else None

    return {
        "trades": len(rows),
        "buys": len(buys),
        "sells": len(sells),
        "buy_usd": round(buy_usd, 2),
        "sell_usd": round(sell_usd, 2),
        "buy_sell_ratio": round(buy_usd / sell_usd, 3) if sell_usd > 0 else None,
        "buy_wallets": len(per_wallet),
        "median_buy_wallet_usd": (round(statistics.median(per_wallet.values()), 2)
                                  if per_wallet else None),
        "top_buy_wallet_usd": round(top, 2) if top is not None else None,
        "top_buy_share": round(top / buy_usd, 4) if top is not None and buy_usd > 0 else None,
        "fresh_buy_wallets": len({r[2] for r in fresh}),
        "fresh_buy_share": round(sum(r[3] for r in fresh) / buy_usd, 4) if buy_usd > 0 else None,
        "bundler_buy_wallets": len({r[2] for r in bundler}),
        "bundler_buy_share": round(sum(r[3] for r in bundler) / buy_usd, 4) if buy_usd > 0 else None,
        "sandwich_share": round(sum(r[3] for r in sandwich) / total_usd, 4) if total_usd > 0 else None,
        "run_len": run["len"],
        "run_wallets": run["wallets"],
        "run_usd": run["usd"],
        "run_start_ts": run["start"],
    }
