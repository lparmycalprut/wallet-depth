#!/usr/bin/env python3
"""Scanner holder **lane LP saja**: Chart LP Meteora + Robinhood LP.

Dirampingkan **2026-09-07** (permintaan user: "rampingkan dan fokuskan ke
holder scan untuk meteora dan robinhood saja agar fungsi berjalan dengan
normal … semua pencatatan lain tidak usah dilakukan yang tidak perlu").

Yang dikerjakan tiap run (±5 menit):

1. **Chart LP Meteora** — token ``source=meteora`` di ``watchlist.json``
   (Solana, holder via Helius DAS, fallback GMGN);
2. **Robinhood LP** — entri non-``regular`` di ``watchlist_robinhood.json``
   (chain EVM Robinhood id 4663, holder via Blockscout);
3. hitung holder real vs dust + dust % marketcap + mid-tier Crab/Fish, lalu
   evaluasi **satu-satunya** notifikasi — ⚡ EARLY DUMP TERJADI - GANTI WIDE
   RANGE, dikirim tiap dust % MC naik ≥ 0,02% dari angka saat token masuk
   watchlist (rule ambang 0,06% MC / 🔔 HIGH DROP / eskalasi EXIT-CUTLOSS
   DIGANTI 2026-09-13). Konteks pasar untuk baris
   pelengkap pesan ditarik **lazy** — hanya untuk token yang dinotifikasi,
   jadi run tenang tidak menambah satu pun request);
4. catat **satu titik** per token ke store history, publish snapshot dashboard
   (``holder_status.json`` / ``holder_status_robinhood.json`` di ref
   ``holder-live``) + backup durable store.

Yang **tidak** lagi dikerjakan cron (tetap tersedia sebagai scan manual di
dashboard):

- **watchlist biasa** (Solana non-LP & Robinhood ``source=regular``): slot
  4 jam, catch-up run telat, dan bootstrap token baru dihapus dari jalur cron;
- pencatatan yang ikut lane itu: ``merge_status`` (mewariskan baris token
  biasa ke snapshot), pembacaan toggle Telegram watchlist biasa
  (``alert_settings.regular_telegram_enabled``), dan token lama di backup
  durable — ``publish_holder_history(..., keep_mints=…)`` hanya men-push
  token watchlist LP aktif, bukan 81 token watchlist lama (±2,1 MB tiap 5
  menit).

Yang **dibaca** cron dari ``alert_settings.json`` (ref ``holder-live``, satu
request GitHub per run — di-cache modulnya sendiri): ``muted_mints`` = token
yang toggle alert-nya dimatikan user dari dashboard (tombol 🔔/🔕 per baris
watchlist Meteora/Robinhood, 2026-09-11). Token itu tetap di-scan + marker
``early_dump`` tetap dimajukan; hanya pengiriman Telegram-nya dilewati
(``mute_mints``), jadi cron dan dashboard menghormati pilihan yang sama.

Scan FULL (baseline immutable + kronologi wallet antar-scan) tidak
dijadwalkan cron lagi; jalankan manual bila perlu::

    python scripts/scan_holders.py --full          # kedua lane LP, detail=True

Ritme ±5 menit dipegang workflow ``.github/workflows/daily-effort.yml``:
``schedule: */5`` (best-effort, GitHub bisa men-throttle) + **chain dispatch**
di akhir tiap run (langkah itu melewati dispatch bila masih ada run
mengantre/berjalan, supaya antrean concurrency ``holder-scanner`` tidak
menumpuk dan saling membatalkan). Run ganda yang lolos (chain menabrak
schedule) disaring gate :data:`MIN_RUN_GAP_SEC` di :func:`main` — run kedua
keluar tanpa kerja. Katup hemat kuota Helius: ``LP_SCAN_RUN_MULTIPLIER=2|3``
(env) menahan lane **Solana** sampai tiap N run; lane Robinhood tidak
terpengaruh karena chain-nya Blockscout, bukan Helius.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import alert_settings
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
import robinhood_holders
import robinhood_watchlist
from telegram_alerts import (process_holder_alerts, send_test_alert,
                             tracked_wallet_addresses)
from watchlist import load_watchlist

# --- Kadens: kedua lane LP di-scan tiap run (±5 menit) ----------------------
RUN_SCAN_INTERVAL_SEC = 5 * 60          # kadens cron/chain dispatch
RH_FAST_SCAN_INTERVAL_SEC = RUN_SCAN_INTERVAL_SEC   # Robinhood LP: tiap run
METEORA_LP_SCAN_INTERVAL_SEC = RUN_SCAN_INTERVAL_SEC   # Chart LP Meteora
# Hemat kuota Helius: >1 = scan **Solana** hanya pada tiap N run (gate slot di
# bawah). Robinhood tidak terpengaruh — chain-nya Blockscout, bukan Helius.
LP_SCAN_RUN_MULTIPLIER = max(1, int(os.environ.get("LP_SCAN_RUN_MULTIPLIER",
                                                    "1") or 1))


def lp_slot_sec() -> int:
    """Panjang satu **slot scan LP** = interval run × multiplier.

    Berbentuk fungsi, bukan konstanta, supaya override ``LP_SCAN_RUN_MULTIPLIER``
    (env di runner / patch saat uji) langsung dipakai gerbang slot. Konstanta
    ``LP_SCAN_INTERVAL_SEC`` di bawah = nilai pada saat import (untuk laporan
    & uji kadens).
    """
    return RUN_SCAN_INTERVAL_SEC * max(1, int(LP_SCAN_RUN_MULTIPLIER))


LP_SCAN_INTERVAL_SEC = lp_slot_sec()
# Run ganda chain-dispatch + schedule dalam satu slot dicek dari umur
# snapshot publish terakhir: lebih muda dari ini = skip tanpa kerja. Wajib
# lebih kecil dari kadens run (5 menit) supaya lane LP tidak ikut dibungkam
# gate-nya sendiri — 4 menit masih cukup lebar untuk menyaring tabrakan
# chain dispatch + schedule.
MIN_RUN_GAP_SEC = RUN_SCAN_INTERVAL_SEC - 60


def lp_slot_due(now_ts: int, last_scan_ts: int = 0) -> bool:
    """True bila run ini berada di **slot LP** yang berbeda.

    Default (``LP_SCAN_RUN_MULTIPLIER=1``) membuat slot LP = slot run, jadi
    **setiap cron run** menarik Helius — kedua lane LP di-scan tiap ±5 menit.
    Yang tidak due hanyalah run KEDUA dalam slot yang sama (chain dispatch
    menabrak schedule) — itu memang yang diinginkan. Gate berbasis **nomor
    slot** (bukan umur titik) ini tetap self-healing:

    - run yang terlewat / publish gagal → ``updated_at`` tidak maju, jadi run
      berikutnya otomatis mengerjakan LP;
    - bila kuota Helius mulai ketat, ``LP_SCAN_RUN_MULTIPLIER=2``/``3``
      memaksa scan Solana hanya tiap 10/15 menit tanpa menyentuh kode.
    """
    slot = lp_slot_sec()
    last = int(last_scan_ts or 0)
    if last <= 0:
        return True                     # pertama kali / belum ada snapshot
    return (max(0, int(now_ts)) // slot) > (last // slot)


def recently_published(status, now_ts: int,
                       min_gap: int = MIN_RUN_GAP_SEC) -> bool:
    """True bila snapshot publish terakhir lebih muda dari ``min_gap``.

    Dipakai sebagai gate run ganda: chain dispatch + schedule bisa
    menumbangkan dua run hampir bersamaan; yang kedua cukup keluar tanpa
    kerja (snapshot dashboard justru bukti run pertama sudah selesai).
    """
    try:
        updated = int((status or {}).get("updated_at") or 0)
    except (TypeError, ValueError):
        updated = 0
    return updated > 0 and 0 <= int(now_ts) - updated < min_gap


def scan_watchlist(watchlist: dict, *, dust_limit: float | None = None,
                   max_wallets: int | None = None,
                   workers: int = 4, progress=None,
                   holder_source: str | None = None,
                   history_store: dict | None = None,
                   detail: bool = True) -> dict:
    """Analisis semua token yang diberikan; return {mint: analysis}.

    ``holder_source``: ``gmgn`` / ``helius`` / ``auto`` — default
    ``None`` = ikuti config/env (default ``auto`` = Helius dulu).

    ``max_wallets`` default = ``FULL_SCAN_MAX_WALLETS`` (100.000): cron
    memakai batas atas yang sama dengan tombol scan FULL di halaman Holder,
    jadi holder diambil sampai habis (bukan sampel 3000).
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
            addrs = list((cohort.get("balances") or {}).keys()) if detail else []
            tracked = (tracked_wallet_addresses(token_slot.get("alert_state"))
                       if detail else [])
            analysis = analyze_token(
                mint, (meta or {}).get("symbol") or "?",
                dust_limit=dust_limit, max_wallets=max_wallets,
                fetch_market=True, holder_source=holder_source,
                cohort_addrs=addrs, tracked_wallet_addrs=tracked,
                detail=detail)
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
    parser = argparse.ArgumentParser(
        description="Holder scan lane LP: Chart LP Meteora + Robinhood LP.")
    parser.add_argument("--dust-limit", type=float, default=None,
                        help="batas value USD dust (default 10)")
    parser.add_argument("--max-wallets", type=int, default=None,
                        help="maks holder Solana per token (Robinhood selalu FULL; "
                             "default: "
                             f"FULL = {FULL_SCAN_MAX_WALLETS:,} — semua "
                             "halaman sampai habis)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--holder-source", choices=("gmgn", "helius",
                                                    "auto"), default=None,
                        help="sumber holder; default ikut config/env "
                             "(auto = Helius dulu, fallback GMGN)")
    parser.add_argument("--full", action="store_true",
                        help="scan FULL: detail=True (baseline immutable + "
                             "kronologi wallet) + konfirmasi volume/harga "
                             "untuk kedua lane LP — default cron off")
    parser.add_argument("--ignore-gap", action="store_true",
                        help="lewati gate run ganda (dipakai dispatch "
                             "manual saat token baru ditambahkan)")
    parser.add_argument("--no-push", action="store_true",
                        help="hanya tulis status lokal")
    parser.add_argument("--telegram-test", action="store_true",
                        help="kirim satu pesan test Telegram, lalu scan normal")
    # Alias sementara untuk workflow lama yang masih mengirim ``--scope``
    # (berkas workflow tidak bisa ditulis bot — lihat DEPLOY.md). ``all``
    # diperlakukan sebagai ``--full``; nilai lain diabaikan karena cron hanya
    # punya satu lane. Hapus setelah ``daily-effort-5menit.yml`` terpasang.
    parser.add_argument("--scope", choices=("auto", "fast", "all"),
                        default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.scope:
        alias = "; dianggap --full" if args.scope == "all" else "; diabaikan"
        print(f"WARN: --scope {args.scope} sudah tidak dipakai (cron hanya "
              f"lane LP sejak 2026-09-07){alias}. Perbarui workflow ke "
              "input full_scan.", file=sys.stderr)
        if args.scope == "all":
            args.full = True

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

    # Lane Solana = Chart LP Meteora saja; watchlist biasa tidak di-scan cron.
    watchlist = load_watchlist()
    lp_watch, _regular_watch = split_watchlist(watchlist)
    try:
        from core import get_helius_keys
        helius_ok = bool(get_helius_keys())
    except Exception:  # noqa: BLE001
        helius_ok = False
    if lp_watch and not helius_ok:
        print("WARN: HELIUS_API_KEY tidak ada — holder hanya via GMGN "
              "(sering diblokir di runner Actions → dust kosong). "
              "Set secret HELIUS_API_KEY di repo.", file=sys.stderr)
    max_wallets = (FULL_SCAN_MAX_WALLETS if args.max_wallets is None
                   else int(args.max_wallets))
    print(f"Holder scanner (lane LP): meteora={len(lp_watch)} "
          f"time={datetime.now(timezone.utc).isoformat()} "
          f"max_wallets={max_wallets} "
          f"holder_source={args.holder_source or 'config(auto)'} "
          f"full={'ya' if args.full else 'tidak'} "
          f"(LP tiap run ±{RUN_SCAN_INTERVAL_SEC // 60} menit"\
          + (f", Solana tiap {lp_slot_sec() // 60} menit"
             if lp_slot_sec() > RUN_SCAN_INTERVAL_SEC else "") + ")")

    started = time.monotonic()
    started_wall = int(time.time())
    # Urutan pemulihan state: file lokal runner (kosong di Actions) -> backup
    # durable holder_history.json.gz di ref holder-live (menang bila timestamp
    # seri, karena itulah akumulasi run sebelumnya) -> titik/state dari snapshot
    # dashboard sebagai jaring kedua.
    durable = pull_holder_history()
    store = merge_stores(load_holder_history(), durable or {})
    # Snapshot publish terakhir dipakai dua kali: seed store + gate run ganda.
    current_status = load_holder_status(force_refresh=True)
    store = seed_from_status(store, current_status)
    print(f"Store holder: tokens={len(store.get('tokens') or {})} "
          f"backup={'ada' if durable else 'tidak ada'}")
    # Toggle alert per token (tombol 🔔/🔕 di dashboard, 2026-09-11): satu
    # bacaan untuk kedua lane. Token yang dimatikan tetap di-scan + marker
    # 🚨 tetap dimajukan; hanya pengirimannya yang dilewati.
    muted_alerts = alert_settings.muted_mints(force_refresh=True)
    print(f"Toggle alert per token: {len(muted_alerts)} dimatikan"
          + (f" ({', '.join(sorted(muted_alerts))[:120]})"
             if muted_alerts else ""))

    # Gerbang slot LP berbasis nomor slot dengan anchor timestamp snapshot
    # terakhir, supaya run yang terlewat/publish gagal mengejar.
    lp_slot = lp_slot_due(started_wall,
                          int((current_status or {}).get("updated_at") or 0))
    due = dict(lp_watch) if (args.full or lp_slot) else {}
    if due and not args.ignore_gap \
            and recently_published(current_status, started_wall):
        print(f"Scan Meteora dilewati: snapshot terbaru < "
              f"{MIN_RUN_GAP_SEC // 60} menit lalu (run ganda "
              "chain dispatch + schedule).")
        due = {}
    print(f"Rencana scan Meteora LP: watchlist={len(lp_watch)} "
          f"due={len(due)} slot_lp={'ya' if lp_slot else 'bukan'}")

    analyses = {}
    if due:
        analyses = scan_watchlist(
            due, dust_limit=args.dust_limit,
            max_wallets=max_wallets,
            workers=args.workers,
            holder_source=args.holder_source,
            history_store=store, detail=args.full)

    exit_code = 0
    if analyses:
        # The rule reads the old marker first. process_holder_alerts mutates
        # only alert state; ingest_many writes that state together with the
        # newest history point afterwards. Konteks pasar (volume/harga) ditarik
        # lazy — hanya untuk token yang benar-benar akan dinotifikasi — dan
        # di-memo per token, jadi run yang tenang tidak menambah request.
        contexts: dict = {}
        provider = None
        if args.full:
            provider = market_context_provider(cache=contexts,
                                               daily_loader=load_daily_effort)
        # ⚡ EARLY DUMP = satu-satunya notifikasi, scope-nya seluruh lane yang
        # di-scan run ini (patokan 0,02% per token diambil dari history).
        # advance_anchors: peta wallet (anchor ±4 jam) hanya digeser scan FULL.
        deliveries = process_holder_alerts(
            analyses, store, context_provider=provider,
            mute_mints=alert_settings.mutes_for(analyses),
            watchlist_meta=lp_watch, advance_anchors=args.full)
        history = ingest_many(analyses, store=store, detail=args.full)
        status = publish_holder_status(
            analyses, lp_watch, push=not args.no_push,
            history_store=history, contexts=contexts)
        # Backup durable dibatasi token watchlist LP aktif: token lama yang
        # sudah tidak di-scan tidak perlu di-push ulang tiap 5 menit.
        backup = publish_holder_history(history, push=not args.no_push,
                                       keep_mints=set(lp_watch))
        sent_alerts = sum(1 for item in deliveries
                          if (item.get("delivery") or {}).get("ok"))
        if backup.get("pushed"):
            backup_label = f"ok {backup.get('bytes') or 0}B"
            if backup.get("dropped_tokens"):
                backup_label += f" tanpa {backup['dropped_tokens']} token lama"
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
        print(f"Meteora scan selesai: analyzed={len(analyses)} "
              f"history={len((history or {}).get('tokens') or {})} "
              f"alerts={sent_alerts}/{len(deliveries)} "
              f"konteks={len(contexts)} token "
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
            exit_code = 2
    elif due:
        publish_holder_status({}, lp_watch, push=not args.no_push)
        print("Meteora scan selesai: tidak ada token yang berhasil dianalisis")
        return 2
    else:
        print("Meteora scan dilewati: tidak ada token LP jatuh tempo run ini.")
    if not args.no_push and due and last_publish_result().get("ok") is False:
        print(f"ERROR: publish holder_status gagal: "
              f"{last_publish_result().get('error')}", file=sys.stderr)
        return 3

    # --- Robinhood Chain: lane LP watchlist terpisah (EVM, chain id 4663) ----
    # Scan best-effort: kegagalan jaringan Robinhood tidak boleh membuat cron
    # Solana mati. Entri ``source=regular`` (slot 4 jam) tidak di-scan cron
    # sejak 2026-09-07.
    rh_done = 0
    rh_due = 0
    try:
        rh_watch = robinhood_watchlist.load_watchlist()
        rh_lp, rh_regular = robinhood_watchlist.split_robinhood_watchlist(
            rh_watch)
        if rh_lp:
            rh_status_now = robinhood_watchlist.load_status(force_refresh=True)
            rh_store = robinhood_watchlist.load_history()
            rh_due = len(rh_lp)
            rh_targets = dict(rh_lp)
            if not args.ignore_gap \
                    and recently_published(rh_status_now, started_wall):
                print(f"Scan Robinhood dilewati: snapshot terbaru < "
                      f"{MIN_RUN_GAP_SEC // 60} menit lalu (run ganda "
                      "chain dispatch + schedule).")
                rh_targets = {}
            rh_n_keys = len(robinhood_holders.get_pro_api_keys())
            print(f"Rencana scan Robinhood LP: watchlist={rh_due} "
                  f"due={len(rh_targets)} "
                  f"(biasa {len(rh_regular)} token tidak di-scan cron) "
                  f"blockscout_pro_keys={rh_n_keys}")
            if rh_targets and not rh_n_keys:
                print("WARN: BLOCKSCOUT_API_KEY(S) tidak ada — holder "
                      "Robinhood lewat instance publik yang sering menjawab "
                      "403 bot-protection di runner Actions. Set secret "
                      "BLOCKSCOUT_API_KEYS (koma) di repo.", file=sys.stderr)
            if rh_targets:
                rh_analyses = robinhood_watchlist.scan_watchlist(
                    rh_targets, history_store=rh_store,
                    # Blockscout sorts richest first: a 3k sample can omit
                    # the entire dust tail. Keep RH at the dedicated scan cap;
                    # the workflow --max-wallets budget is for Solana only.
                    max_wallets=FULL_SCAN_MAX_WALLETS, workers=args.workers,
                    detail=args.full)
                if rh_analyses:
                    rh_contexts: dict = {}
                    rh_provider = None
                    if args.full:
                        # Konteks pasar memakai data DexScreener yang sudah
                        # disuntik analysis["market"]; geckoterminal/networks
                        # Solana tidak dipakai untuk chain EVM.
                        rh_provider = market_context_provider(fetch=False,
                                                              cache=rh_contexts)
                    process_holder_alerts(
                        rh_analyses, rh_store,
                        context_provider=rh_provider,
                        mute_mints=alert_settings.mutes_for(rh_analyses),
                        watchlist_meta=rh_watch,
                        advance_anchors=args.full)
                    rh_status = robinhood_watchlist.publish_scan(
                        rh_analyses, rh_watch, history_store=rh_store,
                        push=not args.no_push, contexts=rh_contexts,
                        detail=args.full, keep_mints=set(rh_watch))
                    rh_done = sum(1 for item in rh_analyses.values()
                                  if (item.get("holders") or {}).get(
                                      "total_fetched"))
                    rh_blocked = sum(1 for item in rh_analyses.values()
                                     if (item.get("holders") or {}).get(
                                         "blocked"))
                    rh_routes = sorted({
                        robinhood_holders.route_label(
                            str(((item.get("holders") or {}).get("source"))
                                or "")) or "?"
                        for item in rh_analyses.values()
                        if (item.get("holders") or {}).get("total_fetched")})
                    print(f"Robinhood scan selesai: tokens={len(rh_analyses)} "
                          f"fetched={rh_done}/{len(rh_analyses)} "
                          f"updated={rh_status.get('updated_at')}"
                          + (f" route={'/'.join(rh_routes)}"
                             if rh_routes else ""))
                    # Ringkasan pool key PRO (label key#N + sisa kredit dari
                    # header x-credits-remaining) — key aslinya tidak dicetak.
                    rh_keys_note = robinhood_holders.pro_key_summary()
                    if rh_keys_note:
                        print(rh_keys_note)
                    if rh_blocked:
                        # 403 bot-protection instance publik: nyatakan
                        # terang di log Actions + cara memperbaikinya.
                        if robinhood_holders.pro_keys_configured():
                            remedy = ("Semua key PRO API ditolak / kredit "
                                      "hariannya habis — cek dashboard "
                                      f"{robinhood_holders.BLOCKSCOUT_KEY_URL}"
                                      " atau tambah key akun lain ke secret "
                                      "BLOCKSCOUT_API_KEYS.")
                        else:
                            remedy = ("Pasang secret BLOCKSCOUT_API_KEY "
                                      "(key gratis: "
                                      f"{robinhood_holders.BLOCKSCOUT_KEY_URL}"
                                      ") supaya scan lewat PRO API.")
                        print(f"WARN: Blockscout menolak scan "
                              f"{rh_blocked}/{len(rh_analyses)} token "
                              f"(HTTP 403 bot-protection). {remedy}",
                              file=sys.stderr)
                else:
                    print("Robinhood scan selesai: tidak ada token berhasil")
        else:
            print("Robinhood scan dilewati: watchlist LP kosong")
    except Exception as exc:  # noqa: BLE001 - best-effort
        print(f"WARN: Robinhood scanner gagal: {exc}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
