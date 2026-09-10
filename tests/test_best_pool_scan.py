"""Coverage 🏆 Scan Best Pool Meteora (filter baru + urutan dust → volume).

Filter yang diminta user 2026-09-10:

- query API Meteora ``pool_type=dlmm&&fee_pct>=5&&active_tvl>=10000``
  (timeframe 24 jam, category ``top``);
- layar: dust holder < 0,05% MC, active TVL > 10K, fee/active TVL > 20%,
  volatility > 5%, top 10 holder < 30%, total LPs > 20;
- urutan: dust % MC terkecil dulu, lalu volume terbesar.
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


def _token(addr, symbol="TOK", mc=1_000_000, top10=20.0):
    return {"address": addr, "symbol": symbol, "name": symbol,
            "market_cap": mc, "fdv": mc, "price": 0.01, "holders": 1200,
            "top_holders_pct": top10}


def _pool(addr="P1", mint="MintAAA", *, active_tvl=25_000, ratio=40.0,
          volatility=6.2, total_lps=88, fee_pct=5.0, volume=120_000,
          top10=20.0):
    return {
        "pool_address": addr, "name": "TOK-SOL", "pool_type": "dlmm",
        "token_x": _token(mint, top10=top10),
        "token_y": _token(SOL, "SOL", mc=1e9, top10=0.5),
        "tvl": active_tvl * 1.1, "active_tvl": active_tvl,
        "fee_active_tvl_ratio": ratio, "volume": volume,
        "fee_pct": fee_pct, "volatility": volatility,
        "total_lps": total_lps,
    }


def _row(**over):
    row = {
        "pool_address": "P1", "ca": "MintAAA", "symbol": "AAA",
        "mc": 1_000_000, "tvl": 27_000, "active_tvl": 25_000,
        "fee_active_tvl_ratio": 40.0, "volume": 120_000, "fee_pct": 5.0,
        "volatility": 6.2, "total_lps": 88, "top_holders_pct": 20.0,
        "analysis": {"holders": {"dust_pct_mc": 0.03, "dust_count": 12,
                                 "total_fetched": 1200,
                                 "wallets_analyzed": 1100}},
    }
    row.update(over)
    return row


class BestFilterQueryTest(unittest.TestCase):
    def test_filter_by_matches_curl(self):
        self.assertEqual(ms.best_filter_by(),
                         "pool_type=dlmm&&fee_pct>=5&&active_tvl>=10000")

    def test_fetch_sends_best_params(self):
        with mock.patch.object(ms, "_http_get",
                               return_value={"data": []}) as http:
            ms.fetch_best_pools()
        args, _kwargs = http.call_args
        self.assertEqual(args[0], ms.POOLS_URL)
        self.assertEqual(args[1], {
            "page_size": 50, "timeframe": "24h", "category": "top",
            "filter_by": "pool_type=dlmm&&fee_pct>=5&&active_tvl>=10000",
        })

    def test_payload_rows_only(self):
        with mock.patch.object(ms, "_http_get",
                               return_value={"data": [{"pool_address": "P1"},
                                                      "rusak", None]}):
            pools = ms.fetch_best_pools()
        self.assertEqual(pools, [{"pool_address": "P1"}])


class RowMetricsTest(unittest.TestCase):
    def test_row_captures_new_metrics_from_base_token(self):
        row = ms.rows_from_pools(
            [_pool(volatility=7.1, total_lps=64, top10=23.5)])[0]
        self.assertEqual(row["volatility"], 7.1)
        self.assertEqual(row["total_lps"], 64)
        # top 10 holder diambil dari token base, bukan sisi quote (SOL 0,5%).
        self.assertEqual(row["top_holders_pct"], 23.5)
        self.assertEqual(row["ca"], "MintAAA")

    def test_duplicate_pool_address_dropped(self):
        rows = ms.rows_from_pools([_pool("P1"), _pool("P1"), _pool("P2")])
        self.assertEqual([r["pool_address"] for r in rows], ["P1", "P2"])


class BestGatesTest(unittest.TestCase):
    def test_passing_row_has_no_gap(self):
        self.assertEqual(ms.row_best_gaps(_row()), [])
        self.assertTrue(ms.row_dust_ok(_row()))

    def test_each_rule_is_strict(self):
        cases = {
            "active TVL == 10K": _row(active_tvl=10_000),
            "fee/active TVL == 20%": _row(fee_active_tvl_ratio=20.0),
            "volatility == 5%": _row(volatility=5.0),
            "top10 == 30%": _row(top_holders_pct=30.0),
            "total LPs == 20": _row(total_lps=20),
        }
        for label, row in cases.items():
            gaps = ms.row_best_gaps(row)
            self.assertEqual(len(gaps), 1, label)
            self.assertFalse(ms.row_best_gaps(row) == [], label)

    def test_missing_data_is_rejected(self):
        self.assertEqual(len(ms.row_best_gaps(_row(volatility=None))), 1)
        self.assertFalse(ms.row_dust_ok(_row(analysis=None,
                                            dust_pct_mc=None)))

    def test_dust_boundary_is_strict_below(self):
        ok = _row(analysis={"holders": {"dust_pct_mc": 0.0499}})
        bad = _row(analysis={"holders": {"dust_pct_mc": 0.05}})
        self.assertTrue(ms.row_dust_ok(ok))
        self.assertFalse(ms.row_dust_ok(bad))


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

    def test_sort_dust_ascending_then_volume_descending(self):
        def _dust(row, pct):
            return _row(**row, analysis={"holders": {"dust_pct_mc": pct}})

        rows = [
            _dust({"pool_address": "A", "symbol": "AAA", "volume": 1_000},
                  0.030),
            _dust({"pool_address": "B", "symbol": "BBB", "volume": 500},
                  0.010),
            _dust({"pool_address": "C", "symbol": "CCC", "volume": 9_000},
                  0.030),
            _row(pool_address="D", symbol="DDD", volume=10 ** 9,
                 analysis=None),
        ]
        order = [row["pool_address"] for row in ms.sort_best_rows(rows)]
        # dust terkecil dulu (B), lalu volume terbesar di dust yang sama
        # (C sebelum A), baris tanpa dust paling bawah (D).
        self.assertEqual(order, ["B", "C", "A", "D"])

    def test_sort_tie_uses_display_precision(self):
        """0,0301% dan 0,0304% tampil sama (0,030%) → volume terbesar dulu."""
        rows = [
            _row(pool_address="SMALL", symbol="AAA", volume=1_000,
                 analysis={"holders": {"dust_pct_mc": 0.0301}}),
            _row(pool_address="BIG", symbol="BBB", volume=250_000,
                 analysis={"holders": {"dust_pct_mc": 0.0304}}),
        ]
        order = [row["pool_address"] for row in ms.sort_best_rows(rows)]
        self.assertEqual(order, ["BIG", "SMALL"])


class ScanBestTest(unittest.TestCase):
    def test_scan_filters_before_holder_and_sorts_result(self):
        pools = [_pool("P1", "MintAAA", volume=5_000),
                 _pool("P2", "MintBBB", volatility=1.0, volume=9_000),
                 _pool("P3", "MintCCC", volume=50_000)]
        dusts = {"MintAAA": 0.02, "MintBBB": 0.01, "MintCCC": 0.01}

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

        # P2 gugur di volatility → holder-nya tidak perlu di-fetch.
        fetched = [row["pool_address"] for row in enrich.call_args.args[0]]
        self.assertEqual(fetched, ["P1", "P3"])
        self.assertEqual(result["fetched"], 3)
        self.assertEqual(result["hidden_metric"], 1)
        self.assertEqual(result["hidden_dust"], 0)
        self.assertEqual(result["error"], "")
        # dust sama (0,01%) hanya untuk P3; P3 bervolume terbesar tetap di
        # atas P1 (dust 0,02%).
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
        """Rule filter card jadi tooltip judul (permintaan user 2026-09-10).

        Teks ambang masih harus disebut — tapi di atribut ``title`` pada teks
        judul, bukan sebagai caption panjang di badan card. angkanya dibaca
        dari ``meteora_screener.BEST_*`` sehingga tidak bisa beda dari rule.
        """
        import html as _html

        app = self._app()
        # atribut ``title`` di-escape (``<`` → ``&lt;``) — unescape dulu
        body = _html.unescape("\n".join(node.value for node in app.markdown))
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn('title="Replika listing Scan Meteora Pool', body)
        for label in (f"dust holder < {ms.BEST_DUST_MAX_PCT:g}% marketcap",
                      f"fee/active TVL > {ms.BEST_FEE_RATIO_MIN:g}%",
                      f"volatility > {ms.BEST_VOLATILITY_MIN:g}%",
                      f"top 10 holder < {ms.BEST_TOP10_MAX_PCT:g}% supply",
                      f"total LPs > {ms.BEST_TOTAL_LPS_MIN:g}",
                      "dust % marketcap terkecil dulu, lalu volume terbesar"):
            self.assertIn(label, body)
        # caption deskripsi rule sudah hilang dari badan card…
        self.assertNotIn("Urutan: **dust % MC terkecil**, lalu", captions)
        self.assertNotIn("lalu saringan layar: dust holder", captions)
        # …dan judul card-nya yang membawa tooltip, bukan teks telanjang.
        self.assertIn('title="Replika', "\n".join(
            node.value for node in app.markdown))

    def test_tooltip_mengikuti_perubahan_konstanta(self):
        """Tooltip dibangun dari konstanta — ubah ambang, teks ikut berubah."""
        tooltip = bp.best_pool_tooltip()
        self.assertIn(f"{ms.BEST_DUST_MAX_PCT:g}%", tooltip)
        self.assertIn(f"{int(ms.BEST_ACTIVE_TVL_MIN):,}", tooltip)
        with mock.patch.object(ms, "BEST_DUST_MAX_PCT", 0.07):
            self.assertIn("0.07%", bp.best_pool_tooltip())
        self.assertNotIn("0.07%", bp.best_pool_tooltip())

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


if __name__ == "__main__":
    unittest.main()
