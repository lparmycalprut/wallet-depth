"""Konfirmasi struktur harga (SBR) untuk gate alert reversal realtime.

Sinyal flow (REVERSAL_UP / REVERSAL_DOWN dari ``reversal_engine``) hanya boleh
mengirim alert Telegram setelah struktur harga mengonfirmasi. Modul ini
membangun candle dari stream trade yang sudah di-fetch scanner (tanpa API
baru) lalu mengevaluasi:

1. **Zona SBR** — shelf support (UP) / resistance (DOWN) dominan: klaster low
   (atau high) yang paling banyak disentuh sebelum ekstrem, dibentuk cukup
   lama (≥ ``min_span_sec``) dan cukup rapat (lebar band ≤ 3%).
2. **Higher-low** — anchor struktur adalah ekstrem global window; undercut apa
   pun di bawahnya otomatis memindahkan anchor (fakeout kecil menjadi low baru
   yang sah), sehingga "tidak bisa buat low baru" tervalidasi secara
   konstruksi terhadap anchor terakhir.
3. **Reclaim** — ada close di atas tepi zona SETELAH anchor, dan saat
   evaluasi close terakhir masih bertahan di/atas dasar zona.

Empat pola konfirmasi yang diakomodasi (dari pengujian manual):
  P1 retest SBR → tidak bisa low baru → breakout → pump
  P2 retest SBR → fakeout kecil di bawah lowest low → pump   (anchor bergeser
      ke low fakeout; reclaim setelahnya menutup case)
  P3 retest SBR → reclaim → kembali ke last low → reclaim ulang (hold longgar:
      hanya close terakhir vs dasar zona yang dinilai)
  P4 last support breakout → fast reclaim (<3 jam)           (tanpa batas waktu)

Dikalibrasi pada kasus DREGG 17–18 Agu 2026: zona yang dipilih harus shelf
0.000266–0.000272, wick-retest 00:15 (0.00027289, tanpa close di atas zona)
TIDAK mengonfirmasi, konfirmasi baru sah saat candle 08:30 WIB close 0.0002936,
dan dip retest 0.0002699 dari atas zona tidak membatalkan konfirmasi.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

CONFIRMED = "confirmed"
FORMING = "forming"
NO_ZONE = "no_zone"
NO_DATA = "no_data"

FORMING_LOW = "forming"
HIGHER_LOW = "higher_low"    # UP: tidak ada low baru / DOWN: tidak ada high baru


@dataclass(frozen=True)
class StructureConfig:
    """Ambang deteksi zona SBR (dikalibrasi pada DREGG, lihat docstring modul)."""

    interval_sec: int = 300          # candle 5 menit dari stream trade
    band_tol: float = 0.025          # low digabung ke band bila ≤ 2.5% dari dasarnya
    max_band_width: float = 0.03     # lebar band maksimal 3%
    min_touches: int = 3             # shelf butuh ≥ 3 sentuhan
    min_span_sec: int = 3600         # dan terbentuk ≥ 1 jam (bukan ledge sekejap)
    min_zone_height: float = 0.08    # zona ≥ 8% di atas flush low (bukan dasar V)
    hold_tol: float = 0.01           # hold: close terakhir ≥ dasar zona − 1%


def bars_from_trades(trades, interval_sec: int = 300,
                     now_ts: int | None = None) -> list[dict]:
    """Bangun candle OHLC dari trade (``timestamp`` + ``price_usd``).

    Candle yang masih berjalan (belum tutup pada ``now_ts``) dibuang supaya
    semua keputusan memakai close yang sudah_final._ Trade tanpa harga valid
    di-skip; bar kosong (tidak ada trade) tidak direpresentasikan.
    """
    buckets: dict[int, list[float]] = {}
    for row in trades or ():
        try:
            ts = int(row.get("timestamp") or row.get("ts") or 0)
            price = float(row.get("price_usd") or row.get("price") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if ts <= 0 or price <= 0:
            continue
        bucket = ts - (ts % interval_sec)
        if now_ts is not None and bucket + interval_sec > now_ts:
            continue  # candle berjalan: jangan dipakai untuk keputusan close
        buckets.setdefault(bucket, []).append((ts, price))
    bars = []
    for bucket in sorted(buckets):
        points = sorted(buckets[bucket])
        prices = [p for _ts, p in points]
        bars.append({"ts": bucket, "open": points[0][1],
                     "high": max(prices), "low": min(prices),
                     "close": points[-1][1]})
    return bars


def _invert(bars: list[dict]) -> list[dict]:
    """Balik harga (1/x) sehingga logika UP dapat dipakai untuk sisi DOWN.

    Setiap field dipetakan dari field yang sama (close' = 1/close) supaya
    semua keputusan berbasis close tetap memakai close harga asli; hanya
    high/low yang bertukar karena 1/x monoton turun.
    """
    return [{"ts": b["ts"], "open": 1.0 / b["open"], "high": 1.0 / b["low"],
             "low": 1.0 / b["high"], "close": 1.0 / b["close"]}
            for b in bars]


def find_support_zone(bars: list[dict], low_idx: int,
                      cfg: StructureConfig) -> dict | None:
    """Zona SBR = band low paling dominan sebelum flush low.

    Band dibentuk dengan mengelompokkan low candle (urut harga) ke dalam
    toleransi ``band_tol``; band sah bila cukup sentuhan, cukup rapat, terbentuk
    cukup lama, dan berada ≥ ``min_zone_height`` di atas flush low — supaya
    ledge-ledge kecil di dalam kaskade turun tidak ikut terpilih. Pemenang:
    sentuhan terbanyak, tie-break band terendah ("last support" terakhir).
    """
    extreme = bars[low_idx]["low"]
    floor = extreme * (1 + cfg.min_zone_height)
    lows = sorted(b["low"] for b in bars[:low_idx] if b["low"] >= floor)
    clusters: list[dict] = []
    for value in lows:
        if clusters and value <= clusters[-1]["low"] * (1 + cfg.band_tol):
            clusters[-1]["high"] = value
            clusters[-1]["vals"].append(value)
        else:
            clusters.append({"low": value, "high": value, "vals": [value]})
    best = None
    for cluster in clusters:
        lo, hi = cluster["low"], cluster["high"]
        hits = [b["ts"] for b in bars[:low_idx]
                if lo * 0.999 <= b["low"] <= hi * (1 + cfg.band_tol)]
        width = hi / lo - 1.0
        if (len(hits) < cfg.min_touches or width > cfg.max_band_width
                or max(hits) - min(hits) < cfg.min_span_sec):
            continue
        cand = {"low": lo, "high": hi, "touches": len(hits),
                "first_ts": min(hits), "last_ts": max(hits)}
        if best is None or (cand["touches"], -cand["low"]) > \
                            (best["touches"], -best["low"]):
            best = cand
    if best:
        best.pop("vals", None)
    for cluster in clusters:
        cluster.pop("vals", None)
    return best


def _detect_up(bars: list[dict], cfg: StructureConfig) -> dict:
    """Logika UP pada skala harga apa adanya (lihat ``detect_structure``)."""
    # Ekstrem flush low dihitung dari candle yang sudah tutup saja.
    low_idx = min(range(len(bars)), key=lambda i: bars[i]["low"])
    extreme = bars[low_idx]["low"]
    post = bars[low_idx + 1:]
    low_state = FORMING_LOW if not post else HIGHER_LOW
    out = {
        "state": FORMING, "zone": None, "low_state": low_state,
        "extreme": extreme, "extreme_ts": bars[low_idx]["ts"],
        "reclaim_ts": None, "last_close": bars[-1]["close"], "reason": "",
    }
    if low_idx == 0 or not post:
        out["reason"] = ("flush low belum terbentuk penuh"
                         if not post
                         else "tidak ada riwayat sebelum flush low")
        return out
    zone = find_support_zone(bars, low_idx, cfg)
    if not zone:
        out.update(state=NO_ZONE,
                   reason="tidak ada shelf support dominan di window 31 jam")
        return out
    out["zone"] = {"low": zone["low"], "high": zone["high"],
                   "touches": zone["touches"]}
    top, bottom = zone["high"], zone["low"]
    reclaim = next((b for b in post if b["close"] > top), None)
    if not reclaim:
        out["reason"] = "belum ada close di atas zona SBR — masih di bawah"
        return out
    out["reclaim_ts"] = reclaim["ts"] + cfg.interval_sec
    if bars[-1]["close"] < bottom * (1 - cfg.hold_tol):
        out["reason"] = "reclaim gagal bertahan — close balik di bawah zona"
        return out
    out.update(state=CONFIRMED, reason="")
    return out


def detect_structure(bars: list[dict], side: str,
                     cfg: StructureConfig | None = None) -> dict:
    """Verdict struktur untuk satu sisi ("up"/"down") dari candle terurut.

    Semua candle input harus sudah tutup (lihat ``bars_from_trades``). Sisi
    DOWN dievaluasi pada harga terbalik (1/x) lalu dipetakan kembali ke skala
    harga asli, sehingga satu set aturan melayani dua arah.
    """
    cfg = cfg or StructureConfig()
    bars = [b for b in (bars or []) if
            b.get("low", 0) > 0 and b.get("high", 0) > 0]
    base = {"side": side, "state": NO_DATA, "zone": None, "low_state": None,
            "extreme": None, "extreme_ts": None, "reclaim_ts": None,
            "last_close": None, "reason": "data candle kosong"}
    if len(bars) < 5:
        base["reason"] = f"bar terlalu sedikit ({len(bars)})"
        return base
    if side == "down":
        inv = _invert(bars)
        raw = _detect_up(inv, cfg)
        out = dict(raw)
        out["zone"] = None
        if raw.get("zone"):
            out["zone"] = {"low": 1.0 / raw["zone"]["high"],
                           "high": 1.0 / raw["zone"]["low"],
                           "touches": raw["zone"]["touches"]}
        for key in ("extreme", "last_close"):
            if raw.get(key):
                out[key] = 1.0 / raw[key]
        out["side"] = "down"
        return out
    out = _detect_up(bars, cfg)
    out["side"] = "up"
    return out


CONFIG_FIELDS = tuple(asdict(StructureConfig()))
