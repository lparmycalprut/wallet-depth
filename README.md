# Wallet Depth — Holder Analytic (Dust)

Wallet Depth memantau token Solana dan berfokus pada **analisa holder
dust** sebagai jejak dump, plus **Scan Meteora DLMM**. Cron holder dapat
mengirim alert Telegram khusus perubahan dust; sinyal lama seperti silent
accumulation 12 jam dan reversal tetap tidak digunakan.

## Halaman

- **Halaman utama** (`app.py`): paling atas **🚨 header "STOP DEGEN, GAK BISA"**
  (2026-09-17 — *"merah menyala berkedip, tulisan besar, ada emoticon warning"*;
  tulisannya tetap **BIRU royal** sesuai permintaan *"ganti tulisan warna
  warning kita menjadi warna biru, efek tetap"*, sedangkan permintaan terbaru
  *"background nya ganti warna merah, tulisan tetap biru"* membuat panelnya
  **merah gelap** tanpa mengubah animasi kelip + glow)
  `dashboard_components.render_degen_stop_header()`, gaya + animasi di
  `render_styles()`), lalu **🏆 Scan Best Pool Meteora** (**full-width**
  sejak 2026-09-11 — "jangan dibuat grid lagi"; sejak 2026-09-16 **satu tombol
  deteksi 24H saja** dengan satu tabel), lalu paling bawah **🧾 Log Aktivitas**.
  Detail karakteristik tiap card/section bukan caption panjang lagi — jadi
  **tooltip** yang muncul saat kursor digeser ke teks judulnya (sejak
  2026-09-10), jadi badan card hanya berisi rekap angka hasil scan.
- **📦 TEMP** (`pages/6_📦_TEMP.py` + `temp_ui.py`, sejak 2026-09-16):
  penampungan card yang dicabut dari halaman utama — **🌊 Watchlist Meteora**
  (dulu "Chart LP", ±auto-refresh 60 detik) dan **🛰 Scan Holder Solana**.
  Permintaan user: *"🌊 Watchlist Meteora pindah ke page baru TEMP"* + *"🛰 Scan
  Holder Solana pindah ke page baru TEMP"*. Isi `app.py` tinggal
  `render_best_pool_scan()` + log, dan **🏆 Scan Best Pool tidak ikut pindah**.
  Nomor 6 dipakai lagi setelah halaman Robinhood dihapus (lihat bullet
  berikutnya); `page_router` memantulkan `?page=temp` / `?page=6` /
  `?page=6_📦_temp` ke halaman ini.
- **Holder Analytic** (`pages/5_🧮_Holder.py`): analisa detail satu token dan
  scan FULL/kronologi.
- Halaman **🦅 Robinhood** dan **temp** (📦) **dihapus total 2026-09-15** atas
  permintaan user — bersama seluruh fungsinya: watchlist Robinhood
  (`watchlist_robinhood.json`, snapshot & history-nya), card 🦅 Watchlist
  Robinhood LP/biasa, 🦅 Scan Best Pool Krystal, 🦅 Scan Best Robinhood Coin,
  🌊 Scan Meteora Pool, 📋 Watchlist Analisa Holder (Dust), 🔍 Temukan Token
  (Trending/Degen), lane Robinhood di cron, dan transport Blockscout. App kini
  **Solana saja**. Nomor 6 dihidupkan kembali 2026-09-16 sebagai **📦 TEMP** —
  isinya bukan fungsi Robinhood lama, hanya kedua card yang dicabut dari
  halaman utama (tes `test_pre_pump_screener.test_pre_pump_page_file_is_gone`
  mem-pin isi `pages/`: `5_🧮_Holder.py` + `6_📦_TEMP.py`).

## Konsep

1. **Dust holder** — wallet murni dengan `0 < nilai ≤ $10`:
   - **dust % MC** = total nilai dust / marketcap × 100 — **satu sumber angka
     di semua kartu**: MC dan harga dari DexScreener (yang baru di-fetch),
     bukan MC listing Meteora/Blockscout (2026-09-13; itu hanya cadangan bila
     DexScreener tidak membalas),
   - **tanpa bukti holder = tanpa angka**: scan yang gagal / 0 wallet /
     terpotong / sampel < 40 wallet menampilkan `—` (bukan `0,00%`),
     `holder_history.holders_usable` satu-satunya gerbangnya,
   - ≥ **0,5% MC** → **HATI-HATI** (badge kuning, peringatan dini — Chart LP
     / watchlist),
   - ≥ **1% MC** → **BAHAYA** (Chart LP / watchlist),
   - **Scan Meteora** (sejak 2026-09-07): hanya pool dengan dust **≤ 0,1% MC**
     yang ditampilkan (`DUST_SCAN_HIDE_PCT`); dust > 0,1% disembunyikan
     seluruhnya, sehingga badge AMAN/HATI-HATI/BAHAYA **dinonaktifkan** di
     listing itu,
   - < **0,1% MC** + data holder valid (≥ 40 wallet) + **TVL pool ≥ 10K USD**
     (`DUST_BEST_MIN_TVL_USD`) → badge **🏆 BEST POOL** di baris listing Scan
     Meteora. Nilai **== 0,1%** sengaja tidak dapat badge (butuh `< 0,1%`).
     Notifikasi Watchlist Meteora tidak membaca angka ini: alert pool memakai
     quotient fee/active TVL terhadap volatility. Rule dust ⚡ EARLY DUMP hanya
     berlaku pada lane non-Meteora yang masih menggunakan alert holder lama.
   Dust yang nambah pesat = holder sebelumnya sudah distribusi / bag
   merosot jadi sisa. **Catatan:** batas dust itu **$10 per wallet dalam
   USD**, jadi dust % MC *tidak* invariant terhadap harga — harga naik
   membuat wallet "lulus" ke >$10 (dust % MC turun walau tidak ada yang
   jual), harga turun mendorong wallet masuk dust (dust % MC naik). Baca
   angka ini bersama jumlah dust wallet.
2. **Watchlist Meteora (Chart LP) — watchlist terpisah** — token/pool yang
   ditambahkan dari **Scan Meteora Pool** (⭐) atau form manual dikumpulkan di
   card kiri atas dashboard. Row menyimpan dan menampilkan source/timeframe
   (`24h`/`30m`), `fee_active_tvl_ratio`, `volatility`, quotient metrik, dan
   klasifikasinya. Baseline metrik dipasang ketika pool masuk watchlist.
   Watchlist **24h** memberi alert bila quotient fee/volatility turun minimal
   30% dari baseline; watchlist **30m** memberi alert bila snapshot baru
   memiliki `volatility > fee_active_tvl_ratio`. Dust holder/grafik 5 menit
   tetap dicatat untuk data LP, tetapi bukan lagi rule notifikasi Meteora.
   Tombol 🔔/🔕 tetap mengatur pengiriman alert metrik. Token LP tidak
   ditampilkan dua kali di watchlist holder biasa.
3. **Kohort mid-tier (Crab+Fish, $100–$10k)** — daftar address di-freeze
   4 jam, lalu diukur **sisa token** (bukan dollar) supaya dump harga
   tidak ketiru sebagai exit.
4. **Grafik** — setiap scan mencatat titik ke `holder_history.json`.
   Lane LP (Chart LP Meteora) digambar per bucket **5 menit**
   (`resample_5m`, `LP_INTERVAL_SEC`); halaman Holder tetap per bucket 4 jam
   (`resample_4h`).
5. **Wallet Depth by Threshold** — Helius DAS `getTokenAccounts`, bucket
   `>$0-$10` … `>$500k` atas wallet murni (LP/pool DexScreener disingkirkan).
   Tier 🦐/🦀/🐟/🐬/🦈 selalu wallet murni.
6. **Kronologi Holder (scan FULL)** — snapshot awal disimpan sekali dan
   tidak ditimpa. Scan FULL berikutnya membandingkan **balance token**
   (bukan hanya nilai USD) untuk melihat wallet dust yang membesar, turun
   kategori, baru teramati, atau saldo menjadi nol. Kenaikan harga tanpa
   kenaikan balance tidak dianggap pembelian. Perubahan saldo tidak dapat
   membedakan swap dengan transfer — tautan Solscan disediakan untuk
   verifikasi. Payload wallet dibatasi (sampel deterministik); hasil
   sampled/truncated tidak disebut daftar lengkap. Kronologi baru muncul
   setelah scan FULL kedua.
7. **Alert Telegram** — Watchlist Meteora memakai metrik pool, bukan
   notifikasi dust holder: 24h memantau penurunan quotient
   `fee_active_tvl_ratio / volatility` ≥ 30% dari baseline, sedangkan 30m
   mendeteksi `volatility > fee_active_tvl_ratio`. Snapshot dan status metric
   dipakai bersama oleh cron dan scan manual. Rule **EARLY DUMP** berbasis
   dust (`telegram_alerts.process_holder_alerts`) tidak lagi punya pemanggil
   sejak card watchlist Robinhood/biasa dan lane cron-nya dihapus
   (2026-09-15).

## Konteks pasar di pesan (info, bukan gerbang)

Gerbang konfirmasi volume **sudah dihapus** bersama rule-rule lama
(2026-09-11): notifikasi ⚡ tidak menunggu bukti volume lagi — dust yang naik
≥ 0,02% dari patokan watchlist langsung diberitahu. Yang tersisa adalah
**baris pelengkap** di pesan, dibuat dari konteks pasar yang sama:

- `alert_context.build_market_context` menyusun volume 4 jam, rata-rata
  volume **per window 4 jam** selama 7 hari (`avg_volume_7d`, supaya
  satuannya setara dengan `volume_4h` — bukan total harian), perubahan harga,
  buy/sell pressure, dan metrik volatilitas;
- sumber berurutan: candle hourly **GeckoTerminal** (168 jam) → angka
  DexScreener yang **sudah** diambil scan (`volume.h6` di-skala ke 4 jam,
  baseline `volume.h24`, `priceChange.h6`, `txns`) → `daily_effort.json`;
- ditarik **lazy**: provider hanya dipanggil saat notifikasi benar-benar akan
  dikirim, maksimal satu kali per token per run, jadi scan yang tenang tidak
  menambah request apa pun. Kegagalan provider = baris `📈 Pasar` tidak
  dicetak; **dilarang mengarang angka**;
- konteks yang sama ditulis `holder_status.snapshot_status` ke
  `tokens[mint].market_signal` (dipakai untuk pemeriksaan cepat kondisi pasar
  per token di snapshot).

