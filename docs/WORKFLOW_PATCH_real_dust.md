# Patch `.github/workflows/cvd-update.yml` — `real_dust_history.json`

**Owner action required.** Agen tidak bisa edit workflow (GitHub App
tidak punya izin `workflows` — lihat AGENTS.md §7). Edit manual
lewat web GitHub dengan diff di bawah ini.

## File: `.github/workflows/cvd-update.yml`

Tujuan: supaya `real_dust_history.json` (history real holder vs dust
holder per CA, dicatat tiap cron 1 jam) ikut di-commit tiap cron run.
Tanpa ini, grafik **📈 Pertumbuhan real vs dust** di card LP/Degen
Radar tidak pernah punya data di Streamlit Cloud — file di-write di
runner tapi hilang saat runner selesai (runner ephemeral).

File sudah dibuat sebagai `{}` kosong di repo, jadi `git add` tidak
akan gagal walaupun tanpa `|| true`.

### Diff (tambahkan 1 baris)

```diff
           git add cvd.json signals.json conviction.json levels.json breakouts.json
           git add holder_snapshots.json 2>/dev/null || true
+          # real_dust_history.json: hourly real-vs-dust holder counts —
+          # powers the "📈 Pertumbuhan real vs dust" card on the main page
+          git add real_dust_history.json 2>/dev/null || true
           git diff --cached --quiet || git commit -m "chore: cvd update $(date -u +%FT%H:%M) · GMGN"
```

## Cara apply lewat web GitHub

1. Buka <https://github.com/lparmycalprut/wallet-depth/edit/main/.github/workflows/cvd-update.yml>
2. Cari baris:
   ```
   git add holder_snapshots.json 2>/dev/null || true
   ```
3. Tambahkan tepat di bawahnya:
   ```
   git add real_dust_history.json 2>/dev/null || true
   ```
4. Commit langsung di web (judul bebas, misal
   "ci: commit real_dust_history.json").

## Verifikasi setelah update

1. Tunggu cron berikutnya (tiap jam, menit :30 UTC). Log run akan
   menampilkan suffix baru, misal:
   `✅ RYDER HB7MPRY… +12 swaps, 48 hourly buckets snap-helius:1234 holders rd:210r/1024d`
   (`rd:210r/1024d` = 210 real, 1024 dust tercatat).
2. Buka `https://github.com/lparmycalprut/wallet-depth/blob/main/real_dust_history.json`
   — file berisi 1 titik per CA per jam.
3. Di main app: card LP/Degen Radar menampilkan blok
   **📈 Pertumbuhan real vs dust** (headline NAIK/TURUN/DATAR + chip
   Δ 1/6/24 jam + sparkline). Headline arah baru muncul setelah
   **≥2 titik** (±2 jam setelah patch aktif); chip 6 jam/24 jam
   muncul setelah datanya cukup.

## Catatan penting

- Pencatatan hanya terjadi di **jalur Helius** (list holder lengkap).
  Fallback GMGN (top-10 holder) **sengaja tidak mencatat** — real/dust
  dari top-10 akan selalu bilang "0 dust", itu bohong.
- Kalau `HELIUS_API_KEY` tidak diset di secrets, history tidak tercatat
  (card tetap menampilkan blok real/dust live dari dashboard, tapi
  grafik pertumbuhan kosong).
- Threshold dust mengikuti `dust_limit_usd` di `config.json`
  (default $5) — sama dengan yang dipakai card live.
