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


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
# Fit bands. Deliberately high: with the strict scoring below a token only
# clears 75 when *every* pillar is genuinely good, so green stays rare.
FIT_PRIME = 75      # green  — prime accumulation candidate
FIT_OK = 55         # yellow — decent, needs a manual Analyze
FIT_WEAK = 35       # grey   — weak
#: a token tripping any hard risk flag can never score above this
HIGH_RISK_CAP = 40

#: point budget per pillar (sums to 100)
WEIGHTS = {"price": 22, "t10": 20, "liq": 15, "smart": 14, "rug": 12,
           "vol": 9, "holders": 4, "age": 4}


def _f(v, default=0.0):
    """float() that never raises (GMGN sometimes sends null/str/absent)."""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    """int() that never raises."""
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _first(t, *keys, default=0.0):
    """First present key among *keys* (GMGN renames fields now and then)."""
    for k in keys:
        if k in t and t[k] not in (None, ""):
            return _f(t[k], default)
    return default


def fit_grade(fit: int, high_risk: bool = False) -> str:
    """Short human label for a fit score."""
    if high_risk:
        return "AVOID"
    if fit >= FIT_PRIME:
        return "PRIME"
    if fit >= FIT_OK:
        return "OK"
    if fit >= FIT_WEAK:
        return "WEAK"
    return "POOR"


def fit_color(fit: int, high_risk: bool = False) -> str:
    """Colour matching :func:`fit_grade` (shared by both UIs)."""
    if high_risk:
        return "#ef4444"
    if fit >= FIT_PRIME:
        return "#22c55e"
    if fit >= FIT_OK:
        return "#facc15"
    if fit >= FIT_WEAK:
        return "#94a3b8"
    return "#64748b"


