# -*- coding: utf-8 -*-
"""Transport Blockscout Robinhood Chain: PRO API → instance publik.

Latar (2026-09-08): instance publik ``robinhoodchain.blockscout.com`` mulai
menolak request script dengan **HTTP 403** bot-protection (halaman
"Just a moment…" Cloudflare) — ``getToken``, CSV export, dan REST v2 gagal
serentak sehingga Scan Holder Khusus menulis "Scan tidak menghasilkan
holder. Pastikan CA valid …" untuk CA yang sah (Pusheen ``0x1209ec…``,
409 holder). Suite ini mengunci perilaku barunya:

- ada ``BLOCKSCOUT_API_KEY`` → semua request lewat
  ``https://api.blockscout.com/4663/…`` dengan ``Authorization: Bearer``
  (key tidak pernah muncul di URL/pesan error);
- tanpa key → instance publik dengan profil TLS browser yang dirotasi saat
  403, lalu ``requests`` biasa;
- semua ditolak → ``BlockscoutBlocked`` (bukan transient, tidak di-retry),
  ``fetch_holders`` pulang ``blocked: True`` + satu kalimat petunjuk,
  ``analyze_token``/``scan_token_holders`` meneruskan penandanya;
- ``source`` hasil sukses diberi akhiran rute (``blockscout-csv@pro``).

Tidak menembus jaringan: ``requests.get`` dan ``_curl_requests`` di-mock.
"""
from __future__ import annotations

import os
import types
import unittest
from unittest import mock

import requests

import robinhood_holders as rh


CA = "0x1209ec401498a1b781412576c978eee0daa0bb6e"
CSV_BODY = ("HolderAddress,Balance\n"
            "0x8366a39CC670B4001A1121B8F6A443A643e40951,146292445.7\n"
            "0xc88252fcf1690E45195F690F9A6c1B6423AfFAcc,31142024.5\n"
            "0x606Cb3CAc9291693F18972a96273EeC67A0cd004,1.5\n")
TOKEN_INFO = {"status": "1", "result": {
    "decimals": "18", "symbol": "Pusheen", "name": "Pusheen",
    "totalSupply": "1000000000000000000000000000"}}


class _Resp:
    def __init__(self, status, text="", payload=None, headers=None):
        self.status_code = status
        self.text = text
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code),
                                                response=self)


def _challenge():
    """403 Cloudflare persis seperti yang dilihat 2026-09-08."""
    return _Resp(403, "<!DOCTYPE html><html><head><title>Just a moment..."
                      "</title></head><body>…</body></html>",
                 headers={"server": "cloudflare",
                          "cf-mitigated": "challenge"})


def _ok_public(url, params=None, **_kw):
    if url.endswith("/counters"):
        return _Resp(200, payload={"token_holders_count": "3"})
    if url.endswith("/holders/csv"):
        return _Resp(200, text=CSV_BODY)
    if url.endswith("/api"):
        return _Resp(200, payload=TOKEN_INFO)
    return _Resp(404, payload={"message": "Not found"})


def _no_key():
    """Pastikan tidak ada key dari env/config/secrets host pengembang."""
    return mock.patch.multiple(
        rh,
        _config_pro_keys=mock.Mock(return_value=[]),
        _secrets_pro_keys=mock.Mock(return_value=[]),
    )


def _only_env_keys():
    """Config/secrets dimatikan; key hanya dari env (dipakai test multi-key)."""
    return _no_key()


