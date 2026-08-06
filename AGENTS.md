# AGENTS.md — baca ini dulu sebelum mengubah apa pun

File ini adalah **memori antar-sesi**. Agen AI (Arena, Claude Code, Cursor,
Copilot, dll.) membaca `AGENTS.md` secara otomatis saat membuka repo, jadi
sesi baru tidak perlu diberi konteks ulang dari nol.

> **Untuk agen:** setelah menyelesaikan pekerjaan yang mengubah perilaku,
> perbarui file ini + `docs/PROGRESS.md` dalam commit yang sama. Kalau tidak,
> sesi berikutnya akan mengulang pertanyaan yang sudah dijawab.

---

## 1. Apa ini

Dashboard Streamlit + cron untuk cek kesehatan token Solana sebelum
trade/LP. Bahasa pengguna: **Indonesia**. Komentar & docstring kode:
**Inggris** (ikuti gaya yang sudah ada).

Pemilik memakai ini untuk keputusan uang sungguhan. Jadi: **jangan pernah
melonggarkan kriteria risiko diam-diam**, dan kalau mengubah scoring,
buktikan kalibrasinya tidak bergeser (lihat §5).

**Kerapian Kode (Code Neatness & Formatting):**
- Seluruh agen AI yang berkolaborasi pada repository ini **WAJIB** merapikan semua kode sebelum mengakhiri sesi.
- Gunakan format PEP 8 yang konsisten, hilangkan unused imports/variables, dan berikan komentar/docstring bahasa Inggris yang jelas untuk setiap perubahan.
- Lakukan pengecekan linter dan selalu jalankan suite pengujian (`python -m unittest discover tests`) untuk memastikan kerapian kode tidak memicu bug baru.

## 2. Peta file

| File | Isi |
|---|---|
| `app.py` | dashboard utama (besar, ~110KB) |
| `pages/` | halaman Streamlit tambahan |
| `accum_history.py` | **Accumulation History (page 10)**: pure scoring/rolling-scan/merge 5-fase + paginasi candle GeckoTerminal `before_timestamp` |
| `core.py` | helper Helius (shared multi-key pool)/DexScreener/GeckoTerminal |
| `cvd.py` | store swap, bucket CVD, profil wallet, **level D1**, **flow attribution**, **flow safety checks** (freshness / persistence / distribution / quality) |
| `gmgn_screener.py` | screener GMGN + **scoring ramp kontinu** + **fresh-wallet & top-50 concentration penalties** |
| `ai_prompt.py` | builder prompt CVD siap-salin, jujur soal cakupan data |
| `breakout_guard.py` | **Breakout Guard**: level D1 + konfirmasi close H4 |
| `breakout_log.py` | log event level → `breakouts.json` |
| `signals.py` | log sinyal CVD/pre-pump → `signals.json` + Telegram (digest mode di cron) |
| `watchlist.py` | watchlist helpers (load/save/add/remove + GitHub commit) |
| `scripts/update_cvd.py` | entry point cron (tiap jam, menit :20) |
| `tests/` | 19 suite, **jalan tanpa pytest & tanpa jaringan** |

**File data yang di-commit cron** (jangan di-`.gitignore`):
`cvd.json` · `signals.json` · `conviction.json` · `levels.json` ·
`breakouts.json` · **`holder_snapshots.json`** (whale/dolphin holdings
delta baseline; 4h cron commit per CA per ~4h bucket) ·
**`real_dust_history.json`** (history real vs dust holder per jam —
lihat §7.7)

## 2.5 Monitor growth CVD (4 jam / 72 jam)

- Raw swap CVD disimpan selama **72 jam** (`cvd.update_token_cvd`); page CVD menyediakan pilihan 72H.
- Dashboard monitor menggabungkan pure accumulator (buy ≥0.1 SOL, sell ≤10%), conviction, TX, dan volume dalam bucket 4 jam. Grafik gabungan dinormalisasi ke index 100 agar arah lintas-unit terbaca.
- Cron mencatat metrik accumulator pada setiap snapshot conviction 4 jam dan mengirim `📊 CVD MONITOR` Telegram untuk semua empat metrik naik, semua turun, atau TX/volume ≥5× antar bin 4 jam (vs bin sebelumnya atau median 4 bin). Dedupe mengikuti `signals.py` (4 jam/token/tipe).
- "Holders with no buy in this window" sengaja nonaktif; jangan mengaktifkannya tanpa persetujuan karena menambah RPC holder mahal dan bukan flow aktif.

## 3. Dua jenis notifikasi Telegram — JANGAN tertukar

Keduanya lewat `send_telegram()` di `breakout_guard.py`, tapi beda sumber
dan beda caption. Caption itu wajib ada supaya pembaca tahu yang mana.

| Caption | Modul | Dasar | Dedupe |
|---|---|---|---|
| 📊 **CVD MONITOR** | `signals.py` | flow 4 jam + divergensi H1 | 4 jam per `(ca, tipe)` |
| 🛡️ **BREAKOUT GUARD** | `breakout_guard.py` | level **D1**, konfirmasi **close H4** | 12 jam per level |

Guard juga menulis ke `signals.json` (`src="guard"`, tipe `guard_*`) untuk
riwayat, tapi **tidak** memicu pesan CVD — terkunci dua lapis: tipe `guard_*`
tidak ada di peta emoji, dan `src != "cron"`. Jangan hapus salah satu kunci
itu tanpa sadar; nanti tiap breakout kirim dua pesan.

## 4. Breakout Guard — aturan yang sudah disepakati

Pemilik trading di **H4**, tapi memakai level **D1**. Itu disengaja.

