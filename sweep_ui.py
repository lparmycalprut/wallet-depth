# -*- coding: utf-8 -*-
"""UI page **🌊 Sweep Screener** (permintaan user 2026-10-12).

Halaman terpisah dari **🏆 Scan Best Pool Meteora** — ``app.py`` tidak disentuh;
entri-nya ada di ``pages/8_🌊_Sweep.py`` (multipage bawaan Streamlit).

Isi halaman:

1. **Watchlist manual** — tempel mint, satu per baris.
2. **Tabel kelayakan** — 6 kriteria menjadi skor + vonis, plus kolom pasar.
3. **Detail per mint** — alasan tiap kriteria + tabel biaya sweep (rumus
   ``(akar(m)-1) x liq/MC``).
4. **Statistik** — riwayat sinyal beserta ``max_up`` / ``max_down`` sehingga
   hit rate bisa dilihat, bukan ditebak.

Auto-refresh memakai ``st.fragment(run_every=…)`` (Streamlit 1.61): kalau
diaktifkan, halaman memindai ulang tiap 5 menit selama tab terbuka. Cron GitHub
Actions menangani sisanya saat tab ditutup.
"""
from __future__ import annotations

import json
import time

import streamlit as st

import sweep_alert as alert
import sweep_data as data
import sweep_scan as scan
import sweep_screen as screen
import sweep_store as store

AUTO_REFRESH_SEC = 300  # 5 menit — sama dengan jadwal cron


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
        "murah di-sweep (liq/MC kecil) + LP terkunci + float tersebar + ada "
        "jejak akumulasi. Alert Telegram dikirim saat kelayakan muncul dan "
        "saat sweep mulai terjadi."
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
            saved = store.save_watchlist(text, persist=False)
            if store.push_watchlist(saved):
                _flash("success",
                       f"{len(saved)} mint disimpan + di-commit ke GitHub.")
            else:
                # Streamlit Cloud sistem berkasnya sementara: kalau tidak
                # di-commit, daftar ini hilang saat container restart.
                _stash_watchlist_in_config(saved)
                _flash("warning",
                       f"{len(saved)} mint tersimpan **lokal + cadangan "
                       "`config.json`**. Commit ke GitHub gagal (token belum "
                       "diisi?) — isi token GitHub supaya daftar ikut "
                       "tersimpan permanen di repo.")
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
            "Vonis": result.get("verdict") or "—",
            "Skor": (f"{result.get('passed_count')}/{result.get('scored_count')}"
                     if result.get("scored_count") else "—"),
            "Kriteria": passed or "—",
            "Harga": _fmt_price(metrics.get("price_usd")),
            "liq/MC": _fmt_pct(result.get("liq_mc")),
            "Liq": _fmt_usd(metrics.get("liq_usd")),
            "MC": _fmt_usd(metrics.get("fdv_usd")),
            "LP locked": _fmt_pct100(metrics.get("lp_locked_pct")),
            "Top-10": _fmt_pct100(metrics.get("top10_holder_pct")),
            "Holder": metrics.get("holder_count"),
            "Bundler": _fmt_pct(metrics.get("bundler_rate")),
            "Bot degen": _fmt_pct(metrics.get("bot_degen_rate")),
            "Vol 1h": _fmt_usd(metrics.get("vol_1h")),
            "Sweep": (f"⚡ {_fmt_mult(context.get('vol_x'))} vol"
                      if context else "—"),
            "GMGN": _link(row.get("mint") or ""),
        })
    return out


def _render_table(rows) -> None:
    if not rows:
        st.info("Belum ada hasil. Tambahkan mint ke watchlist lalu tekan "
                "**Scan sekarang**.")
        return
    st.dataframe(_eligibility_rows(rows), use_container_width=True,
                 hide_index=True, column_config={
                     "GMGN": st.column_config.LinkColumn(
                         "GMGN", display_text="buka")})


