"""Daily CVD calculations matching the GMGN extractor extension.

The browser extension is the reference for day-by-day accounting: buy volume
minus sell volume is CVD, total volume is buy plus sell, and a dry day is a
40%+ volume contraction with a nearly flat CVD ratio.
"""
from collections import defaultdict
from datetime import datetime, timezone

DRY_VOLUME_DROP_PCT = -40.0
DRY_CVD_RATIO_PCT = 10.0


def _day_key(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()


def calculate_daily_cvd(swaps):
    """Return extension-compatible daily rows, oldest first."""
    days = defaultdict(lambda: {"buy_tx": 0, "sell_tx": 0,
                                "buy_sol": 0.0, "sell_sol": 0.0,
                                "wallets": set()})
    for row in swaps or []:
        if len(row) < 4:
            continue
        side, amount, ts, wallet = str(row[0]).lower(), float(row[1]), int(row[2]), str(row[3])
        if side not in {"buy", "sell"} or amount <= 0:
            continue
        day = days[_day_key(ts)]
        day["wallets"].add(wallet)
        key = "buy" if side == "buy" else "sell"
        day[f"{key}_tx"] += 1
        day[f"{key}_sol"] += amount
    result, running = [], 0.0
    previous_volume = None
    for date in sorted(days):
        d = days[date]
        volume = d["buy_sol"] + d["sell_sol"]
        delta = d["buy_sol"] - d["sell_sol"]
        running += delta
        change = ((volume - previous_volume) / previous_volume * 100.0
                  if previous_volume else None)
        ratio = delta / volume * 100.0 if volume else 0.0
        tx = d["buy_tx"] + d["sell_tx"]
        buy_pct = d["buy_tx"] / tx * 100.0 if tx else 0.0
        if change is not None and change <= DRY_VOLUME_DROP_PCT and abs(ratio) <= DRY_CVD_RATIO_PCT:
            status = "KERING / TEST SUPLAI (LPS)"
        elif abs(ratio) <= 7.5:
            status = "DATAR / PENYERAPAN (ABSORPTION)"
        elif ratio > 7.5 and buy_pct >= 52:
            status = "NAIK TAJAM / AGGRESSIVE BUY (MARK-UP)"
        elif ratio < -15:
            status = "TURUN / DISTRIBUSI / DUMP"
        else:
            status = "NORMAL"
        result.append({"date": date, "total_tx": tx, "buy_tx": d["buy_tx"],
                       "sell_tx": d["sell_tx"], "buy_tx_pct": round(buy_pct, 2),
                       "volume_sol": round(volume, 8), "volume_change_pct":
                       round(change, 2) if change is not None else None,
                       "delta_sol": round(delta, 8), "cvd_ratio_pct": round(ratio, 2),
                       "running_cvd_sol": round(running, 8), "status": status,
                       "unique_wallets": len(d["wallets"])})
        previous_volume = volume
    return result


def latest_dry_signal(rows):
    """Return the latest dry-day row, or None."""
    for row in reversed(rows or []):
        if row.get("status", "").startswith("KERING"):
            return row
    return None


def priority_spike(swaps, *, min_tx=500.0, min_volume_sol=500.0):
    """Check the current 15-minute sample for a large transaction burst."""
    rows = [r for r in (swaps or []) if len(r) >= 4 and float(r[1]) > 0]
    volume = sum(float(r[1]) for r in rows)
    buys = sum(1 for r in rows if str(r[0]).lower() == "buy")
    sells = len(rows) - buys
    return {"triggered": len(rows) > min_tx and volume > min_volume_sol,
            "tx": len(rows), "volume_sol": volume, "buy_tx": buys,
            "sell_tx": sells, "cvd_sol": sum(float(r[1]) if str(r[0]).lower() == "buy" else -float(r[1]) for r in rows)}
