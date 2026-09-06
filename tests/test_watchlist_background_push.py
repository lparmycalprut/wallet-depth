# -*- coding: utf-8 -*-
"""Watchlist mutation di UI tidak boleh menunggu GitHub (2026-09-06).

Permintaan user: "hapus dari watchlist robinhood kurang responsif". Jalur
lama (sinkron) menarik GitHub **sebelum** menulis (``_load_and_merge`` →
``_github_pull``: sampai 3 GET × 10 dtk) lalu commit (``_github_push``:
GET+PUT × 3 percobaan × 15 dtk). Diukur dengan stub RTT 0,8 dtk: **2,4 s per
klik** — dan berlipat saat API lambat karena setiap rerun ``load_watchlist``
ikut mem-flush journal.

Kontrak baru (``background=True``): baca state lokal → tulis lokal + journal →
seed cache → commit di thread latar. Nol panggilan jaringan di jalur klik,
jurnal tetap menjadi jaring pengaman sampai remote menerima perubahannya.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import watchlist as wl

REPO_PATH = "watchlist_robinhood.json"
CA_A = "0x" + "a" * 40
CA_B = "0x" + "b" * 40


class _Sandbox(unittest.TestCase):
    """File watchlist di tmpdir + semua titik jaringan di-stub."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wl-bg-push-")
        self.local = os.path.join(self.dir, REPO_PATH)
        self.pending = os.path.join(self.dir,
                                    "watchlist_robinhood_pending.json")
        self._write({CA_A: {"symbol": "AAA", "source": "lp"},
                     CA_B: {"symbol": "BBB", "source": "lp"}})
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
        # Test tidak boleh menyentuh jaringan sama sekali: kedua titik
        # masuk di-mock dan bisa diaudit siapa memanggil apa.
        self.pull = mock.Mock(return_value=None)
        self.push = mock.Mock(return_value=True)
        for name, stub in (("_github_pull", self.pull),
                           ("_github_push", self.push)):
            patch = mock.patch.object(wl, name, stub)
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)

    # --- helpers ------------------------------------------------------------
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

    def _remove(self, ca: str, **kwargs) -> bool:
        kwargs.setdefault("background", True)
        return wl.remove_from_watchlist(ca, repo_path=REPO_PATH,
                                        local_path=self.local,
                                        pending_path=self.pending, **kwargs)

    def _wait(self) -> None:
        wl.wait_for_pushes(REPO_PATH, timeout=10)


