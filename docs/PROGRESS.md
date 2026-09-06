# Progress

## 2026-09-06 (pagi): ✕ watchlist dibebaskan dari GitHub + fetch Robinhood 5 menit

Permintaan user: *"perbaiki juga hapus dari watchlist robinhood, kurang
responsif, lalu percepat fetch untuk watchlist robinhood menjadi 5 menit
sekali."*

### Masalah (dibuktikan lewat script, bukan asumsi)

- **Klik ✕ menahan seluruh rerun Streamlit.** Skrip pengukuran (stub
  `requests.get/put` dengan RTT 0,8 dtk — angka konservatif, API nyata sering
  lebih lambat) mencatat **2,40 s** per satu penghapusan dan **3 round-trip
  HTTP di jalur klik**: `remove_from_watchlist()` → `_load_and_merge()` menarik
  remote lewat `_github_pull` (3 percobaan GET × timeout 10 dtk: API bertoken,
  API tanpa token, raw CDN) → `save_watchlist()` → `_github_push()`
  (GET sha + PUT, 3 percobaan × timeout 15 dtk + backoff). Rantai yang sama
  ada di setiap tombol watchlist (➕/✕/📋/⚡) di kedua jaringan; worst case
  saat API macet ±2 menit, dan setiap render ulang ikut mencoba flush journal
  yang belum ter-commit → keluhan "kurang responsif" bukan persepsi.
- **Kadens lama tidak bisa dinaikkan begitu saja.** `scripts/scan_holders.py`
  hanya punya satu jalur cepat (`FAST_SCAN_INTERVAL_SEC` 15 menit) yang
  dipakai bersama Chart LP Meteora **dan** Robinhood LP, dan gate run ganda
  `MIN_RUN_GAP_SEC = FAST − 60` (14 menit) dibaca dari umur snapshot. Menurun-
  kan `FAST` ke 5 menit tanpa menyentuh gate itu membuat **semua** lane
  dibungkam: run berikutnya selalu melihat snapshot berumur 5 menit < 14 menit
  → "Scan dilewati". Lane Solana juga ikut naik 3× (Helius, kuota holder
  100.000 wallet/scan) yang tidak diminta user.
- **Bug tersembunyi di `holder_history.MIN_POINT_GAP_SEC` (8 menit).** Titik
  yang lebih muda dari ambang itu **ditimpa**, bukan ditambahkan (dulu untuk
  membuang run ganda). Dengan run tiap 5 menit, history lane Robinhood tidak
  akan pernah punya lebih dari satu titik: sparkline, Δ 4 jam, dan titik acuan
  rule diam di tempat.

### Perbaikan

1. **Mutasi watchlist jadi non-blocking** (`watchlist.py`). Semua jalur UI
   meneruskan `background=True`: state dibaca lokal
   (`_load_and_merge(local_first=True)`, nol HTTP) → journal + tulis file
   lokal → `_seed_remote_cache()` (render berikutnya tidak pull; TTL load
   watchlist 15 → 60 dtk) → commit GitHub di thread daemon
   `_queue_github_push` (satu worker per file, job terbaru menimpa job lama →
   klik beruntun jadi satu commit) → journal dipangkas **hanya** setelah
   commit sukses. `load_watchlist()` melewati flush inline selama
   `push_inflight()` benar (tidak balap 409), dan dispatch scan
   `request_immediate_scan()` pindah ke `dispatch_scan_async()` (thread + rem
   10 dtk). Default library tetap `background=False` untuk cron/skrip. Setelah:
   **1,4 ms** klik + 0,9 ms render, 0 HTTP di jalur klik. Kepala card
   Robinhood menampilkan badge `🔄 sinkron…` / `⚠️ belum sinkron`
   (`watchlist.push_status()`), jadi state "belum ter-commit" tidak diam-diam.
2. **Kadens per lane, bukan per cron** (`scripts/scan_holders.py`):
   `RUN_SCAN_INTERVAL_SEC = RH_FAST_SCAN_INTERVAL_SEC = 5 menit`,
   `METEORA_LP_SCAN_INTERVAL_SEC = 15 menit` dengan gate slot baru
   `lp_slot_due(now, snapshot.updated_at)` (berbasis *nomor slot*, bukan umur
   titik: run yang terlewat/gagal tetap mengerjakan LP di run berikutnya, dan
   dua run dalam satu slot tidak mengulang scan), `REGULAR_SLOTS` 16 → 48,
   `MIN_RUN_GAP_SEC` 840 → **240 dtk**. Robinhood LP di-scan tiap run;
   `--scope fast|all` tetap melewati semua gate.
3. **Workflow belum terpasang — dan tidak akan pernah bisa dari sisi bot.**
   Target: `schedule: "*/5 * * * *"` + chain dispatch
   `WAIT=$((300 - NOW % 300 + 20))` (sebelumnya 900). Percobaan push
   (`git push`) dan `PUT /contents/.github/workflows/daily-effort.yml`
   sama-sama ditolak GitHub: `403 refusing to allow a GitHub App to create or
   update workflow … without "workflows" permission`. Isi lengkapnya karena itu
   disimpan di root repo sebagai **`daily-effort-5menit.yml`** (bukan workflow
   aktif) untuk disalin manual. Beban setelah dipasang: ±288 run/hari; repo
   publik jadi menit Actions tidak berkuota, dan run di luar slot LP praktis
   nol kerja (lihat `Rencana scan: … slot_lp=bukan`).
4. **Titik per 5 menit disimpan**: `MIN_POINT_GAP_SEC` 8 → **4 menit**,
   dikunci tes di antara `MIN_RUN_GAP_SEC` dan kadens run.
5. **Alert tidak ikut berlipat 3×**: bucket pengingat ⚡
   (`telegram_alerts.FAST_BUCKET_SEC` + `EARLY_DUMP_RESEND_SEC`) sengaja tetap
   **15 menit per token** — fetch lebih sering, notifikasi tidak. Teks pesan
   kini berbunyi "pengingat berulang (dibatasi ±15 menit per token)".
6. **Bug silang jaringan di `_github_push` diperbaiki sekalian.** Merge
   lost-update selalu membaca jurnal Solana (`_load_pending()` tanpa path)
   padahal fungsi yang sama dipakai `watchlist_robinhood.json` **dan**
   `holder_status*.json` — op `add` tertunda di satu jaringan bisa masuk ke
   payload file jaringan lain. Sekarang `_github_push(..., pending_path=…)`
   membaca jurnal milik file yang ditulis, dan publish snapshot mengirim
   `merge_journal=False`. Tulis-baca jurnal juga dilindungi `_JOURNAL_LOCK`
   supaya prune dari worker latar belakang tidak menghapus op yang baru saja
   ditulis thread UI.
7. **Teks UI ikut kadens baru**: label radio "🦅 Robinhood LP (scan ±5
   menit)", `chain_note` baris "LP · scan ±5 menit", caption card RH, help
   tombol ⚡, dan caption "Cadens cron" (Chart LP Meteora tetap tertulis
   ±15 menit).

### Catatan operasional

- **Yang masih manual:** `.github/workflows/daily-effort.yml` (403 — lihat
  poin 3). Salin `daily-effort-5menit.yml` ke path itu lewat UI GitHub; yang
  harus sama hanya `*/5` di `schedule` dan `300` di `WAIT`.
- Untuk mengembalikan kadens ke 15 menit: `WAIT` 300 → 900, `*/5` → `*/15`,
  `RUN_SCAN_INTERVAL_SEC`/`RH_FAST_SCAN_INTERVAL_SEC` → 900,
  `MIN_RUN_GAP_SEC` → 840, dan `MIN_POINT_GAP_SEC` > 900 tidak perlu —
  biarkan 240 (ambang titik hanya boleh ≥ `MIN_RUN_GAP_SEC`). DEPLOY.md
  mencatat rumus invariannya.
- Load Blockscout naik 3× pada lane Robinhood (±30 halaman holder/token per
  run, `--max-wallets 3000` masih dipatok di workflow). Client sudah
  backoff 3 dtk untuk 429; kalau mulai sering, turunkan `--max-wallets`.
- Store mentah lane 5 menit hanya menyimpan `MAX_POINTS` 336 titik ≈ 28 jam
  (Solana tetap ±14 hari). Grafik 4 jam dan snapshot dashboard tidak berubah
  karena keduanya memakai `resample_4h` (84 bucket).

### Tes

`tests/test_watchlist_background_push.py` (10 uji: nol HTTP + nol blocking di
jalur klik, commit selesai → journal bersih, gagal → journal + `state=error`,
coalescing, jalur sinkron lama tidak berubah, simbol di pesan commit,
`push_status`/`push_inflight` per file, flush tidak dobel, rem dispatch),
`ScanCadenceTest` di `tests/test_scan_holders.py` (7: konstanta + invarian
gate, `regular_slot_due` di batas 4 jam, `lp_slot_due`, `build_scan_plan`
dengan/`tanpa slot`, dan tiga integrasi `main()` dengan jam tersumbat —
tengah slot hanya Robinhood yang scan, slot LP ikut Solana, run ganda
membungkam semuanya), `FiveMinuteCadenceTest` di `tests/test_holder_history.py`
(3), dan 5 uji UI di `tests/test_rh_card_ui.py` (✕/📋 wajib
`background=True`, caption ±5 menit, badge sinkron). Assert kwargs lama
di-perbarui di `tests/test_lp_card_ui.py` + `tests/test_robinhood_watchlist.py`
(flag diteruskan + `sync_state`), dan `GithubPushJournalIsolationTest`
(isolasi jurnal per file + `merge_journal=False`).
Suite: **824 passed** `pytest -q` **dan** `unittest discover -s tests -t .`
(sebelumnya 794).

## 2026-09-06 (malam): tautan 🧮 Holder Analytic tidak pernah sampai ke halamannya

Laporan user: menempel
`https://…streamlit.app/~/+/pages/5_🧮_Holder.py?mint=0x1a3876…` dengan
keterangan *"belum berfungsi"*.

### Masalah (dibuktikan lewat script, bukan asumsi)

- `links.holder_analytic_link_html` membuat href `pages/5_🧮_Holder.py?mint=…`.
  Streamlit **tidak** melayani file di `pages/` lewat path file. Registry
  runtime app ini (dibaca langsung dari websocket `/_stcore/stream`) berisi
  `url_pathname`: `CVD`, `Holder`, `Deteksi_Akumulasi`, `Pre-Pump`, dan
  frontend mencocokkan URL dengan
  `pathname.endsWith('/' + url_pathname)` (case-sensitive). Path file tidak
  cocok dengan halaman mana pun → Streamlit menampilkan "Page not found" dan
  menjalankan **halaman utama**, sehingga `?mint=` tidak pernah dibaca
  halaman Holder.
