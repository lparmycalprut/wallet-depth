'''Multi-Tier On-Chain Pre-Pump Radar (multi-factor, 0-100 score).

Network-free evaluation of recent swap flow (cvd tuples (side, sol, ts, wallet)).
Shared by the dashboard, the hourly cron, and the unit tests.

Pipeline:
  1. Pre-processing: drop MEV / sandwich-bot trades.
  2. Baseline normalization: prior-hours volume -> per-hour baseline.
  3. Four 25-point pillars:
       P1 Volume Compression & Seller Exhaustion
       P2 Order-Flow Size Asymmetry (MEV-cleaned)
       P3 Pure Accumulator & Holding Conviction
       P4 Order-Flow Delta & Terminal Ignition
  4. Score >= 75 -> PRE-PUMP IMMINENT (Tier 1, Telegram)
             55-74 -> PRE-PUMP FORMING     (Tier 2, gated by focus_mode)
             < 55  -> neutral / noise

Multi-timeframe (evaluate_prepump_multi_tf):
  30m (Micro Ignition / Timing) · 1h (Hourly Setup / Base) ·
  4h (Swing Channel / Wyckoff Accumulation) · 12h (Macro Cycle Base)
  plus a CONFLUENCE verdict:
    🌟 GOLDEN CONFLUENCE   (macro 4h/12h >= 60 AND micro 30m/1h >= 75)
    🪤 DEAD CAT / FAKE BOUNCE (micro 30m >= 70 BUT macro 4h/12h < 35)
    ⏳ ACCUMULATION SLEEPER (macro 4h/12h >= 65 BUT micro 30m < 40)
    ➖ NORMAL / FORMING    (everything else)
'''
import time

from cvd import wallet_profiles

# Smart-money tags that count for pure-accumulator conviction (pillar 3).
PREPUMP_SMART_TAGS = {'bluechip_owner', 'axiom', 'top_holder', 'padre',
                      'fresh_wallet'}
# Bot/terminal tags whose appearance signals ignition (pillar 4).
PREPUMP_TERMINAL_TAGS = {'axiom', 'trojan', 'padre', 'photon', 'bundler'}
# Bundlers are excluded from the smart-money count.
PREPUMP_BUNDLER_TAGS = {'bundler', 'sandwich_bot'}
# Same (ca, type) Telegram alert at most once per this many seconds.
PREPUMP_DEDUPE_SEC = 3 * 3600

# Tier badge used everywhere (UI matrix, Telegram, digest pills).
PREPUMP_TIER_BADGES = {'imminent': '🚨', 'forming': '👀',
                       'neutral': '➖', 'blocked': '🚫'}

# ---------------------------------------------------------------------------
# Multi-timeframe configuration.
#
# Every timeframe reuses the exact same 4-pillar math as the legacy 30m
# evaluation; only the windowing / gates scale. The 30m entry reproduces the
# legacy defaults 1:1 (sub-window 15m, terminal 10m, min_buy 3, large dump
# 1 SOL, absorption multiplier x1) so existing calibration does NOT drift.
# ---------------------------------------------------------------------------
PREPUMP_TF_CONFIGS = {
    '30m': {
        'window_min': 30, 'prior_hours': 4, 'sub_window_min': 15,
        'terminal_min': 10, 'min_buy': 3, 'large_dump_sol': 1.0,
        'absorp_mult': 1.0, 'role': 'Micro Ignition / Timing',
    },
    '1h': {
        'window_min': 60, 'prior_hours': 8, 'sub_window_min': 30,
        'terminal_min': 20, 'min_buy': 5, 'large_dump_sol': 2.0,
        'absorp_mult': 2.0, 'role': 'Hourly Setup / Base',
    },
    '4h': {
        'window_min': 240, 'prior_hours': 24, 'sub_window_min': 120,
        'terminal_min': 60, 'min_buy': 12, 'large_dump_sol': 5.0,
        'absorp_mult': 6.0, 'role': 'Swing Channel / Wyckoff Accumulation',
    },
    '12h': {
        'window_min': 720, 'prior_hours': 48, 'sub_window_min': 360,
        'terminal_min': 180, 'min_buy': 25, 'large_dump_sol': 10.0,
        'absorp_mult': 12.0, 'role': 'Macro Cycle Base',
    },
}
PREPUMP_TF_ORDER = ('30m', '1h', '4h', '12h')
PREPUMP_TF_MACRO = ('4h', '12h')
PREPUMP_TF_MICRO = ('30m', '1h')