- Level dari candle **harian** (`cvd.daily_levels`), pivot konfirmasi 2 bar
  kiri-kanan, level berjarak <1,5% digabung, maks 6 per sisi.
- Keputusan **hanya saat candle H4 CLOSE** (`closed_h4_candles` membuang
  candle berjalan). Jangan pernah pakai harga tick.
- Lima event: `breakout` · `failed_breakout` · `breakdown` · `spring` ·
  `reclaim` (maks **5 candle H4** setelah break).
- **Tiap notifikasi wajib menyebut siapa pelakunya** (whale vs retail, jumlah
  wallet, pure accum vs distributor). Ini permintaan eksplisit pemilik —
  "harga break" saja tidak actionable.
- Event tersimpan di `breakouts.json` dengan `parent_id` + `outcome`
  (`reclaimed`/`failed`/`held`/`no_reclaim`) supaya spring/reclaim bisa
  dianalisa terhadap break sebelumnya.

Konstanta (`breakout_guard.py`): `RECLAIM_MAX_CANDLES=5` ·
`ALERT_DEDUPE_H=12` · `ALERT_FRESH_H=8` · `MIN_PENETRATION=0.0015` ·
`MIN_WICK_RATIO=0.20`. Whale = swap ≥ `WHALE_SOL` (3.0 SOL) di `cvd.py`.

## 4.5 Holder-delta (whale / dolphin holdings baseline)

LP Radar juga menampilkan **delta holdings** (bukan delta swap) untuk
tier **whale** (top 1% by holdings) dan **dolphin** (1-5%). Dibanding
`flow_report` yang cuma lihat buy-sell di window, module ini
membandingkan dua snapshot holder (T0 = baseline, T1 = now) jadi
wallet yang beli 50 lalu jual 30 muncul sebagai **net +20**, bukan
+80 churn.

- **Snapshot store**: `holder_snapshots.json` (per CA, key = bucket
  4 jam). Commit tiap cron run via `cvd.record_holder_snapshot()`;
  `SNAPSHOT_MIN_GAP_S = 4*3600` jadi 4h cron commit tiap 4 jam.
  File ini WAJIB masuk daftar `git add` di `.github/workflows/cvd-update.yml`
  — kalau tidak, dashboard di Streamlit Cloud cuma lihat snapshot
  kosong dan badge tidak pernah muncul. **Pemilik sudah setuju update
  workflow via web**.
- **Tier classification**: `cvd.classify_holders()` sortir by holdings
  desc, potong di `WHALE_PCT=0.01` (whale) dan `DOLPHIN_PCT=0.05`
  (dolphin). Cut by COUNT, bukan by supply — tetap stabil saat
  holder set tumbuh.
- **Tier inheritance**: wallet yang turun dari whale ke minnow tetap
  dihitung sebagai whale story (rank `whale>dolphin>minnow`, pilih
  yang lebih tinggi). Jadi "5 whale exited" tidak salah jadi "0 whale
  exited + 5 minnow exited" kalau holders bertambah.
- **Exit rule**: drop ≥ `EXIT_DROP_PCT=0.90` (90%) dari baseline.
  Epsilon `+1e-9` di comparator untuk hindarin floating-point
  `100 * 0.10 = 9.999…` false-negative.
- **Threshold owner-tunable**: `WHALE_DELTA_MIN_SOL=1.0` dan
  `DOLPHIN_DELTA_MIN_SOL=2.0` di `cvd.py` (fallback). Owner set di
  `config.json` (`whale_delta_min_sol`, `dolphin_delta_min_sol`) dan
  via sidebar `🐋 Holder-delta thresholds` di `app.py`. Live sidebar
  override prioritas sampai owner klik "Save".
- **Level**: `ok` (nothing meaningful) · `warn` (any tier ≥ threshold)
  · `danger` (whale sold ≥ 2× threshold AND ≥1 exit).
- **UI**: `app.py` LP Radar card — row ke-3 dari header (setelah
  KOKOH/GOYAH + vol badge) berisi `🐋 +12.5 2↑` dan `🐬 -2.0 1↓`.
  Row ke-3 tidak ada (atau "⏳ waiting for snapshot baseline") sebelum
  cron commit baseline. Masuk juga ke "Why flagged?" list dengan
  emoji `🐋` (danger) / `🐬` (warn) / `ℹ️` (info).
- **Trade-off**: snapshot butuh 1 fetch Helius holders + 1 supply per
  CA per commit. LP Radar page load pakai holder list yang sama (cached
  1 jam lewat `st.cache_data`) jadi tidak fetch 2×.
- **Constanta tunable** di `cvd.py`: `WHALE_PCT`, `DOLPHIN_PCT`,
  `EXIT_DROP_PCT`, `SNAPSHOT_KEEP_DAYS=30`, `WHALE_DELTA_MIN_SOL`,
  `DOLPHIN_DELTA_MIN_SOL`, `SNAPSHOT_MIN_GAP_S`. Kalau diubah, jalankan
  `tests/test_holder_delta.py` (13 case) untuk verifikasi.

## 5. Scoring screener — ramp kontinu, bukan tangga

Dulu tumpukan `if/elif` sehingga 1 smart wallet membalik skor 54→77.
Sekarang interpolasi linear lewat `CURVES` / `PENALTY_CURVES` / `CAP_CURVE`.
**Kontrak Fit terkini:** raw score hanya 4 pillar struktural: T10 30,
liquidity/MC 30, rug 25, volume/MC 15. Price 24h/1h, holder count, dan age
tidak mendapat poin; price/age tetap konteks visual. Smart/KOL dihapus dari
scorer row dan tabel. Gate price, smart, dan age sudah dihapus; jangan
masukkan kembali diam-diam. Holder count tetap safety gate (tanpa raw points)
sesuai keputusan pemilik. Sorting tie memakai T10 lebih rendah lalu liquidity
lebih tinggi, bukan smart wallet.

