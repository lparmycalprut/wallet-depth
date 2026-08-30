"""Coverage dasar scanner cron silent-accumulation."""
from __future__ import annotations

import unittest
from unittest import mock

from scripts.scan_silent import scan_watchlist


class LegacyBridgeTest(unittest.TestCase):
    def test_realtime_reversal_bridge_forwards_to_silent_scanner(self):
        import scripts.realtime_reversal as bridge
        with mock.patch("scripts.scan_silent.main", return_value=7) as main:
            self.assertEqual(bridge.main(["--no-alert", "--mint", "X"]), 7)
        main.assert_called_once_with([])


class ScanWatchlistTest(unittest.TestCase):
    def test_collects_success_and_skips_failures(self):
        def fake(ca, *args, **kwargs):
            if ca == "BAD":
                raise RuntimeError("gagal")
            return {"ca": ca, "symbol": args[0] if args else "?"}

        watchlist = {
            "GOOD": {"symbol": "GD"},
            "BAD": {"symbol": "BD"},
        }
        with mock.patch("scripts.scan_silent.analyze_token",
                        side_effect=fake):
            out = scan_watchlist(watchlist, workers=1)
        self.assertEqual(set(out), {"GOOD"})

    def test_empty_watchlist_returns_empty(self):
        self.assertEqual(scan_watchlist({}), {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
