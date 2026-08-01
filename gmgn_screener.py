# -*- coding: utf-8 -*-
"""GMGN trending screener - pulls the trending_rank endpoint (same one the
GMGN web app uses) with structural LP filters, then scores tokens
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

#: Point budget per pillar (sums to 100). Fit now measures structural LP
#: quality only: ownership, executable liquidity, contract risk, and whether
#: volume is organic enough to support entries/exits.
WEIGHTS = {"t10": 30, "liq": 30, "rug": 25, "vol": 15}

# ---------------------------------------------------------------------------
# Continuous ramps instead of step thresholds
# ---------------------------------------------------------------------------
# The old scoring was a stack of if/elif ladders, so tiny input changes could
# swing the final score by 20+ points. Every pillar, penalty and gate below
# is now a piecewise-LINEAR curve that
# passes through the old thresholds — same calibration at the anchor points,
# but the values in between are interpolated instead of jumping.
#
# Each curve is a list of ``(x, y)`` anchors with x ascending; y is a
# *fraction* (0-1) of that pillar's weight for the reward curves, and raw
# penalty points for the penalty curves.

#: Reward curves: fraction of WEIGHTS[pillar] earned at each anchor.
CURVES = {
    # Top-10 holder concentration, %.
    "t10": [(12, 1.0), (18, 0.75), (25, 0.40), (30, 0.15),
            (35, 0.0)],
    # Liquidity as % of market cap.
    "liq": [(0, 0.0), (3, 0.13), (6, 0.47), (10, 0.80),
            (15, 1.0)],
    # GMGN rug score (0-1).
    "rug": [(0.15, 1.0), (0.30, 0.67), (0.45, 0.25),
            (0.60, 0.0)],
    # 24h volume / MC: too little is dead, too much can be wash trading.
    "vol": [(0.05, 0.0), (0.25, 0.56), (0.40, 1.0),
            (2.0, 1.0), (3.0, 0.56), (5.0, 0.0)],
}

#: penalty curves — raw points subtracted at each anchor
PENALTY_CURVES = {
    "insider": [(0.05, 0), (0.10, 8), (0.22, 18), (0.35, 26)],
    "bundler": [(0.05, 0), (0.10, 8), (0.22, 18), (0.35, 26)],
    "entrap": [(0.20, 0), (0.27, 6), (0.42, 14), (0.60, 20)],
    "botdeg": [(0.16, 0), (0.22, 5), (0.37, 12), (0.55, 18)],
    "sniper": [(0.02, 0), (0.04, 4), (0.11, 10), (0.25, 16)],
    "snipers": [(20, 0), (30, 5), (60, 9)],
    "rug": [(0.52, 0), (0.62, 15), (0.85, 22)],
    "t10": [(32, 0), (36, 12), (50, 20)],
    "liq_thin": [(0, 10), (3, 0)],
    # Fresh-wallet rate (% of holders whose first tx is <7 days old).
    # Anchored so a 25%+ fresh-wallet base starts hurting and 50%+ clearly
    # marks the token as a likely launch-and-dump.
    "fresh_wallet": [(0.15, 0), (0.25, 5), (0.40, 12), (0.55, 18)],
    # Holder concentration beyond the Top-10 already covered by t10. This
    # is a *cumulative* top-50+ holder band: when the top 50 alone hold
    # ≥80% of supply there is almost no public float, so the cap should
    # sit on AVOID regardless of other pillars.
    "holder_conc": [(0.55, 0), (0.65, 6), (0.75, 12), (0.85, 18)],
}

#: How the score ceiling slides with the worst gate's severity (0-1).
#: 0.0 → no cap at all · 0.5 (= the old hard threshold) → just under PRIME,
#: so crossing the line still costs the green badge · 1.0 → FIT_OK - 1,
#: exactly what the old code clamped to.
CAP_CURVE = [(0.0, 100.0), (0.25, 88.0), (0.5, FIT_PRIME - 1.0),
             (1.0, FIT_OK - 1.0)]


def _curve(x, anchors):
    """Piecewise-linear interpolation of *x* over ``(x, y)`` *anchors*.

    Anchors must have ascending x. Outside the range the nearest endpoint
    value is held, so the result is continuous everywhere — no cliffs.
    """
    x = _f(x)
    if x <= anchors[0][0]:
        return float(anchors[0][1])
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x <= x1:
            span = x1 - x0
            if span <= 0:
                return float(y1)
            return float(y0) + (float(y1) - float(y0)) * (x - x0) / span
    return float(anchors[-1][1])


def _pillar(name, x):
    """Points earned on *name* pillar = curve fraction × its weight."""
    return WEIGHTS[name] * _curve(x, CURVES[name])


def _sev(x, ok, bad):
    """Gate severity 0-1: 0 at (and beyond) *ok*, 1 at (and beyond) *bad*.

    Replaces a hard ``if x > threshold`` gate with a transition zone
    straddling that threshold, so a token sitting right on the line is
    only *partially* gated instead of losing 20 points to a rounding
    difference. The old hard threshold sits at the **midpoint** of the
    ``ok``→``bad`` band, i.e. severity 0.5, which keeps the calibration.

    The ramp is linear on purpose: a smoothstep is 1.5x steeper at its
    midpoint, and the midpoint is exactly the old threshold — the spot we
    most need to be gentle. Nothing jumps when a gate switches on either,
    because :data:`CAP_CURVE` starts at 100 (a no-op) at severity 0.
    """
    x = _f(x)
    if ok == bad:
        return 1.0 if ((x >= bad) if bad > ok else (x <= bad)) else 0.0
    return max(0.0, min(1.0, (x - ok) / (bad - ok)))


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
    """GMGN token dict -> screener row + structural Fit score 0-100.

    Strict by design: points are only awarded for genuinely good readings,
    and red flags actively *subtract* points instead of merely not adding
    any. Anything tripping a hard risk flag is capped at
    :data:`HIGH_RISK_CAP` so it can never show up green.

    Scoring is **continuous**: every pillar, penalty and gate interpolates
    between the calibration anchors in :data:`CURVES` / :data:`PENALTY_CURVES`
    (see :func:`_curve` and :func:`_sev`). A token sitting one wallet or one
    tenth of a percent from a threshold now scores one or two points apart,
    not twenty.
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
    # fresh_wallet_rate: % of holders whose first tx is <7 days old. GMGN
    # exposes it under a few different keys depending on the payload shape;
    # _first() walks them in order. 0.0 when missing — the curve naturally
    # produces no penalty for missing data.
    fresh_wallet = _first(t, "fwr", "fresh_wallet_rate",
                          "fresh_holder_rate",
                          default=0.0)
    # holder_concentration: top-50 holder share (0-1). Falls back to top-10
    # if GMGN only sends that — Top-50 is the stricter metric, but the
    # penalty curves are calibrated so a 0.55+ reading is the same story
    # either way (top 10 at 0.55% would be unrealistic).
    holder_conc = _first(t, "t50", "top_50_holder_rate",
                         default=max(0.0, t10 / 100.0 * 1.1))
    # clamp t10-derived fallback into 0-1 (it's already a percent, so
    # divide by 100). The +10% bump rewards the user for sending the
    # real top-50 number; if only top-10 is available, we use a
    # slightly harsher version (top-50 ≥ top-10).
    holder_conc = holder_conc if holder_conc <= 1.0 else holder_conc / 100.0
    liq_pct = lq / mc * 100 if mc else 0.0
    vol_mc = vol / mc if mc else 0.0

    raw = 0.0
    notes = []
    wins = []

    # 1. Top-10 concentration (max 30) -------------------------------
    t10_pts = _pillar("t10", t10)
    raw += t10_pts
    if t10_pts >= WEIGHTS["t10"] * 0.9:
        wins.append(f"Top 10 only {t10:.0f}%")

    # 2. Liquidity vs MC (max 30) ------------------------------------
    liq_pts = _pillar("liq", liq_pct)
    raw += liq_pts
    if liq_pts >= WEIGHTS["liq"] * 0.9:
        wins.append(f"deep liq {liq_pct:.0f}% MC")

    # 3. Rug score (max 25) ------------------------------------------
    raw += _pillar("rug", rug)

    # 4. Volume / MC sanity (max 15) --------------------------------
    raw += _pillar("vol", vol_mc)
    if vol_mc > 5:
        notes.append(f"suspicious vol {vol_mc:.1f}x MC")
    elif vol_mc < 0.1:
        notes.append(f"illiquid vol {vol_mc:.2f}x MC")

    raw = min(100.0, raw)

    # ---- Penalties: red flags cost points, they don't just miss them ------
    # Same anchor values as the old if/elif ladders, interpolated in between.
    penalty_f = 0.0
    penalty_f += _curve(insider, PENALTY_CURVES["insider"])
    penalty_f += _curve(bundler, PENALTY_CURVES["bundler"])
    # entrapment = wallets that trap buyers (honeypot-ish behaviour)
    penalty_f += _curve(entrap, PENALTY_CURVES["entrap"])
    # bot-degen dominated flow = fake activity
    penalty_f += _curve(botdeg, PENALTY_CURVES["botdeg"])
    # snipers still sitting on supply
    penalty_f += _curve(sniper, PENALTY_CURVES["sniper"])
    penalty_f += _curve(snipers, PENALTY_CURVES["snipers"])
    penalty_f += _curve(rug, PENALTY_CURVES["rug"])
    penalty_f += _curve(t10, PENALTY_CURVES["t10"])
    penalty_f += _curve(liq_pct, PENALTY_CURVES["liq_thin"])
    # fresh-wallet rate (PR #5 explicit ask) — a mostly-fresh holder base
    # means the token just launched and any "fit" reading is built on
    # noise. Curves anchor so 25% is the first warning, 40%+ clearly
    # hurtful, 55%+ cap-killing.
    penalty_f += _curve(fresh_wallet, PENALTY_CURVES["fresh_wallet"])
    # holder concentration beyond T10 (also from PR #5). The top-50
    # share caps the public float; if insiders + bundles + sniper + T10
    # already own 80%+, retail is the exit liquidity.
    penalty_f += _curve(holder_conc, PENALTY_CURVES["holder_conc"])
    score = max(0.0, raw - penalty_f)
    penalty = penalty_f

    # ---- Gating: a single broken pillar disqualifies the top grades -------
    # Without this a token can coast to PRIME on strong averages while one
    # structural safety pillar is broken.
    #
    # Each gate now has a *transition zone* instead of a bright line: the
    # severity ramps 0→1 between "still fine" and "definitely broken", and
    # the cap slides from PRIME down to FIT_OK-1 in proportion. A token that
    # just grazes a gate keeps most of its score; one that blows through it
    # is clamped exactly as hard as before.
    # Each band is centred on the OLD hard threshold (severity 0.5 sits
    # exactly where the if-statement used to fire) and is wide enough that
    # one percent or a small input change can never move the
    # result by more than a couple of points.
    gates = []          # (severity 0-1, reason)
    gates.append((_sev(t10, 19, 31),
                  f"Top 10 {t10:.0f}% too concentrated"))
    gates.append((_sev(liq_pct, 9.0, 1.0), f"liq only {liq_pct:.1f}% MC"))
    gates.append((_sev(rug, 0.33, 0.57), f"rug score {rug:.2f}"))
    gates.append((_sev(hd, 1600, 400), f"only {hd:,} holders"))
    gates.append((max(_sev(insider, 0.05, 0.15), _sev(bundler, 0.05, 0.15)),
                  "insider/bundler pressure"))
    gates.append((_sev(entrap, 0.22, 0.38),
                  f"entrapment traders {entrap * 100:.0f}%"))
    gates.append((_sev(botdeg, 0.22, 0.38),
                  f"bot-degen flow {botdeg * 100:.0f}%"))

    hit = [(sev, reason) for sev, reason in gates if sev > 0]
    if hit:
        worst = max(sev for sev, _ in hit)
        total = sum(sev for sev, _ in hit)
        # The cap slides along CAP_CURVE: a no-op at severity 0 (so a gate
        # can never appear out of nowhere and knock points off), through
        # "just lost PRIME" at severity 0.5 — which is exactly where the old
        # hard threshold sat — down to FIT_OK - 1 at full severity, the
        # value the old code clamped to. Same verdicts at the anchors,
        # interpolated in between.
        cap_val = _curve(worst, CAP_CURVE)
        # Extra flaws and accrued penalty push the cap down further, each
        # weighted by severity so they too fade in smoothly.
        cap_val -= 3.0 * (total - worst)
        cap_val -= min(12.0, penalty_f / 2.0) * min(1.0, total)
        cap_val = max(0.0, cap_val)
        if score > cap_val:
            score = cap_val
        # Only *name* the gates that are meaningfully broken, so the notes
        # column doesn't fill up with "0.02 over the line" noise.
        notes.extend(reason for sev, reason in hit
                     if sev >= 0.5 and reason not in notes)
    score = max(0.0, min(100.0, score))

    # ---- Hard risk flags ---------------------------------------------------
    risk_reasons = []
    if rug > 0.60:
        risk_reasons.append(f"High rug score ({rug:.2f})")
    if t10 > 35:
        risk_reasons.append(f"Very concentrated (Top 10 {t10:.0f}%)")
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
    # Fresh-wallet rate above 50% means the holder base is almost entirely
    # brand-new accounts. Real accumulation needs aged wallets; without
    # them every "good" pillar reading is built on a launch-day mirage.
    if fresh_wallet > 0.50:
        risk_reasons.append(
            f"Fresh-wallet base {fresh_wallet * 100:.0f}% "
            "(mostly brand-new holders)")
    # Top-50 share above 85% means there is basically no public float
    # left to absorb any buying — AVOID regardless of other pillars.
    if holder_conc > 0.85:
        risk_reasons.append(
            f"Top-50 hold {holder_conc * 100:.0f}% of supply (no float)")
    high_risk = bool(risk_reasons)
    if high_risk:
        score = min(score, float(HIGH_RISK_CAP))
    fit = int(round(score))

    return {
        "ca": t.get("a") or t.get("address"),
        "symbol": t.get("s") or t.get("symbol"),
        "name": t.get("nm") or t.get("name"),
        "mc": mc, "liq": lq, "liq_pct": round(liq_pct, 1),
        "vol24": vol, "vol_mc": round(vol_mc, 2),
        "holders": hd, "t10_pct": round(t10, 1),
        "rug": round(rug, 2), "age_d": round(age_d, 1),
        "chg24": round(chg24, 1), "chg1h": round(chg1h, 1),
        "fit": fit, "penalty": int(round(penalty)),
        # unrounded score — lets the UI sort/rank tokens that land on the
        # same displayed integer, which the ramps make far more common
        "fit_exact": round(score, 2),
        "grade": fit_grade(fit, high_risk),
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
        "fresh_wallet_rate": round(fresh_wallet, 4),
        "holder_conc": round(holder_conc, 4),
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
    rows.sort(key=lambda row: (
        -row.get("fit_exact", row["fit"]), row["t10_pct"],
        -row["liq_pct"]))
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


# ---------------------------------------------------------------------------
# High Risk High Reward (HRHR) Screening
# ---------------------------------------------------------------------------
HRHR_FILTER_BODY = {
    "meta": {},
    "params": [{
        "chain": "sol",
        "interval": "24h",
        "filter": {
            "filters": ["migrated", "not_wash_trading", "renounced",
                        "frozen"],
            "min_created": "2880m",   # min age 2d
            "max_created": "86400m",  # max age 60d
            "max_marketcap": 250000,  # mc max 250k
            "min_holder_count": 1000, # holder min 1000
            "min_gas_fee": 30,        # total fees min 30 SOL
            "min_volume_24h": 10000,  # 24h volume min 10k
        },
    }],
}


def _get_avg_cost_and_ath(t):
    """Parse average cost change % and down % from ATH from GMGN token metadata.

    Provides robust fallbacks to guarantee the UI remains functional.
    Fallbacks are deterministic (not random) so the same token always
    gets the same score across runs.
    """
    # Average cost change % (minimal -50% means holders are down at least -50% on average, e.g. -65%)
    avg_cost_change = t.get("avg_cost_change") or t.get("holder_avg_cost_change") or t.get("avg_cost_pct")
    if avg_cost_change is None:
        # Deterministic fallback for HRHR micro-caps: assume -65% (typical)
        avg_cost_change = -65.0
    else:
        avg_cost_change = float(avg_cost_change)

    # Down % from ATH
    down_from_ath = t.get("down_from_ath") or t.get("down_pct_from_ath") or t.get("ath_down_pct")
    if down_from_ath is None:
        price = _first(t, "p", "price", default=0.0)
        ath = _first(t, "ath", "highest_price", "highestPrice", default=0.0)
        if ath > 0 and price > 0:
            down_from_ath = ((ath - price) / ath) * 100.0
        else:
            # Deterministic fallback: assume -90% (typical for HRHR)
            down_from_ath = 90.0
    else:
        down_from_ath = float(down_from_ath)

    return avg_cost_change, down_from_ath


def fetch_hrhr(timeout=25, debug=False):
    """Fetch raw token dicts from GMGN HRHR list."""
    try:
        from curl_cffi import requests as cr
    except ImportError:
        if debug:
            print("curl_cffi not installed")
        return []

    last = ""
    for imp in ("chrome", "chrome131", "safari17_0"):
        try:
            r = cr.post(_trending_url(), impersonate=imp, timeout=timeout,
                        headers=HEADERS, data=json.dumps(HRHR_FILTER_BODY))
        except Exception as exc:                        # noqa: BLE001
            last = f"{imp}: {type(exc).__name__}: {exc}"
            continue
        if r.status_code != 200:
            last = f"{imp}: HTTP {r.status_code}"
            continue
        try:
            data = r.json()
        except Exception:
            last = f"{imp}: non-JSON reply"
            continue
        if data.get("code") not in (0, None):
            last = f"{imp}: api code={data.get('code')}"
            continue
        blocks = data.get("data") or []
        if isinstance(blocks, dict):
            blocks = [blocks]
        toks = []
        for b in blocks:
            toks.extend((b or {}).get("tokens") or [])
        if toks:
            return toks
        last = f"{imp}: 200 OK but 0 tokens"
    if debug and last:
        print("GMGN HRHR fetch failed —", last)
    return []


def screen_hrhr():
    """Fetch + score + filter for HRHR criteria + sort. Returns list of rows."""
    rows, seen = [], set()
    tokens = fetch_hrhr()
    if not tokens:
        # fallback using fetch_trending if fetch_hrhr returns empty (Cloudflare blocks etc)
        tokens = fetch_trending()
        
    for t in tokens:
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

        avg_cost, down_ath = _get_avg_cost_and_ath(t)
        if avg_cost is not None and avg_cost > -50.0:
            # Skip if holder average cost is not down at least 50%
            continue

        row["avg_cost"] = avg_cost
        row["down_ath"] = down_ath

        # Add ATH information to the notes
        ath_note = f"Down {down_ath:.1f}% dari ATH"
        if down_ath >= 90.0:
            row["notes"] = f"🟢 {ath_note}; " + (row.get("notes") or "")
        else:
            row["notes"] = f"{ath_note}; " + (row.get("notes") or "")

        rows.append(row)

    rows.sort(key=lambda row: (
        -row.get("fit_exact", row["fit"]), row["t10_pct"],
        -row["liq_pct"]))
    return rows


if __name__ == "__main__":
    print("build tag:", _build_tag())
    raw = fetch_trending(debug=True)
    print("raw tokens:", len(raw))
    rows = sorted((score_token(t) for t in raw if isinstance(t, dict)),
                  key=lambda r: -r.get("fit_exact", r["fit"]))
    if not rows:
        print("Nothing returned — see docs/gmgn_api.md for what to re-check.")
    for r in rows:
        print(str(r["fit"]).rjust(3), (r["grade"] or "").ljust(6),
              (r["symbol"] or "?").ljust(10),
              "MC $" + format(r["mc"], ",.0f"),
              "| Top 10 " + str(r["t10_pct"]) + "%",
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
