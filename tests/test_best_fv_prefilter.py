"""Rule F/V per lane wajib jalan SEBELUM enrichment holder yang mahal.

Kriteria 2026-09-13 sore (permintaan user: "tombol scan 24H kita prioritaskan
di 24H yang fee/v >= 5x untuk di scan detail lainnya, jika kurang dari itu
langsung skip" + "tombol scan 30M kita prioritaskan yang fee/v nya lebih besar,
jika lebih kecil langsung skip"):

- 24H: ``F/V >= BEST_FV_24H_MIN`` (5×, inklusif);
- 30M: ``F/V > BEST_FV_30M_MIN`` (1× — fee harus benar-benar lebih besar dari
  volatility);
- tiap tombol hanya mengambil lane-nya sendiri, dan kandidat di bawah ambang
  tidak pernah membuat request holder (``enrich_pools`` tidak dipanggil untuk
  mereka) tapi tetap tercatat di ``hidden_rows`` beserta ``best_gaps``.
"""
import unittest
from unittest.mock import patch

import meteora_screener as ms
from tests.test_best_pool_scan import _pool


class LaneGateBoundaryTest(unittest.TestCase):
    """Tabel batas ambang per lane (F/V 5× inklusif, 1× strict)."""

    def test_boundaries(self):
        for lane, fee, vol, ok in [
            ('24h', 50, 10, True), ('24h', 49.999, 10, False),
            ('24h', 50.001, 10, True),
            ('30m', 10, 10, False), ('30m', 10.001, 10, True),
            ('30m', 9.999, 10, False),
            ('24h', 1, 0, True), ('30m', 1, 0, True),
            ('24h', 0, 0, False), ('30m', 0, 0, False),
            ('24h', None, 1, False), ('30m', 1, None, False),
            ('24h', float('inf'), 1, False), ('30m', 1, -1, False),
            ('24h', 10, float('nan'), False), ('other', 50, 1, False),
        ]:
            with self.subTest(lane=lane, fee=fee, vol=vol):
                self.assertEqual(not ms.row_best_gaps(dict(
                    timeframe=lane, fee_active_tvl_ratio=fee, volatility=vol)), ok)

    def test_lane_kwarg_mengoverride_timeframe_baris(self):
        """``lane=`` memaksa aturan tombol yang ditekan (render ulang hasil lama)."""
        row = dict(timeframe='24h', fee_active_tvl_ratio=20.0, volatility=10.0)
        self.assertEqual(ms.row_best_gaps(row), ['24H: F/V < 5×'])      # 24H gugur
        self.assertEqual(ms.row_best_gaps(row, lane='30m'), [])         # 30M lolos
        self.assertEqual(ms.row_best_gaps(row, lane='both'),
                         ['24H: F/V < 5×'])   # both: tetap pakai lane baris
        self.assertEqual(ms.row_best_gaps(row, lane='5m'),
                         ['timeframe tidak dikenal'])

    def test_teks_gap_ikuti_konstanta(self):
        """Label gap dibaca dari konstanta — ubah ambang, teks ikut berubah."""
        with patch.object(ms, 'BEST_FV_24H_MIN', 8.0):
            self.assertEqual(ms.row_best_gaps(dict(
                timeframe='24h', fee_active_tvl_ratio=20, volatility=10)),
                ['24H: F/V < 8×'])
        with patch.object(ms, 'BEST_FV_30M_MIN', 3.0):
            self.assertEqual(ms.row_best_gaps(dict(
                timeframe='30m', fee_active_tvl_ratio=20, volatility=10)),
                ['30M: F/V ≤ 3×'])


