# Kegiatan — 6 September 2026 (sesi 4 · ✕ watchlist responsif + fetch Robinhood 5 menit)

Permintaan user: **"perbaiki juga hapus dari watchlist robinhood, kurang
responsif, lalu percepat fetch untuk watchlist robinhood menjadi 5 menit
sekali."**

## 1. Hapus dari watchlist: tidak lagi menunggu GitHub di dalam rerun

Diukur dengan stub RTT 0,8 dtk (skrip sementara; angka di log Actions nyata
lebih besar): satu klik ✕ = **2,40 s** tertahan dan **3 panggilan HTTP** di
jalur klik — `remove_from_watchlist()` → `_load_and_merge()` menarik remote
(sampai 3 GET × timeout 10 dtk) lalu `save_watchlist()` → `_github_push()`
(GET sha + PUT, 3 percobaan × timeout 15 dtk + backoff). Saat API melambat
klik bisa mendekati ±2 menit, dan setiap render ulang ikut mem-flush journal
yang gagal → terasa "kurang responsif".

**Perbaikan (`watchlist.py`)** — kontrak baru untuk jalur UI, flag
`background=True` (default `False` untuk cron/skrip):

1. state dibaca **lokal** (`_load_and_merge(local_first=True)`: cache
   `_REMOTE_CACHE` → file watchlist) — nol HTTP;
2. journal + tulis file lokal seperti semula;
3. `_seed_remote_cache()` memasang state baru sebagai "remote terbaru" →
   render ulang berikutnya **tidak** pull (TTL load watchlist 15 → **60 dtk**);
4. commit ke GitHub di **thread daemon** `_queue_github_push` (satu worker per
   file; job terbaru menimpa job lama, jadi klik cepat beruntun = satu commit
   final); journal dibersihkan hanya setelah commit sukses;
5. `load_watchlist()` melewati flush inline selama `push_inflight()` benar
   (mencegah balap 409 dengan worker); dispatch "scan sekarang"
   (`request_immediate_scan`) pindah ke `dispatch_scan_async()` dengan rem 10s.

Terukur setelahnya: **1,4 ms** untuk klik + 0,9 ms render ulang, **0 HTTP** di
jalur klik. Badge status di kepala card Robinhood: `🔄 sinkron…` /
`⚠️ belum sinkron` (`push_status()`). Dipakai di semua jalur UI: ✕/📋/⚡ di
card Robinhood (lp & biasa), ✕/📋 Chart LP, ✕/🌊 watchlist holder, form tambah
(Solana + Robinhood), tombol ➕ di `pages/4_📊_CVD.py` dan
`pages/5_🧮_Holder.py`.

## 2. Fetch watchlist Robinhood jadi tiap 5 menit

Kadens lama = **satu angka** (`FAST_SCAN_INTERVAL_SEC` 15 menit) untuk Chart
LP Meteora **dan** Robinhood LP, dijaga chain dispatch `WAIT=900-NOW%900+20`.
Yang diminta hanya Robinhood, jadi lane dipecah (`scripts/scan_holders.py`):

| Lane | Kadens | Konstanta |
| --- | --- | --- |
| 🦅 Robinhood LP | tiap run = ±5 menit | `RH_FAST_SCAN_INTERVAL_SEC` = `RUN_SCAN_INTERVAL_SEC` = 300 |
| 🌊 Chart LP Meteora | slot ±15 menit | `METEORA_LP_SCAN_INTERVAL_SEC` + gate baru `lp_slot_due(now, snapshot.updated_at)` |
| 📋 biasa (Solana + Robinhood) | slot 4 jam | `REGULAR_SLOTS` 16 → **48** |

- Cron `*/15` → **`*/5`** dan chain `900` → **`300`**. Berkas
  `.github/workflows/daily-effort.yml` **ditolak GitHub** saat di-push/PUT
  (GitHub App tanpa izin `workflows`, 403), jadi workflow lengkapnya disiapkan
  di root repo sebagai **`daily-effort-5menit.yml`** untuk disalin lewat UI
  GitHub; selama belum disalin cron tetap 15 menit dan lane Robinhood ikut 15
  menit (tidak ada yang rusak — scanner sudah mendukung keduanya).
- **`MIN_RUN_GAP_SEC` 840 → 240 dtk.** Ini wajib: gate run ganda dibaca dari
  umur snapshot, dan kalau ambangnya ≥ kadens run (5 menit), lane Robinhood
  justru dibungkam gate-nya sendiri. Invarian ini dites.
- **`holder_history.MIN_POINT_GAP_SEC` 8 → 4 menit.** Bug yang dicegah:
  titik yang lebih muda dari ambang **ditimpa**, jadi dengan run tiap 5 menit
  dan ambang 8 menit store Robinhood tidak pernah punya lebih dari satu titik
  (grafik/Δ membeku). `FiveMinuteCadenceTest` mengunci
  `MIN_RUN_GAP_SEC ≤ MIN_POINT_GAP_SEC < kadens run`.
- Solana **tidak** ikut 3× lebih sering: run di luar slot LP tidak memanggil
  Helius sama sekali (log `Rencana scan: … slot_lp=bukan`), jadi kuota
  Helius tetap. Repo publik → menit Actions gratis (±288 run/hari,
  sebagian besar tidur di langkah chain).
- Alert **tidak** ikut spam: bucket pengingat ⚡ `FAST_BUCKET_SEC` sengaja
  tetap 15 menit per token (`telegram_alerts`), hanya caption UI yang berubah.
- Teks UI mengikuti: label radio, caption card, `chain_note` baris
  ("LP · scan ±5 menit"), help tombol ⚡, caption "Cadens cron" — Chart LP
  Meteora tetap tertulis ±15 menit.

## 3. Bug silang jaringan di `watchlist._github_push` (ikut diperbaiki)

