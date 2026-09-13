# -*- coding: utf-8 -*-
"""Card **🏆 Scan Best Pool Meteora** untuk halaman utama (``app.py``).

Kriteria 2026-09-13 — semua saringan layar **dihapus** per request user:

- \"dust% syaratnya hapus saja\" (dust <0,05%),
- \"volatility dan minimum volume juga hapus\" (volatility >=2%, volume >=1M),
- \"fee_pct>=2 hapus\" (2026-09-13 sore — supaya pool ber-fee rendah
  seperti EMBER/USDC juga muncul).

Sekarang hanya filter server API Meteora:
``pool_type=dlmm&&active_tvl>=50000`` (timeframe 24H + 30M,
category ``top``, page_size 50) — lihat ``meteora_screener.best_filter_by``.
Semua pool dari API (kecuali quote-only SOL/USDC/USDT) ditampilkan apa adanya.

- urutan baris: **volume 24 jam / active TVL (``volume_active_tvl_ratio``)
  terbesar** → **dust % MC terkecil** (sejak 2026-09-13). Rasionya dikirim
  langsung API Meteora dan ditampilkan di baris kecil kolom **Vol 24h**, jadi
  kunci urutnya bisa diperiksa;
- kolom **F/V** = fee_active_tvl_ratio ÷ volatility (berapa kali fee
  pool lebih besar dari volatility);
- kolom **Src** = timeframe listing (24H atau 30M);
- tabel menampilkan detail fee dan active TVL (kolom **A.TVL**, **Fee/TVL**
  dengan fee USD + tier fee, **Vol 24h** dengan Δ volume + rasio
  volume/active TVL) sebagai informasi.

**🏆 BEST POOL badge (dust <= 0,035% MC) dihapus** 2026-09-13 sore per
permintaan user: \"tulisan tentang dust holder BEST POOL aman dll hapus
juga\". Pill di kepala card juga dihapus. Dust %MC tetap tampil sebagai
informasi (angka + kunci urut kedua) tanpa penanda visual apa pun.

Saringan lama (fee/TVL >20%, top10 <30%, LPs >20, active TVL >10K,
dust <0,05%, volatility >=2%, volume >=1M, fee_pct >=2%) **dihapus total**
— semua metrik tetap tampil sebagai informasi + kunci urut.

Detail karakteristik = **tooltip judul** — bukan caption panjang. ⭐
memasukkan token ke card **Watchlist Meteora** di halaman utama.
"""
from __future__ import annotations

BEST_SESSION_KEY = "best_pool_scan"
BEST_SHOW_HIDDEN_KEY = "best_pool_show_hidden"


def best_pool_tooltip() -> str:
    """Detail karakteristik card — teks tooltip di judul (bukan caption).

    Semua saringan layar dinonaktifkan 2026-09-13 per request user:
    dust% + volatility + minimum volume + fee_pct dihapus. Hanya filter
    API server ``pool_type=dlmm&&active_tvl>=50000`` yang tersisa.
    """
    from meteora_screener import BEST_ACTIVE_TVL_MIN
    return (
        "Listing API Meteora **24H + 30M** (category top, page_size 50) "
        f"dengan filter pool_type=dlmm&&active_tvl>="
        f"{int(BEST_ACTIVE_TVL_MIN)} — active TVL disaring langsung oleh "
        "Meteora, bukan di layar. Filter ``fee_pct>=2`` **dihapus** "
        "2026-09-13 supaya pool ber-fee rendah (EMBER/USDC, SOL/USDC, "
        "dll) juga muncul. Semua pool dari API (kecuali quote-only "
        "SOL/USDC/USDT) ditampilkan apa adanya — TIDAK ada saringan "
        "layar dust / volatility / volume / fee_pct lagi. "
        "Urutan: volume 24 jam dibagi active TVL (rasio yang dikirim "
        "API Meteora — angkanya di baris kecil kolom Vol 24h) paling "
        "besar dulu, lalu dust % marketcap terkecil. "
        "Kolom **F/V** = fee_active_tvl_ratio ÷ volatility (berapa kali "
        "fee pool lebih besar dari volatility — lebih tinggi = fee lebih "
        "dominan). Kolom **Src** = timeframe listing pool (24H atau 30M; "
        "pool yang sama bisa muncul di kedua timeframe sebagai baris "
        "terpisah karena metrik fee/volatility berbeda). "
        "Di tabel: A.TVL = active TVL pool, Fee/TVL = fee dibagi "
        "active TVL (baris kecilnya angka fee + tier fee), Vol 24h = "
        "volume 24 jam dengan Δ + rasio volume/active TVL, Volat = "
        "volatility, Top10/LPs/Dust = informasi. ⭐ memasukkan token ke "
        "Watchlist Meteora; tombol kanan buka Meteora DLMM + HawkFi. "
        "Dust dihitung dari scan FULL holder Helius, pembagi Dust %MC = "
        "market cap DexScreener (kolom MC). Pool quote-only dilewati "
        "sebelum holder di-fetch. Baris yang holdernya gagal tetap tampil "
        "dengan —." )


