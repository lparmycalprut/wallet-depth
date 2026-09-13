# Wallet Depth — Holder Analytic (Dust)

Wallet Depth memantau token Solana dan berfokus pada **analisa holder
dust** sebagai jejak dump, plus **Scan Meteora DLMM**. Cron holder dapat
mengirim alert Telegram khusus perubahan dust; sinyal lama seperti silent
accumulation 12 jam dan reversal tetap tidak digunakan.

## Halaman

- **Halaman utama**: **🌊 Watchlist Meteora** (dulu "Chart LP") berdampingan
  dengan **🦅 Watchlist Robinhood** (LP) dalam grid 2 kolom, di bawahnya
  **🏆 Scan Best Pool Meteora** (sejak 2026-09-10; **full-width** sejak
  2026-09-11 — "jangan dibuat grid lagi", dulu menempel di bawah card
  Meteora di dalam grid) dan **🛰 Scan Holder Solana / Robinhood** (dulu
  "Scan Holder Khusus — Helius / Robinhood") — keduanya full-width.
  **🦅 Scan Best Robinhood Coin** (2026-09-10) **diparkir di halaman temp
  (📦) sejak 2026-09-11** — "belum berfungsi": listing GMGN Robinhood Chain
  **volume 6 jam terakhir** → hanya tampilkan **top 10 holder < 30%** dan
  **dust ≤ 0,05% MC** (dust dari Blockscout), urut **dust % MC terkecil** lalu
  **volume 6 jam terbesar**; pernah **Dexboost** = poin tambah (badge 🚀).
  Baris: 📋 copy CA dan ⭐ tambah ke **Watchlist Robinhood** LP di halaman
  utama. Detail
  karakteristik tiap card/section
  bukan caption panjang lagi — jadi **tooltip** yang muncul saat kursor
  digeser ke teks judulnya (sejak 2026-09-10; **🏆 Scan Best Pool Meteora**
  menyusul ke tooltip di hari yang sama, **🦅 Scan Best Robinhood** pada
  2026-09-11 — sejak itu badan card mana pun hanya berisi rekap angka hasil
  scan). 2026-09-11 juga menghapus caption yang menulis ulang ANGKA ambangnya
  (RH: "dust > 0,05% MC = 2, top 10 holder ≥ 30% = 1, honeypot = …"; toggle
  Auto-refresh halaman utama; caption 🌊 Scan Meteora Pool di /temp) dan teks
  abu-abu penjelasan auto-refresh — semuanya sudah ada di tooltip yang sama.
  Scan Best Robinhood menunggu **semua** kandidat sampai
  selesai — budget waktu 300 detik yang dulu membuang token ber-holder
  puluhan ribu sudah dihapus (2026-09-10). Paling bawah: **🧾 Log Aktivitas**
  — sejak
  2026-09-10 menampilkan **sisa kredit key Helius** di samping status pool key
  Blockscout.
- **temp** (`/temp`, sejak 2026-09-09): **🦅 Watchlist Robinhood — Holder
  Dust** (biasa/non-LP), **📋 Watchlist — Analisa Holder (Dust)**,
  **🌊 Scan Meteora Pool** (dipindah dari halaman utama sejak 2026-09-10 —
  ⭐-nya tetap memasukkan token ke Watchlist Meteora di halaman utama),
  **🦅 Scan Best Robinhood Coin** (diparkir dari halaman utama sejak
  2026-09-11 — "belum berfungsi"; ⭐-nya tetap memasukkan token ke
  **Watchlist Robinhood** LP di halaman utama), dan **🔍 Temukan Token**
  (Trending/Degen). Dibuka lewat tautan **📦 temp**
  di halaman utama atau sidebar; tersedia tautan kembali ke halaman utama.
  Fitur sementara diparkir, **bukan dihapus**: data, form tambah, scan manual,
  dan tombol pindah/hapus token tetap tersedia. Scan manual hanya memproses
  lane pada card tersebut; snapshot lane lain tetap dipertahankan.