**Kalau mengubah scoring, wajib:**
1. Titik tengah tiap ramp = ambang lama (jaga kalibrasi).
2. Jalankan `tests/test_scoring_continuity.py` — gagal kalau ada lompatan
   >4 poin antar-langkah input.
3. Bandingkan distribusi grade lama vs baru di token sintetis. Patokan
   terakhir: PRIME ~1,7%→2,9%, flag high-risk **100% identik**.
- **Style screener bukan scoring.** `T10 ... too concentrated` dan kolom
  T10 mulai 25% memakai red glow; `Down >=90% dari ATH` memakai green
  glow melalui `trending_ui._format_note_part()`. Retrace ATH tetap
  display-only dan tidak boleh diam-diam menambah Fit. Jaga style lewat
  `tests/test_markup_ai_prompt.py` dan formula lewat
  `tests/test_scoring_continuity.py`.
- **Screener Insider/Bundler 15%.** `bndl`/`insd` <15% = hijau `#22c55e`,
  >=15% = merah `#ef4444`; note `insider/bundler pressure` glow hijau
  (<15%) atau merah (>=15%) via `max(insider_ratio, bundler_rate)`; link
  GMGN (`gmgn.ai`) dan DexScreener (`dexscreener.com`) kecil di cc[1];
  caption diperbarui.

## 6. Markup safety + Prompt to AI

- Risiko markup dihitung oleh `cvd.markup_from_candles()` dari **low harian
  terendah dalam 30 candle terakhir**. Warning = +150%; danger = +300%.
- Banner merah danger di `app.py` wajib menyapu **seluruh watchlist sebelum
  filter `grow1` LP Radar**. Jangan pindahkan ke dalam loop card; conviction
  datar justru kasus yang tidak punya card.
- `ai_prompt.build_ai_prompt()` wajib tetap network-free. Glosarium (whale
  ≥3 SOL, pure toleransi 5%, definisi conviction) harus tampil sebelum angka.
- Kalau window diminta lebih panjang dari data tersedia, prompt wajib bilang
  data tidak penuh dan **melarang AI menyimpulkan tren**. Tabel waktu harus
  lama → baru dan tabel dompet harus membawa umur 🐣/🌱/🌳.
- Tombol Prompt to AI memakai dropdown Time window yang sudah ada. Jangan
  membuat pemilih window kedua.
- Nested CVD window tidak boleh melebihi window yang di-fetch
  (`cvd.analysis_windows`). Semua perhitungan rerun harus tetap di-anchor ke
  `fetched_at`; memakai `time.time()` akan membuat data stale tampak makin
  lengkap.
- Periode prompt yang belum tercakup wajib diberi label `TIDAK TERCAKUP` atau
  `SEBAGIAN`, bukan ditampilkan sebagai flow nol tanpa penjelasan.

## 7. Cara kerja & jebakan

```bash
python tests/test_breakout_guard.py       # 67 assertion
python tests/test_scoring_continuity.py
python tests/test_markup_ai_prompt.py
python tests/test_flow_safety.py          # LP Radar 4-window + flow checks + GMGN new penalties
python tests/test_helius_rotation.py       # key merge/de-dup + 429 failover
python tests/test_cvd_update.py            # stale backfill persistence/status
python tests/test_real_dust_history.py     # hourly real/dust history record/trend
```

Tanpa pytest, tanpa jaringan. **Tes wajib mem-patch semua path file**
(`LOG_PATH`, `LEVELS_PATH`, `signals.SIGNALS_PATH`) ke tmpdir — pernah
bocor menulis ke `signals.json` asli.

Jebakan yang sudah pernah menggigit:

- **Runner Actions ephemeral.** File yang tidak di-commit hilang tiap run.
  Karena itu `breakouts.json` ada di `git add` workflow — tanpa itu
  `reclaim`/`failed_breakout` tidak akan pernah terdeteksi.
- **Agen tidak bisa mengubah `.github/workflows/`.** GitHub App tidak punya
  izin `workflows`; `git push`, Contents API, dan Git Data API semuanya 403.
  Kalau perlu ubah workflow, **minta pemilik** melakukannya lewat web GitHub.
- **Field GMGN.** Payload `trending_rank` TIDAK punya `insider_ratio` /
  `bundler_rate`. Yang benar: `bdrr` `dhr` `etpr` `bdr` `t70_shr` `snp`.
  Lihat `docs/gmgn_api.md`. PR #5 tambah `fwr` (`fresh_wallet_rate`) dan
  `t50` (`top_50_holder_rate`) — kalau GMGN rename, `_first()` akan jatuh
  ke default 0.0 dan penalty tidak kena. Pantau di run berikutnya.
- **Toggle CVD GMGN Trades API.** `app.py` dan `pages/4_📊_CVD.py`
  punya checkbox `🔄 Use GMGN Trades API` (default OFF). OFF tetap Helius;
  ON wajib lewat `cvd.fetch_swaps(..., use_gmgn=True)` ke
  `https://gmgn.ai/vas/api/v1/token_trades/sol/{ca}`. Mapping ada di
  `cvd.gmgn_trade_to_swap`: `event` → buy/sell,
  `quote_amount`/`amount_usd` → SOL-equivalent, `timestamp` → ts,
  `maker` → wallet. Jangan balik ke helper lama `gmgn_screener` yang
  memakai estimasi SOL fixed; error GMGN harus tampil via
  `cvd.get_gmgn_last_error()` dan tidak boleh crash.
