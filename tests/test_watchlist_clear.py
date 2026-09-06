# -*- coding: utf-8 -*-
"""Tombol **🗑️ Hapus semua** watchlist biasa (permintaan user 2026-09-06).

Dua lapis:

1. ``watchlist.remove_many_from_watchlist`` — hapus banyak token dengan
   **satu** tulis journal + **satu** commit (bukan N klik ✕), kontrak
   durabilitas sama dengan hapus satu token: journal dulu → file lokal →
   commit (``background=True`` = thread latar, nol jaringan di jalur klik).
2. AppTest ``app.py`` — tombol hanya ada di card watchlist biasa, butuh
   konfirmasi, dan scope-nya **hanya** token non-LP (Chart LP Meteora dan
   watchlist Robinhood tidak ikut).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import holder_history as hh
import watchlist as wl

APP = str(Path(__file__).resolve().parent.parent / "app.py")

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


# ---------------------------------------------------------------------------
# Lapis 2: tombol di app.py (AppTest)
# ---------------------------------------------------------------------------
BUCKET = hh.INTERVAL_SEC
CLEAR_KEY = "clear-regular-watchlist"


def _point(index: int, pct: float, count: int) -> dict:
    return {"ts": (index + 1) * BUCKET, "price": 0.01, "mc": 100_000.0,
            "dust_count": count, "dust_pct_mc": pct,
            "dust_value_usd": count * 5.0, "real_count": 40,
            "real_pct_mc": 20.0, "mid_count": 6, "mid_pct_mc": 4.0,
            "cohort_token_pct": 90.0, "cohort_cut50_pct": 10.0,
            "cohort_n": 6, "holder_count": count + 40,
            "buckets": {">$0-$10": count}}


def _watchlist():
    return {
        LP_MINT: {"symbol": "LPTOK", "source": "meteora",
                  "added": "2026-09-03"},
        CA_A: {"symbol": "AAA", "source": "manual", "added": "2026-09-02"},
        CA_B: {"symbol": "BBB", "source": "degen", "added": "2026-09-02"},
    }


def _status():
    tokens = {}
    for mint, meta in _watchlist().items():
        tokens[mint] = {"symbol": meta["symbol"], "marketcap": 100_000.0,
                        "price": 0.01, "analyzed_at": 2 * BUCKET,
                        "holders": {"dust_count": 20, "dust_pct_mc": 0.20,
                                    "real_count": 80, "total_fetched": 100},
                        "history": [_point(0, 0.10, 10), _point(1, 0.20, 20)]}
    return {"updated_at": 2 * BUCKET, "tokens": tokens}


def _store():
    return {"updated_at": 2 * BUCKET,
            "tokens": {mint: {"symbol": slot["symbol"], "cohort": {},
                              "points": slot.get("history") or []}
                       for mint, slot in _status()["tokens"].items()}}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class ClearRegularWatchlistButtonTest(unittest.TestCase):
    def _app(self, watchlist=None):
        data = dict(_watchlist() if watchlist is None else watchlist)
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: dict(data)),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: _status()),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: _store()),
            # Backup durable store: tes tidak boleh menyentuh jaringan.
            mock.patch("holder_history.pull_holder_history", return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=60).run()

    def _button(self, app, key):
        found = [button for button in app.button if button.key == key]
        self.assertTrue(found, f"tombol {key} tidak ditemukan")
        return found[0]

    def _body(self, app):
        return "\n".join(node.value for node in app.markdown)

    def test_tombol_konfirmasi_ada_dan_menyebut_jumlah_token_biasa(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        button = self._button(app, CLEAR_KEY)
        # 2 token biasa (AAA manual + BBB degen); LPTOK (meteora) tidak dihitung
        self.assertIn("2 token", button.label)
        body = self._body(app)
        self.assertIn("Hapus **2 token** dari watchlist biasa?", body)
        self.assertIn("Tidak** menyentuh Chart LP Meteora", body)

    def test_klik_konfirmasi_hanya_menghapus_token_non_lp(self):
        app = self._app()
        with mock.patch("watchlist.remove_many_from_watchlist",
                        return_value={"removed": 2, "missing": 0,
                                      "saved": True,
                                      "addresses": [CA_A, CA_B]}) as clear:
            app = self._button(app, CLEAR_KEY).click().run()
        clear.assert_called_once()
        cas = clear.call_args.args[0]
        self.assertEqual(sorted(cas), sorted([CA_A, CA_B]))
        self.assertNotIn(LP_MINT, cas)
        self.assertEqual(clear.call_args.kwargs.get("background"), True)
        self.assertEqual(clear.call_args.kwargs.get("note"),
                         "watchlist biasa")
        self.assertEqual(len(app.exception), 0)
        # laporan hasil ditampilkan setelah rerun
        notices = "\n".join(node.value for node in app.success)
        self.assertIn("2 token dihapus dari watchlist biasa", notices)

    def test_tanpa_token_biasa_tombol_tidak_dirender(self):
        """Card kosong (hanya Chart LP) → tidak ada yang bisa dihapus."""
        only_lp = {LP_MINT: _watchlist()[LP_MINT]}
        app = self._app(watchlist=only_lp)
        self.assertEqual(len(app.exception), 0)
        keys = [button.key or "" for button in app.button]
        self.assertNotIn(CLEAR_KEY, keys)
        # baris LP tetap ada di card Chart LP
        self.assertIn(f"lp-move-{LP_MINT}", keys)

    def test_tombol_baris_lama_tetap_ada(self):
        """Hapus semua melengkapi ✕ per baris, bukan menggantikannya."""
        app = self._app()
        keys = [button.key or "" for button in app.button]
        self.assertIn(f"remove-{CA_A}", keys)
        self.assertIn(f"remove-{CA_B}", keys)
        self.assertIn(CLEAR_KEY, keys)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
