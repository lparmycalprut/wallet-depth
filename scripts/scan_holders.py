#!/usr/bin/env python3
"""Scanner analisa holder (dust + kohort) untuk watchlist.

Cadens dua tingkat (permintaan user 2026-09-05):

- **Watchlist LP** — token pool Meteora (Chart LP, ``source=meteora``) dan
  watchlist **Robinhood LP** — di-scan **tiap ±15 menit**
  (:data:`FAST_SCAN_INTERVAL_SEC`) supaya exit LP bisa lebih awal. Selama
  dust % MC token LP berada di atas 0,1%, pengingat ⚡ Telegram dikirim
  ulang **tiap scan** sampai token dihapus dari watchlist LP atau
  dipindah ke watchlist biasa.
- **Watchlist biasa** (Solana non-LP + Robinhood biasa) tetap **tiap ±4
  jam** (:data:`REGULAR_SCAN_INTERVAL_SEC`): penuh di slot 4 jam (slot 15
  menit dengan indeks % 16 == 0) plus catch-up bila datanya lebih tua dari
  :data:`REGULAR_CATCHUP_SEC` (run telat) dan bootstrap untuk token yang
  belum punya titik history sama sekali. Rule 🔔 HIGH DROP berlaku di
  scope ini: titik acuan = **hold % MC terbesar** yang pernah tercatat;
  dust % MC yang turun >= 50% dari titik high mengirim alert.

Untuk setiap token yang discan:

1. ambil daftar holder (Helius DAS dulu — ``auto`` — fallback GMGN),
2. pisahkan real vs dust, hitung dust % marketcap + mid-tier Crab/Fish,
3. evaluasi alert Telegram terhadap snapshot rolling ~4 jam dan snapshot
   awal **sebelum** snapshot terbaru ditulis; kandidat yang lolos ambang dust
   masih harus dikonfirmasi volume + harga + volatilitas (konteks pasar
   ditarik **lazy**, hanya untuk token yang punya kandidat, jadi scan tenang
   tidak menambah satu pun request),
4. catat **titik perubahan** ke ``holder_history.json`` (titik mentah per
   run; grafik memakai bucket 4 jam); cron scan **FULL** + ``detail=True``:
   scan pertama setelah token masuk watchlist menjadi titik awal holder
   analytic (``baseline`` immutable), lalu tiap run berikutnya memperbarui
   ``latest_detail`` + interval **kronologi**,
5. tulis ``holder_status.json`` lokal & publish ke branch ``holder-live``.
   Run cepat **merge**: token watchlist biasa diwariskikan dari snapshot
   sebelumnya (``publish_holder_status(..., merge_status=...)``) supaya
   dashboard tidak kehilangan baris di antara dua run 4 jam.

Dijalankan GitHub Actions dengan kadens run **±5 menit** sejak 2026-09-06
(watchlist **Robinhood LP** di-scan tiap run): workflow memakai
``schedule: */5`` (best-effort, GitHub bisa men-throttle sampai ±2 jam — lihat
DEPLOY.md) plus **chain dispatch** (tiap run men-dispatch run berikutnya
setelah tidur sampai batas 5 menit berikutnya). Run ganda (chain + schedule)
dicek gate :data:`MIN_RUN_GAP_SEC` di :func:`main` dan dilewati tanpa kerja.

Karena hanya Robinhood yang diminta dipercepat, **Chart LP Meteora** (Solana)
tetap di-scan pada **slot ±15 menit**: run di luar slot itu tidak menarik
Helius sama sekali (budget rate-limit tidak berubah), hanya card Robinhood
yang bekerja. Watchlist biasa (Solana & Robinhood biasa) tetap slot **4 jam**.
Scope bisa dipaksa lewat ``--scope all`` (semua token) atau ``--scope fast``
(hanya LP, tanpa gate slot).
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
from holder_history import (FULL_SCAN_MAX_WALLETS, history_for_mint,
                            ingest_many, load_holder_history, merge_stores,
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

# --- Cadens tiga jalur (2026-09-06: Robinhood LP dipercepat ke 5 menit) -----
# Watchlist Robinhood LP diminta user di-scan **tiap ±5 menit** "supaya exit
# bisa lebih awal". Karena cron hanya punya satu jam dinding, yang berubah
# adalah **kadens run** (workflow chain-dispatch): tiap 5 menit. Lane lain
# tetap seperti semula, jadi beban Helius (Solana) dan Telegram tidak naik 3×.
RH_FAST_SCAN_INTERVAL_SEC = 5 * 60      # Robinhood LP: tiap run
RUN_SCAN_INTERVAL_SEC = RH_FAST_SCAN_INTERVAL_SEC  # kadens cron/chain dispatch
METEORA_LP_SCAN_INTERVAL_SEC = 15 * 60  # Chart LP Meteora (Solana): slot 15 mnt
REGULAR_SCAN_INTERVAL_SEC = 4 * 3600    # watchlist biasa: tetap 4 jam
# Alias lama: "jalur cepat" sekarang = lane Robinhood (tiap run).
FAST_SCAN_INTERVAL_SEC = RH_FAST_SCAN_INTERVAL_SEC
REGULAR_SLOTS = (REGULAR_SCAN_INTERVAL_SEC // RUN_SCAN_INTERVAL_SEC)  # 48
# Token biasa yang datanya lebih tua dari ini ikut di-scan meski bukan slot
# 4 jam (catch-up run telat/terlewat); juga jadi ambang bootstrap token baru.
REGULAR_CATCHUP_SEC = REGULAR_SCAN_INTERVAL_SEC - RUN_SCAN_INTERVAL_SEC
# Run ganda chain-dispatch + schedule dalam satu slot dicek dari umur
# snapshot publish terakhir: lebih muda dari ini = skip tanpa kerja. Wajib
# lebih kecil dari kadens run (5 menit) supaya lane Robinhood tidak ikut
# dibungkam — 4 menit dipilih agar tabrakan chain+schedule tetap ter-bitih.
MIN_RUN_GAP_SEC = RUN_SCAN_INTERVAL_SEC - 60


def regular_slot_due(now_ts: int) -> bool:
    """True bila ``now_ts`` jatuh di slot **4 jam** (slot 5 menit ke-48)."""
    return (max(0, int(now_ts)) // RUN_SCAN_INTERVAL_SEC) % REGULAR_SLOTS == 0


def lp_slot_due(now_ts: int, last_scan_ts: int = 0) -> bool:
    """True bila run ini berada di **slot 15 menit** yang berbeda.

    Lane Chart LP Meteora (Solana) sengaja TIDAK ikut dipercepat ke 5 menit:
    setiap scan Solana menarik Helius sampai 100 ribu wallet. Gate-nya adalah
    nomor slot 15 menit terakhir kali snapshot dipublish (:func:`main`
    memakai ``updated_at`` snapshot), jadi:

    - run di tengah slot (5/10 menit setelah scan) tidak bekerja sama sekali;
    - run yang **terlewat atau gagal** tetap mengerjakan LP pada run
      berikutnya, karena ``updated_at`` tidak maju selama publish gagal.
    """
    last = int(last_scan_ts or 0)
    if last <= 0:
        return True
    return (max(0, int(now_ts)) // METEORA_LP_SCAN_INTERVAL_SEC) > (
        last // METEORA_LP_SCAN_INTERVAL_SEC)


def token_needs_scan(store: dict, mint: str, now_ts: int, *,
                     max_age_sec: int = REGULAR_CATCHUP_SEC) -> bool:
    """Token watchlist biasa due bila belum pernah discan / datanya menua.

    Bootstrap: token yang baru masuk watchlist (belum punya titik history)
    ikut scan run berikutnya — tidak perlu menunggu slot 4 jam. Catch-up:
    titik terakhir lebih tua dari ``max_age_sec`` (default
    :data:`REGULAR_CATCHUP_SEC`, 3 jam 55 menit) → scan pada run berikutnya
    supaya run telat/terlewat tetap pulih.
    """
    rows = [row for row in (history_for_mint(store, mint) or [])
            if isinstance(row, dict) and int(row.get("ts") or 0) > 0]
    if not rows:
        return True
    latest = max(int(row.get("ts") or 0) for row in rows)
    return latest <= 0 or (int(now_ts) - latest) >= int(max_age_sec)


def build_scan_plan(watchlist: dict, store: dict, now_ts: int, *,
                    lp_slot: bool = True) -> dict:
    """Pecah watchlist jadi scope LP (cepat) + biasa, lalu pilih yang due.

    Return ``{lp, regular, due, regular_slot, lp_slot}`` — ``due`` adalah dict
    token yang harus di-scan run ini (LP selama :func:`lp_slot_due` benar;
    biasa saat slot 4 jam / catch-up / bootstrap). ``lp_slot=False`` dipakai
    run di luar slot 15 menit: watchlist Meteora tidak di-scan, hanya token
    biasa yang genuinely due. Dispatch manual (``--scope fast|all``) melewati
    gate ini karena pemanggil yang memutuskan.
    """
    lp, regular = split_watchlist(watchlist)
    slot = regular_slot_due(now_ts)
    due = dict(lp) if lp_slot else {}
    if slot:
        due.update(regular)
    else:
        for mint, meta in regular.items():
            if token_needs_scan(store, mint, now_ts):
                due[mint] = meta
    return {"lp": lp, "regular": regular, "due": due,
            "regular_slot": slot, "lp_slot": lp_slot}


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
    parser.add_argument("--scope", choices=("auto", "fast", "all"),
                        default="auto",
                        help="auto = watchlist LP tiap run (±15 menit) + "
                             "watchlist biasa di slot 4 jam / catch-up; "
                             "fast = hanya LP; all = semua token")
    parser.add_argument("--ignore-gap", action="store_true",
                        help="lewati gate run ganda (dipakai dispatch "
                             "manual saat token baru ditambahkan)")
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
          f"holder_source={args.holder_source or 'config(auto)'} "
          f"scope={args.scope} "
          f"(Robinhood LP ±{RUN_SCAN_INTERVAL_SEC // 60} menit · Chart LP "
          f"Meteora ±{METEORA_LP_SCAN_INTERVAL_SEC // 60} menit · biasa ±"
          f"{REGULAR_SCAN_INTERVAL_SEC // 3600} jam)")

    started = time.monotonic()
    started_wall = int(time.time())
    # Urutan pemulihan state: file lokal runner (kosong di Actions) -> backup
    # durable holder_history.json.gz di ref holder-live (menang bila timestamp
    # seri, karena itulah akumulasi run sebelumnya) -> titik/state dari snapshot
    # dashboard sebagai jaring kedua (juga satu-satunya sumber bila backup belum
    # pernah dibuat, mis. snapshot format lama yang masih membawa peta wallet).
    durable = pull_holder_history()
    store = merge_stores(load_holder_history(), durable or {})
    # Snapshot publish terakhir dipakai tiga kali: seed store, gate run ganda,
    # dan dasar merge publish run cepat (token watchlist biasa diwariskan).
    current_status = load_holder_status(force_refresh=True)
    store = seed_from_status(store, current_status)
    print(f"Store holder: tokens={len(store.get('tokens') or {})} "
          f"backup={'ada' if durable else 'tidak ada'}")

    # Lane Solana (Chart LP Meteora) hanya jalan pada slot ±15 menit; anchor-
    # nya timestamp snapshot terakhir supaya run yang terlewat tetap mengejar.
    lp_slot = lp_slot_due(started_wall,
                          int((current_status or {}).get("updated_at") or 0))
    plan = build_scan_plan(watchlist, store, started_wall, lp_slot=lp_slot)
    if args.scope == "fast":
        due = dict(plan["lp"])
    elif args.scope == "all":
        due = dict(watchlist)
    else:
        due = plan["due"]
        if due and not args.ignore_gap \
                and recently_published(current_status, started_wall):
            print(f"Scan Solana dilewati: snapshot terbaru < "
                  f"{MIN_RUN_GAP_SEC // 60} menit lalu (run ganda "
                  "chain dispatch + schedule).")
            due = {}
    print(f"Rencana scan: LP={len(plan['lp'])} "
          f"biasa={len(plan['regular'])} due={len(due)} "
          f"slot_lp={'ya' if lp_slot else 'bukan'} "
          f"slot_4jam={'ya' if plan['regular_slot'] else 'bukan'}")

    if due:
        analyses = scan_watchlist(
            due, dust_limit=args.dust_limit,
            max_wallets=max_wallets,
            workers=args.workers,
            holder_source=args.holder_source,
            history_store=store)
    else:
        analyses = {}

    if analyses:
        # Rules read the old anchors first. process_holder_alerts mutates only
        # alert state; ingest_many writes that state together with the newest
        # history point afterwards.
        # Konteks volume/harga/volatilitas ditarik lazy (hanya bila ada
        # kandidat sinyal) dan di-memo per token untuk seluruh run ini.
        contexts: dict = {}
        provider = market_context_provider(cache=contexts,
                                           daily_loader=load_daily_effort)
        # Scope rule ⚡ EARLY DUMP = watchlist LP (source=meteora / Chart LP):
        # pengingat berulang selama dust % MC > 0,1% sampai token dihapus
        # dari watchlist LP atau dipindah ke watchlist biasa. Scope rule
        # 🔔 HIGH DROP = watchlist biasa: titik acuan = hold % MC terbesar;
        # turun >= 50% dari titik high mengirim alert.
        # Watchlist saat ini belum punya pool address (keterbatasan: pesan
        # early dump cron tidak menyertakan link 🌊 Meteora/🦅 HawkFi).
        deliveries = process_holder_alerts(
            analyses, store, context_provider=provider,
            lp_mints=set(plan["lp"]), high_mints=set(plan["regular"]),
            watchlist_meta=watchlist)
        # detail=True (sejak 2026-09-05): cron scan FULL, jadi rekaman
        # baseline (titik awal holder analytic sejak token masuk watchlist),
        # latest_detail, dan kronologi dibuat/diperbarui otomatis — tidak
        # lagi hanya titik ringkas. Baseline tetap immutable.
        history = ingest_many(analyses, store=store, detail=True)
        # Run cepat merge: token yang tidak ikut scan run ini (watchlist
        # biasa di luar slot 4 jam) diwariskan dari snapshot sebelumnya,
        # jadi dashboard tidak kehilangan baris di antara dua run 4 jam.
        merge_status = current_status if args.scope != "all" else None
        status = publish_holder_status(
            analyses, watchlist, push=not args.no_push,
            history_store=history, contexts=contexts,
            merge_status=merge_status)
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
              f"merged={'ya' if merge_status else 'tidak'} "
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
    elif due:
        publish_holder_status({}, watchlist, push=not args.no_push)
        print("Holder scan selesai: tidak ada token yang berhasil dianalisis")
        return 2
    else:
        print("Holder scan selesai: tidak ada token jatuh tempo run ini "
              "(watchlist LP kosong dan watchlist biasa belum due).")
    if not args.no_push and due and last_publish_result().get("ok") is False:
        print(f"ERROR: publish holder_status gagal: "
              f"{last_publish_result().get('error')}", file=sys.stderr)
        return 3

    # --- Robinhood Chain: watchlist terpisah (EVM, chain id 4663) -----------
    # Scan best-effort: kegagalan jaringan Robinhood tidak boleh membuat cron
    # Solana mati (data dashboard Solana lebih penting dari card tambahan).
    # Split (2026-09-05, kadens LP diubah 2026-09-06): **Robinhood LP** tiap
    # run = ±5 menit (pengingat > 0,1% MC berulang), **Robinhood biasa** tiap
    # ±4 jam (rule 🔔 HIGH DROP).
    try:
        rh_watch = robinhood_watchlist.load_watchlist()
        if rh_watch:
            rh_lp, rh_regular = \
                robinhood_watchlist.split_robinhood_watchlist(rh_watch)
            rh_status_now = robinhood_watchlist.load_status(
                force_refresh=True)
            rh_store = robinhood_watchlist.load_history()
            rh_due = dict(rh_lp)
            if args.scope == "all":
                # Dispatch scan_all: seluruh watchlist Robinhood.
                rh_due.update(rh_regular)
            elif args.scope != "fast" and regular_slot_due(started_wall):
                rh_due.update(rh_regular)
            else:
                for ca, meta in rh_regular.items():
                    if token_needs_scan(rh_store, ca, started_wall):
                        rh_due[ca] = meta
            if rh_due and not args.ignore_gap and args.scope == "auto" \
                    and recently_published(rh_status_now, started_wall):
                print(f"Scan Robinhood dilewati: snapshot terbaru < "
                      f"{MIN_RUN_GAP_SEC // 60} menit lalu (run ganda "
                      "chain dispatch + schedule).")
                rh_due = {}
            print(f"Rencana scan Robinhood: LP={len(rh_lp)} "
                  f"biasa={len(rh_regular)} due={len(rh_due)} "
                  f"(LP tiap run ±{RUN_SCAN_INTERVAL_SEC // 60} menit · "
                  f"biasa slot {REGULAR_SCAN_INTERVAL_SEC // 3600} jam)")
            if rh_due:
                rh_analyses = robinhood_watchlist.scan_watchlist(
                    rh_due, history_store=rh_store,
                    max_wallets=max_wallets, workers=args.workers)
                if rh_analyses:
                    rh_contexts: dict = {}
                    # Konteks pasar memakai data DexScreener yang sudah
                    # disuntik analysis["market"]; geckoterminal/networks
                    # Solana tidak dipakai untuk chain EVM, jadi seluruh
                    # fetch dimatikan.
                    rh_provider = market_context_provider(fetch=False,
                                                          cache=rh_contexts)
                    # Scope ⚡ EARLY DUMP = hanya subset **Robinhood LP**
                    # (pengingat berulang > 0,1% MC); scope 🔔 HIGH DROP =
                    # watchlist Robinhood biasa (titik high, turun >= 50%).
                    process_holder_alerts(
                        rh_analyses, rh_store,
                        context_provider=rh_provider,
                        lp_mints=set(rh_lp), high_mints=set(rh_regular),
                        watchlist_meta=rh_watch)
                    rh_status = robinhood_watchlist.publish_scan(
                        rh_analyses, rh_watch, history_store=rh_store,
                        push=not args.no_push, contexts=rh_contexts,
                        merge_status=(rh_status_now
                                      if args.scope != "all" else None))
                    rh_ok = sum(1 for item in rh_analyses.values()
                                if (item.get("holders") or {}).get(
                                    "total_fetched"))
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
