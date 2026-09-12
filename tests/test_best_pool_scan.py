"""Coverage 🏆 Scan Best Pool Meteora (kriteria 2026-09-11).

Filter yang diminta user 2026-09-11 (kriteria lama **diganti total**):

- query API Meteora ``pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000``
  (timeframe 24 jam, category ``top``, page_size 50);
- saringan layar: dust holder **< 0,05% MC**, volatility **>= 2%**, dan
  **volume 24 jam >= 1 juta USD** (2026-09-12: "minimal volume 24 jam
  adalah 1M, dibawah itu jangan di show") — saringan lama (active TVL > 10K,
  fee/active TVL > 20%, top 10 holder < 30%, total LPs > 20) dihapus;
- urutan: kenaikan volume 24 jam (``volume_change_pct``) terbesar → dust %
  MC terkecil → fee/active TVL terbesar (sejak 2026-09-11 sore; pagi harinya
  masih dust → fee/TVL → volume);
- tabel menampilkan detail fee + active TVL (kolom A.TVL, Fee/TVL dengan
  angka fee USD, Vol 24h dengan Δ volume);
- tanda chip **🏆 BEST POOL** (2026-09-12): baris dengan dust <= 0,035% MC
  (``BEST_DUST_MARK_PCT``, inklusif) ditandai di kolom Dust %MC + dihitung
  di pill kepala card — penanda visual, bukan saringan (saringan tetap
  0,05%).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import best_pool_ui as bp
import meteora_screener as ms

APP = str(Path(__file__).resolve().parent.parent / "app.py")
SOL = ms.SOL_MINT
QUERY = "pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000"


def _token(addr, symbol="TOK", mc=1_000_000, top10=20.0):
    return {"address": addr, "symbol": symbol, "name": symbol,
            "market_cap": mc, "fdv": mc, "price": 0.01, "holders": 1200,
            "top_holders_pct": top10}


def _pool(addr="P1", mint="MintAAA", *, active_tvl=60_000, ratio=40.0,
          volatility=6.2, total_lps=88, fee_pct=2.0, volume=1_200_000,
          fee=24_000.0, volume_change_pct=12.5, top10=20.0):
    return {
        "pool_address": addr, "name": "TOK-SOL", "pool_type": "dlmm",
        "token_x": _token(mint, top10=top10),
        "token_y": _token(SOL, "SOL", mc=1e9, top10=0.5),
        "tvl": active_tvl * 1.1, "active_tvl": active_tvl,
        "fee_active_tvl_ratio": ratio, "volume": volume, "fee": fee,
        "volume_change_pct": volume_change_pct,
        "fee_pct": fee_pct, "volatility": volatility,
        "total_lps": total_lps,
    }


def _row(**over):
    # Default-nya lolos semua saringan layar (volatility 6,2% >= 2%, volume
    # 24 jam $1,2M >= $1M, dust 0,03% < 0,05%) supaya tiap tes hanya perlu
    # mengubah satu angka untuk menguji satu syarat.
    row = {
        "pool_address": "P1", "ca": "MintAAA", "symbol": "AAA",
        "mc": 1_000_000, "tvl": 66_000, "active_tvl": 60_000,
        "fee_active_tvl_ratio": 40.0, "volume": 1_200_000, "fee": 24_000.0,
        "volume_change_pct": 12.5, "fee_pct": 2.0, "volatility": 6.2,
        "total_lps": 88, "top_holders_pct": 20.0,
        "analysis": {"holders": {"dust_pct_mc": 0.03, "dust_count": 12,
                                 "total_fetched": 1200,
                                 "wallets_analyzed": 1100}},
    }
    row.update(over)
    return row


def _dust(row, pct):
    row = dict(row)
    row["analysis"] = {"holders": {"dust_pct_mc": pct, "dust_count": 5,
                                   "total_fetched": 1000,
                                   "wallets_analyzed": 900}}
    return row


class BestFilterQueryTest(unittest.TestCase):
    def test_filter_by_matches_curl(self):
        """Query = persis curl user, angka dibaca dari konstanta."""
        self.assertEqual(ms.best_filter_by(), QUERY)
        self.assertEqual(ms.BEST_FEE_PCT_MIN, 2.0)
        self.assertEqual(ms.BEST_ACTIVE_TVL_MIN, 50_000.0)

    def test_fetch_sends_best_params(self):
        with mock.patch.object(ms, "_http_get",
                               return_value={"data": []}) as http:
            ms.fetch_best_pools()
        args, _kwargs = http.call_args
        self.assertEqual(args[0], ms.POOLS_URL)
        self.assertEqual(args[1], {
            "page_size": 50, "timeframe": "24h", "category": "top",
            "filter_by": QUERY,
        })

    def test_payload_rows_only(self):
        with mock.patch.object(ms, "_http_get",
                               return_value={"data": [{"pool_address": "P1"},
                                                      "rusak", None]}):
            pools = ms.fetch_best_pools()
        self.assertEqual(pools, [{"pool_address": "P1"}])


class RowMetricsTest(unittest.TestCase):
    def test_row_captures_detail_and_sort_metrics(self):
        row = ms.rows_from_pools(
            [_pool(volatility=7.1, total_lps=64, top10=23.5,
                   fee=97_718.0, volume_change_pct=-34.46)])[0]
        self.assertEqual(row["volatility"], 7.1)
        self.assertEqual(row["total_lps"], 64)
        # top 10 holder diambil dari token base, bukan sisi quote (SOL 0,5%).
        self.assertEqual(row["top_holders_pct"], 23.5)
        # detail fee / active TVL + kunci urut kenaikan volume.
        self.assertEqual(row["fee"], 97_718.0)
        self.assertEqual(row["volume_change_pct"], -34.46)
        self.assertEqual(row["active_tvl"], 60_000)
        self.assertEqual(row["ca"], "MintAAA")

    def test_missing_change_defaults_to_zero(self):
        pool = _pool()
        pool.pop("volume_change_pct")
        pool.pop("fee")
        row = ms.rows_from_pools([pool])[0]
        self.assertEqual((row["volume_change_pct"], row["fee"]), (0.0, 0.0))

    def test_duplicate_pool_address_dropped(self):
        rows = ms.rows_from_pools([_pool("P1"), _pool("P1"), _pool("P2")])
        self.assertEqual([r["pool_address"] for r in rows], ["P1", "P2"])


class BestGatesTest(unittest.TestCase):
    """Layar: volatility >= 2% + volume 24 jam >= $1M (metrik), dust < 0,05%."""

    def test_passing_row_has_no_gap(self):
        self.assertEqual(ms.row_best_gaps(_row()), [])
        self.assertTrue(ms.row_dust_ok(_row()))

    def test_volatility_minimal_inklusif(self):
        """Volatility 2,0% = "minimal 2%" → lolos; di bawah itu gugur."""
        self.assertEqual(ms.row_best_gaps(_row(volatility=2.0)), [])
        self.assertEqual(ms.row_best_gaps(_row(volatility=1.99)),
                         ["volatility < 2%"])

    def test_volume_24h_minimal_inklusif(self):
        """Permintaan user 2026-09-12: "minimal volume 24 jam adalah 1M,
        dibawah itu jangan di show" — tepat $1M lolos, di bawahnya gugur."""
        self.assertEqual(ms.BEST_VOLUME_24H_MIN, 1_000_000.0)
        self.assertEqual(ms.row_best_gaps(_row(volume=1_000_000)), [])
        self.assertEqual(ms.row_best_gaps(_row(volume=1_500_000)), [])
        self.assertEqual(ms.row_best_gaps(_row(volume=999_999.99)),
                         ["volume 24 jam < $1,000,000"])
        self.assertEqual(ms.row_best_gaps(_row(volume=0)),
                         ["volume 24 jam < $1,000,000"])

    def test_volume_missing_is_rejected(self):
        """Volume tidak ada = tidak terbukti ramai → gugur (sama seperti
        volatility ``None``), bukan diloloskan diam-diam."""
        self.assertEqual(ms.row_best_gaps(_row(volume=None)),
                         ["volume 24 jam < $1,000,000"])

    def test_ambang_volume_diikuti_teks_gap(self):
        """Label gap dibaca dari konstanta — ubah ambang, teks ikut."""
        with mock.patch.object(ms, "BEST_VOLUME_24H_MIN", 2_500_000.0):
            self.assertEqual(ms.row_best_gaps(_row(volume=1_200_000)),
                             ["volume 24 jam < $2,500,000"])

    def test_old_screens_are_gone(self):
        """Fee/active TVL, top 10 holder, total LPs, active TVL tidak lagi
        menyaring (kriteria lama diganti total 2026-09-11)."""
        row = _row(active_tvl=0, fee_active_tvl_ratio=0.1,
                   top_holders_pct=99.0, total_lps=0, fee_pct=0.5)
        self.assertEqual(ms.row_best_gaps(row), [])
        for gone in ("BEST_FEE_RATIO_MIN", "BEST_TOP10_MAX_PCT",
                     "BEST_TOTAL_LPS_MIN"):
            self.assertFalse(hasattr(ms, gone), gone)

    def test_missing_data_is_rejected(self):
        self.assertEqual(len(ms.row_best_gaps(_row(volatility=None))), 1)
        self.assertEqual(len(ms.row_best_gaps(_row(volume=None))), 1)
        # Keduanya hilang → dua gap dilaporkan (bukan cuma yang pertama).
        self.assertEqual(
            ms.row_best_gaps(_row(volatility=None, volume=None)),
            ["volatility < 2%", "volume 24 jam < $1,000,000"])
        self.assertFalse(ms.row_dust_ok(_row(analysis=None,
                                            dust_pct_mc=None)))

    def test_dust_boundary_is_strict_below(self):
        ok = _row(analysis={"holders": {"dust_pct_mc": 0.0499}})
        bad = _row(analysis={"holders": {"dust_pct_mc": 0.05}})
        self.assertTrue(ms.row_dust_ok(ok))
        self.assertFalse(ms.row_dust_ok(bad))
        self.assertEqual(ms.BEST_DUST_MAX_PCT, 0.05)


