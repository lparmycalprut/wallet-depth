# -*- coding: utf-8 -*-
"""🔍 Accumulation Detector — 5-Phase Pre-Pump Pattern Analyzer

Analyzes a Solana token contract address against the 5-phase accumulation
pattern that historically precedes a 100x-1000x pump in memecoins:
  Phase 1: Liquidity Test (weight 15)
  Phase 2: Slow Accumulation (weight 20)
  Phase 3: Whale Entry (weight 20)
  Phase 4: Volume Spike (weight 25)
  Phase 5: Thin Liquidity Indicator (weight 20)

Data sources: DexScreener (market/price), GeckoTerminal (OHLC candles),
GMGN Trades API (swap-level wallet data), Helius (tx history).
"""

import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Accumulation Detector",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ─────────────────────────────────────────────────────────────────
st.markdown("""<style>
.block-container {padding-top:1.2rem;max-width:1400px;}
h1 {font-size:1.3rem!important;margin-bottom:0!important;}
[data-testid="stMetric"] {padding:0.3rem 0.6rem;background:rgba(128,128,128,0.07);border-radius:8px;}
.phase-card {border-radius:12px;padding:16px 20px;margin-bottom:12px;border:2px solid;}
.phase-card-pass {background:rgba(34,197,94,0.08);border-color:#22c55e;}
.phase-card-partial {background:rgba(250,204,21,0.08);border-color:#facc15;}
.phase-card-miss {background:rgba(239,68,68,0.06);border-color:#ef4444;}
</style>""", unsafe_allow_html=True)


# ── Helper imports ──────────────────────────────────────────────────────
try:
    from core import get_helius_keys, get_market
except Exception as e:
    st.error(f"Import core failed: {e}")
    st.stop()

try:
    from cvd import (
        fetch_candles,
        fetch_swaps,
        get_sol_price,
        classify_swap,
        WHALE_SOL,
        MIN_SOL,
    )
except Exception as e:
    st.error(f"Import cvd failed: {e}")
    st.stop()


# ── Page header ─────────────────────────────────────────────────────────
st.title("🔍 Accumulation Detector")
st.caption(
    "5-Phase Pre-Pump Pattern Analyzer — detects the accumulation pattern "
    "that historically precedes a 100x-1000x pump in Solana memecoins."
)

st.markdown("""
**Detection Logic — 5 Phases (max 100 pts):**
| Phase | Weight | What it detects |
|-------|--------|-----------------|
| 1. Liquidity Test | 15 pts | First 2-6 small test transactions (buy+sell within minutes) |
| 2. Slow Accumulation | 20 pts | Transaction/volume/trader growth over 2-4 hours |
| 3. Whale Entry | 20 pts | Large wallet entry (>$1K) 1-3h before volume spike |
| 4. Volume Spike | 25 pts | Transaction count & volume explosion + shakeout pattern |
| 5. Thin Liquidity | 20 pts | Low liquidity + low FDV = easy to manipulate = higher pump potential |
""")


# ── Session state ───────────────────────────────────────────────────────
if "accum_result" not in st.session_state:
    st.session_state["accum_result"] = None
if "accum_ca" not in st.session_state:
    st.session_state["accum_ca"] = ""


# ── Input ───────────────────────────────────────────────────────────────
ca = st.text_input(
    "Solana Token Contract Address (CA) or DexScreener URL",
    value=st.session_state.get("accum_ca", ""),
    placeholder="e.g. AkchGAUdXXRGHt3HXaHbTvw3JLGUwtJRmYnkG66wpump",
).strip()

# Parse DexScreener URL → CA
if ca.startswith("http"):
    parts = ca.rstrip("/").split("/")
    ca = parts[-1] if parts else ca

st.session_state["accum_ca"] = ca

analyze = st.button(
    "🔍 Run Accumulation Analysis",
    type="primary",
    use_container_width=True,
)