class _Base(unittest.TestCase):
    def setUp(self):
        rh.clear_holder_cache()
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for name in rh._PRO_KEY_ENV:
            os.environ.pop(name, None)
        sleep = mock.patch.object(rh.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        self.addCleanup(self._env.stop)
        self.addCleanup(rh.clear_holder_cache)


class ProApiKeyTest(_Base):
    def test_key_dibaca_dari_env_lalu_config_lalu_secrets(self):
        with _no_key():
            self.assertEqual(rh.get_pro_api_key(), "")
            self.assertEqual(rh.get_pro_api_keys(), [])
            self.assertFalse(rh.pro_keys_configured())
        with mock.patch.dict(os.environ, {"BLOCKSCOUT_API_KEY": " proapi_env "}), \
                _no_key():
            self.assertEqual(rh.get_pro_api_key(), "proapi_env")
        with mock.patch.object(rh, "_config_pro_keys", return_value=["proapi_cfg"]), \
                mock.patch.object(rh, "_secrets_pro_keys", return_value=["proapi_sec"]):
            self.assertEqual(rh.get_pro_api_key(), "proapi_cfg")
            # sumber digabung, bukan saling menimpa (pola Helius)
            self.assertEqual(rh.get_pro_api_keys(), ["proapi_cfg", "proapi_sec"])
        with mock.patch.object(rh, "_config_pro_keys", return_value=[]), \
                mock.patch.object(rh, "_secrets_pro_keys", return_value=["proapi_sec"]):
            self.assertEqual(rh.get_pro_api_key(), "proapi_sec")

    def test_banyak_key_dari_env_daftar_koma_dan_baris_baru(self):
        env = {"BLOCKSCOUT_API_KEY": "proapi_1",
               "BLOCKSCOUT_API_KEYS": "proapi_2, proapi_3\nproapi_1\n\nproapi_4 "}
        with mock.patch.dict(os.environ, env), _no_key():
            keys = rh.get_pro_api_keys()
            configured = rh.pro_keys_configured()
        # urut sesuai sumber, duplikat (proapi_1) dibuang, spasi dibersihkan
        self.assertEqual(keys, ["proapi_1", "proapi_2", "proapi_3", "proapi_4"])
        self.assertTrue(configured)

    def test_config_json_menerima_dua_nama_kunci(self):
        import json
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"blockscout_api_key": "proapi_a",
                       "blockscout_api_keys": "proapi_b,proapi_c"}, fh)
            path = fh.name
        self.addCleanup(os.unlink, path)
        with mock.patch.object(rh, "CONFIG_PATH", path), \
                mock.patch.object(rh, "_secrets_pro_keys", return_value=[]):
            self.assertEqual(rh.get_pro_api_keys(),
                             ["proapi_a", "proapi_b", "proapi_c"])

    def test_secrets_menerima_daftar_maupun_string(self):
        fake_secrets = {"blockscout_api_keys": ["proapi_x", "proapi_y"],
                        "BLOCKSCOUT_API_KEY": "proapi_z"}
        fake_st = types.SimpleNamespace(secrets=fake_secrets)
        with mock.patch.dict("sys.modules", {"streamlit": fake_st}), \
                mock.patch.object(rh, "_config_pro_keys", return_value=[]):
            keys = rh.get_pro_api_keys()
        self.assertEqual(keys, ["proapi_x", "proapi_y", "proapi_z"])

    def test_pro_url_menyisipkan_chain_id_dengan_path_identik(self):
        self.assertEqual(
            rh._pro_url(f"{rh.BLOCKSCOUT_V2}/tokens/{CA}/holders/csv"),
            f"https://api.blockscout.com/4663/api/v2/tokens/{CA}/holders/csv")
        self.assertEqual(rh._pro_url(rh.BLOCKSCOUT_API),
                         "https://api.blockscout.com/4663/api")
        # URL PRO tidak diprefiks dua kali
        pro = "https://api.blockscout.com/4663/api/v2/stats"
        self.assertEqual(rh._pro_url(pro), pro)


