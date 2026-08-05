# -*- coding: utf-8 -*-
"""📈 Accumulation History — deteksi pola akumulasi di SELURUH umur token.

Page baru (10) yang memindai seluruh riwayat chart sebuah token dengan
window geser 48 jam (definisi & threshold 5 fase SAMA dengan page 9
Accumulation Detector), lalu memverifikasi window kandidat dengan data
swap GMGN wallet-level.  Hasilnya adalah RENTANG TANGGAL (WIB) di mana pola
akumulasi terdeteksi di masa lalu — bukan hanya verdict 48 jam terakhir.

Alur:
  1. Candle-first: fetch full history (day + hour, paginasi backward via
     ``before_timestamp``), rolling scan murni dari candle.
  2. Hanya window kandidat (pre-score cukup tinggi) yang di-fetch swap
     GMGN-nya (from_ts/to_ts, max_pages dibatasi) untuk skor 5 fase penuh.
  3. Window berdekatan yang lolos digabung menjadi rentang tanggal.
  4. Panel perbandingan: verdict window 48 jam terakhir (logika sama dgn
     page 9) supaya bisa dibandingkan langsung.

Bahasa UI: Indonesia.  Waktu ditampilkan dalam WIB (Asia/Jakarta).
Semua logika scoring/merging ada di modul murni ``accum_history.py``.
"""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Accumulation History",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.warning("⚠️ Aplikasi ini dinonaktifkan sementara.")
st.stop()

WIB = ZoneInfo("Asia/Jakarta")
_BLN = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep",
        "Okt", "Nov", "Des"]

PHASE_LABEL_ID = {
    "liquidity_test": "🧪 Liquidity Test",
    "slow_accumulation": "📈 Akumulasi Lambat",
    "whale_entry": "🐋 Whale Entry",
    "volume_spike": "🚀 Volume Spike",
    "thin_liquidity": "💧 Thin Liquidity",
}

REC_EMOJI = {"BUY WATCH": "🟢", "ACCUMULATING": "🟡", "AVOID": "🔴",
             "TOO LATE": "⚫"}


def fmt_wib(ts, with_time=True) -> str:
    """Format unix seconds → WIB string, e.g. '30 Jul 2026 23:00'."""
    dt = datetime.fromtimestamp(int(ts), tz=WIB)
    base = f"{dt.day} {_BLN[dt.month]} {dt.year}"
    return f"{base} {dt.hour:02d}:{dt.minute:02d}" if with_time else base


try:
    from core import get_market
    from cvd import (fetch_swaps, get_gmgn_fetch_status, get_sol_price)
    import accum_history as ah
except Exception as e:
    st.error(f"Import gagal: {e}")
    st.stop()


# ── Fetch ter-cache (jangan fetch 2x per page load) ──────────────────────


@st.cache_data(ttl=300, show_spinner=False)
def _cached_market(ca: str) -> dict:
    return get_market(ca)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_candles(pool: str, timeframe: str) -> dict:
    return ah.fetch_candles_full(pool, timeframe=timeframe, aggregate=1,
                                 max_pages=ah.MAX_CANDLE_PAGES, timeout=20)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_window_swaps(ca: str, t0: int, t1: int, max_pages: int):
    """GMGN swap fetch untuk satu window kandidat + metadata kelengkapan."""
    swaps, _sig, _ts, _hit = fetch_swaps(
        "", "", ca, use_gmgn=True, from_ts=int(t0), to_ts=int(t1),
        max_pages=max_pages, sleep=0.05)
    status = get_gmgn_fetch_status()
    return list(swaps), dict(status)


# ── Header ───────────────────────────────────────────────────────────────

st.title("📈 Accumulation History")
st.caption(
    "Scan pola akumulasi 5-fase di **SELURUH umur token** (sejak pair dibuat), "
    "bukan hanya 48 jam terakhir — hasil berupa rentang tanggal (WIB) kapan "
    "pola terdeteksi. Definisi & threshold sama persis dengan page 9 "
    "🔍 Accumulation Detector supaya bisa dibandingkan."
)

