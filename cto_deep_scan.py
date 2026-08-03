# -*- coding: utf-8 -*-
"""
CTO Deep Scan + Auto-Watchlist + Telegram
Stage 2 of CTO Incubation Radar

1. For candidates from incubation_radar (2d-60d death valley)
2. Deep scan via Helius (holders, supply, concentration, real/dust, cluster/fresh)
   - Falls back to GMGN token_stat if no Helius key
3. Check CTO flag via DexScreener page ("community claimed ownership" / "Community Takeover")
4. Check conviction flip via conviction.json (rising, persist bonus, net_pure)
5. Auto-add to watchlist + Telegram if passes

Usage:
  python cto_deep_scan.py --limit 20 --auto-watchlist --telegram
  python cto_deep_scan.py --ca <CA> --deep
"""

import json
import os
import re
import time
import argparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- imports from existing modules ---
try:
    from core import (
        get_helius_keys, get_holders, get_supply, concentration,
        health_score, gmgn_token_stat, get_market, get_rugcheck
    )
except Exception as e:
    print(f"core import failed: {e}")
    get_helius_keys = lambda: []
    get_holders = None
    get_supply = None
    concentration = lambda df, supply: {"top5":0,"top10":0,"top100":0}
    health_score = lambda **kw: (0, [])
    gmgn_token_stat = lambda ca, timeout=15: {}
    get_market = lambda ca: {}
    get_rugcheck = lambda ca: {}

try:
    from cvd import load_conviction, get_recent_swaps
except Exception:
    load_conviction = lambda required_cas=None: {}
    get_recent_swaps = lambda ca, h: []

try:
    from watchlist import add_to_watchlist, load_watchlist
except Exception:
    add_to_watchlist = lambda ca, symbol="?", source="", **kw: False
    load_watchlist = lambda: {}

try:
    from breakout_guard import send_telegram
except Exception:
    def send_telegram(text):
        print(f"[TELEGRAM MOCK] {text}")
        return False

