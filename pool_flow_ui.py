# -*- coding: utf-8 -*-
"""UI main app: 🏆 Scan ALL (24H) dengan RINGKASAN (pool FEE PRINTER) di atas tabel FEE PRINTER, satu tombol SCAN ALL.

Logika ada di ``pool_flow.py``; modul ini hanya menampilkan hasil scan.
Scan tidak menulis berkas apa pun.

Tabel dibuat HTML dengan lebar minimum dan scroll horizontal (AGENTS.md,
"Mobile UI invariant": semua kolom tetap ada, tanpa kartu dan tanpa kolom
yang disembunyikan).
"""
from __future__ import annotations

import html as _html

import pool_flow as pf
from links import external_links_html, pool_links_html

RESULT_KEY = "pool_flow_result"
BUTTON_LABEL = "SCAN ALL"
# Warna tabel (permintaan user): FEE PRINTER biru. Nama warna untuk st.markdown.
SLOW_FEE_PRINTER_COLOR = "blue"  # warna border tabel (tidak dipakai untuk judul lagi)
FEE_PRINTER_TITLE_CLASS = "fee-printer-title"  # judul FEE PRINTER: hijau tua menyala, lihat dashboard_components.render_styles
SLOW_FEE_PRINTER_BORDER = "rgba(59,130,246,.85)"
DEFAULT_BORDER = "rgba(128,128,128,.35)"

TABLE_HEADERS = ["Token / pool", "TVL", "Fee tier", "Fee/volume",
                 "Volatility", "Fee/TVL", "Fee/active TVL", "Net deposit",
                 "Fee/active TVL ÷ volatility", "Avg volume/menit (pool)",
                 "Avg volume/menit ÷ TVL", "Avg fee/menit ÷ TVL",
                 "Volume 24H (pool)", "Peringatan keamanan"]

def _filter_caption() -> str:
    return ("Timeframe 24H · kategori top · dlmm · "
            "market cap ≥ $20.000 · holders ≥ 1.500 · TVL ≥ $30.000 · active TVL ≥ $10.000 · "
            "fee/TVL ≥ 1 · fee ≥ 0.5% · pool dibuat ≥ 24 jam lalu · "
            "tanpa konsentrasi/kepemilikan tunggal tinggi · "
            "FEE PRINTER: volatility ≤ 3% · fee/active TVL ≥ 2 × volatility · net deposit ≥ $10.000.")


def _render_scan_result(result: dict) -> None:
    import streamlit as st

    passing = result.get("passing") or []
    st.caption(
        f"Listing {result.get('listing_rows', 0)} baris · pool dievaluasi "
        f"{result.get('candidates', 0)} · ditampilkan {len(passing)} · "
        f"dicatat {result.get('scanned_at', '')}"
        + (f" · {result['listing_errors']} halaman listing gagal"
           if result.get("listing_errors") else ""))
    if result.get("truncated"):
        st.warning("Listing belum lengkap: pengambilan berhenti sebelum semua halaman "
                   f"terambil (batas {pf.FLOW_MAX_PAGES} halaman atau ada halaman gagal), "
                   "sebagian pool belum terambil.")
    if not passing:
        st.info("Tidak ada pool dari listing.")
        return
    st.caption("Geser tabel ke kanan untuk melihat semua kolom. Keamanan: pool dengan mint/freeze "
               "authority aktif atau top holders > 30 % dibuang; peringatan muncul bila top holders "
               "> 15 %, dev > 5 %, atau LP keluar lebih besar dari masuk saat TVL < $50K. "
               "Baris kuning = pool teratas (avg volume/menit ÷ TVL terbesar).")
    rows = pf.fee_printer_rows(passing)
    top = pf.most_crowded(result)
    top_pool = top["pool"] if top else None
    st.markdown(f'<span class="{FEE_PRINTER_TITLE_CLASS}">FEE PRINTER</span>', unsafe_allow_html=True)
    st.markdown(f"*· {len(rows)} pool · volatility 0,01–3 % · fee/active TVL ≥ 2 × volatility · "
                f"net deposit ≥ $10.000 · urut fee/active TVL ÷ volatility terbesar dulu*")
    _render_pool_table(rows, "Tidak ada pool untuk FEE PRINTER.", top_pool,
                       accent=SLOW_FEE_PRINTER_BORDER, builder=_fee_printer_table_html)


