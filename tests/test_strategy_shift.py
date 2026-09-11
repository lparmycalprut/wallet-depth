"""Rule 🚨 WAKTUNYA GANTI STRATEGI — satu-satunya notifikasi sejak 2026-09-11.

Permintaan user: *"buat 1 notifikasi lagi — jika %dust di atas ≥ 0,06 kasih
notif WAKTUNYA GANTI STRATEGI — hapus notif lainnya."* Karena itu:

- rule ini **level-based**: tiap evaluasi selama ``dust % MC`` masih
  **≥ 0,06%** mengirim pengingat (dibatasi satu event per bucket 5 menit +
  cooldown 5 menit, sama seperti ritme scan cron LP);
- ``< 0,06%`` = marker dihapus (episode berikutnya mulai dari nol) dan
  **tidak** ada notifikasi "sudah aman";
- rule lama (⚡ EARLY DUMP, 🔔 HIGH DROP, 🚨 EXIT/CUTLOSS, ✅ KEMBALI KE
  TITIK AMAN, dump/akumulasi 4 jam, baseline shift) sudah dihapus — tesnya
  ikut hilang bersama rule-nya.
"""
from __future__ import annotations

import unittest
from unittest import mock

import holder_history as hh
import telegram_alerts as ta

NOW = 1_800_000_000
BUCKET = ta.FAST_BUCKET_SEC              # 5 menit
MINT = "LpMint11111111111111111111111111111111111"
POOL = "PoolAddr11111111111111111111111111111111111"


def _marker(ts, pct, since=None):
    out = {"ts": ts, "dust_pct_mc": pct}
    if since:
        out["since_ts"] = since
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
        state[ta.STRATEGY_SHIFT_MARKER] = dict(marker)
    return state


class ThresholdTest(unittest.TestCase):
    """Ambang 0,06% MC: `>=` menyala, di bawahnya diam."""

    def test_ambang_memakai_dua_desimal_tepat_di_atas_listing_filter(self):
        self.assertEqual(ta.STRATEGY_SHIFT_PCT, 0.06)
        # Sengaja DI ATAS ambang tampil listing scan best (0,05% MC), supaya
        # token yang baru masuk listing tidak langsung berbunyi.
        import meteora_screener
        import robinhood_best_scan
        self.assertGreater(ta.STRATEGY_SHIFT_PCT,
                           meteora_screener.BEST_DUST_MAX_PCT)
        self.assertGreater(ta.STRATEGY_SHIFT_PCT,
                           robinhood_best_scan.RH_SCAN_MAX_DUST_PCT)

    def test_pas_di_ambang_mengirim(self):
        events = ta.evaluate_strategy_shift_rule(
            None, _current(NOW, 0.06), mint=MINT, symbol="tst")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], ta.STRATEGY_SHIFT_KIND)
        self.assertEqual(events[0]["symbol"], "TST")
        self.assertAlmostEqual(events[0]["threshold_pct"], 0.06)
        self.assertIn("pertama kali terpantau", events[0]["scope"])

    def test_di_bawah_ambang_diam(self):
        for value in (0.0, 0.04, 0.05, 0.0599):
            with self.subTest(pct=value):
                self.assertEqual(ta.evaluate_strategy_shift_rule(
                    _marker(NOW - BUCKET, 0.10), _current(NOW, value),
                    mint=MINT), [])

    def test_dust_none_tidak_mengapa_napa(self):
        self.assertEqual(ta.evaluate_strategy_shift_rule(
            None, _current(NOW, None), mint=MINT), [])

    def test_level_based_turun_di_atas_ambang_tetap_mengingatkan(self):
        """Naik, hover, atau turun sedikit — selama ≥ 0,06% tetap dikirim."""
        falling = ta.evaluate_strategy_shift_rule(
            _marker(NOW - BUCKET, 0.20, since=NOW - 6 * BUCKET),
            _current(NOW, 0.15), mint=MINT, symbol="tst")
        self.assertEqual(len(falling), 1)
        self.assertAlmostEqual(falling[0]["change_pp"], -0.05)
        self.assertIn("pengingat berulang", falling[0]["scope"])
        # durasi episode dibawa ke pesan (baris ⏱️): NOW-6*bucket → 30 menit
        self.assertEqual(falling[0]["minutes_above"], 30)

    def test_id_unik_per_bucket_lima_menit(self):
        first = ta.evaluate_strategy_shift_rule(
            None, _current(NOW, 0.10), mint=MINT)[0]
        same_bucket = ta.evaluate_strategy_shift_rule(
            _marker(NOW, 0.10), _current(NOW + 60, 0.13), mint=MINT,
            sent_event_ids=[first["id"]])
        self.assertEqual(same_bucket, [])
        later = ta.evaluate_strategy_shift_rule(
            _marker(NOW + 60, 0.13), _current(NOW + BUCKET + 60, 0.20),
            mint=MINT, sent_event_ids=[first["id"]])[0]
        self.assertNotEqual(later["id"], first["id"])

    def test_cooldown_lima_menit_memblokir_run_ganda(self):
        blocked = ta.evaluate_strategy_shift_rule(
            _marker(NOW, 0.10), _current(NOW + 2 * 60, 0.25), mint=MINT,
            last_sent={ta.STRATEGY_SHIFT_KIND: NOW})
        self.assertEqual(blocked, [])
        later = ta.evaluate_strategy_shift_rule(
            _marker(NOW + 2 * 60, 0.25), _current(NOW + 6 * 60, 0.30),
            mint=MINT, last_sent={ta.STRATEGY_SHIFT_KIND: NOW})
        self.assertEqual(len(later), 1)


