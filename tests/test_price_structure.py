"""Gate struktur harga (SBR): dikalibrasi pada DREGG + 4 pola konfirmasi."""
import json
import unittest
from pathlib import Path

from price_structure import (CONFIRMED, FORMING, FORMING_LOW, HIGHER_LOW,
                             NO_DATA, NO_ZONE, StructureConfig,
                             bars_from_trades, detect_structure)

FIXTURE = Path(__file__).parent / "fixtures" / "dregg_15m.json"
CFG15 = StructureConfig(interval_sec=900)   # fixture disimpan sebagai bar 15m
T0 = 1_786_000_000


def _dregg():
    raw = json.loads(FIXTURE.read_text())
    return [dict(ts=int(b[0]), open=b[1], high=b[2], low=b[3], close=b[4])
            for b in raw]


def bar(i, o, h, l, c):
    return {"ts": T0 + i * 300, "open": o, "high": h, "low": l, "close": c}


def shelf(n=14, lo=100.0):
    """Shelf support ~lo±1 selama >1 jam (>min_span_sec), close bertahan."""
    lows = [100.0, 100.4, 99.9, 100.2, 100.8, 99.8, 100.1, 100.3,
            100.6, 99.9, 100.2, 100.0, 100.5, 100.1, 100.3, 100.2]
    out = []
    for i in range(n):
        l = lows[i % len(lows)] * lo / 100.0
        out.append(bar(i, l, l * 1.015, l, l * 1.008))
    return out


class DreggFixtureTest(unittest.TestCase):
    """Perilaku persis seperti narasi chart DREGG 17–18 Agu 2026."""

    def test_zone_is_the_sbr_shelf(self):
        v = detect_structure(_dregg(), "up", CFG15)
        zone = v["zone"]
        self.assertIsNotNone(zone)
        self.assertAlmostEqual(zone["low"], 0.000266, delta=1.5e-6)
        self.assertAlmostEqual(zone["high"], 0.0002722, delta=1.0e-6)
        self.assertGreaterEqual(zone["touches"], 20)
        self.assertAlmostEqual(v["extreme"], 0.0001952076, delta=1e-9)
        self.assertEqual(v["low_state"], HIGHER_LOW)

    def test_retest_wick_does_not_confirm(self):
        # @00:45 WIB: wick 0.00027289 menyentuh zona tapi tertolak (tanpa close).
        v = detect_structure(_dregg()[:125], "up", CFG15)
        self.assertEqual(v["state"], FORMING)
        self.assertIsNone(v["reclaim_ts"])

    def test_original_alert_moment_still_forming(self):
        # @08:34 WIB (alert flow asli fire): candle breakout belum tutup.
        v = detect_structure(_dregg()[:157], "up", CFG15)
        self.assertEqual(v["state"], FORMING)

    def test_confirm_when_breakout_candle_closes(self):
        # Candle 08:30 close 0.0002936 → konfirmasi sah pada 08:45.
        v = detect_structure(_dregg()[:159], "up", CFG15)
        self.assertEqual(v["state"], CONFIRMED)
        self.assertEqual(v["reclaim_ts"], 1787016600 + 900)

    def test_retest_from_above_keeps_confirmation(self):
        # Live ~09:10: dip ke 0.0002699 (di dalam/atas dasar zona) → hold.
        v = detect_structure(_dregg(), "up", CFG15)
        self.assertEqual(v["state"], CONFIRMED)


