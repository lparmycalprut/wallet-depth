# -*- coding: utf-8 -*-
"""Sisa kredit Helius di panel 🧾 Log Aktivitas (permintaan user 2026-09-10).

Semua request ke metadata key (``/v0/keys``) di-stub. ``tests/__init__.py``
mematikan probe (``HELIUS_USAGE_PROBE=0``) supaya suite tetap offline — tes di
bawah menyalakannya lewat ``mock.patch.dict`` sendiri dan matikan lagi untuk
memastikan pembacaan cache tidak menyentuh jaringan.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

import activity_log as al
import core

ROOT = Path(__file__).resolve().parent.parent
PROBE_ON = {"HELIUS_USAGE_PROBE": "1"}


class _Response:
    """Stub ``requests.Response`` minimal (status + body JSON)."""

    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if self._payload is None:
            raise ValueError("body bukan JSON")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise core.requests.HTTPError(f"{self.status_code}")


def _get(payload, status: int = 200):
    return mock.patch.object(core.requests, "get",
                             return_value=_Response(payload, status))


def _key_payload(**over):
    item = {"name": "wallet-depth", "cluster": "mainnet", "permissions": "FULL",
            "rateLimit": {"max": 10, "period": 1},
            "credits": {"total": 1_000_000, "used": 187_655,
                        "available": 812_345}}
    item.update(over)
    return [item]


class _Probe(unittest.TestCase):
    """Boilerplate: probe ON, cache + log kosong, key pool = ``["k1"]``."""

    keys = ["k1"]

    def setUp(self):
        core.reset_helius_usage_cache()
        self.addCleanup(core.reset_helius_usage_cache)
        core._reset_helius_request_count()
        self.addCleanup(core._reset_helius_request_count)
        al.clear()
        self.addCleanup(al.clear)
        patcher = mock.patch.object(core, "get_helius_keys",
                                     return_value=list(self.keys))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _probe(self, payload, status: int = 200, keys=None):
        with mock.patch.dict(os.environ, PROBE_ON), \
                _get(payload, status):
            return core.helius_key_status(keys=list(keys or self.keys),
                                          refresh=True, timeout=1)


class ParseCreditsTest(unittest.TestCase):
    def test_objek_credits(self):
        self.assertEqual(core.parse_helius_credits(_key_payload()),
                         (1_000_000, 187_655, 812_345))

    def test_field_datar(self):
        self.assertEqual(core.parse_helius_credits({"creditsTotal": 500,
                                                    "creditsRemaining": 120}),
                         (500, None, 120))

    def test_angka_tunggal_dianggap_sisa(self):
        self.assertEqual(core.parse_helius_credits({"credits": 950_000}),
                         (None, None, 950_000))

    def test_tanpa_angka_kredit_kembali_none(self):
        self.assertEqual(
            core.parse_helius_credits([{"name": "k",
                                        "rateLimit": {"max": 10,
                                                      "period": 1}}]),
            (None, None, None))

    def test_beberapa_key_satu_project_tidak_dijumlah(self):
        """Plafon kredit dihitung per project — menjumlah = berlipat ganda."""
        payload = _key_payload() + _key_payload(name="wallet-depth-2")
        self.assertEqual(core.parse_helius_credits(payload),
                         (1_000_000, 187_655, 812_345))

    def test_string_angka_berpemisah_ribu(self):
        total, _used, remaining = core.parse_helius_credits(
            {"credits": {"total": "1,000,000", "available": "12,500"}})
        self.assertEqual((total, remaining), (1_000_000, 12_500))

    def test_sisa_dihitung_dari_total_kurang_pakai(self):
        self.assertEqual(
            core.parse_helius_credits({"credits": {"total": 100, "used": 40}}),
            (100, 40, 60))

    def test_pesan_error_tidak_membocorkan_key(self):
        text = core._scrub_key_text("GET /v0/keys?api-key=SECRETABC gagal")
        self.assertNotIn("SECRETABC", text)
        self.assertIn("api-key=***", text)


class KeyStatusTest(_Probe):
    def test_baris_penuh_dari_metadata_key(self):
        row = self._probe(_key_payload())[0]
        self.assertEqual(row["label"], "key#1")
        self.assertEqual(row["name"], "wallet-depth")
        self.assertEqual(row["total"], 1_000_000)
        self.assertEqual(row["remaining"], 812_345)
        self.assertAlmostEqual(row["percent_used"], 18.7655, places=3)
        self.assertEqual(row["rate_limit"], "10 rps")
        self.assertEqual(row["status"], "ok")

    def test_tanpa_key_tanpa_request(self):
        with mock.patch.dict(os.environ, PROBE_ON), \
                mock.patch.object(core.requests, "get") as get:
            self.assertEqual(core.helius_key_status(keys=[], refresh=True), [])
        get.assert_not_called()

    def test_probe_dimatikan_hanya_baca_cache(self):
        self._probe(_key_payload())            # isi cache
        with mock.patch.dict(os.environ, {"HELIUS_USAGE_PROBE": "0"}), \
                mock.patch.object(core.requests, "get") as get:
            rows = core.helius_key_status(keys=["k1"], refresh=True,
                                          timeout=1)
        get.assert_not_called()
        self.assertEqual(rows[0]["remaining"], 812_345)

    def test_cache_dipakai_tanpa_request_kedua(self):
        self._probe(_key_payload())
        with mock.patch.object(core.requests, "get") as get:
            rows = core.helius_key_status(keys=["k1"], timeout=1)
        get.assert_not_called()                 # masih segar (TTL 300 dtk)
        self.assertEqual(rows[0]["remaining"], 812_345)

    def test_daftar_key_berubah_membatalkan_cache(self):
        def _by_key(url, params=None, timeout=None, **kw):
            return _Response([{"name": {"k1": "satu", "k2": "kedua"}
                                [params["api-key"]],
                                "credits": {"available": 5}}])

        with mock.patch.dict(os.environ, PROBE_ON), \
                mock.patch.object(core.requests, "get", side_effect=_by_key):
            self.assertEqual(core.helius_key_status(keys=["k1"], refresh=True,
                                                     timeout=1)[0]["name"],
                             "satu")
            self.assertEqual(core.helius_key_status(keys=["k2"],
                                                    timeout=1)[0]["name"],
                             "kedua")

    def test_key_ditolak_status_rejected(self):
        rows = self._probe(None, status=401)
        self.assertEqual(rows[0]["status"], "rejected")
        self.assertIn("401", rows[0]["error"])
        # ❗ perlu tindakan user → level action (merah bold di panel).
        entry = al.entries()[0]
        self.assertEqual(entry["level"], al.LEVEL_ACTION)
        self.assertIn("HELIUS_API_KEY", entry["message"])

    def test_host_publik_tanpa_metadata_dicoba_host_kedua(self):
        seen: list[str] = []

        def _side_effect(url, params=None, timeout=None, **kw):
            seen.append(url)
            if len(seen) == 1:
                return _Response(None, 404)
            return _Response(_key_payload())

        with mock.patch.dict(os.environ, PROBE_ON), \
                mock.patch.object(core.requests, "get",
                                  side_effect=_side_effect):
            rows = core.helius_key_status(keys=["k1"], refresh=True, timeout=1)
        self.assertEqual(len(seen), 2)
        self.assertEqual(rows[0]["remaining"], 812_345)

    def test_network_error_jadi_warn_bukan_exception(self):
        with mock.patch.dict(os.environ, PROBE_ON), \
                mock.patch.object(core.requests, "get",
                                  side_effect=OSError("TLS/SSL closed")):
            rows = core.helius_key_status(keys=["k1"], refresh=True, timeout=1)
        self.assertEqual(rows[0]["status"], "unreachable")
        entry = al.entries()[0]
        self.assertEqual(entry["level"], al.LEVEL_WARN)
        self.assertNotIn("k1", entry["message"])       # key tak pernah tampil

    def test_kredit_habis_menjadi_action(self):
        rows = self._probe(_key_payload(credits={"total": 1_000_000,
                                                 "used": 1_000_000,
                                                 "available": 0}))
        self.assertEqual(rows[0]["remaining"], 0)
        entry = al.entries()[0]
        self.assertEqual(entry["level"], al.LEVEL_ACTION)
        self.assertIn("HABIS", entry["message"])

    def test_kredit_menipis_menjadi_warn(self):
        self._probe(_key_payload(credits={"total": 100, "used": 95,
                                          "available": 5}))
        entry = al.entries()[0]
        self.assertEqual(entry["level"], al.LEVEL_WARN)
        self.assertIn("menipis", entry["message"])

    def test_plan_tanpa_laporan_kredit_bukan_kejadian_log(self):
        rows = self._probe([{"name": "free",
                             "rateLimit": {"max": 10, "period": 1}}])
        self.assertEqual(rows[0]["status"], "no_credit_data")
        self.assertEqual(al.entries(), [])   # hidup, cuma tidak lapor angka


class SummaryTest(_Probe):
    def test_satu_baris_sisa_kredit(self):
        self._probe(_key_payload())
        for _ in range(37):
            core._count_helius_call()
        summary = core.helius_usage_summary(background=False)
        self.assertIn("Helius API: 1 key", summary)
        self.assertIn("kredit tersisa 812,345 dari 1,000,000", summary)
        self.assertIn("pakai 18.8%", summary)
        self.assertIn("±37 request sesi ini", summary)

    def test_angka_identik_dari_beberapa_key_disebut_sekali(self):
        """Dua key satu project = satu plafon; jangan ditulis dua kali."""
        with mock.patch.object(core, "get_helius_keys",
                               return_value=["k1", "k2"]):
            self._probe(_key_payload(), keys=["k1", "k2"])
            summary = core.helius_usage_summary(background=False)
        self.assertIn("Helius API: 2 key", summary)
        self.assertEqual(summary.count("kredit tersisa 812,345"), 1)

    def test_plan_tanpa_kredit_dijelaskan_jujur(self):
        self._probe([{"name": "free", "rateLimit": {"max": 10, "period": 1}}])
        summary = core.helius_usage_summary(background=False)
        self.assertIn("tidak mengirim angka kredit", summary)
        self.assertIn("dashboard.helius.dev", summary)

    def test_cache_kosong_mengatakan_sedang_dicek(self):
        with mock.patch.object(core, "helius_usage_status",
                               return_value={"rows": [], "total_keys": 1,
                                             "refreshing": True,
                                             "cache_age_sec": None}):
            summary = core.helius_usage_summary()
        self.assertIn("sedang dicek", summary)

    def test_tanpa_key_menyuruh_pasang_key(self):
        with mock.patch.object(core, "get_helius_keys", return_value=[]):
            summary = core.helius_usage_summary(background=False)
        self.assertIn("belum ada key terpasang", summary)
        self.assertIn("HELIUS_API_KEY", summary)

    def test_helius_credit_remaining_total(self):
        self._probe(_key_payload())
        self.assertEqual(core.helius_credit_remaining(), 812_345)

    def test_helius_credit_remaining_none_bila_tidak_dilaporkan(self):
        self._probe([{"name": "free"}])
        self.assertIsNone(core.helius_credit_remaining())


class SumberKeyTest(unittest.TestCase):
    """Placeholder config.json tidak boleh menutupi secrets (bug lama)."""

    def test_placeholder_disaring(self):
        self.assertEqual(
            core.merge_helius_keys("PASTE-API-KEY-KAMU-DISINI", "realtoken"),
            ["realtoken"])
        self.assertEqual(core.merge_helius_keys("your_api_key"), [])

    def test_secrets_menang_atas_config_json(self):
        with mock.patch.object(core, "_config_file",
                               return_value={"helius_api_key": "key-lama"}), \
                mock.patch.object(core, "_streamlit_helius_keys",
                                  return_value=["key-secrets"]):
            self.assertEqual(core.get_helius_keys()[0], "key-secrets")

    def test_nilai_eksplisit_tetap_paling_depan(self):
        with mock.patch.object(core, "_config_file",
                               return_value={"helius_api_key": "key-lama"}), \
                mock.patch.object(core, "_streamlit_helius_keys",
                                  return_value=["key-secrets"]):
            self.assertEqual(core.get_helius_keys(primary="key-sidebar"),
                             ["key-sidebar", "key-secrets", "key-lama"])


class RequestCounterTest(unittest.TestCase):
    def test_setiap_request_sukses_naik_satu(self):
        class _R:
            status_code = 200

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {"jsonrpc": "2.0", "id": 1, "result": {"value": 1}}

        core._reset_helius_request_count()
        with mock.patch.object(core.requests, "post", return_value=_R()):
            core.helius_rpc("getSlot", [], helius_keys=["k1"])
        self.assertEqual(core.helius_request_count(), 1)

    def test_request_gagal_tidak_dihitung(self):
        core._reset_helius_request_count()
        with mock.patch.object(core.requests, "post",
                               side_effect=OSError("TLS closed")):
            with self.assertRaises(Exception):
                core.helius_rpc("getSlot", [], helius_keys=["k1"])
        self.assertEqual(core.helius_request_count(), 0)
        core._reset_helius_request_count()


class PanelLogTest(unittest.TestCase):
    """Panel 🧾 benar-benar menampilkan baris kredit Helius (AppTest)."""

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest  # noqa: F401
        except Exception:  # noqa: BLE001
            raise unittest.SkipTest("streamlit/AppTest tidak terpasang")

    def test_caption_helius_dirender_di_panel_log(self):
        from streamlit.testing.v1 import AppTest

        text = "Helius API: 1 key · key#1 kredit tersisa 500 dari 1.000"
        with mock.patch.object(core, "helius_usage_summary",
                               return_value=text):
            app = AppTest.from_file(str(ROOT / "app.py"),
                                    default_timeout=90).run()
        self.assertEqual(len(app.exception), 0)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("kredit tersisa 500 dari 1.000", captions)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
