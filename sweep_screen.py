# -*- coding: utf-8 -*-
"""Mesin skrining **kelayakan sweep** + deteksi sweep (logika murni).

Modul ini sengaja **tanpa jaringan** supaya bisa diuji penuh tanpa API: semua
fungsi menerima angka yang sudah diambil (:mod:`sweep_data`) atau deret candle
mentah. Permintaan user 2026-10-12: *"bisa kamu buat ini di wallet-depth? …
nanti ada telegram alert … catat detail2nya sebagai tabel yang bisa saya lihat
statistiknya."*

Enam kriteria berasal dari analisis COCKROACH (``H4KUxs…nyJc``) 1 Okt 2026 —
sweep 8 menit yang menaikkan harga 8,67x dengan net inflow hanya $58.778:

    biaya sweep (fraksi MC) = (akar(m) - 1) x (liq / MC)

Kriteria **bukan filter kaku**: tiap kriteria mengembalikan ``passed`` yang
bisa ``True`` / ``False`` / ``None`` (``None`` = data belum cukup), dan skor
akhirnya adalah proporsi yang lulus dari yang **punya data**. Ini disengaja —
kriteria 4 dan 5 butuh riwayat snapshot, jadi mint yang baru ditambahkan tidak
boleh dihukum karena datanya belum terkumpul.
"""
from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timedelta, timezone

# --- ambang tetap kriteria (satu tempat, biar mesin, UI & test tidak menyimpang) ---
# Kriteria 1 (2026-10-14, keputusan user): float tipis diukur dari sisi TOKEN
# pool = pool_base_usd ÷ FDV. Ambang 17,5% = setara liq/MC 35% dibagi dua, dengan
# asumsi sisi quote kira-kira separuh likuiditas. Liq/MC tetap dipakai untuk
# biaya sweep, bukan untuk kriteria ini.
TOKEN_MC_MAX = 0.175       # kriteria 1: token/MC maksimum 17,5%, tetap
# Kriteria LP locked dihapus: likuiditas token pump.fun sudah pasti terkunci,
# jadi tidak lagi dicek maupun dihitung sebagai skor.
TOP10_MAX = 0.25           # kriteria 3: top-10 (tanpa pool) < 25% supply
HOLDER_MAX_PCT = 5.0       # kriteria 3: tiap holder maksimum 5%, tetap
ABSORPTION_MAX_DRIFT = 0.25  # kriteria 4: harga sideways (< 25%) selama akumulasi
MIN_SNAPSHOTS_ABSORPTION = 3  # kriteria 4/5: minimal snapshot sebelum dinilai
VOL_EXPANSION_MIN_X = 3.0  # kriteria 5: ekspansi volume >= 3x titik tersepi
VOL_VERTICAL_MAX = 3.0     # kriteria 5: harga belum lari (< 3x dari titik tersepi)
SHAKEOUT_MIN_DROP = 0.30   # kriteria 6: satu bar turun >= 30%
HIGHER_LOW_MIN = 1.0       # kriteria 6: low berikutnya harus >= low shakeout

# Acuan cohort pra-pump COCKROACH, 1 Okt 2026 22:42 WIB: MC $233.451,
# TVL dua sisi $30.232, cash satu sisi $15.116, biaya dorong 3x $11.066
# (=4,74% MC). Sejak 2026-10-14 (permintaan user) acuan dana memakai 10x:
# biaya 10x COCK = (√10 − 1) × cash $15.116 = $32.684 (≈14,0% MC). Angka 10x
# ini turunan dari rumus yang sama dengan angka 3x terukur, bukan pengukuran.
REFERENCE_MULT = 10.0
COCK_REFERENCE_MC_USD = 233_451.0
COCK_REFERENCE_CASH_USD = 15_116.0
COCK_REFERENCE_COST_3X_USD = 11_066.0
COCK_REFERENCE_COST_3X_MC_FRAC = (COCK_REFERENCE_COST_3X_USD /
                                  COCK_REFERENCE_MC_USD)
COCK_REFERENCE_COST_10X_USD = ((math.sqrt(REFERENCE_MULT) - 1.0)
                               * COCK_REFERENCE_CASH_USD)
COCK_REFERENCE_COST_10X_MC_FRAC = (COCK_REFERENCE_COST_10X_USD /
                                   COCK_REFERENCE_MC_USD)
COHORT_WINDOW_HOURS = 48
#: Ambang minimum kohort: VWAP kelahiran harus minus minimal 50% dari harga
#: kini (status_avg_cost ≤ -0,50). Diturunkan dari -70% atas permintaan user
#: 2026-10-13.
COHORT_MINUS_THRESHOLD = -0.50

#: Biaya sweep untuk naik ``COST_GATE_MULT`` kali (fraksi MC) hanya ditampilkan
#: sebagai informasi. Gate batas 28% MC DIHAPUS 2026-10-15 atas permintaan user:
#: biaya 10x tidak menentukan vonis, sehingga tidak ada status ``TUNGGU — biaya 10x``.
COST_GATE_MULT = 10.0

#: Acuan kalibrasi inflow nyata vs biaya dorong ke puncak, dari satu event
#: terukur: COCKROACH 1 Okt 2026 — Δ TVL $58.778 ÷ 2 = uang quote masuk
#: $29.389 ÷ biaya dorong ke puncak $29.389 = 1,0x. Konstanta ini dipakai
#: hanya sebagai **estimasi berlabel** saat selisih likuiditas antar snapshot
#: belum tersedia; begitu ada pengukuran nyata, angka nyata yang dipakai
#: (jangan mencampur keduanya).
REF_NET_COST_MULT = 1.0

# --- ambang deteksi sweep ---
SWEEP_VOL_MULT = 20.0      # volume candle sweep >= 20x median baseline
SWEEP_PRICE_MULT = 1.5     # harga naik >= 1,5x dari harga dasar
SWEEP_BASELINE_BARS = 24   # baseline = 24 candle sebelum kandidat

# --- standar struktural tetap ---
# Biaya dorong = uang quote yang masuk ke pool = (√m−1) × liq/2 (liq = TVL dua
# sisi, sisi quote = setengah). Kriteria float memakai token/MC ≤ 17,5%; biaya
# 3x pada batas itu ≈ (√3−1)×35%/2 = 6,4% MC. Acuan COCK 3× $11.066 = 4,74% MC
# cocok dengan basis biaya ini. Holder per-wallet maksimum 5%.

#: Minimal kriteria lulus untuk vonis LAYAK — tapi ambangnya menyesuaikan
#: berapa kriteria yang **sudah punya data**: di deploy baru hanya trio
#: struktural (1+2+3) yang bisa dinilai, dan menuntut 4 dari 3 mustahil.
#: Jadi: wajib lulus trio struktural, lalu minimal ``min(4, jumlah_yang_dinilai)``
#: kriteria lulus. Artinya begitu riwayat akumulasi/volume/shakeout tersedia,
#: syaratnya otomatis naik menjadi "struktural + minimal satu bukti".
ELIGIBLE_MIN_PASSED = 4
ELIGIBLE_STRUCTURAL = ("token_mc", "float_spread", "authority")  # wajib lulus; authority tidak masuk skor

CRITERIA_KEYS = (
    ("token_mc", "Token/MC"),
    ("float_spread", "Float tersebar"),
    ("absorption", "Akumulasi (proxy)"),
    ("vol_expansion", "Ekspansi volume"),
    ("shakeout", "Shakeout + higher low"),
)

#: Skor minimum yang tetap dihitung sebagai "punya data" (untuk rata-rata).
SCORE_GOOD = 0.75

VERDICT_LAYAK = ("LAYAK SWEEP", "#15803d")
VERDICT_KANDIDAT = ("KANDIDAT", "#b45309")
VERDICT_TIDAK = ("TIDAK LAYAK", "#64748b")
VERDICT_DATA = ("DATA KURANG", "#64748b")


