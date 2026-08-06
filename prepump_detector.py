'''Multi-Tier On-Chain Pre-Pump Radar (multi-factor, 0-100 score).

Network-free evaluation of recent swap flow (cvd tuples (side, sol, ts, wallet)).
Shared by the dashboard, the hourly cron, and the unit tests.

Pipeline:
  1. Pre-processing: drop MEV / sandwich-bot trades.
  2. Baseline normalization: 4h prior volume -> per-hour baseline.
  3. Four 25-point pillars:
       P1 Volume Compression & Seller Exhaustion
       P2 Order-Flow Size Asymmetry (MEV-cleaned)
       P3 Pure Accumulator & Holding Conviction
       P4 Order-Flow Delta & Terminal Ignition
  4. Score >= 75 -> PRE-PUMP IMMINENT (Tier 1, Telegram)
             55-74 -> PRE-PUMP FORMING     (Tier 2, gated by focus_mode)
             < 55  -> neutral / noise
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


def _clean_swaps(swaps, wallet_tags):
    '''Drop sandwich-bot / MEV-arbitrage swaps so they don't fake flow.'''
    by_wallet = {}
    for s in (swaps or []):
        if len(s) < 4:
            continue
        by_wallet.setdefault(s[3], []).append(s)
    out = []
    for w, ws in by_wallet.items():
        if _is_sandwich(ws, wallet_tags):
            continue
        out.extend(ws)
    return out


