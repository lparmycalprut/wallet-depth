# -*- coding: utf-8 -*-
"""Alert Telegram page **🌊 Sweep** (kredensial berlapis).

Urutan pembacaan kredensial — persis yang dipilih user 2026-10-12
(*"Berlapis: st.secrets → env → config.json"*):

1. Streamlit secrets (``.streamlit/secrets.toml`` / Settings → Secrets)
2. environment variable ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID``
3. ``config.json``

Langkah 2 adalah pola yang sudah terbukti di repo lain user
(``handsoff/prepump_cron_detector.py`` + ``cron_workflow.yml``), jadi cron
GitHub Actions cukup memakai secrets repo dengan nama yang sama — tanpa kode
kedua.

Modul ini **tidak pernah melempar** ke pemanggil: alert adalah pelengkap, dan
satu Telegram yang gagal tidak boleh menggagalkan scan.
"""
from __future__ import annotations

import json
import os
import urllib.request

import sweep_screen as screen

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
API_URL = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT = 10

ENV_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_CHAT = "TELEGRAM_CHAT_ID"

SOURCE_SECRETS = "st.secrets"
SOURCE_ENV = "env"
SOURCE_CONFIG = "config.json"
SOURCE_NONE = "—"


def _clean(value) -> str:
    return str(value or "").strip()


def _from_secrets() -> tuple:
    try:
        import streamlit as st
        token = _clean(st.secrets.get(ENV_TOKEN) or st.secrets.get("telegram_bot_token"))
        chat = _clean(st.secrets.get(ENV_CHAT) or st.secrets.get("telegram_chat_id"))
        return token, chat
    except Exception:  # noqa: BLE001 - CLI/cron tidak punya secrets
        return "", ""


def _from_config() -> tuple:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            data = json.load(handle) or {}
        return (_clean(data.get(ENV_TOKEN) or data.get("telegram_bot_token")),
                _clean(data.get(ENV_CHAT) or data.get("telegram_chat_id")))
    except Exception:  # noqa: BLE001
        return "", ""


def telegram_config() -> dict:
    """Kredensial efektif + asalnya; ``ok`` True hanya bila keduanya terisi."""
    token, chat = _from_secrets()
    source = SOURCE_SECRETS if (token and chat) else ""
    if not (token and chat):
        token, chat = _clean(os.environ.get(ENV_TOKEN)), _clean(os.environ.get(ENV_CHAT))
        if token and chat:
            source = SOURCE_ENV
    if not (token and chat):
        token, chat = _from_config()
        if token and chat:
            source = SOURCE_CONFIG
    return {"token": token, "chat_id": chat, "ok": bool(token and chat),
            "source": source or SOURCE_NONE}


