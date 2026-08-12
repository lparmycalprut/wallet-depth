# -*- coding: utf-8 -*-
"""Setup Emas detector — 7 daily-transaction checks across 3 pillars.

Calibrated 2026-08-12 against Ansem / Punch / Assface (pass) and
Callcat / Froge (stealth dump). Score points only at the golden
accumulation setup; ignition (P4) is informational, not required.

  P1  CVD Absorption          |CVD/Vol| < 3.0%
  P1  Bullish Divergence      CVD flat/up, or vol-up + CVD-down absorption
  P2  Buy TX Dominance        Buy TX >= 49% (near-even tape is OK)
  P2  Order Size Discrepancy  Avg SELL > Avg BUY
  P2  Whale Pressure Absorbed whale net < 0
  P3  Volume                  LPS −40%…−75% OR absorbed expansion
                              (vol ≥ +40% and CVD down and |CVD/Vol| < 3%)
  P3  Retensi Akumulator      Top-100 lock >= 40%

Verdict: STEALTH DUMP / SETUP EMAS (7/7) / WATCH (>=5/7) / FAIL.
"""
from collections import defaultdict
from datetime import datetime, timezone

from cvd_daily import calculate_daily_cvd, complete_daily_rows

# ---------------------------------------------------------------------------
# Calibrated thresholds (do not loosen without a new fixture suite)
# ---------------------------------------------------------------------------
CVD_ABSORPTION_PCT = 3.0
# 49% = tape hampir seimbang (541/547 SISYPUSS). Stealth dump tetap
# memakai 52% + avg buy ≥ avg sell (Callcat/Froge).
BUY_TX_MIN_PCT = 49.0
STEALTH_BUY_TX_MAX = 52.0
WHALE_SOL = 1.0
LPS_DROP_MIN_PCT = -40.0
# Upper dry bound: user asked −40…−70; −75 keeps LUNA (−73) / Punch (−72).
LPS_DROP_MAX_PCT = -75.0
# Symmetric with LPS: volume +40%+ with CVD down = large absorption.
VOL_EXPANSION_MIN_PCT = 40.0
SUPPLY_LOCK_MIN_PCT = 40.0
CVD_FLAT_TOL_SOL = 1.0
IGNITION_BUY_PCT = 55.0
IGNITION_VOL_MIN_PCT = 100.0
IGNITION_VOL_MAX_PCT = 14000.0
M15_SEC = 900
H1_SEC = 3600

VERDICT_EMAS = "SETUP EMAS"
VERDICT_PASS = VERDICT_EMAS  # compat alias
VERDICT_WATCH = "WATCH"
VERDICT_FAIL = "FAIL"
VERDICT_STEALTH = "STEALTH DUMP"

PHASE_ABSORPTION = "ABSORPTION"
PHASE_LPS = "KERING / LPS"
PHASE_EMAS = "SETUP EMAS"
PHASE_IGNITION = "IGNITION"
PHASE_STEALTH = "STEALTH DUMP"
PHASE_DUMP = "DISTRIBUSI / DUMP"
PHASE_NORMAL = "NORMAL"