def score_token(t):
    """GMGN token dict -> screener row + accumulation-fit score 0-100.

    Strict by design: points are only awarded for genuinely good readings,
    and red flags actively *subtract* points instead of merely not adding
    any. Anything tripping a hard risk flag is capped at
    :data:`HIGH_RISK_CAP` so it can never show up green.
    """
    now = time.time()
    mc = _first(t, "mc", "market_cap", "usd_market_cap")
    lq = _first(t, "lq", "liquidity")
    vol = _first(t, "v", "volume", "volume_24h")
    hd = _i(t.get("hd") or t.get("holder_count"))
    t10 = _first(t, "t10", "top_10_holder_rate") * 100
    smt = _i(t.get("smt") or t.get("smart_degen_count"))
    rug = _first(t, "rug", "rug_ratio")
    ot = _first(t, "ot", "open_timestamp", "created_timestamp", default=now)
    age_d = max(0.0, (now - ot) / 86400.0)
    chg24 = _first(t, "pcp", "price_change_percent24h")
    chg1h = _first(t, "pcp1h", "price_change_percent1h")
    insider = _first(t, "insider_ratio", "ins")
    bundler = _first(t, "bundler_rate", "bundler_ratio")
    liq_pct = lq / mc * 100 if mc else 0.0
    vol_mc = vol / mc if mc else 0.0

    score = 0
    notes = []
    wins = []

    # 1. Price action — we want a FLAT base, not a pump (max 22) ------------
    if -6 <= chg24 <= 8 and abs(chg1h) <= 5:
        score += 22
        wins.append("tight flat base")
    elif -12 <= chg24 <= 15:
        score += 15
        wins.append("price flat (accum window)")
    elif -25 <= chg24 <= 30:
        score += 6
    elif chg24 > 30:
        score += 2 if chg24 <= 60 else 0
    # (>30% / <-25% are called out by the gating section below)

    # 2. Top-10 concentration (max 20) --------------------------------------
    if t10 <= 12:
        score += 20
        wins.append(f"T10 only {t10:.0f}%")
    elif t10 <= 18:
        score += 15
    elif t10 <= 25:
        score += 8
    elif t10 <= 30:
        score += 3

    # 3. Liquidity vs MC (max 15) -------------------------------------------
    if liq_pct >= 15:
        score += 15
        wins.append(f"deep liq {liq_pct:.0f}% MC")
    elif liq_pct >= 10:
        score += 12
    elif liq_pct >= 6:
        score += 7
    elif liq_pct >= 3:
        score += 2

    # 4. Smart-money presence (max 14) --------------------------------------
    if smt >= 30:
        score += 14
        wins.append(f"{smt} smart wallets")
    elif smt >= 20:
        score += 11
        wins.append(f"{smt} smart wallets")
    elif smt >= 10:
        score += 6
    elif smt >= 5:
        score += 2

    # 5. Rug score (max 12) --------------------------------------------------
    if rug <= 0.15:
        score += 12
    elif rug <= 0.30:
        score += 8
    elif rug <= 0.45:
        score += 3

    # 6. Volume / MC sanity (max 9) -----------------------------------------
    if 0.4 <= vol_mc <= 2.0:
        score += 9
    elif 0.25 <= vol_mc <= 3.0:
        score += 5
    elif vol_mc > 5:
        notes.append(f"suspicious vol {vol_mc:.1f}x MC")
    elif vol_mc < 0.1:
        notes.append(f"illiquid vol {vol_mc:.2f}x MC")

    # 7. Holder base (max 4) -------------------------------------------------
    if hd >= 5000:
        score += 4
    elif hd >= 2500:
        score += 3
    elif hd >= 1000:
        score += 1

    # 8. Age — survived long enough to prove itself (max 4) ------------------
    if age_d >= 7:
        score += 4
    elif age_d >= 4:
        score += 2

    # ---- Penalties: red flags cost points, they don't just miss them ------
    penalty = 0
    if insider > 0.20:
        penalty += 18
    elif insider > 0.10:
        penalty += 8
    if bundler > 0.20:
        penalty += 18
    elif bundler > 0.10:
        penalty += 8
    if rug > 0.60:
        penalty += 15
    if t10 > 35:
        penalty += 12
    if smt < 3:
        penalty += 6
    if liq_pct < 3:
        penalty += 8
    score = max(0, score - penalty)

    # ---- Gating: a single broken pillar disqualifies the top grades -------
    # Without this a token can coast to PRIME on 7 good pillars while the
    # one that actually matters (e.g. "already +80%") is broken. Each failed
    # gate clamps the score, so PRIME really does mean "all-round clean".
    caps = []
    if chg24 > 25:
        caps.append((FIT_OK - 1, f"already ran +{chg24:.0f}%"))
    if chg24 < -25:
        caps.append((FIT_OK - 1, f"downtrend {chg24:.0f}%"))
    if smt < 10:
        caps.append((FIT_OK - 1, f"thin smart-money interest ({smt})"))
    if t10 > 25:
        caps.append((FIT_OK - 1, f"T10 {t10:.0f}% too concentrated"))
    if liq_pct < 5:
        caps.append((FIT_OK - 1, f"liq only {liq_pct:.1f}% MC"))
    if rug > 0.45:
        caps.append((FIT_OK - 1, f"rug score {rug:.2f}"))
    if age_d < 2:
        caps.append((FIT_OK - 1, f"only {age_d:.1f}d old"))
    if hd < 1000:
        caps.append((FIT_OK - 1, f"only {hd:,} holders"))
    if insider > 0.10 or bundler > 0.10:
        caps.append((FIT_OK - 1, "insider/bundler pressure"))
    if caps:
        cap_val = min(c for c, _ in caps)
        if score > cap_val:
            score = cap_val
        notes.extend(reason for _, reason in caps
                     if reason not in notes)

    # ---- Hard risk flags ---------------------------------------------------
    risk_reasons = []
    if rug > 0.60:
        risk_reasons.append(f"High rug score ({rug:.2f})")
    if t10 > 35:
        risk_reasons.append(f"Very concentrated (T10 {t10:.0f}%)")
    if insider > 0.20:
        risk_reasons.append(f"High insider ratio ({insider * 100:.0f}%)")
    if bundler > 0.20:
        risk_reasons.append(f"High bundler rate ({bundler * 100:.0f}%)")
    if liq_pct < 2:
        risk_reasons.append(f"Liquidity only {liq_pct:.1f}% of MC")
    if vol_mc > 8:
        risk_reasons.append(f"Volume {vol_mc:.0f}x MC (wash-trade smell)")
    high_risk = bool(risk_reasons)
    if high_risk:
        score = min(score, HIGH_RISK_CAP)

    return {
        "ca": t.get("a") or t.get("address"),
        "symbol": t.get("s") or t.get("symbol"),
        "name": t.get("nm") or t.get("name"),
        "mc": mc, "liq": lq, "liq_pct": round(liq_pct, 1),
        "vol24": vol, "vol_mc": round(vol_mc, 2),
        "holders": hd, "t10_pct": round(t10, 1), "smart": smt,
        "rug": round(rug, 2), "age_d": round(age_d, 1),
        "chg24": round(chg24, 1), "chg1h": round(chg1h, 1),
        "fit": int(score), "penalty": int(penalty),
        "grade": fit_grade(int(score), high_risk),
        "notes": "; ".join(notes),
        "wins": "; ".join(wins),
        "high_risk": high_risk,
        "risk_reasons": risk_reasons,
        "insider_ratio": round(insider, 3),
        "bundler_rate": round(bundler, 3),
    }


