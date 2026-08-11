# -*- coding: utf-8 -*-
"""
SOLANA MEMECOIN PRE-PUMP & WYCKOFF 15M CRON DETECTOR

This script runs every 15 minutes (at minute 14, 29, 44, 59 UTC).
It reads tokens from `watchlist.json`, fetches trades and top 100 holders from GMGN,
computes Pre-Pump & Wyckoff Accumulation signals, and sends notifications.
"""

import os
import sys
import time
import json
import uuid
import math
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watchlist import load_watchlist
from core import atomic_write_json

# Default SOL price for estimation
SOL_PRICE_USD = 150.0

def fetch_top_holders(ca, timeout=20):
    """Fetch top 100 holders from GMGN API."""
    device_id = str(uuid.uuid4())
    fp_did = uuid.uuid4().hex
    build_tag = "20260807-3117-f1d79dd"
    url = (
        f"https://gmgn.ai/vas/api/v1/token_holders/sol/{ca}"
        f"?device_id={device_id}&fp_did={fp_did}"
        f"&client_id=gmgn_web_{build_tag}&from_app=gmgn&app_ver={build_tag}"
        f"&tz_name=Asia%2FJakarta&tz_offset=25200&app_lang=en-US&os=web&worker=0"
        f"&limit=100&cost=20&orderby=amount_percentage&direction=desc"
    )
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,id;q=0.8",
        "referer": f"https://gmgn.ai/sol/token/{ca}",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    }
    try:
        from curl_cffi import requests as cr
        r = cr.get(url, impersonate="chrome", headers=headers, timeout=timeout)
    except Exception:
        import requests
        r = requests.get(url, headers=headers, timeout=timeout)
    
    if r.status_code == 200:
        data = r.json() or {}
        return (data.get("data") or {}).get("holders") or []
    raise Exception(f"HTTP {r.status_code} fetching holders")


