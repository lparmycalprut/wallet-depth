# -*- coding: utf-8 -*-
"""Temporarily parked sections; data and actions remain available."""
from __future__ import annotations


METEORA_CARD_TITLE = "🌊 Scan Meteora Pool"


def meteora_scan_tooltip() -> str:
    """Detail karakteristik card — teks tooltip di judul (bukan caption).

    Sama seperti dua card scan best di halaman utama (konvensi 2026-09-10):
    caption panjang di badan card dihapus, seluruh isinya pindah ke atribut
    ``title`` pada teks judul, jadi hanya muncul saat kursor digeser ke judul.
    Permintaan user 2026-09-11 mengkonfirmasi: tulisan rule memang tidak perlu
    dua-duanya. Atribut ``title`` tidak mengenal markdown (plain text tanpa
    ``**``); semua ambang dibaca dari konstanta rule saat dipanggil — impor di
    dalam fungsi supaya modul halaman tetap ringan.
    """
    import holder_history
    import meteora_screener

    return (
        "Top DLMM 24 jam "
        f"(active_tvl ≥ {meteora_screener.TVL_MIN:g}, "
        "fee_active_tvl_ratio ≥ "
        f"{meteora_screener.FEE_RATIO_24H:g}) dibandingkan 1 jam "
        f"(fee_active_tvl_ratio ≥ {meteora_screener.FEE_RATIO_1H:g}). "
        "Pool 24 jam yang masih muncul di 1 jam tetap ditampilkan. Hanya pool "
        f"dengan dust holder ≤ {holder_history.DUST_SCAN_HIDE_PCT:g}% MC yang "
        "ditampilkan — sisanya disembunyikan (badge AMAN/HATI-HATI/BAHAYA "
        "tidak dipakai di sini). Dust "
        f"< {holder_history.DUST_BEST_PCT:g}% MC + data holder valid "
        f"(≥ {holder_history.DUST_BEST_MIN_HOLDERS:g} wallet) + TVL ≥ "
        f"${holder_history.DUST_BEST_MIN_TVL_USD / 1000:g}K diberi badge 🏆 "
        "BEST POOL dan diurutkan paling atas, lalu dust % MC terkecil dan TVL "
        "terbesar. ⭐ memasukkan token ke card Watchlist Meteora di halaman "
        "utama. Tombol kanan: Meteora + HawkFi.")


def _meteora_head_html(rows: list, hidden: int, best_count: int) -> str:
    """Header card Scan Meteora: jumlah pool + rekap BEST / disembunyikan."""
    from dashboard_components import card_head_html

    pills = [f'<span class="lp-count">{len(rows)} pool</span>']
    if best_count:
        pills.append('<span class="lp-count" style="color:#3b2f0a;'
                     'background:#fde047;border:1px solid #facc15;">'
                     f'🏆 {best_count} BEST</span>')
    if hidden:
        pills.append('<span class="lp-count" style="color:#334155;'
                     f'background:#e2e8f0;">{hidden} disembunyikan</span>')
    return card_head_html(METEORA_CARD_TITLE, pills,
                          tooltip=meteora_scan_tooltip())


