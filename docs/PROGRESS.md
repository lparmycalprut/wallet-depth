# PROGRESS — riwayat keputusan & status

Catatan berjalan supaya sesi baru tahu **sudah sampai mana** dan **kenapa
sesuatu dibuat begitu**. Tambahkan entri baru di ATAS, jangan hapus yang lama.

Format tiap entri: apa yang berubah · kenapa · bukti verifikasi · sisa PR.

---

## 2026-08-13 — CVD: Pure Accumulator Growth graph + Tag-Aware Flow (poin filter)

### Masalah
- Grafik "👥 Top 100 Holder / Supply Lock" di halaman CVD punya teks
  tumpang tindih (judul vs caption) dari sesi sebelumnya.
- Owner ingin grafik itu diganti dengan **pertumbuhan pure accumulator per
  hari** (yang beli tanpa jual >10%).
- Ingin poin tambahan untuk filter: akumulator/distributor bertag
  smart money / bundler / top holder # / fresh wallet diberi poin tersendiri.

### Yang berubah
1. `pages/4_📊_CVD.py` — section `👥 Top 100 Holder / Supply Lock` (KPI +
   tabel 100 top holder + re-evaluasi Pilar 3) **dihapus**.
2. Ganti dengan **`🐳 Pure Accumulator Growth (per hari)`** — grafik
   `pure_accumulator_growth(..., bucket_s=86400)`: wallet baru/hari +
   kumulatif + SOL dibeli. Tanpa plotly-title (judul via `st.markdown`),
   jadi judul tidak mungkin tumpang tindih caption.
3. Tambah **`🏷️ Tag-Aware Flow — poin filter`** — `tagged_flow_report()`:
   akumulator (beli ≥ 0.1 SOL, jual ≤ 10%) & distributor (jual ≥ 0.1 SOL,
   beli ≤ 10%) diberi tag dari `maker_tags` GMGN + top-holder rank + umur
   wallet. Agregat: `smart_accum_buy_sol`, `bundler_dist_sell_sol`,
   `trusted_accum_share`, `tagged_*_points`, dan **`tag_score` 0–100** untuk
   dipakai sebagai poin tambahan filter Setup Emas.
4. `cvd.py` — `tag_wallet_meta_tags`, `tag_wallets`, `load_tag_points`,
   `wallet_tag_points`, `tagged_flow_report`, konstanta `SMART_TAGS` /
   `BUNDLER_TAGS` / `FRESH_TAGS` / `TAG_FLOW_WEIGHTS` / `TAG_FLOW_FLOOR` /
   `DEFAULT_TAG_POINTS`. Poin per tag dapat dituning via `config.json`
   `tag_points`.
5. Perbaiki overlap legend/title di `render_daily_chart` &
   `render_tx_dominance` (margin atas 84, legend y 1.16).

### Verifikasi
`python tests/test_tag_aware_flow.py` (7 tes) + semua suite lama hijau
(16 file + unittest holder_split 18 tes) + AppTest render idle halaman CVD
tanpa exception.

### Sisa PR
- `tag_score` belum di-`AND`/ditambahkan ke gerbang Telegram Setup Emas
  7/7 (masih ditampilkan sebagai poin di halaman). Owner menentukan bobot
  / ambang sebelum dipakai di cron.

---

## 2026-08-12 — Setup Emas: tape seimbang + ekspansi terserap (SISYPUSS)

### Masalah
SISYPUSS 10 Agu 2026 (lalu pump 11 Agu) gagal notifikasi: Buy TX 49.7%
< 52%, dan vol +146% + CVD turun dianggap ignition / gagal LPS.

### Yang berubah
1. `BUY_TX_MIN_PCT` 52 → **49** (buy≈sell = absorption, bukan dump).
   Callcat/Froge tetap ~42% + avg buy > sell = STEALTH DUMP.
2. P3 lolos jika LPS −40%…−75% **atau** ekspansi terserap
   (vol ≥ +40%, Δ CVD < 0, |CVD/Vol| < 3%).
3. Bugfix: vol naik + CVD turun **bukan** ignition — itu setup.
   Ignition hanya jika Δ > 0.

### Verifikasi
`python tests/test_prepump_detector.py` (Ansem/Punch/Assface 7/7,
Callcat/Froge stealth, SISYPUSS 10 Agu 7/7 + would notify).

---

## 2026-08-12 — Watchlist: hapus kolom Real/Dust + Top 100 Lock

### Masalah
Owner minta **Real/Dust** dan **Top 100 Lock** tidak tampil di tabel
watchlist (main app).

### Yang berubah
`app.py` — tabel watchlist jadi 8 kolom: Token, CA + Links, Diamond,
`|CVD/Vol|`, Buy / Sell TX, 4 Pilar, Update, Hapus. Caption + indeks
kolom disesuaikan. Fetch diamond (`get_watchlist_details`) tetap jalan;
angka real/dust & lock tidak dirender.

### Verifikasi
`python -m py_compile app.py` + cek header tidak lagi memuat
`Real/Dust` / `Top 100 Lock`.

---

## 2026-08-12 — Setup Emas 7 cek harian + Telegram pagi

### Masalah
Owner minta scoring mengarah ke **setup emas** saja. Telegram pagi hanya
jika setup itu muncul di watchlist; kalau tidak, kirim
`TIDAK ADA SETUP HARI INI`.

### Yang berubah
1. **`prepump_detector.py`** — 7 cek: absorption, CVD flat/up, buy TX ≥52%,
   avg sell > buy, whale absorbed, LPS −40%…−75%, lock ≥40%. Verdict
   `SETUP EMAS` / WATCH (≥5/7) / FAIL / STEALTH DUMP. Skor 0–100 dari
   bobot cek. P4 ignition tetap dihitung, tidak wajib.
2. **`signals.py`** — Telegram hanya `is_setup_emas`. Pesan 🥇 SETUP EMAS.
   `queue_no_setup_message` untuk hari kosong (dedupe per tanggal).
3. **`scripts/update_cvd.py`** — digest pagi: antrikan emas, atau
   TIDAK ADA SETUP HARI INI.
4. **UI** — CVD + watchlist menampilkan 7/7 + skor.

### Verifikasi
`python tests/test_prepump_detector.py` (Ansem/Punch/Assface = 7/7),
`python tests/test_signals_telegram.py`.

---

## 2026-08-12 — CVD/watchlist: no auto-fetch, warna tua, TX dominasi, Telegram 4/4

### Masalah
Klik CVD dari watchlist (`/CVD?ca=`) atau paste CA langsung memicu fetch
GMGN/Helius. Hijau/merah neon + glow melelahkan mata. CVD belum menampilkan
dominasi Buy TX vs Sell TX per hari. Telegram cron ikut mengirim WATCH /
STEALTH DUMP.

### Yang berubah
1. **`pages/4_📊_CVD.py`** — `?ca=` hanya prefill input. Fetch, DexScreener
   `get_pool`, dan holder Helius hanya setelah tombol **Fetch & Analisis**.
   Hasil di-cache di `session_state` per CA+hari. Palet hijau-tua/merah-tua
   tanpa glow. Section baru **Buy TX vs Sell TX dominasi %** (stacked 100%
   bar + tabel). Telegram diantrikan hanya jika evaluasi
   `include_today=False` = PASS 4/4.
2. **`app.py`** — CSS nyaman dibaca (slate text, padding lebih longgar,
   tanpa `#000000` paksa). Kolom **Buy / Sell TX** menampilkan `62% / 38%`.
   Tautan CVD tetap `?ca=` (tidak auto-fetch).
3. **`cvd_daily.py`** — field `sell_tx_pct` + helper murni
   `tx_dominance_from_daily`.
4. **`prepump_detector.py`** — `sell_tx_pct` di metrics + hint KPI.
5. **`signals.py`** — `is_complete_daily_pass` +
   `maybe_queue_complete_prepump` (dedupe `telegram_sent` per CA+tanggal).
   Pesan memuat Buy TX vs Sell TX %.
6. **`scripts/update_cvd.py`** — digest harian hanya mengantrikan PASS 4/4.

### Verifikasi
- `python tests/test_cvd_daily.py`
- `python tests/test_signals_telegram.py`
- `python tests/test_prepump_detector.py`
- `python tests/test_watchlist.py`
- `python -m py_compile` file yang diubah

### Sisa PR
- Cron 15m Wyckoff tetap helper ignition; jangan hidupkan alert spam.

---

## 2026-08-12 — 4 Pilar Pre-Pump (CVD Absorption < 3%) + chunk 4 jam

### Masalah
Scoring 0–100 / Grade A-B-C dan alert 15m single-candle tidak membedakan
akumulasi murni (Ansem/Punch/Assface) dari distribusi terselubung
(Callcat/Froge). Cron 00:00 UTC yang full-fetch 24 jam rentan timeout /
rate-limit GMGN-Helius.

### Yang berubah
1. **`prepump_detector.py`** — 4 pilar PASS/FAIL, tanpa skor 60/100:
   P1 `|CVD/Vol| < 3.0%`; P2 Buy TX ≥ 52% + Avg Sell > Avg Buy
   (STEALTH DUMP jika kebalikan); P3 LPS vol −40%…−85% + lock ≥ 40%;
   P4 ignition 15m/1h buy ≥ 55% + ekspansi +100%…+14000%. Setup day
   (absorption/LPS) dinilai terpisah dari candle ignition.
2. **`cvd_daily.py`** — penyimpanan inkremental
   `data/cvd_4h_chunks/<mint>.json`, agregasi 6 chunk → baris harian,
   field `absorption_pct` / `avg_*` / whale net.
3. **`cvd.py`** — `fetch_swaps_multiday` + `fetch_and_analyze_multiday`
   (1–7 hari), persist ke store 168 jam + chunk + `cvd_daily.json`.
4. **`scripts/update_cvd.py`** dihidupkan kembali: `4h` / `daily` /
   `auto`. YAML cron: `docs/WORKFLOW_PATCH_cvd_4h.md` (owner paste
   manual — App tidak punya izin `workflows`).
5. **`pages/4_📊_CVD.py`** — selector 1–7 hari, tombol fetch, CSS
   `.glowing-pass` / `.glowing-fail`, 4 KPI card, Plotly dual-axis,
   tabel day-by-day. Data auto-persist.
6. **`app.py`** — watchlist menampilkan `|CVD/Vol|`, Buy TX %, verdict
   4 pilar (PASS / WATCH / FAIL / STEALTH DUMP).
7. **`signals.record_prepump_4pilar`** + digest Telegram harian.

### Verifikasi
- `python tests/test_prepump_detector.py` — Ansem/Punch/Assface PASS,
  Callcat/Froge STEALTH DUMP, chunk roundtrip, include_today.
- `python tests/test_cvd_daily.py` — status KERING lama tetap valid.
- `python tests/test_watchlist.py` — `resolve_prepump_row`.
- Suite lama (cron 15m, wallet profiles, top holders, scoring, …) hijau.
- `python -m py_compile` modul baru/diubah — OK.

### Sisa PR
- Cron 15m Wyckoff tetap ada sebagai helper ignition; jangan hidupkan
  kembali alert spam (volume spike / breakout guard / CTO / LP radar).

---

## 2026-08-12 — Watchlist main app: angka 15m tidak sinkron

### Masalah
Tabel watchlist di `app.py` hanya membaca sinyal **trigger** di
`signals.json`. Cron tidak menulis apa-apa saat NORMAL / Grade C →
LUNA / FROGE / CHEEMS / CALLCAT tampil `—`. SISYPUSS masih badge
absorption 4 jam (data mock 12.3 / −1.96). Diamond/Real-Dust membeku
di meta add-day karena live fetch hanya jalan jika nilainya `None`.

### Yang berubah
- Cron menulis snapshot `wyckoff_ts/type/score/volume_sol/cvd_sol/lock`
  ke `watchlist.json` setiap siklus (tanpa GitHub push; workflow commit).
- `resolve_wyckoff_row` + `meta_details_stale` di `watchlist.py`.
- UI: snapshot > sinyal; trigger >3 jam → NORMAL; kolom Update `stale`
  bila >45 menit; Diamond/Real-Dust live-refresh jika meta >12 jam.
- `signals.load_signals` pakai salinan `main` jika lebih baru.

### Verifikasi
`python tests/test_watchlist.py` (case 6) + `test_cron_top_holders.py`.

---

## 2026-08-12 — Alert Telegram: $TICKER + urutan candle 3-baris

### Masalah
SOS IGNITION `$HWG` tidak menampilkan simbol token. Baris
`C1: 0.00S ➔ C2: 1.80S (0.0%)` sulit dibaca: `S` = SOL, `0.00` = candle
15m tanpa trade, dan `(0.0%)` palsu karena C1 kosong (bukan dry-up).

### Yang berubah
`format_signal_message` / `format_grade_a_message` di
`scripts/prepump_wyckoff_cron.py`:
- `$TICKER` di bawah judul (`ticker_label`, uppercase ASCII)
- Mint di `<code>` (tap-to-copy Telegram)
- C1/C2/C3 masing-masing satu baris + jendela waktu
- Volume 0 → `0.00 SOL — sepi (tidak ada trade)`; drop% hanya jika C1 > 0
- Smart buyers satu wallet per baris

### Verifikasi
`python tests/test_cron_top_holders.py` — termasuk
`test_ticker_and_empty_c1_label` dan `test_sos_message_includes_symbol`.

---

## 2026-08-12 — Continuous Open (prev close) + anti false-green

### Masalah
Open M15 memakai trade pertama di bin. Dump di awal candle lalu bounce
kecil terlihat hijau padahal Close masih di bawah close candle sebelumnya
(chart TradingView / GMGN = merah). Itu false-positive absorption.

### Yang berubah
`process_trades_to_15m_bins` + `apply_continuous_opens`: Open[n] = Close[n-1].
Bin kosong meneruskan last close (datar 0%). `is_c3_spring_divergence`
memakai warna chart itu (Close ≥ Open vs prev close, CVD < −0.05, vol ≥ 0.50).
Gap-down yang tidak reclaim prev close **bukan** Grade A / absorption.

### Verifikasi
`test_continuous_open_vs_false_green`, `test_apply_continuous_opens_empty_carry`,
`test_false_green_gap_down_not_grade_a` + suite cron sebelumnya.

---

## 2026-08-12 — 3-Candle Wyckoff Spring + Smart Buyer + Grade A/B/C

### Masalah
Detektor single-candle 15m memicu 15+ notifikasi false alarm per hari
(noise akumulasi rutin: candle hijau + CVD minus di tengah sideways).

### Yang berubah

1. **Clock-aligned 15m binning** (`scripts/prepump_wyckoff_cron.py`):
   `bucket_ts = (int(trade_timestamp) // 900) * 900`. Cron di menit
   14/29/44/59 UTC → C3 adalah candle resmi yang sedang akan ditutup.
   Bin lama (now-relative) memotong dua candle resmi — itu sumber noise.
2. **3-candle sequence engine** (fungsi murni, offline-testable):
   - C1 baseline = 30–45 menit lalu (bins[2])
   - C2 kering/LPS = drop volume ≥40% vs C1 **atau** vol < 3.0 SOL, dan
     `|Change| ≤ 2.5%`
   - C3 spring = Close ≥ Open, Change ≥ 0, CVD < −0.05 SOL, vol ≥ 0.50 SOL
3. **Smart-buyer filter di C3**: BUY dari wallet bertag `top_holder`,
   `smart_degen`, `bundler`, `axiom`, `bluechip_owner`, atau masuk Top 100
   holders (utamanya Top 1–10). Disimpan: alamat ringkas, tags, nominal SOL.
4. **Grading**:
   - ⭐ Grade A 95–100: C2 kering AND C3 spring AND smart buyer → **wajib
     Telegram + Discord**. Format pesan sesuai spec (Urutan Candle +
     Smart Buyers + tautan GMGN).
   - 🟢 Grade B 80: C3 spring + satu konfirmasi (hanya C2 kering ATAU
     hanya smart buyer) → catat `signals.json`, notify karena score ≥ 80.
   - ⚪ Grade C 50–55: C3 spring tanpa konfirmasi → **mute**, tidak ditulis
     ke `signals.json` (dashboard tidak tertimpa noise).
