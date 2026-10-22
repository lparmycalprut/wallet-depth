"""Tes early watcher: logika murni, tanpa jaringan dan tanpa Telegram."""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest

import early_watch as ew

MINT = "5ubruMYpgKqw9ip5J1qrXbVGmMdn2VCsMg421B4bpump"
SOL = "So11111111111111111111111111111111111111112"
CM = "pumpCmTestQuote1111111111111111111111111111"
WALLETS = ["W1", "W2", "W3", "W4"]


def trade(tx, maker, event, quote, price, usd, ts, base=0.0):
    return {"tx_hash": tx, "maker": maker, "event": event, "quote_address": quote,
            "price_usd": str(price), "amount_usd": str(usd), "timestamp": ts,
            "base_amount": str(base)}


def round_trip_trades(tx, maker, ts, spread=0.05, usd=50.0):
    """Satu putaran: beli di pasar CM, jual di pasar SOL, satu tx, selisih `spread`."""
    return [trade(tx, maker, "buy", CM, 1.0, usd, ts),
            trade(tx, maker, "sell", SOL, 1.0 + spread, usd, ts)]


def burst(base, n, wallets, prefix="tx", spread=0.05):
    """n putaran dalam 60 detik dari daftar wallet (round-robin)."""
    out = []
    for i in range(n):
        out += round_trip_trades(f"{prefix}{base}-{i}", wallets[i % len(wallets)],
                                 base + (i * 5) % 55, spread=spread)
    return out


def dump_trade(ts, usd=1430.0, base=6_600_000, maker="D1", tx=None):
    """Satu jual tunggal, seperti COCK 22:42:32 WIB (≈$1,43K, 6,6 juta token)."""
    return trade(tx or f"DUMP{ts}", maker, "sell", SOL, 0.000217, usd, ts, base=base)


def with_dump(base, trades, usd=1430.0, lead=30):
    """Tambahkan jual besar `lead` detik sebelum awal burst di `base`."""
    return [dump_trade(base - lead, usd=usd)] + trades


class RoundTripTests(unittest.TestCase):
    def test_round_trip_detected(self):
        rts = ew.round_trips(round_trip_trades("T1", "W1", 1000, spread=0.05))
        self.assertEqual(len(rts), 1)
        self.assertAlmostEqual(rts[0]["spread"], 0.05, places=6)
        self.assertEqual(rts[0]["maker"], "W1")

    def test_same_quote_is_not_round_trip(self):
        buy = trade("T1", "W1", "buy", SOL, 1.0, 50, 1000)
        sell = trade("T1", "W1", "sell", SOL, 1.05, 50, 1000)
        self.assertEqual(ew.round_trips([buy, sell]), [])

    def test_different_tx_is_not_round_trip(self):
        buy = trade("T1", "W1", "buy", CM, 1.0, 50, 1000)
        sell = trade("T2", "W1", "sell", SOL, 1.05, 50, 1000)
        self.assertEqual(ew.round_trips([buy, sell]), [])

    def test_below_min_spread_ignored(self):
        self.assertEqual(ew.round_trips(round_trip_trades("T1", "W1", 1000, spread=0.01)), [])

    def test_above_max_spread_ignored(self):
        self.assertEqual(ew.round_trips(round_trip_trades("T1", "W1", 1000, spread=0.60)), [])

    def test_dust_leg_ignored(self):
        self.assertEqual(ew.round_trips(round_trip_trades("T1", "W1", 1000, usd=0.05)), [])

    def test_malformed_rows_ignored(self):
        bad = [None, "x", {"event": "buy"}, {"tx_hash": "T", "maker": "W", "event": "swap"},
               trade("T", "W", "buy", CM, 0, 50, 1000),
               trade("T", "W", "buy", CM, 1.0, 50, 0)]
        self.assertEqual(ew.round_trips(bad), [])


class ActivityTests(unittest.TestCase):
    def test_active_needs_five_trips_from_three_wallets(self):
        rts = ew.round_trips(burst(1000, 5, WALLETS))
        self.assertTrue(ew.active_ends(ew.window_stats(rts)))

    def test_four_trips_not_active(self):
        rts = ew.round_trips(burst(1000, 4, WALLETS))
        self.assertEqual(ew.active_ends(ew.window_stats(rts)), [])

    def test_two_wallets_not_active(self):
        rts = ew.round_trips(burst(1000, 8, ["W1", "W2"]))
        self.assertEqual(ew.active_ends(ew.window_stats(rts)), [])

    def test_spread_out_trips_not_active(self):
        trades = []
        for i in range(6):
            trades += round_trip_trades(f"T{i}", WALLETS[i % 4], 1000 + i * 120)
        self.assertEqual(ew.active_ends(ew.window_stats(ew.round_trips(trades))), [])