def muted_mints() -> set:
    """Daftar mint yang dibisukan (``sweep_muted_mints`` di ``config.json``)."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            data = json.load(handle) or {}
        raw = data.get("sweep_muted_mints") or []
        return {_clean(item) for item in raw if _clean(item)}
    except Exception:  # noqa: BLE001
        return set()


def send_message(text: str, *, config: dict | None = None) -> tuple:
    """Kirim pesan; mengembalikan ``(terkirim, pesan_error)``."""
    cfg = config or telegram_config()
    if not cfg.get("ok"):
        return False, "kredensial Telegram belum dipasang"
    if not _clean(text):
        return False, "teks kosong"
    url = API_URL.format(token=cfg["token"])
    payload = json.dumps({"chat_id": cfg["chat_id"], "text": text,
                          "disable_web_page_preview": True}).encode("utf-8")
    try:
        import requests
        response = requests.post(url, data=payload,
                                 headers={"Content-Type": "application/json"},
                                 timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return True, ""
        return False, f"HTTP {response.status_code}: {response.text[:120]}"
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:160]
    try:
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:160]


# ---------------------------------------------------------------------------
# Format pesan
# ---------------------------------------------------------------------------
def _pct(value, digits: int = 1) -> str:
    number = screen._num(value)
    return f"{number*100:.{digits}f}%" if number is not None else "—"


def _pct100(value, digits: int = 1) -> str:
    """Format angka yang **sudah** dalam persen (0-100)."""
    number = screen._num(value)
    return f"{number:.{digits}f}%" if number is not None else "—"


def _usd(value, digits: int = 0) -> str:
    number = screen._num(value)
    if number is None:
        return "—"
    if abs(number) >= 1000:
        return f"${number:,.{digits}f}"
    return f"${number:,.4f}"


def _mult(value, digits: int = 2) -> str:
    number = screen._num(value)
    return f"{number:.{digits}f}x" if number is not None else "—"


def _price(value) -> str:
    number = screen._num(value)
    if number is None:
        return "—"
    if number >= 1:
        return f"${number:,.4f}"
    return f"${number:.8f}"


def _link(mint: str) -> str:
    return f"https://gmgn.ai/sol/token/{mint}"


def format_eligibility(mint: str, metrics: dict, result: dict) -> str:
    """Pesan alert **kelayakan sweep** — struktur + rumus biaya sweep."""
    metrics = metrics or {}
    result = result or {}
    symbol = metrics.get("symbol") or mint[:8]
    checks = [c for c in (result.get("checks") or []) if c.get("has_data")]
    lines = [
        f"🌊 KELAYAKAN SWEEP — ${symbol}",
        f"Vonis: {result.get('verdict') or '—'} "
        f"({result.get('passed_count')}/{result.get('scored_count')} kriteria)",
        f"liq/MC: {_pct(result.get('liq_mc'))} | "
        f"liq {_usd(metrics.get('liq_usd'))} | MC {_usd(metrics.get('fdv_usd'))}",
        f"LP locked {_pct100(metrics.get('lp_locked_pct'))} | "
        f"top-10 {_pct100(metrics.get('top10_holder_pct'))} | "
        f"holder {metrics.get('holder_count') or '—'}",
        f"Bundler {_pct(metrics.get('bundler_rate'))} | "
        f"bot degen {_pct(metrics.get('bot_degen_rate'))} | "
        f"entrapment {_pct(metrics.get('entrapment_rate'))}",
    ]
    targets = result.get("targets") or []
    if targets:
        bits = [f"{_mult(t['mult'], 0)}≈{t['cost_pct']:.0f}%MC"
                for t in targets[:3] if t.get("cost_pct") is not None]
        if bits:
            lines.append("Biaya sweep: " + " | ".join(bits))
    if checks:
        lines.append("Kriteria: " + ", ".join(
            ("✅" if c.get("passed") else "❌") + c.get("label", "")
            for c in checks))
    missing = result.get("missing") or []
    if missing:
        lines.append("Data kurang: " + ", ".join(missing))
    lines.append(_link(mint))
    return "\n".join(lines)


def format_sweep(mint: str, metrics: dict, context: dict) -> str:
    """Pesan alert **sweep mulai terjadi** — termasuk rumus net vs churn."""
    metrics = metrics or {}
    context = context or {}
    symbol = metrics.get("symbol") or mint[:8]
    lines = [
        f"⚡ SWEEP TERDETEKSI — ${symbol}",
        f"Volume {_mult(context.get('vol_x'), 1)} median candle "
        f"({_usd(context.get('vol'))})",
        f"Harga {_price(context.get('base_price'))} → "
        f"{_price(context.get('close'))} ({_mult(context.get('price_mult'))})",
        f"liq/MC: {_pct(context.get('liq_mc'))}"
        + (f" | leverage {_mult(context.get('leverage'), 0)}"
           if context.get("leverage") else ""),
    ]
    if context.get("est_cost_usd"):
        lines.append(f"Biaya dorong min (akar m − 1) × liq: "
                     f"{_usd(context['est_cost_usd'])}")
    if context.get("paper_mcap_usd"):
        lines.append(f"Paper MC di close sweep: "
                     f"{_usd(context['paper_mcap_usd'])}")
    inflow = context.get("net_inflow_usd")
    if inflow:
        lines.append(f"Inflow nyata (Δ likuiditas): {_usd(inflow)}"
                     + (f" → {inflow / context['est_cost_usd']:.1f}x biaya "
                        "dorong (pembeli luar ikut masuk)"
                        if context.get("est_cost_usd") else ""))
    if context.get("churn_x"):
        lines.append(f"Churn {context['churn_x']:.1f}x (volume ÷ biaya dorong "
                     "teoretis; makin besar = makin tidak efisien)")
    if context.get("churn_net_x"):
        lines.append(f"Churn nyata {context['churn_net_x']:.1f}x "
                     "(volume ÷ inflow terukur)")
    elif context.get("net_inflow_ref_usd"):
        lines.append(f"Acuan 1 event (COCKROACH 1 Okt): inflow nyata "
                     f"≈{_usd(context['net_inflow_ref_usd'])} = 2,4x biaya "
                     "dorong → churn ≈21x")
    if context.get("bars_ago"):
        lines.append(f"Terjadi {context['bars_ago']} candle lalu")
    lines.append("⚠️ Candle vertikal = retrace 11/12 kali. Tunggu retest "
                 "38,2-50%, jangan chase.")
    lines.append(_link(mint))
    return "\n".join(lines)


def format_test() -> str:
    return ("✅ Test alert page 🌊 Sweep — koneksi Telegram OK.\n"
            "Alert akan dikirim saat kelayakan sweep muncul dari watchlist "
            "atau saat sweep mulai terjadi.")