def _num(value):
    """float finite, atau ``None`` bila bukan angka."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def leverage_cost(mult, liq_mc):
    """Biaya net sweep sebagai **fraksi market cap** untuk naik ``mult`` kali.

    ``(akar(m) - 1) x (liq / MC) / 2`` — uang quote yang benar-benar masuk ke
    pool untuk menaikkan harga ``m`` kali pada AMM constant-product. Liq adalah
    TVL dua sisi, sisi quote = liq/2. Diverifikasi pada COCKROACH: 2x $6.261,
    3x $11.066 (4,74% MC), 5x $18.684 — persis angka acuan di docs.
    """
    m = _num(mult)
    lm = _num(liq_mc)
    if m is None or lm is None or m <= 0 or lm <= 0:
        return None
    return (math.sqrt(m) - 1.0) * lm / 2.0


def leverage_ratio(mult, liq_mc):
    """Paper market cap yang diciptakan per $1 uang quote masuk.

    ``(akar(m) + 1) / (liq / MC / 2)`` — uang masuk = ``(akar(m)-1) x liq/2``.
    """
    m = _num(mult)
    lm = _num(liq_mc)
    if m is None or lm is None or m <= 0 or lm <= 0:
        return None
    return (math.sqrt(m) + 1.0) / (lm / 2.0)


def cost_usd(mult, liq_usd):
    """Nominal USD yang dibutuhkan untuk naik ``mult`` kali.

    ``(akar(m) - 1) x liq_usd / 2`` — uang quote masuk ke pool (sisi quote =
    setengah TVL dua sisi). Sama dengan ``cost_frac x MC``.
    """
    m = _num(mult)
    lu = _num(liq_usd)
    if m is None or lu is None or m <= 0 or lu <= 0:
        return None
    return (math.sqrt(m) - 1.0) * lu / 2.0


def target_costs(liq_mc, mults=(2.0, 5.0, 10.0, 50.0), liq_usd=None):
    """Tabel biaya sweep + leverage untuk beberapa target kelipatan.

    ``usd`` hanya diisi bila ``liq_usd`` diberikan (nominal dolar biaya).
    """
    out = []
    for mult in mults:
        cost = leverage_cost(mult, liq_mc)
        out.append({
            "mult": float(mult),
            "cost_frac": cost,
            "cost_pct": (cost * 100.0) if cost is not None else None,
            "cost_usd": cost_usd(mult, liq_usd),
            "leverage": leverage_ratio(mult, liq_mc),
            "feasible": (cost is not None and cost <= 1.0),
        })
    return out


#: Gate avg buy holder (permintaan user 2026-10-13): avg buy terendah di antara
#: holder yang masih memegang token tidak boleh lebih dari 50% di bawah harga
#: sekarang. Di bawah itu ada holder yang sudah profit besar dan siap dump →
#: TUNGGU. Tanpa data = TUNGGU juga (sama seperti gate lain).
HOLDER_COST_MAX_GAP = 0.50


def holder_cost_gate(min_avg_cost, price_usd) -> dict:
    """Gate avg buy holder: jarak harga ke avg buy terendah ≤ 50% → LOLOS.

    ``gap = 1 − min_avg_cost / price``; gap > 50% (equivalently
    min_avg_cost < 0.5 × price) → TUNGGU. Input kosong/nol → TUNGGU tanpa data.
    """
    avg = _num(min_avg_cost)
    price = _num(price_usd)
    limit_pct = HOLDER_COST_MAX_GAP * 100
    if avg is None or avg <= 0 or price is None or price <= 0:
        return {"passed": False, "gap": None,
                "status": "TUNGGU — avg buy holder belum ada data",
                "detail": "avg buy holder terendah atau harga belum tersedia; "
                          "gate belum lolos"}
    gap = 1.0 - avg / price
    detail = (f"avg buy holder terendah ${avg:.8g}, harga ${price:.8g}: "
              f"jarak {gap * 100:.1f}% (batas {limit_pct:.0f}%)")
    if gap > HOLDER_COST_MAX_GAP:
        return {"passed": False, "gap": gap,
                "status": f"TUNGGU — avg buy holder {gap * 100:.0f}% di bawah harga",
                "detail": detail + "; holder sudah profit besar"}
    return {"passed": True, "gap": gap, "status": "LOLOS", "detail": detail}


def holder_price_change_vs_lowest_buy(min_avg_cost, price_usd):
    """Perubahan harga sekarang terhadap lowest buy: ``harga ÷ min_avg − 1``.

    Positif = harga sudah naik dari avg buy terendah, negatif = sudah turun.
    Tanpa data = None.
    """
    low = _num(min_avg_cost)
    price = _num(price_usd)
    if low is None or price is None or low <= 0 or price <= 0:
        return None
    return price / low - 1.0


def holder_lowest_buy_mc(min_avg_cost, price_usd, mc_usd):
    """Lowest buy holder (avg buy terendah) dinyatakan dalam market cap.

    ``lowest buy MC = min_avg_cost × MC ÷ harga`` (MC ÷ harga = total supply).
    Nilai yang sama dipakai gate avg buy holder. Tanpa data = None.
    """
    low = _num(min_avg_cost)
    price = _num(price_usd)
    mc = _num(mc_usd)
    if low is None or price is None or mc is None:
        return None
    if low <= 0 or price <= 0 or mc <= 0:
        return None
    return low * (mc / price)


def decide_verdict(cohort_gate, holder_gate, *, score, passed_count, score_ok):
    """Rantai vonis: kohort → holder → data → LAYAK / KANDIDAT / TIDAK LAYAK.

    Gate biaya 10x tidak ada di sini (dihapus 2026-10-15). Mengembalikan
    ``(vonis, warna)``.
    """
    cohort_missing = str(cohort_gate["status"]).startswith("TANPA DATA")
    holder_wait = not holder_gate["passed"] and holder_gate.get("gap") is not None
    if not cohort_gate["passed"] and not (cohort_missing and holder_wait):
        return cohort_gate["status"], ("#64748b" if cohort_missing else "#b45309")
    if not holder_gate["passed"]:
        return holder_gate["status"], "#b45309"
    if score is None:
        return VERDICT_DATA
    if score_ok:
        return VERDICT_LAYAK
    if passed_count >= 2:
        return VERDICT_KANDIDAT
    return VERDICT_TIDAK


def current_verdict(result):
    """Vonis dan ``eligible`` kini dari gate yang **sudah tersimpan** di snapshot.

    Snapshot lama (sebelum gate biaya 28% dihapus) masih memuat vonis
    ``TUNGGU — biaya 10x …``. Kriteria dan gate kohort/holder tidak bergantung
    pada biaya, jadi vonis dihitung ulang dari field yang tersimpan tanpa
    mengambil data baru. Snapshot tanpa field gate dikembalikan apa adanya.
    """
    if (not isinstance(result, dict) or "cohort_gate_status" not in result
            or "holder_gate_status" not in result):
        return result
    required = _num(result.get("required_count"))
    passed = _num(result.get("passed_count")) or 0
    score = _num(result.get("score"))
    score_ok = bool(score is not None and required is not None
                    and passed >= required and result.get("structural_ok"))
    cohort_gate = {"passed": bool(result.get("cohort_gate_passed")),
                   "status": str(result.get("cohort_gate_status") or "")}
    holder_gate = {"passed": bool(result.get("holder_gate_passed")),
                   "gap": _num(result.get("holder_gap")),
                   "status": str(result.get("holder_gate_status") or "")}
    verdict, color = decide_verdict(cohort_gate, holder_gate, score=score,
                                    passed_count=int(passed), score_ok=score_ok)
    eligible = bool(cohort_gate["passed"] and holder_gate["passed"] and score_ok)
    return {**result, "verdict": verdict, "color": color, "eligible": eligible}


def pool_token_mc_frac(pool_base_usd, mc_usd):
    """Nilai token di sisi pool sebagai fraksi MC (mis. 0,078 = 7,8% MC).

    Sama dengan liq/MC tetapi hanya sisi token (base) pool. Tanpa data = None.
    """
    value = _num(pool_base_usd)
    mc = _num(mc_usd)
    if value is None or value < 0 or mc is None or mc <= 0:
        return None
    return value / mc


def reference_fund_multiple(liq_mc):
    """Biaya 10x sebagai kelipatan dana acuan COCK pra-pump.

    Acuan = biaya 10x COCK = (√10 − 1) × cash satu sisi $15.116 = $32.684
    (14,0% MC). Dengan basis yang sama, biaya 10x pada liq/MC COCK 12,95%
    menghasilkan tepat 1,0×.
    """
    ratio = _num(liq_mc)
    if ratio is None or ratio <= 0:
        return None
    cost_frac = leverage_cost(REFERENCE_MULT, ratio)
    if cost_frac is None or COCK_REFERENCE_COST_10X_MC_FRAC <= 0:
        return None
    return cost_frac / COCK_REFERENCE_COST_10X_MC_FRAC


def _timestamp_seconds(value):
    """Normalize epoch seconds/milliseconds (DexScreener may send milliseconds)."""
    timestamp = _num(value)
    if timestamp is None or timestamp <= 0:
        return None
    return timestamp / 1000.0 if timestamp > 1e12 else timestamp


def cohort_profile(candles, pair_created_at, price_now, *, now=None,
                   fetch_error=None) -> dict:
    """VWAP, rentang harga, status avg cost, dan dinding impas cohort kelahiran.

    OHLCV harus berasal dari pool utama dan hanya jendela 48 jam pertama yang
    dipakai. VWAP memakai harga tipikal OHLC berbobot volume GeckoTerminal.
    """
    created = _timestamp_seconds(pair_created_at)
    current = _num(price_now)
    result = {
        "available": False,
        "pair_created_at": created,
        "window_hours": COHORT_WINDOW_HOURS,
        "window_candles": 0,
        "partial_window": None,
        "vwap_48h": None,
        "price_min": None,
        "price_max": None,
        "status_avg_cost": None,
        "breakeven_wall_vwap_x": None,
        "breakeven_wall_high_x": None,
    }
    if created is None:
        result["error"] = "pairCreatedAt tidak tersedia"
        return result

    now_seconds = _timestamp_seconds(now) if now is not None else time.time()
    if now_seconds is None:
        now_seconds = time.time()
    age = max(0.0, now_seconds - created)
    window_seconds = COHORT_WINDOW_HOURS * 3600
    window_end = created + window_seconds
    # Include the hourly candle overlapping pairCreatedAt, whose timestamp is
    # the start of its hour, but exclude candles starting at/after hour 48.
    valid = []
    for candle in candles or []:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            continue
        ts = _timestamp_seconds(candle[0])
        if ts is None or ts + 3600 <= created or ts >= window_end:
            continue
        open_, high, low, close, volume = (_num(v) for v in candle[1:6])
        if (open_ is None or high is None or low is None or close is None
                or high <= 0 or low <= 0 or high < low):
            continue
        valid.append((ts, open_, high, low, close, volume))

    result["window_candles"] = len(valid)
    result["partial_window"] = (age < window_seconds or len(valid) < COHORT_WINDOW_HOURS)
    result["error"] = ""
    if not valid:
        # Alasan dari pengambil data (mis. "GeckoTerminal HTTP 429") lebih
        # berguna daripada pesan umum; gate tetap menahan (TANPA DATA).
        result["error"] = (str(fetch_error).strip() if fetch_error
                           else "OHLCV 48 jam pertama tidak tersedia")
        return result

    low = min(row[3] for row in valid)
    high = max(row[2] for row in valid)
    weighted = [(sum(row[1:5]) / 4.0, row[5])
                for row in valid if row[5] is not None and row[5] > 0]
    volume_total = sum(volume for _, volume in weighted)
    if volume_total <= 0:
        result.update({"price_min": low, "price_max": high,
                       "error": "volume OHLCV 48 jam pertama tidak tersedia"})
        return result

    vwap = sum(price * volume for price, volume in weighted) / volume_total
    result.update({"available": True, "vwap_48h": vwap,
                   "price_min": low, "price_max": high})
    if current is not None and current > 0:
        result["status_avg_cost"] = current / vwap - 1.0
        result["breakeven_wall_vwap_x"] = vwap / current
        result["breakeven_wall_high_x"] = high / current
    return result


def screen_time_wib(ts) -> str:
    """Waktu tampilan dalam WIB (Asia/Jakarta) dari epoch detik."""
    number = _num(ts)
    if not number:
        return "—"
    wib = datetime.fromtimestamp(number, timezone(timedelta(hours=7)))
    return wib.strftime("%d %b %H:%M WIB")


def cohort_latch_from_history(history, cohort_vwap, cost_basis, balance_total):
    """Latch kohort dari riwayat harga snapshot (per jam).

    Kohort dianggap pernah lolos bila ada snapshot dengan harga yang, pada
    saat yang sama, membuat VWAP proksi DAN avg cost GMGN minus ≥ 50%. Harga
    snapshot dibandingkan terhadap VWAP 48 jam (tetap) dan avg buy GMGN
    tertimbang. Tanpa data GMGN atau VWAP tidak ada latch (konservatif).
    Mengembalikan ``{"ts", "price", "source": "riwayat"}`` atau ``None``.
    """
    vwap = _num(cohort_vwap)
    if vwap is None or vwap <= 0:
        return None
    for row in sorted((r for r in (history or []) if isinstance(r, dict)),
                      key=lambda r: r.get("ts") or 0):
        price = _num(row.get("price"))
        if price is None or price <= 0:
            continue
        gmgn = gmgn_cohort_status(cost_basis, balance_total, price)
        if gmgn is None:
            return None
        if (price / vwap - 1.0 <= COHORT_MINUS_THRESHOLD
                and gmgn <= COHORT_MINUS_THRESHOLD):
            return {"ts": int(row.get("ts") or 0), "price": price,
                    "source": "riwayat"}
    return None


def gmgn_cohort_status(cost_basis, balance_total, price_usd):
    """Status avg cost GMGN kohort = harga ÷ avg buy tertimbang saldo − 1.

    ``cost_basis`` = Σ(avg_cost × saldo) dan ``balance_total`` = Σ saldo dari
    holder GMGN yang memegang token dan punya avg cost. Tanpa data → None.
    """
    basis = _num(cost_basis)
    balance = _num(balance_total)
    price = _num(price_usd)
    if basis is None or balance is None or price is None:
        return None
    if basis <= 0 or balance <= 0 or price <= 0:
        return None
    return price * balance / basis - 1.0


#: Retry otomatis untuk mint yang kohortnya tanpa data (OHLCV/VWAP atau avg cost
#: GMGN belum tersedia): dipindai ulang hanya mint itu, berjeda, dan dibatasi.
NODATA_RETRY_DELAY_SEC = 60
NODATA_RETRY_MAX_ATTEMPTS = 5
NODATA_COHORT_PREFIX = "TANPA DATA — kohort"


def is_cohort_nodata(result) -> bool:
    """True bila gate kohort belum punya data (termasuk varian ``kohort GMGN``)."""
    status = str((result or {}).get("cohort_gate_status") or "")
    return status.startswith(NODATA_COHORT_PREFIX)


def nodata_retry_targets(views, attempts,
                         max_attempts: int = NODATA_RETRY_MAX_ATTEMPTS) -> list:
    """Mint tanpa data kohort yang masih punya jatah percobaan, urut sesuai views.

    ``attempts`` = {mint: jumlah percobaan retry yang sudah dijalankan}.
    """
    attempts = attempts or {}
    out = []
    for view in views or []:
        if not isinstance(view, dict):
            continue
        mint = view.get("mint")
        if not mint or not is_cohort_nodata(view.get("result")):
            continue
        if attempts.get(mint, 0) >= max_attempts:
            continue
        out.append(mint)
    return out


#: Awalan status TUNGGU dari gate kohort (dipakai latch kohort).
COHORT_WAIT_PREFIX = "TUNGGU — kohort"


def cohort_gate(profile) -> dict:
    """Gate kohort (Kohort C, 2026-10-13): VWAP proksi DAN avg cost GMGN keduanya
    harus minus ≥ 50%. PLUS skip, belum minus tunggu, tanpa data tunggu.
    """
    status = _num((profile or {}).get("status_avg_cost"))
    threshold_pct = abs(COHORT_MINUS_THRESHOLD) * 100
    if status is None:
        return {"passed": False, "status": "TANPA DATA — kohort",
                "detail": "VWAP/jendela kelahiran tidak tersedia; gate belum lolos"}
    if status >= 0:
        return {"passed": False, "status": "SKIP — kohort plus",
                "detail": f"kohort PLUS {status*100:.1f}% terhadap VWAP kelahiran"}
    if status > COHORT_MINUS_THRESHOLD:
        return {"passed": False,
                "status": f"TUNGGU — kohort belum minus {threshold_pct:.0f}%",
                "detail": f"kohort MINUS {abs(status)*100:.1f}% (butuh {threshold_pct:.0f}%)"}
    gmgn = _num((profile or {}).get("gmgn_status_avg_cost"))
    if gmgn is None:
        return {"passed": False, "status": "TANPA DATA — kohort GMGN",
                "detail": f"VWAP minus {abs(status)*100:.1f}% lolos, tetapi avg cost "
                          "GMGN holder belum tersedia; gate belum lolos"}
    if gmgn >= 0:
        return {"passed": False,
                "status": "TUNGGU — kohort GMGN plus",
                "detail": f"VWAP minus {abs(status)*100:.1f}%, avg cost GMGN "
                          f"PLUS {gmgn*100:.1f}%"}
    if gmgn > COHORT_MINUS_THRESHOLD:
        return {"passed": False,
                "status": f"TUNGGU — kohort GMGN belum minus {threshold_pct:.0f}%",
                "detail": f"VWAP minus {abs(status)*100:.1f}%, avg cost GMGN minus "
                          f"{abs(gmgn)*100:.1f}% (butuh {threshold_pct:.0f}%)"}
    return {"passed": True, "status": "LOLOS",
            "detail": f"kohort MINUS {abs(status)*100:.1f}% terhadap VWAP dan "
                      f"{abs(gmgn)*100:.1f}% terhadap avg cost GMGN "
                      f"(ambang minus {threshold_pct:.0f}%)"}


#: Grup vonis (urutan kedua setelah jarak ke acuan dana, lihat display_sort_key).
#: 0 LAYAK · 1 KANDIDAT · 2 gate lolos tapi kriteria kurang · 3 TUNGGU kohort
#: · 4 TANPA DATA kohort · 9 SKIP kohort PLUS (selalu paling bawah).
_DISPLAY_GROUP_SKIP = 9


#: Filter tampilan hasil (permintaan user 2026-10-14): baris disembunyikan bila
#: ``x dana acuan 10x`` > 3× atau bundler < 10%. Hanya tampilan; data tetap ada.
VIEW_HIDE_REF_X_ABOVE = 3.0
VIEW_HIDE_BUNDLER_BELOW = 0.10  # fraksi 0-1 (10%)


def is_tidak_layak(result) -> bool:
    """True bila vonis baris adalah TIDAK LAYAK."""
    return str((result or {}).get("verdict") or "") == VERDICT_TIDAK[0]


def view_hidden(row) -> bool:
    """True bila baris disembunyikan dari tabel hasil.

    Nilai yang belum ada (None) tidak disembunyikan: filter hanya berlaku
    saat data untuk kriteria itu sudah terukur.
    """
    row = row or {}
    # Scan terakhir gagal (fetch data error): baris selalu tampil di tabel utama,
    # tidak pernah disembunyikan oleh filter (permintaan user 2026-10-14).
    if row.get("scan_error"):
        return False
    result = row.get("result") or {}
    metrics = row.get("metrics") or {}
    # TIDAK LAYAK disembunyikan (permintaan user 2026-10-15) dan tampil di tabel
    # terpisah, sama seperti baris yang kena filter tampilan.
    if is_tidak_layak(result):
        return True
    ref_x = _num(result.get("reference_fund_x"))
    if ref_x is None:
        ref_x = reference_fund_multiple(result.get("liq_mc"))
    bundler = _num(metrics.get("top_bundler_trader_percentage"))
    if bundler is None:
        bundler = _num(metrics.get("bundler_rate"))
    if ref_x is not None and ref_x > VIEW_HIDE_REF_X_ABOVE:
        return True
    if bundler is not None and bundler < VIEW_HIDE_BUNDLER_BELOW:
        return True
    return False


def display_sort_key(result) -> tuple:
    """Kunci urut tabel Sweep (kecil = lebih atas).

    Urutan (permintaan user 2026-10-14):
    0. blok kandidat: vonis LAYAK SWEEP dan KANDIDAT selalu paling atas, di dalam
       blok diurutkan dengan aturan 2–6 di bawah (jarak terdekat ke acuan dulu);
    1. kohort PLUS (SKIP) selalu paling bawah;
    2. baris tanpa acuan dana (tanpa liq/MC) sebelum PLUS;
    3. jarak ``|x dana acuan 10x − 1|`` paling kecil di atas (1,0× = acuan COCK);
    4. jika jarak sama: skor kriteria tertinggi (``passed/scored``) di atas;
    5. jika skor sama: jumlah kriteria lolos lebih banyak di atas;
    6. jika masih sama: kelompok vonis (LAYAK > KANDIDAT > gate lolos > TUNGGU
       > TANPA DATA), lalu untuk TUNGGU: status kohort makin dekat −50% di atas.

    ``x dana acuan`` = ``reference_fund_x`` dari :func:`evaluate`; snapshot lama
    yang belum menyimpannya dihitung ulang dari ``liq_mc``.
    """
    result = result or {}
    status = str(result.get("cohort_gate_status") or "")
    avg = _num((result.get("cohort") or {}).get("status_avg_cost"))
    passed = _num(result.get("passed_count")) or 0
    score = _num(result.get("score"))
    verdict = str(result.get("verdict") or "")
    distance = 0.0
    if status.startswith("SKIP"):
        group = _DISPLAY_GROUP_SKIP
    elif status.startswith("TANPA DATA"):
        group = 4
    elif status.startswith("TUNGGU"):
        group = 3
        if avg is not None:
            distance = abs(avg - COHORT_MINUS_THRESHOLD)
    elif verdict == VERDICT_TIDAK[0]:
        # TIDAK LAYAK diperlakukan seperti SKIP kohort plus (permintaan user
        # 2026-10-15): paling bawah dan disembunyikan dari tabel utama.
        group = _DISPLAY_GROUP_SKIP
    elif result.get("cohort_gate_passed"):
        # Termasuk TUNGGU gate avg buy holder: kohort sudah lolos, tapi holder belum.
        group = {VERDICT_LAYAK[0]: 0, VERDICT_KANDIDAT[0]: 1}.get(verdict, 2)
    else:
        group = 4
    ref_x = _num(result.get("reference_fund_x"))
    if ref_x is None:
        ref_x = reference_fund_multiple(result.get("liq_mc"))
    no_ref = ref_x is None
    ref_gap = abs(ref_x - 1.0) if ref_x is not None else 0.0
    # Blok kandidat (LAYAK SWEEP / KANDIDAT) di atas; grup 0/1 hanya terisi
    # bila kohort lolos dan vonisnya kandidat, jadi PLUS tidak pernah masuk blok.
    is_candidate = group in (0, 1)
    return (not is_candidate, group == _DISPLAY_GROUP_SKIP, no_ref, ref_gap,
            score is None, -(score or 0.0), -passed, group, distance)


# ---------------------------------------------------------------------------
# Kriteria
# ---------------------------------------------------------------------------

def _check(key, label, passed, detail, *, scored=True):
    return {"key": key, "label": label, "passed": passed, "detail": detail,
            "has_data": passed is not None, "scored": scored}


def criterion_token_mc(pool_base_usd, fdv_usd):
    """Kriteria 1 — token/MC maksimum 17,5%: float tipis di sisi token pool.

    Tanpa ``pool_base_usd`` (snapshot lama sebelum kolom ini ada) hasilnya
    ``None`` = belum ada data, bukan tebakan dari liq/MC.
    """
    ratio = pool_token_mc_frac(pool_base_usd, fdv_usd)
    if ratio is None:
        return _check("token_mc", "Token/MC", None,
                      "token pool/FDV belum tersedia (snapshot lama)")
    if ratio <= TOKEN_MC_MAX:
        detail = (f"token/MC {ratio*100:.1f}% <= {TOKEN_MC_MAX*100:.1f}% "
                  "(float tipis)")
    else:
        detail = (f"token/MC {ratio*100:.1f}% > {TOKEN_MC_MAX*100:.1f}% — "
                  "float terlalu tebal")
    return _check("token_mc", "Token/MC", ratio <= TOKEN_MC_MAX, detail)


def criterion_authority(mint_authority=None, freeze_authority=None, *,
                        known=True):
    """Gate struktural — mint dan freeze authority sudah dilepas.

    Tidak masuk skor. ``known=False`` berarti data RugCheck tidak tersedia,
    sehingga gate tidak bisa dinilai (struktural gagal, bukan lolos diam-diam).
    """
    label = "Authority dilepas"
    if not known:
        return _check("authority", label, None,
                      "data authority tidak tersedia", scored=False)
    open_authority = []
    if mint_authority not in (None, "", "null"):
        open_authority.append("mint")
    if freeze_authority not in (None, "", "null"):
        open_authority.append("freeze")
    if open_authority:
        return _check("authority", label, False,
                      "authority masih terbuka: " + ", ".join(open_authority),
                      scored=False)
    return _check("authority", label, True, "authority dilepas", scored=False)


def criterion_float_spread(top10_pct, holder_pcts):
    """Kriteria 3 — top-10 < 25% dan holder per-wallet maksimum tetap 5%.

    ``top10_pct`` dan ``holder_pcts`` selalu dalam skala persen (0-100);
    daftar holder tidak memasukkan akun pool AMM.
    """
    top10 = _num(top10_pct)
    pcts = [p for p in (_num(x) for x in (holder_pcts or [])) if p is not None]
    if top10 is None and not pcts:
        return _check("float_spread", "Float tersebar", None,
                      "top-10 / holder tidak tersedia")
    worst = max(pcts) if pcts else None
    ok = ((top10 is None or top10 < TOP10_MAX * 100.0)
          and (worst is None or worst <= HOLDER_MAX_PCT))
    bits = []
    if top10 is not None:
        bits.append(f"top-10 {top10:.1f}%")
    if worst is not None:
        bits.append(f"holder terbesar {worst:.2f}%")
    n = len(pcts)
    if n:
        bits.append(f"{n} holder dicek")
    if not ok:
        bits.append(f"→ terkonsentrasi (batas {HOLDER_MAX_PCT:.0f}%)")
    else:
        bits.append(f"→ lolos batas holder {HOLDER_MAX_PCT:.0f}%")
    return _check("float_spread", "Float tersebar", ok, " | ".join(bits))


def criterion_absorption(snapshots):
    """Kriteria 4 — akumulasi tersebar **tanpa** kenaikan harga (**proxy**).

    PROXY, bukan CVD wallet-level: dari snapshot berurutan kita hitung net
    tekanan beli ``volume_1h x (buyShare - sellShare)`` dan memastikan harga
    tidak lari selama window. Ia **tidak** membedakan 1 entitas memakai 50
    wallet dari 50 pembeli independen — itu butuh penelusuran funder per
    wallet (Helius), di luar cakupan modul ini.
    """
    rows = [r for r in (snapshots or []) if isinstance(r, dict)]
    if len(rows) < MIN_SNAPSHOTS_ABSORPTION:
        return _check("absorption", "Akumulasi (proxy)", None,
                      f"butuh {MIN_SNAPSHOTS_ABSORPTION} snapshot, "
                      f"baru {len(rows)}")
    rows = sorted(rows, key=lambda r: r.get("ts") or 0)
    net = 0.0
    seen = 0
    for row in rows:
        vol = _num(row.get("vol_1h"))
        buys = _num(row.get("buys_1h"))
        sells = _num(row.get("sells_1h"))
        if vol is None or buys is None or sells is None:
            continue
        total = buys + sells
        if total <= 0:
            continue
        net += vol * ((buys - sells) / total)
        seen += 1
    if not seen:
        return _check("absorption", "Akumulasi (proxy)", None,
                      "tidak ada snapshot dengan volume + buys/sells")
    first = _num(rows[0].get("price"))
    last = _num(rows[-1].get("price"))
    if not first or last is None:
        return _check("absorption", "Akumulasi (proxy)", None,
                      "harga snapshot tidak lengkap")
    drift = (last / first) - 1.0
    sideways = abs(drift) <= ABSORPTION_MAX_DRIFT
    ok = net > 0 and sideways
    detail = (f"net tekanan beli {net:+,.0f} USD | drift harga {drift*100:+.1f}%"
              f" | {seen} snapshot")
    if not ok:
        detail += (" → harga sudah lari" if not sideways
                   else " → net negatif (distribusi)")
    return _check("absorption", "Akumulasi (proxy)", ok, detail)


def criterion_vol_expansion(snapshots):
    """Kriteria 5 — volume minimum lalu ekspansi bertahap (belum vertikal)."""
    rows = [r for r in (snapshots or []) if isinstance(r, dict)]
    vols = [(r.get("ts") or 0, _num(r.get("vol_1h")), _num(r.get("price")))
            for r in rows]
    vols = [v for v in vols if v[1] is not None]
    if len(vols) < MIN_SNAPSHOTS_ABSORPTION:
        return _check("vol_expansion", "Ekspansi volume", None,
                      f"butuh {MIN_SNAPSHOTS_ABSORPTION} snapshot volume, "
                      f"baru {len(vols)}")
    vols.sort(key=lambda v: v[0])
    values = [v[1] for v in vols]
    min_idx = values.index(min(values))
    trough = values[min_idx]
    latest = values[-1]
    if trough <= 0:
        return _check("vol_expansion", "Ekspansi volume", None,
                      "volume dasar nol, tidak bisa dibandingkan")
    expansion = latest / trough
    base_price = vols[min_idx][2]
    last_price = vols[-1][2]
    rise = (last_price / base_price) if (base_price and last_price) else None
    expanding = expansion >= VOL_EXPANSION_MIN_X
    not_vertical = (rise is None or rise < VOL_VERTICAL_MAX)
    ok = expanding and not_vertical and min_idx < len(values) - 1
    detail = (f"titik tersepi {trough:,.0f} → terakhir {latest:,.0f} "
              f"({expansion:.1f}x)")
    if rise is not None:
        detail += f" | harga {rise:.2f}x dari titik tersepi"
    if not expanding:
        detail += " → belum ada ekspansi"
    elif not not_vertical:
        detail += " → sudah vertikal (sweep, bukan base)"
    return _check("vol_expansion", "Ekspansi volume", ok, detail)


def criterion_shakeout(candles, *, lookback: int = 48):
    """Kriteria 6 — shakeout + higher low; expose timestamp for permanent latch.

    Candle sequence stays the source of initial detection. A previously stored
    latch is applied by :func:`evaluate`, so a later sweep below the old low
    does not erase an already-confirmed pattern.
    """
    rows = [c for c in (candles or []) if isinstance(c, (list, tuple))
            and len(c) >= 5]
    # Minimum 3 bar: one shakeout bar + at least one higher-low confirmation.
    if len(rows) < 3:
        return _check("shakeout", "Shakeout + higher low", None,
                      "candle belum cukup")
    rows = rows[-lookback:] if lookback else rows
    best = None
    for idx, row in enumerate(rows[:-1]):
        high, low = _num(row[2]), _num(row[3])
        if not high or low is None or high <= 0:
            continue
        drop = (high - low) / high
        if drop < SHAKEOUT_MIN_DROP:
            continue
        after = rows[idx + 1:]
        later_lows = [v for v in (_num(x[3]) for x in after) if v is not None]
        if not later_lows:
            continue
        higher_low = min(later_lows)
        if higher_low >= low * HIGHER_LOW_MIN:
            candidate = {
                "ts": row[0], "drop_pct": drop * 100.0, "low": low,
                "higher_low": higher_low,
                "lift_pct": (higher_low / low - 1.0) * 100.0,
                "bars_since": len(after),
            }
            if best is None or (row[0] or 0) > (best["ts"] or 0):
                best = candidate
    if best is None:
        return _check("shakeout", "Shakeout + higher low", False,
                      f"tidak ada shakeout >= {SHAKEOUT_MIN_DROP*100:.0f}% "
                      "dengan low lebih tinggi")
    detail = (f"shakeout {best['drop_pct']:.0f}% → low naik "
              f"{best['lift_pct']:+.1f}% ({best['bars_since']} bar lalu)")
    check = _check("shakeout", "Shakeout + higher low", True, detail)
    check["detection_ts"] = best["ts"]
    check["shakeout_low"] = best["low"]
    return check


def _shakeout_base_low(candles, latched_at):
    """Low candle dengan ``ts == latched_at`` (low shakeout), atau None."""
    latched_ts = _timestamp_seconds(latched_at)
    if latched_ts is None:
        return None
    for row in candles or []:
        if isinstance(row, (list, tuple)) and len(row) >= 4 \
                and _timestamp_seconds(row[0]) == latched_ts:
            low = _num(row[3])
            return low if low is not None and low > 0 else None
    return None


def shakeout_breach(candles, latched_at):
    """Low shakeout yang sudah dilatch lalu dilanggar candle sesudahnya.

    Low shakeout = low candle dengan ``ts == latched_at``. Pelanggaran = candle
    sesudahnya dengan low lebih rendah. Latch tetap berlaku (permanen); ini hanya
    tanda peringatan (permintaan user 2026-10-14, opsi 3). Mengembalikan
    ``{"low", "base_low", "ts"}`` atau ``None`` bila tidak dilanggar / low tidak
    ada di jendela candle.
    """
    latched_ts = _timestamp_seconds(latched_at)
    if latched_ts is None:
        return None
    rows = [c for c in (candles or []) if isinstance(c, (list, tuple)) and len(c) >= 4]
    base_low = None
    for row in rows:
        if _timestamp_seconds(row[0]) == latched_ts:
            base_low = _num(row[3])
            break
    if base_low is None or base_low <= 0:
        return None
    breach = None
    for row in rows:
        ts, low = _timestamp_seconds(row[0]), _num(row[3])
        if ts is None or low is None or ts <= latched_ts:
            continue
        if low < base_low and (breach is None or low < breach["low"]):
            breach = {"low": low, "base_low": base_low, "ts": int(ts)}
    return breach


def _latched_shakeout_check(check, latched_at, candles=None):
    """A stored timestamp makes shakeout permanently passed for that mint.

    Bila low shakeout kemudian dilanggar (lihat :func:`shakeout_breach`), kriteria
    tetap LOLOS tetapi ``breached`` = True dan keterangan memuat peringatan.
    """
    if latched_at is None:
        return check
    latched_ts = _timestamp_seconds(latched_at)
    timestamp = int(latched_ts) if latched_ts is not None else str(latched_at)
    detail = f"latch permanen sejak {timestamp}"
    breach = shakeout_breach(candles, latched_at)
    if breach is not None:
        detail += (f" · ⚠ low shakeout {breach['base_low']:.8g} dilanggar "
                   f"(low {breach['low']:.8g} pada {screen_time_wib(breach['ts'])})")
    result = _check("shakeout", "Shakeout + higher low", True, detail)
    result["latched_at"] = latched_at
    # Low shakeout disimpan untuk indikator info "low bertahan" (2026-10-28).
    result["shakeout_low"] = _shakeout_base_low(candles, latched_at)
    result["breached"] = breach is not None
    if breach is not None:
        result["breach"] = breach
    return result


def evaluate(metrics, *, snapshots=None, candles=None, cohort_candles=None,
             state=None, mint=None, now=None, cohort_error=None,
             cohort_latch=None):
    """Jalankan lima kriteria skor, gate authority, dan gate kohort sebelum vonis LAYAK.

    Ambang struktural fixed. Kohort memakai VWAP 48 jam pertama dari pool
    utama; shakeout yang sudah tersimpan di ``state.shakeout_latched_at`` tetap
    LOLOS walau candle terbaru menyapu low lamanya.
    """
    metrics = metrics or {}
    mint = mint or metrics.get("mint") or ""
    liq, fdv = _num(metrics.get("liq_usd")), _num(metrics.get("fdv_usd"))
    liq_mc = liq / fdv if liq is not None and fdv is not None and fdv > 0 else None

    shakeout = criterion_shakeout(candles)
    latches = (state or {}).get("shakeout_latched_at") or {}
    latched_at = latches.get(mint) if isinstance(latches, dict) else None
    shakeout = _latched_shakeout_check(shakeout, latched_at, candles)

    checks = [
        criterion_token_mc(metrics.get("pool_base_usd"), metrics.get("fdv_usd")),
        criterion_authority(metrics.get("mint_authority"),
                            metrics.get("freeze_authority"),
                            known=metrics.get("rugcheck_ok", True)),
        criterion_float_spread(metrics.get("top10_holder_pct"),
                               metrics.get("holder_pcts")),
        criterion_absorption(snapshots),
        criterion_vol_expansion(snapshots),
        shakeout,
    ]
    scored = [c for c in checks if c.get("scored", True)]
    with_data = [c for c in scored if c["has_data"]]
    passed = [c for c in with_data if c["passed"]]
    score = (len(passed) / len(with_data)) if with_data else None
    structural_ok = all(
        any(c["key"] == key and c["passed"] for c in checks)
        for key in ELIGIBLE_STRUCTURAL
    )
    required = min(ELIGIBLE_MIN_PASSED, len(with_data))

    cohort = cohort_profile(cohort_candles, metrics.get("pair_created_at"),
                            metrics.get("price_usd"), now=now,
                            fetch_error=cohort_error)
    gmgn_status = gmgn_cohort_status(metrics.get("holder_cost_basis"),
                                     metrics.get("holder_cost_balance"),
                                     metrics.get("price_usd"))
    cohort["gmgn_status_avg_cost"] = gmgn_status
    gate = cohort_gate(cohort)
    # Latch kohort (2026-10-14): kohort yang pernah ≤ −50% tetap lolos walau harga
    # kini naik. Menggantikan semua status TUNGGU kohort (belum minus 50% VWAP/GMGN,
    # dan GMGN plus); SKIP kohort PLUS dan TANPA DATA tidak berubah.
    if (cohort_latch and not gate["passed"]
            and str(gate["status"]).startswith(COHORT_WAIT_PREFIX)):
        when = screen_time_wib(cohort_latch.get("ts"))
        gate = {"passed": True,
                "status": "LOLOS — pernah ≤ −50% (latch)",
                "detail": (f"kohort pernah ≤ −50% ({cohort_latch.get('source') or '—'}"
                           f", {when}); kini {gate['status']}")}
    # Biaya 10x hanya informasi (gate 28% dihapus 2026-10-15).
    cost_10x_mc_frac = leverage_cost(COST_GATE_MULT, liq_mc)
    # Gate avg buy holder: dicek setelah gate kohort; keduanya harus lolos.
    holder_gate = holder_cost_gate(metrics.get("holder_min_avg_cost"),
                                   metrics.get("price_usd"))
    score_ok = (score is not None and len(passed) >= required and structural_ok)
    eligible = bool(gate["passed"] and holder_gate["passed"] and score_ok)
    # Gate holder yang sudah terhitung (TUNGGU, bukan "belum ada data") tetap
    # tampil walau kohort TANPA DATA: data holder tidak bergantung pada candle.
    verdict, color = decide_verdict(gate, holder_gate, score=score,
                                    passed_count=len(passed), score_ok=score_ok)

    vol24 = _num(metrics.get("vol24_usd"))
    if vol24 is None:
        vol24 = _num(metrics.get("vol_24h"))
    turnover_x = (vol24 / liq if vol24 is not None and liq is not None and liq > 0
                  else None)
    cost_3x_mc_frac = leverage_cost(3.0, liq_mc)
    # UI column "× dana acuan" = ((√10−1)×(liq/MC÷2)) ÷ 14,0%, where
    # 14,0% = COCK's 10x cost $32,684 / $233,451; its one-sided cash basis makes COCK 1.0×.
    reference_fund_x = reference_fund_multiple(liq_mc)
    # Nominal $ untuk "× dana acuan": (√10−1) x (liq/2), sama dengan
    # reference_fund_x x 14,0% MC (basis kas satu sisi seperti di atas).
    reference_fund_usd = cost_usd(REFERENCE_MULT, liq) if liq is not None else None
    return {
        "checks": checks,
        "passed_count": len(passed),
        "scored_count": len(with_data),
        "required_count": required,
        "score": score,
        "structural_ok": structural_ok,
        "eligible": eligible,
        "verdict": verdict,
        "color": color,
        "liq_mc": liq_mc,
        "targets": target_costs(liq_mc, liq_usd=liq) if liq_mc else [],
        "cost_3x_mc_frac": cost_3x_mc_frac,
        "cost_10x_mc_frac": cost_10x_mc_frac,
        "holder_min_avg_cost": _num(metrics.get("holder_min_avg_cost")),
        "holder_gap": holder_gate["gap"],
        "holder_gate_status": holder_gate["status"],
        "holder_gate_passed": holder_gate["passed"],
        "holder_gate_detail": holder_gate["detail"],
        "reference_fund_x": reference_fund_x,
        "reference_fund_usd": reference_fund_usd,
        "turnover_x": turnover_x,
        "cohort": cohort,
        "gmgn_status_avg_cost": gmgn_status,
        "cohort_gate_status": gate["status"],
        "cohort_gate_passed": gate["passed"],
        "cohort_gate_detail": gate["detail"],
        "missing": [c["key"] for c in checks if not c["has_data"]],
        # Info saja: tidak dipakai untuk vonis, eligible, urutan, atau filter.
        "order_flow": order_flow_info(candles),
    }


# ---------------------------------------------------------------------------
# Deteksi sweep
# ---------------------------------------------------------------------------
def _sqrt(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return math.sqrt(value) if value >= 0 else None


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def detect_sweep(candles, *, spike_mult: float = SWEEP_VOL_MULT,
                 price_mult: float = SWEEP_PRICE_MULT,
                 baseline_bars: int = SWEEP_BASELINE_BARS):
    """Cari candle sweep terakhir di deret candle.

    Sweep = satu candle dengan volume ``>= spike_mult x`` median ``baseline_bars``
    candle sebelumnya **dan** harga penutup ``>= price_mult x`` harga penutup
    sebelum candle itu. Mengembalikan ``None`` bila tidak ada.
    """
    rows = [c for c in (candles or []) if isinstance(c, (list, tuple))
            and len(c) >= 6]
    if len(rows) < 3:
        return None
    for idx in range(len(rows) - 1, 0, -1):
        row = rows[idx]
        ts = row[0]
        close = _num(row[4])
        vol = _num(row[5])
        prev_close = _num(rows[idx - 1][4])
        if vol is None or close is None or not prev_close:
            continue
        start = max(0, idx - baseline_bars)
        baseline = _median([_num(x[5]) for x in rows[start:idx]])
        if not baseline or baseline <= 0:
            continue
        vol_x = vol / baseline
        if vol_x < spike_mult:
            continue
        if close / prev_close < price_mult:
            continue
        peak = _num(row[2]) or close
        low_v = _num(row[3])
        mult = close / prev_close
        return {
            "ts": ts,
            "index": idx,
            "base_price": prev_close,
            "close": close,
            "peak": peak,
            "low": low_v,
            "vol": vol,
            "baseline_vol": baseline,
            "vol_x": vol_x,
            "price_mult": mult,
            "range_pct": (((peak - low_v) / low_v * 100.0)
                          if (peak and low_v) else None),
            "bars_ago": len(rows) - 1 - idx,
        }
    return None


#: Order flow (info saja, 2026-10-15): dibaca dari candle jam yang sudah ada.
#: Tidak memengaruhi kriteria, skor, vonis, ``eligible``, urutan, maupun filter.
ORDER_FLOW_LOOKBACK = 20   # jam: jendela struktur untuk BOS dan sweep low
ORDER_FLOW_POC_BARS = 48   # jam: jendela volume profile
ORDER_FLOW_BINS = 24       # jumlah level harga pada volume profile
ORDER_FLOW_WICK_MIN = 0.5  # ekor bawah minimal 50% dari range candle
ORDER_FLOW_LABELS = {
    "bos_up": "BOS naik (close di atas high {n} jam sebelumnya)",
    "sweep_reclaim": "sweep low lalu reclaim (low menembus {n} jam, close kembali di atas)",
    "wick_rejection": "ekor bawah panjang, close di separuh atas (penolakan harga bawah)",
}


def _order_flow_rows(candles):
    rows = []
    for c in candles or []:
        if not isinstance(c, (list, tuple)) or len(c) < 6:
            continue
        vals = [_num(x) for x in c[:6]]
        if any(v is None for v in vals[:5]):
            continue
        ts, o, h, low, close, vol = vals[0], vals[1], vals[2], vals[3], vals[4], vals[5] or 0.0
        if h < low or low <= 0:
            continue
        rows.append((ts, o, h, low, close, vol))
    return sorted(rows, key=lambda r: r[0])


def order_flow_info(candles, *, lookback: int = ORDER_FLOW_LOOKBACK,
                    poc_bars: int = ORDER_FLOW_POC_BARS,
                    bins: int = ORDER_FLOW_BINS):
    """Pola order flow dari candle jam (info saja, tidak masuk vonis).

    - ``bos_up``: close candle terakhir di atas high ``lookback`` jam sebelumnya.
    - ``sweep_reclaim``: low candle terakhir menembus low ``lookback`` jam
      sebelumnya, tetapi close kembali di atasnya.
    - ``wick_rejection``: ekor bawah ≥ 50% range dan close di separuh atas.
    - Volume node: POC = pusat level harga dengan volume terbanyak pada
      ``poc_bars`` jam terakhir (volume tiap candle dialokasikan ke level close-nya).
    """
    rows = _order_flow_rows(candles)
    need = lookback + 1
    if len(rows) < need:
        return {"available": False, "flags": [], "labels": [],
                "poc_price": None, "poc_dist": None,
                "reason": f"butuh {need} candle jam, baru {len(rows)}"}
    _ts, o, h, low, close, _vol = rows[-1]
    prior = rows[-1 - lookback:-1]
    prior_high = max(r[2] for r in prior)
    prior_low = min(r[3] for r in prior)
    flags = []
    if close > prior_high:
        flags.append("bos_up")
    if low < prior_low and close > prior_low:
        flags.append("sweep_reclaim")
    rng = h - low
    if rng > 0:
        lower_wick = (min(o, close) - low) / rng
        if lower_wick >= ORDER_FLOW_WICK_MIN and close >= (h + low) / 2:
            flags.append("wick_rejection")
    poc_price = poc_dist = None
    window = rows[-poc_bars:] if poc_bars > 0 else []
    lo = min((r[3] for r in window), default=None)
    hi = max((r[2] for r in window), default=None)
    total_vol = sum(r[5] for r in window)
    if lo is not None and hi is not None and hi > lo and total_vol > 0 and bins > 0:
        width = (hi - lo) / bins
        buckets = [0.0] * bins
        for r in window:
            idx = min(bins - 1, max(0, int((r[4] - lo) / width)))
            buckets[idx] += r[5]
        top = max(range(bins), key=lambda i: buckets[i])
        poc_price = lo + (top + 0.5) * width
        if poc_price > 0:
            poc_dist = close / poc_price - 1.0
    labels = [ORDER_FLOW_LABELS[f].format(n=lookback) for f in flags]
    return {"available": True, "flags": flags, "labels": labels,
            "poc_price": poc_price, "poc_dist": poc_dist,
            "bars": len(rows), "lookback": lookback, "poc_bars": poc_bars}


#: Delta dari trade (info saja, 2026-10-15). Trade GMGN per jam: delta = beli − jual
#: (USD), CVD = jumlah delta dalam jendela. Tidak memengaruhi vonis atau urutan.
DELTA_WINDOW_HOURS = 6        # jendela CVD
DELTA_MAX_PAGES = 10          # batas halaman GMGN per mint (100 trade/halaman)
DELTA_BUCKET_SEC = 3600       # satu bucket = satu jam (sama dengan candle jam)
DELTA_ABSORB_PCT = 0.20       # delta ≥ +20% dari volume jam, harga tidak naik
DELTA_SPIKE_PCT = 0.50        # |delta| ≥ 50% dari volume jam ...
DELTA_FLAT_PRICE = 0.02       # ... tetapi harga bergerak < 2%
DELTA_LABELS = {
    "div_bearish": "divergensi bearish: harga high baru, CVD lebih rendah dari high sebelumnya",
    "absorb": "penyerapan: delta beli kuat, harga tidak naik",
    "spike_no_progress": "delta ekstrem tanpa kemajuan harga (liquidity grab, bukan breakout)",
}


def delta_candidate(result) -> bool:
    """Mint yang layak diambil trade-nya: kohort minus/tunggu, bukan SKIP/TANPA DATA/TIDAK LAYAK."""
    result = result or {}
    if is_tidak_layak(result):
        return False
    status = str(result.get("cohort_gate_status") or "")
    return status.startswith(("TUNGGU", "LOLOS"))


def delta_info(trades, candles, *, now, complete: bool = True,
               window_hours: int = DELTA_WINDOW_HOURS,
               bucket_sec: int = DELTA_BUCKET_SEC):
    """Delta dan CVD per jam dari trade ter-normalisasi (info saja).

    ``trades`` = iterable tuple ``(side, usd, ts)`` dengan side ``buy``/``sell``.
    ``candles`` = candle jam ``[ts, o, h, l, c, v]`` untuk harga per bucket.
    Jam tanpa trade dihitung delta 0. CVD dimulai dari awal jendela.
    """
    now = int(now)
    end = (now // bucket_sec) * bucket_sec
    start = end - (window_hours - 1) * bucket_sec
    buckets = {}
    count = 0
    for trade in trades or []:
        try:
            side, usd, ts = trade[0], float(trade[1]), int(trade[2])
        except (TypeError, ValueError, IndexError):
            continue
        if side not in ("buy", "sell") or usd <= 0 or ts < start or ts > now:
            continue
        key = (ts // bucket_sec) * bucket_sec
        item = buckets.setdefault(key, {"buy": 0.0, "sell": 0.0})
        item[side] += usd
        count += 1
    if count == 0:
        reason = ("data trade tidak lengkap" if not complete
                  else f"tidak ada trade dalam {window_hours} jam")
        return {"available": False, "complete": bool(complete), "reason": reason,
                "trades": 0, "flags": [], "labels": []}
    prices = {}
    for row in _order_flow_rows(candles):
        prices[int(row[0])] = row[4]
    rows, cvd = [], 0.0
    for key in range(start, end + 1, bucket_sec):
        item = buckets.get(key, {"buy": 0.0, "sell": 0.0})
        delta = item["buy"] - item["sell"]
        total = item["buy"] + item["sell"]
        cvd += delta
        rows.append({"ts": key, "buy": item["buy"], "sell": item["sell"],
                     "delta": delta,
                     "delta_pct": (delta / total) if total > 0 else 0.0,
                     "cvd": cvd, "price": prices.get(key)})
    # Harga dan delta jam terakhir dibandingkan dengan jam sebelumnya yang punya harga.
    last = rows[-1]
    prior_priced = [r for r in rows[:-1] if r["price"]]
    price_chg = None
    if last["price"] and prior_priced:
        price_chg = last["price"] / prior_priced[-1]["price"] - 1.0
    flags = []
    if last["price"] and prior_priced:
        high = max(r["price"] for r in prior_priced)
        if last["price"] > high:
            at_high = [r for r in prior_priced if r["price"] == high][-1]
            if last["cvd"] < at_high["cvd"]:
                flags.append("div_bearish")
    total_last = last["buy"] + last["sell"]
    if total_last > 0 and price_chg is not None:
        if last["delta_pct"] >= DELTA_ABSORB_PCT and price_chg <= 0:
            flags.append("absorb")
        if (abs(last["delta_pct"]) >= DELTA_SPIKE_PCT
                and abs(price_chg) < DELTA_FLAT_PRICE):
            flags.append("spike_no_progress")
    return {
        "available": True, "complete": bool(complete), "trades": count,
        "window_hours": window_hours,
        "buy_usd": sum(v["buy"] for v in buckets.values()),
        "sell_usd": sum(v["sell"] for v in buckets.values()),
        "cvd_usd": cvd,
        "last": {k: last[k] for k in ("ts", "buy", "sell", "delta", "delta_pct", "price")}
                | {"price_chg": price_chg},
        "flags": flags,
        "labels": [DELTA_LABELS[f] for f in flags],
        "buckets": [{k: r[k] for k in ("ts", "delta", "cvd", "price")}
                    for r in rows[-window_hours:]],
    }


def sweep_context(event, liq_mc, fdv_usd, *, market_cap_usd=None,
                  price_usd=None, liq_usd=None, net_inflow_usd=None):
    """Perkaya event sweep dengan rumus biaya dorong ke puncak, paper gain, dan churn.

    Berdasarkan rekonstrusi reserve COCKROACH 1 Okt 2026: likuiditas naik dari
    $30.232 → $89.010 (Δ $58.778), dan ``akar(8,669) = 2,9442`` sama dengan
    rasio likuiditas 89.010/30.232 = 2,9442. Artinya uang yang masuk ke pool
    dipakai membeli **seluruh ekskursi sampai puncak**, bukan berhenti di harga
    close.

    Tiga harga dalam satu candle sweep harus dibedakan (jangan dicampur):

    ``peak`` (harga tertinggi dalam candle)
        Puncak candle sweep COCKROACH = 0,00206033 → **8,669×** dari harga
        dasar 0,00023768. Uang masuk $29.389 ≈ biaya dorong ke puncak
        ``(akar(8,669) - 1) × $30.232 / 2 = $29.388``.
    ``close`` (harga penutupan candle)
        Close COCKROACH = 0,00076674 → hanya 3,226× dari dasar. Biaya dorong
        ke close = ``(akar(3,226) - 1) × $30.232 / 2 = $12.033`` — angka lama yang
        sebelah karena penggunaan close sebagai referensi berlebih 2,44×.
    ``base_price`` (harga sebelum candle sweep)
        Harga tenang 22:41 WIB = 0,00023768.

    Enam angka yang harus dibedakan (dua besaran "paper" pun berbeda):

    ``est_cost_usd``
        **Biaya dorong ke PUNCAK**: ``(akar(peak_mult) - 1) × liq / 2``. Uang
        quote yang masuk ke pool supaya harga sampai ke puncak candle, kalau
        tidak ada pembeli lain. COCKROACH 1 Okt = $29.389 (= 12,6% MC).
    ``est_cost_close_usd``
        **Biaya dorong ke CLOSE**: ``(akar(price_mult) - 1) × liq / 2``. Angka
        yang salah dipakai sebelumnya karena menggunakan close sebagai referensi.
        COCKROACH 1 Okt = $12.033 (bedanya > 2× dari biaya ke puncak).
    ``paper_gain_usd``
        **Kenaikan MC kertas sampai puncak**: ``supply × (peak - base_price)``.
        Nilai riil COCKROACH 1 Okt = $1.790.194 (dari supply ≈ 982jt × (0,00206033
        - 0,00023768)).
    ``paper_mcap_usd``
        **MC kertas di CLOSE**: ``supply × close``. Besaran **berbeda** dari
        paper_gain — COCKROACH = $752.939. Jangan dipakai sebagai pembilang
        leverage (itu salah karena underestimate).
    ``net_inflow_usd``
        **Uang quote yang masuk ke pool**: selisih likuiditas (TVL dua sisi)
        antar snapshot dibagi dua. COCKROACH 1 Okt = Δ TVL $58.778 ÷ 2 =
        $29.389 — ≈ biaya dorong ke puncak ($29.388),
        artinya sweep itu tidak menarik pembeli luar (semua uang yang masuk
        dipakai ke puncak). Kalau tidak ada data snapshot, diisi ``None``
        (jangan menebak).
    ``churn_x`` / ``churn_net_x``
        volume candle sweep ÷ biaya ke puncak (**teoretis**) versus ÷ inflow
        nyata (**nyata**). COCKROACH: keduanya ≈ 42,3× karena inflow ≈ biaya
        ke puncak. Kalau ``churn_net_x < churn_x × 0,9`` → ada pembeli luar
        ikut masuk.

    ``leverage`` = ``paper_gain ÷ est_cost`` = ``(akar(peak_mult) + 1) / (liq/MC_dasar/2)``
        (MC dasar, bukan MC sekarang — sama dengan paper_gain yang juga dari MC dasar)
        COCKROACH: ``(akar(8,669) + 1) / 6,475% = 3,944 / 0,06475 = 60,9×``,
        cocok dengan ``$1.790.194 / $29.389 = 60,9×``.

    Catatan: semua angka "paper" (paper_gain, paper_mcap) adalah **teoretis** — nilai
    yang akan ada jika harga bertahan. Angka "terukur" hanya ``est_cost_usd``
    (teoretis tapi deterministik dari reserve) dan ``net_inflow_usd`` (Δ
    likuiditas aktual).
    """
    if not event:
        return None
    enriched = dict(event)
    mc = _num(market_cap_usd) or _num(fdv_usd)
    price_mult = _num(event.get("price_mult"))
    peak = _num(event.get("peak"))
    base_price = _num(event.get("base_price"))
    close = _num(event.get("close"))
    price_now = _num(price_usd)
    liq = _num(liq_usd)
    if liq is None and mc and _num(liq_mc) is not None:
        liq = _num(liq_mc) * mc

    # Supply (jumlah token beredar) stabil di dalam satu candle, jadi MC di
    # titik mana pun bisa dihitung dari supply x harga.
    supply = (mc / price_now) if (mc and price_now) else None
    if supply is not None and base_price:
        base_mcap = supply * base_price
    else:
        base_mcap = mc
    if supply is not None and close:
        paper_mcap = supply * close
    elif mc and price_mult:
        paper_mcap = price_mult * mc
    else:
        paper_mcap = None

    # peak_mult = puncak / harga dasar. Fallback ke price_mult kalau peak tidak
    # tersedia (candle tanpa high yang terekam — tidak seharusnya terjadi).
    if peak and base_price:
        peak_mult = peak / base_price
    elif price_mult:
        peak_mult = price_mult
        # Kalau fallback dipakai, peak diisi ulang supaya konsisten.
        if base_price:
            peak = peak_mult * base_price
    else:
        peak_mult = None

    # --- Biaya dorong ke PUNCAK (bukan ke close) ---
    cost_frac = leverage_cost(peak_mult, liq_mc)
    enriched["liq_mc"] = _num(liq_mc)
    enriched["liq_usd"] = liq
    enriched["est_cost_frac"] = cost_frac
    enriched["est_cost_usd"] = ((_sqrt(peak_mult) - 1.0) * liq / 2.0
                                if (peak_mult and peak_mult > 0 and liq) else None)
    enriched["base_mcap_usd"] = base_mcap
    enriched["paper_mcap_usd"] = paper_mcap

    # --- Biaya dorong ke CLOSE (untuk perbandingan, bukan penggunaan utama) ---
    if price_mult and price_mult > 0 and liq:
        enriched["est_cost_close_usd"] = (_sqrt(price_mult) - 1.0) * liq / 2.0
    else:
        enriched["est_cost_close_usd"] = None

    # --- Kenaikan MC kertas sampai puncak (bukan MC di close) ---
    if supply is not None and peak and base_price:
        enriched["paper_gain_usd"] = supply * (peak - base_price)
    else:
        enriched["paper_gain_usd"] = None

    # Leverage = kenaikan MC kertas (dari MC DASAR) ÷ biaya dorong ke puncak.
    # Sebelumnya memakai liq/MC SEKARANG (MC kini), padahal kenaikan kertas
    # diukur dari MC dasar — hasilnya bias. Sekarang kedua sisi memakai basis
    # yang sama; tanpa salah satunya = None (bukan tebakan).
    gain, cost = enriched["paper_gain_usd"], enriched["est_cost_usd"]
    enriched["leverage"] = (gain / cost
                            if (gain and cost and gain > 0 and cost > 0)
                            else None)
    enriched["sweep_ts"] = _num(event.get("ts"))

    # --- peak_mult untuk sinyal ---
    enriched["peak_mult"] = peak_mult

    # Inflow nyata hanya dari pengukuran (selisih liq snapshot) — bukan tebakan.
    # Δ likuiditas adalah TVL dua sisi; uang quote yang masuk = Δ TVL / 2
    # (dalam CPMM TVL = 2y, jadi ΔTVL = 2Δy). Satuannya disamakan dengan biaya.
    inflow_tvl = _num(net_inflow_usd)
    inflow = inflow_tvl / 2.0 if inflow_tvl is not None else None
    enriched["net_inflow_usd"] = inflow
    enriched["net_inflow_is_estimate"] = inflow is None
    if inflow is None and enriched["est_cost_usd"]:
        # Acuan kalibrasi 1 event (COCKROACH 1 Okt: $58.778 / $58.774 ≈ 1,0x)
        # ditandai jelas sebagai estimasi, bukan angka terukur.
        enriched["net_inflow_ref_usd"] = enriched["est_cost_usd"] * REF_NET_COST_MULT
    else:
        enriched["net_inflow_ref_usd"] = None

    vol = _num(event.get("vol"))
    enriched["churn_x"] = (vol / enriched["est_cost_usd"]
                           if (vol and enriched["est_cost_usd"]) else None)
    enriched["churn_net_x"] = (vol / inflow if (vol and inflow and inflow > 0)
                               else None)
    # leverage_net pakai paper_gain (bukan paper_mcap di close).
    enriched["leverage_net"] = (enriched["paper_gain_usd"] / inflow
                                if (enriched["paper_gain_usd"] and inflow
                                    and inflow > 0) else None)
    return enriched


def summarize_signals(signals):
    """Statistik tabel riwayat sinyal (untuk tab Statistik)."""
    rows = [s for s in (signals or []) if isinstance(s, dict)]
    ups = [_num(s.get("max_up_pct")) for s in rows]
    downs = [_num(s.get("max_down_pct")) for s in rows]
    ups = [u for u in ups if u is not None]
    downs = [d for d in downs if d is not None]
    wins = [u for u in ups if u >= 100.0]
    reasons = [u for u in ups if u >= 300.0]
    churns = [_num(s.get("churn_x")) for s in rows]
    churns = [c for c in churns if c is not None]
    churns_net = [_num(s.get("churn_net_x")) for s in rows]
    churns_net = [c for c in churns_net if c is not None]
    return {
        "n": len(rows),
        "n_tracked": len(ups),
        "n_win_100": len(wins),
        "n_win_300": len(reasons),
        "hit_rate_100": (len(wins) / len(ups)) if ups else None,
        "hit_rate_300": (len(reasons) / len(ups)) if ups else None,
        "median_up": _median(ups),
        "mean_up": (sum(ups) / len(ups)) if ups else None,
        "median_down": _median(downs),
        "worst_down": min(downs) if downs else None,
        "median_churn": _median(churns),
        "n_churn_net": len(churns_net),
        "median_churn_net": _median(churns_net),
    }


def breakeven_hit_rate(win_pct, loss_pct):
    """Hit rate impas untuk payoff ``+win_pct`` vs ``-loss_pct`` (dalam persen)."""
    win, loss = _num(win_pct), _num(loss_pct)
    if win is None or loss is None or win <= 0 or loss <= 0:
        return None
    return loss / (win + loss)


# ---------------------------------------------------------------------------
# CVD & delta sejak harga di bawah lowest avg buy (info saja, 2026-10-20)
# ---------------------------------------------------------------------------
# Episode dimulai pada scan pertama ketika harga ≤ lowest avg buy (holder
# termurah) DAN mint lolos (tidak tersembunyi oleh filter/TIDAK LAYAK, dan
# kandidat delta). Episode berakhir saat harga kembali di atas lowest avg buy.
# Mint yang tersembunyi tidak dihitung; episode yang sudah terbuka tetap
# terbuka (dijeda) dan lanjut bila mint lolos lagi dalam keadaan di bawah.
# Tidak memengaruhi vonis, skor, eligible, urutan, atau filter.
FLOW_MAX_HOURS = 24  # jendela maksimum; trade sebelum 24 jam lalu tidak diambil
FLOW_MAX_PAGES = 20  # batas halaman GMGN per mint per scan (100 trade/halaman)


def flow_eligible(result, metrics) -> bool:
    """Mint lolos untuk perhitungan episode: tampil di tabel utama dan kandidat delta."""
    result = result or {}
    if not delta_candidate(result):
        return False
    return not view_hidden({"result": result, "metrics": metrics or {}})


def below_lowest_buy(price, min_avg_cost):
    """True bila harga ≤ lowest avg buy. None bila data belum lengkap."""
    price = _num(price)
    low = _num(min_avg_cost)
    if price is None or low is None or price <= 0 or low <= 0:
        return None
    return price <= low


def flow_backfill_start(history, min_avg_cost):
    """Perkiraan awal episode dari riwayat snapshot.

    Bucket terakhir yang harganya ≤ lowest avg buy, ditarik mundur selama
    bucket sebelumnya juga ≤ lowest buy. Dipakai hanya bila episode baru akan
    dimulai, supaya CVD tidak mulai dari nol setelah scan pertama. Lowest buy
    yang dipakai adalah nilai SAAT INI (riwayat lowest buy tidak tersimpan).
    Mengembalikan ``{"ts", "price"}`` atau ``None``.
    """
    low = _num(min_avg_cost)
    if low is None or low <= 0:
        return None
    rows = []
    for row in history or []:
        if not isinstance(row, dict):
            continue
        ts, price = _num(row.get("ts")), _num(row.get("price"))
        if ts is not None and price is not None and price > 0:
            rows.append((ts, price))
    if not rows:
        return None
    rows.sort()
    if rows[-1][1] > low:
        return None
    start = rows[-1]
    for ts, price in reversed(rows[:-1]):
        if price > low:
            break
        start = (ts, price)
    return {"ts": int(start[0]), "price": start[1]}


def flow_episode_step(entry, *, price, min_avg_cost, eligible: bool, now: int,
                      start_hint=None) -> dict:
    """Perbarui episode satu mint. Mengembalikan entri baru ``{active, past}``.

    - Data harga/lowest buy belum ada → entri tidak berubah.
    - Tidak ada episode aktif, harga ≤ lowest buy, dan mint lolos → mulai episode.
    - Episode aktif dan harga kembali di atas lowest buy → episode selesai
      (masuk ``past``), apa pun status tampilannya.
    """
    entry = dict(entry or {})
    active = entry.get("active")
    past = list(entry.get("past") or [])
    below = below_lowest_buy(price, min_avg_cost)
    if below is None:
        return {"active": active, "past": past}
    now = int(now)
    if active is None:
        if below and eligible:
            if start_hint:
                start_ts = int(start_hint["ts"])
                start_price = _num(start_hint.get("price"))
                source = "riwayat snapshot (perkiraan)"
            else:
                start_ts, start_price = now, _num(price)
                source = "scan live"
            active = {"start_ts": start_ts, "start_price": start_price,
                      "start_source": source,
                      "min_avg_start": _num(min_avg_cost),
                      "hourly": {}, "last": None}
    elif not below:
        closed = dict(active)
        closed.update({"end_ts": now, "end_price": _num(price)})
        past = [closed] + past
        active = None
    return {"active": active, "past": past}


def flow_info(trades, candles, *, now: int, start_ts: int, complete: bool = True,
              max_hours: int = FLOW_MAX_HOURS) -> dict:
    """CVD dan delta sejak ``start_ts`` (dibatasi ``max_hours`` terakhir).

    ``trades`` = tuple ``(side, usd, ts)``. Trade sebelum jendela dibuang.
    Mengembalikan hasil :func:`delta_info` ditambah penanda jendela.
    """
    now = int(now)
    start_ts = int(start_ts)
    since = max(start_ts, now - int(max_hours) * 3600)
    # delta_info memakai bucket jam penuh dan mundur dari jam sekarang. Agar
    # bucket pertama memuat ``since``, jumlahnya dihitung dari jam awal ``since``.
    end_bucket = (now // 3600) * 3600
    start_bucket = (since // 3600) * 3600
    hours = max(1, (end_bucket - start_bucket) // 3600 + 1)
    inside = []
    for trade in trades or []:
        try:
            if int(trade[2]) >= since:
                inside.append(trade)
        except (TypeError, ValueError, IndexError):
            continue
    info = delta_info(inside, candles, now=now, complete=complete,
                      window_hours=hours)
    info["start_ts"] = start_ts
    info["since_ts"] = since
    info["covers_start"] = since == start_ts
    return info


def flow_record(info, *, price, now: int) -> dict:
    """Ringkasan satu pengukuran (disimpan per jam di episode)."""
    info = info or {}
    last = info.get("last") or {}
    return {
        "ts": int(now),
        "price": _num(price),
        "available": bool(info.get("available")),
        "complete": bool(info.get("complete")),
        "covers_start": bool(info.get("covers_start")),
        "reason": info.get("reason") or "",
        "trades": int(info.get("trades") or 0),
        "buy_usd": info.get("buy_usd"),
        "sell_usd": info.get("sell_usd"),
        "cvd_usd": info.get("cvd_usd"),
        "delta_last_usd": last.get("delta"),
        "flags": list(info.get("flags") or []),
        "labels": list(info.get("labels") or []),
    }


def flow_rows(rows, flows) -> list:
    """Baris tabel CVD/delta: hanya mint lolos yang sedang di bawah lowest avg buy.

    ``rows`` = baris tabel utama (sudah tanpa yang tersembunyi). Baris di atas
    lowest avg buy dan baris tanpa episode aktif tidak dimasukkan.
    """
    out = []
    for row in rows or []:
        mint = row.get("mint")
        result = row.get("result") or {}
        metrics = row.get("metrics") or {}
        entry = (flows or {}).get(mint) or {}
        active = entry.get("active")
        if not active or not active.get("last"):
            continue
        if not delta_candidate(result):
            continue
        low = _num(result.get("holder_min_avg_cost"))
        price = _num(metrics.get("price_usd"))
        if not below_lowest_buy(price, low):
            continue
        last = active["last"]
        start_price = _num(active.get("start_price"))
        out.append({
            "mint": mint,
            "symbol": metrics.get("symbol") or (mint or "")[:8],
            "start_ts": active.get("start_ts"),
            "hours": round((int(last.get("ts") or 0) - int(active.get("start_ts") or 0)) / 3600, 2),
            "start_price": start_price,
            "start_source": active.get("start_source") or "",
            "price": price,
            "price_move": (price / start_price - 1.0) if start_price and price else None,
            "lowest_buy": low,
            "vs_lowest": (price / low - 1.0) if low and price else None,
            "buy_usd": last.get("buy_usd"),
            "sell_usd": last.get("sell_usd"),
            "cvd_usd": last.get("cvd_usd"),
            "delta_last_usd": last.get("delta_last_usd"),
            "available": bool(last.get("available")),
            "complete": bool(last.get("complete")),
            "covers_start": bool(last.get("covers_start")),
            "reason": last.get("reason") or "",
            "labels": list(last.get("labels") or []),
        })
    return out
