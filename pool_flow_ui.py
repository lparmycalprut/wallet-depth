# -*- coding: utf-8 -*-
"""UI main app: 🏆 Scan Best Pool (12H) + 🕓 Deteksi 4H, satu tombol SCAN ALL.

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
RESULT_KEY_4H = "pool_flow_result_4h"
BUTTON_LABEL = "SCAN ALL"
# Warna tabel (permintaan user): HIGH RISK merah, SLOW FEE PRINTER biru. Nama warna untuk st.markdown.
HIGH_RISK_COLOR = "red"
SLOW_FEE_PRINTER_COLOR = "blue"
HIGH_RISK_BORDER = "rgba(239,68,68,.85)"
VERY_HIGH_RISK_COLOR = "red"
VERY_HIGH_RISK_BORDER = "rgba(127,29,29,.95)"  # merah tua: lebih berisiko dari HIGH RISK (2026-11-18)
SLOW_FEE_PRINTER_BORDER = "rgba(59,130,246,.85)"
DEFAULT_BORDER = "rgba(128,128,128,.35)"
FOUR_H_COLOR = "violet"  # bagian Deteksi 4H (permintaan user, 2026-11-15)
FOUR_H_BORDER = "rgba(139,92,246,.85)"

TABLE_HEADERS = ["Token / pool", "TVL", "Fee tier",
                 "Volatility", "Fee/TVL", "Avg volume/menit (pool)",
                 "Avg volume/menit ÷ TVL", "Avg fee/menit ÷ TVL",
                 "Volume 12H (pool)", "Peringatan keamanan"]
TABLE_4H_HEADERS = ["Token / pool", "TVL", "Fee tier",
                    "Avg volume/menit (pool)", "Avg volume/menit ÷ TVL",
                    "Avg fee/menit (pool)", "Avg fee/menit ÷ TVL",
                    "Volume 4H (pool)", "Peringatan keamanan"]


def _filter_caption() -> str:
    return (f"Timeframe 12H · kategori all · dlmm · "
            f"TVL ≥ {pf.fmt_usd(10000)} · fee/TVL ≥ 2 · fee ≥ 0.5% · "
            f"tanpa critical warning · tanpa konsentrasi/kepemilikan tunggal tinggi · "
            f"urut avg volume/menit ÷ TVL terbesar.")


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
    fee_printer, band = pf.fee_printer_split(passing)
    high_risk = pf.fee_printer_high_risk(fee_printer)
    # HIGH RISK FEE PRINTER: fee/TVL > 2 × dan < 20 × volatility (permintaan user, filter kedua).
    top = pf.most_crowded(result)
    top_pool = top["pool"] if top else None
    # Warna per tabel: HIGH RISK merah, SLOW FEE PRINTER biru (judul dan border tabel).
    st.markdown(f"**:{HIGH_RISK_COLOR}[HIGH RISK FEE PRINTER]**")
    st.markdown(f"*· {len(high_risk)} pool · 2 × volatility < fee/TVL < 20 × volatility*")
    _render_pool_table(high_risk, "Tidak ada pool untuk HIGH RISK FEE PRINTER.", top_pool,
                       accent=HIGH_RISK_BORDER)
    # VERY HIGH RISK POOL / BISA DUMP SEWAKTU2: fee/TVL ≥ 20 × volatility (permintaan user, 2026-11-18).
    very_high = pf.very_high_risk(passing)
    st.markdown(f"**:{VERY_HIGH_RISK_COLOR}[VERY HIGH RISK POOL / BISA DUMP SEWAKTU2]**")
    st.markdown(f"*· {len(very_high)} pool · fee/TVL ≥ 20 × volatility*")
    _render_pool_table(very_high, "Tidak ada pool untuk VERY HIGH RISK POOL.", top_pool,
                       accent=VERY_HIGH_RISK_BORDER)
    st.markdown(f"**:{SLOW_FEE_PRINTER_COLOR}[SLOW FEE PRINTER]**")
    st.markdown(f"*· {len(band)} pool · 0,5 × volatility ≤ fee/TVL ≤ 2 × volatility · umur token ≥ 24 jam · urut avg fee/menit ÷ TVL*")
    _render_pool_table(band, "Tidak ada pool untuk SLOW FEE PRINTER.", top_pool,
                       accent=SLOW_FEE_PRINTER_BORDER)


def _filter_caption_4h() -> str:
    return ("Timeframe 4H · kategori top · dlmm · MC ≥ $20K · holders ≥ 1.500 · TVL ≥ $10K · "
            "active TVL ≥ $10K · fee/TVL ≥ 1 · fee ≥ 0.5% · tanpa konsentrasi/kepemilikan tunggal tinggi · "
            "avg volume/menit ÷ TVL > 2% · urut avg volume/menit ÷ TVL, lalu avg fee/menit ÷ TVL terbesar.")


def _render_4h_result(result: dict) -> None:
    import streamlit as st

    passing = result.get("passing") or []
    st.caption(
        f"Listing {result.get('listing_rows', 0)} baris · pool dievaluasi "
        f"{result.get('candidates', 0)} · ditampilkan {len(passing)} · "
        f"dicatat {result.get('scanned_at', '')}"
        + (f" · {result['listing_errors']} halaman listing gagal"
           if result.get("listing_errors") else ""))
    if result.get("truncated"):
        st.warning("Listing 4H belum lengkap: pengambilan berhenti sebelum semua halaman "
                   f"terambil (batas {pf.FLOW_MAX_PAGES} halaman atau ada halaman gagal).")
    if not passing:
        st.info("Tidak ada pool dari listing 4H.")
        return
    st.caption("Geser tabel ke kanan untuk melihat semua kolom. Keamanan: pool dengan mint/freeze "
               "authority aktif atau top holders > 30 % dibuang. Baris kuning = pool teratas 4H.")
    st.markdown(f"**:{FOUR_H_COLOR}[DETEKSI 4H]**")
    st.markdown(f"*· {len(passing)} pool · urut avg volume/menit ÷ TVL, lalu avg fee/menit ÷ TVL*")
    _render_pool_table(passing, "Tidak ada pool untuk DETEKSI 4H.", passing[0]["pool"],
                       accent=FOUR_H_BORDER, builder=_result_table_4h_html)


SUMMARY_HEADERS = ["Token / pool", "Kriteria", "Avg volume/menit ÷ TVL (4H)"]
SUMMARY_BORDER = "rgba(34,197,94,.85)"  # hijau: ringkasan (permintaan user, 2026-11-15)
_SUMMARY_BADGE = {
    pf.SUMMARY_BEST: "background:rgba(34,197,94,.28);color:inherit",
    pf.SUMMARY_4H: "background:rgba(139,92,246,.28);color:inherit",
}


def _summary_table_html(entries: list) -> str:
    body = []
    for row, label in entries:
        badge = (f"<span style='{_SUMMARY_BADGE.get(label, '')};padding:2px 10px;"
                 f"border-radius:999px;font-weight:600;white-space:nowrap'>"
                 f"{_html.escape(label)}</span>")
        cells = [
            _cell_token_html(row),
            badge,
            _html.escape(pf.fmt_ratio_pct(pf.avg_volume_tvl_ratio(row), digits=3)),
        ]
        body.append((cells, False))
    return _table_html(SUMMARY_HEADERS, body, SUMMARY_BORDER)


def _render_summary(result: dict, result_4h: dict) -> None:
    import streamlit as st

    entries = pf.summary_rows(result, result_4h)
    st.markdown("**:green[RINGKASAN]**")
    st.caption("BEST POOL (HIGH RISK) = ada di HIGH RISK FEE PRINTER (12H) dan di DETEKSI 4H. "
               "4H ≥ 10% (CURVE) SL OOR = avg volume/menit ÷ TVL di DETEKSI 4H minimal 10%.")
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


def _table_html(headers: list, body: list, accent: str) -> str:
    """Pembungkus tabel HTML. ``body`` = [(sel-sel teks HTML, baris_teratas)]."""
    head = "".join(
        "<th style='text-align:left;padding:6px 8px;white-space:nowrap;"
        "border-bottom:1px solid rgba(128,128,128,.45)'>"
        f"{_html.escape(title)}</th>"
        for title in headers)
    rows_html = []
    for cells, is_top in body:
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


def _result_table_html(rows: list, top_pool: str | None = None,
                       accent: str = DEFAULT_BORDER) -> str:
    """Tabel HTML 12H, satu baris per pool, urut rasio avg volume/menit ÷ TVL (urutan dari pemanggil).

    Baris pool teratas (``top_pool``) diberi latar kuning; tanpa emoji.
    """
    body = []
    for row in rows:
        cells = [
            _cell_token_html(row),
            _html.escape(pf.fmt_usd(row["tvl"])),
            _html.escape(f"{row['fee_tier']:g}%" if row["fee_tier"] is not None else "—"),
            _html.escape(pf.fmt_pct(row["volatility"])),
            _html.escape(pf.fmt_pct(row.get("fee_tvl"))),
            _html.escape(pf.fmt_usd2(row["avg_volume"])),
            _html.escape(pf.fmt_ratio_pct(pf.avg_volume_tvl_ratio(row))),
            _html.escape(pf.fmt_ratio_pct(pf.avg_fee_tvl_ratio(row), digits=3)),
            _html.escape(pf.fmt_usd(row["activity"]["volume"])),
            _html.escape("; ".join(row.get("warnings") or []) or "—"),
        ]
        body.append((cells, top_pool is not None and row["pool"] == top_pool))
    return _table_html(TABLE_HEADERS, body, accent)


def _result_table_4h_html(rows: list, top_pool: str | None = None,
                          accent: str = DEFAULT_BORDER) -> str:
    """Tabel HTML deteksi 4H: urut avg volume/menit ÷ TVL, lalu avg fee/menit ÷ TVL (urutan dari pemanggil)."""
    body = []
    for row in rows:
        tvl = row["tvl"]
        fee_ratio = (row["avg_fee"] / tvl) if (row.get("avg_fee") is not None and tvl) else None
        cells = [
            _cell_token_html(row),
            _html.escape(pf.fmt_usd(tvl)),
            _html.escape(f"{row['fee_tier']:g}%" if row["fee_tier"] is not None else "—"),
            _html.escape(pf.fmt_usd2(row["avg_volume"])),
            _html.escape(pf.fmt_ratio_pct(pf.avg_volume_tvl_ratio(row), digits=3)),
            _html.escape(pf.fmt_usd2(row.get("avg_fee"))),
            _html.escape(pf.fmt_ratio_pct(fee_ratio, digits=3)),
            _html.escape(pf.fmt_usd(row["activity"]["volume"])),
            _html.escape("; ".join(row.get("warnings") or []) or "—"),
        ]
        body.append((cells, top_pool is not None and row["pool"] == top_pool))
    return _table_html(TABLE_4H_HEADERS, body, accent)


COPY_LABEL = "📋 CA"
TOP_ROW_BG = "rgba(250,204,21,.28)"  # kuning: pool teratas (permintaan user, 2026-11-15)

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
    make_table = builder or _result_table_html
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
            with st.spinner("Memindai listing Meteora (12H dan 4H)…"):
                st.session_state[RESULT_KEY] = pf.scan_pools()
                st.session_state[RESULT_KEY_4H] = pf.scan_4h()
        result = st.session_state.get(RESULT_KEY)
        result_4h = st.session_state.get(RESULT_KEY_4H)
        if not result or not result_4h:
            st.info("Belum di-scan. Tekan SCAN ALL.")
        else:
            _render_summary(result, result_4h)
            _render_scan_result(result)

    # Deteksi 4H: bagian terpisah di paling bawah, tanpa tombol sendiri (SCAN ALL).
    with st.container(border=True):
        st.markdown("## 🕓 Deteksi 4H")
        st.caption(_filter_caption_4h())
        if not result_4h:
            st.info("Belum di-scan. Tekan SCAN ALL.")
        else:
            _render_4h_result(result_4h)
