# -*- coding: utf-8 -*-
"""
Wallet Depth — Prepump Radar (4-pillar multi-day, 2026-08-12)

Kept functions only:
  - watchlist (vertical list + 4-pilar pre-pump status)
  - scan trending / scan degen (with all filters, only Watchlist button)
  - CVD deep analysis (pages/4_📊_CVD.py) with 1–7 day fetch
  - signals.json + cvd_daily.json written by the 4h/daily cron

Scoring 0–100 / Grade A-B-C is no longer the watchlist verdict.
Each token is PASS / WATCH / FAIL / STEALTH DUMP from the 4 pillars.
"""
import html
import time
from datetime import datetime, timezone, timedelta

import streamlit as st

from core import load_config, get_helius_keys
from watchlist import (
    load_watchlist, add_to_watchlist, remove_from_watchlist,
    get_last_push_error, resolve_wyckoff_row, resolve_prepump_row,
    meta_details_stale,
)

st.set_page_config(
    page_title="Wallet Depth — Prepump",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Deep (tua) greens / reds — no neon glow. Easier on the eyes.
st.markdown("""
<style>
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1280px;
    }
    .stButton button {
        font-size: 0.95rem;
        padding: 0.55rem 1.1rem;
        border-radius: 10px;
        font-weight: 600;
    }
    .stTextInput input, .stSelectbox select {
        border-radius: 10px;
        font-size: 1rem;
    }
    .watch-row {
        padding: 8px 6px;
        line-height: 1.5;
        font-size: 0.88rem;
        color: #1e293b;
    }
    .watch-muted {
        font-size: 0.72rem;
        color: #475569;
        font-weight: 500;
    }
    .wl-head {
        color: #334155;
        font-size: 0.78rem;
        letter-spacing: 0.02em;
        font-weight: 700;
    }
    .section-header {
        font-size: 1.35rem;
        font-weight: 700;
        margin: 1.25rem 0 0.4rem 0;
        color: #0f172a;
    }

    @media (prefers-color-scheme: dark) {
        .section-header { color: #e2e8f0; }
        .stMarkdown, .stCaption { color: #cbd5e1; }
        .watch-row { color: #e2e8f0; }
        .watch-muted { color: #94a3b8; }
        .wl-head { color: #cbd5e1; }
        .stButton button {
            background-color: #1e2937;
            color: #e2e8f0;
            border: 1px solid #475569;
        }
    }

    .stMarkdown, .stCaption {
        font-size: 0.95rem;
        line-height: 1.55;
    }
    .glowing-pass {
        background-color: #14532d;
        border: 1px solid #166534 !important;
        color: #dcfce7 !important;
        border-radius: 8px;
        padding: 6px 8px;
        font-weight: 700;
    }
    .glowing-fail {
        background-color: #7f1d1d;
        border: 1px solid #991b1b !important;
        color: #fee2e2 !important;
        border-radius: 8px;
        padding: 6px 8px;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
WIB = timezone(timedelta(hours=7))

def _fmt_ts(ts):
    if not ts:
        return "—"
    try:
        dt = datetime.fromtimestamp(int(ts), tz=WIB)
        return dt.strftime("%m-%d %H:%M WIB")
    except Exception:
        return "—"

def get_signal_for_ca(ca: str, sigs: list):
    """Return the latest 4-pillar (preferred) or Wyckoff 15M signal."""
    four = None
    wyck = None
    for item in reversed(sigs or []):
        if item.get("ca") != ca:
            continue
        if four is None and item.get("type") == "prepump_4pilar":
            four = item
        if (wyck is None and "score" in item
                and "holder_lock_pct" in item
                and item.get("type") != "prepump_4pilar"):
            wyck = item
        if four and wyck:
            break
    return {"four": four, "wyckoff": wyck}

@st.cache_data(ttl=600, show_spinner=False)
def fetch_gmgn_top_holder_summary(ca: str) -> dict:
    """Fetch live GMGN token_stat as fallback for diamond hand and real/dust.

    Price is required for the real/dust split (holder USD value vs dust
    limit) — without it every holder would be valued at $0 and counted as
    dust. Price is taken from the GMGN raw payload first, then DexScreener.
    """
    try:
        from core import gmgn_token_stat, get_market
        from cvd import top_holder_analysis, get_recent_swaps
        stat = gmgn_token_stat(ca, timeout=12)
        holders = stat.get("holders") or []
        if not holders:
            return {}
        # Price for real/dust valuation: GMGN raw -> DexScreener fallback.
        price = 0.0
        raw = stat.get("raw") or {}
        if isinstance(raw, dict):
            for key in ("price", "price_usd", "last_trade_price", "priceUsd"):
                try:
                    v = float(raw.get(key) or 0)
                except (TypeError, ValueError):
                    continue
                if v > 0:
                    price = v
                    break
        if price <= 0:
            try:
                market = get_market(ca)
                price = float(market.get("price_usd") or 0)
            except Exception:
                price = 0.0
        swaps_72h = get_recent_swaps(ca, hours=72)
        tha = top_holder_analysis(holders, swaps=swaps_72h,
                                  price_usd=price,
                                  dust_limit_usd=5.0,
                                  supply=stat.get("supply") or 0.0)
        return {
            "diamond_pct": round(float(tha.get("diamond_pct") or 0.0), 1),
            "real_holders": int(tha.get("all_real_holders") if tha.get("all_real_holders") is not None else (tha.get("real_holders") or 0)),
            "dust_holders": int(tha.get("all_dust_holders") if tha.get("all_dust_holders") is not None else max(0, tha.get("all_holders", 0) - (tha.get("real_holders") or 0))),
        }
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def fetch_helius_top_holder_summary(ca: str, key_pool: tuple) -> dict:
    """Live Helius top-holder summary (diamond + real/dust) for the watchlist.

    Uses the same source as the CVD page (full holder list from Helius,
    DexScreener price) so the main-app columns stop showing "—" when the
    cron metadata / snapshots are missing. Returns {} on any failure.
    """
    try:
        from core import get_holders as core_get_holders
        from core import get_supply as core_get_supply
        from core import get_market
        from cvd import top_holder_analysis, get_recent_swaps
        import pandas as pd
        supply, _dec = core_get_supply(key_pool, ca)
        df = core_get_holders(key_pool, ca)
        if df is None or df.empty or "owner" not in df.columns:
            return {}
        price = 0.0
        try:
            market = get_market(ca)
            price = float(market.get("price_usd") or 0)
        except Exception:
            price = 0.0
        holders = [[str(o), float(a)] for o, a in
                   zip(df["owner"], df["raw_amount"]) if float(a) > 0]
        if not holders:
            return {}
        swaps_72h = get_recent_swaps(ca, hours=72)
        tha = top_holder_analysis(holders, swaps=swaps_72h,
                                  price_usd=price,
                                  dust_limit_usd=5.0,
                                  supply=float(supply or 0.0))
        return {
            "diamond_pct": round(float(tha.get("diamond_pct") or 0.0), 1),
            "real_holders": int(tha.get("all_real_holders") if tha.get("all_real_holders") is not None else (tha.get("real_holders") or 0)),
            "dust_holders": int(tha.get("all_dust_holders") if tha.get("all_dust_holders") is not None else max(0, tha.get("all_holders", 0) - (tha.get("real_holders") or 0))),
        }
    except Exception:
        return {}


def get_watchlist_details(ca: str, meta: dict) -> dict:
    """Ambil detail tambahan untuk watchlist (diamond, real/dust)."""
    details = {
        "diamond_pct": meta.get("diamond_pct"),
        "real_holders": meta.get("real_holders"),
        "dust_holders": meta.get("dust_holders"),
        "down_ath": meta.get("down_ath"),
    }
    stale_details = meta_details_stale(meta)

    # Frozen meta from add-day / deleted cron must not block a live refresh.
    if stale_details:
        live = {}
        if helius_keys:
            live = fetch_helius_top_holder_summary(ca, helius_keys) or {}
        if not live:
            live = fetch_gmgn_top_holder_summary(ca) or {}
        if live:
            if live.get("diamond_pct") is not None:
                details["diamond_pct"] = live.get("diamond_pct")
            if live.get("real_holders") is not None:
                details["real_holders"] = live.get("real_holders")
            if live.get("dust_holders") is not None:
                details["dust_holders"] = live.get("dust_holders")

    # Cek histori real/dust lokal (dari cron) jika belum ada di meta
    if details["real_holders"] is None or details["dust_holders"] is None:
        try:
            from cvd import load_real_dust_history
            rd = load_real_dust_history()
            if ca in rd and rd[ca]:
                last_rd = rd[ca][-1]
                details["real_holders"] = int(last_rd.get("real") or 0)
                details["dust_holders"] = int(last_rd.get("dust") or 0)
        except Exception:
            pass

    # Cek holder snapshots lokal (dari cron) jika belum ada di meta
    if details["diamond_pct"] is None or details["real_holders"] is None:
        try:
            from cvd import load_holder_snapshots, top_holder_analysis, get_recent_swaps
            snaps = (load_holder_snapshots() or {}).get(ca) or {}
            if snaps:
                latest_snap = max(snaps.values(), key=lambda s: s.get("ts", 0))
                holders_list = latest_snap.get("holders", [])
                if holders_list:
                    swaps_72h = get_recent_swaps(ca, hours=72)
                    tha = top_holder_analysis(holders_list, swaps=swaps_72h)
                    if details["diamond_pct"] is None:
                        details["diamond_pct"] = round(float(tha.get("diamond_pct") or 0.0), 1)
                    if details["real_holders"] is None:
                        details["real_holders"] = int(tha.get("all_real_holders") if tha.get("all_real_holders") is not None else (tha.get("real_holders") or 0))
                    if details["dust_holders"] is None:
                        details["dust_holders"] = int(tha.get("all_dust_holders") if tha.get("all_dust_holders") is not None else max(0, tha.get("all_holders", 0) - details["real_holders"]))
        except Exception:
            pass

    # Fallback live via Helius full holder list (sama seperti halaman CVD)
    if details["diamond_pct"] is None or details["real_holders"] is None:
        if helius_keys:
            live_helius = fetch_helius_top_holder_summary(ca, helius_keys)
            if live_helius:
                if details["diamond_pct"] is None:
                    details["diamond_pct"] = live_helius.get("diamond_pct")
                if details["real_holders"] is None:
                    details["real_holders"] = live_helius.get("real_holders")
                if details["dust_holders"] is None:
                    details["dust_holders"] = live_helius.get("dust_holders")

    # Fallback live via GMGN token_stat jika data cron belum tersedia
    if details["diamond_pct"] is None or details["real_holders"] is None:
        live_tha = fetch_gmgn_top_holder_summary(ca)
        if live_tha:
            if details["diamond_pct"] is None:
                details["diamond_pct"] = live_tha.get("diamond_pct")
            if details["real_holders"] is None:
                details["real_holders"] = live_tha.get("real_holders")
            if details["dust_holders"] is None:
                details["dust_holders"] = live_tha.get("dust_holders")

    # Normalisasi angka
    if details["diamond_pct"] is not None:
        try:
            details["diamond_pct"] = round(float(details["diamond_pct"]), 1)
        except Exception:
            details["diamond_pct"] = None

    if details["down_ath"] is not None:
        try:
            details["down_ath"] = round(float(details["down_ath"]), 1)
        except Exception:
            details["down_ath"] = None

    return details


# ---------------------------------------------------------------------------
# Wyckoff 15M signal rendering helpers
# ---------------------------------------------------------------------------
# Short UI label per raw signal type written by scripts/prepump_wyckoff_cron.py
SIGNAL_LABELS = {
    "⭐ GRADE A: GOLDEN SPRING (3-Candle + Smart Buyer)": "⭐ GRADE A GOLDEN SPRING",
    "🟢 GRADE B: HIGH QUALITY ABSORPTION": "🟢 GRADE B ABSORPTION",
    "⚪ GRADE C: ROUTINE NOISE": "⚪ GRADE C NOISE",
    "🟢 ABSORPTION DIVERGENCE (WYCKOFF SPRING)": "🟢 ABSORPTION DIVERGENCE",
    "🟡 TEST SUPLAI (VOLUME KERING / LPS)": "🟡 TEST SUPLAI",
    "🚀 SOS IGNITION BREAKOUT": "🚀 SOS IGNITION",
    "🔴 EXIT LIQUIDITY TRAP (BULL TRAP)": "🔴 BULL TRAP",
    "🔴 BEARISH DIVERGENCE (HARGA TURUN / DISTRIBUSI)": "🔴 BEARISH DIVERGENCE",
    "PRE_PUMP_DETECTION": "👀 PRE-PUMP POTENTIAL",
}

# emoji -> (badge bg, badge fg, badge border)
SIGNAL_STYLES = {
    "⭐": ("#422006", "#fde68a", "#eab308"),  # Grade A golden spring
    "🟢": ("#052e16", "#bbf7d0", "#166534"),  # Grade B / absorption
    "⚪": ("#1e293b", "#cbd5e1", "#64748b"),  # Grade C muted noise
    "🟡": ("#422006", "#fde68a", "#ca8a04"),  # supply test / vol dry-up
    "🚀": ("#431407", "#fed7aa", "#f97316"),  # SOS ignition
    "🔴": ("#450a0a", "#fecaca", "#991b1b"),  # bull trap / bearish
    "👀": ("#172554", "#bfdbfe", "#3b82f6"),  # pre-pump potential
    "➖": ("#1e293b", "#94a3b8", "#334155"),  # normal / no signal
}

# emoji -> row background css
SIGNAL_ROW_BG = {
    "⭐": "background:rgba(234,179,8,0.12);border:1px solid #854d0e;",
    "🟢": "background:rgba(34,197,94,0.08);border:1px solid #14532d;",
    "⚪": "background:rgba(148,163,184,0.06);border:1px solid #475569;",
    "🟡": "background:rgba(234,179,8,0.08);border:1px solid #713f12;",
    "🚀": "background:rgba(34,197,94,0.08);border:1px solid #14532d;",
    "🔴": "background:rgba(220,38,38,0.08);border:1px solid #7f1d1d;",
    "👀": "background:rgba(59,130,246,0.08);border:1px solid #1e3a8a;",
    "➖": "background:rgba(148,163,184,0.04);border:1px solid #334155;",
}


def signal_label(raw_type):
    """Short UI label for a raw signal type from signals.json."""
    if not raw_type:
        return "➖ NORMAL"
    return SIGNAL_LABELS.get(raw_type) or raw_type.split(" (")[0]


def signal_emoji(label):
    """Emoji key used for badge styling; falls back to neutral."""
    emoji = label.split(" ", 1)[0] if " " in label else label
    return emoji if emoji in SIGNAL_STYLES else "➖"


def signal_badge(raw_type):
    """HTML badge for a signal; returns (badge_html, row_bg_css)."""
    label = signal_label(raw_type)
    emoji = signal_emoji(label)
    bg, fg, bd = SIGNAL_STYLES[emoji]
    tip = html.escape(raw_type or label)
    badge = (
        f"<span style='background:{bg};color:{fg};border:1px solid {bd};"
        f"border-radius:6px;padding:3px 8px;font-weight:800;"
        f"font-size:0.80rem;' title='{tip}'>{label}</span>"
    )
    row_bg = SIGNAL_ROW_BG[emoji] + "border-radius:10px;padding:8px 6px;margin-bottom:6px;"
    return badge, row_bg


CONFIG = load_config()
helius_keys = tuple(get_helius_keys(config=CONFIG))
try:
    dust_limit = float(CONFIG.get("dust_limit_usd", 5.0))
except Exception:
    dust_limit = 5.0

# ---------------------------------------------------------------------------
# Query param handling for delete
# ---------------------------------------------------------------------------
_q_del = st.query_params.get("del_ca", "").strip()
if _q_del:
    wl_tmp = load_watchlist()
    if _q_del in wl_tmp:
        sym = wl_tmp.get(_q_del, {}).get("symbol", _q_del[:8])
        ok = remove_from_watchlist(_q_del)
        try:
            st.query_params.pop("del_ca", None)
        except Exception:
            pass
        if not ok:
            err = get_last_push_error()
            st.error(f"⚠️ Gagal hapus {sym}: {err.get('msg')} ({err.get('status')}) — pending akan retry.")
            time.sleep(2)
        st.toast(f"Hapus {sym} dari watchlist")
        st.rerun()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🎯 Wallet Depth — Prepump Radar")
st.caption(
    "Fokus: watchlist → scan trending/degen → CVD → **4 Pilar Pre-Pump** "
    "(|CVD/Vol| < 3.0%, Buy TX ≥ 52%, Avg Sell > Buy, LPS kering). "
    "Cron 4 jam menyimpan chunk transaksi; evaluasi harian 07:00 WIB."
)

# ---------------------------------------------------------------------------
# 1. WATCHLIST (vertical list, sinyal column)
# ---------------------------------------------------------------------------
wl = load_watchlist()

st.markdown("### ⭐ Watchlist — 4 Pilar Pre-Pump")
st.caption(
    "Kolom: **Diamond** (top-100 sell/buy ≤10%), **Real/Dust**, "
    "**Top 100 Lock**, **|CVD/Vol|** (hijau tua bila < 3.0%), "
    "**Buy / Sell TX %** (≥ 52% buy = akumulasi cicil), **4 Pilar** "
    "(PASS / WATCH / FAIL / STEALTH DUMP). "
    "Tautan CVD hanya mengisi CA — fetch harus diklik di halaman CVD. "
    "Data di-refresh cron 4 jam + evaluasi harian 00:00 UTC."
)

if not wl:
    st.info("Watchlist kosong. Tambahkan manual di bawah atau dari hasil Scan Trending / Scan Degen.")
else:
    try:
        from signals import load_signals
        all_sigs = load_signals()
    except Exception:
        all_sigs = []
    # Header row — 4-pillar columns
    WL_WIDTHS = [1.0, 1.5, 0.7, 0.85, 0.95, 0.9, 0.85, 1.45, 0.85, 0.55]
    hdr = st.columns(WL_WIDTHS)
    for c, lab in zip(hdr, ["Token", "CA + Links", "Diamond", "Real/Dust",
                            "Top 100 Lock", "|CVD/Vol|", "Buy / Sell TX",
                            "4 Pilar", "Update", ""]):
        c.markdown(f"<span class='wl-head'>{lab}</span>",
                   unsafe_allow_html=True)
    st.divider()
    for ca, meta in wl.items():
        sym = meta.get("symbol", "?") or "?"
        src = meta.get("source", "manual")

        packed = get_signal_for_ca(ca, all_sigs)
        four = resolve_prepump_row(meta, packed.get("four"))
        wyck = resolve_wyckoff_row(meta, packed.get("wyckoff"))
        ts = four.get("ts") or wyck.get("ts")
        lock_pct = wyck.get("lock_pct")
        row_stale = bool(four.get("stale"))
        verdict = four.get("verdict") or ""
        phase = four.get("phase") or ""
        passed_n = four.get("passed")
        stealth = bool(four.get("stealth_dump"))
        absorption = four.get("absorption_pct")
        buy_tx_pct = four.get("buy_tx_pct")

        if stealth or verdict in ("FAIL", "STEALTH DUMP"):
            raw_type = "🔴 BEARISH DIVERGENCE (HARGA TURUN / DISTRIBUSI)"
        elif verdict == "PASS":
            raw_type = "🟢 ABSORPTION DIVERGENCE (WYCKOFF SPRING)"
        elif verdict == "WATCH":
            raw_type = "🟡 TEST SUPLAI (VOLUME KERING / LPS)"
        else:
            raw_type = wyck.get("raw_type") or ""
        badge, row_bg = signal_badge(raw_type)

        # Fetch detail tambahan
        det = get_watchlist_details(ca, meta)

        # Top 100 Lock — % Pure Accumulator di Top 100 Holders (dari sinyal,
        # fallback ke metadata watchlist.json)
        if lock_pct is None:
            lock_pct = meta.get("holder_lock_pct")
        if lock_pct is not None:
            try:
                lock_v = float(lock_pct)
                lock_color = ("#14532d" if lock_v >= 70
                              else ("#92400e" if lock_v >= 50 else "#7f1d1d"))
                lock_txt = (f"<span style='color:{lock_color};font-weight:700;'>"
                            f"{lock_v:.1f}% Pure Acc</span>")
            except (TypeError, ValueError):
                lock_txt = "<span class='watch-muted'>—</span>"
        else:
            lock_txt = "<span class='watch-muted'>—</span>"

        # |CVD / Volume| — Pilar 1
        if absorption is not None:
            try:
                abs_v = float(absorption)
                abs_ok = abs_v < 3.0
                abs_cls = "glowing-pass" if abs_ok else "glowing-fail"
                vc_txt = (f"<div class='{abs_cls}' style='text-align:center'>"
                          f"{abs_v:.2f}%</div>")
            except (TypeError, ValueError):
                vc_txt = "<span class='watch-muted'>—</span>"
        else:
            vc_txt = "<span class='watch-muted'>—</span>"

        # Buy TX % — Pilar 2
        if buy_tx_pct is not None:
            try:
                bt_v = float(buy_tx_pct)
                sell_v = 100.0 - bt_v
                bt_ok = bt_v >= 52.0
                bt_cls = "glowing-pass" if bt_ok else "glowing-fail"
                buy_txt = (f"<div class='{bt_cls}' style='text-align:center'>"
                           f"{bt_v:.0f}% / {sell_v:.0f}%</div>")
            except (TypeError, ValueError):
                buy_txt = "<span class='watch-muted'>—</span>"
        else:
            buy_txt = "<span class='watch-muted'>—</span>"

        if passed_n is not None:
            try:
                pn = int(passed_n)
                label = verdict or phase or "—"
                if stealth:
                    label = "STEALTH DUMP"
                skor_txt = (
                    f"<span style='font-weight:800'>{html.escape(str(label))}"
                    f"</span>"
                    f"<br><span class='watch-muted'>"
                    f"{pn}/4 pilar</span>"
                )
            except (TypeError, ValueError):
                skor_txt = "<span class='watch-muted'>—</span>"
        else:
            skor_txt = badge

        # 10 kolom compact — Wyckoff 15M
        cols = st.columns(WL_WIDTHS)
        cell_bg = row_bg + "text-align:center;"

        # Token
        sym_show = html.escape(sym.upper() if str(sym).isascii() else str(sym))
        src_show = html.escape(str(src))
        cols[0].markdown(
            f"<div class='watch-row' style='{row_bg}'><b>{sym_show}</b>"
            f"<br><span class='watch-muted'>{src_show}</span></div>",
            unsafe_allow_html=True)

        # CA + Links
        cols[1].markdown(
            f"<div class='watch-row' style='{row_bg}'>"
            f"<a href='https://solscan.io/token/{ca}' target='_blank' "
            f"style='font-size:0.80rem;color:#1d4ed8;text-decoration:none;"
            f"font-weight:600;'>{ca[:8]}…{ca[-4:]}</a><br>"
            f"<a href='https://gmgn.ai/sol/token/{ca}' target='_blank' "
            f"style='font-size:0.72rem;color:#b45309;text-decoration:none;'>"
            f"gmgn ↗</a> · "
            f"<a href='https://dexscreener.com/solana/{ca}' target='_blank' "
            f"style='font-size:0.72rem;color:#334155;text-decoration:none;'>"
            f"chart ↗</a> · "
            f"<a href='/CVD?ca={ca}' target='_self' "
            f"style='font-size:0.72rem;color:#14532d;text-decoration:none;"
            f"font-weight:600;'>CVD ↗</a>"
            f"</div>",
            unsafe_allow_html=True
        )

        # Diamond Hand (top 100 tidak jual >10%)
        diamond = det.get("diamond_pct")
        diamond_txt = (
            f"<span style='color:#14532d;font-weight:700;'>{diamond:.0f}%</span>"
            if diamond is not None
            else "<span class='watch-muted'>—</span>"
        )
        cols[2].markdown(
            f"<div class='watch-row' style='{cell_bg}'>{diamond_txt}"
            f"<br><span class='watch-muted'>diamond</span></div>",
            unsafe_allow_html=True)

        # Real vs Dust holders
        real = det.get("real_holders")
        dust = det.get("dust_holders")
        if real is not None and dust is not None:
            real_dust = (
                f"<span style='color:#14532d;font-weight:700;'>{real}</span>"
                f"/<span style='color:#7f1d1d;font-weight:700;'>{dust}</span>"
            )
        else:
            real_dust = "<span class='watch-muted'>—</span>"
        cols[3].markdown(
            f"<div class='watch-row' style='{cell_bg}'>{real_dust}"
            f"<br><span class='watch-muted'>real/dust</span></div>",
            unsafe_allow_html=True)

        # Top 100 Lock — Pure Accumulator supply lock
        cols[4].markdown(
            f"<div class='watch-row' style='{cell_bg}'>{lock_txt}"
            f"<br><span class='watch-muted'>top 100 lock</span></div>",
            unsafe_allow_html=True
        )

        # |CVD / Volume| Pilar 1
        cols[5].markdown(
            f"<div class='watch-row' style='{cell_bg}'>{vc_txt}"
            f"<br><span class='watch-muted'>"
            f"|CVD/Vol|</span></div>",
            unsafe_allow_html=True
        )

        # Buy / Sell TX % Pilar 2
        cols[6].markdown(
            f"<div class='watch-row' style='{cell_bg}'>{buy_txt}"
            f"<br><span class='watch-muted'>"
            f"buy / sell</span></div>",
            unsafe_allow_html=True
        )

        # 4-pilar verdict
        cols[7].markdown(
            f"<div class='watch-row' style='{row_bg}'>{skor_txt}</div>",
            unsafe_allow_html=True
        )

        # Update — flag rows whose last 15m eval is older than 45 minutes
        stale_html = ""
        if row_stale and ts:
            stale_html = ("<br><span style='font-size:0.60rem;color:#b45309;"
                          "font-weight:700;'>stale</span>")
        cols[8].markdown(
            f"<div class='watch-row' style='{cell_bg}'>"
            f"<span class='watch-muted'>"
            f"{_fmt_ts(ts)}</span>{stale_html}</div>",
            unsafe_allow_html=True)

        # Hapus
        with cols[9]:
            if st.button("🗑️", key=f"del_{ca}", help="Hapus dari watchlist", use_container_width=True):
                ok = remove_from_watchlist(ca)
                if ok:
                    st.toast(f"Hapus {sym} dari watchlist")
                else:
                    err = get_last_push_error()
                    st.error(f"⚠️ Gagal hapus {sym}: {err.get('msg')} ({err.get('status')})")
                time.sleep(0.35)
                st.rerun()

    st.caption(
        f"Total {len(wl)} token dipantau. Lock / Vol / CVD / 4 pilar "
        "dari snapshot cron. Tautan CVD hanya mengisi CA — fetch "
        "manual di halaman CVD. Telegram 4 pilar hanya jika keempat "
        "pilar transaksi harian komplit."
    )

# ---------------------------------------------------------------------------
# 2. TAMBAH KOLEKSI MANUAL KE WATCHLIST
# ---------------------------------------------------------------------------
st.markdown("### ➕ Tambah Koleksi Manual ke Watchlist")
with st.form("manual_add", clear_on_submit=True):
    c1, c2 = st.columns([3, 1])
    ca_in = c1.text_input("Contract Address (CA)", placeholder="Solana CA, contoh: AkchGAUdXX...").strip()
    src_in = c2.selectbox("Sumber", ["manual", "trending", "degen"], index=0)
    submitted = st.form_submit_button("⭐ Tambahkan ke Watchlist", use_container_width=True, type="primary")
    if submitted:
        if not ca_in:
            st.warning("CA kosong.")
        else:
            sym = "?"
            try:
                from core import get_market
                m = get_market(ca_in)
                sym = (m or {}).get("symbol", "?") or "?"
            except Exception:
                pass
            ok = add_to_watchlist(ca_in, symbol=sym, source=src_in)
            if ok:
                st.success(f"Berhasil tambah {sym} ({ca_in[:8]}…) ke watchlist.")
                time.sleep(1)
                st.rerun()
            else:
                err = get_last_push_error()
                st.error(f"Gagal push ke GitHub: {err.get('msg')} ({err.get('status')}) — tersimpan lokal, akan retry.")
                time.sleep(2)
                st.rerun()

# ---------------------------------------------------------------------------
# 3. SCAN TRENDING NOW
# ---------------------------------------------------------------------------
st.markdown("### 🔥 Scan Trending Now (GMGN)")
st.caption("Ambil trending dari GMGN, sudah disaring (Top10, liq/MC, rug, volume/MC) + filter bundler/insider. Hanya tombol **⭐ Watchlist** — tidak ada Analyze di halaman ini. CVD ada di halaman terpisah.")

# Import trending_ui functions lazily
try:
    from trending_ui import run_screen
except Exception as e:
    st.error(f"Gagal load trending_ui: {e}")
    run_screen = None

if run_screen:
    col_scan, col_clear = st.columns([1, 1])
    scan_trending = col_scan.button("🔥 Scan Trending Now", type="primary", use_container_width=True, key="scan_trending_btn")
    clear_trending = col_clear.button("Bersihkan hasil Trending", use_container_width=True, key="clear_trending_btn")
    if clear_trending:
        for k in ["screener_rows", "screener_rows_err"]:
            st.session_state.pop(k, None)
        st.rerun()

    if scan_trending or "screener_rows" in st.session_state:
        with st.spinner("Fetching trending..."):
            rows, err = run_screen(force=scan_trending, dust_limit_usd=float(dust_limit), helius_keys=helius_keys)
        if err:
            st.error(f"Gagal fetch trending: {err}")
        if not rows and not err:
            st.warning("GMGN kosong / diblokir Cloudflare — coba lagi 1 menit.")
        if rows:
            # Render minimal table with only Watchlist button
            # Use trending_ui's CAPTION? We'll render simplified header
            st.markdown(f"**{len(rows)} token** — urut Fit struktural")
            # Table header
            widths = [0.7, 1.4, 1.0, 0.9, 0.7, 0.9, 0.8, 1.1, 0.9]
            hdr2 = st.columns(widths)
            for c, lab in zip(hdr2, ["Fit", "Token", "MC", "Liq", "T10", "Holders", "24h", "Risk", ""]):
                c.markdown(f"**{lab}**")
            # Load watchlist for badge
            wl_now = load_watchlist()
            from gmgn_screener import fit_color
            for r in rows:
                ca = r.get("ca")
                fit = r.get("fit", 0)
                high_risk = r.get("high_risk")
                col = fit_color(fit, high_risk)
                cc = st.columns(widths)
                cc[0].markdown(f"<span style='color:{col};font-weight:800'>{fit}</span><br><span style='font-size:0.6rem;color:{col}'>{r.get('grade','')}</span>", unsafe_allow_html=True)
                gmgn_link = f"<a href='https://gmgn.ai/sol/token/{ca}' target='_blank' style='font-size:0.55rem;color:#f59e0b;text-decoration:none'>↗GMGN</a>"
                dex_link = f"<a href='https://dexscreener.com/solana/{ca}' target='_blank' style='font-size:0.55rem;color:#3b82f6;text-decoration:none;margin-left:3px'>↗DEX</a>"
                cc[1].markdown(f"**{r.get('symbol','?')}**<br><span style='font-size:0.62rem;opacity:0.6'>{r.get('name','')[:16]}</span><br><span style='font-size:0.55rem'>{gmgn_link} {dex_link}</span>", unsafe_allow_html=True)
                cc[2].write(f"${r.get('mc',0):,.0f}")
                cc[3].write(f"{r.get('liq_pct',0)}%")
                cc[4].write(f"{r.get('t10_pct',0)}%")
                cc[5].write(f"{r.get('holders',0):,}")
                chg = r.get("chg24",0)
                cc[6].markdown(f"<span style='color:{'#14532d' if chg>=0 else '#7f1d1d'}'>{chg:+.0f}%</span>", unsafe_allow_html=True)
                # Risk bits
                bits = []
                for lab, val in (("bndl", r.get("bundler_rate",0)), ("insd", r.get("insider_ratio",0))):
                    if val and val>0:
                        c2 = "#14532d" if val<0.15 else "#7f1d1d"
                        bits.append(f"<span style='color:{c2}'>{lab} {val*100:.0f}%</span>")
                cc[7].markdown(" · ".join(bits) if bits else "—", unsafe_allow_html=True)
                with cc[8]:
                    if ca in wl_now:
                        st.caption("⭐ watched")
                    else:
                        if st.button("⭐ Watch", key=f"tr_wl_{ca}", use_container_width=True):
                            ok = add_to_watchlist(ca, symbol=r.get("symbol","?"), source="trending", down_ath=r.get("down_ath"), avg_cost=r.get("avg_cost"))
                            if ok:
                                st.toast(f"Tambah {r.get('symbol','?')}")
                            else:
                                err2 = get_last_push_error()
                                st.error(f"Gagal push: {err2.get('msg')}")
                            st.rerun()
            st.caption("Fit: Top10 30 + liq/MC 30 + rug 25 + vol/MC 15. Diblokir Cloudflare sewaktu-waktu — coba lagi.")

# ---------------------------------------------------------------------------
# 4. SCAN DEGEN NOW (HRHR)
# ---------------------------------------------------------------------------
st.markdown("### ⚡ Scan Degen Now (High Risk High Reward)")
st.caption("Sama filter trending tapi untuk token HRHR — high risk high reward. Hanya **⭐ Watchlist**. DYOR!")

try:
    from trending_ui import run_screen_hrhr
except Exception:
    run_screen_hrhr = None

if run_screen_hrhr:
    col_scan2, col_clear2 = st.columns([1,1])
    scan_degen = col_scan2.button("⚡ Scan Degen Now", type="primary", use_container_width=True, key="scan_degen_btn")
    clear_degen = col_clear2.button("Bersihkan hasil Degen", use_container_width=True, key="clear_degen_btn")
    if clear_degen:
        for k in ["screener_hrhr_rows", "screener_hrhr_rows_err"]:
            st.session_state.pop(k, None)
        st.rerun()
    if scan_degen or "screener_hrhr_rows" in st.session_state:
        with st.spinner("Fetching degen..."):
            rows2, err2 = run_screen_hrhr(force=scan_degen, dust_limit_usd=float(dust_limit), helius_keys=helius_keys)
        if err2:
            st.error(f"Gagal fetch degen: {err2}")
        if not rows2 and not err2:
            st.warning("GMGN degen kosong — coba lagi.")
        if rows2:
            # Enrich with H4 patterns if available (optional)
            try:
                from trending_ui import enrich_hrhr_with_patterns
                rows2 = enrich_hrhr_with_patterns(rows2)
            except Exception:
                pass
            st.markdown(f"**{len(rows2)} token degen**")
            widths = [0.7, 1.4, 1.0, 0.9, 0.7, 0.9, 0.8, 1.1, 0.9]
            hdr3 = st.columns(widths)
            for c, lab in zip(hdr3, ["Fit", "Token", "MC", "Liq", "T10", "Holders", "24h", "Risk", ""]):
                c.markdown(f"**{lab}**")
            wl_now2 = load_watchlist()
            from gmgn_screener import fit_color as fit_color2
            for r in rows2:
                ca = r.get("ca")
                fit = r.get("fit", 0)
                high_risk = r.get("high_risk")
                col = fit_color2(fit, high_risk)
                cc = st.columns(widths)
                cc[0].markdown(f"<span style='color:{col};font-weight:800'>{fit}</span><br><span style='font-size:0.6rem;color:{col}'>{r.get('grade','')}</span>", unsafe_allow_html=True)
                gmgn_link = f"<a href='https://gmgn.ai/sol/token/{ca}' target='_blank' style='font-size:0.55rem;color:#f59e0b;text-decoration:none'>↗GMGN</a>"
                dex_link = f"<a href='https://dexscreener.com/solana/{ca}' target='_blank' style='font-size:0.55rem;color:#3b82f6;text-decoration:none;margin-left:3px'>↗DEX</a>"
                # Show candle patterns if exist
                cp = r.get("candle_patterns", {})
                cp_txt = ""
                if cp:
                    from cvd import PATTERN_EMOJI
                    cp_txt = " ".join(f"{PATTERN_EMOJI.get(k,'🕯️')} {k} {v}x" for k,v in cp.items())
                    cp_txt = f"<br><span style='font-size:0.6rem;color:#14532d'>{cp_txt}</span>"
                cc[1].markdown(f"**{r.get('symbol','?')}**<br><span style='font-size:0.62rem;opacity:0.6'>{r.get('name','')[:16]}</span><br><span style='font-size:0.55rem'>{gmgn_link} {dex_link}</span>{cp_txt}", unsafe_allow_html=True)
                cc[2].write(f"${r.get('mc',0):,.0f}")
                cc[3].write(f"{r.get('liq_pct',0)}%")
                cc[4].write(f"{r.get('t10_pct',0)}%")
                cc[5].write(f"{r.get('holders',0):,}")
                chg = r.get("chg24",0)
                cc[6].markdown(f"<span style='color:{'#14532d' if chg>=0 else '#7f1d1d'}'>{chg:+.0f}%</span>", unsafe_allow_html=True)
                bits = []
                for lab, val in (("bndl", r.get("bundler_rate",0)), ("insd", r.get("insider_ratio",0))):
                    if val and val>0:
                        c2 = "#14532d" if val<0.15 else "#7f1d1d"
                        bits.append(f"<span style='color:{c2}'>{lab} {val*100:.0f}%</span>")
                cc[7].markdown(" · ".join(bits) if bits else "—", unsafe_allow_html=True)
                with cc[8]:
                    if ca in wl_now2:
                        st.caption("⭐ watched")
                    else:
                        if st.button("⭐ Watch", key=f"de_wl_{ca}", use_container_width=True):
                            ok = add_to_watchlist(ca, symbol=r.get("symbol","?"), source="hrhr", down_ath=r.get("down_ath"), avg_cost=r.get("avg_cost"))
                            if ok:
                                st.toast(f"Tambah {r.get('symbol','?')}")
                            else:
                                err3 = get_last_push_error()
                                st.error(f"Gagal push: {err3.get('msg')}")
                            st.rerun()
            st.caption("⚠️ Degen = BERISIKO TINGGI. Selalu cek CVD sebelum entry.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    "Cron 4 jam (`cvd-4h-daily.yml` → `scripts/update_cvd.py`) menyimpan "
    "chunk transaksi ke `data/cvd_4h_chunks/`. Evaluasi harian 00:00 UTC "
    "mengagregasi 6 potongan tanpa full-fetch 24 jam. Ambang: "
    "|CVD/Vol| < 3.0% · Buy TX ≥ 52% · Avg Sell > Avg Buy · LPS −40%. "
    "Halaman CVD fetch hanya setelah tombol diklik. Telegram 4 pilar "
    "hanya jika keempat pilar hari UTC penuh sudah lolos."
)

