"""Telegram alert untuk 3 sinyal bottom (format §6)."""
import unittest

from signals import format_effort_alert, should_send_telegram


def _result(signal, **overrides):
    result = {
        "mint": "Mint123", "date": "2026-07-16", "previous_date": "2026-07-15",
        "signal": signal, "bias": "bullish",
        "price_chg_pct": -47.1, "cvd_delta": -15.4,
        "volume_pct": 28.0, "flush_date": "2026-07-10",
        "flush_cvd": -946.0, "collapse_pct": 1.6,
        "flag_divergence": False, "whale_driven": False,
        "status": "signal",
    }
    result.update(overrides)
    return result


class BottomAlertFormatTest(unittest.TestCase):
    def test_seller_exhaustion_format(self):
        text = format_effort_alert("HOPPY", _result("SELLER_EXHAUSTION"))
        self.assertIn("BOTTOM TERDETEKSI", text)
        self.assertIn("$HOPPY", text)
        self.assertIn("🟢 SELLER EXHAUSTION", text)
        self.assertIn("Hari: 2026-07-16 (flush 2026-07-10)", text)
        self.assertIn("CVD: -15.4 SOL | Volume: 28% dari kemarin", text)
        self.assertIn(
            '<a href="https://gmgn.ai/sol/token/Mint123">GMGN</a>', text)
        self.assertNotIn("https://dexscreener.com", text)

    def test_reversal_format(self):
        text = format_effort_alert("GRAIL", _result(
            "REVERSAL", date="2026-06-28", flush_date="2026-06-26",
            cvd_delta=-36.0, volume_pct=131.0, price_chg_pct=-18.3))
        self.assertIn("🟣 REVERSAL", text)
        self.assertIn("(flush 2026-06-26)", text)
        self.assertIn("Volume: 131% dari kemarin", text)

    def test_akumulasi_format(self):
        # AKUMULASI tidak punya flush → segmen flush dihilangkan.
        text = format_effort_alert("PUNCH", _result(
            "AKUMULASI", date="2025-12-25", flush_date=None,
            cvd_delta=72.2, volume_pct=140.0, price_chg_pct=-1.0))
        self.assertIn("🔵 AKUMULASI", text)
        self.assertIn("Hari: 2025-12-25\n", text)
        self.assertNotIn("flush", text.lower())
        self.assertIn("CVD: +72.2 SOL | Volume: 140% dari kemarin", text)

    def test_symbol_escaped_and_uppercased(self):
        text = format_effort_alert("a<b>", _result("SELLER_EXHAUSTION"))
        self.assertIn("$A&lt;B&gt;", text)


class TelegramGateTest(unittest.TestCase):
    def test_only_three_bottom_signals_send(self):
        for signal in ("SELLER_EXHAUSTION", "REVERSAL", "AKUMULASI"):
            self.assertTrue(should_send_telegram(_result(signal)), signal)

    def test_dash_and_legacy_signals_never_send(self):
        self.assertFalse(should_send_telegram(_result("—", status="no_signal")))
        self.assertFalse(should_send_telegram({"signal": "—"}))
        # sinyal generasi lama tidak boleh pernah terkirim lagi
        for legacy in ("S1_PENYERAPAN", "S2_DUMP_DISTRIBUSI",
                       "S3_DISTRIBUSI_KE_KUAT", "S4_PUMP_ASLI", "S5_NETRAL",
                       "ABSORBSI_LANGSUNG", "SELLING_EXHAUSTION"):
            self.assertFalse(should_send_telegram({"signal": legacy}), legacy)

    def test_signal_without_date_does_not_send(self):
        self.assertFalse(should_send_telegram(
            _result("SELLER_EXHAUSTION", date=None)))
        self.assertFalse(should_send_telegram(
            _result("REVERSAL", date="")))


if __name__ == "__main__":
    unittest.main()
