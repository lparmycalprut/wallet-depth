# -*- coding: utf-8 -*-
"""AppTest: aksi Holder Analytic di card Watchlist Robinhood Chain.

Permintaan user 2026-09-05: setiap baris watchlist (Meteora maupun
Robinhood) punya tombol 🧮 yang membuka halaman Holder Analytic token itu,
dengan navigasi ``?mint=0x…`` yang dipahami halaman Holder (chain EVM).

Sejak 2026-09-06 aksinya tautan **tab baru** (``holder_analytic_link_html``),
bukan tombol ``st.switch_page``, supaya watchlist tidak ikut di-rerun. Tautan
itu wajib memakai **slug halaman** Streamlit (``/Holder``), bukan path file
(``pages/5_🧮_Holder.py``) — path file bukan route, jadi app jatuh ke
halaman utama dan token di URL tidak pernah dibaca. Ditambah dua jaminan:
target tautan = slug yang benar-benar dipakai Streamlit, dan router
``page_router`` memantulkan ``?mint=`` yang mendarat di halaman utama (tautan
lama yang sudah tersebar tetap berfungsi).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

from links import (HOLDER_PAGE_PATH, holder_analytic_url, page_url_path)

APP = str(Path(__file__).resolve().parent.parent / "app.py")

CA = "0x8490acd2d52d0ebd34cb13e01bd9a9380b36411d"
HOUR = 3600


def _point(ts: int, pct: float, count: int) -> dict:
    return {"ts": ts, "dust_count": count, "dust_pct_mc": pct,
            "price": 0.01, "mc": 100_000.0, "real_count": 40,
            "mid_count": 5, "holder_count": count + 40,
            "cohort_token_pct": 90.0, "cohort_n": 5}


@unittest.skipIf(AppTest is None, "streamlit not installed")
class RobinhoodCardHolderButtonTest(unittest.TestCase):
    def _status(self, holders=None, history=None):
        return {
            "updated_at": 6 * HOUR,
            "tokens": {CA: {
                "symbol": "VLAD", "price": 0.01, "marketcap": 100_000.0,
                "analyzed_at": 6 * HOUR,
                "holders": {"dust_count": 70, "dust_pct_mc": 0.55,
                            "real_count": 40, "total_fetched": 110,
                            "mid": {"count": 5, "pct_mc": 4.0}}
                if holders is None else holders,
                "history": [_point(2 * HOUR, 0.30, 50),
                            _point(6 * HOUR, 0.55, 70)]
                if history is None else history,
                "cohort": {"frozen_at": 2 * HOUR, "balances": {}},
            }},
        }

    def _history_store(self, points=None):
        return {"updated_at": 6 * HOUR,
                "tokens": {CA: {"symbol": "VLAD", "cohort": {},
                                "points": [_point(2 * HOUR, 0.30, 50),
                                           _point(6 * HOUR, 0.55, 70)]
                                if points is None else points}}}

    def _app(self, query_params=None, *, status=None, history_store=None):
        patches = (
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value={"tokens": {}}),
            # Backup durable store: tes tidak boleh menyentuh jaringan.
            mock.patch("holder_history.pull_holder_history", return_value=None),
            mock.patch("robinhood_watchlist.load_watchlist",
                       return_value={CA: {"symbol": "VLAD",
                                          "source": "manual"}}),
            mock.patch("robinhood_watchlist.load_status",
                       return_value=status or self._status()),
            mock.patch("robinhood_watchlist.load_history",
                       return_value=history_store or self._history_store()),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60)
        if query_params:
            app.query_params = dict(query_params)
        return app.run()

    def test_manual_watchlist_scan_uses_dedicated_full_coverage(self):
        import holder_history as hh
        with mock.patch("robinhood_watchlist.scan_watchlist", return_value={}) as scan:
            app = self._app()
            button = next(b for b in app.button
                          if b.label == "🔄 Scan holder watchlist Robinhood LP")
            button.click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(scan.call_args.kwargs["max_wallets"], hh.FULL_SCAN_MAX_WALLETS)

    def test_row_has_holder_analytic_link(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        # Judul card LP sejak 2026-09-10: "🦅 Watchlist Robinhood" (detail
        # karakteristik pindah ke tooltip judul, bukan caption panjang).
        self.assertIn("🦅 Watchlist Robinhood</span>", body)
        self.assertIn('title="Watchlist Robinhood LP (0x…, chain id 4663)',
                      body)
        captions = "\n".join(node.value for node in app.caption)
        self.assertNotIn("Pengingat ⚡ Telegram dikirim tiap ±5 menit per "
                         "token", captions)
        self.assertNotIn("Watchlist Robinhood LP — Holder Dust</span>", body)
        self.assertIn("$VLAD", body)
        # Aksi 🧮 = tautan tab baru ke SLUG halaman, bukan path file.
        self.assertIn(f'href="/Holder?mint={CA}"', body)
        self.assertIn('target="_blank"', body)
        self.assertNotIn("pages/5_🧮_Holder.py", body)
        keys = [button.key or "" for button in app.button]
        # tombol pindah card + hapus tetap ada di samping tautan holder
        self.assertIn(f"rh-move-{CA}", keys)
        self.assertIn(f"rh-remove-{CA}", keys)
        # token Solana kosong di test ini — tidak ada baris holder biasa
        self.assertFalse(any(k.startswith("holder-") for k in keys))

    def test_holder_link_targets_streamlit_page_slug(self):
        """Slug tautan harus sama dengan yang diberikan Streamlit ke file-nya.

        Streamlit mencocokkan URL dengan ``pathname.endsWith('/' + urlPathname)``
        (case-sensitive); kalau slugnya meleset, tautan membuka dashboard,
        bukan Holder Analytic — persis bug yang membuat ``?mint=`` "belum
        berfungsi".
        """
        url = holder_analytic_url(CA)
        self.assertEqual(url, f"/Holder?mint={CA}")
        self.assertTrue(url.startswith("/"))
        self.assertNotIn("pages/", url)
        try:
            from streamlit.source_util import page_icon_and_name
        except Exception:  # pragma: no cover - streamlit selalu ada di suite ini
            self.skipTest("streamlit tidak tersedia")
        real_slug = page_icon_and_name(Path(HOLDER_PAGE_PATH))[1]
        self.assertEqual(page_url_path(HOLDER_PAGE_PATH), real_slug)
        self.assertEqual(url.split("?", 1)[0], f"/{real_slug}")

    def test_main_page_routes_mint_query_to_holder(self):
        """Tautan lama (``pages/5_…py?mint=…``) mendarat di halaman utama.

        Halaman utama harus memantulkannya ke Holder Analytic dengan mint yang
        sama — bukan menampilkan dashboard kosong seperti sebelumnya.
        """
        with mock.patch("streamlit.switch_page") as switch:
            app = self._app(query_params={"mint": [CA]})
        self.assertEqual(len(app.exception), 0)
        switch.assert_called_once_with(
            HOLDER_PAGE_PATH, query_params={"mint": CA})
        # penanda sesi: deep link yang sama tidak dipantulkan berulang
        self.assertEqual(app.session_state["_deep_link_routed"],
                         (HOLDER_PAGE_PATH, CA))

    def _button(self, app, key: str):
        return next(node for node in app.button if (node.key or "") == key)

    def test_hapus_tombol_memakai_jalur_nonblocking(self):
        """✕ wajib memanggil penghapusan ``background=True``.

        Tanpa flag itu, satu klik menahan rerun Streamlit sampai commit GitHub
        selesai (terukur 2,4 s per klik pada RTT 0,8 dtk; bisa mendekati dua
        menit saat API melambat) — keluhan user: "kurang responsif".
        """
        app = self._app()
        with mock.patch(
                "robinhood_watchlist.remove_from_robinhood_watchlist",
                return_value=True) as remove:
            self._button(app, f"rh-remove-{CA}").click().run()
        self.assertEqual(len(app.exception), 0)
        remove.assert_called_once_with(CA, background=True)

    def test_pindah_card_memakai_jalur_nonblocking(self):
        app = self._app()
        with mock.patch(
                "robinhood_watchlist.set_robinhood_watchlist_source",
                return_value=True) as move:
            self._button(app, f"rh-move-{CA}").click().run()
        self.assertEqual(len(app.exception), 0)
        move.assert_called_once_with(
            "0x8490acd2d52d0ebd34cb13e01bd9a9380b36411d".lower(),
            "regular", background=True)

    def test_kadens_baris_menyebut_5_menit(self):
        """Baris + tooltip judul card harus menyebut kadens Robinhood.

        Sejak 2026-09-10 teks kadens card bukan caption lagi — pindah ke
        tooltip (``title="…"``) di teks judul card.
        """
        app = self._app()
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("LP · scan ±5 menit", body)
        self.assertIn('title="Watchlist Robinhood LP (0x…, chain id 4663)',
                      body)
        self.assertIn("tiap ±5 menit", body)
        self.assertNotIn("LP · scan ±15 menit", body)

    def test_badge_sinkronisasi_hanya_ketika_perlu(self):
        app = self._app()
        body = "\n".join(node.value for node in app.markdown)
        self.assertNotIn("sinkron…", body)

        with mock.patch("robinhood_watchlist.sync_state",
                       return_value={"state": "syncing", "ts": None,
                                     "msg": ""}):
            app = self._app()
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("🔄 sinkron…", body)

        with mock.patch("robinhood_watchlist.sync_state",
                       return_value={"state": "error", "ts": None,
                                     "msg": "GET 500"}):
            app = self._app()
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("⚠️ belum sinkron", body)

    def test_incomplete_scan_is_not_presented_as_result(self):
        """Scan RH yang pulang dengan 0 wallet harus bilang begitu di barisnya."""
        broken = {"dust_count": 0, "dust_pct_mc": 0.0, "real_count": 0,
                  "total_fetched": 0,
                  "fetch_error": "Blockscout getToken: 429 Too Many Requests"}
        app = self._app(status=self._status(holders=broken, history=[]),
                        history_store=self._history_store(points=[]))
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("⚠️ scan terakhir tidak lengkap", body)
        self.assertIn("429 Too Many Requests", body)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class RobinhoodPublishGuardTest(unittest.TestCase):
    """``publish_scan`` tidak menulis scan tidak layak ke snapshot dashboard."""

    def test_unusable_analysis_skipped_from_status(self):
        import robinhood_watchlist as rw

        broken = {"holders": {"total_fetched": 0, "wallets_analyzed": 0,
                              "dust_count": 0, "dust_pct_mc": 0.0}}
        good = {"holders": {"total_fetched": 300, "wallets_analyzed": 300,
                            "dust_count": 12, "dust_pct_mc": 0.7}}
        published = {}

        def fake_publish(analyses, *args, **kwargs):
            published["mint"] = dict(analyses)
            return {"updated_at": 1, "tokens": {}}

        store = {"updated_at": 0, "tokens": {}}
        with mock.patch.object(rw, "ingest_many", return_value=store), \
                mock.patch.object(rw, "publish_holder_status",
                                  side_effect=fake_publish):
            rw.publish_scan({"broken": broken, "good": good}, {},
                            history_store=store)
        self.assertIn("good", published["mint"])
        self.assertNotIn("broken", published["mint"])

    def test_all_can_be_published_when_usable(self):
        import robinhood_watchlist as rw

        good = {"holders": {"total_fetched": 300, "wallets_analyzed": 300,
                            "dust_count": 12, "dust_pct_mc": 0.7}}
        with mock.patch.object(rw, "ingest_many",
                                return_value={"tokens": {}}), \
                mock.patch.object(rw, "publish_holder_status",
                                  return_value={}) as publish:
            rw.publish_scan({"a": good}, {}, history_store={"tokens": {}})
        self.assertIn("a", publish.call_args[0][0])


@unittest.skipIf(AppTest is None, "streamlit not installed")
class HolderKhususRobinhoodScanTest(unittest.TestCase):
    """Section **Scan Holder Solana / Robinhood** (app.py) menerima CA Robinhood.

    Permintaan user 2026-09-08: "tambahkan fungsi kita bisa scan robinhood
    disini juga". CA EVM (0x…) → ``robinhood_holders.scan_token_holders``
    (Blockscout: CSV export → REST v2 → RPC) dengan shape hasil yang sama; CA
    Solana tetap → ``helius_holders.scan_token_holders`` (Helius DAS).
    """

    SOL_MINT = "So11111111111111111111111111111111111111112"

    @staticmethod
    def _depth_result(mint: str, symbol: str, source: str) -> dict:
        return {
            "mint": mint,
            "symbol": symbol,
            "market": {"price_usd": 1.0, "marketcap": 100_000.0},
            "snapshot": {"fetched": 3, "pages": 1, "truncated": False},
            "depth": {
                "buckets": [
                    {"label": ">$0-$10", "count": 1, "value_usd": 5.0,
                     "pct_mc": 0.005},
                    {"label": "$10-$100", "count": 0, "value_usd": 0.0,
                     "pct_mc": 0.0},
                    {"label": "$100-$1k", "count": 1, "value_usd": 500.0,
                     "pct_mc": 0.5},
                    {"label": "$1k-$10k", "count": 0, "value_usd": 0.0,
                     "pct_mc": 0.0},
                    {"label": "$10k-$100k", "count": 1, "value_usd": 90_000.0,
                     "pct_mc": 90.0},
                    {"label": "$100k-$500k", "count": 0, "value_usd": 0.0,
                     "pct_mc": 0.0},
                    {"label": ">$500k", "count": 0, "value_usd": 0.0,
                     "pct_mc": 0.0},
                ],
                "tiers": [],
                "holders_all": 3, "holders_wallet": 2, "pool_excluded": 1,
                "buckets_include_pools": False,
                "market_cap": 100_000.0,
            },
            "source": source,
            "no_helius_keys": False,
            "scan_failed": False,
        }

    def _app(self):
        patches = (
            mock.patch("watchlist.load_watchlist", return_value={}),
            mock.patch("holder_status.load_holder_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("holder_history.load_holder_history",
                       return_value={"tokens": {}}),
            mock.patch("holder_history.pull_holder_history",
                       return_value=None),
            mock.patch("robinhood_watchlist.load_watchlist",
                       return_value={}),
            mock.patch("robinhood_watchlist.load_status",
                       return_value={"updated_at": None, "tokens": {}}),
            mock.patch("robinhood_watchlist.load_history",
                       return_value={"updated_at": None, "tokens": {}}),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app = AppTest.from_file(APP, default_timeout=60)
        return app.run()

    def _submit(self, app, ca: str):
        inputs = [node for node in app.text_input
                  if node.key == "helius-ca-input"]
        self.assertTrue(inputs, "input CA Scan Holder tidak ditemukan")
        inputs[0].set_value(ca)
        submit = [button for button in app.button
                  if (button.label or "").strip() == "🛰 Scan Holder"]
        self.assertTrue(submit, "tombol Scan Holder tidak ditemukan")
        return submit[0].click().run()

    def test_robinhood_ca_routes_to_robinhood_scan(self):
        """CA 0x… → scan Robinhood (Blockscout), dirender label Robinhood."""
        app = self._app()
        ca_mixed = "0x" + CA[2:].upper()  # prefix 0x tetap lowercase
        with mock.patch("robinhood_holders.scan_token_holders",
                        return_value=self._depth_result(CA, "VLAD",
                                                        "blockscout-csv")) \
                as rh_scan, \
                mock.patch("helius_holders.scan_token_holders") as helius:
            result = self._submit(app, ca_mixed)
        self.assertEqual(len(result.exception), 0)
        helius.assert_not_called()
        rh_scan.assert_called_once()
        # EVM di-normalize (lowercase) sebelum scan
        self.assertEqual(rh_scan.call_args.args[0], CA.lower())
        self.assertEqual(rh_scan.call_args.kwargs["max_wallets"], 100_000)
        self.assertFalse(rh_scan.call_args.kwargs["include_pools"])

        body = "\n".join(node.value for node in result.markdown)
        metrics = "\n".join(m.label for m in result.metric)
        captions = "\n".join(node.value for node in result.caption)
        self.assertIn("$VLAD", body)
        self.assertIn("Akun holder (Blockscout)", metrics)
        self.assertNotIn("Helius", metrics)
        self.assertNotIn("GMGN", metrics)
        self.assertIn("Blockscout (Robinhood Chain)", captions)
        # tautan eksternal EVM (bukan GMGN/Solscan Solana)
        self.assertIn("rh-scan.com", body)
        self.assertIn("robinhoodchain.blockscout.com", body)

    def test_robinhood_ca_blockscout_source_label(self):
        """CSV terpotong → jalur RPC, label sumber tetap Blockscout."""
        app = self._app()
        with mock.patch("robinhood_holders.scan_token_holders",
                        return_value=self._depth_result(
                            CA, "VLAD", "blockscout-rpc")):
            result = self._submit(app, CA)
        metrics = "\n".join(m.label for m in result.metric)
        captions = "\n".join(node.value for node in result.caption)
        self.assertIn("Akun holder (Blockscout)", metrics)
        self.assertIn("Blockscout (Robinhood Chain)", captions)

    def test_robinhood_source_route_suffix_in_caption(self):
        """``blockscout-csv@pro`` → caption menyebut PRO API (2026-09-08)."""
        app = self._app()
        with mock.patch("robinhood_holders.scan_token_holders",
                        return_value=self._depth_result(
                            CA, "VLAD", "blockscout-csv@pro")):
            result = self._submit(app, CA)
        self.assertEqual(len(result.exception), 0)
        metrics = "\n".join(m.label for m in result.metric)
        captions = "\n".join(node.value for node in result.caption)
        self.assertIn("Akun holder (Blockscout)", metrics)
        self.assertIn("Blockscout (Robinhood Chain) · PRO API", captions)

    def test_robinhood_403_blocked_shows_api_key_hint(self):
        """Regresi 2026-09-08: 403 bot-protection Blockscout publik.

        Sebelumnya UI menulis "Scan tidak menghasilkan holder. Pastikan CA
        valid …" + tiga URL 403 — menyesatkan, CA-nya sah. Sekarang pesan
        menyebut 403 bot-protection dan cara memperbaikinya
        (``BLOCKSCOUT_API_KEY``), tanpa menyalahkan CA/harga.
        """
        app = self._app()
        failed = {
            "mint": CA, "symbol": "PUSHEEN",
            "market": {"price_usd": 0.001, "marketcap": 1_000.0,
                       "symbol": "PUSHEEN"},
            "snapshot": {
                "holders": [], "fetched": 0, "pages": 0, "truncated": False,
                "source": "blockscout-csv(fail)", "blocked": True,
                "error": ("Blockscout publik menolak request (HTTP 403 "
                          "bot-protection) di /api [cf-mitigated=challenge] "
                          "— pasang BLOCKSCOUT_API_KEY (key gratis: "
                          "https://dev.blockscout.com) agar scan lewat "
                          "PRO API"),
            },
            "depth": {"buckets": [], "tiers": [], "holders_all": 0,
                      "holders_wallet": 0, "pool_excluded": 0,
                      "buckets_include_pools": False, "market_cap": 1_000.0},
            "source": "blockscout-csv(fail)",
            "no_helius_keys": False,
            "scan_failed": True,
        }
        with mock.patch("robinhood_holders.scan_token_holders",
                        return_value=failed):
            result = self._submit(app, CA)
        self.assertEqual(len(result.exception), 0)
        errors = "\n".join(node.value for node in result.error)
        self.assertIn("HTTP 403", errors)
        self.assertIn("BLOCKSCOUT_API_KEY", errors)
        self.assertIn("dev.blockscout.com", errors)
        self.assertIn("bukan karena CA salah", errors)
        self.assertNotIn("Pastikan CA valid", errors)
        self.assertNotIn("Helius API key", errors)

    def test_robinhood_403_with_keys_points_to_dashboard_not_install(self):
        """Key PRO sudah ada tapi semua gagal → jangan suruh 'pasang key'."""
        app = self._app()
        failed = {
            "mint": CA, "symbol": "PUSHEEN",
            "market": {"price_usd": 0.001, "marketcap": 1_000.0,
                       "symbol": "PUSHEEN"},
            "snapshot": {
                "holders": [], "fetched": 0, "pages": 0, "truncated": False,
                "source": "blockscout-csv(fail)", "blocked": True,
                "pro_keys": 4, "pro_key": "",
                "error": ("Blockscout publik menolak request (HTTP 403 "
                          "bot-protection) di /api [PRO: PRO API 402 Out of "
                          "credits (key#4)] — key PRO API ada tetapi "
                          "semuanya ditolak / kreditnya habis"),
            },
            "depth": {"buckets": [], "tiers": [], "holders_all": 0,
                      "holders_wallet": 0, "pool_excluded": 0,
                      "buckets_include_pools": False, "market_cap": 1_000.0},
            "source": "blockscout-csv(fail)",
            "no_helius_keys": False,
            "scan_failed": True,
        }
        with mock.patch("robinhood_holders.scan_token_holders",
                        return_value=failed):
            result = self._submit(app, CA)
        self.assertEqual(len(result.exception), 0)
        errors = "\n".join(node.value for node in result.error)
        self.assertIn("HTTP 403", errors)
        self.assertIn("4 key PRO API terpasang", errors)
        self.assertIn("dev.blockscout.com", errors)
        self.assertIn("BLOCKSCOUT_API_KEYS", errors)
        self.assertNotIn("Pasang `BLOCKSCOUT_API_KEY`", errors)
        self.assertNotIn("Pastikan CA valid", errors)

    def test_robinhood_caption_shows_which_pro_key_was_used(self):
        app = self._app()
        ok = self._depth_result(CA, "VLAD", "blockscout-csv@pro")
        ok["snapshot"]["pro_key"] = "key#3"
        ok["snapshot"]["pro_keys"] = 4
        with mock.patch("robinhood_holders.scan_token_holders",
                        return_value=ok):
            result = self._submit(app, CA)
        self.assertEqual(len(result.exception), 0)
        captions = "\n".join(node.value for node in result.caption)
        self.assertIn("Blockscout (Robinhood Chain) · PRO API key#3", captions)

    def test_robinhood_generic_failure_keeps_old_message(self):
        """Kegagalan non-403 (mis. token belum di-index) → pesan lama."""
        app = self._app()
        failed = {
            "mint": CA, "symbol": "?",
            "market": {},
            "snapshot": {"holders": [], "fetched": 0, "pages": 0,
                         "truncated": False, "source": "blockscout-csv(fail)",
                         "blocked": False, "error": "price/address empty"},
            "depth": {"buckets": [], "tiers": [], "holders_all": 0,
                      "holders_wallet": 0, "pool_excluded": 0,
                      "buckets_include_pools": False, "market_cap": 0.0},
            "source": "blockscout-csv(fail)",
            "no_helius_keys": False,
            "scan_failed": True,
        }
        with mock.patch("robinhood_holders.scan_token_holders",
                        return_value=failed):
            result = self._submit(app, CA)
        errors = "\n".join(node.value for node in result.error)
        self.assertIn("Pastikan CA valid", errors)
        self.assertIn("price/address empty", errors)
        self.assertNotIn("HTTP 403", errors)

    def test_solana_ca_still_routes_to_helius(self):
        """CA base58 → Helius (perilaku lama tidak berubah)."""
        app = self._app()
        with mock.patch("helius_holders.scan_token_holders",
                        return_value=self._depth_result(
                            self.SOL_MINT, "USDC", "helius")) as helius, \
                mock.patch("robinhood_holders.scan_token_holders") as rh_scan:
            result = self._submit(app, self.SOL_MINT)
        self.assertEqual(len(result.exception), 0)
        rh_scan.assert_not_called()
        helius.assert_called_once()
        self.assertEqual(helius.call_args.args[0], self.SOL_MINT)
        metrics = "\n".join(m.label for m in result.metric)
        self.assertIn("Akun holder (Helius)", metrics)

    def test_invalid_ca_is_rejected(self):
        app = self._app()
        with mock.patch("robinhood_holders.scan_token_holders") as rh_scan, \
                mock.patch("helius_holders.scan_token_holders") as helius:
            result = self._submit(app, "0x123")
        self.assertEqual(len(result.exception), 0)
        rh_scan.assert_not_called()
        helius.assert_not_called()
        warnings = [w.value for w in result.warning]
        self.assertTrue(any("Format CA tidak valid" in w for w in warnings))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