class RemoveBackgroundTest(_Sandbox):
    def test_klik_hapus_tidak_menunggu_jaringan(self):
        started = time.perf_counter()
        self.assertTrue(self._remove(CA_A))
        elapsed = time.perf_counter() - started

        # jalur klik: nol GET remote sebelum menulis (state dibaca lokal)
        self.pull.assert_not_called()
        self.assertLess(elapsed, 0.5,
                        f"hapus masih memblokir {elapsed:.2f}s")
        # perubahan langsung ada di file lokal + di-journal
        self.assertEqual(list(self._read()), [CA_B])
        self.assertEqual([op["op"] for op in self._journal()], ["remove"])
        # dan render berikutnya membaca state baru tanpa pull GitHub
        self.pull.side_effect = AssertionError("load_watchlist pull lagi!")
        loaded = wl.load_watchlist(repo_path=REPO_PATH, local_path=self.local,
                                   pending_path=self.pending)
        self.assertEqual(list(loaded), [CA_B])

    def test_commit_dikerjakan_thread_latar_lalu_jurnal_dibersihkan(self):
        # Commit dibuat "lambat" supaya kelihatan jelas: UI tidak ikut menunggu
        gate = threading.Event()
        self.push.side_effect = lambda *a, **k: gate.wait(5) or True
        started = time.perf_counter()
        self.assertTrue(self._remove(CA_A))
        self.assertLess(time.perf_counter() - started, 0.3,
                        "hapus menunggu commit GitHub")
        gate.set()
        self._wait()
        self.push.assert_called_once()
        args = self.push.call_args
        self.assertEqual(args.kwargs["repo_path"], REPO_PATH)
        self.assertNotIn(CA_A, args.args[0])
        # journal dibersihkan hanya setelah remote menerima
        self.assertEqual(self._journal(), [])
        self.assertEqual(wl.push_status(REPO_PATH)["state"], "ok")

    def test_push_gagal_jurnal_dipertahankan_dan_status_error(self):
        self.push.return_value = False
        self._remove(CA_A)
        self._wait()
        ops = self._journal()
        self.assertEqual([op["op"] for op in ops], ["remove"])
        self.assertEqual(ops[0]["ca"], CA_A)
        status = wl.push_status(REPO_PATH)
        self.assertEqual(status["state"], "error")

    def test_perubahan_beruntun_dicoalesce_jadi_commit_terbaru(self):
        gate = threading.Event()
        calls: list = []

        def slow_push(payload, action, *args, **kwargs):
            calls.append((action, dict(payload)))
            gate.wait(5)
            return True

        self.push.side_effect = slow_push
        wl.PUSH_DEBOUNCE_SEC = 0.1
        self._remove(CA_A)
        self._remove(CA_B)
        # worker pertama masih "berada di GitHub": biarkan ambil job terbaru
        time.sleep(0.2)
        gate.set()
        self._wait()
        self.assertTrue(calls, "tidak ada commit sama sekali")
        self.assertNotIn(CA_A, calls[-1][1])
        self.assertNotIn(CA_B, calls[-1][1])
        self.assertEqual(list(self._read()), [])
        self._wait()
        self.assertEqual(self._journal(), [])

    def test_flag_lama_tetap_sinkron(self):
        """Pemanggil non-UI (default background=False) tidak berubah perangainya."""
        self._remove(CA_A, background=False)
        self.pull.assert_called_once_with(REPO_PATH)
        self.push.assert_called_once()
        self.assertEqual(self._journal(), [])

    def test_simbol_dipakai_untuk_pesan_commit(self):
        self._remove(CA_A)
        self._wait()
        self.assertIn("remove AAA", self.push.call_args.args[1])

    def test_remove_tidak_muncul_lagi_saat_push_belum_berhasil(self):
        """Jurnal remove tidak boleh di-prune terhadap seed cache optimis.

        Bug: ``_load_and_merge`` mem-prune jurnal terhadap *seed cache* (state
        hasil perubahan lokal yang ditandai belum ``settled``). Kalau push GitHub
        gagal, jurnal sudah hilang -> begitu cache kedaluwarsa dan server menarik
        ulang remote yang masih memuat token, token yang dihapus **muncul lagi**
        (\"bolak balik\").

        Jalankan: push selalu gagal (remote masih punya CA_A), lalu *load* yang
        memakai seed cache, lalu *force refresh* yang menarik remote lama. CA_A
        harus tetap hilang karena jurnal remove dipertahankan.
        """
        # remote masih memuat CA_A (push gagal) -> jurnal menjadi jaring pengaman.
        self.pull.return_value = {CA_A: {"symbol": "AAA"},
                                  CA_B: {"symbol": "BBB"}}
        self.push.return_value = False

        self._remove(CA_A)
        self._wait()

        # push gagal -> jurnal dipertahankan.
        self.assertEqual([op["op"] for op in self._journal()], ["remove"])
        self.assertEqual(wl.push_status(REPO_PATH)["state"], "error")

        # load_watchlist memakai seed cache (settled=False): jurnal TIDAK boleh
        # di-prune sebelum remote benar-benar menerima penghapusan.
        loaded = wl.load_watchlist(repo_path=REPO_PATH, local_path=self.local,
                                   pending_path=self.pending)
        self.assertEqual(list(loaded), [CA_B])
        self.assertEqual([op["op"] for op in self._journal()], ["remove"],
                         "jurnal harus dipertahankan sebelum push sukses")

        # cache kedaluwarsa + force refresh -> pull mengembalikan remote LAMA
        # (CA_A masih ada). Karena jurnal remove masih ada, token tetap hilang.
        wl._REMOTE_CACHE[wl._norm_repo_path(REPO_PATH)] = {"data": {}, "ts": 0.0}
        loaded2 = wl.load_watchlist(force_refresh=True, repo_path=REPO_PATH,
                                    local_path=self.local,
                                    pending_path=self.pending)
        self.assertNotIn(CA_A, loaded2)
        self.assertEqual(list(loaded2), [CA_B])


class LoadWatchlistFlushTest(_Sandbox):
    def test_flush_journal_tidak_dobel_ketika_push_masih_berjalan(self):
        """``load_watchlist`` me-flush journal — tapi jangan menabrak worker."""
        gate = threading.Event()
        calls = []

        def blocking_push(*args, **kwargs):
            calls.append(kwargs.get("action") or args[1:])
            gate.wait(5)
            return True

        self.push.side_effect = blocking_push
        token = mock.patch.object(wl, "_github_token",
                                 return_value="tok")
        token.start()
        self.addCleanup(token.stop)
        self._journal_append({"op": "add", "ca": "0x" + "c" * 40,
                              "symbol": "CCC"})
        self._remove(CA_A)
        self.assertTrue(wl.push_inflight(REPO_PATH))
        wl.load_watchlist(repo_path=REPO_PATH, local_path=self.local,
                          pending_path=self.pending)
        self.assertEqual(len(calls), 1, "flush inline dobel dengan worker")
        gate.set()
        self._wait()

    def _journal_append(self, op: dict) -> None:
        ops = self._journal()
        ops.append(op)
        with open(self.pending, "w", encoding="utf-8") as handle:
            json.dump(ops, handle)