class BestPoolMarkTest(unittest.TestCase):
    """Tanda chip 🏆 BEST POOL: dust **<= 0,035% MC** (inklusif, 2026-09-12)."""

    def test_mark_boundary_is_inclusive(self):
        self.assertEqual(ms.BEST_DUST_MARK_PCT, 0.035)
        self.assertTrue(ms.row_best_pool(_dust(_row(), 0.0)))
        self.assertTrue(ms.row_best_pool(_dust(_row(), 0.035)))
        self.assertTrue(ms.row_best_pool(_dust(_row(), 0.034999)))
        self.assertFalse(ms.row_best_pool(_dust(_row(), 0.035001)))

    def test_mark_is_visual_not_a_filter(self):
        """0,04% tetap lolos listing (saringan 0,05%) — hanya tanpa tanda."""
        row = _dust(_row(), 0.04)
        self.assertTrue(ms.row_dust_ok(row))
        self.assertFalse(ms.row_best_pool(row))

    def test_mark_never_for_missing_dust(self):
        self.assertFalse(ms.row_best_pool(_row(analysis=None,
                                               dust_pct_mc=None)))
        self.assertFalse(ms.row_best_pool({"analysis":
                                           {"holders": {"dust_pct_mc": None}},
                                           "dust_pct_mc": None}))

    def test_fallback_to_row_level_dust(self):
        """Baris session lama (tanpa ``analysis``) dinilai dari field baris."""
        self.assertTrue(ms.row_best_pool({"dust_pct_mc": 0.02}))
        self.assertFalse(ms.row_best_pool({"dust_pct_mc": 0.045}))

    def test_tooltip_mentions_the_mark(self):
        tooltip = bp.best_pool_tooltip()
        self.assertIn(f"dust <= {ms.BEST_DUST_MARK_PCT:g}% marketcap", tooltip)
        self.assertIn("🏆 BEST POOL", tooltip)


