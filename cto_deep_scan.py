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

MARKET DATA AUTHORITY
---------------------
GMGN is the ONLY authoritative market source for the CTO Incubation Radar.
GMGN counts transactions across ALL pools of a token, while DexScreener
reads a single pair (e.g. MEMIPEDE vol24: GMGN ~$70k vs Dex ~$45k on the
deepest pair only) — mixing them makes Stage 1 and Stage 2 disagree.

- Stage 1 passes its scored GMGN row into ``deep_scan_token(..., gmgn_row=row)``
  so Stage 2 gates (MC / liquidity / volume / vol-MC / holders / T10) run on
  the exact numbers the radar admitted.
- ``--ca`` / watchlist scans fetch a live per-CA GMGN snapshot
  (:func:`fetch_gmgn_market_row`) instead of calling DexScreener.
- If no GMGN snapshot is available the scan FAILS CLOSED with the reason
  "GMGN market snapshot unavailable"; history.json is no longer a market
  fallback.  DexScreener is still used for metadata only: CTO claim
  detection, pair links, and GMGN-vs-Dex divergence logging.

Usage:
  python cto_deep_scan.py --limit 20 --auto-watchlist --telegram
  python cto_deep_scan.py --limit 4 --deep --relaxed
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

def _load_local_watchlist():
    """Small dependency-free fallback for cron/CLI environments.

    The normal path uses ``watchlist.py`` (and GitHub persistence), but a
    minimal local checkout may not have optional pandas/requests dependencies
    installed.  A deep scan should still be able to inspect the four local
    watchlist entries instead of silently scanning zero tokens.
    """
    try:
        with open(os.path.join(BASE_DIR, "watchlist.json"), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

try:
    from watchlist import add_to_watchlist, load_watchlist
except Exception:
    add_to_watchlist = lambda ca, symbol="?", source="", **kw: False
    load_watchlist = _load_local_watchlist

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
            r = rq.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)
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

# ---------------------------------------------------------------------------
# GMGN market authority helpers
# ---------------------------------------------------------------------------
def _num(*values, default=0.0) -> float:
    """First finite numeric among *values* (GMGN sends strings/None)."""
    for v in values:
        if v is None or isinstance(v, bool) or v == "":
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f in (float("inf"), float("-inf")):   # NaN / ±inf
            continue
        return f
    return float(default)


