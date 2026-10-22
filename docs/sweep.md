# Page 🌊 Sweep — kelayakan sweep, alert, dan tabel statistik

Halaman terpisah dari **🏆 Scan Best Pool Meteora**. Entrinya
`pages/8_🌊_Sweep.py`; `app.py` tidak mengimpor modul Sweep.

## Alur

| Berkas | Isi |
| --- | --- |
| `sweep_screen.py` | mesin skrining murni: lima kriteria skor + gate authority, gate kohort, latch shakeout, deteksi sweep, rumus biaya |
| `sweep_data.py` | DexScreener + RugCheck + GMGN `token_stat`/`top_buyers` + GeckoTerminal OHLCV; cache 90/120 detik |
| `sweep_store.py` | watchlist manual, snapshot per jam, sinyal, gate alert, latch shakeout, push GitHub |
| `sweep_alert.py` | Telegram berlapis `st.secrets` → env → `config.json` |
| `sweep_scan.py` | satu putaran scan: ambil → snapshot → latch → gate/s skor → alert → prune |
| `sweep_ui.py` | badan halaman Streamlit, tabel dan panel Kohort lahir |
| `scripts/scan_sweep.py` | runner cron, mencetak `SWEEP_STATE_CHANGED=0\|1` |

Watchlist tetap **manual**. Tidak ada pengisian otomatis dari Best Pool atau
pemindai lain.

## Kriteria struktural dan skor

1. **token/MC ≤ 17,5%** — ambang tetap (keputusan 2026-10-14). Float tipis
   diukur dari sisi **token** pool: `pool_base_usd ÷ FDV` (kolom Token/MC). Angka
   17,5% setara liq/MC 35% dibagi dua, dengan asumsi sisi quote kira-kira separuh
   likuiditas. Tanpa `pool_base_usd` (snapshot lama) kriteria = belum ada data,
   bukan tebakan dari liq/MC. Biaya dorong tetap dihitung dari liq/MC sebagai uang
   quote yang masuk ke pool, `(√m − 1) × liq/2` (liq = TVL dua sisi). Karena sisi
   quote tidak dibatasi kriteria ini, liq/MC bisa lebih besar; yang membatasi biaya
   tidak lagi dibatasi gate; biaya 10x hanya informasi (lihat di bawah).
2. **Authority mint/freeze sudah dilepas** — gate struktural, tidak masuk skor.
   Kriteria LP terkunci dihapus (2026-10-13): likuiditas token pump.fun sudah
   pasti terkunci, jadi tidak dicek maupun dihitung.
3. **Float tersebar**: top-10 < 25% dan setiap holder/wallet ≤ 5%; akun pool
   AMM dikecualikan. Persentase holder berasal dari RugCheck dan ditulis dalam
   skala 0–100.
4. **Akumulasi (proxy)**: net tekanan beli > 0 dengan harga sideways (< 25%),
   dari snapshot. Ini proxy, bukan CVD level wallet.
5. **Ekspansi volume**: volume naik ≥ 3× dari titik tersepi, sementara harga
   belum lari (< 3× dari titik tersepi).
6. **Shakeout + higher low**: satu candle turun ≥ 30%, lalu low berikutnya
   tidak lebih rendah. Begitu terdeteksi, status kriteria 6 di-latch permanen
   per mint di `sweep_state.json` (`shakeout_latched_at`). Harga yang kemudian
   menembus low lama—termasuk candle sweep—tidak menghapus latch. Sebelum pola
   pernah terdeteksi, perilaku kriteria pada candle yang sama tetap seperti
   sebelumnya.
   **Peringatan pelanggaran (2026-10-14, opsi 3):** kriteria tetap LOLOS, tetapi
   bila candle sesudah latch punya low lebih rendah dari low shakeout, hasil
   diberi `breached` dan keterangan ⚠ di detail mint, serta jumlahnya di atas
   tabel. Low shakeout dibaca dari candle dengan `ts` = waktu latch, jadi latch
   yang sudah keluar dari jendela candle tidak bisa dicek dan tidak diberi tanda.
   Contoh COCKROACH 1 Okt: latch 20:00 WIB (low 0,00026020), low 22:00 WIB
   0,00021623 → ditandai.

