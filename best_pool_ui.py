# -*- coding: utf-8 -*-
"""Card **🏆 Scan Best Pool Meteora** untuk halaman utama (``app.py``).

**Dua tombol deteksi, dua tabel** (permintaan user 2026-09-13: "kayaknya untuk
timeframe 30m harus kita pisah tombol deteksinya dan tabel serta fungsi fee/v
lebih besar … di scan meteora pool, kita akan punya 2 tombol 24H dan 30M"):

- **🏆 Scan Best Pool 24H + Holder** — listing timeframe 24H saja; hanya pool
  ``F/V ≥ 5×`` (``BEST_FV_24H_MIN``) yang di-scan detail (holder FULL Helius).
  Yang di bawah itu **langsung di-skip** dan masuk listing "disembunyikan";
- **🏆 Scan Best Pool 30M + Holder** — listing timeframe 30M saja; syaratnya
  fee/vol **lebih besar** (``F/V > 1×`` = ``fee_active_tvl_ratio >
  volatility``, ``BEST_FV_30M_MIN``), yang lebih kecil langsung di-skip.
  Volatility 0 **gugur di kedua lane** (2026-09-14): ∞ bukan kelolosan,
  baris ∞ tidak pernah masuk tabel lolos — dan sejak lanjutan hari yang sama
  pool volatility 0 **dibuang dari listing seluruhnya** (permintaan user:
  "jika volatility 0 jangan tampilkan, karena tidak ada pergerakan disitu"):
  tidak masuk tabel lolos, tidak masuk listing "dilewati" 24H, dan tidak
  dihitung di pill/caption.
- Sel F/V lane 30M: baris yang lolos menampilkan **OK** hijau (angka quotient
  tetap di tooltip sel + kunci urut); kandidat yang tidak memenuhi syarat
  **tidak ditampilkan sama sekali** di 30M — toggle disembunyikan dan pill
  jumlah disembunyikan hanya ada untuk 24H (permintaan user 2026-09-14:
  "kalau di M30, jika syarat terpenuhi, tulis OK · jangan tampilkan yang
  tidak terpenuhi").

F = fee_active_tvl_ratio, V = volatility. Kedua lane disimpan di session key
masing-masing (``best_pool_scan_24h`` / ``best_pool_scan_30m``) sehingga tabel
24H tidak pernah lagi berisi baris 30M — kolom **Src** lama dihapus karena
tidak relevan lagi, diganti pill lane di kepala card.

- urutan baris tiap tabel: **F/V terbesar** (``row_fv_ratio``) → **volume /
  active TVL window lane-nya** (``volume_active_tvl_ratio``, dikirim API
  Meteora dan ditulis di baris kecil kolom Vol) → **dust % MC terkecil**;
- **Fee/TVL tepat di kanan F/V** (penataan kolom 2026-09-14): Token, **F/V**
  (fee_active_tvl_ratio ÷ volatility — kunci urut + syarat lane), **Fee/TVL**
  (pembilang F-nya — permintaan user: "kolom Fee/TVL taruh sebelah kanan
  F/V"), **Volat**, **Dust %MC**; lalu **Fee %** (fee trading pool, mis.
  0.5% / 2% — ditambah setelah Dust %MC), MC, A.TVL, **Vol 24h/30m** (judul
  mengikuti window lane), Top10, LPs, Pool, ⭐. Kolom **Dust** (jumlah
  wallet) dihapus hari yang sama;
- **sorot hijau tua menyala** (``TOP_HIGHLIGHT_COLOR``, bold) di tabel utama:
  sel volatility terbesar, sel F/V tertinggi, dan sel Fee/TVL tertinggi scan
  itu — seri di puncak ikut ditandai semua; tabel "dilewati" tidak ditandai;
- filter API tetap ``pool_type=dlmm&&active_tvl>=50000``; dust, volume,
  volatility minimal, tier fee, top10 dan LPs **bukan** syarat;
- kolom konteks menampilkan detail fee dan active TVL (**A.TVL**,
  **Fee/TVL** dengan fee USD + tier fee, Vol dengan Δ volume + rasio
  volume/active TVL) sebagai informasi.

**Persistensi (2026-09-14):** hasil scan tiap lane disimpan ke cache berkas
lokal (``scan_result_cache.save_result``, key = session key lane-nya) dan
dipulihkan ke ``session_state`` bila sesi kosong, jadi **refresh browser
(F5) tidak menghilangkan tabel** — sesudah scan holder FULL yang memakan
menit, user tidak perlu menekan tombol scan lagi dari nol.

**🏆 BEST POOL badge (dust <= 0,035% MC) dihapus** 2026-09-13 sore per
permintaan user: \"tulisan tentang dust holder BEST POOL aman dll hapus
juga\". Pill di kepala card juga dihapus. Dust %MC tetap tampil sebagai
informasi (angka + tie-break urut) tanpa penanda visual apa pun.

Detail karakteristik = **tooltip judul** — bukan caption panjang. ⭐
memasukkan token ke card **Watchlist Meteora** di halaman utama.
"""
from __future__ import annotations

# Session key lama (satu listing gabungan 24H + 30M). Masih dibaca sekali untuk
# bermigrasi: hasil scan versi sebelum lane dipisah dipecah per timeframe, jadi
# user tidak kehilangan listing setelah update ini.
BEST_SESSION_KEY = "best_pool_scan"
BEST_SHOW_HIDDEN_KEY = "best_pool_show_hidden"
# Satu key per lane — ini yang dipakai card sejak 2026-09-13.
BEST_LANE_SESSION_KEY = "best_pool_scan_{}"
BEST_LANE_HIDDEN_KEY = "best_pool_show_hidden_{}"
BEST_ACTIVE_LANE_KEY = "best_pool_lane"


