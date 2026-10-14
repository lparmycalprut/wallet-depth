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
diaktifkan, halaman memindai ulang tiap 5 menit selama tab terbuka. Cron GitHub
Actions menangani sisanya saat tab ditutup.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import sweep_alert as alert
import sweep_data as data
import sweep_scan as scan
import sweep_screen as screen
import sweep_store as store

AUTO_REFRESH_SEC = 300  # 5 menit — sama dengan jadwal cron
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
        "murah di-sweep (liq/MC kecil) + authority dilepas + float tersebar + ada "
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


def _request_refresh(mints) -> None:
    """Callback tombol Refresh di tabel: catat mint baris yang diklik.

    Pemindaian dijalankan setelah tabel selesai dirender (bukan di callback),
    karena ``st.rerun`` tidak boleh dipanggil dari dalam callback.
    """
    click = st.session_state.get(REFRESH_CLICK_KEY)
    row = click.get("row") if click else None
    if isinstance(row, int) and 0 <= row < len(mints) and mints[row]:
        st.session_state[PENDING_REFRESH_KEY] = mints[row]


def _render_table(rows, watchlist) -> None:
    """Tabel kelayakan dengan kolom **Hapus** untuk mengeluarkan mint dari watchlist."""
    if not rows:
        st.info("Belum ada mint di watchlist. Tambahkan mint, lalu tekan "
                "**Refresh & ambil snapshot**.")
        return
    frame = pd.DataFrame(_eligibility_rows(rows))
    mints = [row.get("mint") or "" for row in rows]
    frame.insert(0, "Hapus", False)
    # Hapus dan Refresh sama-sama pinned: tetap terlihat saat tabel digeser.
    frame.insert(1, "Refresh", "🔄 Refresh")
    edited = st.data_editor(
        frame, key="sweep_table", use_container_width=True, hide_index=True,
        disabled=[column for column in frame.columns if column != "Hapus"],
        column_config={
            # pinned: kolom tetap terlihat saat tabel digeser ke kanan.
            "Hapus": st.column_config.CheckboxColumn(
                "Hapus", help="Centang lalu tekan tombol di bawah tabel",
                pinned=True),
            "Refresh": st.column_config.ButtonColumn(
                "Refresh", help="Pindai ulang mint ini sekarang juga",
                pinned=True, on_click=_request_refresh, args=(mints,),
                key=REFRESH_CLICK_KEY),
            # Token ikut dipin (urutan kolom: Hapus, Refresh, Token).
            "Token": st.column_config.TextColumn("Token", pinned=True),
            "Kohort": st.column_config.TextColumn("Kohort", width=320),
            "GMGN": st.column_config.LinkColumn("GMGN", display_text="buka"),
        })
    pending = st.session_state.pop(PENDING_REFRESH_KEY, None)
    if pending:
        _refresh_token(pending)  # memanggil st.rerun() di akhir
    flags = edited["Hapus"].tolist() if "Hapus" in edited else []
    picked = _flagged_mints(rows, flags)
    if st.button(f"🗑️ Hapus {len(picked)} mint tercentang dari watchlist",
                 disabled=not picked):
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


def _render_details(rows) -> None:
    for row in rows or []:
        metrics = row.get("metrics") or {}
        result = row.get("result") or {}
        symbol = metrics.get("symbol") or row.get("mint", "")[:8]
        if row.get("ts") is None:
            with st.expander(f"⏳ {symbol} — menunggu snapshot", expanded=False):
                st.caption("Belum ada data untuk mint ini. Tekan refresh "
                           "untuk memindai sekarang.")
                _refresh_button(row.get("mint") or "")
            continue
        context = row.get("sweep_context") or {}
        missing = result.get("missing") or []
        title = (f"{symbol} — {result.get('verdict') or '—'} "
                 f"({result.get('passed_count')}/{result.get('scored_count')}"
                 + (f", {len(missing)} kriteria belum ada data" if missing else "")
                 + ")")
        with st.expander(title, expanded=bool(result.get("eligible"))):
            _refresh_button(row.get("mint") or "")
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
            "Waktu": time.strftime("%m-%d %H:%M",
                                   time.localtime(signal.get("ts") or 0)),
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
        })
    st.dataframe(table, use_container_width=True, hide_index=True)


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
    st.caption("Ambang fix: liq/MC ≤ 35% · holder/wallet ≤ 5% · "
               "kohort minimal minus 50% (VWAP kelahiran 48 jam) · "
               "standar pra-pump COCKROACH (acuan dana 10×)")


def _render_results(watchlist, state) -> None:
    """Tabel + detail + statistik dari snapshot terakhir tiap mint watchlist."""
    views, missing = store.watchlist_views(state, watchlist)
    rows = sorted(views + [_placeholder_row(m) for m in missing],
                  key=lambda row: screen.display_sort_key(row.get("result")))
    st.markdown("### 🧭 Kelayakan sweep")
    _render_table(rows, watchlist)
    if rows:
        _render_details(rows)
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
        # Auto-refresh 5 menit sudah memindai ulang semua mint.
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
    """Pindai ulang tiap 5 menit selama tab terbuka (cron menutup sisanya)."""

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
        st.caption(f"Terakhir dipindai {time.strftime('%H:%M:%S')} — "
                   f"{len(outcome['rows'])} mint, {outcome['elapsed']:.1f}s.")
        _render_results(watchlist, outcome["state"])

    _tick()
