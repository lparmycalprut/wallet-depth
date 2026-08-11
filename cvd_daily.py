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


# --- First Buy Surge (awal fase MARK-UP) ------------------------------------
# Deteksi "lonjakan buy pertama" pada token prioritas (volume sudah kering).
# Empat kaki wajib lolos dalam jendela sample (default 15 menit):
#   1. VOLUME SURGE   — volume jendela >= +100% vs volume rata-rata per jam
#                       di fase kering H-1 (zona valid +100% s/d +300%+),
#                       plus floor absolut anti-debu.
#   2. BUY TX RATIO   — >= 60% transaksi adalah BUY (sebelumnya ~48-52%),
#                       dari banyak wallet unik (bukan 1 wallet spam).
#   3. CVD VELOCITY   — (buy_sol - sell_sol) / volume >= +20% (CVD berbelok
#                       tajam ke atas).
#   4. BIG-BUY CLUSTER — >= 3 transaksi buy >= 1 SOL (rentang 0.5-2 SOL)
#                       bertubi-tubi dan TANPA sell besar yang membalas.
FIRST_BUY_SURGE_DEFAULTS = {
    "window_sec": 900,             # jendela sample (cron 15 menit)
    "min_surge_pct": 100.0,        # lonjakan volume vs baseline kering/jam
    "min_window_volume_sol": 5.0,  # floor absolut bila baseline kecil/unknown
    "min_tx": 10,                  # sampel minimal ("dari 10 transaksi...")
    "min_buy_ratio_pct": 60.0,     # minimal 6-8 dari 10 tx adalah BUY
    "min_unique_buy_wallets": 5,   # buy dari wallet unik, bukan 1 wallet
    "min_cvd_ratio_pct": 20.0,     # Delta/Volume >= +20% (CVD velocity)
    "big_buy_sol": 1.0,            # ukuran "big buy" (valid 0.5-2 SOL)
    "min_big_buys": 3,             # 3-5 big buy bertubi-tubi
    "max_big_sells": 0,            # tanpa sell besar pembalas
}


def first_buy_surge(swaps, *, baseline_hourly_sol=None, now_ts=None,
                    **overrides):
    """Deteksi Lonjakan Buy Pertama (MARK-UP) pada sample swap terbaru.

    ``swaps`` adalah baris ``(side, sol, ts, wallet)``; ``baseline_hourly_sol``
    adalah volume rata-rata per jam token saat fase kering (H-1). Bila
    baseline tidak diketahui, kaki volume memakai floor absolut saja.
    """
    cfg = dict(FIRST_BUY_SURGE_DEFAULTS)
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    window = int(cfg["window_sec"])

    rows = [r for r in (swaps or []) if len(r) >= 4 and float(r[1]) > 0]
    if rows and now_ts is not None:
        cutoff = int(now_ts) - window
        rows = [r for r in rows if int(r[2]) >= cutoff]

    tx = len(rows)
    buy_rows = [r for r in rows if str(r[0]).lower() == "buy"]
    sell_rows = [r for r in rows if str(r[0]).lower() != "buy"]
    buy_sol = sum(float(r[1]) for r in buy_rows)
    sell_sol = sum(float(r[1]) for r in sell_rows)
    volume = buy_sol + sell_sol
    cvd = buy_sol - sell_sol
    buy_tx, sell_tx = len(buy_rows), len(sell_rows)
    unique_buy_wallets = len({str(r[3]) for r in buy_rows})
    buy_ratio_pct = buy_tx / tx * 100.0 if tx else 0.0
    cvd_ratio_pct = cvd / volume * 100.0 if volume else 0.0

    big = float(cfg["big_buy_sol"])
    big_buys = [r for r in buy_rows if float(r[1]) >= big]
    big_sells = [r for r in sell_rows if float(r[1]) >= big]
    big_buy_sol_total = sum(float(r[1]) for r in big_buys)

    # --- Kaki 1: volume surge vs baseline kering per jam --------------------
    baseline = (float(baseline_hourly_sol)
                if baseline_hourly_sol is not None else None)
    surge_pct = None
    if baseline is not None and baseline > 0:
        surge_pct = (volume / baseline - 1.0) * 100.0
        volume_ok = (surge_pct >= float(cfg["min_surge_pct"])
                     and volume >= float(cfg["min_window_volume_sol"]))
    elif baseline is not None:  # baseline 0: fase kering benar-benar nol
        volume_ok = volume >= float(cfg["min_window_volume_sol"])
    else:  # baseline tak diketahui -> floor absolut saja
        volume_ok = volume >= float(cfg["min_window_volume_sol"])

    # --- Kaki 2: rasio buy tx (sampel & wallet unik) ------------------------
    ratio_ok = (tx >= int(cfg["min_tx"])
                and buy_ratio_pct >= float(cfg["min_buy_ratio_pct"])
                and unique_buy_wallets >= int(cfg["min_unique_buy_wallets"]))

    # --- Kaki 3: CVD velocity -----------------------------------------------
    cvd_ok = volume > 0 and cvd_ratio_pct >= float(cfg["min_cvd_ratio_pct"])

    # --- Kaki 4: cluster big buy tanpa sell besar pembalas ------------------
    cluster_ok = (len(big_buys) >= int(cfg["min_big_buys"])
                  and len(big_sells) <= int(cfg["max_big_sells"]))

    checks = {"volume": bool(volume_ok), "buy_ratio": bool(ratio_ok),
              "cvd_velocity": bool(cvd_ok), "big_buy_cluster": bool(cluster_ok)}
    reasons = []
    if volume_ok:
        reasons.append(
            f"volume {volume:.2f} SOL"
            + (f" ({surge_pct:+.0f}% vs {baseline:.2f} SOL/jam kering)"
               if surge_pct is not None else " (baseline n/a, floor ok)"))
    else:
        reasons.append(
            "volume kurang: "
            + (f"{surge_pct:+.0f}% < +{cfg['min_surge_pct']:g}%"
               if surge_pct is not None
               else f"{volume:.2f} < {cfg['min_window_volume_sol']:g} SOL"))
    reasons.append(
        f"buy ratio {buy_ratio_pct:.0f}% ({buy_tx}/{tx} tx, "
        f"{unique_buy_wallets} wallet)" + (" ✓" if ratio_ok else " ✗"))
    reasons.append(f"CVD velocity {cvd_ratio_pct:+.1f}%"
                   + (" ✓" if cvd_ok else " ✗"))
    reasons.append(f"big-buy {len(big_buys)}x ≥{big:g} SOL / big-sell "
                   f"{len(big_sells)}x" + (" ✓" if cluster_ok else " ✗"))

    return {"triggered": all(checks.values()), "checks": checks,
            "reasons": reasons, "tx": tx, "buy_tx": buy_tx,
            "sell_tx": sell_tx, "volume_sol": volume, "cvd_sol": cvd,
            "buy_ratio_pct": buy_ratio_pct, "cvd_ratio_pct": cvd_ratio_pct,
            "unique_buy_wallets": unique_buy_wallets,
            "big_buys": len(big_buys), "big_sells": len(big_sells),
            "big_buy_sol_total": big_buy_sol_total,
            "big_buy_sol": big, "baseline_hourly_sol": baseline,
            "surge_pct": surge_pct, "window_sec": window}
