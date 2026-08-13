# -*- coding: utf-8 -*-
"""Offline tests for the 3-candle Wyckoff 15M cron detector.

Covers:
  1. Clock-aligned 15m binning
  2. C2 volume dry-up / C3 spring divergence
  3. Grade A / B / C classification + mute
  4. Smart-buyer tag + Top 100 filter
  5. SOS ignition + anti-trap (CVD < -2 SOL)
  6. Bearish divergence warning
  7. GMGN payload dual-shape + quote_amount sanitizer
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.prepump_wyckoff_cron as wd
from scripts.prepump_wyckoff_cron import (
    SIGNAL_BEARISH,
    SIGNAL_GRADE_A,
    SIGNAL_GRADE_B,
    SIGNAL_GRADE_C,
    SOL_PRICE_USD,
    apply_continuous_opens,
    baseline_avg_volume_sol,
    build_gmgn_trades_url,
    c3_bucket_start,
    classify_wyckoff_grade,
    clock_aligned_bucket,
    evaluate_anti_trap,
    evaluate_bearish_divergence,
    evaluate_sos_ignition,
    extract_holder_rows,
    extract_trade_rows,
    find_smart_buyers,
    format_candle_block,
    format_grade_a_message,
    format_signal_message,
    format_vol_sol,
    is_c2_volume_dry,
    ticker_label,
    is_c3_spring_divergence,
    parse_gmgn_trade,
    process_trades_to_15m_bins,
    sanitize_sol_quote_amount,
)

failures = []

# Fixed clock: C3 opens at this unix ts (divisible by 900), cron at +14 min.
C3 = 1_700_000_100
assert C3 % 900 == 0
NOW = C3 + 14 * 60
C2 = C3 - 900
C1 = C3 - 1800


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _t(wallet, side, sol, price, ts, tags=None):
    return {
        "wallet": wallet,
        "side": side,
        "usd": sol * SOL_PRICE_USD,
        "token_amount": (sol * SOL_PRICE_USD) / price if price else 0.0,
        "price": price,
        "ts": ts,
        "sol": sol,
        "quote_amount": sol,
        "tags": list(tags or []),
    }


def _holders(n=100, smart_rank=3):
    rows = []
    for i in range(1, n + 1):
        addr = (
            "Rank3TopHolderWalletAddressxxxxxxxxxxxxxx"
            if i == smart_rank else f"MockHolderAddress{i}xxxxxxxxxxxxxxxxxx"
        )
        rows.append({
            "address": addr,
            "rank": i,
            "balance": 10000.0 / i,
            "history_bought_amount": 10000.0 / i,
            "history_sold_amount": 0.0,
            "tags": ["top_holder"] if i <= 10 else [],
        })
    return rows


def _silence(mod=wd):
    saved = []
    sent = []
    orig = (
        mod.save_signal_to_history,
        mod.send_telegram_notif,
        mod.send_discord_notif,
    )
    mod.save_signal_to_history = lambda sig: saved.append(sig) or True
    mod.send_telegram_notif = lambda text: sent.append(("tg", text)) or True
    mod.send_discord_notif = lambda text: sent.append(("dc", text)) or True
    return saved, sent, orig


def _restore(orig, mod=wd):
    mod.save_signal_to_history, mod.send_telegram_notif, mod.send_discord_notif = orig


# ---------------------------------------------------------------------------
# 1. Clock-aligned binning
# ---------------------------------------------------------------------------
def test_clock_aligned_binning():
    check(clock_aligned_bucket(C3 + 14 * 60) == C3,
          "bucket at :14 stays on the official open")
    check(clock_aligned_bucket(C3 + 899) == C3,
          "last second of the candle stays in the same bucket")
    check(clock_aligned_bucket(C3 + 900) == C3 + 900,
          "exact next open starts a new bucket")
    check(c3_bucket_start(NOW) == C3,
          "C3 at cron :14 is the candle that is about to close")

    trades = [
        _t("A", "buy", 1.0, 0.001, C3 + 10),
        _t("B", "buy", 2.0, 0.001, C2 + 10),
        _t("C", "buy", 3.0, 0.001, C1 + 10),
        # Would have landed in "bin 0" of the old now-relative scheme
        # (NOW-15m = C3-60s) but must stay in C2 under clock alignment.
        _t("D", "buy", 4.0, 0.001, C3 - 30),
    ]
    bins = process_trades_to_15m_bins(trades, NOW)
    check(bins[0]["start"] == C3 and bins[0]["end"] == C3 + 900,
          "bin 0 is clock-aligned C3")
    check(abs(bins[0]["volume_sol"] - 1.0) < 1e-9,
          f"C3 only has the in-bucket trade (got {bins[0]['volume_sol']})")
    check(abs(bins[1]["volume_sol"] - 6.0) < 1e-9,
          f"C2 includes the pre-open trade (got {bins[1]['volume_sol']})")
    check(abs(bins[2]["volume_sol"] - 3.0) < 1e-9,
          f"C1 is the 30-45m official candle (got {bins[2]['volume_sol']})")


# ---------------------------------------------------------------------------
# 1b. Continuous open = previous close (TradingView / GMGN)
# ---------------------------------------------------------------------------
def test_continuous_open_vs_false_green():
    """Gap-down first print must not paint a fake green candle."""
    trades = [
        _t("C1", "buy", 5.0, 0.000040, C1 + 60),
        _t("C2", "buy", 2.0, 0.000040, C2 + 60),
        # Gap-down dump, then a bounce that STAYS below prev close.
        _t("Dump", "sell", 4.0, 0.000035, C3 + 30),
        _t("Bounce", "buy", 2.0, 0.000038, C3 + 80),
    ]
    bins = process_trades_to_15m_bins(trades, NOW)
    c3 = bins[0]
    c2 = bins[1]
    check(abs(c2["close_price"] - 0.000040) < 1e-12, "C2 close is 0.000040")
    check(c3["open_source"] == "prev_close",
          f"C3 open comes from prev close (got {c3['open_source']})")
    check(abs(c3["open_price"] - c2["close_price"]) < 1e-12,
          f"C3 open == C2 close (open={c3['open_price']}, prev={c2['close_price']})")
    check(abs(c3["first_trade_price"] - 0.000035) < 1e-12,
          "first print is the gap-down 0.000035")
    check(abs(c3["close_price"] - 0.000038) < 1e-12, "C3 close is the bounce")
    check(c3["price_change_pct"] < 0.0,
          f"gap-down that never reclaims prev close is RED "
          f"(chg={c3['price_change_pct']:+.2f}%)")
    check(c3["is_green"] is False, "is_green is False on a bear candle")
    check(is_c3_spring_divergence(c3) is False,
          "false-green bounce is not a Wyckoff spring")

    # Same dump, but last print reclaims the previous close → true green.
    reclaim = [
        _t("C1", "buy", 5.0, 0.000040, C1 + 60),
        _t("C2", "buy", 2.0, 0.000040, C2 + 60),
        _t("Dump", "sell", 4.0, 0.000035, C3 + 30),
        _t("Reclaim", "buy", 2.0, 0.000042, C3 + 80),
    ]
    c3r = process_trades_to_15m_bins(reclaim, NOW)[0]
    check(c3r["is_green"] is True and c3r["price_change_pct"] > 0,
          f"reclaim above prev close is true green "
          f"(chg={c3r['price_change_pct']:+.2f}%)")
    check(abs(c3r["open_price"] - 0.000040) < 1e-12,
          "reclaim candle still opens at prev close, not the dump print")


def test_apply_continuous_opens_empty_carry():
    """Empty bins carry the last close forward so the chain does not break."""
    slots = [
        {"open_price": 0.0, "close_price": 0.000044, "first_trade_price": 0.000044},
        {"open_price": 0.0, "close_price": 0.0, "first_trade_price": 0.0},
        {"open_price": 0.0, "close_price": 0.000040, "first_trade_price": 0.000040},
    ]
    apply_continuous_opens(slots, seed_close=0.0)
    check(abs(slots[2]["open_price"] - 0.000040) < 1e-12,
          "oldest bin falls back to its first print")
    check(abs(slots[1]["open_price"] - 0.000040) < 1e-12,
          "empty middle bin opens at carried close")
    check(abs(slots[1]["close_price"] - 0.000040) < 1e-12,
          "empty middle bin closes flat at carried close")
    check(abs(slots[0]["open_price"] - 0.000040) < 1e-12,
          "newest bin opens at the carried previous close")
    check(abs(slots[0]["close_price"] - 0.000044) < 1e-12,
          "newest close stays the last print")
    check(slots[0]["is_green"] is True, "newest bar is green vs carried open")


# ---------------------------------------------------------------------------
# 2. C2 dry / C3 spring
# ---------------------------------------------------------------------------
def test_c2_volume_dry_up():
    c1 = {"volume_sol": 10.0, "price_change_pct": 1.0}
    c2_dry = {"volume_sol": 2.0, "price_change_pct": 1.0}
    hit, drop = is_c2_volume_dry(c1, c2_dry)
    check(hit is True, f"80% drop + tight range is dry (drop={drop:.1f}%)")
    check(abs(drop - 80.0) < 1e-9, f"drop pct is 80 (got {drop})")

    c2_abs = {"volume_sol": 2.5, "price_change_pct": 0.5}
    c1_small = {"volume_sol": 4.0, "price_change_pct": 0.0}
    hit2, _ = is_c2_volume_dry(c1_small, c2_abs)
    check(hit2 is True, "absolute vol < 3.0 SOL still counts as dry")

    c2_wide = {"volume_sol": 2.0, "price_change_pct": 4.0}
    hit3, _ = is_c2_volume_dry(c1, c2_wide)
    check(hit3 is False, "|change| > 2.5% is not a LPS dry-up")

    empty_c1 = {"volume_sol": 0.0, "price_change_pct": 0.0}
    hit4, _ = is_c2_volume_dry(empty_c1, c2_dry)
    check(hit4 is False, "empty C1 is not a real dry-up")


def test_c3_spring_divergence():
    spring = {
        "open_price": 0.00004,
        "close_price": 0.000044,
        "price_change_pct": 10.0,
        "cvd_sol": -1.96,
        "volume_sol": 12.3,
    }
    check(is_c3_spring_divergence(spring) is True,
          "green candle + CVD -1.96 + vol 12.3 is a spring")

    red = dict(spring, close_price=0.00003, price_change_pct=-10.0)
    check(is_c3_spring_divergence(red) is False, "red candle is not a spring")

    pos_cvd = dict(spring, cvd_sol=0.1)
    check(is_c3_spring_divergence(pos_cvd) is False,
          "positive CVD is not a spring")

    tiny = dict(spring, volume_sol=0.4, cvd_sol=-0.2)
    check(is_c3_spring_divergence(tiny) is False,
          "volume < 0.50 SOL is not a spring")

    weak_cvd = dict(spring, cvd_sol=-0.04)
    check(is_c3_spring_divergence(weak_cvd) is False,
          "CVD >= -0.05 is not a spring")


# ---------------------------------------------------------------------------
# 3. Smart buyers
# ---------------------------------------------------------------------------
def test_smart_buyers_top_holder_and_tags():
    holders = _holders()
    trades = [
        _t("Rank3TopHolderWalletAddressxxxxxxxxxxxxxx", "buy", 5.0,
           0.00004, C3 + 60, tags=["top_holder"]),
        _t("SmartDegenWalletxxxxxxxxxxxxxxxxxxxxxxxxx", "buy", 1.2,
           0.00004, C3 + 70, tags=["smart_degen"]),
        _t("RandomRetailWalletxxxxxxxxxxxxxxxxxxxxxxx", "buy", 3.0,
           0.00004, C3 + 80),
        _t("Rank3TopHolderWalletAddressxxxxxxxxxxxxxx", "sell", 1.0,
           0.00004, C3 + 90),
    ]
    found = find_smart_buyers(trades, holders)
    addrs = {b["address"] for b in found}
    check("Rank3TopHolderWalletAddressxxxxxxxxxxxxxx" in addrs,
          "Top-3 holder buy is a smart buyer")
    check("SmartDegenWalletxxxxxxxxxxxxxxxxxxxxxxxxx" in addrs,
          "smart_degen tag is a smart buyer")
    check("RandomRetailWalletxxxxxxxxxxxxxxxxxxxxxxx" not in addrs,
          "untagged retail buy is ignored")
    rank3 = next(b for b in found if b["address"].startswith("Rank3"))
    check(rank3["in_top10"] is True, "rank 3 is flagged in_top10")
    check(abs(rank3["sol"] - 5.0) < 1e-9, "smart buyer SOL is the buy size")
    check("top_holder" in rank3["tags"], "top_holder tag is stored")


# ---------------------------------------------------------------------------
# 4. Grading
# ---------------------------------------------------------------------------
def _candles(dry=True, spring=True):
    c1 = {"volume_sol": 10.0, "price_change_pct": 0.5,
          "open_price": 0.00004, "close_price": 0.0000402}
    if dry:
        c2 = {"volume_sol": 2.0, "price_change_pct": 0.4,
              "open_price": 0.00004, "close_price": 0.00004016}
    else:
        c2 = {"volume_sol": 9.5, "price_change_pct": 0.4,
              "open_price": 0.00004, "close_price": 0.00004016}
    if spring:
        c3 = {"volume_sol": 12.3, "price_change_pct": 8.0,
              "open_price": 0.00004, "close_price": 0.0000432,
              "cvd_sol": -1.96}
    else:
        c3 = {"volume_sol": 12.3, "price_change_pct": 8.0,
              "open_price": 0.00004, "close_price": 0.0000432,
              "cvd_sol": 0.4}
    return c1, c2, c3


def test_grade_classification():
    smart = [{"in_top10": True, "sol": 5.0, "tags": ["top_holder"]}]
    c1, c2, c3 = _candles(dry=True, spring=True)
    a = classify_wyckoff_grade(c1, c2, c3, smart, holder_lock_pct=100.0)
    check(a["grade"] == "A", f"full setup is Grade A (got {a['grade']})")
    check(95.0 <= a["score"] <= 100.0, f"Grade A score 95-100 (got {a['score']})")
    check(a["signal_type"] == SIGNAL_GRADE_A, "Grade A uses golden-spring title")
    check(a["muted"] is False, "Grade A is not muted")

    b_dry = classify_wyckoff_grade(c1, c2, c3, [], holder_lock_pct=80.0)
    check(b_dry["grade"] == "B", "spring + dry without smart buyer is Grade B")
    check(b_dry["score"] == 80.0, f"Grade B score is 80 (got {b_dry['score']})")

    c1b, c2_wet, c3b = _candles(dry=False, spring=True)
    b_smart = classify_wyckoff_grade(c1b, c2_wet, c3b, smart, 80.0)
    check(b_smart["grade"] == "B", "spring + smart without dry is Grade B")

    c_noise = classify_wyckoff_grade(c1b, c2_wet, c3b, [], 80.0)
    check(c_noise["grade"] == "C", "spring alone is Grade C noise")
    check(c_noise["muted"] is True, "Grade C is muted")
    check(c_noise["score"] == 50.0,
          f"Grade C score is 50 (lock no longer bumps it, got {c_noise['score']})")

    no = classify_wyckoff_grade(c1, c2, _candles(spring=False)[2], smart, 80.0)
    check(no["grade"] is None, "no C3 spring → no grade")

    a0 = classify_wyckoff_grade(c1, c2, c3, smart, holder_lock_pct=0.0)
    a100 = classify_wyckoff_grade(c1, c2, c3, smart, holder_lock_pct=100.0)
    check(a0["score"] == a100["score"],
          "Grade A score ignores tautological holder lock")
    c0 = classify_wyckoff_grade(c1b, c2_wet, c3b, [], 0.0)
    check(c0["score"] == c_noise["score"] == 50.0,
          "Grade C score ignores lock >= 70 bump")


# ---------------------------------------------------------------------------
# 5. Full pipeline: Grade A mock
# ---------------------------------------------------------------------------
def test_grade_a_golden_spring_pipeline():
    saved, sent, orig = _silence()
    try:
        res = wd.run_pipeline_for_ca(
            "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump",
            "SISYPUSS", NOW, mock_mode=True)
    finally:
        _restore(orig)

    check(res is not None, "Grade A pipeline returned results")
    check(res["grade"] == "A", f"mock fixture is Grade A (got {res['grade']})")
    check(res["signal_type"] == SIGNAL_GRADE_A,
          f"signal type is golden spring (got {res['signal_type']})")
    check(95.0 <= res["score"] <= 100.0,
          f"Grade A score in 95-100 (got {res['score']})")
    check(res["is_triggered"] is True, "Grade A must notify")
    check(res["muted"] is False, "Grade A is not muted")
    check(len(res["smart_buyers"]) >= 1, "mock has a smart buyer")
    msg = res["msg"]
    check(SIGNAL_GRADE_A in msg, "message title is Grade A golden spring")
    check("$SISYPUSS" in msg, "message shows the token ticker")
    check("Urutan Candle" in msg, "message includes the 3-candle sequence")
    check("30-45m lalu" in msg, "C1 is labeled with its time window")
    check("Smart Buyers" in msg, "message lists smart buyers")
    check("https://gmgn.ai/sol/token/8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump"
          in msg, "message includes the GMGN link")
    check("C2 (Kering)" in msg, "message labels C2 as dry")
    check(len(sent) == 2, f"Telegram + Discord sent (got {len(sent)})")
    check(len(saved) == 1, "Grade A is recorded in signals.json")


def test_grade_b_partial_and_grade_c_mute():
    holders = _holders()
    # Grade B: dry C2 + spring C3, retail-only buys
    trades_b = [
        _t("Dummy", "buy", 10.0, 0.00004, C1 + 60),
        _t("Dummy", "buy", 2.0, 0.0000402, C2 + 60),
        _t("Seller", "sell", 4.0, 0.00004, C3 + 30),
        _t("Retailxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "buy", 2.0,
           0.000042, C3 + 80),
    ]
    # Grade C: wet C2 + spring C3, retail-only
    trades_c = [
        _t("Dummy", "buy", 10.0, 0.00004, C1 + 60),
        _t("Dummy", "buy", 9.5, 0.0000402, C2 + 60),
        _t("Seller", "sell", 4.0, 0.00004, C3 + 30),
        _t("Retailxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "buy", 2.0,
           0.000042, C3 + 80),
    ]

    def _run(trades):
        def fake_mock(_ts):
            return holders, trades
        saved, sent, orig = _silence()
        orig_mock = wd.get_mock_data
        wd.get_mock_data = fake_mock
        try:
            return wd.run_pipeline_for_ca("CA_TEST", "T", NOW, mock_mode=True), saved, sent
        finally:
            wd.get_mock_data = orig_mock
            _restore(orig)

    res_b, saved_b, sent_b = _run(trades_b)
    check(res_b["grade"] == "B", f"partial confirm is Grade B (got {res_b['grade']})")
    check(res_b["score"] == 80.0, f"Grade B score 80 (got {res_b['score']})")
    check(res_b["is_triggered"] is True, "Grade B score>=80 notifies")
    check(res_b["signal_type"] == SIGNAL_GRADE_B, "Grade B title")
    check(len(saved_b) == 1, "Grade B is recorded")
    check(len(sent_b) == 2, "Grade B sends Telegram + Discord")

    res_c, saved_c, sent_c = _run(trades_c)
    check(res_c["grade"] == "C", f"no confirm is Grade C (got {res_c['grade']})")
    check(res_c["muted"] is True, "Grade C is muted")
    check(res_c["is_triggered"] is False, "Grade C does not notify")
    check(res_c["signal_type"] == SIGNAL_GRADE_C, "Grade C title")
    check(len(saved_c) == 0, "Grade C is not written to signals.json")
    check(len(sent_c) == 0, "Grade C sends no notification")


def test_false_green_gap_down_not_grade_a():
    """Smart buyer + dry C2 + CVD minus is NOT Grade A if C3 is red vs prev close."""
    holders = _holders()
    trades = [
        _t("Dummy", "buy", 10.0, 0.000040, C1 + 60),
        _t("Dummy", "buy", 2.0, 0.000040, C2 + 60),
        _t("Seller", "sell", 7.13, 0.000035, C3 + 30),
        _t("Rank3TopHolderWalletAddressxxxxxxxxxxxxxx", "buy", 5.0,
           0.000038, C3 + 80, tags=["top_holder"]),
    ]

    def fake_mock(_ts):
        return holders, trades

    saved, sent, orig = _silence()
    orig_mock = wd.get_mock_data
    wd.get_mock_data = fake_mock
    try:
        res = wd.run_pipeline_for_ca("CA_FAKE_GREEN", "FG", NOW, mock_mode=True)
    finally:
        wd.get_mock_data = orig_mock
        _restore(orig)

    check(res is not None, "false-green pipeline returned")
    check(res["c3"]["price_change_pct"] < 0.0,
          f"C3 is red vs prev close (chg={res['c3']['price_change_pct']:+.2f}%)")
    check(res["grade"] != "A",
          f"false-green must not be Grade A (got {res['grade']})")
    check(res["signal_type"] != SIGNAL_GRADE_A,
          "absorption / golden spring is not tagged on a red candle")
    check(is_c3_spring_divergence(res["c3"]) is False,
          "spring helper rejects the gap-down bounce")


# ---------------------------------------------------------------------------
# 6. SOS / anti-trap / bearish
# ---------------------------------------------------------------------------
def test_sos_ignition_breakout():
    trades = [
        _t("A", "buy", 10.0, 0.000046, C3 + 10 * 60),
        _t("D", "buy", 1.0, 0.000046, C3 + 12 * 60),
        _t("B", "sell", 0.1, 0.000040, C3 + 60),
    ]
    for i in range(4, 12):
        trades.append(_t("C", "buy", 2.0, 0.000040, C3 - i * 900 + 5 * 60))
    bins = process_trades_to_15m_bins(trades, NOW)
    baseline = baseline_avg_volume_sol(bins)
    hit, ratio = evaluate_sos_ignition(bins[0], baseline)
    check(hit is True,
          f"SOS fires (ratio={ratio:.2f}, buy={bins[0]['buy_tx_ratio']*100:.1f}%, "
          f"CVD={bins[0]['cvd_sol']:+.2f}, px={bins[0]['price_change_pct']:+.1f}%)")


def test_anti_trap_exit_liquidity():
    c3 = {
        "price_change_pct": 12.0,
        "cvd_sol": -2.5,
        "volume_sol": 8.0,
        "open_price": 0.00004,
        "close_price": 0.0000448,
        "buy_tx_ratio": 0.4,
    }
    check(evaluate_anti_trap(c3, 40.0) is True,
          " +12% / CVD -2.5 is an exit-liquidity trap")
    check(evaluate_anti_trap(c3, 70.0) is True,
          "lock no longer gates the trap (tautological Top-N metric)")
    check(evaluate_anti_trap(c3) is True,
          "holder_lock_pct argument is optional")
    weak = dict(c3, cvd_sol=-1.5)
    check(evaluate_anti_trap(weak, 40.0) is False,
          "CVD > -2.0 SOL is not a trap (new threshold)")


def test_bearish_divergence():
    def fake_mock(ts):
        holders = _holders()
        trades = [
            # Previous official close sits above C3 so continuous-open
            # paints a true red candle (not a flat carry from 0.00004).
            _t("Prev", "buy", 2.0, 0.00005, C2 + 5 * 60),
            _t("SellerA", "sell", 5.0, 0.00005, C3 + 2 * 60),
            _t("BuyerA", "buy", 10.0, 0.00004, C3 + 10 * 60),
        ]
        for i in range(4, 12):
            trades.append(_t("Dummy", "buy", 2.0, 0.00004, C3 - i * 900 + 5 * 60))
        return holders, trades

    saved, sent, orig = _silence()
    orig_mock = wd.get_mock_data
    wd.get_mock_data = fake_mock
    try:
        res = wd.run_pipeline_for_ca(
            "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump",
            "SISYPUSS", NOW, mock_mode=True)
    finally:
        wd.get_mock_data = orig_mock
        _restore(orig)

    check(res is not None, "bearish pipeline returned results")
    check(res["signal_type"] == SIGNAL_BEARISH,
          f"signal is bearish divergence (got {res['signal_type']})")
    check(res["is_triggered"] is True, "bearish divergence still notifies")
    check("HATI-HATI" in res["msg"], "message contains HATI-HATI warning")
    check("Net Buys Dominan!" in res["msg"],
          "positive CVD uses Net Buys Dominan")
    check(evaluate_bearish_divergence(res["c3"]) is True,
          "C3 itself is classified as bearish")


# ---------------------------------------------------------------------------
# 7. GMGN robustness
# ---------------------------------------------------------------------------
def test_gmgn_holders_dual_shape():
    via_holders = extract_holder_rows({
        "data": {"holders": [{"address": "AAA", "rank": 1}]}
    })
    via_list = extract_holder_rows({
        "data": {"list": [{"address": "BBB", "rank": 2}]}
    })
    via_top = extract_holder_rows({
        "data": [{"address": "CCC"}]
    })
    check(len(via_holders) == 1 and via_holders[0]["address"] == "AAA",
          "data.holders is accepted")
    check(len(via_list) == 1 and via_list[0]["address"] == "BBB",
          "data.list is accepted")
    check(len(via_top) == 1 and via_top[0]["address"] == "CCC",
          "data-as-list is accepted")


def test_gmgn_trades_url_and_parser():
    url = build_gmgn_trades_url("SoMeCA")
    check("/vas/api/v1/token_trades/sol/SoMeCA" in url,
          "trades URL uses the VAS endpoint")
    check("event=buy" in url and "event=sell" in url,
          "URL requests both buy and sell events")
    check("limit=100" in url, "URL pages 100 trades")
    check("min_amount_usd=1" in url, "URL filters dust under $1")

    rows = extract_trade_rows({
        "data": {"list": [{
            "maker": "WalletX",
            "event": "buy",
            "amount_usd": 150.0,
            "quote_amount": 1.0,
            "amount_token": 1000,
            "price": 0.15,
            "timestamp": C3 + 10,
            "maker_tags": ["smart_degen"],
        }]}
    })
    check(len(rows) == 1, "data.list trades are accepted")
    parsed = parse_gmgn_trade(rows[0])
    check(parsed is not None and parsed["side"] == "buy", "trade side mapped")
    check(parsed["wallet"] == "WalletX", "maker mapped to wallet")
    check("smart_degen" in parsed["tags"], "maker_tags survive parsing")
    check(abs(parsed["sol"] - 1.0) < 1e-9, "quote_amount 1.0 SOL is trusted")


def test_quote_amount_sanitizer():
    ok = sanitize_sol_quote_amount(150.0, 1.0, 150.0)
    check(abs(ok - 1.0) < 1e-9, "implied $150/SOL keeps quote_amount")

    too_cheap = sanitize_sol_quote_amount(150.0, 50.0, 150.0)  # $3/SOL
    check(abs(too_cheap - 1.0) < 1e-9,
          f"implied <$10/SOL falls back to usd/px (got {too_cheap})")

    too_rich = sanitize_sol_quote_amount(150.0, 0.1, 150.0)  # $1500/SOL
    check(abs(too_rich - 1.0) < 1e-9,
          f"implied >$500/SOL falls back to usd/px (got {too_rich})")

    glitched_px = sanitize_sol_quote_amount(150.0, 0.0, 5.0)
    check(abs(glitched_px - 1.0) < 1e-9,
          "converter price <$10 is itself replaced by the $150 fallback")

    lamports = sanitize_sol_quote_amount(150.0, 1_000_000_000, 150.0)
    check(abs(lamports - 1.0) < 1e-9,
          f"raw lamports quote is scaled to 1 SOL (got {lamports})")


def test_grade_a_message_format():
    msg = format_grade_a_message(
        "8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump",
        98, 0.00004398, 22.51, 12.30, -1.96, 100.0,
        10.0, 2.1, 12.30, 79.0,
        [{"short": "Rank...xxxx", "tags": ["top_holder"], "sol": 5.0}],
        symbol="SISYPUSS",
    )
    check(msg.splitlines()[0] == SIGNAL_GRADE_A,
          "first line is the Grade A title")
    check("🪙 $SISYPUSS" in msg, "ticker sits under the title")
    check("🎯 Skor Pre-Pump : 98 / 100" in msg, "score line matches the spec")
    check("<code>8HykgZKXNpMhfxQtDPb7AayRKJonZaQ8Mw1Xo3xmpump</code>" in msg,
          "mint is wrapped in copyable <code>")
    check("C1 · 30-45m lalu : 10.00 SOL" in msg, "C1 shows SOL not S")
    check("C2 (Kering) · 15-30m lalu : 2.10 SOL  · turun 79.0% vs C1"
          in msg, "C2 dry drop is labeled vs C1")
    check("C3 (Spring) · sekarang    : 12.30 SOL" in msg,
          "C3 spring volume is on its own line")
    check("• Rank...xxxx — top_holder · 5.00 SOL" in msg,
          "smart-buyer is one wallet per line")
    check("0.00S" not in msg, "legacy 0.00S shorthand is gone")


def test_ticker_and_empty_c1_label():
    check(ticker_label("hwg") == "$HWG", "ascii ticker is uppercased")
    check(ticker_label("$hwg") == "$HWG", "leading $ is not doubled")
    check(ticker_label("?") == "", "unknown ticker is omitted")
    check(ticker_label("") == "", "empty ticker is omitted")
    check(format_vol_sol(0) == "0.00 SOL — sepi (tidak ada trade)",
          "zero volume is labeled sepi, not 0.00S")
    check(format_vol_sol(8.62) == "8.62 SOL", "positive volume stays numeric")
    block = format_candle_block(0.0, 1.80, 8.62, 0.0)
    check("C1 · 30-45m lalu : 0.00 SOL — sepi (tidak ada trade)" in block,
          "empty C1 explains there were no trades")
    check("turun" not in block,
          "drop % is hidden when C1 has no baseline volume")
    check("0.00S" not in block, "S-suffix volume is not used")


def test_sos_message_includes_symbol():
    msg = format_signal_message(
        wd.SIGNAL_SOS,
        "A6mrpBeeNKm743fiNg8Mrz7pj7uGML5rgDjWo4nrpump",
        93, 0.00003403, 14.29, 8.62, 8.08, 100.0,
        0.0, 1.80, 8.62, 0.0,
        [
            {"short": "GrgB...PjDy", "tags": ["bluechip_owner"],
             "sol": 4.46},
            {"short": "FtZ9...yGDC",
             "tags": ["fresh_wallet", "top_holder"], "sol": 3.20},
        ],
        extra_lines=[
            "📝 Indikator : SOS 3.2x · Buy TX 66.7% · CVD +8.08 SOL"
        ],
        symbol="hwg",
    )
    check(msg.splitlines()[0] == wd.SIGNAL_SOS, "SOS title is first")
    check("🪙 $HWG" in msg, "SOS alert shows $HWG")
    check("sepi (tidak ada trade)" in msg,
          "C1 0.00 SOL is explained as empty")
    check("(0.0%)" not in msg, "meaningless 0.0% drop is not shown")
    check("• GrgB...PjDy — bluechip_owner · 4.46 SOL" in msg,
          "first smart buyer is on its own line")
    check("• FtZ9...yGDC — fresh_wallet, top_holder · 3.20 SOL" in msg,
          "tags are comma-spaced")
    check("📝 Indikator : SOS 3.2x" in msg, "SOS indikator line is kept")
    gmgn = ("https://gmgn.ai/sol/token/"
            "A6mrpBeeNKm743fiNg8Mrz7pj7uGML5rgDjWo4nrpump")
    check(gmgn in msg, "GMGN link is present")


if __name__ == "__main__":
    print("=== test_clock_aligned_binning ===")
    test_clock_aligned_binning()
    print("=== test_continuous_open_vs_false_green ===")
    test_continuous_open_vs_false_green()
    print("=== test_apply_continuous_opens_empty_carry ===")
    test_apply_continuous_opens_empty_carry()
    print("=== test_c2_volume_dry_up ===")
    test_c2_volume_dry_up()
    print("=== test_c3_spring_divergence ===")
    test_c3_spring_divergence()
    print("=== test_smart_buyers_top_holder_and_tags ===")
    test_smart_buyers_top_holder_and_tags()
    print("=== test_grade_classification ===")
    test_grade_classification()
    print("=== test_grade_a_golden_spring_pipeline ===")
    test_grade_a_golden_spring_pipeline()
    print("=== test_grade_b_partial_and_grade_c_mute ===")
    test_grade_b_partial_and_grade_c_mute()
    print("=== test_false_green_gap_down_not_grade_a ===")
    test_false_green_gap_down_not_grade_a()
    print("=== test_sos_ignition_breakout ===")
    test_sos_ignition_breakout()
    print("=== test_anti_trap_exit_liquidity ===")
    test_anti_trap_exit_liquidity()
    print("=== test_bearish_divergence ===")
    test_bearish_divergence()
    print("=== test_gmgn_holders_dual_shape ===")
    test_gmgn_holders_dual_shape()
    print("=== test_gmgn_trades_url_and_parser ===")
    test_gmgn_trades_url_and_parser()
    print("=== test_quote_amount_sanitizer ===")
    test_quote_amount_sanitizer()
    print("=== test_grade_a_message_format ===")
    test_grade_a_message_format()
    print("=== test_ticker_and_empty_c1_label ===")
    test_ticker_and_empty_c1_label()
    print("=== test_sos_message_includes_symbol ===")
    test_sos_message_includes_symbol()

    if failures:
        print(f"\nFAILED ({len(failures)} failures)")
        for item in failures:
            print(" -", item)
        sys.exit(1)
    print("\nALL PASSED")
