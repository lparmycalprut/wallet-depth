# -*- coding: utf-8 -*-
"""
Wallet Depth — Prepump Radar (minimalist reset 2026-08-07, update 2026-08-07 07:00 WIB)

Kept functions only:
  - watchlist (vertical list + sinyal CVD GMGN harian)
  - scan trending / scan degen (with all filters, only Watchlist button)
  - CVD deep analysis (separate page, old prepump_detector tetap untuk deep dive)
  - history/signals as data backend (json)
  - telegram via daily cron at 07:00 WIB (00:00 UTC, GMGN candle flip)

Removed: cards, analyze on main page, compare/history/screener/cto/lp/accum/memecoin/prepump-checker pages,
  breakout_guard, focus, share_card, etc.

Sinyal watchlist now uses the daily GMGN extension-compatible CVD model,
not the old 4-pillar score.
"""
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
    """Return the latest daily GMGN CVD status for a CA."""
    for item in reversed(sigs or []):
        if item.get("ca") == ca and item.get("type") == "cvd_daily":
            detail = item.get("detail") or {}
            status = item.get("status") or detail.get("status") or "NORMAL"
            dry = status.startswith("KERING")
            return ("priority" if dry else "daily", detail.get("cvd_ratio_pct", 0),
                    item.get("ts"), status)
    return None


def live_evaluate(ca: str, symbol: str):
    """No intra-day fallback: signals are produced by the daily cron only."""
    return "unknown", 0, None

