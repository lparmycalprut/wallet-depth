# Kegiatan

## 2026-10-14 — Analisis wallet COCK 1 Okt 2026 (sampel parsial)

Permintaan: cari wallet yang melakukan pump, churn, atau berperan dalam sweep
COCK 1 Okt 2026, sekitar 20:00–23:00 WIB. Token `H4KUxsEgCp2yDpFvyDuGM5k6XevSKKrrKUxZ3Zr6nyJc`.

**Sumber:**
- GeckoTerminal `/trades` hanya menyimpan ±300 trade terakhir. Tidak menjangkau 1 Okt.
- GMGN `vas/api/v1/token_trades/sol/{ca}` dengan parameter `from` dan `to` (unix detik)
  mengembalikan trade historis per wallet. Paging memakai `cursor` (nilai `next`).
  Satu halaman berisi maksimal 100 trade dan dikirim dalam 7 chunk.
- GMGN `api/v1/tokens/top_buyers/sol/{ca}`: 70 holder awal (sniper). Saat ini 69 sudah
  jual penuh, 1 jual sebagian, 0 hold.

**Cakupan yang sudah dibaca (WIB):**
- 22.40.00–22.41.30: sepi, ±6 trade kecil (±$0,05). Harga ±0,00023.
- 22.41.31–22.42.56: halaman terakhir terbaca, 100 trade dalam ±2 detik. Harga naik dari
  ±0,00023 ke ±0,00082–0,00084.
- 22.42.58–22.44.00: halaman pertama terbaca.
- 22.44.59–22.45.00: halaman pertama terbaca.
- 22.45.00–23.00: belum dibaca.

Perkiraan awal bahwa 3–5 halaman cukup untuk jendela pump **keliru**. Trade pada
22.42–22.45 sangat padat (±50 trade/detik saat puncak). Cakupan penuh membutuhkan
ratusan panggilan `fetch_page`. Hasil di bawah adalah sampel, bukan daftar lengkap.

**Wallet dari sampel (bukan kesimpulan final):**

Batch 22.42.56 (harga 0,00082–0,00084):
- `AYZryL5JYFhAJ7PtA9uvebDqcFrifcPTucvDyjbd7xzN`: jual 595.571 token ($510). Tag axiom, padre. Realized $3.463.
- `GGc5VqHic9ieUXbmWa2PWWNenGALbFHPWGChgsZNk3K7`: beli 310.963 token ($271). Tag gmgn, axiom, launchpad_smart, bundler.
- `2NXXPvBR6LVBrE2d3HVDenc6xXvMP6UF23Wz3FhKfVm4`: beli 271.765 token ($235). Tag axiom, padre, bundler.
- `HmVaXWrATTGQmKzbDHuwcdMgvwBoFCjJRX9mTvCHYEvf`: beli 98.607 token ($85). Tag axiom, paper_hands, bundler. 74 trade, realized $1.665.
- `25ZcRco9VbttzHwwuZ13198zkXmBshtRYmaQzba1Efgv`: jual 387.121 token ($318). Tag smart_degen, axiom. Realized $294.
- `67AtLpewju66U9vAmUE46SDib35v6fQeB2aTcbcxSpVv`: beli 135.141 token ($113). Tag fresh_wallet, axiom, bundler.
- `mango2yYw5iHjW2zBoiKLGicQDKj8JTAAqsEceq6b6o`: jual 287.222 token ($237). Tag axiom, padre.
- `5bnmvJXGFNPY3HYvUcsKaMhW7iRPoMYP1BJhqKbr9BWx`: jual 581.907 token ($487). Tag axiom, padre.

