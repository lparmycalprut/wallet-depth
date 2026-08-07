# -*- coding: utf-8 -*-
"""Prepump Baru detector — validated from GMGN real data (prepump_baru repo).

Implements the 1-day FAST signals from HANDOFF_WALLET_DEPTH.md §2.1,
which were validated on 10 pump tokens (testicle, punch 1/2, grail, bountywork,
assface, ansem 1/2, chance, hoppy) + LUNA 3-day sequence.

This is the NEW sinyal column for the watchlist. It does NOT use the old
4-pillar score (prepump_detector.py) — it directly checks the validated
patterns: avg SELL > BUY, whale net negative, CVD flat, buy TX breadth, spring,
etc.  The old detector is kept for CVD deep-dive page, but the watchlist
daily sinyal now comes from here.

Daily window: previous UTC day (00:00 UTC → 00:00 UTC) evaluated at 07:00 WIB
(00:00 UTC), which is when GMGN daily candles flip. The cron calls
`evaluate_baru_daily(swaps, price_candles, wallet_tags)` once per watchlist CA.

For offline / parcial data, price-dependent checks degrade gracefully to
"unknown" and are excluded from the lolos count.
"""

import time
from collections import Counter, defaultdict

# Core validated signals (HANDOFF §2.1)
# Each is a function (ctx) -> (passed: bool, detail: str, weight)
# We keep the 7 most reliable (≥9/10) as primary gates.
# Retention / holder checks are secondary (≥6/10) and not required for tier.
CHECKS = [
    "sell_gt_buy",        # 10/10 avg SELL > avg BUY
    "whale_negative",     # 10/10 whale net negative
    "pantul_gt_5",        # 10/10 low→close >5%
    "cvd_flat",           # 9/10 |CVD/vol| <10%
    "buy_tx_ge_52",       # 9/10 buy TX ≥52%
    "after_low_net_buy",  # 9/10 3h after low net BUY
    "spring_55",          # 9/10 spring 15m post-low buy% ≥55%
]

# Threshold for "sinyal muncul" — core 3 (sell>buy, whale neg, pantul) + at least 3 of the other 4
CORE_REQUIRED = {"sell_gt_buy", "whale_negative", "pantul_gt_5"}
MIN_LOLOS = 6  # out of 7

# Whale threshold per HANDOFF ( >1 SOL/tx )
WHALE_SOL = 1.0
# Spring detection
SPRING_BUY_PCT = 55.0
# CVD tolerance
CVD_VOL_PCT = 10.0


def _avg_sol(sizes):
    if not sizes:
        return 0.0
    return sum(sizes) / len(sizes)


