#!/usr/bin/env python3
"""Scanner analisa holder (dust + kohort) untuk watchlist.

Untuk setiap token watchlist:

1. ambil daftar holder (Helius DAS dulu — ``auto`` — fallback GMGN),
2. pisahkan real vs dust, hitung dust % marketcap + mid-tier Crab/Fish,
3. catat **titik perubahan** ke ``holder_history.json`` (grafik 4 jam) —
   cron sengaja memakai ``ingest_many(..., detail=False)`` sehingga rekaman
   detail hasil scan FULL manual (``baseline`` / ``latest_detail``) milik
   user tidak pernah ditimpa,
4. tulis ``holder_status.json`` lokal & publish ke branch ``holder-live``.

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

from holder_history import ingest_many, load_holder_history, seed_from_status
from holder_analysis import analyze_token
from holder_status import (last_publish_result, load_holder_status,
                           publish_holder_status)
from watchlist import load_watchlist


def scan_watchlist(watchlist: dict, *, dust_limit: float | None = None,
                   max_wallets: int = 3000,
                   workers: int = 4, progress=None,
                   holder_source: str | None = None,
                   history_store: dict | None = None) -> dict:
    """Analisis semua token watchlist; return {mint: analysis}.

    ``holder_source``: ``gmgn`` / ``helius`` / ``auto`` — default
    ``None`` = ikuti config/env (default ``auto`` = Helius dulu).
    """
    analyses: dict[str, dict] = {}
    total = len(watchlist or {})
    if not total:
        return analyses
    workers = max(1, min(int(workers), 8))

    store = load_holder_history()

    def _job(item):
        mint, meta = item
        try:
            cohort = ((store.get("tokens") or {}).get(mint) or {}).get(
                "cohort") or {}
            addrs = list((cohort.get("balances") or {}).keys())
            analysis = analyze_token(
                mint, (meta or {}).get("symbol") or "?",
                dust_limit=dust_limit, max_wallets=max_wallets,
                fetch_market=True, holder_source=holder_source,
                cohort_addrs=addrs)
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
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--holder-source", choices=("gmgn", "helius",
                                                    "auto"), default=None,
                        help="sumber holder; default ikut config/env "
                             "(auto = Helius dulu, fallback GMGN)")
    parser.add_argument("--no-push", action="store_true",
                        help="hanya tulis status lokal")
    args = parser.parse_args(argv)

    watchlist = load_watchlist()
    try:
        from core import get_helius_keys
        helius_ok = bool(get_helius_keys())
    except Exception:  # noqa: BLE001
        helius_ok = False
    if not helius_ok:
        print("WARN: HELIUS_API_KEY tidak ada — holder hanya via GMGN "
              "(sering diblokir di runner Actions → dust kosong). "
              "Set secret HELIUS_API_KEY di repo.", file=sys.stderr)
    print(f"Holder scanner: tokens={len(watchlist)} "
          f"time={datetime.now(timezone.utc).isoformat()} "
          f"max_wallets={args.max_wallets} "
          f"holder_source={args.holder_source or 'config(auto)'}")

    started = time.monotonic()
    store = seed_from_status(load_holder_history(),
                            load_holder_status(force_refresh=True))
    analyses = scan_watchlist(
        watchlist, dust_limit=args.dust_limit,
        max_wallets=args.max_wallets,
        workers=args.workers,
        holder_source=args.holder_source,
        history_store=store)

    if analyses:
        # detail=False: cron hanya menambah titik perubahan; baseline
        # (detail scan FULL pertama dari halaman Holder) tetap utuh.
        history = ingest_many(analyses, store=store, detail=False)
        status = publish_holder_status(
            analyses, watchlist, push=not args.no_push)
        print(f"Holder scan selesai: analyzed={len(analyses)} "
              f"history={len((history or {}).get('tokens') or {})} "
              f"updated={status.get('updated_at')} "
              f"durasi={time.monotonic() - started:.1f}s")
        empty = 0
        for mint, item in sorted(analyses.items()):
            holders = item.get("holders") or {}
            if not holders.get("total_fetched"):
                empty += 1
            print(f"  {item.get('symbol') or '?'} "
                  f"src={holders.get('source')} "
                  f"fetched={holders.get('total_fetched')} "
                  f"real={holders.get('real_count')} "
                  f"dust={holders.get('dust_count')} "
                  f"dust%mc={holders.get('dust_pct_mc')} "
                  f"mid={((holders.get('mid') or {}).get('count'))}")
        if empty == len(analyses):
            print("ERROR: semua token 0 holder — sumber holder gagal "
                  "(cek HELIUS_API_KEY / akses GMGN).", file=sys.stderr)
            return 2
    else:
        publish_holder_status({}, watchlist, push=not args.no_push)
        print("Holder scan selesai: tidak ada token yang berhasil dianalisis")
        if watchlist:
            return 2
    if not args.no_push and last_publish_result().get("ok") is False:
        print(f"ERROR: publish holder_status gagal: "
              f"{last_publish_result().get('error')}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