def best_lane_session_key(lane) -> str:
    """Session key hasil scan satu lane (``best_pool_scan_24h`` / ``_30m``)."""
    from meteora_screener import normalize_best_lane

    return BEST_LANE_SESSION_KEY.format(normalize_best_lane(lane))


def best_lane_hidden_key(lane) -> str:
    """Session key toggle "N disembunyikan" satu lane."""
    from meteora_screener import normalize_best_lane

    return BEST_LANE_HIDDEN_KEY.format(normalize_best_lane(lane))


def best_lane_gate_text(lane) -> str:
    """Syarat kelolosan satu lane dalam teks UI, angka dari konstanta screener.

    ``meteora_screener`` diimpor di dalam fungsi (pola tooltip modul UI lain)
    supaya modul ini tetap ringan diimpor dan ambangnya tidak pernah bisa basi.
    """
    from meteora_screener import lane_fv_min, lane_fv_sign, normalize_best_lane

    normalized = normalize_best_lane(lane)
    return f"F/V {lane_fv_sign(normalized)} {lane_fv_min(normalized):g}×"


def best_lane_detail(lane) -> tuple[str, str, str]:
    """``(label, warna, teks syarat)`` satu lane — dipakai pill, tombol, tooltip."""
    from meteora_screener import BEST_LANE_LABELS, normalize_best_lane

    normalized = normalize_best_lane(lane)
    return (BEST_LANE_LABELS.get(normalized, normalized.upper()),
            "#9333ea" if normalized == "30m" else "#0284c7",
            best_lane_gate_text(normalized))


def best_pool_tooltip() -> str:
    """Rule ada di tooltip, bukan caption — dua tombol, satu lane per tombol."""
    from meteora_screener import BEST_ACTIVE_TVL_MIN, BEST_LANES

    gates = " · ".join(f"{best_lane_detail(lane)[0]}: {best_lane_gate_text(lane)}"
                       for lane in BEST_LANES)
    return (
        "Dua tombol = dua lane terpisah: setiap tombol mengambil listing "
        f"API Meteora timeframe-nya sendiri (category top, page_size 50), "
        f"pool_type=dlmm&&active_tvl>={int(BEST_ACTIVE_TVL_MIN)}. "
        f"{gates}. F = fee_active_tvl_ratio; V = volatility dari lane itu. "
        "Pool di bawah ambang lane-nya langsung dilewati SEBELUM scan holder "
        "(kuota Helius tidak terbakar). Lane 24H: kandidat gagal F/V bisa "
        "dilihat lewat tombol disembunyikan; lane 30M: kandidat gagal TIDAK "
        "ditampilkan sama sekali, dan baris yang lolos cukup ditandai OK di "
        "kolom F/V (angka aslinya di tooltip sel). Volatility 0 gugur di "
        "kedua lane (F/V ∞ bukan kelolosan — pool tanpa volatility tidak "
        "bisa membuktikan fee lebih besar) DAN tidak ditampilkan di mana "
        "pun: pool tanpa pergerakan dibuang dari listing, juga tidak masuk "
        "tabel disembunyikan 24H atau hitungan \"dilewati\". Metrik "
        "hilang/tidak valid dilewati (tetap terlihat di tabel disembunyikan "
        "24H). Hanya pool lolos yang mengambil detail holder FULL "
        "Helius. Dust, volume, tier fee, Top10 dan LPs bukan syarat "
        "kelolosan. Urutan tiap tabel: F/V terbesar, lalu volume/active TVL "
        "terbesar, lalu dust %MC terkecil. Tiap lane punya tabel + session "
        "key sendiri, jadi hasil 24H tidak pernah tercampur 30M. Kolom di "
        "paling depan: Token, F/V, Fee/TVL (tepat di kanan F/V), Volat, "
        "Dust %MC, lalu Fee % (fee trading pool, mis. 0.5% / 2%); kolom "
        "volume mengikuti "
        "window lane (Vol 24h / Vol 30m). Sel volatility terbesar, F/V "
        "tertinggi, dan Fee/TVL tertinggi di tabel utama disorot hijau tua "
        "menyala (kalau seri, semua "
        "di puncak ikut ditandai; tabel dilewati tidak ditandai). Dust %MC "
        "memakai market cap DexScreener; holder gagal tampil —. ⭐ memasukkan "
        "token ke Watchlist Meteora."
    )


# Lebar kolom listing (permintaan user 2026-09-14: "kita tata kolomnya baik
# untuk 24jam maupun 30menit — Dust hapus — Token F/V Volat Dust %MC, 4 kolom
# ini diletakkan paling awal"): Token, F/V, Volat, Dust %MC di depan, lalu
# konteks pasar (MC, A.TVL, Fee/TVL, volume window lane, Top10, LPs), Pool,
# ⭐. Kolom **Dust** (jumlah wallet) dihapus hari yang sama. Judul kolom
# volume mengikuti lane-nya (``_lane_titles``: 24H "Vol 24h", 30M "Vol 30m")
# — kolom Src sudah lama dihapus bersama pemisahan lane.
# Kolom **Fee %** (fee trading pool, mis. 0.5%, 2%) ditambah 2026-09-14 tepat
# setelah Dust %MC (permintaan user: "tambahkan detail pool fee % … setelah
# dust%MC … ini maksudnya fee di pool tersebut, misal 0.5%, 2%, dll").
# Kolom **Fee/TVL** dipindah tepat di kanan **F/V** hari yang sama
# (permintaan user: "kolom Fee/TVL taruh sebelah kanan F/V") — pembilang F
# menempel pada rasio F/V-nya; Volat, Dust %MC, dan semua kolom di kanannya
# bergeser satu posisi.
_COL_SPEC = [1.5, 0.7, 0.78, 0.6, 0.82, 0.6, 0.65, 0.78, 0.85, 0.62,
             0.5, 1.0, 0.4]


