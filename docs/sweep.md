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

1. **liq/MC ≤ 35%** — ambang tetap. Biaya dorong dihitung sebagai uang quote yang
   masuk ke pool, `(√m − 1) × liq/2` (liq = TVL dua sisi, sisi quote = setengah).
   Pada batas 35%: naik 3x = `(√3 − 1) × 17,5% = 6,4% MC`.
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

Kriteria yang belum punya data ditandai belum ada data dan tidak dihukum dalam
skor. Trio struktural (1+2+3) wajib lulus; lalu perlu minimal
`min(4, jumlah kriteria yang ada datanya)` kriteria lolos.

## Ambang tetap dan dana acuan COCKROACH

Ambang UI/cron tidak dapat diubah dan tidak disimpan sebagai setting:

> Ambang fix: liq/MC ≤ 35% · holder/wallet ≤ 5% · standar pra-pump COCKROACH
> (acuan dana 10×)

Acuan COCKROACH pra-pump, 1 Okt 2026 22:42 WIB: harga $0,00023768, MC
$233.451, TVL/liquidity dua sisi $30.232, cash satu sisi $15.116, B/S 6,48%,
liq/MC 12,95%, biaya dorong 2× $6.261 / 3× $11.066 (4,74% MC) / 5× $18.684,
turnover 3,35×/hari, LP 89,82%. Biaya dorong = uang quote masuk
`(√m − 1) × liq/2`; angka 2×/3×/5× di atas cocok persis dengan basis ini.

**Acuan dana (sejak 2026-10-14) = biaya dorong 10× COCK: $32.684 ≈ 14,0% MC.**
Angka ini turunan dari rumus yang sama: `(√10 − 1) × cash satu sisi $15.116`,
bukan pengukuran langsung. Pada batas struktural liq/MC 35%, biaya 10× = 37,8%
MC ≈ 2,7× acuan.

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
kohort `LOLOS`, gate biaya 10x `LOLOS`, trio struktural lulus, dan skor cukup.

### Gate biaya 10x (2026-10-13)

| Status biaya | Aturan |
| --- | --- |
| `TUNGGU — biaya 10x X% MC (batas 80%)` | `(√10 − 1) × liq/MC ÷ 2 > 0,80` |
| `TUNGGU — biaya 10x belum ada data` | liq/MC atau MC kosong; gate belum lolos |
| `LOLOS` | `(√10 − 1) × liq/MC ÷ 2 ≤ 0,80` |

Gate ini diuji setelah gate kohort. Jika kohort belum lolos, status kohort yang
tampil. Dengan batas `liq/MC ≤ 35%` yang sudah ada, biaya 10x maksimum ≈ 37,8%
MC, sehingga gate biaya 10x (batas 80%) baru menahan vonis pada liq/MC di atas
≈ 74%. Gate ini praktis tidak aktif di bawah batas struktural.

### Gate avg buy holder (2026-10-13)

Sumber: GMGN `token_holders` (100 teratas menurut porsi). Hanya holder dengan
`balance > 0` dan `avg_cost` terisi yang dihitung; `min_avg` = avg buy terendah
di antara mereka. Holder dengan avg buy jauh di bawah harga sudah profit besar
dan bisa dump kapan saja.

| Status holder | Aturan |
| --- | --- |
| `TUNGGU — avg buy holder X% di bawah harga` | `1 − min_avg / harga > 0,50` (min_avg < 0,5 × harga) |
| `TUNGGU — avg buy holder belum ada data` | min_avg atau harga kosong; gate belum lolos |
| `LOLOS` | `1 − min_avg / harga ≤ 0,50` |

Gate ini diuji setelah gate biaya 10x, sebelum skor. Batas 50% adalah
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
- sweep mulai terjadi (cooldown 30 menit).

`est_cost_usd` adalah biaya dorong teoretis ke **puncak**:
`(√peak_mult − 1) × liq_usd / 2`, yaitu uang quote masuk ke pool. `leverage`
memakai basis yang sama. `net_inflow_usd` adalah Δ likuiditas (TVL dua sisi)
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
| `leverage` | paper gain ÷ biaya dorong (basis uang masuk) | 60,9× |

## Statistik dan runtime

Tiap alert meninggalkan baris sinyal dengan harga entry, base, `max_up_pct` /
`max_down_pct` (dilacak 72 jam), churn, biaya dorong, dan status. Ringkasan
mencakup hit ≥100% / ≥300%, median naik/turun, dan break-even hit rate.

**Saat halaman dibuka** tabel memakai *snapshot terakhir* tiap mint watchlist
(`store.latest_view`, disimpan di bucket snapshot terbaru), tanpa memindai ulang.
Hanya mint yang belum punya snapshot (baru ditambahkan) dipindai sekali. Tombol
**🔄 Refresh & ambil snapshot** memindai live semua mint dan mengambil snapshot;
**auto-refresh** melakukannya tiap 5 menit selama tab terbuka.

Kolom **Token pool / Token pool $ / Token/MC** (di samping liq/MC) = sisi token pool
(`liquidity.base` DexScreener, jumlah token), nilainya `jumlah × priceUsd`, dan
persentasenya terhadap MC (`fdv`). Snapshot lama belum punya data ini sampai di-refresh.

**Retry otomatis kohort tanpa data**: bila auto-refresh mati dan ada mint yang
gate kohort-nya `TANPA DATA — kohort` (OHLCV/VWAP atau avg cost GMGN belum ada,
mis. GeckoTerminal 429), hanya mint itu yang dipindai ulang tiap
`NODATA_RETRY_DELAY_SEC` = 60 detik (`use_cache=False`), maksimal
`NODATA_RETRY_MAX_ATTEMPTS` = 5 percobaan per mint. Mint yang sudah berdata tidak
ikut dipindai. Tombol Refresh (dan Refresh per mint) mereset jatah percobaan. Saat
auto-refresh menyala, retry ini tidak aktif karena auto-refresh 5 menit sudah
memindai semua mint.

Urutan tabel (`sweep_screen.display_sort_key`) berdasarkan **skor** (`lolos/punya
data`) tertinggi di atas. Jika skor sama, jumlah kriteria lolos yang lebih banyak
di atas, lalu vonis (LAYAK → KANDIDAT → gate lolos → TUNGGU → TANPA DATA), lalu
status kohort yang makin dekat ke −50%. Mint tanpa snapshot tampil sebagai
`MENUNGGU SNAPSHOT` di atas kohort PLUS. **Kohort PLUS selalu di paling bawah.**

Setiap mint punya tombol **🔄 Refresh <mint>** di bagian detailnya untuk pindai
ulang satu token saja (berguna saat data kriteria masih kosong).

Kolom **Hapus** di tabel mengeluarkan mint dari watchlist (centang, lalu tekan
tombol hapus). Snapshot dan sinyal mint tersebut tetap di state; hanya tampilan
dan pemindaian oleh cron yang berhenti.

Cron GitHub Actions tetap berjalan tiap 5 menit (`.github/workflows/sweep-scan.yml`)
dan auto-refresh halaman juga 5 menit. `store.fingerprint()` mencakup **kunci bucket**
snapshot per jam (bukan isinya), id sinyal, dan latch shakeout permanen. Jadi
commit hanya terjadi saat jam baru muncul; harga/view di jam berjalan ditimpa
tiap 5 menit tanpa commit. Field `alerts`/`updated` yang volatil juga tidak
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
