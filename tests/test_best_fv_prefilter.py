"""Rule layar Best Pool wajib jalan SEBELUM enrichment holder yang mahal.

Kriteria 2026-09-16 (satu lane): *"hapus scan 30 menit, kita sisakan yang 24 jam
saja"* + *"volatility kurang dari 1 sembunyikan juga"* + *"volatility > 10
sembunyikan juga"* + *"jika ada top 10 >= 20% jangan tampilkan"*. File ini
mem-pin urutan eksekusinya, bukan angkanya (angka + teks ambang diuji di
``tests/test_best_pool_scan.py``):

- **satu lane 24H**: ``F/V >= BEST_FV_24H_MIN`` (5×, inklusif). Semua alias
  lama (``30m``/``1h``/``both``) dipetakan :func:`normalize_best_lane` ke 24H,
  jadi baris warisan sesi lama (``timeframe="30m"``) dinilai dengan aturan 24H —
  aturan ``F/V > 1×`` lama sudah dicabut dan tidak bisa dihidupkan dari mana pun;
- **volatility 1%–10%** (``BEST_VOL_SHOW_MIN``/``MAX``, inklusif) dan **Top10
  < 20%** (``BEST_TOP10_MAX_PCT``, ``>= 20%`` dibuang) ikut di saringan yang
  sama, di urutan sesudah F/V;
- volatility 0 (F/V ∞) **selalu gugur** (2026-09-14) — ∞ bukan kelolosan, pool
  tanpa volatility tidak bisa membuktikan F > V — dan **dibuang dari listing**:
  tidak masuk ``hidden_rows``, tidak dihitung ``hidden_metric``, hanya tercatat
  di counter audit ``dropped_volatility``;
- kandidat yang gugur tidak pernah membuat request holder (``enrich_pools``
  tidak dipanggil untuk mereka) tapi tetap tercatat di ``hidden_rows`` beserta
  ``best_gaps`` (kecuali vol-0 di atas).
"""
import unittest
from unittest.mock import patch

import meteora_screener as ms
from tests.test_best_pool_scan import _pool


def _gate_row(fee, vol, *, timeframe='24h', top10=0.0):
    return dict(timeframe=timeframe, fee_active_tvl_ratio=fee,
                volatility=vol, top_holders_pct=top10)


