# -*- coding: utf-8 -*-
"""Autouse fixture: keep suite offline.

Existing AppTest/scan tests exercise the Solana (Helius/GMGN) and
watchlist flows and do not yet mock the new Robinhood Chain card. The
Robinhood watchlist/status/history loaders are therefore stubbed to empty
for every test so app-level tests do not hit rh-scan/Blockscout/DexScreener
or the GitHub raw API. The Robinhood modules themselves are still covered
by dedicated tests that monkeypatch the network layer.
"""
import pytest

import alert_settings
import robinhood_watchlist


@pytest.fixture(autouse=True)
def _alert_settings_offline(monkeypatch):
    """Toggle alert tidak boleh menyentuh GitHub di suite (lihat __init__.py)."""
    monkeypatch.setattr(alert_settings, "_read_remote",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(alert_settings, "_write_remote",
                        lambda *args, **kwargs: True)


@pytest.fixture(autouse=True)
def _iso_scan_cache(monkeypatch, tmp_path):
    """Isolasi cache hasil scan per-tes.

    ``scan_result_cache`` menulis berkas JSON ke ``.scan_cache/`` di root repo
    supaya hasil scan tahan refresh browser. Tanpa fixture ini setiap
    AppTest yang memindai akan menulis ke repo dan dua tes bisa saling
    menimpa hasilnya (lagi pula runner tidak boleh menyentuh repo).
    ``tests/__init__.py`` mematikan cache untuk runner ``unittest``; di sini
    cache dihidupkan kembali dengan direktori ``tmp_path`` milik tes sendiri.
    """
    import scan_result_cache

    directory = tmp_path / ".scan_cache"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SCAN_CACHE", "1")
    monkeypatch.setenv("SCAN_CACHE_DIR", str(directory))
    monkeypatch.setattr(scan_result_cache, "DEFAULT_CACHE_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def _robinhood_offline(monkeypatch):
    monkeypatch.setattr(robinhood_watchlist, "load_watchlist",
                        lambda *args, **kwargs: {})
    monkeypatch.setattr(
        robinhood_watchlist, "load_status",
        lambda *args, **kwargs: {"updated_at": None, "tokens": {}})
    monkeypatch.setattr(
        robinhood_watchlist, "load_history",
        lambda *args, **kwargs: {"updated_at": None, "tokens": {}})
