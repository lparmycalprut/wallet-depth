# -*- coding: utf-8 -*-
"""Log aktivitas app (panel 🧾 paling bawah halaman utama, 2026-09-10).

Permintaan user: semua kejadian penting app masuk log; entri yang butuh
perubahan manual user dirender **merah bold** (level ``action``).
Ring buffer murni in-memory — tidak ada IO yang perlu di-mock.
"""
from __future__ import annotations

import threading
import unittest

import activity_log as al


class LogBufferTest(unittest.TestCase):
    def setUp(self):
        al.clear()
        self.addCleanup(al.clear)

    def test_entri_masuk_terbaru_dulu(self):
        al.info("a", "pertama", echo=False)
        al.warn("b", "kedua", echo=False)
        rows = al.entries()
        self.assertEqual([r["message"] for r in rows], ["kedua", "pertama"])

    def test_pesan_kosong_dilewati(self):
        al.info("a", "", echo=False)
        al.info("a", "   ", echo=False)
        self.assertEqual(al.entries(), [])

    def test_level_tak_dikenal_jadi_info(self):
        al.log("aneh", "a", "x", echo=False)
        self.assertEqual(al.entries()[0]["level"], al.LEVEL_INFO)

    def test_dedup_menumpuk_count_bukan_baris(self):
        for _ in range(5):
            al.warn("blockscout", "PRO API key#1: rate limit RPS (429)",
                    echo=False)
        rows = al.entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 5)

    def test_dedup_hanya_untuk_pesan_identik(self):
        al.warn("a", "x", echo=False)
        al.warn("a", "y", echo=False)
        al.error("a", "x", echo=False)  # level beda = baris baru
        self.assertEqual(len(al.entries()), 3)

    def test_ring_buffer_terbatas(self):
        for i in range(al.MAX_ENTRIES + 50):
            al.info("a", f"pesan {i}", dedup_sec=0, echo=False)
        rows = al.entries()
        self.assertEqual(len(rows), al.MAX_ENTRIES)
        self.assertEqual(rows[0]["message"],
                         f"pesan {al.MAX_ENTRIES + 49}")

    def test_counts_per_level(self):
        al.info("a", "i", echo=False)
        al.action("a", "butuh key", echo=False)
        al.action("b", "kredit habis", echo=False)
        stats = al.counts()
        self.assertEqual(stats[al.LEVEL_INFO], 1)
        self.assertEqual(stats[al.LEVEL_ACTION], 2)

    def test_thread_safe(self):
        def _spam(n):
            for i in range(50):
                al.info(f"t{n}", f"pesan {i}", dedup_sec=0, echo=False)
        threads = [threading.Thread(target=_spam, args=(n,))
                   for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(al.entries()), 200)


class EntryHtmlTest(unittest.TestCase):
    """Level ``action`` = merah bold (permintaan user); lainnya tidak bold."""

    def test_action_merah_bold(self):
        html = al.entry_html({"ts": 0, "level": al.LEVEL_ACTION,
                              "source": "blockscout",
                              "message": "kredit habis", "count": 1})
        self.assertIn("font-weight:700", html)
        self.assertIn("#dc2626", html)

    def test_error_merah_tapi_tidak_bold(self):
        html = al.entry_html({"ts": 0, "level": al.LEVEL_ERROR,
                              "source": "x", "message": "gagal", "count": 1})
        self.assertIn("#b91c1c", html)
        self.assertNotIn("font-weight:700", html)

    def test_pesan_di_escape(self):
        html = al.entry_html({"ts": 0, "level": al.LEVEL_INFO, "source": "x",
                              "message": "<script>alert(1)</script>",
                              "count": 1})
        self.assertNotIn("<script>", html)

    def test_count_lebih_dari_satu_ditampilkan(self):
        html = al.entry_html({"ts": 0, "level": al.LEVEL_WARN, "source": "x",
                              "message": "429", "count": 7})
        self.assertIn("×7", html)


class InstrumentasiTest(unittest.TestCase):
    """Titik-titik penting benar-benar menulis ke log."""

    def setUp(self):
        al.clear()
        self.addCleanup(al.clear)

    def test_key_parkir_402_masuk_sebagai_action(self):
        import robinhood_holders as rh
        rh._log_key_parked("key#2", 402, "")
        rows = al.entries()
        self.assertEqual(rows[0]["level"], al.LEVEL_ACTION)
        self.assertIn("key#2", rows[0]["message"])
        self.assertIn("402", rows[0]["message"])

    def test_key_parkir_429_hanya_warning(self):
        import robinhood_holders as rh
        rh._log_key_parked("key#1", 429, "")
        self.assertEqual(al.entries()[0]["level"], al.LEVEL_WARN)

    def test_blocked_tanpa_key_menyuruh_pasang_key(self):
        import robinhood_holders as rh
        from unittest import mock
        with mock.patch.object(rh, "get_pro_api_keys", return_value=[]):
            rh._log_blocked(None)
        row = al.entries()[0]
        self.assertEqual(row["level"], al.LEVEL_ACTION)
        self.assertIn("BLOCKSCOUT_API_KEY", row["message"])

    def test_blocked_dengan_key_menyebut_dashboard(self):
        import robinhood_holders as rh
        from unittest import mock
        with mock.patch.object(rh, "get_pro_api_keys",
                               return_value=["k1", "k2"]):
            rh._log_blocked(None)
        row = al.entries()[0]
        self.assertEqual(row["level"], al.LEVEL_ACTION)
        self.assertIn("2 key PRO", row["message"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
