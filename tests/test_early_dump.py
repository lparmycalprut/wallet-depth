"""Rule ⚡ EARLY DUMP: level > 0,1% MC, dedup bucket 15 menit, wiring lp_mints.

Latar belakang (2026-09-04): user ingin peringatan **lebih awal** saat dust
pool Meteora naik di atas 0,1% MC supaya bisa exit LP lebih cepat.
Revisi 2026-09-05 (user): karena watchlist LP di-scan cron tiap **±15 menit**,
rule jadi **level-based** — selama dust masih di atas 0,1% MC, pengingat
dikirim **berulang** (naik, turun sedikit, atau hover sama saja), dibatasi
satu event per bucket 15 menit + cooldown 15 menit. Turun ke ≤ 0,1% MC =
reset otomatis; berhenti bila token dihapus/dipindah dari watchlist LP.
"""
from __future__ import annotations

import unittest
from unittest import mock

import holder_history as hh
import telegram_alerts as ta

NOW = 1_800_000_000
BUCKET = ta.EVENT_BUCKET_SEC          # 4 jam
MINT = "LpMint11111111111111111111111111111111111"
POOL = "PoolAddr11111111111111111111111111111111111"


def _marker(ts, pct):
    return {"ts": ts, "dust_pct_mc": pct}


def _current(ts, pct, *, pools=()):
    return {"ts": ts, "dust_pct_mc": pct,
            "pool_addresses": [p for p in pools]}


def _analysis(mint, symbol, dust_pct, *, analyzed_at=NOW):
    return {
        "ca": mint, "symbol": symbol, "marketcap": 1_000_000.0, "price": 1.0,
        "analyzed_at": analyzed_at,
        "holders": {
            "dust_pct_mc": dust_pct,
            "total_fetched": 120,
            "wallets_analyzed": 120,
            "real_count": 100,
            "dust_count": 20,
            "wallet_snapshot": {"ts": analyzed_at, "dust_pct_mc": dust_pct,
                                "balances": {}, "dust": [], "wallets_seen": 0,
                                "truncated": False},
        },
    }


def _state(early_marker=None, *, sent=(), last_sent=None):
    state = {"sent_event_ids": list(sent), "last_sent": dict(last_sent or {})}
    if early_marker:
        state["early_dump"] = dict(early_marker)
    return state


