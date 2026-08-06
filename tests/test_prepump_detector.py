'''Unit tests for the Multi-Tier Pre-Pump Detector (no network; deps stubbed).'''
import sys
import os
import types

import importlib.util

# Stub heavy deps only when they are not installed (offline sandbox).
# Overwriting sys.modules unconditionally would leak bare stubs into other
# test modules under `python -m unittest discover tests`.
_stubbed = []
for _m in ('requests', 'pandas', 'numpy'):
    if _m not in sys.modules and importlib.util.find_spec(_m) is None:
        sys.modules[_m] = types.ModuleType(_m)
        _stubbed.append(_m)
if 'pandas' in _stubbed:
    pd = sys.modules['pandas']
    pd.DataFrame = object
    pd.Series = object
    pd.Timestamp = object
    pd.to_datetime = lambda *a, **k: None
    pd.read_json = lambda *a, **k: None
    pd.concat = lambda *a, **k: None
if 'numpy' in _stubbed:
    np = sys.modules['numpy']
    np.ndarray = object
    np.array = lambda *a, **k: None
    np.float64 = float
if 'requests' in _stubbed:
    _req = sys.modules['requests']
    _req.get = lambda *a, **k: None
    _req.post = lambda *a, **k: None
    _req.exceptions = types.SimpleNamespace(RequestException=Exception)

sys.path.insert(0, os.path.abspath('.'))

import prepump_detector as pp


def mk(side, sol, ts, w):
    return (side, sol, ts, w)


t0 = 1700000000
now = t0 + 30


def _tags(pairs):
    return {w: {'maker_tags': list(t), 'maker_token_tags': []}
            for w, t in pairs}


def _build_prepump_swaps(now_ts):
    '''Prior 4h heavy baseline + last 30m compression + 5 pure buys.

    NOTE: baseline swaps are buy-only so they are NOT mistaken for the
    sandwich/MEV filter (a buy+sell within 2s at equal size would be).
    '''
    sw = []
    # prior 4h: 40 buy-only swaps of 10 SOL -> ~100 SOL/hour baseline
    for i in range(40):
        ts = now_ts - 4 * 3600 + i * 300
        sw.append(mk('buy', 10.0, ts, 'M%d' % i))
    # last 30m: dust sells (outside 15m) + 5 strong buys (inside 15m)
    for i in range(8):
        sw.append(mk('sell', 0.03, now_ts - 25 * 60 + i, 'rs%d' % i))
    for w, sol in [('W1', 5.0), ('W2', 5.0), ('W3', 5.0),
                  ('W4', 4.0), ('W5', 3.0)]:
        sw.append(mk('buy', sol, now_ts - 10 * 60, w))
    return sw


def test_real_prepump():
    sw = _build_prepump_swaps(now)
    tags = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom']),
                  ('W3', ['top_holder'])])
    r = pp.evaluate_prepump(sw, {'symbol': 'TEST'}, ca='TEST', now_ts=now,
                            window_min=30, wallet_tags=tags, bullish_div=True)
    print('S1 score=%s tier=%s pillars=%s compression=%s%%'
          % (r['score'], r['tier'], r['pillars'], r['compression_pct']))
    assert r['score'] >= 75, 'expected imminent, got %s' % r['score']
    assert r['tier'] == 'imminent'
    assert r['metrics']['smart_zero'] >= 2
    assert r['pillars']['compression'] == 25.0


def test_wash_distribution_not_flagged():
    sw = []
    for i in range(10):
        sw.append(mk('sell', 4.0, t0 + 5 + i, 'B%d' % i))
        sw.append(mk('buy', 4.0, t0 + 6 + i, 'B%d' % i))
    r = pp.evaluate_prepump(sw, {'symbol': 'WASH'}, ca='WASH', now_ts=now,
                            window_min=30, wallet_tags=None, bullish_div=False)
    print('S2 score=%s tier=%s pillars=%s' % (r['score'], r['tier'], r['pillars']))
    assert r['score'] < 55, 'expected noise, got %s' % r['score']