Sebelum merge journal di-push, fungsi itu selalu membaca
`watchlist_pending.json` (**journal Solana**) — padahal ia dipakai untuk tiga
file: `watchlist.json`, `watchlist_robinhood.json`, **dan**
`holder_status*.json` (publish snapshot). Artinya op `add` yang masih tertunda
di satu jaringan disuntikkan ke payload file jaringan lain
(`_apply_ops(latest_remote, pending_solana)`), bahkan ke snapshot dashboard.
Sekarang `_github_push(..., pending_path=…)` membaca jurnal **milik file yang
sedang ditulis** (diteruskan oleh `save_watchlist`, `load_watchlist`, dan
worker latar belakang), dan `holder_status.publish_holder_status` mengirim
`merge_journal=False` karena file snapshot tidak punya jurnal operasi.
Dua uji `GithubPushJournalIsolationTest` menguncinya.

Selain itu tulis-baca journal kini dilindungi `_JOURNAL_LOCK` (RLock): worker
latar belakang mem-prune jurnal tepat setelah commit sukses, dan tanpa lock
op yang baru ditulis thread UI pada detik yang sama bisa ikut terhapus
(token muncul lagi di render berikutnya).

## Verifikasi

`python -m pytest -q` → **824 hijau** (sebelumnya 794; +30) dan
`python -m unittest discover -s tests -t .` lolos. Test baru:
`tests/test_watchlist_background_push.py` (12: nol HTTP di
jalur klik, commit di thread lalu journal dibersihkan, push gagal = journal
dipertahankan + status `error`, coalescing, flag sinkron tidak berubah,
badge/`push_status`, rem dispatch), `ScanCadenceTest` di
`tests/test_scan_holders.py` (konstanta + `lp_slot_due` + `build_scan_plan`
+ dua integrasi `main()` dengan jam tersumbat: tengah slot hanya Robinhood,
di slot LP Solana ikut, gate run ganda membungkam semuanya),
`FiveMinuteCadenceTest` di `tests/test_holder_history.py` (3), dan 5 test UI
di `tests/test_rh_card_ui.py` (✕/📋 wajib `background=True`, caption ±5 menit,
badge sinkron). Test lama yang memassert kwargs pemanggilan diperbarui
(`tests/test_lp_card_ui.py`, `tests/test_robinhood_watchlist.py`).

# Kegiatan — 6 September 2026 (sesi 3 · tautan 🧮 Holder + scan Robinhood jujur)

Laporan user: menempel URL `…streamlit.app/…/pages/5_🧮_Holder.py?mint=0x1a3876…`
dengan keterangan **"belum berfungsi"**.

## 1. Penyebab: tautan memakai path file, bukan slug halaman

Streamlit tidak melayani file `pages/` lewat path file-nya. Registry runtime
app ini dibaca lewat websocket `/_stcore/stream` dan berisi `url_pathname`:
`CVD`, `Holder`, `Deteksi_Akumulasi`, `Pre-Pump`; frontend mencocokkan URL
dengan `pathname.endsWith('/' + urlPathname)` (case-sensitive). Jadi
`pages/5_🧮_Holder.py?mint=…` tidak cocok dengan halaman mana pun →
"Page not found" + halaman utama yang jalan → `?mint=` tak pernah dibaca
halaman Holder. (Dua uji `tests/test_rh_card_ui.py` sudah merah di HEAD karena
ganti tombol → anchor ini.)

**Perbaikan:** `links.page_url_path()` (mirror aturan Streamlit
`source_util.page_icon_and_name`, fallback lokal identik) + `page_url()` yang
root-absolute dan menghormati `server.baseUrlPath` →
`holder_analytic_url(ca)` = `/Holder?mint=…`. **Jaring:** modul baru
`page_router.py` + `page_router.apply()` di awal `app.py` memantulkan
`mint|ca|token|address` (opsional `page=<slug|nomor|file|path>`) yang mendarat
di halaman utama ke `st.switch_page` — tautan lama yang sudah tersebar ikut
pulih. CA divalidasi (base58 Solana / `0x`+40 hex), registry alias dibaca dari
folder `pages/` (tidak ada path hardcoded), penanda
`st.session_state["_deep_link_routed"]` mencegah pantulan berulang.

## 2. Scan holder Robinhood tidak boleh tampil sebagai "dust 0,00%"

Snapshot `holder_status_robinhood.json` di ref `holder-live` (dibaca langsung)
menunjukkan `total_fetched: 0, wallets_analyzed: 0, dust_count: 0,
dust_pct_mc: 0.0` untuk **0x1a38… (Onboard)** dan **0x8490… (VLAD)** padahal
VLAD punya 2.929 wallet di history — scan provider gagal, dan untuk chain ini
hasilnya tetap di-publish (jalur Solana sudah disaring `holders_usable`,
jalur Robinhood belum).

- `robinhood_holders._jsjson`: error sementara (429/5xx/timeout) diulang 1×
  dengan jeda 3 detik; `fetch_token_info` melempar bila Blockscout membalas
  `status: "0"` (sebelumnya diam-diam jadi `decimals: -1` lalu seluruh scan
  pulang dengan 0 wallet); `fetch_holders` menyalin alasan ke `error` dan
  `analyze_token` menempelnya sebagai `holders.fetch_error`.
- `robinhood_watchlist.publish_scan(..., skip_unusable=True)`: analisis yang
  `holders_usable`-nya False tidak masuk snapshot (aturan cron Solana), titiknya
  tetap di-ingest dengan penanda `degraded`, dan token mewarisi angka lama
  lewat `merge_status`.
- Baris card Robinhood di `app.py` kini menulis
  **"⚠️ scan terakhir tidak lengkap (Blockscout getToken: 429 …)"**; halaman
  Holder menambahkan "Alasan provider: …" di peringatan scan pendek.

## Verifikasi

`python -m pytest -q` → **794 passed** (sebelumnya 758 passed + 2 failed).
Uji baru: `tests/test_page_router.py` (13), `HolderDeepLinkTest` di
`tests/test_links.py` (assert slug == `page_icon_and_name` untuk **semua** file
`pages/`), `ProviderFailureTest` di `tests/test_robinhood_watchlist.py`, guard
publish + pesan baris di `tests/test_rh_card_ui.py`.

