"""Coverage gerbang volume/volatilitas di aturan alert + dedup 1 jam."""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

import telegram_alerts as ta

NOW = 2_000_000
FOUR_HOURS = 4 * 3600
MINT = "MintAddress123"

CALM = {"available": True, "price_stddev_4h": 1.2, "high_volatility": False,
        "high_volatility_pct": 3.0}
WILD = {"available": True, "price_stddev_4h": 4.8, "high_volatility": True,
        "high_volatility_pct": 3.0}

CONFIRMED_DUMP = {
    "available": True, "volume_4h": 40_000.0, "avg_volume_7d": 10_000.0,
    "price": 0.5, "price_change_pct": -3.0, "buy_pressure": 30.0,
    "sell_pressure": 120.0, "volume_source": "geckoterminal_hourly",
    "volatility": CALM,
}
QUIET_VOLUME = dict(CONFIRMED_DUMP, volume_4h=5_000.0, price_change_pct=-0.2)
NO_PRICE_PRESSURE = dict(CONFIRMED_DUMP, price_change_pct=-0.4)
CONFIRMED_ACCUMULATION = dict(CONFIRMED_DUMP, volume_4h=20_000.0,
                              price_change_pct=1.5, buy_pressure=140.0,
                              sell_pressure=40.0)
SELL_PRESSURE = dict(CONFIRMED_ACCUMULATION, buy_pressure=20.0,
                     sell_pressure=140.0)


def _snapshot(ts, dust_pct, balances=None, dust=None):
    return {"ts": ts, "dust_pct_mc": dust_pct, "balances": balances or {},
            "dust": dust or [], "wallets_seen": len(balances or {}),
            "truncated": False}


def _analysis(current, symbol="TST", market_context=None):
    analysis = {
        "symbol": symbol,
        "analyzed_at": current["ts"],
        "holders": {"dust_pct_mc": current["dust_pct_mc"],
                    "wallet_snapshot": current},
    }
    if market_context is not None:
        analysis["market_context"] = market_context
    return analysis


