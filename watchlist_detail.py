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

Ambang warna (permintaan user 2026-09-04):

- ``% MC`` yang dipegang dust **turun ≥ 50%** → hijau (dust menipis),
- ``% MC`` yang dipegang dust **naik ≥ 100%** → merah (dust menebal 2×),
- di antaranya → netral (abu-abu).

⚠️ Angka ini heuristik pemantauan, bukan prediksi arah harga — disclaimer yang
sama dipakai README/AGENTS untuk seluruh rule dust.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# --- ambang warna (relatif terhadap nilai dust % MC saat masuk watchlist) ------
MCAP_DROP_TONE_PCT = 50.0     # turun >= 50% -> hijau
MCAP_RISE_TONE_PCT = 100.0    # naik >= 100% -> merah

# Cron holder jalan 1x/jam (lihat AGENTS.md): data lebih tua dari ini = basi.
STALE_AFTER_SEC = 2 * 3600

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
def resolve_view(token: dict | None, points, *, now=None) -> dict:
    """Pilih nilai dust **terbaru** antara snapshot status dan titik history.

    ``token`` = ``holder_status["tokens"][mint]`` (sudah lewat
    ``apply_manual_scan`` di UI). ``points`` = titik gabungan
    ``holder_history`` + salinan ringkas snapshot (``_points_for`` di app.py).

    Return ``{dust_pct, dust_count, ts, source, age_sec, stale, drift,
    snapshot_pct, history_pct}``:

    - ``source`` = ``"snapshot"`` bila snapshot sama baru/lebih baru, atau
      ``"history"`` bila titik history lebih baru (scan manual / cron yang
      publish snapshot-nya gagal),
    - ``drift`` = True bila kedua sumber punya angka berbeda melebihi
      ``DRIFT_TOLERANCE_PP`` — persis kondisi "watchlist dan scan terakhir
      kurang sinkron" yang dilaporkan user,
    - ``stale`` = data lebih tua dari ``STALE_AFTER_SEC``.
    """
    token = token if isinstance(token, dict) else {}
    holders = token.get("holders") if isinstance(token.get("holders"), dict) \
        else {}
    rows = [row for row in (points or [])
            if isinstance(row, dict) and _int(row.get("ts")) > 0]
    last_point = rows[-1] if rows else {}

    snapshot_pct = _float(holders.get("dust_pct_mc"), None)
    snapshot_count = holders.get("dust_count")
    snapshot_ts = _int(token.get("analyzed_at"), 0)
    history_pct = _float(last_point.get("dust_pct_mc"), None)
    history_count = last_point.get("dust_count")
    history_ts = _int(last_point.get("ts"), 0)

    use_history = (history_ts > snapshot_ts and history_pct is not None)
    drift = (snapshot_pct is not None and history_pct is not None
             and abs(snapshot_pct - history_pct) > DRIFT_TOLERANCE_PP
             and snapshot_ts != history_ts)

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
    return {
        "dust_pct": dust_pct,
        "dust_count": _int(dust_count, None) if dust_count is not None else None,
        "ts": ts or None,
        "source": SOURCE_HISTORY if use_history else SOURCE_SNAPSHOT,
        "age_sec": age,
        "stale": bool(age is not None and age > STALE_AFTER_SEC),
        "drift": bool(drift),
        "snapshot_pct": snapshot_pct,
        "history_pct": history_pct,
        "snapshot_ts": snapshot_ts or None,
        "history_ts": history_ts or None,
        "points": len(rows),
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
    """
    rows = [row for row in (points or [])
            if isinstance(row, dict) and _int(row.get("ts")) > 0
            and _float(row.get("dust_pct_mc"), None) is not None]
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
        "tone": TONE_UNKNOWN,
    }

    if not from_row:
        result["alasan"] = ("Belum ada titik history untuk token ini — cron "
                            "holder belum pernah mencatat scan.")
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
    if change.get("anchor_fallback"):
        parts.append(f"pembanding: titik pertama ({change['anchor_fallback']})")
    return " · ".join(parts)


def change_html(change: dict, *, show_detail: bool = True) -> str:
    """HTML satu sel "sejak masuk" (warna mengikuti ambang user)."""
    change = change or {}
    tone = str(change.get("tone") or TONE_UNKNOWN)
    color = TONE_COLORS.get(tone, TONE_COLORS[TONE_UNKNOWN])
    if not change.get("cukup_data"):
        return ('<div class="watchlist-metric"><div '
                f'style="font-size:.8rem;color:{TONE_COLORS[TONE_UNKNOWN]};">'
                "belum ada data</div></div>")
    relative = _float(change.get("pct_change"), None)
    head = ("—" if relative is None
            else f"{TONE_ARROWS.get(tone, '')} {relative:+.1f}%".strip())
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
    """Rekap sumber data per baris (dipakai caption "scan terakhir")."""
    anchor = _int(now, None)
    summary = {"total": 0, "dari_history": 0, "dari_snapshot": 0,
               "tanpa_data": 0, "stale": 0, "drift": 0,
               "last_scan_ts": None, "max_age_sec": None}
    for view in views or []:
        view = view if isinstance(view, dict) else {}
        summary["total"] += 1
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
        if summary["last_scan_ts"] is None or ts > summary["last_scan_ts"]:
            summary["last_scan_ts"] = ts
    return summary


def sync_caption_text(summary: dict | None, *, status_updated_at=None) -> str:
    """Kalimat caption: waktu scan terakhir + dari mana angka baris diambil."""
    summary = summary if isinstance(summary, dict) else {}
    last_ts = summary.get("last_scan_ts") or _int(status_updated_at, None)
    bits = [f"Scan terakhir: **{format_wib(last_ts)}**"]
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
        if summary.get("stale"):
            bits.append(f"{summary['stale']} token datanya lebih tua dari "
                        f"{format_age(STALE_AFTER_SEC)}")
    if summary.get("max_age_sec") is not None:
        bits.append(f"umur data tertua {format_age(summary['max_age_sec'])}")
    return " · ".join(bits)