def _lane_titles(lane) -> list[str]:
    """Judul kolom satu tabel — kolom volume dinamai sesuai window lane-nya.

    API Meteora mengembalikan volume/fee window ``timeframe`` yang diminta,
    jadi tabel 30M tidak boleh menamai kolomnya "Vol 24h" (bagian dari
    penataan kolom 2026-09-14: "baik untuk 24jam maupun 30menit").
    """
    from meteora_screener import normalize_best_lane

    volume = "Vol 30m" if normalize_best_lane(lane) == "30m" else "Vol 24h"
    return ["Token", "F/V", "Fee/TVL", "Volat", "Dust %MC", "Fee %", "MC",
            "A.TVL", volume, "Top10", "LPs", "Pool", ""]


# Hijau tua menyala penanda sel tertinggi di tabel utama (permintaan user
# 2026-09-14: "tandai volatility paling besar …" + "tandai f/v tertinggi …
# menjadi warna hijau menyala" + lanjutan: "yang paling tinggi nilainya kasih
# warna hijau menyala, hijau tua menyala" → F/V, Fee/TVL, Volat tertinggi
# semua memakai satu warna hijau tua menyala). Dipakai sel Volat, sel F/V,
# dan sel Fee/TVL.
TOP_HIGHLIGHT_COLOR = "#15803d"


def _top_span(text: str) -> str:
    """Bungkus isi sel dengan hijau tua menyala + bold — penanda tertinggi tabel."""
    return (f'<span style="color:{TOP_HIGHLIGHT_COLOR};font-weight:800;">'
            f'{text}</span>')


def _finite_number(value):
    """``float`` finite atau ``None`` — untuk mencari nilai tertinggi tabel."""
    import math as _math

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if _math.isfinite(number) else None


def _table_tops(rows: list) -> tuple:
    """``(volatility tertinggi, F/V tertinggi, Fee/TVL tertinggi)`` di tabel.

    Dipakai untuk sorot hijau tua menyala (permintaan user 2026-09-14 —
    lanjutan: Fee/TVL tertinggi ikut ditandai). Baris tanpa angka valid
    diabaikan; bila beberapa baris seri di puncak, SEMUANYA ikut ditandai
    (tidak ada pemenang acak). Setiap kolom dicari maksimumnya
    sendiri-sendiri, jadi baris pemegang Fee/TVL tertinggi bisa berbeda dari
    baris pemegang F/V tertinggi. Hanya tabel utama yang memanggil ini —
    tabel "dilewati" 24H sengaja tidak ditandai (barisnya sudah dianotasi
    merah gugur-ambang).
    """
    from meteora_screener import row_fv_ratio

    top_vol = top_fv = top_fee_tvl = None
    for row in rows or []:
        vol = _finite_number((row or {}).get("volatility"))
        if vol is not None:
            top_vol = vol if top_vol is None else max(top_vol, vol)
        ratio = row_fv_ratio(row)
        if ratio is not None and _finite_number(ratio) is not None:
            top_fv = ratio if top_fv is None else max(top_fv, ratio)
        fee_tvl = _finite_number((row or {}).get("fee_active_tvl_ratio"))
        if fee_tvl is not None:
            top_fee_tvl = (fee_tvl if top_fee_tvl is None
                           else max(top_fee_tvl, fee_tvl))
    return top_vol, top_fv, top_fee_tvl


def _best_head_html(rows: list, hidden: int, lane: str,
                    *, showing_hidden: bool = False) -> str:
    """Header card: judul + pill lane aktif + jumlah pool / yang disembunyikan.

    Pill **🏆 BEST POOL** dihapus 2026-09-13 per permintaan user
    (\"tulisan tentang dust holder BEST POOL aman dll hapus juga\"). Pill
    **24H/30M** ditambah hari yang sama: tombol dan tabel sudah dipisah per
    timeframe, jadi kepala card yang menunjukkan lane mana yang sedang tampil.
    """
    from dashboard_components import card_head_html
    from meteora_screener import BEST_CARD_TITLE, normalize_best_lane

    label, color, gate = best_lane_detail(lane)
    pills = [f'<span class="lp-count" style="color:#ffffff;background:{color};">'
             f'{label} · {gate}</span>',
             f'<span class="lp-count">{len(rows)} pool</span>']
    # Lane 30M tidak menampilkan kandidat gagal sama sekali (2026-09-14),
    # jadi pill jumlah disembunyikan hanya untuk 24H. Pool volatility 0 dibuang
    # sebelum tabel (permintaan user: tidak ada pergerakan), jadi ``hidden``
    # yang diterima di sini tidak pernah menghitungnya.
    if hidden and normalize_best_lane(lane) != "30m":
        tone = ("color:#1e3a8a;background:#bfdbfe;" if showing_hidden
                else "color:#334155;background:#e2e8f0;")
        pills.append(f'<span class="lp-count" style="{tone}">'
                     f"{hidden} disembunyikan</span>")
    return card_head_html(BEST_CARD_TITLE, pills, tooltip=best_pool_tooltip())


