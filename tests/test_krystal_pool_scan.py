"""Coverage 🦅 Scan Best Pool Krystal (Robinhood Chain 4663, rule F/V 24H).

Card ini **menyalin** rule 🏆 Scan Best Pool Meteora, jadi yang di-pin di sini:

- **normalisasi payload Krystal** (``cloud-api.krystal.app/v1/pools``): F =
  fee 24 jam ÷ TVL × 100, volume/TVL, pasangan token, protokol, alamat pool;
  pool tanpa sisi token (quote-only) dibuang sebelum holder;
- **V = (max high − min low) ÷ min low × 100** dari 24 candle hourly pool
  GeckoTerminal network **robinhood** (``core.get_hourly_candles(network=…)``);
  pool tanpa candle = *volatility tidak tersedia* (bukan 0);
- **gate 24H**: ``F/V ≥ 5×`` (inklusif — tepat 5× lolos, 4,9× gugur),
  V persis 0 → gugur **dan dibuang dari listing** (∞ bukan kelolosan), metrik
  hilang/nonfinite/negatif → gugur "metrik tidak tersedia";
- **urutan baris**: F/V terbesar → volume/TVL terbesar → dust %MC terkecil;
- **UI**: border container, 4 kolom inti di depan (Token, F/V, Volat,
  Dust %MC), sorot hijau menyala (F/V tertinggi + volatility terbesar), ⭐ →
  Watchlist Robinhood LP, detail rule di **tooltip judul** (bukan caption);
- **persistensi**: hasil scan tersimpan ke cache berkas
  (``scan_result_cache``) dan dipulihkan saat ``session_state`` kosong, jadi
  refresh browser tidak menghilangkan tabel.
"""
from __future__ import annotations

import html
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scan_result_cache

try:  # optional dev dependency
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001
    AppTest = None

import core
import krystal_pool_ui as kp
import krystal_screener as ks

APP = str(Path(__file__).resolve().parent.parent / "app.py")
WETH = "0x4200000000000000000000000000000000000006"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TOKEN_A = "0xaaaa000000000000000000000000000000000001"
TOKEN_B = "0xbbbb000000000000000000000000000000000002"
POOL_A = "0x1111000000000000000000000000000000000001"
POOL_B = "0x2222000000000000000000000000000000000002"
POOL_C = "0x3333000000000000000000000000000000000003"


def _token(address, symbol, name=None, decimals=18):
    return {"address": address, "symbol": symbol,
            "name": name or symbol, "decimals": decimals,
            "logo": "https://example/logo.png"}


def _pool(pool_address=POOL_A, base=TOKEN_A, quote=WETH,
          base_symbol="TOK", quote_symbol="WETH", *, tvl=100_000.0,
          fee=1_000.0, volume=250_000.0, apr=18.5, protocol="uniswapv3",
          fee_tier=500):
    """Satu payload ``GET /v1/pools`` Krystal (bentuk terdokumentasi swagger).

    Angka default sengaja sederhana: F = 1.000 / 100.000 × 100 = **1,0%**,
    volume/TVL = 250.000 / 100.000 × 100 = **250%**.
    """
    return {
        "chainId": ks.KRYSTAL_CHAIN_PARAM,
        "poolAddress": pool_address,
        "poolPrice": "1234567890",
        "protocol": {"name": protocol, "factoryAddress": "0xfactory"},
        "feeTier": fee_tier,
        "token0": _token(base, base_symbol),
        "token1": _token(quote, quote_symbol),
        "tvl": str(tvl),
        "stats1h": {"volume": "1000.5", "fee": "10.5", "apr": 12.25},
        "stats24h": {"volume": str(volume), "fee": str(fee), "apr": apr},
        "stats7d": {"volume": "900000.0", "fee": "9000.0", "apr": 21.5},
        "stats30d": {"volume": "3000000.0", "fee": "30000.0", "apr": 19.25},
    }


def _row(**over):
    """Baris lolos gate 24H: F = 10,0% dan V = 1,0% → F/V = 10×."""
    row = {
        "source": "krystal", "timeframe": "24h",
        "chain": ks.KRYSTAL_CHAIN_PARAM,
        "pool_address": POOL_A, "protocol": "uniswapv3",
        "protocol_label": "Uniswap V3", "fee_tier": 500.0,
        "ca": TOKEN_A, "symbol": "TOK", "base_symbol": "TOK",
        "quote_symbol": "WETH", "pair": "TOK/WETH", "quote_address": WETH,
        "quote_only": False,
        "tvl": 100_000.0, "fee": 10_000.0, "volume": 250_000.0, "apr": 18.5,
        "fee_tvl_ratio": 10.0, "vol_tvl_ratio": 250.0,
        "volatility": 1.0, "volatility_candles": 24, "volatility_note": "",
        "mc": 1_000_000.0, "price": 0.01,
        "analysis": _proof(0.03), "dust_pct_mc": 0.03, "dust_count": 12,
        "real_count": 1_090, "holders_proof": True, "holders_note": "",
    }
    row.update(over)
    return row


def _proof(pct, dust_count=5):
    """``analysis.holders`` hasil scan FULL yang **membuktikan** angkanya."""
    return {"marketcap": 1_000_000.0, "price": 0.01,
            "holders": {"dust_pct_mc": pct, "dust_count": dust_count,
                        "real_count": 1_095, "total_fetched": 1_200,
                        "wallets_analyzed": 1_100}}