class LaneEnrichmentTest(unittest.TestCase):
    """Hanya kandidat lolos ambang lane yang boleh menyentuh Helius."""

    def _scan(self, lane, pools, enrich_calls):
        def fake_enrich(rows, **_kw):
            enrich_calls.append([(r['timeframe'], r['pool_address']) for r in rows])
            return rows

        with patch.object(ms, 'fetch_best_pools',
                          side_effect=lambda *, timeframe, **kw: (
                              pools if timeframe == lane else [])), \
                patch.object(ms, 'enrich_pools', side_effect=fake_enrich):
            return ms.scan_best_lane(lane, max_wallets=2000)

    def test_24h_hanya_yang_lolos_5x(self):
        pools = [_pool('SAME', 'MintA', ratio=20, volatility=10),
                 _pool('PASS', 'MintB', ratio=50, volatility=10),
                 _pool('FAIL', 'MintC', ratio=10, volatility=10)]
        calls: list = []
        result = self._scan('24h', pools, calls)
        # SAME 2,0× dan FAIL 1,0× DILEWATI sebelum fetch holder; PASS 5,0× lolos.
        self.assertEqual(calls, [[('24h', 'PASS')]])
        self.assertEqual([r['pool_address'] for r in result['rows']], ['PASS'])
        self.assertEqual(result['fetched'], 3)
        self.assertEqual(result['hidden_metric'], 2)
        self.assertEqual(sorted(r['pool_address'] for r in result['hidden_rows']),
                         ['FAIL', 'SAME'])
        self.assertEqual({tuple(r['best_gaps']) for r in result['hidden_rows']},
                         {('24H: F/V < 5×',)})
        self.assertEqual(result['lane'], '24h')
        self.assertEqual(result['gate'], '24H: F/V ≥ 5×')

    def test_30m_pakai_aturan_lebih_besar(self):
        pools = [_pool('SAME', 'MintA', ratio=20, volatility=10),
                 _pool('EQUAL', 'MintB', ratio=10, volatility=10),
                 _pool('FAIL', 'MintC', ratio=10, volatility=11)]
        calls: list = []
        result = self._scan('30m', pools, calls)
        # F/V 2,0× dan 1,0×: yang tepat SAMA dengan volatility (1,0×) gugur.
        self.assertEqual(calls, [[('30m', 'SAME')]])
        self.assertEqual([r['pool_address'] for r in result['rows']], ['SAME'])
        self.assertEqual([r['pool_address'] for r in result['hidden_rows']],
                         ['EQUAL', 'FAIL'])
        self.assertEqual({tuple(r['best_gaps']) for r in result['hidden_rows']},
                         {('30M: F/V ≤ 1×',)})
        self.assertEqual(result['gate'], '30M: F/V > 1×')

    def test_satu_tombol_hanya_ambil_satu_timeframe(self):
        seen: list = []

        def fake_fetch(*, timeframe, **_kw):
            seen.append(timeframe)
            return []

        for lane in ('24h', '30m'):
            seen.clear()
            with patch.object(ms, 'fetch_best_pools', side_effect=fake_fetch), \
                    patch.object(ms, 'enrich_pools') as enrich:
                result = ms.scan_best_lane(lane, max_wallets=2000)
            self.assertEqual(seen, [lane], lane)
            enrich.assert_not_called()
            self.assertEqual(result['rows'], [])
            self.assertEqual(result['lane'], lane)

    def test_no_enrichment_when_all_rejected(self):
        calls: list = []
        self._scan('24h', [_pool(ratio=1, volatility=2)], calls)
        self.assertEqual(calls, [])

    def test_hasil_disortakan_f_v_terbesar(self):
        """Prioritas = F/V terbesar (permintaan user untuk kedua tombol)."""
        pools = [_pool('KECIL', 'MintA', ratio=25, volatility=5),     # 5×
                 _pool('BESAR', 'MintB', ratio=100, volatility=5),    # 20×
                 _pool('NOL', 'MintC', ratio=50, volatility=0)]       # ∞
        calls: list = []
        result = self._scan('24h', pools, calls)
        self.assertEqual([r['pool_address'] for r in result['rows']],
                         ['NOL', 'BESAR', 'KECIL'])


class LegacyBothLaneTest(unittest.TestCase):
    """``timeframe="both"`` tetap satu listing dua lane (compat, tanpa tombol)."""

    def test_both_mengambil_dua_lane_dua_record(self):
        pools = [_pool('SAME', 'MintA', ratio=20, volatility=10),
                 _pool('PASS', 'MintB', ratio=50, volatility=10),
                 _pool('FAIL', 'MintC', ratio=10, volatility=10)]
        seen: list = []

        def fake_fetch(*, timeframe, **_kw):
            seen.append(timeframe)
            return pools

        with patch.object(ms, 'fetch_best_pools', side_effect=fake_fetch), \
                patch.object(ms, 'enrich_pools',
                             side_effect=lambda rows, **kw: rows) as enrich:
            result = ms.scan_best_meteora(max_wallets=2000, timeframe='both')
        self.assertEqual(seen, ['24h', '30m'])
        enriched = enrich.call_args.args[0]
        self.assertEqual({(r['timeframe'], r['pool_address']) for r in enriched},
                         {('24h', 'PASS'), ('30m', 'SAME'), ('30m', 'PASS')})
        self.assertEqual(result['fetched'], 6)
        self.assertEqual(result['hidden_metric'], 3)
        self.assertEqual(len(result['rows']), 3)
        self.assertEqual(len(result['hidden_rows']), 3)


if __name__ == '__main__':
    unittest.main()
