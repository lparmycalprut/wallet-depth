#!/usr/bin/env python3
"""Scanner analisa holder (dust + kohort) untuk watchlist.

Untuk setiap token watchlist:

1. ambil daftar holder (Helius DAS dulu — ``auto`` — fallback GMGN),
2. pisahkan real vs dust, hitung dust % marketcap + mid-tier Crab/Fish,
3. evaluasi alert Telegram terhadap snapshot rolling ~4 jam dan snapshot
   awal **sebelum** snapshot terbaru ditulis; kandidat yang lolos ambang dust
   masih harus dikonfirmasi volume + harga + volatilitas (konteks pasar
   ditarik **lazy**, hanya untuk token yang punya kandidat, jadi scan tenang
   tidak menambah satu pun request),
4. catat **titik perubahan** ke ``holder_history.json`` (titik mentah per
   run; grafik memakai bucket 4 jam). Sejak 2026-09-05 cron memakai
   ``ingest_many(..., detail=True)``: tiap token watchlist di-scan
   **FULL** (semua halaman holder, bukan sampel 3000) sehingga scan
   pertama setelah token masuk watchlist menjadi **titik awal holder
   analytic** (``baseline`` immutable), lalu tiap run berikutnya
   memperbarui ``latest_detail`` + interval **kronologi** — tanpa perlu
   scan manual lagi,
5. tulis ``holder_status.json`` lokal & publish ke branch ``holder-live``.

Dijalankan GitHub Actions dengan target **1× per jam** (``cron: "0 * * * *"``
sejak 2026-09-04; schedule GitHub best-effort, lihat DEPLOY.md). Scope rule
⚡ EARLY DUMP = token pool (Chart LP / ``source=meteora``) lewat
``lp_watchlist.split_watchlist``.
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

from alert_context import market_context_provider
from daily_store import load_daily_effort
from holder_history import (FULL_SCAN_MAX_WALLETS, ingest_many,
                            load_holder_history, merge_stores,
                            publish_holder_history, pull_holder_history,
                            seed_from_status)
from holder_analysis import analyze_token
from holder_status import (last_publish_result, load_holder_status,
                           publish_holder_status)
from lp_watchlist import split_watchlist
import robinhood_watchlist
from telegram_alerts import (process_holder_alerts, send_test_alert,
                             tracked_wallet_addresses)
from watchlist import load_watchlist


def scan_watchlist(watchlist: dict, *, dust_limit: float | None = None,
                   max_wallets: int | None = None,
                   workers: int = 4, progress=None,
                   holder_source: str | None = None,
                   history_store: dict | None = None) -> dict:
    """Analisis semua token watchlist; return {mint: analysis}.

    ``holder_source``: ``gmgn`` / ``helius`` / ``auto`` — default
    ``None`` = ikuti config/env (default ``auto`` = Helius dulu).

    ``max_wallets`` default = ``FULL_SCAN_MAX_WALLETS`` (100.000): cron
    sejak 2026-09-05 memakai batas atas yang sama dengan tombol scan FULL
    di halaman Holder, jadi holder diambil sampai habis (bukan sampel
    3000) dan kronologi antar-scan FULL bisa dibangun otomatis.
    """
    analyses: dict[str, dict] = {}
    total = len(watchlist or {})
    if not total:
        return analyses
    workers = max(1, min(int(workers), 8))
    max_wallets = (FULL_SCAN_MAX_WALLETS if max_wallets is None
                   else int(max_wallets))

    store = (history_store if isinstance(history_store, dict)
             else load_holder_history())

    def _job(item):
        mint, meta = item
        try:
            token_slot = ((store.get("tokens") or {}).get(mint) or {})
            cohort = token_slot.get("cohort") or {}
            addrs = list((cohort.get("balances") or {}).keys())
            tracked = tracked_wallet_addresses(token_slot.get("alert_state"))
            analysis = analyze_token(
                mint, (meta or {}).get("symbol") or "?",
                dust_limit=dust_limit, max_wallets=max_wallets,
                fetch_market=True, holder_source=holder_source,
                cohort_addrs=addrs, tracked_wallet_addrs=tracked)
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
    parser.add_argument("--max-wallets", type=int, default=None,
                        help="maks holder dianalisis per token (default: "
                             f"FULL = {FULL_SCAN_MAX_WALLETS:,} — semua "
                             "halaman sampai habis, sama seperti tombol "
                             "scan FULL manual)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--holder-source", choices=("gmgn", "helius",
                                                    "auto"), default=None,
                        help="sumber holder; default ikut config/env "
                             "(auto = Helius dulu, fallback GMGN)")
    parser.add_argument("--no-push", action="store_true",
                        help="hanya tulis status lokal")
    parser.add_argument("--telegram-test", action="store_true",
                        help="kirim satu pesan test Telegram, lalu scan normal")
    args = parser.parse_args(argv)

    if args.telegram_test:
        delivery = send_test_alert()
        if delivery.get("ok"):
            print("Telegram test alert: terkirim")
        elif delivery.get("skipped"):
            print("Telegram test alert: dilewati (credential belum tersedia)")
        else:
            print(f"WARN: Telegram test alert gagal: "
                  f"{delivery.get('error') or 'unknown error'}",
                  file=sys.stderr)

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
    max_wallets = (FULL_SCAN_MAX_WALLETS if args.max_wallets is None
                   else int(args.max_wallets))
    print(f"Holder scanner: tokens={len(watchlist)} "
          f"time={datetime.now(timezone.utc).isoformat()} "
          f"max_wallets={max_wallets} (FULL) "
          f"holder_source={args.holder_source or 'config(auto)'}")

    started = time.monotonic()
    started_wall = int(time.time())
    # Urutan pemulihan state: file lokal runner (kosong di Actions) -> backup
    # durable holder_history.json.gz di ref holder-live (menang bila timestamp
    # seri, karena itulah akumulasi run sebelumnya) -> titik/state dari snapshot
    # dashboard sebagai jaring kedua (juga satu-satunya sumber bila backup belum
    # pernah dibuat, mis. snapshot format lama yang masih membawa peta wallet).
    durable = pull_holder_history()
    store = merge_stores(load_holder_history(), durable or {})
    store = seed_from_status(store, load_holder_status(force_refresh=True))
    print(f"Store holder: tokens={len(store.get('tokens') or {})} "
          f"backup={'ada' if durable else 'tidak ada'}")
    analyses = scan_watchlist(
        watchlist, dust_limit=args.dust_limit,
        max_wallets=max_wallets,
        workers=args.workers,
        holder_source=args.holder_source,
        history_store=store)

    if analyses:
        # Rules read the old anchors first. process_holder_alerts mutates only
        # alert state; ingest_many writes that state together with the newest
        # history point afterwards.
        # Konteks volume/harga/volatilitas ditarik lazy (hanya bila ada
        # kandidat sinyal) dan di-memo per token untuk seluruh run ini.
        contexts: dict = {}
        provider = market_context_provider(cache=contexts,
                                           daily_loader=load_daily_effort)
        # Scope rule ⚡ EARLY DUMP = token pool (source=meteora / Chart LP).
        # Watchlist saat ini belum punya pool address (keterbatasan: pesan
        # early dump cron tidak menyertakan link 🌊 Meteora/🦅 HawkFi).
        lp_mints = set(split_watchlist(watchlist)[0])
        deliveries = process_holder_alerts(analyses, store,
                                           context_provider=provider,
                                           lp_mints=lp_mints)
        # detail=True (sejak 2026-09-05): cron scan FULL, jadi rekaman
        # baseline (titik awal holder analytic sejak token masuk watchlist),
        # latest_detail, dan kronologi dibuat/diperbarui otomatis — tidak
        # lagi hanya titik ringkas. Baseline tetap immutable.
        history = ingest_many(analyses, store=store, detail=True)
        status = publish_holder_status(
            analyses, watchlist, push=not args.no_push,
            history_store=history, contexts=contexts)
        # Backup store penuh (peta wallet alert/kohort, baseline FULL,
        # kronologi) — tidak lagi ikut snapshot dashboard yang dirampingkan.
        backup = publish_holder_history(history, push=not args.no_push)
        sent_alerts = sum(1 for item in deliveries
                          if (item.get("delivery") or {}).get("ok"))
        unverified = sum(1 for item in deliveries
                         if not ((item.get("event") or {}).get("volume_check")
                                 or {}).get("verified", True))
        rejected = 0
        fetch_ms = 0
        for mint in analyses:
            slot = (store.get("tokens") or {}).get(mint) or {}
            state = slot.get("alert_state") or {}
            rejected += sum(1 for row in (state.get("rejected_signals") or [])
                            if isinstance(row, dict)
                            and int(row.get("ts") or 0) >= started_wall)
            fetch_ms += int((contexts.get(mint) or {}).get("fetch_ms") or 0)
        # Backup store tidak boleh membuat cron merah (data dashboard lebih
        # penting), tapi kegagalannya harus kelihatan di log.
        if backup.get("pushed"):
            backup_label = f"ok {backup.get('bytes') or 0}B"
            if backup.get("pruned"):
                backup_label += f" pruned={len(backup['pruned'])}"
            if backup.get("over_budget"):
                backup_label += " OVER-BUDGET"
        elif args.no_push:
            backup_label = "skip (--no-push)"
        else:
            backup_label = f"GAGAL ({backup.get('error') or 'unknown'})"
            print(f"WARN: backup holder_history gagal: "
                  f"{backup.get('error') or 'unknown'}", file=sys.stderr)
        print(f"Holder scan selesai: analyzed={len(analyses)} "
              f"history={len((history or {}).get('tokens') or {})} "
              f"alerts={sent_alerts}/{len(deliveries)} "
              f"unverified={unverified} rejected={rejected} "
              f"konteks={len(contexts)} token ({fetch_ms} ms) "
              f"backup={backup_label} "
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

    # --- Robinhood Chain: watchlist terpisah (EVM, chain id 4663) -----------
    # Scan best-effort: kegagalan jaringan Robinhood tidak boleh membuat cron
    # Solana mati (data dashboard Solana lebih penting dari card tambahan).
    try:
        rh_watch = robinhood_watchlist.load_watchlist()
        if rh_watch:
            rh_store = robinhood_watchlist.load_history()
            rh_analyses = robinhood_watchlist.scan_watchlist(
                rh_watch, history_store=rh_store,
                max_wallets=max_wallets, workers=args.workers)
            if rh_analyses:
                rh_contexts: dict = {}
                # Konteks pasar memakai data DexScreener yang sudah disuntik
                # analysis["market"]; geckoterminal/networks Solana tidak
                # dipakai untuk chain EVM, jadi seluruh fetch dimatikan.
                rh_provider = market_context_provider(fetch=False,
                                                      cache=rh_contexts)
                process_holder_alerts(rh_analyses, rh_store,
                                      context_provider=rh_provider)
                rh_status = robinhood_watchlist.publish_scan(
                    rh_analyses, rh_watch, history_store=rh_store,
                    push=not args.no_push, contexts=rh_contexts)
                rh_ok = sum(1 for item in rh_analyses.values()
                            if (item.get("holders") or {}).get("total_fetched"))
                print(f"Robinhood scan selesai: tokens={len(rh_analyses)} "
                      f"fetched={rh_ok}/{len(rh_analyses)} "
                      f"updated={rh_status.get('updated_at')}")
            else:
                print("Robinhood scan selesai: tidak ada token berhasil")
        else:
            print("Robinhood scan dilewati: watchlist kosong")
    except Exception as exc:  # noqa: BLE001 - best-effort
        print(f"WARN: Robinhood scanner gagal: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
