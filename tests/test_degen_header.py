# -*- coding: utf-8 -*-
"""🚨 Header "STOP DEGEN" di halaman utama (`app.py`).

Permintaan user (verbatim, 2026-09-17): *"tambahkan header di page app"* —
*"STOP DEGEN, GAK BISA / SUDAH KALAH BERTUBI2 AKUI KALAU KAMU GAK BISA"* —
*"merah menyala berkedip, tulisan besar, ada emoticon warning"*.

Yang di-pin di sini:

- header benar-benar dirender di halaman utama dan berada **di atas** card
  🏆 Scan Best Pool (posisi "header");
- kedua kalimat tampil **verbatim** (termasuk "BERTUBI2") + emoticon warning
  🚨/⚠️ di kiri-kanan tiap baris;
- gayanya = merah menyala (``#ff2d2d`` + glow) yang **berkedip** (animasi
  ``degen-stop-blink``/``degen-stop-glow`` + keyframes-nya ada di body) dan
  hurufnya **besar** (``clamp(…)``) — semuanya lewat CSS, bukan inline style,
  karena ``st.markdown`` men-sanitasi atribut ``style``;
- halaman lain (📦 TEMP) tidak ikut menampilkan header ini — user minta
  "di page app".
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
TEMP = str(ROOT / "pages" / "6_📦_TEMP.py")

import best_pool_ui as bp
import dashboard_components as dc
import meteora_screener as ms

BARIS_1 = "STOP DEGEN, GAK BISA"
BARIS_2 = "SUDAH KALAH BERTUBI2 AKUI KALAU KAMU GAK BISA"
# Penanda blok header (elemen HTML-nya, bukan selector CSS: CSS-nya ikut
# ter-render di semua halaman yang memanggil render_styles()).
HEADER_HTML = '<div class="degen-stop-header" role="alert">'
# Penanda card 🏆 Scan Best Pool — sama dengan pin tests/test_temp_page_ui.py.
CARD_MARK = ms.BEST_CARD_TITLE + "</span>"


def _body(at) -> str:
    """Semua markdown yang dirender (style + HTML header + card)."""
    return "\n".join(str(node.value) for node in at.markdown)


@unittest.skipIf(AppTest is None, "streamlit belum terpasang")
class DegenHeaderPageTest(unittest.TestCase):
    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist",
                       side_effect=lambda **_kw: {}),
            mock.patch("holder_status.load_holder_status",
                       side_effect=lambda **_kw: {"updated_at": None,
                                                  "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       side_effect=lambda *a, **kw: {"tokens": {}}),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=90).run()
        self.assertEqual(app.exception, [], "halaman utama gagal render")
        return app

    def test_header_terpasang_di_atas_card(self):
        """Header ada di halaman utama dan tampil sebelum card Best Pool."""
        body = _body(self._app())
        self.assertIn(HEADER_HTML, body)
        self.assertIn('role="alert"', body)      # ditandai peringatan
        self.assertLess(body.index(HEADER_HTML), body.index(CARD_MARK),
                        "header harus di ATAS card 🏆 Scan Best Pool")

    def test_dua_baris_verbatim_dengan_emoticon_warning(self):
        """Kalimat user dipin apa adanya (jangan dirapikan/diparafrase)."""
        body = _body(self._app())
        self.assertIn(BARIS_1, body)
        self.assertIn(BARIS_2, body)
        self.assertIn("🚨", body)                 # emoticon warning baris 1
        self.assertIn("⚠️", body)                # emoticon warning baris 2
        self.assertEqual(dc.DEGEN_STOP_LINES,
                         ((BARIS_1, "🚨"), (BARIS_2, "⚠️")))
        # Penanda kedua baris = satu class yang sama (gaya besar/berkedip).
        self.assertEqual(body.count('class="degen-stop-line"'), 2)

    def test_merah_menyala_berkedip_dan_besar(self):
        """Gaya 100% dari CSS `render_styles()` (bukan inline style)."""
        body = _body(self._app())
        for pin in ('class="degen-stop-line"', 'class="degen-stop-emoji"',
                    ".degen-stop-header", ".degen-stop-line",
                    "color:#ff2d2d",
                    "animation:degen-stop-blink 1s ease-in-out infinite",
                    "@keyframes degen-stop-blink",
                    "@keyframes degen-stop-glow",
                    # Huruf besar + skala turun di layar sempit.
                    "font-size:clamp(1.4rem,3.6vw,2.6rem)"):
            self.assertIn(pin, body)
        # Berkedipnya lewat opacity + glow, bukan cuma warna statis.
        self.assertIn("opacity:.3", body)
        self.assertIn("prefers-reduced-motion", body)

    def test_hanya_halaman_utama(self):
        """📦 TEMP (dan halaman lain) tidak ikut menampilkan header ini."""
        for page in ("pages/6_📦_TEMP.py", "pages/5_🧮_Holder.py"):
            self.assertNotIn("render_degen_stop_header",
                             (ROOT / page).read_text(encoding="utf-8"),
                             f"{page} tidak boleh memanggil header STOP DEGEN")
        temp = AppTest.from_file(TEMP, default_timeout=60).run()
        self.assertNotIn(HEADER_HTML, _body(temp))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
