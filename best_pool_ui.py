# -*- coding: utf-8 -*-
"""Streamlit UI for the single 24H Meteora Best Pool scanner.

The table preserves every column on phones by using compact, horizontally
scrollable rows. The scan only enriches pool and market data.
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
    """Return the concise rule summary shown on the Best Pool title."""
    from meteora_screener import (BEST_ACTIVE_TVL_MIN, BEST_FEE_TVL_MIN,
                                  BEST_FV_24H_MIN, BEST_LPS_MIN,
                                  BEST_SOL_TOKEN_MIN_RATIO,
                                  BEST_TOKEN_SOL_RATIO_LABEL,
                                  BEST_TOP10_MAX_PCT, BEST_VOL_SHOW_MAX,
                                  BEST_VOL_SHOW_MIN)

    return (
        "Meteora DLMM 24H only. Active TVL must be at least "
        f"${BEST_ACTIVE_TVL_MIN:,.0f}; LPs at least {BEST_LPS_MIN:g}; "
        f"F/V at least {BEST_FV_24H_MIN:g}×; Fee/TVL at least "
        f"{BEST_FEE_TVL_MIN:g}%; volatility {BEST_VOL_SHOW_MIN:g}%–"
        f"{BEST_VOL_SHOW_MAX:g}%; and Top10 below {BEST_TOP10_MAX_PCT:g}%. "
        "After all cheap listing checks, the final distribution gate uses "
        "official Meteora pool-detail USD side values: SOL liquidity must be "
        f"at least {BEST_SOL_TOKEN_MIN_RATIO:g}× token liquidity "
        f"(token:SOL maximum {BEST_TOKEN_SOL_RATIO_LABEL}). Exact 1:2 and a "
        "more SOL-heavy ratio such as 1:6.52 pass; 1:1.5 fails. Missing, invalid, "
        "non-SOL, or non-positive side data fails closed. Passing rows then "
        "receive optional GMGN, RugCheck, and tax/dividend information. "
        "Columns include Active Range (for example -34.5% / +19.0%). "
        "On mobile the full table and all headers remain available by "
        "horizontal scrolling."
    )




# Relative desktop widths for the thirteen base columns.
_COL_SPEC = [1.4, 1.0, 0.75, 0.58, 0.95, 0.5, 0.58, 0.55, 0.68, 0.8,
             0.6, 1.0, 1.05]

#: Indeks kolom **Pool** di ``_COL_SPEC`` (kolom terakhir tabel "dilewati").
POOL_COL_INDEX = 12

#: Indeks kolom **STRATEGY** (paling kanan, hanya tabel utama) — tepat di
#: kanan ``POOL_COL_INDEX``. Sel strategi DITULIS langsung ke indeks ini,
#: bukan lewat ``enumerate(cells, start=1)`` yang hanya sampai kolom Pool
#: (permintaan user 2026-09-21: *"hybird 5050, bidask - full range — ini
#: taruh di kolom strategy, bukan di pool"*).
TAX_DIVIDEND_COL_INDEX = POOL_COL_INDEX + 1
TAX_DIVIDEND_COL_WIDTH = 1.15
TAX_DIVIDEND_COL_TITLE = "TAX/DIVIDEND"
STRATEGY_COL_INDEX = TAX_DIVIDEND_COL_INDEX + 1

#: Bobot kolom **STRATEGY** (paling kanan, hanya tabel utama — 2026-09-19).
STRATEGY_COL_WIDTH = 1.35


def _col_spec(*, show_strategy: bool = True) -> list[float]:
    """Return 13 base widths plus tax/dividend and strategy when shown."""
    spec = list(_COL_SPEC)
    if show_strategy:
        spec.append(TAX_DIVIDEND_COL_WIDTH)
        spec.append(STRATEGY_COL_WIDTH)
    return spec


def _lane_titles(lane, *, show_strategy: bool = True) -> list[str]:
    """Return headers in exactly the same order as the rendered cells."""
    from meteora_screener import normalize_best_lane

    # Satu judul volume saja: lane 30M dihapus 2026-09-16, window API selalu
    # 24 jam — ``normalize_best_lane`` masih menerima alias lama (dipetakan ke
    # 24H) jadi penamaan kolom tidak pernah bisa lagi tertulis "Vol 30m".
    _ = normalize_best_lane(lane)
    titles = ["Token", "F/V", "Fee/TVL", "Volat", "Active Range", "LPs",
              "Fee %", "MC", "A.TVL", "Vol 24h", "Top10",
              "RugCheck", "Pool"]
    if show_strategy:
        titles.append(TAX_DIVIDEND_COL_TITLE)
        titles.append("STRATEGY")
    return titles


# Hijau tua menyala penanda sel tertinggi di tabel utama (permintaan user
# 2026-09-14: "tandai volatility paling besar …" + "tandai f/v tertinggi …
# menjadi warna hijau menyala" + lanjutan: "yang paling tinggi nilainya kasih
# warna hijau menyala, hijau tua menyala" → F/V, Fee/TVL, Volat tertinggi
# semua memakai satu warna hijau tua menyala). Dipakai sel Volat, sel F/V,
# dan sel Fee/TVL.
TOP_HIGHLIGHT_COLOR = "#15803d"


#: Hijau kolom **LPs** (permintaan user 2026-09-16: "LPs jika lebih dari 100,
#: kasih warna hijau jika tidak, tidak ada perubahan"). Strict: tepat 100 LP
#: masih hitam. Warna #16a34a = hijau yang sama dengan Δ volume naik / label
#: "OK" lama — sengaja BUKAN ``TOP_HIGHLIGHT_COLOR`` supaya penanda "tertinggi
#: di tabel" tetap punya artinya sendiri.
LP_GREEN_COLOR = "#16a34a"
LP_GREEN_MIN_LP = 100.0


#: Ukuran huruf judul kolom tabel (permintaan user 2026-09-19: *"agak
#: perbesar tulisan table semuanya ya, tapi tidak mempengaruhi tampilan"*).
#: Dulu ``0.72rem`` ditulis inline di :func:`_render_best_table`; sekarang
#: jadi konstanta yang **dipakai class ``.bp-col-title``** di
#: ``dashboard_components.render_styles`` — tes memastikan CSS-nya memakai
#: nilai ini, jadi menaikkan ukuran huruf cukup mengubah satu angka di sini.
#: Kenaikannya sengaja kecil (0.72 → 0.82rem) dan hanya menyangkut ukuran
#: huruf: lebar kolom (``_COL_SPEC``), jumlah kolom, garis pembatas, dan tinggi
#: baris tidak berubah — judul tetap satu baris karena ``white-space:nowrap``
#: di class-nya. Ukuran huruf ISI sel (nilai + baris kecil + tautan) ikut
#: dinaikkan di CSS yang sama lewat class ``.watchlist-*``/``.pool-links``.
HEADER_FONT_SIZE = "0.82rem"


def _top_span(text: str) -> str:
    """Bungkus isi sel dengan hijau tua menyala + bold — penanda tertinggi tabel."""
    return (f'<span style="color:{TOP_HIGHLIGHT_COLOR};font-weight:800;">'
            f'{text}</span>')


#: Judul kolom STRATEGY (permintaan user 2026-09-19, huruf besar semua).
STRATEGY_COL_TITLE = "STRATEGY"


def _strategy_cell_html(text: str) -> str:
    """Isi sel **STRATEGY**: teks verbatim user, dipenggal sebelum ``- full``.

    Teksnya panjang untuk satu kolom (``hybird 7030, bidask 3070 - full
    range``), jadi frasa ``- full range`` dijaga tetap utuh (``nowrap`` lewat
    class ``.bp-strategy-range`` di ``dashboard_components.render_styles``)
    sementara bagian depannya boleh melipat — supaya kolomnya tidak perlu
    dilebarkan (permintaan user 2026-09-19: *"agak perbesar tulisan table
    semuanya ya, tapi tidak mempengaruhi tampilan"*: tampilan/lebar kolom
    tetap, hanya ukuran huruf yang naik). Tanpa pemisah `` - `` teksnya
    ditulis apa adanya.
    """
    import html as _html

    body = str(text or "")
    if not body:
        return "—"
    head, sep, tail = body.rpartition(" - ")
    if not sep:
        return _html.escape(body)
    # ``rpartition`` memisahkan " - " sehingga ``head`` berakhir tanpa spasi
    # dan ``sep`` memuat spasinya: spasi tunggal di dalam span nowrap supaya
    # frasa "- full range" tidak pernah terpenggal di tengah.
    return (f'{_html.escape(head)}<span class="bp-strategy-range">'
            f'{_html.escape(sep + tail)}</span>')


def _tax_dividend_cell_html(info: dict) -> str:
    """Isi sel **TAX/DIVIDEND**. Kata ``dividend`` diwarnai; sisanya di-escape.

    Tanpa data → ``—`` (bukan sel kosong). Pajak saja tidak memakai class
    ``bp-dividend``, supaya tes bisa membedakan \"ada pajak\" dari \"ada
    dividend yang mengubah STRATEGY\".
    """
    import html as _html

    label = str((info or {}).get("label") or "—")
    if not (info or {}).get("dividend") or "dividend" not in label:
        return f'<span class="bp-tax-dividend">{_html.escape(label)}</span>'
    parts = label.split("dividend")
    body = '<span class="bp-dividend">dividend</span>'.join(
        _html.escape(part) for part in parts)
    return f'<span class="bp-tax-dividend">{body}</span>'


def _tax_dividend_cell(row) -> tuple[str, str, str]:
    """Sel **TAX/DIVIDEND** (kiri STRATEGY, tabel utama saja).

    Angka dan flag-nya satu sumber di :func:`token_tax.row_tax_dividend`.
    Pajak transfer tidak mengubah STRATEGY; hanya ``dividend is True`` yang
    memakai teks ``30 70 spotbidask full range``. Belum terbaca → ``—``,
    baris tetap tampil.
    """
    from token_tax import row_tax_dividend

    info = row_tax_dividend(row)
    return _tax_dividend_cell_html(info), str(info.get("sub") or "—"), str(
        info.get("reason") or "")


def _strategy_cell(row) -> tuple[str, str, str]:
    """Sel **STRATEGY** (paling kanan, tabel utama) + bukti di baris kecil.

    Permintaan user (verbatim, 2026-09-19): *"Kasih kolom baru dipaling kanan
    STRATEGY — jika total likuiditas >500K, dikolom strategy ditulis, hybird
    7030, bidask 3070 - full range — jika total likuiditas <500K, dikolom
    strategy ditulis, hybird 5050, bidask - full range"*.

    Aturannya tidak disalin di sini: teks + ambangnya tinggal dibaca dari
    :func:`gmgn_liquidity.row_strategy` (satu sumber dengan warna likuiditas
    kolom RugCheck), dan angka pembandingnya pun angka yang sama dengan yang
    ditulis kolom RugCheck (:func:`gmgn_liquidity.row_total_liquidity_usd`) —
    jadi STRATEGY tidak pernah menyarankan 70/30 untuk baris yang angka
    likuiditasnya tampil merah. Baris kecil menulis angka likuiditas +
    ambangnya (``$884.9K > $500K``) supaya sarannya bisa diverifikasi sekali
    lihat; likuiditas tak terukur menulis ``liq —`` dan alasannya ada di
    tooltip (kolom informasi: tidak pernah membuang baris, tidak pernah
    menulis sel kosong).
    """
    from gmgn_liquidity import MIN_LABEL, compact_usd, row_strategy

    info = row_strategy(row)
    value = _strategy_cell_html(info.get("text"))
    usd = info.get("usd")
    if info.get("dividend"):
        # Dividend mengalahkan cabang likuiditas. Baris kecil menulis
        # "dividend" supaya teks "30 70 spotbidask full range" tidak terlihat
        # seperti saran dari angka likuiditas.
        sub = "dividend"
        tip = (f"STRATEGY dari dividend: \"{info.get('text')}\" (teks verbatim). "
               f"{info.get('reason')}. Pajak transfer saja tidak memakai teks "
               "ini — hanya saran, baris tidak dibuang")
        return value, sub, tip
    sub = (f"liq {compact_usd(usd)} · {MIN_LABEL}" if usd is not None
           else f"liq — · {MIN_LABEL}")
    tip = (f"STRATEGY dari likuiditas total: {info.get('reason')} → "
           f"\"{info.get('text')}\" (teks verbatim permintaan user 2026-09-19; "
           f"saldo > {MIN_LABEL} ambil cabang 70/30, < {MIN_LABEL} ambil "
           "cabang 50/50; ambangnya sama dengan warna angka likuiditas kolom "
           "RugCheck) — hanya saran penempatan likuiditas, bukan saringan: "
           "barisnya tidak pernah dibuang karena kolom ini")
    if usd is None:
        tip += (" · likuiditas total tidak terbaca (GMGN/rugchecker.cc tidak "
                "menjawab) sehingga dipakai cabang di bawah ambang")
    return value, sub, tip


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
    """Build the Best Pool heading and visible/skipped count pills."""
    from dashboard_components import card_head_html
    from meteora_screener import BEST_CARD_TITLE

    label, color, gate = best_lane_detail(lane)
    pills = [f'<span class="lp-count" style="color:#ffffff;background:{color};">'
             f'{label} · {gate}</span>',
             f'<span class="lp-count">{len(rows)} pool</span>']
    # ``hidden`` = kandidat 24H yang gugur saringan layar; pool volatility 0
    # dibuang sebelum tabel (permintaan user: tidak ada pergerakan), jadi
    # jumlahnya tidak pernah ikut di sini.
    if hidden:
        tone = ("color:#1e3a8a;background:#bfdbfe;" if showing_hidden
                else "color:#334155;background:#e2e8f0;")
        pills.append(f'<span class="lp-count" style="{tone}">'
                     f"{hidden} disembunyikan</span>")
    return card_head_html(BEST_CARD_TITLE, pills, tooltip=best_pool_tooltip())


def _signed_pct(value) -> tuple[str, str]:
    """Persen dengan tanda +/− + warna (hijau naik, merah turun).

    Dipakai untuk **Δ volume** (baris kecil kolom Vol 24h) — rasio volume
    24 jam / active TVL adalah kunci urut KETIGA card (Fee/TVL lalu F/V di
    depannya sejak 2026-09-15), jadi angka volume + arah perubahannya tetap
    harus terbaca sekali lihat.
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


