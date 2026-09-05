# -*- coding: utf-8 -*-
"""Watchlist khusus **Robinhood Chain** (EVM, chain id 4663).

Watchlist ini terpisah dari ``watchlist.json`` (Solana). File-nya:

- ``watchlist_robinhood.json`` — daftar token ``0x…`` (persisted ke GitHub).
- ``watchlist_robinhood_pending.json`` — journal add/remove (gitignored).
- ``holder_status_robinhood.json`` — snapshot dashboard (ref ``holder-live``).
- ``holder_history_robinhood.json`` / ``.json.gz`` — store/backup history.

Fungsi di sini hanya memilih path + meneruskan ke helper yang sudah ada
(``watchlist``, ``holder_status``, ``holder_history``, ``robinhood_holders``)
supaya aturan holder dust, grafik 4 jam, kronologi, dan Telegram alert
benar-benar **sama** dengan Solana.
"""
from __future__ import annotations

import os

from holder_history import (ingest_many, load_durable_holder_history,
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
                 contexts: dict | None = None) -> dict:
    """Ingest + publish status/history Robinhood ke file lokal/GitHub."""
    store = history_store if isinstance(history_store, dict) \
        else load_history()
    history = ingest_many(analyses, store=store, path=HISTORY_LOCAL_PATH,
                          detail=True)
    status = publish_holder_status(
        analyses, watchlist, push=push, history_store=history,
        contexts=contexts,
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