Batch 22.44.00 (harga ±0,0011):
- `6gRofZ46MG1WagtRLUr8S9LkP9HFYo894KrMwkLkzjLj`: beli 1.020.459 token ($1.127). Tag gmgn, paper_hands, axiom, gmgn_go, bundler. Pembeli terbesar yang terlihat.
- `EraSoBvgn8jmhesKbrsjkLrJ5QZvH5gmZuHe6pqBEc9a`: jual 302.904 token ($326). Tag padre, bundler. 87 trade, realized $5.302.
- `4emG3Uud1nYFjTHFx3xymxwDtrjjPgHaCcZjNX2odR9z`: beli 206.320 token ($225). Tag gmgn, gmgn_go, padre, axiom, bundler.
- `a9Cct2wpjn4vWSR4rsytxm1URyk6vTXo4RTqXFpjyvD`: dua beli ±30–31k token ($34 tiap transaksi) dalam detik yang sama. Tag axiom.
- `8eLeSuhPcHNVMhXPxM4cVGMDxQXtAuuutvJqRv9phkT5`: beli 30.064 token ($34). Tag axiom, bundler. Jumlah SOL identik dengan `a9Cct2` (6.235,928764). Pola bundle.
- `DoBEQpfrZ3xed65wHSKeAHcuqeGtKTA1UtXECzyJXt5f`: beli 7.234 token ($8). Tag gmgn_go, padre, fomo, axiom.

Batch 22.45.00 (sampel dari halaman pertama):
- `AyqWZUPkP9J6oRXwJ3upfizXCsAN1Hr3KfTqQEhykWJr`, `AHw86gCwPmWsofoocEwguKJbQCykXR3NEhxUKx6wv4SD`, `5M79F1cMpoNc5mFzx39EpycfzM2ixETVLYnZkh2CH4wk`: tag axiom, padre, bundler. Jual ±$100–115 tiap transaksi. Riwayat hampir identik: 31 trade, beli 5,01–5,11 juta token, realized $621–652. Kemungkinan satu operator.
- `8oSD5a9EG933qyuL8YdnSy6YPF7peNiXm7PAx19R1phB`: tanpa tag. 328 trade, beli 25,0 juta, jual 24,8 juta, realized $1.007. Pola churn.
- `FnnW7bZdCG7Jd6mqqAxMx1Wd6fT8N5nkC6SdSZBxhccn`: beli 321k token ($511). Tag gmgn, axiom, paper_hands.
- `4AgdaCf3XvAydGJiqC3QTDrsQVeCPB1mZXSrFsm4euUd`: jual 181.631 token ($282). Tag axiom. Realized $15.
- `MeskxyRYaBhYERcNP2zLVTqFVR43TMX4MihyH7AU4XN`: jual 129.591 token ($179). Tag axiom.

Wallet sandwich bot (bukan pelaku pump besar): `78Bo7xxGWBEvqbh3VMKvkFG4Z63cXKSJ2LCEXAanhN7a` dan `8pY1AukbuPgUE3EetyLa59rFLMimJGT94ZzbMEZcQF4w`.

**Belum terjawab:** siapa yang memulai pump di 22.41–22.42, dan kontribusi penuh 22.45–23.00. Keduanya membutuhkan paging penuh atau `cvd.py` di mesin lokal.

---

## 2026-10-13 — Sweep: urut menurut skor, kolom Kohort dilebarkan, refresh per token

- **Urutan tabel** sekarang menurut skor `lolos/punya data` tertinggi (permintaan
  user). Kohort PLUS tetap paling bawah; mint tanpa snapshot tampil sebagai
  `MENUNGGU SNAPSHOT` di atasnya.
- **Kolom Kohort** dilebarkan (320 px) supaya status seperti `TUNGGU — kohort belum minus 50%` terbaca.
- **Refresh per token:** setiap mint punya tombol `🔄 Refresh <mint>` di detailnya
  (dan di baris menunggu snapshot). Tombol ini memindai satu mint saja dan langsung
  menyimpan snapshot.
- Diverifikasi dengan `AppTest`: placeholder tampil, refresh per token mengisi
  snapshot tanpa exception; 138 test sweep lolos.

## 2026-10-13 — Sweep: snapshot terakhir saat dibuka, kohort PLUS di bawah, ambang kohort minus 50%, hapus dari tabel

Permintaan user: *halaman dibuka langsung menampilkan snapshot terakhir, diurutkan
dari yang paling mendekati kelayakan; kohort PLUS di paling bawah; ambang kohort
diturunkan ke minus 50%; refresh manual tetap ada; hapus mint dari tabel.*

- **Ambang kohort** `COHORT_MINUS_THRESHOLD` −0,70 → **−0,50** (`sweep_screen.py`).
  Label gate memakai ambang ini (`TUNGGU — kohort belum minus 50%`). AGENTS.md
  dan `docs/sweep.md` ikut diperbarui.
