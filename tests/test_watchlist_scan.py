"""Filtering and batch-add coverage for Trending/Degen scan results."""
from __future__ import annotations

import unittest
from unittest import mock

import watchlist as wl

try:  # Streamlit is optional in a minimal unit-test environment.
    from trending_ui import filter_watchlisted_rows, merge_scan_rows
except ModuleNotFoundError as exc:
    if exc.name not in {"streamlit", "requests"}:
        raise
    filter_watchlisted_rows = merge_scan_rows = None


EVM_MIXED = "0xAbCdEf0123456789aBCDef0123456789AbCdEf01"
EVM_LOWER = EVM_MIXED.lower()


@unittest.skipIf(filter_watchlisted_rows is None,
                 "UI dependencies are not installed")
class ScanFilteringTest(unittest.TestCase):
    def test_existing_token_is_hidden_after_trim_and_evm_casefold(self):
        rows = [
            {"ca": f"  {EVM_MIXED} ", "symbol": "OLD"},
            {"ca": "NewSolanaMint", "symbol": "NEW"},
        ]
        visible = filter_watchlisted_rows(rows, {EVM_LOWER: {"symbol": "OLD"}})
        self.assertEqual([row["ca"] for row in visible], ["NewSolanaMint"])

    def test_new_token_remains_visible(self):
        rows = [{"ca": "NewSolanaMint", "symbol": "NEW"}]
        self.assertEqual(filter_watchlisted_rows(rows, {}), rows)

    def test_scan_addresses_are_deduplicated_after_normalization(self):
        rows = merge_scan_rows(
            [{"ca": EVM_MIXED, "symbol": "FIRST"}],
            [{"ca": f" {EVM_LOWER} ", "symbol": "SECOND"},
             {"ca": "SolanaMint", "symbol": "SOL"}],
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["symbol"], "FIRST")
        self.assertEqual(rows[0]["ca"], EVM_LOWER)

    def test_solana_base58_comparison_remains_case_sensitive(self):
        rows = [{"ca": "AbCdSolanaMint", "symbol": "ONE"}]
        visible = filter_watchlisted_rows(
            rows, {"abcdsolanamint": {"symbol": "OTHER"}})
        self.assertEqual(len(visible), 1)


class AddManyWatchlistTest(unittest.TestCase):
    def _run(self, existing, rows):
        source_copy = {key: dict(value) for key, value in existing.items()}
        patches = (
            mock.patch.object(wl, "_load_and_merge", return_value=source_copy),
            mock.patch.object(wl, "_journal_many"),
            mock.patch.object(wl, "save_watchlist", return_value=True),
            mock.patch.object(wl, "request_immediate_scan", return_value=True),
        )
        mocks = [patch.start() for patch in patches]
        self.addCleanup(lambda: [patch.stop() for patch in reversed(patches)])
        result = wl.add_many_to_watchlist(rows, source="trending")
        return result, source_copy, mocks

    def test_add_all_only_adds_new_unique_addresses(self):
        existing = {EVM_LOWER: {"symbol": "OLD"}}
        rows = [
            {"ca": EVM_MIXED, "symbol": "OLD AGAIN"},
            {"ca": " NewSolanaMint ", "symbol": "NEW"},
            {"ca": "NewSolanaMint", "symbol": "DUP"},
        ]
        result, _source, mocks = self._run(existing, rows)
        journal, save, dispatch = mocks[1], mocks[2], mocks[3]
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["addresses"], ["NewSolanaMint"])
        self.assertEqual(len(journal.call_args.args[0]), 1)
        saved = save.call_args.args[0]
        self.assertEqual(set(saved), {EVM_LOWER, "NewSolanaMint"})
        self.assertEqual(saved["NewSolanaMint"]["source"], "trending")
        dispatch.assert_called_once_with()

    def test_empty_scan_does_not_write_watchlist(self):
        existing = {"Mint": {"symbol": "TST"}}
        result, source, mocks = self._run(existing, [])
        self.assertEqual(result["added"], 0)
        self.assertEqual(source, existing)
        mocks[1].assert_not_called()  # journal
        mocks[2].assert_not_called()  # save
        mocks[3].assert_not_called()  # dispatch

    def test_all_existing_does_not_change_or_write_watchlist(self):
        existing = {"Mint": {"symbol": "TST"}}
        result, source, mocks = self._run(
            existing, [{"ca": " Mint ", "symbol": "OTHER"}])
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(source, existing)
        mocks[1].assert_not_called()
        mocks[2].assert_not_called()
        mocks[3].assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
