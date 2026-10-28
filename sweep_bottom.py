"""Sinyal bottom — info saja (permintaan user 2026-10-28).

Empat indikator. Masing-masing hanya membaca data yang sudah tersimpan:

1. ``div_cvd``      — divergensi CVD bullish dari bucket jam delta (jendela 6 jam).
2. ``tmc_stall``    — token/MC tidak naik lagi sementara harga turun (snapshot per jam).
3. ``pool_hold``    — sisi quote pool tidak terkuras sementara harga turun (proksi LP).
4. ``shakeout_hold``— harga masih di atas low shakeout yang sudah dilatch.

Modul ini murni (tanpa jaringan, tanpa state). Tidak memengaruhi kriteria, skor,
vonis, ``eligible``, urutan tabel, atau filter. Hanya ditampilkan sebagai kolom
info dan di panel detail.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))

CVD_MIN_BUCKETS = 3        # minimal bucket jam yang punya harga untuk membandingkan low
TMC_WINDOW = 4             # snapshot: 4 titik ≈ 3 jam terakhir
TMC_PRIOR_OFFSET = 7       # snapshot pembanding sebelum jendela (≈ 6 jam lalu)
TMC_FLAT_PP = 0.5          # token/MC dianggap "tidak naik" bila naik ≤ 0,5 poin persen
TMC_PRICE_DOWN = -0.05     # harga turun ≥ 5% dalam jendela
POOL_WINDOW = 7            # snapshot: 7 titik ≈ 6 jam terakhir
POOL_HOLD_MIN = -0.05      # sisi quote tidak turun lebih dari 5%
POOL_PRICE_DOWN = -0.10    # harga turun ≥ 10% dalam jendela
SHORT_LABELS = {
    "div_cvd": "CVD↗",
    "tmc_stall": "Token/MC⏸",
    "pool_hold": "Pool tahan",
    "shakeout_hold": "Low bertahan",
}
ITEM_TITLES = {
    "div_cvd": "Divergensi CVD bullish",
    "tmc_stall": "Token/MC berhenti naik",
    "pool_hold": "Sisi quote pool tahan",
    "shakeout_hold": "Di atas low shakeout",
}
EXPLAIN = {
    "div_cvd": (
        "**Divergensi CVD bullish:** harga membuat *low baru* (sama atau lebih "
        "rendah dari low sebelumnya dalam jendela), tetapi CVD justru *lebih "
        "tinggi* dari nilai saat low itu. CVD = akumulasi (beli − jual) dalam USD "
        "sejak awal jendela. Artinya sejak low itu, pembelian bersih positif: "
        "harga turun ke level yang sama, tetapi jual yang masuk lebih sedikit "
        "dan ada pembeli yang menyerap jual. Ini sinyal awal, bukan kepastian "
        "bottom: harga bisa tetap turun.\n\n"
        "**Batas:** jendela hanya 6 jam (6 bucket jam), dan bucket jam terakhir "
        "bisa belum tutup. Harga per jam berasal dari candle. Delta yang tersimpan "
        "sebelum 28 Okt 2026 belum punya harga per jam, jadi indikator ini baru "
        "terisi setelah scan berikutnya."),
    "tmc_stall": (
        "**Token/MC** = nilai token di pool ÷ MC. Token/MC naik berarti token "
        "masuk ke pool (biasanya jual ke pool). Indikator aktif bila dalam ~3 jam "
        "terakhir token/MC tidak naik lagi (≤ +0,5 poin persen) sementara harga "
        "turun ≥ 5%. Tekanan jual ke pool berhenti walau harga masih turun.\n\n"
        "**Batas:** transfer wallet ke wallet dan perubahan LP tidak terlihat di "
        "sini. Riwayat hanya sejak token/MC mulai dicatat (27 Okt 2026)."),
    "pool_hold": (
        "**Sisi quote pool** = likuiditas total − nilai sisi token (proksi USD; "
        "sisi quote biasanya SOL atau USDC). Indikator aktif bila sisi quote tidak "
        "turun lebih dari 5% dalam ~6 jam sementara harga turun ≥ 10%. Tanda bahwa "
        "pool tidak sedang dikuras, bukan LP yang ditarik.\n\n"
        "**Batas:** di pool CPMM, jual ke pool juga mengurangi sisi quote. Jadi "
        "indikator ini hanya menyatakan tidak ada penarikan besar, bukan bahwa "
        "tekanan jual sudah berhenti."),
    "shakeout_hold": (
        "**Low shakeout** = low candle saat shakeout pertama kali terdeteksi "
        "(latch permanen). Indikator aktif bila harga sekarang masih di atas low "
        "itu dan tidak ada candle yang melanggarnya. Ini cek lanjutan dari "
        "kriteria 6 (shakeout + higher low), tidak menggantikannya."),
}


def _f(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # buang NaN


def _wib(ts) -> str:
    return datetime.fromtimestamp(int(ts), WIB).strftime("%d %b %H:%M WIB")


def _usd(value, signed: bool = False) -> str:
    number = _f(value)
    if number is None:
        return "—"
    if signed:
        return f"{'−' if number < 0 else '+'}${abs(number):,.0f}"
    return f"{'−' if number < 0 else ''}${abs(number):,.0f}"


def _price(value) -> str:
    number = _f(value)
    return "—" if number is None else f"${number:.6g}"


def _pp(value) -> str:
    """Selisih dalam poin persen dengan tanda minus yang konsisten."""
    number = _f(value)
    return "—" if number is None else f"{'−' if number < 0 else '+'}{abs(number):.2f} poin persen"


def _pct(value, digits: int = 1, signed: bool = True) -> str:
    number = _f(value)
    if number is None:
        return "—"
    text = f"{number * 100:+.{digits}f}%" if signed else f"{number * 100:.{digits}f}%"
    return text.replace("-", "−")


def _item(key: str, *, available: bool, active: bool = False, reason: str = "",
          lines=None, data=None) -> dict:
    return {
        "key": key,
        "title": ITEM_TITLES[key],
        "short": SHORT_LABELS[key],
        "available": bool(available),
        "active": bool(active) if available else False,
        "reason": reason,
        "lines": list(lines or []),
        "data": data or {},
        "explain": EXPLAIN[key],
    }


def cvd_divergence(delta) -> dict:
    """Divergensi CVD bullish: harga low baru, CVD lebih tinggi dari low sebelumnya."""
    key = "div_cvd"
    if not delta:
        return _item(key, available=False,
                     reason="bukan kandidat delta (kohort SKIP/TANPA DATA/TIDAK LAYAK)")
    if not delta.get("available"):
        return _item(key, available=False,
                     reason=f"delta belum tersedia: {delta.get('reason') or 'tidak ada data'}")
    buckets = [b for b in (delta.get("buckets") or [])
               if _f(b.get("price")) is not None and _f(b.get("cvd")) is not None]
    if len(buckets) < CVD_MIN_BUCKETS:
        return _item(key, available=False,
                     reason=(f"harga per jam belum cukup ({len(buckets)} dari "
                             f"{CVD_MIN_BUCKETS} jam); tunggu scan berikutnya"))
    last = buckets[-1]
    prev = buckets[:-1]
    low_price = min(_f(b["price"]) for b in prev)
    low = [b for b in prev if _f(b["price"]) == low_price][-1]  # low terbaru bila seri
    now_price = _f(last["price"])
    now_cvd = _f(last["cvd"])
    low_cvd = _f(low["cvd"])
    new_low = now_price <= low_price
    cvd_up = now_cvd > low_cvd
    active = new_low and cvd_up
    cvd_change = now_cvd - low_cvd
    vs_low = now_price / low_price - 1.0 if low_price > 0 else None
    if active:
        reason = ""
    elif not new_low:
        reason = (f"belum: harga {_pct(vs_low)} di atas low sebelumnya")
    else:
        reason = (f"belum: CVD tidak lebih tinggi dari low (selisih "
                  f"{_usd(cvd_change, signed=True)})")
    lines = [
        f"Jendela: {len(buckets)} bucket jam, CVD dihitung dari awal jendela.",
        f"Low sebelumnya: {_wib(low['ts'])} · harga {_price(low_price)} · "
        f"CVD {_usd(low_cvd, signed=True)}",
        f"Sekarang: {_wib(last['ts'])} · harga {_price(now_price)} · "
        f"CVD {_usd(now_cvd, signed=True)}",
        f"Harga sekarang vs low: {_pct(vs_low)} · perubahan CVD sejak low: "
        f"{_usd(cvd_change, signed=True)}",
    ]
    data = {"low_ts": int(low["ts"]), "low_price": low_price, "low_cvd": low_cvd,
            "now_ts": int(last["ts"]), "now_price": now_price, "now_cvd": now_cvd,
            "cvd_change": cvd_change, "vs_low": vs_low, "buckets": len(buckets)}
    return _item(key, available=True, active=active, reason=reason,
                 lines=lines, data=data)


def _token_mc(row):
    value = _f(row.get("token_mc"))
    if value is not None:
        return value
    base, fdv = _f(row.get("pool_base_usd")), _f(row.get("fdv_usd"))
    if base is None or fdv is None or base < 0 or fdv <= 0:
        return None
    return base / fdv


def token_mc_stall(history) -> dict:
    """Token/MC tidak naik lagi (≈3 jam) sementara harga turun ≥ 5%."""
    key = "tmc_stall"
    rows = [r for r in (history or []) if _token_mc(r) is not None and _f(r.get("price"))]
    if len(rows) < TMC_WINDOW:
        return _item(key, available=False,
                     reason=f"riwayat token/MC belum cukup ({len(rows)} dari {TMC_WINDOW} snapshot)")
    then, now = rows[-TMC_WINDOW], rows[-1]
    tmc_then, tmc_now = _token_mc(then), _token_mc(now)
    change_pp = (tmc_now - tmc_then) * 100.0
    price_chg = _f(now["price"]) / _f(then["price"]) - 1.0
    prior_pp = None
    if len(rows) >= TMC_PRIOR_OFFSET:
        prior = rows[-TMC_PRIOR_OFFSET]
        prior_pp = (tmc_then - _token_mc(prior)) * 100.0
    active = change_pp <= TMC_FLAT_PP and price_chg <= TMC_PRICE_DOWN
    if active:
        reason = ""
    elif change_pp > TMC_FLAT_PP:
        reason = f"belum: token/MC masih naik {_pp(change_pp)[1:]}"
    else:
        reason = f"belum: harga {_pct(price_chg)} (belum turun ≥ 5%)"
    lines = [
        f"Jendela: {_wib(then['ts'])} → {_wib(now['ts'])} ({TMC_WINDOW - 1} jam)",
        f"Token/MC: {tmc_then * 100:.2f}% → {tmc_now * 100:.2f}% ({_pp(change_pp)})",
        f"Harga: {_price(then['price'])} → {_price(now['price'])} ({_pct(price_chg)})",
    ]
    if prior_pp is not None:
        lines.append(f"Sebelum jendela (≈6 jam sampai 3 jam lalu): token/MC berubah "
                     f"{_pp(prior_pp)}")
    data = {"tmc_then": tmc_then, "tmc_now": tmc_now, "change_pp": change_pp,
            "price_chg": price_chg, "prior_pp": prior_pp}
    return _item(key, available=True, active=active, reason=reason,
                 lines=lines, data=data)


def _quote_usd(row):
    liq, base = _f(row.get("liq_usd")), _f(row.get("pool_base_usd"))
    if liq is None or base is None or liq < 0 or base < 0:
        return None
    return max(liq - base, 0.0)


def pool_quote_hold(history) -> dict:
    """Sisi quote pool tidak turun >5% (≈6 jam) sementara harga turun ≥10%."""
    key = "pool_hold"
    rows = [r for r in (history or []) if _quote_usd(r) is not None and _f(r.get("price"))]
    if len(rows) < 3:
        return _item(key, available=False,
                     reason=f"riwayat likuiditas belum cukup ({len(rows)} snapshot)")
    window = rows[-POOL_WINDOW:]
    start, now = window[0], window[-1]
    q_start, q_now = _quote_usd(start), _quote_usd(now)
    if not q_start:
        return _item(key, available=False, reason="sisi quote awal nol atau tidak ada")
    quote_chg = q_now / q_start - 1.0
    price_chg = _f(now["price"]) / _f(start["price"]) - 1.0
    active = quote_chg >= POOL_HOLD_MIN and price_chg <= POOL_PRICE_DOWN
    if active:
        reason = ""
    elif price_chg > POOL_PRICE_DOWN:
        reason = f"belum: harga {_pct(price_chg)} (belum turun ≥ 10%)"
    else:
        reason = f"belum: sisi quote turun {_pct(quote_chg)} (lebih dari 5%)"
    lines = [
        f"Jendela: {_wib(start['ts'])} → {_wib(now['ts'])} ({len(window) - 1} jam)",
        f"Sisi quote (proksi USD): {_usd(q_start)} → {_usd(q_now)} ({_pct(quote_chg)})",
        f"Harga: {_price(start['price'])} → {_price(now['price'])} ({_pct(price_chg)})",
    ]
    data = {"quote_start": q_start, "quote_now": q_now, "quote_chg": quote_chg,
            "price_chg": price_chg, "hours": len(window) - 1}
    return _item(key, available=True, active=active, reason=reason,
                 lines=lines, data=data)


def shakeout_hold(shakeout, price, latched_at=None) -> dict:
    """Harga masih di atas low shakeout dan tidak pernah dilanggar."""
    key = "shakeout_hold"
    shakeout = shakeout or {}
    if not shakeout.get("passed"):
        return _item(key, available=False, reason="belum ada shakeout yang terdeteksi/dilatch")
    if shakeout.get("breached"):
        breach = shakeout.get("breach") or {}
        lines = [f"Low shakeout {_price(breach.get('base_low'))} sudah dilanggar "
                 f"(low {_price(breach.get('low'))})."]
        return _item(key, available=True, active=False,
                     reason="belum: low shakeout sudah dilanggar", lines=lines,
                     data={"breached": True})
    low = _f(shakeout.get("shakeout_low"))
    now = _f(price)
    if low is None or low <= 0:
        return _item(key, available=False,
                     reason=("low shakeout belum tersimpan; tunggu scan berikutnya"
                             if latched_at is not None else "low shakeout tidak tersedia"))
    if now is None or now <= 0:
        return _item(key, available=False, reason="harga sekarang tidak tersedia")
    vs_low = now / low - 1.0
    active = now >= low
    reason = "" if active else f"belum: harga {_pct(vs_low)} di bawah low shakeout"
    lines = [f"Low shakeout: {_price(low)} · harga sekarang: {_price(now)} "
             f"({_pct(vs_low)} dari low)"]
    data = {"low": low, "price": now, "vs_low": vs_low, "breached": False}
    return _item(key, available=True, active=active, reason=reason,
                 lines=lines, data=data)


def bottom_signals(*, result, metrics, history, latched_at=None) -> dict:
    """Empat indikator info untuk satu mint. Tidak memengaruhi vonis apa pun."""
    result = result or {}
    metrics = metrics or {}
    shakeout = next((c for c in (result.get("checks") or [])
                     if c.get("key") == "shakeout"), None)
    items = [
        cvd_divergence(result.get("delta")),
        token_mc_stall(history),
        pool_quote_hold(history),
        shakeout_hold(shakeout, metrics.get("price_usd"), latched_at),
    ]
    available = sum(1 for item in items if item["available"])
    active = [item for item in items if item["active"]]
    if available == 0:
        summary = "—"
    else:
        summary = f"{len(active)}/{available}"
        if active:
            summary += " · " + " · ".join(item["short"] for item in active)
    return {"items": items, "available": available, "active": len(active),
            "total": len(items), "summary": summary}
