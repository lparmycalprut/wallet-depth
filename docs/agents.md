# Agent Instructions — wallet-depth

## Recent changes (2026-07-29)

### 💧 LP Radar — rewrite total (`app.py`)
- **Semua watchlist token** ditampilkan, tidak hanya yang growing
- **Stability badge**: 🟢 KOKOH (conviction stabil ≥30%) · 🟡 GOYAH · 🔴 MELEMAH
- **Multi-window sparkline**: 3 baris (6h / 12h / 24h) — lihat konsistensi conviction
- **Volume-quality indicator**: 💪 STRONG (≥100 SOL + ≥40%) · 🟡 NOISY · 👍 LIGHT · ⚪ THIN · 💤 QUIET
- Border card: hijau = kokoh, kuning = goyah, merah = melemah, glow hijau = grow 2x + kokoh

### 🎯 LP Radar — Warning badge (`app.py`)
- Jika conviction **≥100%** → badge merah `⚠️ EXTREME`
- Jika conviction **≥50%** → badge oranye `⚠️ HIGH`
- Badge muncul di samping persentase pada setiap card LP Radar

### 🔗 LP Radar — DexScreener & GMGN shortcuts (`app.py`)
- Setiap card LP Radar punya shortcut **🦆** (DexScreener) dan **⚡** (GMGN) di pojok kanan atas
- Link terbuka di tab baru, klik card tetap bisa ke halaman CVD

### ⏱ CVD page — dropdown jam + Analyze button (`pages/4_📊_CVD.py`)
- Card LP Radar tidak auto-analyze lagi — hanya prefill CA
- User pilih **Time window** (4/6/8/12/24/36/48 jam) lalu klik **📊 Analyze**
- Semua chart, tabel, window analysis menyesuaikan dengan jam yang dipilih
- `WINDOWS` via `analysis_windows(hours)` — menjamin semua row ≤ window terpilih
- Semua perhitungan window di-anchor ke `fetched_at`, bukan `time.time()`

### 🔧 CVD update workflow (`.github/workflows/cvd-update.yml`)
- `breakouts.json` ditambahkan ke `for` loop dan `git add`
- Jadwal: **setiap 4 jam** (dulu tiap jam)

### 📸 Watchlist snapshot (`.github/workflows/daily-snapshot.yml`)
- Jadwal: **setiap 8 jam** (dulu setiap 6 jam)

### 📊 Markup safety — 48h window (`cvd.py`)
- `markup_from_candles()` pakai **first candle close** sebagai base, bukan lowest low 30D
- Threshold: danger ≥**+100%**, warn ≥**+50%** (dulu 300%/150%)
- Candle fetch: **hourly 48h** (dulu daily 30 candle)
- Token baru tidak kena false positive markup

### 🔴 Screener notes — red danger styling (`trending_ui.py`)
- Notes yang mengandung "already ran", "entrapment", "trap", "downtrend", dll. di-highlight **merah menyala**

## File structure
- `app.py` — main page (LP Radar, trending, analyzer)
- `pages/4_📊_CVD.py` — deep CVD analysis page
- `cvd.py` — markup logic, CVD buckets, analysis windows
- `trending_ui.py` — screener renderer
- `.github/workflows/cvd-update.yml` — 4-hourly cron untuk CVD + data files
- `.github/workflows/daily-snapshot.yml` — 8-hourly snapshot