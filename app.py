# -*- coding: utf-8 -*-
"""
Wallet Depth — Prepump Radar (minimalist reset 2026-08-07)

Kept functions only:
  - watchlist (vertical list + sinyal harian)
  - scan trending / scan degen (with all filters, only Watchlist button)
  - CVD deep analysis (separate page)
  - history/signals as data backend (json)
  - telegram via daily cron at 00:00 WIB

Removed: cards, analyze on main page, compare/history/screener/cto/lp/accum/memecoin/prepump-checker pages,
  breakout_guard, focus, share_card, etc.
"""
import time
import os
from datetime import datetime, timezone, timedelta

import streamlit as st

from core import load_config, get_helius_keys
from watchlist import load_watchlist, add_to_watchlist, remove_from_watchlist, get_last_push_error

st.set_page_config(page_title="Wallet Depth — Prepump", page_icon="🎯", layout="wide", initial_sidebar_state="collapsed")

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
    """Return last prepump signal for CA, or None. Checks imminent/forming/cleared/neutral."""
    # Find most recent prepump_* for this CA
    best = None
    for s in reversed(sigs or []):
        if s.get("ca") == ca and s.get("type", "").startswith("prepump_"):
            best = s
            break
    if best:
        # Map to tier
        t = best.get("type")
        if t == "prepump_imminent":
            tier = "imminent"
        elif t == "prepump_forming":
            tier = "forming"
        elif t == "prepump_cleared":
            tier = "cleared"
        else:
            tier = "neutral"
        return tier, best.get("score", 0), best.get("ts"), best.get("detail", "")
    return None

def live_evaluate(ca: str, symbol: str):
    """Fallback live evaluate using local swap store (no network). Returns tier/score or neutral."""
    try:
        from cvd import get_recent_swaps
        from prepump_detector import evaluate_prepump
        swaps = get_recent_swaps(ca, hours=4)
        if not swaps:
            return "unknown", 0, None
        # Use 30m window as primary
        res = evaluate_prepump(swaps, {"symbol": symbol}, ca=ca, window_min=30)
        tier = res.get("tier", "neutral")
        score = res.get("score", 0)
        return tier, score, int(time.time())
    except Exception:
        return "unknown", 0, None

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
st.caption("Fokus: watchlist → scan trending/degen → CVD → sinyal harian 00:00 WIB + notifikasi Telegram sehari sekali. Cards & analyze dihapus.")

# ---------------------------------------------------------------------------
# 1. WATCHLIST (vertical list, sinyal column)
# ---------------------------------------------------------------------------
wl = load_watchlist()

st.markdown("### ⭐ Watchlist — Sinyal Prepump (update harian 00:00 WIB)")
st.caption("List menurun. Kolom **Sinyal** menunjukkan apakah ada setup prepump yang terdeteksi (imminent/forming). Update cuma sekali sehari oleh cron — bukan tiap jam — supaya tidak spam.")

if not wl:
    st.info("Watchlist kosong. Tambahkan manual di bawah atau dari hasil Scan Trending / Scan Degen.")
else:
    try:
        from signals import load_signals
        all_sigs = load_signals()
    except Exception:
        all_sigs = []
    # Header row
    hdr = st.columns([1.3, 1.6, 1.1, 0.9, 1.1, 0.7])
    for c, lab in zip(hdr, ["Token", "CA", "Sinyal", "Skor", "Update", ""]):
        c.markdown(f"**{lab}**")
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
            # map unknown to neutral
            if tier == "unknown":
                tier = "neutral"
                score = 0
                ts = None

        # Badge config
        if tier == "imminent":
            badge = f"<span style='background:#7f1d1d;color:#fecaca;border:1px solid #ef4444;border-radius:6px;padding:3px 8px;font-weight:800;font-size:0.82rem;'>🚨 IMMINENT {score:.0f}/100</span>"
            row_bg = "background:rgba(239,68,68,0.06);border:1px solid #7f1d1d;border-radius:10px;padding:8px 6px;margin-bottom:6px;"
        elif tier == "forming":
            badge = f"<span style='background:#78350f;color:#fde68a;border:1px solid #f59e0b;border-radius:6px;padding:3px 8px;font-weight:800;font-size:0.82rem;'>👀 FORMING {score:.0f}/100</span>"
            row_bg = "background:rgba(245,158,11,0.06);border:1px solid #78350f;border-radius:10px;padding:8px 6px;margin-bottom:6px;"
        elif tier == "cleared":
            badge = f"<span style='background:#1e293b;color:#94a3b8;border:1px solid #334155;border-radius:6px;padding:3px 8px;font-weight:700;font-size:0.82rem;'>✅ CLEARED {score:.0f}/100</span>"
            row_bg = "background:rgba(148,163,184,0.05);border:1px solid #334155;border-radius:10px;padding:8px 6px;margin-bottom:6px;"
        else:
            badge = f"<span style='background:#1e293b;color:#94a3b8;border:1px solid #334155;border-radius:6px;padding:3px 8px;font-weight:700;font-size:0.82rem;'>➖ NETRAL</span>"
            row_bg = "background:rgba(148,163,184,0.04);border:1px solid #334155;border-radius:10px;padding:8px 6px;margin-bottom:6px;"

        cols = st.columns([1.3, 1.6, 1.1, 0.9, 1.1, 0.7])
        cols[0].markdown(f"<div style='{row_bg}'><b style='color:#e2e8f0'>{sym}</b><br><span style='font-size:0.68rem;color:#94a3b8'>{src}</span></div>", unsafe_allow_html=True)
        cols[1].markdown(f"<div style='{row_bg}'><a href='https://solscan.io/token/{ca}' target='_blank' style='font-size:0.78rem;color:#38bdf8;text-decoration:none;'>{ca[:8]}…{ca[-4:]}</a><br><a href='https://dexscreener.com/solana/{ca}' target='_blank' style='font-size:0.68rem;color:#64748b;text-decoration:none;'>chart ↗</a> · <a href='/CVD?ca={ca}' target='_self' style='font-size:0.68rem;color:#64748b;text-decoration:none;'>CVD ↗</a></div>", unsafe_allow_html=True)
        cols[2].markdown(f"<div style='{row_bg}'>{badge}</div>", unsafe_allow_html=True)
        cols[3].markdown(f"<div style='{row_bg}'><span style='font-weight:700;color:#e2e8f0'>{score:.0f}</span><span style='color:#64748b;font-size:0.72rem;'>/100</span></div>", unsafe_allow_html=True)
        cols[4].markdown(f"<div style='{row_bg}'><span style='font-size:0.72rem;color:#94a3b8'>{_fmt_ts(ts)}</span></div>", unsafe_allow_html=True)
        # Delete button -> uses link with query param (no form needed)
        cols[5].markdown(f"<div style='{row_bg}'><a href='?del_ca={ca}' style='display:inline-block;background:rgba(239,68,68,0.15);border:1px solid #ef4444;color:#fecaca;border-radius:6px;padding:4px 10px;text-decoration:none;font-weight:700;font-size:0.78rem;'>🗑️ Hapus</a></div>", unsafe_allow_html=True)

    st.caption(f"Total {len(wl)} token dipantau. Cron harian 00:00 WIB akan update CVD + evaluasi prepump + kirim Telegram (hanya jika ada sinyal).")

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
st.caption("Cron harian 00:00 WIB (17:00 UTC): update CVD → evaluasi prepump → Telegram (hanya jika sinyal imminient/forming). Data CVD tetap tersedia 72 jam. Hapus cron lama: cto-radar, lp-safe, memecoin-scanner.")

