# Progress

## 2026-09-03 — Kartu metrik Holder Analytic mengikuti scan manual (kasus AGENTHQ)

Laporan user: token **AGENTHQ** menampilkan dust hold **0,7% di grafik** tetapi
**1,16% di kartu "Dust hold % MC"** pada saat yang sama.

### Akar masalah (dua lapis)
1. **Dua vintage data.** Halaman Holder Analytic mengambil kartu metrik dari
   snapshot terpublikasi `holder_status.json` (`pages/5_🧮_Holder.py` baris
   437/441/448) tetapi mengambil grafik dari `holder_history.json` + riwayat
   snapshot (`_points_for`). Tombol **🔄 Scan holder FULL token ini** hanya
   memanggil `ingest_many(..., detail=True)` → titik baru masuk store,
   snapshot tidak diperbarui — dan memang tidak boleh: `snapshot_status`
   membangun `tokens` dari analyses yang diberikan saja (tidak merge), jadi
   publish satu token akan menghapus token lain dari dashboard. Kartu = cron
   21:35 WIB, grafik = scan manual barusan.
2. **Kenapa selisihnya besar.** AGENTHQ sedang pump: harga 0,0001085 →
   0,0001889 (+74%; `priceChange.h1` +80%), MC $108.545 → ±$188.968.
   dust % MC = nilai dust / MC sebenarnya **invariant terhadap harga**
   ($1.256,73 × 1,741 ÷ $188.968 = 1,158%, tetap), **tetapi** cutoff dust
   adalah **$10 per wallet dalam USD**: wallet yang memegang 52.938–92.166
   token (nilai lama $5,74–$10) "lulus" ke >$10. Agar tampil 0,70%, nilai
   dust harus tinggal ±$1.323 → ±40% nilai dust pindah bucket, dan slice
   $5,74–$10 itu memang lazim memuat 40–45% nilai dust. Jadi **tidak ada yang
   jual** — klasifikasinya yang bergeser. Cerminannya (harga turun → wallet
   masuk dust → dust % MC naik ±0,4-0,5 pp, melewati ambang dump 0,25 pp)
   justru **lolos** gerbang volume/harga karena harga ≤ −1% dan volume tinggi.

### Perbaikan (opsi A — pilihan user)
- `holder_status.compact_manual_scan()`: payload ringkas scan manual untuk
  `st.session_state[MANUAL_SCAN_KEY]`; peta wallet / snapshot alert /
  kronologi dibuang lewat `_holders_for_status`.
- `holder_status.resolve_token_view()`: overlay scan manual di atas entri
  snapshot bila `analyzed_at`-nya tidak lebih tua dan `holders` terisi;
  `history`/`cohort`/`alert_state`/`chronology` tetap dari snapshot; menambah
  `view_source` = `manual`/`snapshot`; tidak memutasi input; mint token lain
  diabaikan.
- `holder_status.apply_manual_scan()`: salinan status dengan token yang cocok
  diganti view terbaru (token baru ditambahkan, token lain tidak dihapus,
  file snapshot & cache publish tidak disentuh).
- `pages/5_🧮_Holder.py` + `app.py` memakai overlay itu sebelum render → kartu
  metrik, badge HATI-HATI/BAHAYA, watchlist, dan Chart LP setuju dengan
  grafik; caption menandai **scan manual barusan**.
- Guard arah turun (opsi B) **belum** dikerjakan; keputusan user dicatat
  sebagai `TODO(alerts)` di atas `validate_alert_with_volume`: bila dust % MC
  naik tetapi `dust_count`/pangsa supply tidak naik → **annotate, bukan
  reject**. Prasyaratnya `dust_pct_supply` terisi untuk sumber Helius (DAS
  tidak mengembalikan `amount_percentage`; `holder_analysis.py` meng-hardcode
  0.0 — hanya GMGN yang mengisi).

### Tes
27 tes murni baru (`tests/test_holder_status_view.py`) + 2 tes AppTest
(`tests/test_holder_page.py`): sebelum klik kartu 1,16% / 90 wallet, sesudah
klik 0,90% / 130 wallet + caption "scan manual barusan" + badge HATI-HATI
(bukan BAHAYA); scan manual token lain diabaikan; snapshot yang lebih baru
mengalahkan scan manual; status asli tidak termutasi. Total **398 tes lulus**.

## 2026-09-03 — Konfirmasi volume + volatilitas untuk alert dust

Permintaan user: ambang dust 0,25 pp terlalu berisik; sinyal harus
divalidasi volume + harga + volatilitas dulu tanpa mengorbankan kecepatan
reaksi (< 5 menit). Ambang dust (0,25 / 0,50 / ±1,00 pp) **tidak diubah** —
konfirmasi ini dipasang di belakangnya, jadi filternya tidak saling menutupi.

