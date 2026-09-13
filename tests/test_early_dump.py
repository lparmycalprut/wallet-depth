"""Rule ⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE — satu-satunya notifikasi.

Permintaan user 2026-09-13: *"notifikasi telegram akan muncul ketika %dust naik
0,02%, jadi sekarang bukan ambang batas, tapi notif berulang ketika dust
bertambah 0,02% dari pertama add watchlist"* + judul baru *"EARLY DUMP TERJADI
- GANTI WIDE RANGE"*. Karena itu:

- **delta, bukan ambang**: patokan = angka dust saat token masuk watchlist
  (``marker["baseline_pct"]``, boleh dari history lewat ``baseline_hint``),
  dan tiap kelipatan 0,02% kenaikan mengirim pesan;
- **berulang**: 0,02% pertama → 1 pesan, 0,02% berikutnya → pesan lagi
  (``marker["step"]`` monoton; turun lalu naik ke level yang sudah dikabarkan
  tidak mengirim ulang);
- evaluasi yang **memasang patokan** tidak mengirim pesan (tanpa hint) supaya
  token lama tidak membanjiri Telegram saat rule dipasang;
- rule lama (🚨 WAKTUNYA GANTI STRATEGI level-based 0,06% MC, 🔔 HIGH DROP,
  🚨 EXIT/CUTLOSS, ✅ KEMBALI KE TITIK AMAN, dump/akumulasi 4 jam, baseline
  shift) sudah dihapus — tesnya ikut hilang bersama rule-nya.
"""
from __future__ import annotations

import unittest
from unittest import mock

import holder_history as hh
import telegram_alerts as ta

NOW = 1_800_000_000
BUCKET = ta.FAST_BUCKET_SEC              # 5 menit
STEP = ta.EARLY_DUMP_STEP_PCT            # 0,02% MC
MINT = "LpMint11111111111111111111111111111111111"
POOL = "PoolAddr11111111111111111111111111111111111"


def _marker(ts, pct, *, baseline=None, baseline_ts=None, step=None):
    """Marker ⚡ seperti yang ditulis ``early_dump_marker_next``."""
    out = {"ts": ts, "dust_pct_mc": pct}
    if baseline is not None:
        out["baseline_pct"] = baseline
    if baseline_ts is not None:
        out["baseline_ts"] = baseline_ts
    if step is not None:
        out["step"] = step
    return out


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


def _state(marker=None, *, sent=(), last_sent=None):
    state = {"sent_event_ids": list(sent), "last_sent": dict(last_sent or {})}
    if marker:
        state[ta.EARLY_DUMP_MARKER] = dict(marker)
    return state