class ProRouteTest(_Base):
    def test_dengan_key_semua_request_lewat_pro_api_bearer(self):
        seen = []

        def fake_get(url, params=None, headers=None, timeout=None):
            seen.append((url, dict(headers or {})))
            return _ok_public(url, params)

        with mock.patch.dict(os.environ, {"BLOCKSCOUT_API_KEY": "proapi_TEST"}), \
                _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=None):
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)

        self.assertEqual(out["fetched"], 3)
        self.assertFalse(out["blocked"])
        self.assertEqual(out["source"], f"{rh.SOURCE_CSV}@{rh.ROUTE_PRO}")
        self.assertTrue(seen)
        for url, headers in seen:
            self.assertTrue(url.startswith("https://api.blockscout.com/4663/"),
                            url)
            self.assertEqual(headers.get("authorization"), "Bearer proapi_TEST")
            self.assertNotIn("proapi_TEST", url)   # key tidak di query string

    def test_pro_401_jatuh_ke_publik_dan_tetap_sukses(self):
        def fake_get(url, params=None, headers=None, timeout=None):
            if url.startswith(rh.BLOCKSCOUT_PRO_BASE):
                return _Resp(401, payload={"error": "Invalid API key"})
            return _ok_public(url, params)

        with mock.patch.dict(os.environ, {"BLOCKSCOUT_API_KEY": "proapi_BAD"}), \
                _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=None):
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)
        self.assertEqual(out["fetched"], 3)
        self.assertEqual(out["source"], f"{rh.SOURCE_CSV}@{rh.ROUTE_PUBLIC}")

    def test_pro_402_kredit_habis_juga_jatuh_ke_publik(self):
        def fake_get(url, params=None, headers=None, timeout=None):
            if url.startswith(rh.BLOCKSCOUT_PRO_BASE):
                return _Resp(402, payload={"error": "Out of credits"})
            return _ok_public(url, params)

        with mock.patch.dict(os.environ, {"BLOCKSCOUT_API_KEY": "proapi_X"}), \
                _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=None):
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)
        self.assertEqual(out["fetched"], 3)
        self.assertEqual(out["source"], f"{rh.SOURCE_CSV}@{rh.ROUTE_PUBLIC}")

    def test_pro_dan_publik_gagal_pesan_menyebut_keduanya_tanpa_key(self):
        def fake_get(url, params=None, headers=None, timeout=None):
            if url.startswith(rh.BLOCKSCOUT_PRO_BASE):
                return _Resp(401, payload={"error": "Invalid API key"})
            return _challenge()

        curl = types.SimpleNamespace(get=lambda *a, **k: _challenge())
        with mock.patch.dict(os.environ, {"BLOCKSCOUT_API_KEY": "proapi_RAHASIA"}), \
                _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=curl):
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)
        self.assertEqual(out["fetched"], 0)
        self.assertTrue(out["blocked"])
        self.assertIn("403", out["error"])
        self.assertIn("PRO: PRO API 401 Invalid API key (key#1)", out["error"])
        self.assertIn(rh.BlockscoutBlocked.HINT_KEYS_FAILED, out["error"])
        self.assertNotIn("proapi_RAHASIA", out["error"])


