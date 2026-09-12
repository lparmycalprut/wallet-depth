# Kegiatan — 12 September 2026 (klik pill N disembunyikan → listing pool tersembunyi)

Permintaan user: *\"ketika saya klik disitu, app akan menampilkan pool yang
disembunyikan sorted by kenaikan volume 24 jam, tapi tetap dengan kriteria
minimal volume 24 jam 1M, dan minimum % dust dibawah 0.05%\"* (konteks:
pill **N disembunyikan** di card 🏆 Scan Best Pool Meteora).

- `scan_best_meteora()` kini meng-enrich semua pool **volume 24 jam ≥ $1M**
  (bukan hanya yang lolos volatility) supaya dust < 0,05% MC bisa dicek di
  listing tersembunyi. Pool sepi (< $1M) tetap tidak di-fetch holder.
  Hasil baru `hidden_rows`: volume ≥ $1M + dust < 0,05% MC, **bukan** di
  listing utama (gagal volatility), urut `sort_best_rows` (Δ volume 24 jam
  terbesar dulu).
- UI `best_pool_ui`: tombol **▶ N disembunyikan** (HTML pill tidak bisa
  diklik di Streamlit) membuka listing itu; **◀ kembali ke N pool lolos**
  mengembalikan listing utama. ⭐ listing tersembunyi memakai key
  `best-pool-hidden-star-…`.
- Coverage: `tests/test_best_pool_scan.py` — `hidden_rows` menolak volume
  < $1M dan dust ≥ 0,05%, urut Δ volume; AppTest klik tombol menampilkan
  token tersembunyi dan menyembunyikan yang lolos.

# Kegiatan — 12 September 2026 (🛰 Scan Holder: tulisan BEST emas kelap-kelip · 🏆 Best Pool: volume 24 jam ≥ $1M)

Permintaan user (dua bagian, menyusul entri tiga bagian sebelumnya di hari
yang sama):
*\"lalu kita tambahkan juga disini, jika kondisi %dust <= 0.035 kasih tulisan
BEST yang agak besar, dengan efek kelap kelip, warnanya GOLD\"* (konteks:
section 🛰 Scan Holder Solana / Robinhood yang baru mendapat metrik Dust %MC)
dan *\"🏆 Scan Best Pool Meteora — tambahkan juga kriteria disini, minimal
volume 24 jam adalah 1M, dibawah itu jangan di show\"*.

## 1 · 🛰 Scan Holder: tulisan **BEST** emas kelap-kelip bila dust ≤ 0,035% MC

- Syarat: `depth["dust_pct_mc"] <= meteora_screener.BEST_DUST_MARK_PCT`
  (0,035%, **inklusif** — angka yang sama dengan tanda 🏆 BEST POOL di card
  🏆 Scan Best Pool Meteora, jadi satu sumber konstanta dan tidak bisa
  menyimpang). Dust `None`/tidak terbaca = tidak pernah ditandai.
- Helper baru `dashboard_components._scan_best_mark_ok()` (syaratnya, impor
  `meteora_screener` di dalam fungsi — pola `best_pool_tooltip()`) +
  `_scan_best_badge_html()` (HTML-nya, return `""` bila tidak lolos supaya
  tidak ada elemen kosong). Dirender `app.py::_render_helius_holder_result`
  dengan `c0.markdown(...)` = **kolom metrik Dust %MC**, tepat di bawah
  angkanya, untuk **kedua jalur** (Helius *dan* Blockscout — satu renderer).
- Tampilan: **agak besar** (1,45rem, weight 900, letter-spacing), warna
  **GOLD** (gradien `#8a5a00 → #ffd700 → #fff6b0` di-clip ke teks + glow
  emas), **kelap-kelip** (`@keyframes scan-best-blink`, opacity 1 → 0,32,
  1,05s infinite) plus kilau menyapu (`scan-best-shine`, 2,8s) dan 🏆 kecil
  di ujungnya. Semua gaya hidup di CSS `render_styles()` karena
  `st.markdown` **men-sanitasi atribut `style` inline**;
  `@media (prefers-reduced-motion: reduce)` mematikan animasinya.
- Nama class-nya `.scan-best-gold`, **sengaja bukan** varian `dust-best`:
  pin regression card Scan Meteora menghitung kemunculan string class chip
  emas itu di seluruh body halaman (`tests/test_lp_card_ui.py`,
  `tests/test_best_pool_scan.py`) dan CSS ikut ter-render di body — memakai
  nama yang mengandung substring itu langsung memecahkan dua tes tersebut
  (terjadi saat implementasi, sudah diperbaiki + diberi komentar di CSS).
- Penanda **visual** saja: tidak ada metrik, saringan, atau angka yang
  berubah. Rule + ambangnya dijelaskan di **tooltip judul section**
  (`app.scan_holder_tooltip()` — konstanta `SCAN_HOLDER_TOOLTIP` dijadikan
  fungsi supaya angkanya dibaca dari `BEST_DUST_MARK_PCT` saat dipanggil),
  bukan caption baru di badan section.
- Coverage: `tests/test_rh_card_ui.py` (AppTest: badge tepat satu di 0,035%
  dan di jalur Helius; tidak muncul di 0,036/0,041/0,55/9,0 maupun saat dust
  `None`; CSS `.scan-best-gold` + `@keyframes scan-best-blink` + warna emas
  ikut ter-render; tooltip section menyebut rule-nya dan caption tidak) +
  `tests/test_best_pool_scan.py::ScanHolderBestBadgeTest` (unit helper:
  batas inklusif, data hilang, teks tanpa `style=` inline, isi CSS
  `render_styles`, ambang mengikuti konstanta).

## 2 · 🏆 Scan Best Pool Meteora: saringan **volume 24 jam ≥ $1.000.000**

- Konstanta baru `meteora_screener.BEST_VOLUME_24H_MIN = 1_000_000.0`
  (USD, **inklusif** — tepat $1M lolos) dan syaratnya masuk
  `row_best_gaps()`: label gap `volume 24 jam < $1,000,000`, volume `None`
  = gugur (sama seperti volatility — pool tanpa data volume tidak terbukti
  ramai). Saringan layar card jadi **tiga**: volume ≥ $1M + volatility ≥ 2%
  (`row_best_gaps`) dan dust < 0,05% MC (`row_dust_ok`).
- Karena `row_best_gaps()` jalan **sebelum** `enrich_pools()`, pool sepi
  gugur tanpa membakar kuota Helius; hitungannya masuk `hidden_metric`
  (bukan `hidden_dust`) sehingga rekap \"N pool lolos · M disembunyikan\" dan
  log aktivitas tetap benar tanpa perubahan UI.
- Bukan query API: `best_filter_by()` tetap `pool_type=dlmm&&fee_pct>=2&&
  active_tvl>=50000` (kunci `filter_by` yang dipakai UI Meteora — kunci
  volume tidak terverifikasi di endpoint itu, jadi disaring di layar supaya
  tidak diam-diam kehilangan seluruh listing).
- UI `best_pool_ui`: tooltip card menyebut ambangnya dari konstanta
  (`volume 24 jam >= $1,000,000 (di bawah itu tidak ditampilkan)`), dan
  tooltip sel **Vol 24h** kini menutup dengan `saringan layar: minimal
  $1,000,000` supaya angka yang jadi bukti saringan terlihat di selnya.
- Coverage: `tests/test_best_pool_scan.py` — batas inklusif ($1M lolos,
  $999.999,99 / $0 gugur), volume `None` gugur, label gap mengikuti
  konstanta, `filter_best_rows` memasukkan pool sepi ke `hidden_metric`,
  `scan_best_meteora` tidak mem-fetch holder pool $400K (fixture default
  dinaikkan ke $1,2M supaya tetap menguji satu syarat per tes), tooltip card
  + tooltip sel, dan AppTest sel Vol 24h menampilkan `$1.20M` /
  `volume 24 jam $1,200,000`.

## Verifikasi

- Suite penuh: **1102 tes lulus** (sebelumnya 1092 — 10 tes baru), tanpa
  network (`tests/conftest.py` + `tests/__init__.py`).
- Dokumentasi ikut diperbarui: `AGENTS.md` (bullet baru tanda BEST di Scan
  Holder, `scan_holder_tooltip()` menggantikan konstanta `SCAN_HOLDER_TOOLTIP`,
  saringan layar Best Pool jadi tiga + urutan baris yang sempat basi
  dikoreksi ke volume → dust → fee/TVL) dan `README.md` (tabel saringan
  layar Best Pool + paragraf metrik/BEST di section Scan Holder).

# Kegiatan — 12 September 2026 (🏆 tanda Best Pool ≤ 0,035% · Hold %MC 3 desimal · Dust %MC di Scan Holder)

Permintaan user (tiga bagian):
*\"pada 🏆 Scan Best Pool Meteora tandai jika %dust <= 0.035 menjadi Best
Pool; pada 🌊 Watchlist Meteora dan 🦅 Watchlist Robinhood pada kolom Hold
%MC buat menjadi 3 angka dibelakang koma persenannya; lalu pada 🛰 Scan
Holder Solana / Robinhood tambahkan detail % dust di sebelah kiri Akun
holder (Blockscout) — pada scan holder ini, kita buat menjadi 3 angka
dibelakang koma juga, termasuk di grafik\"*.

## 1 · 🏆 Scan Best Pool Meteora: tanda Best Pool untuk dust ≤ 0,035%

- Konstanta baru `meteora_screener.BEST_DUST_MARK_PCT = 0.035` + helper
  `row_best_pool()` (batas **inklusif** — 0,035 persis ikut ditandai; dust
  `None` tidak pernah). Penanda **visual, bukan saringan**: saringan
  listing tetap `BEST_DUST_MAX_PCT` 0,05% (lebih longgar), jadi listing
  tidak menyempit dan pool 0,04% tetap tampil hanya tanpa tanda.
- UI `best_pool_ui`: kolom **Dust %MC** baris yang lolos tanda menampilkan
  angka warna emas + chip `dust-badge dust-best` 🏆 BEST POOL (chip mengganti
  sub "dust" di selnya); kepala card mendapat pill emas **🏆 BEST POOL N**
  di antara pill jumlah pool dan "disembunyikan". Tooltip sel dan tooltip
  judul card menjelaskan ambangnya dengan angka dari konstanta (konvensi
  2026-09-10: tooltip mengikuti konstanta, tidak hard-code).
- Coverage: `tests/test_best_pool_scan.py::BestPoolMarkTest` (batas
  inklusif 0,035 / bukan saringan — 0,04% tetap lolos / `None` tak pernah /
  fallback field baris / tooltip) + 2 AppTest (chip hanya di baris ≤0,035
  dengan pill rekap; tanpa baris bertanda = tanpa chip/pill).

## 2 · Kolom Hold %MC di watchlist → 3 desimal

- `app.py::_render_lp_row` (🌊 Watchlist Meteora) dan
  `dashboard_components._render_rh_row` (🦅 Watchlist Robinhood — varian LP
  halaman utama *dan* varian biasa halaman temp ikut karena satu renderer):
  `pct_txt` `.2f` → `.3f` ("0.450%" bukan "0.45%"). Dust watchlist LP sering
  di kisaran 0,01–0,09% MC; dua desimal menyembunyikan beda 0,044% vs
  0,037% yang justru penting untuk memutuskan masuk pool.
- Yang **tidak** ikut berubah: Watchlist Holder biasa di `temp_ui.py`
  (scope permintaan hanya kedua card watchlist chain) dan pembanding
  `watchlist_detail` (Δ→% MC format lain).

## 3 · 🛰 Scan Holder: metrik Dust %MC + semua persen 3 desimal

- **Metrik baru `Dust %MC` tepat di kiri "Akun holder (…)"**
  (`app.py::_render_helius_holder_result`, kolom metrik jadi 5): nilai
  `dust_pct_mc` yang dihitung `classify_holders` **di dalam**
  `scan_token_holders` — Helius *dan* Robinhood — lalu ditempel ke
  `depth` (`dust_pct_mc`, `dust_count`, `dust_value_usd`,
  `dust_limit_usd`). Kenapa bukan bucket `$0-$10` depth: definisi
  `classify_holders` adalah sumber kebenaran kolom **Hold %MC** watchlist
  (wallet 0 < nilai ≤ $10, LP/pool disingkirkan lewat pair_addresses +
  `is_wallet`), jadi angka Scan Holder identik dengan watchlist token yang
  sama untuk kedua sumber (Helius/Blockscout). Help metrik membawa jumlah
  wallet (≥ bila scan terpotong) + total nilai USD dust.
- **3 desimal**: metrik baru (`.3f`), label batang grafik
  `helius_holders.depth_bar_chart` (`.1f` → `.3f` — bucket dust 0,008% MC
  dulu memayat jadi "0.0%"), dan kolom **% Market Cap**
  `dashboard_components._depth_tables_html` (`.2f` → `.3f`; tabel ini juga
  dipakai Wallet Depth nested di expander watchlist — seragam). Tooltip
  judul section (`SCAN_HOLDER_TOOLTIP`) ikut menyebut definisi + presisi.
- Coverage: `tests/test_helius_holders.py` (depth membawa dust stats; LP
  dust tidak ikut; marketcap 0 → `dust_pct_mc` `None` → metrik "—"; label
  grafik 3 desimal), `tests/test_robinhood_transport.py::ScanHoldersDustStatsTest`
  (jalur Blockscout identik), `tests/test_rh_card_ui.py` (AppTest: metrik
  "Dust %MC" = "0.035%" tepat sebelum "Akun holder (Blockscout)"), dan
  pin 3 desimal di `tests/test_lp_card_ui.py` (🌊, "0.610%"/"1.350%"),
  `tests/test_rh_card_ui.py` (🦅, "0.550%"), `tests/test_alert_toggle_per_token.py`
  (assert "0.55%" → "0.550%").

# Kegiatan — 11 September 2026 (🔔/🔕 toggle alert Telegram per token: Meteora + Robinhood)

Permintaan user: *"kasih toggle alert on/off per token yang ada di watchlist
meteora dan robinhood. jadi misal saya sudah tau ada notif, saya bisa
nonaktifkan. tapi pas awal memasukkan ke watchlist, otomatis on"*.

## 1 · Penyimpanan pilihan: `alert_settings.muted_mints` (blocklist)

- `alert_settings.py` menampung setelan kedua di file yang sama
  (`alert_settings.json`, ref `holder-live`): `muted_mints` = daftar token
  yang notifnya **dimatikan**. Karena bentuknya *blocklist*, token baru
  otomatis ON — tidak ada tulis/commit saat menambah token.
- API baru: `mint_key()` (EVM `0x…` di-lowercase, mint Solana
  case-sensitive), `muted_mints()`, `is_mint_muted()`,
  `mutes_for(mints)` (irisan siap pakai sebagai `mute_mints`),
  `set_mint_alert_enabled(mint, enabled)`, `forget_mint_alert(mint)`.
  `save_settings()` dapat `message=` (commit per token, e.g.
  `alert-settings: notif off 0xe2324ff2a59 [skip ci]`) dan transport
  dipindah ke `_write_remote()` supaya suite bisa mematikannya.
