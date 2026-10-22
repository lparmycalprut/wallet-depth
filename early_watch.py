# -*- coding: utf-8 -*-
"""Early watcher — deteksi awal aktivitas arbitrase lintas-pasar (permintaan user 2026-10-22).

Standar (dari pengamatan COCK 1 Okt 2026, 22:40–22:45 WIB):

* **Putaran (round trip)**: satu wallet, satu tx, dua kaki — beli di satu pasar
  (quote SOL atau quote lain) dan jual di pasar lain. Sisi jual harus lebih
  mahal daripada sisi beli dengan selisih ≥ ``ROUND_TRIP_MIN_SPREAD``.
* **Aktif**: dalam jendela ``WINDOW_SEC`` detik terdapat ≥ ``ACTIVE_MIN_TRADES``
  putaran dari ≥ ``ACTIVE_MIN_WALLETS`` wallet berbeda.
* **Awal**: aktif setelah ``QUIET_SEC`` detik tanpa aktivitas. Alert hanya pada
  transisi ini, bukan pada setiap poll; ``COOLDOWN_SEC`` mencegah alert ulang.

Dua batas tambahan (bukan bagian standar awal, dicantumkan agar bisa ditinjau):
``ROUND_TRIP_MAX_SPREAD`` membuang selisih harga >50% yang ternyata artefak dari
trade dust, dan ``LEG_MIN_USD`` membuang kaki di bawah $0,10.

Modul ini murni logika. Pengambilan data GMGN ada di :func:`fetch_window`, dan
pengiriman Telegram ada di :func:`run_poll` lewat parameter ``sender``.
Semua mint di watchlist dipantau; tidak ada mekanisme mute atau sembunyi.
Hasil tidak mempengaruhi verdict, skor, ``eligible``, atau filter Sweep.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "early_watch_watchlist.json")
STATE_PATH = os.path.join(BASE_DIR, "early_watch_state.json")

ROUND_TRIP_MIN_SPREAD = 0.02
ROUND_TRIP_MAX_SPREAD = 0.50
LEG_MIN_USD = 0.10
WINDOW_SEC = 60
ACTIVE_MIN_TRADES = 5
ACTIVE_MIN_WALLETS = 3
QUIET_SEC = 600
COOLDOWN_SEC = 1800
LOOKBACK_SEC = 180
POLL_INTERVAL_SEC = 120
# Kriteria dump sebelum aktif (permintaan user 2026-10-22). Angka ini usulan dari
# COCK 22:42:32 WIB: satu jual $1,43K (≈6,6 juta token) dalam satu order.
DUMP_MIN_USD = 1000.0
DUMP_LOOKBACK_SEC = 300      # dump harus ada dalam 5 menit sebelum awal aktivitas
DUMP_KEEP_SEC = 900          # dump disimpan 15 menit di state antar poll
DUMP_KEEP_MAX = 50
MAX_PAGES = 7
PAGE_LIMIT = 100
LOG_KEEP = 400


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Watchlist & state
# ---------------------------------------------------------------------------

def load_watchlist(path: str = WATCHLIST_PATH) -> list:
    """Daftar mint early watcher. Semua mint dikembalikan tanpa penyaringan."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    raw = data.get("mints", []) if isinstance(data, dict) else data
    out, seen = [], set()
    for item in raw or []:
        mint = str(item or "").strip()
        if mint and mint not in seen:
            seen.add(mint)
            out.append(mint)
    return out


def empty_state(now: int = 0) -> dict:
    return {"version": 1, "updated": int(now), "mints": {}, "log": []}


