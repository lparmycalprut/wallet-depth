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

## 2. Peta file

| File | Isi |
|---|---|
| `app.py` | dashboard utama (besar, ~110KB) |
| `pages/` | halaman Streamlit tambahan |
| `core.py` | helper Helius (shared multi-key pool)/DexScreener/GeckoTerminal |
| `cvd.py` | store swap, bucket CVD, profil wallet, **level D1**, **flow attribution**, **flow safety checks** (freshness / persistence / distribution / quality) |
| `gmgn_screener.py` | screener GMGN + **scoring ramp kontinu** + **fresh-wallet & top-50 concentration penalties** |
| `ai_prompt.py` | builder prompt CVD siap-salin, jujur soal cakupan data |
| `breakout_guard.py` | **Breakout Guard**: level D1 + konfirmasi close H4 |
| `breakout_log.py` | log event level → `breakouts.json` |
| `signals.py` | log sinyal CVD → `signals.json` + notif Telegram |
| `watchlist.py` | watchlist helpers (load/save/add/remove + GitHub commit) |
| `scripts/update_cvd.py` | entry point cron (tiap jam, menit :20) |
| `tests/` | 9 suite, **jalan tanpa pytest & tanpa jaringan** |

**File data yang di-commit cron** (jangan di-`.gitignore`):
`cvd.json` · `signals.json` · `conviction.json` · `levels.json` ·
`breakouts.json` · **`holder_snapshots.json`** (whale/dolphin holdings
delta baseline; 4h cron commit per CA per ~6h bucket)

## 3. Dua jenis notifikasi Telegram — JANGAN tertukar

Keduanya lewat `send_telegram()` di `breakout_guard.py`, tapi beda sumber
dan beda caption. Caption itu wajib ada supaya pembaca tahu yang mana.

| Caption | Modul | Dasar | Dedupe |
|---|---|---|---|
| 📊 **CVD MONITOR** | `signals.py` | flow 6 jam + divergensi H1 | 4 jam per `(ca, tipe)` |
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
  6 jam). Commit tiap cron run via `cvd.record_holder_snapshot()`;
  `SNAPSHOT_MIN_GAP_S = 6*3600` jadi 4h cron commit setiap run kedua.
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
  gagal dan bisa dicoba lagi. Raw-swap prune di `cvd.update_token_cvd()`
  memakai key comprehension (`key[2]`), bukan nama argumen lambda yang hanya
  hidup di dalam lambda. Jaga lewat `tests/test_cvd_update.py`.
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
- **Watchlist Quick Delete**: Tombol "Hapus" langsung disematkan di dashboard halaman utama sehingga pengguna dapat memotong token tanpa harus berpindah ke halaman watchlist.
- **Data Integrity**: Penyimpanan file data (`cvd.json` & `conviction.json`) diubah murni atomik via `tempfile` + `os.replace` untuk menghindari korupsi file jika crash. Swaps raw juga secara otomatis dideduplikasi dan diurutkan secara kronologis saat pembaruan untuk menghindari inflasi volume yang tidak masuk akal.
- **Scoring & Checklist**: LP locked dihapus dari bobot skor kesehatan (karena token pumpfun sudah otomatis terkunci), melainkan diganti tanda bahaya keras jika LP terdeteksi 0% (tidak dikunci sama sekali). Batas dust default disesuaikan menjadi $5.
- **CVD Deep Focus**: Menghadirkan tabel analisis kepemilikan dan retensi pembeli murni dari timeframe terpilih saja, disaring dari dust (<$5), bots, dan churn.
- **Bug Fix — hist_df NameError**: `hist_df` yang dulu hanya didefinisikan di dalam `if False:` block sekarang dipindahkan keluar sehingga Divergence Check dan session state save tidak crash.
- **Bug Fix — GMGN Screener Random Fallback**: Fallback value di `_get_avg_cost_and_ath()` yang menggunakan `random` diubah menjadi deterministik supaya token yang sama selalu mendapat skor yang sama.

Lihat `docs/PROGRESS.md` untuk riwayat keputusan detail dan daftar perubahan lengkap.
