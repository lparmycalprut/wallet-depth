"""Unit coverage for holder-dust Telegram rules, state, and transport.

Rule-nya satu: ⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE (dust naik ≥ 0,02% MC
dari patokan saat token di-add — lihat ``tests/test_early_dump.py``). File ini
menjaga lapisannya yang lain:
snapshot wallet (bahan pembanding kronologi), dedup/cooldown, bentuk state yang
dipersist, format pesan (hyperlink + judul bold), dan transport Telegram.
"""
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


def _snapshot(ts, dust_pct, balances=None, dust=None):
    return {
        "ts": ts,
        "dust_pct_mc": dust_pct,
        "balances": balances or {},
        "dust": dust or [],
        "wallets_seen": len(balances or {}),
        "truncated": False,
    }


def _event_state(previous, *, sent=None, baseline=None, step=0,
                 marker_dust=None):
    """State dengan anchor wallet **dan** marker ⚡ siap berbunyi.

    Patokan ⚡ = angka dust snapshot ``previous``, jadi analisa berikutnya yang
    dust-nya naik ≥ 0,02% langsung menghasilkan satu event (``step`` = langkah
    terakhir yang sudah dikabarkan).
    """
    previous = previous or {}
    dust = previous.get("dust_pct_mc")
    marker = {"ts": previous.get("ts") or NOW - ta.FAST_BUCKET_SEC,
              "dust_pct_mc": dust if marker_dust is None else marker_dust,
              "baseline_pct": dust,
              "baseline_ts": previous.get("ts") or NOW,
              "step": step,
              "baseline_src": "first-scan"}
    return {
        "rolling": previous,
        "baseline": baseline or previous,
        "sent_event_ids": sent or [],
        ta.EARLY_DUMP_MARKER: marker,
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


def _early_dump_event(mint=MINT, *, pct=0.42, baseline=0.07, step=0):
    """Event ⚡ nyata dari rule (bukan dict bikinan tangan).

    ``step=0`` = belum ada langkah 0,02% yang dikabarkan, jadi kenaikan dari
    patokan 0,07% ke ``pct`` (default 0,42%) menghasilkan satu event.
    """
    return ta.evaluate_early_dump_rule(
        {"ts": NOW - ta.FAST_BUCKET_SEC, "dust_pct_mc": baseline,
         "baseline_pct": baseline, "baseline_ts": NOW - FOUR_HOURS,
         "step": step, "baseline_src": "first-scan"},
        {"ts": NOW, "dust_pct_mc": pct},
        mint=mint, symbol="TST")[0]


class WalletSnapshotTest(unittest.TestCase):
    """Peta wallet masih dipersist: dipakai kesinambungan kronologi antar-scan."""

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

    def test_tracked_addresses_union_two_anchors(self):
        state = {"baseline": _snapshot(NOW - FOUR_HOURS, 1.0, {"A": 1.0}),
                 "rolling": _snapshot(NOW, 1.0, {"B": 2.0})}
        self.assertEqual(ta.tracked_wallet_addresses(state), ["A", "B"])

    def test_wallet_movements_counts(self):
        previous = _snapshot(NOW - FOUR_HOURS, 1.0,
                             {"GROW": 2.0, "SOLD": 3.0, "STAY": 2.0},
                             ["GROW", "SOLD", "STAY"])
        current = _snapshot(NOW, 0.5, {"GROW": 20.0, "SOLD": 0.0,
                                       "STAY": 2.0, "NEW": 1.0},
                            ["STAY", "NEW"])
        movement = ta.wallet_movements(previous, current)
        self.assertEqual(movement["dust_grew_out"], 1)
        self.assertEqual(movement["dust_sold_out"], 1)
        self.assertEqual(movement["new_dust"], 1)
        self.assertEqual(movement["increased"], 1)

    def test_four_hour_window_validation(self):
        recent = _snapshot(NOW - 3600, 1.0, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 2.0, {"A": 20.0}, [])
        self.assertFalse(ta.is_valid_4h_snapshot(recent, current))
        aged = _snapshot(NOW - FOUR_HOURS, 1.0, {"A": 10.0}, ["A"])
        self.assertTrue(ta.is_valid_4h_snapshot(aged, current))

    def test_dedup_key_is_the_kind(self):
        self.assertEqual(ta.dedup_key({"kind": ta.EARLY_DUMP_KIND,
                                       "direction": "up"}),
                         ta.EARLY_DUMP_KIND)
        self.assertEqual(ta.dedup_key(None), "")

    def test_resend_cooldown_window(self):
        last = {ta.EARLY_DUMP_KIND: NOW}
        self.assertTrue(ta.in_resend_cooldown(ta.EARLY_DUMP_KIND,
                                              NOW + 60, last))
        self.assertFalse(ta.in_resend_cooldown(
            ta.EARLY_DUMP_KIND, NOW + ta.EARLY_DUMP_RESEND_SEC, last))


class AlertStateTest(unittest.TestCase):
    def test_first_snapshot_seeds_anchors_without_alert(self):
        current = _snapshot(NOW, 0.01, {"A": 10.0}, ["A"])
        events, state = ta.evaluate_alert_events(MINT, _analysis(current), {})
        self.assertEqual(events, [])
        self.assertEqual(state["baseline"]["ts"], NOW)
        self.assertEqual(state["rolling"]["ts"], NOW)

    def test_anchors_not_advanced_when_disabled(self):
        current = _snapshot(NOW, 0.01, {"A": 10.0}, ["A"])
        _events, state = ta.evaluate_alert_events(MINT, _analysis(current), {},
                                                   advance_anchors=False)
        self.assertIsNone(state["baseline"].get("dust_pct_mc"))

    def test_rolling_anchor_only_moves_after_four_hours(self):
        young = _snapshot(NOW - 600, 0.01, {"A": 10.0}, ["A"])
        current = _snapshot(NOW, 0.02, {"A": 9.0}, ["A"])
        _events, state = ta.evaluate_alert_events(
            MINT, _analysis(current), {"rolling": young, "baseline": young})
        self.assertEqual(state["rolling"]["ts"], NOW - 600)

        stale = _snapshot(NOW - 2 * FOUR_HOURS, 0.01, {"A": 10.0}, ["A"])
        _events, state = ta.evaluate_alert_events(
            MINT, _analysis(current), {"rolling": stale, "baseline": stale})
        self.assertEqual(state["rolling"]["ts"], NOW)

    def test_process_records_event_dan_dedup_satu_bucket(self):
        current = _snapshot(NOW, 0.5, {"A": 9.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": _event_state(
            _snapshot(NOW - FOUR_HOURS, 0.1, {"A": 10.0}, ["A"])),
            "points": [], "cohort": {}}}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        first = ta.process_holder_alerts(
            {MINT: _analysis(current)}, store, sender=sender)
        self.assertEqual(len(first), 1)
        self.assertEqual(sender.call_count, 1)
        sent_ids = store["tokens"][MINT]["alert_state"]["sent_event_ids"]
        self.assertEqual(len(sent_ids), 1)

        # Run kedua di bucket yang sama: id sudah tercatat → tidak dobel.
        second = ta.process_holder_alerts(
            {MINT: _analysis(current)}, store, sender=sender)
        self.assertEqual(second, [])
        self.assertEqual(sender.call_count, 1)

    def test_sender_error_never_raises(self):
        current = _snapshot(NOW, 0.5, {"A": 9.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": _event_state(
            _snapshot(NOW - FOUR_HOURS, 0.1, {"A": 10.0}, ["A"]))}}}
        result = ta.process_holder_alerts(
            {MINT: _analysis(current)}, store,
            sender=mock.Mock(side_effect=TimeoutError("late")),
        )
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["delivery"]["ok"])

    def test_zero_holder_provider_failure_does_not_advance_or_alert(self):
        previous = _snapshot(NOW - FOUR_HOURS, 0.5, {"A": 10.0}, ["A"])
        store = {"tokens": {MINT: {"alert_state": _event_state(previous),
                                   "points": [], "cohort": {}}}}
        failed = _analysis(_snapshot(NOW, 0.0, {}, []))
        failed["holders"]["total_fetched"] = 0
        before = deepcopy(store["tokens"][MINT]["alert_state"])
        sender = mock.Mock()
        result = ta.process_holder_alerts({MINT: failed}, store, sender=sender)
        self.assertEqual(result, [])
        self.assertEqual(store["tokens"][MINT]["alert_state"], before)
        sender.assert_not_called()

    def test_compact_bounds_sent_ids_and_last_sent(self):
        state = {"sent_event_ids": [f"id{i}" for i in range(200)],
                 "last_sent": {f"k{i}": NOW + i for i in range(20)},
                 "strategy_shift": {"ts": NOW}, "high_drop": {"ts": NOW},
                 "rejected_signals": [{"kind": "dump"}]}
        compact = ta.compact_alert_state(state)
        self.assertEqual(len(compact["sent_event_ids"]),
                         ta.MAX_SENT_EVENT_IDS)
        self.assertEqual(len(compact["last_sent"]), ta.MAX_LAST_SENT)
        for stale in ("strategy_shift", "high_drop", "rejected_signals"):
            self.assertNotIn(stale, compact)
        self.assertEqual(compact[ta.EARLY_DUMP_MARKER], {})

    def test_delivery_note_mentions_failures(self):
        note = ta.delivery_note(ta.summarize_deliveries([
            {"event": {"kind": ta.EARLY_DUMP_KIND},
             "delivery": {"ok": True}},
            {"event": {"kind": ta.EARLY_DUMP_KIND},
             "delivery": {"ok": False, "muted": True}},
            {"event": {"kind": ta.EARLY_DUMP_KIND},
             "delivery": {"ok": False, "error": "Telegram HTTP 500"}},
        ]))
        self.assertIn("⚡ 1 notifikasi EARLY DUMP TERJADI dikirim", note)
        self.assertIn("1 notifikasi dilewati", note)
        self.assertIn("Telegram HTTP 500", note)
        self.assertEqual(ta.delivery_note({"total": 0}),
                         "Tidak ada notifikasi dari hasil scan ini.")


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

    URL tidak ditulis di teks (permintaan user 2026-09-09 — URL polos 44+
    karakter membuat pesan panjang dan tidak enak dibaca); baris hanya
    ``🔗 GMGN`` dan labelnya diberi entity hyperlink.
    """

    def test_link_gmgn_dan_dexscreener_jadi_hyperlink(self):
        text, entities = ta.build_alert_message(_early_dump_event())
        self.assertIn("\n🔗 GMGN\n", text)
        self.assertTrue(text.endswith("\n🦆 DexScreener"))
        self.assertEqual(_links(text, entities),
                         [("GMGN", gmgn_token_url(MINT)),
                          ("DexScreener", dexscreener_token_url(MINT))])

    def test_url_tidak_ditulis_di_teks(self):
        text, entities = ta.build_alert_message(_early_dump_event())
        self.assertNotIn("http", text)
        self.assertNotIn("gmgn.ai", text)
        self.assertNotIn("dexscreener.com", text)
        self.assertEqual(ta.format_alert_message(_early_dump_event()), text)
        # emoji tidak ikut jadi bagian hyperlink, hanya labelnya
        for entity in entities:
            self.assertNotIn("\U0001f517", _utf16_slice(
                text, entity["offset"], entity["length"]))

    def test_link_muncul_setelah_baris_mint(self):
        text, _ = ta.build_alert_message(_early_dump_event())
        self.assertLess(text.index("Mint:"), text.index("GMGN"))

    def test_tanpa_mint_tidak_ada_link_menggantung(self):
        text, entities = ta.build_alert_message(_early_dump_event(mint=""))
        self.assertIn("Mint: -", text)
        self.assertTrue(text.endswith("Mint: -"))
        self.assertNotIn("GMGN", text)
        self.assertNotIn("DexScreener", text)
        self.assertEqual([e for e in entities if e["type"] == "text_link"], [])

    def test_mint_berbahaya_diencode_di_url_entity(self):
        text, entities = ta.build_alert_message(_early_dump_event(mint="a?b&c d#e"))
        for _, url in _links(text, entities):
            self.assertIn("a%3Fb%26c%20d%23e", url)
            self.assertNotIn(" ", url)
        # mint mentah tetap literal di baris Mint (bukan markup)
        self.assertIn("📋 Mint: a?b&c d#e", text)

    def test_offset_utf16_tepat_walau_symbol_dan_mint_beremoji(self):
        event = dict(_early_dump_event(mint="M🚀int" + "x" * 20), symbol="TST🚀🚀")
        text, entities = ta.build_alert_message(event)
        labels = [label for label, _ in _links(text, entities)]
        self.assertEqual(labels, ["GMGN", "DexScreener"])

    def test_robinhood_links_dipakai_untuk_ca_evm(self):
        mint = "0x" + "aB" * 20
        text, entities = ta.build_alert_message(_early_dump_event(mint))
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

    def test_alert_test_tetap_tanpa_link_token(self):
        with mock.patch.object(ta, "send_telegram_message",
                               return_value={"ok": True}) as send:
            ta.send_test_alert()
        text = send.call_args.args[0]
        self.assertIn("TEST ALERT", text)
        self.assertNotIn("gmgn.ai", text)
        self.assertIn("WIB", text)
        self.assertNotIn("UTC", text)


class FormatTest(unittest.TestCase):
    def test_pesan_ringkas_tanpa_blok_pergerakan_wallet(self):
        message = ta.format_alert_message(_early_dump_event())
        self.assertNotIn("Pergerakan sampel wallet dust", message)
        # Tidak ada lagi baris verifikasi volume/gerbang — rule-nya dihapus.
        self.assertNotIn("TIDAK TERVERIFIKASI", message)
        self.assertNotIn("terkonfirmasi", message)
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
                mock.patch.object(ta.requests, "post",
                                  return_value=response) as post:
            result = (ta.send_test_alert() if event is None
                      else ta.send_telegram_alert(event))
        self.assertTrue(result["ok"])
        post.assert_called_once()
        return post.call_args.kwargs["json"]

    def test_judul_early_dump_ditebalkan_utf16(self):
        event = _early_dump_event()
        payload = self._payload(event)
        title = "⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE"
        self.assertEqual(title, ta.EARLY_DUMP_TITLE)
        self.assertTrue(payload["text"].startswith(title + "\n\n🪙"))
        self.assertEqual(payload["text"], ta.format_alert_message(event))
        length = len(title.encode("utf-16-le")) // 2
        # ⚡ (U+26A1) masih satu unit UTF-16, jadi panjang entity = len(title).
        self.assertEqual(length, len(title))
        bold = [e for e in payload["entities"] if e["type"] == "bold"]
        self.assertEqual(bold, [{"type": "bold", "offset": 0, "length": length}])
        marked = (payload["text"].encode("utf-16-le")[:length * 2]
                  .decode("utf-16-le"))
        self.assertEqual(marked, title)  # Detail token tidak ikut tebal.
        self.assertEqual(_links(payload["text"], payload["entities"]),
                         [("GMGN", gmgn_token_url(MINT)),
                          ("DexScreener", dexscreener_token_url(MINT))])
        self.assertNotIn("parse_mode", payload)
        self.assertEqual(payload["link_preview_options"], {"is_disabled": True})

    def test_untrusted_names_and_mints_remain_literal_not_markup(self):
        mint = 'a<b>&"[_]/?'
        symbol = 'TST<&>_*[]🚀'
        payload = self._payload(dict(_early_dump_event(mint), symbol=symbol))
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