def test_sandwich_filtered():
    sw = [mk('buy', 10.0, t0 + 20, 'S'), mk('sell', 10.0, t0 + 21, 'S'),
          mk('buy', 1.0, t0 + 22, 'L')]
    tags = {'S': {'maker_tags': ['sandwich_bot'], 'maker_token_tags': []}}
    cleaned = pp._clean_swaps(sw, tags)
    assert all(s[3] != 'S' for s in cleaned), 'sandwich wallet must be dropped'
    r = pp.evaluate_prepump(sw, {'symbol': 'SW'}, ca='SW', now_ts=now,
                            window_min=30, wallet_tags=tags)
    # only L remains -> buy_count 1 (<3) -> score 0
    assert r['score'] == 0.0, 'sandwich should be filtered, got %s' % r['score']


def test_volume_scaling_low_vs_high():
    # High-volume token
    sw_h = _build_prepump_swaps(now)
    tags_h = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom']),
                    ('W3', ['top_holder'])])
    r_h = pp.evaluate_prepump(sw_h, {'symbol': 'HV'}, ca='HV', now_ts=now,
                             window_min=30, wallet_tags=tags_h, bullish_div=True)
    # Low-volume token: same proportional shape, smaller baseline (~10/h)
    sw_l = []
    for i in range(8):
        ts = now - 4 * 3600 + i * 1700
        sw_l.append(mk('buy', 5.0, ts, 'm%d' % i))  # buy-only -> no sandwich
    for i in range(8):
        sw_l.append(mk('sell', 0.01, now - 25 * 60 + i, 'rs%d' % i))
    for w, sol in [('w1', 0.6), ('w2', 0.6), ('w3', 0.6),
                  ('w4', 0.5), ('w5', 0.4)]:
        sw_l.append(mk('buy', sol, now - 10 * 60, w))
    tags_l = _tags([('w1', ['bluechip_owner']), ('w2', ['axiom']),
                    ('w3', ['top_holder'])])
    r_l = pp.evaluate_prepump(sw_l, {'symbol': 'LV'}, ca='LV', now_ts=now,
                             window_min=30, wallet_tags=tags_l, bullish_div=True)
    print('S3 high=%s low=%s' % (r_h['score'], r_l['score']))
    assert r_h['score'] >= 75, 'high-volume pre-pump >=75, got %s' % r_h['score']
    assert r_l['score'] >= 75, 'low-volume pre-pump >=75, got %s' % r_l['score']
    # proportional: both compress fully, both full pillars
    assert r_h['pillars']['compression'] == 25.0
    assert r_l['pillars']['compression'] == 25.0
    assert r_h['pillars']['accum'] == 25.0
    assert r_l['pillars']['accum'] == 25.0


def test_telegram_format():
    sw = _build_prepump_swaps(now)
    tags = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom'])])
    ti = {'symbol': 'TEST', 'price_usd': 0.0012, 'mc': 12345,
          'vol_24h': 98765}
    r = pp.evaluate_prepump(sw, ti, ca='TESTCA', now_ts=now, window_min=30,
                            wallet_tags=tags, bullish_div=False)
    msg = pp.format_prepump_telegram(r, 'TESTCA', ti)
    # New tier-badge title + on-chain signature breakdown.
    assert 'PRE-PUMP IMMINENT' in msg or 'PRE-PUMP FORMING' in msg
    assert '$TEST' in msg
    assert 'Pre-Pump Score' in msg
    assert 'dexscreener.com/solana/TESTCA' in msg
    assert 'Liq' in msg
    assert 'Active Terminals' in msg
    assert 'Order Asymmetry' in msg
    assert 'Order Flow' in msg
    assert 'Pure Accumulators' in msg
    print('telegram format ok, len=%d' % len(msg))


def test_dedup_cooldown():
    sigs = [{'ca': 'X', 'type': 'prepump_imminent', 'ts': 1000}]
    assert pp.prepump_already_sent(sigs, 'X', 'prepump_imminent',
                                  1000 + 3600, 10800) is True
    assert pp.prepump_already_sent(sigs, 'X', 'prepump_imminent',
                                  1000 + 4 * 3600, 10800) is False
    # different type (forming -> imminent exception) is not deduped
    assert pp.prepump_already_sent(sigs, 'X', 'prepump_forming',
                                  1000 + 3600, 10800) is False