class MarkerTest(unittest.TestCase):
    def test_marker_digeser_ke_angka_run_terakhir(self):
        marker = ta.strategy_shift_marker_next(
            _marker(NOW - BUCKET, 0.09, since=NOW - 4 * BUCKET),
            _current(NOW, 0.11))
        self.assertEqual(marker["ts"], NOW)
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.11)
        # since_ts episode lama DIPERTAHANKAN (untuk baris ⏱️ di pesan).
        self.assertEqual(marker["since_ts"], NOW - 4 * BUCKET)

    def test_di_bawah_ambang_marker_kosong(self):
        self.assertEqual(ta.strategy_shift_marker_next(
            _marker(NOW, 0.2), _current(NOW + BUCKET, 0.03)), {})

    def test_episode_baru_memulai_since_ts(self):
        marker = ta.strategy_shift_marker_next(
            _marker(NOW - BUCKET, 0.04), _current(NOW, 0.08))
        self.assertEqual(marker["since_ts"], NOW)


class MessageTest(unittest.TestCase):
    def test_judul_dan_angka_pokok(self):
        event = ta.evaluate_strategy_shift_rule(
            _marker(NOW - BUCKET, 0.07), _current(NOW, 0.42),
            mint=MINT, symbol="LPDUMP")[0]
        message = ta.format_alert_message(event)
        self.assertTrue(message.startswith(ta.STRATEGY_SHIFT_TITLE + "\n"))
        self.assertIn("🚨 WAKTUNYA GANTI STRATEGI", message)
        self.assertIn("$LPDUMP", message)
        self.assertIn("📊 Dust: 0.070% → 0.420% MC (+0.350 pp) · ambang ≥ 0.06%",
                      message)
        self.assertIn(MINT, message)
        self.assertIn("WIB", message)
        self.assertNotIn("UTC", message)

    def test_observasi_pertua_tanpa_angka_pembanding(self):
        event = ta.evaluate_strategy_shift_rule(
            None, _current(NOW, 0.08), mint=MINT, symbol="X")[0]
        message = ta.format_alert_message(event)
        self.assertIn("📊 Dust: 0.080% MC — baru melewati ambang ≥ 0.06%",
                      message)
        self.assertNotIn("0.000% →", message)
        # Episode baru → tidak ada baris durasi.
        self.assertNotIn("menit di atas ambang", message)

    def test_judul_ditebalkan_dan_link_jadi_hyperlink(self):
        event = ta.evaluate_strategy_shift_rule(
            None, _current(NOW, 0.07), mint=MINT, symbol="X")[0]
        text, entities = ta.build_alert_message(event)
        bold = [e for e in entities if e["type"] == "bold"]
        self.assertEqual(len(bold), 1)
        self.assertEqual(bold[0]["offset"], 0)
        self.assertEqual(bold[0]["length"], ta._utf16_len(ta.STRATEGY_SHIFT_TITLE))
        self.assertNotIn("http", text)
        self.assertTrue(text.endswith("🔗 GMGN\n🦆 DexScreener"))

    def test_baris_pasar_hanya_bila_konteks_ada(self):
        event = ta.evaluate_strategy_shift_rule(
            None, _current(NOW, 0.07), mint=MINT, symbol="X")[0]
        self.assertNotIn("📈 Pasar", ta.format_alert_message(event))
        with_context = ta.evaluate_strategy_shift_rule(
            None, _current(NOW, 0.07), mint=MINT, symbol="X",
            market_context={"volume_4h": 12_000.0, "avg_volume_7d": 6_000.0,
                            "price_change_pct": -2.5})[0]
        self.assertEqual(with_context["market"]["volume_ratio"], 2.0)
        self.assertIn("📈 Pasar: vol 4j 2.00× avg 7d · harga -2.50%",
                      ta.format_alert_message(with_context))

    def test_link_pool_bila_pool_address_ada(self):
        event = ta.evaluate_strategy_shift_rule(
            None, _current(NOW, 0.07, pools=[POOL]), mint=MINT,
            symbol="X")[0]
        message, entities = ta.build_alert_message(event)
        self.assertTrue(message.endswith("\n🌊 Meteora\n🦅 HawkFi"))
        links = [e for e in entities if e.get("type") == "text_link"]
        self.assertEqual([e["url"] for e in links][-2:],
                         [ta.meteora_dlmm_url(POOL), ta.hawkfi_meteora_url(POOL)])


