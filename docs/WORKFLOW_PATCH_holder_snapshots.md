# Patch `.github/workflows/cvd-update.yml` — `holder_snapshots.json`

**Owner action required.** Agen tidak bisa edit workflow (GitHub App
tidak punya izin `workflows` — lihat AGENTS.md §7). Edit manual
lewat web GitHub dengan diff di bawah ini.

## File: `.github/workflows/cvd-update.yml`

Tujuan: supaya `holder_snapshots.json` (snapshot holder per CA per 6h
bucket) ikut di-commit tiap cron run. Tanpa ini, file di-write lokal
di action tapi tidak pernah sampai ke repo, dan LP Radar whale/dolphin
delta tidak akan pernah muncul di Streamlit Cloud.

### Diff (tambahkan 1 file + 2 line edit)

```diff
@@ -44,11 +44,12 @@ jobs:
           # never commit conflict markers into JSON data files
           for f in cvd.json signals.json conviction.json levels.json breakouts.json; do
             if grep -q "<<<<<<<" "$f" 2>/dev/null; then
               git checkout --theirs "$f" 2>/dev/null || git checkout HEAD -- "$f" || true
             fi
           done
-          git add cvd.json signals.json conviction.json levels.json breakouts.json
+          git add cvd.json signals.json conviction.json levels.json breakouts.json holder_snapshots.json
+          # holder_snapshots.json: whale/dolphin holdings baseline (whale/dolphin delta
+          # on LP Radar). The 4h cron commits per CA every other run (~6h bucket).
           git diff --cached --quiet || git commit -m "chore: cvd update $(date -u +%FT%H:%M)"
           git push || (git pull --rebase && git push) || true
```

## Cara apply lewat web GitHub

1. Buka <https://github.com/lparmycalprut/wallet-depth/edit/main/.github/workflows/cvd-update.yml>
2. Cari baris:
   ```
   git add cvd.json signals.json conviction.json levels.json breakouts.json
   ```
3. Ganti dengan:
   ```
   git add cvd.json signals.json conviction.json levels.json breakouts.json holder_snapshots.json
   # holder_snapshots.json: whale/dolphin holdings baseline
   git diff --cached --quiet || git commit -m "chore: cvd update $(date -u +%FT%H:%M)"
   ```
4. Commit langsung di web (judul bebas, misal "ci: commit holder_snapshots.json").

## Verifikasi setelah update

Tunggu cron berikutnya (4h cadence, menit :20 UTC), lalu:
1. Buka `https://github.com/lparmycalprut/wallet-depth/blob/main/holder_snapshots.json`
   — file akan muncul (mungkin kecil dulu: hanya 1-2 CA di watchlist).
2. Buka LP Radar di Streamlit Cloud — badge `🐋` / `🐬` akan mulai
   muncul setelah **2 cron run** (butuh T0 + T1). Sebelum itu badge
   tetap menampilkan `⏳ waiting for snapshot baseline`.

## Kalau owner tidak mau edit workflow

Tidak fatal — UI sudah siap, kode `record_holder_snapshot` sudah
dipanggil di cron. Yang hilang hanya:
- Data tidak sampai ke repo → LP Radar di Streamlit Cloud tidak
  pernah lihat baseline (kecuali user force refresh manual).
- File di local runner akan ter-overwrite tiap cron tanpa pernah
  di-push (sampah membengkak di runner, tapi selesai saat runner
  restart).

Opsi alternatif kalau owner berubah pikiran: lihat `inline-commit`
opsi di tanya jawab sebelumnya (cron `git add && git commit && git
push` inline, bypass workflow).
