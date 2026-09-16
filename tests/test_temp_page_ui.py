"""📦 TEMP — halaman penampungan UI yang dicabut dari 🏆 Best Pool (2026-09-16).

Permintaan user: *"🌊 Watchlist Meteora pindah ke page baru TEMP"* dan *"🛰 Scan
Holder Solana pindah ke page baru TEMP"*. Yang di-pin di sini:

- kedua blok itu benar-benar **pindah** (dirender ``pages/6_📦_TEMP.py``, tidak
  ada lagi di ``app.py``) dan halaman TEMP merender tanpa exception;
- kunci tombol lama dipertahankan apa adanya (``helius-scan-button``,
  ``lp-scan-now``, form ``lp-add-token``) karena status auto-refresh per-mint
  dan watchlist per-token dibaca dari kunci itu;
- ``temp_ui`` memanggil fungsi sumber **lewat modulnya** (``wl.add_to_watchlist``
  dst.) — ``app.py`` di-exec ulang tiap run AppTest tapi modul tetangga di-cache,
  jadi ``mock.patch("watchlist.add_to_watchlist")`` hanya kena kalau pemanggilnya
  tidak mengikat nama fungsi di module-level;
- 🏆 Scan Best Pool **tidak** ikut pindah: tombolnya tetap di ``app.py`` dan
  tidak muncul di TEMP.
"""
import ast
import re
import unittest
from pathlib import Path

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
TEMP = str(ROOT / "pages" / "6_📦_TEMP.py")


@unittest.skipIf(AppTest is None, "streamlit belum terpasang")
class TempPageTest(unittest.TestCase):
    def _at(self, page: str):
        at = AppTest.from_file(page, default_timeout=60)
        at.run()
        self.assertEqual(at.exception, [], f"{page} gagal render")
        return at

    def _texts(self, at) -> str:
        """Semua teks yang dirender (markdown/caption/title + label tombol)."""
        parts: list[str] = []
        for attr in ("markdown", "caption", "title", "header", "subheader",
                     "info", "warning", "error"):
            for item in getattr(at, attr, None) or []:
                parts.append(str(getattr(item, "value", "")))
        for button in at.button:
            parts.append(str(button.label or ""))
        return "\n".join(parts)

    def test_temp_page_merender_tanpa_exception(self):
        self._at(TEMP)   # assertion di dalam _at

    def test_kedua_blok_yang_pindah_muncul_di_temp(self):
        body = self._texts(self._at(TEMP))
        self.assertIn("🌊 Watchlist Meteora", body)
        self.assertIn("🛰 Scan Holder Solana", body)

    def test_kunci_tombol_lama_dipertahankan(self):
        """Status per-mint + form lama harus tetap dikenali tombolnya."""
        at = self._at(TEMP)
        keys = [button.key or "" for button in at.button]
        labels = [button.label or "" for button in at.button]
        # Kunci tombol + nama form dipindah apa adanya (ada tes lain yang
        # menekan tombol-tombol ini dan status auto-refresh per-mint dibaca
        # dari kunci yang sama).
        self.assertIn("lp-scan-now", keys)
        self.assertTrue(any(k.startswith("FormSubmitter:helius-holder-form-")
                            for k in keys), " ".join(keys))
        self.assertTrue(any(k.startswith("FormSubmitter:lp-add-token-")
                            for k in keys), " ".join(keys))
        self.assertIn("🛰 Scan Holder", labels)

    def test_temp_page_menyebut_asal_pindah_di_caption(self):
        """Caption halaman menjelaskan kedua card dipindah dari 🏆 Best Pool.

        Teks "🏆 Scan Best Pool" sendiri BOLEH muncul di TEMP (caption "belum
        ada helius_api_key" menyebut ketiga card), yang tidak boleh adalah card
        Best Pool-nya ikut dirender: judul card + tombol scan-nya.
        """
        at = self._at(TEMP)
        body = self._texts(at)
        self.assertIn("Card yang dipindah dari halaman utama", body)
        self.assertIn("🏆 Best Pool Meteora", body)
        self.assertNotIn("🏆 Scan Best Pool Meteora</span>", body)
        keys = [button.key or "" for button in at.button]
        labels = [button.label or "" for button in at.button]
        self.assertNotIn("best-pool-scan-24h", keys)
        self.assertNotIn("🏆 Scan Best Pool 24H + Holder", labels)

    def test_app_tidak_lagi_memilik_blok_yang_pindah(self):
        """Judul card yang pindah tidak boleh jadi kepala card di Home.

        Nama "🌊 Watchlist Meteora" / "🛰 Scan Holder Solana" **boleh** muncul di
        Home sebagai teks penjelasan (tooltip "⭐ memasukkan token ke card 🌊
        Watchlist Meteora di halaman 📦 TEMP" + caption kunci Helius) — yang
        tidak boleh adalah card-nya sendiri, jadi yang dibandingkan adalah
        markup judul (``…</span>``) + label/kunci tombolnya.
        """
        at = self._at(APP)
        body = self._texts(at)
        for title in ("🌊 Watchlist Meteora", "🛰 Scan Holder Solana"):
            self.assertNotIn(f"{title}</span>", body,
                             f"card {title} masih dirender di app.py")
        for label in ("🌊 Tambah ke Watchlist Meteora",
                      "🔄 Scan sekarang Watchlist Meteora", "🛰 Scan Holder"):
            self.assertNotIn(label, [button.label or "" for button in at.button],
                             f"tombol {label} masih di app.py")
        keys = [button.key or "" for button in at.button]
        self.assertNotIn("helius-scan-button", keys)
        self.assertNotIn("lp-scan-now", keys)
        self.assertFalse([k for k in keys
                          if k.startswith("FormSubmitter:lp-add-token-")],
                         "form ➕ watchlist Meteora masih di app.py")
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        for token in ("render_auto_refresh", "render_temp_page",
                      "import temp_ui"):
            self.assertNotIn(token, app_src,
                             f"{token} masih diimpor/dipanggil di app.py")

    def test_scan_best_pool_tetap_di_home(self):
        labels = [button.label or "" for button in self._at(APP).button]
        self.assertIn("🏆 Scan Best Pool 24H + Holder", labels)