# Kegiatan — 5 September 2026 (sesi 2 · scan 15 menit + titik high)

Empat permintaan user: (1) watchlist **Meteora (Chart LP) & Robinhood LP**
di-scan cron tiap **±15 menit** (awalnya minta 30 menit, dikoreksi jadi 15
"agar exit bisa lebih early"); watchlist lain tetap ±4 jam; (2) bila hold
dust **> 0,1% MC**, pemberitahuan dikirim **berulang** sampai token
dihapus dari watchlist atau dipindah ke watchlist biasa; (3) watchlist
Robinhood lama diganti **"watchlist Robinhood LP"**, terpisah dari
watchlist Robinhood biasa; (4) titik acuan alert watchlist biasa bukan
lagi snapshot awal melainkan **hold % MC terbesar (titik high)** — turun
**≥ 50% dari titik high** mengirim alert Telegram.

## 1. Cron 15 menit untuk watchlist LP (Meteora + Robinhood LP)

`scripts/scan_holders.py` punya `build_scan_plan()`: token LP
(`source=meteora` / watchlist Robinhood LP) **due tiap run**, watchlist
biasa hanya di **slot 4 jam** (`REGULAR_SLOTS` 16/hari) atau saat token
baru belum punya titik (`token_needs_scan`), plus catch-up bila slot
terlewat (`REGULAR_CATCHUP_SEC` 3,75 jam). Flag baru `--scope
auto|fast|all` (auto = default cron; fast = hanya LP; all = dispatch
manual) + gate run ganda (`recently_published`, `MIN_RUN_GAP_SEC` 14
menit) yang bisa dilewati `--ignore-gap`. Run cepat mem-publish snapshot
dengan `merge_status` — token biasa di luar slot diwariskan agar
dashboard tidak kehilangan baris. Blok Robinhood best-effort (gagal
jaringan tidak merahkan cron) kini juga dipecah LP/biasa dengan scope
rule masing-masing.

`.github/workflows/daily-effort.yml` **tidak bisa diedit/dipush lewat
bot** (GitHub menolak tanpa izin `workflows` — push ditolak saat sesi
ini). Isi lengkap workflow baru disiapkan di **`daily-effort-15menit.yml`**
(berkas di luar repo, satu tingkat di atas folder repo): cron `*/15`,
input dispatch `scan_all` (menjalankan `--scope all --ignore-gap`) dan
`telegram_test`, langkah "Chain run berikutnya" men-dispatch run
berikutnya tepat setelah batas 15 menit, permissions
`contents: write` + `actions: write`, concurrency `holder-scanner`.
Salin isinya ke `.github/workflows/daily-effort.yml` lewat GitHub UI.
Catatan: `--max-wallets 3000` masih disematkan di workflow (menjaga
durasi run ≤ 45 menit pada slot 4 jam) — hapus manual bila mau FULL
100 ribu di cron.

## 2. Pengingat ⚡ > 0,1% MC berulang (level-based)

`telegram_alerts.evaluate_early_dump_rule()` berubah dari crossing-based
menjadi **level-based**: selama dust % MC di atas `DUST_BEST_PCT`
(0,1%), tiap evaluasi mengirim event — naik, turun sedikit, atau hover
sama. Frekuensi dibatasi bucket **15 menit** (`FAST_BUCKET_SEC`) +
cooldown `EARLY_DUMP_RESEND_SEC` (15 menit); turun ke ≤ 0,1% MC = reset
otomatis. Scope rule = watchlist Meteora (Chart LP) + **Robinhood LP**.
Penghenti hanya: hapus token (✕) atau pindah ke watchlist biasa (📋 di
baris Robinhood LP, 📋 `lp-move` di Chart LP).

## 3. Watchlist Robinhood dipecah dua card

`robinhood_watchlist` punya `RH_LP_SOURCE` / `RH_REGULAR_SOURCE` +
`split_robinhood_watchlist()` (default/manual = LP; `"regular"` =
biasa). `app.py` merender **dua card**: "🦅 Watchlist Robinhood LP —
Holder Dust" (scan ±15 menit, pengingat ⚡ berulang) dan "🦅 Watchlist
Robinhood — Holder Dust" (scan ±4 jam, rule 🔔 titik high), lengkap
tombol pindah ⚡/📋 antar card, form tambah dengan radio tujuan card, dan
caption kadens masing-masing.

## 4. Rule 🔔 HIGH DROP: titik acuan = titik high

`telegram_alerts` baru: `evaluate_high_drop_rule()` +
`high_drop_marker_next()` dengan marker `{high, high_ts, notified_high}`
(satu alert per titik high). Naik ke high baru / keluar zona drop =
re-arm. Konek ke cron: `process_holder_alerts(lp_mints=…,
high_mints=…, watchlist_meta=…)` — `high_mints` = watchlist biasa
Solana + Robinhood biasa. Turun ≥ 50% dari titik high mengirim alert
"🔔 DUST TURUN ≥ 50% DARI TITIK HIGH" tanpa gerbang volume keras
(konteks pasar info saja). Caption + selectbox urut baris watchlist
menyebut rule titik high.

## Verifikasi

`python -m unittest discover tests` — 725 test hijau (termasuk 14 test
baru `tests/test_high_drop.py`, 2 test `ScanScopeMergeTest`, revisi
test early dump ke semantik bucket 15 menit). `py_compile` semua modul
teredit lolos.

# Kegiatan — 5 September 2026

Dua permintaan user: (1) token yang sudah ada di watchlist maupun baru
ditambahkan menjadi **titik awal holder analytic** — cron mulai sekarang
scan **holder FULL** sehingga kronologi bisa langsung dilihat tanpa scan
manual; (2) baris watchlist diurut dari **minus dust holder terbesar**
(contoh: GPRO −60% sejak masuk harus di atas, Sue juga).