def market_from_gmgn_row(gmgn_row, ca: str = None) -> dict:
    """Build the deep-scan market snapshot from a GMGN row.

    Accepts a scored row from ``gmgn_screener.score_token`` / the incubation
    radar (``mc`` / ``liq`` / ``vol24`` / …) or a raw-ish dict with the long
    GMGN aliases, and returns the ``get_market``-shaped dict the gate logic
    consumes — but tagged ``market_source = "gmgn"`` so no caller can
    silently mix it with DexScreener numbers.  Every metric the gates use
    (MC, liquidity, vol24, vol/MC, holders, T10, risk fields) comes from the
    same row, which is exactly what keeps Stage 1 and Stage 2 consistent.

    Returns ``{}`` when the row carries no usable market cap — that is the
    "snapshot unavailable" case and the caller must fail closed instead of
    back-filling from DexScreener/history.
    """
    if not isinstance(gmgn_row, dict) or not gmgn_row:
        return {}
    # Never mislabel a history/Dex fallback as GMGN-authoritative.
    explicit_src = gmgn_row.get("market_source") or gmgn_row.get("_source")
    if explicit_src not in (None, "", "gmgn"):
        return {}
    mc = _num(gmgn_row.get("mc"), gmgn_row.get("marketcap"),
              gmgn_row.get("market_cap"), gmgn_row.get("usd_market_cap"))
    if mc <= 0:
        return {}
    liq = _num(gmgn_row.get("liq"), gmgn_row.get("liquidity_usd"),
               gmgn_row.get("liquidity"), gmgn_row.get("lq"))
    vol_raw = gmgn_row.get("vol24")
    if vol_raw is None:
        vol_field = gmgn_row.get("volume")
        if isinstance(vol_field, dict):
            vol_raw = vol_field.get("h24", vol_field.get("24h"))
        elif vol_field is not None:
            vol_raw = vol_field
    vol = _num(vol_raw, gmgn_row.get("volume_24h"), gmgn_row.get("v"))

    t10 = gmgn_row.get("t10_pct")
    if t10 is None:
        t10 = gmgn_row.get("top_10_holder_rate")
    if t10 is not None:
        try:
            t10 = float(t10)
            if t10 != t10 or t10 in (float("inf"), float("-inf")):
                t10 = None
            elif 0 < t10 <= 1:
                t10 *= 100     # raw rate (0-1) -> percent
        except (TypeError, ValueError):
            t10 = None

    vol_mc = _num(gmgn_row.get("vol_mc"))
    if not vol_mc and mc and vol:
        vol_mc = vol / mc

    addr = gmgn_row.get("ca") or gmgn_row.get("a") or ca
    return {
        "symbol": gmgn_row.get("symbol") or gmgn_row.get("s") or "?",
        "name": gmgn_row.get("name") or gmgn_row.get("nm") or "",
        "price_usd": _num(gmgn_row.get("price_usd"), gmgn_row.get("price"),
                          gmgn_row.get("p")),
        "marketcap": mc,
        "liquidity_usd": liq,
        "liq_pct_mc": (liq / mc * 100) if mc else 0,
        "volume": {"h24": vol},
        "vol_mc": round(vol_mc, 4),
        "holders": _num(gmgn_row.get("holders"), gmgn_row.get("holder_count"),
                        gmgn_row.get("hd")),
        "t10_pct": t10,
        "age_d": _num(gmgn_row.get("age_d")),
        "chg24": _num(gmgn_row.get("chg24"), gmgn_row.get("pcp")),
        # risk fields for the safety gates & health display
        "insider_ratio": _num(gmgn_row.get("insider_ratio"),
                              gmgn_row.get("dev_team_hold_rate")),
        "bundler_rate": _num(gmgn_row.get("bundler_rate"),
                             gmgn_row.get("top_bundler_trader_percentage")),
        "fresh_wallet_rate": _num(gmgn_row.get("fresh_wallet_rate"),
                                  gmgn_row.get("fwr")),
        "entrap_rate": _num(gmgn_row.get("entrap_rate"),
                            gmgn_row.get("top_entrapment_trader_percentage")),
        "botdegen_rate": _num(gmgn_row.get("botdegen_rate"),
                              gmgn_row.get("bot_degen_rate")),
        "rug": _num(gmgn_row.get("rug"), gmgn_row.get("rug_ratio")),
        "market_source": "gmgn",
        "url": f"https://gmgn.ai/sol/token/{addr}" if addr else "",
    }