5. **Sinyal lain**: SOS Ignition (vol ≥3.0×, Buy TX ≥60%, CVD > +3 SOL,
   kenaikan ≥ +8%). Anti-trap: kenaikan ≥ +10% **tp** CVD < **−2.0 SOL**
   (dulu −1.0) dan lock < 50%. Bearish divergence tetap notify.
   Prioritas: trap > SOS > Grade A > bearish > Grade B > Grade C mute.
6. **GMGN robustness**: `extract_holder_rows` menerima `data.holders` dan
   `data.list`. Trades pindah ke
   `/vas/api/v1/token_trades/sol/{ca}?event=buy&event=sell&limit=100&min_amount_usd=1`.
   `sanitize_sol_quote_amount` membuang quote jika implied SOL price
   < $10 atau > $500 (plus normalisasi lamports).
7. **UI** (`app.py`): badge ⭐ Grade A / 🟢 Grade B / ⚪ Grade C; caption
   menjelaskan filter 3-candle + mute Grade C.

### Verifikasi
`python tests/test_cron_top_holders.py` — clock-align, C2/C3 rules, smart
buyer tag+top100, Grade A pipeline (notify+format), Grade B notify, Grade C
mute (0 save / 0 send), SOS, anti-trap threshold −2.0, bearish, dual-shape
holders, VAS trades URL, sanitizer quote_amount, format pesan Grade A.

### Sisa PR
- Ambang C2 40% / C3 CVD −0.05 bisa dituning lewat config jika masih
  kebocoran noise (saat ini hardcode, sengaja ketat).
- Live GMGN `maker_tags` belum di-HAR ulang hari ini; parser sudah
  menerima list/csv/dict + boolean flag.

---

## 2026-08-11 — Bearish Divergence (kebalikan Absorption) di Wyckoff 15M Detector

### Yang berubah

1. **Cek fungsi lama** (`scripts/prepump_wyckoff_cron.py` section 4.1):
   CVD minus + candle hijau (harga naik) → `🟢 ABSORPTION DIVERGENCE
   (WYCKOFF SPRING)` (+30 skor, trigger notifikasi). Terverifikasi via mock
   (score 95, pesan "CVD -1.96 SOL tp Candle Naik +22.5%").
2. **Fungsi kebalikan baru** (section 4.5):
   - Kondisi: `price_change_pct < 0` (candle merah) **dan** `cvd_sol >= +1.0`
     (CVD jelas plus) → `🔴 BEARISH DIVERGENCE (HARGA TURUN / DISTRIBUSI)`.
   - Skor **-30**, selalu **trigger notifikasi** (bukan filter seperti bull
     trap), pesan berisi **⚠️ HATI-HATI** + bullet indikator "buyer diserap
     seller".
   - Label CVD di pesan jadi dinamis: `(Net Sells Terserap!)` saat CVD ≤ 0,
     `(Net Buys Dominan!)` saat CVD > 0.
3. **Dashboard**: `app.py` SIGNAL_LABELS + caption menampilkan
   `🔴 BEARISH DIVERGENCE` (badge merah sama seperti bull trap).
4. **Tests**: `tests/test_cron_top_holders.py` + `test_bearish_divergence`
   (monkeypatch mock: candle -20% + CVD +5 SOL; save sinyal di-patch no-op
   agar tidak mencemari `signals.json`). Data test `test_sos_ignition_breakout`
   diperbaiki (buy ratio 50% → 66.7%) — gagal karena data test tidak
   memenuhi ambang kode (>= 60%), bukan karena logika detector.

### Verifikasi

`python tests/test_cron_top_holders.py` → **ALL PASSED** (termasuk SOS yang
sebelumnya pre-existing FAIL); seluruh suite lain tetap hijau; `signals.json`
tidak berubah (tetap 358 entri); AppTest app.py 0 exception/error.

### Sisa PR

- Ambang `cvd_sol >= 1.0` dan penalti -30 bisa dituning jika terlalu
  sensitif/noise (config belum dipisah, masih hardcode di script).

---

## 2026-08-11 — app.py diselaraskan ke Pre-Pump & Wyckoff 15M Cron Detector

### Yang berubah (`app.py`)

1. **Kolom tabel Watchlist diganti ke data Wyckoff 15M** (10 kolom):
   Token · CA + Links · Diamond · Real/Dust · **Top 100 Lock** (%
   Pure Accumulator di Top 100, dari `holder_lock_pct`, fallback metadata)
   · **15m Vol / CVD** (dari `volume_sol` & `cvd_sol`) · **Sinyal** (label
   Wyckoff: 🟢 ABSORPTION DIVERGENCE, 🟡 TEST SUPLAI, 🚀 SOS IGNITION,
   🔴 BULL TRAP, 👀 PRE-PUMP POTENTIAL, ➖ NORMAL) · **Skor** (0–100 dari
   `score`) · Update · Hapus.
2. **`get_signal_for_ca()` dibaca ulang**: sekarang mengambil entri terbaru
   format baru di `signals.json` (punya kunci `score` + `holder_lock_pct`,
   ditulis `scripts/prepump_wyckoff_cron.py` tiap 15 menit). Entri lama
   (`cvd_daily`, cron 6h) diabaikan.
3. **Dihapus**: `watchlist_m15_flag()` + kolom M15 (store swap lokal sudah
   tidak ada), kolom AvgCost + `fetch_gmgn_avg_cost()`, `live_evaluate()`,
   skor "/7 checks", semua caption "cron harian 07:00 WIB".
4. **Teks UI**: subheader `### ⭐ Watchlist — Wyckoff 15M Pre-Pump
   Detector`, caption kolom menjelaskan indikator Wyckoff 15m (Pure
   Accumulator supply lock, Absorption Divergence, Vol Dry-Up/Test Suplai,
   SOS Ignition, Bull Trap), footer merujuk `prepump-wyckoff-cron.yml`.

### Verifikasi

`python -m py_compile app.py` OK; Streamlit `AppTest` jalan tanpa exception
maupun error; baris SISYPUSS merender `100.0% Pure Acc`, `12.30 SOL |
-1.96 SOL`, badge `🟢 ABSORPTION DIVERGENCE`, skor `95 / 100`.

### Sisa PR

- Badge/row background hanya untuk sinyal terbaru per CA; skor tidak
  bertahan jika sinyal lama kadaluarsa (detektor hanya menulis saat
  trigger). Kalau mau histori skor per CA, perlu file state terpisah.

---

## 2026-08-10 — Owner request batch: CVD funder, window 24/48/72, Wyckoff 12h/24h, fix Diamond/Real-Dust, M15 flag

### Yang berubah

1. **CVD — Fund Source Wallet (Funder) dari Top 100** (`cvd.funder_wallet_analysis`
   + section baru di `pages/4_📊_CVD.py`):
   - Scan transfer SOL MASUK ke wallet top-100 holder (Helius Enhanced API,
     `max_tx_per_holder=20`), kumpulkan sender = wallet **funder**.
   - Funder diurutkan dari **balance SOL terbesar** (getBalance Helius) —
     makin besar makin menarik.
   - **Exchange di-exclude** otomatis: daftar kurasi `cvd.EXCHANGE_WALLETS`
     (Binance/Coinbase/Kraken/FTX/CEX.IO — terverifikasi 2026-08) + bisa
     diperluas via `config.json` → `exchange_wallets` (list address).
   - Alamat pool token di-exclude juga (arg `exclude_addresses`) supaya hasil
     jual pool→holder tidak terhitung sebagai funder.
   - Helper murni `_parse_funder_transfers()` (offline-testable), UI cached
     15 menit (`st.cache_data`), semua kegagalan network → pesan ramah.
2. **CVD — window conviction jadi 24/48/72 saja** (`pages/4_📊_CVD.py`):
   - `CONVICTION_WINDOWS = (24, 48, 72)`; grafik pertumbuhan/penurunan
     conviction vs periode sebelumnya tetap (▲/▼ + Δ%).
3. **Wyckoff hanya di 12H & 24H** (`prepump_detector.py`):
   - TF 4h tidak lagi berlabel Wyckoff (`role` → "Swing Channel").
   - TF 12h → "Macro Cycle / Wyckoff Accumulation"; tambah TF baru **24h**
     ("Wyckoff Accumulation (24h)") — `window_min 1440, prior 48h,
     sub 720m, terminal 360m, min_buy 40, large_dump 20 SOL, absorp x24`.
   - `PREPUMP_TF_MACRO = ('12h', '24h')` (macro = Wyckoff), micro tetap
     `('30m', '1h')`; confluence golden/dead_cat/sleeper mengikuti macro baru.
4. **Fix Diamond/Real-Dust "—" di main app** (`app.py`):
   - Bug: `fetch_gmgn_top_holder_summary` tidak mengirim `price_usd` ke
     `top_holder_analysis` → semua holder dinilai $0 → semua "dust".
     Sekarang price diambil dari raw GMGN lalu fallback DexScreener.
   - Tambah fallback live Helius (`fetch_helius_top_holder_summary`) sebelum
     fallback GMGN — pakai full holder list Helius + price DexScreener,
     persis seperti halaman CVD. Rantai: meta watchlist.json →
     real_dust_history/holder_snapshots → Helius live → GMGN live.
5. **Detail M15 di watchlist** (`app.py` + `pages/3_⭐_Watchlist.py`):
   - Helper murni `cvd.m15_activity_flag()`: bucket swap ke candle 15 menit;
     flag **YA** kalau ada SATU candle dengan tx **>500** DAN volume
     **>500 SOL** (strict >). Data dari store 72 jam (fast, cached 10 menit);
     fallback fetch GMGN cepat bila store kosong.
   - Kolom **M15** baru di tabel watchlist main app (tooltip: tx & vol candle
     terkuat) dan di halaman Watchlist.

### Kenapa

Semua dari permintaan pemilik 2026-08-10: mau lihat funder ber-SOL besar
(exclude CEX), conviction cukup 24/48/72, Wyckoff tidak boleh di TF kecil,
kolom Diamond/Real-Dust harus muncul di main app, dan watchlist harus tahu
apakah token sudah pernah punya candle M15 ekstrem (tx>500 & vol>500 SOL).

### Verifikasi

- `python tests/test_m15_and_funder.py` — 8 test baru (M15 bucket/threshold,
  parsing funder, exchange exclusion, ranking balance, path kosong) semua lulus.
- `python tests/test_prepump_detector.py` — diperbarui untuk TF 24h +
  macro 12h/24h, semua lulus (termasuk absorp scaling 3/18/36/72).
- Seluruh suite lama (`python tests/test_*.py` + `unittest discover`) hijau.
- `python -m py_compile cvd.py prepump_detector.py app.py pages/*.py` — OK.
- AppTest smoke: app.py & pages/3 render 12 token watchlist, kolom M15
  tampil (LUNA ⚡ YA tx 2321/3020.8 SOL; Tilly ⚡ YA; sisanya Belum), 0 exception.

### Sisa PR / catatan

- Daftar exchange di `cvd.EXCHANGE_WALLETS` sengaja konservatif (hanya
  address terverifikasi). Perluas via `config.json` `exchange_wallets`.
- Analisis funder = heuristik window 20 tx terakhir per holder; funding
  yang sangat lama bisa terlewat. UI sudah menuliskan keterbatasan ini.

---

## 2026-08-07 — CVD page fix: Real/Dust dihitung dari seluruh holder Helius

### Yang berubah

1. Scope analisis dipisahkan secara tegas antara Top 100 dan Semua Holder:
   - **Top 100 holder**: ranking berdasarkan saldo token terbesar, analisis
     diamond hand (sell/buy ≤10% pada window swap 72h; wallet tanpa sell teramati
     ikut dihitung dengan batasan observasi yang jelas di UI), dan tabel detail
     100 wallet.
   - **Semua holder**: total holder valid (`all_holders`), jumlah Real holder
     (`all_real_holders`), jumlah Dust holder (`all_dust_holders`), serta
     persentase Real (`all_real_pct`) dan Dust (`all_dust_pct`) dihitung dari
     seluruh holder token yang dikembalikan daftar lengkap Helius (dinormalisasi
     ke UI token amount memakai decimals dari `get_supply()`).
2. Helper `cvd.top_holder_analysis()` diperbarui untuk menyediakan field
   keseluruhan (`all_holders`, `all_real_holders`, `all_dust_holders`,
   `all_real_pct`, `all_dust_pct`) tanpa mengubah arti field Top 100 (`real_holders`,
   `real_pct`, `diamond_hands`, `diamond_pct`).
3. UI page `pages/4_📊_CVD.py` menampilkan metrik:
   - Diamond hand: denominator Top 100 (`diamond_count/n_top`);
   - Real holder: denominator seluruh holder (`all_real_holders/all_holders`);
   - Dust holder: denominator seluruh holder (`all_dust_holders/all_holders`);
   - Caption yang jelas bahwa Real/Dust dihitung dari seluruh holder token Helius.
4. Test offline di `tests/test_top_holder_analysis.py` diperbarui untuk memvalidasi:
   - pembatasan Top 100 tetap pada 100 wallet;
   - metrik Real/Dust overall menggunakan seluruh holder;
   - holder Real di luar Top 100 tetap dihitung;
   - holder Dust di luar Top 100 tetap dihitung;
   - threshold tepat sama dengan `dust_limit_usd` dianggap Real (`>=`).

### Kenapa

Sebelumnya terdapat bug di mana metrik Real vs Dust holder pada summary card
hanya dihitung dari 100 top holder saja. Seharusnya rasio Real vs Dust
menggambarkan distribusi seluruh populasi holder token dari Helius.

### Verifikasi

- `python tests/test_top_holder_analysis.py` — semua 6 test case lulus.
- `python -m unittest tests/test_*.py` / `python tests/test_*.py` — semua suite lulus.
- `python -m py_compile cvd.py pages/4_📊_CVD.py` — kompilasi lulus tanpa error.
- `git diff --check` — bersih tanpa whitespace / merge marker issues.

---

## 2026-08-07 — CVD page: conviction 4–72h + Top 100 holder analysis

### Yang berubah

1. `pages/4_📊_CVD.py` sekarang mengambil satu range swap GMGN 72 jam dan
   menggambar conviction pada window tetap **4h, 6h, 12h, 24h, 48h, 72h**.
   Table conviction dihapus, begitu juga grafik CVD hourly 72h.
2. UI CVD tidak lagi merender **Pre-Pump Radar 30m**, **Multi-Timeframe
   30m/1h/4h/12h**, atau **Whale & Dolphin held-flow**. Backend prepump tetap
   ada karena masih dipakai sinyal watchlist/Telegram dan test suite.
3. Ditambahkan blok **Top 100 Holder Analysis**. Full holder list Helius
   diagregasi per owner, diurutkan berdasarkan saldo, lalu 100 teratas
   dibandingkan dengan wallet profile dari sample swap 72 jam:
   - diamond hand = sell/buy ≤10%; wallet tanpa sell terdeteksi juga masuk
     hitungan, tetapi UI menyatakan bahwa ini hanya observasi 72 jam;
   - real holder = nilai saldo saat ini ≥ `dust_limit_usd` (default config $5);
   - detail rank, saldo, supply %, nilai USD, buy/sell, sold/buy, diamond,
     real/dust, dan aktivitas tersedia di expander.
4. Aturan analisis diletakkan di helper murni `cvd.top_holder_analysis()` agar
   tidak bergantung pada Streamlit atau jaringan dan dapat diuji offline.

### Kenapa

Owner meminta page CVD diringkas menjadi graph conviction dan holder quality,
serta menghapus panel prepump/multi-TF/cohort yang tidak lagi dibutuhkan di
halaman tersebut. Holder dihitung dari Helius penuh, bukan top-10 GMGN, agar
persentase real-vs-dust tidak menyesatkan.