SUMMARY_HEADERS = ["Token / pool", "Asal tabel", "Fee tier", "Fee/volume", "Net deposit",
                   "Fee/active TVL", "Volatility", "Fee/active TVL ÷ volatility",
                   "Peringatan keamanan"]
SUMMARY_BORDER = "rgba(34,197,94,.85)"  # hijau: RINGKASAN (permintaan user, 2026-11-15)
# Badge asal tabel: warna sama dengan judul/border tabel di halaman.
_SUMMARY_BADGE = {
    # Badge FEE PRINTER: teks hijau tua menyala (iframe tidak memakai CSS app, jadi gaya inline).
    pf.SUMMARY_LABEL: ("background:rgba(59,130,246,.28);color:#14532d;font-weight:800;"
                            "text-shadow:0 0 6px rgba(34,197,94,.85),0 0 14px rgba(22,163,74,.5)"),
}


def _summary_table_html(entries: list) -> str:
    """RINGKASAN compact: token/pool, asal tabel, fee tier, fee/volume, net deposit, fee/active TVL, volatility, fee/active ÷ volatility, peringatan keamanan."""
    body = []
    for row, label in entries:
        badge = (f"<span style='{_SUMMARY_BADGE.get(label, '')};padding:2px 10px;"
                 f"border-radius:999px;font-weight:600;white-space:nowrap'>"
                 f"{_html.escape(label)}</span>")
        cells = [
            _cell_token_html(row),
            badge,
            _html.escape(f"{row['fee_tier']:g}%" if row.get("fee_tier") is not None else "—"),
            _html.escape(pf.fmt_pct2(pf.fee_volume_pct(row))),
            _html.escape(pf.fmt_usd(row.get("net_deposits"))),
            _html.escape(pf.fmt_pct2(row.get("fee_active_tvl"))),
            _html.escape(pf.fmt_pct2(row.get("volatility"))),
            _html.escape(pf.fmt_times_plain(pf.fee_active_per_volatility(row))),
            _html.escape("; ".join(row.get("warnings") or []) or "—"),
        ]
        body.append((cells, False))
    return _table_html(SUMMARY_HEADERS, body, SUMMARY_BORDER)


def _render_summary(result: dict) -> None:
    import streamlit as st

    entries = pf.summary_rows(result)
    st.markdown("**:green[RINGKASAN]**")
    st.caption("Hanya pool dari tabel FEE PRINTER (di bawah), satu baris per pool.")
    if not entries:
        st.info("Belum ada pool yang memenuhi kriteria ringkasan.")
        return
    document = ("<!doctype html><html><head><meta charset=\"utf-8\">"
                f"<style>{_COPY_CSS}</style></head><body>"
                f"{_summary_table_html(entries)}{_COPY_SCRIPT}</body></html>")
    st.iframe(document, height="content", width="stretch")


def _render_pool_table(rows: list, empty_text: str, top_pool: str | None = None,
                       accent: str = DEFAULT_BORDER, builder=None) -> None:
    import streamlit as st

    if not rows:
        st.info(empty_text)
        return
    # st.iframe (bukan components.v1.html): HTML dirender di iframe agar tombol copy CA bisa berjalan.
    # height="content": iframe mengikuti tinggi tabel (tanpa ruang kosong di bawah tabel, 2026-11-18).
    st.iframe(_result_document(rows, top_pool, accent, builder=builder),
              height="content", width="stretch")


