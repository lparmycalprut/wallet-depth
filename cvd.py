# -*- coding: utf-8 -*-
"""On-chain CVD (Cumulative Volume Delta) via Helius Enhanced API.

Every DEX swap has a definite direction (no aggressor guessing like on CEX):
  token OUT of pool  -> user BUY
  token INTO pool    -> user SELL
Volumes are measured in SOL (the quote side of the pool).

Data is stored in cvd.json as hourly buckets per CA:
  {ca: {"pool": str, "newest_sig": str, "newest_ts": int,
        "buckets": {hour_ts: {bs, ss, nb, ns, wbs, wss}}}}
  bs/ss  = buy/sell volume (SOL)   nb/ns = trade counts
  wbs/wss = whale buy/sell volume (SOL), swaps >= WHALE_SOL
Small swaps below MIN_SOL are ignored entirely (bot dust noise).
"""
import json
import os
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CVD_PATH = os.path.join(BASE_DIR, "cvd.json")

SOL_MINT = "So11111111111111111111111111111111111111112"
MIN_SOL = 0.05      # ignore swaps below (~$10) — bot/dust noise
WHALE_SOL = 3.0     # swaps >= this (~$500+) count as whale flow
BUCKET = 3600       # 1-hour buckets (resampled to H4 for divergence)


