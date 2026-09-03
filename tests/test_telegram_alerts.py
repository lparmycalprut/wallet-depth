"""Unit coverage for holder-dust Telegram rules, state, and transport."""
from __future__ import annotations

import unittest
from unittest import mock

import requests

import telegram_alerts as ta

NOW = 2_000_000
FOUR_HOURS = 4 * 3600
MINT = "MintAddress123"


def _snapshot(ts, dust_pct, balances=None, dust=None):
    return {
        "ts": ts,
        "dust_pct_mc": dust_pct,
        "balances": balances or {},
        "dust": dust or [],
        "wallets_seen": len(balances or {}),
        "truncated": False,
    }


def _event_state(previous, *, sent=None, baseline=None):
    return {
        "rolling": previous,
        "baseline": baseline or previous,
        "sent_event_ids": sent or [],
    }


def _analysis(current, symbol="TST"):
    return {
        "symbol": symbol,
        "analyzed_at": current["ts"],
        "holders": {
            "dust_pct_mc": current["dust_pct_mc"],
            "wallet_snapshot": current,
        },
    }


class FourHourRuleTest(unittest.TestCase):
    def setUp(self):
        self.previous = _snapshot(
            NOW - FOUR_HOURS, 1.00, {"A": 10.0}, ["A"])

    def evaluate(self, current):
        return ta.evaluate_4h_rules(
            self.previous, current, mint=MINT, symbol="TST")

    def test_dump_exactly_at_point_25_threshold(self):
        events = self.evaluate(_snapshot(NOW, 1.25, {"A": 9.0}, ["A"]))
        self.assertEqual([event["kind"] for event in events], ["dump"])
        self.assertAlmostEqual(events[0]["change_pp"], 0.25)

    def test_dump_below_threshold_does_not_trigger(self):
        events = self.evaluate(_snapshot(NOW, 1.2499, {"A": 9.0}, ["A"]))
        self.assertEqual(events, [])

    def test_dust_drop_exactly_point_50_with_buyer_triggers(self):
        current = _snapshot(NOW, 0.50, {"A": 11.0}, [])
        events = self.evaluate(current)
        self.assertEqual([event["kind"] for event in events], ["accumulation"])
        self.assertEqual(events[0]["wallet_increases"], 1)
        self.assertAlmostEqual(events[0]["change_pp"], -0.50)

    def test_dust_drop_without_buyer_does_not_trigger(self):
        current = _snapshot(NOW, 0.50, {"A": 9.0}, ["A"])
        self.assertEqual(self.evaluate(current), [])

    def test_dust_drop_with_increased_wallet_triggers(self):
        current = _snapshot(NOW, 0.40, {"A": 10.5}, [])
        events = self.evaluate(current)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "accumulation")

    def test_new_wallet_is_safe_and_not_assumed_to_be_a_comparable_buyer(self):
        current = _snapshot(NOW, 0.40, {"A": 9.0, "NEW": 5.0},
                            ["A", "NEW"])
        self.assertEqual(self.evaluate(current), [])
        movement = ta.wallet_movements(self.previous, current)
        self.assertEqual(movement["new_wallets"], 1)
        self.assertEqual(movement["increased"], 0)

    def test_no_valid_four_hour_snapshot(self):
        recent = _snapshot(NOW - 3600, 1.0, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 2.0, {"A": 20.0}, [])
        self.assertFalse(ta.is_valid_4h_snapshot(recent, current))
        self.assertEqual(ta.evaluate_4h_rules(
            recent, current, mint=MINT, symbol="TST"), [])

    def test_event_deduplication(self):
        current = _snapshot(NOW, 1.30, {"A": 9.0}, ["A"])
        first = self.evaluate(current)
        self.assertEqual(len(first), 1)
        duplicate = ta.evaluate_4h_rules(
            self.previous, current, mint=MINT, symbol="TST",
            sent_event_ids=[first[0]["id"]])
        self.assertEqual(duplicate, [])


class BaselineShiftTest(unittest.TestCase):
    def test_drop_one_point_from_initial_snapshot_has_exit_diagnostics(self):
        baseline = _snapshot(
            NOW - 8 * 3600, 1.50,
            {"GROW": 2.0, "SOLD": 3.0, "STAY": 2.0},
            ["GROW", "SOLD", "STAY"],
        )
        current = _snapshot(
            NOW, 0.50,
            {"GROW": 20.0, "SOLD": 0.0, "STAY": 2.0},
            ["STAY"],
        )
        events = ta.evaluate_baseline_rule(
            baseline, current, mint=MINT, symbol="TST")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "baseline_shift")
        self.assertAlmostEqual(events[0]["change_pp"], -1.0)
        movement = events[0]["movements"]
        self.assertEqual(movement["dust_grew_out"], 1)
        self.assertEqual(movement["dust_sold_out"], 1)

    def test_rise_one_point_reports_wallets_shrinking_into_dust(self):
        baseline = _snapshot(NOW - FOUR_HOURS, 0.20, {"BIG": 20.0}, [])
        current = _snapshot(NOW, 1.20, {"BIG": 2.0, "NEW": 1.0},
                            ["BIG", "NEW"])
        event = ta.evaluate_baseline_rule(
            baseline, current, mint=MINT, symbol="TST")[0]
        self.assertEqual(event["movements"]["larger_shrank_into_dust"], 1)
        self.assertEqual(event["movements"]["new_dust"], 1)
        message = ta.format_alert_message(event)
        self.assertIn("SNAPSHOT AWAL", message)
        self.assertIn("+1.00 poin persentase", message)
        self.assertIn(MINT, message)