class ScanHolderBestBadgeTest(unittest.TestCase):
    """Tulisan **BEST** emas kelap-kelip di 🛰 Scan Holder (2026-09-12).

    Permintaan user: "jika kondisi %dust <= 0.035 kasih tulisan BEST yang
    agak besar, dengan efek kelap kelip, warnanya GOLD". Ambangnya **satu
    sumber** dengan tanda 🏆 BEST POOL card ini (``BEST_DUST_MARK_PCT``) —
    jadi bila ambang Best Pool diubah, Scan Holder ikut berubah (diuji lewat
    ``mock.patch.object``). AppTest-nya (render di section) ada di
    ``tests/test_rh_card_ui.py``.
    """

    @staticmethod
    def _badge(pct):
        from dashboard_components import _scan_best_badge_html

        return _scan_best_badge_html(pct)

    @staticmethod
    def _ok(pct):
        from dashboard_components import _scan_best_mark_ok

        return _scan_best_mark_ok(pct)

    def test_batas_inklusif(self):
        self.assertTrue(self._ok(0.035))
        self.assertTrue(self._ok(0.034999))
        self.assertTrue(self._ok(0.0))
        self.assertFalse(self._ok(0.035001))
        self.assertFalse(self._ok(0.041))

    def test_data_hilang_tidak_pernah_ditandai(self):
        """Dust gagal diambil (``None``/teks) → tanpa badge, tanpa crash."""
        for value in (None, "", "kosong", {}, []):
            self.assertFalse(self._ok(value), value)
            self.assertEqual(self._badge(value), "", value)
        self.assertTrue(self._ok("0.02"))  # angka sebagai teks tetap dinilai

    def test_html_badge_emas_kelap_kelip(self):
        html_text = self._badge(0.035)
        self.assertIn('class="scan-best-gold"', html_text)
        self.assertIn(">BEST</span>", html_text)
        self.assertIn("title=", html_text)
        self.assertIn(f"{ms.BEST_DUST_MARK_PCT:g}% marketcap", html_text)
        # Gaya (ukuran/warna/animasi) hidup di CSS render_styles, bukan
        # atribut style inline — st.markdown men-sanitasi style inline.
        self.assertNotIn("style=", html_text)

    def test_css_di_render_styles(self):
        """CSS badge: warna emas + animasi kelap-kelip + hormati reduced
        motion. Diambil dari sumbernya (``render_styles``) supaya tes tidak
        bergantung pada Streamlit runtime."""
        import inspect

        import dashboard_components as dc

        source = inspect.getsource(dc.render_styles)
        self.assertIn(".scan-best-gold", source)
        self.assertIn("#ffd700", source.lower())
        self.assertIn("@keyframes scan-best-blink", source)
        self.assertIn("animation:scan-best-blink", source)
        self.assertIn("prefers-reduced-motion", source)
        # Nama class-nya bukan varian `dust-best`: pin regression card Scan
        # Meteora menghitung kemunculan string class chip emas itu di body.
        self.assertNotIn('class="dust-badge dust-best"',
                         dc._scan_best_badge_html(0.01))

    def test_ambang_mengikuti_konstanta_best_pool(self):
        with mock.patch.object(ms, "BEST_DUST_MARK_PCT", 0.02):
            self.assertEqual(self._badge(0.03), "")
            self.assertIn(">BEST</span>", self._badge(0.02))