- **Token yang di-add ulang selalu ON**: `watchlist.add_to_watchlist` dan
  `add_many_to_watchlist` memanggil `forget_mint_alert(ca)`
  (`_reset_alert_toggle_on_add`). Tanpa ini token yang pernah dimatikan,
  dihapus, lalu di-add lagi akan mewarisi pilihan OFF periode sebelumnya.
  Mint yang memang tidak pernah dimatikan tidak menulis/meng-commit apa pun.

## 2 · Yang menghormatinya (cron + semua scan manual)

- Cron `scripts/scan_holders.py`: membaca `muted_mints(force_refresh=True)`
  **sekali per run** (1 request GitHub, tercetak di log
  `Toggle alert per token: N dimatikan`) dan meneruskan
  `mute_mints=alert_settings.mutes_for(...)` ke **kedua** lane LP.
- Scan manual: 🔍 Scan LP Meteora (`app.py`), scan ulang card Robinhood
  (`dashboard_components._render_rh_card`), dan scan watchlist biasa
  (`temp_ui.py`) memakai `mutes_for(fresh)` — sehingga token yang dipindah
  card (Meteora → Holder, LP → biasa) tetap senyap.
- Semantiknya tetap **"kirim dilewati, evaluasi jalan"**: rule 🚨 tetap
  dievaluasi dan marker `strategy_shift` tetap dimajukan, jadi menyalakan
  notif lagi tidak membanjiri pengingat episode lama. Catatan hasil scan
  manual ikut menyebut jumlah yang dilewati.

## 3 · Tombolnya di UI

- Baris Watchlist Meteora (`app.py`) dan kedua card Robinhood
  (`dashboard_components._render_rh_row`) dapat kolom baru: **🔔** (ON, klik
  = matikan) / **🔕** (OFF, klik = nyalakan) dengan key `lp-alert-<mint>`,
  `rh-alert-<0x…>`, `rhreg-alert-<0x…>`. Grid baris jadi 7 kolom; 📋/⚡ dan ✕
  bergeser satu kolom.
- Kepala card menampilkan pill **🔕 N** (`_muted_pill_html`) dan baris yang
  dimatikan menambah **· 🔕 notif off** di caption, jadi statusnya kelihatan
  tanpa menebak dari emoji tombol.
- Gagal sinkron GitHub tidak ditelan: `_store_toggle_note` /
  `_render_toggle_note(scope)` menampilkan peringatan **di card pemiliknya**
  (karena klik langsung `st.rerun()`), plus entri di 🧾 Log Aktivitas.
- `LP_CARD_TOOLTIP`, `RH_CARD_TOOLTIP`, `RH_REGULAR_CARD_TOOLTIP`, dan help
  toggle global watchlist biasa (halaman temp) menyebut tombol per token ini.
- Catatan hasil scan manual (`telegram_alerts.delivery_note`) tidak lagi
  berbunyi "notif watchlist biasa OFF" — jadi
  "(notif token itu sedang dimatikan)" supaya benar untuk kedua sumber mute.
- Watchlist Holder biasa di halaman temp **tidak** diberi tombol (scope
  permintaan user = Meteora + Robinhood); `mute_mints`-nya tetap dihormati.

## 4 · Tes

- Baru: `tests/test_alert_toggle_per_token.py` (27 tes) — store (default ON,
  mute → nyala lagi, EVM case-insensitive, `forget_mint_alert` tanpa tulis
  bila tidak dimatikan, payload rusak/toleran, push gagal tetap lokal),
  add-ulang = ON (satu + massal), UI AppTest (bell 🔔/🔕 di tiga card, pill
  🔕, caption "🔕 notif off", klik menyimpan pilihan, peringatan gagal
  sinkron), jalur scan (LP Meteora, Robinhood LP, Robinhood biasa saat toggle
  global ON, watchlist Holder Solana) memastikan **tidak ada** pesan terkirim
  tapi marker `strategy_shift` tetap tersimpan, dan wiring cron (mute
  diteruskan ke kedua lane).
- Dua tes khusus menegaskan **per token, bukan global**: dari dua token LP di
  card yang sama, hanya baris yang di-🔕 berlabel 🔕 (yang lain tetap 🔔, pill
  cukup "🔕 1"), dan scan-nya mengirim Telegram untuk token 🔔 sambil melewati
  token 🔕 (dihitung di laporan scan manual).
- Suite offline: `tests/__init__.py` + `conftest.py` men-stub
  `alert_settings._read_remote`/`_write_remote`; dua assertion lama
  (`tests/test_manual_scan_alerts.py`) menyesuaikan kalimat `delivery_note`.
- Suite penuh: **1076 lulus** (sebelumnya 1049), 21 subtests.

# Kegiatan — 11 September 2026 (🦅 Scan Best Robinhood Coin → temp · 🏆 Scan Best Pool Meteora keluar dari grid)

Dua permintaan user sekaligus:

1. **🦅 Scan Best Robinhood Coin** → *"pindah ke page temp karena belum
   berfungsi"*,
2. **🏆 Scan Best Pool Meteora** → *"jangan dibuat grid lagi"*.

- `app.py`: card **🦅 Scan Best Robinhood Coin**
  (`robinhood_best_scan.render_robinhood_best_scan()`) dihapus dari kolom
  kanan grid 2 kolom — **hanya penempatan** yang berubah: logika scan,
  filter, urutan, tombol 📋/⭐, dan session key tidak disentuh. Card **🏆
  Scan Best Pool Meteora** keluar dari grid 2 kolom (dulu menempel di bawah
  🌊 Watchlist Meteora, kolom kiri) dan dirender **full-width** di bawah
  grid, sebelum 🛰 Scan Holder — posisi seperti sebelum grid 2 kolom
  2026-09-10 (dipisah `st.divider()`). Grid 2 kolom tetap untuk dua card
  watchlist: kiri 🌊 Watchlist Meteora, kanan 🦅 Watchlist Robinhood (LP).
- `temp_ui.py`: `render_temp()` memanggil
  `robinhood_best_scan.render_robinhood_best_scan()` setelah card 🌊 Scan
  Meteora Pool, sebelum section 🔍 Temukan Token. ⭐ card tetap memasukkan
  token ke **Watchlist Robinhood LP** di halaman utama (source/target tidak
  berubah); data, cron, dan alert tidak disentuh.
- Docstring `robinhood_best_scan.py` (modul + `render_robinhood_best_scan`)
  dan `best_pool_ui.py` mengikuti (penempatan + alasan diparkir).
- Tidak ada perubahan logika sama sekali — murni pemindahan card + layout.
- Tes: `tests/test_robinhood_best_scan.py::RenderTest` (4 AppTest) kini
  membuka halaman **temp** via `switch_page("pages/8_temp.py")` (pola
  `tests/test_temp_page.py`), `test_card_tampil_di_halaman_utama` diganti
  `test_card_tampil_di_halaman_temp`; `tests/test_temp_page.py` menambah pin:
  halaman utama TIDAK lagi merender kepala/tombol Scan Best Robinhood, dan
  halaman temp MEMENUangnya. Suite penuh: **1049 passed, 21 subtests**
  (sama dengan baseline).

# Kegiatan — 11 September 2026 (🏆 Scan Best Pool Meteora: kriteria diganti total)

Permintaan user: *"untuk Scan Meteora pool kita ganti seperti ini … kriteria
yang sebelumnya, ganti total dengan ini"* — disertai curl
`pool-discovery-api.datapi.meteora.ag/pools?page_size=50&timeframe=24h&category=top&filter_by=pool_type=dlmm&&fee_pct>=2&&active_tvl>=50000`
+ respons JSON-nya, dan daftar "kondisi": hanya tampilkan dust < 0,05% MC,
kasih detail fee / active TVL di tabel, urut dust terkecil lalu fee/active
TVL terbesar, volatility minimal 2%, lalu urutkan dari kenaikan volume
terbesar. Ditanya balik, user memilih: card = **🏆 Scan Best Pool Meteora**
saja (card 🌊 /temp + 🦅 tidak disentuh), saringan lama = **dihapus** (bukan
ditumpuk), "kenaikan volume" = **`volume_change_pct`** (bukan volume
absolut).

## 1 · Rule baru (`meteora_screener.py`)

- Konstanta: `BEST_FEE_PCT_MIN` 5,0 → **2,0**, `BEST_ACTIVE_TVL_MIN` 10.000
  → **50.000** (keduanya hanya dikirim ke API sebagai `filter_by`, TIDAK
  diulang di layar), `BEST_VOLATILITY_MIN` 5,0 → **2,0** dengan operator
  **`>=`** ("minimal 2%" — 2,0% lolos; beda dari rule lama yang ketat `>`).
  `BEST_DUST_MAX_PCT` tetap **0,05** dan tetap ketat `<` (data dust hilang =
  gugur). `BEST_FEE_RATIO_MIN`, `BEST_TOP10_MAX_PCT`, `BEST_TOTAL_LPS_MIN`
  **dihapus** bersama layarnya.
- `row_best_gaps()` menyusut dari 5 cek metrik jadi **1 cek** (volatility).
  Fungsi + label gapnya tetap satu-satunya sumber angka "gugur metrik"
  (`hidden_metric`) supaya pill "N disembunyikan" jujur.
- `_row_from_pool()` menambah **`fee`** (fee 24 jam, USD) dan
  **`volume_change_pct`** — dipakai tabel + kunci urut. Card 🌊 Scan Meteora
  Pool memakai fungsi yang sama tapi tidak menampilkan field baru, jadi
  listingnya tidak berubah.
- `sort_best_rows()`: `(bawa dust? , dust % MC asc (3 desimal tampilan),
  -fee/active TVL, -volume_change_pct, simbol)`. Baris tanpa angka dust tetap
  paling bawah.

## 2 · Tabel + tooltip card (`best_pool_ui.py`)

- Kepala tabel sekarang: `Token · MC · A.TVL · Fee/TVL · Vol 24h · Volat ·
  Top10 · LPs · Dust · Dust %MC · Pool · ⭐` — tetap 12 kolom: kolom "Fee"
  (tier fee saja) dihapus dan posisinya dipakai untuk **Vol 24h** (Δ volume
  hijau/merah jadi baris kecilnya), tier fee pindah ke baris kecil
  **Fee/TVL** (`fee $97.7K·2%`), dan kolom volatilitas lama `Vol` berganti
  nama jadi `Volat` supaya tidak tabrakan. Jadi "detail fee / active TVL"
  bisa dibaca langsung: A.TVL = penyebut, fee = pembilang, rasio = kunci urut
  kedua.