class AlertStateTest(unittest.TestCase):
    def test_first_snapshot_seeds_anchors_without_alert(self):
        current = _snapshot(NOW, 1.2, {"A": 10.0}, ["A"])
        events, state = ta.evaluate_alert_events(MINT, _analysis(current), {})
        self.assertEqual(events, [])
        self.assertEqual(state["baseline"]["ts"], NOW)
        self.assertEqual(state["rolling"]["ts"], NOW)

    def test_process_records_successful_event_and_deduplicates_same_bucket(self):
        previous = _snapshot(NOW - FOUR_HOURS, 1.0, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.3, {"A": 9.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": _event_state(previous),
                                    "points": [], "cohort": {}}}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        first = ta.process_holder_alerts(
            {MINT: _analysis(current)}, store, sender=sender)
        self.assertEqual(len(first), 1)
        self.assertEqual(sender.call_count, 1)
        sent_ids = store["tokens"][MINT]["alert_state"]["sent_event_ids"]
        self.assertEqual(len(sent_ids), 1)

        # Rolling anchor is now current and the baseline event is below 1 pp.
        second = ta.process_holder_alerts(
            {MINT: _analysis(current)}, store, sender=sender)
        self.assertEqual(second, [])
        self.assertEqual(sender.call_count, 1)

    def test_sender_error_never_raises(self):
        previous = _snapshot(NOW - FOUR_HOURS, 1.0, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 1.3, {"A": 9.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": _event_state(previous)}}}
        result = ta.process_holder_alerts(
            {MINT: _analysis(current)}, store,
            sender=mock.Mock(side_effect=TimeoutError("late")),
        )
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["delivery"]["ok"])

    def test_zero_holder_provider_failure_does_not_advance_or_alert(self):
        previous = _snapshot(NOW - FOUR_HOURS, 1.5, {"A": 10.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": _event_state(previous)}}}
        failed = _analysis(_snapshot(NOW, 0.0, {}, []))
        failed["holders"]["total_fetched"] = 0
        before = store["tokens"][MINT]["alert_state"]
        sender = mock.Mock()
        result = ta.process_holder_alerts({MINT: failed}, store, sender=sender)
        self.assertEqual(result, [])
        self.assertIs(store["tokens"][MINT]["alert_state"], before)
        sender.assert_not_called()

    def test_snapshot_payload_is_bounded(self):
        holders = [
            {"address": f"W{i}", "balance": i + 1, "usd_value": 5.0,
             "is_wallet": True}
            for i in range(ta.MAX_COMPARISON_WALLETS + 100)
        ]
        current = ta.build_wallet_snapshot(
            holders, dust_pct_mc=1.0, max_wallets=999999, ts=NOW)
        self.assertLessEqual(len(current["balances"]),
                             ta.MAX_COMPARISON_WALLETS)
        saved = ta.compact_wallet_snapshot(current)
        self.assertLessEqual(len(saved["balances"]), ta.MAX_STORED_WALLETS)


class TelegramTransportTest(unittest.TestCase):
    def test_empty_credentials_skip_without_request(self):
        post = mock.Mock()
        result = ta.send_telegram_message(
            "hello", bot_token="", chat_id="", post=post)
        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        post.assert_not_called()

    def test_success_response(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        post = mock.Mock(return_value=response)
        result = ta.send_telegram_message(
            "hello", bot_token="token", chat_id="chat", post=post)
        self.assertTrue(result["ok"])
        self.assertFalse(result["skipped"])
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "chat")
        self.assertEqual(post.call_args.kwargs["timeout"], 10)

    def test_timeout_does_not_raise(self):
        post = mock.Mock(side_effect=requests.Timeout("too slow"))
        result = ta.send_telegram_message(
            "hello", bot_token="token", chat_id="chat", post=post)
        self.assertFalse(result["ok"])
        self.assertIn("request failed", result["error"])

    def test_http_error_does_not_raise(self):
        response = mock.Mock(status_code=500)
        post = mock.Mock(return_value=response)
        result = ta.send_telegram_message(
            "hello", bot_token="token", chat_id="chat", post=post)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 500)

    def test_transport_error_redacts_bot_token(self):
        secret = "123456:very-secret"
        post = mock.Mock(side_effect=requests.ConnectionError(
            f"failed https://api.telegram.org/bot{secret}/sendMessage"))
        result = ta.send_telegram_message(
            "hello", bot_token=secret, chat_id="chat", post=post)
        self.assertNotIn(secret, result["error"])
        self.assertIn("[REDACTED]", result["error"])

    def test_api_ok_false_does_not_raise(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"ok": False, "description": "bad chat"}
        result = ta.send_telegram_message(
            "hello", bot_token="token", chat_id="chat",
            post=mock.Mock(return_value=response))
        self.assertFalse(result["ok"])
        self.assertIn("bad chat", result["error"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