# Confluence thresholds (scores out of 100).
CONFLUENCE_GOLDEN_MACRO_MIN = 60.0   # macro (best of 4h/12h)
CONFLUENCE_GOLDEN_MICRO_MIN = 75.0   # micro (best of 30m/1h)
CONFLUENCE_DEADCAT_MACRO_MAX = 35.0  # macro below this = weak
CONFLUENCE_DEADCAT_MICRO_MIN = 70.0  # 30m "high" bounce threshold
CONFLUENCE_SLEEPER_MACRO_MIN = 65.0  # macro quietly forming
CONFLUENCE_SLEEPER_MICRO30_MAX = 40.0  # 30m still asleep

#: Confluence status -> (emoji, label, short description). Ordered by
#: precedence; compute_confluence returns the FIRST matching status.
PREPUMP_CONFLUENCE_STYLES = {
    'golden': ('🌟', 'GOLDEN CONFLUENCE', 'Macro Accum + Micro Ignition'),
    'dead_cat': ('🪤', 'DEAD CAT / FAKE BOUNCE', 'Micro spike, macro weak'),
    'sleeper': ('⏳', 'ACCUMULATION SLEEPER', 'Macro forming, micro quiet'),
    'normal': ('➖', 'NORMAL / FORMING', 'No cross-TF alignment'),
}


def _r(v, n=2):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return 0.0


def _fmt(v):
    if v is None:
        return '-'
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return '-'
    if fv >= 1:
        return '{:,.2f}'.format(fv)
    return '{:.8f}'.format(fv).rstrip('0').rstrip('.')


def _is_sandwich(wallet_swaps, wallet_tags):
    '''True if a wallet is a sandwich bot or did a buy+sell within 2s at
    near-equal size (+-2%).'''
    meta = (wallet_tags or {}).get(wallet_swaps[0][3]) if wallet_swaps else {}
    tags = set()
    if isinstance(meta, dict):
        tags.update(meta.get('maker_tags', []) or [])
        tags.update(meta.get('maker_token_tags', []) or [])
    if PREPUMP_BUNDLER_TAGS & tags:
        return True
    buys = sorted((int(s[2]), float(s[1])) for s in wallet_swaps
                  if s[0] == 'buy')
    sells = sorted((int(s[2]), float(s[1])) for s in wallet_swaps
                   if s[0] == 'sell')
    for bt, bv in buys:
        for st, sv in sells:
            if abs(bt - st) <= 2 and abs(bv - sv) <= 0.02 * max(bv, sv, 1e-9):
                return True
    return False


def _clean_swaps(swaps, wallet_tags, pool_sol=None):
    '''Drop sandwich-bot / MEV-arbitrage swaps and cap absurd swap sizes
    (GMGN quote bugs / MEV skew) at min(500 SOL, 0.10 * pool_sol).'''
    sol_cap = min(500.0, 0.10 * float(pool_sol)) if pool_sol else 500.0
    by_wallet = {}
    for s in (swaps or []):
        if len(s) < 4:
            continue
        s = list(s)
        if abs(float(s[1])) > sol_cap:
            s[1] = sol_cap if float(s[1]) > 0 else -sol_cap
        by_wallet.setdefault(s[3], []).append(tuple(s))
    out = []
    for w, ws in by_wallet.items():
        if _is_sandwich(ws, wallet_tags):
            continue
        out.extend(ws)
    return out


def _min_absorp(mc):
    '''Adaptive liquidity tier: minimum pure-accumulation SOL to count.

    Low-cap (<$50k): 3 SOL · Mid-cap ($50k-$500k): 10 SOL ·
    High-cap (>$500k): 25 SOL. None -> 0 (no tier gate; used in tests).
    '''
    if mc is None:
        return 0.0
    if mc < 50000:
        return 3.0
    if mc <= 500000:
        return 10.0
    return 25.0


def _safety_check(ti):
    '''Fast-fail gates (Rug / Markup distance / Liquidity sanity).

    Only blocks when the relevant data is present; missing data => pass,
    so offline tests and the backtest (no safety fields) are unaffected.
    Returns (blocked: bool, reason: str).
    '''
    if not ti:
        return False, ''
    if ti.get('rug_risky'):
        return True, 'rug/safety risk flagged'
    mu = ti.get('markup_24h_pct')
    if mu is not None and mu >= 80.0:
        return True, 'price already +%s%% (24h)' % round(mu)
    tx24 = ti.get('tx24')
    if tx24 is not None and tx24 < 1000:
        return True, '24h tx %s < 1000' % tx24
    v24 = ti.get('vol24_usd')
    if v24 is not None and v24 < 20000.0:
        return True, '24h vol $%s < $20k' % _r(v24)
    return False, ''