def _pct_full(value) -> str:
    """Persen **penuh** untuk tooltip sel F/V (``—`` bila tidak ada).

    Angka normal ditulis 2 desimal seperti sebelumnya (``40.00%``), tetapi
    persen yang sangat kecil tidak boleh dibulatkan jadi ``0.00%``: pool
    tenang bisa punya ``volatility`` 2,06e-09% (pool GOLD-XAUt0, dilaporkan
    user 2026-09-15 — justru angka itulah penyebab F/V-nya jutaan), dan
    ``0.00%`` di tooltip membuat pembacanya tidak bisa memverifikasi apa pun.
    Di bawah 0,005% nilainya ditulis 3 angka penting (``2.06e-09%``).
    """
    number = _finite_number(value)
    if number is None:
        return "—"
    if number != 0 and abs(number) < 0.005:
        return f"{number:.3g}%"
    return f"{number:,.2f}%"


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


def _price_or_dash(value) -> str:
    """Harga bin mentah siap tampil (6 angka penting — harga memecoin kecil).

    Harga bin DLMM memecoin sering 1e-05, jadi ``.2f`` akan menulis ``0.00``;
    ``.6g`` tetap terbaca (``1.49369e-05``).
    """
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return "—"


def _range_part(value, *, down: bool) -> str:
    """Satu sisi **Active Range** dengan warna: turun merah, naik hijau.

    ``0.0%`` sengaja ditulis tanpa tanda dan tanpa warna — artinya harga
    persis di tepi range likuiditas (contoh nyata ROUTER-SOL 2026-09-14:
    ``min_price`` == ``pool_price``), dan ``+0.0%``/``-0.0%`` hanya
    membingungkan.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    signed = -number if down else number
    if abs(signed) < 0.05:
        return "0.0%"
    color = "#dc2626" if signed < 0 else "#16a34a"
    return f'<span style="color:{color};">{signed:+.1f}%</span>'


def _active_range_cell(row) -> tuple[str, str, str]:
    """Sel **Active Range**: ``-34.5% / +19.0%`` (turun / naik) + lebar range.

    Persen saja sesuai permintaan user 2026-09-14 ("tambahkan Active Range,
    tapi % saja, misal -30% +40"); harga bin mentah, lebar range, dan jumlah
    bin yang berisi likuiditas tetap ada di tooltip sel. Baris lama di
    ``session_state`` (hasil scan sebelum kolom ini ada) atau pool yang
    payload-nya tanpa ``pool_price``/``min_price``/``max_price`` → ``—``,
    bukan ``-0.0% / +0.0%`` palsu.
    """
    from meteora_screener import (active_range_bins, active_range_pct,
                                  active_range_width_pct)

    row = row or {}
    down, up = active_range_pct(row)
    if down is None or up is None:
        return ("—", "range",
                "active range tidak terbaca — hasil scan sebelum kolom ini "
                "ada (2026-09-14) atau API Meteora tidak mengirim pool_price / "
                "min_price / max_price untuk pool ini; tekan tombol scan lagi")
    value = (f"{_range_part(down, down=True)} / "
             f"{_range_part(up, down=False)}")
    width = active_range_width_pct(row)
    sub = f"lebar {_pct_or_dash(width)}" if width is not None else "range"
    bins = active_range_bins(row)
    bins_txt = (f"{bins[0]} bin berisi likuiditas ({bins[1]} bin di bawah "
                f"harga, {bins[2]} bin di atasnya) · bin_step "
                f"{_num_or_dash(row.get('bin_step'), '.4g')} bp"
                if bins else "")
    tip = ("active range = rentang bin DLMM yang masih berisi likuiditas "
           f"(min_price … max_price API Meteora): harga boleh turun "
           f"{_pct_or_dash(down)} atau naik {_pct_or_dash(up)} dari harga "
           f"pool sekarang ({_price_or_dash(row.get('pool_price'))}) sebelum "
           "keluar range — di luar itu posisi LP berhenti menghasilkan fee · "
           f"lebar range {_pct_or_dash(width)} · tepi "
           f"{_price_or_dash(row.get('range_min_price'))} … "
           f"{_price_or_dash(row.get('range_max_price'))}"
           + (f" · {bins_txt}" if bins_txt else "")
           + " — informasi, bukan saringan")
    return value, sub, tip


def _fv_cell(row: dict, lane: str, *, top: bool = False) -> tuple[str, str, str]:
    """Build one F/V cell, including the failure reason or top highlight."""
    from meteora_screener import (format_fv_ratio, row_best_final_gaps,
                                  row_fv_ratio)

    ratio = row_fv_ratio(row)
    label, _, gate = best_lane_detail(lane)
    fails = row_best_final_gaps(row, lane=lane)
    value = format_fv_ratio(ratio)
    sub = f"syarat {gate}"
    if value is None:
        value, color = "—", "#dc2626"
    else:
        # Angka (atau ∞ warisan hasil scan lama): tanpa warna khusus —
        # penanda hijau hanya untuk F/V tertinggi tabel (``top``).
        color = ""
    tip = (f"fee_active_tvl_ratio {_pct_full(row.get('fee_active_tvl_ratio'))}"
           f" ÷ volatility {_pct_full(row.get('volatility'))} = "
           f"{_num_or_dash(ratio, ',.2f')}× — "
           f"berapa kali fee pool lebih besar dari volatility; kunci urut "
           f"kedua listing {label} + syarat lane ({gate}); "
           "lebih tinggi = fee lebih dominan")
    if fails:
        # Gugur F/V, volatility di luar 1%–10%, atau Top10 >= 20% — semuanya
        # dibaca dari satu sumber (row_best_gaps) supaya teks sel tidak pernah
        # ketinggalan aturan baru.
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
                       mark_tops: bool = True,
                       show_strategy: bool = True) -> None:
    """Render the complete Best Pool table.

    The visible table has all fifteen columns; the skipped table omits the two
    final informational columns. One ``.bp-table-scroll`` wrapper keeps its
    header and rows aligned while mobile users scroll horizontally.
    """
    import html

    import streamlit as st

    from dashboard_components import _number
    from links import external_links_html, pool_links_html
    from meteora_screener import (BEST_LPS_MIN, BEST_SOL_TOKEN_MIN_RATIO,
                                  BEST_TOP10_MAX_PCT, BEST_VOL_SHOW_MAX,
                                  BEST_VOL_SHOW_MIN,
                                  liquidity_distribution_label,
                                  normalize_best_lane, row_fv_ratio,
                                  row_pair_label, row_vol_tvl_ratio)
    # RugCheck = kolom baru 2026-09-16; fmt-nya tinggal di modul rugchecker
    # supaya card tidak pernah menebak struktur laporan API pihak ketiga.
    from rugchecker import cell_parts as _rug_cell_parts
    # Modul ``bubblemaps`` TIDAK diimpor lagi di sini (2026-09-19): kolom
    # Bubble Map dihapus, yang tersisa hanya tautan 🫧 dari ``links``
    # (permintaan user: "hapus tentang bubblemap, sisakan hyperlink ke
    # bubblemapnya saja"). URL tautannya dihitung dari mint, dengan fallback
    # ke URL yang tersimpan di hasil scan lama (``row["bubblemap"]["url"]``)
    # supaya baris hasil scan 2026-09-18 tetap mengarah ke map yang sama.

    titles = _lane_titles(lane, show_strategy=show_strategy)
    table_rows: list[str] = []
    top_vol, top_fv, top_fee_tvl = (_table_tops(rows) if mark_tops
                                     else (None, None, None))
    window_txt = ("30 menit" if normalize_best_lane(lane) == "30m"
                  else "24 jam")

    for index, row in enumerate(rows):
        ca = str(row.get("ca") or "")
        symbol = str(row.get("symbol") or "?").upper()
        pool = str(row.get("pool_address") or "")
        fee = row.get("fee")
        active_tvl = row.get("active_tvl")
        ratio = row.get("fee_active_tvl_ratio")
        distribution_report = row.get("liquidity_distribution") or {}
        distribution_ratio = liquidity_distribution_label(row)
        token_liq_usd = (distribution_report.get("token_value_usd")
                         if isinstance(distribution_report, dict) else None)
        sol_liq_usd = (distribution_report.get("sol_value_usd")
                       if isinstance(distribution_report, dict) else None)
        active_tvl_sub = (f"token:SOL {distribution_ratio}"
                          if distribution_ratio != "—" else "active tvl")
        distribution_tip = (
            f" · distribusi nilai USD token {_usd_or_dash(token_liq_usd, compact=False)} "
            f": SOL {_usd_or_dash(sol_liq_usd, compact=False)} = "
            f"{distribution_ratio} (filter akhir: SOL minimal "
            f"{BEST_SOL_TOKEN_MIN_RATIO:g}× token)"
            if distribution_ratio != "—" else
            " · distribusi token:SOL tidak tersedia")
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
        # Sorot hijau tua menyala: F/V tertinggi, volatility terbesar, dan
        # Fee/TVL tertinggi tabel ini (permintaan user 2026-09-14 lanjutan).
        fv_here = row_fv_ratio(row)
        fv_top = bool(top_fv is not None and fv_here is not None
                      and fv_here == top_fv)
        fv_value, fv_sub, fv_tip = _fv_cell(row, lane, top=fv_top)
        vol_value = _pct_or_dash(row.get("volatility"))
        vol_tip = ("volatility pool "
                   f"{_num_or_dash(row.get('volatility'), ',.2f')}% — "
                   "saringan sejak 2026-09-16: hanya "
                   f"{float(BEST_VOL_SHOW_MIN):g}%–{float(BEST_VOL_SHOW_MAX):g}%"
                   " yang ditampilkan (inklusif; 0% dibuang total sejak "
                   "2026-09-14)")
        vol_here = _finite_number(row.get("volatility"))
        if top_vol is not None and vol_here is not None and vol_here == top_vol:
            vol_value = _top_span(vol_value)
            vol_tip += " — volatility terbesar di tabel ini"
        fee_tvl_value = _pct_or_dash(ratio)
        fee_tvl_tip = (f"tier fee {_num_or_dash(fee_pct, '.4g')}% · fee "
                       f"{window_txt} {_usd_or_dash(fee, compact=False)} / "
                       f"active TVL {_usd_or_dash(active_tvl, compact=False)} "
                       f"= {_num_or_dash(ratio, ',.2f')}% — kunci urut "
                       "pertama (terbesar dulu, permintaan user 2026-09-15), "
                       "bukan saringan")
        fee_tvl_here = _finite_number(ratio)
        if (top_fee_tvl is not None and fee_tvl_here is not None
                and fee_tvl_here == top_fee_tvl):
            fee_tvl_value = _top_span(fee_tvl_value)
            fee_tvl_tip += " — Fee/TVL tertinggi di tabel ini"
        pair = row_pair_label(row)
        pair_html = (
            f'<span class="watchlist-pair" title="pasangan pool '
            f'(nama pool dari API Meteora)">{html.escape(pair)}</span>'
            if pair else "")
        token_html = (
            '<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'{pair_html}'
            f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(ca)}</div>'
            "</div>")
        # Cell order follows ``_lane_titles``; Token was rendered above.
        # Sel **LPs** (2026-09-16, permintaan user: "LPs jika lebih dari 100,
        # kasih warna hijau jika tidak, tidak ada perubahan") — hanya warnanya
        # yang berubah, angkanya tetap angka pool dari API Meteora.
        lps_here = _finite_number(row.get("total_lps"))
        lps_value = _num_or_dash(row.get("total_lps"))
        if lps_here is not None and lps_here > LP_GREEN_MIN_LP:
            lps_value = (f'<span style="color:{LP_GREEN_COLOR};'
                         f'font-weight:700;">{lps_value}</span>')
        # Kolom **RugCheck** (baru 2026-09-16): verdict dari rugchecker.cc +
        # likuiditas **total GMGN** (sejak 2026-09-17 — sumber angkanya
        # dipindah ke gmgn.ai, permintaan user), ditempel scan_best_lane
        # lewat modul ``rugchecker`` (angka GMGN-nya: modul ``gmgn_liquidity``).
        # Hanya verdict yang diwarnai (hijau→merah) — angka likuiditas ikut
        # diwarnai sejak 2026-09-17: HIJAU di atas ambang $500K, MERAH di
        # bawahnya (permintaan user), hitam bila tidak terukur. Warnanya
        # dihitung rugchecker.cell_parts lewat gmgn_liquidity.liq_color.
        rug_report = row.get("rugcheck") or {}
        rug_value, rug_sub, rug_tip = _rug_cell_parts(rug_report)
        rug_color = str(rug_report.get("color") or "") if isinstance(rug_report, dict) else ""
        if rug_color and rug_value != "—":
            rug_value = (f'<span style="color:{rug_color};font-weight:700;">'
                         f'{rug_value}</span>')
        cells = (
            (fv_value, fv_sub, fv_tip),
            (fee_tvl_value, fee_sub, fee_tvl_tip),
            (vol_value, "volat", vol_tip),
            _active_range_cell(row),
            (lps_value, "lps",
             f"jumlah liquidity provider pool — saringan minimal "
             f"{BEST_LPS_MIN:g} LP (tepat {BEST_LPS_MIN:g} lolos); HIJAU bila "
             f"> {LP_GREEN_MIN_LP:g} LP"),
            (_num_or_dash(fee_pct, ".4g") + "%" if fee_pct is not None
             else "—", "pool fee",
             f"fee trading pool ini (tier fee pool DLMM) = "
             f"{_num_or_dash(fee_pct, '.4g')}% (mis. 0.5%, 2%) — "
             "hanya informasi, bukan saringan"),
            (_usd_or_dash(row.get("mc")), "",
             f"market cap {_usd_or_dash(row.get('mc'), compact=False)} — "
             "market cap reported by the Meteora listing"),
            (_usd_or_dash(active_tvl), active_tvl_sub,
             f"active TVL {_usd_or_dash(active_tvl, compact=False)} · "
             f"TVL total {_usd_or_dash(row.get('tvl'), compact=False)}"
             f"{distribution_tip}"),
            (_usd_or_dash(volume), delta_html,
             f"volume {window_txt} {_usd_or_dash(volume, compact=False)} · "
             f"perubahan {delta_txt} · rasio volume/active TVL "
             f"{_num_or_dash(vol_tvl_ratio, ',.2f')}% — kunci urut ketiga "
             "(terbesar dulu; setelah Fee/TVL & F/V), informasi "
             "(bukan saringan)"),
            (_pct_or_dash(row.get("top_holders_pct")), "top10",
             "10 akun teratas token base (% of supply) — saringan sejak "
             f"2026-09-16: Top10 **{BEST_TOP10_MAX_PCT:g}% atau lebih** tidak "
             "ditampilkan (permintaan user: \"jika ada top 10 >= 20% jangan "
             "tampilkan\"; tanpa angka = tidak terukur, barisnya tetap "
             "tampil)"),
            (rug_value, rug_sub, rug_tip),
        )
        rendered = [token_html]
        rendered.extend(_cell(value, sub, tip) for value, sub, tip in cells)
        pool_html = pool_links_html(pool, mint=ca) or "<span>—</span>"
        rendered.append(f'<div class="pool-links">{pool_html}</div>')
        if show_strategy:
            tax_value, tax_sub, tax_tip = _tax_dividend_cell(row)
            rendered.append(_cell(tax_value, tax_sub, tax_tip))
            value, sub, tip = _strategy_cell(row)
            rendered.append(_cell(value, sub, tip))
        table_rows.append("<tr>" + "".join(
            f'<td data-label="{html.escape(title, quote=True)}">{body}</td>'
            for title, body in zip(titles, rendered)) + "</tr>")

    header = "".join(
        f'<th scope="col"><div class="bp-col-title">{html.escape(title)}</div></th>'
        for title in titles)
    st.markdown(
        '<div class="bp-table-scroll" role="region" '
        'aria-label="Best Pool table" tabindex="0">'
        '<table class="bp-table"><thead><tr>' + header +
        '</tr></thead><tbody>' + "".join(table_rows) +
        '</tbody></table></div>',
        unsafe_allow_html=True)


def _lane_result(st, lane: str) -> dict:
    """Hasil scan tersimpan satu lane (dibaca dari session_state)."""
    return st.session_state.get(best_lane_session_key(lane)) or {}


def _run_lane_scan(lane: str) -> dict:
    """Run one Best Pool scan and convert an unexpected error to card data."""
    from meteora_screener import scan_best_lane

    try:
        return scan_best_lane(lane, workers=6, bubblemap=False)
    except Exception as exc:  # noqa: BLE001 - show scanner failure in the card
        return {"rows": [], "hidden_rows": [], "error": str(exc),
                "fetched": 0, "hidden_metric": 0, "skipped_quote": 0,
                "dropped_volatility": 0, "dropped_top10": 0,
                "dropped_lps": 0, "dropped_fv": 0, "dropped_total": 0,
                "failed_liquidity_ratio": 0,
                "liquidity_distribution_failed": 0,
                "liquidity_distribution_filter": True,
                "rugcheck_failed": 0, "bubblemap_failed": 0, "lane": lane}



def render_best_pool_scan() -> None:
    """Card **🏆 Scan Best Pool Meteora** di halaman utama — satu tombol 24H.

    Dulu card ini punya dua tombol + pemilih lane (24H dan 30M, aturan
    2026-09-13). Sejak 2026-09-16 hanya lane **24H** yang tersisa —
    permintaan user: *"hapus scan 30 menit, kita sisakan yang 24 jam saja"* —
    jadi satu tombol = satu listing API (``timeframe=24h``) = satu tabel,
    disimpan di satu session key ``best_pool_scan_24h`` (+ cache berkas dengan
    nama yang sama, lihat ``scan_result_cache``). Key lama per-lane lain
    (``best_pool_scan_30m``) dan key gabungan lama (``best_pool_scan``) tidak
    pernah dibaca lagi, jadi hasil 30M tidak bisa lagi menyusup ke tabel.
    """
    import streamlit as st

    from meteora_screener import (BEST_ACTIVE_TVL_MIN, BEST_FEE_TVL_MIN,
                                  BEST_LPS_MIN, BEST_SOL_TOKEN_MIN_RATIO,
                                  BEST_TOKEN_SOL_RATIO_LABEL, best_gap_summary,
                                  gmgn_min_label,
                                  normalize_best_lane, row_best_dropped,
                                  row_best_final_gaps, row_volatility_zero,
                                  sort_best_rows, sort_hidden_best_rows)

    with st.container(border=True):
        active = normalize_best_lane("24h")
        # Bersihkan state pemilih lane lama supaya sesi yang masih menyimpan
        # "30m" tidak bisa memengaruhi apa pun.
        st.session_state.pop(BEST_ACTIVE_LANE_KEY, None)

        # Pulihkan hasil scan dari cache berkas lokal bila session_state kosong
        # — Streamlit membuat session baru setiap refresh browser (F5) / tab
        # baru, sehingga tanpa ini listing yang sudah selesai
        # ikut hilang dan user harus menekan tombol scan lagi. Cache diisi
        # ``scan_result_cache.save_result`` sesudah scan (lihat bawah).
        try:
            import scan_result_cache

            scan_result_cache.restore_into_session(
                st, best_lane_session_key(active), best_lane_session_key(active))
        except Exception:  # noqa: BLE001 - cache hanya pelengkap
            pass

        # ---- satu tombol deteksi: 24H -------------------------------------
        label, _color, gate = best_lane_detail(active)
        if st.button(f"🏆 Scan Best Pool {label}", type="primary",
                     key=f"best-pool-scan-{active}",
                     use_container_width=True,
                     help=(f"Listing Meteora timeframe {label}, disaring "
                           f"{gate} + active TVL ≥ "
                           f"${BEST_ACTIVE_TVL_MIN / 1000:g}K + LPs ≥ "
                           f"{BEST_LPS_MIN:g} + volatility 1%–10% + Top10 < 20% "
                           f"+ Fee/TVL ≥ {BEST_FEE_TVL_MIN:g}%. Filter terakhir "
                           f"wajib nilai USD SOL minimal "
                           f"{BEST_SOL_TOKEN_MIN_RATIO:g}× token (token:SOL "
                           f"maksimal {BEST_TOKEN_SOL_RATIO_LABEL}). Semua dijalankan "
                           "sebagai tahap akhir setelah filter murah. Kandidat "
                           "yang gagal langsung dilewati. F/V "
                           "di bawah 2× dibuang total (tidak muncul di "
                           "'dilewati' maupun di mana pun). Tiap "
                           "pool yang lolos dilengkapi laporan RugCheck "
                           "(verdict rugchecker.cc, angka likuiditas GMGN — "
                           "sejak 2026-09-17) dan kolom STRATEGY di paling "
                           "kanan (saran penempatan likuiditas dari ambang "
                           f"{gmgn_min_label()} — sejak 2026-09-19) plus "
                           "kolom TAX/DIVIDEND di kirinya (pajak transfer + "
                           "mode reward; dividend menulis "
                           "30 70 spotbidask full range).")):
            with st.spinner("Memindai listing dan detail pool Meteora…"):
                result = _run_lane_scan(active)
            st.session_state[best_lane_session_key(active)] = result
            st.session_state[best_lane_hidden_key(active)] = False
            # Tahan refresh browser: simpan hasil ke cache berkas lokal
            # (2026-09-14). Gagal tulis tidak boleh membatalkan hasil scan.
            try:
                import scan_result_cache

                scan_result_cache.save_result(best_lane_session_key(active),
                                              result)
            except Exception:  # noqa: BLE001 - cache hanya pelengkap
                pass
            st.rerun()
        # Rekap hasil tersimpan di bawah tombol (aturan card sejak 2026-09-13:
        # tombol menunjukkan apa yang sudah ada tanpa memindai ulang) — dengan
        # satu lane cukup satu baris, tidak lagi per tombol.
        stored = _lane_result(st, active)
        st.caption(f"{len(stored.get('rows') or [])} pool tersimpan" if stored
                   else "belum di-scan")

        # ---- isi tabel ----------------------------------------------------
        result = _lane_result(st, active)
        error = str(result.get("error") or "")
        if not result:
            st.markdown(_best_head_html([], 0, active),
                        unsafe_allow_html=True)
            st.info(f"Belum ada hasil scan lane {label}. Tekan tombol "
                    f"🏆 Scan Best Pool {label} untuk memindai "
                    "listing terbaru.")
            return
        # ``scan_best_lane`` sudah mengurutkan, tapi hasil lama di
        # ``session_state`` (dari kriteria versi sebelumnya) belum —
        # diurutkan lagi dengan rule baru agar listing konsisten tanpa perlu
        # scan ulang (kolom yang dibutuhkan sort ada di baris lama juga).
        stored_rows = result.get("rows") or []
        newly_hidden = [
            dict(r, best_gaps=row_best_final_gaps(
                r, lane=active))
            for r in stored_rows
            if row_best_final_gaps(r, lane=active)
        ]
        # Pool yang gugur karena Top10 atau volatility dibuang total di sini
        # (permintaan user: "hasil yang gugur karena gugur: Top10, gugur:
        # volatility langsung sembunyikan total, tidak ditampilkana dimanapun")
        # — filter render supaya hasil scan LAMA yang masih membawanya di
        # ``rows`` atau di ``hidden_rows`` ikut bersih tanpa scan ulang.
        stored_rows = [r for r in stored_rows
                       if not row_best_dropped(r, lane=active)]
        rows = sort_best_rows([
            r for r in stored_rows
            if not row_best_final_gaps(
                r, lane=active)
        ])
        hidden_rows = sort_hidden_best_rows(
            [r for r in (result.get("hidden_rows") or []) + newly_hidden
             if not row_best_dropped(r, lane=active)])
        # ``hidden`` dihitung dari listing yang benar-benar bisa dilihat
        # (bukan counter mentah ``hidden_metric`` dari scan lama, yang masih
        # bisa menghitung pool vol/Top10 gugur), jadi pill/tombol/caption selalu
        # cocok dengan isi tabel disembunyikan.
        hidden = len(hidden_rows)
        fetched = int(result.get("fetched") or 0)
        skipped_quote = int(result.get("skipped_quote") or 0)
        rug_failed = int(result.get("rugcheck_failed") or 0)
        showing_hidden = bool(
            st.session_state.get(best_lane_hidden_key(active)))

        # Tanpa caption ambang: detail karakteristik card sudah jadi tooltip
        # judul (``best_pool_tooltip()``) — permintaan user 2026-09-10.
        st.markdown(_best_head_html(rows, hidden, active,
                                    showing_hidden=showing_hidden),
                    unsafe_allow_html=True)
        if hidden:
            # Caption/tombol = angka rekap saja; ambangnya hidup di tooltip
            # (judul card + tooltip sel F/V) — aturan card sejak 2026-09-10.
            view = ("◀ kembali ke tabel yang lolos"
                    if showing_hidden else f"▶ {hidden} pool dilewati")
            if st.button(view, key=f"best-pool-toggle-hidden-{active}",
                         help=f"Tampilkan kandidat {label} yang di-skip karena "
                              "gugur F/V (2×–5×), Fee/TVL, atau filter akhir "
                              f"SOL < {BEST_SOL_TOKEN_MIN_RATIO:g}× token "
                              f"(batas token:SOL {BEST_TOKEN_SOL_RATIO_LABEL}). "
                              "F/V di bawah 2× tidak ikut di sini — barisnya "
                              "dibuang total.",
                         use_container_width=True):
                st.session_state[best_lane_hidden_key(active)] = \
                    not showing_hidden
                st.rerun()
        if error:
            st.warning(f"Meteora API: {error}")
        gmgn_failed = int(result.get("gmgn_failed") or 0)
        ratio_failed = int(result.get("failed_liquidity_ratio") or 0)
        distribution_failed = int(
            result.get("liquidity_distribution_failed") or 0)
        tax_failed = int(result.get("tax_failed") or 0)
        if fetched:
            quote_txt = (f" · {skipped_quote} pool quote dilewati"
                         if skipped_quote else "")
            rug_txt = (f" · {rug_failed} mint tanpa laporan RugCheck"
                       if rug_failed else "")
            gmgn_txt = (f" · {gmgn_failed} likuiditas GMGN tak terbaca"
                        if gmgn_failed else "")
            ratio_txt = (
                f" · {ratio_failed} pool dengan SOL < "
                f"{BEST_SOL_TOKEN_MIN_RATIO:g}× token"
                if ratio_failed else "")
            distribution_txt = (
                f" · {distribution_failed} distribusi token:SOL tak terbaca/non-SOL"
                if distribution_failed else "")
            tax_txt = (f" · {tax_failed} tax/dividend tak terbaca"
                       if tax_failed else "")
            # Rekap "N tanpa Bubble Map" dihapus 2026-09-19 bersama kolomnya
            # (permintaan user: "hapus tentang bubblemap, sisakan hyperlink ke
            # bubblemapnya saja") — ``bubblemap_failed`` hasil scan lama
            # (session/cache 2026-09-18) sengaja tidak dibaca lagi supaya
            # caption tidak menyebut kolom yang sudah tidak ada.
            st.caption(f"{len(rows)} pool {label} tampil · {hidden} "
                       f"dilewati · listing {fetched} pool{quote_txt}"
                       f"{rug_txt}{gmgn_txt}{ratio_txt}{distribution_txt}{tax_txt}.")
        if showing_hidden:
            if not hidden_rows:
                st.info("Tidak ada pool tersembunyi di lane ini.")
                return
            st.caption(
                f"{len(hidden_rows)} pool {label} yang dilewati ditampilkan.")
            # Sorot hijau tua menyala khusus tabel utama — listing dilewati
            # barisnya sudah dianotasi merah gugur-ambang.
            # Tabel "dilewati" tanpa kolom STRATEGY (konfirmasi user
            # 2026-09-19: kolom baru itu hanya untuk tabel utama) — 13 kolom,
            # sama seperti sebelum STRATEGY ada.
            _render_best_table(hidden_rows, lane=active,
                               key_prefix=f"best-pool-hidden-{active}",
                               mark_tops=False, show_strategy=False)
            return
        if not rows:
            # Pesan kosong menyebut PENYEBABNYA (2026-09-17, laporan user
            # "poolnya kok jadi kosong"): rekap alasan gugur per kategori
            # + ajakan membuka daftar "dilewati" — user tidak perlu menebak
            # saringan mana yang membuang listing-nya.
            reason = best_gap_summary(hidden_rows)
            st.info(f"Tidak ada pool {label} yang lolos filter Best Pool "
                    "(atau listing kosong)."
                    + (f" {hidden} pool dilewati: {reason} — buka "
                       f"'▶ {hidden} pool dilewati' di atas untuk alasan "
                       "tiap baris." if reason else ""))
            return
        _render_best_table(rows, lane=active,
                           key_prefix=f"best-pool-{active}")
