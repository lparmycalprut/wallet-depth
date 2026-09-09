# -*- coding: utf-8 -*-
"""Rule 🚨 WAKTUNYA EXIT / CUTLOSS + ✅ KEMBALI KE TITIK AMAN.

Permintaan user 2026-09-07, sebagai turunan dari episode ⚡ EARLY DUMP:

- bila dalam **15 menit** setelah pengingat ⚡ pertama dust terus bertambah
  (3 scan 5 menit berturut-turut naik) → kirim **WAKTUNYA EXIT / CUTLOSS**;
- bila dalam kurun yang sama dust **turun lagi di bawah 0,1% MC** → kirim
  **KEMBALI KE TITIK AMAN**.

Keduanya maksimal satu kali per episode, dan episode direset begitu dust
kembali bersih.
"""
from __future__ import annotations

import unittest

import telegram_alerts as ta

NOW = 1_800_000_000
STEP = ta.FAST_BUCKET_SEC              # 5 menit
MINT = "LpMint11111111111111111111111111111111111"


def _analysis(pct, ts):
    return {"symbol": "LPX", "analyzed_at": ts,
            "holders": {"dust_pct_mc": pct,
                        "wallet_snapshot": {"ts": ts, "dust_pct_mc": pct}}}


def _run(series, *, start=NOW, step=STEP):
    """Jalankan urutan scan lane LP; kembalikan (kinds per scan, state)."""
    state: dict = {}
    seen: list[list[str]] = []
    for index, pct in enumerate(series):
        events, state = ta.evaluate_alert_events(
            MINT, _analysis(pct, start + index * step), state,
            lp_mint=True, volume_rules=False)
        state["sent_event_ids"] = (list(state.get("sent_event_ids") or [])
                                   + [event["id"] for event in events])
        seen.append([event["kind"] for event in events])
    return seen, state


def _flat(seen):
    return [kind for scan in seen for kind in scan]


class EscalationTest(unittest.TestCase):
    def test_tiga_scan_naik_berturut_memicu_exit_cutloss(self):
        seen, state = _run([0.15, 0.22, 0.31])
        self.assertIn(ta.ESCALATION_KIND, seen[2])
        # Dua scan pertama hanya pengingat biasa.
        self.assertEqual(seen[0], ["early_dump"])
        self.assertEqual(seen[1], ["early_dump"])
        self.assertTrue(state["early_dump"]["escalated"])

    def test_exit_cutloss_hanya_sekali_per_episode(self):
        seen, _state = _run([0.15, 0.22, 0.31, 0.42, 0.55])
        self.assertEqual(_flat(seen).count(ta.ESCALATION_KIND), 1)

    def test_dust_tidak_naik_terus_tidak_eskalasi(self):
        # Naik, lalu datar: rangkaian putus → tidak ada cutloss.
        seen, _state = _run([0.15, 0.22, 0.22])
        self.assertNotIn(ta.ESCALATION_KIND, _flat(seen))

    def test_dua_scan_saja_belum_cukup(self):
        seen, _state = _run([0.15, 0.22])
        self.assertNotIn(ta.ESCALATION_KIND, _flat(seen))

    def test_kenaikan_di_luar_15_menit_tidak_eskalasi(self):
        # Scan berjarak 15 menit → scan ketiga jatuh di menit ke-30, jauh di
        # luar jendela 15 menit (+1 bucket toleransi run cron yang telat).
        seen, _state = _run([0.15, 0.22, 0.31], step=15 * 60)
        self.assertNotIn(ta.ESCALATION_KIND, _flat(seen))

    def test_toleransi_satu_bucket_untuk_cron_telat(self):
        """Scan ke-3 telat sedikit (menit ke-20) tetap dihitung."""
        seen, _state = _run([0.15, 0.22, 0.31], step=10 * 60)
        self.assertIn(ta.ESCALATION_KIND, _flat(seen))

    def test_episode_baru_bisa_eskalasi_lagi(self):
        seen, _state = _run([0.15, 0.22, 0.31,   # episode 1 → cutloss
                             0.05,               # reset (aman)
                             0.15, 0.22, 0.31])  # episode 2 → cutloss lagi
        self.assertEqual(_flat(seen).count(ta.ESCALATION_KIND), 2)