class FilterAndSortTest(unittest.TestCase):
    def test_filter_splits_metric_and_dust(self):
        rows = [
            _row(),
            _row(pool_address="P2", volatility=1.0),
            _row(pool_address="P3",
                 analysis={"holders": {"dust_pct_mc": 0.4}}),
        ]
        kept, hidden_metric, hidden_dust = ms.filter_best_rows(rows)
        self.assertEqual([r["pool_address"] for r in kept], ["P1"])
        self.assertEqual((hidden_metric, hidden_dust), (1, 1))

    def test_filter_menyembunyikan_volume_di_bawah_1m(self):
        """Volume 24 jam < $1M tidak ditampilkan (permintaan user 2026-09-12).

        Masuk hitungan ``hidden_metric`` (bukan ``hidden_dust``) karena
        volumenya metrik pool dari listing API — tidak butuh scan holder.
        """
        rows = [
            _row(),
            _row(pool_address="SEPI", volume=250_000),
            _row(pool_address="PAS", volume=1_000_000),
        ]
        kept, hidden_metric, hidden_dust = ms.filter_best_rows(rows)
        self.assertEqual([r["pool_address"] for r in kept], ["P1", "PAS"])
        self.assertEqual((hidden_metric, hidden_dust), (1, 0))

    def test_sort_volume_change_then_dust_then_fee_ratio(self):
        rows = [
            _dust({"pool_address": "A", "symbol": "AAA",
                   "fee_active_tvl_ratio": 10.0, "volume_change_pct": 99.0},
                  0.030),
            _dust({"pool_address": "B", "symbol": "BBB",
                   "fee_active_tvl_ratio": 5.0, "volume_change_pct": 80.0},
                  0.010),
            _dust({"pool_address": "C", "symbol": "CCC",
                   "fee_active_tvl_ratio": 90.0, "volume_change_pct": 80.0},
                  0.030),
            _dust({"pool_address": "D", "symbol": "DDD",
                   "fee_active_tvl_ratio": 10.0, "volume_change_pct": 80.0},
                  0.030),
            _row(pool_address="E", symbol="EEE", fee_active_tvl_ratio=999.0,
                 volume_change_pct=500.0, analysis=None),
        ]
        order = [row["pool_address"] for row in ms.sort_best_rows(rows)]
        # kenaikan volume terbesar dulu (A Δ99%); di Δ80% yang sama dust
        # terkecil dulu (B 0,010% → C/D 0,030%); di dust seri fee/active TVL
        # terbesar dulu (C 90% → D 10%); baris tanpa dust paling bawah meski
        # Δ volume + rasio fee-nya paling gede (E).
        self.assertEqual(order, ["A", "B", "C", "D", "E"])

    def test_tie_break_uses_display_precision(self):
        """0,0301% dan 0,0304% tampil sama (0,030%) → fee/TVL yang menentukan.

        Kedua baris Δ volumenya sama (default 12,5%) dan dust tampilannya
        seri, jadi rasio fee/active TVL yang memutuskan urutannya."""
        rows = [
            _row(pool_address="LOW", symbol="AAA", fee_active_tvl_ratio=3.0,
                 analysis={"holders": {"dust_pct_mc": 0.0301}}),
            _row(pool_address="HIGH", symbol="BBB", fee_active_tvl_ratio=70.0,
                 analysis={"holders": {"dust_pct_mc": 0.0304}}),
        ]
        order = [row["pool_address"] for row in ms.sort_best_rows(rows)]
        self.assertEqual(order, ["HIGH", "LOW"])

    def test_volume_change_is_primary_key(self):
        """Kenaikan volume memutuskan duluan (kunci urut pertama).

        Dust dan fee/active TVL sama persis → Δ volume 61% di atas Δ 4%
        (sejak 2026-09-11 sore; sebelumnya volume hanya tie-break terakhir).
        """
        rows = [
            _row(pool_address="KECIL", symbol="AAA", fee_active_tvl_ratio=50.0,
                 volume_change_pct=4.0,
                 analysis={"holders": {"dust_pct_mc": 0.02}}),
            _row(pool_address="BESAR", symbol="BBB",
                 fee_active_tvl_ratio=50.0, volume_change_pct=61.0,
                 analysis={"holders": {"dust_pct_mc": 0.02}}),
        ]
        order = [row["pool_address"] for row in ms.sort_best_rows(rows)]
        self.assertEqual(order, ["BESAR", "KECIL"])