def _fv(fee_ratio, volatility):
    return {"fee_tvl_ratio": fee_ratio, "volatility": volatility}


def _candles(*rows):
    return [{"ts": 1000 + index * 3600, "open": low, "high": high,
             "low": low, "close": low, "volume_usd": 100.0}
            for index, (high, low) in enumerate(rows)]


def _isolate_cache(case) -> Path:
    """Arahkan cache hasil scan ke direktori sementara milik tes ini.

    Runner pytest sudah memasang fixture ``_iso_scan_cache``, tetapi
    ``python -m unittest discover tests`` mematikan cache
    (``tests/__init__.py``), jadi tes yang menguji persistensi menyiapkan
    direktorinya sendiri — hasilnya sama di dua runner.
    """
    tmp = tempfile.TemporaryDirectory(prefix="krystal-cache-")
    case.addCleanup(tmp.cleanup)
    previous = {name: os.environ.get(name)
                for name in ("SCAN_CACHE", "SCAN_CACHE_DIR")}

    def _restore():
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    case.addCleanup(_restore)
    os.environ["SCAN_CACHE"] = "1"
    os.environ["SCAN_CACHE_DIR"] = tmp.name
    return Path(tmp.name)


class PayloadTest(unittest.TestCase):
    """Normalisasi payload Krystal → baris tabel."""

    def test_field_utama_terbaca(self):
        row = ks.normalize_pool(_pool(), protocol="uniswapv3")
        self.assertEqual(row["pool_address"], POOL_A)
        self.assertEqual(row["protocol"], "uniswapv3")
        self.assertEqual(row["protocol_label"], "Uniswap V3")
        self.assertEqual(row["fee_tier"], 500.0)
        # Sisi token: base = bukan WETH/USDG/stable → token0 di contoh ini.
        self.assertEqual(row["ca"], TOKEN_A)
        self.assertEqual(row["symbol"], "TOK")
        self.assertEqual(row["quote_symbol"], "WETH")
        self.assertEqual(row["pair"], "TOK/WETH")
        self.assertEqual(row["timeframe"], "24h")
        self.assertEqual(row["source"], "krystal")

    def test_f_dan_volume_tvl_dihitung_dari_field_krystal(self):
        row = ks.normalize_pool(_pool(tvl=100_000.0, fee=1_000.0,
                                      volume=250_000.0))
        # F = fee 24 jam / TVL x 100 = 1,0
        self.assertAlmostEqual(row["fee_tvl_ratio"], 1.0)
        self.assertAlmostEqual(row["vol_tvl_ratio"], 250.0)
        self.assertAlmostEqual(row["apr"], 18.5)
        # Field jendela lain (1h/7d/30d) tidak boleh dipakai untuk F.
        self.assertAlmostEqual(row["fee"], 1_000.0)
        self.assertAlmostEqual(row["volume"], 250_000.0)

    def test_metrik_hilang_jadi_none_bukan_nol(self):
        """TVL/fee tidak terbaca → F ``None`` (gugur "metrik tidak tersedia")."""
        row = ks.normalize_pool({"poolAddress": POOL_A,
                                 "token0": _token(TOKEN_A, "TOK")})
        self.assertIsNone(row["tvl"])
        self.assertIsNone(row["fee_tvl_ratio"])
        self.assertIsNone(row["vol_tvl_ratio"])
        self.assertEqual(ks.row_krystal_gaps(row), ["metrik tidak tersedia"])

    def test_base_token_dipilih_bukan_sisi_quote(self):
        """token0 = WETH, token1 = TOK → base-nya TOK (bukan stable/WETH)."""
        row = ks.normalize_pool(_pool(base=WETH, quote=TOKEN_A,
                                      base_symbol="WETH",
                                      quote_symbol="TOK"))
        self.assertEqual(row["ca"], TOKEN_A)
        self.assertEqual(row["symbol"], "TOK")
        self.assertEqual(row["quote_symbol"], "WETH")

    def test_pool_quote_only_dibuang(self):
        rows = ks.rows_from_pools([
            _pool(POOL_A, base=WETH, quote=USDG, base_symbol="WETH",
                  quote_symbol="USDG"),
            _pool(POOL_B, base=TOKEN_B, quote=WETH, base_symbol="TOKB"),
        ])
        kept, dropped = ks.drop_quote_rows(rows)
        self.assertEqual(dropped, 1)
        self.assertEqual([row["pool_address"] for row in kept], [POOL_B])
        self.assertIn("quote-only", ks.unanalysable_row(rows[0]))
        self.assertEqual(ks.unanalysable_row(rows[1]), "")

    def test_pool_tanpa_alamat_token_dibuang(self):
        row = ks.normalize_pool({"poolAddress": POOL_A, "token1": {}})
        self.assertEqual(ks.unanalysable_row(row),
                         "mint token base tidak terbaca")

    def test_dedup_per_alamat_pool(self):
        rows = ks.rows_from_pools([_pool(POOL_A), _pool(POOL_A), _pool(POOL_B)])
        self.assertEqual([row["pool_address"] for row in rows],
                         [POOL_A, POOL_B])

    def test_payload_rusak_tidak_merender_eksception(self):
        """Baris bukan dict dilewati; dict kosong tetap jadi baris tanpa metrik."""
        rows = ks.rows_from_pools([None, "rusak", {}, 42])
        self.assertEqual(len(rows), 1)
        self.assertEqual(ks.row_krystal_gaps(rows[0]),
                         ["metrik tidak tersedia"])

    def test_variasi_nama_field_statistik(self):
        """Field jendela toleran: ``stats24h`` / ``stats_24h`` / ``24h``."""
        for name in ("stats24h", "stats_24h", "24h"):
            with self.subTest(name=name):
                pool = _pool()
                pool.pop("stats24h")
                pool[name] = {"volume": "2000", "fee": "20", "apr": 5.0}
                row = ks.normalize_pool(pool)
                self.assertAlmostEqual(row["fee"], 20.0)
                self.assertAlmostEqual(row["volume"], 2000.0)

    def test_label_protokol(self):
        self.assertEqual(ks.protocol_label("ramsescl"), "Ramses CL")
        self.assertEqual(ks.protocol_label("uniswapv4"), "Uniswap V4")
        self.assertEqual(ks.protocol_label(""), "?")