### Verifikasi

- `python -m py_compile cvd.py pages/4_📊_CVD.py` — lulus.
- `python tests/test_top_holder_analysis.py` — helper diamond hand, top-100
  sorting/limit, empty activity, supply share, dan real/dust threshold.
- `git diff --check` — lulus.

### Catatan

Diamond hand bukan bukti lifetime holding: data sell/buy berasal dari swap
sample yang sedang dianalisis (72 jam). Jika Helius key tidak tersedia, page
masih menampilkan conviction GMGN tetapi memberi warning bahwa holder analysis
belum tersedia.

---

## 2026-08-07 — RESET TOTAL: minimalist prepump focus (owner request)

### Ringkasan
Owner minta perombakan total: backup dulu, lalu hapus cards, hapus analyze di main page, hapus 8 halaman (compare/history/screener/cto/lp/accum/memecoin/prepump-checker), hanya sisakan app, watchlist, CVD. Urutan main app: watchlist (vertical + sinyal harian) → tambah manual → scan trending now → scan degen now. Tombol di trending/degen hanya ⭐ Watchlist. Sumber utama = prepump_baru HANDOFF_WALLET_DEPTH.md — implementasi deteksi watchlist + Telegram sehari sekali tepat ganti hari (07:00 WIB).

### Backup
- Full copy 17M di /home/user/wallet-depth_backup_20260807_0706 + tar 3.7M /tmp sebelum perubahan (commit cdcd34b). History git tetap. Untuk restore: `git checkout cdcd34b -- <file>` atau ekstrak tar.

### Yang dipertahankan (6 fungsi) — revisi 07:00 WIB + prepump_baru
- watchlist (vertical list + kolom sinyal imminent/forming/cleared/neutral, update harian) — `watchlist.py` + `app.py` watchlist section
- scan trending & degen + seluruh filter (gmgn_screener scoring ramp, 4 pilar, penalties) — `gmgn_screener.py` + `trending_ui.py` (hanya Watchlist button)
- CVD — `cvd.py` (72h store) + `pages/4_📊_CVD.py` minimalist 358 baris
- history — `history.json` via daily snapshot (DexScreener+GMGN)
- signals — `signals.py` minimalist (hanya prepump, send_telegram via requests, digest harian)
- telegram — `daily-prepump.yml` 07:00 WIB (00:00 UTC, GMGN candle flip) sekali sehari, bukan hourly

### Yang dihapus total (bukan disable)
- Halaman: 1_Compare, 2_History, 5_Signals, 6_Screener, 7_CTO_Radar, 8_LP_Safe_Radar, 9_Accumulation_Detector, 10_Accumulation_History, 11_Memecoin_Scanner, 12_Prepump_Checker (10 file)
- Modul: accum_history, ai_prompt, breakout_guard, breakout_log, focus, cto_deep_scan, incubation_radar, lp_safe_radar, memecoin_scanner, monitor_alerts, share_card, telegram_monitor_alerts, token_context, cli, debug_rako (13 file + share_card deps)
- Workflow: cto-radar.yml (15 *), cvd-update.yml (30 * hourly), lp-safe-radar.yml (25 *), memecoin-scanner.yml (*/15), daily-snapshot.yml (30 0 *) — diganti single `daily-prepump.yml` 0 17 * * * (07:00 WIB)
- Data: levels.json, breakouts.json, holder_snapshots.json, real_dust_history.json, scanner_*.json, GMGN_Trades_*.csv (2.3M)
- Test: 9 suite yang menguji fitur yang dihapus (accum_history, breakout_guard, flow_safety, stealth_signals, dll) — tersisa 12 suite inti

### Perubahan utama
1. **app.py 4020 → 371 baris**: hapus 3000+ baris (cards, holder depth, health score, breakout_guard, focus, share_card, divergence, cluster, real_dust, etc). Ganti dengan watchlist vertical (badge 🚨/👀/✅/➖ + skor + update WIB + hapus), form manual, scan trending, scan degen (render minimal, hanya Watchlist). Sinyal diambil dari `signals.json` last prepump_*; fallback live_evaluate via `cvd.get_recent_swaps` + `evaluate_prepump` 30m.
2. **pages/4_📊_CVD.py 1961 → 358 baris**: hapus ai_prompt, monitor_alerts, focus, fresh_wallet, cohort detail. Pertahankan: fetch GMGN/Helius, win_stats, conviction, CVD chart, divergence H1, prepump 30m + multi-TF + confluence, whale/dolphin held-flow.
3. **signals.py 566 → ~200 baris**: hapus breakout_guard import, implement `send_telegram` via requests + creds dari env/secrets/config, hanya tier prepump, digest harian. `detect_prepump_and_record` tetap multi-TF.
4. **scripts/update_cvd.py 434 → ~180 baris**: daily only 07:00 WIB, `begin_digest` → loop watchlist → update CVD + conviction + daily snapshot + prepump → `flush_telegram_digest("DAILY PRE-PUMP DIGEST — 07:00 WIB")`. Hapus holder snapshot, breakout_guard, liquidity test, growth alerts.
5. **.github/workflows**: hapus 5, tambah 1 (`daily-prepump.yml`).

### Verifikasi & bugfix
- `python -m py_compile` semua file kept → OK
- `pip install --break-system-packages streamlit` + `python -m unittest discover tests` → holder_split 18 tests OK (sebelumnya 5 error AppRealDustCardHtml diperbaiki dengan hapus class)
- `python tests/test_*.py` individual: test_prepump_detector ALL PASSED, test_candle_patterns ALL PASSED, test_scoring_continuity ALL PASSED, test_wallet_profiles ALL PASSED, test_watchlist ALL PASSED, test_holder_delta ALL PASSED, test_h4_activity ALL PASSED, dll. 5 suite yang gagal karena fitur dihapus sengaja dihapus (cvd_prepump_trigger, cvd_update, flow_safety, stealth_signals, fetch_reliability).
- Watchlist sinyal fallback live_evaluate tested: jika signals.json kosong, evaluate via local store → neutral jika no swaps.
- Cron instruction: hapus workflow lama di GitHub Actions (akan hilang setelah push karena file terhapus). Jika masih ada di UI, disable manual. Workflow baru jalan 07:00 WIB (00:00 UTC, GMGN candle flip) — cek logs di Actions → Daily Prepump.

### Sisa PR & catatan
- Token context (down_ath/avg_cost) tetap di gmgn_screener/trending_ui sebagai display-only (tidak scoring), tapi tidak lagi dipakai di app cards (sudah dihapus).
- Holder delta / real_dust_history tidak lagi di-commit — jika ingin aktifkan lagi untuk CVD deep dive, perlu restore cvd logic + workflow patch.
- DISBALED.md perlu update: halaman yang dulu "disabled via st.stop()" sekarang "deleted total" — jangan revert tanpa persetujuan.


---

## 2026-08-06 — Multi-Timeframe Pre-Pump Radar (30m/1h/4h/12h) + Telegram multi-TF

### Yang berubah

1. **`prepump_detector.py`** — `evaluate_prepump()` diperluas dengan
   parameter per-timeframe (`sub_window_min`, `terminal_min`, `min_buy`,
   `large_dump_sol`, `absorp_mult`, `bullish_div_h4`, `tf`); default-nya
   mereproduksi kalibrasi 30m lama 1:1. Baru: `PREPUMP_TF_CONFIGS` (30m
   Micro Ignition · 1h Hourly Setup · 4h Swing/Wyckoff · 12h Macro Cycle),
   `evaluate_prepump_multi_tf()`, `compute_confluence()`
   (🌟 GOLDEN / 🪤 DEAD CAT / ⏳ SLEEPER / ➖ NORMAL), helper format
   `format_multi_tf_line()`, `format_confluence_line()`,
   `format_prepump_digest_pill()`. Metrics baru: `vol_sub_window`,
   `net_sub_sol`, `min_buy`, `large_dump_sol`, `absorp_target_sol`
   (key lama `vol_15m`/`vol_30m` dipertahankan untuk kompatibilitas).
2. **Telegram** — `format_prepump_telegram()` kini berjudul badge tier
   (🚨 PRE-PUMP IMMINENT / 👀 PRE-PUMP FORMING) dan menyertakan baris
   `📊 Multi-TF: [30m: 90/100 🚨 | 1h: 78/100 🚨 | 4h: 65/100 👀 | 12h: 58/100 👀]`
   + `🎯 Confluence: 🌟 GOLDEN CONFLUENCE (...)` bila hasil multi-TF
   tersedia; breakdown on-chain signature diperjelas (asymmetry ratio,
   order flow, pure accum %, smart 0-sell, active terminals). Digest
   (`monitor_alerts.format_combined_digest` +
   `format_prepump_combined_digest`) menampilkan pill multi-TF ringkas
   per token + emoji confluence.
3. **`signals.detect_prepump_and_record()`** — menempelkan hasil multi-TF
   (`result['multi_tf']`, sumber swap store lokal 72h tanpa RPC) ke entry
   `signals.json` (`tf_scores`, `confluence`) dan pesan Telegram. Gating
   alert TIDAK berubah (tetap primary 30m).
4. **`telegram_monitor_alerts.py`** — blok pre-pump memakai
   `evaluate_prepump_multi_tf()` atas swap 72h; state anti-spam tetap pakai
   skor/tier 30m; `--dry` mencetak preview pesan penuh format baru; log
   mencantumkan skor semua TF + confluence.
5. **UI** — `pages/4_📊_CVD.py`: section "🧭 Multi-Timeframe Pre-Pump
   Radar" (banner confluence, matriks ringkasan 4 TF, tab detail per TF
   dengan breakdown 4 pilar + metrik spesifik TF, tabel multi-TF di export
   Markdown). `pages/12_🎯_Prepump_Checker.py`: full multi-TF (matriks,
   tabs, download report Markdown).
6. **`scripts/update_cvd.py`** — cron membaca swap 72h sekali untuk multi-TF
   + divergence H4 opsional; log prepump menyertakan emoji confluence.
7. **Perbaikan test pre-existing** (drift vs kode, semua gagal juga di base
   commit): `test_cvd_update.py` (retensi 48h→72h + dedup store),
   `test_fetch_reliability.py` (first backfill 72h + ladder 72h→12h→3h→1h +
   jalur partial recovery kini diuji eksplisit), stub `requests/pandas/numpy`
   di semua test dibuat *guarded* (hanya saat paket benar-benar tidak
   terinstal) supaya tidak mencemari modul lain saat
   `python -m unittest discover tests`.

### Verifikasi

- 26/26 test suite PASS sebagai script; `python -m unittest discover tests`
  → **OK (52 tests)**.
- Regresi kalibrasi 30m: fixture lama tetap score 100/100 tier imminent.
- Smoke test UI: `pages/12` dirender via `streamlit.testing.v1.AppTest`
  dengan query `?ca=` → matriks 4 TF + 4 tabs + download button, tanpa
  exception; `run_once` `telegram_monitor_alerts.py --dry` disimulasikan
  offline → digest berisi pill multi-TF + preview pesan penuh.

---

## 2026-08-06 — Pre-Pump follow-ups: sidebar radar, cleared notice, combined digest

### Yang berubah

1. **Sidebar Pre-Pump Radar** (`app.py`) — badge live di sidebar Settings
   untuk tiap token watchlist (max 20). Hot setup (forming/imminent) di
   atas; sisanya di expander "Lainnya". Sumber = swap tersimpan 1 jam
   (tanpa RPC baru). Helper `format_prepump_sidebar_badge()`.
2. **Cleared notification** — bila skor pre-pump turun <55 setelah
   previously imminent/forming, catat `prepump_cleared` di `signals.json`
   + kirim Telegram `✅ PRE-PUMP CLEARED`. Mirror di monitor stealth/
   distribution: TRUE→FALSE transition kirim `format_cleared()`.
3. **Combined Telegram digest** — cron `update_cvd.py` memanggil
   `begin_digest()` di awal + `flush_telegram_digest()` di akhir, sehingga
   CVD monitor + pre-pump + cleared digabung jadi 1 pesan
   `📬 CVD / PRE-PUMP DIGEST`. `telegram_monitor_alerts.py --watchlist`
   default ON digest (override `--no-digest`).

### Verifikasi

- `tests/test_alert_followups.py` (baru, 10 case) — ALL PASSED.
- `tests/test_prepump_detector.py` — ALL PASSED (regresi).
- `py_compile` signals/prepump/monitor/telegram/update_cvd + app.py parse OK.

---
## 2026-08-05 — CVD 72H & monitor growth per 6 jam

### Yang berubah

1. Retensi raw swap CVD dan selector Deep Analysis diperluas ke **72 jam**.
2. Page CVD menampilkan pure accumulator growth (semua wallet buy ≥0.1 SOL, sell ≤10%), conviction history, TX/volume, serta satu grafik gabungan yang di-index 100; semua memakai bucket 6 jam.
3. Cron menyimpan jumlah/volume pure accumulator pada conviction snapshot dan mengirim Telegram `CVD MONITOR` bila empat indikator serentak naik/turun, atau TX/volume melonjak ≥5× snapshot sebelumnya.
4. Detail Real Transaction Summary pada cards dan pemeriksaan "Holders with no buy" dinonaktifkan sementara. Advanced cohort divergence dan Separate wallet lists sekarang closed dropdown secara default.

### Verifikasi

- `python -m py_compile cvd.py signals.py scripts/update_cvd.py pages/4_📊_CVD.py app.py` lulus.
- `python -m unittest discover tests` tidak dapat berjalan di sandbox karena dependency repo belum terpasang (`requests` dan `pandas` tidak ada); kegagalan terjadi pada import sebelum test dieksekusi.

---

## 2026-08-05 — Fix identitas token DexScreener untuk CVD (MEMIPEDE ≠ Cyclospora)

### Masalah

Saat CVD dibuka untuk CA MEMIPEDE
`6LLNiWXRZp8hn5oTFTHEo8ERbJS3QJfHSKhnTCqipump`, halaman dapat memakai
pair DexScreener paling likuid mentah. Endpoint `/latest/dex/tokens/<CA>`
juga mengandung cross-pair ketika CA tersebut menjadi `quoteToken`; kode lama
lalu selalu membaca `baseToken`, sehingga nama token di header berubah menjadi
**Cyclospora** meskipun CA yang dianalisis tetap MEMIPEDE.

### Yang berubah

1. **`core.py`** sekarang memiliki resolver identitas tunggal:
   `matching_dexscreener_pairs()` mewajibkan kecocokan address exact,
   memprioritaskan target di `baseToken`, lalu mengurutkan likuiditas. Bila
   hanya ada quote-side pair, `dexscreener_pair_token()` mengambil metadata
   dari sisi CA yang benar, bukan meminjam nama base token.
2. **`core.get_market()` + page `4_📊_CVD.py`** memakai resolver tersebut;
   `get_pool()` page CVD sekarang hanya membaca market terverifikasi. Header,
   pair GeckoTerminal, harga, dan MC CVD mengikuti pair MEMIPEDE/SOL yang
   benar, bukan cross-pair lebih likuid.
3. **Jalur pendukung** juga memakai selector yang sama: cron CVD,
   snapshot harian, harga watchlist/Quick Pick, ATH context, pola candle,
   CLI, memecoin scanner, serta harga SOL untuk normalisasi CVD. Ini mencegah
   salah nama yang sama muncul kembali lewat UI atau proses terjadwal.

### Verifikasi

- `tests/test_dexscreener_identity.py` (baru, 6 test / 20 assertion, tanpa
  jaringan) memakai fixture cross-pair Cyclospora/MEMIPEDE dengan likuiditas
  jauh lebih besar daripada pair MEMIPEDE/SOL. Hasil: selector tetap memilih
  MEMIPEDE/SOL, metadata = `MEMIPEDE`, dan pair yang tidak memuat CA ditolak.