- **Holder**: analisa detail satu token dan scan FULL/kronologi.

Pemindahan halaman tidak mengubah file watchlist, source token, jadwal cron,
atau setelan Telegram. Robinhood LP tetap di halaman utama, bukan di temp.

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
   Lane LP (Chart LP Meteora + Robinhood LP) digambar per bucket **5 menit**
   (`resample_5m`, `LP_INTERVAL_SEC`); watchlist biasa dan halaman Holder
   tetap per bucket 4 jam (`resample_4h`).
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
   dipakai bersama oleh cron dan scan manual. Rule **EARLY DUMP** berbasis dust
   tetap berlaku hanya untuk lane non-Meteora yang masih menggunakan
   `process_holder_alerts` (watchlist biasa/Robinhood), dan tidak boleh
   tercampur ke card Watchlist Meteora.

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
Format ini sama untuk semua lane (Watchlist Meteora, Robinhood LP, watchlist
biasa).

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
diketahui; `🦆 rh-scan` / `🌏 Blockscout` untuk Robinhood) adalah
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
selalu ter-encode. Token Robinhood memakai **🦆 rh-scan, 🦆 DexScreener
Robinhood, 🌏 Blockscout**, bukan link Solana. Bila mint kosong, link
dilewati. Bila event LP membawa pool address Meteora, ditambahkan
**🌊 Meteora + 🦅 HawkFi**; cron belum menyimpan pool address.

Transport tetap mengirim teks literal (tanpa `parse_mode`), sehingga nama
token dengan karakter HTML/Markdown tidak merusak pesan. Judul exit diberi
native entity `bold` dan setiap label link diberi entity `text_link`,
keduanya dengan offset/panjang **UTF-16** (emoji 🚨 / 🔗 = dua unit).

## Sumber data

**Helius** = sumber utama holder (DAS `getTokenAccounts`). **GMGN** hanya
listing Trending/Degen + fallback. **Meteora** pool-discovery API untuk
Scan Meteora. Harga/MC/volume/`txns` dari DexScreener. Candle hourly & harian
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

Scan Holder Solana / Robinhood (halaman utama; dulu "Scan Holder Khusus")
menerima **dua chain**: CA Solana
(base58) → Helius DAS, CA **Robinhood Chain** (`0x…`) → **Blockscout**
(CSV export, tanpa limit) lewat `robinhood_holders.scan_token_holders` — hasil (bar chart
Wallet Depth + tabel) dirender sama. Jalur Solana dan cron butuh
`HELIUS_API_KEY` (config / env / Streamlit secrets). Tanpa key, jalur
Solana memakai fallback GMGN.

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
(`app.scan_holder_tooltip()`), bukan caption.