class StepTest(unittest.TestCase):
    """Patokan + langkah 0,02%: kapan berbunyi, kapan diam."""

    def test_langkah_dua_persen_mc(self):
        self.assertAlmostEqual(ta.EARLY_DUMP_STEP_PCT, 0.02)
        self.assertEqual(ta.EARLY_DUMP_TITLE,
                         "⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE")

    def test_patokan_dipasang_tanpa_notifikasi(self):
        """Marker kosong = evaluasi pertama hanya memasang patokan."""
        events = ta.evaluate_early_dump_rule(None, _current(NOW, 0.012),
                                             mint=MINT, symbol="tst")
        self.assertEqual(events, [])
        marker = ta.early_dump_marker_next(None, _current(NOW, 0.012))
        self.assertAlmostEqual(marker["baseline_pct"], 0.012)
        self.assertEqual(marker["baseline_ts"], NOW)
        self.assertEqual(marker["step"], 0)
        self.assertEqual(marker["baseline_src"], "first-scan")

    def test_naik_kurang_dari_langkah_diam(self):
        marker = _marker(NOW - BUCKET, 0.017, baseline=0.012, baseline_ts=NOW)
        self.assertEqual(ta.evaluate_early_dump_rule(
            marker, _current(NOW, 0.0319), mint=MINT), [])

    def test_naik_satu_langkah_mengirim(self):
        marker = _marker(NOW - BUCKET, 0.017, baseline=0.012, baseline_ts=NOW)
        events = ta.evaluate_early_dump_rule(marker, _current(NOW, 0.032),
                                             mint=MINT, symbol="tst")
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["kind"], ta.EARLY_DUMP_KIND)
        self.assertEqual(event["symbol"], "TST")
        self.assertEqual(event["step"], 1)
        self.assertAlmostEqual(event["previous_dust_pct_mc"], 0.012)
        self.assertAlmostEqual(event["current_dust_pct_mc"], 0.032)
        self.assertAlmostEqual(event["change_pp"], 0.020)
        self.assertAlmostEqual(event["step_pct"], STEP)

    def test_langkah_berikutnya_berbunyi_lagi(self):
        """Notif berulang: tiap kelipatan 0,02% dari patokan."""
        marker = _marker(NOW - BUCKET, 0.033, baseline=0.012, baseline_ts=NOW,
                         step=1)
        events = ta.evaluate_early_dump_rule(marker, _current(NOW, 0.055),
                                             mint=MINT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["step"], 2)
        self.assertAlmostEqual(events[0]["change_pp"], 0.043)

    def test_langkah_yang_sudah_dikabarkan_tidak_diulang(self):
        marker = _marker(NOW - BUCKET, 0.033, baseline=0.012, baseline_ts=NOW,
                         step=1)
        self.assertEqual(ta.evaluate_early_dump_rule(
            marker, _current(NOW, 0.033), mint=MINT), [])
        self.assertEqual(ta.evaluate_early_dump_rule(
            marker, _current(NOW, 0.040), mint=MINT), [])

    def test_lompatan_beberapa_langkah_satu_pesan(self):
        marker = _marker(NOW - BUCKET, 0.013, baseline=0.012, baseline_ts=NOW)
        events = ta.evaluate_early_dump_rule(marker, _current(NOW, 0.071),
                                             mint=MINT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["step"], 2)

    def test_turun_lalu_naik_lagi_tidak_mengulang(self):
        """Langkah = high water mark, dihitung dari patokan (bukan antar-scan)."""
        marker = _marker(NOW, 0.055, baseline=0.012, baseline_ts=NOW, step=2)
        lowered = ta.early_dump_marker_next(marker, _current(NOW + BUCKET, 0.04))
        self.assertEqual(lowered["step"], 2)
        self.assertAlmostEqual(lowered["baseline_pct"], 0.012)
        self.assertEqual(ta.evaluate_early_dump_rule(
            lowered, _current(NOW + 2 * BUCKET, 0.05), mint=MINT), [])
        # Naik lagi melewati langkah ke-3 → berbunyi.
        events = ta.evaluate_early_dump_rule(
            lowered, _current(NOW + 2 * BUCKET, 0.072), mint=MINT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["step"], 3)

    def test_dust_none_tidak_mengapa_napa(self):
        self.assertEqual(ta.evaluate_early_dump_rule(
            _marker(NOW, 0.05, baseline=0.01), _current(NOW, None),
            mint=MINT), [])
        self.assertEqual(ta.early_dump_marker_next(
            _marker(NOW, 0.05, baseline=0.01), _current(NOW, None)), {})

    def test_id_unik_per_bucket_lima_menit(self):
        marker = _marker(NOW, 0.013, baseline=0.012, baseline_ts=NOW)
        first = ta.evaluate_early_dump_rule(marker, _current(NOW, 0.041),
                                            mint=MINT)[0]
        same_bucket = ta.evaluate_early_dump_rule(
            marker, _current(NOW + 60, 0.041), mint=MINT,
            sent_event_ids=[first["id"]])
        self.assertEqual(same_bucket, [])
        later = ta.evaluate_early_dump_rule(
            marker, _current(NOW + BUCKET + 60, 0.062), mint=MINT,
            sent_event_ids=[first["id"]])[0]
        self.assertNotEqual(later["id"], first["id"])

    def test_cooldown_lima_menit_memblokir_run_ganda(self):
        marker = _marker(NOW, 0.013, baseline=0.012, baseline_ts=NOW)
        blocked = ta.evaluate_early_dump_rule(
            marker, _current(NOW + 2 * 60, 0.035), mint=MINT,
            last_sent={ta.EARLY_DUMP_KIND: NOW})
        self.assertEqual(blocked, [])
        later = ta.evaluate_early_dump_rule(
            marker, _current(NOW + 6 * 60, 0.035), mint=MINT,
            last_sent={ta.EARLY_DUMP_KIND: NOW})
        self.assertEqual(len(later), 1)


