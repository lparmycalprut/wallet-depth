'''Telegram alert version of the 4h basis-100 monitor, with anti-spam + scheduler.

Reuses the exact same detection logic as the dashboard (monitor_alerts.py).

Usage:
  python telegram_monitor_alerts.py --ca <CA> --dry          # preview text
  python telegram_monitor_alerts.py --ca <CA>                # send if triggered
  python telegram_monitor_alerts.py --watchlist              # scan whole watchlist
  python telegram_monitor_alerts.py --watchlist --loop --interval 15
  python telegram_monitor_alerts.py --ca <CA> --cooldown 180  # re-alert max every 3h

Anti-spam: a (CA, kind) alert only sends on a FALSE->TRUE transition, or
after its cooldown (minutes) has elapsed while still TRUE. State persists in
monitor_alerts_state.json so repeated runs / cron invocations do not spam.

Scheduler: --loop runs forever, sleeping --interval minutes between scans.
For a real cron, call without --loop, e.g.  */15 * * * *  cd /repo && \
python telegram_monitor_alerts.py --watchlist

Telegram delivery uses breakout_guard.send_telegram() which reads
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (env) or config.json
(telegram_bot_token / telegram_chat_id). Use --dry to preview.
'''
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import get_helius_keys, get_market, load_config
from cvd import update_token_cvd, get_recent_swaps, wallet_profiles
import monitor_alerts as ma
from breakout_guard import send_telegram

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE, 'monitor_alerts_state.json')
NL = chr(10)


def analyze_ca(ca, hours, mon_bin_h):
    market = get_market(ca)
    pools = (market or {}).get('pair_addresses') or []
    if not market or not pools:
        return None, 'no market/pool'
    pool = pools[0]
    helius_keys = tuple(get_helius_keys(config=load_config()))
    try:
        update_token_cvd(helius_keys, ca, pool, max_pages=120,
                         use_gmgn=True)
    except Exception as exc:
        return None, 'fetch failed: ' + str(exc)
    swaps = get_recent_swaps(ca, hours)
    if not swaps:
        return None, 'no swaps in window'
    profiles = wallet_profiles(swaps)
    now_ts = time.time()
    rows = ma.build_monitor_rows(swaps, profiles, ca, hours, mon_bin_h,
                                now_ts)
    stealth = ma.detect_stealth_accumulation(rows)
    dist = ma.detect_distribution(rows)
    return {'symbol': market.get('symbol', '?'), 'rows': rows,
            'stealth': stealth, 'dist': dist}, None


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_state(state):
    try:
        tmp = STATE_PATH + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f, separators=(',', ':'))
        os.replace(tmp, STATE_PATH)
    except Exception as exc:
        print('[warn] cannot save state:', exc)


def evaluate(state, ca, kind, triggered, cooldown_min):
    '''Decide whether to send, and return the new state entry.

    Send on FALSE->TRUE transition, or when still TRUE and the cooldown
    (minutes) since the last send has elapsed. Does NOT mutate state;
    the caller applies the returned entry (unless --dry).
    '''
    key = ca + '|' + kind
    now = time.time()
    prev = state.get(key) or {}
    if not triggered:
        return False, 'not triggered', {
            'triggered': False,
            'sent_ts': prev.get('sent_ts', 0),
            'last_ts': now,
        }
    if not prev.get('triggered'):
        return True, 'new trigger', {
            'triggered': True, 'sent_ts': now, 'last_ts': now,
        }
    elapsed = now - prev.get('sent_ts', 0)
    if elapsed >= cooldown_min * 60:
        return True, 're-alert after cooldown', {
            'triggered': True, 'sent_ts': now, 'last_ts': now,
        }
    return False, 'within cooldown', {
        'triggered': True,
        'sent_ts': prev.get('sent_ts', now),
        'last_ts': now,
    }


def run_once(args):
    cas = []
    if args.watchlist:
        try:
            from watchlist import load_watchlist
            cas = list(load_watchlist())
        except Exception as exc:
            print('[warn] cannot load watchlist:', exc)
    elif args.ca:
        cas = [args.ca]
    else:
        print('[warn] need --ca or --watchlist')
        return

    if not cas:
        print('[warn] no CA to scan.')
        return

    state = load_state()
    for ca in cas:
        res, err = analyze_ca(ca, args.hours, args.bin_h)
        if err:
            print('[skip]', ca + ':', err)
            continue
        for kind in ('stealth', 'dist'):
            trig = res[kind]['triggered']
            send, why, entry = evaluate(state, ca, kind, trig,
                                        args.cooldown)
            if not trig:
                if not args.dry:
                    state[ca + '|' + kind] = entry
                print('[clear] %s %s' % (res['symbol'], kind))
                continue
            text = ma.format_alert(res['symbol'], ca, res['rows'], kind,
                                   res[kind])
            if args.dry:
                print('=' * 60)
                print('[%s] WOULD SEND (%s) %s' % (kind, why, res['symbol']))
                print(text)
                print('=' * 60)
            elif send:
                ok = send_telegram(text)
                print('[%s] telegram %s (%s) %s' % (
                    kind, res['symbol'], ca[:8], 'OK' if ok else 'FAIL'))
                state[ca + '|' + kind] = entry
            else:
                print('[%s] suppressed (%s) %s' % (kind, why, res['symbol']))
    if not args.dry:
        save_state(state)


def main():
    ap = argparse.ArgumentParser(
        description='4h basis-100 monitor Telegram alerts (anti-spam + loop)')
    ap.add_argument('--ca')
    ap.add_argument('--watchlist', action='store_true')
    ap.add_argument('--hours', type=int, default=24)
    ap.add_argument('--bin', type=int, default=4, dest='bin_h')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--cooldown', type=int, default=180,
                   help='re-alert max once per N minutes while still TRUE')
    ap.add_argument('--loop', action='store_true',
                   help='run forever, sleeping --interval minutes between scans')
    ap.add_argument('--interval', type=int, default=15,
                   help='minutes between scans when --loop')
    args = ap.parse_args()

    if args.loop:
        print('[loop] every %d min (ctrl-c to stop)' % args.interval)
        while True:
            try:
                run_once(args)
            except Exception as exc:
                print('[loop error]', exc)
            time.sleep(max(1, args.interval) * 60)
    else:
        run_once(args)


if __name__ == '__main__':
    main()