### Aturan
- `telegram_alerts.validate_alert_with_volume(...)` →
  `VolumeValidation(is_valid, confidence_score, reason, verified, details)`.
  Gerbang keras: **dump** = volume 4 jam ≥ 2× `avg_volume_7d` **dan**
  perubahan harga ≤ −1%; **akumulasi** = volume ≥ 1,5× **dan** buy pressure
  > sell pressure. `avg_volume_7d` diartikan sebagai rata-rata volume
  **per window 4 jam** selama 7 hari (bukan angka harian) supaya sebanding
  dengan `volume_4h`.
- Skor: 0,70 dasar + ≤0,15 kekuatan volume + ≤0,10 harga/tekanan beli +
  0,20 bila volatilitas tinggi **dan** arah harga mendukung; gagal gerbang →
  skor diagnostik ≤0,40. Ambang lolos 0,70, naik ke 0,80 bila
  `price_stddev_4h > 3%`. Contoh di prompt (stddev >3% + dust ≥0,25 pp →
  0,90 → lolos) direproduksi persis; dump tanpa volume (0,85 < 1,0 → 0,67)
  dan akumulasi tanpa tekanan beli (0,62) ditolak.
- Volatilitas tinggi **tanpa** dukungan arah harga tidak memberi bonus:
  kalau diberi, ambang 0,80 tidak pernah menyaring apa pun (terukur —
  akumulasi marginal menjadi 0,702 < 0,80 → ditolak).
- `evaluate_4h_rules` / `evaluate_baseline_rule` memakai gerbang itu;
  baseline shift divalidasi mengikuti arah perubahan (naik = dump, turun =
  akumulasi). Kandidat yang ditolak di-log `Dust signal rejected …` (dust,
  volume, harga, alasan) dan dicatat ke `alert_state.rejected_signals`
  (maks 8/token) untuk audit false positive.
- Kebijakan data hilang (keputusan user): alert **tetap dikirim**, diberi
  baris `⚠️ TIDAK TERVERIFIKASI` + `Konfirmasi: ⚠️ data tidak lengkap`
  (`ALLOW_UNVERIFIED_ALERTS = True`). `volume_4h = 0` diperlakukan sebagai
  data valid, bukan data hilang → gerbang gagal.
- Dedup: event id bucket 4 jam tetap, ditambah **jeda minimum 1 jam** per
  token+jenis(+arah) lewat `alert_state.last_sent`. Sebelumnya dua alert
  identik bisa terkirim berjarak ±2 menit di dua sisi batas bucket.

### Data
- `holder_history.calculate_volatility_metrics(candles, historical, ...)`:
  16 candle hourly → `price_stddev_4h`, `price_range_4h`,
  `intra_hour_volatility(+_max)`, `price_change_4h_pct`, `volume_4h`,
  `missing_hours`, `stale`, `available`, `high_volatility`. Candle < 2 atau
  harga 0 → `available: False` (bukan stddev 0 yang tampak "tenang");
  candle basi (> `MAX_AGE_HOURS`) → `stale: True`.
- `core.get_hourly_candles()` baru; `get_daily_candles()` kini agregasi dari
  candle hourly yang sama (satu endpoint, dua bentuk, tanpa double-fetch).
- `alert_context.py` (baru): `build_market_context()`, `volume_from_candles()`,
  `volume_from_dexscreener()`, `volume_from_daily_rows()`,
  `pressure_from_txns()`, `compact_signal()`, `market_context_provider()`.
  Urutan sumber: candle hourly GeckoTerminal → DexScreener (sudah diambil
  `analyze_token`, tanpa request tambahan) → `daily_effort.json`.
  Ditarik **lazy**: hanya token yang punya kandidat, memo 1× per token per run.
- `holder_analysis.analyze_token` kini meneruskan ringkasan `market`
  (volume, price_change, txns, pair_addresses) di hasil analisis;
  `holder_status.snapshot_status` menyimpan `tokens[mint].market_signal`
  berdampingan dust % MC; `scripts/scan_holders.py` menyuntikkan provider
  dan mencetak `unverified=`, `rejected=`, `konteks=N token (X ms)`.

