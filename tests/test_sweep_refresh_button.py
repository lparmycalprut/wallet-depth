# -*- coding: utf-8 -*-
"""Tombol Refresh di tabel Sweep: callback mencatat mint baris yang diklik."""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sweep_ui as ui  # noqa: E402


class RequestRefreshTest(unittest.TestCase):
    def _run(self, click, mints):
        fake_st = types.SimpleNamespace(session_state={})
        if click is not None:
            fake_st.session_state[ui.REFRESH_CLICK_KEY] = click
        with mock.patch.object(ui, "st", fake_st):
            ui._request_refresh(mints)
        return fake_st.session_state

    def test_clicked_row_maps_to_its_mint(self):
        state = self._run({"row": 1, "label": "🔄 Refresh"}, ["A", "B", "C"])
        self.assertEqual(state[ui.PENDING_REFRESH_KEY], "B")

    def test_no_click_does_nothing(self):
        state = self._run(None, ["A"])
        self.assertNotIn(ui.PENDING_REFRESH_KEY, state)

    def test_out_of_range_or_blank_mint_is_ignored(self):
        self.assertNotIn(ui.PENDING_REFRESH_KEY,
                         self._run({"row": 5, "label": "x"}, ["A"]))
        self.assertNotIn(ui.PENDING_REFRESH_KEY,
                         self._run({"row": 0, "label": "x"}, [""]))


class FrozenColumnsTest(unittest.TestCase):
    def test_hapus_refresh_token_stay_left_rest_scrolls_right(self):
        import pandas as pd
        frame = pd.DataFrame([{"Hapus": False, "Refresh": "🔄 Refresh",
                               "Token": "RARI", "Snapshot": "x", "Kohort": "y"}])
        left, right = ui._split_frozen_columns(frame)
        self.assertEqual(list(left.columns), ["Hapus", "Refresh", "Token"])
        self.assertEqual(list(right.columns), ["Snapshot", "Kohort"])
        self.assertEqual(len(left), len(right))


if __name__ == "__main__":
    unittest.main()