def fetch_gmgn_avg_cost(ca: str, timeout: int = 18) -> float | None:
    """Fetch average holder cost (%) from GMGN token_holders endpoint (cost=20)."""
    try:
        from curl_cffi import requests as cr
    except ImportError:
        return None

    import uuid
    device_id = str(uuid.uuid4())
    fp_did = uuid.uuid4().hex
    build_tag = "20260807-3117-f1d79dd"

    url = (
        f"https://gmgn.ai/vas/api/v1/token_holders/sol/{ca}"
        f"?device_id={device_id}&fp_did={fp_did}"
        f"&client_id=gmgn_web_{build_tag}&from_app=gmgn&app_ver={build_tag}"
        f"&tz_name=Asia%2FJakarta&tz_offset=25200&app_lang=en-US&os=web&worker=0"
        f"&limit=100&cost=20&orderby=amount_percentage&direction=desc"
    )

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,id;q=0.8",
        "referer": f"https://gmgn.ai/sol/token/{ca}",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    }

    try:
        r = cr.get(url, impersonate="chrome", headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json() or {}
        holders = (data.get("data") or {}).get("holders") or []

        costs = []
        for h in holders:
            cost_val = h.get("cost") or h.get("avg_cost") or h.get("cost_usd")
            if cost_val is not None:
                try:
                    c = float(cost_val)
                    if -200 < c < 200:
                        costs.append(c)
                except (TypeError, ValueError):
                    continue

        if costs:
            avg = sum(costs) / len(costs)
            return round(avg, 1)
        return None
    except Exception:
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


@st.cache_data(ttl=600, show_spinner=False)
def watchlist_m15_flag(ca: str) -> dict:
    """M15 activity flag: sudah ada candle 15 menit dengan tx >500 DAN
    volume >500 SOL dalam satu candle? Data dari store 72h; kalau store
    kosong, coba fetch GMGN cepat (best effort)."""
    try:
        from cvd import m15_activity_flag, get_recent_swaps
        swaps = get_recent_swaps(ca, hours=72)
        if not swaps:
            # best-effort live fetch (bounded) when the store is empty
            try:
                from cvd import fetch_swaps
                cutoff = int(time.time()) - 72 * 3600
                swaps, _sig, _ts, _hit = fetch_swaps(
                    "", "", ca, stop_ts=cutoff, max_pages=10, sleep=0.05,
                    use_gmgn=True)
            except Exception:
                swaps = []
        return m15_activity_flag(swaps)
    except Exception:
        return {}


def get_watchlist_details(ca: str, meta: dict) -> dict:
    """Ambil detail tambahan untuk watchlist (diamond, real/dust, avg_cost)."""
    details = {
        "diamond_pct": meta.get("diamond_pct"),
        "real_holders": meta.get("real_holders"),
        "dust_holders": meta.get("dust_holders"),
        "avg_cost": meta.get("avg_cost"),
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

    # Jika avg_cost belum ada di watchlist.json → fetch live dari GMGN
    if details["avg_cost"] is None:
        live_avg = fetch_gmgn_avg_cost(ca)
        if live_avg is not None:
            details["avg_cost"] = live_avg

    # Normalisasi angka
    if details["diamond_pct"] is not None:
        try:
            details["diamond_pct"] = round(float(details["diamond_pct"]), 1)
        except Exception:
            details["diamond_pct"] = None

    if details["avg_cost"] is not None:
        try:
            details["avg_cost"] = round(float(details["avg_cost"]), 1)
        except Exception:
            details["avg_cost"] = None

    if details["down_ath"] is not None:
        try:
            details["down_ath"] = round(float(details["down_ath"]), 1)
        except Exception:
            details["down_ath"] = None

    return details

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
st.caption("Fokus: watchlist → scan trending/degen → CVD → sinyal CVD harian 07:00 WIB (00:00 UTC, perhitungan mengikuti ekstensi GMGN) + notifikasi Telegram sehari sekali. Token KERING otomatis masuk prioritas scan 15 menit.")

# ---------------------------------------------------------------------------
# 1. WATCHLIST (vertical list, sinyal column)
# ---------------------------------------------------------------------------
wl = load_watchlist()

st.markdown("### ⭐ Watchlist — CVD GMGN Harian (update 07:00 WIB)")
st.caption("""List menurun. Kolom: **Diamond** (% top-100 holder yang tidak jual >10%), **Real/Dust** (holder >$5 vs ≤$5), **M15** (sudah ada candle 15 menit dengan **tx >500 DAN volume >500 SOL** dalam satu candle — dari store swap 72 jam), **AvgCost** (perubahan harga vs avg holder cost dari GMGN — di-fetch live via token_holders API jika belum tersimpan).
Kolom **Sinyal** mengikuti rekap ekstensi GMGN. **KERING** berarti volume turun ≥40% dengan CVD relatif datar dan token masuk prioritas scan transaksi 15 menit.""")

if not wl:
    st.info("Watchlist kosong. Tambahkan manual di bawah atau dari hasil Scan Trending / Scan Degen.")
else:
    try:
        from signals import load_signals
        all_sigs = load_signals()
    except Exception:
        all_sigs = []
    # Header row — now with extra detail columns (compact + eye friendly) — ATR removed
    hdr = st.columns([1.2, 1.6, 0.9, 1.05, 0.8, 0.9, 1.05, 0.75, 0.95, 0.6])
    for c, lab in zip(hdr, ["Token", "CA + Links", "Diamond", "Real/Dust", "M15", "AvgCost", "Sinyal", "Skor", "Update", ""]):
        c.markdown(f"<b style='color:#000000'>{lab}</b>", unsafe_allow_html=True)
    st.divider()
    for ca, meta in wl.items():
        sym = meta.get("symbol", "?") or "?"
        src = meta.get("source", "manual")
        # Determine sinyal
        sig = get_signal_for_ca(ca, all_sigs)
        if sig:
            tier, score, ts, detail = sig
        else:
            # fallback live
            tier, score, ts = live_evaluate(ca, sym)
            detail = ""
            if tier == "unknown":
                tier = "neutral"
                score = 0
                ts = None

        # Badge config — daily GMGN CVD
        if tier == "priority":
            badge = f"<span style='background:#7c2d12;color:#fed7aa;border:1px solid #f97316;border-radius:6px;padding:3px 8px;font-weight:800;font-size:0.82rem;'>🔥 PRIORITAS · KERING</span>"
            row_bg = "background:rgba(34,197,94,0.08);border:1px solid #14532d;border-radius:10px;padding:8px 6px;margin-bottom:6px;"
        elif tier == "unknown":
            badge = f"<span style='background:#1e293b;color:#94a3b8;border:1px solid #334155;border-radius:6px;padding:3px 8px;font-weight:700;font-size:0.82rem;'>❓ UNKNOWN</span>"
            row_bg = "background:rgba(148,163,184,0.04);border:1px solid #334155;border-radius:10px;padding:8px 6px;margin-bottom:6px;"
        else:
            label = detail[:28] if detail else "➖ NORMAL"
            badge = f"<span style='background:#1e293b;color:#94a3b8;border:1px solid #334155;border-radius:6px;padding:3px 8px;font-weight:700;font-size:0.82rem;'>{label}</span>"
            row_bg = "background:rgba(148,163,184,0.04);border:1px solid #334155;border-radius:10px;padding:8px 6px;margin-bottom:6px;"

        # Fetch detail tambahan
        det = get_watchlist_details(ca, meta)

        # M15 flag: sudah ada candle 15m dengan tx>500 DAN vol>500 SOL?
        m15 = watchlist_m15_flag(ca)
        if m15:
            m15_hit = bool(m15.get("hit"))
            m15_txt = ("⚡ YA" if m15_hit else "Belum")
            m15_color = "#16a34a" if m15_hit else "#dc2626"
            m15_tip = (f"tx {m15.get('best_tx')} · vol {m15.get('best_vol_sol')} SOL "
                       f"· {m15.get('total_tx')} tx/72h")
        else:
            m15_hit = False
            m15_txt = "—"
            m15_color = "#000000"
            m15_tip = "data swap belum tersedia"

        # 10 kolom compact (ATR dihapus)
        cols = st.columns([1.2, 1.6, 0.9, 1.05, 0.8, 0.9, 1.05, 0.75, 0.95, 0.6])

        # Token
        cols[0].markdown(f"<div class='watch-row'><b style='color:#000000'>{sym}</b><br><span style='font-size:0.65rem;color:#000000'>{src}</span></div>", unsafe_allow_html=True)

        # CA + Links
        cols[1].markdown(
            f"<div class='watch-row'>"
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
        cols[2].markdown(f"<div class='watch-row' style='text-align:center'>{diamond_txt}<br><span style='font-size:0.60rem;color:#000000'>diamond</span></div>", unsafe_allow_html=True)

        # Real vs Dust holders
        real = det.get("real_holders")
        dust = det.get("dust_holders")
        if real is not None and dust is not None:
            real_dust = f"<span style='color:#16a34a;font-weight:700;'>{real}</span>/<span style='color:#dc2626;font-weight:700;'>{dust}</span>"
        else:
            real_dust = "<span style='color:#000000'>—</span>"
        cols[3].markdown(f"<div class='watch-row' style='text-align:center'>{real_dust}<br><span style='font-size:0.60rem;color:#000000'>real/dust</span></div>", unsafe_allow_html=True)

        # M15 flag — candle 15m dgn tx>500 & vol>500 SOL
        cols[4].markdown(
            f"<div class='watch-row' style='text-align:center'>"
            f"<span style='color:{m15_color};font-weight:700;' title='{m15_tip}'>{m15_txt}</span>"
            f"<br><span style='font-size:0.60rem;color:#000000'>tx&gt;500 &amp; vol&gt;500 SOL</span></div>",
            unsafe_allow_html=True
        )

        # Avg Cost (dari GMGN — live fetch jika perlu)
        avgc = det.get("avg_cost")
        avgc_txt = f"<span style='color:#ca8a04;font-weight:700;'>{avgc:+.1f}%</span>" if avgc is not None else "<span style='color:#000000'>—</span>"
        cols[5].markdown(f"<div class='watch-row' style='text-align:center'>{avgc_txt}<br><span style='font-size:0.60rem;color:#000000'>avg cost</span></div>", unsafe_allow_html=True)

        # Sinyal
        cols[6].markdown(f"<div class='watch-row'>{badge}</div>", unsafe_allow_html=True)

        # Skor
        cols[7].markdown(f"<div class='watch-row'><span style='font-weight:700;color:#000000'>{score:.0f}/7</span><span style='color:#000000;font-size:0.69rem;'> checks</span></div>", unsafe_allow_html=True)

        # Update
        cols[8].markdown(f"<div class='watch-row'><span style='font-size:0.69rem;color:#000000'>{_fmt_ts(ts)}</span></div>", unsafe_allow_html=True)

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

    st.caption(f"Total {len(wl)} token dipantau. Cron harian 07:00 WIB (00:00 UTC) menghitung CVD GMGN; token KERING dipindai transaksi setiap 15 menit.")

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
st.caption("Cron harian 07:00 WIB (00:00 UTC, GMGN candle flip): update CVD → evaluasi prepump_baru (7 checks) → Telegram jika sinyal muncul. Data CVD 72 jam. Sinyal BARU dari prepump_baru (bukan 4-pillar lama).")