class ProKeyPoolTest(_Base):
    """Beberapa key PRO: round-robin, parkir per status, tidak bocor."""

    KEYS = {"BLOCKSCOUT_API_KEYS": "proapi_A,proapi_B,proapi_C"}

    @staticmethod
    def _bearer(headers) -> str:
        return str((headers or {}).get("authorization") or "").replace("Bearer ", "")

    def test_request_dibagi_round_robin_ke_semua_key(self):
        used = []

        def fake_get(url, params=None, headers=None, timeout=None):
            used.append(self._bearer(headers))
            return _ok_public(url, params)

        with mock.patch.dict(os.environ, self.KEYS), _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=None):
            rh.clear_holder_cache()
            for _ in range(6):
                rh._jsjson({"module": "token"})
        self.assertEqual(used, ["proapi_A", "proapi_B", "proapi_C"] * 2)

    def test_402_kredit_habis_memarkir_key_dan_pindah_ke_key_lain(self):
        used = []

        def fake_get(url, params=None, headers=None, timeout=None):
            key = self._bearer(headers)
            used.append(key)
            if key == "proapi_A":
                return _Resp(402, payload={"error": "Out of credits"},
                             headers={"x-credits-remaining": "0"})
            return _Resp(200, payload=TOKEN_INFO,
                         headers={"x-credits-remaining": "98765"})

        with mock.patch.dict(os.environ, self.KEYS), _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=None), \
                mock.patch.object(rh.time, "sleep") as sleep:
            rh.clear_holder_cache()
            for _ in range(4):
                payload = rh._jsjson({"module": "token"})
                self.assertEqual(payload["status"], "1")
            status = {row["label"]: row for row in rh.pro_key_status()}
            summary = rh.pro_key_summary()
        # A dicoba sekali (402) lalu diparkir; sisanya bergantian B/C tanpa
        # menyentuh A lagi; tidak ada backoff (402 bukan transient).
        self.assertEqual(used[:2], ["proapi_A", "proapi_B"])
        self.assertNotIn("proapi_A", used[2:])
        self.assertEqual(len(used), 5)
        # beban rata di antara key yang masih aktif
        self.assertEqual(sorted(used[2:]), ["proapi_B", "proapi_C", "proapi_C"])
        sleep.assert_not_called()
        self.assertFalse(status["key#1"]["active"])
        self.assertEqual(status["key#1"]["parked_status"], 402)
        self.assertEqual(status["key#1"]["credits_remaining"], 0)
        self.assertTrue(status["key#2"]["active"])
        self.assertEqual(status["key#2"]["credits_remaining"], 98765)
        self.assertIn("key#1 parkir 402 kredit habis", summary)
        self.assertIn("key#2 sisa 98,765 kredit", summary)
        # key asli tidak pernah muncul di ringkasan/status
        self.assertNotIn("proapi_", summary)
        self.assertNotIn("proapi_", repr(status))

    def test_429_memarkir_sebentar_sesuai_header_reset(self):
        used = []

        def fake_get(url, params=None, headers=None, timeout=None):
            key = self._bearer(headers)
            used.append(key)
            if key == "proapi_A":
                return _Resp(429, payload={"error": "rate limited"},
                             headers={"x-ratelimit-reset": "1500"})
            return _Resp(200, payload=TOKEN_INFO)

        with mock.patch.dict(os.environ, self.KEYS), _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=None), \
                mock.patch.object(rh.time, "sleep") as sleep:
            rh.clear_holder_cache()
            self.assertEqual(rh._jsjson({"module": "token"})["status"], "1")
            status = {row["label"]: row for row in rh.pro_key_status()}
        self.assertEqual(used, ["proapi_A", "proapi_B"])
        sleep.assert_not_called()             # tidak menunggu; pindah key
        self.assertEqual(status["key#1"]["parked_status"], 429)
        self.assertLessEqual(status["key#1"]["parked_for_sec"], 2)

    def test_key_yang_diparkir_dicoba_lagi_setelah_masa_parkir_habis(self):
        calls = {"A": 0}

        def fake_get(url, params=None, headers=None, timeout=None):
            key = self._bearer(headers)
            if key == "proapi_A":
                calls["A"] += 1
                if calls["A"] == 1:
                    return _Resp(402, payload={"error": "Out of credits"})
            return _Resp(200, payload=TOKEN_INFO)

        with mock.patch.dict(os.environ, {"BLOCKSCOUT_API_KEYS": "proapi_A,proapi_B"}), \
                _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=None):
            rh.clear_holder_cache()
            rh._jsjson({"module": "token"})          # A 402 → parkir, B ok
            rh._jsjson({"module": "token"})          # B (giliran) ok
            self.assertEqual(calls["A"], 1)
            # majukan jam melewati masa parkir 402 → A dicoba lagi
            future = rh.time.time() + rh.PRO_PARK_SEC[402] + 1
            with mock.patch.object(rh.time, "time", return_value=future):
                rh._jsjson({"module": "token"})
                rh._jsjson({"module": "token"})
            self.assertEqual(calls["A"], 2)

    def test_semua_key_gagal_jatuh_ke_publik_dan_pesan_menyebut_key_habis(self):
        def fake_get(url, params=None, headers=None, timeout=None):
            if url.startswith(rh.BLOCKSCOUT_PRO_BASE):
                return _Resp(402, payload={"error": "Out of credits"})
            return _challenge()

        curl = types.SimpleNamespace(get=lambda *a, **k: _challenge())
        with mock.patch.dict(os.environ, self.KEYS), _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=curl):
            rh.clear_holder_cache()
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)
        self.assertEqual(out["fetched"], 0)
        self.assertTrue(out["blocked"])
        self.assertEqual(out["pro_keys"], 3)
        self.assertEqual(out["pro_key"], "")
        msg = out["error"]
        self.assertIn("403", msg)
        self.assertIn("PRO: PRO API 402 Out of credits (key#", msg)
        # petunjuknya bukan lagi "pasang key" — key sudah ada
        self.assertIn("semuanya ditolak / kreditnya habis", msg)
        self.assertNotIn("pasang BLOCKSCOUT_API_KEY", msg)
        self.assertNotIn("proapi_", msg)

    def test_semua_key_parkir_tapi_publik_lolos_tetap_sukses(self):
        def fake_get(url, params=None, headers=None, timeout=None):
            if url.startswith(rh.BLOCKSCOUT_PRO_BASE):
                return _Resp(401, payload={"error": "Invalid API key"})
            return _ok_public(url, params)

        with mock.patch.dict(os.environ, self.KEYS), _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh, "_curl_requests", return_value=None):
            rh.clear_holder_cache()
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)
        self.assertEqual(out["fetched"], 3)
        self.assertEqual(out["source"], f"{rh.SOURCE_CSV}@{rh.ROUTE_PUBLIC}")
        self.assertEqual(out["pro_key"], "")
        self.assertFalse(out["blocked"])

    def test_fetch_holders_melaporkan_label_key_yang_dipakai(self):
        with mock.patch.dict(os.environ, self.KEYS), _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=_ok_public), \
                mock.patch.object(rh, "_curl_requests", return_value=None):
            rh.clear_holder_cache()
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)
        self.assertEqual(out["source"], f"{rh.SOURCE_CSV}@{rh.ROUTE_PRO}")
        self.assertRegex(out["pro_key"], r"^key#[123]$")
        self.assertEqual(out["pro_keys"], 3)

    def test_analyze_token_membawa_pro_keys_dan_pro_key(self):
        market = {"price_usd": 0.001, "marketcap": 1_000.0, "symbol": "PUSHEEN",
                  "pair_addresses": []}
        with mock.patch.dict(os.environ, self.KEYS), _no_key(), \
                mock.patch.object(rh.requests, "get", side_effect=_ok_public), \
                mock.patch.object(rh, "_curl_requests", return_value=None), \
                mock.patch.object(rh, "get_market", return_value=market):
            rh.clear_holder_cache()
            analysis = rh.analyze_token(CA, "PUSHEEN")
        holders = analysis["holders"]
        self.assertEqual(holders["pro_keys"], 3)
        self.assertRegex(holders["pro_key"], r"^key#[123]$")
        self.assertNotIn("blocked", holders)

    def test_pool_dibangun_ulang_saat_daftar_key_berubah(self):
        with _no_key(), mock.patch.dict(os.environ, {"BLOCKSCOUT_API_KEYS": "proapi_A"}):
            rh.clear_holder_cache()
            self.assertEqual([r["label"] for r in rh.pro_key_status()], ["key#1"])
        with _no_key(), mock.patch.dict(os.environ, self.KEYS):
            self.assertEqual([r["label"] for r in rh.pro_key_status()],
                             ["key#1", "key#2", "key#3"])
        with _no_key():
            os.environ.pop("BLOCKSCOUT_API_KEYS", None)
            self.assertEqual(rh.pro_key_status(), [])
            self.assertEqual(rh.pro_key_summary(), "")