### Review optimasi (diminta user)
| Fungsi | Temuan | Tindakan |
|---|---|---|
| `core.matching_dexscreener_pairs` | Sort O(n log n) atas ≤30 pair; heap/single-pass top-1 diukur **tidak lebih cepat** (5,6 vs 5,2 µs n=10; 271 vs 263 µs n=500) — biaya dominannya `_dex_liquidity_usd` per pair, bukan sort. `get_market` juga butuh seluruh urutan untuk `pair_addresses`. | Tidak diubah (terukur) |
| `core.get_daily_candles` | Batas hari UTC benar (`datetime.date()`); diverifikasi 31 Des→1 Jan, 28→29 Feb kabisat, 30→31 Des, awal/akhir Maret. **Tiga bug nyata**: (1) sel `null` GeckoTerminal → `float(None)` TypeError **di luar** blok try; (2) `limit_days=0` mengembalikan seluruh riwayat (`[-0:]`); (3) timestamp duplikat menghitung volume dua kali. Hari UTC yang masih berjalan ikut ter-return (sudah disaring `cvd_daily.completed_dates`). | Diperbaiki + guard milidetik, dicatat di docstring |
| `holder_analysis.classify_holders` | Konversi USD sudah sekali per wallet di fetcher (bukan di sini); yang boros ±9 lintasan atas holder yang sama. Single-pass **dengan `_float()` per baris justru lebih lambat** (4,15 vs 2,86 ms / 12k holder) karena overhead pemanggilan fungsi; single-pass ramping = **1,94 ms**. | Single-pass ramping; identik di 500 trial acak + 12k holder sintetis |
| Dedup alert | Event id `holder-dust:mint:kind:bucket[:arah]` disimpan di `alert_state.sent_event_ids` (maks 96), hanya dicatat setelah kirim sukses → gagal kirim dicoba lagi. Granularitasnya bucket 4 jam, bukan 1 jam. | Jeda minimum 1 jam (`MIN_RESEND_SEC`) + `last_sent` |
| `telegram_alerts._event` | `wallet_movements()` (O(W), W ≤ 800 address) dihitung dua kali untuk kandidat yang sama. | Dihitung sekali, diteruskan ke `_event` |
| `telegram_alerts.compact_wallet_snapshot` | `sorted(dust, key=…)` identik dipanggil dua kali. | Diurut sekali |
| `telegram_alerts.send_telegram_message` | 429 `retry_after` tidak dihormati (hanya di-log; event dikirim ulang run berikutnya). | `TODO(alerts)` di kode |
| Beban API candle | GeckoTerminal publik ±30 req/menit; run yang memicu banyak sinyal bersamaan bisa tersentuh (lazy fetch sudah membatasi ke kandidat saja). | `TODO(alerts)` throttle |
| Store JSON | `holder_history.json` / `holder_status.json` ditulis ulang penuh tiap run (atomic write). | Belum perlu; dipantau |

### Tes
369 tes lulus (sebelumnya 228). Baru: `test_volume_validation.py` (33),
`test_volatility_metrics.py` (17), `test_alert_context.py` (32),
`test_alert_gating.py` (27), `test_alert_pipeline.py` (8),
`test_core_candles.py` (24) — mencakup edge case yang diminta: volume 0,
`avg_volume_7d` 0/None (pool baru), NaN/inf, candle bolong (price gap),
candle < 2, candle basi, timestamp milidetik, payload DexScreener rusak,
provider gagal, cooldown 1 jam, dan lazy-fetch (provider tidak dipanggil
bila tidak ada kandidat). `test_alert_pipeline.py` juga memastikan
integrasi end-to-end tidak menulis `holder_status.json` asli.

## 2026-09-03 — Kronologi holder sejak snapshot awal (scan FULL)

- Setelah `Scan holder FULL` pertama, halaman Holder Analytic menandai
  **snapshot awal** (data pembanding belum cukup). Baseline tidak ditimpa.
- Scan FULL berikutnya menambah interval kronologi: dust % MC, wallet
  yang balance-nya naik/turun, wallet baru, saldo 0 / tidak teramati, dan
  perpindahan kategori. Perbandingan memakai **balance token**, bukan
  hanya USD, supaya kenaikan harga tidak dianggap pembelian.
- Wallet LP/pool/noise dikecualikan. Setiap movement punya tautan Solscan
  (address penuh, URL-encoded). Payload snapshot/movement dibatasi;
  sampled/truncated dijelaskan. Schema history lama tetap bisa dibuka.
- Modul baru `holder_chronology.py`; persistensi tetap di
  `holder_history.py` / `holder_status.py` (versi compact).


## 2026-09-01 — Holder Analytic (dust) + Scan Meteora

- UI fokus dust: watchlist ringkasan jumlah + % MC, badge 1%/2%, sparkline
  4 jam; Trending/Degen tanpa kolom holder/12 jam; CVD tanpa Holder Analytic.
- Halaman baru `pages/5_🧮_Holder.py`. History di `holder_history.json`.
- Scan Meteora DLMM 24h+1h, hide dust ≥ 1% MC, shortcut Meteora + HawkFi.
- Kohort Crab+Fish di-freeze 4 jam (sisa token, bukan USD).

## 2026-08-19 — Port sinyal SMART SEROK + watchlist bersih

- Mengosongkan `watchlist.json` (semua token lama dihapus).
- Tambah CA manual: field ticker dihapus; `fetch_token_symbol()` memakai
  DexScreener (`get_market`) sehingga symbol terisi otomatis.
- Scanner realtime tidak lagi memakai wash-collapse / SBR. Engine baru
  `serok_engine.py` meniru ekstensi SMART SEROK v9.1.3 (bar 1H, R-spike,
  battle P65).
- Telegram: 🔴 WASPADA DUMP, 🟢 SIAP2 PUMP, ⚔️ BATTLE TERJADI — satu
  alert per `event_id`, format rapi + link GMGN/DexScreener + detail bar/MC.
- Cron GitHub Actions `*/15 * * * *`. Window fetch 48 jam.
- Tes: `tests/test_serok_engine.py`; payload Telegram dan UI disesuaikan.

