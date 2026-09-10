# -*- coding: utf-8 -*-
"""Card **🏆 Scan Best Pool Meteora** untuk halaman utama (``app.py``).

Replika listing **🌊 Scan Meteora Pool** (``temp_ui.render_meteora_scan``,
halaman temp) dengan filter baru (permintaan user 2026-09-10):

- query API Meteora ``pool_type=dlmm&&fee_pct>=5&&active_tvl>=10000``
  (timeframe 24 jam, category ``top``, page_size 50) — lihat
  ``meteora_screener.best_filter_by``;
- saringan layar: dust holder **< 0,05% MC**, active TVL **> 10K USD**,
  fee/active TVL **> 20%**, volatility **> 5%**, top 10 holder **< 30%**,
  total LPs **> 20**;
- urutan baris: **dust % MC terkecil**, lalu **volume terbesar** (tie-break).

Ambangnya hidup di konstanta ``meteora_screener.BEST_*`` supaya angka di
tooltip/caption tidak pernah beda dari rule yang benar-benar jalan. ⭐
memasukkan token ke card **Watchlist Meteora** di halaman utama
(``source=meteora``, sama seperti card temp).
"""
from __future__ import annotations

BEST_SESSION_KEY = "best_pool_scan"

# Detail karakteristik card = tooltip judul (konvensi 2026-09-10): bukan
# caption panjang di badan card. Atribut ``title`` tidak mengenal markdown.
BEST_POOL_TOOLTIP = (
    "Replika Scan Meteora Pool untuk halaman utama dengan filter baru. "
    "Listing API Meteora (24 jam, category top): pool_type=dlmm, "
    "fee_pct>=5, active_tvl>=10000. Yang ditampilkan hanya pool dengan "
    "dust holder < 0.05% marketcap, active TVL > 10K USD, fee/active TVL "
    "> 20%, volatility > 5%, top 10 holder < 30% supply, dan total LPs "
    "> 20. Urutan: dust % marketcap terkecil dulu, lalu volume terbesar. "
    "Tombol bintang memasukkan token ke card Watchlist Meteora; tombol "
    "kanan membuka Meteora DLMM + HawkFi.")

# Lebar kolom listing: Token, MC, A.TVL, Fee/TVL, Vol, Top10, LPs, Fee,
# Dust (wallet), Dust %MC, Pool, ⭐.
_COL_SPEC = [1.5, 0.65, 0.78, 0.72, 0.6, 0.62, 0.5, 0.5, 0.6, 0.82, 1.0, 0.4]
_TITLES = ["Token", "MC", "A.TVL", "Fee/TVL", "Vol", "Top10", "LPs", "Fee",
           "Dust", "Dust %MC", "Pool", ""]


def _best_head_html(rows: list, hidden: int) -> str:
    """Header card: judul + pill jumlah pool / pool yang disembunyikan."""
    from dashboard_components import card_head_html
    from meteora_screener import BEST_CARD_TITLE

    pills = [f'<span class="lp-count">{len(rows)} pool</span>']
    if hidden:
        pills.append('<span class="lp-count" style="color:#334155;'
                     f'background:#e2e8f0;">{hidden} disembunyikan</span>')
    return card_head_html(BEST_CARD_TITLE, pills, tooltip=BEST_POOL_TOOLTIP)