class GateTest(unittest.TestCase):
    """Gate 24H: F/V ≥ 5× inklusif; V=0 dibuang; metrik hilang gugur."""

    def test_konstanta_dan_label(self):
        self.assertEqual(ks.KRYSTAL_FV_24H_MIN, 5.0)
        self.assertEqual(ks.KRYSTAL_LANES, ("24h",))
        self.assertEqual(ks.KRYSTAL_CHAIN_ID, 4663)
        self.assertEqual(ks.KRYSTAL_CHAIN_PARAM, "robinhood@4663")
        self.assertEqual(ks.KRYSTAL_PROTOCOLS,
                         ("ramsescl", "uniswapv2", "uniswapv3", "uniswapv4"))
        self.assertTrue(ks.lane_fv_inclusive("24h"))
        self.assertEqual(ks.lane_fv_sign("24h"), "≥")
        self.assertEqual(ks.krystal_lane_gate_label("24h"), "24H: F/V ≥ 5×")
        with mock.patch.object(ks, "KRYSTAL_FV_24H_MIN", 7.0):
            self.assertEqual(ks.krystal_lane_gate_label("24h"),
                             "24H: F/V ≥ 7×")

    def test_lolos_tepat_lima_kali(self):
        """Tepat 5× lolos (inklusif) — batasnya eksak, bukan "kira-kira 5"."""
        row = _row(**_fv(50.0, 10.0))
        self.assertAlmostEqual(ks.row_fv_ratio(row), 5.0)
        self.assertEqual(ks.row_krystal_gaps(row), [])

    def test_empat_koma_sembilan_gugur(self):
        self.assertEqual(ks.row_krystal_gaps(_row(**_fv(49.0, 10.0))),
                         ["24H: F/V < 5×"])

    def test_volatility_nol_gugur_dan_dibuang(self):
        row = _row(**_fv(10.0, 0))
        self.assertEqual(ks.row_krystal_gaps(row),
                         ["24H: volatility 0 — F/V tidak terukur"])
        self.assertTrue(ks.row_volatility_zero(row))
        # Dibuang total: tidak masuk "dilewati" dan tidak dihitung.
        self.assertEqual(ks.filter_krystal_rows([row]), ([], 0))
        # ∞ bukan kelolosan walau fee besar.
        with mock.patch.object(ks, "KRYSTAL_FV_24H_MIN", 0.0):
            self.assertNotEqual(ks.row_krystal_gaps(row), [])
        # None/negatif/nonfinite bukan nol → tetap masuk "dilewati".
        self.assertFalse(ks.row_volatility_zero(_row(volatility=None)))
        self.assertFalse(ks.row_volatility_zero(_row(volatility=-0.01)))
        self.assertFalse(ks.row_volatility_zero(
            _row(volatility=float("nan"))))

    def test_metrik_hilang_atau_tidak_valid_gugur(self):
        for payload in (_fv(None, 1.0), _fv(10.0, None), _fv(10.0, -1.0),
                        _fv(-1.0, 1.0), _fv(float("nan"), 1.0)):
            with self.subTest(payload=payload):
                self.assertEqual(ks.row_krystal_gaps(_row(**payload)),
                                 ["metrik tidak tersedia"])

    def test_lane_tidak_dikenal(self):
        self.assertEqual(ks.row_krystal_gaps(_row(), lane="30m"),
                         ["timeframe tidak dikenal"])
        self.assertIsNone(ks.normalize_krystal_lane("5m", default=None))

    def test_row_fv_ratio_inf_dan_none(self):
        self.assertIsNone(ks.row_fv_ratio(None))
        self.assertEqual(ks.row_fv_ratio(_fv(5.0, 0)), float("inf"))
        self.assertEqual(ks.row_fv_ratio(_fv(0.0, 0)), 0.0)
        self.assertAlmostEqual(ks.row_fv_ratio(_fv(40.0, 8.0)), 5.0)