- **View snapshot:** setiap snapshot terbaru menyimpan `view` (metrik + vonis +
  konteks sweep, daftar field eksplisit). Hanya satu view per mint yang disimpan,
  jadi `sweep_state.json` tidak membengkak. Halaman dibuka membaca view ini tanpa
  scan jaringan; mint tanpa view dipindai sekali.
- **Urutan tabel:** `display_sort_key` — vonis, lalu jumlah kriteria lolos, lalu
  jarak kohort ke −50% untuk kelompok TUNGGU. Kohort PLUS selalu paling bawah.
- **Tombol** `🔄 Refresh & ambil snapshot` (sebelumnya "Scan sekarang") memindai
  live semua mint watchlist dan menyimpan snapshot. Auto-refresh tetap ada.
- **Hapus dari tabel:** kolom *Hapus* (checkbox) + tombol; memperbarui
  `sweep_watchlist.json` dan di-commit ke GitHub. Snapshot/sinyal mint tetap
  tersimpan di state.
- Verifikasi: 138 test sweep lolos; halaman diuji dengan `AppTest` (jaringan
  di-stub, berkas state dialihkan ke folder sementara). Klik centang di data editor
  tidak bisa disimulasikan oleh AppTest, jadi logika pemilihan diuji sebagai fungsi
  murni (`_flagged_mints`).

## 2026-10-12 — Batas holder per-wallet jadi setelan, default 3% → 5%

Permintaan verifikasi data riil: *"batas holder per-wallet harus jadi setelan, bukan angka mati 3%"*.

Berdasarkan data nyata Team Human (diverifikasi lewat AppTest dengan jaringan di-stub):
- Token dengan top-10 18,97% (sehat) tapi satu holder 3,94% → kandidat yang
  strukturnya paling mendekati pola dicari malah gugur di batas 3%.
- Dengan batas 5%: LAYAK SWEEP 4/4.
- Dengan batas 3% (lama): KANDIDAT 3/4 (kriteria 3 gagal).

**Perubahan:**

1. **`sweep_screen.py`:**
   - `HOLDER_MAX_PCT = 3.0` → `5.0` (default baru)
   - `SETTINGS_DEFAULTS` tambah `holder_max_pct`
   - `SETTINGS_MIN_HOLDER_PCT = 1.0`, `SETTINGS_MAX_HOLDER_PCT = 20.0`
   - `normalize_settings()` menangani `holder_max_pct` (dijepit 1%–20%)
   - `criterion_float_spread(..., max_holder_pct=None)` pakai setelan, detail
     selalu menyebut batas yang dipakai

2. **`sweep_ui.py`:** slider kedua "batas holder per-wallet (%)" 1–20 di halaman

3. **`scripts/scan_sweep.py`:** `--holder-max-pct` di cron (tidak mengembalikan
   liq_mc_max ke default)

4. **Test:** 373 → 377 OK; data nyata Team Human dikunci

5. **Dokumentasi:** `docs/sweep.md`, `KEGIATAN.md`

---

## 2026-10-12 — Perbaikan biaya sweep: ukur ke PUNCAK candle, bukan close

Permintaan verifikasi data riil: *"biaya dorong sweep harus diukur ke PUNCAK candle, bukan ke harga close, dan pembilang leverage harus memakai kenaikan MC, bukan MC di close"*.

Berdasarkan rekonstruksi reserve COCKROACH 1 Okt 2026:
- reserve quote naik **$30.232 → $89.010** (rasio 2,9442), dan ``akar(8,669) = 2,9442``.
- Artinya uang yang masuk ke pool dipakai membeli **seluruh ekskursi sampai puncak**, bukan berhenti di harga close.

**Perubahan:**

