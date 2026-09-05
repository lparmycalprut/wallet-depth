"""Rule 🔔 HIGH DROP (watchlist biasa): turun ≥ 50% dari **titik high**.

Permintaan user 2026-09-05: titik acuan alert watchlist biasa (selain
Meteora/Robinhood LP) bukan lagi snapshot awal, melainkan **hold % MC
terbesar** yang pernah tercatat. Bila dust % MC turun ≥ 50%
(:data:`telegram_alerts.HIGH_DROP_RATIO`) dari titik high itu, alert
Telegram dikirim **satu kali per titik high**; naik ke titik high baru
atau keluar dari zona drop me-re-arm (bisa mengirim lagi).
"""
from __future__ import annotations

import unittest

import telegram_alerts as ta

NOW = 1_800_000_000
MINT = "RegMint11111111111111111111111111111111111"


def _current(ts, pct):
    return {"ts": ts, "dust_pct_mc": pct}


def _marker(high, *, ts=NOW - 3600, notified=0.0):
    return {"ts": ts, "high": high, "high_ts": ts, "notified_high": notified}


class HighDropMarkerNextTest(unittest.TestCase):
    """Transisi marker ``(high, high_ts, notified_high)`` murni."""

    def test_marker_kosong_menjadi_high_pertama(self):
        marker = ta.high_drop_marker_next(None, _current(NOW, 0.4),
                                          emitted=False)
        self.assertEqual(marker, {"ts": NOW, "high": 0.4, "high_ts": NOW,
                                  "notified_high": 0.0})

    def test_naik_ke_high_baru_rearm(self):
        next_marker = ta.high_drop_marker_next(
            _marker(0.4, notified=0.4), _current(NOW, 0.8), emitted=False)
        self.assertEqual(next_marker["high"], 0.8)
        self.assertEqual(next_marker["high_ts"], NOW)
        # high baru → boleh mengirim lagi untuk high berikutnya.
        self.assertEqual(next_marker["notified_high"], 0.0)

    def test_nilai_di_luar_zona_mengembalikan_notified(self):
        # high 0.4, zona drop = 0.2; 0.3 masih di atas zona → notified
        # di-nol-kan supaya penurunan berikutnya ke dalam zona mengirim.
        next_marker = ta.high_drop_marker_next(
            _marker(0.4, notified=0.4), _current(NOW, 0.3), emitted=False)
        self.assertEqual(next_marker["high"], 0.4)
        self.assertEqual(next_marker["notified_high"], 0.0)

    def test_event_terkirim_mengunci_high(self):
        next_marker = ta.high_drop_marker_next(
            _marker(0.4), _current(NOW, 0.15), emitted=True)
        self.assertEqual(next_marker["notified_high"], 0.4)

    def test_nilai_kosong_memertahankan_marker(self):
        marker = _marker(0.4, notified=0.4)
        self.assertEqual(
            ta.high_drop_marker_next(marker, _current(NOW + 60, None),
                                     emitted=False),
            marker)