def screen():
    """Fetch + score + sort by fit desc. Returns list of rows.

    Rows without a contract address are dropped and duplicate CAs are
    collapsed, so callers can safely use ``ca`` as a widget key.
    """
    rows, seen = [], set()
    for t in fetch_trending():
        if not isinstance(t, dict):
            continue
        try:
            row = score_token(t)
        except Exception:
            continue
        ca = row.get("ca")
        if not ca or ca in seen:
            continue
        seen.add(ca)
        rows.append(row)
    rows.sort(key=lambda r: (-r["fit"], -r["smart"], r["t10_pct"]))
    return rows


# ------------------------------------------------------------------
# NEW: GMGN Token Trades (untuk CVD & flow analysis)
# ------------------------------------------------------------------
GMGN_TRADES_URL = "https://gmgn.ai/api/v1/token_trades/sol/{}?limit=50"

def fetch_gmgn_trades(ca: str, limit: int = 200, timeout: int = 20):
    """
    Fetch recent trades for a Solana token from GMGN.
    Returns list of dicts:
        {
            "wallet": str,
            "side": "buy" | "sell",
            "usd": float,
            "token_amount": float,
            "ts": int (unix timestamp)
        }
    """
    try:
        from curl_cffi import requests as cr
    except ImportError:
        return []

    all_trades = []
    cursor = None
    pages = 0
    max_pages = (limit // 50) + 1

    while pages < max_pages:
        url = GMGN_TRADES_URL.format(ca)
        if cursor:
            url += f"&cursor={cursor}"

        try:
            r = cr.get(url, impersonate="safari17_0", timeout=timeout, headers=HEADERS)
            if r.status_code != 200:
                break
            data = r.json()
            trades = (data.get("data") or {}).get("trades") or []
            if not trades:
                break

            for t in trades:
                all_trades.append({
                    "wallet": t.get("maker") or t.get("address"),
                    "side": "buy" if (t.get("event") or "").lower() == "buy" else "sell",
                    "usd": float(t.get("amount_usd") or t.get("usd") or 0),
                    "token_amount": float(t.get("amount_token") or t.get("token_amount") or 0),
                    "ts": int(t.get("timestamp") or t.get("time") or 0),
                })

            cursor = (data.get("data") or {}).get("next")
            pages += 1
            if not cursor or len(trades) < 50:
                break
            time.sleep(0.15)
        except Exception:
            break

    return all_trades[:limit]


def gmgn_trades_to_swaps(trades):
    """
    Convert GMGN trades ke format yang mirip Helius swaps
    untuk dipakai di CVD analysis.
    Return: list of (side, sol_amount, ts, wallet)
    """
    swaps = []
    for t in trades:
        # Estimasi SOL (kasar, karena GMGN kasih USD)
        # Kita pakai rata-rata $180/SOL sebagai estimasi
        sol_est = round(t["usd"] / 180, 4) if t["usd"] > 0 else 0
        if sol_est < 0.1:
            continue
        swaps.append((
            t["side"],
            sol_est,
            t["ts"],
            t["wallet"]
        ))
    return swaps


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

    # Contoh fetch trades
    if rows:
        print("\n--- Sample trades for first token ---")
        trades = fetch_gmgn_trades(rows[0]["ca"], limit=30)
        print(f"Fetched {len(trades)} trades")
        for t in trades[:5]:
            print(t)
