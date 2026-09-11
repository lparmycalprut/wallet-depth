# -*- coding: utf-8 -*-
"""Card **🏆 Scan Best Pool Meteora** untuk halaman utama (``app.py``).

Kriteria **diganti total** 2026-09-11 sesuai request user (curl UI Meteora):

- query API Meteora ``pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000``
  (timeframe 24 jam, category ``top``, page_size 50) — lihat
  ``meteora_screener.best_filter_by``; tier fee ≥ 2% dan active TVL ≥ $50K
  disaring **oleh API**, tidak diulang sebagai saringan layar;
- saringan layar tinggal dua: dust holder **< 0,05% MC** dan volatility
  **≥ 2%**;
- urutan baris: **dust % MC terkecil** → **fee / active TVL terbesar** →
  **kenaikan volume 24 jam (``volume_change_pct``) terbesar**;
- tabel menampilkan detail fee dan active TVL (kolom **A.TVL**, **Fee/TVL**
  dengan angka fee USD + tier fee di baris kecilnya, **Vol 24h** dengan Δ
  volume) supaya rasio yang jadi kunci urut bisa diperiksa, bukan cuma
  dipercaya. Kolom lama ``Fee`` (tier saja) dihapus — tier fee ikut nempel di
  baris kecil Fee/TVL; kolom ``Vol`` lama (= volatilitas) berganti nama jadi
  **Volat** karena **Vol 24h** sekarang benar-benar volume.

Saringan lama (fee/active TVL > 20%, top 10 holder < 30%, total LPs > 20,
active TVL > 10K) **dihapus** — top 10 holder dan total LPs tetap tampil
sebagai informasi.

Detail karakteristik card = **tooltip judul** (konvensi 2026-09-10,
permintaan user: "ini juga bikin tooltip saja") — bukan caption panjang di
badan card. Angka ambangnya diambil dari konstanta ``meteora_screener.BEST_*``
supaya teks tooltip tidak pernah beda dari rule yang benar-benar jalan. ⭐
memasukkan token ke card **Watchlist Meteora** di halaman utama
(``source=meteora``, sama seperti card temp).

**Penempatan (2026-09-11):** card dirender **full-width** di bawah grid 2
kolom watchlist — permintaan user: "jangan dibuat grid lagi" (2026-09-10
dulu menempel di bawah 🌊 Watchlist Meteora di dalam grid).
"""
from __future__ import annotations

BEST_SESSION_KEY = "best_pool_scan"


def best_pool_tooltip() -> str:
    """Detail karakteristik card — teks tooltip di judul (bukan caption).

    Atribut ``title`` browser tidak mengenal markdown, jadi teksnya plain
    tanpa ``**``. Semua ambang diambil dari ``meteora_screener.BEST_*``
    (sumber kebenaran rule), sehingga tooltip ikut berubah kalau filternya
    diubah — tidak mungkin lagi ada angka tooltip yang beda dengan angka
    yang jalan.
    """
    from meteora_screener import (BEST_ACTIVE_TVL_MIN, BEST_DUST_MAX_PCT,
                                  BEST_FEE_PCT_MIN, BEST_VOLATILITY_MIN)
    return (
        "Listing API Meteora 24 jam (category top, page_size 50) dengan "
        f"filter pool_type=dlmm&&fee_pct>={BEST_FEE_PCT_MIN:g}&&active_tvl>="
        f"{int(BEST_ACTIVE_TVL_MIN)} — tier fee dan active TVL disaring "
        "langsung oleh Meteora, bukan di layar. Yang ditampilkan hanya pool "
        f"dengan dust holder < {BEST_DUST_MAX_PCT:g}% marketcap dan "
        f"volatility >= {BEST_VOLATILITY_MIN:g}%. Urutan: dust % marketcap "
        "terkecil dulu, lalu fee/active TVL paling besar, lalu kenaikan "
        "volume 24 jam paling besar. Di tabel: A.TVL = active TVL "
        "pool, Fee/TVL = fee 24 jam dibagi active TVL (baris kecilnya angka "
        "fee + tier fee), Vol 24h = volume dengan perubahannya (Δ) — kolom "
        "Top10 dan LPs hanya informasi, keduanya bukan saringan lagi. ⭐ "
        "memasukkan token ke card 🌊 Watchlist Meteora di halaman utama; "
        "tombol kanan "
        "membuka Meteora DLMM + HawkFi. Dust dihitung dari scan FULL holder "
        "Helius (bukan sampel), jadi scan token ber-holder banyak bisa makan "
        "waktu beberapa menit.")


# Lebar kolom listing: Token, MC, A.TVL, Fee/TVL, Vol 24h, Volatilitas,
# Top10, LPs, Dust (wallet), Dust %MC, Pool, ⭐.
_COL_SPEC = [1.5, 0.65, 0.78, 0.78, 0.85, 0.6, 0.62, 0.5, 0.6, 0.82, 1.0, 0.4]
_TITLES = ["Token", "MC", "A.TVL", "Fee/TVL", "Vol 24h", "Volat", "Top10",
           "LPs", "Dust", "Dust %MC", "Pool", ""]


def _best_head_html(rows: list, hidden: int) -> str:
    """Header card: judul + pill jumlah pool / pool yang disembunyikan."""
    from dashboard_components import card_head_html
    from meteora_screener import BEST_CARD_TITLE

    pills = [f'<span class="lp-count">{len(rows)} pool</span>']
    if hidden:
        pills.append('<span class="lp-count" style="color:#334155;'
                     f'background:#e2e8f0;">{hidden} disembunyikan</span>')
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

    Dipakai untuk **Δ volume** — kenaikan volume 24 jam adalah kunci urut
    ketiga card, jadi tandanya harus terbaca sekali lihat. ``None`` → ``—``.
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


