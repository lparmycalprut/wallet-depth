# -*- coding: utf-8 -*-
"""Shared watchlist helpers (used by app, watchlist page, and the cron job)."""
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")


def load_watchlist() -> dict:
    """{ca: {"symbol": str, "added": iso-date, "note": str}}"""
    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_watchlist(wl: dict) -> None:
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(wl, f, indent=1)


def add_to_watchlist(ca: str, symbol: str = "?", note: str = "") -> dict:
    wl = load_watchlist()
    if ca not in wl:
        wl[ca] = {"symbol": symbol, "note": note,
                  "added": datetime.now().strftime("%Y-%m-%d")}
    else:
        if symbol and symbol != "?":
            wl[ca]["symbol"] = symbol
    save_watchlist(wl)
    return wl


def remove_from_watchlist(ca: str) -> dict:
    wl = load_watchlist()
    wl.pop(ca, None)
    save_watchlist(wl)
    return wl
