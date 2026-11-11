# -*- coding: utf-8 -*-
"""Tes offline logika 🏆 Scan Best Pool (net deposit). Tanpa jaringan."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pool_flow as pf  # noqa: E402
import pool_flow_alert as alert  # noqa: E402

SOL = "So11111111111111111111111111111111111111112"
MINT = "9VZerdNL1x6EjetDqRnh5bYcdmk1y8sLAGs1ybzGpump"
POOL = "38hkfLZhhtjhn9t49LhCkconQ297ad5fnoZ3Mj7w5wEk"
POOL2 = "CPWA5ufjXEyC7DTd7g5fVUxJYZ81kxvbC8f9R9XFx1Y8"


def row(pool=POOL, *, tvl=60_000.0, fee_pct=2.0, avg_fee=6.0, net=1000.0,
        mint=MINT, symbol="X", name="X-SOL"):
    return {
        "pool_address": pool, "name": name,
        "token_x": {"address": mint, "symbol": symbol, "name": "apeonx"},
        "token_y": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"},
        "fee_pct": fee_pct, "tvl": tvl,
        "fee": avg_fee * pf.FLOW_LISTING_MINUTES,  # fee 24J; avg/menit = fee ÷ 1440
        "net_deposits": net,
    }


def windows(net=1000.0, pool=POOL):
    return {w: row(pool, net=net) for w in pf.FLOW_WINDOWS}


class FilterTest(unittest.TestCase):
    def test_fee_tier_di_bawah_1_persen_dilewati(self):
        ok, reason = pf.base_passes(row(fee_pct=0.99))
        self.assertFalse(ok)
        self.assertIn("fee tier", reason)

    def test_fee_tier_tepat_1_persen_lolos(self):
        self.assertTrue(pf.base_passes(row(fee_pct=1.0))[0])

    def test_fee_tier_2_persen_tetap_lolos(self):
        self.assertTrue(pf.base_passes(row(fee_pct=2.0))[0])

    def test_tvl_di_bawah_50k_dilewati(self):
        ok, reason = pf.base_passes(row(tvl=49_999.0))
        self.assertFalse(ok)
        self.assertIn("TVL", reason)

    def test_avg_fee_di_bawah_5_dilewati(self):
        ok, reason = pf.base_passes(row(avg_fee=4.99))
        self.assertFalse(ok)
        self.assertIn("fee/menit", reason)

    def test_evaluasi_lolos_bila_semua_net_positif(self):
        result = pf.evaluate_pool(row(), windows(net=500.0))
        self.assertTrue(result["passes"])
        self.assertEqual(result["reason"], "")
        self.assertEqual(result["nets"]["12h"], 500.0)

    def test_satu_window_negatif_gugurkan(self):
        nets = windows(net=500.0)
        nets["4h"] = row(net=-1.0)
        result = pf.evaluate_pool(row(), nets)
        self.assertFalse(result["passes"])
        self.assertIn("4H", result["reason"])

    def test_net_nol_bukan_positif(self):
        nets = windows(net=0.0)
        self.assertFalse(pf.evaluate_pool(row(), nets)["passes"])

    def test_window_hilang_tidak_terukur(self):
        nets = windows(net=500.0)
        nets["12h"] = None
        result = pf.evaluate_pool(row(), nets)
        self.assertFalse(result["passes"])
        self.assertIn("12H", result["reason"])

    def test_net_dihitung_dari_deposit_dikurangi_withdraw(self):
        r = {"total_deposits": 300.0, "total_withdraws": 120.0}
        self.assertEqual(pf.net_of(r), 180.0)
        self.assertIsNone(pf.net_of({"total_deposits": 1.0}))

    def test_candidates_dedupe_dan_filter(self):
        rows = [row(POOL), row(POOL), row(POOL2, tvl=10.0)]
        cands = pf.candidates_from_listing(rows)
        self.assertEqual(list(cands), [POOL])

    def test_avg_fee_per_menit_dari_fee_24_jam(self):
        self.assertAlmostEqual(pf.avg_fee_per_min({"fee": 1440.0}), 1.0)
        self.assertIsNone(pf.avg_fee_per_min({}))
        self.assertTrue(pf.base_passes(row(avg_fee=5.0))[0])

    def test_mint_non_sol_dan_nama_token(self):
        r = row()
        self.assertEqual(pf.mint_of_pool(r), MINT)
        self.assertEqual(pf.token_info(r, MINT), ("X", "apeonx"))


class ScanTest(unittest.TestCase):
    def test_scan_candidates_pakai_listing_dan_per_window(self):
        listing = ([row(POOL, net=900.0), row(POOL2, net=900.0, tvl=10.0)], [])

        def fake_window(mint, pool, window):
            return row(pool, net=800.0)

        with mock.patch.object(pf, "pool_row_for_window", side_effect=fake_window):
            result = pf.scan_candidates(listing=listing)
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(len(result["passing"]), 1)
        self.assertEqual(result["passing"][0]["pool"], POOL)
        self.assertEqual(result["passing"][0]["nets"]["1h"], 800.0)

    def test_scan_window_gagal_dianggap_tidak_terukur(self):
        listing = ([row(POOL)], [])

        def boom(mint, pool, window):
            raise OSError("timeout")

        with mock.patch.object(pf, "pool_row_for_window", side_effect=boom):
            result = pf.scan_candidates(listing=listing)
        self.assertEqual(result["passing"], [])
        self.assertIn("tidak terukur", result["results"][0]["reason"])


class StateTest(unittest.TestCase):
    def test_watchlist_tambah_hapus_tanpa_duplikat(self):
        state = pf.empty_state()
        self.assertTrue(pf.watch_add(state, pool=POOL, mint=MINT, symbol="X", name="n"))
        self.assertFalse(pf.watch_add(state, pool=POOL, mint=MINT, symbol="X", name="n"))
        self.assertTrue(pf.watch_remove(state, POOL))
        self.assertEqual(state["watchlist"], [])

    def test_riwayat_dipangkas(self):
        state = pf.empty_state()
        for _ in range(pf.FLOW_HISTORY_CAP + 5):
            pf.record_snapshot(state, POOL, {"1h": 1.0})
        self.assertEqual(len(state["history"][POOL]), pf.FLOW_HISTORY_CAP)

    def test_simpan_dan_muat_ulang(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            state = pf.empty_state()
            pf.watch_add(state, pool=POOL, mint=MINT, symbol="X", name="n")
            pf.save_state(state, path)
            again = pf.load_state(path)
            self.assertEqual(again["watchlist"][0]["pool"], POOL)
            self.assertEqual(pf.load_state(Path(tmp) / "tidak_ada.json")["watchlist"], [])
            json.loads(path.read_text(encoding="utf-8"))


class BestAlertTest(unittest.TestCase):
    def _passing(self, *pools):
        return [pf.evaluate_pool(row(p), windows(net=500.0, pool=p)) for p in pools]

    def test_nomor_alert_naik_dan_pool_berulang_diberi_tanda(self):
        state = pf.empty_state()
        first = pf.apply_best_alert(state, self._passing(POOL))
        self.assertIn("alert #1", first)
        self.assertIn("🆕", first)
        second = pf.apply_best_alert(state, self._passing(POOL, POOL2))
        self.assertIn("alert #2", second)
        self.assertIn("sudah pernah · alert #1", second)
        self.assertEqual(state["best_alert"]["next_no"], 3)
        self.assertEqual(len(state["alerts"]), 2)

    def test_tanpa_pool_lolos_tidak_ada_alert(self):
        state = pf.empty_state()
        self.assertIsNone(pf.apply_best_alert(state, []))
        self.assertEqual(state["best_alert"]["next_no"], 1)


class WatchAlertTest(unittest.TestCase):
    def _check(self, h1, h4):
        return {"pool": POOL, "symbol": "X", "nets": {"1h": h1, "4h": h4}}

    def test_alert_hanya_saat_berubah_jadi_negatif(self):
        state = pf.empty_state()
        self.assertEqual(pf.watch_transition_alerts(state, [self._check(10.0, 10.0)]), [])
        msgs = pf.watch_transition_alerts(state, [self._check(-5.0, 1.0)])
        self.assertEqual(len(msgs), 1)
        self.assertIn("H1 + H4", msgs[0])
        # masih negatif: tidak berulang
        self.assertEqual(pf.watch_transition_alerts(state, [self._check(-6.0, 1.0)]), [])
        # kembali positif, lalu negatif lagi: alert lagi
        pf.watch_transition_alerts(state, [self._check(10.0, 10.0)])
        self.assertEqual(len(pf.watch_transition_alerts(state, [self._check(-1.0, 0.0)])), 1)

    def test_net_tidak_terukur_dilewati(self):
        state = pf.empty_state()
        self.assertEqual(pf.watch_transition_alerts(state, [self._check(None, -5.0)]), [])


class AlertScriptTest(unittest.TestCase):
    def test_mode_best_menulis_state_dan_menandai_perubahan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool_flow_state.json"
            fake = {"scanned_at": "2026-11-10T00:00:00Z", "listing_rows": 1,
                    "listing_errors": 0, "candidates": 1, "results": [],
                    "passing": [pf.evaluate_pool(row(POOL), windows(500.0))]}
            sent = []
            with mock.patch.object(pf, "scan_candidates", return_value=fake), \
                    mock.patch.object(pf, "send_telegram", side_effect=lambda t: (sent.append(t), (True, ""))[1]), \
                    mock.patch.object(pf, "STATE_PATH", path):
                code = alert.main(["--mode", "best", "--state", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(len(sent), 1)
            self.assertIn("alert #1", sent[0])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["best_alert"]["next_no"], 2)

    def test_mode_watch_kirim_alert_saat_negatif_sekali(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool_flow_state.json"
            state = pf.empty_state()
            pf.watch_add(state, pool=POOL, mint=MINT, symbol="X", name="n")
            pf.save_state(state, path)

            def fake_row(mint, pool, window):
                # H1 -10 + H4 +5 = -5 → negatif
                return row(pool, net=-10.0 if window == "1h" else 5.0)

            sent = []
            with mock.patch.object(alert.pf, "pool_row_for_window", side_effect=fake_row), \
                    mock.patch.object(pf, "send_telegram",
                                      side_effect=lambda t: (sent.append(t), (True, ""))[1]):
                alert.main(["--mode", "watch", "--state", str(path)])
                self.assertEqual(len(sent), 1)
                self.assertIn("H1 + H4", sent[0])
                # run kedua: masih negatif, tidak boleh kirim lagi
                alert.main(["--mode", "watch", "--state", str(path)])
            self.assertEqual(len(sent), 1)


class ManualWatchTest(unittest.TestCase):
    def test_valid_mint_menerima_ca_dan_menolak_selain_itu(self):
        self.assertEqual(pf.valid_mint("  " + MINT + " "), MINT)
        for bad in ("", "abc", "0" * 40, MINT[:-1] + "O", "https://x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    pf.valid_mint(bad)

    def test_find_pools_hanya_mint_itu_urut_tvl(self):
        other = "Dz2wMTCsWKRFLzyaisX97HAqzJDyyPqfETvKQHFJaA8D"
        rows = [row(POOL, tvl=60_000.0), row(POOL2, tvl=90_000.0),
                row("POOL3xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", tvl=500.0, mint=other)]
        with mock.patch.object(pf, "fetch_mint_window", return_value=rows):
            found = pf.find_pools_for_mint(MINT)
        self.assertEqual([p["pool"] for p in found], [POOL2, POOL])
        self.assertEqual(found[0]["symbol"], "X")
        self.assertEqual(found[0]["tvl"], 90_000.0)


class AlertLinksTest(unittest.TestCase):
    def test_alert_best_memuat_ca_dan_empat_link(self):
        passing = [pf.evaluate_pool(row(POOL), windows(500.0))]
        text = pf.best_alert_text(1, passing, {})
        self.assertIn(f"<code>{MINT}</code>", text)
        self.assertIn("https://gmgn.ai/sol/token/" + MINT, text)
        self.assertIn("https://dexscreener.com/solana/" + MINT, text)
        self.assertIn("https://app.meteora.ag/dlmm/" + POOL, text)
        self.assertIn("https://www.hawkfi.ag/meteora/" + POOL, text)

    def test_alert_watch_memuat_ca_dan_link(self):
        state = pf.empty_state()
        checks = [{"pool": POOL, "mint": MINT, "symbol": "X",
                   "nets": {"1h": -10.0, "4h": 1.0}}]
        (msg,) = pf.watch_transition_alerts(state, checks)
        self.assertIn(f"<code>{MINT}</code>", msg)
        self.assertIn("https://gmgn.ai/sol/token/" + MINT, msg)
        self.assertIn("https://www.hawkfi.ag/meteora/" + POOL, msg)

    def test_pesan_panjang_dipecah_dan_semua_terkirim(self):
        text = "\n".join(["baris " + "x" * 120] * 80)  # > 4096 karakter
        parts = pf.split_for_telegram(text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= pf.TELEGRAM_CHUNK for p in parts))
        self.assertEqual("\n".join(parts), text)
        sent = []
        with mock.patch.object(pf, "_send_telegram_once",
                               side_effect=lambda t: (sent.append(t), (True, ""))[1]):
            ok, _ = pf.send_telegram(text)
        self.assertTrue(ok)
        self.assertEqual(len(sent), len(parts))

    def test_kegagalan_satu_bagian_menghentikan_dan_melaporkan(self):
        with mock.patch.object(pf, "_send_telegram_once", return_value=(False, "HTTP 500")):
            self.assertEqual(pf.send_telegram("halo"), (False, "HTTP 500"))


class TelegramFormatTest(unittest.TestCase):
    def test_payload_memakai_parse_mode_html(self):
        import json as _json
        captured = {}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(request, timeout=None):
            captured["body"] = _json.loads(request.data.decode("utf-8"))
            return _Resp()

        env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=fake_open):
            ok, _ = pf.send_telegram("<b>halo</b>")
        self.assertTrue(ok)
        self.assertEqual(captured["body"]["parse_mode"], "HTML")

    def test_nama_token_dengan_simbol_html_di_escape(self):
        passing = [pf.evaluate_pool(row(POOL, symbol="A<B>&C"), windows(500.0))]
        text = pf.best_alert_text(1, passing, {})
        self.assertIn("A&lt;B&gt;&amp;C", text)
        self.assertNotIn("A<B>", text)


class SendTelegramTest(unittest.TestCase):
    def test_tanpa_kredensial_tidak_mengirim(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            ok, reason = pf.send_telegram("halo")
        self.assertFalse(ok)
        self.assertIn("belum dipasang", reason)


if __name__ == "__main__":
    unittest.main()
