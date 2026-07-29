# -*- coding: utf-8 -*-
"""Breakout Guard — D1 levels, H4 confirmation, on-chain attribution.

Design (rewritten):

* **Levels come from DAILY candles.** A level that survived a whole day is
  one other traders can see too; the old H1 pivots produced dozens of
  micro-levels that fired constantly.
* **Decisions are made on a CLOSED H4 candle**, never on the live tick.
  Nothing is evaluated until ``now >= candle_open + 4h``, so a wick that
  gets bought back inside the candle is not mistaken for a break.
* **Every alert names who was behind the candle** — whale vs retail, buy
  vs sell, pure accumulators vs distributors — because "price broke the
  level" is not actionable but "whales sold into retail buying" is.
* **Every event is logged to its own file** (``breakouts.json``) with the
  candle and the flow, and later events link back via ``parent_id``, so a
  spring or a reclaim can be analysed against the break that preceded it.

Event vocabulary (all judged on the H4 close):

===================  =====================================================
``breakout``         closed ABOVE a daily resistance
``failed_breakout``  poked above resistance but closed back below (wick)
``breakdown``        closed BELOW a daily support
``spring``           poked below support but closed back above (wick)
``reclaim``          closed back above a lost support within 5 H4 candles
===================  =====================================================

A confirmed ``breakout`` that later closes back below the level is logged
as ``failed_breakout`` linked to it; a ``breakdown`` that is won back is
logged as ``reclaim``. Both close out the parent event's ``outcome``.
"""
import json
import os
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEVELS_PATH = os.path.join(BASE_DIR, "levels.json")

H4 = 4 * 3600
#: how many H4 candles a break has to be reclaimed / to fail within
RECLAIM_MAX_CANDLES = 5
#: same level + same event may not re-alert within this many hours
ALERT_DEDUPE_H = 12
#: don't alert on a candle that closed longer ago than this (cron catch-up
#: still logs it, it just doesn't spam stale notifications)
ALERT_FRESH_H = 8
#: price must clear the level by this fraction for the event to count —
#: filters out "touched it to the tick" noise
MIN_PENETRATION = 0.0015          # 0.15%
#: a wick must be at least this fraction of the candle's range to read as
#: a genuine rejection rather than a rounding artefact
MIN_WICK_RATIO = 0.20
MAX_LEVELS = 6

#: prefix that makes it obvious which subsystem sent the message
GUARD_TAG = "\U0001F6E1\ufe0f <b>BREAKOUT GUARD</b>"
GUARD_SUB = "<i>D1 levels \u00b7 confirmed on H4 close</i>"


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
    """Daily support/resistance for *pool*.

    Thin wrapper over :func:`cvd.daily_levels` so the guard keeps one
    obvious entry point for levels (and older callers keep working).
    """
    from cvd import daily_levels
    return daily_levels(pool, limit=60, left=2, right=2, max_levels=MAX_LEVELS)


