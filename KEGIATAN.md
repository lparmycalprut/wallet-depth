# Kegiatan

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
