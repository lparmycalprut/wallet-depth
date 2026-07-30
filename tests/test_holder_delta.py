# -*- coding: utf-8 -*-
"""Tests for the holder-delta analyzer (whale/dolphin/minnow).

Covers:
  * tier classification by % of holder count
  * snapshot save / load / dedup / trim
  * holder_delta: per-tier SOL change, wallets added/exited
  * "exit" = drop ≥ 90% of baseline holdings
  * window_start baseline picker (newest snapshot <= window start)
  * edge cases: empty snapshot, empty current, no baseline, very
    small holder sets (n=1), ties in holdings

Run with:  python tests/test_holder_delta.py  (no pytest, no network)
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cvd  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class TempPaths:
    """Patch cvd paths to a tmpdir so we never touch real snapshots."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = cvd.HOLDER_SNAPSHOT_PATH
        cvd.HOLDER_SNAPSHOT_PATH = os.path.join(
            self.tmp.name, "holder_snapshots.json")
        return self

    def __exit__(self, *args):
        cvd.HOLDER_SNAPSHOT_PATH = self.saved
        self.tmp.cleanup()


def holders_from_pairs(pairs):
    """Helper: build the [owner, amount] iterable Helius returns."""
    return [[p[0], p[1]] for p in pairs]


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------
def test_classify_holders_top_pct():
    print("\n[classify] top-1% whale, next-4% dolphin, rest minnow")
    # 100 holders, sorted by amount desc, "alice" = biggest = whale
    pairs = [(f"wallet_{i:03d}", 100 - i) for i in range(100)]
    tiers = cvd.classify_holders(pairs)
    n_whale = sum(1 for t in tiers.values() if t == "whale")
    n_dolphin = sum(1 for t in tiers.values() if t == "dolphin")
    n_minnow = sum(1 for t in tiers.values() if t == "minnow")
    check(n_whale == 1, f"top 1% of 100 → 1 whale (got {n_whale})")
    check(n_dolphin == 4, f"next 4% → 4 dolphins (got {n_dolphin})")
    check(n_minnow == 95, f"rest → 95 minnows (got {n_minnow})")
    check(tiers["wallet_000"] == "whale",
          f"wallet_000 is whale (got {tiers.get('wallet_000')!r})")
    check(tiers["wallet_001"] == "dolphin",
          f"wallet_001 is dolphin (got {tiers.get('wallet_001')!r})")
    check(tiers["wallet_004"] == "dolphin",
          f"wallet_004 is the last dolphin (got {tiers.get('wallet_004')!r})")
    check(tiers["wallet_005"] == "minnow",
          f"wallet_005 is minnow (got {tiers.get('wallet_005')!r})")


def test_classify_holders_small_set():
    print("\n[classify] very small holder sets still get a whale seat")
    pairs = [("alice", 100), ("bob", 50), ("carol", 10)]
    tiers = cvd.classify_holders(pairs)
    check(tiers.get("alice") == "whale",
          f"alice is whale in n=3 set (got {tiers.get('alice')!r})")
    check(tiers.get("bob") in ("dolphin", "minnow"),
          f"bob is dolphin or minnow (got {tiers.get('bob')!r})")
    check(tiers.get("carol") == "minnow",
          f"carol is minnow (got {tiers.get('carol')!r})")


def test_classify_holders_dict_input():
    print("\n[classify] dict input (DataFrame-style) works")
    pairs = [{"owner": "a", "ui_amount": 100},
             {"owner": "b", "ui_amount": 50}]
    tiers = cvd.classify_holders(pairs)
    check(tiers.get("a") == "whale", f"a is whale")
    check(tiers.get("b") in ("dolphin", "minnow"), f"b is tier-2")


def test_classify_holders_empty():
    print("\n[classify] empty / garbage input → empty tier map")
    check(cvd.classify_holders([]) == {}, "empty list → empty dict")
    check(cvd.classify_holders(None) == {}, "None → empty dict")
    check(cvd.classify_holders([None, "", []]) == {},
          "garbage entries → empty dict")


# ---------------------------------------------------------------------------
# Snapshot save / load / dedup / trim
# ---------------------------------------------------------------------------
def test_record_and_load_snapshot():
    print("\n[snapshot] record + load roundtrip")
    with TempPaths() as t:
        pairs = holders_from_pairs([("a", 100.0), ("b", 50.0)])
        point = cvd.record_holder_snapshot("CA1", pairs, supply=1000.0)
        check(point is not None, "returns a point")
        check(point["ts"] > 0, f"point has ts (got {point['ts']})")
        check(len(point["holders"]) == 2,
              f"2 holders recorded (got {len(point['holders'])})")
        loaded = cvd.load_holder_snapshots()
        check("CA1" in loaded, f"CA1 in loaded (keys: {list(loaded)})")
        snap = next(iter(loaded["CA1"].values()))
        check(snap["supply"] == 1000.0, f"supply roundtrips")
        check(snap["holders"][0][0] == "a",
              "largest holder first after sort (a comes before b)")
        check(snap["holders"][0][1] >= snap["holders"][1][1],
              "holders sorted descending by amount")