Kriteria yang belum punya data ditandai belum ada data dan tidak dihukum dalam
skor. Trio struktural (1+2+3) wajib lulus; lalu perlu minimal
`min(4, jumlah kriteria yang ada datanya)` kriteria lolos.

## Ambang tetap dan dana acuan COCKROACH

Ambang UI/cron tidak dapat diubah dan tidak disimpan sebagai setting:

> Ambang fix: token/MC ≤ 17,5% · holder/wallet ≤ 5% · standar pra-pump COCKROACH
> (acuan dana 10×)

Acuan COCKROACH pra-pump, 1 Okt 2026 22:42 WIB: harga $0,00023768, MC
$233.451, TVL/liquidity dua sisi $30.232, cash satu sisi $15.116, B/S 6,48%,
liq/MC 12,95%, biaya dorong 2× $6.261 / 3× $11.066 (4,74% MC) / 5× $18.684,
turnover 3,35×/hari, LP 89,82%. Biaya dorong = uang quote masuk
`(√m − 1) × liq/2`; angka 2×/3×/5× di atas cocok persis dengan basis ini.

**Acuan dana (sejak 2026-10-14) = biaya dorong 10× COCK: $32.684 ≈ 14,0% MC.**
Angka ini turunan dari rumus yang sama: `(√10 − 1) × cash satu sisi $15.116`,
bukan pengukuran langsung. Biaya 10× pada liq/MC 12,95% (COCK) = 14,0% MC = 1,0× acuan.

Kolom **× dana acuan 10x** menampilkan biaya dorong 10× dalam kelipatan acuan
14,0% MC: `biaya 10× (% MC) ÷ 14,0%`. COCK = 1,0×.

Turnover di tabel utama adalah **`vol24_usd / liq_usd`**, dengan `liq_usd`
dua sisi. Angka pembanding: COCK 3,35×/hari, TH 1,39×/hari, Paws 2,12×/hari.
Biaya 3× COCK $11.066 dan turnover ini acuan informasi, bukan pengganti gate.

## Gate kohort kelahiran

Sebelum vonis layak, token harus lolos gate kohort. Pool utama adalah pool
DexScreener dengan likuiditas terbesar. Dari OHLCV GeckoTerminal per jam,
mesin mengambil **48 jam pertama sejak `pairCreatedAt`** dan menghitung proksi
VWAP berbobot volume (harga tipikal OHLC). Rentang low–high jendela itu
ditampilkan sebagai **biaya kohort**. Pilihan jendela awal berfokus pada cohort
launch: bundler, bot-degen, dan fresh-wallet rate GMGN terlihat sebagai angka
ukur di panel yang sama; `bot_degen_rate` yang tinggi (misalnya 44,6%) menjadi
indikator terukur konsentrasi aktivitas bot pada cohort awal.

`status_avg_cost = harga_sekarang / VWAP_48h_lahir − 1`. Nilainya fraksi di
mesin dan ditampilkan sebagai PLUS/MINUS persen. Dinding impas adalah dua jarak
`VWAP / harga_sekarang` dan `harga_tertinggi_jendela / harga_sekarang`.
Label wajib UI: **perkiraan (proksi VWAP 48 jam)** — bukan harga rata-rata
wallet yang diamati langsung. GMGN `holding_rate` dan ringkasan `statusNow`
(`hold / sold_part / sold`) adalah data provider terpisah dan tetap ditampilkan
apa adanya sebagai konteks cohort.

