# Wallet Depth — Holder Analytic (Dust)

Wallet Depth memantau token Solana dan berfokus pada **analisa holder
dust** sebagai jejak dump, plus **Scan Meteora DLMM**. Cron holder dapat
mengirim alert Telegram khusus perubahan dust; sinyal lama seperti silent
accumulation 12 jam dan reversal tetap tidak digunakan.

## Konsep

1. **Dust holder** — wallet murni dengan `0 < nilai ≤ $10`:
   - **dust % MC** = total nilai dust / marketcap × 100,
   - ≥ **0,5% MC** → **HATI-HATI** (badge kuning, peringatan dini),
   - ≥ **1% MC** → **BAHAYA** (disembunyikan dari Scan Meteora),
   - < **0,1% MC** + data holder valid (≥ 40 wallet) → badge **🏆 BEST POOL**
     di baris listing Scan Meteora (level AMAN tidak berubah — ini penanda
     kebersihan distribusi, bukan level bahaya). Nilai **== 0,1%** sengaja
     tidak dapat badge (butuh `< 0,1%`) dan juga tidak memicu alert
     EARLY DUMP (butuh `> 0,1%`), jadi kedua sinyal tidak tumpang tindih.
   Dust yang nambah pesat = holder sebelumnya sudah distribusi / bag
   merosot jadi sisa. **Catatan:** batas dust itu **$10 per wallet dalam
   USD**, jadi dust % MC *tidak* invariant terhadap harga — harga naik
   membuat wallet "lulus" ke >$10 (dust % MC turun walau tidak ada yang
   jual), harga turun mendorong wallet masuk dust (dust % MC naik). Baca
   angka ini bersama jumlah dust wallet.
2. **Chart LP — watchlist terpisah** — token yang ditambahkan dari **Scan
   Meteora Pool** (⭐) atau ditambah manual ke card itu dikumpulkan di card
   paling atas dashboard. Card ini menampilkan **grafik perubahan dust
   holder** (dust % MC + jumlah wallet dust per bucket 4 jam, garis ambang
   0,5% / 1%), sparkline, Δ poin persentase 4 jam & total, overlay semua
   token LP, plus tombol pindah card (📋 ↔ 🌊). Token LP tidak ditampilkan
   dua kali di watchlist holder biasa.
3. **Kohort mid-tier (Crab+Fish, $100–$10k)** — daftar address di-freeze
   4 jam, lalu diukur **sisa token** (bukan dollar) supaya dump harga
   tidak ketiru sebagai exit.
4. **Grafik 4 jam** — setiap scan mencatat titik ke `holder_history.json`,
   ditampilkan per bucket 4 jam (watchlist sparkline + halaman Holder).
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
7. **Alert Telegram holder dust** — membandingkan `dust_pct_mc` terbaru
   dengan anchor sekitar 4 jam sebelumnya menggunakan perubahan **poin
   persentase**:
   - naik minimal `+0.25` poin → indikasi dump;
   - turun minimal `-0.50` poin **dan** ada wallet lama yang saldo tokennya
     meningkat → kemungkinan akumulasi;
   - berubah minimal `±1.00` poin dari snapshot awal → alert pemeriksaan
     pergerakan wallet dust (membesar/keluar dust, jual habis/hilang,
     mengecil/masuk dust, atau wallet dust baru);
   - **khusus token pool** (Chart LP / `source=meteora`): dust
     **menyeberang naik di atas 0,1% MC** dibanding nilai run sebelumnya →
     **⚡ EARLY DUMP** (peringatan lebih awal untuk exit LP). Crossing +
     hysteresis: token baru dipantau tidak langsung mengirim, turun ke
     ≤ 0,1% = reset. Ulang maksimal 1× per bucket 4 jam dan hanya selama
     dust masih naik; dikirim **tanpa** gerbang volume keras (konteks pasar
     jadi info di pesan). Catatan: saat ini 0 token watchlist ber-source
     meteora — rule aktif begitu ada pool yang di-⭐ dari Scan Meteora.

   Perubahan dust baru menghasilkan **kandidat** sinyal: setiap kandidat
   harus lolos konfirmasi volume + harga + volatilitas dulu (bagian
   berikutnya) sebelum dikirim. Snapshot saldo dibatasi maksimum 300 wallet
   per anchor, event yang sukses dikirim dideduplikasi per bucket 4 jam
   **dan** ditahan minimal 1 jam antar alert sejenis.
