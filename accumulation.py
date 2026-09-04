# -*- coding: utf-8 -*-
"""Delapan heuristik **deteksi akumulasi** untuk token watchlist.

Modul ini **murni kalkulasi**: tidak ada satu pun request jaringan di sini.
Semua bahan mentah (titik history holder, swap GMGN, metrik volatilitas,
candle) disuntikkan pemanggil — halaman ``pages/6_🔎_Deteksi_Akumulasi.py``
yang menariknya lewat fetcher yang sudah ada (``cvd.fetch_gmgn_swaps``,
``core.get_market``, ``core.get_hourly_candles``, ``holder_history``), jadi
tidak ada jalur API baru dan **kuota Helius tidak tersentuh sama sekali**.

Setiap metrik mengembalikan struktur yang sama supaya gampang dirender dan
gampang dites::

    {"key", "nama", "nilai", "nilai_text", "status", "status_label",
     "penjelasan", "cukup_data", "bobot", "detail", "sumber"}

``status`` ∈ ``positif`` / ``netral`` / ``negatif`` / ``tidak_cukup_data``.
Bila ``cukup_data`` False, metrik **tidak** ikut skor gabungan — "tidak tahu"
tidak pernah dihitung sebagai "netral" (pola yang sama dipakai
``holder_history.calculate_volatility_metrics`` lewat ``available``).

⚠️ Semua metrik di sini **heuristik**, bukan bukti dan **bukan** prediksi arah
harga (disclaimer yang sama dipakai README/AGENTS untuk rule dust & cluster).

Catatan sumber data (penting, hasil penelusuran repo):

* Metrik 4 (Smart Money / PnL) **hanya** memakai GMGN — field per-wallet
  ``realized_profit`` / ``maker_tags`` yang sudah diparsing
  ``cvd._extract_gmgn_trade_meta``. Riwayat PnL lintas token lewat Helius
  Enhanced API **sengaja tidak diimplementasikan**: boros kuota Helius
  (keputusan user 2026-09-04).
* Metrik 6 (Spring/Test) memakai level support D1 yang diturunkan dari candle
  harian ``core.get_daily_candles`` karena repo ini tidak punya
  ``levels.json``/``breakout_guard.py``.
* Metrik 7 (Funder chain) memakai tag ``fresh_wallet`` GMGN + pola waktu buy.
  **Identitas funder tidak tersedia** tanpa scan Helius, jadi metrik ini
  menandai pola "wallet baru beli pelan-pelan tanpa jual", bukan "satu funder
  yang sama" — dan itu ditulis eksplisit di penjelasannya.
"""
from __future__ import annotations

import json
import os
import time

from cvd_daily import FRESH_WALLET_TAG, SMART_MONEY_TAGS, normalize_tag

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCUMULATION_HISTORY_PATH = os.path.join(BASE_DIR, "accumulation_history.json")

# --- label status -------------------------------------------------------------
POSITIF = "positif"
NETRAL = "netral"
NEGATIF = "negatif"
NO_DATA = "tidak_cukup_data"

STATUS_LABEL = {
    POSITIF: "Terpenuhi",
    NETRAL: "Netral",
    NEGATIF: "Tidak terpenuhi",
    NO_DATA: "Data kurang",
}

# Status ringkas per token (dipakai header card).
TOKEN_AKUMULASI = "Terindikasi Akumulasi"
TOKEN_NETRAL = "Netral"
TOKEN_NO_DATA = "Tidak Cukup Data"

# Ambang skor gabungan (0-100).
SCORE_AKUMULASI = 60.0

# Bobot per metrik untuk skor gabungan (jumlah = 8; boleh dinormalisasi).
METRIC_WEIGHTS = {
    "tier_migration": 1.0,
    "diamond_hands": 1.0,
    "dca_pattern": 1.0,
    "smart_money_pnl": 1.0,
    "silent_range": 1.0,
    "spring_test": 1.0,
    "funder_prep": 1.0,
    "sell_side_thinning": 1.0,
}

METRIC_NAMES = {
    "tier_migration": "1. Tier Migration Velocity",
    "diamond_hands": "2. Diamond Hands Ratio",
    "dca_pattern": "3. Pola DCA vs One-off Buy",
    "smart_money_pnl": "4. Smart Money / PnL Wallet (GMGN)",
    "silent_range": "5. Silent Range Accumulation",
    "spring_test": "6. Spring / Test Pattern",
    "funder_prep": "7. Fresh Wallet Prep (funder chain)",
    "sell_side_thinning": "8. Sell-Side Liquidity Thinning",
}

# Label bucket wallet depth (``solscan_holders.DEPTH_BUCKETS``) yang dipakai
# metrik 1. Repo ini tidak punya boundary $1M — bucket tertinggi ``>$500k``.
DUST_BUCKET = ">$0-$10"
MID_TIER_BUCKETS = ("$100-$1k", "$1k-$10k")
UPPER_TIER_BUCKETS = ("$10k-$100k", "$100k-$500k", ">$500k")

# --- ambang metrik ------------------------------------------------------------
DUST_STABLE_PCT = 10.0          # metrik 1: perubahan relatif bucket dust
DIAMOND_POSITIF_PCT = 60.0      # metrik 2
DIAMOND_NEGATIF_PCT = 35.0
DCA_MIN_BUYS = 3                # metrik 3
DCA_MAX_SINGLE_SHARE = 0.60     # satu buy tidak boleh mendominasi
ONEOFF_SINGLE_SHARE = 0.80
SMART_MIN_WALLETS = 1           # metrik 4
SILENT_MIN_VOLUME_USD = 10_000.0   # metrik 5: lantai — di bawah ini token mati
SILENT_MAX_VOLUME_USD = 250_000.0  # metrik 5: plafon — di atas ini bukan "silent"
SILENT_RANGE_SHRINK = 0.80      # stddev window <= 0,8x stddev konteks = menyempit
SILENT_MAX_NET_PCT = 15.0       # CVD net positif tipis (bukan pump)
SPRING_VOLUME_RATIO = 1.0       # metrik 6: volume spring < rata-rata sekitarnya
SPRING_LOOKBACK = 12            # jumlah candle 4 jam yang diperiksa
FRESH_MIN_WALLETS = 3           # metrik 7
FRESH_MIN_BUYS = 2
FRESH_MIN_SPAN_MIN = 30         # "pelan-pelan", bukan sniper instan
FRESH_MAX_SINGLE_SHARE = 0.75
THINNING_DAYS = 14              # metrik 8
THINNING_POSITIF_PCT = 70.0
MIN_WALLETS_FOR_FLOW = 5        # floor umum: < 5 wallet = sampel terlalu kecil

INTERVAL_4H = 4 * 3600
SECONDS_PER_DAY = 86_400