- Efek yang sama terlihat di test: `tests/test_rh_card_ui.py` sudah merah di
  HEAD (aksi 🧮 pernah jadi tombol `st.switch_page`, lalu diganti anchor tanpa
  target yang benar).
- Data holder Robinhood Chain ikut diperiksa karena baris Onboard/VLAD
  menampilkan dust 0: snapshot `holder_status_robinhood.json` di ref
  `holder-live` (dibaca 2026-09-06 ±01:00 UTC) berisi
  `total_fetched: 0, wallets_analyzed: 0, dust_count: 0, dust_pct_mc: 0.0`
  untuk kedua token. Penyebabnya: error provider ditelan
  `classify_holders` sehingga **scan gagal terbaca seperti hasil sungguhan**,
  dan blok Robinhood — tidak seperti jalur Solana — mempublikasikan apa pun
  tanpa saringan `holders_usable`.

### Perbaikan

1. **Slug halaman, bukan path file.** `links.page_url_path()` menghitung path
   URL dengan aturan Streamlit sendiri (`source_util.page_icon_and_name`,
   fallback lokal identik bila streamlit tidak terimpor), `links.base_url_path()`
   menghormati `server.baseUrlPath`, dan `links.holder_analytic_url()`
   mengembalikan `/Holder?mint=<ca>` — root-absolute sehingga tidak patah saat
   dibuka dari halaman lain. `holder_analytic_link_html` sekarang memakainya.
2. **`page_router.py` (baru)** + `page_router.apply()` di awal `app.py`:
   `mint|ca|token|address` (dan `page=<slug|nomor|nama file|path>`) yang
   mendarat di halaman utama dipantulkan ke halaman yang benar lewat
   `st.switch_page(page, query_params={"mint": …})`. Tautan lama yang sudah
   tersebar — termasuk URL yang ditempel user — ikut pulih. CA wajib lolos
   format (base58 Solana / `0x`+40 hex) supaya nilai sampah tidak membajak
   navigasi, dan penanda di `st.session_state` mencegah pantulan berulang
   ketika user sengaja kembali ke dashboard membawa `?mint=`.
3. **Robinhood Chain tidak lagi berbohong.** `_jsjson` mengulang error
   sementara (429/5xx/timeout) satu kali dengan jeda; `fetch_token_info`
   melempar bila Blockscout membalas `status: "0"` (rate limit) alih-alih
   diam-diam mengembalikan `decimals: -1`; `fetch_holders` menyalin alasan
   kegagalan ke `error`, dan `analyze_token` menempelnya sebagai
   `holders.fetch_error`. `robinhood_watchlist.publish_scan` menyaring
   analisis yang tidak layak (`holder_history.holders_usable`) dari snapshot —
   aturan yang sama dengan cron Solana — sambil tetap mencatat titiknya di
   history (ditandai `degraded`) supaya jejak "scan gagal" tidak hilang.
   Baris card RH menulis **"⚠️ scan terakhir tidak lengkap (…)"**, bukan
   "dust 0,00% MC" yang terbaca AMAN.
4. **Halaman Holder** menampilkan alasan provider pada peringatan scan pendek
   (`Scan holder terakhir tidak lengkap: … Alasan provider: …`).

### Catatan operasional

`holder_history_robinhood.json`/`holder_status_robinhood.json` tidak ada di
repo (gitignored, hidup di ref `holder-live`), jadi titik grafik Onboard baru
muncul setelah 2 bucket 4 jam terisi oleh cron — tombol **🔄 Scan holder FULL
token ini** di halaman Holder mengisi titik pertama sekarang juga.

### Tes

`tests/test_page_router.py` (13 uji: resolusi alias, validasi CA, AppTest
pantulan dari halaman utama), `HolderDeepLinkTest` di `tests/test_links.py`
(slug == `page_icon_and_name` untuk **semua** file di `pages/`, encoding,
`baseUrlPath`), `ProviderFailureTest` di `tests/test_robinhood_watchlist.py`,
guard publish + pesan baris di `tests/test_rh_card_ui.py`.
Suite: **794 passed** (sebelumnya 758 passed + 2 failed).

## 2026-09-06 (sore): scan holder dari halaman utama tidak menimpa data tercatat

Laporan: *"ketika saya scan dari main app page, jangan timpa data awal yang
sudah tercatat, tapi update holder list terbaru sesuai time snapshot."*

### Masalah (dibuktikan lewat script, bukan asumsi)

Tombol **"🔄 Scan holder watchlist"** di `app.py` memanggil
`publish_holder_status(analyses, …)` dengan `analyses` = token yang **berhasil
di-scan** saja. `snapshot_status` membangun `tokens` hanya dari analyses yang
diberikan, lalu `publish_holder_status` menulis file dan mengganti
`holder_status._CACHE`. Akibatnya:

- token yang **gagal / timeout** pada run itu **hilang dari snapshot** →
  dashboard kehilangan baris + nilai terakhir yang sudah tercatat;
- scan **tidak lengkap** ikut di-publish → nilai 0,00% palsu menimpa angka
  yang benar (bagian dari bug −100%);
- tombol **Robinhood** (`robinhood_watchlist.publish_scan`) sama, tanpa merge.

### Perbaikan

- **Merge, bukan ganti.** `publish_holder_status(…, merge_status=holder_status)`
  (dan `merge_status=rh_status` untuk tombol Robinhood): token yang tidak ikut
  scan run ini tetap memakai snapshot-nya. Scan jadi *update per token*, bukan
  penggantian massal.
- **Hanya scan layak yang masuk.** Analyses di-filter `holders_usable` sebelum
  `ingest_many` dan sebelum publish → scan pendek (provider mengembalikan
  sampel) tidak menulis apa pun; angka lama dipertahankan dan token itu
  dilaporkan sebagai "dilewati".
- **Data awal tidak disentuh.** `ingest_many(fresh, store=…)` tetap
  `detail=False`: baseline scan FULL, `latest_detail`, dan kronologi tidak
  pernah ditimpa scan dari halaman utama (sudah didokumentasikan di
  `holder_history._ingest_full_detail`, sekarang benar-benar dijaga).
- **Laporan setelah scan** (`st.session_state["watchlist_scan_report"]` +
  `st.info`): `N token diperbarui · K token tetap memakai data yang sudah
  tercatat · F scan gagal · S scan tidak lengkap dilewati (ticker) · list
  holder diperbarui sampai snapshot <waktu>`, ditutup "Baseline scan FULL,
  latest detail, dan kronologi tidak ditimpa".

### Waktu snapshot per token

- `watchlist_detail.sync_summary` menambah `latest_count` / `older_count`
  (berapa token yang benar-benar duduk di waktu snapshot terbaru vs masih di
  snapshot sebelumnya) dan caption membacanya:
  `Scan terakhir: **06 Sep 03:01 WIB** (36 token) · 41 token masih di snapshot
  sebelumnya — waktu tiap baris ada di kolom scan`. Satu angka "Scan terakhir"
  saja menyesatkan kalau sebagian baris belum ter-update run terakhir.
- Tooltip **"Sejak masuk"** kini menyebut ujung window-nya:
  `dari 1,00% (23,45 hari lalu, 05 Sep 03:01 WIB) ke 0,50% (1,00 hari lalu,
  sampai snapshot 06 Sep 03:01 WIB)` → jelas angka itu snapshot **kapan**.

### Yang **tidak** berubah

Scan manual tetap memakai analisis SAMPLE, jadi ia hanya menambah titik baru
di atas kronologi yang sudah ada; scan FULL tetap lewat
`pages/5_🧮_Holder.py` / cron, dan tombol manual tetap menulis lokal
(`push=False`) seperti sebelumnya.

### Verifikasi

`tests/test_watchlist_manual_scan.py` (6 AppTest, token GOOD/FAILS/SHORT):
token gagal **bertahan** di snapshot, scan pendek **tidak** di-publish dan
**tidak** masuk history, baseline/`latest_detail` tidak tersentuh, laporan
menyebut jumlah + ticker + waktu snapshot. Di `HEAD` sebelumnya 4 dari tes itu
**gagal**. `SnapshotTimeReportingTest` (3 tes) untuk summary/caption/tooltip.
Suite penuh **760 passed** (`pytest tests -q`); replay data produksi tetap
0 exception.

---


## 2026-09-06 — Watchlist: scan holder tidak lengkap tidak lagi terbaca "−100%"

**Laporan user**: "Perbaiki tampilan data watchlist, banyak yang jadi −100%
padahal cron sudah terjadi beberapa kali."

### Diagnosis (dipakai data produksi sungguhan, ref `holder-live`)

Bukan bug perhitungan perubahan. Dari 79 token watchlist Solana:

| Gejala | Sebelum | Sesudah |
|---|---|---|
| Baris **Sejak masuk** = −100,0% | **34** | **0** |
| Snapshot cron dengan holder tidak layak | 43 dari 79 | tetap 43 (datanya), tapi tidak lagi ditampilkan sebagai angka |
| Titik history yang dibuang dari grafik/angka | — | 190 dari 633 |
| Baris tanpa pembanding layak | 0 (semua "punya angka") | 2 (jujur menulis *belum ada data ⚠️*) |

Penyebabnya **data**, bukan rumus: scan terakhir puluhan token cuma mengambil
**20 holder**. Helius gagal (rate limit) → fallback GMGN mengembalikan satu
halaman pendek dengan `truncated: False` (`total_fetched: 20`,
`wallets_analyzed: 19`, `source: gmgn`). Wallet dust (nilai ≤ $10) berada di
**ekor** daftar holder, jadi sampel sependek itu selalu berisi
`dust_count 0` / `dust_pct_mc 0.0`, dan kolom **Sejak masuk** menghitung
`(0 − 2,68) / 2,68 = −100%` — hijau, seolah dust habis keluar padahal tidak ada
transaksi. Snapshot `holder_status.json` membawa angka yang sama, jadi kolom
**Hold %MC** ikut menampilkan `0,00%` + badge **AMAN**.

### Perbaikan

1. **Lantai kelayakan data holder** (`holder_history`): `MIN_USABLE_WALLETS`
   (40, sama dengan guard BEST POOL) + `scan_degraded()` /
   `holders_usable()` / `point_wallets()` / `point_usable()` /
   `usable_points()`. Aturan: `total_fetched < 40` atau jumlah wallet
   dianalisis `< 40` = **tidak layak**; dict tanpa bukti jumlah wallet sama
   sekali (snapshot skema lama/fixture) **tidak** ditolak, jadi perilaku lama
   tidak berubah. Titik hasil scan tidak lengkap ditandai `degraded: True`
   saat `ingest_one` (penanda ikut lewat `compact_point` → `resample_4h` →
   snapshot).