class DumpTests(unittest.TestCase):
    def test_big_sell_is_dump(self):
        d = ew.big_sells([dump_trade(1000)], set())
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["base"], 6_600_000)

    def test_small_sell_is_not_dump(self):
        # COCK 22:40 WIB: jual $379, di bawah ambang $1.000.
        self.assertEqual(ew.big_sells([dump_trade(1000, usd=379)], set()), [])

    def test_buy_is_never_dump(self):
        buy = trade("B1", "D1", "buy", SOL, 0.0002, 5000, 1000, base=1)
        self.assertEqual(ew.big_sells([buy], set()), [])

    def test_round_trip_leg_is_not_dump(self):
        big_leg = trade("T1", "W1", "sell", SOL, 1.05, 5000, 1000, base=1)
        buy_leg = trade("T1", "W1", "buy", CM, 1.0, 5000, 1000, base=1)
        rts = ew.round_trips([buy_leg, big_leg])
        rt_keys = {(r["tx"], r["maker"]) for r in rts}
        self.assertEqual(ew.big_sells([big_leg], rt_keys), [])

    def test_find_dump_window(self):
        dumps = [{"tx": "a", "maker": "D", "ts": 10_000, "usd": 1500, "base": 1}]
        # Awal aktivitas 10_300: jendela = [10_300-60-300, 10_300] = [9_940, 10_300].
        self.assertIsNotNone(ew.find_dump(dumps, 10_300))
        # 10_000 terlalu jauh dari awal 10_400 (jendela mulai 10_040).
        self.assertIsNone(ew.find_dump(dumps, 10_400))
        # Dump sesudah awal tidak dihitung.
        self.assertIsNone(ew.find_dump(dumps, 9_900))

    def test_merge_dumps_dedupes_and_prunes(self):
        d = {"tx": "a", "maker": "D", "ts": 10_000, "usd": 1500.0, "base": 1}
        merged = ew._merge_dumps([d], [dict(d)], now=10_100)
        self.assertEqual(len(merged), 1)
        self.assertEqual(ew._merge_dumps([d], [], now=10_000 + ew.DUMP_KEEP_SEC + 1), [])


