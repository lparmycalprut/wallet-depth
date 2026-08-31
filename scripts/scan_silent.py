#!/usr/bin/env python3
"""Scanner silent-accumulation 12 jam untuk watchlist.

Menggantikan ``realtime_reversal``: TANPA sinyal dan TANPA Telegram.
Untuk setiap token watchlist:

1. ambil daftar holder (Solscan dulu — ``auto`` — fallback GMGN/Helius,
   paginasi penuh, batas ``--max-wallets``),
2. pisahkan real holder (>$10 value) vs dust, hitung dust % marketcap,
3. hitung net flow + akumulator 12 jam terakhir,
4. tulis ``silent_status.json`` lokal & publish ke branch ``silent-live``.

Dijalankan GitHub Actions tiap ~15 menit.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from silent_accumulation import analyze_token
from silent_status import publish_silent_status
from watchlist import load_watchlist


def scan_watchlist(watchlist: dict, *, dust_limit: float | None = None,
                   max_wallets: int = 3000, max_trade_pages: int = 8,
                   workers: int = 4, progress=None,
                   holder_source: str | None = None) -> dict:
    """Analisis semua token watchlist; return {mint: analysis}.

    ``holder_source``: ``gmgn`` / ``solscan`` / ``auto`` — default
    ``None`` = ikuti config/env (default ``auto`` = Solscan dulu).
    """
    analyses: dict[str, dict] = {}
    total = len(watchlist or {})
    if not total:
        return analyses
    workers = max(1, min(int(workers), 8))

    def _job(item):
        mint, meta = item
        try:
            analysis = analyze_token(
                mint, (meta or {}).get("symbol") or "?",
                dust_limit=dust_limit, max_wallets=max_wallets,
                max_trade_pages=max_trade_pages, fetch_market=True,
                holder_source=holder_source)
            return mint, analysis, None
        except Exception as exc:  # noqa: BLE001
            return mint, None, str(exc)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_job, item): item[0] for item in watchlist.items()}
        for future in as_completed(futures):
            mint, analysis, error = future.result()
            done += 1
            if analysis is not None:
                analyses[mint] = analysis
            if error:
                print(f"WARN {mint[:8]}: {error}", file=sys.stderr)
            if progress:
                try:
                    progress(done, total, mint[:8])
                except Exception:  # noqa: BLE001
                    pass
    return analyses


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dust-limit", type=float, default=None,
                        help="batas value USD dust (default 10)")
    parser.add_argument("--max-wallets", type=int, default=3000,
                        help="maks holder dianalisis per token")
    parser.add_argument("--max-trade-pages", type=int, default=8,
                        help="maks halaman trade (100/halaman) per token")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--holder-source", choices=("gmgn", "solscan",
                                                    "auto"), default=None,
                        help="sumber holder; default ikut config/env "
                             "(auto = Solscan dulu, fallback GMGN/Helius)")
    parser.add_argument("--no-push", action="store_true",
                        help="hanya tulis status lokal")
    args = parser.parse_args(argv)

    watchlist = load_watchlist()
    print(f"Silent scanner: tokens={len(watchlist)} "
          f"time={datetime.now(timezone.utc).isoformat()} "
          f"max_wallets={args.max_wallets} "
          f"holder_source={args.holder_source or 'config(auto)'}")

    started = time.monotonic()
    analyses = scan_watchlist(
        watchlist, dust_limit=args.dust_limit,
        max_wallets=args.max_wallets,
        max_trade_pages=args.max_trade_pages,
        workers=args.workers,
        holder_source=args.holder_source)

    if analyses:
        silent = sum(1 for item in analyses.values()
                     if (item.get("silent") or {}).get("silent"))
        status = publish_silent_status(
            analyses, watchlist, push=not args.no_push)
        print(f"Silent scan selesai: analyzed={len(analyses)} "
              f"silent={silent} updated={status.get('updated_at')} "
              f"durasi={time.monotonic() - started:.1f}s")
        for mint, item in sorted(analyses.items()):
            holders = item.get("holders") or {}
            flow = item.get("flow") or {}
            print(f"  {item.get('symbol') or '?'} "
                  f"net12h={flow.get('net_usd')} "
                  f"real={holders.get('real_count')} "
                  f"dust={holders.get('dust_count')} "
                  f"dust%mc={holders.get('dust_pct_mc')} "
                  f"silent={bool((item.get('silent') or {}).get('silent'))}")
    else:
        publish_silent_status({}, watchlist, push=not args.no_push)
        print("Silent scan selesai: tidak ada token yang berhasil dianalisis")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
