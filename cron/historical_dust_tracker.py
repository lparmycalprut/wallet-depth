#!/usr/bin/env python3
"""
Historical Dust % Market Cap Tracker

Simpan persentase Market Cap yang dipegang oleh dust wallets ($0-$10)
setiap jam untuk token $MORTY.

Cara pakai:
    python3 cron/historical_dust_tracker.py MORTY_ADDRESS

Atau tambahkan ke crontab:
    0 * * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py MORTY_CA

Contoh:
    0 * * * * /usr/bin/python3 /home/user/wallet-depth/cron/historical_dust_tracker.py 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Path file database
CRON_DIR = Path(__file__).parent
DB_PATH = CRON_DIR / "dust_history.json"

# Token Address (bisa di-override via command line)
DEFAULT_TOKEN_CA = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"  # $MORTY


def init_db():
    """Inisialisasi database JSON jika belum ada."""
    if not DB_PATH.exists():
        with open(DB_PATH, "w") as f:
            json.dump({"entries": []}, f, indent=2)


def load_db():
    """Load database dari file."""
    init_db()
    with open(DB_PATH, "r") as f:
        return json.load(f)


def save_db(db):
    """Simpan database ke file."""
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2)


def get_dust_percentage(token_ca):
    """
    Ambil % Market Cap dust wallets ($0-$10) untuk token.
    
    Menggunakan fungsi yang sudah ada di holder_analysis.py
    """
    try:
        from holder_analysis import analyze_token, classify_holders, fetch_holders
        from core import get_market
        
        # Ambil data market
        market = get_market(token_ca)
        if not market:
            print(f"[ERROR] Market data not found for {token_ca}")
            return None
        
        market_cap = float(market.get("marketcap") or 0)
        price = float(market.get("price_usd") or 0)
        symbol = str(market.get("symbol") or "?")
        
        if market_cap <= 0 or price <= 0:
            print(f"[ERROR] Invalid market data: MC={market_cap}, Price={price}")
            return None
        
        # Ambil snapshot holders
        snapshot = fetch_holders(
            token_ca,
            max_wallets=3000,
            timeout=30,
            price_usd=price
        )
        
        if not snapshot.get("holders"):
            print(f"[ERROR] No holders data for {token_ca}")
            return None
        
        # Klasifikasi holders
        holder_stats = classify_holders(snapshot, market_cap, dust_limit=10.0)
        
        dust_pct_mc = holder_stats.get("dust_pct_mc")
        
        if dust_pct_mc is None:
            print(f"[ERROR] dust_pct_mc not available")
            return None
        
        print(f"[SUCCESS] Dust % MCAP: {dust_pct_mc:.4f}%")
        return float(dust_pct_mc)
        
    except Exception as e:
        print(f"[ERROR] Failed to get dust percentage: {e}")
        import traceback
        traceback.print_exc()
        return None


def save_dust_data(token_ca, dust_percentage):
    """Simpan data dust percentage ke database."""
    db = load_db()
    
    now = datetime.now()
    
    entry = {
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "token_ca": token_ca,
        "dust_percentage": round(dust_percentage, 4),
        "dust_percentage_display": f"{dust_percentage:.4f}%"
    }
    
    db["entries"].append(entry)
    
    # Keep only last 30 days of data
    thirty_days_ago = now - timedelta(days=30)
    db["entries"] = [
        e for e in db["entries"]
        if datetime.fromisoformat(e["timestamp"]) >= thirty_days_ago
    ]
    
    save_db(db)
    print(f"[SAVED] {now.isoformat()} - Dust: {dust_percentage:.4f}%")


def main():
    # Ambil token address dari command line atau gunakan default
    token_ca = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TOKEN_CA
    
    print(f"[START] Tracking dust % MCAP for {token_ca}")
    print(f"[TIME] {datetime.now().isoformat()}")
    
    # Ambil % dust
    dust_percentage = get_dust_percentage(token_ca)
    
    if dust_percentage is not None:
        # Simpan ke database
        save_dust_data(token_ca, dust_percentage)
        print(f"[DONE] Successfully saved dust data")
    else:
        print(f"[FAILED] Could not retrieve dust percentage")
        sys.exit(1)


if __name__ == "__main__":
    main()