class VolatilityTest(unittest.TestCase):
    """V = (max high − min low) ÷ min low × 100 dari candle hourly."""

    def test_rumus_range(self):
        # high tertinggi 1,50 · low terendah 1,00 → (1,5-1,0)/1,0 x 100 = 50%
        value, count = ks.volatility_from_candles(
            _candles((1.2, 1.0), (1.5, 1.1), (1.3, 1.05)))
        self.assertAlmostEqual(value, 50.0)
        self.assertEqual(count, 3)

    def test_satu_candle_diukur_dua_titik_ekstrem(self):
        value, count = ks.volatility_from_candles(_candles((1.1, 1.0)))
        self.assertAlmostEqual(value, 10.0)
        self.assertEqual(count, 1)

    def test_tanpa_candle_volatility_tidak_tersedia(self):
        """Pool tanpa candle = tidak tahu, BUKAN 0% (0% = klaim tidak
        ada pergerakan yang tidak bisa dibuktikan)."""
        for candles in ([], None, [{"ts": 1, "close": 1.0}],
                        [{"high": None, "low": 1.0}]):
            with self.subTest(candles=candles):
                value, count = ks.volatility_from_candles(candles)
                self.assertIsNone(value)
                self.assertEqual(count, 0)
        row = _row(volatility=None, volatility_candles=0,
                   volatility_note="volatility tidak tersedia (tanpa candle)")
        self.assertEqual(ks.row_krystal_gaps(row), ["metrik tidak tersedia"])

    def test_low_nol_tidak_dipakai_pembagi(self):
        value, count = ks.volatility_from_candles(
            [{"high": 1.0, "low": 0.0}, {"high": 0.0, "low": 0.0}])
        self.assertIsNone(value)
        self.assertEqual(count, 0)

    def test_fetch_memakai_24_candle_network_robinhood(self):
        with mock.patch.object(
                core, "get_hourly_candles",
                return_value=_candles((1.2, 1.0), (1.5, 0.9))) as fetch:
            value, count = ks.fetch_pool_volatility(POOL_A)
        self.assertAlmostEqual(value, 66.66666666666666)
        self.assertEqual(count, 2)
        args, kwargs = fetch.call_args
        self.assertEqual(args[0], POOL_A)
        self.assertEqual(kwargs["limit_hours"], ks.KRYSTAL_VOLATILITY_HOURS)
        # Network GeckoTerminal = robinhood (chain 4663), bukan solana.
        self.assertEqual(kwargs["network"], "robinhood")
        self.assertEqual(kwargs["timeout"], ks.KRYSTAL_TIMEOUT)

    def test_kegagalan_transport_jadi_tanpa_volatility(self):
        with mock.patch.object(core, "get_hourly_candles",
                               side_effect=RuntimeError("HTTP 429")):
            value, count = ks.fetch_pool_volatility(POOL_A)
        self.assertIsNone(value)
        self.assertEqual(count, 0)

    def test_enrich_volatility_mengisi_semua_baris(self):
        rows = [_row(pool_address=POOL_A, volatility=None),
                _row(pool_address=POOL_B, volatility=None)]
        with mock.patch.object(ks, "fetch_pool_volatility",
                               side_effect=[(2.0, 24), (None, 0)]):
            rows = ks.enrich_volatility(rows)
        self.assertEqual(rows[0]["volatility"], 2.0)
        self.assertEqual(rows[0]["volatility_candles"], 24)
        self.assertEqual(rows[0]["volatility_note"], "")
        self.assertIsNone(rows[1]["volatility"])
        self.assertEqual(rows[1]["volatility_note"],
                         "volatility tidak tersedia (tanpa candle)")


class SortTest(unittest.TestCase):
    """Urutan baris: F/V → volume/TVL → dust %MC terkecil → simbol."""

    def test_urutan_fv_lalu_volume_tvl_lalu_dust(self):
        rows = [
            _row(pool_address="F_V_KECIL", symbol="SMALL", **_fv(10.0, 1.0),
                 vol_tvl_ratio=900.0, analysis=_proof(0.001)),
            _row(pool_address="F_V_BESAR", symbol="BIG", **_fv(90.0, 1.0),
                 vol_tvl_ratio=10.0, analysis=_proof(0.09)),
            _row(pool_address="VOL_BESAR", symbol="VOLT", **_fv(50.0, 1.0),
                 vol_tvl_ratio=900.0, analysis=_proof(0.05)),
            _row(pool_address="F_V_SEDANG", symbol="MID", **_fv(50.0, 1.0),
                 vol_tvl_ratio=100.0, analysis=_proof(0.05)),
        ]
        order = [row["pool_address"] for row in ks.sort_krystal_rows(rows)]
        self.assertEqual(order, ["F_V_BESAR", "VOL_BESAR", "F_V_SEDANG",
                                 "F_V_KECIL"])

    def test_tie_break_dust_pakai_presisi_tampilan(self):
        rows = [
            _row(pool_address="MENTAH", symbol="ZZZ", **_fv(20.0, 4.0),
                 vol_tvl_ratio=7.0, analysis=_proof(0.0301)),
            _row(pool_address="TAMPIL", symbol="AAA", **_fv(20.0, 4.0),
                 vol_tvl_ratio=7.0, analysis=_proof(0.0304)),
        ]
        self.assertEqual([row["pool_address"]
                          for row in ks.sort_krystal_rows(rows)],
                         ["TAMPIL", "MENTAH"])

    def test_tanpa_fv_paling_bawah(self):
        rows = [_row(pool_address="TANPA", volatility=None),
                _row(pool_address="LENGKAP", **_fv(10.0, 1.0))]
        self.assertEqual([row["pool_address"]
                          for row in ks.sort_krystal_rows(rows)],
                         ["LENGKAP", "TANPA"])

    def test_dust_tanpa_bukti_tidak_jadi_nol_palsu(self):
        """Scan holder gagal (0 wallet) → ``None``, bukan 0,000%."""
        row = _row(analysis={"holders": {"dust_pct_mc": 0.0,
                                         "total_fetched": 0}},
                   dust_pct_mc=None, holders_proof=False,
                   holders_note="⚠️ 0 holder")
        self.assertIsNone(ks.row_dust_pct(row))


