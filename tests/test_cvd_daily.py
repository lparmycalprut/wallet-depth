"""Offline checks for the GMGN extension-compatible daily CVD model."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cvd_daily import calculate_daily_cvd, latest_dry_signal, priority_spike


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


def test_priority_threshold_is_strict():
    rows = [("buy", 1, 1, "x")] * 500
    assert not priority_spike(rows, min_tx=500, min_volume_sol=500)["triggered"]
    rows.append(("buy", 2, 1, "y"))
    assert priority_spike(rows, min_tx=500, min_volume_sol=500)["triggered"]


if __name__ == "__main__":
    test_daily_accounting_and_dry_status()
    test_priority_threshold_is_strict()
    print("ok")