## 2026-08-18 — Watchlist utama mengikuti scanner realtime

- Akar masalah: cron harian diganti scanner 10 menit, tetapi `app.py` masih
  mengklasifikasi `daily_effort.json` (terakhir 2026-08-16) sementara
  `last_scan_result.json` hanya ada di Actions cache.
- Scanner kini mem-publish snapshot `reversal_status.json` ke ref
  `reversal-live` setelah setiap scan.
- Watchlist halaman utama menampilkan REVERSAL UP/DOWN, setup, confidence,
  CVD bersih, wash-collapse, dan breakdown wallet — sama dengan payload
  Telegram — plus tombol muat ulang.

## 2026-08-17 — Realtime bidirectional reversal

- Port engine SMART SEROK ke `reversal_engine.py`: normalisasi GMGN, re-derive
  SOL rusak, FIFO wash matcher 60 detik, clean CVD, daily parity, dan rolling
  6h vs prior 24h.
- Tambah sinyal simetris `REVERSAL_UP` dan `REVERSAL_DOWN`, setup
  accumulation/distribution, serta guard minimum tx/volume.
- Tambah scanner incremental terkompresi, payload Telegram dua arah, dan state
  machine 2-scan/transition-only/cooldown 18 jam.
- Workflow lama harian diganti rolling scan setiap 10 menit dengan Actions
  cache untuk state dan trade window.
- Validasi offline SISYPUSS cocok dengan reference: 08-16 CVD sekitar -22 SOL,
  wash 15.2%; 08-17 clean CVD sekitar +11.8 SOL, wash 3.0%, `REVERSAL_UP`.


## 2026-08-15 — Overhaul Efisiensi Anomali

- Mengganti seluruh logika deteksi dengan R = |ΔCVD| / |ΔHarga%| per hari WIB.
- Menambahkan `effort_detector.py`, persistence idempoten 30 hari, dan S1–S5.
- Menulis ulang cron menjadi sekali sehari pukul 00:00 WIB.
- Menulis ulang Telegram sehingga hanya S1–S4 yang dikirim.
- Mengubah dashboard menjadi watchlist effort dan listing GMGN tanpa ranking.
- Menambahkan chart harga/CVD dual-axis dan chart ratio tujuh hari.
- Memangkas layer CVD menjadi fetch/normalisasi trade yang dibutuhkan saja.
- Menghapus state, detector, workflow, dokumentasi, dan test generasi lama.
- Menambahkan unit test formula, boundary, insufficient data, WIB, persistence,
  join candle/CVD, dan format Telegram.

## 2026-08-15 — Perbaikan Baseline Stabil (arena/01a00357-wallet-depth)

- Menambahkan `MIN_BASELINE_RATIO = 0.05` dan `MIN_BASELINE_CVD_SOL = 1.0`.
- Menambahkan validasi baseline (aturan 1–6) ke `effort_detector.py`.
- Menambahkan `baseline_status`, `baseline_reason`, dan `raw_multiplier` ke output.
- Mengubah `signals.py` dengan `should_send_telegram()` (defensive gate).
- Memperbarui `scripts/update_cvd.py` agar hanya mengirim Telegram jika
  `baseline_status == "stable"` dan sinyal S1–S4.
- Memperbarui `app.py` dan `pages/4_📊_CVD.py` dengan badge baseline,
  alasan, dan tampilan multiplier yang ditolak.
- Memastikan S1–S4 hanya keluar saat `baseline_status == "stable"`.
- Memastikan chart tidak menampilkan marker bullish/bearish untuk baseline
  yang ditolak (`unstable` / `incompatible_direction`).
- Menambahkan test wajib: fixture MIM, ratio kecil, direction berbeda,
  stable S1, boundary, current ranging, dan defensive Telegram.
- Memperbarui dokumentasi (`AGENTS.md`, `README.md`, `PROMPT_EFFORT_ANOMALI.md`).

## 2026-08-15 — Link eksternal, shortcut CVD & fetch manual (arena/01a0039e-wallet-depth)

- Menambahkan `links.py`: helper bersama `gmgn_token_url`, `dexscreener_token_url`,
  `safe_url_part` (URL-encoding), `cvd_shortcut_query`, dan `external_links_html`
  (anchor `target="_blank"`) sehingga URL CA aman dan tidak duplikasi.
- Watchlist (`app.py`): menampilkan link ringkas GMGN dan DexScreener di setiap
  baris tanpa mengganggu tombol Chart/Hapus.
- Trending & Degen (`trending_ui.py`): menambahkan link GMGN, DexScreener, dan
  tombol shortcut `📊 CVD` yang membuka `pages/4_📊_CVD.py` dengan token
  terpilih (`?mint=...` + `effort_mint`). Shortcut bekerja meski token belum ada
  di watchlist dan tidak mengubah watchlist secara diam-diam.