with st.expander("ℹ️ Cara kerja & batasan", expanded=False):
    st.markdown("""
**Alur scan:**
1. **Candle-first** — fetch full history OHLCV GeckoTerminal (timeframe `day`
   untuk overview + `hour` untuk detail, paginasi mundur via
   `before_timestamp` bila > 1000 candle). Rolling scan window **48 jam**
   (step 3–12 jam) di seluruh umur token, murni dari candle.
2. **Kandidat** — window dengan pre-score cukup tinggi (volume spike,
   struktur base→spike, estimasi thin-liquidity historis) dipilih; fase yang
   butuh data wallet (tx count, unique wallet, whale entry, test tx) diberi
   status *belum diverifikasi*.
3. **Verifikasi** — hanya kandidat yang di-fetch swap GMGN-nya
   (`from_ts`/`to_ts`, `max_pages` dibatasi), lalu dihitung skor 5 fase penuh
   ala page 9 dengan progress bar. Kalau GMGN gagal/terbatas, confidence
   turun — tidak crash.
4. **Merge** — window berdekatan yang lolos digabung menjadi satu rentang
   `[mulai, selesai]` (skor = maksimum, fase hit = gabungan).

**Catatan penting:**
- Fase 5 (Thin Liquidity) untuk window historis memakai **estimasi**
  liq/FDV saat itu = nilai kini × rasio harga candle (median close window vs
  harga sekarang) — ditandai `~` di tabel.
- Fase 1–3 dirancang untuk periode launch; untuk token tua, fase 1/2 pada
  window historis hanya konteks, bukan sinyal utama — perhatikan fase
  `Volume Spike` & `Whale Entry`.
- Harga & volume candle GeckoTerminal = USD; data swap GMGN = SOL
  (dikonversi via harga SOL terkini).
- Semua timestamp ditampilkan dalam **WIB (Asia/Jakarta)**.
""")

# ── Sidebar konfigurasi ──────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ Konfigurasi Scan")
    step_h = st.selectbox("Langkah geser window (jam)", [3, 6, 12], index=1,
                          help="Window 48 jam digeser sebesar ini di seluruh "
                               "umur token. Lebih kecil = lebih teliti, lebih "
                               "lambat.")
    min_cand = st.slider("Pre-score minimum kandidat", 30, 60, 40, 5,
                         help="Window dengan skor candle di bawah ini "
                              "dilewati (tidak diverifikasi).")
    max_cands = st.slider("Maks. window yang diverifikasi", 3, 12, 8, 1,
                          help="Batas window kandidat yang di-fetch swap "
                               "GMGN-nya per scan.")
    max_pages = st.slider("Maks. halaman GMGN per window", 10, 120, 60, 10,
                          help="100 trade/halaman. Terlalu rendah → data "
                               "parsial → confidence turun.")
    min_res = st.slider("Ambang skor hasil yang ditampilkan", 30, 60, 40, 5,
                        help="Rentang dengan skor terverifikasi di bawah ini "
                             "tidak dimasukkan ke tabel hasil.")
    verify_on = st.checkbox("Verifikasi wallet via GMGN", value=True,
                            help="Matikan untuk mode candle-only (lebih "
                                 "cepat, semua fase wallet 'belum diverifikasi').")
    st.caption(f"Window: {ah.WINDOW_H} jam · step {step_h} jam · gap merge "
               f"{ah.MERGE_GAP_H} jam")

# ── Input ────────────────────────────────────────────────────────────────

if "accum_hist_ca" not in st.session_state:
    st.session_state["accum_hist_ca"] = ""

ca = st.text_input(
    "Solana Token Contract Address (CA)",
    value=st.session_state.get("accum_hist_ca", ""),
    placeholder="e.g. 6LLNiWXRZp8hn5oTFTHEo8ERbJS3QJfHSKhnTCqipump (MEMIPEDE)",
).strip()

# Parse URL DexScreener → CA
if ca.startswith("http"):
    parts = ca.rstrip("/").split("/")
    ca = parts[-1] if parts else ca