class BaselineHintTest(unittest.TestCase):
    """Patokan dari history = angka dust saat token **pertama** di-add."""

    def test_hint_dipakai_dan_langsung_mengabarkan_kenaikan(self):
        hint = (0.010, NOW - 3600, "history")
        events = ta.evaluate_early_dump_rule(
            None, _current(NOW, 0.035), mint=MINT, symbol="tst",
            baseline_hint=hint)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["step"], 1)
        self.assertAlmostEqual(events[0]["previous_dust_pct_mc"], 0.010)
        self.assertEqual(events[0]["baseline_ts"], NOW - 3600)
        self.assertEqual(events[0]["minutes_since_baseline"], 60)
        marker = ta.early_dump_marker_next(None, _current(NOW, 0.035),
                                           baseline_hint=hint)
        self.assertAlmostEqual(marker["baseline_pct"], 0.010)
        self.assertEqual(marker["baseline_ts"], NOW - 3600)
        self.assertEqual(marker["step"], 1)
        self.assertEqual(marker["baseline_src"], "history")

    def test_hint_yang_sudah_naik_banyak_tidak_mengirim_banjir(self):
        """Satu pesan, bukan satu per langkah yang sudah terlewat."""
        hint = (0.010, NOW - 7200, "history")
        events = ta.evaluate_early_dump_rule(
            None, _current(NOW, 0.093), mint=MINT, baseline_hint=hint)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["step"], 4)

    def test_hint_tidak_menimpa_patokan_yang_sudah_ada(self):
        marker = _marker(NOW - BUCKET, 0.02, baseline=0.015, baseline_ts=NOW,
                         step=0)
        events = ta.evaluate_early_dump_rule(
            marker, _current(NOW, 0.036), mint=MINT,
            baseline_hint=(0.001, NOW - 99999, "history"))
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["previous_dust_pct_mc"], 0.015)
        marker_next = ta.early_dump_marker_next(
            marker, _current(NOW, 0.036),
            baseline_hint=(0.001, NOW - 99999, "history"))
        self.assertAlmostEqual(marker_next["baseline_pct"], 0.015)

    def test_add_baseline_for_mint_memilih_titik_paling_awal_setelah_add(self):
        store = {"tokens": {MINT: {"points": [
            {"ts": NOW - 3600, "dust_pct_mc": 0.005, "holder_count": 200},
            {"ts": NOW - 1800, "dust_pct_mc": 0.011, "holder_count": 200},
            {"ts": NOW - 900, "dust_pct_mc": 0.013, "holder_count": 200},
        ]}}}
        hint = ta.add_baseline_for_mint(store, MINT, {"added": NOW - 2000})
        self.assertAlmostEqual(hint[0], 0.011)
        self.assertEqual(hint[1], NOW - 1800)
        self.assertEqual(hint[2], "history")

    def test_add_baseline_for_mint_menolak_scan_yang_tidak_layak(self):
        store = {"tokens": {MINT: {"points": [
            # Titik gagal (0 wallet) dan titik tanpa angka dust harus dilewati.
            {"ts": NOW - 1800, "dust_pct_mc": 0.011, "holder_count": 0,
             "degraded": True},
            {"ts": NOW - 900, "holder_count": 200},
        ]}}}
        self.assertIsNone(ta.add_baseline_for_mint(store, MINT,
                                                   {"added": NOW - 2000}))
        # Tanpa tanggal add / tanpa token di store → tidak ada patokan.
        self.assertIsNone(ta.add_baseline_for_mint(store, MINT, {}))
        self.assertIsNone(ta.add_baseline_for_mint(store, "Lain",
                                                   {"added": NOW - 2000}))


