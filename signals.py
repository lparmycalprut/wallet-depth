# -*- coding: utf-8 -*-
"""Signal log: every time the cron (or an Analyze run) detects a CVD event —
stealth accumulation, distribution, or a price/CVD divergence — it is
recorded with the exact time, so you can line it up with the chart later.

Stored in signals.json:
  [{ts, ca, symbol, type, src, detail, window_h, whale_net, retail_net,
    price}]
type: "accumulation" | "stealth_accumulation" | "distribution" |
      "bullish_div" | "bearish_div"

FOCUS_MODE (default ON)
-----------------------
When focus_mode is enabled, signals are filtered into two tiers:
  - Tier 1 (always shown + Telegram): accumulation, stealth_accumulation,
    distribution
  - Tier 2 (signals.json only, no Telegram): bullish_div, bearish_div

Divergence is still computed and stored for analytics / backtests, but
does NOT spam Telegram in focus mode. Set ``focus_mode: false`` in
config.json to revert.
"""
import json
import os
import statistics
import sys
import time

from core import atomic_write_json, load_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_PATH = os.path.join(BASE_DIR, "signals.json")
DEDUPE_SEC = 4 * 3600     # same signal type per token max once per 4h
MAX_SIGNALS = 2000

#: Tier 1 signal types (focus mode keeps these on Telegram + dashboard).
TIER1_SIGNAL_TYPES = {"accumulation", "stealth_accumulation",
                      "distribution", "prepump_imminent"}
#: Tier 2 signal types (focus mode hides these from Telegram; still
#: stored in signals.json for analysis).
TIER2_SIGNAL_TYPES = {"bullish_div", "bearish_div", "prepump_forming"}

#: Caption prefix so a Telegram reader can tell at a glance which subsystem
#: is talking. The Breakout Guard uses its own tag (see breakout_guard.py):
#: this one is flow/divergence monitoring, NOT a level event.
CVD_TAG = "\U0001F4CA <b>CVD MONITOR</b>"
CVD_SUB = "<i>order-flow \u00b7 rolling window</i>"  # was: "order-flow &amp; divergence · rolling window"