| Status kohort | Aturan |
| --- | --- |
| `SKIP — kohort plus` | `status_avg_cost ≥ 0`; cohort rata-rata sedang PLUS |
| `TUNGGU — kohort belum minus 50%` | `−0,50 < status_avg_cost < 0` |
| `TUNGGU — kohort GMGN belum minus 50%` | VWAP lolos, tetapi `status_gmgn ∈ (−0,50, 0)` |
| `TUNGGU — kohort GMGN plus` | VWAP lolos, tetapi `status_gmgn ≥ 0` |
| `LOLOS` | `status_avg_cost ≤ −0,50` **dan** `status_gmgn ≤ −0,50` (Kohort C, 2026-10-13) |
| `LOLOS — pernah ≤ −50% (latch)` | Latch kohort (2026-10-14): status di atas pernah tercapai (live, atau dari riwayat snapshot per jam pada harga yang sama). Latch menggantikan semua status `TUNGGU — kohort …` (belum minus 50% VWAP/GMGN dan GMGN plus, 2026-10-14) — `SKIP` dan `TANPA DATA` tidak berubah. Tersimpan di `state.cohort_latched` dan permanen |
| `TANPA DATA — kohort` | OHLCV/VWAP/harga tidak tersedia; jangan klaim lolos |
| `TANPA DATA — kohort GMGN` | VWAP lolos, tetapi data holder GMGN (avg cost) tidak tersedia; jangan klaim lolos |

**Status GMGN** (`status_gmgn`) = harga sekarang ÷ avg buy tertimbang saldo − 1.
Avg buy tertimbang = Σ(`avg_cost` × `balance`) ÷ Σ`balance`, dari holder GMGN
`token_holders` (100 teratas menurut porsi) yang masih memegang token dan punya
`avg_cost`. Ini **perkiraan**: `avg_cost` GMGN adalah biaya per total pembelian,
sehingga untuk holder yang sudah menjual bagian basisnya tidak persis. Holder di
luar 100 teratas tidak dihitung.

Pool berumur kurang dari 48 jam memakai seluruh jendela yang ada dan diberi
label **jendela parsial**. OHLCV kosong atau VWAP tidak bisa dihitung selalu
menahan gate, bukan dianggap minus. `LAYAK SWEEP` hanya mungkin jika gate
kohort `LOLOS`, gate avg buy holder `LOLOS`, trio struktural lulus, dan skor cukup.

### Biaya 10x (informasi saja, 2026-10-15)

Biaya untuk naik 10x, `(√10 − 1) × liq/MC ÷ 2`, ditampilkan sebagai informasi
(`cost_10x_mc_frac`, kolom `× dana acuan 10x`). **Tidak ada gate batas 28% MC**:
biaya tidak memengaruhi vonis maupun `eligible`, dan tidak ada status
`TUNGGU — biaya 10x`. Gate ini dihapus atas permintaan user (2026-10-15).


### Gate avg buy holder (2026-10-13)

Sumber: GMGN `token_holders` (100 teratas menurut porsi). Hanya holder dengan
`balance > 0` dan `avg_cost` terisi yang dihitung; `min_avg` = avg buy terendah
di antara mereka. Holder dengan avg buy jauh di bawah harga sudah profit besar
dan bisa dump kapan saja.

| Status holder | Aturan |
| --- | --- |
| `TUNGGU — avg buy holder X% di bawah harga` | `1 − min_avg / harga > 0,50` (min_avg < 0,5 × harga) |
| `TUNGGU — avg buy holder belum ada data` | min_avg atau harga kosong; gate belum lolos |

Kolom **Lowest buy (MC)** di tabel utama = `min_avg × MC ÷ harga`, yaitu avg buy
terendah dinyatakan dalam market cap (`screen.holder_lowest_buy_mc`). Di sampingnya
ditampilkan pergerakan harga sekarang sejak avg buy terendah, `harga ÷ min_avg − 1`
(`naik X%` jika harga di atas lowest buy, `turun X%` jika di bawahnya), misalnya
`$30K (harga naik 46.0%)`. Kolom ini hanya tampilan dan
tidak mengubah vonis; nilainya sama dengan yang dipakai gate.

