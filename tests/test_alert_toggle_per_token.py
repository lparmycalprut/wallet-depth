# -*- coding: utf-8 -*-
"""Toggle alert Telegram **per token** (🔔/🔕) — watchlist Meteora + Robinhood.

Permintaan user 2026-09-11: *"kasih toggle alert on/off per token yang ada di
watchlist meteora dan robinhood. jadi misal saya sudah tau ada notif, saya
bisa nonaktifkan. tapi pas awal memasukkan ke watchlist, otomatis on"*.

Yang dikunci di sini:

1. pilihan hidup di ``alert_settings.muted_mints`` (blocklist) → **default
   ON**, jadi token yang baru ditambahkan ke watchlist otomatis menyala;
2. token yang pernah dimatikan, dihapus, lalu di-add **ulang** tidak mewarisi
   pilihan OFF lama (``watchlist.add_to_watchlist`` memanggil
   ``forget_mint_alert`` — juga di jalur massal ``add_many_to_watchlist``);
3. kontrak ``mute_mints`` = **kirim dilewati, evaluasi tetap jalan** (marker
   🚨 tetap dimajukan) dan berlaku di **semua jalur**: cron lane LP,
   tombol scan manual Meteora, dan scan manual Robinhood (LP + biasa);
4. tombolnya benar-benar ada di tiap baris: ``lp-alert-*`` (Watchlist
   Meteora), ``rh-alert-*`` (Robinhood LP), ``rhreg-alert-*`` (Robinhood
   biasa di halaman temp), lengkap dengan rekap 🔕 di kepala card;
5. kegagalan sinkron GitHub tidak ditelan — UI memberi peringatan supaya user
   tidak mengira cron sudah ikut berhenti mengirim.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import alert_settings
import watchlist as wl

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TEMP = "pages/8_temp.py"

LP_MINT = "LpMint11111111111111111111111111111111111"
# base58 valid (tanpa 0/O/I/l) supaya lolos validasi CA di UI
SOL_MINT = "Watch11111111111111111111111111111111111"
RH_CA = "0x" + "a" * 40
RH_CA2 = "0x" + "b" * 40
NOW = 1_770_000_000
BUCKET = 300


# ---------------------------------------------------------------------------
# 1. Store: alert_settings.muted_mints
# ---------------------------------------------------------------------------
class SettingsMuteStoreTest(unittest.TestCase):
    """Blocklist mute: default ON, EVM tidak case-sensitive, payload utuh."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        patch = mock.patch.object(
            alert_settings, "SETTINGS_PATH",
            os.path.join(self.dir, "alert_settings.json"))
        patch.start()
        self.addCleanup(patch.stop)
        alert_settings.reset_cache()
        self.addCleanup(alert_settings.reset_cache)
        self.write = mock.patch.object(alert_settings, "_write_remote",
                                       return_value=True)
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
        self.assertEqual(self.remote.call_args.args[0]["muted_mints"],
                         [LP_MINT])
        self.assertIn("notif off", self.remote.call_args.args[1])

        self.assertTrue(alert_settings.set_mint_alert_enabled(LP_MINT, True))
        self.assertFalse(alert_settings.is_mint_muted(LP_MINT))
        self.assertEqual(self._payload()[alert_settings.KEY_MUTED_MINTS], [])

    def test_toggle_global_dan_mute_per_token_saling_menjaga(self):
        """Dua setelan berbagi satu file: yang satu tidak menghapus lainnya."""
        alert_settings.set_mint_alert_enabled(RH_CA, False)
        self.assertTrue(alert_settings.set_regular_telegram_enabled(False))
        self.assertEqual(alert_settings.muted_mints(), {RH_CA})
        self.assertFalse(alert_settings.regular_telegram_enabled(True))

        alert_settings.set_mint_alert_enabled(RH_CA, True)
        self.assertTrue(alert_settings.set_regular_telegram_enabled(True))
        payload = self._payload()
        self.assertEqual(payload[alert_settings.KEY_MUTED_MINTS], [])
        self.assertTrue(payload[alert_settings.KEY_REGULAR_TELEGRAM])

    def test_alamat_evm_tidak_beda_huruf_besar_kecil(self):
        upper = "0x" + "A" * 40
        self.assertTrue(alert_settings.set_mint_alert_enabled(upper, False))
        self.assertTrue(alert_settings.is_mint_muted(upper.lower()))
        self.assertTrue(alert_settings.is_mint_muted(upper))
        self.assertEqual(alert_settings.mutes_for([RH_CA]),
                         {RH_CA})
        # Nomor/nama mint Solana case-sensitive: jangan di-lowercase.
        self.assertTrue(alert_settings.set_mint_alert_enabled("AbC1", False))
        self.assertFalse(alert_settings.is_mint_muted("abc1"))

    def test_forget_mint_alert_tanpa_mute_tidak_menulis(self):
        self.assertTrue(alert_settings.forget_mint_alert(LP_MINT))
        self.remote.assert_not_called()
        self.assertFalse(os.path.exists(alert_settings.SETTINGS_PATH))

    def test_forget_mint_alert_membuang_pilihan_off(self):
        alert_settings.set_mint_alert_enabled(LP_MINT, False)
        alert_settings.set_mint_alert_enabled(RH_CA, False)
        self.remote.reset_mock()
        self.assertTrue(alert_settings.forget_mint_alert(LP_MINT))
        self.assertFalse(alert_settings.is_mint_muted(LP_MINT))
        self.assertTrue(alert_settings.is_mint_muted(RH_CA))
        self.assertEqual(self.remote.call_args.args[0]["muted_mints"], [RH_CA])

    def test_daftar_stabil_dan_toleran_payload_lama(self):
        alert_settings.set_mint_alert_enabled(RH_CA, False)
        alert_settings.set_mint_alert_enabled(LP_MINT, False)
        self.assertEqual(self._payload()[alert_settings.KEY_MUTED_MINTS],
                         sorted([LP_MINT, RH_CA]))
        # String tunggal / entri kosong / angka tidak membuat modul meledak.
        with open(alert_settings.SETTINGS_PATH, "w",
                  encoding="utf-8") as handle:
            json.dump({"muted_mints": [LP_MINT, "", None, LP_MINT],
                       "telegram_regular_enabled": "off"}, handle)
        alert_settings.reset_cache()
        with mock.patch.object(alert_settings, "_read_remote",
                               return_value=None):
            self.assertEqual(alert_settings.muted_mints(), {LP_MINT})
            self.assertFalse(alert_settings.regular_telegram_enabled(True))

    def test_push_gagal_tetap_tersimpan_lokal(self):
        self.remote.return_value = False
        self.assertFalse(alert_settings.set_mint_alert_enabled(LP_MINT, False))
        self.assertTrue(alert_settings.is_mint_muted(LP_MINT))
        with mock.patch.object(alert_settings, "_read_remote",
                               return_value=None):
            alert_settings.reset_cache()
            self.assertEqual(alert_settings.muted_mints(), {LP_MINT})