- **Helius key pool hanya di `core.py`.** Semua RPC/Enhanced API wajib lewat
  `get_helius_keys()` + `helius_rpc()`/`helius_api_get()`. Jangan kembali
  membuat endpoint `?api-key=...` langsung di app/page/cron; itu akan
  melewati `helius_extra_keys` dan failover 429/5xx.
- **Manual stale backfill harus melaporkan hasil nyata.** Di `app.py`, CA
  baru boleh masuk `stale_watchlist_cas` setelah `record_conviction()`
  menghasilkan point. Jangan menghitung panjang `_to_refresh` sebagai jumlah
  sukses: pool kosong, window tanpa swap, fetch/save exception harus tetap
  gagal dan bisa dicoba lagi. Backfill CVD default memakai **GMGN**, jadi
  tidak boleh diblokir karena Helius key/pool DexScreener kosong; wajib cek
  `update_token_cvd(..., use_gmgn=True)` mengembalikan `fetch_ok` sebelum
  merekam conviction. Jika pagination GMGN partial/error, cursor/bucket lama
  harus dipertahankan dan cron/manual **tidak boleh** membuat timestamp
  conviction baru. Status stale juga wajib memakai `flow_freshness()` saja,
  bukan `health_badge()` (quality/distribution advisory bukan data stale).
  Raw-swap prune di `cvd.update_token_cvd()` memakai key comprehension
  (`key[2]`), bukan nama argumen lambda yang hanya hidup di dalam lambda.
  Jaga lewat `tests/test_cvd_update.py` + `tests/test_fetch_reliability.py`.
- **Jangan commit `config.json`** (berisi API key, sudah di `.gitignore`).
- **LP Radar 48h butuh ≥8 cron point (≥2 hari).** Sebelum itu, sparkline
  baris ke-4 mirror 24h supaya tidak misleading ke 0%. Konvensi ini di-
  encode di `app.py` — jangan disederhanakan.
- **CVD flow checks** (`cvd.flow_freshness`/`persistence`/`distribution`/
  `quality`) adalah *advisory*, bukan blocker. Mereka tidak masuk ke
  scoring; hanya menampilkan badge di panel. Kalau mau dipakai sebagai
  gate, tambahkan test dulu, jangan diubah diam-diam.
- **Freshness 3-level** — `flow_freshness()` mengembalikan `level`
  `ok`/`warn`/`danger` dengan ambang `FRESH_MAX_AGE_S=2.5h` dan
  `STALE_MAX_AGE_S=12h` (lihat konstanta di `cvd.py`). Konstanta ini
  *digunakan* oleh `app.py` Freshness sweep, dan kalau diubah
  perilakunya langsung bergeser. Test di
  `tests/test_flow_safety.py::test_flow_freshness` wajib tetap
  hijau — kalau naik/turun band, update test bersamaan.
- **`streamlit` WAJIB dipin di `requirements.txt`.** Starlette 0.41+
  menambahkan argumen **keyword-only** `thread_minimum_size` ke
  `GZipResponder.__init__()`. Streamlit lawas memanggilnya TANPA
  argumen itu dan crash dengan
  `TypeError: GZipResponder.__init__() missing 1 required
  keyword-only argument: 'thread_minimum_size'` di
  `streamlit/web/server/starlette/starlette_gzip_middleware.py:125`
  untuk **setiap** request. Floor `streamlit>=1.39` (rilis
  2024-10-31 sudah pass arg baru). JANGAN kembalikan ke `streamlit`
  tanpa pin — pip bisa menarik versi lama dan server crash lagi.
  Berlaku untuk Python 3.11/3.12/3.14 dan untuk Streamlit Cloud
  (rilis image lebih baru = starlette lebih baru = lebih rentan
  terhadap drift). Detail di `BUGFIX_SUMMARY.md` § Bug 0.

## 7.5 Perilaku baru yang wajib dijaga (2026-08-01)

- **Quick Pick one-shot (jangan di-rerun).** Blok Quick Pick di `app.py`
  TIDAK boleh `st.rerun()` setelah set `trigger_analyze` — dulu itu bikin
  loop rerun tanpa henti (selectbox masih terpilih → flag diset lagi).
  Sekarang selectbox di-reset ke placeholder dan run yang sama yang
  meneruskan analisis. Kalau mengubah blok ini, jangan kembalikan
  `st.rerun()` di sana.
- **`detect_phase()` memakai rata-rata conviction 4-48 jam**, bukan titik
  4 jam terakhir: `cv = cvd.conviction_avg(pts)` dipakai untuk SEMUA
  ambang phase (Markdown <30, Accumulation-Late ≥50, dll) dan semua pesan
  `reason` menampilkan `avg conviction X% (4-48h)`. Momentum pendek
  (naik/turun) tetap dari 2 titik terakhir. Jangan mengembalikan
  `cv = pts[-1]["conviction"]` tanpa sadar — owner butuh angka yang bisa
  dibandingkan dengan analisa CVD 48h.
