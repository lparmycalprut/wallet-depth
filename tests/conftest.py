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
def _robinhood_offline(monkeypatch):
    monkeypatch.setattr(robinhood_watchlist, "load_watchlist",
                        lambda *args, **kwargs: {})
    monkeypatch.setattr(
        robinhood_watchlist, "load_status",
        lambda *args, **kwargs: {"updated_at": None, "tokens": {}})
    monkeypatch.setattr(
        robinhood_watchlist, "load_history",
        lambda *args, **kwargs: {"updated_at": None, "tokens": {}})
