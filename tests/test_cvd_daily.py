"""Offline checks for the GMGN extension-compatible daily CVD model."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cvd_daily import (calculate_daily_cvd, first_buy_surge,
                       latest_dry_signal)


def test_daily_accounting_and_dry_status():
    day1 = 1704067200
    rows = []
    for i in range(10):
        rows.append(("buy", 10, day1 + i * 60, f"a{i}"))
    for i in range(10):
        rows.append(("sell", 10, day1 + i * 60 + 30, f"b{i}"))
    day2 = day1 + 86400
    rows += [("buy", 3, day2 + i * 60, f"c{i}") for i in range(5)]
    rows += [("sell", 2.5, day2 + i * 60 + 30, f"d{i}") for i in range(5)]
    out = calculate_daily_cvd(rows)
    assert out[0]["delta_sol"] == 0
    assert out[1]["volume_change_pct"] == -86.25
    assert out[1]["status"].startswith("KERING")
    assert latest_dry_signal(out) is out[1]


T0 = 1_700_000_000


def _valid_surge_rows():
    """10 buy (3 big) + 2 sell kecil dalam 15 menit — semua kaki lolos."""
    rows = []
    amounts = [1.5, 1.2, 1.1, 0.6, 0.6, 0.6, 0.5, 0.5, 0.5, 0.5]
    for i, amt in enumerate(amounts):
        rows.append(("buy", amt, T0 - 800 + i * 60, f"buyer{i}"))
    rows.append(("sell", 0.4, T0 - 700, "seller0"))
    rows.append(("sell", 0.3, T0 - 650, "seller1"))
    return rows


def test_first_buy_surge_triggers_on_valid_markup_start():
    stats = first_buy_surge(_valid_surge_rows(), baseline_hourly_sol=2.0,
                            now_ts=T0)
    assert stats["triggered"], stats["reasons"]
    assert stats["checks"] == {"volume": True, "buy_ratio": True,
                               "cvd_velocity": True, "big_buy_cluster": True}
    assert stats["big_buys"] == 3 and stats["big_sells"] == 0
    assert stats["surge_pct"] > 100.0  # 8.3 SOL/15m vs 2 SOL/jam kering


def test_first_buy_surge_rejects_small_volume_surge():
    # Baseline kering 10 SOL/jam -> 8.3 SOL/15m bukan lonjakan.
    stats = first_buy_surge(_valid_surge_rows(), baseline_hourly_sol=10.0,
                            now_ts=T0)
    assert not stats["triggered"]
    assert not stats["checks"]["volume"]


def test_first_buy_surge_rejects_low_buy_ratio():
    # 6 buy vs 5 sell -> 55% < 60% (kaki lain tetap lolos).
    rows = [("buy", amt, T0 - 800 + i * 60, f"buyer{i}")
            for i, amt in enumerate([1.5, 1.2, 1.1, 0.5, 0.5, 0.5])]
    rows += [("sell", 0.3, T0 - 500 + i * 30, f"seller{i}") for i in range(5)]
    stats = first_buy_surge(rows, baseline_hourly_sol=2.0, now_ts=T0)
    assert not stats["triggered"]
    assert not stats["checks"]["buy_ratio"]
    assert stats["checks"]["volume"] and stats["checks"]["cvd_velocity"]


def test_first_buy_surge_rejects_flat_cvd_velocity():
    # Buy tx mendominasi tapi sell value besar -> Delta/Volume < +20%.
    rows = [("buy", 1.0, T0 - 800 + i * 60, f"buyer{i}") for i in range(3)]
    rows += [("buy", 0.3, T0 - 600 + i * 30, f"buyerx{i}") for i in range(6)]
    rows += [("sell", 0.7, T0 - 500 + i * 30, f"seller{i}") for i in range(5)]
    stats = first_buy_surge(rows, baseline_hourly_sol=2.0, now_ts=T0)
    assert stats["checks"]["buy_ratio"]          # 9/14 = 64%
    assert not stats["checks"]["cvd_velocity"]   # 1.3/8.3 = +15.7%
    assert not stats["triggered"]


def test_first_buy_surge_rejects_single_whale_spam():
    # 10 buy tapi semua dari 1 wallet -> bukan akumulasi banyak wallet.
    rows = [("buy", amt, T0 - 800 + i * 60, "whale")
            for i, amt in enumerate([1.5, 1.2, 1.1] + [0.5] * 7)]
    rows += [("sell", 0.3, T0 - 400, "seller0"),
             ("sell", 0.3, T0 - 350, "seller1")]
    stats = first_buy_surge(rows, baseline_hourly_sol=2.0, now_ts=T0)
    assert not stats["triggered"]
    assert not stats["checks"]["buy_ratio"]  # unique wallet < 5


def test_first_buy_surge_rejects_big_sell_reply():
    rows = _valid_surge_rows() + [("sell", 1.5, T0 - 300, "whale-seller")]
    stats = first_buy_surge(rows, baseline_hourly_sol=2.0, now_ts=T0)
    assert not stats["triggered"]
    assert not stats["checks"]["big_buy_cluster"]  # ada sell besar pembalas


def test_first_buy_surge_rejects_old_swaps_outside_window():
    # Surge valid tapi 2 jam lalu -> di luar jendela 15 menit.
    rows = [("buy", amt, T0 - 2 * 3600 + i * 60, f"buyer{i}")
            for i, amt in enumerate([1.5, 1.2, 1.1] + [0.5] * 7)]
    stats = first_buy_surge(rows, baseline_hourly_sol=2.0, now_ts=T0)
    assert not stats["triggered"]
    assert stats["tx"] == 0


def test_first_buy_surge_unknown_baseline_uses_floor():
    stats = first_buy_surge(_valid_surge_rows(), baseline_hourly_sol=None,
                            now_ts=T0)
    assert stats["triggered"], stats["reasons"]
    assert stats["surge_pct"] is None


if __name__ == "__main__":
    test_daily_accounting_and_dry_status()
    test_first_buy_surge_triggers_on_valid_markup_start()
    test_first_buy_surge_rejects_small_volume_surge()
    test_first_buy_surge_rejects_low_buy_ratio()
    test_first_buy_surge_rejects_flat_cvd_velocity()
    test_first_buy_surge_rejects_single_whale_spam()
    test_first_buy_surge_rejects_big_sell_reply()
    test_first_buy_surge_rejects_old_swaps_outside_window()
    test_first_buy_surge_unknown_baseline_uses_floor()
    print("ok")