- **Pola candle body kecil di card LP & DEGEN.** `cvd.candle_pattern_summary(candles)`
  mengembalikan `{counts, low, high, n}` (pola + RANGE harga pola).
  Klasifikasi tunggal di `cvd._classify_small_body()`. Di card, H1 48h
  diambil dari cache candle watchlist yang SUDAH ada
  (`_daily_candles` = `fetch_watchlist_daily_candles`), H4 dibuat dari
  H1 lewat `cvd.aggregate_candles(candles, 4)` (buang grup parsial) —
  jadi TIDAK ada fetch GeckoTerminal tambahan per card. H4 dan H1
  ditampilkan TERPISAH dengan range-nya masing-masing.
- **Real holder vs dust di card LP & DEGEN.** `fetch_real_dust_ratio()`
  di `app.py` memakai `fetch_holder_data()` (satu fetch Helius per CA,
  di-share dengan holder-delta panel — jangan fetch 2×). Threshold dari
  sidebar `dust_limit_usd` (default $5). Card menampilkan
  `💎 Real ≥$5: N · 🪙 Dust: M · ratio R%` (hijau jika tidak ada dust
  atau real ≥ 50% dari dust, merah di bawahnya).
- **% dari ATH.** `gmgn_screener.screen()` (trending) sekarang mengisi
  `row["down_ath"]` dan note `Down X% dari ATH` seperti HRHR. Kolom
  **ATH** ada di tabel screener (`trending_ui.COLUMNS`); deep retrace
  ≥90% glow hijau (display-only). Saat ⭐ watch dari screener,
  `add_to_watchlist(..., down_ath=...)` menyimpannya di watchlist meta;
  card LP/DEGEN menampilkannya via `app._ath_html()` (fallback: session
  screener rows). Jangan jadikan `down_ath` bagian scoring.
- **Tulisan `T10` diganti `Top 10`** di notes screener, kolom tabel,
  wins, dan risk reasons. Regex glow di `trending_ui._format_note_part`
  tetap menerima `T10` lama (catatan tersimpan) DAN `Top 10` baru.

## 7.55 Perilaku baru yang wajib dijaga (2026-08-02)

- **History real vs dust holder dicatat cron 1 jam** →
  `real_dust_history.json`, recorder `cvd.record_real_dust_point()`
  dipanggil di `scripts/update_cvd.py::_try_snapshot()` **hanya di
  jalur Helius** (list holder lengkap, sudah di-fetch untuk snapshot —
  nol RPC tambahan). JANGAN pernah mencatat dari fallback GMGN
  (top-10 holder): real/dust dari top-10 selalu klaim "0 dust" — bohong.
  Dedup `REAL_DUST_MIN_GAP_S=45m` (retry cron tidak dobel), retensi
  `REAL_DUST_KEEP_DAYS=30`, hard cap `REAL_DUST_MAX_POINTS=744`.
  Threshold dari `dust_limit_usd` config (sama dengan card live).
  Workflow patch untuk owner: `docs/WORKFLOW_PATCH_real_dust.md`
  (tanpa itu file tidak ter-commit dan grafik kosong di Cloud).
- **Card pertumbuhan menyambung di bawah blok real/dust**:
  `app._real_dust_growth_html()` — headline 📈 NAIK / 📉 TURUN /
  ➡️ DATAR (arah = Δ real holder vs titik cron sebelumnya), chip
  Δ 1/6/24 jam (💎 real + 🪙 dust), sparkline SVG 48 titik terakhir
  (hijau = real, oranye = dust, **skala masing-masing** — diberi label
  jelas supaya tidak menyesatkan). Anchor window memakai
  `cvd._nearest_older_point()` = konvensi yang sama dengan
  `holder_delta` (titik terbaru ≤ tepi window); lewat gap cron, anchor
  jatuh ke titik terlama yang tersedia — jangan dikembalikan None.
  Dijaga `tests/test_real_dust_history.py`.
- **Tombol 🗑️ Hapus dipin ke dasar card.** Card LP & Degen sekarang
  `display:flex;flex-direction:column` dengan spacer
  `<div style='flex:1 1 auto;'>` sebelum baris tombol → tombol selalu
  di posisi vertikal yang sama di semua card (parent row sudah
  `align-items:stretch`). Jangan kembalikan `margin-top:10px` murni
  tanpa spacer — itu yang bikin tombol dulu pindah-pindah.

## 7.57 Perilaku baru yang wajib dijaga (2026-08-03 — CTO radar GMGN authority)

- **GMGN = satu-satunya sumber market data untuk CTO Incubation Radar.**
  GMGN menghitung transaksi lintas semua pool; DexScreener membaca satu
  pair saja (kasus MEMIPEDE: vol24 GMGN ~$70k vs Dex ~$45k → Stage 1 vs
  Stage 2 sempat beda angka). `cto_deep_scan.deep_scan_token()` sekarang
  berhenti memakai `core.get_market()` / `history.json` untuk gate
  MC/liquidity/volume/vol-MC/holders/T10 — Dex hanya untuk metadata
  (symbol/url), CTO claim detection (halaman DexScreener), dan
  divergence logging.
- **Row GMGN diteruskan utuh dari Stage 1 ke Stage 2** via
  `deep_scan_token(ca, relaxed=False, do_cluster=False, helius_keys=None,
  gmgn_row=row)`; `cto_deep_scan.market_from_gmgn_row()` membangun snapshot
  ber-tag `market_source = "gmgn"` (marketcap←`mc`, liquidity_usd←`liq`,
  volume.h24←`vol24`, t10/holders/risk fields ikut). Row bertanda
  `_source != gmgn` (mis. demo watchlist dari history di page 7) DITOLAK
  supaya tidak pernah salah label authoritative.