Jalur Robinhood **sebaiknya** diberi `BLOCKSCOUT_API_KEY` (env /
`blockscout_api_key` di `config.json` / Streamlit secrets; key gratis
dari <https://dev.blockscout.com>, tanpa kartu). Sejak 2026-09-08
instance publik `robinhoodchain.blockscout.com` memasang bot-protection:
request dari server (Streamlit Cloud, GitHub runner) sering dijawab
**HTTP 403** "Just a moment…" serentak untuk `getToken`, CSV export, dan
REST v2 — dulu terbaca sebagai *"Scan tidak menghasilkan holder. Pastikan
CA valid…"* padahal CA-nya sah. Dengan key, semua request lewat **PRO
API** `https://api.blockscout.com/4663/…` (header `Authorization:
Bearer`, path & bentuk respons identik dengan instance publik; free tier
5 RPS / 100K kredit per hari ≈ 3.000–5.000 request). **Beberapa key**
boleh dipasang sekaligus (`BLOCKSCOUT_API_KEYS`, dipisah koma) — kuota
free tier dihitung per akun, jadi key dari akun berbeda menaikkan
plafon; request dibagi bergantian dan key yang ditolak / kreditnya
habis (401/402/403/429) diparkir sementara lalu request pindah ke key
berikutnya, key aslinya tidak pernah masuk log (hanya `key#N`). Tanpa key modul
tetap mencoba instance publik dengan TLS browser (`curl_cffi`, profil
dirotasi saat 403) lalu `requests` biasa; bila semuanya ditolak hasil
pulang dengan `blocked: True` + satu kalimat yang menyebut 403 dan cara
memasang key (bukan menyalahkan CA). Rute yang dipakai terlihat di
`source` (`blockscout-csv@pro` / `@public`) dan caption UI.

## 🌊 Watchlist Meteora (watchlist pool terpisah)

Card kiri atas dashboard berisi pool yang ditambahkan dari **Scan Meteora
Pool** (⭐) atau form manual (`source=meteora`). Setiap entry menyimpan
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
  Meteora** atau radio target di halaman temp. Pool yang ditambahkan dari scan
  membawa baseline metric otomatis.

## 🏆 Scan Best Pool Meteora (halaman utama, sejak 2026-09-10)

Listing pool Meteora khusus halaman utama. **Penempatan (2026-09-11):**
card dirender **full-width** di bawah grid 2 kolom watchlist — permintaan
user "jangan dibuat grid lagi" (2026-09-10 dulu menempel di bawah 🌊
Watchlist Meteora di dalam grid). **Kriteria diganti total
2026-09-11** mengikuti query UI Meteora (semua ambang hidup di konstanta
`meteora_screener.BEST_*`):

- **Query API Meteora** (24 jam, `category=top`, `page_size=50`):
  `pool_type=dlmm && fee_pct>=2 && active_tvl>=50000` — tier fee dan active
  TVL disaring **oleh API**, jadi tidak diulang sebagai saringan layar.
- **Saringan layar** — tinggal tiga (data hilang/`None` = gugur):
  | Syarat | Ambang |
  |---|---|
  | Volume 24 jam | **≥ $1.000.000** (`BEST_VOLUME_24H_MIN`, 2026-09-12 — "minimal volume 24 jam adalah 1M, dibawah itu jangan di show"; tepat $1M lolos) |
  | Dust holder | **< 0,05% MC** (`BEST_DUST_MAX_PCT`, ketat `<`) |
  | Volatility | **≥ 2%** (`BEST_VOLATILITY_MIN` — "minimal 2%", 2,0% lolos) |
  Saringan lama (active TVL > 10K, fee/active TVL > 20%, top 10 holder
  < 30%, total LPs > 20) **dihapus**; Top10 + LPs tetap tampil sebagai
  informasi tapi tidak lagi menyaring.
- **Urutan baris**: **volume 24 jam / active TVL** terbesar
  (`volume_active_tvl_ratio` — angka persen yang dikirim API Meteora, sejak
  2026-09-13) → **dust % MC terkecil** → simbol alfabetis. Kunci dust
  dibulatkan ke presisi tampilan (3 desimal) supaya dua pool yang di layar
  sama-sama "0,030%" dianggap seri. Baris tanpa angka dust paling bawah,
  apa pun rasionya. Rasio itu tampil di baris kecil kolom **Vol 24h**
  (`… · 1,647× A.TVL`) sehingga urutannya bisa diperiksa mata.
- **Volume 24 jam ≥ $1M** disaring **sebelum** holder di-fetch, jadi kuota
  Helius tidak terpakai untuk pool sepi. Pool volume ≥ $1M yang gagal
  volatility tetap di-scan holder: dust < 0,05% MC-nya masuk listing
  **disembunyikan** (tombol **▶ N disembunyikan** di card, urut
  volume/active TVL lalu dust). Listing utama tetap butuh volatility ≥ 2%
  juga.
- Kolom listing (detail fee / active TVL ada di sini): Token · MC · **A.TVL** ·
  **Fee/TVL** (baris kecil = fee 24 jam dalam USD + tier fee) · **Vol 24h**
  (baris kecil = Δ volume 24 jam, hijau naik / merah turun, plus rasio
  volume/active TVL) · Volat · Top10 ·
  LPs ·
  Dust (wallet) · Dust %MC (3 desimal) · Pool (Meteora DLMM + HawkFi) · ⭐ —
  hover tiap angka memberi angka penuh + keterangan apakah metrik itu kunci
  urut atau hanya informasi.
- Tombol **⭐** memasukkan token ke card **🌊 Watchlist Meteora** di halaman
  utama (`source=meteora`, sama seperti card temp) — token lalu ikut di-scan
  cron ±5 menit lengkap dengan grafik perubahan dust holder.
- **Tanpa caption rule di badan card** (2026-09-10): seluruh penjelasan
  filter + urutan + tombol hanya tampil sebagai **tooltip judul** (kursor di
  atas tulisan "🏆 Scan Best Pool Meteora"). Teksnya dibangun
  `best_pool_ui.best_pool_tooltip()` dari konstanta `meteora_screener.BEST_*`,
  jadi angka di tooltip tidak mungkin lagi beda dari rule yang jalan;
  mengubah ambang = tooltip ikut berubah.

## 🌊 Scan Meteora Pool (halaman temp sejak 2026-09-10)

Regular scan mengambil dua listing pool-discovery secara berurutan:
**24 jam (`timeframe=24h`) lalu 30 menit (`timeframe=30m`)**, dengan
`category=top`, `pool_type=dlmm`, dan `active_tvl≥50000`.

- **24 jam**: pool tidak ditampilkan bila
  `volatility ≥ fee_active_tvl_ratio`. Pool dengan
  `fee_active_tvl_ratio ≥ 5 × volatility` diberi catatan **SAFE LP**; pool
  fee-dominant lain tetap bisa tampil sebagai LP 24H.
- **30 menit**: hanya pool dengan `fee_active_tvl_ratio > volatility` yang
  ditampilkan sebagai **HIGH RISK LP (PANTAU)**.
- **Urutan**: lane 24h selalu lebih dahulu, lane 30m sesudahnya; di dalam lane
  quotient `fee_active_tvl_ratio ÷ volatility` terbesar lebih dahulu. Dust
  `%MC` tetap dicatat/ditampilkan sebagai data, tetapi tidak pernah menjadi
  kunci urut regular scan. Render UI tidak melakukan sorting kedua.
- Hasil menampilkan source/timeframe, fee/active TVL, volatility, klasifikasi,
  TVL, dan dust holder. Filter dust lama `DUST_SCAN_HIDE_PCT` tetap berlaku;
  holder tanpa bukti tidak dipalsukan menjadi `0,000%`.
- Pool tanpa sisi memecoin (SOL/USDC/USDT) tetap dilewati sebelum holder
  di-fetch. Tombol ⭐ menyimpan source/timeframe, pool address, dan baseline
  fee/volatility ke Watchlist Meteora.

**Scan Best Pool Meteora** di halaman utama tetap memakai query, filter, dan
sorter khususnya sendiri; perubahan regular scan ini tidak mengubah pipeline
Best Pool.

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
  🌊 Watchlist Meteora dan 🦅 Watchlist Robinhood (LP + biasa) — ketiga
  tabel kini 8 kolom, kolom ke-4 adalah **Awal Masuk**;
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
  ikut ditulis. Berlaku di semua card watchlist (Meteora LP, Robinhood
  LP/biasa, watchlist Holder) karena semuanya memakai expander yang sama.

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
| `meteora_screener.py` | Regular listing DLMM 24h lalu 30m, active TVL ≥ 50K, filter/classification fee-versus-volatility, sort quotient tanpa dust, enrich holder; Best Pool tetap terpisah |
| `holder_analysis.py` | Fetch holder Helius/GMGN, klasifikasi real/dust/mid |
| `robinhood_holders.py` | Robinhood Chain (chain 4663): holder **Blockscout** — CSV export (utama, seluruh daftar dalam 1 request) → REST v2 keyset → legacy RPC `offset=400`; decimals/supply, analisa dust + `scan_token_holders` (padanan EVM Scan Holder Solana / Robinhood) sama dengan Solana |
| `robinhood_watchlist.py` | Watchlist/path Robinhood: `watchlist_robinhood.json`, status & history terpisah, scan + publish best-effort |
| `solscan_holders.py` | Kalkulasi wallet_depth (bucket & tier) |
| `helius_holders.py` | Scan Holder Solana satu token (Solana/Helius) + bar chart |
| `holder_status.py` | Snapshot dashboard ramping (ref `holder-live`) + history ringkas + transport GitHub (JSON & byte/gzip) |
| `core.py` | Config/key Helius (pool round-robin; placeholder `PASTE-API-KEY-…` disaring, Streamlit secrets menang atas `config.json`), pasar DexScreener, candle hourly/harian GeckoTerminal, **status + sisa kredit key Helius** (`helius_key_status` / `helius_usage_summary`) dan hitungan request lokal |
| `activity_log.py` | Ring buffer kejadian semua card (400 entri, dedup 60 dtk, level `action` = merah bold) + panel **🧾 Log Aktivitas**: status pool key PRO Blockscout & **sisa kredit Helius** |
| `best_pool_ui.py` | Card **🏆 Scan Best Pool Meteora** (halaman utama, full-width di bawah grid 2 kolom sejak 2026-09-11) — listing + saringan `meteora_screener.BEST_*`, ⭐ → Watchlist Meteora, detail = tooltip judul |
| `robinhood_best_scan.py` | Card **🦅 Scan Best Robinhood Coin** (diparkir di halaman temp 2026-09-11, "belum berfungsi") — rank GMGN `swaps/6h` + dust Blockscout, badge 🚀 Dexboost, 📋 copy CA, ⭐ → Watchlist Robinhood LP di halaman utama; semua kandidat ditunggu (tanpa budget waktu) |
| `scripts/scan_holders.py` | Cron **lane LP saja** (run ±5 menit): snapshot metric Meteora + holder/history tanpa alert dust Meteora, alert holder lama hanya lane Robinhood, publish status + backup |
| `telegram_alerts.py` | Alert holder-dust untuk lane non-Meteora: ⚡ EARLY DUMP TERJADI - GANTI WIDE RANGE (delta dust ≥ 0,02% MC), marker `alert_state["early_dump"]`, Telegram Bot API |
| `links.py` | Satu sumber URL eksternal: GMGN, DexScreener, Solscan, Meteora DLMM, HawkFi (HTML untuk UI, teks polos untuk Telegram) + slug halaman internal (`/Holder?mint=…`) |
| `page_router.py` | Router deep link: `?mint=`/`?page=` yang jatuh ke halaman utama dipantulkan ke halaman yang dituju (`st.switch_page`) |
| `trending_ui.py` | Listing Trending/Degen + Add All Watchlist |
| `pre_pump_screener.py` | 🚀 Pre-Pump Screener: 4 sinyal on-chain (gelombang add likuiditas + journal, konsolidasi holder, volume calm-before-storm, TX velocity), PUMP SCORE 0–10, kartu token, auto-refresh `st.fragment(run_every=300)` |
| `pages/4_📊_CVD.py` | Chart CVD harian |
| `pages/5_🧮_Holder.py` | Holder Analytic: dust, grafik 4 jam, kohort, kronologi FULL (satu-satunya halaman sejak 2026-09-07) |

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
`mint` / `ca` / `token` / `address` (CA Solana base58 atau `0x`+40 hex
Robinhood Chain) dan `page` (slug / nomor halaman / nama file). Nilai yang
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
| 🦅 **Watchlist Robinhood LP** (EVM/Blockscout) | tiap run = **±5 menit** | permintaan user: "percepat fetch watchlist robinhood menjadi 5 menit sekali" |
| 📋 **Watchlist biasa** (Solana non-LP & Robinhood `source=regular`) | **tidak di-scan cron** | dirampingkan 2026-09-07: "fokuskan ke holder scan untuk meteora dan robinhood saja … pencatatan lain tidak perlu" — tetap bisa di-scan manual dari dashboard |

Yang ikut dibuang bersama lane biasa: slot 4 jam + catch-up + bootstrap token
baru, `merge_status` (pewarisan baris token biasa ke
snapshot), pembacaan toggle **global** Telegram watchlist biasa per run, dan
token lama di backup durable — `publish_holder_history(..., keep_mints=watchlist LP)` hanya
men-push token yang memang di-scan (terukur pada store nyata: **2.135.084 →
10.050 byte** gzip, 81 token → 1 token LP aktif). Scan FULL (baseline immutable
+ kronologi wallet) tidak dijadwalkan lagi; jalankan manual bila perlu:
`python scripts/scan_holders.py --full`.

Harga yang dibayar: tiap run menarik holder penuh semua token Meteora dari
Helius dan ±30 halaman Blockscout per token Robinhood. Kalau kuota mulai ketat,
TIDAK perlu mengubah kode — set `LP_SCAN_RUN_MULTIPLIER: "3"` di langkah scan
pada workflow, lalu `lp_slot_due` menahan lane Solana di luar slot 15 menitnya
(log: `Rencana scan Meteora LP: … slot_lp=bukan`) sementara Robinhood LP tetap
tiap run. **Gate run ganda** `MIN_RUN_GAP_SEC` = **4 menit**, wajib di bawah
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
| `BLOCKSCOUT_API_KEY` | Key **Blockscout PRO API** (gratis di dev.blockscout.com) untuk holder Robinhood Chain; tanpa key modul memakai instance publik yang sejak 2026-09-08 sering menjawab 403 bot-protection. Alias: `BLOCKSCOUT_PRO_API_KEY`, `blockscout_api_key` di `config.json` / Streamlit secrets |
| `BLOCKSCOUT_API_KEYS` | Beberapa key PRO API dipisah koma/baris baru (digabung dengan `BLOCKSCOUT_API_KEY`, dedup). Round-robin; 401/403 parkir 60/5 mnt, 402 kredit habis parkir 30 mnt, 429 parkir sesuai `x-ratelimit-reset`. Alias `blockscout_api_keys` di `config.json` / secrets |
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

Ambang notifikasi + dedup ada di `telegram_alerts.py`, metrik volatilitas di
`holder_history.py`, dan pengambilan konteks pasar (baris info +
`market_signal`) di `alert_context.py`.

## Pengujian

```bash
# -s tests -t . membuat unittest meng-import paket test sebagai `tests.*`,
# sehingga `tests/__init__.py` (kill-switch offline Robinhood/backup) aktif.
python -m unittest discover -s tests -t .
python -m py_compile holder_history.py holder_chronology.py meteora_screener.py \
  holder_analysis.py holder_status.py telegram_alerts.py alert_context.py \
  lp_watchlist.py core.py app.py scripts/scan_holders.py trending_ui.py \
  watchlist.py watchlist_detail.py accumulation.py
```

## Sinkronisasi watchlist non-blocking

Tombol ➕ / ✕ / 📋 di card watchlist (Solana, Chart LP, dan Robinhood)
**tidak lagi menunggu GitHub** sebelum tabel berubah. Jalur lama menarik
remote dua kali dalam satu klik: `remove_from_watchlist()` →
`_load_and_merge()` (pull: sampai 3 GET × timeout 10 dtk) → `save_watchlist()`
→ `_github_push()` (GET+PUT × 3 percobaan, timeout 15 dtk). Diukur dengan stub
RTT 0,8 dtk: **2,40 s** per klik, 3 panggilan HTTP di jalur klik, dan
membengkak sampai sekitar dua menit saat API lambat (retry + backoff) —
itulah keluhan "hapus dari watchlist Robinhood kurang responsif".

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
Screener): **Chart LP Meteora dan kedua card Robinhood tidak ikut terhapus**.
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
`process_holder_alerts`/alert dust. Jalur Robinhood dan watchlist biasa tetap
memakai `process_holder_alerts(..., advance_anchors=False)` untuk event holder
lama; cron memilih kadens dan baseline masing-masing lane.

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