# Lebar kolom listing: Token, MC, A.TVL, Fee/TVL, Vol 24h, Volatilitas,
# Top10, LPs, Dust (wallet), Dust %MC, F/V (fee÷volatility), Src (24H/30M),
# Pool, ⭐.
_COL_SPEC = [1.5, 0.65, 0.78, 0.78, 0.85, 0.6, 0.62, 0.5, 0.6, 0.82,
             0.55, 0.45, 1.0, 0.4]
_TITLES = ["Token", "MC", "A.TVL", "Fee/TVL", "Vol 24h", "Volat", "Top10",
           "LPs", "Dust", "Dust %MC", "F/V", "Src", "Pool", ""]


def _best_head_html(rows: list, hidden: int, *, showing_hidden: bool = False) -> str:
    """Header card: judul + pill jumlah pool / pool yang disembunyikan.

    Pill **🏆 BEST POOL** dihapus 2026-09-13 per permintaan user
    (\"tulisan tentang dust holder BEST POOL aman dll hapus juga\").
    Pill **N disembunyikan** tetap di sini sebagai rekap.
    """
    from dashboard_components import card_head_html
    from meteora_screener import BEST_CARD_TITLE

    pills = [f'<span class="lp-count">{len(rows)} pool</span>']
    if hidden:
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

    Dipakai untuk **Δ volume** (baris kecil kolom Vol 24h) — sejak
    2026-09-13 kunci urut pertama card adalah **volume 24 jam / active TVL**,
    jadi angka volume + arah perubahannya harus terbaca sekali lihat.
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