- **Fail closed.** Tanpa snapshot GMGN (row tidak ada & live fetch
  `fetch_gmgn_market_row()` gagal), `pass=False` dengan reason
  `GMGN market snapshot unavailable — fail closed`. Jangan
  mengembalikan fallback Dex/history untuk market gates; checks lain
  (Helius holders, CTO, conviction) tetap jalan untuk display.
- **T10 gate memakai row GMGN dulu**, baru konsentrasi on-chain Helius,
  baru token_stat mentah — supaya angka Stage 1 dan Stage 2 selalu sama.
- **Divergence logging.** `_divergence_notes()` membandingkan GMGN vs Dex
  (toleransi max($1500, 10%)); setiap selisih dicatat di
  `result["market_divergence"]`/`market_notes`, di-print CLI, dan
  ditampilkan di page 7 ("GMGN authoritative").
- **Tombol Deep Scan di page 7 langsung menjalankan scan** (bukan set
  state + `st.rerun()` yang bikin tampak tidak terjadi apa-apa karena tab
  kembali ke Stage 1); row GMGN utuh disimpan di session state
  (`cto_deep_single_row`) dan dipakai ulang di tab Stage 2.
- **Untuk `--ca` / watchlist langsung**, snapshot GMGN di-fetch live
  (`token_stat` → normalisasi via `score_token`, + best-effort
  `token_prices` bila tidak ada MC). Gagal → fail closed seperti di atas.
- Dijaga `tests/test_gmgn_market_authority.py` (7 grup, termasuk mock
  MEMIPEDE $189k/$70k → candidate, vol24 $99.064 → FAIL `vol24 > 90000`,
  Dex $45k monkeypatched tidak menimpa GMGN $70k, dan cek signature
  `screen_incubation(relaxed=False, debug=False)`).

## 7.56 Perilaku baru yang wajib dijaga (2026-08-03)

- **Rangkuman TX real di card LP & Degen** — `app._real_tx_summary_html()`
  dirender TEPAT di bawah blok `💎 Real ≥$5 vs 🪙 Dust` (sebelum card
  pertumbuhan). Isi: 4 chip window **6/12/24/48 jam**, masing-masing
  jumlah swap senilai ≥ `dust_limit_usd` (SOL × harga SOL) dan net
  SOL-nya (beli − jual; ▲ hijau / ▼ merah). **Definisi "real TX" =
  swap bernilai ≥ ambang real/dust** (keputusan owner, bukan profil
  wallet dan bukan join list holder).
- **Nol RPC tambahan.** Sumber = raw-swap store 48 jam yang SUDAH ada
  (`cvd.get_recent_swaps`) — jangan ganti ke fetch live Helius/GMGN.
  Harga SOL dari `cvd.get_sol_price()` (cache 10 menit) dihitung
  SEKALI per page load (`_sol_price`) dan dipakai kedua radar. Per CA
  di-cache 5 menit via `st.cache_data` (`fetch_real_tx_summary`).
- **Komputasi murni di `cvd.real_tx_summary()`** — pure function,
  deterministik dengan `now_ts`, batas inklusif (swap tepat di ambang =
  real), sol NaN/rusak di-skip, `covered_h` membedakan token sepi vs
  store kosong. Store kosong → blok disembunyikan, JANGAN render nol
  palsu. Dijaga `tests/test_real_tx_summary.py`.
- **Catatan untuk owner:** di ambang default $5, hampir semua swap store
  (≥ `MIN_SOL` 0.05 SOL) masuk real → naikkan `dust_limit_usd` di
  sidebar untuk pisahan yang lebih tajam (sudah dijelaskan di caption
  kedua radar).

## 7.6 Perilaku baru yang wajib dijaga (2026-08-01 — batch 2)

- **Routing card LP vs Degen bergantung field `source` di watchlist meta.**
  JANGAN buang `source`/`down_ath` saat replay journal:
  `watchlist._apply_ops()` wajib menyalin SEMUA field op
  (`symbol`/`note`/`added`/`source`/`down_ath`), dan
  `add_to_watchlist()` memaksa source dari add terbaru
  (latest-add-wins). Kalau tidak, token HRHR jatuh ke 💧 LP Radar.
- **Semua write JSON state wajib atomic via `core.atomic_write_json()`.**
  Helper baru (mkstemp di dir sama + fsync + `os.replace`). Kalau
  menambah file state JSON baru, jangan `open(path,"w")+json.dump`
  langsung. Write yang gagal harus ter-log (`WARN ... file=sys.stderr`),
  kecuali fetch/parsing eksternal yang memang sengaja `except: pass`.
- **Tombol "🔄 Force refresh now" DIKEMBALIKAN.** Auto-refresh otomatis yang dulu membackfill token secara paksa saat pertama kali ditambahkan telah dihapus, dan sekarang menggunakan manual button kembali dengan bar progress sync dan estimasi waktu selesai. Tombol muncul saat ada token yang stale atau baru ditambah.
- **`detect_clusters()` paralel — jangan kembalikan loop sekuensial.**
  Wallet belum ter-cache di-submit ke `ThreadPoolExecutor`
  (`workers = min(8, n)`); dict `disk` hanya diupdate di MAIN thread via
  `as_completed`; `save_funder_cache` cukup SEKALI di akhir; pass
  terakhir tetap urutan wallet asli (hasil `groups`/`cdf`/`info`
  deterministik). `time.sleep(0.1)` lama dihapus — rotasi key di
  `core._helius_candidates` sudah thread-safe.
- **Snapshot harian menyimpan `name`** (nama lengkap token) di
  `history.json`. Pembaca history wajib pakai `.get("name")` dengan
  fallback — snapshot lama tidak punya field ini.
