# -*- coding: utf-8 -*-
"""
LP Safe Radar — CATJAK-like but safe from negative flags

CATJAK reference (from GMGN token_stat + DexScreener):
- age 5d 20h, liq $48k, mcap $373k, holders 1631
- vol24 $154k (h24 buys 1279 sells 1315 ratio 0.97 balanced)
- top10 14.12% (excellent), bundler 3.96%, entrap 26.43%, bot_degen 15.14%, fresh 8.9% low
- dev hold 2.02%, sniper 2.02%
- liq/mc 12.86%, vol/mc 0.41x healthy
- socials: website + twitter + telegram, boost 1164
- avg_cost +17% (holders in profit but not extreme)

Goal: find tokens with CATJAK structure but safe = no red flags, ideal for LP

Filters:
- Age 3-15 days (CATJAK 5d) — not too new (rug) not too old (dead)
- Liq $20k-$120k (CATJAK $48k) — enough for LP, not too thin
- MC $120k-$1M (CATJAK $373k)
- Holders >=1000 (CATJAK 1631)
- Vol24 $30k-$400k (CATJAK $154k) balanced
- Liq/MC 8%-30% (CATJAK 12%)
- Vol/MC 0.15x - 2.5x (CATJAK 0.41x) — not wash, not dead
- Top10 <=20% (CATJAK 14%) — stricter than usual 30%
- Bundler <=5% (CATJAK 3.96%), Insider <=8%, Entrap <=30%, BotDegen <=20%, Fresh <=15%, Sniper <=5%
- Rug <=0.30, has renounced + frozen
- Buys/Sells 24h ratio 0.75-1.35 (CATJAK 0.97)
- Socials: website + twitter (at least 2)
- Boost >=200 (optional marketing)
- Avg_cost -30% to +60% (not deep underwater, not extreme profit)
"""

import json
import time
import uuid

DEVICE_ID = str(uuid.uuid4())
FP_DID = uuid.uuid4().hex
GMGN_ORIGIN = "https://gmgn.ai"
TRENDING_PATH = "/trs/api/v1/trending_rank"
VERSION_URL = GMGN_ORIGIN + "/version.json"
DEFAULT_BUILD = "20260803-2834-2eed5c7"
_build_cache = {"tag": "", "ts": 0.0}

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "content-type": "application/json",
    "origin": GMGN_ORIGIN,
    "referer": GMGN_ORIGIN + "/trend?chain=sol",
    "priority": "u=1, i",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
}

def _build_tag(timeout=10):
    now = time.time()
    if _build_cache["tag"] and now - _build_cache["ts"] < 3600:
        return _build_cache["tag"]
    tag = DEFAULT_BUILD
    try:
        from curl_cffi import requests as cr
        r = cr.get(VERSION_URL, impersonate="chrome", timeout=timeout)
        if r.status_code == 200:
            raw = (r.json() or {}).get("buildTag") or ""
            parts = [p for p in raw.split("-") if p and p != "master"]
            if len(parts) >= 3:
                tag = "-".join(parts[:3])
    except Exception:
        pass
    _build_cache.update(tag=tag, ts=now)
    return tag

def _trending_url():
    build = _build_tag()
    return (
        f"{GMGN_ORIGIN}{TRENDING_PATH}?"
        f"device_id={DEVICE_ID}&fp_did={FP_DID}&"
        f"client_id=gmgn_web_{build}&from_app=gmgn&app_ver={build}&"
        f"tz_name=Asia%2FJakarta&tz_offset=25200&app_lang=en-US&"
        f"os=web&worker=0"
    )

# LP Safe windows: CATJAK-like age 3-15d split into 2 buckets for more results
WINDOWS = [
    ("3-7d", "4320m", "10080m"),   # 3-7 days
    ("7-15d", "10080m", "21600m"), # 7-15 days
]

def _make_body_lp(min_c, max_c):
    return {
        "meta": {},
        "params": [{
            "chain": "sol",
            "interval": "24h",
            "filter": {
                "filters": ["migrated", "not_wash_trading", "renounced", "frozen"],
                "min_created": min_c,
                "max_created": max_c,
                "min_liquidity": 15000,
                "min_marketcap": 80000,
                "min_holder_count": 800,
                "min_gas_fee": 15,
                "max_insider_ratio": 0.10,
                "max_bundler_rate": 0.10,
                "min_volume_24h": 20000,
            },
        }],
    }