class MessageTest(unittest.TestCase):
    def _event(self, **kwargs):
        hint = kwargs.pop("hint", None)
        current = kwargs.pop("current", _current(NOW, 0.036))
        return ta.evaluate_early_dump_rule(
            kwargs.pop("marker", _marker(NOW - BUCKET, 0.017, baseline=0.012,
                                         baseline_ts=NOW - 600)),
            current, mint=MINT, symbol="LPDUMP", baseline_hint=hint, **kwargs)[0]

    def test_judul_dan_angka_pokok(self):
        message = ta.format_alert_message(self._event())
        self.assertTrue(message.startswith(ta.EARLY_DUMP_TITLE + "\n"))
        self.assertIn("⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE", message)
        self.assertIn("$LPDUMP", message)
        self.assertIn("📊 Dust: 0.012% → 0.036% MC "
                      "(+0.024 pp · langkah 1× 0.02%)", message)
        self.assertIn("⏱️ 10 menit sejak masuk watchlist", message)
        self.assertIn(MINT, message)
        self.assertIn("WIB", message)
        self.assertNotIn("UTC", message)

    def test_tanpa_patokan_waktu_tidak_ada_baris_menit(self):
        marker = _marker(NOW - BUCKET, 0.017, baseline=0.012)
        message = ta.format_alert_message(self._event(marker=marker))
        self.assertNotIn("menit sejak masuk watchlist", message)

    def test_judul_ditebalkan_dan_link_jadi_hyperlink(self):
        text, entities = ta.build_alert_message(self._event())
        bold = [e for e in entities if e["type"] == "bold"]
        self.assertEqual(len(bold), 1)
        self.assertEqual(bold[0]["offset"], 0)
        self.assertEqual(bold[0]["length"],
                         ta._utf16_len(ta.EARLY_DUMP_TITLE))
        self.assertNotIn("http", text)
        self.assertTrue(text.endswith("🔗 GMGN\n🦆 DexScreener"))

    def test_baris_pasar_hanya_bila_konteks_ada(self):
        event = self._event()
        self.assertNotIn("📈 Pasar", ta.format_alert_message(event))
        with_context = self._event(market_context={
            "volume_4h": 12_000.0, "avg_volume_7d": 6_000.0,
            "price_change_pct": -2.5})
        self.assertEqual(with_context["market"]["volume_ratio"], 2.0)
        self.assertIn("📈 Pasar: vol 4j 2.00× avg 7d · harga -2.50%",
                      ta.format_alert_message(with_context))

    def test_link_pool_bila_pool_address_ada(self):
        event = self._event(current=_current(NOW, 0.036, pools=[POOL]))
        message, entities = ta.build_alert_message(event)
        self.assertTrue(message.endswith("\n🌊 Meteora\n🦅 HawkFi"))
        links = [e for e in entities if e.get("type") == "text_link"]
        self.assertEqual([e["url"] for e in links][-2:],
                         [ta.meteora_dlmm_url(POOL), ta.hawkfi_meteora_url(POOL)])


