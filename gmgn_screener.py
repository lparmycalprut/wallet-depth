# -*- coding: utf-8 -*-
"""GMGN trending screener - pulls the trending_rank endpoint (same one the
GMGN web app uses) with accumulation-friendly filters, then scores tokens
against this tool's criteria. curl_cffi Safari fingerprint passes GMGN CF."""
import json
import time
import uuid

DEVICE_ID = str(uuid.uuid4())
#: browser-fingerprint id — GMGN only checks that it's present & hex-ish
FP_DID = uuid.uuid4().hex
GMGN_ORIGIN = "https://gmgn.ai"
TRENDING_PATH = "/trs/api/v1/trending_rank"
VERSION_URL = GMGN_ORIGIN + "/version.json"

#: fallback build tag; the real one is fetched from /version.json at runtime
#: (verified against a browser HAR capture — the web app sends its build tag
#: as both client_id and app_ver, and a stale value gets soft-blocked).
DEFAULT_BUILD = "20260728-2617-057cd43"
_build_cache = {"tag": "", "ts": 0.0}


def _build_tag(timeout=10):
    """Current GMGN web build tag, cached for an hour.

    GMGN bumps this on every deploy and rejects/soft-blocks obviously stale
    clients, which is why a hard-coded ``20250101`` eventually stops working.
    """
    now = time.time()
    if _build_cache["tag"] and now - _build_cache["ts"] < 3600:
        return _build_cache["tag"]
    tag = DEFAULT_BUILD
    try:
        from curl_cffi import requests as cr
        r = cr.get(VERSION_URL, impersonate="chrome", timeout=timeout)
        if r.status_code == 200:
            # {"buildTag":"20260728-2617-master-057cd43","seq":2617,...}
            raw = (r.json() or {}).get("buildTag") or ""
            # query params use the tag WITHOUT the "master-" branch segment
            parts = [p for p in raw.split("-") if p and p != "master"]
            if len(parts) >= 3:
                tag = "-".join(parts[:3])
    except Exception:
        pass
    _build_cache.update(tag=tag, ts=now)
    return tag


def _trending_url():
    """Full trending_rank URL with the query params the web app sends."""
    build = _build_tag()
    return (f"{GMGN_ORIGIN}{TRENDING_PATH}?"
            f"device_id={DEVICE_ID}&fp_did={FP_DID}&"
            f"client_id=gmgn_web_{build}&from_app=gmgn&app_ver={build}&"
            f"tz_name=Asia%2FJakarta&tz_offset=25200&app_lang=en-US&"
            f"os=web&worker=0")

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

# Header set copied from a real browser capture (HAR). curl_cffi's "chrome"
# fingerprint + these headers is what gets past GMGN's Cloudflare check.
# No cookie/auth is needed — the trending endpoint is public.
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "content-type": "application/json",
    "origin": GMGN_ORIGIN,
    "referer": GMGN_ORIGIN + "/trend?chain=sol",
    "priority": "u=1, i",
    "sec-ch-ua": ('"Not;A=Brand";v="8", "Chromium";v="150", '
                  '"Google Chrome";v="150"'),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/150.0.0.0 Safari/537.36"),
}


def fetch_trending(timeout=25, debug=False):
    """Return raw token dicts from GMGN trending (may be empty).

    Set ``debug=True`` to print why a fetch came back empty instead of
    silently swallowing it.
    """
    try:
        from curl_cffi import requests as cr
    except ImportError:
        if debug:
            print("curl_cffi not installed — run: pip install curl_cffi")
        return []

    last = ""
    # a couple of fingerprints, in case one gets stale with a CF update
    for imp in ("chrome", "chrome131", "safari17_0"):
        try:
            r = cr.post(_trending_url(), impersonate=imp, timeout=timeout,
                        headers=HEADERS, data=json.dumps(FILTER_BODY))
        except Exception as exc:                        # noqa: BLE001
            last = f"{imp}: {type(exc).__name__}: {exc}"
            continue
        if r.status_code != 200:
            last = f"{imp}: HTTP {r.status_code}"
            continue
        try:
            data = r.json()
        except Exception:
            last = f"{imp}: non-JSON reply ({r.text[:80]!r})"
            continue
        if data.get("code") not in (0, None):
            last = f"{imp}: api code={data.get('code')} {data.get('message')}"
            continue
        blocks = data.get("data") or []
        if isinstance(blocks, dict):          # tolerate a shape change
            blocks = [blocks]
        toks = []
        for b in blocks:
            toks.extend((b or {}).get("tokens") or [])
        if toks:
            return toks
        last = f"{imp}: 200 OK but 0 tokens (filters too strict?)"
    if debug and last:
        print("GMGN fetch failed —", last)
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
    """float() that never raises and never returns NaN/inf.

    GMGN occasionally sends null, "", or a string; a corrupted/hostile reply
    could carry NaN or inf, which would silently poison every comparison
    below (NaN compares False against everything) — so those collapse to
    *default* too.
    """
    try:
        if v is None or isinstance(v, bool) or v == "":
            return default
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):   # NaN / ±inf
        return default
    return f