# ---------------------------------------------------------------------------
# 2. Tambah token ke watchlist = otomatis ON
# ---------------------------------------------------------------------------
class AddUlangSelaluOnTest(unittest.TestCase):
    """Token baru selalu ON, termasuk token lama yang di-add ulang."""

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
            mock.patch.object(wl, "request_immediate_scan",
                              return_value=True),
            mock.patch.object(alert_settings, "SETTINGS_PATH",
                              os.path.join(self.dir, "alert_settings.json")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.write = mock.patch.object(alert_settings, "_write_remote",
                                       return_value=True)
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
        alert_settings.set_mint_alert_enabled(RH_CA, False)
        self.remote.reset_mock()
        result = wl.add_many_to_watchlist(
            [{"ca": LP_MINT, "symbol": "RAYCAT"},
             {"ca": RH_CA, "symbol": "CME"}], source="meteora")
        self.assertEqual(result.get("added"), 2)
        self.assertFalse(alert_settings.is_mint_muted(LP_MINT))
        self.assertFalse(alert_settings.is_mint_muted(RH_CA))

    def test_token_tanpa_mute_tidak_commit_apa_pun(self):
        self.assertTrue(wl.add_to_watchlist(LP_MINT, "RAYCAT"))
        self.remote.assert_not_called()


# ---------------------------------------------------------------------------
# 3. UI: tombol 🔔/🔕 per baris
# ---------------------------------------------------------------------------
def _point(ts: int, pct: float, count: int) -> dict:
    return {"ts": ts, "dust_count": count, "dust_pct_mc": pct,
            "price": 0.01, "mc": 100_000.0, "real_count": 40,
            "mid_count": 5, "holder_count": count + 40}


def _status_lp() -> dict:
    return {
        "updated_at": NOW,
        "tokens": {LP_MINT: {
            "symbol": "RAYCAT", "price": 0.01, "marketcap": 100_000.0,
            "analyzed_at": NOW,
            "holders": {"dust_count": 70, "dust_pct_mc": 0.55,
                        "real_count": 40, "total_fetched": 110},
            "history": [_point(NOW - BUCKET, 0.30, 50),
                        _point(NOW, 0.55, 70)],
        }},
    }


def _store_lp() -> dict:
    return {"updated_at": NOW, "tokens": {LP_MINT: {
        "symbol": "RAYCAT", "cohort": {},
        "points": [_point(NOW - BUCKET, 0.30, 50),
                   _point(NOW, 0.55, 70)]}}}


def _analysis(symbol: str, pct: float, ts: int = NOW) -> dict:
    return {"symbol": symbol, "analyzed_at": ts,
            "holders": {"total_fetched": 500, "dust_pct_mc": pct,
                        "wallet_snapshot": {"ts": ts, "dust_pct_mc": pct}}}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class AlertToggleUiTest(unittest.TestCase):
    """Tombol 🔔/🔕 di baris watchlist Meteora + kedua card Robinhood."""

    def setUp(self):
        self.sent: list[dict] = []
        self.written: dict = {}
        self.store: dict = {}
        patches = [
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
            mock.patch("holder_status.atomic_write_json",
                       side_effect=self._write),
            mock.patch("holder_history.save_holder_history",
                       side_effect=self._save),
            mock.patch("telegram_alerts.send_telegram_alert",
                       side_effect=self._sender),
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: self.watchlist()),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: _status_lp()),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *_a, **_kw: _store_lp()),
            mock.patch("robinhood_watchlist.load_watchlist",
                       side_effect=lambda **_kw: self.rh_watchlist()),
            mock.patch("robinhood_watchlist.load_status",
                       return_value={"updated_at": NOW, "tokens": {}}),
            mock.patch("robinhood_watchlist.load_history",
                       return_value={"updated_at": NOW, "tokens": {}}),
            mock.patch("robinhood_watchlist.sync_state",
                       return_value={"state": ""}),
            mock.patch("alert_settings.muted_mints",
                       side_effect=lambda *a, **kw: set(self.muted)),
            mock.patch("alert_settings.set_mint_alert_enabled",
                       side_effect=self._toggle),
        ]
        self.muted: set[str] = set()
        self.toggle_ok = True
        self.toggle_calls: list[tuple] = []
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    # --- harness ------------------------------------------------------------
    def watchlist(self):
        return {LP_MINT: {"symbol": "RAYCAT", "source": "meteora",
                          "added": "2026-09-11"},
                SOL_MINT: {"symbol": "HOLDT", "source": "manual",
                           "added": "2026-09-11"}}

    def rh_watchlist(self):
        return {RH_CA: {"symbol": "CME", "source": "lp",
                        "added": "2026-09-11"},
                RH_CA2: {"symbol": "MOO", "source": "regular",
                         "added": "2026-09-11"}}

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

    def _app(self, *, temp=False):
        app = AppTest.from_file(APP, default_timeout=90)
        if temp:
            app = app.switch_page(TEMP)
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

    # --- tampilan -----------------------------------------------------------
    def test_baris_lp_punya_bell_on_dan_klik_mematikan(self):
        app = self._app()
        button = self._button(app, f"lp-alert-{LP_MINT}")
        self.assertEqual(button.label, "🔔")
        self.assertIn("Matikan notif Telegram", button.help or "")
        button.click().run()
        self.assertEqual(self.toggle_calls, [(LP_MINT, False)])
        self.assertEqual(len(app.exception), 0)

    def test_baris_lp_muted_tampil_bell_off_rekap_dan_catatan(self):
        self.muted = {LP_MINT}
        app = self._app()
        self.assertEqual(self._button(app, f"lp-alert-{LP_MINT}").label, "🔕")
        self.assertIn("🔕 notif off", self._body(app))
        self.assertIn("🔕 1", self._body(app))     # pill di kepala card
        # Token tetap dipantau: baris + dust tetap dirender.
        self.assertIn("$RAYCAT", self._body(app))
        self.assertIn("0.55%", self._body(app))

    def test_klik_bell_off_menyalakan_lagi(self):
        self.muted = {LP_MINT}
        app = self._app()
        self._button(app, f"lp-alert-{LP_MINT}").click().run()
        self.assertEqual(self.toggle_calls, [(LP_MINT, True)])

    def test_notif_biasa_robinhood_punya_bell_sendiri(self):
        app = self._app(temp=True)
        self.assertEqual(self._button(app, f"rhreg-alert-{RH_CA2}").label, "🔔")
        self._button(app, f"rhreg-alert-{RH_CA2}").click().run()
        self.assertEqual(self.toggle_calls, [(RH_CA2, False)])

    def test_notif_robinhood_lp_punya_bell_di_halaman_utama(self):
        app = self._app()
        self.assertEqual(self._button(app, f"rh-alert-{RH_CA}").label, "🔔")
        self.muted = {RH_CA}
        app = self._app()
        self.assertEqual(self._button(app, f"rh-alert-{RH_CA}").label, "🔕")
        self.assertIn("🔕 notif off", self._body(app))

    def test_gagal_sinkron_github_diperingatkan(self):
        self.toggle_ok = False
        app = self._app()
        self._button(app, f"lp-alert-{LP_MINT}").click().run()
        warnings = "\n".join(node.value for node in app.warning)
        self.assertIn("sinkronisasi ke GitHub gagal", warnings)

    # --- jalur scan ---------------------------------------------------------
    def test_scan_lp_manual_menghormati_bell_off(self):
        self.muted = {LP_MINT}
        app = self._app()
        with mock.patch("holder_analysis.analyze_token",
                        return_value=_analysis("RAYCAT", 0.11)):
            app = self._button(app, "lp-scan-now").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.sent, [], "token yang dimatikan tidak boleh kirim")
        self.assertIn("dilewati", self._info(app))
        # Evaluasi tetap jalan: marker episode ikut tersimpan.
        state = ((self.store.get("tokens") or {}).get(LP_MINT) or {}).get(
            "alert_state") or {}
        self.assertIn("strategy_shift", state)

    def test_scan_lp_manual_tanpa_bell_off_tetap_kirim(self):
        app = self._app()
        with mock.patch("holder_analysis.analyze_token",
                        return_value=_analysis("RAYCAT", 0.11)):
            app = self._button(app, "lp-scan-now").click().run()
        self.assertEqual(len(self.sent), 1, self.sent)
        self.assertIn("dikirim", self._info(app))

    def test_scan_robinhood_lp_manual_menghormati_bell_off(self):
        self.muted = {RH_CA}
        app = self._app()
        with mock.patch("robinhood_watchlist.scan_watchlist",
                        return_value={RH_CA: _analysis("CME", 0.11)}), \
                mock.patch("robinhood_watchlist.publish_scan",
                           return_value={"updated_at": NOW}):
            app = self._label_button(
                app, "🔄 Scan holder watchlist Robinhood LP").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.sent, [])
        self.assertIn("dilewati", self._info(app))

    def test_scan_robinhood_biasa_hormati_bell_walau_toggle_global_on(self):
        """Lane biasa: toggle global ON + bell 🔕 token → tetap tidak kirim."""
        self.muted = {RH_CA2}
        app = self._app(temp=True)
        with mock.patch("alert_settings.regular_telegram_enabled",
                        return_value=True), \
                mock.patch("robinhood_watchlist.scan_watchlist",
                           return_value={RH_CA2: _analysis("MOO", 0.11)}), \
                mock.patch("robinhood_watchlist.publish_scan",
                           return_value={"updated_at": NOW}):
            app = self._label_button(
                app, "🔄 Scan holder watchlist Robinhood biasa").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.sent, [])
        self.assertIn("dilewati", self._info(app))

    def test_scan_watchlist_biasa_solana_hormati_mute_token_pindahan(self):
        """Token yang di-🔕 di card Meteora lalu dipindah (📋) tetap senyap.

        Toggle-nya tidak dirender di card Holder, jadi yang diuji di sini
        adalah pilihan yang **ikut terbawa** token — bukan memaksa user
        mencari tokennya kembali di card Meteora.
        """
        self.muted = {SOL_MINT}
        app = self._app(temp=True)
        with mock.patch("alert_settings.regular_telegram_enabled",
                        return_value=True), \
                mock.patch("holder_analysis.analyze_token",
                           return_value=_analysis("HOLDT", 0.11)):
            app = self._label_button(
                app, "🔄 Scan holder watchlist").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.sent, [])
        self.assertIn("dilewati", self._info(app))

    def test_scan_robinhood_biasa_tanpa_bell_tetap_kirim(self):
        app = self._app(temp=True)
        with mock.patch("alert_settings.regular_telegram_enabled",
                        return_value=True), \
                mock.patch("robinhood_watchlist.scan_watchlist",
                           return_value={RH_CA2: _analysis("MOO", 0.11)}), \
                mock.patch("robinhood_watchlist.publish_scan",
                           return_value={"updated_at": NOW}):
            app = self._label_button(
                app, "🔄 Scan holder watchlist Robinhood biasa").click().run()
        self.assertEqual(len(self.sent), 1, self.sent)