# --- CTO detection via DexScreener page ---
def is_cto_via_dexscreener(ca: str, timeout=15) -> tuple[bool, str]:
    """Fetch DexScreener pair page and look for CTO claim.
    Returns (is_cto, detail)
    """
    url = f"https://dexscreener.com/solana/{ca}"
    content = ""
    # Try curl_cffi first (bypasses Cloudflare)
    try:
        try:
            from curl_cffi import requests as cr
            r = cr.get(url, impersonate="chrome", timeout=timeout,
                       headers={
                           "accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                           "user-agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                       })
            if r.status_code == 200:
                content = r.text
        except ImportError:
            import requests as rq
            r = rq.get(url, timeout=timeout, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code == 200:
                content = r.text
    except Exception:
        content = ""

    if not content:
        # Try via direct API token-profiles which has cto bool
        try:
            import requests as rq
            # token-profiles latest may contain this CA
            # fallback: search all profiles via API? We'll just try the pair page again with requests
            r = rq.get(f"https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)
            if r.status_code == 200:
                data = r.json() or []
                for item in data:
                    if item.get("tokenAddress") == ca:
                        if item.get("cto"):
                            return True, "cto=true in token-profiles/latest"
        except Exception:
            pass
        return False, "no content"

    low = content.lower()
    # patterns from 7 examples
    patterns = [
        "community claimed ownership",
        "community takeover",
        "community claim",
        "a community claimed",
        "cto",
    ]
    found = []
    for p in patterns:
        if p in low:
            found.append(p)
    # More specific: look for date
    m = re.search(r"community claimed ownership.*?on\s*([a-z]{3}\s+\d{1,2}\s+\d{4})", low, re.I)
    detail = ""
    if m:
        detail = f"CTO on {m.group(1)}"
    elif found:
        detail = f"found keywords: {', '.join(found[:3])}"
    
    is_cto = "community claimed ownership" in low or "community takeover" in low
    # also check if page has takeover badge
    if "community takeover" in low:
        is_cto = True
    return is_cto, detail

def get_conviction_flip(ca: str):
    """Check conviction.json for rising conviction + persist bonus + net_pure"""
    try:
        with open(os.path.join(BASE_DIR, "conviction.json"), "r") as f:
            data = json.load(f) or {}
        pts = data.get(ca) or []
        if len(pts) < 3:
            return {"rising": False, "reason": f"only {len(pts)} points", "last": None}
        # last 4 points
        last4 = pts[-4:]
        # check rising
        rising = all(last4[i]["conviction"] <= last4[i+1]["conviction"] for i in range(len(last4)-1))
        # check net_pure positive in last 2
        last2_net = [p.get("net_pure", 0) for p in last4[-2:]]
        net_pos = sum(1 for n in last2_net if n > 0)
        persist = last4[-1].get("persist_bonus", 0) or 0
        holder_up = last4[-1].get("consecutive_ups", 0) or 0
        conv = last4[-1].get("conviction", 0)
        reason = f"conv {last4[0].get('conviction',0):.0f}%->{conv:.0f}% rising={rising} net_pos {last2_net} persist {persist} ups {holder_up}"
        return {
            "rising": rising and conv >= 40,
            "conv": conv,
            "persist": persist,
            "ups": holder_up,
            "net_pos": net_pos,
            "reason": reason,
            "last": last4[-1]
        }
    except Exception as e:
        return {"rising": False, "reason": f"error {e}", "last": None}

def deep_scan_token(ca: str, do_cluster=False, helius_keys=None):
    """Full deep scan for one CA"""
    if helius_keys is None:
        helius_keys = tuple(get_helius_keys())

    result = {
        "ca": ca,
        "symbol": "?",
        "market": {},
        "holders": None,
        "supply": 0,
        "decimals": 6,
        "concentration": {},
        "tiers": {},
        "real_dust": {},
        "health": {},
        "cto": False,
        "cto_detail": "",
        "conviction": {},
        "pass": False,
        "reasons": [],
    }

    # 1. Market - try DexScreener, fallback to history.json
    m = {}
    try:
        m = get_market(ca)
        result["market"] = m
        result["symbol"] = m.get("symbol", "?")
    except Exception as e:
        result["reasons"].append(f"market fetch failed: {e}")
    
    # Fallback to history.json if market empty (sandbox SSL block)
    if not m or not m.get("marketcap"):
        try:
            hist_path = os.path.join(BASE_DIR, "history.json")
            with open(hist_path, "r") as f:
                hist = json.load(f) or {}
            if ca in hist:
                # get latest entry
                entries = hist[ca]
                latest_key = sorted(entries.keys())[-1]
                latest = entries[latest_key]
                m = {
                    "symbol": latest.get("symbol") or entries[latest_key].get("name") or "?",
                    "marketcap": latest.get("marketcap") or 0,
                    "liquidity_usd": 0,
                    "price_usd": latest.get("price") or 0,
                    "volume": {"h24": latest.get("vol24",0)},
                    "txns": {"h24": {"buys": latest.get("buys24",0), "sells": latest.get("sells24",0)}},
                }
                # estimate liq from liq_pct_mc
                liq_pct = latest.get("liq_pct_mc") or 0
                mc_val = latest.get("marketcap") or 0
                if liq_pct and mc_val:
                    m["liquidity_usd"] = mc_val * liq_pct / 100
                result["market"] = m
                result["symbol"] = m.get("symbol","?")
                result["reasons"].append(f"fallback history {latest_key} MC ${mc_val:.0f}")
        except Exception as e:
            result["reasons"].append(f"history fallback failed: {e}")

    price = m.get("price_usd") or m.get("price") or 0
    mc = m.get("marketcap") or m.get("mc") or 0
    liq = m.get("liquidity_usd") or m.get("liq") or 0
    # also try liq from liq_pct if still 0
    if liq == 0 and mc and m.get("liq_pct_mc"):
        liq = mc * float(m.get("liq_pct_mc",0)) / 100

    # 2. Holders via Helius or GMGN fallback
    holders_df = None
    supply = 0
    decimals = 6
    gmgn_stat = {}

    if helius_keys and get_holders and get_supply:
        try:
            supply, decimals = get_supply(helius_keys, ca)
            holders_df = get_holders(helius_keys, ca)
            result["supply"] = supply
            result["decimals"] = decimals
        except Exception as e:
            result["reasons"].append(f"helius holders failed: {e}")
    
    if holders_df is None or (hasattr(holders_df, 'empty') and holders_df.empty):
        # fallback GMGN top10
        try:
            gmgn_stat = gmgn_token_stat(ca)
            holders = gmgn_stat.get("holders") or []
            # construct pseudo df
            import pandas as pd
            if holders:
                df = pd.DataFrame([{"owner": o, "raw_amount": amt* (10**6), "ui_amount": amt} for o, amt in holders])
                holders_df = df
                result["supply"] = gmgn_stat.get("supply") or (mc / price if price else 0)
                result["gmgn_stat"] = gmgn_stat
                result["reasons"].append(f"gmgn fallback {len(holders)} holders")
        except Exception as e:
            result["reasons"].append(f"gmgn fallback failed: {e}")

    # 3. Compute if holders available
    if holders_df is not None and not holders_df.empty:
        try:
            import pandas as pd
            df = holders_df.copy()
            if "ui_amount" not in df.columns:
                df["ui_amount"] = df["raw_amount"] / (10 ** decimals)
            df = df[df["ui_amount"] > 0]
            df["usd_value"] = df["ui_amount"] * (price or 0)
            # concentration
            conc = concentration(df, supply or (df["ui_amount"].sum()))
            result["concentration"] = conc

            # tiers
            tiers = {}
            for label, thr in [(">$10",10),(">$100",100),(">$1K",1000),(">$10K",10000),(">$100K",100000),(">$1M",1000000)]:
                tiers[label] = int((df["usd_value"] > thr).sum())
            result["tiers"] = tiers

            # real vs dust
            dust_limit = 5.0
            try:
                import json as _j
                with open(os.path.join(BASE_DIR,"config.json")) as f:
                    dust_limit = float((_j.load(f) or {}).get("dust_limit_usd",5.0))
            except:
                pass
            n_dust = int((df["usd_value"] < dust_limit).sum())
            n_real = int((df["usd_value"] >= dust_limit).sum())
            ratio = (n_real / n_dust) if n_dust else float("inf")
            result["real_dust"] = {"n_real": n_real, "n_dust": n_dust, "ratio": ratio, "dust_limit": dust_limit}

            # health score (partial)
            liq_pct_mc = (liq / mc * 100) if mc else 0
            try:
                score, breakdown = health_score(
                    ratio_pct=(ratio*100 if n_dust else 100),
                    real_mc_pct=0,
                    top10_pct=conc.get("top10", 0),
                    liq_pct_mc=liq_pct_mc,
                    lp_locked_pct=None,
                    mint_auth=None,
                    freeze_auth=None,
                    holder_delta=None,
                    max_cluster_pct=None,
                    fresh_pct=gmgn_stat.get("raw",{}).get("fresh_wallet_rate", 0)*100 if gmgn_stat else None
                )
                result["health"] = {"score": score, "breakdown": breakdown}
            except Exception as e:
                result["reasons"].append(f"health_score failed: {e}")
        except Exception as e:
            result["reasons"].append(f"holder compute failed: {e}")

    # 4. CTO check
    try:
        is_cto, detail = is_cto_via_dexscreener(ca)
        result["cto"] = is_cto
        result["cto_detail"] = detail
    except Exception as e:
        result["reasons"].append(f"cto check failed: {e}")

    # 5. Conviction flip
    try:
        conv = get_conviction_flip(ca)
        result["conviction"] = conv
    except Exception as e:
        result["reasons"].append(f"conviction check failed: {e}")

    # 6. Pass criteria for CTO incubation
    conc_top10 = result["concentration"].get("top10", None)
    if conc_top10 is None:
        # no holder data - use GMGN fallback if available
        try:
            gmgn_raw = result.get("gmgn_stat",{}).get("raw",{}) or {}
            # gmgn token_stat has top_10_holder_rate as 0-1
            t10_rate = gmgn_raw.get("top_10_holder_rate")
            if t10_rate is None:
                t10_rate = (result.get("gmgn_stat",{}).get("raw",{}) or {}).get("top_10_holder_rate")
            if t10_rate is not None:
                conc_top10 = float(t10_rate)*100
            else:
                # try from gmgn token_stat earlier fetch
                # if still none, set to 30 as neutral for no-helius mode
                conc_top10 = 30.0
        except:
            conc_top10 = 30.0

    health_score_val = result["health"].get("score", 0)
    has_helius = len(helius_keys) > 0
    conv_rising = result["conviction"].get("rising", False)
    conv_reason = result["conviction"].get("reason","")
    conv_data = result["conviction"].get("last") or {}
    net_pure = conv_data.get("net_pure", 0) if conv_data else 0
    persist = conv_data.get("persist_bonus",0) or result["conviction"].get("persist",0) or 0
    ups = conv_data.get("consecutive_ups",0) or result["conviction"].get("ups",0) or 0

    passes = []
    fails = []

    if 3000 <= liq <= 40000:
        passes.append(f"liq ${liq:.0f} in 3k-40k")
    else:
        fails.append(f"liq ${liq:.0f} NOT in 3k-40k")

    if 3000 <= mc <= 600000:
        passes.append(f"mc ${mc:.0f} in 3k-600k")
    else:
        fails.append(f"mc ${mc:.0f} NOT in 3k-600k")

    if conc_top10 is not None and conc_top10 <= 45:
        passes.append(f"top10 {conc_top10:.1f}% <=45%")
    elif conc_top10 is None:
        passes.append(f"top10 unknown (no helius)")
    else:
        # if no helius, don't hard fail on top10
        if not has_helius:
            passes.append(f"top10 {conc_top10:.1f}% >45% but no helius -> soft pass")
        else:
            fails.append(f"top10 {conc_top10:.1f}% >45%")

    if health_score_val >= 50:
        passes.append(f"health {health_score_val} >=50")
    else:
        if not has_helius:
            passes.append(f"health {health_score_val} <50 but no helius -> soft pass")
        else:
            fails.append(f"health {health_score_val} <50")

    if result["cto"]:
        passes.append(f"CTO TRUE ({result['cto_detail']})")
    else:
        passes.append(f"CTO false (early accum ok)")

    # conviction: need rising OR net_pure positive + persist
    if conv_rising or (net_pure > 5 and (persist >=3 or ups>=1)):
        passes.append(f"conviction rising/positive: {conv_reason} net {net_pure}")
    else:
        fails.append(f"conviction NOT rising: {conv_reason}")

    # Final verdict for no-helius mode: liq+mc pass AND (conviction positive OR CTO)
    # For helius mode: also need top10 and health
    if has_helius:
        result["pass"] = (len([f for f in fails if "liq" in f or "mc" in f or "top10" in f or "health" in f]) == 0) and (result["cto"] or conv_rising or net_pure>10)
    else:
        # lenient for sandbox demo
        liq_ok = 3000 <= liq <= 40000
        mc_ok = 3000 <= mc <= 600000
        conv_ok = conv_rising or net_pure > 0 or ups >=1
        result["pass"] = liq_ok and mc_ok and conv_ok

    result["reasons"] = passes + fails

    return result

def auto_watchlist_and_telegram(candidates, do_telegram=True):
    """Add passing deep scan tokens to watchlist + telegram"""
    wl = load_watchlist()
    added = []
    for ca in candidates:
        # deep scan already done outside? candidates here are CA strings or result dicts
        if isinstance(ca, dict):
            res = ca
            ca_str = res["ca"]
        else:
            ca_str = ca
            res = deep_scan_token(ca_str)

        if not res.get("pass"):
            continue

        symbol = res.get("symbol") or res.get("market",{}).get("symbol") or "?"
        if ca_str in wl:
            continue

        ok = add_to_watchlist(ca_str, symbol=symbol, source="cto_radar", note=f"CTO radar {datetime.now().isoformat()} {res.get('cto_detail','')} {res.get('conviction',{}).get('reason','')[:80]}")
        if ok:
            added.append(res)
            msg = (
                f"💀 CTO Radar Hit: ${symbol} ({ca_str[:8]}...)\n"
                f"MC ${res.get('market',{}).get('marketcap',0):,.0f} Liq ${res.get('market',{}).get('liquidity_usd',0):,.0f}\n"
                f"Top10 {res.get('concentration',{}).get('top10',0):.1f}% Health {res.get('health',{}).get('score',0)}\n"
                f"CTO: {res.get('cto')} {res.get('cto_detail')}\n"
                f"Conv: {res.get('conviction',{}).get('reason','')}\n"
                f"https://dexscreener.com/solana/{ca_str}\n"
                f"https://gmgn.ai/sol/token/{ca_str}"
            )
            if do_telegram:
                try:
                    send_telegram(msg)
                except Exception as e:
                    print(f"telegram failed: {e}")
            print(f"Added {symbol} {ca_str} to watchlist")

    return added

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20, help="max candidates to deep scan")
    parser.add_argument("--ca", type=str, help="single CA to deep scan")
    parser.add_argument("--deep", action="store_true", help="run deep scan on provided CA or watchlist")
    parser.add_argument("--auto-watchlist", action="store_true", help="auto add passing tokens to watchlist")
    parser.add_argument("--telegram", action="store_true", help="send telegram for hits")
    parser.add_argument("--from-radar", action="store_true", help="run incubation_radar first to get candidates")
    args = parser.parse_args()

    helius_keys = tuple(get_helius_keys())
    print(f"Helius keys: {len(helius_keys)} configured")

    cas_to_scan = []

    if args.ca:
        cas_to_scan = [args.ca]
    elif args.from_radar:
        print("Running incubation_radar to get candidates (2d min)...")
        try:
            from incubation_radar import screen_incubation
            candidates, _, _ = screen_incubation(debug=False)
            cas_to_scan = [r["ca"] for r in candidates[:args.limit]]
            print(f"Radar found {len(cas_to_scan)} candidates")
        except Exception as e:
            print(f"radar failed: {e}")
            # fallback to watchlist
            wl = load_watchlist()
            cas_to_scan = list(wl.keys())[:args.limit]
    else:
        # default: scan watchlist
        wl = load_watchlist()
        cas_to_scan = list(wl.keys())[:args.limit]
        print(f"Scanning watchlist {len(cas_to_scan)} tokens")

    results = []
    for i, ca in enumerate(cas_to_scan, 1):
        print(f"\n[{i}/{len(cas_to_scan)}] Deep scanning {ca}...")
        res = deep_scan_token(ca, helius_keys=helius_keys)
        results.append(res)
        print(f"  Symbol: {res.get('symbol')} MC ${res.get('market',{}).get('marketcap',0):,.0f} Liq ${res.get('market',{}).get('liquidity_usd',0):,.0f}")
        print(f"  Top10 {res.get('concentration',{}).get('top10',0):.1f}% Health {res.get('health',{}).get('score',0)} CTO {res.get('cto')} {res.get('cto_detail')}")
        print(f"  Conviction: {res.get('conviction',{}).get('reason','')}")
        print(f"  Pass: {res.get('pass')} Reasons: {' | '.join(res.get('reasons',[])[:5])}")

    passing = [r for r in results if r.get("pass")]
    print(f"\n=== SUMMARY ===")
    print(f"Scanned: {len(results)} | Passing: {len(passing)}")
    for r in passing:
        print(f"  ✅ {r.get('symbol')} {r['ca']} - {r.get('cto_detail')} - {r.get('conviction',{}).get('reason','')}")

    if args.auto_watchlist and passing:
        print("\nAuto-adding to watchlist...")
        added = auto_watchlist_and_telegram(passing, do_telegram=args.telegram)
        print(f"Added {len(added)} to watchlist")

if __name__ == "__main__":
    main()