st.session_state["accum_hist_ca"] = ca

scan = st.button("🔍 Scan Riwayat Akumulasi", type="primary",
                 use_container_width=True)

if not scan:
    st.info("Masukkan CA token Solana lalu klik **Scan Riwayat Akumulasi**. "
            "Contoh test case: `6LLNiWXRZp8hn5oTFTHEo8ERbJS3QJfHSKhnTCqipump` "
            "(MEMIPEDE — spike volume ~$16.6K pada 30 Jul 2026 16:00 UTC).")
    st.stop()

if not ca:
    st.error("CA kosong — masukkan contract address token.")
    st.stop()

# ═════════════════════════════════════════════════════════════════════════
# RUN SCAN
# ═════════════════════════════════════════════════════════════════════════

with st.spinner("Fetch data pasar (DexScreener)..."):
    try:
        market = _cached_market(ca)
    except Exception as e:
        market = {}
        st.error(f"Gagal fetch data pasar (DexScreener): {e}")
if not market:
    st.error("Token tidak ditemukan di DexScreener. Periksa CA-nya.")
    st.stop()

symbol = market.get("symbol", "?")
name = market.get("name", "?")
price_now = float(market.get("price_usd") or 0)
liq_now = float(market.get("liquidity_usd") or 0)
fdv_now = float(market.get("marketcap") or 0)
created_ms = market.get("pair_created_at")
created_ts = int(created_ms / 1000) if created_ms else None
pair_addrs = market.get("pair_addresses") or []
if not pair_addrs:
    st.warning("DexScreener tidak mengembalikan pair address — tidak bisa "
               "fetch candle GeckoTerminal.")
    st.stop()
pool = pair_addrs[0]

now_ts = int(time.time())
age_days = (now_ts - created_ts) / 86400.0 if created_ts else None

st.markdown(f"### {name} (`{symbol}`)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Harga", f"${price_now:,.8f}".rstrip("0").rstrip("."))
c2.metric("Market Cap", f"${fdv_now:,.0f}")
c3.metric("Liquidity", f"${liq_now:,.0f}")
c4.metric(
    "Umur Pair",
    f"{age_days:.1f} hari" if age_days is not None else "?",
    f"dibuat {fmt_wib(created_ts) if created_ts else '?'} WIB",
)

if age_days is not None and age_days < 2.5:
    st.warning(f"⚠️ Pair baru berumur **{age_days:.1f} hari** — riwayat candle "
               f"belum penuh 48 jam untuk window pertama. Hasil bersifat "
               f"parsial; coba lagi besok.")

# ── 1. Fetch candle full history ─────────────────────────────────────────

with st.spinner("Fetch full history candle (GeckoTerminal, day + hour)..."):
    try:
        daily_res = _cached_candles(pool, "day")
        hourly_res = _cached_candles(pool, "hour")
    except Exception as e:
        daily_res = {"candles": [], "pages": 0, "complete": False,
                     "oldest_ts": None}
        hourly_res = dict(daily_res)
        st.error(f"Gagal fetch candle GeckoTerminal: {e}")

daily_candles = daily_res.get("candles") or []
hourly_candles = hourly_res.get("candles") or []

if not hourly_candles and not daily_candles:
    st.error("GeckoTerminal tidak mengembalikan candle apa pun untuk pair ini "
             "(network terblokir / pair tidak ter-track). Tidak bisa scan.")
    st.stop()
if not hourly_candles:
    st.warning("Candle hourly kosong — scan memakai candle harian saja "
               "(resolusi kasar).")

st.caption(
    f"Data candle: day {len(daily_candles)} candle ({daily_res['pages']} "
    f"halaman, complete={daily_res['complete']}) · hour "
    f"{len(hourly_candles)} candle ({hourly_res['pages']} halaman, "
    f"complete={hourly_res['complete']})"
)

# ── 2. Rolling scan (candle-only) ────────────────────────────────────────