- Halaman CVD (`pages/4_📊_CVD.py`):
  - Seleksi token dari query param/session, termasuk token di luar watchlist
    (dengan warning + tombol tambah eksplisit).
  - Panel "Fetch data manual": input hari 2–30 (default 7), tombol "Fetch
    sekarang", spinner/status, tanpa fetch otomatis saat page load.
  - Menampilkan log manual per fetch (timestamp WIB, tahapan, jumlah trades,
    rows dibuat/di-update, durasi, status, error) yang persisten dalam session.
- Refactor `scripts/update_cvd.py`: menambahkan `refresh_single_token` (pipeline
  reusable satu token: lookup market/pool → GMGN trades + fallback Helius →
  candle harian → agregasi CVD → `build_effort_rows` → merge idempotent) yang
  dipakai halaman CVD tanpa subprocess. Menambahkan `compute_lookback_window`
  (batas WIB, menghormati jumlah hari, tanpa hari berjalan) dan `_redact` agar
  API key/credential tidak bocor ke log.
- Fetch manual tidak mengirim alert Telegram dan tidak menyentuh watchlist.
- Menambahkan test `test_links.py` dan `test_manual_refresh.py` (URL, shortcut,
  lookback, refresh sukses/fallback/error, idempotent, tanpa alert, redaksi key).

## 2026-08-15 — Backtest history rentang tanggal di halaman CVD (arena/01a0039e-wallet-depth)

- Menambahkan `compute_date_window` dan `_resolve_window` di `scripts/update_cvd.py`
  untuk mendukung fetch dengan rentang tanggal inklusif dari–sampai (WIB), dengan
  clamp batas atas ke kemarin (hari berjalan tidak pernah diambil) dan clamp span
  maksimal 30 hari.
- `refresh_single_token` kini menerima `start_date`/`end_date`; `run_daily` (cron)
  tetap memakai `lookback_days=4` via `_resolve_window` sehingga perilaku cron
  tidak berubah.
- Halaman `pages/4_📊_CVD.py`: panel "📅 Rentang tanggal & backtest" untuk memilih
  dari–sampai, tombol "🔍 Lihat & fetch" yang mengambil data untuk rentang tersebut
  secara idempoten, lalu menampilkan history (metrik, chart harga/CVD, chart ratio,
  dan tabel data) untuk rentang terpilih. Fetch hanya terjadi saat tombol diklik
  (tidak otomatis saat page load).
- Panel "🔁 Fetch data manual" (last-N-days, default 7) tetap dipertahankan.
- Menambahkan test `DateWindowTest` (rentang inklusif, clamp ke kemarin, clamp span,
  urutan terbalik, dan pass-through window ke pipeline fetch).

## 2026-08-15 — Batas hari market (UTC) & backtest start+N hari (arena/01a0039e-wallet-depth)

- Mengubah batas hari dari Asia/Jakarta (WIB) menjadi hari market 00:00–23:59 UTC
  (sesuai Helius/Solscan) di seluruh pipeline:
  - `cvd_daily.py`: `MARKET_TZ = timezone.utc`; `day_key`, `completed_dates`,
    `build_effort_rows`, `fallback_candles_from_swaps` memakai batas UTC.
    Alias lama (`WIB`, `day_key_wib`, `completed_wib_dates`) dipertahankan.
  - `core.py`: `get_daily_candles` menggabungkan candle GeckoTerminal per hari UTC
    (alias `get_daily_candles_wib` dipertahankan).
  - `scripts/update_cvd.py`: `MARKET_TZ`, `_now_market`, `_as_market_midnight`,
    `compute_lookback_window`, `compute_date_window`, log `ts_market`.
- Halaman `pages/4_📊_CVD.py`: panel "📅 Backtest history" kini input tanggal awal
  (Dari, market/UTC) + "Berapa hari ke depan" (2–30), lalu fetch otomatis saat
  input berubah (idempoten, tidak mengirim alert, tidak fetch saat load pertama).
  History menampilkan metrik, chart harga/CVD, chart ratio, dan tabel data untuk
  rentang start → start+N-1 (dibatasi maksimal 30 hari dan tidak melewati kemarin).
- Memperbarui caption UI, `app.py`, `AGENTS.md`, `README.md`, `PROMPT_EFFORT_ANOMALI.md`
  ke terminologi hari market UTC.
- Menyesuaikan test ke batas UTC (`test_daily_pipeline.py`, `test_manual_refresh.py`).

## 2026-08-15 — Cron ke 00:00 UTC & tombol fetch rentang eksplisit (arena/01a003cb-wallet-depth)

- Menyelaraskan cron harian dengan batas hari market: `.github/workflows/daily-effort.yml`
  kini `0 0 * * *` (00:00 UTC / 07:00 WIB) — berjalan tepat setelah hari market
  berganti, bukan lagi `0 17 * * *` (jadwal lama untuk batas WIB).
  `DEPLOY.md` dan `prompt_overhaul_wallet_depth.md` ikut diperbarui ke
  terminologi 00:00 UTC (07:00 WIB).