def _table_html(headers: list, body: list, accent: str, *, align: list | None = None,
                readable: bool = False) -> str:
    """Pembungkus tabel HTML. ``body`` = [(sel-sel teks HTML, baris_teratas)].

    ``readable`` (tabel SLOW, permintaan user 2026-11-23): judul boleh turun baris, angka rata
    kanan dengan digit sejajar, kolom Token menempel saat digeser, dan baris belang.
    """
    align = align or ["left"] * len(headers)
    if readable:
        head_bg, zebra_bg = "#f1f5f9", "#f8fafc"
        th_base = ("padding:8px 10px;font-weight:600;vertical-align:bottom;white-space:normal;"
                   "min-width:78px;border-bottom:2px solid rgba(128,128,128,.45);background:"
                   + head_bg)  # latar judul; sel Token (sticky) memakai latar yang sama
    else:
        th_base = ("padding:6px 8px;white-space:nowrap;"
                   "border-bottom:1px solid rgba(128,128,128,.45)")

    def th_style(i: int) -> str:
        style = f"text-align:{align[i]};{th_base}"
        if readable and i == 0:
            style += ";position:sticky;left:0;z-index:2"
        return style

    head = "".join(
        f"<th style='{th_style(i)}'>{_html.escape(title)}</th>"
        for i, title in enumerate(headers))
    rows_html = []
    for r, (cells, is_top) in enumerate(body):
        if readable:
            bg = TOP_ROW_SOLID if is_top else (zebra_bg if r % 2 else "#ffffff")
            tds = "".join(
                f"<td style='padding:8px 10px;vertical-align:top;text-align:{align[i]};"
                f"border-bottom:1px solid rgba(128,128,128,.2);font-variant-numeric:tabular-nums;"
                f"white-space:{'normal' if i == 0 else 'nowrap'};background:{bg}"
                + (";position:sticky;left:0;z-index:1" if i == 0 else "")
                + f"'>{cell}</td>"
                for i, cell in enumerate(cells))
            highlight = " style='font-weight:600'" if is_top else ""
        else:
            tds = "".join(
                f"<td style='padding:6px 8px;vertical-align:top;border-bottom:1px solid "
                f"rgba(128,128,128,.2);white-space:{'normal' if i == 0 else 'nowrap'}'>{cell}</td>"
                for i, cell in enumerate(cells))
            highlight = (f" style='background:{TOP_ROW_BG};font-weight:600'" if is_top else "")
        rows_html.append(f"<tr{highlight}>{tds}</tr>")
    return (
        "<div style='overflow-x:auto;-webkit-overflow-scrolling:touch;"
        f"border:2px solid {accent};border-radius:8px'>"
        "<table style='border-collapse:collapse;width:100%;min-width:1100px;"
        "font-size:13px;line-height:1.4'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows_html)}</tbody></table></div>"
    )


def _fee_printer_table_html(rows: list, top_pool: str | None = None, accent: str = DEFAULT_BORDER) -> str:
    """Tabel FEE PRINTER (24H). Satu baris per pool, urut fee/active TVL ÷ volatility (urutan dari pemanggil).

    Baris pool teratas (``top_pool``, avg volume/menit ÷ TVL terbesar) diberi latar kuning.
    Judul boleh turun baris; angka rata kanan; kolom Token menempel saat digeser.
    """
    body = []
    for row in rows:
        cells = [
            _cell_token_html(row),
            _html.escape(pf.fmt_usd(row["tvl"])),
            _html.escape(f"{row['fee_tier']:g}%" if row["fee_tier"] is not None else "—"),
            _html.escape(pf.fmt_pct2(pf.fee_volume_pct(row))),
            _html.escape(pf.fmt_pct2(row["volatility"])),
            _html.escape(pf.fmt_pct2(row.get("fee_tvl"))),
            _html.escape(pf.fmt_pct2(row.get("fee_active_tvl"))),
            _html.escape(pf.fmt_usd(row.get("net_deposits"))),
            _html.escape(pf.fmt_times_plain(pf.fee_active_per_volatility(row))),
            _html.escape(pf.fmt_usd2(row["avg_volume"])),
            _html.escape(pf.fmt_ratio_pct(pf.avg_volume_tvl_ratio(row))),
            _html.escape(pf.fmt_ratio_pct(pf.avg_fee_tvl_ratio(row), digits=3)),
            _html.escape(pf.fmt_usd(row["activity"]["volume"])),
            _html.escape("; ".join(row.get("warnings") or []) or "—"),
        ]
        body.append((cells, top_pool is not None and row["pool"] == top_pool))
    align = ["left"] + ["right"] * (len(TABLE_HEADERS) - 2) + ["left"]
    return _table_html(TABLE_HEADERS, body, accent, align=align, readable=True)


