# Deploy

## Streamlit

- Entry point: `app.py`
- Python: lihat `runtime.txt`
- Dependencies: `requirements.txt`
- Opsional secrets: `HELIUS_API_KEY`, `HELIUS_API_KEYS`, `GITHUB_TOKEN`.
- **Tidak ada** `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — Telegram sudah
  dihapus.

Watchlist di halaman utama menarik `silent_status.json` dari ref
`silent-live` (bukan commit `main`). Tombol **Scan watchlist sekarang**
menjalankan analisis lokal 12 jam + holder depth. Chart 📈 membuka halaman
CVD historic (tanpa sinyal).

## GitHub Actions

Workflow `.github/workflows/daily-effort.yml` berjalan setiap 15 menit
(`*/15 * * * *`) dan menjalankan `python scripts/scan_silent.py` — scan
silent-accumulation 12 jam + holder dust untuk seluruh watchlist.

Langkah setelah scan:

1. Analisis per token: holder GMGN (paginasi, max 3000 wallet), net flow
   12 jam (max 8 halaman trade), klasifikasi real (>$10) vs dust.
2. Publish snapshot `silent_status.json` ke branch `silent-live`
   (dibuat otomatis pada publish pertama) agar dashboard Streamlit
   membaca data yang sama dengan cron tanpa commit ke `main`.

   **Wajib di workflow**:

   ```yaml
   permissions:
     contents: write
   ```

3. Tidak ada kirim Telegram.

Jalankan manual lewat **Actions → Silent Accumulation 12H Scanner → Run
workflow**.