### TIDAK LAYAK disembunyikan (2026-10-15)

Baris dengan vonis `TIDAK LAYAK` diperlakukan seperti `SKIP — kohort plus`: diurutkan
paling bawah dan tidak tampil di tabel utama. Baris tersebut muncul di tabel
terpisah ("Tampilkan N mint yang disembunyikan"). Baris dengan scan terakhir gagal
tidak pernah disembunyikan. Baris `SKIP — kohort plus` sendiri tetap tampil di bawah.

### Order flow (info saja, 2026-10-15)

Dibaca dari candle jam yang sudah ada (`screen.order_flow_info`). Hasilnya disimpan
di `result["order_flow"]` dan ditampilkan di panel detail. **Tidak memengaruhi**
kriteria, skor, vonis, `eligible`, urutan, maupun filter tampilan.

| Pola | Aturan |
| --- | --- |
| BOS naik | close candle terakhir > high 20 jam sebelumnya |
| Sweep low lalu reclaim | low candle terakhir < low 20 jam sebelumnya, tetapi close di atasnya |
| Penolakan ekor bawah | ekor bawah ≥ 50% range dan close di separuh atas |
| Volume node (POC) | level harga dengan volume terbanyak pada 48 jam terakhir; volume tiap candle dialokasikan ke level close-nya (24 level) |

Delta per candle dari trade (GMGN) belum diimplementasikan.

### Delta dari trade (info saja, 2026-10-15)

Diambil hanya untuk kandidat (`delta_candidate`: kohort `TUNGGU` atau `LOLOS`,
bukan `TIDAK LAYAK`). Sumber: GMGN token trades, jendela 6 jam, maksimal 10 halaman
(100 trade per halaman). Trade dengan nilai USD kosong dibuang.

| Istilah | Rumus |
| --- | --- |
| Delta jam | beli USD − jual USD |
| Delta % | delta ÷ (beli + jual) |
| CVD | jumlah delta sejak awal jendela (jam tanpa trade = 0) |

| Flag | Aturan (jam terakhir vs jam sebelumnya) |
| --- | --- |
| `div_bearish` | harga lebih tinggi dari semua jam sebelumnya di jendela, tetapi CVD lebih rendah dari CVD pada harga tertinggi sebelumnya |
| `absorb` | delta % ≥ +20% dan harga tidak naik |
| `spike_no_progress` | \|delta %\| ≥ 50% tetapi \|perubahan harga\| < 2% |

Jika fetch gagal atau data tidak lengkap (batas halaman tercapai), panel menampilkan
peringatan. `MIN_SOL = 0.05` di `cvd.py` ikut membuang trade kecil. Hasil tidak
memengaruhi kriteria, skor, vonis, `eligible`, urutan, atau filter tampilan.
| `LOLOS` | `1 − min_avg / harga ≤ 0,50` |

Gate ini diuji setelah gate kohort, sebelum skor. Batas 50% adalah
interpretasi dari "maks 50% dari harga sekarang" dan perlu dikonfirmasi user.

### Nominal dolar (tabel utama dan detail biaya)

- Kolom **Dana acuan 10x** di tabel utama = `(√10 − 1) × liq/2`, basis kas satu sisi
  seperti `× dana acuan` (COCK ≈ $32.684). Setara dengan `× dana acuan` × 14,0%
  × MC; untuk COCK hasilnya ≈ $32.684.
- Tabel **Biaya sweep** di detail menambah kolom **Biaya ($)** per target
  = `(√m − 1) × liq / 2`, uang quote masuk ke pool. Setara dengan `% MC × MC`.
- Snapshot lama yang belum punya field ini tampil `—` sampai dipindai ulang.

## Mengapa gate kohort minus besar

