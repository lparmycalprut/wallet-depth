"""Rantai cron 5 menit: guard harus tetap dispatch saat schedule di-throttle.

Kasus nyata yang jadi regresi utama: 2026-09-09, run #1182 selesai 16:40:24
UTC dan tidak ada scan lagi sampai 17:29+ UTC, karena guard lama menyimpulkan
"schedule */5 sehat" dari umur run ``event=schedule`` (299 s < 900 s) lalu
melewati dispatch — padahal scheduler GitHub saat itu cuma menyala 4× sehari.
"""
from __future__ import annotations

import unittest
from unittest import mock

from scripts import chain_next_run as c


def _run(rid, status="completed", updated="2026-09-09T16:35:26Z",
         branch="main", event="schedule"):
    return {"id": rid, "status": status, "updated_at": updated,
            "head_branch": branch, "event": event}


class NextBoundaryWaitTest(unittest.TestCase):
    def test_bangun_setelah_batas_5_menit(self):
        # 16:40:00 → batas berikutnya 16:45:00 + 20 s lead = 320 s
        now = c._parse_ts("2026-09-09T16:40:00Z")
        self.assertEqual(c.next_boundary_wait(now), 320)

    def test_tepat_di_batas_menunggu_satu_kadens_penuh(self):
        # Baru saja melewati batas → tidur penuh (kadens + lead), sama
        # seperti perilaku bash lama; yang mengejar +20 s hanyalah run yang
        # tiba SEBELUM batas: 16:44:59 → 21 s.
        self.assertEqual(c.next_boundary_wait(c._parse_ts("2026-09-09T16:45:00Z")), 320)
        self.assertEqual(c.next_boundary_wait(c._parse_ts("2026-09-09T16:44:59Z")), 21)

    def test_selalu_positif_dan_cadence_dibulatkan_ke_batas_aman(self):
        now = c._parse_ts("2026-09-09T16:44:59Z")
        self.assertGreaterEqual(c.next_boundary_wait(now, cadence=10), 1)
        # cadence < 60 s ditolak (satu run Actions tidak pernah secepat itu)
        self.assertEqual(c.next_boundary_wait(now, cadence=10, lead=0), 1)


class SplitRunsTest(unittest.TestCase):
    def test_mengabaikan_run_sendiri(self):
        active, age = c.split_runs([_run(1182)], "1182", branch="main",
                                   now_ts=c._parse_ts("2026-09-09T16:40:20Z"))
        self.assertEqual((active, age), (0, None))

    def test_menghitung_yang_masih_hidup(self):
        for state in c.ACTIVE_STATES:
            with self.subTest(state=state):
                active, age = c.split_runs(
                    [_run(1, status=state, updated=""),
                     _run(2, updated="")], "9",
                    branch="main", now_ts=1_000_000)
                self.assertEqual(active, 1)
                self.assertEqual(age, None)

    def test_umur_diambil_dari_run_selesai_terbaru(self):
        runs = [_run(1, updated="2026-09-09T16:35:26Z"),
                _run(2, updated="2026-09-09T16:30:26Z"),
                _run(3, status="in_progress", updated="")]
        now = c._parse_ts("2026-09-09T16:40:20Z")
        active, age = c.split_runs(runs, "9", branch="main", now_ts=now)
        self.assertEqual(active, 1)
        self.assertEqual(age, 294)

    def test_cabang_lain_bukan_sinyal_rantai(self):
        runs = [_run(1, branch="arena/other"), _run(2, branch="main")]
        now = c._parse_ts("2026-09-09T16:40:20Z")
        _active, age = c.split_runs(runs, "9", branch="main", now_ts=now)
        self.assertEqual(age, now - c._parse_ts("2026-09-09T16:35:26Z"))

    def test_run_cancelled_tetap_hitung_sebagai_selesai(self):
        # status "completed" + conclusion "cancelled" pernah terjadi (run
        # #1175) dan tetap berarti "baru ada run di slot ini".
        runs = [_run(1, updated="2026-09-09T16:35:26Z")]
        now = c._parse_ts("2026-09-09T16:40:20Z")
        self.assertEqual(c.split_runs(runs, "9", "main", now)[1], 294)

    def test_timestamp_cacat_ditoleransi(self):
        runs = [_run(1, updated="bukan-tanggal"), _run(2, updated=None)]
        self.assertEqual(c.split_runs(runs, "9", "main", 0), (0, None))


