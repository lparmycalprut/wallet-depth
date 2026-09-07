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
berjalan **tiap ±5 menit** (`schedule: cron "*/5 * * * *"` + langkah **chain
dispatch**) dan memanggil `python scripts/scan_holders.py`. Sejak
**2026-09-07** scanner hanya mengerjakan **lane LP**: Chart LP Meteora
(Solana/Helius) + Robinhood LP (EVM/Blockscout), keduanya tiap run = ±5 menit.
Watchlist biasa (Solana non-LP & Robinhood `source=regular`) tidak di-scan cron
lagu — slot 4 jam, catch-up, bootstrap, dan rule 🔔 HIGH DROP dilepas dari
jalur cron (scan manual di dashboard tetap ada). Pencatatan ikut dirampingkan:
snapshot dipublish tanpa `merge_status`, toggle Telegram watchlist biasa tidak
dibaca lagi, dan backup durable dibatasi token LP aktif
(`publish_holder_history(..., keep_mints=…)` — terukur 2.135.084 → 10.050 byte
gzip pada store live). Kalau kuota Helius mulai ketat: set
`LP_SCAN_RUN_MULTIPLIER: "3"` di langkah scan (env, tanpa ubah kode) sehingga
scan Solana kembali ±15 menit sementara Robinhood LP tetap tiap run.
`timeout-minutes` job diusulkan turun 45 → 15 menit di `daily-effort-5menit.yml`
(scan ±1-2 menit + tidur chain ±5 menit) supaya run yang macet tidak menumpuk
antre di concurrency group `holder-scanner`; workflow terpasang masih 45.

> **Run "cancelled" dengan pesan `Canceling since a higher priority waiting
> request for holder-scanner exists` bukan prioritas lain.** Tidak ada workflow
> lain yang memakai concurrency group `holder-scanner` (satu-satunya workflow
> lain, `lp-safe-radar.yml`, statusnya `disabled_manually` dan berkasnya sudah
> tidak ada di `main` → 404 saat dibaca lewat API). Penyebabnya run dari
> workflow ini sendiri: GitHub hanya menahan **satu** run mengantre per
> concurrency group, jadi saat chain dispatch + `schedule */5` (+ dispatch
> manual) menghasilkan request ketiga, run yang sedang mengantre dibatalkan
> dengan pesan itu. Contoh nyata 2026-09-07: run 34092534104 dibuat 06:49:20
> UTC lalu `conclusion: cancelled` pada 06:50:23 UTC **tanpa punya job sama
> sekali** (API `/actions/runs/34092534104/jobs` → `total_count: 0`), dua detik
> sesudah run 34092608329 dibuat 06:50:21 UTC — persis pola "yang mengantre
> ditendang request lebih baru".
>
> Perbaikannya ada di **`daily-effort-5menit.yml`** (menunggu disalin ke
> `.github/workflows/daily-effort.yml` lewat UI — lihat catatan 403 di bawah):
> langkah "Chain run berikutnya" dapat dua rem — dispatch **dilewati** bila
> masih ada run workflow ini yang `queued`/`in_progress`/`waiting`, dan
> **dilewati** juga bila schedule `*/5` terbukti sehat (run `event=schedule`
> terakhir < 15 menit) — jadi chain hanya menambal saat schedule di-throttle.
> Run ganda yang tetap lolos disaring gate `MIN_RUN_GAP_SEC` (4 menit) di
> scanner dan keluar tanpa kerja.