def _render_best_table(rows: list, *, key_prefix: str = "best-pool") -> None:
    """Tabel listing Best Pool (listing utama atau yang disembunyikan)."""
    import html

    import streamlit as st

    from dashboard_components import _number
    from links import external_links_html, pool_links_html
    from lp_watchlist import LP_SOURCE
    from meteora_screener import (fee_volatility_ratio,
                                  row_dust_pct,
                                  row_vol_tvl_ratio)
    from watchlist import add_to_watchlist

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
        # Kunci urut pertama (volume 24 jam / active TVL) ditulis di baris
        # kecil kolom Vol 24h supaya urutannya bisa diperiksa sekali lihat.
        vol_tvl_ratio = row_vol_tvl_ratio(row)
        if vol_tvl_ratio is not None:
            delta_html += (f" · {_num_or_dash(vol_tvl_ratio, ',.0f')}×"
                           " A.TVL")
        dust_value = _pct_txt(dust_pct, 3)
        dust_sub = "dust"
        dust_tip = ("dust holder — informasi (filter dust dinonaktifkan "
                    "2026-09-13) · kunci urut kedua (terkecil dulu) · "
                    "pembaginya market cap DexScreener (kolom MC), sumber "
                    "yang sama dengan 🛰 Scan Holder")
        cols = st.columns(_COL_SPEC)
        cols[0].markdown(
            '<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(ca)}</div>'
            "</div>", unsafe_allow_html=True)
        # Kolom F/V — berapa kali fee/activeTVL dibandingkan volatility.
        # Angka quotient = fee_active_tvl_ratio ÷ volatility (keduanya sudah
        # dalam persen dari API Meteora, jadi quotient-nya tanpa satuan).
        fv_ratio = fee_volatility_ratio(row.get("fee_active_tvl_ratio"),
                                        row.get("volatility"))
        if fv_ratio is not None:
            import math as _math
            if _math.isinf(fv_ratio):
                fv_value = "∞"
            else:
                fv_value = f"{fv_ratio:.1f}×"
        else:
            fv_value = "—"
        fv_sub = "fee÷vol"
        fv_tip = ("fee_active_tvl_ratio ÷ volatility = "
                  f"{_num_or_dash(fv_ratio, ',.2f')}× — "
                  "berapa kali fee pool lebih besar dari volatility; "
                  "lebih tinggi = fee lebih dominan")
        # Kolom Src — timeframe pool: 24H atau 30M.
        row_tf = str(row.get("timeframe") or row.get("source")
                     or "24h").lower()
        if row_tf in ("30m", "1h", "30 menit", "30 min"):
            src_value = "30M"
            src_color = "#9333ea"  # ungu untuk 30M
        else:
            src_value = "24H"
            src_color = "#0284c7"  # biru untuk 24H
        src_sub = "timeframe"
        src_tip = (f"pool berasal dari listing timeframe {src_value} — "
                   "metrik fee/volatility API Meteora dihitung pada "
                   "window waktu ini")
        cells = (
            (_usd_or_dash(row.get("mc")), "",
             f"market cap {_usd_or_dash(row.get('mc'), compact=False)} — "
             "DexScreener, angka yang dipakai sebagai pembagi Dust %MC"),
            (_usd_or_dash(active_tvl), "active tvl",
             f"active TVL {_usd_or_dash(active_tvl, compact=False)} · "
             f"TVL total {_usd_or_dash(row.get('tvl'), compact=False)}"),
            (_pct_or_dash(ratio), fee_sub,
             f"tier fee {_num_or_dash(fee_pct, '.4g')}% · fee 24 jam "
             f"{_usd_or_dash(fee, compact=False)} / active TVL "
             f"{_usd_or_dash(active_tvl, compact=False)} = "
             f"{_num_or_dash(ratio, ',.2f')}% — informasi, bukan kunci "
             "urut lagi sejak 2026-09-13"),
            (_usd_or_dash(volume), delta_html,
             f"volume 24 jam {_usd_or_dash(volume, compact=False)} · "
             f"perubahan {delta_txt} · rasio volume/active TVL "
             f"{_num_or_dash(vol_tvl_ratio, ',.2f')}% — kunci urut pertama "
             "(terbesar dulu), informasi (bukan saringan)"),
            (_pct_or_dash(row.get("volatility")), "volat",
             "volatility pool "
             f"{_num_or_dash(row.get('volatility'), ',.2f')}% — informasi, "
             "bukan saringan lagi sejak 2026-09-13"),
            (_pct_or_dash(row.get("top_holders_pct")), "top10",
             "10 holder teratas token base (% supply) — hanya "
             "informasi, bukan saringan lagi sejak 2026-09-11"),
            (_num_or_dash(row.get("total_lps")), "lps",
             "jumlah liquidity provider pool — hanya informasi, bukan "
             "saringan lagi sejak 2026-09-11"),
            (_num_or_dash(row.get("dust_count")), "wallet",
             "jumlah wallet dust di bawah ambang dust"),
            (dust_value, dust_sub, dust_tip),
            (fv_value, fv_sub, fv_tip),
            (f'<span style="color:{src_color};font-weight:700;">'
             f'{src_value}</span>', src_sub, src_tip),
        )
        for position, (value, sub, tip) in enumerate(cells, start=1):
            cols[position].markdown(_cell(value, sub, tip),
                                    unsafe_allow_html=True)
        pool_html = pool_links_html(pool) or "<span>—</span>"
        cols[12].markdown(f'<div class="pool-links">{pool_html}</div>',
                          unsafe_allow_html=True)
        star_key = f"{key_prefix}-star-{pool or ca or index}"
        if cols[13].button("⭐", key=star_key,
                           help="Tambah ke Watchlist Meteora "
                                "(halaman utama)",
                           use_container_width=True):
            if ca:
                add_to_watchlist(ca, symbol, source=LP_SOURCE,
                                 background=True)
                st.success(f"${symbol} masuk Watchlist Meteora")
        st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)


