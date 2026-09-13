# AGENTS.md — Wallet Depth

Dashboard token Solana. Fokus: **analisa holder dust** (jumlah + % MC,
grafik 4 jam, kohort Crab+Fish) dan **Scan Meteora DLMM**, ditambah
**🚀 Pre-Pump Screener** (4 sinyal on-chain untuk token watchlist
`source=degen`, lihat `pre_pump_screener.py`). Tidak ada silent accumulation
/ flow 12 jam; Telegram hanya dipakai cron untuk alert perubahan holder dust
yang sudah dikonfirmasi volume + harga + volatilitas.

## Pembagian halaman (2026-09-10)

- `app.py` = halaman utama: **grid 2 kolom** watchlist (`st.columns([1, 1],
  gap="medium")`) — **kiri** 🌊 Watchlist Meteora (dulu
  "Chart LP — Watchlist Meteora"), **kanan** 🦅 Watchlist Robinhood (LP).
  **🏆 Scan Best Pool Meteora** (`best_pool_ui.render_best_pool_scan()`)
  **full-width di bawah grid**, sebelum 🛰 Scan Holder (2026-09-11,
  permintaan user: "jangan dibuat grid lagi" — 2026-09-10 dulu menempel di
  bawah card Meteora di dalam grid). **🦅 Scan Best Robinhood Coin**
  diparkir di **halaman temp** (📦) sejak 2026-09-11 (permintaan user:
  "pindah ke page temp karena belum berfungsi"; 2026-09-10 dulu di bawah
  card Robinhood di dalam grid). Di bawah grid: 🏆 Scan Best Pool Meteora
  (full-width), lalu 🛰 Scan Holder Solana / Robinhood (dulu "Scan Holder
  Khusus — Helius / Robinhood", full-width). Detail **🦅 Scan Best Robinhood
  Coin** (modul `robinhood_best_scan.py`, dirender
  `temp_ui.render_temp()` di halaman temp — listing GMGN `GET
  /defi/quotation/v1/rank/robinhood/swaps/6h?orderby=volume` **publik
  tanpa auth**, filter top 10 holder < 30% + dust ≤ 0,05% MC dari
  Blockscout, urut dust terkecil lalu volume 6 jam terbesar, pernah
  Dexboost = poin tambah 🚀; baris: 📋 copy CA via `st.iframe` + ⭐
  Watchlist Robinhood LP **di halaman utama**; detail endpoint di
  `docs/gmgn_api.md`).
  **Budget waktu kandidat DIHAPUS 2026-09-10**: `scan_candidates` menunggu
  **semua** kandidat sampai selesai (`as_completed` tanpa timeout, di dalam
  `with ThreadPoolExecutor`) — `CANDIDATE_TIMEOUT_SEC = 300` dulu membuang
  kandidat lambat, padahal yang lambat itu token ber-holder puluhan ribu
  (paginasi Blockscout memang 10-15 menit per token) sehingga hasilnya sayang
  dibuang. Yang dipertahankan dari perbaikan "macet 6/7" hanya label progress
  `sedang: SYMBOL (+N lagi)` saat kandidat **mulai**. Timeout HTTP per request
  (`_get_json(timeout=25)`, `CSV_TIMEOUT`, masa parkir key PRO) **tidak** ikut
  dihapus — yang dihapus hanya batas umur scan. Paling
  bawah: **🧾 Log Aktivitas** (`activity_log.render_activity_log()`,
  2026-09-10) — ring buffer in-memory thread-safe (`activity_log.py`)
  yang mencatat kejadian penting semua card: scan mulai/selesai
  (Meteora/Best Pool/Best Robinhood/Scan Holder), parkir key PRO
  Blockscout (401/402/403/429), fallback ke instance publik, 403
  bot-protection, fetch holder gagal/terpotong, sync watchlist GitHub
  gagal. Level `action` = **perlu perubahan manual user** (pasang/ganti
  API key, kredit habis) dan dirender **merah bold**; kepala panel
  menampilkan `robinhood_holders.pro_key_summary()` (status per key) **dan
  sisa kredit key Helius** (`core.helius_usage_summary()`, permintaan user
  2026-09-10) — baris Helius dibaca dari cache ±5 menit dan disegarkan di
  **thread latar** (`core.refresh_helius_usage_async`), jadi render halaman
  tidak pernah menunggu `api.helius.xyz`; suite tes mematikan probe lewat
  `HELIUS_USAGE_PROBE=0` (`tests/__init__.py`). Bentuk respons Helius beda per
  plan; `core.parse_helius_credits()` menerima semuanya dan mengembalikan
  `None` bila tidak ada angka — **dilarang mengarang angka kredit**, UI lalu
  menampilkan hitungan request lokal (`core.helius_request_count()`). Key tidak
  pernah tampil: label `key#N` + `_scrub_key_text()`.
  Log hidup di memori proses (kosong setelah restart); modul lain
  menulis lewat `import activity_log` yang selalu dibungkus try/except
  supaya cron/tes tanpa Streamlit tetap jalan. Tiap
  section dipisah `st.divider()`. Kedua card grid
  ber-`st.container(border=True)` dengan kepala seragam dari
  `dashboard_components.card_head_html()` (pill ringkasan di sebelah judul).
  Hero header halaman (judul + ringkasan ambang) **dihapus**
  2026-09-09 bersama CSS `.hero`. **Jangan render watchlist biasa/Temukan
  Token di sini.**
- **Detail karakteristik card/section = tooltip judul (2026-09-10)** —
  caption panjang di badan card dihapus. Teksnya hidup di konstanta
  `LP_CARD_TOOLTIP` (app.py), `RH_CARD_TOOLTIP`
  (dashboard_components.py), `app.scan_holder_tooltip()` (dulu konstanta
  `SCAN_HOLDER_TOOLTIP`; **jadi fungsi 2026-09-12** supaya ambang tanda BEST
  dibaca dari `meteora_screener.BEST_DUST_MARK_PCT` saat dipanggil — pola
  yang sama dengan `best_pool_tooltip()`),
  `best_pool_ui.best_pool_tooltip()`, `temp_ui.meteora_scan_tooltip()` dan
  `robinhood_best_scan.RH_SCAN_TOOLTIP` (dua card scan best menyusul
  2026-09-10/11: caption ambangnya dihapus, seluruh isinya pindah ke tooltip —
  termasuk **🌊 Scan Meteora Pool** di halaman temp yang sebelumnya tidak punya
  tooltip sama sekali, dan caption rekap yang masih mengulang ANGKA ambang
  seperti "dust > 0,05% MC = 2, top 10 holder ≥ 30% = 1"; teks abu-abu
  penjelasan toggle Auto-refresh di halaman utama juga dihapus karena `help`
  toggle berkata hal yang sama); dirender
  sebagai atribut `title="…"` pada teks judul (`card_head_html(tooltip=…)`
  / `hover_title_html()`) sehingga **hanya muncul saat kursor digeser ke
  atas tulisan judul**. Yang boleh tersisa di badan card hanya **rekap hasil
  scan** (jumlah lolos / disembunyikan / dilewati) — itu data, bukan deskripsi
  rule. Kalau karakteristik berubah, ubah teks di konstanta itu — ambang
  **selalu** diambil dari konstanta rule (`holder_history`,
  `meteora_screener.BEST_*`, `RH_SCAN_*`) agar tidak pernah beda dengan yang
  jalan. Atribut `title` tidak mengenal markdown (plain text tanpa `**`).
  `best_pool_tooltip()` membaca konstantanya **saat dipanggil** (impor
  `meteora_screener` di dalam fungsi) supaya modul UI tetap ringan saat
  diimpor — jangan hard-code angka ambang di teksnya. Teks tooltip juga jangan
  memuat judul persis card halaman lain (emoji + `Scan Meteora Pool`):
  `tests/test_temp_page.py` memakai string itu untuk memastikan card temp
  tidak dirender di halaman utama.
  **Jangan menulis ulang deskripsi rule di caption** (permintaan user
  2026-09-11: "tulisan ini hapus donk, sudah ada di tooltip") — termasuk angka
  ambangnya; caption = hasil (angka rekap) saja. Pin regression-nya di
  pin regression-nya di `tests/test_temp_page.py::TooltipBukanCaptionTest`
  (card /temp memuat `title="Top DLMM 24 jam…"`, captionnya bebas teks rule)
  dan
  `tests/test_robinhood_best_scan.py::RenderTest`
  `.test_detail_karakteristik_di_tooltip_bukan_caption`.
- **Toggle alert Telegram per token di baris watchlist (2026-09-11)** —
  permintaan user: "kasih toggle alert on/off per token yang ada di watchlist
  meteora dan robinhood … pas awal memasukkan ke watchlist, otomatis on".
  Tombol 🔔 (ON, klik = matikan) / 🔕 (OFF, klik = nyalakan) ada di kolom
  **sebelum** 📋/⚡ dan ✕ pada ketiga baris — `lp-alert-<mint>` di
  `app.py::_render_lp_row` (scope `lp`), `rh-alert-<0x…>` dan
  `rhreg-alert-<0x…>` di `dashboard_components._render_rh_row` (scope dari
  `_rh_scope`: card LP halaman utama / card biasa halaman temp). Grid baris
  jadi **7 kolom** — sejak 2026-09-13 **8 kolom** karena kolom ke-4
  **Awal Masuk** (LP `[1.62, 0.72, 0.9, 0.8, 0.42, 0.42, 0.42, 0.42]`, RH
  `[1.62, 0.75, 0.9, 0.8, 0.42, 0.42, 0.42, 0.42]`) dan kepala card menampilkan
  pill `🔕 N` (`_muted_pill_html`) bila ada token yang dimatikan. Baris yang
  dimatikan menambah **· 🔕 notif off** di captionnya; pilihan disimpan
  `alert_settings.set_mint_alert_enabled` (pusatnya di bullet
  `alert_settings.py` di bawah — bukan `watchlist.json`). Watchlist Holder
  biasa di `temp_ui.py` **tidak** ikut diberi tombol (scope permintaan user
  = Meteora + Robinhood), tetapi `mute_mints`-nya tetap dihormati bila token
  dipindah ke sana.
- **Persentase %MC 3 desimal + metrik Dust %MC di Scan Holder
  (2026-09-12)** — permintaan user dalam tiga bagian: (1) tanda di 🏆 Scan
  Best Pool Meteora (lihat bullet `meteora_screener` di bawah); (2) kolom
  **Hold %MC** 🌊 Watchlist Meteora (`app.py::_render_lp_row`) dan 🦅
  Watchlist Robinhood (`dashboard_components._render_rh_row` — varian LP
  *dan* biasa ikut karena satu renderer) tampil **3 angka di belakang
  koma** (`.3f` — dua desimal menyembunyikan beda 0,044% vs 0,037%); (3)
  section 🛰 Scan Holder Solana / Robinhood mendapat metrik **`Dust %MC`
  tepat di kiri "Akun holder (…)"** — angkanya `classify_holders` yang
  ditempel ke `depth` di dalam `scan_token_holders` (Helius *dan*
  Robinhood: `dust_pct_mc`, `dust_count`, `dust_value_usd`,
  `dust_limit_usd`), jadi definisinya persis kolom Hold %MC watchlist
  (wallet 0 < nilai ≤ $10, LP/pool disingkirkan). Semua persen %MC di Scan
  Holder 3 desimal: metrik, label batang `depth_bar_chart` (`.3f`), dan
  kolom **% Market Cap** `_depth_tables_html` (dipakai juga tabel Wallet
  Depth nested di expander watchlist — seragam, jangan dibalikan).
- **Tulisan BEST emas kelap-kelip di 🛰 Scan Holder (2026-09-12)** —
  permintaan user: *"jika kondisi %dust <= 0.035 kasih tulisan BEST yang
  agak besar, dengan efek kelap kelip, warnanya GOLD"*. Bila
  `depth["dust_pct_mc"] <= meteora_screener.BEST_DUST_MARK_PCT` (0,035%,
  **inklusif** — ambang yang sama dengan tanda 🏆 BEST POOL card Best Pool,
  satu sumber konstanta) maka `_render_helius_holder_result` merender
  `<span class="scan-best-gold">BEST</span>` **di kolom metrik Dust %MC**
  (`c0.markdown`, tepat di bawah angkanya — tanda menempel pada buktinya),
  untuk **kedua** jalur (Helius *dan* Blockscout, satu renderer).
  HTML-nya dibuat `dashboard_components._scan_best_badge_html()` (return
  `""` bila tidak lolos → tidak ada elemen kosong), syaratnya
  `_scan_best_mark_ok()` (dust `None`/teks tak terbaca = tidak pernah
  ditandai), dan **seluruh gayanya hidup di CSS `render_styles`**
  (`.scan-best-gold`, `@keyframes scan-best-blink` = kelap-kelip opacity,
  `scan-best-shine` = kilau gradien emas menyapu, plus
  `@media (prefers-reduced-motion: reduce)` yang mematikan animasi) karena
  `st.markdown` **men-sanitasi atribut `style` inline** — jangan pernah
  menaruh warna/ukuran/animasi badge ini di atribut style. Nama class-nya
  **sengaja bukan** varian `dust-best`: pin regression card Scan Meteora
  menghitung kemunculan string class chip emas itu di seluruh body halaman
  (`tests/test_lp_card_ui.py`, `tests/test_best_pool_scan.py`), dan CSS ikut
  ter-render di body. Penanda **visual** saja — tidak mengubah metrik,
  saringan, atau angka mana pun. Rule + ambangnya dijelaskan di tooltip
  judul section (`scan_holder_tooltip()`), bukan caption. Coverage:
  `tests/test_rh_card_ui.py` (AppTest: badge tepat di 0,035 & jalur Helius,
  tidak muncul di 0,036/0,041/0,55 dan saat dust `None`, CSS + tooltip
  ikut ter-render) dan `tests/test_best_pool_scan.py::ScanHolderBestBadgeTest`
  (unit helper: batas inklusif, data hilang, tanpa `style=` inline, CSS di
  `render_styles`, ambang mengikuti konstanta).
- **Grafik perubahan dust holder seragam di semua card (2026-09-10)** —
  setiap baris watchlist (Watchlist Meteora di `app.py`, Watchlist
  Robinhood LP/biasa di `dashboard_components._render_rh_row`, Watchlist
  Holder biasa di `temp_ui.py`) memakai satu pembuat expander yang sama,
  `dashboard_components._render_dust_change(points, holders, symbol,
  interval=…)`: **📈 Grafik perubahan dust holder — $SYM** berisi grafik
  `lp_watchlist.lp_chart_figure(..., interval=…)` (garis dust % MC + garis
  ambang HATI-HATI/BAHAYA + batang jumlah wallet dust), dan tabel **📊
  Wallet Depth by Threshold** ter-nested di dalamnya bila scan menghasilkan
  `depth` — expander tabel mandiri di baris Robinhood/temp dihapus. Bucket
  mengikuti kadens lane: `LP_INTERVAL_SEC` (5 menit) untuk lane LP,
  `INTERVAL_SEC` (4 jam) untuk lane biasa; teks info < 2 bucket ikut
  mengikuti (`_dust_change_empty_note`).
- `pages/8_temp.py` → slug **`/temp`**, judul **temp**, memanggil
  `temp_ui.render_temp()`: Robinhood biasa (non-LP), Watchlist — Analisa
  Holder (Dust), **🌊 Scan Meteora Pool** (`temp_ui.render_meteora_scan()`,
  dipindah dari halaman utama 2026-09-10; ⭐-nya tetap memasukkan token ke
  card Watchlist Meteora di halaman utama), **🦅 Scan Best Robinhood Coin**
  (`robinhood_best_scan.render_robinhood_best_scan()`, diparkir dari halaman
  utama 2026-09-11 — "belum berfungsi"; ⭐-nya tetap memasukkan token ke
  card Watchlist Robinhood LP di halaman utama), dan Temukan Token
  (Trending/Degen), termasuk semua kontrol.
  Tautan `st.page_link` main ↔ temp; bukan salinan watchlist baru.
- `dashboard_components.py`: CSS/helper presentasi, card Robinhood bersama
  (`variant="lp"|"regular"`, snapshot merge diberikan eksplisit), dan
  `load_dashboard_data()` (store Solana & Robinhood terpisah, overlay scan
  manual tetap berlaku). Import modul tidak merender UI atau memuat store.
- Scan manual hanya lane card yang sedang dibuka: Solana biasa di temp
  memakai `holder_watch`, bukan seluruh watchlist termasuk Meteora LP;
  scan Robinhood memakai subset LP/biasa sesuai halaman. Semua tetap
  memakai guard kelayakan + merge snapshot. Form Robinhood tersedia di
  kedua halaman, default sesuai lane. Pemindahan UI **tidak** menghapus
  token/history, mengubah `source`, cron, atau pengaturan Telegram.
- **Alert watchlist sekarang dipisah per lane.** Watchlist Meteora tidak lagi
  memanggil `process_holder_alerts`/alert dust lama. `meteora_watchlist.py`
  menyimpan baseline metrik saat add dan mengevaluasi snapshot pool:
  24h mendeteksi quotient `fee_active_tvl_ratio / volatility` turun minimal
  30% sejak baseline, sedangkan 30m mendeteksi snapshot baru saat
  `volatility > fee_active_tvl_ratio`. State metric ringkas masuk
  `holder_status.json`; `metric_baseline` tetap di `watchlist.json`.
  Tombol 🔔/🔕 per token tetap dihormati oleh `send_metric_alerts`.
  `scripts/scan_holders.py` mengambil snapshot pool tiap lane LP, mengirim
  event metric baru, lalu tetap mencatat holder untuk grafik tanpa alert dust.
  Scan manual LP di `app.py` memakai jalur metric yang sama.
- `process_holder_alerts` dan marker `early_dump` masih dipakai lane Robinhood
  / watchlist biasa yang memang belum mempunyai metrik pool; jangan mengubah
  rule global itu saat menyentuh Watchlist Meteora. `dashboard_components.py`
  dan `temp_ui.py` tetap memakai jalur lama hanya untuk lane non-Meteora.
  Kredensial Telegram tetap lazy: env → `config.json` → `st.secrets`.

- AppTest untuk halaman temp dijalankan dari entrypoint `app.py` lalu
  `.switch_page("pages/8_temp.py")` agar registry multipage/navigation sama
  dengan deployment (bukan menjalankan file halaman sebagai main script).

## Sumber kebenaran

- `holder_history.py`: store `holder_history.json` (+ backup durable
  `holder_history.json.gz`, lihat bawah), freeze kohort 4 jam,
  resample grafik 4 jam, ambang dust **≥ 0,5% MC = HATI-HATI** dan
  **≥ 1% MC = BAHAYA** (level dipakai Chart LP/watchlist). **Sejak
  2026-09-07** `hide` = `pct > DUST_SCAN_HIDE_PCT` (0,1%): Scan Meteora
  hanya menampilkan pool dust ≤ 0,1% MC dan badge level di listing itu
  dinonaktifkan. **`DUST_BEST_PCT = 0.1`** (badge 🏆 BEST POOL, label
  `DUST_BEST_LABEL = "BEST POOL"`) bersifat **aditif**: `dust_flag(pct,
  prev, *, holders=..., tvl=...)` mengembalikan `best: bool` tanpa mengubah
  level/label; guard `_holders_valid_for_best` menolak data kosong/gagal
  (`total_fetched <= 0`, `< 40 wallet`) dan `_tvl_valid_for_best` menolak
  TVL pool `< DUST_BEST_MIN_TVL_USD` (10K) atau `None`. `MAX_POINTS = 1008` —
  jendela titik mentah per token, dikalibrasi ke densitas run LP 5 menit
  (±3,5 hari = 21 bucket 4 jam; dulu 336 untuk cron hourly/15 mnt); UI tetap
  memakai `resample_4h` (maks 84 bucket 4 jam) untuk watchlist biasa /
  halaman Holder, dan **`resample_5m` (`LP_INTERVAL_SEC` = 5 menit)** untuk
  lane LP — Chart LP Meteora + Robinhood LP di-scan tiap ±5 menit, jadi
  grafiknya 5 menitan (permintaan user 2026-09-07). Pada tanggal yang sama
  kolom tabel **`Δ 4 jam` dan `Grafik 4 jam` (sparkline) dihapus dari semua
  card watchlist**; grafik hanya tampil di expander per token.
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
- **Scan holder manual** (Chart LP di `app.py`, watchlist biasa di
  `temp_ui.py`) tidak boleh mengganti
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
- `alert_settings.py`: setelan UI yang memengaruhi cron. Dua hal, satu file
  `alert_settings.json` di ref `holder-live` lewat transport
  `holder_status._github_get_bytes/_github_put_bytes` (fallback file lokal →
  default **ON**; kegagalan API tidak boleh membisukan alert):
  1. `telegram_regular_enabled` — **on/off notif Telegram watchlist biasa**
     (Solana `source` manual/degen), tombol di `temp_ui.py` (halaman temp),
     dibaca `dashboard_components._render_rh_card` + `temp_ui` saat scan
     manual. Lane biasa tidak di-scan cron, jadi cron **tidak** membaca key
     ini.
  2. `muted_mints` — **toggle alert per token** (2026-09-11, permintaan user:
     "kasih toggle alert on/off per token yang ada di watchlist meteora dan
     robinhood … pas awal memasukkan ke watchlist, otomatis on"). Ini
     **blocklist**: default ON, jadi tidak ada yang perlu ditulis saat token
     ditambah; sebaliknya `watchlist.add_to_watchlist` /
     `add_many_to_watchlist` memanggil `forget_mint_alert(ca)` supaya token
     yang di-add **ulang** tidak mewarisi pilihan OFF lama. API:
     `mint_key` (EVM `0x…` di-lowercase, mint Solana case-sensitive),
     `muted_mints`, `is_mint_muted`, `mutes_for(mints)` (irisan siap pakai
     sebagai `mute_mints`), `set_mint_alert_enabled(mint, enabled)` (pesan
     commit `alert-settings: notif off <mint12> [skip ci]`),
     `forget_mint_alert` (no-op tanpa tulis/commit bila mint memang tidak
     dimatikan). Cron membaca `muted_mints(force_refresh=True)` **sekali per
     run** (1 request GitHub) lalu meneruskan `mutes_for(...)` per lane;
     jalur scan manual memakai fungsi yang sama, jadi cron dan dashboard
     selalu sepakat.
  **Muted = kirim dilewati, evaluasi TIDAK**: untuk Meteora, snapshot + state
  metric tetap dimajukan; untuk lane non-Meteora marker `early_dump`
  (`ts`/`dust_pct_mc`/`step`) tetap dimajukan supaya menyalakan notif lagi
  tidak membanjiri user dengan pengingat episode lama. Tombol 🔔/🔕 dirender
  per baris: `lp-alert-<mint>` (Watchlist Meteora di `app.py`), `rh-alert-…`
  + `rhreg-alert-…` (`dashboard_components._render_rh_row`, scope dari
  `_rh_scope`), plus pill `🔕 N` di kepala card dan catatan "🔕 notif off" di
  barisnya. Catatan gagal-sinkron per card lewat `_store_toggle_note` /
  `_render_toggle_note(scope)` (session_state, karena klik langsung rerun).
- `holder_chronology.py`: perbandingan scan FULL (balance token, kategori
  `wallet_depth`, link Solscan). Tanpa LLM. Schema lama tetap bisa dibaca.
- `meteora_screener.py`: regular pool-discovery Meteora dua lane **24h lalu
  30m**, `pool_type=dlmm`, `active_tvl≥50000`. 24h disembunyikan bila
  `volatility≥fee_active_tvl_ratio`; fee ≥ 5× volatility diberi **SAFE LP**.
  30m hanya menampilkan `fee_active_tvl_ratio>volatility` sebagai **HIGH RISK
  LP (PANTAU)**. `sort_regular_rows()` mengurutkan lane lalu quotient
  fee/volatility terbesar; dust > 0,1% MC tetap dibuang sebagai filter lama
  tetapi **bukan kunci urut**. `sort_rows()` dipertahankan hanya untuk
  compatibility, tidak dipanggil regular scan maupun render UI.
  Source/timeframe, fee ratio, volatility, dan dust ikut dibawa ke UI. ⭐ di
  UI menyimpan baseline Meteora ke watchlist. `row_flag()` / `row_dust_pct()`
  tetap dipakai untuk data/badge lama; Scan Best Pool Meteora memakai pipeline
  dan sorter-nya sendiri, jangan diubah.
- `meteora_watchlist.py`: normalisasi snapshot, baseline metric, deteksi 24h/30m,
  dan pengiriman alert metric tanpa mencampur rule holder-dust lane lain.
  **🏆 Scan Best Pool Meteora** (halaman utama; kriteria **diganti total**
  2026-09-11) — semua ambangnya konstanta `BEST_*` di modul ini: query API
  `best_filter_by()` = `pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000`
  (24 jam, `category=top`, `page_size=50`, `fetch_best_pools()`) sehingga
  tier fee + active TVL tersearing di server. Saringan layar tinggal tiga:
  `row_best_gaps()` (volatility ≥ `BEST_VOLATILITY_MIN` 2% **dan volume 24
  jam ≥ `BEST_VOLUME_24H_MIN` $1.000.000** — keduanya inklusif, angka
  `None` = gugur) + `row_dust_ok()` (dust < `BEST_DUST_MAX_PCT` 0,05% MC;
  angka `None` = gugur). **Volume 24 jam ≥ 1M ditambah 2026-09-12**
  (permintaan user: *"minimal volume 24 jam adalah 1M, dibawah itu jangan di
  show"*) dan ikut masuk `hidden_metric` karena volumenya metrik listing API
  — tidak butuh scan holder. Saringan fee/active TVL / top 10 holder / total
  LPs / active TVL yang lama **dihapus** — konstantanya tidak ada lagi,
  jangan dipakai ulang.
  `scan_best_meteora()` menjalankan saringan **volume 24 jam ≥ $1M**
  sebelum `enrich_pools()` (pool sepi tidak membakar kuota Helius). Pool
  volume ≥ $1M yang gagal volatility tetap di-enrich: hasilnya
  `hidden_rows` (volume ≥ 1M + dust < 0,05% MC, urut
  `sort_best_rows`) untuk tombol **N disembunyikan** di
  `best_pool_ui` (klik = listing itu; klik lagi = kembali ke yang lolos).
  Lalu `sort_best_rows()`: **volume 24 jam / active TVL
  (`volume_active_tvl_ratio` — angka persen dari API Meteora; field absen
  dihitung ulang `volume/active_tvl*100`) terbesar → dust % MC terkecil**
  (sejak 2026-09-13; kunci
  dust dibulatkan ke `BEST_DUST_SORT_DECIMALS` = 3 desimal = presisi
  tampilan card, jadi pool yang di layar sama-sama "0,030%" dianggap seri),
  baris tanpa dust paling bawah, simbol sebagai tie-break terakhir. Hasil scan:
  `rows/error/fetched/hidden_metric/hidden_dust/analyzed_at`. UI-nya
  `best_pool_ui.render_best_pool_scan()` (card full-width di bawah grid 2
  kolom watchlist sejak 2026-09-11 — "jangan dibuat grid lagi"; dulu di
  dalam grid, kolom kiri bawah Watchlist Meteora; tooltip
  `best_pool_tooltip()`, session key `best_pool_scan`, ⭐ = `source=meteora`
  → card Watchlist Meteora). Tabel
  card = detail fee / active TVL: kolom **A.TVL**, **Fee/TVL** (baris kecil
  angka fee USD), **Vol 24h** (baris kecil Δ volume + `N× A.TVL`), tiap sel
  ber-`title` dengan angka penuh + statusnya sebagai kunci urut.
  **Tanda 🏆 BEST POOL (2026-09-12):** baris dengan dust **<=
  `BEST_DUST_MARK_PCT` 0,035% MC** (inklusif, `row_best_pool()`) ditandai —
  angka dust diwarnai emas + sub sel kolom Dust %MC diganti chip
  `dust-badge dust-best`, dan kepala card menghitungnya di pill `🏆 BEST
  POOL N`. Penanda **visual, bukan saringan** (saringan tetap 0,05%);
  ambangnya dibaca konstanta di tooltip card dan tooltip sel — jangan
  hard-code angkanya di teks.
  **Dua rule 2026-09-13 (akar keluhan "di scan meteora menunjukkan 0.000%
  padahal di scan holder hasilnya beda") — jangan dirotasi balik:**
  (a) **satu denominator** — `holder_analysis.analyze_token` menghitung
  `mc`/`price` dari data market yang BARU di-fetch (DexScreener) dan angka
  listing pemanggil (`enrich_pools` mengirim MC/harga Meteora) hanya jadi
  **cadangan** (`market.get("marketcap") or market_cap`). MC Meteora =
  `market_cap or fdv` + harga lain sumber = dua kartu membagi dust dengan
  angka berbeda, dan titik `holder_history` dari scan pool tidak sebanding
  dengan titik cron. `enrich_pools` **menulis balik** `row["mc"]` ke MC yang
  dipakai, jadi kolom MC dan Dust %MC satu sumber. (b) **tanpa bukti = tanpa
  angka** — `row_dust_pct()` mengembalikan `None` (bukan `0.0` dari
  `classify_holders` daftar kosong) bila `holder_history.holders_usable(holders)`
  False (fetch gagal/0 wallet, `truncated`, sampel < `MIN_USABLE_WALLETS`),
  `enrich_pools` men-null-kan `dust_count`/`dust_pct_mc`/`real_count` +
  menulis `holders_note`, dan `ingest_many` hanya menerima analisis yang layak.
  Selain itu `drop_quote_rows()` (dipakai `scan_meteora` dan
  `scan_best_meteora`, hasil di `skipped_quote`) membuang baris yang
  `unanalysable_row()`-nya terisi: `ca` kosong atau `ca in QUOTE_MINTS` —
  `base_token()` jatuh ke `token_x` untuk pool SOL/USDC/USDT, jadi tanpa
  guard ini holder SOL di-scan lalu dibagi MC SOL = "0,000% + 🏆 BEST POOL"
  permanen. Rekap + alasan tampil di UI (`temp_ui` caption `N pool quote
  dilewati` dan sub sel Dust %MC).
- `holder_analysis.py`: **Helius** sumber holder utama
  (`fetch_holders_helius`, fallback GMGN). `analyze_token` = holder
  real/dust + mid-tier + kohort. `extra_pools` + `cohort_addrs`
  untuk Meteora / kohort. **Pembagi persen = data market terbaru**
  (`get_market`/DexScreener), parameter `market_cap`/`price_usd` dari
  pemanggil **hanya cadangan** sejak 2026-09-13 — urutan lama
  (`market_cap or market…`) membuat Scan Meteora membagi dust dengan MC
  listingnya sendiri sementara kartu lain memakai MC DexScreener, sehingga
  dua kartu menampilkan angka berbeda untuk token yang sama. Jangan dibalik:
  semua pembanding (`holder_status`, `holder_history`, alert Telegram) dihitung
  dengan denominator DexScreener.
- `solscan_holders.py`: hanya kalkulasi `wallet_depth`.
- `helius_holders.py`: Scan Holder Khusus satu token (Solana/Helius).
  Padanan Robinhood Chain: `robinhood_holders.scan_token_holders`
  (Blockscout CSV → v2 → RPC, `chain_id=robinhood` di
  `get_market`) — **shape dict hasilnya sama persis**
  (`mint/symbol/market/snapshot/depth/source/no_helius_keys/scan_failed`)
  supaya section **Scan Holder Khusus** di `app.py` dipakai ulang tanpa
  cabang: CA `0x…` → jalur Robinhood, base58 → Helius; label sumber
  metrik/caption dihitung dari `result["source"]`
  (`app._scan_source_meta`). **Transport Blockscout (sejak 2026-09-08):**
  semua request lewat `_blockscout_get()` = **PRO API**
  `api.blockscout.com/4663/…` (bila ada key: `BLOCKSCOUT_API_KEY` /
  `BLOCKSCOUT_API_KEYS` daftar koma / `blockscout_api_key(s)` config /
  secrets — digabung lewat `get_pro_api_keys()`; header Bearer, key tak
  pernah di URL/log, label `key#N`) → instance publik (curl_cffi
  impersonate dirotasi saat 403 → `requests`). **Multi-key** (2026-09-09):
  `_ProKeyPool` round-robin; 401/403/402/429 memarkir key itu dan request
  pindah ke key berikutnya di putaran yang sama (kuota per akun, jadi N
  akun = N× plafon). `pro_key_summary()` untuk log; hasil membawa
  `pro_key`/`pro_keys`. Jangan kembali ke `get_pro_api_key()` tunggal.
  **Cakupan dust (2026-09-09):** default Robinhood 100.000, bukan default
  Solana 3.000. CSV mencapai cap tanpa counters, jumlah di bawah counters,
  RPC gagal di tengah jalan, atau v2 mencapai page cap → `truncated=True`;
  hasil parsial membawa alasan dan tidak boleh menjadi angka/alert valid.
  Instance publik memblokir server dengan 403 bot-protection; itu
  `BlockscoutBlocked` — **bukan transient, jangan di-retry**, dan
  `fetch_holders` merangkumnya jadi **satu** kalimat + `blocked: True`
  (`analyze_token` → `holders["blocked"]`) supaya UI/cron bilang "pasang
  BLOCKSCOUT_API_KEY", bukan "pastikan CA valid". `source` sukses diberi
  akhiran `@pro`/`@public` — bandingkan lewat `source_base()`, label UI
  lewat `route_label()`. Detail: `docs/robinhood_holders_api.md`.
- `core.py`: **status + sisa kredit key Helius** (`helius_key_status` =
  blocking, untuk cron/tes; `helius_usage_status(background=True)` =
  non-blokir untuk UI; `helius_usage_summary()` untuk panel 🧾;
  `helius_credit_remaining()`; `helius_request_count()`), cache
  `HELIUS_USAGE_TTL_SEC` + kill-switch `HELIUS_USAGE_PROBE=0`. Urutan pool
  key: nilai eksplisit → `config` passed → **Streamlit secrets → env →
  config.json** (`merge_helius_keys` first-wins; secrets di depan config.json
  supaya placeholder `PASTE-API-KEY-KAMU-DISINI` yang ikut ter-bundle tidak
  menutupi key asli — placeholder juga dibuang `_KEY_PLACEHOLDER_RE`).
  config/key Helius, pasar DexScreener (`get_market` ikut
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
- `scripts/scan_holders.py`: cron **lane LP saja** sejak **2026-09-07**
  (permintaan user: "rampingkan dan fokuskan ke holder scan untuk meteora dan
  robinhood saja … semua pencatatan lain tidak usah dilakukan yang tidak
  perlu"). Yang di-scan tiap run **±5 menit**: Chart LP Meteora
  (`split_watchlist(watchlist)[0]`, Solana/Helius) + Robinhood LP
  (`split_robinhood_watchlist(rh_watch)[0]`, EVM/Blockscout). **Watchlist
  biasa tidak di-scan cron**: slot 4 jam, `token_needs_scan` (catch-up +
  bootstrap), `build_scan_plan`, `--scope`, `merge_status`, rule 🔔 HIGH DROP,
  dan semua flag scope rule (`lp_mints`/`high_mints`) sudah **dihapus dari
  modul** — (yang tetap dibaca cron: `alert_settings.muted_mints` = toggle
  🔔/🔕 **per token** dari dashboard, satu bacaan per run, lihat bullet
  `alert_settings.py`) —
  jangan dikembalikan tanpa alasan; scan manual di dashboard tetap melayani
  token biasa. Pencatatan ikut dibatasi: `publish_holder_history(...,
  keep_mints=set(lp_watch))` / `robinhood_watchlist.publish_scan(...,
  keep_mints=set(rh_watch))` hanya men-push token watchlist aktif
  (`holder_history.restrict_store_to_mints`; terukur 2.135.084 → 10.050 byte
  gzip pada store live 81 token → 1 token LP). Scan FULL (baseline immutable +
  kronologi) tidak dijadwalkan cron; jalankan `--full` manual. Katup hemat
  kuota: `LP_SCAN_RUN_MULTIPLIER` (env, default 1) → `lp_slot_due(now,
  status.updated_at)` menahan scan **Solana** sampai tiap N run kalau kuota
  Helius menipis, tanpa menyentuh kode. Tiga invarian yang wajib dijaga bila
  kadens diubah lagi: `MIN_RUN_GAP_SEC` (gate run ganda) dan
  `holder_history.MIN_POINT_GAP_SEC` harus **di antara** gate itu dan kadens
  run tercepat — kalau ambang titik ≥ kadens, tiap titik baru menimpa titik
  sebelumnya dan history lane itu berhenti tumbuh
  (`tests/test_holder_history.py::FiveMinuteCadenceTest`); dan
  `holder_history.MAX_POINTS` harus ikut density run supaya jendela grafik LP
  tidak menyusut (`ScanDensityCalibrationTest`).
  Yang menahan pesan kembar: bucket event + jeda kirim
  (`telegram_alerts.FAST_BUCKET_SEC` = `EARLY_DUMP_RESEND_SEC` = **300 dtk
  per token**) masih menahan pesan kembar untuk lane non-Meteora; metric Meteora
  memakai state transisi aktif di `meteora_watchlist.py`. **Pull + merge
  backup store sebelum scan**, evaluasi metric/holder sesuai lane sebelum
  ingest history, publish snapshot, **push backup store sesudahnya**; exit
  non-zero bila 0 holder / publish snapshot gagal (backup gagal = `WARN` saja,
  tidak membuat cron merah). Yang diteruskan ke `process_holder_alerts` hanya
  lane non-Meteora; `watchlist_meta` hanya dipakai pada lane Robinhood yang
  masih memanggil holder alert (Solana Meteora tidak lagi melewati fungsi itu)
  untuk **marker re-add** (`_reset_markers_on_readd` — token yang
  masuk lagi setelah dihapus memulai episode dari nol), dan
  `advance_anchors=args.full` (hanya scan FULL menggeser anchor
  `baseline`/`rolling`; run ±5 menit `detail=False` tidak). Entri
  `source=regular` tidak di-scan cron sejak 2026-09-07. Cron memakai
  `detail=False` (`scan_watchlist(..., detail=args.full)` +
  `ingest_many(..., detail=args.full)`): tiap run hanya menambah titik holder
  + evaluasi alert; baseline immutable + kronologi wallet ditulis scan FULL
  manual (`--full`) atau tombol scan FULL di dashboard. Workflow tetap
  mengirim `--max-wallets 3000`: sejak **2026-09-09** batas itu hanya
  untuk **Solana**. Robinhood selalu memakai
  `holder_history.FULL_SCAN_MAX_WALLETS` (100.000), sama dengan tombol
  watchlist dan Scan Holder Khusus. Blockscout mengurutkan saldo terbesar
  dulu; cap 2.000/3.000 melewatkan ekor dust (laporan PARE 0,00% vs 0,03%).
  `--full` tetap hanya mengaktifkan detail/baseline/kronologi, bukan syarat
  mengambil seluruh daftar Robinhood.
  Berkas workflow **tidak pernah bisa** diubah dari sisi bot (GitHub App tanpa
  izin `workflows` → 403 saat push/PUT; diverifikasi ulang 2026-09-07:
  `refusing to allow a GitHub App to create or update workflow
  .github/workflows/daily-effort.yml without 'workflows' permission`). Karena
  itu `daily-effort-5menit.yml` di root repo = **satu-satunya tempat**
  perubahan workflow disiapkan untuk disalin manual lewat UI GitHub; isinya
  versi 2026-09-07 (lane LP, input `full_scan` menggantikan `scan_all`, dua rem
  anti-tabrakan di langkah chain, `timeout-minutes: 15`). Jangan dianggap sudah
  terpasang sebelum terlihat di tab **Actions**. Supaya workflow lama tidak
  crash selama belum disalin, `scripts/scan_holders.py` masih menerima
  `--scope auto|fast|all` sebagai **alias tersembunyi** (`argparse.SUPPRESS`):
  `all` → `--full`, selain itu diabaikan + `WARN`. Hapus alias itu begitu
  `daily-effort-5menit.yml` terpasang.

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
- `telegram_alerts.py`: rule holder-dust untuk lane **non-Meteora** — ⚡
  **EARLY DUMP TERJADI - GANTI WIDE RANGE** (kind + marker `early_dump`),
  menyala ketika `dust_pct_mc` naik
  ≥ `EARLY_DUMP_STEP_PCT` (**0.02**) dari **patokan watchlist**
  (`baseline_pct` = dust saat token masuk watchlist; boleh dari titik
  `holder_history` pertama setelah tanggal `added`, ditandai `baseline_src`
  `history`/`first-scan`) pada token non-Meteora yang dievaluasi.
  **Delta berulang, bukan ambang**: `_steps_from_baseline()` menghitung
  `floor((dust - baseline)/0.02)`, event dibuat hanya bila langkah itu
  **lebih besar** dari `marker["step"]` — 0,02% pertama, kedua, dst.
  masing-masing satu pesan, dan turun-naik ke level yang sudah dikabarkan
  tidak mengirim ulang. Tiap evaluasi dibatasi bucket `FAST_BUCKET_SEC` =
  `EARLY_DUMP_RESEND_SEC` = 300 dtk/token. Dust turun **tidak**
  mengosongkan patokan dan **tidak** ada pesan penutup. Marker
  `alert_state["early_dump"]` = `{ts, dust_pct_mc, baseline_pct,
  baseline_ts, step, baseline_src}` (`baseline_ts` = saat patokan dipasang →
  baris `⏱️ N menit sejak masuk watchlist`; `ts` digeser tiap kirim oleh
  `early_dump_marker_next`, `baseline_*` diKEEP). Marker dipertahankan
  `compact_alert_state`, di-merge terbaru oleh
  `holder_history._merge_alert_state` (daftar kunci marker =
  `("early_dump",)` — tambah key baru di DUA tempat itu).
  **Yang DIHAPUS 2026-09-11** (permintaan user "hapus notif lainnya"): rule
  dust 4 jam (+0,25/−0,50 pp), baseline shift ±1 pp, 🔔 HIGH
  DROP, 🚨 EXIT/CUTLOSS + ✅ TITIK AMAN, 🚨 WAKTUNYA GANTI STRATEGI
  (level ≥ 0,06% MC, sempat menggantikan ⚡ EARLY DUMP 2026-09-11—2026-09-13),
  **gerbang konfirmasi
  volume/harga/volatilitas** (`validate_alert_with_volume`, skor 0,70/0,80,
  `is_high_volatility`, `required_confidence`), `escalation_due`,
  `safe_return_due`, `volume_verdict`, `MAX_HOLDER_DETAILS`/
  `MAX_WALLETS_SUMMARY` di pesan, dan **`rejected_signals`** (jejak audit
  kandidat ditolak — jangan ditulis ulang di state). Simbol-simbol itu
  asserted tidak ada lagi oleh `tests/test_early_dump.py::
  NoLegacyRulesTest`; jangan menghidupkannya tanpa permintaan user.
  Pesan selalu ditutup link token **🔗 GMGN + 🦆 DexScreener** dari
  `links.token_links(mint)`; bila event membawa `pool_addresses`, ditambah
  `🌊 Meteora` + `🦅 HawkFi` (`_pool_links`) — cron belum bisa mengisinya
  (watchlist tidak menyimpan pool address). **Format notifikasi (2026-09-07,
  judul 2026-09-13)**: setiap baris beremoji, dust sebelum → sesudah
  + Δ pp + `· langkah N× 0.02%` dalam satu baris, durasi episode, waktu WIB
  tanpa detik; tanpa tabel wallet/skor/penjelasan panjang. Token tanpa
  patokan (`baseline_ts`) atau patokan dari scan pertama tanpa tanggal
  `added` tidak menampilkan baris `⏱️`. `event["market"]` (konteks pasar) **hanya** dilampirkan
  bila provider mengembalikan minimal satu nilai non-None — jadi jangan
  menguji ketiadaan key `"market"`, uji field-nya
  (`volume_ratio`/`price_change_pct`). Judulnya tebal melalui native entity
  `bold` (offset/panjang **UTF-16**, bukan `len` karakter Python). **Link =
  hyperlink (2026-09-09)**: `build_alert_message(event)` → `(teks, entities)`;
  baris link hanya `"<emoji> <label>"` (`🔗 GMGN`, `🦆 DexScreener`,
  `🌊 Meteora`, `🦅 HawkFi`, `🦆 rh-scan`, `🌏 Blockscout`) dan label diberi
  entity `text_link` dengan URL dari `links.token_links()` / `_pool_links()` —
  URL **tidak** ditulis di teks. `format_alert_message()` = teksnya saja.
  Jangan kembali ke `token_link_lines()` (URL polos) untuk Telegram.
  Telegram tidak mendukung ukuran/warna/teks berkedip: jangan kirim
  HTML/CSS palsu. Teks tetap literal, tanpa `parse_mode`;
  `link_preview_options.is_disabled=True` menjaga pesan tetap pendek.
  `send_test_alert()` juga beremoji dan sengaja tanpa link. Rule tidak pernah
  fetch sendiri: pemanggil menyuntikkan `market_context` /
  `context_provider(mint, analysis)` yang hanya dipanggil **saat pesan akan
  dikirim** (bukan saat kandidat muncul) — satu-satunya alasan modul itu masih
  menyentuh pasar. `advance_anchors` (default True, dipakai cron `--full`)
  memisahkan "kirim notifikasi" dari "geser anchor baseline/rolling".
  Transport: `_telegram_credentials()` lazy (env → `config.json` →
  `st.secrets`), timeout `(3.05, 10)`, `payload=None` = tidak ada yang terkirim
  (state TIDAK dimajukan). **TODO di kode**: `retry_after` dari HTTP 429
  belum dihormati — satu run yang kena rate limit mengirim sebagian event lalu
  berhenti tanpa menandai sisanya.
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
  (dust "habis") dari sampel yang memang tidak memuat wallet dust.
  **Dust saat masuk watchlist (2026-09-13)** — permintaan user *"pada detail
  watchlist, juga tunjukkan pertama kali saya menambahkan ke watchlist, posisi
  % dust di berapa %"*: `added_baseline(meta, points)` mengembalikan
  `{pct, count, ts, added_ts, fallback}` dari titik pembanding yang **sama**
  dengan kolom "Sejak masuk" (`anchor_point`, titik pertama pada/setelah
  `added` yang layak — identik dengan patokan `telegram_alerts.
  add_baseline_for_mint`), dan `baseline_note()` merangkainya jadi satu baris
  caption `📌 Saat masuk watchlist (…): dust X% MC · sekarang Y% MC (+Z pp) —
  patokan notif ⚡ EARLY DUMP`. Varian `fallback` (`no_added_date` /
  belum ada titik setelah tanggal masuk) tetap ditulis apa adanya; tanpa titik
  layak sama sekali → "belum bisa dihitung". Captionnya dirender di baris
  pertama expander detail `dashboard_components._render_dust_change(…, meta=,
  current_pct=)` — keempat lane (Meteora LP, Robinhood LP/biasa, watchlist
  biasa Solana) memakai expander itu. **Kolom tabel "Awal Masuk"
  (2026-09-13)** — permintaan user *"Saat masuk watchlist (13 Sep 07:00
  WIB): dust 0.103% MC — ini tambakan ke kolom table saja dengan caption
  Awal Masuk"*: `baseline_cell(baseline, current_pct=…)` →
  `{value, sub, note}` (`value` dust % MC 3 desimal, `sub` waktu titik
  pembanding + penanda fallback, `note` = kalimat lengkap `baseline_note()`
  untuk atribut `title` sel). Selnya jadi **kolom ke-4 dari 8** di ketiga
  tabel watchlist — `app._render_lp_row`, `dashboard_components._render_rh_row`
  (varian LP & biasa) dan tabel 📋 watchlist Holder `temp_ui.render_temp`
  (di situ di kiri "Sejak masuk"). Titik pembandingnya TETAP
  `added_baseline()`/`anchor_point()` — dilarang membuat definisi baseline
  kedua; angkanya harus sama dengan caption expander 📈 dan patokan rule ⚡.
  Urutan baris (2026-09-05):
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

Semua mutasi watchlist (tambah ➕, hapus ✕, hapus semua 🗑️, pindah card
📋/⚡ — Solana **dan** Robinhood) lewat `watchlist.add_to_watchlist` /
`remove_from_watchlist` / `remove_many_from_watchlist` /
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
`load_watchlist()` me-flush journal yang tersisa **di latar belakang**
(`_queue_github_push`, non-blocking — dulu sinkron sehingga setiap rerun bisa
membeku sampai ±2 menit saat push gagal), tapi **melewati** enqueue selama
`push_inflight(repo_path)` masih benar (mencegah balap 409), dan status terakhir
bisa dibaca UI lewat `push_status(repo_path)`
(badge `🔄 sinkron…` / `⚠️ belum sinkron` di kepala card Robinhood).

**Jurnal hanya di-prune terhadap state yang terkonfirmasi mencerminkan repo**
(cache ditandai `settled=True`: hasil pull GitHub atau push yang sukses).
State optimis hasil perubahan lokal (`_seed_remote_cache`, `settled=False`) atau
file lokal **bukan** bukti remote menerima op — mem-prune terhadapnya menghapus
jurnal sebelum push berhasil, sehingga token yang dihapus muncul lagi di render
berikutnya saat cache kedaluwarsa dan server menarik ulang GitHub (bug
"bolak balik" pada hapus watchlist). Karena itu `_load_and_merge` / `_push_worker`
mem-prune jurnal hanya bila data acuannya `settled=True`, dan worker mem-prune
terhadap `wl` yang benar-benar di-commit (bukan cache yang bisa saja di-seed
ulang oleh mutation lain saat push jalan).
Pemanggil non-UI (cron/skrip) tetap default `background=False`.
`_CACHE_TTL` load watchlist 60 dtk karena perubahan lokal selalu men-*seed*
cache — menaikkan lagi TTL tidak membuat UI lebih cepat, menurunkannya
mengembali-kan round-trip tiap rerun.

**🗑️ Hapus semua (2026-09-06)** — tombol popover di kepala card watchlist
biasa (`app.py`, sebelah selectbox "Urutkan baris watchlist"; hanya dirender
bila `holder_watch` tidak kosong) → konfirmasi "Ya, hapus N token"
(`key="clear-regular-watchlist"`) → `remove_many_from_watchlist(
list(holder_watch), note="watchlist biasa", background=True)`. Scope =
`holder_watch` hasil `split_watchlist` (token Solana non-LP, termasuk
`degen` yang dipakai Pre-Pump Screener); Chart LP Meteora dan kedua card
Robinhood **sengaja tidak ikut** — fungsi ini tidak menyaring `source`,
pemanggil yang menentukan daftar CA. Satu tulis journal (`_journal_many`,
last-op-wins per CA membatalkan `add` tertunda) + **satu** commit, bukan N
klik ✕. Op `remove` untuk CA yang tidak ada di state lokal tetap
di-journal (remote yang lebih baru ikut bersih; `_op_is_applied` mem-prune
bila memang sudah tidak ada). History/snapshot holder tidak dihapus —
`snapshot_status` sudah membuang kunci di luar watchlist saat publish
berikutnya.

## Ambang

```text
dust_limit_usd        : 10.0  (real > $10; dust 0 < value <= $10)
                          -> dust % MC TIDAK invariant harga: cutoff USD
                          menggeser klasifikasi wallet (TODO(alerts):
                          annotate re-klasifikasi, bukan reject)
dust HATI-HATI        : >= 0.5% marketcap (Chart LP / watchlist)
dust BAHAYA           : >= 1% marketcap (Chart LP / watchlist)
hide Scan Meteora     : > 0.1% marketcap (DUST_SCAN_HIDE_PCT, 2026-09-07);
                        listing hanya memuat dust <= 0.1%, badge level
                        AMAN/HATI-HATI/BAHAYA dinonaktifkan di listing itu
pembagi dust %MC      : market cap DEXSCREENER hasil fetch terbaru di semua
                        kartu (2026-09-13) — angka yang dikirim pemanggil ke
                        analyze_token (MC listing Meteora/Blockscout) hanya
                        cadangan saat DexScreener diam
bukti dust Meteora    : row_dust_pct() = None bila holders_usable False (fetch
                        gagal / 0 wallet / truncated / sampel <
                        MIN_USABLE_WALLETS 40) — bukan 0.0 dari daftar kosong
                        (2026-09-13). Barisnya tanpa angka + holders_note,
                        gugur dari Best Pool, tanpa BEST POOL, dan tidak
                        di-ingest ke holder_history. Pool tanpa sisi memecoin
                        (ca in QUOTE_MINTS / mint kosong) dibuang sebelum
                        fetch holder (drop_quote_rows -> skipped_quote)
badge BEST POOL       : < 0.1% marketcap (DUST_BEST_PCT, aditif) + data
                        holder valid: total_fetched > 0 dan >= 40 wallet
                        (DUST_BEST_MIN_HOLDERS) + TVL pool >= 10K USD
                        (DUST_BEST_MIN_TVL_USD; None = bukan best).
                        == 0.1% bukan BEST POOL (strict <). Notifikasi
                        tidak memakai angka ini (pemicunya delta +0.02 dari
                        patokan watchlist).
                        Hanya dirender di listing Scan Meteora.
🏆 Scan Best Pool     : query API pool_type=dlmm && fee_pct>=2 &&
                        active_tvl>=50000 (24 jam, category=top, page_size
                        50) — fee tier + active TVL disaring API, bukan di
                        layar. Saringan layar (kriteria diganti total
                        2026-09-11): dust < 0.05% MC (BEST_DUST_MAX_PCT,
                        ketat <) + volatility >= 2% (BEST_VOLATILITY_MIN,
                        "minimal 2%" -> 2,0% lolos). Data hilang (None) =
                        gugur. Saringan lama fee/active TVL > 20%, top 10
                        holder < 30%, total LPs > 20, active TVL > 10K =
                        DIHAPUS. Urutan (2026-09-13): volume 24 jam /
                        active TVL (volume_active_tvl_ratio) terbesar ->
                        dust % MC terkecil -> simbol.
grafik lane LP        : bucket 5 menit (resample_5m / LP_INTERVAL_SEC)
kolom tabel watchlist : Δ 4 jam + sparkline Grafik 4 jam DIHAPUS (2026-09-07)
grafik / kohort       : bucket 4 jam (resample_4h; titik mentah per run,
                        MAX_POINTS 1008 = 3,5 hari @ 5 menit LP)

Notifikasi Telegram — scope lane:
Meteora metric        : `meteora_watchlist.py`; baseline `metric_baseline` saat
                        pool masuk; 24h alert bila quotient
                        `fee_active_tvl_ratio / volatility` turun >=30%; 30m
                        alert bila snapshot baru `volatility > fee_active_tvl_ratio`.
                        Snapshot/status metric dibagi cron + dashboard; dust
                        holder tetap data/grafik, bukan rule Watchlist Meteora.
non-Meteora holder    : `telegram_alerts.py` masih memakai marker
                        `alert_state["early_dump"]` dan rule dust delta 0,02%
                        untuk lane Robinhood/watchlist biasa yang belum punya
                        metrik pool. State itu tidak dibaca oleh lane Meteora.
metric dedup          : evaluasi hanya membuat event saat kondisi berubah dari
                        tidak aktif ke aktif; toggle mute hanya melewati kirim,
                        snapshot dan state tetap dimajukan.

volatilitas "liar"    : price_stddev_4h > 3.0% (HIGH_VOLATILITY_STDDEV_PCT,
                        holder_history) — sekarang murni info di snapshot
                        `market_signal`, bukan gerbang kirim lagi
avg_volume_7d         : rata-rata volume PER WINDOW 4 JAM selama 7 hari
                        (dipakai baris `📈 Pasar`; dulu gerbang 2.0x/1.5x —
                        DIHAPUS bersama skor konfirmasi 0.70/0.80)
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
dust saat masuk       : baris pertama detail card menulis dust % MC saat
                        token masuk watchlist (added_baseline() +
                        baseline_note(), 2026-09-13) — angka yang sama dengan
                        patokan notif ⚡ EARLY DUMP; varian fallback
                        (tanggal `added` tidak terbaca / belum ada titik
                        setelah add) ditandai di teksnya
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
scan_degraded()       : True bila truncated/degraded, termasuk ribuan top
                        holder tanpa ekor dust; atau bukti sampel pendek/0 wallet —
                        dict tanpa info jumlah wallet (skema lama) tidak
                        ditolak, jadi perilaku lama tidak berubah
point_usable()        : titik ber-penanda truncated/degraded (termasuk
                        history lama), tanpa dust_pct_mc, atau
                        < 40 wallet -> dibuang dari angka baris, pembanding
                        "sejak masuk", sparkline, grafik 4 jam, overlay LP
alert                 : process_holder_alerts() melewatkan scan tidak layak
                        (rule notifikasi tidak boleh menyala dari dust 0%
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
  best_pool_ui.py page_router.py "pages/5_🧮_Holder.py"
```