1. **`sweep_screen.py` — `sweep_context()`:**
   - `peak_mult = peak / base_price` (fallback ke `price_mult` kalau peak tidak ada)
   - `est_cost_usd` pakai `peak_mult` → $58.778 (bukan $24.067 dari close)
   - `est_cost_close_usd` baru: biaya ke close = $24.067 (untuk dokumentasi perbandingan)
   - `paper_gain_usd = supply × (peak − base_price)` → $1.790.194 (bukan paper_mcap di close)
   - `leverage` pakai `peak_mult` → 30,5× (bukan ≤21× dari close)
   - `leverage_net = paper_gain ÷ net_inflow` (bukan paper_mcap ÷ net_inflow)
   - `churn_x = vol ÷ est_cost` (sudah benar, tetap 21,1×)
   - Konstanta `REF_NET_COST_MULT`: **2,44 → 1,0** (inflow $58.778 ≈ biaya ke puncak $58.774)

2. **`sweep_alert.py` — `format_sweep()`:**
   - Baris baru: `Biaya dorong ke puncak (akar m − 1) × liq: $58,778 = 25.2% dari MC`
   - `Biaya dorong ke close (akar price_mult − 1) × liq: $24,067` (angka lama yang sebelah)
   - `MC kertas yang naik: $1,790,194 → leverage 30.5x`
   - `Paper MC di close (besaran lain, bukan pembilang leverage): $752,939`
   - `Inflow nyata (Δ likuiditas): $58,778 → 1.0x biaya dorong ke puncak`
   - Catatan "ada pembeli luar" **hanya jika** `churn_net_x < churn_x × 0,9`
   - Kalau belum terukur: `Perkiraan inflow (belum ada snapshot pembanding) … acuan kalibrasi 1 event`

3. **`sweep_scan.py`:** tambah `peak_mult`, `est_cost_close_usd`, `paper_gain_usd`, `leverage_net` ke sinyal `kind == "sweep"`.

4. **`sweep_ui.py`:**
   - Banner: `harga $0.00023768 → puncak $0.00206033 (8.7x), tutup di $0.00076674`
   - `Biaya dorong ke puncak $58,778 = 25.2% dari MC`
   - `ΔMC kertas $1,790,194 → leverage 30.5x`
   - Tabel statistik tambah kolom: `Puncak`, `Peak mult`, `Biaya ke puncak`, `Biaya ke close`, `ΔMC kertas`, `Leverage`

5. **Test:** kunci semua angka dengan basis supply `982_000_000`:
   - `est_cost_usd ≈ 58.778` dan = `(akar(peak_mult) − 1) × 30.232`
   - `est_cost_close_usd ≈ 24.067` dan beda > 2×
   - `est_cost_frac ≈ 0,252`
   - `paper_gain_usd ≈ 1.790.194` dan `paper_mcap_usd ≈ 752.600` (dua besaran berbeda)
   - `leverage ≈ 30,5` di tiga jalur
   - `churn_x ≈ churn_net_x ≈ 21,1` saat inflow 58.778
   - candle tanpa `peak` tidak menghasilkan `None`

6. **Dokumentasi:** `docs/sweep.md` tabel angka diganti versi puncak.

**Alasan (jangan diubah):** Sweep COCKROACH 1 Okt 2026 membuktikan bahwa inflow $58.778 ≈ biaya ke puncak $58.774 (selisih <$4, dalam boltjang). Menggunakan close sebagai referensi menghasilkan biaya $24.067 yang sebelah 2,44× dan leverage yang underestimate.

---

## 2026-10-12 — Ambang liq/MC page 🌊 Sweep jadi setelan, bukan angka mati

Pertanyaan user: *"minimum Liquidity/MC ini 15% memang harus apa bisa diperlonggar?"*

- **15% bukan batas alam.** Yang menentukan biaya sweep adalah
  `biaya/MC = (akar(m) − 1) × (liq/MC)`, jadi "mahal/murah" selalu relatif
  terhadap target kelipatan harga. Batas fisiknya: naik 10x melewati 100% MC di
  liq/MC **46,2%**, naik 5x di **80,9%**.
- Ambang dipindah dari konstanta menjadi **setelan user**: slider 5%–60%
  (default 15%) di halaman, opsi `--liq-mc-max` di runner cron, disimpan di
  `sweep_state.json` (`settings.liq_mc_max`) supaya halaman dan cron memakai
  angka yang sama, dan ikut masuk `store.fingerprint()` agar perubahannya
  ter-commit.
