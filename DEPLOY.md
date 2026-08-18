# Deploy

## Streamlit

- Entry point: `app.py`
- Python: lihat `runtime.txt`
- Dependencies: `requirements.txt`
- Opsional secrets: `HELIUS_API_KEY`, `HELIUS_API_KEYS`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, dan `GITHUB_TOKEN`.

Watchlist di halaman utama menarik `reversal_status.json` dari ref
`reversal-live` (bukan candle harian). Tombol **Muat ulang status**
memaksa pull baru. Chart 📈 masih membuka halaman CVD historis.

## GitHub Actions

Workflow `.github/workflows/daily-effort.yml` berjalan setiap 10 menit
(`*/10 * * * *`) dan memindai reversal rolling 6 jam vs 24 jam sebelumnya.

Langkah setelah scan:

1. Simpan state transisi di `last_scan_result.json` + cache trade (Actions cache).
2. Publish snapshot `reversal_status.json` ke branch `reversal-live`
   agar dashboard Streamlit melihat sinyal yang sama dengan Telegram
   tanpa commit ke `main`.

   **Wajib di workflow** (satu baris; belum bisa diubah lewat PR ini
   karena token App tidak punya izin `workflows`):

   ```yaml
   permissions:
     contents: write   # sekarang masih `read` — tanpa ini snapshot gagal
   ```
3. Kirim Telegram hanya pada transisi `REVERSAL_UP` / `REVERSAL_DOWN`.

Jalankan manual lewat **Actions → Realtime Bidirectional Reversal → Run
workflow**. Branch `reversal-live` dibuat otomatis pada publish pertama.