**Metrik volatilitas** — `holder_history.calculate_volatility_metrics`
memakai 16 candle hourly terakhir dan menghasilkan `price_stddev_4h` (sample
stddev close per jam, dalam % harga rata-rata), `price_range_4h`
((high−low)/rata-rata), `intra_hour_volatility` + `intra_hour_volatility_max`
(rentang dalam tiap jam), `price_change_4h_pct`, `volume_4h`, `missing_hours`
(candle bolong), dan `stale`.

## Format alert Telegram (contoh)

Semua notifikasi, termasuk test koneksi, memakai emoji dan detail pendek.
Angka `pp` berarti **poin persentase**, bukan perubahan relatif %.
Preview tautan dimatikan agar pesan tidak dipenuhi kartu pratinjau.

Judul **⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE** — persis satu baris itu —
ditampilkan **tebal** (entity `bold`; offset/length dihitung dalam UTF-16
karena emoji bisa dua unit) dan dipisahkan baris kosong dari detail. Telegram
Bot API tidak mendukung ukuran font khusus, warna merah, atau teks berkedip,
jadi penekanan memakai **tebal + ⚡**, bukan HTML/CSS yang tidak didukung.
Format ini sama untuk semua notifikasi (Watchlist Meteora memakai metrik
pool; judul ⚡ dipakai rule dust).

```text
⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE

🪙 $LPX
📊 Dust: 0.012% → 0.036% MC (+0.024 pp · langkah 1× 0.02%)
⏱️ 10 menit sejak masuk watchlist
📈 Pasar: vol 4j 3.73× avg 7d · harga -6.00%
🕒 2026-09-13 08:20 WIB
📋 Mint: LpMint11111111111111111111111111111111111
🔗 GMGN
🦆 DexScreener
```

Baris `🔗 GMGN` / `🦆 DexScreener` (dan `🌊 Meteora` / `🦅 HawkFi` bila pool
diketahui) adalah
**hyperlink** — labelnya diberi entity `text_link` Bot API, URL-nya tidak
ditulis di teks (sejak 2026-09-09; sebelumnya URL polos 44+ karakter
membuat pesan panjang).

Token yang belum punya patokan waktu (mis. patokan dari scan pertama tanpa
tanggal `added`) tidak menampilkan baris `⏱️`; baris `📊` tetap menulis
patokan → angka sekarang. Baris `📈 Pasar` hilang sendiri bila konteks pasar
tidak tersedia
(tanpa tanda "TIDAK TERVERIFIKASI" — gerbangnya sudah dihapus, jadi tidak ada
lagi yang perlu dimaafkan).

URL hyperlink dibangun `links.token_links(mint)` (satu sumber dengan tabel
watchlist dan `token_link_lines()` versi teks polos untuk log/CLI) dan
selalu ter-encode. Bila mint kosong, link dilewati. Bila event LP membawa pool address Meteora, ditambahkan
**🌊 Meteora + 🦅 HawkFi**; cron belum menyimpan pool address.

Transport tetap mengirim teks literal (tanpa `parse_mode`), sehingga nama
token dengan karakter HTML/Markdown tidak merusak pesan. Judul exit diberi
native entity `bold` dan setiap label link diberi entity `text_link`,
keduanya dengan offset/panjang **UTF-16** (emoji 🚨 / 🔗 = dua unit).

## Sumber data

**Helius** = sumber utama holder (DAS `getTokenAccounts`). **GMGN** hanya
listing Trending/Degen + fallback. **Meteora** pool-discovery API untuk
Scan Meteora + 🏆 Best Pool. **rugchecker.cc** (`/api/honeypot/checker`, publik
tanpa key) = kolom **RugCheck** 🏆 Best Pool — see **🧿 RugCheck**. Harga/MC/volume/`txns` dari DexScreener. Candle hourly & harian
(volume + volatilitas) dari GeckoTerminal. Solscan dilepas.

| `holder_source` | Perilaku |
|---|---|
| `auto` (default) | Helius dulu → fallback GMGN. |
| `helius` | Paksa Helius → fallback GMGN. |
| `gmgn` | GMGN saja (listing Trending/Degen), fallback Helius. |

**Sisa kredit Helius** ikut ditampilkan di panel **🧾 Log Aktivitas**
(sejak 2026-09-10, `core.helius_usage_summary()`): metadata key dibaca dari
`GET https://api.helius.xyz/v0/keys` (fallback host RPC), cache 5 menit
(`HELIUS_USAGE_TTL_SEC`) dan di-refresh di **thread latar** sehingga render
halaman tidak pernah menunggu jaringan. Bentuk respons antar plan berbeda —
`credits` objek `{total, used, available}`, angka tunggal, atau field datar
`creditsRemaining` — dan semuanya diterima; kalau Helius tidak mengirim angka
kredit (plan tertentu), barisnya menyebut "Helius tidak mengirim angka kredit
untuk plan ini" + berapa request yang app ini kirim (hitungan lokal), bukan
mengarang angka. Key ditolak (401/403) atau kredit habis → entri `action`
(merah bold). Kill-switch suite tes: `HELIUS_USAGE_PROBE=0`.

Scan Holder Solana (**📦 TEMP** sejak 2026-09-16, sebelum itu halaman utama;
dulu "Scan Holder Khusus") menerima CA
Solana (base58) → Helius DAS, lalu menampilkan bar chart Wallet Depth + tabel.
Jalur ini dan cron butuh `HELIUS_API_KEY` (config / env / Streamlit secrets);
tanpa key dipakai fallback GMGN.

Metrik hasil scan (2026-09-12): **Dust %MC** di kiri **Akun holder (…)**,
lalu Bucket > $0, Wallet murni (tier), dan Marketcap — semua persen %MC 3
desimal (metrik, label batang chart, kolom % Market Cap tabel), dan Dust
%MC memakai definisi kolom **Hold %MC** watchlist (wallet `0 < nilai ≤ $10`,
LP/pool disingkirkan). Bila **Dust %MC ≤ 0,035%**
(`meteora_screener.BEST_DUST_MARK_PCT`, inklusif — ambang yang sama dengan
tanda 🏆 BEST POOL di card **🏆 Scan Best Pool Meteora**), di bawah metrik
itu muncul tulisan **BEST** agak besar berwarna **emas (GOLD)** dengan efek
**kelap-kelip** (`dashboard_components._scan_best_badge_html` + CSS
`.scan-best-gold` / `@keyframes scan-best-blink`, hormati
`prefers-reduced-motion`). Penanda **visual** saja: tidak ada angka/saringan
yang berubah, dan dust yang gagal diambil (`None`) tidak pernah ditandai.
Nama class-nya sengaja bukan varian `dust-best` karena pin regression card
Scan Meteora menghitung kemunculan string class chip emas itu di body
halaman. Rule-nya dijelaskan di **tooltip judul section**
(`temp_ui.scan_holder_tooltip()`, dulu di `app.py`), bukan caption.

## 🌊 Watchlist Meteora (watchlist pool terpisah — di halaman 📦 TEMP)

