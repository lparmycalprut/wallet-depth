# -*- coding: utf-8 -*-
"""Autouse fixture: keep suite offline.

AppTest/scan tests exercise the Solana (Helius/GMGN) and watchlist flows;
the alert-settings transport and the scan-result cache are pinned here so no
test touches GitHub or writes into the repo.
"""
import pytest

import alert_settings


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