# ---------------------------------------------------------------------------
# 4. Cron lane LP menghormati pilihan yang sama
# ---------------------------------------------------------------------------
class CronMuteWiringTest(unittest.TestCase):
    """``scripts/scan_holders.py`` meneruskan mute token ke kedua lane LP."""

    def _run(self, mute, *, lp, rh):
        import scripts.scan_holders as mod
        import robinhood_watchlist as rw_mod
        seen = []

        def _process(items, store, **kwargs):
            seen.append(kwargs.get("mute_mints"))
            return []

        with mock.patch.object(mod, "load_watchlist", return_value=lp), \
                mock.patch.object(mod, "load_holder_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "load_holder_history",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "pull_holder_history",
                                  return_value=None), \
                mock.patch.object(mod, "seed_from_status",
                                  side_effect=lambda s, _st: s), \
                mock.patch.object(mod, "scan_watchlist",
                                  return_value=lp), \
                mock.patch.object(mod, "ingest_many",
                                  return_value={"tokens": {}}), \
                mock.patch.object(mod, "publish_holder_status",
                                  return_value={"updated_at": 1}), \
                mock.patch.object(mod, "publish_holder_history",
                                  return_value={"pushed": True}), \
                mock.patch.object(mod, "last_publish_result",
                                  return_value={"ok": True, "error": ""}), \
                mock.patch.object(mod.alert_settings, "muted_mints",
                                  side_effect=lambda *a, **kw: set(mute)), \
                mock.patch.object(rw_mod, "load_watchlist",
                                  return_value=rh), \
                mock.patch.object(rw_mod, "load_status",
                                  return_value={"tokens": {}}), \
                mock.patch.object(rw_mod, "load_history",
                                  return_value={"tokens": {}}), \
                mock.patch.object(rw_mod, "scan_watchlist",
                                  return_value=rh), \
                mock.patch.object(rw_mod, "publish_scan",
                                  return_value={"updated_at": 2}), \
                mock.patch.object(mod, "process_holder_alerts",
                                  side_effect=_process):
            self.assertEqual(mod.main(["--no-push"]), 0)
        return seen

    def test_mute_diteruskan_ke_meteora_dan_robinhood(self):
        rh_ca = RH_CA2
        seen = self._run({LP_MINT, rh_ca},
                         lp={LP_MINT: {"symbol": "RAYCAT",
                                       "source": "meteora",
                                       "holders": {"total_fetched": 5}}},
                         rh={rh_ca: {"symbol": "MOO", "source": "lp",
                                     "holders": {"total_fetched": 5}}})
        self.assertEqual(len(seen), 2, "dua lane harus dievaluasi")
        self.assertEqual(seen[0], {LP_MINT})
        self.assertEqual(seen[1], {rh_ca})

    def test_tanpa_mute_tidak_ada_yang_dilewati(self):
        seen = self._run(set(),
                         lp={LP_MINT: {"symbol": "RAYCAT",
                                       "source": "meteora",
                                       "holders": {"total_fetched": 5}}},
                         rh={})
        self.assertEqual(seen, [set()])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
