# -*- coding: utf-8 -*-
"""Tombol **🗑️ Hapus semua** watchlist biasa (permintaan user 2026-09-06).

Dua lapis:

1. ``watchlist.remove_many_from_watchlist`` — hapus banyak token dengan
   **satu** tulis journal + **satu** commit (bukan N klik ✕), kontrak
   durabilitas sama dengan hapus satu token: journal dulu → file lokal →
   commit (``background=True`` = thread latar, nol jaringan di jalur klik).
Tombol 🗑️ di card watchlist biasa ikut terhapus bersama page temp
(2026-09-15); yang tetap di-pin di sini adalah kontrak fungsi
``remove_many_from_watchlist``-nya.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import watchlist as wl


CA_A = "RegularA111111111111111111111111111111111"
CA_B = "RegularB222222222222222222222222222222222"
CA_C = "RegularC333333333333333333333333333333333"
LP_MINT = "LpMint11111111111111111111111111111111111"
NOT_LISTED = "Missing4444444444444444444444444444444444"


# ---------------------------------------------------------------------------
# Lapis 1: watchlist.remove_many_from_watchlist
# ---------------------------------------------------------------------------
class _Sandbox(unittest.TestCase):
    """File watchlist di tmpdir + semua titik jaringan di-stub (offline)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wl-clear-")
        self.local = os.path.join(self.dir, "watchlist.json")
        self.pending = os.path.join(self.dir, "watchlist_pending.json")
        self._write({
            CA_A: {"symbol": "AAA", "source": "manual"},
            CA_B: {"symbol": "BBB", "source": "degen"},
            CA_C: {"symbol": "CCC", "source": "degen"},
            LP_MINT: {"symbol": "LP1", "source": "meteora"},
        })
        wl._reset_cache()
        self.addCleanup(wl._reset_cache)
        self._debounce = wl.PUSH_DEBOUNCE_SEC
        wl.PUSH_DEBOUNCE_SEC = 0.0
        self.addCleanup(setattr, wl, "PUSH_DEBOUNCE_SEC", self._debounce)
        for target, value in (("WATCHLIST_PATH", self.local),
                              ("PENDING_PATH", self.pending)):
            patch = mock.patch.object(wl, target, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.pull = mock.Mock(return_value=None)
        self.push = mock.Mock(return_value=True)
        for name, stub in (("_github_pull", self.pull),
                           ("_github_push", self.push)):
            patch = mock.patch.object(wl, name, stub)
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)
        # Cleanup berjalan LIFO: tunggu worker commit latar selesai SEBELUM
        # tmpdir dihapus, supaya prune jurnal tidak menulis ke folder hilang.
        self.addCleanup(self._wait)

    def _write(self, data: dict) -> None:
        with open(self.local, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)

    def _read(self) -> dict:
        with open(self.local, encoding="utf-8") as handle:
            return json.load(handle)

    def _journal(self) -> list:
        try:
            with open(self.pending, encoding="utf-8") as handle:
                return json.load(handle) or []
        except FileNotFoundError:
            return []

    def _clear(self, cas, **kwargs) -> dict:
        kwargs.setdefault("background", True)
        return wl.remove_many_from_watchlist(
            cas, local_path=self.local, pending_path=self.pending, **kwargs)

    def _wait(self) -> None:
        wl.wait_for_pushes("watchlist.json", timeout=10)