- Test juga mengunci bahwa `pages/4_📊_CVD.py::get_pool()` tetap
  mendelegasikan ke `core.get_market()`, sehingga tidak boleh kembali ke
  `pairs[0]`/`baseToken` mentah.
- `python -m py_compile` untuk modul yang diubah — lulus.
- Uji live API tidak dapat dilakukan di sandbox karena egress crypto API
  diblokir; fixture mereplikasi struktur respons yang menyebabkan bug.

---

## 2026-08-04 — Page 10 Accumulation History: scan akumulasi SELURUH umur token

### Yang berubah

1. **`pages/10_📈_Accumulation_History.py` (baru)** — memindai seluruh
   riwayat chart sebuah token (sejak pair dibuat) dengan rolling window
   48 jam, lalu menampilkan **rentang tanggal (WIB)** di mana pola
   akumulasi 5-fase terdeteksi di masa lalu. Page 9 tidak diubah sama
   sekali; page 10 menyediakan panel perbandingan verdict 48 jam terakhir
   ala page 9 (definisi fase identik) supaya bisa dibandingkan
   berdampingan.
2. **`accum_history.py` (baru, modul murni)** — semua skoring/scanning/
   merging tanpa Streamlit & tanpa network di jalur scoring:
   - `score_phase1..5` + `score_window` + `recommendation`: threshold
     sama persis dengan page 9 (Liquidity Test 15, Slow Accumulation 20,
     Whale Entry 20, Volume Spike 25, Thin Liquidity 20; BUY WATCH /
     ACCUMULATING / TOO LATE / AVOID ladder identik termasuk precedence
     BUY WATCH > TOO LATE).
   - `rolling_scan`: window 48 jam, step 3–12 jam, kandidat = pre-score
     ≥ 40 (sidebar) DAN sinyal nyata (p2-proxy ≥5 ATAU p4-est ≥10) —
     poin thin-liquidity saja tidak boleh membentuk kandidat; kandidat
     tumpang-tindih >75% dibuang (hemat fetch GMGN).
   - `merge_windows`: window berdekatan (gap ≤ 12 jam) digabung jadi
     rentang — skor = maksimum, fase hit = gabungan, `n_windows` dicatat.
   - `fetch_candles_full`: paginasi mundur GeckoTerminal via
     `before_timestamp` (limit 1000/request, `page_fetcher` injectable
     untuk test offline) — `cvd.fetch_candles` tidak diubah.
   - `estimate_liq_fdv`: liq/FDV historis = nilai kini × rasio median
     close window vs harga sekarang — selalu ESTIMASI, confidence turun
     kalau GMGN parsial/gagal.
3. **Alur page**: candle-first (day + hour, full history) → rolling scan →
   verifikasi GMGN hanya untuk kandidat (`from_ts`/`to_ts`, `max_pages`
   dibatasi, progress bar, `get_gmgn_fetch_status()` untuk
   ok/complete/error) → filter ambang hasil → merge → tabel rentang +
   chart full-periode dengan highlight vrect + breakdown fase per rentang
   + panel perbandingan page 9. Empty state: pair terlalu baru, tidak ada
   kandidat, GMGN gagal — tidak crash.

### Kenapa begitu

- Page 9 hanya melihat window geser 48 jam terakhir → untuk token tua
  verdict flip-flop tiap jam (jam penting masuk/keluar window) dan fase
  1–3 (dirancang untuk periode launch) diterapkan ke riwayat acak. Kasus
  nyata: MEMIPEDE
  `6LLNiWXRZp8hn5oTFTHEo8ERbJS3QJfHSKhnTCqipump` — spike hourly ~$16.6K
  30 Jul 2026 16:00 UTC sudah di luar 48 jam page 9.
- Verifikasi wallet (GMGN) mahal (100 trade/halaman) → hanya window
  kandidat ber-pre-score tinggi yang di-fetch.
- Skoring ditaruh di modul murni supaya bisa di-unit-test offline
  (sandbox Arena memblokir egress ke API crypto).

### Verifikasi

- `tests/test_accum_history.py` (baru, 17 fungsi test / 94 check, tanpa
  pytest & tanpa jaringan): ladder tiap fase, window MEMIPEDE-like
  (skor ≥ 70, whale_entry + volume_spike hit, estimasi liq <$50K),
  quiet window → AVOID tanpa volume-spike hit, rolling scan menemukan
  event 28 Jul–1 Agu & TIDAK ada kandidat di hari sepi, merge adjacent
  (skor max, fase union), paginasi 2500 candle (cap halaman →
  complete=False, dedupe boundary), GMGN gagal → confidence LOW,
  recommendation precedence page 9.
- Suite penuh: `python -m pytest tests/ -q` → **206 passed** (189 lama +
  17 baru). `py_compile` semua file baru OK.
- Smoke test E2E page via `streamlit.testing.v1.AppTest` dengan fixture
  sintetis (market/candles/swaps GMGN di-mock): 8 kandidat → 1 rentang
  **29 Jul 2026 01:00 → 31 Jul 2026 19:00 WIB, skor 90, BUY WATCH, HIGH**
  (4 window digabung); kasus GMGN 429 → warning + confidence LOW tanpa
  crash; mode candle-only → "BELUM DIVERIFIKASI"; pair baru → warning
  parsial; candle fetch gagal → error state.
- Uji manual live dengan MEMIPEDE tidak bisa dijalankan di sandbox
  (egress ke dexscreener/geckoterminal diblokir, HTTP 000) — sudah
  disimulasikan dengan fixture sintetis yang meniru profil volume/price
  token tersebut.

### Sisa PR

- Verifikasi live pertama di lingkungan dengan akses jaringan
  (Streamlit Cloud / lokal) memakai CA MEMIPEDE di atas; ekspektasi:
  minimal satu rentang kandidat di sekitar 28–31 Jul 2026 dan tidak ada
  sinyal palsu besar di hari sepi.

---

## 2026-08-03 — CTO Incubation Radar: GMGN jadi satu-satunya market source (lanjutan PR #38)

### Yang berubah

1. **`cto_deep_scan.deep_scan_token()` berhenti memakai DexScreener +
   `history.json` untuk market gates.** Signature baru
   `deep_scan_token(ca, relaxed=False, do_cluster=False, helius_keys=None,
   gmgn_row=None)`. Bila `gmgn_row` (row hasil `screen_incubation`)
   diserahkan, snapshot market dibangun murni dari row itu
   (`market_from_gmgn_row`): `marketcap`←`mc`, `liquidity_usd`←`liq`,
   `volume.h24`←`vol24`, plus symbol/holders/T10/vol-MC/risk fields, dan
   di-tag `market_source = "gmgn"`. Kalau tidak ada row, scan mengambil
   snapshot GMGN live (`fetch_gmgn_market_row`: `token_stat` + best-effort
   `token_prices`, dinormalisasi lewat `score_token`). Kalau keduanya tidak
   tersedia → **fail closed** dengan reason `GMGN market snapshot
   unavailable`; Dex/history tidak pernah dipakai untuk MC/liquidity/
   volume/pass criteria.
2. **DexScreener tetap dipakai sebagai metadata saja**: CTO claim detection
   (page DexScreener, tidak berubah), symbol/url display, dan divergence
   logging `_divergence_notes()` (mis. `GMGN vol24 $70,000 vs DexScreener
   $45,000 (divergence 36%) — GMGN authoritative` → `market_divergence` +
   print CLI + warning di page 7).
3. **T10 gate memprioritaskan row GMGN** → baru konsentrasi on-chain Helius
   → baru token_stat mentah. Helius tetap jalan untuk holders/real-dust/
   health display.
4. **CLI `cto_deep_scan.py --from-radar`** menyimpan mapping CA→GMGN row
   dari `screen_incubation` dan meneruskannya ke setiap deep scan;
   output per token kini menampilkan `Market source:` + divergence lines.
   Pesan Telegram auto-watchlist juga menyebut market source.
5. **Page 7 (`pages/7_💀_CTO_Radar.py`)**: tombol Deep Scan per kandidat
   **langsung menjalankan Stage 2** dengan row GMGN utuh (disimpan di
   `cto_deep_single_row`) — sebelumnya tombol hanya `set state + st.rerun()`
   sehingga tampak tidak melakukan apa-apa karena UI kembali ke tab
   pertama. Tab Stage 2 membangun mapping CA→row yang sama, menampilkan
   `Market source: GMGN` + semua metrics yang dipakai + divergence
   warnings, dan kolom `MktSrc`/`Vol24` di tabel hasil. Row demo watchlist
   (dari history saat sandbox GMGN-block) ditandai `_source=history_fallback`
   dan TIDAK diteruskan sebagai `gmgn_row` — deep scan-nya live fetch GMGN
   atau fail closed.

### Kenapa begitu

- GMGN menghitung volume lintas **semua** pool sebuah token; DexScreener
  membaca pair terdalam saja. MEMIPEDE: MC sama ~$189k di dua sumber,
  tetapi volume 24h GMGN ~$70k vs Dex ~$45k → Stage 1 (GMGN) dan Stage 2
  (Dex) pernah memberi angka berbeda dan verdict berbeda.
- Fail closed mencegah token "masuk radar" lewat angka cache/history yang
  tidak dapat diverifikasi lagi di GMGN.
- Threshold PR #38 tidak disentuh: incubation strict/relaxed, deep
  strict/relaxed, dan LP Safe (MC ≥$120k, vol ≥$60k) persis sama.

### Verifikasi

- `tests/test_gmgn_market_authority.py` (baru, 7 grup uji, 62 assertion,
  tanpa pytest & tanpa jaringan) — ALL PASSED. Termasuk: mock MEMIPEDE
  (MC 189000, vol24 70000, vol/MC 0.37, liq <$45k, holders/T10/risk lolos)
  → candidate strict+relaxed; row sama dengan `vol24=99064` → FAIL
  `vol24 > 90000` di Stage 1 (dua mode) + deep strict; `get_market()`
  dimonkeypatch ke Dex vol 45000 → hasil tetap vol 70000,
  `market_source == "gmgn"`, angka Dex hanya muncul di divergence note;
  tanpa snapshot GMGN → FAIL dengan reason jelas meski Dex "bagus".
- Seluruh suite `tests/` (18 file) — ALL PASSED.
- Runtime: `python cto_deep_scan.py --limit 4 --deep`, `--relaxed`, dan
  `--from-radar` jalan; di sandbox tanpa jaringan setiap token fail closed
  dengan reason `GMGN market snapshot unavailable` (sebelumnya diam-diam
  memakai `history.json`). `python lp_safe_radar.py --limit 20` tidak
  berubah.
- Simulasi E2E raw GMGN trending → Stage 1 → Stage 2: MEMIPEDE PASS dengan
  angka GMGN identik di dua stage.
- Signature runtime: `screen_incubation(relaxed=False, debug=False)` —
  dicek lewat `inspect` di test.

### Sisa PR / catatan

- `.github/workflows/cto-radar.yml` sudah memakai
  `python cto_deep_scan.py --from-radar --auto-watchlist --telegram`, jadi
  pipeline cron otomatis ikut alur GMGN-authoritative **tanpa perlu ubah
  workflow** (GitHub App memang tidak bisa mengubah `workflows/` — kalau
  nanti ada penyesuaian, lakukan lewat GitHub Web UI).

---

## 2026-08-03 — Rangkuman TX real di cards LP & Degen (6/12/24/48 jam)

### Yang berubah

1. **Blok "🧾 Rangkuman TX real ≥$5" di card LP Radar & Degen Radar**,
   tepat di bawah blok `💎 Real ≥$5 vs 🪙 Dust` (sebelum card
   pertumbuhan). Tiap card menampilkan 4 chip — window 6/12/24/48 jam —
   berisi jumlah swap senilai ≥ ambang real/dust (SOL × harga SOL) dan
   net SOL-nya (beli − jual; ▲ hijau / ▼ merah).
2. **Nol RPC tambahan.** Sumbernya raw-swap store 48 jam yang SUDAH ada
   (`cvd.get_recent_swaps`), sama seperti panel CVD. Harga SOL diambil
   `cvd.get_sol_price()` (cache 10 menit) sekali per page load dan
   dipakai kedua radar; per CA di-cache 5 menit via `st.cache_data`.
3. **Komputasi murni di `cvd.real_tx_summary()`** — pure function,
   deterministik dengan `now_ts`, toleran swap rusak/NaN, batas inklusif
   (swap tepat di ambang = real). Store kosong → blok disembunyikan,
   tidak pernah render nol palsu; `covered_h` membedakan token sepi vs
   store kosong.
4. **Caption kedua radar diperbarui**, termasuk catatan jujur: di ambang
   default $5 hampir semua swap store (≥0.05 SOL) masuk kategori real —
   naikkan ambang di sidebar untuk pisahan yang lebih tajam.

### Kenapa begitu