> Kohort **minus besar = loss aversion** → tidak mau jual di harga bawah → tekanan jual
> **habis**. Gejalanya: tape sepi (turnover rendah) dan float sudah terserap ke pool.
> Harga impas mereka masih jauh di atas harga kini → tidak ada dinding jual sampai target
> 2–5× tercapai. Ruang bebas untuk operator. Sebaliknya kohort yang sedang **PLUS** akan
> merealisasikan profit ke pump kita → token semacam itu di-skip. Contoh acuan: COCK
> pra-pump (1 Okt) — kohort lahir minus besar (−45% s/d −82%), tape sepi 3,35×/hari, float
> 6,48% → layak disweep.

## Alert dan angka teoretis vs terukur

Alert dikirim hanya saat **transisi status**, bukan setiap scan:

- kelayakan muncul (cooldown 6 jam);
- sweep mulai terjadi — **sekali per candle 5 menit**. Waktu sinyal = waktu candle
  sweep (kolom `ts`, `sweep_ts`), bukan waktu scan (`detected_ts`). Alert hanya
  dikirim bila candle tidak lebih dari 60 menit lalu; sweep yang lebih tua tetap
  tercatat dengan `alert_skipped = candle_terlalu_tua`.

Saat candle yang sama terlihat lagi di scan berikutnya, sinyal tidak dibuat ulang.
Bila inflow nyata baru tersedia dari snapshot berikutnya, angka itu diisi ke sinyal
yang sudah ada (`net_inflow_usd`, `churn_net_x`, `leverage_net`, `net_measured_at`).
Putaran tanpa alert (`--no-alerts`, hanya dipakai manual; cron tidak memakai flag ini)
tetap mencatat sinyal dengan `alert_skipped = alert_nonaktif`. Candle yang dicatat
dari putaran itu dianggap sudah tercatat, jadi tidak dikirim ulang oleh putaran berikutnya.

`est_cost_usd` adalah biaya dorong teoretis ke **puncak**:
`(√peak_mult − 1) × liq_usd / 2`, yaitu uang quote masuk ke pool. `leverage`
= `paper_gain_usd ÷ est_cost_usd` (keduanya dari MC dasar, sejak 2026-10-14; sebelumnya
memakai liq/MC sekarang sehingga angkanya bias).

Semua tampilan waktu di app memakai **WIB** (Asia/Jakarta). Batas hari UTC di modul
CVD/core tetap dipakai untuk data GMGN/Helius dan bukan untuk tampilan. `net_inflow_usd` adalah Δ likuiditas (TVL dua sisi)
antar snapshot dibagi dua, sehingga satuannya sama dengan biaya. Tetap `None`
jika tidak tersedia. Referensi dari `REF_NET_COST_MULT = 1,0` berlabel estimasi,
bukan pengukuran.

| Nama | Arti | COCKROACH 1 Okt |
| --- | --- | --- |
| `est_cost_usd` | biaya teoretis dorong ke **puncak** `(√peak_mult−1) × liq / 2` | $29.389 |
| `est_cost_close_usd` | biaya ke **close** `(√price_mult−1) × liq / 2` | $12.033 |
| `paper_gain_usd` | kenaikan MC kertas sampai puncak | $1.790.194 |
| `paper_mcap_usd` | MC kertas di close; bukan pembilang leverage | $752.939 |
| `net_inflow_usd` | **terukur**: Δ likuiditas antar snapshot ÷ 2 (uang masuk) | $29.389 |
| `churn_x` / `churn_net_x` | volume ÷ biaya teoretis / inflow terukur | 42,3× / 42,3× |
| `leverage` | paper gain ÷ biaya dorong, keduanya dari MC dasar | 60,9× |

## Statistik dan runtime

Tiap alert meninggalkan baris sinyal dengan harga entry, base, `max_up_pct` /
`max_down_pct` (dilacak 72 jam), churn, biaya dorong, dan status. Ringkasan
mencakup hit ≥100% / ≥300%, median naik/turun, dan break-even hit rate.