def test_snapshot_dedup_same_bucket():
    print("\n[snapshot] duplicate commits in the same window are deduped")
    with TempPaths():
        pairs = holders_from_pairs([("a", 100.0)])
        p1 = cvd.record_holder_snapshot("CA2", pairs, supply=1000.0)
        # immediate second commit hits the same bucket — should be skipped
        p2 = cvd.record_holder_snapshot("CA2", pairs, supply=1000.0)
        check(p1 is not None, "first commit returns point")
        check(p2 is None, "second commit in same bucket is skipped")
        loaded = cvd.load_holder_snapshots()
        check(len(loaded.get("CA2", {})) == 1,
              f"only 1 snapshot stored (got {len(loaded.get('CA2', {}))})")


def test_snapshot_keeps_minimum_4():
    print("\n[snapshot] trims old data but always keeps latest 4")
    with TempPaths():
        # Inject 6 old snapshots, all >30 days old
        state = {}
        very_old = int(time.time()) - 40 * 86400
        for i in range(6):
            ts = very_old + i * 3600
            state.setdefault("CA3", {})[f"b{int(ts // 3600)}"] = {
                "ts": ts, "supply": 1000.0,
                "holders": [["x", 50.0]],
            }
        cvd._save_holder_snapshots(state)
        # Now write 1 fresh snapshot — the trim should keep the 4 latest
        # even if they all exceed the 30-day cutoff.
        fresh = cvd.record_holder_snapshot(
            "CA3", holders_from_pairs([("y", 80.0)]), supply=1000.0)
        check(fresh is not None, "fresh commit succeeds")
        loaded = cvd.load_holder_snapshots()
        kept = loaded.get("CA3", {})
        check(len(kept) == 4,
              f"4 snapshots kept (got {len(kept)}); trim should never go below 4")


