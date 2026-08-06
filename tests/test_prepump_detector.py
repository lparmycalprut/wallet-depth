'''Unit tests for the Multi-Tier Pre-Pump Detector (no network; deps stubbed).'''
import sys
import os
import types

for _m in ('requests', 'pandas', 'numpy'):
    sys.modules[_m] = types.ModuleType(_m)
pd = sys.modules['pandas']
pd.DataFrame = object
pd.Series = object
pd.Timestamp = object
pd.to_datetime = lambda *a, **k: None
pd.read_json = lambda *a, **k: None
pd.concat = lambda *a, **k: None
np = sys.modules['numpy']
np.ndarray = object
np.array = lambda *a, **k: None
np.float64 = float
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
    r = pp.evaluate_prepump(sw, {'symbol': 'TEST', 'price_usd': 0.0012,
                                 'mc': 12345, 'vol_24h': 98765},
                           ca='TESTCA', now_ts=now, window_min=30,
                           wallet_tags=tags, bullish_div=False)
    msg = pp.format_prepump_telegram(
        r, 'TESTCA', {'symbol': 'TEST', 'price_usd': 0.0012,
                      'mc': 12345, 'vol_24h': 98765})
    assert 'PRE-PUMP DETECTED' in msg
    assert 'TEST' in msg
    assert 'Score' in msg
    assert 'dexscreener.com/solana/TESTCA' in msg
    assert 'Vol 24h' in msg
    assert 'Ignition / Terminals' in msg
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
