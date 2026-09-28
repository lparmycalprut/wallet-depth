"""Token:SOL is retained as information but no longer filters Best Pool."""
import inspect
import unittest
from unittest import mock

import gmgn_liquidity as gl
import meteora_screener as ms

TOKEN = "CbcyNo7m1amFWqEQm2m4PLv1UNvpcL3C1Ujm6AkzpKoU"


def _detail(*, token_amount=3_309_152.809654, token_price=0.0185571483206408,
            sol_amount=3_286.474952877, sol_price=121.79789459574916):
    return {
        "address": "HC7ArykAUSamJSAJ1aYLrS8aAamvBb1JvqMf1woUtnKo",
        "token_x": {"address": TOKEN, "symbol": "e/acc", "price": token_price},
        "token_y": {"address": ms.SOL_MINT, "symbol": "SOL", "price": sol_price},
        "token_x_amount": token_amount,
        "token_y_amount": sol_amount,
    }


def _pool(address, *, fee=80.0, volatility=6.0, lps=150.0):
    return {
        "pool_address": address,
        "name": "TOK-SOL",
        "pool_type": "dlmm",
        "token_x": {"address": TOKEN + address[-1:], "symbol": address,
                    "name": address, "price": 0.01,
                    "market_cap": 1_000_000, "top_holders_pct": 10.0},
        "token_y": {"address": ms.SOL_MINT, "symbol": "SOL", "price": 120.0},
        "tvl": 150_000.0,
        "active_tvl": 120_000.0,
        "fee_active_tvl_ratio": fee,
        "volatility": volatility,
        "total_lps": lps,
        "volume": 2_000_000.0,
        "fee": 48_000.0,
    }


def _report(ratio, *, ok=True, error=""):
    return {
        "checked": True,
        "ok": ok,
        "token_value_usd": 100_000.0 * ratio,
        "sol_value_usd": 100_000.0,
        "token_to_sol_ratio": ratio,
        "source": "test",
        "error": error,
    }


class ThresholdTest(unittest.TestCase):
    def test_thresholds_diperketat_dan_pool_baru_dihapus(self):
        self.assertEqual(ms.BEST_ACTIVE_TVL_MIN, 50_000.0)
        self.assertEqual(ms.BEST_LPS_MIN, 100.0)
        for name in ("BEST_SOL_TOKEN_MAX_RATIO", "BEST_TOKEN_SOL_MIN_RATIO",
                     "BEST_TOKEN_SOL_RATIO_LIMIT_LABEL"):
            self.assertFalse(hasattr(ms, name), name)
        for name in ("NEW_POOL_MAX_AGE_HOURS", "NEW_POOL_LABEL",
                     "row_new_pool", "row_new_pool_gaps", "new_pool_rule_text"):
            self.assertFalse(hasattr(ms, name), name)
        self.assertFalse(hasattr(gl, "STRATEGY_NEW_POOL"))
        self.assertNotIn(
            "distribution", inspect.signature(ms.scan_best_lane).parameters,
            "gate distribusi wajib tidak boleh punya kwarg bypass")
        self.assertNotIn(
            "distribution", inspect.signature(ms.scan_best_meteora).parameters)

    def test_query_best_pool_dan_regular_sama_sama_50k(self):
        self.assertEqual(ms.best_filter_by(),
                         "pool_type=dlmm&&active_tvl>=50000")
        self.assertEqual(ms.filter_by(),
                         "pool_type=dlmm&&active_tvl>=50000")

    def test_semua_rasio_hanya_informasi(self):
        base = {"timeframe": "24h", "fee_active_tvl_ratio": 80.0,
                "volatility": 6.0, "total_lps": 100,
                "top_holders_pct": 10.0,
                "bundler": {"ok": True, "combined_rate": 0.30}}
        exact = dict(base, liquidity_distribution=_report(0.5))
        over_sol_cap = dict(base, liquidity_distribution=_report(0.4999))
        under_sol_cap = dict(base, liquidity_distribution=_report(0.5001))
        self.assertEqual(ms.liquidity_distribution_label(exact), "1:2")
        self.assertEqual(ms.row_best_final_gaps(exact), [])
        self.assertEqual(ms.liquidity_distribution_label(over_sol_cap), "1:2")
        self.assertEqual(ms.row_best_final_gaps(over_sol_cap), [])
        self.assertEqual(ms.liquidity_distribution_label(under_sol_cap), "1:2")
        self.assertEqual(ms.row_best_final_gaps(under_sol_cap), [])
        # Label kolom tetap satu angka di belakang koma; presisi penuh masih
        # tersedia untuk tooltip walaupun tidak lagi menjadi alasan gugur.
        self.assertEqual(
            ms.liquidity_distribution_label(over_sol_cap, decimals=4), "1:2.0004")
        self.assertEqual(
            ms.liquidity_distribution_label(under_sol_cap, decimals=4), "1:1.9996")

    def test_label_kolom_satu_angka_di_belakang_koma(self):
        base = {"timeframe": "24h"}
        self.assertEqual(
            ms.liquidity_distribution_label(
                dict(base, liquidity_distribution=_report(0.15341))),
            "1:6.5")
        # Token lebih berat (hanya muncul di tabel "dilewati").
        self.assertEqual(
            ms.liquidity_distribution_label(
                dict(base, liquidity_distribution=_report(2.345))),
            "2.3:1")
        # Rasio bulat tidak menulis nol di ekor, dan tanpa data tetap "—".
        self.assertEqual(
            ms.liquidity_distribution_label(
                dict(base, liquidity_distribution=_report(0.1))),
            "1:10")
        self.assertEqual(ms.liquidity_distribution_label(base), "—")

    def test_hilang_error_dan_non_sol_tidak_menggugurkan(self):
        row = {"timeframe": "24h", "fee_active_tvl_ratio": 80.0,
               "volatility": 6.0, "total_lps": 100,
               "top_holders_pct": 10.0,
               "bundler": {"ok": True, "combined_rate": 0.30}}
        self.assertEqual(ms.row_best_final_gaps(row), [])
        row["liquidity_distribution"] = _report(
            0, ok=False, error="pool bukan pasangan token-SOL")
        self.assertEqual(ms.row_best_final_gaps(row), [])


