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
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
MIN_SOL = 0.05      # ignore swaps below (~$10) — bot/dust noise
WHALE_SOL = 3.0     # swaps >= this (~$500+) count as whale flow
BUCKET = 3600       # 1-hour buckets (resampled to H4 for divergence)

_sol_price_cache = {"price": 0.0, "ts": 0.0}

# ---------------------------------------------------------------------------
# Helius key pool — rotate across multiple free keys on rate limits.
# Sources (merged): env HELIUS_API_KEYS (comma-sep), env HELIUS_API_KEY,
# config.json helius_api_key + helius_extra_keys, streamlit secrets.
# ---------------------------------------------------------------------------
_key_pool = {"keys": [], "idx": 0, "loaded": 0.0}


def _load_key_pool() -> list:
    now = time.time()
    if _key_pool["keys"] and now - _key_pool["loaded"] < 300:
        return _key_pool["keys"]
    keys = []

    def _add(v):
        for k in str(v or "").replace("\n", ",").split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)

    _add(os.environ.get("HELIUS_API_KEYS"))
    _add(os.environ.get("HELIUS_API_KEY"))
    try:
        with open(os.path.join(BASE_DIR, "config.json")) as f:
            cfg = json.load(f) or {}
        _add(cfg.get("helius_api_key"))
        _add(cfg.get("helius_extra_keys"))
    except Exception:
        pass
    try:
        import streamlit as st
        _add(st.secrets.get("helius_api_key", ""))
        _add(st.secrets.get("helius_extra_keys", ""))
    except Exception:
        pass
    _key_pool["keys"] = keys
    _key_pool["loaded"] = now
    return keys


def _next_key(current: str | None = None) -> str | None:
    """Round-robin to the next key in the pool (skipping `current`)."""
    keys = _load_key_pool()
    if not keys:
        return current
    _key_pool["idx"] = (_key_pool["idx"] + 1) % len(keys)
    k = keys[_key_pool["idx"]]
    if k == current and len(keys) > 1:
        _key_pool["idx"] = (_key_pool["idx"] + 1) % len(keys)
        k = keys[_key_pool["idx"]]
    return k


def helius_rpc_post(payload: dict, timeout: int = 30, retries: int = 3):
    """JSON-RPC POST with key rotation on 429/5xx. Returns dict or None."""
    key = _load_key_pool()[0] if _load_key_pool() else None
    if not key:
        return None
    delay = 0.5
    for _ in range(retries):
        try:
            r = requests.post(f"https://mainnet.helius-rpc.com/?api-key={key}",
                              json=payload, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                key = _next_key(key) or key
        except Exception:
            pass
        time.sleep(delay)
        delay *= 2
    return None


def get_sol_price() -> float:
    """SOL/USD price, cached 10 min — used to convert USDC/USDT-quoted
    pools into SOL-equivalent so thresholds stay consistent."""
    now = time.time()
    if _sol_price_cache["price"] > 0 and \
            now - _sol_price_cache["ts"] < 600:
        return _sol_price_cache["price"]
    try:
        r = requests.get(
            "https://api.dexscreener.com/latest/dex/tokens/" + SOL_MINT,
            timeout=15)
        pairs = (r.json() or {}).get("pairs") or []
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                   reverse=True)
        px = float(pairs[0].get("priceUsd") or 0) if pairs else 0.0
        if px > 0:
            _sol_price_cache.update(price=px, ts=now)
            return px
    except Exception:
        pass
    return _sol_price_cache["price"] or 150.0  # sane fallback


def _quote_rates() -> dict:
    """mint -> SOL per 1 unit of that quote token."""
    sp = get_sol_price()
    usd_to_sol = 1.0 / sp if sp else 0.0
    return {SOL_MINT: 1.0, USDC_MINT: usd_to_sol, USDT_MINT: usd_to_sol}