def _focus_mode() -> bool:
    """Read focus_mode from config.json; default True (focus ON)."""
    try:
        with open(os.path.join(BASE_DIR, "config.json"),
                  "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
        return bool(cfg.get("focus_mode", True))
    except Exception:
        return True


def load_signals() -> list:
    try:
        with open(SIGNALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def save_signals(sigs: list) -> None:
    try:
        atomic_write_json(SIGNALS_PATH, sigs[-MAX_SIGNALS:],
                          separators=(",", ":"))
    except Exception as exc:
        print(f"WARN: failed to save {SIGNALS_PATH}: {exc}",
              file=sys.stderr)


def record_signal(ca: str, symbol: str, sig_type: str, detail: str, *,
                  src: str = "cron", window_h: int = None,
                  whale_net: float = None, retail_net: float = None,
                  price: float = None) -> bool:
    """Append a signal unless the same (ca, type) fired within DEDUPE_SEC.
    Returns True if recorded.

    Telegram gating (focus_mode=True):
      - Tier 1 types (accumulation, stealth_accumulation, distribution)
        → always sent to Telegram
      - Tier 2 types (bullish_div, bearish_div) → stored in signals.json
        but NOT sent to Telegram (kept for analytics / backtests)
    """
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
        emo = {"accumulation": "🟢", "stealth_accumulation": "🕵️",
               "distribution": "🔴",
               "bullish_div": "📈", "bearish_div": "📉",
               "monitor_all_up": "🟢", "monitor_all_down": "🔴",
               "monitor_activity_spike": "⚡"}.get(sig_type)
        if not emo or src != "cron":
            return True
        # FOCUS_MODE: Tier 2 signals do NOT go to Telegram.
        if _focus_mode() and sig_type in TIER2_SIGNAL_TYPES:
            return True
        _queue_or_send(
            f"{CVD_TAG}\n{CVD_SUB}\n\n"
            f"{emo} <b>${symbol}</b> — {sig_type.replace('_', ' ')}\n"
            f"{detail}\n"
            f"<a href='https://dexscreener.com/solana/{ca}'>chart</a>")
    except Exception:
        pass
    return True


def detect_and_record(ca: str, symbol: str, *, src: str = "cron",
                      window_h: int = 4, price_now: float = None,
                      pool: str = None) -> list:
    """Run flow + divergence detection on the stored swaps/buckets and
    record any signals. Returns list of recorded signal types.

    Signal types (dedup 4h per (ca, type)):
      - "accumulation"        broad: LH+trader+pure_accum all positive
      - "stealth_accumulation" pure_accum whales dominating while retail
                              net is negative: pure_dist/two_way sell flow
                              exceeds light_holder/trader net buying
                              (the most important stealth pattern)
      - "distribution"        dumpers dominate holders
    """
    from cvd import (get_recent_swaps, get_series, detect_divergence,
                     fetch_price_series, wallet_profiles, WHALE_SOL)
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

        # Whale-tier pure_accum (the smart money, Fix #2.2a)
        pure_whale_net = sum(d["buy"] - d["sell"] for d in profiles.values()
                             if d.get("profile") == "pure_accum"
                             and d.get("buy", 0) >= WHALE_SOL)
        n_pure_whale = sum(1 for d in profiles.values()
                           if d.get("profile") == "pure_accum"
                           and d.get("buy", 0) >= WHALE_SOL)

        dist_net = max(0.0, sum(d["sell"] - d["buy"] for d in profiles.values()
                                if d.get("profile") in ("pure_dist", "two_way")))
        n_dist = sum(1 for d in profiles.values()
                     if d.get("profile") in ("pure_dist", "two_way"))
        # Unlike holders_net (whose component profiles are always net buyers),
        # retail_net includes net-selling pure_dist/two_way wallets and can
        # therefore represent either retail accumulation or distribution.
        retail_net = (lh_net + trader_net) - dist_net

        if n_holders >= 3 or (n_lh + n_trader) >= 2 or holders_net >= 25.0 or (dist_net >= 15.0 and n_dist >= 2):
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
            # Fix #2.2c: Stealth accumulation — whales absorb while
            # pure_dist/two_way selling exceeds LH/trader net buying.
            elif pure_whale_net >= 5.0 and n_pure_whale >= 1 and \
                    retail_net < 0:
                ok = record_signal(
                    ca, symbol, "stealth_accumulation",
                    f"🕵️ stealth accumulation: whales absorbed "
                    f"+{pure_whale_net:.1f} SOL via {n_pure_whale} pure_accum "
                    f"wallet(s) while retail net "
                    f"{retail_net:+.1f} SOL — quiet "
                    f"smart-money bid (last {window_h}h)",
                    src=src, window_h=window_h,
                    whale_net=pure_whale_net,
                    retail_net=retail_net,
                    price=price_now)
                if ok:
                    recorded.append("stealth_accumulation")
            elif retail_net <= -10.0 or (dist_net >= abs(holders_net) * 1.3 and dist_net >= 15.0):
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


# Pending Telegram snippets collected when DIGEST_MODE is on. Cron (or
# any multi-CA scan) flushes them once at the end via flush_telegram_digest()
# so the operator gets one combined message instead of N separate pings.
_DIGEST_BUF: list = []
_DIGEST_MODE: bool = False


def begin_digest() -> None:
    """Start buffering Telegram alerts into a combined digest."""
    global _DIGEST_MODE, _DIGEST_BUF
    _DIGEST_MODE = True
    _DIGEST_BUF = []


def _queue_or_send(text: str) -> bool:
    """Send *text* immediately, or queue it when digest mode is active.

    Returns True when the text was accepted (queued or delivered).
    """
    if not text:
        return False
    if _DIGEST_MODE:
        _DIGEST_BUF.append(text)
        return True
    try:
        from breakout_guard import send_telegram
        return bool(send_telegram(text))
    except Exception:
        return False


def flush_telegram_digest(*, title=None, send_fn=None) -> int:
    """Flush the digest buffer as one (or few) combined Telegram message(s).

    Returns the number of Telegram messages actually dispatched. Safe to
    call when the buffer is empty (returns 0). Always ends digest mode.
    """
    global _DIGEST_MODE, _DIGEST_BUF
    items = list(_DIGEST_BUF)
    _DIGEST_BUF = []
    _DIGEST_MODE = False
    if not items:
        return 0
    try:
        # Prefer a simple multi-item join (list of HTML snippets). Main's
        # format_combined_digest uses structured kwargs (triggered/cleared/
        # prepump) — different call shape — so we format the buffer here.
        hdr = title or "📬 <b>ALERT DIGEST</b>"
        sep = "\n\n— — —\n\n"
        body = sep.join(items)
        chunks = [hdr + "\n\n" + body]
        # Soft-split if over Telegram's 4096 limit.
        if len(chunks[0]) > 3800:
            chunks, buf, n = [], [], 0
            overhead = len(hdr) + 2
            for it in items:
                add = len(it) + (len(sep) if buf else 0)
                if buf and overhead + n + add > 3800:
                    chunks.append(hdr + "\n\n" + sep.join(buf))
                    buf, n = [it], len(it)
                else:
                    buf.append(it)
                    n += add
            if buf:
                chunks.append(hdr + "\n\n" + sep.join(buf))
    except Exception:
        chunks = items  # fall back to one-by-one
    sender = send_fn
    if sender is None:
        try:
            from breakout_guard import send_telegram as sender
        except Exception:
            return 0
    n = 0
    for chunk in chunks:
        try:
            if sender(chunk):
                n += 1
        except Exception:
            pass
    return n


def detect_prepump_and_record(ca, symbol, swaps, token_info=None, *, now_ts=None,
                              src="cron", window_min=30, whale_min_sol=3.0,
                              wallet_tags=None, bullish_div=False, pool=None,
                              pool_sol=None):
    """Run the Pre-Pump Detector on recent swaps and record/alert if scored.

    Returns the evaluate_prepump result dict (including neutral / blocked),
    or None only when evaluation itself could not run.

    Behaviour (per spec):
      - score >= 75 -> "prepump_imminent" (Tier 1, always Telegram)
      - score 55-74 -> "prepump_forming" (Tier 2, Telegram only when
        focus_mode is OFF)
      - score < 55 after a prior imminent/forming -> "prepump_cleared"
        (Telegram notice so the operator knows the setup cooled)
      - each type is deduped per (ca, type) within PREPUMP_DEDUPE_SEC (3h)
    """
    from prepump_detector import (
        evaluate_prepump, format_prepump_telegram,
        format_prepump_cleared_telegram,
        prepump_already_sent, PREPUMP_DEDUPE_SEC,
    )
    now_ts = int(now_ts if now_ts is not None else time.time())
    result = evaluate_prepump(
        swaps, token_info, ca=ca, now_ts=now_ts, window_min=window_min,
        whale_min_sol=whale_min_sol, wallet_tags=wallet_tags,
        bullish_div=bullish_div, pool_sol=pool_sol)

    def _last_prepump(sigs, ca_):
        """Most recent imminent/forming/cleared signal for this CA."""
        for s in reversed(sigs or []):
            if s.get("ca") == ca_ and s.get("type") in (
                    "prepump_imminent", "prepump_forming", "prepump_cleared"):
                return s
        return None

    # ── CLEARED path: was active, now below forming threshold ──────────
    if result["score"] < 55 or result.get("tier") in ("neutral", "blocked"):
        prev = _last_prepump(load_signals(), ca)
        if prev and prev.get("type") in ("prepump_imminent", "prepump_forming"):
            # Dedupe cleared the same way as other pre-pump types.
            if not prepump_already_sent(load_signals(), ca, "prepump_cleared",
                                        now_ts, PREPUMP_DEDUPE_SEC):
                detail = ("Pre-pump CLEARED (was %s @ %s/100 → now %s/100)"
                          % (prev.get("type"), prev.get("score"),
                             result["score"]))
                sigs = load_signals()
                sigs.append({
                    "ts": now_ts, "ca": ca, "symbol": symbol,
                    "type": "prepump_cleared", "src": src,
                    "detail": detail, "score": result["score"],
                    "prev_type": prev.get("type"),
                    "prev_score": prev.get("score"),
                    "window_min": window_min,
                    "price": (token_info or {}).get("price_usd"),
                })
                save_signals(sigs)
                # Cleared is actionable (stop watching a setup) → always TG.
                try:
                    # Main API: format_prepump_cleared_telegram(ca, token_info, last_score)
                    msg = format_prepump_cleared_telegram(
                        ca, token_info or {"symbol": symbol},
                        last_score=prev.get("score"))
                    _queue_or_send(msg)
                except Exception:
                    pass
                result = dict(result)
                result["cleared"] = True
        return result

    sig_type = ("prepump_imminent" if result["tier"] == "imminent"
                else "prepump_forming")
    if prepump_already_sent(load_signals(), ca, sig_type, now_ts,
                            PREPUMP_DEDUPE_SEC):
        return result  # evaluated, but already alerted within cooldown
    detail = ("Pre-pump score %s/100 (%s) | compression %s, asymmetry %s, "
              "delta %s, accum %s"
              % (result["score"], result["tier"],
                 result["pillars"]["compression"], result["pillars"]["asymmetry"],
                 result["pillars"]["delta"], result["pillars"]["accum"]))
    sigs = load_signals()
    sigs.append({"ts": now_ts, "ca": ca, "symbol": symbol, "type": sig_type,
                 "src": src, "detail": detail, "score": result["score"],
                 "window_min": window_min,
                 "price": (token_info or {}).get("price_usd")})
    save_signals(sigs)
    # Telegram gating by tier / focus mode
    if result["tier"] == "imminent":
        send = True
    else:
        send = not _focus_mode()
    if send:
        try:
            msg = format_prepump_telegram(result, ca, token_info)
            _queue_or_send(msg)
        except Exception:
            pass
    return result


def _monitor_cfg():
    """(bin_h, spike_mult) from config.json — default 4 jam / 5×.

    Keys: ``monitor_bin_h`` (hours per activity bin) and
    ``monitor_spike_mult`` (the × jump that counts as a spike).
    """
    try:
        cfg = load_config() or {}
        bin_h = max(1, min(int(cfg.get("monitor_bin_h", 4) or 4), 24))
        mult = max(2.0, float(cfg.get("monitor_spike_mult", 5.0) or 5.0))
    except Exception:
        bin_h, mult = 4, 5.0
    return bin_h, mult


def detect_growth_alerts(ca: str, symbol: str, point: dict | None = None) -> list:
    """Alert on synchronized monitor moves and fivefold activity (4h bins).

    Spike detection now uses **fixed, non-overlapping 4h bins** from the
    raw swap store (same clock as the Breakout Guard H4 candles), not the
    old rolling 6h snapshots — a rolling window overlaps 5/6 of its own
    history, so it needed ~25-30× average hourly activity to move 5× and
    almost never fired. Two comparisons, one deduped alert:

      * last closed bin vs the bin before it (≥5×), and
      * last closed bin vs the **median of the 4 previous bins** (catches
        a gradual ramp that a single previous bin can't see).

    Floors match ``h4_activity_series``: ≥5 tx / ≥1 SOL in the current
    bin before any 5× call counts as news. ``bin_h`` / ``spike_mult`` are
    configurable via config.json (``monitor_bin_h`` / ``monitor_spike_mult``).

    ``point`` (optional) is the latest conviction snapshot; it still
    drives the ``monitor_all_up`` / ``monitor_all_down`` checks against
    the previous snapshot.
    """
    bin_h, mult = _monitor_cfg()
    recorded = []
    try:
        from cvd import get_recent_swaps, h4_activity_series
        swaps = get_recent_swaps(ca, 48)
        act = h4_activity_series(swaps, bins=max(3, int(48 // bin_h)),
                                 now_ts=time.time(), spike_mult=mult,
                                 bin_h=bin_h)
    except Exception:
        act = None

    if act and act.get("cur") is not None:
        cur = act["cur"]
        closed = [b for b in act["bins"] if b["ts"] < int(cur["ts"])]
        prev = act.get("prev")
        baseline = closed[-5:-1]  # up to 4 closed bins before cur (median)
        floors = {"tx": 5, "vol": 1.0}
        spikes = []
        for label, key in (("TX", "tx"), ("volume", "vol")):
            new = float(cur.get(key) or 0)
            old = float(prev.get(key) or 0) if prev else 0.0
            if max(new, old) < floors[key]:
                continue
            if old > 0 and new >= old * mult:
                spikes.append(f"{label} {new / old:.1f}× vs {bin_h} jam "
                              f"sebelumnya ({old:,.0f} → {new:,.0f})")
            elif baseline:
                med = statistics.median(
                    float(b.get(key) or 0) for b in baseline)
                if med > 0 and new >= med * mult and new >= floors[key]:
                    spikes.append(f"{label} {new / med:.1f}× vs median "
                                  f"{len(baseline)} bin ({med:,.0f} → "
                                  f"{new:,.0f})")
        if spikes and record_signal(ca, symbol, "monitor_activity_spike",
                                    f"Lonjakan {bin_h} jam: " + "; ".join(spikes),
                                    src="cron", window_h=bin_h):
            recorded.append("monitor_activity_spike")

    # Synchronized all-up / all-down from consecutive conviction snapshots.
    if not point:
        return recorded
    try:
        from cvd import load_conviction
        points = load_conviction().get(ca, [])
    except Exception:
        return recorded
    if len(points) < 2:
        return recorded
    previous = points[-2]
    keys = ("accum_wallets", "conviction", "swaps", "vol")
    if any(k not in previous or k not in point for k in keys):
        return recorded
    current = [float(point[k] or 0) for k in keys]
    before = [float(previous[k] or 0) for k in keys]
    if all(a > b for a, b in zip(current, before)):
        if record_signal(ca, symbol, "monitor_all_up",
                         "Semua monitor 4h naik: accumulator, conviction, "
                         "TX, volume.",
                         src="cron", window_h=bin_h):
            recorded.append("monitor_all_up")
    elif all(a < b for a, b in zip(current, before)):
        if record_signal(ca, symbol, "monitor_all_down",
                         "Semua monitor 4h turun: accumulator, conviction, "
                         "TX, volume.",
                         src="cron", window_h=bin_h):
            recorded.append("monitor_all_down")
    return recorded
