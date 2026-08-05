# -*- coding: utf-8 -*-
"""Memecoin Scanner — 5 Fase Scoring System untuk deteksi pola akumulasi.

Logic port dari https://github.com/lparmycalprut/memecoin_scanner

5 Fase Scoring (total 100 poin):
1. Liquidity Test (15 pts) - early stage detection
2. Slow Accumulation (20 pts) - transaction growth
3. Whale Entry (20 pts) - whale transactions dari Helius
4. Volume Spike (25 pts) - volume spike ratio
5. Thin Liquidity (20 pts) - thin liquidity = early opportunity

Alert threshold: score >= 60/100
Scan interval: setiap 15 menit
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional

import requests

from core import (atomic_write_json, dexscreener_pair_token,
                  get_helius_keys, select_dexscreener_pair)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "scanner_state.json")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Default thresholds (bisa di-override via config.json)
DEFAULT_CONFIG = {
    "scan_interval_minutes": 15,
    "alert_score_threshold": 60,
    "liquidity_threshold": 300_000,
    "fdv_threshold": 2_000_000,
    "volume_spike_x": 10,
    "tx_spike_x": 10,
    "whale_min_amount": 1000,
    "whale_lookback_hours": 3,
}

# Dedupe: don't re-send the same alert within this many minutes
ALERT_DEDUPE_MIN = 60


def load_config() -> dict:
    """Load scanner config from config.json."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f) or {}
            for key in DEFAULT_CONFIG:
                if key in user_cfg:
                    cfg[key] = user_cfg[key]
    except Exception:
        pass
    return cfg


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def load_state() -> dict:
    """Load scanner state from disk."""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    """Persist scanner state to disk."""
    try:
        atomic_write_json(STATE_PATH, state, separators=(",", ":"))
    except Exception as exc:
        print(f"WARN: failed to save {STATE_PATH}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def _tg_creds():
    """Telegram credentials from env/config."""
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat:
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f) or {}
            tok = tok or str(cfg.get("telegram_bot_token", "")).strip()
            chat = chat or str(cfg.get("telegram_chat_id", "")).strip()
        except Exception:
            pass
    return tok, chat


def send_telegram(text: str) -> bool:
    """Send a Telegram message (Markdown parse mode)."""
    tok, chat = _tg_creds()
    if not tok or not chat:
        print("WARN: Telegram credentials not configured", file=sys.stderr)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": True}, timeout=15)
        return bool(r.json().get("ok"))
    except Exception as exc:
        print(f"WARN: Telegram send failed: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------
def fetch_token_data(address: str) -> Optional[Dict[str, Any]]:
    """Fetch token data from DexScreener API."""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("pairs"):
            return None

        pair = select_dexscreener_pair(data["pairs"], address)
        if not pair:
            return None
        token = dexscreener_pair_token(pair, address)

        result = {
            "address": address,
            "symbol": token.get("symbol", "UNKNOWN"),
            "price_usd": float(pair.get("priceUsd", 0)),
            "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
            "fdv": float(pair.get("fdv", 0)),
            "volume_h1": float(pair.get("volume", {}).get("h1", 0)),
            "volume_h6": float(pair.get("volume", {}).get("h6", 0)),
            "txns_h1": pair.get("txns", {}).get("h1", {"buys": 0, "sells": 0}),
            "txns_h6": pair.get("txns", {}).get("h6", {"buys": 0, "sells": 0}),
            "txns_h24": pair.get("txns", {}).get("h24", {"buys": 0, "sells": 0}),
        }
        return result
    except Exception as e:
        print(f"❌ Gagal fetch {address}: {e}")
        return None


def fetch_whale_transactions(
    token_address: str,
    current_price_usd: float,
    config: dict,
    decimals: int = 9
) -> List[Dict[str, Any]]:
    """Fetch whale transactions from Helius."""
    api_keys = get_helius_keys()
    if not api_keys:
        return []

    api_key = api_keys[0]  # Use first key
    url = f"https://api.helius.xyz/v0/addresses/{token_address}/transactions"
    params = {"api-key": api_key, "limit": 100}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"❌ Helius error: {e}")
        return []

    if not data or not isinstance(data, list):
        return []

    lookback_hours = config.get("whale_lookback_hours", 3)
    min_amount = config.get("whale_min_amount", 1000)
    cutoff_time = int(time.time()) - (lookback_hours * 3600)
    whale_txs = []

    for tx in data:
        if tx.get("timestamp", 0) < cutoff_time:
            continue

        for transfer in tx.get("tokenTransfers", []):
            if transfer.get("mint") != token_address:
                continue

            amount_raw = int(transfer.get("amount", 0))
            if amount_raw == 0:
                continue

            amount_decimal = amount_raw / (10 ** decimals)
            usd_value = amount_decimal * current_price_usd

            if usd_value >= min_amount:
                whale_txs.append({
                    "signature": tx.get("signature", ""),
                    "timestamp": tx.get("timestamp"),
                    "buyer": transfer.get("toUserAccount", "Unknown"),
                    "usd_value": usd_value
                })

    # Sort by value descending & remove duplicates
    whale_txs.sort(key=lambda x: x["usd_value"], reverse=True)
    seen = set()
    unique = []
    for tx in whale_txs:
        if tx["signature"] not in seen:
            seen.add(tx["signature"])
            unique.append(tx)

    return unique[:10]


