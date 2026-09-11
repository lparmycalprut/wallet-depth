"""Integrasi: scan → notifikasi 🚨 (+konteks pasar lazy) → holder_status.json.

Rule-nya satu sejak 2026-09-11 (dust ≥ 0,06% MC → 🚨 WAKTUNYA GANTI STRATEGI).
Yang dijaga file ini adalah **sambungan** antar-lapisan: konteks pasar hanya
ditarik untuk token yang benar-benar dinotifikasi (lazy), angka itu mendarat di
pesan sebagai satu baris info, dan konteks yang sama ditulis
``holder_status`` sebagai ``market_signal`` per token.
"""
from __future__ import annotations

import unittest
from unittest import mock

import alert_context as ac
import holder_status as hs
import telegram_alerts as ta

NOW = 1_800_000_000
FOUR_HOURS = 4 * 3600
HOT_MINT = "HotMint111111111111111111111111111111111111"
QUIET_MINT = "QuietMint222222222222222222222222222222222"

# Empat jam terakhir: volume 4× baseline dan harga turun → konteks "ramai".
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


class LazyFetchTest(unittest.TestCase):
    def test_hanya_token_di_atas_ambang_yang_menarik_konteks(self):
        fetcher = mock.Mock(side_effect=lambda pair, hours: candles())
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=fetcher, daily_loader=lambda: [],
            now=NOW)
        analyses = {
            # dust 0,42% MC → ≥ 0,06% → notifikasi → konteks ditarik
            HOT_MINT: analysis(HOT_MINT, "HOT", 0.42),
            # dust 0,02% MC → di bawah ambang → tidak boleh menarik apa pun
            QUIET_MINT: analysis(QUIET_MINT, "QET", 0.02),
        }
        store = {"tokens": {}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            analyses, store, sender=sender, context_provider=provider)

        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["event"]["mint"], HOT_MINT)
        self.assertEqual(fetcher.call_count, 1)
        self.assertEqual(fetcher.call_args.args[0], f"PAIR{HOT_MINT[:6]}")
        self.assertEqual(fetcher.call_args.args[1], ac.BASELINE_HOURS)
        self.assertIn(HOT_MINT, provider.cache)
        self.assertNotIn(QUIET_MINT, provider.cache)

    def test_konteks_pasar_jadi_baris_info_di_pesan(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=candles()),
            daily_loader=lambda: [], now=NOW)
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {HOT_MINT: analysis(HOT_MINT, "HOT", 0.42)}, {"tokens": {}},
            sender=sender, context_provider=provider)
        event = deliveries[0]["event"]
        # Bukan gerbang: verdict lama (allow/confidence_score) sudah hilang…
        self.assertNotIn("volume_check", event)
        # …tapi angkanya tetap dibawa sebagai pelengkap pesan.
        self.assertAlmostEqual(event["market"]["volume_ratio"], 3.73, places=2)
        self.assertLess(event["market"]["price_change_pct"], 0)
        message = ta.format_alert_message(event)
        self.assertIn("📈 Pasar: vol 4j 3.73× avg 7d · harga -6.00%", message)
        self.assertNotIn("Skor konfirmasi:", message)
        self.assertNotIn("TIDAK TERVERIFIKASI", message)

    def test_volume_sepi_tidak_lagi_membungkam_notifikasi(self):
        """Gerbang volume DIHAPUS — dust di atas ambang selalu diberitahu."""
        flat = candles([(1.0, 1_000.0)] * 4)
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=flat),
            daily_loader=lambda: [], now=NOW)
        store = {"tokens": {}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {HOT_MINT: analysis(HOT_MINT, "HOT", 0.42)}, store,
            sender=sender, context_provider=provider)
        self.assertEqual(len(deliveries), 1)
        sender.assert_called_once()
        # Dulu sinyal seperti ini masuk ``rejected_signals``; auditnya hilang
        # bersama gerbangnya.
        state = store["tokens"][HOT_MINT]["alert_state"]
        self.assertNotIn("rejected_signals", state)

    def test_tanpa_data_pasar_notif_tetap_terkirim(self):
        bare = analysis(HOT_MINT, "HOT", 0.42,
                        market={"pair_addresses": [], "volume": {},
                                "price_change": {}, "txns": {}})
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=[]),
            daily_loader=lambda: [], now=NOW)
        store = {"tokens": {}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {HOT_MINT: bare}, store, sender=sender, context_provider=provider)
        self.assertEqual(len(deliveries), 1)
        event = deliveries[0]["event"]
        # Tidak ada angka volume/harga yang bisa dipercaya → baris pasar
        # tidak dicetak (dilarang mengarang angka di notifikasi).
        self.assertIsNone((event.get("market") or {}).get("volume_ratio"))
        self.assertIsNone((event.get("market") or {}).get("price_change_pct"))
        message = ta.format_alert_message(event)
        self.assertIn("🚨 WAKTUNYA GANTI STRATEGI", message)
        self.assertNotIn("📈 Pasar", message)
        # State hanya marker rule ini — tidak ada sisa rule lama.
        state = store["tokens"][HOT_MINT]["alert_state"]
        self.assertNotIn("rejected_signals", state)
        self.assertIn("strategy_shift", state)


