#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runner Early Watcher (GitHub Actions, satu job ≈ 25 menit, poll tiap 2 menit).

    python scripts/early_watch.py [--duration 1500] [--interval 120] [--no-alerts]

Dengan ``--duration 0`` (default) hanya satu poll. Di workflow, durasi diisi
supaya satu job mencakup beberapa poll. Cron GitHub tidak cukup rapat untuk
interval 2 menit, jadi loop ada di dalam job.

Baris terakhir selalu ``EARLY_WATCH_CHANGED=0|1``. Nilai 1 berarti fingerprint
keputusan (lihat :func:`early_watch.decision_fingerprint`) berubah, sehingga
workflow perlu meng-commit state. Log poll tidak memicu commit.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import early_watch as ew  # noqa: E402


def _send(text: str):
    import sweep_alert  # impor lokal: tes tidak membutuhkan kredensial
    return sweep_alert.send_message(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--duration", type=int, default=0,
                    help="detik total loop; 0 = satu poll saja")
    ap.add_argument("--interval", type=int, default=ew.POLL_INTERVAL_SEC)
    ap.add_argument("--no-alerts", action="store_true",
                    help="jangan kirim Telegram (uji lokal)")
    ap.add_argument("--state", default=ew.STATE_PATH)
    args = ap.parse_args(argv)

    mints = ew.load_watchlist()
    if not mints:
        print("Watchlist kosong.", file=sys.stderr)
        print("EARLY_WATCH_CHANGED=0")
        return 1

    state = ew.load_state(args.state)
    before = ew.decision_fingerprint(state)
    sender = None if args.no_alerts else _send
    start = time.time()
    polls = 0
    while True:
        now = int(time.time())
        ew.run_poll(state, mints, now, sender=sender)
        ew.save_state(state, args.state)
        polls += 1
        for mint in mints:
            rec = state["mints"].get(mint, {})
            print(f"poll {polls} {time.strftime('%H:%M:%S', time.gmtime(now + 7 * 3600))} "
                  f"{mint[:8]} {rec.get('status')} trades={rec.get('trades')} "
                  f"rt={rec.get('rt_peak')} wallets={rec.get('wallets_peak')} "
                  f"partial={rec.get('partial')} err={rec.get('error', '')[:60]}")
        elapsed = time.time() - start
        if elapsed + args.interval > args.duration:
            break
        time.sleep(max(0.0, start + polls * args.interval - time.time()))

    changed = ew.decision_fingerprint(state) != before
    print(f"polls={polls}")
    print(f"EARLY_WATCH_CHANGED={int(changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