> **Berkas workflow tidak bisa ditulis bot — terverifikasi ulang 2026-09-07.**
> `git push` ke branch berisi perubahan `.github/workflows/daily-effort.yml`
> ditolak remote:
> `refusing to allow a GitHub App to create or update workflow
> .github/workflows/daily-effort.yml without 'workflows' permission`. Isi
> lengkap versi terbaru (lane LP + dua rem chain dispatch + input `full_scan` +
> `timeout-minutes: 15`) ada di **`daily-effort-5menit.yml`** di root repo —
> salin lewat UI GitHub (Actions → Holder Dust Scanner → edit → timpa dari
> baris `name:` ke bawah → commit). Selama belum disalin: cron terpasang tetap
> jalan normal (dipanggil tanpa argumen = lane LP tiap run), `--scope all` dari
> input `scan_all` masih diterima sebagai alias `--full` (tidak crash), hanya
> rem anti-tabrakan antrean yang belum aktif.
>
> **Cara memperlambat scan Solana saja** (kalau kuota Helius menipis, tanpa
> menyentuh kode): tambah env `LP_SCAN_RUN_MULTIPLIER: "3"` di langkah
> "Holder scan" → lane Meteora tiap 3 run (±15 menit), Robinhood LP tetap tiap
> run.
>
> **Cara mengembalikan SELURUH kadens ke 15 menit** (atau ke berapa pun):
> angka-angka ini harus bergerak bersamaan —
> `WAIT=$((300 - NOW % 300 + 20))` → `900` di langkah "Chain run berikutnya",
> `cron: "*/5 * * * *"` → `"*/15 * * * *"`, `RUN_SCAN_INTERVAL_SEC` (yang
> menurunkan `RH_FAST_SCAN_INTERVAL_SEC` / `METEORA_LP_SCAN_INTERVAL_SEC`) dan
> `MIN_RUN_GAP_SEC` di `scripts/scan_holders.py` (gate run
> ganda wajib **lebih kecil** dari kadens run), dan `holder_history.MAX_POINTS`
> kembali ke 336 kalau densitas titik juga ikut melambat (1008 titik @ 15 menit
> = 10,5 hari). `holder_history.MIN_POINT_GAP_SEC` aman dibiarkan 4 menit —
> yang berbahaya justru kalau ia Naik sampai ≥ kadens run: titik tiap run saling
> menimpa dan history berhenti tumbuh. Beban Actions ±288 run/hari
> (repo publik = menit Actions gratis; tiap run ±5 menit sebagian besar tidur
> di langkah chain).

> **Schedule GitHub bersifat best-effort, bukan SLA.** GitHub bisa
> men-throttle / melewatkan schedule: pada cron `*/15 * * * *` kadens nyata
> terukur **±2 jam** (contoh run: 18:02, 20:58, 22:57, 00:39 UTC), bukan 15
> menit. Karena itu ritme 5 menit dipegang **chain dispatch** (tiap run
> men-dispatch run berikutnya setelah tidur sampai batas berikutnya) dan
> schedule hanya jaring pengaman. Artinya "5 menit" tetap **target**, bukan
> janji — alert bucket 4 jam, titik per 4 jam, dan cooldown 1 jam dirancang
> toleran terhadap run yang telat/dilewati; pengingat ⚡ lane LP sengaja tidak
> ikut dipercepat (bucket `FAST_BUCKET_SEC` tetap 15 menit per token).
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

1. Analisis per token **lane LP**: holder Helius DAS untuk Chart LP Meteora
   (fallback GMGN) dan Blockscout untuk Robinhood LP (`--max-wallets 3000`
   dikirim workflow; default modul 100.000), klasifikasi real (>$10) vs dust,
   `dust_pct_mc`, mid-tier. Cron memakai `detail=False` (titik holder +
   alert ⚡ saja); baseline immutable + kronologi wallet hanya ditulis scan
   FULL manual (`--full`).
2. Evaluasi alert terhadap snapshot lama **sebelum** snapshot terbaru
   ditulis. Snapshot wallet disimpan secara bounded di history/status.
3. Publish `holder_status.json` ke branch `holder-live` (dibuat otomatis
   pada publish pertama) agar dashboard dan cron memakai state yang sama —
   **tanpa** `merge_status` sejak 2026-09-07 (tidak ada baris token watchlist
   biasa yang perlu diwariskan). Snapshot ramping: peta balance alert /
   kohort / wallet kronologi tidak ikut (hanya jumlah + sampel movements) —
   2,87 MB → 0,30 MB untuk 36 token (−90%), jadi dashboard memuat jauh lebih
   ringan.
4. Backup store sebagai `holder_history.json.gz` (gzip, ref `holder-live`)
   lewat `holder_history.publish_holder_history(..., keep_mints=watchlist LP)`
   — state alert, kohort, dan titik grafik bertahan walau runner ephemeral,
   tanpa menyeret token watchlist lama (lihat bullet ukuran repo di bawah).
   Run berikutnya mem-pull + `merge_stores()` **sebelum** evaluasi alert
   (langkah 2), jadi cron tidak pernah mulai dari nol. Backup gagal hanya
   `WARN` (`backup=GAGAL (...)` di log), exit code tetap dari publish
   snapshot. `--no-push` melewati keduanya.

Cadence (2026-09-04 hourly → 2026-09-05 LP 15 menit → 2026-09-06 run 5 menit:
pertama khusus lane Robinhood, lalu hari yang kedua untuk KEDUA lane LP) dan
ukuran ref `holder-live`:

