"""Pindah card watchlist: ``source`` menentukan Chart LP vs watchlist holder."""
from __future__ import annotations

import unittest
from unittest import mock

import watchlist as wl

LP_MINT = "LpMint11111111111111111111111111111111111"
HOLDER_MINT = "Holder11111111111111111111111111111111111"


class ApplyOpsSourceTest(unittest.TestCase):
    def test_source_op_updates_existing_entry_only(self):
        data = {HOLDER_MINT: {"symbol": "HLD", "source": "manual",
                              "added": "2026-09-03"},
                "Untouched111111111111111111111111111111111": {"symbol": "X"}}
        out = wl._apply_ops(dict(data),
                            [{"op": "source", "ca": HOLDER_MINT,
                              "source": "meteora"}])
        self.assertEqual(out[HOLDER_MINT]["source"], "meteora")
        # field lain tidak hilang
        self.assertEqual(out[HOLDER_MINT]["symbol"], "HLD")
        self.assertEqual(out[HOLDER_MINT]["added"], "2026-09-03")
        self.assertEqual(out["Untouched111111111111111111111111111111111"],
                         {"symbol": "X"})

    def test_source_op_never_creates_an_entry(self):
        out = wl._apply_ops({}, [{"op": "source", "ca": LP_MINT,
                                  "source": "meteora"}])
        self.assertEqual(out, {})

    def test_source_op_does_not_mutate_the_original_entry(self):
        entry = {"symbol": "HLD", "source": "manual"}
        data = {HOLDER_MINT: entry}
        wl._apply_ops(data, [{"op": "source", "ca": HOLDER_MINT,
                              "source": "meteora"}])
        self.assertEqual(entry["source"], "manual")


class OpAppliedTest(unittest.TestCase):
    def test_source_op_is_applied_when_repo_matches(self):
        self.assertTrue(wl._op_is_applied(
            {"op": "source", "ca": LP_MINT, "source": "meteora"},
            {LP_MINT: {"source": "meteora"}}))
        self.assertFalse(wl._op_is_applied(
            {"op": "source", "ca": LP_MINT, "source": "meteora"},
            {LP_MINT: {"source": "manual"}}))
        self.assertFalse(wl._op_is_applied(
            {"op": "source", "ca": LP_MINT, "source": "meteora"}, {}))

    def test_add_and_remove_keep_their_rules(self):
        self.assertTrue(wl._op_is_applied({"op": "add", "ca": LP_MINT},
                                          {LP_MINT: {}}))
        self.assertFalse(wl._op_is_applied({"op": "add", "ca": LP_MINT}, {}))
        self.assertTrue(wl._op_is_applied({"op": "remove", "ca": LP_MINT}, {}))
        self.assertFalse(wl._op_is_applied({"op": "remove", "ca": LP_MINT},
                                           {LP_MINT: {}}))

    def test_prune_pending_drops_applied_ops(self):
        pending = [{"op": "source", "ca": LP_MINT, "source": "meteora"},
                   {"op": "add", "ca": HOLDER_MINT, "symbol": "HLD"}]
        repo = {LP_MINT: {"source": "meteora"}}
        self.assertEqual(wl._prune_pending(pending, repo),
                         [{"op": "add", "ca": HOLDER_MINT, "symbol": "HLD"}])


class JournalMergeTest(unittest.TestCase):
    def test_source_after_pending_add_is_merged_into_the_add(self):
        saved = {}
        with mock.patch.object(wl, "_load_pending",
                               return_value=[{"op": "add", "ca": LP_MINT,
                                              "symbol": "LP1",
                                              "source": "manual"}]), \
                mock.patch.object(wl, "_save_pending",
                                  side_effect=lambda ops: saved.update(
                                      {"ops": ops})):
            wl._journal_many([{"op": "source", "ca": LP_MINT,
                               "source": "meteora"}])
        ops = saved["ops"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["op"], "add")
        self.assertEqual(ops[0]["symbol"], "LP1")
        self.assertEqual(ops[0]["source"], "meteora")

    def test_last_op_wins_for_same_address(self):
        saved = {}
        with mock.patch.object(wl, "_load_pending",
                               return_value=[{"op": "add", "ca": LP_MINT}]), \
                mock.patch.object(wl, "_save_pending",
                                  side_effect=lambda ops: saved.update(
                                      {"ops": ops})):
            wl._journal_many([{"op": "remove", "ca": LP_MINT}])
        self.assertEqual(saved["ops"], [{"op": "remove", "ca": LP_MINT}])


class SetWatchlistSourceTest(unittest.TestCase):
    def _run(self, existing, ca, source):
        data = {key: dict(value) for key, value in (existing or {}).items()}
        patches = (
            mock.patch.object(wl, "_load_and_merge", return_value=data),
            mock.patch.object(wl, "_journal"),
            mock.patch.object(wl, "save_watchlist", return_value=True),
        )
        mocks = [patch.start() for patch in patches]
        self.addCleanup(lambda: [patch.stop() for patch in reversed(patches)])
        return wl.set_watchlist_source(ca, source), data, mocks

    def test_moves_token_to_the_lp_card(self):
        existing = {HOLDER_MINT: {"symbol": "HLD", "source": "manual"}}
        ok, saved, mocks = self._run(existing, HOLDER_MINT, "meteora")
        self.assertTrue(ok)
        self.assertEqual(saved[HOLDER_MINT]["source"], "meteora")
        journal, save = mocks[1], mocks[2]
        journal.assert_called_once_with({"op": "source", "ca": HOLDER_MINT,
                                         "source": "meteora"})
        self.assertIn("move HLD", save.call_args.args[1])

    def test_moves_token_back_to_the_holder_watchlist(self):
        existing = {LP_MINT: {"symbol": "LP1", "source": "meteora"}}
        ok, saved, _mocks = self._run(existing, LP_MINT, "manual")
        self.assertTrue(ok)
        self.assertEqual(saved[LP_MINT]["source"], "manual")

    def test_unknown_address_is_rejected_without_writing(self):
        ok, _saved, mocks = self._run({LP_MINT: {"source": "meteora"}},
                                      HOLDER_MINT, "meteora")
        self.assertFalse(ok)
        mocks[1].assert_not_called()
        mocks[2].assert_not_called()

    def test_same_source_is_a_noop(self):
        existing = {LP_MINT: {"symbol": "LP1", "source": "meteora"}}
        ok, _saved, mocks = self._run(existing, LP_MINT, " Meteora ")
        self.assertTrue(ok)
        mocks[1].assert_not_called()
        mocks[2].assert_not_called()

    def test_empty_arguments_are_rejected(self):
        self.assertFalse(wl.set_watchlist_source("", "meteora"))
        self.assertFalse(wl.set_watchlist_source(LP_MINT, ""))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
