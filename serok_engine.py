"""SMART SEROK v9.1.3 signal engine (1H bars).

Ports the extension's bar aggregator and three live signals:
  WASPADA DUMP, SIAP2 PUMP, BATTLE TERJADI.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from reversal_engine import NOISE_TAGS, annotate_matched_amounts, normalize_trades

WASPADA_DUMP = "WASPADA DUMP"
SIAP2_PUMP = "SIAP2 PUMP"
BATTLE = "BATTLE TERJADI"
NEUTRAL = "NETRAL"

BAR_SEC = 3600
CLUSTER_GAP = 6 * BAR_SEC
MIN_CLUSTER_BARS = 4
MAX_BARS = 168
R_SPIKE_MULT = 10
R_MIN_ABS = 10
BATTLE_MAX_GAP_PCT = 2.5
BATTLE_ACTIVITY_PCTL = 0.65
BATTLE_MIN_BARS = 8
MIN_TX = 20
FRESH_TAG = "fresh_wallet"
WIB_OFF = 7 * 3600
TREND_BARS = 4


def bar_floor(ts: int, bar_sec: int = BAR_SEC) -> int:
    if bar_sec == 3600:
        return (int(ts) // 3600) * 3600
    local = int(ts) + WIB_OFF
    return (local // bar_sec) * bar_sec - WIB_OFF


def _has_fresh(tags) -> bool:
    for tag in tags or ():
        clean = str(tag or "").lower().replace(" ", "_").replace("-", "_")
        if clean == FRESH_TAG:
            return True
    return False


def percentile(values, p: float):
    arr = sorted(float(v) for v in values if v is not None)
    if not arr:
        return None
    if len(arr) == 1:
        return arr[0]
    p = max(0.0, min(1.0, float(p)))
    pos = (len(arr) - 1) * p
    lo = int(pos)
    hi = min(len(arr) - 1, lo + 1)
    w = pos - lo
    return arr[lo] + (arr[hi] - arr[lo]) * w


def _r_abs(bar: dict | None):
    if not bar or bar.get("R") is None:
        return None
    return abs(float(bar["R"]))


def build_bars(raw_trades: Iterable[Mapping], *, now_ts: int,
               mc_usd: float = 0.0, supply: float = 0.0,
               bar_sec: int = BAR_SEC) -> list[dict]:
    trades = normalize_trades(raw_trades)
    annotate_matched_amounts(trades)
    if not trades:
        return []

    maker_tags: dict[str, set[str]] = defaultdict(set)
    for trade in trades:
        for tag in trade.get("tags") or ():
            maker_tags[trade["maker"]].add(tag)

    buckets: dict[int, list[dict]] = defaultdict(list)
    for trade in trades:
        buckets[bar_floor(trade["ts"], bar_sec)].append(trade)

    bars = []
    for start in sorted(buckets):
        rows = sorted(buckets[start], key=lambda row: row["ts"])
        priced = [row for row in rows if row.get("price", 0) > 0]
        open_px = priced[0]["price"] if priced else None
        close_px = priced[-1]["price"] if priced else None
        high = max(row["price"] for row in priced) if priced else None
        low = min(row["price"] for row in priced) if priced else None
        cvd = cvd_clean = wash_vol = buy_sol = sell_sol = vol_usd = 0.0
        fresh_tx = fresh_buy = fresh_sell = 0.0
        volumes: dict[str, float] = defaultdict(float)
        tagged = set()
        fresh = set()
        for row in rows:
            sign = 1 if row["event"] == "buy" else -1
            union = list(maker_tags.get(row["maker"]) or row.get("tags") or ())
            is_noise = bool(NOISE_TAGS.intersection(union))
            removed = row["sol"] if is_noise else float(row.get("matched") or 0)
            cvd += sign * row["sol"]
            cvd_clean += sign * (row["sol"] - removed)
            wash_vol += removed
            if row["event"] == "buy":
                buy_sol += row["sol"]
            else:
                sell_sol += row["sol"]
            vol_usd += float(row.get("usd") or 0)
            volumes[row["maker"]] += row["sol"]
            if union:
                tagged.add(row["maker"])
            if _has_fresh(union):
                fresh.add(row["maker"])
                fresh_tx += 1
                if row["event"] == "buy":
                    fresh_buy += row["sol"]
                else:
                    fresh_sell += row["sol"]
        vol_sol = buy_sol + sell_sol
        price_chg = None
        if open_px and close_px and open_px > 0:
            price_chg = (close_px / open_px - 1.0) * 100.0
        r_abs = None
        if price_chg is not None and abs(price_chg) > 1e-9:
            r_abs = abs(cvd_clean) / abs(price_chg)
        signed_r = None if r_abs is None else (r_abs if cvd_clean >= 0 else -r_abs)
        top1 = max(volumes.values()) if volumes else 0.0
        bars.append({
            "start": start, "end": start + bar_sec,
            "open": open_px, "high": high, "low": low, "close": close_px,
            "price_chg_pct": price_chg, "cvd": cvd, "cvdClean": cvd_clean,
            "buySol": buy_sol, "sellSol": sell_sol, "volSol": vol_sol,
            "volUsd": vol_usd, "washVol": wash_vol,
            "washPct": (wash_vol / vol_sol * 100.0) if vol_sol else 0.0,
            "txCount": len(rows), "uniqueMakers": len(volumes),
            "taggedMakers": len(tagged),
            "freshWallets": len(fresh),
            "freshWalletPct": (len(fresh) / len(volumes) * 100.0) if volumes else 0.0,
            "freshTxCount": int(fresh_tx),
            "freshBuySol": fresh_buy, "freshSellSol": fresh_sell,
            "topWalletPct": (top1 / vol_sol * 100.0) if vol_sol else 0.0,
            "R": r_abs, "signedR": signed_r,
            "partial": (start + bar_sec) > int(now_ts),
        })

    if len(bars) > MAX_BARS:
        bars = bars[-MAX_BARS:]

    latest = next((bar for bar in reversed(bars)
                   if bar.get("close") and bar["close"] > 0), None)
    inferred = (mc_usd / latest["close"]) if (mc_usd > 0 and latest) else 0.0
    mc_per = supply if supply > 0 else inferred
    for bar in bars:
        bar["mcPerPrice"] = mc_per or None
        for key, src in (("openMc", "open"), ("highMc", "high"),
                         ("lowMc", "low"), ("closeMc", "close")):
            px = bar.get(src)
            bar[key] = (px * mc_per) if (mc_per and px is not None) else None

    cluster = 0
    cum = 0.0
    for i, bar in enumerate(bars):
        if i and bar["start"] - bars[i - 1]["start"] > CLUSTER_GAP:
            cluster += 1
        bar["cluster"] = cluster
        cum += bar["cvdClean"]
        bar["cumCVD"] = cum
    return bars


def latest_cluster(bars: list[dict]) -> list[dict]:
    if not bars or len(bars) <= 1:
        return list(bars or ())
    breaks = [0]
    for i in range(1, len(bars)):
        if bars[i]["start"] - bars[i - 1]["start"] > CLUSTER_GAP:
            breaks.append(i)
    start = breaks[-1]
    if len(bars) - start < MIN_CLUSTER_BARS and len(breaks) >= 2:
        start = breaks[-2]
    return bars[start:]


def battle_thresholds(bars: list[dict]) -> dict | None:
    done = [bar for bar in bars if not bar.get("partial") and (bar.get("volSol") or 0) > 0]
    if len(done) < BATTLE_MIN_BARS:
        return None
    return {
        "tx": percentile([bar["txCount"] for bar in done], BATTLE_ACTIVITY_PCTL),
        "makers": percentile([bar["uniqueMakers"] for bar in done], BATTLE_ACTIVITY_PCTL),
        "fresh": percentile([bar["freshWallets"] for bar in done], BATTLE_ACTIVITY_PCTL),
        "freshTagsSeen": any((bar.get("freshWallets") or 0) > 0 for bar in done),
        "samples": len(done),
    }


def battle_stats(bar: dict, thresholds: dict | None) -> dict | None:
    if not bar or not thresholds or bar.get("partial") or not (bar.get("volSol") or 0) > 0:
        return None
    gap = abs((bar.get("buySol") or 0) - (bar.get("sellSol") or 0)) / bar["volSol"] * 100.0
    tx_floor = max(MIN_TX, thresholds.get("tx") or 0)
    makers_floor = thresholds.get("makers") or 0
    fresh_floor = max(1, thresholds.get("fresh") or 0)
    if (not thresholds.get("freshTagsSeen") or gap > BATTLE_MAX_GAP_PCT
            or (bar.get("txCount") or 0) < tx_floor
            or (bar.get("uniqueMakers") or 0) < makers_floor
            or (bar.get("freshWallets") or 0) < fresh_floor):
        return None
    return {"gapPct": gap, "txFloor": tx_floor, "makersFloor": makers_floor,
            "freshFloor": fresh_floor, "samples": thresholds["samples"]}


def _price_trend(bars, i, n=TREND_BARS) -> float:
    j = max(0, i - n)
    a = (bars[j] or {}).get("close")
    b = (bars[i] or {}).get("close")
    if not a or not b:
        return 0.0
    return (b / a - 1.0) * 100.0


def _make_setup(kind, bar, i, prev, r_mult, bars) -> dict:
    return {
        "signal": kind,
        "setup": bar,
        "confirm": bar,
        "setupIdx": i,
        "confirmIdx": i,
        "event_id": f"{kind}:{bar['start']}",
        "ev": {
            "rMult": r_mult,
            "prevR": _r_abs(prev),
            "setupR": bar.get("signedR") if bar.get("signedR") is not None else bar.get("R"),
            "setupChg": bar.get("price_chg_pct"),
            "setupCvd": bar.get("cvdClean"),
            "trend": _price_trend(bars, i),
        },
    }


def _make_battle(bar, i, stats, trigger) -> dict:
    return {
        "signal": BATTLE,
        "setup": bar,
        "confirm": bar,
        "setupIdx": i,
        "confirmIdx": i,
        "event_id": f"{BATTLE}:{bar['start']}",
        "ev": {
            "balanceGapPct": stats["gapPct"],
            "txFloor": stats["txFloor"],
            "makersFloor": stats["makersFloor"],
            "freshFloor": stats["freshFloor"],
            "activitySamples": stats["samples"],
            "rangeLowMc": bar.get("lowMc"),
            "rangeHighMc": bar.get("highMc"),
            "triggerSignal": trigger["signal"],
            "triggerStart": trigger["confirm"]["start"],
            "gap": i - trigger["confirmIdx"],
            "setupChg": bar.get("price_chg_pct"),
        },
    }


def scan_signals(bars: list[dict]) -> list[dict]:
    events = []
    thresholds = battle_thresholds(bars)
    latest_setup = None
    for i, bar in enumerate(bars):
        prev = bars[i - 1] if i else None
        prior_setup = latest_setup
        if (prev and bar.get("price_chg_pct") is not None
                and bar.get("cumCVD") is not None
                and prev.get("cumCVD") is not None):
            a, b = _r_abs(prev), _r_abs(bar)
            if a and b and a > 1e-9:
                r_mult = b / a
                if r_mult >= R_SPIKE_MULT and b >= R_MIN_ABS:
                    setup = None
                    if bar["price_chg_pct"] > 0 and bar["cumCVD"] > prev["cumCVD"]:
                        setup = _make_setup(WASPADA_DUMP, bar, i, prev, r_mult, bars)
                    elif bar["price_chg_pct"] < 0 and bar["cumCVD"] < prev["cumCVD"]:
                        setup = _make_setup(SIAP2_PUMP, bar, i, prev, r_mult, bars)
                    if setup:
                        events.append(setup)
                        latest_setup = setup
        stats = battle_stats(bar, thresholds)
        if stats and prior_setup and prior_setup["confirmIdx"] < i:
            events.append(_make_battle(bar, i, stats, prior_setup))
    return events


def classify(bars: list[dict]) -> dict:
    cluster = latest_cluster(bars)
    if not cluster:
        return {"signal": NEUTRAL, "reason": "butuh data bar",
                "events": [], "bars": [], "current": {}}
    events = scan_signals(cluster)
    last = cluster[-1]
    current = {
        "cvd_delta_clean": last.get("cvdClean"),
        "wash_pct": last.get("washPct"),
        "price_chg_pct": last.get("price_chg_pct"),
        "tx_count": last.get("txCount"),
        "vol_sol": last.get("volSol"),
        "unique_makers": last.get("uniqueMakers"),
        "fresh_buy": last.get("freshWallets"),
        "fresh_buy_sol": last.get("freshBuySol"),
        "top_wallet_pct": last.get("topWalletPct"),
        "buy_sol": last.get("buySol"),
        "sell_sol": last.get("sellSol"),
        "R": last.get("R"),
        "signedR": last.get("signedR"),
        "bar_start": last.get("start"),
        "partial": last.get("partial"),
        "fresh_wallets": last.get("freshWallets"),
        "fresh_wallet_pct": last.get("freshWalletPct"),
    }
    if not events:
        reason = (f"NETRAL — battle butuh ≥{BATTLE_MIN_BARS} bar selesai; "
                  f"klaster terakhir {len(cluster)} bar."
                  if len(cluster) < BATTLE_MIN_BARS else
                  "NETRAL — belum ada WASPADA DUMP / SIAP2 PUMP / BATTLE TERJADI.")
        return {"signal": NEUTRAL, "reason": reason, "events": events,
                "bars": cluster, "current": current, "event": None}
    event = events[-1]
    return {
        "signal": event["signal"],
        "reason": "",
        "events": events,
        "bars": cluster,
        "current": current,
        "event": event,
        "event_id": event["event_id"],
    }
