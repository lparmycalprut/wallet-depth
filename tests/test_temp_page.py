"""The three parked sections live on /temp, not on the active LP dashboard."""
import copy
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from holder_history import FULL_SCAN_MAX_WALLETS
from links import page_url_path
import page_router

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
TEMP = "pages/8_temp.py"
SOL = "So11111111111111111111111111111111111111112"
LP = "LpMint111111111111111111111111111111111111"
RH_LP = "0x" + "a" * 40
RH_REG = "0x" + "b" * 40


class TempPageTest(unittest.TestCase):
    def setUp(self):
        self.watch = {SOL: {"symbol": "REGSOL", "source": "manual"},
                      LP: {"symbol": "LPSOL", "source": "meteora"}}
        self.rh_watch = {RH_LP: {"symbol": "RHLP", "source": "lp"},
                         RH_REG: {"symbol": "RHREG", "source": "regular"}}
        self.status = {"updated_at": 1000, "tokens": {}}
        self.history = {"updated_at": 1000, "tokens": {}}
        patches = [
            mock.patch("watchlist.load_watchlist", side_effect=lambda **kw: self.watch),
            mock.patch("holder_status.load_holder_status", return_value=self.status),
            mock.patch("holder_history.load_durable_holder_history", return_value=self.history),
            mock.patch("robinhood_watchlist.load_watchlist", side_effect=lambda **kw: self.rh_watch),
            mock.patch("robinhood_watchlist.load_status", return_value=self.status),
            mock.patch("robinhood_watchlist.load_history", return_value=self.history),
            mock.patch("alert_settings.regular_telegram_enabled", return_value=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _app(self, *, temp=False):
        app = AppTest.from_file(APP, default_timeout=30)
        if temp:
            app.switch_page(TEMP)
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app

    @staticmethod
    def _body(app):
        return "\n".join(node.value for node in app.markdown)

    @staticmethod
    def _click(app, label):
        return next(b for b in app.button if b.label == label).click().run()

    def test_main_has_only_active_cards_and_scans(self):
        with mock.patch("alert_settings.regular_telegram_enabled") as alerts, \
                mock.patch("trending_ui.render_trending") as discovery:
            app = self._app()
        body = self._body(app)
        headings = [node.value for node in app.subheader]
        self.assertIn("Chart LP — Watchlist Meteora", body)
        self.assertIn("Watchlist Robinhood LP — Holder Dust", body)
        self.assertIn("🛰 Scan Holder Khusus — Helius / Robinhood", headings)
        self.assertNotIn("Watchlist Robinhood — Holder Dust</span>", body)
        self.assertNotIn("📋 Watchlist — Analisa Holder (Dust)", headings)
        self.assertNotIn("🔍 Temukan Token", headings)
        self.assertNotIn("$RHREG", body)
        self.assertNotIn("$REGSOL", body)
        self.assertIn("temp", [node.proto.label for node in app.get("page_link")])
        alerts.assert_not_called()
        discovery.assert_not_called()

    def test_temp_has_all_three_sections_but_not_lp_or_dedicated_scan(self):
        app = self._app(temp=True)
        body = self._body(app)
        headings = [node.value for node in app.subheader]
        self.assertEqual(app.title[0].value, "temp")
        self.assertIn("Watchlist Robinhood — Holder Dust</span>", body)
        self.assertIn("📋 Watchlist — Analisa Holder (Dust)", headings)
        self.assertIn("🔍 Temukan Token", headings)
        self.assertNotIn("Watchlist Robinhood LP — Holder Dust</span>", body)
        self.assertNotIn("Chart LP — Watchlist Meteora", body)
        self.assertNotIn("🛰 Scan Holder Khusus — Helius / Robinhood", headings)
        self.assertIn("$RHREG", body)
        self.assertIn("$REGSOL", body)
        self.assertNotIn("$RHLP", body)
        self.assertNotIn("$LPSOL", body)
        self.assertIn("Kembali ke halaman utama",
                      [node.proto.label for node in app.get("page_link")])

    def test_navigation_preserves_watchlists_and_history_without_scans(self):
        before = copy.deepcopy((self.watch, self.rh_watch, self.status, self.history))
        with mock.patch("holder_analysis.analyze_token") as sol_scan, \
                mock.patch("robinhood_watchlist.scan_watchlist") as rh_scan, \
                mock.patch("holder_status.publish_holder_status") as publish:
            app = self._app().switch_page(TEMP).run()
            self.assertEqual(len(app.exception), 0)
            app.switch_page("app.py").run()
            self.assertEqual(len(app.exception), 0)
        sol_scan.assert_not_called()
        rh_scan.assert_not_called()
        publish.assert_not_called()
        self.assertEqual((self.watch, self.rh_watch, self.status, self.history), before)

    def test_temp_rh_scan_only_scans_regular_with_full_coverage(self):
        with mock.patch("robinhood_watchlist.scan_watchlist", return_value={}) as scan:
            app = self._click(self._app(temp=True),
                              "🔄 Scan holder watchlist Robinhood biasa")
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(set(scan.call_args.args[0]), {RH_REG})
        self.assertEqual(scan.call_args.kwargs["max_wallets"], FULL_SCAN_MAX_WALLETS)

    def test_temp_solana_scan_does_not_scan_active_lp(self):
        with mock.patch("holder_analysis.analyze_token", return_value=None) as scan:
            app = self._click(self._app(temp=True), "🔄 Scan holder watchlist")
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([c.args[0] for c in scan.call_args_list], [SOL])

    def test_main_rh_scan_does_not_scan_parked_regular_tokens(self):
        with mock.patch("robinhood_watchlist.scan_watchlist", return_value={}) as scan:
            self._click(self._app(), "🔄 Scan holder watchlist Robinhood LP")
        self.assertEqual(set(scan.call_args.args[0]), {RH_LP})

    def test_rh_add_on_temp_defaults_to_regular_even_after_visiting_main(self):
        app = self._app().switch_page(TEMP).run()
        radio = next(r for r in app.radio if r.key == "rh-add-target")
        self.assertIn("Robinhood biasa", radio.value)
        app.text_input(key="rh-ca-input").set_value(RH_REG)
        with mock.patch("robinhood_watchlist.add_to_robinhood_watchlist",
                        return_value=True) as add:
            self._click(app, "🦅 Tambah ke Watchlist Robinhood")
        self.assertEqual(add.call_args.kwargs["source"], "regular")
        self.assertTrue(add.call_args.kwargs["background"])

    def test_regular_token_can_move_back_to_main_lp(self):
        def move(ca, source, **kw):
            self.rh_watch[ca]["source"] = source
            return True

        with mock.patch("robinhood_watchlist.set_robinhood_watchlist_source",
                        side_effect=move) as moved:
            app = self._app(temp=True)
            app.button(key=f"rhreg-move-{RH_REG}").click().run()
            moved.assert_called_once_with(RH_REG, "lp", background=True)
            self.assertNotIn("$RHREG", self._body(app))
            app.switch_page("app.py").run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("$RHREG", self._body(app))

    def test_temp_is_a_real_page_slug(self):
        self.assertEqual(page_url_path(TEMP), "temp")
        self.assertEqual(page_router.resolve({"page": "temp"})["page"], TEMP)
