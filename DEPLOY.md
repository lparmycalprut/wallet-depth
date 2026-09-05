# Deploy

## Streamlit

- Entry point: `app.py`
- Python: lihat `runtime.txt`
- Dependencies: `requirements.txt`
- Secrets scanner utama: `HELIUS_API_KEY`/`HELIUS_API_KEYS` dan
  `GITHUB_TOKEN`.
- Secrets alert Telegram opsional: `TELEGRAM_BOT_TOKEN` dan
  `TELEGRAM_CHAT_ID`.

Watchlist di halaman utama menarik `holder_status.json` dari ref
`holder-live` (bukan commit `main`). Tombol **Scan holder watchlist**
menjalankan analisis holder lokal. Chart 📈 membuka halaman CVD.

Disk Streamlit Cloud **ephemeral**, jadi `holder_history.json` lokal hilang
tiap restart. Store penuh dipulihkan dari backup durable
`holder_history.json.gz` (ref `holder-live`) lewat
`holder_history.load_durable_holder_history()` — store lokal menang bila
timestamp seri, hasil pull di-cache 600 detik. Matikan round-trip dengan
`HOLDER_STORE_BACKUP=0` (mis. untuk debugging offline); tanpa backup pun
dashboard tetap jalan, hanya baseline scan FULL / kohort / kronologi wallet
yang tidak bisa dipulihkan.

## GitHub Actions

Workflow `.github/workflows/daily-effort.yml` ("Holder Dust Scanner")
menargetkan **1× per jam** (`schedule: cron "0 * * * *"`) dan memanggil
`python scripts/scan_holders.py`. Job memakai `timeout-minutes: 45` supaya
run yang macet tidak menumpuk antre di concurrency group `holder-scanner`
(run hourly yang lambat bisa membuat beberapa run tertunda sekaligus).

> **Schedule GitHub bersifat best-effort, bukan SLA.** GitHub bisa
> men-throttle / melewatkan schedule: pada cron `*/15 * * * *` kadens nyata
> terukur **±2 jam** (contoh run: 18:02, 20:58, 22:57, 00:39 UTC), bukan 15
> menit. Artinya "1 jam" adalah **target**, bukan janji — alert bucket 4 jam,
> titik per jam, dan cooldown 1 jam dirancang toleran terhadap run yang
> telat/dilewati.
>
> Cara memverifikasi kadens nyata:
> - log run: baris `Holder scan selesai: … updated=<ts> durasi=<detik>`
>   (`updated=` adalah timestamp run; selisih antar log = kadens aktual), atau
> - riwayat commit branch `holder-live` (commit `holder-history: backup …`
>   dibuat tiap publish), atau
> - tab **Actions → Holder Dust Scanner → schedule**.
>
> Repo yang tidak aktif > 60 hari otomatis dinonaktifkan GitHub Actions-nya
> (kebijakan GitHub) — jadwal perlu diaktifkan ulang manual bila dashboard
> berhenti diperbarui.

Langkah setiap scan:

1. Analisis per token: holder Helius DAS (fallback GMGN, **scan FULL** —
   paginasi sampai habis; `--max-wallets` default 100.000 sejak
   2026-09-05), klasifikasi real (>$10) vs dust, `dust_pct_mc`, mid-tier,
   kohort, lalu simpan detail baseline + kronologi (`detail=True`).
2. Evaluasi alert terhadap snapshot lama **sebelum** snapshot terbaru
   ditulis. Snapshot wallet disimpan secara bounded di history/status.
3. Publish `holder_status.json` ke branch `holder-live` (dibuat otomatis
   pada publish pertama) agar dashboard dan cron memakai state yang sama.
   Snapshot ramping: peta balance alert / kohort / wallet kronologi tidak
   ikut (hanya jumlah + sampel movements) — 2,87 MB → 0,30 MB untuk 36
   token (−90%), jadi dashboard memuat jauh lebih ringan.
4. Backup store penuh sebagai `holder_history.json.gz` (gzip, ref
   `holder-live`) lewat `holder_history.publish_holder_history()` — baseline
   scan FULL, kohort, state alert, dan kronologi wallet bertahan walau runner
   ephemeral. Run berikutnya mem-pull + `merge_stores()` **sebelum** evaluasi
   alert (langkah 2), jadi cron tidak pernah mulai dari nol. Backup gagal
   hanya `WARN` (`backup=GAGAL (...)` di log), exit code tetap dari publish
   snapshot. `--no-push` melewati keduanya.

