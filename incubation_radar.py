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
    """Body for one window — deliberately broad; client gates decide the mode.

    GMGN's server-side filter is only a pre-filter.  Keep it no stricter than
    the radar's local gates so a token with 50-79 holders, for example, is not
    silently lost before :func:`is_incubation_candidate` can classify it.
    """
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
                "min_holder_count": 50,
                "min_gas_fee": 2,
                "max_insider_ratio": 0.35,
                "max_bundler_rate": 0.45,
                "min_volume_24h": 0,
            },
        }],
    }

def _make_body_strict(min_created, max_created):
    """Fallback body if the loose request returns 0.

    This fallback is still only a server-side pre-filter.  The exact strict or
    relaxed thresholds are applied locally below, rather than accidentally
    using the old 5k/100-holder/15k-volume tuning here.
    """
    return {
        "meta": {},
        "params": [{
            "chain": "sol",
            "interval": "24h",
            "filter": {
                "filters": ["migrated", "not_wash_trading", "renounced"],
                "min_created": min_created,
                "max_created": max_created,
                "min_liquidity": 3000,
                "min_marketcap": 3000,
                "min_holder_count": 50,
                "min_gas_fee": 2,
                "max_insider_ratio": 0.35,
                "max_bundler_rate": 0.45,
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

def _number(row: Dict, *keys, default=0.0) -> float:
    """Read a numeric radar field without letting a bad API value crash scan."""
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value == value and value not in (float("inf"), float("-inf")):
            return value
    return float(default)


def is_incubation_candidate(row: Dict, relaxed: bool = False) -> tuple[bool, str]:
    """Apply the CTO Death Valley gates to one scored row.

    ``relaxed`` is the pre-CTO accumulation mode.  It widens the low-liq
    boundary and Top-10 band, while keeping an absolute-volume ceiling.  The
    strict 0.8x volume/MC gate gets a small 1.2x pre-CTO tolerance because the
    two intended death-valley examples (RYDER and looong) currently read about
    0.90x and 1.17x; the $45k liquidity cap still keeps RAKO/CATJAK out.  It
    does *not* bring the old $80k-liquidity trending tokens back into the
    accumulation radar.  All values below use the same units as
    :func:`gmgn_screener.score_token`: dollars, percent for ``t10_pct``, and
    fractions for wallet rates.

    Returns ``(ok, reason)`` so the UI can show the first failed gate.
    """
    age = _number(row, "age_d", "age", default=0)
    liq = _number(row, "liq", "liquidity", default=0)
    mc = _number(row, "mc", "marketcap", "market_cap", default=0)
    vol = _number(row, "vol24", "volume", "volume_24h", default=0)
    holders = _number(row, "holders", "holder_count", default=0)
    t10 = _number(row, "t10_pct", "t10", "top10_pct", default=100)
    insider = _number(row, "insider_ratio", "insider", default=0)
    bundler = _number(row, "bundler_rate", "bundler", default=0)
    fresh = _number(row, "fresh_wallet_rate", "fresh", "fresh_pct", default=0)
    vol_mc = _number(row, "vol_mc", "volume_mc", default=0)
    chg24 = _number(row, "chg24", default=0)

    liq_max = 45000 if relaxed else 40000
    vol_mc_max = 1.20 if relaxed else 0.80
    t10_max = 55 if relaxed else 50
    mode = "relaxed" if relaxed else "strict"

    # Exact requested incubation window: 2-60 days.
    if not (2.0 <= age <= 60.0):
        return False, f"{mode}: age {age:g}d not in 2-60d"
    if not (3000 <= liq <= liq_max):
        return False, f"{mode}: liq ${liq:.0f} not in 3k-{liq_max // 1000}k"
    if not (3000 <= mc <= 600000):
        return False, f"{mode}: mc ${mc:.0f} not in 3k-600k"
    if vol > 90000:
        return False, f"{mode}: vol24 ${vol:.0f} >90k too active"
    if vol_mc > vol_mc_max:
        return False, f"{mode}: vol/mc {vol_mc:.2f}x >{vol_mc_max:.2f} too active"
    if not (50 <= holders <= 6000):
        return False, f"{mode}: holders {holders:g} not 50-6000"
    if t10 > t10_max:
        return False, f"{mode}: t10 {t10:.1f}% >{t10_max}%"
    if insider > 0.35:
        return False, f"{mode}: insider {insider * 100:.1f}% >35%"
    if bundler > 0.45:
        return False, f"{mode}: bundler {bundler * 100:.1f}% >45%"
    if fresh > 0.50:
        return False, f"{mode}: fresh {fresh * 100:.1f}% >50%"

    reason = (
        f"{mode}: age {age:.1f}d liq ${liq:.0f} mc ${mc:.0f} "
        f"vol ${vol:.0f} ({vol_mc:.2f}x) t10 {t10:.1f}% "
        f"holders {holders:.0f} insider {insider * 100:.1f}% "
        f"bundler {bundler * 100:.1f}% fresh {fresh * 100:.1f}% chg24 {chg24:.1f}%"
    )
    return True, reason


def screen_incubation(relaxed: bool = False, debug: bool = False):
    """Fetch and classify incubation rows in strict or pre-CTO mode."""
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
        ok, reason = is_incubation_candidate(row, relaxed=relaxed)
        row["_incubation_ok"] = ok
        row["_incubation_reason"] = reason
        rows.append(row)
    candidates = [r for r in rows if r["_incubation_ok"]]
    rejects = [r for r in rows if not r["_incubation_ok"]]

    # Sort candidates by fit desc, then by low volume, then by holders.
    candidates.sort(key=lambda r: (-r.get("fit_exact", r["fit"]), r["vol24"], -r["holders"]))
    rejects.sort(key=lambda r: (-r.get("fit_exact", r["fit"])))
    return candidates, rejects, rows

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--relaxed", action="store_true",
                        help="pre-CTO mode: liq up to $45k and Top10 up to 55%")
    args = parser.parse_args()

    candidates, rejects, all_rows = screen_incubation(relaxed=args.relaxed, debug=args.debug)
    mode = "RELAXED / PRE-CTO" if args.relaxed else "STRICT / DEATH VALLEY"
    print(f"\n=== CTO INCUBATION RADAR ({mode}) ===")
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