class GithubPushJournalIsolationTest(unittest.TestCase):
    """``_github_push`` hanya boleh membaca jurnal **milik file itu sendiri**.

    Jurnal lama selalu dibaca dari ``watchlist_pending.json`` (Solana), padahal
    fungsi yang sama dipakai untuk ``watchlist_robinhood.json`` **dan**
    ``holder_status*.json``: op add yang tertunda di satu jaringan bisa
    nyempil ke payload jaringan lain. Sekarang ``pending_path`` /
    ``merge_journal`` menentukan isinya.
    """

    BASE = 1_800_000_000

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wl-journal-")
        self.rh_pending = os.path.join(self.dir, "rh_pending.json")
        self.sol_pending = os.path.join(self.dir, "sol_pending.json")
        with open(self.sol_pending, "w", encoding="utf-8") as handle:
            json.dump([{"op": "add", "ca": "SOLMINT11111111111111111111111",
                        "symbol": "FOE"},
                       {"op": "remove", "ca": CA_A}], handle)
        with open(self.rh_pending, "w", encoding="utf-8") as handle:
            json.dump([{"op": "remove", "ca": CA_B}], handle)
        self.addCleanup(shutil.rmtree, self.dir, True)

    class _Resp:
        status_code = 200
        text = "{}"

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def _push(self, payload, *, pending_path, merge_journal=True):
        import base64
        sent: dict = {}
        remote = {"tokens": json.dumps({CA_A: {"symbol": "AAA"},
                                        CA_B: {"symbol": "BBB"}})}

        def fake_get(url, headers=None, timeout=None):
            return self._Resp({"sha": "deadbeef",
                               "content": base64.b64encode(
                                   remote["tokens"].encode()).decode()})

        def fake_put(url, headers=None, json=None, timeout=None):
            sent.update(json)
            return self._Resp({})

        requests_stub = mock.Mock()
        requests_stub.get.side_effect = fake_get
        requests_stub.put.side_effect = fake_put
        with mock.patch.object(wl, "requests", requests_stub), \
                mock.patch.object(wl, "_github_token",
                                  return_value="tok"):
            ok = wl._github_push(payload, "remove X",
                                 repo_path=REPO_PATH,
                                 pending_path=pending_path,
                                 merge_journal=merge_journal)
        self.assertTrue(ok)
        import base64 as b64
        return json.loads(b64.b64decode(sent["content"]).decode())

    def test_jurnal_solana_tidak_masuk_payload_robinhood(self):
        pushed = self._push({CA_A: {"symbol": "AAA"}},
                            pending_path=self.rh_pending)
        # jurnal Solana (add SOLMINT + remove AAA) tidak boleh berlaku di sini
        self.assertNotIn("SOLMINT1111111111111111111111", pushed,
                         "jurnal watchlist Solana menular ke file Robinhood")
        self.assertIn(CA_A, pushed)
        # jurnal milik file itu sendiri tetap diterapkan (lost-update guard)
        self.assertNotIn(CA_B, pushed)

    def test_merge_journal_false_untuk_file_tanpa_jurnal(self):
        """``holder_status*.json``: tidak ada jurnal sama sekali."""
        pushed = self._push({CA_A: {"symbol": "AAA"}},
                            pending_path=self.sol_pending,
                            merge_journal=False)
        self.assertEqual(sorted(pushed), sorted({CA_A, CA_B}))


class StatusAndDispatchTest(_Sandbox):
    def test_push_status_idle_sebelum_ada_perubahan(self):
        self.assertEqual(wl.push_status(REPO_PATH),
                         {"state": "idle", "ts": None, "msg": ""})
        self.assertFalse(wl.push_inflight(REPO_PATH))

    def test_status_dan_antrian_terpisah_per_file_watchlist(self):
        gate = threading.Event()
        self.push.side_effect = lambda *a, **k: gate.wait(5) or True
        wl.remove_from_watchlist(CA_A, repo_path=REPO_PATH,
                                 local_path=self.local,
                                 pending_path=self.pending, background=True)
        self.assertTrue(wl.push_inflight(REPO_PATH))
        self.assertFalse(wl.push_inflight("watchlist.json"))
        gate.set()
        self._wait()

    def test_dispatch_scan_async_direm_agar_tidak_banjir(self):
        hits = []
        done = threading.Event()

        def fake_dispatch():
            hits.append(1)
            done.set()
            return True

        with mock.patch.object(wl, "request_immediate_scan",
                              side_effect=fake_dispatch):
            self.assertTrue(wl.dispatch_scan_async(min_gap_sec=60))
            self.assertTrue(done.wait(5))
            self.assertFalse(wl.dispatch_scan_async(min_gap_sec=60),
                             "dispatch kedua harus direm")
            wl._SCAN_DISPATCH["ts"] = 0.0
            self.assertTrue(wl.dispatch_scan_async(min_gap_sec=60))
            for _ in range(50):
                if len(hits) == 2:
                    break
                time.sleep(0.1)
        self.assertEqual(len(hits), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