2. **`watchlist_detail.resolve_view()`** memilih nilai **layak** terbaru,
   bukan sekadar terbaru: snapshot/titik dari scan pendek tidak pernah jadi
   angka baris; hasil membawa `degraded`, `degraded_ts`, `degraded_wallets`,
   `degraded_note`, `usable_points`, `skipped_scans`. `drift` hanya dihitung
   bila snapshot layak. `anchor_point()` juga melewati titik tidak layak
   supaya nilai awal "sejak masuk" tidak ikut rusak.
3. **UI** (`app.py`): baris memakai scan layak terakhir, sub-baris waktu
   scan menulis `⚠️ scan 06 Sep 03:00 WIB cuma 19 wallet`, kolom **Sejak
   masuk** diberi penanda ⚠️ (dan `belum ada data ⚠️` + alasan di tooltip
   bila belum ada satu pun scan layak), sparkline + pembanding badge hanya
   digambar dari titik layak, dan `sync_caption_text()` menghitung berapa
   token yang scan terakhirnya tidak lengkap. Card **Chart LP**
   (`lp_watchlist.build_lp_row` + grafik/overlay) memakai aturan yang sama.
4. **Halaman Holder Analytic** (`pages/5_🧮_Holder.py`): kartu metrik jatuh
   ke titik history layak terakhir dan menampilkan peringatan "scan holder
   terakhir tidak lengkap (19 wallet)" alih-alih menyajikan `Dust 0 / 0,00%`
   sebagai fakta.
5. **Alert**: `telegram_alerts.process_holder_alerts()` melewatkan scan yang
   holder-nya tidak layak (guard lama hanya menolak `total_fetched <= 0`).
   Tanpa ini, setiap run dengan sampel pendek akan membaca "dust turun 100%
   dari titik high" dan mengirim 🔔 HIGH DROP palsu.

### Yang **tidak** diubah (dan kenapa)

- `full_scan_usable()` tetap hanya menolak `total_fetched <= 0`: baseline /
  `latest_detail` / kronologi masih ditulis untuk scan pendek. Menyamakan
  ambangnya akan mengubah arti fixture scan kecil yang sudah ada
  (mis. `wallets_analyzed: 14` di `tests/test_holder_history.py`). Konsekuensi
  yang diketahui: Δ bucket vs baseline di halaman Holder bisa menyesatkan
  tepat setelah scan pendek — titiknya sudah ditandai `degraded`, jadi guard
  bisa dipasang kemudian tanpa mengubah skema.
- Sumber masalahnya (Helius rate limit → GMGN satu halaman) tidak disentuh di
  layer fetch. Selama provider mengembalikan sampel pendek, run berikutnya
  tetap mencoba; UI hanya berhenti mengklaim angka yang tidak terbukti.

**Tes**: 751 lulus (26 tes baru: 9 `DegradedScanTest` di
`tests/test_watchlist_detail.py`, 8 `HolderDataUsabilityTest` di
`tests/test_holder_history.py`, 2 alert di `tests/test_high_drop.py`,
5 AppTest `tests/test_watchlist_degraded_scan.py`, 2 AppTest halaman Holder).
Verifikasi tambahan: `app.py` dijalankan lewat `AppTest` dengan **snapshot +
store produksi asli** (79 token, 2,7 MB / 3,4 MB gzip) — 0 exception, 0
kemunculan `−100.0%`.

## 2026-09-05 (kedua) — Notifikasi early dump Robinhood + tombol Holder Analytic

Dua permintaan user lanjutan di sesi yang sama:

1. **Notifikasi watchlist Robinhood dengan kriteria sama** seperti token pool
   Meteora: jika dust holder menyeberang naik **> 0,1% MC**, alert
   ⚡ EARLY DUMP dikirim (tanpa gerbang volume keras, ulang 1×/bucket 4 jam,
   hanya saat masih naik). Watchlist RH tidak dipecah Chart LP, jadi scope =
   **seluruh `rh_watch`**; cron kini memanggil
   `process_holder_alerts(..., lp_mints=set(rh_watch))` di blok Robinhood
   `scripts/scan_holders.py`. Aturan `early_dump` sendiri chain-agnostic
   (mint hanya string; link pesan sudah EVM-aware rh-scan/DexScreener/
   Blockscout).
2. **Tombol Holder Analytic (🧮) di baris watchlist Meteora dan Robinhood.**
   Card Chart LP (Meteora) sudah punya tombol sejak 2026-09-03; yang baru:
   - `app.py` card Robinhood: kolom diperlebar 6 → 7, tombol `rh-holder-{mint}`
     (🧮, switch_page ke halaman Holder dengan `?mint=0x…`), ✕ pindah ke
     kolom terakhir.
   - `pages/5_🧮_Holder.py` kini mendukung **dua chain**: pemilihan chain
     ikut format address `mint` (`0x…` = Robinhood, selain itu Solana).
     EVM memakai `robinhood_watchlist.load_watchlist/load_status/load_history`
     + `seed_from_status`, form CA menerima base58 Solana **dan** `0x…`,
     tombol "+ Tambahkan ke watchlist" dan "Scan holder FULL" dirutekan ke
     `robinhood_holders.analyze_token` + store `holder_history_robinhood.json`.
     Overlay scan manual (`MANUAL_SCAN_KEY`) disaring per chain agar hasil
     scan EVM tidak bocor ke watchlist Solana dan sebaliknya.

**Tes**: 708 lulus (AppTest Streamlit aktif: 2 tes baru card RH, 1 tes
halaman Holder EVM, 1 tes wiring cron RH).

# Progress

## 2026-09-05 — Watchlist holder Robinhood Chain (EVM, chain id 4663)

User minta tambahan **holder watchlist untuk jaringan Robinhood** dengan rule
yang sama seperti Solana, contoh token `0x8490acd2d52d0ebd34cb13e01bd9a9380b36411d`
(VLAD). Implementasi:

- Watchlist terpisah `watchlist_robinhood.json` + pending journal; snapshot
  `holder_status_robinhood.json`, history `holder_history_robinhood.json(.gz)`
  di ref `holder-live`.
- Holder diambil dari Blockscout `robinhoodchain.blockscout.com`
  (`module=token&action=getTokenHolders`, pagination `page`/`offset`), decimals
  & supply dari `getToken`; harga/marketcap/volume dari DexScreener
  `chainId=robinhood` (filter `get_market(..., chain_id="robinhood")`).
- Rule dust tetap sama: `$10` per wallet, ≥0,5% HATI-HATI, ≥1% BAHAYA,
  grafik 4 jam, tracking wallet/alert Telegram. Link UI/pesan memakai
  rh-scan.com + DexScreener robinhood + Blockscout, sedangkan Solana tetap
  GMGN + DexScreener + Solscan.
- `scripts/scan_holders.py` men-scan Robinhood best-effort setelah Solana
  (kegagalan Robinhood tidak mematikan cron Solana); dashboard merender card
  terpisah "🦅 Watchlist Robinhood Chain".
- **Tes**: 704 lulus (111 skip Streamlit UI), termasuk per-path cache untuk
  `holder_status`/`holder_history`, EVM branch `links`, routing
  `watchlist_robinhood`, dan `test_store_backup`. Perintah unittest di
  README diubah ke `python -m unittest discover -s tests -t .` supaya
  `tests/__init__.py` (kill-switch offline Robinhood/backup) ikut aktif —
  tanpa ini, `watchlist_robinhood.json` yang terisi membuat test cron
  mencoba skan Robinhood sungguhan.

## 2026-09-04 — Cron hourly + badge 🏆 BEST POOL + alert ⚡ EARLY DUMP

Tiga permintaan user dalam satu sesi: (1) cron pencatatan holder jadi
**1×/jam** karena schedule GitHub `*/15` terbukti ter-throttle; (2) badge
**BEST POOL** di listing Scan Meteora untuk pool dengan dust < 0,1% MC;
(3) **early notification** saat dust pool Meteora naik di atas 0,1% supaya
bisa exit LP lebih cepat. Jawaban user via ask_user: scope early dump =
**hanya token pool (source=meteora/Chart LP)**; kirim **tanpa gerbang
volume**; ulang **1× per bucket 4 jam** (+ reset saat ≤ 0,1%); badge hanya
di **Scan Meteora**; history **MAX_POINTS → 336** (14 hari × 24 titik).

### Keputusan & angka terukur

- **Cron `0 * * * *`** + `timeout-minutes: 45` (run hourly yang lambat tidak
  boleh menumpuk di concurrency group). Dokumen DEPLOY.md menjelaskan bahwa
  schedule GitHub best-effort (kadens `*/15` terukur ±2 jam: run 18:02,
  20:58, 22:57, 00:39 UTC) dan cara verifikasi kadens (log `updated=` /
  `durasi=` / commit `holder-live`).
- **MAX_POINTS 84 → 336** dipilih (bukan bucket 4 jam in-place): alert tetap
  dapat resolusi per jam (crossing dibaca tiap run) sementara UI/chart tetap
  `resample_4h` (≤ 84 bucket 4 jam = 14 hari), jadi snapshot dashboard tidak
  membengkak. Terukur dengan store sintetis realistis 55 token × 336 titik
  per jam: raw 3,22 → 10,22 MB tapi gzip hanya 901 kB → **1,03 MB** (rasio
  9,9×; titik JSON sangat kompresibel) — jauh di bawah `MAX_BACKUP_BYTES`
  3,5 MB. Backup nyata terakhir: 901 kB (55 token, masih muda: 1–8 titik/
  token). Snapshot `holder_status.json` tetap ~0,4 MB karena
  `compact_history_for_status` = resample 4 jam.
- **Prune step 5 disesuaikan**: sebelumnya "titik di luar 42 terbaru (7 hari
  @ 4 jam)". Dengan titik per jam, 42 mentah = 42 jam saja, jadi step 5 kini
  `resample_4h(points)[-42:]` — backup yang terpaksa dipangkas tetap
  menyimpan ~7 hari grafik bucket 4 jam.
