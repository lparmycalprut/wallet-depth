#!/usr/bin/env python3
"""Backtest: seberapa sering confidence 🟢 KUAT (strong) benar-benar muncul?

Menjalankan ``detect_daily`` atas ``daily_effort.json`` (satu-satunya dataset
historis yang tersimpan di repo) lalu melaporkan:

1. distribusi signal x confidence,
2. gate mana yang menggagalkan tiap baris (diagnostik),
3. simulasi "what-if" wash: karena baris harian lama tidak menyimpan
   ``wash_pct``/``cvd_delta_clean``, kita ukur berapa baris yang *akan* lolos
   ambang strong (|CVD| >= 5 SOL) seandainya wash-collapse terpenuhi.

Pakai: python3 scripts/backtest_confidence.py [--json]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from reversal_engine import (  # noqa: E402
    NEUTRAL, REVERSAL_DOWN, REVERSAL_UP, ReversalConfig, detect_daily,
)

DAILY_PATH = os.path.join(ROOT, "daily_effort.json")
STRONG_CVD = 5.0
STRONG_WASH = 3.0


def load_daily(path: str = DAILY_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        rows = json.load(handle)
    return rows if isinstance(rows, list) else []


def group_by_mint(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        grouped[str(row.get("mint") or "")].append(row)
    for series in grouped.values():
        series.sort(key=lambda row: str(row.get("date") or ""))
    return grouped


def _blocking_gate(row: dict, cfg: ReversalConfig) -> str:
    """Gate pertama yang membuat baris ini tidak bisa jadi strong."""
    if row.get("wash_pct") is None:
        return "tanpa field wash_pct (data harian lama)"
    if row.get("cvd_delta_clean") is None:
        return "tanpa field cvd_delta_clean (data harian lama)"
    if int(row.get("tx_count") or 0) < cfg.min_tx:
        return f"tx_count < {cfg.min_tx}"
    if float(row.get("wash_pct") or 0) > STRONG_WASH:
        return f"wash > {STRONG_WASH:.0f}%"
    if abs(float(row.get("cvd_delta_clean") or 0)) < STRONG_CVD:
        return f"|CVD bersih| < {STRONG_CVD:.0f} SOL"
    return "-"


def run(rows: list[dict], cfg: ReversalConfig | None = None) -> dict:
    cfg = cfg or ReversalConfig()
    counts: collections.Counter = collections.Counter()
    gates: collections.Counter = collections.Counter()
    strong: list[dict] = []
    evaluated = 0
    for mint, series in group_by_mint(rows).items():
        for idx, row in enumerate(series):
            result = detect_daily(series, idx, cfg)
            evaluated += 1
            counts[(result["signal"], result["confidence"])] += 1
            gates[_blocking_gate(row, cfg)] += 1
            if result["confidence"] == "strong":
                strong.append({"mint": mint, "date": row.get("date"),
                               "signal": result["signal"]})
    # What-if: berapa baris yang punya magnitudo CVD cukup untuk strong,
    # seandainya syarat wash-collapse terpenuhi.
    cvd_ok = sum(1 for row in rows
                 if abs(float(row.get("cvd_delta") or 0)) >= STRONG_CVD)
    reversal = sum(count for (signal, _), count in counts.items()
                   if signal in (REVERSAL_UP, REVERSAL_DOWN))
    return {
        "rows": len(rows), "mints": len(group_by_mint(rows)),
        "evaluated": evaluated, "reversal_signals": reversal,
        "strong_count": len(strong), "strong": strong,
        "by_signal_confidence": {f"{sig}/{conf}": count
                                 for (sig, conf), count in sorted(counts.items())},
        "blocking_gates": dict(gates.most_common()),
        "rows_with_wash_field": sum(1 for row in rows if row.get("wash_pct") is not None),
        "rows_cvd_magnitude_ok": cvd_ok,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=DAILY_PATH)
    parser.add_argument("--json", action="store_true", help="cetak JSON mentah")
    args = parser.parse_args(argv)

    rows = load_daily(args.path)
    report = run(rows)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Dataset      : {os.path.basename(args.path)}")
    print(f"Baris/mint   : {report['rows']} baris · {report['mints']} token")
    print(f"Dievaluasi   : {report['evaluated']} window")
    print(f"Sinyal REVERSAL : {report['reversal_signals']}")
    print(f"Confidence STRONG (🟢 KUAT) : {report['strong_count']}")
    for hit in report["strong"]:
        print(f"  - {hit['date']} {hit['signal']} {hit['mint']}")
    print("\nDistribusi signal/confidence:")
    for key, count in report["by_signal_confidence"].items():
        print(f"  {key:<28} {count}")
    print("\nGate yang menghalangi strong:")
    for key, count in report["blocking_gates"].items():
        print(f"  {key:<44} {count}")
    print(f"\nBaris punya field wash_pct : {report['rows_with_wash_field']}/{report['rows']}")
    print(f"Baris |CVD| >= {STRONG_CVD:.0f} SOL   : {report['rows_cvd_magnitude_ok']}/{report['rows']}"
          " (kandidat strong bila wash-collapse tercatat)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
