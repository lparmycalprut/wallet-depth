# PROGRESS — riwayat keputusan & status

Catatan berjalan supaya sesi baru tahu **sudah sampai mana** dan **kenapa
sesuatu dibuat begitu**. Tambahkan entri baru di ATAS, jangan hapus yang lama.

Format tiap entri: apa yang berubah · kenapa · bukti verifikasi · sisa PR.

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
