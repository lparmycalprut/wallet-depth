# -*- coding: utf-8 -*-
"""
Wallet Depth — Prepump Radar (minimalist reset 2026-08-07,
update 2026-08-11: Wyckoff 15M cron detector)

Kept functions only:
  - watchlist (vertical list + sinyal Wyckoff 15M pre-pump)
  - scan trending / scan degen (with all filters, only Watchlist button)
  - CVD deep analysis (separate page)
  - signals.json as backend (written by the 15-minute GitHub Actions cron)

Removed: cards, analyze on main page, compare/history/screener/cto/lp/accum/
  memecoin/prepump-checker pages, breakout_guard, focus, share_card, daily
  07:00 WIB cron, M15 swap-store flag, 7-checks scoring, AvgCost column.

Sinyal watchlist reads the latest Wyckoff 15M entry per CA from signals.json
(scripts/prepump_wyckoff_cron.py format), not the old daily CVD model.
"""
import html
import time
from datetime import datetime, timezone, timedelta

import streamlit as st

from core import load_config, get_helius_keys
from watchlist import load_watchlist, add_to_watchlist, remove_from_watchlist, get_last_push_error

st.set_page_config(
    page_title="Wallet Depth — Prepump",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ====================== GLOBAL USER-FRIENDLY STYLING (Light + Dark aware) ======================
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
        padding: 4px 0;
        line-height: 1.35;
    }
    .section-header {
        font-size: 1.35rem;
        font-weight: 700;
        margin: 1.25rem 0 0.4rem 0;
    }

    /* ========== LIGHT MODE ========== */
    @media (prefers-color-scheme: light) {
        .section-header { color: #0f172a; }
        .stMarkdown, .stCaption { color: #334155; }
        .watch-row { color: #1e2937; }
    }

    /* ========== DARK MODE ========== */
    @media (prefers-color-scheme: dark) {
        .section-header { color: #e0e7ff; }
        .stMarkdown, .stCaption { color: #cbd5e1; }
        .watch-row { color: #e2e8f0; }
        .stButton button {
            background-color: #1e2937;
            color: #e0e7ff;
            border: 1px solid #475569;
        }
    }

    .stMarkdown, .stCaption {
        font-size: 0.95rem;
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
    """Return the latest Wyckoff 15M signal entry for a CA (or None).

    New detector format (scripts/prepump_wyckoff_cron.py)::

        {"ts": ..., "ca": ..., "symbol": ..., "type": "🟢 ABSORPTION ...",
         "score": 95.0, "price_usd": ..., "volume_sol": 12.3,
         "cvd_sol": -1.96, "holder_lock_pct": 100.0, "detail": {...}}

    Legacy rows (cvd_daily, cron 6h distribution/accumulation, ...) are
    ignored — only entries carrying the new Wyckoff keys are considered.
    """
    for item in reversed(sigs or []):
        if (item.get("ca") == ca
                and "score" in item and "holder_lock_pct" in item):
            return item
    return None

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
    "🟢 ABSORPTION DIVERGENCE (WYCKOFF SPRING)": "🟢 ABSORPTION DIVERGENCE",
    "🟡 TEST SUPLAI (VOLUME KERING / LPS)": "🟡 TEST SUPLAI",
    "🚀 SOS IGNITION BREAKOUT": "🚀 SOS IGNITION",
    "🔴 EXIT LIQUIDITY TRAP (BULL TRAP)": "🔴 BULL TRAP",
    "PRE_PUMP_DETECTION": "👀 PRE-PUMP POTENTIAL",
}

# emoji -> (badge bg, badge fg, badge border)
SIGNAL_STYLES = {
    "🟢": ("#052e16", "#86efac", "#16a34a"),  # absorption divergence
    "🟡": ("#422006", "#fde68a", "#ca8a04"),  # supply test / vol dry-up
    "🚀": ("#431407", "#fed7aa", "#f97316"),  # SOS ignition
    "🔴": ("#450a0a", "#fecaca", "#dc2626"),  # bull trap
    "👀": ("#172554", "#bfdbfe", "#3b82f6"),  # pre-pump potential
    "➖": ("#1e293b", "#94a3b8", "#334155"),  # normal / no signal
}

# emoji -> row background css
SIGNAL_ROW_BG = {
    "🟢": "background:rgba(34,197,94,0.08);border:1px solid #14532d;",
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
st.caption("Fokus: watchlist → scan trending/degen → CVD → sinyal **Wyckoff 15M** (detektor berjalan otomatis tiap 15 menit via GitHub Actions, sinyal terbaru di `signals.json`) + notifikasi Telegram/Discord saat trigger.")

# ---------------------------------------------------------------------------
# 1. WATCHLIST (vertical list, sinyal column)
# ---------------------------------------------------------------------------
wl = load_watchlist()

st.markdown("### ⭐ Watchlist — Wyckoff 15M Pre-Pump Detector")
st.caption("""List menurun. Kolom: **Diamond** (% top-100 holder yang tidak jual >10%), **Real/Dust** (holder >$5 vs ≤$5), **Top 100 Lock** (% **Pure Accumulator** di Top 100 Holders — supply terkunci, dari sinyal Wyckoff terbaru di `signals.json`), **15m Vol / CVD** (volume & CVD SOL 15 menit terakhir dari detektor 15 menit).
Kolom **Sinyal** = label Wyckoff 15m terbaru: 🟢 **ABSORPTION DIVERGENCE** (candle naik tapi CVD negatif — sell terserap / spring), 🟡 **TEST SUPLAI** (volume kering / LPS — suplai sedang diuji), 🚀 **SOS IGNITION** (lonjakan volume + CVD positif = awal mark-up), 🔴 **BULL TRAP** (harga naik tapi CVD negatif & lock lemah), atau ➖ **NORMAL**. Kolom **Skor** = skor pre-pump dinamis **0–100** (lock 65% + kondisi sinyal).""")

if not wl:
    st.info("Watchlist kosong. Tambahkan manual di bawah atau dari hasil Scan Trending / Scan Degen.")
else:
    try:
        from signals import load_signals
        all_sigs = load_signals()
    except Exception:
        all_sigs = []
    # Header row — Wyckoff 15M columns (compact + eye friendly)
    WL_WIDTHS = [1.0, 1.5, 0.7, 0.85, 1.0, 1.05, 1.35, 0.65, 0.85, 0.55]
    hdr = st.columns(WL_WIDTHS)
    for c, lab in zip(hdr, ["Token", "CA + Links", "Diamond", "Real/Dust",
                            "Top 100 Lock", "15m Vol / CVD", "Sinyal", "Skor",
                            "Update", ""]):
        c.markdown(f"<b style='color:#000000'>{lab}</b>", unsafe_allow_html=True)
    st.divider()
    for ca, meta in wl.items():
        sym = meta.get("symbol", "?") or "?"
        src = meta.get("source", "manual")

        # Sinyal Wyckoff 15m terbaru dari signals.json
        sig = get_signal_for_ca(ca, all_sigs)
        if sig:
            raw_type = str(sig.get("type") or "")
            score = sig.get("score")
            ts = sig.get("ts")
            vol_sol = sig.get("volume_sol")
            cvd_sol = sig.get("cvd_sol")
            lock_pct = sig.get("holder_lock_pct")
        else:
            raw_type, score, ts = "", None, None
            vol_sol = cvd_sol = lock_pct = None

        # Badge config — Wyckoff 15M
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
                lock_color = ("#16a34a" if lock_v >= 70
                              else ("#ca8a04" if lock_v >= 50 else "#dc2626"))
                lock_txt = (f"<span style='color:{lock_color};font-weight:700;'>"
                            f"{lock_v:.1f}% Pure Acc</span>")
            except (TypeError, ValueError):
                lock_txt = "<span style='color:#000000'>—</span>"
        else:
            lock_txt = "<span style='color:#000000'>—</span>"

        # 15m Vol / CVD — volume & CVD SOL 15 menit terakhir
        if vol_sol is not None and cvd_sol is not None:
            try:
                vol_v = float(vol_sol)
                cvd_v = float(cvd_sol)
                cvd_color = "#16a34a" if cvd_v >= 0 else "#dc2626"
                vc_txt = (f"<span style='color:#000000;font-weight:700;'>"
                          f"{vol_v:.2f} SOL</span> | "
                          f"<span style='color:{cvd_color};font-weight:700;'>"
                          f"{cvd_v:+.2f} SOL</span>")
            except (TypeError, ValueError):
                vc_txt = "<span style='color:#000000'>—</span>"
        else:
            vc_txt = "<span style='color:#000000'>—</span>"

        # Skor pre-pump dinamis 0-100
        if score is not None:
            try:
                sc_v = float(score)
                sc_color = ("#16a34a" if sc_v >= 70
                            else ("#ca8a04" if sc_v >= 50 else "#94a3b8"))
                skor_txt = (f"<span style='font-weight:800;color:{sc_color};'>"
                            f"{sc_v:.0f}</span>"
                            f"<span style='color:#000000;font-size:0.69rem;'>"
                            f" / 100</span>")
            except (TypeError, ValueError):
                skor_txt = "<span style='color:#000000'>—</span>"
        else:
            skor_txt = "<span style='color:#000000'>—</span>"

        # 10 kolom compact — Wyckoff 15M
        cols = st.columns(WL_WIDTHS)
        cell_bg = row_bg + "text-align:center;"

        # Token
        cols[0].markdown(f"<div class='watch-row' style='{row_bg}'><b style='color:#000000'>{sym}</b><br><span style='font-size:0.65rem;color:#000000'>{src}</span></div>", unsafe_allow_html=True)

        # CA + Links
        cols[1].markdown(
            f"<div class='watch-row' style='{row_bg}'>"
            f"<a href='https://solscan.io/token/{ca}' target='_blank' style='font-size:0.74rem;color:#0284c7;text-decoration:none;font-weight:600;'>{ca[:8]}…{ca[-4:]}</a><br>"
            f"<a href='https://gmgn.ai/sol/token/{ca}' target='_blank' style='font-size:0.65rem;color:#d97706;text-decoration:none;'>gmgn ↗</a> · "
            f"<a href='https://dexscreener.com/solana/{ca}' target='_blank' style='font-size:0.65rem;color:#000000;text-decoration:none;'>chart ↗</a> · "
            f"<a href='/CVD?ca={ca}' target='_self' style='font-size:0.65rem;color:#000000;text-decoration:none;'>CVD ↗</a>"
            f"</div>",
            unsafe_allow_html=True
        )

        # Diamond Hand (top 100 tidak jual >10%)
        diamond = det.get("diamond_pct")
        diamond_txt = f"<span style='color:#16a34a;font-weight:700;'>{diamond:.0f}%</span>" if diamond is not None else "<span style='color:#000000'>—</span>"
        cols[2].markdown(f"<div class='watch-row' style='{cell_bg}'>{diamond_txt}<br><span style='font-size:0.60rem;color:#000000'>diamond</span></div>", unsafe_allow_html=True)

        # Real vs Dust holders
        real = det.get("real_holders")
        dust = det.get("dust_holders")
        if real is not None and dust is not None:
            real_dust = f"<span style='color:#16a34a;font-weight:700;'>{real}</span>/<span style='color:#dc2626;font-weight:700;'>{dust}</span>"
        else:
            real_dust = "<span style='color:#000000'>—</span>"
        cols[3].markdown(f"<div class='watch-row' style='{cell_bg}'>{real_dust}<br><span style='font-size:0.60rem;color:#000000'>real/dust</span></div>", unsafe_allow_html=True)

        # Top 100 Lock — Pure Accumulator supply lock
        cols[4].markdown(
            f"<div class='watch-row' style='{cell_bg}'>{lock_txt}"
            f"<br><span style='font-size:0.60rem;color:#000000'>top 100 lock</span></div>",
            unsafe_allow_html=True
        )

        # 15m Vol / CVD
        cols[5].markdown(
            f"<div class='watch-row' style='{cell_bg}'>{vc_txt}"
            f"<br><span style='font-size:0.60rem;color:#000000'>15m vol / CVD</span></div>",
            unsafe_allow_html=True
        )

        # Sinyal Wyckoff 15m
        cols[6].markdown(f"<div class='watch-row' style='{row_bg}'>{badge}</div>", unsafe_allow_html=True)

        # Skor pre-pump
        cols[7].markdown(
            f"<div class='watch-row' style='{cell_bg}'>{skor_txt}"
            f"<br><span style='font-size:0.60rem;color:#000000'>skor / 100</span></div>",
            unsafe_allow_html=True
        )

        # Update
        cols[8].markdown(f"<div class='watch-row' style='{cell_bg}'><span style='font-size:0.69rem;color:#000000'>{_fmt_ts(ts)}</span></div>", unsafe_allow_html=True)

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

    st.caption(f"Total {len(wl)} token dipantau. Sinyal & skor Wyckoff 15M di-refresh otomatis tiap 15 menit dari `signals.json`.")

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
                cc[6].markdown(f"<span style='color:{'#22c55e' if chg>=0 else '#ef4444'}'>{chg:+.0f}%</span>", unsafe_allow_html=True)
                # Risk bits
                bits = []
                for lab, val in (("bndl", r.get("bundler_rate",0)), ("insd", r.get("insider_ratio",0))):
                    if val and val>0:
                        c2 = "#22c55e" if val<0.15 else "#ef4444"
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
                    cp_txt = f"<br><span style='font-size:0.6rem;color:#22c55e'>{cp_txt}</span>"
                cc[1].markdown(f"**{r.get('symbol','?')}**<br><span style='font-size:0.62rem;opacity:0.6'>{r.get('name','')[:16]}</span><br><span style='font-size:0.55rem'>{gmgn_link} {dex_link}</span>{cp_txt}", unsafe_allow_html=True)
                cc[2].write(f"${r.get('mc',0):,.0f}")
                cc[3].write(f"{r.get('liq_pct',0)}%")
                cc[4].write(f"{r.get('t10_pct',0)}%")
                cc[5].write(f"{r.get('holders',0):,}")
                chg = r.get("chg24",0)
                cc[6].markdown(f"<span style='color:{'#22c55e' if chg>=0 else '#ef4444'}'>{chg:+.0f}%</span>", unsafe_allow_html=True)
                bits = []
                for lab, val in (("bndl", r.get("bundler_rate",0)), ("insd", r.get("insider_ratio",0))):
                    if val and val>0:
                        c2 = "#22c55e" if val<0.15 else "#ef4444"
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
st.caption("Detektor otomatis berjalan tiap 15 menit via GitHub Actions (`prepump-wyckoff-cron.yml` → `scripts/prepump_wyckoff_cron.py`): evaluasi Wyckoff 15m (Top 100 Pure Accumulator Lock, Absorption Divergence, Vol Dry-Up / Test Suplai, SOS Ignition, Bull Trap) → skor pre-pump 0-100 → sinyal terbaru di `signals.json` → notifikasi Telegram/Discord saat trigger. Data CVD 72 jam tetap tersedia di halaman 📊 CVD.")

