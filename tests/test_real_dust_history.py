# -*- coding: utf-8 -*-
"""Tests for the hourly real-vs-dust holder history.

Covers:
  * record / dedup (REAL_DUST_MIN_GAP_S) / trim (retention + hard cap)
  * chronological series normalization (tolerates missing fields)
  * real_dust_trend: direction (up/down/flat), 1h/4h/24h deltas,
    ratio now vs previous, anchor picking past cron gaps
  * edge cases: empty series, single point, nonsense counts rejected,
    dust=0 ratio (None = "∞")

Run with:  python tests/test_real_dust_history.py  (no pytest, no network)
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cvd  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class TempPath:
    """Patch cvd.REAL_DUST_PATH to a tmpdir so we never touch real data."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = cvd.REAL_DUST_PATH
        cvd.REAL_DUST_PATH = os.path.join(self.tmp.name,
                                          "real_dust_history.json")
        return self

    def __exit__(self, *args):
        cvd.REAL_DUST_PATH = self.saved
        self.tmp.cleanup()


T0 = 1_760_000_000  # fixed base ts so tests are deterministic


# ---------------------------------------------------------------------------
# Recording: basic append, fields, rejection of nonsense
# ---------------------------------------------------------------------------
def test_record_basic_point():
    print("\n[record] appends a point with all fields")
    with TempPath():
        pt = cvd.record_real_dust_point("CA_A", 120, 480, price=0.002,
                                        dust_limit=5.0, ts=T0)
        check(pt is not None, "first point recorded")
        check(pt["real"] == 120 and pt["dust"] == 480,
              f"counts stored (got {pt})")
        check(pt["ts"] == T0, "ts stored")
        check(abs(pt["price"] - 0.002) < 1e-12, "price stored")
        state = cvd.load_real_dust_history()
        check("CA_A" in state, "CA present in state file")
        check(len(state["CA_A"]) == 1, "exactly one point in file")


def test_record_rejects_nonsense():
    print("\n[record] rejects empty / negative counts")
    with TempPath():
        check(cvd.record_real_dust_point("CA_A", 0, 0, ts=T0) is None,
              "0 real + 0 dust rejected (no holders = bad fetch)")
        check(cvd.record_real_dust_point("CA_A", -5, 10, ts=T0) is None,
              "negative count rejected")
        check(not os.path.exists(cvd.REAL_DUST_PATH)
              or not cvd.load_real_dust_history(),
              "nothing written to disk for rejected points")


def test_record_dedup_min_gap():
    print("\n[record] dedup inside REAL_DUST_MIN_GAP_S (cron retry)")
    with TempPath():
        assert cvd.record_real_dust_point("CA_A", 100, 400, ts=T0)
        # 10 minutes later — a retry of the same cron window, must skip
        retry = cvd.record_real_dust_point("CA_A", 101, 399,
                                           ts=T0 + 600)
        check(retry is None, "point 10 min after previous is deduped")
        # 44 min later — still inside the 45-min gap, must skip
        check(cvd.record_real_dust_point("CA_A", 101, 399,
                                         ts=T0 + 44 * 60) is None,
              "point 44 min after previous is deduped")
        # the next hourly run (>= 45 min) must record
        nxt = cvd.record_real_dust_point("CA_A", 101, 399, ts=T0 + 3600)
        check(nxt is not None, "point 60 min after previous is recorded")
        state = cvd.load_real_dust_history()
        check(len(state["CA_A"]) == 2,
              f"exactly 2 points after dedup (got {len(state['CA_A'])})")


