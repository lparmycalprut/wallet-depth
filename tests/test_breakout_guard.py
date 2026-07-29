# -*- coding: utf-8 -*-
"""Tests for the rewritten Breakout Guard.

Covers the five behaviours that were asked for:
  1. levels come from DAILY candles
  2. every alert is captioned (guard vs CVD monitor)
  3. every alert attributes the move to whales / retail, and events are
     logged to their own file
  4. decisions happen only on a CLOSED H4 candle
  5. spring = wick rejection; reclaim = within 5 H4 candles, with the
     reclaimer identified

Runs without pytest and without network:
    python tests/test_breakout_guard.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import breakout_guard as bg      # noqa: E402
import breakout_log as blog      # noqa: E402
import cvd                       # noqa: E402
import signals as sig            # noqa: E402

H4 = bg.H4
failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def candle(ts, o, h, low, c, v=1000.0):
    return {"ts": ts, "o": o, "h": h, "l": low, "c": c, "v": v}


def swap(side, sol, ts, wallet):
    return (side, sol, ts, wallet)


class Harness:
    """Redirects every file + network touch point to memory/tmp."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = {}
        self.sent = []
        self.candles_h4 = []
        self.daily = None
        self.swaps = []
        self.now = None          # simulated wall clock

    def __enter__(self):
        self.saved = {
            "LOG_PATH": blog.LOG_PATH,
            "LEVELS_PATH": bg.LEVELS_PATH,
            "send": bg.send_telegram,
            "closed": bg.closed_h4_candles,
            "levels": bg.compute_levels,
            "diag": bg.diagnose_breakout,
            "swaps_between": cvd.swaps_between,
            "signals": sig.SIGNALS_PATH,
        }
        blog.LOG_PATH = os.path.join(self.tmp, "breakouts.json")
        bg.LEVELS_PATH = os.path.join(self.tmp, "levels.json")
        bg.send_telegram = self._send
        bg.closed_h4_candles = lambda pool, limit=60, now=None: \
            [c for c in self.candles_h4
             if c["ts"] + H4 <= (now if now is not None else self.clock())]
        bg.compute_levels = lambda pool: self.daily
        bg.diagnose_breakout = lambda ca, **kw: None
        cvd.swaps_between = self._swaps_between
        # the guard also mirrors events into signals.json — keep the real
        # one untouched
        sig.SIGNALS_PATH = os.path.join(self.tmp, "signals.json")
        return self

    def __exit__(self, *a):
        blog.LOG_PATH = self.saved["LOG_PATH"]
        bg.LEVELS_PATH = self.saved["LEVELS_PATH"]
        bg.send_telegram = self.saved["send"]
        bg.closed_h4_candles = self.saved["closed"]
        bg.compute_levels = self.saved["levels"]
        bg.diagnose_breakout = self.saved["diag"]
        cvd.swaps_between = self.saved["swaps_between"]
        sig.SIGNALS_PATH = self.saved["signals"]

    def clock(self):
        """Simulated 'now': just after the newest candle closed."""
        if self.now is not None:
            return self.now
        if self.candles_h4:
            return max(c["ts"] for c in self.candles_h4) + H4 + 60
        return time.time()

    def run(self, ca, symbol="TEST", pool="pool", price=100.0):
        """run_guard on the simulated clock."""
        return bg.run_guard(ca, symbol, pool, price, now=self.clock())

    def _send(self, text):
        self.sent.append(text)
        return True

    def _swaps_between(self, ca, t0, t1):
        return [s for s in self.swaps if t0 <= s[2] < t1]