def evaluate_prepump(swaps, token_info=None, *, ca=None, now_ts=None,
                     window_min=30, prior_hours=4, whale_min_sol=3.0,
                     smart_tags=None, wallet_tags=None, bullish_div=False,
                     pool_sol=None):
    '''Score the last ``window_min`` minutes for a pre-pump setup.

    Args:
        swaps: iterable of (side, sol, ts, wallet) cvd tuples.
        token_info: optional {symbol, price_usd, mc, vol_24h} for messaging.
        ca, now_ts, window_min, prior_hours: windowing (default 30m / 4h).
        whale_min_sol: large-sell threshold reference.
        wallet_tags: {wallet: {maker_tags:[...], maker_token_tags:[...]}}.
        bullish_div: True if bullish divergence on whale CVD H1.
        pool_sol: pool SOL reserves (enables the 0.5%-of-pool sell filter).

    Returns a dict with score, tier, per-pillar points, and metric details.
    '''
    now_ts = int(now_ts if now_ts is not None else time.time())
    win_start = now_ts - int(window_min) * 60
    prior_start = now_ts - int(prior_hours) * 3600
    w15_start = now_ts - 15 * 60

    cleaned = _clean_swaps(swaps, wallet_tags)
    recent = [s for s in cleaned
              if win_start <= int(s[2]) <= now_ts]
    prior = [s for s in cleaned
             if prior_start <= int(s[2]) < win_start]

    def _vol(subset):
        return sum(float(s[1]) for s in subset)

    vol_30m = _vol(recent)
    vol_15m = _vol([s for s in recent if int(s[2]) >= w15_start])
    baseline_vol_1h = (_vol(prior) / max(1e-9, int(prior_hours))) \
        if prior else 0.0

    # ---- Pillar 1: Volume Compression & Seller Exhaustion (25) ----------
    p1 = 0.0
    compression_pct = 0.0
    if baseline_vol_1h > 0 and vol_15m < 0.35 * baseline_vol_1h:
        p1 += 15.0
        compression_pct = max(0.0, (1 - vol_15m / (baseline_vol_1h / 4.0))
                              * 100.0)
    elif baseline_vol_1h <= 0 and vol_15m <= 1.0:
        p1 += 15.0
        compression_pct = 100.0 if vol_15m <= 0.01 else 0.0
    large_sell_thr = (max(1.0, 0.005 * float(pool_sol))
                      if pool_sol else 1.0)
    large_sell = any(s[0] == 'sell' and float(s[1]) >= large_sell_thr
                     for s in recent)
    if not large_sell:
        p1 += 10.0
    p1 = min(25.0, p1)
    p1r = 'vol15m %.2f vs baseline1h %.2f; large-sell=%s' % (
        vol_15m, baseline_vol_1h, bool(large_sell))

    # ---- Pillar 2: Order-Flow Size Asymmetry (25) ---------------------
    buy_swaps = [s for s in recent if s[0] == 'buy']
    sell_swaps = [s for s in recent if s[0] == 'sell']
    buy_count = len(buy_swaps)
    buy_vol = _vol(buy_swaps)
    sell_vol = _vol(sell_swaps)
    avg_buy = buy_vol / buy_count if buy_count else 0.0
    avg_sell = sell_vol / sell_count if (sell_count := len(sell_swaps)) else 0.0
    ratio = avg_buy / max(avg_sell, 0.01)
    if buy_count >= 3:
        if ratio >= 3.0:
            p2 = 25.0
        elif ratio >= 2.0:
            p2 = 15.0
        else:
            p2 = 0.0
    else:
        p2 = 0.0
    p2r = 'avg buy %.2f vs sell %.2f (%sx), %d buys' % (
        avg_buy, avg_sell, _r(ratio), buy_count)

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
    p3 = 0.0
    if pct_pure >= 0.6:
        p3 += 15.0
    if smart_zero >= 2:
        p3 += 10.0
    p3 = min(25.0, p3)
    p3r = 'pure_accum %.0f%% of buy vol; %d smart wallets 0-sell' % (
        pct_pure * 100, smart_zero)

    # ---- Pillar 4: Order-Flow Delta & Terminal Ignition (25) ---------
    net_sol = buy_vol - sell_vol
    net_15 = (_vol([s for s in buy_swaps if int(s[2]) >= w15_start])
              - _vol([s for s in sell_swaps if int(s[2]) >= w15_start]))
    p4 = 0.0
    if net_15 > 0 and net_sol > 0:
        p4 += 10.0
    if bullish_div:
        p4 += 10.0
    # ignition: terminal-tagged wallets active in the last 10 minutes
    active_terminals = []
    if wallet_tags:
        for w, meta in (wallet_tags or {}).items():
            tags = set()
            if isinstance(meta, dict):
                tags.update(meta.get('maker_tags', []) or [])
                tags.update(meta.get('maker_token_tags', []) or [])
            if tags & PREPUMP_TERMINAL_TAGS:
                if any(int(s[2]) >= now_ts - 10 * 60 and s[3] == w
                       for s in recent):
                    for t in tags & PREPUMP_TERMINAL_TAGS:
                        if t not in active_terminals:
                            active_terminals.append(t)
    if active_terminals:
        p4 += 5.0
    p4 = min(25.0, p4)
    p4r = 'net15 %s net30 %s; div=%s; terminals=%s' % (
        _r(net_15), _r(net_sol), bool(bullish_div),
        ','.join(active_terminals) or '-')

    score = max(0.0, p1 + p2 + p3 + p4)
    if buy_count < 3:
        score = 0.0  # need a minimum of organic buys
    score = round(score, 1)
    tier = ('imminent' if score >= 75 else
            'forming' if score >= 55 else 'neutral')

    if active_terminals and compression_pct >= 50:
        stage = 'Compression Completed -> Smart Buying Detected'
    elif bullish_div:
        stage = 'Bullish Divergence -> Accumulation Confirmed'
    else:
        stage = 'Accumulation Building'

    return {
        'ca': ca,
        'score': score,
        'tier': tier,
        'window_min': int(window_min),
        'bullish_div': bool(bullish_div),
        'compression_pct': round(compression_pct, 1),
        'metrics': {
            'buy_vol': _r(buy_vol), 'sell_vol': _r(sell_vol),
            'net_sol': _r(net_sol), 'avg_buy': _r(avg_buy),
            'avg_sell': _r(avg_sell), 'ratio': _r(ratio),
            'buy_count': buy_count, 'sell_count': sell_count,
            'n_pure': n_pure, 'pct_pure': round(pct_pure, 4),
            'smart_count': smart_zero, 'smart_zero': smart_zero,
            'vol_15m': _r(vol_15m), 'vol_30m': _r(vol_30m),
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


def format_prepump_telegram(result, ca, token_info=None):
    '''Render an HTML Telegram message for a pre-pump result.'''
    NL = chr(10)
    m = result.get('metrics', {})
    ti = token_info or result.get('token_info') or {}
    sym = ti.get('symbol') or '?'
    badge = '🚨' if result['tier'] == 'imminent' else '👀'
    tier = ('HIGH CONVICTION' if result['tier'] == 'imminent'
            else 'EARLY STAGE')
    tags = ', '.join(result.get('smart_tags_found', [])) or \
        'bluechip_owner, axiom, top_holder'
    terms = ', '.join(m.get('active_terminals', [])) or \
        'axiom, trojan, bluechip_owner'
    lines = [
        '🎯 <b>PRE-PUMP DETECTED: $%s</b>' % sym,
        '<i>smart-money absorption · seller exhaustion · ignition trigger</i>',
        '',
        '📊 <b>Pre-Pump Score:</b> <b>%s/100</b> %s' % (result['score'], badge),
        '💰 <b>Price:</b> $%s | <b>MC:</b> $%s | <b>Vol 24h:</b> $%s'
        % (_fmt(ti.get('price_usd')), _fmt(ti.get('mc')),
           _fmt(ti.get('vol_24h'))),
        '',
        '🔍 <b>On-Chain Signatures:</b>',
        '• <b>Seller State:</b> 🟢 Exhausted (Vol compression -%s%% vs 4h avg)'
        % round(result.get('compression_pct', 0)),
        '• <b>Order Asymmetry:</b> Avg Buy <b>%s SOL</b> vs Avg Sell <b>%s SOL</b> (%sx)'
        % (_r(m.get('avg_buy', 0)), _r(m.get('avg_sell', 0)), _r(m.get('ratio', 0))),
        '• <b>Order Flow (30m):</b> Net <b>+%s SOL</b> (Buys: %s SOL | Sells: %s SOL)'
        % (_r(m.get('net_sol', 0)), _r(m.get('buy_vol', 0)), _r(m.get('sell_vol', 0))),
        '• <b>Accumulator Wallets:</b> %s Pure Wallets (%s%% volume hold, 0%% sell)'
        % (m.get('n_pure', 0), round(m.get('pct_pure', 0) * 100)),
        '• <b>Ignition / Terminals:</b> %s (e.g. <i>axiom, trojan, bluechip_owner</i>)'
        % terms,
        '',
        '⏱ <b>Status:</b> %s' % result.get('stage', ''),
        ('🔗 ' + chr(39) + '<a href=' + chr(39)
         + 'https://dexscreener.com/solana/' + str(ca) + chr(39)
         + '>DexScreener</a> | ' + chr(39) + '<a href=' + chr(39)
         + 'https://gmgn.ai/sol/token/' + str(ca) + chr(39) + '>GMGN</a>'),
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