class ShouldDispatchTest(unittest.TestCase):
    def test_stall_2026_09_09_harus_dispatch(self):
        """Guard lama lewati di sini (299 < 900); rantai harus menyambung."""
        go, _why = c.should_dispatch(active=0, last_age=299, quiet_sec=240)
        self.assertTrue(go)

    def test_antrean_penuh_jangan_dispatch(self):
        go, why = c.should_dispatch(active=1, last_age=None)
        self.assertFalse(go)
        self.assertIn("antre", why)

    def test_run_lain_baru_selesai_biar_dia_yang_merantai(self):
        go, why = c.should_dispatch(active=0, last_age=120, quiet_sec=240)
        self.assertFalse(go)
        self.assertIn("merantai", why)

    def test_tidak_ada_run_sama_sekali_tetap_dispatch(self):
        self.assertTrue(c.should_dispatch(active=0, last_age=None)[0])

    def test_jendela_quiet_dipotong_dibawah_kadens(self):
        """Pembanding == kadens membuat rantai mematikan dirinya sendiri."""
        self.assertTrue(c.should_dispatch(0, 240, quiet_sec=240)[0])
        self.assertFalse(c.should_dispatch(0, 239, quiet_sec=240)[0])


class ChainOnceTest(unittest.TestCase):
    def test_dispatch_terkirim_saat_run_terakhir_tua(self):
        calls = []
        with mock.patch.object(c, "list_runs", return_value=[_run(1181)]), \
                mock.patch.object(c, "dispatch_run",
                                  side_effect=lambda *a, **k: calls.append(a) or True):
            code = c.chain_once(repo="o/r", workflow="daily-effort.yml",
                                ref="main", run_id="1182", token="t",
                                cadence=300, quiet_sec=240, lead=20,
                                now=lambda: c._parse_ts("2026-09-09T16:40:20Z"),
                                sleeper_ok=False)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [("o/r", "daily-effort.yml", "main", "t")])

    def test_run_hidup_membatalkan_dispatch(self):
        with mock.patch.object(c, "list_runs",
                               return_value=[_run(1183, status="queued")]), \
                mock.patch.object(c, "dispatch_run") as dispatched:
            code = c.chain_once(repo="o/r", workflow="w.yml", ref="main",
                                run_id="1182", token="t", cadence=300,
                                quiet_sec=240, lead=20,
                                now=lambda: c._parse_ts("2026-09-09T16:40:20Z"),
                                sleeper_ok=False)
        self.assertEqual(code, 0)
        dispatched.assert_not_called()

    def test_api_mati_fail_open_jangan_mematikan_pipeline(self):
        """Guard tidak bisa dinilai → tetap dispatch (run ganda sudah
        disaring gate MIN_RUN_GAP_SEC di scanner)."""
        with mock.patch.object(c, "list_runs", return_value=None), \
                mock.patch.object(c, "dispatch_run", return_value=True) as d:
            code = c.chain_once(repo="o/r", workflow="w.yml", ref="main",
                                run_id="1", token="t", cadence=300,
                                quiet_sec=240, lead=20,
                                now=lambda: 1_000_000, sleeper_ok=False)
        self.assertEqual(code, 0)
        d.assert_called_once()

    def test_dispatch_gagal_total_dilaporkan_merah(self):
        with mock.patch.object(c, "list_runs", return_value=[]), \
                mock.patch.object(c, "dispatch_run", return_value=False):
            code = c.chain_once(repo="o/r", workflow="w.yml", ref="main",
                                run_id="1", token="t", cadence=300,
                                quiet_sec=240, lead=20,
                                now=lambda: 1_000_000, sleeper_ok=False)
        self.assertEqual(code, 1)

    def test_tidur_sampai_batas_berikutnya(self):
        slept = []
        with mock.patch.object(c, "list_runs", return_value=[]), \
                mock.patch.object(c, "dispatch_run", return_value=True):
            c.chain_once(repo="o/r", workflow="w.yml", ref="main", run_id="1",
                         token="t", cadence=300, quiet_sec=240, lead=20,
                         do_sleep=slept.append,
                         now=lambda: c._parse_ts("2026-09-09T16:40:00Z"))
        self.assertEqual(slept, [320])