class EarlyDumpRuleTest(unittest.TestCase):
    """Unit test rule murni: crossing, hysteresis, dedup, cooldown."""

    def test_crossing_dari_005_ke_011_menyala(self):
        events = ta.evaluate_early_dump_rule(
            _marker(NOW - 3600, 0.05), _current(NOW, 0.11),
            mint=MINT, symbol="tst")
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["kind"], "early_dump")
        self.assertEqual(event["mint"], MINT)
        self.assertEqual(event["symbol"], "TST")
        self.assertAlmostEqual(event["previous_dust_pct_mc"], 0.05)
        self.assertAlmostEqual(event["current_dust_pct_mc"], 0.11)
        self.assertAlmostEqual(event["change_pp"], 0.06)
        self.assertEqual(event["direction"], "up")
        self.assertIn("pengingat berulang", event["scope"])

    def test_titik_pertama_tanpa_marker_tidak_langsung_mengirim(self):
        # Token baru dipantau: mustahil membuktikan crossing tanpa titik
        # sebelumnya → cukup rekam marker, jangan mengirim.
        events = ta.evaluate_early_dump_rule(
            None, _current(NOW, 0.3), mint=MINT, symbol="?")
        self.assertEqual(events, [])

    def test_masih_di_bawah_atau_pas_01_tidak_menyala(self):
        for value in (0.05, 0.099, 0.1):
            events = ta.evaluate_early_dump_rule(
                _marker(NOW - 3600, value), _current(NOW, 0.1),
                mint=MINT)
            self.assertEqual(events, [], f"current 0.1 vs previous {value}")

    def test_turun_tapi_masih_di_atas_tetap_mengingatkan(self):
        """Sejak 2026-09-05 rule level-based: selama > 0,1% MC tetap kirim.

        0,2 → 0,15 (turun) dan hover 0,12 → 0,12 tetap mengirim pengingat
        (berulang tiap scan ±15 menit); turun ke ≤ 0,1% MC = reset, tanpa
        notifikasi turun.
        """
        falling = ta.evaluate_early_dump_rule(
            _marker(NOW - 900, 0.2), _current(NOW, 0.15), mint=MINT,
            symbol="tst")
        self.assertEqual(len(falling), 1)
        self.assertGreater(falling[0]["current_dust_pct_mc"],
                           hh.DUST_BEST_PCT)
        hover = ta.evaluate_early_dump_rule(
            _marker(NOW - 900, 0.12), _current(NOW, 0.12), mint=MINT,
            symbol="?")
        self.assertEqual(len(hover), 1)
        # Turun ke <= 0,1% MC: pengingat berhenti (reset otomatis).
        self.assertEqual(ta.evaluate_early_dump_rule(
            _marker(NOW - 900, 0.12), _current(NOW, 0.1), mint=MINT), [])

    def test_satu_event_per_bucket_4_jam(self):
        first = ta.evaluate_early_dump_rule(
            _marker(NOW - 3600, 0.05), _current(NOW, 0.11),
            mint=MINT, symbol="?")
        self.assertEqual(len(first), 1)
        event_id = first[0]["id"]
        # Run berikutnya di bucket yang sama → id sama → dedup.
        again = ta.evaluate_early_dump_rule(
            _marker(NOW, 0.11), _current(NOW + 600, 0.13),
            mint=MINT, symbol="?", sent_event_ids=[event_id])
        self.assertEqual(again, [])
        # Bucket baru (>= 4 jam) + cooldown 1 jam lewat → boleh kirim lagi.
        later = ta.evaluate_early_dump_rule(
            _marker(NOW + 600, 0.13), _current(NOW + BUCKET + 600, 0.20),
            mint=MINT, symbol="?", sent_event_ids=[event_id])
        self.assertEqual(len(later), 1)
        self.assertNotEqual(later[0]["id"], event_id)

    def test_cooldown_15_menit_memblokir_slot_sama(self):
        sent_ts = NOW
        blocked = ta.evaluate_early_dump_rule(
            _marker(sent_ts, 0.15), _current(sent_ts + 10 * 60, 0.25),
            mint=MINT, symbol="?", rejected=[], last_sent={"early_dump": NOW})
        self.assertEqual(blocked, [])
        # Lewat cooldown ±15 menit (dan bucket baru) → boleh kirim lagi.
        later = ta.evaluate_early_dump_rule(
            _marker(sent_ts + 10 * 60, 0.25),
            _current(sent_ts + 16 * 60, 0.30),
            mint=MINT, symbol="?", last_sent={"early_dump": NOW})
        self.assertEqual(len(later), 1)

    def test_tanpa_konteks_pasar_tetap_terkirim_dan_ditandai(self):
        events = ta.evaluate_early_dump_rule(
            _marker(NOW - 3600, 0.05), _current(NOW, 0.11),
            mint=MINT, symbol="?")
        check = events[0]["volume_check"]
        self.assertTrue(check["allow"])          # tanpa gerbang volume
        self.assertFalse(check["verified"])      # data pasar tidak ada
        message = ta.format_alert_message(events[0])
        self.assertIn("TIDAK TERVERIFIKASI", message)

    def test_konteks_pasar_ditampilkan_sebagai_info(self):
        context = {"available": True, "volume_4h": 12_000.0,
                   "avg_volume_7d": 8_000.0, "price_change_pct": -2.5,
                   "buy_pressure": 50, "sell_pressure": 60}
        events = ta.evaluate_early_dump_rule(
            _marker(NOW - 3600, 0.05), _current(NOW, 0.11),
            mint=MINT, symbol="?", market_context=context)
        check = events[0]["volume_check"]
        self.assertTrue(check["verified"])
        self.assertAlmostEqual(check["volume_ratio"], 1.5)
        message = ta.format_alert_message(events[0])
        self.assertIn("volume 4 jam 1.50× rata-rata 7d", message)
        self.assertIn("harga -2.50%", message)
        self.assertIn("(info saja, tanpa gerbang volume)", message)


class EarlyDumpMessageTest(unittest.TestCase):
    """Pesan Telegram kind early_dump: judul, angka, verifikasi, link."""

    def test_judul_dan_field_pokok(self):
        events = ta.evaluate_early_dump_rule(
            _marker(NOW - 7200, 0.04), _current(NOW, 0.42),
            mint=MINT, symbol="LPDUMP")
        message = ta.format_alert_message(events[0])
        self.assertIn("⚡ EARLY DUMP", message)
        self.assertIn("0.1%", message)           # DUST_BEST_PCT 0,1
        self.assertIn("$LPDUMP", message)
        self.assertIn("Dust sebelumnya: 0.04% MC", message)
        self.assertIn("Dust terbaru: 0.42% MC", message)
        self.assertIn("+0.38 poin persentase", message)
        self.assertIn("Periode:", message)
        # Kind baru tetap memakai blok link token (aturan semua jenis alert).
        self.assertIn("🔗 GMGN:", message)
        self.assertIn("🦆 DexScreener:", message)
        # Tanpa movement wallet: marker early dump tidak punya peta balance.
        self.assertNotIn("Pergerakan sampel wallet dust", message)

    def test_link_pool_hanya_bila_pool_address_tersedia(self):
        events = ta.evaluate_early_dump_rule(
            _marker(NOW - 3600, 0.05),
            _current(NOW, 0.11, pools=[POOL]),
            mint=MINT, symbol="?")
        message = ta.format_alert_message(events[0])
        self.assertIn(f"🌊 Meteora: {ta.meteora_dlmm_url(POOL)}", message)
        self.assertIn(f"🦅 HawkFi: {ta.hawkfi_meteora_url(POOL)}", message)
        # Tanpa pool address (kondisi cron saat ini) → tanpa baris pool.
        events = ta.evaluate_early_dump_rule(
            _marker(NOW - 3600, 0.05), _current(NOW, 0.11),
            mint=MINT, symbol="?")
        message = ta.format_alert_message(events[0])
        self.assertNotIn("Meteora:", message)
        self.assertNotIn("HawkFi:", message)

    def test_kind_early_dump_tidak_mengubah_pesan_lama(self):
        dump = {"id": "x", "kind": "dump", "scope": "~4 jam", "mint": MINT,
                "symbol": "DMP", "previous_dust_pct_mc": 1.0,
                "current_dust_pct_mc": 1.4, "change_pp": 0.4,
                "previous_ts": NOW - BUCKET, "current_ts": NOW,
                "wallet_increases": 2, "movements": {}, "volume_check": {}}
        message = ta.format_alert_message(dump)
        self.assertIn("🚨 INDIKASI DUMP", message)
        self.assertIn("Pergerakan sampel wallet dust", message)