# ── Analysis function ───────────────────────────────────────────────────
def run_accumulation_analysis(ca: str, helius_keys: tuple) -> dict:
    """Run the full 5-phase accumulation analysis for a token."""

    result = {
        "contract_address": ca,
        "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_score": 0,
        "risk_level": "NEGLIGIBLE",
        "phase_scores": {},
        "raw_data": {},
        "pattern_detected": "NONE",
        "confidence": "LOW",
        "recommendation": "AVOID",
        "notes": "",
    }

    # ── 1. Fetch market data from DexScreener ───────────────────────────
    with st.spinner("Fetching market data from DexScreener..."):
        market = get_market(ca)
    if not market:
        return {"error": "Token not found on DexScreener. Check the CA."}

    price = market["price_usd"]
    marketcap = market["marketcap"]
    liquidity = market["liquidity_usd"]
    symbol = market.get("symbol", "?")
    name = market.get("name", "?")
    pair_created_at = market.get("pair_created_at")
    pair_addresses = market.get("pair_addresses") or []

    # Buy/sell counts from DexScreener
    txns_24h = (market.get("txns") or {}).get("h24") or {}
    txns_1h = (market.get("txns") or {}).get("h1") or {}
    txns_6h = (market.get("txns") or {}).get("h6") or {}
    buys_24 = int(txns_24h.get("buys") or 0)
    sells_24 = int(txns_24h.get("sells") or 0)
    vol_24 = float((market.get("volume") or {}).get("h24") or 0)
    vol_6h = float((market.get("volume") or {}).get("h6") or 0)
    vol_1h = float((market.get("volume") or {}).get("h1") or 0)
    bs_ratio = buys_24 / sells_24 if sells_24 else float("inf")

    # Price changes
    pc = market.get("price_change") or {}
    chg_5m = float(pc.get("m5") or 0)
    chg_1h = float(pc.get("h1") or 0)
    chg_6h = float(pc.get("h6") or 0)
    chg_24h = float(pc.get("h24") or 0)

    # Token age
    age_hours = None
    if pair_created_at:
        age_seconds = (time.time() * 1000 - pair_created_at) / 1000
        age_hours = age_seconds / 3600

    result["raw_data"] = {
        "symbol": symbol,
        "name": name,
        "price": price,
        "marketcap": marketcap,
        "liquidity": liquidity,
        "total_transactions_24h": buys_24 + sells_24,
        "buys_24h": buys_24,
        "sells_24h": sells_24,
        "buy_sell_ratio": round(bs_ratio, 2) if bs_ratio != float("inf") else "inf",
        "volume_24h": vol_24,
        "volume_6h": vol_6h,
        "volume_1h": vol_1h,
        "price_change_5m": chg_5m,
        "price_change_1h": chg_1h,
        "price_change_6h": chg_6h,
        "price_change_24h": chg_24h,
        "age_hours": round(age_hours, 1) if age_hours else None,
        "unique_traders": None,  # will be filled from GMGN data
        "top_wallet_entries": [],
    }

    # ── 2. Fetch hourly candles from GeckoTerminal (up to 168h = 7 days) ──
    candles_h1 = []
    pair_addr = pair_addresses[0] if pair_addresses else None
    if pair_addr:
        with st.spinner("Fetching hourly candles (GeckoTerminal)..."):
            try:
                candles_h1 = fetch_candles(
                    pair_addr, timeframe="hour", aggregate=1,
                    limit=168, timeout=15,
                )
            except Exception:
                candles_h1 = []

    # ── 3. Fetch swap data from GMGN (last 48h, wallet-level) ───────────
    sol_price = get_sol_price()
    all_swaps = []
    top_wallets_data = []

    with st.spinner("Fetching swap data from GMGN (wallet-level, up to 48h)..."):
        cutoff = int(time.time()) - 48 * 3600
        try:
            all_swaps, _sig, _ts, _hit = fetch_swaps(
                "", pair_addr or "", ca,
                stop_ts=cutoff, max_pages=80,
                sleep=0.05, use_gmgn=True,
            )
        except Exception:
            all_swaps = []

    if all_swaps:
        # Deduplicate
        seen = {}
        for s in all_swaps:
            if len(s) >= 4:
                key = (s[0], float(s[1]), int(s[2]), str(s[3]))
                seen[key] = s
        all_swaps = sorted(seen.values(), key=lambda x: x[2])

        # Build DataFrame for analysis
        sdf = pd.DataFrame(all_swaps, columns=["side", "sol", "ts", "wallet"])
        sdf["dt"] = pd.to_datetime(sdf["ts"], unit="s")
        sdf["usd"] = sdf["sol"] * sol_price

        # Unique traders
        unique_traders = int(sdf["wallet"].nunique())
        result["raw_data"]["unique_traders"] = unique_traders

        # ── Top wallets by volume ───────────────────────────────────────
        wallet_stats = sdf.groupby("wallet").agg(
            total_vol=("sol", "sum"),
            n_swaps=("sol", "count"),
            first_ts=("ts", "min"),
            last_ts=("ts", "max"),
            max_single=("sol", "max"),
        ).reset_index()
        wallet_stats = wallet_stats.sort_values("total_vol", ascending=False)

        top_wallets_data = []
        for _, row in wallet_stats.head(10).iterrows():
            top_wallets_data.append({
                "wallet": row["wallet"],
                "amount_usd": round(float(row["total_vol"]) * sol_price, 2),
                "amount_sol": round(float(row["total_vol"]), 2),
                "n_swaps": int(row["n_swaps"]),
                "first_seen": datetime.fromtimestamp(
                    int(row["first_ts"]), tz=timezone.utc
                ).isoformat(),
                "max_single_swap_sol": round(float(row["max_single"]), 2),
            })

        result["raw_data"]["top_wallet_entries"] = top_wallets_data

        # ── Build hourly time series for phase analysis ─────────────────
        sdf["hour"] = sdf["dt"].dt.floor("h")
        hourly = sdf.groupby("hour").agg(
            tx_count=("sol", "size"),
            volume_sol=("sol", "sum"),
            volume_usd=("usd", "sum"),
            unique_wallets=("wallet", "nunique"),
            buys=("side", lambda x: (x == "buy").sum()),
            sells=("side", lambda x: (x == "sell").sum()),
        ).reset_index()
        hourly["bs_ratio"] = hourly.apply(
            lambda r: r["buys"] / r["sells"] if r["sells"] > 0 else float("inf"),
            axis=1,
        )
        hourly = hourly.sort_values("hour").reset_index(drop=True)

    else:
        hourly = pd.DataFrame()
        sdf = pd.DataFrame()

    # ── Build candle-based hourly series if we have candles ─────────────
    candle_df = pd.DataFrame()
    if candles_h1:
        candle_df = pd.DataFrame(candles_h1)
        if not candle_df.empty:
            for col in ["o", "h", "l", "c", "v"]:
                if col in candle_df.columns:
                    candle_df[col] = pd.to_numeric(candle_df[col], errors="coerce")

    # ══════════════════════════════════════════════════════════════════════
    # PHASE SCORING
    # ══════════════════════════════════════════════════════════════════════
    notes = []

    # ── Phase 1: Liquidity Test (15 pts) ────────────────────────────────
    p1_score = 0
    p1_detail = ""

    if not hourly.empty and len(hourly) >= 1:
        first_hours = hourly.head(6)
        total_first_vol = first_hours["volume_usd"].sum()
        total_first_tx = first_hours["tx_count"].sum()

        # Check for test-like behavior in first hours
        small_tx_count = total_first_tx
        small_vol = total_first_vol

        if 2 <= small_tx_count <= 6 and small_vol < 1000:
            p1_score = 15
            p1_detail = (
                f"Exactly {int(small_tx_count)} test transactions in first hours "
                f"with ${small_vol:,.0f} total volume — classic liquidity test pattern."
            )
        elif 7 <= small_tx_count <= 15 and small_vol < 2000:
            p1_score = 10
            p1_detail = (
                f"{int(small_tx_count)} small transactions in first hours "
                f"(${small_vol:,.0f} volume) — likely test phase."
            )
        elif small_tx_count > 0 and small_vol < 5000:
            p1_score = 5
            p1_detail = (
                f"Some small early transactions ({int(small_tx_count)} tx, "
                f"${small_vol:,.0f}) but pattern is unclear."
            )
        else:
            p1_detail = (
                f"No clear test transactions: {int(small_tx_count)} tx / "
                f"${small_vol:,.0f} in first hours — too large for test phase."
            )

        # Also check if first candles show buy+sell within minutes
        if not candle_df.empty and len(candle_df) >= 2:
            first_candles = candle_df.tail(6).head(3)  # earliest 3 hours
            body_sizes = abs(first_candles["c"] - first_candles["o"])
            avg_body = body_sizes.mean() if len(body_sizes) else 0
            price_range = candle_df["h"].max() - candle_df["l"].min()
            if price_range > 0 and avg_body / price_range < 0.1:
                p1_score = max(p1_score, 10)
                p1_detail += " Early candles show minimal price movement (test-like)."
                notes.append("Phase 1: early candles show test-like minimal movement")
    else:
        p1_detail = "Insufficient hourly data to detect liquidity test phase."

    result["phase_scores"]["liquidity_test"] = {
        "score": p1_score,
        "max": 15,
        "detail": p1_detail,
    }

    # ── Phase 2: Slow Accumulation (20 pts) ─────────────────────────────
    p2_score = 0
    p2_detail = ""

    if not hourly.empty and len(hourly) >= 4:
        # Look for growing pattern over consecutive hours
        early = hourly.head(max(2, len(hourly) // 3))
        late = hourly.tail(max(2, len(hourly) // 3))

        early_avg_tx = early["tx_count"].mean()
        late_avg_tx = late["tx_count"].mean()
        early_avg_vol = early["volume_usd"].mean()
        late_avg_vol = late["volume_usd"].mean()
        early_avg_wallets = early["unique_wallets"].mean()
        late_avg_wallets = late["unique_wallets"].mean()

        tx_growth = late_avg_tx / early_avg_tx if early_avg_tx > 0 else 1
        vol_growth = late_avg_vol / early_avg_vol if early_avg_vol > 0 else 1
        wallet_growth = late_avg_wallets / early_avg_wallets if early_avg_wallets > 0 else 1

        # Buy/sell ratio trend
        early_bs = early["bs_ratio"].replace(float("inf"), 10).mean()
        late_bs = late["bs_ratio"].replace(float("inf"), 10).mean()

        # Composite growth score
        composite_growth = max(tx_growth, vol_growth, wallet_growth)

        if composite_growth >= 10:
            p2_score = 20
            p2_detail = (
                f"Clear 10x+ accumulation: tx growth {tx_growth:.1f}x, "
                f"vol growth {vol_growth:.1f}x, wallet growth {wallet_growth:.1f}x. "
                f"Buy/sell ratio: {early_bs:.2f} → {late_bs:.2f}."
            )
        elif composite_growth >= 5:
            p2_score = 15
            p2_detail = (
                f"5x-10x growth detected: tx {tx_growth:.1f}x, "
                f"vol {vol_growth:.1f}x, wallets {wallet_growth:.1f}x. "
                f"B/S ratio: {early_bs:.2f} → {late_bs:.2f}."
            )
        elif composite_growth >= 2:
            p2_score = 10
            p2_detail = (
                f"2x-5x moderate accumulation: tx {tx_growth:.1f}x, "
                f"vol {vol_growth:.1f}x, wallets {wallet_growth:.1f}x."
            )
        elif composite_growth >= 1.3:
            p2_score = 5
            p2_detail = (
                f"Minimal growth: tx {tx_growth:.1f}x, vol {vol_growth:.1f}x, "
                f"wallets {wallet_growth:.1f}x."
            )
        else:
            p2_detail = (
                f"No accumulation phase detected. Growth: tx {tx_growth:.1f}x, "
                f"vol {vol_growth:.1f}x, wallets {wallet_growth:.1f}x."
            )

        # Extra: check if buy:sell ratio is positive (>1.0) or negative with decreasing sell
        if late_bs >= 1.2:
            p2_detail += " Buy pressure dominant (B/S ≥ 1.2)."
            notes.append("Phase 2: buy pressure dominant in accumulation window")
        elif early_bs > late_bs and late_bs < 0.8:
            p2_detail += " Sell pressure decreasing — absorption pattern."
            notes.append("Phase 2: decreasing sell pressure (absorption)")
    else:
        p2_detail = "Insufficient hourly data for accumulation detection."

    result["phase_scores"]["slow_accumulation"] = {
        "score": p2_score,
        "max": 20,
        "detail": p2_detail,
    }

    # ── Phase 3: Whale Entry (20 pts) ───────────────────────────────────
    p3_score = 0
    p3_detail = ""

    whale_txns = []
    if not sdf.empty and "wallet" in sdf.columns:
        # Find large single transactions (whale entries)
        whale_threshold_sol = 1000 / sol_price if sol_price > 0 else 7  # ~$1000
        big5k_threshold_sol = 5000 / sol_price if sol_price > 0 else 35  # ~$5000

        # Find wallets that had their first big buy
        whale_sdf = sdf[sdf["sol"] >= whale_threshold_sol].copy()
        whale_sdf = whale_sdf.sort_values("ts")

        # Group by wallet to find first entry
        if not whale_sdf.empty:
            first_whale = whale_sdf.groupby("wallet").agg(
                first_sol=("sol", "first"),
                first_ts=("ts", "first"),
                total_sol=("sol", "sum"),
            ).reset_index()
            first_whale = first_whale.sort_values("first_sol", ascending=False)

            for _, row in first_whale.head(5).iterrows():
                whale_txns.append({
                    "wallet": row["wallet"],
                    "amount_usd": round(float(row["first_sol"]) * sol_price, 2),
                    "amount_sol": round(float(row["first_sol"]), 2),
                    "timestamp": datetime.fromtimestamp(
                        int(row["first_ts"]), tz=timezone.utc
                    ).isoformat(),
                    "ts_epoch": int(row["first_ts"]),
                })

            # Check whale timing vs volume spike
            if whale_txns:
                # Find the hour with highest volume
                if not hourly.empty:
                    peak_hour_idx = hourly["volume_usd"].idxmax()
                    peak_hour_ts = hourly.loc[peak_hour_idx, "hour"]
                    peak_hour_epoch = peak_hour_ts.timestamp()

                    # Check if any whale entered 1-3 hours BEFORE the spike
                    for wt in whale_txns:
                        hours_before = (peak_hour_epoch - wt["ts_epoch"]) / 3600
                        wt["hours_before_spike"] = round(hours_before, 1)

                    best_whale = min(
                        whale_txns,
                        key=lambda w: abs(w.get("hours_before_spike", 999) - 2),
                    )
                    hbs = best_whale.get("hours_before_spike", 0)

                    if best_whale["amount_usd"] >= 5000 and 0 < hbs <= 4:
                        p3_score = 20
                        p3_detail = (
                            f"Whale entry ${best_whale['amount_usd']:,.0f} detected "
                            f"{hbs:.1f}h before volume spike — perfect timing pattern."
                        )
                    elif best_whale["amount_usd"] >= 1000 and 0 < hbs <= 4:
                        p3_score = 15
                        p3_detail = (
                            f"Whale entry ${best_whale['amount_usd']:,.0f} detected "
                            f"{hbs:.1f}h before volume spike."
                        )
                    elif best_whale["amount_usd"] < 1000:
                        p3_score = 10
                        p3_detail = (
                            f"Possible whale entry ${best_whale['amount_usd']:,.0f} "
                            f"but below $1K threshold, or timing unclear ({hbs:.1f}h "
                            f"before peak)."
                        )
                    elif hbs > 4 or hbs < 0:
                        p3_score = 5
                        p3_detail = (
                            f"Whale entry ${best_whale['amount_usd']:,.0f} found but "
                            f"timing unclear ({hbs:.1f}h relative to peak)."
                        )
                    else:
                        p3_score = 5
                        p3_detail = f"Possible whale pattern but unclear."
                else:
                    best = whale_txns[0]
                    if best["amount_usd"] >= 5000:
                        p3_score = 10
                    elif best["amount_usd"] >= 1000:
                        p3_score = 5
                    p3_detail = (
                        f"Whale entry ${best['amount_usd']:,.0f} found but no "
                        f"hourly data to confirm timing relative to volume spike."
                    )
            else:
                p3_detail = "No whale entry (>$1K single transaction) detected."
        else:
            p3_detail = "No whale entry (>$1K single transaction) detected."
    else:
        p3_detail = "No swap data available for whale detection."

    # Check if whale wallets are new (minimal prior activity)
    if whale_txns and not sdf.empty:
        for wt in whale_txns[:3]:
            wallet_txs = sdf[sdf["wallet"] == wt["wallet"]]
            n_prior = len(wallet_txs)
            if n_prior <= 2:
                p3_detail += f" Wallet {wt['wallet'][:8]}… is new/minimal activity ({n_prior} txs)."
                notes.append(f"Phase 3: whale wallet {wt['wallet'][:8]}… appears new")

    result["phase_scores"]["whale_entry"] = {
        "score": p3_score,
        "max": 20,
        "detail": p3_detail,
    }

    # ── Phase 4: Volume Spike (25 pts) ──────────────────────────────────
    p4_score = 0
    p4_detail = ""

    if not hourly.empty and len(hourly) >= 3:
        # Find the peak 2-hour window
        hourly_sorted = hourly.sort_values("volume_usd", ascending=False)
        peak_tx = int(hourly_sorted.iloc[0]["tx_count"])
        peak_vol = float(hourly_sorted.iloc[0]["volume_usd"])
        peak_wallets = int(hourly_sorted.iloc[0]["unique_wallets"])

        # Baseline = median of non-peak hours
        baseline_tx = hourly["tx_count"].median()
        baseline_vol = hourly["volume_usd"].median()
        baseline_wallets = hourly["unique_wallets"].median()

        # Check for shakeout pattern (B/S ratio reversal)
        bs_values = hourly["bs_ratio"].replace(float("inf"), 10)
        bs_reversal = False
        if len(bs_values) >= 4:
            early_bs = bs_values.head(len(bs_values) // 2).mean()
            late_bs = bs_values.tail(len(bs_values) // 2).mean()
            if (early_bs > 1.2 and late_bs < 0.8) or (early_bs < 0.8 and late_bs > 1.2):
                bs_reversal = True

        if peak_tx >= 300 and peak_vol >= 50000 and peak_wallets >= 200:
            p4_score = 25
            p4_detail = (
                f"Massive spike: {peak_tx} tx, ${peak_vol:,.0f} volume, "
                f"{peak_wallets} unique wallets in peak hour."
            )
        elif peak_tx >= 100 and peak_vol >= 20000:
            p4_score = 20
            p4_detail = (
                f"Strong spike: {peak_tx} tx, ${peak_vol:,.0f} volume, "
                f"{peak_wallets} wallets in peak hour."
            )
        elif peak_tx >= 50 and peak_vol >= 10000:
            p4_score = 15
            p4_detail = (
                f"Moderate spike: {peak_tx} tx, ${peak_vol:,.0f} volume, "
                f"{peak_wallets} wallets."
            )
        elif peak_tx >= 20 or peak_vol >= 5000:
            p4_score = 10
            p4_detail = (
                f"Moderate activity: {peak_tx} tx, ${peak_vol:,.0f} volume "
                f"in peak hour."
            )
        elif peak_tx >= 5 or peak_vol >= 1000:
            p4_score = 5
            p4_detail = (
                f"Minor spike: {peak_tx} tx, ${peak_vol:,.0f} volume."
            )
        else:
            p4_detail = (
                f"No significant spike detected. Peak: {peak_tx} tx, "
                f"${peak_vol:,.0f} volume."
            )

        # Compare to baseline
        if baseline_tx > 0:
            spike_ratio = peak_tx / baseline_tx
            p4_detail += f" ({spike_ratio:.1f}x over median {int(baseline_tx)} tx/h)."
        if baseline_vol > 0:
            vol_spike = peak_vol / baseline_vol
            p4_detail += f" Volume {vol_spike:.1f}x over median."

        if bs_reversal:
            p4_detail += " Shakeout pattern detected (B/S ratio reversal)."
            notes.append("Phase 4: shakeout pattern (buy/sell ratio reversal)")
    else:
        # Fallback to DexScreener 24h data
        if vol_24 >= 50000:
            p4_score = 15
            p4_detail = f"24h volume ${vol_24:,.0f} — significant but hourly data unavailable."
        elif vol_24 >= 10000:
            p4_score = 10
            p4_detail = f"24h volume ${vol_24:,.0f} — moderate activity."
        elif vol_24 >= 1000:
            p4_score = 5
            p4_detail = f"24h volume ${vol_24:,.0f} — low activity."
        else:
            p4_detail = f"No hourly data. 24h volume only ${vol_24:,.0f}."

    result["phase_scores"]["volume_spike"] = {
        "score": p4_score,
        "max": 25,
        "detail": p4_detail,
    }

    # ── Phase 5: Thin Liquidity Indicator (20 pts) ──────────────────────
    p5_score = 0
    p5_detail = ""

    fdv = marketcap  # FDV ≈ marketcap for memecoins

    if liquidity < 50000 and fdv < 500000:
        p5_score = 20
        p5_detail = (
            f"Liquidity ${liquidity:,.0f} (<$50K) + FDV ${fdv:,.0f} (<$500K) — "
            f"very thin, easy to manipulate, high pump potential."
        )
    elif liquidity < 100000 and fdv < 1000000:
        p5_score = 15
        p5_detail = (
            f"Liquidity ${liquidity:,.0f} (<$100K) + FDV ${fdv:,.0f} (<$1M) — "
            f"thin liquidity, good pump potential."
        )
    elif liquidity < 300000 and fdv < 2000000:
        p5_score = 10
        p5_detail = (
            f"Liquidity ${liquidity:,.0f} (<$300K) + FDV ${fdv:,.0f} (<$2M) — "
            f"moderate liquidity."
        )
    elif liquidity < 500000:
        p5_score = 5
        p5_detail = (
            f"Liquidity ${liquidity:,.0f} (<$500K) — somewhat liquid."
        )
    else:
        p5_detail = (
            f"Liquidity ${liquidity:,.0f} (>$500K) — too liquid for easy "
            f"manipulation. Lower pump potential."
        )

    result["phase_scores"]["thin_liquidity"] = {
        "score": p5_score,
        "max": 20,
        "detail": p5_detail,
    }

    # ══════════════════════════════════════════════════════════════════════
    # OVERALL SCORE & RECOMMENDATION
    # ══════════════════════════════════════════════════════════════════════
    overall = p1_score + p2_score + p3_score + p4_score + p5_score
    result["overall_score"] = overall

    # Risk level
    if overall >= 75:
        result["risk_level"] = "HIGH"
    elif overall >= 50:
        result["risk_level"] = "MEDIUM"
    elif overall >= 25:
        result["risk_level"] = "LOW"
    else:
        result["risk_level"] = "NEGLIGIBLE"

    # Pattern detection
    phases_hit = sum(
        1 for k, v in result["phase_scores"].items()
        if v["score"] >= v["max"] * 0.5
    )
    if phases_hit >= 4:
        result["pattern_detected"] = "FULL"
    elif phases_hit >= 2:
        result["pattern_detected"] = "PARTIAL"
    else:
        result["pattern_detected"] = "NONE"

    # Confidence
    data_quality = 0
    if not hourly.empty:
        data_quality += 1
    if not sdf.empty:
        data_quality += 1
    if candles_h1:
        data_quality += 1

    if overall >= 60 and data_quality >= 3:
        result["confidence"] = "HIGH"
    elif overall >= 40 and data_quality >= 2:
        result["confidence"] = "MEDIUM"
    else:
        result["confidence"] = "LOW"

    # Recommendation
    if overall >= 75 and result["pattern_detected"] == "FULL":
        result["recommendation"] = "BUY WATCH"
    elif overall >= 50 and phases_hit >= 3:
        result["recommendation"] = "ACCUMULATING"
    elif overall >= 60 and result["pattern_detected"] == "PARTIAL":
        result["recommendation"] = "ACCUMULATING"
    elif liquidity > 500000 or fdv > 5000000:
        result["recommendation"] = "TOO LATE"
    elif overall < 25:
        result["recommendation"] = "AVOID"
    else:
        result["recommendation"] = "AVOID"

    # Notes
    if notes:
        result["notes"] = " | ".join(notes)

    # Additional observations
    if age_hours and age_hours < 24:
        result["notes"] += f" ⚠️ Very new token ({age_hours:.0f}h old)."
    if age_hours and age_hours > 168:
        result["notes"] += f" Token is {age_hours/24:.0f} days old."

    return result


# ── Run analysis ────────────────────────────────────────────────────────
if analyze and ca:
    helius_keys = tuple(get_helius_keys())
    with st.spinner("Running 5-phase accumulation analysis..."):
        result = run_accumulation_analysis(ca, helius_keys)
        st.session_state["accum_result"] = result

    if result.get("error"):
        st.error(result["error"])
        st.stop()

# ── Display results ─────────────────────────────────────────────────────
result = st.session_state.get("accum_result")
if not result:
    st.info("Enter a Solana token Contract Address and click **Run Accumulation Analysis**.")
    st.stop()

if result.get("error"):
    st.error(result["error"])
    st.stop()

# ── Header card ─────────────────────────────────────────────────────────
raw = result.get("raw_data", {})
symbol = raw.get("symbol", "?")
name = raw.get("name", "?")

# Overall score color
overall = result["overall_score"]
if overall >= 75:
    score_color = "#22c55e"
    score_bg = "#14532d"
    score_border = "#22c55e"
elif overall >= 50:
    score_color = "#facc15"
    score_bg = "#3f3411"
    score_border = "#facc15"
elif overall >= 25:
    score_color = "#fb923c"
    score_bg = "#431407"
    score_border = "#fb923c"
else:
    score_color = "#ef4444"
    score_bg = "#7f1d1d"
    score_border = "#ef4444"

risk = result["risk_level"]
pattern = result["pattern_detected"]
confidence = result["confidence"]
recommendation = result["recommendation"]

# Recommendation styling
rec_styles = {
    "BUY WATCH": ("#22c55e", "#14532d", "🟢"),
    "ACCUMULATING": ("#facc15", "#3f3411", "🟡"),
    "AVOID": ("#ef4444", "#7f1d1d", "🔴"),
    "TOO LATE": ("#94a3b8", "#1e293b", "⚫"),
}
rec_col, rec_bg, rec_icon = rec_styles.get(recommendation, ("#94a3b8", "#1e293b", "⚫"))

st.markdown(
    f"""<div style="background:{score_bg};border:2px solid {score_border};
    border-radius:14px;padding:20px 24px;margin-bottom:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
    <div>
    <span style="font-size:1.4rem;font-weight:800;color:#e2e8f0;">
    {name} (${symbol})</span>
    <span style="font-size:0.8rem;color:#94a3b8;margin-left:8px;">
    <code>{ca[:12]}…{ca[-4:]}</code></span>
    </div>
    <div style="text-align:center;">
    <div style="font-size:2.4rem;font-weight:900;color:{score_color};line-height:1;">
    {overall}<span style="font-size:1rem;color:#94a3b8;">/100</span></div>
    <div style="font-size:0.75rem;color:#94a3b8;">Accumulation Score</div>
    </div>
    </div>
    <div style="display:flex;gap:12px;margin-top:14px;flex-wrap:wrap;">
    <span style="background:rgba(148,163,184,0.12);border:1px solid #475569;
    border-radius:8px;padding:4px 12px;font-size:0.8rem;color:#cbd5e1;">
    Risk: <b style="color:{score_color};">{risk}</b></span>
    <span style="background:rgba(148,163,184,0.12);border:1px solid #475569;
    border-radius:8px;padding:4px 12px;font-size:0.8rem;color:#cbd5e1;">
    Pattern: <b>{pattern}</b></span>
    <span style="background:rgba(148,163,184,0.12);border:1px solid #475569;
    border-radius:8px;padding:4px 12px;font-size:0.8rem;color:#cbd5e1;">
    Confidence: <b>{confidence}</b></span>
    <span style="background:{rec_bg};border:1px solid {rec_col};
    border-radius:8px;padding:4px 12px;font-size:0.85rem;color:{rec_col};
    font-weight:800;">
    {rec_icon} {recommendation}</span>
    </div>
    </div>""",
    unsafe_allow_html=True,
)

# ── Quick stats row ─────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Price", f"${raw.get('price', 0):,.10f}".rstrip("0").rstrip("."))
c2.metric("Market Cap", f"${raw.get('marketcap', 0):,.0f}")
c3.metric("Liquidity", f"${raw.get('liquidity', 0):,.0f}")
c4.metric("24h Volume", f"${raw.get('volume_24h', 0):,.0f}")
c5.metric(
    "24h Txns",
    f"{raw.get('total_transactions_24h', 0):,}",
    f"B:{raw.get('buys_24h',0)} S:{raw.get('sells_24h',0)}",
)
c6.metric(
    "B/S Ratio",
    f"{raw.get('buy_sell_ratio', 0)}" if isinstance(raw.get('buy_sell_ratio'), str) else f"{raw.get('buy_sell_ratio', 0):.2f}",
    "buy pressure" if isinstance(raw.get("buy_sell_ratio"), (int, float)) and raw.get("buy_sell_ratio", 0) >= 1 else "sell pressure",
)

# ── 5-Phase breakdown cards ────────────────────────────────────────────
st.markdown("### 📊 Phase-by-Phase Breakdown")

phases = [
    ("liquidity_test", "Phase 1: Liquidity Test", "🧪", 15),
    ("slow_accumulation", "Phase 2: Slow Accumulation", "📈", 20),
    ("whale_entry", "Phase 3: Whale Entry", "🐋", 20),
    ("volume_spike", "Phase 4: Volume Spike", "🚀", 25),
    ("thin_liquidity", "Phase 5: Thin Liquidity", "💧", 20),
]

phase_cols = st.columns(5)
for i, (key, title, emoji, max_pts) in enumerate(phases):
    ps = result["phase_scores"].get(key, {})
    score = ps.get("score", 0)
    detail = ps.get("detail", "")

    pct = score / max_pts if max_pts > 0 else 0
    if pct >= 0.6:
        card_class = "phase-card-pass"
        bar_color = "#22c55e"
    elif pct >= 0.3:
        card_class = "phase-card-partial"
        bar_color = "#facc15"
    else:
        card_class = "phase-card-miss"
        bar_color = "#ef4444"

    with phase_cols[i]:
        st.markdown(
            f"""<div class="{card_class}" style="border-color:{bar_color};">
            <div style="font-size:0.78rem;color:#94a3b8;font-weight:700;">
            {emoji} {title}</div>
            <div style="font-size:1.6rem;font-weight:900;color:{bar_color};
            margin:4px 0;">{score}<span style="font-size:0.8rem;color:#64748b;">
            /{max_pts}</span></div>
            <div style="background:rgba(148,163,184,0.15);border-radius:4px;
            height:6px;margin:6px 0;overflow:hidden;">
            <div style="background:{bar_color};height:100%;
            width:{pct*100:.0f}%;border-radius:4px;
            transition:width 0.5s;"></div></div>
            <div style="font-size:0.72rem;color:#94a3b8;line-height:1.4;
            margin-top:4px;">{detail}</div>
            </div>""",
            unsafe_allow_html=True,
        )

# ── Volume & Transaction chart ──────────────────────────────────────────
st.markdown("### 📈 Hourly Activity Timeline")

# Re-fetch data for chart display (quick since it's cached in session)
pair_addresses = (st.session_state.get("accum_result", {})
                  .get("raw_data", {}))

# We need to reconstruct hourly data from the analysis
# Let's fetch it fresh for the chart
helius_keys = tuple(get_helius_keys())
pair_addr = None
try:
    market = get_market(ca)
    pair_addr = (market.get("pair_addresses") or [None])[0]
except Exception:
    pass

if pair_addr:
    try:
        chart_candles = fetch_candles(
            pair_addr, timeframe="hour", aggregate=1,
            limit=168, timeout=15,
        )
        if chart_candles:
            cdf = pd.DataFrame(chart_candles)
            for col in ["o", "h", "l", "c", "v"]:
                if col in cdf.columns:
                    cdf[col] = pd.to_numeric(cdf[col], errors="coerce")
            if "ts" in cdf.columns:
                cdf["dt"] = pd.to_datetime(cdf["ts"].astype(int), unit="s")
            elif "timestamp" in cdf.columns:
                cdf["dt"] = pd.to_datetime(cdf["timestamp"].astype(int), unit="s")

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=cdf["dt"], y=cdf["v"],
                name="Volume",
                marker=dict(color="#38bdf8", opacity=0.5),
                yaxis="y2",
            ))
            fig.add_trace(go.Scatter(
                x=cdf["dt"], y=cdf["c"],
                name="Price",
                line=dict(color="#facc15", width=2),
                yaxis="y1",
            ))
            fig.update_layout(
                height=300,
                margin=dict(t=10, b=0, l=0, r=0),
                legend=dict(orientation="h", font=dict(size=10)),
                yaxis=dict(title="Price", tickfont=dict(size=9),
                           side="left"),
                yaxis2=dict(title="Volume", overlaying="y", side="right",
                            visible=True, tickfont=dict(size=9)),
                xaxis=dict(tickfont=dict(size=9)),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            st.caption("No hourly candle data available for chart.")
    except Exception as e:
        st.caption(f"Chart data unavailable: {e}")

# ── Top Wallets ─────────────────────────────────────────────────────────
top_wallets = result.get("raw_data", {}).get("top_wallet_entries", [])
if top_wallets:
    st.markdown("### 🏆 Top 10 Wallets by Volume")

    tw_df = pd.DataFrame([
        {
            "Wallet": f"https://solscan.io/account/{w['wallet']}",
            "Amount (USD)": f"${w['amount_usd']:,.2f}",
            "Amount (SOL)": f"{w['amount_sol']:.2f}",
            "Swaps": w["n_swaps"],
            "First Seen": w["first_seen"][:16],
            "Max Single (SOL)": f"{w['max_single_swap_sol']:.2f}",
        }
        for w in top_wallets
    ])
    st.dataframe(
        tw_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Wallet": st.column_config.LinkColumn(
                "Wallet",
                display_text=r"account/(.{6}).*",
            )
        },
    )
    st.caption(
        "Top wallets ranked by total volume in the analyzed window. "
        "New wallets (first seen recently) with large entries are flagged "
        "as potential whale accumulation."
    )

# ── Whale entries (from Phase 3) ────────────────────────────────────────
whale_phase = result.get("phase_scores", {}).get("whale_entry", {})
if whale_phase.get("score", 0) > 0:
    st.markdown("### 🐋 Whale Entry Timeline")
    st.caption(whale_phase.get("detail", ""))

# ── Price change summary ────────────────────────────────────────────────
st.markdown("### 📊 Price Movement")
pc1, pc2, pc3, pc4 = st.columns(4)

def _chg_color(v):
    return "#22c55e" if v >= 0 else "#ef4444"

pc1.metric("5m Change", f"{raw.get('price_change_5m', 0):+.2f}%")
pc2.metric("1h Change", f"{raw.get('price_change_1h', 0):+.2f}%")
pc3.metric("6h Change", f"{raw.get('price_change_6h', 0):+.2f}%")
pc4.metric("24h Change", f"{raw.get('price_change_24h', 0):+.2f}%")

# ── Notes ───────────────────────────────────────────────────────────────
notes_text = result.get("notes", "")
if notes_text:
    st.markdown("### 📝 Observations")
    st.info(notes_text)

# ── Recommendation banner ───────────────────────────────────────────────
st.markdown("---")
rec_explanations = {
    "BUY WATCH": (
        "🟢 **BUY WATCH** — Full accumulation pattern detected (4-5 phases hit). "
        "Whale entries + volume spike + thin liquidity = high probability "
        "pre-pump setup. DYOR before entering — check holder distribution "
        "and security on the main analysis page."
    ),
    "ACCUMULATING": (
        "🟡 **ACCUMULATING** — Partial accumulation pattern detected (2-3 phases). "
        "Early-stage accumulation may be underway. Add to watchlist and "
        "monitor for volume spike confirmation."
    ),
    "AVOID": (
        "🔴 **AVOID** — No significant accumulation pattern detected. "
        "Token does not exhibit the 5-phase pre-pump signature. "
        "May be in distribution, dead, or not yet in accumulation phase."
    ),
    "TOO LATE": (
        "⚫ **TOO LATE** — Liquidity too high for classic memecoin pump pattern. "
        "The accumulation phase has likely already completed and the token "
        "is established. Lower pump multiplier potential."
    ),
}

st.markdown(
    f"""<div style="background:{rec_bg};border:2px solid {rec_col};
    border-radius:12px;padding:16px 20px;margin-top:8px;">
    <div style="font-size:1.1rem;font-weight:800;color:{rec_col};">
    {rec_icon} {recommendation}</div>
    <div style="font-size:0.85rem;color:#cbd5e1;margin-top:6px;line-height:1.5;">
    {rec_explanations.get(recommendation, "")}</div>
    </div>""",
    unsafe_allow_html=True,
)

# ── External links ──────────────────────────────────────────────────────
st.markdown(
    f"🔗 "
    f"[DexScreener](https://dexscreener.com/solana/{ca}) · "
    f"[GMGN](https://gmgn.ai/sol/token/{ca}) · "
    f"[Solscan](https://solscan.io/token/{ca}) · "
    f"[Birdeye](https://birdeye.so/token/{ca}?chain=solana)"
)

# ── Raw data expander ───────────────────────────────────────────────────
with st.expander("🔧 Raw Data (JSON)", expanded=False):
    st.json(result)

# ── Footer ──────────────────────────────────────────────────────────────
st.caption(
    f"Analysis timestamp: {result.get('analysis_timestamp', '?')} · "
    f"Data: DexScreener + GeckoTerminal + GMGN Trades API · "
    f"SOL price: ${get_sol_price():,.2f} · "
    f"Heuristic — NOT financial advice. Always DYOR."
)