def test_record_out_of_order_and_trim():
    print("\n[record] late/stale points deduped; old points trimmed; "
          "series read back sorted")
    with TempPath():
        old = T0 - (cvd.REAL_DUST_KEEP_DAYS + 2) * 86400
        cvd.record_real_dust_point("CA_A", 1, 1, ts=old)         # too old
        cvd.record_real_dust_point("CA_A", 40, 60, ts=T0)        # fresh
        # a late-arriving point BEHIND the newest one is a stale retry —
        # the recorder drops it (dedup compares against the newest ts)
        check(cvd.record_real_dust_point("CA_A", 39, 61,
                                         ts=T0 - 2 * 3600) is None,
              "point older than the newest recorded point is deduped")
        pts = cvd.real_dust_series(cvd.load_real_dust_history(), "CA_A")
        check(len(pts) == 1 and pts[0]["ts"] == T0,
              "stale 32-day-old point trimmed, only the fresh one kept")
        # out-of-order storage (git merge / hand edit) still reads sorted
        state = {"CA_A": [{"ts": T0 + 7200, "real": 3, "dust": 3},
                          {"ts": T0, "real": 1, "dust": 1},
                          {"ts": T0 + 3600, "real": 2, "dust": 2}]}
        with open(cvd.REAL_DUST_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
        pts = cvd.real_dust_series(cvd.load_real_dust_history(), "CA_A")
        check([p["real"] for p in pts] == [1, 2, 3],
              "out-of-order file reads back chronological")


def test_record_hard_cap():
    print("\n[record] hard cap at REAL_DUST_MAX_POINTS")
    with TempPath():
        # 50-minute spacing: inside the 30-day retention (≈27.8 days of
        # span) but above the 45-min dedup gap, so the hard cap is what
        # actually trims.
        n = cvd.REAL_DUST_MAX_POINTS + 56
        base = T0 - n * 3000
        last = None
        for i in range(n):
            last = cvd.record_real_dust_point("CA_A", 10 + (i % 50), 100,
                                              ts=base + i * 3000)
        check(last is not None, "50-min spaced points are recorded")
        pts = cvd.real_dust_series(cvd.load_real_dust_history(), "CA_A")
        check(len(pts) == cvd.REAL_DUST_MAX_POINTS,
              f"capped at {cvd.REAL_DUST_MAX_POINTS} (got {len(pts)})")
        check(pts[-1]["ts"] == base + (n - 1) * 3000,
              "newest points survive the cap")


# ---------------------------------------------------------------------------
# Series normalization
# ---------------------------------------------------------------------------
def test_series_tolerates_missing_fields():
    print("\n[series] points missing optional fields normalize cleanly")
    with TempPath():
        state = {"CA_A": [{"ts": T0, "real": 10, "dust": 5},
                          {"ts": T0 + 3600, "real": 12},          # no dust
                          {"bad": True}]}                          # no ts
        with open(cvd.REAL_DUST_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
        pts = cvd.real_dust_series(cvd.load_real_dust_history(), "CA_A")
        check(len(pts) == 3, f"all points kept (got {len(pts)})")
        check(pts[0]["ts"] == 0 and pts[0]["real"] == 0,
              "broken point normalized to zeros, never crashes")
        check(pts[2]["dust"] == 0, "missing dust defaults to 0")
        check(pts[2]["limit"] == 5.0, "missing limit defaults to $5")
        check(cvd.real_dust_series({}, "CA_NOPE") == [],
              "unknown CA → empty series")


# ---------------------------------------------------------------------------
# Trend: direction + window deltas
# ---------------------------------------------------------------------------
def _hourly(start_i, end_i, real0=100, step_r=1, dust0=400, step_d=-2):
    """Deterministic hourly series from start_i to end_i (hours before T0)."""
    return [{"ts": T0 + i * 3600, "real": real0 + i * step_r,
             "dust": dust0 + i * step_d, "price": 0.001, "limit": 5.0}
            for i in range(start_i, end_i + 1)]


def test_trend_up_down_flat():
    print("\n[trend] direction between the last two cron points")
    up = cvd.real_dust_trend(_hourly(-25, 0))
    check(up["dir_1h"] == "up", "rising series → dir up")
    down = cvd.real_dust_trend(_hourly(-25, 0, step_r=-3, step_d=4))
    check(down["dir_1h"] == "down", "falling series → dir down")
    flat_pts = [{"ts": T0 - 3600, "real": 100, "dust": 400,
                 "price": 0.0, "limit": 5.0},
                {"ts": T0, "real": 100, "dust": 399,
                 "price": 0.0, "limit": 5.0}]
    flat = cvd.real_dust_trend(flat_pts)
    check(flat["dir_1h"] == "flat",
          f"unchanged real count → dir flat (got {flat['dir_1h']})")
    check(flat["d1h"] == (0, -1),
          f"flat real / -1 dust delta (got {flat['d1h']})")


def test_trend_window_deltas():
    print("\n[trend] 1h / 4h / 24h deltas anchor to nearest older point")
    pts = _hourly(-25, 0)                      # 26 hourly points
    tr = cvd.real_dust_trend(pts)
    check(tr["d1h"] == (1, -2), f"d1h vs previous hour (got {tr['d1h']})")
    check(tr["d4h"] == (4, -8), f"d4h vs 4h back (got {tr['d4h']})")
    check(tr["d24h"] == (24, -48), f"d24h vs 24h back (got {tr['d24h']})")
    check(tr["n"] == 26, "n = point count")


def test_trend_young_series_windows_none():
    print("\n[trend] windows beyond coverage return None, never a fake zero")
    pts = _hourly(-2, 0)                       # only 3 hourly points
    tr = cvd.real_dust_trend(pts)
    check(tr["d1h"] is not None, "1h delta available with 2+ points")
    check(tr["d4h"] is None, "4h delta honestly None (series too young)")
    check(tr["d24h"] is None, "24h delta honestly None (series too young)")


def test_trend_gap_in_cron():
    print("\n[trend] anchors fall back to the nearest older point across "
          "a cron gap (same convention as holder_delta)")
    # points hourly until 10h ago, then nothing until now (cron was down)
    pts = _hourly(-25, -10)
    pts.append({"ts": T0, "real": 122, "dust": 350,
                "price": 0.0, "limit": 5.0})
    tr = cvd.real_dust_trend(pts)
    check(tr["d1h"] == (122 - (100 - 10), 350 - (400 + 20)),
          "1h delta falls back to nearest available older point "
          f"(got {tr['d1h']})")
    check(tr["d4h"] == tr["d1h"],
          "4h delta uses the same nearest-older anchor past the gap "
          "(documented convention — never a fabricated anchor)")


def test_trend_ratio_and_edge_cases():
    print("\n[trend] ratio now vs prev; dust=0 → None (∞); empty series")
    pts = [{"ts": T0 - 3600, "real": 100, "dust": 400,
            "price": 0.0, "limit": 5.0},
           {"ts": T0, "real": 120, "dust": 300,
            "price": 0.0, "limit": 5.0}]
    tr = cvd.real_dust_trend(pts)
    check(abs(tr["ratio_now"] - 120 / 300) < 1e-9, "ratio_now = real/dust")
    check(abs(tr["ratio_prev"] - 100 / 400) < 1e-9, "ratio_prev from anchor")
    no_dust = cvd.real_dust_trend(
        [{"ts": T0, "real": 50, "dust": 0, "price": 0.0, "limit": 5.0}])
    check(no_dust["ratio_now"] is None,
          "no dust → ratio None (UI renders ∞, never a ZeroDivision)")
    empty = cvd.real_dust_trend([])
    check(empty["n"] == 0 and empty["cur"] is None
          and empty["dir_1h"] == "flat",
          "empty series → safe empty trend")
    one = cvd.real_dust_trend(
        [{"ts": T0, "real": 5, "dust": 5, "price": 0.0, "limit": 5.0}])
    check(one["d1h"] is None and one["cur"]["real"] == 5,
          "single point → no deltas but current value present")


def test_disk_roundtrip_isolated():
    print("\n[disk] state file is written where REAL_DUST_PATH points")
    with TempPath() as t:
        cvd.record_real_dust_point("CA_A", 7, 3, ts=T0)
        check(os.path.exists(cvd.REAL_DUST_PATH),
              "file created under tmpdir")
        with open(cvd.REAL_DUST_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        check(raw["CA_A"][0]["real"] == 7, "roundtrip keeps values")


if __name__ == "__main__":
    test_record_basic_point()
    test_record_rejects_nonsense()
    test_record_dedup_min_gap()
    test_record_out_of_order_and_trim()
    test_record_hard_cap()
    test_series_tolerates_missing_fields()
    test_trend_up_down_flat()
    test_trend_window_deltas()
    test_trend_young_series_windows_none()
    test_trend_gap_in_cron()
    test_trend_ratio_and_edge_cases()
    test_disk_roundtrip_isolated()
    print()
    if failures:
        print(f"{len(failures)} FAILURES:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("ALL PASSED")