COPY_LABEL = "📋 CA"
TOP_ROW_BG = "rgba(250,204,21,.28)"  # kuning: pool teratas (permintaan user, 2026-11-15)
TOP_ROW_SOLID = "#fef1be"  # TOP_ROW_BG di atas putih, untuk sel yang menempel (sticky)

# Markdown Streamlit membuang <script>, jadi tabel dirender di dalam komponen HTML
# (iframe) yang mengizinkan JavaScript. Tombol copy hanya menyalin CA; tidak ada
# perubahan pada tautan.
_COPY_SCRIPT = """
<script>
function copyCa(btn) {
  var text = btn.getAttribute('data-ca') || '';
  function done(ok) {
    btn.textContent = ok ? '✅ Tersalin' : '❌ Gagal';
    setTimeout(function () { btn.textContent = '%s'; }, 1500);
  }
  function fallback() {
    var t = document.createElement('textarea');
    t.value = text;
    t.setAttribute('readonly', '');
    t.style.position = 'fixed';
    t.style.opacity = '0';
    document.body.appendChild(t);
    t.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(t);
    done(ok);
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
  } else {
    fallback();
  }
}
</script>
""" % COPY_LABEL

_COPY_CSS = (
    "body{margin:0;background:#ffffff;color:#000000;"
    "font-family:'Source Sans Pro',sans-serif;}"
    ".copy-ca{font-size:12px;font-weight:700;color:#1d4ed8;background:#eff6ff;"
    "border:1px solid #93c5fd;border-radius:6px;padding:1px 7px;margin-left:.3rem;"
    "cursor:pointer;white-space:nowrap;font-family:inherit;}"
    ".copy-ca:hover{background:#dbeafe;}"
)


def _copy_button_html(ca: str) -> str:
    if not ca:
        return ""
    return (f'<button type="button" class="copy-ca" data-ca="{_html.escape(ca, quote=True)}" '
            f'onclick="copyCa(this)">{COPY_LABEL}</button>')


def _result_document(rows: list, top_pool: str | None = None,
                     accent: str = DEFAULT_BORDER, builder=None) -> str:
    """Dokumen HTML utuh untuk komponen: tabel + skrip copy CA."""
    make_table = builder or _fee_printer_table_html
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<style>{_COPY_CSS}</style></head><body>"
            f"{make_table(rows, top_pool, accent)}{_COPY_SCRIPT}</body></html>")


def _cell_token_html(row: dict) -> str:
    """Nama token + pool, CA lengkap, dan link. Dipakai di dalam sel tabel."""
    name = _html.escape(f"{row['symbol']} · {row['pool_name'] or row['pool'][:8]}")
    ca = _html.escape(row.get("mint") or "")
    parts = [f"<b style='font-size:14px'>{name}</b>"]
    if ca:
        parts.append(f"<code style='font-size:11px;word-break:break-all;"
                     f"white-space:normal'>{ca}</code>")
    links_html = " &nbsp; ".join(part for part in (
        external_links_html(row.get("mint") or ""),
        pool_links_html(row.get("pool") or ""),
    ) if part)
    copy_html = _copy_button_html(row.get("mint") or "")
    if links_html or copy_html:
        parts.append(f"<span style='font-size:12px'>{links_html}{copy_html}</span>")
    return "<br>".join(parts)


def render_pool_flow_page() -> None:
    import streamlit as st

    with st.container(border=True):
        st.markdown("## 🏆 Scan ALL")
        st.caption(_filter_caption())
        if st.button(BUTTON_LABEL, type="primary", key="pool_flow_scan",
                     use_container_width=True):
            with st.spinner("Memindai listing Meteora (24H)…"):
                st.session_state[RESULT_KEY] = pf.scan_pools()
        result = st.session_state.get(RESULT_KEY)
        if not result:
            st.info("Belum di-scan. Tekan SCAN ALL.")
        else:
            _render_summary(result)
            _render_scan_result(result)