Permintaan owner (lanjutan PR #35): "tambahkan detail ke semua cards LP
dan degen jumlah real TX ... dalam timeframe 6/12/24/48 jam terakhir,
tempatkan di bawah holder ratio di cards." Definisi "real TX" dikonfirmasi
owner = **swap bernilai ≥ ambang real/dust** (bukan profil wallet, bukan
join list holder), isi = **jumlah + net SOL** per window.

### Verifikasi

- `tests/test_real_tx_summary.py` (baru, 7 grup uji, ~30 assertion,
  tanpa pytest/jaringan) — ALL PASSED.
- Seluruh suite `tests/` (17 file) — ALL PASSED.
- `python -m py_compile app.py cvd.py tests/test_real_tx_summary.py` dan
  `git diff --check` — lulus.
- Smoke test blok HTML dengan data store nyata (AkchGAUd…): chip
  6j 104 tx · −7.4 SOL / 12j 345 tx · +3.4 SOL / 24j 1.084 tx · −18.7 SOL /
  48j 2.454 tx · −50.2 SOL; CA tanpa store → blok kosong (tidak nol palsu).

---

## 2026-08-03 — Perbaikan stale RAKO + backfill GMGN yang aman

### Yang berubah

1. **False stale di LP Radar diperbaiki.** Freshness sweep sekarang selalu
   memakai `cvd.flow_freshness()` saja. Sebelumnya saat `FOCUS_MODE` aktif,
   sweep memakai `health_badge()`, yang menggabungkan freshness dengan
   advisory quality/persistence/distribution; akibatnya flow RAKO yang masih
   fresh bisa salah diumumkan sebagai `very stale` hanya karena distribution
   warn/danger. Pesan ambang juga diselaraskan dengan konstanta aktual:
   fresh ≤2,5 jam, warn sampai 12 jam, lalu very stale.
2. **Remote conviction dicek per watchlist CA.** `load_conviction(required_cas)`
   sekarang merge `conviction.json` cron dari GitHub bila CA yang diminta
   hilang/stale, meskipun token lain di checkout Streamlit masih fresh.
   Cache 10 menit dipakai sekali per render; helper flow internal tetap
   network-free. Ini menutup kasus Cloud checkout lama yang punya token A
   fresh tetapi RAKO sudah ada point baru di GitHub.
3. **Force refresh benar-benar GMGN-only.** Tombol tidak lagi ditolak jika
   Helius key atau main pool DexScreener tidak ada. GMGN fetch memakai CA,
   mempertahankan pool lama bila tersedia, membatasi batch ke 10 token, dan
   menyisakan token gagal di antrean agar bisa dicoba lagi.
4. **Partial GMGN fetch tidak boleh menyegarkan conviction palsu.** Fetch
   sekarang membawa status `ok`/`complete`; cursor, raw swap, dan bucket tidak
   dimajukan bila TLS/API/cursor/page-cap gagal sebelum cutoff. Cron dan manual
   backfill memeriksa `fetch_ok` sebelum `record_conviction()`/signal, sehingga
   timestamp baru tidak bisa menyamarkan data lama. First backfill diberi
   cutoff raw-store 48 jam supaya token aktif tidak menelusuri seluruh umur
   token lalu mentok page cap.
5. **Request GMGN lebih tahan gagal.** `tz_name` tidak lagi double-encoded
   (`Asia/Jakarta` → client mengirim `Asia%2FJakarta`), dan kegagalan runtime
   `curl_cffi` mencoba `requests` sebelum melaporkan error.
6. **Card benar-benar mematuhi very-stale state.** LP dan Degen Radar menyembunyikan
   conviction trend/sparkline, net_pure, volume, swaps, dan phase yang stale;
   hanya placeholder refresh yang ditampilkan. Advisory flag tidak memicu
   masking ini.

### Verifikasi

- `tests/test_fetch_reliability.py` (baru, tanpa jaringan): query encoding,
  fallback curl→requests, terminal/capped pagination, state preservation,
  pool-less GMGN recovery, cron guard, per-CA remote merge/cache — ALL PASSED.
- `tests/test_cvd_update.py`: UI GMGN backfill, actual-success counter,
  freshness-only sweep, stale-card masking, atomic conviction failure — ALL
  PASSED.
- `tests/test_flow_safety.py`, `tests/test_focus_mode.py`,
  `tests/test_watchlist.py`, dan `tests/test_helius_rotation.py` — ALL PASSED.
- `python -m py_compile app.py cvd.py scripts/update_cvd.py` dan
  `git diff --check` — lulus.

---

## 2026-08-02 — History real vs dust per jam + grafik pertumbuhan di card + tombol hapus konsisten

### Yang berubah

1. **Pencatatan real holder vs dust holder tiap cron 1 jam.** Store baru
   `real_dust_history.json` (`{ca: [{ts, real, dust, price, limit}]}`).
   Recorder `cvd.record_real_dust_point()` + loader
   `cvd.load_real_dust_history()` + normalizer `cvd.real_dust_series()`
   + analyzer `cvd.real_dust_trend()`. Dipanggil di
   `scripts/update_cvd.py::_try_snapshot()` — memakai list holder Helius
   yang SUDAH di-fetch untuk holder snapshot, jadi nol RPC tambahan.
   Status log cron dapat suffix `rd:210r/1024d`. Hanya jalur Helius yang
   mencatat; fallback GMGN (top-10 holder) sengaja diskip karena
   real/dust dari top-10 tidak bermakna. Dedup 45 menit
   (`REAL_DUST_MIN_GAP_S`) supaya retry cron tidak dobel-commit; retensi
   30 hari; hard cap 744 titik/CA. Threshold mengikuti `dust_limit_usd`
   config (default $5, sama dengan card).
2. **Card pertumbuhan menyambung di main page.** Helper baru
   `app._real_dust_growth_html()` dirender tepat di bawah blok
   `💎 Real ≥$5 vs 🪙 Dust` di card LP Radar DAN Degen Radar (border
   dashed + radius bawah supaya tampak "menyambung"). Isi: headline
   arah **📈 NAIK / 📉 TURUN / ➡️ DATAR** (berdasarkan Δ real holder vs
   titik cron sebelumnya), chip delta **1 jam / 6 jam / 24 jam**
   (💎+N real, 🪙±N dust), perubahan rasio, dan **sparkline SVG** 48
   titik terakhir (garis hijau = real, oranye = dust; skala
   masing-masing dengan label supaya tidak menyesatkan), plus timestamp
   titik terakhir (WIB). Semua read via `fetch_real_dust_history()`
   (cache 5 menit, 1× baca file per page load).
3. **Tombol 🗑️ Hapus konsisten posisinya.** Kedua card sekarang
   `display:flex;flex-direction:column` + spacer `<div style='flex:1 1
   auto;'>` tepat sebelum baris tombol → tombol selalu menempel di
   dasar card dengan posisi vertikal yang sama di semua card (row
   parent sudah `align-items:stretch`, jadi tinggi card dalam satu baris
   memang sama). Sebelumnya tombol mengikuti panjang konten
   (`margin-top:10px`) sehingga pindah-pindah antar card.

### Kenapa begitu

Permintaan owner: (1) catat perbandingan real vs dust holder tiap cron
1 jam beserta arah naik/turun + detail, (2) tampilkan history-nya real
time di main page — "di bawah card masing2 token, buatkan card yang
menyambung, atau grafik pertumbuhan", (3) tombol hapus watchlist di
card dibuat konsisten tidak pindah-pindah. Sparkline SVG dipilih (bukan
plotly) karena card dirender sebagai HTML string di `st.markdown`;
plotly per card akan berat & lambat untuk satu baris card.

### Sisa PR untuk owner

- **Edit workflow** `.github/workflows/cvd-update.yml`: tambah
  `git add real_dust_history.json 2>/dev/null || true` setelah baris
  holder_snapshots — panduan lengkap di
  `docs/WORKFLOW_PATCH_real_dust.md`. Tanpa ini data tidak ter-commit
  (runner ephemeral) dan grafik kosong di Streamlit Cloud.
- Headline arah baru muncul setelah ≥2 titik (±2 jam setelah cron
  pertama dengan kode ini); chip 6 jam/24 jam menyusul saat data cukup.

### Verifikasi

- `python -m py_compile app.py cvd.py scripts/update_cvd.py` — lulus.
- `tests/test_real_dust_history.py` (baru, 12 grup uji, ~45 assertion;
  path di-patch ke tmpdir) — ALL PASSED.
- Integration test offline `_try_snapshot()`: jalur Helius mencatat
  `rd:3r/2d`, retry ter-dedup, tanpa harga → skip, fallback GMGN →
  **tidak** mencatat. Lulus.
- Uji fungsi `_real_dust_growth_html()` via ekstraksi AST: kosong → tidak
  render; 1 titik → catatan; 30 titik → NAIK + chip + SVG + WIB;
  downtrend + standalone; dust=0 → ∞. Geometri SVG tervalidasi dalam
  viewBox.
- Suite test existing tetap hijau (`test_holder_delta`, `test_flow_safety`,
  `test_breakout_guard`, dll.). `test_cvd_update` & `test_holder_split`
  gagal juga di baseline (pre-existing, env sandbox);
  `test_markup_ai_prompt` butuh streamlit (tidak di sandbox).
- **Fix hygiene**: `tests/test_stealth_signals.py` sempat bocor menulis
  sinyal sintetis `T_NEW` ke `signals.json` asli — sekarang
  `signals.SIGNALS_PATH` di-patch ke tmpdir (aturan AGENTS.md §7).
  `signals.json` yang terpollusi saat test run sudah di-restore.

---

## 2026-08-02 — Pindahkan "Quick Delete" ke tombol kecil di card

### Yang berubah

1. **Expander "🗑️ Quick Delete dari watchlist" dihapus** dari dashboard
   halaman utama. Dulu ada daftar terpisah (semua token watchlist, masing-
   masing satu tombol "Hapus") yang duplikatif dengan halaman ⭐ Watchlist.
2. **Tombol 🗑️ kecil disematkan di header setiap card** LP Radar & Degen
   Radar — berdampingan dengan shortcut 🦆 DexScreener dan ⚡ GMGN.
   Didesain sebagai pill merah kecil (latar `rgba(239,68,68,0.12)`, border
   merah 0.35) supaya kontras dengan dua shortcut abu-abu di sebelahnya.
3. **Mekanisme hapus via query param.** Karena card di-render lewat
   `st.markdown(..., unsafe_allow_html=True)`, tombol Streamlit tidak bisa
   ditanam di HTML. Tombol jadi anchor `<a href='?del_ca=<ca>'>`; lalu di
   atas (tepat setelah `_wl = load_watchlist()`) ada handler yang membaca
   `st.query_params.get("del_ca")`, memanggil `remove_from_watchlist()`,
   membersihkan param via `st.query_params.pop(...)`, menampilkan toast,
   lalu `st.rerun()`. Pola ini sama dengan link navigasi card yang sudah
   ada (`?ca=<ca>`).

### Kenapa begitu

Permintaan owner: hapus tempat hapus terpisah dan sematkan langsung di
card supaya hapus token sekali klik persis di tempat token itu ditampilkan.
Tidak ada lagi dua lokasi untuk fungsi yang sama.

### Catatan

- Token yang **belum punya card** (belum ada conviction point, misal baru
  di-add tapi belum di-backfill cron) tidak terlihat tombol hapusnya.
  Tetap bisa dihapus lewat tombol "💔 Remove from watchlist" saat token
  itu dianalisa, atau di halaman ⭐ Watchlist.
- Tombol hapus **satu klik tanpa konfirmasi** — konsisten dengan perilaku
  "Quick Delete" lama. `onclick`/JS konfirmasi sengaja tidak dipakai karena
  Streamlit men-strip event handler dari `unsafe_allow_html`.

### Verifikasi

- `python -m py_compile app.py` — lulus.
- `grep` konfirmasi: expander "Quick Delete" beserta key `del_wl_*` sudah
  hilang; handler `del_ca` + dua tombol 🗑️ (LP & Degen) sudah ada.
- `remove_from_watchlist` masih dipakai di: handler `del_ca` baru + tombol
  "💔 Remove from watchlist" (analyse section) — import tetap relevan.

---

## 2026-08-01 — Mengembalikan Tombol Force Refresh dengan Estimasi Waktu (ETA)

### Yang berubah

1. **Tombol "🔄 Force refresh now" dikembalikan.** Sesuai permintaan terbaru, fitur auto-refresh yang secara diam-diam membackfill token baru (lewat `watchlist_auto_refresh_cas`) kini diubah menjadi klik manual.
2. **Proses sinkronisasi dilengkapi estimasi (ETA).** Saat tombol diklik, proses iterasi (loop) akan menghitung sisa waktu (`rem_time`) berdasarkan waktu mulai dan menyajikannya bersama *progress bar*.
3. Tombol ini tidak hanya menangani token baru, melainkan mencakup **semua token yang stale** (`_stale_cas` + `_very_stale_cas`).

### Kenapa begitu
Pemilik meminta agar visibilitas proses *refresh* diperjelas dengan menyediakan kontrol manual secara eksplisit beserta estimasi penyelesaian sinkronisasi.

### Verifikasi
- Terverifikasi pada `app.py`: kompilasi sukses (`python -m py_compile app.py`). Logika baru diintegrasikan di lokasi *freshness sweep* yang sama dengan *graceful error handling* dan tampilan indikator sinkronisasi.

---

## 2026-08-01 — Stat avg cost GMGN di card LP/Degen + kolom AvgCost di scan trending/degen

### Yang berubah

1. **`gmgn_screener.screen()` (trending) sekarang menyimpan `row["avg_cost"]`**
   (dari `_get_avg_cost_and_ath`), sejajar dengan `screen_hrhr` yang sudah
   menyimpannya. Fallback deterministik -65% tetap berlaku bila GMGN tidak
   mengirim field `avg_cost_change`.
2. **Kolom `AvgCost` baru di tabel screener** (`trending_ui.COLUMNS`, dipakai
   scan trending & degen/HRHR): % harga saat ini vs rata-rata harga beli
   holder GMGN — merah ≤ -50% (holder rata-rata rugi dalam), oranye <0%,
   hijau ≥0%. Display-only, tidak menambah Fit (dijelaskan di CAPTION).
   Indeks kolom render digeser (risk/notes/buttons ke cc[10]/cc[11]/cc[12]).
3. **Card LP Radar & Degen Radar menampilkan `💰 avg cost`** lewat helper
   baru `app._ca_avg_cost()` + `app._avg_cost_html()` (mirror pola
   `_ca_down_ath`/`_ath_html`): baca dari watchlist meta → fallback session
   screener rows (`screener_rows`/`screener_hrhr_rows`). Warna sama dengan
   kolom tabel. Caption kedua card di-update.
4. **`watchlist.add_to_watchlist()` menerima `avg_cost`** (opsional),
   disimpan di entry + meta (fresh capture menang), dan `_apply_ops`
   ikut menyalin field `avg_cost` saat replay journal. Tombol ⭐ watch di
   `trending_ui` meneruskan `avg_cost=r.get("avg_cost")`.

### Verifikasi

- `python -m py_compile` (13 file incl. gmgn_screener/trending_ui) — lulus.
- `python -m pyflakes *.py pages/*.py scripts/*.py` — bersih (hanya 2
  f-string lama yang di luar scope).
- 3 suite test (`test_breakout_guard`, `test_scoring_continuity`,
  `test_markup_ai_prompt`) — ALL PASSED (test markup memeriksa labels
  COLUMNS & CAPTION tetap valid).
- Offline checks: `screen()` membawa `avg_cost` (-62.5 dari field GMGN,
  fallback -65.0); watchlist menyimpan + replay journal membawa avg_cost;
  re-add tanpa avg_cost tidak menghapus nilai lama; `_avg_cost_html`
  render 3 warna + empty saat unknown + fallback session rows.
- `git diff --check` bersih (cr-at-eol).

### Catatan / sisa PR

- Token watchlist lama (ditambahkan sebelum fitur ini) tidak punya
  `avg_cost` di meta — card tetap aman (line disembunyikan) dan terisi
  otomatis saat di-add ulang dari screener atau via fallback session rows.

## 2026-08-01 — Watchlist HRHR→LP bug + atomic JSON writes + cluster scan paralel + auto-refresh on add

### Yang berubah

1. **Bug fix: token HRHR masuk LP Cards.** `watchlist._apply_ops()` dulu hanya
   menyalin `symbol`/`note`/`added` dari journal op, sehingga field `source`
   (`"hrhr"`) hilang saat replay journal → LP Radar memakai default
   `"trending"` → token HRHR tampil di 💧 LP Radar, bukan ⚡ Degen Radar.
   Sekarang SEMUA field journal (`symbol`, `note`, `added`, `source`,
   `down_ath`) disalin, dan `add_to_watchlist()` memaksa source dari add
   terbaru (latest-add-wins) supaya re-add tidak menimpa section card.
2. **Semua write JSON state jadi atomic.** Helper baru
   `core.atomic_write_json(path, data, **dump_kwargs)` (mkstemp di dir yang
   sama → flush+fsync → `os.replace`, cleanup temp saat gagal) menggantikan
   pola `open(path,"w")+json.dump` di: `cvd.py` (`save_cvd`, merge
   conviction remote, `record_conviction`, `_save_holder_snapshots`),
   `watchlist.py` (pending journal + watchlist), `breakout_guard.py`,
   `signals.py`, `breakout_log.py`, `app.py` (`save_config`,
   `save_snapshot`, `save_funder_cache`), `pages/4_📊_CVD.py`
   (`save_funder_cache`), `scripts/daily_snapshot.py`. Format JSON output
   TIDAK berubah (kwargs `separators`/`indent` dipertahankan).
3. **Write gagal tidak diam lagi.** `except Exception: pass` yang membungkus
   PENULISAN file kini `print(f"WARN: failed to save ...: {exc}",
   file=sys.stderr)`. `except: pass` untuk fetch/parsing data eksternal
   TIDAK diubah (fallback graceful memang disengaja). `record_conviction`
   tetap re-raise (jangan laporkan sukses kalau belum sampai disk).
4. **Dead code dihapus.** Blok `if False: with col_liq:` di `app.py`
   (mereferensikan `col_liq` yang undefined — akan NameError kalau flag
   pernah diaktifkan) dihapus beserta isinya. `go.Figure`, `active_pools`,
   `pools`, `total_pool_liq` dsb. tetap dipakai kode lain → import tidak
   dihapus.
5. **Unused imports dibersihkan:** `PATTERN_EMOJI` duplikat (baris ~902
   `app.py`), `import tempfile as _tf` (`cvd.py`), `score_token`
   (`debug_rako.py`), `WHALE_SOL` (`signals.py`),
   `record_holder_snapshot` (`scripts/update_cvd.py`).
6. **`detect_clusters()` paralel.** Wallet yang BELUM ada di
   `funders_cache.json` di-submit ke `ThreadPoolExecutor`
   (`workers = min(8, n)`), wallet ter-cache tetap lookup lokal tanpa
   network. Hasil future diambil via `as_completed` dan dict `disk`
   diupdate di MAIN thread (tanpa lock); `progress_cb` tetap terpanggil
   per-future selesai; `time.sleep(0.1)` dihapus (rotasi key di
   `core._helius_candidates`/`_helius_rotation_lock` sudah thread-safe);
   `save_funder_cache(disk)` sekali di akhir; pass terakhir tetap dalam
   urutan wallet asli → `groups`/`cdf`/`info` deterministik identik dengan
   loop sekuensial lama.
7. **Tombol "🔄 Force refresh now" DIHAPUS** (permintaan owner). Gantinya:
   `add_to_watchlist()` men-set flag `watchlist_auto_refresh_cas` di
   session_state (best-effort, aman dipakai cron karena wrapped try/except),
   dan freshness sweep di `app.py` otomatis backfill token baru
   (`update_token_cvd` + `record_conviction`, progress bar) pada rerun
   berikutnya — card langsung tampil dengan data segar di run yang sama.
   Banner peringatan token stale tetap ada.
8. **`scripts/daily_snapshot.py` menyimpan `name`** (nama lengkap token)
   di history.json. Konsumen lama aman: semua pembaca pakai
   `.get("symbol")`/`.get(...)` dengan fallback, field `name` opsional.

### Verifikasi

- `python -m py_compile` 11 file target — lulus.
- `python -m pyflakes *.py pages/*.py scripts/*.py` — semua warning task
  hilang; sisa 2 warning `f-string is missing placeholders` lama yang
  memang sudah ada sebelum perubahan (app.py:1191, pages/4:342).
- `tests/test_breakout_guard.py`, `tests/test_scoring_continuity.py`,
  `tests/test_markup_ai_prompt.py` — ALL PASSED (3/3).
- Offline determinism test `detect_clusters`: hasil identik dengan
  referensi sekuensial; wallet ter-cache tidak di-fetch ulang;
  `save_funder_cache` tepat 1×; progress monotonik 0.1→1.0.
- Offline watchlist test: op journal `source="hrhr"` bertahan melewati
  replay `_apply_ops` + `load_watchlist`; journal ter-clear setelah push.
- `git diff --check` bersih (dengan `core.whitespace cr-at-eol`).

### Catatan / sisa PR

- Estimasi paralelisme poin 6: sebelumnya 1 wallet sekuensial (dengan
  sleep 0.1s/wallet); sekarang sampai 8 wallet bersamaan (Deep/100 holder
  belum ter-cache → ~13 batch vs 100 iterasi + 10 detik sleep total).
- Auto-refresh hanya 1× percobaan per add (flag di-consume); kalau gagal,
  data diisi cron 4h berikutnya (sama seperti perilaku tombol lama yang
  butuh klik ulang).

## 2026-08-01 — Phase avg conviction 6-48h + pola candle H4/H1 + real vs dust + ATH + Top 10 + Quick Pick fix

### Yang berubah

1. **Phase (semua) memakai rata-rata conviction 6–48 jam.** `cvd.conviction_avg(pts)`
   menghitung rata-rata conviction dari point cron (window 6h) dalam 48 jam
   terakhir. `detect_phase()` sekarang memakai angka ini untuk SEMUA ambang
   phase (Markdown <30, Accumulation-Late ≥50, dll) dan SEMUA pesan `reason`
   menampilkan `avg conviction X% (6-48h)` — termasuk **Distribution-Early**
   yang tadinya hanya lihat 6 jam terakhir. Momentum pendek (naik/turun)
   tetap dari 2 titik terakhir. Owner butuh angka rata-rata supaya bisa
   dibandingkan dengan analisa CVD 48h.
2. **Pola candle body kecil (doji/hammer/spinning top) H1 & H4 48 jam.**
   - `cvd._classify_small_body()` — satu jalur klasifikasi (Doji family
     body ≤10%, Hammer/Inverted Hammer ≤30%, Spinning Top ≤25%).
   - `cvd.candle_pattern_summary(candles)` — counts pola + **range harga**
     (low–high) semua candle pola; `cvd.aggregate_candles(h1, 4)` — H4 dari
     H1 (buang grup parsial/bar berjalan).
   - Card **LP Radar** dan **Degen Radar** menampilkan detail H4 dan H1
     **terpisah** beserta range-nya (mis. `🕯️ H4 body kecil 🕯️ Doji 2x ·
     range $0.000012 – $0.000015`). H1 diambil dari cache candle watchlist
     yang sudah ada (`_daily_candles`), H4 di-aggregate dari H1 → **tidak
     ada fetch GeckoTerminal tambahan per card**.
3. **Real holder vs dust aktif lagi di card LP & DEGEN.** `app.fetch_holder_data()`
   (supply + holders dalam satu fetch Helius ter-cache, di-share dengan
   holder-delta panel) dan `app.fetch_real_dust_ratio()` (threshold dari
   sidebar `dust_limit_usd`, default $5). Card menampilkan
   `💎 Real ≥$5: N · 🪙 Dust: M · ratio R%` — hijau jika tidak ada dust
   atau real ≥ 50% dari dust, merah di bawahnya.
4. **% dari ATH di scan trending + cards.**
   - `gmgn_screener.screen()` (trending) mengisi `row["down_ath"]` dan note
     `Down X% dari ATH` (sama seperti HRHR; ≥90% dapat 🟢).
   - Kolom **ATH** baru di tabel screener (`trending_ui.COLUMNS`), glow
     hijau untuk retrace ≥90% (display-only, tidak menambah Fit).
   - Saat ⭐ watch dari screener, `add_to_watchlist(..., down_ath=...)`
     menyimpan ke watchlist meta; card LP/DEGEN menampilkan
     `📉 dari ATH: -X%` via `app._ath_html()` (fallback dari session
     screener rows untuk token lama).
5. **Tulisan `T10` → `Top 10`** di notes, kolom tabel, wins, dan risk
   reasons screener. Regex glow tetap menerima format lama `T10` maupun
   baru `Top 10`.
6. **Card LP & DEGEN diperbesar** (min 320px / max 400px, `overflow-wrap:
   anywhere`, badge phase bisa wrap) untuk menampung detail baru tanpa
   terpotong.
7. **Bug fix Quick Pick loop.** Blok Quick Pick di `app.py` dulu memanggil
   `st.rerun()` setelah set `trigger_analyze`/`cvd_on`/`cvd_win` → selectbox
   masih terpilih → flag diset lagi → **loop rerun tanpa henti**. Sekarang
   selectbox di-reset ke placeholder dan analisis diproses di run yang sama
   (tanpa rerun).
8. **Defensive init `_daily_candles = {}`** sebelum blok watchlist supaya
   LP/Degen Radar tidak crash saat watchlist kosong.

### Verifikasi

- `tests/test_candle_patterns.py` — 15 case: klasifikasi lama + summary
  range, agregasi H1→H4 (grup parsial dibuang), `conviction_avg` (window
  48h, poin tua diabaikan, fallback sparse), dan `detect_phase` memakai
  rata-rata 6-48h (level + pesan Distribution-Early).
- `tests/test_markup_ai_prompt.py` — test baru `test_trending_rows_carry_down_ath`
  (down_ath dihitung dari price/ath, note + 🟢 ≥90%) + glow `Top 10` dan
  legacy `T10`.
- Seluruh 9 suite test PASS tanpa pytest/jaringan; semua file Python lulus
  `py_compile`; `git diff --check` bersih (dengan `core.whitespace cr-at-eol`
  karena repo mixed CRLF/LF).
- `gmgn_screener.py` di-patch mempertahankan line-ending asli per baris
  (mixed CRLF/LF) supaya diff minimal.

### Catatan / sisa PR

- Card menampilkan `📉 dari ATH` hanya jika datanya ada (watchlist lama
  tanpa `down_ath` akan kosong sampai di-add ulang dari screener atau
  tersedia di session screener rows).
- `down_ath` GMGN bisa berubah nama field kapan saja; `_get_avg_cost_and_ath`
  sudah punya fallback deterministik (90%) untuk HRHR micro-cap — untuk
  trending, fallback yang sama berlaku.

---

## 2026-08-01 — CVD whale/dolphin activity + separated wallet details

### Yang berubah

1. **Whale activity ikut tampil di row cohort CVD** — halaman CVD sekarang
   menampilkan `🐋 Whale held buy`, `🐋 Whale pure sell`, `🐋 Whale net`, dan
   rasio `🐋 vs 🐬 net`; dolphin tetap tampil di row sendiri.
2. **List wallet dipisah** — tidak lagi mencampur semuanya dalam satu tabel.
   Ada tabel terpisah untuk whale pure accumulators, whale pure distributors,
   dolphin pure accumulators, dolphin pure distributors, light holders, dan
   traders. Semua membawa Buy/Sell/Net/Held %, swaps, age, dan flags.
3. **No-buy holders** — CVD menampilkan holder-rank whale/dolphin current
   holders yang tidak punya buy di window terpilih tetapi masih memegang token
   (scan holder Helius, cached 1 jam, pool address dikecualikan). Selain itu,
   GMGN sell-only wallets yang masih punya token balance juga muncul terpisah.
4. **Export report/CSV ikut diperbarui** — markdown report membawa ringkasan
   whale/dolphin held-flow, section detail per cohort, dan section no-buy
   holders bila ada.
5. **Advanced cohort divergence** — section `🧭 Advanced cohort divergence`
   membandingkan price pivots vs `Whale Held CVD`, `Dolphin Held CVD`,
   `Trader CVD`, dan `Pure Distributor CVD`. Ini advisory dan difilter oleh
   minimum SOL movement; divergence lama All CVD + Whale-swap CVD tetap utuh.
6. **Helper network-free di `cvd.py`** — `split_wallet_profile_cohorts()`,
   `cohort_activity_summary()`, `cohort_cvd_series()`,
   `detect_cohort_divergences()`, dan `detect_no_buy_holders()` supaya logic
   UI bisa dites tanpa Streamlit/jaringan.

### Kenapa

Pemilik melihat row dolphin (`Dolphin pure buy/sell/net`) tetapi aktivitas
whale hanya tersirat di rasio. Dibutuhkan pemisahan eksplisit agar mudah
membedakan: whale yang benar-benar hold, dolphin absorber, light holder yang
hanya sedikit jual, trader yang masih long, dan holder besar yang tidak membeli
lagi tapi masih memegang supply.

### Verifikasi

- `python -m py_compile cvd.py pages/4_📊_CVD.py tests/test_wallet_profiles.py`
  — lulus.
- `python tests/test_wallet_profiles.py` — ALL PASSED, termasuk test baru
  untuk split cohort, summary whale/dolphin, cohort CVD divergence, dan
  no-buy GMGN holder.
- `python tests/test_flow_safety.py` — ALL PASSED.

### Catatan

`light_holder` dan `trader` secara definisi harus punya buy di window. Jika
wallet tidak membeli sama sekali tetapi masih hold, kasus itu ditampilkan di
section **Holders with no buy in this window**, bukan dipaksa masuk label
light/trader.

---

## 2026-07-31 (7) — Insider/Bundler 15% presentation + links + regression

### Yang berubah

1. **Kolom Risk `bndl`/`insd`** — threshold merah disamakan 15% untuk keduanya;
   <15% hijau `#22c55e`, >=15% merah `#ef4444` (sebelumnya insd 10% abu-abu).
2. **Note `insider/bundler pressure`** — `_format_note_part()` menerima `row`;
   glow hijau jika `max(insider_ratio, bundler_rate) < 0.15`, merah jika >=0.15.
3. **Link GMGN & DexScreener** — kecil di samping nama token (`cc[1]`) pada scan
   trending/degen.
4. **Caption Screener** — menjelaskan `bndl/insd <15% = hijau · >=15% = merah`.
5. **Regression test** — `tests/test_markup_ai_prompt.py`: 14,9% / 12% hijau,
   tepat 15% merah, note green/red glow, semua lulus.
6. **Tidak mengubah** formula Fit, penalty curve, gate severity, hard-risk cap.

### Verifikasi

- `python tests/test_markup_ai_prompt.py` — ALL PASSED (termasuk 6 assertion baru).
- `python tests/test_scoring_continuity.py` — ALL PASSED (formula tidak berubah).
- `python -m py_compile trending_ui.py` — lulus.
- `git diff --check` — bersih.

---

## 2026-07-31 (6) — Fit direbalance menjadi structural-only

### Keputusan pemilik

Price action 24h/1h, smart-money, KOL, holder points, dan age points tidak lagi
menentukan Fit. Gate untuk pump/dump 24h, smart-money tipis, dan umur terlalu
muda juga dihapus. Holder count tetap menjadi safety gate karena pemilik tidak
meminta gate holder dihapus, tetapi tidak lagi memberi raw points.

### Formula baru

Empat pillar raw score berjumlah tepat 100:

- **T10 concentration: 30** — kualitas distribusi supply;
- **Liquidity/MC: 30** — kemampuan entry/exit LP;
- **Rug score: 25** — keamanan kontrak/struktur;
- **Volume/MC sanity: 15** — aktivitas cukup, tetapi bobot paling kecil karena
  volume paling mudah dimanipulasi.

KOL bonus dan `smt_thin` penalty dihapus. Price dan age sekarang netral
terhadap Fit tetapi tetap tampil sebagai konteks; smart/KOL dihapus dari row
scorer dan tabel. Sorting tie juga tidak lagi memakai smart wallet; urutannya
Fit exact, T10 lebih rendah, lalu liquidity lebih tinggi.
Penalty wallet-risk, structural gates lain, holder safety gate, dan hard-risk
cap 40 tetap aktif.

### Kalibrasi dan verifikasi

- 20.000 token sintetis yang menyerupai hasil prefilter: mean Fit lama
  **58,0**, baru **58,5**. PRIME 10,5% → 13,5%; OK 48,5% → 47,6%; WEAK
  38,5% → 34,2%; POOR 2,5% → 4,7%. Hard-risk classification tidak berubah.
- `tests/test_scoring_continuity.py` mengunci empat weight, total 100,
  netralitas price/smart/KOL/age, gate struktural, kontinuitas, dan ranking.
- Seluruh test suite lulus; file Python terkait lulus `py_compile` dan
  `git diff --check` bersih.

---

## 2026-07-31 (5) — Highlight T10 concentration dan retrace ATH

### Yang berubah

1. Note seperti **`T10 29% too concentrated`** sekarang merah terang dengan
   glow. Kolom T10 juga memakai style yang sama mulai 25%, yaitu titik saat
   concentration gate mulai benar-benar menahan grade tertinggi.
2. Note **`Down 90.0% dari ATH`** sekarang hijau terang dengan glow untuk
   retrace minimal 90%. Batas sebelumnya `>90%` diubah menjadi `>=90%`.
3. Styling dipusatkan di `_format_note_part()` agar dashboard utama dan
   halaman Screener selalu memakai aturan visual yang sama.

Perubahan ini **display-only**: retrace dari ATH tidak menambah Fit dan formula
Fit/T10 tidak diubah. T10 tetap memengaruhi pillar, gate, penalty, dan hard-risk
cap sesuai logika scoring yang sudah ada.

### Verifikasi

- `tests/test_markup_ai_prompt.py` mengunci red glow T10, green glow ATH pada
  90%, serta memastikan 89,9% belum glow.
- `tests/test_scoring_continuity.py` tetap lulus, membuktikan distribusi dan
  kontinuitas Fit tidak berubah; file terkait lulus `py_compile`.

---

## 2026-07-31 (4) — Perbaikan stale-token backfill dan status UI

### Masalahnya

Manual backfill gagal dengan `NameError: name 'x' is not defined`, tetapi UI
selalu menutup proses dengan notifikasi hijau `Backfilled N token(s)`.
Akibatnya kegagalan terlihat seperti sukses dan CA yang belum diperbarui sulit
dibedakan dari CA yang benar-benar sudah mendapat conviction point baru.

### Yang berubah

1. **Akar `NameError` diperbaiki** — filter deduplikasi raw swap di
   `update_token_cvd()` memakai `x[2]` di luar scope `lambda x`. Sekarang key
   comprehension yang benar dipakai untuk filter umur 48 jam dan sorting.
2. **Status berdasarkan hasil nyata** — dashboard mencatat daftar berhasil
   dan gagal. Notifikasi hijau hanya muncul jika semua token berhasil;
   kegagalan total menjadi merah dan partial success menjadi kuning.
3. **Tidak ada false refresh** — CA hanya dimasukkan ke set refreshed setelah
   `record_conviction()` benar-benar menghasilkan point. Main pool yang tidak
   ada dan window tanpa swap sekarang dihitung gagal serta bisa dicoba lagi.
4. **Error persistence diteruskan** — kegagalan atomic save
   `conviction.json` tidak lagi ditelan; caller dapat menandainya gagal.

### Verifikasi

- Regression suite baru `tests/test_cvd_update.py` membuktikan dedupe/prune
  swap selesai tanpa `NameError`, hasil tersimpan, dan error atomic save
  diteruskan ke caller.
- Seluruh 9 test suite lulus tanpa jaringan; `app.py` dan `cvd.py` lulus
  `py_compile`; `git diff --check` bersih.

---

## 2026-07-31 (3) — Light Holder & Trader profiles, persistence conviction bonus

### Yang berubah

1. **Light Holder & Trader Profiles** — `wallet_profiles()` sekarang mengklasifikasikan wallet menjadi 5 kategori:
   - `pure_accum` (sell ≤ 5% of buy) — held 95%+
   - `light_holder` (5% < sell < 10% of buy) — held 90%+
   - `trader` (10% ≤ sell ≤ 50% of buy) — held 50%+
   - `two_way` (sell > 50% of buy, buy > 5% of sell) — bot/MM noise
   - `pure_dist` (buy ≤ 5% of sell) — sold & left

2. **Conviction Calculation dengan Weighted Volumes** — `conviction_split()` sekarang menghitung conviction dengan weighted buy volumes:
   - pure_accum: 100% weight
   - light_holder: 75% weight
   - trader: 30% weight
   - two_way: 0% weight
   - Formula: `effective_buy / total_buy * 100`

3. **Persistence Conviction Bonus** — `record_conviction()` menambahkan bonus +3% per cron point jika jumlah pure_accum + light_holder wallet bertambah berturut-turut. Cap +15%. Contoh: naik 3x berturut-turut = +9% bonus.

4. **UI Update** — Pure flow metrics di dashboard sekarang 5 kolom: Pure Accum, Light Holder, Trader, Pure Distribution, Conviction Ratio. Accumulator table juga menampilkan light_holder dan trader wallets. CVD page juga diupdate.

### Kenapa

- Wallet yang sell 7% masih essentially holder — masuk two_way sebelumnya terlalu agresif.
- Trader yang masih hold 50%+ masih ada kontribusi ke conviction — tidak boleh 0%.
- Persistence bonus menghargai token yang holder base-nya tumbuh secara konsisten.

### Verifikasi

- 8/8 test suites lulus (termasuk `test_wallet_profiles.py` baru).
- Semua file Python lulus `py_compile`.

---

## 2026-07-31 (2) — H4 candle pattern detection for Degen, phase threshold memecoin tuning

### Yang berubah

1. **H4 Candle Pattern Detection (Degen HRHR)** — Fungsi `detect_candle_patterns()` di `cvd.py` mendeteksi pola candle body kecil (Doji, Dragonfly Doji, Gravestone Doji, Hammer, Inverted Hammer, Spinning Top) di 12 candle H4 terakhir (48 jam). Hasilnya ditampilkan di kolom Notes HRHR screener dengan warna hijau glowing (`text-shadow`). Setiap token di-resolve pair address-nya via DexScreener, lalu fetch H4 candles dari GeckoTerminal. Pattern di-cache di session state supaya tidak re-fetch setiap rerun.
2. **Phase Threshold Tuning untuk Memecoin** — Threshold `price_flat` di `detect_phase()` diubah dari ±8% jadi ±20% (akumulasi di bawah 20% masih flat). Threshold `Markup`/`Markdown` diubah: 24h > 50% ATAU 6h > 25% untuk dianggap "big move". `Distribution-Early` threshold diubah dari ±8% jadi ±20%. Parameter `price_change_6h` (6H change dari DexScreener) ditambahkan ke `detect_phase()` dan `chg6` ditambahkan ke `_prices` di `app.py`.
3. **Test suite** — `tests/test_candle_patterns.py` ditambahkan (11 test cases, semua passed).

### Kenapa

- Pola candle body kecil (Doji, Hammer, dsb.) di H4 adalah acuan penting untuk degen entry di fibo bawah. Munculnya pola ini menandakan potensi reversal.
- Threshold lama (±8% flat, ±15% big) terlalu ketat untuk memecoin yang volatility-nya tinggi. 20% masih normal untuk akumulasi, dan Markup/Markdown perlu 25%+ di 6h.

### Verifikasi

- 7/7 test suites lulus (termasuk `test_candle_patterns.py` baru).
- Semua file Python lulus `py_compile`.

---

## 2026-07-31 — Degen Radar, LP Radar split, CVD dolphin details, bug fixes

### Yang berubah

1. **LP Radar & Degen Radar Split** — LP Radar sekarang hanya menampilkan token dari watchlist dengan source "trending" (dari GMGN trending screener). Token dari HRHR screener ditampilkan di card baru "⚡ Degen Radar" dengan border oranye dan styling yang berbeda. Source tracking ditambahkan ke `watchlist.py` (`add_to_watchlist(ca, source="trending"|"hrhr"|"manual")`).
2. **HRHR Label "FOR DEGEN"** — Label expander HRHR diubah dari "FOR LP" menjadi "FOR DEGEN" untuk menegaskan bahwa token ini berisiko tinggi dan untuk degen trader.
3. **Watchlist Ticker Bar Dinonaktifkan** — Ticker bar (chips harga scrollable) di atas LP Radar dinonaktifkan per permintaan owner. Safety sweep dan freshness sweep tetap berjalan normal.
4. **Holder Warning Disederhanakan** — Banner merah "UNHEALTHY HOLDER BASE" yang mengkhawatirkan diganti dengan peringatan kuning yang lebih informatif dan tenang ("Holder base tipis").
5. **Quick Pick Tanpa Tombol** — Tombol "Gunakan" dihapus dari Quick Pick. Memilih token dari dropdown langsung memicu Analyze + CVD 48h secara otomatis.
6. **CVD Dolphin Details** — Halaman CVD sekarang menampilkan dolphin metrics row (pure buy/sell/net, whale vs dolphin ratio) dan kolom 🐬 Dolphin di multi-window table. Sebelumnya dolphin hanya muncul di tabel accumulator/distributor.
7. **Bug Fix — hist_df NameError** — `hist_df` yang dulu hanya didefinisikan di dalam `if False:` block (chart section yang dinonaktifkan) sekarang dipindahkan keluar sebelum Divergence Check section. Ini memperbaiki crash `NameError: name 'hist_df' is not defined` yang muncul di Streamlit Cloud.
8. **Bug Fix — GMGN Screener Random Fallback** — Fallback value di `_get_avg_cost_and_ath()` yang menggunakan `random.uniform()` diubah menjadi deterministik (-65% avg cost, -90% from ATH) supaya token yang sama selalu mendapat skor yang sama antar run.
9. **Bug Fix — Duplicate drop_from_peak** — Baris `drop_from_peak = peak4 - cv` yang duplikat dihapus.
10. **Test Update** — Test `LP Radar card avoids invalid nested anchor markup` diupdate dari `== 2` menjadi `>= 2` untuk mengakomodasi Degen Radar card yang juga menggunakan `href='{_cvd_link}'`.

### Verifikasi

- Seluruh suite test lulus: `tests/test_breakout_guard.py`, `tests/test_scoring_continuity.py`, `tests/test_markup_ai_prompt.py`, `tests/test_flow_safety.py`, `tests/test_holder_delta.py` — **ALL PASSED (5/5)**.
- Seluruh file Python lulus kompilasi `py_compile`.

---

## 2026-07-31 — GMGN API full, CVD Deep Focus, High Risk Screener & Watchlist Quick Delete

### Yang berubah

1. **GMGN Trades API & Helius Bypass** — Mengubah seluruh fungsi fetch otomatis untuk selalu memprioritaskan GMGN Token Trades API (`use_gmgn_trades = True`) dan menonaktifkan cron holder snapshot harian dari Helius (`_try_snapshot` mengembalikan empty). Menghapus checkbox toggle standard/GMGN dari UI.
2. **Watchlist Quick Pick & Auto Analyze** — Quick Pick di halaman utama kini langsung memicu proses analisis, mengaktifkan visualisasi CVD, dan mengambil seluruh rentang waktu 48 jam secara otomatis.
3. **Peningkatan Custom Range & AI Prompt** — Menghapus batasan waktu 48 jam untuk custom range di halaman CVD. AI Prompt di halaman CVD kini otomatis berfokus pada filter data timeframe terpilih jika custom date range aktif.
4. **Simplifikasi LP Radar Cards** — Menghapus noise flags, border menyala/glow, serta badge status (`KOKOH`, `NOISY`, dll). Menghadirkan *conviction sparkline* yang bersih dengan warna hijau untuk tren naik dan merah untuk turun, disertai catatan ringkas momentum akumulasi dan volume.
5. **High Risk High Reward Scanner** — Menambahkan scanner baru dengan kriteria 24h, umur koin 2d-60d, marketcap maks 250K USD, volume 24 jam min 10K USD, total gas fee min 30 SOL, holders min 1000, serta holder average cost <= -50%. Ditampilkan persentase penurunan dari ATH (jika >90% catatan berwarna hijau).
6. **Watchlist Quick Delete** — Menambahkan expander khusus di dashboard utama untuk menghapus token dari watchlist langsung di tempat dengan satu tombol tanpa perlu berpindah halaman.
7. **Scoring Risk & UI formatting** — Mengubah batas bndl (bundler) menjadi 15%, trap dan bot tetap 30% sebelum ditandai merah. Memperbesar ukuran teks Risk dan Notes menjadi `0.80rem` agar lebih nyaman dibaca.
8. **Dolphin Cohort di Pure Accumulator/Distributor** — Menambahkan kategori Dolphin (`1.0 <= buy < 3.0 SOL`) di bawah Whale pada tabel akumulator dan distributor halaman utama dan halaman CVD.
9. **Perbaikan Keamanan Data (Atomic Save & Dedup)** — Penyimpanan file `cvd.json` dan `conviction.json` kini menggunakan mekanisme `tempfile` + `os.replace` secara atomik untuk mencegah korupsi data. Swaps raw juga secara otomatis dideduplikasi dan diurutkan secara kronologis saat pembaruan untuk menghindari inflasi volume tidak masuk akal.
10. **Scoring Checklist Keamanan & LP locked** — Menghapus metrik LP locked dari penambahan skor karena token pumpfun sudah otomatis terkunci, serta menyematkan tanda bahaya keras jika LP terdeteksi 0% (tidak terkunci sama sekali). Batas dust default diubah menjadi $5.
11. **CVD Deep Focus** — Menghadirkan tabel analisis kepemilikan dan retensi pembeli yang murni dari timeframe terpilih saja, serta menyaring keluar noise berupa dust (<$5), bots, dan churn.

### Verifikasi

- Menjalankan seluruh test suite (`tests/test_breakout_guard.py`, `tests/test_flow_safety.py`, `tests/test_markup_ai_prompt.py`, `tests/test_scoring_continuity.py`, `tests/test_holder_delta.py`): **ALL PASSED (5/5)**.
- Seluruh file Python lulus kompilasi `py_compile`.

---

## 2026-07-29 — LP Radar 48h + CVD flow safety + GMGN new penalties + Watchlist quick-pick

### Yang berubah

1. **LP Radar multi-window sparkline** sekarang punya **4 baris** —
   `6h → 12h → 24h → 48h` (sebelumnya 3). Baris ke-4 butuh ≥8 cron
   point (≥2 hari) untuk diisi; sebelum itu mirror 24h supaya tidak
   misleading ke 0%. Caption diperbarui menjelaskan perilaku ini.

2. **CVD flow safety checks** (4 function baru di `cvd.py`):
   - `flow_freshness(ca)` — umur conviction point terakhir, OK bila <90m
   - `flow_persistence(ca)` — 3 cron point beruntun searah, masing-masing
     ≥5 SOL net
   - `flow_distribution(ca)` — `net_pure` drop ≥30% dari peak 24h
   - `flow_quality(ca)` — window cukup aktif, tidak dominated 1 wallet
   - `flow_check_panel(ca)` — wrapper, kembalikan keempatnya sekaligus

3. **GMGN screener: 2 penalty curve + 2 hard risk baru** (PR #5 eksplisit
   sebut tapi belum masuk):
   - `fresh_wallet` — anchor 0.25/0.40/0.55, hard risk pada 0.50
   - `holder_conc` — top-50 holder share, anchor 0.65/0.75/0.85,
     hard risk pada 0.85 (tidak ada public float)
   - Field `fwr` / `fresh_wallet_rate` dan `t50` /
     `top_50_holder_rate` di payload; fallback ke `top-10 × 1.1` kalau
     GMGN tidak kirim `t50` (t10-derived 0-1)

4. **Watchlist quick-pick** — `pages/3_⭐_Watchlist.py` punya expander
   "⚡ Quick-pick" di atas input manual. Pilih dari CA yang sudah
   dianalisis (`history.json`) atau yang barusan muncul di trending
   screener sesi ini. Manual CA input tetap di bawah, jadi quick-pick
   additive, bukan replacement.

5. **Line endings** — PR #5 di-upstream akhirnya CRLF lagi (squash
   merge + GitHub CRLF autosave). PR ini tetap CRLF karena itu
   konvensi repo (`tests/*.py` semua CRLF, `.gitattributes` tidak ada
   untuk override).