class ScanLaneTest(unittest.TestCase):
    """Satu tombol = satu lane; gate jalan SEBELUM holder."""

    @staticmethod
    def _fake_holders(rows, **_kw):
        out = []
        for row in rows:
            item = dict(row)
            item["analysis"] = _proof(0.02)
            item["dust_pct_mc"] = 0.02
            item["dust_count"] = 5
            item["holders_proof"] = True
            out.append(item)
        return out

    def _scan(self, pools, *, lane="24h", **kwargs):
        with mock.patch.object(ks, "fetch_all_pools",
                               return_value=(pools, "")) as listing, \
                mock.patch.object(ks, "fetch_pool_volatility",
                                  side_effect=self._vol(pools)), \
                mock.patch.object(ks, "enrich_holders",
                                  side_effect=self._fake_holders) as holders:
            result = ks.scan_krystal_lane(lane, **kwargs)
        return result, listing, holders

    @staticmethod
    def _vol(pools):
        values = []
        for pool in pools:
            address = pool.get("poolAddress")
            values.append((10.0, 24) if address != POOL_C else (0.0, 24))
        return values

    def test_gate_sebelum_holder_dan_vol_nol_dibuang(self):
        """Gate memakai **F dan V**, bukan field mentah fee/TVL.

        POOL_A: F = 10.000/100.000 = 10% dengan V = 1% → F/V 10× lolos.
        POOL_B: F = 100/100.000 = 0,1% dengan V = 1% → F/V 0,1× gugur.
        POOL_C: V = 0 → gugur dan **dibuang** (tidak masuk hidden_rows).
        """
        pools = [
            _pool(POOL_A, tvl=100_000.0, fee=10_000.0),
            _pool(POOL_B, base=TOKEN_B, tvl=100_000.0, fee=100.0),
            _pool(POOL_C, tvl=100_000.0, fee=10_000.0),
        ]
        with mock.patch.object(ks, "fetch_all_pools",
                               return_value=(pools, "")), \
                mock.patch.object(ks, "fetch_pool_volatility",
                                  side_effect=[(1.0, 24), (1.0, 24),
                                               (0.0, 24)]), \
                mock.patch.object(ks, "enrich_holders",
                                  side_effect=self._fake_holders) as holders:
            result = ks.scan_krystal_lane("24h")
        # Hanya pool lolos yang menyentuh Blockscout.
        self.assertEqual([row["pool_address"]
                          for row in holders.call_args.args[0]], [POOL_A])
        self.assertEqual([row["pool_address"] for row in result["rows"]],
                         [POOL_A])
        # Pool V=0 tidak masuk "dilewati" dan tidak dihitung di hidden_metric.
        self.assertEqual([row["pool_address"] for row in result["hidden_rows"]],
                         [POOL_B])
        self.assertEqual(result["hidden_metric"], 1)
        self.assertEqual(result["dropped_volatility"], 1)
        self.assertEqual(result["fetched"], 3)
        self.assertEqual(result["lane"], "24h")
        self.assertEqual(result["gate"], "24H: F/V ≥ 5×")

    def test_hanya_pool_lolos_yang_di_enrich(self):
        pools = [_pool(POOL_A, tvl=100_000.0, fee=10_000.0),   # F 10% · V 1%
                 _pool(POOL_B, base=TOKEN_B, tvl=100_000.0, fee=100.0)]
        with mock.patch.object(ks, "fetch_all_pools",
                               return_value=(pools, "")), \
                mock.patch.object(ks, "fetch_pool_volatility",
                                  side_effect=[(1.0, 24), (10.0, 24)]), \
                mock.patch.object(ks, "enrich_holders",
                                  side_effect=self._fake_holders) as holders:
            result = ks.scan_krystal_lane("24h")
        self.assertEqual([row["pool_address"]
                          for row in holders.call_args.args[0]], [POOL_A])
        self.assertEqual([row["pool_address"] for row in result["rows"]],
                         [POOL_A])
        self.assertEqual([row["pool_address"] for row in result["hidden_rows"]],
                         [POOL_B])
        self.assertEqual(result["hidden_metric"], 1)
        self.assertEqual(result["dropped_volatility"], 0)

    def test_kegagalan_api_jadi_pesan_card(self):
        with mock.patch.object(
                ks, "fetch_all_pools",
                return_value=([], "uniswapv3: Krystal HTTP 503")):
            result = ks.scan_krystal_lane("24h")
        self.assertIn("Krystal HTTP 503", result["error"])
        self.assertEqual(result["rows"], [])

    def test_tanpa_api_key_tidak_melempar(self):
        with mock.patch.object(ks, "api_key", return_value=""):
            with mock.patch.object(ks, "fetch_all_pools",
                                   return_value=([], "KC-APIKey required")):
                result = ks.scan_krystal_lane("24h")
        self.assertIn("KC-APIKey required", result["error"])
        self.assertEqual(result["rows"], [])

    def test_protokol_dan_dedup_diteruskan(self):
        seen: list = []

        def _fake(protocol, **_kw):
            seen.append(protocol)
            # F = 10.000/100.000 = 10% dengan V = 1% → F/V 10× (lolos gate).
            return ([_pool(POOL_A, tvl=100_000.0, fee=10_000.0)]
                    if protocol == "uniswapv3" else [])

        with mock.patch.object(ks, "fetch_pools", side_effect=_fake), \
                mock.patch.object(ks, "fetch_pool_volatility",
                                  side_effect=[(1.0, 24)]), \
                mock.patch.object(ks, "enrich_holders",
                                  side_effect=self._fake_holders):
            result = ks.scan_krystal_lane("24h")
        self.assertEqual(seen, list(ks.KRYSTAL_PROTOCOLS))
        # Pool yang sama dikembalikan 4 protokol (mock di atas hanya untuk
        # uniswapv3) → dedup per alamat pool.
        self.assertEqual(len(result["rows"]), 1)


