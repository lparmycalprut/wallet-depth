# Progress Log — wallet-depth

## 2026-07-29

### ✅ LP Radar — Warning badge (app.py)
- Menambahkan badge `⚠️ HIGH` (oranye) untuk conviction ≥50%
- Menambahkan badge `⚠️ EXTREME` (merah) untuk conviction ≥100%
- Badge muncul di samping persentase pada setiap card LP Radar

### ✅ LP Radar — DexScreener & GMGN shortcuts (app.py)
- Shortcut 🦆 (DexScreener) dan ⚡ (GMGN) di pojok kanan atas setiap card
- Link `target='_blank'`, klik card tetap ke halaman CVD

### ✅ CVD page — dropdown jam (pages/4_📊_CVD.py)
- **Perubahan**: Card LP Radar tidak auto-analyze lagi — hanya prefill CA
- **Baru**: Dropdown **Time window** (4/6/8/12/24/36/48 jam, default 24h)
- **Baru**: Tombol **📊 Analyze** — fetch + analisis hanya setelah diklik
- `WINDOWS` dinamis: `[hours//4, hours//2, hours, 48]` (filter ≥4, ≤48)
- Semua teks, chart title, dan tabel menyesuaikan dengan jam yang dipilih

### ✅ CVD update workflow (.github/workflows/cvd-update.yml)
- `breakouts.json` ditambahkan ke `for` loop dan `git add` (sepertinya revert oleh user)

---

## Catatan untuk agent selanjutnya
- Jangan auto-analyze saat navigasi dari card LP Radar ke halaman CVD
- Halaman CVD butuh dropdown jam + tombol Analyze sebelum fetch
- LP Radar card punya shortcut DexScreener/GMGN di pojok kanan