class OfficialPoolDetailTest(unittest.TestCase):
    def test_nilai_usd_bukan_perbandingan_jumlah_koin(self):
        report = ms._liquidity_distribution_report(_detail(), base_mint=TOKEN)
        self.assertTrue(report["ok"])
        self.assertAlmostEqual(report["token_value_usd"], 61_408.44, places=0)
        self.assertAlmostEqual(report["sol_value_usd"], 400_285.73, places=0)
        self.assertAlmostEqual(report["token_to_sol_ratio"], 0.15341, places=4)
        row = {"liquidity_distribution": report}
        self.assertTrue(ms.liquidity_distribution_label(row).startswith("1:6.5"))
        # Rasio hanya informasi: tidak pernah menghasilkan alasan gugur.
        self.assertEqual(ms.row_liquidity_distribution_gap(row), "")

    def test_token_boleh_berada_di_sisi_y(self):
        payload = _detail()
        payload["token_x"], payload["token_y"] = payload["token_y"], payload["token_x"]
        payload["token_x_amount"], payload["token_y_amount"] = (
            payload["token_y_amount"], payload["token_x_amount"])
        report = ms._liquidity_distribution_report(payload, base_mint=TOKEN)
        self.assertTrue(report["ok"])
        self.assertEqual(report["token"]["mint"], TOKEN)
        self.assertEqual(report["sol"]["mint"], ms.SOL_MINT)

    def test_fetch_memakai_endpoint_detail_resmi(self):
        with mock.patch.object(ms, "_http_get", return_value=_detail()) as http:
            report = ms.fetch_pool_liquidity_distribution(
                "HC7ArykAUSamJSAJ1aYLrS8aAamvBb1JvqMf1woUtnKo",
                base_mint=TOKEN, timeout=7)
        self.assertTrue(report["ok"])
        self.assertEqual(http.call_args.args[0],
                         ms.DLMM_POOLS_URL + "/HC7ArykAUSamJSAJ1aYLrS8aAamvBb1JvqMf1woUtnKo")
        self.assertEqual(http.call_args.args[1], {})
        self.assertEqual(http.call_args.kwargs["timeout"], 7)


class PipelineTest(unittest.TestCase):
    def test_rasio_tidak_menyaring_sebelum_enrichment(self):
        pools = [
            _pool("PASS"),
            _pool("BOUNDARY"),
            _pool("RATIOFAIL"),
            _pool("APIERROR"),
            _pool("FVFAIL", fee=70.0, volatility=6.0),
        ]
        seen_distribution = []
        seen_market_enrichment = []

        def fake_distribution(rows, **_kwargs):
            seen_distribution.extend(row["pool_address"] for row in rows)
            ratios = {"PASS": _report(1.0), "BOUNDARY": _report(0.5),
                      "RATIOFAIL": _report(0.1),
                      "APIERROR": _report(0, ok=False, error="timeout"),
                      "FVFAIL": _report(0.75)}
            for row in rows:
                row["liquidity_distribution"] = ratios[row["pool_address"]]
            return rows

        def fake_market(rows, **_kwargs):
            seen_market_enrichment.extend(row["pool_address"] for row in rows)
            return rows

        with mock.patch.object(ms, "fetch_best_pools", return_value=pools), \
                mock.patch.object(ms, "attach_liquidity_distribution",
                                  side_effect=fake_distribution), \
                mock.patch("gmgn_liquidity.attach_total_liquidity",
                           side_effect=fake_market):
            result = ms.scan_best_lane(rugcheck=False, gmgn=True, bundler=False, tax=False)

        self.assertEqual(seen_distribution,
                         ["PASS", "BOUNDARY", "RATIOFAIL", "APIERROR",
                          "FVFAIL"])
        self.assertEqual(seen_market_enrichment,
                         ["PASS", "BOUNDARY", "RATIOFAIL", "APIERROR",
                          "FVFAIL"])
        self.assertEqual({row["pool_address"] for row in result["rows"]},
                         {"PASS", "BOUNDARY", "RATIOFAIL", "APIERROR", "FVFAIL"})
        self.assertEqual(result["hidden_rows"], [])
        self.assertEqual(result["failed_liquidity_ratio"], 0)
        self.assertEqual(result["liquidity_distribution_failed"], 1)
        self.assertFalse(result["liquidity_distribution_filter"])
        by_pool = {row["pool_address"]: row for row in result["rows"]}
        self.assertEqual(ms.liquidity_distribution_label(by_pool["FVFAIL"]),
                         "1:1.3")
        self.assertEqual(result["hidden_distribution_failed"], 0)


if __name__ == "__main__":
    unittest.main()