@unittest.skipIf(AppTest is None, "streamlit not installed")
class KrystalCardTest(unittest.TestCase):
    """Card 🦅 Scan Best Pool Krystal: tabel, sorot, ⭐, cache."""

    def setUp(self):
        # Tes ini menguji penulisan cache hasil scan → direktori sementara
        # sendiri (lihat :func:`_isolate_cache`).
        _isolate_cache(self)

    def _app(self, *, with_key: bool = True):
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
            mock.patch.object(ks, "api_key",
                              return_value="kc-test-key" if with_key else ""),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=120).run()

    @staticmethod
    def _result(rows, hidden=None, *, fetched=None, error="", lane="24h"):
        hidden = list(hidden or [])
        return {"rows": rows, "hidden_rows": hidden, "error": error,
                "fetched": fetched if fetched is not None else len(rows) + len(hidden),
                "hidden_metric": len(hidden), "dropped_volatility": 0,
                "skipped_quote": 0, "volatility_missing": 0,
                "protocols": list(ks.KRYSTAL_PROTOCOLS), "lane": lane,
                "timeframe": lane, "gate": ks.krystal_lane_gate_label(lane),
                "analyzed_at": 1_780_000_000}

    def test_judul_dan_tombol_card(self):
        app = self._app()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(ks.KRYSTAL_CARD_TITLE, body)
        keys = [button.key or "" for button in app.button]
        self.assertIn("krystal-pool-scan-24h", keys)

    def test_tanpa_api_key_card_tetap_render_dengan_pesan(self):
        app = self._app(with_key=False)
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(ks.KRYSTAL_CARD_TITLE, body)
        warnings = "\n".join(node.value for node in app.warning)
        self.assertIn("KRYSTAL_API_KEY", warnings)
        self.assertIn("secrets.toml", warnings)
        # Tombol scan tidak ditawarkan tanpa key (scan pasti gagal).
        keys = [button.key or "" for button in app.button]
        self.assertNotIn("krystal-pool-scan-24h", keys)

    def test_empat_kolom_inti_di_depan(self):
        app = self._app()
        app.session_state["krystal_pool_scan_24h"] = self._result([
            _row(pool_address=POOL_A, ca=TOKEN_A, symbol="TOK")])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        for header in (">Token<", ">F/V<", ">Volat<", ">Dust %MC<"):
            self.assertIn(header, body)
        self.assertLess(body.index(">Token<"), body.index(">F/V<"))
        self.assertLess(body.index(">F/V<"), body.index(">Volat<"))
        self.assertLess(body.index(">Volat<"), body.index(">Dust %MC<"))
        # Konteks pool (TVL, Fee/TVL, Vol 24h, APR) SETELAH 4 kolom inti.
        for header in (">TVL<", ">Fee/TVL<", ">Vol 24h<", ">APR<", ">Pool<"):
            self.assertIn(header, body)
            self.assertLess(body.index(">Dust %MC<"), body.index(header))
        # Protokol tampil di kolom Pool (syarat: nama protokol kelihatan).
        self.assertIn("Uniswap V3", body)

    def test_sorot_hijau_menyala_fv_dan_volat_tertinggi(self):
        neon = kp.TOP_HIGHLIGHT_COLOR
        app = self._app()
        app.session_state["krystal_pool_scan_24h"] = self._result([
            _row(pool_address="PoolTop", ca=TOKEN_A, symbol="TOP",
                 **_fv(100.0, 9.9)),   # F/V 10,1× · volat terbesar
            _row(pool_address="PoolKedua", ca=TOKEN_B, symbol="KDUA",
                 **_fv(30.0, 6.2)),    # F/V 4,8× -> gugur? tidak: 30/6,2=4,84
        ])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn(
            f'<span style="color:{neon};font-weight:800;">9.9%</span>', body)
        self.assertIn(
            f'<span style="color:{neon};font-weight:800;">10.1×</span>', body)
        self.assertIn("F/V tertinggi di tabel ini", body)
        self.assertIn("volatility terbesar di tabel ini", body)

    def test_tabel_dilewati_tanpa_sorot(self):
        neon = kp.TOP_HIGHLIGHT_COLOR
        app = self._app()
        app.session_state["krystal_pool_scan_24h"] = self._result(
            [_row(pool_address=POOL_A, ca=TOKEN_A, symbol="TOK")],
            hidden=[_row(pool_address=POOL_B, ca=TOKEN_B, symbol="LEWAT",
                         **_fv(10.0, 10.0))], fetched=2)
        app.session_state["krystal_pool_show_hidden_24h"] = True
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("$LEWAT", body)
        self.assertIn("gugur: F/V < 5×", body)
        # Tabel dilewati tidak ikut disorot (barisnya sudah dianotasi merah),
        # jadi warna neon tidak muncul sama sekali di halaman ini.
        self.assertNotIn(f"color:{neon}", body)

    def test_volatility_nol_dibuang_dari_semua_tabel(self):
        """Baris V=0 (hasil scan lama sekalipun) tidak tampil di mana pun."""
        app = self._app()
        app.session_state["krystal_pool_scan_24h"] = self._result(
            [_row(pool_address=POOL_A, ca=TOKEN_A, symbol="TOK"),
             _row(pool_address="PoolNol", ca=TOKEN_B, symbol="MATI",
                  volatility=0.0)],
            hidden=[_row(pool_address="PoolNol2", ca=TOKEN_B, symbol="SEPI",
                         volatility=0.0)])
        app.run()
        self.assertEqual(len(app.exception), 0)
        body = "\n".join(node.value for node in app.markdown)
        self.assertNotIn("$MATI", body)
        self.assertNotIn("$SEPI", body)
        self.assertIn("$TOK", body)

    def test_star_masuk_watchlist_robinhood(self):
        app = self._app()
        app.session_state["krystal_pool_scan_24h"] = self._result([
            _row(pool_address=POOL_A, ca=TOKEN_A, symbol="TOK")])
        app.run()
        with mock.patch("robinhood_watchlist.add_to_robinhood_watchlist",
                        return_value=True) as add:
            app.button(key=f"krystal-pool-24h-star-{POOL_A}").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(add.called)
        args, kwargs = add.call_args
        self.assertEqual(args[0], TOKEN_A)
        self.assertEqual(args[1], "TOK")
        self.assertEqual(kwargs.get("source"), "lp")
        self.assertTrue(kwargs.get("background"))

    def test_rule_di_tooltip_bukan_caption(self):
        app = self._app()
        app.session_state["krystal_pool_scan_24h"] = self._result([
            _row(pool_address=POOL_A, ca=TOKEN_A, symbol="TOK")], fetched=3)
        app.run()
        captions = "\n".join(node.value for node in app.caption)
        body = "\n".join(node.value for node in app.markdown)
        self.assertIn("1 pool 24H tampil", captions)
        # Detail rule hidup di atribut title (tooltip judul), bukan caption.
        tooltip = html.escape(kp.krystal_pool_tooltip(), quote=True)
        self.assertIn(f'title="{tooltip}"', body)
        for rule_text in ("F/V ≥ 5×", "fee 24 jam", "GeckoTerminal"):
            self.assertNotIn(rule_text, captions)
        self.assertIn("F/V ≥ 5×", tooltip)

    def test_tooltip_ambang_mengikuti_konstanta(self):
        with mock.patch.object(ks, "KRYSTAL_FV_24H_MIN", 7.0):
            self.assertIn("Gate 24H: F/V ≥ 7×", kp.krystal_pool_tooltip())

    def test_scan_menyimpan_hasil_ke_cache(self):
        app = self._app()
        with mock.patch.object(
                ks, "fetch_all_pools",
                return_value=([_pool(POOL_A, tvl=100_000.0, fee=10_000.0)], "")), \
                mock.patch.object(ks, "fetch_pool_volatility",
                                  return_value=(1.0, 24)), \
                mock.patch.object(ks, "enrich_holders",
                                  side_effect=lambda rows, **_kw: rows):
            app.button(key="krystal-pool-scan-24h").click().run()
        self.assertEqual(len(app.exception), 0)
        path = scan_result_cache.cache_path(kp.krystal_cache_key("24h"))
        self.assertTrue(path.exists(), f"cache tidak ditulis: {path}")
        payload = scan_result_cache.load_result(kp.krystal_cache_key("24h"))
        self.assertEqual([row["pool_address"] for row in payload["rows"]],
                         [POOL_A])


