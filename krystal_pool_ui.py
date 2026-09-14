# -*- coding: utf-8 -*-
"""Card **🦅 Scan Best Pool Krystal** (halaman utama, Robinhood Chain 4663).

Tata letak dan rule-nya **meniru** 🏆 Scan Best Pool Meteora
(``best_pool_ui.py``) supaya dua card bisa dibaca dengan cara yang sama:

- **satu tombol** ``🦅 Scan Best Pool Krystal 24H + Holder``; listing pool
  Krystal (``cloud-api.krystal.app/v1/pools``, header ``KC-APIKey``) untuk
  empat protokol chain 4663 — **ramsescl, uniswapv2, uniswapv3, uniswapv4**;
- **F = fee 24 jam ÷ TVL × 100** (field Krystal ``stats24h.fee`` / ``tvl``)
  dan **V = (max high − min low) ÷ min low × 100** dari 24 candle hourly pool
  GeckoTerminal network **robinhood**. **Gate 24H: F/V ≥ 5×** (inklusif,
  ambang :data:`krystal_screener.KRYSTAL_FV_24H_MIN` dibaca saat dipakai).
  V persis 0 → gugur **dan dibuang dari listing** (∞ bukan kelolosan); metrik
  hilang → gugur "metrik tidak tersedia" dan tampil di tabel "dilewati";
- **lalu** holder: hanya pool lolos gate yang di-scan
  ``robinhood_holders.analyze_token`` (Blockscout, FULL 100.000 wallet, tanpa
  budget waktu) → kolom **Dust %MC** (informasi, bukan syarat);
- **urutan baris**: F/V terbesar → volume/TVL terbesar → dust %MC terkecil;
- **4 kolom inti di depan**: Token · **F/V** · **Volat** · **Dust %MC**, lalu
  TVL · Fee/TVL · Vol 24h · APR · Pool (protokol) · ⭐;
- **sorot hijau menyala** (:data:`TOP_HIGHLIGHT_COLOR`) pada sel F/V tertinggi
  dan volatility terbesar tabel utama — seri di puncak ikut semua; tabel
  "dilewati" tidak ditandai;
- **detail rule ada di tooltip judul** (bukan caption panjang — aturan card
  sejak 2026-09-10); caption hanya angka rekap;
- **⭐** memasukkan token ke **Watchlist Robinhood LP** di halaman utama;
- **persisten**: hasil scan disimpan ke berkas cache
  (``scan_result_cache.save_result``, key ``krystal_pool_scan_24h``) dan
  dipulihkan ke ``session_state`` saat sesi kosong, jadi **refresh browser
  tidak menghilangkan tabel**.

Sumber data + rule lengkap: ``docs/krystal_api.md`` dan docstring
:mod:`krystal_screener`.
"""
from __future__ import annotations

import time

# Satu key per lane (card ini baru punya lane 24H); dipakai sebagai session key
# **dan** key cache berkas supaya keduanya tidak pernah bisa berbeda.
KRYSTAL_LANE_SESSION_KEY = "krystal_pool_scan_{}"
KRYSTAL_LANE_HIDDEN_KEY = "krystal_pool_show_hidden_{}"
KRYSTAL_CACHE_KEY = "krystal_pool_scan_{}"

# Lebar kolom: 4 kolom inti di depan (Token, F/V, Volat, Dust %MC), lalu
# konteks pool (TVL, Fee/TVL, Vol 24h, APR), Pool (protokol), ⭐.
_COL_SPEC = [1.5, 0.7, 0.6, 0.82, 0.7, 0.8, 0.85, 0.6, 1.05, 0.4]

# Hijau menyala penanda sel tertinggi (salinan ``best_pool_ui``).
TOP_HIGHLIGHT_COLOR = "#00c853"


def krystal_lane_session_key(lane="24h") -> str:
    """Session key hasil scan satu lane (``krystal_pool_scan_24h``)."""
    from krystal_screener import normalize_krystal_lane

    return KRYSTAL_LANE_SESSION_KEY.format(normalize_krystal_lane(lane))


def krystal_lane_hidden_key(lane="24h") -> str:
    """Session key toggle "N dilewati" satu lane."""
    from krystal_screener import normalize_krystal_lane

    return KRYSTAL_LANE_HIDDEN_KEY.format(normalize_krystal_lane(lane))


