# Agent Instructions — wallet-depth

## Recent changes (2026-07-29)

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
- `WINDOWS` dihitung dinamis: `[hours//4, hours//2, hours, 48]` (filter ≥4 dan ≤48)

### 🔧 CVD update workflow (`.github/workflows/cvd-update.yml`)
- `breakouts.json` ditambahkan ke `for` loop dan `git add`

## File structure
- `app.py` — main page (LP Radar, trending, analyzer)
- `pages/4_📊_CVD.py` — deep CVD analysis page
- `.github/workflows/cvd-update.yml` — hourly cron untuk CVD + data files