@unittest.skipIf(AppTest is None, "streamlit not installed")
class CachePersistenceTest(unittest.TestCase):
    """Refresh browser: session kosong → tabel dipulihkan dari cache."""

    def setUp(self):
        _isolate_cache(self)

    def _result(self):
        return {"rows": [_row(pool_address=POOL_A, ca=TOKEN_A, symbol="TOK")],
                "hidden_rows": [], "error": "", "fetched": 4,
                "hidden_metric": 0, "dropped_volatility": 0,
                "skipped_quote": 0, "volatility_missing": 0,
                "lane": "24h", "timeframe": "24h",
                "gate": ks.krystal_lane_gate_label("24h"),
                "analyzed_at": 1_780_000_000}

    def test_save_lalu_session_kosong_dipulihkan(self):
        key = kp.krystal_cache_key("24h")
        scan_result_cache.save_result(key, self._result())
        payload = scan_result_cache.load_result(key)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["rows"][0]["symbol"], "TOK")
        # Baris tanpa cache → tidak ada yang dipulihkan.
        self.assertIsNone(scan_result_cache.load_result("krystal_pool_scan_30m"))

    def test_restore_mengisi_session_state_kosong(self):
        class _Session(dict):
            pass

        class _St:
            def __init__(self):
                self.session_state = _Session()

        st = _St()
        key = kp.krystal_cache_key("24h")
        scan_result_cache.save_result(key, self._result())
        self.assertTrue(scan_result_cache.restore_into_session(st, key, key))
        self.assertEqual(st.session_state[key]["rows"][0]["symbol"], "TOK")
        # Sesi yang sudah berisi hasil scan baru tidak ditimpa cache lama.
        st.session_state[key] = {"rows": []}
        self.assertFalse(scan_result_cache.restore_into_session(st, key, key))
        self.assertEqual(st.session_state[key], {"rows": []})

    def test_refresh_browser_tidak_menghilangkan_tabel(self):
        """Sesi benar-benar baru (AppTest kedua) tetap melihat hasil scan.

        Alurnya: scan di satu sesi → hasil disimpan ke berkas cache → sesi
        baru (refresh browser) memulihkannya. Bila cache dihapus, sesi baru
        kembali ke kondisi "belum di-scan" — jadi yang diuji memang cache-nya,
        bukan sesi yang masih hidup.
        """
        app = self._new_app()
        with mock.patch.object(
                ks, "fetch_all_pools",
                return_value=([_pool(POOL_A, tvl=100_000.0, fee=10_000.0)], "")), \
                mock.patch.object(ks, "fetch_pool_volatility",
                                  return_value=(1.0, 24)), \
                mock.patch.object(ks, "enrich_holders",
                                  side_effect=lambda rows, **_kw: rows):
            app.run()
            app.button(key="krystal-pool-scan-24h").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("$TOK", "\n".join(node.value for node in app.markdown))

        fresh = self._new_app()
        fresh.run()
        self.assertEqual(len(fresh.exception), 0)
        self.assertIn("$TOK", "\n".join(node.value for node in fresh.markdown))

        # Hapus cache → sesi baru benar-benar kosong (bukan kebetulan).
        scan_result_cache.clear_result(kp.krystal_cache_key("24h"))
        kosong = self._new_app()
        kosong.run()
        self.assertEqual(len(kosong.exception), 0)
        body = "\n".join(node.value for node in kosong.markdown)
        self.assertNotIn("$TOK", body)
        self.assertIn("belum di-scan",
                      "\n".join(node.value for node in kosong.caption))

    def _new_app(self):
        """AppTest yang belum dijalankan (sesi kosong seperti habis refresh)."""
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
            mock.patch.object(ks, "api_key", return_value="kc-test-key"),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return AppTest.from_file(APP, default_timeout=120)