class PublicRouteTest(_Base):
    def test_403_challenge_menjadi_BlockscoutBlocked_dan_tidak_diretry(self):
        curl = types.SimpleNamespace(get=lambda *a, **k: _challenge())
        with _no_key(), \
                mock.patch.object(rh, "_curl_requests", return_value=curl), \
                mock.patch.object(rh.requests, "get",
                                  return_value=_challenge()) as plain, \
                mock.patch.object(rh.time, "sleep") as sleep:
            with self.assertRaises(rh.BlockscoutBlocked) as ctx:
                rh._jsjson({"module": "token", "action": "getToken",
                            "contractaddress": CA})
        exc = ctx.exception
        self.assertFalse(rh.is_transient_error(exc))
        self.assertTrue(rh.is_blocked_error(exc))
        sleep.assert_not_called()               # 403 bukan transient
        self.assertEqual(plain.call_count, 1)   # requests biasa dicoba sekali
        msg = str(exc)
        self.assertIn("403", msg)
        self.assertIn("BLOCKSCOUT_API_KEY", msg)
        self.assertIn(rh.BLOCKSCOUT_KEY_URL, msg)
        self.assertIn("cf-mitigated=challenge", msg)
        self.assertNotIn("Forbidden for url", msg)

    def test_rotasi_profil_tls_403_lalu_profil_lain_lolos(self):
        tried = []

        def curl_get(url, params=None, headers=None, impersonate=None,
                     timeout=None):
            tried.append(impersonate)
            if impersonate != "chrome131":
                return _challenge()
            return _ok_public(url, params)

        curl = types.SimpleNamespace(get=curl_get)
        with _no_key(), \
                mock.patch.object(rh, "_curl_requests", return_value=curl), \
                mock.patch.object(rh.requests, "get") as plain:
            payload = rh._jsjson({"module": "token", "action": "getToken",
                                  "contractaddress": CA})
        self.assertEqual(payload["status"], "1")
        self.assertEqual(tried, ["chrome", "chrome136", "chrome131"])
        plain.assert_not_called()

    def test_impersonate_header_ua_tidak_menimpa_profil(self):
        captured = {}

        def curl_get(url, params=None, headers=None, impersonate=None,
                     timeout=None):
            captured.update(headers or {})
            return _ok_public(url, params)

        with _no_key(), \
                mock.patch.object(rh, "_curl_requests",
                                  return_value=types.SimpleNamespace(get=curl_get)):
            rh._jsjson({"module": "token"})
        self.assertNotIn("user-agent", {k.lower() for k in captured})
        self.assertIn("accept", {k.lower() for k in captured})

    def test_curl_cffi_rusak_jatuh_ke_requests_biasa(self):
        def boom(*_a, **_k):
            raise RuntimeError("Impersonating chrome999 is not supported")

        with _no_key(), \
                mock.patch.object(rh, "_curl_requests",
                                  return_value=types.SimpleNamespace(get=boom)), \
                mock.patch.object(rh.requests, "get",
                                  side_effect=_ok_public) as plain:
            payload = rh._jsjson({"module": "token"})
        self.assertEqual(payload["status"], "1")
        self.assertEqual(plain.call_count, 1)

    def test_tanpa_curl_cffi_requests_biasa_tetap_dipakai(self):
        with _no_key(), \
                mock.patch.object(rh, "_curl_requests", return_value=None), \
                mock.patch.object(rh.requests, "get",
                                  side_effect=_ok_public):
            response = rh._http_get(f"{rh.BLOCKSCOUT_V2}/tokens/{CA}/counters")
        self.assertEqual(response.json()["token_holders_count"], "3")
        self.assertEqual(rh._route_of(response), rh.ROUTE_PUBLIC)

    def test_503_berbadan_challenge_ikut_dianggap_blokir(self):
        cf503 = _Resp(503, "<html><title>Just a moment...</title></html>",
                      headers={"server": "cloudflare"})
        with _no_key(), \
                mock.patch.object(rh, "_curl_requests", return_value=None), \
                mock.patch.object(rh.requests, "get", return_value=cf503), \
                mock.patch.object(rh.time, "sleep") as sleep:
            with self.assertRaises(rh.BlockscoutBlocked):
                rh._jsjson({"module": "token"})
        sleep.assert_not_called()

    def test_429_biasa_masih_transient_dan_diulang(self):
        calls = []

        def fake_get(*_a, **_k):
            calls.append(1)
            if len(calls) == 1:
                return _Resp(429, payload={"message": "Too Many Requests"})
            return _Resp(200, payload=TOKEN_INFO)

        with _no_key(), \
                mock.patch.object(rh, "_curl_requests", return_value=None), \
                mock.patch.object(rh.requests, "get", side_effect=fake_get), \
                mock.patch.object(rh.time, "sleep") as sleep:
            payload = rh._jsjson({"module": "token"})
        self.assertEqual(payload["status"], "1")
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once()