### Verifikasi

- `tests/test_flow_safety.py` (baru) — 8 sub-test, 33 assertion,
  tanpa pytest/jaringan. Coverage:
  - freshness: no history / fresh / stale 4h
  - persistence: <2 points / 3-point accum / 3-point dist / small
    moves / sign-flip / zero trailing
  - distribution: <4 points / no net-buy peak / mild 25% drop /
    40% drop flagged
  - quality: no history / quiet / normal
  - panel: keempat sub-check muncul
  - fresh-wallet: penalty kontinu, 25% ≤ 8 pts, 55% → AVOID
  - holder-conc: penalty kontinu, 65% ≤ 8 pts, 90% → AVOID
  - contract: `fresh_wallet_rate` & `holder_conc` di row output
- `python -m py_compile` untuk 4 file Python yang diubah — lulus.
- `python -m pytest tests/` — 33/33 passed (25 lama + 8 baru).

### Tidak dilakukan

- **Cron schedule tidak diubah** (4h CVD / 8h watchlist). `AGENTS.md`
  tegas bilang agen tidak boleh edit `.github/workflows/`. Kalau mau
  balik ke hourly, pemilik sendiri yang harus commit.
- Tidak menambah field baru di `trending_rank` parser. Yang dipakai
  mengikuti apa yang GMGN kirim; kalau payload berubah, `_first()`
  graceful jatuh ke 0.0 → penalty tidak kena → token akan kelihatan
  lebih baik dari yang sebenarnya. Pantau di run berikutnya.