- `MAX_POINTS = 1008` — densitas titik riwayat mengikuti kadens run, jadi
  batasnya ikut dikalibrasi. Sejak kedua lane LP di-scan tiap 5 menit, batas
  lama 336 (= 14 hari × 24 titik/jam di era hourly) cuma bertahan **28 jam**
  dan grafik bucket 4 jam menyusut 3×; 1008 titik @ 5 menit = ±3,5 hari =
  **21 bucket 4 jam**, persis jendela yang dulu dihasilkan 336 titik @ 15
  menit. Lane biasa (6 titik/hari) tidak terpengaruh. Grafik UI tetap
  memakai `resample_4h` (bucket 4 jam, ≤ 84 titik), jadi snapshot dashboard
  tidak ikut membengkak; store mentah yang membesar dibackup terkompresi
  gzip. Terukur dengan store sintetis 55 token × 336 titik per jam:
  backup ~**1,03 MB** (batas `MAX_BACKUP_BYTES` 3,5 MB); varian dengan 10
  token LP @ 1008 titik 5 menit menghasilkan **0,33 MB** untuk 10 token LP itu
  (vs 0,25 MB @ 336 titik 15 menit) — jauh di bawah budget, dan tangga prune
  backup tetap merapatkan store ke 42 bucket 4 jam kalau suatu saat melewati
  `MAX_BACKUP_BYTES`. Estimasi
  pertumbuhan ~**±633 kB × 24 run/hari ≈ 15 MB/hari** isi Git bila tiap run
  mengganti blob (bandingkan ±7,6 MB/hari pada kadens 2 jam; git menyimpan
  delta antar commit, nilai sesungguhnya lebih kecil).
- Ukuran repo `holder-live`: tiap run menulis DUA commit (`holder-status:` +
  `holder-history:`), jadi kadens 5 menit = ±576 commit/hari. Sejak
  **2026-09-07** blob `holder_history.json.gz` dibatasi token LP aktif
  (`keep_mints`), jadi ukurannya mengikuti jumlah token watchlist LP, bukan
  akumulasi token lama: pada store live 81 token (1 token LP aktif) payload
  turun **2.135.084 → 10.050 byte** per commit. Snapshot
  `holder_status.json` tetap tiap run. Bila suatu saat blob LP membesar lagi,
  tangga `prune_store_for_backup()` (batas `MAX_BACKUP_BYTES` 3,5 MB) tetap
  bekerja seperti sebelumnya.
- Kuota holder: sejak 2026-09-05 cron scan **FULL** (bukan sampel 3000):
  token yang punya ≤ 3000 holder tidak berubah biayanya, token lebih besar
  ikut semua halamannya (default `--max-wallets` = 100.000 = batas atas
  aman). **Catatan:** baris workflow yang masih mengirim
  `--max-wallets 3000` belum bisa dihapus lewat bot (butuh izin
  `workflows` di repo) — selama ada, cron produksi terbatas 3.000
  wallet/token; token ≤ 3.000 tidak terpengaruh, baseline + kronologi
  otomatis tetap jalan. Hapus flag itu dari workflow untuk FULL penuh.
  Perkiraan:
  token LP × 288 run/hari (kedua chain) + token biasa × 6 run/hari, holder
  aktual per token (order ribuan untuk token degen) via Helius DAS + market
  DexScreener; pantau durasi di log `durasi=<detik>` dan kuota Helius bila
  watchlist membesar — katupnya `LP_SCAN_RUN_MULTIPLIER` atau
  `--max-wallets` yang lebih kecil.
- Baseline/kronologi: scan FULL pertama tiap token (setelah masuk
  watchlist) menulis `baseline` immutable + snapshot wallet; run berikutnya
  menambah interval kronologi (bounded: 24 interval / 400 wallet snapshot /
  40 movement per interval per token).
- `MIN_POINT_GAP_SEC` (4 menit sejak 2026-09-06; dulu 8 menit) adalah ambang
  "run ganda": titik yang lebih muda dari itu ditimpa, bukan ditambahkan.
  Nilainya harus berada di antara `MIN_RUN_GAP_SEC` (4 menit) dan kadens run
  tercepat (5 menit) — di luar rentang itu history salah satu lane berhenti
  tumbuh (`tests/test_holder_history.py::FiveMinuteCadenceTest` mengunci ini).
  Konsekuensi lain: store mentah lane 5 menit menyimpan `MAX_POINTS` titik
  (= 1008 ≈ ±3,5 hari sejak 2026-09-06); grafik 4 jam & snapshot dashboard
  tetap ≤ 84 bucket karena memakai `resample_4h`.

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