def format_whale_summary(whale_txs: List[Dict[str, Any]], config: dict) -> str:
    """Format whale transactions for alert message."""
    if not whale_txs:
        lookback = config.get("whale_lookback_hours", 3)
        return f"🐋 Tidak ada whale detected dalam {lookback} jam terakhir."

    total_val = sum(tx["usd_value"] for tx in whale_txs)
    top_wallets = []
    for tx in whale_txs[:3]:
        w = tx["buyer"]
        short_w = f"{w[:6]}...{w[-4:]}" if w and w != "Unknown" else "Unknown"
        top_wallets.append(f"{short_w} (${tx['usd_value']:,.0f})")

    return (
        f"🐋 *Aktivitas Whale*:\n"
        f"  - Total buy whale: {len(whale_txs)}\n"
        f"  - Total nilai: ${total_val:,.0f}\n"
        f"  - Top wallets: {', '.join(top_wallets)}"
    )


# ---------------------------------------------------------------------------
# 5 Fase Scoring System
# ---------------------------------------------------------------------------
@dataclass
class ScanResult:
    address: str
    symbol: str
    score: int
    phases: Dict[str, Any] = field(default_factory=dict)
    alert_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


def analyze_token(data: Dict[str, Any], config: dict) -> Optional[ScanResult]:
    """
    Analyze token dengan 5 Fase Scoring System.
    
    Returns ScanResult dengan score 0-100 dan alert_message jika score >= threshold.
    """
    if not data:
        return None

    # === Ekstrak Data ===
    liq = data["liquidity_usd"]
    fdv = data["fdv"]
    vol_h1 = data["volume_h1"]
    vol_h6 = data["volume_h6"]
    tx_h1 = data["txns_h1"]
    tx_h6 = data["txns_h6"]
    total_tx_h1 = tx_h1.get("buys", 0) + tx_h1.get("sells", 0)
    total_tx_h6 = tx_h6.get("buys", 0) + tx_h6.get("sells", 0)
    buy_ratio_h1 = tx_h1.get("buys", 0) / max(1, tx_h1.get("sells", 1))

    phase_scores = {}
    total_score = 0

    # === FASE 1: Liquidity Test (15 pts) ===
    if total_tx_h1 < 20 and vol_h1 < 1000:
        score, detail = 15, "Masih fase test awal"
    elif total_tx_h1 < 50 and vol_h1 < 5000:
        score, detail = 10, "Akumulasi awal mulai terlihat"
    else:
        score, detail = 5, "Sudah melewati fase test"
    phase_scores["liquidity_test"] = {"score": score, "detail": detail}
    total_score += score

    # === FASE 2: Slow Accumulation (20 pts) ===
    tx_growth = total_tx_h1 / max(1, total_tx_h6)
    tx_spike_x = config.get("tx_spike_x", 10)
    if tx_growth >= tx_spike_x and total_tx_h1 > 50:
        score, detail = 18, f"Kuat! Tx growth {tx_growth:.1f}x"
    elif tx_growth >= 5:
        score, detail = 12, f"Moderate growth {tx_growth:.1f}x"
    elif total_tx_h1 > 100:
        score, detail = 8, "Tx tinggi tapi growth melambat"
    else:
        score, detail = 2, "Akumulasi rendah"
    phase_scores["slow_accumulation"] = {"score": score, "detail": detail}
    total_score += score

    # === FASE 3: Whale Entry (20 pts) - REAL ONCHAIN ===
    whale_txs = fetch_whale_transactions(data["address"], data["price_usd"], config)
    whale_summary = format_whale_summary(whale_txs, config)
    whale_count = len(whale_txs)

    if whale_count > 0:
        largest = whale_txs[0]["usd_value"]
        total_whale = sum(tx["usd_value"] for tx in whale_txs)
        if largest >= 5000 and whale_count >= 3:
            score, detail = 20, f"🔥 Banyak whale! Top ${largest:,.0f}, Total ${total_whale:,.0f}"
        elif largest >= 5000:
            score, detail = 18, f"🐋 Mega whale! ${largest:,.0f}"
        elif largest >= 2000:
            score, detail = 15, f"🐳 Whale detected! ${largest:,.0f}"
        else:
            score, detail = 12, f"🐟 Small whale ${largest:,.0f}"
    else:
        # Fallback ke proksi
        if buy_ratio_h1 > 1.5 and vol_h1 > 10000:
            score, detail = 12, "⚠️ Proksi: Buy pressure tinggi (no onchain data)"
        elif buy_ratio_h1 > 1.2 and vol_h1 > 5000:
            score, detail = 8, "⚠️ Proksi: Buy pressure sedang"
        else:
            score, detail = 0, "❌ Tidak ada whale & tidak ada buy pressure"
    phase_scores["whale_entry"] = {"score": score, "detail": detail, "whale_data": whale_txs}
    total_score += score

    # === FASE 4: Volume Spike (25 pts) ===
    if vol_h6 > 0:
        avg_baseline = vol_h6 / 6
        spike_ratio = vol_h1 / max(1, avg_baseline)
    else:
        spike_ratio = 0

    volume_spike_x = config.get("volume_spike_x", 10)
    if spike_ratio >= volume_spike_x:
        score, detail = 22, f"💥 Lonjakan besar {spike_ratio:.1f}x"
    elif spike_ratio >= 5:
        score, detail = 15, f"Lonjakan bagus {spike_ratio:.1f}x"
    elif spike_ratio >= 2:
        score, detail = 8, f"Lonjakan kecil {spike_ratio:.1f}x"
    else:
        score, detail = 2, "Tidak ada lonjakan volume"
    phase_scores["volume_spike"] = {"score": score, "detail": detail}
    total_score += score

    # === FASE 5: Thin Liquidity (20 pts) ===
    liq_threshold = config.get("liquidity_threshold", 300_000)
    fdv_threshold = config.get("fdv_threshold", 2_000_000)
    
    if liq < 50000 and fdv < 500000:
        score, detail = 20, "Sangat tipis (liq<50k, fdv<500k)"
    elif liq < 100000 and fdv < 1000000:
        score, detail = 16, "Sangat tipis (liq<100k, fdv<1M)"
    elif liq < liq_threshold and fdv < fdv_threshold:
        score, detail = 12, "Tipis (liq & fdv rendah)"
    elif liq < liq_threshold:
        score, detail = 8, "Tipis tapi fdv tinggi"
    else:
        score, detail = 2, "Likuiditas terlalu tebal"
    phase_scores["thin_liquidity"] = {"score": score, "detail": detail}
    total_score += score

    # === Buat Alert ===
    alert = None
    alert_threshold = config.get("alert_score_threshold", 60)
    if total_score >= alert_threshold:
        phase_lines = "\n".join([f"  - {k}: {v['score']}pts - {v['detail']}" for k, v in phase_scores.items()])
        alert = (
            f"🚨 *ALERT: Pola Akumulasi Terdeteksi!*\n"
            f"Token: {data['symbol']} ({data['address'][:6]}...{data['address'][-4:]})\n"
            f"Score: *{total_score}/100*\n"
            f"Harga: ${data['price_usd']:.6f}\n"
            f"Liq: ${liq:,.0f} | FDV: ${fdv:,.0f}\n"
            f"Vol 1j: ${vol_h1:,.0f} (Spike: {spike_ratio:.1f}x)\n"
            f"Buy/Sell 1j: {tx_h1.get('buys', 0)} / {tx_h1.get('sells', 0)}\n"
            f"\n📊 *Rincian Fase:*\n{phase_lines}\n\n{whale_summary}"
        )

    return ScanResult(
        address=data["address"],
        symbol=data["symbol"],
        score=total_score,
        phases=phase_scores,
        alert_message=alert,
    )