def _pct_txt(value, digits: int = 2) -> str:
    """Angka persen siap tampil (``None`` → ``—``)."""
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _signed_pct(value) -> tuple[str, str]:
    """Persen dengan tanda +/− + warna (hijau naik, merah turun).

    Dipakai untuk **Δ volume** (baris kecil kolom Vol 24h) — rasio volume
    24 jam / active TVL adalah kunci urut KEDUA card (pertama F/V), jadi angka
    volume + arah perubahannya tetap harus terbaca sekali lihat.
    ``None`` → ``—``.
    """
    if value is None:
        return "—", ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—", ""
    text = f"{number:+.1f}%"
    color = "#16a34a" if number > 0 else ("#dc2626" if number < 0 else "")
    return text, color


def _pct_or_dash(value, pattern: str = ".1f") -> str:
    """Persen siap tampil, aman ``None`` (``—``, bukan ``—%`` yang aneh)."""
    from dashboard_components import _number

    return "—" if value is None else f"{_number(value, pattern)}%"


def _num_or_dash(value, pattern: str = ".0f") -> str:
    """Angka biasa siap tampil (``None`` → ``—``)."""
    from dashboard_components import _number

    return "—" if value is None else _number(value, pattern)


def _usd_or_dash(value, compact: bool = True) -> str:
    """USD siap tampil: ringkas (``$24.0K``) atau penuh (``$24,000``).

    Data lama di ``session_state`` bisa tidak punya field baru (fee /
    volume_change) — ``None`` harus jadi ``—``, bukan ``$0``.
    """
    if value is None:
        return "—"
    if compact:
        from dashboard_components import _compact

        return _compact(value)
    from dashboard_components import _number

    return f"${_number(value, ',.0f')}"


def _cell(value: str, sub: str = "", title: str = "") -> str:
    """Satu sel metrik listing: angka + baris kecil (boleh HTML, mis. warna).

    ``title`` = tooltip browser dengan angka penuh (persen/USD mentah dari
    API Meteora) supaya angka ringkas di card tetap bisa diverifikasi.
    """
    import html as _html

    tip = f' title="{_html.escape(str(title))}"' if title else ""
    return ('<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{value}</div>'
            f'<div class="watchlist-metric-sub"{tip}>{sub}</div></div>')


def _fv_cell(row: dict, lane: str, *, top: bool = False) -> tuple[str, str, str]:
    """Sel **F/V** = ``fee_active_tvl_ratio ÷ volatility`` satu baris + lane.

    Lane **30M** (permintaan user 2026-09-14): baris yang lolos cukup
    menampilkan **OK** hijau — angka quotient tetap di tooltip sel dan tetap
    jadi kunci urut + saringan, tapi tidak ditampilkan di sel. Lane **24H**
    tetap menampilkan angka ``N,N×``. ``top=True`` (F/V tertinggi di tabel
    utama) mengubahnya jadi **hijau tua menyala + bold**, baik untuk sel angka
    24H maupun sel OK 30M (permintaan user: "tandai f/v tertinggi tersebut
    menjadi warna hijau menyala" — lanjutan: "yang paling tinggi nilainya
    kasih warna hijau menyala, hijau tua menyala"). Baris gagal ambang
    (hanya mungkin muncul
    di listing "disembunyikan" lane 24H, yang tidak pernah diberi tanda)
    tetap merah + alasan, supaya jelas kenapa holdernya tidak ikut di-scan.
    """
    import math as _math

    from meteora_screener import (normalize_best_lane, row_best_gaps,
                                  row_fv_ratio)

    ratio = row_fv_ratio(row)
    label, _, gate = best_lane_detail(lane)
    fails = row_best_gaps(row, lane=lane)
    if normalize_best_lane(lane) == "30m" and not fails:
        # 30M lolos → "OK" saja; angka asli tetap di tooltip supaya urutan
        # dan syarat masih bisa diverifikasi (permintaan user 2026-09-14:
        # "kalau di M30, jika syarat terpenuhi, tulis OK").
        value, color = "OK", "#16a34a"
        sub = f"syarat {gate} terpenuhi"
    elif ratio is None:
        value, color = "—", "#dc2626"
        sub = f"syarat {gate}"
    elif _math.isinf(ratio):
        value, color = "∞", ""
        sub = f"syarat {gate}"
    else:
        value, color = f"{ratio:.1f}×", ""
        sub = f"syarat {gate}"
    tip = (f"fee_active_tvl_ratio {_num_or_dash(row.get('fee_active_tvl_ratio'), ',.2f')}%"
           f" ÷ volatility {_num_or_dash(row.get('volatility'), ',.2f')}% = "
           f"{_num_or_dash(ratio, ',.2f')}× — "
           f"berapa kali fee pool lebih besar dari volatility; kunci urut "
           f"pertama listing {label} + syarat lane ({gate}); "
           "lebih tinggi = fee lebih dominan")
    if fails:
        sub = f"gugur: {fails[0].split(': ', 1)[-1]}"
        shown = f'<span style="color:#dc2626;">{value}</span>'
    elif top:
        tip += " — F/V tertinggi di tabel ini"
        shown = _top_span(value)
    elif color:
        shown = f'<span style="color:{color};">{value}</span>'
    else:
        shown = value
    return shown, sub, tip