class RemoveManyTest(_Sandbox):
    def test_hapus_hanya_alamat_yang_diminta(self):
        """Scope = daftar CA dari pemanggil: token LP di file tidak disentuh."""
        result = self._clear([CA_A, CA_B, CA_C])
        self.assertEqual(result["removed"], 3)
        self.assertEqual(result["missing"], 0)
        self.assertTrue(result["saved"])
        self.assertEqual(sorted(result["addresses"]), sorted([CA_A, CA_B, CA_C]))
        # file lokal langsung berubah, token Meteora tetap ada
        self.assertEqual(list(self._read()), [LP_MINT])

    def test_journal_ditulis_sekali_untuk_semua_op(self):
        with mock.patch.object(wl, "_save_pending",
                               wraps=wl._save_pending) as save_pending:
            self._clear([CA_A, CA_B, CA_C])
        # satu tulis journal untuk tiga op (bukan tiga tulis)
        self.assertEqual(save_pending.call_count, 1)
        ops = self._journal()
        self.assertEqual([op["op"] for op in ops], ["remove"] * 3)
        self.assertEqual(sorted(op["ca"] for op in ops),
                         sorted([CA_A, CA_B, CA_C]))

    def test_jalur_klik_tanpa_jaringan_dan_satu_commit_latar(self):
        self._clear([CA_A, CA_B, CA_C])
        # tidak ada pull GitHub di jalur klik (state dibaca lokal)
        self.pull.assert_not_called()
        self._wait()
        # tepat satu commit untuk seluruh batch
        self.push.assert_called_once()
        payload, action = self.push.call_args.args[:2]
        self.assertEqual(list(payload), [LP_MINT])
        self.assertIn("remove 3 token", action)
        # journal dibersihkan setelah remote menerima
        self.assertEqual(self._journal(), [])
        self.assertEqual(wl.push_status("watchlist.json")["state"], "ok")

    def test_catatan_scope_masuk_pesan_commit(self):
        self._clear([CA_A], note="watchlist biasa")
        self._wait()
        self.assertIn("remove 1 token (watchlist biasa)",
                      self.push.call_args.args[1])

    def test_push_gagal_jurnal_dipertahankan(self):
        self.push.return_value = False
        self._clear([CA_A, CA_B])
        self._wait()
        ops = self._journal()
        self.assertEqual(sorted(op["ca"] for op in ops), sorted([CA_A, CA_B]))
        self.assertEqual(wl.push_status("watchlist.json")["state"], "error")
        # render berikutnya tetap tidak menampilkan token yang dihapus
        loaded = wl.load_watchlist(local_path=self.local,
                                   pending_path=self.pending)
        self.assertEqual(sorted(loaded), sorted([CA_C, LP_MINT]))

    def test_alamat_tak_dikenal_dihitung_missing_tapi_tetap_dijournal(self):
        result = self._clear([CA_A, NOT_LISTED])
        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(result["addresses"], [CA_A])
        # op remove untuk alamat yang tidak ada tetap di-journal: remote yang
        # lebih baru daripada state lokal ikut dibersihkan; _op_is_applied
        # akan mem-prune-nya bila memang sudah tidak ada.
        self.assertEqual(sorted(op["ca"] for op in self._journal()),
                         sorted([CA_A, NOT_LISTED]))

    def test_duplikat_dan_kosong_diabaikan(self):
        result = self._clear([CA_A, CA_A, "", None, "  "])
        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(len(self._journal()), 1)

    def test_daftar_kosong_tidak_menulis_apa_pun(self):
        before = self._read()
        result = self._clear([])
        self.assertEqual(result, {"removed": 0, "missing": 0, "saved": None,
                                  "addresses": []})
        self.assertEqual(self._read(), before)
        self.assertEqual(self._journal(), [])
        self.push.assert_not_called()

    def test_remove_membatalkan_add_yang_masih_tertunda(self):
        """Last-op-wins per CA: add yang belum ter-commit tidak hidup lagi."""
        wl._save_pending([{"op": "add", "ca": CA_A, "symbol": "AAA"}],
                         self.pending)
        self._clear([CA_A])
        ops = self._journal()
        self.assertEqual(ops, [{"op": "remove", "ca": CA_A}])

    def test_jalur_sinkron_tetap_tersedia_untuk_skrip(self):
        """Default ``background=False`` = pull + push sinkron (cron/skrip)."""
        result = self._clear([CA_A, CA_B], background=False)
        self.assertEqual(result["removed"], 2)
        self.pull.assert_called_once_with("watchlist.json")
        self.push.assert_called_once()
        self.assertEqual(self._journal(), [])




if __name__ == "__main__":
    unittest.main()