# ---------------------------------------------------------------------------
# Helper numerik
# ---------------------------------------------------------------------------
def _float(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return num if num == num else default  # tolak NaN


def _int(value, default=0):
    num = _float(value, None)
    return default if num is None else int(num)


def _pct(numerator, denominator) -> float | None:
    """Persentase aman; ``None`` bila penyebut nol/tidak ada."""
    top = _float(numerator, None)
    bottom = _float(denominator, None)
    if top is None or bottom is None or bottom == 0:
        return None
    return round(top / bottom * 100.0, 2)


def _fmt_pct(value, digits: int = 2) -> str:
    """Format persentase untuk penjelasan; ``—`` bila tidak ada angka."""
    num = _float(value, None)
    return "—" if num is None else f"{num:.{digits}f}%"


def _median(values) -> float | None:
    rows = sorted(v for v in (_float(x, None) for x in values or [])
                  if v is not None)
    if not rows:
        return None
    middle = len(rows) // 2
    if len(rows) % 2:
        return round(rows[middle], 4)
    return round((rows[middle - 1] + rows[middle]) / 2.0, 4)


def mask_address(address) -> str:
    """Potong address jadi ``Abcd…wxyz`` (jangan tampilkan penuh di UI)."""
    text = str(address or "")
    if len(text) <= 10:
        return text or "—"
    return f"{text[:4]}…{text[-4:]}"


def metric_result(key: str, *, nilai=None, nilai_text="", status=NO_DATA,
                  penjelasan="", cukup_data=False, detail=None, bobot=None,
                  sumber="") -> dict:
    """Struktur baku satu metrik (dipakai semua fungsi di bawah)."""
    key = str(key or "")
    status = status if status in STATUS_LABEL else NO_DATA
    if not cukup_data and status != NO_DATA:
        # "cukup_data=False" selalu berarti tidak tahu, apa pun statusnya.
        status = NO_DATA
    return {
        "key": key,
        "nama": METRIC_NAMES.get(key, key),
        "nilai": nilai,
        "nilai_text": str(nilai_text or ""),
        "status": status,
        "status_label": STATUS_LABEL[status],
        "penjelasan": str(penjelasan or ""),
        "cukup_data": bool(cukup_data),
        "bobot": float(METRIC_WEIGHTS.get(key, 1.0) if bobot is None
                       else bobot),
        "detail": dict(detail or {}),
        "sumber": str(sumber or ""),
    }


# ---------------------------------------------------------------------------
# Normalisasi swap GMGN (tuple 3..7 elemen — kontrak ``cvd.fetch_gmgn_swaps``)
# ---------------------------------------------------------------------------
def normalize_swaps(swaps) -> list[dict]:
    """Ubah swap tuple jadi dict urut waktu naik.

    Bentuk tuple ``cvd``: ``(side, sol_eq, ts, wallet, price_usd, amount_usd,
    tags)`` — hanya 3 elemen pertama yang wajib, sisanya ditoleransi supaya
    tuple legacy tetap bisa dipakai.
    """
    rows = []
    for swap in swaps or []:
        if isinstance(swap, dict):
            side = str(swap.get("side") or "").lower()
            sol_eq = _float(swap.get("sol") or swap.get("amount_sol"), 0.0)
            ts = _int(swap.get("ts") or swap.get("timestamp"))
            wallet = str(swap.get("wallet") or "")
            usd = _float(swap.get("amount_usd"), 0.0)
            tags = swap.get("tags") or []
        elif isinstance(swap, (list, tuple)) and len(swap) >= 3:
            side = str(swap[0] or "").lower()
            sol_eq = _float(swap[1], 0.0)
            ts = _int(swap[2])
            wallet = str(swap[3]) if len(swap) > 3 and swap[3] else ""
            usd = _float(swap[5], 0.0) if len(swap) > 5 else 0.0
            tags = swap[6] if len(swap) > 6 else []
        else:
            continue
        if side not in ("buy", "sell") or sol_eq <= 0 or ts <= 0:
            continue
        if isinstance(tags, str):
            tags = [tags]
        rows.append({
            "side": side,
            "sol": sol_eq,
            "ts": ts,
            "wallet": wallet,
            "usd": usd or 0.0,
            "tags": {normalize_tag(tag) for tag in (tags or [])
                     if normalize_tag(tag)},
        })
    rows.sort(key=lambda row: row["ts"])
    return rows


def wallet_profiles(swaps) -> dict:
    """Rekap per wallet dari swap ternormalisasi (dipakai metrik 2/3/7/8)."""
    rows = normalize_swaps(swaps)
    profiles: dict[str, dict] = {}
    for row in rows:
        wallet = row["wallet"]
        if not wallet:
            continue
        item = profiles.setdefault(wallet, {
            "wallet": wallet, "buy_tx": 0, "sell_tx": 0, "buy_sol": 0.0,
            "sell_sol": 0.0, "buy_usd": 0.0, "sell_usd": 0.0,
            "buys": [], "first_buy_ts": None, "last_buy_ts": None,
            "first_ts": row["ts"], "last_ts": row["ts"],
            "last_sell_ts": None, "net_sol": 0.0, "never_decreased": True,
            "tags": set(),
        })
        item["tags"] |= row["tags"]
        item["last_ts"] = row["ts"]
        item["first_ts"] = min(item["first_ts"], row["ts"])
        if row["side"] == "buy":
            item["buy_tx"] += 1
            item["buy_sol"] += row["sol"]
            item["buy_usd"] += row["usd"]
            item["buys"].append(row["sol"])
            item["first_buy_ts"] = (row["ts"] if item["first_buy_ts"] is None
                                    else min(item["first_buy_ts"], row["ts"]))
            item["last_buy_ts"] = (row["ts"] if item["last_buy_ts"] is None
                                   else max(item["last_buy_ts"], row["ts"]))
            item["net_sol"] += row["sol"]
        else:
            item["sell_tx"] += 1
            item["sell_sol"] += row["sol"]
            item["sell_usd"] += row["usd"]
            item["last_sell_ts"] = (row["ts"] if item["last_sell_ts"] is None
                                    else max(item["last_sell_ts"], row["ts"]))
            item["net_sol"] -= row["sol"]
            # Posisi net turun di titik mana pun = pernah net-sell.
            item["never_decreased"] = False
    return profiles


def cvd_net_pct(swaps) -> float | None:
    """CVD net dalam % total volume USD: (buy − sell) / (buy + sell) × 100.

    ``None`` bila tidak ada volume USD sama sekali (bukan 0% — 0% berarti
    benar-benar seimbang).
    """
    rows = normalize_swaps(swaps)
    buy = sum(row["usd"] for row in rows if row["side"] == "buy")
    sell = sum(row["usd"] for row in rows if row["side"] == "sell")
    total = buy + sell
    if total <= 0:
        return None
    return round((buy - sell) / total * 100.0, 2)


def select_pair_address(market) -> str:
    """Pool address pertama dari payload ``core.get_market`` ('' bila kosong).

    DexScreener bisa mengembalikan token tanpa pair (token mati / API gagal),
    jadi indeks ``[0]`` langsung akan melempar ``IndexError`` — halaman
    Deteksi Akumulasi harus tetap jalan dan menandai metriknya kurang data.
    """
    pairs = (market or {}).get("pair_addresses") if isinstance(market, dict) \
        else None
    for pair in pairs or []:
        if pair:
            return str(pair)
    return ""


def window_swaps(swaps, *, since_ts=None, until_ts=None) -> list:
    """Saring swap ke window waktu (dipakai halaman untuk membatasi kuota)."""
    rows = normalize_swaps(swaps)
    low = _int(since_ts, 0)
    high = _int(until_ts, 0)
    out = []
    for row in rows:
        if low and row["ts"] < low:
            continue
        if high and row["ts"] > high:
            continue
        out.append((row["side"], row["sol"], row["ts"], row["wallet"], None,
                    row["usd"], sorted(row["tags"])))
    return out


# ---------------------------------------------------------------------------
# Metrik 1 — Tier Migration Velocity
# ---------------------------------------------------------------------------
def tier_migration_velocity(points, *, dust_stable_pct: float = DUST_STABLE_PCT,
                            min_points: int = 2) -> dict:
    """Perpindahan jumlah wallet antar tier antara dua snapshot terakhir.

    ``points`` = titik ``holder_history`` (field ``buckets`` = label → jumlah
    wallet, hasil ``holder_history.bucket_counts``). Sinyal positif: tier
    ``$100-$1k`` dan ``$1k-$10k`` naik sementara bucket dust relatif stabil
    (bukan lonjakan spam wallet).
    """
    usable = [row for row in (points or [])
              if isinstance(row, dict) and isinstance(row.get("buckets"), dict)
              and row.get("buckets")]
    key = "tier_migration"
    if len(usable) < max(2, int(min_points)):
        return metric_result(
            key, nilai_text="—",
            penjelasan=("Butuh minimal 2 snapshot holder dengan data wallet "
                        "depth (bucket). Snapshot tersimpan: "
                        f"{len(usable)}."),
            detail={"snapshots": len(usable)}, sumber="holder_history.json")

    latest, previous = usable[-1], usable[-2]
    labels = sorted(set(latest["buckets"]) | set(previous["buckets"]))
    deltas = {}
    for label in labels:
        before = _int(previous["buckets"].get(label))
        after = _int(latest["buckets"].get(label))
        deltas[label] = after - before

    dust_before = _int(previous["buckets"].get(DUST_BUCKET))
    dust_change = _pct(deltas.get(DUST_BUCKET, 0), dust_before or None)
    mid = {label: deltas.get(label, 0) for label in MID_TIER_BUCKETS
           if label in deltas}
    upper = {label: deltas.get(label, 0) for label in UPPER_TIER_BUCKETS
             if label in deltas}
    mid_up = [label for label, delta in mid.items() if delta > 0]
    mid_down = [label for label, delta in mid.items() if delta < 0]
    upper_up = [label for label, delta in upper.items() if delta > 0]
    dust_stable = (dust_change is None
                   or abs(dust_change) <= float(dust_stable_pct))

    cukup = bool(mid)
    if not cukup:
        status = NO_DATA
        alasan = ("Snapshot tidak memuat bucket tier menengah "
                  "($100-$1k / $1k-$10k), jadi migrasi tier tidak bisa "
                  "diukur.")
    elif mid_up and not mid_down and dust_stable:
        status = POSITIF
        alasan = (f"Tier menengah naik ({', '.join(mid_up)}) sementara dust "
                  f"relatif stabil ({_fmt_pct(dust_change)}).")
    elif mid_down:
        status = NEGATIF
        alasan = (f"Tier menengah menyusut ({', '.join(mid_down)}) — holder "
                  "menengah keluar/menipis, bukan pola akumulasi.")
    elif not dust_stable:
        status = NEGATIF
        alasan = (f"Dust melonjak {_fmt_pct(dust_change)} (ambang stabil "
                  f"±{float(dust_stable_pct):g}%) — tambahan wallet lebih "
                  "mirip spam/distribusi daripada migrasi ke tier atas.")
    else:
        status = NETRAL
        alasan = ("Jumlah wallet per tier praktis tidak berubah; belum ada "
                  "migrasi yang terlihat.")
    if upper_up and status == POSITIF:
        alasan += f" Tier atas ikut naik ({', '.join(upper_up)})."

    return metric_result(
        key,
        nilai={"deltas": deltas, "mid_up": len(mid_up),
               "mid_down": len(mid_down), "dust_change_pct": dust_change},
        nilai_text=(f"mid {sum(mid.values()):+d} wallet · dust "
                    f"{_fmt_pct(dust_change)}"),
        status=status, cukup_data=cukup, penjelasan=alasan,
        detail={"deltas": deltas, "dust_before": dust_before,
                "dust_change_pct": dust_change, "mid_up": mid_up,
                "mid_down": mid_down, "upper_up": upper_up,
                "from_ts": _int(previous.get("ts")),
                "to_ts": _int(latest.get("ts")),
                "ambang_stabil_pct": float(dust_stable_pct)},
        sumber="holder_history.json (wallet depth per bucket)")


# ---------------------------------------------------------------------------
# Metrik 2 — Diamond Hands Ratio
# ---------------------------------------------------------------------------
def diamond_hands_ratio(swaps, *, min_wallets: int = MIN_WALLETS_FOR_FLOW,
                        positif_pct: float = DIAMOND_POSITIF_PCT,
                        negatif_pct: float = DIAMOND_NEGATIF_PCT) -> dict:
    """% wallet yang posisi net-nya **tidak pernah turun** sejak muncul.

    Posisi net dihitung dari swap (buy menambah, sell mengurangi) dalam
    SOL-equivalent — GMGN tidak mengirim jumlah token di payload trade, jadi
    SOL-equivalent dipakai sebagai proxy posisi. Wallet yang pernah net-sell
    satu kali pun tidak dihitung diamond hands.
    """
    key = "diamond_hands"
    profiles = wallet_profiles(swaps)
    total = len(profiles)
    if total < max(1, int(min_wallets)):
        return metric_result(
            key, nilai_text="—",
            penjelasan=(f"Hanya {total} wallet teramati di window swap; "
                        f"butuh minimal {int(min_wallets)} wallet supaya "
                        "rasio tidak ditentukan satu-dua wallet."),
            detail={"wallets": total}, sumber="GMGN token trades")

    diamonds = [item for item in profiles.values() if item["never_decreased"]]
    ratio = _pct(len(diamonds), total)
    if ratio is None:
        ratio = 0.0
    if ratio >= float(positif_pct):
        status = POSITIF
        alasan = (f"{ratio:.1f}% wallet ({len(diamonds)}/{total}) tidak pernah "
                  f"net-sell (ambang {float(positif_pct):g}%).")
    elif ratio >= float(negatif_pct):
        status = NETRAL
        alasan = (f"{ratio:.1f}% wallet ({len(diamonds)}/{total}) tidak pernah "
                  f"net-sell — campuran holder diam dan trader aktif.")
    else:
        status = NEGATIF
        alasan = (f"Hanya {ratio:.1f}% wallet ({len(diamonds)}/{total}) yang "
                  f"tidak pernah net-sell (di bawah {float(negatif_pct):g}%) — "
                  "mayoritas sudah pernah mengurangi posisi.")

    return metric_result(
        key, nilai=ratio, nilai_text=f"{ratio:.1f}% diamond hands",
        status=status, cukup_data=True, penjelasan=alasan,
        detail={"wallets": total, "diamond_wallets": len(diamonds),
                "ambang_positif_pct": float(positif_pct),
                "ambang_negatif_pct": float(negatif_pct),
                "contoh_wallet": [mask_address(item["wallet"])
                                  for item in diamonds[:5]]},
        sumber="GMGN token trades (net position per wallet)")


# ---------------------------------------------------------------------------
# Metrik 3 — Pola DCA vs One-off Buy
# ---------------------------------------------------------------------------
def dca_vs_oneoff(swaps, *, min_buys: int = DCA_MIN_BUYS,
                  max_single_share: float = DCA_MAX_SINGLE_SHARE,
                  oneoff_share: float = ONEOFF_SINGLE_SHARE,
                  min_wallets: int = MIN_WALLETS_FOR_FLOW) -> dict:
    """Bedakan buyer berulang kecil (DCA) dari satu buy besar lalu diam.

    DCA = ≥ ``min_buys`` transaksi buy **dan** tidak ada satu buy yang
    mendominasi (share ≤ ``max_single_share``). One-off = buy ≤ 2 kali atau
    satu buy ≥ ``oneoff_share`` dari total buy wallet itu.
    """
    key = "dca_pattern"
    profiles = wallet_profiles(swaps)
    buyers = [item for item in profiles.values() if item["buy_tx"] > 0]
    if len(buyers) < max(1, int(min_wallets)):
        return metric_result(
            key, nilai_text="—",
            penjelasan=(f"Hanya {len(buyers)} wallet buyer teramati; butuh "
                        f"minimal {int(min_wallets)} untuk memisahkan pola "
                        "DCA dari one-off."),
            detail={"buyers": len(buyers)}, sumber="GMGN token trades")

    dca, oneoff, mixed = [], [], []
    for item in buyers:
        total_buy = item["buy_sol"] or 0.0
        largest = max(item["buys"]) if item["buys"] else 0.0
        share = (largest / total_buy) if total_buy > 0 else 1.0
        if item["buy_tx"] >= int(min_buys) and share <= float(max_single_share):
            dca.append((item, share))
        elif item["buy_tx"] <= 2 or share >= float(oneoff_share):
            oneoff.append((item, share))
        else:
            mixed.append((item, share))

    dca_pct = _pct(len(dca), len(buyers)) or 0.0
    oneoff_pct = _pct(len(oneoff), len(buyers)) or 0.0
    avg_buys = round(sum(item["buy_tx"] for item in buyers) / len(buyers), 2)
    if dca_pct >= 40.0 and len(dca) >= 3:
        status = POSITIF
        alasan = (f"{dca_pct:.1f}% buyer ({len(dca)}/{len(buyers)}) beli "
                  f"berulang kecil (DCA), rata-rata {avg_buys:g} buy per "
                  "wallet — pola masuk bertahap.")
    elif oneoff_pct >= 60.0:
        status = NEGATIF
        alasan = (f"{oneoff_pct:.1f}% buyer ({len(oneoff)}/{len(buyers)}) "
                  "one-off (satu buy besar lalu diam) — khas entry spekulatif/"
                  "sniper, bukan akumulasi bertahap.")
    else:
        status = NETRAL
        alasan = (f"Campuran: {len(dca)} DCA, {len(oneoff)} one-off, "
                  f"{len(mixed)} di antaranya; belum condong ke salah satu "
                  "pola.")

    return metric_result(
        key, nilai={"dca": len(dca), "oneoff": len(oneoff),
                    "mixed": len(mixed), "dca_pct": dca_pct,
                    "oneoff_pct": oneoff_pct, "avg_buy_tx": avg_buys},
        nilai_text=(f"{dca_pct:.0f}% DCA · {oneoff_pct:.0f}% one-off "
                    f"(avg {avg_buys:g} buy)"),
        status=status, cukup_data=True, penjelasan=alasan,
        detail={"buyers": len(buyers), "dca_wallets": len(dca),
                "oneoff_wallets": len(oneoff), "mixed_wallets": len(mixed),
                "min_buys": int(min_buys),
                "max_single_share": float(max_single_share),
                "contoh_dca": [mask_address(item["wallet"])
                               for item, _share in dca[:5]]},
        sumber="GMGN token trades (jumlah buy unik per wallet)")


# ---------------------------------------------------------------------------
# Metrik 4 — Smart Money / PnL Wallet (GMGN saja)
# ---------------------------------------------------------------------------
def smart_money_pnl(swaps, wallet_meta=None, *,
                    min_wallets: int = SMART_MIN_WALLETS) -> dict:
    """Wallet bertag smart money (GMGN) yang mulai masuk + realized PnL-nya.

    **GMGN saja.** ``wallet_meta`` = ``cvd.get_gmgn_wallet_metadata()``
    (diparsing ``cvd._extract_gmgn_trade_meta``): ``maker_tags``,
    ``realized_profit``, ``unrealized_profit``, ``history_bought_amount``,
    ``history_sold_amount``. Riwayat PnL **lintas token** lewat Helius
    Enhanced API sengaja tidak dipakai (boros kuota Helius — keputusan user),
    jadi angka PnL di sini adalah realized profit wallet itu **pada token
    ini** menurut GMGN, bukan rekam jejak lintas token.
    """
    key = "smart_money_pnl"
    profiles = wallet_profiles(swaps)
    meta = wallet_meta if isinstance(wallet_meta, dict) else {}
    if not meta:
        return metric_result(
            key, nilai_text="tidak ada metadata GMGN",
            penjelasan=("Metadata per-wallet GMGN kosong untuk window ini "
                        "(tag/profit tidak ikut terkirim), jadi smart money "
                        "tidak bisa dinilai. Riwayat PnL lintas token lewat "
                        "Helius Enhanced API sengaja tidak dipakai untuk "
                        "menghemat kuota Helius."),
            detail={"wallet_meta": 0, "wallets": len(profiles)},
            sumber="GMGN token trades (maker_tags + realized_profit)")
    if not profiles:
        return metric_result(
            key, nilai_text="—",
            penjelasan="Tidak ada wallet dengan address di window swap ini.",
            detail={"wallet_meta": len(meta), "wallets": 0},
            sumber="GMGN token trades (maker_tags + realized_profit)")

    smart = []
    for wallet, item in profiles.items():
        info = meta.get(wallet)
        if not isinstance(info, dict):
            continue
        tags = {normalize_tag(tag)
                for tag in (info.get("maker_tags") or [])} | item["tags"]
        if not (tags & SMART_MONEY_TAGS):
            continue
        smart.append({
            "wallet": wallet,
            "tags": sorted(tags & SMART_MONEY_TAGS),
            "net_sol": item["net_sol"],
            "buy_sol": item["buy_sol"],
            "sell_sol": item["sell_sol"],
            "realized_profit": _float(info.get("realized_profit"), 0.0) or 0.0,
            "unrealized_profit": _float(info.get("unrealized_profit"), 0.0) or 0.0,
        })

    if len(smart) < max(1, int(min_wallets)):
        return metric_result(
            key, nilai_text="0 wallet smart money",
            status=NETRAL, cukup_data=True,
            penjelasan=(f"{len(meta)} wallet punya metadata GMGN tetapi tidak "
                        "ada yang membawa tag smart money "
                        f"({', '.join(sorted(SMART_MONEY_TAGS))}) di window "
                        "ini — tidak ada jejak smart money masuk."),
            detail={"wallet_meta": len(meta), "smart_wallets": 0},
            sumber="GMGN token trades (maker_tags + realized_profit)")

    profitable = [row for row in smart if row["realized_profit"] > 0]
    net_buyers = [row for row in smart if row["net_sol"] > 0]
    profit_share = _pct(len(profitable), len(smart)) or 0.0
    median_profit = _median([row["realized_profit"] for row in smart]) or 0.0
    if net_buyers and profit_share >= 50.0:
        status = POSITIF
        alasan = (f"{len(net_buyers)}/{len(smart)} wallet smart money sedang "
                  f"membeli dan {profit_share:.0f}% punya realized profit "
                  f"positif (median ${median_profit:,.0f}) di token ini.")
    elif net_buyers:
        status = NETRAL
        alasan = (f"{len(net_buyers)}/{len(smart)} wallet smart money membeli, "
                  f"tetapi hanya {profit_share:.0f}% yang realized profitnya "
                  "positif — belum konsisten.")
    else:
        status = NEGATIF
        alasan = (f"{len(smart)} wallet smart money teramati tetapi semuanya "
                  "net-sell/keluar — kebalikan dari akumulasi.")

    return metric_result(
        key, nilai={"smart_wallets": len(smart),
                    "net_buyers": len(net_buyers),
                    "profit_share_pct": profit_share,
                    "median_realized_usd": median_profit},
        nilai_text=(f"{len(net_buyers)}/{len(smart)} smart money beli · "
                    f"median PnL ${median_profit:,.0f}"),
        status=status, cukup_data=True, penjelasan=alasan,
        detail={"wallet_meta": len(meta), "smart_wallets": len(smart),
                "net_buyers": len(net_buyers),
                "profitable": len(profitable),
                "median_realized_usd": median_profit,
                "catatan": ("PnL = realized profit GMGN pada token ini, bukan "
                            "lintas token (Helius Enhanced API tidak dipakai "
                            "untuk hemat kuota)."),
                "contoh_wallet": [f"{mask_address(row['wallet'])} "
                                  f"({', '.join(row['tags'])})"
                                  for row in smart[:5]]},
        sumber="GMGN token trades (maker_tags + realized_profit)")


# ---------------------------------------------------------------------------
# Metrik 5 — Silent Range Accumulation
# ---------------------------------------------------------------------------
def silent_range_accumulation(*, volume_usd=None, volatility=None,
                              cvd_net=None, swaps=None,
                              min_volume_usd: float = SILENT_MIN_VOLUME_USD,
                              max_volume_usd: float = SILENT_MAX_VOLUME_USD,
                              shrink_ratio: float = SILENT_RANGE_SHRINK,
                              max_net_pct: float = SILENT_MAX_NET_PCT) -> dict:
    """Volume tenang + range menyempit + CVD net positif tipis.

    ``volume_usd`` = volume 24 jam (DexScreener ``volume.h24``). Ada **lantai**
    volume (``min_volume_usd``): token yang benar-benar mati tidak boleh
    terbaca "terakumulasi". ``volatility`` = hasil
    ``holder_history.calculate_volatility_metrics`` (range menyempit bila
    ``price_stddev_4h`` ≤ ``shrink_ratio`` × ``history_stddev_pct``).
    ``cvd_net`` = CVD net % (bila ``None``, dihitung dari ``swaps``).
    """
    key = "silent_range"
    volume = _float(volume_usd, None)
    vol_metrics = volatility if isinstance(volatility, dict) else {}
    net = _float(cvd_net, None)
    if net is None and swaps:
        net = cvd_net_pct(swaps)

    if volume is None or not vol_metrics.get("available"):
        return metric_result(
            key, nilai_text="—",
            penjelasan=("Butuh volume 24 jam (DexScreener) dan metrik "
                        "volatilitas 4 jam yang ``available``; tanpa itu "
                        "\"tenang\" tidak bisa dibedakan dari \"tidak ada "
                        "data\"."),
            detail={"volume_usd": volume,
                    "volatility_available": bool(vol_metrics.get("available"))},
            sumber="DexScreener + candle GeckoTerminal + GMGN")

    floor = float(min_volume_usd)
    ceiling = float(max_volume_usd)
    quiet = floor <= volume <= ceiling
    stddev = _float(vol_metrics.get("price_stddev_4h"), None)
    history_stddev = _float(vol_metrics.get("history_stddev_pct"), None)
    narrowing = (stddev is not None and history_stddev is not None
                 and history_stddev > 0
                 and stddev <= history_stddev * float(shrink_ratio))
    net_ok = net is not None and 0.0 < net <= float(max_net_pct)

    bits = []
    if volume < floor:
        bits.append(f"volume ${volume:,.0f} di bawah lantai ${floor:,.0f} "
                    "(token terlalu mati — bukan akumulasi senyap)")
    elif volume > ceiling:
        bits.append(f"volume ${volume:,.0f} di atas plafon ${ceiling:,.0f} "
                    "(terlalu ramai untuk disebut senyap)")
    else:
        bits.append(f"volume ${volume:,.0f} dalam rentang tenang "
                    f"${floor:,.0f}–${ceiling:,.0f}")
    if narrowing:
        bits.append(f"range menyempit (stddev 4 jam {stddev:.2f}% ≤ "
                    f"{float(shrink_ratio):g}× konteks {history_stddev:.2f}%)")
    else:
        bits.append("range belum menyempit (stddev 4 jam "
                    f"{_fmt_pct(stddev)} vs konteks {_fmt_pct(history_stddev)})")
    if net_ok:
        bits.append(f"CVD net +{net:.2f}% (positif tipis, ≤ "
                    f"{float(max_net_pct):g}%)")
    elif net is None:
        bits.append("CVD net tidak tersedia")
    else:
        bits.append(f"CVD net {net:+.2f}% di luar rentang 0…"
                    f"{float(max_net_pct):g}%")

    if quiet and narrowing and net_ok:
        status = POSITIF
    elif not quiet and volume < floor:
        status = NEGATIF
    else:
        status = NETRAL

    return metric_result(
        key, nilai={"volume_usd": volume, "price_stddev_4h": stddev,
                    "history_stddev_pct": history_stddev, "cvd_net_pct": net},
        nilai_text=(f"vol ${volume / 1000.0:,.1f}K · stddev "
                    f"{_fmt_pct(stddev)} · CVD {_fmt_pct(net)}"),
        status=status, cukup_data=True, penjelasan="; ".join(bits) + ".",
        detail={"volume_usd": volume, "lantai_usd": floor, "plafon_usd": ceiling,
                "price_stddev_4h": stddev, "history_stddev_pct": history_stddev,
                "cvd_net_pct": net, "range_menyempit": bool(narrowing),
                "volume_tenang": bool(quiet), "cvd_positif_tipis": bool(net_ok)},
        sumber="DexScreener + candle GeckoTerminal + GMGN")


# ---------------------------------------------------------------------------
# Metrik 6 — Spring / Test Pattern
# ---------------------------------------------------------------------------
def aggregate_4h_candles(hourly) -> list[dict]:
    """Agregasi candle hourly jadi candle 4 jam (murni, tanpa jaringan).

    Baris hasil: ``{ts, open, high, low, close, volume_usd, hours}`` dengan
    ``ts`` = awal bucket 4 jam. Pola ini mengikuti
    ``core.aggregate_daily_candles`` (agregasi kalender, bukan rolling).
    """
    buckets: dict[int, dict] = {}
    for candle in hourly or []:
        if not isinstance(candle, dict):
            continue
        ts = _int(candle.get("ts"))
        close = _float(candle.get("close"), None)
        if ts <= 0 or close is None:
            continue
        high = _float(candle.get("high"), close)
        low = _float(candle.get("low"), close)
        opening = _float(candle.get("open"), close)
        volume = _float(candle.get("volume_usd"), 0.0) or 0.0
        slot_ts = (ts // INTERVAL_4H) * INTERVAL_4H
        row = buckets.get(slot_ts)
        if row is None:
            buckets[slot_ts] = {"ts": slot_ts, "open": opening, "high": high,
                                "low": low, "close": close,
                                "volume_usd": volume, "hours": 1}
            continue
        row["high"] = max(row["high"], high)
        row["low"] = min(row["low"], low)
        row["close"] = close
        row["volume_usd"] += volume
        row["hours"] += 1
    return [buckets[ts] for ts in sorted(buckets)]


def derive_support_level(daily_candles, *, lookback_days: int = 7) -> float | None:
    """Level support D1 = low terendah ``lookback_days`` hari terakhir.

    Pengganti ``levels.json`` (repo ini tidak punya ``breakout_guard.py``):
    diturunkan dari candle harian ``core.get_daily_candles`` yang sudah ada.
    """
    rows = [row for row in (daily_candles or [])
            if isinstance(row, dict) and _float(row.get("low"), None) is not None]
    rows = rows[-max(1, int(lookback_days)):]
    if not rows:
        return None
    return round(min(_float(row.get("low")) for row in rows), 12)


def spring_test_pattern(candles_4h=None, *, level=None, hourly=None,
                        daily_candles=None,
                        volume_ratio_max: float = SPRING_VOLUME_RATIO,
                        lookback: int = SPRING_LOOKBACK,
                        neighbors: int = 4) -> dict:
    """Candle 4 jam menusuk level ke bawah lalu close di atasnya, volume tipis.

    ``level`` boleh disuntikkan; bila kosong diturunkan dari candle harian
    lewat :func:`derive_support_level`. ``candles_4h`` boleh kosong bila
    ``hourly`` (candle hourly ``core.get_hourly_candles``) diberikan.
    """
    key = "spring_test"
    rows = [row for row in (candles_4h or []) if isinstance(row, dict)]
    if not rows and hourly:
        rows = aggregate_4h_candles(hourly)
    support = _float(level, None)
    if support is None:
        support = derive_support_level(daily_candles)
    if support is None or support <= 0:
        return metric_result(
            key, nilai_text="—",
            penjelasan=("Level support D1 tidak tersedia (candle harian "
                        "kosong), jadi pola spring/test tidak bisa diuji."),
            detail={"candles_4h": len(rows)},
            sumber="candle GeckoTerminal (H4 + D1)")
    if len(rows) < 3:
        return metric_result(
            key, nilai_text="—",
            penjelasan=(f"Hanya {len(rows)} candle 4 jam tersedia; butuh "
                        "minimal 3 untuk membandingkan volume dengan "
                        "candle sekitarnya."),
            detail={"candles_4h": len(rows), "level": support},
            sumber="candle GeckoTerminal (H4 + D1)")

    window = rows[-max(3, int(lookback)):]
    found = None
    for index in range(len(window) - 1, -1, -1):
        candle = window[index]
        low = _float(candle.get("low"), None)
        close = _float(candle.get("close"), None)
        if low is None or close is None:
            continue
        if low >= support or close <= support:
            continue  # tidak menusuk, atau malah close di bawah level
        start = max(0, index - int(neighbors))
        around = [row for row in window[start:index + int(neighbors) + 1]
                  if row is not candle]
        volumes = [_float(row.get("volume_usd"), 0.0) or 0.0 for row in around]
        average = (sum(volumes) / len(volumes)) if volumes else 0.0
        volume = _float(candle.get("volume_usd"), 0.0) or 0.0
        ratio = (volume / average) if average > 0 else None
        quiet = ratio is not None and ratio <= float(volume_ratio_max)
        found = {
            "ts": _int(candle.get("ts")), "low": low, "close": close,
            "wick_pct": round((support - low) / support * 100.0, 3)
            if support > 0 else None,
            "volume_usd": volume, "avg_neighbor_volume_usd": round(average, 2),
            "volume_ratio": round(ratio, 3) if ratio is not None else None,
            "volume_tenang": bool(quiet),
        }
        break

    if not found:
        return metric_result(
            key, nilai={"level": support}, nilai_text="tidak ada spring",
            status=NETRAL, cukup_data=True,
            penjelasan=(f"Tidak ada candle 4 jam (dari {len(window)} terakhir) "
                        f"yang menusuk di bawah level ${support:,.6g} lalu "
                        "close kembali di atasnya."),
            detail={"candles_4h": len(rows), "level": support,
                    "diperiksa": len(window)},
            sumber="candle GeckoTerminal (H4 + D1)")

    if found["volume_tenang"]:
        status = POSITIF
        alasan = (f"Candle 4 jam menusuk ${found['low']:,.6g} di bawah level "
                  f"${support:,.6g} ({found['wick_pct']:.2f}%) lalu close "
                  f"${found['close']:,.6g} di atasnya, dengan volume "
                  f"{found['volume_ratio']:.2f}× rata-rata sekitarnya "
                  f"(≤ {float(volume_ratio_max):g}×) — supply di bawah level "
                  "tipis, khas spring/test.")
    else:
        status = NETRAL
        alasan = (f"Ada tusukan ke bawah level lalu close di atasnya, tetapi "
                  f"volume {found['volume_ratio']:.2f}× rata-rata sekitarnya "
                  f"(ambang ≤ {float(volume_ratio_max):g}×) — lebih mirip "
                  "volatilitas biasa daripada spring bervolume tipis.")

    return metric_result(
        key, nilai=found,
        nilai_text=(f"spring {found['wick_pct']:.2f}% di bawah level · vol "
                    f"{found['volume_ratio']:.2f}×"),
        status=status, cukup_data=True, penjelasan=alasan,
        detail={**found, "level": support, "candles_4h": len(rows),
                "volume_ratio_max": float(volume_ratio_max)},
        sumber="candle GeckoTerminal (H4 + D1)")


# ---------------------------------------------------------------------------
# Metrik 7 — Fresh wallet "prep sebelum pump" (pengganti funder chain)
# ---------------------------------------------------------------------------
def funder_prep_cluster(swaps, wallet_meta=None, *,
                        min_wallets: int = FRESH_MIN_WALLETS,
                        min_buys: int = FRESH_MIN_BUYS,
                        min_span_minutes: int = FRESH_MIN_SPAN_MIN,
                        max_single_share: float = FRESH_MAX_SINGLE_SHARE,
                        now=None) -> dict:
    """Wallet baru (🐣 ``fresh_wallet``) yang beli pelan-pelan tanpa jual.

    Repo ini **tidak punya** scan funder/cluster (butuh Helius), jadi identitas
    "funder sama" tidak tersedia. Yang diukur: wallet bertag ``fresh_wallet``
    (GMGN) dengan ≥ ``min_buys`` buy yang **tersebar** (rentang waktu
    ≥ ``min_span_minutes``, bukan satu sniper instan), tidak ada satu buy yang
    mendominasi, dan **tidak ada sell sama sekali** sejauh ini.
    """
    key = "funder_prep"
    profiles = wallet_profiles(swaps)
    meta = wallet_meta if isinstance(wallet_meta, dict) else {}
    fresh = []
    for wallet, item in profiles.items():
        info = meta.get(wallet) if isinstance(meta.get(wallet), dict) else {}
        tags = item["tags"] | {normalize_tag(tag)
                               for tag in (info.get("maker_tags") or [])}
        if FRESH_WALLET_TAG not in tags:
            continue
        fresh.append(item)

    if len(fresh) < max(1, int(min_wallets)):
        return metric_result(
            key, nilai_text=f"{len(fresh)} wallet fresh",
            penjelasan=(f"{len(fresh)} wallet bertag fresh_wallet teramati dari "
                        f"{len(profiles)} wallet (ambang {int(min_wallets)}). "
                        "Tanpa jumlah yang cukup, pola 'persiapan' tidak bisa "
                        "dibedakan dari pembeli baru biasa."),
            detail={"fresh_wallets": len(fresh), "wallets": len(profiles)},
            sumber="GMGN token trades (tag fresh_wallet)")

    gradual = []
    for item in fresh:
        if item["buy_tx"] < int(min_buys) or item["sell_tx"] > 0:
            continue
        span = ((item["last_buy_ts"] or 0) - (item["first_buy_ts"] or 0))
        if span < int(min_span_minutes) * 60:
            continue
        total = item["buy_sol"] or 0.0
        largest = max(item["buys"]) if item["buys"] else 0.0
        if total > 0 and (largest / total) > float(max_single_share):
            continue
        gradual.append({"wallet": item["wallet"], "buy_tx": item["buy_tx"],
                        "span_minutes": round(span / 60.0, 1),
                        "buy_sol": round(item["buy_sol"], 4)})

    share = _pct(len(gradual), len(fresh)) or 0.0
    if len(gradual) >= max(2, int(min_wallets)):
        status = POSITIF
        alasan = (f"{len(gradual)}/{len(fresh)} wallet baru ({share:.0f}%) "
                  f"membeli bertahap (≥ {int(min_buys)} buy, tersebar "
                  f"≥ {int(min_span_minutes)} menit) tanpa satu pun sell — "
                  "pola masuk pelan-pelan sebelum pergerakan.")
    elif gradual:
        status = NETRAL
        alasan = (f"{len(gradual)}/{len(fresh)} wallet baru beli bertahap "
                  "tanpa jual; jumlahnya terlalu sedikit untuk disebut "
                  "kelompok.")
    else:
        status = NEGATIF
        alasan = (f"{len(fresh)} wallet baru teramati tetapi semuanya sniper "
                  "instan atau sudah pernah menjual — bukan pola persiapan.")

    return metric_result(
        key, nilai={"fresh_wallets": len(fresh), "gradual_no_sell": len(gradual),
                    "share_pct": share},
        nilai_text=(f"{len(gradual)}/{len(fresh)} wallet 🐣 beli bertahap, "
                    "0 sell"),
        status=status, cukup_data=True, penjelasan=alasan + (
            " ⚠️ Heuristik: identitas funder tidak tersedia (scan funder "
            "Helius sengaja tidak dijalankan untuk hemat kuota), jadi ini "
            "menandai **pola** wallet baru, bukan bukti satu pemilik."),
        detail={"fresh_wallets": len(fresh), "gradual": gradual[:10],
                "min_buys": int(min_buys),
                "min_span_minutes": int(min_span_minutes),
                "max_single_share": float(max_single_share)},
        sumber="GMGN token trades (tag fresh_wallet + pola waktu buy)")


# ---------------------------------------------------------------------------
# Metrik 8 — Sell-Side Liquidity Thinning
# ---------------------------------------------------------------------------
def sell_side_thinning(swaps, *, days: int = THINNING_DAYS, now=None,
                       previous=None, positif_pct: float = THINNING_POSITIF_PCT) -> dict:
    """% pasokan (dari flow yang teramati) dipegang wallet tanpa jual N hari.

    Basisnya swap GMGN: ``net_sol`` per wallet = total buy − total sell. Wallet
    "tenang" = masih punya posisi net positif **dan** tidak pernah jual atau
    sell terakhirnya lebih tua dari ``days`` hari. ``previous`` (dari
    :func:`load_accumulation_history`) dipakai untuk menunjukkan arah
    proporsinya dari waktu ke waktu.
    """
    key = "sell_side_thinning"
    profiles = wallet_profiles(swaps)
    holders = [item for item in profiles.values() if item["net_sol"] > 0]
    if len(holders) < max(1, MIN_WALLETS_FOR_FLOW):
        return metric_result(
            key, nilai_text="—",
            penjelasan=(f"Hanya {len(holders)} wallet dengan posisi net "
                        f"positif; butuh minimal {MIN_WALLETS_FOR_FLOW} "
                        "supaya proporsi tidak ditentukan satu wallet."),
            detail={"holders": len(holders)}, sumber="GMGN token trades")

    anchor = _int(now, None) or max(
        (item["last_ts"] for item in profiles.values()), default=0)
    cutoff = anchor - int(days) * SECONDS_PER_DAY
    quiet = [item for item in holders
             if item["last_sell_ts"] is None or item["last_sell_ts"] <= cutoff]
    quiet_sol = sum(item["net_sol"] for item in quiet)
    total_sol = sum(item["net_sol"] for item in holders)
    share = _pct(quiet_sol, total_sol) or 0.0
    previous_share = _float(previous, None)
    delta = (round(share - previous_share, 2)
             if previous_share is not None else None)

    bits = [f"{share:.1f}% posisi net (dari {len(holders)} wallet holder) "
            f"dipegang {len(quiet)} wallet tanpa jual dalam {int(days)} hari"]
    if delta is not None:
        bits.append(f"perubahan {delta:+.2f} pp dari pengukuran sebelumnya "
                    f"({previous_share:.1f}%)")
    if share >= float(positif_pct):
        status = POSITIF
        bits.append(f"di atas ambang {float(positif_pct):g}% — sisi jual "
                    "menipis")
    elif share >= 50.0:
        status = NETRAL
        bits.append("sebagian pasokan masih di tangan wallet yang aktif jual")
    else:
        status = NEGATIF
        bits.append("mayoritas pasokan masih di wallet yang baru saja jual — "
                    "sisi jual tebal")

    return metric_result(
        key, nilai={"quiet_share_pct": share, "quiet_wallets": len(quiet),
                    "holders": len(holders), "quiet_sol": round(quiet_sol, 4),
                    "total_sol": round(total_sol, 4), "delta_pp": delta},
        nilai_text=(f"{share:.1f}% supply tenang"
                    + (f" ({delta:+.2f} pp)" if delta is not None else "")),
        status=status, cukup_data=True, penjelasan="; ".join(bits) + ".",
        detail={"quiet_wallets": len(quiet), "holders": len(holders),
                "days": int(days), "anchor_ts": anchor,
                "previous_pct": previous_share, "delta_pp": delta,
                "ambang_positif_pct": float(positif_pct),
                "catatan": ("Basis = flow swap yang teramati di window GMGN, "
                            "bukan total supply on-chain (butuh scan holder "
                            "Helius).")},
        sumber="GMGN token trades (posisi net per wallet)")


# ---------------------------------------------------------------------------
# Skor gabungan + laporan per token
# ---------------------------------------------------------------------------
def _status_score(status: str) -> float | None:
    return {POSITIF: 1.0, NETRAL: 0.5, NEGATIF: 0.0}.get(status)


def accumulation_score(results, *, weights: dict | None = None) -> dict:
    """Skor akumulasi 0-100 dari metrik yang ``cukup_data``.

    Metrik tanpa data **tidak** ikut pembagi — token dengan 1 metrik tersedia
    tidak dihukum/diganjar seolah 8 metrik terukur.
    """
    weights = weights or METRIC_WEIGHTS
    total_weight = 0.0
    earned = 0.0
    used = 0
    for result in results or []:
        if not isinstance(result, dict) or not result.get("cukup_data"):
            continue
        value = _status_score(str(result.get("status")))
        if value is None:
            continue
        weight = _float(result.get("bobot"),
                        _float(weights.get(str(result.get("key"))), 1.0)) or 1.0
        total_weight += weight
        earned += weight * value
        used += 1
    if total_weight <= 0 or not used:
        return {"skor": None, "metrik_dipakai": 0, "metrik_total": len(list(results or [])),
                "status": TOKEN_NO_DATA}
    score = round(earned / total_weight * 100.0, 1)
    return {"skor": score, "metrik_dipakai": used,
            "metrik_total": len(list(results or [])),
            "status": (TOKEN_AKUMULASI if score >= SCORE_AKUMULASI
                       else TOKEN_NETRAL)}


def token_status(results) -> str:
    """Status ringkas token: akumulasi / netral / tidak cukup data."""
    return accumulation_score(results)["status"]


def build_token_report(mint: str, symbol: str = "?", *, points=None, swaps=None,
                       wallet_meta=None, market=None, volatility=None,
                       candles_4h=None, hourly=None, daily_candles=None,
                       level=None, volume_usd=None, cvd_net=None,
                       previous_thinning=None, thinning_days: int = THINNING_DAYS,
                       now=None) -> dict:
    """Rangkai 8 metrik jadi satu laporan token (murni, tanpa jaringan).

    Semua bahan mentah disuntikkan pemanggil; lihat docstring modul untuk
    sumber tiap bahan.
    """
    market = market if isinstance(market, dict) else {}
    volume = _float(volume_usd, None)
    if volume is None:
        raw_volume = (market.get("volume") or {})
        if isinstance(raw_volume, dict):
            volume = _float(raw_volume.get("h24"), None)
    results = [
        tier_migration_velocity(points),
        diamond_hands_ratio(swaps),
        dca_vs_oneoff(swaps),
        smart_money_pnl(swaps, wallet_meta),
        silent_range_accumulation(volume_usd=volume, volatility=volatility,
                                  cvd_net=cvd_net, swaps=swaps),
        spring_test_pattern(candles_4h, level=level, hourly=hourly,
                            daily_candles=daily_candles),
        funder_prep_cluster(swaps, wallet_meta, now=now),
        sell_side_thinning(swaps, days=thinning_days, now=now,
                           previous=previous_thinning),
    ]
    summary = accumulation_score(results)
    positives = [row["key"] for row in results
                 if row["status"] == POSITIF and row.get("cukup_data")]
    missing = [row["key"] for row in results if not row.get("cukup_data")]
    return {
        "mint": str(mint or ""),
        "symbol": str(symbol or "?").upper(),
        "generated_at": _int(now, None) or int(time.time()),
        "metrics": {row["key"]: row for row in results},
        "results": results,
        "score": summary["skor"],
        "status": summary["status"],
        "metrics_used": summary["metrik_dipakai"],
        "metrics_total": summary["metrik_total"],
        "positives": positives,
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Store snapshot terpisah (skema sendiri, tidak menyentuh file data lain)
# ---------------------------------------------------------------------------
def empty_store() -> dict:
    return {"schema": "wallet-depth-accumulation-v1", "updated_at": None,
            "tokens": {}}


def load_accumulation_history(path: str | None = None) -> dict:
    """Baca ``accumulation_history.json``; rusak/hilang → store kosong."""
    target = path or ACCUMULATION_HISTORY_PATH
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:  # noqa: BLE001 - state opsional tidak boleh melempar
        return empty_store()
    if not isinstance(data, dict):
        return empty_store()
    tokens = data.get("tokens")
    store = empty_store()
    store["tokens"] = tokens if isinstance(tokens, dict) else {}
    store["updated_at"] = data.get("updated_at")
    return store


def thinning_previous(store: dict | None, mint: str) -> float | None:
    """Proporsi sell-side thinning pengukuran sebelumnya (untuk delta)."""
    slot = ((store or {}).get("tokens") or {}).get(str(mint or "")) or {}
    rows = slot.get("thinning") if isinstance(slot, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    last = rows[-1]
    return _float(last.get("quiet_share_pct"), None) if isinstance(last, dict) \
        else None


def record_snapshot(store: dict | None, mint: str, report: dict | None,
                    *, now=None, max_points: int = 60) -> dict:
    """Simpan ringkasan satu laporan (mutasi ``store``) untuk delta berikutnya.

    Hanya angka ringkas yang disimpan (skor, status, thinning, jumlah metrik)
    supaya file tetap kecil dan tidak menduplikasi store holder.
    """
    store = store if isinstance(store, dict) else empty_store()
    store.setdefault("tokens", {})
    mint = str(mint or "").strip()
    report = report if isinstance(report, dict) else {}
    if not mint:
        return store
    stamp = _int(now, None) or _int(report.get("generated_at")) or int(time.time())
    thinning = (report.get("metrics") or {}).get("sell_side_thinning") or {}
    slot = store["tokens"].setdefault(mint, {"symbol": report.get("symbol"),
                                             "points": [], "thinning": []})
    slot["symbol"] = report.get("symbol") or slot.get("symbol")
    slot["points"].append({
        "ts": stamp,
        "score": _float(report.get("score"), None),
        "status": str(report.get("status") or ""),
        "metrics_used": _int(report.get("metrics_used")),
        "positives": list(report.get("positives") or []),
    })
    if isinstance(thinning, dict) and thinning.get("cukup_data"):
        slot["thinning"].append({
            "ts": stamp,
            "quiet_share_pct": _float((thinning.get("nilai") or {})
                                      .get("quiet_share_pct"), None),
            "quiet_wallets": _int((thinning.get("nilai") or {})
                                  .get("quiet_wallets")),
        })
    for key in ("points", "thinning"):
        if len(slot[key]) > int(max_points):
            del slot[key][:-int(max_points)]
    store["updated_at"] = stamp
    return store


def save_accumulation_history(store: dict | None, path: str | None = None) -> dict:
    """Tulis store snapshot (atomic, pola ``core.atomic_write_json``)."""
    from core import atomic_write_json

    store = store if isinstance(store, dict) else empty_store()
    target = path or ACCUMULATION_HISTORY_PATH
    try:
        atomic_write_json(target, store)
    except Exception as exc:  # noqa: BLE001 - state opsional
        print(f"WARN: gagal menyimpan {target}: {exc}")
    return store