class DumpGatingTest(unittest.TestCase):
    def setUp(self):
        self.previous = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        self.current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])

    def evaluate(self, context, **kwargs):
        rejected = kwargs.pop("rejected", [])
        return ta.evaluate_4h_rules(
            self.previous, self.current, mint=MINT, symbol="TST",
            market_context=context, rejected=rejected, **kwargs), rejected

    def test_confirmed_dump_is_sent_with_its_verification(self):
        events, rejected = self.evaluate(CONFIRMED_DUMP)
        self.assertEqual([event["kind"] for event in events], ["dump"])
        self.assertEqual(rejected, [])
        check = events[0]["volume_check"]
        self.assertTrue(check["allow"])
        self.assertTrue(check["verified"])
        self.assertTrue(check["is_valid"])
        self.assertGreaterEqual(check["confidence_score"], ta.MIN_CONFIDENCE)
        self.assertEqual(check["volume_ratio"], 4.0)

    def test_quiet_volume_rejects_the_dust_signal(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            events, rejected = self.evaluate(QUIET_VOLUME)
        self.assertEqual(events, [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["kind"], "dump")
        self.assertFalse(rejected[0]["cooldown"])
        self.assertLess(rejected[0]["confidence_score"], ta.MIN_CONFIDENCE)
        self.assertIn("Dust signal rejected TST dump +0.30pp", stderr.getvalue())
        self.assertIn("0.50x", stderr.getvalue())

    def test_dust_rise_without_price_pressure_is_rejected(self):
        events, rejected = self.evaluate(NO_PRICE_PRESSURE)
        self.assertEqual(events, [])
        self.assertIn("belum ada tekanan jual", rejected[0]["reason"])

    def test_high_volatility_raises_the_bar_and_still_passes_a_real_dump(self):
        wild = dict(CONFIRMED_DUMP, volatility=WILD, volume_4h=20_000.0,
                    price_change_pct=-1.0)
        events, _ = self.evaluate(wild)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["volume_check"]["confidence_score"],
                               0.90, places=2)
        self.assertAlmostEqual(
            events[0]["volume_check"]["required_confidence"], 0.80)

    def test_high_volatility_blocks_a_marginal_accumulation(self):
        marginal = dict(CONFIRMED_ACCUMULATION, volume_4h=15_000.0,
                        buy_pressure=51.0, sell_pressure=50.0,
                        price_change_pct=-2.0, volatility=WILD)
        current = _snapshot(NOW, 0.40, {"A": 11.0}, [])
        rejected = []
        events = ta.evaluate_4h_rules(
            self.previous, current, mint=MINT, symbol="TST",
            market_context=marginal, rejected=rejected)
        self.assertEqual(events, [])
        self.assertEqual(rejected[0]["kind"], "accumulation")
        self.assertAlmostEqual(rejected[0]["required_confidence"], 0.80)

    def test_missing_context_still_alerts_but_flags_it_unverified(self):
        events, _ = self.evaluate(None)
        self.assertEqual(len(events), 1)
        check = events[0]["volume_check"]
        self.assertTrue(check["allow"])
        self.assertFalse(check["verified"])
        message = ta.format_alert_message(events[0])
        self.assertIn("TIDAK TERVERIFIKASI", message)

    def test_accumulation_needs_dominant_buyers(self):
        current = _snapshot(NOW, 0.40, {"A": 11.0}, [])
        rejected = []
        events = ta.evaluate_4h_rules(
            self.previous, current, mint=MINT, symbol="TST",
            market_context=SELL_PRESSURE, rejected=rejected)
        self.assertEqual(events, [])
        self.assertIn("tekanan beli belum dominan", rejected[0]["reason"])

        events = ta.evaluate_4h_rules(
            self.previous, current, mint=MINT, symbol="TST",
            market_context=CONFIRMED_ACCUMULATION)
        self.assertEqual([event["kind"] for event in events], ["accumulation"])

    def test_sub_threshold_dust_never_reaches_the_volume_gate(self):
        """Di bawah 0,25 pp tidak ada kandidat → konteks tidak perlu ditarik."""
        provider = mock.Mock(return_value=CONFIRMED_DUMP)
        small = _snapshot(NOW, 1.05, {"A": 9.0}, ["A"])
        events = ta.evaluate_4h_rules(
            self.previous, small, mint=MINT, symbol="TST",
            context_provider=provider)
        self.assertEqual(events, [])
        provider.assert_not_called()


class LazyProviderTest(unittest.TestCase):
    def test_provider_is_called_once_even_with_two_candidate_rules(self):
        """Baseline shift + dump 4 jam dalam satu evaluasi = satu penarikan data."""
        provider = mock.Mock(return_value=CONFIRMED_DUMP)
        baseline = _snapshot(NOW - 8 * 3600, 0.20, {"A": 20.0}, [])
        rolling = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])
        state = {"baseline": baseline, "rolling": rolling, "sent_event_ids": []}
        events, _next = ta.evaluate_alert_events(
            MINT, _analysis(current), state, context_provider=provider)
        self.assertEqual(sorted(event["kind"] for event in events),
                         ["baseline_shift", "dump"])
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.call_args.args[0], MINT)
        self.assertIs(provider.call_args.args[1]["holders"]["wallet_snapshot"],
                      current)

    def test_provider_is_not_called_without_candidates(self):
        provider = mock.Mock(return_value=CONFIRMED_DUMP)
        rolling = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.05, {"A": 9.5}, ["A"])
        state = {"baseline": rolling, "rolling": rolling, "sent_event_ids": []}
        events, _next = ta.evaluate_alert_events(
            MINT, _analysis(current), state, context_provider=provider)
        self.assertEqual(events, [])
        provider.assert_not_called()

    def test_provider_failure_degrades_to_unverified_alert(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            provider = mock.Mock(side_effect=RuntimeError("geckoterminal 429"))
            rolling = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
            current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])
            events, _next = ta.evaluate_alert_events(
                MINT, _analysis(current),
                {"baseline": rolling, "rolling": rolling, "sent_event_ids": []},
                context_provider=provider)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["volume_check"]["verified"])
        self.assertIn("geckoterminal 429", stderr.getvalue())

    def test_context_embedded_in_the_analysis_is_used(self):
        provider = mock.Mock(return_value=None)
        rolling = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])
        events, _next = ta.evaluate_alert_events(
            MINT, _analysis(current, market_context=QUIET_VOLUME),
            {"baseline": rolling, "rolling": rolling, "sent_event_ids": []},
            context_provider=provider)
        self.assertEqual(events, [])
        provider.assert_not_called()