with st.spinner("Rolling scan 48 jam di seluruh umur token..."):
    scan_candles = hourly_candles or daily_candles
    candidates = ah.rolling_scan(
        scan_candles, liq_now=liq_now, fdv_now=fdv_now, price_now=price_now,
        window_h=ah.WINDOW_H, step_h=step_h, min_score=min_cand,
        max_candidates=max_cands)

if not candidates:
    st.info(
        "🔍 **Tidak ada kandidat window akumulasi** di seluruh riwayat token "
        f"ini (pre-score ≥ {min_cand}). Artinya: tidak ada kombinasi "
        "struktur base→spike + estimasi thin-liquidity yang menonjol. "
        "Coba turunkan pre-score minimum di sidebar, atau token ini memang "
        "tidak pernah menunjukkan pola pre-pump klasik."
    )
    st.stop()

st.success(
    f"✅ {len(candidates)} window kandidat ditemukan dari "
    f"{len(scan_candles)} candle ({fmt_wib(scan_candles[0]['ts'])} → "
    f"{fmt_wib(scan_candles[-1]['ts'])} WIB). Verifikasi dengan data swap…"
)

# ── 3. Verifikasi wallet (GMGN) per kandidat ─────────────────────────────

verified = []
gmgn_errors = []
sol_price = get_sol_price()

if verify_on:
    prog = st.progress(0.0, text="Verifikasi window kandidat (GMGN)…")
    for i, cand in enumerate(candidates):
        prog.progress((i + 1) / len(candidates),
                      text=f"Window {i + 1}/{len(candidates)}: "
                           f"{fmt_wib(cand['t0'])} → {fmt_wib(cand['t1'])} WIB")
        swaps, status = _cached_window_swaps(ca, cand["t0"], cand["t1"],
                                             max_pages)
        swaps = [s for s in swaps if len(s) >= 4
                 and cand["t0"] <= int(s[2]) < cand["t1"]]
        gmgn_ok = bool(status.get("ok"))
        gmgn_complete = bool(status.get("complete"))
        if status.get("error"):
            gmgn_errors.append(str(status["error"]))
        res = ah.score_window(
            swaps, scan_candles, sol_price=sol_price, liq_now=liq_now,
            fdv_now=fdv_now, price_now=price_now,
            t0=cand["t0"], t1=cand["t1"], launch_ts=created_ts)
        res["confidence"] = ah.window_confidence(
            res["score"], has_hourly=bool(res["support"]["active_hours"]),
            has_candles=True, gmgn_ok=gmgn_ok, gmgn_complete=gmgn_complete,
            estimated=res["estimated"])
        res["gmgn"] = {"ok": gmgn_ok, "complete": gmgn_complete,
                       "error": status.get("error", "")}
        verified.append(res)
    prog.empty()
else:
    # Mode candle-only: kandidat jadi hasil "belum diverifikasi".
    for cand in candidates:
        verified.append({
            "t0": cand["t0"], "t1": cand["t1"], "score": cand["score"],
            "overall": cand["score"],
            "phase_scores": cand["phase_scores"],
            "phase_hits": cand["phase_hits"],
            "pattern": ah.pattern_from_hits(cand["phase_hits"]),
            "recommendation": "BELUM DIVERIFIKASI",
            "confidence": "LOW", "estimated": True,
            "est_liq": cand["est_liq"], "est_fdv": cand["est_fdv"],
            "launch_window": bool(created_ts and cand["t0"] <= created_ts < cand["t1"]),
            "support": {"tx_total": 0, "vol_usd_total": 0.0,
                        "unique_wallets": 0, "peak_tx": 0,
                        "peak_vol_usd": 0.0, "peak_wallets": 0,
                        "active_hours": 0},
            "n_swaps": 0,
            "gmgn": {"ok": False, "complete": False, "error": ""},
            "unverified": True,
        })

if gmgn_errors:
    st.warning(
        "⚠️ GMGN melaporkan masalah saat verifikasi beberapa window: "
        + "; ".join(sorted(set(gmgn_errors))[:3])
        + ". Window yang terdampak diberi confidence **LOW** — skor tetap "
        "ditampilkan tapi jangan dianggap final."
    )

# ── 4. Filter + merge ────────────────────────────────────────────────────