- **Badge BEST POOL**: `DUST_BEST_PCT = 0.1` + `DUST_BEST_LABEL = "BEST
  POOL"` + `DUST_BEST_MIN_HOLDERS = 40` di holder_history.py; `dust_flag(pct,
  prev, *, holders=...)` aditif (`best: bool`, level AMAN/HATI-HATI/BAHAYA
  dan `dust_level_rank` tidak berubah → sorting Chart LP tidak terpengaruh).
  **Guard data** (paling penting): BEST POOL tidak pernah keluar saat
  `dust_pct_mc is None`, `total_fetched <= 0`, atau wallet dianalisis < 40 —
  dust "0,00%" dari data gagal/kosong tidak boleh tampil sebagai pool
  bersih. Pemanggil lama (watchlist, Chart LP, halaman Holder) tidak
  mengirim `holders` → `best` selalu False, perilaku mereka tidak berubah.
  Badge dirender hanya di listing Scan Meteora (chip `🏆 BEST POOL` di kolom
  Dust %MC). **Boundary `== 0,1%`**: bukan BEST POOL (strict `< 0,1%`) dan
  bukan pemicu early_dump (strict `> 0,1%`) — kedua sinyal tidak pernah
  tumpang tindih di angka yang sama.
- **Rule early_dump** (`telegram_alerts.py`, kind `early_dump`): crossing +
  hysteresis — `previous` = marker `alert_state["early_dump"]` `{ts,
  dust_pct_mc}` yang direkam tiap run; token baru dipantau tidak langsung
  mengirim (mustahil membuktikan crossing); turun ≤ 0,1% = reset (tanpa
  notifikasi turun). **Tanpa gerbang volume**: `early_dump_verdict()` selalu
  `allow=True`, konteks volume/harga/volatilitas ditarik lazy dan tampil
  sebagai info (`Verifikasi: ℹ️ … (info saja, tanpa gerbang volume)`), tanpa
  data pasar → `⚠️ TIDAK TERVERIFIKASI`. Ulang maks 1× per bucket 4 jam
  (event id) + `MIN_RESEND_SEC` 1 jam, hanya saat dust masih **naik**;
  dedup/state/merge memakai mekanisme lama (`sent_event_ids`, `last_sent`,
  `compact_alert_state`, `_merge_alert_state` — marker di-merge paling baru).
  Wiring: `process_holder_alerts(..., lp_mints=...)` → `evaluate_alert_events(
  ..., lp_mint=...)`; `scripts/scan_holders.py` mengisi `lp_mints` dari
  `split_watchlist(watchlist)[0]`. **Blokir nyata**: watchlist saat ini
  54 token = 52 degen / 2 manual / **0 meteora** → rule belum akan menyala
  sampai user ⭐ pool dari Scan Meteora (dokumentasi README/AGENTS).
  Keterbatasan terdokumentasi: cron tidak mengirim link `🌊 Meteora` /
  `🦅 HawkFi` karena `watchlist.json` tidak menyimpan pool address; format
  pesan siap memuatnya bila event membawa `pool_addresses` (field tidak
  mengarang di watchlist.json). Pesan early dump tidak memuat blok
  pergerakan wallet (marker tanpa peta balance).
- Text "cron 15 menit" di app.py/pages/script docstring/README/DEPLOY/
  DISABLED diganti target 1 jam.

### Tes
**508 lulus** (sebelumnya 477). Baru: `tests/test_holder_history.py` +12
(best + guard data kosong/batas 0,1, MAX_POINTS 336, resample per jam tetap
bucket 4 jam, merge cap), `tests/test_early_dump.py` +16 (crossing,
hysteresis, dedup bucket, cooldown, tanpa/ada konteks pasar, pesan + link
pool opsional, compact/summary/merge marker, wiring lp_mints via
process_holder_alerts, zero-fetch tidak menggerakkan marker),
`tests/test_store_backup.py` +1 (prune resample 42 bucket 4 jam; fixture
_big_store titiknya disesuaikan ke jarak bucket 4 jam), `tests/test_lp_card_ui.py` +1 (AppTest badge BEST POOL hanya untuk
data valid), `tests/test_scan_holders.py` +1 (cron meneruskan lp_mints).
pyflakes: tidak ada warning baru.

## 2026-09-04 — Link GMGN + DexScreener di alert Telegram

Permintaan user: *"tambahkan link ke gmgn dan dexscreener ketika notifikasi
telegram muncul"*. Alert holder dust sebelumnya berakhir di baris `Mint: …` —
address harus disalin manual ke browser.

### Perubahan
- `links.token_link_lines(ca)`: dua baris teks polos
  `🔗 GMGN: https://gmgn.ai/sol/token/<ca>` dan
  `🦆 DexScreener: https://dexscreener.com/solana/<ca>`, dibangun dari
  `gmgn_token_url()` / `dexscreener_token_url()` yang sudah ada (satu sumber
  URL dengan link 🔗GMGN/🦆Dex di watchlist UI, address selalu ter-encode
  lewat `safe_url_part`). Return `[]` bila address kosong.
- `telegram_alerts.format_alert_message()`: menambahkan baris link tepat
  setelah `Mint:` untuk **semua** jenis alert (dump, akumulasi, baseline
  shift). Telegram mengirim teks polos dan otomatis me-link URL, jadi tidak
  perlu `parse_mode` HTML (dan tidak ada risiko escaping).
- `send_test_alert()` (`--telegram-test`) sengaja tetap tanpa link: pesan itu
  bukan sinyal token.

### Perilaku tepi
- `mint` kosong/None → kedua baris dilewati, `Mint: -` tetap tampil (tidak ada
  label menggantung).
- Address berisi karakter berbahaya (`a?b&c d#e`) → ter-encode
  (`a%3Fb%26c%20d%23e`) sehingga tidak bisa memutus struktur URL.
- Tidak mengubah aturan alert, ambang, dedup, maupun gerbang volume — hanya
  presentasi pesan.

### Tes
**477 tes lulus** (sebelumnya 465). Baru: `tests/test_links.py` +4 (isi baris,
konsistensi dengan helper URL, address kosong, encoding) dan
`tests/test_telegram_alerts.py::AlertMessageLinkTest` +8 (link terkirim untuk
semua jenis alert, urutan setelah `Mint:`, tanpa mint → tanpa link, encoding,
teks yang benar-benar dikirim ke Bot API, test-alert tetap tanpa link).

## 2026-09-04 — Backup durable store holder + snapshot dirampingkan

Audit backup (pertanyaan user: *"cek sekarang apakah sudah ada backup juga?"*)
menemukan lubang: kode, `holder_status.json`, titik 4 jam, kohort, dan
`alert_state` memang sudah ter-publish ke ref `holder-live`, tetapi
**`holder_history.json` tidak pernah dibackup**. Runner Actions dan Streamlit
Cloud ephemeral, jadi baseline scan FULL, kohort beku, state dedup alert
(`sent_event_ids`/`last_sent`), dan kronologi wallet hilang setiap run — cron
selalu mulai dari nol dan satu-satunya pemulihan adalah `seed_from_status()`
dari snapshot. Pilihan user: **opsi A** (round-trip store ke `holder-live`)
**+ rampingkan snapshot** (peta balance pindah ke store).

### Yang ditambahkan
- `holder_status.py`: transport digeneralisasi — `_github_get_bytes` /
  `_github_put_bytes` (retry 4×, API → raw CDN) + pembungkus JSON
  (`_github_pull` / `_github_push`) yang sudah ada; `pull_store_backup()` /
  `push_store_backup(payload, message)` untuk `HISTORY_REPO_PATH =
  "holder_history.json.gz"`.
- `snapshot_status()` **ramping**: `alert_state` →
  `telegram_alerts.alert_state_summary()` (jumlah balance/dust, `summary:
  True`), kohort → `_cohort_for_status()` (jumlah wallet), kronologi →
  `_chronology_for_status()` (jumlah + sampel movements ≤20/interval,
  ≤12 interval). Angka yang dibaca UI tidak berubah.
- `holder_history.py`: `store_backup_bytes` (gzip+JSON compact),
  `parse_store_backup` (toleran gzip/JSON polos; payload rusak → `None`,
  termasuk gzip terpotong `EOFError`/`zlib.error`), `merge_stores`,
  `prune_store_for_backup`, `publish_holder_history`, `pull_holder_history`,
  `load_durable_holder_history` (cache `DURABLE_CACHE_TTL` 600 detik),
  `reset_durable_cache`, `backup_enabled()` (kill-switch
  `HOLDER_STORE_BACKUP=0`), `MAX_BACKUP_BYTES = 3.500.000`.
- `seed_from_status()` dikerasi: `alert_state`/`cohort` berbentuk ringkasan
  tidak lagi menimpa store (`_is_summary_alert_state`); snapshot **format
  lama** (peta wallet, termasuk yang petanya kosong) tetap dipulihkan supaya
  id dedup alert tidak hilang saat backup durable belum ada;
  `_sanitize_remote_chronology()` menolak peta wallet berbentuk angka.
- `scripts/scan_holders.py`: `pull_holder_history()` →
  `merge_stores(lokal, durable)` → `seed_from_status()` sebelum scan;
  `publish_holder_history(history, push=not --no-push)` setelah publish
  snapshot; log `Store holder: tokens=… backup=ada/tidak ada` dan
  `backup=ok <n>B | skip (--no-push) | GAGAL (…)`.
- `app.py` + `pages/5_🧮_Holder.py`: `load_holder_history()` →
  `load_durable_holder_history()` (`merge_stores(durable, lokal)`: store lokal
  menang bila seri, jadi scan manual baru tidak ditimpa backup lama).

### Aturan merge (ukurannya = siapa yang menang)
| Field | Aturan |
|---|---|
| `points` | union per `ts`, urut, ≤`MAX_POINTS` (84) |
| `baseline` | **paling tua** — immutable, tidak bisa dibuat ulang tanpa scan FULL |
| `latest_detail` | paling baru |
| `cohort` | yang masih punya peta balance, lalu `frozen_at` terbaru |
| `chronology.intervals` | union per `(from_ts, to_ts)`, movements terbanyak menang, ≤24 |
| `chronology.*_wallets` | yang masih punya peta wallet, lalu ts (baseline paling tua) |
| `alert_state` | snapshot `baseline`/`rolling` terbaru; `sent_event_ids` union ≤96; `last_sent` max per jenis ≤8; `rejected_signals` ≤8 |
| seri | **argumen belakang menang** (cron: durable di belakang; UI: lokal di belakang) |

### Ukuran (terukur ulang dengan helper asli pada snapshot live, 36 token)
| Payload | Sebelum | Sesudah |
|---|---|---|
| `holder_status.json` (indent=2, bentuk yang di-publish) | 2.869.835 B | **300.372 B (−89,5%)** |
| — compact JSON | 2.231.997 B | 157.397 B (−92,9%) |
| — `alert_state` | 1.850.768 B (83% payload) | **10.695 B** (ringkasan jumlah) |
| — `cohort` | 236.345 B | **1.890 B** (jumlah wallet) |
| — `chronology` | 13.104 B | 13.032 B (peta wallet → jumlah, movements sampel ≤20/interval tetap) |
| store penuh (36 token) | **tidak dibackup** | 15.051.771 B JSON compact → **576.832 B gzip (26,1×)**; body PUT base64 0,77 MB |
| blob git baru per run (zlib −9) | 654.921 B | **±633.833 B** (snapshot 21.083 + gz 612.750) = **0,97×** |

