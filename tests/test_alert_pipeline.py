"""Integrasi: scan → konfirmasi volume lazy → alert → holder_status.json."""
from __future__ import annotations

import unittest
from unittest import mock

import alert_context as ac
import holder_status as hs
import telegram_alerts as ta

NOW = 1_800_000_000
FOUR_HOURS = 4 * 3600
DUMP_MINT = "DumpMint111111111111111111111111111111111"
QUIET_MINT = "QuietMint222222222222222222222222222222222"

# Empat jam terakhir: volume 4× baseline dan harga turun → dump terkonfirmasi.
CONFIRMING_TAIL = [(0.99, 4_000.0), (0.97, 4_000.0), (0.95, 4_000.0),
                   (0.94, 4_000.0)]


def candles(tail=CONFIRMING_TAIL, *, hours=168, base_volume=1_000.0,
            base_price=1.0):
    prefix = max(0, hours - len(tail))
    rows = [{"ts": NOW - 3600 * (hours - 1 - index), "open": base_price,
             "high": base_price * 1.01, "low": base_price * 0.99,
             "close": base_price, "volume_usd": base_volume}
            for index in range(prefix)]
    previous = base_price
    for index, (close, volume) in enumerate(tail):
        rows.append({"ts": NOW - 3600 * (len(tail) - 1 - index),
                     "open": previous,
                     "high": max(previous, close) * 1.01,
                     "low": min(previous, close) * 0.99,
                     "close": close, "volume_usd": volume})
        previous = close
    return rows


def analysis(mint, symbol, dust_pct, *, market=None):
    snapshot = {"ts": NOW, "dust_pct_mc": dust_pct,
                "balances": {"A": 100.0 - dust_pct}, "dust": ["A"],
                "wallets_seen": 1, "truncated": False}
    return {
        "ca": mint, "symbol": symbol, "marketcap": 1_000_000.0, "price": 0.94,
        "analyzed_at": NOW,
        "holders": {"dust_pct_mc": dust_pct, "total_fetched": 40,
                    "dust_count": 12, "real_count": 28,
                    "wallet_snapshot": snapshot},
        "market": market if market is not None else {
            "price_usd": 0.94, "marketcap": 1_000_000.0,
            "volume": {"h1": 900, "h6": 5_400, "h24": 24_000},
            "price_change": {"h1": -1.2, "h6": -3.4, "h24": -8.0},
            "txns": {"h6": {"buys": 40, "sells": 120}},
            "pair_addresses": [f"PAIR{mint[:6]}"],
        },
    }


def store_with_anchors(mint, previous_dust):
    rolling = {"ts": NOW - FOUR_HOURS, "dust_pct_mc": previous_dust,
               "balances": {"A": 99.0}, "dust": ["A"], "wallets_seen": 1,
               "truncated": False}
    return {"tokens": {mint: {"symbol": "TST", "cohort": {}, "points": [],
                              "alert_state": {
                                  "baseline": rolling, "rolling": rolling,
                                  "sent_event_ids": []}}}}