def krystal_cache_key(lane="24h") -> str:
    """Key cache berkas hasil scan satu lane."""
    from krystal_screener import normalize_krystal_lane

    return KRYSTAL_CACHE_KEY.format(normalize_krystal_lane(lane))


def krystal_pool_tooltip() -> str:
    """Rule card dalam satu tooltip judul (ambang dibaca saat dipanggil)."""
    from krystal_screener import (KRYSTAL_CHAIN_PARAM, KRYSTAL_PROTOCOLS,
                                  KRYSTAL_VOLATILITY_HOURS,
                                  krystal_lane_gate_label, normalize_krystal_lane,
                                  protocol_label)

    lane = normalize_krystal_lane("24h")
    protocols = ", ".join(protocol_label(item) for item in KRYSTAL_PROTOCOLS)
    return (
        "Listing pool Krystal (Krystal Cloud, 10 unit/call): "
        f"GET cloud-api.krystal.app/v1/pools?chainId={KRYSTAL_CHAIN_PARAM}"
        "&protocol=…&sortBy=0&limit=20 dengan header KC-APIKey — satu request "
        f"per protokol untuk {protocols}, hasilnya digabung dan di-dedup per "
        "alamat pool. F = fee 24 jam / TVL x 100 (field stats24h.fee dan tvl); "
        f"V = (high tertinggi - low terendah) / low terendah x 100 dari "
        f"{KRYSTAL_VOLATILITY_HOURS} candle hourly pool GeckoTerminal network "
        f"robinhood (chain 4663). Gate {krystal_lane_gate_label(lane)} — "
        "inklusif, tepat 5x lolos; pool di bawah ambang langsung di-skip "
        "SEBELUM scan holder (kuota Blockscout tidak terbakar) dan bisa "
        "dilihat lewat tombol 'dilewati'. Volatility 0 (F/V tak terukur) "
        "gugur dan dibuang dari listing: tidak ada pergerakan di pool itu. "
        "Metrik hilang/tidak valid gugur dengan alasan 'metrik tidak "
        "tersedia'; pool tanpa candle GeckoTerminal = 'volatility tidak "
        "tersedia'. Hanya pool lolos yang mengambil holder FULL Blockscout "
        "100.000 wallet (semua kandidat ditunggu sampai selesai) — Dust %MC "
        "murni informasi, bukan syarat; tanpa bukti holder (0 wallet / "
        "terpotong / sampel < 40 wallet) selnya '-', bukan 0,000%. Urutan: "
        "F/V terbesar, lalu volume/TVL terbesar, lalu dust %MC terkecil. "
        "Kolom inti di depan: Token, F/V, Volat, Dust %MC. Sel volatility "
        "terbesar dan F/V tertinggi disorot hijau menyala (seri ikut semua; "
        "tabel dilewati tidak ditandai). Hasil scan disimpan ke cache berkas "
        "lokal, jadi refresh browser tidak menghapus tabel. ⭐ memasukkan "
        "token ke Watchlist Robinhood LP."
    )


def _top_span(text: str) -> str:
    """Bungkus isi sel dengan hijau menyala + bold — penanda tertinggi tabel."""
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
    """``(volatility tertinggi, F/V tertinggi)`` di tabel yang sedang tampil.

    Seri di puncak: semua barisnya ditandai (tidak ada pemenang acak).
    """
    from krystal_screener import row_fv_ratio

    top_vol = top_fv = None
    for row in rows or []:
        vol = _finite_number((row or {}).get("volatility"))
        if vol is not None:
            top_vol = vol if top_vol is None else max(top_vol, vol)
        ratio = row_fv_ratio(row)
        if ratio is not None and _finite_number(ratio) is not None:
            top_fv = ratio if top_fv is None else max(top_fv, ratio)
    return top_vol, top_fv


def _pct_or_dash(value, pattern: str = ".1f") -> str:
    """Persen siap tampil (``None`` → ``—``)."""
    from dashboard_components import _number

    return "—" if value is None else f"{_number(value, pattern)}%"