Artinya durability tambahan ini **tidak memperbesar repo**: gzip backup sudah
tidak termampapkan lagi oleh git, tetapi snapshot yang −90% menutupinya
(cron `*/15`: ±61 MB/hari, sebelumnya ±63 MB/hari).

`MAX_BACKUP_BYTES` 3,5 MB praktis tidak pernah tersentuh (batas PUT Contents
API terbukti aman di 2,85 MB). Tangga `prune_store_for_backup` (bila perlu):
movements interval lama → interval di luar 6 terbaru → peta wallet kronologi →
`points[].buckets` → titik di luar 42 terbaru → `latest_detail`; baseline
dibuang paling akhir.

### Keputusan yang sengaja diambil
- Backup gagal **tidak** membuat cron merah (snapshot dashboard lebih
  penting), tapi selalu tercetak sebagai `WARN` + `backup=GAGAL (…)` dan
  `over_budget` ditandai bila payload tetap melebihi budget.
- `publish_holder_history(save_local=False)` default: `ingest_many()` sudah
  menulis `holder_history.json`, jadi tidak ada tulis ganda (dan tes tidak
  menimpa file data repo).
- Suite tes wajib offline: `tests/__init__.py` memasang kill-switch, dan tes
  UI mem-mock `holder_history.pull_holder_history`. Verifikasi: 48 percobaan
  jaringan saat `discover tests` → **0** setelahnya.
- Guard B (anotasi `dust_pct_supply` 0 dari Helius) tetap `TODO(alerts)` —
  tidak disentuh tugas ini.
- Transisi aman tanpa migrasi: run pertama setelah deploy masih menemukan
  snapshot **gemuk** di `holder-live` (belum ada `holder_history.json.gz`),
  jadi `seed_from_status()` memulihkan peta wallet dari sana seperti sebelumnya
  sambil membuat backup pertama. Run berikutnya memakai snapshot ramping +
  backup `.gz`.

### Tes
**465 tes lulus** (sebelumnya 398). Baru: `tests/test_store_backup.py` (59) —
round-trip gzip, parse payload rusak, semantik merge per field + immutability
input, tangga prune, publish/pull (termasuk transport melempar, over-budget,
kill-switch, `save_local`), cache TTL `load_durable_holder_history`,
`seed_from_status` ringkas vs format lama, dan snapshot ramping (tanpa peta
wallet, movements tetap bounded). `tests/test_scan_holders.py` +5 (restore +
merge backup, push setelah publish, `--no-push`, backup gagal tidak merah,
publish snapshot gagal tetap exit 3) dan `_run()` diperluas;
`tests/test_holder_status.py` ditulis ulang ke kontrak ramping (7).

## 2026-09-03 — Kartu metrik Holder Analytic mengikuti scan manual (kasus AGENTHQ)

Laporan user: token **AGENTHQ** menampilkan dust hold **0,7% di grafik** tetapi
**1,16% di kartu "Dust hold % MC"** pada saat yang sama.

### Akar masalah (dua lapis)
1. **Dua vintage data.** Halaman Holder Analytic mengambil kartu metrik dari
   snapshot terpublikasi `holder_status.json` (`pages/5_🧮_Holder.py` baris
   437/441/448) tetapi mengambil grafik dari `holder_history.json` + riwayat
   snapshot (`_points_for`). Tombol **🔄 Scan holder FULL token ini** hanya
   memanggil `ingest_many(..., detail=True)` → titik baru masuk store,
   snapshot tidak diperbarui — dan memang tidak boleh: `snapshot_status`
   membangun `tokens` dari analyses yang diberikan saja (tidak merge), jadi
   publish satu token akan menghapus token lain dari dashboard. Kartu = cron
   21:35 WIB, grafik = scan manual barusan.
2. **Kenapa selisihnya besar.** AGENTHQ sedang pump: harga 0,0001085 →
   0,0001889 (+74%; `priceChange.h1` +80%), MC $108.545 → ±$188.968.
   dust % MC = nilai dust / MC sebenarnya **invariant terhadap harga**
   ($1.256,73 × 1,741 ÷ $188.968 = 1,158%, tetap), **tetapi** cutoff dust
   adalah **$10 per wallet dalam USD**: wallet yang memegang 52.938–92.166
   token (nilai lama $5,74–$10) "lulus" ke >$10. Agar tampil 0,70%, nilai
   dust harus tinggal ±$1.323 → ±40% nilai dust pindah bucket, dan slice
   $5,74–$10 itu memang lazim memuat 40–45% nilai dust. Jadi **tidak ada yang
   jual** — klasifikasinya yang bergeser. Cerminannya (harga turun → wallet
   masuk dust → dust % MC naik ±0,4-0,5 pp, melewati ambang dump 0,25 pp)
   justru **lolos** gerbang volume/harga karena harga ≤ −1% dan volume tinggi.

### Perbaikan (opsi A — pilihan user)
- `holder_status.compact_manual_scan()`: payload ringkas scan manual untuk
  `st.session_state[MANUAL_SCAN_KEY]`; peta wallet / snapshot alert /
  kronologi dibuang lewat `_holders_for_status`.
- `holder_status.resolve_token_view()`: overlay scan manual di atas entri
  snapshot bila `analyzed_at`-nya tidak lebih tua dan `holders` terisi;
  `history`/`cohort`/`alert_state`/`chronology` tetap dari snapshot; menambah
  `view_source` = `manual`/`snapshot`; tidak memutasi input; mint token lain
  diabaikan.
- `holder_status.apply_manual_scan()`: salinan status dengan token yang cocok
  diganti view terbaru (token baru ditambahkan, token lain tidak dihapus,
  file snapshot & cache publish tidak disentuh).
- `pages/5_🧮_Holder.py` + `app.py` memakai overlay itu sebelum render → kartu
  metrik, badge HATI-HATI/BAHAYA, watchlist, dan Chart LP setuju dengan
  grafik; caption menandai **scan manual barusan**.
- Guard arah turun (opsi B) **belum** dikerjakan; keputusan user dicatat
  sebagai `TODO(alerts)` di atas `validate_alert_with_volume`: bila dust % MC
  naik tetapi `dust_count`/pangsa supply tidak naik → **annotate, bukan
  reject**. Prasyaratnya `dust_pct_supply` terisi untuk sumber Helius (DAS
  tidak mengembalikan `amount_percentage`; `holder_analysis.py` meng-hardcode
  0.0 — hanya GMGN yang mengisi).

### Tes
27 tes murni baru (`tests/test_holder_status_view.py`) + 2 tes AppTest
(`tests/test_holder_page.py`): sebelum klik kartu 1,16% / 90 wallet, sesudah
klik 0,90% / 130 wallet + caption "scan manual barusan" + badge HATI-HATI
(bukan BAHAYA); scan manual token lain diabaikan; snapshot yang lebih baru
mengalahkan scan manual; status asli tidak termutasi. Total **398 tes lulus**.

## 2026-09-03 — Konfirmasi volume + volatilitas untuk alert dust

Permintaan user: ambang dust 0,25 pp terlalu berisik; sinyal harus
divalidasi volume + harga + volatilitas dulu tanpa mengorbankan kecepatan
reaksi (< 5 menit). Ambang dust (0,25 / 0,50 / ±1,00 pp) **tidak diubah** —
konfirmasi ini dipasang di belakangnya, jadi filternya tidak saling menutupi.

### Aturan
- `telegram_alerts.validate_alert_with_volume(...)` →
  `VolumeValidation(is_valid, confidence_score, reason, verified, details)`.
  Gerbang keras: **dump** = volume 4 jam ≥ 2× `avg_volume_7d` **dan**
  perubahan harga ≤ −1%; **akumulasi** = volume ≥ 1,5× **dan** buy pressure
  > sell pressure. `avg_volume_7d` diartikan sebagai rata-rata volume
  **per window 4 jam** selama 7 hari (bukan angka harian) supaya sebanding
  dengan `volume_4h`.
- Skor: 0,70 dasar + ≤0,15 kekuatan volume + ≤0,10 harga/tekanan beli +
  0,20 bila volatilitas tinggi **dan** arah harga mendukung; gagal gerbang →
  skor diagnostik ≤0,40. Ambang lolos 0,70, naik ke 0,80 bila
  `price_stddev_4h > 3%`. Contoh di prompt (stddev >3% + dust ≥0,25 pp →
  0,90 → lolos) direproduksi persis; dump tanpa volume (0,85 < 1,0 → 0,67)
  dan akumulasi tanpa tekanan beli (0,62) ditolak.
- Volatilitas tinggi **tanpa** dukungan arah harga tidak memberi bonus:
  kalau diberi, ambang 0,80 tidak pernah menyaring apa pun (terukur —
  akumulasi marginal menjadi 0,702 < 0,80 → ditolak).
- `evaluate_4h_rules` / `evaluate_baseline_rule` memakai gerbang itu;
  baseline shift divalidasi mengikuti arah perubahan (naik = dump, turun =
  akumulasi). Kandidat yang ditolak di-log `Dust signal rejected …` (dust,
  volume, harga, alasan) dan dicatat ke `alert_state.rejected_signals`
  (maks 8/token) untuk audit false positive.
- Kebijakan data hilang (keputusan user): alert **tetap dikirim**, diberi
  baris `⚠️ TIDAK TERVERIFIKASI` + `Konfirmasi: ⚠️ data tidak lengkap`
  (`ALLOW_UNVERIFIED_ALERTS = True`). `volume_4h = 0` diperlakukan sebagai
  data valid, bukan data hilang → gerbang gagal.
- Dedup: event id bucket 4 jam tetap, ditambah **jeda minimum 1 jam** per
  token+jenis(+arah) lewat `alert_state.last_sent`. Sebelumnya dua alert
  identik bisa terkirim berjarak ±2 menit di dua sisi batas bucket.

### Data
- `holder_history.calculate_volatility_metrics(candles, historical, ...)`:
  16 candle hourly → `price_stddev_4h`, `price_range_4h`,
  `intra_hour_volatility(+_max)`, `price_change_4h_pct`, `volume_4h`,
  `missing_hours`, `stale`, `available`, `high_volatility`. Candle < 2 atau
  harga 0 → `available: False` (bukan stddev 0 yang tampak "tenang");
  candle basi (> `MAX_AGE_HOURS`) → `stale: True`.
