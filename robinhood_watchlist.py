# -*- coding: utf-8 -*-
"""Watchlist khusus **Robinhood Chain** (EVM, chain id 4663).

Watchlist ini terpisah dari ``watchlist.json`` (Solana). File-nya:

- ``watchlist_robinhood.json`` — daftar token ``0x…`` (persisted ke GitHub),
  dipecah dua card lewat field ``source``:
  **Robinhood LP** (default, scan cepat ±15 menit + pengingat > 0,1% MC
  berulang) dan **Robinhood biasa** (``source="regular"``, scan ±4 jam +
  rule 🔔 HIGH DROP) — lihat :func:`split_robinhood_watchlist`.
- ``watchlist_robinhood_pending.json`` — journal add/remove/source
  (gitignored).
- ``holder_status_robinhood.json`` — snapshot dashboard (ref ``holder-live``).
- ``holder_history_robinhood.json`` / ``.json.gz`` — store/backup history.

Fungsi di sini hanya memilih path + meneruskan ke helper yang sudah ada
(``watchlist``, ``holder_status``, ``holder_history``, ``robinhood_holders``)
supaya aturan holder dust, grafik 4 jam, kronologi, dan Telegram alert
benar-benar **sama** dengan Solana.
"""
from __future__ import annotations

import os

from holder_history import (holders_usable, ingest_many,
                            load_durable_holder_history,
                            publish_holder_history, seed_from_status)
from holder_status import load_holder_status, publish_holder_status
import robinhood_holders

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WATCHLIST_REPO_PATH = "watchlist_robinhood.json"
WATCHLIST_LOCAL_PATH = os.path.join(BASE_DIR, WATCHLIST_REPO_PATH)
WATCHLIST_PENDING_PATH = os.path.join(BASE_DIR, "watchlist_robinhood_pending.json")

STATUS_REPO_PATH = "holder_status_robinhood.json"
STATUS_LOCAL_PATH = os.path.join(BASE_DIR, STATUS_REPO_PATH)

HISTORY_REPO_PATH = "holder_history_robinhood.json.gz"
HISTORY_LOCAL_PATH = os.path.join(BASE_DIR, "holder_history_robinhood.json")

CHAIN_SLUG = robinhood_holders.CHAIN_SLUG
CHAIN_NAME = robinhood_holders.CHAIN_NAME

# Watchlist Robinhood dipecah dua card (permintaan user 2026-09-05):
# - **Robinhood LP**    : scan cepat ±15 menit bersama Chart LP (Meteora);
#   pengingat ⚡ EARLY DUMP berulang selama dust % MC > 0,1%.
# - **Robinhood** (biasa): scan ±4 jam; rule 🔔 HIGH DROP (turun >= 50%
#   dari titik high hold % MC).
# Split memakai field ``source`` di file watchlist yang sama, seperti split
# Chart LP di watchlist Solana. Default (source manual/kosong) = **LP** —
# warisan struktur lama saat seluruh watchlist Robinhood dipantau cepat,
# jadi token yang sudah ada tidak berpindah card.
RH_LP_SOURCE = "lp"
RH_REGULAR_SOURCE = "regular"


def is_regular_entry(meta) -> bool:
    """True bila entri watchlist Robinhood ada di card **biasa** (4 jam)."""
    source = str((meta or {}).get("source") or "").strip().lower()
    return source == RH_REGULAR_SOURCE


def split_robinhood_watchlist(watchlist: dict | None) -> tuple[dict, dict]:
    """Pisah watchlist Robinhood jadi ``(lp, regular)`` tanpa mengubah urutan."""
    lp: dict = {}
    regular: dict = {}
    for ca, meta in (watchlist or {}).items():
        if not ca:
            continue
        if is_regular_entry(meta):
            regular[ca] = meta or {}
        else:
            lp[ca] = meta or {}
    return lp, regular


def load_watchlist(force_refresh: bool = False) -> dict:
    return __import__("watchlist", fromlist=["load_watchlist"]).load_watchlist(
        force_refresh=force_refresh,
        repo_path=WATCHLIST_REPO_PATH,
        local_path=WATCHLIST_LOCAL_PATH,
        pending_path=WATCHLIST_PENDING_PATH)


def _watchlist_module():
    import watchlist as wl_mod
    return wl_mod


def add_to_robinhood_watchlist(ca: str, symbol: str = "?", note: str = "",
                               source: str = "manual", **kwargs) -> bool:
    return _watchlist_module().add_to_watchlist(
        ca, symbol, note=note, source=source,
        repo_path=WATCHLIST_REPO_PATH,
        local_path=WATCHLIST_LOCAL_PATH,
        pending_path=WATCHLIST_PENDING_PATH,
        chain_id=CHAIN_SLUG, **kwargs)


def add_many_to_robinhood_watchlist(rows, *, source: str = "manual") -> dict:
    return _watchlist_module().add_many_to_watchlist(
        rows, source=source,
        repo_path=WATCHLIST_REPO_PATH,
        local_path=WATCHLIST_LOCAL_PATH,
        pending_path=WATCHLIST_PENDING_PATH)


