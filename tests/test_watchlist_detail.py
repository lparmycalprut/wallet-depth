"""Detail baris watchlist: delta sejak masuk + sinkronisasi watchlist ↔ scan.

Murni kalkulasi (data dummy, tanpa jaringan). Angka pembanding waktu dihitung
lewat ``datetime`` UTC eksplisit, bukan lewat fungsi yang diuji.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import watchlist_detail as wd

MINT = "Watch11111111111111111111111111111111111"
HOUR = 3600
DAY = 86_400
# 2026-09-01 00:00 WIB == 2026-08-31 17:00 UTC
ADDED_TS = int(datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc).timestamp())


def _point(ts, pct, count=None):
    return {"ts": int(ts), "dust_pct_mc": pct,
            "dust_count": count if count is not None else 100,
            "price": 0.01, "mc": 100_000.0}


def _token(*, pct=None, count=None, analyzed_at=None):
    holders = {}
    if pct is not None:
        holders["dust_pct_mc"] = pct
    if count is not None:
        holders["dust_count"] = count
    return {"symbol": "TST", "analyzed_at": analyzed_at, "holders": holders,
            "marketcap": 100_000.0}


class ParseAddedTest(unittest.TestCase):
    def test_date_string_is_start_of_day_wib(self):
        self.assertEqual(wd.parse_added_ts({"added": "2026-09-01"}), ADDED_TS)

    def test_compact_and_slash_formats_are_accepted(self):
        self.assertEqual(wd.parse_added_ts({"added": "20260901"}), ADDED_TS)
        self.assertEqual(wd.parse_added_ts({"added": "2026/09/01"}), ADDED_TS)

    def test_iso_timestamp_keeps_its_own_timezone(self):
        value = wd.parse_added_ts({"added": "2026-09-01T00:00:00+00:00"})
        self.assertEqual(value,
                         int(datetime(2026, 9, 1, tzinfo=timezone.utc)
                             .timestamp()))

    def test_unix_number_passes_through(self):
        self.assertEqual(wd.parse_added_ts({"added": ADDED_TS}), ADDED_TS)

    def test_missing_or_broken_values_return_none(self):
        for meta in ({}, {"added": ""}, {"added": "kemarin"}, None):
            self.assertIsNone(wd.parse_added_ts(meta))


class ChangeMathTest(unittest.TestCase):
    def test_relative_and_point_changes(self):
        self.assertEqual(wd.pct_change(0.40, 0.20), -50.0)
        self.assertEqual(wd.pct_change(0.20, 0.60), 200.0)
        self.assertEqual(wd.pp_change(0.40, 0.20), -0.2)

    def test_zero_baseline_has_no_relative_change(self):
        self.assertIsNone(wd.pct_change(0.0, 0.4))
        self.assertEqual(wd.pp_change(0.0, 0.4), 0.4)

    def test_missing_side_has_no_change(self):
        self.assertIsNone(wd.pct_change(None, 0.4))
        self.assertIsNone(wd.pp_change(0.4, None))


class ToneTest(unittest.TestCase):
    def test_thresholds_are_inclusive_on_drop_and_rise(self):
        self.assertEqual(wd.tone_for_change(-50.0), wd.TONE_DROP)
        self.assertEqual(wd.tone_for_change(-80.0), wd.TONE_DROP)
        self.assertEqual(wd.tone_for_change(100.0), wd.TONE_RISE)
        self.assertEqual(wd.tone_for_change(250.0), wd.TONE_RISE)

    def test_inside_the_band_is_neutral(self):
        self.assertEqual(wd.tone_for_change(-49.9), wd.TONE_NEUTRAL)
        self.assertEqual(wd.tone_for_change(0.0), wd.TONE_NEUTRAL)
        self.assertEqual(wd.tone_for_change(99.9), wd.TONE_NEUTRAL)

    def test_unknown_without_a_number(self):
        self.assertEqual(wd.tone_for_change(None), wd.TONE_UNKNOWN)


class ResolveViewTest(unittest.TestCase):
    def test_snapshot_wins_when_it_is_the_newest(self):
        points = [_point(1_000, 0.30, 90)]
        view = wd.resolve_view(_token(pct=0.30, count=120, analyzed_at=2_000),
                               points, now=5_000)
        self.assertEqual(view["source"], wd.SOURCE_SNAPSHOT)
        self.assertEqual(view["dust_pct"], 0.30)
        self.assertEqual(view["dust_count"], 120)
        self.assertEqual(view["ts"], 2_000)
        self.assertEqual(view["age_sec"], 3_000)
        # angka snapshot == titik terakhir -> tidak ada selisih untuk dilaporkan
        self.assertFalse(view["drift"])

    def test_newer_history_point_wins_and_is_flagged_as_history(self):
        points = [_point(1_000, 0.30), _point(3_000, 0.71, 210)]
        view = wd.resolve_view(_token(pct=0.30, count=90, analyzed_at=1_000),
                               points, now=4_000)
        self.assertEqual(view["source"], wd.SOURCE_HISTORY)
        self.assertEqual(view["dust_pct"], 0.71)
        self.assertEqual(view["dust_count"], 210)
        self.assertEqual(view["ts"], 3_000)

    def test_disagreement_between_sources_is_flagged_as_drift(self):
        points = [_point(1_000, 0.30), _point(3_000, 0.71)]
        view = wd.resolve_view(_token(pct=0.30, analyzed_at=1_000), points,
                               now=4_000)
        self.assertTrue(view["drift"])
        self.assertEqual(view["snapshot_pct"], 0.30)
        self.assertEqual(view["history_pct"], 0.71)

    def test_small_difference_is_not_drift(self):
        points = [_point(1_000, 0.300), _point(3_000, 0.305)]
        view = wd.resolve_view(_token(pct=0.300, analyzed_at=1_000), points,
                               now=4_000)
        self.assertFalse(view["drift"])

    def test_stale_data_is_flagged(self):
        view = wd.resolve_view(_token(pct=0.30, analyzed_at=1_000), [],
                               now=1_000 + wd.STALE_AFTER_SEC + 1)
        self.assertTrue(view["stale"])

    def test_without_any_data_the_view_is_empty(self):
        view = wd.resolve_view({}, [])
        self.assertIsNone(view["dust_pct"])
        self.assertIsNone(view["ts"])
        self.assertEqual(view["source"], wd.SOURCE_SNAPSHOT)
        self.assertEqual(view["points"], 0)

    def test_snapshot_value_is_used_when_history_point_has_no_dust(self):
        points = [{"ts": 3_000, "dust_pct_mc": None}]
        view = wd.resolve_view(_token(pct=0.42, analyzed_at=1_000), points,
                               now=4_000)
        self.assertEqual(view["source"], wd.SOURCE_SNAPSHOT)
        self.assertEqual(view["dust_pct"], 0.42)


class PreviousPctTest(unittest.TestCase):
    def test_comparison_point_is_the_bucket_before_the_displayed_value(self):
        sampled = [_point(1_000, 0.10), _point(2_000, 0.20),
                   _point(3_000, 0.30)]
        view = wd.resolve_view(_token(pct=0.55, analyzed_at=4_000), sampled,
                               now=5_000)
        # angka baris dari snapshot (0.55) -> pembandingnya bucket 0.30,
        # bukan 0.20 seperti bila selalu mengambil sampled[-2].
        self.assertEqual(wd.previous_pct(sampled, view), 0.30)

    def test_falls_back_to_the_second_last_bucket_without_a_timestamp(self):
        sampled = [_point(1_000, 0.10), _point(2_000, 0.20)]
        self.assertEqual(wd.previous_pct(sampled, {}), 0.10)

    def test_first_point_has_no_comparison(self):
        self.assertIsNone(wd.previous_pct([_point(1_000, 0.10)], {}))
        self.assertIsNone(wd.previous_pct([], {}))


class SinceAddedTest(unittest.TestCase):
    def test_window_starts_at_the_first_point_after_the_added_date(self):
        meta = {"added": "2026-09-01"}
        points = [_point(ADDED_TS - 2 * DAY, 0.90, 400),   # sebelum masuk
                  _point(ADDED_TS + 2 * HOUR, 0.40, 200),  # anchor
                  _point(ADDED_TS + 3 * DAY, 0.10, 80)]    # scan terakhir
        change = wd.dust_change_since_added(meta, points, now=ADDED_TS + 4 * DAY)
        self.assertTrue(change["cukup_data"])
        self.assertEqual(change["from_pct"], 0.40)
        self.assertEqual(change["to_pct"], 0.10)
        self.assertEqual(change["pp_change"], -0.3)
        self.assertEqual(change["pct_change"], -75.0)
        self.assertEqual(change["count_change_pct"], -60.0)
        self.assertEqual(change["tone"], wd.TONE_DROP)
        self.assertEqual(change["anchor_ts"], ADDED_TS + 2 * HOUR)
        self.assertAlmostEqual(change["days"], 2.92, places=1)

    def test_doubling_dust_is_the_red_tone(self):
        meta = {"added": "2026-09-01"}
        points = [_point(ADDED_TS + HOUR, 0.20, 100),
                  _point(ADDED_TS + DAY, 0.45, 180)]
        change = wd.dust_change_since_added(meta, points)
        self.assertEqual(change["pct_change"], 125.0)
        self.assertEqual(change["tone"], wd.TONE_RISE)
        self.assertEqual(change["pp_change"], 0.25)

    def test_small_move_stays_neutral(self):
        meta = {"added": "2026-09-01"}
        points = [_point(ADDED_TS + HOUR, 0.30, 100),
                  _point(ADDED_TS + DAY, 0.33, 105)]
        change = wd.dust_change_since_added(meta, points)
        self.assertEqual(change["tone"], wd.TONE_NEUTRAL)

    def test_newer_snapshot_closes_the_window(self):
        """Scan terakhir boleh datang dari snapshot yang lebih baru dari titik store."""
        meta = {"added": "2026-09-01"}
        points = [_point(ADDED_TS + HOUR, 0.30, 100),
                  _point(ADDED_TS + DAY, 0.31, 102)]
        token = _token(pct=0.09, count=40, analyzed_at=ADDED_TS + 2 * DAY)
        view = wd.resolve_view(token, points, now=ADDED_TS + 2 * DAY)
        change = wd.dust_change_since_added(meta, points, view)
        self.assertEqual(change["to_pct"], 0.09)
        self.assertEqual(change["to_count"], 40)
        self.assertEqual(change["last_ts"], ADDED_TS + 2 * DAY)
        self.assertEqual(change["tone"], wd.TONE_DROP)
        self.assertEqual(change["source"], wd.SOURCE_SNAPSHOT)

    def test_added_date_without_points_falls_back_to_the_first_point(self):
        meta = {"added": "2026-09-03"}     # lebih baru dari semua titik
        points = [_point(ADDED_TS - 2 * DAY, 0.50, 200),
                  _point(ADDED_TS - DAY, 0.20, 90)]
        change = wd.dust_change_since_added(meta, points)
        self.assertTrue(change["cukup_data"])
        self.assertEqual(change["anchor_fallback"],
                         "belum ada titik sejak tanggal masuk")
        self.assertEqual(change["from_pct"], 0.50)
        self.assertIn("titik pertama", change["alasan"])

    def test_missing_added_date_is_reported(self):
        points = [_point(ADDED_TS, 0.50, 200), _point(ADDED_TS + DAY, 0.25, 90)]
        change = wd.dust_change_since_added({}, points)
        self.assertEqual(change["anchor_fallback"], "no_added_date")
        self.assertEqual(change["pct_change"], -50.0)

    def test_single_point_has_nothing_to_compare(self):
        points = [_point(ADDED_TS + HOUR, 0.50, 200)]
        change = wd.dust_change_since_added({"added": "2026-09-01"}, points)
        self.assertFalse(change["cukup_data"])
        self.assertIn("satu titik", change["alasan"])

    def test_without_points_there_is_no_data(self):
        change = wd.dust_change_since_added({"added": "2026-09-01"}, [])
        self.assertFalse(change["cukup_data"])
        self.assertEqual(change["tone"], wd.TONE_UNKNOWN)
        self.assertIn("Belum ada titik history", change["alasan"])


class ChangeHtmlTest(unittest.TestCase):
    def test_drop_uses_green_and_rise_uses_red(self):
        drop = wd.dust_change_since_added(
            {"added": "2026-09-01"},
            [_point(ADDED_TS + HOUR, 0.40), _point(ADDED_TS + DAY, 0.10)])
        html = wd.change_html(drop)
        self.assertIn(wd.TONE_COLORS[wd.TONE_DROP], html)
        self.assertIn("-75.0%", html)
        self.assertIn("0.40→0.10% MC", html)

        rise = wd.dust_change_since_added(
            {"added": "2026-09-01"},
            [_point(ADDED_TS + HOUR, 0.20), _point(ADDED_TS + DAY, 0.60)])
        self.assertIn(wd.TONE_COLORS[wd.TONE_RISE], wd.change_html(rise))
        self.assertIn("+200.0%", wd.change_html(rise))

    def test_neutral_uses_the_slate_color(self):
        change = wd.dust_change_since_added(
            {"added": "2026-09-01"},
            [_point(ADDED_TS + HOUR, 0.30), _point(ADDED_TS + DAY, 0.31)])
        self.assertIn(wd.TONE_COLORS[wd.TONE_NEUTRAL], wd.change_html(change))

    def test_missing_data_renders_a_placeholder(self):
        html = wd.change_html(wd.dust_change_since_added({}, []))
        self.assertIn("belum ada data", html)

    def test_zero_baseline_has_no_relative_number(self):
        change = wd.dust_change_since_added(
            {"added": "2026-09-01"},
            [_point(ADDED_TS + HOUR, 0.0, 0), _point(ADDED_TS + DAY, 0.30, 90)])
        self.assertTrue(change["cukup_data"])
        self.assertIsNone(change["pct_change"])
        self.assertEqual(change["tone"], wd.TONE_UNKNOWN)
        self.assertIn("—", wd.change_html(change))
        self.assertIn("tidak bisa dihitung", change["alasan"])


class SyncSummaryTest(unittest.TestCase):
    def test_counts_sources_drift_and_staleness(self):
        now = ADDED_TS + 5 * DAY
        views = [
            wd.resolve_view(_token(pct=0.30, analyzed_at=now - HOUR),
                            [_point(now - HOUR, 0.30)], now=now),
            wd.resolve_view(_token(pct=0.20, analyzed_at=now - 3 * HOUR),
                            [_point(now - HOUR, 0.75)], now=now),   # drift
            wd.resolve_view(_token(pct=0.10, analyzed_at=now - 9 * HOUR), [],
                            now=now),                               # basi
            wd.resolve_view({}, [], now=now),                       # tanpa data
        ]
        summary = wd.sync_summary(views, now=now)
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["dari_snapshot"], 2)
        self.assertEqual(summary["dari_history"], 1)
        self.assertEqual(summary["tanpa_data"], 1)
        self.assertEqual(summary["drift"], 1)
        self.assertEqual(summary["stale"], 1)
        self.assertEqual(summary["last_scan_ts"], now - HOUR)
        self.assertEqual(summary["max_age_sec"], 9 * HOUR)

    def test_caption_reports_the_last_scan_and_the_sources(self):
        now = ADDED_TS + 5 * DAY
        views = [wd.resolve_view(_token(pct=0.30, analyzed_at=now - HOUR),
                                 [_point(now - HOUR, 0.30)], now=now),
                 wd.resolve_view(_token(pct=0.20, analyzed_at=now - 3 * HOUR),
                                 [_point(now - HOUR, 0.75)], now=now)]
        text = wd.sync_caption_text(wd.sync_summary(views, now=now),
                                    status_updated_at=now - HOUR)
        self.assertIn("Scan terakhir:", text)
        self.assertIn(wd.format_wib(now - HOUR), text)
        self.assertIn("1 dari snapshot cron", text)
        self.assertIn("1 dari titik history lebih baru", text)
        self.assertIn("snapshot ≠ titik history", text)

    def test_caption_falls_back_to_the_status_timestamp(self):
        text = wd.sync_caption_text({"total": 0}, status_updated_at=ADDED_TS)
        self.assertIn(wd.format_wib(ADDED_TS), text)

    def test_age_and_time_formatters(self):
        self.assertEqual(wd.format_age(30), "30 dtk")
        self.assertEqual(wd.format_age(120), "2 mnt")
        self.assertEqual(wd.format_age(3 * HOUR), "3 jam")
        self.assertEqual(wd.format_age(2 * DAY), "2 hari")
        self.assertEqual(wd.format_age(None), "—")
        self.assertEqual(wd.format_wib(None), "—")
        self.assertTrue(wd.format_wib(ADDED_TS).endswith("WIB"))
        self.assertIn("01 Sep 00:00", wd.format_wib(ADDED_TS))


class RowSortKeyTest(unittest.TestCase):
    """Urutan baris watchlist (permintaan user 2026-09-05).

    Default ``SORT_DROP``: minus dust holder terbesar (pct_change paling
    negatif sejak masuk, mis. GPRO −60%) di urutan pertama; baris yang
    belum punya pembanding ditaruh di bawah (tidak bisa diklaim minus).
    """

    def test_default_drop_places_most_negative_first(self):
        rows = [wd.row_sort_key(wd.SORT_DROP, pct_change=-10.0, symbol="A"),
                wd.row_sort_key(wd.SORT_DROP, pct_change=-60.0, symbol="G"),
                wd.row_sort_key(wd.SORT_DROP, pct_change=120.0, symbol="B"),
                wd.row_sort_key(wd.SORT_DROP, pct_change=-35.5, symbol="S")]
        self.assertLess(rows[1], rows[3])
        self.assertLess(rows[3], rows[0])
        self.assertLess(rows[0], rows[2])

    def test_drop_tokens_without_comparison_go_below(self):
        known = wd.row_sort_key(wd.SORT_DROP, pct_change=999.0, symbol="A")
        unknown = wd.row_sort_key(wd.SORT_DROP, pct_change=None, symbol="A")
        self.assertLess(known, unknown)
        # GPRO (−60%) ada data -> di atas token yang belum ada pembanding.
        gpro = wd.row_sort_key(wd.SORT_DROP, pct_change=-60.0, symbol="GPRO")
        self.assertLess(gpro, unknown)

    def test_drop_badges_example_order(self):
        # Kasus user: GPRO & Sue (-60%) harus di atas token lain yang lebih
        # netral atau belum ada datanya.
        keys = [wd.row_sort_key(wd.SORT_DROP, pct_change=10.0, symbol="TOADS"),
                wd.row_sort_key(wd.SORT_DROP, pct_change=-62.0, symbol="SUE"),
                wd.row_sort_key(wd.SORT_DROP, pct_change=None, symbol="MOMO"),
                wd.row_sort_key(wd.SORT_DROP, pct_change=-60.0, symbol="GPRO")]
        ordered = sorted(keys)
        self.assertEqual(ordered, [keys[1], keys[3], keys[0], keys[2]])

    def test_pct_mode_puts_highest_dust_first(self):
        keys = [wd.row_sort_key(wd.SORT_PCT, dust_pct=0.2, symbol="A"),
                wd.row_sort_key(wd.SORT_PCT, dust_pct=1.2, symbol="B"),
                wd.row_sort_key(wd.SORT_PCT, dust_pct=None, symbol="C")]
        ordered = sorted(keys)
        self.assertEqual(ordered, [keys[1], keys[0], keys[2]])

    def test_name_mode_is_alphabetical(self):
        keys = [wd.row_sort_key(wd.SORT_NAME, symbol="GPRO"),
                wd.row_sort_key(wd.SORT_NAME, symbol="Sue"),
                wd.row_sort_key(wd.SORT_NAME, symbol="ANTSEM")]
        ordered = sorted(keys)
        self.assertEqual(ordered, [keys[2], keys[0], keys[1]])

    def test_symbol_is_case_insensitive_tiebreak(self):
        lower = wd.row_sort_key(wd.SORT_DROP, pct_change=-60.0, symbol="sue")
        upper = wd.row_sort_key(wd.SORT_DROP, pct_change=-60.0, symbol="SUE")
        self.assertEqual(lower, upper)


class DegradedScanTest(unittest.TestCase):
    """Scan holder yang datanya tidak lengkap tidak boleh jadi angka baris.

    Kasus produksi 2026-09-06: Helius mati (rate limit) lalu fallback GMGN
    mengembalikan **20** holder dengan ``truncated: False``. Wallet dust ada
    di ekor daftar holder, jadi sampel pendek selalu berisi ``dust 0`` /
    ``0,00% MC`` — 34 dari 79 baris watchlist lalu mengklaim "−100% sejak
    masuk" padahal tidak ada yang menjual.
    """

    def _good(self, ts, pct, count):
        row = _point(ts, pct, count)
        row["holder_count"] = count + 40
        row["real_count"] = 40
        return row

    def _short(self, ts, wallets=19, *, flagged=False):
        row = {"ts": int(ts), "dust_pct_mc": 0.0, "dust_count": 0,
               "real_count": wallets, "holder_count": wallets,
               "price": 0.01, "mc": 100_000.0}
        if flagged:
            row["degraded"] = True
        return row

    def _short_token(self, ts, wallets=19):
        return {"symbol": "TST", "analyzed_at": int(ts),
                "marketcap": 100_000.0,
                "holders": {"dust_count": 0, "dust_pct_mc": 0.0,
                            "real_count": wallets,
                            "wallets_analyzed": wallets,
                            "total_fetched": wallets + 1,
                            "source": "gmgn"}}

    def test_short_sample_snapshot_is_replaced_by_the_last_good_point(self):
        points = [self._good(1_000, 0.30, 120), self._short(3_000)]
        view = wd.resolve_view(self._short_token(3_000), points, now=4_000)
        self.assertEqual(view["dust_pct"], 0.30)
        self.assertEqual(view["ts"], 1_000)
        self.assertEqual(view["source"], wd.SOURCE_HISTORY)
        self.assertTrue(view["degraded"])
        self.assertEqual(view["degraded_wallets"], 19)
        self.assertIn("19 wallet", view["degraded_note"])

    def test_short_sample_point_without_the_flag_is_also_rejected(self):
        # Titik yang sudah terlanjur tersimpan di store produksi tidak punya
        # penanda ``degraded`` — lantai jumlah wallet yang menyaringnya.
        points = [self._good(1_000, 0.30, 120), self._short(3_000)]
        view = wd.resolve_view({}, points, now=4_000)
        self.assertEqual(view["dust_pct"], 0.30)
        self.assertTrue(view["degraded"])

    def test_flagged_point_is_rejected_even_with_many_wallets(self):
        points = [self._good(1_000, 0.30, 120)]
        broken = self._good(3_000, 0.0, 900)
        broken["degraded"] = True
        view = wd.resolve_view({}, points + [broken], now=4_000)
        self.assertEqual(view["dust_pct"], 0.30)
        self.assertTrue(view["degraded"])

    def test_good_newest_scan_is_not_marked_degraded(self):
        points = [self._good(1_000, 0.30, 120), self._good(3_000, 0.42, 150)]
        view = wd.resolve_view({}, points, now=4_000)
        self.assertEqual(view["dust_pct"], 0.42)
        self.assertFalse(view["degraded"])
        self.assertEqual(view["degraded_note"], "")

    def test_change_since_added_is_not_minus_100_from_a_short_scan(self):
        meta = {"added": "2026-09-01"}
        points = [self._good(ADDED_TS + HOUR, 0.40, 200),
                  self._good(ADDED_TS + DAY, 0.30, 150),
                  self._short(ADDED_TS + 2 * DAY, flagged=True)]
        change = wd.dust_change_since_added(
            meta, points, now=ADDED_TS + 2 * DAY)
        self.assertTrue(change["cukup_data"])
        # sebelum perbaikan: 0.40% -> 0.00% = -100.0% (hijau, menyesatkan)
        self.assertEqual(change["pct_change"], -25.0)
        self.assertEqual(change["to_pct"], 0.30)
        self.assertEqual(change["last_ts"], ADDED_TS + DAY)
        self.assertTrue(change["degraded"])
        self.assertIn("wallet", change["alasan"])

    def test_degraded_anchor_point_is_skipped(self):
        meta = {"added": "2026-09-01"}
        points = [self._short(ADDED_TS + HOUR, flagged=True),
                  self._good(ADDED_TS + DAY, 0.40, 200),
                  self._good(ADDED_TS + 2 * DAY, 0.20, 150)]
        change = wd.dust_change_since_added(meta, points,
                                            now=ADDED_TS + 2 * DAY)
        self.assertEqual(change["anchor_ts"], ADDED_TS + DAY)
        self.assertEqual(change["from_pct"], 0.40)
        self.assertEqual(change["pct_change"], -50.0)

    def test_token_with_only_short_scans_has_no_comparator(self):
        meta = {"added": "2026-09-01"}
        points = [self._short(ADDED_TS + HOUR, flagged=True),
                  self._short(ADDED_TS + DAY, flagged=True)]
        change = wd.dust_change_since_added(meta, points,
                                            now=ADDED_TS + 2 * DAY)
        self.assertFalse(change["cukup_data"])
        self.assertIn("tidak lengkap", change["alasan"])
        self.assertEqual(change["tone"], wd.TONE_UNKNOWN)

    def test_change_html_carries_a_warning_marker(self):
        meta = {"added": "2026-09-01"}
        points = [self._good(ADDED_TS + HOUR, 0.40, 200),
                  self._short(ADDED_TS + DAY, flagged=True)]
        html = wd.change_html(
            wd.dust_change_since_added(meta, points, now=ADDED_TS + DAY))
        self.assertIn("⚠️", html)

    def test_summary_and_caption_report_degraded_rows(self):
        points = [self._good(1_000, 0.30, 120), self._short(3_000)]
        views = [wd.resolve_view(self._short_token(3_000), points, now=4_000),
                 wd.resolve_view({}, [self._good(2_000, 0.20, 100)], now=4_000)]
        summary = wd.sync_summary(views, now=4_000)
        self.assertEqual(summary["degraded"], 1)
        caption = wd.sync_caption_text(summary)
        self.assertIn("tidak lengkap", caption)
        self.assertIn("1 token", caption)


class SnapshotTimeReportingTest(unittest.TestCase):
    """List holder diperbarui **sesuai waktu snapshot tiap token**.

    Satu angka "Scan terakhir" saja menyesatkan bila sebagian baris masih
    memakai snapshot run sebelumnya — caption harus menyebut berapa token
    yang duduk di waktu terbaru dan berapa yang lebih lama.
    """

    def test_summary_memisah_token_di_waktu_terbaru(self):
        views = [wd.resolve_view({}, [_point(3_000, 0.30, 100)], now=4_000),
                 wd.resolve_view({}, [_point(3_000, 0.40, 120)], now=4_000),
                 wd.resolve_view({}, [_point(1_000, 0.20, 90)], now=4_000)]
        summary = wd.sync_summary(views, now=4_000)
        self.assertEqual(summary["last_scan_ts"], 3_000)
        self.assertEqual(summary["latest_count"], 2)
        self.assertEqual(summary["older_count"], 1)

    def test_caption_menyebut_jumlah_token_per_waktu_snapshot(self):
        views = [wd.resolve_view({}, [_point(3_000, 0.30, 100)], now=4_000),
                 wd.resolve_view({}, [_point(3_000, 0.40, 120)], now=4_000),
                 wd.resolve_view({}, [_point(1_000, 0.20, 90)], now=4_000)]
        caption = wd.sync_caption_text(wd.sync_summary(views, now=4_000))
        self.assertIn(f"Scan terakhir: **{wd.format_wib(3_000)}** (2 token)",
                      caption)
        self.assertIn("1 token masih di snapshot sebelumnya", caption)

    def test_tooltip_sejak_masuk_menyebut_ujung_window(self):
        points = [_point(ADDED_TS + HOUR, 0.40, 200),
                  _point(ADDED_TS + DAY, 0.20, 150)]
        change = wd.dust_change_since_added({"added": "2026-09-01"}, points)
        self.assertIn(f"sampai snapshot {wd.format_wib(ADDED_TS + DAY)}",
                      wd.explain_change(change))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