### Belum terverifikasi ⚠️

- `fwr` / `t50` belum pernah kena payload GMGN sungguhan (key belum
  dikonfirmasi). Kalau GMGN kasih nama lain, field baru akan jadi 0
  dan penalty tidak firing — test hanya pakai path yang sudah
  diverifikasi kontinuitasnya.

---

## 2026-07-29 — LP Radar rewrite: semua token + stability + multi-window + volume

### Yang berubah

1. **LP Radar sekarang menampilkan SEMUA watchlist token**, tidak hanya yang growing. Border card: hijau = kokoh, kuning = goyah, merah = melemah, glow hijau = grow 2x + kokoh.
2. **Stability badge**: 🟢 KOKOH (conviction stabil ≥30%, turun <15% dari puncak) · 🟡 GOYAH · 🔴 MELEMAH.
3. **Multi-window sparkline**: 3 baris (6h / 12h / 24h) — lihat apakah conviction konsisten di semua jendela atau hanya spike sesaat.
4. **Volume-quality indicator**: 💪 STRONG (≥100 SOL + ≥40%) · 🟡 NOISY · 👍 LIGHT · ⚪ THIN · 💤 QUIET.
5. **Test** — `test_ui_integration_guards` diperbarui: cek keberadaan badge KOKOH/GOYAH/MELEMAH dan volume-quality indicator.