def render_meteora_scan() -> None:
    """Card **Scan Meteora Pool** — dipindah dari halaman utama ke temp
    (2026-09-10); ⭐-nya tetap memasukkan token ke card **Watchlist
    Meteora** di halaman utama."""
    import html

    import streamlit as st

    from dashboard_components import (_compact, _dust_best_html, _number)
    from holder_history import FULL_SCAN_MAX_WALLETS
    from links import external_links_html, pool_links_html
    from lp_watchlist import LP_SOURCE
    from meteora_screener import row_flag, scan_meteora, sort_rows
    from watchlist import add_to_watchlist

    with st.container(border=True):
        # Kepala card butuh angka hasil scan terakhir, jadi hasil disimpan /
        # dibaca lebih dulu — pill ringkasan dan listing di bawahnya selalu
        # satu sumber data (selesai scan → ``st.rerun()`` seperti card LP).
        if st.button("🌊 Scan Meteora + Holder", type="primary",
                     key="meteora-scan-now", use_container_width=True):
            bar = st.progress(0.0, text="Listing pool Meteora…")

            def _progress(index, total, label):
                bar.progress(index / max(total, 1),
                             text=f"Holder {index}/{total} · {label}")

            try:
                # FULL: filter dust > 0,1% MC di listing butuh dust akurat;
                # cap 2000 dulu = sampel bias (urutan Helius tidak urut
                # saldo).
                result = scan_meteora(max_wallets=FULL_SCAN_MAX_WALLETS,
                                      workers=6, progress=_progress)
            except Exception as exc:  # noqa: BLE001
                result = {"rows": [], "error": str(exc), "hidden_dust": 0,
                          "fetched": 0}
            finally:
                bar.empty()
            st.session_state["meteora_scan"] = result
            st.rerun()

        result = st.session_state.get("meteora_scan") or {}
        error = result.get("error") or ""
        # BEST POOL selalu di atas. scan_meteora() sudah mengurutkan, tapi
        # hasil lama yang tersimpan di session_state (sebelum fitur ini)
        # belum — urutkan lagi di sini supaya listing konsisten tanpa perlu
        # scan ulang.
        rows = sort_rows(result.get("rows") or [])
        hidden = int(result.get("hidden_dust") or 0)
        fetched = int(result.get("fetched") or 0)
        best_count = sum(1 for row in rows if row_flag(row).get("best"))

        # Tidak ada caption ambang lagi (2026-09-11): seluruh deskripsi rule
        # hanya ada di tooltip judul — lihat ``meteora_scan_tooltip()``.
        st.markdown(_meteora_head_html(rows, hidden, best_count),
                    unsafe_allow_html=True)
        if error:
            st.warning(f"Meteora API: {error}")
        if fetched:
            best_txt = (f" · 🏆 {best_count} BEST POOL" if best_count else "")
            st.caption(f"{len(rows)} pool ditampilkan · {hidden} disembunyikan"
                       f" · listing {fetched}{best_txt}.")
        if not rows:
            if result:
                st.info("Tidak ada pool yang lolos filter dust (atau "
                        "listing kosong).")
            return

        col_spec = [1.6, 0.8, 0.8, 0.7, 0.9, 0.7, 1.2, 0.45]
        header_cols = st.columns(col_spec)
        titles = ["Token", "MC", "TVL", "Dust", "Dust %MC", "TF", "Pool", ""]
        style = ("font-size:0.72rem;color:#000000;font-weight:700;"
                 "text-align:center;")
        for col, title in zip(header_cols, titles):
            col.markdown(f'<div style="{style}">{title}</div>',
                         unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)

        for index, row in enumerate(rows):
            ca = str(row.get("ca") or "")
            symbol = str(row.get("symbol") or "?").upper()
            pool = str(row.get("pool_address") or "")
            dust_count = row.get("dust_count")
            dust_pct = row.get("dust_pct_mc")
            tvl = row.get("tvl")
            # BEST POOL butuh bukti data holder valid (bukan cuma angka) +
            # TVL pool ≥ 10K: guard ada di dust_flag(holders=…, tvl=…),
            # lihat holder_history._holders_valid_for_best /
            # _tvl_valid_for_best.
            flag = row_flag(row)
            tf = []
            if row.get("in_24h"):
                tf.append("24H")
            if row.get("in_1h"):
                tf.append("1H")
            tf_txt = "+".join(tf) or "—"
            cols = st.columns(col_spec)
            cols[0].markdown(
                f'<div class="watchlist-token">'
                f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
                f'<span class="watchlist-mint">{html.escape(ca[:8])}…</span>'
                f'<div class="watchlist-links">{external_links_html(ca)}</div>'
                f"</div>", unsafe_allow_html=True)
            cols[1].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{_compact(row.get("mc"))}</div></div>',
                unsafe_allow_html=True)
            tvl_txt = "—" if tvl is None else _compact(tvl)
            cols[2].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{tvl_txt}</div><div class="watchlist-metric-sub">tvl</div>'
                '</div>', unsafe_allow_html=True)
            cols[3].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f'{_number(dust_count, ".0f")}</div>'
                '<div class="watchlist-metric-sub">wallet</div></div>',
                unsafe_allow_html=True)
            pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.2f}%"
            # Badge level (AMAN/HATI-HATI/BAHAYA) sengaja TIDAK dirender di
            # listing ini sejak 2026-09-07: semua baris sudah ≤ 0,1% MC,
            # jadi hanya chip 🏆 BEST POOL yang informatif.
            cols[4].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f"{pct_txt}</div>{_dust_best_html(flag)}</div>",
                unsafe_allow_html=True)
            cols[5].markdown(
                '<div class="watchlist-metric">'
                '<div class="watchlist-metric-value">'
                f"{html.escape(tf_txt)}</div></div>", unsafe_allow_html=True)
            pool_html = pool_links_html(pool) or '<span>—</span>'
            cols[6].markdown(
                f'<div class="pool-links">{pool_html}</div>',
                unsafe_allow_html=True)
            # Key diikat ke pool/CA, bukan nomor baris: urutan listing
            # berubah (BEST POOL naik ke atas) sehingga key berbasis index
            # bisa membuat klik ⭐ menempel ke token yang berbeda setelah
            # re-render.
            star_key = f"meteora-star-{pool or ca or index}"
            if cols[7].button("⭐", key=star_key,
                              help="Tambah ke Watchlist Meteora "
                                   "(halaman utama)",
                              use_container_width=True):
                if ca:
                    add_to_watchlist(ca, symbol, source=LP_SOURCE,
                                     background=True)
                    st.success(f"${symbol} masuk Watchlist Meteora")
            st.markdown('<hr style="margin:0.25rem 0;border-color:#cbd5e1;">',
                        unsafe_allow_html=True)


