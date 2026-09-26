# Kegiatan

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
- Nilai USD SOL harus **≥ 5×** nilai USD token.
- token:SOL **1:5 lolos**, **1:6.52 lolos**, **1:4 gagal**.
- Nilai berasal dari official Meteora pool details: amount × USD price.
