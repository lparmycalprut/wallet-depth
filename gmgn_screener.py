# -*- coding: utf-8 -*-
"""GMGN trending screener - pulls the trending_rank endpoint (same one the
GMGN web app uses) with accumulation-friendly filters, then scores tokens
against this tool's criteria. curl_cffi Safari fingerprint passes GMGN CF."""
import json
import time
import uuid

DEVICE_ID = str(uuid.uuid4())
GMGN_URL = ("https://gmgn.ai/trs/api/v1/trending_rank?"
            "device_id=" + DEVICE_ID + "&client_id=gmgn_web_20250101&"
            "from_app=gmgn&app_ver=20250101&tz_name=Asia%2FJakarta&"
            "tz_offset=25200&app_lang=en&os=web&worker=0")

FILTER_BODY = {
    "meta": {},
    "params": [{
        "chain": "sol",
        "interval": "24h",
        "filter": {
            "filters": ["migrated", "not_wash_trading", "renounced",
                        "frozen"],
            "min_created": "2880m",
            "max_created": "43200m",
            "min_liquidity": 30000,
            "min_marketcap": 100000,
            "min_holder_count": 1000,
            "min_gas_fee": 20,
            "max_insider_ratio": 0.15,
            "max_bundler_rate": 0.15,
            "min_volume_24h": 100000,
        },
    }],
}

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "origin": "https://gmgn.ai",
    "referer": "https://gmgn.ai/trend?chain=sol",
}


def fetch_trending(timeout=25):
    """Return raw token dicts from GMGN trending (may be empty)."""
    try:
        from curl_cffi import requests as cr
    except ImportError:
        return []
    try:
        r = cr.post(GMGN_URL, impersonate="safari17_0", timeout=timeout,
                    headers=HEADERS, data=json.dumps(FILTER_BODY))
        if r.status_code != 200 or not r.text.startswith("{"):
            return []
        data = r.json()
        return ((data.get("data") or [{}])[0].get("tokens")) or []
    except Exception:
        return []


def score_token(t):
    """GMGN token dict -> screener row + accumulation-fit score 0-100."""
    now = time.time()
    mc = float(t.get("mc") or 0)
    lq = float(t.get("lq") or 0)
    vol = float(t.get("v") or 0)
    hd = int(t.get("hd") or 0)
    t10 = float(t.get("t10") or 0) * 100
    smt = int(t.get("smt") or 0)
    try:
        rug = float(t.get("rug") or 0)
    except Exception:
        rug = 0.0
    age_d = (now - (t.get("ot") or now)) / 86400.0
    chg24 = float(t.get("pcp") or 0)
    chg1h = float(t.get("pcp1h") or 0)
    liq_pct = lq / mc * 100 if mc else 0
    vol_mc = vol / mc if mc else 0

    score = 0
    notes = []
    # 1. price flat = accumulation window (max 25)
    if -10 <= chg24 <= 15:
        score += 25
        notes.append("price flat (accum window)")
    elif chg24 > 50:
        notes.append("already pumped (late)")
    elif chg24 < -30:
        notes.append("dumping")
    else:
        score += 10
    # 2. concentration (max 20)
    if t10 <= 20:
        score += 20
    elif t10 <= 30:
        score += 10
    else:
        notes.append("T10 " + str(round(t10)) + "% concentrated")
    # 3. liquidity health (max 15)
    if liq_pct >= 10:
        score += 15
    elif liq_pct >= 5:
        score += 8
    else:
        notes.append("thin liq")
    # 4. smart money presence (max 15)
    if smt >= 20:
        score += 15
        notes.append(str(smt) + " smart wallets")
    elif smt >= 8:
        score += 8
    # 5. rug score (max 15)
    if rug <= 0.3:
        score += 15
    elif rug <= 0.5:
        score += 7
    else:
        notes.append("rug risk " + str(round(rug, 2)))
    # 6. healthy volume/mc ratio 0.3-3x (max 10)
    if 0.3 <= vol_mc <= 3:
        score += 10
    elif vol_mc > 5:
        notes.append("suspicious vol " + str(round(vol_mc, 1)) + "x MC")

    return {
        "ca": t.get("a"), "symbol": t.get("s"), "name": t.get("nm"),
        "mc": mc, "liq": lq, "liq_pct": round(liq_pct, 1),
        "vol24": vol, "vol_mc": round(vol_mc, 2),
        "holders": hd, "t10_pct": round(t10, 1), "smart": smt,
        "rug": round(rug, 2), "age_d": round(age_d, 1),
        "chg24": round(chg24, 1), "chg1h": round(chg1h, 1),
        "fit": score, "notes": "; ".join(notes),
    }


def screen():
    """Fetch + score + sort by fit desc. Returns list of rows."""
    toks = fetch_trending()
    rows = [score_token(t) for t in toks]
    rows.sort(key=lambda r: -r["fit"])
    return rows


if __name__ == "__main__":
    rows = screen()
    print("tokens:", len(rows))
    for r in rows:
        print(str(r["fit"]).rjust(3), (r["symbol"] or "?").ljust(10),
              "MC $" + format(r["mc"], ",.0f"),
              "| T10 " + str(r["t10_pct"]) + "%",
              "| smart " + str(r["smart"]),
              "| 24h " + str(r["chg24"]) + "%",
              "|", r["notes"])
