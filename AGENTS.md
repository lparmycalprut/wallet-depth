# AGENTS.md — Wallet Depth

Dashboard token Solana. Fokus: **analisa holder dust** (jumlah + % MC,
grafik 4 jam, kohort Crab+Fish) dan **Scan Meteora DLMM**, ditambah
**🚀 Pre-Pump Screener** (4 sinyal on-chain untuk token watchlist
`source=degen`, lihat `pre_pump_screener.py`). Tidak ada silent accumulation
/ flow 12 jam; Telegram hanya dipakai cron untuk alert perubahan holder dust
yang sudah dikonfirmasi volume + harga + volatilitas.

## Sumber kebenaran

- `holder_history.py`: store `holder_history.json` (+ backup durable
  `holder_history.json.gz`, lihat bawah), freeze kohort 4 jam,
  resample grafik 4 jam, ambang dust **≥ 0,5% MC = HATI-HATI** dan
  **≥ 1% MC = BAHAYA** (hanya BAHAYA yang disembunyikan dari Meteora).
  **`DUST_BEST_PCT = 0.1`** (badge 🏆 BEST POOL, label
  `DUST_BEST_LABEL = "BEST POOL"`) bersifat **aditif**: `dust_flag(pct,
  prev, *, holders=...)` mengembalikan `best: bool` tanpa mengubah
  level/label/hide lama; guard `_holders_valid_for_best` menolak data
  kosong/gagal (`total_fetched <= 0`, `< 40 wallet`). `MAX_POINTS = 1008` —
  jendela titik mentah per token, dikalibrasi ke densitas run LP 5 menit
  (±3,5 hari = 21 bucket 4 jam; dulu 336 untuk cron hourly/15 mnt); UI tetap
  memakai `resample_4h` (maks 84 bucket 4 jam).
  Baseline scan FULL immutable + kronologi wallet bounded
  (`holder_chronology.py`). **Sejak 2026-09-05 cron ikut scan FULL +
  `detail=True`** — scan pertama setelah token masuk watchlist menjadi
  `baseline` (titik awal holder analytic) dan kronologi terakumulasi
  otomatis (interval per scan FULL, `MAX_CHRONOLOGY_INTERVALS` 24).
  `calculate_volatility_metrics()` = metrik
  volatilitas 4 jam dari candle hourly (`price_stddev_4h`, `price_range_4h`,
  `intra_hour_volatility`, `missing_hours`, `stale`); candle < 2 →
  `available: False` (artinya "tidak tahu", bukan "tenang").
  **Sejak 2026-09-06** modul ini juga pemilik lantai kelayakan data holder:
  `MIN_USABLE_WALLETS` (40) + `scan_degraded()` / `holders_usable()` /
  `point_wallets()` / `point_usable()` / `usable_points()`; titik dari scan
  bersampel pendek ditandai `degraded: True` saat `ingest_one` (penanda ikut
  `compact_point`). Lihat "Kelayakan data holder" di tabel ambang bawah.
