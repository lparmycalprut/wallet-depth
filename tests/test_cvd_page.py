"""Streamlit AppTest coverage for the CVD/flow page (tanpa sinyal).

Halaman ini hanya menampilkan agregasi harian;
tes memastikan fetch manual memakai ``lookback_days`` dan data harian
merender tabel tanpa menyentuh modul sinyal.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency — the page itself needs it at runtime
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "4_📊_CVD.py")
MINT = "Mint123"
META = {"symbol": "TST"}


def _fake_result(mint=MINT, *, ok=True, error=None):
    return {
        "mint": mint, "symbol": "TST", "ok": ok, "error": error,
        "source": "gmgn" if ok else None, "fallback": False,
        "trades_count": 3 if ok else 0, "rows_created": 0,
        "rows_updated": 0, "duration_ms": 1, "requested_days": 7,
        "start_date": "2026-08-08", "end_date": "2026-08-14",
        "log": [{"ts_market": "2026-08-15 00:00:01", "stage": "success",
                 "message": "fetch manual berhasil", "ok": True}],
    }


def _patches(daily_rows):
    """Patch dependencies supaya halaman berjalan tanpa jaringan."""
    return (
        mock.patch("watchlist.load_watchlist", return_value={MINT: META}),
        mock.patch("holder_status.load_holder_status",
                   return_value={"updated_at": None, "tokens": {}}),
        # Backup durable store: tes tidak boleh menyentuh jaringan.
        mock.patch("holder_history.pull_holder_history", return_value=None),
        mock.patch("daily_store.load_daily_effort",
                   return_value=daily_rows or []),
        mock.patch("core.get_helius_keys", return_value=["test-key"]),
    )


@unittest.skipUnless(AppTest is not None, "streamlit is not installed")
class CvdPageNoSignalTest(unittest.TestCase):
    def test_first_load_does_not_fetch(self):
        calls = []

        def fake(mint, meta=None, **kwargs):
            calls.append(kwargs)
            return _fake_result(mint=mint)

        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("holder_status.load_holder_status",
                        return_value={"updated_at": None, "tokens": {}}), \
             mock.patch("daily_store.load_daily_effort", return_value=[]), \
             mock.patch("scripts.update_cvd.refresh_single_token",
                        side_effect=fake), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(len(calls), 0)

    @staticmethod
    def _button(app, label):
        return [button for button in app.button
                if label in (button.label or "")][0]

    def test_manual_panel_button_uses_lookback(self):
        calls = []

        def fake(mint, meta=None, **kwargs):
            calls.append(kwargs)
            return _fake_result(mint=mint)

        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("holder_status.load_holder_status",
                        return_value={"updated_at": None, "tokens": {}}), \
             mock.patch("daily_store.load_daily_effort", return_value=[]), \
             mock.patch("scripts.update_cvd.refresh_single_token",
                        side_effect=fake), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            manual = self._button(at, "Fetch")
            manual.click().run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("lookback_days", calls[0])
            self.assertNotIn("start_date", calls[0])

    def test_manual_ca_opens_token_not_in_watchlist(self):
        ca = "So11111111111111111111111111111111111111112"
        with mock.patch("watchlist.load_watchlist", return_value={}), \
             mock.patch("holder_status.load_holder_status",
                        return_value={"updated_at": None, "tokens": {}}), \
             mock.patch("daily_store.load_daily_effort", return_value=[]), \
             mock.patch("scripts.update_cvd.refresh_single_token"), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            at.text_input[0].set_value(ca)
            self._button(at, "Cek CVD").click().run()
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(at.session_state["effort_mint"], ca)
            body = "\n".join(m.value for m in at.markdown)
            self.assertIn(ca, body)

    def test_manual_ca_invalid_format_stays_unselected(self):
        invalid = "not-a-valid-solana-mint"
        with mock.patch("watchlist.load_watchlist", return_value={}), \
             mock.patch("holder_status.load_holder_status",
                        return_value={"updated_at": None, "tokens": {}}), \
             mock.patch("daily_store.load_daily_effort", return_value=[]), \
             mock.patch("scripts.update_cvd.refresh_single_token"), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            at.text_input[0].set_value(invalid)
            self._button(at, "Cek CVD").click().run()
            self.assertEqual(len(at.exception), 0)
            self.assertNotIn("effort_mint", at.session_state)
            warnings_text = "\n".join(w.value for w in at.warning)
            self.assertIn("base58", warnings_text)

    def test_data_present_renders_table_without_signals(self):
        rows = [{"mint": MINT, "date": "2026-08-14", "open": 100.0,
                 "close": 110.0, "price_chg_pct": 10.0, "cvd_delta": 5.0,
                 "direction": "up", "volume_usd": 1234.0}]
        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("holder_status.load_holder_status",
                        return_value={"updated_at": None, "tokens": {}}), \
             mock.patch("daily_store.load_daily_effort", return_value=rows), \
             mock.patch("scripts.update_cvd.refresh_single_token"), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            self.assertEqual(len(at.exception), 0)
            self.assertGreater(len(at.dataframe), 0)
            body = "\n".join(m.value for m in at.markdown)
            self.assertNotIn("Sinyal", body)
            self.assertNotIn("Telegram", body)

    def test_page_has_no_holder_analytic_banner(self):
        token = {"symbol": "TST",
                 "holders": {"real_count": 30, "dust_count": 270,
                             "dust_pct_mc": 0.5}}
        with mock.patch("watchlist.load_watchlist",
                        return_value={MINT: META}), \
             mock.patch("daily_store.load_daily_effort", return_value=[]), \
             mock.patch("scripts.update_cvd.refresh_single_token"), \
             mock.patch("core.get_helius_keys", return_value=["test-key"]):
            at = AppTest.from_file(PAGE)
            at.run()
            self.assertEqual(len(at.exception), 0)
            body = "\n".join(s.value for s in at.subheader)
            self.assertNotIn("Holder Analytic", body)
            joined = "\n".join(m.value for m in at.metric)
            self.assertNotIn("SILENT ACCUMULATION", joined)
            _ = token  # snapshot holder tidak lagi dirender di halaman CVD


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