**Saat halaman dibuka** tabel memakai *snapshot terakhir* tiap mint watchlist
(`store.latest_view`, disimpan di bucket snapshot terbaru), tanpa memindai ulang.
Hanya mint yang belum punya snapshot (baru ditambahkan) dipindai sekali. Tombol
**🔄 Refresh & ambil snapshot** memindai live semua mint dan mengambil snapshot;
**auto-refresh** melakukannya tiap 30 menit selama tab terbuka (`AUTO_REFRESH_SEC` = 1800).

Kolom **Token pool / Token pool $ / Token/MC** (di samping liq/MC) = sisi token pool
(`liquidity.base` DexScreener, jumlah token), nilainya `jumlah × priceUsd`, dan
persentasenya terhadap MC (`fdv`). Snapshot lama belum punya data ini sampai di-refresh.

**Retry otomatis kohort tanpa data**: bila auto-refresh mati dan ada mint yang
gate kohort-nya `TANPA DATA — kohort` (OHLCV/VWAP atau avg cost GMGN belum ada,
mis. GeckoTerminal 429), hanya mint itu yang dipindai ulang tiap
`NODATA_RETRY_DELAY_SEC` = 60 detik (`use_cache=False`), maksimal
`NODATA_RETRY_MAX_ATTEMPTS` = 5 percobaan per mint. Mint yang sudah berdata tidak
ikut dipindai. Tombol Refresh (dan Refresh per mint) mereset jatah percobaan. Saat
auto-refresh menyala, retry ini tidak aktif karena auto-refresh 30 menit sudah
memindai semua mint.

Urutan tabel (`sweep_screen.display_sort_key`): vonis **LAYAK SWEEP** dan **KANDIDAT**
selalu di atas (permintaan user 2026-10-14), diurutkan menurut jarak di bawah. Sisanya
dimulai dari yang **paling dekat ke acuan dana 10x** (`x dana acuan` = 1,0× = biaya 10x COCKROACH): jarak
`|x − 1|` paling kecil di atas (permintaan user 2026-10-14). Jika jaraknya sama,
skor (`lolos/punya data`) tertinggi di atas, lalu jumlah kriteria lolos, lalu vonis
(LAYAK → KANDIDAT → gate lolos → TUNGGU → TANPA DATA), lalu status kohort yang makin
dekat ke −50%. Mint tanpa acuan dana (tanpa liq/MC) dan mint tanpa snapshot
(`MENUNGGU SNAPSHOT`) berada di bawah baris yang punya acuan. **Kohort PLUS selalu di
paling bawah.**

**Scan yang gagal** (fetch data error, permintaan user 2026-10-14): status scan terakhir
tiap mint disimpan di `state.scan_status` (`ts`, `ok`, `error`). Mint yang scan
terakhirnya gagal **tidak pernah disembunyikan** oleh filter tampilan, dan diberi
peringatan di atas tabel serta di detailnya. Datanya tetap dari scan sukses terakhir
(atau belum ada). Scan sukses berikutnya menghapus tanda gagal.

Setiap mint punya tombol **🔄 Refresh <mint>** di bagian detailnya untuk pindai
ulang satu token saja (berguna saat data kriteria masih kosong).

Kolom **Hapus** di tabel mengeluarkan mint dari watchlist (centang, lalu tekan
tombol hapus). Snapshot dan sinyal mint tersebut tetap di state; hanya tampilan
dan pemindaian oleh cron yang berhenti.

Cron GitHub Actions berjalan tiap 30 menit (`.github/workflows/sweep-scan.yml`)
dan auto-refresh halaman 30 menit. `store.fingerprint()` mencakup **kunci bucket**
snapshot per jam (bukan isinya), id sinyal, dan latch shakeout permanen. Jadi
commit hanya terjadi saat jam baru muncul; harga/view di jam berjalan ditimpa
tiap run cron tanpa commit. Field `alerts`/`updated` yang volatil juga tidak
memicu commit. Watchlist tetap manual.