class FetchHoldersBlockedTest(_Base):
    """Regresi laporan user: tiga URL 403 → satu kalimat + penanda ``blocked``."""

    def _all_blocked(self):
        curl = types.SimpleNamespace(get=lambda *a, **k: _challenge())
        return (mock.patch.object(rh, "_curl_requests", return_value=curl),
                mock.patch.object(rh.requests, "get",
                                  return_value=_challenge()))

    def test_fetch_holders_semua_jalur_403(self):
        p1, p2 = self._all_blocked()
        with _no_key(), p1, p2:
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)
        self.assertEqual(out["fetched"], 0)
        self.assertEqual(out["holders"], [])
        self.assertTrue(out["blocked"])
        self.assertEqual(out["source"], f"{rh.SOURCE_CSV}(fail)")
        # satu kalimat, bukan "getToken: 403…; csv: 403…; v2: 403…"
        self.assertEqual(out["error"].count("403"), 1)
        self.assertNotIn("Forbidden for url", out["error"])
        self.assertIn("BLOCKSCOUT_API_KEY", out["error"])

    def test_fetch_holders_403_dengan_decimals_diketahui(self):
        """decimals dari pemanggil → jalur RPC ikut dicoba; tetap satu pesan."""
        p1, p2 = self._all_blocked()
        with _no_key(), p1, p2:
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=18,
                                   total_supply=1e9)
        self.assertTrue(out["blocked"])
        self.assertEqual(out["error"].count("403"), 1)

    def test_analyze_token_dan_scan_meneruskan_penanda_blocked(self):
        market = {"price_usd": 0.001, "marketcap": 1_000.0, "symbol": "PUSHEEN",
                  "pair_addresses": []}
        p1, p2 = self._all_blocked()
        with _no_key(), p1, p2, \
                mock.patch.object(rh, "get_market", return_value=market):
            analysis = rh.analyze_token(CA, "PUSHEEN")
            rh.clear_holder_cache()
            scan = rh.scan_token_holders(CA)
        holders = analysis["holders"]
        self.assertEqual(holders["total_fetched"], 0)
        self.assertTrue(holders["blocked"])
        self.assertIn("403", holders["fetch_error"])
        self.assertTrue(scan["scan_failed"])
        self.assertTrue(scan["snapshot"]["blocked"])

    def test_sukses_tidak_membawa_penanda_blocked(self):
        with _no_key(), \
                mock.patch.object(rh, "_curl_requests", return_value=None), \
                mock.patch.object(rh.requests, "get", side_effect=_ok_public):
            out = rh.fetch_holders(CA, price_usd=0.001, decimals=None)
        self.assertEqual(out["fetched"], 3)
        self.assertFalse(out["blocked"])
        self.assertEqual(out["error"], "")