class EvaluateTests(unittest.TestCase):
    def test_dump_then_burst_alerts_once(self):
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        rec, alert, status = ew.evaluate_mint({}, trades, 10_060, partial=False)
        self.assertEqual(status, "AWAL AKTIF")
        self.assertIsNotNone(alert)
        self.assertEqual(alert["wallets"], 4)
        self.assertEqual(alert["dump"]["usd"], 1430.0)
        self.assertEqual(rec["alerts"], 1)
        self.assertEqual(rec["cooldown_until"], 10_060 + ew.COOLDOWN_SEC)

    def test_burst_without_dump_no_alert(self):
        rec, alert, status = ew.evaluate_mint({}, burst(10_000, 6, WALLETS), 10_060,
                                              partial=False)
        self.assertIsNone(alert)
        self.assertEqual(status, "AKTIF (tanpa dump)")
        self.assertFalse(rec["burst_ok"])
        self.assertEqual(rec.get("alerts", 0), 0)

    def test_small_dump_no_alert(self):
        trades = with_dump(10_000, burst(10_000, 6, WALLETS), usd=379)
        _, alert, status = ew.evaluate_mint({}, trades, 10_060, partial=False)
        self.assertIsNone(alert)
        self.assertEqual(status, "AKTIF (tanpa dump)")

    def test_dump_too_early_no_alert(self):
        trades = [dump_trade(10_000 - 1000)] + burst(10_000, 6, WALLETS)
        _, alert, _ = ew.evaluate_mint({}, trades, 10_060, partial=False)
        self.assertIsNone(alert)

    def test_dump_from_previous_poll_counts(self):
        # Poll 1 hanya melihat dump; poll 2 melihat burst. Dump harus tersimpan di rec.
        rec, alert1, _ = ew.evaluate_mint({}, [dump_trade(9_980)], 9_990, partial=False)
        self.assertIsNone(alert1)
        rec2, alert2, status2 = ew.evaluate_mint(rec, burst(10_000, 6, WALLETS), 10_060,
                                                 partial=False)
        self.assertIsNotNone(alert2)
        self.assertEqual(status2, "AWAL AKTIF")

    def test_ongoing_burst_does_not_realert(self):
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        rec, _, _ = ew.evaluate_mint({}, trades, 10_060, partial=False)
        trades2 = trades + burst(10_100, 6, WALLETS, prefix="b")
        rec2, alert2, status2 = ew.evaluate_mint(rec, trades2, 10_180, partial=False)
        self.assertIsNone(alert2)
        self.assertEqual(status2, "AKTIF")
        self.assertEqual(rec2["alerts"], 1)

    def test_quiet_then_burst_within_cooldown_no_alert(self):
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        rec, _, _ = ew.evaluate_mint({}, trades, 10_060, partial=False)
        second = with_dump(10_700, burst(10_700, 6, WALLETS, prefix="c"), lead=30)
        _, alert2, _ = ew.evaluate_mint(rec, trades + second, 10_800, partial=False)
        self.assertIsNone(alert2)

    def test_quiet_then_burst_after_cooldown_alerts(self):
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        rec, _, _ = ew.evaluate_mint({}, trades, 10_060, partial=False)
        second = with_dump(12_000, burst(12_000, 6, WALLETS, prefix="d"))
        rec2, alert2, status2 = ew.evaluate_mint(rec, trades + second, 12_060,
                                                 partial=False)
        self.assertIsNotNone(alert2)
        self.assertEqual(status2, "AWAL AKTIF")
        self.assertEqual(rec2["alerts"], 2)

    def test_tenang_when_no_activity(self):
        rec, alert, status = ew.evaluate_mint({}, [], 10_000, partial=False)
        self.assertIsNone(alert)
        self.assertEqual(status, "TENANG")
        self.assertEqual(rec["trades"], 0)

    def test_partial_flag_is_kept_on_alert(self):
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        _, alert, _ = ew.evaluate_mint({}, trades, 10_060, partial=True)
        self.assertTrue(alert["partial"])

    def test_alert_text_includes_dump(self):
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        _, alert, _ = ew.evaluate_mint({}, trades, 10_060, partial=False)
        text = ew.format_alert(MINT, alert)
        self.assertIn("Jual besar sebelum aktif: $1,430", text)
        self.assertIn("6.60 juta token", text)
        self.assertIn("Info saja", text)


class PollTests(unittest.TestCase):
    def test_fetch_failure_recorded_and_state_kept(self):
        state = ew.empty_state(9_000)
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        ew.run_poll(state, [MINT], 10_060, fetcher=lambda m, a, b: (trades, False))
        last_active = state["mints"][MINT]["last_active_ts"]

        def broken(m, a, b):
            raise RuntimeError("timeout")

        ew.run_poll(state, [MINT], 10_180, fetcher=broken)
        rec = state["mints"][MINT]
        self.assertEqual(rec["status"], "GAGAL")
        self.assertIn("timeout", rec["error"])
        self.assertEqual(rec["last_active_ts"], last_active)
        self.assertEqual(state["log"][-1]["status"], "GAGAL")

    def test_failure_does_not_alert(self):
        sent = []

        def broken(m, a, b):
            raise RuntimeError("down")

        state = ew.run_poll(ew.empty_state(), [MINT], 10_000, fetcher=broken,
                            sender=lambda t: sent.append(t) or (True, ""))
        self.assertEqual(sent, [])
        self.assertEqual(state["mints"][MINT]["status"], "GAGAL")

    def test_alert_sent_once_with_info_wording(self):
        sent = []
        state = ew.empty_state()
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        fetch = lambda m, a, b: (trades, False)
        sender = lambda t: sent.append(t) or (True, "")
        ew.run_poll(state, [MINT], 10_060, fetcher=fetch, sender=sender)
        ew.run_poll(state, [MINT], 10_180, fetcher=fetch, sender=sender)
        self.assertEqual(len(sent), 1)
        self.assertIn("Info saja", sent[0])
        self.assertIn(MINT, sent[0])
        self.assertTrue(state["mints"][MINT]["last_alert"]["sent"])

    def test_send_failure_recorded(self):
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        state = ew.run_poll(ew.empty_state(), [MINT], 10_060,
                            fetcher=lambda m, a, b: (trades, False),
                            sender=lambda t: (False, "HTTP 500"))
        self.assertFalse(state["mints"][MINT]["last_alert"]["sent"])
        self.assertIn("HTTP 500", state["mints"][MINT]["last_alert"]["error"])

    def test_every_watchlist_mint_is_polled(self):
        mints = ["A1", "B2", "C3"]
        seen = []
        state = ew.run_poll(ew.empty_state(), mints, 10_000,
                            fetcher=lambda m, a, b: (seen.append(m) or ([], False)))
        self.assertEqual(seen, mints)
        self.assertEqual(set(state["mints"]), set(mints))

    def test_log_is_bounded(self):
        state = ew.empty_state()
        for i in range(ew.LOG_KEEP + 50):
            ew.run_poll(state, [MINT], 10_000 + i, fetcher=lambda m, a, b: ([], False))
        self.assertEqual(len(state["log"]), ew.LOG_KEEP)