8. **Watchlist Robinhood Chain (EVM)** — token yang ditambahkan dari form
   /kartu terpisah ke `watchlist_robinhood.json` dipantau dengan **rule
   holder dust yang sama** dengan Solana: holder diambil dari Blockscout
   (`robinhoodchain.blockscout.com`, chain id 4663), harga/marketcap dari
   DexScreener (`chainId=robinhood`), grafik 4 jam dan alert Telegram
   memakai aturan/aturan yang sama. Link card memakai rh-scan.com,
   DexScreener robinhood, dan Blockscout; watchlist, snapshot, dan history
   token disimpan terpisah dari `watchlist.json` / `holder_status.json`.
   Card **Robinhood LP** dan card **Chart LP** (Meteora) sama-sama di-scan
   cron tiap **±5 menit** sejak 2026-09-06 (sebelumnya 15 menit) supaya exit
   LP bisa lebih awal dan perubahan holder langsung kelihatan; **watchlist
   biasa** (Solana & Robinhood biasa) tetap ±4 jam — lihat **Cadens scan**.
   Aksi ➕ / ✕ / 📋 di card ini tidak menunggu GitHub lagi — lihat
   **Sinkronisasi watchlist non-blocking**.

## Konfirmasi volume & volatilitas (filter false positive)

Kandidat sinyal dust diperiksa silang terhadap pasar sebelum dikirim
(`telegram_alerts.validate_alert_with_volume`):

| Sinyal | Gerbang keras |
|---|---|
| **Dump** (dust naik ≥ 0,25 pp) | volume 4 jam ≥ **2×** rata-rata 7 hari **dan** harga ≤ **-1%** |
| **Akumulasi** (dust turun ≥ 0,50 pp + buyer) | volume 4 jam ≥ **1,5×** rata-rata 7 hari **dan** buy pressure > sell pressure |
| **Baseline shift** (±1 pp dari snapshot awal) | mengikuti arah perubahan: naik → aturan dump, turun → aturan akumulasi |

⚡ **EARLY DUMP** (token pool saja, crossing > 0,1% MC) sengaja **tidak**
dipakai gerbang di tabel ini — delta crossing ambang absolut 0,1% bisa jauh
di bawah 0,25 pp yang dirancang untuk gerbang dump. Volume/harga/volatilitas
tetap diambil (lazy) sebagai **konteks info** di pesan; tanpa data pasar,
pesan memuat `⚠️ TIDAK TERVERIFIKASI`.

`avg_volume_7d` = rata-rata volume **per window 4 jam** selama 7 hari, jadi
satuannya setara dengan `volume_4h` (bukan total volume harian).

**Skor konfirmasi (0–1)** — hanya dihitung bila gerbang keras lolos: `0,70`
dasar + hingga `0,15` kekuatan volume + hingga `0,10` kekuatan harga/tekanan
beli + `0,20` bila volatilitas 4 jam tinggi **dan** arah harga mendukung.
Ambang lolos **0,70**, naik menjadi **0,80** bila `price_stddev_4h > 3%`
(pasar sedang liar → butuh bukti lebih kuat). Volatilitas tinggi tanpa arah
harga yang mendukung tidak memberi bonus, supaya ambang 0,80 itu benar-benar
menyaring. Kandidat yang ditolak dicatat ke `alert_state.rejected_signals`
(maks 8 per token) dan ke log cron (`Dust signal rejected …`), jadi sinyal
yang terbuang bisa diaudit.

**Metrik volatilitas** — `holder_history.calculate_volatility_metrics`
memakai 16 candle hourly terakhir dan menghasilkan `price_stddev_4h` (sample
stddev close per jam, dalam % harga rata-rata), `price_range_4h`
((high−low)/rata-rata), `intra_hour_volatility` + `intra_hour_volatility_max`
(rentang dalam tiap jam), `price_change_4h_pct`, `volume_4h`, `missing_hours`
(candle bolong), dan `stale`. Metrik ini disimpan di `holder_status.json`
sebagai `tokens[mint].market_signal`, berdampingan dengan dust % MC.

