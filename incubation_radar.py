# -*- coding: utf-8 -*-
"""CTO Incubation Radar — scan for dead-but-not-buried Solana memecoins
that match the 7 examples (assface, punch, testicle, grail, bountywork, ansem, chance).

Assface accumulation was day 3 => min age 2 days (2880m) is the floor.
We scan 2d - 60d incubation window, low liquidity, low volume = Death Valley.

This uses the same GMGN trending_rank unofficial API as gmgn_screener.py
but with inverted filters: instead of trending (high vol, high liq),
we look for low vol, low liq, medium holder base.
"""
import json
import time
import uuid
from typing import List, Dict

DEVICE_ID = str(uuid.uuid4())
FP_DID = uuid.uuid4().hex
GMGN_ORIGIN = "https://gmgn.ai"
TRENDING_PATH = "/trs/api/v1/trending_rank"
VERSION_URL = GMGN_ORIGIN + "/version.json"
DEFAULT_BUILD = "20260728-2617-057cd43"
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

# Incubation windows to sweep — GMGN limits result set per query,
# so we split 2d-60d into 5 buckets
WINDOWS = [
    ("2-5d", "2880m", "7200m"),
    ("5-10d", "7200m", "14400m"),
    ("10-20d", "14400m", "28800m"),
    ("20-40d", "28800m", "57600m"),
    ("40-60d", "57600m", "86400m"),
]

def _make_body(min_created, max_created):
    """Body for one window — loose filters for dead tokens"""
    return {
        "meta": {},
        "params": [{
            "chain": "sol",
            "interval": "24h",
            "filter": {
                # keep migrated + not wash trading, but DON'T require renounced/frozen
                # because dead tokens before CTO often not renounced yet
                "filters": ["migrated", "not_wash_trading"],
                "min_created": min_created,
                "max_created": max_created,
                "min_liquidity": 3000,
                "min_marketcap": 3000,
                "min_holder_count": 80,
                "min_gas_fee": 2,
                "max_insider_ratio": 0.30,
                "max_bundler_rate": 0.35,
                "min_volume_24h": 0,
            },
        }],
    }

def _make_body_strict(min_created, max_created):
    """Fallback strict body if loose returns 0 (GMGN sometimes needs renounced)"""
    return {
        "meta": {},
        "params": [{
            "chain": "sol",
            "interval": "24h",
            "filter": {
                "filters": ["migrated", "not_wash_trading", "renounced"],
                "min_created": min_created,
                "max_created": max_created,
                "min_liquidity": 5000,
                "min_marketcap": 5000,
                "min_holder_count": 100,
                "min_gas_fee": 5,
                "max_insider_ratio": 0.25,
                "max_bundler_rate": 0.30,
                "min_volume_24h": 0,
            },
        }],
    }

def fetch_window(min_c, max_c, timeout=25, debug=False):
    try:
        from curl_cffi import requests as cr
    except ImportError:
        if debug:
            print("curl_cffi missing")
        return []
    url = _trending_url()
    for body_factory in (_make_body, _make_body_strict):
        body = body_factory(min_c, max_c)
        last = ""
        for imp in ("chrome", "chrome131", "safari17_0"):
            try:
                r = cr.post(url, impersonate=imp, timeout=timeout, headers=HEADERS, data=json.dumps(body))
            except Exception as exc:
                last = f"{imp}: {exc}"
                continue
            if r.status_code != 200:
                last = f"{imp}: HTTP {r.status_code}"
                continue
            try:
                data = r.json()
            except Exception:
                last = f"{imp}: non-JSON"
                continue
            if data.get("code") not in (0, None):
                last = f"{imp}: code {data.get('code')}"
                continue
            blocks = data.get("data") or []
            if isinstance(blocks, dict):
                blocks = [blocks]
            toks = []
            for b in blocks:
                toks.extend((b or {}).get("tokens") or [])
            if toks:
                if debug:
                    print(f"window {min_c}-{max_c} got {len(toks)} tokens via {imp} body={body_factory.__name__}")
                return toks
            last = f"{imp}: 0 tokens"
        if debug:
            print(f"window {min_c}-{max_c} empty after both bodies: {last}")
    return []

def fetch_incubation(timeout=25, debug=False) -> List[Dict]:
    all_tokens = []
    seen = set()
    for label, min_c, max_c in WINDOWS:
        toks = fetch_window(min_c, max_c, timeout=timeout, debug=debug)
        for t in toks:
            ca = t.get("a") or t.get("address")
            if not ca or ca in seen:
                continue
            seen.add(ca)
            # attach window label for later analysis
            t["_window"] = label
            t["_min_c"] = min_c
            all_tokens.append(t)
        time.sleep(0.8)  # be nice
    return all_tokens

