"""Card **Chart LP**: watchlist terpisah token Meteora + grafik dust holder."""
from __future__ import annotations

import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import holder_history as hh  # noqa: E402
import lp_watchlist as lw  # noqa: E402

LP_MINT = "LpMint11111111111111111111111111111111111"
LP_MINT2 = "LpMint22222222222222222222222222222222222"
HOLDER_MINT = "Holder11111111111111111111111111111111111"
BUCKET = hh.INTERVAL_SEC


def _point(index: int, pct: float, count: int = 100) -> dict:
    return {
        "ts": (index + 1) * BUCKET,
        "price": 0.01, "mc": 100_000.0,
        "dust_count": count, "dust_pct_mc": pct, "dust_value_usd": count * 5.0,
        "real_count": 40, "real_pct_mc": 20.0,
        "mid_count": 6, "mid_pct_mc": 4.0,
        "cohort_token_pct": 90.0, "cohort_cut50_pct": 10.0, "cohort_n": 6,
        "holder_count": count + 40,
        "buckets": {">$0-$10": count},
    }


def _store(points_by_mint: dict) -> dict:
    return {
        "updated_at": 3 * BUCKET,
        "tokens": {mint: {"symbol": f"SYM{index}", "cohort": {},
                          "points": points}
                   for index, (mint, points)
                   in enumerate(points_by_mint.items())},
    }


def _status(mint: str, *, pct=None, count=None, mc=120_000.0) -> dict:
    holders = {}
    if pct is not None:
        holders["dust_pct_mc"] = pct
    if count is not None:
        holders["dust_count"] = count
    return {"symbol": "LP1", "marketcap": mc, "price": 0.01,
            "analyzed_at": 3 * BUCKET, "holders": holders, "history": []}


class SplitWatchlistTest(unittest.TestCase):
    def test_lp_sources_go_to_the_lp_card_only(self):
        watchlist = {
            LP_MINT: {"symbol": "LP1", "source": "meteora"},
            "Upper111111111111111111111111111111111111": {"source": "METEORA"},
            HOLDER_MINT: {"symbol": "HLD", "source": "manual"},
            "NoSource1111111111111111111111111111111111": {"symbol": "OLD"},
        }
        lp, holder = lw.split_watchlist(watchlist)
        self.assertEqual(set(lp), {LP_MINT,
                                   "Upper111111111111111111111111111111111111"})
        self.assertEqual(set(holder), {HOLDER_MINT,
                                       "NoSource1111111111111111111111111111111111"})
        # tidak ada token yang muncul di dua card
        self.assertFalse(set(lp) & set(holder))

    def test_order_is_preserved_and_empty_input_is_safe(self):
        watchlist = {LP_MINT: {"source": "lp"}, HOLDER_MINT: {"source": "degen"}}
        lp, holder = lw.split_watchlist(watchlist)
        self.assertEqual(list(lp), [LP_MINT])
        self.assertEqual(list(holder), [HOLDER_MINT])
        self.assertEqual(lw.split_watchlist(None), ({}, {}))
        self.assertEqual(lw.split_watchlist({}), ({}, {}))

    def test_is_lp_source_variants(self):
        self.assertTrue(lw.is_lp_source({"source": "meteora"}))
        self.assertTrue(lw.is_lp_source({"source": " Meteora "}))
        self.assertTrue(lw.is_lp_source({"source": "chart_lp"}))
        self.assertFalse(lw.is_lp_source({"source": "manual"}))
        self.assertFalse(lw.is_lp_source({}))
        self.assertFalse(lw.is_lp_source(None))


class LpRowTest(unittest.TestCase):
    def setUp(self):
        self.store = _store({LP_MINT: [_point(0, 0.40, 80),
                                       _point(1, 0.62, 95),
                                       _point(2, 1.30, 140)]})
        self.status = {LP_MINT: _status(LP_MINT, pct=1.30, count=140)}

    def test_row_carries_dust_metrics_and_deltas(self):
        row = lw.build_lp_row(LP_MINT, {"symbol": "lp1", "source": "meteora"},
                              self.status, self.store)
        self.assertEqual(row["symbol"], "LP1")
        self.assertEqual(row["dust_pct"], 1.30)
        self.assertEqual(row["dust_count"], 140)
        self.assertEqual(row["flag"]["level"], "danger")
        # bucket terakhir 1.30 vs sebelumnya 0.62 → +0.68 poin persentase
        self.assertAlmostEqual(row["delta_4h"], 0.68, places=2)
        self.assertAlmostEqual(row["delta_total"], 0.90, places=2)
        self.assertTrue(row["has_chart"])
        self.assertEqual(len(row["sampled"]), 3)
        self.assertEqual(row["mc"], 120_000.0)

    def test_row_falls_back_to_history_when_status_is_empty(self):
        row = lw.build_lp_row(LP_MINT, {"source": "meteora"}, {}, self.store)
        self.assertEqual(row["dust_pct"], 1.30)
        self.assertEqual(row["flag"]["label"], "BAHAYA")

    def test_row_without_history_has_no_chart(self):
        row = lw.build_lp_row(HOLDER_MINT, {"source": "meteora"}, {},
                              {"tokens": {}})
        self.assertFalse(row["has_chart"])
        self.assertIsNone(row["dust_pct"])
        self.assertIsNone(row["delta_4h"])
        self.assertEqual(row["flag"]["level"], "unknown")

    def test_caution_level_between_half_and_one_percent(self):
        store = _store({LP_MINT: [_point(0, 0.20), _point(1, 0.70)]})
        row = lw.build_lp_row(LP_MINT, {"source": "meteora"}, {}, store)
        self.assertEqual(row["flag"]["level"], "caution")
        self.assertEqual(row["flag"]["label"], "HATI-HATI")


