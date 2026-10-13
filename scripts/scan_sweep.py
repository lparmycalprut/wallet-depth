#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runner cron page **🌊 Sweep** (GitHub Actions, tiap 5 menit).

Alur yang sama dengan tombol "Scan sekarang" di UI, tapi tanpa Streamlit:

    python scripts/scan_sweep.py [--no-alerts] [--no-cache] [--workers N]

Berkas state ditulis **selalu**, tapi baris terakhir mencetak
``SWEEP_STATE_CHANGED=0|1``. Workflow memakai penanda itu untuk memutuskan
perlu tidaknya commit — tanpa itu, cron 5 menitan akan membuat ~288 commit/hari
hanya karena field ``updated``.

Kredensial Telegram dibaca berlapis oleh :mod:`sweep_alert`
(``st.secrets`` → env → ``config.json``); di GitHub Actions cukup lewat
``env:`` dari repository secrets dengan nama ``TELEGRAM_BOT_TOKEN`` dan
``TELEGRAM_CHAT_ID``.
"""
from __future__ import annotations

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import sweep_scan as scan          # noqa: E402
import sweep_store as store        # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scan kelayakan sweep + alert")
    parser.add_argument("--mints", default="",
                        help="override watchlist (koma/baris)")
    parser.add_argument("--no-alerts", action="store_true",
                        help="hitung saja tanpa kirim Telegram")
    parser.add_argument("--no-cache", action="store_true",
                        help="abaikan cache HTTP (paksa ambil ulang)")
    parser.add_argument("--workers", type=int, default=scan.DEFAULT_WORKERS)
    args = parser.parse_args(argv)

    state_before = store.load_state()
    before = store.fingerprint(state_before)
    mints = (store.parse_mints(args.mints) if args.mints
             else store.load_watchlist())
    if not mints:
        print("Watchlist sweep kosong — tidak ada yang dipindai.")
        print("SWEEP_STATE_CHANGED=0")
        return 0

    print(f"Memindai {len(mints)} mint watchlist sweep "
          f"(ambang fix liq/MC {scan.screen.LIQ_MC_MAX*100:.0f}%, "
          f"holder/wallet {scan.screen.HOLDER_MAX_PCT:.0f}%)…")
    outcome = scan.run_scan(mints, state=state_before,
                            use_cache=not args.no_cache,
                            send_alerts=not args.no_alerts,
                            workers=args.workers)
    state = outcome["state"]
    after = store.fingerprint(state)
    store.save_state(state)

    for row in outcome["rows"]:
        result = row.get("result") or {}
        metrics = row.get("metrics") or {}
        symbol = metrics.get("symbol") or row.get("mint", "")[:8]
        liq_mc = result.get("liq_mc")
        liq_mc_text = f"{liq_mc*100:.1f}%" if liq_mc is not None else "—"
        print(f"  {symbol:12} {result.get('verdict') or '—':12} "
              f"{result.get('passed_count')}/{result.get('scored_count')} "
              f"liq/MC={liq_mc_text:>7} "
              f"sweep={'ya' if row.get('sweep_context') else 'tidak'}")
    for item in outcome["alerts"]:
        print(f"  alert {item['kind']} {item['mint'][:8]} "
              f"terkirim={'ya' if item['sent'] else 'tidak'}"
              + (f" ({item['error']})" if item.get("error") else ""))
    print(f"Selesai dalam {outcome['elapsed']:.1f}s. "
          f"State {'berubah' if before != after else 'tidak berubah'}.")
    print(f"SWEEP_STATE_CHANGED={1 if before != after else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