class StatusStorageTest(unittest.TestCase):
    def tearDown(self):
        hs.reset_cache()

    def test_volatility_is_stored_alongside_dust_percentage(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=candles()),
            daily_loader=lambda: [], now=NOW)
        analyses = {HOT_MINT: analysis(HOT_MINT, "HOT", 1.30),
                    QUIET_MINT: analysis(QUIET_MINT, "QET", 0.02)}
        store = {"tokens": {}}
        ta.process_holder_alerts(
            analyses, store, context_provider=provider,
            sender=mock.Mock(return_value={"ok": True, "skipped": False}))
        status = hs.snapshot_status(analyses, {HOT_MINT: {"symbol": "HOT"},
                                               QUIET_MINT: {"symbol": "QET"}},
                                    history_store=store,
                                    contexts=provider.cache)
        dumped = status["tokens"][HOT_MINT]
        self.assertAlmostEqual(dumped["holders"]["dust_pct_mc"], 1.30)
        signal = dumped["market_signal"]
        self.assertEqual(signal["volume_4h"], 16_000.0)
        self.assertAlmostEqual(signal["volume_ratio_7d"], 3.7333, places=3)
        self.assertIsNotNone(signal["price_stddev_4h"])
        self.assertIsNotNone(signal["intra_hour_volatility"])
        self.assertTrue(signal["volatility_available"])
        self.assertEqual(signal["volume_source"], "geckoterminal_hourly")
        # Token di bawah ambang tidak menarik konteks → tidak punya sinyal.
        self.assertNotIn("market_signal", status["tokens"][QUIET_MINT])

    def test_status_survives_a_context_from_the_analysis_payload(self):
        item = analysis(HOT_MINT, "HOT", 1.30)
        item["market_context"] = ac.build_market_context(
            HOT_MINT, item, hourly=candles(), daily_rows=[], now=NOW,
            fetch=False)
        status = hs.snapshot_status({HOT_MINT: item}, {},
                                    history_store={"tokens": {}})
        self.assertEqual(status["tokens"][HOT_MINT]["market_signal"]
                         ["volume_source"], "geckoterminal_hourly")

    def test_publish_passes_contexts_through(self):
        provider = ac.market_context_provider(
            cache={}, hourly_fetcher=mock.Mock(return_value=candles()),
            daily_loader=lambda: [], now=NOW)
        provider(HOT_MINT, analysis(HOT_MINT, "HOT", 1.30))
        with mock.patch.object(hs, "atomic_write_json") as write, \
                mock.patch.object(hs, "_github_token", return_value=""):
            status = hs.publish_holder_status(
                {HOT_MINT: analysis(HOT_MINT, "HOT", 1.30)}, {},
                push=False, history_store={"tokens": {}},
                contexts=provider.cache)
        self.assertIn("market_signal", status["tokens"][HOT_MINT])
        self.assertEqual(write.call_args.args[1], status)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