class LpCardOrderTest(unittest.TestCase):
    def test_rows_sorted_by_severity_then_dust_pct(self):
        watchlist = {
            LP_MINT: {"symbol": "OK", "source": "meteora"},
            LP_MINT2: {"symbol": "DANGER", "source": "meteora"},
            HOLDER_MINT: {"symbol": "CAUTION", "source": "meteora"},
        }
        store = _store({
            LP_MINT: [_point(0, 0.10), _point(1, 0.20)],
            LP_MINT2: [_point(0, 0.90), _point(1, 1.50)],
            HOLDER_MINT: [_point(0, 0.40), _point(1, 0.80)],
        })
        rows = lw.lp_card_rows(watchlist, {}, store)
        self.assertEqual([row["symbol"] for row in rows],
                         ["DANGER", "CAUTION", "OK"])

    def test_non_lp_tokens_are_excluded(self):
        watchlist = {LP_MINT: {"symbol": "LP", "source": "meteora"},
                     HOLDER_MINT: {"symbol": "HLD", "source": "manual"}}
        store = _store({LP_MINT: [_point(0, 0.1)], HOLDER_MINT: [_point(0, 9)]})
        rows = lw.lp_card_rows(watchlist, {}, store)
        self.assertEqual([row["mint"] for row in rows], [LP_MINT])

    def test_summary_counts_levels_and_rising(self):
        watchlist = {LP_MINT: {"source": "meteora"},
                     LP_MINT2: {"source": "meteora"},
                     HOLDER_MINT: {"source": "meteora"}}
        store = _store({
            LP_MINT: [_point(0, 0.10), _point(1, 1.50)],   # danger + rising
            LP_MINT2: [_point(0, 0.90), _point(1, 0.60)],  # caution + turun
            HOLDER_MINT: [],                               # unknown
        })
        summary = lw.lp_summary(lw.lp_card_rows(watchlist, {}, store))
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["danger"], 1)
        self.assertEqual(summary["caution"], 1)
        self.assertEqual(summary["unknown"], 1)
        self.assertEqual(summary["rising"], 1)
        self.assertEqual(summary["with_chart"], 2)
        self.assertEqual(lw.lp_summary([])["total"], 0)


class LpChartTest(unittest.TestCase):
    def test_figure_has_both_threshold_lines(self):
        points = [_point(0, 0.30), _point(1, 0.70), _point(2, 1.20)]
        fig = lw.lp_chart_figure(points, "lp1")
        self.assertIsNotNone(fig)
        try:
            axis = fig.axes[0]
            labels = [text.get_text()
                      for text in axis.get_legend().get_texts()]
            self.assertIn("Hati-hati 0.5%", labels)
            self.assertIn("Bahaya 1%", labels)
            self.assertIn("Dust % MC", labels)
            self.assertIn("LP1", axis.get_title())
            # twin axis = jumlah wallet dust
            self.assertIn("dust", fig.axes[1].get_ylabel().lower())
        finally:
            plt.close(fig)

    def test_figure_needs_two_four_hour_buckets(self):
        self.assertIsNone(lw.lp_chart_figure([_point(0, 0.5)], "A"))
        self.assertIsNone(lw.lp_chart_figure([], "A"))
        self.assertIsNone(lw.lp_chart_figure(None, "A"))

    def test_overlay_skips_tokens_without_history(self):
        rows = [{"symbol": "A", "points": [_point(0, 0.3), _point(1, 0.9)]},
                {"symbol": "B", "points": [_point(0, 0.2)]}]
        fig = lw.lp_overlay_figure(rows)
        self.assertIsNotNone(fig)
        try:
            labels = [text.get_text()
                      for text in fig.axes[0].get_legend().get_texts()]
            self.assertIn("$A", labels)
            self.assertNotIn("$B", labels)
        finally:
            plt.close(fig)
        self.assertIsNone(lw.lp_overlay_figure([]))
        self.assertIsNone(lw.lp_overlay_figure([{"symbol": "B",
                                                 "points": []}]))


class PointsForMintTest(unittest.TestCase):
    def test_merges_status_history_with_local_file(self):
        store = _store({LP_MINT: [_point(0, 0.4)]})
        status = {LP_MINT: {"history": [_point(1, 0.8)]}}
        points = lw.points_for_mint(LP_MINT, status, store)
        self.assertEqual([p["ts"] for p in points], [BUCKET, 2 * BUCKET])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
