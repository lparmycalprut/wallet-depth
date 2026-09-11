# Deploy

## Streamlit

- Entry point: `app.py`
- Python: lihat `runtime.txt`
- Dependencies: `requirements.txt`
- Secrets scanner utama: `HELIUS_API_KEY`/`HELIUS_API_KEYS` dan
  `GITHUB_TOKEN`.
- Secret holder Robinhood Chain: `BLOCKSCOUT_API_KEY` (Blockscout PRO API,
  key gratis di <https://dev.blockscout.com>). Tanpa key modul memakai
  instance publik `robinhoodchain.blockscout.com` yang sejak 2026-09-08
  sering menjawab **HTTP 403 bot-protection** untuk request server
  (Streamlit Cloud / runner Actions). Di Streamlit Cloud isi di
  **Secrets** (`BLOCKSCOUT_API_KEY = "proapi_…"`) atau
  `blockscout_api_key` di `config.json`. Punya lebih dari satu akun?
  `BLOCKSCOUT_API_KEYS = "proapi_1,proapi_2,…"` — dipakai bergantian,
  key yang kreditnya habis/ditolak diparkir otomatis (lihat langkah di
  bawah).
- Secrets alert Telegram opsional: `TELEGRAM_BOT_TOKEN` dan
  `TELEGRAM_CHAT_ID`. **Secret GitHub ≠ secret Streamlit** — cron
  Actions membaca yang pertama, scan manual di dashboard membaca yang
  kedua. Keduanya harus dipasang (lihat **Setup Telegram**).

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
lagu — slot 4 jam, catch-up, bootstrap, pembacaan toggle Telegram-nya, dan
semua rule lama (🔔 HIGH DROP, ⚡ EARLY DUMP, exit/aman) dilepas dari jalur
cron (scan manual di dashboard tetap ada; sejak 2026-09-11 kedua jalur memakai
satu-satunya rule 🚨 WAKTUNYA GANTI STRATEGI — dust ≥ 0,06% MC, diulang tiap
scan selama masih di atas ambang). Pencatatan ikut dirampingkan:
snapshot dipublish tanpa `merge_status`, toggle Telegram watchlist biasa tidak
dibaca lagi, dan backup durable dibatasi token LP aktif
(`publish_holder_history(..., keep_mints=…)` — terukur 2.135.084 → 10.050 byte
gzip pada store live). Kalau kuota Helius mulai ketat: set
`LP_SCAN_RUN_MULTIPLIER: "3"` di langkah scan (env, tanpa ubah kode) sehingga
scan Solana kembali ±15 menit sementara Robinhood LP tetap tiap run.
`timeout-minutes` sudah turun 45 → 15 menit di workflow terpasang
(scan ±1-2 menit + tidur chain ±5 menit) supaya run yang macet tidak menumpuk
antre di concurrency group `holder-scanner`.

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
> langkah "Chain run berikutnya" memanggil **`scripts/chain_next_run.py`**
> dengan dua rem — dispatch **dilewati** bila masih ada run workflow ini yang
> `queued`/`in_progress`/`waiting` (Guard 1), dan **dilewati** bila ada run
> lain yang selesai < `CHAIN_QUIET_SEC=240` detik lalu (Guard 2 — jendela
> WAJIB lebih kecil dari kadens, kalau tidak rantai mematikan dirinya
> sendiri). Run ganda yang tetap lolos disaring gate `MIN_RUN_GAP_SEC`
> (4 menit) di scanner dan keluar tanpa kerja.
>
> **Guard 2 lama adalah bug yang membuat cron mati berjam-jam** — terukur
> 2026-09-09: ia membandingkan umur run `event=schedule` terakhir dengan
> 900 detik dan menyimpulkan "schedule sehat", lalu **membuang** dispatch.
> Karena schedule saat itu baru menyala 4× sehari, setiap kejadian schedule
> hanya menghasilkan SATU run dispatch lalu hening: stall 01:40→06:41,
> 06:50→11:56, 12:05→16:30, 16:40→>17:41 UTC. Guard 2 sekarang memakai run
> terakhir **event apa pun**; rantai selalu tersambung lagi karena satu run
> selalu berumur ±320 detik (tidur sampai batas berikutnya) — selalu lebih
> tua dari jendela 240 s.
>
> Skrip juga **fail-open**: daftar run gagal dibaca (hiccup API/secondary
> rate limit) → guard dilewati, dispatch tetap dicoba. Versi bash lama jalan
> di bawah `bash -e`, jadi `ACTIVE=$(curl -sSf … | python3 -c …)` yang gagal
> membatalkan seluruh langkah tanpa dispatch — stall kedua dengan penyebab
> berbeda. Dispatch POST diulang sampai 4× (backoff 5/10/15 s; 400/401/404/422
> tidak diulang); kalau tetap gagal, langkah rantai `exit 1` supaya run
> ditandai **merah** dengan pesan "rantai TERPUTUS" alih-alih hijau tanpa
> penerus.

> **Berkas workflow tidak bisa ditulis bot — terverifikasi ulang 2026-09-07.**
> `git push` ke branch berisi perubahan `.github/workflows/daily-effort.yml`
> ditolak remote:
> `refusing to allow a GitHub App to create or update workflow
> .github/workflows/daily-effort.yml without 'workflows' permission`. Isi
> lengkap versi terbaru (lane LP + rantai via skrip + input `full_scan` +
> `timeout-minutes: 15`) ada di **`daily-effort-5menit.yml`** di root repo —
> salin lewat UI GitHub (Actions → Holder Dust Scanner → edit → timpa dari
> baris `name:` ke bawah → commit). Selama belum disalin: cron terpasang tetap
> jalan (dipanggil tanpa argumen = lane LP tiap run) TAPI dengan Guard 2 lama
> yang membuang dispatch → berisiko hening berjam-jam seperti 2026-09-09, dan
> `--scope all` dari input `scan_all` lama masih diterima sebagai alias
> `--full` (tidak crash).
>
> Menaruh logika rantai di skrip membuat 403 ini hanya menghalangi **satu**
> baris YAML: selama langkah "Chain run berikutnya" sudah memanggil
> `python scripts/chain_next_run.py`, semua kalibrasi ritme (kadens, jendela
> quiet, retry, guard) bisa diubah bot lewat commit biasa + test. Alternatif
> permanen: **Settings → Third-party Access → (app bot) → Repository
> permissions → Actions Workflows: Read & write**, setelah itu agent bisa
> memasang/mengubah workflow sendiri.
>
> **Cara memperlambat scan Solana saja** (kalau kuota Helius menipis, tanpa
> menyentuh kode): tambah env `LP_SCAN_RUN_MULTIPLIER: "3"` di langkah
> "Holder scan" → lane Meteora tiap 3 run (±15 menit), Robinhood LP tetap tiap
> run.
>
> **Cara mengembalikan SELURUH kadens ke 15 menit** (atau ke berapa pun):
> angka-angka ini harus bergerak bersamaan —
> `cron: "*/5 * * * *"` → `"*/15 * * * *"` **plus** env langkah "Chain run
> berikutnya" `CHAIN_CADENCE_SEC: "300"` → `"900"` (rumus tidur sekarang
> hidup di `scripts/chain_next_run.py:next_boundary_wait`, bukan lagi
> `WAIT=$((300 - NOW % 300 + 20))` di YAML), `RUN_SCAN_INTERVAL_SEC` (yang
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
> terukur **±2 jam** (contoh run: 18:02, 20:58, 22:57, 00:39 UTC), dan pada
> cron `*/5 * * * *` (2026-09-09) schedule hanya menghasilkan **4 run
> sehari** (01:35, 06:41, 11:56, 16:30 UTC) dari 288 yang tertulis di
> jadwalnya. Karena itu ritme 5 menit dipegang **chain dispatch** (tiap run
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
  BLOCKSCOUT_API_KEY: ${{ secrets.BLOCKSCOUT_API_KEY }}
  BLOCKSCOUT_API_KEYS: ${{ secrets.BLOCKSCOUT_API_KEYS }}
  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

`HELIUS_API_KEY` wajib untuk hasil holder yang andal di Actions karena GMGN
sering memblokir runner. `BLOCKSCOUT_API_KEY` sama pentingnya untuk lane
Robinhood LP: tanpa key, 403 bot-protection instance publik membuat semua
token Robinhood pulang 0 wallet (log Actions menulis `WARN: Blockscout
publik menolak scan …`; snapshot lama tidak ditimpa berkat gate
`holders_usable`). `GH_TOKEN` opsional bila token bawaan tidak memiliki
permission publish. Scanner exit non-zero bila semua token menghasilkan nol
holder atau publish status gagal.

## Setup key Blockscout PRO API (Robinhood Chain)

Satu key gratis = 100K kredit/hari & 5 RPS **per akun**; ±3 request per
token per scan (≈60–80 kredit) → 1 key cukup untuk ≤ 3–4 token LP Robinhood
pada kadens 5 menit. Lebih dari itu, atau token > 10.000 holder (paginasi
RPC), pasang beberapa key dari **akun berbeda**.

1. Buat key di <https://dev.blockscout.com> (Sign in → **API Keys** →
   *Create*; key `proapi_…` hanya ditampilkan sekali — salin saat itu juga).
   Ulangi di akun lain bila perlu lebih dari satu key.
2. **Streamlit Cloud** → aplikasi → ⋮ **Settings** → **Secrets** → tambahkan
   (format TOML, satu baris, key dipisah koma, tanpa spasi di dalam tanda
   kutip tidak masalah karena dibersihkan):

   ```toml
   BLOCKSCOUT_API_KEYS = "proapi_AAA,proapi_BBB,proapi_CCC,proapi_DDD"
   ```

   Klik **Save** — aplikasi restart otomatis. Cek: Scan Holder Khusus dengan
   CA Robinhood → caption *Blockscout (Robinhood Chain) · PRO API key#N*.
3. **GitHub** → repo → **Settings** → **Secrets and variables** → **Actions**
   → **New repository secret**: Name `BLOCKSCOUT_API_KEYS`, Secret =
   daftar key yang sama dipisah koma → **Add secret**.
4. Pastikan `.github/workflows/daily-effort.yml` meneruskan env
   `BLOCKSCOUT_API_KEYS: ${{ secrets.BLOCKSCOUT_API_KEYS }}` (sudah ada di
   `daily-effort-5menit.yml`; salin manual bila push bot ke folder workflow
   ditolak). Cek log run berikutnya: baris
   `Rencana scan Robinhood LP: … blockscout_pro_keys=4` dan
   `Blockscout PRO API: 4 key · key#1 sisa 99,800 kredit …`.

Jangan pernah menaruh key di `config.json` yang di-commit; `config.json`
ada di `.gitignore` hanya untuk pemakaian lokal.

## Setup Telegram

Dua runtime, dua tempat secret. Memasang di GitHub **tidak** membuat
dashboard Streamlit ikut bisa mengirim (dan sebaliknya). Butuh **keduanya**:
token bot **dan** chat ID — token saja = pesan
`Telegram credentials are not configured`.

1. Buat bot melalui **@BotFather** dan salin token bot.
2. Tambahkan bot ke chat/grup tujuan. Untuk grup, pastikan bot dapat mengirim
   pesan.
3. Dapatkan chat ID, misalnya dari update bot (`getUpdates`) setelah mengirim
   pesan ke bot/grup. Chat ID grup biasanya bernilai negatif.
4. **GitHub (cron / scan terjadwal)** → repo → **Settings → Secrets and
   variables → Actions → New repository secret**, dua secret terpisah:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. **Streamlit Cloud (scan manual di dashboard)** → aplikasi → ⋮
   **Settings → Secrets** → tambahkan (format TOML, nama key huruf besar
   atau kecil sama-sama dibaca):

   ```toml
   TELEGRAM_BOT_TOKEN = "123456:ABC-token-dari-BotFather"
   TELEGRAM_CHAT_ID = "-1001234567890"
   ```

   Klik **Save** — aplikasi restart otomatis. Tanpa langkah ini tombol scan
   manual menampilkan `1 alert GAGAL dikirim (Telegram credentials are not
   configured)` meski secret GitHub sudah terpasang.

Jangan menaruh nilainya di repository, workflow, log, `config.json` yang
di-commit, atau source Streamlit. Credential kosong/tidak valid tidak
menghentikan scan; pengiriman dilewati atau dicatat sebagai warning tanpa
membocorkan token.

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
