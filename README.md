# Wallet Depth — Holder Analytic (Dust)

Wallet Depth memantau token Solana dan berfokus pada **analisa holder
dust** sebagai jejak dump, plus **Scan Meteora DLMM**. Cron holder dapat
mengirim alert Telegram khusus perubahan dust; sinyal lama seperti silent
accumulation 12 jam dan reversal tetap tidak digunakan.

## Konsep

1. **Dust holder** — wallet murni dengan `0 < nilai ≤ $10`:
   - **dust % MC** = total nilai dust / marketcap × 100,
   - ≥ **0,5% MC** → **HATI-HATI** (badge kuning, peringatan dini),
   - ≥ **1% MC** → **BAHAYA** (disembunyikan dari Scan Meteora).
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
     mengecil/masuk dust, atau wallet dust baru).

   Perubahan dust baru menghasilkan **kandidat** sinyal: setiap kandidat
   harus lolos konfirmasi volume + harga + volatilitas dulu (bagian
   berikutnya) sebelum dikirim. Snapshot saldo dibatasi maksimum 300 wallet
   per anchor, event yang sukses dikirim dideduplikasi per bucket 4 jam
   **dan** ditahan minimal 1 jam antar alert sejenis.

## Konfirmasi volume & volatilitas (filter false positive)

Kandidat sinyal dust diperiksa silang terhadap pasar sebelum dikirim
(`telegram_alerts.validate_alert_with_volume`):

| Sinyal | Gerbang keras |
|---|---|
| **Dump** (dust naik ≥ 0,25 pp) | volume 4 jam ≥ **2×** rata-rata 7 hari **dan** harga ≤ **-1%** |
| **Akumulasi** (dust turun ≥ 0,50 pp + buyer) | volume 4 jam ≥ **1,5×** rata-rata 7 hari **dan** buy pressure > sell pressure |
| **Baseline shift** (±1 pp dari snapshot awal) | mengikuti arah perubahan: naik → aturan dump, turun → aturan akumulasi |

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
jadi scan 15 menit yang tenang tidak menambah request apa pun. Bila
GeckoTerminal gagal, konteks jatuh ke angka DexScreener yang **sudah** diambil
saat scan (`volume.h6` di-skala ke 4 jam, baseline dari `volume.h24`,
`priceChange.h6`, `txns` buys/sells) lalu ke `daily_effort.json` untuk
rata-rata volume 7 hari.

**Bila data tidak ada** (pool lebih muda dari 7 hari, API mati): alert **tetap
dikirim** dengan baris `Verifikasi volume: ⚠️ TIDAK TERVERIFIKASI` — indikasi
dump tidak boleh hilang senyap hanya karena sumber data sedang down. Set
`telegram_alerts.ALLOW_UNVERIFIED_ALERTS = False` untuk perilaku strict.

Alert yang lolos menyertakan rasio volume, perubahan harga, skor konfirmasi,
ambang yang dipakai, dan stddev 4 jam di pesan Telegram.

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
```

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
- Tombol **⭐** memasukkan token ke card **Chart LP** (watchlist terpisah di
  bagian atas dashboard, lengkap dengan grafik perubahan dust holder)
- Shortcut: [Meteora DLMM](https://app.meteora.ag/dlmm/) + [HawkFi](https://www.hawkfi.ag/meteora/)

## Modul

| File | Peran |
|---|---|
| `holder_history.py` | Pencatatan dust/kohort, resample 4 jam, ambang HATI-HATI/BAHAYA, metrik volatilitas 4 jam, baseline FULL, kronologi, backup durable store (`.gz`: merge/prune/publish/pull) |
| `alert_context.py` | Konteks pasar untuk konfirmasi alert: volume 4 jam, rata-rata 7 hari, buy/sell pressure, volatilitas (ditarik lazy) |
| `holder_chronology.py` | Snapshot wallet bounded, klasifikasi pergerakan, narasi kronologi |
| `lp_watchlist.py` | Card **Chart LP**: pisah watchlist Meteora, baris + grafik perubahan dust holder |
| `meteora_screener.py` | Listing DLMM 24h+1h, enrich holder, filter dust ≥1% |
| `holder_analysis.py` | Fetch holder Helius/GMGN, klasifikasi real/dust/mid |
| `solscan_holders.py` | Kalkulasi wallet_depth (bucket & tier) |
| `helius_holders.py` | Scan Holder Khusus satu token + bar chart |
| `holder_status.py` | Snapshot dashboard ramping (ref `holder-live`) + history ringkas + transport GitHub (JSON & byte/gzip) |
| `core.py` | Config/key Helius, pasar DexScreener, candle hourly/harian GeckoTerminal |
| `scripts/scan_holders.py` | Cron watchlist: holder, alert (konfirmasi volume lazy), catat history |
| `telegram_alerts.py` | Rule dust 4 jam/baseline, gerbang volume+volatilitas, dedup bucket 4 jam + jeda 1 jam, Telegram Bot API |
| `trending_ui.py` | Listing Trending/Degen + Add All Watchlist |
| `pages/4_📊_CVD.py` | Chart CVD harian |
| `pages/5_🧮_Holder.py` | Holder Analytic: dust, grafik 4 jam, kohort, kronologi FULL |

## Menjalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

Cron GitHub Actions ~15 menit (`.github/workflows/daily-effort.yml`)
menjalankan `scripts/scan_holders.py`. Snapshot dibaca dari
`holder_status.json` dan store penuh dari `holder_history.json.gz`
(keduanya ref `holder-live`) — lihat **Backup store holder**. Lihat
`DEPLOY.md` untuk env
scanner (`HELIUS_API_KEY`, `GITHUB_TOKEN`) dan setup alert opsional
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Tanpa credential Telegram,
scan tetap berjalan dan pengiriman alert dilewati dengan aman.

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
| `MAX_HOLDERS_PER_TOKEN` | cron 3000, UI 2000 |
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

Konstanta konfirmasi ada di `telegram_alerts.py`, metrik volatilitas di
`holder_history.py`, dan pengambilan konteks di `alert_context.py`.

## Pengujian

```bash
python -m unittest discover tests
python -m py_compile holder_history.py holder_chronology.py meteora_screener.py \
  holder_analysis.py holder_status.py telegram_alerts.py alert_context.py \
  lp_watchlist.py core.py app.py scripts/scan_holders.py trending_ui.py \
  watchlist.py
```

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