class PipelineTest(unittest.TestCase):
    """Wiring ``process_holder_alerts`` untuk semua lane yang di-scan."""

    def test_patokan_lalu_langkah_berikutnya_dikirim(self):
        store = {"tokens": {}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        # Run 1: patokan dipasang, belum ada pesan.
        ta.process_holder_alerts({MINT: _analysis(MINT, "LPT", 0.012)}, store,
                                 sender=sender)
        self.assertEqual(sender.call_count, 0)
        marker = store["tokens"][MINT]["alert_state"][ta.EARLY_DUMP_MARKER]
        self.assertAlmostEqual(marker["baseline_pct"], 0.012)
        self.assertEqual(marker["step"], 0)
        # Run 2 (bucket baru) → dust naik 0,021 → satu notifikasi.
        deliveries = ta.process_holder_alerts(
            {MINT: _analysis(MINT, "LPT", 0.033, analyzed_at=NOW + BUCKET + 60)},
            store, sender=sender)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["event"]["kind"], ta.EARLY_DUMP_KIND)
        state = store["tokens"][MINT]["alert_state"]
        self.assertEqual(state[ta.EARLY_DUMP_MARKER]["step"], 1)
        self.assertAlmostEqual(state[ta.EARLY_DUMP_MARKER]["baseline_pct"], 0.012)
        self.assertEqual(len(state["sent_event_ids"]), 1)

    def test_patokan_dari_history_dipakai_saat_watchlist_meta_ada(self):
        store = {"tokens": {MINT: {"symbol": "LPT", "cohort": {}, "points": [
            {"ts": NOW - 3600, "dust_pct_mc": 0.008, "holder_count": 150},
        ]}}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {MINT: _analysis(MINT, "LPT", 0.031)}, store, sender=sender,
            watchlist_meta={MINT: {"added": NOW - 7200}})
        self.assertEqual(len(deliveries), 1)
        event = deliveries[0]["event"]
        self.assertAlmostEqual(event["previous_dust_pct_mc"], 0.008)
        self.assertEqual(event["step"], 1)
        marker = store["tokens"][MINT]["alert_state"][ta.EARLY_DUMP_MARKER]
        self.assertAlmostEqual(marker["baseline_pct"], 0.008)
        self.assertEqual(marker["baseline_src"], "history")

    def test_langkah_tidak_dimakan_saat_pengiriman_gagal(self):
        """Telegram down ≠ langkah 0,02% hilang: dicoba lagi scan berikutnya."""
        store = {"tokens": {MINT: {
            "symbol": "LPT", "cohort": {}, "points": [],
            "alert_state": _state(_marker(NOW - BUCKET, 0.013,
                                          baseline=0.012, baseline_ts=NOW,
                                          step=0))}}}
        failing = mock.Mock(return_value={"ok": False, "skipped": False,
                                          "error": "Telegram HTTP 500"})
        deliveries = ta.process_holder_alerts(
            {MINT: _analysis(MINT, "LPT", 0.033)}, store, sender=failing)
        self.assertEqual(len(deliveries), 1)
        marker = store["tokens"][MINT]["alert_state"][ta.EARLY_DUMP_MARKER]
        self.assertEqual(marker["step"], 0)          # langkah belum dimakan
        self.assertAlmostEqual(marker["baseline_pct"], 0.012)
        # Scan berikutnya (bucket baru) mengirim ulang langkah yang sama.
        ok = mock.Mock(return_value={"ok": True, "skipped": False})
        again = ta.process_holder_alerts(
            {MINT: _analysis(MINT, "LPT", 0.033,
                             analyzed_at=NOW + BUCKET + 60)}, store, sender=ok)
        self.assertEqual(len(again), 1)
        self.assertEqual(
            store["tokens"][MINT]["alert_state"][ta.EARLY_DUMP_MARKER]["step"], 1)

    def test_mute_hanya_menghambat_pengiriman(self):
        store = {"tokens": {MINT: {
            "symbol": "LPT", "cohort": {}, "points": [],
            "alert_state": _state(_marker(NOW - BUCKET, 0.013,
                                          baseline=0.012, baseline_ts=NOW,
                                          step=0))}}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {MINT: _analysis(MINT, "LPT", 0.033)}, store, sender=sender,
            mute_mints={MINT})
        self.assertEqual(len(deliveries), 1)
        self.assertTrue(deliveries[0]["delivery"]["muted"])
        sender.assert_not_called()
        # Marker tetap dimajukan supaya menyalakan notif lagi tidak bingung.
        marker = store["tokens"][MINT]["alert_state"][ta.EARLY_DUMP_MARKER]
        self.assertEqual(marker["step"], 1)
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.033)

    def test_zero_fetch_tidak_menggerakkan_marker(self):
        store = {"tokens": {MINT: {
            "symbol": "LPT", "cohort": {}, "points": [],
            "alert_state": _state(_marker(NOW - 3600, 0.05, baseline=0.01,
                                          baseline_ts=NOW - 3600, step=2))}}}
        failed = _analysis(MINT, "LPT", 0.0, analyzed_at=NOW)
        failed["holders"]["total_fetched"] = 0
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        ta.process_holder_alerts({MINT: failed}, store, sender=sender)
        sender.assert_not_called()
        marker = store["tokens"][MINT]["alert_state"][ta.EARLY_DUMP_MARKER]
        # Marker TIDAK ditimpa nilai 0,0 dari scan yang gagal.
        self.assertEqual(marker["ts"], NOW - 3600)
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.05)

    def test_advance_anchors_false_tidak_menggeser_peta_wallet(self):
        store = {"tokens": {}}
        ta.process_holder_alerts({MINT: _analysis(MINT, "LPT", 0.02)}, store,
                                 sender=mock.Mock(return_value={"ok": True}),
                                 advance_anchors=False)
        state = store["tokens"][MINT]["alert_state"]
        # Anchor TIDAK diisi snapshot run ini (dust_pct_mc tetap None).
        self.assertIsNone(state["baseline"].get("dust_pct_mc"))
        self.assertIsNone(state["rolling"].get("dust_pct_mc"))