class SafeReturnTest(unittest.TestCase):
    def test_turun_di_bawah_ambang_memicu_titik_aman(self):
        seen, state = _run([0.15, 0.22, 0.05])
        self.assertIn(ta.SAFE_RETURN_KIND, seen[2])
        # Episode ditutup: hitungan bersih lagi.
        self.assertFalse(state["early_dump"].get("first_ts"))

    def test_titik_aman_hanya_sekali(self):
        seen, _state = _run([0.15, 0.22, 0.05, 0.04, 0.03])
        self.assertEqual(_flat(seen).count(ta.SAFE_RETURN_KIND), 1)

    def test_token_yang_selalu_aman_tidak_mengirim_apa_pun(self):
        seen, _state = _run([0.02, 0.03, 0.02])
        self.assertEqual(_flat(seen), [])

    def test_setelah_cutloss_masih_bisa_kirim_titik_aman(self):
        seen, _state = _run([0.15, 0.22, 0.31, 0.05])
        flat = _flat(seen)
        self.assertIn(ta.ESCALATION_KIND, flat)
        self.assertIn(ta.SAFE_RETURN_KIND, flat)


class EpisodeMessageTest(unittest.TestCase):
    def _message(self, series, kind):
        state: dict = {}
        for index, pct in enumerate(series):
            events, state = ta.evaluate_alert_events(
                MINT, _analysis(pct, NOW + index * STEP), state,
                lp_mint=True, volume_rules=False)
            state["sent_event_ids"] = (list(state.get("sent_event_ids") or [])
                                       + [event["id"] for event in events])
            for event in events:
                if event["kind"] == kind:
                    return ta.format_alert_message(event)
        self.fail(f"event {kind} tidak pernah dikirim")

    def test_pesan_exit_cutloss(self):
        message = self._message([0.15, 0.22, 0.31], ta.ESCALATION_KIND)
        self.assertEqual(
            message.splitlines()[0],
            "🚨 WAKTUNYA EXIT / CUTLOSS / Reshape bid-ask 50 bin")
        self.assertEqual(message.splitlines()[1], "")
        self.assertIn("$LPX", message)
        self.assertIn("📊 Dust: 0.22% → 0.31% MC (+0.09 pp)", message)
        self.assertIn("📈 Naik 3 scan berturut (±10 menit)", message)
        self.assertIn("\n🔗 GMGN\n", message)   # hyperlink: URL di entity
        self.assertNotIn("http", message)

    def test_pesan_titik_aman(self):
        message = self._message([0.15, 0.22, 0.05], ta.SAFE_RETURN_KIND)
        self.assertIn("✅ KEMBALI KE TITIK AMAN", message)
        self.assertIn("📊 Dust: 0.22% → 0.05% MC (-0.17 pp)", message)
        self.assertIn("🛡️ Dust kembali ≤ 0.1% MC (±10 menit)", message)


class SimpleFormatTest(unittest.TestCase):
    """Format notifikasi disederhanakan (permintaan user 2026-09-07)."""

    def _early_message(self):
        events, _state = ta.evaluate_alert_events(
            MINT, _analysis(0.15, NOW), {}, lp_mint=True, volume_rules=False)
        return ta.format_alert_message(events[0])

    def test_baris_pengingat_dan_verifikasi_dihapus(self):
        message = self._early_message()
        self.assertNotIn("Pengingat berulang", message)
        self.assertNotIn("Verifikasi", message)
        self.assertNotIn("TIDAK TERVERIFIKASI", message)
        self.assertNotIn("Periode:", message)

    def test_waktu_hanya_wib(self):
        message = self._early_message()
        waktu = [line for line in message.splitlines()
                 if line.startswith("🕒 ")]
        self.assertEqual(len(waktu), 1)
        self.assertIn("WIB", waktu[0])
        self.assertNotIn("UTC", waktu[0])


class StatePersistenceTest(unittest.TestCase):
    """Runner cron ephemeral: state episode harus selamat lewat snapshot."""

    def test_marker_episode_ikut_di_compact_dan_summary(self):
        _seen, state = _run([0.15, 0.22, 0.31])
        for payload in (ta.compact_alert_state(state),
                        ta.alert_state_summary(state)):
            marker = payload["early_dump"]
            self.assertTrue(marker["first_ts"])
            self.assertTrue(marker["escalated"])
            self.assertGreaterEqual(marker["rises"], 3)

    def test_state_yang_dipulihkan_tidak_mengirim_cutloss_dua_kali(self):
        _seen, state = _run([0.15, 0.22, 0.31])
        restored = ta.compact_alert_state(state)
        restored["sent_event_ids"] = list(state.get("sent_event_ids") or [])
        events, _next = ta.evaluate_alert_events(
            MINT, _analysis(0.44, NOW + 3 * STEP), restored,
            lp_mint=True, volume_rules=False)
        self.assertNotIn(ta.ESCALATION_KIND,
                         [event["kind"] for event in events])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