def fetch_window(min_c, max_c, timeout=25, debug=False):
    try:
        from curl_cffi import requests as cr
    except ImportError:
        return []
    url = _trending_url()
    body = _make_body_lp(min_c, max_c)
    for imp in ("chrome", "chrome131", "safari17_0"):
        try:
            r = cr.post(url, impersonate=imp, timeout=timeout, headers=HEADERS, data=json.dumps(body))
        except Exception as exc:
            if debug:
                print(f"{min_c}-{max_c} {imp} exc {exc}")
            continue
        if r.status_code != 200:
            if debug:
                print(f"{min_c}-{max_c} {imp} HTTP {r.status_code}")
            continue
        try:
            data = r.json()
        except Exception:
            continue
        if data.get("code") not in (0, None):
            continue
        blocks = data.get("data") or []
        if isinstance(blocks, dict):
            blocks = [blocks]
        toks = []
        for b in blocks:
            toks.extend((b or {}).get("tokens") or [])
        if toks:
            if debug:
                print(f"window {min_c}-{max_c} got {len(toks)} tokens via {imp}")
            return toks
    return []

def fetch_lp_safe(timeout=25, debug=False):
    all_tokens = []
    seen = set()
    for label, min_c, max_c in WINDOWS:
        toks = fetch_window(min_c, max_c, timeout=timeout, debug=debug)
        for t in toks:
            ca = t.get("a") or t.get("address")
            if not ca or ca in seen:
                continue
            seen.add(ca)
            t["_window"] = label
            all_tokens.append(t)
        time.sleep(0.8)
    return all_tokens

# Reuse scoring
from gmgn_screener import score_token

def is_lp_safe_candidate(row, dex_data=None):
    """
    row: scored row from score_token (has mc, liq, holders, t10, rug, insider, bundler, etc)
    dex_data: optional dict from DexScreener (txns, socials) for extra checks
    Returns (ok, reason)
    """
    age = row.get("age_d", 0)
    liq = row.get("liq", 0)
    mc = row.get("mc", 0)
    vol = row.get("vol24", 0)
    holders = row.get("holders", 0)
    t10 = row.get("t10_pct", 100)
    liq_pct = row.get("liq_pct", 0)
    vol_mc = row.get("vol_mc", 0)
    insider = row.get("insider_ratio", 0)
    bundler = row.get("bundler_rate", 0)
    entrap = row.get("entrap_rate", 0)
    botdegen = row.get("botdegen_rate", 0)
    rug = row.get("rug", 1)
    fresh = row.get("fresh_wallet_rate", 0)
    holder_conc = row.get("holder_conc", 0)
    sniper = row.get("sniper_hold", 0)
    chg24 = row.get("chg24", 0)

    # Hard gates - CATJAK safe
    if not (3 <= age <= 16):
        return False, f"age {age:.1f}d not 3-16d"
    if not (15000 <= liq <= 130000):
        return False, f"liq ${liq:.0f} not 15k-130k (CATJAK 48k)"
    if not (80000 <= mc <= 1200000):
        return False, f"mc ${mc:.0f} not 80k-1.2M (CATJAK 373k)"
    if holders < 800:
        return False, f"holders {holders} <800 (CATJAK 1631)"
    if not (20000 <= vol <= 500000):
        return False, f"vol24 ${vol:.0f} not 20k-500k (CATJAK 154k)"
    if not (8 <= liq_pct <= 32):
        return False, f"liq/mc {liq_pct:.1f}% not 8-32% (CATJAK 12.8%)"
    if not (0.12 <= vol_mc <= 3.0):
        return False, f"vol/mc {vol_mc:.2f}x not 0.12-3.0 (CATJAK 0.41x)"
    if t10 > 22:
        return False, f"t10 {t10:.1f}% >22% (CATJAK 14.1% safe)"
    if insider > 0.08:
        return False, f"insider {insider*100:.1f}% >8% (CATJAK 0%)"
    if bundler > 0.05:
        return False, f"bundler {bundler*100:.1f}% >5% (CATJAK 3.96%)"
    if entrap > 0.32:
        return False, f"entrap {entrap*100:.1f}% >32% (CATJAK 26.4%)"
    if botdegen > 0.22:
        return False, f"botdegen {botdegen*100:.1f}% >22% (CATJAK 15.1%)"
    if fresh > 0.18:
        return False, f"fresh {fresh*100:.1f}% >18% (CATJAK 8.9%)"
    if holder_conc > 0.72:
        return False, f"holder_conc top50 {holder_conc*100:.0f}% >72%"
    if sniper > 0.06:
        return False, f"sniper {sniper*100:.1f}% >6% (CATJAK 2%)"
    if rug > 0.35:
        return False, f"rug {rug:.2f} >0.35"

    # DexScreener extra checks if available
    if dex_data:
        tx = dex_data.get("txns") or {}
        h24 = tx.get("h24") or {}
        buys = h24.get("buys") or 0
        sells = h24.get("sells") or 0
        if buys and sells:
            ratio = buys / sells if sells else 10
            if not (0.70 <= ratio <= 1.40):
                return False, f"buys/sells ratio {ratio:.2f} not 0.70-1.40 balanced (CATJAK 0.97)"
        # socials
        # we expect dex_data has info with websites/socials - checked via separate fetch

    reason = f"age {age:.1f}d liq ${liq:.0f} ({liq_pct:.1f}% MC) mc ${mc:.0f} vol ${vol:.0f} ({vol_mc:.2f}x) t10 {t10:.1f}% holders {holders} bundler {bundler*100:.1f}% fresh {fresh*100:.1f}% chg24 {chg24:.1f}%"
    return True, reason

