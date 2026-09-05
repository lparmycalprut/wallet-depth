# -*- coding: utf-8 -*-
"""Detail baris watchlist: perubahan dust **sejak masuk watchlist** + sinkronisasi.

Dua hal yang dikerjakan modul ini (murni kalkulasi, tanpa Streamlit/jaringan):

1. **Delta sejak ditambahkan** — watchlist menyimpan ``added`` (tanggal,
   ``watchlist.add_to_watchlist``) dan store holder menyimpan titik per scan
   (``holder_history``). Modul ini mencari titik pertama **sejak tanggal
   masuk** sampai titik **scan terakhir**, lalu menghitung perubahan dust
   ``% marketcap``:
   - perubahan **relatif** (%) — dipakai untuk warna,
   - perubahan **poin persentase** (pp) — angka absolut yang dipakai rule alert,
   - perubahan **jumlah wallet dust** (%).

2. **Sinkronisasi watchlist ↔ scan terakhir** — baris watchlist membaca
   snapshot ``holder_status.json`` (cron), sedangkan grafik membaca
   ``holder_history.json`` yang sudah memuat titik scan manual/scan lebih
   baru. Akibatnya satu token bisa menampilkan dua angka berbeda (kasus yang
   sama didokumentasikan di ``KEGIATAN.md`` untuk kartu Holder Analytic).
   :func:`resolve_view` memilih sumber **terbaru** untuk satu baris dan
   :func:`sync_summary` merangkum berapa baris yang ikut sumber mana, sehingga
   caption "scan terakhir" tidak lagi mengklaim waktu yang tidak cocok dengan
   angka di baris.

3. **Urutan baris watchlist** (permintaan user 2026-09-05) — default
   ``SORT_DROP``: token dengan **minus dust terbesar** (``pct_change``
   ``Sejak masuk`` paling negatif, mis. GPRO −60%) di baris paling atas;
   lihat :func:`row_sort_key`.

Ambang warna (permintaan user 2026-09-04):

- ``% MC`` yang dipegang dust **turun ≥ 50%** → hijau (dust menipis),
- ``% MC`` yang dipegang dust **naik ≥ 100%** → merah (dust menebal 2×),
- di antaranya → netral (abu-abu).

⚠️ Angka ini heuristik pemantauan, bukan prediksi arah harga — disclaimer yang
sama dipakai README/AGENTS untuk seluruh rule dust.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from holder_history import (MIN_USABLE_WALLETS, holders_usable, point_usable,
                            point_wallets, usable_points)

# --- ambang warna (relatif terhadap nilai dust % MC saat masuk watchlist) ------
MCAP_DROP_TONE_PCT = 50.0     # turun >= 50% -> hijau
MCAP_RISE_TONE_PCT = 100.0    # naik >= 100% -> merah

# Cron holder watchlist **LP** jalan tiap ±15 menit sejak 2026-09-05: data
# lebih tua dari ini = basi.
STALE_AFTER_SEC = 2 * 3600
# Watchlist **biasa** sengaja di-scan tiap ±4 jam (slot 4 jam + catch-up),
# jadi ambang basinya mengikuti kadens itu, bukan 2 jam.
STALE_REGULAR_AFTER_SEC = 4 * 3600 + 30 * 60

# Zona tampil UI (WIB). ``watchlist.add_to_watchlist`` menulis ``added`` dengan
# ``datetime.now()``; tanggal itu dibaca sebagai awal hari WIB supaya window
# "sejak masuk" tidak bergeser 7 jam terhadap jam yang ditampilkan UI.
WIB_OFFSET_HOURS = 7

# Toleransi selisih snapshot vs titik history sebelum dianggap "tidak sinkron".
DRIFT_TOLERANCE_PP = 0.01

TONE_DROP = "drop_big"      # turun >= MCAP_DROP_TONE_PCT
TONE_RISE = "rise_big"      # naik >= MCAP_RISE_TONE_PCT
TONE_NEUTRAL = "netral"
TONE_UNKNOWN = "unknown"

TONE_COLORS = {
    TONE_DROP: "#15803d",   # hijau — dust % MC menipis
    TONE_RISE: "#b91c1c",   # merah — dust % MC menebal >= 2x
    TONE_NEUTRAL: "#334155",
    TONE_UNKNOWN: "#94a3b8",
}
TONE_ARROWS = {TONE_DROP: "▼", TONE_RISE: "▲", TONE_NEUTRAL: "→",
               TONE_UNKNOWN: "—"}
TONE_LABELS = {
    TONE_DROP: f"dust % MC turun ≥ {MCAP_DROP_TONE_PCT:g}% sejak masuk",
    TONE_RISE: f"dust % MC naik ≥ {MCAP_RISE_TONE_PCT:g}% sejak masuk",
    TONE_NEUTRAL: "perubahan dust % MC masih di dalam ambang warna",
    TONE_UNKNOWN: "belum ada pembanding sejak masuk watchlist",
}

SOURCE_SNAPSHOT = "snapshot"
SOURCE_HISTORY = "history"

# --- Urutan baris watchlist holder (permintaan user 2026-09-05) ---------------
# Default: token dengan "minus dust holder" terbesar di atas — token yang
# dust % MC-nya turun paling banyak sejak masuk watchlist (mis. GPRO -60%)
# berada paling atas; token tanpa pembanding / dust naik di bawah.
SORT_DROP = "drop"          # dust % MC turun terbesar sejak masuk (minus → atas)
SORT_PCT = "pct"            # dust % MC saat ini tertinggi di atas (risiko)
SORT_NAME = "name"          # alfabetis A–Z (urutan lama)
SORT_DEFAULT = SORT_DROP
SORT_OPTIONS = (
    (SORT_DROP, "🔻 Dust turun sejak masuk — minus terbesar di atas"),
    (SORT_PCT, "🔥 Dust % MC tertinggi di atas"),
    (SORT_NAME, "🔤 Nama A–Z"),
)
SORT_LABELS = {key: label for key, label in SORT_OPTIONS}


def row_sort_key(mode: str, *, pct_change=None, dust_pct=None,
                 symbol: str = "") -> tuple:
    """Kunci urut satu baris watchlist (bandingkan hasilnya antar baris).

    - ``drop`` (default): ``pct_change`` (perubahan relatif dust % MC sejak
      masuk) paling kecil/negatif di urutan pertama; baris tanpa nilai
      pembanding ditaruh di bawah (tidak bisa diklaim "minus terbesar").
    - ``pct``: ``dust_pct`` saat ini tertinggi di atas.
    - ``name``: alfabetis ``symbol``.

    Tuple selalu berformat ``(bawah?, nilai, nama)`` sehingga aman
    dibandingkan dan deterministik (nama jadi tie-breaker).
    """
    name = str(symbol or "").upper()
    if mode == SORT_NAME:
        return (0, 0.0, name)
    if mode == SORT_PCT:
        value = _float(dust_pct, None)
        if value is None:
            return (1, 0.0, name)
        return (0, -value, name)
    # SORT_DROP — default: minus terbesar dulu.
    value = _float(pct_change, None)
    if value is None:
        return (1, 0.0, name)
    return (0, value, name)


# ---------------------------------------------------------------------------
# Helper numerik / waktu
# ---------------------------------------------------------------------------
def _float(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return num if num == num else default


def _int(value, default=0):
    num = _float(value, None)
    return default if num is None else int(num)


def pct_change(before, after) -> float | None:
    """Perubahan **relatif** (%) dari ``before`` ke ``after``.

    ``None`` bila salah satu sisi tidak ada atau nilai awal 0 (pembagian tidak
    bermakna — kenaikan dari 0% tidak bisa dinyatakan dalam persen).
    """
    start = _float(before, None)
    end = _float(after, None)
    if start is None or end is None or start == 0:
        return None
    return round((end - start) / abs(start) * 100.0, 1)


def pp_change(before, after) -> float | None:
    """Perubahan **poin persentase** (satuan yang dipakai rule alert dust)."""
    start = _float(before, None)
    end = _float(after, None)
    if start is None or end is None:
        return None
    return round(end - start, 4)


def format_wib(ts, *, with_label: bool = True) -> str:
    """Timestamp → ``04 Sep 12:00 WIB`` (pola ``_wib`` di app.py)."""
    stamp = _int(ts, 0)
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) \
        + timedelta(hours=WIB_OFFSET_HOURS)
    text = when.strftime("%d %b %H:%M")
    return f"{text} WIB" if with_label else text


def format_age(seconds) -> str:
    """Umur data jadi teks ringkas (``12 mnt``, ``3 jam``, ``2 hari``)."""
    total = _int(seconds, -1)
    if total < 0:
        return "—"
    if total < 60:
        return f"{total} dtk"
    if total < 3600:
        return f"{total // 60} mnt"
    if total < 86_400:
        return f"{total // 3600} jam"
    return f"{total // 86_400} hari"


def parse_added_ts(meta, *, tz_offset_hours: int = WIB_OFFSET_HOURS) -> int | None:
    """Timestamp awal hari dari ``added`` di entri watchlist.

    Format yang diterima: ``YYYY-MM-DD`` (yang ditulis
    ``watchlist.add_to_watchlist``), ISO datetime, atau angka Unix. ``None``
    bila tidak ada/tidak bisa dibaca — pemanggil lalu jatuh ke titik history
    paling awal dan menandainya.
    """
    raw = (meta or {}).get("added") if isinstance(meta, dict) else None
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        stamp = int(raw)
        return stamp if stamp > 0 else None
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("/", "-")
    digits = normalized.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        normalized = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"

    moment = None
    for parse in (lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
                  lambda value: datetime.strptime(value, "%Y-%m-%d"),
                  lambda value: datetime.strptime(value, "%d-%m-%Y")):
        try:
            moment = parse(normalized)
            break
        except (TypeError, ValueError):
            continue
    if moment is None:
        return None
    if moment.tzinfo is not None:
        # Sudah membawa zona waktu (ISO): hormati, jangan geser ke WIB.
        return int(moment.timestamp())
    offset = timezone(timedelta(hours=int(tz_offset_hours)))
    return int(moment.replace(tzinfo=offset).timestamp())


# ---------------------------------------------------------------------------
# 1) Sinkronisasi: satu angka per baris, dari sumber terbaru
# ---------------------------------------------------------------------------
def _degraded_note(ts, wallets, source: str, *, used_ts) -> str:
    """Kalimat pendek untuk scan yang datanya tidak lengkap.

    Contoh hasil: ``"scan 06 Sep 03:00 WIB · hanya 19 wallet terambil ·
    snapshot cron — angka memakai scan 05 Sep 23:00 WIB"``.
    """
    bits = [f"scan {format_wib(ts)}"]
    bits.append(f"hanya {int(wallets or 0):,} wallet terambil")
    bits.append("snapshot cron" if source == "snapshot" else "titik history")
    text = " · ".join(bits)
    if used_ts:
        text += f" — angka memakai scan {format_wib(used_ts)}"
    return text


def resolve_view(token: dict | None, points, *, now=None,
                 stale_after: int = STALE_AFTER_SEC) -> dict:
    """Pilih nilai dust **terbaru yang datanya layak** untuk satu baris.

    ``token`` = ``holder_status["tokens"][mint]`` (sudah lewat
    ``apply_manual_scan`` di UI). ``points`` = titik gabungan
    ``holder_history`` + salinan ringkas snapshot (``_points_for`` di app.py).

    Return ``{dust_pct, dust_count, ts, source, age_sec, stale, drift,
    snapshot_pct, history_pct, degraded, ...}``:

    - ``source`` = ``"snapshot"`` bila snapshot sama baru/lebih baru, atau
      ``"history"`` bila titik history lebih baru (scan manual / cron yang
      publish snapshot-nya gagal),
    - ``drift`` = True bila kedua sumber punya angka berbeda melebihi
      ``DRIFT_TOLERANCE_PP`` — persis kondisi "watchlist dan scan terakhir
      kurang sinkron" yang dilaporkan user,
    - ``stale`` = data lebih tua dari ``stale_after`` (kirim
      ``STALE_REGULAR_AFTER_SEC`` untuk baris watchlist biasa yang cadens
      cron-nya ±4 jam).

    **Scan yang datanya tidak lengkap dilewati** (perbaikan 2026-09-06).
    Provider holder bisa mengembalikan daftar pendek tanpa menandai
    ``truncated`` (kasus nyata: Helius mati → fallback GMGN mengembalikan
    20 holder). Wallet dust ada di ekor daftar holder, jadi sampel pendek
    selalu menghasilkan ``dust 0`` / ``0,00% MC`` — dan watchlist lalu
    mengklaim "−100% sejak masuk" untuk puluhan token padahal tidak ada
    yang menjual. Snapshot/titik seperti itu (``holder_history.
    holders_usable`` / ``point_usable``) tidak dipakai sebagai angka:
    baris memakai scan layak terbaru, ``degraded`` = True, dan
    ``degraded_note`` menjelaskan kenapa angkanya lebih tua dari run
    terakhir.
    """
    token = token if isinstance(token, dict) else {}
    holders = token.get("holders") if isinstance(token.get("holders"), dict) \
        else {}
    rows = [row for row in (points or [])
            if isinstance(row, dict) and _int(row.get("ts")) > 0]
    good_rows = [row for row in rows if point_usable(row)]
    last_point = good_rows[-1] if good_rows else {}

    raw_snapshot_pct = _float(holders.get("dust_pct_mc"), None)
    snapshot_pct = raw_snapshot_pct
    snapshot_count = holders.get("dust_count")
    raw_snapshot_ts = _int(token.get("analyzed_at"), 0)
    snapshot_ts = raw_snapshot_ts
    snapshot_ok = bool(holders) and holders_usable(holders)
    history_pct = _float(last_point.get("dust_pct_mc"), None)
    history_count = last_point.get("dust_count")
    history_ts = _int(last_point.get("ts"), 0)

    if not snapshot_ok:
        # Snapshot tidak layak dipakai (fetch gagal / sampel pendek):
        # angkanya tidak boleh jadi nilai baris sama sekali — baris jatuh ke
        # titik history layak terbaru, atau "—" bila tidak ada.
        snapshot_pct = None
        snapshot_count = None
        snapshot_ts = 0
    use_history = (history_ts > snapshot_ts and history_pct is not None)
    drift = (snapshot_ok and raw_snapshot_pct is not None
             and history_pct is not None
             and abs(raw_snapshot_pct - history_pct) > DRIFT_TOLERANCE_PP
             and raw_snapshot_ts != history_ts)

    if use_history:
        dust_pct = history_pct if history_pct is not None else snapshot_pct
        dust_count = (history_count if history_count is not None
                      else snapshot_count)
    else:
        dust_pct = snapshot_pct if snapshot_pct is not None else history_pct
        dust_count = (snapshot_count if snapshot_count is not None
                      else history_count)

    anchor = _int(now, None)
    ts = history_ts if use_history else (snapshot_ts or history_ts)
    age = (anchor - ts) if (anchor and ts) else None
    limit = int(stale_after) if int(stale_after or 0) > 0 else STALE_AFTER_SEC

    # --- Scan terbaru yang datanya dibuang (untuk catatan di UI) ----------
    rejected = []
    if holders and not snapshot_ok:
        rejected.append({"ts": raw_snapshot_ts,
                         "wallets": point_wallets(holders),
                         "source": "snapshot"})
    for row in rows:
        if not point_usable(row):
            rejected.append({"ts": _int(row.get("ts")),
                             "wallets": point_wallets(row),
                             "source": "history"})
    rejected = [item for item in rejected if item["ts"] > 0]
    rejected.sort(key=lambda item: item["ts"])
    newest = rejected[-1] if rejected else None
    degraded = bool(newest) and (not ts or newest["ts"] > ts)
    return {
        "dust_pct": dust_pct,
        "dust_count": _int(dust_count, None) if dust_count is not None else None,
        "ts": ts or None,
        "source": SOURCE_HISTORY if use_history else SOURCE_SNAPSHOT,
        "age_sec": age,
        "stale": bool(age is not None and age > limit),
        "drift": bool(drift),
        "snapshot_pct": raw_snapshot_pct,
        "snapshot_usable": snapshot_ok,
        "history_pct": history_pct,
        "snapshot_ts": raw_snapshot_ts or None,
        "history_ts": history_ts or None,
        "points": len(rows),
        "usable_points": len(good_rows),
        "skipped_scans": len(rejected),
        "degraded": degraded,
        "degraded_ts": newest["ts"] if degraded else None,
        "degraded_wallets": newest["wallets"] if degraded else None,
        "degraded_note": (_degraded_note(newest["ts"], newest["wallets"],
                                         newest["source"], used_ts=ts)
                          if degraded else ""),
    }


def previous_pct(sampled, view) -> float | None:
    """Nilai dust % MC **sebelum** angka yang ditampilkan satu baris.

    ``sampled`` = titik yang sudah di-``resample_4h`` (dipakai sparkline),
    ``view`` = hasil :func:`resolve_view`. Pembandingnya adalah bucket 4 jam
    terakhir yang **lebih tua** dari nilai baris — bukan ``sampled[-2]`` —
    supaya badge "naik/turun" tetap membandingkan dua titik yang berurutan
    ketika angka baris datang dari snapshot yang lebih baru daripada titik
    terakhir di store (kasus sinkronisasi di atas).
    """
    rows = [row for row in (sampled or [])
            if isinstance(row, dict) and _int(row.get("ts")) > 0]
    ts = _int((view or {}).get("ts"), 0)
    if not rows:
        return None
    if not ts:
        return _float(rows[-2].get("dust_pct_mc"), None) if len(rows) >= 2 \
            else None
    earlier = [row for row in rows if _int(row.get("ts")) < ts]
    if earlier:
        return _float(earlier[-1].get("dust_pct_mc"), None)
    return None


# ---------------------------------------------------------------------------
# 2) Delta sejak masuk watchlist sampai scan terakhir
# ---------------------------------------------------------------------------
def anchor_point(meta, points, *, tz_offset_hours: int = WIB_OFFSET_HOURS) -> dict:
    """Titik pembanding "sejak masuk watchlist".

    Dipilih titik **pertama pada/​setelah** tanggal ``added``. Bila belum ada
    titik setelah tanggal itu (token baru masuk, cron belum jalan), dipakai
    titik paling awal yang tersedia dan ditandai ``fallback`` supaya UI bisa
    menyebut "titik pertama" alih-alih mengklaim "sejak masuk".

    Hanya titik yang datanya layak (:func:`holder_history.point_usable`)
    yang boleh jadi pembanding: titik dari scan yang cuma mengambil 20
    holder selalu berisi ``dust 0``, dan memakainya sebagai nilai awal
    membuat perubahan "sejak masuk" terbaca +∞/−100% tanpa ada transaksi.
    """
    rows = [row for row in usable_points(points)
            if _int(row.get("ts")) > 0]
    if not rows:
        return {}
    added_ts = parse_added_ts(meta, tz_offset_hours=tz_offset_hours)
    if added_ts is None:
        return {"point": rows[0], "added_ts": None, "fallback": "no_added_date"}
    after = [row for row in rows if _int(row.get("ts")) >= added_ts]
    if after:
        return {"point": after[0], "added_ts": added_ts, "fallback": ""}
    return {"point": rows[0], "added_ts": added_ts,
            "fallback": "belum ada titik sejak tanggal masuk"}


def dust_change_since_added(meta, points, view: dict | None = None, *,
                            now=None,
                            tz_offset_hours: int = WIB_OFFSET_HOURS) -> dict:
    """Perubahan dust (jumlah wallet + % MC) sejak masuk sampai scan terakhir.

    Return dict siap render: ``from_pct``/``to_pct`` (dust % MC),
    ``pp_change`` (poin persentase), ``pct_change`` (perubahan relatif %,
    dipakai warna), ``from_count``/``to_count``/``count_change_pct``,
    ``anchor_ts``/``last_ts``/``days``, ``tone``, ``cukup_data``, ``alasan``.
    """
    anchor = anchor_point(meta, points, tz_offset_hours=tz_offset_hours)
    resolved = view if isinstance(view, dict) and view else resolve_view(
        None, points, now=now)
    from_row = anchor.get("point") or {}
    from_pct = _float(from_row.get("dust_pct_mc"), None)
    from_count = _int(from_row.get("dust_count"), None) \
        if from_row.get("dust_count") is not None else None
    anchor_ts = _int(from_row.get("ts"), 0) or None

    # Ujung window = scan terakhir (sumber terbaru), bukan titik terakhir
    # mentah: snapshot bisa lebih baru dari titik terakhir di store.
    to_pct = resolved.get("dust_pct")
    to_count = resolved.get("dust_count")
    last_ts = resolved.get("ts")
    if to_pct is None and from_row:
        to_pct = from_pct
        to_count = from_count
        last_ts = anchor_ts

    result = {
        "cukup_data": False,
        "alasan": "",
        "from_pct": from_pct,
        "to_pct": to_pct,
        "pp_change": pp_change(from_pct, to_pct),
        "pct_change": pct_change(from_pct, to_pct),
        "from_count": from_count,
        "to_count": to_count,
        "count_change_pct": pct_change(from_count, to_count),
        "anchor_ts": anchor_ts,
        "anchor_added_ts": anchor.get("added_ts"),
        "anchor_fallback": anchor.get("fallback") or "",
        "last_ts": last_ts,
        "days": (round((last_ts - anchor_ts) / 86_400.0, 2)
                 if (last_ts and anchor_ts and last_ts >= anchor_ts) else None),
        "source": resolved.get("source") or "",
        "degraded": bool(resolved.get("degraded")),
        "degraded_note": str(resolved.get("degraded_note") or ""),
        "tone": TONE_UNKNOWN,
    }

    if not from_row:
        if [row for row in (points or []) if isinstance(row, dict)]:
            result["alasan"] = (
                "Semua titik scan token ini datanya tidak lengkap "
                f"(< {MIN_USABLE_WALLETS} wallet terambil) — belum ada "
                "pembanding yang bisa dipercaya sejak masuk watchlist.")
        else:
            result["alasan"] = ("Belum ada titik history untuk token ini — "
                                "cron holder belum pernah mencatat scan.")
        return result
    if from_pct is None or to_pct is None:
        result["alasan"] = "Nilai dust % MC belum tersedia di salah satu ujung window."
        return result
    if anchor_ts and last_ts and last_ts == anchor_ts:
        # Satu titik saja = belum ada pembanding, bukan "tidak berubah".
        result["alasan"] = ("Baru ada satu titik scan, jadi belum ada "
                            "pembanding sejak masuk watchlist.")
        return result

    result["cukup_data"] = True
    result["tone"] = tone_for_change(result["pct_change"])
    result["alasan"] = explain_change(result)
    return result


def tone_for_change(change_pct) -> str:
    """Kelas warna dari perubahan relatif dust % MC (ambang user)."""
    value = _float(change_pct, None)
    if value is None:
        return TONE_UNKNOWN
    if value <= -float(MCAP_DROP_TONE_PCT):
        return TONE_DROP
    if value >= float(MCAP_RISE_TONE_PCT):
        return TONE_RISE
    return TONE_NEUTRAL


def explain_change(change: dict) -> str:
    """Penjelasan singkat satu baris (dipakai tooltip/caption UI)."""
    change = change or {}
    if not change.get("cukup_data"):
        return str(change.get("alasan") or "Data belum cukup.")
    from_pct = _float(change.get("from_pct"), None)
    to_pct = _float(change.get("to_pct"), None)
    parts = [f"{from_pct:.2f}% → {to_pct:.2f}% MC"]
    relative = _float(change.get("pct_change"), None)
    if relative is None:
        parts.append("perubahan relatif tidak bisa dihitung (nilai awal 0%)")
    else:
        parts.append(f"{relative:+.1f}% relatif")
    pp = _float(change.get("pp_change"), None)
    if pp is not None:
        parts.append(f"{pp:+.2f} pp")
    count_pct = _float(change.get("count_change_pct"), None)
    if count_pct is not None:
        parts.append(f"wallet dust {count_pct:+.1f}%")
    days = _float(change.get("days"), None)
    if days is not None:
        parts.append(f"{days:.1f} hari")
    last_ts = _int(change.get("last_ts"), 0)
    if last_ts:
        parts.append(f"sampai snapshot {format_wib(last_ts)}")
    if change.get("anchor_fallback"):
        parts.append(f"pembanding: titik pertama ({change['anchor_fallback']})")
    note = str(change.get("degraded_note") or "")
    if note:
        parts.append(f"\u26a0\ufe0f {note}")
    return " · ".join(parts)


def change_html(change: dict, *, show_detail: bool = True) -> str:
    """HTML satu sel "sejak masuk" (warna mengikuti ambang user)."""
    change = change or {}
    tone = str(change.get("tone") or TONE_UNKNOWN)
    color = TONE_COLORS.get(tone, TONE_COLORS[TONE_UNKNOWN])
    if not change.get("cukup_data"):
        # Tanpa pembanding tetap dijelaskan **kenapa** (scan terakhir datanya
        # tidak lengkap vs cron belum pernah mencatat), supaya "belum ada
        # data" tidak dibaca sebagai "dust-nya nol".
        reason = str(change.get("alasan") or "")
        note = str(change.get("degraded_note") or "")
        title = " — ".join(bit for bit in (reason, note) if bit)
        label = ("belum ada data ⚠️" if change.get("degraded")
                 else "belum ada data")
        attr = f' title="{title.replace(chr(34), chr(39))}"' if title else ""
        return (f'<div class="watchlist-metric"{attr}><div '
                f'style="font-size:.8rem;color:{TONE_COLORS[TONE_UNKNOWN]};">'
                f"{label}</div></div>")
    relative = _float(change.get("pct_change"), None)
    head = ("—" if relative is None
            else f"{TONE_ARROWS.get(tone, '')} {relative:+.1f}%".strip())
    if change.get("degraded"):
        # Run terakhir datanya tidak lengkap: angka ini dari scan valid
        # sebelumnya, jadi diberi penanda supaya tidak dibaca sebagai hasil
        # scan terbaru.
        head += " ⚠️"
    title = (explain_change(change) + " — "
             + TONE_LABELS.get(tone, "")).replace('"', "'")
    detail = ""
    if show_detail:
        from_pct = _float(change.get("from_pct"), None)
        to_pct = _float(change.get("to_pct"), None)
        count_pct = _float(change.get("count_change_pct"), None)
        bits = []
        if from_pct is not None and to_pct is not None:
            bits.append(f"{from_pct:.2f}→{to_pct:.2f}% MC")
        if count_pct is not None:
            bits.append(f"{count_pct:+.0f}% wallet")
        if bits:
            detail = (f'<div style="font-size:.62rem;color:#000000;">'
                      f"{' · '.join(bits)}</div>")
    return (f'<div class="watchlist-metric" title="{title}">'
            f'<div style="font-size:.9rem;font-weight:800;color:{color};">'
            f"{head}</div>{detail}</div>")


# ---------------------------------------------------------------------------
# 3) Ringkasan sinkronisasi untuk caption dashboard
# ---------------------------------------------------------------------------
def sync_summary(views, *, now=None) -> dict:
    """Rekap sumber data per baris (dipakai caption "scan terakhir").

    Selain sumber per token, rekap ini menghitung **berapa token yang
    benar-benar duduk di waktu snapshot terbaru** (``latest_count``) dan
    berapa yang masih memakai snapshot lebih lama (``older_count``): satu
    angka "Scan terakhir" saja menyesatkan bila sebagian baris belum
    ter-update sejak run sebelumnya.
    """
    anchor = _int(now, None)
    summary = {"total": 0, "dari_history": 0, "dari_snapshot": 0,
               "tanpa_data": 0, "stale": 0, "drift": 0, "degraded": 0,
               "last_scan_ts": None, "latest_count": 0, "older_count": 0,
               "max_age_sec": None}
    stamps = []
    for view in views or []:
        view = view if isinstance(view, dict) else {}
        summary["total"] += 1
        if view.get("degraded"):
            summary["degraded"] += 1
        ts = _int(view.get("ts"), 0)
        if not ts or view.get("dust_pct") is None:
            summary["tanpa_data"] += 1
            continue
        if str(view.get("source")) == SOURCE_HISTORY:
            summary["dari_history"] += 1
        else:
            summary["dari_snapshot"] += 1
        if view.get("stale"):
            summary["stale"] += 1
        if view.get("drift"):
            summary["drift"] += 1
        age = _int(view.get("age_sec"), None) if anchor else None
        if age is not None and (summary["max_age_sec"] is None
                                or age > summary["max_age_sec"]):
            summary["max_age_sec"] = age
        stamps.append(ts)
        if summary["last_scan_ts"] is None or ts > summary["last_scan_ts"]:
            summary["last_scan_ts"] = ts
    if stamps:
        newest = max(stamps)
        summary["latest_count"] = sum(1 for stamp in stamps
                                      if stamp == newest)
        summary["older_count"] = len(stamps) - summary["latest_count"]
    return summary


def sync_caption_text(summary: dict | None, *, status_updated_at=None,
                      stale_after: int = STALE_AFTER_SEC) -> str:
    """Kalimat caption: waktu scan terakhir + dari mana angka baris diambil."""
    summary = summary if isinstance(summary, dict) else {}
    last_ts = summary.get("last_scan_ts") or _int(status_updated_at, None)
    bits = [f"Scan terakhir: **{format_wib(last_ts)}**"]
    if _int(summary.get("latest_count"), 0):
        bits[0] += f" ({summary['latest_count']} token)"
    if _int(summary.get("older_count"), 0):
        # Setiap baris membawa waktu snapshotnya sendiri (kolom "scan …" di
        # baris) — sebutkan berapa yang belum ikut waktu terbaru.
        bits.append(f"{summary['older_count']} token masih di snapshot "
                    "sebelumnya — waktu tiap baris ada di kolom scan")
    total = _int(summary.get("total"), 0)
    if total:
        sumber = []
        if summary.get("dari_snapshot"):
            sumber.append(f"{summary['dari_snapshot']} dari snapshot cron")
        if summary.get("dari_history"):
            sumber.append(f"{summary['dari_history']} dari titik history "
                          "lebih baru")
        if summary.get("tanpa_data"):
            sumber.append(f"{summary['tanpa_data']} belum ada data")
        if sumber:
            bits.append("angka per token: " + ", ".join(sumber))
        if summary.get("drift"):
            bits.append(f"⚠️ {summary['drift']} token snapshot ≠ titik history "
                        "(baris memakai yang terbaru)")
        if summary.get("degraded"):
            bits.append(
                f"⚠️ {summary['degraded']} token: scan terakhirnya tidak "
                f"lengkap (< {MIN_USABLE_WALLETS} wallet terambil, provider "
                "holder mengembalikan sampel pendek) — angka baris memakai "
                "scan layak terakhir, bukan 0% palsu")
        if summary.get("stale"):
            bits.append(f"{summary['stale']} token datanya lebih tua dari "
                        f"{format_age(stale_after)}")
    if summary.get("max_age_sec") is not None:
        bits.append(f"umur data tertua {format_age(summary['max_age_sec'])}")
    return " · ".join(bits)