class HighDropRuleTest(unittest.TestCase):
    """Rule murni: zona drop, satu alert per titik high, re-arm, cooldown."""

    def test_tanpa_marker_tidak_mengirim(self):
        # Token belum pernah discan: high belum ada → tidak ada alert.
        self.assertEqual(ta.evaluate_high_drop_rule(
            None, _current(NOW, 0.1), mint=MINT), [])

    def test_belum_turun_50_persen_tidak_mengirim(self):
        # zona drop = 0.4 * 0.5 = 0.2; 0.25 masih di atas zona → tenang.
        self.assertEqual(ta.evaluate_high_drop_rule(
            _marker(0.4), _current(NOW, 0.25), mint=MINT), [])

    def test_turun_50_persen_dari_titik_high_mengirim(self):
        events = ta.evaluate_high_drop_rule(
            _marker(0.4), _current(NOW, 0.2), mint=MINT, symbol="reg")
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["kind"], "high_drop")
        self.assertEqual(event["direction"], "down")
        self.assertAlmostEqual(event["previous_dust_pct_mc"], 0.4)
        self.assertAlmostEqual(event["current_dust_pct_mc"], 0.2)
        self.assertAlmostEqual(event["drop_pct"], 50.0)
        self.assertIn("titik high", event["scope"])

    def test_satu_alert_per_titik_high(self):
        # ``notified_high`` = high ini sudah pernah diberitahu → hening.
        self.assertEqual(ta.evaluate_high_drop_rule(
            _marker(0.4, notified=0.4), _current(NOW, 0.2), mint=MINT), [])

    def test_naik_ke_titik_high_baru_bisa_mengirim_lagi(self):
        # high 0.4 sudah notified → naik ke 0.8 (re-arm) → turun ke 0.4
        # (≥50% dari 0.8) mengirim lagi.
        rearm = ta.high_drop_marker_next(
            _marker(0.4, notified=0.4), _current(NOW - 3600, 0.8),
            emitted=False)
        events = ta.evaluate_high_drop_rule(rearm, _current(NOW, 0.4),
                                            mint=MINT)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["previous_dust_pct_mc"], 0.8)

    def test_keluar_zona_lalu_turun_lagi_mengirim_ulang(self):
        rearm = ta.high_drop_marker_next(
            _marker(0.4, notified=0.4), _current(NOW - 3600, 0.35),
            emitted=False)
        self.assertEqual(rearm["notified_high"], 0.0)
        events = ta.evaluate_high_drop_rule(rearm, _current(NOW, 0.15),
                                            mint=MINT)
        self.assertEqual(len(events), 1)

    def test_dedup_sent_event_ids(self):
        events = ta.evaluate_high_drop_rule(_marker(0.4), _current(NOW, 0.2),
                                            mint=MINT)
        self.assertEqual(len(events), 1)
        again = ta.evaluate_high_drop_rule(
            _marker(0.4), _current(NOW + 1, 0.2), mint=MINT,
            sent_event_ids=[events[0]["id"]])
        self.assertEqual(again, [])

    def test_cooldown_memblokir_resend_cepat(self):
        first = ta.evaluate_high_drop_rule(_marker(0.4), _current(NOW, 0.2),
                                           mint=MINT)
        self.assertEqual(len(first), 1)
        key = ta.dedup_key(first[0])
        rejected = []
        blocked = ta.evaluate_high_drop_rule(
            _marker(0.4), _current(NOW + 60, 0.2), mint=MINT,
            rejected=rejected, last_sent={key: NOW})
        self.assertEqual(blocked, [])
        self.assertTrue(rejected)


class HighDropFlowTest(unittest.TestCase):
    """Alur penuh lewat :func:`evaluate_alert_events` (``high_track=True``)."""

    def _analysis(self, pct, ts=NOW):
        return {"ca": MINT, "symbol": "REG", "analyzed_at": ts,
                "holders": {"dust_pct_mc": pct, "total_fetched": 10,
                            "wallets_analyzed": 10}}

    _NO_CTX = {"available": False, "reason": "tanpa data pasar (test)"}

    def test_naik_lalu_turun_50_persen_mengirim_sekali(self):
        state: dict = {}
        _, state = ta.evaluate_alert_events(
            MINT, self._analysis(0.5), state, high_track=True,
            market_context=self._NO_CTX)
        self.assertEqual((state.get("high_drop") or {}).get("high"), 0.5)

        events, state = ta.evaluate_alert_events(
            MINT, self._analysis(0.25, ts=NOW + 3600), state,
            high_track=True, market_context=self._NO_CTX)
        drops = [e for e in events if e.get("kind") == "high_drop"]
        self.assertEqual(len(drops), 1)
        self.assertEqual((state.get("high_drop") or {}).get("notified_high"),
                         0.5)

        # Run berikutnya di nilai sama → tidak mengirim ulang.
        events3, _ = ta.evaluate_alert_events(
            MINT, self._analysis(0.25, ts=NOW + 7200), state,
            high_track=True, market_context=self._NO_CTX)
        self.assertEqual(
            [e for e in events3 if e.get("kind") == "high_drop"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
