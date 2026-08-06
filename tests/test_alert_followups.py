'''Tests for alert follow-ups: cleared notice + combined digest + cron buffer.

Network-free; deps stubbed. Paths patched to tmpdir so production
signals.json is never touched.

Note: sidebar Pre-Pump radar + monitor digest live on main via PR #62;
this suite locks the signals.py cron-digest buffer and the pre-pump
CLEARED path that the hourly update_cvd cron relies on.
'''
import os
import sys
import types
import tempfile
import json

# Stub heavy deps before any project import.
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
import monitor_alerts as ma
import signals as sig


def mk(side, sol, ts, w):
    return (side, sol, ts, w)


t0 = 1700000000
now = t0 + 30


def _tags(pairs):
    return {w: {'maker_tags': list(t), 'maker_token_tags': []}
            for w, t in pairs}


def _build_prepump_swaps(now_ts):
    sw = []
    for i in range(40):
        ts = now_ts - 4 * 3600 + i * 300
        sw.append(mk('buy', 10.0, ts, 'M%d' % i))
    for i in range(8):
        sw.append(mk('sell', 0.03, now_ts - 25 * 60 + i, 'rs%d' % i))
    for w, sol in [('W1', 5.0), ('W2', 5.0), ('W3', 5.0),
                  ('W4', 4.0), ('W5', 3.0)]:
        sw.append(mk('buy', sol, now_ts - 10 * 60, w))
    return sw


def _patch_signals_path(tmpdir):
    path = os.path.join(tmpdir, 'signals.json')
    with open(path, 'w') as f:
        json.dump([], f)
    sig.SIGNALS_PATH = path
    return path


# ── 1. Pre-pump cleared format (main API) ───────────────────────────────
def test_prepump_cleared_format():
    msg = pp.format_prepump_cleared_telegram(
        'CA123', {'symbol': 'X', 'price_usd': 0.01, 'mc': 50000},
        last_score=88)
    assert 'CLEARED' in msg
    assert 'X' in msg
    assert 'CA123' in msg
    assert '88' in msg
    assert 'dexscreener.com/solana/CA123' in msg
    print('cleared format ok')


# ── 2. Cleared path via detect_prepump_and_record ───────────────────────
def test_detect_prepump_cleared_path():
    '''When score drops below 55 after a prior imminent, emit cleared.'''
    with tempfile.TemporaryDirectory() as td:
        _patch_signals_path(td)
        sig.save_signals([{
            'ts': now - 3600, 'ca': 'DROP', 'symbol': 'DROP',
            'type': 'prepump_imminent', 'src': 'cron', 'score': 90,
            'detail': 'prior',
        }])
        quiet = [mk('buy', 0.1, now - 10, 'q1')]
        sent = []
        sig._DIGEST_MODE = False
        sig._DIGEST_BUF = []
        orig = sig._queue_or_send
        sig._queue_or_send = lambda t: sent.append(t) or True
        try:
            r = sig.detect_prepump_and_record(
                'DROP', 'DROP', quiet, token_info={'symbol': 'DROP'},
                now_ts=now, src='cron')
        finally:
            sig._queue_or_send = orig
        assert r is not None
        assert r.get('cleared') is True, r
        stored = sig.load_signals()
        types_ = [s['type'] for s in stored if s['ca'] == 'DROP']
        assert 'prepump_cleared' in types_, types_
        assert sent and 'CLEARED' in sent[0]
        print('detect cleared path ok')


def test_detect_prepump_no_clear_without_prior():
    '''Score <55 with no prior active signal → no cleared entry.'''
    with tempfile.TemporaryDirectory() as td:
        _patch_signals_path(td)
        quiet = [mk('buy', 0.1, now - 10, 'q1')]
        sent = []
        sig._DIGEST_MODE = False
        sig._DIGEST_BUF = []
        orig = sig._queue_or_send
        sig._queue_or_send = lambda t: sent.append(t) or True
        try:
            r = sig.detect_prepump_and_record(
                'NEW', 'NEW', quiet, token_info={'symbol': 'NEW'},
                now_ts=now, src='cron')
        finally:
            sig._queue_or_send = orig
        assert r is not None
        assert not r.get('cleared')
        types_ = [s['type'] for s in sig.load_signals()]
        assert 'prepump_cleared' not in types_
        assert sent == []
        print('no-clear-without-prior ok')


# ── 3. Monitor cleared + combined digest (main API) ─────────────────────
def test_monitor_format_cleared_alert():
    rows = [{'accum': 5, 'dist': 1, 'conviction': 40,
             'buy_sell_ratio': 1.5, 'tx': 10, 'volume': 3.0}]
    msg = ma.format_cleared_alert('TOK', 'CA', rows, 'stealth')
    assert 'CLEARED' in msg and 'TOK' in msg
    msg2 = ma.format_cleared_alert('TOK', 'CA', rows, 'dist')
    assert 'DISTRIBUSI CLEARED' in msg2
    print('monitor cleared ok')