def _render_best_table(rows: list, *, lane: str,
                       key_prefix: str = "best-pool",
                       mark_tops: bool = True) -> None:
    """Tabel listing Best Pool untuk **satu** lane (utama atau disembunyikan).

    Susunan kolom 2026-09-14: Token · **F/V · Fee/TVL** (tepat di kanan F/V,
    permintaan user) **· Volat · Dust %MC** · **Fee %** (fee trading pool,
    mis. 0.5% / 2% — ditambah setelah Dust %MC) · MC · A.TVL · Vol (24h/30m
    mengikuti lane) · Top10 · LPs · Pool · ⭐ — kolom Dust (jumlah wallet)
    sudah dihapus. Di tabel
    utama (``mark_tops=True``) sel **volatility terbesar**, sel **F/V
    tertinggi**, dan sel **Fee/TVL tertinggi** disorot hijau tua menyala
    (``TOP_HIGHLIGHT_COLOR``, seri ikut
    semua); tabel "dilewati" 24H tidak ditandai (``mark_tops=False``).
    """
    import html

    import streamlit as st

    from dashboard_components import _number
    from links import external_links_html, pool_links_html
    from lp_watchlist import LP_SOURCE
    from meteora_screener import normalize_best_lane, row_dust_pct, row_fv_ratio
    from meteora_screener import row_vol_tvl_ratio
    from watchlist import add_to_watchlist

    header_cols = st.columns(_COL_SPEC)
    style = ("font-size:0.72rem;color:#000000;font-weight:700;"
             "text-align:center;")
    for col, title in zip(header_cols, _lane_titles(lane)):
        col.markdown(f'<div style="{style}">{title}</div>',
                     unsafe_allow_html=True)
    st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)

    top_vol, top_fv, top_fee_tvl = (_table_tops(rows) if mark_tops
                                     else (None, None, None))
    window_txt = ("30 menit" if normalize_best_lane(lane) == "30m"
                  else "24 jam")

    for index, row in enumerate(rows):
        ca = str(row.get("ca") or "")
        symbol = str(row.get("symbol") or "?").upper()
        pool = str(row.get("pool_address") or "")
        # Satu sumber angka dengan saringan + urutan: ``row_dust_pct`` sudah
        # mengembalikan ``None`` untuk scan holder tanpa bukti — dust tetap
        # tampil sebagai informasi (—) bukan 0,000% palsu. Filter dust
        # dinonaktifkan 2026-09-13.
        dust_pct = row_dust_pct(row)
        fee = row.get("fee")
        active_tvl = row.get("active_tvl")
        ratio = row.get("fee_active_tvl_ratio")
        volume = row.get("volume")
        volume_change = row.get("volume_change_pct")
        fee_pct = row.get("fee_pct")
        fee_sub = f"fee {_usd_or_dash(fee)}"
        if fee_pct is not None:
            fee_sub += f"·{_number(fee_pct, '.4g')}%"
        delta_txt, delta_color = _signed_pct(volume_change)
        delta_html = (f'<span style="color:{delta_color};">Δ '
                      f"{delta_txt}</span>" if delta_color
                      else f"<span>Δ {delta_txt}</span>")
        # Kunci urut KEDUA (volume / active TVL dari window lane) ditulis di
        # baris kecil kolom Vol supaya urutannya bisa diperiksa sekali lihat.
        vol_tvl_ratio = row_vol_tvl_ratio(row)
        if vol_tvl_ratio is not None:
            delta_html += (f" · {_num_or_dash(vol_tvl_ratio, ',.0f')}×"
                           " A.TVL")
        dust_value = _pct_txt(dust_pct, 3)
        dust_sub = "dust"
        dust_tip = ("dust holder — informasi (filter dust dinonaktifkan "
                    "2026-09-13) · tie-break urut terakhir (terkecil dulu) · "
                    "pembaginya market cap DexScreener (kolom MC), sumber "
                    "yang sama dengan 🛰 Scan Holder")
        # Sorot hijau tua menyala: F/V tertinggi, volatility terbesar, dan
        # Fee/TVL tertinggi tabel ini (permintaan user 2026-09-14 lanjutan).
        fv_here = row_fv_ratio(row)
        fv_top = bool(top_fv is not None and fv_here is not None
                      and fv_here == top_fv)
        fv_value, fv_sub, fv_tip = _fv_cell(row, lane, top=fv_top)
        vol_value = _pct_or_dash(row.get("volatility"))
        vol_tip = ("volatility pool "
                   f"{_num_or_dash(row.get('volatility'), ',.2f')}% — "
                   "informasi, bukan saringan lagi sejak 2026-09-13")
        vol_here = _finite_number(row.get("volatility"))
        if top_vol is not None and vol_here is not None and vol_here == top_vol:
            vol_value = _top_span(vol_value)
            vol_tip += " — volatility terbesar di tabel ini"
        fee_tvl_value = _pct_or_dash(ratio)
        fee_tvl_tip = (f"tier fee {_num_or_dash(fee_pct, '.4g')}% · fee "
                       f"{window_txt} {_usd_or_dash(fee, compact=False)} / "
                       f"active TVL {_usd_or_dash(active_tvl, compact=False)} "
                       f"= {_num_or_dash(ratio, ',.2f')}% — informasi, bukan "
                       "saringan")
        fee_tvl_here = _finite_number(ratio)
        if (top_fee_tvl is not None and fee_tvl_here is not None
                and fee_tvl_here == top_fee_tvl):
            fee_tvl_value = _top_span(fee_tvl_value)
            fee_tvl_tip += " — Fee/TVL tertinggi di tabel ini"
        cols = st.columns(_COL_SPEC)
        cols[0].markdown(
            '<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(ca)}</div>'
            "</div>", unsafe_allow_html=True)
        # Urutan sel = urutan judul di ``_lane_titles`` (tanpa Token di sini;
        # kolom Dust jumlah wallet sudah dihapus 2026-09-14; Fee/TVL tepat di
        # kanan F/V — permintaan user 2026-09-14).
        cells = (
            (fv_value, fv_sub, fv_tip),
            (fee_tvl_value, fee_sub, fee_tvl_tip),
            (vol_value, "volat", vol_tip),
            (dust_value, dust_sub, dust_tip),
            (_num_or_dash(fee_pct, ".4g") + "%" if fee_pct is not None
             else "—", "pool fee",
             f"fee trading pool ini (tier fee pool DLMM) = "
             f"{_num_or_dash(fee_pct, '.4g')}% (mis. 0.5%, 2%) — "
             "hanya informasi, bukan saringan"),
            (_usd_or_dash(row.get("mc")), "",
             f"market cap {_usd_or_dash(row.get('mc'), compact=False)} — "
             "DexScreener, angka yang dipakai sebagai pembagi Dust %MC"),
            (_usd_or_dash(active_tvl), "active tvl",
             f"active TVL {_usd_or_dash(active_tvl, compact=False)} · "
             f"TVL total {_usd_or_dash(row.get('tvl'), compact=False)}"),
            (_usd_or_dash(volume), delta_html,
             f"volume {window_txt} {_usd_or_dash(volume, compact=False)} · "
             f"perubahan {delta_txt} · rasio volume/active TVL "
             f"{_num_or_dash(vol_tvl_ratio, ',.2f')}% — kunci urut kedua "
             "(terbesar dulu), informasi (bukan saringan)"),
            (_pct_or_dash(row.get("top_holders_pct")), "top10",
             "10 holder teratas token base (% supply) — hanya "
             "informasi, bukan saringan lagi sejak 2026-09-11"),
            (_num_or_dash(row.get("total_lps")), "lps",
             "jumlah liquidity provider pool — hanya informasi, bukan "
             "saringan lagi sejak 2026-09-11"),
        )
        for position, (value, sub, tip) in enumerate(cells, start=1):
            cols[position].markdown(_cell(value, sub, tip),
                                    unsafe_allow_html=True)
        pool_html = pool_links_html(pool) or "<span>—</span>"
        cols[11].markdown(f'<div class="pool-links">{pool_html}</div>',
                          unsafe_allow_html=True)
        star_key = f"{key_prefix}-star-{pool or ca or index}"
        if cols[12].button("⭐", key=star_key,
                           help="Tambah ke Watchlist Meteora "
                                "(halaman utama)",
                           use_container_width=True):
            if ca:
                add_to_watchlist(ca, symbol, source=LP_SOURCE,
                                 background=True)
                st.success(f"${symbol} masuk Watchlist Meteora")
        st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)