**Biaya & sumber data** — candle hourly GeckoTerminal (168 jam) ditarik
**lazy**: hanya token yang punya kandidat sinyal, maksimal satu kali per run,
jadi scan 1 jam yang tenang tidak menambah request apa pun. Bila
GeckoTerminal gagal, konteks jatuh ke angka DexScreener yang **sudah** diambil
saat scan (`volume.h6` di-skala ke 4 jam, baseline dari `volume.h24`,
`priceChange.h6`, `txns` buys/sells) lalu ke `daily_effort.json` untuk
rata-rata volume 7 hari.

**Bila data tidak ada** (pool lebih muda dari 7 hari, API mati): alert **tetap
dikirim** dengan baris `Verifikasi volume: ⚠️ TIDAK TERVERIFIKASI` — indikasi
dump tidak boleh hilang senyap hanya karena sumber data sedang down. Set
`telegram_alerts.ALLOW_UNVERIFIED_ALERTS = False` untuk perilaku strict.

Alert yang lolos menyertakan rasio volume, perubahan harga, skor konfirmasi,
ambang yang dipakai, stddev 4 jam, **dan link token ke GMGN + DexScreener**
(`links.token_link_lines`) di pesan Telegram supaya alert bisa langsung
ditindaklanjuti. Bila mint tidak diketahui, kedua baris link dilewati (tidak
ada label menggantung).

## Format alert Telegram (contoh)

```text
🚨 INDIKASI DUMP — HOLDER DUST NAIK
Token: $WSOL
Dust sebelumnya: 0.90% MC
Dust terbaru: 1.24% MC
Perubahan: +0.34 poin persentase
Periode: ~4 jam
Verifikasi volume: ✅ volume 4 jam 2.50× rata-rata 7d (ambang 2.0×) · harga -3.20% · buy 62/sell 38
Skor konfirmasi: 0.79 (ambang 0.70) · stddev 4 jam 1.80%
Wallet saldo meningkat: 7
Pergerakan sampel wallet dust:
- Membesar / keluar dust: 4
- Jual habis / hilang: 1
- Keluar dust lainnya: 0
- Mengecil / masuk dust: 2
- Wallet dust baru: 3
- Masuk dust lainnya: 0
Waktu: 2026-09-03 22:11:17 WIB (15:11 UTC)
Mint: So11111111111111111111111111111111111111112
🔗 GMGN: https://gmgn.ai/sol/token/So11111111111111111111111111111111111111112
🦆 DexScreener: https://dexscreener.com/solana/So11111111111111111111111111111111111111112
```

Dua baris link terakhir dibangun `links.token_link_lines(mint)` — helper yang
sama dengan link 🔗GMGN/🦆Dex di tabel watchlist, jadi URL-nya satu sumber dan
selalu ter-encode (Telegram otomatis me-link URL polos).

Contoh alert **⚡ EARLY DUMP** (kind baru, token pool; tanpa blok pergerakan
wallet karena dibandingkan dari nilai dust saja):

```text
⚡ EARLY DUMP — DUST HOLDER NAIK DI ATAS 0.1%
Token: $LPDUMP
Dust sebelumnya: 0.04% MC
Dust terbaru: 0.42% MC
Perubahan: +0.38 poin persentase
Periode: sejak titik terakhir 2 jam lalu
Verifikasi: ℹ️ volume 4 jam 1.50× rata-rata 7d · harga -2.50% (info saja, tanpa gerbang volume)
Waktu: 2026-09-04 01:15:00 WIB (18:15 UTC)
Mint: LpMint11111111111111111111111111111111111
🔗 GMGN: https://gmgn.ai/sol/token/LpMint11111111111111111111111111111111111
🦆 DexScreener: https://dexscreener.com/solana/LpMint11111111111111111111111111111111111
```

Bila konteks pasar tidak tersedia, baris `Verifikasi:` berubah menjadi
`⚠️ TIDAK TERVERIFIKASI — data pasar tidak tersedia (info saja, early warning
tanpa gerbang volume)`. Bila pool address Meteora diketahui, ditambahkan
`🌊 Meteora:` + `🦅 HawkFi:` — cron **belum** bisa mengisinya karena
`watchlist.json` tidak menyimpan pool address (lihat PROGRESS).

Dua baris `Verifikasi volume` / `Skor konfirmasi` hanya muncul bila konteks
pasar berhasil diambil. Bila tidak, keduanya diganti satu baris:

```text
Verifikasi volume: ⚠️ TIDAK TERVERIFIKASI — data pasar tidak tersedia
(volume_4h, avg_volume_7d, price_change_pct) — sinyal dikirim tanpa
verifikasi volume
```

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

Scan Holder Khusus (halaman utama) dan cron butuh `HELIUS_API_KEY`
(config / env / Streamlit secrets). Tanpa key, fallback GMGN.

## Chart LP (watchlist Meteora terpisah)

Card paling atas dashboard, khusus token yang ditambahkan dari **Scan
Meteora Pool** (`source=meteora`):

- **Overlay** dust % MC semua token LP dalam satu grafik + grafik per token
  (garis dust % MC, batang jumlah wallet dust, garis ambang 0,5% & 1%).
- Per baris: MC, jumlah wallet dust, **Hold %MC** + badge
  (AMAN / HATI-HATI / BAHAYA), **Δ 4 jam** dan Δ total dalam **poin
  persentase**, sparkline 4 jam, tombol 🧮 Holder Analytic, 📋 pindah ke
  watchlist holder, ✕ hapus.
- Urut dari yang paling perlu diwaspadai (BAHAYA → HATI-HATI → AMAN, lalu
  dust % MC terbesar).
- Token LP **tidak** muncul dua kali di watchlist holder di bawahnya.
- Tambah manual: form **➕ Tambah CA manual ke Chart LP** di dalam card, atau
  radio *Masuk ke card* pada form **➕ Tambah token** (📋 Watchlist Holder /
  🌊 Chart LP). Tombol 🌊 pada baris watchlist holder memindahkan token ke
  Chart LP (`set_watchlist_source`).

## Scan Meteora Pool

- 24 jam: `pool_type=dlmm && active_tvl≥1000 && fee_active_tvl_ratio≥250`
- 1 jam: `pool_type=dlmm && active_tvl≥1000 && fee_active_tvl_ratio≥1`
- Pool 24 jam yang masih muncul di 1 jam **tetap ditampilkan**
- Dust holder **≥ 1% MC** (BAHAYA) disembunyikan, **≥ 0,5% MC** ditandai
  badge **HATI-HATI**
- Dust **< 0,1% MC** dengan data holder valid (≥ 40 wallet) diberi badge
  **🏆 BEST POOL** di kolom Dust %MC — hanya di listing ini; card Chart LP /
  halaman Holder Analytic tidak berubah (keputusan user). Dust 0,00% dari
  data yang gagal/kosong **tidak pernah** mendapat badge
- Tombol **⭐** memasukkan token ke card **Chart LP** (watchlist terpisah di
  bagian atas dashboard, lengkap dengan grafik perubahan dust holder)
