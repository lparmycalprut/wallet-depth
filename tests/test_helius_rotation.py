# -*- coding: utf-8 -*-
"""Unit tests for the shared Helius multi-key pool and failover.

Runs without pytest and without network:
    python3 tests/test_helius_rotation.py
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402

failures = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)


def test_key_sources_are_merged_and_deduplicated():
    print("\n[key pool] main + extras + env + secrets are merged once")
    with tempfile.TemporaryDirectory() as tmp:
        config_path = os.path.join(tmp, "config.json")
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump({
                "helius_api_key": "main-key",
                "helius_extra_keys": " extra-a, main-key\nextra-b ",
            }, handle)

        env = {
            "HELIUS_API_KEY": "env-key",
            "HELIUS_API_KEYS": "extra-b, env-extra",
        }
        secret_keys = ["secret-key", "extra-a", "secret-extra"]
        with patch.object(core, "CONFIG_PATH", config_path), \
                patch.dict(os.environ, env), \
                patch.object(core, "_streamlit_helius_keys",
                             return_value=secret_keys):
            keys = core.get_helius_keys()

    expected = ["main-key", "extra-a", "extra-b", "env-key",
                "env-extra", "secret-key", "secret-extra"]
    check(keys == expected, f"all sources preserve order and de-dup: {keys}")
    check(keys.count("main-key") == 1 and keys.count("extra-a") == 1,
          "duplicates across main/extra/secrets occur only once")


def test_429_rotates_to_next_key():
    print("\n[failover] HTTP 429 falls through to the next key")
    seen_keys = []

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(
                    f"{self.status_code} simulated Helius response",
                    response=self)

    responses = [
        Response(429, {"error": {"code": 429, "message": "rate limit"}}),
        Response(200, {"jsonrpc": "2.0", "id": 1,
                       "result": {"value": "worked"}}),
    ]

    def fake_post(_url, **kwargs):
        seen_keys.append(kwargs["params"]["api-key"])
        return responses.pop(0)

    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(core, "CONFIG_PATH", os.path.join(tmp, "missing")), \
            patch.dict(os.environ,
                       {"HELIUS_API_KEY": "", "HELIUS_API_KEYS": ""}), \
            patch.object(core, "_streamlit_helius_keys", return_value=[]), \
            patch.object(core.requests, "post", side_effect=fake_post):
        core._reset_helius_rotation()
        result = core.helius_rpc("testMethod", [], ("key-one", "key-two"))

    check(seen_keys == ["key-one", "key-two"],
          f"request rotated after 429: {seen_keys}")
    check(result == {"value": "worked"},
          "the successful second-key response is returned")


if __name__ == "__main__":
    test_key_sources_are_merged_and_deduplicated()
    test_429_rotates_to_next_key()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    for failure in failures:
        print("  -", failure)
    sys.exit(1 if failures else 0)