class BaselineGatingTest(unittest.TestCase):
    def test_rise_is_validated_as_a_dump(self):
        baseline = _snapshot(NOW - FOUR_HOURS, 0.20, {"BIG": 20.0}, [])
        current = _snapshot(NOW, 1.30, {"BIG": 2.0}, ["BIG"])
        events = ta.evaluate_baseline_rule(
            baseline, current, mint=MINT, symbol="TST",
            market_context=CONFIRMED_DUMP)
        self.assertEqual([event["kind"] for event in events], ["baseline_shift"])
        self.assertEqual(events[0]["volume_check"]["event_kind"],
                         "baseline_shift")
        self.assertEqual(events[0]["volume_check"]["kind"], "dump")

        rejected = []
        quiet = ta.evaluate_baseline_rule(
            baseline, current, mint=MINT, symbol="TST",
            market_context=QUIET_VOLUME, rejected=rejected)
        self.assertEqual(quiet, [])
        self.assertEqual(len(rejected), 1)

    def test_drop_is_validated_as_an_accumulation(self):
        baseline = _snapshot(NOW - 8 * 3600, 1.50, {"A": 2.0}, ["A"])
        current = _snapshot(NOW, 0.40, {"A": 20.0}, [])
        events = ta.evaluate_baseline_rule(
            baseline, current, mint=MINT, symbol="TST",
            market_context=CONFIRMED_ACCUMULATION)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["volume_check"]["kind"], "accumulation")

        rejected = []
        blocked = ta.evaluate_baseline_rule(
            baseline, current, mint=MINT, symbol="TST",
            market_context=SELL_PRESSURE, rejected=rejected)
        self.assertEqual(blocked, [])
        self.assertEqual(rejected[0]["kind"], "baseline_shift")


class CooldownTest(unittest.TestCase):
    def setUp(self):
        self.previous = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        self.current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])

    def evaluate(self, last_sent):
        rejected = []
        events = ta.evaluate_4h_rules(
            self.previous, self.current, mint=MINT, symbol="TST",
            market_context=CONFIRMED_DUMP, rejected=rejected,
            last_sent=last_sent)
        return events, rejected

    def test_recent_send_blocks_the_bucket_boundary_duplicate(self):
        events, rejected = self.evaluate({"dump": NOW - 30 * 60})
        self.assertEqual(events, [])
        self.assertTrue(rejected[0]["cooldown"])
        self.assertIn("30 menit", rejected[0]["reason"])

    def test_old_send_does_not_block(self):
        events, _ = self.evaluate({"dump": NOW - 2 * 3600})
        self.assertEqual(len(events), 1)

    def test_other_kind_does_not_block(self):
        events, _ = self.evaluate({"accumulation": NOW - 60})
        self.assertEqual(len(events), 1)

    def test_cooldown_boundary_is_exactly_one_hour(self):
        events, rejected = self.evaluate({"dump": NOW - ta.MIN_RESEND_SEC})
        self.assertEqual(len(events), 1)
        self.assertEqual(rejected, [])
        events, rejected = self.evaluate({"dump": NOW - ta.MIN_RESEND_SEC + 1})
        self.assertEqual(events, [])
        self.assertTrue(rejected[0]["cooldown"])

    def test_future_last_send_is_ignored(self):
        events, _ = self.evaluate({"dump": NOW + 3600})
        self.assertEqual(len(events), 1)

    def test_dedup_key_includes_direction_only_for_baseline_shift(self):
        self.assertEqual(ta.dedup_key({"kind": "dump"}), "dump")
        self.assertEqual(ta.dedup_key({"kind": "accumulation",
                                       "direction": "down"}), "accumulation")
        self.assertEqual(
            ta.dedup_key({"kind": "baseline_shift", "direction": "up"}),
            "baseline_shift:up")