passed = [r for r in verified if r["score"] >= min_res]
merged = ah.merge_windows(passed, gap_h=ah.MERGE_GAP_H)

# ── 5. Panel perbandingan: verdict 48 jam terakhir (ala page 9) ──────────

last_t0 = now_ts - ah.WINDOW_H * 3600
with st.spinner("Analisis window 48 jam terakhir (pembanding page 9)…"):
    if verify_on:
        swaps_last, last_status = _cached_window_swaps(ca, last_t0, now_ts,
                                                       max_pages=80)
        swaps_last = [s for s in swaps_last if len(s) >= 4
                      and last_t0 <= int(s[2]) < now_ts]
        last_res = ah.score_window(
            swaps_last, scan_candles, sol_price=sol_price, liq_now=liq_now,
            fdv_now=fdv_now, price_now=price_now, t0=last_t0, t1=now_ts,
            use_current_liq=True, launch_ts=created_ts)
        last_res["confidence"] = ah.window_confidence(
            last_res["score"],
            has_hourly=bool(last_res["support"]["active_hours"]),
            has_candles=True,
            gmgn_ok=bool(last_status.get("ok")),
            gmgn_complete=bool(last_status.get("complete")),
            estimated=False)
        last_res["gmgn"] = last_status
    else:
        last_res = {"score": 0, "recommendation": "BELUM DIVERIFIKASI",
                    "phase_hits": [], "pattern": "NONE",
                    "confidence": "LOW", "support": {"tx_total": 0,
                    "vol_usd_total": 0.0, "unique_wallets": 0,
                    "active_hours": 0}, "gmgn": {"ok": False,
                    "complete": False, "error": ""}}

# ═════════════════════════════════════════════════════════════════════════
# RENDER HASIL
# ═════════════════════════════════════════════════════════════════════════

# ── Tabel rentang akumulasi ──────────────────────────────────────────────

st.markdown("## 📋 Rentang Akumulasi Terdeteksi")

if not merged:
    st.info(
        f"Tidak ada window yang lolos ambang skor **{min_res}** setelah "
        f"verifikasi (dari {len(candidates)} kandidat). Coba turunkan ambang "
        "di sidebar, atau perbesar jumlah window yang diverifikasi."
    )
else:
    rows = []
    for r in merged:
        sup = r["support"]
        support_txt = f"{sup['tx_total']:,} tx · ${sup['vol_usd_total']:,.0f}"
        if sup["unique_wallets"]:
            support_txt += f" · {sup['unique_wallets']:,} wallet"
        if r.get("n_windows", 1) > 1:
            support_txt += f" · {r['n_windows']} window digabung"
        notes = []
        if r.get("estimated"):
            notes.append(f"liq/FDV estimasi (${r['est_liq']:,.0f}/"
                         f"${r['est_fdv']:,.0f})")
        if r.get("launch_window"):
            notes.append("window berisi jam launch token")
        if r.get("unverified"):
            notes.append("belum diverifikasi GMGN (mode candle-only)")
        elif not r["gmgn"].get("complete"):
            notes.append("data GMGN parsial")
            if r.get("gmgn", {}).get("error"):
                notes.append("ada error GMGN")
        rows.append({
            "Periode (WIB)": f"{fmt_wib(r['t0'])} → {fmt_wib(r['t1'])}",
            "Skor": r["score"],
            "Fase Hit": ", ".join(PHASE_LABEL_ID[k] for k in r["phase_hits"])
                        or "—",
            "Pola": r["pattern"],
            "Rekomendasi": r["recommendation"],
            "Confidence": r["confidence"],
            "Data Pendukung": support_txt,
            "Catatan": "; ".join(notes) or "—",
        })
    df = pd.DataFrame(rows)
    df = df.sort_values("Skor", ascending=False).reset_index(drop=True)
    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            "Skor": st.column_config.ProgressColumn(
                "Skor", min_value=0, max_value=100,
                format="%d/100"),
        },
    )
    st.caption("Urut berdasarkan skor (terbaru-ke-lama bisa dilihat dari "
               "rentang tanggal). Skor & fase = definisi page 9 "
               "(max 100).")