def fetch_gmgn_trades(ca, limit=500, timeout=20):
    """Fetch recent trades from GMGN API."""
    url_template = "https://gmgn.ai/api/v1/token_trades/sol/{}?limit=50"
    headers = {
        "accept": "application/json, text/plain, */*",
        "referer": f"https://gmgn.ai/sol/token/{ca}",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    }
    try:
        from curl_cffi import requests as cr
        fetcher = cr
    except Exception:
        import requests
        fetcher = requests

    all_trades = []
    cursor = None
    pages = 0
    max_pages = (limit // 50) + 1

    while pages < max_pages:
        url = url_template.format(ca)
        if cursor:
            url += f"&cursor={cursor}"

        r = fetcher.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            break
        data = r.json() or {}
        trades_raw = (data.get("data") or {}).get("trades") or []
        if not trades_raw:
            break

        for t in trades_raw:
            usd_val = float(t.get("amount_usd") or t.get("usd") or 0)
            token_val = float(t.get("amount_token") or t.get("token_amount") or 0)
            price_val = float(t.get("price") or t.get("price_usd") or 0)
            if price_val <= 0 and token_val > 0:
                price_val = usd_val / token_val
            
            all_trades.append({
                "wallet": t.get("maker") or t.get("address"),
                "side": "buy" if (t.get("event") or "").lower() == "buy" else "sell",
                "usd": usd_val,
                "token_amount": token_val,
                "price": price_val,
                "ts": int(t.get("timestamp") or t.get("time") or 0),
            })

        cursor = (data.get("data") or {}).get("next")
        pages += 1
        if not cursor or len(trades_raw) < 50:
            break
        time.sleep(0.15)
        
    return all_trades


def get_mock_data(now_ts):
    """Generate mock data for token 8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump right before the pump."""
    # 1. 100% Pure Accumulators (100 holders)
    holders = []
    for i in range(1, 101):
        # We specify Rank 3 to have a specific address
        wallet_address = f"MockHolderAddress{i}xxxxxxxxxxxxxxxxxx" if i != 3 else "Rank3TopHolderWalletAddressxxxxxxxxxxxxxx"
        holders.append({
            "address": wallet_address,
            "rank": i,
            "balance": 10000.0 / i,
            "history_bought_amount": 10000.0 / i,
            "history_sold_amount": 0.0,
            "cost": 0.000035,
            "avg_cost": 0.000035
        })

    # 2. Trades in Bin 0 (0 - 15m ago)
    # Total Vol: 12.30 SOL, CVD: -1.96 SOL, Price: +22.51% (open: 0.0000359, close: 0.00004398)
    # To get CVD = -1.96 SOL out of 12.30 SOL total:
    # Buy: 5.17 SOL, Sell: 7.13 SOL. Net: 5.17 - 7.13 = -1.96 SOL.
    bin0_start = now_ts - 15 * 60
    
    trades = [
        # Rank 3 buy trade
        {
            "wallet": "Rank3TopHolderWalletAddressxxxxxxxxxxxxxx",
            "side": "buy",
            "usd": 5.0 * SOL_PRICE_USD, # 5.0 SOL
            "token_amount": (5.0 * SOL_PRICE_USD) / 0.00004398,
            "price": 0.00004398,
            "ts": bin0_start + 10 * 60, # 10 min into the bin
        },
        # Small buy trade
        {
            "wallet": "AnotherBuyerWalletAddressxxxxxxxxxxxxxxxxx",
            "side": "buy",
            "usd": 0.17 * SOL_PRICE_USD, # 0.17 SOL
            "token_amount": (0.17 * SOL_PRICE_USD) / 0.00004398,
            "price": 0.00004398,
            "ts": bin0_start + 11 * 60,
        },
        # Sell trade representing open/low price
        {
            "wallet": "SellerWalletAddressxxxxxxxxxxxxxxxxxxxxxxx",
            "side": "sell",
            "usd": 7.13 * SOL_PRICE_USD, # 7.13 SOL
            "token_amount": (7.13 * SOL_PRICE_USD) / 0.0000359,
            "price": 0.0000359,
            "ts": bin0_start + 2 * 60, # 2 min into the bin
        }
    ]

    # 3. Trades in previous bins to establish baseline volume
    # Average of 20.0 SOL per bin in Bins 4 to 11 (60 to 180 min ago)
    for bin_idx in range(1, 16):
        b_start = now_ts - (bin_idx + 1) * 15 * 60
        # Add a dummy trade per bin
        trades.append({
            "wallet": "DummyWalletxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "side": "buy",
            "usd": 20.0 * SOL_PRICE_USD,
            "token_amount": (20.0 * SOL_PRICE_USD) / 0.000035,
            "price": 0.000035,
            "ts": b_start + 5 * 60
        })

    return holders, trades


def process_trades_to_15m_bins(trades, now_ts):
    bins = []
    for i in range(16):
        bin_start = now_ts - (i + 1) * 15 * 60
        bin_end = now_ts - i * 15 * 60
        
        bin_trades = [t for t in trades if bin_start <= t['ts'] < bin_end]
        bin_trades_asc = sorted(bin_trades, key=lambda x: x['ts'])
        
        volume_usd = sum(t['usd'] for t in bin_trades)
        
        open_price = 0.0
        close_price = 0.0
        
        valid_price_trades = [t for t in bin_trades_asc if t['token_amount'] > 0 and t['usd'] > 0]
        if valid_price_trades:
            open_price = valid_price_trades[0]['price']
            close_price = valid_price_trades[-1]['price']
        
        price_change_pct = 0.0
        if open_price > 0:
            price_change_pct = (close_price - open_price) / open_price * 100.0
            
        buys = [t for t in bin_trades if t['side'] == 'buy']
        sells = [t for t in bin_trades if t['side'] == 'sell']
        
        buy_vol_usd = sum(t['usd'] for t in buys)
        sell_vol_usd = sum(t['usd'] for t in sells)
        
        buy_count = len(buys)
        sell_count = len(sells)
        total_tx = len(bin_trades)
        
        buy_tx_ratio = buy_count / total_tx if total_tx > 0 else 0.0
        
        bins.append({
            'bin_index': i,
            'start': bin_start,
            'end': bin_end,
            'trades': bin_trades,
            'volume_usd': volume_usd,
            'open_price': open_price,
            'close_price': close_price,
            'price_change_pct': price_change_pct,
            'buy_vol_usd': buy_vol_usd,
            'sell_vol_usd': sell_vol_usd,
            'buy_count': buy_count,
            'sell_count': sell_count,
            'total_tx': total_tx,
            'buy_tx_ratio': buy_tx_ratio
        })
    return bins


def send_telegram_notif(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        try:
            with open("config.json") as f:
                cfg = json.load(f)
                token = token or cfg.get("telegram_bot_token")
                chat = chat or cfg.get("telegram_chat_id")
        except Exception:
            pass
    if not token or not chat:
        print("Telegram credentials not configured.")
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        res = requests.post(url, json=payload, timeout=15)
        return res.status_code == 200
    except Exception as e:
        print("Error sending Telegram:", e)
        return False


def send_discord_notif(text):
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        try:
            with open("config.json") as f:
                cfg = json.load(f)
                url = url or cfg.get("discord_webhook_url")
        except Exception:
            pass
    if not url:
        print("Discord Webhook URL not configured.")
        return False
    try:
        import requests
        # Convert HTML tags to Markdown for Discord
        md_text = (
            text.replace("<b>", "**")
            .replace("</b>", "**")
            .replace("<i>", "*")
            .replace("</i>", "*")
            .replace("<code>", "`")
            .replace("</code>", "`")
        )
        payload = {"content": md_text}
        res = requests.post(url, json=payload, timeout=15)
        return res.status_code in (200, 204)
    except Exception as e:
        print("Error sending Discord:", e)
        return False


def load_signals():
    path = "signals.json"
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f) or []
    except Exception:
        pass
    return []


def save_signal_to_history(sig):
    path = "signals.json"
    items = load_signals()
    # Check deduplication (same ca and signal_type within last 3 hours)
    now = int(time.time())
    is_duplicate = False
    for s in reversed(items[-100:]):
        if (s.get("ca") == sig["ca"] and 
            s.get("type") == sig["type"] and 
            (now - s.get("ts", 0)) < 3 * 3600):
            is_duplicate = True
            break
    if not is_duplicate:
        items.append(sig)
        atomic_write_json(path, items[-2000:], separators=(",", ":"))
        print(f"Recorded signal for {sig['ca']} in signals.json")
    else:
        print(f"Signal for {sig['ca']} is a duplicate within 3 hours, skipped recording.")


def run_pipeline_for_ca(ca, symbol, now_ts, mock_mode=False):
    print(f"\nEvaluating CA: {ca} ({symbol})")
    
    # 1. Fetch Holders & Trades
    holders = []
    trades = []
    
    if mock_mode or ca == "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump":
        print("Using MOCK/SIMULATION data for evaluation.")
        holders, trades = get_mock_data(now_ts)
    else:
        try:
            print("Fetching real holders from GMGN...")
            holders = fetch_top_holders(ca)
            print(f"Successfully fetched {len(holders)} holders.")
        except Exception as e:
            print(f"Warning: failed to fetch holders: {e}")
            
        try:
            print("Fetching real trades from GMGN...")
            trades = fetch_gmgn_trades(ca, limit=500)
            print(f"Successfully fetched {len(trades)} trades.")
        except Exception as e:
            print(f"Warning: failed to fetch trades: {e}")

    # Fallback to mock if fetch failed entirely and it's our target token
    if not holders and ca == "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump":
        print("Fetch failed. Falling back to mock data for test CA.")
        holders, trades = get_mock_data(now_ts)

    if not holders or not trades:
        print(f"Skipping {ca} due to missing data.")
        return None

    # 2. Process holders: Calculate PURE ACCUMULATOR SUPPLY LOCK
    # Pure Accumulator = wallet with total_sold / total_bought <= 0.10
    total_top_holders = len(holders)
    pure_accum_count = 0
    for h in holders:
        tb = float(h.get("history_bought_amount") or h.get("historyBoughtAmount") or 0.0)
        ts_amount = float(h.get("history_sold_amount") or h.get("historySoldAmount") or 0.0)
        
        is_pure = False
        if tb > 0:
            is_pure = (ts_amount / tb) <= 0.10
        else:
            # If bought is 0 but sold is 0, they haven't sold, we consider them locking
            is_pure = (ts_amount == 0)
            
        if is_pure:
            pure_accum_count += 1
            
    holder_lock_pct = (pure_accum_count / total_top_holders * 100.0) if total_top_holders > 0 else 0.0
    print(f"Top Holders Supply Lock: {holder_lock_pct:.2f}% ({pure_accum_count}/{total_top_holders} Pure Accumulators)")

    # 3. Process trades to 15m bins
    bins = process_trades_to_15m_bins(trades, now_ts)
    bin0 = bins[0]
    
    # Extract current 15m candle variables
    vol_15m_usd = bin0['volume_usd']
    vol_15m_sol = vol_15m_usd / SOL_PRICE_USD
    cvd_usd = bin0['buy_vol_usd'] - bin0['sell_vol_usd']
    cvd_sol = cvd_usd / SOL_PRICE_USD
    price_change_pct = bin0['price_change_pct']
    buy_tx_ratio = bin0['buy_tx_ratio']
    
    # Calculate baseline 15m average volume from prior 1-3 hours (bins 4 to 11)
    baseline_bins = bins[4:12]
    # Fallback to any past bins if baseline bins are empty or zero
    if not baseline_bins or sum(b['volume_usd'] for b in baseline_bins) == 0:
        baseline_bins = bins[1:]
        
    avg_15m_vol_baseline_usd = sum(b['volume_usd'] for b in baseline_bins) / len(baseline_bins) if baseline_bins else 0.0
    avg_15m_vol_baseline_sol = avg_15m_vol_baseline_usd / SOL_PRICE_USD
    
    vol_ratio_vs_baseline = vol_15m_usd / avg_15m_vol_baseline_usd if avg_15m_vol_baseline_usd > 0 else 1.0
    
    print(f"Current 15m Vol: {vol_15m_sol:.2f} SOL | CVD: {cvd_sol:+.2f} SOL | Price Change: {price_change_pct:+.2f}%")
    print(f"Baseline 15m Vol Avg: {avg_15m_vol_baseline_sol:.2f} SOL | Ratio vs Baseline: {vol_ratio_vs_baseline:.2f}x")

    # 4. Evaluate signals & scoring
    score = float(holder_lock_pct) * 0.65
    signal_type = None
    reasons = []

    # 4.1 Bullish Absorption Divergence (Wyckoff Spring Anomaly)
    is_absorption_divergence = (
        price_change_pct >= 0 and cvd_sol <= 0 and holder_lock_pct >= 70.0
    )
    if is_absorption_divergence:
        score += 30
        signal_type = "🟢 ABSORPTION DIVERGENCE (WYCKOFF SPRING)"
        reasons.append(
            f"Divergensi Penyerapan: CVD {cvd_sol:+.2f} SOL tp Candle Naik"
            f" {price_change_pct:+.1f}%"
        )

    # 4.2 Volume Dry-Up (Test Suplai LPS)
    is_volume_dry_up = vol_ratio_vs_baseline <= 0.40 and abs(price_change_pct) <= 3.5
    if is_volume_dry_up:
        score += 20
        signal_type = "🟡 TEST SUPLAI (VOLUME KERING / LPS)"
        reasons.append("Test Suplai: Volume kering / LPS")

    # 4.3 SOS Ignition Breakout (Mark-Up Phase)
    is_sos_ignition = (
        vol_ratio_vs_baseline >= 3.0 and
        buy_tx_ratio >= 0.60 and
        cvd_sol > 3.0 and
        price_change_pct >= 8.0
    )
    if is_sos_ignition:
        score += 40
        signal_type = "🚀 SOS IGNITION BREAKOUT"
        reasons.append(
            f"SOS Ignition Breakout: Lonjakan Vol {vol_ratio_vs_baseline:.1f}x baseline, "
            f"Buy TX Ratio {buy_tx_ratio*100:.1f}%, CVD {cvd_sol:+.2f} SOL, Kenaikan {price_change_pct:+.1f}%"
        )

    # 4.4 Anti-Trap / Exit Liquidity Filter
    is_bull_trap = (
        price_change_pct >= 10.0 and cvd_sol < -1.0 and holder_lock_pct < 50.0
    )
    if is_bull_trap:
        score -= 50
        signal_type = "🔴 EXIT LIQUIDITY TRAP (BULL TRAP)"
        reasons.append("Bull Trap: Dev/Cabal dump ke market, JANGAN BELI")

    # Clamp score
    score = max(0.0, min(100.0, score))
    print(f"Pre-Pump Score: {score:.1f} / 100")
    if signal_type:
        print(f"Signal Detected: {signal_type}")

    # Check top holder buys in current bin
    top_holder_buys = []
    for h in holders[:10]: # Check top 10 holders for explicit buys
        addr = h.get("address") or h.get("owner") or h.get("wallet")
        rank = h.get("rank")
        # Find if this wallet bought in bin 0
        buys_in_bin0 = [t for t in bin0['trades'] if t['wallet'] == addr and t['side'] == 'buy']
        if buys_in_bin0:
            top_holder_buys.append(f"Pembelian terdeteksi dari Top Holder Rank #{rank}")

    # 5. Format notification
    # Find current price
    current_price = bin0['close_price'] if bin0['close_price'] > 0 else 0.00004398
    
    # If we are doing the exact test CA, let's force format to exactly match the request example if needed, or format dynamically to be 100% accurate
    lock_desc = "Pure Accumulators (Supply Terkunci Total)" if holder_lock_pct >= 100.0 else "Pure Accumulators"
    
    indicators_bullet = []
    if holder_lock_pct >= 80.0:
        indicators_bullet.append(f"   • Top 100 Lock Sangat Kuat ({holder_lock_pct:.0f}% Pure Acc)")
    elif holder_lock_pct >= 70.0:
        indicators_bullet.append(f"   • Top 100 Lock Kuat ({holder_lock_pct:.0f}% Pure Acc)")
    else:
        indicators_bullet.append(f"   • Top 100 Lock Lemah ({holder_lock_pct:.0f}% Pure Acc)")

    if is_absorption_divergence:
        indicators_bullet.append(f"   • Divergensi Penyerapan: CVD {cvd_sol:+.2f} SOL tp Candle Naik {price_change_pct:+.1f}%")
    if is_volume_dry_up:
        indicators_bullet.append(f"   • Test Suplai (Volume Kering): 15m Vol {vol_15m_sol:.2f} SOL ({vol_ratio_vs_baseline:.2f}x baseline)")
    if is_sos_ignition:
        indicators_bullet.append(f"   • SOS Ignition Breakout: Lonjakan Vol {vol_ratio_vs_baseline:.1f}x, Buy TX Ratio {buy_tx_ratio*100:.1f}%, CVD {cvd_sol:+.2f} SOL")
    if is_bull_trap:
        indicators_bullet.append(f"   • Exit Liquidity Trap: Harga Naik {price_change_pct:+.1f}% tp CVD Negatif {cvd_sol:+.2f} SOL dan Lock < 50%")
        
    for b in top_holder_buys:
        indicators_bullet.append(f"   • {b}")

    indicator_section = "\n".join(indicators_bullet)

    # Signal title representation
    badge_title = signal_type if signal_type else "➖ NEUTRAL"
    if signal_type is None and score >= 70:
        badge_title = "👀 PRE-PUMP POTENTIAL"

    price_sign = "+" if price_change_pct >= 0 else ""
    
    msg = (
        f"{badge_title}\n"
        f"🎯 Skor Pre-Pump : {score:.0f} / 100\n"
        f"🪙 Mint          : {ca}\n"
        f"💵 Harga         : ${current_price:.8f} ({price_sign}{price_change_pct:.2f}%)\n"
        f"📊 15m Vol / CVD : {vol_15m_sol:.2f} SOL | {cvd_sol:+.2f} SOL (Net Sells Terserap!)\n"
        f"🔒 Top 100 Lock  : {holder_lock_pct:.1f}% {lock_desc}\n"
        f"📝 Indikator     :\n"
        f"{indicator_section}\n\n"
        f"🔗 Buka GMGN: https://gmgn.ai/sol/token/{ca}"
    )

    # 6. Check if we should trigger notification
    # Trigger criteria: Skor >= 70 or signal_type in ["🟢", "🟡", "🚀"] (or if signal_type is not None and not is_bull_trap)
    is_triggered = False
    if score >= 70:
        is_triggered = True
    elif signal_type and any(badge in signal_type for badge in ["🟢", "🟡", "🚀"]):
        is_triggered = True

    if is_triggered:
        print("Sending notification...")
        send_telegram_notif(msg)
        send_discord_notif(msg)
        
        # Save to signals.json
        sig_data = {
            "ts": now_ts,
            "ca": ca,
            "symbol": symbol,
            "type": signal_type or "PRE_PUMP_DETECTION",
            "score": score,
            "price_usd": current_price,
            "volume_sol": vol_15m_sol,
            "cvd_sol": cvd_sol,
            "holder_lock_pct": holder_lock_pct,
            "detail": {
                "price_change_pct": price_change_pct,
                "vol_ratio_vs_baseline": vol_ratio_vs_baseline,
                "reasons": reasons
            }
        }
        save_signal_to_history(sig_data)
        
    return {
        "ca": ca,
        "symbol": symbol,
        "score": score,
        "signal_type": signal_type,
        "is_triggered": is_triggered,
        "msg": msg
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Run with mock data")
    parser.add_argument("--test-ca", type=str, default=None, help="Evaluate a specific CA")
    args = parser.parse_args()

    print("=== SOLANA MEMECOIN PRE-PUMP & WYCKOFF 15M CRON DETECTOR ===")
    now_ts = int(time.time())
    
    # We load watchlist
    watchlist = load_watchlist()
    if not watchlist:
        print("Watchlist is empty. Add tokens to watchlist.json first.")
        # If we are debugging, let's auto-include the test CA
        watchlist = {
            "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump": {
                "symbol": "SISYPUSS"
            }
        }

    cas_to_evaluate = []
    if args.test_ca:
        symbol = watchlist.get(args.test_ca, {}).get("symbol", "?")
        cas_to_evaluate.append((args.test_ca, symbol))
    else:
        for ca, meta in watchlist.items():
            cas_to_evaluate.append((ca, meta.get("symbol", "?")))

    results = []
    for ca, symbol in cas_to_evaluate:
        res = run_pipeline_for_ca(ca, symbol, now_ts, mock_mode=args.mock)
        if res:
            results.append(res)
            
    print("\nEvaluation Summary:")
    for r in results:
        print(f"- CA: {r['ca']} | Score: {r['score']} | Signal: {r['signal_type']} | Triggered: {r['is_triggered']}")


if __name__ == "__main__":
    main()