class LaneGateBoundaryTest(unittest.TestCase):
    """Tabel batas ambang 24H (F/V 5× inklusif + volat 1%–10% + Top10 < 20%)."""

    def test_boundaries(self):
        for lane, fee, vol, ok in [
            # F/V: tepat 5× lolos, di bawahnya gugur.
            ('24h', 50, 10, True), ('24h', 49.999, 10, False),
            ('24h', 50.001, 10, True),
            # Volatilitas: window INKLUSIF di dua sisi.
            ('24h', 60, 1.0, True), ('24h', 60, 0.999, False),
            ('24h', 600, 10.0, True), ('24h', 600, 10.001, False),
            # Baris warisan 30M dinilai dengan aturan 24H (F/V 1,0× < 5×).
            ('30m', 10, 10, False), ('30m', 60, 6.0, True),
            # Vol 0 = tanpa pergerakan: gugur di mana pun.
            ('24h', 1, 0, False), ('30m', 1, 0, False),
            ('24h', 0, 0, False), ('30m', 0, 0, False),
            # Metrik hilang / tidak valid → tidak ada kelolosan.
            ('24h', None, 1, False), ('30m', 1, None, False),
            ('24h', float('inf'), 1, False), ('30m', 1, -1, False),
            ('24h', 10, float('nan'), False),
            # Timeframe yang tidak pernah dikenal tetap gugur (bukan 24H).
            ('other', 50, 1, False),
        ]:
            with self.subTest(lane=lane, fee=fee, vol=vol):
                self.assertEqual(not ms.row_best_gaps(_gate_row(fee, vol, timeframe=lane)), ok)

    def test_top10_juga_dievaluasi_sebelum_holder(self):
        """Top10 >= 20% gugur di fungsi yang sama (satu jalur, satu alasan)."""
        self.assertFalse(ms.row_best_gaps(_gate_row(60, 6.0, top10=19.999)))
        self.assertEqual(ms.row_best_gaps(_gate_row(60, 6.0, top10=20.0)),
                         ['24H: Top10 20% ≥ 20% — holder terpusat'])

    def test_lane_kwarg_hanya_mengganti_label(self):
        """``lane=`` tetap diterima, tapi aturannya satu: 24H.

        Render ulang hasil lama memakai argument ini (``hidden``/tabel
        "dilewati"); sejak 30M dihapus yang berubah hanyalah tidak ada lagi
        pelonggaran "F/V > 1×" untuk baris 30m. Hanya ``lane`` yang tidak pernah
        dikenal yang gugur dengan alasan sendiri.
        """
        row = _gate_row(20.0, 10.0)                    # F/V 2,0× → gugur 5×
        self.assertEqual(ms.row_best_gaps(row), ['24H: F/V < 5×'])
        self.assertEqual(ms.row_best_gaps(row, lane='30m'), ['24H: F/V < 5×'])
        self.assertEqual(ms.row_best_gaps(row, lane='both'), ['24H: F/V < 5×'])
        self.assertEqual(ms.row_best_gaps(row, lane='5m'),
                         ['timeframe tidak dikenal'])
        # Baris ber-timeframe 30m + tanpa lane: tetap aturan + label 24H.
        self.assertEqual(
            ms.row_best_gaps(_gate_row(20.0, 10.0, timeframe='30m')),
            ['24H: F/V < 5×'])

    def test_teks_gap_ikuti_konstanta(self):
        """Label gap dibaca dari konstanta — ubah ambang, teks ikut berubah."""
        with patch.object(ms, 'BEST_FV_24H_MIN', 8.0):
            self.assertEqual(ms.row_best_gaps(_gate_row(20, 10)),
                             ['24H: F/V < 8×'])
        with patch.object(ms, 'BEST_VOL_SHOW_MAX', 5.0):
            self.assertEqual(ms.row_best_gaps(_gate_row(60, 6.0)),
                             ['24H: volatility 6% > 5% — pergerakan lebih '
                              'besar dari fee'])
        with patch.object(ms, 'BEST_TOP10_MAX_PCT', 30.0):
            self.assertEqual(ms.row_best_gaps(_gate_row(60, 6.0, top10=25.0)),
                             [])

    def test_volatility_nol_selalu_gugur_dengan_alasan(self):
        """V=0 (F/V ∞) bukan kelolosan, labelnya selalu 24H (2026-09-14)."""
        for lane in ('24h', '30m'):
            with self.subTest(lane=lane):
                for fee in (5.0, 0.0):
                    self.assertEqual(
                        ms.row_best_gaps(_gate_row(fee, 0, timeframe=lane)),
                        ['24H: volatility 0 — F/V tidak terukur'])