class RequestTest(unittest.TestCase):
    def test_retry_sampai_sukses(self):
        seq = [urllib_error_500(), _resp({"workflow_runs": []})]
        with mock.patch.object(c.urllib.request, "urlopen", side_effect=seq):
            status, payload = c._request("https://x", "t", attempts=3,
                                          sleep=lambda s: None)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"workflow_runs": []})

    def test_4xx_permanen_tidak_diulang(self):
        """422 ref salah: retry 4x hanya memperpanjang run yang mati."""
        import urllib.error
        boom = urllib.error.HTTPError("https://x", 422, "Unprocessable", {},
                                      None)
        with mock.patch.object(c.urllib.request, "urlopen",
                               side_effect=boom) as opened:
            status, _ = c._request("https://x", "t", attempts=4,
                                   sleep=lambda s: None)
        self.assertEqual(status, 422)
        self.assertEqual(opened.call_count, 1)

    def test_semua_gagal_kembali_status_terakhir(self):
        with mock.patch.object(c.urllib.request, "urlopen",
                               side_effect=urllib_error_500()):
            status, _payload = c._request("https://x", "t", attempts=2,
                                          sleep=lambda s: None)
        self.assertEqual(status, 500)

    def test_list_runs_membawa_workflow_runs(self):
        payload = {"workflow_runs": [_run(1)]}
        with mock.patch.object(c, "_request", return_value=(200, payload)):
            self.assertEqual(len(c.list_runs("o/r", "w.yml", "t")), 1)

    def test_list_runs_error_dikembalikan_sebagai_none(self):
        with mock.patch.object(c, "_request", return_value=(403, "Forbidden")):
            self.assertIsNone(c.list_runs("o/r", "w.yml", "t"))

    def test_dispatch_status_diterima(self):
        for code in (201, 202, 204):
            with self.subTest(code=code), mock.patch.object(
                    c, "_request", return_value=(code, {})):
                self.assertTrue(c.dispatch_run("o/r", "w.yml", "main", "t"))

    def test_dispatch_ditolak_dikembalikan_false(self):
        with mock.patch.object(c, "_request", return_value=(422, "bad ref")):
            self.assertFalse(c.dispatch_run("o/r", "w.yml", "nope", "t"))


def urllib_error_500():
    import urllib.error
    return urllib.error.HTTPError("https://x", 500, "Server Error", {}, None)


def _resp(payload, status=200):
    """Tiru response context-manager urllib untuk mock urlopen."""
    import json as _json
    body = _json.dumps(payload).encode()

    class _Resp:
        def __init__(self):
            self.status = status

        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return _Resp()


class MainGuardTest(unittest.TestCase):
    def test_tanpa_token_tidak_mengapa_gagal(self):
        env = {"GITHUB_REPOSITORY": "", "GITHUB_TOKEN": ""}
        with mock.patch.dict(c.os.environ, env, clear=False), \
                mock.patch.object(c, "chain_once") as chained:
            self.assertEqual(c.main([]), 0)
        chained.assert_not_called()

    def test_quiet_sec_dipotong_bila_lebih_besar_kadens(self):
        env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t",
               "GITHUB_REF_NAME": "main", "GITHUB_RUN_ID": "1"}
        with mock.patch.dict(c.os.environ, env, clear=False), \
                mock.patch.object(c, "chain_once", return_value=0) as chained:
            self.assertEqual(c.main(["--cadence", "300", "--quiet-sec",
                                     "900", "--no-sleep"]), 0)
        self.assertEqual(chained.call_args.kwargs["quiet_sec"], 240)


if __name__ == "__main__":
    unittest.main()
