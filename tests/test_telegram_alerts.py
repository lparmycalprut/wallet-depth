"""Unit coverage for holder-dust Telegram rules, state, and transport."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest import mock

import requests

import telegram_alerts as ta
from links import (blockscout_token_url, dexscreener_token_url,
                   gmgn_token_url, rh_scan_token_url)

NOW = 2_000_000
FOUR_HOURS = 4 * 3600
MINT = "MintAddress123"
ALERT_KINDS = ("early_dump", ta.ESCALATION_KIND, ta.SAFE_RETURN_KIND,
               ta.HIGH_DROP_KIND, "dump", "accumulation", "baseline_shift")


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
        self.assertIn("+1.00 pp", message)
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


def _dump_event(mint=MINT):
    """Event dump nyata dari aturan baseline (bukan dict bikinan tangan)."""
    baseline = _snapshot(NOW - FOUR_HOURS, 0.20, {"BIG": 20.0}, [])
    current = _snapshot(NOW, 1.20, {"BIG": 2.0, "NEW": 1.0}, ["BIG", "NEW"])
    return ta.evaluate_baseline_rule(baseline, current, mint=mint,
                                     symbol="TST")[0]


def _utf16_slice(text: str, offset: int, length: int) -> str:
    """Potongan teks yang dirujuk satu entity (satuan UTF-16 Bot API)."""
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le")


def _links(text: str, entities: list[dict]) -> list[tuple[str, str]]:
    """``[(label, url), …]`` dari entity ``text_link`` sesuai urutan teks."""
    return [(_utf16_slice(text, e["offset"], e["length"]), e["url"])
            for e in entities if e.get("type") == "text_link"]


class AlertMessageLinkTest(unittest.TestCase):
    """Link GMGN + DexScreener = **hyperlink** (entity ``text_link``).

    Sejak 2026-09-09 URL tidak lagi ditulis di teks (dulu
    ``🔗 GMGN: https://gmgn.ai/sol/token/<mint>`` — panjang dan tidak enak
    dibaca); baris hanya ``🔗 GMGN`` dan labelnya diberi entity hyperlink.
    """

    def test_link_gmgn_dan_dexscreener_jadi_hyperlink(self):
        text, entities = ta.build_alert_message(_dump_event())
        self.assertIn("\n\U0001f517 GMGN\n", text)
        self.assertTrue(text.endswith("\n\U0001f986 DexScreener"))
        self.assertEqual(_links(text, entities),
                         [("GMGN", gmgn_token_url(MINT)),
                          ("DexScreener", dexscreener_token_url(MINT))])

    def test_url_tidak_ditulis_di_teks(self):
        text, entities = ta.build_alert_message(_dump_event())
        self.assertNotIn("http", text)
        self.assertNotIn("gmgn.ai", text)
        self.assertNotIn("dexscreener.com", text)
        self.assertEqual(ta.format_alert_message(_dump_event()), text)
        # emoji tidak ikut jadi bagian hyperlink, hanya labelnya
        for entity in entities:
            self.assertNotIn("\U0001f517", _utf16_slice(
                text, entity["offset"], entity["length"]))

    def test_link_pakai_helper_links_bukan_url_rakitan_sendiri(self):
        text, entities = ta.build_alert_message(_dump_event())
        self.assertEqual([url for _, url in _links(text, entities)],
                         [gmgn_token_url(MINT), dexscreener_token_url(MINT)])

    def test_link_muncul_setelah_baris_mint(self):
        text, _ = ta.build_alert_message(_dump_event())
        self.assertLess(text.index("Mint:"), text.index("GMGN"))

    def test_tanpa_mint_tidak_ada_link_menggantung(self):
        text, entities = ta.build_alert_message(_dump_event(mint=""))
        self.assertIn("Mint: -", text)
        self.assertTrue(text.endswith("Mint: -"))
        self.assertNotIn("GMGN", text)
        self.assertNotIn("DexScreener", text)
        self.assertEqual(entities, [])

    def test_mint_berbahaya_diencode_di_url_entity(self):
        text, entities = ta.build_alert_message(_dump_event(mint="a?b&c d#e"))
        for _, url in _links(text, entities):
            self.assertIn("a%3Fb%26c%20d%23e", url)
            self.assertNotIn(" ", url)
        # mint mentah tetap literal di baris Mint (bukan markup)
        self.assertIn("📋 Mint: a?b&c d#e", text)

    def test_semua_jenis_alert_membawa_link(self):
        for kind in (*ALERT_KINDS, "lain"):
            event = _dump_event()
            event["kind"] = kind
            text, entities = ta.build_alert_message(event)
            self.assertEqual(
                _links(text, entities),
                [("GMGN", gmgn_token_url(MINT)),
                 ("DexScreener", dexscreener_token_url(MINT))], kind)

    def test_entities_yang_dikirim_ke_bot_api_memuat_hyperlink(self):
        with mock.patch.object(ta, "send_telegram_message",
                               return_value={"ok": True}) as send:
            result = ta.send_telegram_alert(_dump_event())
        self.assertTrue(result["ok"])
        text = send.call_args.args[0]
        entities = send.call_args.kwargs["entities"]
        self.assertNotIn("http", text)
        self.assertEqual(_links(text, entities),
                         [("GMGN", gmgn_token_url(MINT)),
                          ("DexScreener", dexscreener_token_url(MINT))])

    def test_offset_utf16_tepat_walau_symbol_dan_mint_beremoji(self):
        event = dict(_dump_event(mint="M🚀int" + "x" * 20), symbol="TST🚀🚀")
        text, entities = ta.build_alert_message(event)
        labels = [label for label, _ in _links(text, entities)]
        self.assertEqual(labels, ["GMGN", "DexScreener"])

    def test_alert_test_tetap_tanpa_link_token(self):
        with mock.patch.object(ta, "send_telegram_message",
                               return_value={"ok": True}) as send:
            ta.send_test_alert()
        text = send.call_args.args[0]
        self.assertIn("TEST ALERT", text)
        self.assertNotIn("gmgn.ai", text)
        self.assertEqual(len(text.splitlines()), 4)
        self.assertIn("🧪 Uji koneksi, bukan sinyal token.", text)
        for line in text.splitlines():
            self.assertTrue(line.startswith(("✅", "📡", "🧪", "🕒")))
        self.assertIn("WIB", text)
        self.assertNotIn("UTC", text)


class CompactAlertMessageTest(unittest.TestCase):
    def test_all_kinds_use_short_emoji_lines_without_changing_event(self):
        emojis = ("⚡", "🚨", "✅", "🔔", "🟢", "🔎", "🪙", "📊", "📈", "🛡️",
                  "📉", "⚠️", "🕒", "📋", "🔗", "🦆")
        for kind in ALERT_KINDS:
            with self.subTest(kind=kind):
                event = dict(_dump_event(), kind=kind, episode_minutes=10,
                             drop_pct=60.0)
                before = deepcopy(event)
                message = ta.format_alert_message(event)
                self.assertEqual(event, before)
                self.assertLessEqual(len(message.splitlines()), 9)
                for line in message.splitlines():
                    if line:
                        self.assertTrue(line.startswith(emojis), line)
                for verbose in ("Periode:", "Verifikasi:", "Verifikasi volume:",
                                "Skor konfirmasi:", "Wallet saldo meningkat:",
                                "Pergerakan sampel wallet dust", "tanpa henti",
                                "Pengingat berulang"):
                    self.assertNotIn(verbose, message)
                times = [line for line in message.splitlines()
                         if line.startswith("🕒 ")]
                self.assertEqual(times, ["🕒 1970-01-24 10:33 WIB"])
                self.assertNotIn("UTC", message)

    def test_decreasing_dust_keeps_negative_percentage_points(self):
        event = dict(_dump_event(), kind="accumulation",
                     previous_dust_pct_mc=1.2, current_dust_pct_mc=0.6,
                     change_pp=-0.6)
        message = ta.format_alert_message(event)
        self.assertTrue(message.startswith("🟢 KEMUNGKINAN AKUMULASI\n"))
        self.assertIn("📊 Dust: 1.20% → 0.60% MC (-0.60 pp)", message)
        self.assertNotIn("-50.00 pp", message)  # Bukan perubahan relatif %.

    def test_high_drop_distinguishes_high_and_relative_drop(self):
        event = dict(_dump_event(), kind=ta.HIGH_DROP_KIND,
                     previous_dust_pct_mc=1.0, current_dust_pct_mc=0.4,
                     change_pp=-0.6, drop_pct=60.0)
        message = ta.format_alert_message(event)
        self.assertIn("🔔 DUST TURUN ≥ 50% DARI HIGH", message)
        self.assertIn("📊 Dust (high → kini): 1.00% → 0.40% MC (-0.60 pp)", message)
        self.assertIn("📉 Turun 60.0% dari high", message)
        self.assertNotIn("TIDAK TERVERIFIKASI", message)

    def test_robinhood_links_preserved_for_all_alert_kinds(self):
        mint = "0x" + "aB" * 20
        for kind in ALERT_KINDS:
            with self.subTest(kind=kind):
                text, entities = ta.build_alert_message(
                    dict(_dump_event(mint), kind=kind))
                self.assertIn(f"📋 Mint: {mint}", text)
                self.assertIn("\n🦆 rh-scan\n🦆 DexScreener\n🌏 Blockscout", text)
                self.assertEqual(
                    _links(text, entities),
                    [("rh-scan", rh_scan_token_url(mint)),
                     ("DexScreener", dexscreener_token_url(mint)),
                     ("Blockscout", blockscout_token_url(mint))])
                self.assertNotIn("http", text)
                for _, url in _links(text, entities):
                    self.assertNotIn("gmgn.ai", url)
                    self.assertNotIn("dexscreener.com/solana", url)

    def test_pool_links_preserved_for_all_lp_alerts(self):
        pool = "PoolAddress123"
        for kind in ("early_dump", ta.ESCALATION_KIND, ta.SAFE_RETURN_KIND):
            with self.subTest(kind=kind):
                text, entities = ta.build_alert_message(dict(
                    _dump_event(), kind=kind, pool_addresses=[pool, "", None]))
                self.assertTrue(text.endswith("\n🌊 Meteora\n🦅 HawkFi"))
                self.assertEqual(text.count("🌊 Meteora"), 1)
                self.assertEqual(
                    _links(text, entities)[-2:],
                    [("Meteora", ta.meteora_dlmm_url(pool)),
                     ("HawkFi", ta.hawkfi_meteora_url(pool))])
                self.assertNotIn("TIDAK TERVERIFIKASI", text)

    def test_pool_links_absent_for_non_lp_alerts(self):
        pool = "PoolAddress123"
        for kind in ALERT_KINDS:
            if kind in ("early_dump", ta.ESCALATION_KIND, ta.SAFE_RETURN_KIND):
                continue
            with self.subTest(kind=kind):
                text, entities = ta.build_alert_message(dict(
                    _dump_event(), kind=kind, pool_addresses=[pool]))
                self.assertNotIn("Meteora", text)
                self.assertEqual(len(_links(text, entities)), 2)

    def test_unverified_warning_stays_short_without_provider_diagnostics(self):
        event = dict(_dump_event(), volume_check={
            "verified": False, "reason": "provider traceback " * 500})
        message = ta.format_alert_message(event)
        self.assertIn("⚠️ TIDAK TERVERIFIKASI — data pasar tidak tersedia", message)
        self.assertNotIn("provider traceback", message)
        self.assertLess(len(message), 600)

    def test_wib_format_and_date_rollover(self):
        self.assertEqual(ta._format_wib(0), "1970-01-01 07:00 WIB")
        self.assertEqual(ta._format_wib(31 * 86400 - 60), "1970-02-01 06:59 WIB")


class TelegramFormattingDeliveryTest(unittest.TestCase):
    def _payload(self, event=None):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"ok": True}
        with mock.patch.dict(ta.os.environ, {"TELEGRAM_BOT_TOKEN": "token",
                                             "TELEGRAM_CHAT_ID": "chat"}), \
                mock.patch.object(ta.requests, "post", return_value=response) as post:
            result = (ta.send_test_alert() if event is None
                      else ta.send_telegram_alert(event))
        self.assertTrue(result["ok"])
        post.assert_called_once()
        return post.call_args.kwargs["json"]

    def test_exit_header_bold_covers_exact_text_with_utf16_emoji_length(self):
        event = dict(_dump_event(), kind=ta.ESCALATION_KIND)
        payload = self._payload(event)
        title = "🚨 WAKTUNYA EXIT / CUTLOSS / Reshape bid-ask 50 bin"
        self.assertEqual(title, ta.ESCALATION_TITLE)
        self.assertTrue(payload["text"].startswith(title + "\n\n🪙"))
        self.assertEqual(payload["text"], ta.format_alert_message(event))
        length = len(title.encode("utf-16-le")) // 2
        self.assertEqual(length, len(title) + 1)  # 🚨 bukan satu unit UTF-16.
        bold = [e for e in payload["entities"] if e["type"] == "bold"]
        self.assertEqual(bold, [{"type": "bold", "offset": 0, "length": length}])
        marked = payload["text"].encode("utf-16-le")[:length * 2].decode("utf-16-le")
        self.assertEqual(marked, title)  # Detail token tidak ikut tebal.
        # Link token ikut sebagai hyperlink di payload yang sama.
        self.assertEqual(_links(payload["text"], payload["entities"]),
                         [("GMGN", gmgn_token_url(MINT)),
                          ("DexScreener", dexscreener_token_url(MINT))])
        self.assertNotIn("parse_mode", payload)
        self.assertEqual(payload["link_preview_options"], {"is_disabled": True})

    def test_other_alerts_and_test_do_not_get_exit_emphasis(self):
        for kind in (*ALERT_KINDS, None):
            if kind == ta.ESCALATION_KIND:
                continue
            with self.subTest(kind=kind):
                event = dict(_dump_event(), kind=kind) if kind else None
                payload = self._payload(event)
                if kind is None:
                    self.assertNotIn("entities", payload)   # test alert polos
                else:
                    self.assertEqual(
                        [e["type"] for e in payload["entities"]],
                        ["text_link", "text_link"])         # tanpa bold
                self.assertNotIn("Reshape", payload["text"])
                self.assertNotIn("parse_mode", payload)
                self.assertEqual(payload["link_preview_options"], {"is_disabled": True})

    def test_untrusted_names_and_mints_remain_literal_not_markup(self):
        mint = 'a<b>&"[_]/?'
        symbol = 'TST<&>_*[]🚀'
        for kind in ALERT_KINDS:
            with self.subTest(kind=kind):
                event = dict(_dump_event(mint), kind=kind, symbol=symbol)
                payload = self._payload(event)
                self.assertIn(f"🪙 ${symbol}", payload["text"])
                self.assertIn(f"📋 Mint: {mint}", payload["text"])
                self.assertIn(("GMGN", gmgn_token_url(mint)),
                              _links(payload["text"], payload["entities"]))
                self.assertNotIn("parse_mode", payload)


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
        self.assertEqual(post.call_args.kwargs["json"], {
            "chat_id": "chat", "text": "hello",
            "link_preview_options": {"is_disabled": True}})
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
