# Kegiatan — 4 September 2026

Tiga permintaan user: (1) halaman baru **Deteksi Akumulasi** dengan 8 metrik,
(2) koreksi metrik 4 supaya **GMGN saja** (kuota Helius terlalu boros),
(3) detail baru di baris watchlist — perubahan dust sejak masuk + warna ambang
— dan perbaikan sinkronisasi data watchlist ↔ scan terakhir.

## 1. Halaman `pages/6_🔎_Deteksi_Akumulasi.py` + modul `accumulation.py`

Semua logika masuk modul **baru** `accumulation.py` (murni kalkulasi, tanpa
Streamlit, **tanpa satu pun request jaringan**); halaman hanya menarik bahan
mentah lewat fetcher yang sudah ada dan merender hasilnya. Sumber daftar token
**selalu** `watchlist.load_watchlist()` — bukan listing Meteora/trending, dan
tidak ada file watchlist baru.

| # | Metrik | Bahan mentah (fetcher lama, reuse) |
|---|---|---|
| 1 | Tier Migration Velocity | bucket wallet depth dua titik `holder_history` terakhir |
| 2 | Diamond Hands Ratio | posisi net per wallet dari swap GMGN |
| 3 | Pola DCA vs One-off Buy | jumlah buy unik + dominasi satu buy per wallet |
| 4 | Smart Money / PnL Wallet | **GMGN**: `maker_tags` + `realized_profit` |
| 5 | Silent Range Accumulation | `core.get_market` + `calculate_volatility_metrics` + CVD net swap |
| 6 | Spring / Test Pattern | candle 4 jam (agregasi dari `core.get_hourly_candles`) vs level support D1 |
| 7 | Fresh Wallet Prep | tag `fresh_wallet` GMGN + pola waktu buy |
| 8 | Sell-Side Liquidity Thinning | posisi net per wallet tanpa jual 14 hari |

Setiap fungsi mengembalikan `{key, nama, nilai, nilai_text, status,
status_label, penjelasan, cukup_data, bobot, detail, sumber}`. `cukup_data`
False **selalu** dipaksa ke status `tidak_cukup_data` dan tidak ikut pembagi
skor (pola `available` di `calculate_volatility_metrics`): "tidak tahu" tidak
pernah dihitung "netral". Skor 0–100 ≥ 60 → **Terindikasi Akumulasi**, selain
itu **Netral**, tanpa data → **Tidak Cukup Data**.

**Koreksi user (metrik 4)** — riwayat PnL lintas token lewat Helius Enhanced
API **tidak diimplementasikan**: terlalu boros kuota Helius. Yang dipakai
metadata per-wallet yang sudah diparsing `cvd._extract_gmgn_trade_meta`
(`realized_profit`, `unrealized_profit`, `maker_tags` ∩
`cvd_daily.SMART_MONEY_TAGS`). Konsekuensinya ditulis jujur di `penjelasan`
dan `detail["catatan"]`: angka PnL = realized profit wallet itu **pada token
ini** menurut GMGN, bukan rekam jejak lintas token. Seluruh halaman ini
**tidak** memanggil Helius sama sekali (dijaga tes
`tests/test_accumulation_page.py::test_helius_is_never_touched`).

**Adaptasi karena modul yang disebut spec tidak ada di repo ini** (dicek:
tidak ada `signals.py`, `breakout_guard.py`, `breakout_log.py`, `ai_prompt.py`,
`levels.json`, `history.json`, `conviction.json`, `cvd.json`, `breakouts.json`,
juga tidak ada test `test_breakout_guard.py` / `test_scoring_continuity.py` /
`test_markup_ai_prompt.py`):

- metrik 1 memakai `points[].buckets` dari `holder_history.json` (label
  `>$0-$10` … `>$500k`; repo ini tidak punya boundary $1M),
- metrik 6 menurunkan level support D1 sendiri
  (`accumulation.derive_support_level` dari candle harian
  `core.get_daily_candles`) karena `levels.json` tidak ada,
