"""F/V lane rules must run before expensive holder enrichment."""
import unittest
from unittest.mock import patch
import meteora_screener as ms
from tests.test_best_pool_scan import _pool


class BestFVPrefilterTest(unittest.TestCase):
    def test_boundaries(self):
        for lane, fee, vol, ok in [
            ('24h', 50, 10, True), ('24h', 49.999, 10, False),
            ('30m', 10, 10, False), ('30m', 10.001, 10, True),
            ('24h', 1, 0, True), ('30m', 1, 0, True),
            ('24h', 0, 0, False), ('30m', 0, 0, False),
            ('24h', None, 1, False), ('30m', 1, None, False),
            ('24h', float('inf'), 1, False), ('30m', 1, -1, False),
            ('24h', 10, float('nan'), False), ('other', 50, 1, False),
        ]:
            with self.subTest(lane=lane, fee=fee, vol=vol):
                self.assertEqual(not ms.row_best_gaps(dict(
                    timeframe=lane, fee_active_tvl_ratio=fee, volatility=vol)), ok)

    def test_only_passing_lane_enriched(self):
        pools = [_pool('SAME', 'MintA', ratio=20, volatility=10),
                 _pool('PASS', 'MintB', ratio=50, volatility=10),
                 _pool('FAIL', 'MintC', ratio=10, volatility=10)]
        with patch.object(ms, 'fetch_best_pools', return_value=pools), \
                patch.object(ms, 'enrich_pools', side_effect=lambda rows, **kw: rows) as enrich:
            result = ms.scan_best_meteora(max_wallets=2000)
        actual = {(r['timeframe'], r['pool_address']) for r in enrich.call_args.args[0]}
        self.assertEqual(actual, {('24h', 'PASS'), ('30m', 'SAME'), ('30m', 'PASS')})
        self.assertEqual(result['fetched'], 6)
        self.assertEqual(result['hidden_metric'], 3)
        self.assertEqual(len(result['hidden_rows']), 3)
        self.assertEqual(len(result['rows']), 3)

    def test_no_enrichment_when_all_rejected(self):
        with patch.object(ms, 'fetch_best_pools', return_value=[_pool(ratio=1, volatility=2)]), \
                patch.object(ms, 'enrich_pools') as enrich:
            result = ms.scan_best_meteora(max_wallets=2000)
        enrich.assert_not_called()
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['hidden_metric'], 2)