def _fetch_gmgn_token_prices(ca: str, timeout: int = 15):
    """POST /api/v1/token_prices — best-effort mc/liq/vol/price for one CA.

    Response shape is undocumented (the HAR capture only recorded the call),
    so the parser accepts dict/list payloads and the usual GMGN field
    aliases.  Returns a small dict of positive numbers or ``None``.
    """
    try:
        from curl_cffi import requests as cr
    except ImportError:
        return None
    try:
        r = cr.post(
            "https://gmgn.ai/api/v1/token_prices",
            json={"chain": "sol", "interval": "24h", "addresses": [ca]},
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/plain, */*",
                "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/150.0.0.0 Safari/537.36"),
            },
            impersonate="chrome", timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    item = None
    payload = data.get("data") if isinstance(data, dict) else None
    if isinstance(payload, dict):
        item = payload.get(ca)
        if item is None:
            item = next(iter(payload.values()), None)
    elif isinstance(payload, list) and payload:
        item = payload[0]
    elif isinstance(data, list) and data:
        item = data[0]
    if not isinstance(item, dict):
        return None
    out = {
        "p": _num(item.get("price"), item.get("usd_price"), item.get("p")),
        "mc": _num(item.get("usd_market_cap"), item.get("market_cap"),
                   item.get("mc")),
        "lq": _num(item.get("liquidity"), item.get("lq")),
        "v": _num(item.get("volume"), item.get("volume_24h"), item.get("v")),
    }
    return {k: v for k, v in out.items() if v > 0} or None


def fetch_gmgn_market_row(ca: str, timeout: int = 15):
    """Best-effort live GMGN market snapshot for a single CA.

    Used only when no Stage-1 radar row was handed in (``--ca`` / watchlist
    scans).  Combines ``gmgn_token_stat`` (rich holder/risk fields, long-form
    market aliases) and, when no market cap was found there, the batch
    ``token_prices`` endpoint, then normalises through
    ``gmgn_screener.score_token`` so the row has the exact same shape as a
    Stage-1 radar row.

    Returns ``(row, stat)`` on success, ``None`` when GMGN has no usable
    snapshot for this CA.
    """
    try:
        stat = gmgn_token_stat(ca, timeout=timeout) or {}
    except Exception:
        stat = {}
    if not isinstance(stat, dict):
        stat = {}
    raw = stat.get("raw")
    merged = dict(raw) if isinstance(raw, dict) else {}
    if _num(merged.get("mc"), merged.get("market_cap"),
            merged.get("usd_market_cap")) <= 0:
        prices = _fetch_gmgn_token_prices(ca, timeout=timeout)
        if prices:
            for k, v in prices.items():
                if v not in (None, ""):
                    merged[k] = v
    if not merged:
        return None
    merged.setdefault("a", ca)
    merged.setdefault("address", ca)
    try:
        from gmgn_screener import score_token
        row = score_token(merged) or {}
    except Exception:
        return None
    if not row.get("ca"):
        row["ca"] = ca
    if not row.get("holders") and stat.get("total_holders"):
        row["holders"] = stat["total_holders"]
    if _num(row.get("mc")) <= 0:
        return None
    return row, stat


def _divergence_notes(gmgn_market: dict, dex_market: dict,
                      rel_tol: float = 0.10, abs_tol: float = 1500.0) -> list:
    """Human-readable GMGN-vs-DexScreener divergence warnings.

    GMGN aggregates transactions across all pools of a token while
    DexScreener reports the single deepest pair, so mismatches (e.g.
    MEMIPEDE vol24 $70k GMGN vs $45k Dex) are expected.  Each note states
    explicitly that the GMGN figure is the authoritative one.  Returns an
    empty list when either side is missing or all metrics agree within
    ``max(abs_tol, rel_tol * value)``.
    """
    notes = []
    if not gmgn_market or not dex_market:
        return notes
    dex_vol = dex_market.get("volume")
    dex_vol24 = dex_vol.get("h24") if isinstance(dex_vol, dict) else None
    metrics = [
        ("mc", gmgn_market.get("marketcap"), dex_market.get("marketcap")),
        ("liq", gmgn_market.get("liquidity_usd"),
         dex_market.get("liquidity_usd")),
        ("vol24", (gmgn_market.get("volume") or {}).get("h24"), dex_vol24),
    ]
    for label, g_val, d_val in metrics:
        try:
            g_val = float(g_val or 0)
            d_val = float(d_val or 0)
        except (TypeError, ValueError):
            continue
        if g_val <= 0 or d_val <= 0:
            continue
        diff = abs(g_val - d_val)
        if diff > max(abs_tol, rel_tol * max(g_val, d_val)):
            notes.append(
                f"GMGN {label} ${g_val:,.0f} vs DexScreener ${d_val:,.0f} "
                f"(divergence {diff / max(g_val, d_val) * 100:.0f}%) — "
                "GMGN authoritative")
    return notes


def deep_scan_token(ca: str, relaxed: bool = False, do_cluster: bool = False,
                    helius_keys=None, gmgn_row=None):
    """Full deep scan for one CA with an explicit accumulation mode.

    Market gates are intentionally independent from the CTO/conviction checks:
    a trending token must not become an accumulation candidate merely because
    its conviction history is positive.  Strict mode uses $45k liquidity,
    $90k volume and 50% Top-10; pre-CTO relaxed mode uses $50k, $100k and 55%.

    ``gmgn_row`` is the Stage-1 incubation-radar row for this CA.  When it is
    provided, every market metric the gates read (MC / liquidity / vol24 /
    vol-MC / holders / T10 / risk fields) comes from that row, so Stage 2 can
    never disagree with the numbers the radar admitted.  Without a row the
    scan tries a live GMGN snapshot (:func:`fetch_gmgn_market_row`).  If no
    GMGN snapshot exists the scan FAILS CLOSED — DexScreener and history.json
    are never used for MC/liquidity/volume/pass criteria, only for CTO claim
    detection, links, symbol metadata, and divergence logging.
    """
    if helius_keys is None:
        helius_keys = tuple(get_helius_keys())

    result = {
        "ca": ca,
        "symbol": "?",
        "market": {},
        "market_source": None,
        "market_divergence": [],
        "market_notes": [],
        "dex_market": {},
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

    # 1. Market — GMGN ONLY (see module docstring).  Priority: the Stage-1
    # radar row handed in by the caller, then a live per-CA GMGN snapshot.
    # DexScreener/history fallbacks were removed on purpose (PR follow-up):
    # Dex reads one pool, GMGN counts all of them, and silently mixing the
    # two sources is exactly what made Stage 1 and Stage 2 numbers differ.
    m = {}
    prefetched_stat = {}
    gmgn_origin = None
    if isinstance(gmgn_row, dict) and gmgn_row:
        m = market_from_gmgn_row(gmgn_row, ca=ca)
        if m:
            gmgn_origin = "radar row"
        else:
            result["market_notes"].append(
                "gmgn_row supplied but unusable (no GMGN mc field)")
    if not m:
        try:
            fetched = fetch_gmgn_market_row(ca)
        except Exception as e:
            fetched = None
            result["market_notes"].append(f"live GMGN snapshot error: {e}")
        if fetched:
            live_row, prefetched_stat = fetched
            m = market_from_gmgn_row(live_row, ca=ca)
            if m:
                gmgn_origin = "live snapshot"
    if m:
        result["market"] = m
        result["market_source"] = "gmgn"
        if m.get("symbol") and m.get("symbol") != "?":
            result["symbol"] = m.get("symbol")
    else:
        result["market"] = {"market_source": None}

    # DexScreener — metadata ONLY: symbol/url hints for display and the
    # divergence log below.  Its MC/liquidity/volume are never written into
    # ``result["market"]`` and never feed a gate.
    dex_m = {}
    try:
        dex_m = get_market(ca) or {}
    except Exception as e:
        result["market_notes"].append(f"dex metadata fetch failed: {e}")
    if dex_m:
        try:
            result["dex_market"] = {
                "symbol": dex_m.get("symbol"),
                "url": dex_m.get("url"),
                "marketcap": dex_m.get("marketcap"),
                "liquidity_usd": dex_m.get("liquidity_usd"),
                "volume_h24": ((dex_m.get("volume") or {}).get("h24")
                               if isinstance(dex_m.get("volume"), dict) else None),
            }
        except Exception:
            result["dex_market"] = {}
        if (not result["symbol"] or result["symbol"] == "?") and dex_m.get("symbol"):
            # Display metadata only — allowed.
            result["symbol"] = dex_m["symbol"]
    result["market_divergence"] = _divergence_notes(m, dex_m) if m else []
    result["market_notes"].extend(result["market_divergence"])
    for _note in result["market_divergence"]:
        print(f"  [market-source] {_note}")

    price = m.get("price_usd") or m.get("price") or 0
    mc = m.get("marketcap") or m.get("mc") or 0
    liq = m.get("liquidity_usd") or m.get("liq") or 0

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
        # fallback GMGN top10 (reuse the stat already fetched for the live
        # market snapshot when we have it — saves one GMGN round-trip)
        try:
            gmgn_stat = prefetched_stat or gmgn_token_stat(ca)
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
            except Exception:
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

    # 6. Pass criteria for CTO incubation.  These are deliberately explicit
    # here instead of reusing the LP or GMGN trending thresholds: deep scan is
    # the final guard against a trending token being treated as accumulation.
    liq_max = 50000 if relaxed else 45000
    vol_max = 100000 if relaxed else 90000
    t10_max = 55 if relaxed else 50
    mode = "relaxed/pre-CTO" if relaxed else "strict/death-valley"

    # Volume is GMGN's 24h value (cross-pool ``v``), marked h24 in the
    # snapshot dict.  Never substitute DexScreener's single-pair h24 here.
    volume = m.get("volume") or {}
    if isinstance(volume, dict):
        vol = volume.get("h24", volume.get("24h", 0)) or 0
    else:
        vol = volume or 0
    try:
        vol = float(vol)
    except (TypeError, ValueError):
        vol = 0.0

    # T10 priority: the GMGN row first (authoritative — the same value the
    # radar admitted), then on-chain Helius concentration, then the raw
    # token_stat rate.  A missing holder snapshot is neutral in no-Helius
    # mode, as it was before; it must not turn a market-quality check into a
    # false failure.
    conc_top10 = None
    for candidate in (m.get("t10_pct"), m.get("top10_pct"), m.get("t10")):
        if candidate is not None:
            try:
                conc_top10 = float(candidate)
                if 0 < conc_top10 <= 1:
                    conc_top10 *= 100
                break
            except (TypeError, ValueError):
                pass
    if conc_top10 is None:
        conc_top10 = result["concentration"].get("top10")
    if conc_top10 is None:
        gmgn_raw = result.get("gmgn_stat", {}).get("raw") or {}
        t10_rate = gmgn_raw.get("top_10_holder_rate")
        if t10_rate is not None:
            try:
                conc_top10 = float(t10_rate)
                if 0 <= conc_top10 <= 1:
                    conc_top10 *= 100
            except (TypeError, ValueError):
                conc_top10 = None
    # No holder provider is a soft/neutral signal, not a reason to admit a
    # token outside the market gates.
    t10_known = conc_top10 is not None
    if conc_top10 is None:
        conc_top10 = 30.0

    health_score_val = result["health"].get("score", 0)
    has_helius = len(helius_keys) > 0
    conv_rising = result["conviction"].get("rising", False)
    conv_reason = result["conviction"].get("reason", "")
    conv_data = result["conviction"].get("last") or {}
    try:
        net_pure = float(conv_data.get("net_pure", 0) or 0)
    except (TypeError, ValueError):
        net_pure = 0.0

    passes = []
    fails = []

    # Fail closed: without an authoritative GMGN snapshot the market gates
    # cannot pass.  DexScreener/history numbers are intentionally NOT read
    # here — gate on what we actually know and say so loudly.
    market_known = bool(m)
    if market_known:
        liq_ok = 3000 <= liq <= liq_max
        mc_ok = 3000 <= mc <= 1000000
        vol_ok = vol <= vol_max
    else:
        liq_ok = mc_ok = vol_ok = False
    t10_ok = conc_top10 <= t10_max

    if market_known:
        passes.append(f"market source: GMGN ({gmgn_origin or 'snapshot'})")
    else:
        fails.append("GMGN market snapshot unavailable — fail closed "
                     "(DexScreener/history not allowed for market gates)")

    if not market_known:
        pass  # the market gate lines below would be pure noise without data
    elif liq_ok:
        passes.append(f"liq ${liq:.0f} in 3k-{liq_max // 1000}k ({mode})")
    else:
        fails.append(f"liq ${liq:.0f} NOT in 3k-{liq_max // 1000}k ({mode})")
    if market_known and mc_ok:
        passes.append(f"mc ${mc:.0f} in 3k-1M")
    elif market_known:
        fails.append(f"mc ${mc:.0f} NOT in 3k-1M")
    if market_known and vol_ok:
        passes.append(f"vol24 ${vol:.0f} <=${vol_max // 1000}k")
    elif market_known:
        fails.append(f"vol24 ${vol:.0f} >${vol_max // 1000}k")
    if t10_ok:
        suffix = " (neutral/no holder snapshot)" if not t10_known else ""
        passes.append(f"top10 {conc_top10:.1f}% <={t10_max}%{suffix}")
    else:
        fails.append(f"top10 {conc_top10:.1f}% >{t10_max}%")

    health_ok = health_score_val >= 50 or not has_helius
    if health_score_val >= 50:
        passes.append(f"health {health_score_val} >=50")
    elif not has_helius:
        passes.append(f"health {health_score_val} soft (no helius)")
    else:
        fails.append(f"health {health_score_val} <50")

    if result["cto"]:
        passes.append(f"CTO TRUE ({result['cto_detail']})")
    else:
        passes.append("CTO false (early accumulation allowed)")

    # A positive latest pure-flow reading is enough for an early accumulation
    # candidate; the old ``consecutive_ups`` shortcut admitted RAKO even while
    # its latest net_pure had already turned negative.
    conviction_ok = bool(result["cto"] or conv_rising or net_pure > 0)
    if conviction_ok:
        passes.append(f"conviction positive/rising: {conv_reason} net {net_pure:g}")
    else:
        fails.append(f"conviction NOT positive/rising: {conv_reason} net {net_pure:g}")

    result["deep_thresholds"] = {
        "relaxed": relaxed,
        "liq_max": liq_max,
        "mc_min": 3000,
        "mc_max": 1000000,
        "vol_max": vol_max,
        "t10_max": t10_max,
        "market_source": result.get("market_source"),
    }
    # ``market_known`` is redundant (liq/mc/vol already fail closed) but kept
    # explicit so a future refactor cannot re-open the gate accidentally.
    result["pass"] = market_known and all(
        (liq_ok, mc_ok, vol_ok, t10_ok, health_ok, conviction_ok))
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
            src = (res.get("market", {}) or {}).get("market_source") or "?"
            msg = (
                f"💀 CTO Radar Hit: ${symbol} ({ca_str[:8]}...)\n"
                f"Market source: {src.upper()}\n"
                f"MC ${res.get('market',{}).get('marketcap',0):,.0f} Liq ${res.get('market',{}).get('liquidity_usd',0):,.0f} Vol24 ${(res.get('market',{}).get('volume') or {}).get('h24',0):,.0f}\n"
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
    parser.add_argument("--relaxed", action="store_true",
                        help="pre-CTO mode: liq <=$50k, vol <=$100k, Top10 <=55%")
    parser.add_argument("--delay", type=float, default=0.8,
                        help="seconds to sleep between API call windows per token (default 0.8)")
    args = parser.parse_args()

    helius_keys = tuple(get_helius_keys())
    print(f"Helius keys: {len(helius_keys)} configured")
    print("Mode: " + ("RELAXED / PRE-CTO (liq <=$50k, vol <=$100k, T10 <=55%)"
                       if args.relaxed else
                       "STRICT / DEATH VALLEY (liq <=$45k, vol <=$90k, T10 <=50%)"))

    cas_to_scan = []
    gmgn_rows = {}

    if args.ca:
        cas_to_scan = [args.ca]
    elif args.from_radar:
        print("Running incubation_radar to get candidates (2d min)...")
        try:
            from incubation_radar import screen_incubation
            candidates, _, _ = screen_incubation(relaxed=args.relaxed, debug=False)
            cas_to_scan = [r["ca"] for r in candidates[:args.limit]]
            # Keep the CA -> GMGN row mapping so Stage 2 gates run on the
            # exact market numbers Stage 1 admitted (GMGN is authoritative —
            # DexScreener single-pair metrics must never overwrite them).
            gmgn_rows = {r["ca"]: r for r in candidates[:args.limit] if r.get("ca")}
            print(f"Radar found {len(cas_to_scan)} candidates (GMGN rows attached: {len(gmgn_rows)})")
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
        print("No radar rows — each token gets a live GMGN snapshot; "
              "without one the scan fails closed (Dex/history not used for gates)")

    results = []
    for i, ca in enumerate(cas_to_scan, 1):
        print(f"\n[{i}/{len(cas_to_scan)}] Deep scanning {ca}...")
        res = deep_scan_token(ca, relaxed=args.relaxed, helius_keys=helius_keys,
                              gmgn_row=gmgn_rows.get(ca))
        results.append(res)
        mkt = res.get("market") or {}
        src = mkt.get("market_source") or "UNAVAILABLE"
        vol24 = (mkt.get("volume") or {}).get("h24", 0) or 0
        print(f"  Market source: {src.upper() if src != 'UNAVAILABLE' else src} | "
              f"Symbol: {res.get('symbol')} MC ${mkt.get('marketcap',0):,.0f} "
              f"Liq ${mkt.get('liquidity_usd',0):,.0f} Vol24 ${vol24:,.0f} "
              f"(vol/mc {mkt.get('vol_mc',0)})")
        for note in res.get("market_divergence") or []:
            print(f"  ⚠ {note}")
        print(f"  Top10 {res.get('concentration',{}).get('top10',0):.1f}% (on-chain) GMGN T10 {mkt.get('t10_pct','?')}% Health {res.get('health',{}).get('score',0)} CTO {res.get('cto')} {res.get('cto_detail')}")
        print(f"  Conviction: {res.get('conviction',{}).get('reason','')}")
        print(f"  Pass: {res.get('pass')} Reasons: {' | '.join(res.get('reasons',[])[:6])}")
        if i < len(cas_to_scan):
            time.sleep(args.delay)

    passing = [r for r in results if r.get("pass")]
    print("\n=== SUMMARY ===")
    print(f"Scanned: {len(results)} | Passing: {len(passing)}")
    for r in passing:
        print(f"  ✅ {r.get('symbol')} {r['ca']} - {r.get('cto_detail')} - {r.get('conviction',{}).get('reason','')}")

    if args.auto_watchlist and passing:
        print("\nAuto-adding to watchlist...")
        added = auto_watchlist_and_telegram(passing, do_telegram=args.telegram)
        print(f"Added {len(added)} to watchlist")

if __name__ == "__main__":
    main()