## 1. Watchlist = titik awal holder analytic; cron scan FULL

Sebelumnya hanya tombol manual "Scan holder FULL" di halaman Holder yang
memanggil `ingest_many(detail=True)` — baseline (snapshot FULL pertama)
dan kronologi tidak pernah terbentuk untuk token yang tidak pernah di-scan
manual. Sekarang `scripts/scan_holders.py`:

- `--max-wallets` default = **FULL** (`holder_history.FULL_SCAN_MAX_WALLETS`
  100.000, sama dengan tombol scan FULL manual; sebelumnya 3000) dan
  `ingest_many(..., detail=True)` — scan pertama setelah token masuk
  watchlist (token lama maupun baru) menulis **baseline immutable** (titik
  awal), tiap run berikutnya memperbarui `latest_detail` + interval
  **kronologi** (bounded: `MAX_CHRONOLOGY_INTERVALS` 24, snapshot 400
  wallet, 40 movement/interval) yang tampil di halaman Holder.

Biaya ekstra hanya untuk token > 3.000 holder (token ≤ 3.000 sama seperti
sebelumnya). Teks kosong di halaman Holder diperbarui: "Belum ada scan
FULL" kini menyebut cron otomatis ≤ ±1 jam. Tes baru
`tests/test_scan_holders.py::CronFullScanTest` memastikan cron memakai
`detail=True` + `FULL_SCAN_MAX_WALLETS`.

Catatan: baris `--max-wallets 3000` di `.github/workflows/daily-effort.yml`
belum bisa dihapus lewat bot (butuh izin `workflows` di repo) — sampai
dihapus manual, cron produksi masih terbatas 3.000 wallet/token; token
≤ 3.000 tidak terpengaruh, baseline + kronologi tetap jalan.

## 2. Watchlist: minus dust holder terbesar di atas

`watchlist_detail.py` mendapat `row_sort_key()` + konstanta
`SORT_DROP` (default) / `SORT_PCT` / `SORT_NAME`. Default baris watchlist
di `app.py` kini diurut dari `pct_change` "Sejak masuk" paling **negatif**
(dust % MC turun paling banyak — GPRO −60%, Sue — di baris paling atas);
token tanpa pembanding ditaruh di bawah. Ada selectbox "Urutkan baris
watchlist" untuk beralih ke dust % MC tertinggi / nama A–Z. Tes unit
`RowSortKeyTest` + AppTest urutan `DRP(−75%) → SYN(+137%) → RSE(+200%)`.

# Kegiatan — 4 September 2026

Permintaan user: halaman baru **🚀 Pre-Pump Screener** — deteksi memecoin
yang mendekati pump lewat sinyal on-chain + velocity volume. Modul baru
`pre_pump_screener.py` (scope: **hanya watchlist `source=degen`**), section
di `app.py` + halaman mandiri `pages/7_🚀_Pre-Pump.py`.

1. **Empat sinyal** → `PUMP SCORE` 0–10 (rata-rata berbobot 0,25 × 4 × 10),
   kartu per token diurut skor menurun: ✅ Liquidity Wave (add kedua ≥ 5x
   dalam 48 jam; 3x untuk likuiditas < $25k), ⚠️ Holder Consolidation
   (≥ 5 wallet keluar dari dust + avg bag real ≥ 2x), 🔥 Volume Spike
   (calm-before-storm 7 hari), 📊 TX Velocity (akselerasi ≥ 1,5 +
   buy_pressure ≥ 0,65). Shortcut kartu: 🔗 Chart (DexScreener), 👥 Holders,
   📈 CVD, plus link GMGN/Dex.
2. **Journal likuiditas** `pre_pump_liq.json` (gitignored): DexScreener tidak
   menyediakan riwayat likuiditas, jadi tiap scan mencatat `liquidity.usd`
   per pool (72 jam / 900 titik). < 2 observasi → confidence likuiditas
   dikunci **0,3**, bukan 0 dan bukan 1; pola dua gelombang baru terbaca
   setelah beberapa run.
3. **Tiga koreksi atas blueprint** (semuanya dijelaskan di docstring):
   (a) syarat "24 jam ≤ 30% rata-rata" + "6 jam ≥ 2x baseline" mustahil
   benar bersamaan bila 24 jam-nya trailing → window tenang dihitung pada
   24 jam **sebelum** window 6 jam (`vol_ratio_24h_trailing` tetap
   dilaporkan, `VOLUME_SPIKE_BASE="daily"` mengembalikan pembacaan harfiah);
   (b) auto-refresh memakai `st.fragment(run_every=300)` + `st.rerun`, bukan
   `while True: time.sleep(300)` yang membuat script Streamlit tidak pernah
   kembali (UI beku); (c) `app.py` tidak punya tab bar, jadi screener masuk
   sebagai section yang memanggil `main(configure_page=False)` —
   `st.set_page_config` hanya boleh sekali per halaman.
4. **Guard sinyal palsu**: token tanpa snapshot holder tidak pernah dihitung
   sebagai konsolidasi (`_snapshot_usable`); tanpa `HELIUS_API_KEY`, TX
   velocity jatuh ke agregat `txns` DexScreener dengan confidence dibatasi
   0,6; history < 24 jam → sinyal volume `available: False` ("tidak tahu",
   bukan "tenang"); snapshot 24 jam tidak ada → pakai titik tertua + tandai
   `stale`.
5. **Tes**: `tests/test_pre_pump_screener.py` (64 kasus: filter watchlist,
   gelombang add + journal, konsolidasi holder, profil volume, velocity
   Helius/DexScreener, skor, kartu UI lewat AppTest, integrasi `app.py`).
   Total suite 508 → **572 test, OK**.

# Kegiatan — 4 September 2026 (lanjutan)

Tiga permintaan user: (1) halaman baru **Deteksi Akumulasi** dengan 8 metrik,
(2) koreksi metrik 4 supaya **GMGN saja** (kuota Helius terlalu boros),
(3) detail baru di baris watchlist — perubahan dust sejak masuk + warna ambang
— dan perbaikan sinkronisasi data watchlist ↔ scan terakhir.