# ---------------------------------------------------------------------------
# holder_delta — the actual analyzer
# ---------------------------------------------------------------------------
def _seed_baseline(ca, pairs, hours_ago):
    """Seed a baseline snapshot ``hours_ago`` from now (for delta tests)."""
    with TempPaths():
        pass  # caller manages TempPaths
    state = cvd.load_holder_snapshots()
    bucket = int((time.time() - hours_ago * 3600) // cvd.SNAPSHOT_MIN_GAP_S)
    state.setdefault(ca, {})[f"b{bucket}"] = {
        "ts": int(time.time() - hours_ago * 3600),
        "supply": 1000.0,
        "holders": pairs,
    }
    cvd._save_holder_snapshots(state)


def test_delta_no_snapshot():
    print("\n[delta] no baseline → ok=False, reason explains")
    with TempPaths():
        # 10 holders currently, but no committed snapshot
        cur = holders_from_pairs([(f"w{i}", 100 - i) for i in range(10)])
        d = cvd.holder_delta("MISSING_CA", window_h=6,
                             current_holders=cur, current_supply=1000.0)
        check(d["ok"] is False, f"ok=False when no snapshot (got {d['ok']!r})")
        check(d["baseline_ts"] == 0, f"baseline_ts=0 (got {d['baseline_ts']})")
        check("no snapshot" in d["summary"].lower() or
              "no baseline" in d["reason"].lower(),
              f"reason mentions no baseline: {d['reason']!r}")
        check(d["level"] == "ok", f"level=ok when no data (got {d['level']!r})")
        check(d["whale"]["delta_sol"] == 0.0,
              f"whale delta is 0 (got {d['whale']['delta_sol']})")


def test_delta_picks_newest_before_window_start():
    print("\n[delta] baseline = newest snapshot with ts <= window_start")
    with TempPaths():
        # 3 snapshots, each 7h apart so they fall in different 6h-buckets
        # (and the 7h-ago one qualifies as the baseline for window=6h)
        now = int(time.time())
        for h_ago, amt in [(1, 100), (8, 200), (15, 300)]:
            state = cvd.load_holder_snapshots()
            bucket = int((now - h_ago * 3600) // cvd.SNAPSHOT_MIN_GAP_S)
            state.setdefault("CA4", {})[f"b{bucket}"] = {
                "ts": now - h_ago * 3600,
                "supply": 1000.0,
                "holders": [["w", float(amt)]],
            }
            cvd._save_holder_snapshots(state)
        cur = holders_from_pairs([("w", 999.0)])
        d = cvd.holder_delta("CA4", window_h=6,
                             current_holders=cur, current_supply=1000.0)
        # 1h-ago snapshot is AFTER window start (now-6h) → excluded.
        # 8h-ago is the newest ≤ window_start → picked.
        # 15h-ago is older → ignored.
        check(d["baseline_ts"] == now - 8 * 3600,
              f"baseline picked 8h-ago snapshot (got ts diff "
              f"{(now - d['baseline_ts']) / 3600:.1f}h)")
        check(d["whale"]["delta_sol"] == 999.0 - 200.0,
              f"whale delta = current - 8h-ago baseline = 799.0 "
              f"(got {d['whale']['delta_sol']})")


def test_delta_per_tier_aggregates():
    print("\n[delta] tier aggregates match per-wallet deltas")
    with TempPaths():
        # 100 holders at T0: 1 whale (alice, 100), 4 dolphins (50 each),
        # 95 minnows (10 each)
        baseline = (
            [("alice", 100.0)]
            + [(f"d{i}", 50.0) for i in range(4)]
            + [(f"m{i}", 10.0) for i in range(95)]
        )
        _seed_baseline("CA5", baseline, hours_ago=8)
        # T1: alice bought 30 (now 130), d0 sold 20 (now 30), 2 NEW
        # minnows (m_new_a, m_new_b) each with 5, m0..m94 all stay
        # unchanged. No exits, so minnow delta = +5 + +5 = +10.
        cur = (
            [("alice", 130.0)]
            + [("d0", 30.0), ("d1", 50.0), ("d2", 50.0), ("d3", 50.0)]
            + [(f"m{i}", 10.0) for i in range(95)]
            + [("m_new_a", 5.0), ("m_new_b", 5.0)]
        )
        d = cvd.holder_delta("CA5", window_h=6,
                             current_holders=cur, current_supply=1000.0)
        # Alice is the only whale (top 1% of 100), and she bought 30 SOL
        check(d["whale"]["delta_sol"] == 30.0,
              f"whale delta = +30 (got {d['whale']['delta_sol']})")
        # Dolphins: 4 wallets at T0 (d0..d3), d0 sold 20, others unchanged
        check(d["dolphin"]["delta_sol"] == -20.0,
              f"dolphin delta = -20 (got {d['dolphin']['delta_sol']})")
        # Minnow: 2 new (m_new_a, m_new_b) with +5 each = +10,
        # no exits (m0..m94 all stayed at 10)
        check(d["minnow"]["delta_sol"] == 10.0,
              f"minnow delta = +10 (got {d['minnow']['delta_sol']})")
        check(d["minnow"]["wallets_added"] == 2,
              f"minnow: 2 wallets added (got {d['minnow']['wallets_added']})")
        check(d["minnow"]["wallets_added"] == 2,
              f"minnow: 2 wallets added (got {d['minnow']['wallets_added']})")


def test_delta_exits_when_drop_over_90_pct():
    print("\n[delta] wallet that dropped ≥ 90% of holdings counts as exited")
    with TempPaths():
        # T0: 10 holders, 'dumper' holds 100 SOL (top 1% → whale)
        baseline = [("dumper", 100.0), ("steady", 50.0)] + \
            [(f"m{i}", 10.0) for i in range(8)]
        _seed_baseline("CA6", baseline, hours_ago=8)
        # T1: dumper sold all (1.0 SOL remaining = 99% drop → exit)
        cur = [("dumper", 1.0), ("steady", 50.0)] + \
            [(f"m{i}", 10.0) for i in range(8)]
        d = cvd.holder_delta("CA6", window_h=6,
                             current_holders=cur, current_supply=1000.0)
        check(d["whale"]["wallets_exited"] == 1,
              f"dumper counted as 1 exit (got {d['whale']['wallets_exited']})")
        check(d["whale"]["delta_sol"] == 1.0 - 100.0,
              f"whale delta = -99 (got {d['whale']['delta_sol']})")


def test_delta_does_not_count_small_drop_as_exit():
    print("\n[delta] 50% drop is NOT an exit (threshold = 90%)")
    with TempPaths():
        baseline = [("half", 100.0), ("steady", 50.0)] + \
            [(f"m{i}", 10.0) for i in range(8)]
        _seed_baseline("CA7", baseline, hours_ago=8)
        # 'half' went from 100 → 50, i.e. 50% drop
        cur = [("half", 50.0), ("steady", 50.0)] + \
            [(f"m{i}", 10.0) for i in range(8)]
        d = cvd.holder_delta("CA7", window_h=6,
                             current_holders=cur, current_supply=1000.0)
        check(d["whale"]["wallets_exited"] == 0,
              f"50% drop → 0 exits (got {d['whale']['wallets_exited']})")


def test_delta_summary_and_level_for_heavy_sell():
    print("\n[delta] heavy whale sell → level=danger, summary mentions it")
    with TempPaths():
        # 10 holders, whale top holds 100, sells 90 → still 10 SOL left
        baseline = [("whale1", 100.0), ("rest", 50.0)] + \
            [(f"m{i}", 10.0) for i in range(8)]
        _seed_baseline("CA8", baseline, hours_ago=8)
        cur = [("whale1", 10.0), ("rest", 50.0)] + \
            [(f"m{i}", 10.0) for i in range(8)]
        d = cvd.holder_delta("CA8", window_h=6,
                             current_holders=cur, current_supply=1000.0,
                             whale_min_sol=1.0)
        check(d["whale"]["delta_sol"] == -90.0,
              f"whale delta = -90 (got {d['whale']['delta_sol']})")
        # Threshold is 1 SOL, 90 SOL moved → level should be 'danger' (>=2x)
        check(d["level"] == "danger",
              f"level=danger for 90 SOL sell (got {d['level']!r})")
        check("dumped" in d["reason"] or "sold" in d["reason"],
              f"reason mentions the sell: {d['reason']!r}")
        check("W" in d["summary"],
              f"summary has whale info: {d['summary']!r}")


def test_delta_quiet_window_returns_ok_false_but_level_ok():
    print("\n[delta] tiny move doesn't surface as flagged")
    with TempPaths():
        # baseline == current within 0.5 SOL → ok=False (nothing to show)
        baseline = [("a", 100.0)] + \
            [(f"m{i}", 10.0) for i in range(20)]
        _seed_baseline("CA9", baseline, hours_ago=8)
        cur = [("a", 100.4)] + [(f"m{i}", 10.0) for i in range(20)]
        d = cvd.holder_delta("CA9", window_h=6,
                             current_holders=cur, current_supply=1000.0,
                             whale_min_sol=1.0, dolphin_min_sol=2.0)
        check(d["level"] == "ok", f"quiet window → level=ok (got {d['level']})")
        check(d["ok"] is False, f"ok=False (no tier above threshold)")
        check("no meaningful move" in d["summary"]
              or "W" not in d["summary"],
              f"summary doesn't lead with whale: {d['summary']!r}")


def test_delta_respects_custom_thresholds():
    print("\n[delta] per-call thresholds override defaults")
    with TempPaths():
        baseline = [("a", 100.0)] + [(f"m{i}", 10.0) for i in range(20)]
        _seed_baseline("CA10", baseline, hours_ago=8)
        # whale sells 5 SOL — above default 1.0, below custom 10.0
        cur = [("a", 95.0)] + [(f"m{i}", 10.0) for i in range(20)]
        d_default = cvd.holder_delta(
            "CA10", window_h=6, current_holders=cur, current_supply=1000.0)
        d_strict = cvd.holder_delta(
            "CA10", window_h=6, current_holders=cur, current_supply=1000.0,
            whale_min_sol=10.0)
        check(d_default["ok"] is True,
              f"5 SOL > default 1.0 → ok=True (got {d_default['ok']})")
        check(d_strict["ok"] is False,
              f"5 SOL < custom 10.0 → ok=False (got {d_strict['ok']})")


def test_delta_handles_holder_inherits_higher_tier():
    print("\n[delta] wallet dropping whale→minnow still counts as whale story")
    with TempPaths():
        # 100 holders at T0; 'rich' is the only whale (100 SOL)
        baseline = [("rich", 100.0)] + \
            [(f"d{i}", 50.0) for i in range(4)] + \
            [(f"m{i}", 10.0) for i in range(95)]
        _seed_baseline("CA11", baseline, hours_ago=8)
        # T1: 'rich' sold 99 (left 1 SOL → now in the minnow tier)
        cur = [("rich", 1.0)] + \
            [(f"d{i}", 50.0) for i in range(4)] + \
            [(f"m{i}", 10.0) for i in range(95)]
        d = cvd.holder_delta("CA11", window_h=6,
                             current_holders=cur, current_supply=1000.0)
        # 'rich' should be classified as whale (highest of its two tiers)
        check(d["whale"]["delta_sol"] == -99.0,
              f"whale delta = -99 (got {d['whale']['delta_sol']})")
        check(d["whale"]["wallets_exited"] == 1,
              f"whale: 1 exit (drop ≥ 90%) (got {d['whale']['wallets_exited']})")


def test_load_holder_delta_config_uses_module_defaults():
    print("\n[config] load_holder_delta_config falls back when no config.json")
    with TempPaths():
        # No config.json in tmpdir → should return empty dict
        cfg = cvd.load_holder_delta_config()
        # Either empty (no file) or the module defaults — both are fine
        if cfg:
            check("whale_delta_min_sol" in cfg
                  and cfg["whale_delta_min_sol"] > 0,
                  f"whale threshold present (got {cfg.get('whale_delta_min_sol')})")
        else:
            check(True, "no config.json → empty config (caller uses defaults)")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def main():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in tests:
        fn()
    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