def _num_or_dash(value, pattern: str = ",.2f") -> str:
    """Angka biasa siap tampil (``None`` → ``—``)."""
    from dashboard_components import _number

    return "—" if value is None else _number(value, pattern)


def _usd_or_dash(value, compact: bool = True) -> str:
    """USD siap tampil: ringkas (``$24.0K``) atau penuh (``$24,000``)."""
    if value is None:
        return "—"
    if compact:
        from dashboard_components import _compact

        return _compact(value)
    from dashboard_components import _number

    return f"${_number(value, ',.0f')}"


def _pct_txt(value, digits: int = 2) -> str:
    """Angka persen siap tampil (``None`` → ``—``)."""
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _cell(value: str, sub: str = "", title: str = "") -> str:
    """Satu sel metrik: angka + baris kecil + tooltip angka penuh."""
    import html as _html

    tip = f' title="{_html.escape(str(title))}"' if title else ""
    return ('<div class="watchlist-metric">'
            f'<div class="watchlist-metric-value">{value}</div>'
            f'<div class="watchlist-metric-sub"{tip}>{sub}</div></div>')


def _fv_cell(row: dict, *, lane: str = "24h", top: bool = False) -> tuple[str, str, str]:
    """Sel **F/V** satu baris + lane (angka, sub syarat, tooltip).

    Baris gagal ambang (hanya mungkin di tabel "dilewati") merah + alasan;
    ``top=True`` (F/V tertinggi tabel utama) mengubahnya jadi **hijau menyala
    + bold** — permintaan user: "tandai f/v tertinggi tersebut menjadi warna
    hijau menyala".
    """
    import math as _math

    from krystal_screener import (krystal_lane_gate_label, row_fv_ratio,
                                  row_krystal_gaps)

    ratio = row_fv_ratio(row)
    gate = krystal_lane_gate_label(lane)
    fails = row_krystal_gaps(row, lane=lane)
    if ratio is None:
        value, color = "—", "#dc2626"
    elif _math.isinf(ratio):
        value, color = "∞", ""
    else:
        value, color = f"{ratio:.1f}×", ""
    sub = f"syarat {gate}"
    tip = (f"F = fee 24 jam / TVL x 100 = "
           f"{_num_or_dash(row.get('fee_tvl_ratio'))}% "
           f"(fee {_usd_or_dash(row.get('fee'), compact=False)} / TVL "
           f"{_usd_or_dash(row.get('tvl'), compact=False)}) ÷ V = volatility "
           f"{_num_or_dash(row.get('volatility'))}% = "
           f"{_num_or_dash(ratio)}× — berapa kali fee pool lebih besar dari "
           f"volatility; kunci urut pertama + syarat lane ({gate}); "
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


def _head_html(rows: list, hidden: int, lane: str, *,
               showing_hidden: bool = False) -> str:
    """Kepala card: judul + pill lane/gate + jumlah pool + yang dilewati."""
    from dashboard_components import card_head_html
    from krystal_screener import KRYSTAL_CARD_TITLE, krystal_lane_gate_label

    gate = krystal_lane_gate_label(lane)
    pills = [f'<span class="lp-count" style="color:#ffffff;background:#0284c7;">'
             f"{gate}</span>",
             f'<span class="lp-count">{len(rows)} pool</span>']
    if hidden:
        tone = ("color:#1e3a8a;background:#bfdbfe;" if showing_hidden
                else "color:#334155;background:#e2e8f0;")
        pills.append(f'<span class="lp-count" style="{tone}">'
                     f"{hidden} dilewati</span>")
    return card_head_html(KRYSTAL_CARD_TITLE, pills,
                          tooltip=krystal_pool_tooltip())


def _render_krystal_table(rows: list, *, lane: str = "24h",
                          key_prefix: str = "krystal-pool",
                          mark_tops: bool = True) -> None:
    """Tabel listing Krystal (utama atau "dilewati") untuk satu lane."""
    import html

    import streamlit as st

    from krystal_screener import (protocol_label, row_dust_pct, row_fv_ratio,
                                  row_vol_tvl_ratio)
    from links import external_links_html, robinhood_pool_links_html
    from robinhood_watchlist import RH_LP_SOURCE, add_to_robinhood_watchlist

    titles = ["Token", "F/V", "Volat", "Dust %MC", "TVL", "Fee/TVL",
              "Vol 24h", "APR", "Pool", ""]
    header_cols = st.columns(_COL_SPEC)
    style = ("font-size:0.72rem;color:#000000;font-weight:700;"
             "text-align:center;")
    for col, title in zip(header_cols, titles):
        col.markdown(f'<div style="{style}">{title}</div>',
                     unsafe_allow_html=True)
    st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)

    top_vol, top_fv = _table_tops(rows) if mark_tops else (None, None)

    for index, row in enumerate(rows):
        ca = str(row.get("ca") or "")
        symbol = str(row.get("symbol") or "?").upper()
        pool = str(row.get("pool_address") or "")
        dust_pct = row_dust_pct(row)
        holders_note = str(row.get("holders_note") or "")
        fv_here = row_fv_ratio(row)
        fv_top = bool(top_fv is not None and fv_here is not None
                      and fv_here == top_fv)
        fv_value, fv_sub, fv_tip = _fv_cell(row, lane=lane, top=fv_top)
        vol_value = _pct_or_dash(row.get("volatility"))
        vol_tip = (f"V = volatility {_num_or_dash(row.get('volatility'))}% — "
                   f"(high tertinggi − low terendah) ÷ low terendah × 100 "
                   f"dari {int(row.get('volatility_candles') or 0)} candle "
                   "hourly pool (GeckoTerminal, network robinhood)"
                   + (f" · {row.get('volatility_note')}"
                      if row.get("volatility_note") else ""))
        vol_here = _finite_number(row.get("volatility"))
        if top_vol is not None and vol_here is not None and vol_here == top_vol:
            vol_value = _top_span(vol_value)
            vol_tip += " — volatility terbesar di tabel ini"
        vol_tvl = row_vol_tvl_ratio(row)
        dust_tip = ("dust holder % MC (Blockscout FULL, pembagi = market cap "
                    "DexScreener kolom MC) — informasi, bukan syarat; "
                    "tie-break urut terakhir (terkecil dulu)")
        if holders_note:
            dust_tip = f"{holders_note} — {dust_tip}"
        label = protocol_label(row.get("protocol"))
        cols = st.columns(_COL_SPEC)
        cols[0].markdown(
            '<div class="watchlist-token">'
            f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
            f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
            f'<div class="watchlist-links">{external_links_html(ca)}</div>'
            "</div>", unsafe_allow_html=True)
        cells = (
            (fv_value, fv_sub, fv_tip),
            (vol_value, "volat", vol_tip),
            (_pct_txt(dust_pct, 3), "dust", dust_tip),
            (_usd_or_dash(row.get("tvl")), "tvl",
             f"TVL pool {_usd_or_dash(row.get('tvl'), compact=False)} — "
             "penyebut F (fee/TVL) dan kunci urut kedua (volume/TVL)"),
            (_pct_or_dash(row.get("fee_tvl_ratio")),
             f"fee {_usd_or_dash(row.get('fee'))}",
             f"F = fee 24 jam {_usd_or_dash(row.get('fee'), compact=False)} ÷ "
             f"TVL {_usd_or_dash(row.get('tvl'), compact=False)} × 100 = "
             f"{_num_or_dash(row.get('fee_tvl_ratio'))}% — pembilang F/V"),
            (_usd_or_dash(row.get("volume")),
             (f"{_num_or_dash(vol_tvl, ',.0f')}× TVL" if vol_tvl is not None
              else "—"),
             f"volume 24 jam {_usd_or_dash(row.get('volume'), compact=False)} · "
             f"rasio volume/TVL {_num_or_dash(vol_tvl)}% — kunci urut kedua "
             "(terbesar dulu)"),
            (_pct_or_dash(row.get("apr")), "apr",
             f"APR 24 jam {_num_or_dash(row.get('apr'))}% dari Krystal — "
             "informasi, bukan syarat"),
            (f'<span title="{html.escape(pool)}">{html.escape(label)}</span>',
             # ``feeTier`` Krystal satuannya beda per protokol (500 = 0,05% di
             # Uniswap V3), jadi yang ditampilkan nilainya apa adanya —
             # jangan ditebak jadi persen.
             f"tier {_num_or_dash(row.get('fee_tier'), '.0f')}"
             if row.get("fee_tier") is not None else "pool",
             f"pool {pool} · protokol {label} · pasangan "
             f"{row.get('pair') or '?'} — sumber listing Krystal "
             f"(chain 4663)"),
        )
        for position, (value, sub, tip) in enumerate(cells, start=1):
            cols[position].markdown(_cell(value, sub, tip),
                                    unsafe_allow_html=True)
        # Kolom Pool: nama protokol (sumber listing) + tautan explorer alamat
        # pool-nya, ditumpuk di sel yang sama (baris kecil tetap terbaca).
        pool_html = robinhood_pool_links_html(pool) or "<span>—</span>"
        cols[8].markdown(f'<div class="pool-links">{pool_html}</div>',
                         unsafe_allow_html=True)
        star_key = f"{key_prefix}-star-{pool or ca or index}"
        if cols[9].button(
                "⭐", key=star_key,
                help="Tambah ke Watchlist Robinhood LP (halaman utama, "
                     "scan cron ±5 menit)",
                use_container_width=True):
            if ca:
                add_to_robinhood_watchlist(
                    ca, symbol, note="Scan Best Pool Krystal",
                    source=RH_LP_SOURCE, background=True)
                st.success(f"${symbol} masuk Watchlist Robinhood")
        st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)