- metrik 7 memakai tag `fresh_wallet` GMGN: **identitas funder tidak tersedia**
  tanpa scan Helius, jadi yang diukur pola "wallet baru beli bertahap tanpa
  jual", dan disclaimer itu ditulis eksplisit di penjelasan metrik.

State baru disimpan di file **terpisah** `accumulation_history.json` (skema
`wallet-depth-accumulation-v1`, git-ignored) — hanya skor/status + proporsi
thinning per run, dipakai metrik 8 untuk menunjukkan arah (delta pp) dari waktu
ke waktu. Format `watchlist.json`, `holder_history.json`, `holder_status.json`
tidak diubah.

## 2. Baris watchlist: kolom "Sejak masuk" + sinkronisasi (modul `watchlist_detail.py`)

1. **Delta sejak masuk** — `dust_change_since_added()` membandingkan titik
   pertama **pada/setelah** tanggal `added` dengan **scan terakhir**: perubahan
   relatif %, poin persentase (satuan rule alert), dan perubahan jumlah wallet
   dust. Tooltip memuat semuanya + umur window; bila belum ada titik setelah
   tanggal masuk, pembandingnya titik pertama dan itu ditandai.
2. **Warna sesuai ambang user** — `tone_for_change()`: turun **≥ 50%** = hijau
   `#15803d`, naik **≥ 100%** = merah `#b91c1c`, di antaranya abu-abu; nilai
   awal 0% → "—" (perubahan relatif dari nol tidak bermakna).
3. **Sinkronisasi watchlist ↔ scan terakhir** — akar masalahnya sama dengan
   kasus "grafik 0,7% tapi kartu 1,16%" di permintaan ke-4: baris watchlist
   membaca snapshot `holder_status.json` (cron) sedangkan sparkline membaca
   `holder_history.json` yang sudah memuat titik scan manual/scan lebih baru,
   dan caption "Terakhir scan" memakai `status.updated_at` global. Perbaikan:
   `resolve_view()` memilih sumber **terbaru** per baris (menandai `drift` bila
   snapshot ≠ titik history > 0,01 pp, dan `stale` bila umur data > 2 jam),
   `previous_pct()` memilih pembanding badge yang benar (bucket sebelum nilai
   yang ditampilkan, bukan `sampled[-2]`), tiap baris kini menulis
   `scan <waktu> · titik history · ⚠️ snapshot ≠ history · basi`, dan caption
   card diganti `sync_caption_text()` — satu waktu "Scan terakhir" + rincian
   berapa token memakai snapshot cron / titik history lebih baru / belum ada
   data / basi.
4. **Perubahan `app.py` dibatasi rendering**: impor `watchlist_detail`, hitung
   `view`/`change` sekali per token, tambah kolom **Sejak masuk** (7 → 8
   kolom), dan ganti caption. Tidak ada logika kalkulasi baru di `app.py`, dan
   `lp_watchlist.py` / `holder_status.py` / `holder_history.py` tidak disentuh.

## 3. Tes

