"""AppTest: card **Chart LP** (watchlist Meteora terpisah) di halaman utama.

Menutup perilaku yang diminta user:
- token ``source=meteora`` tampil di card paling atas, bukan di watchlist biasa;
- badge **HATI-HATI** (≥ 0,5% MC) dan **BAHAYA** (≥ 1% MC);
- grafik perubahan dust holder ikut ter-render;
- tambah manual bisa diarahkan ke Chart LP (radio) atau lewat form di card;
- tombol 🌊 memindahkan token watchlist biasa ke Chart LP.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import holder_history as hh

APP = str(Path(__file__).resolve().parent.parent / "app.py")

LP_MINT = "LpMint11111111111111111111111111111111111"
LP_SAFE = "LpSafe22222222222222222222222222222222222"
# base58 valid (tanpa 0/O/I/l) supaya lolos validasi CA di UI
HOLDER_MINT = "Watch11111111111111111111111111111111111"
BUCKET = hh.INTERVAL_SEC
LP_TAB = "🌊 Chart LP (Meteora)"
HOLDER_TAB = "📋 Watchlist Holder"


def _point(index: int, pct: float, count: int) -> dict:
    return {"ts": (index + 1) * BUCKET, "price": 0.01, "mc": 100_000.0,
            "dust_count": count, "dust_pct_mc": pct,
            "dust_value_usd": count * 5.0, "real_count": 40,
            "real_pct_mc": 20.0, "mid_count": 6, "mid_pct_mc": 4.0,
            "cohort_token_pct": 90.0, "cohort_cut50_pct": 10.0,
            "cohort_n": 6, "holder_count": count + 40,
            "buckets": {">$0-$10": count}}


def _watchlist():
    return {
        LP_MINT: {"symbol": "LPRISK", "source": "meteora",
                  "added": "2026-09-03"},
        LP_SAFE: {"symbol": "LPSAFE", "source": "meteora",
                  "added": "2026-09-03"},
        HOLDER_MINT: {"symbol": "HOLDT", "source": "manual",
                      "added": "2026-09-02"},
    }


def _status():
    return {
        "updated_at": 2 * BUCKET,
        "tokens": {
            LP_MINT: {"symbol": "LPRISK", "marketcap": 90_000.0,
                      "price": 0.01, "analyzed_at": 2 * BUCKET,
                      "holders": {"dust_count": 120, "dust_pct_mc": 1.35,
                                  "real_count": 40, "total_fetched": 160},
                      "history": [_point(0, 0.62, 90), _point(1, 1.35, 120)]},
            LP_SAFE: {"symbol": "LPSAFE", "marketcap": 300_000.0,
                      "price": 0.02, "analyzed_at": 2 * BUCKET,
                      "holders": {"dust_count": 70, "dust_pct_mc": 0.61,
                                  "real_count": 90, "total_fetched": 160},
                      "history": [_point(0, 0.30, 50), _point(1, 0.61, 70)]},
            HOLDER_MINT: {"symbol": "HOLDT", "marketcap": 500_000.0,
                          "price": 0.05, "analyzed_at": 2 * BUCKET,
                          "holders": {"dust_count": 12, "dust_pct_mc": 0.20,
                                      "real_count": 80,
                                      "total_fetched": 92},
                          "history": [_point(0, 0.10, 9),
                                      _point(1, 0.20, 12)]},
        },
    }


def _store():
    return {"updated_at": 2 * BUCKET,
            "tokens": {mint: {"symbol": slot["symbol"], "cohort": {},
                              "points": slot.get("history") or []}
                       for mint, slot in _status()["tokens"].items()}}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class ChartLpCardTest(unittest.TestCase):
    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: _watchlist()),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: _status()),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: _store()),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=60).run()

    def _body(self, app):
        return "\n".join(node.value for node in app.markdown)

    def _button(self, app, key):
        found = [button for button in app.button if button.key == key]
        self.assertTrue(found, f"tombol {key} tidak ditemukan")
        return found[0]

    def test_card_renders_meteora_tokens_with_dust_levels(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = self._body(app)
        self.assertIn("Chart LP — Watchlist Meteora", body)
        self.assertIn("HATI-HATI", body)     # LPSAFE 0,61% MC
        self.assertIn("BAHAYA", body)        # LPRISK 1,35% MC
        self.assertIn("$LPRISK", body)
        self.assertIn("$LPSAFE", body)
        # token non-meteora tidak masuk card LP
        self.assertNotIn(f"lp-move-{HOLDER_MINT}",
                         " ".join(b.key or "" for b in app.button))

    def test_dust_chart_is_rendered(self):
        app = self._app()
        # overlay semua token LP + grafik per token (di dalam expander)
        self.assertGreaterEqual(len(app.get("image")), 2)
        captions = "\n".join(node.value for node in app.caption)
        self.assertIn("Garis = dust % marketcap", captions)
        self.assertIn(f"ambang HATI-HATI {hh.DUST_CAUTION_PCT:g}% / BAHAYA "
                      f"{hh.DUST_DANGER_PCT:g}%", captions)

    def test_lp_rows_are_separate_from_holder_watchlist(self):
        app = self._app()
        keys = [button.key or "" for button in app.button]
        self.assertIn(f"lp-move-{LP_MINT}", keys)
        self.assertIn(f"to-lp-{HOLDER_MINT}", keys)
        # token LP tidak punya tombol baris watchlist biasa
        self.assertNotIn(f"to-lp-{LP_MINT}", keys)
        self.assertNotIn(f"remove-{LP_MINT}", keys)

    def test_move_button_sends_token_to_lp_card(self):
        app = self._app()
        with mock.patch("watchlist.set_watchlist_source",
                        return_value=True) as move:
            self._button(app, f"to-lp-{HOLDER_MINT}").click().run()
        move.assert_called_once_with(HOLDER_MINT, "meteora")

    def test_move_back_button_returns_token_to_holder_watchlist(self):
        app = self._app()
        with mock.patch("watchlist.set_watchlist_source",
                        return_value=True) as move:
            self._button(app, f"lp-move-{LP_MINT}").click().run()
        move.assert_called_once_with(LP_MINT, "manual")

    def test_manual_add_can_target_the_lp_card(self):
        app = self._app()
        radios = [node for node in app.radio if node.label == "Masuk ke card"]
        self.assertTrue(radios, "radio pilihan card tidak ditemukan")
        self.assertEqual(list(radios[0].options), [HOLDER_TAB, LP_TAB])

        radios[0].set_value(LP_TAB)
        inputs = [node for node in app.text_input
                  if node.key == "add-token-input"]
        self.assertTrue(inputs)
        inputs[0].set_value(LP_MINT[:32])
        submit = [button for button in app.button
                  if "Tambah ke watchlist" in (button.label or "")]
        self.assertTrue(submit)
        with mock.patch("watchlist.add_to_watchlist",
                        return_value=True) as add:
            submit[0].click().run()
        self.assertEqual(add.call_args.kwargs["source"], "meteora")

    def test_manual_add_defaults_to_holder_watchlist(self):
        app = self._app()
        inputs = [node for node in app.text_input
                  if node.key == "add-token-input"]
        inputs[0].set_value(HOLDER_MINT[:32])
        submit = [button for button in app.button
                  if "Tambah ke watchlist" in (button.label or "")][0]
        with mock.patch("watchlist.add_to_watchlist",
                        return_value=True) as add:
            submit.click().run()
        self.assertEqual(add.call_args.kwargs["source"], "manual")

    def test_lp_card_form_adds_with_meteora_source(self):
        app = self._app()
        inputs = [node for node in app.text_input
                  if node.key == "lp-ca-input"]
        self.assertTrue(inputs, "form CA di card LP tidak ditemukan")
        inputs[0].set_value(LP_MINT[:32])
        submit = [button for button in app.button
                  if "Tambah ke Chart LP" in (button.label or "")]
        self.assertTrue(submit)
        with mock.patch("watchlist.add_to_watchlist",
                        return_value=True) as add:
            submit[0].click().run()
        self.assertEqual(add.call_args.kwargs["source"], "meteora")

    def test_invalid_ca_is_rejected_without_adding(self):
        app = self._app()
        inputs = [node for node in app.text_input
                  if node.key == "lp-ca-input"]
        inputs[0].set_value("bukan-address")
        submit = [button for button in app.button
                  if "Tambah ke Chart LP" in (button.label or "")][0]
        with mock.patch("watchlist.add_to_watchlist") as add:
            result = submit.click().run()
        add.assert_not_called()
        self.assertTrue(any("Format CA tidak valid" in node.value
                            for node in result.warning))


@unittest.skipIf(AppTest is None, "streamlit not installed")
class EmptyChartLpCardTest(unittest.TestCase):
    def test_empty_card_shows_hint(self):
        patches = (
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value={"tokens": {}}),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60).run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("Chart LP — Watchlist Meteora", body)
        self.assertTrue(any("Chart LP masih kosong" in node.value
                            for node in app.info))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