Cadence hourly (sejak 2026-09-04) dan ukuran ref `holder-live`:

- `MAX_POINTS = 336` = 14 hari × 24 titik/jam per token. Grafik UI tetap
  memakai `resample_4h` (bucket 4 jam, ≤ 84 titik), jadi snapshot dashboard
  tidak ikut membengkak; store mentah yang membesar dibackup terkompresi
  gzip. Terukur dengan store sintetis 55 token × 336 titik per jam:
  backup ~**1,03 MB** (batas `MAX_BACKUP_BYTES` 3,5 MB) — estimasi
  pertumbuhan ~**±633 kB × 24 run/hari ≈ 15 MB/hari** isi Git bila tiap run
  mengganti blob (bandingkan ±7,6 MB/hari pada kadens 2 jam; git menyimpan
  delta antar commit, nilai sesungguhnya lebih kecil).
- Kuota holder: sejak 2026-09-05 cron scan **FULL** (bukan sampel 3000):
  token yang punya ≤ 3000 holder tidak berubah biayanya, token lebih besar
  ikut semua halamannya (default `--max-wallets` = 100.000 = batas atas
  aman). **Catatan:** baris workflow yang masih mengirim
  `--max-wallets 3000` belum bisa dihapus lewat bot (butuh izin
  `workflows` di repo) — selama ada, cron produksi terbatas 3.000
  wallet/token; token ≤ 3.000 tidak terpengaruh, baseline + kronologi
  otomatis tetap jalan. Hapus flag itu dari workflow untuk FULL penuh.
  Perkiraan:
  55 token × 24 run/hari × holder aktual per token (order ribuan untuk
  token degen) via Helius DAS + market DexScreener; pantau durasi di log
  `durasi=<detik>` dan kuota Helius bila watchlist membesar.
- Baseline/kronologi: scan FULL pertama tiap token (setelah masuk
  watchlist) menulis `baseline` immutable + snapshot wallet; run berikutnya
  menambah interval kronologi (bounded: 24 interval / 400 wallet snapshot /
  40 movement per interval per token).
- `MIN_POINT_GAP_SEC` (8 menit) aman untuk run tiap jam: run ganda < 8 menit
  (schedule + `workflow_dispatch`) menimpa titik yang sama, bukan menambah.

Workflow memerlukan permission berikut:

```yaml
permissions:
  contents: write
```

Environment step scanner:

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.GH_TOKEN || secrets.GITHUB_TOKEN }}
  HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}
  HELIUS_API_KEYS: ${{ secrets.HELIUS_API_KEYS }}
  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

`HELIUS_API_KEY` wajib untuk hasil holder yang andal di Actions karena GMGN
sering memblokir runner. `GH_TOKEN` opsional bila token bawaan tidak memiliki
permission publish. Scanner exit non-zero bila semua token menghasilkan nol
holder atau publish status gagal.

## Setup Telegram

1. Buat bot melalui **@BotFather** dan salin token bot.
2. Tambahkan bot ke chat/grup tujuan. Untuk grup, pastikan bot dapat mengirim
   pesan.
3. Dapatkan chat ID, misalnya dari update bot (`getUpdates`) setelah mengirim
   pesan ke bot/grup. Chat ID grup biasanya bernilai negatif.
4. Di GitHub buka **Settings → Secrets and variables → Actions → New
   repository secret**, lalu simpan dua secret terpisah:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

Jangan menaruh nilainya di repository, workflow, log, `config.json`, atau
Streamlit source. Credential kosong/tidak valid tidak menghentikan scan;
pengiriman dilewati atau dicatat sebagai warning tanpa membocorkan token.

### Test pengiriman

Setelah kedua secret tersimpan, buka **Actions → Holder Dust Scanner → Run
workflow**, aktifkan input **Kirim test alert Telegram sebelum scan**, lalu
jalankan. Workflow meneruskan flag `--telegram-test` dan mengirim pesan yang
jelas bertanda `TEST ALERT HOLDER DUST`; pesan tersebut bukan sinyal token.

Untuk environment lokal yang sudah memiliki kedua environment variable:

```bash
python scripts/scan_holders.py --telegram-test --no-push
```

Perintah itu tetap melanjutkan scan normal setelah mencoba pesan test.

> GitHub App tertentu tidak bisa mengubah file workflow tanpa permission
> `workflows`. Jika push workflow ditolak, perubahan perlu diterapkan oleh
> pemilik repository dengan permission tersebut.