class PatternTest(unittest.TestCase):
    """Empat pola konfirmasi manual yang harus lolos (+ anti-pola yang tidak)."""

    def test_p1_retest_no_new_low_then_breakout(self):
        bars = (shelf(14)
                + [bar(14, 100.5, 101.0, 70.0, 78.0)]       # flush
                + [bar(15, 78.0, 80.0, 72.0, 76.0),         # higher low
                   bar(16, 76.0, 79.0, 74.0, 78.0)])
        v = detect_structure(bars, "up")
        self.assertEqual(v["state"], FORMING)
        self.assertEqual(v["low_state"], HIGHER_LOW)
        bars.append(bar(17, 78.0, 105.0, 77.0, 104.0))      # breakout close
        v = detect_structure(bars, "up")
        self.assertEqual(v["state"], CONFIRMED)
        bars.append(bar(18, 104.0, 105.0, 99.0, 100.2))     # retest dari atas
        v = detect_structure(bars, "up")
        self.assertEqual(v["state"], CONFIRMED)

    def test_p2_small_fakeout_below_lowest_low(self):
        bars = (shelf(14)
                + [bar(14, 100.5, 101.0, 70.0, 78.0),        # flush low 70
                   bar(15, 78.0, 79.0, 67.5, 75.0)])          # fakeout kecil
        v = detect_structure(bars, "up")
        # Anchor pindah ke low fakeout; saat bar terakhir = anchor → forming.
        self.assertEqual(v["low_state"], FORMING_LOW)
        self.assertAlmostEqual(v["extreme"], 67.5)
        bars.append(bar(16, 75.0, 106.0, 74.0, 105.0))        # pump/reclaim
        v = detect_structure(bars, "up")
        self.assertEqual(v["state"], CONFIRMED)
        self.assertEqual(v["low_state"], HIGHER_LOW)

    def test_deep_undercut_still_requires_fresh_reclaim(self):
        # Undercut dalam: anchor pindah ke low baru, reclaim LAMA sebelum low
        # itu tidak dihitung — konfirmasi harus datang setelah anchor.
        bars = (shelf(14)
                + [bar(14, 100.5, 104.0, 70.0, 103.5),        # flush + reclaim awal
                   bar(15, 103.0, 103.5, 60.0, 66.0)])        # undercut dalam
        v = detect_structure(bars, "up")
        self.assertEqual(v["extreme_ts"], T0 + 15 * 300)
        self.assertEqual(v["state"], FORMING)                 # reclaim lama hangus
        bars.append(bar(16, 66.0, 106.0, 65.0, 105.0))        # reclaim baru valid
        self.assertEqual(detect_structure(bars, "up")["state"], CONFIRMED)

    def test_p3_reclaim_back_to_last_low_then_reclaim_again(self):
        bars = (shelf(14)
                + [bar(14, 100.5, 101.0, 70.0, 78.0),
                   bar(15, 78.0, 104.0, 77.0, 103.5)])        # reclaim awal
        self.assertEqual(detect_structure(bars, "up")["state"], CONFIRMED)
        bars.append(bar(16, 103.0, 103.5, 71.5, 79.0))        # balik ke last low
        self.assertEqual(detect_structure(bars, "up")["state"], FORMING)
        bars.append(bar(17, 79.0, 106.0, 78.5, 105.0))        # reclaim final
        v = detect_structure(bars, "up")
        self.assertEqual(v["state"], CONFIRMED)
        self.assertEqual(v["low_state"], HIGHER_LOW)

    def test_p4_support_break_fast_reclaim(self):
        bars = (shelf(14)
                + [bar(14, 100.2, 100.8, 92.0, 96.0)])        # breakout support
        self.assertEqual(detect_structure(bars, "up")["state"], FORMING)
        # fast reclaim < 3 jam (2 candle 5m cukup untuk konfirmasi)
        bars += [bar(15, 96.0, 99.0, 95.5, 98.5),
                 bar(16, 98.5, 103.0, 98.0, 102.5)]
        self.assertEqual(detect_structure(bars, "up")["state"], CONFIRMED)

    def test_down_mirror(self):
        highs = [100.0, 100.4, 99.9, 100.2, 100.8, 99.8, 100.1, 100.3,
                 100.6, 99.9, 100.2, 100.0, 100.5, 100.1]
        bars = [bar(i, highs[i] * 0.99, highs[i], highs[i] * 0.975,
                    highs[i] * 0.985) for i in range(14)]
        bars.append(bar(14, 98.5, 130.0, 98.0, 120.0))        # pump high 130
        v = detect_structure(bars, "down")
        self.assertEqual(v["state"], FORMING)                 # masih di atas zona
        self.assertEqual(v["low_state"], FORMING_LOW)
        bars += [bar(15, 120.0, 122.0, 104.0, 108.0),         # lower high
                 bar(16, 108.0, 109.0, 96.0, 98.5)]           # tembus zona
        v = detect_structure(bars, "down")
        self.assertEqual(v["state"], CONFIRMED)
        self.assertEqual(v["low_state"], HIGHER_LOW)          # = lower-high asli
        self.assertAlmostEqual(v["zone"]["low"], 99.8, delta=0.5)
        self.assertAlmostEqual(v["zone"]["high"], 100.9, delta=0.7)


class EdgeTest(unittest.TestCase):
    def test_no_data_and_no_zone(self):
        self.assertIsInstance(detect_structure([], "up"), dict)
        self.assertEqual(detect_structure([], "up")["state"], NO_DATA)
        # Turun terus dengan low di tengah lalu memantul: tidak ada shelf
        # dengan ≥3 sentuhan → zona tidak terdefinisi.
        lows = [100, 97, 94, 91, 88, 85, 82, 80, 78, 76, 74, 77, 79, 81]
        mono = [bar(i, l * 1.01, l * 1.02, l, l * 1.005)
                for i, l in enumerate(lows)]
        self.assertEqual(detect_structure(mono, "up")["state"], NO_ZONE)

    def test_bars_from_trades_completed_only(self):
        trades = [
            {"timestamp": T0 + 5, "price_usd": 10.0},
            {"timestamp": T0 + 50, "price_usd": 12.0},
            {"timestamp": T0 + 400, "price_usd": 11.0},      # bar kedua
            {"timestamp": T0 + 610, "price_usd": 9.0},       # bar berjalan?
            {"timestamp": T0 + 700, "price_usd": 0.0},       # tanpa harga: skip
        ]
        bars = bars_from_trades(trades, 300, now_ts=T0 + 605)
        self.assertEqual(len(bars), 2)                        # bar ke-3 dibuang
        self.assertEqual(bars[0]["open"], 10.0)
        self.assertEqual(bars[0]["high"], 12.0)
        self.assertEqual(bars[1]["close"], 11.0)


if __name__ == "__main__":
    unittest.main()