# ── Chart full periode dengan highlight rentang ──────────────────────────

st.markdown("## 📊 Chart Full Periode (harga + volume harian)")

if daily_candles:
    cdf = pd.DataFrame(daily_candles)
    for col in ["o", "h", "l", "c", "v"]:
        cdf[col] = pd.to_numeric(cdf[col], errors="coerce")
    cdf["dt"] = pd.to_datetime(cdf["ts"].astype(int), unit="s", utc=True) \
        .dt.tz_convert(WIB)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=cdf["dt"], y=cdf["v"], name="Volume (USD)",
        marker=dict(color="#38bdf8", opacity=0.45), yaxis="y2"))
    fig.add_trace(go.Scatter(
        x=cdf["dt"], y=cdf["c"], name="Close (USD)",
        line=dict(color="#facc15", width=2), yaxis="y1"))
    for r in merged:
        fig.add_vrect(
            x0=pd.Timestamp(datetime.fromtimestamp(r["t0"], tz=WIB)),
            x1=pd.Timestamp(datetime.fromtimestamp(r["t1"], tz=WIB)),
            fillcolor="#22c55e", opacity=0.12, line_width=0,
            annotation_text=f"Skor {r['score']}",
            annotation_position="top left",
            annotation_font=dict(size=10, color="#22c55e"))
    if created_ts:
        fig.add_vline(
            x=pd.Timestamp(datetime.fromtimestamp(created_ts, tz=WIB)),
            line_dash="dot", line_color="#64748b", opacity=0.6)
    fig.update_layout(
        height=360, margin=dict(t=10, b=0, l=0, r=0),
        legend=dict(orientation="h", font=dict(size=11)),
        yaxis=dict(title="Harga", type="log", tickfont=dict(size=9)),
        yaxis2=dict(title="Volume", overlaying="y", side="right",
                    visible=True, tickfont=dict(size=9)),
        xaxis=dict(tickfont=dict(size=9), title="WIB"),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})
    st.caption("Area hijau = rentang akumulasi terdeteksi (WIB). Garis "
               "putus-putus = waktu pair dibuat.")
else:
    st.caption("Candle harian tidak tersedia untuk chart.")

# ── Detail hourly untuk window terbaik ───────────────────────────────────

if merged and hourly_candles:
    best = max(merged, key=lambda r: r["score"])
    st.markdown("## 🔬 Detail Hourly — Window Terbaik")
    st.caption(f"Rentang: {fmt_wib(best['t0'])} → {fmt_wib(best['t1'])} WIB "
               f"(skor {best['score']})")
    pad = 12 * 3600
    wc = [c for c in hourly_candles
          if best["t0"] - pad <= int(c["ts"]) < best["t1"] + pad]
    if wc:
        hdf = pd.DataFrame(wc)
        for col in ["o", "h", "l", "c", "v"]:
            hdf[col] = pd.to_numeric(hdf[col], errors="coerce")
        hdf["dt"] = pd.to_datetime(hdf["ts"].astype(int), unit="s", utc=True) \
            .dt.tz_convert(WIB)
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=hdf["dt"], y=hdf["v"], name="Volume",
            marker=dict(color="#38bdf8", opacity=0.5), yaxis="y2"))
        fig2.add_trace(go.Scatter(
            x=hdf["dt"], y=hdf["c"], name="Price",
            line=dict(color="#facc15", width=2), yaxis="y1"))
        fig2.add_vrect(
            x0=pd.Timestamp(datetime.fromtimestamp(best["t0"], tz=WIB)),
            x1=pd.Timestamp(datetime.fromtimestamp(best["t1"], tz=WIB)),
            fillcolor="#22c55e", opacity=0.12, line_width=0)
        fig2.update_layout(
            height=280, margin=dict(t=10, b=0, l=0, r=0),
            legend=dict(orientation="h", font=dict(size=10)),
            yaxis=dict(title="Price", type="log", tickfont=dict(size=9)),
            yaxis2=dict(title="Volume", overlaying="y", side="right",
                        visible=True, tickfont=dict(size=9)),
            xaxis=dict(tickfont=dict(size=9), title="WIB"),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig2, use_container_width=True,
                        config={"displayModeBar": False})