def _split_legacy_result(result: dict) -> dict:
    """Pecah hasil scan lama (24H + 30M jadi satu) ke dua lane.

    Sekali jalan per sesi: card kini membaca satu key per lane, sedangkan
    sesi yang sudah terbuka sebelum perubahan ini hanya punya
    ``best_pool_scan``. Baris dipilah dari ``timeframe``/``source``-nya, jadi
    listing terakhir tidak hilang saat tombol baru pertama kali dirender.
    """
    from meteora_screener import normalize_best_lane

    out: dict[str, dict] = {}
    rows = list(result.get("rows") or [])
    hidden_rows = list(result.get("hidden_rows") or [])
    for lane in ("24h", "30m"):
        lane_rows = [row for row in rows
                     if normalize_best_lane(row.get("timeframe")
                                            or row.get("source"),
                                            default="24h") == lane]
        lane_hidden = [row for row in hidden_rows
                       if normalize_best_lane(row.get("timeframe")
                                              or row.get("source"),
                                              default="24h") == lane]
        if not lane_rows and not lane_hidden:
            continue
        out[lane] = {
            "rows": lane_rows,
            "hidden_rows": lane_hidden,
            "error": result.get("error") or "",
            "fetched": len(lane_rows) + len(lane_hidden),
            "hidden_metric": len(lane_hidden),
            "hidden_dust": 0,
            "skipped_quote": 0,
            # Hasil lama tidak membedakan pool vol-0 di hidden_rows — filter
            # render di ``render_best_pool_scan`` yang membuangnya dari tabel
            # dan hitungan, jadi 0 di sini hanya artinya "tidak tercatat".
            "dropped_volatility": 0,
            "lane": lane,
            "analyzed_at": result.get("analyzed_at"),
        }
    return out


def _lane_result(st, lane: str) -> dict:
    """Hasil scan tersimpan satu lane (dibaca dari session_state)."""
    return st.session_state.get(best_lane_session_key(lane)) or {}


def _run_lane_scan(lane: str, *, progress=None) -> dict:
    """Satu kali scan satu lane — dipakai tombol card.

    ``progress`` dipanggil ``(index, total, label)``; kegagalan scanner
    menjadi pesan card (``error``), bukan exception yang mematikan halaman.
    """
    from holder_history import FULL_SCAN_MAX_WALLETS
    from meteora_screener import scan_best_lane

    try:
        # FULL scan (bukan cap kecil): urutan getTokenAccounts Helius tidak
        # urut saldo, jadi sampel kecil membuat angka dust tidak bisa dipercaya.
        return scan_best_lane(lane, max_wallets=FULL_SCAN_MAX_WALLETS,
                              workers=6, progress=progress)
    except Exception as exc:  # noqa: BLE001 - kegagalan = pesan card
        return {"rows": [], "hidden_rows": [], "error": str(exc),
                "fetched": 0, "hidden_metric": 0, "hidden_dust": 0,
                "skipped_quote": 0, "dropped_volatility": 0, "lane": lane}