def load_cvd() -> dict:
    try:
        with open(CVD_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_cvd(state: dict) -> None:
    with open(CVD_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, separators=(",", ":"))


def classify_swap(tx: dict, pool: str, ca: str):
    """Return (side, sol_amount, ts, wallet) or None."""
    ca_in = ca_out = sol_in = sol_out = 0.0
    for x in (tx.get("tokenTransfers") or []):
        amt = float(x.get("tokenAmount") or 0)
        mint = x.get("mint")
        if mint == ca:
            if x.get("fromUserAccount") == pool:
                ca_out += amt
            elif x.get("toUserAccount") == pool:
                ca_in += amt
        elif mint == SOL_MINT:
            if x.get("fromUserAccount") == pool:
                sol_out += amt
            elif x.get("toUserAccount") == pool:
                sol_in += amt
    ts = tx.get("timestamp") or 0
    wallet = tx.get("feePayer") or ""
    if ca_out > ca_in and sol_in > 0:      # token left pool -> BUY
        return ("buy", sol_in, ts, wallet)
    if ca_in > ca_out and sol_out > 0:     # token entered pool -> SELL
        return ("sell", sol_out, ts, wallet)
    return None


def fetch_swaps(api_key: str, pool: str, ca: str, *, stop_sig=None,
                stop_ts=None, max_pages=40, sleep=0.15):
    """Fetch swaps newest-first until stop_sig/stop_ts/max_pages.
    Returns (swaps, newest_sig, newest_ts, hit_stop)."""
    swaps, before = [], None
    newest_sig, newest_ts, hit_stop = None, None, False
    for _ in range(max_pages):
        params = {"api-key": api_key, "limit": 100, "type": "SWAP"}
        if before:
            params["before"] = before
        try:
            r = requests.get(
                f"https://api.helius.xyz/v0/addresses/{pool}/transactions",
                params=params, headers={"User-Agent": "Mozilla/5.0"},
                timeout=40)
            if r.status_code != 200:
                break
            page = r.json()
        except Exception:
            break
        if not page:
            break
        if newest_sig is None:
            newest_sig = page[0].get("signature")
            newest_ts = page[0].get("timestamp")
        for tx in page:
            if stop_sig and tx.get("signature") == stop_sig:
                hit_stop = True
                break
            if stop_ts and (tx.get("timestamp") or 0) <= stop_ts:
                hit_stop = True
                break
            s = classify_swap(tx, pool, ca)
            if s and s[1] >= MIN_SOL:
                swaps.append(s)
        if hit_stop:
            break
        before = page[-1].get("signature")
        time.sleep(sleep)
    return swaps, newest_sig, newest_ts, hit_stop


def bucketize(swaps) -> dict:
    out = {}
    for s in swaps:
        side, sol, ts = s[0], s[1], s[2]
        b = str(int(ts // BUCKET * BUCKET))
        c = out.setdefault(b, {"bs": 0.0, "ss": 0.0, "nb": 0, "ns": 0,
                               "wbs": 0.0, "wss": 0.0})
        if side == "buy":
            c["bs"] += sol
            c["nb"] += 1
            if sol >= WHALE_SOL:
                c["wbs"] += sol
        else:
            c["ss"] += sol
            c["ns"] += 1
            if sol >= WHALE_SOL:
                c["wss"] += sol
    return out


def update_token_cvd(api_key: str, ca: str, pool: str, *,
                     max_pages=40) -> dict:
    """Incremental update: fetch swaps since last stored signature."""
    state = load_cvd()
    entry = state.get(ca) or {"pool": pool, "buckets": {}}
    stop_sig = entry.get("newest_sig")
    stop_ts = entry.get("newest_ts")
    swaps, new_sig, new_ts, hit = fetch_swaps(
        api_key, pool, ca, stop_sig=stop_sig, stop_ts=stop_ts,
        max_pages=max_pages)
    fresh = bucketize(swaps)
    for b, c in fresh.items():
        old = entry["buckets"].get(b)
        if old:
            for k in c:
                old[k] = old.get(k, 0) + c[k]
        else:
            entry["buckets"][b] = c
    if new_sig:
        entry["newest_sig"] = new_sig
        entry["newest_ts"] = new_ts
    entry["pool"] = pool
    entry["gap"] = bool(stop_sig) and not hit and bool(swaps)
    entry["updated"] = int(time.time())
    # keep last 14 days only
    cutoff = time.time() - 14 * 86400
    entry["buckets"] = {b: c for b, c in entry["buckets"].items()
                        if int(b) >= cutoff}
    state[ca] = entry
    save_cvd(state)
    return {"new_swaps": len(swaps), "buckets": len(entry["buckets"]),
            "gap": entry["gap"]}


# ---------------------------------------------------------------------------
# Divergence detection (pivot-based, non-repainting)
# ---------------------------------------------------------------------------
def find_pivots(vals, left=2, right=2):
    """Indices of local highs/lows confirmed by `left`/`right` neighbours."""
    highs, lows = [], []
    for i in range(left, len(vals) - right):
        win_l = vals[i - left:i]
        win_r = vals[i + 1:i + 1 + right]
        if vals[i] > max(win_l) and vals[i] >= max(win_r):
            highs.append(i)
        if vals[i] < min(win_l) and vals[i] <= min(win_r):
            lows.append(i)
    return highs, lows


def detect_divergence(price, cvd, left=2, right=2):
    """Compare the two most recent confirmed pivots of price vs CVD.
    Returns list of dicts {type, kind, i1, i2, detail}."""
    out = []
    if len(price) < left + right + 3:
        return out
    ph, pl = find_pivots(price, left, right)
    # bearish regular: price HH, cvd LH
    if len(ph) >= 2:
        a, b = ph[-2], ph[-1]
        if price[b] > price[a] and cvd[b] < cvd[a]:
            out.append({"type": "bearish", "kind": "regular", "i1": a, "i2": b,
                        "detail": "price higher-high but CVD lower-high — "
                                  "buys are NOT confirming the pump"})
        elif price[b] < price[a] and cvd[b] > cvd[a]:
            out.append({"type": "bearish", "kind": "hidden", "i1": a, "i2": b,
                        "detail": "price lower-high but CVD higher-high — "
                                  "heavy buying absorbed without new highs "
                                  "(seller in control)"})
    # bullish regular: price LL, cvd HL
    if len(pl) >= 2:
        a, b = pl[-2], pl[-1]
        if price[b] < price[a] and cvd[b] > cvd[a]:
            out.append({"type": "bullish", "kind": "regular", "i1": a, "i2": b,
                        "detail": "price lower-low but CVD higher-low — "
                                  "selling is drying up / being absorbed "
                                  "(accumulation)"})
        elif price[b] > price[a] and cvd[b] < cvd[a]:
            out.append({"type": "bullish", "kind": "hidden", "i1": a, "i2": b,
                        "detail": "price higher-low but CVD lower-low — "
                                  "dip was sold hard yet price held "
                                  "(strong bid underneath)"})
    return out


def get_h4_series(ca: str, hours_span=None):
    """Resample the hourly buckets into H4: returns (ts_list, cvd, whale_cvd,
    retail_cvd, buy_vol, sell_vol) aligned oldest->newest."""
    state = load_cvd()
    entry = state.get(ca)
    if not entry or not entry.get("buckets"):
        return None
    buckets = {int(k): v for k, v in entry["buckets"].items()}
    tmin, tmax = min(buckets), max(buckets)
    if hours_span:
        tmin = max(tmin, tmax - hours_span * 3600)
    h4 = {}
    for ts, c in buckets.items():
        if ts < tmin:
            continue
        b4 = ts // 14400 * 14400
        agg = h4.setdefault(b4, {"bs": 0.0, "ss": 0.0, "wbs": 0.0,
                                 "wss": 0.0, "nb": 0, "ns": 0})
        for k in agg:
            agg[k] += c.get(k, 0)
    ts_sorted = sorted(h4)
    cvd, wcvd, rcvd, bv, sv = [], [], [], [], []
    c = w = rr = 0.0
    for t in ts_sorted:
        a = h4[t]
        c += a["bs"] - a["ss"]
        w += a["wbs"] - a["wss"]
        rr += (a["bs"] - a["wbs"]) - (a["ss"] - a["wss"])
        cvd.append(c)
        wcvd.append(w)
        rcvd.append(rr)
        bv.append(a["bs"])
        sv.append(a["ss"])
    return {"ts": ts_sorted, "cvd": cvd, "whale": wcvd, "retail": rcvd,
            "buy": bv, "sell": sv, "updated": entry.get("updated"),
            "gap": entry.get("gap", False)}


def get_series(ca: str, bucket_hours: int = 1, hours_span: int = None):
    """Resample hourly buckets into N-hour candles. Returns dict with ts,
    cvd, whale, retail, buy, sell lists (oldest->newest) or None."""
    state = load_cvd()
    entry = state.get(ca)
    if not entry or not entry.get("buckets"):
        return None
    buckets = {int(k): v for k, v in entry["buckets"].items()}
    tmax = max(buckets)
    tmin = min(buckets)
    if hours_span:
        tmin = max(tmin, tmax - hours_span * 3600)
    step = bucket_hours * 3600
    agg = {}
    for ts, c in buckets.items():
        if ts < tmin:
            continue
        b = ts // step * step
        a = agg.setdefault(b, {"bs": 0.0, "ss": 0.0, "wbs": 0.0,
                               "wss": 0.0, "nb": 0, "ns": 0})
        for k in a:
            a[k] += c.get(k, 0)
    ts_sorted = sorted(agg)
    cvd, wcvd, rcvd, bv, sv = [], [], [], [], []
    c = w = rr = 0.0
    for t in ts_sorted:
        a = agg[t]
        c += a["bs"] - a["ss"]
        w += a["wbs"] - a["wss"]
        rr += (a["bs"] - a["wbs"]) - (a["ss"] - a["wss"])
        cvd.append(c)
        wcvd.append(w)
        rcvd.append(rr)
        bv.append(a["bs"])
        sv.append(a["ss"])
    return {"ts": ts_sorted, "cvd": cvd, "whale": wcvd, "retail": rcvd,
            "buy": bv, "sell": sv, "updated": entry.get("updated"),
            "gap": entry.get("gap", False)}


def fetch_price_series(pool: str, bucket_hours: int = 1, limit: int = 100):
    """GeckoTerminal candles -> {bucket_ts: close}."""
    res, aggr = ("hour", bucket_hours) if bucket_hours in (1, 4, 12) else \
        ("hour", 1)
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pool}/ohlcv/{res}", params={"aggregate": aggr, "limit": limit},
            headers={"accept": "application/json"}, timeout=20)
        lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list") or []
    except Exception:
        return {}
    return {int(x[0]): float(x[4]) for x in reversed(lst)}


def fetch_h4_price(pool: str, limit=42):
    """GeckoTerminal 4h candles -> {ts: close} oldest->newest."""
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pool}/ohlcv/hour", params={"aggregate": 4, "limit": limit},
            headers={"accept": "application/json"}, timeout=20)
        lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list") or []
    except Exception:
        return {}
    return {int(x[0]): float(x[4]) for x in reversed(lst)}
