# -*- coding: utf-8 -*-
"""UI main app: 🏆 SCAN BEST POOL (timeframe 12H).

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
BUTTON_LABEL = "SCAN BEST POOL"

TABLE_HEADERS = ["Token / pool", "TVL", "Fee tier",
                 "Volatility", "Fee/TVL", "Fee/active TVL", "Avg volume/menit (pool)",
                 "Volume 12H (pool)", "Peringatan keamanan"]
HOT = "🔥🔥🔥"  # tanda pool paling ramai (baris teratas)


def _filter_caption() -> str:
    return (f"Timeframe 12H · kategori all · urut volume/TVL (listing) · dlmm · "
            f"TVL ≥ {pf.fmt_usd(1000)} · fee ≥ 0.5% · fee/active TVL ≥ 2 · "
            f"tanpa critical warning · tanpa konsentrasi/kepemilikan tunggal tinggi · "
            f"urut fee/active TVL terbesar, lalu avg volume/menit.")


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
    st.caption("Dipisah berdasarkan fee/TVL terhadap volatility: FEE PRINTER (SPOT) bila "
               "fee/TVL > 2 × volatility; tabel kedua bila 0,5 × – 2 × volatility. Pool di bawah "
               "0,5 × volatility tidak ditampilkan di kedua tabel.")
    st.caption("Geser tabel ke kanan untuk melihat semua kolom. Keamanan: pool dengan mint/freeze "
               "authority aktif atau top holders > 30 % dibuang; peringatan muncul bila top holders "
               "> 15 %, dev > 5 %, atau LP keluar lebih besar dari masuk saat TVL < $50K.")
    top = pf.most_crowded(result)
    top_pool = top["pool"] if top else None
    fee_printer, band = pf.fee_printer_split(passing)
    _render_pool_table("FEE PRINTER (SPOT)", "fee/TVL > 2 × volatility", fee_printer, top_pool)
    _render_pool_table("Fee/TVL 0,5× – 2× volatility", "0,5 × volatility ≤ fee/TVL ≤ 2 × volatility",
                       band, top_pool)


def _render_pool_table(title: str, rule: str, rows: list, top_pool) -> None:
    import streamlit as st

    st.markdown(f"**{title}** · {len(rows)} pool · {rule}")
    if not rows:
        st.info(f"Tidak ada pool untuk {title}.")
        return
    # st.iframe (bukan components.v1.html): HTML dirender di iframe agar tombol copy CA bisa berjalan.
    st.iframe(_result_document(rows, top_pool),
              height=_result_height(len(rows)), width="stretch")


def _result_table_html(rows: list, top_pool: str | None = None) -> str:
    """Tabel HTML satu baris per pool, urut avg volume per menit (urutan dari pemanggil)."""
    head = "".join(
        "<th style='text-align:left;padding:6px 8px;white-space:nowrap;"
        "border-bottom:1px solid rgba(128,128,128,.45)'>"
        f"{_html.escape(title)}</th>"
        for title in TABLE_HEADERS)
    body = []
    for row in rows:
        hot = row["pool"] == top_pool
        cells = [
            _cell_token_html(row, hot=hot),
            _html.escape(pf.fmt_usd(row["tvl"])),
            _html.escape(f"{row['fee_tier']:g}%" if row["fee_tier"] is not None else "—"),
            _html.escape(pf.fmt_pct(row["volatility"])),
            _html.escape(pf.fmt_pct(row.get("fee_tvl"))),
            _html.escape(pf.fmt_pct(row["fee_active_tvl"])),
            _html.escape(pf.fmt_usd2(row["avg_volume"])),
            _html.escape(pf.fmt_usd(row["activity"]["volume"])),
            _html.escape("; ".join(row.get("warnings") or []) or "—"),
        ]
        tds = "".join(
            f"<td style='padding:6px 8px;vertical-align:top;border-bottom:1px solid "
            f"rgba(128,128,128,.2);white-space:{'normal' if i == 0 else 'nowrap'}'>{cell}</td>"
            for i, cell in enumerate(cells))
        row_style = " style='background:rgba(249,115,22,.14)'" if hot else ""
        body.append(f"<tr{row_style}>{tds}</tr>")
    return (
        "<div style='overflow-x:auto;-webkit-overflow-scrolling:touch;"
        "border:1px solid rgba(128,128,128,.35);border-radius:8px'>"
        "<table style='border-collapse:collapse;width:100%;min-width:1100px;"
        "font-size:13px;line-height:1.4'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


COPY_LABEL = "📋 CA"

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


def _result_document(rows: list, top_pool: str | None = None) -> str:
    """Dokumen HTML utuh untuk komponen: tabel + skrip copy CA."""
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<style>{_COPY_CSS}</style></head><body>"
            f"{_result_table_html(rows, top_pool)}{_COPY_SCRIPT}</body></html>")


def _result_height(count: int) -> int:
    """Tinggi iframe: header + perkiraan tinggi tiap baris (token bisa dua-tiga baris)."""
    return min(1200, max(160, 60 + 120 * count))


def _cell_token_html(row: dict, hot: bool = False) -> str:
    """Nama token + pool, CA lengkap, dan link. Dipakai di dalam sel tabel."""
    label = f"{row['symbol']} · {row['pool_name'] or row['pool'][:8]}"
    name = _html.escape(f"{HOT} {label}" if hot else label)
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
        st.markdown("## 🏆 Scan Best Pool")
        st.caption(_filter_caption())
        if st.button(BUTTON_LABEL, type="primary", key="pool_flow_scan",
                     use_container_width=True):
            with st.spinner("Memindai listing Meteora (12H)…"):
                result = pf.scan_pools()
            st.session_state[RESULT_KEY] = result
        result = st.session_state.get(RESULT_KEY)
        if not result:
            st.info("Belum di-scan. Tekan SCAN BEST POOL.")
        else:
            _render_scan_result(result)