def evaluate_baru_daily(swaps, *, token_info=None, candles=None, now_ts=None):
    """Evaluate one daily window for prepump Baru signals.

    Args:
        swaps: iterable of (side, sol, ts, wallet) — raw GMGN trades for the
               window being evaluated (e.g. last 24h). `side` is "buy"/"sell"
               (case-insensitive), `sol` is SOL amount (float), `ts` unix,
               `wallet` string.
        token_info: optional dict {symbol, price_usd, mc, low_price, close_price,
                    low_time} — if provided, price checks use it; otherwise we
                    try to infer low/close from `candles`.
        candles: optional list of {ts, o, h, l, c, v} (GeckoTerminal) for price
                 low/close. If None and token_info has no low/close, price
                 checks become "unknown".
        now_ts: evaluation time (unix). Defaults to now.

    Returns dict:
        {
          tier: "sinyal_muncul" | "belum" | "unknown",
          score: lolos count (0-7),
          total: 7,
          checks: {name: {passed, detail, value}},
          lolos: int,
          detail: human-readable summary,
          raw: {vol, buy, sell, cvd, buy_tx_pct, avg_buy, avg_sell, whale_net, ...}
        }
    """
    now_ts = int(now_ts or time.time())
    # Normalize swaps
    buys = []
    sells = []
    buy_tx = 0
    sell_tx = 0
    total_vol = 0.0
    cvd = 0.0
    whale_buys = []
    whale_sells = []
    # For spring detection we need per-wallet 15m bins around low, so keep raw
    swaps_norm = []
    for s in (swaps or []):
        if len(s) < 4:
            continue
        side = str(s[0]).lower()
        try:
            sol = float(s[1])
        except Exception:
            continue
        try:
            ts = int(s[2])
        except Exception:
            continue
        wallet = str(s[3]) if len(s) > 3 else ""
        if sol <= 0:
            continue
        swaps_norm.append((side, sol, ts, wallet))
        total_vol += sol
        if side == "buy":
            buys.append(sol)
            buy_tx += 1
            cvd += sol
            if sol >= WHALE_SOL:
                whale_buys.append(sol)
        else:
            sells.append(sol)
            sell_tx += 1
            cvd -= sol
            if sol >= WHALE_SOL:
                whale_sells.append(sol)

    total_tx = buy_tx + sell_tx
    buy_tx_pct = (buy_tx / total_tx * 100) if total_tx else 0.0
    avg_buy = _avg_sol(buys)
    avg_sell = _avg_sol(sells)
    whale_net = sum(whale_buys) - sum(whale_sells)
    cvd_pct = (cvd / total_vol * 100) if total_vol else 0.0

    # Price-derived values
    low_price = None
    close_price = None
    low_time = None
    if token_info:
        low_price = token_info.get("low_price")
        close_price = token_info.get("close_price") or token_info.get("price_usd")
        low_time = token_info.get("low_time")
        # Fallback: try candles
    if (low_price is None or close_price is None) and candles:
        try:
            # candles: list of dict with l, c, ts
            # Find candle with minimum low
            min_c = min(candles, key=lambda c: float(c.get("l") or c.get("low") or float("inf")))
            low_price = float(min_c.get("l") or min_c.get("low"))
            low_time = int(min_c.get("ts") or min_c.get("timestamp") or 0)
            # Close is last candle close
            last_c = max(candles, key=lambda c: int(c.get("ts") or 0))
            close_price = float(last_c.get("c") or last_c.get("close") or 0)
        except Exception:
            pass

    # If still no price, we cannot evaluate pantul
    pantul_pct = None
    if low_price and close_price and low_price > 0:
        try:
            pantul_pct = (close_price / low_price - 1) * 100
        except Exception:
            pantul_pct = None

    # Spring detection: need 15m bins 3h after low
    spring_found = False
    spring_max_buy = 0.0
    spring_detail = "no low_time"
    after_low_net = None
    after_low_buy_pct = None
    if low_time and swaps_norm:
        try:
            # Window 3h after low
            t0 = low_time
            t1 = low_time + 3 * 3600
            after_swaps = [s for s in swaps_norm if t0 < s[2] <= t1]
            if after_swaps:
                after_buy = sum(sol for side, sol, _, _ in after_swaps if side == "buy")
                after_sell = sum(sol for side, sol, _, _ in after_swaps if side == "sell")
                after_vol = after_buy + after_sell
                after_low_net = after_buy - after_sell
                after_low_buy_pct = (after_buy / after_vol * 100) if after_vol else 0.0
                # 15m bins
                bins = defaultdict(list)
                for side, sol, ts, _ in after_swaps:
                    bin_ts = (ts // 900) * 900  # 15min = 900s
                    bins[bin_ts].append((side, sol))
                # Check each 15m bin for buy% >=55%
                spring_bins = []
                for bts, bswaps in sorted(bins.items()):
                    b_buy = sum(sol for side, sol in bswaps if side == "buy")
                    b_sell = sum(sol for side, sol in bswaps if side == "sell")
                    b_vol = b_buy + b_sell
                    b_pct = (b_buy / b_vol * 100) if b_vol else 0.0
                    if b_pct >= SPRING_BUY_PCT:
                        spring_bins.append((bts, b_pct, b_buy - b_sell))
                    spring_max_buy = max(spring_max_buy, b_pct)
                spring_found = len(spring_bins) > 0
                spring_detail = f"{len(spring_bins)} spring candle(s), max {spring_max_buy:.0f}%"
            else:
                spring_detail = "no swaps 3h after low"
        except Exception as e:
            spring_detail = f"error: {e}"
    else:
        spring_detail = "unknown (no low_time or no swaps)"

    # Build checks
    checks = {}

    # 1. avg SELL > avg BUY
    checks["sell_gt_buy"] = {
        "passed": avg_sell > avg_buy if (avg_buy and avg_sell) else False,
        "detail": f"avg SELL {avg_sell:.3f} vs BUY {avg_buy:.3f}",
        "value": {"avg_sell": avg_sell, "avg_buy": avg_buy},
    }
    # 2. whale net negative
    checks["whale_negative"] = {
        "passed": whale_net < 0,
        "detail": f"whale net {whale_net:+.1f} SOL ({len(whale_buys)} buys, {len(whale_sells)} sells)",
        "value": whale_net,
    }
    # 3. pantul >5%
    if pantul_pct is None:
        checks["pantul_gt_5"] = {"passed": False, "detail": "unknown (no price)", "value": None, "unknown": True}
    else:
        checks["pantul_gt_5"] = {
            "passed": pantul_pct > 5.0,
            "detail": f"low→close {pantul_pct:+.1f}% (low {low_price:.8f} → close {close_price:.8f})",
            "value": pantul_pct,
        }
    # 4. CVD flat |cvd/vol| <10%
    checks["cvd_flat"] = {
        "passed": abs(cvd_pct) < CVD_VOL_PCT,
        "detail": f"CVD {cvd:+.1f} SOL = {cvd_pct:+.1f}% vol (vol {total_vol:.1f})",
        "value": cvd_pct,
    }
    # 5. buy TX ≥52%
    checks["buy_tx_ge_52"] = {
        "passed": buy_tx_pct >= 52.0,
        "detail": f"buy TX {buy_tx_pct:.1f}% ({buy_tx}/{total_tx})",
        "value": buy_tx_pct,
    }
    # 6. 3h after low net BUY
    if after_low_net is None:
        checks["after_low_net_buy"] = {"passed": False, "detail": spring_detail, "value": None, "unknown": True}
    else:
        checks["after_low_net_buy"] = {
            "passed": after_low_net > 0,
            "detail": f"3h after low net {after_low_net:+.1f} SOL, buy% {after_low_buy_pct:.0f}%",
            "value": after_low_net,
        }
    # 7. spring ≥55%
    if spring_found is None:
        checks["spring_55"] = {"passed": False, "detail": spring_detail, "value": None, "unknown": True}
    else:
        checks["spring_55"] = {
            "passed": spring_found,
            "detail": spring_detail,
            "value": spring_max_buy,
        }

    # Count lolos, but unknown price checks should not penalize if missing data
    # For minimalist daily, we count all 7; unknown = not passed.
    # If price unknown, we will have at most 6/7, so threshold should allow 5/7 when price missing.
    lolos = sum(1 for v in checks.values() if v.get("passed"))
    total = len(CHECKS)

    # Tier logic: core 3 must pass, plus total lolos >= MIN_LOLOS
    # If price unknown, relax: core pantul is unknown, so require lolos >=5 and whale+sell pass
    has_price = not checks["pantul_gt_5"].get("unknown")
    if has_price:
        core_pass = all(checks[k]["passed"] for k in CORE_REQUIRED)
        tier = "sinyal_muncul" if (core_pass and lolos >= MIN_LOLOS) else "belum"
    else:
        # No price: require sell>buy + whale negative + at least 3 of remaining 4 non-price
        non_price_core = ["sell_gt_buy", "whale_negative"]
        core2_pass = all(checks[k]["passed"] for k in non_price_core)
        # Count non-price lolos
        non_price_lolos = sum(1 for k in ["sell_gt_buy", "whale_negative", "cvd_flat", "buy_tx_ge_52", "after_low_net_buy", "spring_55"] if checks[k]["passed"])
        tier = "sinyal_muncul" if (core2_pass and non_price_lolos >= 4) else "belum"

    # If no swaps at all, tier = unknown
    if total_tx == 0:
        tier = "unknown"
        detail = "no swaps in window"
    else:
        detail = f"lolos {lolos}/{total} — " + ", ".join(f"{k}={'✓' if v['passed'] else '✗'}" for k, v in checks.items())

    return {
        "tier": tier,
        "score": lolos,
        "total": total,
        "lolos": lolos,
        "checks": checks,
        "detail": detail,
        "raw": {
            "vol": total_vol,
            "buy": sum(buys),
            "sell": sum(sells),
            "cvd": cvd,
            "cvd_pct": cvd_pct,
            "buy_tx_pct": buy_tx_pct,
            "avg_buy": avg_buy,
            "avg_sell": avg_sell,
            "whale_net": whale_net,
            "total_tx": total_tx,
            "pantul_pct": pantul_pct,
            "spring_max_buy": spring_max_buy,
            "after_low_net": after_low_net,
        },
        "token_info": token_info or {},
    }


def format_baru_tier(tier: str, lolos: int, total: int) -> str:
    if tier == "sinyal_muncul":
        return f"🚨 SINYAL MUNCUL {lolos}/{total}"
    if tier == "belum":
        return f"➖ BELUM {lolos}/{total}"
    return "❓ UNKNOWN"


def detect_baru_and_record(ca: str, symbol: str, swaps, *, token_info=None, candles=None, now_ts=None, src="cron"):
    """Run Baru detector and record to signals.json. Returns result dict.

    Record types:
      - prepump_baru_muncul (Tier: sinyal_muncul)
      - prepump_baru_belum (not recorded, just returned)
    Telegram is queued via signals._queue_or_send if tier is sinyal_muncul.
    Dedupe 24h per CA (since daily cron).
    """
    from signals import load_signals, save_signals, PREPUMP_DEDUPE_SEC
    import time as _time
    now_ts = int(now_ts or _time.time())
    res = evaluate_baru_daily(swaps, token_info=token_info, candles=candles, now_ts=now_ts)
    tier = res["tier"]
    if tier != "sinyal_muncul":
        return res

    # Dedupe 24h (daily cron, so 20h dedupe to allow next day)
    dedupe_sec = 20 * 3600
    sigs = load_signals()
    for s in reversed(sigs[-200:]):
        if s.get("ca") == ca and s.get("type") == "prepump_baru_muncul" and now_ts - (s.get("ts") or 0) < dedupe_sec:
            return res

    # Build detail
    detail = f"Baru sinyal {res['lolos']}/{res['total']} — " + "; ".join(
        f"{k} {v['detail']}" for k, v in res["checks"].items() if v["passed"]
    )
    entry = {
        "ts": now_ts,
        "ca": ca,
        "symbol": symbol,
        "type": "prepump_baru_muncul",
        "src": src,
        "detail": detail,
        "score": res["lolos"],
        "total": res["total"],
        "tier": tier,
        "checks": {k: v["passed"] for k, v in res["checks"].items()},
        "price": (token_info or {}).get("price_usd"),
    }
    sigs.append(entry)
    save_signals(sigs)

    # Telegram (daily digest)
    if src == "cron":
        try:
            from signals import _queue_or_send
            msg = (
                f"🎯 <b>PREPUMP BARU — SINYAL MUNCUL: ${symbol}</b>\n"
                f"<code>{ca}</code>\n\n"
                f"{detail}\n\n"
                f"<a href='https://dexscreener.com/solana/{ca}'>DexScreener</a> | "
                f"<a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>"
            )
            _queue_or_send(msg)
        except Exception:
            pass
    return res