class LazyFetchTest(unittest.TestCase):
    def test_only_tokens_with_a_candidate_pull_market_context(self):
        fetcher = mock.Mock(side_effect=lambda pair, hours: candles())
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=fetcher, daily_loader=lambda: [],
            now=NOW)
        analyses = {
            # dust +0,30 pp → kandidat dump → konteks ditarik
            DUMP_MINT: analysis(DUMP_MINT, "DMP", 1.30),
            # dust +0,05 pp → di bawah ambang → tidak boleh menarik apa pun
            QUIET_MINT: analysis(QUIET_MINT, "QET", 1.05),
        }
        store = {"tokens": {}}
        for mint, item in analyses.items():
            store["tokens"].update(store_with_anchors(mint, 1.00)["tokens"])
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            analyses, store, sender=sender, context_provider=provider)

        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["event"]["mint"], DUMP_MINT)
        self.assertEqual(fetcher.call_count, 1)
        self.assertEqual(fetcher.call_args.args[0], f"PAIR{DUMP_MINT[:6]}")
        self.assertEqual(fetcher.call_args.args[1], ac.BASELINE_HOURS)
        self.assertIn(DUMP_MINT, provider.cache)
        self.assertNotIn(QUIET_MINT, provider.cache)

    def test_confirmed_dump_is_delivered_with_verification(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=candles()),
            daily_loader=lambda: [], now=NOW)
        store = store_with_anchors(DUMP_MINT, 1.00)
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {DUMP_MINT: analysis(DUMP_MINT, "DMP", 1.30)}, store,
            sender=sender, context_provider=provider)
        event = deliveries[0]["event"]
        check = event["volume_check"]
        self.assertTrue(check["verified"])
        self.assertTrue(check["allow"])
        self.assertEqual(check["volume_source"], "geckoterminal_hourly")
        self.assertAlmostEqual(check["volume_ratio"], 3.7333, places=3)
        self.assertLess(check["price_change_pct"], 0)
        message = ta.format_alert_message(event)
        self.assertIn("Verifikasi volume: ✅", message)
        self.assertIn("Skor konfirmasi:", message)

    def test_quiet_volume_rejects_the_signal_and_records_the_reason(self):
        flat = candles([(1.0, 1_000.0)] * 4)
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=flat),
            daily_loader=lambda: [], now=NOW)
        store = store_with_anchors(DUMP_MINT, 1.00)
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {DUMP_MINT: analysis(DUMP_MINT, "DMP", 1.30)}, store,
            sender=sender, context_provider=provider)
        self.assertEqual(deliveries, [])
        sender.assert_not_called()
        rejected = store["tokens"][DUMP_MINT]["alert_state"]["rejected_signals"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["kind"], "dump")
        self.assertTrue(rejected[0]["verified"])   # datanya ada, sinyalnya lemah
        self.assertIn("1.00x", rejected[0]["reason"])

    def test_candle_outage_falls_back_to_dexscreener_and_still_verifies(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=[]),
            daily_loader=lambda: [], now=NOW)
        store = store_with_anchors(DUMP_MINT, 1.00)
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {DUMP_MINT: analysis(DUMP_MINT, "DMP", 1.30)}, store,
            sender=sender, context_provider=provider)
        context = provider.cache[DUMP_MINT]
        self.assertEqual(context["volume_source"], "dexscreener_h6_scaled")
        self.assertIsNone(context["volatility"])
        # h6 5.400 → 3.600 per 4 jam vs baseline h24 24.000/6 = 4.000 → 0,90×
        # → terverifikasi tapi lemah, jadi tetap ditolak (bukan "tidak tahu").
        self.assertEqual(deliveries, [])
        rejected = store["tokens"][DUMP_MINT]["alert_state"]["rejected_signals"]
        self.assertTrue(rejected[0]["verified"])
        self.assertIn("0.90x", rejected[0]["reason"])

    def test_no_market_data_anywhere_still_alerts_as_unverified(self):
        bare = analysis(DUMP_MINT, "DMP", 1.30,
                        market={"pair_addresses": [], "volume": {},
                                "price_change": {}, "txns": {}})
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=[]),
            daily_loader=lambda: [], now=NOW)
        store = store_with_anchors(DUMP_MINT, 1.00)
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {DUMP_MINT: bare}, store, sender=sender, context_provider=provider)
        self.assertEqual(len(deliveries), 1)
        self.assertFalse(deliveries[0]["event"]["volume_check"]["verified"])
        self.assertIn("TIDAK TERVERIFIKASI",
                      ta.format_alert_message(deliveries[0]["event"]))


class StatusStorageTest(unittest.TestCase):
    def tearDown(self):
        hs.reset_cache()

    def test_volatility_is_stored_alongside_dust_percentage(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=candles()),
            daily_loader=lambda: [], now=NOW)
        analyses = {DUMP_MINT: analysis(DUMP_MINT, "DMP", 1.30),
                    QUIET_MINT: analysis(QUIET_MINT, "QET", 1.05)}
        store = {"tokens": {}}
        for mint in analyses:
            store["tokens"].update(store_with_anchors(mint, 1.00)["tokens"])
        ta.process_holder_alerts(
            analyses, store, context_provider=provider,
            sender=mock.Mock(return_value={"ok": True, "skipped": False}))
        status = hs.snapshot_status(analyses, {DUMP_MINT: {"symbol": "DMP"},
                                               QUIET_MINT: {"symbol": "QET"}},
                                    history_store=store,
                                    contexts=provider.cache)
        dumped = status["tokens"][DUMP_MINT]
        self.assertAlmostEqual(dumped["holders"]["dust_pct_mc"], 1.30)
        signal = dumped["market_signal"]
        self.assertEqual(signal["volume_4h"], 16_000.0)
        self.assertAlmostEqual(signal["volume_ratio_7d"], 3.7333, places=3)
        self.assertIsNotNone(signal["price_stddev_4h"])
        self.assertIsNotNone(signal["intra_hour_volatility"])
        self.assertTrue(signal["volatility_available"])
        self.assertEqual(signal["volume_source"], "geckoterminal_hourly")
        # Token tanpa kandidat tidak menarik konteks → tidak punya sinyal.
        self.assertNotIn("market_signal", status["tokens"][QUIET_MINT])

    def test_status_survives_a_context_from_the_analysis_payload(self):
        item = analysis(DUMP_MINT, "DMP", 1.30)
        item["market_context"] = ac.build_market_context(
            DUMP_MINT, item, hourly=candles(), daily_rows=[], now=NOW,
            fetch=False)
        status = hs.snapshot_status({DUMP_MINT: item}, {},
                                    history_store={"tokens": {}})
        self.assertEqual(status["tokens"][DUMP_MINT]["market_signal"]
                         ["volume_source"], "geckoterminal_hourly")

    def test_publish_passes_contexts_through(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=candles()),
            daily_loader=lambda: [], now=NOW)
        provider(DUMP_MINT, analysis(DUMP_MINT, "DMP", 1.30))
        with mock.patch.object(hs, "atomic_write_json") as write, \
                mock.patch.object(hs, "_github_token", return_value=""):
            status = hs.publish_holder_status(
                {DUMP_MINT: analysis(DUMP_MINT, "DMP", 1.30)}, {},
                push=False, history_store={"tokens": {}},
                contexts=provider.cache)
        self.assertIn("market_signal", status["tokens"][DUMP_MINT])
        self.assertEqual(write.call_args.args[1], status)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