- `pages/4_📊_CVD.py`: menambahkan tombol "🔍 Fetch rentang ini" di panel
  backtest yang memanggil `refresh_single_token(..., start_date=..., end_date=...)`
  untuk rentang yang sedang dipilih (sebelumnya hanya auto-fetch saat input
  berubah dan panel fetch manual yang memakai last-N-days).
- History backtest kini membedakan tiga status: fetch gagal → `st.error` dengan
  pesan error (sudah di-redact), fetch sukses tapi 0 baris → info "tidak ada data",
  dan belum pernah fetch → ajakan klik tombol / ubah rentang. Auto-fetch saat
  input berubah tetap dipertahankan; tombol dan auto-fetch berbagi jalur yang sama
  dan menyimpan hasilnya di `session_state["bt_result"]` (terpisah dari
  `manual_result` untuk panel fetch manual last-N).
- Log fetch manual (`manual_result` / `_render_manual_log`) tetap memakai
  `ts_market` dan tidak mencatat credential (error di-redact `_redact`).
- Menambahkan test: `DateRangeRefreshTest` (sukses/error/redaksi, idempoten,
  clamp 30 hari, tidak termasuk hari berjalan, tanpa alert Telegram) dan
  `test_cvd_page.py` (AppTest: tombol rentang memakai start/end, auto-fetch saat
  input berubah, jalur error/data/tidak-fetch, dan panel manual tetap lookback).

## UI kontras (teks hitam)

- `app.py` & `trending_ui.py`: nama token (`$SYMBOL`) sebelumnya memakai warna
  `#f8fafc` (hampir putih) sehingga tidak terlihat di background terang. Semua
  teks tabel watchlist dan listing GMGN kini `#000000` (hitam), termasuk mint
  pendek, header kolom, tanggal, nilai metrik, sub-label, dan alasan baseline.
- Link eksternal memakai biru gelap `#1d4ed8` (hover hitam + underline), badge
  netral memakai background terang `#e2e8f0` dengan teks hitam, garis pemisah
  `#cbd5e1`, dan persentase 24h memakai hijau/merah gelap agar tetap terbaca.
- Ditambahkan `.streamlit/config.toml` (`base = "light"`, `textColor #000000`)
  supaya tema selalu terang dan teks default hitam. Hero banner tetap gradasi
  gelap dengan teks putih.

## Kolom baseline: detail kejadian

- `effort_detector._build_result` kini menyertakan konteks hari baseline:
  `baseline_date`, `baseline_ratio`, `baseline_price_chg_pct`,
  `baseline_cvd_delta`, `baseline_direction`, dan `baseline_gap_days`
  (jarak hari ke hari N). Field murni informatif — formula R, multiplier,
  ambang 2,0/0,5, dan klasifikasi S1–S5 tidak berubah.
- `app.py`: kolom watchlist "Baseline" menjadi "Baseline & detail". Setiap baris
  menampilkan fakta hari baseline (`Base <tanggal> (<n>h lalu) · Δ<harga>% ·
  CVD <sol> SOL`). Untuk sinyal **selain netral** ditambahkan narasi kejadian:
  - S1/S3: "butuh SOL M× lebih banyak per 1% …" (supply/demand diserap),
  - S2/S4: "hanya perlu M× effort per 1% …" (buyer/seller absen),
  - ABSORBSI_LANGSUNG: CVD vs pergerakan harga (tanpa baseline),
  - SELLING_EXHAUSTION: tanggal flush, CVD flush → CVD hari ini, sisa %.
  Baris netral/insufficient tetap hanya fakta baseline plus alasan penolakan
  (noise, baseline tidak cukup) seperti sebelumnya.
- Lebar kolom watchlist disesuaikan agar teks detail tidak terlalu terpotong.
- Test baru `tests/test_baseline_detail.py`: field baseline (stabil, kosong,
  flush exhaustion) dan AppTest render kolom (narasi muncul untuk non-netral,
  tidak muncul untuk netral).

## 2026-08-16 — Detektor 3 sinyal bottom (arena/01a00a8e-wallet-depth)

- Mengganti total framework Efisiensi Anomali (R/M/baseline/S1–S5/ABSORBSI
  LANGSUNG/PENYERAPAN) dengan **3 sinyal bottom tervalidasi empiris**:
  🟢 SELLER_EXHAUSTION (CVD runtuh vs flush ≤ -30 SOL/5 hari + volume kering
  ≤40%), 🟣 REVERSAL (runtuh sama + volume naik ≥130%), 🔵 AKUMULASI
  (CVD ≥ +5 SOL, harga ≤ +0.5%, volume naik ≥130%). Urutan cek persis
  exhaustion → reversal → akumulasi → "—".
- Threshold final di `effort_detector.py` sesuai spesifikasi (30/0.40/5/0.5,
  0.40/1.30, 5.0/0.5/1.30, whale 40%, anti-wash 3× MC close bila MC tersedia).
- Perbandingan volume antar-hari kini **selalu USD** (`amount_usd`), bukan
  SOL: `cvd.py` membawa `amount_usd` pada tiap swap (GMGN: langsung dari API /
  quote terverifikasi; Helius fallback: estimasi SOL×harga SOL),
  `cvd_daily.py` mengagregasi `volume_usd`/`buy_usd`/`sell_usd` per hari.