def load_state(path: str = STATE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    data.setdefault("mints", {})
    data.setdefault("log", [])
    return data


def save_state(state: dict, path: str = STATE_PATH) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Deteksi
# ---------------------------------------------------------------------------

def round_trips(trades) -> list:
    """Kembalikan putaran dari daftar trade GMGN mentah (satu mint).

    Satu entri per pasangan (tx, wallet). Quote harus berbeda antara kaki beli
    dan kaki jual. Selisih dihitung dari harga jual terhadap harga beli.
    """
    groups = defaultdict(list)
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        event = str(trade.get("event") or "").lower()
        if event not in ("buy", "sell"):
            continue
        tx = trade.get("tx_hash")
        maker = trade.get("maker")
        quote = trade.get("quote_address")
        price = _f(trade.get("price_usd"))
        usd = _f(trade.get("amount_usd"))
        ts = int(_f(trade.get("timestamp")))
        if not (tx and maker and quote) or price <= 0 or usd < LEG_MIN_USD or ts <= 0:
            continue
        groups[(tx, maker)].append((event, quote, price, usd, ts))

    out = []
    for (tx, maker), legs in groups.items():
        best = None
        for s_event, s_quote, s_price, s_usd, s_ts in legs:
            if s_event != "sell":
                continue
            for b_event, b_quote, b_price, b_usd, b_ts in legs:
                if b_event != "buy" or b_quote == s_quote:
                    continue
                spread = s_price / b_price - 1.0
                if best is None or spread > best["spread"]:
                    best = {"spread": spread, "usd": min(s_usd, b_usd),
                            "ts": max(s_ts, b_ts)}
        if best and ROUND_TRIP_MIN_SPREAD <= best["spread"] <= ROUND_TRIP_MAX_SPREAD:
            out.append({"tx": tx, "maker": maker, "ts": best["ts"],
                        "spread": best["spread"], "usd": best["usd"]})
    out.sort(key=lambda r: r["ts"])
    return out


def window_stats(rts: list, window: int = WINDOW_SEC) -> list:
    """Untuk setiap putaran sebagai ujung jendela: jumlah putaran & wallet.

    Mengembalikan daftar ``(end_ts, count, wallets, max_spread)``.
    """
    stats = []
    for end in rts:
        t = end["ts"]
        inside = [r for r in rts if t - window < r["ts"] <= t]
        stats.append((t, len(inside), len({r["maker"] for r in inside}),
                      max(r["spread"] for r in inside)))
    return stats


def active_ends(stats: list) -> list:
    """Ujung jendela yang memenuhi standar aktif (sorted, unik)."""
    ends = {end for end, count, wallets, _ in stats
            if count >= ACTIVE_MIN_TRADES and wallets >= ACTIVE_MIN_WALLETS}
    return sorted(ends)


def _peak(stats: list) -> dict:
    if not stats:
        return {"rt_peak": 0, "wallets_peak": 0, "max_spread": 0.0}
    best = max(stats, key=lambda s: (s[1], s[2]))
    return {"rt_peak": best[1], "wallets_peak": best[2],
            "max_spread": max(s[3] for s in stats)}


def big_sells(trades, rt_keys, min_usd: float = DUMP_MIN_USD) -> list:
    """Jual tunggal ≥ ``min_usd``. Kaki putaran bot (pasangan tx+maker di ``rt_keys``) dikecualikan."""
    out = []
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        if str(trade.get("event") or "").lower() != "sell":
            continue
        tx, maker = trade.get("tx_hash"), trade.get("maker")
        if not tx or not maker or (tx, maker) in rt_keys:
            continue
        usd = _f(trade.get("amount_usd"))
        ts = int(_f(trade.get("timestamp")))
        if usd < min_usd or ts <= 0:
            continue
        out.append({"tx": tx, "maker": maker, "ts": ts, "usd": usd,
                    "base": _f(trade.get("base_amount"))})
    return out


def _merge_dumps(old, new, now: int) -> list:
    seen = {}
    for dump in list(old or []) + list(new or []):
        if now - int(dump["ts"]) > DUMP_KEEP_SEC:
            continue
        key = (dump["tx"], dump["maker"], int(dump["ts"]), round(float(dump["usd"]), 2))
        seen[key] = dump
    out = sorted(seen.values(), key=lambda d: d["ts"])
    return out[-DUMP_KEEP_MAX:]


def find_dump(dumps, start: int):
    """Jual terbesar yang terjadi dalam jendela sebelum ``start``, atau None."""
    lo = int(start) - WINDOW_SEC - DUMP_LOOKBACK_SEC
    cands = [d for d in (dumps or []) if lo <= int(d["ts"]) <= int(start)]
    return max(cands, key=lambda d: d["usd"]) if cands else None


def evaluate_mint(rec: dict, trades, now: int, *, partial: bool) -> tuple:
    """Perbarui catatan satu mint dari trade terbaru.

    Alert hanya bila awal aktivitas didahului dump (``find_dump``). Aktivitas
    tanpa dump tetap dicatat sebagai ``AKTIF (tanpa dump)`` tetapi tidak dikirim.
    Mengembalikan ``(rec_baru, alert_dict_atau_None, status)``; ``rec`` tidak diubah langsung.
    """
    rec = dict(rec or {})
    trades = trades or []
    rts = round_trips(trades)
    stats = window_stats(rts)
    peak = _peak(stats)
    ends = active_ends(stats)
    rt_keys = {(r["tx"], r["maker"]) for r in rts}
    rec["dumps"] = _merge_dumps(rec.get("dumps"), big_sells(trades, rt_keys), now)

    last_active = rec.get("last_active_ts")
    prev = last_active
    starts = []
    for end in ends:
        if last_active is not None and end <= last_active:
            continue
        if prev is None or end - prev > QUIET_SEC:
            starts.append(end)
        prev = end
    if ends and (last_active is None or ends[-1] > last_active):
        rec["last_active_ts"] = ends[-1]
        last_active = ends[-1]

    prices = [(t.get("timestamp"), _f(t.get("price_usd"))) for t in trades
              if isinstance(t, dict) and _f(t.get("price_usd")) > 0]
    if prices:
        rec["last_price"] = max(prices, key=lambda p: _f(p[0]))[1]

    alert = None
    for start in starts:
        dump = find_dump(rec["dumps"], start)
        rec["burst_ok"] = dump is not None
        if dump is None or alert is not None:
            continue
        if now < int(rec.get("cooldown_until") or 0):
            continue
        window_at_start = next(s for s in stats if s[0] == start)
        alert = {"t": now, "start_ts": start, "count": window_at_start[1],
                 "wallets": window_at_start[2], "max_spread": window_at_start[3],
                 "partial": bool(partial), "price": rec.get("last_price"),
                 "dump": dump}
        rec["cooldown_until"] = now + COOLDOWN_SEC
        rec["alerts"] = int(rec.get("alerts") or 0) + 1

    if alert:
        status = "AWAL AKTIF"
    elif last_active is not None and now - last_active <= QUIET_SEC:
        status = "AKTIF" if rec.get("burst_ok") else "AKTIF (tanpa dump)"
    else:
        status = "TENANG"

    rec.update({"status": status, "last_poll": int(now), "trades": len(trades),
                "partial": bool(partial), "error": "", **peak})
    return rec, alert, status


# ---------------------------------------------------------------------------
# Pengambilan data GMGN (hanya di runner, bukan saat tes)
# ---------------------------------------------------------------------------

def fetch_window(mint: str, from_ts: int, to_ts: int, *, max_pages: int = MAX_PAGES):
    """Ambil trade GMGN untuk jendela waktu. Mengembalikan ``(trades, partial)``.

    Tidak memakai filter ``MIN_SOL`` dari :mod:`cvd`, karena pola ini justru
    dibentuk trade kecil. ``partial=True`` bila batas halaman tercapai dan
    masih ada halaman berikutnya. Gagal ambil data akan melempar exception.
    """
    import cvd  # impor lokal: tes tidak membutuhkan curl_cffi

    out, cursor = [], None
    for _ in range(max_pages):
        trades, nxt = cvd._fetch_gmgn_page(mint, cursor=cursor, limit=PAGE_LIMIT,
                                           from_ts=from_ts, to_ts=to_ts)
        if trades is None:
            raise RuntimeError(str(cvd.get_gmgn_fetch_status())[:160] or "GMGN gagal")
        out.extend(trades)
        if not nxt or not trades:
            return out, False
        cursor = nxt
    return out, True


def format_alert(mint: str, alert: dict) -> str:
    ts = time.strftime("%H:%M:%S", time.gmtime(int(alert["start_ts"]) + 7 * 3600))
    price = alert.get("price")
    price_txt = f"${price:.8f}" if price else "—"
    lines = [
        "⚡ EARLY SWEEP — awal aktivitas arbitrase",
        f"Mint: {mint}",
        f"Waktu deteksi (WIB): {ts}",
        f"Dalam 60 detik: {alert['count']} putaran dari {alert['wallets']} wallet",
        f"Selisih maksimum putaran: {alert['max_spread'] * 100:.1f}%",
        f"Harga terakhir: {price_txt}",
        "Info saja. Tidak mengubah verdict Sweep.",
        f"https://gmgn.ai/sol/token/{mint}",
    ]
    dump = alert.get("dump")
    if dump:
        base = float(dump.get("base") or 0)
        tokens = f"{base / 1e6:.2f} juta" if base >= 1e6 else f"{base:,.0f}"
        d_ts = time.strftime("%H:%M:%S", time.gmtime(int(dump["ts"]) + 7 * 3600))
        lead = int(alert["start_ts"]) - int(dump["ts"])
        lines.insert(3, f"Jual besar sebelum aktif: ${dump['usd']:,.0f} (≈{tokens} token) "
                        f"pukul {d_ts} WIB, {lead} detik sebelum awal")
    if alert.get("partial"):
        lines.insert(3, "⚠ Data terpotong (batas halaman tercapai)")
    return "\n".join(lines)


def decision_fingerprint(state: dict) -> str:
    """Ringkasan field yang menentukan alert berikutnya.

    Runner hanya meng-commit state bila fingerprint ini berubah. Log dan
    ``last_poll`` sengaja tidak masuk, agar tidak membuat commit tiap poll.
    Bila ``last_active_ts`` atau ``cooldown_until`` berubah tanpa commit, job
    berikutnya bisa mengulang transisi yang sama dan mengirim alert ganda.
    """
    rows = {}
    for mint, rec in (state.get("mints") or {}).items():
        rows[mint] = [rec.get("status"), rec.get("last_active_ts"),
                      rec.get("cooldown_until"), rec.get("alerts"),
                      (rec.get("last_alert") or {}).get("t"),
                      rec.get("burst_ok"),
                      [[d["tx"], d["ts"]] for d in rec.get("dumps") or []]]
    return json.dumps(rows, sort_keys=True)


def run_poll(state: dict, mints: list, now: int, *, fetcher=None, sender=None) -> dict:
    """Satu poll untuk semua mint. Mengubah ``state`` di tempat dan mengembalikannya.

    ``fetcher(mint, from_ts, to_ts) -> (trades, partial)`` dan
    ``sender(text) -> (ok, err)`` bisa diganti saat tes.
    Kegagalan ambil data dicatat sebagai status GAGAL dan tidak mengubah state
    aktivitas, sehingga tidak bisa memicu atau membatalkan alert.
    """
    fetcher = fetcher or fetch_window
    now = int(now)
    state.setdefault("mints", {})
    state.setdefault("log", [])
    alerts = []
    for mint in mints:
        prev = dict(state["mints"].get(mint) or {})
        try:
            trades, partial = fetcher(mint, now - LOOKBACK_SEC, now)
        except Exception as exc:  # noqa: BLE001 — dicatat, bukan disembunyikan
            rec = dict(prev)
            rec.update({"status": "GAGAL", "last_poll": now,
                        "error": str(exc)[:200]})
            state["mints"][mint] = rec
            state["log"].append({"t": now, "mint": mint, "status": "GAGAL",
                                 "trades": 0, "rt": 0, "wallets": 0,
                                 "partial": False, "error": rec["error"]})
            continue

        rec, alert, status = evaluate_mint(prev, trades, now, partial=partial)
        state["mints"][mint] = rec
        state["log"].append({"t": now, "mint": mint, "status": status,
                             "trades": rec["trades"], "rt": rec["rt_peak"],
                             "wallets": rec["wallets_peak"],
                             "partial": bool(partial), "error": ""})
        if alert:
            alerts.append((mint, alert))

    state["log"] = state["log"][-LOG_KEEP:]
    state["updated"] = now

    for mint, alert in alerts:
        text = format_alert(mint, alert)
        if sender is not None:
            ok, err = sender(text)
            state["mints"][mint]["last_alert"] = {"t": now, "sent": bool(ok),
                                                  "error": "" if ok else str(err)[:160]}
        else:
            state["mints"][mint]["last_alert"] = {"t": now, "sent": False,
                                                  "error": "tanpa pengirim"}
    return state
