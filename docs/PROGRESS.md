# PROGRESS — riwayat keputusan & status

Catatan berjalan supaya sesi baru tahu **sudah sampai mana** dan **kenapa
sesuatu dibuat begitu**. Tambahkan entri baru di ATAS, jangan hapus yang lama.

Format tiap entri: apa yang berubah · kenapa · bukti verifikasi · sisa PR.

---

## 2026-07-30 — Helius multi-key dipakai oleh semua alur

### Root cause

Field `helius_extra_keys` hanya dibaca oleh pool lokal di `cvd.py`. Fetch
holder utama di `app.py`, supply/mint/cluster, dan halaman Compare membangun
URL dari satu `helius_api_key`; HTTP 429 langsung gagal. Cache Streamlit juga
tidak memasukkan pool key sebagai argumen pada beberapa fetch CVD.

### Perbaikan

1. `core.py` menjadi sumber tunggal pool Helius: main + extra dari sidebar,
   config.json, `HELIUS_API_KEY`, `HELIUS_API_KEYS`, dan Streamlit Secrets
   digabung berurutan dan di-de-dup.
2. JSON-RPC dan Enhanced API memakai round-robin serta fallback ke key
   berikutnya pada HTTP 429/5xx (juga transient network/JSON-RPC rate errors).
3. Holder, supply, mint info, funder/cluster scan, Compare, CVD main/deep, CLI,
   dan dua cron memakai helper yang sama. Cache fetch menerima tuple pool;
   cache cluster menyertakan fingerprint pool agar perubahan key tidak memakai
   hasil scan lama.
4. `tests/test_helius_rotation.py` memverifikasi merge/de-dup semua sumber dan
   skenario key pertama 429 lalu key kedua berhasil tanpa jaringan.

### Verifikasi

- Semua 5 file `tests/*.py` menghasilkan **ALL PASSED**.
- Seluruh file Python lulus `py_compile`.
- Audit URL Helius: endpoint hanya didefinisikan di `core.py`; app/page/cron
  tidak lagi melakukan request Helius langsung.

---

## 2026-07-29 — Toggle GMGN Trades API untuk sumber CVD

### Perubahan

- `cvd.py` sekarang punya jalur GMGN Token Trades API: `fetch_swaps(...,
  use_gmgn=True)` memanggil `https://gmgn.ai/vas/api/v1/token_trades/sol/{ca}`.
- Mapping GMGN: `event` → buy/sell, `quote_amount` (atau fallback
  `amount_usd`/harga SOL) → SOL-equivalent, `timestamp` → ts, dan `maker`
  → wallet. Ada normalisasi timestamp ms dan heuristik lamports untuk
  `quote_amount` SOL yang raw.
- UI utama (`app.py`) dan halaman deep CVD (`pages/4_📊_CVD.py`) punya
  checkbox `🔄 Use GMGN Trades API`. Default OFF tetap Helius/incremental
  store seperti sebelumnya; ON bypass Helius untuk fetch swap dan menampilkan
  pesan jelas jika GMGN kosong/gagal.
- Error GMGN disimpan lewat `cvd.get_gmgn_last_error()` supaya kegagalan API,
  response kosong, schema berubah, atau semua trade di bawah threshold tidak
  membuat aplikasi crash.

### Verifikasi

- `.venv/bin/python -m pytest tests/` — **33 passed**.

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