- Batas hari tetap 00:00 UTC; alias peninggalan WIB (`day_key_wib`,
  `completed_wib_dates`, `get_daily_candles_wib`, `WIB`) dihapus.
- 4 penanda on-chain ditangkap per trade (`maker_tags`, `maker_token_tags`,
  `maker_event_tags`) lalu diagregasi harian: `smart_money_buy`, `fresh_buy`,
  `bot_sell`, `mev_noise` — info output saja, bukan syarat sinyal.
- `marketcap_close` harian = close × supply (supply ≈ MC/harga DexScreener)
  untuk gerbang anti wash-trade; tanpa MC, gerbang dilewati sesuai spesifikasi.
- Scan seluruh window: `classify_all` memberi sinyal per hari (hari pertama
  "—"); `classify_effort` = verdict hari terakhir.
- Telegram (`signals.py`) hanya untuk 3 sinyal, format konsisten "⚡ BOTTOM
  TERDETEKSI — $SYMBOL" + emoji 🟢/🟣/🔵 + hari/flush + `CVD: X SOL |
  Volume: Y% dari kemarin` + link GMGN; gate menolak "—" dan semua sinyal lama.
- UI: watchlist `app.py` menampilkan sinyal (badge warna per sinyal), CVD,
  volume vs kemarin, narasi flush + penanda whale/on-chain; halaman CVD
  menampilkan chart harga/CVD + chart volume USD, tabel harian dengan kolom
  `volume_usd`/`marketcap_close`/4 penanda, CSV + rekapan teks format baru
  (`# <date>  <SIGNAL> | Δ<+%>% | CVD <+x> | vol <y>% dari kemarin`).
- Storage `daily_effort.json` tetap upsert idempoten (window 30 hari; kini
  bernama `STORAGE_WINDOW_DAYS`, bukan sinyal retensi).
- Test: `tests/test_effort_detector.py` ditulis ulang (exhaustion/reversal/
  akumulasi + boundary 40%/130%/+5 SOL, flush lookback 5, price cap, wash
  gate, whale, tag passthrough, UTC, export, rekapan, storage);
  `test_daily_pipeline.py` menambah uji volume USD, penanda on-chain,
  marketcap_close; `test_effort_alert.py` untuk format/gate Telegram baru;
  `test_baseline_detail.py` digantikan `test_signal_detail.py` (AppTest badge
  & detail); `test_manual_refresh.py` diperbarui untuk wiring supply.

# 2026-08-30 — Silent accumulation 12 jam (buang semua sinyal)

- Menghapus seluruh sinyal (SMART SEROK / reversal / effort bottom) dan
  notifikasi Telegram: `signals.py`, `serok_engine.py`, `reversal_engine.py`,
  `reversal_state.py`, `reversal_status.py`, `price_structure.py`,
  `effort_detector.py`, `scripts/realtime_reversal.py`,
  `scripts/backtest_confidence.py`.
- Baru: `silent_accumulation.py` (holder real vs dust + flow 12 jam),
  `silent_status.py` (snapshot `silent-live`), `scripts/scan_silent.py`
  (cron 15 menit), `daily_store.py` (storage harian tanpa sinyal).
- Dashboard `app.py` & `trending_ui.py`: kolom Real >$10 / Dust / Dust %MC /
  Status 12 jam saat scan Trending & Degen.
- Endpoint `token_holders` diverifikasi paginasi `next` (limit 1000/page).

# 2026-09-01 — Grafik holder + scan FULL dengan baseline permanen

- `holder_history.py`: titik history kini membawa `holder_count` dan
  `buckets` (jumlah holder per range USD) sehingga komposisi holder bisa
  digambar sepanjang waktu. Baru: `bucket_counts`, `detail_snapshot`,
  `baseline_for_mint`, `latest_detail_for_mint`, `bucket_delta`,
  `bucket_series`, konstanta `FULL_SCAN_MAX_WALLETS = 100_000`.
- Scan manual halaman Holder = **FULL** (paginasi Helius sampai habis) dan
  memanggil `ingest_many(..., detail=True)`. Detail scan pertama disimpan
  sebagai `baseline` per token dan **tidak pernah ditimpa**; scan FULL
  berikutnya hanya memperbarui `latest_detail`.
- `scripts/scan_silent.py` (cron 15 menit) memakai `detail=False`: hanya
  menambah titik perubahan, baseline milik user tetap utuh.
- `pages/5_🧮_Holder.py`: seksi **📊 Grafik holder** (total/dust/real/pilar +
  area komposisi bucket) dan **🧱 Distribusi holder (scan FULL)** (bar chart
  Wallet Depth, metrik tier, tabel Δ bucket vs baseline).
- `silent_accumulation.fetch_holders_helius`: pengaman paginasi tidak lagi
  dipatok 60 halaman — ikut `max_wallets` (batas keras 200 halaman).