# Reuse scoring from gmgn_screener
from gmgn_screener import score_token

def is_incubation_candidate(row: Dict) -> tuple[bool, str]:
    """Apply client-side Death Valley + CTO incubation filters.
    Returns (ok, reason)
    """
    # From score_token row
    age = row.get("age_d", 0)
    liq = row.get("liq", 0)
    mc = row.get("mc", 0)
    vol = row.get("vol24", 0)
    holders = row.get("holders", 0)
    t10 = row.get("t10_pct", 100)
    liq_pct = row.get("liq_pct", 0)
    insider = row.get("insider_ratio", 0)
    bundler = row.get("bundler_rate", 0)
    vol_mc = row.get("vol_mc", 0)
    chg24 = row.get("chg24", 0)

    # Hard gates — based on 7 examples
    if age < 2.0:
        return False, f"age {age}d <2d"
    if age > 70:
        return False, f"age {age}d >70d"
    if not (3000 <= liq <= 40000):
        return False, f"liq ${liq:.0f} not in 3k-40k"
    if not (3000 <= mc <= 600000):
        return False, f"mc ${mc:.0f} not in 3k-600k"
    if holders < 80 or holders > 6000:
        return False, f"holders {holders} not 80-6000"
    if t10 > 45:
        return False, f"t10 {t10}% >45%"
    if insider > 0.30 or bundler > 0.40:
        return False, f"insider {insider*100:.0f}% bundler {bundler*100:.0f}% too high"
    # Death valley: vol low
    if vol > 15000:
        return False, f"vol24 ${vol:.0f} >15k too active"
    if vol_mc > 0.30:
        return False, f"vol/mc {vol_mc} >0.3 too active"
    # But not completely dead 0 vol (still need some tx history)
    # Allow 0-15k

    # Extra signal: deep retrace or flat is good for bottom
    # We don't gate on chg, just note
    reason = f"age {age:.1f}d liq ${liq:.0f} mc ${mc:.0f} vol ${vol:.0f} ({vol_mc:.2f}x) t10 {t10}% holders {holders} chg24 {chg24}%"
    return True, reason

def screen_incubation(debug=False):
    raw = fetch_incubation(debug=debug)
    print(f"Raw GMGN tokens from all windows: {len(raw)}") if debug else None
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
        ok, reason = is_incubation_candidate(row)
        row["_incubation_ok"] = ok
        row["_incubation_reason"] = reason
        rows.append(row)
    # Split
    candidates = [r for r in rows if r["_incubation_ok"]]
    rejects = [r for r in rows if not r["_incubation_ok"]]

    # Sort candidates by fit desc, then by low vol, then by holders
    candidates.sort(key=lambda r: (-r.get("fit_exact", r["fit"]), r["vol24"], -r["holders"]))
    rejects.sort(key=lambda r: (-r.get("fit_exact", r["fit"])))

    return candidates, rejects, rows

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    candidates, rejects, all_rows = screen_incubation(debug=args.debug)
    print(f"\n=== CTO INCUBATION RADAR ===")
    print(f"Total scanned: {len(all_rows)} | Candidates: {len(candidates)} | Rejected: {len(rejects)}\n")

    if not candidates:
        print("No candidates matching death valley. Showing top 20 closest rejects for tuning:")
        for r in rejects[:20]:
            print(f"{r['fit']:3d} {r['grade']:5s} {r['symbol'] or '?':10s} age {r['age_d']}d liq ${r['liq']:.0f} mc ${r['mc']:.0f} vol ${r['vol24']:.0f} t10 {r['t10_pct']}% chg {r['chg24']}% -> {r['_incubation_reason']} | https://gmgn.ai/sol/token/{r['ca']}")
    else:
        for r in candidates[:args.limit]:
            print(f"{r['fit']:3d} {r['grade']:5s} {r['symbol'] or '?':10s} MC ${r['mc']:,.0f} Liq ${r['liq']:,.0f} ({r['liq_pct']}%) Vol ${r['vol24']:,.0f} ({r['vol_mc']}x) T10 {r['t10_pct']}% Holders {r['holders']} Age {r['age_d']}d Chg24 {r['chg24']}% FitExact {r['fit_exact']} | {r['_incubation_reason']}")
            print(f"  -> https://gmgn.ai/sol/token/{r['ca']} | https://dexscreener.com/solana/{r['ca']}")
            if r.get("risk_reasons"):
                print(f"     Risk: {'; '.join(r['risk_reasons'])}")
            if r.get("notes"):
                print(f"     Notes: {r['notes']}")
            print()