## 1. Halaman `pages/6_🔎_Deteksi_Akumulasi.py` + modul `accumulation.py`

Semua logika masuk modul **baru** `accumulation.py` (murni kalkulasi, tanpa
Streamlit, **tanpa satu pun request jaringan**); halaman hanya menarik bahan
mentah lewat fetcher yang sudah ada dan merender hasilnya. Sumber daftar token
**selalu** `watchlist.load_watchlist()` — bukan listing Meteora/trending, dan
tidak ada file watchlist baru.

| # | Metrik | Bahan mentah (fetcher lama, reuse) |
|---|---|---|
| 1 | Tier Migration Velocity | bucket wallet depth dua titik `holder_history` terakhir |
| 2 | Diamond Hands Ratio | posisi net per wallet dari swap GMGN |
| 3 | Pola DCA vs One-off Buy | jumlah buy unik + dominasi satu buy per wallet |
| 4 | Smart Money / PnL Wallet | **GMGN**: `maker_tags` + `realized_profit` |
| 5 | Silent Range Accumulation | `core.get_market` + `calculate_volatility_metrics` + CVD net swap |
| 6 | Spring / Test Pattern | candle 4 jam (agregasi dari `core.get_hourly_candles`) vs level support D1 |
| 7 | Fresh Wallet Prep | tag `fresh_wallet` GMGN + pola waktu buy |
| 8 | Sell-Side Liquidity Thinning | posisi net per wallet tanpa jual 14 hari |

Setiap fungsi mengembalikan `{key, nama, nilai, nilai_text, status,
status_label, penjelasan, cukup_data, bobot, detail, sumber}`. `cukup_data`
False **selalu** dipaksa ke status `tidak_cukup_data` dan tidak ikut pembagi
skor (pola `available` di `calculate_volatility_metrics`): "tidak tahu" tidak
pernah dihitung "netral". Skor 0–100 ≥ 60 → **Terindikasi Akumulasi**, selain
itu **Netral**, tanpa data → **Tidak Cukup Data**.

**Koreksi user (metrik 4)** — riwayat PnL lintas token lewat Helius Enhanced
API **tidak diimplementasikan**: terlalu boros kuota Helius. Yang dipakai
metadata per-wallet yang sudah diparsing `cvd._extract_gmgn_trade_meta`
(`realized_profit`, `unrealized_profit`, `maker_tags` ∩
`cvd_daily.SMART_MONEY_TAGS`). Konsekuensinya ditulis jujur di `penjelasan`
dan `detail["catatan"]`: angka PnL = realized profit wallet itu **pada token
ini** menurut GMGN, bukan rekam jejak lintas token. Seluruh halaman ini
**tidak** memanggil Helius sama sekali (dijaga tes
`tests/test_accumulation_page.py::test_helius_is_never_touched`).

**Adaptasi karena modul yang disebut spec tidak ada di repo ini** (dicek:
tidak ada `signals.py`, `breakout_guard.py`, `breakout_log.py`, `ai_prompt.py`,
`levels.json`, `history.json`, `conviction.json`, `cvd.json`, `breakouts.json`,
juga tidak ada test `test_breakout_guard.py` / `test_scoring_continuity.py` /
`test_markup_ai_prompt.py`):

- metrik 1 memakai `points[].buckets` dari `holder_history.json` (label
  `>$0-$10` … `>$500k`; repo ini tidak punya boundary $1M),
- metrik 6 menurunkan level support D1 sendiri
  (`accumulation.derive_support_level` dari candle harian
  `core.get_daily_candles`) karena `levels.json` tidak ada,
- metrik 7 memakai tag `fresh_wallet` GMGN: **identitas funder tidak tersedia**
  tanpa scan Helius, jadi yang diukur pola "wallet baru beli bertahap tanpa
  jual", dan disclaimer itu ditulis eksplisit di penjelasan metrik.

State baru disimpan di file **terpisah** `accumulation_history.json` (skema
`wallet-depth-accumulation-v1`, git-ignored) — hanya skor/status + proporsi
thinning per run, dipakai metrik 8 untuk menunjukkan arah (delta pp) dari waktu
ke waktu. Format `watchlist.json`, `holder_history.json`, `holder_status.json`
tidak diubah.

## 2. Baris watchlist: kolom "Sejak masuk" + sinkronisasi (modul `watchlist_detail.py`)

1. **Delta sejak masuk** — `dust_change_since_added()` membandingkan titik
   pertama **pada/setelah** tanggal `added` dengan **scan terakhir**: perubahan
   relatif %, poin persentase (satuan rule alert), dan perubahan jumlah wallet
   dust. Tooltip memuat semuanya + umur window; bila belum ada titik setelah
   tanggal masuk, pembandingnya titik pertama dan itu ditandai.
2. **Warna sesuai ambang user** — `tone_for_change()`: turun **≥ 50%** = hijau
   `#15803d`, naik **≥ 100%** = merah `#b91c1c`, di antaranya abu-abu; nilai
   awal 0% → "—" (perubahan relatif dari nol tidak bermakna).
3. **Sinkronisasi watchlist ↔ scan terakhir** — akar masalahnya sama dengan
   kasus "grafik 0,7% tapi kartu 1,16%" di permintaan ke-4: baris watchlist
   membaca snapshot `holder_status.json` (cron) sedangkan sparkline membaca
   `holder_history.json` yang sudah memuat titik scan manual/scan lebih baru,
   dan caption "Terakhir scan" memakai `status.updated_at` global. Perbaikan:
   `resolve_view()` memilih sumber **terbaru** per baris (menandai `drift` bila
   snapshot ≠ titik history > 0,01 pp, dan `stale` bila umur data > 2 jam),
   `previous_pct()` memilih pembanding badge yang benar (bucket sebelum nilai
   yang ditampilkan, bukan `sampled[-2]`), tiap baris kini menulis
   `scan <waktu> · titik history · ⚠️ snapshot ≠ history · basi`, dan caption
   card diganti `sync_caption_text()` — satu waktu "Scan terakhir" + rincian
   berapa token memakai snapshot cron / titik history lebih baru / belum ada
   data / basi.