if __name__ == '__main__':
    test_real_prepump()
    test_wash_distribution_not_flagged()
    test_sandwich_filtered()
    test_volume_scaling_low_vs_high()
    test_telegram_format()
    test_dedup_cooldown()
    print('ALL TESTS PASSED')


# ---------------------------------------------------------------------------
# Multi-timeframe radar (30m / 1h / 4h / 12h) + confluence
# ---------------------------------------------------------------------------
def test_multi_tf_structure():
    sw = _build_prepump_swaps(now)
    tags = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom']),
                  ('W3', ['top_holder'])])
    multi = pp.evaluate_prepump_multi_tf(sw, {'symbol': 'TEST'}, ca='TEST',
                                         now_ts=now, wallet_tags=tags,
                                         bullish_div_h1=True)
    assert set(multi['timeframes']) == {'30m', '1h', '4h', '12h'}
    assert multi['primary_tf'] == '30m'
    for tf, cfg in pp.PREPUMP_TF_CONFIGS.items():
        r = multi['timeframes'][tf]
        assert r['tf'] == tf
        assert r['window_min'] == cfg['window_min'], (tf, r['window_min'])
        assert r['metrics']['sub_window_min'] == cfg['sub_window_min']
        assert r['metrics']['terminal_min'] == cfg['terminal_min']
        assert r['metrics']['min_buy'] == cfg['min_buy']
        assert r['metrics']['large_dump_sol'] == cfg['large_dump_sol']
        assert r['tf_role'] == cfg['role']
    assert multi['scores']['30m'] == multi['overall_score']
    conf = multi['confluence']
    assert conf['status'] in ('golden', 'dead_cat', 'sleeper', 'normal')
    assert 'label' in conf and 'emoji' in conf
    # legacy calibration retained on the primary timeframe
    assert multi['timeframes']['30m']['score'] == 100.0
    print('multi-tf structure ok scores=%s conf=%s'
          % (multi['scores'], conf['status']))


def test_confluence_statuses():
    # 🌟 golden: macro (best 4h/12h) >= 60 AND micro (best 30m/1h) >= 75
    c = pp.compute_confluence({'30m': 90, '1h': 40, '4h': 65, '12h': 20})
    assert c['status'] == 'golden' and c['emoji'] == '🌟', c
    assert c['label'] == 'GOLDEN CONFLUENCE'
    # macro can come from 12h alone; micro from 1h alone
    c = pp.compute_confluence({'30m': 10, '1h': 78, '4h': 20, '12h': 61})
    assert c['status'] == 'golden', c
    # 🪤 dead cat: 30m high but macro < 35
    c = pp.compute_confluence({'30m': 85, '1h': 50, '4h': 30, '12h': 10})
    assert c['status'] == 'dead_cat' and c['emoji'] == '🪤', c
    assert c['label'] == 'DEAD CAT / FAKE BOUNCE'
    # ⏳ sleeper: macro >= 65 but 30m < 40 (and micro best < 75, no golden)
    c = pp.compute_confluence({'30m': 20, '1h': 55, '4h': 70, '12h': 66})
    assert c['status'] == 'sleeper' and c['emoji'] == '⏳', c
    assert c['label'] == 'ACCUMULATION SLEEPER'
    # ➖ normal otherwise
    c = pp.compute_confluence({'30m': 50, '1h': 45, '4h': 50, '12h': 40})
    assert c['status'] == 'normal' and c['emoji'] == '➖', c
    # golden precedence over sleeper/dead_cat
    c = pp.compute_confluence({'30m': 80, '1h': 80, '4h': 70, '12h': 70})
    assert c['status'] == 'golden', c
    print('confluence statuses ok')


