'''Tests for PR follow-ups: sidebar badge, cleared notice, combined digest.

Network-free; deps stubbed. Paths patched to tmpdir so production
signals.json is never touched.
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


# ── helpers ──────────────────────────────────────────────────────────────
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


# ── 1. Sidebar badge ────────────────────────────────────────────────────
def test_sidebar_badge_tiers():
    sw = _build_prepump_swaps(now)
    tags = _tags([('W1', ['bluechip_owner']), ('W2', ['axiom']),
                  ('W3', ['top_holder'])])
    r = pp.evaluate_prepump(sw, {'symbol': 'HOT'}, ca='HOT', now_ts=now,
                            window_min=30, wallet_tags=tags, bullish_div=True)
    html, tier = pp.format_prepump_sidebar_badge(r, 'HOT')
    assert tier == 'imminent', tier
    assert 'HOT' in html and 'IMMINENT' in html
    assert str(int(r['score'])) in html or str(r['score']) in html

    # Neutral
    r0 = {'score': 10.0, 'tier': 'neutral'}
    html0, tier0 = pp.format_prepump_sidebar_badge(r0, 'COLD')
    assert tier0 == 'neutral'
    assert 'COLD' in html0 and 'neutral' in html0

    # Forming
    r1 = {'score': 60.0, 'tier': 'forming'}
    html1, tier1 = pp.format_prepump_sidebar_badge(r1, 'MID')
    assert tier1 == 'forming'
    assert 'FORMING' in html1
    print('sidebar badge ok')


# ── 2. Cleared notification (pre-pump) ──────────────────────────────────
def test_prepump_cleared_format():
    prev = {'type': 'prepump_imminent', 'score': 88, 'symbol': 'X'}
    msg = pp.format_prepump_cleared_telegram(
        prev, 'CA123', {'symbol': 'X', 'price_usd': 0.01, 'mc': 50000},
        score=12.0)
    assert 'CLEARED' in msg
    assert 'X' in msg
    assert 'IMMINENT' in msg
    assert '12' in msg or '12.0' in msg
    assert 'dexscreener.com/solana/CA123' in msg
    print('cleared format ok')


def test_last_prepump_signal():
    sigs = [
        {'ca': 'A', 'type': 'accumulation', 'ts': 1},
        {'ca': 'A', 'type': 'prepump_forming', 'ts': 2, 'score': 60},
        {'ca': 'B', 'type': 'prepump_imminent', 'ts': 3, 'score': 80},
        {'ca': 'A', 'type': 'prepump_cleared', 'ts': 4, 'score': 10},
    ]
    last_a = pp.last_prepump_signal(sigs, 'A')
    assert last_a['type'] == 'prepump_cleared'
    last_b = pp.last_prepump_signal(sigs, 'B')
    assert last_b['type'] == 'prepump_imminent'
    assert pp.last_prepump_signal(sigs, 'Z') is None
    print('last_prepump_signal ok')


def test_detect_prepump_cleared_path():
    '''When score drops below 55 after a prior imminent, emit cleared.'''
    with tempfile.TemporaryDirectory() as td:
        _patch_signals_path(td)
        # Seed a prior imminent signal.
        sig.save_signals([{
            'ts': now - 3600, 'ca': 'DROP', 'symbol': 'DROP',
            'type': 'prepump_imminent', 'src': 'cron', 'score': 90,
            'detail': 'prior',
        }])
        # Quiet swaps → score 0 → should clear.
        quiet = [mk('buy', 0.1, now - 10, 'q1')]
        sent = []
        # Force immediate send (no digest) and capture.
        sig._DIGEST_MODE = False
        sig._DIGEST_BUF = []
        # Monkeypatch send path.
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


# ── 3. Monitor cleared ──────────────────────────────────────────────────
def test_monitor_format_cleared():
    rows = [{'accum': 5, 'dist': 1, 'conviction': 40,
             'buy_sell_ratio': 1.5, 'tx': 10, 'volume': 3.0}]
    msg = ma.format_cleared('TOK', 'CA', 'stealth', rows)
    assert 'CLEARED' in msg and 'STEALTH' in msg and 'TOK' in msg
    msg2 = ma.format_cleared('TOK', 'CA', 'dist', rows)
    assert 'DISTRIBUSI CLEARED' in msg2
    print('monitor cleared ok')


# ── 4. Combined digest ──────────────────────────────────────────────────
def test_combined_digest_basic():
    items = ['msg one about $AAA', 'msg two about $BBB', 'msg three $CCC']
    chunks = ma.format_combined_digest(items, title='📬 <b>DIGEST</b>')
    assert len(chunks) == 1
    assert 'DIGEST' in chunks[0]
    assert 'msg one' in chunks[0] and 'msg three' in chunks[0]
    assert chunks[0].count('— — —') == 2
    print('digest basic ok')


def test_combined_digest_chunks_on_overflow():
    # Force tiny max_chars so each item becomes its own chunk.
    items = ['AAAA' * 20, 'BBBB' * 20, 'CCCC' * 20]
    chunks = ma.format_combined_digest(items, title='H', max_chars=80)
    assert len(chunks) >= 2, len(chunks)
    joined = ' | '.join(chunks)
    assert 'AAAA' in joined and 'CCCC' in joined
    print('digest chunking ok, n=%d' % len(chunks))


def test_combined_digest_empty():
    assert ma.format_combined_digest([]) == []
    assert ma.format_combined_digest(None) == []
    assert ma.format_combined_digest(['', '  ']) == []
    print('digest empty ok')


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
        # Empty flush is a no-op.
        assert sig.flush_telegram_digest(send_fn=lambda t: True) == 0
        print('signals digest flush ok')


def test_evaluate_cleared_transition_logic():
    '''telegram_monitor evaluate: TRUE→FALSE should be detectable via state.'''
    # Re-import evaluate from telegram_monitor_alerts with stubs.
    # We only test the pure state transition helper.
    from telegram_monitor_alerts import evaluate
    state = {}
    # First trigger
    send, why, entry = evaluate(state, 'CA', 'stealth', True, 180)
    assert send is True and why == 'new trigger'
    state['CA|stealth'] = entry
    # Still true within cooldown
    send2, why2, entry2 = evaluate(state, 'CA', 'stealth', True, 180)
    assert send2 is False and 'cooldown' in why2
    # Clear
    send3, why3, entry3 = evaluate(state, 'CA', 'stealth', False, 180)
    assert send3 is False and why3 == 'not triggered'
    assert entry3['triggered'] is False
    # The caller uses was_trig=prev.triggered to decide CLEARED — verify.
    assert state['CA|stealth']['triggered'] is True  # before apply
    print('evaluate clear transition ok')


if __name__ == '__main__':
    test_sidebar_badge_tiers()
    test_prepump_cleared_format()
    test_last_prepump_signal()
    test_detect_prepump_cleared_path()
    test_monitor_format_cleared()
    test_combined_digest_basic()
    test_combined_digest_chunks_on_overflow()
    test_combined_digest_empty()
    test_signals_digest_buffer_flush()
    test_evaluate_cleared_transition_logic()
    print('ALL FOLLOW-UP TESTS PASSED')