def _load_json_tolerant(path):
    """Load JSON; if the file contains git conflict markers, parse the
    newest side of the conflict instead of failing."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    if "<<<<<<<" in raw:
        import re as _re
        m = _re.search(r"<<<<<<<[^\n]*\n(.*?)\n=======\n(.*?)\n>>>>>>>",
                       raw, _re.S)
        if m:
            for side in (m.group(2), m.group(1)):  # prefer incoming side
                try:
                    return json.loads(side)
                except Exception:
                    continue
    return None


def load_cvd() -> dict:
    return _load_json_tolerant(CVD_PATH) or {}


def save_cvd(state: dict) -> None:
    with open(CVD_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, separators=(",", ":"))


def classify_swap(tx: dict, pool: str, ca: str):
    """Return (side, sol_equivalent, ts, wallet) or None.
    Works for SOL-quoted AND USDC/USDT-quoted pools (converted to SOL)."""
    rates = _quote_rates()
    ca_in = ca_out = 0.0
    q_in = q_out = 0.0   # quote value in SOL-equivalent
    for x in (tx.get("tokenTransfers") or []):
        amt = float(x.get("tokenAmount") or 0)
        mint = x.get("mint")
        if mint == ca:
            if x.get("fromUserAccount") == pool:
                ca_out += amt
            elif x.get("toUserAccount") == pool:
                ca_in += amt
        elif mint in rates:
            sol_eq = amt * rates[mint]
            if x.get("fromUserAccount") == pool:
                q_out += sol_eq
            elif x.get("toUserAccount") == pool:
                q_in += sol_eq
    ts = tx.get("timestamp") or 0
    wallet = tx.get("feePayer") or ""
    if ca_out > ca_in and q_in > 0:        # token left pool -> BUY
        return ("buy", q_in, ts, wallet)
    if ca_in > ca_out and q_out > 0:       # token entered pool -> SELL
        return ("sell", q_out, ts, wallet)
    return None


def _fetch_page(api_key: str, pool: str, before=None, *, retries=4):
    """One Enhanced-API page with retries + backoff + KEY ROTATION.
    On 429/5xx the next attempt uses the next key in the pool."""
    params = {"limit": 100, "type": "SWAP"}
    if before:
        params["before"] = before
    key = api_key or _next_key()
    delay = 0.6
    for attempt in range(retries):
        try:
            r = requests.get(
                f"https://api.helius.xyz/v0/addresses/{pool}/transactions",
                params={**params, "api-key": key},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                key = _next_key(key) or key   # rotate to another free key
        except Exception:
            pass
        time.sleep(delay)
        delay *= 2
    return None


def fetch_swaps(api_key: str, pool: str, ca: str, *, stop_sig=None,
                stop_ts=None, max_pages=40, sleep=0.15):
    """Fetch swaps newest-first until stop_sig/stop_ts/max_pages.
    Returns (swaps, newest_sig, newest_ts, hit_stop)."""
    swaps, before = [], None
    newest_sig, newest_ts, hit_stop = None, None, False
    for _ in range(max_pages):
        page = _fetch_page(api_key, pool, before)
        if page is None:   # all retries failed -> stop but keep what we have
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
    """Incremental update: fetch swaps since last stored signature.
    Also keeps raw swaps of the last 24h (with wallets) so the dashboard
    can show a COMPLETE window without a huge live fetch."""
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
    # --- raw swap store (last 24h, incl. wallet) for complete-window UI ----
    cutoff_raw = time.time() - 48 * 3600
    raw = entry.get("swaps") or []
    raw.extend([list(s) for s in swaps])
    entry["swaps"] = [s for s in raw if (s[2] or 0) >= cutoff_raw]
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
# Wallet behaviour profiling — pure accumulators / distributors
# ---------------------------------------------------------------------------
def wallet_profiles(swaps, *, pure_tol=0.05):
    """Classify wallets by behaviour within the window.
    swaps: iterable of (side, sol, ts, wallet).
    profile: 'pure_accum' (sells <= 5% of buys), 'pure_dist'
    (buys <= 5% of sells), or 'two_way'."""
    w = {}
    for side, sol, ts, wallet in swaps:
        if not wallet:
            continue
        d = w.setdefault(wallet, {"buy": 0.0, "sell": 0.0, "n_buy": 0,
                                  "n_sell": 0, "max_swap": 0.0,
                                  "first_ts": ts, "last_ts": ts})
        if side == "buy":
            d["buy"] += sol
            d["n_buy"] += 1
        else:
            d["sell"] += sol
            d["n_sell"] += 1
        d["max_swap"] = max(d["max_swap"], sol)
        d["first_ts"] = min(d["first_ts"], ts)
        d["last_ts"] = max(d["last_ts"], ts)
    for wallet, d in w.items():
        if d["buy"] > 0 and d["sell"] <= d["buy"] * pure_tol:
            d["profile"] = "pure_accum"
        elif d["sell"] > 0 and d["buy"] <= d["sell"] * pure_tol:
            d["profile"] = "pure_dist"
        else:
            d["profile"] = "two_way"
        vol = d["buy"] + d["sell"]
        d["dca"] = (d["n_buy"] + d["n_sell"]) >= 4 and \
            d["max_swap"] < vol * 0.5
    return w


def conviction_split(profiles, *, whale_min_sol=3.0):
    """How much whale-sized buy volume is 'pure' (bought & held) vs
    recycled by two-way traders. Same for the sell side."""
    pure_buy = tw_buy = pure_sell = tw_sell = 0.0
    for d in profiles.values():
        if d["profile"] == "pure_accum" and d["buy"] >= whale_min_sol:
            pure_buy += d["buy"]
        elif d["profile"] == "pure_dist" and d["sell"] >= whale_min_sol:
            pure_sell += d["sell"]
        elif d["profile"] == "two_way":
            tw_buy += d["buy"]
            tw_sell += d["sell"]
    total_buy = pure_buy + tw_buy
    conviction = pure_buy / total_buy * 100 if total_buy else 0.0
    return {"pure_buy": pure_buy, "pure_sell": pure_sell,
            "tw_buy": tw_buy, "tw_sell": tw_sell,
            "conviction_pct": conviction}


# ---------------------------------------------------------------------------
# Conviction history — recorded by the cron every run, shown on the landing
# page so LP players can see at a glance whether a pair is still alive.
# ---------------------------------------------------------------------------
CONV_PATH = os.path.join(BASE_DIR, "conviction.json")


_conv_remote_cache = {"data": None, "ts": 0.0}


def load_conviction() -> dict:
    """{ca: [{ts, conviction, pure_buy, pure_sell, net_pure, vol}]}

    On Streamlit Cloud the local file is frozen at deploy time while the
    hourly cron keeps committing fresh points to the repo — so if the
    local copy looks stale (newest point older than ~90 min), pull the
    fresh copy from GitHub raw (cached 10 min) and merge."""
    local = _load_json_tolerant(CONV_PATH) or {}

    newest = 0
    for pts in local.values():
        if pts:
            newest = max(newest, pts[-1].get("ts") or 0)
    fresh_enough = newest and (time.time() - newest) < 90 * 60
    if fresh_enough:
        return local

    now = time.time()
    if _conv_remote_cache["data"] is not None and \
            now - _conv_remote_cache["ts"] < 600:
        remote = _conv_remote_cache["data"]
    else:
        remote = None
        try:
            r = requests.get(
                "https://raw.githubusercontent.com/lparmycalprut/"
                "wallet-depth/main/conviction.json",
                params={"t": int(now)}, timeout=10)
            if r.status_code == 200:
                remote = r.json() or {}
                _conv_remote_cache.update(data=remote, ts=now)
        except Exception:
            pass
    if not remote:
        return local

    # merge: union of points per CA, dedup by ts
    merged = dict(local)
    for ca, pts in remote.items():
        seen = {p["ts"] for p in merged.get(ca, [])}
        merged.setdefault(ca, [])
        merged[ca].extend([p for p in pts if p["ts"] not in seen])
        merged[ca].sort(key=lambda p: p["ts"])
    try:
        with open(CONV_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, separators=(",", ":"))
    except Exception:
        pass
    return merged


def record_conviction(ca: str, *, window_h: int = 6) -> dict | None:
    """Compute conviction over the last `window_h` from the swap store and
    append it to conviction.json. Returns the point or None."""
    swaps = get_recent_swaps(ca, window_h)
    if not swaps:
        return None
    profiles = wallet_profiles(swaps)
    conv = conviction_split(profiles, whale_min_sol=WHALE_SOL)
    vol = sum(s[1] for s in swaps)
    point = {"ts": int(time.time()),
             "conviction": round(conv["conviction_pct"], 1),
             "pure_buy": round(conv["pure_buy"], 1),
             "pure_sell": round(conv["pure_sell"], 1),
             "net_pure": round(conv["pure_buy"] - conv["pure_sell"], 1),
             "vol": round(vol, 1), "swaps": len(swaps)}
    hist = load_conviction()
    arr = hist.setdefault(ca, [])
    arr.append(point)
    # keep last 7 days of points
    cutoff = time.time() - 7 * 86400
    hist[ca] = [p for p in arr if p["ts"] >= cutoff]
    try:
        with open(CONV_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f, separators=(",", ":"))
    except Exception:
        pass
    return point


def get_recent_swaps(ca: str, hours: int = 12):
    """Raw swaps [(side, sol, ts, wallet)] from the store, last N hours (store keeps 48h)."""
    state = load_cvd()
    entry = state.get(ca)
    if not entry or not entry.get("swaps"):
        return []
    cutoff = time.time() - hours * 3600
    out = [tuple(s) for s in entry["swaps"] if (s[2] or 0) >= cutoff]
    out.sort(key=lambda s: s[2])
    return out


# ---------------------------------------------------------------------------
# Market phase detection (Wyckoff-style heuristic, read-only)
# ---------------------------------------------------------------------------
def detect_phase(ca: str, price_change_24h: float | None = None) -> dict:
    """Classify the market phase from data we ALREADY have:
    conviction history (conviction.json) + 24h price change (DexScreener,
    passed in by the caller — no new fetches here).

    Returns {"phase": str, "confidence": "low"|"medium"|"high",
             "reason": short explanation for the tooltip}.
    Heuristic only — not a trading signal.
    """
    pts = (load_conviction() or {}).get(ca) or []
    if not pts:
        return {"phase": "Neutral/Choppy", "confidence": "low",
                "reason": "no conviction history yet (cron still filling)"}

    last = pts[-1]
    cv = float(last.get("conviction") or 0)
    np_now = float(last.get("net_pure") or 0)
    vol_now = float(last.get("vol") or 0)
    chg = price_change_24h  # may be None

    prev = pts[-2] if len(pts) >= 2 else None
    prev2 = pts[-3] if len(pts) >= 3 else None
    cv_prev = float(prev["conviction"]) if prev else None
    np_prev = float(prev.get("net_pure") or 0) if prev else None
    vol_prev = float(prev.get("vol") or 0) if prev else None

    cv_rising = cv_prev is not None and cv > cv_prev
    cv_falling = cv_prev is not None and cv < cv_prev
    np_flipped_neg = np_prev is not None and np_prev >= 0 and np_now < 0
    vol_rising = vol_prev is not None and vol_prev > 0 and \
        vol_now > vol_prev * 1.15

    # confidence: need >=3 cron points to talk about "trend"
    confidence = "low" if len(pts) < 3 else "medium"
    if len(pts) >= 3 and chg is not None:
        confidence = "high"

    price_flat = chg is not None and -8 <= chg <= 8
    price_up_big = chg is not None and chg > 15
    price_up_small = chg is not None and 0 < chg <= 15
    price_down_big = chg is not None and chg < -15
    price_down = chg is not None and chg < 0

    # --- ordered rules (most specific first) --------------------------------
    # 5. Distribution-Late / Markdown
    if (price_down_big or (price_down and np_now < -10)) and \
            np_now < 0 and cv < 30:
        return {"phase": "Markdown", "confidence": confidence,
                "reason": f"price {chg:+.0f}% 24h, net pure {np_now:+.0f} "
                          f"SOL (sellers one-way), conviction {cv:.0f}% — "
                          f"distribution done, supply overhang"}
    # 4. Distribution-Early
    if (chg is None or chg > -8) and (cv_falling or np_flipped_neg) and \
            (np_now < 0 or (cv_prev is not None and cv < cv_prev - 5)):
        r_bits = []
        if chg is not None:
            r_bits.append(f"price still holding ({chg:+.0f}% 24h)")
        if cv_falling:
            r_bits.append(f"conviction dropping {cv_prev:.0f}→{cv:.0f}%")
        if np_flipped_neg:
            r_bits.append("net pure flipped negative")
        return {"phase": "Distribution-Early", "confidence": confidence,
                "reason": ", ".join(r_bits) or "early distribution signs"}
    # 3. Markup
    if price_up_big and np_now >= -5:
        return {"phase": "Markup", "confidence": confidence,
                "reason": f"price {chg:+.0f}% 24h with net pure "
                          f"{np_now:+.0f} SOL — trend leg in progress"
                          f"{', volume rising' if vol_rising else ''}"}
    # 2. Accumulation-Late
    if cv >= 50 and (cv_rising or (cv_prev is not None and
                                   abs(cv - cv_prev) <= 5)) and \
            np_now > 0 and (chg is None or price_flat or price_up_small):
        return {"phase": "Accumulation-Late", "confidence": confidence,
                "reason": f"conviction {cv:.0f}% (high & holding), net pure "
                          f"{np_now:+.0f} SOL, price quiet — mature "
                          f"accumulation"}
    # 1. Accumulation-Early
    if cv_rising and np_now > 0 and \
            (chg is None or price_flat or price_down) and cv < 50:
        return {"phase": "Accumulation-Early", "confidence": confidence,
                "reason": f"conviction climbing {cv_prev:.0f}→{cv:.0f}% "
                          f"from a low base, net pure {np_now:+.0f} SOL"
                          f"{', volume picking up' if vol_rising else ''}"}
    # 6. fallback
    bits = [f"conviction {cv:.0f}%"]
    if cv_prev is not None:
        bits.append(f"prev {cv_prev:.0f}%")
    bits.append(f"net pure {np_now:+.0f}")
    if chg is not None:
        bits.append(f"price {chg:+.0f}%/24h")
    return {"phase": "Neutral/Choppy", "confidence": confidence,
            "reason": "mixed signals: " + ", ".join(bits)}


PHASE_COLORS = {
    "Accumulation-Early": "#38bdf8",   # blue
    "Accumulation-Late": "#2563eb",    # deeper blue
    "Markup": "#22c55e",               # green
    "Distribution-Early": "#fb923c",   # orange
    "Markdown": "#ef4444",             # red
    "Neutral/Choppy": "#64748b",       # grey
}


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


# ---------------------------------------------------------------------------
# OHLC candles + flow attribution for the Breakout Guard
# ---------------------------------------------------------------------------
def fetch_candles(pool: str, *, timeframe: str = "hour", aggregate: int = 4,
                  limit: int = 100, timeout: int = 20):
    """GeckoTerminal OHLCV -> list of candle dicts, oldest -> newest.

    Each candle: ``{ts, o, h, l, c, v}`` with ``ts`` the candle's OPEN time
    (unix seconds), which is how GeckoTerminal labels them.

    ``timeframe`` is ``day`` / ``hour`` / ``minute``; ``aggregate`` multiplies
    it (``hour`` + 4 = H4). Returns [] on any failure — every caller must
    treat an empty list as "no data, do nothing".
    """
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pool}/ohlcv/{timeframe}",
            params={"aggregate": aggregate, "limit": limit},
            headers={"accept": "application/json"}, timeout=timeout)
        lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list") or []
    except Exception:
        return []
    out = []
    for x in lst:
        try:
            out.append({"ts": int(x[0]), "o": float(x[1]), "h": float(x[2]),
                        "l": float(x[3]), "c": float(x[4]),
                        "v": float(x[5] or 0)})
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda c: c["ts"])
    return out


def swaps_between(ca: str, t0: float, t1: float):
    """Raw swaps from the store with ``t0 <= ts < t1`` (oldest first)."""
    state = load_cvd()
    entry = state.get(ca)
    if not entry or not entry.get("swaps"):
        return []
    out = [tuple(s) for s in entry["swaps"]
           if t0 <= (s[2] or 0) < t1]
    out.sort(key=lambda s: s[2])
    return out


def flow_report(swaps) -> dict:
    """Who was actually behind these swaps?

    Splits the window's flow into whale (>= :data:`WHALE_SOL`) vs retail,
    counts distinct wallets on each side, folds in the pure-accumulator /
    pure-distributor profiling, and names the dominant actor. This is what
    turns "price broke the level" into "whales sold into retail buying".
    """
    empty = {"n": 0, "buy_vol": 0.0, "sell_vol": 0.0, "net": 0.0,
             "whale_buy": 0.0, "whale_sell": 0.0, "whale_net": 0.0,
             "retail_buy": 0.0, "retail_sell": 0.0, "retail_net": 0.0,
             "n_whale_buyers": 0, "n_whale_sellers": 0,
             "n_retail_buyers": 0, "n_retail_sellers": 0,
             "biggest_buy": 0.0, "biggest_sell": 0.0,
             "pure_buy": 0.0, "pure_sell": 0.0, "net_pure": 0.0,
             "actor": "no data", "actor_side": "none"}
    if not swaps:
        return empty

    r = dict(empty)
    r["n"] = len(swaps)
    wb, ws, rb, rs = set(), set(), set(), set()
    for side, sol, _ts, w in swaps:
        sol = float(sol or 0)
        whale = sol >= WHALE_SOL
        if side == "buy":
            r["buy_vol"] += sol
            r["biggest_buy"] = max(r["biggest_buy"], sol)
            if whale:
                r["whale_buy"] += sol
                wb.add(w)
            else:
                r["retail_buy"] += sol
                rb.add(w)
        else:
            r["sell_vol"] += sol
            r["biggest_sell"] = max(r["biggest_sell"], sol)
            if whale:
                r["whale_sell"] += sol
                ws.add(w)
            else:
                r["retail_sell"] += sol
                rs.add(w)

    r["net"] = r["buy_vol"] - r["sell_vol"]
    r["whale_net"] = r["whale_buy"] - r["whale_sell"]
    r["retail_net"] = r["retail_buy"] - r["retail_sell"]
    r["n_whale_buyers"] = len(wb)
    r["n_whale_sellers"] = len(ws)
    r["n_retail_buyers"] = len(rb)
    r["n_retail_sellers"] = len(rs)

    prof = wallet_profiles(swaps)
    conv = conviction_split(prof, whale_min_sol=WHALE_SOL)
    r["pure_buy"] = conv["pure_buy"]
    r["pure_sell"] = conv["pure_sell"]
    r["net_pure"] = conv["pure_buy"] - conv["pure_sell"]

    # Who dominated? Compare the four flows by absolute size.
    flows = [("whale buying", r["whale_buy"], "buy"),
             ("whale selling", r["whale_sell"], "sell"),
             ("retail buying", r["retail_buy"], "buy"),
             ("retail selling", r["retail_sell"], "sell")]
    label, size, side = max(flows, key=lambda f: f[1])
    total = r["buy_vol"] + r["sell_vol"]
    if total <= 0 or size <= 0:
        r["actor"], r["actor_side"] = "no meaningful flow", "none"
    else:
        r["actor"] = f"{label} ({size / total * 100:.0f}% of window volume)"
        r["actor_side"] = side
    return r


def describe_flow(f: dict) -> str:
    """Plain-language read of :func:`flow_report`, for the alert body."""
    if not f or not f.get("n"):
        return ("\u26a0\ufe0f no on-chain swaps stored for this candle "
                "\u2014 flow unknown (cron may have missed the window)")
    bits = [
        f"\U0001F40B whales: <b>{f['whale_net']:+.1f}</b> SOL "
        f"(+{f['whale_buy']:.1f} / -{f['whale_sell']:.1f}) \u00b7 "
        f"{f['n_whale_buyers']} buyer / {f['n_whale_sellers']} seller",
        f"\U0001F41F retail: <b>{f['retail_net']:+.1f}</b> SOL "
        f"(+{f['retail_buy']:.1f} / -{f['retail_sell']:.1f}) \u00b7 "
        f"{f['n_retail_buyers']} buyer / {f['n_retail_sellers']} seller",
        f"\U0001F48E pure: +{f['pure_buy']:.1f} / -{f['pure_sell']:.1f} "
        f"(net {f['net_pure']:+.1f}) \u00b7 {f['n']} swaps",
        f"\U0001F3AD dominant: <b>{f['actor']}</b>",
    ]
    return "\n".join(bits)


def flow_warning(f: dict, direction: str = "up") -> str:
    """The 'so what do I do' line — the whole point of the flow block.

    *direction* is the direction of the price event (``up`` for a
    breakout/reclaim, ``down`` for a breakdown), because the same flow
    means opposite things depending on which way price moved.
    """
    if not f or not f.get("n"):
        return ("\u2753 no flow data \u2014 treat this level event as "
                "unconfirmed.")
    wn, rn = f["whale_net"], f["retail_net"]
    if direction == "up":
        if wn > 0 and rn < 0:
            return ("\u2705 whales BOUGHT this move while retail sold "
                    "\u2014 strongest confirmation.")
        if wn < 0 and rn > 0:
            return ("\U0001F6A8 CAREFUL: whales SOLD into retail buying "
                    "\u2014 classic distribution into strength.")
        if wn > 0 and rn > 0:
            return ("\u26a0\ufe0f everyone bought \u2014 real demand but "
                    "crowded; watch for a fast fade.")
        return ("\u26a0\ufe0f both sides net sellers \u2014 the move is not "
                "backed by buying, likely thin-liquidity drift.")
    if wn < 0 and rn > 0:
        return ("\U0001F6A8 CAREFUL: whales DUMPED and retail absorbed it "
                "\u2014 retail is holding the bag.")
    if wn > 0 and rn < 0:
        return ("\U0001F440 whales BOUGHT the breakdown while retail "
                "panic-sold \u2014 possible shakeout, watch for a reclaim.")
    if wn < 0 and rn < 0:
        return ("\U0001F6A8 broad selling from both whales and retail "
                "\u2014 no bid underneath.")
    return ("\u26a0\ufe0f whales quiet, retail drove it \u2014 low-conviction "
            "move, needs confirmation.")


def daily_levels(pool: str, *, limit: int = 60, left: int = 2, right: int = 2,
                 merge_pct: float = 0.015, max_levels: int = 6):
    """Support/resistance from DAILY candles (pivot highs/lows).

    Daily pivots are far fewer and far more meaningful than the H1 pivots
    this used to run on: a level that held for a day is a level other
    traders can see too.

    ``right`` bars must exist AFTER a pivot for it to be confirmed, so the
    still-forming session can never invent a level. Returns
    ``{"highs": [...], "lows": [...], "price": float, "candles": n}`` with
    highs sorted ascending (nearest resistance first) and lows descending
    (nearest support first), or None when there is not enough history.
    """
    candles = fetch_candles(pool, timeframe="day", aggregate=1, limit=limit)
    if len(candles) < left + right + 3:
        return None
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    price = candles[-1]["c"]

    piv_h, piv_l = [], []
    for i in range(left, len(candles) - right):
        seg_h = highs[i - left:i + right + 1]
        seg_l = lows[i - left:i + right + 1]
        if highs[i] == max(seg_h):
            piv_h.append(highs[i])
        if lows[i] == min(seg_l):
            piv_l.append(lows[i])

    def merge(vals, prefer_recent=True):
        """Collapse levels within merge_pct of each other."""
        out = []
        for v in (reversed(vals) if prefer_recent else vals):
            if v and not any(abs(v - o) / o < merge_pct for o in out if o):
                out.append(v)
        return out

    res = sorted(v for v in merge(piv_h) if v > price)[:max_levels]
    sup = sorted((v for v in merge(piv_l) if v < price),
                 reverse=True)[:max_levels]
    return {"highs": res, "lows": sup, "price": price,
            "candles": len(candles)}
