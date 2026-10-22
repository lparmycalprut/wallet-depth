# -*- coding: utf-8 -*-
"""UI page **🌊 Sweep Screener** (permintaan user 2026-10-12).

Halaman terpisah dari **🏆 Scan Best Pool Meteora** — ``app.py`` tidak disentuh;
entri-nya ada di ``pages/8_🌊_Sweep.py`` (multipage bawaan Streamlit).

Isi halaman:

1. **Watchlist manual** — tempel mint, satu per baris.
2. **Tabel kelayakan** — 5 kriteria menjadi skor + vonis, plus kolom pasar.
3. **Detail per mint** — alasan tiap kriteria + tabel biaya sweep (rumus
   ``(akar(m)-1) x liq/MC / 2``).
4. **Statistik** — riwayat sinyal beserta ``max_up`` / ``max_down`` sehingga
   hit rate bisa dilihat, bukan ditebak.

Auto-refresh memakai ``st.fragment(run_every=…)`` (Streamlit 1.61): kalau
diaktifkan, halaman memindai ulang tiap 30 menit selama tab terbuka. Cron GitHub
Actions menangani sisanya saat tab ditutup.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import sweep_alert as alert
import sweep_check as check
import sweep_data as data
import sweep_scan as scan
import sweep_screen as screen
import sweep_store as store

AUTO_REFRESH_SEC = 1800  # 30 menit (permintaan user 2026-10-19); cron juga 30 menit (2026-10-21)
ATTEMPTS_KEY = "sweep_nodata_attempts"  # {mint: jumlah retry kohort tanpa data}
READY_KEY = "sweep_nodata_ready_at"     # kapan retry berikutnya boleh jalan
WIB = timezone(timedelta(hours=7))  # waktu tampilan: Asia/Jakarta


def _fmt_usd(value, digits: int = 0) -> str:
    number = screen._num(value)
    if number is None:
        return "—"
    if abs(number) >= 1000:
        return f"${number:,.{digits}f}"
    return f"${number:,.4f}"


def _fmt_pct(value, digits: int = 1) -> str:
    number = screen._num(value)
    return f"{number*100:.{digits}f}%" if number is not None else "—"


def _fmt_price_move(value, digits: int = 1) -> str:
    """Pergerakan harga sejak lowest buy: ``naik 38,1%`` / ``turun 5,8%``.

    ``value`` adalah fraksi (0,381 = naik 38,1%). Nol = ``tetap``.
    """
    number = screen._num(value)
    if number is None:
        return "—"
    pct = abs(number) * 100
    if round(pct, digits) == 0:
        return "tetap"
    word = "naik" if number > 0 else "turun"
    return f"{word} {pct:.{digits}f}%"


def _fmt_pct100(value, digits: int = 1) -> str:
    number = screen._num(value)
    return f"{number:.{digits}f}%" if number is not None else "—"


def _fmt_mult(value, digits: int = 1) -> str:
    number = screen._num(value)
    return f"{number:.{digits}f}x" if number is not None else "—"


def _fmt_times(value, digits: int = 1) -> str:
    number = screen._num(value)
    return f"{number:.{digits}f}×" if number is not None else "—"


def _fmt_amount(value) -> str:
    """Jumlah token ringkas: 77,02M, 1,5K, 812."""
    number = screen._num(value)
    if number is None:
        return "—"
    if abs(number) >= 1e9:
        return f"{number / 1e9:.2f}B"
    if abs(number) >= 1e6:
        return f"{number / 1e6:.2f}M"
    if abs(number) >= 1e3:
        return f"{number / 1e3:.1f}K"
    return f"{number:,.0f}"


def _fmt_price(value) -> str:
    number = screen._num(value)
    if number is None:
        return "—"
    return f"${number:,.4f}" if number >= 1 else f"${number:.8f}"


def _link(mint: str) -> str:
    return f"https://gmgn.ai/sol/token/{mint}"


def _flash(kind: str, message: str) -> None:
    """Antre pesan yang bertahan melewati ``st.rerun()``.

    Tombol-tombol di halaman ini diakhiri ``st.rerun()`` supaya tabel langsung
    ikut segar; tanpa antrean ini pesan sukses/gagalnya ikut terhapus sebelum
    sempat terbaca.
    """
    st.session_state.setdefault("sweep_flash", []).append((kind, message))


def _render_flash() -> None:
    for kind, message in st.session_state.pop("sweep_flash", []):
        (st.success if kind == "success" else st.warning)(message)


def _stash_watchlist_in_config(mints) -> None:
    """Cadangan: tulis juga ke ``config.json`` (`sweep_watchlist`).

    Di Streamlit Cloud berkas lokal hilang saat restart, sementara
    ``config.json`` diisi lewat secrets/berkas yang di-deploy. Kalau file
    config lokal tidak bisa ditulis (tidak ada/milik orang lain), tidak
    melakukan apa-apa — ini jalur cadangan, bukan jalur utama.
    """
    path = store.CONFIG_PATH
    config = {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            config = loaded
    except Exception:  # noqa: BLE001 - belum ada config.json = buat baru
        config = {}
    config["sweep_watchlist"] = list(mints)
    try:
        store.atomic_write_json(path, config, indent=2)
    except Exception:  # noqa: BLE001 - cadangan opsional, jangan matikan UI
        pass


# ---------------------------------------------------------------------------
# Header + Telegram
# ---------------------------------------------------------------------------
def _render_header() -> None:
    st.markdown("## 🌊 Sweep Screener")
    st.caption(
        "Skrining **kelayakan sweep** untuk token yang sudah retrace dalam: "
        "float tipis (token/MC kecil) + authority dilepas + float tersebar + ada "
        "jejak akumulasi. Alert Telegram dikirim saat kelayakan muncul dan "
        "saat sweep mulai terjadi. Halaman dibuka dengan **snapshot terakhir** "
        "tiap mint di watchlist; tekan **Refresh & ambil snapshot** untuk "
        "pindai live."
    )
    cfg = alert.telegram_config()
    left, right = st.columns([3, 2])
    with left:
        if cfg.get("ok"):
            st.success(f"Telegram siap — kredensial dari **{cfg['source']}**")
        else:
            st.warning(
                "Telegram belum siap. Isi salah satu: `st.secrets` "
                "(`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`), environment "
                "variable dengan nama sama, atau `config.json`."
            )
    with right:
        if st.button("📨 Kirim test alert", use_container_width=True,
                     disabled=not cfg.get("ok")):
            sent, error = alert.send_message(alert.format_test(), config=cfg)
            if sent:
                st.success("Test terkirim.")
            else:
                st.error(f"Gagal: {error or 'tidak diketahui'}")


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
def _commit_watchlist(mints, label: str) -> list:
    """Simpan watchlist lokal + commit GitHub, dengan pesan yang jujur.

    Di Streamlit Cloud sistem berkasnya sementara: kalau tidak di-commit, daftar
    ini hilang saat container restart, jadi kegagalan commit harus terlihat.
    """
    saved = store.save_watchlist(mints, persist=False)
    if store.push_watchlist(saved):
        _flash("success", f"{label}: {len(saved)} mint di-commit ke GitHub.")
    else:
        _stash_watchlist_in_config(saved)
        _flash("warning",
               f"{label}: {len(saved)} mint tersimpan **lokal + cadangan "
               "`config.json`**. Commit ke GitHub gagal (token belum "
               "diisi?) — isi token GitHub supaya daftar ikut "
               "tersimpan permanen di repo.")
    return saved


def _render_watchlist() -> list:
    watchlist = store.load_watchlist()
    with st.expander(f"📝 Watchlist manual ({len(watchlist)} mint)",
                     expanded=not watchlist):
        text = st.text_area(
            "Satu mint per baris (koma/spasi juga boleh)",
            value="\n".join(watchlist), height=140,
            key="sweep_watchlist_text",
            placeholder="H4KUxsEgCp2yDpFvyDuGM5k6XevSKKrrKUxZ3Zr6nyJc",
        )
        col_a, col_b, col_c = st.columns([1, 1, 1])
        if col_a.button("💾 Simpan watchlist", use_container_width=True):
            _commit_watchlist(text, "Watchlist disimpan")
            st.rerun()
        if col_b.button("♻️ Buang cache HTTP", use_container_width=True):
            data.reset_cache()
            _flash("success", "Cache HTTP dibuang.")
            st.rerun()
        if col_c.button("🧹 Kosongkan", use_container_width=True):
            store.save_watchlist([])
            st.rerun()
        if watchlist:
            st.caption("Mint terpantau: " + ", ".join(m[:8] for m in watchlist))
    return watchlist


# ---------------------------------------------------------------------------
# Tabel kelayakan
# ---------------------------------------------------------------------------
def _fmt_snapshot_time(ts) -> str:
    number = screen._num(ts)
    if not number:
        return "—"
    return datetime.fromtimestamp(number, WIB).strftime("%d %b %H:%M WIB")


def _fmt_wib(ts, fmt: str) -> str:
    """Format epoch detik sebagai waktu WIB (Asia/Jakarta), bukan zona server."""
    number = screen._num(ts)
    if not number:
        return "—"
    return datetime.fromtimestamp(number, WIB).strftime(fmt)


def _lowest_buy_cell(metrics) -> str:
    """``$X (harga naik/turun Y%)``: lowest buy MC dan pergerakan harga sejak itu."""
    low_mc = screen.holder_lowest_buy_mc(
        metrics.get("holder_min_avg_cost"), metrics.get("price_usd"),
        metrics.get("fdv_usd"))
    if low_mc is None:
        return "—"
    move = screen.holder_price_change_vs_lowest_buy(
        metrics.get("holder_min_avg_cost"), metrics.get("price_usd"))
    return f"{_fmt_usd(low_mc)} (harga {_fmt_price_move(move)})"


def _eligibility_rows(rows) -> list:
    out = []
    for row in rows or []:
        metrics = row.get("metrics") or {}
        result = row.get("result") or {}
        context = row.get("sweep_context") or {}
        passed = " ".join(
            ("✅" if c.get("passed") else ("▫️" if not c.get("has_data") else "❌"))
            for c in (result.get("checks") or []))
        out.append({
            "Token": metrics.get("symbol") or row.get("mint", "")[:8],
            "Snapshot": _fmt_snapshot_time(row.get("ts")),
            "Vonis": result.get("verdict") or "—",
            "Skor": (f"{result.get('passed_count')}/{result.get('scored_count')}"
                     if result.get("scored_count") else "—"),
            "Kriteria": passed or "—",
            "Kohort": result.get("cohort_gate_status") or "TANPA DATA — kohort",
            "Harga": _fmt_price(metrics.get("price_usd")),
            "liq/MC": _fmt_pct(result.get("liq_mc")),
            # Sisi token di pool: jumlah, nilai USD, dan % terhadap MC.
            "Token pool": _fmt_amount(metrics.get("pool_base_amount")),
            "Token pool $": _fmt_usd(metrics.get("pool_base_usd")),
            "Token/MC": _fmt_pct(screen.pool_token_mc_frac(
                metrics.get("pool_base_usd"), metrics.get("fdv_usd"))),
            # Cost 10x MC divided by COCK 10x MC ($32,684 / $233,451 = 14,0%).
            "× dana acuan 10x": _fmt_times(result.get("reference_fund_x")),
            # Nominal $ untuk 10x pada basis kas satu sisi (= × dana acuan).
            "Dana acuan 10x": _fmt_usd(result.get("reference_fund_usd")),
            "Turnover (×/hari)": _fmt_times(row.get("turnover_x",
                                                       result.get("turnover_x")), 2),
            "Liq": _fmt_usd(metrics.get("liq_usd")),
            "MC": _fmt_usd(metrics.get("fdv_usd")),
            # Lowest buy holder (avg buy terendah, GMGN) dinyatakan sebagai MC,
            # disertai pergerakan harga sekarang sejak lowest buy (naik/turun %).
            "Lowest buy (MC)": _lowest_buy_cell(metrics),
            "Top-10": _fmt_pct100(metrics.get("top10_holder_pct")),
            "Holder": metrics.get("holder_count"),
            "Bundler": _fmt_pct(metrics.get("top_bundler_trader_percentage",
                                             metrics.get("bundler_rate"))),
            "Bot degen": _fmt_pct(metrics.get("bot_degen_rate")),
            "Vol 1h": _fmt_usd(metrics.get("vol_1h")),
            "Sweep": (f"⚡ {_fmt_mult(context.get('vol_x'))} vol"
                      if context else "—"),
            "GMGN": _link(row.get("mint") or ""),
        })
    return out


def _flagged_mints(rows, flags) -> set:
    """Mint dari baris yang kolom *Hapus*-nya dicentang (urutan = tabel)."""
    return {rows[i]["mint"] for i, flag in enumerate(flags or [])
            if flag and i < len(rows)}


def _placeholder_row(mint: str) -> dict:
    """Baris untuk mint watchlist yang belum punya snapshot sama sekali."""
    return {"mint": mint, "ts": None, "metrics": {"mint": mint},
            "result": {"verdict": "MENUNGGU SNAPSHOT",
                       "cohort_gate_status": "MENUNGGU SNAPSHOT",
                       "checks": [], "passed_count": None,
                       "scored_count": None, "score": None},
            "sweep_context": None, "turnover_x": None}


def _refresh_token(mint: str) -> None:
    """Pindai ulang satu mint sekarang juga dan ambil snapshot-nya."""
    attempts = st.session_state.get(ATTEMPTS_KEY)
    if isinstance(attempts, dict):
        attempts.pop(mint, None)  # refresh manual memberi jatah retry baru
    with st.spinner(f"Memindai {mint[:8]}…"):
        outcome = scan.run_scan([mint], state=_working_state(), persist=True)
    _remember_outcome(outcome)
    row = next((r for r in outcome["rows"] if r.get("mint") == mint), None)
    metrics = (row or {}).get("metrics") or {}
    if metrics.get("ok"):
        _flash("success", f"{mint[:8]} diperbarui dari live scan.")
    else:
        _flash("warning", f"{mint[:8]} belum bisa dipindai: "
               f"{metrics.get('error') or 'sumber data tidak merespons'}")
    st.rerun()


def _refresh_button(mint: str) -> None:
    if st.button(f"🔄 Refresh {mint[:8]}", key=f"refresh_{mint}"):
        _refresh_token(mint)


REFRESH_CLICK_KEY = "sweep_refresh_click"
PENDING_REFRESH_KEY = "sweep_pending_refresh"


def _request_refresh(mints, click_key=REFRESH_CLICK_KEY) -> None:
    """Callback tombol Refresh di tabel: catat mint baris yang diklik.

    Pemindaian dijalankan setelah tabel selesai dirender (bukan di callback),
    karena ``st.rerun`` tidak boleh dipanggil dari dalam callback.
    """
    click = st.session_state.get(click_key)
    row = click.get("row") if click else None
    if isinstance(row, int) and 0 <= row < len(mints) and mints[row]:
        st.session_state[PENDING_REFRESH_KEY] = mints[row]


def _render_table(rows, watchlist, *, suffix: str = "") -> None:
    """Tabel kelayakan dengan kolom **Hapus** untuk mengeluarkan mint dari watchlist.

    ``suffix`` memisahkan key widget bila tabel dirender lebih dari sekali
    (tabel utama dan tabel mint tersembunyi).
    """
    refresh_key = f"{REFRESH_CLICK_KEY}{suffix}"
    if not rows:
        st.info("Belum ada mint di watchlist. Tambahkan mint, lalu tekan "
                "**Refresh & ambil snapshot**.")
        return
    frame = pd.DataFrame(_eligibility_rows(rows))
    mints = [row.get("mint") or "" for row in rows]
    frame.insert(0, "Hapus", False)
    # Hapus dan Refresh sama-sama pinned: tetap terlihat saat tabel digeser.
    frame.insert(1, "Refresh", "🔄 Refresh")
    # Kolom pinned harus berurutan dari kiri: GMGN dipindah tepat setelah Token
    # (Hapus, Refresh, Token, GMGN) lalu ikut di-pin.
    if "GMGN" in frame.columns and "Token" in frame.columns:
        order = [c for c in frame.columns if c != "GMGN"]
        order.insert(order.index("Token") + 1, "GMGN")
        frame = frame[order]
    edited = st.data_editor(
        frame, key=f"sweep_table{suffix}", use_container_width=True, hide_index=True,
        disabled=[column for column in frame.columns if column != "Hapus"],
        column_config={
            # pinned: kolom tetap terlihat saat tabel digeser ke kanan.
            "Hapus": st.column_config.CheckboxColumn(
                "Hapus", help="Centang lalu tekan tombol di bawah tabel",
                pinned=True),
            "Refresh": st.column_config.ButtonColumn(
                "Refresh", help="Pindai ulang mint ini sekarang juga",
                pinned=True, on_click=_request_refresh,
                args=(mints, refresh_key), key=refresh_key),
            # Token ikut dipin (urutan kolom: Hapus, Refresh, Token).
            "Token": st.column_config.TextColumn("Token", pinned=True),
            "Kohort": st.column_config.TextColumn("Kohort", width=320),
            # pinned: link GMGN ikut tetap terlihat saat tabel digeser.
            "GMGN": st.column_config.LinkColumn("GMGN", display_text="buka",
                                                pinned=True),
        })
    pending = st.session_state.pop(PENDING_REFRESH_KEY, None)
    if pending:
        _refresh_token(pending)  # memanggil st.rerun() di akhir
    flags = edited["Hapus"].tolist() if "Hapus" in edited else []
    picked = _flagged_mints(rows, flags)
    if st.button(f"🗑️ Hapus {len(picked)} mint tercentang dari watchlist",
                 disabled=not picked, key=f"sweep_delete{suffix}"):
        remaining = [mint for mint in watchlist if mint not in picked]
        st.session_state.pop("sweep_watchlist_text", None)
        _commit_watchlist(remaining, f"{len(picked)} mint dihapus")
        st.rerun()


def _status_count(value) -> str:
    number = screen._num(value)
    if number is None:
        return "—"
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.1f}"


def _render_cohort(metrics, result) -> None:
    """Show measured GMGN cohort fields and the labeled VWAP proxy."""
    metrics = metrics or {}
    result = result or {}
    cohort = result.get("cohort") or {}
    label = "**Kohort lahir — perkiraan (proksi VWAP 48 jam)"
    if cohort.get("partial_window"):
        label += " · jendela parsial"
    label += "**"
    st.markdown(label)

    status_now = metrics.get("status_now") or {}
    statuses = " / ".join(
        f"{key} {_status_count(status_now.get(key))}"
        for key in ("hold", "sold_part", "sold"))
    details = [
        f"bundler {_fmt_pct(metrics.get('top_bundler_trader_percentage', metrics.get('bundler_rate')))}",
        f"bot degen {_fmt_pct(metrics.get('bot_degen_rate'))}",
        f"fresh {_fmt_pct(metrics.get('fresh_wallet_rate'))}",
        f"holding_rate {_fmt_pct(metrics.get('holding_rate'))}",
        f"statusNow {statuses}",
    ]
    low, high = cohort.get("price_min"), cohort.get("price_max")
    if low is not None and high is not None:
        details.append(f"biaya kohort {_fmt_price(low)}–{_fmt_price(high)}")
    else:
        details.append("biaya kohort —")

    average_cost = screen._num(cohort.get("status_avg_cost"))
    if average_cost is None:
        avg_status = "TANPA DATA — kohort"
    elif average_cost >= 0:
        avg_status = f"PLUS {average_cost*100:.1f}%"
    else:
        avg_status = f"MINUS {abs(average_cost)*100:.1f}%"
    details.append(f"status avg cost: {avg_status}")
    gmgn_avg = screen._num(cohort.get("gmgn_status_avg_cost"))
    if gmgn_avg is None:
        gmgn_status = "TANPA DATA"
    elif gmgn_avg >= 0:
        gmgn_status = f"PLUS {gmgn_avg*100:.1f}%"
    else:
        gmgn_status = f"MINUS {abs(gmgn_avg)*100:.1f}%"
    details.append(f"avg cost GMGN: {gmgn_status}")

    wall_vwap = cohort.get("breakeven_wall_vwap_x")
    wall_high = cohort.get("breakeven_wall_high_x")
    if wall_vwap is not None and wall_high is not None:
        walls = f"{_fmt_times(wall_vwap)}–{_fmt_times(wall_high)} harga kini"
    else:
        walls = "—"
    details.append(f"dinding impas: {walls}")
    st.caption(" · ".join(details))
    if cohort.get("error"):
        st.caption(f"Data proksi kohort: {cohort['error']}")
    st.caption(f"Gate kohort: **{result.get('cohort_gate_status') or 'TANPA DATA — kohort'}** — "
               f"{result.get('cohort_gate_detail') or 'data belum tersedia'}")


def _fmt_usd_plain(value, signed: bool = False) -> str:
    """USD dengan tanda minus di depan: −$1,500 / +$300 / $0."""
    number = screen._num(value)
    if number is None:
        return "—"
    sign = ("−" if number < 0 else "+") if signed else ("−" if number < 0 else "")
    return f"{sign}${abs(number):,.0f}"


def _render_delta(result) -> None:
    """Delta dari trade GMGN: info saja, tidak memengaruhi vonis."""
    delta = result.get("delta")
    if delta is None:
        st.caption("⚖️ Delta: tidak diambil (kohort SKIP/TANPA DATA atau TIDAK LAYAK).")
        return
    if not delta.get("available"):
        st.caption(f"⚖️ Delta: {delta.get('reason') or 'belum ada data'}")
        return
    last = delta.get("last") or {}
    chg = last.get("price_chg")
    chg_txt = f"{chg * 100:+.1f}%" if chg is not None else "—"
    head = (f"⚖️ Delta {delta.get('window_hours')} jam (info, tidak memengaruhi vonis): "
            f"beli {_fmt_usd_plain(delta.get('buy_usd'))} · "
            f"jual {_fmt_usd_plain(delta.get('sell_usd'))} · "
            f"CVD {_fmt_usd_plain(delta.get('cvd_usd'), signed=True)}")
    st.caption(head)
    st.caption(f"Jam terakhir: delta {_fmt_usd_plain(last.get('delta'), signed=True)} "
               f"({(last.get('delta_pct') or 0) * 100:+.0f}% dari volume jam) · harga {chg_txt}"
               + ("" if delta.get("complete") else " · ⚠️ data trade tidak lengkap"))
    labels = delta.get("labels") or []
    if labels:
        st.caption("Pola delta: " + "; ".join(labels))


def _render_order_flow(result) -> None:
    """Order flow dari candle jam: info saja, tidak memengaruhi vonis."""
    flow = result.get("order_flow") or {}
    if not flow.get("available"):
        st.caption(f"🔎 Order flow: {flow.get('reason') or 'belum ada data'}")
        return
    labels = flow.get("labels") or []
    st.caption("🔎 Order flow (info, tidak memengaruhi vonis): "
               + ("; ".join(labels) if labels else "tidak ada pola struktur terbaru"))
    poc, dist = flow.get("poc_price"), flow.get("poc_dist")
    if poc is not None and dist is not None:
        st.caption(f"Volume node {flow.get('poc_bars')} jam (POC): ${poc:.8g} · "
                   f"harga {dist * 100:+.1f}% dari POC")


def _render_details(rows, *, refresh: bool = True) -> None:
    """Panel detail per mint. ``refresh=False`` menyembunyikan tombol Refresh
    (dipakai halaman cek manual, yang tidak boleh menulis ke watchlist)."""
    for row in rows or []:
        metrics = row.get("metrics") or {}
        result = row.get("result") or {}
        symbol = metrics.get("symbol") or row.get("mint", "")[:8]
        if row.get("ts") is None:
            with st.expander(f"⏳ {symbol} — menunggu snapshot", expanded=False):
                st.caption("Belum ada data untuk mint ini. Tekan refresh "
                           "untuk memindai sekarang.")
                if refresh:
                    _refresh_button(row.get("mint") or "")
            continue
        context = row.get("sweep_context") or {}
        missing = result.get("missing") or []
        title = (f"{symbol} — {result.get('verdict') or '—'} "
                 f"({result.get('passed_count')}/{result.get('scored_count')}"
                 + (f", {len(missing)} kriteria belum ada data" if missing else "")
                 + ")")
        with st.expander(title, expanded=bool(result.get("eligible"))):
            if refresh:
                _refresh_button(row.get("mint") or "")
            if row.get("scan_error"):
                failure = row["scan_error"]
                st.warning(
                    f"Scan terakhir gagal ({screen.screen_time_wib(failure.get('ts'))}): "
                    f"{failure.get('error') or 'sumber data tidak merespons'}")
            shakeout = next((c for c in (result.get("checks") or [])
                             if c.get("key") == "shakeout"), {})
            if shakeout.get("breached"):
                st.warning("⚠️ Kriteria 6 tetap lolos (latch permanen), tetapi low "
                           f"shakeout sudah dilanggar: {shakeout.get('detail') or ''}")
            _render_order_flow(result)
            _render_delta(result)
            if metrics.get("error"):
                st.warning(f"Sumber data: {metrics['error']}")
            st.caption(
                f"liq {_fmt_usd(metrics.get('liq_usd'))} · "
                f"MC {_fmt_usd(metrics.get('fdv_usd'))} · "
                f"liq/MC {_fmt_pct(result.get('liq_mc'))} · "
                f"{metrics.get('dex_id') or '—'} · "
                f"{metrics.get('pool_count') or 0} pool")
            _render_cohort(metrics, result)
            if missing:
                st.caption(
                    "Belum bisa dinilai: "
                    + ", ".join(c.get("label") or c.get("key")
                                for c in (result.get("checks") or [])
                                if not c.get("has_data"))
                    + f". Vonis memakai {result.get('passed_count')}"
                    f"/{result.get('scored_count')} dari kriteria yang ada "
                    f"(ambang {result.get('required_count')} + trio struktural).")
            checks = result.get("checks") or []
            for check in checks:
                icon = ("✅" if check.get("passed") else
                        ("▫️" if not check.get("has_data") else "❌"))
                st.markdown(f"{icon} **{check.get('label')}** — "
                            f"{check.get('detail')}")
            targets = result.get("targets") or []
            if targets:
                st.markdown("**Biaya sweep** (`(akar(m)-1) x liq/MC / 2`, uang quote masuk):")
                st.dataframe(
                    [{"Target": _fmt_mult(t["mult"], 0),
                      "Biaya (% MC)": (f"{t['cost_pct']:.1f}%"
                                       if t.get("cost_pct") is not None else "—"),
                      "Biaya ($)": _fmt_usd(t.get("cost_usd")),
                      "Leverage": _fmt_mult(t.get("leverage"), 0),
                      "Realistis": "ya" if t.get("feasible") else "berat"}
                     for t in targets],
                    use_container_width=True, hide_index=True)
            if context:
                bars_ago = context.get("bars_ago") or 0
                kapan = ("di candle 5-menit terakhir" if bars_ago == 0
                         else f"{bars_ago} candle 5-menit lalu")
                base = _fmt_price(context.get("base_price"))
                peak = _fmt_price(context.get("peak"))
                close = _fmt_price(context.get("close"))
                peak_mult = _fmt_mult(context.get("peak_mult"))
                price_mult = _fmt_mult(context.get("price_mult"))
                est_cost = _fmt_usd(context.get("est_cost_usd"))
                est_cost_close = _fmt_usd(context.get("est_cost_close_usd"))
                paper_gain = _fmt_usd(context.get("paper_gain_usd"))
                leverage = _fmt_mult(context.get("leverage"))
                churn = _fmt_mult(context.get("churn_x"))
                churn_net = _fmt_mult(context.get("churn_net_x"))
                inflow = context.get("net_inflow_usd")

                # Hitung %MC untuk biaya ke puncak
                base_mcap = context.get("base_mcap_usd")
                cost_pct_mc = (
                    f"{context['est_cost_usd'] / base_mcap * 100:.1f}% dari MC"
                    if (base_mcap and base_mcap > 0 and context.get("est_cost_usd"))
                    else ""
                )

                # Catatan pembeli luar
                noise_parts = []
                if context.get("churn_net_x"):
                    noise_parts.append(f"Churn nyata {churn_net} (volume ÷ inflow terukur)")
                if context.get("churn_x"):
                    noise_parts.append(f"Churn {churn} (volume ÷ biaya dorong ke puncak)")
                if context.get("net_inflow_ref_usd"):
                    noise_parts.append(
                        f"Perkiraan inflow { _fmt_usd(context['net_inflow_ref_usd']) } "
                        f"(belum ada snapshot pembanding — acuan 1 event)"
                    )
                noise = " | ".join(noise_parts) if noise_parts else ""

                st.error(
                    f"⚡ Sweep terdeteksi {kapan}: volume "
                    f"{_fmt_mult(context.get('vol_x'))} median, "
                    f"harga {base} → puncak {peak} ({peak_mult}), "
                    f"tutup di {close} ({price_mult}). "
                    f"Biaya dorong ke puncak {est_cost}"
                    + (f" ({cost_pct_mc})" if cost_pct_mc else "")
                    + (f", ΔMC kertas {paper_gain} → leverage {leverage}"
                       if paper_gain else "")
                    + (f", inflow nyata { _fmt_usd(inflow) }"
                       if inflow else "")
                    + f". {noise}.")
                st.caption("Ingat: candle vertikal retrace >50% dalam 6 jam "
                           "pada 11 dari 12 kejadian di token acuan — tunggu "
                           "retest 38,2–50%, jangan chase.")


# ---------------------------------------------------------------------------
# Statistik
# ---------------------------------------------------------------------------
def _render_stats(state) -> None:
    signals = (state or {}).get("signals") or []
    stats = screen.summarize_signals(signals)
    st.markdown("### 📊 Statistik sinyal")
    if not stats["n"]:
        st.info("Belum ada sinyal. Statistik terisi setelah alert pertama.")
        return
    cols = st.columns(5)
    cols[0].metric("Sinyal", stats["n"])
    cols[1].metric("Hit ≥100%", _fmt_pct(stats["hit_rate_100"], 0),
                   help="Proporsi sinyal yang naik minimal 100% dari entry")
    cols[2].metric("Hit ≥300%", _fmt_pct(stats["hit_rate_300"], 0))
    cols[3].metric("Median naik", _fmt_pct100(stats["median_up"], 0))
    cols[4].metric("Median turun", _fmt_pct100(stats["median_down"], 0))
    breakeven = screen.breakeven_hit_rate(200.0, 30.0)
    st.caption(
        f"Break-even hit rate (menang +200% / kalah −30%) = "
        f"{_fmt_pct(breakeven, 1)} — jadi hit rate tinggi tidak diperlukan; "
        f"yang menentukan payoff dan ukuran posisi.")
    if stats.get("median_churn_net"):
        st.caption(f"Median churn **nyata** ({stats['n_churn_net']} sinyal "
                   f"terukur): {_fmt_mult(stats['median_churn_net'])} — volume ÷ "
                   "inflow nyata (Δ likuiditas). Acuan COCKROACH 1 Okt: 21,1x.")
    if stats.get("median_churn"):
        st.caption(f"Median churn teoretis: {_fmt_mult(stats['median_churn'])} "
                   "(volume ÷ biaya dorong minimum).")
    table = []
    for signal in sorted((s for s in signals if isinstance(s, dict)),
                         key=lambda s: s.get("ts") or 0, reverse=True)[:200]:
        table.append({
            "Waktu": _fmt_wib(signal.get("ts"), "%m-%d %H:%M"),
            "Token": signal.get("symbol") or (signal.get("mint") or "")[:8],
            "Jenis": ("⚡ sweep" if signal.get("kind") == "sweep"
                      else "🌊 kelayakan"),
            "Entry": _fmt_price(signal.get("entry_price")),
            "Base": _fmt_price(signal.get("base_price")),
            "Puncak": _fmt_price(signal.get("peak_price")),
            "Peak mult": _fmt_mult(signal.get("peak_mult")),
            "Maks naik": _fmt_pct100(signal.get("max_up_pct"), 0),
            "Maks turun": _fmt_pct100(signal.get("max_down_pct"), 0),
            "Dari base": _fmt_pct100(signal.get("from_base_up_pct"), 0),
            "Biaya ke puncak": _fmt_usd(signal.get("est_cost_usd")),
            "Biaya ke close": _fmt_usd(signal.get("est_cost_close_usd")),
            "ΔMC kertas": _fmt_usd(signal.get("paper_gain_usd")),
            "Leverage": _fmt_mult(signal.get("leverage")),
            "Churn": _fmt_mult(signal.get("churn_x")),
            "Churn nyata": _fmt_mult(signal.get("churn_net_x")),
            "Inflow nyata": _fmt_usd(signal.get("net_inflow_usd")),
            "Status": signal.get("status") or "—",
            "Tampil saat terdeteksi": (
                "tersembunyi" if signal.get("hidden_at_detect") is True
                else "tampil" if signal.get("hidden_at_detect") is False
                else "—"),
        })
    st.dataframe(table, use_container_width=True, hide_index=True)
    _render_pre_sweep(state, signals)


def _fmt_count(value) -> str:
    number = screen._num(value)
    return f"{int(number):,}" if number is not None else "—"


def _pre_sweep_scan_rows(scans, sweep_ts) -> list:
    """Baris tabel untuk catatan scan sebelum sweep (kondisi per scan)."""
    rows = []
    for scan_row in scans:
        metrics = scan_row.get("metrics") or {}
        result = scan_row.get("result") or {}
        criteria = scan_row.get("criteria") or {}
        icons = {"lolos": "✅", "gagal": "❌", "n/a": "▫️"}
        is_after = (sweep_ts is not None and scan_row.get("ts") is not None
                    and int(scan_row["ts"]) >= int(sweep_ts))
        rows.append({
            "Posisi": "⚡ deteksi" if is_after else "sebelum candle",
            "Waktu": _fmt_wib(scan_row.get("ts"), "%m-%d %H:%M"),
            "Tampil": "tersembunyi" if scan_row.get("hidden") else "tampil",
            "Vonis": result.get("verdict") or "—",
            "Skor": (f"{result.get('passed_count')}/{result.get('scored_count')}"
                     if result.get("scored_count") else "—"),
            "Kriteria": " ".join(icons.get(v, "▫️") for v in criteria.values()) or "—",
            "Harga": _fmt_price(metrics.get("price_usd")),
            "Liq/MC": _fmt_pct(result.get("liq_mc")),
            "Lowest buy (MC)": _lowest_buy_cell(metrics),
            "Holder": _fmt_count(metrics.get("holder_count")),
            "Top-10": _fmt_pct100(metrics.get("top10_holder_pct")),
            "Bundler": _fmt_pct(metrics.get("top_bundler_trader_percentage",
                                            metrics.get("bundler_rate"))),
            "Bot degen": _fmt_pct(metrics.get("bot_degen_rate")),
            "Vol 1h": _fmt_usd(metrics.get("vol_1h")),
            "Buys/Sells 1h": f"{metrics.get('buys_1h') or 0} / {metrics.get('sells_1h') or 0}",
        })
    return rows


def _pre_sweep_snapshot_rows(history, sweep_ts) -> list:
    """Fallback untuk sinyal lama: snapshot per jam sebelum candle sweep."""
    rows = []
    for snap in history[-3:]:
        rows.append({
            "Posisi": "snapshot per jam",
            "Waktu": _fmt_wib(snap.get("ts"), "%m-%d %H:%M"),
            "Harga": _fmt_price(snap.get("price")),
            "Liq/MC": _fmt_pct(snap.get("liq_mc")),
            "Holder": _fmt_count(snap.get("holders")),
            "Top-10": _fmt_pct100(snap.get("top10_pct")),
            "Bundler": _fmt_pct(snap.get("bundler")),
            "Bot degen": _fmt_pct(snap.get("bot_degen")),
            "Vol 1h": _fmt_usd(snap.get("vol_1h")),
        })
    return rows


def _render_wallet_compare(state, signal, sweep_ts) -> None:
    """Fitur wallet 3 jam sebelum sweep vs. jendela pembanding (lonjakan volume)."""
    mint = signal.get("mint") or ""
    wallet_pre = signal.get("wallet_pre") or {}
    feats = wallet_pre.get("features")
    rows = []
    for entry in (state or {}).get("wallet_flow", {}).get(mint, []) or []:
        if not isinstance(entry, dict):
            continue
        f = entry.get("features") or {}
        rows.append({
            "Jenis": "⚡ sweep" if entry.get("kind") == "sweep" else "lonjakan",
            "Waktu": _fmt_wib(entry.get("ts"), "%m-%d %H:%M"),
            "Vol x": _fmt_mult(entry.get("spike_x")) if entry.get("spike_x") is not None else "—",
            "Buy $": _fmt_usd(f.get("buy_usd")),
            "Sell $": _fmt_usd(f.get("sell_usd")),
            "Buy/Sell": _fmt_mult(f.get("buy_sell_ratio")) if f.get("buy_sell_ratio") is not None else "—",
            "Wallet buy": _fmt_count(f.get("buy_wallets")),
            "Fresh % buy": _fmt_pct(f.get("fresh_buy_share")),
            "Bundler % buy": _fmt_pct(f.get("bundler_buy_share")),
            "Top wallet $": _fmt_usd(f.get("top_buy_wallet_usd")),
            "Rangkaian fresh/bundler": f"{f.get('run_len') or 0} trade, {f.get('run_wallets') or 0} wallet, {_fmt_usd(f.get('run_usd'))}",
            "Lengkap": "ya" if entry.get("complete") else "tidak",
        })
    if not feats and not rows:
        return
    st.markdown("**Wallet (GMGN) sebelum sweep vs. lonjakan volume**")
    if feats:
        st.caption("Jendela 3 jam sebelum candle sweep. "
                   + ("Data lengkap." if wallet_pre.get("complete")
                      else "Data GMGN tidak lengkap, angka bisa kurang."))
        st.dataframe([
            {"Ukuran": "Trade / buy / sell", "Nilai": f"{feats.get('trades')} / {feats.get('buys')} / {feats.get('sells')}"},
            {"Ukuran": "Buy $ / sell $", "Nilai": f"{_fmt_usd(feats.get('buy_usd'))} / {_fmt_usd(feats.get('sell_usd'))}"},
            {"Ukuran": "Wallet pembeli", "Nilai": _fmt_count(feats.get("buy_wallets"))},
            {"Ukuran": "Median buy per wallet", "Nilai": _fmt_usd(feats.get("median_buy_wallet_usd"))},
            {"Ukuran": "Wallet terbesar", "Nilai": f"{_fmt_usd(feats.get('top_buy_wallet_usd'))} ({_fmt_pct(feats.get('top_buy_share'))} dari buy)"},
            {"Ukuran": "Fresh wallet (wallet / % buy)", "Nilai": f"{_fmt_count(feats.get('fresh_buy_wallets'))} / {_fmt_pct(feats.get('fresh_buy_share'))}"},
            {"Ukuran": "Bundler (wallet / % buy)", "Nilai": f"{_fmt_count(feats.get('bundler_buy_wallets'))} / {_fmt_pct(feats.get('bundler_buy_share'))}"},
            {"Ukuran": "Sandwich (% volume)", "Nilai": _fmt_pct(feats.get("sandwich_share"))},
            {"Ukuran": "Rangkaian fresh/bundler terpanjang", "Nilai": f"{feats.get('run_len') or 0} trade, {feats.get('run_wallets') or 0} wallet, {_fmt_usd(feats.get('run_usd'))}"},
        ], use_container_width=True, hide_index=True)
    if rows:
        st.caption("Riwayat fitur wallet mint ini (jendela pembanding dicatat saat volume 5m melonjak ≥ 5×).")
        st.dataframe(rows[-10:], use_container_width=True, hide_index=True)


def _render_pre_sweep(state, signals) -> None:
    """Pilih satu sinyal sweep: kondisi token sebelum sweep + candle 5 menit."""
    sweeps = sorted((s for s in signals if isinstance(s, dict)
                     and s.get("kind") == "sweep" and s.get("id")),
                    key=lambda s: s.get("ts") or 0, reverse=True)[:200]
    if not sweeps:
        return
    st.markdown("#### 🔎 Detail token sebelum sweep")
    by_id = {s["id"]: s for s in sweeps}

    def _label(sid: str) -> str:
        sig = by_id[sid]
        flag = " · tersembunyi" if sig.get("hidden_at_detect") else ""
        name = sig.get("symbol") or (sig.get("mint") or "")[:8]
        return f"{_fmt_wib(sig.get('ts'), '%m-%d %H:%M')} · {name}{flag}"

    pick = st.selectbox("Pilih sinyal sweep", options=list(by_id),
                        format_func=_label, key="sweep_pre_pick")
    signal = by_id[pick]
    mint = signal.get("mint") or ""
    sweep_ts = signal.get("sweep_ts") or signal.get("ts")
    hidden = signal.get("hidden_at_detect")
    st.caption(
        f"Candle sweep {_fmt_wib(sweep_ts, '%d %b %Y %H:%M')} WIB · "
        + ("tersembunyi dari tabel saat terdeteksi" if hidden is True
           else "tampil di tabel saat terdeteksi" if hidden is False
           else "status tampilan tidak tercatat (sinyal lama)"))

    scans = [s for s in (signal.get("pre_sweep") or []) if isinstance(s, dict)]
    if scans:
        st.dataframe(_pre_sweep_scan_rows(scans, sweep_ts),
                     use_container_width=True, hide_index=True)
    else:
        history = [row for row in store.mint_history(state, mint, limit=168)
                   if isinstance(row, dict)
                   and int(row.get("ts") or 0) < int(sweep_ts or 0)]
        st.caption("Belum ada catatan scan untuk sinyal ini (dicatat sebelum "
                   "fitur ini ada). Yang tampil: snapshot per jam sebelum sweep.")
        if history:
            st.dataframe(_pre_sweep_snapshot_rows(history, sweep_ts),
                         use_container_width=True, hide_index=True)
        else:
            st.info("Tidak ada snapshot sebelum sweep untuk mint ini.")

    _render_wallet_compare(state, signal, sweep_ts)

    candles = signal.get("pre_candles") or []
    if candles:
        st.markdown("**Candle 5 menit di sekitar sweep**")
        st.dataframe([
            {"Waktu": _fmt_wib(c[0], "%H:%M"),
             "Open": _fmt_price(c[1]), "High": _fmt_price(c[2]),
             "Low": _fmt_price(c[3]), "Close": _fmt_price(c[4]),
             "Volume": _fmt_usd(c[5]),
             "Sweep": "⚡" if int(c[0]) == int(sweep_ts or 0) else ""}
            for c in candles if isinstance(c, (list, tuple)) and len(c) >= 6
        ], use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------
def _working_state() -> dict:
    """State kerja sesi; pertama kali dibuka dibaca dari berkas lokal."""
    state = st.session_state.get("sweep_state")
    if state is None:
        state = store.load_state()
        st.session_state["sweep_state"] = state
    return state


def _remember_outcome(outcome) -> None:
    st.session_state["sweep_state"] = outcome["state"]
    st.session_state["sweep_alerts"] = outcome["alerts"]
    st.session_state["sweep_elapsed"] = outcome["elapsed"]


def _snapshot_all(watchlist, *, persist: bool) -> dict:
    """Pindai live semua mint watchlist dan ambil snapshot (refresh manual)."""
    with st.spinner(f"Memindai {len(watchlist)} mint…"):
        outcome = scan.run_scan(watchlist, state=_working_state(),
                                persist=persist)
    _remember_outcome(outcome)
    return outcome


def _fill_missing_views(watchlist) -> None:
    """Mint yang belum punya snapshot (baru ditambahkan) dipindai sekali saja.

    Mint yang gagal dipindai tidak diulang di setiap rerun; tekan Refresh
    untuk mencoba lagi.
    """
    _, missing = store.watchlist_views(_working_state(), watchlist)
    attempted = st.session_state.setdefault("sweep_attempted", set())
    todo = [mint for mint in missing if mint not in attempted]
    if not todo:
        return
    attempted.update(todo)
    with st.spinner(f"Mengambil snapshot awal {len(todo)} mint baru…"):
        outcome = scan.run_scan(todo, state=_working_state(), persist=True)
    _remember_outcome(outcome)


def _render_threshold() -> None:
    """Ambang struktural permanen: tidak ada knob UI/cron atau rescore."""
    st.markdown("### ⚙️ Ambang kelayakan")
    st.caption("Ambang fix: token/MC ≤ 17,5% · holder/wallet ≤ 5% · "
               "kohort minimal minus 50% (VWAP kelahiran 48 jam) · "
               "standar pra-pump COCKROACH (acuan dana 10×)")


def _fmt_signed_pct(value, digits: int = 1) -> str:
    number = screen._num(value)
    return f"{number*100:+.{digits}f}%" if number is not None else "—"


def _fmt_signed_usd(value) -> str:
    number = screen._num(value)
    return f"{number:+,.0f} USD" if number is not None else "—"


def _flow_data_status(row) -> str:
    if not row.get("available"):
        return f"belum ada trade ({row.get('reason') or 'kosong'})"
    if not row.get("complete"):
        return "sebagian (batas halaman GMGN)"
    if not row.get("covers_start"):
        return f"sebagian ({screen.FLOW_MAX_HOURS} jam terakhir)"
    return "lengkap"


def _render_flow(rows, state) -> None:
    """Tabel CVD & delta sejak harga pertama di bawah lowest avg buy (info saja).

    Hanya mint lolos (tidak tersembunyi, kandidat delta) yang sedang di bawah
    lowest avg buy. Yang di atas lowest buy tidak dihitung dan tidak ditampilkan.
    """
    flows = (state or {}).get("flow_episodes") or {}
    table = screen.flow_rows(rows, flows)
    st.markdown("### 📉 CVD & delta sejak di bawah lowest avg buy")
    st.caption(
        "Info saja: tidak memengaruhi vonis, urutan, atau filter. Dihitung hanya "
        "untuk koin yang lolos dan sedang di bawah lowest avg buy. Mulai saat "
        "harga pertama kali ≤ lowest avg buy pada scan yang lolos; berhenti saat "
        "harga kembali di atas. CVD = akumulasi beli − jual (USD) sejak mulai; "
        f"jendela maksimum {screen.FLOW_MAX_HOURS} jam.")
    if not table:
        st.info("Tidak ada koin lolos yang sedang di bawah lowest avg buy.")
        return
    st.dataframe(
        [{"Token": r["symbol"],
          "Mulai (WIB)": _fmt_wib(r.get("start_ts"), "%d %b %H:%M"),
          "Sumber mulai": r.get("start_source") or "—",
          "Jam sejak mulai": f"{r['hours']:.1f}",
          "Harga mulai": _fmt_price(r.get("start_price")),
          "Harga sekarang": _fmt_price(r.get("price")),
          "Δ harga sejak mulai": _fmt_signed_pct(r.get("price_move")),
          "Lowest buy": _fmt_price(r.get("lowest_buy")),
          "Harga vs lowest buy": _fmt_signed_pct(r.get("vs_lowest")),
          "Beli (USD)": _fmt_usd(r.get("buy_usd")),
          "Jual (USD)": _fmt_usd(r.get("sell_usd")),
          "CVD sejak mulai": _fmt_signed_usd(r.get("cvd_usd")),
          "Delta jam terakhir": _fmt_signed_usd(r.get("delta_last_usd")),
          "Data": _flow_data_status(r),
          "Flag": "; ".join(r.get("labels") or []) or "—"}
         for r in table],
        use_container_width=True, hide_index=True)


def _render_results(watchlist, state) -> None:
    """Tabel + detail + statistik dari snapshot terakhir tiap mint watchlist."""
    views, missing = store.watchlist_views(state, watchlist)
    # Vonis tersimpan dihitung ulang dari gate yang sudah ada (tanpa gate biaya),
    # supaya snapshot lama tidak lagi menampilkan "TUNGGU — biaya 10x …".
    views = [{**view, "result": screen.current_verdict(view.get("result"))}
             for view in views]
    placeholders = []
    for mint in missing:
        placeholder = _placeholder_row(mint)
        failure = store.scan_failure(state, mint)
        if failure is not None:
            placeholder["scan_error"] = failure
        placeholders.append(placeholder)
    all_rows = sorted(views + placeholders,
                      key=lambda row: screen.display_sort_key(row.get("result")))
    # Filter tampilan: x dana acuan 10x > 3× atau bundler < 10% disembunyikan
    # dari tabel utama; tabel terpisah di bawah bisa menampilkannya.
    # Baris dengan scan terakhir gagal tidak pernah disembunyikan.
    rows = [row for row in all_rows if not screen.view_hidden(row)]
    hidden_rows = [row for row in all_rows if screen.view_hidden(row)]
    hidden = len(hidden_rows)
    failed = sum(1 for row in all_rows if row.get("scan_error"))
    breached = sum(1 for row in all_rows
                   if any(c.get("key") == "shakeout" and c.get("breached")
                          for c in ((row.get("result") or {}).get("checks") or [])))
    st.markdown("### 🧭 Kelayakan sweep")
    if breached:
        st.caption(f"⚠️ {breached} mint: kriteria 6 lolos (latch), tetapi low "
                   "shakeout-nya sudah dilanggar. Lihat detail tiap mint.")
    if failed:
        st.warning(f"⚠️ {failed} mint scan terakhirnya gagal (fetch data error). "
                   "Baris ini tetap ditampilkan; data di dalamnya dari scan "
                   "sukses terakhir, atau belum ada.")
    if hidden:
        tidak = sum(1 for row in hidden_rows
                    if screen.is_tidak_layak(row.get("result")))
        filtered = hidden - tidak
        if filtered:
            st.caption(f"🙈 {filtered} mint disembunyikan filter tampilan "
                       f"(× dana acuan 10x > {screen.VIEW_HIDE_REF_X_ABOVE:.0f}× "
                       f"atau bundler < {screen.VIEW_HIDE_BUNDLER_BELOW*100:.0f}%).")
        if tidak:
            st.caption(f"🙈 {tidak} mint TIDAK LAYAK disembunyikan "
                       "(diperlakukan sebagai SKIP kohort plus).")
    if all_rows and not rows:
        st.info("Semua mint di watchlist tersembunyi oleh filter tampilan.")
    _render_table(rows, watchlist)
    if rows:
        _render_details(rows)
        _render_flow(rows, state)
    if hidden:
        # Tabel terpisah di bawah hasil utama; mati secara default.
        show_hidden = st.toggle(
            f"👁️ Tampilkan {hidden} mint yang disembunyikan", value=False,
            key="sweep_show_hidden")
        if show_hidden:
            st.markdown("#### 🙈 Mint tersembunyi (filter tampilan & TIDAK LAYAK)")
            _render_table(hidden_rows, watchlist, suffix="_hidden")
    st.divider()
    _render_stats(state)


def _nodata_targets(watchlist, state) -> list:
    """Mint watchlist yang kohortnya tanpa data dan masih punya jatah retry."""
    views, _ = store.watchlist_views(state, watchlist)
    return screen.nodata_retry_targets(views, st.session_state.get(ATTEMPTS_KEY))


def _nodata_exhausted(watchlist, state) -> list:
    """Mint yang kohortnya masih tanpa data setelah habis jatah retry."""
    views, _ = store.watchlist_views(state, watchlist)
    attempts = st.session_state.get(ATTEMPTS_KEY) or {}
    return [view["mint"] for view in views
            if screen.is_cohort_nodata(view.get("result"))
            and attempts.get(view.get("mint"), 0) >= screen.NODATA_RETRY_MAX_ATTEMPTS]


def _attach_nodata_retry(watchlist) -> None:
    """Retry otomatis: hanya mint tanpa data kohort yang dipindai ulang.

    Jeda ``NODATA_RETRY_DELAY_SEC`` antar percobaan, maksimum
    ``NODATA_RETRY_MAX_ATTEMPTS`` per mint. Mint yang sudah berdata tidak
    ikut dipindai. Saat tidak ada lagi yang tertahan, fragment dihentikan
    lewat rerun penuh supaya tabel kembali normal.
    """
    delay = screen.NODATA_RETRY_DELAY_SEC
    st.session_state.setdefault(READY_KEY, time.time() + delay)

    @st.fragment(run_every=delay)
    def _retry_tick() -> None:
        todo = _nodata_targets(watchlist, _working_state())
        if todo and time.time() >= st.session_state.get(READY_KEY, 0):
            attempts = st.session_state.setdefault(ATTEMPTS_KEY, {})
            for mint in todo:
                attempts[mint] = attempts.get(mint, 0) + 1
            outcome = scan.run_scan(todo, state=_working_state(), persist=True,
                                    use_cache=False)
            _remember_outcome(outcome)
            st.session_state[READY_KEY] = time.time() + delay
        pending = _nodata_targets(watchlist, _working_state())
        if not pending:
            st.session_state.pop(READY_KEY, None)
            st.rerun(scope="app")
        attempts = st.session_state.get(ATTEMPTS_KEY) or {}
        round_no = max(attempts.get(mint, 0) for mint in pending)
        wait = max(0, int(st.session_state.get(READY_KEY, 0) - time.time()))
        progress = (f"percobaan {round_no}/{screen.NODATA_RETRY_MAX_ATTEMPTS}"
                    if round_no else "menunggu percobaan pertama")
        st.caption(
            f"🔁 Retry otomatis: {len(pending)} mint tanpa data kohort "
            f"({progress}, berikutnya ±{wait} dtk). "
            "Mint yang sudah berdata tidak dipindai ulang.")
        _render_results(watchlist, _working_state())

    _retry_tick()


def _render_body(watchlist) -> None:
    _render_threshold()

    col_scan, col_auto = st.columns([1, 2])
    if col_scan.button("🔄 Refresh & ambil snapshot", type="primary",
                       use_container_width=True, disabled=not watchlist):
        # Refresh manual memberi jatah retry baru untuk semua mint.
        st.session_state.pop(ATTEMPTS_KEY, None)
        st.session_state.pop(READY_KEY, None)
        outcome = _snapshot_all(watchlist, persist=True)
        st.success(f"Snapshot diambil: {len(watchlist)} mint dipindai live "
                   f"({outcome['elapsed']:.1f}s).")
    auto = col_auto.toggle(
        f"Auto-refresh tiap {AUTO_REFRESH_SEC // 60} menit (selama tab terbuka)",
        value=st.session_state.get("sweep_auto", False), key="sweep_auto")

    _fill_missing_views(watchlist)

    sent = [a for a in (st.session_state.get("sweep_alerts") or [])
            if a.get("sent")]
    if sent:
        st.success("Alert terkirim: " + ", ".join(
            f"{a['kind']} {a['mint'][:8]}" for a in sent))

    if auto:
        # Auto-refresh 30 menit sudah memindai ulang semua mint.
        _attach_autorefresh(watchlist)
    elif _nodata_targets(watchlist, _working_state()):
        _attach_nodata_retry(watchlist)
    else:
        _render_results(watchlist, _working_state())
        exhausted = _nodata_exhausted(watchlist, _working_state())
        if exhausted:
            st.caption(
                f"⚠️ {len(exhausted)} mint masih tanpa data kohort setelah "
                f"{screen.NODATA_RETRY_MAX_ATTEMPTS} percobaan retry. "
                "Tekan Refresh untuk mencoba lagi.")


def render_sweep_page() -> None:
    """Render halaman lengkap (dipanggil dari ``pages/8_🌊_Sweep.py``)."""
    _render_flash()
    _render_header()
    st.divider()
    watchlist = _render_watchlist()
    st.divider()
    _render_body(watchlist)


def _attach_autorefresh(watchlist) -> None:
    """Pindai ulang tiap 30 menit selama tab terbuka (cron menutup sisanya)."""

    @st.fragment(run_every=AUTO_REFRESH_SEC)
    def _tick() -> None:
        if not watchlist:
            return
        outcome = scan.run_scan(watchlist, state=_working_state(), persist=False)
        fingerprint = store.fingerprint(outcome["state"])
        last = st.session_state.get("sweep_fingerprint")
        st.session_state["sweep_fingerprint"] = fingerprint
        _remember_outcome(outcome)
        if last is not None and fingerprint != last:
            store.save_state(outcome["state"], persist=True, reason="auto-refresh")
        st.caption(f"Terakhir dipindai {_fmt_wib(time.time(), '%H:%M:%S')} WIB — "
                   f"{len(outcome['rows'])} mint, {outcome['elapsed']:.1f}s.")
        _render_results(watchlist, outcome["state"])

    _tick()


# ---------------------------------------------------------------------------
# Cek manual satu CA (halaman terpisah, permintaan user 2026-10-20)
# ---------------------------------------------------------------------------
CHECK_RESULT_KEY = "sweep_check_result"  # hasil cek terakhir (tetap saat rerun)


def _vertical_rows(record: dict) -> pd.DataFrame:
    """Ubah satu baris tabel menjadi dua kolom (Kolom, Nilai) untuk halaman cek.

    Nilai dibuat string supaya kolom campuran (angka, teks, URL) tetap bisa
    dirender tanpa error tipe.
    """
    return pd.DataFrame(
        [{"Kolom": str(key), "Nilai": "" if value is None else str(value)}
         for key, value in record.items()],
        columns=["Kolom", "Nilai"])


def render_check_page() -> None:
    """Halaman **🔍 Cek CA Sweep**: periksa satu token secara manual.

    Hasil tidak masuk watchlist, tidak disimpan ke snapshot, dan tidak memicu
    alert Telegram (lihat :mod:`sweep_check`).
    """
    st.markdown("## 🔍 Cek CA Sweep (manual)")
    st.caption(
        "Tempel satu CA token Solana lalu tekan **Cek sekarang**. Token dipindai "
        "live sekali dan dinilai dengan kriteria yang sama seperti 🌊 Sweep. "
        "Hasilnya **tidak** ditambahkan ke watchlist, **tidak** disimpan ke "
        "snapshot, dan **tidak** mengirim alert Telegram. Riwayat tersimpan "
        "(latch shakeout, latch kohort) dibaca bila token sudah pernah dipindai.")

    with st.form("sweep_check_form", clear_on_submit=False):
        raw = st.text_input("Contract address (CA) Solana",
                            key="sweep_check_input",
                            placeholder="contoh: 8nPoBHiBM6pybxMws9PA2JRb9BjkppBfqcZGmot4DMBC")
        submitted = st.form_submit_button("🔍 Cek sekarang", type="primary")

    if submitted:
        mint, error = check.parse_single_ca(raw)
        if error:
            st.session_state[CHECK_RESULT_KEY] = {"ok": False, "error": error,
                                                  "row": None, "ts": None}
        else:
            with st.spinner(f"Memindai {mint[:8]}… (live)"):
                st.session_state[CHECK_RESULT_KEY] = check.check_mint(mint)

    result = st.session_state.get(CHECK_RESULT_KEY)
    if not result:
        st.info("Belum ada hasil. Masukkan CA lalu tekan **Cek sekarang**.")
        return

    if result.get("ts"):
        st.caption(f"Dipindai {_fmt_wib(result['ts'], '%d %b %Y %H:%M:%S')} WIB "
                   "(hasil sekali jalan, tidak disimpan).")
    if result.get("in_watchlist"):
        st.info("CA ini sudah ada di watchlist 🌊 Sweep.")
    row = result.get("row")
    if not result.get("ok") or row is None:
        st.error(f"Cek gagal: {result.get('error') or 'sumber data tidak merespons'}")
        return
    # Tabel kelayakan yang sama dengan 🌊 Sweep, tetapi baca-saja: tanpa kolom
    # Hapus/Refresh, karena halaman cek tidak boleh mengubah watchlist.
    st.markdown("### 🧭 Kelayakan sweep")
    # Satu mint: tampilkan vertikal (dua kolom Kolom | Nilai, baris ke bawah).
    st.dataframe(
        _vertical_rows(_eligibility_rows([row])[0]),
        use_container_width=True, hide_index=True,
        column_config={
            "Kolom": st.column_config.TextColumn("Kolom", width="small"),
            "Nilai": st.column_config.TextColumn("Nilai", width="large"),
        })
    _render_details([row], refresh=False)