### Verifikasi

- Semua 3 suite tes lulus (markup + guard + scoring).

---

## 2026-07-29 — Markup 48h + red notes + cron 4h/8h

### Yang berubah

1. **`markup_from_candles()`** — base diganti dari lowest low 30D ke **first candle close** dalam window. Threshold: danger ≥+100%, warn ≥+50% (dulu 300/150). Fetch candle: **hourly 48h** (dulu daily 30). Token baru tidak kena false positive markup.
2. **`fetch_watchlist_daily_candles()`** — sekarang fetch hourly 48h, bukan daily 30.
3. **Screener notes** — notes berbahaya ("already ran", "entrapment", "downtrend", dll) di-highlight **merah menyala** di kolom Notes.
4. **CVD workflow** — `cron: "20 */4 * * *"` (tiap 4 jam, dulu tiap jam).
5. **Snapshot workflow** — `cron: "0 */8 * * *"` (tiap 8 jam, dulu tiap 6 jam).
6. **Test** — `test_markup_contract` disesuaikan dengan base first-close 48h.

### Verifikasi

- `tests/test_markup_ai_prompt.py` — threshold 48h base first-close lulus.
- Semua file Python yang diubah lulus `py_compile`.

---

## 2026-07-29 — Audit bug/efisiensi + README sesuai perilaku program

### Bug dan risiko yang diperbaiki

1. CVD dulu selalu menambahkan row 48h walau user hanya fetch 4–36h. Sekarang
   `analysis_windows()` menjamin semua row berada di dalam window terpilih.
2. Rerun Streamlit memakai `time.time()` baru sehingga swap cache tampak
   mencakup makin banyak jam. Semua window/prompt sekarang di-anchor ke
   `fetched_at` snapshot asli.
3. Periode prompt di luar cakupan dulu tampak sebagai angka nol. Sekarang
   tiap row diberi status `lengkap`, `SEBAGIAN`, atau `TIDAK TERCAKUP`.
4. Card LP Radar memakai `<a>` bersarang untuk card + shortcut eksternal
   (HTML tidak valid). Link card, DexScreener, dan GMGN sekarang bersaudara.
5. Fetch candle harian watchlist yang semula serial sekarang concurrent
   (maksimum 8 worker) dan tetap di-cache 15 menit.
6. Event `guard_*` sudah ditulis ke `signals.json` tetapi tidak ada di metadata
   halaman Signals, sehingga hilang dari chart/filter. Lima tipe Guard kini
   dirender.
7. Contoh deploy berisi key nyata; diganti placeholder. Key yang pernah
   dipublikasikan tetap harus dirotasi karena masih ada di riwayat Git.
8. Label cron 2/4-hourly yang sudah basi diselaraskan dengan workflow hourly
   menit :20.

### Dokumentasi

`README.md` diganti penuh agar menjelaskan apa yang benar-benar dilakukan
program: holder/security, cluster, CVD, Prompt to AI, watchlist/markup safety,
GMGN screener, dua sistem alert, sumber data, instalasi, cron, state file,
tes, dan batasan.

### Verifikasi

- Seluruh suite di `tests/` lulus tanpa pytest/jaringan.
- Seluruh file Python lulus `py_compile`.
- `ruff` kategori fatal (`F`/`E9`) diperiksa; temuan baru dibersihkan.

---

## 2026-07-29 — Markup safety watchlist + Prompt to AI

### Yang berubah

1. `cvd.markup_from_candles()` mengukur kenaikan dari low harian terendah
   dalam 30 candle terakhir: warning +150%, danger +300%, lengkap dengan
   peak markup, jarak dari peak, label, dan kalimat warning.
2. Halaman utama menyapu **semua token watchlist** untuk danger +300% dan
   menampilkan banner merah sebelum filter `grow1`. Token dengan conviction
   datar tetap terlihat walaupun tidak mendapat card LP Radar.
3. `ai_prompt.py` membangun prompt CVD siap-salin untuk DeepSeek. Glosarium
   angka tampil sebelum data; cakupan window yang kurang diumumkan eksplisit;
   flow dipecah menjadi empat periode lama → baru; tabel pure wallet membawa
   umur 🐣/🌱/🌳; tugas AI mencakup skenario, verdict panik/tidak, dan
   invalidation tanpa target harga.
4. Tombol **Prompt to AI** memakai dropdown Time window yang sudah ada dan
   mempertahankan hasil analisis di rerun tanpa fetch kedua.

Perubahan dari `main` sebelum pekerjaan ini tetap dipertahankan: badge
EXTREME/HIGH, shortcut DexScreener/GMGN, dropdown CVD 4–48 jam, serta file
`docs/agents.md` dan `docs/progress.md` huruf kecil.

### Verifikasi

- `tests/test_breakout_guard.py` — semua 67 assertion lulus.
- `tests/test_scoring_continuity.py` — seluruh continuity/calibration lulus.
- `tests/test_markup_ai_prompt.py` — threshold 30D, kejujuran cakupan,
  urutan prompt, umur wallet, dan wiring UI lulus; tanpa pytest/jaringan.
- `python -m py_compile` untuk seluruh file Python yang diubah — lulus.

---

## 2026-07-29 — Breakout Guard: level D1, konfirmasi H4, atribusi flow

**Commit:** `58b5f35` (kode) + `0169f05` (workflow, oleh pemilik)

### Yang berubah

1. **Level dari candle D1**, bukan pivot H1 lagi (`cvd.daily_levels`).
   Pivot H1 menghasilkan puluhan level mikro → alert terlalu sering.
2. **Caption di tiap pesan Telegram** — 🛡️ BREAKOUT GUARD vs 📊 CVD MONITOR.
3. **Atribusi flow** (`cvd.flow_report` / `describe_flow` / `flow_warning`):
   tiap alert menyebut whale vs retail, jumlah wallet tiap sisi, pure accum
   vs distributor, aktor dominan, plus kalimat "jadi harus apa".
   Event dicatat ke **`breakouts.json`** (file baru, terpisah dari
   `signals.json`) dengan `parent_id` + `outcome`.
4. **Keputusan hanya saat close H4** — `closed_h4_candles()` membuang candle
   berjalan; `run_guard` cuma proses candle baru sejak `last_h4_ts`.
5. **Spring & reclaim** — spring = wick ≥20% range tertolak; reclaim = maks
   5 candle H4. Verdict membedakan WHALE vs RETAIL RECLAIM, BULLISH vs WEAK
   SPRING.

### Kenapa begitu

Pemilik fokus entry di H4 tapi ingin level yang "dilihat orang lain" → D1.
Dan alert yang cuma bilang "harga break" tidak bisa ditindaklanjuti; yang
dibutuhkan "whale jual ke retail" (hati-hati) vs "whale yang reclaim" (kuat).

### Bug yang ditemukan sambil jalan

- **Alert bisa hilang.** Kode lama menandai level `alerted` sebelum tahu
  Telegram berhasil. Sekarang teks disimpan di `breakouts.json` sampai
  terkirim, di-retry lewat `flush_pending_alerts()`.
- **Satu candle bisa jadi dua event.** Wick di bawah support lalu close di
  atas terbaca `spring` DAN `reclaim`. Sekarang `reclaim` menang.
- **Tes bocor** menulis ke `signals.json` asli — sekarang semua path di-patch
  ke tmpdir.

### Verifikasi

- `tests/test_breakout_guard.py` — 67 assertion, tanpa jaringan.
- Migrasi diuji: `levels.json` format H1 lama hanya jadi baseline di run
  pertama → tidak ada banjir alert saat deploy.
- YAML workflow di-parse ulang setelah pemilik edit: valid, 5 step utuh,
  4 secret masih ter-inject.

### Belum terverifikasi ⚠️

- **Endpoint `/ohlcv/day` GeckoTerminal** belum kena data sungguhan (tes
  pakai candle sintetis). Pantau run cron pertama.
- **Run pertama sunyi itu normal** — baseline `last_h4_ts` baru diisi;
  alert mulai run berikutnya. Jangan dikira rusak.

---

## 2026-07-28 — Scoring screener: ganti ambang tangga dengan ramp kontinu

**Commit:** `b175ad7`

### Masalahnya

Skor Fit tumpukan `if/elif`, jadi pergeseran input sekecil apa pun membalik
hasil. Kasus nyata RAKO (`5sd8bKra…`, ada di watchlist): **9 smart wallet =
54 WEAK, 10 wallet = 77 PRIME**. Token sama, beda satu wallet, beda 2 grade.

### Solusinya

Interpolasi linear piecewise: `CURVES` (8 pilar) · `PENALTY_CURVES` ·
`CAP_CURVE` (plafon mengikuti severity gate terburuk). Anchor tiap kurva
persis di ambang lama; gate jadi pita transisi yang titik tengahnya = ambang
lama. Tambah field `fit_exact` (skor sebelum bulat) untuk sorting.

### Verifikasi

6.000 token sintetis yang lolos prefilter GMGN:

| | lama | baru |
|---|---|---|
| PRIME | 1,7% | 2,9% |
| high-risk | — | **100% identik** |

Lompatan maksimum per langkah input: **23 poin → 3,5 poin**.
Dijaga `tests/test_scoring_continuity.py` (ambang gagal >4 poin).

### Catatan teknis

Sempat pakai **smoothstep**, ternyata 1,5× lebih curam di titik tengah —
padahal titik tengah itu justru ambang lama. Dikembalikan ke linear.

---

## Konvensi repo (jangan diubah tanpa alasan)

- Bahasa: balasan ke pemilik **Indonesia**, kode/docstring **Inggris**.
- Tes: tanpa pytest, tanpa jaringan, semua path file di-patch ke tmpdir.
- Baris kode maks 79 karakter (gaya lama repo).
- Agen **tidak bisa** menyentuh `.github/workflows/` — minta pemilik.

---

## 2026-08-08 — Cron detail CVD & Top Holders per 4 jam (`cvd-detail.yml`)

### Masalah
Setelah reset ke alur harian saja (`07:00 WIB`), tidak ada cron rutin yang berjalan per 4 jam untuk memperbarui data detail CVD (`cvd.json`), poin conviction (`conviction.json`), dan histori holder top (`holder_snapshots.json` & `real_dust_history.json`). Akibatnya, kolom **Diamond** dan **Real/Dust** pada tabel Watchlist di `app.py` tampil kosong (`—`) dan analisis Top 100 Holder pada halaman CVD memerlukan Helius API key yang mungkin tidak terkonfigurasi.

### Solusinya
1. **Cron per 4 jam:** Menambahkan workflow `.github/workflows/cvd-detail.yml` (`0 */4 * * *`) yang mengeksekusi `python scripts/update_cvd.py 60` dan meng-commit file `cvd.json`, `conviction.json`, `holder_snapshots.json`, `real_dust_history.json`, serta `watchlist.json`.
2. **Kalkulasi Top Holder & Watchlist Metadata:** Mengaktifkan kembali `_try_snapshot()` di `scripts/update_cvd.py` agar mengambil data top holder dari Helius atau GMGN (`gmgn_token_stat`), mencatat snapshot di `holder_snapshots.json` dan `real_dust_history.json`, serta menyimpan hasil kalkulasi (`diamond_pct`, `real_holders`, `dust_holders`) langsung ke metadata di `watchlist.json`.
3. **Fallback UI Interaktif:**
   - Pada `app.py`, fungsi `get_watchlist_details()` kini membaca metadata `watchlist.json` dan mendukung fallback ke file `holder_snapshots.json` dan `real_dust_history.json`, serta fallback live GMGN `token_stat`.
   - Pada `pages/4_📊_CVD.py`, fungsi `fetch_holder_snapshot()` mendukung fallback ke snapshot cron di `holder_snapshots.json` atau data GMGN top holders jika Helius API key tidak dikonfigurasi.
4. **Verifikasi Tes:** Seluruh tes eksisting (`tests/test_*.py` dan `unittest`) tetap hijau + ditambahkan `tests/test_cron_top_holders.py` untuk menguji integrasi kalkulasi snapshot dan fallback UI.

## 2026-08-10 — Owner request: CVD mengikuti ekstensi + priority 15 menit

- Menghapus seluruh panel **Fund Source Wallet (Funder) — Top 100 Holder** dari halaman CVD.
- Menambahkan `cvd_daily.py`, perhitungan yang mengikuti ekstensi GMGN: rekap per hari UTC, TX buy/sell, volume, delta CVD, rasio, status KERING/ABSORPTION/MARK-UP/DUMP, dan running CVD.
- `scripts/update_cvd.py` hanya merekam CVD harian sekali per tanggal dan mengirim Telegram digest harian; pemanggilan detector sinyal lama/conviction lama dihapus dari cron.
- Status KERING memindahkan token ke prioritas (`priority=true`). `priority-volume.yml` menjalankan scan GMGN setiap 15 menit dan mengirim alert Telegram menarik saat burst >500 TX dan ≥500 SOL.
- Format Telegram baru memakai blok HTML, metrik volume/CVD, tautan GMGN + DexScreener, dan dedupe 14 menit untuk burst.

Verifikasi: `python -m py_compile cvd_daily.py signals.py scripts/update_cvd.py scripts/priority_scan.py pages/4_📊_CVD.py` dan `python tests/test_cvd_daily.py`.

## 2026-08-14 — P3-Lock verifikasi + 4-Pilar detail + tombol Get Signal manual

### Status perubahan P3-Lock
- **Sudah terimplementasi di kode** (`prepump_detector.py`): `evaluate_golden_checks`
  mengembalikan tepat 6 cek inti tanpa `p3_lock`; `GOLDEN_TOTAL=6`. Retensi Top-100
  bersifat informasional dan **tidak** menghitung kegagalan verdict saat datanya
  `n/a` (diverifikasi `tests/test_prepump_detector.py`: "missing holder lock is
  excluded from scoring", "6/6 Setup Emas does not require holder lock").
- **Catatan data**: `signals.json` yang di-commit masih berisi format lama 7 cek
  (dengan `p3_lock`) dari cron cloud yang berjalan versi lama. Setelah cron jalan
  dengan kode baru, record baru berformat 6 cek / `total=6`.

### Fitur baru
1. **Detail 4 Pilar di watchlist (`app.py`)** — kolom "4 Pilar" kini menampilkan
   chip per-cek (✓ hijau = lolos, ✗ merah = gagal) lewat `pillar_checks_html()`.
   `resolve_prepump_row()` menambah field `total` agar angka "X/6" dinamis.
2. **Tombol "▶️ Get Signal (Manual Daily)"** di main page — menjalankan
   `scripts.update_cvd.run_daily(..., send_telegram=False)` untuk mengetes
   evaluasi harian manual; hasil ditulis ke `signals.json` + ditampilkan lewat
   `_show_manual_signal_results()`. Tidak mengirim Telegram (mode test).
3. `signals.drain_digest()` + param `send_telegram` di `run_daily` untuk membuang
   buffer digest tanpa kirim Telegram pada run manual.

Verifikasi: seluruh `tests/test_*.py` hijau (17 suite) dengan venv terpisah.