- Tes: `tests/test_holder_page.py` (AppTest) + kasus baru di
  `tests/test_holder_history.py`.

# 2026-09-03 — Bersih-bersih silent accumulation + ambang dust tunggal

- Ambang dust hanya satu: **≥ 1% MC = BAHAYA** (sekaligus filter hide
  Scan Meteora). Ambang 2% / label HATI-HATI / DUMP dihapus.
- Hapus sisa silent accumulation: `fetch_12h_flow`, `detect_silent`,
  filter SILENT/LP/PUMPDUMP, `enrich_rows`, bridge
  `scripts/realtime_reversal.py`. Rename `silent_accumulation.py` →
  `holder_analysis.py`, `silent_status.py` → `holder_status.py`
  (`holder_status.json`, ref `holder-live`), `scripts/scan_silent.py` →
  `scripts/scan_holders.py`.
- Scanner cron exit non-zero bila semua token 0 holder / publish gagal;
  dashboard menampilkan peringatan bila data cron kosong.
- Workflow perlu env `GITHUB_TOKEN` + `HELIUS_API_KEY` (harus di-commit
  manual — GitHub App tanpa permission `workflows`).

# 2026-09-03 — Ambang HATI-HATI 0,5% + card Chart LP (watchlist Meteora terpisah)

- `holder_history.py`: dua ambang dust — `DUST_CAUTION_PCT = 0.5`
  (**HATI-HATI**, badge kuning, tidak disembunyikan) dan `DUST_DANGER_PCT =
  1.0` (**BAHAYA**, `hide=True` → tetap disaring dari Scan Meteora).
  `dust_flag` mengembalikan level `ok`/`caution`/`danger`/`unknown`; helper
  baru `dust_level_rank` untuk sorting. Alias lama `DUST_CAUTION_PCT =
  DUST_DANGER_PCT` diganti nilai sebenarnya.
- Badge & grafik mengikuti: `app.py` (`.dust-caution`, panah ↑ juga untuk
  caution), `pages/5_🧮_Holder.py` (warna badge + `axhline` 0,5% pada grafik
  dust 4 jam), caption/hero menyebut kedua ambang.
- Modul baru `lp_watchlist.py` (murni data + figure, tanpa Streamlit):
  `split_watchlist` (token `source=meteora`/`lp`/`chart_lp` → card LP,
  sisanya watchlist holder; tidak ada token yang muncul dua kali),
  `build_lp_row`/`lp_card_rows` (dust % MC, dust count, Δ 4 jam & Δ total
  dalam poin persentase, level, `has_chart`), `sort_lp_rows` (BAHAYA →
  HATI-HATI → AMAN lalu % MC terbesar), `lp_summary`, `lp_chart_figure`
  (garis dust % MC + batang wallet dust + garis ambang 0,5%/1%),
  `lp_overlay_figure` (semua token LP dalam satu grafik).
- `app.py`: card **🌊 Chart LP — Watchlist Meteora** di bagian paling atas
  (`st.container(border=True)`) berisi header pill (jumlah token / BAHAYA /
  HATI-HATI / dust naik), overlay chart, form **➕ Tambah CA manual ke Chart
  LP**, dan baris per token: MC + waktu scan, dust count, Hold %MC + badge,
  Δ 4 jam & total, sparkline, expander grafik per token (+ Wallet Depth),
  tombol 🧮 / 📋 (pindah ke watchlist holder) / ✕.
- Watchlist holder di bawah hanya berisi token non-LP, kolom tombol bertambah
  🌊 (pindah ke Chart LP). Form **➕ Tambah token** punya radio *Masuk ke
  card* (📋 Watchlist Holder / 🌊 Chart LP) + validasi CA (Solana base58 /
  EVM) lewat `_ca_error`; pesan push-error kini membaca kunci `msg` yang
  benar dari `get_last_push_error()`.
- Scan Meteora: ⭐ memakai `source=meteora` → token langsung masuk Chart LP;
  caption menyebut badge HATI-HATI dan card tujuan.
- `watchlist.py`: op journal baru `"source"` (`set_watchlist_source(ca,
  source)`) untuk pindah card — `_apply_ops` menimpa `source` tanpa membuat
  entri baru, `_op_is_applied`/`_prune_pending` membuang op setelah repo
  mencerminkannya, dan `_journal_many` melebur op `source` ke op `add` yang
  belum ter-commit supaya entri baru tidak hilang. `add_to_watchlist`
  mengambil symbol dari DexScreener setiap kali symbol tidak diketahui
  (sebelumnya hanya `source="manual"`).
- Tes: `tests/test_lp_watchlist.py` (split/order/ringkasan/figure/ambang),
  `tests/test_watchlist_source.py` (op `source`, prune, journal merge,
  `set_watchlist_source`), `tests/test_lp_card_ui.py` (AppTest: card LP
  terpisah, badge HATI-HATI/BAHAYA, grafik, tombol pindah, radio tujuan
  tambah manual, validasi CA), dan `DustFlagTest` diperbarui untuk tiga
  level. Total 228 tes lulus.
