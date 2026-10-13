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

# --- ambang tetap kriteria (satu tempat, biar mesin, UI & test tidak menyimpang) ---
LIQ_MC_MAX = 0.35          # kriteria 1: liq/MC maksimum 35%, tetap
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
# (=4,74% MC). Toleransi 3x dana acuan = $33.198 (~14,2% MC).
COCK_REFERENCE_MC_USD = 233_451.0
COCK_REFERENCE_CASH_USD = 15_116.0
COCK_REFERENCE_COST_3X_USD = 11_066.0
COCK_REFERENCE_COST_3X_MC_FRAC = (COCK_REFERENCE_COST_3X_USD /
                                  COCK_REFERENCE_MC_USD)
COHORT_WINDOW_HOURS = 48
#: Ambang minimum kohort: VWAP kelahiran harus minus minimal 50% dari harga
#: kini (status_avg_cost ≤ -0,50). Diturunkan dari -70% atas permintaan user
#: 2026-10-13.
COHORT_MINUS_THRESHOLD = -0.50

#: Gate biaya (2026-10-13, permintaan user): biaya sweep untuk naik
#: ``COST_GATE_MULT`` kali harus ≤ 75% market cap. Di atas itu, atau bila belum
#: ada data, vonis = TUNGGU. Ambang tetap, tidak dapat diubah dari UI/cron.
COST_GATE_MULT = 10.0
COST_GATE_MAX_FRAC = 0.75

#: Acuan kalibrasi inflow nyata vs biaya dorong ke puncak, dari satu event
#: terukur: COCKROACH 1 Okt 2026 — inflow nyata $58.778 ÷ biaya dorong ke
#: puncak $58.774 = 1,0x (selisih < $4, dalam boltjang). Konstanta ini dipakai
#: hanya sebagai **estimasi berlabel** saat selisih likuiditas antar snapshot
#: belum tersedia; begitu ada pengukuran nyata, angka nyata yang dipakai
#: (jangan mencampur keduanya).
REF_NET_COST_MULT = 1.0

# --- ambang deteksi sweep ---
SWEEP_VOL_MULT = 20.0      # volume candle sweep >= 20x median baseline
SWEEP_PRICE_MULT = 1.5     # harga naik >= 1,5x dari harga dasar
SWEEP_BASELINE_BARS = 24   # baseline = 24 candle sebelum kandidat

# --- standar struktural tetap ---
# Basis cash-side untuk pembanding acuan: (√3−1)×(35%÷2) = 12,8% MC,
# di bawah toleransi COCK 3×$11.066 / $233.451 = 14,2% MC. Estimator biaya
# aktual est_cost/leverage tetap memakai liq dua sisi; hasilnya 25,6% MC di
# rasio 35% dan sengaja tidak di-rebase. Holder per-wallet maksimum 5%.

#: Minimal kriteria lulus untuk vonis LAYAK — tapi ambangnya menyesuaikan
#: berapa kriteria yang **sudah punya data**: di deploy baru hanya trio
#: struktural (1+2+3) yang bisa dinilai, dan menuntut 4 dari 3 mustahil.
#: Jadi: wajib lulus trio struktural, lalu minimal ``min(4, jumlah_yang_dinilai)``
#: kriteria lulus. Artinya begitu riwayat akumulasi/volume/shakeout tersedia,
#: syaratnya otomatis naik menjadi "struktural + minimal satu bukti".
ELIGIBLE_MIN_PASSED = 4
ELIGIBLE_STRUCTURAL = ("liq_mc", "float_spread", "authority")  # wajib lulus; authority tidak masuk skor

