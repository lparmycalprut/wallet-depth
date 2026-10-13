# -*- coding: utf-8 -*-
"""Alert Telegram page 🌊 Sweep (:mod:`sweep_alert`).

Dua hal yang dikunci: **urutan kredensial berlapis** (``st.secrets`` → env →
``config.json``, pilihan user 2026-10-12) dan **isi pesan** yang memuat angka
yang membuat alert berguna — bukan sekadar "ada sinyal".
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import sweep_alert as alert


class CredentialTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sweep-alert-")
        self.config = os.path.join(self.dir, "config.json")
        for target, value in (("CONFIG_PATH", self.config),
                              ("ENV_TOKEN", alert.ENV_TOKEN),
                              ("ENV_CHAT", alert.ENV_CHAT)):
            patcher = mock.patch.object(alert, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write_config(self, data):
        with open(self.config, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_secrets_wins_over_env_and_config(self):
        self._write_config({"TELEGRAM_BOT_TOKEN": "cfg", "TELEGRAM_CHAT_ID": "cfg"})
        with mock.patch.object(alert, "_from_secrets",
                               return_value=("sec", "sec")), \
                mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env",
                                             "TELEGRAM_CHAT_ID": "env"}):
            cfg = alert.telegram_config()
        self.assertEqual((cfg["token"], cfg["chat_id"]), ("sec", "sec"))
        self.assertEqual(cfg["source"], alert.SOURCE_SECRETS)
        self.assertTrue(cfg["ok"])

    def test_env_wins_over_config(self):
        self._write_config({"TELEGRAM_BOT_TOKEN": "cfg", "TELEGRAM_CHAT_ID": "cfg"})
        with mock.patch.object(alert, "_from_secrets", return_value=("", "")), \
                mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env",
                                             "TELEGRAM_CHAT_ID": "env"}):
            cfg = alert.telegram_config()
        self.assertEqual(cfg["token"], "env")
        self.assertEqual(cfg["source"], alert.SOURCE_ENV)

    def test_config_is_last_resort(self):
        self._write_config({"TELEGRAM_BOT_TOKEN": "cfg-token",
                            "TELEGRAM_CHAT_ID": "cfg-chat"})
        with mock.patch.object(alert, "_from_secrets", return_value=("", "")), \
                mock.patch.dict(os.environ, {}, clear=True):
            cfg = alert.telegram_config()
        self.assertEqual((cfg["token"], cfg["chat_id"]),
                         ("cfg-token", "cfg-chat"))
        self.assertEqual(cfg["source"], alert.SOURCE_CONFIG)

    def test_snake_case_keys_also_accepted(self):
        self._write_config({"telegram_bot_token": "low",
                            "telegram_chat_id": "low-chat"})
        with mock.patch.object(alert, "_from_secrets", return_value=("", "")), \
                mock.patch.dict(os.environ, {}, clear=True):
            cfg = alert.telegram_config()
        self.assertEqual((cfg["token"], cfg["chat_id"]), ("low", "low-chat"))

    def test_not_configured(self):
        with mock.patch.object(alert, "_from_secrets", return_value=("", "")), \
                mock.patch.dict(os.environ, {}, clear=True):
            cfg = alert.telegram_config()
        self.assertFalse(cfg["ok"])
        self.assertEqual(cfg["source"], alert.SOURCE_NONE)

    def test_partial_credentials_are_not_ok(self):
        with mock.patch.object(alert, "_from_secrets",
                               return_value=("only-token", "")), \
                mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(alert.telegram_config()["ok"])

    def test_muted_mints_from_config(self):
        self._write_config({"sweep_muted_mints": ["A", "", "B"]})
        self.assertEqual(alert.muted_mints(), {"A", "B"})
        self.assertEqual(alert.muted_mints(), {"A", "B"})


class SendMessageTest(unittest.TestCase):
    def test_without_credentials(self):
        with mock.patch.object(alert, "telegram_config",
                               return_value={"ok": False, "token": "",
                                             "chat_id": "", "source": "—"}):
            sent, error = alert.send_message("hai")
        self.assertFalse(sent)
        self.assertIn("belum dipasang", error)

    def test_empty_text_rejected(self):
        cfg = {"ok": True, "token": "t", "chat_id": "c", "source": "env"}
        self.assertFalse(alert.send_message("   ", config=cfg)[0])

    def test_posts_to_telegram(self):
        posted = {}

        class _Response:
            status_code = 200
            text = "ok"

        class _Requests:
            @staticmethod
            def post(url, data=None, headers=None, timeout=None):
                posted["url"] = url
                posted["payload"] = json.loads(data.decode("utf-8"))
                return _Response()

        cfg = {"ok": True, "token": "TOKEN123", "chat_id": "CHAT9",
               "source": "env"}
        with mock.patch.dict("sys.modules", {"requests": _Requests()}):
            sent, error = alert.send_message("halo", config=cfg)
        self.assertTrue(sent, error)
        self.assertIn("botTOKEN123/sendMessage", posted["url"])
        self.assertEqual(posted["payload"]["chat_id"], "CHAT9")
        self.assertEqual(posted["payload"]["text"], "halo")

    def test_http_error_reported(self):
        class _Response:
            status_code = 400
            text = "bad request"

        class _Requests:
            @staticmethod
            def post(url, data=None, headers=None, timeout=None):
                return _Response()

        cfg = {"ok": True, "token": "t", "chat_id": "c", "source": "env"}
        with mock.patch.dict("sys.modules", {"requests": _Requests()}):
            sent, error = alert.send_message("halo", config=cfg)
        self.assertFalse(sent)
        self.assertIn("400", error)


class MessageFormatTest(unittest.TestCase):
    def _metrics(self):
        return {
            "symbol": "COCKROACH", "price_usd": 0.00023768309790897773,
            "liq_usd": 30232.0, "fdv_usd": 233451.0,
            "top10_holder_pct": 18.92,
            "holder_count": 3609, "bundler_rate": 0.1764,
            "bot_degen_rate": 0.4551, "entrapment_rate": 0.3222,
        }

    def test_eligibility_message_has_verdict_and_formula(self):
        import sweep_screen as screen
        metrics = self._metrics()
        result = screen.evaluate(metrics, snapshots=[], candles=[])
        text = alert.format_eligibility("MINT123", metrics, result)
        self.assertIn("KELAYAKAN SWEEP", text)
        self.assertIn("COCKROACH", text)
        self.assertIn("liq/MC: 13.0%", text)
        self.assertNotIn("LP locked", text)
        self.assertIn("top-10 18.9%", text)
        self.assertIn("Bundler 17.6%", text)
        self.assertIn("bot degen 45.5%", text)
        # Tabel biaya sweep ikut dikirim karena liq/MC diketahui.
        self.assertIn("Biaya sweep:", text)
                # (akar(10)-1) x 12,95% = 27,99% → 28%
        self.assertIn("10x≈14%MC", text)
        self.assertIn("https://gmgn.ai/sol/token/MINT123", text)

    def test_eligibility_message_lists_missing_data(self):
        import sweep_screen as screen
        metrics = self._metrics()
        result = screen.evaluate(metrics, snapshots=[], candles=[])
        text = alert.format_eligibility("MINT123", metrics, result)
        self.assertIn("Data kurang:", text)
        self.assertIn("absorption", text)

    def test_sweep_message_separates_theory_from_measurement(self):
        # Context dengan angka PEAK-based (bukan close-based)
        base_price = 0.00023768309790897773
        mc_base = 233451.0  # MC di harga dasar (untuk %MC calculation)
        context = {
            "vol_x": 1189.6, "vol": 1242746.0,
            "base_price": base_price,
            "peak": 0.0020603307226025585,
            "close": 0.0007667356548390803,
            "price_mult": 3.2256, "peak_mult": 8.669,
            "liq_mc": 0.1295, "leverage": 60.9,
            "est_cost_usd": 29389.0, "est_cost_close_usd": 12033.5,
            "paper_gain_usd": 1790194.0, "paper_mcap_usd": 752939.0,
            "base_mcap_usd": mc_base,  # untuk %MC calculation
            "net_inflow_usd": 29389.0, "churn_x": 42.3,
            "churn_net_x": 42.3, "bars_ago": 0,
        }
        text = alert.format_sweep("MINT123", self._metrics(), context)
        self.assertIn("SWEEP TERDETEKSI", text)
        self.assertIn("1189.6x median", text)
        self.assertIn("Biaya dorong ke puncak (akar m − 1) × liq/2 (uang quote masuk): $29,389", text)
        self.assertIn("12.6% dari MC", text)
        self.assertIn("MC kertas yang naik: $1,790,194 → leverage 60.9x", text)
        self.assertIn("leverage 60.9x", text)
        self.assertIn("Paper MC di close (besaran lain, bukan pembilang leverage): $752,939", text)
        self.assertIn("Inflow nyata (Δ likuiditas ÷ 2): $29,389", text)
        self.assertIn("1.0x biaya dorong ke puncak", text)
        self.assertIn("Churn 42.3x", text)
        self.assertIn("Churn nyata 42.3x", text)
        self.assertIn("tidak ada pembeli luar bersih", text)
        self.assertIn("retrace 11/12 kali", text)
        self.assertIn("https://gmgn.ai/sol/token/MINT123", text)

    def test_sweep_message_uses_calibration_when_unmeasured(self):
        # Tanpa snapshot pembanding: inflow teoretis ditandai sebagai acuan
        # 1 event, bukan dipresentasikan sebagai pengukuran.
        context = {"vol_x": 25.0, "vol": 1000.0, "base_price": 1.0,
                   "close": 1.6, "price_mult": 1.6, "est_cost_usd": 100.0,
                   "net_inflow_ref_usd": 100.0, "net_inflow_usd": None,
                   "churn_x": 10.0, "churn_net_x": None}
        text = alert.format_sweep("MINT123", self._metrics(), context)
        self.assertIn("Perkiraan inflow", text)
        self.assertIn("belum ada snapshot pembanding", text)
        self.assertIn("acuan kalibrasi 1 event", text)
        self.assertIn("$100", text)
        self.assertNotIn("Inflow nyata", text)

    def test_sweep_message_without_liq_mc_omits_formula(self):
        text = alert.format_sweep("M", {"symbol": "X"},
                                  {"vol_x": 25.0, "vol": 1000.0,
                                   "base_price": 1.0, "close": 1.6,
                                   "price_mult": 1.6})
        self.assertIn("SWEEP TERDETEKSI", text)
        self.assertNotIn("Biaya dorong ke puncak", text)
        self.assertNotIn("paper_mcap_usd", text)
        self.assertNotIn("churn_x", text)

    def test_test_message(self):
        self.assertIn("Test alert", alert.format_test())


if __name__ == "__main__":
    unittest.main()