class LaneEnrichmentTest(unittest.TestCase):
    """Hanya kandidat lolos saringan yang boleh menyentuh Helius."""

    def _scan(self, lane, pools, enrich_calls):
        """Scan ``lane`` (alias lama ikut) — listing selalu window 24 jam.

        Fetch di-mock mengembalikan ``pools`` apa pun window yang diminta, dan
        ``self.fetched_timeframes`` mencatat window yang benar-benar diminta
        supaya "satu tombol = satu listing" tetap bisa di-pin.
        """
        def fake_enrich(rows, **_kw):
            enrich_calls.append([(r['timeframe'], r['pool_address'])
                                 for r in rows])
            return rows

        def fake_fetch(*, timeframe, **_kw):
            self.fetched_timeframes.append(timeframe)
            return pools

        # ``rugcheck=False``: kolom RugCheck menghubungi rugchecker.cc dan tidak
        # ada hubungannya dengan pre-filter; attach GMGN (2026-09-17) di-patch
        # offline (likuiditas tak terbaca = tidak menyaring) supaya uji ini
        # tetap tidak menyentuh jaringan.
        self.fetched_timeframes = []

        def _fake_gmgn_attach(rows, **_kw):
            for row in rows:
                row['gmgn_liq'] = {'ok': False}
            return rows

        with patch.object(ms, 'fetch_best_pools', side_effect=fake_fetch), \
                patch.object(ms, 'enrich_pools', side_effect=fake_enrich), \
                patch('gmgn_liquidity.attach_total_liquidity',
                      side_effect=_fake_gmgn_attach):
            result = ms.scan_best_lane(lane, max_wallets=2000,
                                       rugcheck=False)
        result['fetched_timeframes'] = list(self.fetched_timeframes)
        return result

    def test_24h_hanya_yang_lolos_5x(self):
        pools = [_pool('SAME', 'MintA', ratio=20, volatility=10),
                 _pool('PASS', 'MintB', ratio=50, volatility=10),
                 _pool('FAIL', 'MintC', ratio=10, volatility=10)]
        calls: list = []
        result = self._scan('24h', pools, calls)
        # SAME 2,0× dan FAIL 1,0× DILEWATI sebelum fetch holder; PASS 5,0× lolos.
        self.assertEqual(result['fetched_timeframes'], ['24h'])
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

    def test_volat_di_luar_rentang_tanpa_scan_holder(self):
        """Volat 0,5% dan 42% diperlakukan sama seperti gugur F/V: skip Helius."""
        pools = [_pool('SEPI', 'MintA', ratio=60, volatility=0.5),
                 _pool('BATAS', 'MintB', ratio=60, volatility=1.0),
                 _pool('GEBUDEG', 'MintC', ratio=600, volatility=42.0)]
        calls: list = []
        result = self._scan('24h', pools, calls)
        self.assertEqual(calls, [[('24h', 'BATAS')]])
        self.assertEqual([r['pool_address'] for r in result['rows']], ['BATAS'])
        self.assertEqual(sorted(r['pool_address'] for r in result['hidden_rows']),
                         ['GEBUDEG', 'SEPI'])
        self.assertEqual({tuple(r['best_gaps']) for r in result['hidden_rows']},
                         {('24H: volatility 0.5% < 1% — pool nyaris tidak '
                           'bergerak',),
                          ('24H: volatility 42% > 10% — pergerakan lebih besar '
                           'dari fee',)})
        self.assertEqual(result['hidden_metric'], 2)

    def test_top10_20_ke_atas_tanpa_scan_holder(self):
        pools = [_pool('BERSIH', 'MintA', ratio=60, volatility=6.0, top10=4.0),
                 _pool('PAS', 'MintB', ratio=60, volatility=6.0, top10=20.0),
                 _pool('PUSAT', 'MintC', ratio=60, volatility=6.0, top10=77.0)]
        calls: list = []
        result = self._scan('24h', pools, calls)
        self.assertEqual(calls, [[('24h', 'BERSIH')]])
        self.assertEqual(sorted(r['pool_address'] for r in result['hidden_rows']),
                         ['PAS', 'PUSAT'])
        self.assertEqual(result['hidden_metric'], 2)

    def test_satu_tombol_hanya_ambil_satu_timeframe(self):
        """Apa pun alias yang dikirim, fetch-nya SATU kali dan window 24h."""
        seen: list = []

        def fake_fetch(*, timeframe, **_kw):
            seen.append(timeframe)
            return []

        for lane in ('24h', '30m', 'both'):
            seen.clear()
            with patch.object(ms, 'fetch_best_pools', side_effect=fake_fetch), \
                    patch.object(ms, 'enrich_pools') as enrich:
                result = ms.scan_best_lane(lane, max_wallets=2000,
                                           rugcheck=False)
            self.assertEqual(seen, ['24h'], lane)
            enrich.assert_not_called()
            self.assertEqual(result['rows'], [])
            self.assertEqual(result['lane'], '24h')

    def test_no_enrichment_when_all_rejected(self):
        calls: list = []
        self._scan('24h', [_pool(ratio=1, volatility=2)], calls)
        self.assertEqual(calls, [])

    def test_volatility_nol_dibuang_tanpa_scan_holder(self):
        """∞ gugur gate DAN dibuang dari hidden_rows (2026-09-14 lanjutan)."""
        pools = [_pool('DOM', 'MintA', ratio=60, volatility=6),     # 10× lolos
                 _pool('SAMA', 'MintB', ratio=10, volatility=10),   # 1× gugur
                 _pool('NOL', 'MintC', ratio=50, volatility=0)]     # ∞ → dibuang
        calls: list = []
        result = self._scan('30m', pools, calls)
        # Alias 30m = scan 24H: DOM lolos (10×), SAMA gugur, NOL dibuang total.
        self.assertEqual(calls, [[('24h', 'DOM')]])
        self.assertEqual([r['pool_address'] for r in result['rows']], ['DOM'])
        self.assertEqual([r['pool_address'] for r in result['hidden_rows']],
                         ['SAMA'])
        self.assertEqual({tuple(r['best_gaps']) for r in result['hidden_rows']},
                         {('24H: F/V < 5×',)})
        self.assertEqual(result['hidden_metric'], 1)
        self.assertEqual(result['dropped_volatility'], 1)
        self.assertEqual(result['fetched'], 3)

    def test_hasil_disortakan_fee_tvl_lalu_f_v(self):
        """Prioritas = Fee/TVL terbesar (2026-09-15), baru F/V; ∞ dibuang.

        FEE_RAJIN Fee/TVL-nya paling besar (200%) tapi F/V-nya cuma 20×,
        FV_TAJAM F/V 50× tapi Fee/TVL 100% — kalau F/V masih kunci pertama,
        FV_TAJAM yang muncul di atas.
        """
        pools = [_pool('FV_TAJAM', 'MintB', ratio=100, volatility=2),   # 50×
                 _pool('FEE_RAJIN', 'MintA', ratio=200, volatility=10),  # 20×
                 _pool('NOL', 'MintC', ratio=150, volatility=0)]         # ∞ → dibuang
        calls: list = []
        result = self._scan('24h', pools, calls)
        self.assertEqual([r['pool_address'] for r in result['rows']],
                         ['FEE_RAJIN', 'FV_TAJAM'])
        # Vol-0 tidak lagi ditampilkan di mana pun — hidden_rows kosong dan
        # pembuangannya hanya tercatat di counter audit.
        self.assertEqual(result['hidden_rows'], [])
        self.assertEqual(result['hidden_metric'], 0)
        self.assertEqual(result['dropped_volatility'], 1)


class LegacyBothLaneTest(unittest.TestCase):
    """``timeframe="both"`` lama TIDAK lagi berarti dua listing."""

    def test_both_ditarik_ke_satu_listing_24h(self):
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
            result = ms.scan_best_meteora(max_wallets=2000, timeframe='both',
                                          rugcheck=False)
        # Satu fetch saja (dulu dua: 24h + 30m), dan barisnya tidak diduplikasi.
        self.assertEqual(seen, ['24h'])
        enriched = enrich.call_args.args[0]
        self.assertEqual([(r['timeframe'], r['pool_address']) for r in enriched],
                         [('24h', 'PASS')])
        self.assertEqual(result['fetched'], 3)
        self.assertEqual(result['hidden_metric'], 2)
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(len(result['hidden_rows']), 2)
        self.assertEqual(result['lane'], '24h')


if __name__ == '__main__':
    unittest.main()