# ---------------------------------------------------------------------------
def test_daily_levels():
    print("\n[1] levels come from DAILY candles")
    day = 86400
    base = 1_700_000_000 // day * day
    # a clean double top at 120 and a double bottom at 80
    # A pivot needs `left` bars before and `right` bars after it, so the
    # tops/bottoms are placed at interior indices. 120 and 119 would be
    # merged (0.8% apart) — that IS the intended behaviour — so the second
    # top sits well clear of the first.
    #        idx:  0    1    2     3    4    5     6    7    8    9
    seq = [(100, 105, 95), (100, 106, 94), (100, 120, 96), (100, 108, 93),
           (100, 104, 80), (100, 106, 92), (100, 140, 91), (100, 107, 93),
           (100, 103, 90), (100, 102, 91)]
    cands = [candle(base + i * day, o, h, low, 100)
             for i, (o, h, low) in enumerate(seq)]
    saved = cvd.fetch_candles
    cvd.fetch_candles = lambda pool, **kw: cands
    try:
        lv = cvd.daily_levels("pool")
    finally:
        cvd.fetch_candles = saved
    check(lv is not None, "daily_levels returns a result")
    check(any(abs(h - 120) < 1e-9 for h in lv["highs"]),
          f"found the 120 daily resistance: {lv['highs']}")
    check(any(abs(x - 80) < 1e-9 for x in lv["lows"]),
          f"found the 80 daily support: {lv['lows']}")
    check(all(h > lv["price"] for h in lv["highs"]),
          "resistances are all above price")
    check(all(x < lv["price"] for x in lv["lows"]),
          "supports are all below price")
    # near-duplicate levels must be merged
    check(len(lv["highs"]) <= bg.MAX_LEVELS and
          len(lv["lows"]) <= bg.MAX_LEVELS, "level count is capped")