def test_multi_tf_min_buy_gate():
    '''4 organic buys pass the 30m gate (min 3) but not the 1h gate (min 5).'''
    sw = []
    # mild prior baseline (8h) so both 30m and 1h have reference data
    for i in range(8):
        sw.append(mk('buy', 2.0, now - 8 * 3600 + i * 3000, 'BL%d' % i))
    # recent: 4 pure buys inside the last 30m (and 1h), one dust sell
    for w, sol, ago in [('b1', 1.5, 25 * 60), ('b2', 1.5, 20 * 60),
                        ('b3', 1.5, 10 * 60), ('b4', 1.5, 5 * 60)]:
        sw.append(mk('buy', sol, now - ago, w))
    sw.append(mk('sell', 0.05, now - 60, 'rs'))
    multi = pp.evaluate_prepump_multi_tf(sw, {'symbol': 'G'}, ca='G',
                                         now_ts=now)
    r30 = multi['timeframes']['30m']
    r1h = multi['timeframes']['1h']
    print('min-buy gate 30m=%s 1h=%s' % (r30['score'], r1h['score']))
    assert r30['metrics']['buy_count'] == 4
    assert r30['score'] > 0, '30m (min 3 buys) should score, got %s' % r30
    assert r1h['score'] == 0.0, '1h (min 5 buys) must gate at 0, got %s' % r1h
    assert r1h['metrics']['min_buy'] == 5


def test_large_dump_threshold_per_tf():
    '''A 2 SOL sell trips the 30m/1h dump filter (1/2 SOL) but not 4h (5 SOL).'''
    sw = list(_build_prepump_swaps(now))
    sw.append(mk('sell', 2.0, now - 5 * 60, 'whale_dump'))
    multi = pp.evaluate_prepump_multi_tf(sw, {'symbol': 'D'}, ca='D',
                                         now_ts=now)
    assert multi['timeframes']['30m']['metrics']['whale_dumper'] is True
    assert multi['timeframes']['1h']['metrics']['whale_dumper'] is True
    assert multi['timeframes']['4h']['metrics']['whale_dumper'] is False
    assert multi['timeframes']['12h']['metrics']['whale_dumper'] is False
    # 30m P1 lost the 10-pt no-large-dump bonus vs the undumped baseline
    base = pp.evaluate_prepump(_build_prepump_swaps(now), {'symbol': 'D'},
                               ca='D', now_ts=now)
    dumped = multi['timeframes']['30m']
    assert base['pillars']['compression'] - dumped['pillars']['compression'] \
        >= 10.0, (base['pillars'], dumped['pillars'])
    print('large-dump thresholds ok')


def test_absorp_target_scales_with_tf():
    sw = _build_prepump_swaps(now)
    multi = pp.evaluate_prepump_multi_tf(sw, {'symbol': 'A', 'mc': 40000.0},
                                         ca='A', now_ts=now)
    t30 = multi['timeframes']['30m']['metrics']['absorp_target_sol']
    t4h = multi['timeframes']['4h']['metrics']['absorp_target_sol']
    t12 = multi['timeframes']['12h']['metrics']['absorp_target_sol']
    # low-cap tier base = 3 SOL, scaled x1 / x6 / x12
    assert t30 == 3.0 and t4h == 18.0 and t12 == 36.0, (t30, t4h, t12)
    print('absorp scaling ok %s/%s/%s' % (t30, t4h, t12))


def test_telegram_multi_tf_format():
    sw = _build_prepump_swaps(now)
    tags = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom'])])
    ti = {'symbol': 'TEST', 'price_usd': 0.0012, 'mc': 12345,
          'vol_24h': 98765}
    multi = pp.evaluate_prepump_multi_tf(sw, ti, ca='TESTCA', now_ts=now,
                                         wallet_tags=tags, bullish_div_h1=True)
    primary = multi['timeframes']['30m']
    msg = pp.format_prepump_telegram(primary, 'TESTCA', ti, multi=multi)
    assert '🚨 <b>PRE-PUMP IMMINENT: $TEST</b>' in msg
    assert 'Multi-TF:' in msg
    for tf in ('30m:', '1h:', '4h:', '12h:'):
        assert tf in msg, tf
    assert 'Confluence:' in msg
    assert '🌟' in msg or '➖' in msg or '🪤' in msg or '⏳' in msg
    assert 'dexscreener.com/solana/TESTCA' in msg
    # convenience: result-embedded multi also renders
    r2 = dict(primary)
    r2['multi_tf'] = multi
    msg2 = pp.format_prepump_telegram(r2, 'TESTCA', ti)
    assert 'Multi-TF:' in msg2
    # line helpers standalone
    assert pp.format_multi_tf_line(None) == ''
    assert pp.format_confluence_line(None) == ''
    pill = pp.format_prepump_digest_pill(multi)
    for tf in ('30m:', '1h:', '4h:', '12h:'):
        assert tf in pill, tf
    print('telegram multi-tf format ok, len=%d' % len(msg))