class FingerprintAndRunnerTests(unittest.TestCase):
    def test_log_only_change_keeps_fingerprint(self):
        state = ew.run_poll(ew.empty_state(), [MINT], 10_000,
                            fetcher=lambda m, a, b: ([], False))
        before = ew.decision_fingerprint(state)
        ew.run_poll(state, [MINT], 10_120, fetcher=lambda m, a, b: ([], False))
        self.assertEqual(ew.decision_fingerprint(state), before)

    def test_alert_changes_fingerprint(self):
        state = ew.run_poll(ew.empty_state(), [MINT], 10_000,
                            fetcher=lambda m, a, b: ([], False))
        before = ew.decision_fingerprint(state)
        trades = with_dump(10_000, burst(10_000, 6, WALLETS))
        ew.run_poll(state, [MINT], 10_060, fetcher=lambda m, a, b: (trades, False),
                    sender=None)
        self.assertNotEqual(ew.decision_fingerprint(state), before)

    def test_new_dump_changes_fingerprint(self):
        # Dump yang belum ter-commit akan hilang di job berikutnya, jadi harus
        # tercermin di fingerprint.
        state = ew.run_poll(ew.empty_state(), [MINT], 10_000,
                            fetcher=lambda m, a, b: ([], False))
        before = ew.decision_fingerprint(state)
        ew.run_poll(state, [MINT], 10_060, fetcher=lambda m, a, b: ([dump_trade(10_050)], False))
        self.assertNotEqual(ew.decision_fingerprint(state), before)

    def test_runner_once_offline(self):
        import early_watch as mod  # noqa: F401 — memastikan modul yang sama
        import scripts.early_watch as runner
        orig_fetch, orig_wl = ew.fetch_window, ew.load_watchlist
        try:
            # Runner memakai jam nyata; fixture harus relatif terhadap sekarang,
            # karena dump yang lebih tua dari 15 menit di-prune.
            t0 = int(time.time()) - 60
            ew.fetch_window = lambda m, a, b: (with_dump(t0, burst(t0, 6, WALLETS)), False)
            ew.load_watchlist = lambda *a, **k: [MINT]
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "st.json")
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = runner.main(["--no-alerts", "--state", path])
                self.assertEqual(rc, 0)
                self.assertIn("EARLY_WATCH_CHANGED=1", buf.getvalue().splitlines()[-1])
                with open(path, encoding="utf-8") as fh:
                    saved = json.load(fh)
                self.assertEqual(saved["mints"][MINT]["status"], "AWAL AKTIF")
        finally:
            ew.fetch_window, ew.load_watchlist = orig_fetch, orig_wl


class WatchlistTests(unittest.TestCase):
    def test_dedupe_and_order(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"mints": ["A", "B", "A", "", None, " C "]}, fh)
            path = fh.name
        self.assertEqual(ew.load_watchlist(path), ["A", "B", "C"])

    def test_missing_file_is_empty(self):
        self.assertEqual(ew.load_watchlist("/nonexistent/x.json"), [])

    def test_repo_watchlist_has_the_five_requested_mints(self):
        mints = ew.load_watchlist()
        self.assertEqual(len(mints), 5)
        self.assertIn("8nPoBHiBM6pybxMws9PA2JRb9BjkppBfqcZGmot4DMBC", mints)
        self.assertIn("55A3VxMBfzw6uSe64zms5iMPw9k6kx9WzzusbCU6pump", mints)


if __name__ == "__main__":
    unittest.main()
