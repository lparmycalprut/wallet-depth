"""Coverage for the enriched baseline fields and the watchlist detail column.

``classify_at`` now reports what happened on the baseline day
(``baseline_date``, ``baseline_price_chg_pct``, ``baseline_cvd_delta``,
``baseline_gap_days``) so ``app.py`` can narrate non-neutral signals inside the
"Baseline & detail" column. Neutral rows only show the plain baseline facts.

Streamlit is an optional dev dependency, so the AppTest part is skipped when it
is unavailable.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from effort_detector import classify_effort, daily_effort_record

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

APP = str(Path(__file__).resolve().parent.parent / "app.py")
MINT = "MintBaseline"


def _rows():
    """Baseline day up +6%, next day a cheap dump (S2_DUMP_DISTRIBUSI)."""
    return [
        daily_effort_record(MINT, "2026-08-13", 1.0, 1.06, 12.4),
        daily_effort_record(MINT, "2026-08-14", 1.06, 0.84, -16.5),
    ]


class BaselineFieldsTest(unittest.TestCase):
    def test_stable_baseline_exposes_day_details(self):
        result = classify_effort(_rows(), MINT)
        self.assertEqual(result["signal"], "S2_DUMP_DISTRIBUSI")
        self.assertEqual(result["baseline_date"], "2026-08-13")
        self.assertEqual(result["baseline_direction"], "up")
        self.assertEqual(result["baseline_gap_days"], 1)
        self.assertAlmostEqual(result["baseline_price_chg_pct"], 6.0, places=6)
        self.assertAlmostEqual(result["baseline_cvd_delta"], 12.4, places=6)
        self.assertAlmostEqual(result["baseline_ratio"],
                               result["ratio_N_minus_1"], places=8)

    def test_missing_baseline_keeps_fields_none(self):
        rows = [daily_effort_record(MINT, "2026-08-14", 1.0, 1.01, 0.2)]
        result = classify_effort(rows, MINT)
        self.assertIsNone(result["baseline_date"])
        self.assertIsNone(result["baseline_price_chg_pct"])
        self.assertIsNone(result["baseline_cvd_delta"])
        self.assertIsNone(result["baseline_gap_days"])

    def test_selling_exhaustion_keeps_flush_reference(self):
        rows = [
            daily_effort_record(MINT, "2026-08-11", 1.0, 0.55, -106.6),
            daily_effort_record(MINT, "2026-08-12", 0.55, 0.55, -15.4),
        ]
        result = classify_effort(rows, MINT)
        self.assertEqual(result["signal"], "SELLING_EXHAUSTION")
        self.assertEqual(result["flush_date"], "2026-08-11")
        self.assertEqual(result["baseline_date"], "2026-08-11")


@unittest.skipIf(AppTest is None, "streamlit not installed")
class BaselineColumnRenderTest(unittest.TestCase):
    def _run(self, rows):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       return_value={MINT: {"symbol": "TST"}}),
            mock.patch("effort_detector.load_daily_effort",
                       return_value=rows),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=30)
        app.run()
        self.assertFalse(app.exception)
        return "\n".join(block.value for block in app.markdown)

    def test_non_neutral_row_explains_baseline_and_today(self):
        body = self._run(_rows())
        self.assertIn("Base 2026-08-13", body)
        self.assertIn("CVD +12.40 SOL", body)
        self.assertIn("buyer absen", body)

    def test_neutral_row_shows_facts_without_narrative(self):
        rows = _rows() + [
            daily_effort_record(MINT, "2026-08-15", 0.84, 0.85, 6.0),
        ]
        result = classify_effort(rows, MINT)
        self.assertEqual(result["bias"], "neutral")
        body = self._run(rows)
        self.assertIn("Base 2026-08-14", body)
        self.assertNotIn("buyer absen", body)
        self.assertNotIn("seller absen", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
