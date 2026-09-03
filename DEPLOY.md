# Deploy

## Streamlit

- Entry point: `app.py`
- Python: lihat `runtime.txt`
- Dependencies: `requirements.txt`
- Opsional secrets: `HELIUS_API_KEY`, `HELIUS_API_KEYS`, `GITHUB_TOKEN`.
- Opsional: `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` untuk mengaktifkan
  alert dump / kemungkinan akumulasi. Simpan keduanya sebagai GitHub Actions
  secrets (buat bot lewat BotFather, lalu tambahkan bot ke chat/channel).

Watchlist di halaman utama menarik `holder_status.json` dari ref
`holder-live` (bukan commit `main`). Tombol **Scan holder watchlist**
menjalankan analisis holder lokal. Chart 📈 membuka halaman CVD.

## GitHub Actions

Workflow `.github/workflows/daily-effort.yml` ("Holder Dust Scanner")
berjalan setiap 15 menit dan memanggil `python scripts/scan_holders.py`.

Langkah setelah scan:

1. Analisis per token: holder Helius DAS (fallback GMGN, max 3000
   wallet), klasifikasi real (>$10) vs dust, dust % MC, mid-tier, kohort.
2. Publish snapshot `holder_status.json` ke branch `holder-live`
   (dibuat otomatis pada publish pertama) agar dashboard Streamlit
   membaca data yang sama dengan cron tanpa commit ke `main`.

   **Wajib di workflow**:

   ```yaml
   permissions:
     contents: write
   ```

   dan env step scan harus diberi token + key Helius, kalau tidak
   publish gagal dan watchlist di dashboard kosong (`—`):

   ```yaml
   env:
     GITHUB_TOKEN: ${{ secrets.GH_TOKEN || secrets.GITHUB_TOKEN }}
     HELIUS_API_KEY: ${{ secrets.HELIUS_API_KEY }}
   ```

   Secret repo yang perlu diset: **`HELIUS_API_KEY`** (wajib — GMGN
   diblokir dari runner Actions) dan opsional `GH_TOKEN` (PAT) bila
   token bawaan tidak cukup. Scanner exit non-zero (run merah) bila
   semua token 0 holder atau publish gagal.

> GitHub App tidak bisa mengubah file workflow (butuh permission
> `workflows`) — perubahan workflow harus di-commit manual oleh pemilik
> repo.

Jalankan manual lewat **Actions → Holder Dust Scanner → Run workflow**.