- `core.get_hourly_candles()` baru; `get_daily_candles()` kini agregasi dari
  candle hourly yang sama (satu endpoint, dua bentuk, tanpa double-fetch).
- `alert_context.py` (baru): `build_market_context()`, `volume_from_candles()`,
  `volume_from_dexscreener()`, `volume_from_daily_rows()`,
  `pressure_from_txns()`, `compact_signal()`, `market_context_provider()`.
  Urutan sumber: candle hourly GeckoTerminal → DexScreener (sudah diambil
  `analyze_token`, tanpa request tambahan) → `daily_effort.json`.
  Ditarik **lazy**: hanya token yang punya kandidat, memo 1× per token per run.
- `holder_analysis.analyze_token` kini meneruskan ringkasan `market`
  (volume, price_change, txns, pair_addresses) di hasil analisis;
  `holder_status.snapshot_status` menyimpan `tokens[mint].market_signal`
  berdampingan dust % MC; `scripts/scan_holders.py` menyuntikkan provider
  dan mencetak `unverified=`, `rejected=`, `konteks=N token (X ms)`.

### Review optimasi (diminta user)
| Fungsi | Temuan | Tindakan |
|---|---|---|
| `core.matching_dexscreener_pairs` | Sort O(n log n) atas ≤30 pair; heap/single-pass top-1 diukur **tidak lebih cepat** (5,6 vs 5,2 µs n=10; 271 vs 263 µs n=500) — biaya dominannya `_dex_liquidity_usd` per pair, bukan sort. `get_market` juga butuh seluruh urutan untuk `pair_addresses`. | Tidak diubah (terukur) |
| `core.get_daily_candles` | Batas hari UTC benar (`datetime.date()`); diverifikasi 31 Des→1 Jan, 28→29 Feb kabisat, 30→31 Des, awal/akhir Maret. **Tiga bug nyata**: (1) sel `null` GeckoTerminal → `float(None)` TypeError **di luar** blok try; (2) `limit_days=0` mengembalikan seluruh riwayat (`[-0:]`); (3) timestamp duplikat menghitung volume dua kali. Hari UTC yang masih berjalan ikut ter-return (sudah disaring `cvd_daily.completed_dates`). | Diperbaiki + guard milidetik, dicatat di docstring |
| `holder_analysis.classify_holders` | Konversi USD sudah sekali per wallet di fetcher (bukan di sini); yang boros ±9 lintasan atas holder yang sama. Single-pass **dengan `_float()` per baris justru lebih lambat** (4,15 vs 2,86 ms / 12k holder) karena overhead pemanggilan fungsi; single-pass ramping = **1,94 ms**. | Single-pass ramping; identik di 500 trial acak + 12k holder sintetis |
| Dedup alert | Event id `holder-dust:mint:kind:bucket[:arah]` disimpan di `alert_state.sent_event_ids` (maks 96), hanya dicatat setelah kirim sukses → gagal kirim dicoba lagi. Granularitasnya bucket 4 jam, bukan 1 jam. | Jeda minimum 1 jam (`MIN_RESEND_SEC`) + `last_sent` |
| `telegram_alerts._event` | `wallet_movements()` (O(W), W ≤ 800 address) dihitung dua kali untuk kandidat yang sama. | Dihitung sekali, diteruskan ke `_event` |
| `telegram_alerts.compact_wallet_snapshot` | `sorted(dust, key=…)` identik dipanggil dua kali. | Diurut sekali |
| `telegram_alerts.send_telegram_message` | 429 `retry_after` tidak dihormati (hanya di-log; event dikirim ulang run berikutnya). | `TODO(alerts)` di kode |
| Beban API candle | GeckoTerminal publik ±30 req/menit; run yang memicu banyak sinyal bersamaan bisa tersentuh (lazy fetch sudah membatasi ke kandidat saja). | `TODO(alerts)` throttle |
| Store JSON | `holder_history.json` / `holder_status.json` ditulis ulang penuh tiap run (atomic write). | Belum perlu; dipantau. **2026-09-04**: store kini juga dibackup durable (`holder_history.json.gz`, ref `holder-live`) — lihat entri terbaru |

### Tes
369 tes lulus (sebelumnya 228). Baru: `test_volume_validation.py` (33),
`test_volatility_metrics.py` (17), `test_alert_context.py` (32),
`test_alert_gating.py` (27), `test_alert_pipeline.py` (8),
`test_core_candles.py` (24) — mencakup edge case yang diminta: volume 0,
`avg_volume_7d` 0/None (pool baru), NaN/inf, candle bolong (price gap),
candle < 2, candle basi, timestamp milidetik, payload DexScreener rusak,
provider gagal, cooldown 1 jam, dan lazy-fetch (provider tidak dipanggil
bila tidak ada kandidat). `test_alert_pipeline.py` juga memastikan
integrasi end-to-end tidak menulis `holder_status.json` asli.

## 2026-09-03 — Kronologi holder sejak snapshot awal (scan FULL)

- Setelah `Scan holder FULL` pertama, halaman Holder Analytic menandai
  **snapshot awal** (data pembanding belum cukup). Baseline tidak ditimpa.
- Scan FULL berikutnya menambah interval kronologi: dust % MC, wallet
  yang balance-nya naik/turun, wallet baru, saldo 0 / tidak teramati, dan
  perpindahan kategori. Perbandingan memakai **balance token**, bukan
  hanya USD, supaya kenaikan harga tidak dianggap pembelian.
- Wallet LP/pool/noise dikecualikan. Setiap movement punya tautan Solscan
  (address penuh, URL-encoded). Payload snapshot/movement dibatasi;
  sampled/truncated dijelaskan. Schema history lama tetap bisa dibuka.
- Modul baru `holder_chronology.py`; persistensi tetap di
  `holder_history.py` / `holder_status.py` (versi compact).


## 2026-09-01 — Holder Analytic (dust) + Scan Meteora

- UI fokus dust: watchlist ringkasan jumlah + % MC, badge 1%/2%, sparkline
  4 jam; Trending/Degen tanpa kolom holder/12 jam; CVD tanpa Holder Analytic.
- Halaman baru `pages/5_🧮_Holder.py`. History di `holder_history.json`.
- Scan Meteora DLMM 24h+1h, hide dust ≥ 1% MC, shortcut Meteora + HawkFi.
- Kohort Crab+Fish di-freeze 4 jam (sisa token, bukan USD).

## 2026-08-19 — Port sinyal SMART SEROK + watchlist bersih

- Mengosongkan `watchlist.json` (semua token lama dihapus).
- Tambah CA manual: field ticker dihapus; `fetch_token_symbol()` memakai
  DexScreener (`get_market`) sehingga symbol terisi otomatis.
- Scanner realtime tidak lagi memakai wash-collapse / SBR. Engine baru
  `serok_engine.py` meniru ekstensi SMART SEROK v9.1.3 (bar 1H, R-spike,
  battle P65).
- Telegram: 🔴 WASPADA DUMP, 🟢 SIAP2 PUMP, ⚔️ BATTLE TERJADI — satu
  alert per `event_id`, format rapi + link GMGN/DexScreener + detail bar/MC.
- Cron GitHub Actions `*/15 * * * *`. Window fetch 48 jam.
- Tes: `tests/test_serok_engine.py`; payload Telegram dan UI disesuaikan.

## 2026-08-18 — Watchlist utama mengikuti scanner realtime

- Akar masalah: cron harian diganti scanner 10 menit, tetapi `app.py` masih
  mengklasifikasi `daily_effort.json` (terakhir 2026-08-16) sementara
  `last_scan_result.json` hanya ada di Actions cache.
- Scanner kini mem-publish snapshot `reversal_status.json` ke ref
  `reversal-live` setelah setiap scan.
- Watchlist halaman utama menampilkan REVERSAL UP/DOWN, setup, confidence,
  CVD bersih, wash-collapse, dan breakdown wallet — sama dengan payload
  Telegram — plus tombol muat ulang.

## 2026-08-17 — Realtime bidirectional reversal

- Port engine SMART SEROK ke `reversal_engine.py`: normalisasi GMGN, re-derive
  SOL rusak, FIFO wash matcher 60 detik, clean CVD, daily parity, dan rolling
  6h vs prior 24h.
- Tambah sinyal simetris `REVERSAL_UP` dan `REVERSAL_DOWN`, setup
  accumulation/distribution, serta guard minimum tx/volume.
- Tambah scanner incremental terkompresi, payload Telegram dua arah, dan state
  machine 2-scan/transition-only/cooldown 18 jam.
- Workflow lama harian diganti rolling scan setiap 10 menit dengan Actions
  cache untuk state dan trade window.
- Validasi offline SISYPUSS cocok dengan reference: 08-16 CVD sekitar -22 SOL,
  wash 15.2%; 08-17 clean CVD sekitar +11.8 SOL, wash 3.0%, `REVERSAL_UP`.


## 2026-08-15 — Overhaul Efisiensi Anomali

- Mengganti seluruh logika deteksi dengan R = |ΔCVD| / |ΔHarga%| per hari WIB.
- Menambahkan `effort_detector.py`, persistence idempoten 30 hari, dan S1–S5.
- Menulis ulang cron menjadi sekali sehari pukul 00:00 WIB.
- Menulis ulang Telegram sehingga hanya S1–S4 yang dikirim.
- Mengubah dashboard menjadi watchlist effort dan listing GMGN tanpa ranking.
- Menambahkan chart harga/CVD dual-axis dan chart ratio tujuh hari.
- Memangkas layer CVD menjadi fetch/normalisasi trade yang dibutuhkan saja.
- Menghapus state, detector, workflow, dokumentasi, dan test generasi lama.
- Menambahkan unit test formula, boundary, insufficient data, WIB, persistence,
  join candle/CVD, dan format Telegram.

## 2026-08-15 — Perbaikan Baseline Stabil (arena/01a00357-wallet-depth)

- Menambahkan `MIN_BASELINE_RATIO = 0.05` dan `MIN_BASELINE_CVD_SOL = 1.0`.
- Menambahkan validasi baseline (aturan 1–6) ke `effort_detector.py`.
- Menambahkan `baseline_status`, `baseline_reason`, dan `raw_multiplier` ke output.
- Mengubah `signals.py` dengan `should_send_telegram()` (defensive gate).
- Memperbarui `scripts/update_cvd.py` agar hanya mengirim Telegram jika
  `baseline_status == "stable"` dan sinyal S1–S4.
- Memperbarui `app.py` dan `pages/4_📊_CVD.py` dengan badge baseline,
  alasan, dan tampilan multiplier yang ditolak.