- Rentangnya dijepit: di bawah 5% likuiditas terlalu tipis untuk masuk/keluar
  posisi, di atas 60% kriterianya kehilangan arti (naik 2x pun perlu 21% MC).
- Di bawah slider ada tabel biaya untuk ambang yang sedang dipakai
  (`naik 2x = 6% MC`, `naik 3x = 11% MC`, dst) supaya longgar-sempitnya bisa
  dinilai langsung, bukan ditebak.
- Detail kriteria 1 sekarang selalu menyebut ambang yang berlaku **dan** biaya
  naik 3x, jadi alert lama tetap bisa diaudit: batas mana yang dipakai saat itu
  tersimpan di `result.settings` dan di riwayat sinyal.
- Menggeser slider **tidak** memanggil jaringan lagi — baris yang sudah ada
  dinilai ulang dari data di memori (`sweep_scan.rescore_rows`), jadi mencoba
  beberapa ambang tidak menambah beban API.
- Diperbaiki: `save_settings` sempat menyalin dict sehingga state pemanggil
  tidak ikut berubah (setelan tidak pernah tersimpan dari `run_scan`).


## 2026-10-12 — Page baru 🌊 Sweep: skrining kelayakan sweep + alert Telegram

Permintaan user: *"bisa kamu buatkan di wallet-depth? bisa memasukkan daftar mint manual ke dalam sistem, jadi ada telegram alert ke saya, dan juga di streamlit. alert ketika ada token di watchlist saya yang potensial akan terjadi sweep, dan alert ketika sweep mulai terjadi. detailnya semua bisa masuk ke tabel statistik yang bisa saya lihat"* dan *"jangan taruh di main app, tapi buat page baru"*.

- **Halaman terpisah** `pages/8_🌊_Sweep.py` (multipage Streamlit). `app.py`
  tidak disentuh sama sekali — Best Pool tetap satu-satunya isi halaman utama.
- **Watchlist manual**: user menempel mint (satu per baris; koma/spasi/komentar
  `#` juga diterima). Tidak ada pengisian otomatis dari scanner mana pun.
- **Enam kriteria kelayakan** dari analisis COCKROACH 1 Okt 2026 menjadi skor
  bertiga-status (lulus / gagal / belum ada data):
  1. `liq/MC < 15%` — murah digerakkan;
  2. LP terkunci ≥ 85% + authority dicabut — ambang 85% (bukan 90%) karena
     token acuan sendiri hanya 89,8%;
  3. float tersebar: top-10 < 25% dan tiap holder < 3% (akun pool dikecualikan);
  4. akumulasi **proxy** (net beli > 0, harga sideways) — bukan CVD level
     wallet, itu butuh Helius;
  5. volume dari titik tersepi lalu ekspansi ≥ 3x, harga belum lari < 3x;
  6. shakeout ≥ 30% dengan higher low.
  Vonis `LAYAK SWEEP` = trio struktural (1+2+3) lulus **dan** minimal
  `min(4, jumlah kriteria yang sudah ada datanya)` lulus. Ambangnya
  menyesuaikan karena di deploy baru hanya trio struktural yang bisa dinilai —
  menuntut 4 dari 3 akan membuat halaman tidak pernah memberi alert kelayakan.
  Begitu riwayat akumulasi/volume/shakeout terkumpul, syaratnya otomatis naik
  menjadi "struktural + minimal satu bukti".
