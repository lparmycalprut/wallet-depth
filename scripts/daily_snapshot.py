# -*- coding: utf-8 -*-
"""Daily snapshot cron job (GitHub Actions).

Scans every CA in watchlist.json, computes the same snapshot the dashboard
saves, and appends it to history.json. The workflow then commits both files
back to the repo, so day-by-day history keeps building even when nobody
opens the dashboard.

Usage:  HELIUS_API_KEY=xxx python scripts/daily_snapshot.py
"""
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import concentration, get_helius_keys, get_holders, get_market, \
    get_rugcheck, get_supply, health_score  # noqa: E402
from watchlist import load_watchlist, save_watchlist  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")

TIERS = [(">$10", 10.0), (">$100", 100.0), (">$1K", 1e3),
         (">$10K", 1e4), (">$100K", 1e5), (">$1M", 1e6)]
DUST_LIMIT = 10.0


def load_history():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def snapshot_one(helius_keys, ca: str) -> dict:
    m = get_market(ca)
    if not m:
        raise RuntimeError("not found on DexScreener")
    supply, dec = get_supply(helius_keys, ca)
    hd = get_holders(helius_keys, ca)
    hd["ui_amount"] = hd["raw_amount"] / (10 ** dec)
    hd = hd[hd["ui_amount"] > 0]
    lp = set(m.get("pair_addresses") or [])
    hd = hd[~hd["owner"].isin(lp)]
    price, mc = m["price_usd"], m["marketcap"]
    hd["usd_value"] = hd["ui_amount"] * price

    dust = hd[hd["usd_value"] < DUST_LIMIT]
    real = hd[hd["usd_value"] >= DUST_LIMIT]
    conc = concentration(hd, supply)
    rug = get_rugcheck(ca)
    liq_pct = m["liquidity_usd"] / mc * 100 if mc else 0
    tx = (m.get("txns") or {}).get("h24") or {}
    buys, sells = int(tx.get("buys") or 0), int(tx.get("sells") or 0)
    vol24 = float((m.get("volume") or {}).get("h24") or 0)
    ratio_pct = (len(real) / len(dust) * 100) if len(dust) else 100.0
    real_mc = float(real["usd_value"].sum()) / mc * 100 if mc else 0
    dust_mc = float(dust["usd_value"].sum()) / mc * 100 if mc else 0
    score, _ = health_score(
        ratio_pct=ratio_pct, real_mc_pct=real_mc, top10_pct=conc["top10"],
        liq_pct_mc=liq_pct, lp_locked_pct=rug.get("lp_locked_pct"),
        mint_auth=rug.get("mint_authority"),
        freeze_auth=rug.get("freeze_authority"),
        holder_delta=None, max_cluster_pct=None, fresh_pct=None)

    return {
        "total_holders": int(len(hd)), "dust": int(len(dust)),
        "real": int(len(real)), "real_mc_pct": float(real_mc),
        "dust_mc_pct": float(dust_mc), "marketcap": float(mc),
        "price": float(price),
        "tiers": {lab: int((hd["usd_value"] > thr).sum())
                  for lab, thr in TIERS},
        "ts": datetime.now().isoformat(timespec="seconds"),
        "score": score, "top10_pct": round(conc["top10"], 2),
        "top5_pct": round(conc["top5"], 2),
        "top100_pct": round(conc["top100"], 2),
        "liq_pct_mc": round(liq_pct, 2), "symbol": m.get("symbol", "?"),
        "buys24": buys, "sells24": sells, "vol24": vol24,
        "source": "cron",
    }


def main():
    helius_keys = tuple(get_helius_keys())
    if not helius_keys:
        sys.exit("HELIUS_API_KEY(S) missing (env, config.json, or secrets)")

    wl = load_watchlist()
    if not wl:
        print("Watchlist empty — nothing to snapshot.")
        return

    hist = load_history()
    today = date.today().isoformat()
    ok, failed = 0, 0
    for ca, meta in wl.items():
        try:
            snap = snapshot_one(helius_keys, ca)
            hist.setdefault(ca, {})[today] = snap
            if snap.get("symbol") and snap["symbol"] != "?":
                meta["symbol"] = snap["symbol"]
            ok += 1
            print(f"✅ {snap['symbol']:>10} {ca[:8]}… holders="
                  f"{snap['total_holders']:,} score={snap['score']}")
        except Exception as e:
            failed += 1
            print(f"❌ {ca[:8]}… failed: {str(e)[:100]}")

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=1)
    save_watchlist(wl)
    print(f"\nDone: {ok} ok, {failed} failed, {len(wl)} watched.")


if __name__ == "__main__":
    main()
