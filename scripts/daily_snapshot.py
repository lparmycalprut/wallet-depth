# -*- coding: utf-8 -*-
"""Daily snapshot cron job (GitHub Actions).

Scans every CA in watchlist.json, saves a lightweight daily snapshot to
history.json. NO Helius dependency — uses DexScreener (primary) + GMGN
token_stat (fallback for holder_count/top10).

The CVD cron (hourly) already handles deep on-chain flow; this cron
just needs the daily "point-in-time" numbers so the dashboard can show
day-over-day deltas and the History page has long-term data.

Usage:  python scripts/daily_snapshot.py
"""

import json
import os
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from watchlist import load_watchlist, save_watchlist  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")

TIERS = [(">$10", 10.0), (">$100", 100.0), (">$1K", 1e3),
         (">$10K", 1e4), (">$100K", 1e5), (">$1M", 1e6)]
DUST_LIMIT = 10.0

# ---------------------------------------------------------------------------
# GMGN token_stat — alternative to Helius for holder count + top10
# ---------------------------------------------------------------------------
GMGN_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://gmgn.ai",
    "referer": "https://gmgn.ai/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/150.0.0.0 Safari/537.36"),
}


def _gmgn_token_stat(ca: str, timeout: int = 15) -> dict:
    """Fetch GMGN /api/v1/token_stat/sol/<CA> — holder_count, top10, etc."""
    try:
        from curl_cffi import requests as cr
        r = cr.get(
            f"https://gmgn.ai/api/v1/token_stat/sol/{ca}",
            headers=GMGN_HEADERS, impersonate="chrome", timeout=timeout)
    except ImportError:
        r = requests.get(
            f"https://gmgn.ai/api/v1/token_stat/sol/{ca}",
            headers=GMGN_HEADERS, timeout=timeout)
    if r.status_code != 200:
        return {}
    try:
        return r.json() or {}
    except Exception:
        return {}


def _dex_market(ca: str, timeout: int = 20) -> dict | None:
    """DexScreener pair info for a single CA."""
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
            timeout=timeout)
        pairs = (r.json() or {}).get("pairs") or []
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                   reverse=True)
        if not pairs:
            return None
        return pairs[0]
    except Exception:
        return None


def _as_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def snapshot_one(ca: str) -> dict:
    """Lightweight daily snapshot — DexScreener + GMGN fallback. No Helius."""
    pair = _dex_market(ca)
    if not pair:
        raise RuntimeError("not found on DexScreener")

    price = _as_float(pair.get("priceUsd"))
    mc = _as_float(pair.get("marketCap") or pair.get("fdv"))
    liq = _as_float((pair.get("liquidity") or {}).get("usd"))
    liq_pct = (liq / mc * 100) if mc else 0
    tx = (pair.get("txns") or {}).get("h24") or {}
    buys = int(tx.get("buys") or 0)
    sells = int(tx.get("sells") or 0)
    vol24 = _as_float((pair.get("volume") or {}).get("h24"))
    symbol = (pair.get("baseToken") or {}).get("symbol") or "?"
    name = (pair.get("baseToken") or {}).get("name") or "?"

    # ── GMGN fallback for holder count + top10 ──────────────────────────
    gmgn = _gmgn_token_stat(ca)
    holders = int(_as_float(gmgn.get("holder_count", 0)))
    t10_raw = _as_float(gmgn.get("top_10_holder_rate", 0))
    # top_10_holder_rate is 0-1 in GMGN response
    top10_pct = t10_raw * 100 if t10_raw < 1 else t10_raw
    if top10_pct > 100:
        top10_pct = 0  # bad parse

    # DexScreener fallback for holders (some pairs have it)
    if not holders:
        hd = pair.get("holders")
        if hd:
            holders = int(_as_float(hd))

    # ── Score estimate (lightweight, without full holder list) ──────────
    # Can't compute real/dust ratio or concentration without Helius.
    # Use conservative defaults: real_mc_pct=80 (assume healthy-ish),
    # ratio_pct=50 (borderline), top10=top10_pct from GMGN.
    real_est = max(0, holders - max(1, int(holders * 0.4)))  # guess: 60% real
    dust_est = holders - real_est
    ratio_pct = (real_est / dust_est * 100) if dust_est else 100.0
    real_mc_pct = 80.0  # conservative default

    # ── Score calculation ───────────────────────────────────────────────
    from core import health_score
    score, _ = health_score(
        ratio_pct=ratio_pct, real_mc_pct=real_mc_pct,
        top10_pct=top10_pct, liq_pct_mc=liq_pct,
        lp_locked_pct=None, mint_auth=None, freeze_auth=None,
        holder_delta=None, max_cluster_pct=None, fresh_pct=None)

    tiers = {}
    if holders:
        # Rough tier distribution (no per-wallet data, use power-law estimate)
        tiers = {
            ">$10":   max(1, int(holders * 0.70)),
            ">$100":  max(1, int(holders * 0.30)),
            ">$1K":   max(1, int(holders * 0.12)),
            ">$10K":  max(1, int(holders * 0.04)),
            ">$100K": max(1, int(holders * 0.008)),
            ">$1M":   max(0, int(holders * 0.001)),
        }

    return {
        "total_holders": holders,
        "dust": dust_est,
        "real": real_est,
        "real_mc_pct": round(real_mc_pct, 2),
        "dust_mc_pct": round(100 - real_mc_pct, 2),
        "marketcap": float(mc),
        "price": float(price),
        "tiers": tiers,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "score": score,
        "top10_pct": round(top10_pct, 2),
        "top5_pct": round(top10_pct * 0.55, 2),   # estimate
        "top100_pct": round(min(100, top10_pct * 3), 2),  # estimate
        "liq_pct_mc": round(liq_pct, 2),
        "symbol": symbol,
        "buys24": buys, "sells24": sells, "vol24": vol24,
        "source": "cron-daily (DexScreener+GMGN)",
    }


def load_history():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def main():
    wl = load_watchlist()
    if not wl:
        print("Watchlist empty — nothing to snapshot.")
        return

    hist = load_history()
    today = date.today().isoformat()
    ok, failed, skipped = 0, 0, 0

    for ca, meta in wl.items():
        # Skip if already snapshotted today (idempotent — safe against retry)
        existing = hist.get(ca, {})
        if today in existing:
            sym = existing[today].get("symbol", meta.get("symbol", "?"))
            print(f"⏭️  {sym:>10} {ca[:8]}… already snapshotted today, skip")
            skipped += 1
            continue

        try:
            snap = snapshot_one(ca)
            hist.setdefault(ca, {})[today] = snap
            if snap.get("symbol") and snap["symbol"] != "?":
                meta["symbol"] = snap["symbol"]
            ok += 1
            print(f"✅ {snap['symbol']:>10} {ca[:8]}… "
                  f"holders={snap['total_holders']:,} "
                  f"score={snap['score']} mc=${snap['marketcap']:,.0f}")
        except Exception as e:
            failed += 1
            print(f"❌ {ca[:8]}… failed: {str(e)[:100]}")
        time.sleep(0.3)  # gentle rate limit

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=1)
    save_watchlist(wl)
    print(f"\nDone: {ok} ok, {failed} failed, {skipped} skipped, "
          f"{len(wl)} watched.")


if __name__ == "__main__":
    main()