- **Alert Telegram, hanya saat transisi status** (bukan tiap scan): kelayakan
  muncul/menghilang (cooldown 6 jam) dan sweep mulai terjadi (cooldown 30
  menit). Kredensial dibaca berlapis: `st.secrets` → environment →
  `config.json`; nama variabelnya sama dengan `handsoff/prepump_cron_detector.py`
  (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`). Ada tombol **Kirim test alert**.
- **Deteksi sweep**: volume candle 5-menit ≥ 20x median 24 candle sebelumnya
  **dan** harga ≥ 1,5x. Barisnya memuat `vol_x`, `price_mult`, `bars_ago`, dan
  `liq/MC`.
- **Angka teoretis dipisah dari angka terukur** — ini yang paling mudah salah:
  - `est_cost_usd` = `(akar(m) − 1) × liq` = **biaya dorong minimum**
    (COCKROACH 1 Okt: $24.067);
  - `net_inflow_usd` = selisih likuiditas antar snapshot = **inflow nyata**
    (COCKROACH: $58.778 = 2,44x biaya dorong);
  - `churn_x` = volume ÷ biaya teoretis (51,6x) dan `churn_net_x` = volume ÷
    inflow nyata (21,1x, angka yang dipakai di analisis awal).
    Kalau belum ada snapshot pembanding, acuan 2,44x dipakai **dan diberi
    label "acuan 1 event"** — tidak pernah ditampilkan sebagai pengukuran.
  - `paper_mcap_usd` diperbaiki menjadi MC di **close** candle (`m × MC`),
    sebelumnya memakai `(m − 1) × MC` sehingga MC-nya kurang satu satuan.
- **Tabel statistik**: tiap alert meninggalkan baris sinyal berisi harga
  entry, `max_up_pct` / `max_down_pct` (dilacak 72 jam), `from_base_up_pct`,
  churn, dan status. Ringkasannya: jumlah sinyal, hit ≥100% / ≥300%, median
  naik/turun, plus break-even hit rate 13,0% (menang +200% / kalah −30%).
- **Dua runtime**: cron GitHub Actions `*/5 * * * *`
  (`.github/workflows/sweep-scan.yml`) dan auto-refresh halaman tiap 5 menit
  selama tab terbuka. Commit cron dibatasi `store.fingerprint()` sehingga
  hanya snapshot jam baru / sinyal baru yang di-commit — tanpa itu cron 5
  menitan akan membuat ~288 commit/hari.
- **Penyimpanan** `sweep_watchlist.json` + `sweep_state.json` (di-commit lewat
  GitHub Contents API supaya selamat dari restart Streamlit Cloud);
  `sweep_cache.json` masuk `.gitignore`. Kalau token GitHub belum ada, UI
  memberi tahu bahwa daftarnya baru tersimpan lokal **dan** menulis cadangan
  ke `config.json` (`sweep_watchlist`).
- `AGENTS.md` dan `DEPLOY.md` diperbarui: alert Telegram kembali **sah khusus
  untuk page 🌊 Sweep** (keputusan produk eksplisit user), sementara mesin
  alert era Holder tetap tidak dihidupkan kembali.

## 2026-10-09 — Bundler+Phishing tidak lagi menyaring pool

Permintaan user: *"filter untuk bundler dan phising hapus saja, jadi tetap lolos meskipun bundler dan phising besar"*.

- Menghapus Bundler+Phishing GMGN dari seluruh keputusan kelolosan. Persentase
  tinggi, data tidak valid, maupun report GMGN yang gagal dibaca tidak lagi
  mengeluarkan kandidat dari tabel utama.
- Mempertahankan kolom Bundler+Phishing sebagai informasi; nilai tinggi hanya
  diberi penanda risiko merah statis, bukan status gagal atau animasi berkedip.
- Memastikan baris yang dulu tersimpan di `pool dilewati` hanya karena gate
  Bundler+Phishing kembali ke tabel utama dari cache, selama memenuhi filter
  pool lainnya.
- RugCheck dan tax/dividend tetap berjalan untuk semua baris yang memenuhi
  filter pool, tanpa bergantung pada hasil Bundler+Phishing.

## 2026-09-28 — Bundler+Phishing menjadi gate final dengan batas 40%

Permintaan user: *"kita perbesar batas bundler + phising menjadi 40% maksimal"* dan *"filter terakhir kelolosan adalah di f/v dan di bundler"*.

- Mengubah batas gabungan Bundler+Phishing GMGN menjadi **40% maksimal**;
  tepat 40% lolos, sedangkan di atas 40% tidak masuk tabel utama.
- Mengembalikan Bundler+Phishing sebagai filter final setelah F/V. Laporan
  yang tidak terbaca juga fail-closed agar tidak dianggap aman tanpa data.
- Pool yang gagal gate final tetap masuk **pool dilewati** untuk transparansi,
  dan kolom Bundler+Phishing-nya menjadi **bold merah menyala berkedip**.
- Cache laporan lama yang masih memakai batas 25% diinvalidasi otomatis.

## 2026-09-28 — Bundler+Phishing untuk pool dilewati dan lantai F/V 5×

Permintaan user: *"Bundler+Phishing yang ada di pool disembunyikan juga harus di fetch datanya"* dan *"syarat pool yang masuk kriteria ... minimal 5x F/V"*.

- Tabel utama tetap mensyaratkan **F/V ≥ 10×**.
- Pool dengan **F/V 5× sampai <10×** tetap masuk listing **pool dilewati** dan sekarang ikut mengambil data **Bundler+Phishing GMGN**.
- Pool dengan **F/V < 5×** dibuang total dari card (tidak masuk tabel utama maupun pool dilewati) agar hanya kandidat minimal yang diperkaya data pihak ketiga.
- Fetch Bundler+Phishing dibatch untuk baris utama + baris dilewati supaya mint duplikat tetap satu request.

## 2026-09-28 — F/V minimal 10× dan batas Token:SOL dihapus total

Permintaan user: *"filter batasan perbandingan token : sol hilangkan lagi"* dan
*"ganti minimal f/v ke 10x minimal"*.

- Menaikkan ambang F/V Best Pool dari **2× menjadi 10×** (inklusif) untuk
  tabel utama. Catatan: lanjutan pada hari yang sama menetapkan lantai kandidat
  **5×**, sehingga F/V 5× sampai <10× masuk listing "pool dilewati".
- Menghapus seluruh sisa batas perbandingan Token:SOL: konstanta
  `BEST_SOL_TOKEN_MAX_RATIO`, `BEST_TOKEN_SOL_MIN_RATIO`,
  `BEST_TOKEN_SOL_RATIO_LIMIT_LABEL`, isi `row_liquidity_distribution_gap`
  (kini stub yang selalu kosong), dan kategori alasan gugur token:SOL.
- Kolom **Token:SOL** tetap ada sebagai informasi (label + tooltip presisi
  penuh), tanpa ambang apa pun.
- Tooltip/caption UI diselaraskan ke angka 10×.

## 2026-09-27 — F/V 3× dan gate Bundler+Phishing

- Menurunkan minimum F/V Best Pool dari **5× menjadi 3×** (inklusif).
- Menghapus Token:SOL sebagai filter; kolom dan nilai USD resminya tetap
  ditampilkan sebagai informasi pada pool lolos maupun pool dilewati.
- Mengganti filter terakhir menjadi statistik GMGN **Bundler +
  Phishing/Entrapment ≤ 25%**. Tepat 25% lolos; di atas 25% atau data wajib
  tidak terbaca masuk tabel pool dilewati.
- RugCheck dan tax/dividend hanya dijalankan setelah gate risiko GMGN lolos.

## 2026-09-27 — Token:SOL pada pool dilewati

- Baris yang masih tersedia lewat tombol **pool dilewati** sekarang ikut
  mengambil detail resmi Meteora dan menampilkan nilai **Token:SOL**.
- Fetch tambahan hanya untuk baris dilewati yang belum memiliki laporan
  distribusi; hasilnya murni informasi dan tidak menjadi jalur lolos alternatif.
- Jika detail gagal, sel tetap `—` dan pool tetap berada di tabel dilewati.

## 2026-09-27 — deteksi bundler token

Permintaan user: *"bisakah kamu deteksi bundler untuk token yang kita scan?"*

- Menambahkan kolom **Bundler** untuk pool yang lolos scan.
- Sumbernya statistik per-token GMGN
  `top_bundler_trader_percentage` (porsi supply yang diperdagangkan wallet
  yang diklasifikasikan GMGN sebagai bundler), dilengkapi konteks dev dan
  sniper bila tersedia.
- Klasifikasi informasi: `< 5%` rendah, `5%–<15%` waspada, dan `≥ 15%`
  berisiko. Data gagal/hilang ditulis `—`, tidak ditebak dan tidak menyaring
  pool.
- Request berjalan paralel dan memakai cache 15 menit; tabel utama kini 16
  kolom dan tetap dapat digeser horizontal di ponsel.

## 2026-09-27 — klarifikasi batas distribusi SOL

Permintaan user: *"maksimal SOL-nya adalah 2× token."*

- Membalik gate distribusi akhir menjadi **nilai USD SOL ≤ 2× nilai USD token**.
- Batas **token:SOL 1:2** tetap inklusif; **1:1.5** dan saldo yang lebih
  token-heavy lolos, sedangkan **1:6.52** gagal karena sisi SOL melebihi 2×.
- Menyelaraskan tooltip, teks tabel, ringkasan hasil, checklist, README, dan
  regression test dengan arti batas maksimum tersebut.

## 2026-09-26 — perapihan kolom tabel Best Pool

Permintaan user:

1. *"hapus saja tombol copy hawkfi link dari kolom"*
2. *"hapus juga kolom strategy dan logika deteksi strategy apa yang dipakai"*
3. *"Token:SOL kolom ini taruh dikanan LPs, lalu pakai 1 angka aja dibelakang koma"*

Yang dikerjakan:

- Menghapus tombol 📋 **copy link HawkFi** dari kolom Pool (`links.hawkfi_copy_html`
  beserta seluruh JS clipboard-nya dan CSS `.hawkfi-copy-btn`). Kolom Pool kini
  hanya berisi tautan 🌊Meteora, 🦅HawkFi, dan 🫧 Bubble Map.
- Menghapus kolom **STRATEGY** dan seluruh logika deteksinya:
  `gmgn_liquidity.row_strategy`, `strategy_for_liquidity`,
  `row_total_liquidity_usd`, konstanta `STRATEGY_LIQ_HIGH` / `STRATEGY_LIQ_LOW` /
  `STRATEGY_DIVIDEND`, sel `best_pool_ui._strategy_cell(_html)`, dan CSS
  `.bp-strategy-range`. Ambang $500K kembali hanya mengatur warna angka
  likuiditas kolom RugCheck. Kolom **TAX/DIVIDEND** tetap ada (informasi) dan
  kini menjadi kolom paling kanan tabel utama.
- Memindahkan kolom **Token:SOL** ke kanan **LPs** (indeks 6) dan membulatkan
  labelnya menjadi **1 angka di belakang koma** (`1:6.5`; nol di ekor dipangkas
  sehingga rasio bulat tetap `1:2`). Teks alasan gugur dan tooltip sel memakai
  `liquidity_distribution_label(row, decimals=4)` agar rasio dekat boundary
  (`1:1.9996`) tidak terbaca kontradiktif.
- Jumlah kolom: tabel utama **15**, tabel "▶ N pool dilewati" **14**
  (tanpa TAX/DIVIDEND). Lebar `nth-child` CSS disesuaikan; tabel tetap satu
  tabel utuh yang digeser horizontal di ponsel.

## 2026-09-26 — penyederhanaan aplikasi

- Menghapus seluruh wallet-depth Holder subsystem:
  - halaman dan UI scan
  - analisis, history, chronology, status, dan store JSON
  - scanner terjadwal, workflow, dan cron artifacts
  - Telegram/alert settings/context
  - tautan dan routing internal Holder
  - enrichment Holder dari Best Pool
- Menghapus halaman TEMP beserta Watchlist Meteora dan Scan Holder UI.
- Menghapus modul lama yang bergantung pada store Holder/TEMP, termasuk LP watchlist detail dan pre-pump/accumulation surfaces.
- Mempertahankan `watchlist.py`, Helius request infrastructure, dan CVD tooling yang masih independen dari Holder.
- Mengubah Best Pool menjadi pipeline pool/market saja: cheap gates → official Meteora distribution gate → optional GMGN/RugCheck/tax.
- Menghapus dust-derived sorting/output dan progress Holder dari Best Pool.
- Memperbaiki tampilan ponsel: semua 15 kolom dan header Best Pool tetap ada dalam baris ringkas yang dapat digeser horizontal; tidak ada card wrapping atau kolom tersembunyi.

## Best Pool distribution rule

- Active TVL minimum: **$100K**.
- LP minimum: **100**.
- Tidak ada POOL BARU atau jalur lolos alternatif.
- Gate distribusi adalah filter terakhir setelah semua cheap checks.
- Aturan batas rasio ini **dihapus total pada 2026-09-28**: token:SOL kini
  murni informasi, berapa pun rasionya tidak pernah menggugurkan pool.
- Nilai berasal dari official Meteora pool details: amount × USD price.