class StateShapeTest(unittest.TestCase):
    """Tidak ada jejak rule lama di state yang dipersist."""

    def test_compact_menulis_marker_lengkap(self):
        state = _state(_marker(NOW, 0.043, baseline=0.012, baseline_ts=NOW - 900,
                               step=2), sent=["id-1"])
        state["baseline_pct"] = 0.5          # sisa field rule lama (tidak ada)
        state["strategy_shift"] = {"ts": NOW, "dust_pct_mc": 0.2}
        state["high_drop"] = {"ts": NOW, "high": 1.0}
        state["rejected_signals"] = [{"kind": "dump"}]
        compact = ta.compact_alert_state(state)
        marker = compact[ta.EARLY_DUMP_MARKER]
        self.assertEqual(marker["ts"], NOW)
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.043)
        self.assertAlmostEqual(marker["baseline_pct"], 0.012)
        self.assertEqual(marker["baseline_ts"], NOW - 900)
        self.assertEqual(marker["step"], 2)
        for stale in ("strategy_shift", "high_drop", "rejected_signals",
                      "baseline_pct"):
            self.assertNotIn(stale, compact)
        self.assertEqual(ta.compact_alert_state({})[ta.EARLY_DUMP_MARKER], {})

    def test_marker_tanpa_patokan_tetap_ringkas_dan_aman(self):
        compact = ta.compact_alert_state(_state(_marker(NOW, 0.02)))
        marker = compact[ta.EARLY_DUMP_MARKER]
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.02)
        self.assertIsNone(marker["baseline_pct"])
        self.assertEqual(marker["step"], 0)

    def test_summary_tanpa_peta_wallet(self):
        summary = ta.alert_state_summary(
            _state(_marker(NOW, 0.043, baseline=0.012, baseline_ts=NOW - 900,
                           step=2)))
        self.assertTrue(summary["summary"])
        self.assertEqual(summary["sent_event_ids"], 0)
        marker = summary[ta.EARLY_DUMP_MARKER]
        self.assertEqual(marker["ts"], NOW)
        self.assertAlmostEqual(marker["baseline_pct"], 0.012)
        self.assertEqual(marker["step"], 2)
        self.assertNotIn("rejected_signals", summary)

    def test_summary_bisa_melanjutkan_episode_di_run_berikutnya(self):
        """Snapshot status dipakai runner ephemeral: patokan harus ikut."""
        summary = ta.alert_state_summary(
            _state(_marker(NOW, 0.033, baseline=0.012, baseline_ts=NOW - 600,
                           step=1)))
        events = ta.evaluate_early_dump_rule(
            summary[ta.EARLY_DUMP_MARKER], _current(NOW + BUCKET, 0.033),
            mint=MINT)
        self.assertEqual(events, [])
        events = ta.evaluate_early_dump_rule(
            summary[ta.EARLY_DUMP_MARKER], _current(NOW + BUCKET, 0.055),
            mint=MINT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["step"], 2)

    def test_merge_stores_marker_terbaru_menang(self):
        old = {"updated_at": NOW, "tokens": {MINT: {
            "symbol": "LP",
            "alert_state": _state(_marker(NOW - 100, 0.02, baseline=0.01,
                                          baseline_ts=NOW - 100, step=1)),
            "points": [], "cohort": {}}}}
        new = {"updated_at": NOW + 60, "tokens": {MINT: {
            "symbol": "LP",
            "alert_state": _state(_marker(NOW + 60, 0.05, baseline=0.01,
                                          baseline_ts=NOW - 100, step=2)),
            "points": [], "cohort": {}}}}
        merged = hh.merge_stores(old, new)
        marker = merged["tokens"][MINT]["alert_state"][ta.EARLY_DUMP_MARKER]
        self.assertEqual(marker["ts"], NOW + 60)
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.05)
        self.assertEqual(marker["step"], 2)

    def test_marker_dibersihkan_bila_token_dimasuk_ulang(self):
        """Patokan lama dari periode watchlist sebelumnya tidak dipakai lagi."""
        state = _state(_marker(NOW - 10, 0.5, baseline=0.01,
                               baseline_ts=NOW - 10, step=3))
        cleared = ta._reset_markers_on_readd(state, {"added": NOW})
        self.assertEqual(cleared[ta.EARLY_DUMP_MARKER], {})
        # Marker yang LEBIH BARU dari tanggal ``added`` tetap dipertahankan.
        kept = ta._reset_markers_on_readd(
            _state(_marker(NOW, 0.5, baseline=0.01)), {"added": NOW - 10})
        self.assertAlmostEqual(
            kept[ta.EARLY_DUMP_MARKER]["dust_pct_mc"], 0.5)


class NoLegacyRulesTest(unittest.TestCase):
    """Rule lama benar-benar hilang dari modul (bukan sekadar mati)."""

    def test_nama_rule_lama_tidak_ada_lagi(self):
        # ``evaluate_early_dump_rule`` TIDAK ada di daftar ini: nama itu kembali
        # 2026-09-13 dengan arti baru (delta 0,02% dari patokan watchlist),
        # menggantikan rule crossing > 0,1% MC yang dihapus 2026-09-11.
        for name in ("evaluate_strategy_shift_rule", "strategy_shift_marker_next",
                     "evaluate_high_drop_rule", "evaluate_4h_rules",
                     "evaluate_baseline_rule", "evaluate_episode_rules",
                     "validate_alert_with_volume", "volume_verdict",
                     "escalation_due", "safe_return_due"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(ta, name))

    def test_proses_flag_lama_ditolak(self):
        # ``lp_mints``/``high_mints``/``volume_rules`` hilang: penerusan lama
        # harus gagal keras, bukan diam-diam mengabaikan scope.
        with self.assertRaises(TypeError):
            ta.process_holder_alerts({}, {"tokens": {}}, lp_mints=set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
