# -*- coding: utf-8 -*-
"""Alert Telegram juga dikirim dari **scan manual** dashboard.

Permintaan user 2026-09-09: "meskipun saya scan manual, jika hasilnya harus
kirim notif, kirim saja". Sebelumnya hanya cron (:mod:`scripts.scan_holders`)
yang memanggil :func:`telegram_alerts.process_holder_alerts`, sehingga token
yang baru dipantau — atau token di lane yang tidak di-scan cron sama sekali
(watchlist biasa sejak 2026-09-07) — tidak pernah mengirim notif meski
dashboard sudah menampilkan dust di atas ambang.

Sejak 2026-09-13 notifnya satu: ⚡ **EARLY DUMP TERJADI - GANTI WIDE RANGE**
(dust naik ≥ 0,02% MC dari patokan saat token di-add) — dan lane mana pun yang
di-scan boleh mengirimnya, termasuk watchlist biasa lewat tombol scan manual.

Yang dikunci di sini:

1. tombol scan manual **Chart LP Meteora** mengevaluasi + mengirim alert
   (card Robinhood LP/biasa dan card watchlist biasa ikut terhapus bersama
   page 🦅 Robinhood + page temp, 2026-09-15);
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

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
# 🔄 Scan sekarang Chart LP duduk di card 🌊 Watchlist Meteora yang pindah ke
# halaman 📦 TEMP (2026-09-16) — uji tombolnya ikut ke sana.
TEMP = str(ROOT / "pages/6_📦_TEMP.py")

LP_MINT = "LpMint11111111111111111111111111111111111"
SOL_MINT = "SolMint2222222222222222222222222222222222"
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


def _episode(dust_pct, *, baseline=0.05, step=0, ts=NOW - 300):
    """Marker ⚡ seperti tulisan ``early_dump_marker_next`` (siap berbunyi).

    ``dust_pct_mc`` = angka run terakhir, ``baseline_pct`` = patokan saat token
    masuk watchlist, ``step`` = langkah 0,02% yang sudah dikabarkan. Rule baru
    berbunyi kalau ``dust_pct_mc`` run ini sudah melewati langkah berikutnya.
    """
    return {ta.EARLY_DUMP_MARKER: {
        "ts": ts, "dust_pct_mc": dust_pct,
        "baseline_pct": baseline, "baseline_ts": NOW - 900,
        "step": step, "baseline_src": "history"}}


class DeliverySummaryTest(unittest.TestCase):
    """Ringkasan kirim alert yang dipakai UI scan manual."""

    def test_sent_muted_failed_dan_kosong(self):
        kinds = ta.EARLY_DUMP_KIND
        rows = [
            {"event": {"kind": kinds}, "delivery": {"ok": True}},
            {"event": {"kind": kinds},
             "delivery": {"ok": False, "skipped": True, "muted": True,
                          "error": "telegram muted"}},
            {"event": {"kind": kinds},
             "delivery": {"ok": False,
                          "error": "Telegram credentials are not configured"}},
        ]
        summary = ta.summarize_deliveries(rows)
        self.assertEqual((summary["total"], summary["sent"], summary["muted"],
                          summary["failed"]), (3, 1, 1, 1))
        self.assertEqual(summary["kinds"], [kinds, kinds, kinds])
        note = ta.delivery_note(summary)
        self.assertIn("1 notifikasi EARLY DUMP TERJADI dikirim", note)
        self.assertIn("1 notifikasi dilewati (notif token itu sedang dimatikan)", note)
        self.assertIn("1 notifikasi GAGAL dikirim", note)
        self.assertIn("Telegram credentials are not configured", note)

    def test_tanpa_event_dibedakan_dari_gagal(self):
        summary = ta.summarize_deliveries([])
        self.assertEqual(summary["total"], 0)
        self.assertEqual(ta.delivery_note(summary),
                         "Tidak ada notifikasi dari hasil scan ini.")
        self.assertEqual(ta.delivery_note(None),
                         "Tidak ada notifikasi dari hasil scan ini.")


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

    def test_kredensial_dari_streamlit_secrets_huruf_besar(self):
        """Secret GitHub/DEPLOY memakai TELEGRAM_*; Streamlit harus sama."""
        self._without_env()
        import core
        secrets = {"TELEGRAM_BOT_TOKEN": "123:ST",
                   "TELEGRAM_CHAT_ID": "-100ST"}
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "config.json")
            with open(empty, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with mock.patch.object(core, "CONFIG_PATH", empty):
                with mock.patch("streamlit.secrets", secrets):
                    self.assertEqual(ta._telegram_credentials(),
                                     ("123:ST", "-100ST"))

    def test_kredensial_dari_streamlit_secrets_huruf_kecil(self):
        self._without_env()
        import core
        secrets = {"telegram_bot_token": "123:st",
                   "telegram_chat_id": "-100st"}
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "config.json")
            with open(empty, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with mock.patch.object(core, "CONFIG_PATH", empty):
                with mock.patch("streamlit.secrets", secrets):
                    self.assertEqual(ta._telegram_credentials(),
                                     ("123:st", "-100st"))

    def test_token_saja_tanpa_chat_id_tetap_belum_terpasang(self):
        """Bot token tanpa chat ID = kredensial belum lengkap."""
        self._without_env()
        import core
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:ONLY"}):
            with tempfile.TemporaryDirectory() as tmp:
                empty = os.path.join(tmp, "config.json")
                with open(empty, "w", encoding="utf-8") as handle:
                    json.dump({}, handle)
                with mock.patch.object(core, "CONFIG_PATH", empty):
                    with mock.patch("streamlit.secrets", {}):
                        self.assertEqual(ta._telegram_credentials(),
                                         ("123:ONLY", ""))
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

    # -- Chart LP Meteora (halaman 📦 TEMP) --------------------------------
    def _run_lp_scan(self, dust_pct: float, *, alert_state=None):
        """Scan manual Chart LP; ``alert_state`` = state alert tersimpan.

        Marker ⚡ bersarang di ``alert_state["early_dump"]`` (bentuk yang
        dibaca ``evaluate_alert_events``) — salah sarang berarti rule tidak
        pernah melihat episode sebelumnya.
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
        app = AppTest.from_file(TEMP, default_timeout=90).run()
        self.assertEqual(len(app.exception), 0)
        button = [b for b in app.button if b.key == "lp-scan-now"]
        self.assertTrue(button, "tombol scan Chart LP tidak ditemukan")
        button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_chart_lp_scan_manual_mengirim_notif(self):
        app = self._run_lp_scan(0.11, alert_state=_episode(0.05))
        self.assertEqual(len(self.sent), 1, self.sent)
        self.assertEqual(self.sent[0]["kind"], ta.EARLY_DUMP_KIND)
        self.assertEqual(self.sent[0]["mint"], LP_MINT)
        self.assertAlmostEqual(self.sent[0]["current_dust_pct_mc"], 0.11)
        # 0,11% vs patokan 0,05% = 3 langkah 0,02% (bukan ambang 0,06%).
        self.assertEqual(self.sent[0]["step"], 3)
        self.assertIn("1 notifikasi EARLY DUMP TERJADI dikirim",
                      self._infos(app))

    def test_chart_lp_di_bawah_langkah_tidak_mengirim(self):
        # 0,06% vs patokan 0,05% = naik 0,01% → belum sampai satu langkah
        # 0,02%, jadi tidak ada spam.
        app = self._run_lp_scan(0.06, alert_state=_episode(0.05))
        self.assertEqual(self.sent, [])
        self.assertNotIn("notifikasi", self._infos(app))

    def test_scan_pertama_memasang_patokan_tanpa_notif(self):
        """Tanpa state = run pertama rule ini: patokan dipasang, diam dulu."""
        app = self._run_lp_scan(0.30)
        self.assertEqual(self.sent, [])
        state = ((self.store.get("tokens") or {}).get(LP_MINT) or {}).get(
            "alert_state") or {}
        marker = state["early_dump"]
        self.assertAlmostEqual(marker["baseline_pct"], 0.30)
        self.assertEqual(marker["step"], 0)
        self.assertNotIn("notifikasi", self._infos(app))

    def test_state_alert_tersimpan_bersama_store(self):
        """State (last_sent/marker) harus ikut ditulis ingest_many.

        Tanpa ini scan manual berikutnya mengirim pesan yang sama lagi:
        dedup event id + cooldown dibaca dari ``alert_state``.
        """
        self._run_lp_scan(0.11, alert_state=_episode(0.05))
        state = ((self.store.get("tokens") or {}).get(LP_MINT) or {}).get(
            "alert_state") or {}
        marker = state["early_dump"]
        self.assertAlmostEqual(marker["dust_pct_mc"], 0.11)
        self.assertAlmostEqual(marker["baseline_pct"], 0.05)
        self.assertEqual(marker["step"], 3)
        self.assertIn(ta.EARLY_DUMP_KIND, state.get("last_sent") or {})

    def test_langkah_berikutnya_dilanjutkan_bukan_dimulai_ulang(self):
        """Marker langkah 4 → kenaikan ke langkah 5 = pengingat berulang.

        Patokan (``baseline_pct``/``baseline_ts``) TIDAK digeser saat run
        berjalan: 0,02% selalu dihitung dari angka saat token di-add.
        """
        episode = _episode(0.13, baseline=0.05, step=4)
        self._run_lp_scan(0.15, alert_state=episode)
        self.assertEqual([e["kind"] for e in self.sent], [ta.EARLY_DUMP_KIND])
        self.assertEqual(self.sent[0]["step"], 5)
        state = ((self.store.get("tokens") or {}).get(LP_MINT) or {}).get(
            "alert_state") or {}
        marker = state["early_dump"]
        self.assertEqual(marker["ts"], NOW)
        self.assertAlmostEqual(marker["baseline_pct"], 0.05)
        self.assertEqual(marker["baseline_ts"], NOW - 900)
        self.assertEqual(marker["step"], 5)

    def test_turun_di_bawah_patokan_tanpa_notif_penutup(self):
        """Dust turun lagi = diam, TIDAK ada pesan "aman"; step tidak mundur."""
        episode = _episode(0.14, baseline=0.05, step=4)
        self._run_lp_scan(0.02, alert_state=episode)
        self.assertEqual(self.sent, [])
        state = ((self.store.get("tokens") or {}).get(LP_MINT) or {}).get(
            "alert_state") or {}
        marker = state["early_dump"]
        self.assertAlmostEqual(marker["baseline_pct"], 0.05)
        self.assertEqual(marker["step"], 4)   # high water mark tidak mundur

    def test_scan_manual_kedua_di_bucket_sama_tidak_mengirim_ulang(self):
        """Dedup event id per bucket 5 menit harus bertahan antar scan.

        State hasil scan pertama ikut ditulis ``ingest_many``; scan manual
        kedua pada bucket yang sama tidak boleh mengirim pesan kembar.
        """
        self._run_lp_scan(0.11, alert_state=_episode(0.05))
        self.assertEqual(len(self.sent), 1)
        state = ((self.store.get("tokens") or {}).get(LP_MINT) or {}).get(
            "alert_state") or {}
        events, _ = ta.evaluate_alert_events(
            LP_MINT, _analysis("LPRISK", 0.11), state)
        self.assertEqual(events, [], "event kembar lolos dedup bucket 5 menit")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