- **Stat `avg_cost` GMGN (display-only) di screener + card.** `screen()`
  (trending) menyimpan `row["avg_cost"]` seperti `screen_hrhr`; tabel
  screener punya kolom **AvgCost** (merah ≤ -50%, oranye <0%, hijau ≥0%);
  card LP/Degen Radar menampilkan `💰 avg cost` via `app._avg_cost_html()`
  dengan fallback session screener rows. `add_to_watchlist(..., avg_cost=)`
  menyimpannya di watchlist meta dan `_apply_ops` wajib ikut menyalinnya.

## 7.58 Perilaku baru yang wajib dijaga (2026-08-04 — page 10 Accumulation History)

- **Page 10 (`pages/10_📈_Accumulation_History.py`) memindai SELURUH umur
  token**, bukan 48 jam terakhir seperti page 9. Alasan: verdict page 9
  flip-flop untuk token tua karena window 48 jam bergeser tiap jam dan
  fase 1–3 dirancang untuk periode launch. Kasus nyata test case: MEMIPEDE
  `6LLNiWXRZp8hn5oTFTHEo8ERbJS3QJfHSKhnTCqipump` — spike hourly ~$16.6K
  30 Jul 2026 16:00 UTC (31 Jul 00:00 WIB); akumulasi terdeteksi page 10
  pada rentang ~29 Jul – 31 Jul 2026 WIB, di luar jangkauan page 9.
- **Semua logika skoring/scanning/merging ada di modul murni
  `accum_history.py`** (tanpa Streamlit, tanpa network di jalur scoring) —
  definisi & threshold 5 fase SAMA PERSIS dengan page 9
  (`score_phase1..5`, `score_window`, `recommendation`). Jangan melonggarkan
  threshold; kalau page 9 berubah, samakan di sini (dijaga
  `tests/test_accum_history.py`).
- **Candle-first, verifikasi wallet hanya untuk kandidat.** Rolling scan
  window 48 jam (step 3–12 jam, default 6) murni dari candle
  (`rolling_scan`); kandidat = pre-score ≥ 40 DAN ada sinyal nyata
  (p2-proxy ≥ 5 ATAU p4-est ≥ 10) supaya poin thin-liquidity saja tidak
  membentuk kandidat. Hanya kandidat (maks 8) yang di-fetch swap GMGN
  (`cvd.fetch_swaps(..., use_gmgn=True, from_ts=..., to_ts=...)`,
  `max_pages` dibatasi) lalu diskor penuh ala page 9.
- **Paginasi candle penuh via `before_timestamp`** (GeckoTerminal, limit
  max 1000/request) ada di `accum_history.fetch_candles_full` — jangan
  ganti ke `cvd.fetch_candles` untuk full history (tidak punya
  `before_timestamp`). `page_fetcher` injectable supaya bisa di-test
  offline.
- **Liq/FDV historis = ESTIMASI** (`estimate_liq_fdv`): nilai kini × rasio
  median close window vs harga sekarang; selalu ditandai `~`/`estimasi` di
  UI, dan confidence turun ke LOW kalau GMGN parsial/gagal — jangan pernah
  tampil sebagai angka pasti.
- **Merge window berdekatan** (gap ≤ 12 jam) jadi rentang `[mulai, selesai]`:
  skor = maksimum, fase hit = gabungan, `n_windows` dicatat. Diuji
  `test_merge_adjacent_and_far`.
- **UI bahasa Indonesia, timestamp WIB (Asia/Jakarta)** lewat `fmt_wib` di
  page (bukan `strftime` lokal). Wajib ada: tabel rentang (urut skor),
  chart full-periode dengan highlight vrect, panel perbandingan verdict 48
  jam terakhir ala page 9, empty state jelas (pair terlalu baru / tidak ada
  kandidat / GMGN gagal — jangan crash).
- **`fetch_swaps` GMGN**: gunakan `get_gmgn_fetch_status()` untuk
  `ok`/`complete`/`error` per window; kalau `complete=False` karena cap
  halaman, confidence LOW + note "data GMGN parsial".

## 7.59 Token identity DexScreener — CVD tidak boleh salah nama (2026-08-05)

- Endpoint `GET /latest/dex/tokens/<CA>` dapat mengembalikan cross-pair
  berlikuiditas tinggi ketika CA yang diminta berada di `quoteToken`.
  **Jangan pernah** mengambil `pairs[0]` lalu membaca `baseToken` tanpa
  memeriksa address — kasus nyata CA MEMIPEDE
  `6LLNiWXRZp8hn5oTFTHEo8ERbJS3QJfHSKhnTCqipump` sempat tampil sebagai
  `Cyclospora`.
- Satu-satunya selector kanonik adalah
  `core.matching_dexscreener_pairs()` / `select_dexscreener_pair()`:
  match address harus persis (case-sensitive), pair target sebagai base
  diprioritaskan dan diurutkan berdasarkan likuiditas, lalu quote-side
  fallback. Ambil nama/simbol lewat `core.dexscreener_pair_token()`, bukan
  selalu `baseToken`.
- `core.get_market()` adalah jalur yang dipakai page CVD; `get_pool()` di
  `pages/4_📊_CVD.py` wajib tetap mendelegasikan ke sana. Cron CVD,
  snapshot harian, quick-pick/watchlist pricing, konteks ATH, pola candle,
  CLI, dan memecoin scanner juga memakai selector ini agar identitas tidak
  bergeser di layar atau data terjadwal.