**Penulisan bersama (cron + app).** Cron (`scripts/commit_sweep_state.sh`) dan app
(`save_state(persist=True)`) sama-sama menulis `sweep_state.json` ke `main`. Sebelum
menimpa, keduanya menggabung dengan versi GitHub lewat `sweep_store.merge_states`
(snapshot di-union per mint dan jam), dan push cron di-retry bila ditolak. Bila versi
GitHub tidak bisa dibaca, app menulis lokal saja dan tidak push. Penjadwalan cron
GitHub tetap best-effort: GitHub boleh melewatkan atau menunda run `schedule`.

| Berkas | Status |
| --- | --- |
| `sweep_watchlist.json` | di-commit |
| `sweep_state.json` | di-commit (snapshot, sinyal, latch shakeout) |
| `sweep_cache.json` | `.gitignore` (TTL 90–120 detik) |

## Test

```bash
python -m unittest tests.test_sweep_screen tests.test_sweep_data \
                   tests.test_sweep_store tests.test_sweep_alert tests.test_sweep_scan
```

Semuanya offline; fixture COCKROACH untuk biaya sweep tidak berubah.

## Cek manual satu CA (2026-10-20)

Halaman **🔍 Cek CA Sweep** (`pages/9_🔍_Cek_CA_Sweep.py`) memeriksa satu token
secara manual. Tempel satu CA Solana (base58, 32–44 karakter), lalu tekan
**Cek sekarang**.

- Input harus tepat satu CA. Kosong, lebih dari satu, atau format salah ditolak
  dengan pesan.
- Token dipindai live sekali (`sweep_scan.run_scan`, `use_cache=False`) dengan
  kriteria, vonis, dan filter yang sama seperti 🌊 Sweep.
- Hasil **tidak** masuk watchlist, **tidak** disimpan ke `sweep_state.json`, dan
  **tidak** mengirim alert Telegram. Delta GMGN tetap dihitung untuk kandidat
  (info saja).
- Riwayat tersimpan dibaca dari salinan state (latch shakeout dan latch kohort
  ikut berlaku). Salinan itu tidak pernah ditulis balik.
- Tombol Refresh per mint tidak ditampilkan di halaman ini.
- Bila CA sudah ada di watchlist, halaman menampilkan keterangan itu.
- Pemindaian gagal (mis. sumber data tidak merespons) ditampilkan sebagai error,
  tanpa vonis.

## CVD & delta sejak di bawah lowest avg buy (2026-10-20)

Tabel **📉 CVD & delta sejak di bawah lowest avg buy** di bawah hasil utama.
Info saja: tidak memengaruhi vonis, `eligible`, urutan, atau filter.

- **Yang dihitung:** hanya mint yang *lolos* (tampil di tabel utama dan kandidat
  delta, jadi tidak TIDAK LAYAK dan tidak tersembunyi filter) dan sedang berada
  di bawah lowest avg buy (`price ≤ holder_min_avg_cost`).
- **Mulai episode:** scan pertama ketika mint lolos dan harga ≤ lowest avg buy.
  Bila episode baru dimulai, awalnya diambil dari riwayat snapshot (bucket
  berurutan terakhir yang ≤ lowest buy). Label kolom *Sumber mulai* menunjukkan
  `riwayat snapshot (perkiraan)` atau `scan live`. Perkiraan ini memakai lowest
  buy saat ini, karena riwayat lowest buy tidak disimpan. Riwayat keterlihatan
  mint juga tidak disimpan, jadi diasumsikan lolos.
- **Berhenti:** episode selesai saat harga kembali di atas lowest avg buy. Riwayat
  selesai disimpan di `flow_episodes[mint].past` (10 terakhir).
- **Jeda:** saat mint tersembunyi, tidak ada trade yang diambil dan episode tetap
  terbuka. Saat lolos lagi dan masih di bawah, hitungan lanjut dari awal episode.