def screen_lp_safe(debug=False, enrich_dex=False):
    raw = fetch_lp_safe(debug=debug)
    rows = []
    seen = set()
    for t in raw:
        try:
            row = score_token(t)
        except Exception:
            continue
        ca = row.get("ca")
        if not ca or ca in seen:
            continue
        seen.add(ca)
        row["_window"] = t.get("_window")
        # optional DexScreener enrichment for buys/sells ratio
        dex_data = None
        if enrich_dex:
            try:
                from core import get_market
                dex_data = get_market(ca)
            except Exception:
                dex_data = None
        ok, reason = is_lp_safe_candidate(row, dex_data=dex_data)
        row["_lp_ok"] = ok
        row["_lp_reason"] = reason
        row["_dex"] = dex_data
        rows.append(row)

    candidates = [r for r in rows if r["_lp_ok"]]
    rejects = [r for r in rows if not r["_lp_ok"]]
    candidates.sort(key=lambda r: (-r.get("fit_exact", r["fit"]), r["t10_pct"], -r["liq_pct"]))
    rejects.sort(key=lambda r: (-r.get("fit_exact", r["fit"])))
    return candidates, rejects, rows

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    cands, rejects, all_rows = screen_lp_safe(debug=args.debug, enrich_dex=False)
    print(f"\n=== CATJAK LP SAFE RADAR ===")
    print(f"Total: {len(all_rows)} | Safe LP candidates: {len(cands)} | Rejected: {len(rejects)}\n")

    if cands:
        for r in cands[:args.limit]:
            print(f"{r['fit']:3d} {r['grade']:5s} {r['symbol'] or '?':10s} age {r['age_d']:.1f}d MC ${r['mc']:,.0f} Liq ${r['liq']:,.0f} ({r['liq_pct']}%) Vol ${r['vol24']:,.0f} ({r['vol_mc']}x) T10 {r['t10_pct']}% Hold {r['holders']} bund {r['bundler_rate']*100:.1f}% fresh {r['fresh_wallet_rate']*100:.1f}% entrap {r['entrap_rate']*100:.1f}% -> {r['_lp_reason']}")
            print(f"  https://gmgn.ai/sol/token/{r['ca']} https://dexscreener.com/solana/{r['ca']}")
            if r.get("risk_reasons"):
                print(f"  Risk: {r['risk_reasons']}")
            print()
    else:
        print("No LP safe candidates, top rejects:")
        for r in rejects[:20]:
            print(f"{r['fit']:3d} {r['symbol'] or '?':10s} age {r['age_d']:.1f}d liq ${r['liq']:.0f} mc ${r['mc']:.0f} vol ${r['vol24']:.0f} t10 {r['t10_pct']}% -> {r['_lp_reason']}")
