# -*- coding: utf-8 -*-
"""Breakout Guard + Telegram alerts.

Cron flow: build swing high/low levels from H1 candles -> detect level
crossings -> diagnose with on-chain data (on-chain RVOL, whale CVD, pure
flow, conviction) -> verdict REAL MARKUP / BULL TRAP / UNCLEAR -> send
Telegram alert + record to signals.json.
"""
import json
import os
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEVELS_PATH = os.path.join(BASE_DIR, "levels.json")
ALERT_DEDUPE_H = 12
MAX_LEVELS = 6


def _tg_creds():
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat:
        try:
            with open(os.path.join(BASE_DIR, "config.json")) as f:
                cfg = json.load(f) or {}
            tok = tok or str(cfg.get("telegram_bot_token", "")).strip()
            chat = chat or str(cfg.get("telegram_chat_id", "")).strip()
        except Exception:
            pass
    return tok, chat


def send_telegram(text: str) -> bool:
    tok, chat = _tg_creds()
    if not tok or not chat:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}, timeout=15)
        return bool(r.json().get("ok"))
    except Exception:
        return False


def load_levels() -> dict:
    try:
        with open(LEVELS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_levels(state: dict) -> None:
    try:
        with open(LEVELS_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, separators=(",", ":"))
    except Exception:
        pass


def compute_levels(pool: str):
    """Swing highs/lows from H1 candles (GeckoTerminal), pivots L/R=3."""
    try:
        r = requests.get(
            "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
            f"{pool}/ohlcv/hour", params={"aggregate": 1, "limit": 120},
            headers={"accept": "application/json"}, timeout=20)
        lst = (((r.json() or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list") or []
    except Exception:
        return None
    if len(lst) < 10:
        return None
    lst = list(reversed(lst))
    highs = [float(c[2]) for c in lst]
    lows = [float(c[3]) for c in lst]
    closes = [float(c[4]) for c in lst]
    price = closes[-1]
    L = 3
    swing_h, swing_l = [], []
    for i in range(L, len(lst) - L):
        if highs[i] == max(highs[i - L:i + L + 1]):
            swing_h.append(highs[i])
        if lows[i] == min(lows[i - L:i + L + 1]):
            swing_l.append(lows[i])

    def dedupe(vals):
        out = []
        for v in vals:
            if not any(abs(v - o) / o < 0.02 for o in out if o):
                out.append(v)
        return out

    res_up = sorted([v for v in dedupe(swing_h) if v > price])[:MAX_LEVELS]
    sup_dn = sorted([v for v in dedupe(swing_l) if v < price],
                    reverse=True)[:MAX_LEVELS]
    return {"highs": res_up, "lows": sup_dn, "price": price}



# ---------------------------------------------------------------------------
# On-chain diagnosis of a breakout
# ---------------------------------------------------------------------------
def diagnose_breakout(ca, hours_move=3, baseline_h=24):
    """Who is on the other side of the candle? Uses the raw swap store.
    Returns dict with on-chain RVOL (non-churn), whale net, pure flow and
    a verdict, or None if the store is empty."""
    from cvd import (WHALE_SOL, get_recent_swaps, wallet_profiles,
                     conviction_split, load_conviction)

    swaps_all = get_recent_swaps(ca, baseline_h + hours_move)
    if not swaps_all:
        return None
    now = time.time()
    cut_move = now - hours_move * 3600

    move = [s for s in swaps_all if s[2] >= cut_move]
    base = [s for s in swaps_all if s[2] < cut_move]
    if not move:
        return None

    prof = wallet_profiles(move)
    conv = conviction_split(prof, whale_min_sol=WHALE_SOL)

    def nonchurn_vol(swaps, profs):
        v = 0.0
        for side, sol, ts, w in swaps:
            p = profs.get(w)
            if p and p.get("profile") in ("pure_accum", "pure_dist"):
                v += sol
        return v

    move_nc = nonchurn_vol(move, prof)
    base_prof = wallet_profiles(base) if base else {}
    base_nc = nonchurn_vol(base, base_prof) if base else 0.0
    base_nc_per_h = base_nc / max(baseline_h, 1)
    move_nc_per_h = move_nc / max(hours_move, 1)
    rvol_onchain = (move_nc_per_h / base_nc_per_h) if base_nc_per_h > 0 \
        else (99.0 if move_nc_per_h > 0 else 0.0)

    whale_net = sum((s[1] if s[0] == "buy" else -s[1])
                    for s in move if s[1] >= WHALE_SOL)
    retail_net = sum((s[1] if s[0] == "buy" else -s[1])
                     for s in move if s[1] < WHALE_SOL)
    net_pure = conv["pure_buy"] - conv["pure_sell"]

    # conviction trend from history
    pts = (load_conviction() or {}).get(ca) or []
    conv_now = pts[-1]["conviction"] if pts else None
    conv_prev = pts[-2]["conviction"] if len(pts) >= 2 else None
    conv_rising = (conv_now is not None and conv_prev is not None
                   and conv_now > conv_prev)

    return {"rvol_onchain": round(rvol_onchain, 2),
            "move_nc_vol": round(move_nc, 1),
            "whale_net": round(whale_net, 1),
            "retail_net": round(retail_net, 1),
            "pure_buy": round(conv["pure_buy"], 1),
            "pure_sell": round(conv["pure_sell"], 1),
            "net_pure": round(net_pure, 1),
            "conviction": conv_now, "conviction_rising": conv_rising,
            "swaps_move": len(move)}


def verdict_up(d):
    """Verdict for an UPSIDE breakout."""
    if d is None:
        return ("UNCLEAR", "🟡", "no on-chain store data yet")
    good = 0
    bad = 0
    reasons = []
    if d["whale_net"] > 5:
        good += 2
        reasons.append(f"whales BUYING the breakout ({d['whale_net']:+.0f} SOL)")
    elif d["whale_net"] < -5:
        bad += 2
        reasons.append(f"whales SELLING into it ({d['whale_net']:+.0f} SOL)")
    if d["net_pure"] > 10:
        good += 1
        reasons.append(f"pure accum dominates ({d['net_pure']:+.0f})")
    elif d["net_pure"] < -10:
        bad += 1
        reasons.append(f"pure distribution ({d['net_pure']:+.0f})")
    if d["rvol_onchain"] >= 2:
        good += 1
        reasons.append(f"on-chain RVOL {d['rvol_onchain']:.1f}x (real vol)")
    elif d["rvol_onchain"] < 1.2:
        bad += 1
        reasons.append(f"thin on-chain RVOL {d['rvol_onchain']:.1f}x")
    if d["conviction_rising"]:
        good += 1
        reasons.append("conviction rising")
    if bad >= 2 and d["whale_net"] < 0 and d["retail_net"] > 0:
        return ("BULL TRAP", "🔴",
                "whales exit into retail FOMO (BUNKEE pattern) — " +
                "; ".join(reasons))
    if good >= 3 and bad == 0:
        return ("REAL MARKUP", "🟢", "; ".join(reasons))
    if good > bad:
        return ("LEANS REAL", "🟢", "; ".join(reasons))
    if bad > good:
        return ("LEANS TRAP", "🔴", "; ".join(reasons))
    return ("UNCLEAR", "🟡", "; ".join(reasons) or "mixed signals")


def verdict_down(d):
    """Verdict for a DOWNSIDE break (support lost)."""
    if d is None:
        return ("UNCLEAR", "🟡", "no on-chain store data yet")
    if d["whale_net"] > 5 and d["net_pure"] > 0:
        return ("SPRING?", "🟡",
                f"support broke BUT whales buying the dip "
                f"({d['whale_net']:+.0f} SOL, net pure {d['net_pure']:+.0f}) "
                f"— possible shakeout, watch for fast reclaim")
    if d["whale_net"] < -5 or d["net_pure"] < -10:
        return ("REAL BREAKDOWN", "🔴",
                f"whales/pure sellers driving it (whale {d['whale_net']:+.0f}"
                f", net pure {d['net_pure']:+.0f}) — structure lost")
    return ("UNCLEAR", "🟡", "mixed flow on the breakdown")



# ---------------------------------------------------------------------------
# Main guard: refresh levels, detect crossings, alert
# ---------------------------------------------------------------------------
def run_guard(ca, symbol, pool, price_now):
    """Called once per cron run per token. Returns list of alerts sent."""
    state = load_levels()
    entry = state.get(ca) or {"levels": {}, "alerted": {}, "last_price": None}
    sent = []

    lv = compute_levels(pool)
    if lv:
        entry["levels"] = {"highs": lv["highs"], "lows": lv["lows"]}
    highs = (entry.get("levels") or {}).get("highs") or []
    lows = (entry.get("levels") or {}).get("lows") or []
    prev_price = entry.get("last_price")
    now = time.time()
    alerted = entry.get("alerted") or {}

    def recently(key):
        return now - (alerted.get(key) or 0) < ALERT_DEDUPE_H * 3600

    def mark(key):
        alerted[key] = now

    def fmt(v):
        if v >= 1:
            return f"${v:,.2f}"
        return f"${v:.10f}".rstrip("0")

    def plan_up(level, lows, highs):
        stop = level * 0.97
        hard = next((s for s in lows if s < level), None)
        tps = [h for h in highs if h > level][:2]
        txt = ("\n\n\U0001F4CB <b>ACTION PLAN</b>"
               f"\n\U0001F6D1 Stop (failed breakout): close H1 &lt; "
               f"{fmt(stop)} (-3% = back inside range)")
        if hard:
            txt += (f"\n\U0001F6D1 Hard invalidation: {fmt(hard)} "
                    f"(next support)")
        if tps:
            txt += ("\n\U0001F3AF TP zones: " +
                    " \u2192 ".join(fmt(t) for t in tps))
            risk = price_now - stop
            if risk > 0 and tps[0] > price_now:
                rr = (tps[0] - price_now) / risk
                txt += f"\n\U0001F4D0 R:R to TP1 \u2248 {rr:.1f}"
        txt += ("\n\U0001F4A1 close back below the level = failed "
                "breakout \u2014 act on the stop, not on hope.")
        return txt

    def plan_down(level, lows):
        reclaim = level * 1.02
        nxt = next((s for s in lows if s < level), None)
        txt = ("\n\n\U0001F4CB <b>ACTION PLAN</b>"
               f"\n\U0001F7E2 Thesis alive again only if fast reclaim: "
               f"close H1 &gt; {fmt(reclaim)} within 1-3 candles (spring)")
        if nxt:
            txt += (f"\n\U0001F6D1 If no reclaim: next support "
                    f"{fmt(nxt)} \u2014 cut there at the latest")
        else:
            txt += ("\n\U0001F6D1 No support left below \u2014 if no "
                    "fast reclaim, cut immediately")
        txt += ("\n\U0001F4A1 holding a lost support without a reclaim "
                "is how small losses become big ones.")
        return txt

    link = f"https://dexscreener.com/solana/{ca}"

    if prev_price:
        # ---- upside breakouts ----
        for level in highs:
            key = f"up:{level:.12g}"
            if prev_price < level <= price_now and not recently(key):
                d = diagnose_breakout(ca)
                v, emo, why = verdict_up(d)
                plan = plan_up(level, lows, highs)
                extra = ""
                if d:
                    extra = (f"\n🐋 whale net: <b>{d['whale_net']:+.0f}</b> SOL"
                             f" · 🐟 retail: {d['retail_net']:+.0f}"
                             f"\n💎 pure: +{d['pure_buy']:.0f} / "
                             f"-{d['pure_sell']:.0f} (net "
                             f"{d['net_pure']:+.0f})"
                             f"\n📊 on-chain RVOL: "
                             f"<b>{d['rvol_onchain']:.1f}x</b> · conviction "
                             f"{d['conviction'] if d['conviction'] is not None else '?'}%"
                             f"{' 📈' if d['conviction_rising'] else ''}")
                msg = (f"{emo} <b>${symbol} BREAKOUT above "
                       f"{fmt(level)}</b> → {fmt(price_now)}\n"
                       f"Verdict: <b>{v}</b>\n{why}{extra}{plan}\n"
                       f"⚠️ wait for 2-3 candle follow-through before "
                       f"acting.\n<a href='{link}'>chart</a>")
                if send_telegram(msg):
                    sent.append(("breakout_up", level, v))
                    mark(key)
                try:
                    from signals import record_signal
                    record_signal(ca, symbol,
                                  "breakout_real" if "REAL" in v
                                  else ("breakout_trap" if "TRAP" in v
                                        else "breakout_unclear"),
                                  f"break {fmt(level)} -> {v}: {why}",
                                  src="guard", price=price_now)
                except Exception:
                    pass
        # ---- downside breaks ----
        for level in lows:
            key = f"dn:{level:.12g}"
            if prev_price > level >= price_now and not recently(key):
                d = diagnose_breakout(ca)
                v, emo, why = verdict_down(d)
                plan = plan_down(level, lows)
                msg = (f"{emo} <b>${symbol} broke SUPPORT "
                       f"{fmt(level)}</b> → {fmt(price_now)}\n"
                       f"Verdict: <b>{v}</b>\n{why}{plan}\n"
                       f"<a href='{link}'>chart</a>")
                if send_telegram(msg):
                    sent.append(("breakdown", level, v))
                    mark(key)
                try:
                    from signals import record_signal
                    record_signal(ca, symbol, "breakdown",
                                  f"lost {fmt(level)} -> {v}: {why}",
                                  src="guard", price=price_now)
                except Exception:
                    pass

    entry["alerted"] = alerted
    entry["last_price"] = price_now
    state[ca] = entry
    save_levels(state)
    return sent
