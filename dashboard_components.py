# -*- coding: utf-8 -*-
"""Shared dashboard presentation; importing this module renders no page."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import html
import re
import streamlit as st

from holder_history import (DUST_BEST_LABEL, DUST_CAUTION_PCT,
                            DUST_DANGER_PCT, FULL_SCAN_MAX_WALLETS, INTERVAL_SEC,
                            LP_INTERVAL_SEC, dust_flag, history_for_mint,
                            holders_usable, merge_status_history, resample_4h,
                            resample_5m, usable_points)
from links import external_links_html, holder_analytic_link_html
from lp_watchlist import interval_label, lp_chart_figure
import alert_settings
import robinhood_holders
import robinhood_watchlist
from robinhood_watchlist import RH_LP_SOURCE, RH_REGULAR_SOURCE
from telegram_alerts import (STRATEGY_SHIFT_PCT, STRATEGY_SHIFT_TITLE,
                             delivery_note, process_holder_alerts,
                             summarize_deliveries)
from watchlist_detail import (STALE_AFTER_SEC, STALE_REGULAR_AFTER_SEC,
                              format_wib, previous_pct, resolve_view)


def render_styles() -> None:
    st.markdown("""
    <style>
    .main .block-container {max-width: 1280px; padding-top: 1.5rem;}
    html, body, p, span, div, label, li, td, th,
    h1, h2, h3, h4, h5, h6 {color:#000000;}
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p,
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"],
    [data-testid="stWidgetLabel"] p {color:#000000 !important;}
    .dust-badge {display:inline-block;padding:.28rem .58rem;border-radius:8px;
     font-size:.78rem;font-weight:800}
    .dust-ok {background:#14532d;color:#dcfce7}
    .dust-caution {background:#78350f;color:#fef3c7}
    .dust-danger {background:#7f1d1d;color:#fee2e2}
    .dust-none {background:#e2e8f0;color:#000000}
    .dust-best {background:#3b2f0a;color:#fde047;border:1px solid #facc15}
    .lp-head {display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;
     padding:.5rem 0 .1rem}
    .lp-title {font-size:1.15rem;font-weight:800;color:#000000}
    /* Judul card/section beralih tooltip (title="…") — hint visual halus. */
    .lp-title[title], .md-title-tip[title] {cursor:help;}
    .lp-count {font-size:.75rem;font-weight:700;color:#312e81;background:#e0e7ff;
     padding:.2rem .5rem;border-radius:999px}
    .lp-warn {font-size:.75rem;font-weight:700;color:#7f1d1d;background:#fee2e2;
     padding:.2rem .5rem;border-radius:999px}
    .lp-delta-up {color:#b91c1c;font-weight:800}
    .lp-delta-down {color:#15803d;font-weight:800}
    .watchlist-row {display:flex;align-items:center;padding:.75rem 0;
     border-bottom:1px solid #cbd5e1;}
    .watchlist-token {display:flex;flex-direction:column;gap:.25rem;}
    .watchlist-symbol {font-size:1.1rem;font-weight:800;color:#000000;}
    .watchlist-mint {font-size:.75rem;color:#000000;font-family:monospace;}
    .watchlist-links {display:flex;gap:.5rem;margin-top:.25rem;}
    .watchlist-links a {font-size:.75rem;color:#1d4ed8;font-weight:600;
     text-decoration:none;}
    .watchlist-links a:hover {color:#000000;text-decoration:underline;}
    .watchlist-holder-link {display:flex;align-items:center;justify-content:center;
     width:2rem;height:2rem;border:1px solid #cbd5e1;border-radius:.35rem;
     background:#ffffff;color:#000000;text-decoration:none;font-size:1rem;
     line-height:1;cursor:pointer;}
    .watchlist-holder-link:hover {background:#e0e7ff;border-color:#6366f1;
     color:#000000;text-decoration:none;}
    .watchlist-metric {text-align:center;}
    .watchlist-metric-label {font-size:.65rem;color:#000000;text-transform:uppercase;
     letter-spacing:.04em;}
    .watchlist-metric-value {font-size:.95rem;font-weight:700;color:#000000;}
    .watchlist-metric-sub {font-size:.65rem;color:#000000;}
    .pool-links {display:flex;gap:.5rem;flex-wrap:wrap;justify-content:center;}
    .pool-links a {font-size:.75rem;color:#1d4ed8;font-weight:700;
     text-decoration:none;}
    .pool-links a:hover {color:#000000;text-decoration:underline;}
    </style>
    """, unsafe_allow_html=True)


def _number(value, pattern=".1f"):
    if value is None:
        return "—"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return "—"


def _compact(value, signed=False):
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if signed and n > 0 else ""
    if abs(n) >= 1e6:
        return f"{sign}${n / 1e6:.2f}M"
    if abs(n) >= 1e3:
        return f"{sign}${n / 1e3:.1f}K"
    return f"{sign}${n:,.0f}"


def _wib(ts):
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return "—"
    if stamp <= 0:
        return "—"
    when = datetime.fromtimestamp(stamp, timezone.utc) + timedelta(hours=7)
    return when.strftime("%d %b %H:%M") + " WIB"


def _dust_badge_html(flag: dict) -> str:
    level = flag.get("level") or "unknown"
    label = str(flag.get("label") or "—")
    if flag.get("rising") and level in ("danger", "caution"):
        label = f"{label} ↑"
    cls = {"ok": "dust-ok", "caution": "dust-caution",
           "danger": "dust-danger"}.get(level, "dust-none")
    return f'<span class="dust-badge {cls}">{html.escape(label)}</span>'


def _dust_best_html(flag: dict) -> str:
    """Chip 🏆 BEST POOL — hanya Scan Meteora (permintaan user 2026-09-04).

    ``flag["best"]`` sudah dijamin oleh ``dust_flag(..., holders=..., tvl=...)``:
    dust % MC < 0,1% **dan** data holder valid (total_fetched > 0,
    wallets_analyzed ≥ 40) **dan** TVL pool ≥ 10K USD (2026-09-07) — dust
    "0,00%" dari data gagal tidak pernah mendapat chip ini.
    """
    if not flag.get("best"):
        return ""
    label = html.escape(str(DUST_BEST_LABEL))
    return f'<span class="dust-badge dust-best">🏆 {label}</span>'


def _delta_pp_html(delta, digits: int = 2) -> str:
    """Perubahan dust % MC dalam poin persentase (merah bila naik)."""
    if delta is None:
        return '<span style="color:#64748b;">—</span>'
    try:
        value = float(delta)
    except (TypeError, ValueError):
        return '<span style="color:#64748b;">—</span>'
    cls = "lp-delta-up" if value > 0 else (
        "lp-delta-down" if value < 0 else "")
    text = f"{value:+.{digits}f} pp"
    return f'<span class="{cls}">{text}</span>' if cls else text


SOLANA_CA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_CA_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _ca_error(value) -> str:
    """Pesan error validasi CA; string kosong bila address terlihat valid."""
    ca = str(value or "").strip()
    if not ca:
        return "Masukkan contract address terlebih dahulu."
    if not (SOLANA_CA_RE.match(ca) or EVM_CA_RE.match(ca)):
        return ("Format CA tidak valid. Solana: base58 32–44 karakter · "
                "EVM: 0x + 40 hex.")
    return ""


def _points_for(mint, token, store):
    return merge_status_history(history_for_mint(store, mint),
                                (token or {}).get("history") or [])


def _depth_tables_html(depth: dict) -> str:
    """Tabel Wallet Depth by Threshold + tier ala Solscan (HTML)."""
    def _pct(item):
        pct = item.get("pct_mc")
        return "—" if pct is None else f"{float(pct):.2f}%"

    def _count(item):
        return "—" if item.get("count") is None else f"{int(item['count']):,}"

    bucket_rows = "".join(
        f"<tr><td>{html.escape(str(b.get('label') or ''))}</td>"
        f"<td style='text-align:center'>{_count(b)}</td>"
        f"<td style='text-align:right'>{_compact(b.get('value_usd'))}</td>"
        f"<td style='text-align:right'>{_pct(b)}</td></tr>"
        for b in (depth.get("buckets") or []))
    tier_rows = "".join(
        f"<tr><td>{html.escape(str(t.get('emoji') or ''))} "
        f"{html.escape(str(t.get('tier') or ''))}</td>"
        f"<td style='text-align:center'>{_count(t)}</td>"
        f"<td style='text-align:right'>{_compact(t.get('value_usd'))}</td>"
        f"<td style='text-align:right'>{_pct(t)}</td></tr>"
        for t in (depth.get("tiers") or []))
    style = ("border-collapse:collapse;font-size:.8rem;color:#000000;"
             "margin:0 .6rem .4rem 0;")
    th = "border:1px solid #cbd5e1;padding:.3rem .6rem;background:#f1f5f9;"
    td = "border:1px solid #cbd5e1;padding:.25rem .6rem;"
    return f"""
<div style="display:flex;flex-wrap:wrap;gap:1rem;">
<table style="{style}">
<thead><tr><th style="{th}">Range</th><th style="{th}">Holder</th>
<th style="{th}">Total Value</th><th style="{th}">% Market Cap</th>
</tr></thead><tbody>{bucket_rows}</tbody></table>
<table style="{style}">
<thead><tr><th style="{th}">Tier</th><th style="{th}">Holder</th>
<th style="{th}">Total Value</th><th style="{th}">% Market Cap</th>
</tr></thead><tbody>{tier_rows}</tbody></table>
</div>"""


def _render_depth(holders: dict, symbol: str) -> None:
    """Render Wallet Depth by Threshold dari data holder Helius."""
    depth = holders.get("depth") if isinstance(holders.get("depth"), dict) \
        else None
    if not depth:
        return
    with st.expander(f"📊 Wallet Depth by Threshold — ${symbol} "
                     "(Helius)", expanded=False):
        st.markdown(_depth_tables_html(depth), unsafe_allow_html=True)
        total_all = depth.get("holders_all")
        total_wallet = depth.get("holders_wallet")
        pool_n = int(depth.get("pool_excluded") or 0)
        if depth.get("buckets_include_pools"):
            bucket_line = (f"Bucket dihitung atas semua akun bernilai >$0 "
                           f"({total_all:,} akun, termasuk LP/pool)")
        else:
            bucket_line = (f"Bucket dihitung atas wallet murni saja "
                           f"({total_wallet:,} akun — {pool_n:,} akun "
                           f"LP/pool disingkirkan dari list holder)")
        st.caption(
            f"{bucket_line}; tier atas wallet murni "
            f"({total_wallet:,} wallet). Nilai USD = "
            f"balance × harga token saat scan (DexScreener)."
        )


def _dust_change_empty_note(interval: int) -> str:
    """Pesan bila grafik belum bisa digambar (< 2 bucket layak)."""
    label = interval_label(interval)
    if int(interval) <= LP_INTERVAL_SEC:
        return (f"Butuh minimal 2 titik bucket {label}. Cron watchlist LP "
                f"(tiap ±{label}) atau tombol **Scan sekarang** di card ini "
                "akan mengisinya.")
    return (f"Butuh minimal 2 titik bucket {label}. Scan beberapa kali "
            "(tombol scan di card ini / halaman Holder Analytic) supaya "
            f"bucket {label} terisi.")


def _render_dust_change(points, holders: dict, symbol: str, *,
                        interval: int = INTERVAL_SEC,
                        empty_note: str = "") -> None:
    """Expander **📈 Grafik perubahan dust holder** ala Watchlist Meteora.

    Bentuk yang sama persis dengan expander grafik per token di card
    Watchlist Meteora (`app.py`, permintaan user 2026-09-10: semua card
    watchlist memakai grafik perubahan dust holder, bukan cuma tabel Wallet
    Depth): garis dust % MC + garis ambang HATI-HATI/BAHAYA, batang jumlah
    wallet dust, caption, lalu tabel **📊 Wallet Depth by Threshold**
    ter-nested di dalamnya bila scan menghasilkan ``depth``. ``interval`` =
    bucket resample (``LP_INTERVAL_SEC`` 5 menit untuk lane LP,
    ``INTERVAL_SEC`` 4 jam untuk watchlist biasa).
    """
    label = interval_label(interval)
    with st.expander(f"📈 Grafik perubahan dust holder — ${symbol}",
                     expanded=False):
        figure = lp_chart_figure(points, symbol, interval=interval)
        if figure is None:
            st.info(empty_note or _dust_change_empty_note(interval))
        else:
            import matplotlib.pyplot as plt  # lazy: module-level import
            # dashboard_components ikut di-import jalur non-UI.
            st.pyplot(figure, use_container_width=True)
            plt.close(figure)
        sampled = resample_4h(usable_points(points), interval=interval)
        st.caption(
            f"Garis = dust % marketcap · batang = jumlah wallet dust · "
            f"ambang HATI-HATI {DUST_CAUTION_PCT:g}% / BAHAYA "
            f"{DUST_DANGER_PCT:g}% · titik per {label} "
            f"({len(sampled)} bucket).")
        if isinstance((holders or {}).get("depth"), dict):
            _render_depth(holders, symbol)


def card_head_html(title: str, pills: list[str] | None = None,
                   tooltip: str = "") -> str:
    """Header card grid: judul tebal + pill ringkasan di sebelahnya.

    Dipakai card **Watchlist Meteora** (halaman utama), **Watchlist
    Robinhood**, dan **Scan Meteora Pool** (halaman temp) supaya card yang
    berkepala sama itu punya satu pembuat. ``tooltip`` (opsional) = detail
    karakteristik card yang HANYA muncul saat kursor berada di atas teks
    judul (atribut ``title`` native browser — permintaan user 2026-09-10
    supaya card tetap ramping, bukan caption panjang di badan card). Atribut
    ``title`` tidak mengenal markdown, jadi tulis plain text tanpa ``**``.
    """
    tip = f' title="{html.escape(tooltip)}"' if tooltip else ""
    chips = "".join(pills or [])
    return (f'<div class="lp-head"><span class="lp-title"{tip}>{title}'
            f"</span>{chips}</div>")


def hover_title_html(text: str, tooltip: str) -> str:
    """Judul section (heading markdown ``###``) dengan tooltip di teksnya.

    Pengganti caption panjang di bawah judul section (2026-09-10): detail
    hanya muncul saat kursor berada di atas teks judul — karena itu teksnya
    dibungkus ``<span title="…">``, bukan ditempel di seluruh lebar baris.
    Markdown ``###`` dipertahankan supaya styling sama persis dengan
    ``st.subheader``; atribut ``title`` tidak mengenal markdown (plain text).
    """
    return (f'### <span class="md-title-tip" title="{html.escape(tooltip)}" '
            f'style="cursor:help;">{html.escape(text)}</span>')


RH_CARD_TITLE = "🦅 Watchlist Robinhood"
RH_REGULAR_CARD_TITLE = "🦅 Watchlist Robinhood — Holder Dust"
# Detail karakteristik card LP (2026-09-10) tidak lagi jadi caption panjang
# di badan card — pindah ke tooltip judul (title="…", muncul saat kursor di
# atas teks "Watchlist Robinhood"). Kalau karakteristiknya berubah, ubah
# teks di sini; ambang diambil dari konstanta holder_history supaya tooltip
# tidak pernah beda dengan rule yang benar-benar jalan.
RH_CARD_TOOLTIP = (
    "Watchlist Robinhood LP (0x…, chain id 4663) — di-scan cron tiap ±5 "
    "menit (sejak 2026-09-06, sama cepatnya dengan Watchlist Meteora) "
    "supaya exit bisa lebih awal. Satu-satunya notifikasi Telegram: "
    f"{STRATEGY_SHIFT_TITLE} — dikirim berulang tiap scan selama hold % MC "
    f"dust masih ≥ {STRATEGY_SHIFT_PCT:g}%, berhenti hanya bila token "
    "dihapus (✕) atau dipindah ke watchlist biasa (📋). Notif bisa "
    "dimatikan per token lewat tombol 🔕 di barisnya (token baru selalu "
    "🔔 ON; scan + grafik tetap jalan). Badge level dust "
    f"tetap di baris: ≥ {DUST_CAUTION_PCT:g}% MC = HATI-HATI, "
    f"≥ {DUST_DANGER_PCT:g}% MC = BAHAYA. Data holder dari Blockscout, "
    "harga/marketcap dari DexScreener.")
# Card Robinhood **biasa** (halaman temp): detail karakteristik juga tooltip
# (2026-09-11) — caption panjangnya dihapus karena mengulang isi tooltip dan
# masih menyebut rule 🔔 titik high yang sudah tidak ada.
RH_REGULAR_CARD_TOOLTIP = (
    "Watchlist Robinhood biasa (0x…, chain id 4663) — TIDAK di-scan cron "
    "(slot 4 jam dimatikan); datanya jalan lewat tombol scan manual di "
    "card ini atau pindah ke card LP. Notifikasinya sama seperti lane LP: "
    f"{STRATEGY_SHIFT_TITLE} dikirim tiap scan selama hold % MC dust "
    f"≥ {STRATEGY_SHIFT_PCT:g}% (hanya bila notif watchlist biasa ON di "
    "bawah card dan tombol 🔔 token itu tidak dimatikan). Badge level dust "
    "di baris: "
    f"≥ {DUST_CAUTION_PCT:g}% MC = HATI-HATI, "
    f"≥ {DUST_DANGER_PCT:g}% MC = BAHAYA. Data holder dari Blockscout, "
    "harga/marketcap dari DexScreener.")

ALERT_NOTE_KEY = "manual_alert_note_"


def _store_alert_note(deliveries, key: str) -> None:
    """Simpan ringkasan kirim alert scan manual untuk ditampilkan setelah rerun.

    Ketiga tombol scan manual (Chart LP Meteora, Robinhood LP/biasa, watchlist
    biasa Solana) langsung ``st.rerun()`` setelah scan, jadi catatan hasil
    kirim harus lewat ``session_state`` — permintaan user 2026-09-09: hasil
    scan manual yang memenuhi syarat **ikut dikirim** ke Telegram, dan UI
    harus melaporkan apakah pesannya benar-benar keluar.
    """
    summary = summarize_deliveries(deliveries)
    if not summary.get("total"):
        st.session_state.pop(key, None)
        return
    st.session_state[key] = {"text": delivery_note(summary),
                             "failed": bool(summary.get("failed"))}


def _render_alert_note(key: str) -> None:
    """Tampilkan (sekali) catatan kirim alert scan manual di card."""
    note = st.session_state.pop(key, None)
    if not isinstance(note, dict):
        return
    text = str(note.get("text") or "").strip()
    if not text:
        return
    if note.get("failed"):
        st.warning(text)
    else:
        st.info(text, icon="🚨")


# ---------------------------------------------------------------------------
# Toggle alert Telegram **per token** (🔔/🔕 di tiap baris watchlist)
# ---------------------------------------------------------------------------
# Permintaan user 2026-09-11: *"kasih toggle alert on/off per token yang ada
# di watchlist meteora dan robinhood … jadi misal saya sudah tau ada notif,
# saya bisa nonaktifkan. tapi pas awal memasukkan ke watchlist, otomatis
# on"*. Pilihan user hidup di ``alert_settings.muted_mints`` (blocklist →
# default ON, dan ``watchlist`` membersihkan entri saat token di-add) supaya
# **cron** GitHub Actions ikut menghormatinya — bukan di ``watchlist.json``,
# yang punya jalur journal + merge sendiri.
ALERT_TOGGLE_NOTE_KEY = "alert_toggle_note_"


def _alert_toggle_label(alert_on: bool) -> str:
    """🔔 = notif menyala (klik untuk mematikan), 🔕 = sedang dimatikan."""
    return "🔔" if alert_on else "🔕"


def _alert_toggle_help(symbol: str, alert_on: bool) -> str:
    """Tooltip tombol 🔔/🔕 — menjelaskan apa yang terjadi, bukan rule-nya."""
    if alert_on:
        return (f"Matikan notif Telegram untuk ${symbol}: token tetap "
                "di-scan + grafiknya tetap jalan, hanya pesan 🚨 yang tidak "
                "dikirim. Token yang baru masuk watchlist selalu ON.")
    return (f"Nyalakan lagi notif Telegram untuk ${symbol} (default ON). "
            "Sinyal yang sudah lewat saat mati tidak dikirim ulang.")


def _muted_pill_html(muted: int) -> str:
    """Pill jumlah token yang notifnya dimatikan user (kosong bila 0)."""
    try:
        count = int(muted or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return ""
    return ('<span class="lp-count" style="color:#374151;background:#e5e7eb;">'
            f'🔕 {count}</span>')


def _store_toggle_note(scope: str, text: str) -> None:
    """Simpan catatan toggle untuk ditampilkan setelah rerun (per card)."""
    st.session_state[f"{ALERT_TOGGLE_NOTE_KEY}{scope}"] = str(text)


def _render_toggle_note(scope: str) -> None:
    """Tampilkan (sekali) catatan toggle di card pemiliknya."""
    text = st.session_state.pop(f"{ALERT_TOGGLE_NOTE_KEY}{scope}", None)
    if text:
        st.warning(text, icon="⚠️")


def _mint_alert_on(mint) -> bool:
    """True bila notif Telegram token ini menyala (default = ON)."""
    return not alert_settings.is_mint_muted(mint)


def _alert_toggle_button(column, mint: str, symbol: str, *, scope: str,
                         alert_on: bool) -> None:
    """Render tombol 🔔/🔕 satu baris; klik = simpan pilihan + rerun.

    ``scope`` menentukan awalan key (``lp`` / ``rh`` / ``rhreg``) sekaligus
    card pemilik catatan gagal-sinkron (``_render_toggle_note``) supaya
    peringatan tidak nyasar ke card lain di halaman yang sama.
    """
    if not column.button(_alert_toggle_label(alert_on),
                         key=f"{scope}-alert-{mint}",
                         help=_alert_toggle_help(symbol, alert_on),
                         use_container_width=True):
        return
    ok = alert_settings.set_mint_alert_enabled(mint, not alert_on)
    if not ok:
        _store_toggle_note(
            scope,
            f"Pilihan notif ${symbol} tersimpan di file lokal, tapi "
            "sinkronisasi ke GitHub gagal — cron mungkin masih memakai "
            "setelan lama.")
    try:
        import activity_log
        if ok:
            activity_log.info(
                "alert",
                f"Notif Telegram ${symbol} "
                f"{'dimatikan' if alert_on else 'dinyalakan'} "
                "(toggle per token)")
        else:
            activity_log.warn(
                "alert",
                f"Toggle notif ${symbol} tersimpan lokal, sinkron GitHub "
                "gagal — cron bisa masih memakai setelan lama")
    except Exception:  # noqa: BLE001 - log bersifat pelengkap
        pass
    st.rerun()


RH_ADD_FORM = "rh-add-token"
RH_LP_TAB = "🦅 Robinhood LP (scan ±5 menit)"
RH_REGULAR_TAB = "📋 Robinhood biasa (scan ±4 jam)"
RH_ADD_TARGETS = [RH_LP_TAB, RH_REGULAR_TAB]
RH_ADD_TARGET_SOURCE = {RH_LP_TAB: RH_LP_SOURCE,
                        RH_REGULAR_TAB: RH_REGULAR_SOURCE}


def _rh_head_html(title: str, total: int, danger: int, caution: int,
                  sync: str = "", tooltip: str = "",
                  muted: int = 0) -> str:
    """Kepala card Robinhood; ``sync`` = badge status sinkronisasi GitHub.

    Ditampilkan hanya bila masih ada commit latar belakang berjalan
    (``🔄 sinkron…``) atau commit terakhir gagal (``⚠️ belum sinkron``), jadi
    badge tidak menumpuk saat semua sudah tersimpan. ``muted`` = jumlah token
    yang toggle 🔕-nya dimatikan user. ``tooltip`` = detail karakteristik card
    di atribut judul (lihat ``card_head_html``).
    """
    pills = [f'<span class="lp-count">{total} token</span>']
    muted_pill = _muted_pill_html(muted)
    if muted_pill:
        pills.append(muted_pill)
    if sync == "syncing":
        pills.append('<span class="lp-count">🔄 sinkron…</span>')
    elif sync == "error":
        pills.append('<span class="lp-warn">⚠️ belum sinkron</span>')
    if danger:
        pills.append(f'<span class="lp-warn">BAHAYA {danger}</span>')
    if caution:
        pills.append(f'<span class="lp-warn" style="color:#78350f;'
                     f'background:#fef3c7;">HATI-HATI {caution}</span>')
    return card_head_html(title, pills, tooltip=tooltip)


def _rh_scope(variant: str) -> str:
    """Awalan key tombol card Robinhood: ``rh`` (LP) / ``rhreg`` (biasa).

    Kunci tombol varian LP dipertahankan ``rh-*`` (kompatibilitas uji UI);
    varian biasa memakai awalan ``rhreg-*`` supaya tombol kedua card tidak
    bentrok saat token berpindah card dalam satu sesi. Dipakai juga sebagai
    ``scope`` catatan toggle alert (``_render_toggle_note``).
    """
    return "rh" if variant == "lp" else "rhreg"


def _render_rh_row(row: dict, *, variant: str = "lp") -> None:
    """Satu baris watchlist Robinhood (``variant`` = ``lp`` / ``regular``)."""
    prefix = _rh_scope(variant)
    mint = row.get("mint") or ""
    symbol = row.get("symbol") or "?"
    holders = row.get("holders") or {}
    flag = row.get("flag") or {}
    dust_count = row.get("dust_count")
    dust_pct = row.get("dust_pct")
    truncated = bool(holders.get("truncated"))
    dust_txt = ("—" if dust_count is None
                else (f"≥{int(dust_count)}" if truncated
                      else f"{int(dust_count):,}"))
    pct_txt = "—" if dust_pct is None else f"{float(dust_pct):.2f}%"

    # 7 kolom: token · dust · hold %MC · 🧮 holder · 🔔 toggle alert ·
    # aksi pindah card · hapus (kolom toggle ditambah 2026-09-11).
    cols = st.columns([1.7, 0.8, 0.95, 0.42, 0.42, 0.42, 0.42])
    alert_on = _mint_alert_on(mint)
    chain_note = ("LP · scan ±5 menit" if variant == "lp"
                  else "biasa · scan ±4 jam")
    # Scan yang pulang dengan 0 wallet (provider holder gagal/kena rate limit)
    # tidak boleh terbaca seperti hasil: bilang terus terang apa yang terjadi.
    fetch_error = str(holders.get("fetch_error") or "")
    if holders.get("blocked"):
        # 403 bot-protection Blockscout publik (2026-09-08): ringkas +
        # langsung ke obatnya; pesan panjangnya terpotong 90 karakter.
        fetch_error = ("Blockscout 403 — semua key PRO ditolak/kredit habis"
                       if holders.get("pro_keys") else
                       "Blockscout 403 bot-protection — pasang "
                       "BLOCKSCOUT_API_KEY (PRO API)")
    scan_note = f"scan {format_wib(row.get('view_ts'))}"
    if holders and not holders_usable(holders):
        scan_note += " · ⚠️ scan terakhir tidak lengkap"
        if fetch_error:
            scan_note += f" ({html.escape(fetch_error[:90])})"
    elif fetch_error:
        scan_note += f" · ⚠️ provider holder: {html.escape(fetch_error[:90])}"
    if not alert_on:
        scan_note += " · 🔕 notif off"
    cols[0].markdown(
        f'<div class="watchlist-token">'
        f'<span class="watchlist-symbol">${html.escape(symbol)}</span>'
        f'<span class="watchlist-mint">{html.escape(mint[:10])}…</span>'
        f'<span class="watchlist-metric-sub">'
        f'MC {_compact(row.get("mc"))} · chain Robinhood · {chain_note} · '
        f'{scan_note}</span>'
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
        f'{_dust_badge_html(flag)}</div>', unsafe_allow_html=True)
    cols[3].markdown(holder_analytic_link_html(mint),
                     unsafe_allow_html=True)
    # 🔔/🔕: notif Telegram khusus token ini (token baru selalu ON).
    _alert_toggle_button(cols[4], mint, symbol, scope=prefix,
                         alert_on=alert_on)
    if variant == "lp":
        if cols[5].button("📋", key=f"rh-move-{mint}",
                          help="Pindahkan ke Watchlist Robinhood (biasa, "
                               "halaman temp) — pengingat 🚨 dust ≥ 0,06% MC "
                               "berhenti",
                          use_container_width=True):
            robinhood_watchlist.set_robinhood_watchlist_source(
                mint, RH_REGULAR_SOURCE, background=True)
            st.rerun()
        remove_col = cols[6]
    else:
        if cols[5].button("⚡", key=f"rhreg-move-{mint}",
                          help="Pindahkan ke Watchlist Robinhood LP "
                               "(scan cepat ±5 menit)",
                          use_container_width=True):
            robinhood_watchlist.set_robinhood_watchlist_source(
                mint, RH_LP_SOURCE, background=True)
            st.rerun()
        remove_col = cols[6]
    if remove_col.button("✕", key=f"{prefix}-remove-{mint}",
                         help="Hapus dari watchlist Robinhood",
                         use_container_width=True):
        robinhood_watchlist.remove_from_robinhood_watchlist(
            mint, background=True)
        st.rerun()
    # Grafik perubahan dust holder ala Watchlist Meteora (permintaan user
    # 2026-09-10) — lane LP bucket 5 menit, lane biasa bucket 4 jam; tabel
    # Wallet Depth by Threshold ikut ter-nested di dalam expander.
    _render_dust_change(row.get("points"), holders, symbol,
                        interval=(LP_INTERVAL_SEC if variant == "lp"
                                  else INTERVAL_SEC))
    st.markdown('<hr style="margin:0.3rem 0;border-color:#cbd5e1;">',
                unsafe_allow_html=True)


def _render_rh_card(watchlist: dict, status_tokens: dict,
                    history_store: dict, now: int, *,
                    variant: str = "lp",
                    merge_status: dict | None = None) -> None:
    """Card watchlist Robinhood Chain (EVM): ``lp`` (cepat) / ``regular``."""
    rows = []
    danger = caution = 0
    for mint, meta in (watchlist or {}).items():
        token = status_tokens.get(mint) or {}
        points = merge_status_history(history_for_mint(history_store, mint),
                                      token.get("history") or [])
        view = resolve_view(
            token, points, now=now,
            stale_after=(STALE_AFTER_SEC if variant == "lp"
                         else STALE_REGULAR_AFTER_SEC))
        sampled = (resample_5m(points) if variant == "lp"
                   else resample_4h(points))
        prev = previous_pct(sampled, view)
        dust_pct = view.get("dust_pct")
        flag = dust_flag(dust_pct, prev, holders=token.get("holders"))
        level = flag.get("level")
        if level == "danger":
            danger += 1
        elif level == "caution":
            caution += 1
        rows.append({
            "mint": mint,
            "symbol": str(meta.get("symbol") or token.get("symbol") or "?")
            .upper(),
            "holders": token.get("holders") or {},
            "dust_count": view.get("dust_count"),
            "dust_pct": dust_pct,
            "flag": flag,
            "points": points,
            "mc": view.get("mc"),
            "view_ts": view.get("ts"),
            "delta_4h": (view.get("latest") or {}).get("delta_pp")
            if isinstance(view.get("latest"), dict) else None,
            "delta_total": view.get("delta_total"),
        })

    muted = alert_settings.mutes_for(watchlist or {})
    title = RH_CARD_TITLE if variant == "lp" else RH_REGULAR_CARD_TITLE
    with st.container(border=True):
        # Detail karakteristik KEDUA card = tooltip di teks judul
        # (2026-09-10; card biasa menyusul 2026-09-11) — bukan caption
        # panjang di badan card. Lihat RH_CARD_TOOLTIP /
        # RH_REGULAR_CARD_TOOLTIP.
        st.markdown(_rh_head_html(title, len(watchlist or {}), danger,
                                  caution, muted=len(muted),
                                  sync=robinhood_watchlist.sync_state().get(
                                      "state") or "",
                                  tooltip=RH_CARD_TOOLTIP if variant == "lp"
                                  else RH_REGULAR_CARD_TOOLTIP),
                    unsafe_allow_html=True)
        # Caption rule di card biasa DIHAPUS (2026-09-11): tulisan itu
        # mengulang isi tooltip judul, dan rule 🔔 titik high sudah tidak ada.
        # Karakteristik card pindah ke RH_REGULAR_CARD_TOOLTIP (tooltip judul).

        with st.expander("➕ Tambah token Robinhood ke watchlist",
                         expanded=not rows):
            with st.form(RH_ADD_FORM, clear_on_submit=True):
                rh_ca = st.text_input(
                    "Contract address (0x…)", key="rh-ca-input",
                    help="Pastikan address benar di rh-scan.com / "
                         "Blockscout")
                rh_target = st.radio(
                    "Masuk ke card", RH_ADD_TARGETS, index=(0 if variant == "lp" else 1),
                    key="rh-add-target", horizontal=True,
                    help=("🦅 Robinhood LP = scan cepat ±5 menit + "
                          "pengingat 🚨 tiap scan selama dust ≥ 0,06% MC. "
                          "📋 Robinhood biasa = tidak di-scan cron "
                          "(4 jam dimatikan); pakai pindah card / "
                          "scan manual."))
                if st.form_submit_button(
                        "🦅 Tambah ke Watchlist Robinhood"):
                    ca = str(rh_ca or "").strip()
                    if not robinhood_holders.is_robinhood_address(ca):
                        st.warning("Format CA Robinhood tidak valid. "
                                   "Gunakan 0x + 40 hex.")
                    else:
                        robinhood_watchlist.add_to_robinhood_watchlist(
                            ca, "?",
                            source=RH_ADD_TARGET_SOURCE.get(
                                rh_target, RH_LP_SOURCE),
                            background=True)
                        st.success(f"{ca[:10]}… masuk watchlist "
                                   "Robinhood.")
                        st.rerun()

        if st.button(("🔄 Scan holder watchlist Robinhood LP" if variant == "lp"
                      else "🔄 Scan holder watchlist Robinhood biasa"),
                     type="primary", use_container_width=True):
            bar = st.progress(0.0, text="Scan Robinhood 0/…")

            def _progress(index, total, label):
                bar.progress(index / max(total, 1),
                             text=f"Scan {index}/{total} · {label}")

            try:
                analyses = robinhood_watchlist.scan_watchlist(
                    watchlist, history_store=history_store,
                    max_wallets=FULL_SCAN_MAX_WALLETS, workers=4,
                    progress=_progress)
            finally:
                bar.empty()
            ok = {mint: item for mint, item in analyses.items()
                  if isinstance(item, dict)}
            # Sama seperti watchlist Solana: scan bersampel pendek tidak
            # menimpa data tercatat, dan snapshot di-merge supaya token
            # yang tidak ikut scan run ini tidak hilang.
            fresh = {mint: item for mint, item in ok.items()
                     if holders_usable(item.get("holders"))}
            if fresh:
                # Alert ikut dievaluasi + dikirim dari scan manual (permintaan
                # user 2026-09-09), bukan hanya dari cron. HARUS sebelum
                # publish_scan: rule membaca marker lama, dan state hasil
                # evaluasi (sent_event_ids/last_sent/marker 🚨) ikut tertulis
                # saat ingest_many menyimpan store — pola cron scan_holders.py.
                # advance_anchors=False: scan ad-hoc tidak menggeser anchor
                # 4 jam / peta wallet milik scan FULL cron.
                # Mute = evaluasi + marker tetap jalan, hanya pengiriman yang
                # dilewati. Dua sumbernya: toggle 🔔/🔕 **per token**
                # (alert_settings.muted_mints — berlaku juga di cron) dan
                # toggle global notif watchlist biasa untuk lane non-LP
                # (card Robinhood biasa di halaman temp).
                muted = alert_settings.mutes_for(fresh)
                if variant != "lp" \
                        and not alert_settings.regular_telegram_enabled():
                    muted |= set(fresh)
                _store_alert_note(process_holder_alerts(
                    fresh, history_store, mute_mints=muted,
                    watchlist_meta=watchlist,
                    advance_anchors=False), f"{ALERT_NOTE_KEY}rh_{variant}")
                robinhood_watchlist.publish_scan(
                    fresh, watchlist, history_store=history_store,
                    push=False, merge_status=merge_status)
                st.success(f"{len(fresh)} token Robinhood diperbarui"
                           + (f" · {len(ok) - len(fresh)} scan tidak "
                              "lengkap dilewati" if len(ok) != len(fresh)
                              else "") + ".")
            else:
                st.warning("Tidak ada token Robinhood yang berhasil "
                           "dianalisis — data yang sudah tercatat tidak "
                           "diubah.")
            st.rerun()

        _render_alert_note(f"{ALERT_NOTE_KEY}rh_{variant}")
        _render_toggle_note(_rh_scope(variant))

        if not rows:
            empty_text = (
                "Watchlist Robinhood LP masih kosong. Tambahkan address "
                "0x… di form atas."
                if variant == "lp" else
                "Watchlist Robinhood biasa masih kosong — pindahkan token "
                "dari card Robinhood LP di halaman utama (📋) atau "
                "tambahkan lewat form di atas.")
            st.info(empty_text)
            return

        header = st.columns([1.7, 0.8, 0.95, 0.42, 0.42, 0.42, 0.42])
        style = "font-size:0.72rem;color:#000000;font-weight:700;"
        titles = ["Token", "Dust", "Hold %MC", "", "", "", ""]
        for col, col_title in zip(header, titles):
            align = "" if col_title == "Token" else "text-align:center;"
            col.markdown(f'<div style="{style}{align}">{col_title}</div>',
                         unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.4rem 0;border-color:#cbd5e1;">',
                    unsafe_allow_html=True)
        for row in rows:
            _render_rh_row(row, variant=variant)



@dataclass
class DashboardData:
    watchlist: dict
    status: dict
    history: dict
    rh_watchlist: dict
    rh_status: dict
    rh_history: dict


def load_dashboard_data() -> DashboardData:
    """Read the existing stores, keeping Solana and Robinhood separate.

    Both pages use the same files and manual-scan overlay. No migration,
    rescan, or write occurs merely because a section moved to another page.
    """
    import holder_history as hh
    import holder_status as hs
    import watchlist as wl

    watch = wl.load_watchlist()
    force = bool(st.session_state.pop("status_force_refresh", False))
    status = hs.apply_manual_scan(
        hs.load_holder_status(force_refresh=force),
        st.session_state.get(hs.MANUAL_SCAN_KEY))
    history = hh.seed_from_status(hh.load_durable_holder_history(), status)
    rh_watch = robinhood_watchlist.load_watchlist()
    rh_status = (robinhood_watchlist.load_status() if rh_watch
                 else {"updated_at": None, "tokens": {}})
    rh_history = (robinhood_watchlist.load_history() if rh_watch
                  else {"updated_at": None, "tokens": {}})
    return DashboardData(watch, status, history, rh_watch, rh_status, rh_history)