- Shortcut: [Meteora DLMM](https://app.meteora.ag/dlmm/) + [HawkFi](https://www.hawkfi.ag/meteora/)

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

- perubahan **relatif** (%) dust % MC — angka besar di kolom **Sejak masuk**,
- pembandingnya titik pertama **pada/setelah** tanggal masuk; bila belum ada
  titik setelah tanggal itu, dipakai titik pertama dan ditandai di tooltip,
- tooltip memuat nilai awal → akhir (% MC), perubahan **poin persentase**
  (satuan rule alert), perubahan **jumlah wallet dust**, dan umur window,
- warna mengikuti ambang permintaan user:
  **turun ≥ 50%** = hijau (`#15803d`, dust menipis),
  **naik ≥ 100%** = merah (`#b91c1c`, dust menebal 2×), di antaranya abu-abu.

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
  sehingga rule 🔔 HIGH DROP tidak pernah menyala dari "dust 0%" palsu.

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
| `lp_watchlist.py` | Card **Chart LP**: pisah watchlist Meteora, baris + grafik perubahan dust holder |
| `meteora_screener.py` | Listing DLMM 24h+1h, enrich holder, filter dust ≥1%; badge BEST POOL di UI app.py (dust < 0,1% + data valid) |
| `holder_analysis.py` | Fetch holder Helius/GMGN, klasifikasi real/dust/mid |
| `robinhood_holders.py` | Robinhood Chain (chain 4663): holder Blockscout, decimals/supply, analisa dust sama dengan Solana |
| `robinhood_watchlist.py` | Watchlist/path Robinhood: `watchlist_robinhood.json`, status & history terpisah, scan + publish best-effort |
| `solscan_holders.py` | Kalkulasi wallet_depth (bucket & tier) |
| `helius_holders.py` | Scan Holder Khusus satu token + bar chart |
| `holder_status.py` | Snapshot dashboard ramping (ref `holder-live`) + history ringkas + transport GitHub (JSON & byte/gzip) |
| `core.py` | Config/key Helius, pasar DexScreener, candle hourly/harian GeckoTerminal |
| `scripts/scan_holders.py` | Cron watchlist (run ±5 menit; kedua lane LP tiap run, biasa slot 4 jam, `LP_SCAN_RUN_MULTIPLIER` untuk rem Helius): holder, alert (konfirmasi volume lazy, scope early dump = token LP), catat history, publish snapshot + backup store |
| `telegram_alerts.py` | Rule dust 4 jam/baseline + ⚡ EARLY DUMP (crossing 0,1% MC, token pool, tanpa gerbang volume), dedup bucket 4 jam + jeda 1 jam, Telegram Bot API (+ link GMGN & DexScreener di pesan) |
| `links.py` | Satu sumber URL eksternal: GMGN, DexScreener, Solscan, Meteora DLMM, HawkFi (HTML untuk UI, teks polos untuk Telegram) + slug halaman internal (`/Holder?mint=…`) |
| `page_router.py` | Router deep link: `?mint=`/`?page=` yang jatuh ke halaman utama dipantulkan ke halaman yang dituju (`st.switch_page`) |
| `trending_ui.py` | Listing Trending/Degen + Add All Watchlist |
| `pre_pump_screener.py` | 🚀 Pre-Pump Screener: 4 sinyal on-chain (gelombang add likuiditas + journal, konsolidasi holder, volume calm-before-storm, TX velocity), PUMP SCORE 0–10, kartu token, auto-refresh `st.fragment(run_every=300)` |
| `pages/4_📊_CVD.py` | Chart CVD harian |
| `pages/5_🧮_Holder.py` | Holder Analytic: dust, grafik 4 jam, kohort, kronologi FULL |

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
`TELEGRAM_CHAT_ID`). Tanpa credential Telegram, scan tetap berjalan dan
pengiriman alert dilewati dengan aman.

## Cadens scan

Sejak **2026-09-06** cron berjalan **tiap ±5 menit** dan scanner yang membagi
pekerjaannya per lane (`scripts/scan_holders.py`):

| Lane | Kadens | Alasan |
| --- | --- | --- |
| 🦅 **Watchlist Robinhood LP** | tiap run = **±5 menit** | permintaan user: "percepat fetch watchlist robinhood menjadi 5 menit sekali" |
| 🌊 **Chart LP Meteora** (Solana) | tiap run = **±5 menit** | permintaan user susulan: "iya untuk watchlist meteora juga, per 5 menit, biar perubahan holder bisa langsung ketahuan" |
| 📋 **Watchlist biasa** (Solana & Robinhood biasa) | slot **4 jam** = 48 slot 5 menit | tidak berubah |

Harga yang dibayar: tiap run sekarang menarik holder penuh semua token Meteora
dari Helius (±3× dibanding era 15 menit) dan ±30 halaman Blockscout per token
Robinhood. Kalau kuota mulai ketat, TIDAK perlu mengubah kode — set
`LP_SCAN_RUN_MULTIPLIER: "3"` di langkah scan pada workflow, lalu `lp_slot_due`
menahan lane Solana di luar slot 15 menitnya (log:
`Rencana scan: … slot_lp=bukan`) sementara Robinhood LP tetap tiap run.
**Gate run ganda** `MIN_RUN_GAP_SEC` = **4 menit**, wajib di bawah kadens run —
kalau tidak, lane LP justru dibungkam gate-nya sendiri. Yang sengaja tidak ikut
dipercepat: pengingat ⚡ Telegram (`FAST_BUCKET_SEC` tetap 15 menit/token —
kalau tidak, satu token bisa dapat 3 pesan yang sama per 15 menit).

Densitas titik riwayat mengikuti kadens run, jadi `holder_history.MAX_POINTS`
naik **336 → 1008** (±3,5 hari pada titik 5 menit) supaya "Grafik 4 jam" di
card LP tetap 21 bucket; tanpa itu jendela grafik menyusut jadi 28 jam.