class PipelineTest(unittest.TestCase):
    """Wiring ``process_holder_alerts`` untuk semua lane yang di-scan."""

    def test_semua_token_dievaluasi_tanpa_scope_flag(self):
        store = {"tokens": {}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        ta.process_holder_alerts({MINT: _analysis(MINT, "LPT", 0.02)}, store,
                                 sender=sender)
        self.assertEqual(sender.call_count, 0)
        # Run 2 (bucket baru) → dust naik ke 0,2 → satu notifikasi.
        deliveries = ta.process_holder_alerts(
            {MINT: _analysis(MINT, "LPT", 0.2, analyzed_at=NOW + BUCKET + 60)},
            store, sender=sender)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["event"]["kind"],
                         ta.STRATEGY_SHIFT_KIND)
        state = store["tokens"][MINT]["alert_state"]
        self.assertAlmostEqual(state[ta.STRATEGY_SHIFT_MARKER]["dust_pct_mc"],
                               0.2)
        self.assertEqual(len(state["sent_event_ids"]), 1)

    def test_dust_turun_di_bawah_ambang_menghapus_marker(self):
        store = {"tokens": {MINT: {"symbol": "LPT", "cohort": {},
                                   "points": [],
                                   "alert_state": _state(_marker(
                                       NOW, 0.30, since=NOW))}}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        ta.process_holder_alerts(
            {MINT: _analysis(MINT, "LPT", 0.01,
                             analyzed_at=NOW + BUCKET + 60)}, store,
            sender=sender)
        self.assertEqual(sender.call_count, 0)
        self.assertEqual(
            store["tokens"][MINT]["alert_state"][ta.STRATEGY_SHIFT_MARKER], {})

    def test_mute_hanya_menghambat_pengiriman(self):
        store = {"tokens": {}}
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        deliveries = ta.process_holder_alerts(
            {MINT: _analysis(MINT, "REG", 0.09)}, store, sender=sender,
            mute_mints={MINT})
        self.assertEqual(len(deliveries), 1)
        self.assertTrue(deliveries[0]["delivery"]["muted"])
        sender.assert_not_called()
        # marker tetap dimajukan supaya menyalakan notif lagi tidak bingung
        self.assertAlmostEqual(
            store["tokens"][MINT]["alert_state"][
                ta.STRATEGY_SHIFT_MARKER]["dust_pct_mc"], 0.09)

    def test_zero_fetch_tidak_menggerakkan_marker(self):
        store = {"tokens": {MINT: {
            "symbol": "LP", "cohort": {}, "points": [],
            "alert_state": _state(_marker(NOW - 3600, 0.05))}}}
        failed = _analysis(MINT, "LPT", 0.0, analyzed_at=NOW)
        failed["holders"]["total_fetched"] = 0
        sender = mock.Mock(return_value={"ok": True, "skipped": False})
        ta.process_holder_alerts({MINT: failed}, store, sender=sender)
        sender.assert_not_called()
        marker = store["tokens"][MINT]["alert_state"][
            ta.STRATEGY_SHIFT_MARKER]
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

    def test_compact_hanya_menulis_marker_baru(self):
        state = _state(_marker(NOW, 0.123, since=NOW - 600), sent=["id-1"])
        state["early_dump"] = {"ts": NOW}
        state["high_drop"] = {"ts": NOW, "high": 1.0}
        state["rejected_signals"] = [{"kind": "dump"}]
        compact = ta.compact_alert_state(state)
        self.assertEqual(compact[ta.STRATEGY_SHIFT_MARKER]["ts"], NOW)
        self.assertAlmostEqual(
            compact[ta.STRATEGY_SHIFT_MARKER]["dust_pct_mc"], 0.123)
        self.assertEqual(compact[ta.STRATEGY_SHIFT_MARKER]["since_ts"],
                         NOW - 600)
        for stale in ("early_dump", "high_drop", "rejected_signals"):
            self.assertNotIn(stale, compact)
        self.assertEqual(ta.compact_alert_state({})[ta.STRATEGY_SHIFT_MARKER],
                         {})

    def test_summary_tanpa_peta_wallet(self):
        summary = ta.alert_state_summary(_state(_marker(NOW, 0.2)))
        self.assertTrue(summary["summary"])
        self.assertEqual(summary["sent_event_ids"], 0)
        self.assertEqual(summary[ta.STRATEGY_SHIFT_MARKER]["ts"], NOW)
        self.assertNotIn("rejected_signals", summary)

    def test_merge_stores_marker_terbaru_menang(self):
        old = {"updated_at": NOW, "tokens": {MINT: {
            "symbol": "LP", "alert_state": _state(_marker(NOW - 100, 0.05)),
            "points": [], "cohort": {}}}}
        new = {"updated_at": NOW + 60, "tokens": {MINT: {
            "symbol": "LP",
            "alert_state": _state(_marker(NOW + 60, 0.21, since=NOW - 900)),
            "points": [], "cohort": {}}}}
        merged = hh.merge_stores(old, new)
        marker = merged["tokens"][MINT]["alert_state"][
            ta.STRATEGY_SHIFT_MARKER]
        self.assertEqual(marker["ts"], NOW + 60)
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.21)

    def test_marker_dibersihkan_bila_token_dimasuk_ulang(self):
        """Marker lama dari periode watchlist sebelumnya tidak dipakai lagi."""
        state = _state(_marker(NOW - 10, 0.5, since=NOW - 10))
        cleared = ta._reset_markers_on_readd(state, {"added": NOW})
        self.assertEqual(cleared[ta.STRATEGY_SHIFT_MARKER], {})
        # Marker yang LEBIH BARU dari tanggal ``added`` tetap dipertahankan.
        kept = ta._reset_markers_on_readd(_state(_marker(NOW, 0.5)),
                                         {"added": NOW - 10})
        self.assertAlmostEqual(
            kept[ta.STRATEGY_SHIFT_MARKER]["dust_pct_mc"], 0.5)


class NoLegacyRulesTest(unittest.TestCase):
    """Rule lama benar-benar hilang dari modul (bukan sekadar mati)."""

    def test_nama_rule_lama_tidak_ada_lagi(self):
        for name in ("evaluate_early_dump_rule", "evaluate_high_drop_rule",
                     "evaluate_4h_rules", "evaluate_baseline_rule",
                     "evaluate_episode_rules", "validate_alert_with_volume",
                     "volume_verdict", "escalation_due", "safe_return_due"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(ta, name))

    def test_proses_flag_lama_ditolak(self):
        # ``lp_mints``/``high_mints``/``volume_rules`` hilang: penerusan lama
        # harus gagal keras, bukan diam-diam mengabaikan scope.
        with self.assertRaises(TypeError):
            ta.process_holder_alerts({}, {"tokens": {}}, lp_mints=set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