def fmt(v) -> str:
    """Price formatter that survives 9-decimal memecoin prices."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "?"
    if v >= 1:
        return f"${v:,.4f}".rstrip("0").rstrip(".")
    s = f"${v:.10f}".rstrip("0")
    return s.rstrip(".") if s not in ("$0.", "$") else "$0"


def closed_h4_candles(pool: str, *, limit: int = 60, now: float = None):
    """H4 candles that have actually CLOSED, oldest -> newest.

    GeckoTerminal includes the candle currently forming; acting on it is
    exactly the mistake this guard is meant to avoid, so it is dropped.
    """
    from cvd import fetch_candles
    now = time.time() if now is None else now
    candles = fetch_candles(pool, timeframe="hour", aggregate=4, limit=limit)
    return [c for c in candles if c["ts"] + H4 <= now]


# ---------------------------------------------------------------------------
# Event classification on a single closed H4 candle
# ---------------------------------------------------------------------------
def classify_candle(candle, prev_close, highs, lows):
    """What did this closed H4 candle do to the daily levels?

    Returns a list of ``(event, level)``. ``prev_close`` may be None (first
    candle we ever saw) in which case only wick events are reported — we
    cannot know whether a close-through was a *new* crossing.
    """
    out = []
    o, h, low, c = candle["o"], candle["h"], candle["l"], candle["c"]
    rng = max(h - low, 0.0)

    for lv in highs or []:
        if lv <= 0:
            continue
        cleared = (c - lv) / lv >= MIN_PENETRATION
        poked = (h - lv) / lv >= MIN_PENETRATION
        if cleared:
            # a genuine new crossing needs the previous candle to be below
            if prev_close is not None and prev_close <= lv:
                out.append(("breakout", lv))
        elif poked and c < lv:
            # wick above resistance, closed back under = rejection
            upper_wick = h - max(o, c)
            if rng > 0 and upper_wick / rng >= MIN_WICK_RATIO:
                out.append(("failed_breakout", lv))

    for lv in lows or []:
        if lv <= 0:
            continue
        lost = (lv - c) / lv >= MIN_PENETRATION
        poked = (lv - low) / lv >= MIN_PENETRATION
        if lost:
            if prev_close is not None and prev_close >= lv:
                out.append(("breakdown", lv))
        elif poked and c > lv:
            # wick below support, closed back above = spring / shakeout
            lower_wick = min(o, c) - low
            if rng > 0 and lower_wick / rng >= MIN_WICK_RATIO:
                out.append(("spring", lv))
    return out


def verdict_for(event, flow, ctx=None):
    """Verdict + emoji + reasons, driven by WHO traded inside the candle.

    *flow* is a :func:`cvd.flow_report` over the candle window; *ctx* is the
    optional wider :func:`diagnose_breakout` context.
    """
    if not flow or not flow.get("n"):
        return ("UNCONFIRMED", "\U0001F7E1",
                "no on-chain swaps stored for this candle")

    wn, rn, npure = flow["whale_net"], flow["retail_net"], flow["net_pure"]
    rvol = (ctx or {}).get("rvol_onchain")
    reasons = []
    up_move = event in ("breakout", "reclaim", "spring")

    if wn > 0:
        reasons.append(f"whales net BUYING {wn:+.1f} SOL "
                       f"({flow['n_whale_buyers']} wallets)")
    elif wn < 0:
        reasons.append(f"whales net SELLING {wn:+.1f} SOL "
                       f"({flow['n_whale_sellers']} wallets)")
    else:
        reasons.append("no whale-sized flow")
    if rn:
        reasons.append(f"retail {rn:+.1f} SOL")
    if npure:
        reasons.append(f"net pure {npure:+.1f}")
    if rvol:
        reasons.append(f"on-chain RVOL {rvol:.1f}x")

    # score the move: whales carry double weight, pure flow single
    good = bad = 0
    if up_move:
        good += 2 if wn > 0 else 0
        bad += 2 if wn < 0 else 0
        good += 1 if npure > 0 else 0
        bad += 1 if npure < 0 else 0
    else:
        good += 2 if wn < 0 else 0      # "good" = the move is genuine
        bad += 2 if wn > 0 else 0
        good += 1 if npure < 0 else 0
        bad += 1 if npure > 0 else 0
    if rvol is not None:
        if rvol >= 2:
            good += 1
        elif rvol < 1.2:
            bad += 1

    why = " \u00b7 ".join(reasons)

    if event == "breakout":
        if wn < 0 and rn > 0:
            return ("BULL TRAP", "\U0001F534",
                    "whales exit into retail FOMO \u2014 " + why)
        if good >= 3 and bad == 0:
            return ("REAL MARKUP", "\U0001F7E2", why)
        return (("LEANS REAL", "\U0001F7E2", why) if good > bad
                else ("LEANS TRAP", "\U0001F534", why) if bad > good
                else ("UNCLEAR", "\U0001F7E1", why))

    if event == "breakdown":
        if wn > 0 and rn < 0:
            return ("SHAKEOUT?", "\U0001F7E1",
                    "whales bought the breakdown \u2014 " + why)
        if good >= 3 and bad == 0:
            return ("REAL BREAKDOWN", "\U0001F534", why)
        return (("LEANS REAL", "\U0001F534", why) if good > bad
                else ("LEANS SHAKEOUT", "\U0001F7E1", why) if bad > good
                else ("UNCLEAR", "\U0001F7E1", why))

    if event == "spring":
        if wn > 0:
            return ("BULLISH SPRING", "\U0001F7E2",
                    "support wicked and whales absorbed it \u2014 " + why)
        if rn > 0 and wn <= 0:
            return ("WEAK SPRING", "\U0001F7E1",
                    "only retail defended the level \u2014 " + why)
        return ("UNCLEAR SPRING", "\U0001F7E1", why)

    if event == "failed_breakout":
        if wn < 0:
            return ("REJECTED (whales sold)", "\U0001F534",
                    "whales sold the poke above \u2014 " + why)
        return ("REJECTED", "\U0001F534", why)

    if event == "reclaim":
        if wn > 0:
            return ("WHALE RECLAIM", "\U0001F7E2",
                    "whales drove the reclaim \u2014 " + why)
        if rn > 0:
            return ("RETAIL RECLAIM", "\U0001F7E1",
                    "retail-only reclaim, weaker \u2014 " + why)
        return ("WEAK RECLAIM", "\U0001F7E1", why)

    return ("UNCLEAR", "\U0001F7E1", why)


# ---------------------------------------------------------------------------
# Wider on-chain context (unchanged behaviour, kept for the RVOL figure)
# ---------------------------------------------------------------------------
def diagnose_breakout(ca, hours_move=4, baseline_h=24):
    """Non-churn RVOL + whale/pure flow over the recent move window."""
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


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------
def _plan_up(level, price_now, lows, highs):
    stop = level * 0.97
    hard = next((s for s in lows if s < level), None)
    tps = [h for h in highs if h > level][:2]
    txt = ("\n\n\U0001F4CB <b>ACTION PLAN</b>"
           f"\n\U0001F6D1 Stop: H4 close &lt; {fmt(stop)} "
           f"(-3%, back inside range)")
    if hard:
        txt += f"\n\U0001F6D1 Hard invalidation: {fmt(hard)} (next D1 support)"
    if tps:
        txt += "\n\U0001F3AF TP zones: " + " \u2192 ".join(fmt(t) for t in tps)
        risk = price_now - stop
        if risk > 0 and tps[0] > price_now:
            rr = (tps[0] - price_now) / risk
            txt += f"\n\U0001F4D0 R:R to TP1 \u2248 {rr:.1f}"
    txt += ("\n\U0001F4A1 next H4 closing back below the level = failed "
            "breakout \u2014 act on the stop, not on hope.")
    return txt


def _plan_down(level, lows):
    reclaim = level * 1.02
    nxt = next((s for s in lows if s < level), None)
    txt = ("\n\n\U0001F4CB <b>ACTION PLAN</b>"
           f"\n\U0001F7E2 Thesis alive only on a fast reclaim: H4 close &gt; "
           f"{fmt(reclaim)} within {RECLAIM_MAX_CANDLES} candles")
    if nxt:
        txt += (f"\n\U0001F6D1 If no reclaim: next D1 support {fmt(nxt)} "
                f"\u2014 cut there at the latest")
    else:
        txt += ("\n\U0001F6D1 No D1 support left below \u2014 if no fast "
                "reclaim, cut immediately")
    txt += ("\n\U0001F4A1 holding a lost support without a reclaim is how "
            "small losses become big ones.")
    return txt


TITLES = {
    "breakout": "BROKE RESISTANCE",
    "failed_breakout": "FAILED BREAKOUT",
    "breakdown": "LOST SUPPORT",
    "spring": "SPRING (support held)",
    "reclaim": "RECLAIMED",
}


def build_message(*, event, symbol, ca, level, candle, flow, verdict, emoji,
                  why, highs, lows, extra_note="", history=None):
    """Render the Telegram text for one level event."""
    from cvd import describe_flow, flow_warning

    up_move = event in ("breakout", "reclaim", "spring")
    direction = "up" if up_move else "down"
    when = time.strftime("%d %b %H:%M", time.gmtime(candle["ts"]))

    head = f"{GUARD_TAG}\n{GUARD_SUB}\n\n"
    title = (f"{emoji} <b>${symbol} \u2014 {TITLES.get(event, event)} "
             f"{fmt(level)}</b>")

    body = (f"\n\U0001F551 H4 candle {when} UTC (closed)"
            f"\n\U0001F4C8 O {fmt(candle['o'])} \u00b7 H {fmt(candle['h'])} "
            f"\u00b7 L {fmt(candle['l'])} \u00b7 C <b>{fmt(candle['c'])}</b>"
            f"\n\u2696\ufe0f Verdict: <b>{verdict}</b>"
            f"\n{why}")
    if extra_note:
        body += f"\n{extra_note}"

    flow_block = ("\n\n\U0001F50D <b>WHO WAS BEHIND THIS CANDLE</b>\n"
                  + describe_flow(flow)
                  + "\n" + flow_warning(flow, direction))

    if event in ("breakout", "spring", "reclaim"):
        plan = _plan_up(level, candle["c"], lows, highs)
    elif event in ("breakdown", "failed_breakout"):
        plan = _plan_down(level, lows)
    else:
        plan = ""

    hist = ""
    if history:
        hist = ("\n\n\U0001F4DC <b>This level before</b>\n"
                + "\n".join("\u2022 " + h for h in history[:3]))

    link = (f"\n\n<a href='https://dexscreener.com/solana/{ca}'>chart</a>"
            f" \u00b7 <code>{ca}</code>")
    return head + title + body + flow_block + plan + hist + link


# ---------------------------------------------------------------------------
# Main guard
# ---------------------------------------------------------------------------
def _deliver(event_id, msg, fresh):
    """Send one event's alert now, if it is still worth sending.

    A stale candle (cron catch-up after downtime) is logged but not
    announced. The event is only marked delivered when Telegram actually
    accepted it, so a failed send stays queued for
    :func:`flush_pending_alerts`.
    """
    from breakout_log import mark_alerted
    if not fresh:
        return False
    if send_telegram(msg):
        mark_alerted(event_id)
        return True
    return False


def flush_pending_alerts(*, now: float = None):
    """Retry alerts whose Telegram send failed on an earlier run.

    The old code marked a level as alerted *before* knowing the send
    worked, so a Telegram outage silently swallowed the notification.
    """
    from breakout_log import mark_alerted, pending_alerts
    sent = 0
    for e in pending_alerts(now=now):
        if send_telegram(e.get("msg") or ""):
            mark_alerted(e["id"])
            sent += 1
    return sent


def run_guard(ca, symbol, pool, price_now, *, now: float = None):
    """Evaluate newly-closed H4 candles against the daily levels.

    Called once per token per cron run. Returns a list of
    ``(event, level, verdict)`` for the alerts that went out.

    ``now`` overrides the clock (tests simulate successive cron runs with
    it); production callers leave it None.
    """
    from breakout_log import (events_for, history_line, make_id, record_event,
                              set_outcome)
    from cvd import flow_report, swaps_between

    state = load_levels()
    entry = state.get(ca) or {}
    entry.setdefault("levels", {})
    entry.setdefault("alerted", {})
    entry.setdefault("pending", [])
    sent = []
    now = time.time() if now is None else now

    # ---- refresh DAILY levels -------------------------------------------
    lv = compute_levels(pool)
    if lv:
        entry["levels"] = {"highs": lv["highs"], "lows": lv["lows"],
                           "tf": "D1", "updated": int(now)}
    highs = (entry.get("levels") or {}).get("highs") or []
    lows = (entry.get("levels") or {}).get("lows") or []

    # ---- only look at candles that have actually closed ------------------
    candles = closed_h4_candles(pool, now=now)
    if not candles:
        entry["last_price"] = price_now
        state[ca] = entry
        save_levels(state)
        return sent

    last_seen = entry.get("last_h4_ts")
    if last_seen is None:
        # First run for this token: set the baseline, never fire on history.
        entry["last_h4_ts"] = candles[-1]["ts"]
        entry["last_price"] = price_now
        state[ca] = entry
        save_levels(state)
        return sent

    new = [c for c in candles if c["ts"] > last_seen]
    if not new:
        entry["last_price"] = price_now
        state[ca] = entry
        save_levels(state)
        return sent

    by_ts = {c["ts"]: c for c in candles}
    alerted = entry.get("alerted") or {}
    pending = entry.get("pending") or []

    def recently(key):
        return now - (alerted.get(key) or 0) < ALERT_DEDUPE_H * 3600

    for candle in new:
        cts = candle["ts"]
        prev = by_ts.get(cts - H4)
        prev_close = prev["c"] if prev else None
        fresh = (now - (cts + H4)) <= ALERT_FRESH_H * 3600

        # flow INSIDE this candle — the heart of the whole feature
        flow = flow_report(swaps_between(ca, cts, cts + H4))
        ctx = diagnose_breakout(ca) if fresh else None

        events = classify_candle(candle, prev_close, highs, lows)

        # ---- resolve still-open breaks first -----------------------------
        # resolved_parent maps level -> the event id being closed out, so the
        # follow-up alert can link back to it (the pending entry itself is
        # dropped below, which is why the id is captured here).
        still_open, resolved_parent = [], {}
        for p in pending:
            age = int((cts - p["candle_ts"]) // H4)
            lvl = p["level"]
            resolved = False
            up_ok = candle["c"] > lvl * (1 + MIN_PENETRATION)
            dn_ok = candle["c"] < lvl * (1 - MIN_PENETRATION)
            if p["dir"] == "down" and up_ok:
                events.append(("reclaim", lvl))
                set_outcome(p["event_id"], "reclaimed")
                resolved_parent[lvl] = p["event_id"]
                resolved = True
            elif p["dir"] == "up" and dn_ok:
                events.append(("failed_breakout", lvl))
                set_outcome(p["event_id"], "failed")
                resolved_parent[lvl] = p["event_id"]
                resolved = True
            elif age >= RECLAIM_MAX_CANDLES:
                set_outcome(p["event_id"],
                            "held" if p["dir"] == "up" else "no_reclaim")
                resolved = True
            if not resolved:
                still_open.append(p)
        pending = still_open

        # A candle that wicks below a lost support and closes back above it
        # is a RECLAIM, not a fresh spring — keep the stronger reading and
        # drop duplicates of the same (event, level) pair.
        reclaimed_levels = {lv for ev, lv in events if ev == "reclaim"}
        seen_ev = set()
        deduped = []
        for ev, lv in events:
            if ev == "spring" and lv in reclaimed_levels:
                continue
            if (ev, lv) in seen_ev:
                continue
            seen_ev.add((ev, lv))
            deduped.append((ev, lv))
        events = deduped

        # ---- emit events --------------------------------------------------
        for event, level in events:
            key = f"{event}:{level:.12g}"
            if recently(key):
                continue
            eid = make_id(ca, event, cts)
            verdict, emoji, why = verdict_for(event, flow, ctx)

            # link a follow-up back to the break it resolves
            parent = resolved_parent.get(level)
            if parent is None:
                parent = next((p["event_id"] for p in pending
                               if abs(p["level"] - level) < 1e-18), None)
            note = ""
            if event in ("reclaim", "failed_breakout") and parent:
                prior = next((e for e in events_for(ca, limit=40)
                              if e.get("id") == parent), None)
                if prior:
                    n = max(1, int((cts - (prior.get("candle", {}) or {})
                                    .get("ts", cts)) // H4))
                    word = ("reclaimed" if event == "reclaim"
                            else "failed")
                    note = (f"\u21a9\ufe0f {word} {n} H4 candle(s) after the "
                            f"{prior.get('event')}")

            hist = [history_line(e) for e in events_for(ca, limit=8)
                    if abs((e.get("level") or 0) - level) < 1e-18
                    and e.get("id") != eid]

            msg = build_message(
                event=event, symbol=symbol or "?", ca=ca, level=level,
                candle=candle, flow=flow, verdict=verdict, emoji=emoji,
                why=why, highs=highs, lows=lows, extra_note=note,
                history=hist)

            pen = ((candle["h"] - level) / level if event in
                   ("breakout", "failed_breakout")
                   else (level - candle["l"]) / level)
            rec = {
                "id": eid, "ts": int(now), "ca": ca, "symbol": symbol,
                "event": event, "level": level, "levels_tf": "D1",
                "level_kind": "resistance" if event in
                              ("breakout", "failed_breakout") else "support",
                "candle": candle, "penetration_pct": round(pen * 100, 3),
                "flow": flow, "verdict": verdict, "why": why,
                "parent_id": parent, "msg": msg, "alerted": False,
            }
            if record_event(rec) is None:
                continue          # already logged on an earlier run

            if _deliver(eid, msg, fresh):
                sent.append((event, level, verdict))
                alerted[key] = now

            # a confirmed break starts a watch window
            if event in ("breakout", "breakdown"):
                pending.append({"event_id": eid, "level": level,
                                "dir": "up" if event == "breakout" else "down",
                                "candle_ts": cts})

            # log the follow-up into signals.json too (history, no alert)
            try:
                from signals import record_signal
                record_signal(ca, symbol, f"guard_{event}",
                              f"{event} @ {fmt(level)} (D1/H4) -> {verdict}: "
                              f"{why}", src="guard", price=candle["c"])
            except Exception:
                pass

        entry["last_h4_ts"] = cts

    entry["alerted"] = alerted
    entry["pending"] = pending
    entry["last_price"] = price_now
    state[ca] = entry
    save_levels(state)
    return sent
