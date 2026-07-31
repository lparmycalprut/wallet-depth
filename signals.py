# -*- coding: utf-8 -*-
"""Signal log: every time the cron (or an Analyze run) detects a CVD event —
stealth accumulation, distribution, or a price/CVD divergence — it is
recorded with the exact time, so you can line it up with the chart later.

Stored in signals.json:
  [{ts, ca, symbol, type, src, detail, window_h, whale_net, retail_net,
    price}]
type: "accumulation" | "distribution" | "bullish_div" | "bearish_div"
"""
import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_PATH = os.path.join(BASE_DIR, "signals.json")
DEDUPE_SEC = 4 * 3600     # same signal type per token max once per 4h
MAX_SIGNALS = 2000

#: Caption prefix so a Telegram reader can tell at a glance which subsystem
#: is talking. The Breakout Guard uses its own tag (see breakout_guard.py):
#: this one is flow/divergence monitoring, NOT a level event.
CVD_TAG = "\U0001F4CA <b>CVD MONITOR</b>"
CVD_SUB = "<i>order-flow &amp; divergence \u00b7 rolling window</i>"


def load_signals() -> list:
    try:
        with open(SIGNALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def save_signals(sigs: list) -> None:
    try:
        with open(SIGNALS_PATH, "w", encoding="utf-8") as f:
            json.dump(sigs[-MAX_SIGNALS:], f, separators=(",", ":"))
    except Exception:
        pass


def record_signal(ca: str, symbol: str, sig_type: str, detail: str, *,
                  src: str = "cron", window_h: int = None,
                  whale_net: float = None, retail_net: float = None,
                  price: float = None) -> bool:
    """Append a signal unless the same (ca, type) fired within DEDUPE_SEC.
    Returns True if recorded."""
    sigs = load_signals()
    now = int(time.time())
    for s in reversed(sigs[-200:]):
        if s.get("ca") == ca and s.get("type") == sig_type and \
                now - (s.get("ts") or 0) < DEDUPE_SEC:
            return False
    sigs.append({"ts": now, "ca": ca, "symbol": symbol, "type": sig_type,
                 "src": src, "detail": detail, "window_h": window_h,
                 "whale_net": whale_net, "retail_net": retail_net,
                 "price": price})
    save_signals(sigs)
    # push important signals to Telegram too (best effort)
    try:
        from breakout_guard import send_telegram
        emo = {"accumulation": "🟢", "distribution": "🔴",
               "bullish_div": "📈", "bearish_div": "📉"}.get(sig_type)
        if emo and src == "cron":
            send_telegram(
                f"{CVD_TAG}\n{CVD_SUB}\n\n"
                f"{emo} <b>${symbol}</b> — {sig_type.replace('_', ' ')}\n"
                f"{detail}\n"
                f"<a href='https://dexscreener.com/solana/{ca}'>chart</a>")
    except Exception:
        pass
    return True


def detect_and_record(ca: str, symbol: str, *, src: str = "cron",
                      window_h: int = 6, price_now: float = None,
                      pool: str = None) -> list:
    """Run flow + divergence detection on the stored swaps/buckets and
    record any signals. Returns list of recorded signal types."""
    from cvd import (WHALE_SOL, get_recent_swaps, get_series,
                     detect_divergence, fetch_price_series,
                     wallet_profiles)
    recorded = []

    # --- battle-tested CVD flow check: holders (LH/trader/pure) vs dumpers --
    swaps = get_recent_swaps(ca, window_h)
    if swaps:
        profiles = wallet_profiles(swaps)
        lh_net = sum(d["buy"] - d["sell"] for d in profiles.values()
                     if d.get("profile") == "light_holder")
        trader_net = sum(d["buy"] - d["sell"] for d in profiles.values()
                         if d.get("profile") == "trader")
        pure_net = sum(d["buy"] - d["sell"] for d in profiles.values()
                       if d.get("profile") == "pure_accum")
        n_lh = sum(1 for d in profiles.values()
                   if d.get("profile") == "light_holder")
        n_trader = sum(1 for d in profiles.values()
                       if d.get("profile") == "trader")
        n_pure = sum(1 for d in profiles.values()
                     if d.get("profile") == "pure_accum")
        holders_net = lh_net + trader_net + pure_net
        n_holders = n_lh + n_trader + n_pure

        dist_net = max(0.0, sum(d["sell"] - d["buy"] for d in profiles.values()
                                if d.get("profile") in ("pure_dist", "two_way")))
        n_dist = sum(1 for d in profiles.values()
                     if d.get("profile") in ("pure_dist", "two_way"))

        if n_holders >= 3 or (n_lh + n_trader) >= 2 or abs(holders_net) >= 25.0 or (dist_net >= 15.0 and n_dist >= 2):
            if holders_net >= 10.0 and (lh_net + trader_net) > 0 and holders_net >= max(dist_net * 1.1, 10.0):
                ok = record_signal(
                    ca, symbol, "accumulation",
                    f"holders +{holders_net:.1f} SOL net "
                    f"(LH {lh_net:+.1f} / Traders {trader_net:+.1f} / Pure {pure_net:+.1f} across {n_holders} wallets) — "
                    f"strong absorption (last {window_h}h)",
                    src=src, window_h=window_h, whale_net=holders_net,
                    retail_net=-dist_net, price=price_now)
                if ok:
                    recorded.append("accumulation")
            elif holders_net <= -10.0 or (dist_net >= abs(holders_net) * 1.3 and dist_net >= 15.0):
                ok = record_signal(
                    ca, symbol, "distribution",
                    f"distribution pressure: dumpers -{dist_net:.1f} SOL vs holders {holders_net:+.1f} SOL "
                    f"(LH {lh_net:+.1f} / Traders {trader_net:+.1f}) (last {window_h}h)",
                    src=src, window_h=window_h, whale_net=holders_net,
                    retail_net=-dist_net, price=price_now)
                if ok:
                    recorded.append("distribution")

    # --- divergence check on H1 buckets vs price -----------------------------
    if pool:
        s = get_series(ca, bucket_hours=1, hours_span=48)
        if s and len(s["ts"]) >= 7:
            pmap = fetch_price_series(pool, 1, limit=60)
            pser, last = [], None
            for t in s["ts"]:
                last = pmap.get(t, last)
                pser.append(last)
            if pser and pser[0] is None:
                fv = next((p for p in pser if p is not None), None)
                pser = [fv if p is None else p for p in pser]
            if all(p is not None for p in pser):
                divs = detect_divergence(pser, s["cvd"])
                divs += [dict(d, src_cvd="whale") for d in
                         detect_divergence(pser, s["whale"])]
                for d in divs:
                    stype = ("bullish_div" if d["type"] == "bullish"
                             else "bearish_div")
                    cvd_src = ("whale CVD" if d.get("src_cvd") == "whale"
                               else "CVD")
                    ok = record_signal(
                        ca, symbol, stype,
                        f"{d['kind']} {d['type']} divergence on {cvd_src} "
                        f"(H1): {d['detail']}",
                        src=src, window_h=window_h, price=price_now)
                    if ok:
                        recorded.append(stype)
    return recorded