# ── Breakdown fase per window ────────────────────────────────────────────

if merged:
    st.markdown("## 🧩 Breakdown Fase per Rentang")
    for r in sorted(merged, key=lambda x: x["score"], reverse=True):
        label = (f"{fmt_wib(r['t0'])} → {fmt_wib(r['t1'])} WIB · "
                 f"Skor {r['score']}/100 · {REC_EMOJI.get(r['recommendation'], '')} "
                 f"{r['recommendation']}")
        with st.expander(label):
            for key, _n, max_pts in ah.PHASES:
                ps = r["phase_scores"].get(key, {})
                score = ps.get("score", 0)
                pct = score / max_pts if max_pts else 0
                hit = score >= max_pts * ah.PHASE_HIT_RATIO
                badge = "✅" if hit else ("◐" if score > 0 else "—")
                st.markdown(
                    f"**{badge} {PHASE_LABEL_ID[key]}** — {score}/{max_pts} "
                    f"({pct * 100:.0f}%)  \n"
                    f"<small>{ps.get('detail', '')}</small>",
                    unsafe_allow_html=True)
            if not r.get("unverified") and r.get("gmgn", {}).get("error"):
                st.caption(f"GMGN: {r['gmgn']['error']}")

# ── Panel perbandingan page 9 ────────────────────────────────────────────

st.markdown("## ⚖️ Perbandingan — Verdict 48 Jam Terakhir (ala page 9)")
lrec = last_res.get("recommendation", "?")
lscore = last_res.get("score", 0)
lhit = ", ".join(PHASE_LABEL_ID[k] for k in last_res.get("phase_hits", [])) \
    or "—"
lsup = last_res.get("support", {})
st.markdown(
    f"""<div style="border:2px solid #475569;border-radius:12px;
    padding:14px 18px;background:rgba(71,85,105,0.15);">
    <b>Window {ah.WINDOW_H} jam terakhir:</b> {fmt_wib(last_t0)} →
    {fmt_wib(now_ts)} WIB  ·  Skor <b>{lscore}/100</b>  ·  Verdict:
    <b>{REC_EMOJI.get(lrec, '')} {lrec}</b>  ·  Confidence
    {last_res.get('confidence', '—')}<br>
    Fase hit: {lhit}<br>
    <small>Data: {lsup.get('tx_total', 0):,} tx · $
    {lsup.get('vol_usd_total', 0):,.0f} · {lsup.get('unique_wallets', 0):,}
    wallet · liq/FDV nilai kini (bukan estimasi). Definisi fase identik
    dengan page 9 🔍 Accumulation Detector; page 9 memakai window geser yang
    sama namun hanya melihat 48 jam terakhir.</small>
    </div>""",
    unsafe_allow_html=True,
)

if merged:
    hist_best = max(merged, key=lambda r: r["score"])
    if hist_best["score"] >= last_res.get("score", 0) and \
            hist_best["t1"] <= now_ts - 24 * 3600:
        st.info(
            f"💡 Pola akumulasi terkuat token ini terjadi pada "
            f"**{fmt_wib(hist_best['t0'])} → {fmt_wib(hist_best['t1'])} WIB** "
            f"(skor {hist_best['score']}) — sudah **di luar** window 48 jam "
            "terakhir yang dianalisa page 9. Page ini menangkapnya karena "
            "memindai seluruh umur token."
        )

# ── Footer ───────────────────────────────────────────────────────────────

st.markdown("---")
st.caption(
    f"Scan {fmt_wib(now_ts)} WIB · Sumber: DexScreener + GeckoTerminal + "
    f"GMGN Trades API · SOL ${sol_price:,.2f} · Skor fase = definisi page 9 "
    "(identik) · Liq/FDV historis = estimasi skala harga · "
    "Heuristik — bukan nasihat keuangan."
)
