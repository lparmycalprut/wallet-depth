"""Regression: PARE watchlist 0.00% vs dedicated scan 0.03%.

Synthetic descending balances reproduce the missing dust tail, not a captured
live PARE snapshot. All provider, market and persistence IO is mocked.
"""
import copy
import unittest
from unittest import mock

import holder_history as hh
import robinhood_holders as rh
import robinhood_watchlist as rw
import telegram_alerts as ta
from watchlist_detail import resolve_view

CA = "0x15d36b6a28d8327abc7afabf0f106ae2c9af5c4d"


class DustCoverageTest(unittest.TestCase):
    def setUp(self):
        rh.clear_holder_cache()
        self.addCleanup(rh.clear_holder_cache)

    def test_watchlist_and_dedicated_include_tail_after_3000_rich_holders(self):
        csv = "HolderAddress,Balance\n" + "".join(
            f"0x{i + 1:040x},{20 if i < 3000 else 1}\n"
            for i in range(3300))
        market = {"symbol": "PARE", "price_usd": 1, "marketcap": 1_000_000}
        with mock.patch.object(rh, "get_market", return_value=market), \
                mock.patch.object(rh, "fetch_token_info", return_value={
                    "decimals": 18, "total_supply": 1_000_000}), \
                mock.patch.object(rh, "fetch_holders_count", return_value=3300), \
                mock.patch.object(rh, "_http_get", return_value=mock.Mock(text=csv)), \
                mock.patch.object(rh, "fetch_holders_rpc") as rpc, \
                mock.patch.object(rh, "fetch_holders_v2") as v2:
            # The old watchlist caps lose the entire dust tail.
            for cap in (2000, 3000):
                partial = rh.analyze_token(CA, max_wallets=cap, detail=False)
                self.assertEqual(partial["holders"]["dust_pct_mc"], 0.0)
                self.assertTrue(partial["holders"]["truncated"])
                self.assertFalse(hh.holders_usable(partial["holders"]))

            dedicated = rh.scan_token_holders(CA)
            watchlist = rw.scan_watchlist({CA: {"symbol": "PARE"}},
                                         history_store={}, detail=False)[CA]
        stats = watchlist["holders"]
        self.assertEqual(stats["total_fetched"], 3300)
        self.assertEqual(stats["dust_count"], 300)
        self.assertEqual(stats["dust_pct_mc"], 0.03)
        self.assertEqual(stats["dust_pct_mc"], dedicated["depth"]["buckets"][0]["pct_mc"])
        self.assertFalse(stats["truncated"])
        self.assertTrue(hh.holders_usable(stats))
        rpc.assert_not_called()
        v2.assert_not_called()  # Full CSV still costs one request.

    def _fetch_csv_sample(self, count, *, limit=100_000, counter=0, rpc=None):
        rows = [rh._holder_row(f"0x{i + 1:040x}", 20, 1, 1_000_000, set())
                for i in range(count)]
        with mock.patch.object(rh, "fetch_holders_count", return_value=counter), \
                mock.patch.object(rh, "fetch_holders_csv", return_value=rows), \
                mock.patch.object(rh, "fetch_holders_rpc",
                                  return_value=rpc or ([], 0, True, "unavailable")), \
                mock.patch.object(rh, "fetch_holders_v2", return_value=[]):
            return rh.fetch_holders(CA, max_wallets=limit, price_usd=1,
                                    decimals=18, total_supply=1_000_000)

    def test_csv_at_requested_cap_without_counter_is_not_complete(self):
        result = self._fetch_csv_sample(2000, limit=2000)
        self.assertTrue(result["truncated"])
        self.assertIn("holder tidak lengkap", result["error"])

    def test_counter_proves_exact_limit_is_complete(self):
        result = self._fetch_csv_sample(2000, limit=2000, counter=2000)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["error"], "")

    def test_failed_fallback_below_requested_limit_is_incomplete(self):
        result = self._fetch_csv_sample(100, counter=500)
        self.assertTrue(result["truncated"])
        self.assertIn("100/500", result["error"])

    def test_server_csv_ceiling_without_counter_is_incomplete(self):
        with mock.patch.object(rh, "CSV_EXPORT_LIMIT", 100):
            result = self._fetch_csv_sample(100)
        self.assertTrue(result["truncated"])

    def test_rpc_error_after_first_page_is_incomplete_without_counter(self):
        payload = {"status": "1", "result": [
            {"address": f"0x{i + 1:040x}", "value": str(20 * 10**18)}
            for i in range(rh.HOLDER_PAGE_SIZE)]}
        with mock.patch.object(rh, "_jsjson", side_effect=[payload, RuntimeError("429")]), \
                mock.patch.object(rh.time, "sleep"):
            rows, pages, truncated, error = rh.fetch_holders_rpc(CA, price_usd=1)
        self.assertEqual(len(rows), rh.HOLDER_PAGE_SIZE)
        self.assertEqual(pages, 1)
        self.assertTrue(truncated)
        self.assertEqual(error, "429")


class PartialScanSafetyTest(unittest.TestCase):
    def setUp(self):
        self.holders = {"total_fetched": 3000, "wallets_analyzed": 3000,
                        "real_count": 3000, "dust_count": 0,
                        "dust_pct_mc": 0.0, "truncated": True}
        self.analysis = {"ca": CA, "symbol": "PARE", "analyzed_at": 2000,
                         "holders": self.holders}
        self.old_point = {"ts": 1000, "dust_pct_mc": 0.03,
                          "holder_count": 3300, "dust_count": 300}
        self.partial_point = {"ts": 2000, "dust_pct_mc": 0.0,
                              "holder_count": 3000, "truncated": True}

    def test_legacy_truncated_history_rejected_without_degraded_marker(self):
        self.assertFalse(hh.point_usable(hh.compact_point(self.partial_point)))
        self.assertEqual(hh.usable_points([self.old_point, self.partial_point]),
                         [self.old_point])

    def test_row_uses_last_complete_scan_not_partial_zero(self):
        view = resolve_view(self.analysis, [self.old_point, self.partial_point])
        self.assertEqual(view["dust_pct"], 0.03)
        self.assertTrue(view["degraded"])

    def test_new_token_with_only_partial_scans_has_no_percentage(self):
        view = resolve_view(self.analysis, [self.partial_point])
        self.assertIsNone(view["dust_pct"])
        self.assertTrue(view["degraded"])

    def test_publish_keeps_old_snapshot_and_marks_history_degraded(self):
        store = hh.empty_store()
        old = {"tokens": {CA: {"holders": {"dust_pct_mc": 0.03}}}}
        with mock.patch.object(rw, "publish_holder_status", return_value=old) as publish, \
                mock.patch.object(hh, "save_holder_history"):
            rw.publish_scan({CA: self.analysis}, {CA: {"symbol": "PARE"}},
                            history_store=store, merge_status=old, detail=False)
        self.assertEqual(publish.call_args.args[0], {})
        self.assertIs(publish.call_args.kwargs["merge_status"], old)
        self.assertTrue(store["tokens"][CA]["points"][-1]["degraded"])

    def test_partial_scan_cannot_send_alert_or_advance_markers(self):
        store = {"tokens": {CA: {"points": [self.old_point]}}}
        before = copy.deepcopy(store)
        with mock.patch.object(ta, "evaluate_alert_events") as evaluate:
            result = ta.process_holder_alerts({CA: self.analysis}, store,
                                              lp_mints={CA}, high_mints={CA})
        self.assertEqual(result, [])
        evaluate.assert_not_called()
        self.assertEqual(store, before)