class TempUiSourceTest(unittest.TestCase):
    """Kontrak non-UI yang bikin tes kartu LP bisa mem-patch modul sumber.

    ``temp_ui`` dipakai oleh ``pages/6_📦_TEMP.py``. Fungsi modul yang jadi
    target ``mock.patch("<modul>.<fungsi>")`` **wajib** dipanggil lewat
    modulnya (``wl.add_to_watchlist``), bukan ``from watchlist import
    add_to_watchlist``: ``app.py`` di-exec ulang setiap run AppTest sehingga
    from-import ikut melihat mock, tetapi modul tetangga di-cache antar-run —
    binding from-import membekukan fungsi asli dan patch jadi no-op.
    """

    #: modul → fungsi yang dipatch test DAN dipakai temp_ui
    QUALIFIED = {
        "watchlist": ("add_to_watchlist", "remove_from_watchlist",
                      "save_watchlist", "set_watchlist_source"),
        "holder_status": ("load_holder_status", "publish_holder_status"),
        "holder_history": ("holders_usable", "ingest_many"),
        "holder_analysis": ("analyze_token",),
        "meteora_screener": ("fetch_watchlist_metric_snapshots",),
        "meteora_watchlist": ("apply_metric_snapshots", "send_metric_alerts"),
        "alert_settings": ("mutes_for",),
        "lp_watchlist": ("lp_card_rows", "lp_summary", "split_watchlist"),
        "helius_holders": ("scan_token_holders",),
    }
    #: nama alias modul yang dipakai di temp_ui (wl = watchlist, dst.)
    ALIAS = {"watchlist": "wl", "holder_status": "hs", "holder_history": "hh"}

    def setUp(self):
        self.path = ROOT / "temp_ui.py"
        self.src = self.path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.src)
        self.imported: dict[str, set[str]] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                self.imported.setdefault(node.module, set()).update(
                    alias.name or alias.asname or alias.name
                    for alias in node.names)

    def test_fungsi_target_patch_tidak_diimpor_langsung(self):
        for module, names in self.QUALIFIED.items():
            bad = set(names) & self.imported.get(module, set())
            self.assertFalse(
                bad, f"{module} diimpor langsung ({sorted(bad)}) — patch "
                     f"mock ke modul sumber jadi no-op untuk halaman TEMP")

    def test_fungsi_target_patch_dipanggil_lewat_modul(self):
        for module, names in self.QUALIFIED.items():
            prefix = self.ALIAS.get(module, module)
            for name in names:
                with self.subTest(call=f"{prefix}.{name}"):
                    self.assertRegex(
                        self.src, rf"(?<![\w.]){prefix}\.{name}\(",
                        f"{prefix}.{name}() tidak pernah dipanggil di temp_ui")

    def test_temp_ui_tidak_mengimpor_app(self):
        """Halaman tidak boleh mengimpor ``app.py`` (di-exec ulang per route)."""
        self.assertIsNone(
            re.search(r"^\s*(from|import)\s+app\b", self.src, re.M),
            "temp_ui mengimpor app.py")


if __name__ == "__main__":
    unittest.main()
