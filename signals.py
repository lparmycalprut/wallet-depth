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
                     detect_divergence, fetch_price_series)
    recorded = []

    # --- flow check on the raw swap store (complete window) -----------------
    swaps = get_recent_swaps(ca, window_h)
    if swaps:
        wh = rt = 0.0
        for side, sol, ts, _w in swaps:
            signed = sol if side == "buy" else -sol
            if sol >= WHALE_SOL:
                wh += signed
            else:
                rt += signed
        if (wh >= 0) != (rt >= 0) and max(abs(wh), abs(rt)) >= 5:
            if wh >= 0:
                ok = record_signal(
                    ca, symbol, "accumulation",
                    f"whales +{wh:.1f} SOL vs retail {rt:+.1f} SOL "
                    f"(last {window_h}h, {len(swaps)} swaps)",
                    src=src, window_h=window_h, whale_net=wh,
                    retail_net=rt, price=price_now)
            else:
                ok = record_signal(
                    ca, symbol, "distribution",
                    f"whales {wh:+.1f} SOL vs retail +{rt:.1f} SOL "
                    f"(last {window_h}h, {len(swaps)} swaps)",
                    src=src, window_h=window_h, whale_net=wh,
                    retail_net=rt, price=price_now)
            if ok:
                recorded.append("accumulation" if wh >= 0 else "distribution")

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