def _run_lane_scan(lane: str = "24h", *, progress=None) -> dict:
    """Satu kali scan lane — kegagalan jadi pesan card, bukan exception."""
    from krystal_screener import scan_krystal_lane

    try:
        return scan_krystal_lane(lane, progress=progress)
    except Exception as exc:  # noqa: BLE001 - kegagalan = pesan card
        return {"rows": [], "hidden_rows": [], "error": str(exc),
                "fetched": 0, "hidden_metric": 0,
                "dropped_volatility": 0, "skipped_quote": 0,
                "volatility_missing": 0, "lane": lane}


def _api_key_warning() -> None:
    """Peringatan "pasang KRYSTAL_API_KEY" — ditulis sekali, tanpa nilai key."""
    import streamlit as st

    st.warning(
        "KRYSTAL_API_KEY belum terpasang — listing pool Krystal butuh API key "
        "(Krystal Cloud, 10 unit/call; 50.000 unit gratis). Pasang di "
        "`.streamlit/secrets.toml` **dan** Streamlit Cloud → Settings → "
        "Secrets:\n\n```toml\nKRYSTAL_API_KEY = \"key-mu\"\n```\n\n"
        "Berkas itu sudah di-gitignore — jangan pernah di-commit.")


def render_krystal_pool_scan(lane: str = "24h") -> None:
    """Card **🦅 Scan Best Pool Krystal** — border container + tabel lane.

    Hasil scan dibaca dari ``session_state``; bila sesi kosong (baru refresh
    browser) hasilnya dipulihkan dari cache berkas lokal
    (:mod:`scan_result_cache`).
    """
    import streamlit as st

    import scan_result_cache
    from krystal_screener import (api_key_configured, normalize_krystal_lane,
                                  row_krystal_gaps, row_volatility_zero,
                                  sort_krystal_rows)

    with st.container(border=True):
        active = normalize_krystal_lane(lane)
        session_key = krystal_lane_session_key(active)
        hidden_key = krystal_lane_hidden_key(active)
        cache_key = krystal_cache_key(active)

        # Pulihkan hasil scan sebelumnya saat session_state kosong (refresh
        # browser / tab baru) — cache berkas lokal, bukan scan ulang.
        scan_result_cache.restore_into_session(st, cache_key, session_key)

        if not api_key_configured():
            st.markdown(_head_html([], 0, active), unsafe_allow_html=True)
            _api_key_warning()
            return

        stored = st.session_state.get(session_key) or {}
        count = len(stored.get("rows") or [])
        label = "24H"
        if count:
            # Angka rekap saja (aturan card: detail rule hidup di tooltip).
            st.caption(f"{count} pool tersimpan")
        if st.button(f"🦅 Scan Best Pool Krystal {label} + Holder",
                     type="primary", key=f"krystal-pool-scan-{active}",
                     use_container_width=True,
                     help="Listing pool Krystal (chain robinhood@4663) untuk "
                          "ramsescl + uniswapv2/v3/v4, disaring F/V ≥ 5× "
                          "SEBELUM scan holder — pool di bawah ambang "
                          "langsung di-skip, holdernya tidak di-fetch."):
            bar = st.progress(0.0, text="Listing pool Krystal…")

            def _progress(index, total, note):
                bar.progress(index / max(total, 1),
                             text=f"{index}/{total} · {note}")

            result = _run_lane_scan(active, progress=_progress)
            bar.empty()
            st.session_state[session_key] = result
            st.session_state[hidden_key] = False
            # Simpan sesudah scan: refresh browser tidak menghapus hasil.
            scan_result_cache.save_result(cache_key, result)
            st.rerun()

        if not stored:
            st.markdown(_head_html([], 0, active), unsafe_allow_html=True)
            st.caption("belum di-scan")
            st.info(f"Belum ada hasil scan lane {label}. Tekan tombol "
                    f"🦅 Scan Best Pool Krystal {label} + Holder untuk "
                    "memindai lane ini.")
            return

        stored_rows = list(stored.get("rows") or [])
        # Hasil lama di session_state/cache bisa belum memakai rule terbaru:
        # disaring + diurutkan ulang saat render supaya listing konsisten
        # tanpa scan ulang (pola yang sama dengan card Best Pool Meteora).
        newly_hidden = [row for row in stored_rows
                        if row_krystal_gaps(row, lane=active)]
        stored_rows = [row for row in stored_rows
                       if not row_volatility_zero(row)]
        rows = sort_krystal_rows([row for row in stored_rows
                                  if not row_krystal_gaps(row, lane=active)])
        hidden_rows = sort_krystal_rows(
            [row for row in (list(stored.get("hidden_rows") or [])
                             + newly_hidden)
             if not row_volatility_zero(row)])
        hidden = len(hidden_rows)
        error = str(stored.get("error") or "")
        fetched = int(stored.get("fetched") or 0)
        skipped_quote = int(stored.get("skipped_quote") or 0)
        showing_hidden = bool(st.session_state.get(hidden_key))

        st.markdown(_head_html(rows, hidden, active,
                               showing_hidden=showing_hidden),
                    unsafe_allow_html=True)
        if hidden:
            view = ("◀ kembali ke tabel yang lolos" if showing_hidden
                    else f"▶ {hidden} pool dilewati")
            if st.button(view, key=f"krystal-pool-toggle-hidden-{active}",
                         help="Tampilkan kandidat yang di-skip karena di bawah "
                              "ambang F/V lane ini; holdernya tidak pernah "
                              "di-scan.",
                         use_container_width=True):
                st.session_state[hidden_key] = not showing_hidden
                st.rerun()
        if error:
            st.warning(f"Krystal API: {error}")
        if fetched:
            quote_txt = (f" · {skipped_quote} pool quote dilewati"
                         if skipped_quote else "")
            st.caption(f"{len(rows)} pool {label} tampil · {hidden} dilewati "
                       f"· listing {fetched} pool{quote_txt}.")
        analyzed_at = int(stored.get("analyzed_at") or 0)
        if analyzed_at:
            stamp = time.strftime("%d %b %Y %H:%M WIB",
                                  time.localtime(analyzed_at))
            st.caption(f"Hasil scan {stamp} · tersimpan di cache lokal, "
                       "tahan refresh browser.")
        if showing_hidden:
            if not hidden_rows:
                st.info("Tidak ada pool tersembunyi di lane ini.")
                return
            st.caption(f"{len(hidden_rows)} pool {label} dilewati ditampilkan "
                       "· detail holder tidak diambil untuk kandidat ini.")
            _render_krystal_table(hidden_rows, lane=active,
                                  key_prefix=f"krystal-pool-hidden-{active}",
                                  mark_tops=False)
            return
        if not rows:
            st.info(f"Tidak ada pool {label} yang lolos filter Best Pool "
                    "Krystal (atau listing kosong).")
            return
        _render_krystal_table(rows, lane=active,
                              key_prefix=f"krystal-pool-{active}")