class SourceRouteLabelTest(unittest.TestCase):
    def test_source_with_route_dan_source_base(self):
        self.assertEqual(rh.source_with_route("blockscout-csv", "pro"),
                         "blockscout-csv@pro")
        self.assertEqual(rh.source_with_route("blockscout-v2", "public"),
                         "blockscout-v2@public")
        self.assertEqual(rh.source_with_route("blockscout-csv", ""),
                         "blockscout-csv")
        self.assertEqual(rh.source_with_route("blockscout-csv(fail)", "pro"),
                         "blockscout-csv(fail)")
        self.assertEqual(rh.source_with_route("blockscout-csv@pro", "public"),
                         "blockscout-csv@pro")
        self.assertEqual(rh.source_base("blockscout-rpc@public"),
                         "blockscout-rpc")
        self.assertEqual(rh.source_base("blockscout-rpc"), "blockscout-rpc")

    def test_route_label_untuk_ui(self):
        """Dipakai ``app._scan_source_meta`` (AppTest-nya di test_rh_card_ui)."""
        self.assertEqual(rh.route_label("blockscout-csv@pro"), "PRO API")
        self.assertEqual(rh.route_label("blockscout-v2@public"),
                         "instance publik")
        self.assertEqual(rh.route_label("blockscout-csv"), "")
        self.assertEqual(rh.route_label("blockscout-csv(fail)"), "")
        self.assertEqual(rh.route_label(""), "")
        self.assertEqual(rh.route_label("blockscout-csv@aneh"), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