- Tiap sel metrik dapat atribut `title` berisi **angka penuh** + statusnya
  ("kunci urut kedua (terbesar dulu)", "hanya informasi, bukan saringan lagi
  sejak 2026-09-11"). Konvensi 2026-09-10 tetap: prose rule hanya di tooltip
  judul, badan card hanya angka rekap.
- `best_pool_tooltip()` ditulis ulang — query API, dua saringan, tiga kunci
  urut — dan **semua angkanya dibaca dari konstanta** `meteora_screener.BEST_*`
  (konvensi AGENTS.md). Enam konstanta lama yang dihapus tidak lagi diimpor
  (kalau dibiarkan, card langsung melempar ImportError jadi baris peringatan).

## 3 · Tes & docs

- `tests/test_best_pool_scan.py` ditulis ulang (22 tes): query = persis curl
  user; `fee_pct>=2`/`active_tvl>=50000`; volatility 2,0% **lolos** dan
  1,99% gugur; deretan saringan lama diuji **tidak** menggugurkan lagi +
  konstantanya benar-benar hilang (`hasattr`); rantai urut dust → rasio → Δ
  volume; tabel harus memuat `fee $…`, rasio, dan `+12,5%`; tooltip berubah
  kalau konstantanya di-patch.
- `tests/test_strategy_shift.py` tetap hijau — `STRATEGY_SHIFT_PCT` (0,06)
  masih di atas `BEST_DUST_MAX_PCT` (0,05), ambang notifikasi tidak ikut
  berubah.
- README (§🏆 Scan Best Pool Meteora + tabel kolom), AGENTS.md (blok modul
  `meteora_screener.py` + tabel angka kunci), `docs/PROGRESS.md` mengikuti.
- **Batas verifikasi:** sandbox tidak punya jaringan, jadi payload API
  sungguhan tidak pernah dipanggil — bentuk respons diambil dari JSON yang
  user tempel (field `fee`, `volume_change_pct`, `fee_active_tvl_ratio`,
  `volatility`; satuan persen sudah final, tidak dikali 100 lagi).
  Suite: **1049 passed** (+4 tes), 21 subtests, 0 gagal.

# Kegiatan — 11 September 2026 (satu notifikasi: 🚨 GANTI STRATEGI · caption dobel tooltip dihapus)

Dua permintaan user:

1. *"tulisan ini hapus donk, sudah ada di tooltip"* → ditanya balik, user
   memilih **semuanya**: semua caption yang mengulang isi tooltip judul
   dihapus (3 tempat).
2. *"buat 1 notifikasi lagi — jika %dust diatas >= 0,06 kasih notif, WAKTUNYA
   GANTI STRATEGI"* + *"hapus notif lainnya"* → rule notifikasi diganti satu
   saja; ditanya balik soal kadens, user memilih **tiap scan selama masih di
   atas ambang** (`every_scan`).

## 1 · Caption rule → tooltip saja

- **🌊 Scan Meteora Pool** (halaman temp) sebelumnya **tidak punya tooltip
  sama sekali** — captionnya panjang dan mengarang ulang isi yang sama, jadi
  teksnya tidak dibuang tapi **dipindah**: fungsi baru
  `temp_ui.meteora_scan_tooltip()` menyusun rule + ambang dari konstanta
  (`meteora_screener.TVL_MIN`/`FEE_RATIO_24H`/`FEE_RATIO_1H`,
  `holder_history.DUST_SCAN_HIDE_PCT`/`DUST_BEST_PCT`/`DUST_BEST_MIN_*`) dan
  dipasang sebagai `tooltip=` pada `card_head_html()` di
  `temp_ui._meteora_head_html()` (impor dilakukan di dalam fungsi, sama seperti
  `best_pool_ui.best_pool_tooltip()`). Caption rekap di bawahnya kehilangan
  angka yang dobel — dulu `… {hidden} disembunyikan (dust > 0,1% MC) · listing
  K · 🏆 X BEST POOL di urutan teratas`, sekarang
  `{N} pool ditampilkan · {M} disembunyikan · listing {K}[ · 🏆 X BEST POOL]`.
  Kepala card scan best memang bukan `<details>`/accordion, hanya
  `<div class="lp-head">` dengan pill — tidak ada yang diubah di struktur itu.
  Card Robinhood (`_head_html`/`_rh_head_html`) sudah memakai helper tooltip
  yang sama, tidak disentuh.
- **🦅 Scan Best Robinhood Coin** (`robinhood_best_scan`): caption rekap masih
  menulis ulang **angka** ambangnya
  ("…= 2, top 10 holder ≥ 30% = 1, honeypot = …") — sekarang hanya
  `Listing N coin · M dilewati · dust X · top 10 Y · honeypot Z · holder gagal W.`;
  seluruh prose sudah ada di `RH_SCAN_TOOLTIP`.
- **Toggle Auto-refresh** di header halaman utama: teks abu-abu
  `st.caption("Data baris = snapshot cron (±5 menit); halaman ini re-check tiap
  ±60 detik.")` dihapus — `help` toggle sudah berkata persis begitu.
- Pin regression baru: `tests/test_temp_page.py::TooltipBukanCaptionTest`
  (teks toggle hilang dari badan halaman **tapi tetap ada di `proto.help`**;
  kepala card /temp memuat `title="Top DLMM 24 jam…"` dan captionnya bebas
  angka rule) + perluasan
  `tests/test_robinhood_best_scan.py::RenderTest.test_detail_karakteristik_di_tooltip_bukan_caption`.

## 2 · Satu rule: 🚨 WAKTUNYA GANTI STRATEGI (dust ≥ 0,06% MC)

- `telegram_alerts.py` ditulis ulang (1078 baris):
  `STRATEGY_SHIFT_PCT = 0.06`, kind/marker `strategy_shift`,
  `STRATEGY_SHIFT_TITLE = "🚨 WAKTUNYA GANTI STRATEGI"`,
  `evaluate_strategy_shift_rule(marker, current, *, mint, symbol, sent_event_ids,
  last_sent, market_context)`. Sifatnya **level-based**: selama
  `dust_pct_mc >= 0.06` tiap evaluasi menghasilkan event; `< 0.06` = marker
  `{}` dan **tidak ada** pesan "sudah aman". Ulang dibatasi bucket event
  `FAST_BUCKET_SEC` 300 dtk + `STRATEGY_SHIFT_RESEND_SEC` 300 dtk per token,
  jadi cron 5 menit + scan manual + run ganda tidak mengirim pesan kembar.
  Ambangnya sengaja **di atas** filter listing 0,05%
  (`meteora_screener.BEST_DUST_MAX_PCT`, `robinhood_best_scan.RH_SCAN_*`)
  supaya token yang baru masuk daftar tidak langsung bunyi — dipin
  `ThresholdTest`.
- **Dihapus**: ⚡ EARLY DUMP (crossing > 0,1%), 🔔 HIGH DROP (≥50% dari titik
  high), 🚨 EXIT/CUTLOSS + ✅ KEMBALI KE TITIK AMAN, rule dust 4 jam
  (dump +0,25 pp / akumulasi −0,50 pp), baseline shift ±1 pp, **gerbang
  konfirmasi volume/harga/volatilitas** (`validate_alert_with_volume`,
  `volume_verdict`, `is_high_volatility`, skor 0,70/0,80), `escalation_due`,
  `safe_return_due`, dan **jejak audit `rejected_signals`**. `NoLegacyRulesTest`
  menuntut simbol-simbol itu tidak ada lagi dan `lp_mints=` menolak TypeError.
  Yang **tidak** ikut dihapus: anchor `baseline`/`rolling` +
  `tracked_wallet_addresses()` (dipakai `holder_analysis`, `robinhood_holders`,
  `robinhood_watchlist` untuk kronologi/peta wallet) dan `alert_context.py`
  — konteks pasar sekarang murni baris info `📈 Pasar`, diambil **lazy** hanya
  saat pesan jadi dikirim, disimpan di `event["market"]` (key hanya diisi bila
  ada nilai non-None).
- **Baru di API**: `advance_anchors` (default True) memisahkan "kirim notif"
  dari "geser anchor". Cron `scripts/scan_holders.py` → `advance_anchors=args.full`;
  **semua** tombol scan manual (`app.py`, `dashboard_components._render_rh_card`,
  `temp_ui.py`) sekarang ikut mengirim notif dengan `advance_anchors=False`
  + tanpa flag scope. `holder_history` hanya menyimpan/menggabung marker
  `("strategy_shift",)` (2 tempat: restore snapshot ringkas + `_merge_alert_state`);
  `holder_status._alert_state_for_status` membuang `rejected_signals` + marker
  legacy. Tooltip card (`app.LP_CARD_TOOLTIP`, `RH_CARD_TOOLTIP`,
  `RH_REGULAR_CARD_TOOLTIP`) menyebut rule baru dari konstanta impor, bukan angka
  diketik manual, dan `st.info(..., icon="🚨")` di panel hasil scan.

## Hasil tes

`/home/user/.venv/bin/python -m pytest -q tests` → **1043 passed, 21 subtests
passed, 0 gagal** (~63 s). Berkas tes yang ikut dipensiunkan
(`git rm`): `test_early_dump.py`, `test_high_drop.py`, `test_exit_cutloss.py`,
`test_alert_gating.py`, `test_volume_validation.py`. Baru:
`tests/test_strategy_shift.py` (26 tes + 13 subtests). Ditulis ulang:
`tests/test_telegram_alerts.py` (32). Diperbaiki ikut menyesuaikan:
`test_alert_pipeline.py`, `test_manual_scan_alerts.py` (19), `test_scan_holders.py`,
`test_robinhood_dust_coverage.py`, `test_holder_status.py`, `test_store_backup.py`,
`test_alert_settings.py`, `test_lp_card_ui.py`.

Bug produk yang ketemu **berkat tes**, bukan tesnya yang diubah:
`evaluate_strategy_shift_rule` dulu mensyaratkan `since_ts` untuk
"in-episode", padahal `compact_alert_state` bisa membuangnya → marker hasil
state terkompaksi diperlakukan sebagai episode baru dan teks
"baru melewati ambang" muncul terus. Sekarang `since_ts = marker["since_ts"]
or marker["ts"]` (fallback sama di `strategy_shift_marker_next`).

Dokumen yang disamakan: `README.md` (seksi alert, "Konteks pasar di pesan",
format contoh pesan, tabel konstanta), `AGENTS.md` (bullet scan-manual,
`alert_settings`, cron, `telegram_alerts`, tabel angka kunci, konvensi
tooltip), `DEPLOY.md`.

# Kegiatan — 10 September 2026 (scan best jadi tooltip, kredit Helius di 🧾, budget waktu Scan Best Robinhood dihapus)

Tiga permintaan user sekaligus (sesi sebelum tidur — "nanti kalau sudah
selesai langsung create pr dan merge saja"):

1. *caption rule* **🏆 Scan Best Pool Meteora** dan **🦅 Scan Best Robinhood
   Coin** → *"ini juga bikin tooltip saja"*,
2. **🧾 Log Aktivitas** → *"tampilkan juga berapa kredit tersisa dari helius
   key kita"*,
3. **🦅 Scan Best Robinhood Coin** → *"hapus timeoutnya, gak papa ternyata
   tadi masalahnya holdernya sangat banyak, jadi agak lama memang
   fetchingnya"*.

## 1 · Detail card scan best = tooltip judul (bukan caption)

- `best_pool_ui.py`: `st.caption(...)` berisi seluruh ambang **dihapus**;
  gantinya `best_pool_tooltip()` yang **menyusun teks dari konstanta**
  `meteora_screener.BEST_*` saat dipanggil. Sebelumnya tooltip ini teks
  hardcoded, jadi angka bisa basi; sekarang ubah ambang = tooltip ikut
  berubah. Yang tersisa di badan card hanya rekap hasil scan
  (`N pool lolos · M disembunyikan · listing K pool`) — itu data.
- `robinhood_best_scan.py`: konstanta `CAPTION` + `st.caption(CAPTION)`
  dihapus, isinya (endpoint rank GMGN, filter, urutan, Dexboost, honeypot,
  tombol 📋/⭐, cron ±5 menit) digabung ke `RH_SCAN_TOOLTIP` yang sudah
  membaca `RH_SCAN_MAX_*`.
- Tes: `test_best_pool_scan.py` **16 → 18** (teks rule ada di
  `title="…"` pada judul dan TIDAK lagi di caption; tooltip dibangun dari
  konstanta sehingga ikut berubah kalau `BEST_DUST_MAX_PCT` diubah) dan
  `test_robinhood_best_scan.py` **27 → 29** (`title="Listing GMGN Robinhood
  Chain…"`, caption rule hilang, caption rekap hasil tetap ada).
- `tests/test_temp_page.py`: cek "card temp tidak muncul di halaman utama"
  dipindah dari *string nama card di body* ke *kepala card* `…</span>` +
  label tombol scan, karena tooltip card Best Pool memang menyebut nama
  listing yang direplikanya (dan teks tooltip sengaja tidak memakai emoji +
  nama persis itu).

## 2 · 🧾 Log Aktivitas: sisa kredit key Helius

Baris baru di bawah status pool Blockscout, contoh:

```
Helius API: 2 key · key#1 (wallet-depth) kredit tersisa 812,345 dari
1,000,000 (pakai 18.8%) · ±1,204 request sesi ini · dicek 3 mnt lalu
```

- `core.py` (modul pemilik pool key — bukan UI): `helius_key_status()`
  memprobe metadata key `GET https://api.helius.xyz/v0/keys` per key di pool
  (fallback `mainnet.helius-rpc.com/v0/keys`), `parse_helius_credits()`
  menerima **semua** bentuk respons plan (objek `{total, used, available}`,
  angka tunggal, field datar `creditsRemaining`, string berpemisah ribu) dan
  mengembalikan `None` bila Helius tidak lapor; `total` & `used` → sisa
  dihitung, bukan ditebak. Persentase memakai `used` bila ada, jika tidak
  `(total - remaining) / total`.
- **Key tidak pernah bocor**: pesan error di-*scrub* (`api-key=…` →
  `api-key=***`), baris hanya berisi `key#N` + nama key dari Helius.
- **Kredit per project, bukan per key** — beberapa key satu project melaporkan
  plafon yang sama, jadi nilainya **tidak dijumlah** (didedup;
  `helius_credit_remaining()` menjumlah nilai unikat).
- Render non-blokir: `helius_usage_summary()` dipakai panel log lewat
  `helius_usage_status(background=True)` → **tidak pernah memblokir render**: cache
  ±5 menit (`HELIUS_USAGE_TTL_SEC`, env) dibaca, dan bila basi satu thread
  daemon (`refresh_helius_usage_async`, guard `_helius_usage_inflight`)
  mengisinya; angka muncul pada auto-refresh ±60 dtk berikutnya. Cron/tes bisa
  minta probe inline (`background=False`).
- Level log: kredit `0` atau key ditolak 401/403 → **❗ `action`** (merah bold,
  sesuai konvensi "perlu perubahan manual"); tidak bisa dihubungi / kredit
  menipis ≥ 90% → ⚠️ `warn` (dedup 30 mnt supaya rerun tidak banjir).
  Plan yang tidak mengirim angka kredit → tidak ada entri log, hanya caption
  "Helius tidak mengirim angka kredit untuk plan ini (sisa hanya terlihat di
  dashboard.helius.dev)" + hitungan request lokal.
- Pelengkap baru lain: `helius_request_count()` — dihitung di
  `helius_rpc_request()`/`helius_api_get()` saat request sukses, jadi "±N
  request sesi ini" selalu benar walau Helius tidak mengirim angka.
- Suite offline: `tests/__init__.py` menyetel `HELIUS_USAGE_PROBE=0`
  (kill-switch `core._helius_probe_enabled()`); tes yang menguji transport
  menyalakannya sendiri lewat `mock.patch.dict`.
- **Perbaikan berbarengan (bug nyata yang membuat angka "sisa kredit" tak akan
  pernah terbaca)**: urutan pool key jadi *eksplisit → config passed →
  Streamlit secrets → env → config.json* dan placeholder
  `PASTE-API-KEY-KAMU-DISINI` disaring `_KEY_PLACEHOLDER_RE`. Sebelumnya
  `config.json` (berisi placeholder, ikut ter-bundle di Streamlit Cloud)
  menang atas secrets, `merge_helius_keys` first-wins, dan
  `helius_rpc_request` **tidak** rotation-fallback pada HTTP 401 — tiap scan
  holder mati walaupun key valid terpasang.
- Tes baru `tests/test_helius_usage.py` (**32**) — parser bentuk kredit,
  scrub key,
  cache/TTL + invalidasi saat daftar key berubah, kill-switch offline,
  fallback host kedua, level log per kejadian, teks summary (termasuk plafon
  dibagi beberapa key), urutan sumber key, counter request, dan AppTest
  halaman utama yang memastikan caption Helius benar-benar dirender.

## 3 · Budget waktu Scan Best Robinhood dihapus

- `scan_candidates()`: `CANDIDATE_TIMEOUT_SEC = 300`, `deadline =
  time.monotonic() + …`, `wait(FIRST_COMPLETED)`, `shutdown(wait=False,
  cancel_futures=True)` dan param `timeout_sec` **dihapus** →
  `with ThreadPoolExecutor` + `as_completed(futures)` tanpa timeout. Kandidat
  ber-holder puluhan ribu tidak lagi ditandai "gagal/lewat budget"; hasil
  scan tidak kehilangan baris, hanya butuh lebih lama (sesuai keputusan user).
  Entri log `kandidat lewat budget … dan dilewati` ikut hilang.
- Yang **tidak** ikut dihapus: timeout HTTP per request GMGN
  (`_get_json(timeout=25)`), `CSV_TIMEOUT` Blockscout 90 dtk, `PAGE_SLEEP_SEC`,
  dan masa parkir key PRO (401/402/403/429) — itu proteksi koneksi/kuota,
  bukan batas umur scan. `timeout-minutes: 15` di workflow cron juga tetap
  (watchdog Actions; scan best hanya jalan dari tombol UI).
- Tooltip card sekarang jujur soal durasi ("semua kandidat ditunggu sampai
  selesai … bisa makan waktu puluhan menit"); label progress `sedang: SYMBOL
  (+N lagi)` tetap supaya scan panjang tidak kelihatan hang.
- Tes: `ScanCandidatesTest` dibalik — `test_kandidat_lambat_dilewati_setelah_budget`
  (dulu menuntut kandidat lambat dibuang) jadi
  `test_kandidat_lambat_tetap_ditunggu_sampai_selesai`, plus
  `test_scan_candidates_tidak_menerima_budget_waktu` yang membaca sumber
  modul: `timeout_sec` / `deadline` / `CANDIDATE_TIMEOUT_SEC` tidak boleh
  muncul lagi.

Catatan hasil: `python -m unittest discover tests` → **1138 tes** (sebelumnya
1102: +2 Best Pool, +2 Best Robinhood, +32 Helius) — lulus kecuali 2 tes
`test_scan_holders` (DurableStoreBackup + EarlyDumpScope) yang **sudah gagal
di HEAD sebelum perubahan ini juga** (polusi state antar tes saat whole-suite
discover — store/watchlist betulan; lolos kalau modulnya dijalankan sendiri),
jadi bukan efek perubahan ini.

# Kegiatan — 10 September 2026 (grid 2 kolom: scan best di bawah watchlist chain-nya)

Permintaan user: *"🏆 Scan Best Pool Meteora dibawah 🌊 Watchlist
Meteora; 🦅 Scan Best Robinhood Coin dibawah 🦅 Watchlist Robinhood —
kita edit tampilannya, menjadi 2 grid."*

- `app.py`: kedua card scan best pindah **masuk ke grid 2 kolom** —
  kolom kiri = 🌊 Watchlist Meteora + 🏆 Scan Best Pool Meteora, kolom
  kanan = 🦅 Watchlist Robinhood + 🦅 Scan Best Robinhood Coin. Dulu
  keduanya full-width di bawah grid (Best Pool sebelum Scan Holder,
  Best Robinhood setelahnya). 🛰 Scan Holder dan 🧾 Log Aktivitas tetap
  full-width di bawah grid. Tidak ada perubahan logika scan/render card
  — hanya penempatan (listing di dalam card memakai kolom relatif, jadi
  aman menyempit setengah lebar).

# Kegiatan — 10 September 2026 (🧾 Log Aktivitas + scan "macet 6/7")

User melaporkan **Scan Best Robinhood macet di 6/7** dan **Scan Holder
biasa Robinhood ikut lambat** ("apakah kena limit? di 4 API semuanya?").
Diagnosa: bukan hang — kandidat terakhir jatuh ke paginasi RPC Blockscout
(400 wallet/halaman + jeda 0,6 dtk; token 80-100rb holder ≈ 10-15 menit),
sementara progress bar hanya di-update saat kandidat **selesai**
(`as_completed`) jadi terlihat diam. Scan Holder biasa melambat karena
**pool key PRO Blockscout dipakai bersama** oleh semua card dalam satu
proses; 6 worker Scan Best menabrak 5 RPS/key → key diparkir berantai →
request jatuh ke instance publik yang lambat.

Perbaikan (permintaan user: progress jujur + budget waktu + **log**):

- **`activity_log.py` (modul baru)** — ring buffer in-memory thread-safe
  (400 entri, dedup 60 dtk → `×N`), 4 level: `info` / `warn` / `error` /
  **`action` = perlu perubahan manual user → merah bold** (permintaan
  user eksplisit). Panel **🧾 Log Aktivitas** dirender di **paling bawah
  `app.py`**; kepala panel menampilkan pill jumlah per level +
  `pro_key_summary()` (status per key PRO: sisa kredit / parkir) —
  jawaban langsung "kena limit di key mana".
- **Instrumentasi**: `robinhood_holders` (key diparkir 401/402/403 =
  action, 429 = warn; semua key parkir → fallback publik = warn; 403
  bot-protection = action dengan petunjuk key; hasil fetch holder per
  token: sukses/terpotong/gagal), `robinhood_best_scan` +
  `meteora_screener` (scan mulai/selesai/listing gagal),
  `helius_holders` (key hilang = action, scan gagal = error),
  `watchlist._github_push` (token hilang = action, push gagal = error).
  Semua `import activity_log` dibungkus try/except — cron/tes tanpa
  modul/Streamlit tetap jalan.
- **`scan_candidates` (Scan Best Robinhood)**: progress dipanggil juga
  saat kandidat **mulai** dengan label `sedang: SYMBOL (+N lagi)` — 6/7
  tidak lagi terlihat seperti hang; **budget waktu per scan**
  (`CANDIDATE_TIMEOUT_SEC = 300` dtk): kandidat yang lewat budget
  dilewati (dicatat di log), thread telatnya dibiarkan selesai di latar
  (`shutdown(wait=False)` — sengaja bukan `with ThreadPoolExecutor` yang
  `shutdown(wait=True)`).

Tes: `tests/test_activity_log.py` (16) + 3 tes `scan_candidates`
(timeout/progress) → **1102 lulus** (71 dtk).

# Kegiatan — 10 September 2026 (Scan Best Robinhood Coin di halaman utama)

Permintaan user: *"buatkan saya Scan Best Coin Robinhood — datanya dari
gmgn … ini pakai volume 6 jam terakhir; sortnya: %dust paling kecil,
volume paling besar; hanya tampilkan yang top holder dibawah 30%; jika
pernah ada dexboost, menjadi poin tambah; hanya tampilkan yang %dust
<= 0,05%; buat di main app, seperti scan meteora pool; kasih nama Scan
Best Robinhood Coin; kasih tombol copy CA, add watchlist ke watchlist
robinhood."*

- Modul baru `robinhood_best_scan.py` + card **🦅 Scan Best Robinhood
  Coin** di halaman utama (`app.py`, full-width di bawah Scan Holder);
  bentuk meniru **Scan Meteora Pool** (tombol scan + progress, hasil di
  `session_state`, ⭐ per baris) + input "Jumlah kandidat" (default 50,
  sesuai `limit=50` di curl user).
- Sumber data: **endpoint rank publik GMGN** (diverifikasi live
  2026-09-10, tanpa auth): `GET
  /defi/quotation/v1/rank/robinhood/swaps/6h?orderby=volume&direction=
  desc&limit=N` → `data.rank[]` sudah berisi `top_10_holder_rate` +
  penanda Dexboost (`dexscr_boost_ts` / `dexscr_boost_fee`). Endpoint
  `follow_token/following_group_tokens` dari curl user **tidak dipakai**
  — butuh Bearer token user (hidup ±30 menit) dan hanya mengembalikan
  token yang di-follow; dicatat di `docs/gmgn_api.md`.
- Dust % MC dari **Blockscout** via `robinhood_holders.analyze_token`
  (FULL 100.000, LP/pool disingkirkan; harga + MC dari baris GMGN agar
  rasio konsisten dengan listing, `fetch_market` hanya untuk metadata
  pool). Rule: **top 10 holder < 30%** + **dust ≤ 0,05% MC** (nilai
  0,05% tepat ikut tampil), honeypot dikeluarkan; urut **dust % MC
  terkecil → volume 6 jam terbesar** (deterministik, tie simbol A-Z).
  Pernah Dexboost = **poin tambah**: badge 🚀 DEXBOOST + rekap di kepala
  card (bukan kunci sort).
- Baris: kolom Token/MC/Vol 6J/Liq/Holders/Top10/Dust %MC + tombol **📋
  copy CA** (JS clipboard + fallback; dirender `st.iframe` karena
  markdown Streamlit men-trip `<script>`; `st.components.v1.html` sudah
  deprecated di 1.61) dan **⭐ tambah ke Watchlist Robinhood LP**
  (halaman utama, scan cron ±5 menit; tanpa `st.rerun()` — pola ⭐
  Scan Meteora).
- Validasi: 24 test baru `tests/test_robinhood_best_scan.py`
  (normalisasi, filter/ambang, urutan, dexboost, AppTest card + tombol
  scan + ⭐); suite penuh **1067 tests** hijau.
- Catatan utk test: request GMGN/Blockscout **live tidak lulus jaringan
  sandbox** (TLS diputus — batasan yang sudah lama terdokumentasi);
  preview live hanya menampilkan warning "GMGN API: koneksi TLS …".
  Endpoint sudah diverifikasi publik & normal via klien lain; dari
  browser/Streamlit Cloud seharusnya langsung jalan.
  (Permintaan user: selesai dulu, nanti test & rapikan ulang bersama PR
  lain.)
# Kegiatan — 10 September 2026 (🏆 Scan Best Pool Meteora di halaman utama)

Permintaan user: *"replika scan meteora pool, masukkan ke main app page …
ganti filter baru seperti ini"* (curl `filter_by=pool_type=dlmm&&fee_pct>=5
&&active_tvl>=10000`, timeframe 24 jam, category top) — yang ditampilkan
hanya pool dengan dust holder < 0,05% MC, active TVL > 10K, fee/active TVL
> 20%, volatility > 5%, top 10 holder < 30%, total LPs > 20, **diurutkan
dari % dust terkecil lalu volume terbesar** ("ambil yang terbesar dan
terbaik"). Judul card: **Scan Best Pool Meteora**.

- `meteora_screener.py`: blok konstanta `BEST_*` + fungsi baru —
  `best_filter_by()` (menghasilkan `pool_type=dlmm&&fee_pct>=5&&
  active_tvl>=10000` persis filter UI Meteora), `fetch_best_pools()`,
  `rows_from_pools()` (dedup `pool_address`), `row_best_gaps()` (5 metrik
  pool: active TVL, fee/active TVL, volatility, top 10 holder, total LPs),
  `row_dust_ok()` (dust < 0,05% MC), `filter_best_rows()`,
  `sort_best_rows()`, dan `scan_best_meteora()`. Semua syarat **ketat**
  (`>`/`<`): angka pas di ambang tidak lolos, dan data hilang (`None`) juga
  gugur — helper `_maybe_float()` membedakan "nol" dari "tidak ada data"
  (beda dari `_float()` yang menelan `None` jadi 0).
- `_row_from_pool()` kini ikut membawa `volatility`, `total_lps`, dan
  `top_holders_pct` (diambil dari **token base**, bukan sisi quote SOL/USDC)
  supaya saringan baru punya datanya; field lama tidak berubah sehingga
  card **🌊 Scan Meteora Pool** di halaman temp tetap seperti semula.
- Hemat kuota Helius: 5 syarat metrik pool disaring **sebelum**
  `enrich_pools()`, jadi holder hanya di-fetch untuk pool yang masih bisa
  lolos; dust < 0,05% MC baru dicek setelahnya.
- Urutan baris `sort_best_rows()`: **dust % MC terkecil → volume terbesar**.
  Kunci dust dibulatkan ke `BEST_DUST_SORT_DECIMALS` (3 desimal = angka yang
  tampil di card) supaya dua pool yang di layar sama-sama "0,030%" diurutkan
  menurut volumenya; baris tanpa angka dust paling bawah, simbol alfabetis
  sebagai tie-break terakhir (deterministik antar scan).
- Card baru `best_pool_ui.render_best_pool_scan()` dirender full-width di
  **halaman utama** (`app.py`, antara grid watchlist dan 🛰 Scan Holder,
  dipisah `st.divider()`): 12 kolom listing (Token · MC · A.TVL · Fee/TVL ·
  Vol · Top10 · LPs · Fee · Dust · Dust %MC 3 desimal · Pool · ⭐), kepala
  card `card_head_html()` dengan pill jumlah pool + yang disembunyikan, dan
  detail karakteristik di **tooltip judul** (`best_pool_tooltip()`) mengikuti
  konvensi 2026-09-10. Tombol scan: **🏆 Scan Best Pool Meteora + Holder**
  (progress bar holder, hasil di `session_state["best_pool_scan"]`).
- ⭐ memakai `source=meteora` (`lp_watchlist.LP_SOURCE`) → token masuk card
  **🌊 Watchlist Meteora** di halaman utama dan ikut cron ±5 menit; key
  tombol diikat ke pool address, bukan nomor baris (urutan listing berubah
  setelah scan ulang).
- Tidak ada perubahan data/cron/alert: `watchlist*.json`, history, source
  token, jadwal scan, dan rule Telegram tidak disentuh. Card **🌊 Scan
  Meteora Pool** di halaman temp tetap ada dengan filter lamanya (24 jam
  `fee_active_tvl_ratio≥250` + 1 jam `≥1`).
- Validasi: suite penuh **1059 tests** hijau lewat `pytest` (16 test baru di
  `tests/test_best_pool_scan.py`: string `filter_by`, parameter
  `fetch_best_pools`, ekstraksi metrik baru, tiap syarat ketat + boundary
  0,05%/10K/20%/5%/30%/20, `filter_best_rows`, urutan dust→volume termasuk
  tie presisi tampilan, `scan_best_meteora` end-to-end dengan `enrich_pools`
  di-mock — memastikan pool yang gugur di metrik tidak di-fetch holder-nya —
  serta AppTest `app.py` yang memastikan card + tombol + listing terender di
  halaman utama); `python -m py_compile` semua modul daftar AGENTS.md bersih;
  live preview Streamlit port 8501. **Catatan:** API Meteora/DexScreener
  tidak terjangkau dari sandbox ini (TLS ditutup), jadi listing live
  diverifikasi lewat endpoint `pool-discovery-api.datapi.meteora.ag/pools`
  dengan `filter_by` yang sama (32 pool, field `volatility`/`total_lps`/
  `top_holders_pct` ada di response); angka dust tetap butuh `HELIUS_API_KEY`
  saat dijalankan di dashboard.

# Kegiatan — 10 September 2026 (Wallet Depth by Threshold → grafik perubahan dust holder ala Watchlist Meteora)

Permintaan user: *"📊 Wallet Depth by Threshold - ganti seperti pada
**Watchlist Meteor** / Grafik perubahan dust holder"* — expander mandiri
**📊 Wallet Depth by Threshold** (hanya tabel bucket + tier) di baris
watchlist diganti expander grafik seperti card **Watchlist Meteora**; tabel
Wallet Depth tidak dihapus melainkan ikut ter-nested di dalam expander
grafik (persis susunan di Watchlist Meteora).

- Pembuat bersama baru `dashboard_components._render_dust_change(points,
  holders, symbol, interval=…)`: expander **📈 Grafik perubahan dust
  holder — $SYM** berisi grafik `lp_watchlist.lp_chart_figure(...,
  interval=…)` (garis dust % MC + garis ambang HATI-HATI/BAHAYA + batang
  jumlah wallet dust), caption ringkas, lalu `_render_depth` ter-nested
  bila scan menghasilkan `depth`. Pesan "belum cukup titik" mengikuti
  kadens (`_dust_change_empty_note`).
- `lp_watchlist.lp_chart_figure` kini menerima `interval` (default tetap
  `LP_INTERVAL_SEC` = bucket 5 menit, jadi output Watchlist Meteora tidak
  berubah); helper `interval_label()` memberi judul "(5 menit)" /
  "(4 jam)". `resample_5m` di figure diganti `resample_4h(...,
  interval=…)` yang identik untuk default lama.
- Dipakai di tiga card: **🦅 Watchlist Robinhood** LP (bucket 5 menit) +
  Robinhood biasa (bucket 4 jam) di `dashboard_components._render_rh_row`,
  dan **📋 Watchlist Holder** biasa di `temp_ui.py` (bucket 4 jam).
  `_render_lp_row` di `app.py` dipindah ke pembuat yang sama supaya bentuk
  rujukan tidak bercabang (caption/jumlah bucket tetap sama).
- Tidak ada perubahan data/cron/alert: `watchlist*.json`, history, source
  token, jadwal scan, dan rule Telegram tidak disentuh — hanya presentasi
  baris watchlist.
- Validasi: suite penuh **1043 tests** hijau (5 test baru: figure bucket 4
  jam + `interval_label`, AppTest baris Robinhood LP & watchlist biasa
  merender expander grafik + caption); AppTest data asli repo tanpa
  exception (expander grafik tampil di baris $STONK dan $ORBIO); live
  preview Streamlit port 8501.

# Kegiatan — 10 September 2026 (rename card + detail jadi tooltip judul)

Permintaan user: ganti judul card — **🌊 Chart LP — Watchlist Meteora** →
**🌊 Watchlist Meteora**, **🦅 Watchlist Robinhood LP — Holder Dust** →
**🦅 Watchlist Robinhood**, **🛰 Scan Holder Khusus — Helius / Robinhood** →
**🛰 Scan Holder Solana / Robinhood** — dan teks detail karakteristiknya
bukan caption lagi melainkan **tooltip** yang hanya muncul saat kursor
digeser ke tulisan judulnya. Selain itu **🌊 Scan Meteora Pool** dipindah ke
halaman temp dan **Watchlist Robinhood** (LP) pindah ke samping **Watchlist
Meteora**.

- Tooltip = atribut `title="…"` native browser di teks judul, bukan elemen
  tambahan: card memakai `dashboard_components.card_head_html(title, pills,
  tooltip=…)` (atribut menempel di `<span class="lp-title">`), section Scan
  Holder memakai `hover_title_html()` — heading markdown `###` dengan
  `<span title>` supaya styling persis `st.subheader` dan tooltip hanya
  aktif di atas teks (bukan seluruh lebar baris). CSS `cursor:help`
  ditambahkan sebagai hint halus.
- Teks detail hidup di konstanta — `LP_CARD_TOOLTIP` + `SCAN_HOLDER_TOOLTIP`
  (`app.py`), `RH_CARD_TOOLTIP` (`dashboard_components.py`) — dengan ambang
  diambil dari konstanta `holder_history` (`DUST_BEST_PCT`,
  `DUST_CAUTION_PCT`, `DUST_DANGER_PCT`), jadi kalau karakteristik/rule
  berubah tinggal edit konstanta dan angkanya tetap sinkron. Atribut
  `title` tidak mengenal markdown → teks plain (tanpa `**`).
- `app.py`: grid 2 kolom kini **kiri** Watchlist Meteora, **kanan** Watchlist
  Robinhood LP (`_render_rh_card(variant="lp")` dipindah dari full-width ke
  kolom kanan; `split_robinhood_watchlist` naik ke atas grid). Scan Holder
  tetap full-width di bawah `st.divider()`. Label di dalam card LP ikut
  diganti ("Tambah CA manual ke Watchlist Meteora", "Scan sekarang Watchlist
  Meteora", ✕ "Hapus dari Watchlist Meteora", info kosong menunjuk
  **⭐ Scan Meteora Pool di halaman temp (📦)**).
- `temp_ui.py`: `render_meteora_scan()` (pindahan `app.py`, termasuk
  `_meteora_head_html` + `METEORA_CARD_TITLE`) dipanggil sebelum section
  **🔍 Temukan Token**; `card_head_html` kini pembuat kepala bersama.
  ⭐ tetap `add_to_watchlist(..., source=meteora)` — targetnya card
  **Watchlist Meteora** di halaman utama; caption/help di halaman temp
  disinkronkan ("Chart LP" → "Watchlist Meteora").
- `dashboard_components.py`: judul card LP Robinhood menjadi
  `RH_CARD_TITLE = "🦅 Watchlist Robinhood"` (card biasa/temp tetap
  "🦅 Watchlist Robinhood — Holder Dust"); caption LP dihapus dan digantikan
  tooltip, caption card biasa (temp) tidak diubah.
- Tidak ada perubahan data/cron: `watchlist.json`,
  `watchlist_robinhood.json`, source token, jadwal scan ±5 menit, dan rule
  alert Telegram sama persis — hanya judul, teks, dan posisi card.
- Validasi: `py_compile` app/temp_ui/dashboard_components lolos; suite
  penuh **1038 tests** = sama dengan baseline (2 FAIL `test_scan_holders`
  itu pre-existing saat dijalankan `discover`, terbukti ikut muncul di
  `git stash` baseline); AppTest ad-hoc memastikan tiga tooltip ter-render
  di markup (atribut `title` lengkap) tanpa exception; live preview
  Streamlit port 8501. Frontend Streamlit memakai `rehype-raw`, jadi HTML
  inline (termasuk `title`) di dalam heading markdown ikut ter-render.

# Kegiatan — 9 September 2026 (cron 5 menit mati lagi: rantai dipindah ke skrip)

User: *"coba cek kenapa cron tidak berjalan per 5 menit"* (run #1182 selesai
16:40:24 UTC; tidak ada run baru sampai 17:29 UTC ke atas).

## 1. Diagnosa (angka dari `GET /actions/workflows/daily-effort.yml/runs`)

- Repo **publik** (`isPrivate: false`) dan workflow berstatus `active` → bukan
  kuota billing, bukan workflow dinonaktifkan.
- Hari itu `schedule: */5` hanya menghasilkan **4 run** (01:35, 06:41, 11:56,
  16:30 UTC) dari 288 yang dijadwalkan — scheduler GitHub di-throttle, jarak
  antar-kejadian 4,5–5,2 JAM. Bukan anomali baru: `*/15` pernah terukur ±2 jam
  (DEPLOY.md).
- Pola tiap kejadian schedule identik: schedule → **tepat satu** chain dispatch
  → hening (01:35→01:35, 06:41→06:45, 11:56→12:00, 16:30→16:35). Empat stall
  hari itu (01:40, 06:50, 12:05, 16:40 UTC) = empat kejadian schedule.
- Akar masalah: **Guard 2 di `.github/workflows/daily-effort.yml`** — dispatch
  dilewati bila run `event=schedule` terakhir selesai < 900 detik lalu. Chain
  dispatch berjalan ±5 menit setelah schedule, jadi umurnya selalu ~300 detik →
  "schedule */5 sehat" → dispatch dibuang → tidak ada yang membangunkan
  pipeline sampai schedule (telat berjam-jam) berikutnya. Guard lama juga tidak
  mengecualikan run sendiri (query `event=schedule&status=completed&per_page=1`),
  akibatnya run schedule SELALU dispatch dan run dispatch SELALU skip —
  persis rasio 1:1 yang terukur.
- Perbaikan Guard 2 sudah ditulis pagi harinya di `daily-effort-5menit.yml`
  (root repo) tapi **tidak pernah terpasang**: `git push` yang menyentuh
  `.github/workflows/*` ditolak remote (`refusing to allow a GitHub App to
  create or update workflow ... without 'workflows' permission`) — diverifikasi
  ulang hari ini dengan pesan yang sama.
- Temuan tambahan: langkah rantai versi inline bash **fail-closed** — di bawah
  `bash -e`, satu hiccup `curl -sSf` di `ACTIVE=$(…)` membatalkan seluruh
  langkah tanpa dispatch (stall yang sama, penyebab lain), dan daftar run
  queried 2× per run (Guard 1 + Guard 2) padahal cukup sekali.

## 2. Perbaikan

- **`scripts/chain_next_run.py`** (baru, stdlib saja): tidur ke batas kadens →
  SATU `GET …/runs` dipakai Guard 1 (antrean `holder-scanner`) + Guard 2 (umur
  run `completed` terbaru, event apa pun, cabang sama, run sendiri dikecualikan)
  → `POST dispatches`. `CHAIN_QUIET_SEC=240` < kadens 300 supaya rantai tidak
  bisa mematikan dirinya sendiri; API error = **fail-open** (tetap dispatch —
  run ganda sudah disaring `MIN_RUN_GAP_SEC` di scanner); retry 3× GET / 4×
  POST dengan backoff, 400/401/404/422 tidak diulang; dispatch buntu → `exit 1`
  + pesan "rantai TERPUTUS" supaya run merah, bukan hijau tanpa penerus; tanpa
  `GITHUB_TOKEN`/`GITHUB_REPOSITORY` (jalankan lokal) → `exit 0` diam.
- **`daily-effort-5menit.yml`**: langkah "Chain run berikutnya" jadi satu baris
  `python scripts/chain_next_run.py` + env `CHAIN_CADENCE_SEC`/`CHAIN_WORKFLOW`.
  Karena logika pindah ke skrip, yang butuh UI tinggal satu baris YAML;
  alternatif permanen: **Settings → Third-party Access → app bot → Repository
  permissions → Actions Workflows: Read & write**.
- **`tests/test_chain_next_run.py`** (28 test, offline): tabel keputusan guard
  termasuk **regresi stall 2026-09-09** (`active=0`, umur run schedule 299 s →
  wajib dispatch), filter cabang/dirinya, `--quiet-sec ≥ --cadence` dipotong
  otomatis, retry 5xx vs 4xx permanen, fail-open saat API mati, exit 1 saat
  dispatch buntu, dan `next_boundary_wait`.

## 3. Yang harus dilakukan user

1. **Pasang `daily-effort-5menit.yml` ke `.github/workflows/daily-effort.yml`**
   (GitHub UI → Actions → Holder Dust Scanner → edit → timpa dari baris `name:`
   → commit). Tanpa ini Guard 2 lama tetap membuang dispatch.
2. Sembari menunggu, **jalankan "Run workflow" manual** (tanpa centang): rantai
   langsung tersambung lagi — guard lama hanya membuang dispatch bila ada run
   `schedule` selesai < 15 menit lalu, jadi mulai sekarang chain jalan terus
   sampai kejadian schedule berikutnya.

## 4. Batas verifikasi

Sandbox tidak bisa mengunduh log run (`results-receiver`/blob storage diblokir),
jadi pesan guard disimpulkan dari **pola waktu run** (create/update + event),
bukan dari stdout langkah "Chain run berikutnya". Skrip diverifikasi terhadap
API asli read-only (50 run terbaca; `head_branch`, `updated_at`, status
`completed`+conclusion `cancelled` diperlakukan benar) dan jalur fail-open
dengan token palsu (404 → dispatch tetap dicoba, retry tidak dibakar).
Kadens nyata setelah fix terpasang baru terbukti ±1–2 jam di tab Actions.

# Kegiatan — 9 September 2026 (secret GitHub ≠ secret Streamlit)

User: *\"1 alert GAGAL dikirim (Telegram credentials are not configured).
sebentar, saya sudah setting token di secret loh, apa butuh di setting di
streamlit juga?\"*

Ya. Secret **GitHub Actions** (`Settings → Secrets → Actions`) hanya
terlihat cron; scan manual jalan di proses Streamlit Cloud yang tidak
menerima env itu. Perlu **dua** secret di **kedua** tempat:
`TELEGRAM_BOT_TOKEN` **dan** `TELEGRAM_CHAT_ID`. Token bot saja tetap
gagal dengan pesan yang sama.

- `_telegram_credentials()` kini menerima nama key huruf besar
  (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`, konvensi GitHub/DEPLOY)
  **dan** huruf kecil (`telegram_bot_token` / `telegram_chat_id`) dari
  env, `config.json`, dan `st.secrets` — sebelumnya Streamlit hanya
  membaca huruf kecil, jadi secret yang disalin persis dari GitHub ke
  Streamlit Cloud tidak ketemu.
- DEPLOY.md bagian **Setup Telegram** memisahkan langkah GitHub (cron)
  vs Streamlit Cloud (scan manual) + contoh TOML. AGENTS.md + README
  menyebut pemisahan yang sama.
- Tes baru: secrets Streamlit huruf besar, huruf kecil, dan token tanpa
  chat ID tetap dilaporkan belum terpasang.

# Kegiatan — 9 September 2026 (MOO 0,11% tanpa alert: cron mati + scan manual bisu)

Laporan user: `0xc103ac00a25173870c909223c5676d50bf5728b2` (MOO) menampilkan
**0,11% MC** di card Robinhood tetapi tidak ada pesan Telegram.

## 1. Diagnosa (semua angka dari API GitHub, bukan asumsi)

- Token **benar** ada di lane LP: `watchlist_robinhood.json` di `main`
  (commit `3c537ff`, 2026-09-09T21:53:20+07:00 = **14:53:20 UTC**) memuat MOO
  dengan `source: "lp"` — jadi scope rule ⚡ EARLY DUMP mencakupnya.
- **Cron berhenti**: run workflow `Holder Dust Scanner` terakhir selesai
  **2026-09-09T12:05:24Z**; tidak ada run lagi sampai 15:16 UTC (±3 jam)
  meski jadwalnya `*/5 * * * *`. Hari itu schedule GitHub hanya menyala 3×
  (01:35, 06:41, 11:56 UTC), masing-masing diikuti **tepat satu** chain
  dispatch lalu hening. MOO baru masuk watchlist **14:53 UTC**, jadi cron
  belum pernah memindainya sama sekali → tidak mungkin ada alert.
- Snapshot Robinhood di ref `holder-live` terakhir
  **2026-09-08T03:56:11Z** dan hanya berisi CME. Ini **bukan** lane rusak:
  pada run 11:56 UTC watchlist Robinhood di `main` masih `{}` (PARE baru
  ditambah 13:24 UTC, NUDES 14:01 UTC), jadi scanner memang mencetak
  "watchlist LP kosong".
- **Akar masalah ritme**: langkah "Chain run berikutnya" punya Guard 2 yang
  menyimpulkan "schedule */5 sehat" bila ada run `event=schedule` yang
  selesai < 900 detik lalu, lalu **melewati dispatch**. Scheduler GitHub bisa
  di-throttle berjam-jam, jadi begitu satu dispatch dilewati tidak ada lagi
  yang membangunkan pipeline. Dibuktikan dengan data run asli: pada
  12:05:24Z umur run schedule terakhir 299 detik → guard lama
  `299 < 900` = lewati (stall), guard baru `299 ≥ 240` = dispatch.
- **Scan manual tidak pernah mengirim alert**: `process_holder_alerts`
  hanya dipanggil `scripts/scan_holders.py`; tombol scan di dashboard cuma
  `publish_scan(..., push=False)`. Angka 0,11% yang dilihat user berasal
  dari scan manual itu — tampil di dashboard, tidak pernah jadi pesan.
- Rule-nya sendiri sehat: simulasi `process_holder_alerts(lp_mints={MOO},
  volume_rules=False)` dengan dust 0,11% MC menghasilkan 1 event
  ⚡ EARLY DUMP (tanpa `lp_mints` → 0 event).

## 2. Perbaikan

- **Scan manual ikut mengirim alert** (permintaan user). Tiga tombol —
  Chart LP Meteora (`app.py`), Robinhood LP/biasa
  (`dashboard_components._render_rh_card`), watchlist biasa Solana
  (`temp_ui.py`) — memanggil `process_holder_alerts` **sebelum**
  `ingest_many`/`publish_scan`, jadi rule membaca anchor lama dan state
  (`sent_event_ids`/`last_sent`/marker episode) ikut tersimpan bersama titik
  baru. `volume_rules=False`: hanya rule lane (⚡ EARLY DUMP + eskalasi EXIT
  di LP, 🔔 HIGH DROP di lane biasa), anchor 4 jam cron tidak digeser.
  `mute_mints` mengikuti tombol on/off notif watchlist biasa.
- **Hasil kirim dilaporkan ke UI** (`_store_alert_note` /
  `_render_alert_note`, lewat `session_state` karena tiap tombol langsung
  `st.rerun()`): "⚡ 1 alert Telegram dikirim", "dilewati (notif watchlist
  biasa OFF)", atau "**GAGAL dikirim** (alasan)" — kegagalan tidak lagi
  terbaca seperti "tidak ada sinyal".
- **Kredensial Telegram** dibaca `env → config.json → st.secrets`
  (`telegram_alerts._telegram_credentials()`, lazy + guarded karena runner
  Actions hanya memasang requests + curl_cffi). Dashboard tidak punya env
  Actions, jadi tanpa ini scan manual selalu gagal kirim.
- **Guard 2 chain dispatch** di `daily-effort-5menit.yml`: pembandingnya run
  terakhir **event apa pun** dengan jendela `CHAIN_QUIET_SEC=240` (< kadens
  5 menit), bukan umur run schedule 900 detik. Aman dari stall karena
  langkah ini tidur sampai batas 5 menit berikutnya, jadi satu run minimal
  ±320 detik — run yang baru selesai pasti lebih tua dari jendela.

## 3. Yang harus dilakukan user

1. **Salin `daily-effort-5menit.yml` ke `.github/workflows/daily-effort.yml`**
   lewat GitHub UI (bot ditolak menulis folder workflow: tanpa izin
   `workflows`). Selama belum disalin, cron tetap memakai Guard 2 lama dan
   bisa mati berjam-jam lagi.
2. Pasang **`telegram_bot_token` + `telegram_chat_id`** di secrets Streamlit
   (atau `config.json`) bila ingin notif dari scan manual; tanpa itu UI kini
   menampilkan "GAGAL dikirim (Telegram credentials are not configured)".
3. Untuk memicu scan sekarang: Actions → "Holder Dust Scanner" → **Run
   workflow** (MOO sudah di lane LP, jadi ⚡ EARLY DUMP langsung terkirim
   bila dust masih > 0,1% MC).

## 4. Validasi & batas verifikasi

- **1007 passed, 37 subtests passed** (991 baseline + 16 tes baru di
  `tests/test_manual_scan_alerts.py`: ringkasan kirim, fallback kredensial
  config.json/env, scan manual Chart LP mengirim ⚡ di 0,11% dan diam di
  0,05%, 🚨 EXIT/CUTLOSS saat naik 3× berturut, ✅ KEMBALI KE TITIK AMAN saat
  turun ≤ 0,1% MC, dedup bucket 5 menit antar scan manual, state alert ikut
  tersimpan, Robinhood LP mengirim ⚡, lane biasa memakai 🔔 HIGH DROP, dan
  mute saat notif OFF).
- Tabel karakteristik → notif diverifikasi dengan menjalankan
  `process_holder_alerts` langsung (fungsi yang dipanggil tombol scan
  manual): 0,11% → ⚡; 0,05% dan tepat 0,10% → diam; naik 3× dalam 15 menit →
  ⚡ + 🚨 `exit_cutloss`; turun ke 0,08% dalam jendela episode → ✅
  `safe_return`; high 0,80% → 0,20% → 🔔; high 0,80% → 0,50% → diam; holder
  10 wallet (scan tidak layak) → diam; notif biasa OFF → mute.
  Catatan: marker episode **wajib** bersarang di
  `alert_state["early_dump"]` (dan 🔔 di `alert_state["high_drop"]`) — bentuk
  yang salah membuat rule episode tidak pernah melihat episodenya; dua tes
  baru mengunci bentuk itu.
- Log run Actions **tidak terbaca** dari sandbox (unduh log `EOF`), daftar
  secret repo **403**, dan API live Blockscout/DexScreener tidak terjangkau
  (egress sandbox hanya GitHub/PyPI) — jadi penyebab pasti kosongnya lane
  Robinhood di run-run sebelumnya disimpulkan dari isi watchlist per commit +
  timestamp snapshot, bukan dari log.

# Kegiatan — 9 September 2026 (header dihapus + grid 2 kolom)

Permintaan user: buang header penjelasan di atas halaman utama, lalu
tampilkan **Chart LP — Watchlist Meteora** di kiri dan **Scan Meteora Pool**
di kanan sebagai grid 2 kolom.

- `app.py`: blok `.hero` (judul 🧮 Wallet Depth + ringkasan ambang) dihapus;
  halaman sekarang mulai dari tautan 📦 temp + toggle auto-refresh. Card
  Chart LP dan Scan Meteora dirender berdampingan lewat
  `st.columns([1, 1], gap="medium")` — dua card ber-`border` sejajar, ⭐ di
  kanan tetap memasukkan token ke card kiri. Robinhood LP dan Scan Holder
  Khusus tetap full-width di bawah, dan `st.divider()` dipindah ke sebelum
  card Robinhood (divider milik Scan Meteora hilang bersama subheader-nya).
  Di layar sempit kolom Streamlit menumpuk sendiri.
- `_render_meteora_scan()`: `st.divider()` + `st.subheader` diganti
  `st.container(border=True)` + kepala `_card_head_html()` (helper baru,
  dipakai juga oleh `_lp_head_html`) dengan pill `N pool` / `🏆 N BEST` /
  `N disembunyikan`. Hasil scan disimpan ke `session_state` lalu
  `st.rerun()` supaya pill, caption, dan listing satu sumber data — pola
  yang sama dengan tombol Scan di card LP. Kolom tabel, badge 🏆 BEST POOL,
  filter dust ≤ 0,1% MC, urutan `sort_rows()`, dan key tombol tidak berubah.
- `dashboard_components.py`: CSS `.hero` dihapus (sudah tidak ada pemakai).
- Teks petunjuk ikut disinkronkan: "Scan Meteora Pool **di bawah**" →
  "**di kolom kanan**", "⭐ … ke card Chart LP di bagian atas dashboard" →
  "di kolom kiri"; AGENTS.md + docstring `lp_watchlist` diperbarui.
- Validasi: **991 passed, 37 subtests passed** (sama dengan baseline
  sebelum perubahan), `py_compile` daftar modul AGENTS.md lolos, dan
  AppTest ad-hoc memastikan grid benar-benar 2 kolom (kolom 0 = card Chart
  LP + form/tombol scan LP, kolom 1 = card Scan Meteora + ⭐) tanpa
  exception. Live preview Streamlit port 8501; scan live Meteora/Helius
  tidak dijalankan dari sandbox (tanpa API key), jadi preview menampilkan
  listing kosong sampai tombol scan ditekan.

# Kegiatan — 9 September 2026 (halaman temp)

Permintaan user: parkir tiga section yang sementara tidak digunakan ke
halaman baru bernama **temp**.

- `pages/8_temp.py` (`/temp`) + `temp_ui.py`: Robinhood biasa/non-LP,
  Watchlist — Analisa Holder (Dust), dan Temukan Token (Trending/Degen).
  Data dan kontrol tambah, scan, pindah lane, hapus, serta setelan Telegram
  tetap tersedia. Scan manual hanya lane yang tampil, bukan token LP di
  halaman lain; snapshot lain tetap di-merge.
- `app.py`: hanya Chart LP Meteora, Scan Meteora, Robinhood LP, dan Scan
  Holder Khusus. Tautan **📦 temp** di atas; halaman temp memiliki tautan
  kembali. Tidak mengubah source token, store, cron, atau setelan alert.
- `dashboard_components.py`: presentasi/CSS dan card Robinhood bersama;
  loader data menjaga store Solana/Robinhood dan overlay manual. Tidak
  mengimpor/menjalankan halaman utama untuk membuka temp.
- AppTest lama diarahkan ke halaman baru sesuai section; 9 tes navigasi,
  pembagian layout, persistensi, scan per lane (Robinhood tetap 100.000),
  default form, dan pindah token antarhalaman ditambahkan.
- Validasi: **991 passed, 37 subtests passed**, py_compile dan pemeriksaan
  import/nama tidak terdefinisi lolos. Live preview Streamlit port 8501.

# Kegiatan — 9 September 2026 (PARE: cakupan scan watchlist)

Laporan: PARE `0x15d36b6a28d8327abc7afabf0f106ae2c9af5c4d`
0,00% di watchlist vs 0,03% di Scan Holder Khusus.

- Akar masalah kode: cap watchlist Robinhood 2.000 / cron 3.000 berbeda
  dari scan khusus 100.000. Urutan saldo terbesar Blockscout memotong ekor
  dust. Tombol dan cron Robinhood sekarang 100.000; budget workflow
  `--max-wallets` hanya untuk Solana. Default modul Robinhood juga 100.000.
- Penanda `truncated` diperbaiki untuk CSV capped/counters tak lengkap,
  RPC gagal setelah sebagian halaman, dan batas halaman v2. Alasan hasil
  parsial diteruskan; guard bersama menolaknya dari snapshot, angka baris,
  grafik, dan alert, termasuk history lama bertanda truncated. Data lama
  tidak diubah; memakai hasil lengkap terakhir atau belum ada data.
- Tes baru mereproduksi cap 2.000/3.000 → 0,00% dan lengkap → 0,03%
  memakai fixture sintetis 3.300 holder. Wiring tombol UI dan cron lama,
  fallback provider, publish/history, dan guard alert ikut diuji.
- Validasi: **982 passed, 36 subtests passed**, py_compile sukses.
  API live tidak terverifikasi dari sandbox karena kegagalan TLS; angka
  0,03% produksi berasal dari laporan user, bukan hasil scan live sesi ini.
  Tidak mengubah workflow atau file status/history produksi.

# Kegiatan — 9 September 2026 (sesi 12 · 📨 Telegram: judul 50 bin + hyperlink)

Permintaan user: judul eskalasi diganti menjadi **"🚨 WAKTUNYA EXIT /
CUTLOSS / Reshape bid-ask 50 bin"** (dulu 25 bin), dan baris link
`🔗 GMGN: https://gmgn.ai/sol/token/<mint>` / `🦆 DexScreener: https://…`
diganti **hyperlink** saja, bukan URL polos.

- `telegram_alerts.ESCALATION_TITLE` → "… 50 bin".
- `build_alert_message(event)` baru → `(teks, entities)`: baris link hanya
  `"<emoji> <label>"` dan label diberi entity `text_link` Bot API (offset /
  length UTF-16, sama seperti entity `bold` judul EXIT yang sudah ada).
  Berlaku untuk semua jenis alert dan semua link: GMGN, DexScreener,
  Meteora, HawkFi (LP), rh-scan, Blockscout (Robinhood). `send_telegram_alert`
  memakai builder ini; `format_alert_message()` sekarang hanya teksnya
  (dipakai log/tes). Tanpa mint → tanpa baris link & tanpa entity.
- `links.token_links(ca)` → `[(emoji, label, url)]` sebagai satu sumber;
  `token_link_lines()` (teks polos) tetap ada untuk log/CLI, tidak lagi
  dipakai Telegram. `telegram_alerts._pool_links()` padanannya untuk pool.
- Tes diperbarui: `test_telegram_alerts.py` (helper `_utf16_slice`/`_links`
  memverifikasi label & URL tiap entity, offset tepat walau symbol/mint
  beremoji, alert lain tanpa bold, test alert tanpa entities),
  `test_exit_cutloss.py`, `test_early_dump.py`. **Suite penuh 969 passed.**
- README (contoh pesan + catatan hyperlink), AGENTS.md.

# Kegiatan — 9 September 2026 (sesi 11 · 🦅 Blockscout PRO API: beberapa key sekaligus)

Pertanyaan user: *"1 api cukup atau tidak? atau beberapa api sekaligus?"* →
hitungan: ±3 request Blockscout per token per scan (getToken + counters +
CSV ≈ 60–80 kredit), cron 288 run/hari, free tier 100K kredit/hari & 5 RPS
**per akun** → 1 key cukup untuk ≤ 3–4 token LP; token > 10.000 holder
(paginasi RPC) atau watchlist lebih besar butuh lebih. Key tambahan dari
akun yang **sama** tidak menambah kuota. User: *"saya sudah punya 4 key,
kita menggunakan lebih dari 1 key, tolong bikinkan"*.

## 1. `robinhood_holders.py`: pool key PRO (`_ProKeyPool`)

- `get_pro_api_keys()` menggabungkan semua sumber (pola
  `core.get_helius_keys`, memakai `merge_helius_keys`): env
  `BLOCKSCOUT_API_KEY` / `BLOCKSCOUT_API_KEYS` (koma/baris baru) /
  `BLOCKSCOUT_PRO_API_KEY` → `blockscout_api_key` / `blockscout_api_keys`
  di `config.json` → Streamlit secrets nama sama; dedup, urutan = label
  `key#1..N`. `get_pro_api_key()` tetap ada (key pertama).
- `_pro_round()`: round-robin di antara key **aktif**; `ProApiError`
  401/403 → parkir 60/5 mnt, 402 kredit habis → parkir 30 mnt (probe ulang
  murah karena reset harian Blockscout tidak berjam tetap), 429 → parkir
  sesuai `x-ratelimit-reset` (≤ 60 dtk); request langsung pindah ke key
  berikutnya di putaran yang sama tanpa backoff. 404 rute → publik.
  Semua key diparkir → `ProKeysParked` → publik. Sisa kredit dibaca dari
  `x-credits-remaining`. Thread-safe (ThreadPool `scan_watchlist`);
  `clear_holder_cache()` juga me-reset pool.
- Pelaporan tanpa bocor key: `pro_key_status()`, `pro_key_summary()`
  (*"Blockscout PRO API: 4 key · key#1 sisa 90,850 kredit, 5 req · key#2
  parkir 402 kredit habis (30 mnt) · …"*), `WARN` sekali per key di stderr.
  Hasil `fetch_holders` bertambah `pro_key` (label yang dipakai) &
  `pro_keys` (jumlah key); `analyze_token` meneruskannya ke `holders`.
- `BlockscoutBlocked` punya `hint` terpisah: tanpa key → "pasang
  BLOCKSCOUT_API_KEY"; key ada tapi PRO ikut gagal →
  `HINT_KEYS_FAILED` ("key PRO API ada tetapi semuanya ditolak / kreditnya
  habis — periksa dashboard") + detail `PRO: PRO API 402 … (key#4)`.

## 2. UI, cron, konfigurasi

- `app.py`: caption *Blockscout (Robinhood Chain) · PRO API key#3*; pesan
  `scan_failed`+`blocked` dibedakan: 0 key → "Pasang `BLOCKSCOUT_API_KEY`
  …", N key → "N key PRO API terpasang tetapi semuanya ditolak / kredit
  hariannya habis — cek dashboard … atau tambah key akun lain ke
  `BLOCKSCOUT_API_KEYS`"; baris watchlist ikut. `pages/5_🧮_Holder.py`
  sama.
- `scripts/scan_holders.py`: `blockscout_pro_keys=N` di baris rencana,
  `WARN` bila 0 key, ringkasan pool setelah scan, `route=` dari label.
- Workflow (`daily-effort-5menit.yml` + `.github/workflows/daily-effort.yml`)
  meneruskan `BLOCKSCOUT_API_KEYS`; `config.example.json` +
  `blockscout_api_keys`.

## 3. Tes & dokumen

- `tests/test_robinhood_transport.py` +12 (31 total): sumber key
  (env daftar, config dua nama, secrets list/string), round-robin, 402 →
  parkir & pindah key, 429 sesuai header, probe ulang setelah parkir,
  semua key gagal → publik + pesan "key habis" tanpa bocor key, label key
  di hasil/analyze_token, pool dibangun ulang saat daftar key berubah.
  `tests/test_rh_card_ui.py` +2 AppTest. **Suite penuh 965 passed** (1
  flaky lama `test_watchlist_clear` lulus saat diisolasi).
- Dok: DEPLOY.md bagian baru **Setup key Blockscout PRO API** (langkah
  Streamlit Cloud + GitHub), README (paragraf + tabel env), AGENTS.md,
  `docs/robinhood_holders_api.md` (diagram pool).

# Kegiatan — 8 September 2026 (sesi 10 · 🦅 Blockscout 403 → PRO API + fallback publik)

Laporan user: Scan Holder Khusus untuk CA Robinhood
`0x1209ec401498a1b781412576c978eee0daa0bb6e` pulang *"Scan tidak
menghasilkan holder. Pastikan CA valid dan harga token tersedia
(DexScreener). Detail: getToken: 403 Client Error: Forbidden …; csv: 403 …;
v2: 403 …"*. Analisis user (WAF/Cloudflare atau migrasi ke PRO API, bukan CA
salah) **divalidasi benar**: dari klien browser endpoint yang sama masih 200
(Pusheen, 409 holder, 18 desimal), dan dokumen resmi Blockscout menyatakan
instance publik dilindungi bot-protection (403 + halaman "Just a moment…")
sementara akses API per-instance **deprecated** → akses program lewat
**PRO API** `https://api.blockscout.com/4663/…` dengan key gratis
(`proapi_…`, <https://dev.blockscout.com>, tanpa kartu; free tier 5 RPS /
100K kredit per hari ≈ 3.000–5.000 request). Opsi #2 user (User-Agent
browser) sudah dipakai sejak awal dan terbukti tidak cukup — yang difilter
TLS fingerprint/IP server.

## 1. `robinhood_holders.py`: transport PRO API → instance publik

- Semua request lewat `_blockscout_get(url)`: bila `BLOCKSCOUT_API_KEY`
  ada (env `BLOCKSCOUT_API_KEY`/`BLOCKSCOUT_PRO_API_KEY` →
  `blockscout_api_key` di `config.json` → `st.secrets`) → **PRO API**
  dengan path identik (`_pro_url`) dan header `Authorization: Bearer`
  (key tidak pernah di URL/log/pesan error); PRO 401/402/403/404 → jatuh
  ke instance publik. Tanpa key → publik: `curl_cffi` impersonate
  (`chrome → chrome136 → chrome131 → safari184 → safari17_0 → firefox133`,
  dirotasi saat 403, `_curl_requests()` bisa di-mock) lalu `requests`
  biasa + header browser.
- `BlockscoutBlocked` (403, atau 503 berbadan halaman challenge Cloudflare;
  detail `cf-mitigated`/`server`) **bukan transient**: tidak di-retry,
  `is_transient_error` → False, `is_blocked_error` baru. Response tanpa
  `status_code` numerik (stub test lama) diserahkan ke `raise_for_status`
  bawaan (`_status_of`).
- `fetch_holders()` merangkum 403 dari getToken/CSV/RPC/v2 menjadi **satu**
  kalimat (*"Blockscout publik menolak request (HTTP 403 bot-protection) di
  /api [cf-mitigated=challenge Cloudflare] — pasang BLOCKSCOUT_API_KEY (key
  gratis: https://dev.blockscout.com) agar scan lewat PRO API"*) + key baru
  `blocked: bool` (juga di early-return); bila PRO ikut gagal alasannya
  disambung (`…; PRO: PRO API 401 Invalid API key`). `fetch_holders_rpc`
  mengembalikan instance `BlockscoutBlocked` sebagai error ke-4.
- `source` sukses diberi akhiran rute: `blockscout-csv@pro` /
  `@public` (thread-local `_ROUTE_STATE`, aman untuk ThreadPool
  `scan_watchlist`); helper `source_with_route`, `source_base`,
  `route_label`, `last_route`. `analyze_token` meneruskan
  `holders["blocked"]` di samping `holders["fetch_error"]`.
- Shape dict hasil (`mint/symbol/market/snapshot/depth/source/…`) dan gate
  `holders_usable`/`fetch_error` tidak berubah; snapshot lama tetap tidak
  ditimpa saat 403.

## 2. UI & cron

- `app.py` `_scan_source_meta`: cocokkan jalur lewat `source_base()` dan
  tambahkan " · PRO API" / " · instance publik" ke help + caption.
  `scan_failed` dengan `snapshot["blocked"]` → pesan baru *"Blockscout
  publik menolak request scan (HTTP 403 bot-protection) — bukan karena CA
  salah. Pasang `BLOCKSCOUT_API_KEY` …"* (pesan lama "Pastikan CA valid"
  tetap untuk kegagalan non-403). Baris watchlist Robinhood: `blocked` →
  catatan ringkas "Blockscout 403 bot-protection — pasang
  BLOCKSCOUT_API_KEY (PRO API)".
- `pages/5_🧮_Holder.py`: peringatan "scan tidak lengkap" menyebut 403 +
  key bila `holders["blocked"]`.
- `scripts/scan_holders.py`: log lane Robinhood menambah `route=pro|public`
  dan `WARN: Blockscout publik menolak scan N/M token …` ke stderr.
- Workflow (`daily-effort-5menit.yml` + `.github/workflows/daily-effort.yml`)
  meneruskan `BLOCKSCOUT_API_KEY: ${{ secrets.BLOCKSCOUT_API_KEY }}`
  (secret perlu dibuat di GitHub; push ke `.github/workflows` mungkin ditolak
  untuk bot — salin manual seperti biasa). `config.example.json` +
  `blockscout_api_key`.

## 3. Tes & dokumen

- Baru `tests/test_robinhood_transport.py` (19 tes): key env/config/secrets,
  `_pro_url`, PRO Bearer tanpa key di URL, PRO 401/402 → publik, PRO+publik
  gagal → pesan gabungan tanpa bocor key, 403 → `BlockscoutBlocked` tanpa
  retry, rotasi profil TLS, header UA tidak menimpa impersonate, curl_cffi
  rusak → requests, 503 challenge, 429 masih di-retry, `fetch_holders`
  semua jalur 403 (dengan/tanpa decimals) → satu pesan + `blocked`,
  `analyze_token`/`scan_token_holders` meneruskan penanda, label rute.
  `tests/test_rh_card_ui.py` +3 AppTest (caption `@pro`, pesan 403 di Scan
  Holder Khusus, pesan lama untuk kegagalan biasa). **Suite penuh 952
  passed.**
- Dok: `docs/robinhood_holders_api.md` (bagian *Transport* + rate limit PRO;
  koreksi klaim lama "mirror PRO jangan dipakai"), README (paragraf Scan
  Holder Khusus + tabel env), DEPLOY (secrets + env Actions), AGENTS.md.

## Yang harus dilakukan user

1. Buat key gratis di <https://dev.blockscout.com> (Sign in → *Create API
   key*; key `proapi_…` hanya ditampilkan sekali).
2. Streamlit Cloud → *Settings → Secrets*: `BLOCKSCOUT_API_KEY = "proapi_…"`
   (atau `blockscout_api_key` di `config.json` lokal).
3. GitHub → *Settings → Secrets and variables → Actions*: secret
   `BLOCKSCOUT_API_KEY`, lalu pastikan `.github/workflows/daily-effort.yml`
   memuat baris env baru (lihat `daily-effort-5menit.yml`).
4. Ulangi scan `0x1209ec…bb6e`: caption harus berbunyi *Blockscout
   (Robinhood Chain) · PRO API*.

Belum dikerjakan (opsional, bila PRO API pun tidak memadai): fallback
on-chain lewat RPC publik `https://rpc.mainnet.chain.robinhood.com`
(`eth_getLogs` Transfer + `balanceOf`; rate-limited, "bukan untuk indexer")
dan Bitquery (berbayar).

# Kegiatan — 8 September 2026 (sesi 9 · 🛰 Scan Holder Khusus: + Robinhood Chain)

Permintaan user: **"tambahkan fungsi kita bisa scan robinhood disini juga"**
(section **🛰 Scan Holder Khusus — Helius** di halaman utama).

## 1. Backend: `robinhood_holders.scan_token_holders()`

Padanan EVM dari `helius_holders.scan_token_holders` — alurnya sama:
market (harga & marketcap) dari DexScreener (`chain_id=robinhood`), token
info (decimals & supply) dari Blockscout, seluruh holder dari
`fetch_holders` (GMGN primary, Blockscout fallback), lalu
`solscan_holders.wallet_depth`. **Shape dict hasilnya sama persis**
(`mint/symbol/market/snapshot/depth/source/no_helius_keys/scan_failed`)
supaya UI dipakai ulang tanpa cabang. Pool AMM (`pair_addresses`
DexScreener + penanda non-wallet GMGN) ditandai `_mark_pools` lalu
default **disingkirkan dari bucket** (`include_pools=False`) — sama
dengan perilaku jalur Helius. `no_helius_keys` selalu `False` (jalur ini
tidak butuh key Helius).

## 2. UI `app.py` (`_render_helius_holder_scan` / `_render_helius_holder_result`)

- Judul section: **🛰 Scan Holder Khusus — Helius / Robinhood**; caption +
  placeholder form menjelaskan kedua chain (base58 Solana / `0x…`
  Robinhood).
- Validasi CA menerima **dua format**: base58 (Solana) ATAU `0x` + 40 hex
  (Robinhood) — pesan error menyebut keduanya. CA EVM di-normalize
  (lowercase) sebelum scan.
- Dispatch per chain: `0x…` → `robinhood_holders.scan_token_holders`
  (status "Mengambil holder dari GMGN/Blockscout (Robinhood Chain)…"),
  base58 → `scan_token_holders` Helius (perilaku lama).
- Helper baru `app._scan_source_meta(result)`: label metrik "Akun holder
  (…)", help, dan caption "Sumber holder: …" dihitung dari
  `result["source"]` — `gmgn+robinhood*` → **GMGN (Robinhood Chain)**;
  ada `blockscout` (GMGN gagal, Blockscout yang pulang) →
  **Blockscout (Robinhood Chain)**; selain itu → **Helius DAS**
  (perilaku lama). Pesan error `scan_failed` hanya menyebut "Helius API
  key aktif" untuk jalur Helius.
- Input CA diberi key `helius-ca-input` (konvensi `lp-ca-input`/
  `add-token-input`) supaya bisa ditarget test.

## Verifikasi

- `tests/test_robinhood_watchlist.py::ScanTokenHoldersTest`: shape hasil
  identik jalur Helius; pool keluar dari bucket default / masuk saat
  `include_pools=True`; `max_wallets/price_usd/decimals/total_supply`
  diteruskan; tanpa harga → `scan_failed` + `fetch_token_info` tidak
  dipanggil; GMGN+Blockscout gagal → `scan_failed` + alasan provider
  tersimpan.
- `tests/test_rh_card_ui.py::HolderKhususRobinhoodScanTest` (AppTest):
  CA `0x…` (mixed case) → `robinhood_holders.scan_token_holders` dengan
  CA lowercase + `max_wallets=100_000`, hasil dirender "Akun holder
  (GMGN)" + caption "GMGN (Robinhood Chain)" + tautan rh-scan/Blockscout;
  source fallback → label "Akun holder (Blockscout)"; CA base58 tetap →
  `helius_holders.scan_token_holders` + label "Akun holder (Helius)";
  `0x123` → ditolak tanpa scan.
- Suite penuh: 916 passed (termasuk test Helius lama — jalur Solana
  tidak berubah).

---

# Kegiatan — 7 September 2026 (sesi 8 · 🌊 Scan Meteora: hanya dust ≤ 0,1% + BEST POOL TVL ≥ 10K)

Permintaan user: **"jangan tampilkan yang dust sudah > 0,1%, jadi sesi
deteksi dan notifikasi aman, hati-hati, bahaya sudah tidak diperlukan lagi,
bisa dinonaktifkan. Lalu best pool kriterianya dari kriteria kita tambah
minimum TVL adalah 10K."**

## 1. Filter listing: `hide` = dust > 0,1% MC (`holder_history.py`)

- Konstanta baru `DUST_SCAN_HIDE_PCT = DUST_BEST_PCT` (0,1). `dust_flag()`
  kini mengisi `hide = pct > DUST_SCAN_HIDE_PCT` untuk semua level — dulu
  hanya BAHAYA (≥ 1%) yang `hide`. `should_hide_dust()` (dipakai
  `meteora_screener.hide_dust_limit`) otomatis ikut. Boundary strict `>`:
  tepat 0,1% masih tampil (tapi bukan BEST POOL karena butuh `<`), dust
  `None` (holder gagal) tetap tampil tanpa angka.
- **Level/label AMAN/HATI-HATI/BAHAYA tidak dihapus** dari `dust_flag` —
  Chart LP Meteora, Robinhood LP, cron dan alert masih memakainya. Yang
  dinonaktifkan hanya *tampilannya* di listing Scan Meteora.
- `DUST_LIMIT_PCT` (alias lama) sekarang menunjuk `DUST_SCAN_HIDE_PCT`.

## 2. BEST POOL + minimum TVL 10K

- `DUST_BEST_MIN_TVL_USD = 10_000.0` + guard `_tvl_valid_for_best()`.
  `dust_flag(..., holders=..., tvl=...)` → `best` True hanya bila dust
  < 0,1% **dan** holder valid (≥ 40 wallet) **dan** TVL ≥ 10K. `tvl=None`
  → bukan best (sama seperti `holders=None`), jadi Chart LP / watchlist yang
  tidak mengirim TVL tidak berubah perilaku.
- Sumber TVL = field `tvl` pool dari API Meteora (sudah ada di baris hasil
  `_row_from_pool`).

## 3. UI `app.py` (`_render_meteora_scan`)

- Baris listing **tidak lagi** merender `_dust_badge_html` (chip
  AMAN/HATI-HATI/BAHAYA); hanya angka dust % MC + chip 🏆 BEST POOL.
- Kolom baru **TVL** di antara MC dan Dust (`col_spec` 8 kolom).
- Caption + ringkasan "N disembunyikan (dust > 0,1% MC)" + hero text
  disesuaikan; `scan_meteora()` menambah `hide_pct` di hasil.

## Verifikasi

- `tests/test_holder_history.py`: boundary hide 0,1 (strict), guard TVL
  (None / "abc" / 9 999,99 → bukan best; 10 000 / "12000" → best).
- `tests/test_meteora_screener.py`: 2,4% / 0,5% / 0,2% disembunyikan,
  `None` / 0,1 / 0,03 tetap; `analysis.holders.dust_pct_mc` menang atas
  `row.dust_pct_mc`; `hide_pct` di hasil scan.
- `tests/test_lp_card_ui.py::MeteoraBestBadgeTest`: 3 baris (CLN TVL 25K →
  BEST; BGS holder 0 → bukan; THN TVL 4K → bukan), kolom TVL dirender,
  tidak ada chip level di listing.
- Suite penuh: 867 passed (1 test `StandalonePageTest` pre-pump gagal
  karena sandbox tanpa akses jaringan — sudah gagal di `main`, tidak
  terkait).

---

# Kegiatan — 6 September 2026 (sesi 7 · 🗑️ Hapus semua watchlist biasa)

Permintaan user: **"tambahkan tombol delete all watchlist di watchlist biasa
selain meteora dan robinhood."**

## 1. Backend: `watchlist.remove_many_from_watchlist()`

Hapus satu token (`remove_from_watchlist`) memakai satu journal write + satu
commit per klik ✕; mengosongkan 79 token biasa dengan cara itu berarti 79
commit (worker sudah men-*coalesce*, tetapi journal tetap ditulis 79×). Fungsi
baru menerima **daftar CA** dan memakai kontrak durabilitas yang sama, hanya
di-batch:

- `_load_and_merge(local_first=background)` → hitung yang benar-benar ada;
- **journal dulu** lewat `_journal_many` (satu tulis atomik; last-op-wins per
  CA membatalkan `add` yang masih tertunda);
- `save_watchlist(..., background=True)` = tulis lokal + seed cache + **satu**
  commit di thread latar (`remove N token (watchlist biasa)`).

Fungsi **tidak menyaring `source`** — pemanggil yang menentukan scope, sama
seperti `remove_from_watchlist`. Op `remove` untuk CA yang tidak ada di state
lokal tetap di-journal supaya remote yang lebih baru ikut bersih
(`_op_is_applied` mem-prune bila memang sudah tidak ada). Return
`{removed, missing, saved, addresses}`.

## 2. UI (`app.py`): tombol popover di kepala card watchlist biasa

Di sebelah selectbox "Urutkan baris watchlist" (kolom ketiga,
`vertical_alignment="bottom"`): **🗑️ Hapus semua** → popover berisi teks
"Hapus **N token** dari watchlist biasa?" + tombol primary **Ya, hapus N
token** (`key="clear-regular-watchlist"`). Klik → `remove_many_from_watchlist(
list(holder_watch), note="watchlist biasa", background=True)` → laporan
`st.success` setelah rerun (lewat `st.session_state["watchlist_clear_report"]`).

Scope = `holder_watch` hasil `split_watchlist` (token Solana non-LP). Card
**Chart LP Meteora** dan kedua card **Robinhood** SENGAJA tidak ikut — mereka
punya file/watchlist sendiri dan tidak diberi tombol serupa. Teks konfirmasi
menyebut bahwa token `degen` (Pre-Pump Screener) ikut terhapus, dan bahwa
history holder tidak dihapus (`snapshot_status` membuang kunci di luar
watchlist pada publish berikutnya). Tombol tidak dirender bila card kosong.

## Verifikasi

- `python -m pytest -q` → **850 hijau** (sebelumnya 836; +14 test baru di
  `tests/test_watchlist_clear.py`).
- Backend: hanya CA yang diminta yang dihapus (token `meteora` di file
  tetap), satu `_save_pending` untuk seluruh batch, nol pull di jalur klik,
  tepat satu `_github_push`, jurnal dibersihkan setelah commit sukses dan
  dipertahankan saat gagal (token tidak muncul lagi di `load_watchlist`),
  duplikat/kosong diabaikan, daftar kosong tidak menulis apa pun, `remove`
  membatalkan `add` tertunda, jalur sinkron (`background=False`) tetap ada.
- AppTest: tombol menyebut "2 token" (LP tidak dihitung), klik konfirmasi
  memanggil `remove_many_from_watchlist` dengan CA non-LP saja +
  `background=True`, laporan sukses tampil, tombol tidak ada bila watchlist
  hanya berisi token LP, tombol ✕ per baris tetap ada.

# Kegiatan — 6 September 2026 (sesi 6 · ✕ watchlist bolak balik + flush latar)

Permintaan user: **"fungsi hapus dari watchlist masih bolak balik dan tidak
optimal."**

## 1. Akar "bolak balik": jurnal remove di-prune prematur terhadap cache optimis

Reproduksi: token dihapus (✕) tapi **muncul lagi** di render berikutnya setelah
push GitHub gagal. Penyebab ada di `watchlist._load_and_merge`: ia mem-prune
jurnal pending terhadap `raw` yang (dalam TTL 60 dtk) berasal dari **cache
seed** hasil perubahan lokal — state **optimis**, belum tentu sudah sampai ke
GitHub. Kalau push latar belakang gagal, jurnal `remove` sudah di-prune,
sehingga begitu cache kedaluwarsa dan `load_watchlist()` menarik ulang remote
yang *masih memuat* token itu, tidak ada lagi op `remove` yang mengoreksi →
token muncul lagi (dan setiap render ulang mem-flush sinkron yang membekukan UI
selama push gagal). Ini juga berlaku untuk `add`/`source` (sekali saja push
gagal, perubahan "hilang" lalu timbul kembali).

**Perbaikan (`watchlist.py`):**

- Cache `_REMOTE_CACHE` kini menyimpan penanda **`settled`**: `True` bila isi
  **mencerminkan repo** (hasil `_github_pull` atau `_github_push` yang sukses),
  `False` bila isi **optimis** (seed `_seed_remote_cache` setelah perubahan
  lokal). Helper baru `_set_remote_cache(repo_path, data, settled)`.
- `_load_and_merge` (dan `_push_worker`) **hanya mem-prune jurnal terhadap
  state `settled=True`**; terhadap seed optimis atau file lokal, jurnal
  dipertahankan. Jadi `remove` yang belum ter-commit aman dikoreksi ulang saat
  remote ditarik.
- `_push_worker` mem-prune terhadap `wl` yang **benar-benar di-commit** (bukan
  cache yang bisa saja di-seed ulang mutation lain saat push jalan).

## 2. "Tidak optimal": flush `load_watchlist` jadi latar belakang

Dulu `load_watchlist()` yang menemukan sisa jurnal (mis. push gagal) langsung
`_github_push` **sinkron** — setiap render ulang memblokir sampai ±2 menit saat
API lambat. Sekarang diserahkan ke `_queue_github_push` (fire-and-forget):
UI tidak menunggu, jurnal dibersihkan worker setelah commit sukses, dan
`push_inflight` tetap menahan flush dobel saat worker masih jalan.

## Verifikasi

- `python -m pytest -q` → **830 hijau** dan `python -m unittest discover -s
  tests -t .` → **830 OK** (sebelumnya 829).
- Test baru `RemoveBackgroundTest::test_remove_tidak_muncul_lagi_saat_push_belum_berhasil`:
  push selalu gagal (remote masih memuat CA), lalu `load_watchlist` memakai seed
  cache dan `force_refresh` menarik remote lama → CA tetap hilang karena jurnal
  remove dipertahankan.

# Kegiatan — 6 September 2026 (sesi 5 · Chart LP Meteora ikut 5 menit)

Permintaan user: **"iya untuk watchlist meteora juga, per 5 menit, biar
perubahan holder bisa langsung ketahuan."** Ini **membatalkan** keputusan sesi 4
yang sengaja menahan lane Solana di slot ±15 menit demi anggaran Helius —
readernya: laju 5 menit sekarang berlaku untuk KEDUA card LP, dan penghematan
Helius menjadi knob opsional, bukan default kode.

## 1. Lane Meteora = tiap run (satu knob, bukan dua jam dinding)

Sebelum sesi ini ada dua gerbang di `scripts/scan_holders.py`
(`RH_FAST_SCAN_INTERVAL_SEC` 5 menit untuk Robinhood, `METEORA_LP_SCAN_INTERVAL_SEC`
15 menit untuk Solana). Sekarang keduanya menempel satu jam dinding run:

```
RUN_SCAN_INTERVAL_SEC = RH_FAST_SCAN_INTERVAL_SEC = FAST_SCAN_INTERVAL_SEC = 300
LP_SCAN_RUN_MULTIPLIER = int(env, default 1)          # katup hemat, opsional
lp_slot_sec() = RUN_SCAN_INTERVAL_SEC * MULTIPLIER    # slot LP = slot run
```

`lp_slot_due(now, snapshot.updated_at)` tetap ada dan tetap berbasis **nomor
slot** (bukan umur titik): dengan multiplier 1 setiap cron run = slot LP baru,
jadi Helius ditarik tiap 5 menit; yang tidak due hanyalah run KEDUA dalam satu
slot (chain dispatch menabrak schedule) — persis yang diinginkan. Gate lama
berbasis umur titik tidak dipakai lagi sejak sesi 2 karena publish yang gagal
membuat token tidak pernah terkejar.

Bila kuota Helius mulai menipis, tidak perlu sentuh kode: env
`LP_SCAN_RUN_MULTIPLIER: "3"` di langkah "Holder scan" pada workflow → lane
Solana kembali ±15 menit, Robinhood LP tetap tiap run. Log run selalu
menyebutkan kadens aktif: `Rencana scan: LP=… biasa=… due=… slot_lp=… (LP ±5
menit · tiap run · biasa ±4 jam)`.

## 2. Konsekuensi yang harus ikut digerakkan: `MAX_POINTS`

Densitas titik riwayat = kadens run. `ingest_point` **menimpa** titik yang lebih
muda dari `MIN_POINT_GAP_SEC`, jadi tidak ada cara "scan 5 menit tapi simpan
tiap 15 menit" dengan mekanisme itu (titik terakhir selalu berjarak 5 menit →
satu-satunya titik yang pernah ada). Satu-satunya knob panjang grafik =
`holder_history.MAX_POINTS`:

| | densitas | batas | jendela | bucket 4 jam |
| --- | --- | --- | --- | --- |
| lama (sesi 2–4) | 15 menit | 336 | 3,5 hari | 21 |
| 5 menit, batas lama | 5 menit | 336 | **28 jam** | **7** |
| sekarang | 5 menit | **1008** | 3,5 hari | 21 |

Tanpa kenaikan itu "Grafik 4 jam" di card LP menyusut 3× persis saat datanya
paling rapat. Ukuran tetap aman: snapshot dashboard selalu
`compact_history_for_status` (≤ 84 bucket `resample_4h`) dan sparkline
meresample internal, jadi payload HTML tidak berubah; simulasi store sintetis
(10 token LP @ 1008 titik 5 menit + 45 token biasa @ 336 titik/hari) =
**0,33 MB gz** vs 0,25 MB sebelum perubahan, di bawah `MAX_BACKUP_BYTES`
3,5 MB. `MIN_POINT_GAP_SEC` (4 menit) dan `MIN_RUN_GAP_SEC` (4 menit) tetap
**— harus di bawah 5 menit**, itu yang dikunci
`ScanCadenceTest::test_konstanta_kadens`.

## 3. Teks yang ikut disinkronkan

Caption/penjelasan kadens di `app.py` (kepala card Chart LP & Robinhood,
helper tab, komentar router), `pages/5_🧮_Holder.py`, komentar
`watchlist_detail.py` (ambang basi tetap 20 menit — sengaja jauh di atas
kadens supaya hanya cron mati yang kena), `robinhood_watchlist.py`,
`holder_status.py`, dan `telegram_alerts.py`. Yang SENGAJA tidak berubah:
bucket pengingat ⚡ (`FAST_BUCKET_SEC` 15 menit/token) — kalau ikut dipercepat,
satu token menerima 3 pesan identik per 15 menit; data dashboard sendiri tetap
diperbarui tiap run.

## 4. Workflow (satu-satunya langkah manual)

Berkas workflow tidak bisa ditulis bot (GitHub menolak push/PUT ke
`.github/workflows/*`, 403). Kadens cron **tidak perlu diubah lagi** untuk sesi
ini — `*/5` + chain `WAIT=$((300 - NOW % 300 + 20))` sudah ada di
`daily-effort-5menit.yml`; yang berubah hanya nama langkah + catatan env
opsional. Terukur dari `holder-live`: commit masih berjarak 15 menit (01:00,
01:15, 01:30, … UTC) → berkas itu belum ditempel. Setelah ditempel, bukti
kadens nyata = baris `Rencana scan: … (LP ±5 menit · tiap run …)` dan commit
`holder-status: snapshot …` tiap 5 menit. Konsekuensi: ±576 commit/hari di
branch `holder-live` (repo terukur ±56 MB pada kadens 15 menit).

## Verifikasi

- `python -m pytest -q` dan `python -m unittest discover -s tests -t .` — lihat
  angka di PR; yang relevan: `ScanCadenceTest` (kadens + `main()` integration
  dengan jam tersumbat), `ScanDensityCalibrationTest` (kalibrasi `MAX_POINTS`,
  21 bucket 4 jam, lane biasa), `FiveMinuteCadenceTest`,
  `test_watchlist_background_push`, `test_rh_card_ui`.
- Uji baru yang spesifik menahan permintaan sesi ini:
  `test_run_biasa_scan_kedua_lane_lp` (tiap run = Meteora **dan** Robinhood),
  `test_multiplier_menahan_solana_tetapi_tidak_robinhood` (katup hemat bekerja),
  `test_lp_slot_due_default_setiap_run`.

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

> Baris Chart LP pada tabel ini **sudah digantikan sesi 5** (lihat di atas):
> sejak itu lane Meteora ikut tiap run, dan `lp_slot_due` hanya mengikat kalau
> `LP_SCAN_RUN_MULTIPLIER` > 1.
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
  Meteora tetap tertulis ±15 menit *(kalimat ini berlaku sampai sesi 5; kini
  kedua lane LP tertulis ±5 menit di semua caption)*.

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