class ScanBestTest(unittest.TestCase):
    def test_scan_filters_before_holder_and_sorts_result(self):
        # P2 gugur volatility (1%), P4 gugur volume 24 jam ($400K < $1M) —
        # keduanya harus tersaring SEBELUM holder di-fetch (hemat kuota
        # Helius); P1/P3 lolos semua syarat metrik.
        pools = [_pool("P1", "MintAAA", volume=1_200_000),
                 _pool("P2", "MintBBB", volatility=1.0, volume=1_500_000),
                 _pool("P3", "MintCCC", volume=5_000_000, ratio=80.0),
                 _pool("P4", "MintDDD", volume=400_000)]
        dusts = {"MintAAA": 0.02, "MintBBB": 0.01, "MintCCC": 0.02}

        def fake_enrich(rows, **_kwargs):
            out = []
            for row in rows:
                item = dict(row)
                pct = dusts.get(row["ca"])
                item["analysis"] = {"holders": {
                    "dust_pct_mc": pct, "dust_count": 5,
                    "total_fetched": 1000, "wallets_analyzed": 900}}
                item["dust_pct_mc"] = pct
                item["dust_count"] = 5
                out.append(item)
            return out

        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "enrich_pools",
                                  side_effect=fake_enrich) as enrich:
            result = ms.scan_best_meteora(max_wallets=2000)

        # P2 gugur di volatility, P4 di volume 24 jam → holder keduanya
        # tidak perlu di-fetch (saringan metrik jalan sebelum enrich).
        fetched = [row["pool_address"] for row in enrich.call_args.args[0]]
        self.assertEqual(fetched, ["P1", "P3"])
        self.assertEqual(result["fetched"], 4)
        self.assertEqual(result["hidden_metric"], 2)
        self.assertEqual(result["hidden_dust"], 0)
        self.assertEqual(result["error"], "")
        # Δ volume sama (default 12,5%) + dust sama (0,02%) → fee/active TVL
        # terbesar dulu: P3 (80) di atas P1 (40), meski volume P1 lebih kecil.
        self.assertEqual([row["pool_address"] for row in result["rows"]],
                         ["P3", "P1"])

    def test_scan_reports_api_error(self):
        with mock.patch.object(ms, "fetch_best_pools",
                               side_effect=RuntimeError("Meteora HTTP 503")):
            result = ms.scan_best_meteora(max_wallets=2000)
        self.assertIn("Meteora HTTP 503", result["error"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["fetched"], 0)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class BestPoolCardTest(unittest.TestCase):
    """Card 🏆 Scan Best Pool Meteora ada di halaman utama (``app.py``)."""

    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: {}),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: {"updated_at": None,
                                                  "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: {"tokens": {}}),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=90).run()

    def test_card_and_button_render_on_main_page(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(ms.BEST_CARD_TITLE, body)
        keys = [button.key or "" for button in app.button]
        self.assertIn("best-pool-scan-now", keys)

    def test_detail_karakteristik_di_tooltip_bukan_caption(self):
        """Rule filter card jadi tooltip judul (bukan caption panjang).

        angkanya dibaca dari ``meteora_screener.BEST_*`` sehingga tidak bisa
        beda dari rule yang jalan. Kriteria lama (fee/active TVL > 20%, top
        10 < 30%, total LPs > 20, active TVL > 10K) tidak boleh muncul lagi.
        """
        import html as _html

        app = self._app()
        # atribut ``title`` di-escape (``<`` → ``&lt;``) — unescape dulu
        body = _html.unescape("\n".join(node.value for node in app.markdown))
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("title=\"Listing API Meteora 24 jam", body)
        for label in (f"pool_type=dlmm&&fee_pct>={ms.BEST_FEE_PCT_MIN:g}"
                      f"&&active_tvl>={int(ms.BEST_ACTIVE_TVL_MIN)}",
                      f"dust holder < {ms.BEST_DUST_MAX_PCT:g}% marketcap",
                      f"volatility >= {ms.BEST_VOLATILITY_MIN:g}%",
                      # saringan volume 24 jam (2026-09-12) ikut dijelaskan
                      # di tooltip dengan angka dari konstanta.
                      f"volume 24 jam >= ${ms.BEST_VOLUME_24H_MIN:,.0f}",
                      "kenaikan volume 24 jam paling besar dulu, lalu dust % "
                      "marketcap terkecil, lalu fee/active TVL paling "
                      "besar"):
            self.assertIn(label, body)
        # rule lama sudah diganti total — tidak boleh tersisa di tooltip
        # card ini (card lain, mis. 🦅 Scan Best Robinhood Coin, memang masih
        # memakai top 10 holder < 30% — makanya dicek di tooltip Best Pool).
        tooltip = bp.best_pool_tooltip()
        self.assertNotIn("top 10 holder", tooltip)
        self.assertNotIn("total LPs", tooltip)
        self.assertNotIn("Replika listing", tooltip)
        # …dan caption deskripsi rule tetap hilang dari badan card.
        self.assertNotIn("Urutan: **dust % MC terkecil**, lalu", captions)
        self.assertNotIn("lalu saringan layar: dust holder", captions)
        # …dan judul card-nya yang membawa tooltip, bukan teks telanjang.
        self.assertIn("title=\"Listing API Meteora", "\n".join(
            node.value for node in app.markdown))

    def test_tooltip_mengikuti_perubahan_konstanta(self):
        """Tooltip dibangun dari konstanta — ubah ambang, teks ikut berubah."""
        tooltip = bp.best_pool_tooltip()
        self.assertIn(f"{ms.BEST_DUST_MAX_PCT:g}%", tooltip)
        self.assertIn(f"{int(ms.BEST_ACTIVE_TVL_MIN)}", tooltip)
        self.assertIn(f"volatility >= {ms.BEST_VOLATILITY_MIN:g}%", tooltip)
        with mock.patch.object(ms, "BEST_VOLATILITY_MIN", 3.5):
            self.assertIn("volatility >= 3.5%", bp.best_pool_tooltip())
        self.assertNotIn("3.5%", bp.best_pool_tooltip())
        with mock.patch.object(ms, "BEST_ACTIVE_TVL_MIN", 75_000.0):
            self.assertIn("active_tvl>=75000", bp.best_pool_tooltip())
        self.assertNotIn("75000", bp.best_pool_tooltip())
        with mock.patch.object(ms, "BEST_VOLUME_24H_MIN", 2_000_000.0):
            self.assertIn("volume 24 jam >= $2,000,000",
                          bp.best_pool_tooltip())
        self.assertNotIn("$2,000,000", bp.best_pool_tooltip())

    def test_listing_uses_stored_result_without_new_scan(self):
        app = self._app()
        app.session_state["best_pool_scan"] = {
            "rows": [_row(pool_address="PoolBest", ca="MintAAA",
                          symbol="AAA", dust_pct_mc=0.03,
                          analysis={"holders": {"dust_pct_mc": 0.03,
                                               "dust_count": 12}})],
            "error": "", "fetched": 4, "hidden_metric": 2,
            "hidden_dust": 1,
        }
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$AAA", body)
        self.assertIn("MintAAA", body)
        self.assertIn("1 pool", body)
        self.assertIn("3 disembunyikan", body)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("1 pool lolos · 3 disembunyikan · listing 4 pool.",
                      captions)
        # tombol ⭐ baris (key diikat ke pool address, bukan index)
        self.assertIn("best-pool-star-PoolBest",
                      [button.key or "" for button in app.button])

    def test_baris_dust_0035_ditandai_chip_best_pool(self):
        """Chip 🏆 BEST POOL (2026-09-12) hanya di baris dust <= 0,035% MC.

        Permintaan user: "tandai jika %dust <= 0.035 menjadi Best Pool" —
        baris 0,032% dapat chip emas di sel Dust %MC + pill rekap di kepala
        card; baris 0,041% (lolos saringan 0,05%) tidak."""
        app = self._app()
        app.session_state["best_pool_scan"] = {
            "rows": [
                _row(pool_address="PoolBest", ca="MintBest", symbol="BST",
                     dust_pct_mc=0.032,
                     analysis={"holders": {"dust_pct_mc": 0.032,
                                           "dust_count": 4}}),
                _row(pool_address="PoolOk", ca="MintOkk", symbol="OKP",
                     dust_pct_mc=0.041, volume_change_pct=3.0,
                     analysis={"holders": {"dust_pct_mc": 0.041,
                                           "dust_count": 7}}),
            ],
            "error": "", "fetched": 2, "hidden_metric": 0, "hidden_dust": 0,
        }
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        bst, okp = body.index("$BST"), body.index("$OKP")
        segment_bst = body[bst:okp]
        # chip tepat satu, di baris 0,032% (angka emas ditandai span).
        self.assertEqual(segment_bst.count('class="dust-badge dust-best"'), 1)
        self.assertIn("🏆 BEST POOL</span>", segment_bst)
        self.assertEqual(body[okp:].count('class="dust-badge dust-best"'), 0)
        # pill rekap kepala card menghitung baris bertanda; tooltip sel dan
        # tooltip card menjelaskan ambang tandanya (angka dari konstanta —
        # ``<=`` di-escape ``&lt;=`` di atribut title, unescape dulu).
        self.assertIn("🏆 BEST POOL 1</span>", body)
        import html as _html
        self.assertIn(f"dust <= {ms.BEST_DUST_MARK_PCT:g}% marketcap",
                      _html.unescape(body))

    def test_tanpa_baris_bertanda_tidak_ada_chip(self):
        """Semua dust di atas 0,035% → tidak ada chip, tidak ada pill."""
        app = self._app()
        app.session_state["best_pool_scan"] = {
            "rows": [_row(pool_address="PoolOk", ca="MintOkk", symbol="OKP",
                          dust_pct_mc=0.041,
                          analysis={"holders": {"dust_pct_mc": 0.041,
                                                "dust_count": 7}})],
            "error": "", "fetched": 1, "hidden_metric": 0, "hidden_dust": 0,
        }
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertNotIn('class="dust-badge dust-best"', body)
        self.assertNotIn("🏆 BEST POOL</span>", body)   # teks chip
        self.assertNotIn("🏆 BEST POOL 1</span>", body)  # pill

    def test_tabel_memakai_kolom_detail_fee_dan_vol(self):
        """Detail fee / active TVL + Δ volume harus tampil di tabel card."""
        app = self._app()
        app.session_state["best_pool_scan"] = {
            "rows": [_row(pool_address="PoolBest", dust_pct_mc=0.03)],
            "error": "", "fetched": 1, "hidden_metric": 0, "hidden_dust": 0,
        }
        app.run()
        body = "\n".join(node.value for node in app.markdown)
        for title in ("A.TVL", "Fee/TVL", "Vol 24h", "Volat", "Dust %MC"):
            self.assertIn(title, body)
        # angka fee USD + tier fee + rasio + perubahan volume (Δ) per baris
        self.assertIn("fee $24.0K·2%", body)
        self.assertIn("40.0%", body)
        self.assertIn("+12.5%", body)
        # kunci urut dijelaskan di tooltip sel (bukan caption): Vol 24h =
        # pertama, Dust %MC = kedua, Fee/TVL = ketiga.
        for key in ("kunci urut pertama", "kunci urut kedua",
                    "kunci urut ketiga"):
            self.assertIn(key, body)
        # Sel Vol 24h = bukti saringan volume baru (2026-09-12): angka
        # ringkas di card, angka penuh + ambang saringan di tooltip sel.
        self.assertIn("$1.20M", body)
        self.assertIn("volume 24 jam $1,200,000", body)
        self.assertIn(f"saringan layar: minimal "
                      f"${ms.BEST_VOLUME_24H_MIN:,.0f}", body)


if __name__ == "__main__":
    unittest.main()