class ProcessAlertsTest(unittest.TestCase):
    def test_last_sent_is_recorded_after_a_successful_delivery(self):
        rolling = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": {
            "baseline": rolling, "rolling": rolling, "sent_event_ids": []}}}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {MINT: _analysis(current, market_context=CONFIRMED_DUMP)}, store,
            sender=sender)
        self.assertEqual(len(deliveries), 1)
        state = store["tokens"][MINT]["alert_state"]
        self.assertEqual(state["last_sent"], {"dump": NOW})
        self.assertEqual(state["rejected_signals"], [])

    def test_cross_bucket_duplicate_within_one_hour_is_suppressed(self):
        """Event id berbeda (bucket baru) tapi masih dalam jendela 1 jam."""
        later = NOW + 1_700                     # bucket 4 jam berikutnya
        self.assertNotEqual(later // ta.EVENT_BUCKET_SEC,
                            NOW // ta.EVENT_BUCKET_SEC)
        rolling = _snapshot(later - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        current = _snapshot(later, 1.30, {"A": 9.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": {
            "baseline": rolling, "rolling": rolling, "sent_event_ids": [],
            "last_sent": {"dump": NOW}}}}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {MINT: _analysis(current, market_context=CONFIRMED_DUMP)}, store,
            sender=sender)
        self.assertEqual(deliveries, [])
        sender.assert_not_called()
        rejected = store["tokens"][MINT]["alert_state"]["rejected_signals"]
        self.assertTrue(rejected[-1]["cooldown"])

    def test_failed_delivery_does_not_start_the_cooldown(self):
        rolling = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": {
            "baseline": rolling, "rolling": rolling, "sent_event_ids": []}}}}
        ta.process_holder_alerts(
            {MINT: _analysis(current, market_context=CONFIRMED_DUMP)}, store,
            sender=mock.Mock(return_value={"ok": False, "skipped": False,
                                           "error": "Telegram HTTP 500"}))
        state = store["tokens"][MINT]["alert_state"]
        self.assertEqual(state["last_sent"], {})
        self.assertEqual(state["sent_event_ids"], [])

    def test_rejected_signals_are_persisted_and_bounded(self):
        store = {"tokens": {}}
        for index in range(ta.MAX_REJECTED_SIGNALS + 4):
            ts = NOW + index * ta.ALERT_WINDOW_SEC
            rolling = _snapshot(ts - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
            current = _snapshot(ts, 1.30, {"A": 9.0}, ["A"])
            store["tokens"][MINT] = {"alert_state": {
                "baseline": rolling, "rolling": rolling,
                "sent_event_ids": [],
                "rejected_signals": (store["tokens"].get(MINT, {})
                                     .get("alert_state", {})
                                     .get("rejected_signals", []))}}
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                ta.process_holder_alerts(
                    {MINT: _analysis(current, market_context=QUIET_VOLUME)},
                    store, sender=mock.Mock())
        state = store["tokens"][MINT]["alert_state"]
        self.assertEqual(len(state["rejected_signals"]),
                         ta.MAX_REJECTED_SIGNALS)
        self.assertFalse(state["rejected_signals"][-1]["verified"] is False)

    def test_unverified_alert_message_says_so(self):
        rolling = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])
        events, _ = ta.evaluate_alert_events(
            MINT, _analysis(current),
            {"baseline": rolling, "rolling": rolling, "sent_event_ids": []})
        message = ta.format_alert_message(events[0])
        self.assertIn("TIDAK TERVERIFIKASI", message)
        self.assertNotIn("Skor konfirmasi", message)

    def test_verified_alert_message_shows_ratio_and_score(self):
        rolling = _snapshot(NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])
        events, _ = ta.evaluate_alert_events(
            MINT, _analysis(current, market_context=dict(
                CONFIRMED_DUMP, volatility=WILD)),
            {"baseline": rolling, "rolling": rolling, "sent_event_ids": []})
        message = ta.format_alert_message(events[0])
        self.assertIn("Verifikasi volume: ✅", message)
        self.assertIn("4.00× rata-rata 7d", message)
        self.assertIn("harga -3.00%", message)
        self.assertIn("Skor konfirmasi:", message)
        self.assertIn("stddev 4 jam 4.80%", message)
        self.assertIn("(pasar liar)", message)

    def test_state_compaction_keeps_the_new_fields_bounded(self):
        state = {
            "baseline": _snapshot(NOW, 1.0), "rolling": _snapshot(NOW, 1.0),
            "sent_event_ids": [f"id{index}" for index in range(200)],
            "last_sent": {f"dump{index}": NOW - index for index in range(40)},
            "rejected_signals": [{"ts": NOW, "kind": "dump"}] * 40,
        }
        compact = ta.compact_alert_state(state)
        self.assertEqual(len(compact["sent_event_ids"]), ta.MAX_SENT_EVENT_IDS)
        self.assertEqual(len(compact["last_sent"]), ta.MAX_LAST_SENT)
        self.assertEqual(len(compact["rejected_signals"]),
                         ta.MAX_REJECTED_SIGNALS)
        self.assertEqual(compact["last_sent"]["dump0"], NOW)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