def test_only_closed_candles():
    print("\n[4] only CLOSED H4 candles are evaluated")
    now = time.time()
    saved = cvd.fetch_candles
    forming = int(now // H4 * H4)          # current, still forming
    closed = forming - H4
    cvd.fetch_candles = lambda pool, **kw: [
        candle(closed - H4, 100, 101, 99, 100),
        candle(closed, 100, 101, 99, 100),
        candle(forming, 100, 130, 99, 130),      # would look like a breakout
    ]
    try:
        got = bg.closed_h4_candles("pool", now=now)
    finally:
        cvd.fetch_candles = saved
    check(all(c["ts"] + H4 <= now for c in got),
          "the forming candle is excluded")
    check(forming not in [c["ts"] for c in got],
          "the 130-high forming candle cannot trigger anything")
    check(len(got) == 2, f"both closed candles kept ({len(got)})")


def test_classify():
    print("\n[5] classification: breakout / spring / failed / breakdown")
    highs, lows = [120.0], [80.0]
    t = 1_700_000_000

    # closed above resistance, previous candle below -> breakout
    ev = bg.classify_candle(candle(t, 110, 126, 109, 125), 110, highs, lows)
    check(("breakout", 120.0) in ev, f"close above 120 = breakout ({ev})")

    # poked above but closed back below with a big wick -> failed breakout
    ev = bg.classify_candle(candle(t, 110, 126, 109, 111), 110, highs, lows)
    check(("failed_breakout", 120.0) in ev,
          f"wick above 120, close below = failed breakout ({ev})")

    # poked below support, closed back above with a big lower wick -> spring
    ev = bg.classify_candle(candle(t, 90, 92, 74, 89), 90, highs, lows)
    check(("spring", 80.0) in ev,
          f"wick below 80, close above = spring ({ev})")

    # closed below support -> breakdown
    ev = bg.classify_candle(candle(t, 90, 92, 74, 78), 90, highs, lows)
    check(("breakdown", 80.0) in ev, f"close below 80 = breakdown ({ev})")
    check(("spring", 80.0) not in ev, "a real breakdown is not also a spring")

    # barely grazing the level must NOT fire
    graze = 120.0 * (1 + bg.MIN_PENETRATION / 3)
    ev = bg.classify_candle(candle(t, 119, graze, 118, graze), 119,
                            highs, lows)
    check(ev == [], f"sub-threshold graze is ignored ({ev})")

    # no previous close -> cannot claim a NEW crossing
    ev = bg.classify_candle(candle(t, 110, 126, 109, 125), None, highs, lows)
    check(("breakout", 120.0) not in ev,
          "without a previous close, no breakout is claimed")

    # already above the level (prev close above) -> not a new breakout
    ev = bg.classify_candle(candle(t, 125, 130, 124, 129), 125, highs, lows)
    check(("breakout", 120.0) not in ev,
          "staying above the level does not re-fire")


def test_flow_attribution():
    print("\n[3] flow attribution names who bought and who sold")
    t = 1_700_000_000
    # whales dumping into retail buying
    swaps = [swap("sell", 40, t, "W1"), swap("sell", 25, t + 5, "W2")]
    swaps += [swap("buy", 1.0, t + 10 + i, f"R{i}") for i in range(20)]
    f = cvd.flow_report(swaps)
    check(f["whale_net"] < 0 and f["retail_net"] > 0,
          f"whales negative, retail positive ({f['whale_net']:+.1f} / "
          f"{f['retail_net']:+.1f})")
    check(f["n_whale_sellers"] == 2,
          f"2 whale sellers ({f['n_whale_sellers']})")
    check(f["n_retail_buyers"] == 20,
          f"20 retail buyers ({f['n_retail_buyers']})")
    check("whale selling" in f["actor"], f"dominant actor named: {f['actor']}")
    warn = cvd.flow_warning(f, "up")
    check("CAREFUL" in warn, f"upside warning flags distribution: {warn[:60]}")
    desc = cvd.describe_flow(f)
    check("whales" in desc and "retail" in desc,
          "description mentions both cohorts")

    empty = cvd.flow_report([])
    check(empty["n"] == 0 and "no flow data" in cvd.flow_warning(empty, "up"),
          "empty flow degrades gracefully")
    check("no on-chain swaps" in cvd.describe_flow(empty),
          "empty flow description says so plainly")


def test_end_to_end_breakdown_then_reclaim():
    print("\n[5] breakdown -> reclaim within 5 candles, reclaimer identified")
    with Harness() as h:
        base = 1_700_000_000 // H4 * H4
        ts = [base + i * H4 for i in range(5)]
        h.daily = {"highs": [120.0], "lows": [80.0], "price": 100.0}

        # candle 0/1: baseline above support
        h.candles_h4 = [candle(ts[0], 90, 92, 88, 90),
                        candle(ts[1], 90, 92, 88, 90)]
        h.run("CA1", price=90)     # baseline run
        check(blog.load_events() == [], "first run logs nothing (baseline)")

        # candle 2: closes below 80 -> breakdown, whales selling
        h.candles_h4.append(candle(ts[2], 88, 89, 76, 77))
        h.swaps = [swap("sell", 30, ts[2] + 60, "W1"),
                   swap("sell", 20, ts[2] + 120, "W2"),
                   swap("buy", 0.5, ts[2] + 180, "R1")]
        sent = h.run("CA1", price=77)
        evs = blog.load_events()
        check(any(e["event"] == "breakdown" for e in evs),
              f"breakdown logged ({[e['event'] for e in evs]})")
        check(len(sent) == 1 and sent[0][0] == "breakdown",
              f"breakdown alert sent ({sent})")
        msg = h.sent[-1]
        check("BREAKOUT GUARD" in msg, "guard caption present")
        check("WHO WAS BEHIND THIS CANDLE" in msg, "flow block present")
        check("whales" in msg and "retail" in msg,
              "alert names whales and retail")
        bd = [e for e in evs if e["event"] == "breakdown"][0]
        check(bd["flow"]["whale_net"] < 0,
              "logged flow shows whales selling the breakdown")
        check(bd["levels_tf"] == "D1", "event records D1 as the level source")

        # candle 3: closes back above 80 -> reclaim, whales buying
        h.candles_h4.append(candle(ts[3], 78, 86, 77, 85))
        h.swaps = [swap("buy", 25, ts[3] + 60, "W3"),
                   swap("buy", 15, ts[3] + 90, "W4"),
                   swap("sell", 0.4, ts[3] + 120, "R2")]
        sent = h.run("CA1", price=85)
        check(any(s[0] == "reclaim" for s in sent),
              f"reclaim alert sent ({sent})")
        rec = [e for e in blog.load_events() if e["event"] == "reclaim"][0]
        check("WHALE RECLAIM" in rec["verdict"],
              f"reclaimer identified as whales ({rec['verdict']})")
        check(rec["parent_id"] == bd["id"],
              "reclaim links back to the breakdown it resolves")
        bd2 = [e for e in blog.load_events() if e["id"] == bd["id"]][0]
        check(bd2["outcome"] == "reclaimed",
              f"breakdown outcome closed out ({bd2['outcome']})")


def test_reclaim_window_expires():
    print("\n[5] a reclaim after >5 H4 candles is NOT a reclaim")
    with Harness() as h:
        base = 1_700_000_000 // H4 * H4
        ts = [base + i * H4 for i in range(9)]
        h.daily = {"highs": [120.0], "lows": [80.0], "price": 100.0}
        h.candles_h4 = [candle(ts[0], 90, 92, 88, 90),
                        candle(ts[1], 90, 92, 88, 90)]
        h.run("CA2", price=90)

        h.candles_h4.append(candle(ts[2], 88, 89, 76, 77))
        h.swaps = [swap("sell", 30, ts[2] + 60, "W1")]
        h.run("CA2", price=77)

        # drift below support for 5 candles, then close back above
        for i in (3, 4, 5, 6, 7):
            h.candles_h4.append(candle(ts[i], 77, 78, 75, 76))
        h.swaps = []
        h.run("CA2", price=76)
        h.candles_h4.append(candle(ts[8], 76, 86, 75, 85))
        h.swaps = [swap("buy", 20, ts[8] + 60, "W9")]
        h.run("CA2", price=85)

        evs = blog.load_events()
        check(not any(e["event"] == "reclaim" for e in evs),
              f"no late reclaim ({[e['event'] for e in evs]})")
        bd = [e for e in evs if e["event"] == "breakdown"][0]
        check(bd["outcome"] == "no_reclaim",
              f"breakdown expired as no_reclaim ({bd['outcome']})")


def test_spring_alert():
    print("\n[5] spring: wick below support, closed back above")
    with Harness() as h:
        base = 1_700_000_000 // H4 * H4
        ts = [base + i * H4 for i in range(3)]
        h.daily = {"highs": [120.0], "lows": [80.0], "price": 100.0}
        h.candles_h4 = [candle(ts[0], 90, 92, 88, 90),
                        candle(ts[1], 90, 92, 88, 90)]
        h.run("CA3", price=90)

        # long lower wick to 74, closes back at 88 — whales absorbed it
        h.candles_h4.append(candle(ts[2], 88, 90, 74, 88))
        h.swaps = [swap("buy", 22, ts[2] + 30, "W1"),
                   swap("buy", 18, ts[2] + 60, "W2"),
                   swap("sell", 0.8, ts[2] + 90, "R1")]
        sent = h.run("CA3", price=88)
        check(any(s[0] == "spring" for s in sent), f"spring alerted ({sent})")
        ev = [e for e in blog.load_events() if e["event"] == "spring"][0]
        check("SPRING" in ev["verdict"].upper(),
              f"verdict is a spring read ({ev['verdict']})")
        check(ev["flow"]["whale_net"] > 0,
              "spring flow shows whales buying the wick")
        check("SPRING" in h.sent[-1], "message titles it as a spring")


def test_idempotent_and_dedupe():
    print("\n[misc] re-running the same candles does not double-alert")
    with Harness() as h:
        base = 1_700_000_000 // H4 * H4
        ts = [base + i * H4 for i in range(3)]
        h.daily = {"highs": [120.0], "lows": [80.0], "price": 100.0}
        h.candles_h4 = [candle(ts[0], 110, 112, 108, 110),
                        candle(ts[1], 110, 112, 108, 110)]
        h.run("CA4", price=110)
        h.candles_h4.append(candle(ts[2], 112, 126, 111, 125))
        h.swaps = [swap("buy", 30, ts[2] + 60, "W1")]
        first = h.run("CA4", price=125)
        before = len(h.sent)
        again = h.run("CA4", price=125)
        check(len(first) == 1, f"breakout alerted once ({first})")
        check(again == [] and len(h.sent) == before,
              "second run over the same candle sends nothing")
        ids = [e["id"] for e in blog.load_events()]
        check(len(ids) == len(set(ids)), "no duplicate event ids")


def test_breakout_then_failed():
    print("\n[5] breakout that closes back below = failed breakout, linked")
    with Harness() as h:
        base = 1_700_000_000 // H4 * H4
        ts = [base + i * H4 for i in range(4)]
        h.daily = {"highs": [120.0], "lows": [80.0], "price": 100.0}
        h.candles_h4 = [candle(ts[0], 110, 112, 108, 110),
                        candle(ts[1], 110, 112, 108, 110)]
        h.run("CA6", price=110)

        # breakout on whale buying
        h.candles_h4.append(candle(ts[2], 112, 128, 111, 126))
        h.swaps = [swap("buy", 30, ts[2] + 60, "W1")]
        h.run("CA6", price=126)
        bo = [e for e in blog.load_events() if e["event"] == "breakout"][0]

        # next candle closes back under the level -> failed breakout
        h.candles_h4.append(candle(ts[3], 125, 126, 112, 114))
        h.swaps = [swap("sell", 26, ts[3] + 60, "W2")]
        sent = h.run("CA6", price=114)
        check(any(s[0] == "failed_breakout" for s in sent),
              f"failed breakout alerted ({sent})")
        fb = [e for e in blog.load_events()
              if e["event"] == "failed_breakout"][0]
        check(fb["parent_id"] == bo["id"],
              "failed breakout links back to the breakout")
        parent = [e for e in blog.load_events() if e["id"] == bo["id"]][0]
        check(parent["outcome"] == "failed",
              f"breakout outcome closed as failed ({parent['outcome']})")
        check("whales" in h.sent[-1], "failure alert still names the flow")


def test_spring_not_duplicated_with_reclaim():
    print("\n[5] a reclaim candle is not ALSO reported as a spring")
    with Harness() as h:
        base = 1_700_000_000 // H4 * H4
        ts = [base + i * H4 for i in range(4)]
        h.daily = {"highs": [120.0], "lows": [80.0], "price": 100.0}
        h.candles_h4 = [candle(ts[0], 90, 92, 88, 90),
                        candle(ts[1], 90, 92, 88, 90)]
        h.run("CA7", price=90)
        h.candles_h4.append(candle(ts[2], 88, 89, 76, 77))
        h.swaps = [swap("sell", 30, ts[2] + 60, "W1")]
        h.run("CA7", price=77)
        # wicks below 80 but closes back above -> reclaim, not spring
        h.candles_h4.append(candle(ts[3], 78, 88, 74, 87))
        h.swaps = [swap("buy", 25, ts[3] + 60, "W2")]
        sent = h.run("CA7", price=87)
        kinds = [s[0] for s in sent]
        check("reclaim" in kinds, f"reclaim reported ({kinds})")
        check("spring" not in kinds,
              f"the same candle is not also a spring ({kinds})")


def test_migration_from_old_state():
    print("\n[misc] an existing levels.json (old H1 format) migrates safely")
    import json
    with Harness() as h:
        base = 1_700_000_000 // H4 * H4
        ts = [base + i * H4 for i in range(3)]
        # old-format entry: H1 levels, no last_h4_ts, no pending
        old = {"CA8": {"levels": {"highs": [111.0], "lows": [99.0]},
                       "alerted": {"up:111": base}, "last_price": 100.0}}
        with open(bg.LEVELS_PATH, "w") as f:
            json.dump(old, f)
        h.daily = {"highs": [120.0], "lows": [80.0], "price": 100.0}
        h.candles_h4 = [candle(ts[0], 112, 126, 111, 125),
                        candle(ts[1], 125, 128, 124, 127)]
        sent = h.run("CA8", price=127)
        check(sent == [], "no alert fired from pre-existing history")
        st = json.load(open(bg.LEVELS_PATH))["CA8"]
        check(st["levels"]["highs"] == [120.0],
              f"H1 levels replaced by D1 ({st['levels']['highs']})")
        check(st["levels"].get("tf") == "D1", "levels tagged as D1")
        check(st.get("last_h4_ts") == ts[1], "H4 baseline recorded")
        check("pending" in st, "pending watch-list initialised")


def test_captions_distinct():
    print("\n[2] the two message types are captioned differently")
    import signals
    check(bg.GUARD_TAG != signals.CVD_TAG, "tags differ")
    check("BREAKOUT GUARD" in bg.GUARD_TAG, f"guard tag: {bg.GUARD_TAG}")
    check("CVD MONITOR" in signals.CVD_TAG, f"cvd tag: {signals.CVD_TAG}")
    msg = bg.build_message(
        event="breakout", symbol="X", ca="CA", level=100.0,
        candle=candle(1_700_000_000, 99, 106, 98, 105),
        flow=cvd.flow_report([swap("buy", 20, 1_700_000_001, "W1")]),
        verdict="REAL MARKUP", emoji="🟢", why="test",
        highs=[120.0], lows=[80.0])
    check(msg.startswith(bg.GUARD_TAG), "guard message starts with its tag")
    check("D1 levels" in msg and "H4 close" in msg,
          "guard subtitle states the timeframes")


def test_pending_retry():
    print("\n[misc] a failed Telegram send is retried, not lost")
    with Harness() as h:
        base = 1_700_000_000 // H4 * H4
        ts = [base + i * H4 for i in range(3)]
        h.daily = {"highs": [120.0], "lows": [80.0], "price": 100.0}
        h.candles_h4 = [candle(ts[0], 110, 112, 108, 110),
                        candle(ts[1], 110, 112, 108, 110)]
        h.run("CA5", price=110)

        bg.send_telegram = lambda text: False        # Telegram is down
        h.candles_h4.append(candle(ts[2], 112, 126, 111, 125))
        h.swaps = [swap("buy", 30, ts[2] + 60, "W1")]
        sent = h.run("CA5", price=125)
        check(sent == [], "nothing reported as sent while Telegram is down")
        pend = blog.pending_alerts(now=h.clock())
        check(len(pend) == 1 and pend[0]["msg"],
              f"the alert is queued for retry ({len(pend)})")

        bg.send_telegram = h._send                   # Telegram is back
        n = bg.flush_pending_alerts(now=h.clock())
        check(n == 1, f"queued alert re-sent ({n})")
        check(blog.pending_alerts(now=h.clock()) == [], "queue drained")
        check("BREAKOUT GUARD" in h.sent[-1], "retried message intact")


if __name__ == "__main__":
    test_daily_levels()
    test_only_closed_candles()
    test_classify()
    test_flow_attribution()
    test_end_to_end_breakdown_then_reclaim()
    test_reclaim_window_expires()
    test_spring_alert()
    test_breakout_then_failed()
    test_spring_not_duplicated_with_reclaim()
    test_idempotent_and_dedupe()
    test_captions_distinct()
    test_migration_from_old_state()
    test_pending_retry()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for f in failures:
        print("  -", f)
    sys.exit(1 if failures else 0)