def render_best_pool_scan() -> None:
    """Card **🏆 Scan Best Pool Meteora** di halaman utama."""
    import streamlit as st

    from holder_history import FULL_SCAN_MAX_WALLETS
    from meteora_screener import scan_best_meteora, sort_best_rows

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
                result = {"rows": [], "hidden_rows": [], "error": str(exc),
                          "fetched": 0, "hidden_metric": 0, "hidden_dust": 0}
            finally:
                bar.empty()
            st.session_state[BEST_SESSION_KEY] = result
            st.session_state[BEST_SHOW_HIDDEN_KEY] = False
            st.rerun()

        result = st.session_state.get(BEST_SESSION_KEY) or {}
        error = str(result.get("error") or "")
        # ``scan_best_meteora`` sudah mengurutkan, tapi hasil lama di
        # ``session_state`` (dari kriteria versi sebelumnya) belum —
        # diurutkan lagi dengan rule baru agar listing konsisten tanpa perlu
        # scan ulang (kolom yang dibutuhkan sort ada di baris lama juga).
        rows = sort_best_rows(result.get("rows") or [])
        hidden_rows = sort_best_rows(result.get("hidden_rows") or [])
        hidden = int(result.get("hidden_metric") or 0) + \
            int(result.get("hidden_dust") or 0)
        fetched = int(result.get("fetched") or 0)
        skipped_quote = int(result.get("skipped_quote") or 0)
        showing_hidden = bool(st.session_state.get(BEST_SHOW_HIDDEN_KEY))

        # Tanpa caption ambang: detail karakteristik card sudah jadi tooltip
        # judul (``best_pool_tooltip()``) — permintaan user 2026-09-10.
        st.markdown(_best_head_html(rows, hidden,
                                    showing_hidden=showing_hidden),
                    unsafe_allow_html=True)
        if hidden:
            # Sejak 2026-09-13 semua saringan layar dihapus — hidden seharusnya 0.
            # Tombol tetap dipertahankan untuk kompatibilitas data lama di session.
            label = (f"◀ kembali ke {len(rows)} pool lolos"
                     if showing_hidden
                     else f"▶ {hidden} disembunyikan")
            if st.button(label, key="best-pool-toggle-hidden",
                         help=("Tampilkan pool yang disembunyikan (legacy, "
                               "sekarang semua pool tampil di listing utama)."),
                         use_container_width=True):
                st.session_state[BEST_SHOW_HIDDEN_KEY] = not showing_hidden
                st.rerun()
        if error:
            st.warning(f"Meteora API: {error}")
        if fetched:
            quote_txt = (f" · {skipped_quote} pool quote dilewati"
                         if skipped_quote else "")
            st.caption(f"{len(rows)} pool tampil · {hidden} disembunyikan "
                       f"· listing {fetched} pool{quote_txt}.")
        if showing_hidden:
            if not hidden_rows:
                st.info("Tidak ada pool tersembunyi (semua saringan layar "
                        "dihapus 2026-09-13 — semua pool tampil di listing utama).")
                return
            st.caption(
                f"{len(hidden_rows)} pool disembunyikan ditampilkan "
                f"(legacy, urut volume/active TVL lalu dust sebagai info).")
            _render_best_table(hidden_rows, key_prefix="best-pool-hidden")
            return
        if not rows:
            if result:
                st.info("Tidak ada pool yang lolos filter Best Pool "
                        "(atau listing kosong).")
            return
        _render_best_table(rows, key_prefix="best-pool")