def render_temp() -> None:
    from datetime import datetime, timezone
    import html

    import streamlit as st

    from holder_history import (DUST_CAUTION_PCT,
                                DUST_DANGER_PCT, dust_flag,
                                FULL_SCAN_MAX_WALLETS,
                                holders_usable, ingest_many,
                                resample_4h,
                                usable_points)
    from links import (external_links_html, holder_analytic_link_html)
    import alert_settings
    from lp_watchlist import (LP_SOURCE, split_watchlist)
    from robinhood_watchlist import (split_robinhood_watchlist)
    from holder_analysis import DUST_LIMIT_USD, analyze_token
    from holder_status import (publish_holder_status)
    from trending_ui import (merge_scan_rows, render_trending, run_screen,
                             run_screen_h1, run_screen_hrhr, run_screen_hrhr_h1)
    from watchlist import (add_to_watchlist, get_last_push_error, remove_from_watchlist, remove_many_from_watchlist,
                           set_watchlist_source)
    from watchlist_detail import (SORT_DEFAULT, SORT_DROP, SORT_LABELS,
                                  SORT_NAME, SORT_OPTIONS, SORT_PCT,
                                  SOURCE_HISTORY, SOURCE_SNAPSHOT, STALE_REGULAR_AFTER_SEC,
                                  change_html,
                                  dust_change_since_added, format_wib,
                                  previous_pct, resolve_view, row_sort_key,
                                  sync_caption_text, sync_summary)

    from dashboard_components import (_ca_error, _dust_badge_html,
                                      _points_for, _render_alert_note,
                                      _render_dust_change, _render_rh_card,
                                      _store_alert_note,
                                      load_dashboard_data, render_styles,
                                      ALERT_NOTE_KEY)
    from telegram_alerts import process_holder_alerts
    import robinhood_best_scan

    render_styles()
    st.title("temp")
    st.caption("Bagian yang sementara tidak digunakan. Watchlist dan data holder "
               "tetap tersimpan; tidak ada token yang dihapus atau dipindah lane.")
    st.page_link("app.py", label="Kembali ke halaman utama", icon="🏠")

    data = load_dashboard_data()
    watchlist, holder_status, history_store = data.watchlist, data.status, data.history
    status_tokens = holder_status.get("tokens") or {}
    _, holder_watch = split_watchlist(watchlist)
    _, rh_regular_watch = split_robinhood_watchlist(data.rh_watchlist)
    _render_rh_card(rh_regular_watch, data.rh_status.get("tokens") or {},
                    data.rh_history, int(datetime.now(timezone.utc).timestamp()),
                    variant="regular", merge_status=data.rh_status)

    HOLDER_TAB = "📋 Watchlist Holder"
    LP_TAB = "🌊 Watchlist Meteora"
    ADD_TARGETS = [HOLDER_TAB, LP_TAB]
    ADD_TARGET_SOURCE = {HOLDER_TAB: "manual", LP_TAB: LP_SOURCE}

    # Satu angka per baris watchlist: snapshot cron **atau** titik history yang
    # lebih baru (scan manual / cron yang publish snapshot-nya gagal). Dihitung
    # sekali di sini supaya caption "scan terakhir" dan angka di baris selalu
    # bicara tentang data yang sama (sebelumnya baris membaca snapshot sementara
    # grafik membaca history — dua angka untuk satu token).
    _now_ts = int(datetime.now(timezone.utc).timestamp())
    _holder_points = {mint: _points_for(mint, status_tokens.get(mint) or {},
                                        history_store)
                      for mint in holder_watch}
    # Watchlist biasa di-scan cron tiap ±4 jam → ambang "basi" baris mengikuti
    # kadens itu (bukan 2 jam milik watchlist LP).
    _holder_views = {mint: resolve_view(status_tokens.get(mint) or {}, points,
                                        now=_now_ts,
                                        stale_after=STALE_REGULAR_AFTER_SEC)
                     for mint, points in _holder_points.items()}
    _watch_sync = sync_summary(_holder_views.values(), now=_now_ts)

    st.subheader("📋 Watchlist — Analisa Holder (Dust)")
    st.caption(
        "Ringkasan dust: jumlah wallet dan **berapa % marketcap** yang mereka "
        f"pegang. ≥ {DUST_CAUTION_PCT:g}% MC = HATI-HATI · "
        f"≥ {DUST_DANGER_PCT:g}% MC = BAHAYA "
        "(dust nambah pesat = jejak distribusi). "
        f"Ambang dust: ${DUST_LIMIT_USD:.0f}. "
        "Grafik perubahan dust holder (bucket 4 jam, ala Watchlist Meteora) "
        "ada di expander tiap baris. Kolom **Sejak masuk** = perubahan "
        "dust % MC sejak token ditambahkan sampai scan terakhir (hijau bila turun "
        "≥ 50%, merah bila naik ≥ 100%). Token dari Scan Meteora ada di "
        "card **Watchlist Meteora** di halaman utama. Cadens cron: semua "
        "watchlist LP (Watchlist Meteora + Robinhood LP) **±5 menit**. "
        "Watchlist biasa **tidak** "
        "di-scan cron (slot 4 jam dimatikan) — pakai tombol scan manual."
    )
    st.caption(sync_caption_text(_watch_sync,
                                 status_updated_at=holder_status.get("updated_at"),
                                 stale_after=STALE_REGULAR_AFTER_SEC))

    # --- Tombol on/off notifikasi Telegram (watchlist biasa saja) --------------
    # Permintaan user 2026-09-06: watchlist biasa kadang cukup dipantau di
    # dashboard tanpa pesan Telegram. Scope SENGAJA hanya watchlist Solana biasa
    # — Chart LP Meteora dan kedua card Robinhood tidak ikut dimatikan. Saat
    # OFF, cron tetap scan + tetap memajukan marker 🚨; hanya pengiriman
    # pesannya yang dilewati.
    _notif_on = alert_settings.regular_telegram_enabled()
    _notif_toggle = st.toggle(
        "🔔 Notifikasi Telegram watchlist biasa",
        value=_notif_on, key="regular-telegram-toggle",
        help=("ON = notifikasi 🚨 WAKTUNYA GANTI STRATEGI (satu-satunya "
              "notifikasi) untuk watchlist biasa dikirim ke Telegram. OFF = "
              "token tetap di-scan dan grafiknya tetap jalan, pesannya saja "
              "yang tidak dikirim. Tidak memengaruhi Watchlist Meteora maupun "
              "watchlist Robinhood."))
    if bool(_notif_toggle) != bool(_notif_on):
        _saved = alert_settings.set_regular_telegram_enabled(bool(_notif_toggle))
        if not _saved:
            st.warning("Pilihan tersimpan lokal, tapi sinkronisasi ke GitHub "
                       "gagal — cron mungkin masih memakai setelan lama.",
                       icon="⚠️")
        st.rerun()
    st.caption(
        ("Notif Telegram watchlist biasa **AKTIF**." if _notif_toggle else
         "Notif Telegram watchlist biasa **NONAKTIF** — scan & grafik tetap "
         "jalan, pesan tidak dikirim.")
        + " Watchlist Meteora dan Robinhood tidak terpengaruh tombol ini.")


    if holder_watch and not status_tokens:
        st.warning(
            "Belum ada data holder dari cron (`holder_status.json` di branch "
            "`holder-live` kosong/tidak ada). Pastikan secret **HELIUS_API_KEY** "
            "dan **GITHUB_TOKEN/GH_TOKEN** terpasang di GitHub Actions, atau klik "
            "**Scan holder watchlist** untuk mengisi data sekarang.",
            icon="⚠️")
    elif holder_watch:
        _missing = [str((m or {}).get("symbol") or ca[:6]).upper()
                    for ca, m in holder_watch.items()
                    if not ((status_tokens.get(ca) or {}).get("holders") or {}
                            ).get("total_fetched")]
        if _missing:
            st.info("Holder belum terambil untuk: " + ", ".join(_missing[:8])
                    + (" …" if len(_missing) > 8 else "")
                    + ". Cron LP mencoba tiap ±5 menit; watchlist biasa tidak "
                      "di-scan cron (4 jam dimatikan) — pakai scan manual.",
                    icon="ℹ️")

    if st.button("🔄 Scan holder watchlist", type="primary",
                 use_container_width=True):
        analyses = {}
        total = len(holder_watch)
        bar = st.progress(0.0, text=f"Scan 0/{total} token…")
        done = 0
        for mint, meta in holder_watch.items():
            try:
                cohort = ((history_store.get("tokens") or {}).get(mint) or {}).get(
                    "cohort") or {}
                addrs = list((cohort.get("balances") or {}).keys())
                analyses[mint] = analyze_token(
                    mint, (meta or {}).get("symbol") or "?",
                    max_wallets=FULL_SCAN_MAX_WALLETS,
                    fetch_market=True, cohort_addrs=addrs)
            except Exception:  # noqa: BLE001
                analyses[mint] = None
            done += 1
            bar.progress(done / max(total, 1),
                         text=f"Scan {done}/{total} · "
                              f"{str((meta or {}).get('symbol') or '?')}")
        bar.empty()
        ok = {mint: item for mint, item in analyses.items()
              if isinstance(item, dict)}
        # Scan yang holdernya **tidak lengkap** (provider mengembalikan sampel
        # pendek, mis. 20 wallet) tidak boleh menimpa angka yang sudah
        # tercatat: dust dari sampel pendek selalu 0 dan akan terbaca seperti
        # "dust habis" (lihat holder_history.holders_usable).
        fresh = {mint: item for mint, item in ok.items()
                 if holders_usable(item.get("holders"))}
        skipped_short = sorted(set(ok) - set(fresh))
        failed = sorted(mint for mint, item in analyses.items()
                        if not isinstance(item, dict))
        _published = None
        if fresh:
            # Alert ikut dievaluasi + dikirim dari scan manual (permintaan user
            # 2026-09-09). Lane watchlist biasa TIDAK di-scan cron sejak
            # 2026-09-07, jadi tombol ini satu-satunya jalur notifikasi lane
            # itu — tanpa evaluasi di sini token biasa tidak pernah bisa
            # mengirim notif. Sebelum ingest_many supaya state alert ikut
            # tersimpan; advance_anchors=False = anchor 4 jam cron tidak
            # digeser. Tombol on/off notif watchlist biasa tetap dihormati
            # lewat mute_mints (evaluasi jalan, kirim dilewati).
            _store_alert_note(process_holder_alerts(
                fresh, history_store,
                mute_mints=(set() if alert_settings.regular_telegram_enabled()
                            else set(holder_watch)),
                watchlist_meta=holder_watch,
                advance_anchors=False), f"{ALERT_NOTE_KEY}regular")
            # ``detail=False``: baseline scan FULL + ``latest_detail`` +
            # kronologi (data awal yang sudah tercatat) **tidak disentuh** —
            # scan ini hanya menambah titik baru di atasnya.
            ingest_many(fresh, store=history_store)
            # ``merge_status``: token yang gagal / tidak dapat scan layak tetap
            # memakai snapshot sebelumnya. ``snapshot_status`` membangun
            # ``tokens`` dari analyses yang diberikan saja, jadi tanpa merge
            # baris token yang tidak ikut scan run ini **hilang** dari
            # dashboard (data awalnya tertimpa).
            _published = publish_holder_status(fresh, watchlist, push=False,
                                               history_store=history_store,
                                               merge_status=holder_status)
        st.session_state["watchlist_scan_report"] = {
            "total": total, "updated": len(fresh), "failed": len(failed),
            "short": len(skipped_short),
            "snapshot_ts": ((_published or holder_status).get("updated_at")),
            "short_symbols": [str((watchlist.get(mint) or {}).get("symbol")
                                  or mint[:6]).upper()
                              for mint in skipped_short[:6]],
        }
        st.session_state["status_force_refresh"] = True
        st.rerun()

    _scan_report = st.session_state.pop("watchlist_scan_report", None)
    if isinstance(_scan_report, dict):
        _bits = [f"{_scan_report.get('updated') or 0} token diperbarui"]
        _kept = ((_scan_report.get("total") or 0)
                 - (_scan_report.get("updated") or 0))
        if _kept > 0:
            _bits.append(f"{_kept} token tetap memakai data yang sudah tercatat")
        if _scan_report.get("failed"):
            _bits.append(f"{_scan_report['failed']} scan gagal")
        if _scan_report.get("short"):
            _names = ", ".join(_scan_report.get("short_symbols") or [])
            _bits.append(f"{_scan_report['short']} scan tidak lengkap dilewati "
                         f"({_names}) — angka lama dipertahankan")
        _bits.append("list holder diperbarui sampai snapshot "
                     f"**{format_wib(_scan_report.get('snapshot_ts'))}**")
        st.info("Scan watchlist selesai: " + " · ".join(_bits)
                + ". Baseline scan FULL, latest detail, dan kronologi tidak "
                  "ditimpa; tiap baris menampilkan angka sesuai waktu "
                  "snapshotnya sendiri.", icon="✅")
    _render_alert_note(f"{ALERT_NOTE_KEY}regular")

    # Laporan tombol 🗑️ Hapus semua (ditulis sebelum st.rerun di bawah) supaya
    # hasilnya terlihat di tempat card yang baru saja dikosongkan.
    _clear_report = st.session_state.pop("watchlist_clear_report", None)
    if isinstance(_clear_report, dict):
        _n = int(_clear_report.get("removed") or 0)
        if _n > 0:
            st.success(f"{_n} token dihapus dari watchlist biasa. Commit GitHub "
                       "berjalan di latar belakang; card Watchlist Meteora "
                       "dan watchlist Robinhood tidak disentuh.", icon="🗑️")
        else:
            st.info("Tidak ada token watchlist biasa yang dihapus.", icon="ℹ️")

    if not holder_watch:
        st.info("Watchlist holder kosong. Tambahkan contract address di bawah, "
                "atau pindahkan token dari card Chart LP (📋).")
    else:
        # Perubahan "Sejak masuk" per token dihitung sekali di sini karena
        # dipakai untuk urutan baris DAN dirender di kolomnya.
        _change_by_mint = {
            mint: dust_change_since_added(meta, _holder_points.get(mint) or [],
                                          _holder_views.get(mint) or {},
                                          now=_now_ts)
            for mint, meta in holder_watch.items()}

        # Urutan baris (permintaan user 2026-09-05): default token dengan minus
        # dust holder terbesar (dust % MC turun paling banyak sejak masuk) di
        # atas — mis. GPRO −60% dari awal watchlist.
        _sort_keys = [key for key, _label in SORT_OPTIONS]
        # ``vertical_alignment="bottom"``: selectbox punya label di atasnya,
        # tombol 🗑️ tidak — tanpa ini tombolnya menggantung sejajar label.
        _sort_col, _sort_note, _clear_col = st.columns(
            [0.30, 0.50, 0.20], vertical_alignment="bottom")
        sort_mode = _sort_col.selectbox(
            "Urutkan baris watchlist", options=_sort_keys,
            index=_sort_keys.index(SORT_DEFAULT),
            format_func=lambda key: SORT_LABELS.get(str(key), str(key)))
        _sort_notes = {
            SORT_DROP: ("Token dengan <b>minus dust terbesar sejak masuk</b> di "
                        "paling atas (dust % MC turun paling banyak, mis. "
                        "−60%) — yang belum ada pembanding di bawah."),
            SORT_PCT: ("Token dengan <b>dust % MC saat ini tertinggi</b> di "
                       "paling atas (risiko distribusi / BAHAYA lebih dulu)."),
            SORT_NAME: "Urutan alfabetis A–Z (urutan lama).",
        }
        _sort_note.markdown(
            '<div style="font-size:0.72rem;color:#64748b;">'
            f"{_sort_notes.get(str(sort_mode), '')}</div>",
            unsafe_allow_html=True)

        # --- 🗑️ Hapus semua (watchlist biasa saja) ------------------------------
        # Permintaan user 2026-09-06. Scope = ``holder_watch`` (hasil
        # ``split_watchlist``: token Solana non-LP) — Chart LP Meteora dan kedua
        # card Robinhood punya file/watchlist sendiri dan SENGAJA tidak ikut.
        # Aksi destruktif atas puluhan token → butuh konfirmasi eksplisit di
        # popover; satu journal + satu commit latar (bukan N klik ✕).
        _clear_total = len(holder_watch)
        with _clear_col.popover("🗑️ Hapus semua", use_container_width=True,
                                help=("Kosongkan watchlist biasa (semua baris "
                                      "card ini). Watchlist Meteora dan watchlist "
                                      "Robinhood tidak ikut terhapus.")):
            st.markdown(
                f"Hapus **{_clear_total} token** dari watchlist biasa?  \n"
                "Termasuk token `degen` yang dipantau **🚀 Pre-Pump Screener**. "
                "**Tidak** menyentuh Watchlist Meteora maupun watchlist "
                "Robinhood. History holder yang sudah tercatat tidak dihapus.")
            if st.button(f"Ya, hapus {_clear_total} token",
                         key="clear-regular-watchlist", type="primary",
                         use_container_width=True):
                _cleared = remove_many_from_watchlist(
                    list(holder_watch), note="watchlist biasa", background=True)
                st.session_state["watchlist_clear_report"] = {
                    "removed": int(_cleared.get("removed") or 0),
                    "saved": _cleared.get("saved"),
                }
                st.rerun()

        header_cols = st.columns([1.55, 0.85, 0.9, 1.05, 0.4, 0.4, 0.4])
        header_style = "font-size:0.78rem;color:#000000;font-weight:700;"
        center = "text-align:center;" + header_style
        header_titles = ["Token", "Dust", "Hold %MC", "Sejak masuk",
                         "", "", ""]
        header_css = [header_style] + [center] * 6
        for col, style, title in zip(header_cols, header_css, header_titles):
            col.markdown(f'<div style="{style}">{title}</div>',
                         unsafe_allow_html=True)

        st.markdown(
            '<div style="font-size:0.65rem;color:#64748b;margin:0.3rem 0;">'
            "Dust = wallet 0 &lt; value ≤ $10 (bukan LP). "
            "<b>Sejak masuk</b> = perubahan dust % MC dari "
            "titik pertama setelah token ditambahkan sampai scan terakhir "
            "(<span style=\"color:#15803d;font-weight:700;\">hijau</span> turun "
            "≥ 50% · <span style=\"color:#b91c1c;font-weight:700;\">merah</span> "
            "naik ≥ 100%). 🧮 buka Holder Analytic · 🌊 pindahkan ke "
            "Watchlist Meteora."
            "</div>",
            unsafe_allow_html=True)

        st.markdown('<hr style="margin:0.5rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)

        ordered = sorted(
            holder_watch.items(),
            key=lambda item: row_sort_key(
                sort_mode,
                pct_change=(_change_by_mint.get(item[0]) or {}).get("pct_change"),
                dust_pct=(_holder_views.get(item[0]) or {}).get("dust_pct"),
                symbol=str((status_tokens.get(item[0]) or {}).get("symbol")
                           or item[1].get("symbol") or "?")))
        for mint, meta in ordered:
            token = status_tokens.get(mint) or {}
            symbol = str(meta.get("symbol") or token.get("symbol") or "?").upper()
            holders = token.get("holders") or {}
            points = _holder_points.get(mint) or _points_for(mint, token,
                                                             history_store)
            view = (_holder_views.get(mint)
                    or resolve_view(token, points, now=_now_ts,
                                    stale_after=STALE_REGULAR_AFTER_SEC))
            # Grafik & pembanding badge hanya memakai titik yang datanya layak:
            # titik dari scan yang cuma mengambil 20 wallet berisi dust 0 dan
            # akan menggambar tebing palsu ke 0% (lihat holder_history).
            sampled = resample_4h(usable_points(points))
            # Angka baris = sumber terbaru (snapshot cron / titik history / scan
            # manual), bukan selalu snapshot — lihat sync_caption_text di atas.
            dust_count = view.get("dust_count")
            dust_pct = view.get("dust_pct")
            prev_pct = previous_pct(sampled, view)
            flag = dust_flag(dust_pct, prev_pct)
            change = _change_by_mint.get(mint) or {}
            truncated = holders.get("truncated", False)
            dust_txt = ("—" if dust_count is None
                        else (f"≥{int(dust_count)}" if truncated
                              else f"{int(dust_count):,}"))
            pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.2f}%"
            scan_note = f"scan {format_wib(view.get('ts'))}"
            if view.get("source") == SOURCE_HISTORY:
                scan_note += " · titik history"
            if view.get("drift"):
                scan_note += " · ⚠️ snapshot ≠ history"
            if view.get("truncation_swap"):
                scan_note += " · ⚠️ memakai scan lengkap sebelumnya " \
                             "(scan teranyar sampel terpotong)"
            elif view.get("snapshot_truncated") and \
                    view.get("source") == SOURCE_SNAPSHOT:
                scan_note += " · ≥ sampel terpotong"
            if view.get("degraded"):
                # Run terakhir datanya tidak lengkap → angka baris dari scan
                # layak sebelumnya; bilang terus terang, jangan diam-diam.
                wallets = view.get("degraded_wallets")
                if view.get("ts"):
                    scan_note += (f" · ⚠️ scan "
                                  f"{format_wib(view.get('degraded_ts'))} cuma "
                                  f"{int(wallets or 0):,} wallet")
                else:
                    # Belum ada satu pun scan yang layak: jangan tulis "scan —".
                    scan_note = (f"⚠️ scan "
                                 f"{format_wib(view.get('degraded_ts'))} tidak "
                                 f"lengkap ({int(wallets or 0):,} wallet)")
            if view.get("stale"):
                scan_note += " · basi"

            cols = st.columns([1.55, 0.85, 0.9, 1.05, 0.4, 0.4, 0.4])
            cols[0].markdown(
                f'<div class="watchlist-token">'
                f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
                f'<span class="watchlist-mint">{html.escape(mint[:8])}…</span>'
                f'<span class="watchlist-metric-sub">{scan_note}</span>'
                f'<div class="watchlist-links">{external_links_html(mint)}</div>'
                f"</div>", unsafe_allow_html=True)
            cols[1].markdown(
                f'<div class="watchlist-metric">'
                f'<div class="watchlist-metric-value">{dust_txt}</div>'
                f'<div class="watchlist-metric-sub">wallet dust</div></div>',
                unsafe_allow_html=True)
            cols[2].markdown(
                f'<div class="watchlist-metric">'
                f'<div class="watchlist-metric-value">{pct_txt}</div>'
                f'{_dust_badge_html(flag)}</div>',
                unsafe_allow_html=True)
            cols[3].markdown(change_html(change), unsafe_allow_html=True)
            cols[4].markdown(holder_analytic_link_html(mint),
                             unsafe_allow_html=True)
            if cols[5].button("🌊", key=f"to-lp-{mint}",
                              help="Pindahkan ke Watchlist Meteora "
                                   "(halaman utama)",
                              use_container_width=True):
                set_watchlist_source(mint, LP_SOURCE, background=True)
                st.rerun()
            if cols[6].button("✕", key=f"remove-{mint}", help="Hapus watchlist",
                              use_container_width=True):
                remove_from_watchlist(mint, background=True)
                st.rerun()
            # Grafik perubahan dust holder ala Watchlist Meteora (permintaan
            # user 2026-09-10): bucket 4 jam (kadens watchlist biasa) + tabel
            # Wallet Depth by Threshold ter-nested di dalam expander.
            _render_dust_change(points, holders, symbol)
            st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">',
                        unsafe_allow_html=True)

    with st.expander("➕ Tambah token", expanded=not bool(watchlist)):
        with st.form("add-token", clear_on_submit=True):
            mint_input = st.text_input(
                "Contract address", key="add-token-input",
                help="Symbol di-fetch otomatis dari DexScreener")
            target = st.radio(
                "Masuk ke card", ADD_TARGETS, index=0, key="add-token-target",
                horizontal=True,
                help=("📋 Watchlist Holder = daftar analisa dust biasa. "
                      "🌊 Chart LP = watchlist terpisah di halaman utama untuk "
                      "token Meteora/LP beserta grafik perubahan dust holder."))
            submitted = st.form_submit_button("Tambah ke watchlist")
            if submitted:
                ca_error = _ca_error(mint_input)
                if ca_error:
                    st.warning(ca_error)
                else:
                    source = ADD_TARGET_SOURCE.get(target, "manual")
                    added = add_to_watchlist(str(mint_input).strip(), "?",
                                             source=source, background=True)
                    card = ("Watchlist Meteora" if source == LP_SOURCE
                            else "watchlist")
                    if added:
                        st.success(f"Token ditambahkan ke {card}.")
                    else:
                        error = get_last_push_error()
                        st.warning(error.get("msg")
                                   or f"Tersimpan lokal di {card}; sinkronisasi "
                                      "GitHub belum berhasil.")
                    st.rerun()

    # Card Scan Meteora Pool dipindah ke sini dari halaman utama (2026-09-10);
    # ⭐ tetap memasukkan token ke card Watchlist Meteora di halaman utama.
    render_meteora_scan()

    # 🦅 Scan Best Robinhood Coin diparkir ke sini dari halaman utama
    # (2026-09-11, permintaan user: "pindah ke page temp karena belum
    # berfungsi") — logika scan, data, dan tombol tidak disentuh; ⭐ tetap
    # memasukkan token ke card Watchlist Robinhood LP di halaman utama.
    robinhood_best_scan.render_robinhood_best_scan()

    st.divider()
    st.subheader("🔍 Temukan Token")
    st.caption("Scan Trending/Degen menampilkan listing GMGN. "
               "Analisa dust ada di Scan Meteora dan watchlist.")

    st.markdown("""
    <style>
    div[data-testid="stButtonGroup"] button {
        font-size: 0.9rem !important;
        padding: 0.5rem 1.1rem !important;
        font-weight: 700 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    TREND_TAB = "📈 Trending"
    DEGEN_TAB = "🔥 Degen"
    DISCOVER_TABS = [TREND_TAB, DEGEN_TAB]

    active_tab = st.session_state.get("discover_tab_active", TREND_TAB)
    selected_tab = st.segmented_control(
        "Mode listing", DISCOVER_TABS, default=active_tab,
        key="discover_tab", label_visibility="collapsed")
    if selected_tab not in DISCOVER_TABS:
        selected_tab = active_tab
    st.session_state["discover_tab_active"] = selected_tab

    if selected_tab == DEGEN_TAB:
        if st.button("🔥 Scan Degen", use_container_width=True):
            rows_24, error_24 = run_screen_hrhr(force=True)
            rows_1, error_1 = run_screen_hrhr_h1(force=True)
            combined = merge_scan_rows(rows_24, rows_1)
            st.session_state["degen_combined"] = combined
            st.session_state["degen_error"] = error_24 or error_1
        if st.session_state.get("degen_error"):
            st.error(st.session_state["degen_error"])
        render_trending(st.session_state.get("degen_combined", []),
                        key_prefix="degen", source="degen", watchlist=watchlist)
    else:
        if st.button("🔎 Scan Trending", use_container_width=True):
            rows_24, error_24 = run_screen(force=True)
            rows_1, error_1 = run_screen_h1(force=True)
            combined = merge_scan_rows(rows_24, rows_1)
            st.session_state["trend_combined"] = combined
            st.session_state["trend_error"] = error_24 or error_1
        if st.session_state.get("trend_error"):
            st.error(st.session_state["trend_error"])
        render_trending(st.session_state.get("trend_combined", []),
                        key_prefix="trend", source="trending", watchlist=watchlist)