def render_best_pool_scan() -> None:
    """Card **🏆 Scan Best Pool Meteora** di halaman utama.

    Dua tombol (24H / 30M) — satu tombol = satu lane listing + satu tabel.
    Lane yang sedang ditampilkan disimpan di ``best_pool_lane`` supaya hasil
    scan yang sudah ada bisa dilihat ulang tanpa memindai ulang.
    """
    import streamlit as st

    from meteora_screener import (BEST_LANES, normalize_best_lane,
                                  row_best_gaps, row_volatility_zero,
                                  sort_best_rows)

    with st.container(border=True):
        active = normalize_best_lane(
            st.session_state.get(BEST_ACTIVE_LANE_KEY) or "24h")
        if active not in BEST_LANES:
            active = "24h"

        # Pulihkan hasil scan dari cache berkas lokal bila session_state kosong
        # — Streamlit membuat session baru setiap refresh browser (F5) / tab
        # baru, sehingga tanpa ini listing + holder FULL yang memakan menit
        # ikut hilang dan user harus menekan tombol scan lagi. Cache diisi
        # ``scan_result_cache.save_result`` sesudah scan (lihat bawah).
        try:
            import scan_result_cache

            for lane in BEST_LANES:
                scan_result_cache.restore_into_session(
                    st, best_lane_session_key(lane), best_lane_session_key(lane))
        except Exception:  # noqa: BLE001 - cache hanya pelengkap
            pass

        # Migrasi hasil lama (gabungan 24H + 30M) ke key per-lane, sekali saja.
        if not any(st.session_state.get(best_lane_session_key(lane))
                   for lane in BEST_LANES):
            legacy = st.session_state.get(BEST_SESSION_KEY) or {}
            if legacy:
                split = _split_legacy_result(legacy)
                if not split and str(legacy.get("error") or ""):
                    # Tidak ada baris untuk dipecah (mis. listing API gagal) —
                    # minimal pesan error lama tetap tampil, jangan hilang
                    # bersama key lama.
                    split = {active: dict(legacy, rows=[], hidden_rows=[],
                                         fetched=0, hidden_metric=0,
                                         hidden_dust=0, dropped_volatility=0,
                                         lane=active)}
                for lane, part in split.items():
                    st.session_state[best_lane_session_key(lane)] = part

        # ---- dua tombol deteksi: 24H dan 30M ------------------------------
        cols = st.columns(len(BEST_LANES))
        pressed: str | None = None
        for col, lane in zip(cols, BEST_LANES):
            label, _color, gate = best_lane_detail(lane)
            stored = _lane_result(st, lane)
            count = len(stored.get("rows") or [])
            if col.button(f"🏆 Scan Best Pool {label} + Holder",
                          type="primary" if lane == active else "secondary",
                          key=f"best-pool-scan-{lane}",
                          use_container_width=True,
                          help=(f"Listing Meteora timeframe {label}, disaring "
                                f"{gate} SEBELUM scan holder — pool di bawah "
                                "ambang langsung di-skip, holdernya tidak "
                                f"di-fetch. Hasil tampil di tabel {label} "
                                "sendiri.")):
                pressed = lane
            col.caption(f"{count} pool tersimpan" if stored
                        else "belum di-scan")
        if pressed:
            bar = st.progress(0.0, text="Listing pool Meteora…")

            def _progress(index, total, note):
                bar.progress(index / max(total, 1),
                             text=f"Holder {index}/{total} · {note}")

            result = _run_lane_scan(pressed, progress=_progress)
            bar.empty()
            st.session_state[best_lane_session_key(pressed)] = result
            st.session_state[best_lane_hidden_key(pressed)] = False
            st.session_state[BEST_ACTIVE_LANE_KEY] = normalize_best_lane(pressed)
            # Tahan refresh browser: simpan hasil ke cache berkas lokal
            # (2026-09-14). Gagal tulis tidak boleh membatalkan hasil scan.
            try:
                import scan_result_cache

                scan_result_cache.save_result(best_lane_session_key(pressed),
                                              result)
            except Exception:  # noqa: BLE001 - cache hanya pelengkap
                pass
            st.rerun()

        # ---- pindah lihat tabel lane lain tanpa scan ulang ----------------
        others = [lane for lane in BEST_LANES
                  if lane != active and _lane_result(st, lane)]
        if others:
            view_cols = st.columns(len(BEST_LANES) + 1)
            view_cols[0].markdown(
                '<div style="font-size:0.72rem;color:#475569;'
                'font-weight:700;padding-top:.5rem;">Tabel:</div>',
                unsafe_allow_html=True)
            for position, lane in enumerate([active] + others, start=1):
                label, color, _gate = best_lane_detail(lane)
                count = len(_lane_result(st, lane).get("rows") or [])
                marker = "◼ " if lane == active else "◻ "
                weight = "700" if lane == active else "400"
                if view_cols[position].button(
                        f"{marker}{label} · {count} pool",
                        key=f"best-pool-view-{lane}",
                        use_container_width=True,
                        help=f"Tampilkan hasil scan lane {label} "
                             "tanpa memindai ulang."):
                    st.session_state[BEST_ACTIVE_LANE_KEY] = lane
                    st.rerun()
                view_cols[position].markdown(
                    f'<div style="font-size:0.62rem;color:{color};'
                    f'font-weight:{weight};">{"aktif" if lane == active else "hasil tersimpan"}</div>',
                    unsafe_allow_html=True)

        # ---- isi tabel lane aktif ------------------------------------------
        active = normalize_best_lane(
            st.session_state.get(BEST_ACTIVE_LANE_KEY) or "24h")
        result = _lane_result(st, active)
        error = str(result.get("error") or "")
        label, _color, _gate = best_lane_detail(active)
        if not result:
            st.markdown(_best_head_html([], 0, active),
                        unsafe_allow_html=True)
            st.info(f"Belum ada hasil scan lane {label}. Tekan tombol "
                    f"🏆 Scan Best Pool {label} + Holder untuk memindai "
                    "lane ini.")
            return
        # ``scan_best_lane`` sudah mengurutkan, tapi hasil lama di
        # ``session_state`` (dari kriteria versi sebelumnya) belum —
        # diurutkan lagi dengan rule baru agar listing konsisten tanpa perlu
        # scan ulang (kolom yang dibutuhkan sort ada di baris lama juga).
        stored_rows = result.get("rows") or []
        newly_hidden = [r for r in stored_rows if row_best_gaps(r, lane=active)]
        # Pool volatility 0 (tanpa pergerakan) juga dibuang di sini — filter
        # render supaya hasil scan LAMA yang masih membawa baris vol-0 di
        # ``rows`` (era sebelum ∞ gugur) atau di ``hidden_rows`` ikut bersih
        # tanpa scan ulang (permintaan user 2026-09-14 lanjutan: "jika
        # volatility 0 jangan tampilkan").
        stored_rows = [r for r in stored_rows if not row_volatility_zero(r)]
        rows = sort_best_rows([r for r in stored_rows
                              if not row_best_gaps(r, lane=active)])
        hidden_rows = sort_best_rows(
            [r for r in (result.get("hidden_rows") or []) + newly_hidden
             if not row_volatility_zero(r)])
        # ``hidden`` dihitung dari listing yang benar-benar bisa dilihat
        # (bukan counter mentah ``hidden_metric`` dari scan lama, yang masih
        # bisa menghitung pool vol-0), jadi pill/tombol/caption selalu cocok
        # dengan isi tabel disembunyikan.
        hidden = len(hidden_rows)
        fetched = int(result.get("fetched") or 0)
        skipped_quote = int(result.get("skipped_quote") or 0)
        # Lane 30M tidak menampilkan kandidat gagal sama sekali (permintaan
        # user 2026-09-14: "jangan tampilkan yang tidak terpenuhi") — toggle
        # disembunyikan + tabel disembunyikan hanya untuk 24H.
        showing_hidden = bool(
            st.session_state.get(best_lane_hidden_key(active))
            if active != "30m" else False)

        # Tanpa caption ambang: detail karakteristik card sudah jadi tooltip
        # judul (``best_pool_tooltip()``) — permintaan user 2026-09-10.
        st.markdown(_best_head_html(rows, hidden, active,
                                    showing_hidden=showing_hidden),
                    unsafe_allow_html=True)
        if hidden and active != "30m":
            # Caption/tombol = angka rekap saja; ambangnya hidup di tooltip
            # (judul card + tooltip sel F/V) — aturan card sejak 2026-09-10.
            view = ("◀ kembali ke tabel yang lolos"
                    if showing_hidden else f"▶ {hidden} pool dilewati")
            if st.button(view, key=f"best-pool-toggle-hidden-{active}",
                         help=f"Tampilkan kandidat {label} yang di-skip karena "
                              "di bawah ambang F/V lane ini; holdernya tidak "
                              "pernah di-scan.",
                         use_container_width=True):
                st.session_state[best_lane_hidden_key(active)] = \
                    not showing_hidden
                st.rerun()
        if error:
            st.warning(f"Meteora API: {error}")
        if fetched:
            quote_txt = (f" · {skipped_quote} pool quote dilewati"
                         if skipped_quote else "")
            if active == "30m":
                # 30M: baris yang tidak memenuhi syarat tidak tampil dan
                # tidak dihitung di caption (permintaan user 2026-09-14).
                st.caption(f"{len(rows)} pool {label} tampil · "
                           f"listing {fetched} pool{quote_txt}.")
            else:
                st.caption(f"{len(rows)} pool {label} tampil · {hidden} "
                           f"dilewati · listing {fetched} pool{quote_txt}.")
        if showing_hidden:
            if not hidden_rows:
                st.info("Tidak ada pool tersembunyi di lane ini.")
                return
            st.caption(
                f"{len(hidden_rows)} pool {label} disembunyikan ditampilkan "
                "· detail holder tidak diambil untuk kandidat ini.")
            # Sorot hijau tua menyala khusus tabel utama — listing dilewati
            # barisnya sudah dianotasi merah gugur-ambang.
            _render_best_table(hidden_rows, lane=active,
                               key_prefix=f"best-pool-hidden-{active}",
                               mark_tops=False)
            return
        if not rows:
            st.info(f"Tidak ada pool {label} yang lolos filter Best Pool "
                    "(atau listing kosong).")
            return
        _render_best_table(rows, lane=active,
                           key_prefix=f"best-pool-{active}")
