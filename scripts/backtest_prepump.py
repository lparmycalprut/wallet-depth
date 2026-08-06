'''Offline backtester for the Pre-Pump Radar.

Loads every GMGN Trades detail CSV in the repo (GMGN_Trades_*_detail.csv),
reconstructs per-swap flow + wallet tags, locates the price pump peak, then
slides a 30-minute detection window forward to find the EARLIEST minute the
Pre-Pump Radar crosses the FORMING (>=55) / IMMINENT (>=75) thresholds, and
reports how many minutes BEFORE the peak the signal fired.

Run:  python scripts/backtest_prepump.py
'''
import calendar
import csv
import glob
import os
import sys
import time
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from prepump_detector import evaluate_prepump  # noqa: E402


def _parse_ts(s):
    '''2026-04-21 00:00:09.000 (UTC) -> epoch seconds.'''
    try:
        dt = datetime.strptime(s.strip(), '%Y-%m-%d %H:%M:%S.%f')
    except Exception:
        return None
    return calendar.timegm(dt.timetuple())


def parse_detail(path):
    '''Return (swaps, wallet_tags, prices) for one GMGN detail CSV.'''
    swaps, tags_map, prices = [], {}, []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            ts = _parse_ts(row.get('Timestamp (UTC)', ''))
            if ts is None:
                continue
            side = 'buy' if (row.get('Arah (BUY/SELL)', '').strip().upper()
                             == 'BUY') else 'sell'
            try:
                sol = float(row.get('SOL Amount', 0) or 0)
                price = float(row.get('Price USD', 0) or 0)
            except ValueError:
                continue
            wallet = (row.get('Wallet Address') or '').strip()
            raw_tags = row.get('Tags') or ''
            tags = [t.strip() for t in raw_tags.split(';') if t.strip()]
            swaps.append((side, sol, ts, wallet))
            if wallet:
                tags_map[wallet] = {'maker_tags': tags,
                                    'maker_token_tags': []}
            if price > 0:
                prices.append((ts, price))
    return swaps, tags_map, prices


def pump_peak(prices):
    '''Timestamp of the maximum per-swap price (the pump peak).'''
    if not prices:
        return None, 0.0
    peak_ts, peak_px = max(prices, key=lambda x: x[1])
    return peak_ts, peak_px


def backtest_one(path, step_s=60, scan_min_back=180):
    swaps, tags_map, prices = parse_detail(path)
    if not swaps or not prices:
        return None
    swaps.sort(key=lambda s: s[2])
    start_ts = swaps[0][2]
    end_ts = swaps[-1][2]
    peak_ts, peak_px = pump_peak(prices)
    start_px = prices[0][1] or peak_px

    first_forming = first_imminent = None
    scan_start = max(start_ts, peak_ts - scan_min_back * 60)
    t = scan_start
    while t <= peak_ts:
        r = evaluate_prepump(swaps, {'symbol': '?'}, ca='backtest',
                             now_ts=t, window_min=30,
                             wallet_tags=tags_map, bullish_div=False)
        if r.get('tier') != 'blocked':
            if first_forming is None and r['score'] >= 55:
                first_forming = t
            if first_imminent is None and r['score'] >= 75:
                first_imminent = t
            if first_forming is not None and first_imminent is not None:
                break
        t += step_s

    def _lead(ts):
        return round((peak_ts - ts) / 60.0, 1) if ts is not None else None

    return {
        'file': os.path.basename(path),
        'tx': len(swaps),
        'span_min': round((end_ts - start_ts) / 60.0),
        'pump_x': round(peak_px / start_px, 2) if start_px else None,
        'peak_utc': datetime.fromtimestamp(peak_ts, tz=timezone.utc)
        .strftime('%Y-%m-%d %H:%M'),
        'lead_forming': _lead(first_forming),
        'lead_imminent': _lead(first_imminent),
    }


def main():
    files = sorted(glob.glob(os.path.join(BASE, 'GMGN_Trades_*_detail.csv'))
                 + glob.glob(os.path.join(BASE, 'datasets',
                                          'GMGN_Trades_*_detail.csv')))
    if not files:
        print('No GMGN_Trades_*_detail.csv found in repo root.')
        return
    print('Found %d dataset CSV(s). Running offline backtest...\n' % len(files))
    print('%-34s %6s %7s %8s %10s %10s' % (
        'dataset', 'tx', 'pumpX', 'peak', 'leadF', 'leadI'))
    ok = 0
    for p in files:
        r = backtest_one(p)
        if not r:
            continue
        print('%-34s %6d %6sx %8s %9s %9s' % (
            r['file'][:34], r['tx'], r['pump_x'], r['peak_utc'],
            r['lead_forming'], r['lead_imminent']))
        if (r['lead_imminent'] is not None and r['lead_imminent'] > 0) or \
           (r['lead_forming'] is not None and r['lead_forming'] > 0):
            ok += 1
    print('\n%d/%d dataset(s) showed a pre-pump signal before the pump peak.'
          % (ok, len(files)))


if __name__ == '__main__':
    main()