- **Angka:** trade GMGN dari mulai episode (maksimum 24 jam, `FLOW_MAX_PAGES` = 20
  halaman). Buy dan sell dalam USD, CVD = akumulasi buy − sell sejak mulai.
  *Data* menjadi `sebagian` bila batas halaman tercapai atau jendela tidak
  mencakup mulai episode.
- **Rekaman:** satu entri per jam di `flow_episodes[mint].active.hourly`
  (maksimum 168 jam). Fingerprint state ikut berubah saat jam baru tercatat, jadi
  cron akan commit per jam.


## Catatan kondisi sebelum sweep (2026-10-21)

Sweep bisa terjadi di mint yang **tersembunyi** dari tabel (filter tampilan atau
TIDAK LAYAK). Karena itu:

- Setiap scan yang berhasil menyimpan **catatan kompak** (`state.scan_log`) untuk
  semua mint, termasuk yang tersembunyi: vonis, skor, kriteria lolos/gagal,
  harga, liq/MC, holder, top-10, bundler, bot degen, volume, dan lowest buy.
  Hanya 6 scan terakhir per mint (cron 30 menit ≈ 3 jam).
- Saat sinyal sweep baru dicatat, sinyal menyimpan `pre_sweep` (hingga 3 scan
  sebelum candle sweep, plus scan yang mendeteksi), `pre_candles` (12 candle 5
  menit yang berakhir di candle sweep), dan `hidden_at_detect` (tersembunyi atau
  tidak saat terdeteksi).
- Sinyal sweep lama tidak punya `pre_sweep`. Halaman Statistik lalu menampilkan
  snapshot per jam sebelum sweep sebagai gantinya, dengan keterangan.
- Scan GMGN dan kriteria untuk mint tersembunyi tetap jalan seperti biasa. CVD dan
  delta tetap mengikuti aturan lama (mint tersembunyi tidak dihitung).
- Catatan scan ikut digabung saat state dari cron dan app di-merge.

## Fitur wallet sebelum sweep (2026-10-22)

Tujuan: membandingkan pola per wallet (fresh wallet dan bundler yang beli beruntun,
nominal buy per wallet) antara jendela sebelum sweep dan jendela pembanding.

- Sumber: trade GMGN (`cvd.fetch_gmgn_swaps`) dengan tag `fresh_wallet`, `bundler`,
  dan `sandwich_bot`. Trade di bawah `MIN_SOL` (≈ $10) tidak ikut, sama seperti di
  pemindaian CVD.
- **Jendela pembanding** (`wallet_flow` kind `spike`): setiap scan, untuk mint yang
  volume bar 5 menit terakhirnya ≥ 5× median 24 bar sebelumnya, fitur 3 jam terakhir
  dicatat. Mint itu bisa punya sweep atau tidak. Ini pembanding dari kondisi yang
  mirip, tetapi belum tentu tanpa sweep sama sekali.
- **Sweep baru** (`wallet_pre` di sinyal, kind `sweep`): fitur 3 jam sebelum candle
  sweep, dengan jendela yang sama.
- Fitur (angka mentah, tanpa ambang): jumlah trade, buy/sell USD, rasio buy/sell,
  jumlah wallet pembeli, median dan terbesar buy per wallet, porsi buy dari fresh
  dan bundler, porsi sandwich dari volume, dan **rangkaian fresh/bundler terpanjang**
  (buy beruntun dengan jarak ≤ 120 detik antar buy fresh/bundler).
- Batas: `WALLET_MAX_PAGES = 10` (≈ 1.000 trade per jendela). Jika GMGN gagal atau
  halaman habis sebelum jendela selesai, `complete = false` dan angkanya bisa kurang.
- Tes: `tests/test_sweep_wallets.py` memakai contoh kecil dengan angka dihitung manual.
  Jalur GMGN wallet dimatikan di `tests/_offline_delta.py` supaya tes tetap offline.