def render_best_pool_scan() -> None:
    """Card **🏆 Scan Best Pool Meteora** di halaman utama."""
    import html

    import streamlit as st

    from dashboard_components import _number
    from holder_history import FULL_SCAN_MAX_WALLETS
    from links import external_links_html, pool_links_html
    from lp_watchlist import LP_SOURCE
    from meteora_screener import (BEST_DUST_MAX_PCT, BEST_VOLATILITY_MIN,
                                  scan_best_meteora, sort_best_rows)
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
        # ``session_state`` (dari kriteria versi sebelumnya) belum —
        # diurutkan lagi dengan rule baru agar listing konsisten tanpa perlu
        # scan ulang (kolom yang dibutuhkan sort ada di baris lama juga).
        rows = sort_best_rows(result.get("rows") or [])
        hidden = int(result.get("hidden_metric") or 0) + \
            int(result.get("hidden_dust") or 0)
        fetched = int(result.get("fetched") or 0)

        # Tanpa caption ambang: detail karakteristik card sudah jadi tooltip
        # judul (``best_pool_tooltip()``) — permintaan user 2026-09-10.
        st.markdown(_best_head_html(rows, hidden), unsafe_allow_html=True)
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
            fee = row.get("fee")
            active_tvl = row.get("active_tvl")
            ratio = row.get("fee_active_tvl_ratio")
            volume = row.get("volume")
            volume_change = row.get("volume_change_pct")
            # Baris kecil kolom Fee/TVL: angka fee 24 jam + tier fee pool —
            # tier tidak punya kolom sendiri lagi (query API sudah menjamin
            # fee_pct >= BEST_FEE_PCT_MIN) tapi tetap harus terbaca.
            fee_pct = row.get("fee_pct")
            fee_sub = f"fee {_usd_or_dash(fee)}"
            if fee_pct is not None:
                fee_sub += f"·{_number(fee_pct, '.4g')}%"
            delta_txt, delta_color = _signed_pct(volume_change)
            # Δ volume boleh bewarna (hijau/merah) dan jadi baris kecil
            # kolom "Vol 24h" — kunci urut ketiga, tidak perlu kolom baru.
            delta_html = (f'<span style="color:{delta_color};">Δ '
                          f"{delta_txt}</span>" if delta_color
                          else f"<span>Δ {delta_txt}</span>")
            cols = st.columns(_COL_SPEC)
            cols[0].markdown(
                '<div class="watchlist-token">'
                f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
                f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
                f'<div class="watchlist-links">{external_links_html(ca)}</div>'
                "</div>", unsafe_allow_html=True)
            # Detail fee / active TVL + kunci urut (permintaan user
            # 2026-09-11): kolom Fee/TVL memegang rasio yang jadi kunci urut
            # kedua dengan angka fee 24 jam di baris kecilnya, A.TVL memegang
            # penyebutnya, Vol 24h memegang Δ volume (kunci urut ketiga).
            # Tooltip tiap sel memberi angka penuh supaya angka ringkas bisa
            # diperiksa.
            cells = (
                (_usd_or_dash(row.get("mc")), "",
                 f"market cap {_usd_or_dash(row.get('mc'), compact=False)}"),
                (_usd_or_dash(active_tvl), "active tvl",
                 f"active TVL {_usd_or_dash(active_tvl, compact=False)} · "
                 f"TVL total {_usd_or_dash(row.get('tvl'), compact=False)}"),
                (_pct_or_dash(ratio), fee_sub,
                 f"tier fee {_num_or_dash(fee_pct, '.4g')}% · fee 24 jam "
                 f"{_usd_or_dash(fee, compact=False)} / active TVL "
                 f"{_usd_or_dash(active_tvl, compact=False)} = "
                 f"{_num_or_dash(ratio, ',.2f')}% — kunci urut kedua "
                 "(terbesar dulu)"),
                (_usd_or_dash(volume), delta_html,
                 f"volume 24 jam {_usd_or_dash(volume, compact=False)} · "
                 f"perubahan {delta_txt} — kunci urut ketiga (terbesar dulu)"),
                (_pct_or_dash(row.get("volatility")), "volat",
                 "volatility pool "
                 f"{_num_or_dash(row.get('volatility'), ',.2f')}% — saringan "
                 f"layar: minimal {BEST_VOLATILITY_MIN:g}%"),
                (_pct_or_dash(row.get("top_holders_pct")), "top10",
                 "10 holder teratas token base (% supply) — hanya "
                 "informasi, bukan saringan lagi sejak 2026-09-11"),
                (_num_or_dash(row.get("total_lps")), "lps",
                 "jumlah liquidity provider pool — hanya informasi, bukan "
                 "saringan lagi sejak 2026-09-11"),
                (_num_or_dash(row.get("dust_count")), "wallet",
                 "jumlah wallet dust di bawah ambang dust"),
                (_pct_txt(dust_pct, 3), "dust",
                 f"dust holder < {BEST_DUST_MAX_PCT:g}% marketcap — saringan "
                 "sekaligus kunci urut pertama (terkecil dulu)"),
            )
            for position, (value, sub, tip) in enumerate(cells, start=1):
                cols[position].markdown(_cell(value, sub, tip),
                                        unsafe_allow_html=True)
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