def test_combined_digest_pill():
    sw = _build_prepump_swaps(now)
    multi = pp.evaluate_prepump_multi_tf(sw, {'symbol': 'TEST'}, ca='TESTCA',
                                         now_ts=now)
    entries = [{'symbol': 'TEST', 'ca': 'TESTCA',
                'result': multi['timeframes']['30m'], 'multi': multi},
               {'symbol': 'PLAIN', 'ca': 'PLAINCA',
                'result': {'score': 61, 'tier': 'forming'}}]
    txt = pp.format_prepump_combined_digest(entries)
    assert txt is not None
    assert '[30m:' in txt and '12h:' in txt  # multi-TF pill present
    assert 'PLAIN' in txt  # entries without multi still render
    assert pp.format_prepump_combined_digest([]) is None
    print('combined digest pill ok')


if __name__ == '__main__':
    test_multi_tf_structure()
    test_confluence_statuses()
    test_multi_tf_min_buy_gate()
    test_large_dump_threshold_per_tf()
    test_absorp_target_scales_with_tf()
    test_telegram_multi_tf_format()
    test_combined_digest_pill()
    print('ALL MULTI-TF TESTS PASSED')


def test_safety_gate_blocks():
    sw = _build_prepump_swaps(now)
    tags = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom']),
                  ('W3', ['top_holder'])])
    # markup distance gate: already +120% in 24h -> blocked
    r = pp.evaluate_prepump(sw, {'symbol': 'X', 'markup_24h_pct': 120.0},
                            ca='X', now_ts=now, window_min=30,
                            wallet_tags=tags, bullish_div=True)
    assert r['tier'] == 'blocked', r
    assert r['score'] == 0.0
    # 24h vol < $20k -> blocked
    r2 = pp.evaluate_prepump(sw, {'symbol': 'X', 'vol24_usd': 15000.0},
                             ca='X', now_ts=now, window_min=30,
                             wallet_tags=tags, bullish_div=True)
    assert r2['tier'] == 'blocked'
    # without safety fields, same data scores high (not blocked)
    r3 = pp.evaluate_prepump(sw, {'symbol': 'X'}, ca='X', now_ts=now,
                             window_min=30, wallet_tags=tags, bullish_div=True)
    assert r3['tier'] != 'blocked'
    print('safety gate ok')


def test_liquidity_tier_scaling():
    sw = _build_prepump_swaps(now)
    tags = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom']),
                  ('W3', ['top_holder'])])
    r_low = pp.evaluate_prepump(sw, {'symbol': 'L', 'mc': 40000.0}, ca='L',
                                now_ts=now, window_min=30, wallet_tags=tags,
                                bullish_div=True)
    r_high = pp.evaluate_prepump(sw, {'symbol': 'H', 'mc': 1000000.0}, ca='H',
                                 now_ts=now, window_min=30, wallet_tags=tags,
                                 bullish_div=True)
    p3_low = r_low['pillars']['accum']
    p3_high = r_high['pillars']['accum']
    assert p3_low >= p3_high, (p3_low, p3_high)
    assert p3_low == 25.0, p3_low  # low-cap tier: 22 SOL >= 3 SOL -> full
    print('tier scaling ok low=%s high=%s' % (p3_low, p3_high))


if __name__ == '__main__':
    test_safety_gate_blocks()
    test_liquidity_tier_scaling()
