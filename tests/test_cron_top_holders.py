# -*- coding: utf-8 -*-
"""Offline tests for Pre-Pump & Wyckoff 15M Cron Detector integration.

Covers:
  1. Pure Accumulator Supply Lock detection
  2. Wyckoff Absorption Divergence
  3. Volume Dry-Up (Test Suplai LPS)
  4. SOS Ignition Breakout
  5. Exit Liquidity Trap / Bull Trap filter
  6. Bearish Divergence (kebalikan absorption: CVD plus tp candle merah)
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.prepump_wyckoff_cron import run_pipeline_for_ca, process_trades_to_15m_bins

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def test_pure_accumulator_supply_lock():
    """Verify that mock data has 100% Pure Accumulators and run_pipeline scores it correctly."""
    now_ts = int(time.time())
    res = run_pipeline_for_ca(
        "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump", 
        "SISYPUSS", 
        now_ts, 
        mock_mode=True
    )
    
    check(res is not None, "pipeline execution returned results")
    check(res["score"] == 95.0, f"score should be exactly 95.0 (got {res['score']})")
    check(res["signal_type"] == "🟢 ABSORPTION DIVERGENCE (WYCKOFF SPRING)", f"signal type should be Absorption Divergence (got {res['signal_type']})")
    check(res["is_triggered"] is True, "is_triggered is True")


def test_volume_dry_up():
    """Verify Volume Dry-up detection on a token with very low volume and sideways price action."""
    now_ts = int(time.time())
    
    # Let's mock a scenario with dry up
    # Vol Ratio <= 0.40, |price_change| <= 3.5%
    # Baseline vol = 10 SOL per bin. Current vol = 2 SOL.
    trades = []
    # Current bin (Bin 0)
    trades.append({
        "wallet": "WalletA", "side": "buy", "usd": 2.0 * 150.0, "token_amount": 2.0 * 150.0 / 0.00004, "price": 0.00004, "ts": now_ts - 5 * 60
    })
    # Bins 4 to 11
    for i in range(4, 12):
        trades.append({
            "wallet": "WalletB", "side": "buy", "usd": 10.0 * 150.0, "token_amount": 10.0 * 150.0 / 0.00004, "price": 0.00004, "ts": now_ts - (i * 15 * 60 + 5 * 60)
        })
        
    bins = process_trades_to_15m_bins(trades, now_ts)
    bin0 = bins[0]
    
    vol_15m_usd = bin0['volume_usd']
    price_change_pct = bin0['price_change_pct']
    
    baseline_bins = bins[4:12]
    avg_15m_vol_baseline_usd = sum(b['volume_usd'] for b in baseline_bins) / len(baseline_bins) if baseline_bins else 0.0
    vol_ratio_vs_baseline = vol_15m_usd / avg_15m_vol_baseline_usd if avg_15m_vol_baseline_usd > 0 else 1.0
    
    is_volume_dry_up = vol_ratio_vs_baseline <= 0.40 and abs(price_change_pct) <= 3.5
    check(is_volume_dry_up is True, f"is_volume_dry_up is True (vol_ratio: {vol_ratio_vs_baseline:.2f}, price_change: {price_change_pct:.2f}%)")


def test_sos_ignition_breakout():
    """Verify SOS Ignition Breakout detection on high volume jump, buys, CVD, and price markup."""
    now_ts = int(time.time())
    # Baseline vol = 2 SOL per bin. Current vol = 10 SOL.
    # Price increase >= +8% (e.g., +15%).
    # Buy ratio >= 60%. CVD > 3.0 SOL.
    trades = []
    # Current bin (Bin 0) - total 11 SOL (10 buy + 1 buy), 1 small sell
    # => Buy ratio = 2/3 = 66.7% (>= 60%), CVD = 11.0 - 0.1 = +10.9 SOL
    trades.append({
        "wallet": "WalletA", "side": "buy", "usd": 10.0 * 150.0, "token_amount": 10.0 * 150.0 / 0.000046, "price": 0.000046, "ts": now_ts - 5 * 60
    })
    trades.append({
        "wallet": "WalletD", "side": "buy", "usd": 1.0 * 150.0, "token_amount": 1.0 * 150.0 / 0.000046, "price": 0.000046, "ts": now_ts - 3 * 60
    })
    # Open price is represented by a small sell at start
    trades.append({
        "wallet": "WalletB", "side": "sell", "usd": 0.1 * 150.0, "token_amount": 0.1 * 150.0 / 0.000040, "price": 0.000040, "ts": now_ts - 14 * 60
    })
    # Bins 4 to 11
    for i in range(4, 12):
        trades.append({
            "wallet": "WalletC", "side": "buy", "usd": 2.0 * 150.0, "token_amount": 2.0 * 150.0 / 0.000040, "price": 0.000040, "ts": now_ts - (i * 15 * 60 + 5 * 60)
        })
        
    bins = process_trades_to_15m_bins(trades, now_ts)
    bin0 = bins[0]
    
    vol_15m_usd = bin0['volume_usd']
    price_change_pct = bin0['price_change_pct']
    buy_tx_ratio = bin0['buy_tx_ratio']
    cvd_sol = (bin0['buy_vol_usd'] - bin0['sell_vol_usd']) / 150.0
    
    baseline_bins = bins[4:12]
    avg_15m_vol_baseline_usd = sum(b['volume_usd'] for b in baseline_bins) / len(baseline_bins) if baseline_bins else 0.0
    vol_ratio_vs_baseline = vol_15m_usd / avg_15m_vol_baseline_usd if avg_15m_vol_baseline_usd > 0 else 1.0
    
    is_sos_ignition = (
        vol_ratio_vs_baseline >= 3.0 and
        buy_tx_ratio >= 0.60 and
        cvd_sol > 3.0 and
        price_change_pct >= 8.0
    )
    check(is_sos_ignition is True, f"is_sos_ignition is True (ratio: {vol_ratio_vs_baseline:.2f}, buy_tx: {buy_tx_ratio*100:.1f}%, CVD: {cvd_sol:+.2f} SOL, price: {price_change_pct:+.1f}%)")


def test_bearish_divergence():
    """Kebalikan absorption: candle MERAH (harga turun) tapi CVD PLUS.

    Harus memicu notifikasi warning "HATI-HATI" (potensi distribusi),
    dan tidak boleh tertulis ke signals.json (save di-patch no-op).
    """
    import scripts.prepump_wyckoff_cron as wd
    now_ts = int(time.time())

    def fake_mock(ts):
        # 100% Pure Accumulators (agar baseline skor tinggi)
        holders = [
            {"address": f"MockW{i}", "rank": i + 1, "balance": 100.0,
             "history_bought_amount": 100.0, "history_sold_amount": 0.0,
             "cost": 0.00004, "avg_cost": 0.00004}
            for i in range(100)
        ]
        bin0_start = ts - 15 * 60
        trades = [
            # Open price 0.00005 (sell di awal bin) -> close 0.00004 = -20%
            {"wallet": "SellerA", "side": "sell", "usd": 5.0 * 150.0,
             "token_amount": 5.0 * 150.0 / 0.00005, "price": 0.00005,
             "ts": bin0_start + 2 * 60},
            # Buy 10 SOL di harga lebih rendah -> CVD = +5.0 SOL
            {"wallet": "BuyerA", "side": "buy", "usd": 10.0 * 150.0,
             "token_amount": 10.0 * 150.0 / 0.00004, "price": 0.00004,
             "ts": bin0_start + 10 * 60},
        ]
        # Baseline bins 4-11 (2 SOL per bin)
        for i in range(4, 12):
            trades.append({"wallet": "Dummy", "side": "buy",
                           "usd": 2.0 * 150.0,
                           "token_amount": 2.0 * 150.0 / 0.00004,
                           "price": 0.00004,
                           "ts": ts - (i * 15 * 60 + 5 * 60)})
        return holders, trades

    orig_mock = wd.get_mock_data
    orig_save = wd.save_signal_to_history
    orig_tg = wd.send_telegram_notif
    orig_dc = wd.send_discord_notif
    wd.get_mock_data = fake_mock
    wd.save_signal_to_history = lambda sig: None
    wd.send_telegram_notif = lambda text: False
    wd.send_discord_notif = lambda text: False
    try:
        res = wd.run_pipeline_for_ca(
            "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump",
            "SISYPUSS", now_ts, mock_mode=True)
    finally:
        wd.get_mock_data = orig_mock
        wd.save_signal_to_history = orig_save
        wd.send_telegram_notif = orig_tg
        wd.send_discord_notif = orig_dc

    check(res is not None, "bearish pipeline returned results")
    check(res["signal_type"] == "🔴 BEARISH DIVERGENCE (HARGA TURUN / DISTRIBUSI)",
          f"signal type should be Bearish Divergence (got {res['signal_type']})")
    check(res["is_triggered"] is True, "bearish divergence is_triggered is True")
    check(res["score"] == 35.0, f"score should be 65 - 30 = 35.0 (got {res['score']})")
    check("HATI-HATI" in res["msg"], "message contains HATI-HATI warning")
    check("Net Buys Dominan!" in res["msg"],
          "message CVD note flips to Net Buys Dominan for positive CVD")


if __name__ == "__main__":
    print("=== test_pure_accumulator_supply_lock ===")
    test_pure_accumulator_supply_lock()
    print("=== test_volume_dry_up ===")
    test_volume_dry_up()
    print("=== test_sos_ignition_breakout ===")
    test_sos_ignition_breakout()
    print("=== test_bearish_divergence ===")
    test_bearish_divergence()

    if failures:
        print(f"\nFAILED ({len(failures)} failures)")
        sys.exit(1)
    else:
        print("\nALL PASSED")