- Memastikan S1–S4 hanya keluar saat `baseline_status == "stable"`.
- Memastikan chart tidak menampilkan marker bullish/bearish untuk baseline
  yang ditolak (`unstable` / `incompatible_direction`).
- Menambahkan test wajib: fixture MIM, ratio kecil, direction berbeda,
  stable S1, boundary, current ranging, dan defensive Telegram.
- Memperbarui dokumentasi (`AGENTS.md`, `README.md`, `PROMPT_EFFORT_ANOMALI.md`).

## 2026-08-15 — Link eksternal, shortcut CVD & fetch manual (arena/01a0039e-wallet-depth)

- Menambahkan `links.py`: helper bersama `gmgn_token_url`, `dexscreener_token_url`,
  `safe_url_part` (URL-encoding), `cvd_shortcut_query`, dan `external_links_html`
  (anchor `target="_blank"`) sehingga URL CA aman dan tidak duplikasi.
- Watchlist (`app.py`): menampilkan link ringkas GMGN dan DexScreener di setiap
  baris tanpa mengganggu tombol Chart/Hapus.
- Trending & Degen (`trending_ui.py`): menambahkan link GMGN, DexScreener, dan
  tombol shortcut `📊 CVD` yang membuka `pages/4_📊_CVD.py` dengan token
  terpilih (`?mint=...` + `effort_mint`). Shortcut bekerja meski token belum ada
  di watchlist dan tidak mengubah watchlist secara diam-diam.
- Halaman CVD (`pages/4_📊_CVD.py`):
  - Seleksi token dari query param/session, termasuk token di luar watchlist
    (dengan warning + tombol tambah eksplisit).
  - Panel "Fetch data manual": input hari 2–30 (default 7), tombol "Fetch
    sekarang", spinner/status, tanpa fetch otomatis saat page load.
  - Menampilkan log manual per fetch (timestamp WIB, tahapan, jumlah trades,
    rows dibuat/di-update, durasi, status, error) yang persisten dalam session.
- Refactor `scripts/update_cvd.py`: menambahkan `refresh_single_token` (pipeline
  reusable satu token: lookup market/pool → GMGN trades + fallback Helius →
  candle harian → agregasi CVD → `build_effort_rows` → merge idempotent) yang
  dipakai halaman CVD tanpa subprocess. Menambahkan `compute_lookback_window`
  (batas WIB, menghormati jumlah hari, tanpa hari berjalan) dan `_redact` agar
  API key/credential tidak bocor ke log.
- Fetch manual tidak mengirim alert Telegram dan tidak menyentuh watchlist.
- Menambahkan test `test_links.py` dan `test_manual_refresh.py` (URL, shortcut,
  lookback, refresh sukses/fallback/error, idempotent, tanpa alert, redaksi key).

## 2026-08-15 — Backtest history rentang tanggal di halaman CVD (arena/01a0039e-wallet-depth)

- Menambahkan `compute_date_window` dan `_resolve_window` di `scripts/update_cvd.py`
  untuk mendukung fetch dengan rentang tanggal inklusif dari–sampai (WIB), dengan
  clamp batas atas ke kemarin (hari berjalan tidak pernah diambil) dan clamp span
  maksimal 30 hari.
- `refresh_single_token` kini menerima `start_date`/`end_date`; `run_daily` (cron)
  tetap memakai `lookback_days=4` via `_resolve_window` sehingga perilaku cron
  tidak berubah.
- Halaman `pages/4_📊_CVD.py`: panel "📅 Rentang tanggal & backtest" untuk memilih
  dari–sampai, tombol "🔍 Lihat & fetch" yang mengambil data untuk rentang tersebut
  secara idempoten, lalu menampilkan history (metrik, chart harga/CVD, chart ratio,
  dan tabel data) untuk rentang terpilih. Fetch hanya terjadi saat tombol diklik
  (tidak otomatis saat page load).
- Panel "🔁 Fetch data manual" (last-N-days, default 7) tetap dipertahankan.
- Menambahkan test `DateWindowTest` (rentang inklusif, clamp ke kemarin, clamp span,
  urutan terbalik, dan pass-through window ke pipeline fetch).

## 2026-08-15 — Batas hari market (UTC) & backtest start+N hari (arena/01a0039e-wallet-depth)

- Mengubah batas hari dari Asia/Jakarta (WIB) menjadi hari market 00:00–23:59 UTC
  (sesuai Helius/Solscan) di seluruh pipeline:
  - `cvd_daily.py`: `MARKET_TZ = timezone.utc`; `day_key`, `completed_dates`,
    `build_effort_rows`, `fallback_candles_from_swaps` memakai batas UTC.
    Alias lama (`WIB`, `day_key_wib`, `completed_wib_dates`) dipertahankan.
  - `core.py`: `get_daily_candles` menggabungkan candle GeckoTerminal per hari UTC
    (alias `get_daily_candles_wib` dipertahankan).
  - `scripts/update_cvd.py`: `MARKET_TZ`, `_now_market`, `_as_market_midnight`,
    `compute_lookback_window`, `compute_date_window`, log `ts_market`.
- Halaman `pages/4_📊_CVD.py`: panel "📅 Backtest history" kini input tanggal awal
  (Dari, market/UTC) + "Berapa hari ke depan" (2–30), lalu fetch otomatis saat
  input berubah (idempoten, tidak mengirim alert, tidak fetch saat load pertama).
  History menampilkan metrik, chart harga/CVD, chart ratio, dan tabel data untuk
  rentang start → start+N-1 (dibatasi maksimal 30 hari dan tidak melewati kemarin).
- Memperbarui caption UI, `app.py`, `AGENTS.md`, `README.md`, `PROMPT_EFFORT_ANOMALI.md`
  ke terminologi hari market UTC.
- Menyesuaikan test ke batas UTC (`test_daily_pipeline.py`, `test_manual_refresh.py`).

## 2026-08-15 — Cron ke 00:00 UTC & tombol fetch rentang eksplisit (arena/01a003cb-wallet-depth)

- Menyelaraskan cron harian dengan batas hari market: `.github/workflows/daily-effort.yml`
  kini `0 0 * * *` (00:00 UTC / 07:00 WIB) — berjalan tepat setelah hari market
  berganti, bukan lagi `0 17 * * *` (jadwal lama untuk batas WIB).
  `DEPLOY.md` dan `prompt_overhaul_wallet_depth.md` ikut diperbarui ke
  terminologi 00:00 UTC (07:00 WIB).
- `pages/4_📊_CVD.py`: menambahkan tombol "🔍 Fetch rentang ini" di panel
  backtest yang memanggil `refresh_single_token(..., start_date=..., end_date=...)`
  untuk rentang yang sedang dipilih (sebelumnya hanya auto-fetch saat input
  berubah dan panel fetch manual yang memakai last-N-days).
- History backtest kini membedakan tiga status: fetch gagal → `st.error` dengan
  pesan error (sudah di-redact), fetch sukses tapi 0 baris → info "tidak ada data",
  dan belum pernah fetch → ajakan klik tombol / ubah rentang. Auto-fetch saat
  input berubah tetap dipertahankan; tombol dan auto-fetch berbagi jalur yang sama
  dan menyimpan hasilnya di `session_state["bt_result"]` (terpisah dari
  `manual_result` untuk panel fetch manual last-N).
- Log fetch manual (`manual_result` / `_render_manual_log`) tetap memakai
  `ts_market` dan tidak mencatat credential (error di-redact `_redact`).
- Menambahkan test: `DateRangeRefreshTest` (sukses/error/redaksi, idempoten,
  clamp 30 hari, tidak termasuk hari berjalan, tanpa alert Telegram) dan
  `test_cvd_page.py` (AppTest: tombol rentang memakai start/end, auto-fetch saat
  input berubah, jalur error/data/tidak-fetch, dan panel manual tetap lookback).

## UI kontras (teks hitam)

- `app.py` & `trending_ui.py`: nama token (`$SYMBOL`) sebelumnya memakai warna
  `#f8fafc` (hampir putih) sehingga tidak terlihat di background terang. Semua
  teks tabel watchlist dan listing GMGN kini `#000000` (hitam), termasuk mint
  pendek, header kolom, tanggal, nilai metrik, sub-label, dan alasan baseline.
- Link eksternal memakai biru gelap `#1d4ed8` (hover hitam + underline), badge
  netral memakai background terang `#e2e8f0` dengan teks hitam, garis pemisah
  `#cbd5e1`, dan persentase 24h memakai hijau/merah gelap agar tetap terbaca.
- Ditambahkan `.streamlit/config.toml` (`base = "light"`, `textColor #000000`)
  supaya tema selalu terang dan teks default hitam. Hero banner tetap gradasi
  gelap dengan teks putih.

## Kolom baseline: detail kejadian

- `effort_detector._build_result` kini menyertakan konteks hari baseline:
  `baseline_date`, `baseline_ratio`, `baseline_price_chg_pct`,
  `baseline_cvd_delta`, `baseline_direction`, dan `baseline_gap_days`
  (jarak hari ke hari N). Field murni informatif — formula R, multiplier,
  ambang 2,0/0,5, dan klasifikasi S1–S5 tidak berubah.
- `app.py`: kolom watchlist "Baseline" menjadi "Baseline & detail". Setiap baris
  menampilkan fakta hari baseline (`Base <tanggal> (<n>h lalu) · Δ<harga>% ·
  CVD <sol> SOL`). Untuk sinyal **selain netral** ditambahkan narasi kejadian:
  - S1/S3: "butuh SOL M× lebih banyak per 1% …" (supply/demand diserap),
  - S2/S4: "hanya perlu M× effort per 1% …" (buyer/seller absen),
  - ABSORBSI_LANGSUNG: CVD vs pergerakan harga (tanpa baseline),
  - SELLING_EXHAUSTION: tanggal flush, CVD flush → CVD hari ini, sisa %.
  Baris netral/insufficient tetap hanya fakta baseline plus alasan penolakan
  (noise, baseline tidak cukup) seperti sebelumnya.
- Lebar kolom watchlist disesuaikan agar teks detail tidak terlalu terpotong.
- Test baru `tests/test_baseline_detail.py`: field baseline (stabil, kosong,
  flush exhaustion) dan AppTest render kolom (narasi muncul untuk non-netral,
  tidak muncul untuk netral).

## 2026-08-16 — Detektor 3 sinyal bottom (arena/01a00a8e-wallet-depth)

- Mengganti total framework Efisiensi Anomali (R/M/baseline/S1–S5/ABSORBSI
  LANGSUNG/PENYERAPAN) dengan **3 sinyal bottom tervalidasi empiris**:
  🟢 SELLER_EXHAUSTION (CVD runtuh vs flush ≤ -30 SOL/5 hari + volume kering
  ≤40%), 🟣 REVERSAL (runtuh sama + volume naik ≥130%), 🔵 AKUMULASI
  (CVD ≥ +5 SOL, harga ≤ +0.5%, volume naik ≥130%). Urutan cek persis
  exhaustion → reversal → akumulasi → "—".