# ---------------------------------------------------------------------------
# Main scanner runner
# ---------------------------------------------------------------------------
def run_scan() -> dict:
    """
    Run a full scan cycle.
    
    Returns:
        {sent: int, tokens_scanned: int, alerts_sent: int, results: list}
    """
    from watchlist import load_watchlist

    state = load_state()
    config = load_config()
    now = time.time()

    wl = load_watchlist()
    if not wl:
        return {"sent": 0, "tokens_scanned": 0, "alerts_sent": 0, 
                "results": [], "message": "empty watchlist"}

    # Track last alerts for dedup
    last_alerts = state.get("last_alerts", {})

    results = []
    alerts_sent = 0

    for ca, meta in wl.items():
        try:
            # Fetch token data
            data = fetch_token_data(ca)
            if not data:
                continue

            # Analyze with 5-phase scoring
            result = analyze_token(data, config)
            if not result:
                continue

            # Check if should send alert
            if result.alert_message:
                # Dedup check
                last_sent = last_alerts.get(ca, 0)
                if now - last_sent >= ALERT_DEDUPE_MIN * 60:
                    # Send alert
                    if send_telegram(result.alert_message):
                        last_alerts[ca] = now
                        alerts_sent += 1
                        print(f"🔔 ALERT! {result.symbol} score={result.score}")

            results.append({
                "ca": ca,
                "symbol": result.symbol,
                "score": result.score,
                "phases": result.phases,
                "has_alert": result.alert_message is not None,
                "timestamp": result.timestamp,
            })

        except Exception as exc:
            print(f"WARN: scan failed for {ca[:8]}: {exc}", file=sys.stderr)

    # Save state
    state["last_alerts"] = last_alerts
    state["last_scan_ts"] = now
    save_state(state)

    # Save results for dashboard
    try:
        results_path = os.path.join(BASE_DIR, "scanner_results.json")
        atomic_write_json(results_path, {
            "ts": int(now),
            "time_wib": time.strftime("%H:%M", time.gmtime(now + 7 * 3600)),
            "results": results,
            "alerts_sent": alerts_sent,
        }, indent=1)
    except Exception:
        pass

    return {
        "sent": alerts_sent,
        "tokens_scanned": len(results),
        "alerts_sent": alerts_sent,
        "results": results,
        "message": f"{alerts_sent} alert(s) sent",
    }


def run_scan_cli():
    """CLI entry point for the cron job."""
    print(f"🔍 Memecoin Scanner — {time.strftime('%Y-%m-%d %H:%M:%S WIB', time.gmtime(time.time() + 7*3600))}")
    result = run_scan()
    print(f"  Scanned: {result['tokens_scanned']} tokens")
    print(f"  Alerts: {result['alerts_sent']}")
    print(f"  Status: {result['message']}")
    return result


if __name__ == "__main__":
    run_scan_cli()