def evaluate_prepump(swaps, token_info=None, *, ca=None, now_ts=None,
                     window_min=30, prior_hours=4, whale_min_sol=3.0,
                     smart_tags=None, wallet_tags=None, bullish_div=False,
                     pool_sol=None, sub_window_min=None, terminal_min=None,
                     min_buy=None, large_dump_sol=None, absorp_mult=1.0,
                     bullish_div_h4=False, tf=None):
    '''Score the last ``window_min`` minutes for a pre-pump setup.

    Args:
        swaps: iterable of (side, sol, ts, wallet) cvd tuples.
        token_info: optional {symbol, price_usd, mc, vol_24h} for messaging.
        ca, now_ts, window_min, prior_hours: windowing (default 30m / 4h).
        whale_min_sol: large-sell threshold reference.
        wallet_tags: {wallet: {maker_tags:[...], maker_token_tags:[...]}}.
        bullish_div: True if bullish divergence on whale CVD H1.
        pool_sol: pool SOL reserves (enables the 0.5%-of-pool sell filter).
        sub_window_min: "fresh flow" sub-window (default window_min/2;
            legacy 30m default = 15m).
        terminal_min: ignition window for terminal-bot activity (default
            window_min/3; legacy 30m default = 10m).
        min_buy: minimum organic buys before any score counts (default 3).
        large_dump_sol: large-sell threshold reference (default 1 SOL).
        absorp_mult: multiplier on the low/mid/high-cap pure-accumulation
            SOL target (default 1.0; bigger TFs require bigger absorption).
        bullish_div_h4: True if bullish divergence on whale CVD H4.
        tf: optional timeframe label ('30m', '1h', '4h', '12h') attached to
            the result for multi-TF consumers.

    The defaults reproduce the legacy 30m calibration exactly; the
    multi-timeframe wrapper (evaluate_prepump_multi_tf) passes explicit
    values from PREPUMP_TF_CONFIGS.

    Returns a dict with score, tier, per-pillar points, and metric details.
    '''
    now_ts = int(now_ts if now_ts is not None else time.time())
    ti = token_info or {}
    window_min = int(window_min)
    sub_window_min = int(sub_window_min) if sub_window_min \
        else max(5, window_min // 2)
    terminal_min = int(terminal_min) if terminal_min \
        else max(5, window_min // 3)
    min_buy = int(min_buy) if min_buy else 3
    large_dump_sol = float(large_dump_sol) if large_dump_sol else 1.0
    absorp_mult = float(absorp_mult) if absorp_mult else 1.0
    if tf is None:
        tf = {30: '30m', 60: '1h', 240: '4h', 720: '12h'}.get(
            window_min, '%dm' % window_min)
    blocked, block_reason = _safety_check(ti)
    if blocked:
        return {
            'ca': ca, 'score': 0.0, 'tier': 'blocked', 'tf': tf,
            'window_min': window_min, 'bullish_div': bool(bullish_div),
            'compression_pct': 0.0, 'blocked': True,
            'block_reason': block_reason,
            'metrics': {'buy_vol': 0.0, 'sell_vol': 0.0, 'net_sol': 0.0,
                        'net_sub_sol': 0.0,
                        'avg_buy': 0.0, 'avg_sell': 0.0, 'ratio': 0.0,
                        'buy_count': 0, 'sell_count': 0, 'n_pure': 0,
                        'pct_pure': 0.0, 'smart_count': 0, 'smart_zero': 0,
                        'vol_15m': 0.0, 'vol_30m': 0.0,
                        'vol_sub_window': 0.0, 'vol_window': 0.0,
                        'sub_window_min': sub_window_min,
                        'terminal_min': terminal_min, 'min_buy': min_buy,
                        'large_dump_sol': large_dump_sol,
                        'absorp_mult': _r(absorp_mult),
                        'absorp_target_sol': 0.0,
                        'baseline_vol_1h': 0.0, 'active_terminals': [],
                        'whale_dumper': False},
            'smart_tags_found': [], 'stage': 'BLOCKED: ' + block_reason,
            'pillars': {'compression': 0.0, 'asymmetry': 0.0,
                        'accum': 0.0, 'delta': 0.0},
            'reasons': {'compression': block_reason, 'asymmetry': '',
                        'accum': '', 'delta': ''},
            'token_info': ti,
        }
    win_start = now_ts - window_min * 60
    prior_start = now_ts - int(prior_hours) * 3600
    sub_start = now_ts - sub_window_min * 60

    cleaned = _clean_swaps(swaps, wallet_tags, pool_sol)
    recent = [s for s in cleaned
              if win_start <= int(s[2]) <= now_ts]
    prior = [s for s in cleaned
             if prior_start <= int(s[2]) < win_start]

    def _vol(subset):
        return sum(float(s[1]) for s in subset)

    vol_window = _vol(recent)
    vol_sub = _vol([s for s in recent if int(s[2]) >= sub_start])
    baseline_vol_1h = (_vol(prior) / max(1e-9, int(prior_hours))) \
        if prior else 0.0

    # ---- Pillar 1: Volume Compression & Seller Exhaustion (25) ----------
    # Sub-window volume vs the per-hour prior baseline. Thresholds scale
    # linearly with the sub-window length so the *pace* semantics of the
    # legacy 15m check stay identical on every timeframe.
    sub_ref = sub_window_min / 15.0           # 1.0 on the legacy 30m eval
    sub_hours = sub_window_min / 60.0
    p1 = 0.0
    compression_pct = 0.0
    if baseline_vol_1h > 0 and vol_sub < 0.35 * baseline_vol_1h * sub_ref:
        p1 += 15.0
        compression_pct = max(
            0.0, (1 - vol_sub / (baseline_vol_1h * sub_hours)) * 100.0)
    elif baseline_vol_1h <= 0 and vol_sub <= 1.0 * sub_ref:
        p1 += 15.0
        compression_pct = 100.0 if vol_sub <= 0.01 else 0.0
    # Timeframe-adjusted large-dump gate (1 SOL @30m .. 10 SOL @12h),
    # still floored to 0.5% of pool depth when pool data is available.
    large_sell_thr = (max(large_dump_sol, 0.005 * float(pool_sol))
                      if pool_sol else large_dump_sol)
    large_sell = any(s[0] == 'sell' and float(s[1]) >= large_sell_thr
                     for s in recent)
    if not large_sell:
        p1 += 10.0
    p1 = min(25.0, p1)
    p1r = 'vol%dm %.2f vs baseline1h %.2f; large-sell(>=%s SOL)=%s' % (
        sub_window_min, vol_sub, baseline_vol_1h, _r(large_sell_thr),
        bool(large_sell))

    # ---- Pillar 2: Order-Flow Size Asymmetry (25) ---------------------
    buy_swaps = [s for s in recent if s[0] == 'buy']
    sell_swaps = [s for s in recent if s[0] == 'sell']
    buy_count = len(buy_swaps)
    buy_vol = _vol(buy_swaps)
    sell_vol = _vol(sell_swaps)
    avg_buy = buy_vol / buy_count if buy_count else 0.0
    avg_sell = sell_vol / sell_count if (sell_count := len(sell_swaps)) else 0.0
    ratio = avg_buy / max(avg_sell, 0.01)
    if buy_count >= min_buy:
        if ratio >= 3.0:
            p2 = 25.0
        elif ratio >= 2.0:
            p2 = 15.0
        else:
            p2 = 0.0
    else:
        p2 = 0.0
    p2r = 'avg buy %.2f vs sell %.2f (%sx), %d buys (min %d)' % (
        avg_buy, avg_sell, _r(ratio), buy_count, min_buy)

    # ---- Pillar 3: Pure Accumulator & Holding Conviction (25) --------
    profiles = wallet_profiles(recent)
    pure_buy_vol = sum(float(d.get('buy') or 0.0) for d in profiles.values()
                       if d.get('profile') == 'pure_accum')
    n_pure = sum(1 for d in profiles.values()
                 if d.get('profile') == 'pure_accum')
    pct_pure = (pure_buy_vol / buy_vol) if buy_vol > 0 else 0.0
    # per-wallet sell sums (from cleaned recent) for zero-sell check
    wallet_sell = {}
    for s in sell_swaps:
        wallet_sell[s[3]] = wallet_sell.get(s[3], 0.0) + float(s[1])
    smart_zero = 0
    smart_tags_found = []
    for w, meta in (wallet_tags or {}).items():
        tags = set()
        if isinstance(meta, dict):
            tags.update(meta.get('maker_tags', []) or [])
            tags.update(meta.get('maker_token_tags', []) or [])
        if tags & PREPUMP_SMART_TAGS and not (tags & PREPUMP_BUNDLER_TAGS):
            if wallet_sell.get(w, 0.0) <= 0:
                smart_zero += 1
            for t in tags & PREPUMP_SMART_TAGS:
                if t not in smart_tags_found:
                    smart_tags_found.append(t)
    # Tiered SOL absorption target: (low/mid/high cap) x timeframe mult.
    _min_abs = _min_absorp(ti.get('mc')) * absorp_mult
    p3 = 0.0
    if pct_pure >= 0.6:
        p3 += 15.0 * (min(1.0, pure_buy_vol / _min_abs) if _min_abs > 0
                      else 1.0)
    if smart_zero >= 2:
        p3 += 10.0
    p3 = min(25.0, p3)
    p3r = 'pure_accum %.0f%% of buy vol (target %s SOL); %d smart 0-sell' % (
        pct_pure * 100, _r(_min_abs), smart_zero)

    # ---- Pillar 4: Order-Flow Delta & Terminal Ignition (25) ---------
    net_sol = buy_vol - sell_vol
    net_sub = (_vol([s for s in buy_swaps if int(s[2]) >= sub_start])
               - _vol([s for s in sell_swaps if int(s[2]) >= sub_start]))
    p4 = 0.0
    if net_sub > 0 and net_sol > 0:
        p4 += 10.0
    if bullish_div:
        p4 += 10.0
    if bullish_div_h4:
        p4 += 10.0
    # ignition: terminal-tagged wallets active in the last terminal_min min
    active_terminals = []
    if wallet_tags:
        for w, meta in (wallet_tags or {}).items():
            tags = set()
            if isinstance(meta, dict):
                tags.update(meta.get('maker_tags', []) or [])
                tags.update(meta.get('maker_token_tags', []) or [])
            if tags & PREPUMP_TERMINAL_TAGS:
                if any(int(s[2]) >= now_ts - terminal_min * 60 and s[3] == w
                       for s in recent):
                    for t in tags & PREPUMP_TERMINAL_TAGS:
                        if t not in active_terminals:
                            active_terminals.append(t)
    if active_terminals:
        p4 += 5.0
    p4 = min(25.0, p4)
    p4r = 'net%dm %s net%dm %s; divH1=%s divH4=%s; terminals=%s' % (
        sub_window_min, _r(net_sub), window_min, _r(net_sol),
        bool(bullish_div), bool(bullish_div_h4),
        ','.join(active_terminals) or '-')

    score = max(0.0, p1 + p2 + p3 + p4)
    if buy_count < min_buy:
        score = 0.0  # need a minimum of organic buys
    score = round(score, 1)
    tier = ('imminent' if score >= 75 else
            'forming' if score >= 55 else 'neutral')

    if active_terminals and compression_pct >= 50:
        stage = 'Compression Completed -> Smart Buying Detected'
    elif bullish_div or bullish_div_h4:
        stage = 'Bullish Divergence -> Accumulation Confirmed'
    else:
        stage = 'Accumulation Building'

    return {
        'ca': ca,
        'score': score,
        'tier': tier,
        'tf': tf,
        'window_min': window_min,
        'bullish_div': bool(bullish_div),
        'bullish_div_h4': bool(bullish_div_h4),
        'compression_pct': round(compression_pct, 1),
        'metrics': {
            'buy_vol': _r(buy_vol), 'sell_vol': _r(sell_vol),
            'net_sol': _r(net_sol), 'net_sub_sol': _r(net_sub),
            'avg_buy': _r(avg_buy),
            'avg_sell': _r(avg_sell), 'ratio': _r(ratio),
            'buy_count': buy_count, 'sell_count': sell_count,
            'n_pure': n_pure, 'pct_pure': round(pct_pure, 4),
            'smart_count': smart_zero, 'smart_zero': smart_zero,
            # Legacy keys (30m naming) kept for backward compatibility.
            'vol_15m': _r(vol_sub), 'vol_30m': _r(vol_window),
            # Explicit multi-timeframe keys.
            'vol_sub_window': _r(vol_sub), 'vol_window': _r(vol_window),
            'sub_window_min': sub_window_min,
            'terminal_min': terminal_min, 'min_buy': min_buy,
            'large_dump_sol': _r(large_dump_sol),
            'absorp_mult': _r(absorp_mult),
            'absorp_target_sol': _r(_min_abs),
            'baseline_vol_1h': _r(baseline_vol_1h),
            'active_terminals': active_terminals,
            'whale_dumper': bool(large_sell),
        },
        'smart_tags_found': smart_tags_found,
        'stage': stage,
        'pillars': {
            'compression': round(p1, 1),
            'asymmetry': round(p2, 1),
            'accum': round(p3, 1),
            'delta': round(p4, 1),
        },
        'reasons': {
            'compression': p1r, 'asymmetry': p2r,
            'accum': p3r, 'delta': p4r,
        },
        'token_info': token_info or {},
    }


# ---------------------------------------------------------------------------
# Multi-timeframe evaluation + confluence
# ---------------------------------------------------------------------------
def compute_confluence(scores):
    '''Cross-timeframe confluence from a {tf: score} mapping.

    Returns {'status', 'emoji', 'label', 'desc', 'macro_score',
    'micro_score'}. Precedence: golden > dead_cat > sleeper > normal.
    '''
    scores = scores or {}
    macro = max(float(scores.get(tf, 0.0) or 0.0) for tf in PREPUMP_TF_MACRO)
    micro = max(float(scores.get(tf, 0.0) or 0.0) for tf in PREPUMP_TF_MICRO)
    micro_30 = float(scores.get('30m', 0.0) or 0.0)
    if macro >= CONFLUENCE_GOLDEN_MACRO_MIN \
            and micro >= CONFLUENCE_GOLDEN_MICRO_MIN:
        status = 'golden'
    elif micro_30 >= CONFLUENCE_DEADCAT_MICRO_MIN \
            and macro < CONFLUENCE_DEADCAT_MACRO_MAX:
        status = 'dead_cat'
    elif macro >= CONFLUENCE_SLEEPER_MACRO_MIN \
            and micro_30 < CONFLUENCE_SLEEPER_MICRO30_MAX:
        status = 'sleeper'
    else:
        status = 'normal'
    emoji, label, desc = PREPUMP_CONFLUENCE_STYLES[status]
    return {'status': status, 'emoji': emoji, 'label': label, 'desc': desc,
            'macro_score': round(macro, 1), 'micro_score': round(micro, 1)}


def evaluate_prepump_multi_tf(swaps, token_info=None, *, ca=None, now_ts=None,
                              wallet_tags=None, whale_min_sol=3.0,
                              bullish_div_h1=False, bullish_div_h4=False,
                              pool_sol=None, tfs=None):
    '''Evaluate the pre-pump radar on every timeframe in ``tfs``.

    All four evaluations share the same (already-cleaned) swap list and
    reference timestamp so the matrix is internally consistent. Returns::

        {'ca', 'evaluated_at', 'primary_tf', 'best_tf', 'timeframes',
         'scores', 'confluence', 'overall_score', 'overall_tier',
         'token_info'}

    ``timeframes[tf]`` is the full evaluate_prepump result for that
    timeframe (with ``tf_role`` from PREPUMP_TF_CONFIGS). The 30m result is
    the "primary" (timing) row so legacy consumers (signals.json, state
    files) keep their meaning.
    '''
    now_ts = int(now_ts if now_ts is not None else time.time())
    tfs = tuple(tfs) if tfs else PREPUMP_TF_ORDER
    results = {}
    for tf in tfs:
        cfg = PREPUMP_TF_CONFIGS[tf]
        r = evaluate_prepump(
            swaps, token_info, ca=ca, now_ts=now_ts,
            window_min=cfg['window_min'], prior_hours=cfg['prior_hours'],
            whale_min_sol=whale_min_sol, wallet_tags=wallet_tags,
            bullish_div=bullish_div_h1, bullish_div_h4=bullish_div_h4,
            pool_sol=pool_sol,
            sub_window_min=cfg['sub_window_min'],
            terminal_min=cfg['terminal_min'],
            min_buy=cfg['min_buy'],
            large_dump_sol=cfg['large_dump_sol'],
            absorp_mult=cfg['absorp_mult'], tf=tf)
        r['tf_role'] = cfg['role']
        results[tf] = r
    scores = {tf: r.get('score', 0.0) for tf, r in results.items()}
    confluence = compute_confluence(scores)
    primary_tf = '30m' if '30m' in results else tfs[0]
    primary = results[primary_tf]
    best_tf = max(results, key=lambda t: results[t].get('score', 0.0))
    return {
        'ca': ca,
        'evaluated_at': now_ts,
        'primary_tf': primary_tf,
        'best_tf': best_tf,
        'timeframes': results,
        'scores': scores,
        'confluence': confluence,
        'overall_score': primary.get('score', 0.0),
        'overall_tier': primary.get('tier', 'neutral'),
        'token_info': token_info or {},
    }


def _score_txt(v):
    ''''100' instead of '100.0', '78.5' otherwise.'''
    s = '%s' % _r(v, 1)
    return s[:-2] if s.endswith('.0') else s


def format_multi_tf_line(multi):
    '''Compact multi-timeframe score row for Telegram, e.g.
    "📊 Multi-TF: [30m: 90/100 🚨 | 1h: 78/100 🚨 | 4h: 65/100 👀 | 12h: 58/100 👀]".
    Returns '' when no timeframe data is present.'''
    tfr = (multi or {}).get('timeframes') or {}
    parts = []
    for tf in PREPUMP_TF_ORDER:
        r = tfr.get(tf)
        if not r:
            continue
        badge = PREPUMP_TIER_BADGES.get(r.get('tier'), '❓')
        parts.append('%s: %s/100 %s' % (tf, _score_txt(r.get('score', 0)),
                                        badge))
    if not parts:
        return ''
    return '📊 <b>Multi-TF:</b> [%s]' % ' | '.join(parts)


def format_confluence_line(confluence):
    '''"🎯 Confluence: 🌟 GOLDEN CONFLUENCE (Macro Accum + Micro Ignition)"
    plus the underlying macro/micro scores. Returns '' when empty.'''
    conf = confluence or {}
    if not conf.get('label'):
        return ''
    return ('🎯 <b>Confluence:</b> %s <b>%s</b> (%s) · macro %s/100 · micro '
            '%s/100' % (conf.get('emoji', '➖'), conf['label'],
                        conf.get('desc', ''),
                        _score_txt(conf.get('macro_score', 0)),
                        _score_txt(conf.get('micro_score', 0))))


def format_prepump_digest_pill(multi):
    '''Ultra-compact per-token pill for the periodic digest, e.g.
    "[30m:90🚨 1h:78🚨 4h:65👀 12h:58👀]". Returns '' when empty.'''
    tfr = (multi or {}).get('timeframes') or {}
    parts = []
    for tf in PREPUMP_TF_ORDER:
        r = tfr.get(tf)
        if not r:
            continue
        parts.append('%s:%s%s' % (tf, _score_txt(r.get('score', 0)),
                                  PREPUMP_TIER_BADGES.get(r.get('tier'), '❓')))
    return '[%s]' % ' '.join(parts) if parts else ''


def format_prepump_telegram(result, ca, token_info=None, multi=None):
    '''Render an HTML Telegram message for a pre-pump result.

    When ``multi`` (an evaluate_prepump_multi_tf result) is given — or the
    result itself carries a 'multi_tf' entry — the message also shows the
    multi-timeframe score row and the confluence verdict.
    '''
    NL = chr(10)
    if multi is None:
        multi = result.get('multi_tf')
    m = result.get('metrics', {})
    ti = token_info or result.get('token_info') or {}
    sym = ti.get('symbol') or '?'
    badge = PREPUMP_TIER_BADGES.get(result.get('tier'), '👀')
    title = ('PRE-PUMP IMMINENT' if result.get('tier') == 'imminent'
             else 'PRE-PUMP FORMING')
    tf_label = result.get('tf') or '%dm' % result.get('window_min', 30)
    win_label = '%dm' % result.get('window_min', 30)
    sub_label = '%dm' % m.get('sub_window_min', 15)
    if multi and multi.get('primary_tf'):
        tf_label = multi['primary_tf']
        _prim = (multi.get('timeframes') or {}).get(tf_label) or {}
        win_label = '%dm' % _prim.get('window_min', 30)
        sub_label = '%dm' % (_prim.get('metrics', {}).get('sub_window_min', 15))
    terms = ', '.join(m.get('active_terminals', [])) or \
        'axiom, trojan, bluechip_owner'
    net_sol = m.get('net_sol', 0)
    lines = [
        '%s <b>%s: $%s</b>' % (badge, title, sym),
        '<i>smart-money absorption · seller exhaustion · ignition trigger</i>',
        '',
        '📊 <b>Pre-Pump Score (%s):</b> <b>%s/100</b> %s'
        % (tf_label, _score_txt(result['score']), badge),
        '💰 <b>Price:</b> $%s | <b>MC:</b> $%s | <b>Liq:</b> $%s'
        % (_fmt(ti.get('price_usd')), _fmt(ti.get('mc')),
           _fmt(ti.get('liquidity'))),
    ]
    mtf_line = format_multi_tf_line(multi)
    if mtf_line:
        lines.append(mtf_line)
        conf_line = format_confluence_line((multi or {}).get('confluence'))
        if conf_line:
            lines.append(conf_line)
    lines += [
        '',
        '🔍 <b>On-Chain Signatures (%s):</b>' % win_label,
        '• <b>Seller State:</b> 🟢 Exhausted (vol compression -%s%% vs prior avg)'
        % round(result.get('compression_pct', 0)),
        '• <b>Order Asymmetry:</b> Avg Buy <b>%s SOL</b> vs Avg Sell <b>%s SOL</b> (%sx)'
        % (_r(m.get('avg_buy', 0)), _r(m.get('avg_sell', 0)), _r(m.get('ratio', 0))),
        '• <b>Order Flow (%s):</b> Net <b>%s%s SOL</b> (Buys: %s SOL | Sells: %s SOL)'
        % (win_label, '+' if net_sol >= 0 else '', _r(net_sol),
           _r(m.get('buy_vol', 0)), _r(m.get('sell_vol', 0))),
        '• <b>Pure Accumulators:</b> %s Pure Wallets (%s%% buy volume hold, 0%% sell)'
        % (m.get('n_pure', 0), round(m.get('pct_pure', 0) * 100)),
        '• <b>Smart Wallets (0-sell):</b> %s · <b>Active Terminals (%s):</b> %s'
        % (m.get('smart_count', 0), sub_label, terms),
        '',
        '⏱ <b>Status:</b> %s' % result.get('stage', ''),
        ('🔗 <a href="https://dexscreener.com/solana/%s">DexScreener</a> | '
         '<a href="https://gmgn.ai/sol/token/%s">GMGN</a>' % (ca, ca)),
    ]
    return NL.join(lines)


def compute_bullish_div(ca, pool, *, bucket_hours=1, hours_span=48):
    '''Detect a bullish CVD/price divergence on H1 whale CVD. Returns bool.

    Network-only helper (GeckoTerminal price). Returns False on any failure
    so callers never crash. Pass the result into evaluate_prepump as
    ``bullish_div``.
    '''
    try:
        from cvd import (get_series, fetch_price_series, detect_divergence)
        s = get_series(ca, bucket_hours=bucket_hours, hours_span=hours_span)
        if not s or len(s.get('ts', [])) < 7:
            return False
        pmap = fetch_price_series(pool, bucket_hours, limit=max(60, hours_span))
        pser, last = [], None
        for t in s['ts']:
            last = pmap.get(int(t), last)
            pser.append(last)
        if pser and pser[0] is None:
            fv = next((p for p in pser if p is not None), None)
            pser = [fv if p is None else p for p in pser]
        if not all(p is not None for p in pser):
            return False
        divs = (detect_divergence(pser, s.get('cvd', []))
                + detect_divergence(pser, s.get('whale', [])))
        return any(d.get('type') == 'bullish' for d in divs)
    except Exception:
        return False


def prepump_already_sent(sigs, ca, sig_type, now_ts,
                         dedupe_sec=PREPUMP_DEDUPE_SEC):
    '''True if the same (ca, sig_type) fired within ``dedupe_sec``.'''
    now_ts = int(now_ts)
    for s in reversed((sigs or [])[-300:]):
        if (s.get('ca') == ca and s.get('type') == sig_type
                and now_ts - (s.get('ts') or 0) < dedupe_sec):
            return True
    return False


def format_prepump_cleared_telegram(ca, token_info=None, last_score=None):
    """Render a Telegram message when a pre-pump condition clears."""
    NL = chr(10)
    ti = token_info or {}
    sym = ti.get('symbol') or '?'
    score_txt = f" last score {last_score}/100" if last_score is not None else ""
    lines = [
        f"✅ <b>PRE-PUMP CLEARED: ${sym}</b>",
        f"<code>{ca}</code>",
        "",
        f"Pre-pump conditions no longer met{score_txt} — compression / asymmetry / "
        "pure-accum signals have faded on the 30m window.",
        "No imminent ignition; watch for fresh compression before re-entry.",
        "",
        f"<a href='https://dexscreener.com/solana/{ca}'>chart</a> | "
        f"<a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>",
    ]
    return NL.join(lines)


def format_prepump_combined_digest(entries):
    """One combined digest for multiple pre-pump results (for cron digest mode).

    Entries may carry a ``multi`` (evaluate_prepump_multi_tf result); when
    present a compact multi-timeframe pill + confluence emoji is appended.
    """
    if not entries:
        return None
    NL = chr(10)
    lines = [f"<b>🎯 PRE-PUMP DIGEST</b> — {len(entries)} token(s)", ""]
    for e in entries:
        r = e.get("result") or {}
        ca = e.get("ca", "")
        ti = e.get("token_info") or r.get("token_info") or {}
        sym = ti.get("symbol") or e.get("symbol") or "?"
        multi = e.get("multi") or r.get("multi_tf")
        pill = (" " + format_prepump_digest_pill(multi)) if multi else ""
        conf = (multi or {}).get("confluence") or {}
        conf_emo = ""
        if conf.get("status") and conf.get("status") != "normal":
            conf_emo = " " + conf.get("emoji", "")
        lines.append(
            f"{'🚨' if r.get('tier')=='imminent' else '👀'} <b>${sym}</b> "
            f"{r.get('score','?')}/100 {r.get('tier','?')}"
            f"{pill}{conf_emo} "
            f"<a href='https://dexscreener.com/solana/{ca}'>chart</a>"
        )
    return NL.join(lines)