Card ini **pindah ke halaman 📦 TEMP 2026-09-16** (permintaan user: *"🌊
Watchlist Meteora pindah ke page baru TEMP"*); logikanya tinggal di
`temp_ui.py`, datanya tetap store lama (`watchlist.json`, `holder_status.json`,
`holder_history.json`) sehingga cron ±5 menit dan alert tidak berubah sedikit
pun. ⭐ di card 🏆 Scan Best Pool (halaman utama) tetap memasukkan token ke card
ini — hanya tempat tampilnya yang pindah.

Card ini berisi pool yang ditambahkan dari **Scan Meteora Pool** (⭐) atau form
manual (`source=meteora`). Setiap entry menyimpan
`timeframe`/source (`24h` atau `30m`), `pool_address`, dan
`metric_baseline` saat masuk watchlist. Snapshot terbaru
`fee_active_tvl_ratio` dan `volatility` ditampilkan langsung di baris bersama
status klasifikasinya.

- **24h** — deteksi bila quotient `fee_active_tvl_ratio / volatility` turun
  minimal **30%** dari baseline saat masuk.
- **30m** — deteksi pada snapshot baru bila `volatility >
  fee_active_tvl_ratio`, yaitu **HIGH RISK LP (PANTAU)**.
- Notifikasi lama berbasis perubahan dust holder **tidak dipakai lagi** untuk
  Watchlist Meteora. Dust holder dan grafik 5 menit tetap tersedia sebagai data
  historis, bukan rule alert. Tombol 🔔/🔕 per token tetap mengatur pengiriman
  alert metrik.
- Source/timeframe, fee/active TVL, volatility, quotient terhadap baseline,
  dan catatan deteksi terlihat tanpa harus membuka expander. Token LP tetap
  tidak muncul dua kali di watchlist holder biasa.
- Tambah manual tersedia lewat form **➕ Tambah CA manual ke Watchlist
  Meteora** di card ini.

## 🏆 Scan Best Pool Meteora (halaman utama, sejak 2026-09-10)

Listing pool Meteora khusus halaman utama. **Penempatan (2026-09-11):**
card dirender **full-width** di bawah grid 2 kolom watchlist — permintaan
user "jangan dibuat grid lagi" (2026-09-10 dulu menempel di bawah 🌊
Watchlist Meteora di dalam grid).

**Satu tombol, satu tabel 24H (sejak 2026-09-16)** — permintaan user: *"hapus
scan 30 menit, kita sisakan yang 24 jam saja"*. Kartu ini pernah punya **dua
tombol** (2026-09-13: *"kayaknya untuk timeframe 30m harus kita pisah tombol
deteksinya dan tabel serta fungsi fee/v lebih besar … kita akan punya 2 tombol
24H dan 30M"*) — tombol **🏆 Scan Best Pool 30M + Holder**, aturan `F/V > 1×`,
tabel-nya, tombol pindah lihat **◼ 24H / ◻ 30M**, dan kolom **Src** semuanya
**dihapus**. Yang tersisa **🏆 Scan Best Pool 24H + Holder** (`key=
"best-pool-scan-24h"`) dengan pill `24H · F/V ≥ 5×`; di bawah tombol ada caption
status hasil per-result (`N pool tersimpan` / `belum di-scan`), bukan lagi
pengalih lane.

Semua **alias lane lama** (`30m`, `1h`, `both`) dipetakan
`meteora_screener.normalize_best_lane()` ke `24h`, jadi hasil scan lama di
session state / `.scan_cache/` dirender ulang dengan aturan 24H (bukan
dibuang): baris `timeframe="30m"` ikut dinilai `F/V ≥ 5×` dan label gapnya
`24H: …`. `scan_best_meteora(timeframe="both")` tetap bisa dipanggil (kompat),
tapi yang dijalankan tetap satu listing 24H.

- **Syarat kelolosan per lane** (`meteora_screener.row_best_gaps`,
  F = `fee_active_tvl_ratio`, V = `volatility` — keduanya persen dari API):

  | Gate (24H saja) | Ambang | Arti |
  |---|---|---|
  | **Volat di window** | `BEST_VOL_SHOW_MIN <= V <= BEST_VOL_SHOW_MAX` (**1%–10%**, dua-duanya inklusif) | permintaan user 2026-09-16: *"volatility kurang dari 1 sembunyikan juga"* + *"volatility > 10 sembunyikan juga"* — di bawah 1% pool nyaris tidak bergerak (fee-nya tidak berarti), di atas 10% pergerakan lebih besar daripada fee yang dibagi. Tepat 1,0% dan 10,0% **tetap tampil** |
  | **F/V** | `F/V >= BEST_FV_24H_MIN` (**5×**, inklusif) | "prioritaskan 24H yang fee/v >= 5× untuk di scan detail, jika kurang dari itu langsung skip" |
  | **Fee/TVL** | `fee_active_tvl_ratio >= BEST_FEE_TVL_MIN` (**30%**, inklusif di sisi tampil) | permintaan user 2026-09-23: *"kita perketat filter yang boleh di show di hasil"* + *"Fee/TVL minimal 30%"* + *"dibawah itu jangan show"* — fee yang kurang dari 30% terhadap active TVL dianggap kurang produktif, jadi **tidak masuk tabel hasil**. Tepat 30,0% **tetap tampil**. Berbeda dari Top10/volat/LPs: barisnya **tidak dibuang total**, masih bisa dibuka lewat "▶ N pool dilewati" dengan alasan `gugur: Fee/TVL … < 30%`. Dicek **sesudah** ambang F/V, jadi pool yang gagal keduanya tetap beralasan `F/V < 5×` |
  | **F/V (lantai buang)** | `F/V < BEST_FV_HIDE_MIN` (**2×**, eksklusif — tepat 2,0× masih tampil) → **dibuang total** | permintaan user 2026-09-24: *"jangan tampilkan sama sekali pool yang F/V nya kurang dari 2 di pool yang dilewati atau dimanapun"* — baris F/V 0–2× **lenyap dari mana pun**: tidak masuk tabel hasil, tidak masuk listing "▶ N pool dilewati", tidak dihitung pill/caption `dilewati`, dan tidak ikut rekap alasan tabel kosong (jejak audit: counter `dropped_fv`). Jadi "dilewati" hanya memuat F/V **2×–5×** plus baris Fee/TVL tipis. Angka F/V tanpa bukti (metrik hilang/nonfinite, volatility 0) **bukan** "kurang dari 2" — baris seperti itu tetap muncul di "dilewati" dengan alasannya sendiri |
  | **Top10** | `top_holders_pct < BEST_TOP10_MAX_PCT` (**< 20%**; `>= 20%` dibuang) | *"scan meteora, TOP 10 diatas 20% jangan ditampilkan lagi"* + koreksi hari yang sama *"jika ada top 10 >= 20% jangan tampilkan"* — **batasnya pindah ke sisi buang**, jadi tepat 20,0% **tidak lagi** tampil. Baris **tanpa** angka (`None`) tetap lolos: tanpa data tidak ada bukti konsentrasi, kolomnya tampil `—` |
  | **Likuiditas GMGN** | **bukan saringan lagi** sejak 2026-09-17 malam (*"filter likuiditas hapus coba"*); `MIN_TOTAL_LIQ_USD` ($500K) sekarang ambang **warna** angka di kolom RugCheck: **> $500K hijau**, **< $500K merah**, tepat di ambang / tak terukur hitam (`gmgn_liquidity.liq_color`) | *"jika grand total liquiditas kurang dari 1M, jangan tampilkan di hasil scan"* (2026-09-17) — ambangnya **$500K**, bukan $1M: diukur dari `gmgn.ai/api/v1/token_info`, PAID = $884.912 / pill = $153.496 / ELON = $149.542, jadi $1M mengosongkan seluruh tabel (*"poolnya kok jadi kosong, padahal token PAID harusnya masuk"*). Baris **tanpa bukti** GMGN (API mati / token tak terlacak) tidak pernah disaring maupun diwarnai — kolomnya menulis `—` hitam |

  Urutan evaluasi = urutan di atas (volat → F/V → **Fee/TVL** → Top10; likuiditas GMGN bukan
  saringan lagi sejak 2026-09-17 malam) supaya
  satu baris gugur hanya menulis satu alasan, dan `BEST_FV_30M_MIN` **tidak** dipakai lagi di mana
  pun (konstanta mati, tetap di-pin "ada tapi tidak dipakai" oleh
  `tests/test_best_pool_scan.py::test_saringan_lama_tetap_mati`).

  V = 0 gugur (2026-09-14: `∞` bukan kelolosan — pool tanpa
  volatility tidak bisa membuktikan fee lebih besar) **dan dibuang dari
  listing seluruhnya** (lanjutan hari yang sama, permintaan user: *"jika
  volatility 0 jangan tampilkan, karena tidak ada pergerakan disitu"* —
  `meteora_screener.row_volatility_zero()`). **Update 2026-09-22**: hasil yang
  gugur karena **Top10** (`Top10 >= 20%`) atau **volatility** (0, < 1%, > 10%)
  **langsung disembunyikan total, tidak ditampilkan di mana pun**
  (`meteora_screener.row_best_dropped()`) — tidak masuk tabel lolos, tidak
  masuk listing "dilewati" 24H, dan tidak dihitung di pill/caption
  (`hidden_metric`). **Update 2026-09-24**: **F/V di bawah 2×**
  (`BEST_FV_HIDE_MIN`, permintaan user *"jangan tampilkan sama sekali pool
  yang F/V nya kurang dari 2 di pool yang dilewati atau dimanapun"*) ikut
  dibuang total lewat helper yang sama (`row_fv_under_hide()`); yang boleh
  masuk listing "dilewati" hanya kandidat gagal **F/V 2×–5×**, baris
  **Fee/TVL** tipis, dan metrik tidak valid. **Di hasil pool yang disembunyikan, baris
  diurutkan menurut: (1) F/V terbesar, (2) Fee/TVL terbesar**
  (`meteora_screener.sort_hidden_best_rows()`), sementara tabel utama tetap
  mendahulukan Fee/TVL terbesar baru kelipatan F/V (`sort_best_rows()`).
  Kandidat gugur lain **tidak pernah** membuat request holder —
  `scan_best_lane()` menolak mereka sebelum `enrich_pools()` (kuota Helius aman).
  Kandidat gagal F/V dibuka lewat tombol **▶ N pool dilewati** (barisnya ditandai
  merah `gugur: F/V < 5×` di sel F/V); baris yang lolos menulis **`<angka>× · lolos ≥ 5×`**
  di sel yang sama (format satu desimal dari `format_fv_ratio`, jadi `5×` tampil `5,0×`).
- **Query API Meteora** (`category=top`, `page_size=50`) —
  `meteora_screener.best_filter_by()`:
  **`base_token_has_critical_warnings=false&&quote_token_has_critical_warnings=false&&pool_type=dlmm&&active_tvl>=50000`**.
  Dua filter paling depan adalah **safeguard Jupiter** yang diminta user
  2026-09-16 (*"scan baru saya tambahkan jupiter safeguard untuk filter yang
  mungkin rug"*): listing hanya boleh berisi pool yang **bebas critical warning
  di kedua sisinya** (base DAN quote), jadi token dengan mint/freeze authority
  aktif, extensions mencurigakan, atau `critical_warnings` dari Jupiter
  terbuang **sebelum payload diterima** — hemat kuota, bukan hanya hemat
  render. Guard ini milik jalur Best Pool saja: `filter_by()` reguler (card 🌊
  Watchlist Meteora) tetap `pool_type=dlmm&&active_tvl>=50000` tanpa safeguard,
  dan bisa dimatikan per-panggilan lewat `safeguard=False` untuk diagnosis.
  `fee_pct>=2` **dihapus**
  2026-09-13 (pool ber-fee rendah seperti EMBER/USDC harus muncul). Saringan
  layar lama — volume 24 jam ≥ $1M, volatility ≥ 2%, dust < 0,05% MC — ikut
  **dihapus**: dust/volume/tier fee/LPs/active TVL tetap tampil sebagai
  **informasi**, bukan syarat. **Top10 adalah pengecualian sejak
  2026-09-16** — ambangnya dihidupkan lagi (20%, bukan 30% yang lama) atas
  permintaan user di atas.
- **Urutan tiap tabel** (2026-09-15 lanjutan, permintaan user: *"sebentar, kita
  urutkan fee/TVL paling besar dulu, baru perkalian f/v"*): **Fee/TVL
  terbesar** (`fee_active_tvl_ratio`) → **F/V terbesar** → **volume / active
  TVL window lane-nya** (`volume_active_tvl_ratio`, angka persen dari API;
  ditulis di baris kecil kolom Vol sebagai `… · 1,647× A.TVL`) → **dust % MC
  terkecil** → simbol alfabetis. Fee/TVL hanya **urutan**, bukan saringan —
  kelolosan tetap F/V lane. Kunci dust dibulatkan ke presisi tampilan (3
  desimal) supaya dua pool yang di layar sama-sama "0,030%" dianggap seri;
  baris tanpa angka di sebuah kunci turun ke bawah di kunci itu (tidak
  hilang).
- **Session key**: `best_pool_scan_24h` (satu-satunya hasil) +
  `best-pool-toggle-hidden-24h` (lihat/tabel dilewati) + ⭐ per pool
  `best-pool-24h-star-<pool_address>`. Kunci lama `best_pool_scan_30m`,
  lane aktif `best_pool_lane`, dan tombol `best-pool-scan-30m` **dihapus**;
  hasilnya tidak dibuang — hasil sesi lama yang masih gabung (`best_pool_scan`)
  dipecah sekali saat render lalu dinilai ulang dengan aturan 24H, jadi listing
  tidak hilang setelah update.
- **Kolom Token menulis pasangan pool-nya** (2026-09-15, permintaan user:
  *"kolom Token sekarang akan menunjukkan pasangan pairnya, misal
  ALLINU/SOL"*): `$SIMBOL` di baris pertama, pasangan pool DLMM di bawahnya
  (nama pool dari API Meteora apa adanya — `meteora_screener.row_pair_label`,
  mis. `ALLINU/SOL`, `GOLD/XAUt0`; pasangannya **tidak** ditebak dari simbol,
  pool `TOK-USDC` tetap `TOK-USDC`), alamat mint tetap di baris terakhir.
  Hasil scan lama yang belum menyimpan `pool_name` tidak menampilkan baris
  pasangan sama sekali (bukan dikarang).
- **Angka F/V** dibaca dari `meteora_screener.format_fv_ratio`: satu desimal
  di bawah 100× (`10,1×`, `6,4×`), **bulat + pemisah ribuan** dari 100× ke
  atas (`6,328,266×`) — permintaan user 2026-09-15 (*"coba cek last scan —
  gold menunjukkan 6328266.1 F/V — perbaiki"*: rasio pool `GOLD-XAUt0`
  memang benar 6,33 juta× karena `volatility`-nya 2,06e-09, yang salah cuma
  formatnya). `∞` (warisan hasil lama) dan `—` (tidak terukur) tetap; angka
  yang sama tetap dipakai menyaring + mengurutkan (`row_fv_ratio`), jadi
  format tidak mengubah keputusan. Tooltip sel menulis persen kecil apa
  adanya (`volatility 2.06e-09%`, bukan `0.00%`).
- Kolom listing (ditata 2026-09-16 — **15 kolom**, satu sumber urutan
  `best_pool_ui._COL_SPEC` yang dibaca `_lane_titles()` supaya header, lebar,
  dan isi sel tidak bisa berbeda jumlah; kolom **Src** dan **Dust** (jumlah
  wallet) sudah dihapus):

  `Token` · `F/V` · `Fee/TVL` · `Volat` · **`Active Range`** · **`LPs`** ·
  `Dust %MC` · `Fee %` · `MC` · `A.TVL` · `Vol 24h` · `Top10` ·
  **`RugCheck`** · `Pool` · `⭐`

  Yang berubah hari ini: **Active Range digeser ke kanan Volat** (*"Active Range
  kolom ini pindah ke kanan volat"*) dan **LPs tepat di kanannya** (*"kolom LPs
  pindah ke kanan active range setelah dipindah"*), keduanya masuk ke blok
  "pergerakan + kedalaman"; **kolom RugCheck baru** di antara Top10 dan Pool;
  dan **LPs menjadi hijau** bila `lps_count > 100` (*"LPs jika lebih dari 100,
  kasih warna hijau jika tidak, tidak ada perubahan"* — `LP_GREEN_COLOR
  #16a34a`, `LP_GREEN_MIN_LP = 100.0`, **strict**: tepat 100 tidak hijau, dan
  tidak ada pill/ikon tambahan). Baris kecil kolom **F/V** = `syarat F/V ≥ 5×`
  (lolos) / `gugur: <alasan>` merah (tabel dilewati). Hover tiap angka memberi
  angka penuh + keterangan apakah metrik itu kunci urut atau hanya informasi.
  Sel **volatility terbesar**, sel **F/V tertinggi**, dan sel **Fee/TVL
  tertinggi** tabel utama disorot
  **hijau tua menyala** (`#15803d`, bold; seri di puncak ikut ditandai semua;
  tabel "dilewati" tidak ditandai).
- **Kolom Active Range** (2026-09-14, permintaan user: *"tambahkan Active
  Range, tapi % saja, misal -30% +40"*; sejak 2026-09-16 duduk di kanan **Volat**
  dan di kiri **LPs**, bukan lagi di kanan A.TVL) hanya menulis persen: `-34.5% / +19.0%` = harga pool masih boleh **turun
  34,5%** atau **naik 19,0%** sebelum keluar dari rentang bin DLMM yang
  berisi likuiditas — di luar range itu posisi LP berhenti menghasilkan fee.
  Turun ditulis merah, naik hijau, baris kecil = lebar range seluruhnya.
  `0.0%` (tanpa tanda) berarti harga **persis di tepi range**. Sumbernya
  payload listing yang sudah dipakai: `pool_price` (harga bin aktif) +
  `min_price` / `max_price` (bin berisi likuiditas terendah/tertinggi) dari
  `pool-discovery-api.datapi.meteora.ag/pools`, disimpan ke baris sebagai
  `pool_price` / `range_min_price` / `range_max_price` + `bin_step`
  (`_row_from_pool`) dan dihitung `meteora_screener.active_range_pct()` /
  `active_range_width_pct()` / `active_range_bins()` / `active_range_text()`.
  Terverifikasi 2026-09-14 pada tiga pool live dengan `bin_step` berbeda
  (CATE-USDC 20, biketyson-SOL 100, ROUTER-SOL 250): ketiga harga itu cocok
  dengan rumus bin DLMM `P_i = (1 + bin_step/10000)^i` sampai 0,000 ppm, jadi
  `min_price`/`max_price` memang tepi bin — **bukan** high/low 24 jam. Harga
  bin mentah, lebar range, jumlah bin (`300 bin · 212 bin di bawah harga`),
  dan `bin_step` ada di tooltip sel. **Bukan saringan** — informasi saja, dan
  hasil scan lama yang belum menyimpan field-nya menulis `—` (bukan
  `-0.0% / +0.0%` palsu), jadi tekan tombol scan lagi untuk mengisinya.

- Tombol **⭐** memasukkan token ke card **🌊 Watchlist Meteora** di halaman
  **📦 TEMP** (`source=meteora`) — token lalu ikut di-scan cron ±5 menit lengkap
  dengan grafik perubahan dust holder. Tombolnya tetap di baris Best Pool
  (halaman utama); yang pindah hanya card tujuannya.
- **Kolom RugCheck** (2026-09-16) — lihat section **🧿 RugCheck** di bawah.
  Kolom ini **informasi saja**: ia tidak pernah membuang baris (saringannya
  tetap volat + F/V + Top10 + safeguard Jupiter di sisi API), dan verdict tidak
  pernah ditebak dari ketiadaan data.
- **Tanpa caption rule di badan card** (2026-09-10): penjelasan dua tombol +
  ambang + urutan hanya tampil sebagai **tooltip judul** (kursor di atas
  tulisan "🏆 Scan Best Pool Meteora") dan tooltip `help` tiap tombol.
  Teksnya dibangun `best_pool_ui.best_pool_tooltip()` +
  `best_lane_gate_text()` dari konstanta `meteora_screener.BEST_FV_*`, jadi
  angka di tooltip tidak mungkin beda dari rule yang jalan; mengubah ambang =
  tooltip, label sel, dan teks gugur ikut berubah.

Tes terfokus: `python -m unittest tests.test_best_pool_scan
tests.test_best_fv_prefilter tests.test_rugchecker tests.test_temp_page_ui` —
saringan lane + kolom 15 + aturan RugCheck + halaman TEMP semuanya diuji di
empat file itu (suite penuh offline: 1059 tes).

## 🧿 RugCheck (kolom di listing 🏆 Scan Best Pool)

Permintaan user 2026-09-16: *"kita tambahkan kolom baru RugCheck dengan metode
ini"* — sumbernya **`GET https://www.rugchecker.cc/api/honeypot/checker?address=<mint>`**
(bukan rugcheck.xyz; koreksi user: *"maaf salah, bukan dari rugcheck tapi dari
sini"*), **tanpa API key** — cukup header browser (`accept`,
`referer: https://www.rugchecker.cc/`, User-Agent). Cookie `_ga` yang ikut
terkirim di devtools adalah analytics Google, bukan kredensial, jadi **sengaja
tidak dikirim** (`rugchecker._HEADERS`).

Yang dibaca dari payload: `data.is_honeypot`, `data.security` (9 bendera),
`data.dex[]` (likuiditas per pool = blok "Liquidity Information" di UI
rugchecker.cc) dan `data.symbol` — diminta user **dalam versi yang lebih
ringkas**, jadi satu sel hanya menulis verdict + total likuiditas + jumlah
pool, sisanya (baris per DEX, bendera, penjelasan metode tambahan) masuk
tooltip sel.

| Kelas | Kondisi | Verdict / warna |
|---|---|---|
| **RUG** | `is_honeypot` true | `RUG` `#dc2626` |
| **BERISIKO** | bendera kritis di `security`: `mintable`, `freezable`, `non_transferable`, `transfer_hook_upgradable`, atau `transfer_fee > 0` (angka persen → `transfer fee 5%`) | `BERISIKO` `#b91c1c` |
| **WASPADA** | bendera minor: `transfer_fee_upgradable`, `balance_mutable`, `metadata_mutable`, `closable` | `WASPADA` `#b45309` |
| **AMAN** | tidak ada satu pun | `AMAN` `#15803d` |
| **—** | laporan tidak didapat (HTTP/timeout/JSON rusak/`code != 0`) | `—` (tanpa warna) |

**Metode tambahan** (user: *"jika kamu memiliki metode tambahan untuk check rug,
bisa kamu tambahkan kolom juga untuk penjelasanmu secara ringkas"*) — tiga
pemeriksaan tanpa request tambahan, di atas payload yang sama:

1. **kedalaman pool yang dipakai** — `liquidity.usd` pool ini (dicocokkan lewat
   `pair_address` listing Meteora) vs `POOL_MIN_LIQ_USD` ($10K): di bawah itu
   `TIPIS — harga mudah digeser`;
2. **sebaran likuiditas** — share likuiditas token di pool ini vs
   `POOL_SHARE_MIN_PCT` (25%); di bawah itu harga pool bisa menyimpang dan fee
   ikut terkuras;
3. **konsentrasi pasar** — berapa pool yang likuiditasnya ≥
   `BIG_POOL_SHARE_PCT` (10%) dari total; kalimat "sisanya debu, mudah ditarik
   keluar" hanya boleh ditulis kalau memang ada sisa (kalau semua pool sama
   besar, tertulis `tersebar merata`).

Aturan teknis lain: `market_cap` **selalu** diambil dari pool **terbesar**
(token sampel user melaporkan MC $1,9 M di pool berlikuiditas $0,16 — angka
per-pool tidak bisa dipakai); baris likuiditas dibatasi `MAX_LIQ_LINES` (3)
lalu `+N pool`; mint yang laporannya tidak didapat menulis `—`, **bukan**
`AMAN`; cache berkas `rugchecker_cache.json` (TTL sukses `CACHE_TTL_OK` 1800 s,
kegagalan `CACHE_TTL_FAIL` 300 s, prune LRU `CACHE_MAX_ENTRIES` 400, tulis
atomik) menahan request berulang saat rerun Streamlit.

`rugchecker.py` **tidak** mengimpor Streamlit/`dashboard_components` (dipakai
cron + tes juga), hanya `requests` di-import di dalam fungsi. `attach_to_rows()`
menempel `row["rugcheck"]` ke baris yang **lolos saringan** saja — baris gugur
tidak pernah menembak API pihak ketiga.

## 🚀 Pre-Pump Screener

Section di dashboard utama (`pre_pump_screener.main(configure_page=False)`)
dan halaman mandiri `pages/7_🚀_Pre-Pump.py`. Scope: **hanya token watchlist
`source=degen`** (token Meteora/LP dan manual dikecualikan). Empat sinyal
independen, tiap sinyal mengembalikan `confidence` 0–1:

| Sinyal | Sumber | Syarat menyala |
|---|---|---|
| ✅ **Liquidity wave** | `liquidity.usd` DexScreener → journal `pre_pump_liq.json` | add kedua ≥ **5x** add pertama dalam **48 jam** (token berlikuiditas < $25k: **3x**) |
| ⚠️ **Holder consolidation** | `holder_status.json` + titik 24 jam lalu di `holder_history.json` | ≥ **5 wallet** keluar dari dust **dan** rata-rata bag real ≥ **2x** |
| 🔥 **Volume calm-before-storm** | candle hourly GeckoTerminal 7 hari | 24 jam **pra-spike** ≤ **30%** rata-rata harian **dan** 6 jam terakhir ≥ **2x** baseline 6 jam |
| 📊 **TX velocity** | swap Helius (`cvd.fetch_swaps`), fallback agregat `txns` DexScreener | akselerasi 2 jam akhir vs 2 jam awal ≥ **1,5** (+150%); `buy_pressure` ≥ **0,65** = whale |

```text
PUMP SCORE      = (0,25·liq + 0,25·consol + 0,25·vol + 0,25·vel) × 10
confidence_pct  = rata-rata confidence sinyal AKTIF saja (tanpa sinyal = 0%)
EST. ALPHA WINDOW: ≥3 sinyal & skor ≥ 6,5 → 2–6 jam (0–2 jam bila TX
                   velocity sudah akselerasi); skor ≥ 5 → 6–24 jam
```

Catatan implementasi yang perlu diketahui:

- **Journal likuiditas.** DexScreener tidak punya endpoint riwayat
  likuiditas, jadi tiap scan mencatat `liquidity.usd` per pool ke
  `pre_pump_liq.json` (gitignored, dipangkas ke 72 jam / 900 titik). Run
  pertama hanya mengisi journal: dengan < 2 observasi confidence likuiditas
  dikunci **0,3** (bukan 0, bukan 1). Pola dua gelombang baru terbaca
  setelah beberapa run.
- **Window volume tidak boleh tumpang tindih.** Syarat "24 jam ≤ 30%
  rata-rata" dan "6 jam ≥ 2x baseline" mustahil benar bersamaan bila 24 jam-nya
  trailing (window 6 jam ada di dalamnya). Window tenang dihitung pada 24 jam
  **sebelum** window 6 jam; rasio 24 jam trailing tetap dilaporkan sebagai
  `vol_ratio_24h_trailing`.
- **`VOLUME_SPIKE_BASE`** (`"6h"` default) memilih pembanding lonjakan 6 jam;
  ubah ke `"daily"` untuk membaca blueprint (`vol_6h ≥ 2x` rata-rata harian).
- **Auto-refresh 5 menit** memakai `st.fragment(run_every=300)`, bukan
  `while True: time.sleep(300)` — loop seperti itu tidak pernah kembali di
  Streamlit (script dijalankan ulang per interaksi), UI akan membeku.
  Fragment punya guard umur hasil scan supaya tidak rerun berulang.
- **Tanpa `HELIUS_API_KEY`** sinyal TX velocity tetap jalan dari agregat
  `txns` DexScreener, ditandai `source=dexscreener_txns` dengan confidence
  dibatasi **0,6**.
- Token tanpa history 7 hari → sinyal volume dilewati; snapshot holder < 24
  jam → pakai titik tertua dan tandai **stale**; data likuiditas hilang →
  confidence 0,3.

## Kolom "Sejak masuk" di watchlist

Setiap baris 📋 Watchlist Holder menampilkan perubahan dust **sejak token
ditambahkan** (`added` di `watchlist.json`) **sampai scan terakhir**:

- kolom **Awal Masuk** (tepat di kiri "Sejak masuk", sejak 2026-09-13) =
  dust % MC di titik yang sama saat token masuk watchlist — angka patokan
  notif ⚡ EARLY DUMP, 3 desimal, sub-caption waktu titik + penanda varian
  fallback, tooltip sel = kalimat lengkap `baseline_note()`
  (`watchlist_detail.baseline_cell()`); kolom yang sama juga ada di tabel
  🌊 Watchlist Meteora — keduanya 8 kolom, kolom ke-4 adalah **Awal Masuk**;
- perubahan **relatif** (%) dust % MC — angka besar di kolom **Sejak masuk**,
- pembandingnya titik pertama **pada/setelah** tanggal masuk; bila belum ada
  titik setelah tanggal itu, dipakai titik pertama dan ditandai di tooltip,
- tooltip memuat nilai awal → akhir (% MC), perubahan **poin persentase**
  (satuan rule alert), perubahan **jumlah wallet dust**, dan umur window,
- warna mengikuti ambang permintaan user:
  **turun ≥ 50%** = hijau (`#15803d`, dust menipis),
  **naik ≥ 100%** = merah (`#b91c1c`, dust menebal 2×), di antaranya abu-abu.
- **detail tiap token** (expander 📈) dibuka dengan baris **dust % MC saat
  token pertama masuk watchlist** (sejak 2026-09-13) — angka yang sama dengan
  patokan notifikasi ⚡ EARLY DUMP, lengkap dengan dust sekarang + selisih pp;
  varian fallback (tanggal masuk tak terbaca / belum ada titik sejak masuk)
  ikut ditulis. Berlaku di semua card watchlist karena semuanya memakai
  expander yang sama.

**Sinkronisasi baris ↔ scan terakhir.** Sebelumnya baris membaca snapshot
`holder_status.json` (cron) sementara sparkline membaca `holder_history.json`
yang sudah memuat titik scan manual/scan lebih baru — satu token bisa
menampilkan dua angka berbeda. `watchlist_detail.resolve_view()` memilih
sumber **terbaru** untuk satu baris, `previous_pct()` memilih pembanding
badge yang benar, dan caption card diganti `sync_caption_text()`: satu waktu
"Scan terakhir" + rincian berapa token memakai snapshot cron, berapa memakai
titik history yang lebih baru, berapa yang datanya basi (> 2 jam), dan berapa
yang snapshot-nya berbeda dari titik history (⚠️).

### Scan holder yang tidak lengkap tidak dihitung sebagai angka

Provider holder bisa pulang dengan **sampel pendek tanpa menandai
`truncated`** (kasus nyata 2026-09-06: Helius mati karena rate limit →
fallback GMGN mengembalikan 20 holder). Wallet dust (nilai ≤ $10) ada di
**ekor** daftar holder, jadi sampel sependek itu selalu berisi
`dust_count 0` / `dust_pct_mc 0.0`. Kalau angka itu dipakai apa adanya, kolom
**Sejak masuk** melaporkan **−100%** (hijau, "dust habis") untuk puluhan token
padahal tidak ada yang menjual — dan **Hold %MC** ikut menampilkan `0,00%` +
badge **AMAN**.

Aturan yang dipakai (`holder_history.MIN_USABLE_WALLETS` = 40, sama dengan
guard badge 🏆 BEST POOL):

- `scan_degraded(holders)` / `holders_usable(holders)` — `total_fetched < 40`
  atau jumlah wallet dianalisis `< 40` = **tidak layak**. Snapshot lama tanpa
  info jumlah wallet tidak ditolak (tidak ada bukti).
- `point_usable(point)` / `usable_points(points)` — titik history dari scan
  pendek (atau yang sudah ditandai `degraded: True` saat ingest) dibuang dari
  angka baris, pembanding "sejak masuk", sparkline, grafik 4 jam, dan overlay
  Chart LP.
- `watchlist_detail.resolve_view()` memilih nilai **layak** terbaru dan
  melaporkan `degraded` + `degraded_note`; baris menulis
  `⚠️ scan 06 Sep 03:00 WIB cuma 19 wallet`, kolom **Sejak masuk** diberi ⚠️,
  dan caption menyebut berapa token yang scan terakhirnya tidak lengkap.
- Token yang **semua** scan-nya pendek menulis `belum ada data ⚠️` (tooltip
  menjelaskan alasannya) — bukan `0,00%`.
- Halaman **Holder Analytic** memakai aturan yang sama: kartu metrik jatuh ke
  titik layak terakhir + peringatan "scan holder terakhir tidak lengkap".
- `telegram_alerts.process_holder_alerts()` melewatkan scan tidak layak,
  sehingga tidak ada notifikasi yang pernah menyala dari "dust 0%" palsu.

### Scan dari halaman utama = update per token, bukan timpa data

Tombol **🔄 Scan holder watchlist** (halaman utama) memperbarui **list holder
terbaru sesuai waktu snapshot masing-masing token** tanpa menimpa data yang
sudah tercatat:

- Snapshot di-publish dengan `merge_status` → token yang **gagal/timeout** pada
  run itu tetap memakai baris + nilai terakhirnya (tidak hilang dari
  dashboard).
- Scan yang **tidak lengkap** (kurang dari 40 wallet terambil) tidak
  di-publish dan tidak masuk history → angka lama dipertahankan.
- `ingest_many(..., detail=False)`: **baseline scan FULL**, `latest_detail`,
  dan kronologi tidak pernah ditimpa oleh scan halaman utama — angka
  "Δ bucket vs baseline" tetap memakai data scan FULL.
- Setelah scan muncul ringkasan: `N token diperbarui · K token tetap memakai
  data yang sudah tercatat · F scan gagal · S scan tidak lengkap dilewati
  (ticker) · list holder diperbarui sampai snapshot <waktu>`.
- Caption dashboard menyebut **berapa token yang ada di waktu snapshot
  terbaru** (`Scan terakhir: 06 Sep 03:01 WIB (36 token) · 41 token masih di
  snapshot sebelumnya`), dan tooltip **Sejak masuk** menyebut waktu snapshot
  yang dipakai — jadi satu angka waktu global tidak menyesatkan.

## Deteksi Akumulasi (8 heuristik)

Halaman `pages/6_🔎_Deteksi_Akumulasi.py` menghitung 8 heuristik untuk token
**watchlist** (sumber daftar selalu `watchlist.load_watchlist()`), masing-masing
mengembalikan `{nilai, status, penjelasan, cukup_data}` sehingga "tidak tahu"
tidak pernah dihitung sebagai "netral":

| # | Metrik | Bahan mentah |
|---|---|---|
| 1 | Tier Migration Velocity | bucket wallet depth dua titik `holder_history` terakhir |
| 2 | Diamond Hands Ratio | posisi net per wallet dari swap GMGN (tidak pernah net-sell) |
| 3 | Pola DCA vs One-off Buy | jumlah buy unik + dominasi satu buy per wallet |
| 4 | Smart Money / PnL Wallet | **GMGN saja**: `maker_tags` + `realized_profit` per wallet |
| 5 | Silent Range Accumulation | volume DexScreener (lantai $10K–plafon $250K), range menyempit, CVD net 0…+15% |
| 6 | Spring / Test Pattern | candle 4 jam menusuk level support D1 lalu close di atasnya, volume tipis |
| 7 | Fresh Wallet Prep | tag `fresh_wallet` GMGN, beli bertahap ≥ 30 menit, tanpa sell |
| 8 | Sell-Side Liquidity Thinning | % posisi net di wallet tanpa jual 14 hari (+ delta dari snapshot sebelumnya) |

Skor 0–100 = rata-rata berbobot metrik yang **cukup data**; ≥ 60 →
**Terindikasi Akumulasi**, selain itu **Netral**, tanpa data →
**Tidak Cukup Data**. Snapshot ringkas disimpan ke `accumulation_history.json`
(skema sendiri, git-ignored) supaya metrik 8 bisa menunjukkan arah proporsinya.

**Kuota Helius tidak dipakai halaman ini** (keputusan user 2026-09-04):
metrik 4 memakai realized profit per wallet dari GMGN, bukan riwayat PnL
lintas token lewat Helius Enhanced API, dan metrik 7 memakai tag
`fresh_wallet` GMGN — identitas funder tidak tersedia tanpa scan Helius, jadi
metrik itu menandai **pola** wallet baru (ditulis eksplisit di penjelasan).
Level support metrik 6 diturunkan dari candle harian `core.get_daily_candles`
karena repo ini tidak punya `levels.json`.

⚠️ Seluruh metrik heuristik: penanda untuk diperiksa manual, bukan bukti
akumulasi dan bukan prediksi arah harga.

## Modul

| File | Peran |
|---|---|
| `holder_history.py` | Pencatatan dust/kohort, resample 4 jam, ambang HATI-HATI/BAHAYA + BEST POOL 0,1% (aditif), metrik volatilitas 4 jam, baseline FULL, kronologi, backup durable store (`.gz`: merge/prune/publish/pull; titik mentah per run, `MAX_POINTS` 1008) |
| `alert_context.py` | Konteks pasar untuk konfirmasi alert: volume 4 jam, rata-rata 7 hari, buy/sell pressure, volatilitas (ditarik lazy) |
| `holder_chronology.py` | Snapshot wallet bounded, klasifikasi pergerakan, narasi kronologi |
| `lp_watchlist.py` | Card **Chart LP**: pisah watchlist Meteora, baris metrik fee/volatility + grafik dust historis |
| `meteora_screener.py` | Regular listing DLMM 24h lalu 30m, active TVL ≥ 50K, filter/classification fee-versus-volatility, sort quotient tanpa dust, enrich holder; Best Pool terpisah: `scan_best_lane(lane)` **satu listing 24H** (alias `30m`/`1h`/`both` → `normalize_best_lane` → `24h`), query `best_filter_by()` = safeguard Jupiter + `pool_type=dlmm&&active_tvl>=50000`, saringan `row_best_gaps` volat 1%–10% → F/V ≥ 5× → Fee/TVL ≥ 30% → Top10 `< 20%` **sebelum** holder, lantai buang `row_fv_under_hide` (F/V < 2×) lewat `row_best_dropped`, `sort_best_rows` urut Fee/TVL → F/V → vol/TVL → dust, lalu `rugchecker.attach_to_rows` |
| `rugchecker.py` | Kolom **RugCheck** — honeypot checker **rugchecker.cc** (tanpa API key): `fetch_raw` (1 mint), `summarize` (verdict AMAN/WASPADA/BERISIKO/RUG/`—` + likuiditas ringkas + 3 catatan "metode tambahan"), `check_tokens` (paralel `WORKERS` 6, cache berkas TTL, kegagalan satu mint ≠ scan mati), `attach_to_rows` (menempel, tidak menyaring), `cell_parts` (angka/sub/tooltip — dipakai UI, formatting tidak diulang di card) |
| `temp_ui.py` | Isi halaman **📦 TEMP**: `render_auto_refresh()` (±60 dtk), card **🌊 Watchlist Meteora** (`_render_lp_card` + head/row), section **🛰 Scan Holder Solana** (form CA → scan Helius FULL → bar chart + tabel), dan `render_temp_page()` sebagai entry point halaman. Fungsi store/scan dipanggil **lewat modulnya** (`wl.add_to_watchlist`, `hs.publish_holder_status`, …) supaya `mock.patch("watchlist.…")` di tes tetap kena (modul ini di-cache antar-run AppTest, `app.py` di-exec ulang) |
| `holder_analysis.py` | Fetch holder Helius/GMGN, klasifikasi real/dust/mid |
| `solscan_holders.py` | Kalkulasi wallet_depth (bucket & tier) |
| `helius_holders.py` | Scan Holder Solana satu token (Solana/Helius) + bar chart |
| `holder_status.py` | Snapshot dashboard ramping (ref `holder-live`) + history ringkas + transport GitHub (JSON & byte/gzip) |
| `core.py` | Config/key Helius (pool round-robin; placeholder `PASTE-API-KEY-…` disaring, Streamlit secrets menang atas `config.json`), pasar DexScreener, candle hourly/harian GeckoTerminal (network bisa dipilih; app ini memakai `solana`), **status + sisa kredit key Helius** (`helius_key_status` / `helius_usage_summary`) dan hitungan request lokal |
| `activity_log.py` | Ring buffer kejadian semua card (400 entri, dedup 60 dtk, level `action` = merah bold) + panel **🧾 Log Aktivitas**: **sisa kredit Helius** |
| `best_pool_ui.py` | Card **🏆 Scan Best Pool Meteora** (halaman utama, full-width sejak 2026-09-11) — **satu tombol 24H** + satu tabel 15 kolom (`_COL_SPEC` + `_lane_titles`), saringan `meteora_screener.BEST_*` + sel RugCheck dari `rugchecker.cell_parts`, LPs hijau > 100, ⭐ → Watchlist Meteora di 📦 TEMP, detail = tooltip judul, hasil ikut tersimpan di cache berkas (2026-09-14) |
| `scan_result_cache.py` | Cache berkas hasil scan (`.scan_cache/`, git-ignored): `save_result` / `load_result` / `restore_into_session` — refresh browser tidak menghilangkan tabel; payload dirampingkan (peta wallet dibuang) dan ditulis atomik |
| `scripts/scan_holders.py` | Cron **lane LP saja** (run ±5 menit): snapshot metric Meteora + holder/history, publish status + backup |
| `telegram_alerts.py` | Alert holder-dust untuk lane non-Meteora: ⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE (delta dust ≥ 0,02% MC), marker `alert_state["early_dump"]`, Telegram Bot API |
| `links.py` | Satu sumber URL eksternal: GMGN, DexScreener, Solscan, Meteora DLMM, HawkFi (HTML untuk UI, teks polos untuk Telegram) + slug halaman internal (`/Holder?mint=…`) |
| `page_router.py` | Router deep link: `?mint=`/`?page=` yang jatuh ke halaman utama dipantulkan ke halaman yang dituju (`st.switch_page`) |
| `pre_pump_screener.py` | 🚀 Pre-Pump Screener: 4 sinyal on-chain (gelombang add likuiditas + journal, konsolidasi holder, volume calm-before-storm, TX velocity), PUMP SCORE 0–10, kartu token, auto-refresh `st.fragment(run_every=300)` |
| `pages/4_📊_CVD.py` | Chart CVD harian |
| `pages/5_🧮_Holder.py` | Holder Analytic: dust, grafik 4 jam, kohort, kronologi FULL |
| `pages/6_📦_TEMP.py` | Halaman **📦 TEMP** (sejak 2026-09-16): wrapper tipis yang memanggil `temp_ui.render_temp_page()` — 🌊 Watchlist Meteora + 🛰 Scan Holder Solana. Tanpa `page_router.apply()` (router hanya untuk halaman utama) |

| `watchlist_detail.py` | Baris watchlist: delta dust **sejak masuk watchlist** (relatif % + pp + jumlah wallet), warna ambang −50%/+100%, dan penyatuan angka baris ↔ scan terakhir |
| `accumulation.py` | 8 heuristik deteksi akumulasi (murni kalkulasi, tanpa Helius) + skor 0–100 + store snapshot `accumulation_history.json` |
| `pages/6_🔎_Deteksi_Akumulasi.py` | Halaman **Deteksi Akumulasi**: ringkasan skor/status per token watchlist + expander breakdown 8 metrik |
| `pages/7_🚀_Pre-Pump.py` | Halaman mandiri Pre-Pump Screener |

## Tautan Holder Analytic (deep link)

Tombol **🧮** di setiap baris watchlist membuka **tab baru** ke analisa holder
token itu. URL-nya memakai **slug halaman** Streamlit, bukan path file:

```text
https://<app>.streamlit.app/Holder?mint=<contract address>   ✅ berfungsi
https://<app>.streamlit.app/pages/5_🧮_Holder.py?mint=…      ❌ bukan route
```

Streamlit menyetel URL halaman dari nama file di `pages/` dengan prefiks nomor
dan emoji dibuang (`5_🧮_Holder.py` → `/Holder`, `4_📊_CVD.py` → `/CVD`,
`6_🔎_Deteksi_Akumulasi.py` → `/Deteksi_Akumulasi`), dan pencocokannya
**case-sensitive**. Bentuk kedua tidak cocok dengan halaman mana pun:
Streamlit menampilkan "Page not found" lalu menjalankan halaman utama, sehingga
`?mint=` tidak pernah dibaca.

Tautan lama (dan URL yang salah ketik/salah kapitalisasi) tetap dipakai
bersama: `page_router` di halaman utama melihat `mint=` di URL lalu memantulkan
ke halaman yang benar lewat `st.switch_page`. Parameter yang dimengerti:
`mint` / `ca` / `token` / `address` (CA Solana base58) dan `page` (slug /
nomor halaman / nama file). Nilai yang
bukan address valid diabaikan — navigasi user tidak pernah dibajak. Bisa juga
dipakai manual: `?page=cvd&mint=…`.

## Menjalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

Snapshot dibaca dari `holder_status.json` dan store penuh dari
`holder_history.json.gz` (keduanya ref `holder-live`) — lihat **Backup store
holder**. Lihat `DEPLOY.md` untuk env scanner (`HELIUS_API_KEY`,
`GITHUB_TOKEN`) dan setup alert opsional (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`). **Secret GitHub dan secret Streamlit Cloud terpisah**
— cron memakai yang pertama, scan manual di dashboard memakai yang kedua;
keduanya butuh token bot **dan** chat ID. Tanpa credential Telegram, scan
tetap berjalan dan pengiriman alert dilewati dengan aman.

## Cadens scan

Sejak **2026-09-07** cron dirampingkan jadi **lane LP saja** dan berjalan
**tiap ±5 menit** (`scripts/scan_holders.py`):

| Lane | Kadens | Alasan |
| --- | --- | --- |
| 🌊 **Chart LP Meteora** (Solana/Helius) | tiap run = **±5 menit** | permintaan user: "untuk watchlist meteora juga, per 5 menit, biar perubahan holder bisa langsung ketahuan" |
| 📋 **Watchlist biasa** (Solana non-LP) | **tidak di-scan cron** | dirampingkan 2026-09-07 ("fokuskan ke holder scan … pencatatan lain tidak perlu"); card-nya ikut terhapus 2026-09-15 bersama page temp |

Yang ikut dibuang bersama lane biasa: slot 4 jam + catch-up + bootstrap token
baru, `merge_status` (pewarisan baris token biasa ke
snapshot), pembacaan toggle **global** Telegram watchlist biasa per run, dan
token lama di backup durable — `publish_holder_history(..., keep_mints=watchlist LP)` hanya
men-push token yang memang di-scan (terukur pada store nyata: **2.135.084 →
10.050 byte** gzip, 81 token → 1 token LP aktif). Scan FULL (baseline immutable
+ kronologi wallet) tidak dijadwalkan lagi; jalankan manual bila perlu:
`python scripts/scan_holders.py --full`.

Harga yang dibayar: tiap run menarik holder penuh semua token Meteora dari
Helius. Kalau kuota mulai ketat, TIDAK perlu mengubah kode — set
`LP_SCAN_RUN_MULTIPLIER: "3"` di langkah scan pada workflow, lalu
`lp_slot_due` menahan lane Solana di luar slot 15 menitnya
(log: `Rencana scan Meteora LP: … slot_lp=bukan`).
**Gate run ganda** `MIN_RUN_GAP_SEC` = **4 menit**, wajib di bawah
kadens run — kalau tidak, lane LP justru dibungkam gate-nya sendiri. Yang
sengaja dibatasi: notifikasi 🚨 Telegram (`FAST_BUCKET_SEC` = 5 menit/token)
— tanpanya satu token bisa dapat pesan kembar di tiap run yang berdekatan
(chain dispatch + schedule).

Densitas titik riwayat mengikuti kadens run, jadi `holder_history.MAX_POINTS`
naik **336 → 1008** (±3,5 hari pada titik 5 menit) supaya "Grafik 4 jam" di
card LP tetap 21 bucket; tanpa itu jendela grafik menyusut jadi 28 jam.

Kadens dijaga dua mekanisme di `.github/workflows/daily-effort.yml`: `schedule:
"*/5 * * * *"` (fallback) dan langkah **chain dispatch** yang tidur sampai
batas 5 menit berikutnya lalu men-dispatch run baru — dengan dua rem supaya
antrean concurrency `holder-scanner` tidak menumpuk dan saling membatalkan
("Canceling since a higher priority waiting request …"): dispatch dilewati bila
masih ada run mengantre/berjalan, dan dilewati juga bila schedule `*/5`
terbukti sehat (run schedule terakhir < 15 menit). Kedua rem itu (beserta
input `full_scan` dan `timeout-minutes: 15`) ada di **`daily-effort-5menit.yml`**
dan menunggu disalin ke `.github/workflows/daily-effort.yml` lewat UI GitHub —
berkas workflow tidak bisa ditulis bot (`git push` ditolak 403 `refusing to
allow a GitHub App to create or update workflow`); selama belum disalin, cron
terpasang tetap jalan normal karena scanner menerima `--scope` lama sebagai
alias. Schedule GitHub bersifat
**best-effort** — run bisa telat/dilewati (pada `*/15` pernah terukur ±2 jam)
— jadi yang menjaga ritme adalah chain dispatch. Lihat `DEPLOY.md` untuk cara
memverifikasi kadens nyata, memperlambat lane Solana, atau mengembalikan
keseluruhan kadens ke 15 menit.

## Kunci konfigurasi

| Variabel / konstanta | Isi |
|---|---|
| `HELIUS_API_KEY` | API key Helius untuk data holder |
| `GITHUB_TOKEN` | Token GitHub (push watchlist + snapshot) |
| `GITHUB_REPO`, `GITHUB_REF` | default `lparmycalprut/wallet-depth`; scanner memakai branch aktif |
| `WATCHLIST_FILE`, `HOLDER_STATUS_FILE` | default `watchlist.json`, `holder_status.json` |
| `HOLDER_STORE_BACKUP` | `1` (default) — `0`/`off` mematikan pull+push backup durable store (dev/offline; dipakai suite tes) |
| `DAILY_EFFORT_PATH` | default `daily_effort.json` (cache harga/volume DexScreener) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Alert Telegram (opsional) |
| `MAX_HOLDERS_PER_TOKEN` | FULL 100.000 (cron sejak 2026-09-05 & tombol "Scan holder FULL"), 2.000 (tombol scan watchlist di app.py) |
| `MIN_HOLDERS`, `MIN_WALLET_DEPTH_PCT` | 40, 75% — ambang minimum Holder Analytic |
| `MAX_HOLDER_HISTORY`, `MAX_HOLDER_TOKENS`, `MAX_WALLETS_PER_TOKEN` | 1200, 120, 800 — batas store |
| `EARLY_DUMP_STEP_PCT` | **0.02** — langkah delta satu-satunya notifikasi Telegram (⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE); tiap kelipatan 0,02% MC di atas patokan watchlist |
| `FAST_BUCKET_SEC` = `EARLY_DUMP_RESEND_SEC` | 300 s — bucket event id + jeda minimum kirim per token |
| ~~`DUMP_THRESHOLD_PP`~~ dll. | **dihapus 2026-09-11**: ambang rule lama (0,25/0,50/1,00 pp), gerbang volume (2,0×/1,5×), skor konfirmasi (0,70/0,80/0,50) dan `MIN_RESEND_SEC` tidak ada lagi |
| `VOLATILITY_WINDOW_HOURS`, `HIGH_VOLATILITY_STDDEV_PCT` | 4, 3.0 — `holder_history` (metrik, bukan gerbang lagi) |
| `BASELINE_HOURS`, `MIN_BASELINE_HOURS` | 168, 24 — `alert_context` (baseline volume 7 hari) |
| `MAX_BACKUP_BYTES`, `DURABLE_CACHE_TTL` | 3.500.000, 600 — `holder_history` (budget backup `.gz`, cache pull UI) |
| `HELIUS_USAGE_TTL_SEC` | 300 — cache status/sisa kredit key Helius di panel 🧾; `HELIUS_USAGE_PROBE=0` mematikan probe sama sekali (suite tes) |
| `MAX_POINTS` | 1008 — batas titik mentah per token; ±3,5 hari pada densitas LP 5 menit, 168 hari pada lane biasa 4 jam (grafik UI tetap di-resample per bucket 4 jam) |
| `DUST_BEST_PCT`, `DUST_BEST_MIN_HOLDERS`, `DUST_BEST_MIN_TVL_USD` | 0.1, 40, 10000 — badge BEST POOL (strict `< 0,1%`) + guard data holder minimal + TVL pool minimal |
| `DUST_SCAN_HIDE_PCT` | 0.1 — Scan Meteora menyembunyikan pool dust `> 0,1%` MC (`should_hide_dust`) |
| `DUST_BEST_LABEL` | `BEST POOL` — label badge (tampil apa adanya) |
| `BEST_TOP10_MAX_PCT` | 20.0 — 🏆 Scan Best Pool Meteora: Top10 holder token base **`>= 20%` tidak ditampilkan** (`row_top10_over`, batas di sisi buang sesuai *"jika ada top 10 >= 20% jangan tampilkan"*; `None` = lolos, tampil `—`) |
| `BEST_FEE_TVL_MIN` | 30.0 — 🏆 Scan Best Pool Meteora: **Fee/TVL (`fee_active_tvl_ratio`) di bawah 30% tidak ditampilkan di tabel hasil** (`row_fee_tvl_under`; inklusif di sisi tampil — tepat 30,0% lolos; permintaan user 2026-09-23 *"Fee/TVL minimal 30%, dibawah itu jangan show"*). Gugurnya masuk `hidden_rows` + tombol "▶ N pool dilewati", **bukan** dibuang total seperti Top10/volat/LPs; dicek sesudah ambang F/V. Hanya card Best Pool — `filter_regular_rows` Scan Meteora regular tidak ikut |
| `BEST_FV_HIDE_MIN` | 2.0 — 🏆 Scan Best Pool Meteora: **F/V di bawah 2× dibuang total** (`row_fv_under_hide`, dipanggil `row_best_dropped`; permintaan user 2026-09-24 *"jangan tampilkan sama sekali pool yang F/V nya kurang dari 2 di pool yang dilewati atau dimanapun"*). Tidak masuk tabel hasil, tidak masuk `hidden_rows`/`hidden_metric`/tombol "▶ N pool dilewati", tidak ikut rekap alasan; counter audit `dropped_fv`. Batas eksklusif di sisi buang — tepat 2,0× masih boleh tampil di "dilewati"; tanpa angka F/V (metrik hilang, volatility 0) **bukan** "kurang dari 2". Hasil scan lama di `session_state`/cache ikut bersih saat render (tanpa scan ulang). Hanya card Best Pool |
| `BEST_VOL_SHOW_MIN` / `MAX` | 1.0 / 10.0 — 🏆 Scan Best Pool Meteora: volatility **di luar** window ini gugur, dua-duanya inklusif (`row_volatility_gap`; V = 0 tetap punya alasan sendiri = dibuang total) |
| `BEST_FV_30M_MIN` | 1.0 — **mati** sejak 2026-09-16 (scan 30M dihapus); konstanta dibiarkan ada supaya percobaan menghidupkan lane lama lewat konstanta tetap gagal — di-pin `test_saringan_lama_tetap_mati` |
| `MIN_TOTAL_LIQ_USD`, `MIN_LABEL` (`gmgn_liquidity.py`) | 500000.0, `$500K` — 🏆 Scan Best Pool Meteora: **ambang WARNA** angka likuiditas GMGN di kolom RugCheck (`liq_color`: `> $500K` → `LIQ_GREEN_COLOR` hijau, `< $500K` → `LIQ_RED_COLOR` merah, sisanya tanpa warna). Saringannya sendiri dicabut 2026-09-17 malam — `row_gmgn_gap` selalu ``None``. **Dulu $1M** (2026-09-17 pagi) → mengosongkan tabel karena PAID saja hanya $884.912; angka terukur itu di-pin `tests/test_gmgn_liquidity.py::AmbangTest`. Teks UI/log membaca `meteora_screener.gmgn_min_label()`, jadi satu konstanta ini saja yang perlu diubah |
| `JUPITER_SAFEGUARD_FILTERS` | `base_token_has_critical_warnings=false&&quote_token_has_critical_warnings=false` — prepend di `best_filter_by()` saja (`safeguard=False` untuk mematikan) |
| `POOL_MIN_LIQ_USD`, `POOL_SHARE_MIN_PCT`, `BIG_POOL_SHARE_PCT` | 10000, 25.0, 10.0 — tiga catatan "metode tambahan" `rugchecker.py` (kedalaman pool, share likuiditas, konsentrasi pasar) |
| `CACHE_TTL_OK`, `CACHE_TTL_FAIL`, `CACHE_MAX_ENTRIES`, `WORKERS` | 1800, 300, 400, 6 — cache berkas `rugchecker.py` + paralelisme |
| `LP_GREEN_MIN_LP`, `LP_GREEN_COLOR` | 100.0 (strict `>`), `#16a34a` — kolom **LPs** hijau di 🏆 Scan Best Pool |

Ambang notifikasi + dedup ada di `telegram_alerts.py`, metrik volatilitas di
`holder_history.py`, dan pengambilan konteks pasar (baris info +
`market_signal`) di `alert_context.py`.

## Pengujian

```bash
# -s tests -t . membuat unittest meng-import paket test sebagai `tests.*`,
# sehingga `tests/__init__.py` (kill-switch offline alert-settings/backup) aktif.
python -m unittest discover -s tests -t .
python -m py_compile holder_history.py holder_chronology.py meteora_screener.py \
  holder_analysis.py holder_status.py telegram_alerts.py alert_context.py \
  lp_watchlist.py core.py app.py scripts/scan_holders.py \
  watchlist.py watchlist_detail.py accumulation.py
```

## Sinkronisasi watchlist non-blocking

Tombol ➕ / ✕ / 📋 di card watchlist (Solana + Chart LP Meteora)
**tidak lagi menunggu GitHub** sebelum tabel berubah. Jalur lama menarik
remote dua kali dalam satu klik: `remove_from_watchlist()` →
`_load_and_merge()` (pull: sampai 3 GET × timeout 10 dtk) → `save_watchlist()`
→ `_github_push()` (GET+PUT × 3 percobaan, timeout 15 dtk). Diukur dengan stub
RTT 0,8 dtk: **2,40 s** per klik, 3 panggilan HTTP di jalur klik, dan
membengkak sampai sekitar dua menit saat API lambat (retry + backoff) —
itulah keluhan "hapus dari watchlist kurang responsif".

Sekarang (flag `background=True` yang dipakai semua jalur UI):

1. state dibaca **lokal** (`_load_and_merge(local_first=True)`: cache
   `_REMOTE_CACHE` → file watchlist), tanpa HTTP;
2. perubahan ditulis ke file lokal + **journal** `watchlist_pending.json`
   (kontrak lama: journal selalu ditulis sebelum write/push apa pun);
3. cache remote di-*seed* dengan hasil baru → render ulang langsung menampilkan
   state benar dan **tidak** pull lagi (`_CACHE_TTL` naik 15 → 60 detik);
4. commit ke GitHub dijalankan di **thread daemon** (`_queue_github_push`),
   satu worker per file watchlist; job terbaru menimpa job lama, jadi klik
   cepat beruntun hanya menghasilkan satu commit final;
5. journal dibersihkan **hanya** setelah commit sukses — kegagalan apa pun
   membuat operasi tetap tertunda dan di-flush oleh `load_watchlist()`
   berikutnya (yang otomatis melewat flush inline selama worker masih jalan,
   supaya tidak balap 409).

Hasil terukur setelah perubahan: **1,4 ms** untuk klik + 0,9 ms untuk render
ulang, 0 panggilan jaringan di jalur klik. Badge kecil di kepala card
menunjukkan statusnya: `🔄 sinkron…` (masih dikirim) atau `⚠️ belum sinkron`
(commit terakhir gagal; lihat `watchlist.push_status()`).

Catatan durability: filesystem Streamlit Cloud ephemeral, jadi window antara
klik dan commit adalah window risiko — sebelumnya window itu sepanjang
percobaan push (bisa puluhan detik saat API macet), sekarang ±0,4–2 dtk.
Perubahan yang belum ter-commit hilang bila proses mati di dalam window itu,
persis seperti push yang gagal.

### 🗑️ Hapus semua (watchlist biasa saja)

Di kepala card **📋 Watchlist — Analisa Holder (Dust)**, di sebelah pilihan
"Urutkan baris watchlist", ada tombol **🗑️ Hapus semua**. Tombol ini membuka
popover konfirmasi yang menyebut jumlah token yang akan dihapus; baru setelah
**Ya, hapus N token** diklik seluruh watchlist biasa dikosongkan lewat
`watchlist.remove_many_from_watchlist()` — **satu** tulis journal + **satu**
commit GitHub di latar belakang (bukan N klik ✕). Scope-nya **hanya** token
Solana non-LP (`manual`/`degen`, termasuk token yang dipantau Pre-Pump
Screener): **Chart LP Meteora tidak ikut terhapus**.
History holder yang sudah tercatat tidak dihapus; snapshot cron berikutnya
otomatis membuang token yang sudah tidak ada di watchlist. Tombol tidak
ditampilkan bila card sudah kosong.

## Scan manual vs snapshot cron

Tombol **🔄 Scan holder FULL token ini** di halaman Holder Analytic menulis
titik baru ke `holder_history.json` (store) tetapi **tidak** mempublish
`holder_status.json` — publish hanya dilakukan cron / *Scan holder watchlist*,
dan `snapshot_status()` membangun `tokens` dari analyses yang diberikan saja
(tidak merge), jadi publish satu token akan menghapus token lain dari
dashboard. Supaya tidak ada dua angka berbeda untuk satu token (kartu metrik
dari snapshot cron, grafik dari store), UI memakai
`holder_status.apply_manual_scan()`: hasil scan manual disimpan ringkas di
`st.session_state[MANUAL_SCAN_KEY]` lalu dioverlay ke snapshot bila
`analyzed_at`-nya tidak lebih tua. Kartu metrik, badge HATI-HATI/BAHAYA,
watchlist, dan Chart LP lalu membaca angka yang sama dengan grafik, dan
caption menandai *scan manual barusan*. File snapshot tidak disentuh.

**Scan manual sejak 2026-09-11 juga mengirim alert sesuai lane.** Jalur
Meteora manual di `app.py` mengambil snapshot fee/volatility dan memakai rule
`meteora_watchlist.py` (24h quotient turun ≥30%; 30m volatility > fee), tanpa
`process_holder_alerts`/alert dust. Rule holder lama
(`process_holder_alerts`) tidak lagi punya pemanggil sejak card watchlist
Robinhood/biasa dan lane cron-nya dihapus (2026-09-15).

## Backup store holder (durable)

Runner GitHub Actions dan Streamlit Cloud memakai filesystem **ephemeral**:
`holder_history.json` lenyap setiap run/restart, jadi baseline scan FULL,
kohort beku, state dedup alert, dan kronologi wallet tidak pernah bertahan.
Store sekarang dibackup penuh ke ref `holder-live` sebagai
**`holder_history.json.gz`** (gzip + JSON compact via Contents API base64):

- **cron** (`scripts/scan_holders.py`): `pull_holder_history()` →
  `merge_stores(lokal, durable)` → `seed_from_status()` (jaring kedua) →
  scan → publish snapshot → `publish_holder_history(..., keep_mints=watchlist
  LP)`. **Sejak 2026-09-07 payload backup dibatasi token lane LP aktif**
  (`holder_history.restrict_store_to_mints`): token watchlist lama yang sudah
  tidak di-scan cron tidak ikut di-push ulang tiap 5 menit. Terukur pada store
  live (81 token, hanya 1 token LP aktif): **2.135.084 → 10.050 byte gzip
  (−99,5%)**, jadi riwayat branch `holder-live` tidak lagi menampung ±600 MB
  blob per hari. Store lokal (`holder_history.json`) tetap penuh; yang
  dibatasi hanya byte yang naik ke GitHub, dan jumlah token yang dibuang
  dilaporkan sebagai `tanpa N token lama` di log run. Backup gagal hanya
  mencetak `WARN` + `backup=GAGAL (...)` di log; run tidak jadi merah.
- **UI** (`app.py`, `pages/5_🧮_Holder.py`): `load_durable_holder_history()`
  = `merge_stores(durable, lokal)` — **store lokal menang** bila timestamp
  seri supaya scan manual yang baru tidak ditimpa backup lama; hasil pull
  di-cache 600 detik (`DURABLE_CACHE_TTL`).

| Data | `holder_status.json` (snapshot) | `holder_history.json.gz` (backup) |
|---|---|---|
| Dust per token, `holders`, `market_signal` | ✅ | ✅ |
| Titik grafik 4 jam | ringkas (`history`) | penuh (`points`, ≤84) |
| Balance alert `baseline`/`rolling`, `sent_event_ids` | **jumlah** | peta penuh |
| Kohort Crab+Fish | **jumlah wallet** | peta balance penuh |
| Kronologi wallet | **jumlah** + sampel movements (≤20/interval, ≤12 interval) | penuh |
| Baseline scan FULL (`depth`, buckets) | ❌ | ✅ (dibuang paling akhir) |

Perampingan snapshot (terukur pada 36 token live): **2,87 MB → 0,30 MB
(−90%)** — `alert_state` 1.850.768 → 10.695 B, `cohort` 236.345 → 1.890 B,
`chronology` hampir tetap (13.104 → 13.032 B, movements sampel dipertahankan).
Store penuh 36 token = 15,05 MB JSON compact → **577 kB gzip (26×)**, jauh di
bawah `MAX_BACKUP_BYTES` 3,5 MB dan di bawah batas PUT Contents API yang sudah
terbukti (2,85 MB), jadi `prune_store_for_backup()` praktis tidak pernah
terpicu. Bila perlu, pembuangannya berjenjang: movements interval lama →
interval di luar 6 terbaru → peta wallet kronologi → `points[].buckets` →
titik di luar 42 terbaru → `latest_detail`.

Pertumbuhan repo **tidak bertambah**: blob baru per run ±655 kB (snapshot
gemuk, zlib) → ±635 kB (snapshot ramping 21 kB + backup gzip 613 kB yang sudah
tak termampapkan lagi). Pada cron `*/15` itu ±61 MB/hari, sebelumnya ±63
MB/hari.

Analisis bersifat heuristik dan bukan saran keuangan.
