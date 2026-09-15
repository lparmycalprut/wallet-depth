# -*- coding: utf-8 -*-
"""Toggle alert Telegram per token — updated for Meteora metric alerts."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

try:
    from streamlit.testing.v1 import AppTest
except Exception:
    AppTest = None

import alert_settings
import watchlist as wl

APP = str(Path(__file__).resolve().parent.parent / "app.py")

LP_MINT = "LpMint11111111111111111111111111111111111"
LP_SAFE = "LpSafe22222222222222222222222222222222222"
SOL_MINT = "Watch11111111111111111111111111111111111"
# CA kedua untuk menguji store mute (format 0x di-casefold oleh
# ``alert_settings.mint_key``; Solana case-sensitive).
OTHER_CA = "0x" + "a" * 40
OTHER_CA2 = "0x" + "b" * 40
NOW = 1_770_000_000
BUCKET = 300


class SettingsMuteStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        patch = mock.patch.object(alert_settings, "SETTINGS_PATH", os.path.join(self.dir, "alert_settings.json"))
        patch.start()
        self.addCleanup(patch.stop)
        alert_settings.reset_cache()
        self.addCleanup(alert_settings.reset_cache)
        self.write = mock.patch.object(alert_settings, "_write_remote", return_value=True)
        self.remote = self.write.start()
        self.addCleanup(self.write.stop)

    def _payload(self):
        with open(alert_settings.SETTINGS_PATH, encoding="utf-8") as handle:
            return json.load(handle)

    def test_default_semua_token_on(self):
        self.assertEqual(alert_settings.muted_mints(), set())
        self.assertFalse(alert_settings.is_mint_muted(LP_MINT))
        self.assertEqual(alert_settings.mutes_for([LP_MINT, ""]), set())

    def test_mute_lalu_nyala_lagi(self):
        self.assertTrue(alert_settings.set_mint_alert_enabled(LP_MINT, False))
        self.assertTrue(alert_settings.is_mint_muted(LP_MINT))
        self.assertEqual(alert_settings.mutes_for([LP_MINT]), {LP_MINT})
        self.assertIn("muted_mints", self.remote.call_args.args[0])
        self.assertEqual(self.remote.call_args.args[0]["muted_mints"], [LP_MINT])
        self.assertIn("notif off", self.remote.call_args.args[1])
        self.assertTrue(alert_settings.set_mint_alert_enabled(LP_MINT, True))
        self.assertFalse(alert_settings.is_mint_muted(LP_MINT))
        self.assertEqual(self._payload()[alert_settings.KEY_MUTED_MINTS], [])

    def test_toggle_global_dan_mute_per_token_saling_menjaga(self):
        alert_settings.set_mint_alert_enabled(OTHER_CA, False)
        self.assertTrue(alert_settings.set_regular_telegram_enabled(False))
        self.assertEqual(alert_settings.muted_mints(), {OTHER_CA})
        self.assertFalse(alert_settings.regular_telegram_enabled(True))
        alert_settings.set_mint_alert_enabled(OTHER_CA, True)
        self.assertTrue(alert_settings.set_regular_telegram_enabled(True))
        payload = self._payload()
        self.assertEqual(payload[alert_settings.KEY_MUTED_MINTS], [])
        self.assertTrue(payload[alert_settings.KEY_REGULAR_TELEGRAM])

    def test_alamat_evm_tidak_beda_huruf_besar_kecil(self):
        upper = "0x" + "A" * 40
        self.assertTrue(alert_settings.set_mint_alert_enabled(upper, False))
        self.assertTrue(alert_settings.is_mint_muted(upper.lower()))
        self.assertTrue(alert_settings.is_mint_muted(upper))
        self.assertEqual(alert_settings.mutes_for([OTHER_CA]), {OTHER_CA})
        self.assertTrue(alert_settings.set_mint_alert_enabled("AbC1", False))
        self.assertFalse(alert_settings.is_mint_muted("abc1"))

    def test_forget_mint_alert_tanpa_mute_tidak_menulis(self):
        self.assertTrue(alert_settings.forget_mint_alert(LP_MINT))
        self.remote.assert_not_called()
        self.assertFalse(os.path.exists(alert_settings.SETTINGS_PATH))

    def test_forget_mint_alert_membuang_pilihan_off(self):
        alert_settings.set_mint_alert_enabled(LP_MINT, False)
        alert_settings.set_mint_alert_enabled(OTHER_CA, False)
        self.remote.reset_mock()
        self.assertTrue(alert_settings.forget_mint_alert(LP_MINT))
        self.assertFalse(alert_settings.is_mint_muted(LP_MINT))
        self.assertTrue(alert_settings.is_mint_muted(OTHER_CA))
        self.assertEqual(self.remote.call_args.args[0]["muted_mints"], [OTHER_CA])

    def test_daftar_stabil_dan_toleran_payload_lama(self):
        alert_settings.set_mint_alert_enabled(OTHER_CA, False)
        alert_settings.set_mint_alert_enabled(LP_MINT, False)
        self.assertEqual(self._payload()[alert_settings.KEY_MUTED_MINTS], sorted([LP_MINT, OTHER_CA]))
        with open(alert_settings.SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump({"muted_mints": [LP_MINT, "", None, LP_MINT], "telegram_regular_enabled": "off"}, handle)
        alert_settings.reset_cache()
        with mock.patch.object(alert_settings, "_read_remote", return_value=None):
            self.assertEqual(alert_settings.muted_mints(), {LP_MINT})
            self.assertFalse(alert_settings.regular_telegram_enabled(True))

    def test_push_gagal_tetap_tersimpan_lokal(self):
        self.remote.return_value = False
        self.assertFalse(alert_settings.set_mint_alert_enabled(LP_MINT, False))
        self.assertTrue(alert_settings.is_mint_muted(LP_MINT))
        with mock.patch.object(alert_settings, "_read_remote", return_value=None):
            alert_settings.reset_cache()
            self.assertEqual(alert_settings.muted_mints(), {LP_MINT})


class AddUlangSelaluOnTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.local = os.path.join(self.dir, "watchlist.json")
        self.pending = os.path.join(self.dir, "watchlist_pending.json")
        patches = [
            mock.patch.object(wl, "WATCHLIST_PATH", self.local),
            mock.patch.object(wl, "PENDING_PATH", self.pending),
            mock.patch.object(wl, "_github_pull", return_value=None),
            mock.patch.object(wl, "_github_push", return_value=True),
            mock.patch.object(wl, "request_immediate_scan", return_value=True),
            mock.patch.object(alert_settings, "SETTINGS_PATH", os.path.join(self.dir, "alert_settings.json")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.write = mock.patch.object(alert_settings, "_write_remote", return_value=True)
        self.remote = self.write.start()
        self.addCleanup(self.write.stop)
        wl._reset_cache()
        self.addCleanup(wl._reset_cache)
        alert_settings.reset_cache()
        self.addCleanup(alert_settings.reset_cache)

    def test_add_satu_token_membersihkan_mute(self):
        alert_settings.set_mint_alert_enabled(LP_MINT, False)
        self.assertTrue(wl.add_to_watchlist(LP_MINT, "RAYCAT"))
        self.assertFalse(alert_settings.is_mint_muted(LP_MINT))
        self.assertEqual(self.remote.call_args.args[0]["muted_mints"], [])

    def test_add_banyak_token_membersihkan_mute(self):
        alert_settings.set_mint_alert_enabled(LP_MINT, False)
        alert_settings.set_mint_alert_enabled(OTHER_CA, False)
        self.remote.reset_mock()
        result = wl.add_many_to_watchlist([{"ca": LP_MINT, "symbol": "RAYCAT"}, {"ca": OTHER_CA, "symbol": "CME"}], source="meteora")
        self.assertEqual(result.get("added"), 2)
        self.assertFalse(alert_settings.is_mint_muted(LP_MINT))
        self.assertFalse(alert_settings.is_mint_muted(OTHER_CA))

    def test_token_tanpa_mute_tidak_commit_apa_pun(self):
        self.assertTrue(wl.add_to_watchlist(LP_MINT, "RAYCAT"))
        self.remote.assert_not_called()


def _point(ts: int, pct: float, count: int) -> dict:
    return {"ts": ts, "dust_count": count, "dust_pct_mc": pct, "price": 0.01, "mc": 100_000.0, "real_count": 40, "mid_count": 5, "holder_count": count + 40}

def _status_lp() -> dict:
    return {"updated_at": NOW, "tokens": {LP_MINT: _status_token("RAYCAT", 0.55), LP_SAFE: _status_token("LPSAFE", 0.31)}}

def _status_token(symbol: str, pct: float) -> dict:
    return {"symbol": symbol, "price": 0.01, "marketcap": 100_000.0, "analyzed_at": NOW, "holders": {"dust_count": 70, "dust_pct_mc": pct, "real_count": 40, "total_fetched": 110}, "history": [_point(NOW - BUCKET, 0.30, 50), _point(NOW, pct, 70)]}

def _store_lp() -> dict:
    return {"updated_at": NOW, "tokens": {LP_MINT: _store_token("RAYCAT", 0.55), LP_SAFE: _store_token("LPSAFE", 0.31), SOL_MINT: {"symbol": "HOLDT", "cohort": {}, "points": [], "alert_state": _episode_marker()}}}

def _episode_marker(dust_pct: float = 0.07) -> dict:
    return {"early_dump": {"ts": NOW - BUCKET, "dust_pct_mc": dust_pct, "baseline_pct": dust_pct, "baseline_ts": NOW - 3600, "step": 0, "baseline_src": "history"}}

def _store_token(symbol: str, pct: float) -> dict:
    return {"symbol": symbol, "cohort": {}, "points": [_point(NOW - BUCKET, 0.30, 50), _point(NOW, pct, 70)], "alert_state": _episode_marker()}

def _analysis(symbol: str, pct: float, ts: int = NOW) -> dict:
    return {"symbol": symbol, "analyzed_at": ts, "holders": {"total_fetched": 500, "dust_pct_mc": pct, "wallet_snapshot": {"ts": ts, "dust_pct_mc": pct}}}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class AlertToggleUiTest(unittest.TestCase):
    def setUp(self):
        self.sent: list[dict] = []
        self.written: dict = {}
        self.store: dict = {}
        patches = [
            mock.patch("holder_history.pull_holder_history", return_value=None),
            mock.patch("holder_status.atomic_write_json", side_effect=self._write),
            mock.patch("holder_history.save_holder_history", side_effect=self._save),
            mock.patch("telegram_alerts.send_telegram_alert", side_effect=self._sender),
            mock.patch("watchlist.load_watchlist", side_effect=lambda **_kw: self.watchlist()),
            mock.patch("holder_status.load_holder_status", side_effect=lambda **_kw: _status_lp()),
            mock.patch("holder_history.load_holder_history", side_effect=lambda *_a, **_kw: _store_lp()),
            mock.patch("alert_settings.muted_mints", side_effect=lambda *a, **kw: set(self.muted)),
            mock.patch("alert_settings.set_mint_alert_enabled", side_effect=self._toggle),
        ]
        self.muted: set[str] = set()
        self.toggle_ok = True
        self.toggle_calls: list[tuple] = []
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def watchlist(self):
        return {LP_MINT: {"symbol": "RAYCAT", "source": "meteora", "added": "2026-01-05"}, LP_SAFE: {"symbol": "LPSAFE", "source": "meteora", "added": "2026-01-05"}, SOL_MINT: {"symbol": "HOLDT", "source": "manual", "added": "2026-01-05"}}

    def _write(self, path, payload, **_kw):
        self.written[str(path)] = payload
        return payload

    def _save(self, store, path=None):
        self.store = store
        return store

    def _sender(self, event):
        self.sent.append(event)
        return {"ok": True, "skipped": False}

    def _toggle(self, mint, enabled, **_kw):
        self.toggle_calls.append((mint, enabled))
        if self.toggle_ok:
            if enabled:
                self.muted.discard(mint)
            else:
                self.muted.add(mint)
        return self.toggle_ok

    def _app(self, *, page=APP):
        app = AppTest.from_file(APP, default_timeout=90)
        app.switch_page(page)
        app.run()
        self.assertEqual(len(app.exception), 0, app.exception)
        return app

    @staticmethod
    def _body(app):
        return "\n".join(node.value for node in app.markdown)

    @staticmethod
    def _info(app):
        return "\n".join(node.value for node in app.info)

    def _button(self, app, key):
        found = [b for b in app.button if (b.key or "") == key]
        self.assertTrue(found, f"tombol {key} tidak ada")
        return found[0]

    def _label_button(self, app, label):
        found = [b for b in app.button if (b.label or "") == label]
        self.assertTrue(found, f"tombol {label} tidak ada")
        return found[0]

    def test_baris_lp_punya_bell_on_dan_klik_mematikan(self):
        app = self._app(page=APP)
        button = self._button(app, f"lp-alert-{LP_MINT}")
        self.assertEqual(button.label, "🔔")
        self.assertIn("Matikan notif Telegram", button.help or "")
        button.click().run()
        self.assertEqual(self.toggle_calls, [(LP_MINT, False)])
        self.assertEqual(len(app.exception), 0)

    def test_baris_lp_muted_tampil_bell_off_rekap_dan_catatan(self):
        self.muted = {LP_MINT}
        app = self._app(page=APP)
        self.assertEqual(self._button(app, f"lp-alert-{LP_MINT}").label, "🔕")
        body = self._body(app)
        self.assertIn("🔕", body)
        self.assertIn("notif off", body)
        self.assertIn("🔕 1", body)
        self.assertIn("$RAYCAT", body)
        self.assertIn("0.550%", body)

    def test_bukan_global_hanya_token_yang_dimatikan(self):
        self.muted = {LP_MINT}
        app = self._app(page=APP)
        self.assertEqual(self._button(app, f"lp-alert-{LP_MINT}").label, "🔕")
        self.assertEqual(self._button(app, f"lp-alert-{LP_SAFE}").label, "🔔")
        body = self._body(app)
        self.assertIn("🔕 1", body)
        self.assertNotIn("🔕 2", body)
        self.assertEqual(body.count("notif off"), 1)

    def test_scan_hanya_melewati_token_yang_dimatikan(self):
        self.muted = {LP_MINT}
        app = self._app(page=APP)
        with ExitStack() as stack:
            stack.enter_context(mock.patch("holder_analysis.analyze_token", side_effect=lambda mint, *a, **kw: _analysis(str(mint)[:6], 0.11)))
            stack.enter_context(mock.patch("meteora_screener.fetch_watchlist_metric_snapshots", return_value={}))
            stack.enter_context(mock.patch("meteora_watchlist.apply_metric_snapshots", return_value={"watchlist": self.watchlist(), "metrics": {}, "events": [{"mint": LP_MINT}, {"mint": LP_SAFE}], "baseline_changed": []}))
            send_metric = stack.enter_context(mock.patch("meteora_watchlist.send_metric_alerts", side_effect=lambda events, mute_mints=None, **kw: [{"delivery": {"ok": True}, "mint": e["mint"]} for e in events if e["mint"] not in (mute_mints or set())]))
            stack.enter_context(mock.patch("watchlist.save_watchlist", return_value=True))
            stack.enter_context(mock.patch("holder_status.publish_holder_status", return_value={"updated_at": NOW}))
            app = self._button(app, "lp-scan-now").click().run()
        self.assertTrue(send_metric.called)
        mute_arg = send_metric.call_args.kwargs.get("mute_mints") or set()
        self.assertIn(LP_MINT, mute_arg)

    def test_klik_bell_off_menyalakan_lagi(self):
        self.muted = {LP_MINT}
        app = self._app(page=APP)
        self._button(app, f"lp-alert-{LP_MINT}").click().run()
        self.assertEqual(self.toggle_calls, [(LP_MINT, True)])

    def test_gagal_sinkron_github_diperingatkan(self):
        self.toggle_ok = False
        app = self._app(page=APP)
        self._button(app, f"lp-alert-{LP_MINT}").click().run()
        warnings = "\n".join(node.value for node in app.warning)
        self.assertIn("sinkronisasi ke GitHub gagal", warnings)

    def test_scan_lp_manual_menghormati_bell_off(self):
        self.muted = {LP_MINT}
        app = self._app(page=APP)
        with ExitStack() as stack:
            stack.enter_context(mock.patch("holder_analysis.analyze_token", return_value=_analysis("RAYCAT", 0.11)))
            stack.enter_context(mock.patch("meteora_screener.fetch_watchlist_metric_snapshots", return_value={}))
            stack.enter_context(mock.patch("meteora_watchlist.apply_metric_snapshots", return_value={"watchlist": self.watchlist(), "metrics": {LP_MINT: {}, LP_SAFE: {}}, "events": [{"mint": LP_MINT, "type": "metric"}, {"mint": LP_SAFE, "type": "metric"}], "baseline_changed": []}))
            send_metric = stack.enter_context(mock.patch("meteora_watchlist.send_metric_alerts", side_effect=lambda events, mute_mints=None, **kw: [{"delivery": {"ok": True}, "mint": e["mint"]} for e in events if e["mint"] not in (mute_mints or set())]))
            stack.enter_context(mock.patch("watchlist.save_watchlist", return_value=True))
            stack.enter_context(mock.patch("holder_status.publish_holder_status", return_value={"updated_at": NOW}))
            stack.enter_context(mock.patch("holder_history.ingest_many", return_value={"tokens": {}}))
            app = self._button(app, "lp-scan-now").click().run()
        self.assertEqual(len(app.exception), 0)
        mute_arg = send_metric.call_args.kwargs.get("mute_mints", set())
        self.assertIn(LP_MINT, mute_arg)

    def test_scan_lp_manual_tanpa_bell_off_tetap_kirim(self):
        app = self._app(page=APP)
        with ExitStack() as stack:
            stack.enter_context(mock.patch("holder_analysis.analyze_token", side_effect=lambda mint, *a, **kw: _analysis(str(mint)[:6], 0.11)))
            stack.enter_context(mock.patch("meteora_screener.fetch_watchlist_metric_snapshots", return_value={}))
            stack.enter_context(mock.patch("meteora_watchlist.apply_metric_snapshots", return_value={"watchlist": self.watchlist(), "metrics": {LP_MINT: {}, LP_SAFE: {}}, "events": [{"mint": LP_MINT}, {"mint": LP_SAFE}], "baseline_changed": []}))
            stack.enter_context(mock.patch("meteora_watchlist.send_metric_alerts", return_value=[{"delivery": {"ok": True}, "mint": LP_MINT}, {"delivery": {"ok": True}, "mint": LP_SAFE}]))
            stack.enter_context(mock.patch("watchlist.save_watchlist", return_value=True))
            stack.enter_context(mock.patch("holder_status.publish_holder_status", return_value={"updated_at": NOW}))
            stack.enter_context(mock.patch("holder_history.ingest_many", return_value={"tokens": {}}))
            app = self._button(app, "lp-scan-now").click().run()
        self.assertEqual(len(app.exception), 0)

class CronMuteWiringTest(unittest.TestCase):
    """Cron hanya punya lane Meteora sejak lane Robinhood dihapus (2026-09-15).

    Yang di-pin: token yang 🔕-nya dimatikan user tetap di-scan, tetapi
    ``mute_mints`` diteruskan ke pengiriman metric Telegram.
    """

    def _run(self, mute, *, lp):
        import scripts.scan_holders as mod
        seen_metric = []

        def _send_metric(events, **kwargs):
            seen_metric.append(kwargs.get("mute_mints") or set())
            return []

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(mod, "load_watchlist", return_value=lp))
            stack.enter_context(mock.patch.object(mod, "load_holder_status", return_value={"tokens": {}}))
            stack.enter_context(mock.patch.object(mod, "load_holder_history", return_value={"tokens": {}}))
            stack.enter_context(mock.patch.object(mod, "pull_holder_history", return_value=None))
            stack.enter_context(mock.patch.object(mod, "seed_from_status", side_effect=lambda s, _st: s))
            stack.enter_context(mock.patch.object(mod, "scan_watchlist", return_value=lp))
            stack.enter_context(mock.patch.object(mod, "ingest_many", return_value={"tokens": {}}))
            stack.enter_context(mock.patch.object(mod, "publish_holder_status", return_value={"updated_at": 1}))
            stack.enter_context(mock.patch.object(mod, "publish_holder_history", return_value={"pushed": True}))
            stack.enter_context(mock.patch.object(mod, "last_publish_result", return_value={"ok": True, "error": ""}))
            stack.enter_context(mock.patch.object(mod, "fetch_watchlist_metric_snapshots", return_value={}))
            stack.enter_context(mock.patch.object(mod, "apply_metric_snapshots", return_value={"watchlist": lp, "metrics": {}, "events": [], "baseline_changed": []}))
            stack.enter_context(mock.patch.object(mod, "send_metric_alerts", side_effect=_send_metric))
            stack.enter_context(mock.patch.object(mod, "save_watchlist", return_value=True))
            stack.enter_context(mock.patch.object(mod.alert_settings, "muted_mints", side_effect=lambda *a, **kw: set(mute)))
            stack.enter_context(mock.patch.object(mod.alert_settings, "mutes_for", side_effect=lambda mints, **kw: set(mute) & set(mints or [])))
            self.assertEqual(mod.main(["--no-push"]), 0)
        return seen_metric

    def test_mute_diteruskan_ke_metric_meteora(self):
        seen_metric = self._run({LP_MINT}, lp={LP_MINT: {"symbol": "RAYCAT", "source": "meteora", "holders": {"total_fetched": 5}}})
        self.assertEqual(len(seen_metric), 1)
        self.assertEqual(seen_metric[0], {LP_MINT})

    def test_tanpa_mute_tidak_ada_yang_dilewati(self):
        seen_metric = self._run(set(), lp={LP_MINT: {"symbol": "RAYCAT", "source": "meteora", "holders": {"total_fetched": 5}}})
        self.assertEqual(seen_metric, [set()])


if __name__ == "__main__":
    unittest.main()