def _pct_txt(value, digits: int = 2) -> str:
    """Angka persen siap tampil (``None`` → ``—``)."""
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def render_best_pool_scan() -> None:
    """Card **🏆 Scan Best Pool Meteora** di halaman utama."""
    import html

    import streamlit as st

    from dashboard_components import _compact, _number
    from holder_history import FULL_SCAN_MAX_WALLETS
    from links import external_links_html, pool_links_html
    from lp_watchlist import LP_SOURCE
    from meteora_screener import (BEST_ACTIVE_TVL_MIN, BEST_DUST_MAX_PCT,
                                  BEST_FEE_PCT_MIN, BEST_FEE_RATIO_MIN,
                                  BEST_TOTAL_LPS_MIN, BEST_TOP10_MAX_PCT,
                                  BEST_VOLATILITY_MIN, scan_best_meteora,
                                  sort_best_rows)
    from watchlist import add_to_watchlist

    with st.container(border=True):
        # Kepala card butuh hasil scan terakhir (jumlah pool + yang
        # disembunyikan), jadi hasil dibaca dulu lalu listing di bawahnya —
        # satu sumber data, selesai scan langsung ``st.rerun()`` (pola card
        # Watchlist Meteora / Scan Meteora Pool).
        if st.button("🏆 Scan Best Pool Meteora + Holder", type="primary",
                     key="best-pool-scan-now", use_container_width=True):
            bar = st.progress(0.0, text="Listing pool Meteora…")

            def _progress(index, total, label):
                bar.progress(index / max(total, 1),
                             text=f"Holder {index}/{total} · {label}")

            try:
                # FULL scan (bukan cap kecil): urutan getTokenAccounts Helius
                # tidak urut saldo, jadi sampel kecil membuat angka dust
                # < 0,05% MC tidak bisa dipercaya.
                result = scan_best_meteora(max_wallets=FULL_SCAN_MAX_WALLETS,
                                           workers=6, progress=_progress)
            except Exception as exc:  # noqa: BLE001 - kegagalan = pesan card
                result = {"rows": [], "error": str(exc), "fetched": 0,
                          "hidden_metric": 0, "hidden_dust": 0}
            finally:
                bar.empty()
            st.session_state[BEST_SESSION_KEY] = result
            st.rerun()

        result = st.session_state.get(BEST_SESSION_KEY) or {}
        error = str(result.get("error") or "")
        # ``scan_best_meteora`` sudah mengurutkan, tapi hasil lama di
        # ``session_state`` (dari versi sebelumnya) belum — urutkan lagi agar
        # listing konsisten tanpa perlu scan ulang.
        rows = sort_best_rows(result.get("rows") or [])
        hidden = int(result.get("hidden_metric") or 0) + \
            int(result.get("hidden_dust") or 0)
        fetched = int(result.get("fetched") or 0)

        st.markdown(_best_head_html(rows, hidden), unsafe_allow_html=True)
        st.caption(
            f"Top DLMM 24 jam (`pool_type=dlmm`, `fee_pct ≥ "
            f"{BEST_FEE_PCT_MIN:g}`, `active_tvl ≥ "
            f"{int(BEST_ACTIVE_TVL_MIN)}`) lalu saringan layar: dust holder "
            f"**< {BEST_DUST_MAX_PCT:g}% MC**, active TVL **> "
            f"${BEST_ACTIVE_TVL_MIN / 1000:g}K**, fee/active TVL **> "
            f"{BEST_FEE_RATIO_MIN:g}%**, volatility **> "
            f"{BEST_VOLATILITY_MIN:g}%**, top 10 holder **< "
            f"{BEST_TOP10_MAX_PCT:g}%**, total LPs **> "
            f"{BEST_TOTAL_LPS_MIN:g}**. Urutan: **dust % MC terkecil**, lalu "
            "**volume terbesar**. ⭐ memasukkan token ke card **Watchlist "
            "Meteora** di halaman utama."
        )
        if error:
            st.warning(f"Meteora API: {error}")
        if fetched:
            st.caption(f"{len(rows)} pool lolos · {hidden} disembunyikan "
                       f"· listing {fetched} pool.")
        if not rows:
            if result:
                st.info("Tidak ada pool yang lolos filter Best Pool "
                        "(atau listing kosong).")
            return

        header_cols = st.columns(_COL_SPEC)
        style = ("font-size:0.72rem;color:#000000;font-weight:700;"
                 "text-align:center;")
        for col, title in zip(header_cols, _TITLES):
            col.markdown(f'<div style="{style}">{title}</div>',
                         unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)

        for index, row in enumerate(rows):
            ca = str(row.get("ca") or "")
            symbol = str(row.get("symbol") or "?").upper()
            pool = str(row.get("pool_address") or "")
            dust_pct = row.get("dust_pct_mc")
            cols = st.columns(_COL_SPEC)
            cols[0].markdown(
                '<div class="watchlist-token">'
                f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
                f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
                f'<div class="watchlist-links">{external_links_html(ca)}</div>'
                "</div>", unsafe_allow_html=True)
            for position, (value, sub, pattern) in enumerate((
                    (row.get("mc"), "", None),
                    (row.get("active_tvl"), "active tvl", None),
                    (row.get("fee_active_tvl_ratio"), "fee/tvl", ".1f"),
                    (row.get("volatility"), "vol", ".1f"),
                    (row.get("top_holders_pct"), "top10", ".1f"),
                    (row.get("total_lps"), "lps", ".0f"),
                    (row.get("fee_pct"), "fee", ".1f"),
                    (row.get("dust_count"), "wallet", ".0f")), start=1):
                if pattern is None:
                    text = _compact(value) if value is not None else "—"
                else:
                    text = _number(value, pattern)
                # Suffix "%" hanya untuk kolom persen (fee/TVL, volatility,
                # top 10 holder, fee tier) — MC/A.TVL berupa USD dan Dust
                # berupa jumlah wallet.
                suffix = "%" if position in (3, 4, 5, 7) else ""
                cols[position].markdown(
                    '<div class="watchlist-metric">'
                    '<div class="watchlist-metric-value">'
                    f"{text}{suffix}</div>"
                    f'<div class="watchlist-metric-sub">{sub}</div>'
                    "</div>", unsafe_allow_html=True)
            cols[9].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f"{_pct_txt(dust_pct, 3)}</div>"
                '<div class="watchlist-metric-sub">dust</div>'
                "</div>", unsafe_allow_html=True)
            pool_html = pool_links_html(pool) or "<span>—</span>"
            cols[10].markdown(f'<div class="pool-links">{pool_html}</div>',
                              unsafe_allow_html=True)
            # Key diikat ke pool/CA, bukan nomor baris: urutan listing bisa
            # berubah setelah scan ulang sehingga key berbasis index membuat
            # klik ⭐ menempel ke token yang berbeda.
            star_key = f"best-pool-star-{pool or ca or index}"
            if cols[11].button("⭐", key=star_key,
                               help="Tambah ke Watchlist Meteora "
                                    "(halaman utama)",
                               use_container_width=True):
                if ca:
                    add_to_watchlist(ca, symbol, source=LP_SOURCE,
                                     background=True)
                    st.success(f"${symbol} masuk Watchlist Meteora")
            st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                        unsafe_allow_html=True)