4. **Perubahan `app.py` dibatasi rendering**: impor `watchlist_detail`, hitung
   `view`/`change` sekali per token, tambah kolom **Sejak masuk** (7 → 8
   kolom), dan ganti caption. Tidak ada logika kalkulasi baru di `app.py`, dan
   `lp_watchlist.py` / `holder_status.py` / `holder_history.py` tidak disentuh.

## 3. Tes

`tests/test_accumulation.py` (59), `tests/test_watchlist_detail.py` (37),
`tests/test_watchlist_row_ui.py` (5, AppTest `app.py`),
`tests/test_accumulation_page.py` (6, AppTest halaman baru + guard "Helius
tidak tersentuh" + store snapshot di temp dir). Semua tanpa jaringan dan tanpa
pytest, mengikuti pola suite yang ada.

```
Ran 615 tests ... OK   (sebelumnya 508)
```

# Kegiatan — 3 September 2026

Dua permintaan user: ambang **HATI-HATI** untuk dust holder dan watchlist
terpisah **Chart LP** untuk token hasil Scan Meteora.

1. **Ambang dust jadi dua tingkat**: `≥ 0,5% MC = HATI-HATI` (badge kuning,
   peringatan dini) dan `≥ 1% MC = BAHAYA` (tetap disembunyikan dari Scan
   Meteora). `holder_history.dust_flag` mengembalikan level
   `ok`/`caution`/`danger`, helper baru `dust_level_rank`; badge di `app.py`
   + halaman Holder, dan grafik 4 jam kini punya garis ambang 0,5% & 1%.
   (Catatan: user sempat menulis 5%, lalu dikoreksi menjadi **0,5%**.)
2. **Card 🌊 Chart LP di paling atas dashboard**: watchlist terpisah berisi
   token `source=meteora`. Modul baru `lp_watchlist.py` menyiapkan baris
   data + figure: grafik perubahan dust holder per token (dust % MC + jumlah
   wallet dust + garis ambang), overlay semua token LP, Δ 4 jam & Δ total
   dalam poin persentase, sparkline, dan urutan BAHAYA → HATI-HATI → AMAN.
   Token LP tidak muncul lagi di watchlist holder bawah.
3. **Tambah manual ke card Meteora**: form ➕ Tambah token punya radio
   *Masuk ke card* (📋 Watchlist Holder / 🌊 Chart LP), card LP punya form
   CA sendiri, ⭐ di Scan Meteora menulis `source=meteora`, tombol 🌊/📋
   memindahkan token antar card lewat `watchlist.set_watchlist_source`
   (op journal baru `"source"`, aman terhadap push gagal / entri baru).

# Kegiatan — 1 September 2026

Fokus UI ke **analisa holder dust** (bukan silent 12 jam) + Scan Meteora.

1. Watchlist: buang Status/Net/Harga 12j, Real, Dust kolom lama, Scan,
   shortcut CVD. Ganti ringkasan dust (jumlah wallet + % MC), badge
   AMAN / HATI-HATI (≥1%) / DUMP (>2%), sparkline 4 jam, tombol 🧮 ke
   halaman Holder Analytic.
2. Trending/Degen: buang kolom Real/Dust/Dust%MC/12 Jam/Net 12j dan
   scan holder. Listing GMGN saja (Token, MC, 24h).
3. Halaman baru `pages/5_🧮_Holder.py` (di bawah CVD): dust, grafik 4
   jam, sisa token kohort Crab+Fish.
4. CVD: buang 🧮 Holder Analytic + kartu silent 12 jam.
5. `holder_history.py` + `holder_history.json`: catat dust/kohort tiap
   scan, resample 4 jam. Cron watchlist holder-only.
6. Scan Meteora di halaman utama: API 24h (fee_ratio≥250) + 1h (≥1),
   DLMM active_tvl≥1000. Pool 24h yang masih di 1h tetap tampil. Dust
   >2% MC disembunyikan. Shortcut Meteora DLMM + HawkFi.

# Kegiatan — 31 Agustus 2026 (lanjutan)

**Migrasi total sumber data ke Helius** (kecuali listing Trending/Degen
yang memang hanya ada di GMGN):

1. Fix bug konversi holder Helius: `amount` DAS adalah unit RAW → dibagi
   `10^decimals` mint (decimals dari DAS `getAsset`, fallback RPC
   `getTokenSupply`; per-item bila tersedia; abort bersih bila tidak
   ketemu). Sebelumnya nilai USD holder 10^decimals× lebih besar (tier
   Shark bernilai triliunan $).
2. `_fetch_holders_snapshot`: **Helius dulu, GMGN
   fallback**. `fetch_swaps` Enhanced API diprioritaskan juga di
   `scripts/update_cvd.py` (fetch harian CVD) dengan fallback GMGN.
3. **Solscan API dilepas total**: `solscan_holders.py` hanya tersisa
   kalkulasi `wallet_depth` (bucket/tier); `get_solscan_key` +
   `solscan_api_key` dihapus; nilai `holder_source=solscan` lama otomatis
   jatuh ke `auto` (= Helius). Opsi sumber kini `auto`/`helius`/`gmgn`.
4. Tier Helius sekarang mengecualikan LP/pool via `pair_addresses`
   DexScreener; legend/ikon UI menghilangkan 📡 Solscan.
5. Workflow `daily-effort.yml` **belum** bisa diubah via push (GitHub App
   tanpa permission `workflows`) — tambahkan manual env `HELIUS_API_KEY` /
   `HELIUS_API_KEYS` di step scan (lihat snippet di README); tanpa secret
   → otomatis fallback GMGN.

# Kegiatan — 31 Agustus 2026

Holder token watchlist diambil dari **Solscan**, plus **Wallet Depth by
Threshold** ala halaman analytics Solscan.

## Yang dikerjakan

1. `solscan_holders.py`: fetch holder Solscan — Pro API `v2.0/token/holders`
   bila `SOLSCAN_API_KEY` ada (tiap baris membawa `value` USD + `percentage`
   dari Solscan), fallback Public API `token/holders` (nilai USD =
   balance × harga app), lalu fallback GMGN/Helius. Normalisasi ke bentuk
   holder GMGN; LP/pool (dari `pair_addresses` DexScreener) ditandai bukan
   wallet.
2. `wallet_depth()`: **bucket** `>$0-$10` … `>$500k` atas semua akun
   (seperti chart Solscan) dan **tier** 🦐/🦀/🐟/🐬/🦈 atas wallet murni —
   count, total value, % marketcap per bucket/tier.
3. `silent_accumulation.analyze_token` punya `holder_source`
   (`gmgn`/`solscan`/`auto`, default config `holder_source` = `auto`):
   watchlist (cron & tombol scan lokal) Solscan dulu; listing
   Trending/Degen tetap GMGN. Saat sumber Solscan, `holders["depth"]` +
   `holders["api"]` ikut tersimpan di snapshot `silent_status`.
4. UI watchlist: ikon 📡 Solscan di kolom Real, expander per token
   "📊 Wallet Depth by Threshold" berisi dua tabel (bucket & tier).
5. Workflow cron menerima env `SOLSCAN_API_KEY` (repo secret, opsional);
   `config.example.json` + docs diperbarui. Catatan: bila GitHub App
   menolak push perubahan `.github/workflows`, tambahkan env tersebut
   manual di settings repo.

Tidak diubah: logika silent 12 jam, filter holder depth (SILENT/LP/
PUMPDUMP), listing Trending/Degen.

# Kegiatan — 19 Agustus 2026 (lanjutan)

- Token baru: fetch penuh **48 jam** (bukan incremental), lalu kirim Telegram
  untuk **semua** sinyal di window itu (historis tetap dikirim, sekali per
  `event_id`).
- Payload Telegram: hari (WIB), jam bar, range harga, range MC, R/CVD/TX,
  link GMGN + DexScreener. Tag “Historis” vs “Sinyal baru”.
- `add_to_watchlist` memanggil `request_immediate_scan()` (workflow_dispatch)
  agar 48 jam ditarik segera, lalu cron 15 menit menyambung incremental.

# Kegiatan — 19 Agustus 2026

Port sinyal ekstensi [SMART_SEROK v9.1.3](https://github.com/lparmycalprut/SMART_SEROK) ke wallet-depth.

## Yang dikerjakan

1. **Watchlist dikosongkan** (`watchlist.json` = `{}`).
2. **Symbol otomatis** saat CA manual: field ticker dihapus di form Streamlit;
   `watchlist.fetch_token_symbol()` memanggil DexScreener.
3. **Sinyal diganti** dari wash-collapse / SBR menjadi:
   - 🔴 WASPADA DUMP
   - 🟢 SIAP2 PUMP
   - ⚔️ BATTLE TERJADI
   Engine: `serok_engine.py` (bar 1 jam, R ≥10× prev + |R|≥10, battle gap ≤2.5% + P65).
4. **Scan tiap 15 menit** (intended cron `*/15`). File workflow tidak bisa
   di-push oleh GitHub App (butuh permission `workflows`) — ubah manual
   `.github/workflows/daily-effort.yml` menjadi `*/15 * * * *`. Fetch 48 jam.
5. **Telegram** rapi: judul + `$SYMBOL`, syarat, R/CVD/TX/wallet, range MC (battle),
   jam WIB, tautan GMGN + DexScreener. Satu alert per `event_id`.
6. **Tes** `tests/test_serok_engine.py`; payload Telegram & UI disesuaikan.
   `python -m unittest` untuk modul baru lulus.

Tidak diubah tanpa perlu: halaman CVD, listing Trending/Degen, fetch GMGN,
persist watchlist GitHub.

# Kegiatan — 30 Agustus 2026

Refactor besar: **buang semua sinyal + Telegram**, fokus **silent
accumulation 12 jam** dan **holder depth**.

## Yang dikerjakan

1. Hapus modul sinyal (serok, reversal, effort, price_structure), scanner
   realtime, dan transport `signals.py` (Telegram) beserta secrets.
2. `silent_accumulation.py`: fetch holder GMGN paginasi `next`
   (verified limit 1000/page, `limit=1000`), klasifikasi real holder
   (>$10 value) vs dust (0 < value <= $10), dust % dari marketcap,
   net flow 12 jam (`token_trades`), deteksi silent (net >= $50,
   >= 3 akumulator, |harga| <= 5%, bot <= 35%).
3. `silent_status.py` + `scripts/scan_silent.py`: cron tiap ~15 menit
   publish snapshot ke ref `silent-live`.
4. `app.py` & `trending_ui.py`: kolom/holder-depth langsung saat scan
   Trending/Degen (real count, dust count, dust %MC, status 12 jam).
5. Halaman CVD: chart flow harian tanpa sinyal; `daily_effort.json`
   dipertahankan sebagai agregasi murni (`daily_store.py`).
6. Workflow `daily-effort.yml` target: Silent Accumulation 12H Scanner tanpa
   `TELEGRAM_*`. Catatan: file workflow tidak bisa di-push oleh GitHub App
   (butuh permission `workflows`), jadi `scripts/realtime_reversal.py`
   dipertahankan sebagai adapter ke `scan_silent.py` agar cron tetap
   berjalan; ubah workflow manual bila ingin langsung memanggil
   `scripts/scan_silent.py`.

Tidak diubah tanpa perlu: watchlist GitHub, fetch GMGN/Helius, listing
screener.
## Lanjutan hari yang sama — konfirmasi volume + volatilitas (permintaan ke-3)

User mengirim prompt baru: alert dust 0,25 pp masih sering false positive,
jadi tiap sinyal harus divalidasi volume + harga + volatilitas dulu, tetap
reaktif (< 5 menit), dan ambang dust yang ada tidak boleh diubah.

1. **Volume correlation** — `validate_alert_with_volume()` di
   `telegram_alerts.py`: dump butuh volume 4 jam ≥ 2× `avg_volume_7d`
   **dan** harga ≤ −1%; akumulasi butuh ≥ 1,5× **dan** tekanan beli >
   tekanan jual. Skor 0,70 dasar + ≤0,15 volume + ≤0,10 harga/tekanan +
   0,20 volatilitas tinggi yang mendukung arah; gagal gerbang → ≤0,40.
   `avg_volume_7d` dibaca sebagai rata-rata **per window 4 jam** selama
   7 hari agar sebanding dengan `volume_4h`. Semua kandidat yang ditolak
   di-log + dicatat ke `rejected_signals` supaya bisa diaudit.
2. **Volatility metrics** — `calculate_volatility_metrics()` di
   `holder_history.py` dari 16 candle hourly: `price_stddev_4h`,
   `price_range_4h`, `intra_hour_volatility`. Kalau `price_stddev_4h > 3%`
   ambang skor naik dari 0,70 ke **0,80** — dan karena volatilitas tinggi
   tanpa dukungan arah harga tidak memberi bonus, ambang itu benar-benar
   menyaring (terukur 0,702 < 0,80). Hasilnya disimpan berdampingan
   dust % MC di `holder_status.json` sebagai `tokens[mint].market_signal`.
3. **Sumber konteks** — `alert_context.py` (baru): candle hourly
   GeckoTerminal → DexScreener (data yang sudah diambil `analyze_token`,
   tanpa request tambahan) → `daily_effort.json`. Ditarik **lazy**: hanya
   token yang punya kandidat (keputusan user), memo 1× per token per run,
   jadi latensi run normal tidak bertambah. `core.get_hourly_candles()`
   baru dan `get_daily_candles()` kini agregasi dari candle yang sama.
4. **Data hilang** (keputusan user): alert tetap dikirim, diberi baris
   `⚠️ TIDAK TERVERIFIKASI` dengan skor 0,50 — jadi tidak ada sinyal yang
   hilang diam-diam saat GeckoTerminal mati.
5. **Dedup 1 jam** — selain event id bucket 4 jam, kini ada jeda minimum
   1 jam per token+jenis(+arah) lewat `alert_state.last_sent`; sebelumnya
   dua alert identik bisa terkirim berjarak ±2 menit di sekitar batas
   bucket.
6. **Review optimasi** (diminta user, tabel lengkap di
   `docs/PROGRESS.md`): heap untuk `matching_dexscreener_pairs` diukur
   **tidak** lebih cepat sehingga tidak diubah; `get_daily_candles`
   diperbaiki (sel null, `limit_days=0`, timestamp duplikat) dan batas UTC
   diverifikasi sampai kasus kabisat; `classify_holders` dibuat single-pass
   ramping (2,86 → 1,94 ms per 12k holder, keluaran identik di 500 trial);
   `wallet_movements()` tidak lagi dihitung dua kali; dua `TODO(alerts)`
   (429 `retry_after`, throttle GeckoTerminal).
7. **Tes** — 6 file baru, 141 tes tambahan: 369 lulus (sebelumnya 228),
   termasuk edge case volume 0, avg 0/None, NaN/inf, candle bolong,
   candle < 2, candle basi, payload DexScreener rusak, provider gagal,
   cooldown 1 jam, dan lazy-fetch.
## Permintaan ke-4 — AGENTHQ: grafik 0,7% tapi kartu "Dust hold % MC" 1,16%

User melaporkan angka yang tidak cocok di halaman Holder Analytic. Setelah
ditelusuri (snapshot live di ref `holder-live` + DexScreener), ada dua lapis
penyebab dan **bukan** bug grafik:

1. **Kartu metrik dan grafik membaca dua sumber berbeda umur.** Kartu metrik,
   badge, dan caption membaca snapshot `holder_status.json` (cron 21:35 WIB),
   sedangkan grafik membaca `holder_history.json` yang sudah memuat titik scan
   manual yang baru dijalankan. Tombol scan FULL hanya `ingest_many(detail=True)`;
   ia tidak mempublish snapshot — dan memang tidak boleh, karena
   `snapshot_status` membangun `tokens` hanya dari analyses yang diberikan
   (publish satu token = token lain hilang dari dashboard).
2. **Harga sedang pump +74% dan cutoff dust itu $10 dalam USD.** harga
   0,0001085 → 0,0001889, MC $108.545 → ±$188.968. dust % MC invariant
   terhadap harga, tetapi **klasifikasi**-nya tidak: wallet dengan 52.938–
   92.166 token (nilai lama $5,74–$10) "lulus" menjadi real >$10, sehingga
   ±40% nilai dust pindah bucket dan dust % MC turun 1,16% → 0,7% tanpa ada
   yang jual. Cerminannya (harga turun) menaikkan dust % MC ±0,4-0,5 pp —
   di atas ambang dump 0,25 pp — dan itu lolos gerbang volume/harga.

Perbaikan yang dikerjakan (user memilih opsi A): `holder_status` mendapat
`compact_manual_scan()`, `resolve_token_view()`, dan `apply_manual_scan()`;
halaman Holder Analytic + `app.py` mengoverlay scan manual yang lebih baru ke
snapshot sebelum render, sehingga kartu metrik, badge, watchlist, dan Chart LP
setuju dengan grafik, dan caption menandai *scan manual barusan*. Guard
re-klasifikasi harga (opsi B) belum dikerjakan — keputusannya (**annotate,
bukan reject**) dicatat sebagai `TODO(alerts)` di `telegram_alerts.py`.
Tes: 27 murni + 2 AppTest baru → **398 lulus**.
