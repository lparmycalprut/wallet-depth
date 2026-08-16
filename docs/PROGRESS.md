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