CRITERIA_KEYS = (
    ("liq_mc", "liq/MC"),
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

    ``(akar(m) - 1) x (liq / MC)`` — turunan dari ``P/P0 = (1 + X/Q0)^2`` pada
    AMM constant-product. Diverifikasi pada COCKROACH: ``(akar(8,67)-1) x
    12,95% = 25,2%`` dan ``$58.778 / $233.451 = 25,2%``.
    """
    m = _num(mult)
    lm = _num(liq_mc)
    if m is None or lm is None or m <= 0 or lm <= 0:
        return None
    return (math.sqrt(m) - 1.0) * lm


def leverage_ratio(mult, liq_mc):
    """Paper market cap yang diciptakan per $1 net masuk.

    ``(akar(m) + 1) / (liq / MC)`` — COCKROACH: ``3,944 / 0,1295 = 30,5x``,
    cocok dengan aktual ``$1.790.194 / $58.778 = 30,5x``.
    """
    m = _num(mult)
    lm = _num(liq_mc)
    if m is None or lm is None or m <= 0 or lm <= 0:
        return None
    return (math.sqrt(m) + 1.0) / lm


def cost_usd(mult, liq_usd):
    """Nominal USD yang dibutuhkan untuk naik ``mult`` kali.

    ``(akar(m) - 1) x liq_usd``. Sama dengan ``cost_frac x MC`` karena
    ``liq/MC = liq_usd / MC``; dihitung langsung dari likuiditas agar tidak
    ada pembulatan ganda.
    """
    m = _num(mult)
    lu = _num(liq_usd)
    if m is None or lu is None or m <= 0 or lu <= 0:
        return None
    return (math.sqrt(m) - 1.0) * lu


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


def cost_gate(cost_frac) -> dict:
    """Gate biaya 10x: biaya ≤ 75% MC lolos; > 75% atau tanpa data = TUNGGU."""
    value = _num(cost_frac)
    label = f"biaya {COST_GATE_MULT:.0f}x"
    if value is None:
        return {"passed": False,
                "status": f"TUNGGU — {label} belum ada data",
                "detail": f"{label} belum bisa dihitung (liq/MC atau MC kosong); "
                          "gate belum lolos"}
    limit_pct = COST_GATE_MAX_FRAC * 100
    if value > COST_GATE_MAX_FRAC:
        return {"passed": False,
                "status": f"TUNGGU — {label} {value * 100:.1f}% MC (batas {limit_pct:.0f}%)",
                "detail": f"{label} {value * 100:.1f}% MC melebihi batas {limit_pct:.0f}%"}
    return {"passed": True,
            "status": "LOLOS",
            "detail": f"{label} {value * 100:.1f}% MC (batas {limit_pct:.0f}%)"}


def reference_fund_multiple(liq_mc):
    """Biaya 3x sebagai kelipatan dana acuan COCK pra-pump.

    COCK's measured reference ($11,066 = 4.74% MC) uses cash-side reserves
    ($15,116), so this comparison uses half of the two-sided liq/MC. Existing
    ``est_cost_usd`` and ``leverage`` deliberately continue to use full, two-
    sided ``liq_usd``. At COCK's liq/MC 12.95%, this returns about 1.0x.
    """
    ratio = _num(liq_mc)
    if ratio is None or ratio <= 0:
        return None
    cost_frac = leverage_cost(3.0, ratio / 2.0)
    if cost_frac is None or COCK_REFERENCE_COST_3X_MC_FRAC <= 0:
        return None
    return cost_frac / COCK_REFERENCE_COST_3X_MC_FRAC


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


def cohort_gate(profile) -> dict:
    """Gate pra-penilaian: PLUS skip, tunggu sampai minus 50%, no-data tunggu."""
    status = _num((profile or {}).get("status_avg_cost"))
    if status is None:
        return {"passed": False, "status": "TANPA DATA — kohort",
                "detail": "VWAP/jendela kelahiran tidak tersedia; gate belum lolos"}
    if status >= 0:
        return {"passed": False, "status": "SKIP — kohort plus",
                "detail": f"kohort PLUS {status*100:.1f}% terhadap VWAP kelahiran"}
    threshold_pct = abs(COHORT_MINUS_THRESHOLD) * 100
    if status <= COHORT_MINUS_THRESHOLD:
        return {"passed": True, "status": "LOLOS",
                "detail": f"kohort MINUS {abs(status)*100:.1f}% (ambang minus {threshold_pct:.0f}%)"}
    return {"passed": False,
            "status": f"TUNGGU — kohort belum minus {threshold_pct:.0f}%",
            "detail": f"kohort MINUS {abs(status)*100:.1f}% (butuh {threshold_pct:.0f}%)"}


#: Urutan tampilan tabel: yang paling dekat ke kelayakan di atas.
#: 0 LAYAK · 1 KANDIDAT · 2 gate lolos tapi kriteria kurang · 3 TUNGGU kohort
#: · 4 TANPA DATA kohort · 9 SKIP kohort PLUS (selalu paling bawah).
_DISPLAY_GROUP_SKIP = 9


def display_sort_key(result) -> tuple:
    """Kunci urut tabel Sweep (kecil = lebih atas).

    Urutan (berdasarkan skor, sesuai permintaan user 2026-10-13):
    1. kohort PLUS (SKIP) selalu paling bawah;
    2. baris tanpa skor (belum ada data / belum ada snapshot) sebelum PLUS;
    3. skor kriteria tertinggi (``passed/scored``) di atas;
    4. jika skor sama: jumlah kriteria lolos lebih banyak di atas;
    5. jika masih sama: kelompok vonis (LAYAK > KANDIDAT > gate lolos > TUNGGU
       > TANPA DATA), lalu untuk TUNGGU: status kohort makin dekat −50% di atas.
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
    elif result.get("cohort_gate_passed"):
        # Termasuk TUNGGU gate biaya 10x: kohort sudah lolos, tapi biaya belum.
        group = {VERDICT_LAYAK[0]: 0, VERDICT_KANDIDAT[0]: 1}.get(verdict, 2)
    else:
        group = 4
    return (group == _DISPLAY_GROUP_SKIP, score is None,
            -(score or 0.0), -passed, group, distance)


# ---------------------------------------------------------------------------
# Kriteria
# ---------------------------------------------------------------------------

def _check(key, label, passed, detail, *, scored=True):
    return {"key": key, "label": label, "passed": passed, "detail": detail,
            "has_data": passed is not None, "scored": scored}


def criterion_liq_mc(liq_usd, fdv_usd):
    """Kriteria 1 — liq/MC maksimum tetap 35% (murah di-sweep)."""
    liq, fdv = _num(liq_usd), _num(fdv_usd)
    if not liq or not fdv or fdv <= 0:
        return _check("liq_mc", "liq/MC", None, "liq/FDV tidak tersedia")
    ratio = liq / fdv
    cost3 = leverage_cost(3.0, ratio)
    tail = (f" — naik 3x perlu {cost3*100:.1f}% MC" if cost3 is not None else "")
    if ratio <= LIQ_MC_MAX:
        detail = (f"liq/MC {ratio*100:.1f}% <= {LIQ_MC_MAX*100:.0f}%{tail}")
    else:
        detail = (f"liq/MC {ratio*100:.1f}% > {LIQ_MC_MAX*100:.0f}% — sweep mahal"
                  f"{tail}")
    return _check("liq_mc", "liq/MC", ratio <= LIQ_MC_MAX, detail)


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


def _latched_shakeout_check(check, latched_at):
    """A stored timestamp makes shakeout permanently passed for that mint."""
    if latched_at is None:
        return check
    latched_ts = _timestamp_seconds(latched_at)
    timestamp = int(latched_ts) if latched_ts is not None else str(latched_at)
    result = _check("shakeout", "Shakeout + higher low", True,
                    f"latch permanen sejak {timestamp}")
    result["latched_at"] = latched_at
    return result


def evaluate(metrics, *, snapshots=None, candles=None, cohort_candles=None,
             state=None, mint=None, now=None, cohort_error=None):
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
    shakeout = _latched_shakeout_check(shakeout, latched_at)

    checks = [
        criterion_liq_mc(metrics.get("liq_usd"), metrics.get("fdv_usd")),
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
    gate = cohort_gate(cohort)
    # Gate biaya 10x diuji setelah gate kohort; keduanya harus lolos sebelum
    # skor menentukan LAYAK/KANDIDAT.
    cost_10x_mc_frac = leverage_cost(COST_GATE_MULT, liq_mc)
    cost_gate_result = cost_gate(cost_10x_mc_frac)
    score_ok = (score is not None and len(passed) >= required and structural_ok)
    eligible = bool(gate["passed"] and cost_gate_result["passed"] and score_ok)
    if not gate["passed"]:
        verdict, color = gate["status"], (
            "#64748b" if gate["status"].startswith("TANPA DATA") else "#b45309")
    elif not cost_gate_result["passed"]:
        verdict, color = cost_gate_result["status"], "#b45309"
    elif score is None:
        verdict, color = VERDICT_DATA
    elif score_ok:
        verdict, color = VERDICT_LAYAK
    elif len(passed) >= 2:
        verdict, color = VERDICT_KANDIDAT
    else:
        verdict, color = VERDICT_TIDAK

    vol24 = _num(metrics.get("vol24_usd"))
    if vol24 is None:
        vol24 = _num(metrics.get("vol_24h"))
    turnover_x = (vol24 / liq if vol24 is not None and liq is not None and liq > 0
                  else None)
    cost_3x_mc_frac = leverage_cost(3.0, liq_mc)
    # UI column "× dana acuan" = ((√3−1)×(liq/MC÷2)) ÷ 4.74%, where
    # 4.74% = COCK's $11,066 / $233,451; its one-sided cash basis makes COCK 1.0×.
    reference_fund_x = reference_fund_multiple(liq_mc)
    # Nominal $ untuk "× dana acuan": (√3−1) x (liq/2), sama dengan
    # reference_fund_x x 4,74% MC (basis kas satu sisi seperti di atas).
    reference_fund_usd = cost_usd(3.0, liq / 2.0) if liq is not None else None
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
        "cost_gate_status": cost_gate_result["status"],
        "cost_gate_passed": cost_gate_result["passed"],
        "cost_gate_detail": cost_gate_result["detail"],
        "reference_fund_x": reference_fund_x,
        "reference_fund_usd": reference_fund_usd,
        "turnover_x": turnover_x,
        "cohort": cohort,
        "cohort_gate_status": gate["status"],
        "cohort_gate_passed": gate["passed"],
        "cohort_gate_detail": gate["detail"],
        "missing": [c["key"] for c in checks if not c["has_data"]],
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
        dasar 0,00023768. Inflow $58.778 ≈ biaya dorong ke puncak
        ``(akar(8,669) - 1) × $30.232 = $58.774``.
    ``close`` (harga penutupan candle)
        Close COCKROACH = 0,00076674 → hanya 3,226× dari dasar. Biaya dorong
        ke close = ``(akar(3,226) - 1) × $30.232 = $24.067`` — angka lama yang
        sebelah karena penggunaan close sebagai referensi berlebih 2,44×.
    ``base_price`` (harga sebelum candle sweep)
        Harga tenang 22:41 WIB = 0,00023768.

    Enam angka yang harus dibedakan (dua besaran "paper" pun berbeda):

    ``est_cost_usd``
        **Biaya dorong ke PUNCAK**: ``(akar(peak_mult) - 1) × liq``. Jumlah
        quote yang harus disedot AMM supaya harga sampai ke puncak candle,
        kalau tidak ada pembeli lain. COCKROACH 1 Okt = $58.778 (= 25,2% MC).
    ``est_cost_close_usd``
        **Biaya dorong ke CLOSE**: ``(akar(price_mult) - 1) × liq``. Angka
        yang salah dipakai sebelumnya karena menggunakan close sebagai referensi.
        COCKROACH 1 Okt = $24.067 (bedanya > 2× dari biaya ke puncak).
    ``paper_gain_usd``
        **Kenaikan MC kertas sampai puncak**: ``supply × (peak - base_price)``.
        Nilai riil COCKROACH 1 Okt = $1.790.194 (dari supply ≈ 982jt × (0,00206033
        - 0,00023768)).
    ``paper_mcap_usd``
        **MC kertas di CLOSE**: ``supply × close``. Besaran **berbeda** dari
        paper_gain — COCKROACH = $752.939. Jangan dipakai sebagai pembilang
        leverage (itu salah karena underestimate).
    ``net_inflow_usd``
        **Uang yang benar-benar tinggal di pool**: selisih likuiditas antar
        snapshot. COCKROACH 1 Okt = $58.778 — ≈ biaya dorong ke puncak ($58.774),
        artinya sweep itu tidak menarik pembeli luar (semua uang yang masuk
        dipakai ke puncak). Kalau tidak ada data snapshot, diisi ``None``
        (jangan menebak).
    ``churn_x`` / ``churn_net_x``
        volume candle sweep ÷ biaya ke puncak (**teoretis**) versus ÷ inflow
        nyata (**nyata**). COCKROACH: keduanya ≈ 21,1× karena inflow ≈ biaya
        ke puncak. Kalau ``churn_net_x < churn_x × 0,9`` → ada pembeli luar
        ikut masuk.

    ``leverage`` = ``paper_gain ÷ est_cost`` = ``(akar(peak_mult) + 1) / (liq/MC)``
        COCKROACH: ``(akar(8,669) + 1) / 12,95% = 3,944 / 0,1295 = 30,5×``,
        cocok dengan ``$1.790.194 / $58.778 = 30,5×``.

    페르세타:
    Semua angka "paper" (paper_gain, paper_mcap) adalah **teoretis** — nilai
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
    enriched["est_cost_usd"] = ((_sqrt(peak_mult) - 1.0) * liq
                                if (peak_mult and peak_mult > 0 and liq) else None)
    enriched["leverage"] = leverage_ratio(peak_mult, liq_mc)
    enriched["base_mcap_usd"] = base_mcap
    enriched["paper_mcap_usd"] = paper_mcap

    # --- Biaya dorong ke CLOSE (untuk perbandingan, bukan penggunaan utama) ---
    if price_mult and price_mult > 0 and liq:
        enriched["est_cost_close_usd"] = (_sqrt(price_mult) - 1.0) * liq
    else:
        enriched["est_cost_close_usd"] = None

    # --- Kenaikan MC kertas sampai puncak (bukan MC di close) ---
    if supply is not None and peak and base_price:
        enriched["paper_gain_usd"] = supply * (peak - base_price)
    else:
        enriched["paper_gain_usd"] = None

    # --- peak_mult untuk sinyal ---
    enriched["peak_mult"] = peak_mult

    # Inflow nyata hanya dari pengukuran (selisih liq snapshot) — bukan tebakan.
    inflow = _num(net_inflow_usd)
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
