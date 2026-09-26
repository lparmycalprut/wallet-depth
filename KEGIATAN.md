# Kegiatan

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
- Nilai USD SOL harus **≥ 2×** nilai USD token.
- token:SOL **1:2 lolos**, **1:6.52 lolos**, **1:1.5 gagal**.
- Nilai berasal dari official Meteora pool details: amount × USD price.