Kadens dijaga dua mekanisme di `.github/workflows/daily-effort.yml`: `schedule:
"*/5 * * * *"` (fallback) dan langkah **chain dispatch** yang tidur sampai
batas 5 menit berikutnya lalu men-dispatch run baru. Berkas workflow tidak
bisa ditulis bot (GitHub menolak tanpa izin `workflows`), jadi kedua perubahan
itu disiapkan di **`daily-effort-5menit.yml`** — salin isinya ke
`.github/workflows/daily-effort.yml` lewat UI GitHub. Selama belum disalin,
cron tetap ±15 menit untuk SEMUA lane (aman, hanya saja belum secepat yang
diminta). Schedule GitHub bersifat
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
| `TELEGRAM_ALERT_MODE` | `off` (default), `summary`, `full` |
| `TELEGRAM_MAX_HOLDERS_PER_TOKEN`, `TELEGRAM_MAX_WALLETS_PER_TOKEN` | default 20, 10 |
| `MAX_HOLDERS_PER_TOKEN` | FULL 100.000 (cron sejak 2026-09-05 & tombol "Scan holder FULL"), 2.000 (tombol scan watchlist di app.py) |
| `MIN_HOLDERS`, `MIN_WALLET_DEPTH_PCT` | 40, 75% — ambang minimum Holder Analytic |
| `MAX_HOLDER_HISTORY`, `MAX_HOLDER_TOKENS`, `MAX_WALLETS_PER_TOKEN` | 1200, 120, 800 — batas store |
| `DUMP_THRESHOLD_PP`, `ACCUMULATION_THRESHOLD_PP`, `BASELINE_SHIFT_THRESHOLD_PP` | 0.25, 0.50, 1.0 — ambang dust (tidak diubah) |
| `DUMP_VOLUME_MULTIPLE`, `ACCUMULATION_VOLUME_MULTIPLE` | 2.0, 1.5 — gerbang volume konfirmasi |
| `MIN_CONFIDENCE`, `MIN_CONFIDENCE_HIGH_VOLATILITY` | 0.70, 0.80 — ambang skor konfirmasi |
| `UNVERIFIED_CONFIDENCE`, `ALLOW_UNVERIFIED_ALERTS` | 0.50, `True` — data pasar hilang → tetap kirim, ditandai ⚠️ |
| `CONFIDENCE_VOLATILITY_BONUS` | 0.20 — bonus volatilitas tinggi + arah mendukung |
| `MIN_RESEND_SEC` | 3600 — jeda minimum antar-alert token+jenis yang sama |
| `VOLATILITY_WINDOW_HOURS`, `HIGH_VOLATILITY_STDDEV_PCT` | 4, 3.0 — `holder_history` |
| `BASELINE_HOURS`, `MIN_BASELINE_HOURS` | 168, 24 — `alert_context` (baseline volume 7 hari) |
| `MAX_BACKUP_BYTES`, `DURABLE_CACHE_TTL` | 3.500.000, 600 — `holder_history` (budget backup `.gz`, cache pull UI) |
| `MAX_POINTS` | 1008 — batas titik mentah per token; ±3,5 hari pada densitas LP 5 menit, 168 hari pada lane biasa 4 jam (grafik UI tetap di-resample per bucket 4 jam) |
| `DUST_BEST_PCT`, `DUST_BEST_MIN_HOLDERS` | 0.1, 40 — badge BEST POOL (strict `< 0,1%`) + guard data holder minimal |
| `DUST_BEST_LABEL` | `BEST POOL` — label badge (tampil apa adanya) |

Konstanta konfirmasi ada di `telegram_alerts.py`, metrik volatilitas di
`holder_history.py`, dan pengambilan konteks di `alert_context.py`.

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

## Backup store holder (durable)

Runner GitHub Actions dan Streamlit Cloud memakai filesystem **ephemeral**:
`holder_history.json` lenyap setiap run/restart, jadi baseline scan FULL,
kohort beku, state dedup alert, dan kronologi wallet tidak pernah bertahan.
Store sekarang dibackup penuh ke ref `holder-live` sebagai
**`holder_history.json.gz`** (gzip + JSON compact via Contents API base64):

- **cron** (`scripts/scan_holders.py`): `pull_holder_history()` →
  `merge_stores(lokal, durable)` → `seed_from_status()` (jaring kedua) →
  scan → publish snapshot → `publish_holder_history()`. Backup gagal hanya
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
