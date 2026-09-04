"""AppTest halaman **🔎 Deteksi Akumulasi** (``pages/6_🔎_Deteksi_Akumulasi.py``).

Yang dijaga tes ini:

- halaman hanya mengambil token dari ``watchlist.load_watchlist`` (bukan
  listing Meteora/trending);
- semua fetch lewat fetcher yang sudah ada (GMGN ``cvd``, DexScreener/
  GeckoTerminal ``core``) dan **tidak menyentuh Helius sama sekali**;
- GMGN dibatasi ``max_pages`` + window ``stop_ts``;
- 8 metrik dirender lengkap dengan penjelasan, dan hasil disimpan ke store
  snapshot terpisah (``accumulation_history.json`` di temp dir).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import accumulation as acc

PAGE = str(Path(__file__).resolve().parent.parent / "pages"
           / "6_🔎_Deteksi_Akumulasi.py")

# path store snapshot milik repo — harus tetap tidak tersentuh oleh tes
REPO_STORE = acc.ACCUMULATION_HISTORY_PATH

MINT = "AccMint11111111111111111111111111111111111"
MINT2 = "AccMint22222222222222222222222222222222222"
WALLET_A = "WalletA111111111111111111111111111111111"
WALLET_B = "WalletB222222222222222222222222222222222"
HOUR = 3600
DAY = 86_400
NOW = 1_757_000_000


def _watchlist():
    return {MINT: {"symbol": "ACC", "source": "manual", "added": "2026-09-01"},
            MINT2: {"symbol": "ACC2", "source": "manual",
                    "added": "2026-09-02"}}


def _swaps():
    """6 wallet buyer (5 DCA + 1 seller) — cukup untuk metrik 2/3/7/8."""
    rows = []
    for index, wallet in enumerate((WALLET_A, WALLET_B, WALLET_A, WALLET_B,
                                    WALLET_A, WALLET_B)):
        rows.append(("buy", 0.3, NOW - (6 - index) * HOUR, wallet, None, 30.0,
                     ["fresh_wallet"]))
    rows.append(("sell", 0.2, NOW - HOUR, WALLET_B, None, 20.0, []))
    return rows


def _market():
    return {"symbol": "ACC", "name": "Accumulation", "price_usd": 0.01,
            "marketcap": 250_000.0, "liquidity_usd": 40_000.0,
            "pair_addresses": ["PairAddress111111111111111111111111111111"],
            "volume": {"h24": 60_000.0, "h6": 12_000.0},
            "price_change": {"h24": 1.5}, "txns": {}}


def _hourly():
    base = (NOW // HOUR) * HOUR - 30 * HOUR
    rows = []
    for step in range(30):
        rows.append({"ts": base + step * HOUR, "open": 0.010, "high": 0.0102,
                     "low": 0.0098, "close": 0.0100,
                     "volume_usd": 2_000.0})
    return rows


@unittest.skipIf(AppTest is None, "streamlit not installed")
class DeteksiAkumulasiPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self.tmp.name,
                                       "accumulation_history.json")
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: _watchlist()),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: {"updated_at": NOW,
                                                  "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: {"tokens": {}}),
            mock.patch("holder_history.pull_holder_history", return_value=None),
            # store snapshot diarahkan ke temp dir (bukan file repo)
            mock.patch("accumulation.ACCUMULATION_HISTORY_PATH",
                       self.store_path),
            # fetcher yang sudah ada — semua dimock, tanpa jaringan
            mock.patch("cvd.fetch_gmgn_swaps",
                       return_value=(_swaps(), "sig", NOW, False)),
            mock.patch("cvd.get_gmgn_wallet_metadata",
                       return_value={WALLET_A: {"maker_tags": ["fresh_wallet"],
                                                "realized_profit": 0.0}}),
            mock.patch("cvd.get_gmgn_fetch_status",
                       return_value={"ok": True, "complete": True,
                                     "outcome": "ok"}),
            mock.patch("core.get_market", side_effect=lambda ca: _market()),
            mock.patch("core.get_hourly_candles",
                       side_effect=lambda *a, **kw: _hourly()),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        # Helius tidak boleh tersentuh sama sekali di halaman ini.
        self.helius = []
        for target in ("core.helius_rpc", "core.helius_api_get",
                       "core.helius_rpc_request"):
            patch = mock.patch(target)
            self.helius.append(patch.start())
            self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def _app(self):
        return AppTest.from_file(PAGE, default_timeout=60).run()

    def _body(self, app):
        return "\n".join(node.value for node in app.markdown)

    def test_page_renders_without_exceptions(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Deteksi Akumulasi", app.title[0].value)
        # belum ada hasil sebelum tombol dihitung
        self.assertTrue(any("Hitung akumulasi" in node.value
                            for node in app.info))

    def test_empty_watchlist_stops_the_page(self):
        with mock.patch("watchlist.load_watchlist",
                        side_effect=lambda **_kw: {}):
            app = self._app()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Watchlist kosong" in node.value
                            for node in app.info))

    def test_calculating_renders_the_eight_metrics(self):
        app = self._app()
        button = [node for node in app.button
                  if "Hitung akumulasi" in (node.label or "")][0]
        result = button.click().run()
        self.assertEqual(len(result.exception), 0)
        body = self._body(result)
        for name in acc.METRIC_NAMES.values():
            self.assertIn(name, body)
        self.assertIn("$ACC", body)
        self.assertIn("skor 0–100", body)
        self.assertIn("Heuristik", body)

    def test_gmgn_is_called_with_window_and_page_cap(self):
        import cvd
        app = self._app()
        [node for node in app.button
         if "Hitung akumulasi" in (node.label or "")][0].click().run()
        self.assertTrue(cvd.fetch_gmgn_swaps.called)
        for call in cvd.fetch_gmgn_swaps.call_args_list:
            self.assertIn(call.args[0], (MINT, MINT2))
            self.assertLessEqual(call.kwargs["max_pages"], 20)
            self.assertIsNotNone(call.kwargs["stop_ts"])
        # satu token = satu fetch, tidak ada duplikasi
        self.assertEqual(len(cvd.fetch_gmgn_swaps.call_args_list), 2)

    def test_helius_is_never_touched(self):
        app = self._app()
        [node for node in app.button
         if "Hitung akumulasi" in (node.label or "")][0].click().run()
        for patch in self.helius:
            patch.assert_not_called()

    def test_snapshot_store_is_written_outside_the_repo(self):
        app = self._app()
        [node for node in app.button
         if "Hitung akumulasi" in (node.label or "")][0].click().run()
        self.assertTrue(os.path.exists(self.store_path))
        store = acc.load_accumulation_history(self.store_path)
        self.assertIn(MINT, store["tokens"])
        self.assertTrue(store["tokens"][MINT]["points"])
        # store repo tidak boleh ikut tertulis oleh tes
        self.assertFalse(os.path.exists(REPO_STORE),
                         f"{REPO_STORE} seharusnya tidak dibuat oleh tes")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