def _i(v, default=0):
    """int() that never raises (NaN/inf-safe, see :func:`_f`)."""
    f = _f(v, float(default))
    try:
        return int(max(-1e15, min(1e15, f)))
    except (TypeError, ValueError, OverflowError):
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
    # Field names verified against a real browser capture of
    # POST /trs/api/v1/trending_rank (see docs/gmgn_api.md). The long-form
    # aliases are what /api/v1/token_stat returns, kept as a fallback in
    # case GMGN ever switches the trending payload to the verbose shape.
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
    # ⚠️ trending_rank has NO "insider_ratio"/"bundler_rate" key — the real
    # ones are bdrr / bdr / dhr / snp. Using the old names meant these
    # penalties never fired on live data.
    bundler = _first(t, "bdrr", "top_bundler_trader_percentage",
                     "bundler_rate")          # bundler-traded supply share
    insider = _first(t, "dhr", "dev_team_hold_rate", "insider_ratio")
    entrap = _first(t, "etpr", "top_entrapment_trader_percentage")
    botdeg = _first(t, "bdr", "bot_degen_rate")
    sniper = _first(t, "t70_shr", "top70_sniper_hold_rate")
    snipers = _i(t.get("snp"))                # sniper wallet count
    kol = _i(t.get("kol"))                    # KOL/influencer wallets
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

    # 9. Smart-money quality bonus: KOL wallets alongside smart money is a
    #    stronger signal than raw count alone. Clamped to 100 below.
    if kol >= 5 and smt >= 10:
        score += 3
        wins.append(f"{kol} KOL wallets")
    score = min(100, score)

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
    # entrapment = wallets that trap buyers (honeypot-ish behaviour)
    if entrap > 0.40:
        penalty += 14
    elif entrap > 0.25:
        penalty += 6
    # bot-degen dominated flow = fake activity
    if botdeg > 0.35:
        penalty += 12
    elif botdeg > 0.20:
        penalty += 5
    # snipers still sitting on supply
    if sniper > 0.10:
        penalty += 10
    elif sniper > 0.03:
        penalty += 4
    if snipers >= 30:
        penalty += 5
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
    if entrap > 0.30:
        caps.append((FIT_OK - 1, f"entrapment traders {entrap * 100:.0f}%"))
    if botdeg > 0.30:
        caps.append((FIT_OK - 1, f"bot-degen flow {botdeg * 100:.0f}%"))
    if caps:
        # The cap drops with BOTH the number of broken pillars and how much
        # penalty the token accrued — otherwise every flawed token piles up
        # on the exact same number and the list stops being rankable.
        cap_val = max(0, min(c for c, _ in caps)
                      - 3 * (len(caps) - 1)
                      - min(12, penalty // 2))
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
    if entrap > 0.40:
        risk_reasons.append(f"Entrapment traders {entrap * 100:.0f}%")
    if sniper > 0.10:
        risk_reasons.append(f"Snipers hold {sniper * 100:.0f}%")
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
        "insider_ratio": round(insider, 4),
        "bundler_rate": round(bundler, 4),
        "entrap_rate": round(entrap, 4),
        "botdegen_rate": round(botdeg, 4),
        "sniper_hold": round(sniper, 4),
        "snipers": snipers,
        "kol": kol,
        "price": _first(t, "p", "price"),
        "logo": t.get("l") or "",
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
    print("build tag:", _build_tag())
    raw = fetch_trending(debug=True)
    print("raw tokens:", len(raw))
    rows = sorted((score_token(t) for t in raw if isinstance(t, dict)),
                  key=lambda r: -r["fit"])
    if not rows:
        print("Nothing returned — see docs/gmgn_api.md for what to re-check.")
    for r in rows:
        print(str(r["fit"]).rjust(3), (r["grade"] or "").ljust(6),
              (r["symbol"] or "?").ljust(10),
              "MC $" + format(r["mc"], ",.0f"),
              "| T10 " + str(r["t10_pct"]) + "%",
              "| smart " + str(r["smart"]),
              "| 24h " + str(r["chg24"]) + "%",
              "| bndl " + format(r["bundler_rate"] * 100, ".0f") + "%",
              "| trap " + format(r["entrap_rate"] * 100, ".0f") + "%",
              "|", r["notes"] or r["wins"])

    # Contoh fetch trades
    if rows:
        print("\n--- Sample trades for first token ---")
        trades = fetch_gmgn_trades(rows[0]["ca"], limit=30)
        print(f"Fetched {len(trades)} trades")
        for t in trades[:5]:
            print(t)