def _render_details(rows) -> None:
    for row in rows or []:
        metrics = row.get("metrics") or {}
        result = row.get("result") or {}
        symbol = metrics.get("symbol") or row.get("mint", "")[:8]
        context = row.get("sweep_context") or {}
        missing = result.get("missing") or []
        title = (f"{symbol} — {result.get('verdict') or '—'} "
                 f"({result.get('passed_count')}/{result.get('scored_count')}"
                 + (f", {len(missing)} kriteria belum ada data" if missing else "")
                 + ")")
        with st.expander(title, expanded=bool(result.get("eligible"))):
            if metrics.get("error"):
                st.warning(f"Sumber data: {metrics['error']}")
            st.caption(
                f"liq {_fmt_usd(metrics.get('liq_usd'))} · "
                f"MC {_fmt_usd(metrics.get('fdv_usd'))} · "
                f"liq/MC {_fmt_pct(result.get('liq_mc'))} · "
                f"{metrics.get('dex_id') or '—'} · "
                f"{metrics.get('pool_count') or 0} pool")
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
                st.markdown("**Biaya sweep** (`(akar(m)-1) x liq/MC`):")
                st.dataframe(
                    [{"Target": _fmt_mult(t["mult"], 0),
                      "Biaya (% MC)": (f"{t['cost_pct']:.1f}%"
                                       if t.get("cost_pct") is not None else "—"),
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
def _run_and_render(watchlist, *, persist: bool, settings=None) -> None:
    with st.spinner(f"Memindai {len(watchlist)} mint…"):
        outcome = scan.run_scan(watchlist, persist=persist, settings=settings)
    st.session_state["sweep_rows"] = outcome["rows"]
    st.session_state["sweep_state"] = outcome["state"]
    st.session_state["sweep_alerts"] = outcome["alerts"]
    st.session_state["sweep_elapsed"] = outcome["elapsed"]


def _render_threshold(state) -> tuple:
    """Slider ambang liq/MC + tabel biaya sweep. → (settings, berubah?)."""
    config = store.load_settings(state)
    key = "sweep_liq_mc_pct"
    st.session_state.setdefault(key, int(round(config["liq_mc_max"] * 100)))
    st.markdown("### ⚙️ Ambang kelayakan")
    pct = st.slider(
        "liq/MC maksimum (%)", min_value=5, max_value=60, step=1, key=key,
        help="Bukan batas alam: yang menentukan biaya sweep adalah "
             "(akar(m) − 1) × (liq/MC). Menurunkan ambang = lebih sedikit "
             "kandidat tapi lebih murah digerakkan; menaikkan = lebih banyak "
             "kandidat tapi biaya sweep naik.")
    ratio = pct / 100.0
    st.caption("Pada ambang " + f"{pct}%: " + " · ".join(
        f"naik {t['mult']:.0f}x = {t['cost_pct']:.0f}% MC "
        f"(leverage {t['leverage']:.0f}x)"
        for t in screen.target_costs(ratio, mults=(2.0, 3.0, 5.0, 10.0))))
    settings = screen.normalize_settings({"liq_mc_max": ratio})
    changed = abs(settings["liq_mc_max"] - config["liq_mc_max"]) > 1e-9
    return settings, changed


def _render_body(*, persisting: bool) -> None:
    watchlist = store.load_watchlist()
    state = st.session_state.get("sweep_state") or store.load_state()

    settings, threshold_changed = _render_threshold(state)
    if threshold_changed:
        # Dinilai ulang dari data yang sudah ada di memori — tidak ada
        # panggilan jaringan hanya karena ambang digeser.
        store.save_settings(state, settings)
        rows = st.session_state.get("sweep_rows")
        if rows:
            st.session_state["sweep_rows"] = scan.rescore_rows(
                rows, state, settings)
        if persisting:
            store.save_state(state, persist=True, reason="ambang liq/MC")
        # Pesan ditampilkan langsung (bukan lewat antrean flash): jalur ini
        # tidak memanggil st.rerun, jadi tidak ada yang menghapusnya.
        st.success(f"Ambang liq/MC {settings['liq_mc_max']*100:.0f}% diterapkan "
                   "ke data yang sudah ada — tanpa scan ulang.")

    col_scan, col_auto = st.columns([1, 2])
    if col_scan.button("🔍 Scan sekarang", type="primary",
                       use_container_width=True, disabled=not watchlist):
        _run_and_render(watchlist, persist=persisting, settings=settings)
        _flash("success", f"Scan selesai: {len(watchlist)} mint dipindai.")
        st.rerun()
    auto = col_auto.toggle(
        f"Auto-refresh tiap {AUTO_REFRESH_SEC // 60} menit (selama tab terbuka)",
        value=st.session_state.get("sweep_auto", False), key="sweep_auto")

    rows = st.session_state.get("sweep_rows")
    if rows is None and watchlist:
        _run_and_render(watchlist, persist=persisting, settings=settings)
        rows = st.session_state.get("sweep_rows")
    rows = rows or []
    state = st.session_state.get("sweep_state") or state

    sent = [a for a in (st.session_state.get("sweep_alerts") or [])
            if a.get("sent")]
    if sent:
        st.success("Alert terkirim: " + ", ".join(
            f"{a['kind']} {a['mint'][:8]}" for a in sent))

    st.markdown("### 🧭 Kelayakan sweep")
    _render_table(rows)
    if rows:
        _render_details(rows)
    st.divider()
    _render_stats(state)
    return auto


def render_sweep_page() -> None:
    """Render halaman lengkap (dipanggil dari ``pages/8_🌊_Sweep.py``)."""
    _render_flash()
    _render_header()
    st.divider()
    watchlist = _render_watchlist()
    st.divider()

    # Persistensi GitHub hanya saat memang ada perubahan layak-commit, supaya
    # halaman tidak membuat commit tiap rerun Streamlit.
    persisting = _should_persist()
    auto = _render_body(persisting=persisting)
    if auto:
        _attach_autorefresh(watchlist)


def _should_persist() -> bool:
    return bool(alert.telegram_config().get("ok") or store._github_token())


def _attach_autorefresh(watchlist) -> None:
    """Pindai ulang tiap 5 menit selama tab terbuka (cron menutup sisanya)."""

    @st.fragment(run_every=AUTO_REFRESH_SEC)
    def _tick() -> None:
        if not watchlist:
            return
        outcome = scan.run_scan(
            watchlist, persist=False,
            settings=store.load_settings(st.session_state.get("sweep_state")
                                         or store.load_state()))
        fingerprint = store.fingerprint(outcome["state"])
        last = st.session_state.get("sweep_fingerprint")
        st.session_state["sweep_fingerprint"] = fingerprint
        st.session_state["sweep_rows"] = outcome["rows"]
        st.session_state["sweep_state"] = outcome["state"]
        if last is not None and fingerprint != last:
            store.save_state(outcome["state"], persist=True, reason="auto-refresh")
        st.caption(f"Terakhir dipindai {time.strftime('%H:%M:%S')} — "
                   f"{len(outcome['rows'])} mint, {outcome['elapsed']:.1f}s.")

    _tick()