- Regression: `tests/test_dexscreener_identity.py` memakai fixture
  cross-pair `Cyclospora / MEMIPEDE` yang likuiditasnya lebih besar dari
  pair MEMIPEDE/SOL. Ekspektasi: CVD memilih pair MEMIPEDE/SOL serta nama,
  simbol, dan harga MEMIPEDE; pair yang tidak mengandung CA ditolak.

## 8. Status & langkah berikutnya

Per 2026-07-31, seluruh sistem telah difokuskan murni menggunakan **GMGN Token Trades API** secara default (`use_gmgn_trades = True`) untuk semua penarikan data transaksi on-chain. Cron holder snapshot harian dari Helius (`_try_snapshot`) telah dinonaktifkan sementara.

Beberapa pembaruan penting lainnya meliputi:
- **Watchlist Quick Pick & Auto Analyze**: Memilih koin di Quick Pick akan langsung melakukan Analyze dan menjalankan CVD analisis untuk window 48h secara otomatis (tanpa tombol "Gunakan").
- **Dolphin Cohort**: Menambahkan kategori Dolphin (`1.0 <= buy < 3.0 SOL`) di tabel akumulator dan distributor halaman utama dan halaman CVD, termasuk dolphin metrics row dan kolom dolphin di multi-window table CVD.
- **LP Radar & Degen Radar Split**: LP Radar hanya menampilkan token dari watchlist dengan source "trending" (dari GMGN trending screener). Token dari HRHR screener ditampilkan di card baru "⚡ Degen Radar" dengan border oranye. Source tracking ditambahkan ke `watchlist.py` (`add_to_watchlist(ca, source="trending"|"hrhr"|"manual")`).
- **Screener "High Risk High Reward" — FOR DEGEN**: Label diubah dari "FOR LP" menjadi "FOR DEGEN" untuk menegaskan bahwa token ini berisiko tinggi dan untuk degen trader.
- **Simplifikasi LP Radar**: Menghapus seluruh noise flags, borders menyala/glow, serta badge status (`KOKOH`, `NOISY`). Menampilkan momentum conviction dalam visualisasi grafik batang hijau (naik) / merah (turun) yang bersih, beserta catatan momentum akumulasi dan volume.
- **Watchlist Ticker Bar Dinonaktifkan**: Ticker bar (chips harga scrollable) di atas LP Radar telah dinonaktifkan. Safety sweep dan freshness sweep tetap berjalan.
- **Holder Warning Disederhanakan**: Banner merah "UNHEALTHY HOLDER BASE" yang mengkhawatirkan diganti dengan peringatan kuning yang lebih informatif dan tenang.
- **Watchlist Quick Delete — sekarang di card**: Tombol 🗑️ kecil disematkan langsung di header setiap card LP Radar & Degen Radar (di sebelah shortcut DexS/GMGN). Klik → navigasi ke `?del_ca=<ca>` → token dihapus dari watchlist lalu page di-rerun. Expander "Quick Delete" lama (daftar terpisah) sudah dihapus supaya tidak ada dua tempat hapus; token tanpa card (belum punya conviction) tetap bisa dihapus lewat tombol "💔 Remove from watchlist" saat dianalisa atau di halaman ⭐ Watchlist.
- **Data Integrity**: Penyimpanan file data (`cvd.json` & `conviction.json`) diubah murni atomik via `tempfile` + `os.replace` untuk menghindari korupsi file jika crash. Swaps raw juga secara otomatis dideduplikasi dan diurutkan secara kronologis saat pembaruan untuk menghindari inflasi volume yang tidak masuk akal.
- **Scoring & Checklist**: LP locked dihapus dari bobot skor kesehatan (karena token pumpfun sudah otomatis terkunci), melainkan diganti tanda bahaya keras jika LP terdeteksi 0% (tidak dikunci sama sekali). Batas dust default disesuaikan menjadi $5.
- **CVD Deep Focus**: Menghadirkan tabel analisis kepemilikan dan retensi pembeli murni dari timeframe terpilih saja, disaring dari dust (<$5), bots, dan churn.
- **CVD Cohort Details v2**: Halaman `pages/4_📊_CVD.py` sekarang menampilkan row metrik whale held-buy/sell/net berdampingan dengan dolphin, memecah list menjadi whale pure accumulator/distributor, dolphin pure accumulator/distributor, light holder, dan trader. Helper network-free ada di `cvd.split_wallet_profile_cohorts()`, `cvd.cohort_activity_summary()`, `cvd.cohort_cvd_series()`, `cvd.detect_cohort_divergences()`, dan `cvd.detect_no_buy_holders()`; dijaga oleh `tests/test_wallet_profiles.py`. Ada juga section no-buy holders: holder-rank whale/dolphin dari scan Helius current holders yang tidak buy di window, plus sell-only wallet GMGN yang masih punya balance. Advanced cohort divergence bersifat advisory: price vs Whale Held CVD / Dolphin Held CVD / Trader CVD / Pure Distributor CVD dengan filter minimum SOL, tidak mengganti All CVD + Whale-swap divergence lama. Ingat: light_holder/trader secara definisi harus punya buy di window, jadi kasus no-buy masuk section no-buy holders.
- **Bug Fix — hist_df NameError**: `hist_df` yang dulu hanya didefinisikan di dalam `if False:` block sekarang dipindahkan keluar sehingga Divergence Check dan session state save tidak crash.
- **Bug Fix — GMGN Screener Random Fallback**: Fallback value di `_get_avg_cost_and_ath()` yang menggunakan `random` diubah menjadi deterministik supaya token yang sama selalu mendapat skor yang sama.

Lihat `docs/PROGRESS.md` untuk riwayat keputusan detail dan daftar perubahan lengkap.
