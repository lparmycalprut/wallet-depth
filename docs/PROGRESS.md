# Progress

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