class EarlyDumpStateTest(unittest.TestCase):
    """Marker early_dump: compact, summary aman, merger store (backup)."""

    def test_compact_alert_state_menyimpan_marker_ringkas(self):
        state = _state(_marker(NOW, 0.123), sent=["id-1"])
        compact = ta.compact_alert_state(state)
        self.assertEqual(compact["early_dump"],
                         {"ts": NOW, "dust_pct_mc": 0.123})
        # Tanpa marker → {} (tidak mengganggu state lama).
        self.assertEqual(ta.compact_alert_state({})["early_dump"], {})

    def test_alert_state_summary_aman_dengan_marker(self):
        state = _state(_marker(NOW, 0.2))
        summary = ta.alert_state_summary(state)
        self.assertTrue(summary["summary"])
        self.assertEqual(summary["sent_event_ids"], 0)

    def test_merge_stores_marker_early_dump_terbaru_menang(self):
        old = {"updated_at": NOW, "tokens": {MINT: {
            "symbol": "LP", "alert_state": _state(_marker(NOW - 100, 0.05)),
            "points": [], "cohort": {}}}}
        new = {"updated_at": NOW + 60, "tokens": {MINT: {
            "symbol": "LP", "alert_state": _state(_marker(NOW + 60, 0.21)),
            "points": [], "cohort": {}}}}
        merged = hh.merge_stores(old, new)
        marker = merged["tokens"][MINT]["alert_state"]["early_dump"]
        self.assertEqual(marker["ts"], NOW + 60)
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.21)


class EarlyDumpIntegrationTest(unittest.TestCase):
    """Wiring process_holder_alerts: scope lp_mints + persist marker."""

    def test_hanya_token_lp_yang_dievaluasi_dan_marker_direkam(self):
        lp_analysis = _analysis(MINT, "LPT", 0.05)
        non_lp = _analysis("RegMint33333333333333333333333333333333333",
                           "REG", 0.05)
        store = {"tokens": {}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})

        # Run 1: semua masih bersih → tidak ada alert, marker direkam.
        ta.process_holder_alerts(
            {MINT: lp_analysis, "RegMint33333333333333333333333333333333333":
             non_lp}, store, sender=sender, lp_mints={MINT})
        self.assertEqual(sender.call_count, 0)
        lp_state = store["tokens"][MINT]["alert_state"]
        self.assertAlmostEqual(lp_state["early_dump"]["dust_pct_mc"], 0.05)
        reg_state = store["tokens"]["RegMint33333333333333333333333333333333333"][
            "alert_state"]
        self.assertEqual(reg_state.get("early_dump"), {})
        # Run 2 (bucket berbeda): LP menyeberang 0,05 → 0,2 → alert terkirim.
        sender.reset_mock()
        crossing = {MINT: _analysis(MINT, "LPT", 0.2,
                                    analyzed_at=NOW + BUCKET + 60)}
        deliveries = ta.process_holder_alerts(
            crossing, store, sender=sender, lp_mints={MINT})
        self.assertEqual(len(deliveries), 1)
        event = deliveries[0]["event"]
        self.assertEqual(event["kind"], "early_dump")
        # Run 3: non-LP dengan kondisi sama TIDAK boleh mengirim.
        sender.reset_mock()
        reg_crossing = {
            "RegMint33333333333333333333333333333333333":
            _analysis("RegMint33333333333333333333333333333333333", "REG", 0.2,
                      analyzed_at=NOW + 2 * BUCKET)}
        ta.process_holder_alerts(
            reg_crossing, store, sender=sender,
            lp_mints={MINT})
        self.assertEqual(sender.call_count, 0)

    def test_zero_fetch_tidak_menggerakkan_marker(self):
        store = {"tokens": {MINT: {
            "symbol": "LP", "cohort": {}, "points": [],
            "alert_state": _state(_marker(NOW - 3600, 0.05))}}}
        failed = dict(_analysis(MINT, "LPT", 0.0, analyzed_at=NOW))
        failed["holders"]["total_fetched"] = 0
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        ta.process_holder_alerts({MINT: failed}, store, sender=sender,
                                 lp_mints={MINT})
        sender.assert_not_called()
        marker = store["tokens"][MINT]["alert_state"]["early_dump"]
        # Marker TIDAK ditimpa nilai 0,0 dari scan yang gagal.
        self.assertEqual(marker["ts"], NOW - 3600)
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.05)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
