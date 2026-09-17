# -*- coding: utf-8 -*-
"""Shared dashboard presentation; importing this module renders no page."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import html
import re
import streamlit as st

from holder_history import (DUST_CAUTION_PCT,
                            DUST_DANGER_PCT, INTERVAL_SEC,
                            LP_INTERVAL_SEC, history_for_mint,
                            merge_status_history, resample_4h,
                            usable_points)
from lp_watchlist import interval_label, lp_chart_figure
import alert_settings
from telegram_alerts import (delivery_note,
                             summarize_deliveries)
from watchlist_detail import (added_baseline,
                              baseline_note)


def render_styles() -> None:
    st.markdown("""
    <style>
    .main .block-container {max-width: 1280px; padding-top: 1.5rem;}
    html, body, p, span, div, label, li, td, th,
    h1, h2, h3, h4, h5, h6 {color:#000000;}
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p,
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"],
    [data-testid="stWidgetLabel"] p {color:#000000 !important;}
    .dust-badge {display:inline-block;padding:.28rem .58rem;border-radius:8px;
     font-size:.78rem;font-weight:800}
    .dust-ok {background:#14532d;color:#dcfce7}
    .dust-caution {background:#78350f;color:#fef3c7}
    .dust-danger {background:#7f1d1d;color:#fee2e2}
    .dust-none {background:#e2e8f0;color:#000000}
    .dust-best {background:#3b2f0a;color:#fde047;border:1px solid #facc15}
    /* Tulisan BEST emas berkelap-kelip di metrik Dust %MC section Scan Holder
       (2026-09-12, permintaan user: agak besar, kelap kelip, warna GOLD).
       Nama class-nya sengaja BUKAN varian `dust-best`: pin regression card
       Scan Meteora menghitung kemunculan string class chip emas itu di
       seluruh body halaman (tests/test_lp_card_ui.py, test_best_pool_scan.py)
       — CSS ini ikut ter-render di body, jadi namanya harus bebas substring
       tersebut. Semua gaya hidup di sini karena st.markdown men-sanitasi
       atribut style inline. */
    .scan-best-gold {display:inline-block;margin-top:.15rem;padding:.05rem .5rem;
     font-size:1.45rem;font-weight:900;letter-spacing:.1em;line-height:1.15;
     text-align:center;border-radius:8px;border:1px solid #b8860b;
     background-image:linear-gradient(100deg,#8a5a00 0%,#ffd700 22%,
      #fff6b0 42%,#ffd700 62%,#b8860b 100%);
     background-size:220% 100%;
     -webkit-background-clip:text;background-clip:text;
     -webkit-text-fill-color:transparent;color:transparent;
     text-shadow:0 0 6px rgba(255,215,0,.55),0 0 16px rgba(255,193,7,.35);
     animation:scan-best-blink 1.05s ease-in-out infinite,
      scan-best-shine 2.8s linear infinite;}
    .scan-best-gold::after {content:"🏆";margin-left:.3rem;font-size:.95rem;
     -webkit-text-fill-color:initial;color:initial;text-shadow:none;}
    /* Kelap-kelip: opacity (aman untuk background-clip:text — text-shadow
       ikut memudar sehingga emasnya benar-benar berkedip, bukan cuma glow). */
    @keyframes scan-best-blink {0%,100% {opacity:1} 50% {opacity:.32}}
    /* Kilau menyapu: gradien emasnya bergeser perlahan. */
    @keyframes scan-best-shine {from {background-position:0% 50%}
     to {background-position:220% 50%}}
    @media (prefers-reduced-motion: reduce) {
     .scan-best-gold {animation:none;opacity:1}
    }
    .lp-head {display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;
     padding:.5rem 0 .1rem}
    .lp-title {font-size:1.15rem;font-weight:800;color:#000000}
    /* Judul card/section beralih tooltip (title="…") — hint visual halus. */
    .lp-title[title], .md-title-tip[title] {cursor:help;}
    .lp-count {font-size:.75rem;font-weight:700;color:#312e81;background:#e0e7ff;
     padding:.2rem .5rem;border-radius:999px}
    .lp-warn {font-size:.75rem;font-weight:700;color:#7f1d1d;background:#fee2e2;
     padding:.2rem .5rem;border-radius:999px}
    .lp-delta-up {color:#b91c1c;font-weight:800}
    .lp-delta-down {color:#15803d;font-weight:800}
    .watchlist-row {display:flex;align-items:center;padding:.75rem 0;
     border-bottom:1px solid #cbd5e1;}
    .watchlist-token {display:flex;flex-direction:column;gap:.25rem;}
    .watchlist-symbol {font-size:1.1rem;font-weight:800;color:#000000;}
    .watchlist-mint {font-size:.75rem;color:#000000;font-family:monospace;}
    .watchlist-links {display:flex;gap:.5rem;margin-top:.25rem;}
    .watchlist-links a {font-size:.75rem;color:#1d4ed8;font-weight:600;
     text-decoration:none;}
    .watchlist-links a:hover {color:#000000;text-decoration:underline;}
    .watchlist-holder-link {display:flex;align-items:center;justify-content:center;
     width:2rem;height:2rem;border:1px solid #cbd5e1;border-radius:.35rem;
     background:#ffffff;color:#000000;text-decoration:none;font-size:1rem;
     line-height:1;cursor:pointer;}
    .watchlist-holder-link:hover {background:#e0e7ff;border-color:#6366f1;
     color:#000000;text-decoration:none;}
    .watchlist-metric {text-align:center;}
    /* Pasangan pool di kolom Token listing 🏆 Scan Best Pool Meteora
       (permintaan user 2026-09-15: "kolom Token sekarang akan menunjukkan
       pasangan pairnya, misal ALLINU/SOL") — di bawah $SIMBOL, di atas
       alamat mint. Huruf monospace + agak tebal supaya pasangannya terbaca
       sebagai satu kesatuan (bukan dua ticker terpisah). */
    .watchlist-pair {font-size:.78rem;font-weight:800;color:#000000;
     font-family:monospace;letter-spacing:.01em;}
    .watchlist-metric-label {font-size:.65rem;color:#000000;text-transform:uppercase;
     letter-spacing:.04em;}
    .watchlist-metric-value {font-size:.95rem;font-weight:700;color:#000000;}
    .watchlist-metric-sub {font-size:.65rem;color:#000000;}
    .pool-links {display:flex;gap:.5rem;flex-wrap:wrap;justify-content:center;}
    .pool-links a {font-size:.75rem;color:#1d4ed8;font-weight:700;
     text-decoration:none;}
    .pool-links a:hover {color:#000000;text-decoration:underline;}
    /* Tombol 📋 copy link HawkFi di kolom Pool tabel 🏆 Scan Best Pool
       (permintaan user 2026-09-17: "tambahkan copy link hawkfi dibagian
       scan") — tampil sejajar tautan 🌊/🦅, tanpa bingkai tombol, dan
       kliknya murni JS clipboard (tidak memicu rerun Streamlit). */
    .pool-links .hawkfi-copy-btn {background:transparent;border:none;
     padding:0;margin:0;font-size:.8rem;line-height:1;cursor:pointer;}
    .pool-links .hawkfi-copy-btn:hover {transform:scale(1.15);}
    /* Garis vertikal pembatas antar kolom tabel 🏆 Scan Best Pool
       (permintaan user 2026-09-17: "batasi per kolom dengan garis naik
       turun"). Marker tak-kasatmata .bp-cols-next disisipkan tepat SEBELUM
       tiap st.columns tabel (header + baris data), lalu :has() menandai
       horizontal block milik tabelnya supaya hanya kolom tabel scan yang
       diberi border kanan. DOM Streamlit 1.61.1 (diverifikasi dari bundle
       frontend): markdown dibungkus div[data-testid="stElementContainer"],
       dan blok kolom div[data-testid="stHorizontalBlock"] adalah SAUDARA
       LANGSUNG-nya di dalam stVerticalBlock (blok TIDAK dibungkus
       stElementContainer); kolom di dalamnya ber-data-testid "stColumn"
       ("column" dicantumkan sebagai varian kedua untuk toleransi bila
       Streamlit di-upgrade/downgrade).
       Hanya layar > 768px: di mobile kolom tabel wrap menjadi card 2
       kolom, garis tegaknya menjadi acak-acakan. */
    .bp-cols-next {display:none;}
    @media (min-width: 769px) {
      div[data-testid="stElementContainer"]:has(.bp-cols-next) + div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:not(:last-child),
      div[data-testid="stElementContainer"]:has(.bp-cols-next) + div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:not(:last-child) {
        border-right: 1px solid #cbd5e1;
        padding-right: 0.45rem;
      }
    }
    /* Helper untuk menyembunyikan header tabel di mobile (dipakai best_pool_ui
       + temp_ui). Elemen marker .mobile-hide-next disisipkan sebelum header
       stHorizontalBlock, lalu header itu disembunyikan pada layar kecil. */
    .mobile-hide-next {display:none;}
    .desktop-only {display:block;}
    .mobile-only {display:none;}
    /* Cegah zoom gestur iOS yang aneh dan pastikan box-sizing rapi */
    html { -webkit-text-size-adjust: 100%; }
    *, *::before, *::after { box-sizing: border-box; }
    /* Pastikan chart/canvas/image tidak meluber di mobile */
    [data-testid="stImage"] img, canvas { max-width: 100% !important; height: auto !important; }
    /* Dataframe/table: scroll horizontal halus di mobile */
    [data-testid="stDataFrame"] > div, [data-testid="stTable"] { overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
    /* Depth tables wrapper jadi scroll di layar kecil */
    /* Semua tabel depth yang dirender via _depth_tables_html sudah flex-wrap, tapi tambahkan scroll bila masih sempit */
    /* ===== Mobile Friendly Overrides ===== */
    @media (max-width: 768px) {
      .main .block-container {
        max-width: 100% !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 0.85rem !important;
        padding-bottom: 1rem !important;
      }
      /* Typography responsif — clamp agar tidak terlalu besar di tablet */
      h1 { font-size: clamp(1.35rem, 5vw, 1.7rem) !important; line-height: 1.2 !important; word-break: break-word; }
      h2 { font-size: clamp(1.15rem, 4vw, 1.4rem) !important; line-height: 1.25 !important; }
      h3 { font-size: clamp(1.02rem, 3.6vw, 1.2rem) !important; }
      /* Marker header: sembunyikan header tabel di mobile.
         Marker dirender sebagai <div class="mobile-hide-next"> di dalam
         stMarkdownContainer; container markdown itu sendiri disembunyikan (0 tinggi),
         lalu horizontalBlock header setelahnya disembunyikan. :has() dipakai karena
         marker bersarang di dalam container. */
      div[data-testid="stMarkdownContainer"]:has(.mobile-hide-next) {
        display: none !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
      }
      div[data-testid="stMarkdownContainer"]:has(.mobile-hide-next) + div[data-testid="stHorizontalBlock"] {
        display: none !important;
      }
      /* Fallback untuk browser/dirender tanpa :has — marker sendiri punya class, jadi header tetap tersembunyi lewat sibling generic */
      .mobile-hide-next { display: none !important; }
      .desktop-only { display: none !important; }
      .mobile-only { display: block !important; }
      /* Gap antar blok vertikal lebih lega di mobile untuk tap */
      [data-testid="stVerticalBlock"] { gap: 0.85rem !important; }
      [data-testid="stVerticalBlock"] > div { width: 100%; }
      /* Horizontal block default: wrap jadi 2 kolom (grid) — card style */
      [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
        gap: 0.55rem !important;
        align-items: stretch !important;
      }
      [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        flex: 1 1 calc(50% - 0.55rem) !important;
        min-width: calc(50% - 0.55rem) !important;
        width: auto !important;
        max-width: none !important;
      }
      /* Form (CA input + tombol) harus vertikal penuh — bukan 2 kolom */
      [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: column !important;
        gap: 0.6rem !important;
      }
      [data-testid="stForm"] [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        flex: 1 1 100% !important;
        min-width: 100% !important;
        width: 100% !important;
      }
      /* Metric KPI (Holder Analytic 4 kolom): tetap 2 kolom biar ringkas */
      [data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 0.55rem 0.6rem !important;
      }
      [data-testid="stMetricLabel"] p { font-size: 0.72rem !important; white-space: normal !important; }
      [data-testid="stMetricValue"] { font-size: 1.05rem !important; }
      [data-testid="stMetricDelta"] { font-size: 0.72rem !important; }
      /* Header card pills wrap rapi */
      .lp-head { gap: 0.4rem !important; padding: 0.35rem 0 0.15rem !important; }
      .lp-title { font-size: 1.02rem !important; }
      .lp-count, .lp-warn { font-size: 0.68rem !important; padding: 0.18rem 0.44rem !important; }
      /* Watchlist token: alamat panjang wrap */
      .watchlist-symbol { font-size: 0.98rem !important; }
      .watchlist-mint { font-size: 0.66rem !important; word-break: break-all !important; }
      .watchlist-pair { font-size: 0.72rem !important; }
      .watchlist-metric-value { font-size: 0.88rem !important; }
      .watchlist-metric-sub { font-size: 0.6rem !important; }
      .watchlist-links a, .pool-links a { font-size: 0.7rem !important; }
      /* Pool links di mobile rata kiri biar tidak mengambang */
      .pool-links { justify-content: flex-start !important; gap: 0.35rem !important; }
      /* Setiap baris dengan banyak kolom (Best Pool 15 kolom & LP 11 kolom)
         jadikan card ber-border agar tiap token terpisah jelas saat wrap 2 kolom */
      [data-testid="stHorizontalBlock"]:has(> [data-testid="column"]:nth-child(n+6)) {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 0.7rem 0.55rem !important;
        box-shadow: 0 1px 4px rgba(15,23,42,0.06);
      }
      /* Kolom pertama (Token: symbol + pair + mint + links) bentang penuh di dalam card */
      [data-testid="stHorizontalBlock"]:has(> [data-testid="column"]:nth-child(n+6)) > [data-testid="column"]:first-child {
        flex: 1 1 100% !important;
        min-width: 100% !important;
        border-bottom: 1px solid #f1f5f9;
        padding-bottom: 0.45rem !important;
        margin-bottom: 0.15rem;
      }
      /* Kolom metric di dalam card sebaiknya tetap center tapi label lebih kecil */
      [data-testid="stHorizontalBlock"]:has(> [data-testid="column"]:nth-child(n+6)) .watchlist-metric {
        padding: 0.1rem 0;
      }
      /* Tombol aksi (⭐, 🔔/🔕, ✕, 📋, 🧮) lebih besar untuk jempol */
      .stButton > button, [data-testid="stFormSubmitButton"] > button {
        min-height: 44px !important;
        padding: 0.55rem 0.9rem !important;
        font-size: 0.9rem !important;
        border-radius: 10px !important;
      }
      /* Tombol kecil di baris watchlist (ikon) tetap tap-friendly */
      [data-testid="stHorizontalBlock"] .stButton > button {
        min-height: 42px !important;
        min-width: 42px !important;
      }
      /* Link holder 🧮 sebagai kotak juga lebih besar di mobile */
      .watchlist-holder-link {
        width: 2.6rem !important;
        height: 2.6rem !important;
        font-size: 1.15rem !important;
        border-radius: 0.5rem !important;
      }
      /* Expander & container border lebih tipis di mobile */
      [data-testid="stExpander"] { border-radius: 10px !important; }
      div[data-testid="stVerticalBlockBorderWrapper"] {
        padding: 0.7rem !important;
      }
      /* Caption lebih kecil agar tidak mendominasi */
      [data-testid="stCaptionContainer"] p {
        font-size: 0.76rem !important;
        line-height: 1.45 !important;
      }
      /* Plot matplotlib: kurangi margin & pastikan responsif */
      [data-testid="stPyplot"] { overflow-x: auto; }
      /* Tabs: bisa discroll horizontal di mobile */
      [data-testid="stTabs"] [role="tablist"] {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
        flex-wrap: nowrap !important;
        gap: 0.25rem;
      }
      /* Depth tables: dari flex row jadi column di mobile */
      /* Tabel yang dibungkus div flex-wrap: paksa column & scroll */
      /* Semua tabel depth HTML: buat wrapper bisa scroll horizontal */
      /* Selector umum untuk tabel di dalam markdown */
      div[data-testid="stMarkdownContainer"] table {
        display: block;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        max-width: 100%;
      }
      /* Pastikan blok markdown tidak membuat overflow horizontal */
      [data-testid="stMarkdownContainer"] { overflow-wrap: break-word; word-break: break-word; }
      /* Input & select: font 16px mencegah zoom otomatis iOS */
      input, select, textarea { font-size: 16px !important; }
      /* Sidebar di mobile: pastikan overlay penuh & tidak gepeng */
      [data-testid="stSidebar"] { width: 85vw !important; max-width: 320px !important; }
    }
    @media (max-width: 480px) {
      .main .block-container {
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
      }
      /* Pada layar sangat kecil, kebanyakan kolom jadi 1 kolom penuh, kecuali KPI metrics tetap 2 kolom */
      [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        flex: 1 1 100% !important;
        min-width: 100% !important;
      }
      /* KPI metrics (berisi stMetric) pertahankan 2 kolom agar 4 metric jadi 2x2 grid, bukan 4 baris tinggi */
      [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="column"] {
        flex: 1 1 calc(50% - 0.55rem) !important;
        min-width: calc(50% - 0.55rem) !important;
      }
      /* Header card: font lebih kecil lagi */
      .lp-title { font-size: 0.98rem !important; }
      /* Watchlist card di 480px: metric 2 kolom tadi sudah, tapi card dengan banyak kolom tetap 2 kolom biar tidak terlalu panjang */
      [data-testid="stHorizontalBlock"]:has(> [data-testid="column"]:nth-child(n+6)) > [data-testid="column"] {
        flex: 1 1 calc(50% - 0.55rem) !important;
        min-width: calc(50% - 0.55rem) !important;
      }
      [data-testid="stHorizontalBlock"]:has(> [data-testid="column"]:nth-child(n+6)) > [data-testid="column"]:first-child,
      [data-testid="stHorizontalBlock"]:has(> [data-testid="column"]:nth-child(n+6)) > [data-testid="column"]:last-child {
        flex: 1 1 100% !important;
        min-width: 100% !important;
      }
      /* Tombol di baris LP yang banyak (11 kolom) terakhir 4 ikon: buat 2+2 grid di 480px */
    }
    /* Fallback untuk browser tanpa :has() — pastikan tetap wrap walau card styling tidak aktif */
    @supports not selector(:has(*)) {
      @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] {
          flex-wrap: wrap !important;
        }
      }
    }
    /* Print-friendly: jangan potong card */
    @media print {
      .main .block-container { max-width: none !important; }
    }
    </style>
    """, unsafe_allow_html=True)


def _number(value, pattern=".1f"):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


def _compact(value, signed=False):
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if signed and n > 0 else ""
    if abs(n) >= 1e6:
        return f"{sign}${n / 1e6:.2f}M"
    if abs(n) >= 1e3:
        return f"{sign}${n / 1e3:.1f}K"
    return f"{sign}${n:,.0f}"


def _wib(ts):
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(hours=7)
    return when.strftime("%d %b %H:%M") + " WIB"


def _dust_badge_html(flag: dict) -> str:
    """Badge level dust (AMAN/HATI-HATI/BAHAYA) — **dihapus** 2026-09-13.

    Permintaan user: \"tulisan aman, hati2, bahaya dll terkait % dust hapus
    juga\". Return ``\"\"`` supaya pemanggil tidak perlu diubah — angka
    Dust %MC tetap tampil, hanya label level-nya yang hilang.
    """
    return ""


def _dust_best_html(flag: dict) -> str:
    """Chip 🏆 BEST POOL — **dihapus** 2026-09-13 per permintaan user.

    Selalu return ``""``. Permintaan user: "tulisan aman, hati2, bahaya
    dll terkait % dust hapus juga".
    """
    return ""


def _scan_best_mark_ok(dust_pct) -> bool:
    """True bila dust % MC **<= 0,035%** → tulisan emas **BEST** boleh tampil.

    Ambangnya satu sumber dengan tanda 🏆 BEST POOL di card **🏆 Scan Best
    Pool Meteora** (``meteora_screener.BEST_DUST_MARK_PCT``, 2026-09-12) —
    permintaan user 2026-09-12: "jika kondisi %dust <= 0.035 kasih tulisan
    BEST yang agak besar, dengan efek kelap kelip, warnanya GOLD" di section
    🛰 Scan Holder Solana. Batas **inklusif** (0,035 persis ikut
    ditandai); angka yang tidak terbaca (``None``/teks kosong) tidak pernah
    ditandai — tidak ada bukti. ``meteora_screener`` diimpor di dalam fungsi
    (pola ``best_pool_ui.best_pool_tooltip``) supaya impor modul UI ini tetap
    ringan dan bebas dependensi baru di level atas.
    """
    # Tulisan BEST emas **dihapus** 2026-09-13 per permintaan user:
    # "tulisan aman, hati2, bahaya dll terkait % dust hapus juga".
    return False


def _scan_best_badge_html(dust_pct, label: str = "BEST") -> str:
    """HTML tulisan BEST emas — **dihapus** 2026-09-13 per permintaan user.

    Selalu return ``""``. Permintaan user: "tulisan aman, hati2, bahaya
    dll terkait % dust hapus juga".
    """
    return ""


def _delta_pp_html(delta, digits: int = 2) -> str:
    """Perubahan dust % MC dalam poin persentase (merah bila naik)."""
    if delta is None:
        return '<span style="color:#64748b;">—</span>'
    try:
        value = float(delta)
    except (TypeError, ValueError):
        return '<span style="color:#64748b;">—</span>'
    cls = "lp-delta-up" if value > 0 else (
        "lp-delta-down" if value < 0 else "")
    text = f"{value:+.{digits}f} pp"
    return f'<span class="{cls}">{text}</span>' if cls else text


SOLANA_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _ca_error(value) -> str:
    """Pesan error validasi CA; string kosong bila address terlihat valid."""
    ca = str(value or "").strip()
    if not ca:
        return "Masukkan contract address terlebih dahulu."
    if not SOLANA_CA_RE.match(ca):
        return ("Format CA tidak valid. Solana: base58 32–44 karakter.")
    return ""


def _points_for(mint, token, store):
    return merge_status_history(history_for_mint(store, mint),
                                (token or {}).get("history") or [])


def _depth_tables_html(depth: dict) -> str:
    """Tabel Wallet Depth by Threshold + tier ala Solscan (HTML).

    Kolom **% Market Cap** memakai 3 desimal sejak 2026-09-12 (permintaan
    user — sama seperti Hold %MC watchlist dan grafik Scan Holder); bucket
    dust sering jauh di bawah 0,01% MC sehingga dua desimal selalu tampil
    ``0.00%``.
    """
    def _pct(item):
        pct = item.get("pct_mc")
        return "—" if pct is None else f"{float(pct):.3f}%"

    def _count(item):
        return "—" if item.get("count") is None else f"{int(item['count']):,}"

    bucket_rows = "".join(
        f"<tr><td>{html.escape(str(b.get('label') or ''))}</td>"
        f"<td style='text-align:center'>{_count(b)}</td>"
        f"<td style='text-align:right'>{_compact(b.get('value_usd'))}</td>"
        f"<td style='text-align:right'>{_pct(b)}</td></tr>"
        for b in (depth.get("buckets") or []))
    tier_rows = "".join(
        f"<tr><td>{html.escape(str(t.get('emoji') or ''))} "
        f"{html.escape(str(t.get('tier') or ''))}</td>"
        f"<td style='text-align:center'>{_count(t)}</td>"
        f"<td style='text-align:right'>{_compact(t.get('value_usd'))}</td>"
        f"<td style='text-align:right'>{_pct(t)}</td></tr>"
        for t in (depth.get("tiers") or []))
    style = ("border-collapse:collapse;font-size:.8rem;color:#000000;"
             "margin:0 .6rem .4rem 0;")
    th = "border:1px solid #cbd5e1;padding:.3rem .6rem;background:#f1f5f9;"
    td = "border:1px solid #cbd5e1;padding:.25rem .6rem;"
    return f"""
<div style="display:flex;flex-wrap:wrap;gap:1rem;">
<table style="{style}">
<thead><tr><th style="{th}">Range</th><th style="{th}">Holder</th>
<th style="{th}">Total Value</th><th style="{th}">% Market Cap</th>
</tr></thead><tbody>{bucket_rows}</tbody></table>
<table style="{style}">
<thead><tr><th style="{th}">Tier</th><th style="{th}">Holder</th>
<th style="{th}">Total Value</th><th style="{th}">% Market Cap</th>
</tr></thead><tbody>{tier_rows}</tbody></table>
</div>"""


def _render_depth(holders: dict, symbol: str) -> None:
    """Render Wallet Depth by Threshold dari data holder Helius."""
    depth = holders.get("depth") if isinstance(holders.get("depth"), dict) \
        else None
    if not depth:
        return
    with st.expander(f"📊 Wallet Depth by Threshold — ${symbol} "
                     "(Helius)", expanded=False):
        st.markdown(_depth_tables_html(depth), unsafe_allow_html=True)
        total_all = depth.get("holders_all")
        total_wallet = depth.get("holders_wallet")
        pool_n = int(depth.get("pool_excluded") or 0)
        if depth.get("buckets_include_pools"):
            bucket_line = (f"Bucket dihitung atas semua akun bernilai >$0 "
                           f"({total_all:,} akun, termasuk LP/pool)")
        else:
            bucket_line = (f"Bucket dihitung atas wallet murni saja "
                           f"({total_wallet:,} akun — {pool_n:,} akun "
                           f"LP/pool disingkirkan dari list holder)")
        st.caption(
            f"{bucket_line}; tier atas wallet murni "
            f"({total_wallet:,} wallet). Nilai USD = "
            f"balance × harga token saat scan (DexScreener)."
        )


def _dust_change_empty_note(interval: int) -> str:
    """Pesan bila grafik belum bisa digambar (< 2 bucket layak)."""
    label = interval_label(interval)
    if int(interval) <= LP_INTERVAL_SEC:
        return (f"Butuh minimal 2 titik bucket {label}. Cron watchlist LP "
                f"(tiap ±{label}) atau tombol **Scan sekarang** di card ini "
                "akan mengisinya.")
    return (f"Butuh minimal 2 titik bucket {label}. Scan beberapa kali "
            "(tombol scan di card ini / halaman Holder Analytic) supaya "
            f"bucket {label} terisi.")


def _render_dust_change(points, holders: dict, symbol: str, *,
                        interval: int = INTERVAL_SEC,
                        empty_note: str = "",
                        meta: dict | None = None,
                        current_pct=None) -> None:
    """Expander **📈 Grafik perubahan dust holder** ala Watchlist Meteora.

    Bentuk yang sama persis dengan expander grafik per token di card
    Watchlist Meteora (`app.py`, permintaan user 2026-09-10: semua card
    watchlist memakai grafik perubahan dust holder, bukan cuma tabel Wallet
    Depth): garis dust % MC + garis ambang HATI-HATI/BAHAYA, batang jumlah
    wallet dust, caption, lalu tabel **📊 Wallet Depth by Threshold**
    ter-nested di dalamnya bila scan menghasilkan ``depth``. ``interval`` =
    bucket resample (``LP_INTERVAL_SEC`` 5 menit untuk lane LP,
    ``INTERVAL_SEC`` 4 jam untuk watchlist biasa).

    ``meta`` (entri watchlist: ``added``/``symbol``) + ``current_pct``
    dipakai baris pertama detail: **dust % MC saat token pertama masuk
    watchlist** — patokan notifikasi ⚡ EARLY DUMP (permintaan user
    2026-09-13: *"pada detail watchlist, juga tunjukkan pertama kali saya
    menambahkan ke watchlist, posisi % dust di berapa %"*).
    """
    label = interval_label(interval)
    with st.expander(f"📈 Grafik perubahan dust holder — ${symbol}",
                     expanded=False):
        st.caption(baseline_note(added_baseline(meta, points),
                                 current_pct=current_pct))
        figure = lp_chart_figure(points, symbol, interval=interval)
        if figure is None:
            st.info(empty_note or _dust_change_empty_note(interval))
        else:
            import matplotlib.pyplot as plt  # lazy: module-level import
            # dashboard_components ikut di-import jalur non-UI.
            st.pyplot(figure, use_container_width=True)
            plt.close(figure)
        sampled = resample_4h(usable_points(points), interval=interval)
        st.caption(
            f"Garis = dust % marketcap · batang = jumlah wallet dust · "
            f"ambang HATI-HATI {DUST_CAUTION_PCT:g}% / BAHAYA "
            f"{DUST_DANGER_PCT:g}% · titik per {label} "
            f"({len(sampled)} bucket).")
        if isinstance((holders or {}).get("depth"), dict):
            _render_depth(holders, symbol)


def card_head_html(title: str, pills: list[str] | None = None,
                   tooltip: str = "") -> str:
    """Header card grid: judul tebal + pill ringkasan di sebelahnya.

    Dipakai card **Watchlist Meteora** (halaman utama) dan **🏆 Scan Best
    Pool Meteora** supaya card yang berkepala sama itu punya satu pembuat.
    ``tooltip`` (opsional) = detail
    karakteristik card yang HANYA muncul saat kursor berada di atas teks
    judul (atribut ``title`` native browser — permintaan user 2026-09-10
    supaya card tetap ramping, bukan caption panjang di badan card). Atribut
    ``title`` tidak mengenal markdown, jadi tulis plain text tanpa ``**``.
    """
    tip = f' title="{html.escape(tooltip)}"' if tooltip else ""
    chips = "".join(pills or [])
    return (f'<div class="lp-head"><span class="lp-title"{tip}>{title}'
            f"</span>{chips}</div>")


def hover_title_html(text: str, tooltip: str) -> str:
    """Judul section (heading markdown ``###``) dengan tooltip di teksnya.

    Pengganti caption panjang di bawah judul section (2026-09-10): detail
    hanya muncul saat kursor berada di atas teks judul — karena itu teksnya
    dibungkus ``<span title="…">``, bukan ditempel di seluruh lebar baris.
    Markdown ``###`` dipertahankan supaya styling sama persis dengan
    ``st.subheader``; atribut ``title`` tidak mengenal markdown (plain text).
    """
    return (f'### <span class="md-title-tip" title="{html.escape(tooltip)}" '
            f'style="cursor:help;">{html.escape(text)}</span>')


ALERT_NOTE_KEY = "manual_alert_note_"


def _store_alert_note(deliveries, key: str) -> None:
    """Simpan ringkasan kirim alert scan manual untuk ditampilkan setelah rerun.

    Tombol scan manual (Chart LP Meteora + watchlist biasa Solana) langsung
    ``st.rerun()`` setelah scan, jadi catatan hasil
    kirim harus lewat ``session_state`` — permintaan user 2026-09-09: hasil
    scan manual yang memenuhi syarat **ikut dikirim** ke Telegram, dan UI
    harus melaporkan apakah pesannya benar-benar keluar.
    """
    summary = summarize_deliveries(deliveries)
    if not summary.get("total"):
        st.session_state.pop(key, None)
        return
    st.session_state[key] = {"text": delivery_note(summary),
                             "failed": bool(summary.get("failed"))}


def _render_alert_note(key: str) -> None:
    """Tampilkan (sekali) catatan kirim alert scan manual di card."""
    note = st.session_state.pop(key, None)
    if not isinstance(note, dict):
        return
    text = str(note.get("text") or "").strip()
    if not text:
        return
    if note.get("failed"):
        st.warning(text)
    else:
        st.info(text, icon="🚨")


# ---------------------------------------------------------------------------
# Toggle alert Telegram **per token** (🔔/🔕 di tiap baris watchlist)
# ---------------------------------------------------------------------------
# Permintaan user 2026-09-11: *"kasih toggle alert on/off per token yang ada
# di watchlist meteora … jadi misal saya sudah tau ada notif,
# saya bisa nonaktifkan. tapi pas awal memasukkan ke watchlist, otomatis
# on"*. Pilihan user hidup di ``alert_settings.muted_mints`` (blocklist →
# default ON, dan ``watchlist`` membersihkan entri saat token di-add) supaya
# **cron** GitHub Actions ikut menghormatinya — bukan di ``watchlist.json``,
# yang punya jalur journal + merge sendiri.
ALERT_TOGGLE_NOTE_KEY = "alert_toggle_note_"


def _alert_toggle_label(alert_on: bool) -> str:
    """🔔 = notif menyala (klik untuk mematikan), 🔕 = sedang dimatikan."""
    return "🔔" if alert_on else "🔕"


def _alert_toggle_help(symbol: str, alert_on: bool) -> str:
    """Tooltip tombol 🔔/🔕 — menjelaskan apa yang terjadi, bukan rule-nya."""
    if alert_on:
        return (f"Matikan notif Telegram untuk ${symbol}: token tetap "
                "di-scan + grafiknya tetap jalan, hanya pesan 🚨 yang tidak "
                "dikirim. Token yang baru masuk watchlist selalu ON.")
    return (f"Nyalakan lagi notif Telegram untuk ${symbol} (default ON). "
            "Sinyal yang sudah lewat saat mati tidak dikirim ulang.")


def _muted_pill_html(muted: int) -> str:
    """Pill jumlah token yang notifnya dimatikan user (kosong bila 0)."""
    try:
        count = int(muted or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return ""
    return ('<span class="lp-count" style="color:#374151;background:#e5e7eb;">'
            f'🔕 {count}</span>')


def _store_toggle_note(scope: str, text: str) -> None:
    """Simpan catatan toggle untuk ditampilkan setelah rerun (per card)."""
    st.session_state[f"{ALERT_TOGGLE_NOTE_KEY}{scope}"] = str(text)


def _render_toggle_note(scope: str) -> None:
    """Tampilkan (sekali) catatan toggle di card pemiliknya."""
    text = st.session_state.pop(f"{ALERT_TOGGLE_NOTE_KEY}{scope}", None)
    if text:
        st.warning(text, icon="⚠️")


def _mint_alert_on(mint) -> bool:
    """True bila notif Telegram token ini menyala (default = ON)."""
    return not alert_settings.is_mint_muted(mint)


def _alert_toggle_button(column, mint: str, symbol: str, *, scope: str,
                         alert_on: bool) -> None:
    """Render tombol 🔔/🔕 satu baris; klik = simpan pilihan + rerun.

    ``scope`` menentukan awalan key (``lp`` / ``rh`` / ``rhreg``) sekaligus
    card pemilik catatan gagal-sinkron (``_render_toggle_note``) supaya
    peringatan tidak nyasar ke card lain di halaman yang sama.
    """
    if not column.button(_alert_toggle_label(alert_on),
                         key=f"{scope}-alert-{mint}",
                         help=_alert_toggle_help(symbol, alert_on),
                         use_container_width=True):
        return
    ok = alert_settings.set_mint_alert_enabled(mint, not alert_on)
    if not ok:
        _store_toggle_note(
            scope,
            f"Pilihan notif ${symbol} tersimpan di file lokal, tapi "
            "sinkronisasi ke GitHub gagal — cron mungkin masih memakai "
            "setelan lama.")
    try:
        import activity_log
        if ok:
            activity_log.info(
                "alert",
                f"Notif Telegram ${symbol} "
                f"{'dimatikan' if alert_on else 'dinyalakan'} "
                "(toggle per token)")
        else:
            activity_log.warn(
                "alert",
                f"Toggle notif ${symbol} tersimpan lokal, sinkron GitHub "
                "gagal — cron bisa masih memakai setelan lama")
    except Exception:  # noqa: BLE001 - log bersifat pelengkap
        pass
    st.rerun()


@dataclass
class DashboardData:
    watchlist: dict
    status: dict
    history: dict


def load_dashboard_data() -> DashboardData:
    """Read the existing Solana stores (watchlist + snapshot + history).

    No migration, rescan, or write occurs merely because a section moved to
    another page.
    """
    import holder_history as hh
    import holder_status as hs
    import watchlist as wl

    watch = wl.load_watchlist()
    force = bool(st.session_state.pop("status_force_refresh", False))
    status = hs.apply_manual_scan(
        hs.load_holder_status(force_refresh=force),
        st.session_state.get(hs.MANUAL_SCAN_KEY))
    history = hh.seed_from_status(hh.load_durable_holder_history(), status)
    return DashboardData(watch, status, history)