def test_combined_digest_structured():
    '''Main's format_combined_digest takes structured kwargs.'''
    triggered = [{
        'symbol': 'AAA', 'ca': 'CA1',
        'rows': [{'accum': 3, 'dist': 0, 'conviction': 50,
                  'buy_sell_ratio': 2.0, 'tx': 5, 'volume': 10.0}],
        'kind': 'stealth',
        'result': {'msg': 'ok'},
    }]
    cleared = [{
        'symbol': 'BBB', 'ca': 'CA2',
        'rows': [{'accum': 1, 'dist': 2, 'conviction': 20,
                  'buy_sell_ratio': 0.5, 'tx': 8, 'volume': 4.0}],
        'kind': 'dist',
    }]
    prepump = [{
        'symbol': 'CCC', 'ca': 'CA3',
        'result': {'score': 80, 'tier': 'imminent'},
    }]
    prepump_cleared = [{'symbol': 'DDD', 'ca': 'CA4'}]
    msg = ma.format_combined_digest(
        triggered=triggered, cleared=cleared,
        prepump=prepump, prepump_cleared=prepump_cleared)
    assert msg is not None
    assert 'DIGEST' in msg
    assert 'AAA' in msg and 'BBB' in msg and 'CCC' in msg and 'DDD' in msg
    assert ma.format_combined_digest() is None
    print('structured digest ok')


# ── 4. signals.py digest buffer (cron path) ─────────────────────────────
def test_signals_digest_buffer_flush():
    with tempfile.TemporaryDirectory() as td:
        _patch_signals_path(td)
        sent = []
        sig.begin_digest()
        assert sig._DIGEST_MODE is True
        sig._queue_or_send('first alert')
        sig._queue_or_send('second alert')
        assert len(sig._DIGEST_BUF) == 2
        n = sig.flush_telegram_digest(
            title='📬 TEST', send_fn=lambda t: sent.append(t) or True)
        assert n == 1, (n, sent)
        assert sig._DIGEST_MODE is False
        assert sig._DIGEST_BUF == []
        assert len(sent) == 1
        assert 'first alert' in sent[0] and 'second alert' in sent[0]
        assert sig.flush_telegram_digest(send_fn=lambda t: True) == 0
        print('signals digest flush ok')


def test_imminent_goes_to_digest_buffer():
    '''When digest mode is on, imminent pre-pump is queued not sent.'''
    with tempfile.TemporaryDirectory() as td:
        _patch_signals_path(td)
        sw = _build_prepump_swaps(now)
        tags = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom']),
                      ('W3', ['top_holder'])])
        sent = []
        sig.begin_digest()
        # Capture immediate send attempts (should not happen in digest mode)
        import breakout_guard as bg
        orig_tg = getattr(bg, 'send_telegram', None)
        bg.send_telegram = lambda t: sent.append(('direct', t)) or True
        try:
            r = sig.detect_prepump_and_record(
                'HOT', 'HOT', sw,
                token_info={'symbol': 'HOT'}, now_ts=now, src='cron',
                wallet_tags=tags, bullish_div=True)
        finally:
            if orig_tg is not None:
                bg.send_telegram = orig_tg
            # end digest cleanly
            out = []
            n = sig.flush_telegram_digest(
                title='T', send_fn=lambda t: out.append(t) or True)
        assert r is not None and r.get('tier') == 'imminent'
        assert sent == [], 'must not send directly in digest mode: %s' % sent
        assert n == 1 and out and 'PRE-PUMP' in out[0]
        print('imminent buffered ok')


def test_evaluate_clear_transition():
    from telegram_monitor_alerts import evaluate
    state = {}
    send, why, entry = evaluate(state, 'CA', 'stealth', True, 180)
    assert send is True
    state['CA|stealth'] = entry
    send3, why3, entry3 = evaluate(state, 'CA', 'stealth', False, 180)
    assert send3 is False and why3 == 'not triggered'
    assert entry3['triggered'] is False
    assert state['CA|stealth']['triggered'] is True  # before apply
    print('evaluate clear transition ok')


if __name__ == '__main__':
    test_prepump_cleared_format()
    test_detect_prepump_cleared_path()
    test_detect_prepump_no_clear_without_prior()
    test_monitor_format_cleared_alert()
    test_combined_digest_structured()
    test_signals_digest_buffer_flush()
    test_imminent_goes_to_digest_buffer()
    test_evaluate_clear_transition()
    print('ALL FOLLOW-UP TESTS PASSED')
