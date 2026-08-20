"""GMGN HTTP resilience: no double-encoded tz, 403 rotates impersonate."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

import cvd


class _Resp:
    def __init__(self, status_code, payload=None, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class GmgnFetchTests(unittest.TestCase):
    def test_tz_name_is_not_pre_encoded(self):
        params = cvd._gmgn_build_params()
        self.assertEqual(params["tz_name"], "Asia/Jakarta")
        self.assertNotIn("%2F", params["tz_name"])
        self.assertNotIn("%252F", params["tz_name"])

    def test_token_referer_uses_ca(self):
        headers = cvd._gmgn_request_headers("Abc123pump")
        self.assertEqual(headers["referer"], "https://gmgn.ai/sol/token/Abc123pump")

    def test_curl_tls_failure_falls_back_to_requests(self):
        calls = []

        def bad_curl(*_args, **_kwargs):
            calls.append("curl")
            raise RuntimeError("TLS reset")

        fallback = _Resp(200, {"ok": True})
        fake_curl = types.ModuleType("curl_cffi")
        fake_curl.requests = types.SimpleNamespace(get=bad_curl)
        with patch.dict(sys.modules, {"curl_cffi": fake_curl}), \
                patch.object(cvd.requests, "get", return_value=fallback) as get:
            got = cvd._gmgn_http_get("https://example.test", params={},
                                     timeout=1)
        self.assertIs(got, fallback)
        self.assertEqual(len(calls), len(cvd.GMGN_IMPERSONATE))
        self.assertEqual(get.call_count, 1)

    def test_http_403_tries_next_impersonate(self):
        seen = []

        def fake_get(*_args, impersonate=None, **_kwargs):
            seen.append(impersonate)
            if impersonate != "chrome131":
                return _Resp(403, text="blocked",
                             headers={"server": "cloudflare",
                                      "cf-mitigated": "challenge"})
            return _Resp(200, {"code": 0, "data": {"history": []}})

        fake_curl = types.ModuleType("curl_cffi")
        fake_curl.requests = types.SimpleNamespace(get=fake_get)
        with patch.dict(sys.modules, {"curl_cffi": fake_curl}), \
                patch.object(cvd.requests, "get") as fallback:
            got = cvd._gmgn_http_get("https://example.test", params={},
                                     timeout=1)
        self.assertEqual(got.status_code, 200)
        self.assertIn("chrome131", seen)
        self.assertGreaterEqual(len(seen), 2)
        fallback.assert_not_called()

    def test_fetch_page_retries_403_then_succeeds(self):
        n = {"i": 0}

        def fake_http(*_args, **_kwargs):
            n["i"] += 1
            if n["i"] < 2:
                return _Resp(403, text="blocked",
                             headers={"server": "cloudflare",
                                      "cf-mitigated": "challenge"})
            return _Resp(200, {"code": 0, "data": {"history": [
                {"event": "buy", "timestamp": 1}]}})

        with patch.object(cvd, "_gmgn_http_get", side_effect=fake_http), \
                patch.object(cvd.time, "sleep", return_value=None):
            trades, _cursor = cvd._fetch_gmgn_page("CA")
        self.assertEqual(len(trades), 1)
        self.assertEqual(n["i"], 2)

    def test_fetch_page_drops_from_to_after_api_code(self):
        seen = []

        def fake_http(_url, *, params, **_kwargs):
            seen.append(dict(params))
            if "from" in params or "to" in params:
                return _Resp(200, {"code": 1, "message": "invalid from"})
            return _Resp(200, {"code": 0, "data": {"history": [
                {"event": "sell", "timestamp": 2}]}})

        with patch.object(cvd, "_gmgn_http_get", side_effect=fake_http), \
                patch.object(cvd.time, "sleep", return_value=None):
            trades, _cursor = cvd._fetch_gmgn_page("CA", from_ts=10, to_ts=20)
        self.assertEqual(len(trades), 1)
        self.assertIn("from", seen[0])
        self.assertNotIn("from", seen[1])

    def test_describe_mentions_cloudflare(self):
        text = cvd._describe_gmgn_http(_Resp(
            403, headers={"Server": "cloudflare", "cf-mitigated": "challenge"},
            text="just a moment"))
        self.assertIn("HTTP 403", text)
        self.assertIn("Cloudflare", text)
        self.assertIn("cf-mitigated=challenge", text)


if __name__ == "__main__":
    unittest.main()