- **Scan holder dari halaman utama** (`app.py`) tidak boleh mengganti
  snapshot: selalu `publish_holder_status(..., merge_status=holder_status)`
  (tanpa merge, `snapshot_status` membangun `tokens` **hanya** dari analyses
  yang diberikan → token yang gagal/timeout pada run itu hilang dari
  dashboard dan nilai terakhirnya terbuang), filter analyses dengan
  `holders_usable` supaya scan bersampel pendek tidak menulis apa pun, dan
  biarkan `ingest_many(..., detail=False)` agar baseline scan FULL +
  `latest_detail` + kronologi tidak tertimpa. Tombol Robinhood
  (`robinhood_watchlist.publish_scan`) berlaku sama — saringan
  `holders_usable` dipasang di sana (2026-09-06) sehingga scan yang gagal /
  mengembalikan 0 wallet **tidak pernah** masuk snapshot
  `holder_status_robinhood.json`; titiknya tetap dicatat (ditandai
  `degraded`) supaya jejak kegagalan terlihat, dan token itu mewarisi angka
  lama lewat `merge_status`. Alasan provider dibawa sebagai
  `holders["fetch_error"]` (dulu ditelan `classify_holders` sehingga "dust
  0 wallet" terbaca seperti hasil nyata).
- **Tautan halaman internal = slug, bukan path file.** Streamlit memberi
  setiap file `pages/` URL dari nama file yang sudah dibersihkan (prefiks
  nomor + emoji leading dibuang): `pages/5_🧮_Holder.py` → `/Holder`,
  `pages/4_📊_CVD.py` → `/CVD`; frontend mencocokkan dengan
  `pathname.endsWith('/' + url_pathname)` sehingga `pages/5_🧮_Holder.py`
  **bukan route** (app jatuh ke halaman utama + "Page not found"). Karena itu
  tautan 🧮 dibangun lewat `links.page_url_path` / `links.page_url` (slug +
  `server.baseUrlPath`) dan **jangan** disambung manual. `page_router.apply()`
  — dipanggil paling awal di `app.py` — memantulkan `?mint=|ca=|token=|address=`
  (opsional `?page=<slug|nomor|file|path>`) yang mendarat di halaman utama ke
  halaman yang dituju lewat `st.switch_page`, supaya tautan lama tetap hidup;
  registry alias dibaca dari folder `pages/` (tanpa hardcoded), CA divalidasi
  format, dan penanda `st.session_state["_deep_link_routed"]` mencegah loop.
- `lp_watchlist.py`: card **Chart LP** — watchlist terpisah berisi token
  `source=meteora`; baris data (dust % MC, Δ poin persentase, level) +
  figure matplotlib grafik perubahan dust holder (garis ambang 0,5% / 1%)
  dan overlay semua token LP. Murni data/figure, tanpa Streamlit. Badge
  🏆 BEST POOL **tidak** dirender di card ini (scope: listing Scan
  Meteora saja, keputusan user) — `build_lp_row` memanggil
  `dust_flag(pct, prev)` tanpa `holders`, jadi `best` selalu False.
- `holder_chronology.py`: perbandingan scan FULL (balance token, kategori
  `wallet_depth`, link Solscan). Tanpa LLM. Schema lama tetap bisa dibaca.
- `meteora_screener.py`: pool-discovery Meteora 24h (`fee_ratio≥250`) +
  1h (`fee_ratio≥1`), `active_tvl≥1000`, DLMM. Pool 24h yang masih di 1h
  tetap tampil. Dust ≥ 1% MC dibuang; ⭐ di UI memakai `source=meteora`
  sehingga token masuk Chart LP. Badge 🏆 BEST POOL dirender di `app.py`
  (`_dust_best_html`), bukan di modul ini.
- `holder_analysis.py`: **Helius** sumber holder utama
  (`fetch_holders_helius`, fallback GMGN). `analyze_token` = holder
  real/dust + mid-tier + kohort. `extra_pools` + `cohort_addrs`
  untuk Meteora / kohort.
- `solscan_holders.py`: hanya kalkulasi `wallet_depth`.
- `helius_holders.py`: Scan Holder Khusus satu token.
- `core.py`: config/key Helius, pasar DexScreener (`get_market` ikut
  mengembalikan `volume`, `price_change`, `txns`), candle GeckoTerminal —
  `get_hourly_candles()` (mentah, per jam) dan `get_daily_candles()`
  (agregasi hari UTC; **hari UTC yang masih berjalan ikut ter-return**,
  saring dengan `cvd_daily.completed_dates`).
- `alert_context.py`: konteks pasar untuk konfirmasi alert — volume 4 jam,
  rata-rata volume per window 4 jam selama 7 hari, perubahan harga,
  buy/sell pressure, volatilitas. `market_context_provider()` = memo per
  token; `compact_signal()` untuk disimpan ke status. Ditarik **lazy**.
- `holder_status.py`: snapshot `holder_status.json` → ref `holder-live`
  (ikut `history` 4 jam dan `market_signal` bila konteks pasar tersedia).
  Snapshot **ramping**: peta balance alert, peta kohort, dan peta wallet
  kronologi tidak ikut (hanya jumlah + sampel movements ≤20/interval,
  ≤12 interval) — terukur 2,87 MB → **0,30 MB** untuk 36 token (−90%). Data penuh itu hidup di
  backup store (bawah). Transport-nya generik: `_github_get_bytes` /
  `_github_put_bytes` (+ pembungkus JSON) dipakai `holder_status.json` dan
  `holder_history.json.gz` (`pull_store_backup` / `push_store_backup`).
  `snapshot_status` **tidak merge** token lama: publish satu token akan
  menghapus token lain, jadi scan manual di halaman Holder tidak boleh
  publish. Overlay `apply_manual_scan()` / `resolve_token_view()`
  (`st.session_state[MANUAL_SCAN_KEY]`) membuat kartu metrik, badge,
  watchlist, dan Chart LP ikut scan manual yang lebih baru daripada snapshot
  cron — grafik sudah lebih dulu memuat titik itu dari `holder_history.json`.
- `scripts/scan_holders.py`: cron watchlist. **Kadens run ±5 menit sejak
  2026-09-06** (dulu 1×/jam → ±15 menit); lane diatur scanner, bukan cron:
  **KEDUA lane LP tiap run** (Chart LP Meteora + Robinhood LP, ±5 mnt —
  permintaan user: "buat meteora juga, per 5 menit, biar perubahan holder bisa
  langsung ketahuan"), **watchlist biasa slot 4 jam** (48 slot × 5 menit).
  Beban API naik 3× di kedua chain; katup hematnya
  `LP_SCAN_RUN_MULTIPLIER` (env, default 1) → `lp_slot_due(now,
  status.updated_at)` menahan scan **Solana** sampai tiap N run kalau kuota
  Helius menipis, tanpa menyentuh kode. Tiga invarian yang wajib dijaga bila
  kadens diubah lagi: `MIN_RUN_GAP_SEC` (gate run ganda) dan
  `holder_history.MIN_POINT_GAP_SEC` harus **di antara** gate itu dan kadens
  run tercepat — kalau ambang titik ≥ kadens, tiap titik baru menimpa titik
  sebelumnya dan history lane itu berhenti tumbuh
  (`tests/test_holder_history.py::FiveMinuteCadenceTest`); dan
  `holder_history.MAX_POINTS` harus ikut density run supaya jendela grafik LP
  tidak menyusut (`ScanDensityCalibrationTest`). Yang SENGAJA tidak ikut
  dipercepat: bucket pengingat ⚡ Telegram (`telegram_alerts.FAST_BUCKET_SEC`
  15 menit/token — kalau ikut, satu token dapat 3 pesan identik per 15 menit). **Pull + merge
  backup store sebelum scan**, evaluasi alert
  sebelum ingest history, publish snapshot, **push backup store
  sesudahnya**; exit non-zero bila 0 holder / publish snapshot gagal
  (backup gagal = `WARN` saja, tidak membuat cron merah). Scope rule
  ⚡ EARLY DUMP diteruskan lewat `lp_mints` = set `split_watchlist(
  watchlist)[0]` (token pool); untuk blok Robinhood di cron, `lp_mints` =
  seluruh `rh_watch` (watchlist RH tidak dipecah Chart LP). Sejak
  **2026-09-05 cron scan FULL**
  (`--max-wallets` default = `holder_history.FULL_SCAN_MAX_WALLETS`
  100.000) dan
  `ingest_many(..., detail=True)`: token watchlist (lama maupun baru)
  menjadi titik awal holder analytic tanpa scan manual. **Catatan:** baris
  `.github/workflows/daily-effort.yml` yang masih mengirim
  `--max-wallets 3000` belum bisa diubah lewat bot (butuh izin
  `workflows` di repo) — selama ada, cron produksi terbatas 3.000
  wallet/token (token ≤ 3.000 tidak terpengaruh; baseline + kronologi
  otomatis tetap jalan). Hapus flag itu dari workflow untuk FULL penuh.
  Berkas workflow **tidak pernah bisa** diubah dari sisi bot (GitHub App tanpa
  izin `workflows` → 403 saat push/PUT): perubahan kadens 2026-09-06
  (`*/5` + `WAIT=300`) karena itu disimpan sebagai `daily-effort-5menit.yml`
  di root repo untuk disalin manual — jangan dianggap sudah terpasang sebelum
  ada run Actions tiap 5 menit di tab **Actions**.

### Backup durable store holder

Runner Actions & Streamlit Cloud ephemeral, jadi `holder_history.json` hilang
tiap run. Store penuh dibackup sebagai **`holder_history.json.gz`** (gzip +
JSON compact, Contents API base64) di ref `holder-live`:

- `store_backup_bytes` / `parse_store_backup` (toleran gzip & JSON polos,
  payload rusak → `None`, tidak pernah melempar).
- `merge_stores(*stores)` — **argumen belakang menang** saat timestamp seri;
  titik union (≤`MAX_POINTS`), `baseline` **paling tua** (immutable),
  `latest_detail` terbaru, kohort yang masih punya balance lalu `frozen_at`
  terbaru, interval kronologi union per `(from_ts, to_ts)` (movements
  terbanyak menang), `alert_state` snapshot terbaru + union `sent_event_ids`
  + `last_sent` maksimum. Cron: `merge_stores(lokal, durable)`; UI:
  `merge_stores(durable, lokal)` (scan manual baru tidak ditimpa backup).
- `prune_store_for_backup` — hanya bila payload > `MAX_BACKUP_BYTES`
  (3,5 MB; terukur ~901 kB untuk 55 token jadi praktis tak pernah): buang
  movements interval lama → interval di luar 6 terbaru → peta wallet
  kronologi → `points[].buckets` → titik di luar **42 bucket 4 jam
  terakhir** (titik per jam di-`resample_4h` dulu supaya backup tetap
  ~7 hari grafik, bukan 42 jam) → `latest_detail`. **Baseline scan FULL
  dibuang paling akhir.**
- `publish_holder_history` / `pull_holder_history` /
  `load_durable_holder_history` (cache `DURABLE_CACHE_TTL` 600 detik) /
  `reset_durable_cache`. Kill-switch `HOLDER_STORE_BACKUP=0`.
- `seed_from_status` tetap jadi jaring kedua: snapshot **format lama** (masih
  membawa peta wallet) dipulihkan seperti semula, snapshot ramping
  (`summary: True` / `balances` berupa angka) **tidak** menimpa store.
- `telegram_alerts.py`: rule dust 4 jam (+0,25 pp dump; -0,50 pp + buyer
  akumulasi), perubahan ±1 pp dari baseline, **gerbang konfirmasi
  volume/harga/volatilitas**, dedup, transport Telegram, dan rule
  **⚡ EARLY DUMP** (kind `early_dump`): crossing naik melewati
  `DUST_BEST_PCT` 0,1% untuk token pool (`lp_mints` → `lp_mint` di
  `evaluate_alert_events`) maupun **seluruh watchlist Robinhood**
  (cron mengirim `lp_mints=set(rh_watch)`), **tanpa gerbang volume keras**
  (`early_dump_verdict`: `allow` selalu True, konteks pasar = info di
  pesan), ulang 1× per bucket 4 jam + `MIN_RESEND_SEC`, hanya saat dust
  masih naik; marker `alert_state["early_dump"]` = `{ts, dust_pct_mc}`
  run terakhir (di-merge paling baru oleh `holder_history._merge_alert_state`,
  dipertahankan `compact_alert_state`). Pesan selalu ditutup link token
  **🔗 GMGN + 🦆 DexScreener** dari `links.token_link_lines(mint)`; bila
  event membawa `pool_addresses`, ditambah `🌊 Meteora` + `🦅 HawkFi`
  (`_pool_link_lines`) — cron belum bisa mengisinya (watchlist tidak
  menyimpan pool address). `send_test_alert()` sengaja tanpa link. Aturan
  tidak pernah fetch: pemanggil menyuntikkan `market_context` atau
  `context_provider(mint, analysis)` yang hanya dipanggil bila ada kandidat.
- `gmgn_screener.py`: listing Trending/Degen.
- `pre_pump_screener.py`: section **🚀 Pre-Pump Screener** di `app.py`
  (`main(configure_page=False)`, watchlist/snapshot/store disuntikkan) +
  halaman mandiri `pages/7_🚀_Pre-Pump.py`. Scope **hanya watchlist
  `source=degen`** (`load_degen_watchlist`). Empat sinyal, tiap sinyal
  mengembalikan `confidence` 0–1 dan `PUMP SCORE` = rata-rata berbobot
  0,25 × 4 × 10: **A** gelombang add likuiditas (journal lokal
  `pre_pump_liq.json` — DexScreener tidak punya riwayat likuiditas; < 2
  observasi → confidence dikunci `LIQ_MISSING_CONFIDENCE` 0,3; ≥ 5x dalam
  48 jam, 3x untuk likuiditas < $25k), **B** konsolidasi holder
  (`dust_grew_out` kronologi, fallback selisih `dust_count`, + avg bag real
  ≥ 2x; tanpa snapshot sekarang **tidak pernah** menyala — lihat
  `_snapshot_usable`), **C** volume calm-before-storm (window tenang = 24 jam
  **sebelum** window 6 jam; 24 jam trailing tidak bisa dipakai karena window
  6 jam ada di dalamnya), **D** TX velocity (`cvd.fetch_swaps`, fallback
  agregat `txns` DexScreener dengan confidence dibatasi 0,6). Auto-refresh
  5 menit lewat `st.fragment(run_every=300)` + `st.rerun` — **bukan**
  `while True: time.sleep(300)` (script Streamlit tidak pernah kembali dari
  loop itu); hasil scan di-cache `st.session_state["pre_pump_results"]`.
- `links.py` (+ `page_router.py`): **tautan internal memakai slug halaman
  Streamlit, bukan path file.** `pages/5_🧮_Holder.py` dilayani di `/Holder`
  (prefiks nomor + emoji dibuang, case-sensitive — frontend mencocokkan
  `pathname.endsWith('/' + urlPathname)`); href `pages/…py` membuat Streamlit
  jatuh ke halaman utama dengan "Page not found" sehingga `?mint=` tidak dibaca
  (bug yang dilaporkan user 2026-09-06). `page_url_path()` meniru aturan
  `streamlit.source_util.page_icon_and_name` (dipakai `_mpa_v1`),
  `page_url()`/`holder_analytic_url()` root-absolute + `server.baseUrlPath`.
  `page_router.apply()` — dipanggil **paling awal** di `app.py` — memantulkan
  `?mint=`/`?ca=`/`?token=`/`?address=` (opsional `?page=`) ke
  `st.switch_page`, jadi tautan lama yang sudah tersebar tetap hidup; CA
  divalidasi dulu (base58 Solana / `0x`+40 hex) supaya sampah tidak membajak
  navigasi, dan `st.session_state["_deep_link_routed"]` mencegah loop saat
  user kembali ke dashboard. **Jangan** menulis ulang path halaman manual di
  UI; tambah tombol baru lewat helper ini.
- `pages/5_🧮_Holder.py`: Holder Analytic (di bawah CVD) + kronologi FULL.
  Sejak 2026-09-05 mendukung **dua chain**: Solana (watchlist/status/history
  utama) dan **Robinhood Chain** (`0x…`, watchlist/status/history terpisah
  lewat `robinhood_watchlist`) — pemilihan chain ikut format CA query param
  `mint`; overlay scan manual disaring per chain agar tidak bocor antar
  watchlist. Scan FULL EVM memakai `robinhood_holders.analyze_token` +
  store `holder_history_robinhood.json`.
- `pages/4_📊_CVD.py`: CVD harian saja (tanpa Holder Analytic).
- `watchlist_detail.py`: detail baris watchlist — perubahan dust **sejak
  tanggal masuk** (`added`) sampai **scan terakhir** (relatif %, poin
  persentase, jumlah wallet) dengan ambang warna **turun ≥ 50% = hijau** /
  **naik ≥ 100% = merah** (`MCAP_DROP_TONE_PCT` / `MCAP_RISE_TONE_PCT`), plus
  penyatuan angka baris ↔ scan terakhir: `resolve_view()` memilih snapshot
  cron **atau** titik history yang lebih baru (menandai `drift` bila keduanya
  berbeda > 0,01 pp dan `stale` bila > 2 jam), `previous_pct()` memilih
  pembanding badge yang benar, `sync_caption_text()` menulis satu caption
  "Scan terakhir" + rincian sumber per token. **Sejak 2026-09-06 "terbaru"
  berarti "terbaru yang datanya layak"**: snapshot/titik dari scan holder
  tidak lengkap (`holder_history.holders_usable` / `point_usable` — sampel
  < 40 wallet, mis. GMGN mengembalikan 20 holder saat Helius mati) tidak
  pernah jadi angka baris; `resolve_view()` mengembalikan `degraded` /
  `degraded_note` / `usable_points` / `skipped_scans`, UI menulis
  `⚠️ scan … cuma 19 wallet`, dan token yang semua scan-nya pendek menulis
  `belum ada data ⚠️`. Tanpa ini kolom "Sejak masuk" melaporkan **−100%**
  (dust "habis") dari sampel yang memang tidak memuat wallet dust. Urutan baris (2026-09-05):
  default `SORT_DROP` — **minus dust terbesar di atas** (`pct_change`
  "Sejak masuk" paling negatif, mis. GPRO −60%; tanpa pembanding di
  bawah), opsi lain `SORT_PCT` (dust % MC tertinggi) / `SORT_NAME`
  (alfabetis) lewat `row_sort_key()`. Murni kalkulasi.
- `accumulation.py`: 8 heuristik **Deteksi Akumulasi** (tier migration,
  diamond hands, DCA vs one-off, smart money GMGN, silent range, spring/test,
  fresh wallet prep, sell-side thinning) + skor 0–100 (`SCORE_AKUMULASI` 60)
  + store snapshot `accumulation_history.json` (skema sendiri, git-ignored).
  Setiap fungsi mengembalikan `{nilai, nilai_text, status, penjelasan,
  cukup_data, detail, sumber}`; `cukup_data=False` **selalu** dipaksa ke
  status `tidak_cukup_data` dan tidak ikut pembagi skor (pola `available`
  di `calculate_volatility_metrics`). **Tanpa satu pun request jaringan** dan
  **tanpa Helius** (keputusan user 2026-09-04): metrik 4 memakai
  `realized_profit`/`maker_tags` GMGN dari `cvd._extract_gmgn_trade_meta`,
  metrik 7 memakai tag `fresh_wallet` GMGN (identitas funder tidak tersedia
  tanpa scan Helius → ditulis eksplisit di penjelasan), level metrik 6
  diturunkan `derive_support_level()` dari candle harian
  `core.get_daily_candles` karena repo ini tidak punya `levels.json`.
- `pages/6_🔎_Deteksi_Akumulasi.py`: halaman Deteksi Akumulasi. Token **hanya**
  dari `watchlist.load_watchlist()`; fetch lewat fetcher yang sudah ada
  (`cvd.fetch_gmgn_swaps` dengan `stop_ts` + cap `max_pages`,
  `core.get_market`, `core.get_hourly_candles`,
  `holder_history.calculate_volatility_metrics`), jeda 0,4 detik antar token,
  hasil di `st.session_state`, snapshot ringkas ke `accumulation_history.json`.

Watchlist di `app.py` membaca `load_holder_status()` + `holder_history`
lalu dipecah `lp_watchlist.split_watchlist()`: **Chart LP** (card paling
atas, token `source=meteora`) dan watchlist holder biasa — satu token hanya
muncul di satu card. Tombol 🌊/📋 memanggil `set_watchlist_source()`
(journal op `source`), form tambah manual punya radio tujuan card.
Trending/Degen **tidak** menganalisa holder. Scan Meteora menganalisa
holder per mint lalu filter dust ≥ 1% MC.

### Persistensi watchlist: tulis lokal + commit latar belakang

Semua mutasi watchlist (tambah ➕, hapus ✕, pindah card 📋/⚡ — Solana **dan**
Robinhood) lewat `watchlist.add_to_watchlist` / `remove_from_watchlist` /
`set_watchlist_source` / `add_many_to_watchlist` dengan urutan tetap:

1. **journal dulu** (`watchlist_pending.json`; `save_watchlist` prune hanya
   sesudah remote menerima) — tidak boleh dipindah ke belakang;
2. tulis file watchlist lokal;
3. kirim ke GitHub (`_github_push`: GET sha → merge remote+pending → PUT,
   retry + re-fetch sha saat 409).

Langkah 3 **wajib non-blocking di jalur UI**: `app.py` dan `pages/` selalu
meneruskan `background=True`, yang men-*seed* `_REMOTE_CACHE` dengan state baru
lalu menyerahkan commit ke worker `_queue_github_push` (satu worker per
terhadap file; job terbaru menimpa job lama). Mengembalikan panggilan
sinkron di handler Streamlit = membuat klik terasa macet lagi (terukur
2,4 s/klik pada RTT 0,8 dtk, dan berlipat sampai ±2 menit saat API GitHub
lambat karena 3 percobaan × timeout 15 dtk + pull 3× timeout 10 dtk).
`load_watchlist()` me-flush journal yang tersisa, tapi **melewati** flush
inline selama `push_inflight(repo_path)` masih benar (mencegah balap 409),
dan status terakhir bisa dibaca UI lewat `push_status(repo_path)`
(badge `🔄 sinkron…` / `⚠️ belum sinkron` di kepala card Robinhood).
Pemanggil non-UI (cron/skrip) tetap default `background=False`.
`_CACHE_TTL` load watchlist 60 dtk karena perubahan lokal selalu men-*seed*
cache — menaikkan lagi TTL tidak membuat UI lebih cepat, menurunkannya
mengembali-kan round-trip tiap rerun.

## Ambang

```text
dust_limit_usd        : 10.0  (real > $10; dust 0 < value <= $10)
                          -> dust % MC TIDAK invariant harga: cutoff USD
                          menggeser klasifikasi wallet (TODO(alerts):
                          annotate re-klasifikasi, bukan reject)
dust HATI-HATI        : >= 0.5% marketcap
dust BAHAYA / hide    : >= 1% marketcap
badge BEST POOL       : < 0.1% marketcap (DUST_BEST_PCT, aditif) + data
                        holder valid: total_fetched > 0 dan >= 40 wallet
                        (DUST_BEST_MIN_HOLDERS). == 0.1% bukan BEST POOL
                        dan bukan pemicu early_dump (strict < dan >).
                        Hanya dirender di listing Scan Meteora.
grafik / kohort       : bucket 4 jam (resample_4h; titik mentah per run,
                        MAX_POINTS 1008 = 3,5 hari @ 5 menit LP)

Konfirmasi alert (setelah ambang dust di atas terpenuhi):
dump                  : volume 4 jam >= 2.0x avg_volume_7d DAN harga <= -1%
akumulasi             : volume 4 jam >= 1.5x avg_volume_7d DAN buy > sell
baseline shift +-1 pp : ikut arah perubahan (naik = dump, turun = akumulasi)
early dump (pool LP)  : crossing naik > 0.1% (dibanding nilai run
                        sebelumnya, marker alert_state["early_dump"]) —
                        scope token pool Meteora/Chart LP + seluruh
                        watchlist Robinhood Chain — TANPA gerbang volume
                        (konteks = info), sekali per bucket 4 jam + jeda
                        1 jam, hanya saat masih naik; turun ke <= 0.1% =
                        reset
skor konfirmasi       : 0.70 dasar + <=0.15 volume + <=0.10 harga/pressure
                        + 0.20 volatilitas tinggi dengan arah mendukung
ambang skor           : 0.70; 0.80 bila price_stddev_4h > 3%
volatilitas "liar"    : price_stddev_4h > 3.0% (sample stddev close 4 jam)
avg_volume_7d         : rata-rata volume PER WINDOW 4 JAM selama 7 hari
dedup                 : bucket 4 jam (event id) + jeda minimum 1 jam
data pasar tidak ada  : alert tetap dikirim, ditandai TIDAK TERVERIFIKASI
                        (ALLOW_UNVERIFIED_ALERTS = True)
mid-tier (pilar)      : Crab+Fish = $100–$10k, freeze max 200 address
max holders/token     : FULL default 100.000 (cron & tombol "Scan holder
                        FULL" halaman Holder, paginasi sampai habis) /
                        2.000 (tombol scan watchlist di app.py, titik
                        ringkas tanpa detail)

Pre-Pump Screener (pre_pump_screener.py; scope: watchlist source=degen):
liquidity wave        : add kedua >= 5x add pertama dalam 48 jam
                          -> 3x bila likuiditas pool < $25.000
                          -> langkah < $500 atau < 5% = noise harga, diabaikan
                          -> < 2 observasi journal = confidence 0,3
holder consolidation  : >= 5 wallet keluar dari dust DAN avg bag real >= 2x
                          (snapshot 24 jam +- 8 jam; di luar itu = stale,
                          confidence x 0,8)
volume calm-before    : 24 jam sebelum window 6 jam <= 30% avg harian 7 hari
                          DAN 6 jam terakhir >= 2x baseline 6 jam
                          (VOLUME_SPIKE_BASE="daily" = pembanding avg harian)
                          coverage < 24 jam = available False (bukan "tenang")
tx velocity           : (avg 2 jam akhir - avg 2 jam awal)/awal >= 1,5
                        buy_pressure >= 0,65 = whale accumulation
                        sumber DexScreener txns = confidence maksimal 0,6
PUMP SCORE            : (0,25 x jumlah 4 confidence) x 10  -> 0..10
confidence_pct        : rata-rata confidence sinyal AKTIF saja
auto-refresh          : 300 detik (st.fragment(run_every=...))
journal likuiditas    : pre_pump_liq.json (gitignored), 72 jam / 900 titik

Baris watchlist "Sejak masuk" (watchlist_detail.py):
warna hijau           : dust % MC turun >= 50% sejak tanggal masuk
                        (MCAP_DROP_TONE_PCT)
warna merah           : dust % MC naik >= 100% sejak tanggal masuk
                        (MCAP_RISE_TONE_PCT)
data basi             : umur data > 2 jam (STALE_AFTER_SEC; kedua lane LP
                        ±5 mnt sejak 2026-09-06 — ambangnya sengaja jauh
                        di atas kadens supaya hanya cron yang mati yang kena)
drift                 : |snapshot - titik history| > 0,01 pp dengan ts beda
                        (DRIFT_TOLERANCE_PP) -> baris pakai yang terbaru
urutan baris          : default minus dust terbesar di atas (pct_change
                        paling negatif sejak masuk; tanpa pembanding di
                        bawah) — SORT_DROP; pilihan lain SORT_PCT /
                        SORT_NAME lewat selectbox "Urutkan baris watchlist"

Kelayakan data holder (holder_history) — filter sebelum angka ditampilkan:
MIN_USABLE_WALLETS    : 40 (= DUST_BEST_MIN_HOLDERS); total_fetched atau
                        jumlah wallet dianalisis di bawahnya = scan tidak
                        layak (provider mengembalikan sampel pendek tanpa
                        menandai truncated; wallet dust ada di ekor daftar)
scan_degraded()       : True hanya bila ADA bukti sampel pendek/0 wallet —
                        dict tanpa info jumlah wallet (skema lama) tidak
                        ditolak, jadi perilaku lama tidak berubah
point_usable()        : titik ber-penanda degraded, tanpa dust_pct_mc, atau
                        < 40 wallet -> dibuang dari angka baris, pembanding
                        "sejak masuk", sparkline, grafik 4 jam, overlay LP
alert                 : process_holder_alerts() melewatkan scan tidak layak
                        (rule HIGH DROP tidak boleh menyala dari dust 0%
                        palsu)

Deteksi Akumulasi (accumulation.py) — semua heuristik, tanpa Helius:
skor gabungan         : >= 60 = Terindikasi Akumulasi (SCORE_AKUMULASI),
                        tanpa metrik cukup data = Tidak Cukup Data
tier migration        : tier $100-$1k & $1k-$10k naik, dust relatif stabil
                        (|delta| <= 10% = DUST_STABLE_PCT)
diamond hands         : >= 60% wallet tak pernah net-sell = positif,
                        < 35% = negatif (DIAMOND_*_PCT)
DCA                   : >= 3 buy DAN satu buy <= 60% total buy wallet
silent range          : volume 24 jam $10K–$250K (lantai wajib: token mati
                        tidak boleh terbaca terakumulasi), stddev 4 jam
                        <= 0,8x konteks, CVD net 0…+15%
spring/test           : low < level <= close, volume <= 1,0x rata-rata
                        4 candle sekitarnya (SPRING_VOLUME_RATIO)
fresh wallet prep     : >= 3 wallet fresh_wallet, >= 2 buy tersebar
                        >= 30 menit, satu buy <= 75%, 0 sell
sell-side thinning    : >= 70% posisi net di wallet tanpa jual 14 hari
floor sampel flow     : < 5 wallet teramati = tidak cukup data
                        (MIN_WALLETS_FOR_FLOW)

Wallet depth (buckets): >$0-$10 … >$500k — default wallet murni
Tier: 🦐 Shrimp ≤$100, 🦀 Crab $100-$1k, 🐟 Fish $1k-$10k,
      🐬 Dolphin $10k-$100k, 🦈 Shark >$100k.
```

Jalankan:

```bash
python -m unittest discover tests
python -m py_compile holder_history.py holder_chronology.py meteora_screener.py \
  holder_analysis.py holder_status.py telegram_alerts.py alert_context.py \
  lp_watchlist.py core.py scripts/scan_holders.py trending_ui.py watchlist.py \
  watchlist_detail.py accumulation.py pre_pump_screener.py app.py \
  "pages/7_🚀_Pre-Pump.py"
```