- Threshold final di `effort_detector.py` sesuai spesifikasi (30/0.40/5/0.5,
  0.40/1.30, 5.0/0.5/1.30, whale 40%, anti-wash 3× MC close bila MC tersedia).
- Perbandingan volume antar-hari kini **selalu USD** (`amount_usd`), bukan
  SOL: `cvd.py` membawa `amount_usd` pada tiap swap (GMGN: langsung dari API /
  quote terverifikasi; Helius fallback: estimasi SOL×harga SOL),
  `cvd_daily.py` mengagregasi `volume_usd`/`buy_usd`/`sell_usd` per hari.
- Batas hari tetap 00:00 UTC; alias peninggalan WIB (`day_key_wib`,
  `completed_wib_dates`, `get_daily_candles_wib`, `WIB`) dihapus.
- 4 penanda on-chain ditangkap per trade (`maker_tags`, `maker_token_tags`,
  `maker_event_tags`) lalu diagregasi harian: `smart_money_buy`, `fresh_buy`,
  `bot_sell`, `mev_noise` — info output saja, bukan syarat sinyal.
- `marketcap_close` harian = close × supply (supply ≈ MC/harga DexScreener)
  untuk gerbang anti wash-trade; tanpa MC, gerbang dilewati sesuai spesifikasi.
- Scan seluruh window: `classify_all` memberi sinyal per hari (hari pertama
  "—"); `classify_effort` = verdict hari terakhir.
- Telegram (`signals.py`) hanya untuk 3 sinyal, format konsisten "⚡ BOTTOM
  TERDETEKSI — $SYMBOL" + emoji 🟢/🟣/🔵 + hari/flush + `CVD: X SOL |
  Volume: Y% dari kemarin` + link GMGN; gate menolak "—" dan semua sinyal lama.
- UI: watchlist `app.py` menampilkan sinyal (badge warna per sinyal), CVD,
  volume vs kemarin, narasi flush + penanda whale/on-chain; halaman CVD
  menampilkan chart harga/CVD + chart volume USD, tabel harian dengan kolom
  `volume_usd`/`marketcap_close`/4 penanda, CSV + rekapan teks format baru
  (`# <date>  <SIGNAL> | Δ<+%>% | CVD <+x> | vol <y>% dari kemarin`).
- Storage `daily_effort.json` tetap upsert idempoten (window 30 hari; kini
  bernama `STORAGE_WINDOW_DAYS`, bukan sinyal retensi).
- Test: `tests/test_effort_detector.py` ditulis ulang (exhaustion/reversal/
  akumulasi + boundary 40%/130%/+5 SOL, flush lookback 5, price cap, wash
  gate, whale, tag passthrough, UTC, export, rekapan, storage);
  `test_daily_pipeline.py` menambah uji volume USD, penanda on-chain,
  marketcap_close; `test_effort_alert.py` untuk format/gate Telegram baru;
  `test_baseline_detail.py` digantikan `test_signal_detail.py` (AppTest badge
  & detail); `test_manual_refresh.py` diperbarui untuk wiring supply.

# 2026-08-30 — Silent accumulation 12 jam (buang semua sinyal)

- Menghapus seluruh sinyal (SMART SEROK / reversal / effort bottom) dan
  notifikasi Telegram: `signals.py`, `serok_engine.py`, `reversal_engine.py`,
  `reversal_state.py`, `reversal_status.py`, `price_structure.py`,
  `effort_detector.py`, `scripts/realtime_reversal.py`,
  `scripts/backtest_confidence.py`.
- Baru: `silent_accumulation.py` (holder real vs dust + flow 12 jam),
  `silent_status.py` (snapshot `silent-live`), `scripts/scan_silent.py`
  (cron 15 menit), `daily_store.py` (storage harian tanpa sinyal).
- Dashboard `app.py` & `trending_ui.py`: kolom Real >$10 / Dust / Dust %MC /
  Status 12 jam saat scan Trending & Degen.
- Endpoint `token_holders` diverifikasi paginasi `next` (limit 1000/page).

# 2026-09-01 — Grafik holder + scan FULL dengan baseline permanen

- `holder_history.py`: titik history kini membawa `holder_count` dan
  `buckets` (jumlah holder per range USD) sehingga komposisi holder bisa
  digambar sepanjang waktu. Baru: `bucket_counts`, `detail_snapshot`,
  `baseline_for_mint`, `latest_detail_for_mint`, `bucket_delta`,
  `bucket_series`, konstanta `FULL_SCAN_MAX_WALLETS = 100_000`.
- Scan manual halaman Holder = **FULL** (paginasi Helius sampai habis) dan
  memanggil `ingest_many(..., detail=True)`. Detail scan pertama disimpan
  sebagai `baseline` per token dan **tidak pernah ditimpa**; scan FULL
  berikutnya hanya memperbarui `latest_detail`.
- `scripts/scan_silent.py` (cron 15 menit) memakai `detail=False`: hanya
  menambah titik perubahan, baseline milik user tetap utuh.
- `pages/5_🧮_Holder.py`: seksi **📊 Grafik holder** (total/dust/real/pilar +
  area komposisi bucket) dan **🧱 Distribusi holder (scan FULL)** (bar chart
  Wallet Depth, metrik tier, tabel Δ bucket vs baseline).
- `silent_accumulation.fetch_holders_helius`: pengaman paginasi tidak lagi
  dipatok 60 halaman — ikut `max_wallets` (batas keras 200 halaman).
- Tes: `tests/test_holder_page.py` (AppTest) + kasus baru di
  `tests/test_holder_history.py`.

# 2026-09-03 — Bersih-bersih silent accumulation + ambang dust tunggal

- Ambang dust hanya satu: **≥ 1% MC = BAHAYA** (sekaligus filter hide
  Scan Meteora). Ambang 2% / label HATI-HATI / DUMP dihapus.
- Hapus sisa silent accumulation: `fetch_12h_flow`, `detect_silent`,
  filter SILENT/LP/PUMPDUMP, `enrich_rows`, bridge
  `scripts/realtime_reversal.py`. Rename `silent_accumulation.py` →
  `holder_analysis.py`, `silent_status.py` → `holder_status.py`
  (`holder_status.json`, ref `holder-live`), `scripts/scan_silent.py` →
  `scripts/scan_holders.py`.
- Scanner cron exit non-zero bila semua token 0 holder / publish gagal;
  dashboard menampilkan peringatan bila data cron kosong.
- Workflow perlu env `GITHUB_TOKEN` + `HELIUS_API_KEY` (harus di-commit
  manual — GitHub App tanpa permission `workflows`).

# 2026-09-03 — Ambang HATI-HATI 0,5% + card Chart LP (watchlist Meteora terpisah)

- `holder_history.py`: dua ambang dust — `DUST_CAUTION_PCT = 0.5`
  (**HATI-HATI**, badge kuning, tidak disembunyikan) dan `DUST_DANGER_PCT =
  1.0` (**BAHAYA**, `hide=True` → tetap disaring dari Scan Meteora).
  `dust_flag` mengembalikan level `ok`/`caution`/`danger`/`unknown`; helper
  baru `dust_level_rank` untuk sorting. Alias lama `DUST_CAUTION_PCT =
  DUST_DANGER_PCT` diganti nilai sebenarnya.
- Badge & grafik mengikuti: `app.py` (`.dust-caution`, panah ↑ juga untuk
  caution), `pages/5_🧮_Holder.py` (warna badge + `axhline` 0,5% pada grafik
  dust 4 jam), caption/hero menyebut kedua ambang.
- Modul baru `lp_watchlist.py` (murni data + figure, tanpa Streamlit):
  `split_watchlist` (token `source=meteora`/`lp`/`chart_lp` → card LP,
  sisanya watchlist holder; tidak ada token yang muncul dua kali),
  `build_lp_row`/`lp_card_rows` (dust % MC, dust count, Δ 4 jam & Δ total
  dalam poin persentase, level, `has_chart`), `sort_lp_rows` (BAHAYA →
  HATI-HATI → AMAN lalu % MC terbesar), `lp_summary`, `lp_chart_figure`
  (garis dust % MC + batang wallet dust + garis ambang 0,5%/1%),
  `lp_overlay_figure` (semua token LP dalam satu grafik).
- `app.py`: card **🌊 Chart LP — Watchlist Meteora** di bagian paling atas
  (`st.container(border=True)`) berisi header pill (jumlah token / BAHAYA /
  HATI-HATI / dust naik), overlay chart, form **➕ Tambah CA manual ke Chart
  LP**, dan baris per token: MC + waktu scan, dust count, Hold %MC + badge,
  Δ 4 jam & total, sparkline, expander grafik per token (+ Wallet Depth),
  tombol 🧮 / 📋 (pindah ke watchlist holder) / ✕.
- Watchlist holder di bawah hanya berisi token non-LP, kolom tombol bertambah
  🌊 (pindah ke Chart LP). Form **➕ Tambah token** punya radio *Masuk ke
  card* (📋 Watchlist Holder / 🌊 Chart LP) + validasi CA (Solana base58 /
  EVM) lewat `_ca_error`; pesan push-error kini membaca kunci `msg` yang
  benar dari `get_last_push_error()`.
- Scan Meteora: ⭐ memakai `source=meteora` → token langsung masuk Chart LP;
  caption menyebut badge HATI-HATI dan card tujuan.
- `watchlist.py`: op journal baru `"source"` (`set_watchlist_source(ca,
  source)`) untuk pindah card — `_apply_ops` menimpa `source` tanpa membuat
  entri baru, `_op_is_applied`/`_prune_pending` membuang op setelah repo
  mencerminkannya, dan `_journal_many` melebur op `source` ke op `add` yang
  belum ter-commit supaya entri baru tidak hilang. `add_to_watchlist`
  mengambil symbol dari DexScreener setiap kali symbol tidak diketahui
  (sebelumnya hanya `source="manual"`).
- Tes: `tests/test_lp_watchlist.py` (split/order/ringkasan/figure/ambang),
  `tests/test_watchlist_source.py` (op `source`, prune, journal merge,
  `set_watchlist_source`), `tests/test_lp_card_ui.py` (AppTest: card LP
  terpisah, badge HATI-HATI/BAHAYA, grafik, tombol pindah, radio tujuan
  tambah manual, validasi CA), dan `DustFlagTest` diperbarui untuk tiga
  level. Total 228 tes lulus.