`tests/test_accumulation.py` (59), `tests/test_watchlist_detail.py` (37),
`tests/test_watchlist_row_ui.py` (5, AppTest `app.py`),
`tests/test_accumulation_page.py` (6, AppTest halaman baru + guard "Helius
tidak tersentuh" + store snapshot di temp dir). Semua tanpa jaringan dan tanpa
pytest, mengikuti pola suite yang ada.

```
Ran 615 tests ... OK   (sebelumnya 508)
```

# Kegiatan — 3 September 2026

Dua permintaan user: ambang **HATI-HATI** untuk dust holder dan watchlist
terpisah **Chart LP** untuk token hasil Scan Meteora.

1. **Ambang dust jadi dua tingkat**: `≥ 0,5% MC = HATI-HATI` (badge kuning,
   peringatan dini) dan `≥ 1% MC = BAHAYA` (tetap disembunyikan dari Scan
   Meteora). `holder_history.dust_flag` mengembalikan level
   `ok`/`caution`/`danger`, helper baru `dust_level_rank`; badge di `app.py`
   + halaman Holder, dan grafik 4 jam kini punya garis ambang 0,5% & 1%.
   (Catatan: user sempat menulis 5%, lalu dikoreksi menjadi **0,5%**.)
2. **Card 🌊 Chart LP di paling atas dashboard**: watchlist terpisah berisi
   token `source=meteora`. Modul baru `lp_watchlist.py` menyiapkan baris
   data + figure: grafik perubahan dust holder per token (dust % MC + jumlah
   wallet dust + garis ambang), overlay semua token LP, Δ 4 jam & Δ total
   dalam poin persentase, sparkline, dan urutan BAHAYA → HATI-HATI → AMAN.
   Token LP tidak muncul lagi di watchlist holder bawah.
3. **Tambah manual ke card Meteora**: form ➕ Tambah token punya radio
   *Masuk ke card* (📋 Watchlist Holder / 🌊 Chart LP), card LP punya form
   CA sendiri, ⭐ di Scan Meteora menulis `source=meteora`, tombol 🌊/📋
   memindahkan token antar card lewat `watchlist.set_watchlist_source`
   (op journal baru `"source"`, aman terhadap push gagal / entri baru).

# Kegiatan — 1 September 2026

Fokus UI ke **analisa holder dust** (bukan silent 12 jam) + Scan Meteora.

1. Watchlist: buang Status/Net/Harga 12j, Real, Dust kolom lama, Scan,
   shortcut CVD. Ganti ringkasan dust (jumlah wallet + % MC), badge
   AMAN / HATI-HATI (≥1%) / DUMP (>2%), sparkline 4 jam, tombol 🧮 ke
   halaman Holder Analytic.
2. Trending/Degen: buang kolom Real/Dust/Dust%MC/12 Jam/Net 12j dan
   scan holder. Listing GMGN saja (Token, MC, 24h).
3. Halaman baru `pages/5_🧮_Holder.py` (di bawah CVD): dust, grafik 4
   jam, sisa token kohort Crab+Fish.
4. CVD: buang 🧮 Holder Analytic + kartu silent 12 jam.
5. `holder_history.py` + `holder_history.json`: catat dust/kohort tiap
   scan, resample 4 jam. Cron watchlist holder-only.
6. Scan Meteora di halaman utama: API 24h (fee_ratio≥250) + 1h (≥1),
   DLMM active_tvl≥1000. Pool 24h yang masih di 1h tetap tampil. Dust
   >2% MC disembunyikan. Shortcut Meteora DLMM + HawkFi.

# Kegiatan — 31 Agustus 2026 (lanjutan)

**Migrasi total sumber data ke Helius** (kecuali listing Trending/Degen
yang memang hanya ada di GMGN):

1. Fix bug konversi holder Helius: `amount` DAS adalah unit RAW → dibagi
   `10^decimals` mint (decimals dari DAS `getAsset`, fallback RPC
   `getTokenSupply`; per-item bila tersedia; abort bersih bila tidak
   ketemu). Sebelumnya nilai USD holder 10^decimals× lebih besar (tier
   Shark bernilai triliunan $).
2. `_fetch_holders_snapshot`: **Helius dulu, GMGN
   fallback**. `fetch_swaps` Enhanced API diprioritaskan juga di
   `scripts/update_cvd.py` (fetch harian CVD) dengan fallback GMGN.
3. **Solscan API dilepas total**: `solscan_holders.py` hanya tersisa
   kalkulasi `wallet_depth` (bucket/tier); `get_solscan_key` +
   `solscan_api_key` dihapus; nilai `holder_source=solscan` lama otomatis
   jatuh ke `auto` (= Helius). Opsi sumber kini `auto`/`helius`/`gmgn`.
4. Tier Helius sekarang mengecualikan LP/pool via `pair_addresses`
   DexScreener; legend/ikon UI menghilangkan 📡 Solscan.
5. Workflow `daily-effort.yml` **belum** bisa diubah via push (GitHub App
   tanpa permission `workflows`) — tambahkan manual env `HELIUS_API_KEY` /
   `HELIUS_API_KEYS` di step scan (lihat snippet di README); tanpa secret
   → otomatis fallback GMGN.

# Kegiatan — 31 Agustus 2026

Holder token watchlist diambil dari **Solscan**, plus **Wallet Depth by
Threshold** ala halaman analytics Solscan.

## Yang dikerjakan

1. `solscan_holders.py`: fetch holder Solscan — Pro API `v2.0/token/holders`
   bila `SOLSCAN_API_KEY` ada (tiap baris membawa `value` USD + `percentage`
   dari Solscan), fallback Public API `token/holders` (nilai USD =
   balance × harga app), lalu fallback GMGN/Helius. Normalisasi ke bentuk
   holder GMGN; LP/pool (dari `pair_addresses` DexScreener) ditandai bukan
   wallet.
2. `wallet_depth()`: **bucket** `>$0-$10` … `>$500k` atas semua akun
   (seperti chart Solscan) dan **tier** 🦐/🦀/🐟/🐬/🦈 atas wallet murni —
   count, total value, % marketcap per bucket/tier.
3. `silent_accumulation.analyze_token` punya `holder_source`
   (`gmgn`/`solscan`/`auto`, default config `holder_source` = `auto`):
   watchlist (cron & tombol scan lokal) Solscan dulu; listing
   Trending/Degen tetap GMGN. Saat sumber Solscan, `holders["depth"]` +
   `holders["api"]` ikut tersimpan di snapshot `silent_status`.
4. UI watchlist: ikon 📡 Solscan di kolom Real, expander per token
   "📊 Wallet Depth by Threshold" berisi dua tabel (bucket & tier).
5. Workflow cron menerima env `SOLSCAN_API_KEY` (repo secret, opsional);
   `config.example.json` + docs diperbarui. Catatan: bila GitHub App
   menolak push perubahan `.github/workflows`, tambahkan env tersebut
   manual di settings repo.

Tidak diubah: logika silent 12 jam, filter holder depth (SILENT/LP/
PUMPDUMP), listing Trending/Degen.

# Kegiatan — 19 Agustus 2026 (lanjutan)

- Token baru: fetch penuh **48 jam** (bukan incremental), lalu kirim Telegram
  untuk **semua** sinyal di window itu (historis tetap dikirim, sekali per
  `event_id`).
- Payload Telegram: hari (WIB), jam bar, range harga, range MC, R/CVD/TX,
  link GMGN + DexScreener. Tag “Historis” vs “Sinyal baru”.
- `add_to_watchlist` memanggil `request_immediate_scan()` (workflow_dispatch)
  agar 48 jam ditarik segera, lalu cron 15 menit menyambung incremental.

# Kegiatan — 19 Agustus 2026

Port sinyal ekstensi [SMART_SEROK v9.1.3](https://github.com/lparmycalprut/SMART_SEROK) ke wallet-depth.

## Yang dikerjakan

1. **Watchlist dikosongkan** (`watchlist.json` = `{}`).
2. **Symbol otomatis** saat CA manual: field ticker dihapus di form Streamlit;
   `watchlist.fetch_token_symbol()` memanggil DexScreener.
3. **Sinyal diganti** dari wash-collapse / SBR menjadi:
   - 🔴 WASPADA DUMP
   - 🟢 SIAP2 PUMP
   - ⚔️ BATTLE TERJADI
   Engine: `serok_engine.py` (bar 1 jam, R ≥10× prev + |R|≥10, battle gap ≤2.5% + P65).
4. **Scan tiap 15 menit** (intended cron `*/15`). File workflow tidak bisa
   di-push oleh GitHub App (butuh permission `workflows`) — ubah manual
   `.github/workflows/daily-effort.yml` menjadi `*/15 * * * *`. Fetch 48 jam.
5. **Telegram** rapi: judul + `$SYMBOL`, syarat, R/CVD/TX/wallet, range MC (battle),
   jam WIB, tautan GMGN + DexScreener. Satu alert per `event_id`.
6. **Tes** `tests/test_serok_engine.py`; payload Telegram & UI disesuaikan.
   `python -m unittest` untuk modul baru lulus.

Tidak diubah tanpa perlu: halaman CVD, listing Trending/Degen, fetch GMGN,
persist watchlist GitHub.

# Kegiatan — 30 Agustus 2026

Refactor besar: **buang semua sinyal + Telegram**, fokus **silent
accumulation 12 jam** dan **holder depth**.

## Yang dikerjakan

1. Hapus modul sinyal (serok, reversal, effort, price_structure), scanner
   realtime, dan transport `signals.py` (Telegram) beserta secrets.
2. `silent_accumulation.py`: fetch holder GMGN paginasi `next`
   (verified limit 1000/page, `limit=1000`), klasifikasi real holder
   (>$10 value) vs dust (0 < value <= $10), dust % dari marketcap,
   net flow 12 jam (`token_trades`), deteksi silent (net >= $50,
   >= 3 akumulator, |harga| <= 5%, bot <= 35%).
3. `silent_status.py` + `scripts/scan_silent.py`: cron tiap ~15 menit
   publish snapshot ke ref `silent-live`.
4. `app.py` & `trending_ui.py`: kolom/holder-depth langsung saat scan
   Trending/Degen (real count, dust count, dust %MC, status 12 jam).
5. Halaman CVD: chart flow harian tanpa sinyal; `daily_effort.json`
   dipertahankan sebagai agregasi murni (`daily_store.py`).
6. Workflow `daily-effort.yml` target: Silent Accumulation 12H Scanner tanpa
   `TELEGRAM_*`. Catatan: file workflow tidak bisa di-push oleh GitHub App
   (butuh permission `workflows`), jadi `scripts/realtime_reversal.py`
   dipertahankan sebagai adapter ke `scan_silent.py` agar cron tetap
   berjalan; ubah workflow manual bila ingin langsung memanggil
   `scripts/scan_silent.py`.

Tidak diubah tanpa perlu: watchlist GitHub, fetch GMGN/Helius, listing
screener.
## Lanjutan hari yang sama — konfirmasi volume + volatilitas (permintaan ke-3)

User mengirim prompt baru: alert dust 0,25 pp masih sering false positive,
jadi tiap sinyal harus divalidasi volume + harga + volatilitas dulu, tetap
reaktif (< 5 menit), dan ambang dust yang ada tidak boleh diubah.

1. **Volume correlation** — `validate_alert_with_volume()` di
   `telegram_alerts.py`: dump butuh volume 4 jam ≥ 2× `avg_volume_7d`
   **dan** harga ≤ −1%; akumulasi butuh ≥ 1,5× **dan** tekanan beli >
   tekanan jual. Skor 0,70 dasar + ≤0,15 volume + ≤0,10 harga/tekanan +
   0,20 volatilitas tinggi yang mendukung arah; gagal gerbang → ≤0,40.
   `avg_volume_7d` dibaca sebagai rata-rata **per window 4 jam** selama
   7 hari agar sebanding dengan `volume_4h`. Semua kandidat yang ditolak
   di-log + dicatat ke `rejected_signals` supaya bisa diaudit.
2. **Volatility metrics** — `calculate_volatility_metrics()` di
   `holder_history.py` dari 16 candle hourly: `price_stddev_4h`,
   `price_range_4h`, `intra_hour_volatility`. Kalau `price_stddev_4h > 3%`
   ambang skor naik dari 0,70 ke **0,80** — dan karena volatilitas tinggi
   tanpa dukungan arah harga tidak memberi bonus, ambang itu benar-benar
   menyaring (terukur 0,702 < 0,80). Hasilnya disimpan berdampingan
   dust % MC di `holder_status.json` sebagai `tokens[mint].market_signal`.
3. **Sumber konteks** — `alert_context.py` (baru): candle hourly
   GeckoTerminal → DexScreener (data yang sudah diambil `analyze_token`,
   tanpa request tambahan) → `daily_effort.json`. Ditarik **lazy**: hanya
   token yang punya kandidat (keputusan user), memo 1× per token per run,
   jadi latensi run normal tidak bertambah. `core.get_hourly_candles()`
   baru dan `get_daily_candles()` kini agregasi dari candle yang sama.
4. **Data hilang** (keputusan user): alert tetap dikirim, diberi baris
   `⚠️ TIDAK TERVERIFIKASI` dengan skor 0,50 — jadi tidak ada sinyal yang
   hilang diam-diam saat GeckoTerminal mati.
5. **Dedup 1 jam** — selain event id bucket 4 jam, kini ada jeda minimum
   1 jam per token+jenis(+arah) lewat `alert_state.last_sent`; sebelumnya
   dua alert identik bisa terkirim berjarak ±2 menit di sekitar batas
   bucket.
6. **Review optimasi** (diminta user, tabel lengkap di
   `docs/PROGRESS.md`): heap untuk `matching_dexscreener_pairs` diukur
   **tidak** lebih cepat sehingga tidak diubah; `get_daily_candles`
   diperbaiki (sel null, `limit_days=0`, timestamp duplikat) dan batas UTC
   diverifikasi sampai kasus kabisat; `classify_holders` dibuat single-pass
   ramping (2,86 → 1,94 ms per 12k holder, keluaran identik di 500 trial);
   `wallet_movements()` tidak lagi dihitung dua kali; dua `TODO(alerts)`
   (429 `retry_after`, throttle GeckoTerminal).
7. **Tes** — 6 file baru, 141 tes tambahan: 369 lulus (sebelumnya 228),
   termasuk edge case volume 0, avg 0/None, NaN/inf, candle bolong,
   candle < 2, candle basi, payload DexScreener rusak, provider gagal,
   cooldown 1 jam, dan lazy-fetch.
## Permintaan ke-4 — AGENTHQ: grafik 0,7% tapi kartu "Dust hold % MC" 1,16%

User melaporkan angka yang tidak cocok di halaman Holder Analytic. Setelah
ditelusuri (snapshot live di ref `holder-live` + DexScreener), ada dua lapis
penyebab dan **bukan** bug grafik:

1. **Kartu metrik dan grafik membaca dua sumber berbeda umur.** Kartu metrik,
   badge, dan caption membaca snapshot `holder_status.json` (cron 21:35 WIB),
   sedangkan grafik membaca `holder_history.json` yang sudah memuat titik scan
   manual yang baru dijalankan. Tombol scan FULL hanya `ingest_many(detail=True)`;
   ia tidak mempublish snapshot — dan memang tidak boleh, karena
   `snapshot_status` membangun `tokens` hanya dari analyses yang diberikan
   (publish satu token = token lain hilang dari dashboard).
2. **Harga sedang pump +74% dan cutoff dust itu $10 dalam USD.** harga
   0,0001085 → 0,0001889, MC $108.545 → ±$188.968. dust % MC invariant
   terhadap harga, tetapi **klasifikasi**-nya tidak: wallet dengan 52.938–
   92.166 token (nilai lama $5,74–$10) "lulus" menjadi real >$10, sehingga
   ±40% nilai dust pindah bucket dan dust % MC turun 1,16% → 0,7% tanpa ada
   yang jual. Cerminannya (harga turun) menaikkan dust % MC ±0,4-0,5 pp —
   di atas ambang dump 0,25 pp — dan itu lolos gerbang volume/harga.

Perbaikan yang dikerjakan (user memilih opsi A): `holder_status` mendapat
`compact_manual_scan()`, `resolve_token_view()`, dan `apply_manual_scan()`;
halaman Holder Analytic + `app.py` mengoverlay scan manual yang lebih baru ke
snapshot sebelum render, sehingga kartu metrik, badge, watchlist, dan Chart LP
setuju dengan grafik, dan caption menandai *scan manual barusan*. Guard
re-klasifikasi harga (opsi B) belum dikerjakan — keputusannya (**annotate,
bukan reject**) dicatat sebagai `TODO(alerts)` di `telegram_alerts.py`.
Tes: 27 murni + 2 AppTest baru → **398 lulus**.
