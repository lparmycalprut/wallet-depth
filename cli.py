# -*- coding: utf-8 -*-
"""
CLI version — Wallet Depth by Threshold (tanpa dashboard).

Pakai:
    python cli.py <CA> --helius-key <API_KEY>

Contoh:
    python cli.py AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump --helius-key xxxx
"""
import argparse
import json
import os
import sys

import requests

from core import get_helius_keys, get_holders, get_supply

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

DUST_LIMIT = 5.0
REAL_RATIO_OK = 0.30
TIERS = [(">$5", 5.0), (">$100", 100.0), (">$1K", 1e3),
         (">$10K", 1e4), (">$100K", 1e5), (">$1M", 1e6)]

RED = "\033[91m"
GREEN = "\033[92m"
BOLD = "\033[1m"
END = "\033[0m"


def dexscreener(ca):
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}", timeout=20)
    pairs = (r.json() or {}).get("pairs") or []
    if not pairs:
        return None
    pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
    b = pairs[0]
    return {
        "name": b["baseToken"].get("name"), "symbol": b["baseToken"].get("symbol"),
        "price": float(b.get("priceUsd") or 0),
        "mc": float(b.get("marketCap") or b.get("fdv") or 0),
        "lp": {p.get("pairAddress") for p in pairs},
    }


def holders_helius(keys, ca):
    holders = get_holders(keys, ca)
    owners = dict(zip(holders["owner"], holders["raw_amount"]))
    print(f"  ...{len(owners):,} owners")
    return owners


def decimals_of(keys, ca):
    supply, decimals = get_supply(keys, ca)
    return decimals, supply


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("ca", nargs="?", default="")
    ap.add_argument("--helius-key", default=cfg.get("helius_api_key") or "",
                    help="Optional if already set in config.json")
    ap.add_argument("--dust", type=float,
                    default=float(cfg.get("dust_limit_usd", DUST_LIMIT)))
    args = ap.parse_args()

    helius_keys = tuple(get_helius_keys(primary=args.helius_key, config=cfg))
    if not helius_keys:
        sys.exit("Missing Helius API key(s). Set config.json / environment "
                 "or pass --helius-key.")

    ca = args.ca or input("Enter Solana token CA: ").strip()
    if not ca:
        sys.exit("Empty CA.")

    print(f"\n{BOLD}Fetching DexScreener...{END}")
    m = dexscreener(ca)
    if not m:
        sys.exit("Token not found on DexScreener.")
    print(f"  {m['name']} (${m['symbol']}) | price ${m['price']:.10f} | MC ${m['mc']:,.0f}")

    dec, supply = decimals_of(helius_keys, ca)
    print(f"{BOLD}Fetching all holders via Helius...{END}")
    owners = holders_helius(helius_keys, ca)

    vals = []
    for o, raw in owners.items():
        if o in m["lp"]:
            continue
        ui = raw / 10 ** dec
        if ui > 0:
            vals.append(ui * m["price"])

    total = len(vals)
    dust = [v for v in vals if v < args.dust]
    real = [v for v in vals if v >= args.dust]
    ratio = len(real) / len(dust) if dust else float("inf")
    dust_pct = sum(dust) / m["mc"] * 100 if m["mc"] else 0
    real_pct = sum(real) / m["mc"] * 100 if m["mc"] else 0

    print(f"\n{BOLD}=== DUST vs REAL ==={END}")
    print(f"  Total holders: {total:,}")
    print(f"  Dust (<${args.dust:g})  : {len(dust):,}  -> {dust_pct:.2f}% of MC")
    print(f"  Real (>=${args.dust:g}) : {len(real):,}  -> {real_pct:.2f}% of MC")
    print(f"  Real/dust ratio: {ratio*100:,.1f}% (threshold {REAL_RATIO_OK*100:.0f}%)")
    if not dust or ratio > REAL_RATIO_OK:
        print(f"\n{GREEN}{BOLD}✅ HOLDERS OK — real holders are dominant, "
              f"controlling {real_pct:.2f}% of marketcap.{END}")
    else:
        print(f"\n{RED}{BOLD}🚨 WARNING — most holders are dust wallets! "
              f"Real holders are only {ratio*100:.1f}% of dust holders "
              f"and control just {real_pct:.2f}% of marketcap.{END}")

    print(f"\n{BOLD}=== WALLET DEPTH BY THRESHOLD ==={END}")
    print(f"  {'Tier':8} {'Wallet':>10} {'%Holders':>9} {'USD Value':>16} {'%MC':>8}")
    for label, thr in [(">$0", 0.0)] + TIERS:
        sub = [v for v in vals if v > thr]
        usd = sum(sub)
        print(f"  {label:8} {len(sub):>10,} {len(sub)/total*100 if total else 0:>8.2f}% "
              f"{usd:>15,.0f}$ {usd/m['mc']*100 if m['mc'] else 0:>7.2f}%")


if __name__ == "__main__":
    main()