class CacheModuleTest(unittest.TestCase):
    """Modul cache: ramping, tidak pernah melempar, atomic."""

    def setUp(self):
        self._cache_dir = _isolate_cache(self)

    def test_peta_wallet_berat_dibuang(self):
        result = {"rows": [{"ca": TOKEN_A, "symbol": "TOK",
                            "analysis": {"holders": {"dust_pct_mc": 0.03},
                                         "wallet_snapshot": {"balances":
                                                             {"a": 1}},
                                         "chrono_snapshot": {"movements": []}}}]}
        slim = scan_result_cache.slim_result(result)
        analysis = slim["rows"][0]["analysis"]
        self.assertNotIn("wallet_snapshot", analysis)
        self.assertNotIn("chrono_snapshot", analysis)
        self.assertEqual(analysis["holders"]["dust_pct_mc"], 0.03)

    def test_payload_rusak_tidak_melempar(self):
        self.assertIsNone(scan_result_cache.save_result("rusak", None))
        self.assertIsNone(scan_result_cache.load_result("tidak-ada"))
        self.assertFalse(scan_result_cache.clear_result("tidak-ada"))

    def test_nilai_non_json_dinormalkan(self):
        slim = scan_result_cache.slim_result(
            {"rows": [{"x": float("nan"), "y": float("inf")}], "n": 1})
        self.assertIsNone(slim["rows"][0]["x"])
        self.assertIsNone(slim["rows"][0]["y"])

    def test_key_aneh_jadi_nama_berkas_aman(self):
        path = scan_result_cache.cache_path("../../etc/passwd")
        self.assertTrue(path.name.endswith(".json"))
        self.assertNotIn("..", path.name)

    def test_direktori_cache_mengikuti_env_dan_tulisan_atomik(self):
        """``SCAN_CACHE_DIR`` menentukan lokasi; berkas ditulis utuh."""
        self.assertEqual(scan_result_cache.cache_dir(), self._cache_dir)
        self.assertTrue(scan_result_cache.enabled())
        path = scan_result_cache.save_result("krystal_pool_scan_24h",
                                             {"rows": [{"symbol": "TOK"}]})
        self.assertEqual(Path(path).parent, self._cache_dir)
        self.assertFalse(list(self._cache_dir.glob("*.tmp")))
        self.assertEqual(scan_result_cache.load_result(
            "krystal_pool_scan_24h")["rows"][0]["symbol"], "TOK")
        self.assertTrue(scan_result_cache.clear_result("krystal_pool_scan_24h"))
        self.assertEqual(scan_result_cache.clear_all(), 0)


if __name__ == "__main__":
    unittest.main()