def remove_from_robinhood_watchlist(ca: str) -> bool:
    return _watchlist_module().remove_from_watchlist(
        ca, repo_path=WATCHLIST_REPO_PATH,
        local_path=WATCHLIST_LOCAL_PATH,
        pending_path=WATCHLIST_PENDING_PATH)


def set_robinhood_watchlist_source(ca: str, source: str) -> bool:
    return _watchlist_module().set_watchlist_source(
        ca, source,
        repo_path=WATCHLIST_REPO_PATH,
        local_path=WATCHLIST_LOCAL_PATH,
        pending_path=WATCHLIST_PENDING_PATH)


def load_status(force_refresh: bool = False) -> dict:
    return load_holder_status(
        force_refresh=force_refresh,
        repo_path=STATUS_REPO_PATH,
        local_path=STATUS_LOCAL_PATH)


def load_history() -> dict:
    store = load_durable_holder_history(path=HISTORY_LOCAL_PATH,
                                        repo_path=HISTORY_REPO_PATH)
    return seed_from_status(store, load_status())


def scan_watchlist(watchlist: dict | None, *, history_store: dict | None = None,
                   max_wallets: int | None = None,
                   dust_limit: float | None = None,
                   workers: int = 4,
                   progress=None) -> dict:
    """Scan semua token 0x… pada watchlist Robinhood Chain.

    Memanggil :func:`robinhood_holders.analyze_token` sehingga bentuk output
    sama dengan Solana (dust_count/dust_pct_mc/depth/wallet_snapshot/…).
    """
    analyses: dict[str, dict] = {}
    total = len(watchlist or {})
    if not total:
        return analyses
    store = history_store if isinstance(history_store, dict) \
        else load_history()
    workers = max(1, min(int(workers), 8))
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _job(item):
        mint, meta = item
        try:
            token_slot = ((store.get("tokens") or {}).get(mint) or {})
            cohort = token_slot.get("cohort") or {}
            addrs = list((cohort.get("balances") or {}).keys())
            tracked = []
            try:
                from telegram_alerts import tracked_wallet_addresses
                tracked = tracked_wallet_addresses(token_slot.get("alert_state"))
            except Exception:  # noqa: BLE001 - tracked bersifat pelengkap
                tracked = []
            analysis = robinhood_holders.analyze_token(
                mint, (meta or {}).get("symbol") or "?",
                dust_limit=dust_limit,
                max_wallets=int(max_wallets or 100_000),
                fetch_market=True,
                cohort_addrs=addrs,
                tracked_wallet_addrs=tracked)
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
                print(f"WARN robinhood {mint[:8]}: {error}",
                      file=__import__("sys").stderr)
            if progress:
                try:
                    progress(done, total, mint[:8])
                except Exception:  # noqa: BLE001
                    pass
    return analyses


def publish_scan(analyses: dict, watchlist: dict, *,
                 history_store: dict | None = None,
                 push: bool = False,
                 contexts: dict | None = None,
                 merge_status: dict | None = None,
                 skip_unusable: bool = True) -> dict:
    """Ingest + publish status/history Robinhood ke file lokal/GitHub.

    ``merge_status`` (snapshot sebelumnya) mewariskan token yang tidak
    ikut dianalisis run cepat — lihat ``holder_status.snapshot_status``.

    ``skip_unusable=True`` (default) menyaring hasil yang **tidak layak**
    (``holder_history.holders_usable``: 0 wallet / sampel di bawah
    ``MIN_USABLE_WALLETS``, mis. satu request Blockscout kena rate limit) dari
    snapshot dashboard — aturan yang sama dengan cron Solana. Tanpa saringan
    ini, scan gagal mempublikasikan ``dust_count 0`` / ``dust 0,00% MC`` di
    atas angka cron terakhir yang masih benar, sehingga dashboard berbunyi
    "AMAN" padahal tidak ada data. Titiknya TETAP masuk history (``ingest_many``
    menandainya ``degraded``) supaya jejak scan gagal tidak hilang, dan token itu
    mewarisi angka snapshot lama lewat ``merge_status``.
    """
    store = history_store if isinstance(history_store, dict) \
        else load_history()
    history = ingest_many(analyses, store=store, path=HISTORY_LOCAL_PATH,
                          detail=True)
    publishable = analyses
    skipped: list[str] = []
    if skip_unusable:
        publishable = {}
        for mint, analysis in (analyses or {}).items():
            if holders_usable((analysis or {}).get("holders")):
                publishable[mint] = analysis
            else:
                skipped.append(str(mint))
        if skipped:
            print("Robinhood publish: %d token dilewati (holder scan tidak "
                  "layak): %s" % (len(skipped), ", ".join(s[:10] for s in skipped)),
                  file=__import__("sys").stderr)
    status = publish_holder_status(
        publishable, watchlist, push=push, history_store=history,
        contexts=contexts, merge_status=merge_status,
        repo_path=STATUS_REPO_PATH,
        local_path=STATUS_LOCAL_PATH)
    if push:
        try:
            publish_holder_history(history, push=True,
                                   repo_path=HISTORY_REPO_PATH)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: robinhood backup publish failed: {exc}",
                  file=__import__("sys").stderr)
    return status