GOLDEN_TOTAL = 7
GOLDEN_WEIGHTS = {
    "p1_absorption": 18,
    "p1_cvd_flat": 12,
    "p2_buy_tx": 18,
    "p2_order_size": 16,
    "p2_whale": 10,
    "p3_lps": 16,
    "p3_lock": 10,
}


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _day_key(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()


def _empty_metrics():
    return {
        "buy_tx": 0,
        "sell_tx": 0,
        "total_tx": 0,
        "buy_tx_pct": 0.0,
        "sell_tx_pct": 0.0,
        "buy_sol": 0.0,
        "sell_sol": 0.0,
        "volume_sol": 0.0,
        "delta_sol": 0.0,
        "absorption_pct": 0.0,
        "avg_buy_sol": 0.0,
        "avg_sell_sol": 0.0,
        "whale_buy_sol": 0.0,
        "whale_sell_sol": 0.0,
        "whale_net_sol": 0.0,
        "unique_wallets": 0,
        "volume_change_pct": None,
    }


def compute_window_metrics(swaps, *, whale_sol=WHALE_SOL):
    """Aggregate one swap window into 4-pillar inputs.

    ``swaps`` is an iterable of ``(side, sol, ts, wallet)``.
    """
    out = _empty_metrics()
    wallets = set()
    for row in swaps or []:
        if len(row) < 4:
            continue
        side = str(row[0]).lower()
        amount = _as_float(row[1], 0.0)
        wallet = str(row[3] or "")
        if side not in {"buy", "sell"} or amount <= 0:
            continue
        if wallet:
            wallets.add(wallet)
        if side == "buy":
            out["buy_tx"] += 1
            out["buy_sol"] += amount
            if amount >= whale_sol:
                out["whale_buy_sol"] += amount
        else:
            out["sell_tx"] += 1
            out["sell_sol"] += amount
            if amount >= whale_sol:
                out["whale_sell_sol"] += amount
    out["total_tx"] = out["buy_tx"] + out["sell_tx"]
    out["volume_sol"] = out["buy_sol"] + out["sell_sol"]
    out["delta_sol"] = out["buy_sol"] - out["sell_sol"]
    if out["total_tx"]:
        out["buy_tx_pct"] = out["buy_tx"] / out["total_tx"] * 100.0
        out["sell_tx_pct"] = out["sell_tx"] / out["total_tx"] * 100.0
    if out["buy_tx"]:
        out["avg_buy_sol"] = out["buy_sol"] / out["buy_tx"]
    if out["sell_tx"]:
        out["avg_sell_sol"] = out["sell_sol"] / out["sell_tx"]
    if out["volume_sol"] > 0:
        out["absorption_pct"] = (
            abs(out["delta_sol"]) / out["volume_sol"] * 100.0
        )
    out["whale_net_sol"] = out["whale_buy_sol"] - out["whale_sell_sol"]
    out["unique_wallets"] = len(wallets)
    return out


def metrics_for_day(swaps, date_iso, *, whale_sol=WHALE_SOL):
    """Window metrics restricted to one UTC calendar day."""
    day_swaps = [
        row for row in (swaps or [])
        if len(row) >= 3 and _day_key(row[2]) == date_iso
    ]
    return compute_window_metrics(day_swaps, whale_sol=whale_sol)


def is_stealth_dump(metrics):
    """Retail FOMO buying big while insiders dribble-sell (Callcat/Froge)."""
    m = metrics or {}
    avg_buy = _as_float(m.get("avg_buy_sol"), 0.0)
    avg_sell = _as_float(m.get("avg_sell_sol"), 0.0)
    buy_pct = _as_float(m.get("buy_tx_pct"), 0.0)
    if avg_buy <= 0 and avg_sell <= 0:
        return False
    return avg_buy >= avg_sell and buy_pct < STEALTH_BUY_TX_MAX


def _pillar(name, passed, detail, **extra):
    row = {
        "id": name,
        "passed": bool(passed),
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }
    row.update(extra)
    return row


def _cvd_is_flat(daily_rows, *, tol_sol=CVD_FLAT_TOL_SOL):
    """True when running CVD is flat or rising (1 SOL noise = flat)."""
    if not daily_rows or len(daily_rows) < 2:
        return True
    prev = _as_float(daily_rows[-2].get("running_cvd_sol"), 0.0)
    last = _as_float(daily_rows[-1].get("running_cvd_sol"), prev)
    return last >= prev - abs(_as_float(tol_sol, CVD_FLAT_TOL_SOL))


def _row_absorption(src):
    """|CVD/Vol| from a metrics dict or daily row."""
    src = src or {}
    if src.get("absorption_pct") is not None:
        return abs(_as_float(src.get("absorption_pct"), 99.0))
    return abs(_as_float(src.get("cvd_ratio_pct"), 99.0))


def _is_lps_drop(change_pct):
    """True when daily volume contracted into the LPS band (−40%…−75%)."""
    if change_pct is None:
        return False
    change = _as_float(change_pct, 0.0)
    return LPS_DROP_MAX_PCT <= change <= LPS_DROP_MIN_PCT


def _is_absorbed_expansion(change_pct, metrics=None, row=None):
    """Volume up + CVD down + tight tape = large absorption (bullish).

    SISYPUSS 2026-08-10: vol +146%, Δ −9.7 SOL, |CVD/Vol| 1.07% →
    pump the next day. That print is the setup, not ignition.
    """
    if change_pct is None:
        return False
    change = _as_float(change_pct, 0.0)
    if change < VOL_EXPANSION_MIN_PCT:
        return False
    src = metrics or row or {}
    delta = _as_float(src.get("delta_sol"), 0.0)
    absorption = _row_absorption(src)
    volume = _as_float(src.get("volume_sol"), 0.0)
    return (delta < 0 and volume > 0
            and absorption < CVD_ABSORPTION_PCT)


def _p3_volume_ok(change_pct, metrics=None, row=None):
    """P3 volume: classic LPS dry-up or absorbed expansion."""
    return (_is_lps_drop(change_pct)
            or _is_absorbed_expansion(
                change_pct, metrics=metrics, row=row))


def _p1_divergence_ok(daily_rows, metrics=None):
    """Flat/up CVD, or vol-up + CVD-down absorption (not bearish)."""
    if _cvd_is_flat(daily_rows):
        return True
    m = metrics or {}
    change = m.get("volume_change_pct")
    if change is None and daily_rows:
        change = (daily_rows[-1] or {}).get("volume_change_pct")
    return _is_absorbed_expansion(change, metrics=m)


def evaluate_pillar1_flow(metrics, daily_rows=None):
    """P1 — absorption < 3.0% AND CVD flat/up at the support test."""
    m = metrics or _empty_metrics()
    absorption = _as_float(m.get("absorption_pct"), 0.0)
    volume = _as_float(m.get("volume_sol"), 0.0)
    delta = _as_float(m.get("delta_sol"), 0.0)
    tight = volume > 0 and absorption < CVD_ABSORPTION_PCT
    rising = _p1_divergence_ok(daily_rows, m)
    passed = tight and rising
    if _is_absorbed_expansion(m.get("volume_change_pct"), metrics=m):
        cvd_txt = "turun terserap (vol naik)"
    elif rising:
        cvd_txt = "datar/naik"
    else:
        cvd_txt = "turun"
    label = (
        f"|CVD/Vol| {absorption:.2f}% "
        f"({'< 3.0% ABSORPTION KUAT' if tight else '>= 3.0% TEKANAN JUAL'})"
        f" · Δ {delta:+.2f} SOL"
        f" · CVD {cvd_txt}"
    )
    return _pillar(
        "p1_flow",
        passed,
        label,
        absorption_pct=round(absorption, 4),
        delta_sol=round(delta, 8),
        volume_sol=round(volume, 8),
        cvd_rising=rising,
    )


def evaluate_pillar2_participation(metrics):
    """P2 — buy-TX breadth + anti-stealth order-size + whale absorption."""
    m = metrics or _empty_metrics()
    buy_pct = _as_float(m.get("buy_tx_pct"), 0.0)
    avg_buy = _as_float(m.get("avg_buy_sol"), 0.0)
    avg_sell = _as_float(m.get("avg_sell_sol"), 0.0)
    whale_net = _as_float(m.get("whale_net_sol"), 0.0)
    buy_ok = buy_pct >= BUY_TX_MIN_PCT
    order_ok = avg_sell > avg_buy and avg_sell > 0
    stealth = is_stealth_dump(m)
    whale_absorbed = whale_net < 0
    passed = buy_ok and order_ok and whale_absorbed and not stealth
    thr = f"{BUY_TX_MIN_PCT:g}"
    bits = [
        f"Buy TX {buy_pct:.1f}% "
        f"({'≥ '+thr+'% AKUMULASI CICIL' if buy_ok else '< '+thr+'% DISTRIBUSI'})",
        f"Avg Sell {avg_sell:.3f} vs Avg Buy {avg_buy:.3f} SOL "
        f"({'RITEL PANIK DISERAP' if order_ok else 'STEALTH DUMP RISK'})",
        f"Whale net {whale_net:+.2f} SOL "
        f"({'diserap' if whale_absorbed else 'net buyer'})",
    ]
    if stealth:
        bits.append(
            f"TRAP: avg BUY ≥ avg SELL + buy TX < {thr}%")
    return _pillar(
        "p2_participation",
        passed,
        " · ".join(bits),
        buy_tx_pct=round(buy_pct, 2),
        avg_buy_sol=round(avg_buy, 6),
        avg_sell_sol=round(avg_sell, 6),
        whale_net_sol=round(whale_net, 6),
        stealth_dump=stealth,
        whale_absorbed=whale_absorbed,
    )


def evaluate_pillar3_supply(daily_rows, holder_lock_pct=None,
                            price_series=None, metrics=None):
    """P3 — LPS dry-up or absorbed expansion + Top-100 lock."""
    rows = list(daily_rows or [])
    latest = rows[-1] if rows else {}
    src = metrics or latest
    change = src.get("volume_change_pct")
    if change is None:
        change = latest.get("volume_change_pct")
    lps = _is_lps_drop(change)
    absorbed = _is_absorbed_expansion(change, metrics=src, row=latest)
    vol_ok = lps or absorbed
    lock = None if holder_lock_pct is None else _as_float(holder_lock_pct)
    lock_ok = lock is not None and lock >= SUPPLY_LOCK_MIN_PCT
    no_ll = True
    if price_series and len(price_series) >= 2:
        lows = [_as_float(p, 0.0) for p in price_series if _as_float(p, 0) > 0]
        if len(lows) >= 2:
            no_ll = lows[-1] >= min(lows[:-1]) - 1e-18
    passed = vol_ok and lock_ok and no_ll
    change_txt = "n/a" if change is None else f"{_as_float(change):+.1f}%"
    lock_txt = "n/a" if lock is None else f"{lock:.1f}%"
    if lps:
        vol_label = "SUPLAI KERING / LPS"
    elif absorbed:
        vol_label = "EKSPANSI TERSERAP (vol naik, CVD turun)"
    else:
        vol_label = "belum kering / belum terserap"
    detail = (
        f"Vol vs H-1 {change_txt} ({vol_label})"
        f" · Top-100 lock {lock_txt}"
        f"{'' if no_ll else ' · NEW LOWER-LOW'}"
    )
    return _pillar(
        "p3_supply",
        passed,
        detail,
        volume_change_pct=(
            None if change is None else round(_as_float(change), 2)
        ),
        holder_lock_pct=lock,
        lps=lps,
        absorbed_expansion=absorbed,
        no_lower_low=no_ll,
    )


def _bin_swaps(swaps, bucket_sec):
    bins = defaultdict(list)
    for row in swaps or []:
        if len(row) < 4:
            continue
        try:
            ts = int(row[2])
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        bins[(ts // bucket_sec) * bucket_sec].append(row)
    return bins


def find_ignition(swaps, *, dry_hourly_sol=None, now_ts=None,
                  after_ts=None):
    """Return the first 15m/1h ignition candle, or None.

    Ignition = buy TX >= 55%, net delta SOL > 0, and volume expansion
    of +100% … +14000% versus the dry-phase hourly baseline.
    """
    rows = [r for r in (swaps or []) if len(r) >= 4]
    if now_ts is not None:
        rows = [r for r in rows if int(r[2]) <= int(now_ts)]
    if after_ts is not None:
        rows = [r for r in rows if int(r[2]) >= int(after_ts)]
    if not rows:
        return None

    baseline = None
    if dry_hourly_sol is not None and _as_float(dry_hourly_sol) >= 0:
        baseline = _as_float(dry_hourly_sol)

    for bucket_sec, label in ((M15_SEC, "15m"), (H1_SEC, "1h")):
        hours = bucket_sec / 3600.0
        expected = None if baseline is None else baseline * hours
        grouped = _bin_swaps(rows, bucket_sec)
        for start in sorted(grouped):
            metrics = compute_window_metrics(grouped[start])
            if metrics["total_tx"] <= 0 or metrics["volume_sol"] <= 0:
                continue
            if metrics["buy_tx_pct"] < IGNITION_BUY_PCT:
                continue
            if metrics["delta_sol"] <= 0:
                continue
            surge = None
            if expected is not None and expected > 0:
                surge = (metrics["volume_sol"] / expected - 1.0) * 100.0
                if surge < IGNITION_VOL_MIN_PCT:
                    continue
                if surge > IGNITION_VOL_MAX_PCT:
                    continue
            elif expected == 0:
                # Fully dry hour: any real positive volume is ignition.
                surge = None
            else:
                # No baseline: require a meaningful absolute print.
                floor = 5.0 if label == "15m" else 10.0
                if metrics["volume_sol"] < floor:
                    continue
            return {
                "tf": label,
                "start_ts": start,
                "buy_tx_pct": metrics["buy_tx_pct"],
                "delta_sol": metrics["delta_sol"],
                "volume_sol": metrics["volume_sol"],
                "surge_pct": surge,
                "metrics": metrics,
            }
    return None


def evaluate_pillar4_ignition(swaps, daily_rows=None, *, now_ts=None):
    """P4 — first 15m/1h ignition after a dry / absorption day."""
    dry_hourly = None
    after_ts = None
    for row in reversed(daily_rows or []):
        status = str(row.get("status") or "")
        change = row.get("volume_change_pct")
        absorption = abs(_as_float(row.get("cvd_ratio_pct")
                                   or row.get("absorption_pct"), 99))
        is_dry = status.startswith("KERING") or _is_lps_drop(change)
        is_abs = absorption < CVD_ABSORPTION_PCT
        if is_dry or is_abs:
            vol = _as_float(row.get("volume_sol"), 0.0)
            dry_hourly = vol / 24.0
            try:
                day = datetime.strptime(row["date"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc)
                after_ts = int(day.timestamp())
            except Exception:
                after_ts = None
            break
    hit = find_ignition(
        swaps, dry_hourly_sol=dry_hourly, now_ts=now_ts, after_ts=after_ts,
    )
    if not hit:
        return _pillar(
            "p4_ignition",
            False,
            "Belum ada candle 15m/1h dengan buy ≥ 55% + net Δ > 0 "
            "+ volume expansion",
            ignition=None,
        )
    surge = hit.get("surge_pct")
    surge_txt = "n/a" if surge is None else f"{surge:+.0f}%"
    detail = (
        f"{hit['tf']} ignition · buy {hit['buy_tx_pct']:.1f}% "
        f"· Δ {hit['delta_sol']:+.2f} SOL · vol {hit['volume_sol']:.2f} SOL "
        f"({surge_txt} vs kering)"
    )
    return _pillar(
        "p4_ignition",
        True,
        detail,
        ignition=hit,
    )


def classify_phase(pillars, *, stealth=False, vol_change_pct=None):
    """Human phase label for the day-by-day table / watchlist."""
    if stealth:
        return PHASE_STEALTH
    p = {item["id"]: item for item in (pillars or [])}
    if p.get("p4_ignition", {}).get("passed"):
        return PHASE_IGNITION
    if p.get("p3_supply", {}).get("passed") or _is_lps_drop(vol_change_pct):
        return PHASE_LPS
    if p.get("p1_flow", {}).get("passed"):
        return PHASE_ABSORPTION
    change = vol_change_pct
    if change is not None and _as_float(change) >= IGNITION_VOL_MIN_PCT:
        return PHASE_IGNITION
    if not p.get("p2_participation", {}).get("passed"):
        return PHASE_DUMP
    return PHASE_NORMAL


def evaluate_golden_checks(metrics, daily_rows=None, holder_lock_pct=None):
    """Return the 7 Setup Emas checks (pure, network-free)."""
    m = metrics or _empty_metrics()
    absorption = _as_float(m.get("absorption_pct"), 0.0)
    volume = _as_float(m.get("volume_sol"), 0.0)
    buy_pct = _as_float(m.get("buy_tx_pct"), 0.0)
    avg_buy = _as_float(m.get("avg_buy_sol"), 0.0)
    avg_sell = _as_float(m.get("avg_sell_sol"), 0.0)
    whale_net = _as_float(m.get("whale_net_sol"), 0.0)
    change = m.get("volume_change_pct")
    if change is None and daily_rows:
        change = (daily_rows[-1] or {}).get("volume_change_pct")
    lock = None if holder_lock_pct is None else _as_float(holder_lock_pct)
    cvd_ok = _p1_divergence_ok(daily_rows, m)
    absorbed = _is_absorbed_expansion(change, metrics=m)
    vol_ok = _p3_volume_ok(change, metrics=m)
    if absorbed:
        cvd_detail = "vol naik + CVD turun (penyerapan besar)"
        vol_detail = (
            "n/a" if change is None
            else f"Vol vs H-1 {_as_float(change):+.1f}% "
                 f"(ekspansi terserap)"
        )
    else:
        cvd_detail = (
            "CVD running datar/naik di support test"
            if cvd_ok else "CVD running turun"
        )
        vol_detail = (
            "n/a" if change is None
            else f"Vol vs H-1 {_as_float(change):+.1f}% "
                 f"(band -40%...-75%)"
        )
    return [
        {
            "id": "p1_absorption",
            "pillar": "p1",
            "title": "CVD Absorption",
            "passed": volume > 0 and absorption < CVD_ABSORPTION_PCT,
            "detail": f"|CVD/Vol| {absorption:.2f}% (ambang < 3.0%)",
        },
        {
            "id": "p1_cvd_flat",
            "pillar": "p1",
            "title": "Bullish Divergence",
            "passed": cvd_ok,
            "detail": cvd_detail,
        },
        {
            "id": "p2_buy_tx",
            "pillar": "p2",
            "title": "Buy TX Dominance",
            "passed": buy_pct >= BUY_TX_MIN_PCT,
            "detail": (
                f"Buy TX {buy_pct:.1f}% "
                f"(ambang >= {BUY_TX_MIN_PCT:g}%)"
            ),
        },
        {
            "id": "p2_order_size",
            "pillar": "p2",
            "title": "Order Size Discrepancy",
            "passed": avg_sell > avg_buy and avg_sell > 0,
            "detail": (
                f"Avg Sell {avg_sell:.3f} vs Avg Buy {avg_buy:.3f} SOL"
            ),
        },
        {
            "id": "p2_whale",
            "pillar": "p2",
            "title": "Whale Pressure Absorbed",
            "passed": whale_net < 0,
            "detail": f"Whale net {whale_net:+.2f} SOL",
        },
        {
            "id": "p3_lps",
            "pillar": "p3",
            "title": "Volume Kering LPS / Ekspansi Terserap",
            "passed": vol_ok,
            "detail": vol_detail,
        },
        {
            "id": "p3_lock",
            "pillar": "p3",
            "title": "Retensi Akumulator Bottom",
            "passed": lock is not None and lock >= SUPPLY_LOCK_MIN_PCT,
            "detail": (
                "lock n/a" if lock is None
                else f"Top-100 lock {lock:.1f}% (ambang >= 40%)"
            ),
        },
    ]


def golden_score(checks):
    """0-100: full weight if the check passed, else 0."""
    total = 0
    for item in checks or []:
        if item.get("passed"):
            total += int(GOLDEN_WEIGHTS.get(item.get("id"), 0))
    return int(total)


def is_setup_emas(evaluation) -> bool:
    """True when every golden check passed on a finished UTC day."""
    ev = evaluation or {}
    if ev.get("stealth_dump"):
        return False
    if not ev.get("date"):
        return False
    checks = ev.get("checks") or []
    if len(checks) == GOLDEN_TOTAL:
        return all(bool(c.get("passed")) for c in checks)
    try:
        passed = int(ev.get("passed") or 0)
        total = int(ev.get("total") or 0)
    except (TypeError, ValueError):
        return False
    verdict = ev.get("verdict")
    return (verdict in (VERDICT_EMAS, "SETUP EMAS", "PASS")
            and passed >= GOLDEN_TOTAL and total >= GOLDEN_TOTAL)


def _overall_verdict(checks, stealth):
    if stealth:
        return VERDICT_STEALTH, PHASE_STEALTH
    n = sum(1 for c in (checks or []) if c.get("passed"))
    if n >= GOLDEN_TOTAL:
        return VERDICT_EMAS, PHASE_EMAS
    if n >= 5:
        return VERDICT_WATCH, PHASE_LPS
    p2_ids = {"p2_buy_tx", "p2_order_size"}
    p2_ok = all(
        c.get("passed") for c in (checks or []) if c.get("id") in p2_ids
    )
    return VERDICT_FAIL, PHASE_DUMP if not p2_ok else PHASE_NORMAL


def _is_ignition_row(row):
    """True when a daily row is the markup/ignition print, not the setup.

    Volume expansion + CVD down + tight absorption is the setup
    (sellers hit into bids), not ignition. Ignition needs buyers winning
    the tape (Δ > 0).
    """
    if not row:
        return False
    change = row.get("volume_change_pct")
    if _is_absorbed_expansion(change, row=row):
        return False
    delta = _as_float(row.get("delta_sol"), 0.0)
    if change is not None and _as_float(change) >= IGNITION_VOL_MIN_PCT:
        return delta > 0
    status = str(row.get("status") or "")
    if "MARK-UP" in status or "IGNITION" in status:
        return True
    absorption = _row_absorption(row)
    buy_pct = _as_float(row.get("buy_tx_pct"), 0.0)
    return (absorption >= CVD_ABSORPTION_PCT
            and buy_pct >= IGNITION_BUY_PCT and delta > 0)


def _select_setup_row(rows):
    """Prefer the latest absorption/LPS day over a subsequent ignition day.

    P1/P2/P3 describe the floor (compression). Scoring them on the first
    ignition print falsely fails absorption because that candle is supposed
    to be one-sided buying.
    """
    rows = list(rows or [])
    if not rows:
        return {}
    latest = rows[-1]
    if not _is_ignition_row(latest):
        return latest
    for row in reversed(rows[:-1]):
        change = row.get("volume_change_pct")
        absorption = abs(_as_float(
            row.get("absorption_pct") if row.get("absorption_pct") is not None
            else row.get("cvd_ratio_pct"), 99.0))
        if (_is_lps_drop(change)
                or absorption < CVD_ABSORPTION_PCT
                or _is_absorbed_expansion(change, row=row)):
            return row
    return rows[-2] if len(rows) >= 2 else latest


def evaluate_prepump(swaps, *, daily_rows=None, holder_lock_pct=None,
                     price_series=None, now_ts=None, include_today=True):
    """Evaluate the 4 pillars on a swap sample.

    ``daily_rows`` may be precomputed (cron aggregation). When omitted the
    detector builds them from ``swaps``. Live UI should pass
    ``include_today=True`` so the still-running UTC day is scored; the
    daily digest should pass ``include_today=False``.
    """
    daily = list(daily_rows or calculate_daily_cvd(swaps))
    if not include_today:
        usable = complete_daily_rows(daily, now_ts=now_ts)
    else:
        usable = daily
    setup = _select_setup_row(usable)
    date = setup.get("date")
    if date:
        metrics = metrics_for_day(swaps, date)
        if setup.get("volume_change_pct") is not None:
            metrics["volume_change_pct"] = setup.get("volume_change_pct")
    else:
        metrics = compute_window_metrics(swaps)

    p1 = evaluate_pillar1_flow(metrics, usable)
    p2 = evaluate_pillar2_participation(metrics)
    p3 = evaluate_pillar3_supply(
        usable, holder_lock_pct=holder_lock_pct,
        price_series=price_series, metrics=metrics)
    p4 = evaluate_pillar4_ignition(swaps, usable, now_ts=now_ts)
    pillars = [p1, p2, p3, p4]
    stealth = bool(p2.get("stealth_dump"))
    checks = evaluate_golden_checks(
        metrics, usable, holder_lock_pct=holder_lock_pct)
    score = golden_score(checks)
    passed_n = sum(1 for c in checks if c.get("passed"))
    verdict, phase = _overall_verdict(checks, stealth)
    if stealth:
        phase = PHASE_STEALTH
    return {
        "date": date,
        "verdict": verdict,
        "phase": phase,
        "passed": passed_n,
        "total": GOLDEN_TOTAL,
        "score": score,
        "stealth_dump": stealth,
        "setup_emas": (
            not stealth and passed_n >= GOLDEN_TOTAL and bool(date)
        ),
        "metrics": metrics,
        "checks": checks,
        "pillars": pillars,
        "daily_rows": daily,
        "usable_rows": usable,
        "holder_lock_pct": (
            None if holder_lock_pct is None
            else _as_float(holder_lock_pct)
        ),
        "kpi": kpi_cards_from_eval(
            metrics, p1, p2, p3, p4, stealth=stealth),
    }


def kpi_cards_from_eval(metrics, p1, p2, p3, p4, *, stealth=False):
    """Four UI cards: absorption, buy-TX, order size, LPS/ignition."""
    m = metrics or _empty_metrics()
    absorption = _as_float(m.get("absorption_pct"), 0.0)
    buy_pct = _as_float(m.get("buy_tx_pct"), 0.0)
    avg_buy = _as_float(m.get("avg_buy_sol"), 0.0)
    avg_sell = _as_float(m.get("avg_sell_sol"), 0.0)
    change = m.get("volume_change_pct")
    if change is None:
        change = p3.get("volume_change_pct")
    lps = _is_lps_drop(change)
    absorbed = _is_absorbed_expansion(change, metrics=m)
    if lps:
        card4_label = "👀 SUPLAI KERING / LPS"
    elif absorbed:
        card4_label = "✅ PENYERAPAN BESAR"
    else:
        card4_label = "➖ NORMAL / BELUM KERING"
    change_txt = "n/a" if change is None else f"{_as_float(change):+.1f}%"
    return [
        {
            "id": "absorption",
            "title": "CVD Absorption",
            "value": f"{absorption:.2f}%",
            "passed": bool(p1.get("passed")),
            "label": ("✅ ABSORPTION KUAT" if p1.get("passed")
                      else "❌ TEKANAN JUAL/TIDAK SEIMBANG"),
            "hint": "|CVD / Volume|",
        },
        {
            "id": "buy_tx",
            "title": "Buy TX Dominance",
            "value": f"{buy_pct:.1f}%",
            "passed": buy_pct >= BUY_TX_MIN_PCT,
            "label": ("✅ AKUMULASI CICIL" if buy_pct >= BUY_TX_MIN_PCT
                      else "❌ DISTRIBUSI"),
            "hint": (
                f"Buy {m.get('buy_tx', 0)} ({buy_pct:.1f}%) vs "
                f"Sell {m.get('sell_tx', 0)} "
                f"({_as_float(m.get('sell_tx_pct'), 100.0 - buy_pct):.1f}%)"
            ),
        },
        {
            "id": "order_size",
            "title": "Order Size Discrepancy",
            "value": f"S {avg_sell:.3f} / B {avg_buy:.3f}",
            "passed": avg_sell > avg_buy and not stealth,
            "label": ("✅ RITEL PANIK DISERAP" if avg_sell > avg_buy
                      else "⚠️ PERINGATAN: STEALTH DUMP"),
            "hint": "Avg Sell vs Avg Buy (SOL)",
        },
        {
            "id": "lps",
            "title": "Volume & Suplai Kering",
            "value": change_txt,
            "passed": lps or absorbed,
            "label": card4_label,
            "hint": "% perubahan vol vs H-1",
        },
    ]


def format_watchlist_badge(evaluation):
    """Short label for the main-app sinyal column."""
    if not evaluation:
        return "➖ BELUM DIANALISIS"
    if evaluation.get("stealth_dump"):
        return "🔴 STEALTH DUMP"
    verdict = evaluation.get("verdict")
    passed = int(evaluation.get("passed") or 0)
    total = int(evaluation.get("total") or GOLDEN_TOTAL)
    score = evaluation.get("score")
    score_txt = f" · skor {int(score)}" if score is not None else ""
    if verdict == VERDICT_EMAS or evaluation.get("setup_emas"):
        return f"🥇 SETUP EMAS ({passed}/{total}{score_txt})"
    if verdict == VERDICT_WATCH:
        return f"🟡 WATCH ({passed}/{total}{score_txt})"
    return f"🔴 FAIL ({passed}/{total})"
