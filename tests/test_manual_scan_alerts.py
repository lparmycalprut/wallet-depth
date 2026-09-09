# -*- coding: utf-8 -*-
"""Alert Telegram juga dikirim dari **scan manual** dashboard.

Permintaan user 2026-09-09: "meskipun saya scan manual, jika hasilnya harus
kirim notif, kirim saja". Sebelumnya hanya cron (:mod:`scripts.scan_holders`)
yang memanggil :func:`telegram_alerts.process_holder_alerts`, sehingga token
yang baru dipantau — atau token di lane yang tidak di-scan cron sama sekali
(watchlist biasa sejak 2026-09-07) — tidak pernah mengirim notif meski
dashboard sudah menampilkan dust di atas ambang (kasus nyata: MOO
``0xc103ac…`` 0,11% MC di Robinhood, tidak ada pesan Telegram).

Yang dikunci di sini:

1. ketiga tombol scan manual (Chart LP Meteora, Robinhood LP/biasa, watchlist
   biasa Solana) mengevaluasi + mengirim alert;
2. evaluasi berjalan **sebelum** ``ingest_many``/``publish_scan`` supaya rule
   membaca anchor lama dan state hasil evaluasi ikut tersimpan;
3. dust di bawah ambang tidak mengirim apa pun (tidak ada spam);
4. tombol on/off notif watchlist biasa tetap dihormati (mute = evaluasi jalan,
   kirim dilewati);
5. kredensial Telegram ditemukan di ``config.json``/``st.secrets`` — bukan
   hanya env — karena dashboard tidak punya env Actions; kegagalan kirim
   dilaporkan ke UI, bukan ditelan.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import telegram_alerts as ta

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TEMP_PAGE = "pages/8_temp.py"

LP_MINT = "LpMint11111111111111111111111111111111111"
SOL_MINT = "SolMint2222222222222222222222222222222222"
RH_CA = "0xc103ac00a25173870c909223c5676d50bf5728b2"
NOW = 1_800_000_000


def _holders(dust_pct: float, *, wallets: int = 900, dust: int = 120) -> dict:
    """Holder layak (:func:`holder_history.holders_usable`) pada dust tertentu."""
    return {"dust_count": dust, "dust_pct_mc": dust_pct,
            "dust_value_usd": dust * 5.0, "real_count": wallets - dust,
            "real_pct_mc": 12.0, "wallets_analyzed": wallets,
            "total_fetched": wallets, "truncated": False, "source": "helius",
            "mid": {"count": 2, "pct_mc": 3.0, "balances": {}}}


def _analysis(symbol: str, dust_pct: float, **kwargs) -> dict:
    return {"symbol": symbol, "analyzed_at": NOW,
            "holders": _holders(dust_pct, **kwargs),
            "market": {"marketcap": 250_000.0, "price": 0.001}}


class DeliverySummaryTest(unittest.TestCase):
    """Ringkasan kirim alert yang dipakai UI scan manual."""

    def test_sent_muted_failed_dan_kosong(self):
        rows = [
            {"event": {"kind": "early_dump"}, "delivery": {"ok": True}},
            {"event": {"kind": "high_drop"},
             "delivery": {"ok": False, "skipped": True, "muted": True,
                          "error": "telegram muted"}},
            {"event": {"kind": "early_dump"},
             "delivery": {"ok": False,
                          "error": "Telegram credentials are not configured"}},
        ]
        summary = ta.summarize_deliveries(rows)
        self.assertEqual((summary["total"], summary["sent"], summary["muted"],
                          summary["failed"]), (3, 1, 1, 1))
        self.assertEqual(summary["kinds"],
                         ["early_dump", "high_drop", "early_dump"])
        note = ta.delivery_note(summary)
        self.assertIn("1 alert Telegram dikirim", note)
        self.assertIn("1 alert dilewati (notif watchlist biasa OFF)", note)
        self.assertIn("1 alert GAGAL dikirim", note)
        self.assertIn("Telegram credentials are not configured", note)

    def test_tanpa_event_dibedakan_dari_gagal(self):
        summary = ta.summarize_deliveries([])
        self.assertEqual(summary["total"], 0)
        self.assertEqual(ta.delivery_note(summary),
                         "Tidak ada alert dari hasil scan ini.")
        self.assertEqual(ta.delivery_note(None),
                         "Tidak ada alert dari hasil scan ini.")


class TelegramCredentialFallbackTest(unittest.TestCase):
    """Dashboard tidak punya env Actions: kredensial dari config.json."""

    def _without_env(self):
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            patch = mock.patch.dict(os.environ, {}, clear=False)
            patch.start()
            self.addCleanup(patch.stop)
            os.environ.pop(key, None)

    def test_kredensial_dibaca_dari_config_json(self):
        self._without_env()
        import core
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as handle:
                json.dump({"telegram_bot_token": "123:CFG",
                           "telegram_chat_id": "-100CFG"}, handle)
            with mock.patch.object(core, "CONFIG_PATH", cfg_path):
                self.assertEqual(ta._telegram_credentials(),
                                 ("123:CFG", "-100CFG"))

    def test_env_tetap_menang(self):
        import core
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "9:ENV",
                                          "TELEGRAM_CHAT_ID": "-1ENV"}):
            with tempfile.TemporaryDirectory() as tmp:
                cfg_path = os.path.join(tmp, "config.json")
                with open(cfg_path, "w", encoding="utf-8") as handle:
                    json.dump({"telegram_bot_token": "123:CFG",
                               "telegram_chat_id": "-100CFG"}, handle)
                with mock.patch.object(core, "CONFIG_PATH", cfg_path):
                    self.assertEqual(ta._telegram_credentials(),
                                     ("9:ENV", "-1ENV"))

    def test_pesan_dipakai_bila_env_kosong(self):
        """``send_telegram_message`` harus ikut memakai fallback config.json."""
        self._without_env()
        import core
        posted = {}

        def _post(url, json=None, timeout=None, **_kw):
            posted["url"] = url
            posted["chat_id"] = (json or {}).get("chat_id")
            posted["text"] = (json or {}).get("text")

            class _Resp:
                status_code = 200

                @staticmethod
                def json():
                    return {"ok": True}

            return _Resp()

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as handle:
                json.dump({"telegram_bot_token": "123:CFG",
                           "telegram_chat_id": "-100CFG"}, handle)
            with mock.patch.object(core, "CONFIG_PATH", cfg_path):
                result = ta.send_telegram_message("uji", post=_post)
        self.assertTrue(result.get("ok"), result)
        self.assertIn("123:CFG", posted["url"])
        self.assertEqual(posted["chat_id"], "-100CFG")
        self.assertEqual(posted["text"], "uji")

    def test_tanpa_kredensial_tetap_dilaporkan_bukan_ditelan(self):
        self._without_env()
        import core
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "config.json")
            with open(empty, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with mock.patch.object(core, "CONFIG_PATH", empty):
                with mock.patch("streamlit.secrets", {}):
                    result = ta.send_telegram_message("uji")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"),
                         "Telegram credentials are not configured")


@unittest.skipIf(AppTest is None, "streamlit not installed")
class ManualScanAlertTest(unittest.TestCase):
    """Tombol scan manual di dashboard ikut mengirim alert."""

    def setUp(self):
        self.sent: list[dict] = []
        self.written: dict = {}
        self.store: dict = {}
        patches = [
            # Tidak boleh menyentuh disk/jaringan dari tes.
            mock.patch("holder_history.pull_holder_history", return_value=None),
            mock.patch("holder_status.atomic_write_json",
                       side_effect=self._write),
            mock.patch("holder_history.save_holder_history",
                       side_effect=self._save),
            mock.patch("telegram_alerts.send_telegram_alert",
                       side_effect=self._sender),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _write(self, path, payload, **_kw):
        self.written[str(path)] = payload
        return payload

    def _save(self, store, path=None):
        self.store = store
        return store

    def _sender(self, event):
        self.sent.append(event)
        return {"ok": True, "skipped": False}

    def _infos(self, app):
        return "\n".join(node.value for node in app.info)

    # -- Chart LP Meteora (app.py) -----------------------------------------
    def _run_lp_scan(self, dust_pct: float, *, alert_state=None):
        """Scan manual Chart LP; ``alert_state`` = marker episode sebelumnya.

        Marker ⚡ bersarang di ``alert_state["early_dump"]`` (bentuk yang
        dibaca ``evaluate_alert_events``) — salah sarang berarti rule episode
        tidak pernah melihat episodenya.
        """
        store = {"tokens": {LP_MINT: {"symbol": "LPRISK", "cohort": {},
                                      "points": [],
                                      "alert_state": alert_state or {}}}}
        patches = [
            mock.patch("watchlist.load_watchlist",
                       return_value={LP_MINT: {"symbol": "LPRISK",
                                               "source": "meteora",
                                               "added": "2026-09-03"}}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": NOW - 300, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value=store),
            mock.patch("holder_analysis.analyze_token",
                       return_value=_analysis("LPRISK", dust_pct)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=90).run()
        self.assertEqual(len(app.exception), 0)
        button = [b for b in app.button if b.key == "lp-scan-now"]
        self.assertTrue(button, "tombol scan Chart LP tidak ditemukan")
        button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_chart_lp_scan_manual_mengirim_early_dump(self):
        app = self._run_lp_scan(0.11)
        self.assertEqual(len(self.sent), 1, self.sent)
        self.assertEqual(self.sent[0]["kind"], "early_dump")
        self.assertEqual(self.sent[0]["mint"], LP_MINT)
        self.assertAlmostEqual(self.sent[0]["current_dust_pct_mc"], 0.11)
        self.assertIn("1 alert Telegram dikirim", self._infos(app))

    def test_chart_lp_di_bawah_ambang_tidak_mengirim(self):
        app = self._run_lp_scan(0.05)
        self.assertEqual(self.sent, [])
        self.assertNotIn("alert Telegram dikirim", self._infos(app))

    def test_state_alert_tersimpan_bersama_store(self):
        """State (last_sent/marker) harus ikut ditulis ingest_many.

        Tanpa ini scan manual berikutnya mengirim pesan yang sama lagi:
        dedup event id + cooldown dibaca dari ``alert_state``.
        """
        self._run_lp_scan(0.11)
        state = ((self.store.get("tokens") or {}).get(LP_MINT) or {}).get(
            "alert_state") or {}
        self.assertIn("early_dump", state)
        self.assertAlmostEqual(state["early_dump"]["dust_pct_mc"], 0.11)
        self.assertIn("early_dump", state.get("last_sent") or {})

    def test_eskalasi_exit_cutloss_dari_scan_manual(self):
        """Naik 3 scan berturut dalam ±15 menit → 🚨 WAKTUNYA EXIT/CUTLOSS."""
        episode = {"early_dump": {"ts": NOW - 300, "dust_pct_mc": 0.13,
                                  "first_ts": NOW - 600, "rises": 2,
                                  "escalated": False}}
        self._run_lp_scan(0.15, alert_state=episode)
        kinds = [event["kind"] for event in self.sent]
        self.assertIn("exit_cutloss", kinds)
        self.assertIn("early_dump", kinds)

    def test_kembali_ke_titik_aman_dari_scan_manual(self):
        """Turun lagi ke ≤ 0,1% MC dalam jendela episode → ✅ penutup."""
        episode = {"early_dump": {"ts": NOW - 300, "dust_pct_mc": 0.14,
                                  "first_ts": NOW - 600, "rises": 2,
                                  "escalated": False}}
        self._run_lp_scan(0.08, alert_state=episode)
        self.assertEqual([event["kind"] for event in self.sent],
                         ["safe_return"])

    def test_scan_manual_kedua_di_bucket_sama_tidak_mengirim_ulang(self):
        """Dedup event id per bucket 5 menit harus bertahan antar scan.

        State hasil scan pertama ikut ditulis ``ingest_many``; scan manual
        kedua pada bucket yang sama tidak boleh mengirim pesan kembar.
        """
        self._run_lp_scan(0.11)
        self.assertEqual(len(self.sent), 1)
        state = ((self.store.get("tokens") or {}).get(LP_MINT) or {}).get(
            "alert_state") or {}
        events, _ = ta.evaluate_alert_events(
            LP_MINT, _analysis("LPRISK", 0.11), state,
            lp_mint=True, volume_rules=False)
        self.assertEqual(events, [], "event kembar lolos dedup bucket 5 menit")

    # -- Robinhood LP (app.py) ---------------------------------------------
    def _run_rh_scan(self, variant: str, dust_pct: float, *,
                     telegram_on: bool = True, marker=None):
        source = "lp" if variant == "lp" else "regular"
        # Marker 🔔 HIGH DROP bersarang di ``alert_state["high_drop"]``
        # (lihat telegram_alerts.evaluate_alert_events).
        store = {"tokens": {RH_CA: {"symbol": "MOO", "cohort": {},
                                    "points": [],
                                    "alert_state": ({"high_drop": marker}
                                                    if marker else {})}}}
        patches = [
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": NOW - 300, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value={"tokens": {}}),
            mock.patch("robinhood_watchlist.load_watchlist",
                       return_value={RH_CA: {"symbol": "MOO", "source": source,
                                             "added": "2026-09-09"}}),
            mock.patch("robinhood_watchlist.load_status",
                       return_value={"updated_at": NOW - 300, "tokens": {}}),
            mock.patch("robinhood_watchlist.load_history",
                       side_effect=lambda *a, **kw: json.loads(json.dumps(store))),
            mock.patch("robinhood_watchlist.sync_state",
                       return_value={"state": ""}),
            mock.patch("robinhood_watchlist.scan_watchlist",
                       return_value={RH_CA: _analysis("MOO", dust_pct)}),
            mock.patch("robinhood_watchlist.publish_scan",
                       return_value={"updated_at": NOW}),
            mock.patch("alert_settings.regular_telegram_enabled",
                       return_value=telegram_on),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=90)
        if variant == "regular":
            app = app.switch_page(TEMP_PAGE)
        app.run()
        self.assertEqual(len(app.exception), 0)
        label = ("🔄 Scan holder watchlist Robinhood LP" if variant == "lp"
                 else "🔄 Scan holder watchlist Robinhood biasa")
        button = [b for b in app.button if (b.label or "") == label]
        self.assertTrue(button, f"tombol {label} tidak ditemukan")
        button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_robinhood_lp_scan_manual_mengirim_early_dump(self):
        app = self._run_rh_scan("lp", 0.11)
        self.assertEqual(len(self.sent), 1, self.sent)
        self.assertEqual(self.sent[0]["kind"], "early_dump")
        self.assertEqual(self.sent[0]["mint"], RH_CA)
        self.assertIn("1 alert Telegram dikirim", self._infos(app))

    def test_robinhood_lp_di_bawah_ambang_tidak_mengirim(self):
        app = self._run_rh_scan("lp", 0.08)
        self.assertEqual(self.sent, [])
        self.assertNotIn("alert Telegram dikirim", self._infos(app))

    def test_lane_biasa_memakai_rule_high_drop(self):
        """Watchlist biasa tidak di-scan cron: scan manual satu-satunya jalur."""
        marker = {"high": 0.80, "high_ts": NOW - 7200, "ts": NOW - 7200,
                  "notified_high": 0.0}
        app = self._run_rh_scan("regular", 0.20, marker=marker)
        self.assertEqual(len(self.sent), 1, self.sent)
        self.assertEqual(self.sent[0]["kind"], "high_drop")
        self.assertIn("1 alert Telegram dikirim", self._infos(app))

    def test_notif_lane_biasa_dimatikan_user_tetap_dievaluasi(self):
        """Mute: rule + marker jalan, hanya pengiriman yang dilewati."""
        marker = {"high": 0.80, "high_ts": NOW - 7200, "ts": NOW - 7200,
                  "notified_high": 0.0}
        app = self._run_rh_scan("regular", 0.20, telegram_on=False,
                                marker=marker)
        self.assertEqual(self.sent, [], "notif OFF tapi pesan tetap terkirim")
        note = self._infos(app)
        self.assertIn("dilewati (notif watchlist biasa OFF)", note)
        self.assertNotIn("GAGAL dikirim", note)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
